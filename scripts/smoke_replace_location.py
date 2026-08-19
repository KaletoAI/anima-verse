#!/usr/bin/env python3
"""Smoke run for re-placing a location: the occupants move with it
(Seamless World, E2 Task 1).

Runs against a THROWAWAY storage directory — never touches a real world.

Seed: inn placed at (50, 50), plan_width_m 10. npc_a via set_character_pos(52, 53)
(inside inn, off-centre). npc_b via save_character_current_location -> centre (50, 50).
npc_w wilderness at (30, 30). npc_x in inn, pos manually NULLed (direct state write).

[1] update_location_position(inn, 80.0, 90.0) — delta (+30, +40):
    npc_a -> (82.0, 93.0)   (delta preserved, relative offset kept)
    npc_b -> (80.0, 90.0)   (was at centre, delta lands it on new centre)
    npc_w -> (30.0, 30.0)   (wilderness, untouched)
    npc_x -> (80.0, 90.0)   (no pos -> new centre)
    all current_location values unchanged.
[2] update_location_position(inn, None, None) (unplace):
    npc_a keeps (82.0, 93.0), current_location STILL inn (state untouched —
    deliberate: the editor unplaces, gameplay cleanup is not its job).
[3] re-place inn at (0.0, 0.0) from unplaced: npc_a -> (0.0, 0.0) (centre,
    no old centre exists), npc_b -> (0.0, 0.0).

Occupants ROTATE with the location — the point is read back into the OLD local
frame and re-emitted from the NEW one (§ A1.1):
    local_to_world(lx, lz, cx, cz, yaw) = (cx + lx·cos yaw + lz·sin yaw,
                                           cz − lx·sin yaw + lz·cos yaw)

[4] re-seed inn at (50, 50) yaw 0, npc_a at (52, 53) (local offset +2/+3),
    npc_x's point NULLed again. Then yaw-ONLY: update to (50, 50) yaw 90.
    npc_a: local (2, 3) -> (50 + 2·cos90 + 3·sin90, 50 − 2·sin90 + 3·cos90)
                        = (50 + 0 + 3, 50 − 2 + 0) = (53.0, 48.0)
    npc_b sits on the centre: local (0, 0) -> (50.0, 50.0), unmoved.
    npc_x has no point -> new centre (50.0, 50.0).
    npc_w wilderness -> (30.0, 30.0), untouched.
[5] combined move AND rotate: from (50, 50) yaw 90 to (80, 90) yaw 180.
    npc_a at (53, 48): old local = (2, 3) (the offset from [4], read back)
      -> (80 + 2·cos180 + 3·sin180, 90 − 2·sin180 + 3·cos180)
       = (80 − 2 + 0, 90 − 0 − 3) = (78.0, 87.0)
    npc_b at the old centre (50, 50): local (0, 0) -> the new centre (80.0, 90.0).

Usage:  ./.venv/bin/python scripts/smoke_replace_location.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="replace-location-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="replace-location-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models.character import (  # noqa: E402
    _write_character_pos, get_character_current_location, get_character_pos,
    save_character_current_location, save_character_profile, set_character_pos)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location,
    update_location_position)

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


def set_plan_width(location_id: str, width: float) -> None:
    """DRAW the location's boundary as the centred square of edge ``width``
    (contract v6) and store the width the sanitizer derives from its bounding
    box. Since 2026-08-19 the width alone is no shape: without a drawn outline
    a location has no area anywhere. The square's corners are the ones the
    deleted synthesis produced, so every hand-derived number stays put."""
    half = round(float(width) / 2.0, 2)
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d["plan_width_m"] = width
            map3d["boundary"] = [[-half, -half], [half, -half],
                                 [half, half], [-half, half]]
            loc["map3d"] = map3d
    _save_world_data(data)


# ── Seed ────────────────────────────────────────────────────────────────
inn = add_location(name="Smoke Inn", description="replace-location smoke")
INN_ID = inn["id"]
update_location_position(INN_ID, 50.0, 50.0)
set_plan_width(INN_ID, 10.0)

for name in ("npc_a", "npc_b", "npc_w", "npc_x"):
    save_character_profile(name, {"current_location": ""}, create_new=True)

# npc_a: off-centre inside the inn — the point is the truth, the location
# is derived from it.
set_character_pos("npc_a", 52, 53)
# npc_b: teleported in, so its pos was synced to the inn centre.
save_character_current_location("npc_b", INN_ID)
# npc_w: never inside any footprint.
set_character_pos("npc_w", 30, 30)
# npc_x: inside the inn but without any point (legacy row, never positioned).
save_character_current_location("npc_x", INN_ID)
_write_character_pos("npc_x", None, None)

print("[0] seed")
check("npc_a pos", get_character_pos("npc_a"), {"x": 52.0, "z": 53.0})
check("npc_a location", get_character_current_location("npc_a"), INN_ID)
check("npc_b pos", get_character_pos("npc_b"), {"x": 50.0, "z": 50.0})
check("npc_b location", get_character_current_location("npc_b"), INN_ID)
check("npc_w pos", get_character_pos("npc_w"), {"x": 30.0, "z": 30.0})
check("npc_w location", get_character_current_location("npc_w"), "")
check("npc_x pos", get_character_pos("npc_x"), None)
check("npc_x location", get_character_current_location("npc_x"), INN_ID)

print("[1] re-placing the location drags its occupants along (delta shift)")
update_location_position(INN_ID, 80.0, 90.0)
check("npc_a keeps its relative offset",
      get_character_pos("npc_a"), {"x": 82.0, "z": 93.0})
check("npc_b lands on the new centre",
      get_character_pos("npc_b"), {"x": 80.0, "z": 90.0})
check("npc_w in the wilderness is untouched",
      get_character_pos("npc_w"), {"x": 30.0, "z": 30.0})
check("npc_x without a point goes to the new centre",
      get_character_pos("npc_x"), {"x": 80.0, "z": 90.0})
check("npc_a location unchanged",
      get_character_current_location("npc_a"), INN_ID)
check("npc_b location unchanged",
      get_character_current_location("npc_b"), INN_ID)
check("npc_w location unchanged", get_character_current_location("npc_w"), "")
check("npc_x location unchanged",
      get_character_current_location("npc_x"), INN_ID)

print("[2] unplacing leaves the occupants where they stand")
update_location_position(INN_ID, None, None)
check("npc_a pos untouched", get_character_pos("npc_a"), {"x": 82.0, "z": 93.0})
check("npc_a still in the location",
      get_character_current_location("npc_a"), INN_ID)
check("npc_b pos untouched", get_character_pos("npc_b"), {"x": 80.0, "z": 90.0})
check("npc_x pos untouched", get_character_pos("npc_x"), {"x": 80.0, "z": 90.0})

print("[3] placing from unplaced has no old centre — everyone to the new one")
update_location_position(INN_ID, 0.0, 0.0)
check("npc_a on the new centre", get_character_pos("npc_a"), {"x": 0.0, "z": 0.0})
check("npc_b on the new centre", get_character_pos("npc_b"), {"x": 0.0, "z": 0.0})
check("npc_w still untouched",
      get_character_pos("npc_w"), {"x": 30.0, "z": 30.0})

print("[4] turning the location turns its occupants with it (yaw only)")
# Re-seed: inn back at (50, 50) facing 0, npc_a off-centre by (+2, +3),
# npc_x point-less again — the yaw-only case has to answer for it too.
update_location_position(INN_ID, 50.0, 50.0, 0.0)
set_character_pos("npc_a", 52, 53)
_write_character_pos("npc_x", None, None)
check("npc_a re-seeded", get_character_pos("npc_a"), {"x": 52.0, "z": 53.0})
check("npc_b re-seeded on the centre",
      get_character_pos("npc_b"), {"x": 50.0, "z": 50.0})

update_location_position(INN_ID, 50.0, 50.0, 90.0)
check("npc_a rotates around the centre",
      get_character_pos("npc_a"), {"x": 53.0, "z": 48.0})
check("npc_b on the centre stays on the centre",
      get_character_pos("npc_b"), {"x": 50.0, "z": 50.0})
check("npc_x without a point goes to the centre",
      get_character_pos("npc_x"), {"x": 50.0, "z": 50.0})
check("npc_w in the wilderness is untouched",
      get_character_pos("npc_w"), {"x": 30.0, "z": 30.0})
check("npc_a location unchanged",
      get_character_current_location("npc_a"), INN_ID)

print("[5] moving AND turning at once is one and the same path")
update_location_position(INN_ID, 80.0, 90.0, 180.0)
check("npc_a keeps its local offset through move + turn",
      get_character_pos("npc_a"), {"x": 78.0, "z": 87.0})
check("npc_b on the centre lands on the new centre",
      get_character_pos("npc_b"), {"x": 80.0, "z": 90.0})
check("npc_w in the wilderness is untouched",
      get_character_pos("npc_w"), {"x": 30.0, "z": 30.0})

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
