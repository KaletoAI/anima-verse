"""Lint: an async route handler must await something.

A route handler declared `async def` runs directly on the event loop.  If its
body never awaits (no `await`, `async for` or `async with`), every line of it
is synchronous work on the loop thread -- a world-DB read there blocks every
other request.  Such a handler must be a plain `def` (FastAPI then runs it in
the threadpool) or, when it needs the running loop, stay async and move its
blocking work into `asyncio.to_thread` (which is an await).

Scanned: every `app/routes/*.py`, AST only, no import of app code.  A handler
is a function decorated with `<x>.get/post/put/patch/delete/api_route`
(`<x>.websocket` is excluded: a websocket handler is async by contract).
Awaits inside nested functions/lambdas/classes do not count for the handler.

Self-test (runs first, fails loudly if the checker itself is broken):
  good sample: an async handler with one `await` and an async handler whose
               only await is an `async with`  -> 0 findings
  bad sample:  an async handler with no await, plus an async handler whose
               only await sits in a nested `async def` -> 2 findings
               (lines 3 and 7 of the sample, derived by counting the sample)
  websocket:   an async `@router.websocket` handler without await -> 0 findings

Usage:
    ./.venv/bin/python scripts/smoke_async_routes_lint.py
Exit 0 = clean, 1 = findings (printed as file:line:name).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ROOT / "app" / "routes"
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "api_route"}

# Handlers that stay `async def` without an await of their own, each with its
# reason. An entry that no longer names an await-free async handler fails the
# check too, so the list cannot go stale.
INTENTIONAL_ASYNC = {
    # SSE: the handler only checks the session and hands a nested async
    # generator to StreamingResponse; the generator subscribes on the loop
    # (state_events.subscribe calls asyncio.get_running_loop()).
    "app/routes/events.py:event_image_stream",
    "app/routes/events.py:outfit_event_stream",
    "app/routes/events.py:state_event_stream",
}


def _is_route(fn) -> bool:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in HTTP_VERBS:
            return True
    return False


def _awaits(node) -> bool:
    """True when node's OWN body awaits; nested scopes are not descended."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            return True
        # Async comprehensions (`async for` inside a comprehension).
        if isinstance(child, ast.comprehension) and child.is_async:
            return True
        if _awaits(child):
            return True
    return False


def scan_source(src: str, filename: str) -> list[str]:
    tree = ast.parse(src, filename)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and _is_route(node):
            if not _awaits(node):
                out.append(f"{filename}:{node.lineno}:{node.name}")
    return out


_GOOD = '''
@router.get("/a")
async def a():
    return await thing()

@router.post("/b")
async def b():
    async with lock:
        return 1
'''

_BAD = '''
@router.get("/a")
async def a():
    return read_db()

@router.put("/b")
async def b():
    async def inner():
        await thing()
    return inner
'''

_WS = '''
@router.websocket("/ws")
async def ws(sock):
    return None
'''


def _self_test() -> None:
    good = scan_source(_GOOD, "good")
    bad = scan_source(_BAD, "bad")
    ws = scan_source(_WS, "ws")
    assert good == [], good
    assert bad == ["bad:3:a", "bad:7:b"], bad
    assert ws == [], ws
    print("self-test ok: good=0 bad=2 websocket=0")


def main() -> int:
    _self_test()
    raw = []
    for path in sorted(ROUTES.glob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        raw += scan_source(path.read_text(encoding="utf-8"), rel)
    seen = set()
    findings = []
    for f in raw:
        file_, _line, name = f.split(":")
        key = f"{file_}:{name}"
        if key in INTENTIONAL_ASYNC:
            seen.add(key)
        else:
            findings.append(f)
    for key in sorted(INTENTIONAL_ASYNC - seen):
        findings.append(f"{key}: stale INTENTIONAL_ASYNC entry (no await-free async handler)")
    for f in findings:
        print(f)
    if findings:
        print(f"FAIL: {len(findings)} async route handler(s) without await")
        return 1
    print("OK: every async route handler awaits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
