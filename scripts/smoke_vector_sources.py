#!/usr/bin/env python3
"""Guard: every shared test vector names WHERE its numbers are derived.

Usage:
    ./.venv/bin/python scripts/smoke_vector_sources.py

No server, no world, no storage: it reads shared/test-vectors/*.json and the
files they name.

Why. Every 'shared/test-vectors/<name>.json' carries a 'source': the file whose
docstring derives each expected number by hand. Until E1 (2026-11-25) almost
all of them pointed into the browser 3D scene's scripts directory. E1 moved
every derivation out of it first (class A: package-code smokes to scripts/;
class B: word for word into native/tests/Derivations/<smoke>.md, executed by
the C# vector tests; class C: into a Python smoke that replays the vector), and
E3 deleted the browser scene together with that directory. The one-time move
proof ([V4], 70 entries, run green before the deletion apart from the
prop_action_motion derivation that E3 rewrote) and the pointer-docstring check
for old sources that still existed ([V5]) went with it: no old source exists
any more. Their last state, with the move table: `git show
f4ee783afbe52098c1531253bbb0b780a714b789:scripts/smoke_vector_sources.py`.

Checks
  [V1] 'source' is an existing repo file (relative to the repo root) — a
       source inside the deleted browser scene is therefore a violation.
  [V3] the source file contains EXACTLY '<name>.json' (not preceded by a word
       character, so 'prop_water.json' does not prove 'water') or
       loadVectors('<name>') / loadVectors("<name>"). Checked only when [V1]
       holds.

Expected numbers, derived by hand
---------------------------------
Every vector file names an existing source that names it: 0 violations.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VECTOR_DIR = os.path.join(ROOT, "shared", "test-vectors")


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _names_vector(text: str, name: str) -> bool:
    n = re.escape(name)
    return bool(re.search(r"(?<![\w])" + n + r"\.json", text)
                or re.search(r"loadVectors\((['\"])" + n + r"\1\)", text))


def check_sources() -> list[str]:
    """[V1] and [V3]; one line per violation."""
    bad = []
    files = sorted(f for f in os.listdir(VECTOR_DIR) if f.endswith(".json"))
    for fname in files:
        name = fname[:-5]
        with open(os.path.join(VECTOR_DIR, fname), encoding="utf-8") as fh:
            data = json.load(fh)
        src = data.get("source") if isinstance(data, dict) else None
        if not isinstance(src, str) or not os.path.isfile(os.path.join(ROOT, src)):
            bad.append(f"[V1] {name}: source {src!r} is not a repo file")
            continue
        if not _names_vector(_read(src), name):
            bad.append(f"[V3] {name}: {src} names neither {name}.json nor loadVectors('{name}')")
    return bad


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__)
        return 2
    bad = check_sources()
    for line in bad:
        print(line)
    print(f"vector sources: {len(bad)} violations")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
