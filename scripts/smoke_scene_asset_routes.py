#!/usr/bin/env python3
"""Smoke check: the scene-asset pipeline's HTTP surface (Etappe 4 Punkt 6).

Usage:  ./.venv/bin/python scripts/smoke_scene_asset_routes.py

No server, no world.db, no GPU: the router is mounted on a bare FastAPI app,
the world lookup and the trigger are replaced by fakes, and a THROWAWAY prop
directory holds one hand-written run. What is checked is the CONTRACT, derived
by hand from the route docstrings — never recorded from output.

  1. POST /generate
       unknown location / room / index          -> 404, and nothing triggered
       a known placement                        -> 200 {status: "generating"}
       the trigger saying False (already out)   -> 409, the double-start guard
       seed / backend globs                     -> forwarded to the trigger
       placement_index "abc"                    -> 400 before anything runs

  2. GET /status
       running is the KEY test against is_running: "loc|room|3" and nothing
       else — a run on placement 4 of the same prop must not light up 3.
       last_run is the newest run OF THIS PLACEMENT. The prop's directory
       holds three runs by hand:
         20260101-000000  room=hall  index=3  ok=false   (oldest)
         20260102-000000  room=hall  index=4  ok=true    (other placement)
         20260103-000000  room=hall  index=3  ok=true    (newest, ours)
       Newest first by directory name, so the expected answer for index 3 is
       20260103-000000 and for index 4 is 20260102-000000.

  3. The summary shape, hand-derived from the run record written below:
       ok, backend "gw-inpaint", path "inpaint", seed 4242 (the LAST attempt's
       seed, not the first), attempts 2, variant 1, stored_variant 1,
       checks.px_ratio 1.05 from the last attempt, checks.contact_ratio 1.0,
       checks.px_ratio_band [0.4, 2.5] and contact_ratio_min 0.6 from params,
       and files carrying the LAST ATTEMPT's edit/cutout (edit-2.png) over the
       run's own context/mask. Every file is a URL under this very route.

  4. GET /runs/{prop_id}: three runs, newest first; ?limit=1 gives one; an
       unknown prop is a 404 (not an empty list — the id is wrong, not the
       history).

  5. Artefact serving, the path-escape rule (routes/assets.resolve_clip_path):
       "<stamp>/context.png"          -> 200 + the bytes + an ETag
       the same with If-None-Match    -> 304
       one segment / three segments   -> 400
       "..", ".", "" as a segment     -> 400
       a backslash in a segment       -> 400
       a non-PNG                      -> 400
       an escape via an encoded slash -> 400  (%2F..%2F.. reaches the handler)
       a legal but absent file        -> 404
       an unsafe prop id ("../x")     -> 400  (prop_dir refuses it, no root)

  6. POST /placement: patches through update_prop_placement, 400 on an empty
       patch, 404 when the writer reports the placement is gone.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="scene-asset-routes-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE / "world")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.routes import scene_asset as route  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def equals(label: str, actual, expected) -> None:
    check(label, actual == expected, "" if actual == expected
          else f"expected {expected!r}, got {actual!r}")


# ── The fake world ──────────────────────────────────────────────────────
# One location, one room, two placements of the same prop. The route reads the
# STORED world through get_location_by_id; nothing else about a world exists
# here, which is the point — the route's own logic is what is under test.

PROP_ID = "bench-abc123"
LOCATION = {
    "id": "loc1",
    "rooms": [
        {"id": "hall", "layout": {"props": [
            {"prop_id": "other", "at": [0, 0]},
            {"prop_id": "other", "at": [1, 0]},
            {"prop_id": "other", "at": [2, 0]},
            {"prop_id": PROP_ID, "at": [3, 0], "variant": 1, "yaw": 90},
            {"prop_id": PROP_ID, "at": [4, 0]},
        ]}},
        {"id": "__ground__", "layout": {"props": [
            {"prop_id": PROP_ID, "at": [10, 10]},
        ]}},
    ],
}

import app.models.world as world_model  # noqa: E402

world_model.get_location_by_id = lambda lid: (
    LOCATION if lid == LOCATION["id"] else None)

PROPS = STORAGE / "props"


def fake_prop_dir(prop_id: str, *, create: bool = False):
    """The real safe-id rule, a throwaway root — an unsafe id still gives
    None, which is what the escape test at the prop level rides on."""
    import re
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", (prop_id or "").strip().lower()):
        return None
    d = PROPS / prop_id.strip().lower()
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


import app.core.props as prop_store  # noqa: E402

prop_store.prop_dir = fake_prop_dir
prop_store.get_prop = lambda pid: ({"id": pid} if fake_prop_dir(pid) and
                                   (PROPS / pid).is_dir() else None)

# ── The hand-written run history ────────────────────────────────────────

RUNS = PROPS / PROP_ID / "scene_asset"


def write_run(stamp: str, room_id: str, index: int, ok: bool,
              full: bool = False) -> None:
    d = RUNS / stamp
    d.mkdir(parents=True, exist_ok=True)
    (d / "context.png").write_bytes(b"CONTEXT")
    (d / "mask.png").write_bytes(b"MASK")
    (d / "edit.png").write_bytes(b"EDIT1")
    (d / "edit-2.png").write_bytes(b"EDIT2")
    (d / "cutout-2.png").write_bytes(b"CUTOUT2")
    rec = {
        "version": 1, "location_id": "loc1", "room_id": room_id,
        "index": index, "prop_id": PROP_ID, "subject": "a wooden bench",
        "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:02:00Z",
        "seconds": 120.0, "backend": "gw-inpaint", "path": "inpaint",
        "variant": 1, "ok": ok, "failures": [] if ok else ["mesh: height off"],
        "params": {"px_ratio_min": 0.4, "px_ratio_max": 2.5,
                   "contact_ratio": 0.6},
        "files": {"context": str(d / "context.png"), "mask": str(d / "mask.png")},
        "attempts": [
            {"attempt": 0, "seed": 1111, "px_ratio": 0.31,
             "failures": ["drawn object 0.31× the expected pixel height"],
             "files": {"edit": str(d / "edit.png")}},
            {"attempt": 1, "seed": 4242, "px_ratio": 1.05, "ok": ok,
             "files": {"edit": str(d / "edit-2.png"),
                       "cutout": str(d / "cutout-2.png")},
             "mesh": {"ok": True, "height_m": 0.92, "backend": "mesher"},
             "placement": {"yaw_deg": 137.0, "offset_y": -0.02,
                           "sank_m": 0.02, "contact_ratio": 1.0},
             "stored_placement": {"prop_id": PROP_ID, "variant": 1}},
        ],
    }
    if full:
        rec["placement"] = rec["attempts"][1]["placement"]
        rec["mesh"] = rec["attempts"][1]["mesh"]
    (d / "result.json").write_text(json.dumps(rec), encoding="utf-8")


write_run("20260101-000000", "hall", 3, ok=False)
write_run("20260102-000000", "hall", 4, ok=True, full=True)
write_run("20260103-000000", "hall", 3, ok=True, full=True)
# A directory still writing has no result.json and must be invisible.
(RUNS / "20260104-000000").mkdir(parents=True, exist_ok=True)

client = TestClient(FastAPI())
client.app.include_router(route.router)


# ── 1. POST /generate ───────────────────────────────────────────────────

print("\n1. POST /generate")

CALLS = []
TRIGGER_RESULT = [True]


def fake_trigger(location_id, room_id, placement_index, **kw):
    CALLS.append((location_id, room_id, placement_index, kw))
    return TRIGGER_RESULT[0]


import app.core.scene_asset as core  # noqa: E402

core.trigger_scene_asset = fake_trigger

r = client.post("/world/scene-asset/generate",
                json={"location_id": "nope", "room_id": "hall",
                      "placement_index": 3})
equals("unknown location -> 404", r.status_code, 404)
r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "attic",
                      "placement_index": 3})
equals("unknown room -> 404", r.status_code, 404)
r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 99})
equals("index out of range -> 404", r.status_code, 404)
r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "",
                      "placement_index": 0})
equals("empty room_id names nothing -> 404", r.status_code, 404)
equals("nothing triggered by the four refusals", CALLS, [])

r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3, "seed": 77,
                      "image_backend": "gw-*", "mesh_backend": "mesh-*",
                      "subject": " a bench "})
equals("a known placement -> 200", r.status_code, 200)
equals("body", r.json(), {"status": "generating", "prop_id": PROP_ID})
equals("trigger got the target", CALLS[0][:3], ("loc1", "hall", 3))
equals("seed forwarded as an override", CALLS[0][3]["overrides"], {"seed": 77})
equals("image glob forwarded", CALLS[0][3]["image_backend_glob"], "gw-*")
equals("mesh glob forwarded", CALLS[0][3]["mesh_backend_glob"], "mesh-*")
equals("subject trimmed", CALLS[0][3]["subject"], "a bench")

CALLS.clear()
r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "__ground__",
                      "placement_index": 0})
equals("the yard is an ordinary room -> 200", r.status_code, 200)
equals("no override without a seed", CALLS[0][3]["overrides"], None)

CALLS.clear()
TRIGGER_RESULT[0] = False
r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3})
equals("double start -> 409", r.status_code, 409)
check("409 says what it is", "already generating" in r.json().get("detail", ""),
      r.json().get("detail", ""))
TRIGGER_RESULT[0] = True

CALLS.clear()
r = client.post("/world/scene-asset/generate",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": "abc"})
equals("a non-numeric index -> 400", r.status_code, 400)
equals("and nothing was triggered", CALLS, [])


# ── 2./3. GET /status ───────────────────────────────────────────────────

print("\n2. GET /status")

core.is_running = lambda location_id="": ["loc1|hall|4"]

r = client.get("/world/scene-asset/status",
               params={"location_id": "loc1", "room_id": "hall",
                       "placement_index": 3})
equals("status 200", r.status_code, 200)
st = r.json()
equals("a run on 4 does not light up 3", st["running"], False)
equals("prop id", st["prop_id"], PROP_ID)
equals("the stored placement rides along", st["placement"],
       {"variant": 1, "yaw": 90, "offset_y": None})

r = client.get("/world/scene-asset/status",
               params={"location_id": "loc1", "room_id": "hall",
                       "placement_index": 4})
equals("the key that IS running", r.json()["running"], True)
equals("newest run of placement 4", r.json()["last_run"]["stamp"],
       "20260102-000000")

r = client.get("/world/scene-asset/status",
               params={"location_id": "loc1", "room_id": "__ground__",
                       "placement_index": 0})
equals("a placement without any run -> null", r.json()["last_run"], None)

print("\n3. The summary shape")
last = st["last_run"]
equals("newest run of placement 3", last["stamp"], "20260103-000000")
equals("ok", last["ok"], True)
equals("backend", last["backend"], "gw-inpaint")
equals("path", last["path"], "inpaint")
equals("seed is the LAST attempt's", last["seed"], 4242)
equals("attempts", last["attempts"], 2)
equals("variant", last["variant"], 1)
equals("stored variant", last["stored_variant"], 1)
equals("failures", last["failures"], [])
equals("px ratio from the last attempt", last["checks"]["px_ratio"], 1.05)
equals("px band from params", last["checks"]["px_ratio_band"], [0.4, 2.5])
equals("contact ratio", last["checks"]["contact_ratio"], 1.0)
equals("contact minimum from params", last["checks"]["contact_ratio_min"], 0.6)
equals("yaw", last["checks"]["yaw_deg"], 137.0)
equals("mesh height", last["checks"]["mesh_height_m"], 0.92)
BASE = f"/world/scene-asset/runs/{PROP_ID}/20260103-000000"
equals("context url", last["files"]["context"], f"{BASE}/context.png")
equals("mask url", last["files"]["mask"], f"{BASE}/mask.png")
equals("edit url is the LAST attempt's", last["files"]["edit"],
       f"{BASE}/edit-2.png")
equals("cutout url is the LAST attempt's", last["files"]["cutout"],
       f"{BASE}/cutout-2.png")

# A FAILED run still shows its pictures and says why in words.
r = client.get(f"/world/scene-asset/runs/{PROP_ID}")
runs = r.json()["runs"]
failed = next(x for x in runs if x["stamp"] == "20260101-000000")
equals("a failed run keeps its edit picture", failed["files"]["edit"],
       f"/world/scene-asset/runs/{PROP_ID}/20260101-000000/edit-2.png")
equals("and says why in words", failed["failures"], ["mesh: height off"])


# ── 4. GET /runs/{prop_id} ──────────────────────────────────────────────

print("\n4. GET /runs/{prop_id}")
equals("three readable runs (the writing one is invisible)", len(runs), 3)
equals("newest first", [x["stamp"] for x in runs],
       ["20260103-000000", "20260102-000000", "20260101-000000"])
r = client.get(f"/world/scene-asset/runs/{PROP_ID}", params={"limit": 1})
equals("limit", [x["stamp"] for x in r.json()["runs"]], ["20260103-000000"])
r = client.get("/world/scene-asset/runs/ghost-prop")
equals("unknown prop -> 404", r.status_code, 404)


# ── 5. Artefact serving ─────────────────────────────────────────────────

print("\n5. Artefacts + the path-escape rule")
r = client.get(f"{BASE}/context.png")
equals("a legal artefact -> 200", r.status_code, 200)
equals("the bytes", r.content, b"CONTEXT")
etag = r.headers.get("etag", "")
check("carries an ETag", bool(etag), etag)
r = client.get(f"{BASE}/context.png", headers={"If-None-Match": etag})
equals("revalidation -> 304", r.status_code, 304)

# The dot segments are sent PERCENT-ENCODED on purpose: an HTTP client
# collapses "a/./b" and "a/../b" in the URL itself, so a plain spelling would
# never reach the handler and the check would prove nothing about it. Encoded,
# the segment arrives verbatim in the path parameter — which is exactly the
# shape an attacker sends.
for label, rel in [
    ("one segment", "context.png"),
    ("three segments", "20260103-000000/sub/context.png"),
    ("a '..' segment", "20260103-000000%2F..%2Fcontext.png"),
    ("a '.' segment", "20260103-000000%2F.%2Fcontext.png"),
    ("an empty segment", "20260103-000000%2F%2Fcontext.png"),
    ("a backslash", "20260103-000000/..\\context.png"),
    ("a non-PNG", "20260103-000000/result.json"),
    ("an escape out of the prop", "..%2F..%2Fsecrets.png"),
]:
    r = client.get(f"/world/scene-asset/runs/{PROP_ID}/{rel}")
    equals(f"{label} -> 400", r.status_code, 400)

r = client.get(f"{BASE}/nothing.png")
equals("a legal but absent file -> 404", r.status_code, 404)
r = client.get("/world/scene-asset/runs/..%2F..%2Fetc/20260103-000000/x.png")
equals("an unsafe prop id -> 400", r.status_code, 400)


# ── 6. POST /placement ──────────────────────────────────────────────────

print("\n6. POST /placement")

import app.core.world_ops as world_ops  # noqa: E402

PATCHES = []


def fake_update(location_id, room_id, index, patch):
    PATCHES.append((location_id, room_id, index, patch))
    return None if patch.get("variant") == 99 else {"prop_id": PROP_ID, **patch}


world_ops.update_prop_placement = fake_update

r = client.post("/world/scene-asset/placement",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3, "variant": 2})
equals("a variant patch -> 200", r.status_code, 200)
equals("stored placement comes back", r.json()["placement"],
       {"prop_id": PROP_ID, "variant": 2})
equals("the writer got it", PATCHES[-1], ("loc1", "hall", 3, {"variant": 2}))

r = client.post("/world/scene-asset/placement",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3, "yaw": 12.5, "offset_y": -0.1})
equals("yaw + offset are floats", PATCHES[-1][3], {"yaw": 12.5, "offset_y": -0.1})

r = client.post("/world/scene-asset/placement",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3})
equals("an empty patch -> 400", r.status_code, 400)

r = client.post("/world/scene-asset/placement",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3, "variant": "x"})
equals("a non-numeric variant -> 400", r.status_code, 400)

r = client.post("/world/scene-asset/placement",
                json={"location_id": "loc1", "room_id": "hall",
                      "placement_index": 3, "variant": 99})
equals("the writer reporting it is gone -> 404", r.status_code, 404)


# ── Result ──────────────────────────────────────────────────────────────

shutil.rmtree(STORAGE, ignore_errors=True)
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
