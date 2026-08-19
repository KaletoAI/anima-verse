#!/usr/bin/env python3
"""Guard for two dead LLM calls that were hidden behind try/except.

Usage:
    ./.venv/bin/python scripts/test_dead_llm_calls.py

Runs standalone: no server, no world DB, no network, no real LLM.

Background — the bug this still guards against:

  * ``plugins/knowledge/extract_utils.py`` called
    ``resolve_llm("extraction", character_name=...)``. ``resolve_llm`` has no
    ``character_name`` parameter (it is ``agent_name``), so every call raised
    TypeError and the character routing override never applied.

The second original bug lived in ``app.core.pose_engine.normalize_pose``, which
imported ``call`` instead of ``llm_call`` and then did ``(response or
"").strip()`` on the response OBJECT — both hidden in one ``try/except``, so the
``pose_normalize`` task silently never ran. That function, its LLM task and its
template went first (Aug 2026: poses resolve against the catalog,
plan-pose-katalog.md); the rest of ``pose_engine.py`` followed with the
pose-variant teardown. The four checks that exercised it — formerly 3, 4, 5
and 7 — were dropped with it. Their numbers are deliberately NOT reused, so old
failure output stays unambiguous.

Checks (expected values derived by hand from the code, not recorded from a run):

  1. ``app.core.llm_router`` exports ``llm_call`` and NOT ``call``.
     A later rename must break this check immediately — the original bug was a
     caller importing ``call``, and both names must not coexist.
  2. ``resolve_llm`` accepts ``agent_name`` and not ``character_name``
     (via ``inspect.signature``, not a text search).
  6. Every ``resolve_llm(...)`` call site in ``plugins/knowledge/extract_utils``
     binds against the real signature AND actually passes a character name —
     ``resolve_llm("extraction")`` or ``agent_name=""`` would bind fine and
     still leave the character override dead.
  8. NO ``async def`` under ``app/routes/`` calls into the pose write path
     inline — see the ``_BLOCKING_CALLEES`` note for why that still holds now
     that no LLM sits in the chain. Scanned callees: ``set_pose_intent`` and
     the three one-hop entries ``_extract_activity`` / ``_extract_mood``
     (``chat.py``) and ``execute_cast`` (``spell_engine.py``).
     Plus: the six known sites must KEEP their offload — the absence scan
     alone would also pass if the call were simply deleted.

Why checks 6 and 8 work on the source, not on a live call: the only caller of
``resolve_llm`` here, ``extract_knowledge_from_files``, needs a character
directory, the memory tables and a real folder of files before it ever reaches
``resolve_llm`` — i.e. a world DB; the route handlers need auth dependencies, a
Request body, a taken-over avatar, a group chat and a world DB. Neither can run
here. And "does this block the event loop" is a property of the CALL FORM, not
of any return value: a direct ``set_pose_intent(...)`` inside a coroutine
blocks, ``await asyncio.to_thread(set_pose_intent, ...)`` does not. The AST
decides that exactly, a runtime test could only approximate it with timing.
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Never let a check reach the real animation clips (repo convention).
os.environ.setdefault("ANIMATION_CLIPS_DIR", str(REPO / "scripts" / ".no-clips"))

failures: list[str] = []


def fail(check: str, where: str, msg: str) -> None:
    failures.append(f"[{check}] {where}: {msg}")


def ok(check: str, msg: str) -> None:
    print(f"  ok   {check}: {msg}")


def loc(obj) -> str:
    """'<path>:<line>' of a function/module, for actionable failure output."""
    try:
        f = Path(inspect.getsourcefile(obj)).resolve().relative_to(REPO)
        return f"{f}:{inspect.getsourcelines(obj)[1]}"
    except Exception:
        return getattr(obj, "__name__", "?")


# --- check 8 tables -------------------------------------------------------
# Callees that end in set_pose_intent. Since the pose catalog (Aug 2026) that
# chain no longer reaches an LLM or the provider queue — but the offload
# requirement is unchanged, because set_pose_intent is still fully synchronous:
# it resolves the catalog key (a read, possibly an embedding call) and then
# writes the profile. Those are blocking SQLite writes that additionally
# contend for the world-DB write lock, so calling any of these straight from a
# coroutine still stalls the event loop and with it every SSE stream. The bound
# shrank from "up to 3 x 300 s" to "however long the DB lock is held" —
# shorter, not zero, and an SSE stream must not pay it.
#   set_pose_intent   app/models/character.py  (the chain itself)
#   _extract_activity app/routes/chat.py       -> set_pose_intent
#   _extract_mood     app/routes/chat.py       (same extraction pair)
#   execute_cast      app/core/spell_engine.py -> set_pose_intent
_BLOCKING_CALLEES = {"set_pose_intent", "_extract_activity", "_extract_mood",
                     "execute_cast"}

# Deliberate inline exceptions: {(file, async def name, callee): reason}.
# Empty today — every site under app/routes/ is offloaded. The mechanism
# exists so a future exception is written down WITH a reason instead of the
# check being weakened. (The known inline callers outside app/routes/ —
# thoughts.py, telegram_polling.py — are pre-existing and out of scope: they
# already block on their own LLM call, the pose call only adds to it.)
_ALLOWED_INLINE: dict = {}

# Sites that must keep their offload. The scan above only proves the ABSENCE
# of an inline call — deleting the call entirely would pass it too.
_EXPECTED_OFFLOADS = (
    ("app/routes/play.py", "play_set_activity", "set_pose_intent"),
    ("app/routes/characters.py", "update_character_current_activity", "set_pose_intent"),
    ("app/routes/group_chat.py", "generate", "_extract_activity"),
    ("app/routes/group_chat.py", "generate", "_extract_mood"),
    # The offload moved into the ONE shared cast path behind /play/cast-self
    # and /play/cast (docstring there); the route itself only awaits it.
    ("app/routes/play.py", "_cast_from_inventory", "execute_cast"),
    ("app/routes/inventory.py", "cast_spell_on_self_route", "execute_cast"),
)


def _called_name(node: ast.Call) -> str:
    """Name of the callee — plain `f()` AND attribute `mod.f()`.

    The attribute form used to escape the scan entirely.
    """
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _own_nodes(fn: ast.AST):
    """Nodes that belong to THIS function body, not to a nested one.

    Nested ``def``/``async def``/``lambda`` subtrees are cut off. That does two
    things at once: a nested async generator is judged as its own coroutine
    (ast.walk finds it separately), and the correct
    ``await asyncio.to_thread(lambda: set_pose_intent(...))`` no longer reads
    as an inline call — the call lives inside the lambda, which only runs in
    the worker thread.
    """
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            out.append(child)
            walk(child)

    walk(fn)
    return out


def _is_offload_of(node: ast.AST, callee: str) -> bool:
    """True for ``await …to_thread/run_in_executor(<callee>, …)``.

    Accepts the callee as a bare name, as an attribute (``mod.callee``) and
    wrapped in a lambda.
    """
    if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
        return False
    if _called_name(node.value) not in ("to_thread", "run_in_executor"):
        return False
    for arg in node.value.args:
        if isinstance(arg, ast.Name) and arg.id == callee:
            return True
        if isinstance(arg, ast.Attribute) and arg.attr == callee:
            return True
        if isinstance(arg, ast.Lambda):
            if any(isinstance(n, ast.Call) and _called_name(n) == callee
                   for n in ast.walk(arg)):
                return True
    return False


def _iter_blocking_calls_in_coroutines():
    """Yield (``file:line``, message) for every inline blocking call.

    Scans every ``async def`` under ``app/routes/`` — route handlers and the
    nested SSE generators alike.
    """
    for path in sorted((REPO / "app" / "routes").glob("*.py")):
        rel = path.relative_to(REPO)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            for node in _own_nodes(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node)
                if name not in _BLOCKING_CALLEES:
                    continue
                if (str(rel), fn.name, name) in _ALLOWED_INLINE:
                    continue
                yield (f"{rel}:{node.lineno}",
                       f"async def {fn.name} calls {name}(...) inline — that "
                       f"chain reaches set_pose_intent, whose synchronous "
                       f"profile write blocks on the world-DB write lock and "
                       f"stalls the event loop and every SSE stream; wrap it "
                       f"in await asyncio.to_thread(...)")


def main() -> int:
    print("test_dead_llm_calls")

    # --- 1. llm_router exports llm_call, not call ---------------------------
    import app.core.llm_router as llm_router

    where = str(Path(inspect.getsourcefile(llm_router)).resolve().relative_to(REPO))
    if not callable(getattr(llm_router, "llm_call", None)):
        fail("1", where, "app.core.llm_router has no callable 'llm_call' — "
                         "every 'from app.core.llm_router import llm_call' is dead")
    elif hasattr(llm_router, "call"):
        fail("1", where, "app.core.llm_router unexpectedly exports 'call' — "
                         "the canonical name is 'llm_call'; pick ONE and update "
                         "every caller accordingly")
    else:
        ok("1", "llm_router exports llm_call and no 'call'")

    # --- 2. resolve_llm(task, agent_name=...) ------------------------------
    sig = inspect.signature(llm_router.resolve_llm)
    params = list(sig.parameters)
    if "agent_name" not in params:
        fail("2", loc(llm_router.resolve_llm),
             f"resolve_llm has no 'agent_name' parameter (has {params})")
    elif "character_name" in params:
        fail("2", loc(llm_router.resolve_llm),
             "resolve_llm now also has 'character_name' — two names for the "
             "same thing; callers must be unambiguous")
    else:
        ok("2", f"resolve_llm{sig} takes agent_name, not character_name")

    # Checks 3/4/5/7 lived here. They drove app.core.pose_engine.normalize_pose
    # with a fake llm_call; that function, the pose_normalize task and the whole
    # module no longer exist (see the module docstring). Numbers are not reused.

    # --- 6. extract_utils call sites bind against the real signature -------
    import plugins.knowledge.extract_utils as extract_utils

    src_file = Path(inspect.getsourcefile(extract_utils)).resolve()
    rel = src_file.relative_to(REPO)
    tree = ast.parse(inspect.getsource(extract_utils))
    sites = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and ((isinstance(n.func, ast.Name) and n.func.id == "resolve_llm")
                  or (isinstance(n.func, ast.Attribute) and n.func.attr == "resolve_llm"))]
    if not sites:
        fail("6", str(rel), "no resolve_llm(...) call site found — check outdated")
    for node in sites:
        kw_nodes = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        kwargs = {name: None for name in kw_nodes}
        args = [None] * len(node.args)
        try:
            sig.bind(*args, **kwargs)
        except TypeError as e:
            fail("6", f"{rel}:{node.lineno}",
                 f"resolve_llm(...) does not match resolve_llm{sig}: {e}")
            continue
        # Binding alone is not enough: resolve_llm("extraction") and
        # agent_name="" both bind and both leave the character override dead
        # (llm_router.py:300 only consults the override when agent_name is
        # truthy). Positional beyond the first arg is fine too — arg 2 IS
        # agent_name; only the empty/missing case is a defect.
        supplied = kw_nodes.get("agent_name")
        if supplied is None and len(node.args) >= 2:
            supplied = node.args[1]
        if supplied is None:
            fail("6", f"{rel}:{node.lineno}",
                 "resolve_llm(...) passes no agent_name — the character routing "
                 "override (character_config.llm_routing_overrides) is dead")
        elif isinstance(supplied, ast.Constant) and not str(supplied.value or "").strip():
            fail("6", f"{rel}:{node.lineno}",
                 f"resolve_llm(..., agent_name={supplied.value!r}) is empty — "
                 "the character routing override never fires")
        else:
            shown = (supplied.id if isinstance(supplied, ast.Name)
                     else ast.dump(supplied)[:40])
            ok("6", f"{rel}:{node.lineno} resolve_llm(..., agent_name={shown}) "
                    f"binds to resolve_llm{sig} and carries a character name")

    # --- 8. no coroutine under app/routes/ may block on the pose chain -----
    # Static, per the docstring: blocking-ness is a property of the call form.
    # Scans EVERY `async def` in app/routes/ (route handlers and nested SSE
    # generators alike) instead of a hardcoded handler list — the first version
    # of this check named two handlers and therefore missed the group-chat
    # generator and the two spell routes, which reach set_pose_intent one hop
    # further down.
    _before = len(failures)
    for src, msg in _iter_blocking_calls_in_coroutines():
        fail("8", src, msg)
    if len(failures) == _before:
        ok("8", f"no inline {'/'.join(sorted(_BLOCKING_CALLEES))} call in any "
                f"async def under app/routes/")
    for mod_path, func_name, callee in _EXPECTED_OFFLOADS:
        rel = Path(mod_path)
        mod_tree = ast.parse((REPO / mod_path).read_text(encoding="utf-8"))
        target = next((n for n in ast.walk(mod_tree)
                       if isinstance(n, ast.AsyncFunctionDef) and n.name == func_name), None)
        if target is None:
            fail("8", str(rel),
                 f"async def {func_name} not found — check outdated (renamed? "
                 f"turned into a sync def?)")
            continue
        offloaded = [n for n in ast.walk(target) if _is_offload_of(n, callee)]
        if not offloaded:
            fail("8", f"{rel}:{target.lineno}",
                 f"{func_name} no longer offloads {callee} via an awaited "
                 f"to_thread/run_in_executor — check outdated or the guard was lost")
        else:
            ok("8", f"{rel}:{offloaded[0].lineno} {func_name} offloads "
                    f"{callee} to a thread")

    # --- result -----------------------------------------------------------
    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
