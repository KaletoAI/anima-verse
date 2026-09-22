#!/usr/bin/env python3
"""Smoke: a task the player gives in chat becomes an INTENT of the character.

Usage:  ./.venv/bin/python scripts/smoke_player_task_intent.py

No server, no network, no real world: a throwaway storage root (``paths.init``
BEFORE the first app import) and a fresh schema in it.

THE RULE
---------------------------------------------------------------------------
There is exactly ONE marker grammar, taught by exactly ONE text
(``shared/templates/llm/chat/intent_markers.md``) and parsed by exactly one
function (``intents.parse_and_apply_intent_markers``):

    [INTENT: <title> | <description> | when=… | prio=<1-5> | by=<player|self>]

``by=player`` says the task was given by the person in the conversation, which
is what ``source="human"`` records; anything else, and a missing ``by=``, is
the character's own plan (``source="character"``).  The legacy
``[NEW_ASSIGNMENT: <title> | <role> | <description> | <priority> |
<duration_minutes>]`` marker — which the rp_first tool prompt still demanded
while nothing had written the ``assignments`` table since June — is gone.

HAND-DERIVED EXPECTATIONS
---------------------------------------------------------------------------
  [1] "[INTENT: Bring the book | from the library | when=in:2h | prio=2 |
      by=player]" creates ONE intent with
        source      "human"      (by=player)
        title       "Bring the book"
        description "from the library"   (the one field without an "=")
        priority    2
        trigger     {"kind": "at_time", "run_date": <canonical GAME stamp>}
        expires_at  == trigger.run_date
      and that stamp is exactly 2 GAME hours after now: read the game clock
      before and after the call, then
        (before + 7200 s) <= parse(expires_at) <= (after + 7200 s).
      7200 = 2 * 3600 by hand, and ``_when_to_trigger`` builds it as
      ``game_time() + GameDuration.of(seconds=…)`` — GAME time, not a
      ``datetime``: the whole comparison is done in GameTime seconds.
  [2] The SAME marker without "by=player" -> source "character".  Nothing
      else changes.
  [3] "when=standing" -> trigger kind "standing" and expires_at "" — a
      standing task never expires on its own.
  [4] The rp_first flow, at unit level and end to end:
        raw      = the RP prose, WITH the marker in it
        tool_txt = the tool LLM's decision text, with the SAME marker again
      chat_engine feeds post-processing
        _merge_marker_lines(_intent_markers(raw), _extract_markers(tool_txt, clean))
      so the parser sees the marker line EXACTLY ONCE -> exactly ONE new
      intent, although both halves of the turn carried it.  (Before the fix
      the character's own marker was stripped by ``clean_response`` and never
      reached the parser at all; in the streaming path the tool LLM's markers
      were yielded as an ``ExtractionEvent`` that nobody consumed.)
      [4b] Only the tool LLM has it -> still exactly one.
      [4c] Neither has it -> none.
  [4d] The ROOM tool-decision prompt teaches the same marker: the rendered
      ``chat_engine._rp_tool_decision_input`` carries the syntax line
      "[INTENT: <title>" EXACTLY once (it comes from the one fragment, so a
      second copy would mean the text was pasted a second time), and the
      ``by=player`` token with it.  That prompt is the LIVE chat path — the
      streaming prompt runs thoughts/act/story — so without it only the
      character's own prose could ever produce an intent in room chat.
      The movement-marker suppression does not reach it: with
      ``agent_name=""`` -> ``_move_refusal`` truthy ->
      ``tool_decision_guardrails(with_markers=False)``, which drops ONLY the
      "**I am at ...**" hard rule; the plan/task marker is still taught.
  [5] The string "[NEW_ASSIGNMENT" appears in no shipped source under app/,
      shared/templates/, plugins/ (symlinked packs and marketplace installs
      skipped), docs/, README.md — expected count 0.
  [6] ``chat_engine._announce_player_tasks`` records ONE display-only
      storyteller line for the ``source="human"`` intent of a CHAT turn
      (``extraction_context={"source": "user_chat"}``), and NONE for
        - a ``source="character"`` intent (a plan of its own), or
        - a thought turn (``{"source": "thought"}``) — nobody watched it.
      The line is English and display-only:
        content "📝 Mira Sol takes on: Bring the book"
        meta    {"display_only": True, "intent": True}
        speaker STORYTELLER_SPEAKER
      ``record_utterance`` is stubbed on ``app.core.perception``; the helper
      imports it from there at call time.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
STORAGE = Path(tempfile.mkdtemp(prefix="player-task-intent-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="player-task-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import perception as perception_mod  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.perception import STORYTELLER_SPEAKER  # noqa: E402
from app.core.timeutils import game_time  # noqa: E402
from app.core.streaming import _extract_markers, _intent_markers  # noqa: E402
from app.core.chat_engine import (_announce_player_tasks,  # noqa: E402
                                  _merge_marker_lines, _rp_tool_decision_input,
                                  clean_response)
from app.models.intents import (list_intents,  # noqa: E402
                                parse_and_apply_intent_markers)

CHAR = "Mira Sol"
MARKER = ("[INTENT: Bring the book | from the library | when=in:2h "
          "| prio=2 | by=player]")

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


def check_true(label, ok, detail=""):
    global CHECKED
    CHECKED += 1
    print(f"  {'OK ' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def drop_all():
    for it in list_intents():
        from app.models.intents import delete_intent
        delete_intent(it["id"])


# ------------------------------------------------- [1] by=player -> human

print("[1] by=player becomes source human, in:2h becomes a GAME deadline")
_before = game_time().total_seconds
created = parse_and_apply_intent_markers(CHAR, f"Sure, I'll do that.\n{MARKER}")
_after = game_time().total_seconds
check("intents created", len(created), 1)
it = created[0] if created else {}
check("source", it.get("source"), "human")
check("title", it.get("title"), "Bring the book")
check("description", it.get("description"), "from the library")
check("priority", it.get("priority"), 2)
check("trigger kind", (it.get("trigger") or {}).get("kind"), "at_time")
_run = (it.get("trigger") or {}).get("run_date", "")
check("expires_at == trigger.run_date", it.get("expires_at"), _run)
_secs = GameTime.parse(_run).total_seconds if _run else -1
check_true("expires_at is 2 GAME hours ahead",
           _before + 7200 <= _secs <= _after + 7200,
           f"{_before}+7200 <= {_secs} <= {_after}+7200")
drop_all()

# ------------------------------------------- [2] no by= -> the own plan

print("[2] without by= the same marker is the character's own plan")
created = parse_and_apply_intent_markers(
    CHAR, "[INTENT: Bring the book | from the library | when=in:2h | prio=2]")
check("intents created", len(created), 1)
check("source", (created[0] if created else {}).get("source"), "character")
check("priority", (created[0] if created else {}).get("priority"), 2)
drop_all()

# -------------------------------------------- [3] standing has no deadline

print("[3] a standing task carries no expiry")
created = parse_and_apply_intent_markers(
    CHAR, "[INTENT: Watch the harbour | keep an eye out | when=standing | by=player]")
check("intents created", len(created), 1)
it = created[0] if created else {}
check("trigger kind", (it.get("trigger") or {}).get("kind"), "standing")
check("expires_at", it.get("expires_at"), "")
check("source", it.get("source"), "human")
drop_all()

# ------------------------------- [4] the rp_first flow feeds the parser once

print("[4] the rp_first marker flow reaches the parser exactly once")
raw = f'"Of course," she says, and pockets her notebook.\n{MARKER}'
clean = clean_response(raw)
check_true("clean_response strips the marker from the reply",
           "[INTENT:" not in clean, clean)
tool_txt = f"NONE\n{MARKER}\n**I feel calm**"
merged = _merge_marker_lines(_intent_markers(raw),
                             _extract_markers(tool_txt, clean))
check("merged marker lines", merged.count("[INTENT:"), 1)
created = parse_and_apply_intent_markers(CHAR, merged)
check("intents created (prose + tool both had it)", len(created), 1)
check("source", (created[0] if created else {}).get("source"), "human")
drop_all()

print("[4b] only the tool LLM emitted it")
merged = _merge_marker_lines(_intent_markers("Of course."),
                             _extract_markers(f"NONE\n{MARKER}", "Of course."))
created = parse_and_apply_intent_markers(CHAR, merged)
check("intents created", len(created), 1)
drop_all()

print("[4c] nobody emitted one")
merged = _merge_marker_lines(_intent_markers("Of course."),
                             _extract_markers("NONE", "Of course."))
created = parse_and_apply_intent_markers(CHAR, merged)
check("intents created", len(created), 0)
drop_all()

print("[4d] the ROOM tool-decision prompt teaches the same marker, once")
_room_prompt = _rp_tool_decision_input(
    "Bring me the book from the library.", '"Of course," she says.', {},
    agent_name="")
check("syntax line occurrences", _room_prompt.count("[INTENT: <title>"), 1)
check_true("the by=player token is in it", "by=<player|self>" in _room_prompt)
check_true("the movement hard rule is suppressed (agent_name='')",
           "**I am at ...** marker per answer" not in _room_prompt)
check_true("...but the plan/task marker is not",
           "[INTENT_DONE: <id>]" in _room_prompt)

# ------------------------------------------- [5] the legacy marker is gone

print("[5] the legacy [NEW_ASSIGNMENT marker is in no shipped source")
NEEDLE = "[NEW_ASSIGNMENT"
SKIP_PARTS = {"__pycache__", "node_modules", "dist", "installed",
              "attraction", "intimacy", "nsfw_anatomy"}
SUFFIXES = {".py", ".md", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml",
            ".yml", ".txt", ".html", ".css"}
hits = []
for target in ("app", "shared/templates", "plugins", "docs", "README.md"):
    root = REPO / target
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = [f for f in root.rglob("*")
                 if f.is_file() and not f.is_symlink()
                 and f.suffix.lower() in SUFFIXES
                 and not (SKIP_PARTS & set(f.relative_to(REPO).parts))]
    else:
        continue
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if NEEDLE in line:
                hits.append(f"{f.relative_to(REPO)}:{n}")
check("[NEW_ASSIGNMENT occurrences", hits, [])

# ------------------------------------- [6] the display-only feedback line

print("[6] the player feedback line")
RECORDED = []
perception_mod.record_utterance = lambda **kw: RECORDED.append(kw) or 1

_human = {"source": "human", "title": "Bring the book"}
_own = {"source": "character", "title": "Sort the shelves"}

_announce_player_tasks(CHAR, [_human], {"source": "user_chat"})
check("lines for a player task in a chat turn", len(RECORDED), 1)
if RECORDED:
    kw = RECORDED[0]
    check("speaker", kw.get("speaker"), STORYTELLER_SPEAKER)
    check("content", kw.get("content"), f"\U0001F4DD {CHAR} takes on: Bring the book")
    check("meta", kw.get("perception_meta"),
          {"display_only": True, "intent": True})
    check("anchor", kw.get("anchor"), CHAR)

RECORDED.clear()
_announce_player_tasks(CHAR, [_own], {"source": "user_chat"})
check("lines for the character's own plan", len(RECORDED), 0)

RECORDED.clear()
_announce_player_tasks(CHAR, [_human], {"source": "thought"})
check("lines for a thought turn", len(RECORDED), 0)

print()
if FAILURES:
    print(f"RESULT: FAIL — {len(FAILURES)} of {CHECKED} checks failed: "
          + "; ".join(FAILURES))
    sys.exit(1)
print(f"RESULT: PASS — {CHECKED} checks")
