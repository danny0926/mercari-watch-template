"""Isolated adapter around Orchard's actual Scanner, Encoder and SemanticIndex.

No HTTP server is started. The monitor talks to this process over stdin/stdout;
only the reviewed upstream search implementation runs the model and ranking.
"""
import argparse
import base64
import hashlib
from io import BytesIO
import ipaddress
import json
import logging
import socket
import sys
import time
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
from collection_catalog import image_bytes, load_catalog, MAX_BYTES, validate_image
from collection_paths import (RUNTIME, ORCHARD_COMMIT, ORCHARD_FILES, catalog_path, check_tree,
                              child_environment, private_path)

STATES = {"empty": "未比對：本機收藏沒有照片", "model_unavailable": "無法比對：本機模型或套件尚未就緒",
          "missing_image": "未比對：賣場未提供圖片", "download_failed": "無法比對：賣場圖片無法安全讀取",
          "no_candidate": "無可展示候選（未校準，不能據此判定未收藏）",
          "unavailable": "無法比對：本機收藏或比對程序尚未就緒",
          "candidate": "圖片候選，需人工核對；不代表已收藏"}


def orchard():
    vendor = check_tree(RUNTIME / "orchard")
    if (vendor / "PINNED_COMMIT").read_text(encoding="utf-8").strip() != ORCHARD_COMMIT:
        raise ValueError("Unexpected Orchard source")
    for relative, digest in ORCHARD_FILES.items():
        if hashlib.sha256(private_path(vendor / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("Orchard source differs from the reviewed pin")
    sys.path.insert(0, str(vendor))
    from server.scanner import Scanner
    from server import scanner
    from server.semantic import Encoder, SemanticIndex
    from server.cache import connect
    scanner.WORKERS = 1  # Bound simultaneous image decoding without replacing upstream's implementation.
    return Scanner, Encoder, SemanticIndex, connect


class CatalogSource:
    """Orchard scanner source limited to manifest photos, with no recursive folder walk."""
    def __init__(self, root, catalog):
        self.root = root
        self.entries = {p["file"]: item for item in catalog["items"] for p in item["photos"]}
        self.valid = set()
        self.missing = 0

    def check(self):
        private_path(self.root)

    def list(self, found=None):
        entries = []
        self.valid.clear()
        self.missing = 0
        for relative in self.entries:
            try:
                path = private_path(relative, base=self.root)
                image_bytes(path)
                stat = path.stat()
                entries.append((relative, "originals", stat.st_size, stat.st_mtime_ns))
                self.valid.add(relative)
            except (OSError, ValueError):
                self.missing += 1
        return entries, [], []

    def open(self, relative):
        if relative not in self.valid:
            raise ValueError("Unregistered photo")
        # Bound and validate on the actual read too, including files edited during a scan.
        return BytesIO(image_bytes(private_path(relative, base=self.root)))


def download_image(url):
    """Only known marketplace image CDNs, public addresses, HTTPS, no redirects or proxies."""
    import httpx
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    allowed = (host == "mercdn.net" or host.endswith(".mercdn.net")
               or host == "mercari-shops-static.com" or host.endswith(".mercari-shops-static.com")
               or host == "yimg.jp" or host.endswith(".yimg.jp") or host == "cdn.suruga-ya.jp")
    if not allowed or parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Unsupported image URL")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("Nonpublic image host")
    started = time.monotonic()
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(5, connect=3)) as client:
        with client.stream("GET", url, headers={"Accept": "image/*", "Accept-Encoding": "identity"}) as response:
            if response.status_code != 200 or not response.headers.get("Content-Type", "").lower().startswith("image/"):
                raise ValueError("Image unavailable")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Encoded response refused")
            if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
                raise ValueError("Image too large")
            data = bytearray()
            for chunk in response.iter_raw(chunk_size=65536):
                if time.monotonic() - started > 10 or len(data) + len(chunk) > MAX_BYTES:
                    raise ValueError("Image transfer exceeded budget")
                data.extend(chunk)
    validate_image(data)
    return bytes(data)


def montage(candidates):
    from PIL import Image, ImageDraw, ImageOps
    # One thumbnail per product; numbered tiles correspond to the ordered names.
    result = Image.new("RGB", (320 * len(candidates), 352), "#eeeeee")
    draw = ImageDraw.Draw(result)
    for index, candidate in enumerate(candidates):
        with Image.open(BytesIO(candidate["bytes"])) as original:
            tile = ImageOps.exif_transpose(original).convert("RGB")
        tile.thumbnail((304, 312))
        result.paste(tile, (index * 320 + (320 - tile.width) // 2, 32 + (312 - tile.height) // 2))
        draw.text((index * 320 + 12, 2), str(index + 1), fill="black", font_size=24)
        tile.close()
    output = BytesIO()
    result.save(output, "JPEG", quality=88, optimize=True)
    result.close()
    return base64.b64encode(output.getvalue()).decode("ascii")


class Comparison:
    def __init__(self, root):
        self.root = catalog_path(root)
        self.catalog = load_catalog(self.root)
        self.source = CatalogSource(self.root, self.catalog)
        if not self.source.entries:
            self.state = "empty"
            return
        Scanner, Encoder, SemanticIndex, self.connect = orchard()
        self.encoder = Encoder(check_tree(RUNTIME / "models"))
        if not self.encoder.downloaded():
            self.state = "model_unavailable"
            return
        # Indexes are private and distinct for each catalog directory, never shared with seller queries.
        key = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
        self.index_dir = check_tree(RUNTIME / "indexes" / key)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        scanner = Scanner(self.root, self.index_dir, source=self.source)
        scan_status = scanner.scan(retry=True)
        self.source.missing += scan_status.get("unreadable", 0) + scan_status.get("unreached", 0)
        self.index = SemanticIndex(self.index_dir, self.encoder)
        self.index.discard_other_models()
        self.index.index()
        status = self.index.status()
        self.state = "ready" if status["indexed"] else "unavailable"
        self.source.missing += status["total"] - status["indexed"]
        with self.connect(self.index_dir) as connection:
            self.paths = {}
            for relative, digest in connection.execute("SELECT path, image_id FROM files WHERE image_id IS NOT NULL ORDER BY path"):
                if relative in self.source.valid:
                    self.paths.setdefault(digest, []).append(relative)

    def compare(self, data):
        if self.state != "ready":
            return {"state": self.state}
        validate_image(data)
        ranked = self.index.search(image_bytes=data)  # Unmodified upstream retrieval, not a new embedding implementation.
        candidates, seen = [], set()
        for digest, score in ranked:
            for relative in self.paths.get(digest, []):
                item = self.source.entries[relative]
                if item["id"] in seen:
                    continue
                try:
                    evidence = image_bytes(private_path(relative, base=self.root))
                    if hashlib.sha256(evidence).hexdigest() != digest:
                        continue
                except (ValueError, OSError):
                    continue
                seen.add(item["id"])
                candidates.append({"name": item["name"], "score": round(score, 4), "bytes": evidence})
                if len(candidates) == 3:
                    break
            if len(candidates) == 3:
                break
        if not candidates:
            return {"state": "no_candidate"}
        return {"state": "candidate", "candidates": [{"name": x["name"], "score": x["score"]} for x in candidates],
                "evidence_jpeg": montage(candidates), "partial": self.source.missing > 0}


def batch(root, queries):
    if not isinstance(queries, list) or len(queries) > 10:
        raise ValueError("At most ten query images per invocation")
    if not any(queries):
        return [{"state": "missing_image"} for _ in queries]
    try:
        comparison = Comparison(root)
    except (ImportError, FileNotFoundError):
        return [{"state": "model_unavailable"} for _ in queries]
    except Exception:
        return [{"state": "unavailable"} for _ in queries]
    results = []
    for query in queries:
        if not query:
            results.append({"state": "missing_image"})
        elif comparison.state != "ready":
            results.append({"state": comparison.state})
        else:
            try:
                data = download_image(query)
            except Exception:
                results.append({"state": "download_failed"})
                continue
            try:
                results.append(comparison.compare(data))
            except Exception:
                results.append({"state": "unavailable"})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "batch"])
    parser.add_argument("--catalog-dir", default=".state/collection")
    args = parser.parse_args()
    # Run before importing upstream or any dependency that may cache at import time.
    import os
    environment = child_environment(offline=args.command != "prepare")
    os.environ.clear()
    os.environ.update(environment)
    logging.disable(logging.CRITICAL)
    if args.command == "prepare":
        _, Encoder, _, _ = orchard()
        Encoder(check_tree(RUNTIME / "models")).load()
        print("Pinned Orchard SigLIP 2 model loaded locally.")
    else:
        request = sys.stdin.buffer.read(32769)
        if len(request) > 32768:
            raise ValueError("Request too large")
        results = batch(args.catalog_dir, json.loads(request))
        print(json.dumps(results, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Collection engine unavailable", file=sys.stderr)
        raise SystemExit(1)
