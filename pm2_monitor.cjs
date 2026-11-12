'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const RECOVERY_REQUIRED = 78;
const RECOVERY = 'Monitor stopped; check status and run start-local.cmd --resume-cloud before starting again if handback is incomplete.';

// This owns only a Python child and stop.request. Python owns all monitoring,
// locking, encrypted history, and local/cloud transfer decisions.
function supervise({ root = __dirname, spawnChild = spawn, host = process,
  files = fs, every = setInterval, cancel = clearInterval,
  finish = code => { process.exitCode = code; if (process.connected) process.disconnect(); },
  log = message => console.error(message), markerInterval = 200 } = {}) {
  const marker = path.join(root, '.state', 'local-monitor', 'stop.request');
  const startedAt = Date.now();
  let stopping = false;
  let finished = false;
  let timer;
  let markerFailed = false;
  const preserveStop = () => {
    try {
      files.mkdirSync(path.dirname(marker), { recursive: true });
      files.closeSync(files.openSync(marker, 'a'));
    } catch {
      if (!markerFailed) log('Cannot preserve stop.request; keep the service alive until Python completes or repair directory permissions.');
      markerFailed = true;
    }
  };
  const stop = () => {
    if (finished) return;
    stopping = true;
    preserveStop();
    // Python clears a stale marker after acquiring LocalLock. Keep requesting
    // stop through that startup race, then wait without signaling/killing it.
    if (!timer) timer = every(preserveStop, markerInterval);
  };
  const message = value => { if (value === 'shutdown') stop(); };
  host.on('message', message);
  host.on('SIGINT', stop);
  host.on('SIGTERM', stop);

  const complete = (code, signal, spawnError = false) => {
    if (finished) return;
    finished = true;
    if (timer) cancel(timer);
    host.removeListener('message', message);
    host.removeListener('SIGINT', stop);
    host.removeListener('SIGTERM', stop);
    const requested = stopping || files.existsSync(marker);
    // Managed Python returns 0 only after a successful planned handback,
    // regardless of the previous cycle's source errors. Never turn an
    // interrupted requested stop into an automatic restart.
    const result = code === 0 && !signal && !spawnError ? 0
      : code === RECOVERY_REQUIRED || requested || spawnError ? RECOVERY_REQUIRED : 1;
    // PM2's stop callback can precede its exit metadata update. Record proof
    // for this supervisor generation so restart cannot trust a stale exit=0
    // after PM2 times out and forcibly ends the supervisor.
    try {
      const directory = path.join(root, '.state', 'pm2');
      files.mkdirSync(directory, { recursive: true });
      const temporary = path.join(directory, `exit-${host.pid}.tmp`);
      files.writeFileSync(temporary, JSON.stringify({ pid: host.pid, started_at: startedAt, code: result }));
      files.renameSync(temporary, path.join(directory, 'exit.json'));
    } catch {
      log('Could not record supervisor completion; restart must confirm recovery manually.');
    }
    if (result === RECOVERY_REQUIRED) log(RECOVERY);
    else if (result) log('Python exited unexpectedly; PM2 may retry with bounded startup backoff.');
    finish(result);
  };

  const windowsPython = path.join(root, '.venv', 'Scripts', 'python.exe');
  const python = files.existsSync(windowsPython) ? windowsPython : path.join(root, '.venv', 'bin', 'python');
  if (!files.existsSync(python)) {
    log('Project .venv Python is missing; restore the existing project environment before starting.');
    complete(null, null, true);
    return { stop };
  }
  try {
    const child = spawnChild(python, ['-X', 'utf8', '-u', path.join(root, 'local_monitor.py'), '--managed-local'], {
      cwd: root, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'],
    });
    child.once('error', () => complete(null, null, true));
    // close waits for the child and its inherited output to finish.
    child.once('close', (code, signal) => complete(code, signal));
  } catch {
    complete(null, null, true);
  }
  return { stop };
}

if (require.main === module) supervise();
module.exports = { supervise, RECOVERY_REQUIRED };
