#!/usr/bin/env python3
"""Guard: the per-slot outfit colour override is gone for good.

Usage:  ./.venv/bin/python scripts/smoke_piece_colour_meta_gone.py

WHAT THIS PINS

The "generic = colourable" rarity was abolished (boot migration in
``app/core/db.py`` rewrites every generic item to common, the Items UI offers
only common/rare/unique, ``app/core/outfit_renderer.py`` never reads a colour
override).  The three names that carried it were removed in 2026-09:

  * ``equipped_pieces_meta`` — the profile key and the parameter that was
    threaded through ~22 ``app/core/expression_regen.py`` signatures although
    the only end consumer (``_equipped_signature``) ignored it.
  * ``pieces_meta``         — the ``apply_equipped_pieces`` parameter in
    ``app/models/inventory.py`` plus its three call sites.
  * ``piece_colors``        — the query parameter of
    ``GET /characters/{name}/outfit-expression`` that no client ever sent.

This is a pure TEXT scan: no app import, no storage, no DB.  Searching for
``piece_colors`` and ``pieces_meta`` is enough — ``pieces_meta`` is a
substring of ``equipped_pieces_meta``, so the long name cannot come back
without tripping the short one.

EXPECTED RESULT, DERIVED BY HAND (not recorded from a run)

Both names must appear NOWHERE under the scanned roots, with exactly two
documented exceptions.  Their line counts are derived by reading the two
files, one line per occurrence:

  app/core/db.py                    -> 3 lines
      The one-time boot migration ``state_meta_legacy_purged_v1`` strips the
      key out of ``character_state.meta``.  It is a SEPARATE open decision and
      stays: (1) the comment naming the key above the migration, (2) the
      ``for key in ("runtime_outfit_skip", "equipped_pieces_meta")`` tuple,
      (3) the German log line that reports how many characters were purged.

  app/models/inventory.py           -> 3 lines
      One ``profile.pop("equipped_pieces_meta", None)`` per profile writer, so
      an old blob cleans itself up on the next outfit change.  The three
      writers are ``equip_piece``, ``unequip_piece`` and
      ``apply_equipped_pieces`` -> 3 lines, no more.

Anything above those numbers, or any hit in another file, fails the check.
The counts are MAXIMA: fewer lines in the allowlisted files is fine (the
migration or the cleanup may be dropped later), more is a regression.

SCANNED ROOTS

app/, plugins/, frontend/src/, packages/, client3d/src/, static/admin/,
docs/, README.md.  Skipped inside plugins/: ``attraction``, ``intimacy`` and
``nsfw_anatomy`` are symlinks into the private packs repo (read-only, not part
of this repo's tree) and ``installed/`` holds gitignored marketplace installs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent

# ``pieces_colors`` was the same override stored on an outfit SET; its only
# readers fed ``pieces_meta``. One line survives: the ``pop`` that cleans an
# old set on its next save (app/models/character.py).
NAMES = ("piece_colors", "pieces_meta", "pieces_colors")

ROOTS = (
    "app",
    "plugins",
    "frontend/src",
    "packages",
    "client3d/src",
    "static/admin",
    "docs",
    "README.md",
)

# Directory names that never carry source of ours.
SKIP_DIRS = {
    "__pycache__", "node_modules", "dist", "build", ".git", ".cache",
    # plugins/: symlinks into ../anima-verse-packs/packs (read-only) and the
    # gitignored marketplace install target.
    "attraction", "intimacy", "nsfw_anatomy", "installed",
}

TEXT_SUFFIXES = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".md", ".css", ".html", ".txt",
}

# file -> maximum number of lines that may still name one of NAMES.
# Derived by hand in the module docstring above.
ALLOWED: Dict[str, int] = {
    "app/core/db.py": 3,
    "app/models/inventory.py": 3,
    "app/models/character.py": 1,
}


def iter_files() -> List[Path]:
    out: List[Path] = []
    for root in ROOTS:
        p = REPO / root
        if p.is_file():
            out.append(p)
            continue
        if not p.is_dir():
            continue
        for f in p.rglob("*"):
            if not f.is_file():
                continue
            if any(part in SKIP_DIRS for part in f.relative_to(REPO).parts):
                continue
            if f.suffix.lower() not in TEXT_SUFFIXES:
                continue
            out.append(f)
    return out


def main() -> int:
    hits: Dict[str, List[Tuple[int, str]]] = {}
    for f in iter_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not any(n in text for n in NAMES):
            continue
        rel = f.relative_to(REPO).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(n in line for n in NAMES):
                hits.setdefault(rel, []).append((lineno, line.strip()))

    failures: List[str] = []
    for rel in sorted(hits):
        lines = hits[rel]
        allowed = ALLOWED.get(rel)
        if allowed is None:
            failures.append(
                f"{rel}: {len(lines)} line(s) still name the colour override "
                f"(no file outside the allowlist may)")
            for lineno, line in lines[:10]:
                failures.append(f"    {rel}:{lineno}: {line}")
        elif len(lines) > allowed:
            failures.append(
                f"{rel}: {len(lines)} line(s), at most {allowed} expected "
                f"(see the docstring for the hand-derived count)")
            for lineno, line in lines:
                failures.append(f"    {rel}:{lineno}: {line}")
        else:
            print(f"ok   {rel}: {len(lines)}/{allowed} allowlisted line(s)")

    for rel, allowed in sorted(ALLOWED.items()):
        if rel not in hits:
            print(f"ok   {rel}: 0/{allowed} line(s) — allowlist entry unused, "
                  f"that is fine")

    scanned = len(iter_files())
    print(f"\nscanned {scanned} file(s) under: {', '.join(ROOTS)}")
    print(f"names: {', '.join(NAMES)} "
          f"('pieces_meta' also covers 'equipped_pieces_meta')")

    if failures:
        print("\nFAIL — the per-slot colour override is back:")
        for line in failures:
            print("  " + line)
        return 1
    print("\nPASS — piece_colors / pieces_meta / equipped_pieces_meta appear "
          "only in the two documented places.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
