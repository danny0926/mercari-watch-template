"""Run with the isolated collection Python. Synthetic photos only; no model downloads."""
import base64
import contextlib
import hashlib
from io import BytesIO, StringIO
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:
    Image = None
import collection_catalog as catalog
import collection_engine as engine
from collection_paths import PROJECT, private_path


@unittest.skipIf(Image is None, "Run catalog tests with .state/collection-runtime/venv Python")
class CatalogTests(unittest.TestCase):
    def setUp(self):
        parent = private_path(".state/collection-validation")
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        from pathlib import Path
        self.root = Path(self.tmp.name)
        self.photo = self.root / "sample.png"
        with Image.new("RGB", (200, 100), "red") as image:
            image.save(self.photo)

    def command(self, *args):
        with patch("sys.argv", ["collection_catalog.py", "--catalog-dir", str(self.root / "catalog"), *args]), \
             contextlib.redirect_stdout(StringIO()) as output:
            catalog.main()
        return output.getvalue()

    def test_zero_first_multiple_update_delete_and_original_bytes(self):
        self.command("init")
        self.command("add", "--id", "example", "--name", "Example collection")
        self.assertEqual(engine.Comparison(self.root / "catalog").state, "empty")
        self.command("add", "--id", "example", "--photo", str(self.photo))
        self.command("add", "--id", "example", "--photo", str(self.photo), "--name", "Updated example")
        data = catalog.load_catalog(self.root / "catalog")
        item = data["items"][0]
        self.assertEqual(item["name"], "Updated example")
        self.assertEqual(len(item["photos"]), 2)
        for photo in item["photos"]:
            self.assertEqual((self.root / "catalog" / photo["file"]).read_bytes(), self.photo.read_bytes())
        self.assertNotIn("sample.png", str(data))
        self.command("remove", "--id", "example", "--photo-id", item["photos"][0]["id"])
        self.assertFalse((self.root / "catalog" / item["photos"][0]["file"]).exists())
        self.assertEqual(len(catalog.load_catalog(self.root / "catalog")["items"][0]["photos"]), 1)
        self.command("remove", "--id", "example")
        self.assertEqual(catalog.load_catalog(self.root / "catalog")["items"], [])
        self.assertEqual(list((self.root / "catalog/originals").iterdir()), [])

    def test_invalid_or_missing_photo_keeps_catalog_unchanged(self):
        self.command("init")
        before = (self.root / "catalog/catalog.json").read_bytes()
        with self.assertRaises(OSError):
            self.command("add", "--id", "example", "--photo", str(self.photo), "--photo", str(self.root / "missing.png"))
        self.assertEqual((self.root / "catalog/catalog.json").read_bytes(), before)
        self.assertEqual(list((self.root / "catalog/originals").iterdir()), [])

    def test_manifest_escape_is_refused_before_read(self):
        self.command("add", "--id", "example", "--photo", str(self.photo))
        data = catalog.load_catalog(self.root / "catalog")
        data["items"][0]["photos"][0]["file"] = "../../README.md"
        catalog.save_catalog(self.root / "catalog", data)
        with self.assertRaises(ValueError):
            catalog.load_catalog(self.root / "catalog")

    def test_external_symlink_is_refused_before_read(self):
        link = self.root / "outside-link"
        try:
            link.symlink_to(PROJECT / "README.md")
        except OSError:
            self.skipTest("Windows account cannot create symlinks; manifest path traversal is tested separately")
        with self.assertRaises(ValueError):
            private_path(link)

    def test_source_reads_only_manifest_photos_and_handles_missing(self):
        self.command("add", "--id", "example", "--photo", str(self.photo))
        root = self.root / "catalog"
        data = catalog.load_catalog(root)
        source = engine.CatalogSource(root, data)
        entries, unreadable, libraries = source.list()
        self.assertEqual(len(entries), 1)
        self.assertEqual(unreadable + libraries, [])
        with self.assertRaises(ValueError):
            source.open("../sample.png")
        (root / data["items"][0]["photos"][0]["file"]).unlink()
        self.assertEqual(source.list()[0], [])
        self.assertEqual(source.missing, 1)
        # Missing seller images must be reported without loading any model.
        with patch.object(engine, "Comparison", side_effect=AssertionError("Model should not load")):
            self.assertEqual(engine.batch(root, ["", ""]), [{"state": "missing_image"}] * 2)

    def test_one_and_three_photo_montages_use_real_photos_without_stretching(self):
        red = self.photo.read_bytes()
        blue_path = self.root / "blue.png"
        with Image.new("RGB", (100, 200), "blue") as image:
            image.save(blue_path)
        blue = blue_path.read_bytes()
        for photos in ([red], [red, blue, red]):
            data = base64.b64decode(engine.montage([{"bytes": value} for value in photos]))
            self.assertEqual(catalog.validate_image(data), ".jpg")
            with Image.open(BytesIO(data)) as montage:
                self.assertEqual(montage.size, (len(photos) * 320, 352))
                self.assertGreater(montage.getpixel((160, 188))[0], 240)
                self.assertLess(montage.getpixel((160, 188))[1], 15)
                # Letterbox outside the horizontal photo remains grey, not stretched red.
                self.assertGreater(montage.getpixel((160, 45))[1], 200)

    def test_download_rejects_unknown_host_local_dns_redirects_and_oversize(self):
        with patch.object(engine.socket, "getaddrinfo") as dns:
            with self.assertRaises(ValueError):
                engine.download_image("https://127.0.0.1/private")
            dns.assert_not_called()
        with patch.object(engine.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError):
                engine.download_image("https://static.mercdn.net/example.jpg")
        import httpx
        for status, headers in ((302, {"Location": "http://127.0.0.1/private"}),
                                (200, {"Content-Type": "image/jpeg", "Content-Length": str(catalog.MAX_BYTES + 1)})):
            transport = httpx.MockTransport(lambda request: httpx.Response(status, headers=headers))
            client = httpx.Client(transport=transport)
            with patch.object(engine.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]), \
                 patch.object(httpx, "Client", return_value=client):
                with self.assertRaises(ValueError):
                    engine.download_image("https://static.mercdn.net/example.jpg")


if __name__ == "__main__":
    unittest.main()
