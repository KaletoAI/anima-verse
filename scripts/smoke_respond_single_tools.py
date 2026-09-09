#!/usr/bin/env python3
"""Smoke run: inline tool calls in the respond lane (single chat mode).

Bug 2026-09-09: a temporary NPC without an explicit ``chat_mode`` runs in
``single`` mode (``dependencies.determine_mode``) — the chat model is told to
write tool calls inline as ``<tool name="…">…</tool>``. ``run_chat_turn`` (the
respond lane behind every room reply) only knew the rp_first tool phase: an
inline call was neither executed nor stripped, so the raw tag was recorded as
the character's utterance — and the next speakers imitated it. The RP model
had hidden the gap by ignoring the tool format; the fast model routed for
``npc_talk`` follows it.

Throwaway storage, no server, no LLM. Hand-derived expectations:

  (a) clean_response strips inline tool tags like the streaming path's
      ``_strip_tool_hallucinations`` does: a closed ``<tool name="X">…</tool>``
      disappears and the prose around it survives; a reply that is ONLY a
      tag becomes ""; an unclosed tag is cut to the end of the text; the old
      ``<tool_call>`` stripping still works; prose without tags is unchanged.

  (b) execute_tool_matches applies the SAME rules the rp_first phase applied
      to tool-LLM matches: a known tool runs with its input; an unknown name
      is skipped; a CONTENT_TOOL is skipped (no retry path here); a
      SUPPRESS_IN_PERSON verb is skipped while the medium is in_person; a
      DEFERRED tool runs in a background thread with the RP text injected.

  (c) run_chat_turn in single mode, LLM stubbed: prose + tag → the returned
      reply is the prose alone and the tool ran (in the follow-up thread);
      a tag-only reply → "" AND the tool still ran (the character did
      something, it just said nothing); two calls of a SINGLETON tool → only
      the last one runs (``_dedupe_singleton_tools``).

Usage:  ./.venv/bin/python scripts/smoke_respond_single_tools.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="respond-single-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="respond-single-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import chat_engine, streaming  # noqa: E402
from app.core.chat_engine import clean_response, execute_tool_matches  # noqa: E402

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


def wait_for(pred, timeout=3.0):
    """Poll a condition the follow-up thread satisfies; False on timeout."""
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


TAG = '<tool name="SetActivity">{"pose": "leaning", "detail": "an der Theke"}</tool>'

# ── (a) clean_response strips inline tool tags ─────────────────────────────
print("(a) clean_response strips inline tool tags")
check("prose survives, the tag goes",
      clean_response(f"„Noch ein Bier.“\n\n{TAG}"), "„Noch ein Bier.“")
check("a tag-only reply is empty", clean_response(TAG), "")
check("an unclosed tag is cut to the end",
      clean_response('Prost. <tool name="SetActivity">{"pose": "leaning"'), "Prost.")
check("<tool_call> is still stripped",
      clean_response("Hallo <tool_call>x</tool_call> du"), "Hallo  du")
check("plain prose is untouched", clean_response("Ich hebe mein Glas."),
      "Ich hebe mein Glas.")

# ── (b) execute_tool_matches applies the rp_first rules ────────────────────
print("(b) execute_tool_matches: known runs, unknown/content/in-person skipped, deferred in thread")
CALLS = []
ctx = {
    "tools_dict": {
        "SetActivity": lambda inp: CALLS.append(("SetActivity", inp)),
        "TakePhoto": lambda inp: CALLS.append(("TakePhoto", inp)),
        "Undress": lambda inp: CALLS.append(("Undress", inp)),
        "Move": lambda inp: CALLS.append(("Move", inp)),
    },
    "content_tools": {"TakePhoto"},
    "deferred_tools": {"Undress"},
    "medium": "in_person",
}
streaming._suppress_in_person_tool_names = lambda: frozenset({"Move"})
execute_tool_matches(ctx, "Gast", [
    ("SetActivity", '{"pose": "leaning"}'),
    ("Nonsense", "x"),
    ("TakePhoto", "selfie"),
    ("Move", "east"),
    ("Undress", '{"what": "jacket"}'),
], rp_text="Ich ziehe die Jacke aus.", incoming_message="Noch ein Bier")
check("the known tool ran with its input",
      [c for c in CALLS if c[0] == "SetActivity"], [("SetActivity", '{"pose": "leaning"}')])
check("unknown, content and in-person verbs did not run",
      [c[0] for c in CALLS if c[0] in ("Nonsense", "TakePhoto", "Move")], [])
check("the deferred tool ran in the background thread",
      wait_for(lambda: any(c[0] == "Undress" for c in CALLS)), True)
_undress = next(c[1] for c in CALLS if c[0] == "Undress")
check("with the RP text injected", "Ich ziehe die Jacke aus." in _undress, True)

# ── (c) run_chat_turn in single mode, LLM stubbed ──────────────────────────
print("(c) run_chat_turn (single): tag stripped from the reply, tool executed")


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeQueue:
    def __init__(self, content):
        self.content = content
        self.submits = []

    def submit(self, **kwargs):
        self.submits.append(kwargs)
        return FakeResponse(self.content)


def fake_ctx(mode="single"):
    return {
        "llm": object(), "system_content": "sys", "messages": [{"role": "user", "content": "Kai: Noch ein Bier"}],
        "room_mode": True, "mode": mode, "tool_system_content": "", "tool_llm": None,
        "tools_dict": {"SetActivity": lambda inp: CALLS.append(("SetActivity", inp))},
        "tool_format": "tag", "deferred_tools": set(), "content_tools": set(),
        "medium": "in_person", "agent_config": {}, "user_display_name": "Kai",
        "full_chat_history": [], "old_history": None,
    }


import app.core.llm_queue as llm_queue_mod  # noqa: E402
streaming._singleton_tool_names = lambda: frozenset({"SetActivity"})
chat_engine.build_chat_context = lambda *a, **k: fake_ctx()

CALLS.clear()
Q = FakeQueue(f"„Noch ein Bier kommt.“\n\n{TAG}")
llm_queue_mod.get_llm_queue = lambda: Q
reply = chat_engine.run_chat_turn("", "Gast", "Kai", "Noch ein Bier", "in_person",
                                  "character_talk", False, room_stream=[{"x": 1}])
check("the reply is the prose without the tag", reply, "„Noch ein Bier kommt.“")
check("the LLM was asked once", len(Q.submits), 1)
check("the inline tool ran",
      wait_for(lambda: any(c[0] == "SetActivity" for c in CALLS)), True)
check("with the tag's input",
      [c[1] for c in CALLS if c[0] == "SetActivity"],
      ['{"pose": "leaning", "detail": "an der Theke"}'])

CALLS.clear()
Q = FakeQueue(TAG)
llm_queue_mod.get_llm_queue = lambda: Q
reply = chat_engine.run_chat_turn("", "Gast", "Kai", "Noch ein Bier", "in_person",
                                  "character_talk", False, room_stream=[{"x": 1}])
check("a tag-only reply says nothing", reply, "")
check("but the tool still ran",
      wait_for(lambda: any(c[0] == "SetActivity" for c in CALLS)), True)

CALLS.clear()
Q = FakeQueue('<tool name="SetActivity">first</tool> Prost. <tool name="SetActivity">last</tool>')
llm_queue_mod.get_llm_queue = lambda: Q
reply = chat_engine.run_chat_turn("", "Gast", "Kai", "Prost", "in_person",
                                  "character_talk", False, room_stream=[{"x": 1}])
check("both tags stripped", reply, "Prost.")
check("a singleton tool runs once, with the last call",
      wait_for(lambda: CALLS == [("SetActivity", "last")]), True)

CALLS.clear()
chat_engine.build_chat_context = lambda *a, **k: fake_ctx(mode="rp_first")
Q = FakeQueue(f"Prosa. {TAG}")
llm_queue_mod.get_llm_queue = lambda: Q
reply = chat_engine.run_chat_turn("", "Gast", "Kai", "Prost", "in_person",
                                  "character_talk", False, room_stream=[{"x": 1}])
check("rp_first: the tag is stripped too", reply, "Prosa.")
check("rp_first without a tool LLM: no inline execution",
      wait_for(lambda: bool(CALLS), timeout=0.5), False)

# ── result ──────────────────────────────────────────────────────────────────
print()
print(f"{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print("  FAIL", f)
    sys.exit(1)
print("OK")
