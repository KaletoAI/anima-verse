#!/usr/bin/env python3
"""Thought focus smoke, without a server or LLM.

Usage: ./.venv/bin/python scripts/smoke_thought_focus.py

Hand-derived expectations: the five decisions occur once, before the final
instruction; intent completion syntax requires intent tracking. A tool-only
journal row becomes an action (a detail over 60 chars is cut at a word
boundary and marked …; element-style <x><detail>…</detail></x> calls count
too), prose loses tool syntax and mood/activity markers, and storage stays unchanged. Three equal tool sets at one place or
three tool-less turns form a rut; two turns, a changed set or place do not.
An isolated rut waits 20 SYSTEM minutes after its last turn; a bump bypasses
that wait, zero disables it, company/unknown presence prevents it, and a
broken rut releases it. These checks catch missing cleanup, incorrect window
or place comparisons, a sliding rest deadline and cooldown applied to bumps.
Presence: flavor is last after appearance and states; sleep overrides flavor,
pose_key is the fallback, no pose adds nothing, 100 chars become 80 plus …,
and the default chat path omits activity. Expectations are derived by hand.
All database imports follow paths.init in a temporary directory.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TEMP = tempfile.TemporaryDirectory(prefix="thought-focus-")
from app.core import paths
paths.init(Path(_TEMP.name))
from app.core import db
db.init_schema()
from app.core import thought_context as tc, agent_loop as al
from app.core.prompt_templates import _env, render
from app.models import thought_store
from jinja2 import meta


class Focus(unittest.TestCase):
    def test_presence_activity(self):
        cases = [
            ({"pose_flavor": "Schläft auf der Bank"}, "Schläft auf der Bank"),
            ({"is_sleeping": True, "pose_flavor": "ignored"}, "Sleeping"),
            ({"pose_key": "sitting"}, "sitting"), ({}, ""),
            ({"pose_flavor": "x" * 100}, "x" * 80 + "…"),
        ]
        for profile, expected in cases:
            with self.subTest(profile=profile), \
                    patch("app.models.character.get_character_profile", return_value=profile), \
                    patch("app.core.prompt_builder.person_description", return_value="appearance"), \
                    patch("app.core.prompt_filters.collect_image_modifiers",
                          return_value=([], ["relaxed shoulders"])), \
                    patch("app.core.outfit_renderer.uncovered_summary", return_value=""), \
                    patch.object(tc, "_room_presence", return_value=(["Lukas"], [])), \
                    patch("app.models.account.get_active_character", return_value=""):
                base = "- Lukas: appearance; looks: relaxed shoulders"
                block, elsewhere, alone = tc._build_presence("Kira", "demo", "room")
                self.assertEqual(block, base + ("; doing: " + expected if expected else ""))
                self.assertEqual((elsewhere, alone), ("", False))
                self.assertEqual(tc.present_people_details([("Lukas", "Lukas")]), base)

    def test_decisions(self):
        names = meta.find_undeclared_variables(_env.parse(
            _env.loader.get_source(_env, "chat/agent_thought.md")[0]))
        ctx = dict.fromkeys(names, "")
        ctx.update(character_name="demo", action_instruction="FINAL ACTION",
                   intent_tracking_enabled=False)
        out = render("chat/agent_thought.md", **ctx)
        self.assertEqual(out.count("=== What to do now ==="), 1)
        self.assertTrue(out.rstrip().endswith("FINAL ACTION"))
        positions = [out.index(f"{i}. ", out.index("=== What to do now ==="))
                     for i in range(1, 6)]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("[INTENT_DONE:", out)
        ctx["intent_tracking_enabled"] = True
        self.assertIn("[INTENT_DONE:", render("chat/agent_thought.md", **ctx))

    def test_handover(self):
        entries = [
            "<tools-call name=\"DemoAction\" args='{\"detail\":\"finished piece\"}'></tools-call>",
            '<tool name="DemoMessage">{"message":"sent"}</tool>',
            'I finished it. **I feel calm** **I do sit**',
        ]
        for i, text in enumerate(entries):
            self.assertTrue(thought_store.add_thought(
                "demo", text, ts=f"2026-10-18T10:0{i}:00+00:00"))
        self.assertEqual(tc.recent_thoughts_block("demo"),
                         "- (actions) DemoAction: finished piece\n"
                         "- (actions) DemoMessage: sent\n- I finished it.")
        self.assertEqual([row["content"] for row in thought_store.list_thoughts("demo")],
                         list(reversed(entries)))
        for text in ['Use DemoAction for: done', 'Ich nutze DemoAction für: done',
                     '<tool name="DemoAction">done</tool>',
                     '<tools-call name="DemoAction" args=\'{}\'></tools-call>']:
            with self.subTest(text=text), patch.object(thought_store, "list_thoughts",
                    return_value=[{"content": text}]):
                self.assertEqual(tc.recent_thoughts_block("demo"), "- (actions) DemoAction")
        with patch.object(thought_store, "list_thoughts", return_value=[
                {"content": '**I feel calm** **I do sit**'},
                {"content": 'Prose <tool name="DemoAction">{}</tool>'}]):
            self.assertEqual(tc.recent_thoughts_block("demo"), "- Prose")

    def test_handover_limits(self):
        from app.core.tool_formats import thought_handover
        raw = ('<tool name="DemoAction">{"detail":"' + "x" * 100
               + '"}</tool>\nUse DemoMessage for: {"target":"demo"}')
        # One 100-char word has no boundary inside the 60-char window: cut
        # hard at 60 and marked with "…".
        self.assertEqual(thought_handover(raw),
                         "(actions) DemoAction: " + "x" * 60 + "…; DemoMessage: demo")
        # Words: "stands in the changing room holding her things in both
        # hands" is exactly 60 chars and stays whole. With " today" (66
        # chars) char 60 is the space before "today": the window ends on a
        # word boundary, so "hands" stays and only "today" goes. With
        # "neatly" instead ("…in both neatly", 61 chars) the window ends
        # inside "neatly" (chars 55..60), so the cut falls back before it.
        base = "stands in the changing room holding her things in both hands"
        call = '<tool name="DemoAction">{"detail":"%s"}</tool>'
        self.assertEqual(thought_handover(call % base), "(actions) DemoAction: " + base)
        self.assertEqual(thought_handover(call % (base + " today")),
                         "(actions) DemoAction: " + base + "…")
        self.assertEqual(thought_handover(
            call % "stands in the changing room holding her things in both neatly"),
            "(actions) DemoAction: stands in the changing room holding her things in both…")
        # An element-style call no format parses: outer tag = action, the
        # <detail> child = its detail; surrounding prose wins over actions.
        self.assertEqual(thought_handover(
            "<activity><pose>lying</pose><detail>lies on the floor</detail></activity>"),
            "(actions) activity: lies on the floor")
        self.assertEqual(thought_handover(
            "I head out. <activity><pose>walking</pose><detail>to the door</detail></activity>"),
            "I head out.")
        self.assertEqual(thought_handover('I finished. <tool name="DemoAction">{}'),
                         "I finished.")
        with patch.object(thought_store, "list_thoughts", return_value=[
                {"content": "word " * 200}] * 3):
            block = tc.recent_thoughts_block("demo")
            self.assertLessEqual(len(block), tc.THOUGHT_RECENT_CHARS)
            self.assertEqual(len(block.splitlines()), 3)

    def test_rut(self):
        from app.core import thought_rut as rut
        with patch.object(rut, "_turns", {}):
            for i in range(2):
                rut.record_turn("demo", ["DemoAction", "DemoMessage"], ("demo", "room"))
                self.assertEqual(rut.rut_hint("demo"), "")
            rut.record_turn("demo", ["DemoMessage", "DemoAction", "DemoAction"], ("demo", "room"))
            self.assertIn("DemoAction, DemoMessage", rut.rut_hint("demo"))
            self.assertIn("SKIP", rut.rut_hint("demo"))
            rut.record_turn("demo", ["DemoAction"], ("demo", "room"))
            self.assertEqual(rut.rut_hint("demo"), "")
            for i in range(3):
                rut.record_turn("demo", [], ("demo", "room"))
            self.assertTrue(rut.rut_hint("demo"))
            rut.record_turn("demo", [], ("demo", "elsewhere"))
            self.assertEqual(rut.rut_hint("demo"), "")
            for i in range(3):
                rut.record_turn("demo", ["DemoAction"], ("demo", "room"))
            self.assertTrue(rut.rut_here("demo", ("demo", "room")))
            self.assertFalse(rut.rut_here("demo", ("elsewhere", "room")))
            rut.record_turn("demo", ["DemoAction"], ("elsewhere", "room"))
            self.assertEqual(rut.rut_hint("demo"), "")

    def test_runner_records_and_skip(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.core import thoughts, thought_rut as rut, streaming
        from app.core import dependencies, llm_router, llm_queue, chat_engine
        from app.models import character

        response = ["Done"]
        captured = []

        class Agent:
            def __init__(self, **kwargs):
                pass

            async def stream(self, system, history, user):
                captured.append((system, user))
                yield streaming.ContentEvent(response[0])
                if response[0] != "SKIP":
                    yield streaming.ToolResultEvent("DemoAction", "done")

        instance = SimpleNamespace(model="demo", provider_name="demo", create_llm=lambda **kw: object())
        manager = SimpleNamespace(get_agent_tools=lambda name, **_kw: [])
        # With overflow=True the registration also names the instance it
        # picked; this smoke never overflows to another model.
        queue = SimpleNamespace(register_chat_active_async=AsyncMock(
                                    side_effect=lambda *a, overflow=False, **kw:
                                    ("demo", instance) if overflow else "demo"),
                                register_chat_done=lambda task_id: None)
        profile = {"current_location": "demo", "current_room": "room"}

        async def inline_worker(func, *args, **kwargs):
            # Exercise the runner without the executor's thread lifecycle.
            return func(*args, **kwargs)

        with patch.object(asyncio, "to_thread", inline_worker), \
                patch.object(rut, "_turns", {}), \
                patch.object(character, "get_character_profile", return_value=profile), \
                patch.object(character, "get_character_config", return_value={}), \
                patch.object(dependencies, "get_skill_manager", return_value=manager), \
                patch.object(llm_router, "resolve_llm", return_value=instance), \
                patch.object(llm_queue, "get_llm_queue", return_value=queue), \
                patch.object(streaming, "StreamingAgent", Agent), \
                patch.object(chat_engine, "post_process_response", return_value={}), \
                patch.object(thoughts, "thought_anti_repetition_overrides", return_value={}):
            runner = thoughts.ThoughtRunner()
            for i in range(3):
                asyncio.run(runner.run_thought_turn(
                    "demo", system_prompt_override="STABLE", suppress_notification=True))
            self.assertTrue(rut.rut_hint("demo"))
            before = list(rut._turns["demo"])
            response[0] = "SKIP"
            result = asyncio.run(runner.run_thought_turn(
                "demo", context_hint="demo trigger", system_prompt_override="STABLE"))
            self.assertTrue(result["skipped"])
            self.assertEqual(list(rut._turns["demo"]), before)
            self.assertEqual(captured[-1][0], "STABLE")
            self.assertIn("Your last 3 turns", captured[-1][1])
            self.assertIn("demo trigger", captured[-1][1])

    def test_rest(self):
        from app.core import thought_rut as rut, config
        from app.core.timeutils import utc_now
        from datetime import timedelta
        loop = al.AgentLoop()
        now = utc_now()
        with patch.object(rut, "_turns", {}), patch.object(al, "utc_now", return_value=now), \
                patch.object(al, "_is_agent_eligible", return_value=True), \
                patch.object(al, "_build_round_tickets", side_effect=lambda: ["demo"]), \
                patch.object(al, "_get_per_char_cooldown_min", return_value=0), \
                patch.object(config, "get", return_value=20), \
                patch.object(tc, "_build_presence", return_value=("", "", True)), \
                patch("app.models.character.get_character_profile", return_value={
                    "current_location": "demo", "current_room": "room"}):
            for i in range(3):
                rut.record_turn("demo", ["DemoAction"], ("demo", "room"))
            loop._last_real_turn_at["demo"] = now - timedelta(minutes=6)
            with self.assertLogs("agent_loop", level="INFO") as logs:
                self.assertIsNone(loop._pick_next_agent())
                self.assertIsNone(loop._pick_next_agent())
            self.assertEqual(len(logs.output), 1)
            loop._bump_queue.append("demo")
            self.assertEqual(loop._pick_next_agent(), "demo")
            with patch.object(config, "get", return_value=0):
                self.assertEqual(loop._pick_next_agent(), "demo")
            for presence in [("company", "", False), ("", "", False)]:
                with patch.object(tc, "_build_presence", return_value=presence):
                    self.assertEqual(loop._pick_next_agent(), "demo")
            with patch("app.models.character.get_character_profile", return_value={
                    "current_location": "elsewhere", "current_room": "room"}):
                self.assertEqual(loop._pick_next_agent(), "demo")
            loop._last_real_turn_at["demo"] = now - timedelta(minutes=19)
            self.assertIsNone(loop._pick_next_agent())
            loop._last_real_turn_at["demo"] = now - timedelta(minutes=20)
            self.assertEqual(loop._pick_next_agent(), "demo")
            loop._last_real_turn_at["demo"] = now - timedelta(minutes=6)
            rut.record_turn("demo", ["DemoMessage"], ("demo", "room"))
            self.assertEqual(loop._pick_next_agent(), "demo")


if __name__ == "__main__":
    unittest.main()
