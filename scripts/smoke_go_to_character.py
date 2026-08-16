#!/usr/bin/env python3
"""Smoke run for the GoToCharacter decision logic
(plan-room-conversation-ergaenzungsplan.md, A10 / Task R2).

Checks ``plugins.movement.go_to_resolve.resolve_go_to`` — the pure function
the verb uses to pick WHICH movement path applies. Needs no server, no
world DB and no LLM: the function imports nothing from ``app``.

Usage:  ./.venv/bin/python scripts/smoke_go_to_character.py

Rules every expectation below is derived from BY HAND (they are the
verb's contract, not a recording of its output):

  * The verb aims at the target person's CURRENT spot — ``current_location``
    / ``current_room``. For a travelling person that is the nearest cell
    (the game truth), never their journey destination; the function only
    ever sees the resolved ids, so this is a caller rule, not a branch.
  * Standing in the same location AND the same room means there is nothing
    to do at all → ``same_room``.
  * Same location, different room → the instant room change of SetLocation.
    The payload is the ROOM id, because that is what has to change.
  * Different location → allowed only when the actor already knows that
    place; the knowledge source is the same one the "Places you can go"
    block uses. Payload is the LOCATION id.
  * Anything else → ``unknown``: the verb refuses and lists what the actor
    knows. It must never hand out new world knowledge (house rule
    "known_locations strict" — a missing entry is NOT "unrestricted").
  * A person who is nowhere on the map (off-map sleep, never placed) has no
    spot to walk to → ``unknown`` with an empty payload, whatever the actor
    knows.
  * "Same location" is decided on the ids alone. An actor who is nowhere
    (``actor_loc == ""``) therefore never matches a placed target, and
    falls through to the knowledge check — an empty id must not read as
    "we are in the same nowhere".

Hand-derived expectations (actor knows INN and FOREST, not CAVE):

  [1] actor INN/bar,  target INN/bar     → ("same_room", "INN")
  [2] actor INN/bar,  target INN/kitchen → ("room",      "kitchen")
  [3] actor INN/bar,  target FOREST/""   → ("location",  "FOREST")
  [4] actor INN/bar,  target CAVE/""     → ("unknown",   "CAVE")
  [5] actor INN/bar,  target ""/""       → ("unknown",   "")
  [6] actor ""/"",    target INN/bar     → ("location",  "INN")
  [7] actor INN/"",   target INN/""      → ("same_room", "INN")   both on
      the location's ground — no room id on either side is still "together"
  [8] actor INN/"",   target INN/kitchen → ("room",      "kitchen")
  [9] whitespace and non-string knowledge entries are normalised away:
      actor " INN "/" bar ", target "INN"/"bar" → ("same_room", "INN")
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plugins.movement.go_to_resolve import resolve_go_to  # noqa: E402

KNOWN = ["INN", "FOREST"]

CHECKED = 0
FAILURES = []


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


print("\n[1-4] the four cases of the contract")
check("same room — nothing to do",
      resolve_go_to("INN", "bar", "INN", "bar", KNOWN),
      ("same_room", "INN"))
check("same location, other room — instant room change",
      resolve_go_to("INN", "bar", "INN", "kitchen", KNOWN),
      ("room", "kitchen"))
check("known other location — journey",
      resolve_go_to("INN", "bar", "FOREST", "", KNOWN),
      ("location", "FOREST"))
check("unknown location — refuse, teach nothing",
      resolve_go_to("INN", "bar", "CAVE", "", KNOWN),
      ("unknown", "CAVE"))

print("\n[5-6] nobody-there / nowhere-yet")
check("target off the map",
      resolve_go_to("INN", "bar", "", "", KNOWN),
      ("unknown", ""))
check("actor nowhere, target in a known place",
      resolve_go_to("", "", "INN", "bar", KNOWN),
      ("location", "INN"))

print("\n[7-8] the location's ground counts as a room")
check("both on the ground",
      resolve_go_to("INN", "", "INN", "", KNOWN),
      ("same_room", "INN"))
check("actor on the ground, target in a room",
      resolve_go_to("INN", "", "INN", "kitchen", KNOWN),
      ("room", "kitchen"))

print("\n[9] input hygiene")
check("padded ids are stripped before comparing",
      resolve_go_to(" INN ", " bar ", "INN", "bar", KNOWN),
      ("same_room", "INN"))
check("empty/None knowledge entries are dropped",
      resolve_go_to("INN", "bar", "FOREST", "", ["", None, "FOREST"]),
      ("location", "FOREST"))
check("no knowledge at all",
      resolve_go_to("INN", "bar", "FOREST", "", None),
      ("unknown", "FOREST"))

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
