#!/usr/bin/env python3
"""A pair furniture action requested with ``consent="react"`` starts at
once; the partner reacts while both walk over, and may push it away. Every
pair action offers it — the requester chooses, nothing is authored.

Usage: ./.venv/bin/python scripts/smoke_prop_action_react.py

Real temporary world, real journeys, real claims — the fixtures of
``smoke_prop_action_runs.py`` (``authored_pair``: actor at (1,5), partner at
(2,5), a two-place seat; 30 game seconds bring both to their access points).
The ``pair_reaction`` provider is a recorder; the model never runs. Expected
values hand-derived from ``prop_action_engine`` (REACTION_WAIT_S = 60 system
seconds, sentiment step 0.05 per feeling, romantic step 0.02, resisted
actor -0.03) and ``relationship.record_interaction`` (fresh pair: strength
10, sentiments 0; the average sentiment delta below -0.01 turns the strength
change into avg*10):

  [1] react start: status "approaching" at once (no invitation), 4 claims
      (2 slots + 2 persons, like an accepted ask run), consented, reaction
      "pending"; the provider is asked ONCE with (execution, actor, partner);
      the room hears "{actor} approaches {partner}: run-pair." (the pose key
      is its own label — the fixture pose has none). Rows: the
      partner's has own_role partner, partner_consent react, can_resist; the
      actor's reaction "pending" and no can_resist.
      (Fails on 837538f1: request() takes no ``consent``.)
  [2] both arrive, no reaction yet: still "approaching", phase "" — never
      "entry"; 10 more game seconds change nothing (no approach deadline
      while waiting). react(accept, feeling 2, line) -> phase "entry" at
      once, two ticks -> "active"; the line is told to the room verbatim.
      Relationship: partner->actor +0.10, actor->partner 0, strength
      10 + 1 = 11, one history entry of type "pair_reaction".
  [3] react(resist, feeling -2): "cancelled" / "partner_resisted", no
      claims left; partner->actor -0.10, actor->partner -0.03; average
      -0.065 -> strength 10 - 0.65 = 9.35. A second answer changes nothing.
  [4] no answer: both arrived, the wait is 61 s old -> due_in_game_s 0, the
      next advance goes into "entry" with reaction "timeout".
  [5] a romantic accept (feeling 1, romantic, compatible pair): tension
      0 + 0.02 = 0.02.
  [6] a player-controlled partner: reaction "player", the provider is NOT
      asked, nothing waits; its cancel is a push: "partner_resisted", the
      room hears "{partner} pushes {actor} away.", partner->actor -0.05,
      actor->partner -0.03.
  [7] no provider registered (the interact package removed): reaction
      "none", the run goes straight in.
  [8] react() by someone else -> "not_partner"; consent "maybe" ->
      refused "invalid_request"; the same action requested with "ask"
      (the default) -> "awaiting_consent".
  [11] the partner names the run it is in again (actor and partner swapped,
      same piece and action): the answer is that run — same execution id,
      its status, ``already`` True — not "participant_claimed"; the claims
      stay 4 and the run is untouched. The actor repeating it gets the same.
  [9] a plugin task declaring lane_priority chat ranks as CHAT on the lanes.
  [10] the interact package: the parser takes the first JSON object, clamps
      feeling -5 -> -2, strips the line, refuses anything without
      accept/resist; the prompt renders for a waiting run (StrictUndefined —
      every variable is there; the fixture action "Rest" on the piece "Approach
      fixture") and is None once the run no longer waits.
"""
import sys
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import unittest

import smoke_prop_action_runs as S
from smoke_prop_action_runs import A, F, R, request, tick
# Use the shared fixture's private world for the direct app imports below.
F.paths.init(F.ROOT / "world")
from app.core import hooks
from app.core.game_time import GameDuration


def sentiment(source, target):
    from app.models.relationship import get_relationship
    rel = get_relationship(source, target) or {}
    first = rel.get("character_a") == source
    return round(rel.get("sentiment_a_to_b" if first else "sentiment_b_to_a", 0.0), 4), rel


def arrive():
    F.set_game_time(F.game_time() + GameDuration.of(seconds=30))
    F.E.advance_all_journeys()
    A.advance(F.game_time())


class React(unittest.TestCase):
    def setUp(self):
        self.asked = []
        self.lines = []
        hooks.register_provider("pair_reaction", lambda **kw: self.asked.append(kw), owner="smoke")
        self.addCleanup(hooks._providers.pop, "pair_reaction", None)
        from app.core import perception
        real = perception.record_utterance
        self.addCleanup(setattr, perception, "record_utterance", real)
        perception.record_utterance = lambda **kw: self.lines.append(kw["content"])

    def tearDown(self):
        F.W.set_world_frozen(False)
        F.set_game_factor(0)
        for run in R.live_runs():
            A.cancel(run["actor"], run["execution_id"])
        F.assert_no_external_work()

    def start(self):
        name, partner, target, pid = S.authored_pair()
        result = request(name, target, partner=partner, consent="react")
        self.assertEqual(result["status"], "approaching", result)
        return name, partner, result["execution_id"]

    def row(self, who, eid):
        state = A.state_for(who)
        return next(r for kind in ("incoming", "outgoing", "current") for r in state[kind]
                    if r["execution_id"] == eid)

    def test_1_starts_without_invitation(self):
        name, partner, eid = self.start()
        run = R.get(eid)
        self.assertEqual(len(R.claims()), 4)
        self.assertTrue(run["data"]["consented"])
        self.assertEqual(run["data"]["reaction"]["state"], "pending")
        self.assertEqual(self.asked, [dict(execution_id=eid, actor=name, partner=partner)])
        # Room-entry lines of the fixture set-up aside, the run tells ONE line.
        told = [line for line in self.lines if name in line and partner in line]
        self.assertEqual(told, [f"{name} approaches {partner}: run-pair."])
        theirs, mine = self.row(partner, eid), self.row(name, eid)
        self.assertEqual((theirs["own_role"], theirs["partner_consent"], theirs["can_resist"]),
                         ("partner", "react", True))
        self.assertEqual((mine["own_role"], mine["reaction"], mine["can_resist"]), ("actor", "pending", False))

    def test_2_waits_at_the_furniture_then_accept_goes_in(self):
        name, partner, eid = self.start()
        arrive()
        run = R.get(eid)
        self.assertEqual(sorted(run["data"]["arrived"]), sorted([name, partner]))
        self.assertEqual((run["status"], run["phase"]), ("approaching", ""))
        tick(10)
        self.assertEqual((R.get(eid)["status"], R.get(eid)["phase"]), ("approaching", ""))
        result = A.react(partner, eid, True, line="She smiles and moves closer.", feeling=2)
        self.assertEqual(result["status"], "approaching", result)
        self.assertEqual(R.get(eid)["phase"], "entry")
        self.assertIn("She smiles and moves closer.", self.lines)
        tick(2)
        tick(2)
        self.assertEqual(R.get(eid)["status"], "active")
        value, rel = sentiment(partner, name)
        self.assertEqual(value, 0.1)
        self.assertEqual(sentiment(name, partner)[0], 0.0)
        self.assertEqual(rel["strength"], 11)
        self.assertEqual([h["type"] for h in rel["history"]], ["pair_reaction"])

    def test_3_resist_cancels(self):
        name, partner, eid = self.start()
        result = A.react(partner, eid, False, line="He steps aside.", feeling=-2)
        self.assertEqual((result["status"], result["reason"]), ("cancelled", "partner_resisted"), result)
        self.assertFalse(R.claims())
        value, rel = sentiment(partner, name)
        self.assertEqual(value, -0.1)
        self.assertEqual(sentiment(name, partner)[0], -0.03)
        self.assertAlmostEqual(rel["strength"], 9.35)
        again = A.react(partner, eid, True, feeling=2)
        self.assertEqual(again["reason"], "partner_resisted")
        self.assertEqual(sentiment(partner, name)[0], -0.1)

    def test_4_no_answer_goes_on_after_the_wait(self):
        name, partner, eid = self.start()
        arrive()
        self.assertEqual(R.get(eid)["phase"], "")
        self.assertIsNone(A.due_in_game_s(F.game_time()))
        later = A.utc_now() + timedelta(seconds=61)
        with patch.object(A, "utc_now", lambda: later):
            self.assertEqual(A.due_in_game_s(F.game_time()), 0.0)
            A.advance(F.game_time())
        run = R.get(eid)
        self.assertEqual((run["phase"], run["data"]["reaction"]["state"]), ("entry", "timeout"))

    def test_5_romantic_accept(self):
        name, partner, eid = self.start()
        with patch("app.models.relationship.are_romantically_compatible", lambda a, b: True):
            A.react(partner, eid, True, feeling=1, romantic=True)
        self.assertAlmostEqual(sentiment(partner, name)[1]["romantic_tension"], 0.02)

    def test_6_player_partner_pushes_away(self):
        with patch("app.models.account.is_player_controlled", lambda who: True):
            name, partner, eid = self.start()
        self.assertEqual(R.get(eid)["data"]["reaction"]["state"], "player")
        self.assertEqual(self.asked, [])
        arrive()
        self.assertEqual(R.get(eid)["phase"], "entry")
        result = A.cancel(partner, eid)
        self.assertEqual((result["status"], result["reason"]), ("cancelled", "partner_resisted"), result)
        self.assertEqual(self.lines[-1], f"{partner} pushes {name} away.")
        self.assertEqual(sentiment(partner, name)[0], -0.05)
        self.assertEqual(sentiment(name, partner)[0], -0.03)

    def test_7_without_provider_nothing_waits(self):
        hooks._providers.pop("pair_reaction", None)
        name, partner, eid = self.start()
        self.assertEqual(R.get(eid)["data"]["reaction"]["state"], "none")
        arrive()
        self.assertEqual(R.get(eid)["phase"], "entry")

    def test_8_wrong_partner_and_validation(self):
        name, partner, target, pid = S.authored_pair()
        self.assertEqual(request(name, target, partner=partner, consent="maybe")["reason"], "invalid_request")
        eid = request(name, target, partner=partner, consent="react")["execution_id"]
        self.assertEqual(A.react(name, eid, False)["reason"], "not_partner")
        A.cancel(name, eid)
        self.assertEqual(request(name, target, partner=partner)["status"], "awaiting_consent")

    def test_11_naming_the_own_run_again(self):
        name, partner, target, pid = S.authored_pair()
        eid = request(name, target, partner=partner, consent="react")["execution_id"]
        before = R.get(eid)
        for who, other in ((partner, name), (name, partner)):
            answer = request(who, target, partner=other)
            self.assertEqual((answer["execution_id"], answer["status"], answer.get("already")),
                             (eid, "approaching", True))
        self.assertEqual(len(R.claims()), 4)
        self.assertEqual(R.get(eid), before)

    def test_10_package_prompt_and_parser(self):
        from app.core import prompt_templates
        from plugins.interact.reaction import parse_reaction, reaction_prompt
        self.assertEqual(parse_reaction('Sure. {"reaction": "resist", "line": " No! ", "feeling": -5}'),
                         (False, "No!", -2, False))
        self.assertEqual(parse_reaction('{"reaction": "accept", "line": "Ok.", "feeling": 1, "romantic": true}'),
                         (True, "Ok.", 1, True))
        for garbage in ("", "accept", '{"reaction": "maybe"}', '{"reaction": "accept"'):
            self.assertIsNone(parse_reaction(garbage), garbage)
        name, partner, eid = self.start()
        # The temporary world's package discovery (it reruns while the
        # thought context is built) does not see the repo's interact
        # package; keep its template dir on every registration.
        interact = Path(__file__).resolve().parents[1] / "plugins/interact/templates/llm"
        register = prompt_templates.register_package_template_dirs
        self.addCleanup(register, prompt_templates.template_search_dirs()[1:])
        self.enterContext(patch.object(prompt_templates, "register_package_template_dirs",
                                       lambda dirs: register([*dirs, interact])))
        register([*prompt_templates.template_search_dirs()[1:], interact])
        system, user = reaction_prompt(eid, name, partner)
        self.assertIn('"reaction": "accept" or "resist"', system)
        self.assertIn(f'Right now: {name} starts "Rest" with {partner} on the Approach fixture, without asking.', user)
        A.react(partner, eid, True)
        self.assertIsNone(reaction_prompt(eid, name, partner))

    def test_9_lane_priority(self):
        from app.core import llm_lanes, llm_tasks
        from app.core.llm_queue import Priority
        self.assertTrue(llm_tasks.register_plugin_task("smoke_react_lane", dict(
            label="x", category="chat", priority="high", lane_priority="chat"), "smoke"))
        self.addCleanup(llm_tasks.TASK_TYPES.pop, "smoke_react_lane", None)
        self.assertEqual(llm_lanes.lane_priority_for("smoke_react_lane"), int(Priority.CHAT))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *F.REST])
