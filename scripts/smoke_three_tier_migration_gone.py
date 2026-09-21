#!/usr/bin/env python3
"""Lint: the one-time three-tier memory migration stays deleted.

Usage:  ./.venv/bin/python scripts/smoke_three_tier_migration_gone.py

Needs no server, no world DB and no node_modules — it reads source text.

WHAT WAS REMOVED (user decision 2026-09-21, review finding DP-6 / DATA-5)

    `app/core/memory_service.py` carried a one-time migration that folded
    legacy episodic memories into the day/week/season ladder:
    `run_migration_for_all_users`, `submit_three_tier_migration`,
    `handle_three_tier_migration`, `register_migration_handler` and
    `_migrate_three_tier`, wired into `app/server.py`'s lifespan.

    It could not succeed any more.  The handler aborted on its very first
    line when the payload carried no `user_id`, and nobody has sent one
    since the multi-user rework — so the `.migrated_3tier` marker was never
    written, so the submitter skipped nothing on the next boot and every
    server start enqueued one failing background job per character
    (`deduplicate=False`).  The running consolidation
    (`day_consolidation` / weekly / season) covers new memories, so there is
    nothing left for a migration to do.

THE RULE

    Neither the task type `three_tier_migration` nor the marker file name
    `.migrated_3tier` may reappear in shipped code or documentation.  A
    re-introduced task type would be a queue entry nothing handles; a
    re-introduced marker would be a file the DB-only world layout has no
    place for.

WHAT IS SCANNED

    app/, frontend/src/, packages/, static/admin/, docs/, README.md —
    the shipped surfaces.  `development_instructions/` is deliberately NOT
    scanned: those are historical plan and review documents (gitignored)
    that describe the removal and must keep naming it.  Build output
    (`node_modules`, `__pycache__`, `static/game_admin/assets`, `dist`) is
    skipped as well — it is generated, not authored.

    `scripts/` is skipped too, because THIS file names both strings.

EXPECTED RESULT, derived by hand

    0 hits for `three_tier_migration`, 0 hits for `.migrated_3tier`.
    Before the removal the same scan found 6 hits for `three_tier_migration`
    (memory_service.py: the two def lines, the `task_type=` argument, the
    `register_handler` argument, plus `submit_three_tier_migration()` and its
    def — counting the `_migrate_three_tier` def separately) and 2 hits for
    `.migrated_3tier` (the marker path built in the submitter and in the
    handler), so the check fails loudly on the old code.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Needles that must not occur any more.  `_migrate_three_tier` is covered by
# the `three_tier` substring of the task-type needle only if it appears with
# that exact spelling, so it gets its own entry.
NEEDLES = ["three_tier_migration", ".migrated_3tier", "_migrate_three_tier"]

TARGETS = [
    Path("app"),
    Path("frontend/src"),
    Path("packages"),
    Path("static/admin"),
    Path("docs"),
    Path("README.md"),
]

SKIP_DIR_PARTS = {"node_modules", "__pycache__", "dist", ".git", "assets"}

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".jsx", ".json", ".md",
    ".html", ".css", ".yaml", ".yml", ".txt",
}


def iter_files():
    for target in TARGETS:
        p = ROOT / target
        if p.is_file():
            yield p
            continue
        if not p.is_dir():
            continue
        for f in p.rglob("*"):
            if not f.is_file():
                continue
            if SKIP_DIR_PARTS & set(f.relative_to(ROOT).parts):
                continue
            if f.suffix.lower() not in TEXT_SUFFIXES:
                continue
            yield f


def main() -> int:
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
        print(f"FAIL: {len(hits)} forbidden occurrence(s) — the three-tier "
              "migration was deleted on purpose:")
        for rel, lineno, needle, line in hits:
            print(f"  {rel}:{lineno}  [{needle}]  {line}")
        return 1

    print("PASS: three_tier_migration / .migrated_3tier / _migrate_three_tier "
          "appear nowhere in the shipped sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
