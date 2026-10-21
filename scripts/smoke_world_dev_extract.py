"""Smoke: World-Dev schema listing and fenced-JSON extraction.

Two regressions this pins:

1. ``GET /world-dev/schemas`` answered 500 (``NameError: _get_schemas_dir``)
   after the layout helpers moved to ``app/core/layout_prompt.py`` — the
   World-Dev tab then had no schema to pick, so no character could be made.
   Expected by hand: ``shared/world_dev_schemas/`` holds ``character.md``,
   ``location.md`` and ``map.md``, so the listing names at least those three,
   and never the internal ``npc_character``.

2. A ```json:npc answer whose German prose quote opens with „ and closes with
   an ASCII quote (the 2026-10-16 log answer: ``„wie der Wald früher war"``)
   failed to parse, which the NPC generator reports as "no ```json:npc
   block". Expected by hand: the inner ASCII quote becomes “, so the value is
   exactly ``mittellang, oft mit Sprüchen über „wie der Wald früher war“`` and
   the following key ``age`` still reads 48. A correctly closed „…“ quote and a
   plain value pass through unchanged.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_extract.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_wd_extract_"))

from app.core.layout_prompt import extract_json_block  # noqa: E402
from app.routes.world_dev import get_available_schemas  # noqa: E402

failures = []


def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


names = {s["name"] for s in get_available_schemas()["schemas"]}
check("schema listing contains character, location, map",
      {"character", "location", "map"} <= names)
check("schema listing hides npc_character", "npc_character" not in names)

broken = ('```json:npc\n{\n  "dialogue_style": "mittellang, oft mit Sprüchen '
          'über „wie der Wald früher war"",\n  "age": 48\n}\n```')
data = extract_json_block(broken, "npc")
check("„…\" quote is repaired", data is not None)
if data:
    check("repaired value reads „…“",
          data.get("dialogue_style")
          == "mittellang, oft mit Sprüchen über „wie der Wald früher war“")
    check("the key after it still parses", data.get("age") == 48)

clean = ('```json:npc\n{\n  "dialogue_style": "sagt „hallo“ und geht",\n'
         '  "age": 30,\n}\n```')
data = extract_json_block(clean, "npc")
check("a correct „…“ quote stays unchanged",
      bool(data) and data.get("dialogue_style") == "sagt „hallo“ und geht"
      and data.get("age") == 30)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nOK — World-Dev schema listing and JSON extraction")
