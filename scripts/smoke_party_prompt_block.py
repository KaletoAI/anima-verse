#!/usr/bin/env python3
"""Checks that a party is VISIBLE in the prompts — and exactly once.

Usage:
    ./.venv/bin/python scripts/smoke_party_prompt_block.py

Runs against a THROWAWAY storage directory; no server, no real world, no LLM.

THE BUG THIS PINS DOWN

The party verbs existed, the engine dragged followers along — but no prompt
ever said a party was there. In 1137 logged prompts of the user's world not
one carried a party status. A leader therefore waited for its followers to
"come along", which is the one thing they cannot do: the movement verbs are
hidden from a follower (SetLocationSkill.visible_for), so only the leader can
move the group.

EXPECTATIONS, derived by hand from the party rules (plan-party-system.md:
one leader, N followers, only the leader moves, leaving is always allowed):

[1] No party -> no section at all. Nothing is added to a prompt "just in case".
[2] Leader -> the section names the followers, says that only the leader picks
    the destination and that setting out takes them along.
[3] Follower -> the section names the leader and says this character cannot
    set out on its own while it follows.
[4] Both roles are told they may leave — leaving is always allowed.
[5] The section reaches the prompt EXACTLY ONCE although the package has three
    verbs in one class: only the `leave` verb emits it, because `leave` is
    visible exactly when the character is in a party (PartySkill.visible_for).
    invite and join must stay silent in every state.
[6] One follower reads "X travels with you", two read "X and Y travel with
    you" — the line is spoken to the character, so it has to be grammatical.

NOTE the party verbs are ALWAYS_LOAD, i.e. off until a character enables them.
A character without them gets no section — it also has no way into a party.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="party-block-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import party_engine as P  # noqa: E402
from app.models import character as C  # noqa: E402
from plugins.party.blocks import party_section  # noqa: E402

# Deliberately not substrings of one another: a check like "the section does
# not name the leader itself" would otherwise pass or fail by accident.
LEADER, FOLLOWER, SOLO = "demo_one", "demo_two", "demo_three"
LOC = "loc_lake"

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


for name in (LEADER, FOLLOWER, SOLO):
    C.save_character_profile(name, {"character_name": name,
                                    "current_location": LOC,
                                    "current_room": ""}, create_new=True)

# [1] before any party exists
print("\n[1] no party")
for name in (LEADER, FOLLOWER, SOLO):
    check(f"{name} has no section", party_section(name) == "")

assert P.add_to_party(LEADER, FOLLOWER), "setup: the party could not be formed"

# [2] leader
print("\n[2] leader")
lead = party_section(LEADER)
check("names the follower", FOLLOWER in lead, lead.splitlines()[-1][:60] if lead else "")
check("says the leader chooses", "Only you choose" in lead)
check("says setting out takes them along", "they come along" in lead)
check("does not name the leader itself", LEADER not in lead.replace("=== Your party ===", ""))

# [3] follower
print("\n[3] follower")
foll = party_section(FOLLOWER)
check("names the leader", LEADER in foll)
check("says it cannot set out on its own", "cannot set out on your own" in foll)

# [4] leaving
print("\n[4] leaving is always allowed")
check("leader is told", "leave the party" in lead)
check("follower is told", "leave the party" in foll)

# [5] exactly one emitter
print("\n[5] one section, three verbs")
from plugins.party.skill import PartySkill  # noqa: E402

emitted = {}
for verb in ("invite", "join", "leave"):
    skill = PartySkill.__new__(PartySkill)
    skill._verb = verb          # the constructor needs a PluginContext we do
    skill.enabled = True        # not have here; the hook only reads _verb
    emitted[verb] = bool(skill.thought_context_block(LEADER))
check("invite stays silent", emitted["invite"] is False)
check("join stays silent", emitted["join"] is False)
check("leave carries the section", emitted["leave"] is True)
check("exactly one verb emits", sum(emitted.values()) == 1, str(emitted))

# solo character: still nothing, now that a party exists elsewhere
check("an outsider still has no section", party_section(SOLO) == "")

# [6] grammar with one and with two followers
print("\n[6] one follower vs two")
check("singular reads 'travels with you'", f"{FOLLOWER} travels with you" in lead)
assert P.add_to_party(LEADER, SOLO), "setup: the second follower could not join"
lead2 = party_section(LEADER)
check("plural names both", FOLLOWER in lead2 and SOLO in lead2)
check("plural reads 'and ... travel with you'",
      f"{FOLLOWER} and {SOLO} travel with you" in lead2, lead2.splitlines()[-1][:70])

print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
sys.exit(1 if FAILURES else 0)
