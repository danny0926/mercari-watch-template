const path = require('node:path');

module.exports = {
  apps: [{
    name: 'mercari-watch',
    cwd: __dirname,
    script: path.join(__dirname, 'pm2_monitor.cjs'),
    interpreter: process.execPath,
    exec_mode: 'fork',
    instances: 1,
    watch: false,
    windowsHide: true,
    shutdown_with_message: true,
    // Finish the active scan and the existing 900-second encrypted handback.
    kill_timeout: 30 * 60 * 1000,
    autorestart: true,
    stop_exit_codes: [0, 78],
    min_uptime: '10m',
    max_restarts: 5,
    exp_backoff_restart_delay: 3000,
    out_file: path.join(__dirname, '.state', 'pm2', 'out.log'),
    error_file: path.join(__dirname, '.state', 'pm2', 'error.log'),
    merge_logs: true,
    time: true,
    // Private settings are loaded by Python from the project's .env.
  }],
};
