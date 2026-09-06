#!/usr/bin/env python3
"""Smoke run for the party ROLE direction — who leads after an invitation.

Background — the bug this pins down: the avatar proposed the trip ("how about
a glass of wine at the inn?"), the NPC agreed — and the NPC's tool LLM answered
that agreement with InviteToParty(target=avatar) instead of JoinParty. The
inviter becomes the leader, so the roles were swapped: the character whose idea
the trip was ended up a follower and lost the compass.

Two fixes, one of them mechanical and checked here: an invitation is recorded
for EVERY target and acts as the DIRECTION RECORD. Whoever asked first leads —
an invitation answered by a counter-invitation is turned into a JOIN. (The
other fix is prompt-side, in the two skill templates; not testable here.)

The record only counts while it is fresh (30 SYSTEM minutes) — an invitation
nobody ever answered must not still decide the roles in a scene hours later.

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_party_roles.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="party-roles-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import party_engine as P  # noqa: E402
from app.models import character as C  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402
from plugins.party.skill import PartySkill  # noqa: E402

FAILURES = []
CHECKED = 0

HOST = "demo"          # proposes the trip
GUEST = "demo_guest"   # agrees to it
LOC = "loc_inn"

_ctx = PluginContext("party")
INVITE = PartySkill({}, _ctx, "invite")
JOIN = PartySkill({}, _ctx, "join")
LEAVE = PartySkill({}, _ctx, "leave")


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def run(skill, agent, payload):
    return skill.execute(json.dumps({"agent_name": agent, **payload}))


def seed() -> None:
    for name in (HOST, GUEST):
        C.save_character_profile(name, {
            "character_name": name,
            "current_location": LOC,
            "current_room": "",
        }, create_new=True)


def reset() -> None:
    """Back to square one: no party, no open invitation."""
    for name in (HOST, GUEST):
        P.leave_party(name)
        P.clear_invites_for(name)


def test_invite_is_recorded() -> None:
    print("\n[1] every invitation is recorded, avatar or NPC")
    reset()
    out = run(INVITE, HOST, {"target": GUEST})
    check("the invite verb reports the invitation", "invites" in out, out)
    rec = P.find_pending_invite(HOST, GUEST)
    check("a pending row exists for the NPC target", rec is not None, str(rec))
    check("the other direction has no record",
          P.find_pending_invite(GUEST, HOST) is None)
    check("no party yet — the invitee still has to agree",
          P.get_party_of(HOST) is None and P.get_party_of(GUEST) is None)


def test_counter_invite_becomes_join() -> None:
    print("\n[2] the counter-invitation becomes a JOIN (the reported bug)")
    reset()
    run(INVITE, HOST, {"target": GUEST})          # HOST proposes the trip
    out = run(INVITE, GUEST, {"target": HOST})    # GUEST answers with an invite
    check("the guest joins instead of inviting back",
          "joins" in out, out)
    check("the one who asked first leads",
          P.party_followers(HOST) == [GUEST],
          f"followers(HOST)={P.party_followers(HOST)} "
          f"followers(GUEST)={P.party_followers(GUEST)}")
    check("the guest is the follower",
          (P.get_party_of(GUEST) or {}).get("role") == "follower")
    check("the open invitation is used up",
          P.find_pending_invite(HOST, GUEST) is None)


def test_join_verb_still_direct() -> None:
    print("\n[3] the plain JoinParty answer is unchanged")
    reset()
    run(INVITE, HOST, {"target": GUEST})
    out = run(JOIN, GUEST, {"leader": HOST})
    check("join makes the inviter the leader",
          P.party_followers(HOST) == [GUEST], out)
    out = run(LEAVE, GUEST, {})
    check("leaving disbands the two-person party",
          P.get_party_of(HOST) is None and P.get_party_of(GUEST) is None, out)


def test_no_record_means_normal_invite() -> None:
    print("\n[4] without an open invitation an invite stays an invite")
    reset()
    out = run(INVITE, GUEST, {"target": HOST})
    check("the guest invites normally", "invites" in out, out)
    check("...and nobody was dragged into a party",
          P.get_party_of(HOST) is None and P.get_party_of(GUEST) is None)
    check("the record points from the guest to the host",
          P.find_pending_invite(GUEST, HOST) is not None)


def test_stale_record_does_not_decide() -> None:
    print("\n[5] a stale invitation no longer decides the direction")
    reset()
    run(INVITE, HOST, {"target": GUEST})
    # Age the row by two hours (SYSTEM time — the window is conversational).
    from app.core.db import transaction
    from app.core.timeutils import utc_now
    from datetime import timedelta
    old = (utc_now() - timedelta(hours=2)).isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute("UPDATE party_invites SET created_at=? WHERE inviter=? AND invitee=?",
                     (old, HOST, GUEST))
    check("the aged row is not found as fresh",
          P.find_pending_invite(HOST, GUEST) is None)
    out = run(INVITE, GUEST, {"target": HOST})
    check("the guest invites normally again", "invites" in out, out)
    check("...and leads nothing yet",
          P.get_party_of(HOST) is None and P.get_party_of(GUEST) is None)


def main() -> int:
    print(f"Storage: {STORAGE}")
    seed()
    test_invite_is_recorded()
    test_counter_invite_becomes_join()
    test_join_verb_still_direct()
    test_no_record_means_normal_invite()
    test_stale_record_does_not_decide()
    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
    sys.exit(rc)
