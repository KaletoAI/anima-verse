#!/usr/bin/env python3
"""POST /play/bench-result appends one JSON line per run (native-client spike).

Usage:
    ./.venv/bin/python scripts/smoke_bench_result_route.py

Run outside the Codex sandbox: its FastAPI TestClient transport can hang.

Expected, by hand from the route's contract:
  * anonymous POST                       -> 401 (default-deny auth gate)
  * a JSON object as a player            -> 200, the log gains exactly ONE line
    {"received": <iso>, "user": "bench-player", "result": <the object>}
  * a JSON array                         -> 400 (must be an object), no line
  * not JSON                             -> 400, no line
  * 64 KB + 1 byte                       -> 413, no line
So after the five requests the log holds exactly 1 line. The log path is
redirected into the temp dir; the real logs/bench.jsonl is never touched.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="bench-result-route-") as temporary:
        root = Path(temporary)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        from app.server import app
        from app.routes import play
        from app.core import users
        from fastapi.testclient import TestClient

        log = root / "logs" / "bench.jsonl"
        play._BENCH_LOG = log
        anonymous = TestClient(app)
        assert anonymous.post("/play/bench-result", json={"fps": 1}).status_code == 401

        users.create_user("bench-player", "smoke-password", role="user")
        client = TestClient(app)
        assert client.post("/auth/login", json={
            "username": "bench-player", "password": "smoke-password"}).status_code == 200

        result = {"backend": "webgl", "fpsMean": 42.5, "flags": {"scatter": False}}
        r = client.post("/play/bench-result", json=result)
        assert r.status_code == 200, r.text
        assert client.post("/play/bench-result", json=[1, 2]).status_code == 400
        assert client.post("/play/bench-result", content=b"not json",
                           headers={"Content-Type": "application/json"}).status_code == 400
        big = b'{"x":"' + b"a" * (64 * 1024) + b'"}'
        assert client.post("/play/bench-result", content=big,
                           headers={"Content-Type": "application/json"}).status_code == 413

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, lines
        entry = json.loads(lines[0])
        assert entry["user"] == "bench-player"
        assert entry["result"] == result
        assert entry["received"]
        print("PASS: bench result route — auth, one line per run, 400/413 rejected")


if __name__ == "__main__":
    main()
