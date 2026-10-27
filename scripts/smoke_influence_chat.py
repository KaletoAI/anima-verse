#!/usr/bin/env python3
"""Canonical RP influence through the existing extractor and real SQLite state.

Usage: ./.venv/bin/python scripts/smoke_influence_chat.py

Hand-derived expectations from the Task 5 contract (all names/stats synthetic):
* Avatar -> agent +3 with factor 2 changes 50 -> 56. Agent -> addressed
  avatar +4 with factor 2 changes 50 -> 58, even with locked/empty clothing.
  The unrelated active avatar and a named narrative bystander stay at 50.
* An NPC -> NPC source belongs to the receiver's incoming turn, not the
  sender's body evaluation. Its canonical DM identity is evaluated once.
* Two incoming DMs and a private self source stay separate: +3*2 +4*1 +2*1
  changes 50 -> 62, irrespective of JSON pair order. The self consequence
  never receives an actor's rule or duplicates an outgoing body effect.
* Cap 15: original +8 times 5 yields +40, admitted as +15 (50 -> 65).
  A further +1 admits zero, but original -30 times .5 yields -15 and
  bypasses that exhausted ordinary cap (65 -> 50). +/-3*.5 round to +/-2.
  Value 97 plus 10 clamps to 100; history records actual movement of 3.
* Ordered +8, +8 (receipt INSERT fails), +8 admits +8, failure, +7:
  final 65, only first/third receipts. Failure cannot consume RAM budget.
  Retrying the missing pair next hour gives 73. History uses the current
  apply clock, not the older incoming-source stamp.
* A zero/empty evaluation receipts once without effects history. Unknown,
  missing, repeated or malformed pairs reject the whole stat section and
  cannot reserve budget. Unknown actors/targets are never inferred from text.
* Two +3 events with recipient condition signal<55 both see the initial
  apply snapshot 50: +6 +6 -> 62, not 59 from a mid-group rule refresh.
* A persisted obsolete template variable fails before the character LLM
  call, logs an /admin/templates diagnosis and leaves stats/receipts alone;
  the independent avatar-outfit extraction must still run. Old flat chat
  stats are rejected, not silently interpreted as the generic event format.

The first assertion is a route/DB regression, before importing the new core,
so the pre-feature implementation fails on behavior rather than an import.
Only the LLM boundary, follow-up scheduling, synthetic template catalog,
shared-rule fixture path and player-role identity are controlled. Producers,
canonical source resolution, target authority, factors, caps, transactions,
receipts, history and template override rendering are production code. No
provider, server startup, tracked world or real template/library is modified.
"""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STAT = "fixture_signal"
OTHER = "fixture_neighbor"
AVATAR = "demo-avatar"
AGENT = "demo-agent"
BYSTANDER = "demo-bystander"
DECOY = "demo-active-avatar"


def influence(rule_id, actor, recipient, factor=2, direction="both", condition=""):
    return {
        "id": rule_id, "name": rule_id, "type": "influence",
        "condition": condition, "actor_condition": "", "pair_conditions": [],
        "influence": {"actor": actor, "recipient": recipient, "stat": STAT,
                      "direction": direction, "factor": factor},
    }




def main():
    with tempfile.TemporaryDirectory(prefix="influence-chat-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = os.environ["INSTANCE_DIR"] = tmp
        # Initialize storage before importing anything that can touch a world.
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import config
        config.load(root / "config.json")
        from app.core.db import get_connection, init_schema, transaction
        init_schema()
        from app.core import stat_rules, template_overrides
        from app.core.game_time import GameTime
        from app.core.timeutils import game_time, set_game_factor, set_game_time
        from app.core.stat_sources import StatExtractionContext, self_source, source_from_dm
        from app.models import character, character_template, rules
        from app.models.chat import save_direct_message
        from app.models.chat_stat_evaluations import has_evaluation
        from app.routes import chat

        set_game_factor(0)
        set_game_time(GameTime.parse("Y0001-D001T12:00:00"))
        stat_rules.save_setting("chat_cap_per_hour", 15)
        template = {
            "id": "demo-stat-template", "name": "Synthetic stat template",
            "features": {"status_effects_enabled": True},
            "sections": [{"fields": [
                {"key": STAT, "label": "Fixture signal", "store": "status_effects"},
                {"key": OTHER, "label": "Fixture neighbor", "store": "status_effects"},
            ]}],
        }
        shared_rules = root / "shared-rules.json"
        shared_rules.write_text('{"rules": []}', encoding="utf-8")
        calls = []
        queued_response = [{"pose": "", "detail": "", "removed": [], "stat_results": []}]

        def controlled_llm(**kwargs):
            assert kwargs["task"] == "extraction_chat_state", kwargs["task"]
            calls.append(kwargs)
            return SimpleNamespace(content=json.dumps(queued_response[0]))

        with ExitStack() as stack:
            stack.enter_context(patch.object(character_template, "get_template", return_value=template))
            stack.enter_context(patch.object(character_template, "list_templates", return_value=[
                {"id": template["id"], "name": template["id"]}]))
            stack.enter_context(patch.object(rules, "_get_shared_rules_path", return_value=shared_rules))
            stack.enter_context(patch("app.models.account.is_player_controlled",
                                      side_effect=lambda name: name in {AVATAR, DECOY}))
            active = stack.enter_context(patch("app.models.account.get_active_character", return_value=DECOY))
            stack.enter_context(patch("app.core.llm_router.llm_call", side_effect=controlled_llm))
            stack.enter_context(patch("app.core.chat_engine.run_follow_up",
                                      side_effect=lambda callback, **kwargs: callback()))

            def seed(name, value=50, *, enabled=True):
                assert character.save_character_profile(name, {
                    "template": template["id"],
                    "status_effects": {STAT: value, OTHER: 50, "fixture_undeclared": 50},
                    "current_location": "fixture", "current_room": "room",
                }, create_new=True)
                if not enabled:
                    assert character.save_character_config(name, {"status_effects_enabled": False})
                character.set_outfit_locked(name, True)

            def value(name, key=STAT):
                return character.get_character_profile(name, strict=True)["status_effects"][key]

            def history(name):
                entries = [dict(row) | {"state": json.loads(row["state_json"])} for row in
                           get_connection().execute(
                               "SELECT id,game_ts,state_json FROM state_history "
                               "WHERE character_name=? ORDER BY id", (name,))]
                return [row for row in entries if row["state"].get("type") == "effects"]

            def receipt_ids(name):
                return {row[0] for row in get_connection().execute(
                    "SELECT event_id FROM chat_stat_evaluations WHERE recipient=?", (name,))}

            def state_snapshot():
                conn = get_connection()
                return tuple(tuple(tuple(row) for row in conn.execute(query)) for query in (
                    "SELECT * FROM character_state ORDER BY character_name",
                    "SELECT * FROM chat_stat_evaluations ORDER BY event_id,recipient",
                    "SELECT * FROM state_history ORDER BY id",
                ))

            def dm(sender, recipient, text="A synthetic encouragement."):
                event_id = save_direct_message(sender, recipient, text)
                assert event_id, (sender, recipient)
                source = source_from_dm(event_id)
                assert source is not None and source.actor == sender
                return source

            def context(owner, *sources):
                self_id = next((source.event_id for source in sources if source.medium == "self"),
                               "self:fixture-unused")
                return StatExtractionContext(tuple(sources), self_id, owner)

            def extract(owner, ctx, data):
                queued_response[0] = data
                before = len(calls)
                chat._extract_context_from_last_chat(
                    owner,
                    [{"role": "user", "content": "An earlier line names demo-bystander."},
                     {"role": "assistant", "content": "The current response."}],
                    stat_context=ctx,
                )
                return len(calls) - before

            for name in (AVATAR, AGENT, BYSTANDER, DECOY):
                seed(name)
            rules.save_rules([
                influence("demo-incoming", AVATAR, AGENT),
                influence("demo-outgoing", AGENT, AVATAR),
            ])

            incoming = dm(AVATAR, AGENT)
            incoming_context = context(AGENT, incoming)
            assert extract(AGENT, incoming_context, {
                "pose": "", "detail": "", "removed": [],
                "stat_results": [{"event": "S0", "target": "T0", "deltas": {STAT: 3}}],
            }) == 1
            # Intended first behavioral RED: the old route ignores stat_results.
            assert value(AGENT) == 56, "Avatar encouragement +3 * 2 must change agent 50 -> 56"
            assert value(AVATAR) == value(DECOY) == value(BYSTANDER) == 50
            assert has_evaluation(incoming.event_id, AGENT)
            cause = history(AGENT)[-1]["state"]["metadata"]
            assert cause["source"] == "chat" and cause["event_id"] == incoming.event_id
            assert cause["cause"][STAT] == {
                "actor": AVATAR, "base_delta": 3, "modified_delta": 6, "capped_delta": 6,
                "factor": 2.0, "rules": [{"id": "demo-incoming", "name": "demo-incoming", "factor": 2.0}],
            }, cause

            outgoing = dm(AGENT, AVATAR)
            assert outgoing.avatar_targets == (AVATAR,)
            assert outgoing.avatar_audience == (AVATAR,)
            assert extract(AGENT, context(AGENT, outgoing), {
                "pose": "", "detail": "", "removed": [],
                "stat_results": [{"event": "S0", "target": "T0", "deltas": {STAT: 4}}],
            }) == 1
            assert value(AVATAR) == 58 and value(AGENT) == 56 and value(DECOY) == 50
            assert has_evaluation(outgoing.event_id, AVATAR)
            assert history(AVATAR)[-1]["state"]["metadata"]["cause"][STAT]["actor"] == AGENT

            # Import only after the pre-feature route has failed on real values.
            from app.core.chat_stat_effects import (
                apply_chat_stat_results, build_stat_targets, parse_stat_results,
            )

            def authority(ctx):
                targets = build_stat_targets(ctx)
                return targets, {(pair["source"].event_id, pair["recipient"])
                                 for pair in targets["pair_map"].values()}

            def payload(ctx, deltas, *, reverse=False):
                targets, actual = authority(ctx)
                assert actual == set(deltas), (actual, set(deltas))
                items = [{"event": event, "target": target,
                          "deltas": deltas[(pair["source"].event_id, pair["recipient"])]}
                         for (event, target), pair in targets["pair_map"].items()]
                return {"pose": "", "detail": "", "removed": [],
                        "stat_results": list(reversed(items)) if reverse else items}

            def apply(ctx, deltas, *, reverse=False):
                data = payload(ctx, deltas, reverse=reverse)
                return apply_chat_stat_results(ctx, parse_stat_results(data, build_stat_targets(ctx)))

            assert authority(incoming_context)[1] == set(), "Receipted pairs must not be requested again"
            assert authority(context(AVATAR, outgoing))[1] == set(), "Avatar receiver must not repeat sender-owned effects"
            npc_source = dm(AGENT, BYSTANDER)
            assert authority(context(AGENT, npc_source))[1] == set(), "Sender cannot evaluate NPC recipient"
            npc_context = context(BYSTANDER, npc_source)
            assert extract(BYSTANDER, npc_context,
                           payload(npc_context, {(npc_source.event_id, BYSTANDER): {STAT: 3}})) == 1
            assert value(BYSTANDER) == 53, "Without Influence, base delta must remain unchanged"
            before = state_snapshot()
            extract(BYSTANDER, npc_context, {"stat_results": []})
            assert state_snapshot() == before and receipt_ids(BYSTANDER) == {npc_source.event_id}

            # Real perceived speech: an unaddressed player and a narrative name
            # are not targets, even if both are in the same room.
            from app.core.perception import record_utterance
            from app.core.stat_sources import source_from_utterance
            with patch("app.core.perception._resolve_presence", return_value=(
                    [AGENT, AVATAR, DECOY, BYSTANDER], [], [])), patch(
                    "app.core.perception.inattentive_listeners", return_value=()):
                uid = record_utterance(speaker=AGENT, content="demo-bystander believes in you.",
                                       volume="whisper", addressees=[AVATAR],
                                       location_id="fixture", room_id="room")
            speech = source_from_utterance(uid)
            assert speech is not None
            assert speech.avatar_audience == (AVATAR,), "Whisper metadata listeners have no content role"
            assert authority(context(AGENT, speech))[1] == {(speech.event_id, AVATAR)}
            assert authority(context(DECOY, speech))[1] == set()

            # Content-bearing but unaddressed avatars are not outgoing targets,
            # and a later role release must not give their old input to an NPC.
            with patch("app.core.perception._resolve_presence", return_value=(
                    [AGENT, AVATAR, DECOY, BYSTANDER], [], [])), patch(
                    "app.core.perception.inattentive_listeners", return_value=()):
                heard_id = record_utterance(
                    speaker=AGENT, content="A room-wide encouragement.",
                    addressees=[BYSTANDER], location_id="fixture", room_id="room")
            heard = source_from_utterance(heard_id)
            assert heard is not None
            assert heard.avatar_targets == ()
            assert set(heard.avatar_audience) == {AVATAR, DECOY}
            assert authority(context(AGENT, heard))[1] == set()
            assert authority(context(BYSTANDER, heard))[1] == {(heard.event_id, BYSTANDER)}
            with patch("app.models.account.is_player_controlled", return_value=False):
                released = source_from_utterance(heard_id)
                assert released is not None and released.avatar_audience == heard.avatar_audience
                assert authority(context(AVATAR, released))[1] == set()
                assert authority(context(DECOY, released))[1] == set()

            # Body consequences are private self sources; the spoken source's
            # actor cannot make the same body eligible a second time.
            body = self_source(AGENT, "The effort is tiring.", "self:fixture-body")
            body_ctx = context(AGENT, speech, body)
            assert authority(body_ctx)[1] == {(speech.event_id, AVATAR), (body.event_id, AGENT)}
            assert extract(AGENT, body_ctx, payload(body_ctx, {
                (speech.event_id, AVATAR): {}, (body.event_id, AGENT): {STAT: 2},
            })) == 1, "Two targets must share the existing character extraction round"
            assert has_evaluation(speech.event_id, AVATAR) and has_evaluation(body.event_id, AGENT)
            assert value(AGENT) == 58
            assert history(AGENT)[-1]["state"]["metadata"]["cause"][STAT]["factor"] == 1

            # A committed communication still has effects when the RP model
            # returns no prose. This is one existing extraction phase, never
            # one round per source, and cannot invent an owner's body update.
            source_only = dm(AGENT, AVATAR, "A real message without an RP reply.")
            source_only_ctx = context(AGENT, source_only)
            queued_response[0] = payload(source_only_ctx, {
                (source_only.event_id, AVATAR): {STAT: 2},
            })
            before_calls = len(calls)
            owner_before = character.get_character_profile(AGENT, strict=True)
            chat._extract_context_from_last_chat(AGENT, [], stat_context=source_only_ctx)
            assert len(calls) == before_calls + 1
            assert value(AVATAR) == 62 and has_evaluation(source_only.event_id, AVATAR)
            owner_after = character.get_character_profile(AGENT, strict=True)
            for key in ("current_activity", "pose_key", "pose_flavor", "equipped_pieces"):
                assert owner_after.get(key) == owner_before.get(key), key
            assert value(AGENT) == 58 and not has_evaluation(source_only.event_id, AGENT)
            before_calls = len(calls)
            chat._extract_context_from_last_chat(AGENT, [], stat_context=context(AGENT, npc_source))
            assert len(calls) == before_calls, "No prose and no sender-owned stat pairs must not call an LLM"

            seed("demo-multiple")
            rules.add_rule(influence("demo-multiple-incoming", AVATAR, "demo-multiple"))
            first = dm(AVATAR, "demo-multiple")
            second = dm(BYSTANDER, "demo-multiple")
            own = self_source("demo-multiple", "An independent body consequence.", "self:fixture-multiple")
            multi_ctx = context("demo-multiple", first, second, own)
            data = payload(multi_ctx, {
                (first.event_id, "demo-multiple"): {STAT: 3},
                (second.event_id, "demo-multiple"): {STAT: 4},
                (own.event_id, "demo-multiple"): {STAT: 2},
            }, reverse=True)
            assert extract("demo-multiple", multi_ctx, data) == 1, "Sources/targets/rules must not add LLM rounds"
            assert value("demo-multiple") == 62
            assert receipt_ids("demo-multiple") == {first.event_id, second.event_id, own.event_id}
            metadata = [row["state"]["metadata"] for row in history("demo-multiple")]
            assert [row["event_id"] for row in metadata] == [source.event_id for source in sorted(
                (first, second, own), key=lambda source: source.order)]
            assert {row["cause"][STAT]["actor"]: row["cause"][STAT]["factor"] for row in metadata} == {
                AVATAR: 2, BYSTANDER: 1, None: 1}

            seed("demo-disabled", enabled=False)
            disabled = dm(AVATAR, "demo-disabled")
            assert authority(context("demo-disabled", disabled))[1] == set()
            targets = build_stat_targets(context(AGENT, dm(AVATAR, AGENT)))
            assert all("fixture_undeclared" not in pair["keys"] for pair in targets["pair_map"].values())
            assert build_stat_targets(context(AGENT))["required_stat_pairs"] == []

            # Reject partial or invented authority before any write/cap. In
            # particular bool is an int subclass, but not a valid model delta.
            malformed_source = dm(AVATAR, AGENT)
            malformed_ctx = context(AGENT, malformed_source)
            valid = payload(malformed_ctx, {(malformed_source.event_id, AGENT): {STAT: 1}})
            invalid = []
            for bad_delta in (True, False, 1.0, float("nan"), float("inf"), -101, 101, "3", None):
                bad = copy.deepcopy(valid)
                bad["stat_results"][0]["deltas"][STAT] = bad_delta
                invalid.append(bad)
            for changes in ({"event": "invented"}, {"target": BYSTANDER},
                            {"deltas": {"fixture_undeclared": 2}}, {"deltas": []}):
                bad = copy.deepcopy(valid)
                bad["stat_results"][0].update(changes)
                invalid.append(bad)
            invalid += [
                {"stat_results": []}, {"stat_results": {}}, {"stats": {STAT: 10}},
                {"stat_results": valid["stat_results"] * 2},
                {"stat_results": [{"event": "S0", "deltas": {STAT: 1}}]},
                {"stat_results": [None]},
            ]
            before = state_snapshot()
            for bad in invalid:
                try:
                    parse_stat_results(bad, build_stat_targets(malformed_ctx))
                except ValueError as error:
                    assert str(error), "Parser failures must be actionable"
                else:
                    raise AssertionError(f"Accepted invalid structured stats: {bad!r}")
            assert state_snapshot() == before
            # A valid pair cannot make a sibling invalid pair partially commit.
            partial = copy.deepcopy(valid)
            partial["stat_results"].append({"event": "S0", "target": "invented", "deltas": {STAT: 40}})
            extract(AGENT, malformed_ctx, partial)
            assert state_snapshot() == before and not has_evaluation(malformed_source.event_id, AGENT)
            extract(AGENT, malformed_ctx, {"stats": {STAT: 40}, "removed": []})
            assert state_snapshot() == before, "Legacy flat chat stats must not write or receipt"

            # The application boundary also verifies caller authority; parser
            # output is not a license to name another recipient/source later.
            for forged in (
                {"source": malformed_source, "recipient": BYSTANDER, "deltas": {STAT: 10}},
                {"source": speech, "recipient": AGENT, "deltas": {STAT: 10}},
            ):
                try:
                    apply_chat_stat_results(malformed_ctx, [forged])
                except ValueError:
                    pass
                assert state_snapshot() == before

            empty = dm(AVATAR, "demo-multiple")
            empty_ctx = context("demo-multiple", empty)
            before_history = len(history("demo-multiple"))
            result = apply(empty_ctx, {(empty.event_id, "demo-multiple"): {}})
            assert [item["status"] for item in result] == ["unchanged"]
            assert has_evaluation(empty.event_id, "demo-multiple")
            assert len(history("demo-multiple")) == before_history
            assert authority(empty_ctx)[1] == set()
            zero = dm(AVATAR, "demo-multiple")
            zero_ctx = context("demo-multiple", zero)
            result = apply(zero_ctx, {(zero.event_id, "demo-multiple"): {STAT: 0}})
            assert [item["status"] for item in result] == ["unchanged"]
            assert has_evaluation(zero.event_id, "demo-multiple")
            assert len(history("demo-multiple")) == before_history

            seed("demo-cap")
            rules.add_rule(influence("demo-cap-increase", AVATAR, "demo-cap", 5, "increase"))
            rules.add_rule(influence("demo-cap-decrease", AVATAR, "demo-cap", .5, "decrease"))
            cap_sources = [dm(AVATAR, "demo-cap") for _ in range(3)]
            cap_ctx = context("demo-cap", *cap_sources)
            cap_data = payload(cap_ctx, dict(zip(
                [(source.event_id, "demo-cap") for source in cap_sources],
                [{STAT: 8}, {STAT: 1}, {STAT: -30}], strict=True)))
            assert extract("demo-cap", cap_ctx, cap_data) == 1
            assert value("demo-cap") == 50
            cap_history = history("demo-cap")
            assert [row["state"]["metadata"]["changes"][STAT] for row in cap_history] == [
                {"old": 50, "new": 65}, {"old": 65, "new": 50}]
            assert cap_history[0]["state"]["metadata"]["cause"][STAT] == {
                "actor": AVATAR, "base_delta": 8, "modified_delta": 40, "capped_delta": 15,
                "factor": 5.0, "rules": [{"id": "demo-cap-increase", "name": "demo-cap-increase", "factor": 5.0}],
            }
            assert cap_history[1]["state"]["metadata"]["cause"][STAT]["capped_delta"] == -15
            assert receipt_ids("demo-cap") == {source.event_id for source in cap_sources}

            seed("demo-round")
            rules.add_rule(influence("demo-round-half", AVATAR, "demo-round", .5))
            rounds = [dm(AVATAR, "demo-round") for _ in range(2)]
            apply(context("demo-round", *rounds), {
                (rounds[0].event_id, "demo-round"): {STAT: 3},
                (rounds[1].event_id, "demo-round"): {STAT: -3},
            }, reverse=True)
            assert value("demo-round") == 50
            assert [row["state"]["metadata"]["cause"][STAT]["modified_delta"]
                    for row in history("demo-round")] == [2, -2]
            seed("demo-clamp", 97)
            clamp = dm(AVATAR, "demo-clamp")
            apply(context("demo-clamp", clamp), {(clamp.event_id, "demo-clamp"): {STAT: 10}})
            assert value("demo-clamp") == 100
            clamp_meta = history("demo-clamp")[-1]["state"]["metadata"]
            assert clamp_meta["changes"][STAT] == {"old": 97, "new": 100}
            assert clamp_meta["cause"][STAT]["capped_delta"] == 10

            # Failure of the middle pair must not abort the group or publish
            # its reservation; reverse JSON deliberately challenges ordering.
            seed("demo-ordered")
            ordered = [dm(AVATAR, "demo-ordered") for _ in range(3)]
            ordered_ctx = context("demo-ordered", *reversed(ordered))
            set_game_time(GameTime.parse("Y0001-D001T13:00:00"))
            apply_stamp = game_time().canonical()
            rejected_event = ordered[1].event_id.replace("'", "''")
            with transaction() as conn:
                conn.execute("CREATE TEMP TRIGGER reject_chat_pair BEFORE INSERT ON chat_stat_evaluations "
                             f"WHEN NEW.event_id='{rejected_event}' "
                             "BEGIN SELECT RAISE(ABORT,'synthetic pair rejection'); END")
            try:
                result = apply(ordered_ctx, {(source.event_id, "demo-ordered"): {STAT: 8}
                                             for source in ordered}, reverse=True)
            finally:
                with transaction() as conn:
                    conn.execute("DROP TRIGGER reject_chat_pair")
            assert [item["status"] for item in result] == ["applied", "failed", "applied"], result
            assert value("demo-ordered") == 65
            assert receipt_ids("demo-ordered") == {ordered[0].event_id, ordered[2].event_id}
            ordered_history = history("demo-ordered")
            assert [row["state"]["metadata"]["event_id"] for row in ordered_history] == [
                ordered[0].event_id, ordered[2].event_id]
            assert [row["state"]["metadata"]["cause"][STAT]["capped_delta"] for row in ordered_history] == [8, 7]
            assert all(row["game_ts"] == apply_stamp != ordered[0].game_ts for row in ordered_history)
            set_game_time(GameTime.parse("Y0001-D001T14:00:00"))
            apply(ordered_ctx, {(ordered[1].event_id, "demo-ordered"): {STAT: 8}})
            assert value("demo-ordered") == 73 and len(history("demo-ordered")) == 3

            seed("demo-snapshot")
            rules.add_rule(influence("demo-snapshot-condition", AVATAR, "demo-snapshot", condition=f"{STAT}<55"))
            snapshot_sources = [dm(AVATAR, "demo-snapshot") for _ in range(2)]
            apply(context("demo-snapshot", *snapshot_sources), {
                (source.event_id, "demo-snapshot"): {STAT: 3} for source in snapshot_sources})
            assert value("demo-snapshot") == 62, "Every pair must use the same pre-write rule/profile snapshot"

            # A broken world overlay must not reveal a stronger shared rule.
            # Actual persisted JSON corruption exercises the strict public
            # loader, not a mocked factor or exception-shaped wiring echo.
            seed("demo-rule-read-failure")
            shadow_id = "demo-shadowed-factor"
            shared_rules.write_text(json.dumps({"rules": [
                influence(shadow_id, AVATAR, "demo-rule-read-failure", 5),
            ]}), encoding="utf-8")
            rules.add_rule(influence(shadow_id, AVATAR, "demo-rule-read-failure", .5))
            broken_source = dm(AVATAR, "demo-rule-read-failure")
            broken_ctx = context("demo-rule-read-failure", broken_source)
            parsed = parse_stat_results(payload(broken_ctx, {
                (broken_source.event_id, "demo-rule-read-failure"): {STAT: 8},
            }), build_stat_targets(broken_ctx))
            original_meta = get_connection().execute(
                "SELECT meta FROM rules WHERE id=?", (shadow_id,)).fetchone()[0]
            with transaction() as conn:
                conn.execute("UPDATE rules SET meta='not valid JSON' WHERE id=?", (shadow_id,))
            before = state_snapshot()
            try:
                result = apply_chat_stat_results(broken_ctx, parsed)
            finally:
                with transaction() as conn:
                    conn.execute("UPDATE rules SET meta=? WHERE id=?", (original_meta, shadow_id))
            assert [item["status"] for item in result] == ["failed"], result
            assert state_snapshot() == before and value("demo-rule-read-failure") == 50
            assert not has_evaluation(broken_source.event_id, "demo-rule-read-failure")
            apply_chat_stat_results(broken_ctx, parsed)
            assert value("demo-rule-read-failure") == 54
            remaining = dm(AVATAR, "demo-rule-read-failure")
            apply(context("demo-rule-read-failure", remaining), {
                (remaining.event_id, "demo-rule-read-failure"): {STAT: 22},
            })
            assert value("demo-rule-read-failure") == 65, "Failed rule snapshot must not consume cap"
            shared_rules.write_text('{"rules": []}', encoding="utf-8")

            # A failed persisted clock read must not assign an epoch-hour
            # budget or write an otherwise valid effect under a false stamp.
            import sqlite3
            from app.core import timeutils
            seed("demo-clock-read-failure")
            clock_source = dm(AVATAR, "demo-clock-read-failure")
            clock_ctx = context("demo-clock-read-failure", clock_source)
            clock_parsed = parse_stat_results(payload(clock_ctx, {
                (clock_source.event_id, "demo-clock-read-failure"): {STAT: 8},
            }), build_stat_targets(clock_ctx))
            before = state_snapshot()
            timeutils.invalidate_game_clock_cache()
            with patch("app.models.world.get_connection",
                       side_effect=sqlite3.OperationalError("clock storage unavailable")):
                result = apply_chat_stat_results(clock_ctx, clock_parsed)
            assert [entry["status"] for entry in result] == ["failed"], result
            assert state_snapshot() == before and value("demo-clock-read-failure") == 50
            assert not has_evaluation(clock_source.event_id, "demo-clock-read-failure")
            timeutils.invalidate_game_clock_cache()
            apply_chat_stat_results(clock_ctx, clock_parsed)
            assert value("demo-clock-read-failure") == 58

            # Persist an actual world override: obsolete stat_list fails for
            # the character only; an independent avatar call still renders.
            from app.models import inventory
            item = inventory.add_item("Synthetic coat", category="outfit_piece",
                                      outfit_piece={"slots": [sorted(inventory.VALID_PIECE_SLOTS)[0]]})
            from app.core.keyed_lock import keyed_lock
            with keyed_lock("character_profile", AVATAR):
                profile = character.get_character_profile(AVATAR, strict=True)
                profile["equipped_pieces"] = {item["outfit_piece"]["slots"][0]: item["id"]}
                assert character.save_character_profile(AVATAR, profile)
            character.set_outfit_locked(AVATAR, False)
            active.return_value = AVATAR
            override = ("## system\n{% if is_avatar %}Outfit only{% else %}{{ stat_list }}{% endif %}\n"
                        "## user\n{{ source_text }}\n")
            template_overrides.set_override("tasks/extraction_chat_state.md", override, "obsolete-base")
            old_template_source = dm(AVATAR, AGENT)
            old_template_ctx = context(AGENT, old_template_source)
            before = state_snapshot()
            before_calls = len(calls)
            try:
                extract(AGENT, old_template_ctx, {"removed": [], "stat_results": []})
            finally:
                template_overrides.delete_override("tasks/extraction_chat_state.md")
            assert state_snapshot() == before
            assert len(calls) == before_calls + 1 and calls[-1]["agent_name"] == AVATAR, (
                "Character render failure must not skip the independent avatar-outfit call", calls[before_calls:])
            assert not has_evaluation(old_template_source.event_id, AGENT)

            print("PASS influence chat: real DM/perception -> extractor -> factor/cap -> atomic state/receipt/history")
            print("Controlled boundary: llm_call only; no real LLM/provider. Synthetic multi-source extraction: one call.")
            print(f"Observed canonical event={incoming.event_id} actor={AVATAR} base=3 factor=2 capped=6 old=50 new={cause['changes'][STAT]['new']}")


if __name__ == "__main__":
    main()
