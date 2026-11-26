#!/usr/bin/env python3
"""Smoke: no orphan of the removed World Dev schema modes (plan
docs/superpowers/plans/2026-11-25-world-dev-free-remove-schema-modes.md, Task 6).

World Dev offers only the free mode. The schema routes, their JSON-import and
validator routes, the per-type schema files and the schema-mode components are
gone; this check reads files only (no server, no world DB, no app import) and
proves no live file still names them. Historical plans/specs under
docs/superpowers/ are left as they are and are not scanned.

Scanned: app/, scripts/, plugins/ (symlinks followed), frontend/src, packages/,
hud/src, shared/, static/admin/, docs/*.md (top level only), README.md,
CHAT_PROMPTS.md. This file itself is skipped (it spells the patterns).

Expected, by hand:
A) No file names a removed route `world-dev/<schemas|chat|apply…|preview…|map-…|
   layout-…|validate|validate-json|cleanup|character-templates>` -> 0 hits, except
   scripts/smoke_world_dev_free_routes.py, which holds the removed-route 404
   proof (Task 4) and is the ONE allowed file.
B) No file names a deleted schema file
   `shared/world_dev_schemas/{character,location,map}.md` -> 0 hits, except
   scripts/smoke_world_dev_map_parity.py, which quotes map.md from the pinned
   commit a90d96e7e (its EXAMPLE constant). layout.md (building assistant) and
   npc_character.md (temporary NPCs) stay and may be named.
C) No file names a deleted/moved component: `MapDraftPreview`,
   `world-dev/LayoutDraftPreview`, `ConfirmMapAction`, `ConfirmLayoutAction`
   -> 0 hits.
D) The mode selector label `Free (agent)` is gone from the UI, so no file
   points the reader to it -> 0 hits.
E) The free-mode manuals (shared/templates/llm/world_dev_free/*.md) name no
   "map schema" / "map-schema" -> 0 hits (their tables map map-LAYOUT fields).
F) docs/llm-templates.md: the `world_dev_validate.md` row exists once and does
   not name `routes/world_dev.py` (its only caller is npc_ops).
G) README.md: the shared/ paragraph no longer lists the world-dev prompt
   specifications as `character`, `location`, `map`, and names the two that
   stay: the building assistant (`layout`) and the temporary NPCs
   (`npc_character`).
H) app/core/llm_tasks.py: the comment on the removed `world_dev_validate`
   task no longer says the validator model is picked in the World Dev UI, and
   names its one remaining caller (npc_ops).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_no_orphans.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

TREES = ["app", "scripts", "plugins", "frontend/src", "packages", "hud/src",
         "shared", "static/admin"]
SKIP_DIRS = {"node_modules", "dist", "__pycache__", ".git", "build"}
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".css", ".md", ".json",
            ".yaml", ".yml", ".html", ".txt", ".j2"}

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"\n     {detail}"))
    if not ok:
        failures += 1


def files() -> list[Path]:
    out: list[Path] = []
    for tree in TREES:
        base = ROOT / tree
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix in TEXT_EXT:
                    out.append(p)
    out += sorted((ROOT / "docs").glob("*.md"))
    out += [ROOT / "README.md", ROOT / "CHAT_PROMPTS.md"]
    return [p for p in out if p.is_file() and p.resolve() != SELF]


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def hits(pattern: str, allowed: set[str] = frozenset(), only: list[Path] | None = None,
         flags: int = 0) -> list[str]:
    rx = re.compile(pattern, flags)
    found: list[str] = []
    for p in (only if only is not None else ALL):
        r = rel(p)
        if r in allowed:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for no, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                found.append(f"{r}:{no}: {line.strip()[:140]}")
    return found


ALL = files()

route_rx = (r"world-dev/(schemas|chat|apply|preview|map-|layout-|validate(-json)?\b|"
            r"cleanup|character-templates)")
h = hits(route_rx, {"scripts/smoke_world_dev_free_routes.py"})
check("A) no removed /world-dev/ schema route named outside the 404 proof", not h, "\n     ".join(h))
check("A) the 404 proof file still names them (the one allowed file)",
      bool(hits(route_rx, only=[ROOT / "scripts/smoke_world_dev_free_routes.py"])))

h = hits(r"world_dev_schemas/(character|location|map)\.md",
         {"scripts/smoke_world_dev_map_parity.py"})
check("B) no deleted schema file (character/location/map.md) named", not h, "\n     ".join(h))

h = hits(r"MapDraftPreview|world-dev/LayoutDraftPreview|ConfirmMapAction|ConfirmLayoutAction")
check("C) no deleted/moved schema-mode component named", not h, "\n     ".join(h))

h = hits(r"Free \(agent\)")
check("D) no pointer to the removed 'Free (agent)' mode selector", not h, "\n     ".join(h))

manuals = sorted((ROOT / "shared/templates/llm/world_dev_free").glob("*.md"))
h = hits(r"map[ -]schema", only=manuals, flags=re.IGNORECASE)
check(f"E) the {len(manuals)} free-mode manual files name no map schema", not h, "\n     ".join(h))

rows = [l for l in (ROOT / "docs/llm-templates.md").read_text(encoding="utf-8").splitlines()
        if l.startswith("| `world_dev_validate.md`")]
check("F) docs/llm-templates.md has one world_dev_validate.md row", len(rows) == 1, str(rows))
check("F) that row does not name routes/world_dev.py",
      bool(rows) and "routes/world_dev.py" not in rows[0], str(rows))

readme = (ROOT / "README.md").read_text(encoding="utf-8")
check("G) README no longer lists world-dev specs as character/location/map",
      "(`character`, `location`, `map`)" not in readme)
check("G) README names the remaining specs `layout` and `npc_character`",
      "(`layout`)" in readme and "(`npc_character`)" in readme)

llm_tasks = (ROOT / "app/core/llm_tasks.py").read_text(encoding="utf-8")
check("H) llm_tasks.py no longer points to a validator picker in the World Dev UI",
      "World Dev UI" not in llm_tasks)
# Anchor on the comment's own wording and read its whole contiguous "#" block,
# so another mention of the task name or a reflowed comment does not matter.
_lt_lines = llm_tasks.splitlines()
_anchor = next((i for i, l in enumerate(_lt_lines)
                if l.lstrip().startswith("#") and "No `world_dev_validate` task" in l), None)
_block: list[str] = []
if _anchor is not None:
    for l in _lt_lines[_anchor:]:
        if not l.lstrip().startswith("#"):
            break
        _block.append(l)
check("H) llm_tasks.py's world_dev_validate comment names its caller npc_ops",
      any("npc_ops" in l for l in _block),
      f"anchor line {_anchor}: {_block}")

print(f"\n{len(ALL)} files scanned, {failures} failure(s)")
sys.exit(1 if failures else 0)
