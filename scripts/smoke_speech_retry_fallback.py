#!/usr/bin/env python3
"""Smoke: the B-lite speech retry shows a FILLED example and, when the retry
still yields no speech verb, delivers the lines itself to a single listener.

Usage:  ./.venv/bin/python scripts/smoke_speech_retry_fallback.py

Throwaway storage (paths.init on a temp dir BEFORE any world-DB import), no
server, no LLM: the chat LLM and the tool LLM are fakes. One rp_first thought
turn of "Luisa" runs through StreamingAgent.stream for real — RP prose, the
tool decision, the B-lite net, the execution of what it adds. The speech verb
is the real TalkTo skill class (for its input shape); its executor is a
recorder, so nothing is written. Each delivered call = one recorded input.

The RP of every case: two lines of Luisa's own speech,
    „Komm her, Kai“, sage ich. Ich lache. „Bleib noch“, sage ich leise.
The speech filter keeps both (first-person attribution "sage ich", see
smoke_speech_net [6]): quotes = ["Komm her, Kai", "Bleib noch"].
The tool decision always answers NONE, so no speech verb is in the decision
and the retry runs whenever someone is present.

[1] Retry prompt: TalkTo.speech_call_input("Kai", "Komm her, Kai") is
    {"name": "Kai", "message": "Komm her, Kai"} (json.dumps, ensure_ascii off).
    The rendered system part contains exactly that call in the tag format
    and no "<JSON input" placeholder.
[2] (a) present = ["Kai"], the retry copies the OLD placeholder example
    three times. The tag parser finds no call in it (the body is no JSON), so
    the retry delivered nothing -> the fallback sends BOTH lines to the one
    listener: 2 executions, inputs
    {"name": "Kai", "message": "Komm her, Kai"} and
    {"name": "Kai", "message": "Bleib noch"}, in that order.
[3] (b) present = ["Kai"], the retry answers two correct calls -> exactly
    those two executions, no fallback on top (2, not 4).
[4] (c) present = [] -> no retry at all (the tool LLM is asked once, for
    the decision) and no execution: 0.
[5] present = ["Kai", "Mara"], retry copies the placeholder: one listener is
    not certain and TalkTo cannot address the room (speech_call_input(None, …)
    is '') -> 0 executions.
[6] A retry call whose message is a placeholder ({"name": "Kai",
    "message": "<the spoken words>"}) counts as no delivery: the fallback
    sends both real lines (2 executions, the placeholder call is not run).
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="speech-retry-fallback-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402
paths.init(TMP / "world")
from app.core import config, db  # noqa: E402
config.load(paths.get_config_path())
db.init_schema()

from app.utils import llm_logger  # noqa: E402
llm_logger.LOG_FILE = TMP / "llm_calls.jsonl"
from app.models.character import save_character_profile  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402
from app.core import streaming  # noqa: E402
from app.core.streaming import StreamingAgent  # noqa: E402
from app.core.tool_step_prompt import ToolStepPrompt  # noqa: E402
from plugins.talk_to.skill import TalkToSkill  # noqa: E402

for _name in ("Luisa", "Kai", "Mara"):
    save_character_profile(_name, {"character_name": _name,
                                   "template": "human-roleplay"}, create_new=True)

RP = "„Komm her, Kai“, sage ich. Ich lache. „Bleib noch“, sage ich leise."
OLD_PLACEHOLDER = ('<tool name="TalkTo"><JSON input exactly as the tool '
                   'description specifies></tool>')
LINE_1 = json.dumps({"name": "Kai", "message": "Komm her, Kai"}, ensure_ascii=False)
LINE_2 = json.dumps({"name": "Kai", "message": "Bleib noch"}, ensure_ascii=False)

TALK = TalkToSkill({"enabled": True}, PluginContext("talk_to"))
TALK.name = "TalkTo"
TALK.description = "Speak to someone present."

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class _Manager:
    def tool_names_with_flag(self, flag):
        return frozenset({"TalkTo"}) if flag == "DELIVERS_SPEECH" else frozenset()

    def get_skill_by_name(self, name):
        return TALK if name == "TalkTo" else None

    def get_skill(self, skill_id):
        return TALK if skill_id == "talk_to" else None


class _ChatLLM:
    model = "fake-chat"

    async def astream(self, _messages):
        yield SimpleNamespace(content=RP)


class _ToolLLM:
    model = "fake-tool"

    def __init__(self, retry_answer):
        self.retry_answer = retry_answer
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append(messages)
        answer = "NONE" if len(self.prompts) == 1 else self.retry_answer
        return SimpleNamespace(content=answer, finish_reason="stop", usage=None)


def run_turn(present, retry_answer):
    executed = []
    tool_llm = _ToolLLM(retry_answer)
    agent = StreamingAgent(
        llm=_ChatLLM(), tool_format="tag",
        tools_dict={"TalkTo": lambda raw: executed.append(raw) or "Spoke."},
        agent_name="Luisa", tool_llm=tool_llm, log_task="thought", mode="rp_first",
        tool_step=ToolStepPrompt("decide", "decide now", ["TalkTo"], {}))

    async def go():
        async for _ in agent.stream("system", [], "think"):
            pass
    with patch("app.core.dependencies.get_skill_manager", return_value=_Manager()), \
            patch.object(StreamingAgent, "_present_names", lambda self: list(present)), \
            patch.object(StreamingAgent, "_invoke_tool_llm_laned",
                         lambda self, messages: self.tool_llm.invoke(messages)):
        asyncio.run(go())
    return executed, tool_llm


print("[1] the retry prompt carries a filled example")
with patch("app.core.dependencies.get_skill_manager", return_value=_Manager()):
    agent = StreamingAgent(llm=_ChatLLM(), tool_format="tag", tools_dict={"TalkTo": None},
                           agent_name="Luisa", log_task="thought", mode="rp_first")
    system, _user = agent._render_speech_retry(["Komm her, Kai", "Bleib noch"], ["Kai"], ["TalkTo"])
check("[1] the filled call is in the system part",
      f'<tool name="TalkTo">{LINE_1}</tool>' in system, True)
check("[1] no placeholder example any more", "<JSON input" in system, False)

print("[2] (a) placeholder copied, one listener -> direct delivery")
executed, _ = run_turn(["Kai"], "\n".join([OLD_PLACEHOLDER] * 3))
check("[2] both lines delivered, in order", executed, [LINE_1, LINE_2])

print("[3] (b) correct calls -> exactly those")
executed, _ = run_turn(["Kai"], f'<tool name="TalkTo">{LINE_1}</tool>\n'
                                f'<tool name="TalkTo">{LINE_2}</tool>')
check("[3] two deliveries, no fallback on top", executed, [LINE_1, LINE_2])

print("[4] (c) nobody within earshot -> nothing")
executed, tool_llm = run_turn([], OLD_PLACEHOLDER)
check("[4] the tool LLM was asked once (no retry)", len(tool_llm.prompts), 1)
check("[4] no delivery", executed, [])

print("[5] two listeners, a verb that cannot address the room -> nothing")
executed, _ = run_turn(["Kai", "Mara"], OLD_PLACEHOLDER)
check("[5] no delivery", executed, [])

print("[6] a retry call with a placeholder value is no delivery")
executed, _ = run_turn(["Kai"], '<tool name="TalkTo">{"name": "Kai", '
                                '"message": "<the spoken words>"}</tool>')
check("[6] the real lines go out instead", executed, [LINE_1, LINE_2])

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("ALL CHECKS PASSED")
