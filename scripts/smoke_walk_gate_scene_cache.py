#!/usr/bin/env python3
"""Smoke run: the walk gate reads its scene through the scene cache.

QQmodel_surface._scene_specsQQ (the server's walk gate, QQPOST /play/posQQ)
used to call QQscene_inputsQQ + QQcompose_sceneQQ itself every time its own
5-second TTL ran out — a full composition per walked location every 5 s,
although QQGET /play/locations/{id}/sceneQQ already holds exactly that
composition per location under an input fingerprint
(QQscene_recipe.scene_for_locationQQ). Now both read the same cached payload.

Runs against a THROWAWAY storage directory — never a real world, no server,
no LLM, no image call. QQlocation_model3d._demand_lowQQ is stubbed (it would
ask for a distance mesh); QQscene_recipe.compose_sceneQQ is wrapped by a
counter and is otherwise the real composer.

The seed (hand-built, every expectation below is derived from it):

    location "Yard"   pin (0, 0), plan_width_m 20, a drawn 20 m square
                      (corners ±10), one room "hut" with layout
                      x=-4 y=-4 w=8 d=8, level 0, model_offset_y 0.0
    room model        one stored file in the hut's gallery, sidecar
                      {tier full, width_m 4, walk_y 0.5} (the same helper as
                      scripts/smoke_prop_water.py: gallery.new_path +
                      write_sidecar + gallery.select)
    location "Bare"   pin (100, 0), no layout, no outline, no model

The declared walk height (scripts/smoke_scene_recipe.py [4i] derives the
chain): storey 0 is the terrain (floor 0.00), the diorama hangs at
bottom_y = floor 0.00 + DIORAMA_CLEARANCE 0.02 + model_offset_y, and
walk_y_world = bottom_y + walk_y:

    offset  0.00  -> bottom_y  0.02 -> walk_y_world  0.02 + 0.5 = 0.52
    offset -0.30  -> bottom_y -0.28 -> walk_y_world -0.28 + 0.5 = 0.22
    offset -0.10  -> only used to force a fresh compose in [S4]

Hand-derived expectations
-------------------------

[S1] QQ_scene_specs(yard)QQ -> compose counter 1; the hut declares
     walk_y_world 0.52. QQforget_surfaces("yard")QQ drops the gate's own
     5 s cache; the second call finds the SCENE cache warm (no input moved)
     -> counter stays 1. Before the change the gate composed on its own:
     counter 2 — that is the RED half.
[S2] QQscene_for_location(yard, id)QQ right after [S1] -> counter stays 1:
     the walk gate and the scene route share ONE composition.
     The real POST /play/pos hands the walk gate the entry of
     QQlist_locations()QQ (play.py: QQ_locs = list_locations()QQ, then
     QQlocation_at_point(..., _locs)QQ -> QQstand_height_at(derived, ...)QQ),
     not QQget_location_by_idQQ. That entry must hit the SAME cache slot:
     QQforget_surfaces(yard)QQ, QQ_scene_specs(entry)QQ and
     QQscene_for_location(entry, id)QQ -> counter still 1, and the payload is
     the very object the QQget_location_by_idQQ read got. The other order
     too: QQinvalidate_scene_cache()QQ, compose through the list entry
     (counter 2), then QQscene_for_location(yard(), id)QQ -> counter stays 2.
     Were the two dicts ever to fingerprint differently, route and walk gate
     would evict each other in the one slot per location and every call
     would compose again.
[S3] the hut's layout gets model_offset_y -0.30 via QQupsert_locationQQ,
     QQforget_surfacesQQ -> the next QQ_scene_specsQQ composes: counter 2,
     and the declaration names the hut with walk_y_world 0.22.
[S4] offset -0.10 (a fresh input), QQforget_surfacesQQ, QQcompose_sceneQQ
     raising -> QQ([], [])QQ, the composer asked once and exactly ONE
     QQlogger.exceptionQQ from model_surface; a second call within the 5 s
     TTL composes nothing and logs nothing more.
[S5] back to the [S3] layout (offset -0.30). [S4] cached no scene, so the
     scene cache still holds the [S3] payload under the [S3] fingerprint:
     QQscene_for_locationQQ composes nothing. Then QQ_scene_specsQQ and
     QQstand_height_at(yard, 0, 0)QQ — (0, 0) lies inside the hut's hull,
     the room has no lattice, so rung 1 answers: datum (flat, empty terrain)
     0 + lift 0 + 0.22, and max(ground 0, 0.22) = 0.22. The shared payload is
     byte-identical before and after (json.dumps(sort_keys=True)) and the very
     same object — nobody wrote into it.
[S6] "Bare" -> QQscene_for_locationQQ is None, QQ_scene_specsQQ ->
     QQ([], [])QQ, no composition.

Usage:  ./.venv/bin/python scripts/smoke_walk_gate_scene_cache.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="walk-gate-scene-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="walk-gate-scene-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import location_model3d as lm  # noqa: E402
from app.core import model_surface  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.core.model_store import write_sidecar  # noqa: E402
from app.models.world import (  # noqa: E402
    add_location, get_location_by_id, list_locations,
    update_location_position, upsert_location)

FAILURES = []
CHECKED = 0


def check(label, ok, detail=""):
    global CHECKED
    CHECKED += 1
    print(f"  {'OK ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-6):
    try:
        return abs(float(a) - float(b)) <= eps
    except (TypeError, ValueError):
        return False


# ── stubs: no distance-mesh demand, a counting composer ─────────────────
lm._demand_low = lambda *a, **k: None
REAL_COMPOSE = scene_recipe.compose_scene
COMPOSES = [0]
RAISE = [False]


def counting_compose(*args, **kwargs):
    COMPOSES[0] += 1
    if RAISE[0]:
        raise RuntimeError("smoke: compose failed on purpose")
    return REAL_COMPOSE(*args, **kwargs)


scene_recipe.compose_scene = counting_compose

EXCEPTIONS = [0]
_real_exception = model_surface.logger.exception


def counting_exception(*args, **kwargs):
    EXCEPTIONS[0] += 1
    return _real_exception(*args, **kwargs)


model_surface.logger.exception = counting_exception

# ── the world ───────────────────────────────────────────────────────────
YARD = add_location(name="Yard", description="walk gate smoke",
                    rooms=[{"id": "hut", "name": "Hut"}])["id"]
update_location_position(YARD, 0.0, 0.0)
BARE = add_location(name="Bare", description="nothing to compose")["id"]
update_location_position(BARE, 100.0, 0.0)


def shape(offset_y):
    """The yard's drawn square plus the hut's layout at `offset_y`."""
    loc = get_location_by_id(YARD)
    loc["map3d"] = {"plan_width_m": 20.0,
                    "boundary": [[-10.0, -10.0], [10.0, -10.0],
                                 [10.0, 10.0], [-10.0, 10.0]]}
    loc["rooms"][0]["layout"] = {"x": -4, "y": -4, "w": 8, "d": 8,
                                 "level": 0, "model_offset_y": offset_y}
    assert upsert_location(loc, sync_world=False)


shape(0.0)
gallery = lm._gallery(YARD, "hut")
room_model = gallery.new_path()
room_model.write_bytes(b"room-stub")
write_sidecar(room_model, {"tier": "full", "width_m": 4, "walk_y": 0.5,
                           "rotation": {}})
gallery.select(room_model.name, "full")


def yard():
    return get_location_by_id(YARD)


def hut_walk(decs):
    return [round(float(d["spec"]["walk_y_world"]), 6) for d in decs
            if str(d["spec"].get("room_id")) == "hut"]


print("[S1] the walk gate reads the scene cache")
model_surface.forget_surfaces()
scene_recipe.invalidate_scene_cache()
specs, decs = model_surface._scene_specs(yard())
check("first call composes once", COMPOSES[0] == 1, str(COMPOSES[0]))
check("the hut declares walk_y_world 0.52", hut_walk(decs) == [0.52],
      str(hut_walk(decs)))
model_surface.forget_surfaces(YARD)
model_surface._scene_specs(yard())
check("after forget_surfaces: still 1 compose (scene-cache hit)",
      COMPOSES[0] == 1, str(COMPOSES[0]))

print("[S2] walk gate and scene route share one composition")
scene = scene_recipe.scene_for_location(yard(), YARD)
check("scene_for_location returns the payload", scene is not None)
check("scene_for_location composes nothing more", COMPOSES[0] == 1,
      str(COMPOSES[0]))


def yard_listed():
    """The yard as POST /play/pos sees it: its entry of list_locations()."""
    return next(l for l in list_locations() if l.get("id") == YARD)


model_surface.forget_surfaces(YARD)
model_surface._scene_specs(yard_listed())
check("walk gate with the list_locations entry: no compose",
      COMPOSES[0] == 1, str(COMPOSES[0]))
listed_scene = scene_recipe.scene_for_location(yard_listed(), YARD)
check("scene_for_location(list entry): no compose", COMPOSES[0] == 1,
      str(COMPOSES[0]))
check("...the very payload of the get_location_by_id read",
      listed_scene is scene)
scene_recipe.invalidate_scene_cache()
model_surface.forget_surfaces(YARD)
model_surface._scene_specs(yard_listed())
check("cold cache, list entry composes once (counter 2)", COMPOSES[0] == 2,
      str(COMPOSES[0]))
scene_recipe.scene_for_location(yard(), YARD)
check("then get_location_by_id hits it (counter stays 2)", COMPOSES[0] == 2,
      str(COMPOSES[0]))
COMPOSES[0] = 1  # [S3]..[S6] count from the [S1]/[S2] state

print("[S3] a layout change recomposes")
shape(-0.30)
model_surface.forget_surfaces(YARD)
specs, decs = model_surface._scene_specs(yard())
check("compose counter 2", COMPOSES[0] == 2, str(COMPOSES[0]))
check("the hut declares walk_y_world 0.22", hut_walk(decs) == [0.22],
      str(hut_walk(decs)))

print("[S4] a failing compose blocks nothing and logs once")
shape(-0.10)
model_surface.forget_surfaces(YARD)
RAISE[0] = True
before_c, before_e = COMPOSES[0], EXCEPTIONS[0]
try:
    got = model_surface._scene_specs(yard())
    check("answer ([], [])", got == ([], []), str(got))
    check("the composer was asked once", COMPOSES[0] == before_c + 1,
          str(COMPOSES[0] - before_c))
    check("exactly one logger.exception", EXCEPTIONS[0] == before_e + 1,
          str(EXCEPTIONS[0] - before_e))
    got2 = model_surface._scene_specs(yard())
    check("second call within 5 s: ([], [])", got2 == ([], []), str(got2))
    check("...composes nothing", COMPOSES[0] == before_c + 1,
          str(COMPOSES[0] - before_c))
    check("...logs nothing more", EXCEPTIONS[0] == before_e + 1,
          str(EXCEPTIONS[0] - before_e))
finally:
    RAISE[0] = False

print("[S5] the shared payload stays untouched")
shape(-0.30)
model_surface.forget_surfaces(YARD)
c0 = COMPOSES[0]
shared = scene_recipe.scene_for_location(yard(), YARD)
check("the [S3] payload is still cached (no compose)", COMPOSES[0] == c0,
      str(COMPOSES[0] - c0))
dump_before = json.dumps(shared, sort_keys=True, default=str)
specs, decs = model_surface._scene_specs(yard())
h = model_surface.stand_height_at(yard(), 0.0, 0.0)
check("stand_height_at inside the hut = 0.22 (rung 1)", near(h, 0.22), str(h))
again = scene_recipe.scene_for_location(yard(), YARD)
check("payload byte-identical after the walk gate read it",
      dump_before == json.dumps(again, sort_keys=True, default=str))
check("...and it is the very same object", again is shared)
check("still no compose", COMPOSES[0] == c0, str(COMPOSES[0] - c0))

print("[S6] nothing to compose")
c0 = COMPOSES[0]
bare = get_location_by_id(BARE)
check("scene_for_location(bare) is None",
      scene_recipe.scene_for_location(bare, BARE) is None)
model_surface.forget_surfaces(BARE)
check("_scene_specs(bare) == ([], [])",
      model_surface._scene_specs(bare) == ([], []))
check("no composition", COMPOSES[0] == c0, str(COMPOSES[0] - c0))

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
