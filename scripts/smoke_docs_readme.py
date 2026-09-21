#!/usr/bin/env python3
"""Smoke: every concrete thing README.md names really exists.

Usage:  ./.venv/bin/python scripts/smoke_docs_readme.py

The README is the one document a newcomer follows literally: they copy the
start command, the queue command, the npm script, they click the route. A
flag that was renamed or a route that was deleted therefore costs a reader a
debugging session, and nothing in the build catches it. This check does.

Pure text work: the README, `start.sh`, `queue_cli.py`, the `package.json`
files and the FastAPI decorators under `app/` are read and compared. No
server, no world DB, nothing from ``app`` is imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) ``./start.sh --flag`` — every long flag the README uses in a start.sh
   command line, plus every flag it names alone in a code span, must be a case
   of the argument loop in ``start.sh``. Expected value = the ``--x)`` /
   ``--x|--y)`` labels of that ``case "$1" in`` block, because that loop is
   what actually accepts an argument (``--help`` text can lie, the case list
   cannot).

B) ``queue_cli.py <sub>`` — every subcommand used in a README command line
   must be a ``sub.add_parser("<name>")`` in ``queue_cli.py``, and every long
   option on that line must be one of that parser's ``add_argument`` names.

C) ``npm run <script> [-w <workspace>]`` — the script must exist in the
   ``scripts`` block of the addressed ``package.json`` (the workspace's, or
   the repository root's when no ``-w`` is given). Workspace directories are
   resolved through the root ``workspaces`` globs.

D) Repository paths — every inline code span and every relative markdown link
   that looks like a repo path must exist on disk. Paths that only appear at
   runtime (``logs/``, ``models/``, ``client3d/dist/``, …) are exempt by
   prefix; anything with a ``<placeholder>``, a brace or a glob is skipped.

E) Route paths — every ``/path`` the README names in a code span must be
   served. Expected value = the routes collected from the FastAPI decorators:
   for each ``app/routes/*.py`` the ``APIRouter(prefix=…)`` (each of those
   files has exactly one router) plus every ``@router.<verb>("…")``, plus the
   ``@app.<verb>("…")`` of ``app/server.py`` and the ``app.mount("…")``
   prefixes. A README path passes when it is a segment-wise prefix of a real
   route, so ``/play/locations`` is accepted for
   ``/play/locations/{location_id}/scene`` while ``/play/lcoations`` is not.
   Paths of the *provider's* API (``/v1/...``) are not ours and are skipped.

The check is deliberately about existence, not about wording: it cannot know
whether a sentence is still true, only that everything it points at is there.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
START_SH = REPO / "start.sh"
QUEUE_CLI = REPO / "queue_cli.py"

# Paths that exist only on a running/installed instance, never in a fresh
# checkout. Documenting them is right; requiring them on disk is not.
RUNTIME_PREFIXES = (
    "logs/", "models/", "voices/", "exports/", "storage/", ".venv/",
    "client3d/dist/", "plugins/installed/", "node_modules/",
)
# Bare file names that are not repository paths (they live inside a world).
NOT_REPO_FILES = {"world.db", "task_queue.db", "config.json", "secrets.json",
                  "world_setup.json", "plugin.yaml", "package.json",
                  "vite.config.ts", "index.html", "play.html", "LICENSE"}
# Identifiers of OTHER projects that happen to be spelled like a path.
EXTERNAL_IDS = {"BAAI/bge-small-en-v1.5"}

_failures = []
_checks = 0


def check(label, ok, detail=""):
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


# ---------------------------------------------------------------------------
# README extraction
# ---------------------------------------------------------------------------

def fenced_blocks(text):
    return re.findall(r"^```[a-zA-Z]*\n(.*?)^```", text, re.S | re.M)


def code_spans(text):
    """Inline `code` spans, with the fenced blocks removed first."""
    stripped = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    return re.findall(r"`([^`\n]+)`", stripped)


def command_lines(text, prefix):
    """Lines of a fenced block that invoke `prefix` (e.g. './start.sh')."""
    out = []
    for block in fenced_blocks(text):
        for line in block.splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith(prefix):
                out.append(line)
    return out


# ---------------------------------------------------------------------------
# A) start.sh flags
# ---------------------------------------------------------------------------

def start_sh_flags():
    """The labels of the argument `case` block — what start.sh really takes."""
    src = START_SH.read_text(encoding="utf-8")
    m = re.search(r'while \[\[ \$# -gt 0 \]\]; do\n\s*case "\$1" in\n(.*?)\n\s*esac',
                  src, re.S)
    if not m:
        return set()
    flags = set()
    for label in re.findall(r"^\s*((?:--?[a-z0-9|-]+)+)\)", m.group(1), re.M):
        flags.update(f for f in label.split("|") if f.startswith("-"))
    return flags


def check_start_flags(readme):
    real = start_sh_flags()
    check("start.sh still has a parsable argument case block", len(real) >= 5,
          str(sorted(real)))

    used = set()
    for line in command_lines(readme, "./start.sh"):
        used.update(re.findall(r"(--[a-z0-9-]+)", line))
    # Flags the prose names on their own, e.g. `--with-3d`.
    for span in code_spans(readme):
        if re.fullmatch(r"--[a-z0-9-]+", span.strip()):
            used.add(span.strip())

    check(f"the README uses at least 5 start.sh flags ({len(used)})", len(used) >= 5,
          str(sorted(used)))
    unknown = sorted(f for f in used if f not in real)
    check("every start.sh flag the README names exists", not unknown,
          f"{unknown} not in {sorted(real)}")


# ---------------------------------------------------------------------------
# B) queue_cli subcommands
# ---------------------------------------------------------------------------

def queue_cli_parsers():
    """{subcommand: {long options}} straight out of queue_cli.py."""
    src = QUEUE_CLI.read_text(encoding="utf-8")
    subs = {}
    # Each parser is built as `p_x = sub.add_parser("name" ...)` followed by
    # `p_x.add_argument(...)` lines until the next add_parser.
    chunks = re.split(r"\n(?=\s*\w+\s*=\s*sub\.add_parser\()", src)
    for chunk in chunks:
        m = re.search(r'sub\.add_parser\(\s*"([a-z_]+)"', chunk)
        if not m:
            continue
        var = re.search(r"(\w+)\s*=\s*sub\.add_parser\(", chunk).group(1)
        opts = set(re.findall(rf'{var}\.add_argument\(\s*"(--[a-z0-9-]+)"', chunk))
        subs[m.group(1)] = opts
    return subs


def check_queue_cli(readme):
    subs = queue_cli_parsers()
    check(f"queue_cli.py exposes subcommands ({len(subs)})", len(subs) >= 8,
          str(sorted(subs)))

    used = {}
    for line in command_lines(readme, "python queue_cli.py"):
        parts = line.split()[2:]
        positional = [p for p in parts if not p.startswith("-")]
        if not positional:
            continue
        name = positional[0]
        used.setdefault(name, set()).update(re.findall(r"(--[a-z0-9-]+)", line))

    check(f"the README shows at least 8 queue_cli subcommands ({len(used)})",
          len(used) >= 8, str(sorted(used)))
    unknown = sorted(n for n in used if n not in subs)
    check("every queue_cli subcommand the README names exists", not unknown,
          f"{unknown} not in {sorted(subs)}")
    bad_opts = sorted(f"{n} {o}" for n, os_ in used.items() if n in subs
                      for o in os_ if o not in subs[n])
    check("every queue_cli option the README names exists", not bad_opts, str(bad_opts))


# ---------------------------------------------------------------------------
# C) npm scripts
# ---------------------------------------------------------------------------

def workspace_dirs():
    root = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    dirs = {}
    for pattern in root.get("workspaces", []):
        for path in sorted(REPO.glob(pattern)):
            pkg = path / "package.json"
            if pkg.is_file():
                name = json.loads(pkg.read_text(encoding="utf-8")).get("name", path.name)
                dirs[name] = path
                dirs[path.name] = path
    return dirs


def scripts_of(pkg_dir):
    pkg = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
    return set(pkg.get("scripts", {}))


def check_npm_scripts(readme):
    dirs = workspace_dirs()
    root_scripts = scripts_of(REPO)
    check(f"the workspace root lists workspaces ({len(set(dirs.values()))} packages)",
          len(set(dirs.values())) >= 3, str(sorted(p.name for p in set(dirs.values()))))

    uses = re.findall(r"npm run ([a-z0-9:-]+)((?:\s+-w\s+[a-zA-Z0-9/_-]+)?)", readme)
    check(f"the README shows npm scripts ({len(uses)})", len(uses) >= 5)

    bad = []
    for script, ws in uses:
        ws = ws.strip()
        if ws:
            name = ws.split()[-1]
            target = dirs.get(name)
            if target is None:
                bad.append(f"npm run {script} -w {name} (unknown workspace)")
                continue
            if script not in scripts_of(target):
                bad.append(f"npm run {script} -w {name}")
        elif script not in root_scripts:
            bad.append(f"npm run {script} (root)")
    check("every npm script the README names exists", not bad, str(bad))


# ---------------------------------------------------------------------------
# D) repository paths
# ---------------------------------------------------------------------------

_PATH_RE = re.compile(r"^\.?/?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/?$")
_PLACEHOLDER = re.compile(r"[<>{}*…]|\bNAME\b|\bPATH\b")


def readme_repo_paths(readme):
    out = set()
    for span in code_spans(readme):
        span = span.strip()
        if _PLACEHOLDER.search(span) or " " in span:
            continue
        if span.startswith("/") or not _PATH_RE.match(span):
            continue
        if "/" not in span.rstrip("/") and span not in ("start.sh", "queue_cli.py"):
            continue
        out.add(span.lstrip("./") if span.startswith("./") else span)
    # Relative markdown links, e.g. [`docs/x.md`](docs/x.md)
    for target in re.findall(r"\]\(([^)#\s]+)\)", readme):
        if target.startswith(("http", "#", "mailto:")) or _PLACEHOLDER.search(target):
            continue
        out.add(target)
    return {p for p in out if p not in NOT_REPO_FILES and p not in EXTERNAL_IDS}


def check_repo_paths(readme):
    paths = readme_repo_paths(readme)
    check(f"the README names repository paths ({len(paths)})", len(paths) >= 20)
    missing = sorted(p for p in paths
                     if not p.startswith(RUNTIME_PREFIXES)
                     and not (REPO / p).exists())
    check("every repository path the README names exists", not missing, str(missing))


# ---------------------------------------------------------------------------
# E) route paths
# ---------------------------------------------------------------------------

def real_routes():
    """Every route path the FastAPI app serves, as written in the decorators."""
    routes = set()
    for f in sorted((REPO / "app" / "routes").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        m = re.search(r'APIRouter\((?:[^()]|\([^()]*\))*\)', src)
        prefix = ""
        if m:
            pm = re.search(r'prefix\s*=\s*"([^"]*)"', m.group(0))
            prefix = pm.group(1) if pm else ""
        for path in re.findall(r'@router\.(?:get|post|put|delete|patch)\(\s*"([^"]*)"', src):
            full = (prefix + path) or "/"
            routes.add(full if full.startswith("/") else "/" + full)
    server = (REPO / "app" / "server.py").read_text(encoding="utf-8")
    routes.update(re.findall(r'@app\.(?:get|post|put|delete|patch)\(\s*"([^"]*)"', server))
    routes.update(re.findall(r'app\.mount\(\s*"([^"]*)"', server))
    return {r.rstrip("/") or "/" for r in routes}


def segments(path):
    return [s for s in path.strip("/").split("/") if s]


def is_prefix_of(candidate, route):
    cs, rs = segments(candidate), segments(route)
    if len(cs) > len(rs):
        return False
    return all(r.startswith("{") or r == c for c, r in zip(cs, rs))


# The lookbehind keeps out everything that only LOOKS like a route: a URL
# (`http://localhost`), the tail of a placeholder (`{id}/scene`,
# `<world>/task_queue.db`) and a relative path (`./storage/...`).
_ROUTE_RE = re.compile(r"(?<![\w.:>}/-])/[a-z][a-z0-9-]*(?:/[a-z0-9_-]+)*")


def readme_routes(readme):
    out = set()
    for span in code_spans(readme):
        for m in _ROUTE_RE.findall(span):
            if m.startswith("/v1"):          # the LLM provider's API, not ours
                continue
            out.add(m.rstrip("/"))
    return out


def check_routes(readme):
    real = real_routes()
    check(f"routes collected from the decorators ({len(real)})", len(real) >= 100)

    named = readme_routes(readme)
    check(f"the README names route paths ({len(named)})", len(named) >= 10, str(sorted(named)))

    unknown = sorted(c for c in named if not any(is_prefix_of(c, r) for r in real))
    check("every route path the README names is served", not unknown, str(unknown))


def main():
    readme = README.read_text(encoding="utf-8")
    print("A) ./start.sh flags")
    check_start_flags(readme)
    print("B) queue_cli.py subcommands and options")
    check_queue_cli(readme)
    print("C) npm scripts")
    check_npm_scripts(readme)
    print("D) repository paths")
    check_repo_paths(readme)
    print("E) route paths")
    check_routes(readme)

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
