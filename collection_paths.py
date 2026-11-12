"""Storage boundary shared by the optional, isolated collection tools."""
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
RUNTIME = PROJECT / ".state/collection-runtime"
ORCHARD_COMMIT = "24cf2821e2bcc57cb9a25ececc05d9f7c3e0b86c"
ORCHARD_SHA256 = "4be1be35e4bd5ef37dcc521bdadfc6ada4762e9b48793b2857b62d34e4245f4d"
ORCHARD_FILES = {
    "server/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "server/cache.py": "14d9590c4d5a9fb622c1fe513d03e019117b7cf36ae76c2df7e1f14fb996def8",
    "server/scanner.py": "5894835588dcfed9e1cd28fa52e78559d6493897485e7e7bfef1853476e4bc8e",
    "server/semantic.py": "a84203a28cabab58d285ebd1ea9a892b711e7695f34909ee7f3438ec778e805e",
    "server/parity-vector.npy": "e0431af9f19c6ee9123a05c1028bf2d6290bbf55ab6ad97c917e193566967187",
}


def private_path(value, *, base=PROJECT):
    """Resolve before using: junctions and symlinks cannot leave this project's .state."""
    state = PROJECT / ".state"
    if state.resolve() != state:
        raise ValueError("Collection storage boundary is invalid")
    path = Path(value)
    path = path if path.is_absolute() else base / path
    resolved = path.resolve()
    if not resolved.is_relative_to(state) or resolved == state:
        raise ValueError("Collection files must stay inside project .state")
    return resolved


def check_tree(path):
    path = private_path(path)
    for child in path.rglob("*"):
        private_path(child)
    return path


def catalog_path(value=None):
    return private_path(value or ".state/collection")


def isolated_python():
    return private_path(RUNTIME / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python"))


def child_environment(*, offline=True):
    """No webhook, search rules, account tokens, user package paths, or external cache overrides."""
    runtime = private_path(RUNTIME)
    environment = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT")
                   if key in os.environ}
    folders = {"TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp", "HOME": "home",
               "USERPROFILE": "home", "APPDATA": "home/AppData/Roaming",
               "LOCALAPPDATA": "home/AppData/Local", "XDG_CACHE_HOME": "cache",
               "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data", "PIP_CACHE_DIR": "pip-cache",
               "HF_HOME": "models", "HF_HUB_CACHE": "models", "HF_XET_CACHE": "models/xet"}
    for key, suffix in folders.items():
        folder = private_path(runtime / suffix)
        folder.mkdir(parents=True, exist_ok=True)
        environment[key] = str(folder)
    environment.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONIOENCODING": "utf-8", "PIP_CONFIG_FILE": os.devnull,
                        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_XET": "1",
                        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "DO_NOT_TRACK": "1"})
    if offline:
        environment["HF_HUB_OFFLINE"] = "1"
    return environment
