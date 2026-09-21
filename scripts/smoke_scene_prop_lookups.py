#!/usr/bin/env python3
"""Smoke run for IMG-9: the scene composer asks the prop library once per
PROP, not once per PLACEMENT.

``scene_recipe._prop_models`` read ``props.get_prop(pid)`` inside the loop over
``recipe["placements"]`` and used exactly one field of the answer
(``tags``, for the ``walkable`` gate); ``_door_prop_models`` did the same per
door. ``props.get_prop`` is not a lookup: per call it parses the prop's
sidecar, ensures its bounding box, scans a model gallery per ACTIVE variant,
resolves the default tier and parses that file's areas sidecar. A room with
200 placements of 40 props paid all of that 200 times for an answer that is
identical per prop id.

The fix is a REQUEST-LOCAL memo (``scene_recipe._prop_record``), created once
in ``compose_scene`` and handed to both builders. Request-local on purpose:
props are edited while the server runs, so a module-level cache would serve a
stale sidecar.

Runs against a THROWAWAY storage directory — it never touches a real world,
never starts a server and makes no LLM/image call.

The fixture (hand-built, so every expectation below is derived from it):

    40 props ``prop00`` … ``prop39``, sidecar only (no mesh), every fourth
    one tagged ``walkable``
    one room recipe with 200 placements, ``prop_id = prop<i mod 40>``
    ten doorways, each naming ``prop00`` or ``prop01``

Hand-derived expectations
-------------------------

[1] ``_prop_models`` over the 200 placements

      without a memo (``prop_cache=None`` — the OLD code path, kept as the
      parameter's default):  one call per placement          = 200
      with a shared memo:    one call per DISTINCT prop id    =  40

    This is the "fails before / passes after" pair in one run: the None branch
    IS the pre-fix behaviour, line for line.

[2] the result is unchanged. The 200 specs composed with the memo are
    compared field by field against the 200 composed without it — a memo that
    changed a single number would be a different bug, not a fix.

[3] ``_door_prop_models`` over the ten doorways

      without a memo: one call per door naming a prop            = 10
      with the memo already filled by [1]: ``prop00``/``prop01``
      are in it, so the doors add                                =  0

    …and the ``{prop_id: model_signature}`` map it returns beside the specs is
    identical either way (two entries, one per distinct prop).

[4] ``compose_scene`` shares ONE memo across rooms AND doors. The count is not
    predicted in absolute terms here (``room_recipe._join_placements`` has a
    per-layout memo of its own, so the recipe phase contributes a number that
    belongs to that function, not to this fix). What IS derived by hand is the
    DIFFERENCE: composing the same location again with 100 EXTRA placements of
    props that are already placed must cost

      before the fix: +100 calls (one per new placement)
      after the fix:    +0 calls (every id is already in the memo)

[5] timing. Both variants are run 5× and the milliseconds printed. Not a
    threshold — a machine-dependent number is no check — but the factor is the
    whole point of the finding, so it is on the record.

Usage:  ./.venv/bin/python scripts/smoke_scene_prop_lookups.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="scene-prop-lookups-"))
CLIPS = Path(tempfile.mkdtemp(prefix="scene-prop-lookups-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402

FAILURES = []
CHECKED = 0

N_PROPS = 40
N_PLACEMENTS = 200
N_DOORS = 10
STOREY = 3.0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the prop library ────────────────────────────────────────────────────
def prop_id(i: int) -> str:
    return f"prop{i:02d}"


def make_props() -> None:
    """40 sidecar-only props. Written straight into the store's own layout
    (``<storage>/props/<id>/sidecar.json``) — nothing here needs a mesh, and a
    prop without one is a perfectly normal library entry."""
    for i in range(N_PROPS):
        pid = prop_id(i)
        d = STORAGE / "props" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / prop_store.SIDECAR_NAME).write_text(json.dumps({
            "name": f"Prop {i}",
            "category": "furniture",
            "width_m": 1.0, "depth_m": 0.6, "height_m": 0.8,
            # Every fourth one is walkable — the one field `_prop_models`
            # reads off the record.
            "tags": ["walkable"] if i % 4 == 0 else ["decor"],
        }), encoding="utf-8")


make_props()


# ── the call counter ────────────────────────────────────────────────────
_real_get_prop = prop_store.get_prop
_calls = {"n": 0}


def _counting_get_prop(pid):
    _calls["n"] += 1
    return _real_get_prop(pid)


def counted(fn, *args, **kwargs):
    """``fn(*args)`` with every ``props.get_prop`` counted. The patch sits on
    the MODULE, which is how both builders reach the function."""
    prop_store.get_prop = _counting_get_prop
    _calls["n"] = 0
    try:
        t0 = time.perf_counter()
        out = fn(*args, **kwargs)
        dt = time.perf_counter() - t0
    finally:
        prop_store.get_prop = _real_get_prop
    return out, _calls["n"], dt


def ms(fn, *args, n: int = 5) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        fn(*args)
    return (time.perf_counter() - t0) * 1000.0 / n


# ── the recipe and the doorways ─────────────────────────────────────────
def recipe(count: int = N_PLACEMENTS) -> dict:
    """One room recipe with ``count`` placements, cycling through the 40
    props — the shape ``_prop_models`` receives from ``compose_recipe``."""
    return {
        "room_id": "hall",
        "level": 0,
        "outline": [[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
        "placements": [
            {"prop_id": prop_id(i % N_PROPS),
             "at": [float(i % 20), float(i // 20)],
             "yaw": 0.0,
             "dims": {"width_m": 1.0, "depth_m": 0.6, "height_m": 0.8}}
            for i in range(count)],
    }


def doorways() -> list:
    """Ten thresholds, each with a door prop — the shape
    ``_door_prop_models`` receives from ``_doorways``."""
    return [{"level": 0, "rooms": ["hall"], "at_world": [float(i), 0.0],
             "along": [1.0, 0.0], "width_m": 0.9, "height_m": 2.0,
             "base_y": 0.0, "outside": False,
             "_door_prop": {"id": prop_id(i % 2), "hinge": "left",
                            "leaf": True}}
            for i in range(N_DOORS)]


def main() -> int:
    print("[1] _prop_models: one call per placement -> one per prop")
    r = recipe()
    old_specs, old_calls, old_dt = counted(
        scene_recipe._prop_models, r, STOREY, None)
    cache = {}
    new_specs, new_calls, new_dt = counted(
        scene_recipe._prop_models, r, STOREY, cache)
    check("placements composed", len(new_specs), N_PLACEMENTS)
    check("without the memo: one get_prop per placement",
          old_calls, N_PLACEMENTS)
    check("with the memo: one get_prop per distinct prop",
          new_calls, N_PROPS)
    check("the memo holds exactly the 40 records", len(cache), N_PROPS)
    print(f"  --  {old_dt * 1000:.1f} ms  ->  {new_dt * 1000:.1f} ms "
          f"(single run, {N_PLACEMENTS} placements of {N_PROPS} props)")

    print("\n[2] the result is unchanged")
    check("all 200 specs identical", new_specs == old_specs, True)
    check("the walkable gate still fires on every fourth prop",
          sum(1 for s in new_specs if s.get("walkable")),
          sum(1 for i in range(N_PLACEMENTS) if (i % N_PROPS) % 4 == 0))

    print("\n[3] _door_prop_models rides the same memo")
    doors = doorways()
    old_doors, old_door_calls, _ = counted(
        scene_recipe._door_prop_models, doors, None)
    new_doors, new_door_calls, _ = counted(
        scene_recipe._door_prop_models, doorways(), cache)
    check("without the memo: one get_prop per door",
          old_door_calls, N_DOORS)
    check("with the filled memo: none at all", new_door_calls, 0)
    check("same specs", new_doors[0] == old_doors[0], True)
    check("same signature map", new_doors[1], old_doors[1])
    check("…and it names the two distinct door props",
          sorted(new_doors[1]), [prop_id(0), prop_id(1)])

    print("\n[4] compose_scene shares ONE memo across rooms and doors")
    rooms = [{"id": "hall", "name": "Hall",
              "layout": {"x": 0, "y": 0, "w": 20, "d": 20,
                         "props": [
                             {"id": f"p{i}", "prop_id": prop_id(i % 4),
                              "at": [float(i % 10) + 0.5, 1.0], "yaw": 0}
                             for i in range(20)]}},
             {"id": "annex", "name": "Annex",
              "layout": {"x": 22, "y": 0, "w": 10, "d": 10,
                         "props": [
                             {"id": f"q{i}", "prop_id": prop_id(i % 4),
                              "at": [float(i % 8) + 0.5, 1.0], "yaw": 0}
                             for i in range(20)]}}]

    def location(extra: int):
        """The same two rooms, with ``extra`` MORE placements of props that
        are already placed (so no new prop id enters the scene)."""
        grown = [dict(r_) for r_ in rooms]
        grown[0] = {**rooms[0],
                    "layout": {**rooms[0]["layout"],
                               "props": rooms[0]["layout"]["props"] + [
                                   {"id": f"x{i}", "prop_id": prop_id(i % 4),
                                    "at": [float(i % 10) + 0.5, 5.0],
                                    "yaw": 0}
                                   for i in range(extra)]}}
        return {"id": "loc", "name": "Hall House", "rooms": grown,
                "map3d": {"plan_width_m": 40.0,
                          "boundary": [[-20.0, -20.0], [20.0, -20.0],
                                       [20.0, 20.0], [-20.0, 20.0]]}}

    base_scene, base_calls, _ = counted(scene_recipe.compose_scene,
                                        location(0), plan_width_m=40.0)
    grown_scene, grown_calls, _ = counted(scene_recipe.compose_scene,
                                          location(100), plan_width_m=40.0)
    print(f"  --  {base_calls} get_prop calls for 40 placements, "
          f"{grown_calls} for 140")
    check("100 extra placements of known props cost no extra lookup",
          grown_calls - base_calls, 0)
    check("…and they really are in the scene",
          len([m for m in grown_scene["models"] if m.get("role") == "prop"])
          - len([m for m in base_scene["models"] if m.get("role") == "prop"]),
          100)

    print("\n[5] timing, averaged over 5 runs")
    old_ms = ms(lambda: scene_recipe._prop_models(r, STOREY, None))
    new_ms = ms(lambda: scene_recipe._prop_models(r, STOREY, {}))
    print(f"  --  per call: {old_ms:.2f} ms  ->  {new_ms:.2f} ms"
          + (f"  (factor {old_ms / new_ms:.1f})" if new_ms else ""))

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
