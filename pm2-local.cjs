'use strict';

const fs = require('node:fs');
const path = require('node:path');
const ecosystem = require('./ecosystem.config.cjs');
const APP = 'mercari-watch';

function loadPM2() {
  try { return require('pm2'); } catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND') throw new Error('Existing PM2 module could not load.');
  }
  const directories = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  if (process.env.APPDATA) directories.push(path.join(process.env.APPDATA, 'npm'));
  for (const directory of directories) {
    // npm on Windows keeps pm2 beside its shim; Unix globals use ../lib.
    for (const candidate of [path.join(directory, 'node_modules', 'pm2'),
      path.resolve(directory, '..', 'lib', 'node_modules', 'pm2')]) {
      if (!fs.existsSync(path.join(candidate, 'package.json'))) continue;
      try { return require(candidate); } catch { throw new Error('Existing PM2 module could not load.'); }
    }
  }
  throw new Error('Existing PM2 installation not found on Node search paths, PATH, or APPDATA/npm; no installation was attempted.');
}

const call = (pm2, method, ...args) => new Promise((resolve, reject) => {
  pm2[method](...args, (error, value) => error ? reject(new Error(`PM2 ${method} failed; inspect the app logs.`)) : resolve(value));
});

function samePath(left, right) {
  if (!left || !right) return false;
  const normalize = value => {
    const resolved = fs.realpathSync(value);
    return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
  };
  try { return normalize(left) === normalize(right); } catch { return false; }
}

async function control(action, { pm2 = loadPM2(), config = ecosystem.apps[0], log = console.log } = {}) {
  if (!['start', 'stop', 'restart', 'status'].includes(action)) throw new Error('Usage: node pm2-local.cjs start|stop|restart|status');
  const describe = async () => {
    const apps = await call(pm2, 'describe', APP);
    // Read only identity/lifecycle metadata; never print PM2's env or jlist.
    if (apps.length > 1 || apps.some(app => app.name !== APP || !Number.isInteger(app.pm_id) || app.pm_id < 0
      || !samePath(app.pm2_env?.pm_exec_path, config.script)
      || !samePath(app.pm2_env?.pm_cwd, config.cwd))) {
      throw new Error('mercari-watch name collision: script/workspace differs; no app was changed.');
    }
    return apps[0];
  };
  try {
    await call(pm2, 'connect');
    let app = await describe();
    if (action === 'status') {
      log(app ? `${APP}: ${app.pm2_env.status}, pid=${app.pid || 0}, restarts=${app.pm2_env.restart_time || 0}, exit=${app.pm2_env.exit_code ?? 'none'}` : `${APP}: not registered`);
      return;
    }
    if (action === 'stop' || action === 'restart') {
      if (app) {
        const expectedPid = app.pid;
        const expectedUptime = app.pm2_env.pm_uptime;
        log('Waiting for the active scan and encrypted cloud handback (up to 30 minutes)…');
        await call(pm2, 'stop', app.pm_id);
        app = await describe();
        let receipt;
        try {
          receipt = JSON.parse(fs.readFileSync(path.join(config.cwd, '.state', 'pm2', 'exit.json'), 'utf8'));
        } catch { /* Missing/invalid completion proof requires manual recovery. */ }
        if (!app || receipt?.code !== 0 || !Number.isFinite(expectedUptime)
          || !(receipt.started_at >= expectedUptime) || (expectedPid > 0 && receipt.pid !== expectedPid)) {
          throw new Error('Service stopped: clean handback was not confirmed; inspect logs/status and use start-local.cmd --resume-cloud before starting.');
        }
      }
      if (action === 'stop') { log(`${APP}: stopped; check logs/status for handback outcome.`); return; }
    }
    if (app && (['online', 'launching'].includes(app.pm2_env.status)
      || (app.pm2_env.status === 'waiting restart' && ![0, 78].includes(app.pm2_env.exit_code)))) {
      log(`${APP}: ${app.pm2_env.status}; existing service retained.`);
      return;
    }
    if (app?.pm2_env.status === 'stopping') throw new Error('mercari-watch is still handing back; wait for stop to complete.');
    fs.mkdirSync(path.join(config.cwd, '.state', 'pm2'), { recursive: true });
    // PM2 start treats its input as a script/name string before resolving IDs.
    if (app) await call(pm2, 'start', String(app.pm_id));
    else await call(pm2, 'start', config);
    log(`${APP}: start requested; check status and logs for ownership/scan readiness.`);
  } finally {
    pm2.disconnect();
  }
}

if (require.main === module) {
  control(process.argv[2]).catch(error => { console.error(error.message); process.exitCode = 1; });
}
module.exports = { control, samePath };
