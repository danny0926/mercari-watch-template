"""Encrypted state transport between the local launcher and GitHub Actions."""
import argparse
import json
import os
import uuid
import zlib
from pathlib import Path

from cryptography.fernet import Fernet

SLOTS = ("core", "surugaya")
CHUNK_KEYS = tuple(f"MONITOR_HANDOFF_{index:02d}" for index in range(1, 9))
CHUNK_SIZE = 40000
MAX_JSON = 16 * 1024 * 1024


def _validate(states, session):
    if str(uuid.UUID(session)) != session:
        raise ValueError("Invalid handoff session")
    if not isinstance(states, dict) or not states or not set(states) <= set(SLOTS):
        raise ValueError("Invalid state slots")
    if not all(isinstance(state, dict) for state in states.values()):
        raise ValueError("Invalid state objects")


def read_state(path, key):
    state = json.loads(Fernet(key.encode("ascii")).decrypt(Path(path).read_bytes()))
    if not isinstance(state, dict):
        raise ValueError("Invalid state object")
    return state


def write_state(path, key, state):
    if not isinstance(state, dict):
        raise ValueError("Invalid state object")
    path = Path(path)
    data = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encrypted = Fernet(key.encode("ascii")).encrypt(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)


def pack_states(states, session, key):
    _validate(states, session)
    raw = json.dumps({"schema": 1, "session": session, "states": states},
                     ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_JSON:
        raise ValueError("State bundle exceeds size limit")
    token = Fernet(key.encode("ascii")).encrypt(zlib.compress(raw)).decode("ascii")
    split_payload(token)
    return token


def unpack_states(token, session, key):
    if not isinstance(token, str) or not 0 < len(token) <= CHUNK_SIZE * len(CHUNK_KEYS):
        raise ValueError("Invalid transport size")
    compressed = Fernet(key.encode("ascii")).decrypt(token.encode("ascii"))
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, MAX_JSON + 1)
    if len(raw) > MAX_JSON or not decompressor.eof or decompressor.unused_data:
        raise ValueError("Invalid compressed state bundle")
    envelope = json.loads(raw)
    if (not isinstance(envelope, dict) or set(envelope) != {"schema", "session", "states"}
            or envelope["schema"] != 1 or envelope["session"] != session):
        raise ValueError("State bundle session was not confirmed")
    _validate(envelope["states"], session)
    return envelope["states"]


def split_payload(token):
    if not isinstance(token, str) or not token or len(token) > CHUNK_SIZE * len(CHUNK_KEYS):
        raise ValueError("State transfer exceeds secret capacity")
    token.encode("ascii")
    return {name: token[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
            for index, name in enumerate(CHUNK_KEYS)}


def join_payload(values):
    chunks, ended = [], False
    for name in CHUNK_KEYS:
        value = values.get(name, "")
        if not isinstance(value, str) or len(value) > CHUNK_SIZE:
            raise ValueError("Invalid state transfer chunk")
        if not value:
            ended = True
        elif ended:
            raise ValueError("State transfer has missing chunks")
        else:
            chunks.append(value)
    token = "".join(chunks)
    split_payload(token)
    return token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("export", "import"))
    parser.add_argument("--slot", required=True, choices=SLOTS)
    parser.add_argument("--session", required=True)
    parser.add_argument("--input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        key = os.environ["MONITOR_STATE_KEY"]
        if args.mode == "export":
            token = pack_states({args.slot: read_state(args.input, key)}, args.session, key)
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(token, encoding="ascii")
        else:
            states = unpack_states(join_payload(os.environ), args.session, key)
            if set(states) != set(SLOTS):
                raise ValueError("Both source histories are required")
            write_state(args.output, key, states[args.slot])
        print(f"Encrypted state {args.mode} verified: {args.slot}")
    except Exception:
        raise SystemExit("Encrypted state handoff failed; private details omitted") from None


if __name__ == "__main__":
    main()
