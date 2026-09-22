#!/usr/bin/env python3
"""Lint: the three old one-time boot migrations stay deleted.

Usage:  ./.venv/bin/python scripts/smoke_old_boot_migrations_gone.py

Needs no server, no world DB, no node_modules and imports nothing from
``app`` — it reads source text only.

WHAT WAS REMOVED (user decision 2026-09-21; no old world needs them any more)

  1. ``prompt_filters.migrate_status_modifiers_once`` (+ its only helper
     ``_id_from_condition``) and its call frame in ``app/server.py``.
     It imported a world-level ``status_modifiers.json`` into the
     ``prompt_filters`` table.  That file has had no writer for months —
     the one writer, ``danger_system.save_status_modifiers``, was itself
     dead code and is gone — so the migration could only ever find nothing.

  2. ``intents.migrate_assignments_to_intents`` and its call frame in
     ``app/server.py``.  It mirrored rows of the ``assignments`` table into
     ``intents``.  Nothing in ``app/``, ``plugins/`` or the private packs
     INSERTs or UPDATEs that table any more, so the source can only shrink,
     never grow.  With the migration went the last reader of
     ``assignments._load_all`` / ``_get_assignments_path`` and the dead
     diary collector ``diary._collect_assignments`` (the only producer of
     the ``assignment_done`` / ``assignment_update`` diary entry types).
     The ``assignments`` TABLE itself stays in ``world_db_schema.py`` so
     existing worlds keep their schema; it is marked legacy there.

  3. ``memory_service.migrate_rollup_summaries_to_db`` and its call frame in
     ``app/server.py``.  It imported per-character ``weekly_summaries.json``
     / ``monthly_summaries.json`` files into the ``summaries`` table.  The
     DB-only world layout has not written such files since the memory
     rework, so the migration walked every character for nothing on every
     boot.

THE RULE

  Neither the three function names, nor ``_collect_assignments``, nor the
  three legacy JSON file names may reappear in the shipped sources.  Each of
  them would be code reading a file or table that nothing writes.

  The LAST piece of the old assignment module went with the unified intent
  markers: the rp_first tool prompt no longer offers ``[NEW_ASSIGNMENT: …]``
  (it teaches ``[INTENT: … | by=player]`` now), so nothing emits the tag any
  more and ``strip_assignment_tags`` had nothing left to strip.  Both its call
  sites read a FRESH LLM answer, never stored history, so no display path lost
  a cleaner.  ``app/models/assignments.py`` is therefore gone as well, and the
  marker name itself is a needle below.  The ``assignments`` TABLE stays.

WHAT IS SCANNED

  app/, plugins/, docs/, README.md, frontend/src/, packages/, static/admin/.
  ``plugins/attraction``, ``plugins/intimacy`` and ``plugins/nsfw_anatomy``
  are symlinks into the private packs repo and ``plugins/installed`` holds
  marketplace installs — both are foreign content and are skipped.
  ``development_instructions/`` is NOT scanned: those are historical plan
  and review documents that must keep naming what was removed.  ``scripts/``
  is skipped because THIS file names every needle.  Generated output
  (``node_modules``, ``__pycache__``, ``dist``, ``static/game_admin/assets``)
  is skipped as well.

EXPECTED RESULT, derived by hand

  0 hits for every needle.  On the code before the removal the same scan
  found, by hand from the sources:
    migrate_status_modifiers_once   4  (prompt_filters.py def + log line,
                                        server.py import + call)
    migrate_assignments_to_intents  4  (intents.py def, assignments.py
                                        docstring, server.py import + call)
    migrate_rollup_summaries_to_db  3  (memory_service.py def,
                                        server.py import + call)
    _collect_assignments            2  (diary.py def + call)
    status_modifiers.json           6  (prompt_filters.py 5,
                                        world_db_schema.py comment 1 —
                                        server.py's comment makes 7)
    weekly_summaries.json           2  (memory_service.py docstring + tuple)
    monthly_summaries.json          2  (memory_service.py docstring + tuple)
  so the check fails loudly on the old code.  Both positive assertions held
  before and after — they guard against over-deletion, not against the old
  state.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NEEDLES = [
    "migrate_status_modifiers_once",
    "migrate_assignments_to_intents",
    "migrate_rollup_summaries_to_db",
    "_collect_assignments",
    "status_modifiers.json",
    "weekly_summaries.json",
    "monthly_summaries.json",
    "NEW_ASSIGNMENT",
    "strip_assignment_tags",
]

TARGETS = [
    Path("app"),
    Path("plugins"),
    Path("docs"),
    Path("README.md"),
    Path("frontend/src"),
    Path("packages"),
    Path("static/admin"),
]

# Foreign or generated trees — never ours to judge.
SKIP_DIR_PARTS = {"node_modules", "__pycache__", "dist", ".git", "assets",
                  "installed", "attraction", "intimacy", "nsfw_anatomy"}

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".json", ".md",
    ".html", ".css", ".yaml", ".yml", ".txt",
}

ASSIGNMENTS_FILE = ROOT / "app" / "models" / "assignments.py"


def iter_files():
    for target in TARGETS:
        p = ROOT / target
        if p.is_file():
            yield p
            continue
        if not p.is_dir():
            continue
        for f in p.rglob("*"):
            if f.is_symlink() or not f.is_file():
                continue
            if SKIP_DIR_PARTS & set(f.relative_to(ROOT).parts):
                continue
            if f.suffix.lower() not in TEXT_SUFFIXES:
                continue
            yield f


def main() -> int:
    failures = []

    hits = []
    scanned = 0
    for f in iter_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  ! cannot read {f}: {e}")
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            for needle in NEEDLES:
                if needle in line:
                    hits.append((f.relative_to(ROOT), lineno, needle,
                                 line.strip()[:120]))

    print(f"scanned {scanned} files under "
          + ", ".join(str(t) for t in TARGETS))
    if hits:
        failures.append(f"{len(hits)} forbidden occurrence(s)")
        print(f"FAIL: {len(hits)} forbidden occurrence(s) — the old boot "
              "migrations were deleted on purpose:")
        for rel, lineno, needle, line in hits:
            print(f"  {rel}:{lineno}  [{needle}]  {line}")
    else:
        print("PASS: none of the %d removed names/files appears in the "
              "shipped sources" % len(NEEDLES))

    # The module itself went with its last function.
    if ASSIGNMENTS_FILE.exists():
        failures.append("app/models/assignments.py is back")
        print("FAIL: app/models/assignments.py exists again — the assignment "
              "marker feature was removed with the unified intents")
    else:
        print("PASS: app/models/assignments.py is gone")

    if failures:
        print("RESULT: FAIL — " + "; ".join(failures))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
