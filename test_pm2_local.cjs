'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { supervise } = require('./pm2_monitor.cjs');
const { control } = require('./pm2-local.cjs');
const ecosystem = require('./ecosystem.config.cjs').apps[0];

function fixture(t, { earlyStop = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mercari-pm2-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const python = path.join(root, '.venv', 'Scripts', 'python.exe');
  fs.mkdirSync(path.dirname(python), { recursive: true });
  fs.writeFileSync(python, '');
  const marker = path.join(root, '.state', 'local-monitor', 'stop.request');
  const child = new EventEmitter();
  const host = new EventEmitter();
  host.pid = 456;
  const exits = [];
  const logs = [];
  let tick;
  let cancelled = false;
  supervise({ root, host, finish: code => exits.push(code), log: line => logs.push(line),
    every: callback => { tick = callback; return 1; }, cancel: () => { cancelled = true; },
    spawnChild: (file, args, options) => {
      assert.equal(file, python);
      assert.deepEqual(args, ['-X', 'utf8', '-u', path.join(root, 'local_monitor.py'), '--managed-local']);
      assert.equal(options.windowsHide, true);
      assert.equal(options.cwd, root);
      if (earlyStop) host.emit('message', 'shutdown');
      return child;
    },
  });
  return { root, marker, child, host, exits, logs, tick: () => tick(), cancelled: () => cancelled };
}

test('shutdown IPC survives Python clearing the marker under its startup lock and waits for child close', t => {
  const f = fixture(t, { earlyStop: true });
  assert.equal(fs.existsSync(f.marker), true);
  fs.unlinkSync(f.marker); // Simulate Python clearing the stale marker.
  f.tick();
  assert.equal(fs.existsSync(f.marker), true);
  f.host.emit('SIGINT'); // Repeated stop is harmless.
  assert.deepEqual(f.exits, []); // No early supervisor exit or child kill.
  f.child.emit('close', 0, null);
  assert.deepEqual(f.exits, [0]);
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.root, '.state', 'pm2', 'exit.json'), 'utf8')).pid, 456);
  assert.equal(f.cancelled(), true);
  assert.equal(f.host.listenerCount('message'), 0);
});

test('SIGTERM and direct stop markers suppress autorestart on interrupted/nonzero handback', t => {
  for (const stop of ['signal', 'marker']) {
    const f = fixture(t);
    if (stop === 'signal') f.host.emit('SIGTERM');
    else {
      fs.mkdirSync(path.dirname(f.marker), { recursive: true });
      fs.writeFileSync(f.marker, '');
    }
    f.child.emit('close', 1, null);
    assert.deepEqual(f.exits, [78]);
    assert.match(f.logs.join('\n'), /--resume-cloud/);
  }
});

test('managed intentional/recovery exits stop; unexpected child failures remain retryable', t => {
  for (const [code, signal, expected] of [[0, null, 0], [78, null, 78], [1, null, 1], [null, 'SIGKILL', 1]]) {
    const f = fixture(t);
    f.child.emit('close', code, signal);
    assert.deepEqual(f.exits, [expected]);
    assert.equal(ecosystem.stop_exit_codes.includes(expected), expected !== 1);
  }
  const f = fixture(t);
  f.child.emit('error', new Error('fake spawn failure'));
  f.child.emit('close', -1, null);
  assert.deepEqual(f.exits, [78]); // One completion even after error + close.
});

function apiFixture(t, { status = 'online', exitCode = 0, stopExit = 0, collision = false, absent = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mercari-control-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const script = path.join(root, 'pm2_monitor.cjs');
  fs.writeFileSync(script, '');
  const config = { ...ecosystem, cwd: root, script };
  const app = { name: 'mercari-watch', pm_id: 7, pid: 123, pm2_env: {
    pm_exec_path: collision ? __filename : script, pm_cwd: root, status, exit_code: exitCode, pm_uptime: Date.now() - 1000,
  } };
  const calls = [];
  let disconnected = false;
  const pm2 = {
    connect: callback => callback(null),
    describe: (name, callback) => { assert.equal(name, 'mercari-watch'); callback(null, absent ? [] : [app]); },
    stop: (id, callback) => {
      calls.push(['stop', id]); app.pm2_env.status = 'stopped'; app.pm2_env.exit_code = stopExit;
      fs.mkdirSync(path.join(root, '.state', 'pm2'), { recursive: true });
      fs.writeFileSync(path.join(root, '.state', 'pm2', 'exit.json'), JSON.stringify({ pid: 123, started_at: Date.now(), code: stopExit }));
      callback(null);
    },
    start: (target, callback) => {
      assert.ok(typeof target === 'object' || typeof target === 'string');
      calls.push(['start', target]); callback(null);
    },
    disconnect: () => { disconnected = true; },
  };
  return { pm2, config, calls, disconnected: () => disconnected, log: () => {} };
}

test('healthy repeated start and status do not mutate PM2; new start targets only this config', async t => {
  for (const action of ['start', 'status']) {
    const f = apiFixture(t);
    await control(action, f);
    assert.deepEqual(f.calls, []);
    assert.equal(f.disconnected(), true);
  }
  const f = apiFixture(t, { absent: true });
  await control('start', f);
  assert.deepEqual(f.calls, [['start', f.config]]);
  assert.equal(f.disconnected(), true);
});

test('workspace/script collision refuses every action and disconnects', async t => {
  for (const action of ['start', 'stop', 'restart', 'status']) {
    const f = apiFixture(t, { collision: true });
    await assert.rejects(control(action, f), /name collision/);
    assert.deepEqual(f.calls, []);
    assert.equal(f.disconnected(), true);
  }
});

test('restart waits for a clean stop and never starts after failed handback', async t => {
  const clean = apiFixture(t);
  await control('restart', clean);
  assert.deepEqual(clean.calls, [['stop', 7], ['start', '7']]);
  for (const action of ['restart', 'stop']) {
    const failed = apiFixture(t, { stopExit: 78 });
    await assert.rejects(control(action, failed), /--resume-cloud/);
    assert.deepEqual(failed.calls, [['stop', 7]]);
    assert.equal(failed.disconnected(), true);
  }
});

test('manual start can resume an intentional stop even if PM2 labels it waiting restart', async t => {
  const f = apiFixture(t, { status: 'waiting restart', exitCode: 0 });
  await control('start', f);
  assert.deepEqual(f.calls, [['start', '7']]);
  const pending = apiFixture(t, { status: 'waiting restart', exitCode: 1 });
  await control('start', pending);
  assert.deepEqual(pending.calls, []);
});

test('API connection is disconnected on errors without exposing raw provider data', async t => {
  const f = apiFixture(t);
  f.pm2.describe = (name, callback) => callback(new Error('private environment fixture'));
  await assert.rejects(control('status', f), error => !error.message.includes('private environment fixture'));
  assert.equal(f.disconnected(), true);
});

test('restart refuses stale PM2 exit=0 without proof that this Python generation completed', async t => {
  const f = apiFixture(t);
  f.pm2.stop = (id, callback) => { f.calls.push(['stop', id]); callback(null); };
  await assert.rejects(control('restart', f), /clean handback was not confirmed/);
  assert.deepEqual(f.calls, [['stop', 7]]);
  assert.equal(f.disconnected(), true);
});
