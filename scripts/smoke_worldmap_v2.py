#!/usr/bin/env python3
"""Smoke run for the worldmap payload v2 + /play/terrain
(Seamless World, E1 Task 6).

Runs against a THROWAWAY storage directory — never touches a real world.

The grid is gone: locations carry metre positions (``pos_x``/``pos_z``),
a rotation (``yaw_deg``) and a DRAWN BOUNDARY (``map3d.boundary``, contract
v6). The payload therefore reports ``world_bounds`` in metres instead of
``grid_bounds`` in cells, hoists the boundary and its derived bounding-box
width (``plan_width_m``) to the top of each entry and hands every character
its free metre position. Since 2026-08-19 a location WITHOUT a boundary has
no area at all — no square is synthesized for it any more — which is exactly
what the "post" of the seed below is here to prove.

Seed (hand-built, so every expectation below is derived from it and not
recorded from an implementation run):

    inn    at (50, 50),  centred 10 m square boundary, yaw 90  -> half 5
    farm   at (-30, 20), centred 40 m square boundary          -> half 20
    post   at (70, -10), NO boundary                           -> no area
    ghost  unplaced
    water area [[0,0],[20,0],[20,20],[0,20]], type override "grass" renamed
    demo_avatar at inn (via save_character_current_location -> pos (50, 50))
    npc_w  via set_character_pos(30, 30) -> wilderness (location "")

Hand-derived expectations:

  [1] show_all=True: locations = inn + farm + post + ghost (unplaced
      passes); inn entry has pos_x 50.0, yaw_deg 90.0, plan_width_m 10.0
      (DERIVED from its boundary's 10 × 10 bounding box) and NO
      grid_x/surface_kind/map_rotation_2d keys. ``passable``
      came BACK with the avatar journey (E3, Task 5): a destination list
      drops transit tiles by it, so the inn carries it as False. post is
      placed but BOUNDARY-LESS: pos_x 70.0, boundary null AND
      plan_width_m null — it has no area anywhere. The inn also
      carries a ``layout_sig`` although it has no room at all — the
      signature covers ``map3d`` since E5 B11, and the inn has one
      (the boundary). post, without map3d and without rooms, has none.
  [2] world_bounds: min_x = -50 (farm -30-20), max_x = 70 (post's bare
      centre, further out than inn's 50+5), min_z = -10 (post's bare
      centre), max_z = 55 (inn 50+5) -> {"min_x": -50.0, "min_z": -10.0,
      "max_x": 70.0, "max_z": 55.0}; key "grid_bounds" absent. A placed
      location without a scale anchor contributes its CENTRE POINT, so a
      location the payload shows can never fall outside the extent.
  [3] terrain_sig present (10 chars) and equal to terrain.terrain_sig().
  [4] demo_avatar character entry: pos == {"x": 50.0, "z": 50.0},
      location_id == inn. npc_w: pos {"x": 30.0, "z": 30.0},
      location_id "" — a wilderness character IS in the payload
      (show_all=True) even without a location.
  [5] Fog (avatar demo_avatar, knows only inn): farm and post hidden, inn
      visible, ghost (unplaced) visible; world_bounds UNCHANGED (computed
      before the fog filter). npc_w stands in the wilderness and is judged
      by SIGHT RANGE since E6 (§ A12), not by a location:
        avatar at the inn (50, 50), npc_w at (30, 30)
        distance = hypot(20, 20) = 28.28 m
        default range 50 m (discovery.DEFAULT_DISCOVERY_RANGE_M, nothing
        configured here) -> 28.28 <= 50 -> npc_w IS in the fogged payload
        range set to 10 m                -> 28.28 > 10  -> npc_w is gone
      (both sides of the rule in detail: scripts/smoke_fog_worldmap.py)
  [6] GET /play/terrain payload (call the route function directly):
      default_kind "grass", one area, sig == terrain_sig(), types contain
      the renamed grass override. default_kind comes from
      terrain_query.default_kind() and NOT from a second config read: with
      the config key present but EMPTY the endpoint must still answer
      "grass" (the point queries do), never "".
  [7] world_bounds spans the PAINTED map too (E4 finding B7). The frame
      is the union of placed footprints and the axis-aligned boxes of all
      painted areas — otherwise a large painted map with few placed
      locations is cropped to their box by everything that follows the
      frame (base plane, fog blanket, camera fit, minimap). The seed's
      water area (0..20 / 0..20) lies INSIDE [2]'s box, so [2] is
      unchanged by the rule; these cases put terrain outside it:
      (a) paint FAR = [[100,-40],[140,-40],[140,-20],[100,-20]] -> the
          union widens to max_x 140 (FAR, past post's 70) and min_z -40
          (FAR, past post's -10); min_x stays -50 (farm) and max_z 55
          (inn) -> {"min_x": -50.0, "min_z": -40.0, "max_x": 140.0,
          "max_z": 55.0}.
      (b) an area whose polygon holds JUNK points, written past the model
          straight into the DB (save_area sanitizes, a legacy row need
          not have): [[160,60], "nope", [null,5]]. The valid point
          stretches the box to max_x 160 / max_z 60, the two junk points
          are skipped instead of poisoning the extent with NaN (a NaN
          would make the payload unencodable: allow_nan=False).
      (c) terrain-only world (every location deleted, water + FAR left):
          bounds come from the terrain ALONE instead of null ->
          {"min_x": 0.0, "min_z": -40.0, "max_x": 140.0, "max_z": 20.0}
          (water 0..20 / 0..20 union FAR 100..140 / -40..-20).
      (d) nothing placed AND nothing painted -> null. That is the only
          remaining null case.
  [8] ``layout_sig`` covers the scene-shaping map3d, not only the room
      layouts (E5 finding B11). Seed for this section (the world is empty
      after [7d], so it stands on its own): a "Gatehouse" placed at
      (0, 0) with a centred 12 m square boundary
      (−6,−6) (6,−6) (6,6) (−6,6). Hand-derived:
      (a) the entry HAS a layout_sig (10 hex chars) although the location
          has no room — map3d alone is enough now;
      (b) drawing a boundary opening
          (map3d.boundary_openings = [{"edge": 0, "at": 0.5,
          "width_m": 2}]) CHANGES the sig — that is the whole point: a
          gate drawn in the floor-plan editor reaches a running client;
      (c) renaming the location does NOT change it — the signature is
          about geometry, not about anything else on the location;
      (d) building the payload twice over unchanged data yields the SAME
          sig (deterministic serialization, sort_keys);
      (e) with map3d removed and still no room layouts the key is absent
          again — it stays an OPTIONAL key.
  [9] ``openings`` — the authored boundary pass-throughs, FINISHED
      (contract v6, § A1.3 / § B1 Nr. 13). The server computes, the client
      renders: edge INDEX, world point, world inward normal, room link.
      The Gatehouse of [8] is the fixture — pin (0, 0), boundary the
      centred 12 m square (−6,−6) (6,−6) (6,6) (−6,6), clockwise in map
      view (positive shoelace: 4·6² = 144 > 0).
      Hand-derived, edge 0 = point 0 → point 1, i.e. (−6,−6) → (6,−6):
        at 0.5 -> local (−6 + 0.5·12, −6) = (0, −6)
        inward: d = (12, 0), |d| = 12, (−dz, dx)/|d| = (0, 1); the probe a
          millimetre along it lands at (0, −5.999), inside the square, so
          that direction stands. +z is indeed into the square.
        yaw 0  -> world point (0.0, −6.0), inward (0.0, 1.0)
        yaw 90 -> § A1.1: x = cx + lx·cos + lz·sin = 0 + 0 + (−6)·1 = −6
                          z = cz − lx·sin + lz·cos = 0 − 0 + (−6)·0 = 0
                  the NORMAL turns about the ORIGIN, not the pin:
                          x = 0·0 + 1·1 = 1,  z = −0·1 + 1·0 = 0
                  -> world point (−6.0, 0.0), inward (1.0, 0.0)
      The very same numbers stand in client3d/scripts/smoke_enter_math.mjs
      — the client consumes this row verbatim, so both sides check the one
      square. Further cases: a room link travels along (``room``), an
      opening on an index the boundary does not have is dropped, and a
      location without any authored opening carries the EMPTY list, which
      is the free-boundary statement.

Usage:  ./.venv/bin/python scripts/smoke_worldmap_v2.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-v2-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="worldmap-v2-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import config, terrain_query, terrain_types  # noqa: E402
from app.core.world_ops import build_worldmap_payload  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.character import (  # noqa: E402
    save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location, update_location_position)
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


def set_square_boundary(location_id: str, width) -> None:
    """Draw the location's boundary as the centred square of edge ``width``
    (LOCAL metres, clockwise in map view) and store the derived bounding-box
    width alongside — exactly what the sanitizer writes on a real save.
    ``None`` removes both again, leaving a location with no area."""
    data = _load_world_data()
    half = None if width is None else round(float(width) / 2.0, 2)
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            if width is None:
                map3d.pop("boundary", None)
                map3d.pop("plan_width_m", None)
            else:
                map3d["boundary"] = [[-half, -half], [half, -half],
                                     [half, half], [-half, half]]
                map3d["plan_width_m"] = float(width)
            loc["map3d"] = map3d
    _save_world_data(data)


def entry(payload, loc_id: str) -> dict:
    for e in payload["locations"]:
        if e["id"] == loc_id:
            return e
    return {}


def char(payload, name: str) -> dict:
    for c in payload["characters"]:
        if c["name"] == name:
            return c
    return {}


def ids(payload) -> list:
    return sorted(e["id"] for e in payload["locations"])


def names(payload) -> list:
    return sorted(c["name"] for c in payload["characters"])


# ── Seed ────────────────────────────────────────────────────────────────
INN = add_location(name="Smoke Inn", description="worldmap v2 smoke")["id"]
update_location_position(INN, 50.0, 50.0, 90.0)
set_square_boundary(INN, 10.0)

FARM = add_location(name="Wide Farm", description="worldmap v2 smoke")["id"]
update_location_position(FARM, -30.0, 20.0)
set_square_boundary(FARM, 40.0)

# Placed, but nobody ever drew its outline — update_location_position writes
# no boundary, so this is an ordinary authoring state (and the state the
# "Seed missing boundaries" button exists for).
POST = add_location(name="Outline-less Post", description="placed, no area")["id"]
update_location_position(POST, 70.0, -10.0)

GHOST = add_location(name="Unplaced Hut", description="never placed")["id"]

WATER = terrain.save_area({"kind": "water",
                           "polygon": [[0, 0], [20, 0], [20, 20], [0, 20]],
                           "z_order": 0})["id"]
terrain_types.save_world_type({"kind": "grass", "name": "Smoke Meadow",
                               "color": "#00ff00", "passable": True,
                               "speed_factor": 1.0})

save_character_profile("demo_avatar", {"current_location": ""}, create_new=True)
save_character_current_location("demo_avatar", INN)
set_known_locations("demo_avatar", [INN])

save_character_profile("npc_w", {"current_location": ""}, create_new=True)
set_character_pos("npc_w", 30, 30)

BOUNDS = {"min_x": -50.0, "min_z": -10.0, "max_x": 70.0, "max_z": 55.0}


def main() -> int:
    print("\n[1] admin view — location entries are metre-shaped")
    allv = build_worldmap_payload("demo_avatar", show_all=True)
    check("locations", ids(allv), sorted([INN, FARM, POST, GHOST]))
    inn = entry(allv, INN)
    check("inn.pos_x", inn.get("pos_x"), 50.0)
    check("inn.pos_z", inn.get("pos_z"), 50.0)
    check("inn.yaw_deg", inn.get("yaw_deg"), 90.0)
    check("inn.plan_width_m", inn.get("plan_width_m"), 10.0)
    check("inn keys", sorted(inn),
          sorted(["id", "name", "pos_x", "pos_z", "yaw_deg", "plan_width_m",
                  "passable", "map3d", "layout_sig", "boundary", "openings"]))
    # v6 "Gebiete": a location travels as a polygon and as nothing else —
    # the inn's drawn square in LOCAL metres (edge 10 -> half 5), clockwise.
    check("inn.boundary (the drawn square, CW)", inn.get("boundary"),
          [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]])
    # The inn has NO room — its signature comes from map3d alone (E5 B11).
    check("inn.layout_sig without any room", len(inn.get("layout_sig") or ""),
          10)
    check("inn.passable (a house is walked INTO, not through)",
          inn.get("passable"), False)
    for gone in ("grid_x", "grid_y", "surface_kind", "terrain",
                 "map_rotation_2d", "template_location_id", "map_image_off",
                 "map_patch_2d", "map_patch_span"):
        check(f"inn has no {gone}", gone in inn, False)
    ghost = entry(allv, GHOST)
    check("ghost.pos_x (unplaced)", ghost.get("pos_x"), None)
    check("ghost.plan_width_m (no area)", ghost.get("plan_width_m"), None)
    post = entry(allv, POST)
    check("post.pos_x (placed)", post.get("pos_x"), 70.0)
    check("post.pos_z (placed)", post.get("pos_z"), -10.0)
    # PLACED BUT BOUNDARY-LESS — the closing state of the square wave: no
    # outline means no area, so the row is a bare pin and says so twice.
    check("post.boundary (never drawn -> no area)", post.get("boundary"), None)
    check("post.plan_width_m (nothing to derive it from)",
          post.get("plan_width_m"), None)
    check("post has no layout_sig (no map3d, no room)",
          "layout_sig" in post, False)
    # A LEGACY DIAL IS NOT A SHAPE (2026-08-19): a location that still carries
    # plan_width_m but never drew an outline must read exactly like the post
    # above — no synthesized square anywhere in the payload.
    _data = _load_world_data()
    for _l in _data.get("locations", []):
        if _l.get("id") == POST:
            _l["map3d"] = {"plan_width_m": 24.0}
    _save_world_data(_data)
    try:
        _z = entry(build_worldmap_payload("demo_avatar", show_all=True), POST)
        check("legacy plan_width_m alone -> boundary null",
              _z.get("boundary"), None)
        check("legacy plan_width_m alone -> plan_width_m null",
              _z.get("plan_width_m"), None)
    finally:
        _data = _load_world_data()
        for _l in _data.get("locations", []):
            if _l.get("id") == POST:
                _l.pop("map3d", None)
        _save_world_data(_data)

    print("\n[2] world_bounds in metres over all placed locations")
    check("world_bounds", allv.get("world_bounds"), BOUNDS)
    check("grid_bounds gone", "grid_bounds" in allv, False)
    # The invariant behind the centre-point rule: nothing the payload shows
    # may sit outside the extent.
    _b = allv["world_bounds"]
    check("every shown location inside the bounds",
          all(_b["min_x"] <= e["pos_x"] <= _b["max_x"]
              and _b["min_z"] <= e["pos_z"] <= _b["max_z"]
              for e in allv["locations"] if e["pos_x"] is not None), True)

    print("\n[3] terrain_sig travels with the payload")
    sig = allv.get("terrain_sig")
    check("terrain_sig length", len(sig or ""), 10)
    check("terrain_sig matches the model", sig, terrain.terrain_sig())

    print("\n[4] characters carry their free metre position")
    check("characters", names(allv), ["demo_avatar", "npc_w"])
    check("demo_avatar.pos", char(allv, "demo_avatar").get("pos"),
          {"x": 50.0, "z": 50.0})
    check("demo_avatar.location_id", char(allv, "demo_avatar").get("location_id"),
          INN)
    check("npc_w.pos", char(allv, "npc_w").get("pos"), {"x": 30.0, "z": 30.0})
    check("npc_w.location_id (wilderness)",
          char(allv, "npc_w").get("location_id"), "")

    print("\n[5] fog hides the unknown farm, never the bounds")
    fog = build_worldmap_payload("demo_avatar", show_all=False)
    check("locations", ids(fog), sorted([INN, GHOST]))
    check("world_bounds unchanged", fog.get("world_bounds"), BOUNDS)
    check("characters (npc_w is 28.28 m away, sight range 50)",
          names(fog), ["demo_avatar", "npc_w"])
    check("fogged", fog.get("fogged"), True)
    config._CONFIG.setdefault("game", {})["discovery_range_m"] = 10.0
    check("… out of sight at range 10",
          names(build_worldmap_payload("demo_avatar", show_all=False)),
          ["demo_avatar"])
    config._CONFIG["game"].pop("discovery_range_m", None)

    print("\n[6] GET /play/terrain — never fogged")
    tp = play.get_terrain_route()
    check("default_kind", tp.get("default_kind"), "grass")
    check("default_kind == terrain_query.default_kind()",
          tp.get("default_kind"), terrain_query.default_kind())
    # Present-but-EMPTY config key: a second, unguarded config read would
    # answer "" here while kind_at/passability_at still resolve "grass".
    # Poked in memory on purpose — this is a throwaway process.
    config._CONFIG.setdefault("game", {})["default_terrain_kind"] = ""
    try:
        check("empty config key still answers the query default",
              play.get_terrain_route().get("default_kind"),
              terrain_query.default_kind())
        check("…and that default is 'grass'", terrain_query.default_kind(),
              "grass")
    finally:
        config._CONFIG.get("game", {}).pop("default_terrain_kind", None)
    check("areas", len(tp.get("areas") or []), 1)
    check("area kind", (tp.get("areas") or [{}])[0].get("kind"), "water")
    check("sig", tp.get("sig"), terrain.terrain_sig())
    by_kind = {t["kind"]: t for t in (tp.get("types") or [])}
    check("grass override applied", by_kind.get("grass", {}).get("name"),
          "Smoke Meadow")
    check("types sorted by kind", [t["kind"] for t in tp["types"]],
          sorted(by_kind))

    print("\n[7] world_bounds spans the painted map too (E4 finding B7)")
    # (a) a painted area OUTSIDE the location box widens the frame.
    FAR = terrain.save_area({
        "kind": "water",
        "polygon": [[100, -40], [140, -40], [140, -20], [100, -20]],
        "z_order": 0})["id"]
    union = build_worldmap_payload("demo_avatar", show_all=True)
    check("bounds = footprints ∪ painted areas", union.get("world_bounds"),
          {"min_x": -50.0, "min_z": -40.0, "max_x": 140.0, "max_z": 55.0})
    # (b) junk vertices are skipped per POINT, never poisoning the extent.
    # save_area sanitizes, so this row is written straight to the DB — a
    # legacy row is the only way such a polygon can exist.
    import json as _json
    from app.core.db import transaction as _transaction
    with _transaction() as _conn:
        _conn.execute(
            "INSERT INTO terrain_areas (id, kind, polygon, z_order, meta, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("ta_junk", "water",
             _json.dumps([[160, 60], "nope", [None, 5]]), 0, "{}",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
    junk = build_worldmap_payload("demo_avatar", show_all=True)
    check("junk vertices skipped, the valid one still counts",
          junk.get("world_bounds"),
          {"min_x": -50.0, "min_z": -40.0, "max_x": 160.0, "max_z": 60.0})
    # A NaN would survive as a float here and make the payload unencodable.
    check("payload stays JSON-encodable (no NaN in the frame)",
          bool(_json.dumps(junk["world_bounds"], allow_nan=False)), True)
    terrain.delete_area("ta_junk")

    # (c) terrain-only world: nothing placed, but the painted map remains.
    _data = _load_world_data()
    _data["locations"] = []
    _save_world_data(_data)
    only = build_worldmap_payload("demo_avatar", show_all=True)
    check("no locations left", ids(only), [])
    check("terrain-only world still has a frame", only.get("world_bounds"),
          {"min_x": 0.0, "min_z": -40.0, "max_x": 140.0, "max_z": 20.0})

    # (d) the ONE remaining null case: nothing placed AND nothing painted.
    terrain.delete_area(WATER)
    terrain.delete_area(FAR)
    empty = build_worldmap_payload("demo_avatar", show_all=True)
    check("empty world -> null", empty.get("world_bounds"), None)

    print("\n[8] layout_sig covers map3d, not only room layouts (E5 B11)")
    # The world is empty here ([7d] deleted everything) — this section seeds
    # its own location, so it reads on its own.
    GATE = add_location(name="Gatehouse", description="B11 smoke")["id"]
    update_location_position(GATE, 0.0, 0.0)
    set_square_boundary(GATE, 12.0)

    def gate_sig() -> str:
        return entry(build_worldmap_payload("demo_avatar", show_all=True),
                     GATE).get("layout_sig")

    def set_map3d(**keys) -> None:
        """Patch the location's map3d in place (None removes a key)."""
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == GATE:
                m3 = dict(loc.get("map3d") or {})
                for k, v in keys.items():
                    if v is None:
                        m3.pop(k, None)
                    else:
                        m3[k] = v
                loc["map3d"] = m3
        _save_world_data(data)

    # (a) map3d alone earns a signature — the gatehouse has no room.
    base = gate_sig()
    check("layout_sig present without any room layout", len(base or ""), 10)
    # (d) same data, second build -> identical signature.
    check("stable across two payload builds", gate_sig(), base)
    # (b) a drawn boundary opening MOVES the signature.
    set_map3d(boundary_openings=[{"edge": 0, "at": 0.5, "width_m": 2}])
    drawn = gate_sig()
    check("boundary opening changes the sig", drawn != base, True)
    check("…and the new sig is a signature too", len(drawn or ""), 10)
    check("…and is stable in turn", gate_sig(), drawn)
    # (c) an unrelated field leaves it alone.
    _data = _load_world_data()
    for _l in _data.get("locations", []):
        if _l.get("id") == GATE:
            _l["name"] = "Gatehouse renamed"
    _save_world_data(_data)
    check("renaming the location does NOT change the sig", gate_sig(), drawn)
    # (e) nothing scene-shaping left -> the key is optional again.
    set_map3d(boundary_openings=None, boundary=None, plan_width_m=None)
    check("no map3d and no rooms -> no layout_sig",
          "layout_sig" in entry(build_worldmap_payload("demo_avatar",
                                                       show_all=True), GATE),
          False)

    print("\n[9] openings — the pass-throughs arrive COMPUTED (v6, § A1.3)")
    # The Gatehouse gets its area back: the drawn 12 m square around (0, 0).
    set_square_boundary(GATE, 12.0)

    def gate_openings():
        return entry(build_worldmap_payload("demo_avatar", show_all=True),
                     GATE).get("openings")

    check("no authored opening -> the EMPTY list (a free boundary)",
          gate_openings(), [])
    # edge 0 at 0.5 -> local (0, -6), inward (0, 1) -> world the same at yaw 0.
    set_map3d(boundary_openings=[{"edge": 0, "at": 0.5, "width_m": 2}])
    check("edge 0 at 0.5 of the 12 m square, yaw 0", gate_openings(),
          [{"edge": 0, "at_world": [0.0, -6.0], "inward": [0.0, 1.0],
            "room": ""}])
    # The room link travels along; existence of that room is the entry gate's
    # question, not the geometry's.
    set_map3d(boundary_openings=[{"edge": 0, "at": 0.5, "width_m": 2,
                                  "room": "hall"}])
    check("the room link rides along", gate_openings()[0].get("room"), "hall")
    # yaw 90: the point turns about the PIN, the normal about the ORIGIN.
    update_location_position(GATE, 0.0, 0.0, 90.0)
    check("yaw 90 turns point and normal", gate_openings(),
          [{"edge": 0, "at_world": [-6.0, 0.0], "inward": [1.0, 0.0],
            "room": "hall"}])
    update_location_position(GATE, 0.0, 0.0, 0.0)
    # An index the boundary does not have names no edge and therefore no
    # point — the square has exactly the edges 0..3.
    set_map3d(boundary_openings=[{"edge": 4, "at": 0.5, "width_m": 2}])
    check("an edge index the polygon does not have is dropped",
          gate_openings(), [])
    # Without an area there is no edge to sit on either.
    set_map3d(boundary=None, plan_width_m=None,
              boundary_openings=[{"edge": 0, "at": 0.5, "width_m": 2}])
    check("no boundary, no opening points", gate_openings(), [])

    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
        return 1
    print(f"OK — {CHECKED} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS, ignore_errors=True)
