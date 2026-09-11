#!/usr/bin/env python3
"""Lint: a check script must never open the TRACKED demo world.

Usage:  ./.venv/bin/python scripts/smoke_scripts_storage_lint.py

THE RULE, derived from app/core/paths.py (``init`` resolution order)

``paths.init()`` resolves the storage root as: explicit argument, else the
``STORAGE_DIR`` environment variable, else ``./worlds/demo``.  And
``get_storage_dir()`` auto-initialises on first call, so a script that never
calls ``init`` silently lands in ``worlds/demo`` — which is TRACKED in git
(CLAUDE.md: "worlds/demo/ **is** tracked in git").  Any app module that opens
``world.db`` therefore writes into the shipped demo world and leaves the
working tree dirty.  It has happened repeatedly; the two most recent cases:

  * scripts/test_finish_reason.py — ``_log_task_result`` -> ``llm_logger``
    -> ``llm_stats.record_call`` -> ``INSERT INTO llm_call_stats``.
  * scripts/test_respond_lane.py — ``AgentLoop()`` -> ``_is_paused`` ->
    ``is_world_frozen`` -> ``get_connection`` -> ``PRAGMA journal_mode=WAL``.

So: a script that imports a world-DB module MUST set a throwaway storage root
BEFORE that import — ``paths.init(<temp>)`` or the ``STORAGE_DIR`` env var.
"Before" is literal for a MODULE-LEVEL import: it executes at load time and
``get_storage_dir`` caches whatever it resolved first.  An import inside a
function runs on the call instead, so there any redirect in the file counts.
``app.core.paths`` itself is exempt — it is what one calls ``init`` on.

THE CRITERION IS DELIBERATELY NARROW

A script counts as a candidate only if it DIRECTLY imports a world-DB module,
where "world-DB module" is computed, not guessed:

  * every app module whose OWN source calls ``get_connection(`` or
    ``transaction(`` (64 of 332 modules at the time of writing), plus
  * a short, commented list of modules that persist through exactly one
    helper and would otherwise be invisible (see ``PERSISTING_MODULES``).

The blunt alternative — "every script that imports anything from app" — flags
71 scripts, most of which only pull in pure functions and never open a
database.  A whitelist that long says nothing.  The transitive import closure
is no better: one hop out from the DB modules already covers 189 of 332 app
modules, because app/ is one connected web of imports.  Narrow and honest
beats broad and ignored.

WHITELIST

Scripts that work on a REAL world on purpose (CLI tools, not checks) are named
explicitly in ``INTENTIONAL_REAL_WORLD`` with the reason — never skipped
silently.

SELF-TEST, hand-derived (part 1 of the output)

The classifier is checked against six hand-written snippets before it judges
anything, so a broken lint fails loudly instead of passing everything:

  1. redirect via ``paths.init`` on line 3, DB import on line 5  -> clean
  2. DB import on line 3, ``paths.init`` on line 5 (too late)    -> offender
  3. no redirect at all, DB import present                       -> offender
  4. ``STORAGE_DIR`` env set before the DB import                -> clean
  5. app imports, but none of them a world-DB module             -> not a candidate
  6. ``from app.core import paths`` alone before ``init``        -> clean
     (the paths import must not count as "the first app import")
  7. DB import INSIDE a function, ``paths.init`` one line later  -> clean
     (a deferred import runs on the call, so line order proves nothing)
  8. DB import inside a function, no redirect anywhere           -> offender

Exit code 0 = every candidate redirects its storage.  Exit 1 lists the ones
that do not — including the line numbers that decide the verdict.
"""
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
SCRIPTS = REPO / "scripts"

# Modules that DO reach world.db but whose own source shows nothing: they hand
# the write to one helper.  Each entry names the chain it stands for.
PERSISTING_MODULES = {
    # log_llm_call() -> llm_stats.record_call() -> INSERT INTO llm_call_stats
    "app.utils.llm_logger",
    # _log_task_result() -> llm_logger.log_llm_call() -> the same INSERT
    "app.core.provider_queue",
}

# Scripts that operate on a REAL world by design — CLI tools, not checks.
# Listing them here is the point: they are exempt, not overlooked.
INTENTIONAL_REAL_WORLD = {
    # Reads a live world and writes an export next to it.
    "export_world_content.py",
    # One-off migration: rewrites rows of an existing world in place.
    "backfill_canonical.py",
    # Interactive review tool over a world's stored presets.
    "review_presets.py",
    # Task-queue CLI; takes its DB path from the legacy root .env.
    "queue_cli.py",
    # This lint itself: it parses sources, it imports no app module.
    "smoke_scripts_storage_lint.py",
}

# scripts/legacy/ is out of scope wholesale: retired tools, kept only for
# reference, never run as a check (CLAUDE.md: "only scripts/legacy/ stays out").
SKIPPED_DIRS = {"legacy", "__pycache__"}

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(f"{label}: {detail}" if detail else label)


def module_name(path: Path) -> str:
    name = ".".join(path.relative_to(REPO).with_suffix("").parts)
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def world_db_modules() -> set:
    """App modules whose own source opens the world DB, plus the persisting ones."""
    opens = re.compile(r"\bget_connection\s*\(|\btransaction\s*\(")
    found = set()
    for path in APP.rglob("*.py"):
        if opens.search(path.read_text(encoding="utf-8", errors="replace")):
            found.add(module_name(path))
    return found | PERSISTING_MODULES


def app_imports(source: str):
    """[(lineno, module, nested)] for every app import, submodule names resolved.

    ``from app.core import paths`` / ``import app.core.paths`` are reported as
    the module ``app.core.paths`` so the caller can exempt them.  *nested* is
    True for an import inside a function or class body: that one runs when the
    function is CALLED, so the surrounding code decides the storage and the
    line order alone proves nothing.  A module-level import runs at load time,
    where the order is the whole point.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    nested_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    nested_lines.add(inner.lineno)
    out = []
    for node in ast.walk(tree):
        nested = node.lineno in nested_lines if hasattr(node, "lineno") else False
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app"):
                    out.append((node.lineno, alias.name, nested))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level or not mod.startswith("app"):
                continue
            for alias in node.names:
                out.append((node.lineno, f"{mod}.{alias.name}", nested))
            out.append((node.lineno, mod, nested))
    return sorted(out)


REDIRECT = re.compile(r"paths\.init\s*\(|[\"']STORAGE_DIR[\"']")


def redirect_line(source: str):
    """First line that sets a storage root, or None."""
    for lineno, line in enumerate(source.splitlines(), 1):
        code = line.split("#", 1)[0]
        if REDIRECT.search(code):
            return lineno
    return None


def verdict(source: str, db_modules: set):
    """('clean' | 'offender' | 'no-db', first db import line, module, redirect line)."""
    first = None
    for lineno, mod, nested in app_imports(source):
        if mod in db_modules:
            first = (lineno, mod, nested)
            break
    if first is None:
        return "no-db", None, None, None
    where = redirect_line(source)
    if where is None:
        ok = False
    elif first[2]:
        ok = True          # deferred import: any redirect in the file covers it
    else:
        ok = where < first[0]
    return ("clean" if ok else "offender"), first[0], first[1], where


# ---------------------------------------------------------------- self-test

FIXTURES = [
    ("1 redirect before the DB import", "clean", '''
import os
from app.core import paths
paths.init("/tmp/x")
from app.core import db
'''),
    ("2 redirect after the DB import", "offender", '''
import os
from app.core import db
from app.core import paths
paths.init("/tmp/x")
'''),
    ("3 no redirect at all", "offender", '''
from app.core import db
print(db)
'''),
    ("4 STORAGE_DIR env before the import", "clean", '''
import os
os.environ["STORAGE_DIR"] = "/tmp/x"
from app.core import db
'''),
    ("5 app imports, none of them world-DB", "no-db", '''
from app.core.game_time import GameTime
print(GameTime)
'''),
    ("6 paths import alone does not count", "clean", '''
from app.core import paths
paths.init("/tmp/x")
from app.core import db
'''),
    ("7 deferred import, redirect one line later", "clean", '''
def main():
    tmp = "/tmp/x"
    from app.core import paths, db
    paths.init(tmp)
'''),
    ("8 deferred import, no redirect anywhere", "offender", '''
def main():
    from app.core import db
    print(db)
'''),
]


def self_test(db_modules: set) -> None:
    print("1. classifier against hand-written snippets")
    check("app.core.db counts as a world-DB module", "app.core.db" in db_modules)
    check("app.core.paths is NOT a world-DB module",
          "app.core.paths" not in db_modules)
    check("app.core.game_time is NOT a world-DB module",
          "app.core.game_time" not in db_modules)
    for label, expected, src in FIXTURES:
        got = verdict(src, db_modules)[0]
        check(f"{label} -> {expected}", got == expected, got)


# -------------------------------------------------------------------- scan

def scan(db_modules: set):
    """[(name, first db import line, module, redirect line)] for offenders."""
    offenders, candidates = [], 0
    for path in sorted(SCRIPTS.rglob("*.py")):
        if set(path.relative_to(SCRIPTS).parts[:-1]) & SKIPPED_DIRS:
            continue
        if path.name in INTENTIONAL_REAL_WORLD:
            continue
        state, line, mod, where = verdict(
            path.read_text(encoding="utf-8", errors="replace"), db_modules)
        if state == "no-db":
            continue
        candidates += 1
        if state == "offender":
            offenders.append((path.name, line, mod, where))
    return offenders, candidates


def main() -> int:
    db_modules = world_db_modules()
    self_test(db_modules)

    print("2. scripts/ scan")
    offenders, candidates = scan(db_modules)
    print(f"  {candidates} script(s) import a world-DB module, "
          f"{len(INTENTIONAL_REAL_WORLD)} whitelisted, "
          f"{len(offenders)} without a storage redirect")
    for name, line, mod, where in offenders:
        late = f", redirect only on line {where}" if where else ", no redirect"
        FAILURES.append(f"{name}: imports {mod} on line {line}{late}")
        print(f"  FAIL {name} — imports {mod} on line {line}{late}")
    if not offenders:
        print("  OK  every candidate redirects its storage before the import")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
