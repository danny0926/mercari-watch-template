"""Project-contained storage and configuration for the optional CloakBrowser."""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
FREE_BROWSER_VERSION = "146.0.7680.177.5"


@lru_cache(maxsize=1)
def _windows_driver_runtime():
    """Reuse a working packaged Node; some Windows Playwright builds crash at startup."""
    for package in ("playwright", "patchright"):
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.origin:
            continue
        node = Path(spec.origin).parent / "driver/node.exe"
        if not node.is_file():
            continue
        try:
            result = subprocess.run(
                [str(node), "--version"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                env=browser_child_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0 and re.fullmatch(rb"v\d+\.\d+\.\d+\s*", result.stdout):
                return str(node)
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise ValueError("Project browser driver runtime is unavailable")


def configure_browser_driver():
    # Keep an explicitly selected runtime. The fallback stays in the installed
    # project packages and changes neither their files nor the PM2 daemon env.
    if sys.platform == "win32" and not os.environ.get("PLAYWRIGHT_NODEJS_PATH"):
        os.environ["PLAYWRIGHT_NODEJS_PATH"] = _windows_driver_runtime()


def stock_browser_channel(chromium):
    # A virtualenv/package upgrade can leave no matching stock Chromium cache.
    # Reuse installed Edge on Windows; never download or reuse a live profile.
    if sys.platform == "win32" and not Path(chromium.executable_path).is_file():
        return "msedge"
    return "chromium"


def browser_backend():
    backend = os.environ.get("SURUGAYA_BROWSER_BACKEND", "cloakbrowser").strip().lower()
    if backend not in ("cloakbrowser", "patchright"):
        raise ValueError("Unknown Suruga-ya browser backend")
    return backend


def project_path(value, default):
    path = Path(value or default)
    path = (path if path.is_absolute() else PROJECT / path).resolve()
    if not path.is_relative_to(PROJECT) or path == PROJECT:
        raise ValueError("Browser storage must be inside this project")
    return path


def cloak_configuration(require_installed=False):
    if require_installed and importlib.util.find_spec("cloakbrowser") is None:
        raise ValueError("Install project browser dependencies first")
    cache = project_path(os.environ.get("CLOAKBROWSER_CACHE_DIR"), ".state/cloakbrowser")
    profile = project_path(os.environ.get("SURUGAYA_BROWSER_PROFILE"), ".state/browser-profiles/surugaya-cloakbrowser")
    temporary = project_path(None, ".state/browser-tmp")
    version = os.environ.get("CLOAKBROWSER_VERSION", FREE_BROWSER_VERSION).strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3,4}", version):
        raise ValueError("Invalid browser release pin")
    # The pinned keyless binary keeps all state in configurable project paths.
    # New licensed builds use additional home-directory files and need a separate integration.
    if os.environ.get("CLOAKBROWSER_LICENSE_KEY", "").strip() or (cache / "license.key").exists():
        raise ValueError("This project integration supports keyless browser releases")
    if any(os.environ.get(name) for name in ("CLOAKBROWSER_BINARY_PATH", "CLOAKBROWSER_DOWNLOAD_URL", "CLOAKBROWSER_SKIP_CHECKSUM")):
        raise ValueError("Custom binaries and checksum overrides are not supported")
    return {"cache": cache, "profile": profile, "temporary": temporary, "version": version}


def cloak_environment():
    configuration = cloak_configuration()
    environment = dict(os.environ)
    for path in (configuration["cache"], configuration["profile"], configuration["temporary"], PROJECT / ".state/pip-cache"):
        path.mkdir(parents=True, exist_ok=True)
    environment.update({
        "CLOAKBROWSER_CACHE_DIR": str(configuration["cache"]),
        "CLOAKBROWSER_VERSION": configuration["version"],
        "CLOAKBROWSER_AUTO_UPDATE": "false", "CLOAKBROWSER_WIDEVINE": "false",
        "TEMP": str(configuration["temporary"]), "TMP": str(configuration["temporary"]),
        "TMPDIR": str(configuration["temporary"]),
        "PIP_CACHE_DIR": str(PROJECT / ".state/pip-cache"), "PIP_CONFIG_FILE": os.devnull,
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "PLAYWRIGHT_BROWSERS_PATH": str(PROJECT / ".state/playwright-browsers"),
    })
    return environment


def configure_cloak_runtime():
    configuration = cloak_configuration(require_installed=True)
    environment = cloak_environment()
    for name in ("CLOAKBROWSER_CACHE_DIR", "CLOAKBROWSER_VERSION", "CLOAKBROWSER_AUTO_UPDATE",
                 "CLOAKBROWSER_WIDEVINE", "TEMP", "TMP", "TMPDIR"):
        os.environ[name] = environment[name]
    # The other readers use stock Playwright browsers. Cloak passes its executable
    # explicitly, so changing PLAYWRIGHT_BROWSERS_PATH would break the next Taiwan round.
    # tempfile may already have cached the OS temporary directory earlier in the round.
    tempfile.tempdir = str(configuration["temporary"])
    return configuration


def browser_child_environment():
    return {name: value for name, value in os.environ.items()
            if name != "WATCHLIST_JSON" and name != "GITHUB_TOKEN"
            and not name.startswith(("DISCORD_", "LINE_", "MONITOR_", "GH_", "ACTIONS_"))
            and not name.endswith(("_TOKEN", "_SECRET", "_API_KEY"))}


def main():
    from dotenv import load_dotenv
    load_dotenv(PROJECT / ".env", override=False, interpolate=False)
    configuration = configure_cloak_runtime()
    from cloakbrowser.download import ensure_binary
    binary = Path(ensure_binary(browser_version=configuration["version"])).resolve()
    if not binary.is_relative_to(configuration["cache"]):
        raise SystemExit("Browser binary was not installed in the project cache")
    print("Project-local CloakBrowser binary is ready.")


if __name__ == "__main__":
    main()
