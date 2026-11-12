import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import browser_runtime as browser


class BrowserRuntimeTests(unittest.TestCase):
    def test_crashing_packaged_node_reuses_working_patchright_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            packages = {}
            for package in ("playwright", "patchright"):
                base = Path(temporary) / package
                (base / "driver").mkdir(parents=True)
                (base / "driver/node.exe").touch()
                packages[package] = SimpleNamespace(origin=str(base / "__init__.py"))
            crashed = SimpleNamespace(returncode=0xC0000005, stdout=b"")
            healthy = SimpleNamespace(returncode=0, stdout=b"v24.22.1\n")
            browser._windows_driver_runtime.cache_clear()
            self.addCleanup(browser._windows_driver_runtime.cache_clear)
            with patch.object(browser.importlib.util, "find_spec", side_effect=packages.get), \
                    patch.object(browser.subprocess, "run", side_effect=[crashed, healthy]) as run, \
                    patch.object(browser.sys, "platform", "win32"), patch.dict(os.environ, {}, clear=True):
                browser.configure_browser_driver()
                self.assertEqual(os.environ["PLAYWRIGHT_NODEJS_PATH"], str(Path(temporary) / "patchright/driver/node.exe"))
                browser.configure_browser_driver()
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args.kwargs["timeout"], 5)
                self.assertNotIn("WATCHLIST_JSON", run.call_args.kwargs["env"])

    def test_explicit_driver_is_preserved_and_missing_runtimes_fail_closed(self):
        with patch.object(browser.sys, "platform", "win32"), \
                patch.dict(os.environ, {"PLAYWRIGHT_NODEJS_PATH": "explicit-node"}, clear=True), \
                patch.object(browser, "_windows_driver_runtime") as lookup:
            browser.configure_browser_driver()
            lookup.assert_not_called()
            self.assertEqual(os.environ["PLAYWRIGHT_NODEJS_PATH"], "explicit-node")
        browser._windows_driver_runtime.cache_clear()
        self.addCleanup(browser._windows_driver_runtime.cache_clear)
        with patch.object(browser.importlib.util, "find_spec", return_value=None), self.assertRaises(ValueError):
            browser._windows_driver_runtime()

    def test_windows_without_stock_cache_uses_existing_edge_channel(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(browser.sys, "platform", "win32"):
            executable = Path(temporary) / "chrome.exe"
            chromium = SimpleNamespace(executable_path=str(executable))
            self.assertEqual(browser.stock_browser_channel(chromium), "msedge")
            executable.touch()
            self.assertEqual(browser.stock_browser_channel(chromium), "chromium")
            executable.unlink()
            with patch.object(browser.sys, "platform", "linux"):
                self.assertEqual(browser.stock_browser_channel(chromium), "chromium")

    def test_browser_paths_stay_in_project_and_updates_are_frozen(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(browser, "PROJECT", Path(temporary)), \
                patch.dict(os.environ, {}, clear=True):
            environment = browser.cloak_environment()
            for name in ("CLOAKBROWSER_CACHE_DIR", "TEMP", "TMP", "TMPDIR", "PIP_CACHE_DIR", "PLAYWRIGHT_BROWSERS_PATH"):
                self.assertTrue(Path(environment[name]).is_relative_to(Path(temporary)))
            self.assertEqual(environment["CLOAKBROWSER_AUTO_UPDATE"], "false")
            with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(Path(temporary).parent / "outside-browser")}):
                with self.assertRaises(ValueError):
                    browser.cloak_configuration()

    def test_unsupported_license_and_binary_overrides_fail_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(browser, "PROJECT", Path(temporary)):
            for field, value in (("CLOAKBROWSER_LICENSE_KEY", "example-key"),
                                 ("CLOAKBROWSER_BINARY_PATH", "example.exe"),
                                 ("CLOAKBROWSER_SKIP_CHECKSUM", "true")):
                with patch.dict(os.environ, {field: value}, clear=True), self.assertRaises(ValueError):
                    browser.cloak_configuration()
            cache = Path(temporary) / ".state/cloakbrowser"
            cache.mkdir(parents=True)
            (cache / "license.key").write_text("example-key")
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                browser.cloak_configuration()

    def test_cloak_launch_preserves_other_readers_browser_lookup(self):
        for original in (None, "existing-stock-browser-cache"):
            environment = {} if original is None else {"PLAYWRIGHT_BROWSERS_PATH": original}
            with tempfile.TemporaryDirectory() as temporary, patch.object(browser, "PROJECT", Path(temporary)), \
                    patch.dict(os.environ, environment, clear=True), \
                    patch.object(browser.importlib.util, "find_spec", return_value=object()), \
                    patch.object(tempfile, "tempdir", None):
                browser.configure_cloak_runtime()
                self.assertEqual(os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), original)


if __name__ == "__main__":
    unittest.main()
