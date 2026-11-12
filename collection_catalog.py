"""Manual local-photo catalog. Only explicitly supplied, project-private files are read."""
import argparse
from io import BytesIO
import json
import re
import sys
import uuid

sys.dont_write_bytecode = True
from collection_paths import catalog_path, private_path

MAX_BYTES = 6_000_000
MAX_PIXELS = 20_000_000
MAX_PHOTOS = 1000
MAX_ITEMS = 500
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def image_bytes(path):
    path = private_path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Photo exceeds 6 MB")
    data = path.read_bytes()
    validate_image(data)
    return data


def validate_image(data):
    from PIL import Image
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Photo must be at most 6 MB")
    with Image.open(BytesIO(data)) as image:
        if image.format not in FORMATS or image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Use a still JPEG, PNG, or WebP photo at most 20 megapixels")
        extension = FORMATS[image.format]
        image.verify()
    return extension


def load_catalog(root):
    root = catalog_path(root)
    manifest = private_path(root / "catalog.json")
    if not manifest.exists():
        return {"version": 1, "items": []}
    if manifest.stat().st_size > 1_000_000:
        raise ValueError("Catalog is too large")
    catalog = json.loads(manifest.read_text(encoding="utf-8"))
    if catalog.get("version") != 1 or not isinstance(catalog.get("items"), list) or len(catalog["items"]) > MAX_ITEMS:
        raise ValueError("Invalid catalog")
    ids, photo_ids = set(), set()
    for item in catalog["items"]:
        identity = item.get("id")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity) or identity in ids:
            raise ValueError("Invalid catalog identity")
        ids.add(identity)
        if not isinstance(item.get("name"), str) or not 1 <= len(item["name"]) <= 120:
            raise ValueError("Invalid catalog name")
        if not isinstance(item.get("photos"), list):
            raise ValueError("Invalid catalog photos")
        for photo in item["photos"]:
            photo_id = photo.get("id")
            if not isinstance(photo_id, str) or not re.fullmatch(r"[a-f0-9]{32}", photo_id) or photo_id in photo_ids:
                raise ValueError("Invalid photo identity")
            photo_ids.add(photo_id)
            relative = photo.get("file")
            if not isinstance(relative, str) or not re.fullmatch(r"originals/[a-f0-9]{32}\.(jpg|png|webp)", relative):
                raise ValueError("Invalid photo location")
            path = private_path(relative, base=root)
            if not path.is_relative_to(root):
                raise ValueError("Photo escaped catalog")
    if len(photo_ids) > MAX_PHOTOS:
        raise ValueError("Catalog supports at most 1000 photos")
    return catalog


def save_catalog(root, catalog):
    root.mkdir(parents=True, exist_ok=True)
    temporary = private_path(root / (uuid.uuid4().hex + ".tmp"))
    try:
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(private_path(root / "catalog.json"))
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Private manual-photo catalog; paths must be inside project .state")
    parser.add_argument("--catalog-dir", default=".state/collection")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    add = sub.add_parser("add", help="Create, rename, or append photos to a collection entry")
    add.add_argument("--id", required=True)
    add.add_argument("--name")
    add.add_argument("--photo", action="append", default=[])
    remove = sub.add_parser("remove", help="Remove an entry or one photo and its original")
    remove.add_argument("--id", required=True)
    selection = remove.add_mutually_exclusive_group()
    selection.add_argument("--photo-id")
    selection.add_argument("--photo-number", type=int, help="1-based photo number, in the order added")
    sub.add_parser("status", help="Print counts only; never print private names or paths")
    compare = sub.add_parser("compare", help="Offline model comparison; writes numbered evidence inside the catalog")
    compare.add_argument("--photo", required=True)
    args = parser.parse_args()
    root = catalog_path(args.catalog_dir)
    catalog = load_catalog(root)
    if args.command == "compare":
        import base64
        import os
        from collection_paths import child_environment
        environment = child_environment()
        os.environ.clear()
        os.environ.update(environment)
        import logging
        logging.disable(logging.CRITICAL)
        from collection_engine import Comparison, STATES
        result = Comparison(root).compare(image_bytes(private_path(args.photo)))
        evidence = result.pop("evidence_jpeg", None)
        target = private_path(root / "comparison.jpg")
        if evidence:
            target.write_bytes(base64.b64decode(evidence))
        else:
            target.unlink(missing_ok=True)
        # Explicit local command: names appear in terminal only when the user asks to compare.
        print(STATES.get(result["state"], STATES["unavailable"]))
        for i, candidate in enumerate(result.get("candidates", []), 1):
            print(f"Candidate {i}: cosine {candidate['score']:.4f}; not a probability")
        if evidence:
            print("Numbered photo evidence saved as comparison.jpg inside the private catalog directory.")
        return
    if args.command == "init":
        private_path(root / "inbox").mkdir(parents=True, exist_ok=True)
        if not private_path(root / "catalog.json").exists():
            save_catalog(root, catalog)
    elif args.command == "add":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.id):
            raise ValueError("Use a private ID of 1–64 ASCII letters, numbers, underscores or hyphens")
        item = next((item for item in catalog["items"] if item["id"] == args.id), None)
        if item is None:
            if len(catalog["items"]) >= MAX_ITEMS:
                raise ValueError("Catalog entry limit reached")
            item = {"id": args.id, "name": args.name or args.id, "photos": []}
            catalog["items"].append(item)
        if args.name is not None:
            if not 1 <= len(args.name) <= 120 or any(ord(c) < 32 for c in args.name):
                raise ValueError("Name must be 1–120 characters without control characters")
            item["name"] = args.name
        if sum(len(x["photos"]) for x in catalog["items"]) + len(args.photo) > MAX_PHOTOS:
            raise ValueError("Catalog photo limit reached")
        # One photo in memory at a time. Commit only after every supplied photo
        # succeeds; originals keep exactly the supplied bytes, including EXIF.
        created = []
        try:
            for supplied in args.photo:
                data = image_bytes(private_path(supplied))
                identity = uuid.uuid4().hex
                relative = f"originals/{identity}{validate_image(data)}"
                target = private_path(relative, base=root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                created.append(target)
                item["photos"].append({"id": identity, "file": relative})
            save_catalog(root, catalog)
        except Exception:
            for target in created:
                target.unlink(missing_ok=True)
            raise
    elif args.command == "remove":
        item = next((x for x in catalog["items"] if x["id"] == args.id), None)
        if item is None:
            raise ValueError("Unknown collection entry")
        if args.photo_number is not None:
            if not 1 <= args.photo_number <= len(item["photos"]):
                raise ValueError("Unknown photo number")
            args.photo_id = item["photos"][args.photo_number - 1]["id"]
        removed = [p for p in item["photos"] if args.photo_id is None or p["id"] == args.photo_id]
        if args.photo_id and not removed:
            raise ValueError("Unknown photo identity")
        item["photos"] = [p for p in item["photos"] if p not in removed]
        if args.photo_id is None:
            catalog["items"].remove(item)
        save_catalog(root, catalog)
        for photo in removed:
            private_path(photo["file"], base=root).unlink(missing_ok=True)
    print(f"Catalog: {len(catalog['items'])} entries, {sum(len(x['photos']) for x in catalog['items'])} photos.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Catalog operation failed ({type(error).__name__}); check command, photo format and project-local paths.", file=sys.stderr)
        raise SystemExit(1)
