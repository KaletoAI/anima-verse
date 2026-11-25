#!/usr/bin/env python3
"""Smoke run for the WORLDMAP ENCODE path (server hot paths, stage 1, task 3).

Two changes on the 3-second worldmap poll:

* ``world_props.payload_shared()`` hands out the cached world-prop rows
  WITHOUT a deep copy (read-only, for serializers); ``build_worldmap_payload``
  uses it. ``payload_snapshot`` / ``payload_rows`` keep copying (the editor
  route may change what it gets).
* ``play._json_fast(payload)`` encodes the payload in ONE C pass
  (``json.dumps(..., ensure_ascii=False, allow_nan=False,
  separators=(",", ":"), default=_encode_default)``) instead of the Python
  walk of ``jsonable_encoder`` followed by the dump of ``JSONResponse``.
  A ``TypeError`` from the dump falls back to ``_json_off_loop`` and is
  counted as ``hot_path_stats.count("worldmap_encode", "fallback")``.

Runs against a THROWAWAY storage directory — never a real world, no server,
no LLM.

Hand-derived expectations
-------------------------
starlette's ``JSONResponse.render`` is
``json.dumps(c, ensure_ascii=False, allow_nan=False, indent=None,
separators=(",", ":")).encode("utf-8")`` — the same options as the new
path, so for native values both produce the SAME bytes:

[J1] p = {"a": [1, {"b": "Grüße"}], "f": [0.1, 1e-7, -0.0], "n": None,
     "t": True}
     -> both: {"a":[1,{"b":"Grüße"}],"f":[0.1,1e-07,-0.0],"n":null,"t":true}
     (Python's float repr: 1e-7 -> "1e-07"; -0.0 stays "-0.0"; ü raw UTF-8).
[J2] {"s": {3}, "t": (1, 2), "p": Path("/x")}: the tuple is a JSON array to
     json.dumps itself; the set and the Path reach ``default`` =
     jsonable_encoder -> [3] and "/x". Both: {"s":[3],"t":[1,2],"p":"/x"}.
[J3a] {(1, 2): 1}: json.dumps refuses a tuple key (TypeError) -> fallback;
     jsonable_encoder turns the key into the list [1, 2], which cannot be a
     dict key -> TypeError. Both ways: TypeError. The new way counts the
     fallback once: count("worldmap_encode", "fallback") is called exactly
     1 time; [J1]'s native payload calls it 0 times. A count() that raises
     changes nothing: still TypeError (the old way's), never the count's
     RuntimeError.
[J3b] {"m": M.X (value "x"), "n": N.TWO (value 2)} with plain Enums: neither is
     a JSON type, both go through default -> "x" and 2.
     Both: {"m":"x","n":2}.
[J4] {"v": nan}: allow_nan=False -> ValueError on both ways.
[J7] {"_sa_x": 1, "k": 2}: jsonable_encoder drops keys with the SQLAlchemy
     prefix "_sa", json.dumps does not. New: {"_sa_x":1,"k":2}, old: {"k":2}.
     A DOCUMENTED deviation: the worldmap payload has no SQLAlchemy objects;
     such a key from author data is now delivered instead of dropped.
[J5] a tmp world with two placements of one meshed prop:
     payload_shared()[0] is payload_shared()[0] (no copy, len 2);
     payload_snapshot()[0] is not payload_shared()[0] (still a copy) and
     equal to it; build_worldmap_payload(show_all=True)["world_props"] is
     payload_shared()[0].
[J6] a POPULATED payload — the world of [J5] plus three locations
     "Alder" (0, 0), "Birch" (30, 40), "Cedar" (-20, 5), each with a 10 m
     plan_width_m footprint, and three characters: "walker" in Alder on a
     hand-written journey to Birch (waypoints [[0,0,0],[30,0,30],
     [30,40,70]], speed 1.0, started now), "sitter" in Birch, "drifter" in
     Cedar. build_worldmap_payload(show_all=True) therefore carries 3
     locations, 3 characters (the default avatar slot is empty, so nobody is
     filtered out), walker's travel block non-null with target_id Birch and
     total_m 30 + 40 = 70.0, and the 2 world-prop rows. Every value in it is
     native or reaches ``default`` one at a time, and the options of both
     ways are identical, so _json_fast(payload).body == _json_off_loop(
     payload).body BYTE FOR BYTE (a key order or separator difference would
     show here, json.loads equality would hide it). The [J7] ``_sa``
     deviation cannot fire: no key in the payload starts with "_sa".
     play_worldmap(admin, all=1) answers application/json with both world-
     prop rows and the 3 characters.

Usage:  ./.venv/bin/python scripts/smoke_worldmap_encode.py
"""
import enum
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-encode-smoke-"))
INSTANCE = Path(tempfile.mkdtemp(prefix="worldmap-encode-instance-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="worldmap-encode-clips-")
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import props as prop_store  # noqa: E402
from app.core import users  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models import world_props as wp  # noqa: E402
from app.routes import play  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def raised(fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001 — the type IS the answer
        return type(e).__name__
    return None


fast = getattr(play, "_json_fast", None)
shared = getattr(wp, "payload_shared", None)
if fast is None or shared is None:
    print(f"  ✗ names missing: play._json_fast={fast!r} "
          f"world_props.payload_shared={shared!r}")
    sys.exit(1)
old = play._json_off_loop

print("\n[J1] native values: same bytes")
p1 = {"a": [1, {"b": "Grüße"}], "f": [0.1, 1e-7, -0.0], "n": None, "t": True}
want1 = '{"a":[1,{"b":"Grüße"}],"f":[0.1,1e-07,-0.0],"n":null,"t":true}'.encode()
check("new bytes", fast(p1).body, want1)
check("old bytes", old(p1).body, want1)

print("\n[J2] set / tuple / Path")
p2 = {"s": {3}, "t": (1, 2), "p": Path("/x")}
check("new bytes", fast(p2).body, b'{"s":[3],"t":[1,2],"p":"/x"}')
check("old bytes", old(p2).body, b'{"s":[3],"t":[1,2],"p":"/x"}')

print("\n[J3a] tuple key: TypeError on both ways")
from app.core import hot_path_stats  # noqa: E402
_real_count = hot_path_stats.count
COUNTS = []
hot_path_stats.count = lambda name, key: COUNTS.append((name, key))
try:
    check("new", raised(lambda: fast({(1, 2): 1})), "TypeError")
    check("fallback counted once", COUNTS, [("worldmap_encode", "fallback")])
    del COUNTS[:]
    fast(p1)
    check("native payload counts nothing", COUNTS, [])

    def _boom(name, key):
        raise RuntimeError("smoke: count failed on purpose")

    hot_path_stats.count = _boom
    check("a raising count changes nothing", raised(lambda: fast({(1, 2): 1})),
          "TypeError")
finally:
    hot_path_stats.count = _real_count
check("old", raised(lambda: old({(1, 2): 1})), "TypeError")


class M(enum.Enum):
    X = "x"


class N(enum.Enum):
    TWO = 2


print("\n[J3b] Enums through default")
p3 = {"m": M.X, "n": N.TWO}
check("new bytes", fast(p3).body, b'{"m":"x","n":2}')
check("old bytes", old(p3).body, b'{"m":"x","n":2}')

print("\n[J4] NaN: ValueError on both ways")
check("new", raised(lambda: fast({"v": math.nan})), "ValueError")
check("old", raised(lambda: old({"v": math.nan})), "ValueError")

print("\n[J7] _sa prefix (documented deviation)")
check("new keeps it", fast({"_sa_x": 1, "k": 2}).body, b'{"_sa_x":1,"k":2}')
check("old drops it", old({"_sa_x": 1, "k": 2}).body, b'{"k":2}')

print("\n[J5] shared world-prop rows")
rec = prop_store.create_prop(name="Boulder", width_m=2.0, height_m=3.0, depth_m=1.0)
pid = rec["id"]
g = prop_store.model_gallery(pid, 0)
target = g.new_path()
target.write_bytes(b"not-a-real-glb")
g.select(target.name, "full")
wp.save_world_prop({"prop_id": pid, "x": 1.0, "z": 2.0})
wp.save_world_prop({"prop_id": pid, "x": 3.0, "z": 4.0})
s1 = shared()
s2 = shared()
check("two rows", len(s1[0]), 2)
check("shared twice is the same list", s1[0] is s2[0], True)
check("signature of shared == snapshot's", s1[1], wp.payload_snapshot()[1])
snap = wp.payload_snapshot()[0]
check("snapshot is a copy", snap is not s1[0], True)
check("snapshot equals the shared rows", snap, s1[0])
check("payload_rows is a copy", wp.payload_rows() is not s1[0], True)
payload = build_worldmap_payload(show_all=True)
check("worldmap world_props is the shared list",
      payload["world_props"] is shared()[0], True)

print("\n[J6] populated payload: same BYTES both ways")
from app.core import timeutils  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_profile, save_character_profile)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)


def place(name, x, z):
    """A location at a world-metre point with a 10 m footprint edge."""
    loc_id = add_location(name=name, description=f"{name} for the encode smoke.")["id"]
    update_location_position(loc_id, x, z)
    data = _load_world_data()
    for entry in data.get("locations", []):
        if entry.get("id") == loc_id:
            entry["map3d"] = {**(entry.get("map3d") or {}), "plan_width_m": 10.0}
    _save_world_data(data)
    return loc_id


ALDER = place("Alder", 0.0, 0.0)
BIRCH = place("Birch", 30.0, 40.0)
CEDAR = place("Cedar", -20.0, 5.0)
for who, where in (("walker", ALDER), ("sitter", BIRCH), ("drifter", CEDAR)):
    save_character_profile(who, {"current_location": where}, create_new=True)
with keyed_lock("character_profile", "walker"):
    prof = get_character_profile("walker")
    prof["journey"] = {"target": BIRCH,
                       "waypoints": [[0.0, 0.0, 0.0], [30.0, 0.0, 30.0],
                                     [30.0, 40.0, 70.0]],
                       "started_at_s": float(timeutils.motion_time()),
                       "speed_m_s": 1.0, "entry_edge": "",
                       "journey_id": "a" * 32}
    prof["movement_target"] = BIRCH
    save_character_profile("walker", prof)

full = build_worldmap_payload(show_all=True)
chars = {c.get("name"): c for c in full.get("characters") or []}
check("3 locations", len(full.get("locations") or []), 3)
check("3 characters", sorted(chars), ["drifter", "sitter", "walker"])
travel = (chars.get("walker") or {}).get("travel") or {}
check("walker travels to Birch", travel.get("target_id"), BIRCH)
check("walker total_m", travel.get("total_m"), 70.0)
check("2 world-prop rows", len(full.get("world_props") or []), 2)


def sa_keys(o):
    if isinstance(o, dict):
        return [k for k in o if str(k).startswith("_sa")] + \
            [x for v in o.values() for x in sa_keys(v)]
    if isinstance(o, (list, tuple)):
        return [x for v in o for x in sa_keys(v)]
    return []


check("no _sa key anywhere", sa_keys(full), [])
new_body, old_body = fast(full).body, old(full).body
check("byte-identical bodies", new_body == old_body, True)
check("non-trivial body (> 1000 bytes)", len(new_body) > 1000, True)
resp = play.play_worldmap(user={"id": "admin1", "role": users.ROLE_ADMIN,
                                "settings": {}}, show_all=1)
check("route media type", resp.media_type, "application/json")
body = json.loads(resp.body)
check("route body has both world-prop rows", len(body["world_props"]), 2)
check("route body has the 3 characters", len(body["characters"]), 3)

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
