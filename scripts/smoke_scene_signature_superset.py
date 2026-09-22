#!/usr/bin/env python3
"""Smoke run for the SCENE SIGNATURE INVARIANT (§ B1a).

Usage:  ./.venv/bin/python scripts/smoke_scene_signature_superset.py

THE INVARIANT, in one sentence: ``scene_recipe._signature`` is a SUPERSET of
every input the composed payload reads — a mutation that changes the payload
moves the signature. The converse is deliberately NOT promised: an input that
only sometimes reaches the payload (a lake forty metres away) may move the
signature without moving a byte of the payload. A needless remount is cheap, a
stale scene is not — the 3D client rebuilds a location ONLY when ``signature``
changes (``client3d/src/scene/sceneRecipe.ts``: ``SceneLibrary.sweep``), so a
payload change the signature misses is a scene that never updates until the
page is reloaded.

Runs against a THROWAWAY storage directory — never touches a real world, never
starts a server, makes no LLM/image call. Storage and the clip library are
redirected BEFORE the first app import, exactly as ``scripts/smoke_scene_cache.py``
and ``scripts/smoke_scene_recipe.py`` do: an app import that finds no
``--world`` falls back to ``worlds/demo``, whose ``world.db`` is tracked in git.

WHY THIS FILE EXISTS — the two gaps it pins
-------------------------------------------
Before the change this guard accompanies, ``_signature`` hashed the code
version, ``map3d``, ``plan_width_m``, the resolved ground kind, the season
token, the room-recipe signatures, the building meta, the room metas (minus
their lattices), ``default_door_prop_id``, the door-prop mesh signatures, the
surface-lattice signatures and the corridor levels. Two payload inputs reached
NONE of them:

(a) A PROP'S ``tags``. ``_prop_models`` ships ``walkable`` (and with it the
    baked walking lattice) for a placement whose prop carries the ``walkable``
    tag. The room recipe's placement entry carries ``dims``, ``prop_name``,
    ``has_model``, ``model_tiers``, ``variant_tiers`` and ``model_sig`` — no
    tags — and ``model_sig`` is ``props.get_prop()["model_signature"]``, which
    is the per-variant mesh gallery signature (file name + ``created_at`` per
    tier, ``model_store.ModelGallery.signature``) plus the picture part
    (``_picture_signature_part``: ``area_defaults``, ``slot_values``, the
    per-file orientation fix). Tags are in neither half. So untagging a crate
    used to change the payload and leave every signature exactly where it was.

(b) THE PAINTED TERRAIN. ``floor_plan[].map_water`` is composed from
    ``_painted_waters()`` (``models.terrain.list_areas`` +
    ``terrain_types.effective_catalog``); nothing about it is stored on the
    location, so paint a lake under a house and ``map3d``, every room recipe
    and every model meta stay character for character what they were.

Both are now inputs of ``_signature``: ``terrain`` = ``models.terrain.terrain_sig()``
and ``walkable_props`` = ``{prop_id: bool}`` over the props the location really
places. THAT is the "fails before" argument of this file, and it is an argument,
not a run: against the old code the mutations [M1]/[M2] and [M3]…[M6] below
leave ``signature`` unchanged while the payload moves, so every "…and the
signature moves with it" check in those blocks fails. Nothing here compares
against ``git show HEAD:`` — a baseline that stops being a baseline the moment
the fix is committed.

THE WORLD RELIEF is deliberately NOT a signature input, and [M7] is the
measurement that says why: ``heightfield.water_areas`` takes the painted areas
and the type catalog as ARGUMENTS and reads no height, and no other payload
field asks the height field anything. A height area therefore changes no byte
of the payload — checked, not assumed.

===========================================================================
THE FIXTURE (hand-built, so every expectation below follows from it)
===========================================================================
    prop "crate"        sidecar only (no mesh), tagged ``walkable``
    location "Depot"    drawn 20 m square (corners ±10) at world (0, 0),
                        room "hall" layout x=-8 z=-8 w=16 d=12 with one
                        "crate" placement at (2, 2) and one DOOR opening
                        on edge 2
    location "Far"      placed at (300, 300), never composed — it only owns
                        the terrain that [I1] paints far away

===========================================================================
WHAT EACH BLOCK EXPECTS, by hand
===========================================================================
Every mutation block does the same three things: apply ONE change, recompose
through ``scene_for_location``, and compare (1) the payload canonically
JSON-dumped WITHOUT its ``signature`` field, (2) ``signature`` itself and
(3) ``scene_fingerprint`` — the ETag the route answers ``304`` from.

    [M1] the crate loses its ``walkable`` tag
         payload MOVES (the placement stops shipping ``walkable: true`` —
         one crate, one key) -> signature MUST move                    (gap a)
    [M2] the crate gets the tag back
         payload MOVES back to exactly [M0] -> signature MUST move, and back
         to the [M0] value: the hash is a function of the inputs, so equal
         inputs are an equal hash
    [M3] water painted over the whole square
         payload MOVES (``floor_plan[0].map_water`` appears: the hall's hull
         lies wholly inside the lake, so the majority-area test of
         ``_map_water_ref`` answers 1.0 > 0.5) -> signature MUST move  (gap b)
    [M4] that same area's kind changed to ``grass``
         grass is not a water kind, so ``_painted_waters`` drops it: payload
         MOVES (the reference is gone) -> signature MUST move
    [M5] the kind changed back to ``water``
         payload MOVES (the reference is back) -> signature MUST move
    [M6] the area deleted
         payload MOVES (gone again) -> signature MUST move
    [M7] a HEIGHT area over the square (relief)
         payload UNCHANGED — the relief is not a payload input
    [M8] the hall's layout widened 16 -> 17 m
         payload MOVES (hull, walls, plate) -> signature MUST move
    [M9] ``default_door_prop_id`` set on the location
         payload MOVES (the door's flat leaf gives way to a prop spec)
         -> signature MUST move
    [M10] a room on level 1 is added
         payload MOVES (a second storey, and with it the storey corridor)
         -> signature MUST move
    [M11] the game clock jumps into another season
         the SEASON token moves -> signature MUST move. The payload of THIS
         fixture does not (no seasonal prop variant, no seasonal texture) —
         that is the superset direction and no failure.
    [M12] a ROOM META dial, measured on ``compose_scene`` directly (a meta is
         a model sidecar, not a stored world value): ``{}`` -> a meta with
         ``width_m``/``walk_y`` makes the room ship a diorama spec, and
         changing ``walk_y`` inside it moves the spec again. Payload MOVES
         both times -> signature MUST move both times.

    [N1] the location re-saved UNCHANGED      -> signature identical
    [N2] the prop sidecar rewritten byte-identical -> signature identical
    [N3] the terrain area re-saved with its own sanitized data
                                              -> signature identical
    [I1] terrain painted 300 m away, under the OTHER location: informational.
         The payload must NOT move; the signature is ALLOWED to (``terrain_sig``
         covers the painted world, not a bounding box). Reported, never failed.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="scene-sig-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="scene-sig-clips-")

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.core.game_time import GameTime, get_calendar  # noqa: E402
from app.core.timeutils import game_time, set_game_time  # noqa: E402
from app.models.heightfield import save_height_area  # noqa: E402
from app.models.terrain import delete_area, save_area  # noqa: E402
from app.models.world import (  # noqa: E402
    add_location, get_location_by_id, update_location_position,
    upsert_location)

FAILURES = []
CHECKED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'OK  ' if ok else 'FAIL'} {label}"
          + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def note(label: str, detail: str = "") -> None:
    print(f"  --   {label}" + (f" — {detail}" if detail else ""))


# ── the fixture ─────────────────────────────────────────────────────────
CRATE = "crate"
CRATE_DIR = STORAGE / "props" / CRATE
CRATE_DIR.mkdir(parents=True, exist_ok=True)


def write_crate(tags) -> None:
    """The crate's sidecar with exactly ``tags`` — the prop's whole record."""
    (CRATE_DIR / prop_store.SIDECAR_NAME).write_text(json.dumps({
        "name": "Crate", "category": "furniture",
        "width_m": 0.8, "depth_m": 0.8, "height_m": 0.6,
        "tags": list(tags)}), encoding="utf-8")


write_crate(["walkable"])

DEPOT = add_location(name="Depot", description="scene signature smoke",
                     rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(DEPOT, 0.0, 0.0)
FAR = add_location(name="Far", description="owns the distant terrain")["id"]
update_location_position(FAR, 300.0, 300.0)


def hall_layout(width: float = 16.0) -> dict:
    """The hall: one crate, one door on edge 2 (the south wall)."""
    return {"x": -8.0, "y": -8.0, "w": width, "d": 12.0, "level": 0,
            "surfaces": {"floor": "wood", "wall": "plaster"},
            "openings": [{"edge": 2, "at": 0.5, "type": "door",
                          "width_m": 1.0, "height_m": 2.1, "to": "outside"}],
            "props": [{"id": "c0", "prop_id": CRATE, "at": [2.0, 2.0],
                       "yaw": 0}]}


def shape(width: float = 16.0, door_prop: str = "", upper: bool = False) -> None:
    """Write the depot: drawn square, the hall, optionally a level-1 room."""
    loc = get_location_by_id(DEPOT)
    loc["map3d"] = {"plan_width_m": 20.0, "storey_height_m": 3.0,
                    "boundary": [[-10.0, -10.0], [10.0, -10.0],
                                 [10.0, 10.0], [-10.0, 10.0]],
                    "outline": [[-10.0, -10.0], [10.0, -10.0],
                                [10.0, 10.0], [-10.0, 10.0]]}
    loc["default_door_prop_id"] = door_prop
    rooms = [r for r in loc["rooms"] if r.get("id") == "hall"]
    rooms[0]["layout"] = hall_layout(width)
    if upper:
        rooms.append({"id": "attic", "name": "Attic", "layout": {
            "x": -8.0, "y": -8.0, "w": 16.0, "d": 12.0, "level": 1,
            "surfaces": {"floor": "wood"}}})
    loc["rooms"] = rooms
    upsert_location(loc)


shape()


# ── the measurement ─────────────────────────────────────────────────────
def canon(payload: dict) -> str:
    """The payload as canonical JSON WITHOUT its own ``signature`` field —
    "did anything else move?" cannot be asked of a dump that contains the
    answer."""
    return json.dumps({k: v for k, v in payload.items() if k != "signature"},
                      sort_keys=True, default=str)


def probe() -> tuple:
    """``(canonical payload, signature, fingerprint)`` of the depot right now.

    The fingerprint is taken FIRST and from the stored record, exactly as the
    route does (it answers ``304`` from it before it ever asks for a payload).
    """
    loc = get_location_by_id(DEPOT)
    fingerprint = scene_recipe.scene_fingerprint(loc, DEPOT)
    payload = scene_recipe.scene_for_location(loc, DEPOT, fingerprint)
    return canon(payload), payload["signature"], fingerprint


def moved(label: str, before: tuple, after: tuple, *,
          payload_moves: bool = True) -> None:
    """One mutation, measured: the payload's expected move, the signature's
    obligation that follows from it, and the ETag that must never lag behind
    the signature."""
    p0, s0, f0 = before
    p1, s1, f1 = after
    if payload_moves:
        check(f"{label}: the payload moves", p1 != p0)
        check(f"{label}: …and the signature moves with it", s1 != s0,
              f"{s0[:8]} -> {s1[:8]}")
    else:
        check(f"{label}: the payload does not move", p1 == p0)
    # The ETag is the stricter of the two by contract (§ B1a): whenever the
    # signature moved, the fingerprint must have moved too, or a `304` could
    # hide a scene change from the client. Empty tags mean "composed directly,
    # not through the stored route" — [M12] has no fingerprint to compare.
    if s1 != s0 and (f0 or f1):
        check(f"{label}: …and the ETag fingerprint moved too", f1 != f0,
              f"{f0[:8]} -> {f1[:8]}")


def main() -> int:
    print("[M0] the fixture composes")
    base = probe()
    first = scene_recipe.scene_for_location(get_location_by_id(DEPOT), DEPOT)
    props = [m for m in first["models"] if m.get("role") == "prop"]
    check("one crate in the scene", len(props) == 1, str(len(props)))
    check("…and it is walkable", [m.get("walkable") for m in props] == [True])

    print("\n[M1]/[M2] a prop's tags (gap a)")
    write_crate(["decor"])
    untagged = probe()
    moved("the crate loses `walkable`", base, untagged)
    gone = [m.get("walkable")
            for m in scene_recipe.scene_for_location(
                get_location_by_id(DEPOT), DEPOT)["models"]
            if m.get("role") == "prop"]
    check("…and the payload really stopped shipping the flag", gone == [None],
          str(gone))
    write_crate(["walkable"])
    retagged = probe()
    moved("the crate gets `walkable` back", untagged, retagged)
    check("…and the signature is the [M0] one again "
          "(equal inputs, equal hash)", retagged[1] == base[1],
          f"{retagged[1][:8]} vs {base[1][:8]}")

    print("\n[M3]…[M6] the painted terrain (gap b)")
    lake = save_area({"kind": "water",
                      "polygon": [[-12.0, -12.0], [12.0, -12.0],
                                  [12.0, 12.0], [-12.0, 12.0]],
                      "z_order": 1})
    watered = probe()
    moved("water painted over the square", retagged, watered)
    plan = scene_recipe.scene_for_location(
        get_location_by_id(DEPOT), DEPOT)["floor_plan"]
    check("…and the floor plan names the lake",
          bool((plan or [{}])[0].get("map_water")), str(plan and plan[0]))

    save_area(dict(lake, kind="grass"))
    grassed = probe()
    moved("the area's kind becomes `grass`", watered, grassed)

    save_area(dict(lake, kind="water"))
    rewatered = probe()
    moved("the kind becomes `water` again", grassed, rewatered)

    check("the lake is really gone from the DB", delete_area(lake["id"]))
    drained = probe()
    moved("the area is deleted", rewatered, drained)

    print("\n[M7] the relief is NOT a payload input")
    save_height_area({"polygon": [[-12.0, -12.0], [12.0, -12.0],
                                  [12.0, 12.0], [-12.0, 12.0]],
                      "height_m": 4.0, "falloff_m": 2.0})
    relief = probe()
    moved("a height area over the square", drained, relief,
          payload_moves=False)
    note("the signature "
         + ("moved anyway (allowed: a superset may)"
            if relief[1] != drained[1] else "stood still, as expected"))

    print("\n[M8]…[M10] the inputs that were already covered")
    shape(width=17.0)
    widened = probe()
    moved("the hall is widened to 17 m", relief, widened)

    shape(width=17.0, door_prop="oak_door")
    doored = probe()
    moved("the location gets a default door prop", widened, doored)

    shape(width=17.0, door_prop="oak_door", upper=True)
    storeyed = probe()
    moved("a level-1 room (and its storey corridor) appears", doored,
          storeyed)

    print("\n[M11] the season")
    cal = get_calendar()
    now = game_time()
    parts = now.parts(cal)
    starts = list(cal.season_starts or [0])
    if len(starts) > 1:
        # Some OTHER season than the current one, at noon of its first day.
        target = starts[(parts.season_index + 1) % len(starts)]
        year0 = (parts.day_index - (parts.day_of_year - 1))
        set_game_time(GameTime((year0 + target) * 86400 + 12 * 3600))
        seasoned = probe()
        check("a season jump moves the signature", seasoned[1] != storeyed[1],
              f"{storeyed[1][:8]} -> {seasoned[1][:8]}")
        check("…and the ETag fingerprint with it",
              seasoned[2] != storeyed[2])
        note("the payload of this fixture is "
             + ("unchanged (superset direction)" if seasoned[0] == storeyed[0]
                else "changed as well"))
        set_game_time(now)
    else:
        note("the world has one season — nothing to jump to")
    after_season = probe()

    print("\n[M12] a room meta dial (composed directly)")
    loc = get_location_by_id(DEPOT)
    width_m, building_meta, _ = scene_recipe.scene_inputs(loc, DEPOT)
    bare = scene_recipe.compose_scene(loc, plan_width_m=width_m,
                                      building_meta=building_meta,
                                      room_metas={})
    meta = {"tiers": {"full": "model.glb"}, "width_m": 6.0, "walk_y": 0.2,
            "floors": 1}
    withmeta = scene_recipe.compose_scene(loc, plan_width_m=width_m,
                                          building_meta=building_meta,
                                          room_metas={"hall": dict(meta)})
    moved("a room gains a model meta",
          (canon(bare), bare["signature"], ""),
          (canon(withmeta), withmeta["signature"], ""))
    dialled = scene_recipe.compose_scene(
        loc, plan_width_m=width_m, building_meta=building_meta,
        room_metas={"hall": dict(meta, walk_y=0.4)})
    moved("…and its `walk_y` is dialled",
          (canon(withmeta), withmeta["signature"], ""),
          (canon(dialled), dialled["signature"], ""))

    print("\n[N1]…[N3] no-ops must move nothing")
    upsert_location(get_location_by_id(DEPOT))
    resaved = probe()
    check("re-saving the location unchanged keeps the signature",
          resaved[1] == after_season[1],
          f"{after_season[1][:8]} vs {resaved[1][:8]}")
    check("…and the payload", resaved[0] == after_season[0])

    write_crate(["walkable"])
    rewritten = probe()
    check("rewriting the prop sidecar byte-identically keeps the signature",
          rewritten[1] == resaved[1],
          f"{resaved[1][:8]} vs {rewritten[1][:8]}")

    pond = save_area({"kind": "water",
                      "polygon": [[-4.0, -4.0], [4.0, -4.0], [4.0, 4.0]],
                      "z_order": 2})
    with_pond = probe()
    save_area(dict(pond))
    resaved_pond = probe()
    check("re-saving a terrain area with its own data keeps the signature",
          resaved_pond[1] == with_pond[1],
          f"{with_pond[1][:8]} vs {resaved_pond[1][:8]}")
    check("…and the payload", resaved_pond[0] == with_pond[0])

    print("\n[I1] terrain 300 m away (informational)")
    save_area({"kind": "water",
               "polygon": [[290.0, 290.0], [310.0, 290.0], [310.0, 310.0]],
               "z_order": 3})
    far = probe()
    check("the distant lake changes no byte of the payload",
          far[0] == resaved_pond[0])
    note("the signature "
         + ("moved (allowed: `terrain_sig` covers the painted world, not a "
            "bounding box)" if far[1] != resaved_pond[1] else "stood still"))

    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
