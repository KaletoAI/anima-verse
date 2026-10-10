#!/usr/bin/env python3
"""Smoke run for party presence gates and structured alone_here context.

Background — the bug this pins down: an NPC alone at Mondscheinsee invited the
avatar (who was at Kaxai Tower) into its travel party. Two independent holes
lined up:

  A  PartySkill._invite / _join / resolve_pending_invite never compared
     locations, although the tool description promises "present at your current
     location". TalkTo enforced it, the party verbs did not.
  B  Both prompt paths DROPPED the presence section when nobody was around, so
     the prompt said nothing at all about who is there. A missing section is not
     evidence of absence for an LLM — combined with a stale pose ("standing in
     front of the avatar") it kept playing a scene with an absent person.

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_party_presence.py
"""
import shutil
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="party-presence-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")

from app.core import db  # noqa: E402

db.init_schema()
from app.core.dependencies import get_skill_manager
get_skill_manager()

from app.core import party_engine as P  # noqa: E402
from app.models import character as C  # noqa: E402

FAILURES = []
CHECKED = 0

LEADER = "demo"          # stands at loc_lake
GUEST = "demo_guest"     # stands at loc_lake too
FARAWAY = "demo_far"     # stands at loc_tower — the whole point
LOC_LAKE = "loc_lake"
LOC_TOWER = "loc_tower"


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def seed() -> None:
    """Three characters, two locations. Written straight through the profile
    store so no world content (locations, rooms, rules) is needed."""
    for name, loc in ((LEADER, LOC_LAKE), (GUEST, LOC_LAKE), (FARAWAY, LOC_TOWER)):
        C.save_character_profile(name, {
            "character_name": name,
            "current_location": loc,
            "current_room": "",
        }, create_new=True)


# ---------------------------------------------------------------------------
# A — the location brake
# ---------------------------------------------------------------------------

def test_same_location() -> None:
    print("\n[1] same_location")
    check("two characters at the same place are together",
          P.same_location(LEADER, GUEST) is True)
    check("across locations they are not",
          P.same_location(LEADER, FARAWAY) is False)
    check("an unknown character counts as not together",
          P.same_location(LEADER, "demo_ghost") is False)
    check("an empty name counts as not together",
          P.same_location(LEADER, "") is False)


def test_add_to_party() -> None:
    print("\n[2] add_to_party — the central brake")
    check("cross-location join is refused",
          P.add_to_party(LEADER, FARAWAY) is None)
    check("...and no party was created",
          P.get_party_of(LEADER) is None and P.get_party_of(FARAWAY) is None)
    pid = P.add_to_party(LEADER, GUEST)
    check("same-location join works", bool(pid), str(pid))
    check("the guest is a follower now",
          (P.get_party_of(GUEST) or {}).get("role") == "follower")
    # And the brake still holds for a party that already exists.
    check("adding an absent member to an existing party is refused",
          P.add_to_party(LEADER, FARAWAY) is None)
    check("the party is unchanged", P.party_followers(LEADER) == [GUEST])
    P.leave_party(GUEST)
    check("cleanup: nobody is in a party",
          P.get_party_of(LEADER) is None and P.get_party_of(GUEST) is None)


def test_skill_verbs() -> None:
    print("\n[3] PartySkill verbs")
    from app.plugins.context import PluginContext
    from plugins.party.skill import PartySkill  # type: ignore

    ctx = PluginContext("party")
    invite = PartySkill({}, ctx, "invite")
    join = PartySkill({}, ctx, "join")

    def run(skill, agent, payload):
        import json
        return skill.execute(json.dumps({"agent_name": agent, **payload}))

    out = run(invite, LEADER, {"target": FARAWAY})
    check("...and left no pending invite",
          P.get_pending_invites_for(FARAWAY) == [])

    out = run(invite, LEADER, {"target": GUEST})
    pending = P.find_pending_invite(LEADER, GUEST)

    out = run(join, FARAWAY, {"leader": LEADER})
    check("...and created no party", P.get_party_of(FARAWAY) is None)

    out = run(join, GUEST, {"leader": LEADER, "invite_id": (pending or {}).get("invite_id", "missing")})
    check("join at the same location works",
          P.party_followers(LEADER) == [GUEST], out)
    P.leave_party(GUEST)


def test_pending_invites() -> None:
    print("\n[4] pending invites (the avatar path)")
    # Invite while together, then the inviter walks off — the accept must fail
    # and the dead row must not reach the UI.
    inv = P.create_pending_invite(LEADER, GUEST)
    check("a pending invite is created", bool(inv))
    check("it is offered while both are here",
          [i["invite_id"] for i in P.get_pending_invites_for(GUEST)] == [inv])

    C.save_character_profile(GUEST, {"character_name": GUEST,
                                     "current_location": LOC_TOWER,
                                     "current_room": ""})
    check("the guest really moved",
          C.get_character_current_location(GUEST) == LOC_TOWER)
    check("the stale invite is no longer offered to the UI",
          P.get_pending_invites_for(GUEST) == [])
    res = P.resolve_pending_invite(inv, True)
    check("accepting it reports not_present",
          res.get("status") == "not_present", str(res))
    check("...and created no party", P.get_party_of(GUEST) is None)

    # Declining a stale invite must still work — it is just a dismissal.
    inv2 = P.create_pending_invite(LEADER, GUEST)
    res = P.resolve_pending_invite(inv2, False)
    check("declining a stale invite still resolves",
          res.get("status") == "declined", str(res))

    C.save_character_profile(GUEST, {"character_name": GUEST,
                                     "current_location": LOC_LAKE,
                                     "current_room": ""})
    inv3 = P.create_pending_invite(LEADER, GUEST)
    res = P.resolve_pending_invite(inv3, True)
    check("accepting while present joins the party",
          res.get("status") == "accepted", str(res))
    check("the guest is a follower", P.party_followers(LEADER) == [GUEST])
    P.leave_party(GUEST)


# ---------------------------------------------------------------------------
# B — absence and unknown placement have distinct structured context flags.
# ---------------------------------------------------------------------------

def test_presence_context() -> None:
    print("\n[5] thought context — alone_here")
    from app.core.thought_context import _build_presence

    # _build_presence splits by ROOM: (same room, other rooms, alone_known).
    # The characters here carry no room, so everything lands in the room block.
    _, _, alone = _build_presence(FARAWAY, LOC_TOWER, "")
    check("alone at a known location -> alone_here True", alone is True)

    _, _, alone = _build_presence(LEADER, "", "")
    check("unknown location -> NOT reported as alone", alone is False)

    _, _, alone = _build_presence(LEADER, LOC_LAKE, "")
    check("someone else here -> alone_here False", alone is False)






def main() -> int:
    try:
        seed()
        test_same_location()
        test_add_to_party()
        test_skill_verbs()
        test_pending_invites()
        test_presence_context()
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
