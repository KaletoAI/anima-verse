#!/usr/bin/env python3
"""Guard: a skill package only ever touches PUBLIC core names.

Usage:  ./.venv/bin/python scripts/smoke_plugin_private_imports.py

THE RULE (docs/skill-core-api.md, plan-skill-plugin-architecture.md R1-R7)

A package calls the core, never the other way round — and it calls it through
the curated public surface of ``docs/skill-core-api.md``.  A ``_private_name``
of a core module is not a contract: it can be renamed, re-signatured or
deleted in any core refactor, and the package silently breaks (or, worse,
keeps importing a name whose meaning moved).  Whoever needs such a helper has
it made public first and documented in ``docs/skill-core-api.md``.

Two packages had broken the rule and are what this check was written for:

  * plugins/take_photo/skill.py   -> ``room_entry._list_characters_in_room``
  * plugins/movement/skill_set_location.py -> ``character._record_state_change``

Both names are public now (``characters_in_room`` / ``record_state_change``),
so a clean tree prints zero findings.

WHAT IS SCANNED

Every ``*.py`` under ``plugins/`` — including ``plugins/installed/*``
(marketplace installs) and the three package directories that are SYMLINKS
into the private packs repo (``plugins/attraction``, ``plugins/intimacy``,
``plugins/nsfw_anatomy``).  Symlinks are followed for READING only; hits
inside them are printed under their own heading because the fix belongs in
the other repo — but they still fail the check, so nobody misses them.

WHAT COUNTS AS A HIT

  1. ``from app.<mod> import _x``        — a private symbol imported.
  2. ``from app.<pkg>._mod import x``    — a private MODULE imported from.
  3. ``import app.<pkg>._mod``           — same, as a plain import.
  4. ``room_entry._x(...)`` / ``app.core.room_entry._x`` — a private
     attribute read off anything bound to an ``app.*`` module in this file.

Dunder names (``__init__``, ``__doc__``) are not private in this sense and
are ignored.

The scan is pure AST over the file text: nothing from ``app`` is imported, no
storage is initialised, no world DB and no server are touched.

SELF-TEST

Before scanning the tree the checker parses two inline snippets whose answers
are known by hand: one that uses only public names (must yield 0 findings)
and one with a private import plus a private attribute call (must yield
exactly those 2).  A checker that cannot see the bug it guards against is
worth nothing, so a failing self-test fails the run.
"""
import ast
import sys
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parent.parent
PLUGINS = REPO / "plugins"

_failures: List[str] = []
_checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


def _is_private(name: str) -> bool:
    """A leading underscore, but not a dunder."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _dotted(node: ast.AST) -> str:
    """``a.b.c`` for an Attribute/Name chain, else ''."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def scan_source(src: str, label: str) -> List[Tuple[str, int, str]]:
    """Findings as (label, lineno, what) for one file's source text."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(label, e.lineno or 0, f"syntax error: {e.msg}")]

    out: List[Tuple[str, int, str]] = []
    # Local names bound to an app module — `import app.core.x as y`,
    # `from app.core import room_entry`, `import app.core.x` (root "app").
    app_bound = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if not (mod == "app" or mod.startswith("app.")):
                continue
            for part in mod.split(".")[1:]:
                if _is_private(part):
                    out.append((label, node.lineno, f"from {mod} import … (private module '{part}')"))
                    break
            for alias in node.names:
                bound = alias.asname or alias.name
                app_bound.add(bound)
                if _is_private(alias.name):
                    out.append((label, node.lineno, f"from {mod} import {alias.name}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not (alias.name == "app" or alias.name.startswith("app.")):
                    continue
                app_bound.add(alias.asname or alias.name.split(".")[0])
                for part in alias.name.split(".")[1:]:
                    if _is_private(part):
                        out.append((label, node.lineno, f"import {alias.name} (private module '{part}')"))
                        break

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted(node)
        if not dotted:
            continue
        parts = dotted.split(".")
        if parts[0] not in app_bound and parts[0] != "app":
            continue
        private = [p for p in parts[1:] if _is_private(p)]
        if private:
            out.append((label, node.lineno, f"{dotted} (private '{private[0]}')"))

    # One line per (line, text): ast.walk sees nested Attribute chains twice.
    seen = set()
    uniq = []
    for item in out:
        key = (item[1], item[2])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


PUBLIC_SNIPPET = """
from app.core.room_entry import characters_in_room
from app.models.character import record_state_change, __all__ as _unused
import app.core.perception as perception


def go(name):
    perception.addressable_for(name)
    return characters_in_room("inn", "taproom", exclude=name)
"""

PRIVATE_SNIPPET = """
from app.core.room_entry import _list_characters_in_room
import app.models.character as character


def go(name):
    character._record_state_change(name, "travel_failed", "x")
    return _list_characters_in_room("inn", "taproom")
"""


def _package_files() -> List[Tuple[Path, bool]]:
    """(path, is_external) for every .py under plugins/, symlinks followed.

    External = a package directory that is a symlink (the private packs) or
    lives under plugins/installed (marketplace install): its fix belongs to
    another repo, so it is reported separately.
    """
    files: List[Tuple[Path, bool]] = []
    if not PLUGINS.is_dir():
        return files
    for entry in sorted(PLUGINS.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "installed":
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    files += [(p, True) for p in sorted(sub.rglob("*.py"))]
            continue
        external = entry.is_symlink()
        files += [(p, external) for p in sorted(entry.rglob("*.py"))]
    return [(p, ext) for p, ext in files if "__pycache__" not in p.parts]


def main() -> int:
    print("0) self-test: the checker sees a private import")
    pub = scan_source(PUBLIC_SNIPPET, "<public snippet>")
    check("public-only snippet -> 0 findings", not pub, "; ".join(f[2] for f in pub))
    priv = scan_source(PRIVATE_SNIPPET, "<private snippet>")
    priv_texts = sorted(f[2] for f in priv)
    check("private snippet -> exactly the 2 known findings",
          priv_texts == ["character._record_state_change (private '_record_state_change')",
                         "from app.core.room_entry import _list_characters_in_room"],
          repr(priv_texts))

    files = _package_files()
    own = [(p, e) for p, e in files if not e]
    ext = [(p, e) for p, e in files if e]
    print(f"\n1) scanning {len(own)} .py files in this repo's packages "
          f"and {len(ext)} in external/symlinked packages")

    own_hits: List[Tuple[str, int, str]] = []
    ext_hits: List[Tuple[str, int, str]] = []
    for path, external in files:
        try:
            src = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"  (unreadable: {path}: {e})")
            continue
        rel = str(path.relative_to(REPO)) if REPO in path.parents else str(path)
        hits = scan_source(src, rel)
        (ext_hits if external else own_hits).extend(hits)

    if own_hits:
        print("\n  Private core names used by this repo's packages:")
        for label, line, what in own_hits:
            print(f"    {label}:{line}: {what}")
    check("no package in this repo imports a private core name", not own_hits,
          f"{len(own_hits)} hit(s)")

    if ext_hits:
        print("\n  EXTERNAL PACKAGES (private packs / marketplace installs) — "
              "fix belongs to the other repo:")
        for label, line, what in ext_hits:
            print(f"    {label}:{line}: {what}")
    check("no external package imports a private core name", not ext_hits,
          f"{len(ext_hits)} hit(s)")

    print()
    print(f"{_checks - len(_failures)}/{_checks} checks passed")
    if _failures:
        for f in _failures:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
