#!/usr/bin/env python3
"""Smoke: the story arc engine is gone (quest system stage 1, Task 11, plan D16).

The quest system replaces the story arc engine. This check proves the removal at every layer the engine had: its
table (dropped once by a `schema_meta` one-shot in `db.init_schema`), its template overrides, its two modules, its
routes, its config section with the env mirror, and every text reference in the code and shipped templates.

Usage:
    ./.venv/bin/python scripts/smoke_arc_engine_gone.py

Runs against THROWAWAY storage and instance directories (`STORAGE_DIR` / `INSTANCE_DIR` are set and
`paths.init(<tmp>)` runs before any world-DB module is imported); it never touches a real world.

WHAT FOLLOWS BY HAND
 (a) Drop one-shot. A fresh world.db is seeded BEFORE init_schema with
       - a `story_arcs` table holding one row (id "sa1"),
       - `llm_template_overrides` rows: "tasks/story_arc_generation.md" (an arc template),
         "chat/agent_thought.md" = REPAIRED (a header comment whose variable list names arc_block on its own line,
         then "before\n", a whitespace-control block {%- if arc_block -%}…{{ arc_block }}…{%- endif -%} and
         "\nafter"), "chat/thought_extra.md" = DELETED (reads {{ arc_block }} outside any block), and
         "chat/agent_thought_in_chat.md" with plain content (the control: no arc reference), and two rows whose
         repair would not parse: "chat/nested_if.md" = "a\n{% if arc_block %}{% if x %}y{% endif %}z{% endif %}\nb"
         (the shortest match ends at the INNER endif, leaving "z{% endif %}" dangling) and "chat/comment_tail.md" =
         "{# vars:\n     arc_block — x #}\nbody" (the comment line that names arc_block carries the #}, so the
         repair leaves "{# vars:\n" unterminated). Neither still reads arc_block after the repair, so only the
         parse check (jinja2 parse, the loader's options) sends them down the delete path.
     After db.init_schema():
       - sqlite_master has no table "story_arcs" (DROP ran, and no CREATE statement brings it back),
       - the overrides left are exactly {"chat/agent_thought.md", "chat/agent_thought_in_chat.md"} (the arc
         template row goes by its path, thought_extra by its content, nested_if and comment_tail because their
         repair does not parse; the control row stays),
       - for each of nested_if and comment_tail exactly ONE warning names it and carries its FULL original content,
       - agent_thought.md is stored as REPAIRED_THOUGHT: the comment line that starts with arc_block is gone, the
         block plus the one newline after it is gone -> "{# vars:\n     other — x\n#}\nbefore\nafter",
       - the control row's content is unchanged ("a plain override"),
       - schema_meta holds story_arcs_dropped_v1 = "1",
       - exactly ONE warning names "chat/agent_thought.md" together with the world path (the repair note), and
         exactly ONE names "chat/thought_extra.md" and carries its FULL content (logged before the delete).
     A second init_schema() leaves the table absent (the CREATE statement is gone from SCHEMA_STATEMENTS — with it
     still present the table would be recreated empty) and issues no further warning about the override.
 (b) importlib.import_module("app.core.story_engine") and ("app.models.story_arcs") raise ModuleNotFoundError.
 (c) No route path of the real app (app.server.app) contains "story-arc" (the three /queue/story-arc routes went).
 (d) "story_engine" is not a key of config_schema.SECTIONS; it IS in config.DEAD_TOPLEVEL_ONLY_FIELDS (a stored
     section is stripped on load, no "unknown root key" warning); after config._flatten_to_env({}) (a default
     config: every field falls back to its schema default) no os.environ name starts with "STORY_ENGINE_".
 (e) A text scan of app/, plugins/ (following the symlinked packs), shared/templates, shared/prompt_filters and
     static/admin for the words story_arc | story_engine | arc_block | inject_arc_context | arc_context | _advance_arcs
     (the last two: the thought turn's arc load and its arc-advance call site, which main rewrote after this branch
     forked and which partly merged without a conflict marker) finds exactly these lines
     (stripped) and nothing else:
       app/core/config.py   the image-routing seed tuple    ("photo", ("story_engine.imagegen_default",)),
       app/core/config.py   the dead-field entry            DEAD_TOPLEVEL_ONLY_FIELDS ... "body_retexture", "story_engine")
       app/core/db.py       the drop one-shot: the flag lookup, the flag insert, DROP TABLE IF EXISTS story_arcs,
                            the three template paths tasks/story_arc_generation.md | _advancement.md | _resolve.md
                            and the repair's variable name _ARC_VAR = "arc_block"  (7 lines, listed verbatim in
                            ALLOWED below)
     Nor does any scanned FILE NAME contain story_arc / story_engine.
     The scanner is not looking away: at commit 3a444d8bf (before the removal) git grep of the same words over the
     same tracked directories counts >= 110 lines (hand count of that commit: config.py 7, story_engine.py 30,
     template_preview.py 17, story_arcs.py 9, queue.py 6, ... = 110).
 (f) "/play/story-arcs" is not a route of the real app, and app.core.world_ops has no build_player_story_arcs
     (the player panel reads /play/quests since Task 8).
 (g) Frontend (Task 12). A text scan of frontend/src and packages/player-ui/src for
     StoryArcsPanel | story-arc | story_arc finds 0 lines and no such file name (before Task 12 it found the panel
     file StoryArcsPanel.tsx — 7 lines in it: the doc comment's three endpoint mentions, the export, the three api
     calls — plus 2 lines in StorytellerTab.tsx: the import and the mount). shared/languages/de.json has 0 keys that
     contain "story arc" case-insensitively (before: "Story arcs", "No story arcs yet.", "Delete story arc" = 3).
 (h) Built bundles (review R11). A byte scan of every file under static/game_admin and static/hud
     (when present) finds "play/story-arcs" in none of them: the quest book of Game-Admin and of the native
     HUD (static/hud/hud.html) polls /play/quests, and a bundle built from a tree before the removal would poll the
     404 route. The scan is not looking away: it counts >= 1 scanned file per present directory.
"""
import importlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="arc-gone-storage-"))
INSTANCE = Path(tempfile.mkdtemp(prefix="arc-gone-instance-"))
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(INSTANCE)

import app  # noqa: E402

assert Path(app.__file__).resolve().is_relative_to(ROOT), f"app imported from {app.__file__}, not {ROOT}"

from app.core import paths  # noqa: E402

paths.init(STORAGE)

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL {label}: got {got!r}, want {want!r}")


WORDS = re.compile(r"story_arc|story_engine|arc_block|inject_arc_context|arc_context|_advance_arcs")
OLD_COMMIT = "3a444d8bf"
OLD_MIN_LINES = 110

# (relative path, stripped line) — the only places the words may still stand.
ALLOWED = {
    ("app/core/config.py", '("photo", ("story_engine.imagegen_default",)),'),
    ("app/core/config.py",
     'DEAD_TOPLEVEL_ONLY_FIELDS: tuple = ("item_image_width", "item_image_height", "body_retexture", "story_engine")'),
    ("app/core/db.py", '"SELECT value FROM schema_meta WHERE key=\'story_arcs_dropped_v1\'"'),
    ("app/core/db.py", 'conn.execute("DROP TABLE IF EXISTS story_arcs")'),
    ("app/core/db.py", '("tasks/story_arc_generation.md",'),
    ("app/core/db.py", '"tasks/story_arc_advancement.md",'),
    ("app/core/db.py", '"tasks/story_arc_resolve.md"))'),
    ("app/core/db.py", '_ARC_VAR = "arc_block"'),
    ("app/core/db.py", '"(\'story_arcs_dropped_v1\', \'1\')"'),
}
SCAN_DIRS = ("app", "plugins", "shared/templates", "shared/prompt_filters", "static/admin")
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}


# ── (a) the drop one-shot ─────────────────────────────────────────────────
print("(a) drop one-shot in db.init_schema")
from app.core import db  # noqa: E402

DB_PATH = db.get_db_path()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
seed = sqlite3.connect(str(DB_PATH))
seed.execute("CREATE TABLE story_arcs (id TEXT PRIMARY KEY, title TEXT NOT NULL, state TEXT DEFAULT 'active', "
             "beats TEXT DEFAULT '[]', participants TEXT DEFAULT '[]', meta TEXT DEFAULT '{}', "
             "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
seed.execute("INSERT INTO story_arcs (id, title, created_at, updated_at) VALUES ('sa1', 'Old arc', 'x', 'x')")
seed.execute("CREATE TABLE llm_template_overrides (path TEXT PRIMARY KEY, content TEXT NOT NULL, "
             "base_hash TEXT NOT NULL, updated_at TEXT NOT NULL)")
THOUGHT_OVERRIDE = ("{# vars:\n     arc_block   — Low: arc\n     other — x\n#}\nbefore\n"
                    "{%- if arc_block -%}\n=== Story ===\n{{ arc_block }}\n{%- endif -%}\nafter")
REPAIRED_THOUGHT = "{# vars:\n     other — x\n#}\nbefore\nafter"
EXTRA_OVERRIDE = "Plain line.\n{{ arc_block }} is read here without a block."
NESTED_IF_OVERRIDE = "a\n{% if arc_block %}{% if x %}y{% endif %}z{% endif %}\nb"
COMMENT_TAIL_OVERRIDE = "{# vars:\n     arc_block — x #}\nbody"
for path, content in (("tasks/story_arc_generation.md", "an old arc prompt"),
                      ("chat/agent_thought.md", THOUGHT_OVERRIDE),
                      ("chat/thought_extra.md", EXTRA_OVERRIDE),
                      ("chat/agent_thought_in_chat.md", "a plain override"),
                      ("chat/nested_if.md", NESTED_IF_OVERRIDE),
                      ("chat/comment_tail.md", COMMENT_TAIL_OVERRIDE)):
    seed.execute("INSERT INTO llm_template_overrides (path, content, base_hash, updated_at) VALUES (?, ?, 'h', 'x')",
                 (path, content))
seed.commit()
seed.close()

warnings = []
_orig_warning = db.logger.warning


def _capture(msg, *args, **kwargs):
    try:
        warnings.append(str(msg) % args if args else str(msg))
    except Exception:
        warnings.append(f"{msg} {args}")
    return _orig_warning(msg, *args, **kwargs)


db.logger.warning = _capture
db.init_schema()


def table_present() -> bool:
    con = sqlite3.connect(str(DB_PATH))
    try:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='story_arcs'").fetchone() is not None
    finally:
        con.close()


def overrides() -> set:
    con = sqlite3.connect(str(DB_PATH))
    try:
        return {r[0] for r in con.execute("SELECT path FROM llm_template_overrides").fetchall()}
    finally:
        con.close()


def override_content(path: str):
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute("SELECT content FROM llm_template_overrides WHERE path=?", (path,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def flag() -> object:
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute("SELECT value FROM schema_meta WHERE key='story_arcs_dropped_v1'").fetchone()
        return row[0] if row else None
    finally:
        con.close()


world = str(paths.get_storage_dir())
check("table story_arcs dropped", table_present(), False)
check("overrides left: the repaired one and the control row", overrides(),
      {"chat/agent_thought.md", "chat/agent_thought_in_chat.md"})
check("agent_thought repaired, the rest kept", override_content("chat/agent_thought.md"), REPAIRED_THOUGHT)
check("control row untouched", override_content("chat/agent_thought_in_chat.md"), "a plain override")
check("flag story_arcs_dropped_v1 set", flag(), "1")
named = [w for w in warnings if "chat/agent_thought.md" in w and world in w]
check("one warning names the agent_thought override and the world path", len(named), 1)
extra = [w for w in warnings if "chat/thought_extra.md" in w]
check("one warning for the deleted override, with its full content",
      (len(extra), all(EXTRA_OVERRIDE in w for w in extra)), (1, True))
for name, original in (("chat/nested_if.md", NESTED_IF_OVERRIDE), ("chat/comment_tail.md", COMMENT_TAIL_OVERRIDE)):
    got = [w for w in warnings if name in w]
    check(f"{name}: repair does not parse -> deleted, one warning with its full content",
          (name in overrides(), len(got), all(original in w for w in got)), (False, 1, True))
before = len(warnings)
db.init_schema()
check("second init_schema: table still absent", table_present(), False)
check("second init_schema: no further override warning",
      [w for w in warnings[before:] if "chat/agent_thought.md" in w or "thought_extra" in w], [])
db.logger.warning = _orig_warning

# ── (b) modules ───────────────────────────────────────────────────────────
print("(b) modules")
for mod in ("app.core.story_engine", "app.models.story_arcs"):
    try:
        importlib.import_module(mod)
        got = "imported"
    except ModuleNotFoundError:
        got = "ModuleNotFoundError"
    check(f"{mod} is gone", got, "ModuleNotFoundError")

# ── (c) + (f) routes ──────────────────────────────────────────────────────
print("(c)/(f) routes of the real app")
from app.server import app as real_app  # noqa: E402


def walk_routes(routes, prefix=""):
    """Flatten the app's route tree (`include_router` wraps each router in an `_IncludedRouter` node — as
    `smoke_figure_removed.walk_routes`)."""
    from fastapi.routing import _IncludedRouter
    for r in routes:
        if isinstance(r, _IncludedRouter):
            ctx = getattr(r, "include_context", None)
            yield from walk_routes(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif getattr(r, "path", None):
            yield prefix + r.path


route_paths = set(walk_routes(real_app.routes))
check("the walk sees the app's endpoints (/play/quests among them)", "/play/quests" in route_paths, True)
check("no route path contains story-arc", sorted(p for p in route_paths if "story-arc" in p), [])
check("/play/story-arcs is not a route", "/play/story-arcs" in route_paths, False)
from app.core import world_ops  # noqa: E402

check("world_ops has no build_player_story_arcs", hasattr(world_ops, "build_player_story_arcs"), False)

# ── (d) config ────────────────────────────────────────────────────────────
print("(d) config section and env mirror")
from app.core import config, config_schema  # noqa: E402

check("story_engine not in config_schema.SECTIONS", "story_engine" in config_schema.SECTIONS, False)
check("story_engine is a dead top-level section", "story_engine" in config.DEAD_TOPLEVEL_ONLY_FIELDS, True)
for key in [k for k in os.environ if k.startswith("STORY_ENGINE_")]:
    del os.environ[key]
config._flatten_to_env({})
check("no STORY_ENGINE_* env name from a default config",
      sorted(k for k in os.environ if k.startswith("STORY_ENGINE_")), [])

# ── (e) text scan ─────────────────────────────────────────────────────────
print("(e) text scan")
found = set()
bad_names = []
for top in SCAN_DIRS:
    base = ROOT / top
    for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            full = Path(dirpath) / fn
            rel = full.relative_to(ROOT).as_posix()
            if re.search(r"story_arc|story_engine", fn):
                bad_names.append(rel)
            try:
                text = full.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                if WORDS.search(line):
                    found.add((rel, line.strip()))
check("no file name with story_arc / story_engine", bad_names, [])
check("unexpected leftovers", sorted(found - ALLOWED), [])
check("every allowed leftover is really there (the one-shot and the two config lines)", sorted(ALLOWED - found), [])

old = subprocess.run(["git", "grep", "-c", "-E", WORDS.pattern, OLD_COMMIT, "--",
                      "app", "shared/templates", "shared/prompt_filters", "static/admin"],
                     cwd=ROOT, capture_output=True, text=True)
old_total = sum(int(line.rsplit(":", 1)[1]) for line in old.stdout.splitlines() if line.strip())
check(f"the scanner's words hit >= {OLD_MIN_LINES} lines at {OLD_COMMIT}", old_total >= OLD_MIN_LINES, True)

# ── (g) frontend ──────────────────────────────────────────────────────────
print("(g) frontend sources and de.json")
import json  # noqa: E402

FRONT_WORDS = re.compile(r"StoryArcsPanel|story-arc|story_arc")
FRONT_DIRS = ("frontend/src", "packages/player-ui/src")
front_hits = []
for top in FRONT_DIRS:
    for dirpath, dirnames, filenames in os.walk(ROOT / top):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            full = Path(dirpath) / fn
            rel = full.relative_to(ROOT).as_posix()
            if FRONT_WORDS.search(fn):
                front_hits.append(rel)
            try:
                text = full.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                continue
            front_hits += [f"{rel}: {line.strip()}" for line in text.splitlines() if FRONT_WORDS.search(line)]
check("frontend sources: no StoryArcsPanel / story-arc / story_arc", front_hits, [])
de = json.loads((ROOT / "shared/languages/de.json").read_text(encoding="utf-8"))["translations"]
check("de.json has translations (the scan is not looking at an empty dict)", len(de) > 1000, True)
check("de.json: no key containing 'story arc'", sorted(k for k in de if "story arc" in k.lower()), [])

# ── (h) built bundles ─────────────────────────────────────────────────────
print("(h) built bundles")
BUNDLE_DIRS = ("static/game_admin", "static/hud")
bundle_hits = []
for top in BUNDLE_DIRS:
    base = ROOT / top
    if not base.is_dir():
        check(f"{top} exists", top in ("static/hud",), True)
        continue
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(base):
        for fn in filenames:
            full = Path(dirpath) / fn
            scanned += 1
            try:
                if b"play/story-arcs" in full.read_bytes():
                    bundle_hits.append(full.relative_to(ROOT).as_posix())
            except OSError:
                continue
    check(f"{top}: files scanned", scanned >= 1, True)
check("no built bundle polls play/story-arcs", sorted(bundle_hits), [])

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} — {', '.join(FAILURES)}")
    sys.exit(1)
print("OK: the story arc engine is gone")
