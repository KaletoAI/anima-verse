#!/usr/bin/env python3
"""Every ``from app…/plugins… import name`` must name something that exists.

Usage:
    ./.venv/bin/python scripts/smoke_imports_resolve.py

No server, no world DB, nothing is imported: the check is a pure AST scan over
``app/``, ``plugins/`` (symlinked private packs included), ``scripts/`` and
``queue_cli.py``. ``scripts/legacy/`` is skipped, as is every
``__pycache__``/``node_modules``.

Why this exists (review 2026-09-20, KOORD-1): four lazy imports inside
``try:`` blocks pointed at names that had moved or were gone, and the
``except`` swallowed the ImportError. The features behind them — timed
intents, the outfit-mismatch notification and two template previews — simply
never ran, without a single line in the log. An import that lives inside a
function is never executed by a syntax check, so only a scan like this one
finds it.

What counts as broken:
  - ``from <app|plugins>.<module> import X`` where the module file exists but
    defines no ``X`` at module level and there is no submodule ``X``
  - an ``import``/``from`` of an ``app.``/``plugins.`` module that does not
    exist at all

Deliberately not flagged: a module with ``import *`` or a module-level
``__getattr__`` (its names cannot be determined statically), and relative
imports.

Self-test: before scanning the repo the script builds a throwaway package with
one good and one broken import and asserts that the scanner finds exactly the
broken one — so a green run means the detector works, not that it looked away.
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = ["app", "plugins", "scripts", "queue_cli.py",
         "../anima-verse-packs/packs"]
SKIP_DIRS = {"__pycache__", "node_modules", "legacy", ".git", "node_modules"}
PACKAGES = ("app", "plugins")


def py_files(base: Path, roots):
    for r in roots:
        p = (base / r)
        if p.is_file():
            yield p
            continue
        if not p.exists():
            continue        # the private packs are not checked out everywhere
        for dirpath, dirnames, filenames in os.walk(p, followlinks=True):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                if f.endswith(".py"):
                    yield Path(dirpath) / f


def module_path(base: Path, module: str):
    """Source file (or package dir) of a dotted module name, or None."""
    p = base / module.replace(".", "/")
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    if (p / "__init__.py").is_file():
        return p / "__init__.py"
    if p.is_dir():
        return p
    return None


_names_cache = {}


def module_names(path: Path):
    """(top-level names, opaque?) of a module. opaque = we cannot know."""
    key = str(path)
    if key in _names_cache:
        return _names_cache[key]
    found = set()
    opaque = False
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        _names_cache[key] = (set(), True)
        return _names_cache[key]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        found.add(sub.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name):
                found.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    opaque = True
                found.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.asname or alias.name).split(".")[0])
    if "__getattr__" in found:
        opaque = True
    _names_cache[key] = (found, opaque)
    return _names_cache[key]


def scan(base: Path, roots):
    """Returns [(file, line, module, name)] for every unresolved import."""
    bad = []
    for f in py_files(base, roots):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append((f, 0, str(f), f"<unparseable: {e}>"))
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.level == 0
                    and node.module
                    and node.module.split(".")[0] in PACKAGES):
                mp = module_path(base, node.module)
                if mp is None:
                    bad.append((f, node.lineno, node.module, "<module missing>"))
                    continue
                if mp.is_dir():
                    continue
                names, opaque = module_names(mp)
                if opaque:
                    continue
                for alias in node.names:
                    if alias.name == "*" or alias.name in names:
                        continue
                    if module_path(base, f"{node.module}.{alias.name}"):
                        continue        # it is a submodule
                    bad.append((f, node.lineno, node.module, alias.name))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if (alias.name.split(".")[0] in PACKAGES
                            and not module_path(base, alias.name)):
                        bad.append((f, node.lineno, alias.name,
                                    "<module missing>"))
    return bad


def self_test() -> bool:
    """The detector must find a planted break and leave a good import alone."""
    with tempfile.TemporaryDirectory(prefix="imports-selftest-") as tmp:
        base = Path(tmp)
        pkg = base / "app"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "home.py").write_text("def present():\n    return 1\n",
                                     encoding="utf-8")
        (pkg / "user.py").write_text(
            "from app.home import present\n"
            "from app.home import gone\n"
            "from app.nowhere import anything\n", encoding="utf-8")
        hits = {(m, n) for _f, _l, m, n in scan(base, ["app"])}
    expected = {("app.home", "gone"), ("app.nowhere", "<module missing>")}
    if hits != expected:
        print(f"  FAIL self-test: found {sorted(hits)}, expected "
              f"{sorted(expected)}")
        return False
    print("  ok   self-test: a broken import is detected, a good one is not")
    return True


ok = self_test()

bad = scan(REPO, ROOTS)
for f, line, module, name in bad:
    try:
        shown = Path(f).relative_to(REPO)
    except ValueError:
        shown = f
    print(f"  {shown}:{line}  from {module} import {name}")

print()
if not ok or bad:
    print(f"FAILED — {len(bad)} unresolved import(s)")
    sys.exit(1)
print("OK — every app/plugins import resolves to an existing name")
