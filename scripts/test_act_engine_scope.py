#!/usr/bin/env python3
"""Static checks for the Act/Storyteller path — the bug classes that stay
invisible until the feature is actually exercised.

Two real outages, both found in task A3.2a, both silent to ``py_compile``
and to a plain server start:

  1. ``NameError`` — a function body referencing a name that only exists in
     the CALLER's scope (commit 4775bc8 moved one line into
     ``_run_storyteller_agent``; every Act failed for a month).
  2. ``ImportError`` — a function-level import of a module that has since
     moved (``routes/characters.py`` kept importing ``app.skills.act_skill``
     after the logic became ``app.core.act_engine``; the route 500'd).

Check 1 is a static AST scope analysis over the act_engine module: for
every top-level function (and its nested defs/lambdas/comprehensions), every
name that is LOADED must be resolvable as one of
  - a parameter of that function or an enclosing one,
  - a name assigned/imported/bound anywhere in that function or an
    enclosing one (assignment, aug/ann-assign, for-target, with-as,
    except-as, import, nested def/class, walrus, comprehension target),
  - a module-level name (global def/class/assignment/import),
  - a builtin.
Anything else is a caller-scope leak — reported as a failure.

Check 2 walks every ``app.skills.*`` import under ``app/`` and ``plugins/``
and asserts the module exists on disk (path resolution only — nothing is
imported, so the DB/config stack stays untouched).

Additionally, ``_run_storyteller_agent`` is called directly with fakes (no
LLM, no DB, no server) to prove its signature is satisfiable from
``perform_act``'s call site and that the indoor/outdoor resolution runs
through to a real setting block.

Usage:
    ./.venv/bin/python scripts/test_act_engine_scope.py

Needs no server, no world.db and no network. Exit code 0 = pass.
"""
import ast
import asyncio
import builtins
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "app" / "core" / "act_engine.py"

# Function whose scope leak caused the outage — checked first and by name so
# a rename does not silently drop the guard.
CRITICAL = "_run_storyteller_agent"

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


# ---------------------------------------------------------------------------
# AST scope analysis
# ---------------------------------------------------------------------------

def _bound_names(node) -> set:
    """All names BOUND inside one function/lambda body (not recursing into
    nested function bodies — those get their own scope, but their *name* is
    bound here)."""
    out = set()

    args = getattr(node, "args", None)
    if args is not None:
        for a in (list(args.posonlyargs) + list(args.args)
                  + list(args.kwonlyargs)):
            out.add(a.arg)
        if args.vararg:
            out.add(args.vararg.arg)
        if args.kwarg:
            out.add(args.kwarg.arg)

    body = node.body if isinstance(node.body, list) else [node.body]

    def visit(n):
        """Record what ``n`` binds, then recurse — except into nested
        function bodies, which are their own scope (their NAME still binds
        here)."""
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            out.add(n.name)
            return
        if isinstance(n, ast.Lambda):
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                out.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        for child in ast.iter_child_nodes(n):
            visit(child)

    for stmt in body:
        visit(stmt)
    return out


def _module_names(tree: ast.Module) -> set:
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    out.add(t.id)
        elif isinstance(node, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
            # module-level conditional definitions/imports
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    out.add(t.id)
                elif isinstance(t, (ast.Import, ast.ImportFrom)):
                    for alias in t.names:
                        out.add((alias.asname or alias.name).split(".")[0])
                elif isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef)):
                    out.add(t.name)
    return out


def _loaded_names(node):
    """(name, lineno) for every Name load in this scope, excluding nested
    function/lambda bodies (they are visited as their own scopes) but
    INCLUDING comprehensions, whose own targets are handled as bound."""
    out = []
    body = node.body if isinstance(node.body, list) else [node.body]

    def visit(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                          ast.ClassDef)):
            # The nested body is its own scope, but DEFAULT values evaluate
            # here, in the enclosing one.
            args = getattr(n, "args", None)
            if args is not None:
                for d in list(args.defaults) + [
                        x for x in (args.kw_defaults or []) if x is not None]:
                    visit(d)
            for d in getattr(n, "decorator_list", []) or []:
                visit(d)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.append((n.id, n.lineno))
        for child in ast.iter_child_nodes(n):
            visit(child)

    for stmt in body:
        visit(stmt)
    return out


def _scopes(node, enclosing: set, results: list):
    """Recursively collect (function_name, leaks) for node and nested defs."""
    own = _bound_names(node) | enclosing
    name = getattr(node, "name", "<lambda>")
    leaks = []
    for ident, lineno in _loaded_names(node):
        if ident in own or ident in BUILTINS:
            continue
        leaks.append((ident, lineno))
    results.append((name, leaks))

    body = node.body if isinstance(node.body, list) else [node.body]

    def visit(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            _scopes(n, own, results)
            return
        if isinstance(n, ast.ClassDef):
            return
        for child in ast.iter_child_nodes(n):
            visit(child)

    for stmt in body:
        visit(stmt)


def check_scopes() -> int:
    tree = ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))
    module = _module_names(tree)
    results = []
    seen_critical = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == CRITICAL:
                seen_critical = True
            _scopes(node, module, results)

    failures = 0
    if not seen_critical:
        print(f"FAIL: function {CRITICAL} not found in {TARGET.name} — "
              f"renamed? update this check.")
        failures += 1

    for fname, leaks in results:
        if leaks:
            failures += 1
            for ident, lineno in leaks:
                print(f"FAIL: {TARGET.name}:{lineno} in {fname}(): "
                      f"name '{ident}' is neither parameter, local, "
                      f"enclosing, module-level nor builtin "
                      f"(caller-scope leak → NameError at runtime)")
    if not failures:
        print(f"PASS: scope check — {len(results)} scopes in "
              f"{TARGET.name}, no caller-scope leaks")
    return failures


# ---------------------------------------------------------------------------
# Direct call of _run_storyteller_agent with fakes (no LLM, no DB, no server)
# ---------------------------------------------------------------------------

def check_call() -> int:
    """Call the real function with a stubbed storyteller config and a stubbed
    LLM router. resolve_llm returning None makes it bail out right after the
    setting/template stage — which is exactly the stretch that used to raise
    NameError. A clean ("", []) means the whole pre-LLM stretch ran."""
    import types
    # Route model3d/clips lookups away from real data if anything touches them.
    os.environ.setdefault("ANIMATION_CLIPS_DIR", "/tmp/av-scope-check-clips")
    sys.path.insert(0, str(REPO))

    from app.core import paths
    paths.init(storage_dir="/tmp/av-scope-check-world")

    from app.core import act_engine

    calls = {}

    # Stub every module boundary the function reaches before the LLM check.
    import app.models.storyteller as st
    st.get_storyteller_config = lambda: {
        "chat_mode": "no_tools", "llm_task": "storyteller",
        "enabled_skills": {}}

    import app.models.character as ch
    ch.get_character_language = lambda n: "en"
    ch.get_character_personality = lambda n: "calm"
    ch.get_character_current_feeling = lambda n: "neutral"

    import app.core.outfit_renderer as orr
    orr.render_outfit = lambda character_name: {"full": "a plain tunic"}

    import app.core.llm_router as lr
    def _no_llm(task, agent_name=None, **kw):
        calls.setdefault("resolve_llm", []).append(task)
        return None
    lr.resolve_llm = _no_llm

    rendered = {}
    import app.core.prompt_templates as pt
    def _render(name, **kw):
        rendered["name"] = name
        rendered["vars"] = kw
        return ("SYS", "USER")
    pt.render_task = _render

    failures = 0

    # Room flag wins over the location's (the whole point of 4775bc8).
    cases = [
        ({"indoor": "indoor"}, {"indoor": "outdoor"}, "Setting: Outdoor"),
        ({"indoor": "indoor"}, None, "Setting: Indoor"),
        ({"indoor": "outdoor"}, {}, "Setting: Outdoor"),
        ({}, None, ""),
    ]
    for location, room, expect in cases:
        rendered.clear()
        out = asyncio.run(act_engine._run_storyteller_agent(
            actor="Demo", scope="here", location_name="Old Mill",
            room_name="Kitchen", location=location, room=room,
            active_events=[{"category": "danger", "text": "a fire"}],
            recipients=["Other"], user_action_text="douses the fire"))
        if out != ("", []):
            print(f"FAIL: expected ('', []) after the no-LLM bail-out, "
                  f"got {out!r}")
            failures += 1
            continue
        block = (rendered.get("vars") or {}).get("setting_block", "<missing>")
        ok = block.startswith(expect) if expect else block == ""
        if not ok:
            print(f"FAIL: location={location} room={room} → "
                  f"setting_block={block!r}, expected prefix {expect!r}")
            failures += 1

    if not failures:
        print(f"PASS: _run_storyteller_agent ran {len(cases)} times with "
              f"fakes — no NameError, room flag overrides the location's")
    return failures


def check_callsite() -> int:
    """perform_act must pass every parameter _run_storyteller_agent declares."""
    tree = ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))
    sig, call = None, None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == CRITICAL:
                a = node.args
                sig = {x.arg for x in
                       list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
                required = set(sig)
                if a.defaults:
                    for x in (list(a.posonlyargs) + list(a.args))[-len(a.defaults):]:
                        required.discard(x.arg)
                for x, d in zip(a.kwonlyargs, a.kw_defaults):
                    if d is not None:
                        required.discard(x.arg)
                sig = required
            if node.name == "perform_act":
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Name)
                            and sub.func.id == CRITICAL):
                        call = {kw.arg for kw in sub.keywords if kw.arg}
                        call |= {f"<positional {i}>"
                                 for i in range(len(sub.args))}
    if sig is None or call is None:
        print("FAIL: could not locate signature or call site")
        return 1
    missing = sig - call
    if missing:
        print(f"FAIL: perform_act does not pass {sorted(missing)} to {CRITICAL}")
        return 1
    print(f"PASS: perform_act passes all {len(sig)} required parameters "
          f"of {CRITICAL}")
    return 0


# ---------------------------------------------------------------------------
# Dead-module imports: from app.skills.<x> import ...  →  does <x> exist?
# ---------------------------------------------------------------------------

SKILLS_PKG = REPO / "app" / "skills"
SCAN_DIRS = ("app", "plugins")


def _module_exists(dotted: str) -> bool:
    """Resolve a dotted module path to a file/package under the repo, without
    importing anything (imports would pull in the DB/config stack)."""
    rel = Path(*dotted.split("."))
    return (REPO / rel).with_suffix(".py").is_file() or (REPO / rel / "__init__.py").is_file()


def check_skill_imports() -> int:
    """Every ``app.skills.<x>`` referenced from an import under app/ or
    plugins/ must exist on disk.

    The Act pipeline was hit by this twice: the logic moved from
    ``app.skills.act_skill`` to ``app.core.act_engine``, and
    ``routes/characters.py`` kept importing the old path. Because the import
    sits INSIDE the request handler and the handler wraps everything in
    ``except Exception``, the dead module surfaced only as an HTTP 500 —
    never as a startup error. Same class as the scope leak: invisible until
    the feature is actually exercised.
    """
    bad = []
    checked = 0
    for top in SCAN_DIRS:
        for path in sorted((REPO / top).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"),
                                 filename=str(path))
            except SyntaxError as e:
                bad.append((path, e.lineno or 0, f"<syntax error: {e.msg}>"))
                continue
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    targets.append(node.module)
                elif isinstance(node, ast.Import):
                    targets.extend(a.name for a in node.names)
                for mod in targets:
                    if not mod.startswith("app.skills."):
                        continue
                    checked += 1
                    if not _module_exists(mod):
                        bad.append((path, node.lineno, mod))

    for path, lineno, mod in bad:
        print(f"FAIL: {path.relative_to(REPO)}:{lineno}: imports '{mod}' — "
              f"module does not exist (moved/renamed? → ImportError at "
              f"call time, not at startup)")
    if not bad:
        print(f"PASS: skill-module imports — {checked} app.skills.* imports "
              f"under {'/, '.join(SCAN_DIRS)}/, all resolve to a real module")
    return len(bad)


def main() -> int:
    failures = check_scopes()
    failures += check_callsite()
    failures += check_skill_imports()
    failures += check_call()
    print("\nRESULT:", "OK" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
