#!/usr/bin/env python3
"""Checks who may travel through the ``**I am at …**`` marker — and who may not.

Usage:
    ./.venv/bin/python scripts/smoke_marker_travel.py

Runs against a THROWAWAY storage directory; no server, no real world, no LLM.
The journey itself is not exercised: ``travel_engine.start_journey`` is
replaced by a recorder, because what is decided here is WHETHER it is called.
The real one keeps its own gate (the target must be known to the character).

WHY THIS EXISTS

Measured on 2026-09-17: the marker's place change had been discarded since
June 2026 ("Lösung C") — 8 discarded attempts against 1 real room change in
the running log. At the same time the tool path was talked out of moving by
its action hint, so a party stood still: both ways closed. The user's
decision: a character WITHOUT tools must be able to travel, so the marker
starts a JOURNEY (the same call SetLocation makes, pathfinder and knowledge
gate included) — never a teleport.

EXPECTATIONS, derived by hand from that decision:

[1] A character that HAS the movement verb: no journey. It has a way to
    travel, and a second path for the same thing is the bug this strand
    came from.
[2] A character WITHOUT the verb: the marker starts a journey to the named
    place — this is the whole point of the decision.
[3] A party FOLLOWER without the verb: no journey. The verb is hidden from a
    follower on purpose (only the leader moves the group), so "has no verb"
    must not read as permission here.
[4] A player-controlled avatar: no journey. The avatar travels over the /play
    route, not through a chat reply.
[5] A room at the CURRENT place still changes instantly, for everyone, and is
    reported back as a room change — the marker's one remaining real job.
[6] A marker naming nothing known (no room, no place) changes nothing and
    starts nothing.

Each refusal also names its REASON (has_movement_verb / party_follower /
player_avatar), because the log line says why — a wrong reason there sends the
next reader after the wrong rule.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="marker-travel-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import party_engine as P  # noqa: E402
from app.core import travel_engine  # noqa: E402
from app.models import character as C  # noqa: E402
from app.models import world as W  # noqa: E402
from app.plugins.loader import discover_packages  # noqa: E402
from app.routes.chat import (_extract_location, _marker_travel_refusal,  # noqa: E402
                             _may_travel_by_marker)

discover_packages()

# add_location assigns the ids itself — the check works with what it returns.
HERE = THERE = ""
WITH_TOOL, NO_TOOL, FOLLOWER, LEADER, AVATAR = (
    "demo_one", "demo_two", "demo_three", "demo_four", "demo_five")

FAILURES = []
started = []          # (character, target_id) per recorded journey call


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def _recording_start_journey(character_name, target_id):
    started.append((character_name, target_id))
    return {"target": target_id}, ""


travel_engine.start_journey = _recording_start_journey

HERE = W.add_location("Here", "", rooms=[{"id": "room_a", "name": "Hall"},
                                         {"id": "room_b", "name": "Cellar"}])
THERE = W.add_location("There", "", rooms=[])
HERE = HERE.get("id") if isinstance(HERE, dict) else HERE
THERE = THERE.get("id") if isinstance(THERE, dict) else THERE
assert HERE and THERE, "setup: the two places could not be created"

for name in (WITH_TOOL, NO_TOOL, FOLLOWER, LEADER, AVATAR):
    C.save_character_profile(name, {"character_name": name,
                                    "current_location": HERE,
                                    "current_room": "room_a"}, create_new=True)
    C.set_known_locations(name, [HERE, THERE])

# The verb is on by default; these two do without it.
for name in (NO_TOOL, FOLLOWER, AVATAR):
    C.save_character_skill_config(name, "setlocation", {"enabled": False})
for name in (FOLLOWER, LEADER):
    C.save_character_skill_config(name, "leave_party", {"enabled": True})
    C.save_character_skill_config(name, "join_party", {"enabled": True})
assert P.add_to_party(LEADER, FOLLOWER), "setup: the party could not be formed"

MARKER = "I set off. **I am at There**"

print("\n[1] has the movement verb")
started.clear()
check("gate says no", _may_travel_by_marker(WITH_TOOL) is False)
check("for the right reason", _marker_travel_refusal(WITH_TOOL) == "has_movement_verb",
      _marker_travel_refusal(WITH_TOOL))
check("no journey", _extract_location(WITH_TOOL, MARKER) is None and started == [],
      str(started))

print("\n[2] has no movement verb")
started.clear()
check("gate says yes", _may_travel_by_marker(NO_TOOL) is True)
_extract_location(NO_TOOL, MARKER)
check("journey started to the named place", started == [(NO_TOOL, THERE)], str(started))
check("but the character is not moved there",
      C.get_character_current_location(NO_TOOL) == HERE)

print("\n[3] party follower without the verb")
started.clear()
check("gate says no", _may_travel_by_marker(FOLLOWER) is False)
check("for the right reason", _marker_travel_refusal(FOLLOWER) == "party_follower",
      _marker_travel_refusal(FOLLOWER))
check("no journey", _extract_location(FOLLOWER, MARKER) is None and started == [],
      str(started))

print("\n[4] player-controlled avatar")
started.clear()
from app.models import account  # noqa: E402
_real_is_player = account.is_player_controlled
import app.models.account as _acct  # noqa: E402
_acct.is_player_controlled = lambda n: n == AVATAR
check("gate says no", _may_travel_by_marker(AVATAR) is False)
check("for the right reason", _marker_travel_refusal(AVATAR) == "player_avatar",
      _marker_travel_refusal(AVATAR))
check("no journey", _extract_location(AVATAR, MARKER) is None and started == [],
      str(started))
_acct.is_player_controlled = _real_is_player

print("\n[5] a room at the current place still works")
started.clear()
res = _extract_location(NO_TOOL, "I step down. **I am at Cellar**")
check("reports the room change", (res or {}).get("room") == "room_b", str(res))
check("no journey for a room", started == [], str(started))
check("the character really stands there",
      C.get_character_current_room(NO_TOOL) == "room_b",
      C.get_character_current_room(NO_TOOL))

print("\n[6] a marker naming nothing known")
started.clear()
check("nothing happens",
      _extract_location(NO_TOOL, "**I am at Atlantis**") is None and started == [],
      str(started))

print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
sys.exit(1 if FAILURES else 0)
