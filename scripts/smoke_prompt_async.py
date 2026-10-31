#!/usr/bin/env python3
"""Async prompt consumers keep semantic contracts without blocking the loop.

Run: ./.venv/bin/python scripts/smoke_prompt_async.py
Only private fixture roots are initialized, before world imports. No LLM,
provider, server or media work. A thread event holds real room composition
while an independent coroutine releases it; removing either async offload
makes that coroutine miss the rendezvous and the scenario fail.
"""
import asyncio
import ast
from contextvars import ContextVar
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Timer
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TEMP = tempfile.TemporaryDirectory(prefix="prompt-async-")
_ROOT = Path(_TEMP.name)
os.environ.update(STORAGE_DIR=str(_ROOT / "world"), INSTANCE_DIR=str(_ROOT / "instance"),
                  EVENT_ENTRY_ROLL_ENABLED="0")
from app.core import paths
paths.init(_ROOT / "world")
paths.init_instance(_ROOT / "instance")
from app.core import db, places, thought_context, prompt_templates
from app.core.game_time import GameTime
from app.core.timeutils import set_game_factor, set_game_time
from app.blender import refine, runner
refine.auto_retexture_enabled = lambda: False
refine.auto_lod_enabled = lambda: False
refine.auto_bake_vc_enabled = lambda: False
refine.measure_file = lambda path: None
runner.is_available = lambda: False
from app.core import props
from app.models import character as C, world as W
from jinja2 import meta

db.init_schema()
set_game_factor(0)
set_game_time(GameTime.parse("Y0001-D010T12:00:00"))
_UID = "11111111-1111-4111-8111-111111111111"
_PID = props.create_prop(name="Private prompt seat")["id"]
_DOC = props.read_sidecar(_PID)
_DOC.update(bbox=[1, 1, 1], mount="floor", actions=[{
    "id": "rest", "name": "Rest", "description": "Private prompt fixture", "enabled": True,
    "ability": "pose", "pose_key": "sitting", "participants": 1,
    "presence": "any", "interrupt_on_presence_change": False,
    "phases": [], "requirements": [], "effects": []}], model_variants=[{
    "stem": "model", "uid": _UID, "active": True,
    "width_m": 1, "depth_m": 1, "height_m": 1, "dims_estimated": False,
    "markers": [{"id": "body", "group": "seat", "at": [.5, .5, .5], "facing": 0}],
    "action_bindings": [{"action_id": "rest", "variant_uid": _UID, "supported": True,
                         "marker_ids": ["body"], "validation": "local_valid",
                         "access_points": {"actor": {"x": 0, "z": 2, "yaw": 180}}}]}])
props._write_sidecar(_PID, _DOC)
_DIR = props._prop_dir(_PID)
(_DIR / "model_1.glb").write_bytes(b"opaque-private-fixture")
(_DIR / "model_1.json").write_text('{"tier":"full"}')
(_DIR / "selection.json").write_text('{"model":{"full":"model_1.glb"}}')
_LOCATION = W.add_location("Private prompt room", "", rooms=[{
    "id": "hall", "name": "Hall", "layout": {"x": 0, "y": 0, "w": 6, "d": 6,
        "props": [{"id": "seat", "prop_id": _PID, "at": [4, 3], "yaw": 0}]}}])
_LOCATION.update(pos_x=0, pos_z=0, map3d={
    "plan_width_m": 10,
    "boundary": [[-2, -2], [8, -2], [8, 8], [-2, 8]]})
W.upsert_location(_LOCATION, sync_world=True)
places.invalidate()
_ACTOR = "prompt_async_actor"
C.save_character_profile(_ACTOR, {"character_name": _ACTOR, "template": "npc-temporary"},
                         create_new=True)
C.save_character_current_location(_ACTOR, _LOCATION["id"])
C.save_character_current_room(_ACTOR, "hall")
C.set_character_pos(_ACTOR, 2, 2)
assert places.where(_ACTOR) == (_LOCATION["id"], "hall"), \
    "private actor must resolve inside the placed fixture room"
_IDENTITY = ContextVar("prompt_async_identity", default="missing")


class AsyncPrompts(unittest.IsolatedAsyncioTestCase):
    def test_targeted_async_consumers_offload_blocking_helpers(self):
        # Pin the async boundaries: these helpers perform profile IO or render
        # templates with room geometry. Worker-thread arguments are safe.
        targets = {
            "app/core/thoughts.py": {"run_thought_turn": {
                "get_character_profile", "get_character_current_location", "get_character_current_room"}},
            "app/core/act_engine.py": {"_run_storyteller_agent": {"render_task"}},
            "app/core/npc_ops.py": {"_run_pipeline": {"render_task"}},
            "app/routes/world_dev.py": {"validate_json_route": {"render_task"}},
            "app/routes/content_packs.py": {"character_intro_suggest": {"render_task"}},
            "app/core/streaming.py": {"_ensure_speech_mapped": {"_render_speech_retry"}},
        }
        violations = []
        root = Path(__file__).resolve().parents[1]
        for filename, functions in targets.items():
            tree = ast.parse((root / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and node.name in functions:
                    for call in ast.walk(node):
                        if not isinstance(call, ast.Call):
                            continue
                        name = (call.func.id if isinstance(call.func, ast.Name)
                                else call.func.attr if isinstance(call.func, ast.Attribute) else "")
                        if name in functions[node.name]:
                            violations.append(f"{filename}:{call.lineno}: {name}")
        self.assertEqual(violations, [], "blocking async call sites: " + ", ".join(violations))

    async def test_npc_pipeline_offloads_each_render_stage(self):
        from app.core import npc_ops
        calls = []
        identity = _IDENTITY.set("pipeline-fixture")

        def render(task, **variables):
            # get_running_loop fails in workers and succeeds on the event loop.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                self.fail("NPC render blocked the event loop")
            self.assertEqual(_IDENTITY.get(), "pipeline-fixture")
            calls.append((task, variables))
            return "system:" + task, "user:" + task

        data = {"character_name": "private_pipeline_actor"}
        collect = AsyncMock(side_effect=["draft", "- fixture gap", "repair"])
        try:
            with patch.object(npc_ops, "_collect", collect), \
                    patch.object(npc_ops, "_make_llm", return_value=(object(), None)), \
                    patch.object(npc_ops, "validate_npc_fields", return_value=["missing fixture field"]), \
                    patch.object(npc_ops, "name_is_taken", return_value=False):
                frames = [frame async for frame in npc_ops._run_pipeline(
                    object(), "schema fixture", " briefing ", "location", "room", 1,
                    "validator", "provider", "creator", render, lambda *_: data)]
        finally:
            _IDENTITY.reset(identity)
        self.assertEqual([task for task, _ in calls],
                         ["npc_generate", "world_dev_validate", "npc_repair"])
        self.assertEqual(calls[0][1], {"schema_text": "schema fixture", "briefing": "briefing"})
        self.assertEqual(collect.await_count, 3)
        self.assertEqual(frames[-1]["stage"], "apply")
        self.assertIn("error", frames[-1])  # deliberately stops before storage apply

    async def blocked_geometry(self, operation):
        entered, release = Event(), Event()
        observations = []
        compose = places._compose
        loop = asyncio.get_running_loop()
        announced = asyncio.Event()

        def slow_compose(*args, **kwargs):
            if not entered.is_set():
                observations.append((_IDENTITY.get(), C.get_character_profile(_ACTOR)["character_name"]))
                entered.set()
                loop.call_soon_threadsafe(announced.set)
                # Safety release bounds the failure case when the event loop
                # itself is blocked; correctness uses the coroutine rendezvous.
                release.wait(3)
            return compose(*args, **kwargs)

        async def independent_coroutine():
            await announced.wait()
            self.assertFalse(release.is_set(), "geometry blocked the event loop")
            observations.append("independent coroutine ran")
            release.set()

        token = _IDENTITY.set("private-current-profile")
        watchdog = Timer(2, release.set)
        watchdog.start()
        observer = asyncio.create_task(independent_coroutine())
        try:
            with patch.object(places, "_compose", side_effect=slow_compose):
                result = await operation()
                await asyncio.wait_for(observer, 3)
        finally:
            release.set()
            watchdog.cancel()
            if not observer.done():
                observer.cancel()
            _IDENTITY.reset(token)
        self.assertEqual(observations, [("private-current-profile", _ACTOR),
                                        "independent coroutine ran"])
        return result

    async def test_agent_loop_thought_and_in_chat_consumers(self):
        from app.core import agent_loop, thoughts
        expected_context = thought_context.build_thought_context(_ACTOR)
        for age, template in ((None, "chat/agent_thought.md"),
                              (15, "chat/agent_thought_in_chat.md")):
            with self.subTest(template=template):
                loop = agent_loop.AgentLoop()
                turn = AsyncMock(return_value={"preview": "fixture handoff"})
                runner_boundary = SimpleNamespace(run_thought_turn=turn)
                with patch.object(loop, "_maybe_active_conversation_chime", return_value=None), \
                        patch.object(loop, "pop_hint", return_value="private fixture stimulus"), \
                        patch.object(agent_loop, "_minutes_since_last_chat_with_avatar", return_value=age), \
                        patch.object(thoughts, "get_thought_runner", return_value=runner_boundary), \
                        patch("app.core.stat_effects.maybe_activity_tick"), \
                        patch("app.models.rules.check_discover_rules"):
                    await self.blocked_geometry(lambda: loop._run_turn(_ACTOR))
                turn.assert_awaited_once()
                handed_off = turn.await_args.kwargs
                self.assertEqual(handed_off["thought_context_override"], expected_context)
                self.assertEqual(handed_off["system_prompt_override"],
                                 prompt_templates.render(template, **expected_context))
                self.assertIn('- Private prompt seat: Rest', handed_off["system_prompt_override"])
                self.assertEqual(loop._recent[-1]["outcome"], "ok")

    async def test_actual_thought_context_preserves_room_contract(self):
        expected = thought_context.build_thought_context(_ACTOR)
        actual = await self.blocked_geometry(
            lambda: thought_context.build_thought_context_async(_ACTOR))
        self.assertIn("<prop_actions_contract>", actual["activity_hint_block"])
        self.assertIn('- Private prompt seat: Rest', actual["activity_hint_block"])
        self.assertEqual(actual, expected)

    async def test_render_fallback_preserves_thought_and_in_chat_contract(self):
        for template in ("chat/agent_thought.md", "chat/agent_thought_in_chat.md"):
            with self.subTest(template=template):
                names = meta.find_undeclared_variables(prompt_templates._env.parse(
                    prompt_templates._env.loader.get_source(prompt_templates._env, template)[0]))
                variables = dict.fromkeys(names, "")
                variables.update(character_name=_ACTOR, activity_hint_block="")
                expected = prompt_templates.render(template, **variables)
                actual = await self.blocked_geometry(
                    lambda: prompt_templates.render_async(template, **variables))
                self.assertIn("<prop_actions_contract>", actual)
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
