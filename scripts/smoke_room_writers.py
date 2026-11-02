#!/usr/bin/env python3
"""Guard: every writer of a character's ROOM says what happens to its POINT
(docs/schnittstellen-3d.md § A1.4, the standing-point rule T4).

Usage:  ./.venv/bin/python scripts/smoke_room_writers.py

Why: ``current_room`` and the metre point ``pos`` are two columns. A writer
that changes the room and leaves the point alone draws the character in the
room it came from — the finding of 2026-11-02 (waking from the off-map sleep
put two characters in the bathroom while their room said guest room, fixed in
26afabf6). The renderers place by ``pos``, so the point has to follow.

How: an AST scan of ``app/`` and ``plugins/`` (symlinked packs included — the
scan follows directory symlinks) for the two ways the room is written:
``<x>["current_room"] = …`` and SQL text that sets ``current_room=``. Every
site is listed below by file and enclosing function, with the reason its
point is right. A NEW site fails until it is listed — with a reason, which
means somebody decided where the character stands. A listed site that no
longer exists fails too, so the list cannot rot.

No storage, no app import: plain source text.
"""
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (file, function) -> why the point is right after this write.
KNOWN = {
    ("app/models/character.py", "save_character_profile"):
        "the profile upsert itself — it stores what its callers decided",
    ("app/models/character.py", "save_character_current_room"):
        "room_stand.stand_up right after the write (inside-fallback when no free point)",
    ("app/models/character.py", "save_character_current_location"):
        "arrival room: sync_pos writes the centre, then stand_up; without sync_pos the caller writes its point",
    ("app/models/character.py", "_clear_location_and_room"):
        "stepping out into the wilderness — the caller's point is the truth, no room",
    ("app/models/character.py", "enter_offmap_sleep"):
        "off the map: room '' and the point cleared in the same function",
    ("app/models/character.py", "wake_from_offmap"):
        "_place_on_return: the centre, then stand_up in the return room",
    ("app/models/character.py", "appear_in_world"):
        "_place_on_return: the centre, then stand_up in the arrival room",
    ("app/models/world.py", "evict_rooms_to_ground"):
        "a deleted room hands its people to __ground__, which has no hull to stand in",
    ("app/models/world.py", "migrate_ground_rooms_once"):
        "one-time migration onto __ground__ / a storey corridor — no hull, the point stays",
    ("app/core/npc_pool.py", "_unplace"):
        "back into the pool: room '' and the point NULL in the same UPDATE",
    ("app/core/character_ops.py", "build_profile_payload"):
        "a display copy (room id -> name) for a response, never stored",
}


def _sql_sets_room(text: str) -> bool:
    flat = "".join(text.split()).lower()
    return "current_room=" in flat and ("update" in flat or "set" in flat or "excluded" in flat)


def sites():
    found = set()
    for top in ("app", "plugins"):
        for dirpath, _dirs, files in os.walk(ROOT / top, followlinks=True):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = Path(dirpath) / name
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                rel = path.relative_to(ROOT).as_posix()
                stack = []

                class Visitor(ast.NodeVisitor):
                    def visit_FunctionDef(self, node):
                        stack.append(node.name)
                        self.generic_visit(node)
                        stack.pop()

                    visit_AsyncFunctionDef = visit_FunctionDef

                    def visit_Assign(self, node):
                        for target in node.targets:
                            if (isinstance(target, ast.Subscript)
                                    and isinstance(target.slice, ast.Constant)
                                    and target.slice.value == "current_room"):
                                found.add((rel, stack[-1] if stack else "<module>", node.lineno))
                        self.generic_visit(node)

                    def visit_Constant(self, node):
                        if isinstance(node.value, str) and _sql_sets_room(node.value):
                            found.add((rel, stack[-1] if stack else "<module>", node.lineno))

                Visitor().visit(tree)
    return found


def main() -> int:
    print("Smoke: every room writer says where the character stands")
    found = sites()
    failures = []
    for rel, func, line in sorted(found):
        reason = KNOWN.get((rel, func))
        if reason is None:
            failures.append(f"{rel}:{line} {func}() writes current_room — place the point "
                            "(room_stand.stand_up or a point in the new room) and list it here")
        else:
            print(f"  ✓ {rel}:{line} {func}() — {reason}")
    present = {(rel, func) for rel, func, _line in found}
    for key in sorted(set(KNOWN) - present):
        failures.append(f"{key[0]} {key[1]}() is listed but writes no room any more — drop it")
    # Red counter-check: the matcher sees a plain room write and SQL text.
    probe = ast.parse('def f(p):\n    p["current_room"] = "x"\n    q = "UPDATE t SET current_room=?"\n')
    hits = [n for n in ast.walk(probe) if isinstance(n, ast.Subscript)
            and isinstance(n.slice, ast.Constant) and n.slice.value == "current_room"]
    if len(hits) != 1 or not _sql_sets_room("UPDATE t SET current_room=?") \
            or _sql_sets_room("SELECT current_room FROM t"):
        failures.append("the matcher itself is broken")
    for f in failures:
        print(f"  ✗ {f}")
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
