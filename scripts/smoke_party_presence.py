#!/usr/bin/env python3
"""Smoke run for the party presence brake (A) and the "you are alone" prompt
line (B).

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
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="party-presence-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

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
    check("invite across locations is refused",
          "not at your location" in out, out)
    check("...and left no pending invite",
          P.get_pending_invites_for(FARAWAY) == [])

    out = run(invite, LEADER, {"target": GUEST})
    check("invite to someone present is accepted",
          "not at your location" not in out, out)

    out = run(join, FARAWAY, {"leader": LEADER})
    check("join across locations is refused",
          "not at your location" in out, out)
    check("...and created no party", P.get_party_of(FARAWAY) is None)

    out = run(join, GUEST, {"leader": LEADER})
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
# B — the prompt must SAY "alone", not stay silent
# ---------------------------------------------------------------------------

def test_presence_context() -> None:
    print("\n[5] thought context — alone_here")
    from app.core.thought_context import _build_presence

    block, alone = _build_presence(FARAWAY, LOC_TOWER)
    check("alone at a known location -> alone_here True",
          block == "" and alone is True, f"block={block!r} alone={alone}")

    block, alone = _build_presence(LEADER, "")
    check("unknown location -> NOT reported as alone",
          block == "" and alone is False, f"block={block!r} alone={alone}")

    block, alone = _build_presence(LEADER, LOC_LAKE)
    check("someone else here -> block filled, alone_here False",
          bool(block) and alone is False, f"alone={alone} block={block!r}")


def test_thought_template() -> None:
    print("\n[6] agent_thought template renders the alone line")
    from app.core.prompt_templates import render

    base = {
        "character_name": LEADER, "personality": "", "location_name": "Lake",
        "activity": "standing in front of demo_far", "feeling": "calm",
        "time_of_day": "17:21", "has_assignments": False,
        "action_instruction": "Decide what to do.",
    }
    optional = ("effects_block", "state_flags_block", "outfit_self_block",
                "inbox_block", "events_block", "assignments_block",
                "general_task", "commitments_block", "outfit_decision_block",
                "skill_context_blocks", "inventory_block", "room_items_block",
                "activity_hint_block", "daily_schedule_block", "tracker_block",
                "recent_thoughts", "arc_block", "retrospective_block",
                "tools_hint", "lang_instruction", "outfit_avatar_block",
                "recent_chat_block")
    base.update({k: "" for k in optional})

    alone = render("chat/agent_thought.md",
                   **{**base, "present_people_block": "", "alone_here": True})
    check("alone -> the prompt says ALONE", "ALONE" in alone)

    unknown = render("chat/agent_thought.md",
                     **{**base, "present_people_block": "", "alone_here": False})
    check("unknown -> the prompt claims nothing", "ALONE" not in unknown)

    withppl = render("chat/agent_thought.md",
                     **{**base, "present_people_block": "- demo_guest",
                        "alone_here": False})
    check("someone present -> people listed, no alone claim",
          "demo_guest" in withppl and "ALONE" not in withppl)

    in_chat = render("chat/agent_thought_in_chat.md",
                     **{**base, "present_people_block": "", "alone_here": True})
    check("the in-chat variant states it too", "ALONE" in in_chat)


def test_presence_block_formatter() -> None:
    print("\n[7] rp_first tool prompt — nearby_hint")
    from app.core.system_prompt_builder import (_format_presence_block,
                                                load_prompt_data, PRESENCE)

    empty = _format_presence_block("Lake", [], False)
    check("the empty case is spelled out, not omitted",
          "nobody" in empty and "ALONE" in empty, empty.replace("\n", " | "))

    data = load_prompt_data(FARAWAY, {PRESENCE})
    hint = data.get("nearby_hint", "")
    check("a lone character still gets a nearby_hint",
          bool(hint), hint.replace("\n", " | "))
    check("...and it states the absence",
          "ALONE" in hint, hint.replace("\n", " | "))


def main() -> int:
    try:
        seed()
        test_same_location()
        test_add_to_party()
        test_skill_verbs()
        test_pending_invites()
        test_presence_context()
        test_thought_template()
        test_presence_block_formatter()
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
