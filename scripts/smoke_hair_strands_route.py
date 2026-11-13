#!/usr/bin/env python3
"""The strand record's routes and model info (``app/routes/characters.py``, ``model3d.get_model3d_info``) —
strand-hair plan 2026-11-13, Task 6 (spec § 6.2.3 "Routes"). Expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_hair_strands_route.py

Runs ``app.server.app`` (the auth gate included) against a THROWAWAY storage + instance directory
(``STORAGE_DIR`` / ``INSTANCE_DIR`` set before the import) with a TestClient — no world, no hub, no server
process; outbound connections are refused. Two users: an admin and a player (role user, allowed ``demo``).

Fixture: the character ``demo``; a record file ``fixture.strands.json`` = ``{"version": 1, "cards": 2, ...}``
written with ``hair_strands.encode``, sha = sha256 of its bytes. Stubs: ``hair_strands.served_file`` -> (that
file, sha) or None (switched per check); ``garments.preview_path`` -> a fixture path; ``hair_strands.
record_for_fit`` -> the fixture record; ``model3d.find_model3d_serving`` -> a fixture GLB in demo's model dir
(the model info needs a served model to carry ``model``).

[1] GET /characters/demo/model/hair-strands as a PLAYER session -> 200, body == the fixture bytes (JSON equal),
    ETag == '"<sha>"', Content-Type application/json; again with If-None-Match: '"<sha>"' -> 304, empty body; a
    weak 'W/"<sha>"' matches too (``etag_matches``); another tag -> 200.
[2] served_file() None -> 404 (also for the admin).
[3] GET /characters/demo/garments/it1/hair-strands as player -> 403; as admin -> 200 with the same bytes and ETag;
    record_for_fit None -> 404.
[4] GET /characters/demo/model3d (admin) -> model.hair_strands == {"url": "/characters/demo/model/hair-strands",
    "sha256": sha}; served_file() None -> model.hair_strands None.
[5] scripts/smoke_auth_gate.py still passes (run as a subprocess).
[6] GET /characters/demo/garments/it1/model (the Hairstyles preview GLB, Ruling H-R5) with ``hair_strands.
    preview_version`` / ``preview_glb`` stubbed: player 403; admin with ``v`` == the version -> 200, the built
    bytes, ETag '"<version>"', immutable; another ``v`` -> no-cache; If-None-Match the version -> 304 without
    building; no preview fit -> 404. (Run before [5]; numbered after it.)
"""
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
CHAR = "demo"


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _no_net(*_a, **_k):
    raise OSError("smoke: outbound connections are refused")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_hair_strands_route_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    try:
        return run_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(tmp):
    real_connect = socket.socket.connect

    def guarded(self, address, *a, **k):
        # the TestClient talks in-process; only a real outbound connection is refused
        if isinstance(address, tuple):
            return _no_net()
        return real_connect(self, address, *a, **k)
    real_connect_ex = socket.socket.connect_ex

    def guarded_ex(self, address, *a, **k):
        if isinstance(address, tuple):
            return 111                   # ECONNREFUSED
        return real_connect_ex(self, address, *a, **k)
    socket.socket.connect = guarded
    socket.socket.connect_ex = guarded_ex
    socket.create_connection = _no_net
    from app.core import paths
    paths.init(tmp / "world")
    from app.server import app
    from fastapi.testclient import TestClient
    from app.core import garments, hair_strands, model3d, users
    from app.models.character import get_character_dir
    get_character_dir(CHAR, create=True)

    record = {"version": 1, "item_id": "it1", "fsig": "0123456789ab", "mode": "hairdeck", "cards": 2,
              "rest": [0.0] * 102, "pins": [2, 1]}
    data = hair_strands.encode(record)
    sha = hashlib.sha256(data).hexdigest()
    record_file = tmp / "fixture.strands.json"
    record_file.write_bytes(data)
    state = {"served": (record_file, sha), "record": record}
    hair_strands.served_file = lambda name, profile=None, path=None: state["served"]
    hair_strands.record_for_fit = lambda name, fit: state["record"]
    garments.preview_path = lambda name, item_id, method="": tmp / "fixture_fit.glb"
    model_dir = model3d.get_model3d_dir(CHAR)
    model_dir.mkdir(parents=True, exist_ok=True)
    glb = model_dir / "outfit0123ab.glb"
    glb.write_bytes(b"glTF-fixture")
    model3d.find_model3d_serving = lambda name: (glb, "exact")

    users.create_user("strands-admin", "smoke-password", role="admin")
    users.create_user("strands-player", "smoke-password", role="user", allowed_characters=[CHAR])
    admin, player = TestClient(app), TestClient(app)
    check(admin.post("/auth/login", json={"username": "strands-admin", "password": "smoke-password"}).status_code
          == 200, "admin login")
    check(player.post("/auth/login", json={"username": "strands-player", "password": "smoke-password"}).status_code
          == 200, "player login")

    # [1] the public record route
    url = f"/characters/{CHAR}/model/hair-strands"
    r = player.get(url)
    check(r.status_code == 200, f"[1] player GET {url} -> 200 (got {r.status_code})")
    check(r.content == data and r.json() == record, "[1] body == the fixture record")
    check(r.headers.get("etag") == f'"{sha}"', f"[1] ETag \"<sha>\" (got {r.headers.get('etag')})")
    check((r.headers.get("content-type") or "").startswith("application/json"), "[1] application/json")
    r = player.get(url, headers={"If-None-Match": f'"{sha}"'})
    check(r.status_code == 304 and r.content == b"", f"[1] If-None-Match -> 304, empty (got {r.status_code})")
    r = player.get(url, headers={"If-None-Match": f'W/"{sha}"'})
    check(r.status_code == 304, f"[1] weak tag -> 304 (got {r.status_code})")
    r = player.get(url, headers={"If-None-Match": '"other"'})
    check(r.status_code == 200 and r.content == data, f"[1] another tag -> 200 (got {r.status_code})")

    # [2] no strands
    state["served"] = None
    check(player.get(url).status_code == 404 and admin.get(url).status_code == 404, "[2] served_file None -> 404")
    state["served"] = (record_file, sha)

    # [3] the admin preview route
    purl = f"/characters/{CHAR}/garments/it1/hair-strands"
    r = player.get(purl)
    check(r.status_code == 403, f"[3] player GET {purl} -> 403 (got {r.status_code})")
    r = admin.get(purl)
    check(r.status_code == 200 and r.content == data and r.headers.get("etag") == f'"{sha}"',
          f"[3] admin -> 200, the record, ETag (got {r.status_code})")
    check(admin.get(purl, headers={"If-None-Match": f'"{sha}"'}).status_code == 304, "[3] admin If-None-Match -> 304")
    state["record"] = None
    check(admin.get(purl).status_code == 404, "[3] no record -> 404")
    state["record"] = record

    # [4] the model info
    r = admin.get(f"/characters/{CHAR}/model3d")
    model = (r.json() if r.status_code == 200 else {}).get("model") or {}
    check(r.status_code == 200 and model.get("hair_strands") == {"url": url, "sha256": sha},
          f"[4] model.hair_strands == {{url, sha256}} (got {r.status_code}, {model.get('hair_strands')})")
    state["served"] = None
    model = (admin.get(f"/characters/{CHAR}/model3d").json() or {}).get("model") or {}
    check("hair_strands" in model and model["hair_strands"] is None, "[4] no record -> model.hair_strands None")

    # [6] the preview GLB route (Ruling H-R5): preview_version / preview_glb stubbed (their content is
    #     smoke_hair_strands_record.py [11]); version "abcdef0123456789.s1", bytes b"glTF-with-binding"
    ver = "abcdef0123456789.s1"
    calls = []
    hair_strands.preview_version = lambda fit: ver
    hair_strands.preview_glb = lambda name, fit: calls.append(fit) or (b"glTF-with-binding", ver)
    murl = f"/characters/{CHAR}/garments/it1/model"
    check(player.get(murl).status_code == 403, "[6] player GET the preview GLB -> 403")
    r = admin.get(murl + f"?v={ver}")
    check(r.status_code == 200 and r.content == b"glTF-with-binding" and r.headers.get("etag") == f'"{ver}"'
          and "immutable" in (r.headers.get("cache-control") or "")
          and (r.headers.get("content-type") or "").startswith("model/gltf-binary"),
          f"[6] admin ?v=<version> -> 200, the built bytes, ETag, immutable (got {r.status_code}, "
          f"{r.headers.get('etag')}, {r.headers.get('cache-control')})")
    r = admin.get(murl + "?v=older")
    check(r.status_code == 200 and r.headers.get("cache-control") == "no-cache", "[6] another v -> no-cache")
    n = len(calls)
    r = admin.get(murl, headers={"If-None-Match": f'"{ver}"'})
    check(r.status_code == 304 and len(calls) == n, "[6] If-None-Match -> 304 without building")
    garments.preview_path = lambda name, item_id, method="": None
    check(admin.get(murl).status_code == 404, "[6] no preview fit -> 404")

    # [5] the auth gate smoke
    env = {k: v for k, v in os.environ.items() if k not in ("STORAGE_DIR", "INSTANCE_DIR")}
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_auth_gate.py")], cwd=str(ROOT), env=env,
                         capture_output=True, text=True, timeout=600)
    tail = (out.stdout.strip().splitlines() or [""])[-1]
    check(out.returncode == 0, f"[5] smoke_auth_gate.py passes ({tail})")

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
