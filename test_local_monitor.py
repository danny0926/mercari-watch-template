import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet, InvalidToken

import local_monitor as local
from handoff_state import join_payload, read_state, unpack_states, write_state


class FakeGitHub:
    repository = "example/example"

    def __init__(self, enabled=True):
        self.values = {"MONITOR_ENABLED": str(enabled).lower(), "LOCAL_MONITOR_ACTIVE": "false"}
        self.events, self.secrets = [], {}

    def flags(self):
        return dict(self.values)

    def flag(self, name, value):
        self.events.append((name, value))
        self.values[name] = value

    def active(self, _):
        return []

    def dispatch(self, workflow, **_):
        self.events.append(("dispatch", workflow))

    def call(self, *arguments, input=None, **_):
        if arguments[:2] == ("secret", "set"):
            self.secrets[arguments[2]] = input
        elif arguments[:2] == ("secret", "delete"):
            self.secrets.pop(arguments[2], None)


class LocalMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Fernet.generate_key().decode()
        self.gh = FakeGitHub()
        self.monitor = local.LocalMonitor(self.gh, self.key, root=Path(self.tmp.name))
        self.fail_import = False
        self.imported = None

    def transfer(self, mode):
        self.assertEqual(self.gh.values, {"MONITOR_ENABLED": "false", "LOCAL_MONITOR_ACTIVE": "true"})
        self.gh.events.append(("transfer", mode))
        if mode == "import":
            if self.fail_import:
                raise local.HandoffError("example import failure")
            self.imported = unpack_states(join_payload(self.gh.secrets), self.monitor.claim["session"], self.key)
        return 123

    def download(self, _):
        self.gh.events.append(("download", "verified"))
        for slot, path in self.monitor.paths().items():
            write_state(path, self.key, {"_known": [f"example-{slot}"]})
        self.monitor.save(states_ready=True, phase="local")

    def run_local(self, **options):
        with patch.object(self.monitor, "preflight"), patch.object(self.monitor, "transfer", self.transfer), \
                patch.object(self.monitor, "download", self.download), contextlib.redirect_stdout(io.StringIO()):
            return self.monitor.start(**options)

    def test_local_scan_starts_after_export_and_cloud_resumes_after_import(self):
        def scan():
            self.gh.events.append(("scan", "local"))
            self.assertEqual(self.gh.values["MONITOR_ENABLED"], "false")
            path = self.monitor.paths()["core"]
            write_state(path, self.key, {"_known": ["example-new"]})
            return 0
        with patch.object(self.monitor, "cycle", scan):
            self.assertEqual(self.run_local(once=True), 0)
        events = self.gh.events
        self.assertLess(events.index(("transfer", "export")), events.index(("scan", "local")))
        self.assertLess(events.index(("transfer", "import")), events.index(("LOCAL_MONITOR_ACTIVE", "false")))
        self.assertEqual(self.imported["core"]["_known"], ["example-new"])
        self.assertEqual(self.monitor.previous()["phase"], "cloud")
        self.assertEqual(self.gh.values["MONITOR_ENABLED"], "true")

    def test_failed_import_preserves_pause_and_recovery_uses_latest_saved_history(self):
        self.fail_import = True
        with self.assertRaises(local.HandoffError):
            self.run_local(handoff_only=True)
        self.assertEqual(self.gh.values, {"MONITOR_ENABLED": "false", "LOCAL_MONITOR_ACTIVE": "true"})
        self.assertNotEqual(self.monitor.previous()["phase"], "cloud")
        path = self.monitor.paths()["core"]
        write_state(path, self.key, {"_known": ["example-recovered"]})
        self.fail_import = False
        with patch.object(self.monitor, "transfer", self.transfer), contextlib.redirect_stdout(io.StringIO()):
            self.monitor.recover()
        self.assertEqual(self.imported["core"]["_known"], ["example-recovered"])
        self.assertEqual(self.gh.values["MONITOR_ENABLED"], "true")

    def test_startup_failure_rolls_back_without_uploading_stale_local_files(self):
        with patch.object(self.monitor, "preflight"), \
                patch.object(self.monitor, "transfer", side_effect=local.HandoffError("example export failure")), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(local.HandoffError):
            self.monitor.start(handoff_only=True)
        self.assertEqual(self.gh.values["MONITOR_ENABLED"], "true")
        self.assertEqual(self.gh.values["LOCAL_MONITOR_ACTIVE"], "false")
        self.assertIsNone(self.imported)

    def test_previously_disabled_cloud_stays_disabled_and_handoff_only_never_scans(self):
        self.gh.values["MONITOR_ENABLED"] = "false"
        with patch.object(self.monitor, "cycle") as scan:
            self.run_local(handoff_only=True)
            scan.assert_not_called()
        self.assertEqual(self.gh.values["MONITOR_ENABLED"], "false")
        self.assertNotIn(("dispatch", "monitor-clock.yml"), self.gh.events)

    def test_source_groups_use_separate_histories_and_restore_application_settings(self):
        self.run_local(handoff_only=True)
        observed = []
        previous = local.app.SEEN
        async def check(*, only_sources):
            observed.append((local.app.SEEN, only_sources))
            self.assertEqual(os.environ["MONITOR_STATE_PATH"], str(local.app.SEEN))
            return 0
        with patch.object(local.app, "check_once", AsyncMock(side_effect=check)):
            self.assertEqual(self.monitor.cycle(), 0)
        self.assertEqual([path.name for path, _ in observed], ["core.enc", "surugaya.enc"])
        self.assertEqual(observed[1][1], ["surugaya"])
        self.assertEqual(local.app.SEEN, previous)

    def test_duplicate_local_launcher_cannot_take_ownership(self):
        lock = Path(self.tmp.name) / "launcher.lock"
        with local.LocalLock(lock):
            with self.assertRaises(local.HandoffError):
                with local.LocalLock(lock):
                    self.fail("duplicate process lock acquired")

    def test_background_stop_request_interrupts_idle_wait(self):
        (self.monitor.root / "stop.request").touch()
        self.assertTrue(self.monitor.wait_for_next_cycle())
        self.assertTrue(self.monitor.stop.is_set())

    def test_maintenance_restart_keeps_existing_histories_and_cloud_pause(self):
        self.run_local(handoff_only=True)
        self.monitor.save(phase="local")
        self.gh.values.update(MONITOR_ENABLED="false", LOCAL_MONITOR_ACTIVE="true")
        self.gh.events.clear()
        self.monitor.interval = 300
        def run():
            self.assertEqual(self.gh.values["MONITOR_ENABLED"], "false")
            self.assertEqual(read_state(self.monitor.paths()["core"], self.key)["_known"], ["example-core"])
            self.assertEqual(self.monitor.interval, 300)
            self.assertEqual(self.gh.events, [])
            return 0
        with patch.object(self.monitor, "preflight"), patch.object(self.monitor, "run_local", run), \
                patch.object(self.monitor, "restore") as restore:
            self.assertEqual(self.monitor.continue_local(), 0)
            restore.assert_called_once()
        self.gh.values["MONITOR_ENABLED"] = "true"
        with patch.object(self.monitor, "preflight"), patch.object(self.monitor, "run_local") as run, \
                self.assertRaises(local.HandoffError):
            self.monitor.continue_local()
        run.assert_not_called()

    def test_managed_start_selects_existing_routes_and_rejects_transfer_phases(self):
        for phase, expected in ((None, "start"), ("cloud", "start"), ("local", "continue_local")):
            with self.subTest(phase=phase), \
                    patch.object(self.monitor, "previous", return_value={"phase": phase} if phase else None), \
                    patch.object(self.monitor, "start", return_value=0) as start, \
                    patch.object(self.monitor, "continue_local", return_value=0) as resume:
                self.assertEqual(self.monitor.managed_local(), 0)
                self.assertEqual(start.call_count, int(expected == "start"))
                self.assertEqual(resume.call_count, int(expected == "continue_local"))
        for phase in ("pausing", "exporting", "importing", "imported", "starting-cloud", "unknown"):
            with self.subTest(phase=phase), patch.object(self.monitor, "previous", return_value={"phase": phase}), \
                    patch.object(self.monitor, "start") as start, \
                    patch.object(self.monitor, "continue_local") as resume, \
                    self.assertRaisesRegex(local.HandoffError, "--resume-cloud"):
                self.monitor.managed_local()
            start.assert_not_called()
            resume.assert_not_called()

    def test_managed_marker_stop_after_source_error_hands_back_without_restart_exit(self):
        self.run_local(handoff_only=True)
        self.monitor.save(phase="local")
        self.gh.values.update(MONITOR_ENABLED="false", LOCAL_MONITOR_ACTIVE="true")
        self.gh.events.clear()
        def failed_scan():
            (self.monitor.root / "stop.request").touch()
            return 1
        with patch.object(self.monitor, "preflight"), patch.object(self.monitor, "cycle", failed_scan), \
                patch.object(self.monitor, "transfer", self.transfer), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.monitor.managed_local(), 0)
        self.assertEqual(self.monitor.previous()["phase"], "cloud")
        self.assertEqual(self.monitor.previous()["last_cycle_errors"], 1)
        self.assertNotIn(("transfer", "export"), self.gh.events)
        self.assertEqual(self.gh.values["MONITOR_ENABLED"], "true")

    def test_managed_continuation_keeps_encryption_and_ownership_checks(self):
        self.run_local(handoff_only=True)
        self.monitor.save(phase="local")
        with patch.object(self.monitor, "preflight"), patch.object(self.monitor, "run_local") as run:
            with self.assertRaises(local.HandoffError):
                self.monitor.managed_local()  # Cloud flags still say cloud.
            self.gh.values.update(MONITOR_ENABLED="false", LOCAL_MONITOR_ACTIVE="true")
            write_state(self.monitor.paths()["core"], Fernet.generate_key().decode(), {})
            with self.assertRaises(InvalidToken):
                self.monitor.managed_local()  # Wrong key must not start a scan.
            run.assert_not_called()

    def test_managed_import_failure_still_requires_explicit_recovery(self):
        self.run_local(handoff_only=True)
        self.monitor.save(phase="local")
        self.gh.values.update(MONITOR_ENABLED="false", LOCAL_MONITOR_ACTIVE="true")
        self.fail_import = True
        (self.monitor.root / "stop.request").touch()
        with patch.object(self.monitor, "preflight"), patch.object(self.monitor, "transfer", self.transfer), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(local.HandoffError):
            self.monitor.managed_local()
        self.assertEqual(self.monitor.previous()["phase"], "importing")
        self.assertEqual(self.gh.values["LOCAL_MONITOR_ACTIVE"], "true")

    def test_cli_managed_route_is_under_existing_lock_and_errors_do_not_restart(self):
        def managed():
            self.assertFalse((self.monitor.root / "stop.request").exists())
            with self.assertRaises(local.HandoffError):
                with local.LocalLock(self.monitor.root / "launcher.lock"):
                    self.fail("managed routing escaped LocalLock")
            return 0
        (self.monitor.root / "stop.request").touch()
        with patch("sys.argv", ["local_monitor.py", "--managed-local"]), \
                patch.object(local, "ROOT", self.monitor.root), patch.object(local, "load_dotenv"), \
                patch.object(local, "GitHub", return_value=self.gh), \
                patch.object(local, "LocalMonitor", return_value=self.monitor), \
                patch.object(local.signal, "signal"), patch.object(self.monitor, "managed_local", side_effect=managed):
            self.assertEqual(local.main(), 0)
            with patch.object(self.monitor, "managed_local", side_effect=local.HandoffError("interrupted handback")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(local.main(), 78)

    def test_managed_mode_is_mutually_exclusive_with_one_off_modes(self):
        with patch("sys.argv", ["local_monitor.py", "--managed-local", "--once"]), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            local.main()
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
