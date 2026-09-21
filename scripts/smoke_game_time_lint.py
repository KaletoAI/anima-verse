#!/usr/bin/env python3
"""Lint the GAME-clock border: no legacy clock names, no datetime maths on
``GameTime``, no ``parse_iso`` on a persisted game stamp, no naive system clock.

Usage:
    ./.venv/bin/python scripts/smoke_game_time_lint.py

No server, no world DB, no imports of the scanned code: this is a pure TEXT
scan over ``app/``, ``plugins/`` and ``scripts/`` (``*.py``). It is the cheap
net under plan-game-calendar.md — the type border (``datetime`` = SYSTEM time,
:class:`~app.core.game_time.GameTime` = the world) is enforced by the types at
runtime, but a text scan catches the two shapes that slip past a type check: a
name that no longer exists sitting in a doc line, and a SYSTEM-time helper
pointed at a GAME stamp.

The five rules, each reported as ``file:line  RULE  <line>``:

  A  removed clock names — ``game_now(``, ``game_local_now(``,
     ``game_now_iso(``, ``to_world_tz(game``, ``_game_now(``. T1 deleted all
     of them; ``to_world_tz`` survives for SYSTEM stamps only, so pointing it
     at anything named ``game…`` is the same defect.
  B  ``datetime`` maths on the game clock — a line holding ``game_time()``
     together with ``.strftime(``, ``.weekday()``, ``.month``, ``.date()``,
     ``.astimezone(``, ``.isoformat(``, ``.timestamp()`` or ``timedelta``.
     ``GameTime`` has none of those members on purpose (game_time.py's class
     docstring); such a line either crashes or is operating on something else
     that only looks like the clock.
  C  ``parse_iso(`` on the same line as a PERSISTED GAME stamp
     (``started_at_game``, ``state_flag_since``, ``game_ts``,
     ``game_timestamp``, ``_registered_game``, ``sleep_start``, ``expires_at``,
     ``run_date``, ``anchor_game``, ``last_interaction_game``,
     ``last_decay_game``). Those are canonical ``Y0002-D109T14:00:00``
     strings — ``parse_iso`` would raise, or worse, read a legacy row and hand
     back a real date.
  D  day keys built from a real date in ``app/core/day_consolidation.py``:
     ``strftime("%Y-%m-%d")``. The game day is ``GameTime.day_key()``
     (``Y0002-D109``); a real calendar date as the key silently splits one game
     day across two rows the moment the tick factor is not 1.
  E  naive SYSTEM time inside ``app/``: ``datetime.now(``, ``_dt.now(`` or
     ``.fromisoformat(``. Every persisted stamp is written aware
     (``utc_now_iso()``), so a naive value never compares against one — it
     raises ``TypeError``. Where that ``TypeError`` sits inside a ``try`` the
     defect is SILENT: on 2026-09-11 ``memory_service.apply_extracted_memories``
     had killed every thought extraction for weeks and
     ``character_ops._score_memory_no_mutate`` had pinned ``age_days`` to its
     30.0 fallback, turning the recency boost permanently off. The pair
     ``utc_now()`` / ``parse_iso()`` from ``app.core.timeutils`` is the only
     way in; ``parse_iso`` reads a naive legacy stamp as UTC, which is the
     documented convention, not a shim. ``plugins/`` and ``scripts/`` are out
     of scope: a plugin parses calendar dates out of documents, and a script is
     not game logic.

     E also catches the second shape of the same defect: the RIGHT clock read
     for the WRONG question. ``utc_now()`` is aware and is exactly right for a
     technical stamp, so the rule never fires on the call itself — only on the
     COMPONENT that answers "what time is it in the world": ``.hour``,
     ``.minute``, ``.second``, ``.time()``, ``.date()`` off ``utc_now()`` /
     ``local_now()`` / ``to_world_tz()`` / ``to_local()``, plus
     ``date.today()`` / ``datetime.today()``. Time of day and the calendar day
     belong to the GAME clock: ``game_time().is_day()`` (the season's
     sunrise/sunset), ``.day_bucket()``, ``.day_key()``. On 2026-09-11
     ``prompt_builder._collect_location`` chose between ``image_prompt_day``
     and ``image_prompt_night`` from ``6 <= utc_now().hour < 18`` — the UTC
     hour, so the image prompt said "day" while the world was at midnight.
     A naive ``datetime.now().hour`` needs no extra pattern; the first half
     already has it.

Deliberately simple about comments: a line whose first non-blank character is
``#`` is skipped, and on any other line only the text BEFORE the first ``#`` is
scanned. That is what lets the modules which DOCUMENT the removal keep talking
about it in a trailing comment. Prose inside docstrings has no such marker, so
the three files whose docstrings legitimately name the removed helpers are
whitelisted per rule instead (WHITELIST below) — everywhere else a docstring
mentioning a deleted name is a finding, not an exception: it documents an API
that is gone.

Before it scans anything, the run puts the five rules against a table of
hand-written probe lines (PROBES) — one that must trip each rule plus the
exemptions that must stay silent. A scan that matches nothing would otherwise
print "clean" whether it works or not.

Exit code 0 = clean, 1 = at least one finding (or a broken rule).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("app", "plugins", "scripts")
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", ".git", "legacy",
             "installed"}

SELF = Path(__file__).resolve()

# ── rule A ──────────────────────────────────────────────────────────────
REMOVED_NAMES = ("game_local_now(", "game_now_iso(", "_game_now(",
                 "game_now(", "to_world_tz(game")
# The clock modules and the boot migration explain the removal in their
# docstrings — that prose is the documentation of the change, not a call site.
WHITELIST_A = {
    "app/core/game_time.py",
    "app/core/timeutils.py",
    "app/core/game_calendar_migration.py",
}

# ── rule B ──────────────────────────────────────────────────────────────
DATETIME_MEMBERS = (".strftime(", ".weekday()", ".month", ".date()",
                    ".astimezone(", ".isoformat(", ".timestamp()", "timedelta")

# ── rule C ──────────────────────────────────────────────────────────────
GAME_STAMP_FIELDS = ("started_at_game", "state_flag_since", "game_ts",
                     "game_timestamp", "_registered_game", "sleep_start",
                     "expires_at", "run_date", "anchor_game",
                     "last_interaction_game", "last_decay_game")
# The migration is the ONE place that legitimately reads a legacy ISO stamp
# out of these fields — that is its whole job.
WHITELIST_C = {"app/core/game_calendar_migration.py"}
# ``expires_at`` is also the column name of two SYSTEM-time TTLs that predate
# the game calendar and stay system time by design (plan-game-calendar.md § (e)
# lists only the INTENTS' expires_at as a game stamp): login sessions and the
# world events' ttl_hours. Whitelisted by file, so a game stamp appearing in a
# THIRD place still trips the rule.
WHITELIST_C_SYSTEM_TTL = {
    "app/core/sessions.py",
    "app/models/events.py",
    "scripts/test_session_sliding.py",
}

# ── rule D ──────────────────────────────────────────────────────────────
DAY_KEY_FILE = "app/core/day_consolidation.py"
DAY_KEY_PATTERNS = ('strftime("%Y-%m-%d")', "strftime('%Y-%m-%d')")

# ── rule E ──────────────────────────────────────────────────────────────
NAIVE_CLOCK = ("datetime.now(", "_dt.now(", ".fromisoformat(")
RULE_E_ROOT = "app/"
# Known technical stamps that are NOT game logic and stay as they are:
#   app/core/timeutils.py                 — the definition of the border itself
#   app/server.py:688–696                 — the startup timestamp file
#   app/core/game_calendar_migration.py:503 — date.fromisoformat on a legacy
#                                           day key; reading old rows IS its job
#   app/models/world.py:2178              — a file-name stamp
#   app/skills/video_generation_skill.py:234 — legacy skill, animate_created_at
WHITELIST_E = {
    "app/core/timeutils.py",
    "app/server.py",
    "app/core/game_calendar_migration.py",
    "app/models/world.py",
    "app/skills/video_generation_skill.py",
}

# Second half of E: a time-of-day / calendar-day COMPONENT taken off the system
# clock. The aware helpers are matched, never a bare ``utc_now()`` — that call
# is the documented way to stamp something, and it is everywhere.
SYSTEM_CLOCK_PART = re.compile(
    r"\b(?:utc_now|local_now|to_world_tz|to_local)\([^()]*\)"
    r"\.(?:hour|minute|second|time\(\)|date\(\))(?![A-Za-z_])")
# ``date.today()`` / ``datetime.today()`` reach the same answer without the
# detour through timeutils.
SYSTEM_TODAY = re.compile(r"\b(?:date|datetime)\.today\(\)")
# Files whose system-clock day/hour is NOT a statement about the world:
#   app/core/model_suitability.py:477 — a model-test record dates the
#       MEASUREMENT; capabilities are shared across worlds and describe the
#       model plus its hardware, not a game day.
WHITELIST_E_CLOCK = {
    "app/core/model_suitability.py",
}


def iter_python_files() -> Iterable[Path]:
    for root in ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    path = Path(dirpath) / fn
                    if path.resolve() != SELF:
                        yield path


def code_part(line: str) -> str:
    """The scannable part of a line: '' for a comment line, else the text
    before the first ``#``. Deliberately naive — a ``#`` inside a string ends
    the scan early, which can only ever hide a finding, never invent one."""
    if line.lstrip().startswith("#"):
        return ""
    return line.split("#", 1)[0]


def rules_for(rel: str, raw: str) -> List[str]:
    """Every rule the given source line breaks, as ``"<code> <detail>"``."""
    line = code_part(raw)
    if not line.strip():
        return []
    out: List[str] = []

    if rel not in WHITELIST_A:
        for name in REMOVED_NAMES:
            if name in line:
                out.append(f"A removed clock name {name!r}")
                break

    if "game_time()" in line:
        hit = [m for m in DATETIME_MEMBERS if m in line]
        if hit:
            out.append(f"B datetime maths on the game clock ({', '.join(hit)})")

    if ("parse_iso(" in line and rel not in WHITELIST_C
            and rel not in WHITELIST_C_SYSTEM_TTL):
        fields = [f for f in GAME_STAMP_FIELDS if f in line]
        if fields:
            out.append(f"C parse_iso on a game stamp ({', '.join(fields)})")

    if rel == DAY_KEY_FILE and any(p in line for p in DAY_KEY_PATTERNS):
        out.append("D day key built from a real date")

    if rel.startswith(RULE_E_ROOT) and rel not in WHITELIST_E:
        naive = [n for n in NAIVE_CLOCK if n in line]
        if naive:
            out.append("E naive system clock — use utc_now()/parse_iso "
                       f"({', '.join(naive)})")
        if rel not in WHITELIST_E_CLOCK:
            hit = SYSTEM_CLOCK_PART.search(line) or SYSTEM_TODAY.search(line)
            if hit:
                out.append("E the world's time of day off the system clock — "
                           f"use game_time() ({hit.group(0)})")

    return out


def scan(path: Path) -> List[Tuple[int, str, str]]:
    """Findings of one file as ``(lineno, rule, line)``."""
    rel = path.relative_to(REPO).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [(0, "READ", f"could not read {rel}: {e}")]

    return [(no, rule, raw.strip())
            for no, raw in enumerate(text.splitlines(), start=1)
            for rule in rules_for(rel, raw)]


# Hand-written probes: what each rule MUST catch and what it must let pass.
# Without these the scan could match nothing at all and still print "clean".
PROBES: Tuple[Tuple[str, str, str], ...] = (
    # (file the line pretends to live in, source line, expected rule code)
    ("app/core/chat_ops.py", "    now = game_now()", "A"),
    ("app/core/chat_ops.py", '    stamp = game_now_iso()', "A"),
    ("app/core/chat_ops.py", "    local = game_local_now()", "A"),
    ("app/core/travel_engine.py", "    now = _game_now()", "A"),
    ("app/routes/play.py", '    eta = to_world_tz(game_eta).isoformat()', "A"),
    ("app/core/act_engine.py", '    day = game_time().strftime("%A")', "B"),
    ("app/core/flag_lifecycle.py",
     "    until = game_time() + timedelta(hours=3)", "B"),
    ("app/core/thoughts.py", "    stamp = game_time().isoformat()", "B"),
    ("app/core/travel_engine.py",
     '    started = parse_iso(journey["started_at_game"])', "C"),
    ("app/models/character.py", '    since = parse_iso(p["state_flag_since"])', "C"),
    ("app/core/relationship_decay.py",
     '    last = parse_iso(rel["last_interaction_game"])', "C"),
    ("app/core/day_consolidation.py",
     '    key = utc_now().strftime("%Y-%m-%d")', "D"),
    ("app/core/memory_service.py",
     "    recent_cutoff = _dt.now() - _td(days=14)", "E"),
    ("app/core/character_ops.py",
     '    ts = _dt.fromisoformat(entry.get("timestamp", ""))', "E"),
    ("app/core/chat_ops.py", "    now = datetime.now()", "E"),
    ("app/core/prompt_builder.py", "    hour = utc_now().hour", "E"),
    ("app/core/scene_render.py",
     "    bg = resolve_background_path(loc, hour=utc_now().hour)", "E"),
    ("app/core/template_preview.py",
     "    today = utc_now().date().isoformat()", "E"),
    ("app/core/npc_windows.py", "    t = to_world_tz(stamp).time()", "E"),
    ("app/models/character.py", "    born = date.today()", "E"),
    # character_template.py used to be exempt here for _compute_age(); the
    # computation is gone, so the file is an ordinary one again.
    ("app/models/character_template.py", "    today = date.today()", "E"),
    # …and the exemptions, which must stay silent:
    ("app/core/chat_ops.py", "    # game_now() was removed in T1", ""),
    ("app/core/chat_ops.py", "    x = 1   # replaces game_now()", ""),
    ("app/core/timeutils.py", "    ``game_now`` is gone: game_now()", ""),
    ("app/core/game_calendar_migration.py",
     '    old = parse_iso(row["game_ts"])', ""),
    ("app/core/sessions.py", '    expires = parse_iso(row["expires_at"])', ""),
    ("app/core/thoughts.py", "    now = game_time()", ""),
    ("app/core/chat_ops.py", "    stamp = utc_now().isoformat()", ""),
    ("app/core/memory_service.py", "    x = utc_now() - parse_iso(ts)", ""),
    # …and the second half of E must not fire on a technical stamp:
    ("app/core/world_ops.py",
     "    name = f\"{loc}_{utc_now().strftime('%Y%m%d%H%M%S')}.png\"", ""),
    ("app/core/sessions.py", "    ts = utc_now().timestamp()", ""),
    ("app/core/thoughts.py", "    h = game_time().hour", ""),
    ("app/core/model_suitability.py",
     '    rec = {"date": utc_now().date().isoformat()}', ""),
    ("app/server.py", "    last = _dt.fromisoformat(_stamp.read_text())", ""),
    ("plugins/knowledge/extract_utils.py",
     "    d = datetime.fromisoformat(raw)", ""),
    ("scripts/smoke_memory_aware_stamps.py",
     "    old = datetime.now().isoformat()", ""),
)


def self_test() -> List[str]:
    """The rules against the probe table — returns the failures."""
    bad: List[str] = []
    for rel, line, expected in PROBES:
        codes = {r[0] for r in rules_for(rel, line)}
        want = {expected} if expected else set()
        if codes != want:
            bad.append(f"{rel}: {line.strip()!r} → {sorted(codes) or 'nothing'}"
                       f" (expected {sorted(want) or 'nothing'})")
    return bad


def main() -> int:
    broken = self_test()
    if broken:
        print(f"FAIL the lint rules themselves are broken "
              f"({len(broken)} probe(s)):")
        for b in broken:
            print(f"  {b}")
        return 1
    print(f"rule self-test: {len(PROBES)} probes green")

    findings: List[Tuple[str, int, str, str]] = []
    files = 0
    for path in iter_python_files():
        files += 1
        rel = path.relative_to(REPO).as_posix()
        for no, rule, line in scan(path):
            findings.append((rel, no, rule, line))

    print(f"scanned {files} python files under {', '.join(ROOTS)}/")
    if not findings:
        print("clean — no legacy clock names, no datetime maths on GameTime, "
              "no parse_iso on a game stamp, no naive system clock")
        return 0

    for rel, no, rule, line in findings:
        print(f"FAIL {rel}:{no}  {rule}\n       {line}")
    print(f"\n{len(findings)} finding(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
