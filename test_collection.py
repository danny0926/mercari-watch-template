"""Offline monitor integration tests; no catalog photos, live endpoints or model needed."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import httpx
import collection_compare as comparison
from collection_paths import PROJECT, child_environment, private_path
import mercari_watch as app


def record(index):
    return {"item_id": f"synthetic-{index}", "name": f"Synthetic listing {index}", "watch": "Example",
            "price": 500, "url": f"https://example.org/item/{index}", "source": "jp",
            "is_auction": False, "thumbnail": f"https://static.mercdn.net/synthetic-{index}.jpg"}


def candidate(index):
    return {"state": "candidate", "candidates": [{"name": f"Example collection {index}"}],
            "evidence": b"\xff\xd8synthetic-jpeg-" + str(index).encode()}


class CollectionNotificationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        network = patch.object(app.httpx, "post", side_effect=AssertionError("Live network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def test_multipart_maps_each_candidate_to_its_own_seller_and_retries_bytes(self):
        items = [record(i) for i in range(12)]
        evidence = [candidate(i) if i != 2 else {"state": "missing_image"} for i in range(12)]
        evidence[0]["candidates"] = [{"name": "Example one"}, {"name": "Example two"}, {"name": "Example three"}]
        with patch.object(app, "compare_items", return_value=evidence):
            messages = app.build_discord_messages(items)
        self.assertEqual(sum(len(m["embeds"]) for m in messages), 12)
        found = 0
        for message in messages:
            self.assertLessEqual(len(message["embeds"]), 10)
            files = dict(message.get("_collection_files", []))
            for embed in message["embeds"]:
                self.assertEqual(embed["image"]["url"], items[found]["thumbnail"])
                if found == 2:
                    self.assertNotIn("thumbnail", embed)
                else:
                    name = embed["thumbnail"]["url"].removeprefix("attachment://")
                    self.assertEqual(files[name], evidence[found]["evidence"])
                self.assertEqual(embed["url"], items[found]["url"])
                found += 1
            calls = []

            def send(url, **kwargs):
                self.assertNotIn("json", kwargs)
                payload = json.loads(kwargs["data"]["payload_json"])
                self.assertNotIn("_collection_files", payload)
                self.assertEqual(payload["allowed_mentions"], {"parse": []})
                for i, ((part, (name, data, mime)), metadata) in enumerate(zip(kwargs["files"], payload["attachments"])):
                    self.assertEqual(part, f"files[{i}]")
                    self.assertEqual(metadata, {"id": i, "filename": name})
                    self.assertEqual(data, files[name])
                    self.assertEqual(mime, "image/jpeg")
                # Build the actual multipart wire body, including payload_json and files[n].
                request = httpx.Request("POST", str(url), data=kwargs["data"], files=kwargs["files"])
                wire = request.read()
                self.assertIn(b'name="payload_json"', wire)
                for _, (name, data, _) in kwargs["files"]:
                    self.assertIn(name.encode(), wire)
                    self.assertIn(data, wire)
                self.assertNotIn(b".state", wire)
                self.assertNotIn(b"originals/", wire)
                calls.append(kwargs)
                return httpx.Response(429, json={"retry_after": 0}) if len(calls) == 1 else httpx.Response(200)

            with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/example"}), \
                 patch.object(app.httpx, "post", side_effect=send), patch.object(app.time, "sleep"), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(app.discord_push(message))
            self.assertEqual(calls[0]["files"], calls[1]["files"])

    def test_fallbacks_keep_every_listing_and_seller_image(self):
        states = list(comparison.STATUSES)
        items = [record(i) for i in range(len(states) - 1)]
        evidence = [{"state": state} for state in states if state != "candidate"]
        with patch.object(app, "compare_items", return_value=evidence):
            messages = app.build_discord_messages(items)
        embeds = [embed for message in messages for embed in message["embeds"]]
        self.assertEqual(len(embeds), len(items))
        for item, embed, result in zip(items, embeds, evidence):
            self.assertEqual(embed["image"]["url"], item["thumbnail"])
            self.assertNotIn("thumbnail", embed)
            self.assertIn(comparison.STATUSES[result["state"]], json.dumps(embed, ensure_ascii=False))
        self.assertTrue(all("_collection_files" not in m for m in messages))

    def test_comparison_failure_and_incomplete_results_cannot_suppress(self):
        for options in ({"side_effect": RuntimeError("private path")}, {"return_value": []}):
            with patch.object(app, "compare_items", **options):
                messages = app.build_discord_messages([record(1), record(2)])
            self.assertEqual(sum(len(m["embeds"]) for m in messages), 2)
            self.assertNotIn("private path", json.dumps(messages))

    def test_disabled_and_missing_install_never_launch_or_download(self):
        with patch.object(comparison.subprocess, "run") as launch:
            self.assertEqual(comparison.compare_items([record(1)])[0]["state"], "disabled")
            with patch.dict(os.environ, {"COLLECTION_COMPARE_ENABLED": "true"}), \
                 patch.object(comparison, "isolated_python", return_value=PROJECT / ".state/nonexistent-runtime/python"):
                self.assertEqual(comparison.compare_items([record(1)])[0]["state"], "model_unavailable")
        launch.assert_not_called()

    def test_subprocess_timeout_bad_reply_and_missing_evidence_fall_back(self):
        options = [{"side_effect": subprocess.TimeoutExpired("private", 120)},
                   {"return_value": subprocess.CompletedProcess([], 0, b"[]")},
                   {"return_value": subprocess.CompletedProcess([], 0, b'[{"state":"candidate","candidates":[{"name":"Example"}]}]')}]
        with patch.dict(os.environ, {"COLLECTION_COMPARE_ENABLED": "true"}), \
             patch.object(comparison, "isolated_python", return_value=Path(__file__)):
            for option in options:
                with patch.object(comparison.subprocess, "run", **option):
                    self.assertEqual(comparison.compare_items([record(1)]), [{"state": "unavailable"}])

    def test_child_gets_no_credentials_and_evidence_decodes(self):
        encoded = base64.b64encode(candidate(1)["evidence"]).decode()
        result = [{"state": "candidate", "candidates": [{"name": "Example"}], "evidence_jpeg": encoded}]
        with patch.dict(os.environ, {"COLLECTION_COMPARE_ENABLED": "true", "DISCORD_WEBHOOK_URL": "private", "HF_TOKEN": "private",
                                     "WATCHLIST_JSON": "private", "PYTHONPATH": "outside"}), \
             patch.object(comparison, "isolated_python", return_value=Path(__file__)), \
             patch.object(comparison.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(result).encode())) as launch:
            found = comparison.compare_items([record(1)])
        self.assertEqual(found[0]["evidence"], candidate(1)["evidence"])
        env = launch.call_args.kwargs["env"]
        self.assertTrue({"DISCORD_WEBHOOK_URL", "WATCHLIST_JSON", "HF_TOKEN", "PYTHONPATH"}.isdisjoint(env))
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        for key in ("HF_HOME", "HF_XET_CACHE", "HOME", "TEMP", "PIP_CACHE_DIR", "APPDATA"):
            self.assertTrue(Path(env[key]).is_relative_to(PROJECT / ".state"))

    def test_storage_rejects_paths_outside_project_state(self):
        for value in (PROJECT / "README.md", "../other-project/file.jpg", PROJECT / ".state"):
            with self.assertRaises(ValueError):
                private_path(value)
        self.assertTrue(private_path(".state/example/photo.jpg").is_relative_to(PROJECT / ".state"))


if __name__ == "__main__":
    unittest.main()
