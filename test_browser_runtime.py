import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import browser_runtime as browser


class BrowserRuntimeTests(unittest.TestCase):
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
