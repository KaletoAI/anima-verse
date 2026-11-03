#!/usr/bin/env python3
"""A furniture action for three: everyone asked must agree, one "no" ends it
naming who said it, the clip roles follow ``role_gender``, every member
claims a person and a slot, and all three profiles start the same
interaction. Plus the one-shot move of an old ``partner`` row.

Usage: ./.venv/bin/python scripts/smoke_prop_action_group.py

Real temporary world — the fixtures of ``smoke_prop_action_runs.py``
(``authored_pair``: A at (1,5), B at (2,5); here C at (3,5)). The pair
action becomes "trio": three participants, pose "run-trio" (places 3), clip
roles a/b/c with anchors -0.6 / 0 / +0.6 m — exactly the three slots of a
capacity-3 marker with 0.6 m spacing, so role a holds slot 0, b slot 1,
c slot 2. Hand-derived from ``prop_action_engine`` / ``interaction_engine``:

  [1] A asks [B, C]: "awaiting_consent", no claims; B and C each see one
      incoming row with can_respond and consents {B: pending, C: pending};
      A's outgoing row has members [B, C].
  [2] B says yes: still "awaiting_consent", consents {B: yes, C: pending},
      no claims; B's row can no longer respond. B answering again changes
      nothing.
  [3] C says yes: "approaching"; 6 claims (3 persons + 3 slots); plans keyed
      A, B, C with slots 0 / 1 / 2; clip roles {a: A, b: B, c: C} (no
      role_gender: invitation order); access roles A "actor", B and C
      "partner".
  [4] 30 + 2 + 2 game seconds: "active"; all three profiles carry the same
      interaction id and execution_ref; one "prop_action.group_started"
      with members [A, B, C]. A stops it: no profile keeps an interaction,
      one "interaction.ended" with members [A, B, C] (clip-role order).
  [5] A asks again (after the run ended), B says yes, C says no:
      "cancelled" / "consent_declined", declined_by C, no claims.
  [6] role_gender {a: male, b: female, c: female}; A female, B male,
      C female: B takes a (the only male role), A the first free female role
      b, C the next, c -> {a: B, b: A, c: C} once everyone agreed.
  [7] All three female for that clip: A takes b, B takes c, C finds no free
      female role -> the request is refused "roles_unfit".
  [8] A wrong number of invitees (only B for a trio) -> "invalid_partner";
      "react" with two invitees -> "invalid_consent"; an invitee named
      twice -> "invalid_partner".
  [9] Migration: a table with the old ``partner`` column, one open pair
      invitation (A -> B, plans/access keyed actor/partner) and one solo
      row: members [B] / [], plans and access re-keyed to A / B, consents
      {B: pending} on the open one only; the column is gone; a second run
      moves nothing (0).
"""
import json
import sqlite3
import sys
import unittest

import smoke_prop_action_runs as S
from smoke_prop_action_runs import A, F, R, tick
from smoke_prop_action_runs import clips, pose_catalog
from app.core import hooks


def authored_trio(genders=None, role_gender=None):
    name, partner, target, pid = S.authored_pair()
    third = F.actor(target["location_id"], at=(3, 5))
    entries = pose_catalog.world_entries("pose")
    entries["run-trio"] = dict(participants=3, animation="run-trio", group="seat", places=3,
                               yaw_offset=90, prompt="Three people sharing a seat")
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()
    directory = F.ROOT / "clips"
    for role in ("a", "b", "c"):
        (directory / f"run-trio__{role}.fbx").write_bytes(b"private group fixture")
    meta = dict(kind="run-trio", pair=True, duration_s=2, loop=True, roles=["a", "b", "c"],
                geometry=dict(roles=dict(a=dict(anchor_xz_m=[-.6, 0]), b=dict(anchor_xz_m=[0, 0]),
                                         c=dict(anchor_xz_m=[.6, 0]))))
    if role_gender:
        meta["role_gender"] = role_gender
    (directory / "run-trio.json").write_text(json.dumps(meta))
    clips._clear_entries_cache()
    doc = F.props.read_sidecar(pid)
    doc["actions"][0].update(participants=3, pose_key="run-trio")
    marker = doc["model_variants"][0]["markers"][0]
    marker.update(capacity=3, spacing_m=.6)
    marker.pop("access", None)
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]
    S.measured_entry("run-trio")
    people = [name, partner, third]
    for who, gender in zip(people, genders or ()):
        profile = F.C.get_character_profile(who)
        profile["gender"] = gender
        F.C.save_character_profile(who, profile)
    return people, target


def row(who, eid):
    state = A.state_for(who)
    return next((r for kind in ("incoming", "outgoing", "current", "recent_results")
                 for r in state[kind] if r["execution_id"] == eid), None)


class Group(unittest.TestCase):
    def tearDown(self):
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def test_1_to_5_everyone_agrees_or_one_says_no(self):
        started = []
        ended = []
        hooks.register("prop_action.group_started", lambda **kw: started.append(kw), tag="smoke.group")
        self.addCleanup(hooks._hooks.pop, ("prop_action.group_started", "smoke.group"), None)
        hooks.register("interaction.ended", lambda **kw: ended.append(kw), tag="smoke.group_end")
        self.addCleanup(hooks._hooks.pop, ("interaction.ended", "smoke.group_end"), None)
        (a, b, c), target = authored_trio()

        print("[1] one question to two people")
        asked = S.request(a, target, members=[b, c])
        eid = asked["execution_id"]
        self.assertEqual(asked["status"], "awaiting_consent", asked)
        self.assertFalse(R.claims())
        for who in (b, c):
            mine = row(who, eid)
            self.assertTrue(mine["can_respond"], who)
            self.assertEqual(mine["consents"], {b: "pending", c: "pending"})
        self.assertEqual(row(a, eid)["members"], [b, c])

        print("[2] one yes is not enough")
        self.assertEqual(A.respond(b, eid, True)["status"], "awaiting_consent")
        self.assertEqual(R.get(eid)["data"]["consents"], {b: "yes", c: "pending"})
        self.assertFalse(R.claims())
        self.assertFalse(row(b, eid)["can_respond"])
        self.assertEqual(A.respond(b, eid, True)["status"], "awaiting_consent")
        self.assertEqual(R.get(eid)["data"]["consents"], {b: "yes", c: "pending"})

        print("[3] the last yes plans and claims for all three")
        result = A.respond(c, eid, True)
        self.assertEqual(result["status"], "approaching", result)
        self.assertEqual(len(R.claims(eid)), 6)
        run = R.get(eid)
        self.assertEqual({who: plan["entry_anchor"]["slot"] for who, plan in run["data"]["plans"].items()},
                         {a: 0, b: 1, c: 2})
        self.assertEqual(run["data"]["clip_roles"], {"a": a, "b": b, "c": c})
        self.assertEqual(run["data"]["access_roles"], {a: "actor", b: "partner", c: "partner"})

        print("[4] all three start one interaction")
        S.tick(30)
        tick(2)
        tick(2)
        self.assertEqual(R.get(eid)["status"], "active", R.get(eid))
        interactions = [F.C.get_character_profile(who)["interaction"] for who in (a, b, c)]
        self.assertEqual({i["id"] for i in interactions}, {interactions[0]["id"]})
        self.assertEqual({i["execution_ref"] for i in interactions}, {eid})
        self.assertEqual([(kw["execution_id"], kw["members"]) for kw in started], [(eid, [a, b, c])])
        A.cancel(a, eid)
        self.assertFalse([who for who in (a, b, c) if F.C.get_character_profile(who).get("interaction")])
        self.assertEqual([kw["members"] for kw in ended], [[a, b, c]])

        print("[5] one no ends it and says who")
        again = S.request(a, target, members=[b, c])["execution_id"]
        A.respond(b, again, True)
        A.respond(c, again, False)
        run = R.get(again)
        self.assertEqual((run["status"], run["reason"], run["data"]["declined_by"]),
                         ("cancelled", "consent_declined", c))
        self.assertFalse(R.claims(again))

    def test_6_roles_follow_the_clip_gender(self):
        (a, b, c), target = authored_trio(("female", "male", "female"),
                                          dict(a="male", b="female", c="female"))
        print("[6] the man takes the male role, the women the others in order")
        eid = S.request(a, target, members=[b, c])["execution_id"]
        A.respond(b, eid, True)
        self.assertEqual(A.respond(c, eid, True)["status"], "approaching")
        self.assertEqual(R.get(eid)["data"]["clip_roles"], {"a": b, "b": a, "c": c})

    def test_7_no_role_left(self):
        (a, b, c), target = authored_trio(("female", "female", "female"),
                                          dict(a="male", b="female", c="female"))
        print("[7] three women for two female roles")
        answer = S.request(a, target, members=[b, c])
        self.assertEqual((answer["status"], answer["reason"]), ("refused", "roles_unfit"), answer)

    def test_8_invalid_member_lists(self):
        (a, b, c), target = authored_trio()
        print("[8] the request names the right people")
        self.assertEqual(S.request(a, target, members=[b])["reason"], "invalid_partner")
        self.assertEqual(S.request(a, target, members=[b, c], consent="react")["reason"], "invalid_consent")
        self.assertEqual(S.request(a, target, members=[b, b])["reason"], "invalid_partner")


def test_9_migration():
    print("[9] an old partner row moves to members")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE prop_action_runs (execution_id TEXT PRIMARY KEY, actor TEXT, "
                 "partner TEXT NOT NULL DEFAULT '', status TEXT, data TEXT)")
    pair = dict(plans=dict(actor=dict(x=1), partner=dict(x=2)), access_roles=dict(actor="actor", partner="partner"))
    conn.execute("INSERT INTO prop_action_runs VALUES ('p', 'Ann', 'Ben', 'awaiting_consent', ?)", (json.dumps(pair),))
    conn.execute("INSERT INTO prop_action_runs VALUES ('s', 'Ann', '', 'active', ?)",
                 (json.dumps(dict(plans=dict(actor=dict(x=3)), access_roles=dict(actor="actor"))),))
    assert R.migrate_members(conn) == 2
    cols = {r[1] for r in conn.execute("PRAGMA table_info(prop_action_runs)")}
    assert "partner" not in cols and "members" in cols, cols
    rows = {r[0]: (json.loads(r[1]), json.loads(r[2]))
            for r in conn.execute("SELECT execution_id, members, data FROM prop_action_runs")}
    assert rows["p"] == (["Ben"], dict(plans=dict(Ann=dict(x=1), Ben=dict(x=2)),
                                       access_roles=dict(Ann="actor", Ben="partner"),
                                       consents=dict(Ben="pending"))), rows["p"]
    assert rows["s"] == ([], dict(plans=dict(Ann=dict(x=3)), access_roles=dict(Ann="actor"))), rows["s"]
    assert R.migrate_members(conn) == 0


if __name__ == "__main__":
    test_9_migration()
    unittest.main(argv=[sys.argv[0], *F.REST])
