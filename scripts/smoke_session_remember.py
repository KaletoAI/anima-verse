#!/usr/bin/env python3
"""Smoke: per-session remember TTL, additive migration and both cookie writers.

Usage: ./.venv/bin/python scripts/smoke_session_remember.py

Hand-derived expectations from Task 76: default sessions last 24 hours,
24 * 60 * 60 = 86400 seconds; remembered sessions last 30 days,
30 * 24 = 720 hours = 2592000 seconds. Only JSON true selects 30 days;
missing, false, null, 1, "true" and "yes" select 24 hours. Sliding after
120 seconds exceeds the 60-second throttle and renews the ORIGINAL TTL in
both the DB and HTTP/SSE cookie. A legacy row with NULL ttl_hours uses 24
hours. Peeking never slides. Running schema initialization twice on an old
user_sessions table adds the column once and preserves its existing row.
All paths are temporary; app.server is never imported.
"""
import asyncio
import os
from datetime import timedelta
from http.cookies import SimpleCookie
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="session-remember-smoke-")
ROOT = Path(TMP.name)
os.environ["STORAGE_DIR"] = str(ROOT / "world")
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import config, db
config.load(ROOT / "world" / "config.json")
from app.core import auth_dependency, sessions, sync_stream, users
from app.core.timeutils import parse_iso, utc_now
from app.routes import auth
from fastapi import FastAPI
from fastapi.testclient import TestClient


def row(token):
    return dict(db.get_connection().execute(
        "SELECT * FROM user_sessions WHERE token=?", (token,)).fetchone())


def cookie_age(header):
    cookie = SimpleCookie()
    cookie.load(header)
    return int(cookie["av_session"]["max-age"])


async def stream_headers(token):
    """Connect the real SSE endpoint, then disconnect after its headers."""
    started = asyncio.Event()
    messages = []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            started.set()

    async def receive():
        await started.wait()
        return {"type": "http.disconnect"}

    scope = {"type": "http", "path": "/events/sync", "method": "GET",
             "scheme": "https", "headers": [(b"cookie", f"av_session={token}".encode())]}
    await asyncio.wait_for(sync_stream._serve(scope, receive, send), timeout=5)
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200, start
    return [value.decode() for key, value in start["headers"] if key == b"set-cookie"]


# Model the pre-migration table, with a real row already in it at boot.
with db.transaction() as conn:
    conn.execute("CREATE TABLE user_sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
                 "created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_activity TEXT NOT NULL)")
    now = utc_now()
    conn.execute("INSERT INTO user_sessions VALUES (?, ?, ?, ?, ?)",
                 ("legacy-token", "legacy-user", now.isoformat(),
                  (now + timedelta(hours=24)).isoformat(), now.isoformat()))
db.init_schema()
db.init_schema()
assert "ttl_hours" in row("legacy-token"), "existing-world migration must add ttl_hours"
assert row("legacy-token")["ttl_hours"] is None
print("PASS: additive migration reruns and preserves the legacy row")

uid = users.create_user("demo", "demo-password")
with db.transaction() as conn:
    conn.execute("UPDATE user_sessions SET user_id=? WHERE token='legacy-token'", (uid,))

app = FastAPI()
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.middleware("http")(auth_dependency.user_context_middleware)
app.include_router(auth.router)

with TestClient(app) as client, patch.object(sessions, "_now") as clock:
    current = utc_now()
    clock.side_effect = lambda: current
    remembered = ""
    for extra, hours, seconds in [({}, 24, 86400), ({"remember": False}, 24, 86400),
                                  ({"remember": "yes"}, 24, 86400),
                                  ({"remember": 1}, 24, 86400),
                                  ({"remember": "true"}, 24, 86400),
                                  ({"remember": None}, 24, 86400),
                                  ({"remember": True}, 720, 2592000)]:
        client.cookies.clear()
        response = client.post("/auth/login", json={"username": "demo", "password": "demo-password", **extra})
        assert response.status_code == 200, response.text
        token = response.cookies["av_session"]
        stored = row(token)
        assert parse_iso(stored["expires_at"]) == current + timedelta(seconds=seconds), stored
        assert stored["ttl_hours"] == hours, stored
        assert cookie_age(response.headers["set-cookie"]) == seconds, response.headers
        if extra.get("remember") is True:
            remembered = token
        print(f"PASS: login {extra!r} => {hours} hours, Max-Age={seconds}")

    # Direct callers retain the default and may opt into remember as well.
    for remember, seconds in [(False, 86400), (True, 2592000)]:
        token = sessions.create_session(uid, remember=remember)
        assert parse_iso(row(token)["expires_at"]) == current + timedelta(seconds=seconds)

    # The remembered and legacy sessions exercise both slide-cookie writers.
    for token, seconds in [(remembered, 2592000), ("legacy-token", 86400)]:
        for writer in ("http", "sse"):
            before = row(token)
            current += timedelta(seconds=120)
            assert sessions.peek_session(token) is not None
            assert row(token) == before, "peek must not slide"
            if writer == "http":
                client.cookies.clear()
                client.cookies.set("av_session", token)
                response = client.get("/auth/status")
                assert response.json()["authenticated"] is True, response.text
                cookies = response.headers.get_list("set-cookie")
            else:
                cookies = asyncio.run(stream_headers(token))
                assert "Secure" in cookies[0], cookies
            assert len(cookies) == 1, cookies
            assert cookie_age(cookies[0]) == seconds, cookies
            assert parse_iso(row(token)["expires_at"]) == current + timedelta(seconds=seconds)
            print(f"PASS: {writer} slide => original TTL {seconds} seconds")

    # An existing session must not overwrite a new login's cookie TTL.
    current += timedelta(seconds=120)
    client.cookies.clear()
    client.cookies.set("av_session", remembered)
    response = client.post("/auth/login", json={"username": "demo", "password": "demo-password"})
    assert len(response.headers.get_list("set-cookie")) == 1
    assert cookie_age(response.headers["set-cookie"]) == 86400
    print("PASS: login cookie takes precedence over the previous session's slide")

    client.cookies.clear()
    client.cookies.set("av_session", remembered)
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert sessions.peek_session(remembered) is None
    assert cookie_age(response.headers["set-cookie"]) == 0
    print("PASS: remembered logout deletes the row and clears the cookie")

print("All remember-session checks passed")
