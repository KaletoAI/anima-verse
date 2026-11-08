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
  [8] A wrong number of invitees (only B for a trio: two people, fewer
      than a group's three) -> "invalid_partner";
      "react" with two invitees -> "invalid_consent"; an invitee named
      twice -> "invalid_partner".
  [10] The OFFER of the trio (G4) to A, with B and C awake in the room:
      one row, participants 3, required_partner, candidates [B, C] (the
      people A can pick), enabled, no per-partner targets. It is not in the
      LLM's requestable list and a named request for it answers
      "no_such_offer" (only the player starts a group). The preflight of the
      exact choice [B, C] is enabled; [B] alone "invalid_partner"; the player
      route ``POST /play/prop-actions/check`` answers the same. C asleep:
      candidates [B], the row disabled "partners_missing".
  [11] ALT halves (G6): the trio's clip has ``run-trio__c~wave`` on disk and
      lists ``alts {b: [gone], c: [wave]}`` with ``geometry.alts["c~wave"]
      anchor_xz_m [0.6, -0.5]`` (role c itself sits at [0.6, 0]); its finale
      ``run-trio-climax`` has the three roles plus ``__c~wave``. Once active:
      C's row offers ``{current "", options ["" Default, "wave" Wave]}``; A
      (role a, none) and B ("gone" has no file) get null. The library lists
      the alt apart: role_counts run-trio 3, clip_entries holds no alt,
      alt_entries holds exactly ``(run-trio, c, wave)``. C picks "wave": ok,
      the profile and the worldmap block say alt "wave", and C's position
      moves by R(yaw)·(0, -0.5) — 0.5 m from where it was, and
      sqrt(0.6² + 0.5²) = 0.781 m from the anchor, whatever the yaw. C's
      finale then closes in the alt (finale block alt "wave"), B's in its
      own half (alt ""). "nope" and B's "gone" are "unknown_alt", someone
      outside the run "not_participant"; "" puts C back on [0.6, 0] — 0.6 m
      from the anchor, 0 m from where it started.
  [12] FEWER PEOPLE THAN ROLES (2026-11-08): a group action runs with 3
      people up to its ``participants`` (= the clip's role count). The fixture
      grows to five roles "run-five" (anchors -1.2 / -0.6 / 0 / 0.6 / 1.2 m =
      slots 0..4 of a capacity-5 marker), role_gender {a female, b female,
      c male, d female, e male}; A female, B male, C male. A asks [B, C]:
      A takes the first free female role a, B the first male role c, C the
      next male role e -> clip roles {a: A, c: B, e: C}, b and d stay EMPTY
      and are not in the result. Once both agreed: "approaching", 6 claims
      (3 persons + 3 slots — none for the empty roles), slots A 0, B 2, C 4,
      access A "actor" (role a), B and C "partner". Active: every profile's
      interaction has members {a: A, c: B, e: C} and its own role a / c / e;
      the state row's roles.clip says the same; "group_started" names
      [A, B, C]. The pose's finale "run-five-climax" has all five roles
      (finale_kind compares the POSE's participants 5 with the clip's 5
      roles, not the head count): B's finale plays role c, C's role e.
  [13] Head counts: on the five, A + [B] (two people, a pair's count) is
      "invalid_partner" for request and check alike; on the trio with a
      fourth person D in the room, A + [B, C, D] (four people, one more than
      its three roles) is "invalid_partner" too. group_roles itself: four
      names for three roles "roles_unfit"; three names for five roles
      without role_gender take a, b, c in invitation order.
  [14] The offer of the five with only B and C awake beside A: two
      candidates are enough -> enabled, candidates [B, C], participants 5,
      and the preflight [B, C] is enabled; C asleep -> candidates [B],
      "partners_missing".
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
from unittest.mock import patch

import smoke_prop_action_runs as S
from smoke_prop_action_runs import A, F, R, tick
from smoke_prop_action_runs import clips, pose_catalog
# Use the shared fixture's private world for the direct app imports below.
F.paths.init(F.ROOT / "world")
from app.core import hooks                                              # noqa: E402


def authored_trio(genders=None, role_gender=None, *, roles=3, people=3, kind="run-trio"):
    """The group fixture: ``roles`` clip roles (anchors 0.6 m apart around the
    centre, one slot each on a capacity-``roles`` marker), ``people``
    characters in the room at x = 1, 2, 3, … on z = 5."""
    name, partner, target, pid = S.authored_pair()
    others = [F.actor(target["location_id"], at=(3 + i, 5)) for i in range(people - 2)]
    entries = pose_catalog.world_entries("pose")
    entries[kind] = dict(participants=roles, animation=kind, group="seat", places=roles,
                         yaw_offset=90, prompt="People sharing a seat")
    pose_catalog.replace_world_entries("pose", entries)
    pose_catalog.reload_catalogs()
    directory = F.ROOT / "clips"
    names = "abcde"[:roles]
    for role in names:
        (directory / f"{kind}__{role}.fbx").write_bytes(b"private group fixture")
    meta = dict(kind=kind, pair=True, duration_s=2, loop=True, roles=list(names),
                geometry=dict(roles={role: dict(anchor_xz_m=[round(.6 * (i - (roles - 1) / 2), 3), 0])
                                     for i, role in enumerate(names)}))
    if role_gender:
        meta["role_gender"] = role_gender
    (directory / f"{kind}.json").write_text(json.dumps(meta))
    clips._clear_entries_cache()
    doc = F.props.read_sidecar(pid)
    doc["actions"][0].update(participants=roles, pose_key=kind)
    marker = doc["model_variants"][0]["markers"][0]
    marker.update(capacity=roles, spacing_m=.6)
    marker.pop("access", None)
    F.props._write_sidecar(pid, doc)
    target["definition_revision"] = F.props.get_prop(pid)["revision"]
    S.measured_entry(kind)
    people = [name, partner, *others]
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

    def test_10_the_group_offer(self):
        (a, b, c), target = authored_trio()
        from app.core import prop_actions as P
        from app.routes import prop_actions as routes
        print("[10] the trio is offered with its candidates, to the player only")
        rows = [o for o in P.offers(a) if o["action_id"] == target["action_id"]]
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual((row["participants"], row["required_partner"], row["candidates"], row["enabled"],
                          row["available_targets"]), (3, True, [b, c], True, []), row)
        self.assertFalse([o for o in P._requestable(a) if o["label"] == row["label"]])
        self.assertEqual(P._named_request(a, dict(furniture=row["prop_label"], action=row["label"],
                                                  partner=b))["reason"], "no_such_offer")
        exact = {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}
        self.assertEqual(A.check(a, exact, target["action_id"], target["definition_revision"], [b, c],
                                 offer=True), dict(enabled=True, reason=""))
        self.assertEqual(A.check(a, exact, target["action_id"], target["definition_revision"], [b],
                                 offer=True)["reason"], "invalid_partner")
        body = routes.CheckRequest(target=exact, action_id=target["action_id"],
                                   revision=target["definition_revision"], members=[b, c])
        with patch.object(routes, "_avatar", return_value=a):
            self.assertEqual(routes.check(body, user={}), dict(enabled=True, reason=""))
        profile = F.C.get_character_profile(c)
        profile["is_sleeping"] = True
        F.C.save_character_profile(c, profile)
        row = next(o for o in P.offers(a) if o["action_id"] == target["action_id"])
        self.assertEqual((row["candidates"], row["enabled"], row["reason"]), ([b], False, "partners_missing"))


FIVE_GENDER = dict(a="female", b="female", c="male", d="female", e="male")


class Smaller(unittest.TestCase):
    def tearDown(self):
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def test_12_three_people_on_five_roles(self):
        started = []
        hooks.register("prop_action.group_started", lambda **kw: started.append(kw), tag="smoke.smaller")
        self.addCleanup(hooks._hooks.pop, ("prop_action.group_started", "smoke.smaller"), None)
        (a, b, c), target = authored_trio(("female", "male", "male"), FIVE_GENDER, roles=5, kind="run-five")
        directory = F.ROOT / "clips"
        for role in "abcde":
            (directory / f"run-five-climax__{role}.fbx").write_bytes(b"private finale fixture")
        (directory / "run-five-climax.json").write_text(json.dumps(dict(
            kind="run-five-climax", pair=True, duration_s=1, roles=list("abcde"))))
        clips._clear_entries_cache()
        entries = pose_catalog.world_entries("pose")
        entries["run-five"]["finale_animation"] = "run-five-climax"
        pose_catalog.replace_world_entries("pose", entries)
        pose_catalog.reload_catalogs()

        print("[12] three people on a five-role clip: two roles stay empty")
        eid = S.request(a, target, members=[b, c])["execution_id"]
        self.assertEqual(R.get(eid)["status"], "awaiting_consent")
        A.respond(b, eid, True)
        result = A.respond(c, eid, True)
        self.assertEqual(result["status"], "approaching", result)
        run = R.get(eid)
        self.assertEqual(run["data"]["clip_roles"], {"a": a, "c": b, "e": c})
        self.assertEqual(len(R.claims(eid)), 6)
        self.assertEqual({who: plan["entry_anchor"]["slot"] for who, plan in run["data"]["plans"].items()},
                         {a: 0, b: 2, c: 4})
        self.assertEqual(run["data"]["access_roles"], {a: "actor", b: "partner", c: "partner"})
        S.tick(30)
        tick(2)
        tick(2)
        self.assertEqual(R.get(eid)["status"], "active", R.get(eid))
        for who, role in ((a, "a"), (b, "c"), (c, "e")):
            inter = F.C.get_character_profile(who)["interaction"]
            self.assertEqual((inter["members"], inter["role"]), ({"a": a, "c": b, "e": c}, role), who)
        self.assertEqual(row(a, eid)["roles"]["clip"], {"a": a, "c": b, "e": c})
        self.assertEqual([kw["members"] for kw in started], [[a, b, c]])
        self.assertEqual(A.begin_finale(eid, b), {"ok": True, "reason": ""})
        self.assertEqual(A.finale_for(b)["role"], "c")
        self.assertEqual(A.begin_finale(eid, c), {"ok": True, "reason": ""})
        self.assertEqual(A.finale_for(c)["role"], "e")

    def test_13_head_counts(self):
        from app.core import interaction_engine as I
        (a, b, c), target = authored_trio(("female", "male", "male"), FIVE_GENDER, roles=5, kind="run-five")
        exact = {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}
        print("[13] at least three people, at most one per role")
        self.assertEqual(S.request(a, target, members=[b])["reason"], "invalid_partner")
        self.assertEqual(A.check(a, exact, target["action_id"], target["definition_revision"], [b],
                                 offer=True)["reason"], "invalid_partner")
        (a, b, c, d), target = authored_trio(people=4)
        exact = {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}
        self.assertEqual(S.request(a, target, members=[b, c, d])["reason"], "invalid_partner")
        self.assertEqual(A.check(a, exact, target["action_id"], target["definition_revision"], [b, c, d],
                                 offer=True)["reason"], "invalid_partner")
        three = dict(roles=["a", "b", "c"])
        with self.assertRaisesRegex(ValueError, "roles_unfit"):
            I.group_roles(["P", "Q", "R", "S"], {}, three)
        self.assertEqual(I.group_roles(["P", "Q", "R"], {}, dict(roles=list("abcde"))),
                         {"a": "P", "b": "Q", "c": "R"})

    def test_14_two_candidates_are_enough(self):
        (a, b, c), target = authored_trio(roles=5, kind="run-five")
        from app.core import prop_actions as P
        print("[14] the five is offered with two candidates")
        offer = next(o for o in P.offers(a) if o["action_id"] == target["action_id"])
        self.assertEqual((offer["participants"], offer["candidates"], offer["enabled"], offer["reason"]),
                         (5, [b, c], True, ""), offer)
        exact = {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}
        self.assertEqual(A.check(a, exact, target["action_id"], target["definition_revision"], [b, c],
                                 offer=True), dict(enabled=True, reason=""))
        profile = F.C.get_character_profile(c)
        profile["is_sleeping"] = True
        F.C.save_character_profile(c, profile)
        offer = next(o for o in P.offers(a) if o["action_id"] == target["action_id"])
        self.assertEqual((offer["candidates"], offer["enabled"], offer["reason"]), ([b], False, "partners_missing"))


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


class Alts(unittest.TestCase):
    def tearDown(self):
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def test_11_alt_halves(self):
        import math
        from app.core import interaction_engine as I
        (a, b, c), target = authored_trio()
        directory = F.ROOT / "clips"
        (directory / "run-trio__c~wave.fbx").write_bytes(b"private alt fixture")
        meta = json.loads((directory / "run-trio.json").read_text())
        meta["alts"] = {"b": ["gone"], "c": ["wave"]}
        meta["geometry"]["alts"] = {"c~wave": {"anchor_xz_m": [.6, -.5]}}
        (directory / "run-trio.json").write_text(json.dumps(meta))
        for role in ("a", "b", "c", "c~wave"):
            (directory / f"run-trio-climax__{role}.fbx").write_bytes(b"private finale fixture")
        (directory / "run-trio-climax.json").write_text(json.dumps(dict(
            kind="run-trio-climax", pair=True, duration_s=1, roles=["a", "b", "c"], alts={"c": ["wave"]})))
        clips._clear_entries_cache()
        entries = pose_catalog.world_entries("pose")
        entries["run-trio"]["finale_animation"] = "run-trio-climax"
        pose_catalog.replace_world_entries("pose", entries)
        pose_catalog.reload_catalogs()
        eid = S.request(a, target, members=[b, c])["execution_id"]
        A.respond(b, eid, True)
        A.respond(c, eid, True)
        S.tick(30)
        tick(2)
        tick(2)
        self.assertEqual(R.get(eid)["status"], "active", R.get(eid))

        print("[11] the alt halves of a running group")
        self.assertEqual(row(c, eid)["alt"], {"current": "", "options": [
            {"id": "", "label": "Default"}, {"id": "wave", "label": "Wave"}]})
        self.assertIsNone(row(a, eid)["alt"])
        self.assertIsNone(row(b, eid)["alt"])
        self.assertEqual(clips.role_counts().get("run-trio"), 3)
        self.assertFalse([e for e in clips.clip_entries() if "~" in e["rel"]])
        self.assertEqual([(e["kind"], e["role"], e["alt"]) for e in clips.alt_entries()
                          if e["kind"] == "run-trio"], [("run-trio", "c", "wave")])
        inter = F.C.get_character_profile(c)["interaction"]
        ax, az = inter["anchor"]["x"], inter["anchor"]["z"]
        before = F.C.get_character_pos(c)
        self.assertEqual(A.set_alt(eid, c, "wave"), {"ok": True, "reason": ""})
        self.assertEqual(F.C.get_character_profile(c)["interaction"]["alt"], "wave")
        from app.core.timeutils import game_time
        self.assertEqual(I.payload_for(c, F.C.get_character_profile(c), game_time())["alt"], "wave")
        moved = F.C.get_character_pos(c)
        self.assertAlmostEqual(math.dist((moved["x"], moved["z"]), (before["x"], before["z"])), .5, places=3)
        self.assertAlmostEqual(math.dist((moved["x"], moved["z"]), (ax, az)), math.hypot(.6, .5), places=3)
        self.assertEqual(A.begin_finale(eid, c), {"ok": True, "reason": ""})
        self.assertEqual(A.finale_for(c)["alt"], "wave")
        self.assertEqual(A.begin_finale(eid, b), {"ok": True, "reason": ""})
        self.assertEqual(A.finale_for(b)["alt"], "")
        self.assertEqual(A.set_alt(eid, c, "nope")["reason"], "unknown_alt")
        self.assertEqual(A.set_alt(eid, b, "gone")["reason"], "unknown_alt")
        self.assertEqual(A.set_alt(eid, "Nobody", "wave")["reason"], "not_participant")
        self.assertEqual(A.set_alt(eid, c, ""), {"ok": True, "reason": ""})
        self.assertNotIn("alt", F.C.get_character_profile(c)["interaction"])
        back = F.C.get_character_pos(c)
        self.assertAlmostEqual(math.dist((back["x"], back["z"]), (ax, az)), .6, places=3)
        self.assertAlmostEqual(math.dist((back["x"], back["z"]), (before["x"], before["z"])), 0, places=3)


if __name__ == "__main__":
    test_9_migration()
    unittest.main(argv=[sys.argv[0], *F.REST])
