"""Monitor-side optional adapter: no model dependencies in the monitor environment."""
import base64
import json
import os
import subprocess

from collection_paths import PROJECT, catalog_path, child_environment, isolated_python

STATUSES = {"disabled": "未比對：本機收藏比對未啟用", "empty": "未比對：本機收藏沒有照片",
            "model_unavailable": "無法比對：本機模型或套件尚未就緒", "missing_image": "未比對：賣場未提供圖片",
            "download_failed": "無法比對：賣場圖片無法安全讀取", "no_candidate": "無可展示候選（未校準，不能據此判定未收藏）",
            "unavailable": "無法比對：本機收藏或比對程序尚未就緒",
            "candidate": "圖片候選，需人工核對；不代表已收藏"}


def compare_items(items):
    results = []
    enabled = os.environ.get("COLLECTION_COMPARE_ENABLED", "false").lower() == "true"
    fallback = "unavailable" if enabled else "disabled"
    if not enabled:
        return [{"state": fallback} for _ in items]
    try:
        root = catalog_path(os.environ.get("COLLECTION_CATALOG_DIR"))
        python = isolated_python()
        # An unprovisioned GitHub runner never downloads a model or reads catalog elsewhere.
        if not python.is_file():
            return [{"state": "model_unavailable"} for _ in items]
        environment = child_environment()
    except Exception:
        return [{"state": fallback} for _ in items]
    for start in range(0, len(items), 10):
        chunk = items[start:start + 10]
        try:
            run = subprocess.run([str(python), str(PROJECT / "collection_engine.py"), "batch", "--catalog-dir", str(root)],
                                 input=json.dumps([str(x.get("thumbnail") or "")[:2048] for x in chunk]).encode(),
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=PROJECT, env=environment,
                                 timeout=120, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if len(run.stdout) > 4_000_000:
                raise ValueError("Comparison response too large")
            found = json.loads(run.stdout)
            if not isinstance(found, list) or len(found) != len(chunk):
                raise ValueError("Invalid comparison response")
            for result in found:
                if not isinstance(result, dict) or result.get("state") not in STATUSES:
                    raise ValueError("Invalid comparison status")
                if result["state"] == "candidate":
                    candidates = result.get("candidates", [])
                    if not 1 <= len(candidates) <= 3 or any(not isinstance(c.get("name"), str) for c in candidates):
                        raise ValueError("Invalid candidate evidence")
                    encoded = result.pop("evidence_jpeg", "")
                    if len(encoded) > 400_000:
                        raise ValueError("Evidence too large")
                    evidence = base64.b64decode(encoded, validate=True)
                    if not evidence.startswith(b"\xff\xd8"):
                        raise ValueError("Missing candidate evidence")
                    result["evidence"] = evidence
            results.extend(found)
        except Exception:
            results.extend({"state": fallback} for _ in chunk)
    return results


def comparison_text(result):
    text = STATUSES.get(result.get("state"), STATUSES["unavailable"])
    if result.get("state") == "candidate":
        # Names deliberately go to the requested channel; paths and original file names never do.
        names = []
        for number, candidate in enumerate(result["candidates"][:3], 1):
            name = candidate["name"][:120].replace("@", "＠").replace("`", "ˋ")
            for marker in ("*", "_", "~", "|", "[", "]", "\\"):
                name = name.replace(marker, "\\" + marker)
            name = " ".join(name.split())
            names.append(f"{number}. {name}")
        text += "\n" + "\n".join(names) + "\n編號對應右側縮圖，可點開核對；尚未校準。"
        if result.get("partial"):
            text += "\n部分收藏照片無法讀取，候選可能不完整。"
    return text[:1024]
