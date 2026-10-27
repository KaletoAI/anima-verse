#!/usr/bin/env python3
"""Canonical RP sources preserve real recipients and atomic DM delivery.

Usage: ./.venv/bin/python scripts/smoke_influence_sources.py

A whispered line addressed to Receiver supplies content to Sender/Receiver,
not Bystander. A source records that audience and player-role snapshot even
if the live role changes later. Each DM has two history rows but one source;
image/game stamps survive both mirrors. A failed second mirror writes zero
rows, and an insertion observer proves Receiver was written before Sender
failed. Real chime, single-mode tool-only, pre-rendered thought and deferred
speech turns reach the shared extractor and change a declared fixture stat
50 -> 52 once; empty/SKIP context alone does not spend an extraction call.
All storage is temporary; no real world, provider or image service is contacted.
"""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from threading import Event
from unittest.mock import AsyncMock
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="influence-sources-") as tmp:
        temp_instance_dir = str(Path(tmp) / "instance")
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = temp_instance_dir
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(temp_instance_dir)
        from app.core import config, db
        config_path = Path(tmp) / "config.json"
        config_path.write_text(json.dumps({"packages": {"enabled": "talk_to,send_message"}}))
        config.load(config_path)
        db.init_schema()
        from app.core.db import get_connection, transaction
        from app.core.stat_sources import (
            StatSourceCollector, bind_stat_sources, collect_stat_source,
            source_from_utterance, source_from_dm,
        )
        from app.core.perception import record_utterance
        from app.models.chat import get_chat_history, save_direct_message
        from app.core.agent_inbox import load_unread_messages
        from app.core.timeutils import set_game_factor, set_game_time
        from app.core.game_time import GameTime
        set_game_factor(0)
        set_game_time(GameTime.parse("Y0001-D001T12:00:00"))
        names = ("Sender", "Receiver", "Bystander")
        with transaction() as conn:
            for name in names:
                conn.execute(
                    "INSERT INTO characters (name,template,profile_json,config_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                    (name, "human-roleplay", "{}", "{}", "", ""),
                )
                conn.execute(
                    "INSERT INTO character_state (character_name,current_location,current_room) VALUES (?,?,?)",
                    (name, "fixture", "room"),
                )
        with patch("app.core.perception._resolve_presence", return_value=(list(names), [], [])), patch(
                "app.core.perception.inattentive_listeners", return_value=()), patch(
                "app.models.account.is_player_controlled", side_effect=lambda name: name == "Receiver"):
            uid = record_utterance(speaker="Sender", content="You can do it.", volume="whisper",
                                   addressees=["Receiver"], location_id="fixture", room_id="room")
            assert uid is not None
            source = source_from_utterance(uid)
            assert source is not None and source.event_id == f"room:{uid}"
            assert source.actor == "Sender" and source.content == "You can do it."
            assert "Receiver" in source.allowed_targets and "Bystander" not in source.allowed_targets
            assert source.avatar_targets == ("Receiver",)
            assert source.avatar_audience == ("Receiver",)
        # Role/audience belong to the recorded event, not a future lookup.
        with patch("app.models.account.is_player_controlled", return_value=False):
            reloaded = source_from_utterance(uid)
            assert reloaded is not None and reloaded.avatar_targets == ("Receiver",)
            assert reloaded.avatar_audience == ("Receiver",)
        assert source_from_utterance(9999999) is None
        collector = StatSourceCollector()
        with bind_stat_sources(collector):
            collect_stat_source(source)
            collect_stat_source(source)
        assert collector.snapshot() == (source,)

        metadata = {"image": "/fixture/reference.png", "game_ts": "Y0001-D001T11:30:00"}
        event = save_direct_message("Sender", "Receiver", "Keep going.", metadata=metadata)
        assert event and event.startswith("dm:")
        for character, partner, role in (("Sender", "Receiver", "assistant"), ("Receiver", "Sender", "user")):
            row = get_chat_history(character, partner_name=partner, medium="messaging")[-1]
            assert row["role"] == role and row["speaker"] == "Sender"
            assert row["metadata"]["image"] == metadata["image"]
            assert row["metadata"]["game_ts"] == metadata["game_ts"]
            assert row["channel_message_id"] == event.removeprefix("dm:")
        dm = source_from_dm(event)
        assert dm is not None and dm.actor == "Sender" and dm.allowed_targets == ("Receiver",)
        assert source_from_dm("dm:missing") is None
        other = save_direct_message("Bystander", "Receiver", "Take a breath.")
        assert other and other != event
        incoming = load_unread_messages("Receiver")
        assert set(incoming) == {"Sender", "Bystander"}
        assert incoming["Sender"][-1]["speaker"] == "Sender"
        assert incoming["Sender"][-1]["channel_message_id"] == event.removeprefix("dm:")
        assert incoming["Bystander"][-1]["channel_message_id"] == other.removeprefix("dm:")
        stamped = get_chat_history("Bystander", partner_name="Receiver", medium="messaging")[-1]
        assert stamped["metadata"]["game_ts"] == "Y0001-D001T12:00:00"

        before = get_connection().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        attempted_mirrors = []
        get_connection().create_function("fixture_mirror_attempt", 1, attempted_mirrors.append)
        with transaction() as conn:
            conn.execute("CREATE TEMP TRIGGER reject_second_mirror BEFORE INSERT ON chat_messages "
                         "BEGIN SELECT fixture_mirror_attempt(NEW.character_name); "
                         "SELECT CASE WHEN NEW.character_name='Sender' "
                         "THEN RAISE(ABORT,'fixture second mirror rejection') END; END")
        assert save_direct_message("Sender", "Receiver", "Must not partially arrive.") is None
        assert attempted_mirrors == ["Receiver", "Sender"], attempted_mirrors
        assert get_connection().execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == before
        with transaction() as conn:
            conn.execute("DROP TRIGGER reject_second_mirror")
        # Exercise publication before a real state-changing inline tool. Only
        # the LLM and its tool boundary are controlled; the transcript is real.
        from app.core import chat_engine
        from app.core.stat_sources import ReplyReceipt
        moved = Event()

        def move_fixture(_raw):
            with transaction() as conn:
                conn.execute("UPDATE character_state SET current_room='other-room' WHERE character_name='Sender'")
            moved.set()

        context = {
            "llm": object(), "system_content": "fixture", "moment_content": "",
            "messages": [{"role": "user", "content": "Receiver: Please encourage me."}],
            "room_mode": True, "mode": "single", "tool_system_content": "", "tool_llm": None,
            "tools_dict": {"MoveFixture": move_fixture}, "tool_format": "tag",
            "deferred_tools": set(), "content_tools": set(), "medium": "in_person",
            "agent_config": {}, "user_display_name": "Receiver", "full_chat_history": [],
            "old_history": None,
        }
        queue = SimpleNamespace(submit=lambda **kwargs: SimpleNamespace(
            content='I believe in you. <tool name="MoveFixture">{}</tool>'))
        published = []

        def publish(text):
            new_id = record_utterance(speaker="Sender", content=text,
                                      addressees=["Receiver"], source="fixture")
            assert new_id is not None
            published.append(new_id)
            return ReplyReceipt(source_from_utterance(new_id))

        with patch.object(chat_engine, "build_chat_context", return_value=context), patch(
                "app.core.llm_queue.get_llm_queue", return_value=queue), patch(
                "app.core.memory_situational.build_situational_block", return_value=""), patch(
                "app.core.perception._resolve_presence", return_value=(list(names), [], [])), patch(
                "app.core.perception.inattentive_listeners", return_value=()), patch(
                "app.models.account.is_player_controlled", side_effect=lambda name: name == "Receiver"):
            text = chat_engine.run_chat_turn("", "Sender", "Receiver", "Please encourage me.",
                                             room_stream=[{"speaker": "Receiver"}], publish_reply=publish)
            assert text == "I believe in you." and moved.wait(3), text
            assert len(published) == 1
            actual = source_from_utterance(published[0])
            assert actual is not None and actual.room_id == "room"
            assert actual.avatar_targets == ("Receiver",)
            assert actual.avatar_audience == ("Receiver",)
            assert get_connection().execute(
                "SELECT current_room FROM character_state WHERE character_name='Sender'"
            ).fetchone()[0] == "other-room"
            queue.submit = lambda **kwargs: SimpleNamespace(content="SKIP")
            assert chat_engine.run_chat_turn(
                "", "Sender", "Receiver", "A quiet pause.", room_stream=[{"speaker": "Receiver"}],
                respond_opportunity=True, publish_reply=publish) == ""
            assert len(published) == 1
        run_turn_regressions(Path(tmp), names)
        print("PASS influence sources: perceived whisper audience, source roles, canonical DM mirrors, metadata, inbox identities and atomic rejection")


def run_turn_regressions(root, names):
    """Exercise real producers, post-processing, extraction and SQLite writes."""
    from app.core import chat_engine, dependencies, llm_queue
    from app.core import llm_router, prompt_templates, streaming, thoughts
    from app.core.agent_loop import AgentLoop
    from app.core.db import get_connection, transaction
    from app.core.perception import record_utterance
    from app.core.stat_rules import save_setting
    from app.core.stat_sources import source_from_dm, source_from_utterance
    from app.models import account, character, character_template, rules
    from app.models.chat_stat_evaluations import has_evaluation
    real_is_player_controlled = account.is_player_controlled

    stat = "fixture_source_signal"
    template = {
        "id": "demo-source-template", "name": "Synthetic source template",
        "features": {"status_effects_enabled": True, "relationships_enabled": False,
                     "memory_enabled": False, "intents_enabled": True},
        "sections": [{"fields": [
            {"key": stat, "label": "Fixture source signal", "store": "status_effects"},
        ]}],
    }
    shared_rules = root / "source-shared-rules.json"
    shared_rules.write_text('{"rules": []}', encoding="utf-8")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    manager = dependencies.get_skill_manager()
    talk = manager.get_skill("talk_to")
    message = manager.get_skill("send_message")
    assert talk is not None and message is not None
    loop = AgentLoop()
    llm = object()
    instance = SimpleNamespace(model="fixture", provider_name="fixture",
                               create_llm=lambda **kwargs: llm)
    reply = [""]
    queue = SimpleNamespace(
        submit=lambda **kwargs: SimpleNamespace(content=reply[0]),
        register_chat_active_async=AsyncMock(side_effect=lambda *args, overflow=False, **kwargs:
                                            ("fixture", instance) if overflow else "fixture"),
        register_chat_done=lambda task_id: None,
    )
    phase_done = Event()
    extraction_started = Event()
    calls = []
    phases = []
    rendered = {}
    real_render_task = prompt_templates.render_task
    real_post_process = chat_engine.post_process_response

    def capture_render(task, **kwargs):
        if task == "extraction_chat_state":
            rendered.clear()
            rendered.update(kwargs)
        return real_render_task(task, **kwargs)

    def model_boundary(**kwargs):
        assert kwargs["task"] == "extraction_chat_state", kwargs["task"]
        calls.append(kwargs)
        extraction_started.set()
        sources = {source["id"]: source for source in rendered.get("stat_sources", [])}
        result = {
            "pose": "", "detail": "", "removed": [],
            "stat_results": [
                dict(pair, deltas={stat: 2} if sources[pair["event"]]["actor"] else {})
                for pair in rendered.get("required_stat_pairs", [])
            ],
        }
        return SimpleNamespace(content=json.dumps(result))

    def observe_post_process(*args, **kwargs):
        phases.append(kwargs.get("extraction_context") or {})
        try:
            return real_post_process(*args, **kwargs)
        finally:
            phase_done.set()

    def value(name):
        return character.get_character_profile(name, strict=True)["status_effects"][stat]

    def latest_dm():
        row = get_connection().execute(
            "SELECT channel_message_id FROM chat_messages "
            "WHERE character_name='Sender' AND json_extract(metadata,'$.medium')='messaging' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row and row[0]
        return source_from_dm(f"dm:{row[0]}")

    def source_tool(skill):
        def invoke(raw):
            data = json.loads(raw)
            data["agent_name"] = "Sender"
            return skill.execute(json.dumps(data))
        return invoke

    def run_chat(raw, tools=None, deferred=(), publish=None, **kwargs):
        reply[0] = raw
        context = {
            "llm": llm, "system_content": "fixture", "moment_content": "",
            "messages": [{"role": "user", "content": "Bystander: A real conversation."}],
            "room_mode": True, "mode": "single", "tool_system_content": "", "tool_llm": None,
            "tools_dict": tools or {}, "tool_format": "tag", "deferred_tools": set(deferred),
            "content_tools": set(), "medium": "in_person", "agent_config": {},
            "user_display_name": "", "full_chat_history": [], "old_history": [],
        }
        with patch.object(chat_engine, "build_chat_context", return_value=context):
            return chat_engine.run_chat_turn(
                "", "Sender", "Bystander", "A real conversation.", post_process=True,
                room_stream=[{"speaker": "Bystander"}], publish_reply=publish, **kwargs)

    async def run_thought(skill=None, prose="", markers=""):
        class ControlledAgent:
            def __init__(self, **kwargs):
                pass

            async def stream(self, system, history, user):
                if skill is not None:
                    result = await self.tool_executor(skill.name, json.dumps({
                        "to": "Receiver", "name": "Receiver",
                        "message": "A real thought-tool encouragement.",
                    }))
                    yield streaming.ToolResultEvent(skill.name, result)
                if prose:
                    yield streaming.ContentEvent(prose)
                if markers:
                    yield streaming.ExtractionEvent(markers)

        with patch.object(manager, "get_agent_tools",
                          return_value=[skill.as_tool()] if skill else []), \
                patch.object(dependencies, "determine_mode", return_value="single"), \
                patch.object(streaming, "StreamingAgent", ControlledAgent):
            return await thoughts.ThoughtRunner().run_thought_turn(
                "Sender", system_prompt_override="Stable pre-rendered fixture",
                suppress_notification=True)

    class SourceRegressions(unittest.TestCase):
        def setUp(self):
            phase_done.clear()
            extraction_started.clear()
            calls.clear()
            phases.clear()
            with transaction() as conn:
                conn.execute("DELETE FROM chat_stat_evaluations")
                conn.execute("DELETE FROM chat_messages")
                conn.execute("DELETE FROM perceptions")
                conn.execute("DELETE FROM utterances")
                conn.execute("DELETE FROM intents")
                conn.execute("DELETE FROM mood_history")
            for name in names:
                assert character.save_character_profile(name, {
                    "template": template["id"], "status_effects": {stat: 50},
                    "current_location": "fixture", "current_room": "room",
                })
                character.set_outfit_locked(name, True)
                assert character.save_character_config(name, {})
            save_setting("chat_cap_per_hour", 100)
            rules.save_rules([])

        def assert_delivered(self, source, recipient="Receiver"):
            self.assertIsNotNone(source)
            self.assertEqual(value(recipient), 52)
            self.assertTrue(has_evaluation(source.event_id, recipient))
            self.assertEqual(len(calls), 1, "All source pairs share one state-extraction phase")

        def test_room_without_valid_full_role_snapshot_is_not_a_stat_source(self):
            from app.models import perception_store
            uid = record_utterance(
                speaker="Sender", content="This remains ordinary perceived speech.",
                addressees=[], location_id="fixture", room_id="room")
            self.assertIsNotNone(uid)
            original = json.loads(get_connection().execute(
                "SELECT meta FROM utterances WHERE id=?", (uid,)).fetchone()[0])
            invalid_audiences = (None, False, "Receiver", [None], [""],
                                 ["Receiver", "Receiver"], ["missing-character"])
            snapshots = [dict(original, stat_avatar_audience=value) for value in invalid_audiences]
            old_snapshot = dict(original)
            del old_snapshot["stat_avatar_audience"]
            snapshots.append(old_snapshot)
            contradictory = dict(original, stat_avatar_audience=[], stat_avatar_targets=["Receiver"])
            snapshots.append(contradictory)
            for snapshot in snapshots:
                with self.subTest(snapshot=snapshot):
                    with transaction() as conn:
                        conn.execute("UPDATE utterances SET meta=? WHERE id=?",
                                     (json.dumps(snapshot), uid))
                    # A malformed/old event must not consult current avatar
                    # roles to infer that an unrecorded listener was an NPC.
                    with patch.object(account, "is_player_controlled",
                                      side_effect=AssertionError("Live role inference is forbidden")):
                        self.assertIsNone(source_from_utterance(uid))
                    rows = perception_store.get_character_room_stream("Receiver", "fixture", "room")
                    heard = [row for row in rows if row["utterance_id"] == uid]
                    self.assertEqual(len(heard), 1)
                    self.assertEqual(heard[0]["content"], "This remains ordinary perceived speech.")
                    self.assertFalse(has_evaluation(f"room:{uid}", "Receiver"))
                    self.assertEqual(value("Receiver"), 50)

        def test_autochime_uses_the_persisted_perception_source(self):
            uid = record_utterance(
                speaker="Sender", content="You have reason to feel encouraged.",
                addressees=["Bystander"], location_id="fixture", room_id="room")
            self.assertIsNotNone(uid)
            chime = loop._maybe_active_conversation_chime("Bystander")
            self.assertIsNotNone(chime)
            reply[0] = "I can carry on with renewed confidence."
            context = {
                "llm": llm, "system_content": "fixture", "moment_content": "",
                "messages": [{"role": "user", "content": "Sender: An encouragement."}],
                "room_mode": True, "mode": "single", "tools_dict": {}, "medium": "in_person",
                "tool_system_content": "", "tool_llm": None, "agent_config": {},
                "user_display_name": "", "full_chat_history": [], "old_history": [],
            }
            chime["cascade"] = False
            with patch.object(chat_engine, "build_chat_context", return_value=context):
                asyncio.run(loop._run_respond_turn("Bystander", chime))
            self.assertTrue(phase_done.wait(3), "The real respond follow-up did not finish")
            self.assert_delivered(source_from_utterance(uid), "Bystander")
            self.assertEqual(chime.get("utterance_id"), uid)

        def test_released_unaddressed_avatar_cannot_gain_an_old_room_evaluation(self):
            from app.core import users
            user_id = users.create_user(
                "demo", "fixture-password", allowed_characters=["Receiver"])
            self.assertTrue(users.update_user(user_id, settings={"active_character": "Receiver"}))
            try:
                # Use the actual persisted user-role resolver, overriding this
                # suite's ordinary fixed-role boundary for publication/consumer.
                with patch.object(account, "is_player_controlled", real_is_player_controlled):
                    self.assertTrue(account.is_player_controlled("Receiver"))
                    self.assertFalse(account.is_player_controlled("Bystander"))
                    direct_id = record_utterance(
                        speaker="Sender", content="A directly addressed encouragement.",
                        addressees=["Receiver"], location_id="fixture", room_id="room")
                    direct = source_from_utterance(direct_id)
                    self.assertIsNotNone(direct)
                    self.assertEqual(direct.avatar_targets, ("Receiver",))

                    uid = record_utterance(
                        speaker="Sender", content="An encouragement for the whole room.",
                        addressees=[], location_id="fixture", room_id="room")
                    heard_as_avatar = source_from_utterance(uid)
                    self.assertIsNotNone(heard_as_avatar)
                    self.assertIn("Receiver", heard_as_avatar.allowed_targets,
                                  "The unaddressed avatar really heard full content")
                    self.assertEqual(heard_as_avatar.avatar_targets, (),
                                     "Hearing a room line is not direct avatar addressing")
                    self.assertTrue(users.update_user(user_id, settings={
                        "active_character": "", "current_character": ""}))
                    self.assertFalse(account.is_player_controlled("Receiver"),
                                     "The real stored user role must actually change")

                    def respond_to_latest(answer):
                        phase_done.clear()
                        calls.clear()
                        phases.clear()
                        reply[0] = answer
                        chime = loop._maybe_active_conversation_chime("Receiver")
                        self.assertIsNotNone(chime)
                        chime["cascade"] = False
                        context = {
                            "llm": llm, "system_content": "fixture", "moment_content": "",
                            "messages": [{"role": "user", "content": "Sender: Room speech."}],
                            "room_mode": True, "mode": "single", "tools_dict": {},
                            "medium": "in_person", "tool_system_content": "", "tool_llm": None,
                            "agent_config": {}, "user_display_name": "",
                            "full_chat_history": [], "old_history": [],
                        }
                        with patch.object(chat_engine, "build_chat_context", return_value=context):
                            asyncio.run(loop._run_respond_turn("Receiver", chime))
                        self.assertTrue(phase_done.wait(3))
                        return chime

                    chime = respond_to_latest("I acknowledge what I heard in the room.")
                    self.assertEqual(chime["utterance_id"], uid)
                    self.assertEqual(value("Receiver"), 50,
                                     "Avatar release must not retroactively authorize NPC stats")
                    self.assertFalse(has_evaluation(f"room:{uid}", "Receiver"),
                                     "No evaluation receipt is allowed for that publication-time avatar")
                    frozen = source_from_utterance(uid)
                    self.assertIsNotNone(frozen)
                    self.assertEqual(frozen.avatar_targets, ())
                    self.assertEqual(frozen.avatar_audience, ("Receiver",))
                    direct_after = source_from_utterance(direct_id)
                    self.assertIsNotNone(direct_after)
                    self.assertEqual(direct_after.avatar_targets, ("Receiver",))
                    self.assertEqual(direct_after.avatar_audience, ("Receiver",))

                    # The released character is genuinely an NPC for NEW events:
                    # the same real consumer must still accept its next source.
                    new_uid = record_utterance(
                        speaker="Sender", content="A new encouragement after release.",
                        addressees=[], location_id="fixture", room_id="room")
                    self.assertIsNotNone(new_uid)
                    next_chime = respond_to_latest("I can now continue with renewed confidence.")
                    self.assertEqual(next_chime["utterance_id"], new_uid)
                    self.assert_delivered(source_from_utterance(new_uid))
                    self.assertFalse(has_evaluation(f"room:{uid}", "Receiver"))
            finally:
                self.assertTrue(users.delete_user(user_id))

        def test_tool_only_chat_delivers_talk_to_without_a_reply_source(self):
            raw = f'<tool name="{talk.name}">{{"to":"Receiver","message":"You can do it."}}</tool>'
            self.assertEqual(run_chat(raw, {talk.name: source_tool(talk)}), "")
            self.assertTrue(phase_done.wait(3), "Published tool-only speech lost its extraction")
            row = get_connection().execute(
                "SELECT id FROM utterances WHERE speaker='Sender' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assert_delivered(source_from_utterance(row[0]))
            self.assertTrue(phases[0]["stat_only"])
            self.assertEqual(len(phases[0]["stat_context"].sources), 1,
                             "Silence must not fabricate a reply/self source")

        def test_two_outgoing_sources_share_one_source_only_phase(self):
            raw = (
                f'<tool name="{talk.name}">{{"to":"Receiver","message":"You can do it."}}</tool>'
                f'<tool name="{message.name}">{{"to":"Receiver","message":"I believe in you."}}</tool>')
            self.assertEqual(run_chat(raw, {
                talk.name: source_tool(talk), message.name: source_tool(message),
            }), "")
            self.assertTrue(phase_done.wait(3))
            row = get_connection().execute(
                "SELECT id FROM utterances WHERE speaker='Sender' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
            room_source, dm_source = source_from_utterance(row[0]), latest_dm()
            self.assertIsNotNone(room_source)
            self.assertIsNotNone(dm_source)
            self.assertEqual(value("Receiver"), 54, "Two real +2 communications must both apply")
            self.assertTrue(has_evaluation(room_source.event_id, "Receiver"))
            self.assertTrue(has_evaluation(dm_source.event_id, "Receiver"))
            self.assertEqual(len(calls), 1, "Source count must not multiply model rounds")
            self.assertEqual(len(phases), 1)
            self.assertEqual(len(phases[0]["stat_context"].sources), 2)

        def test_empty_thought_delivers_the_actual_dm(self):
            asyncio.run(run_thought(message, ""))
            self.assertTrue(phase_done.wait(3), "Empty private prose lost its published DM")
            self.assert_delivered(latest_dm())
            self.assertTrue(phases[0]["stat_only"])
            self.assertEqual(len(phases[0]["stat_context"].sources), 1)

        def test_skip_thought_delivers_the_actual_talk_to(self):
            asyncio.run(run_thought(talk, "SKIP"))
            self.assertTrue(phase_done.wait(3), "SKIP private prose lost its published speech")
            row = get_connection().execute(
                "SELECT id FROM utterances WHERE speaker='Sender' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assert_delivered(source_from_utterance(row[0]))
            self.assertTrue(phases[0]["stat_only"])
            self.assertEqual(len(phases[0]["stat_context"].sources), 1)

        def marker_fixture(self):
            from app.models import intents
            assert character.save_character_config("Sender", {"mood_tracking": True})
            completed = intents.create_intent(owner="Sender", title="Finish the fixture inventory")
            progressing = intents.create_intent(owner="Sender", title="Read the fixture journal")
            self.assertTrue(completed and progressing)
            markers = (
                "[INTENT: Visit the fixture library | Check the notice board | when=standing | by=self]\n"
                f"[INTENT_DONE: {completed['id']}]\n"
                f"[INTENT_PROGRESS: {progressing['id']} | Read the fixture introduction]\n"
                "**I feel hopeful**")
            return markers, completed["id"], progressing["id"]

        def assert_marker_effects_once(self, completed, progressing):
            from app.models import intents
            self.assertEqual(intents.get_intent(completed)["status"], "done")
            progress = intents.get_intent(progressing)
            self.assertEqual(progress["status"], "active")
            self.assertEqual([entry["note"] for entry in
                              progress["participants"]["Sender"]["progress"]],
                             ["Read the fixture introduction"])
            created = [intent for intent in intents.list_intents(owner="Sender")
                       if intent["title"] == "Visit the fixture library"]
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0]["status"], "active")
            self.assertEqual(created[0]["source"], "character")
            self.assertEqual(len(intents.list_intents(owner="Sender")), 3)
            self.assertEqual(character.get_character_profile("Sender")["current_feeling"], "hopeful")
            moods = get_connection().execute(
                "SELECT mood FROM mood_history WHERE character_name='Sender' ORDER BY id"
            ).fetchall()
            self.assertEqual([row[0] for row in moods], ["hopeful"],
                             "Repeated deterministic post-processing would duplicate mood history")
            self.assertEqual(len(phases), 1, "The authoritative postprocessor must run once")

        def test_marker_only_thought_keeps_explicit_work_without_stat_round(self):
            markers, completed, progressing = self.marker_fixture()
            asyncio.run(run_thought(None, markers))
            self.assert_marker_effects_once(completed, progressing)
            self.assertEqual(calls, [], "Pure markers must not synthesize an LLM state round")
            self.assertIsNone(phases[0].get("stat_context"))
            self.assertEqual(get_connection().execute(
                "SELECT COUNT(*) FROM chat_stat_evaluations").fetchone()[0], 0)
            self.assertEqual(value("Sender"), 50)

        def test_skip_plus_markers_keeps_explicit_work_without_outgoing_source(self):
            markers, completed, progressing = self.marker_fixture()
            asyncio.run(run_thought(None, "SKIP", markers))
            self.assert_marker_effects_once(completed, progressing)
            self.assertEqual(calls, [])
            self.assertIsNone(phases[0].get("stat_context"))
            self.assertEqual(get_connection().execute(
                "SELECT COUNT(*) FROM chat_stat_evaluations").fetchone()[0], 0)
            self.assertEqual(value("Sender"), 50)

        def test_skip_markers_and_real_delivery_keep_both_effects_in_one_phase(self):
            markers, completed, progressing = self.marker_fixture()
            # The same marker may occur in RP and Tool-LLM output; existing
            # thought merging must still route it through the one parser.
            asyncio.run(run_thought(message, "SKIP\n" + markers, markers))
            self.assert_marker_effects_once(completed, progressing)
            self.assert_delivered(latest_dm())
            self.assertEqual(len(phases[0]["stat_context"].sources), 1,
                             "SKIP and deterministic markers are not private RP sources")
            self.assertEqual(rendered["source_text"], "",
                             "Do not feed SKIP, old history or marker text to narrative inference")
            self.assertEqual(value("Sender"), 50)

        def test_markers_survive_delivery_without_eligible_target_stats(self):
            markers, completed, progressing = self.marker_fixture()
            assert character.save_character_config("Receiver", {"status_effects_enabled": False})
            asyncio.run(run_thought(message, "SKIP", markers))
            self.assert_marker_effects_once(completed, progressing)
            self.assertIsNotNone(latest_dm(), "The real communication must still be delivered")
            self.assertEqual(calls, [], "Marker handling is independent of stat target eligibility")
            self.assertIsNone(phases[0].get("stat_context"))
            self.assertEqual(value("Receiver"), 50)

        def test_skip_without_outgoing_delivery_does_not_extract_incoming_context(self):
            from app.models.chat import save_direct_message
            incoming = save_direct_message("Bystander", "Sender", "An unread real incoming DM.")
            self.assertIsNotNone(incoming)
            asyncio.run(run_thought(None, "SKIP"))
            self.assertEqual(calls, [])
            self.assertEqual(phases, [])
            self.assertEqual(value("Sender"), 50)
            self.assertFalse(has_evaluation(incoming, "Sender"))

        def test_refused_tool_only_speech_does_not_start_extraction(self):
            with transaction() as conn:
                conn.execute("UPDATE character_state SET current_room='other-room' "
                             "WHERE character_name='Receiver'")
            raw = f'<tool name="{talk.name}">{{"to":"Receiver","message":"Not delivered."}}</tool>'
            self.assertEqual(run_chat(raw, {talk.name: source_tool(talk)}), "")
            self.assertEqual(calls, [])
            self.assertEqual(phases, [])
            self.assertEqual(value("Receiver"), 50)
            self.assertEqual(get_connection().execute("SELECT COUNT(*) FROM utterances").fetchone()[0], 0)

        def test_published_source_without_enabled_stats_does_not_start_extraction(self):
            assert character.save_character_config("Receiver", {"status_effects_enabled": False})
            asyncio.run(run_thought(message, "SKIP"))
            self.assertIsNotNone(latest_dm(), "The outgoing communication must really be delivered")
            self.assertEqual(calls, [])
            self.assertEqual(phases, [])
            self.assertEqual(value("Receiver"), 50)

        def test_deferred_speech_finishes_before_the_normal_immutable_snapshot(self):
            started, release, finished = Event(), Event(), Event()
            publications = []

            def deferred_speech(raw):
                try:
                    started.set()
                    assert release.wait(3), "Fixture did not release the real publisher"
                    return source_tool(message)(raw)
                finally:
                    finished.set()

            def publish(text):
                from app.core.stat_sources import ReplyReceipt
                uid = record_utterance(speaker="Sender", content=text,
                                       addressees=["Bystander"], source="fixture")
                publications.append(uid)
                return ReplyReceipt(source_from_utterance(uid))

            raw = ('I send an encouraging message while we continue talking. '
                   f'<tool name="{message.name}">{{"to":"Receiver","message":"Keep going."}}</tool>')
            try:
                self.assertTrue(run_chat(raw, {message.name: deferred_speech},
                                         {message.name}, publish))
                self.assertEqual(len(publications), 1, "The normal answer is already public")
                self.assertTrue(started.wait(3))
                self.assertFalse(extraction_started.wait(.15),
                                 "Extraction raced ahead of the source-producing deferred worker")
            finally:
                release.set()
                self.assertTrue(finished.wait(3), "The fixture publisher did not finish")
                self.assertTrue(phase_done.wait(3), "The follow-up worker did not finish")
            self.assertTrue(phase_done.wait(3), "Deferred source follow-up did not finish")
            self.assert_delivered(latest_dm())
            self.assertEqual(len(phases), 1, "Normal prose must not cause a second extraction phase")

        def test_unrelated_media_defer_does_not_hold_the_stat_snapshot(self):
            started, release, finished = Event(), Event(), Event()

            def media(_raw):
                try:
                    started.set()
                    assert release.wait(3), "Fixture did not release unrelated media"
                    return "Fixture media complete"
                finally:
                    finished.set()

            raw = ('I quietly send a message and arrange a later picture. '
                   f'<tool name="{message.name}">{{"to":"Receiver","message":"Keep going."}}</tool>'
                   '<tool name="FixtureMedia">{}</tool>')
            try:
                self.assertTrue(run_chat(
                    raw, {message.name: source_tool(message), "FixtureMedia": media},
                    {message.name, "FixtureMedia"}))
                self.assertTrue(started.wait(3), "The unrelated worker must really be running")
                self.assertTrue(phase_done.wait(2), "Unrelated media held the state-extraction phase")
                self.assert_delivered(latest_dm())
            finally:
                release.set()
                self.assertTrue(finished.wait(3))

        def test_failed_speech_worker_releases_the_normal_extraction_phase(self):
            def fail(_raw):
                raise RuntimeError("Fixture speech failure before publication")

            raw = ('I reconsider what to say while staying in the conversation. '
                   f'<tool name="{message.name}">{{"to":"Receiver","message":"Not delivered."}}</tool>')
            self.assertTrue(run_chat(raw, {message.name: fail}, {message.name}))
            self.assertTrue(phase_done.wait(3), "Failed speech left the source barrier closed")
            self.assertEqual(value("Receiver"), 50)
            self.assertEqual(len(calls), 1)
            self.assertEqual([source.medium for source in phases[0]["stat_context"].sources], ["self"])

        def test_worker_start_failure_releases_its_registered_source_work(self):
            from threading import Thread
            from app.core.stat_sources import StatSourceCollector, bind_stat_sources
            collector = StatSourceCollector()
            context = {"tools_dict": {message.name: source_tool(message)},
                       "deferred_tools": {message.name}, "medium": "in_person"}
            with bind_stat_sources(collector), patch.object(
                    Thread, "start", side_effect=RuntimeError("Fixture worker start failure")):
                chat_engine.execute_tool_matches(
                    context, "Sender", [(message.name, '{"to":"Receiver","message":"Not delivered."}')],
                    rp_text="", incoming_message="")
            completed = Event()

            def wait_for_sources():
                collector.wait_for_source_work()
                completed.set()

            waiter = Thread(target=wait_for_sources, daemon=True)
            waiter.start()
            self.assertTrue(completed.wait(3), "Thread.start failure left a pending source completion")
            waiter.join()
            self.assertEqual(collector.snapshot(), ())
            self.assertEqual(value("Receiver"), 50)

    with ExitStack() as stack:
        stack.enter_context(patch.object(character_template, "get_template", return_value=template))
        stack.enter_context(patch.object(character_template, "list_templates", return_value=[
            {"id": template["id"], "name": template["name"]}]))
        stack.enter_context(patch.object(rules, "_get_shared_rules_path", return_value=shared_rules))
        stack.enter_context(patch("app.models.account.is_player_controlled",
                                 side_effect=lambda name: name == "Receiver"))
        stack.enter_context(patch("app.models.account.get_active_character", return_value=""))
        stack.enter_context(patch("app.core.perception._resolve_presence",
                                 return_value=(list(names), [], [])))
        stack.enter_context(patch("app.core.perception.inattentive_listeners", return_value=()))
        stack.enter_context(patch("app.core.agent_loop.get_agent_loop", return_value=loop))
        stack.enter_context(patch.object(llm_queue, "get_llm_queue", return_value=queue))
        stack.enter_context(patch.object(llm_router, "resolve_llm", return_value=instance))
        stack.enter_context(patch.object(llm_router, "llm_call", side_effect=model_boundary))
        stack.enter_context(patch.object(prompt_templates, "render_task", side_effect=capture_render))
        stack.enter_context(patch.object(chat_engine, "post_process_response",
                                        side_effect=observe_post_process))
        stack.enter_context(patch.object(chat_engine, "run_follow_up",
                                        side_effect=lambda callback, *args, **kwargs: callback(*args)))
        stack.enter_context(patch.object(thoughts, "thought_anti_repetition_overrides", return_value={}))
        stack.enter_context(patch("app.core.memory_situational.build_situational_block", return_value=""))
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SourceRegressions)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        assert result.wasSuccessful(), "Influence source producer/state regressions failed"


if __name__ == "__main__":
    main()
