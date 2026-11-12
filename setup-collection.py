"""Install pinned Orchard source and its CPU search dependencies inside this project."""
import hashlib
from io import BytesIO
from pathlib import PurePosixPath
import subprocess
import sys
import urllib.request
import zipfile

sys.dont_write_bytecode = True
from collection_paths import (PROJECT, RUNTIME, ORCHARD_COMMIT, ORCHARD_SHA256,
                              check_tree, child_environment, isolated_python, private_path)


def model_notices():
    notices = private_path(RUNTIME / "licenses")
    notices.mkdir(parents=True, exist_ok=True)
    sources = {
        "siglip2-model-card.md": "https://huggingface.co/google/siglip2-base-patch16-256/raw/main/README.md",
        "siglip2-onnx-model-card.md": "https://huggingface.co/onnx-community/siglip2-base-patch16-256-ONNX/raw/d1114256522a37ffa257a0a58017348ab0058db2/README.md",
        "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    }
    for name, url in sources.items():
        target = private_path(notices / name)
        if target.is_file():
            continue
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(100_001)
        if len(data) > 100_000:
            raise ValueError("Unexpected model notice size")
        target.write_bytes(data)


def main():
    environment = child_environment(offline=False)
    check_tree(RUNTIME)
    vendor = private_path(RUNTIME / "orchard")
    if not vendor.exists():
        url = f"https://codeload.github.com/chaseleantj/orchard-photos/zip/{ORCHARD_COMMIT}"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive = response.read(10_000_001)
        if len(archive) > 10_000_000 or hashlib.sha256(archive).hexdigest() != ORCHARD_SHA256:
            raise ValueError("Orchard archive did not match the reviewed source")
        with zipfile.ZipFile(BytesIO(archive)) as zipped:
            for member in zipped.infolist():
                parts = PurePosixPath(member.filename).parts[1:]
                if not parts or member.is_dir():
                    continue
                if ".." in parts or member.file_size > 20_000_000:
                    raise ValueError("Invalid source archive")
                target = private_path(vendor.joinpath(*parts))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zipped.read(member))
        (vendor / "PINNED_COMMIT").write_text(ORCHARD_COMMIT + "\n", encoding="utf-8")
    if (vendor / "PINNED_COMMIT").read_text(encoding="utf-8").strip() != ORCHARD_COMMIT:
        raise ValueError("Unexpected Orchard installation")
    model_notices()
    python = isolated_python()
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", "--copies", str(python.parent.parent)],
                       cwd=PROJECT, env=environment, check=True)
    subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--no-input",
                    "--disable-pip-version-check", "--only-binary=:all:", "--cache-dir", environment["PIP_CACHE_DIR"],
                    "--index-url", "https://pypi.org/simple", "-r", str(PROJECT / "requirements-collection.txt")],
                   cwd=PROJECT, env=environment, check=True)
    subprocess.run([str(python), str(PROJECT / "collection_engine.py"), "prepare"],
                   cwd=PROJECT, env=environment, check=True)
    print("Collection runtime ready; catalog remains private in project .state.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Collection setup failed ({type(error).__name__}); retry setup after resolving installation/network access.", file=sys.stderr)
        raise SystemExit(1)
