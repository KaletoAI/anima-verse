#!/usr/bin/env python3
"""One bounded correction of rejected pair actions in run_chat_turn.

Usage: ./.venv/bin/python scripts/smoke_chat_pair_correction.py
       Add --review-terminal, --review-marker or --review-state to isolate a
       review regression. Without arguments every case runs.

Disposable world/instance/catalog/clips, real profiles and invitation engine,
real SetPoseSkill and InteractSkill. Only prompt assembly and external LLM
responses are scripted; real background follow-ups are joined before assertions.

Hand-derived expectations: Ann and the temporary NPC Bob stand 2 m apart.
A SetActivity(embracing) cannot bind them; a single corrective InteractWith
can, because Bob accepts via the real temporary-NPC hook. A successful
RecordFact call must write exactly once, even if the corrective model repeats
it. An unavailable partner, missing correction tool, NONE, a repeated rejected
pose, or a queue failure must remain a visible failure with no interaction.
A correction is at most one additional intent call, never a retry loop.

The review regressions cover the remainder of the real turn: a pair clip with
no duration leaves exactly ONE failed DB row, never another corrective invite.
After successful correction, post_process=True runs the real activity-marker
consumer and chat-state extractor; neither a stale standing marker nor an
extracted known standing key may erase the new pair. Only the extraction LLM
response is supplied; the setters and extraction application remain real.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="chat-pair-correction-")
ROOT = Path(TMP.name)
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
from app.core import paths
paths.init(ROOT / "world")
paths.init_instance(ROOT / "instance")
from app.core import db
db.init_schema()
from app.core import chat_engine, interaction_engine as ie, pose_catalog, streaming
from app.models import character as chars, world
from app.plugins.context import PluginContext
from plugins.interact.skill import InteractSkill
from app.models.perception_store import get_character_room_stream
from plugins.set_pose.skill import SetPoseSkill
import plugins.interact.register

CLIPS = ROOT / "clips"
CLIPS.mkdir()
for role in ("a", "b"):
    (CLIPS / f"hug__{role}.fbx").write_bytes(b"isolated clip fixture")
    (CLIPS / f"broken__{role}.fbx").write_bytes(b"isolated incomplete metadata fixture")
(CLIPS / "hug.json").write_text(json.dumps({
    "kind": "hug", "pair": True, "fps": 30, "frames": 60, "duration_s": 2,
    "geometry": {"anchor_frame": 30, "root_distance_m": 0.6,
                 "roles": {"a": {"anchor_xz_m": [-0.3, 0]},
                           "b": {"anchor_xz_m": [0.3, 0]}}}}))
CATALOG = ROOT / "pose_catalog.json"
CATALOG.write_text(json.dumps({
    "groups": {"stand": {"label": "Standing", "default": "standing", "needs_place": False},
               "seat": {"label": "Seat", "default": "cuddling", "needs_place": True}},
    "entries": {"standing": {"prompt": "standing", "group": "stand", "_default": True},
                "embracing": {"prompt": "two people hugging", "group": "stand",
                              "animation": "hug", "solo": False, "places": 2},
                "cuddling": {"prompt": "two people cuddling", "group": "stand",
                             "animation": "broken", "solo": False, "places": 2}}}))
_original_catalog_path = pose_catalog.catalog_path
pose_catalog.catalog_path = lambda axis: CATALOG if axis == "pose" else _original_catalog_path(axis)
pose_catalog.reload_catalogs()
for name, template in (("Ann", "human-roleplay"), ("Bob", "npc-temporary")):
    assert chars.save_character_profile(name, {"language": "en", "template": template}, create_new=True)
assert not chars.is_temporary_npc("Ann")
assert chars.is_temporary_npc("Bob")
POSE = SetPoseSkill({}, PluginContext("set_pose"))
POSE.name = "SetActivity"
PAIR = InteractSkill({}, PluginContext("interact"))
PAIR.name = "InteractWith"



def scene_rows():
    return get_character_room_stream(
        "Ann", chars.get_character_current_location("Ann") or "",
        chars.get_character_current_room("Ann") or "", include_source=True)


def call(name, **data):
    return f'<tool name="{name}">{json.dumps(data)}</tool>'


def bind(skill):
    def execute(raw):
        data = json.loads(raw)
        data["agent_name"] = "Ann"
        return skill.execute(json.dumps(data))
    return execute


def record_fact(raw):
    value = int(world.get_world_setting("smoke.fact_count", "0")) + 1
    world.set_world_setting("smoke.fact_count", str(value))
    return "Fact recorded."


NARRATIVE = "Ann records a fact, then embraces Bob."
REFUSED = call("SetActivity", pose="embracing", detail="embraces Bob")
PAIR_CALL = call("InteractWith", partner="Bob", action="embracing")
REAL_THREAD = threading.Thread
REAL_REPORT = streaming.report_deferred_failure


def scenario(label, correction, *, mode="rp_first", available=True, tool_llm=True,
             initial=None, paired=False, needs_correction=True, failure_detail="",
             post_process=False, extracted_pose="", terminal_invite=False):
    ie.end_interaction("Ann")
    chars.set_character_pos("Ann", 10, 20)
    chars.set_character_pos("Bob", 12, 20)
    invite_ids_before = {row[0] for row in db.get_connection().execute(
        "SELECT invite_id FROM interaction_invites")}
    world.set_world_setting("smoke.fact_count", "0")
    tools = {"SetActivity": bind(POSE), "RecordFact": record_fact}
    failed_lines_before = sum(row.get("source") == "tool_failed" for row in scene_rows())
    if available:
        tools["InteractWith"] = bind(PAIR)
    initial = initial if initial is not None else call("RecordFact") + REFUSED
    script = [NARRATIVE if mode == "rp_first" else NARRATIVE + initial]
    if mode == "rp_first":
        script.append(initial)
    if available and tool_llm and (needs_correction or terminal_invite):
        script.append(correction)
    calls, workers, feedback, worker_errors = [], [], [], []
    extraction_calls = []

    def scripted_extraction(**kwargs):
        if kwargs.get("task") == "extraction_chat_state":
            extraction_calls.append(kwargs)
            return SimpleNamespace(content=json.dumps({
                "pose": extracted_pose, "detail": "remains close", "removed": []}))
        return SimpleNamespace(content="{}")
    context = {"llm": object(), "system_content": "Scripted chat", "moment_content": "",
               "messages": [], "room_mode": True, "mode": mode, "tool_format": "tag",
               "tools_dict": tools, "tool_llm": object() if tool_llm else None,
               "tool_system_content": "Scripted tool instructions", "speaker": "Bob",
               "medium": "in_person", "agent_config": {}, "full_chat_history": [],
               "user_display_name": "Bob", "agent_tools": [POSE.as_tool(), PAIR.as_tool()]}

    def submit(**kwargs):
        calls.append(kwargs)
        if not script:
            raise AssertionError("more than one correction was requested")
        value = script.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=value)

    def thread(*args, **kwargs):
        target = kwargs["target"]
        def observed():
            try:
                target()
            except BaseException as exc:
                worker_errors.append(exc)
        kwargs["target"] = observed
        worker = REAL_THREAD(*args, **kwargs)
        workers.append(worker)
        return worker

    def report(actor, tool, result, **kwargs):
        feedback.append((tool, str(result)))
        return REAL_REPORT(actor, tool, result, **kwargs)

    with patch.object(chat_engine, "build_chat_context", return_value=context), \
            patch("app.core.llm_queue.get_llm_queue", return_value=SimpleNamespace(submit=submit)), \
            patch("app.core.memory_situational.build_situational_block", return_value=""), \
            patch("app.core.llm_router.llm_call", side_effect=scripted_extraction), \
            patch.object(threading, "Thread", side_effect=thread), \
            patch.object(streaming, "report_deferred_failure", side_effect=report):
        reply = chat_engine.run_chat_turn(
            "demo", "Ann", "Bob", "Stay with me.", post_process=post_process)
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive(), f"{label}: worker did not finish"
    assert not worker_errors, (label, worker_errors)
    assert reply == NARRATIVE, (label, reply)
    assert world.get_world_setting("smoke.fact_count") == "1", f"{label}: successful side effect repeated/lost"
    if terminal_invite:
        new_invites = [(row[0], row[1]) for row in db.get_connection().execute(
            "SELECT invite_id, status FROM interaction_invites")
                       if row[0] not in invite_ids_before]
        assert len(new_invites) == 1 and new_invites[0][1] == "failed", (
            label, "a terminal invitation was repeated", new_invites)
    if post_process:
        assert extraction_calls, f"{label}: real state extraction did not reach its LLM boundary"
    a, b = ie.get_interaction("Ann"), ie.get_interaction("Bob")
    if paired:
        assert a and b and a["id"] == b["id"], f"{label}: rejected pair action was never repaired"
        assert a["partner"] == "Bob" and b["partner"] == "Ann"
        assert a["pose_key"] == b["pose_key"] == "embracing"
        assert not feedback, (label, feedback)
    else:
        assert a is None and b is None, (label, a, b)
        assert feedback and feedback[-1][1].startswith("Error"), f"{label}: refusal was not surfaced"
        if failure_detail:
            assert any(failure_detail in result for _, result in feedback), (label, feedback)
        failed_lines_after = sum(row.get("source") == "tool_failed" for row in scene_rows())
        assert failed_lines_after > failed_lines_before, f"{label}: refusal absent from scene transcript"
    expected_calls = (2 if mode == "rp_first" else 1) + int(available and tool_llm and needs_correction)
    assert len(calls) == expected_calls, (label, len(calls), expected_calls)
    if available and tool_llm and needs_correction:
        assert calls[-1]["task_type"] == "intent"
    print(f"OK: {label}")


def run_regressions():
    selectors = set(sys.argv[1:])
    review_only = bool(selectors)
    # Keep terminal invitation proof first so its RED is independent of the
    # subsequent postprocessing overwrite failures.
    if not review_only or "--review-terminal" in selectors:
        refused_seat = call("SetActivity", pose="cuddling")
        seat_pair = call("InteractWith", partner="Bob", action="cuddling")
        scenario("terminal failed invitation is never corrected again", seat_pair,
                 initial=call("RecordFact") + refused_seat + seat_pair,
                 needs_correction=False, terminal_invite=True)
    if not review_only or "--review-marker" in selectors:
        scenario("repaired pair survives original solo activity marker", PAIR_CALL,
                 initial=call("RecordFact") + REFUSED + "\n**I do standing: embraces Bob**",
                 paired=True, post_process=True)
    if not review_only or "--review-state" in selectors:
        scenario("repaired pair survives extracted known solo pose", PAIR_CALL,
                 paired=True, post_process=True, extracted_pose="standing")
    if review_only:
        return
    scenario("rp_first repairs pair and does not repeat successful tools", call("RecordFact") + PAIR_CALL, paired=True)
    scenario("inline repairs through available tool LLM", PAIR_CALL, mode="single", paired=True)
    scenario("missing partner remains refused", call("InteractWith", partner="Missing", action="embracing"),
             failure_detail="Missing")
    scenario("missing correction tool remains refused", "NONE", available=False)
    scenario("no tool LLM remains refused", "NONE", mode="single", tool_llm=False)
    scenario("NONE remains refused", "NONE")
    scenario("repeated rejected pose never loops", REFUSED)
    scenario("queue failure remains refused", RuntimeError("scripted correction outage"),
             failure_detail="scripted correction outage")
    scenario("successful pair survives accompanying solo pose", "NONE",
             initial=call("RecordFact") + PAIR_CALL + call("SetActivity", pose="standing"),
             paired=True, needs_correction=False)


try:
    run_regressions()
finally:
    TMP.cleanup()
