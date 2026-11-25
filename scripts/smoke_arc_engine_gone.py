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
         "chat/agent_thought.md" whose content contains "{{ arc_block }}" (would raise under StrictUndefined once
         the key is gone), and "chat/agent_thought_in_chat.md" with plain content (the control: no arc reference).
     After db.init_schema():
       - sqlite_master has no table "story_arcs" (DROP ran, and no CREATE statement brings it back),
       - the overrides left are exactly {"chat/agent_thought_in_chat.md"} (the arc template row by its path, the
         agent_thought row by its content; the control row stays),
       - schema_meta holds story_arcs_dropped_v1 = "1",
       - exactly ONE warning names "chat/agent_thought.md" together with the world path (the storage dir).
     A second init_schema() leaves the table absent (the CREATE statement is gone from SCHEMA_STATEMENTS — with it
     still present the table would be recreated empty) and issues no further warning about the override.
 (b) importlib.import_module("app.core.story_engine") and ("app.models.story_arcs") raise ModuleNotFoundError.
 (c) No route path of the real app (app.server.app) contains "story-arc" (the three /queue/story-arc routes went).
 (d) "story_engine" is not a key of config_schema.SECTIONS; it IS in config.DEAD_TOPLEVEL_ONLY_FIELDS (a stored
     section is stripped on load, no "unknown root key" warning); after config._flatten_to_env({}) (a default
     config: every field falls back to its schema default) no os.environ name starts with "STORY_ENGINE_".
 (e) A text scan of app/, plugins/ (following the symlinked packs), shared/templates, shared/prompt_filters and
     static/admin for the words story_arc | story_engine | arc_block | inject_arc_context finds exactly these lines
     (stripped) and nothing else:
       app/core/config.py   the image-routing seed tuple    ("photo", ("story_engine.imagegen_default",)),
       app/core/config.py   the dead-field entry            DEAD_TOPLEVEL_ONLY_FIELDS ... "body_retexture", "story_engine")
       app/core/db.py       the drop one-shot: the flag lookup, the flag insert, DROP TABLE IF EXISTS story_arcs,
                            the three template paths tasks/story_arc_generation.md | _advancement.md | _resolve.md
                            and the content test for 'arc_block'  (7 lines, listed verbatim in ALLOWED below)
     Nor does any scanned FILE NAME contain story_arc / story_engine.
     The scanner is not looking away: at commit 3a444d8bf (before the removal) git grep of the same words over the
     same tracked directories counts >= 110 lines (hand count of that commit: config.py 7, story_engine.py 30,
     template_preview.py 17, story_arcs.py 9, queue.py 6, ... = 110).
 (f) "/play/story-arcs" is not a route of the real app, and app.core.world_ops has no build_player_story_arcs
     (the player panel reads /play/quests since Task 8).
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


WORDS = re.compile(r"story_arc|story_engine|arc_block|inject_arc_context")
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
    ("app/core/db.py", '"WHERE instr(content, \'arc_block\') > 0"'),
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
for path, content in (("tasks/story_arc_generation.md", "an old arc prompt"),
                      ("chat/agent_thought.md", "before\n{% if arc_block %}{{ arc_block }}{% endif %}\nafter"),
                      ("chat/agent_thought_in_chat.md", "a plain override")):
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


def flag() -> object:
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute("SELECT value FROM schema_meta WHERE key='story_arcs_dropped_v1'").fetchone()
        return row[0] if row else None
    finally:
        con.close()


world = str(paths.get_storage_dir())
check("table story_arcs dropped", table_present(), False)
check("overrides left: only the control row", overrides(), {"chat/agent_thought_in_chat.md"})
check("flag story_arcs_dropped_v1 set", flag(), "1")
named = [w for w in warnings if "chat/agent_thought.md" in w and world in w]
check("one warning names the agent_thought override and the world path", len(named), 1)
before = len(warnings)
db.init_schema()
check("second init_schema: table still absent", table_present(), False)
check("second init_schema: no further override warning",
      [w for w in warnings[before:] if "chat/agent_thought.md" in w], [])
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

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} — {', '.join(FAILURES)}")
    sys.exit(1)
print("OK: the story arc engine is gone")
