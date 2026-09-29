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

``by=player`` says the OTHER person explicitly asked for it (the request
stands in their words), which is what ``source="human"`` records; anything
else, and a missing ``by=``, is the character's own plan
(``source="character"``).  The legacy
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
        expires_at  == trigger.run_date + 1 game hour (3600 s of grace, so
                       the scheduled bump still finds the intent active)
      and run_date is exactly 2 GAME hours after now: read the game clock
      before and after the call, then
        (before + 7200 s) <= parse(run_date) <= (after + 7200 s).
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

  B5 of plan-befundrunde-2026-09-29 (duplicates, ids, counters, expiry):
  [7] Duplicates are not created (``find_duplicate``: titles normalized word
      by word — lowercase, punctuation dropped — equal or contained on word
      boundaries, the shorter one >= 6 characters):
        existing "Buy bread at the market"
        "Buy bread at the market"      -> equal            -> 0 created
        "buy BREAD!"                   -> "buy bread" (9) inside -> 0 created
        "Buy breadcrumbs"              -> "buy breadcrumbs" is not a word-run
                                          of the other      -> 1 created
        "Rest" twice                   -> "rest" has 4 < 6 characters, never a
                                          duplicate         -> 1 created each
        "Visit the lighthouse" + "Visit the lighthouse keeper" in ONE text
                                       -> the second contains the first,
                                          created a line earlier -> 1 created
        another character's "Buy bread at the market" -> other owner -> 1
  [8] Every entry of ``build_intents_prompt_section`` carries "(id <id>)"
      (exactly as many "(id " as active intents: 3 here), the header is
      English; with 14 active intents and ``max_entries=12`` it shows 12
      entries plus "(+2 more"; ``build_open_intents_brief`` shows
      "  <id> | <title>"; the room tool-decision prompt for this character
      lists it after the marker grammar.
  [9] ``auto_track_progress`` leaves ``target_count == 0`` alone: its progress
      stays [] after a tool use, while a target_count=2 intent goes 1 -> 2 and
      is done on the second call; with only count-less intents it returns None.
 [10] A thought turn applies its markers ONCE: in the tracked Python under
      app/ and plugins/ the call ``parse_and_apply_intent_markers(`` (not its
      ``def``) occurs exactly 1 time, in app/core/chat_engine.py
      (post_process_response — the thought turn goes through it too).
      Before-proof pinned to commit 03717c17: there it occurred >= 2 times
      (the second in app/core/thoughts.py).
 [11] Expiry in GAME time, set at creation (seconds by hand):
        own plan when=now       -> now + 3600
        own plan when=standing  -> now + 3 * 86400 = 259200 (default TTL)
        with intents.self_intent_ttl_days = 5 -> now + 432000
        with intents.self_intent_ttl_days = 0 -> "" (never)
        player task when=now    -> ""  (a player's task stays until done)
 [12] INTENT_DONE / INTENT_PROGRESS only for the owner or a participant:
        Mira on Other's intent            -> status stays "active", no progress
        Mira as participant of Other's    -> progress note recorded
        Mira on her own intent            -> "done"
 [13] The admin route takes RELATIVE game minutes and computes the stamps:
        create {duration_minutes: 60, trigger {kind at_time, run_in_minutes: 360}}
          -> expires_at = now + 3600, run_date = now + 21600, no run_in_minutes
             stored; PATCH {duration_minutes: 1440} -> expires_at = now + 86400;
        an at_time trigger with neither run_date nor run_in_minutes -> HTTP 400.
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
_secs = GameTime.parse(_run).total_seconds if _run else -1
check("expires_at == run_date + 1 game hour",
      GameTime.parse(it["expires_at"]).total_seconds if it.get("expires_at") else -1,
      _secs + 3600)
check_true("run_date is 2 GAME hours ahead",
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

# --------------------------------------------------- B5 [7] duplicates

from app.core import agent_loop as agent_loop_mod  # noqa: E402
from app.models.intents import (add_progress, auto_track_progress,  # noqa: E402
                                build_intents_prompt_section,
                                build_open_intents_brief, create_intent,
                                find_duplicate, get_intent)


class _FakeLoop:
    def bump(self, *a, **kw):
        return None


# when=now bumps the owner through the agent loop — never start a real one.
agent_loop_mod.get_agent_loop = lambda: _FakeLoop()
OTHER = "Other Person"

print("[7] duplicates are not created")
drop_all()
base = parse_and_apply_intent_markers(CHAR, "[INTENT: Buy bread at the market]")
check("the first one is created", len(base), 1)
check("equal title", len(parse_and_apply_intent_markers(
    CHAR, "[INTENT: Buy bread at the market]")), 0)
check("contained title (normalized)", len(parse_and_apply_intent_markers(
    CHAR, "[INTENT: buy BREAD!]")), 0)
check("find_duplicate names the existing one",
      (find_duplicate(CHAR, "buy bread") or {}).get("id"),
      base[0]["id"] if base else None)
check("not on a word boundary -> created", len(parse_and_apply_intent_markers(
    CHAR, "[INTENT: Buy breadcrumbs]")), 1)
check("short title, first", len(parse_and_apply_intent_markers(
    CHAR, "[INTENT: Rest]")), 1)
check("short title, again (< 6 chars is never a duplicate)",
      len(parse_and_apply_intent_markers(CHAR, "[INTENT: Rest]")), 1)
check("two markers in one text, the second covers the first",
      len(parse_and_apply_intent_markers(
          CHAR, "[INTENT: Visit the lighthouse]\n"
                "[INTENT: Visit the lighthouse keeper]")), 1)
check("another owner's same title is no duplicate",
      len(parse_and_apply_intent_markers(OTHER, "[INTENT: Buy bread at the market]")), 1)
drop_all()

# --------------------------------------------------- B5 [8] ids in the prompt

print("[8] the prompt section shows the ids")
mine = [create_intent(owner=CHAR, title=f"Plan {n}",
                      participants={CHAR: {"role": "", "progress": []}})
        for n in ("alpha", "beta", "gamma")]
section = build_intents_prompt_section(CHAR)
check("'(id ' occurrences", section.count("(id "), 3)
check_true("every id is in it", all(f"(id {m['id']})" in section for m in mine))
check_true("the header is English", "== CURRENT PLANS & TASKS" in section, section[:60])
brief = build_open_intents_brief(CHAR)
check_true("brief line '  <id> | <title>'",
           f"  {mine[0]['id']} | Plan alpha" in brief, brief)
_room = _rp_tool_decision_input("Hello.", '"Hi," she says.', {}, agent_name=CHAR)
_i_grammar = _room.find("[INTENT_DONE: <id>]")
_i_list = _room.find(f"{mine[0]['id']} | Plan alpha")
check_true("the room tool prompt lists the open plan after the grammar",
           0 <= _i_grammar < _i_list, f"{_i_grammar} < {_i_list}")
for n in range(11):
    create_intent(owner=CHAR, title=f"Extra plan {n}",
                  participants={CHAR: {"role": "", "progress": []}})
capped = build_intents_prompt_section(CHAR, max_entries=12)
check("capped entries", capped.count("(id "), 12)
check_true("capped tail line", "(+2 more" in capped, capped[-60:])
drop_all()

# --------------------------------------- B5 [9] auto_track_progress counters

print("[9] auto_track_progress leaves count-less intents alone")
free = create_intent(owner=CHAR, title="Free plan",
                     participants={CHAR: {"role": "", "progress": []}})
counted = create_intent(owner=CHAR, title="Take two photos", target_count=2,
                        participants={CHAR: {"role": "", "progress": []}})
res = auto_track_progress(CHAR, "image")
check("returned intent", (res or {}).get("intent_id"), counted["id"])
check("count-less progress", get_intent(free["id"])["participants"][CHAR]["progress"], [])
check("counted progress after 1", len(
    get_intent(counted["id"])["participants"][CHAR]["progress"]), 1)
auto_track_progress(CHAR, "image")
check("counted status after 2", get_intent(counted["id"])["status"], "done")
check("only count-less left -> None", auto_track_progress(CHAR, "image"), None)
check("count-less progress still", get_intent(free["id"])["participants"][CHAR]["progress"], [])
drop_all()

# ------------------------------------- B5 [10] one parse per thought turn

print("[10] exactly one call site of the marker parser")
import re as _re  # noqa: E402
import subprocess  # noqa: E402
CALL = _re.compile(r"(?<!def )\bparse_and_apply_intent_markers\(")
sites = []
for target in ("app", "plugins"):
    for f in (REPO / target).rglob("*.py"):
        if f.is_symlink() or {"installed", "__pycache__"} & set(f.relative_to(REPO).parts):
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if CALL.search(line):
                sites.append(f"{f.relative_to(REPO)}")
check("call sites", sites, ["app/core/chat_engine.py"])
_old = subprocess.run(
    ["git", "grep", "-c", "parse_and_apply_intent_markers(", "03717c17", "--",
     "app/core/thoughts.py", "app/core/chat_engine.py"],
    cwd=REPO, capture_output=True, text=True).stdout
_old_n = sum(int(ln.rsplit(":", 1)[1]) for ln in _old.splitlines() if ":" in ln)
check_true("before-proof: commit 03717c17 had >= 2", _old_n >= 2, _old.strip())

# ------------------------------------------ B5 [11] expiry in GAME time

print("[11] own plans expire in GAME time")


def _expiry_after(marker, owner=CHAR):
    before = game_time().total_seconds
    got = parse_and_apply_intent_markers(owner, marker)
    after = game_time().total_seconds
    exp = (got[0] if got else {}).get("expires_at", "")
    return before, (GameTime.parse(exp).total_seconds if exp else None), after


b, e, a = _expiry_after("[INTENT: Fetch water now | when=now]")
check_true("when=now -> +3600", e is not None and b + 3600 <= e <= a + 3600, f"{b} {e} {a}")
b, e, a = _expiry_after("[INTENT: Learn the harp | when=standing]")
check_true("standing -> +259200 (3 days)", e is not None and b + 259200 <= e <= a + 259200,
           f"{b} {e} {a}")
config._CONFIG["intents"] = {"self_intent_ttl_days": 5}
b, e, a = _expiry_after("[INTENT: Paint the fence | when=standing]")
check_true("ttl 5 -> +432000", e is not None and b + 432000 <= e <= a + 432000, f"{b} {e} {a}")
config._CONFIG["intents"] = {"self_intent_ttl_days": 0}
check("ttl 0 -> never", _expiry_after("[INTENT: Mend the net | when=standing]")[1], None)
config._CONFIG.pop("intents", None)
check("player task when=now -> never",
      _expiry_after("[INTENT: Carry the crate | when=now | by=player]")[1], None)
drop_all()

# ------------------------------- B5 [12] DONE / PROGRESS only for participants

print("[12] DONE / PROGRESS only for the owner or a participant")
foreign = create_intent(owner=OTHER, title="Guard the gate",
                        participants={OTHER: {"role": "", "progress": []}})
shared = create_intent(owner=OTHER, title="Cook together",
                       participants={OTHER: {"role": "", "progress": []},
                                     CHAR: {"role": "", "progress": []}})
own = create_intent(owner=CHAR, title="Sweep the porch",
                    participants={CHAR: {"role": "", "progress": []}})
parse_and_apply_intent_markers(
    CHAR, f"[INTENT_DONE: {foreign['id']}]\n[INTENT_PROGRESS: {foreign['id']} | nope]")
check("foreign status", get_intent(foreign["id"])["status"], "active")
check("foreign participants", sorted(get_intent(foreign["id"])["participants"]), [OTHER])
parse_and_apply_intent_markers(CHAR, f"[INTENT_PROGRESS: {shared['id']} | chopped onions]")
check("participant progress", [p["note"] for p in
      get_intent(shared["id"])["participants"][CHAR]["progress"]], ["chopped onions"])
parse_and_apply_intent_markers(CHAR, f"[INTENT_DONE: {own['id']}]")
check("own status", get_intent(own["id"])["status"], "done")
drop_all()

# ------------------------------------ B5 [13] the admin route, game minutes

print("[13] the admin route turns relative minutes into GAME stamps")
from fastapi import HTTPException  # noqa: E402
from app.routes.intents import _create_route_sync, _patch_route_sync  # noqa: E402

_b = game_time().total_seconds
made = _create_route_sync({"title": "Deliver the letter", "owner": CHAR,
                           "duration_minutes": 60,
                           "trigger": {"kind": "at_time", "run_in_minutes": 360}})
_a = game_time().total_seconds
_exp = GameTime.parse(made["expires_at"]).total_seconds if made.get("expires_at") else -1
_rd = (made.get("trigger") or {}).get("run_date", "")
_rds = GameTime.parse(_rd).total_seconds if _rd else -1
check_true("create: expires_at = now + 3600", _b + 3600 <= _exp <= _a + 3600, str(_exp))
check_true("create: run_date = now + 21600", _b + 21600 <= _rds <= _a + 21600, str(_rds))
check("create: run_in_minutes not stored", "run_in_minutes" in made.get("trigger", {}), False)
_b = game_time().total_seconds
patched = _patch_route_sync(made["id"], {"duration_minutes": 1440})
_a = game_time().total_seconds
_exp = GameTime.parse(patched["expires_at"]).total_seconds if patched.get("expires_at") else -1
check_true("patch: expires_at = now + 86400", _b + 86400 <= _exp <= _a + 86400, str(_exp))
try:
    _create_route_sync({"title": "Undated", "owner": CHAR, "trigger": {"kind": "at_time"}})
    _status = 200
except HTTPException as _he:
    _status = _he.status_code
check("at_time without a time", _status, 400)
drop_all()

print()
if FAILURES:
    print(f"RESULT: FAIL — {len(FAILURES)} of {CHECKED} checks failed: "
          + "; ".join(FAILURES))
    sys.exit(1)
print(f"RESULT: PASS — {CHECKED} checks")
