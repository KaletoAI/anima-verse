#!/usr/bin/env python3
"""Smoke: there is exactly ONE background queue, and nothing left calls the old wrapper.

Usage:  ./.venv/bin/python scripts/smoke_background_queue_gone.py

WHY

``app/core/background_queue.py`` was a 42-line pass-through: its ``submit`` and
``register_handler`` did nothing but forward to
``app.core.task_queue.get_task_queue()``, and ``get_status`` had no caller at
all.  Two names for one queue is not a harmless duplicate — it made the docs
lie.  ``docs/skill-core-api.md`` described ``get_background_queue()`` to package
authors as "the volatile in-process queue whose tasks are lost on a restart",
which was never true of the thing it delegated to: the task queue is SQLite-
backed and its tasks survive a restart.  A package author who believed the
document would have chosen the wrong queue for work that must not be lost.

So the wrapper is gone and every caller submits to ``get_task_queue()``.  This
check keeps it gone.

WHAT IS CHECKED — every expectation derived by hand, no snapshot

  1. ``app/core/background_queue.py`` does not exist.
  2. None of the three names ``background_queue`` / ``BackgroundQueue`` /
     ``get_background_queue`` appears in any text file under ``app/``,
     ``plugins/``, ``docs/``, ``scripts/`` or in ``README.md``.
     The names are matched with a word boundary, so ordinary prose such as
     "runs in the background queue" (two words) or "Background-Queue" does NOT
     trip the check — only the identifiers do.
  3. ``app/models/chat.py`` does not contain the word DEPRECATED.  It carried a
     "DEPRECATED, use UnifiedChatManager instead" header while 15 call sites in
     app/ and in skill packages used it and while it was documented as official
     core API — the label was simply false.

SCOPE NOTES

``plugins/attraction``, ``plugins/intimacy`` and ``plugins/nsfw_anatomy`` are
symlinks into the private packs repo and ``plugins/installed`` holds
marketplace installs; neither is part of this repository, so both are skipped.
This file itself is skipped for rule 2 — it has to spell the names to forbid
them.

Pure text scan: no import from ``app``, no storage, no server, no network.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

#: The identifiers that must not come back.
FORBIDDEN = ("background_queue", "BackgroundQueue", "get_background_queue")
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b")

#: Where to look.
ROOTS = ("app", "plugins", "docs", "scripts")
EXTRA_FILES = ("README.md",)

#: Not part of this repository — symlinked private packs and marketplace installs.
SKIP_DIR_NAMES = {"installed", "attraction", "intimacy", "nsfw_anatomy",
                  "__pycache__", "node_modules"}

#: Binary-ish files a text scan has no business reading.
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".glb", ".fbx",
                   ".mp4", ".wav", ".db", ".pyc", ".ico", ".woff", ".woff2",
                   ".ttf", ".zip", ".pdf"}

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def _iter_files():
    for root in ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(REPO).parts):
                continue
            if path.suffix.lower() in BINARY_SUFFIXES:
                continue
            if path.is_symlink():
                continue
            yield path
    for name in EXTRA_FILES:
        p = REPO / name
        if p.is_file():
            yield p


def main():
    print("1) the wrapper module is gone")
    module = REPO / "app" / "core" / "background_queue.py"
    check("app/core/background_queue.py does not exist", not module.exists())

    print("2) no source, script or doc names the removed identifiers")
    hits = []
    scanned = 0
    for path in _iter_files():
        if path.resolve() == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            if _FORBIDDEN_RE.search(line):
                hits.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()[:90]}")
    check(f"none of {FORBIDDEN} appears ({scanned} text files scanned)",
          not hits, " | ".join(hits[:8]))

    print("3) app/models/chat.py carries no false DEPRECATED label")
    chat = REPO / "app" / "models" / "chat.py"
    check("app/models/chat.py exists", chat.is_file())
    if chat.is_file():
        check("app/models/chat.py does not contain 'DEPRECATED'",
              "DEPRECATED" not in chat.read_text(encoding="utf-8"))

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
