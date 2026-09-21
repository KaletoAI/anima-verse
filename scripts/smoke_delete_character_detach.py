#!/usr/bin/env python3
"""Smoke run for DELETE-time detachment (DATA-6 / SIM-5 of the 2026-09-20 review).

Usage:
    ./.venv/bin/python scripts/smoke_delete_character_detach.py

Runs against a THROWAWAY storage directory — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.

THE RULE UNDER TEST, derived by hand from the schema and the party rule:

``delete_character`` used to sweep only tables that HAVE a ``character_name``
column, plus four named special cases. Read off ``app/core/world_db_schema.py``,
these four tables reference a character through other columns and were
therefore missed entirely:

    parties             (party_id, leader, members, created_at)
    party_invites       (invite_id, inviter, invitee, created_at, status)
    interaction_invites (invite_id, inviter, invitee, pose_key, …)
    intents             (id, source, owner, participants, …)

The consequence is not cosmetic. ``party_engine.get_party_of`` matches a
name against ``leader``/``members`` purely textually, without asking whether
the name still exists. So a deleted LEADER leaves its ``parties`` row behind,
``is_party_follower(f)`` keeps answering True for both followers, and the
party rule takes the ``SetLocation`` verb away from them (an avatar loses
its compass) — permanently, because the one character that could disband the
party is gone.

Hand-derived expectations after ``delete_character(LEADER)``:

  [1] ``party_engine.get_party_of(F1)`` and ``(F2)`` are None, and
      ``is_party_follower`` is False for both. That is the assertion that
      matters: it is the exact predicate the movement skills gate on
      (``plugins/movement/skill_set_location.py::visible_for``), so it proves
      the followers got their movement back — not merely that a row vanished.
  [2] No ``parties`` row mentions the deleted name at all (leader OR member).
  [3] Every ``party_invites`` row with the deleted name as inviter or invitee
      is gone — both directions, because the index
      ``idx_party_invites_invitee`` keeps serving them to the survivor's UI.
  [4] Same for ``interaction_invites``.
  [5] Every ``intents`` row owned by the deleted character is gone, and a row
      that merely NAMES them in ``participants`` keeps its other participants
      (the row survives, minus the ghost) — the same prune rule
      ``character_reset`` applies. A row whose ONLY participant was the ghost
      is about nobody any more and goes entirely (same rule).
  [6] Rows of the SURVIVORS are untouched: an invitation between two other
      characters and an intent owned by someone else must still be there.
      A sweep that over-deletes is as wrong as one that under-deletes.

  [7] The mirror case: deleting a FOLLOWER. The party survives with the
      leader and the OTHER follower, and the deleted name is out of
      ``members`` — otherwise ``_move_party_followers`` writes a position for
      a ghost on every ticker pass (5 s, forever).

This check fails on the pre-fix code at [1] already: the ``parties`` row
survived the delete untouched.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="deldetach-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="deldetach-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import party_engine  # noqa: E402
from app.core.db import get_connection, transaction  # noqa: E402
from app.core.timeutils import utc_now_iso  # noqa: E402
from app.models import intents as intents_model  # noqa: E402
from app.models.character import (delete_character,  # noqa: E402
                                  save_character_profile)

LEADER = "Leader"
F1 = "Follower1"
F2 = "Follower2"
BYSTANDER = "Bystander"
LOCATION = "tavern"

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def make_character(name):
    """A character standing in LOCATION — enough for the party rule.

    ``current_location`` is a ``character_state`` column that
    ``save_character_profile`` writes from the profile dict, so no world
    location has to exist for ``party_engine.same_location`` to agree.
    """
    save_character_profile(name, {
        "character_name": name,
        "template": "human-default",
        "current_location": LOCATION,
    }, create_new=True)


def party_rows():
    return [(r[0], r[1], json.loads(r[2] or "[]")) for r in
            get_connection().execute(
                "SELECT party_id, leader, members FROM parties").fetchall()]


def invite_rows(table):
    return get_connection().execute(
        f"SELECT invite_id, inviter, invitee FROM {table}").fetchall()


def add_interaction_invite(invite_id, inviter, invitee):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO interaction_invites (invite_id, inviter, invitee, "
            "pose_key, created_at, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (invite_id, inviter, invitee, "hug", utc_now_iso()))


def reset_world():
    with transaction() as conn:
        for t in ("parties", "party_invites", "interaction_invites", "intents",
                  "characters", "character_state"):
            conn.execute(f"DELETE FROM {t}")
    for n in (LEADER, F1, F2, BYSTANDER):
        make_character(n)


def main():
    print("=" * 72)
    print("delete_character detaches party / invites / intents (DATA-6, SIM-5)")
    print("=" * 72)

    # ---------------------------------------------------------------- setup
    reset_world()
    assert party_engine.add_to_party(LEADER, F1), "party setup failed"
    assert party_engine.add_to_party(LEADER, F2), "party setup failed"
    check("setup: both followers are in the leader's party",
          party_engine.is_party_follower(F1) and party_engine.is_party_follower(F2))

    party_engine.create_pending_invite(LEADER, BYSTANDER)   # goes with LEADER
    party_engine.create_pending_invite(BYSTANDER, LEADER)   # goes with LEADER
    party_engine.create_pending_invite(F1, BYSTANDER)       # must SURVIVE
    add_interaction_invite("ii_a", LEADER, BYSTANDER)       # goes
    add_interaction_invite("ii_b", BYSTANDER, LEADER)       # goes
    add_interaction_invite("ii_c", F1, BYSTANDER)           # must SURVIVE

    own = intents_model.create_intent(owner=LEADER, title="own intent")
    shared = intents_model.create_intent(owner=BYSTANDER, title="shared intent",
                                         participants={"partner": LEADER,
                                                       "other": F2})
    lone = intents_model.create_intent(owner=BYSTANDER, title="lone intent",
                                       participants={"partner": LEADER})
    foreign = intents_model.create_intent(owner=BYSTANDER, title="foreign intent")

    # ------------------------------------------------------- delete the leader
    print("\n-- deleting the party LEADER --")
    ok = delete_character(LEADER)
    check("delete_character returned True", ok is True)

    # [1] the assertion that matters: the followers can move again
    check("[1] F1 is no longer a party follower",
          party_engine.get_party_of(F1) is None
          and not party_engine.is_party_follower(F1),
          repr(party_engine.get_party_of(F1)))
    check("[1] F2 is no longer a party follower",
          party_engine.get_party_of(F2) is None
          and not party_engine.is_party_follower(F2),
          repr(party_engine.get_party_of(F2)))

    # [2] no parties row mentions the deleted name
    rows = party_rows()
    check("[2] no parties row names the deleted leader",
          all(r[1] != LEADER and LEADER not in r[2] for r in rows), repr(rows))

    # [3]/[4] invitations in BOTH directions are gone, the survivors' stay
    pinv = invite_rows("party_invites")
    check("[3] no party_invites row names the deleted character",
          all(LEADER not in (r[1], r[2]) for r in pinv), repr(pinv))
    check("[6] the bystander/F1 party invitation survived",
          any({r[1], r[2]} == {F1, BYSTANDER} for r in pinv), repr(pinv))

    iinv = invite_rows("interaction_invites")
    check("[4] no interaction_invites row names the deleted character",
          all(LEADER not in (r[1], r[2]) for r in iinv), repr(iinv))
    check("[6] the bystander/F1 interaction invitation survived",
          any(r[0] == "ii_c" for r in iinv), repr(iinv))

    # [5] intents
    check("[5] the intent OWNED by the deleted character is gone",
          intents_model.get_intent(own["id"]) is None)
    survived = intents_model.get_intent(shared["id"])
    check("[5] the intent that only NAMES them survived without the ghost",
          survived is not None
          and LEADER not in [str(v) for v in (survived.get("participants") or {}).values()],
          repr(survived and survived.get("participants")))
    check("[5] an intent whose ONLY participant was the ghost is gone",
          intents_model.get_intent(lone["id"]) is None)
    check("[6] a foreign intent is untouched",
          intents_model.get_intent(foreign["id"]) is not None)

    # ------------------------------------------------------ delete a follower
    print("\n-- deleting a party FOLLOWER --")
    reset_world()
    assert party_engine.add_to_party(LEADER, F1)
    assert party_engine.add_to_party(LEADER, F2)
    delete_character(F1)
    p = party_engine.get_party_of(LEADER)
    check("[7] the party survives the follower's deletion",
          p is not None and p["role"] == "leader", repr(p))
    check("[7] the deleted follower is out of members",
          p is not None and F1 not in p["members"] and F2 in p["members"],
          repr(p and p["members"]))

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAIL — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("PASS — all checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
