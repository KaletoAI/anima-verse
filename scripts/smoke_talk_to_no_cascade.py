#!/usr/bin/env python3
"""TalkTo pacing smoke; usage: ./.venv/bin/python scripts/smoke_talk_to_no_cascade.py.

Hand-derived: Kira addressing Lukas queues cascade=False. His "Hallo Kira."
is recorded once, consumes zero room hops, dispatches zero reactions, and
leaves Kira's priority queue empty with exactly one ordinary-thought hint:
Lukas answered what you said to them: "Hallo Kira."
400 reply characters become 300 plus …; an avatar/temp sender gets no hint.
Default room speech consumes one hop and dispatches once to Kira.
Retained mandatory/on-demand entries retain their cascade; replacements take
the new value. add_hint and bump accumulate hints with one newline.
All world imports follow paths.init(tmp); no server or LLM is called.
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TEMP = tempfile.TemporaryDirectory(prefix="talkto-no-cascade-")
from app.core import paths
paths.init(Path(_TEMP.name))
from app.core import config, db
config.load(Path(_TEMP.name) / "config.json")
db.init_schema()
from app.core import agent_loop as al, chat_engine, perception
from app.models import character, world
from app.plugins.context import PluginContext
from plugins.talk_to.skill import TalkToSkill


class Pacing(unittest.TestCase):
    def test_talkto(self):
        loc = world.add_location("Bathhouse", "", rooms=[
            {"id": "pool", "name": "Pool"}])["id"]
        for name in ("Kira", "Lukas"):
            character.save_character_profile(name, {
                "character_name": name, "template": "human-roleplay"}, create_new=True)
            character.save_character_current_location(name, loc)
            character.save_character_current_room(name, "pool")
        loop = al.AgentLoop()
        with patch.object(al, "_agent_loop", loop):
            result = TalkToSkill({"enabled": True}, PluginContext("talk_to")).execute(
                json.dumps({"agent_name": "Kira", "name": "Lukas", "message": "Hallo."}))
        self.assertTrue(result.startswith("Spoke to Lukas"), result)
        self.assertIs(loop._respond_to["Lukas"]["cascade"], False)

    def test_handler(self):
        async def inline_worker(func, *args, **kwargs):
            return func(*args, **kwargs)

        def chat_turn(*args, publish_reply, **kwargs):
            # The real chat turn publishes through the handler's callback.
            publish_reply(reply)
            return reply

        for cascade, reply, eligible in [
                (False, "Hallo Kira.", True), (False, "x" * 400, True),
                (False, "Hallo Kira.", False), (True, "Hallo Kira.", True)]:
            with self.subTest(cascade=cascade, length=len(reply), eligible=eligible):
                loop = al.AgentLoop()
                loop._room_ai_turns["sentinel"] = 7
                before = dict(loop._room_ai_turns)
                with patch.object(asyncio, "to_thread", inline_worker), \
                        patch.object(al, "_is_respond_eligible", return_value=True), \
                        patch.object(al, "_is_agent_eligible", return_value=eligible), \
                        patch.object(chat_engine, "run_chat_turn", side_effect=chat_turn), \
                        patch.object(perception, "record_utterance",
                                     wraps=perception.record_utterance) as record, \
                        patch.object(loop, "dispatch_room_reactions") as dispatch:
                    self.assertTrue(loop.bump_respond(
                        "Lukas", "Kira", "Hallo.", **({"cascade": False} if not cascade else {})))
                    entry = loop._respond_to["Lukas"]
                    self.assertIs(entry["cascade"], cascade)
                    asyncio.run(loop._run_respond_turn("Lukas", entry))
                record.assert_called_once()
                self.assertEqual(record.call_args.kwargs["content"], reply)
                self.assertEqual(list(loop._bump_queue), [])
                if cascade:
                    dispatch.assert_called_once()
                    self.assertEqual(dispatch.call_args.kwargs["addressees"], ["Kira"])
                    self.assertEqual(sum(loop._room_ai_turns.values()), 8)
                    self.assertEqual(loop.pop_hint("Kira"), "")
                else:
                    dispatch.assert_not_called()
                    self.assertEqual(loop._room_ai_turns, before)
                    clipped = reply[:300] + "…" if len(reply) > 300 else reply
                    self.assertEqual(loop.pop_hint("Kira"),
                                     f'Lukas answered what you said to them: "{clipped}"'
                                     if eligible else "")
                    self.assertEqual(loop._bump_hints, {})

    def test_hints_and_retention(self):
        loop = al.AgentLoop()
        with patch.object(al, "_is_agent_eligible", return_value=True), \
                patch.object(al, "_is_respond_eligible", return_value=True):
            self.assertTrue(loop.add_hint("Kira", "first"))
            self.assertEqual(list(loop._bump_queue), [])
            loop.bump("Kira", hint="second")
            self.assertEqual(loop.pop_hint("Kira"), "first\nsecond")
            for protected in ({"obligatory": True}, {"on_demand": True}):
                loop._respond_to.clear()
                loop.bump_respond("Lukas", "Kira", "first", cascade=False, **protected)
                loop.bump_respond("Lukas", "Kira", "second", obligatory=False)
                self.assertFalse(loop._respond_to["Lukas"]["cascade"])
            loop.bump_respond("Lukas", "Kira", "third", on_demand=True)
            self.assertTrue(loop._respond_to["Lukas"]["cascade"])
        with patch.object(al, "_is_agent_eligible", return_value=False):
            self.assertFalse(loop.add_hint("Mara", "ignored"))
            self.assertNotIn("Mara", loop._bump_hints)


if __name__ == "__main__":
    unittest.main()
