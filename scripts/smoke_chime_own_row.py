#!/usr/bin/env python3
"""Smoke: a character never answers the same line twice (B6).

Usage:  ./.venv/bin/python scripts/smoke_chime_own_row.py

No server, no network, no LLM, no real world: a throwaway storage root
(``paths.init`` BEFORE the first app import); every world read the two code
paths make is stubbed on its module, so the fixture below is all they see.

THE RULE (plan-befundrunde-2026-09-29, B6 + its binding review notes)
---------------------------------------------------------------------------
1. ``AgentLoop._maybe_active_conversation_chime``: when the newest relevant
   line (content, no whisper_meta, not the narrator) is the character's OWN,
   it has answered already -> None. The backstop is the dispatch's rule
   (``_avatar_holds_floor``): effectively 1 while a non-idle avatar is in
   earshot, else ``_chime_backstop`` (5).
2. ``chat_engine.run_chat_turn``: right after the SKIP gate, ONLY on an
   optional turn (``respond_opportunity`` or ``winding_down``), a reply whose
   ``fuzzy_signature`` equals the one of the character's own last line in its
   room stream is dropped -> "" (nothing stored, no tool phase, no
   post-processing) — but only for a signature of >= 20 characters.

HAND-DERIVED EXPECTATIONS
---------------------------------------------------------------------------
Fixture: Mira (NPC) and Kai (avatar) in "tavern"/"hall"; room key
"tavern/hall"; all lines 10 s old (well inside the 240 s activity window).
Chime:
  [1] stream Kai -> Mira (Mira newest)             -> None
  [2] stream Mira -> Kai (Kai newest)              -> the chime on Kai's line
  [3] stream Kai -> Mira -> narrator (newest)      -> None (the narrator is
      skipped, Mira's own line is the newest relevant one)
  [4] [2] with 1 AI round in the room and Kai (player-controlled) in
      earshot, avatar clock unset (= not idle)     -> None (backstop 1)
  [5] [4] but nobody in earshot is an avatar       -> the chime (backstop 5)
  [6] [4] but Kai idle for 9 min (timeout 8 min)   -> the chime
  [7] [4] with 0 AI rounds                          -> the chime
  [8] the chime does not start the avatar clock (it only reads it): after
      [4] the idle map is still empty.
run_chat_turn (fake LLM answer; Mira's own last line in the stream is
"Das ist wirklich ein schöner Abend hier, findest du nicht?"; its signature
"dasistwirklicheinschöneraben…" is well over 20 characters):
  [9]  the SAME text, respond_opportunity         -> ""
  [10] the same words with other punctuation and a mood marker
       ("**I feel happy** Das ist wirklich ein schöner Abend hier — findest
       du nicht!")                                   -> "" (fuzzy match)
  [11] the SAME text on an OBLIGATORY turn (neither flag) -> returned as is
  [12] the SAME text, winding_down                  -> ""
  [13] a different sentence, respond_opportunity   -> returned
  [14] own last line "Ja.", reply "Ja." (signature "ja", 2 < 20),
       respond_opportunity                          -> "Ja." returned
Every dropped case leaves the stubbed save/post-processing untouched: no
thread is started for the follow-up (the ``threading.Thread`` stand-in
counts 0 starts across [9], [10], [12]).
"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="chime-own-row-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

import app.core.perception as perception_mod  # noqa: E402
import app.core.room_entry as room_entry_mod  # noqa: E402
import app.models.account as account_mod  # noqa: E402
import app.models.character as character_mod  # noqa: E402
import app.models.perception_store as pstore_mod  # noqa: E402
from app.core.agent_loop import AgentLoop  # noqa: E402
from app.core.perception import STORYTELLER_SPEAKER  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402

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


# ------------------------------------------------------------------ fixture
LOC, ROOM, KEY = "tavern", "hall", "tavern/hall"
STREAM = {"rows": []}
AVATARS = {"Kai"}
ROOM_PEOPLE = ["Mira", "Kai"]
_TS = (utc_now().timestamp() - 10)


def _row(speaker, content):
    from datetime import datetime, timezone
    ts = datetime.fromtimestamp(_TS, tz=timezone.utc).isoformat()
    return {"speaker": speaker, "content": content, "ts": ts, "meta": {},
            "kind": "spoken"}


character_mod.get_character_current_location = lambda name, **kw: LOC
character_mod.get_character_current_room = lambda name, **kw: ROOM
pstore_mod.get_character_room_stream = (
    lambda perceiver, loc, room, limit=100, include_meta_lines=False:
    list(STREAM["rows"])[-limit:])
account_mod.is_player_controlled = lambda name: name in AVATARS
room_entry_mod.characters_in_room = lambda loc, room, exclude=None: list(ROOM_PEOPLE)
perception_mod.nearby_in_the_open = lambda who: []

KAI_LINE = "Erzähl mir von deiner Reise."
MIRA_LINE = "Das ist wirklich ein schöner Abend hier, findest du nicht?"

loop = AgentLoop()

# ------------------------------------------------------------------ chime
print("[1]-[3] own newest line -> no chime")
STREAM["rows"] = [_row("Kai", KAI_LINE), _row("Mira", MIRA_LINE)]
check("[1] own line newest", loop._maybe_active_conversation_chime("Mira"), None)
STREAM["rows"] = [_row("Mira", MIRA_LINE), _row("Kai", KAI_LINE)]
res = loop._maybe_active_conversation_chime("Mira")
check("[2] other's line newest -> chime speaker", (res or {}).get("speaker"), "Kai")
check("[2] chime content", (res or {}).get("content"), KAI_LINE)
STREAM["rows"] = [_row("Kai", KAI_LINE), _row("Mira", MIRA_LINE),
                  _row(STORYTELLER_SPEAKER, "The fire crackles.")]
check("[3] narrator newest, own line before it",
      loop._maybe_active_conversation_chime("Mira"), None)

print("[4]-[8] backstop follows the avatar floor")
STREAM["rows"] = [_row("Mira", MIRA_LINE), _row("Kai", KAI_LINE)]
loop._room_ai_turns[KEY] = 1
check("[4] avatar present, 1 AI round", loop._maybe_active_conversation_chime("Mira"), None)
check("[8] chime left the avatar clock alone", dict(loop._room_avatar_idle), {})
AVATARS.clear()
res = loop._maybe_active_conversation_chime("Mira")
check("[5] no avatar in earshot -> chime", (res or {}).get("speaker"), "Kai")
AVATARS.add("Kai")
loop._room_avatar_idle[KEY] = utc_now().timestamp() - 9 * 60
res = loop._maybe_active_conversation_chime("Mira")
check("[6] avatar idle past the timeout -> chime", (res or {}).get("speaker"), "Kai")
loop._room_avatar_idle.clear()
loop._room_ai_turns[KEY] = 0
res = loop._maybe_active_conversation_chime("Mira")
check("[7] no AI round yet -> chime", (res or {}).get("speaker"), "Kai")

# ------------------------------------------------------------------ run_chat_turn
print("[9]-[14] run_chat_turn drops a word-for-word repeat on optional turns")
from app.core import chat_engine  # noqa: E402
import app.core.llm_queue as llm_queue_mod  # noqa: E402
import app.core.memory_situational as msit_mod  # noqa: E402

ANSWER = {"text": ""}


class _Resp:
    def __init__(self, content):
        self.content = content
        self.usage = None


class _FakeQueue:
    def submit(self, **kw):
        return _Resp(ANSWER["text"])


llm_queue_mod.get_llm_queue = lambda: _FakeQueue()
msit_mod.build_situational_block = lambda *a, **k: ""
chat_engine.build_chat_context = lambda *a, **k: {
    "llm": object(), "system_content": "sys", "messages": [{"role": "user",
                                                          "content": "Kai: hi"}],
    "moment_content": "", "room_mode": True, "mode": "rp_first",
    "tools_dict": {}, "tool_system_content": "", "tool_llm": None,
    "agent_config": {}, "full_chat_history": [], "user_display_name": "Kai",
    "speaker": "Kai", "medium": "in_person"}
import app.core.pending_reports as pr_mod  # noqa: E402
pr_mod.trigger_sofort_thought_if_applicable = lambda *a, **k: False

STARTS = {"n": 0}


class _CountingThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        STARTS["n"] += 1


def turn(reply, *, opportunity=False, winding=False, post=True):
    ANSWER["text"] = reply
    return chat_engine.run_chat_turn(
        "", "Mira", "Kai", KAI_LINE, post_process=post,
        respond_opportunity=opportunity, winding_down=winding)


STREAM["rows"] = [_row("Kai", "Wie war dein Tag?"), _row("Mira", MIRA_LINE),
                  _row("Kai", KAI_LINE)]
_real_thread = threading.Thread
threading.Thread = _CountingThread
try:
    check("[9] same text, opportunity", turn(MIRA_LINE, opportunity=True), "")
    check("[10] same words, other punctuation + marker",
          turn("**I feel happy** Das ist wirklich ein schöner Abend hier — "
               "findest du nicht!", opportunity=True), "")
    check("[12] same text, winding down", turn(MIRA_LINE, winding=True), "")
    check("dropped turns started no follow-up thread", STARTS["n"], 0)
    check("[11] same text on an obligatory turn", turn(MIRA_LINE), MIRA_LINE)
    _other = "Die Reise war lang, aber das Meer war die ganze Zeit ruhig."
    check("[13] a different sentence", turn(_other, opportunity=True), _other)
    STREAM["rows"] = [_row("Kai", "Kommst du mit?"), _row("Mira", "Ja."),
                      _row("Kai", "Wirklich?")]
    check("[14] a short 'Ja.' twice is kept", turn("Ja.", opportunity=True), "Ja.")
finally:
    threading.Thread = _real_thread

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + "; ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
