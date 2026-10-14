#!/usr/bin/env python3
"""Fog-before-profile regression, baseline 718322ce, using the load smoke's temp world.

Six hand-derived cases: unknown location hides; show_all includes; distant point
journey hides; stale destination and v1 journeys count as resting; valid location
journey remains visible on explored wilderness. A poll-to-poll move must hide
without loading the moved NPC. All payload fields match the explicit baseline.
Usage: ./.venv/bin/python scripts/smoke_worldmap_fog_first.py
"""
from collections import Counter
from unittest.mock import patch

import smoke_worldmap_profile_loads as seed
from app.core import paths

# Reuse the seed module's throwaway world and make the redirect explicit.
paths.init(seed.STORAGE)
from app.core import exploration, world_ops
from app.models import character

baseline = seed.load_head_module()
assert baseline is not None, "718322ce baseline is required"
NPC = "npc_still"
AVATAR = "npc_lead"
character.set_known_locations(AVATAR, [seed.HOUSE])
exploration.mark_explored(AVATAR, 200, 0)
exploration.mark_explored(AVATAR, 600, 0)


def fixture(location, journey, target):
    character.set_character_pos(NPC, 600 if not location else 200, 0)
    character.save_character_current_location(NPC, location)
    profile = character.get_character_profile(NPC)
    profile["journey"] = journey
    profile["movement_target"] = target
    character.save_character_profile(NPC, profile)


def build(fn, show_all):
    calls = Counter()
    real = character.get_character_profile

    def counted(name):
        calls[name] += 1
        return real(name)

    with patch.object(character, "get_character_profile", counted):
        payload = fn(AVATAR, show_all)
    return payload, calls[NPC]


journey = {"target": seed.MARKET,
           "waypoints": [[600, 0, 0], [200, 0, 400]],
           "started_at_game": seed.FROZEN.canonical(), "speed_m_s": 1}
cases = [
    ("unknown location", seed.MARKET, None, "", False, False),
    ("show_all", seed.MARKET, None, "", True, True),
    ("point journey", "", dict(journey, target="", target_point={"x": 800, "z": 0}), "", False, False),
    ("stale destination", "", journey, seed.HOUSE, False, False),
    ("v1 journey", "", {"target": seed.MARKET, "path": [seed.HOUSE, seed.MARKET]}, seed.MARKET, False, False),
    ("valid wilderness journey", "", journey, seed.MARKET, False, True),
]
failures = []
for label, loc, route, target, show_all, visible in cases:
    fixture(loc, route, target)
    old, _ = build(baseline.build_worldmap_payload, show_all)
    fixture(loc, route, target)
    current, loads = build(world_ops.build_worldmap_payload, show_all)
    present = bool(seed.row(current, NPC))
    # v1 cleanup uses set_movement_target plus its save-time is_temporary_npc
    # reader: two existing profile reads, without building a hidden row.
    # That is distinct from loading the profile to build a hidden map row.
    budget = 2 if label == "v1 journey" else int(visible)
    ok = present == visible and loads <= budget and old == current
    print(f"{'OK' if ok else 'FAIL'} {label}: visible={present}, loads={loads}, baseline={old == current}")
    if not ok:
        failures.append(label)

fixture(seed.HOUSE, None, "")
first, _ = build(world_ops.build_worldmap_payload, False)
assert seed.row(first, NPC), "first poll sees room-mate"
fixture(seed.MARKET, None, "")
second, loads = build(world_ops.build_worldmap_payload, False)
if seed.row(second, NPC) or loads:
    failures.append("move between polls")
# A profile arriving after the batch may reflect a concurrent move. It must
# pass the gates again before its newer location reaches the player.
fixture(seed.HOUSE, None, "")
real_profile = character.get_character_profile
moved = []


def move_on_load(name):
    if name == NPC and not moved:
        moved.append(True)
        character.save_character_current_location(name, seed.MARKET)
    return real_profile(name)


with patch.object(character, "get_character_profile", move_on_load):
    racing = world_ops.build_worldmap_payload(AVATAR, False)
if seed.row(racing, NPC):
    failures.append("move between batch and profile")
print(f"poll-to-poll move: loads={loads}; failures={failures}")
raise SystemExit(bool(failures))
