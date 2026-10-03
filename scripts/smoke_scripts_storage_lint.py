#!/usr/bin/env python3
"""Lint: a check script must never open the TRACKED demo world.

Usage:  ./.venv/bin/python scripts/smoke_scripts_storage_lint.py

THE RULE, derived from app/core/paths.py (``init`` resolution order)

``paths.init()`` resolves the storage root as: explicit argument, else the
``STORAGE_DIR`` environment variable — and nothing else.  There is NO default
world any more: without either, ``init`` and ``get_storage_dir()`` raise
``paths.StorageNotInitialised``.  The default ``worlds/demo`` moved to the one
place that STARTS the server (``start.sh``, ``docker/docker-entrypoint.sh``,
both export ``STORAGE_DIR``).

That is what part 3 of this check pins down.  Until 2026-09-22 the resolution
ended in ``./worlds/demo`` and ``get_storage_dir()`` auto-initialised on first
call, so a script that never called ``init`` silently landed in the demo world
— which is TRACKED in git (CLAUDE.md: "worlds/demo/ **is** tracked in git").
Any app module that opened ``world.db`` therefore wrote into the shipped demo
world and left the working tree dirty.  It happened repeatedly; two cases:

  * scripts/test_finish_reason.py — ``_log_task_result`` -> ``llm_logger``
    -> ``llm_stats.record_call`` -> ``INSERT INTO llm_call_stats``.
  * scripts/test_respond_lane.py — ``AgentLoop()`` -> ``_is_paused`` ->
    ``is_world_frozen`` -> ``get_connection`` -> ``PRAGMA journal_mode=WAL``.

The raise makes such a reach LOUD, but a script must still not rely on it: a
script that imports a world-DB module MUST set a throwaway storage root BEFORE
that import — ``paths.init(<temp>)`` or the ``STORAGE_DIR`` env var.
"Before" is literal for a MODULE-LEVEL import: it executes at load time, and
whatever it touches at load time is decided by the storage root of that
moment.  An import inside a function runs on the call instead, so there any
redirect in the file counts.
``app.core.paths`` itself is exempt — it is what one calls ``init`` on.

THE CRITERION IS DELIBERATELY NARROW

A script counts as a candidate only if it DIRECTLY imports a world-DB module,
where "world-DB module" is computed, not guessed:

  * every app module whose OWN source calls ``get_connection(`` or
    ``transaction(`` (64 of 332 modules at the time of writing), plus
  * a short, commented list of modules that persist through exactly one
    helper and would otherwise be invisible (see ``PERSISTING_MODULES``).

The blunt alternative — "every script that imports anything from app" — flags
71 scripts, most of which only pull in pure functions and never open a
database.  A whitelist that long says nothing.  The transitive import closure
is no better: one hop out from the DB modules already covers 189 of 332 app
modules, because app/ is one connected web of imports.  Narrow and honest
beats broad and ignored.

WHITELIST

Scripts that work on a REAL world on purpose (CLI tools, not checks) are named
explicitly in ``INTENTIONAL_REAL_WORLD`` with the reason — never skipped
silently.

SELF-TEST, hand-derived (part 1 of the output)

The classifier is checked against twelve hand-written snippets before it
judges anything, so a broken lint fails loudly instead of passing everything.
Every expected verdict below is derived by hand from THE RULE above, never
recorded from a run:

  1. redirect via ``paths.init`` on line 3, DB import on line 5  -> clean
  2. DB import on line 3, ``paths.init`` on line 5 (too late)    -> offender
  3. no redirect at all, DB import present                       -> offender
  4. ``STORAGE_DIR`` env set before the DB import                -> clean
  5. app imports, but none of them a world-DB module             -> not a candidate
  6. ``from app.core import paths`` alone before ``init``        -> clean
     (the paths import must not count as "the first app import")
  7. DB import INSIDE a function, ``paths.init`` one line later  -> clean
     (a deferred import runs on the call, so line order proves nothing)
  8. DB import inside a function, no redirect anywhere           -> offender
  9. only a DOCSTRING mentions ``paths.init()``                  -> offender
     (prose is not code — and the sentence that says no redirect is needed
     used to BE the redirect, for a text search)
 10. ``paths.init()`` with NO argument, then the DB import       -> offender
     (no argument means the env decides — which for a check is no redirect at
     all; today it raises, before 2026-09-22 it silently took worlds/demo)
 11. only ``os.environ.get("STORAGE_DIR")`` is READ              -> offender
     (a read leaves the resolution order untouched)
 12. ``os.environ.setdefault("STORAGE_DIR", tmp)`` before it     -> clean
     (a write, just a conditional one — scripts here use this form)

Part 4 pins the same rule for the INSTANCE directory (per-installation
server config): ``paths.init_instance`` takes the argument, else
``INSTANCE_DIR``, else raises ``paths.InstanceNotInitialised``.

PART 5 — a script that imports ``app.server`` sets INSTANCE_DIR first

``app/server.py`` runs ``paths.init()`` and ``paths.init_instance()`` WITHOUT
an argument at import time, so for it only the environment decides — a
``paths.init(tmp)`` / ``paths.init_instance(tmp)`` in the script is simply
re-resolved.  A script that imports it must therefore WRITE both
``os.environ["INSTANCE_DIR"]`` and ``os.environ["STORAGE_DIR"]`` (assignment
or ``setdefault``) before a module-level import; for an import inside a
function any write in the file counts (same reasoning as part 2).  Hand-derived
fixtures, then a counter-check on a violating file in a temp directory, then
the real scan.

PART 6 — who touches the REAL instance is listed

A script reaches the real instance when it

  * calls ``init_instance()`` with NO argument (the env decides — for a
    check that is no redirect at all, cf. fixture 10 above),
  * calls ``init_instance(X)`` where X is not a temp path,
  * writes ``os.environ["INSTANCE_DIR"]`` with a value that is not a temp path,
  * or reads ``get_instance_config_path()`` / ``get_instance_dir()`` without a
    temp redirect before it (module level: an earlier line; inside a function:
    anywhere in the file).

"Temp path" is computed, not guessed: an expression that contains a call to
``mkdtemp`` / ``TemporaryDirectory``, or a name every assignment of which is
such an expression (``with … as tmp`` included; transitive, so
``INST = Path(tempfile.mkdtemp())`` and ``str(INST)`` both count).  Scope-blind
on purpose — the scripts here are flat.  Everything else — a literal,
``REPO / "instance"``, ``args.instance`` — is the real instance.  Such a script
must be named in ``INTENTIONAL_REAL_INSTANCE`` with the reason (the CLI tools
that pass ``--instance``); a stale entry fails as well.  Check scripts never
belong there: they use a temp instance.

Exit code 0 = paths.py has no default world and no default instance AND every
candidate redirects its storage AND every app.server importer sets
INSTANCE_DIR AND every real-instance reach is listed.  Exit 1 lists what is
wrong — including the line numbers that decide a script's verdict.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
SCRIPTS = REPO / "scripts"

# Modules that DO reach world.db but whose own source shows nothing: they hand
# the write to one helper.  Each entry names the chain it stands for.
PERSISTING_MODULES = {
    # log_llm_call() -> llm_stats.record_call() -> INSERT INTO llm_call_stats
    "app.utils.llm_logger",
    # _log_task_result() -> llm_logger.log_llm_call() -> the same INSERT
    "app.core.provider_queue",
}

# Scripts that operate on a REAL world by design — CLI tools, not checks.
# Listing them here is the point: they are exempt, not overlooked.
INTENTIONAL_REAL_WORLD = {
    # Reads a live world and writes an export next to it.
    "export_world_content.py",
    # One-off migration: rewrites rows of an existing world in place.
    "backfill_canonical.py",
    # Interactive review tool over a world's stored presets.
    "review_presets.py",
    # Task-queue CLI; takes its DB path from the legacy root .env.
    "queue_cli.py",
    # This lint itself: it parses sources; the only app module it imports is
    # app.core.paths (part 4), which opens no world.
    "smoke_scripts_storage_lint.py",
}

# Scripts that reach the REAL instance directory on purpose (part 6).  CLI
# tools that need instance config (providers, routing, catalogs + tokens) take
# ``--instance PATH`` with the default ``<repo>/instance`` set in the tool.
INTENTIONAL_REAL_INSTANCE = {
    "review_presets.py":
        "CLI tool: calls the LLMs configured in the instance "
        "(providers, llm_routing); --instance, default <repo>/instance",
    "marketplace_publish.py":
        "CLI tool: publishes to a catalog whose URL + auth_token are instance "
        "config; --instance, default <repo>/instance",
    "smoke_scripts_storage_lint.py":
        "this lint: part 4 calls init_instance() without an argument on purpose "
        "(INSTANCE_DIR popped) to prove it raises, and restores INSTANCE_DIR",
}

# scripts/legacy/ is out of scope wholesale: retired tools, kept only for
# reference, never run as a check (CLAUDE.md: "only scripts/legacy/ stays out").
SKIPPED_DIRS = {"legacy", "__pycache__"}

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(f"{label}: {detail}" if detail else label)


def module_name(path: Path) -> str:
    name = ".".join(path.relative_to(REPO).with_suffix("").parts)
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def world_db_modules() -> set:
    """App modules whose own source opens the world DB, plus the persisting ones."""
    opens = re.compile(r"\bget_connection\s*\(|\btransaction\s*\(")
    found = set()
    for path in APP.rglob("*.py"):
        if opens.search(path.read_text(encoding="utf-8", errors="replace")):
            found.add(module_name(path))
    return found | PERSISTING_MODULES


def app_imports(source: str):
    """[(lineno, module, nested)] for every app import, submodule names resolved.

    ``from app.core import paths`` / ``import app.core.paths`` are reported as
    the module ``app.core.paths`` so the caller can exempt them.  *nested* is
    True for an import inside a function or class body: that one runs when the
    function is CALLED, so the surrounding code decides the storage and the
    line order alone proves nothing.  A module-level import runs at load time,
    where the order is the whole point.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    nested_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    nested_lines.add(inner.lineno)
    out = []
    for node in ast.walk(tree):
        nested = node.lineno in nested_lines if hasattr(node, "lineno") else False
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app"):
                    out.append((node.lineno, alias.name, nested))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level or not mod.startswith("app"):
                continue
            for alias in node.names:
                out.append((node.lineno, f"{mod}.{alias.name}", nested))
            out.append((node.lineno, mod, nested))
    return sorted(out)


def dotted(node) -> str:
    """Dotted name of a Name/Attribute expression, "" for anything else."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def is_storage_env(node) -> bool:
    """True for the subscript ``os.environ["STORAGE_DIR"]`` (or bare ``environ``)."""
    if not isinstance(node, ast.Subscript):
        return False
    if dotted(node.value).split(".")[-1] != "environ":
        return False
    key = node.slice
    return isinstance(key, ast.Constant) and key.value == "STORAGE_DIR"


def redirect_line(source: str):
    """First line that STRUCTURALLY sets a storage root, or None.

    Structural, not textual.  The predecessor searched the text of every
    non-comment line for ``paths.init(`` or ``"STORAGE_DIR"``, which got all
    three of these wrong:

      * a DOCSTRING naming ``paths.init()`` counted as a redirect — even the
        sentence "it builds without a world, so no paths.init() is needed",
        i.e. the very statement that there is none;
      * ``paths.init()`` WITHOUT an argument counted — yet that is exactly the
        call that falls back to ``./worlds/demo``, the opposite of a redirect;
      * merely READING ``os.environ.get("STORAGE_DIR")`` counted.

    Only two shapes count, both taken from the resolution order in
    app/core/paths.py: a call to ``paths.init`` WITH at least one argument
    (positional or ``storage_dir=``), and a WRITE to
    ``os.environ["STORAGE_DIR"]`` — assignment, augmented/annotated
    assignment, or ``os.environ.setdefault("STORAGE_DIR", ...)``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(is_storage_env(t) for t in node.targets):
                lines.append(node.lineno)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if is_storage_env(node.target):
                lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            name = dotted(node.func)
            if name == "paths.init" or name.endswith(".paths.init"):
                if node.args or node.keywords:
                    lines.append(node.lineno)
            elif (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setdefault"
                    and dotted(node.func.value).split(".")[-1] == "environ"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "STORAGE_DIR"):
                lines.append(node.lineno)
    return min(lines) if lines else None


def verdict(source: str, db_modules: set):
    """('clean' | 'offender' | 'no-db', first db import line, module, redirect line)."""
    first = None
    for lineno, mod, nested in app_imports(source):
        if mod in db_modules:
            first = (lineno, mod, nested)
            break
    if first is None:
        return "no-db", None, None, None
    where = redirect_line(source)
    if where is None:
        ok = False
    elif first[2]:
        ok = True          # deferred import: any redirect in the file covers it
    else:
        ok = where < first[0]
    return ("clean" if ok else "offender"), first[0], first[1], where


# ---------------------------------------------------------------- self-test

FIXTURES = [
    ("1 redirect before the DB import", "clean", '''
import os
from app.core import paths
paths.init("/tmp/x")
from app.core import db
'''),
    ("2 redirect after the DB import", "offender", '''
import os
from app.core import db
from app.core import paths
paths.init("/tmp/x")
'''),
    ("3 no redirect at all", "offender", '''
from app.core import db
print(db)
'''),
    ("4 STORAGE_DIR env before the import", "clean", '''
import os
os.environ["STORAGE_DIR"] = "/tmp/x"
from app.core import db
'''),
    ("5 app imports, none of them world-DB", "no-db", '''
from app.core.game_time import GameTime
print(GameTime)
'''),
    ("6 paths import alone does not count", "clean", '''
from app.core import paths
paths.init("/tmp/x")
from app.core import db
'''),
    ("7 deferred import, redirect one line later", "clean", '''
def main():
    tmp = "/tmp/x"
    from app.core import paths, db
    paths.init(tmp)
'''),
    ("8 deferred import, no redirect anywhere", "offender", '''
def main():
    from app.core import db
    print(db)
'''),
    ("9 paths.init only named in a docstring", "offender", '''
"""A check that needs no world, so no paths.init() is needed."""
from app.core import db
print(db)
'''),
    ("10 paths.init() without an argument", "offender", '''
from app.core import paths
paths.init()
from app.core import db
'''),
    ("11 STORAGE_DIR only read, never written", "offender", '''
import os
print(os.environ.get("STORAGE_DIR"))
from app.core import db
'''),
    ("12 os.environ.setdefault writes STORAGE_DIR", "clean", '''
import os
os.environ.setdefault("STORAGE_DIR", "/tmp/x")
from app.core import db
'''),
]


def self_test(db_modules: set) -> None:
    print("1. classifier against hand-written snippets")
    check("app.core.db counts as a world-DB module", "app.core.db" in db_modules)
    check("app.core.paths is NOT a world-DB module",
          "app.core.paths" not in db_modules)
    check("app.core.game_time is NOT a world-DB module",
          "app.core.game_time" not in db_modules)
    for label, expected, src in FIXTURES:
        got = verdict(src, db_modules)[0]
        check(f"{label} -> {expected}", got == expected, got)


# -------------------------------------------------------------------- scan

def scan(db_modules: set):
    """[(name, first db import line, module, redirect line)] for offenders."""
    offenders, candidates = [], 0
    for path in sorted(SCRIPTS.rglob("*.py")):
        if set(path.relative_to(SCRIPTS).parts[:-1]) & SKIPPED_DIRS:
            continue
        if path.name in INTENTIONAL_REAL_WORLD:
            continue
        state, line, mod, where = verdict(
            path.read_text(encoding="utf-8", errors="replace"), db_modules)
        if state == "no-db":
            continue
        candidates += 1
        if state == "offender":
            offenders.append((path.name, line, mod, where))
    return offenders, candidates


# ------------------------------------------------------- paths.py behaviour

NO_DEFAULT_PROBE = """
import app.core.paths as p

# 1. nothing initialised -> the accessor must raise, never resolve
try:
    p.get_storage_dir()
    print("get_storage_dir:NO-RAISE")
except p.StorageNotInitialised as e:
    print("get_storage_dir:RAISE:" + str(e))
except Exception as e:                      # any other type is a failure too
    print("get_storage_dir:WRONG-TYPE:" + type(e).__name__)

# 2. init() with neither argument nor STORAGE_DIR must raise as well
try:
    p.init()
    print("init:NO-RAISE")
except p.StorageNotInitialised:
    print("init:RAISE")
except Exception as e:
    print("init:WRONG-TYPE:" + type(e).__name__)

# 3. the shared/ accessors are repo-relative: they must work WITHOUT storage
try:
    print("shared:" + p.get_shared_dir().name
          + "," + p.get_config_dir().name
          + "," + p.get_animation_clips_dir().name
          + "," + p.get_rig_file().name)
except Exception as e:
    print("shared:RAISED:" + type(e).__name__)
"""

EXPECTED_MESSAGE = ("storage not initialised — call app.core.paths.init(<dir>) "
                    "or set STORAGE_DIR before touching world data")


def paths_has_no_default() -> None:
    """Part 3: paths.py names no world, and an uninitialised read raises.

    Source check first (a literal ``worlds/demo`` in ``init`` is the very bug),
    then the behaviour, measured where it matters: a SUBPROCESS with a clean
    environment — no ``STORAGE_DIR``, nothing this process initialised.
    """
    print("3. app/core/paths.py has no default world")
    src = (REPO / "app" / "core" / "paths.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    init_fn = next((n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "init"), None)
    check("paths.py defines init()", init_fn is not None)
    if init_fn is not None:
        literals = [c.value for c in ast.walk(init_fn)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and "worlds/demo" in c.value]
        check("init() contains no 'worlds/demo' literal", not literals,
              ", ".join(literals))

    # Clean environment: no STORAGE_DIR (the point), and no ANIMATION_* path
    # override either — those legitimately move the shared/ accessors, and a
    # test runner that sets one must not change this verdict.
    env = {k: v for k, v in os.environ.items()
           if k != "STORAGE_DIR" and not k.startswith("ANIMATION_")}
    env["PYTHONPATH"] = str(REPO)
    out = subprocess.run([sys.executable, "-c", NO_DEFAULT_PROBE],
                         capture_output=True, text=True, cwd=str(REPO), env=env)
    lines = dict(line.split(":", 1) for line in out.stdout.splitlines() if ":" in line)
    if out.returncode != 0:
        check("the probe runs", False, out.stderr.strip()[-300:])
        return
    got = lines.get("get_storage_dir", "")
    check("get_storage_dir() raises StorageNotInitialised when uninitialised",
          got.startswith("RAISE"), got)
    check("…with the documented message",
          got == "RAISE:" + EXPECTED_MESSAGE, got)
    check("init() without argument and without STORAGE_DIR raises",
          lines.get("init") == "RAISE", lines.get("init", ""))
    check("the shared/ accessors work without storage",
          lines.get("shared") == "shared,config,clips,reference.fbx",
          lines.get("shared", ""))


def paths_has_no_default_instance() -> None:
    """Part 4: the instance directory follows the same rule as the storage root.

    ``paths.init_instance()`` resolves: explicit argument, else ``INSTANCE_DIR``
    — and nothing else.  The default ``<repo>/instance`` lives in ``start.sh``,
    Docker sets ``/app/instance``; app code names no instance.  Expected
    values, derived by hand from that order:

      a. fresh module, no ``INSTANCE_DIR``  -> ``get_instance_dir()`` raises
         ``InstanceNotInitialised``, ``instance_initialised()`` is False
      b. ``init_instance()`` with neither  -> raises ``InstanceNotInitialised``
      c. ``init_instance(tmp/"a")``        -> ``(tmp/"a").resolve()``, created,
         config path ``(tmp/"a").resolve()/"config.json"``
      d. ``INSTANCE_DIR=tmp/"b"``, no arg  -> ``(tmp/"b").resolve()``
      e. argument AND env                  -> the argument wins

    Measured in-process on a fresh ``importlib.reload(paths)`` (module state
    reset) with ``INSTANCE_DIR`` removed.  Afterwards the environment is
    restored AND the module reloaded once more, so a later in-process part never
    sees ``paths`` pointing at the deleted temp directory.  An exception of the
    WRONG type where a raise is expected is a FAIL line, not a traceback (same
    as part 3's WRONG-TYPE probe).
    """
    import importlib
    import tempfile

    print("4. app/core/paths.py has no default instance")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    saved = os.environ.pop("INSTANCE_DIR", None)

    def expect_raise(label, fn, exc) -> None:
        try:
            fn()
            check(label, False, "no raise")
        except exc:
            check(label, True)
        except Exception as e:              # any other type is a failure too
            check(label, False, "WRONG-TYPE:" + type(e).__name__)

    try:
        import app.core.paths as paths
        paths = importlib.reload(paths)

        exc = getattr(paths, "InstanceNotInitialised", None)
        check("paths defines InstanceNotInitialised(RuntimeError)",
              isinstance(exc, type) and issubclass(exc, RuntimeError))
        if exc is None:
            return

        expect_raise("get_instance_dir() raises when uninitialised",
                     paths.get_instance_dir, exc)
        check("instance_initialised() is False when uninitialised",
              paths.instance_initialised() is False)
        expect_raise("init_instance() without argument and env raises",
                     paths.init_instance, exc)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            want_a = (tmp / "a").resolve()
            got = paths.init_instance(tmp / "a")
            check("init_instance(tmp/a) -> (tmp/a).resolve()", got == want_a, str(got))
            check("…and creates the directory", want_a.is_dir())
            check("get_instance_dir() returns it", paths.get_instance_dir() == want_a)
            check("get_instance_config_path() = <instance>/config.json",
                  paths.get_instance_config_path() == want_a / "config.json",
                  str(paths.get_instance_config_path()))
            check("instance_initialised() is True after init",
                  paths.instance_initialised() is True)

            paths = importlib.reload(paths)
            os.environ["INSTANCE_DIR"] = str(tmp / "b")
            want_b = (tmp / "b").resolve()
            got = paths.init_instance()
            check("INSTANCE_DIR=tmp/b, no argument -> (tmp/b).resolve()",
                  got == want_b, str(got))
            got = paths.init_instance(tmp / "c")
            check("argument beats INSTANCE_DIR", got == (tmp / "c").resolve(), str(got))
    except Exception as e:
        check("part 4 runs", False, f"{type(e).__name__}: {e}")
    finally:
        os.environ.pop("INSTANCE_DIR", None)
        if saved is not None:
            os.environ["INSTANCE_DIR"] = saved
        mod = sys.modules.get("app.core.paths")
        if mod is not None:
            importlib.reload(mod)       # module state no longer names the temp dir


# ------------------------------------------- shared AST helpers (parts 5, 6)

def is_env_key(node, key: str) -> bool:
    """True for the subscript ``os.environ[<key>]`` (or bare ``environ``)."""
    if not isinstance(node, ast.Subscript):
        return False
    if dotted(node.value).split(".")[-1] != "environ":
        return False
    k = node.slice
    return isinstance(k, ast.Constant) and k.value == key


def env_writes(tree, key: str):
    """[(lineno, value expr)] for every WRITE of ``os.environ[<key>]``.

    Assignment, augmented/annotated assignment, or
    ``os.environ.setdefault(<key>, value)`` — the same shapes part 2 accepts
    for STORAGE_DIR.  A read (``.get``) is not a write.
    """
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(is_env_key(t, key) for t in node.targets):
                out.append((node.lineno, node.value))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if is_env_key(node.target, key):
                out.append((node.lineno, node.value))
        elif (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setdefault"
                and dotted(node.func.value).split(".")[-1] == "environ"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == key):
            out.append((node.lineno, node.args[1] if len(node.args) > 1 else None))
    return out


def nested_lines(tree) -> set:
    """Line numbers of every node inside a function or class body."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for inner in ast.walk(node):
                if inner is not node and hasattr(inner, "lineno"):
                    lines.add(inner.lineno)
    return lines


def call_name(node) -> str:
    """Last segment of a call's function name (``paths.init_instance`` -> ``init_instance``)."""
    if not isinstance(node, ast.Call):
        return ""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


TEMP_CALLS = {"mkdtemp", "TemporaryDirectory"}


def is_temp(expr, temp: set) -> bool:
    """True if *expr* contains a temp-dir call or a temp name."""
    if expr is None:
        return False
    for node in ast.walk(expr):
        if call_name(node) in TEMP_CALLS:
            return True
        if isinstance(node, ast.Name) and node.id in temp:
            return True
    return False


def temp_names(tree) -> set:
    """Names EVERY binding of which is a temp-path expression (fixpoint).

    Bindings counted: ``=``, annotated ``=``, ``:=``, augmented ``+=`` etc.,
    ``with X as name``, tuple unpacking and ``for name in …`` (the last two
    have no value per name, so such a name is never temp).  A name's
    references to ITSELF are ignored when judging it (``tmp = Path(tmp)``), but
    at least one binding has to stand on its own.  Scope-blind: one namespace
    for the whole file.
    """
    values: dict = {}

    def bind(target, value):
        if isinstance(target, ast.Name):
            values.setdefault(target.id, []).append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                bind(elt, None)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                bind(t, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            bind(node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            bind(node.target, node.value)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bind(item.optional_vars, item.context_expr)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind(node.target, None)

    temp: set = set()
    changed = True
    while changed:
        changed = False
        for name, vals in values.items():
            if name in temp or any(v is None for v in vals):
                continue
            if (all(is_temp(v, temp | {name}) for v in vals)
                    and any(is_temp(v, temp) for v in vals)):
                temp.add(name)
                changed = True
    return temp


# ---------------------------------------- part 5: app.server importers

def server_imports(tree):
    """[lineno] of every import that loads ``app.server``."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "app.server" or a.name.startswith("app.server.")
                   for a in node.names):
                out.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            mod = node.module or ""
            if mod == "app.server" or mod.startswith("app.server."):
                out.append(node.lineno)
            elif mod == "app" and any(a.name == "server" for a in node.names):
                out.append(node.lineno)
    return sorted(out)


def server_verdict(source: str):
    """('no-server' | 'clean' | 'offender', detail) — see PART 5."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "no-server", ""
    imports = server_imports(tree)
    if not imports:
        return "no-server", ""
    nested = nested_lines(tree)
    problems = []
    for key in ("INSTANCE_DIR", "STORAGE_DIR"):
        writes = [line for line, _ in env_writes(tree, key)]
        for imp in imports:
            if imp in nested:
                ok = bool(writes)          # deferred: runs on the call
            else:
                ok = any(w < imp for w in writes)
            if not ok:
                where = (f"written only on line {min(writes)}" if writes
                         else "never written")
                problems.append(f"imports app.server on line {imp}, {key} {where}")
    return ("offender" if problems else "clean"), "; ".join(problems)


SERVER_FIXTURES = [
    ("a both env vars written, then import app.server", "clean", """
import os, tempfile
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp()
import app.server as server
"""),
    ("b only STORAGE_DIR written", "offender", """
import os, tempfile
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
import app.server
"""),
    ("c INSTANCE_DIR written after the import", "offender", """
import os, tempfile
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
from app.server import app
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp()
"""),
    ("d from app import server, nothing written", "offender", """
from app import server
"""),
    ("e import inside a function, writes later in the file", "clean", """
import os, tempfile
def main():
    import app.server
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp())
os.environ.setdefault("INSTANCE_DIR", tempfile.mkdtemp())
"""),
    ("f paths.init_instance(tmp) is not enough (app.server re-reads the env)",
     "offender", """
import os, tempfile
from app.core import paths
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
paths.init_instance(tempfile.mkdtemp())
import app.server
"""),
    ("g app.server only named in a docstring and a comment", "no-server", '''
"""Never imports app.server."""
# import app.server
from app.core import paths
'''),
    ("h INSTANCE_DIR only read, never written", "offender", """
import os, tempfile
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
print(os.environ.get("INSTANCE_DIR"))
import app.server
"""),
]

BAD_SERVER_FILE = """import os, tempfile
os.environ["STORAGE_DIR"] = tempfile.mkdtemp()
import app.server
"""


def scan_server(root: Path):
    """([(name, detail)] offenders, candidate count) for the scripts under *root*."""
    offenders, candidates = [], 0
    for path in sorted(root.rglob("*.py")):
        if set(path.relative_to(root).parts[:-1]) & SKIPPED_DIRS:
            continue
        state, detail = server_verdict(path.read_text(encoding="utf-8", errors="replace"))
        if state == "no-server":
            continue
        candidates += 1
        if state == "offender":
            offenders.append((path.name, detail))
    return offenders, candidates


def server_importers_set_instance() -> None:
    """Part 5: an ``app.server`` importer writes INSTANCE_DIR + STORAGE_DIR first."""
    import tempfile

    print("5. a script that imports app.server writes INSTANCE_DIR (and STORAGE_DIR) first")
    for label, expected, src in SERVER_FIXTURES:
        got = server_verdict(src)[0]
        check(f"{label} -> {expected}", got == expected, got)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "bad_server_import.py").write_text(BAD_SERVER_FILE, encoding="utf-8")
        (root / "good.py").write_text(SERVER_FIXTURES[0][2], encoding="utf-8")
        offenders, n = scan_server(root)
        check("counter-check: a violating file in a temp dir is caught",
              [o[0] for o in offenders] == ["bad_server_import.py"] and n == 2,
              f"{offenders}, {n} candidate(s)")

    offenders, n = scan_server(SCRIPTS)
    print(f"  {n} script(s) import app.server, "
          f"{len(offenders)} without INSTANCE_DIR/STORAGE_DIR first")
    for name, detail in offenders:
        check(name, False, detail)
    if not offenders:
        print("  OK  every app.server importer writes both env vars before the import")


# -------------------------------------- part 6: real-instance reaches

INSTANCE_READERS = {"get_instance_config_path", "get_instance_dir"}


def instance_verdict(source: str):
    """('none' | 'temp' | 'real', [reason, …]) — see PART 6."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "none", []
    temp = temp_names(tree)
    nested = nested_lines(tree)
    redirects, reads, real = [], [], []
    for node in ast.walk(tree):
        name = call_name(node)
        if name == "init_instance":
            arg = node.args[0] if node.args else next(
                (k.value for k in node.keywords if k.arg == "instance_dir"), None)
            if arg is None:
                real.append((node.lineno, "init_instance() without an argument"))
            elif is_temp(arg, temp):
                redirects.append(node.lineno)
            else:
                real.append((node.lineno, f"init_instance({ast.unparse(arg)})"))
        elif name in INSTANCE_READERS:
            reads.append((node.lineno, name))
    for line, value in env_writes(tree, "INSTANCE_DIR"):
        if is_temp(value, temp):
            redirects.append(line)
        else:
            shown = ast.unparse(value) if value is not None else "?"
            real.append((line, f"INSTANCE_DIR = {shown}"))
    for line, name in reads:
        if line in nested:
            ok = bool(redirects)           # deferred: runs on the call
        else:
            ok = any(r < line for r in redirects)
        if not ok:
            real.append((line, f"{name}() without a temp instance before it"))
    if real:
        return "real", [f"line {ln}: {what}" for ln, what in sorted(real)]
    if redirects or reads:
        return "temp", []
    return "none", []


INSTANCE_FIXTURES = [
    ("1 init_instance(mkdtemp()), then the config path", "temp", """
import tempfile
from app.core import paths
paths.init_instance(tempfile.mkdtemp())
print(paths.get_instance_config_path())
"""),
    ("2 init_instance() without an argument", "real", """
from app.core import paths
paths.init_instance()
"""),
    ("3 init_instance(REPO / 'instance')", "real", """
from pathlib import Path
from app.core import paths
REPO = Path(__file__).resolve().parents[1]
paths.init_instance(REPO / "instance")
"""),
    ("4 init_instance(args.instance) - the CLI shape", "real", """
import argparse
from app.core import paths
args = argparse.ArgumentParser().parse_args()
paths.init_instance(args.instance)
"""),
    ("5 config path read, no init at all", "real", """
from app.core import paths
print(paths.get_instance_config_path())
"""),
    ("6 config path read BEFORE the temp init", "real", """
import tempfile
from app.core import paths
p = paths.get_instance_config_path()
paths.init_instance(tempfile.mkdtemp())
"""),
    ("7 INSTANCE_DIR = str(temp name), then get_instance_dir()", "temp", """
import os, tempfile
from pathlib import Path
from app.core import paths
INST = Path(tempfile.mkdtemp(prefix="x-"))
os.environ["INSTANCE_DIR"] = str(INST)
print(paths.get_instance_dir())
"""),
    ("8 with TemporaryDirectory() as tmp; tmp = Path(tmp); tmp / 'a'", "temp", """
import tempfile
from pathlib import Path
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    paths.init_instance(tmp / "a")
"""),
    ("9 INSTANCE_DIR written with a literal", "real", """
import os
os.environ["INSTANCE_DIR"] = "/srv/anima/instance"
"""),
    ("10 init_instance() only named in a docstring", "none", '''
"""Never calls paths.init_instance() or get_instance_config_path()."""
from app.core import paths
'''),
    ("11 read inside a function, temp init later in the file", "temp", """
import tempfile
from app.core import paths
def show():
    print(paths.get_instance_config_path())
paths.init_instance(tempfile.mkdtemp())
"""),
    ("12 a name bound once temp, once not, is not temp", "real", """
import sys, tempfile
from app.core import paths
d = tempfile.mkdtemp()
d = sys.argv[1]
paths.init_instance(d)
"""),
]

BAD_INSTANCE_FILE = """from pathlib import Path
from app.core import paths
paths.init_instance(Path(__file__).resolve().parents[1] / "instance")
print(paths.get_instance_config_path())
"""


def scan_instance(root: Path, whitelist: dict):
    """(unlisted [(name, reasons)], stale [name], real count) for *root*."""
    unlisted, real_names = [], set()
    for path in sorted(root.rglob("*.py")):
        if set(path.relative_to(root).parts[:-1]) & SKIPPED_DIRS:
            continue
        state, reasons = instance_verdict(
            path.read_text(encoding="utf-8", errors="replace"))
        if state != "real":
            continue
        real_names.add(path.name)
        if path.name not in whitelist:
            unlisted.append((path.name, reasons))
    stale = sorted(n for n in whitelist if n not in real_names)
    return unlisted, stale, len(real_names)


def real_instance_reaches_listed() -> None:
    """Part 6: every reach of the real instance is listed with its reason."""
    import tempfile

    print("6. a script that reaches the REAL instance is listed with a reason")
    for label, expected, src in INSTANCE_FIXTURES:
        got = instance_verdict(src)[0]
        check(f"{label} -> {expected}", got == expected, got)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "bad_real_instance.py").write_text(BAD_INSTANCE_FILE, encoding="utf-8")
        (root / "good.py").write_text(INSTANCE_FIXTURES[0][2], encoding="utf-8")
        (root / "listed.py").write_text(INSTANCE_FIXTURES[1][2], encoding="utf-8")
        unlisted, stale, n = scan_instance(
            root, {"listed.py": "fixture", "gone.py": "fixture"})
        check("counter-check: a violating file in a temp dir is caught",
              [u[0] for u in unlisted] == ["bad_real_instance.py"] and n == 2,
              f"{unlisted}, {n} real")
        check("counter-check: a stale whitelist entry is caught",
              stale == ["gone.py"], str(stale))

    for name, reason in INTENTIONAL_REAL_INSTANCE.items():
        check(f"{name} names a reason", bool(reason and reason.strip()))
    unlisted, stale, n = scan_instance(SCRIPTS, INTENTIONAL_REAL_INSTANCE)
    print(f"  {n} script(s) reach the real instance, "
          f"{len(INTENTIONAL_REAL_INSTANCE)} listed in INTENTIONAL_REAL_INSTANCE")
    for name, reasons in unlisted:
        check(f"{name} is not in INTENTIONAL_REAL_INSTANCE", False, "; ".join(reasons))
    for name in stale:
        check(f"{name} is listed but no longer reaches the real instance", False,
              "remove the entry")
    if not unlisted and not stale:
        print("  OK  every real-instance reach is listed, no stale entry")


def main() -> int:
    db_modules = world_db_modules()
    self_test(db_modules)

    print("2. scripts/ scan")
    offenders, candidates = scan(db_modules)
    print(f"  {candidates} script(s) import a world-DB module, "
          f"{len(INTENTIONAL_REAL_WORLD)} whitelisted, "
          f"{len(offenders)} without a storage redirect")
    for name, line, mod, where in offenders:
        late = f", redirect only on line {where}" if where else ", no redirect"
        FAILURES.append(f"{name}: imports {mod} on line {line}{late}")
        print(f"  FAIL {name} — imports {mod} on line {line}{late}")
    if not offenders:
        print("  OK  every candidate redirects its storage before the import")

    print()
    paths_has_no_default()

    print()
    paths_has_no_default_instance()

    print()
    server_importers_set_instance()

    print()
    real_instance_reaches_listed()

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
