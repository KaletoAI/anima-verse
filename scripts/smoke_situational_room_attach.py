#!/usr/bin/env python3
"""Checks that the situational memory block reaches the ROOM reply's user turn.

Usage:
    ./.venv/bin/python scripts/smoke_situational_room_attach.py

Pure: no server, no world DB, no LLM, no embedding backend. The turn is run
through the real ``chat_engine.run_chat_turn`` with three things replaced —
the prompt builder (``build_chat_context``), the LLM queue and the embedding
function — so what is checked is the production wiring between them, not a
re-implementation of it.

WHAT THE FEATURE IS SUPPOSED TO DO (decisions of 2026-09-21)

``app/core/memory_situational.py`` picks the character's own facts and open
promises that are closest to the incoming line and renders them as a second
user-turn fragment. It is built for the character that REPLIES, and the query
text is the utterance that character is answering (the trigger of the turn —
in the room model the speaker's line, avatar or character alike). The block
hangs BEHIND the scene state inside the SAME last user turn, because the
system prompt's cached prefix has to stay byte-identical (CHAT_PROMPTS.md § 1)
and because ``attach_moment`` must stay the only writer of that turn.

THE VECTORS AND WHAT THEY IMPLY (hand-calculated, not recorded)

Every stub vector is a 2-D unit vector and the trigger sits at (1, 0), so for
a unit vector (x, y) the cosine similarity against the trigger IS x:

    Kira  "Der Bogen des Jaegers steht in der Kammer"  (1.00, 0.00) -> 1.00 ✓
    Kira  "Das Brot wird morgens gebacken"             (0.60, 0.80) -> 0.60 ✗
    Dan   "Dan hat den Bogen zuletzt am Fluss gesehen" (1.00, 0.00) -> 1.00
    off-topic trigger "Wie war das Wetter gestern?"    (-1.00, 0.00)

With the shipped threshold 0.75 exactly ONE of Kira's two memories qualifies
for the on-topic trigger, and NONE for the off-topic one (its best score is
-0.60). Dan's memory would score 1.00 — it must still never appear, because
Dan is the speaker, not the responder.

THE EXPECTED LAST USER MESSAGE, derived by hand

In room mode the transcript already ends with the triggering line, so
``run_chat_turn`` does not append the trigger again; ``attach_moment`` appends
the moment to that last user turn, separated by a blank line, and the block
follows it the same way:

    "Dan: Wo ist eigentlich mein Bogen?"          <- the transcript line
    ""
    "[SCENE STATE …] … [END OF SCENE STATE]"      <- ctx["moment_content"]
    ""
    "[You remember, …:]"                          <- the block
    "- Der Bogen des Jaegers steht in der Kammer"

CHECKS

(a) on-topic trigger: the last message has role "user" and is exactly
    trigger line + moment + block, in that order, with the one matching fact
    and without the one below the threshold.
(b) off-topic trigger: no block; the last user message is exactly what it
    was before this feature — trigger line + moment, nothing else.
(c) ``memory.situational_enabled`` off: no block AND the embedding function is
    never called (the switch must cost nothing, not merely hide the result).
(d) the embedding function raises: no block, and the turn still returns its
    reply — failure is silence, never an exception into the chat turn.
(e) the block carries the RESPONDER's memories: with Kira replying to Dan,
    Dan's equally-close memory is absent.
(f) rp_first: the second LLM call of the same turn (the tool decision) carries
    NO block, and the block is built exactly once for the whole turn.
(g) the system message never sees any of it, and the history dicts handed in
    are not mutated (they must reach the backend byte-identical next turn).

FAILS BEFORE / PASSES AFTER

Confirmed against the PINNED commit 919c997f (never ``HEAD``), the state in
which ``memory_situational.build_situational_block`` had no caller at all:
loading ``git show 919c997f:app/core/chat_engine.py`` as ``app.core.chat_engine``
and running this file against it fails eight checks — in (a) "the last user
message is line + scene state + block" (the message ends at
``[END OF SCENE STATE]``), "the block sits BEHIND the scene state", "the block
was built for the responder" and "exactly one embedding of the message"; in
(d) "it did try once"; in (e) "the responder's fact is there"; in (f) "the chat
call still carried it" and "the block was built ONCE for the whole turn".
(b), (c) and (g) pass there, as they must: they describe what does NOT change.

Exit code 0 = all checks passed, 1 = at least one failed.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Storage and clip library must be redirected BEFORE the first app import: the
# turn below reaches its world.db through paths, and without a storage root
# every world access raises StorageNotInitialised — there is no default world
# any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="situational-attach-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="situational-attach-storage-"))

from app.core import db  # noqa: E402
db.init_schema()  # empty throwaway world — only so the turn's incidental
                  # profile reads answer "unknown character" instead of
                  # logging a missing-table traceback per call.

from app.core import chat_engine  # noqa: E402
from app.core import config  # noqa: E402
from app.core import embedding as embedding_mod  # noqa: E402
from app.core import llm_queue as llm_queue_mod  # noqa: E402
from app.core import memory_situational as ms  # noqa: E402
from app.core import pending_reports  # noqa: E402
from app.models import account as account_mod  # noqa: E402
from app.models import memory as memory_mod  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          f"{'' if ok else f'  — got {got!r}, want {want!r}'}")
    if not ok:
        failures.append(name)


# ── the synthetic world ────────────────────────────────────────────────────

RESPONDER = "Kira"
SPEAKER = "Dan"
TRIGGER = "Wo ist eigentlich mein Bogen?"
OFF_TOPIC = "Wie war das Wetter gestern?"
TRANSCRIPT_LINE = f"{SPEAKER}: {TRIGGER}"
OFF_TOPIC_LINE = f"{SPEAKER}: {OFF_TOPIC}"

MOMENT = ("[SCENE STATE — how things stand right now. Nobody said this.]\n"
          "It is late afternoon in the tavern.\n"
          "[END OF SCENE STATE]")
SYSTEM = "You are Kira. Never break character."
REPLY = "Der steht in der Kammer, gleich hinter der Tuer."

KIRA_HIT = "Der Bogen des Jaegers steht in der Kammer"
KIRA_MISS = "Das Brot wird morgens gebacken"
DAN_FACT = "Dan hat den Bogen zuletzt am Fluss gesehen"

VECTORS = {
    TRIGGER: (1.0, 0.0),
    OFF_TOPIC: (-1.0, 0.0),
    KIRA_HIT: (1.0, 0.0),
    KIRA_MISS: (0.6, 0.8),
    DAN_FACT: (1.0, 0.0),
}

STORE = {
    RESPONDER: [
        {"id": 1, "memory_type": "semantic", "content": KIRA_HIT,
         "timestamp": "2026-09-02T10:00:00", "game_ts": "", "tags": []},
        {"id": 2, "memory_type": "semantic", "content": KIRA_MISS,
         "timestamp": "2026-09-01T10:00:00", "game_ts": "", "tags": []},
    ],
    SPEAKER: [
        {"id": 3, "memory_type": "semantic", "content": DAN_FACT,
         "timestamp": "2026-09-03T10:00:00", "game_ts": "", "tags": []},
    ],
}


class CountingEmbed:
    """The embedding entry point, stubbed. Counts calls, can raise."""

    def __init__(self, raises=False):
        self.raises = raises
        self.calls = 0

    def __call__(self, text):
        self.calls += 1
        if self.raises:
            raise RuntimeError("embedding backend exploded")
        vec = VECTORS.get((text or "").strip())
        return list(vec) if vec else None


class DictCache:
    """The vector cache, stubbed — the two methods of DbVectorCache."""

    def __init__(self):
        self.store = {}

    def get_many(self, memory_ids, model_id):
        wanted = set(memory_ids)
        return {i: v for (i, m), v in self.store.items()
                if m == model_id and i in wanted}

    def put_many(self, model_id, vectors):
        for memory_id, vec in vectors.items():
            self.store[(memory_id, model_id)] = list(vec)


class StubResponse:
    def __init__(self, content):
        self.content = content
        self.usage = None


class StubQueue:
    """Records every submit and answers without touching a provider."""

    def __init__(self):
        self.calls = []

    def submit(self, *, task_type, priority, llm, messages_or_prompt,
               agent_name="", label="", **kw):
        self.calls.append({"task_type": task_type,
                           "messages": [dict(m) for m in messages_or_prompt]})
        # The tool decision must produce no tool call; the chat call answers.
        return StubResponse("NONE" if task_type == "intent" else REPLY)


def make_ctx(mode="single"):
    """What build_chat_context hands run_chat_turn — only the keys it reads."""
    return {
        "system_content": SYSTEM,
        "moment_content": MOMENT,
        "messages": HISTORY,
        "room_mode": True,
        "llm": object(),
        "agent_config": {},
        "mode": mode,
        "tools_dict": ({"SetLocation": lambda *_a, **_k: ""}
                       if mode == "rp_first" else {}),
        "tool_format": "tag",
        "tool_system_content": "TOOL SYSTEM" if mode == "rp_first" else "",
        "tool_llm": object() if mode == "rp_first" else None,
        "medium": "in_person",
        "full_chat_history": [],
        "old_history": [],
        "user_display_name": "",
    }


HISTORY = [
    {"role": "assistant", "content": "Kira wischt den Tresen."},
    {"role": "user", "content": TRANSCRIPT_LINE},
]
HISTORY_SNAPSHOT = [dict(m) for m in HISTORY]


# ── the turn, with the three seams replaced ────────────────────────────────

_real_build_block = ms.build_situational_block


class CountingBlock:
    """Wraps the production block builder so a turn's calls can be counted."""

    def __init__(self):
        self.calls = 0
        self.args = []

    def __call__(self, character_name, message):
        self.calls += 1
        self.args.append((character_name, message))
        return _real_build_block(character_name, message)


block_builder = CountingBlock()
ms.build_situational_block = block_builder

memory_mod.load_memories = lambda name: STORE.get(name, [])
account_mod.is_player_controlled = lambda name: False
pending_reports.trigger_sofort_thought_if_applicable = lambda a, b: False
embedding_mod.current_model_id = lambda: "stub:unit-vectors"
ms.DbVectorCache = DictCache
chat_engine.build_chat_context = lambda *a, **kw: make_ctx(_MODE[0])
_MODE = ["single"]


def run_turn(trigger=TRIGGER, responder=RESPONDER, speaker=SPEAKER,
             mode="single", embed=None):
    """One room reply. Returns (reply, queue, embed stub)."""
    global HISTORY
    HISTORY = [dict(m) for m in HISTORY_SNAPSHOT]
    if trigger != TRIGGER:
        HISTORY[-1]["content"] = f"{speaker}: {trigger}"
    _MODE[0] = mode
    stub_embed = embed if embed is not None else CountingEmbed()
    embedding_mod.embed = stub_embed
    queue = StubQueue()
    llm_queue_mod.get_llm_queue = lambda: queue
    block_builder.calls = 0
    block_builder.args = []
    reply = chat_engine.run_chat_turn(
        "", responder, speaker, trigger, "in_person", "character_talk", False,
        room_stream=None, respond_opportunity=False,
        addressed_to=[responder])
    return reply, queue, stub_embed


def chat_call(queue):
    for call in queue.calls:
        if call["task_type"] != "intent":
            return call
    return None


def last_user(queue):
    call = chat_call(queue)
    return call["messages"][-1] if call else {}


BLOCK_HEADER = "[You remember, and it bears on what was just said"
EXPECTED_BLOCK = f"{BLOCK_HEADER} — use only what fits, never invent details:]\n- {KIRA_HIT}"
EXPECTED_WITHOUT = f"{TRANSCRIPT_LINE}\n\n{MOMENT}"
EXPECTED_WITH = f"{EXPECTED_WITHOUT}\n\n{EXPECTED_BLOCK}"


print("a) the on-topic trigger puts the matching fact behind the scene state")
reply_a, queue_a, embed_a = run_turn()
msg_a = last_user(queue_a)
check("the turn answered", reply_a, REPLY)
check("the last message is the user turn", msg_a.get("role"), "user")
check("the last user message is line + scene state + block",
      msg_a.get("content"), EXPECTED_WITH)
_pos_block = msg_a.get("content", "").find(BLOCK_HEADER)
_pos_end = msg_a.get("content", "").find("[END OF SCENE STATE]")
check("the block sits BEHIND the scene state",
      _pos_block >= 0 and _pos_end >= 0 and _pos_block > _pos_end, True)
check("the memory below the threshold stayed out",
      KIRA_MISS in msg_a.get("content", ""), False)
check("the block was built for the responder, with the trigger as query",
      block_builder.args, [(RESPONDER, TRIGGER)])
check("exactly one embedding of the message, then the two memories",
      embed_a.calls, 3)

print("b) an off-topic trigger leaves the user turn as it was")
reply_b, queue_b, _ = run_turn(trigger=OFF_TOPIC)
msg_b = last_user(queue_b)
check("still answered", reply_b, REPLY)
check("no block in the user turn", BLOCK_HEADER in msg_b.get("content", ""), False)
check("the user turn is line + scene state, nothing else",
      msg_b.get("content"), f"{OFF_TOPIC_LINE}\n\n{MOMENT}")

print("c) the switch costs nothing when it is off")
config._CONFIG.setdefault("memory", {})["situational_enabled"] = False
try:
    reply_c, queue_c, embed_c = run_turn()
    msg_c = last_user(queue_c)
    check("still answered", reply_c, REPLY)
    check("no block", BLOCK_HEADER in msg_c.get("content", ""), False)
    check("the user turn is the one from before the feature",
          msg_c.get("content"), EXPECTED_WITHOUT)
    check("the embedding backend was never asked", embed_c.calls, 0)
finally:
    config._CONFIG["memory"].pop("situational_enabled", None)

print("d) an exploding embedding backend is silence, not a failed turn")
reply_d, queue_d, embed_d = run_turn(embed=CountingEmbed(raises=True))
check("the reply came through", reply_d, REPLY)
check("no block", BLOCK_HEADER in last_user(queue_d).get("content", ""), False)
check("the user turn is the one from before the feature",
      last_user(queue_d).get("content"), EXPECTED_WITHOUT)
check("it did try once", embed_d.calls, 1)

print("e) the memories are the responder's, never the speaker's")
reply_e, queue_e, _ = run_turn()
content_e = last_user(queue_e).get("content", "")
check("the responder's fact is there", KIRA_HIT in content_e, True)
check("the speaker's equally close fact is not", DAN_FACT in content_e, False)

print("f) rp_first: the tool decision of the same turn carries no block")
reply_f, queue_f, _ = run_turn(mode="rp_first")
deadline = time.time() + 5.0
while time.time() < deadline and not any(
        c["task_type"] == "intent" for c in queue_f.calls):
    time.sleep(0.05)
tool_calls = [c for c in queue_f.calls if c["task_type"] == "intent"]
check("the tool decision ran", len(tool_calls), 1)
if tool_calls:
    tool_text = "\n".join(m.get("content", "") for m in tool_calls[0]["messages"])
    check("no block in the tool decision", BLOCK_HEADER in tool_text, False)
    check("and none of its memories either", KIRA_HIT in tool_text, False)
check("the chat call still carried it",
      BLOCK_HEADER in last_user(queue_f).get("content", ""), True)
check("the block was built ONCE for the whole turn", block_builder.calls, 1)

print("g) the system prompt and the history stay untouched")
sys_a = chat_call(queue_a)["messages"][0]
sys_b = chat_call(queue_b)["messages"][0]
check("system role", sys_a.get("role"), "system")
check("byte-identical with and without a matching memory",
      sys_a.get("content"), sys_b.get("content"))
check("the system prompt is exactly what the builder handed over",
      sys_a.get("content"), SYSTEM)
check("nothing leaked into it", BLOCK_HEADER in sys_a.get("content", ""), False)
check("the history dicts were not mutated", HISTORY, HISTORY_SNAPSHOT)
check("the history reached the LLM unchanged",
      chat_call(queue_a)["messages"][1:-1], HISTORY_SNAPSHOT[:-1])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
