import json
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet, InvalidToken

import handoff_state as state


class HandoffStateTests(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode("ascii")
        self.session = str(uuid.uuid4())
        self.states = {"core": {"_known": ["example-1"], "sample": ["example-1"]},
                       "surugaya": {"_known_by_route": {"example-route": ["example-2"]}}}

    def test_encrypted_bundle_preserves_both_histories_and_checks_session_and_key(self):
        for values in (self.states, {"core": self.states["core"]}):
            token = state.pack_states(values, self.session, self.key)
            self.assertNotIn("example-1", token)
            self.assertEqual(state.unpack_states(token, self.session, self.key), values)
            with self.assertRaises(ValueError):
                state.unpack_states(token, str(uuid.uuid4()), self.key)
            with self.assertRaises(InvalidToken):
                state.unpack_states(token, self.session, Fernet.generate_key().decode())
        for values in ({}, {"other": {}}, {"core": []}):
            with self.assertRaises(ValueError):
                state.pack_states(values, self.session, self.key)

    def test_secret_chunks_require_contiguous_bounded_payloads(self):
        token = "x" * (state.CHUNK_SIZE + 100)
        chunks = state.split_payload(token)
        self.assertEqual(len(chunks), 8)
        self.assertEqual(state.join_payload(chunks), token)
        with self.assertRaises(ValueError):
            state.join_payload({**chunks, state.CHUNK_KEYS[0]: ""})
        with self.assertRaises(ValueError):
            state.split_payload("x" * (state.CHUNK_SIZE * 8 + 1))

    def test_state_files_keep_production_format_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "seen.enc"
            state.write_state(path, self.key, self.states["core"])
            before = path.read_bytes()
            plain = Fernet(self.key.encode()).decrypt(before)
            self.assertEqual(json.loads(plain), self.states["core"])
            with patch.object(Path, "replace", side_effect=OSError("example")), self.assertRaises(OSError):
                state.write_state(path, self.key, {"_known": ["example-3"]})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(state.read_state(path, self.key), self.states["core"])

    def test_remote_payload_cannot_expand_past_memory_limit(self):
        token = Fernet(self.key.encode()).encrypt(zlib.compress(b"x" * 1024)).decode()
        with patch.object(state, "MAX_JSON", 128), self.assertRaises(ValueError):
            state.unpack_states(token, self.session, self.key)


if __name__ == "__main__":
    unittest.main()
