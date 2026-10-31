"""Install the optional browser only in this project's virtual environment."""
import subprocess
import sys

from browser_runtime import PROJECT, cloak_environment


def main():
    environment = cloak_environment()
    virtual = PROJECT / ".venv"
    python = virtual / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(virtual)], cwd=PROJECT, env=environment, check=True)
    subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--no-input",
                    "--disable-pip-version-check", "--only-binary=:all:",
                    "--cache-dir", environment["PIP_CACHE_DIR"], "--index-url", "https://pypi.org/simple",
                    "-r", str(PROJECT / "requirements-cloakbrowser.txt")],
                   cwd=PROJECT, env=environment, check=True)
    subprocess.run([str(python), str(PROJECT / "browser_runtime.py")], cwd=PROJECT, env=environment, check=True)


if __name__ == "__main__":
    main()
