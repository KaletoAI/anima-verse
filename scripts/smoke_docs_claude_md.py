#!/usr/bin/env python3
"""Guard for CLAUDE.md: every path, flag, npm script and symbol it names exists.

Usage:
    ./.venv/bin/python scripts/smoke_docs_claude_md.py

No server, no world DB, no imports of app code — a pure filesystem + text scan
of the repository root.

WHY. CLAUDE.md is the first thing every AI coding session in this repo reads.
A stale file path or a function name that moved does not produce a stack trace;
it produces an agent that looks in the wrong place and then invents something.
The cheap half of that is mechanical, so it is checked here.

CLAUDE.md is GITIGNORED (it is local guidance, not repo content). When it is
absent this check prints a note and exits 0 — a fresh clone must not fail.

WHAT IS CHECKED (everything in `backticks`, plus the fenced command block)

1. REPO PATHS — a backticked token that looks like a path (carries a source
   extension, ends in "/", or contains a wildcard) must resolve:
     * as-is from the repo root, or
     * as a path/directory SUFFIX ("routes/world.py" -> "app/routes/world.py",
       "src/hud/" -> "client3d/src/hud"), or
     * by basename anywhere in the repo ("agent_loop.py"), or
     * for a token with a <placeholder>/glob, its longest literal prefix.
   Tokens starting with "/" are URL routes, not paths, and are skipped; the
   per-world runtime files live in PATH_ALLOW.

2. start.sh FLAGS — every "./start.sh --flag" in the document must appear as a
   case label in start.sh.

3. npm SCRIPTS — every "npm run <name>" must exist in the package.json it
   belongs to: the workspace named by "-w <ws>", else the root package.json for
   a "group:target" name, else frontend/ or the root.

4. PYTHON SYMBOLS — three shapes must resolve:
     * a backticked CALL (``foo()``, ``mod.foo(...)``) — the name has to be
       defined somewhere under app/, plugins/, scripts/, packages/, client3d/
       or frontend/ (def/class/assignment/JS function or const);
     * ``<file>.py::<symbol>`` — that file must define that symbol;
     * ``<module>.<name>`` where a file ``<module>.py`` exists in the repo —
       then ``<name>`` must be defined in it. This is the shape that catches a
       renamed helper written without parentheses; config SECTIONS that share a
       module name are listed in DOTTED_ALLOW.

ALLOWLIST. Prose words that only look like symbols live in SYMBOL_ALLOW below,
each with the reason it is there. Nothing else is exempt; if a real symbol goes
missing, the fix is the document, not this list.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "CLAUDE.md"

#: Directories a basename/symbol search never descends into.
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "migration_backup",
             "graphify-out", "dist", "build", ".cache", "logs", "worlds",
             "storage", "exports", ".mypy_cache", ".ruff_cache"}

#: Source extensions that make a bare backticked token count as a path.
PATH_EXTS = (".py", ".md", ".json", ".ts", ".tsx", ".sh", ".yaml", ".yml",
             ".mjs", ".js", ".css", ".html", ".fbx", ".glb", ".db")

#: Calls that are NOT project symbols. Each entry says why.
SYMBOL_ALLOW = {
    "max": "Python builtin, used in the watchdog-budget formula",
    "Depends": "FastAPI, not ours",
    "weekday": "named as a datetime method GameTime deliberately lacks",
    "date": "same — a datetime method, listed as forbidden",
    "init": "written as paths.init(<tmpdir>), resolved via app/core/paths.py",
    "f": "placeholder in a prose example, if one ever appears",
}

#: Dotted "<section>.<key>" tokens that are CONFIG keys, although a module of
#: that name exists. Each entry says which config section it is.
DOTTED_ALLOW = {
    "server": "config section server.* (cors_origins, max_upload_mb, ...)",
    "config": "prose prefix for a config path, e.g. config.embedding.backend",
    "memory": "config section memory.* (situational_*)",
    "image": "config section image.use_cases",
}

#: Path tokens that name a file only a RUNTIME world has (worlds/ is not
#: scanned, and a fresh checkout ships none of these).
PATH_ALLOW = {
    "world.db": "per-world runtime DB",
    "task_queue.db": "per-world runtime DB",
    "secrets.json": "per-world, gitignored",
    "suitability_cases.json": "per-world test output, gitignored",
}

FAILURES = []


def fail(kind, detail):
    FAILURES.append(f"{kind}: {detail}")
    print(f"FAIL {kind}: {detail}")


def ok(msg):
    print(f"ok   {msg}")


# ---------------------------------------------------------------------------
# Repository index (built once)
# ---------------------------------------------------------------------------
def walk_files():
    for dirpath, dirnames, filenames in os.walk(ROOT, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            yield Path(dirpath) / fn


ALL_FILES = list(walk_files())
BY_NAME: dict = {}
for _p in ALL_FILES:
    BY_NAME.setdefault(_p.name, []).append(_p)

REL_PATHS = set()
REL_DIRS = set()
for _p in ALL_FILES:
    try:
        rel = _p.relative_to(ROOT).as_posix()
    except ValueError:
        continue
    REL_PATHS.add(rel)
    parts = rel.split("/")
    for i in range(1, len(parts)):
        REL_DIRS.add("/".join(parts[:i]))

# Source text of everything a symbol could be defined in, concatenated once.
SRC_EXT = (".py", ".ts", ".tsx", ".mjs", ".js")
SRC_ROOTS = ("app", "plugins", "scripts", "packages", "client3d", "frontend")
_src_chunks = []
for _p in ALL_FILES:
    if _p.suffix not in SRC_EXT:
        continue
    try:
        rel = _p.relative_to(ROOT).as_posix()
    except ValueError:
        continue
    if not rel.startswith(SRC_ROOTS):
        continue
    try:
        _src_chunks.append(_p.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        pass
SRC = "\n".join(_src_chunks)


def symbol_defined(name: str) -> bool:
    """True when `name` is defined anywhere in the scanned source."""
    pat = (rf"(?:^|\n)\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b"
           rf"|(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\b"
           rf"|(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+{re.escape(name)}\b"
           rf"|(?:^|\n)\s*{re.escape(name)}\s*[:=]"
           rf"|\b{re.escape(name)}\s*\(")
    return re.search(pat, SRC) is not None


# ---------------------------------------------------------------------------
if not DOC.exists():
    print(f"note: {DOC.relative_to(ROOT)} is absent (it is gitignored) — nothing to check.")
    sys.exit(0)

TEXT = DOC.read_text(encoding="utf-8")
TOKENS = set(re.findall(r"`([^`\n]+)`", TEXT))


# --- 1. paths --------------------------------------------------------------
def looks_like_path(tok: str) -> bool:
    if not re.match(r"^[\w./<>*\[\]-]+$", tok):
        return False
    if tok.endswith("/") or re.search(r"[<*\[]", tok):
        return "/" in tok or tok.endswith(PATH_EXTS)
    # otherwise it must carry a source extension — "window.prompt/alert/confirm"
    # is prose, not a path.
    return tok.endswith(PATH_EXTS)


def literal_prefix(tok: str) -> str:
    """The part of a placeholder/glob token before the first wildcard."""
    cut = len(tok)
    for ch in "<*[":
        i = tok.find(ch)
        if i != -1:
            cut = min(cut, i)
    return tok[:cut]


def path_resolves(tok: str) -> bool:
    tok = tok.rstrip("/")
    if not tok:
        return True
    if (ROOT / tok).exists():
        return True
    if "/" not in tok and tok in BY_NAME:      # "agent_loop.py"
        return True
    # suffix match: "core/world_ops.py" -> "app/core/world_ops.py",
    # "src/hud" -> "client3d/src/hud", "tasks" -> "shared/templates/llm/tasks"
    suffix = "/" + tok
    if any(r.endswith(suffix) for r in REL_PATHS):
        return True
    if tok in REL_DIRS or any(d.endswith(suffix) for d in REL_DIRS):
        return True
    return False


path_tokens = sorted(t for t in TOKENS if looks_like_path(t))
checked = 0
for tok in path_tokens:
    if tok.startswith("/"):
        continue                    # URL route, not a filesystem path
    if tok in PATH_ALLOW:
        continue
    checked += 1
    if re.search(r"[<*\[]", tok):
        prefix = literal_prefix(tok).rstrip("/")
        if not prefix:
            continue
        base = prefix if "/" in prefix else prefix
        if (ROOT / base).exists() or path_resolves(base):
            continue
        # a placeholder in the middle: fall back to the directory in front
        parent = base.rsplit("/", 1)[0] if "/" in base else ""
        if parent and (ROOT / parent).exists():
            continue
        fail("path", f"{tok!r} — nothing at {prefix!r}")
        continue
    if not path_resolves(tok):
        fail("path", f"{tok!r} does not exist")
ok(f"repo paths ({checked} checked)")


# --- 2. start.sh flags -----------------------------------------------------
START = (ROOT / "start.sh").read_text(encoding="utf-8")
flags = set(re.findall(r"\./start\.sh\s+(--[a-z0-9-]+)", TEXT))
# also the "| --restart | --status" continuation form
flags |= set(re.findall(r"\|\s*(--[a-z0-9-]+)", TEXT))
for f in sorted(flags):
    if not re.search(rf"^\s*{re.escape(f)}[\s)|]", START, re.M):
        fail("start.sh flag", f"{f} is documented but start.sh has no case for it")
ok(f"start.sh flags ({len(flags)} checked)")


# --- 3. npm scripts --------------------------------------------------------
def scripts_of(rel: str):
    p = ROOT / rel
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("scripts", {}) or {}
    except (OSError, ValueError):
        return {}


PKG = {rel: scripts_of(rel) for rel in
       ("package.json", "frontend/package.json", "client3d/package.json")}

npm_checked = 0
for line in TEXT.splitlines():
    for m in re.finditer(r"npm run ([\w:-]+)((?:\s+-w\s+[\w/@-]+)?)", line):
        name, ws = m.group(1), m.group(2).strip()
        npm_checked += 1
        if ws:
            rel = ws.split()[-1] + "/package.json"
            where = [rel]
        elif ":" in name:
            where = ["package.json"]
        else:
            where = ["frontend/package.json", "package.json"]
        if not any(name in PKG.get(w, {}) for w in where):
            fail("npm script", f"'npm run {name}' not in {' or '.join(where)}")
ok(f"npm scripts ({npm_checked} checked)")


# --- 4. python / JS symbols ------------------------------------------------
sym_checked = 0
for tok in sorted(TOKENS):
    # <file>.py::<symbol>
    m = re.match(r"^([\w./-]+\.py)::(\w+)$", tok)
    if m:
        sym_checked += 1
        f, name = m.group(1), m.group(2)
        cand = ROOT / f
        if not cand.exists():
            fail("symbol", f"{tok}: file {f} does not exist")
        elif not re.search(rf"(?:^|\n)\s*(?:async\s+)?(?:def|class)\s+{name}\b",
                           cand.read_text(encoding="utf-8", errors="ignore")):
            fail("symbol", f"{tok}: {f} defines no {name}")
        continue
    # dotted module.symbol without parentheses ("chat.save_message").
    # A file name ("service.py") is a PATH and was checked as one above.
    m = re.match(r"^([a-z_][a-z0-9_]*)\.([A-Za-z_]\w*)$", tok)
    if m and not looks_like_path(tok) and m.group(1) not in DOTTED_ALLOW:
        mod, name = m.group(1), m.group(2)
        files = BY_NAME.get(mod + ".py", [])
        if files:
            sym_checked += 1
            pat = rf"(?:^|\n)\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b|(?:^|\n){re.escape(name)}\s*[:=]"
            if not any(re.search(pat, f.read_text(encoding="utf-8", errors="ignore"))
                       for f in files):
                fail("symbol", f"{tok}: {mod}.py defines no {name}")
            continue
    # a call: foo(...), mod.foo(...), obj().bar(...)
    for name in re.findall(r"([A-Za-z_]\w*)\s*\(", tok):
        if name in SYMBOL_ALLOW:
            continue
        sym_checked += 1
        if not symbol_defined(name):
            fail("symbol", f"{tok}: '{name}' is not defined anywhere in the source")
ok(f"symbols ({sym_checked} checked)")


# ---------------------------------------------------------------------------
print()
if FAILURES:
    print(f"{len(FAILURES)} problem(s) in CLAUDE.md")
    sys.exit(1)
print("all checks passed")
