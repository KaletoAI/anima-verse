#!/usr/bin/env python3
"""Smoke run: a chat background task is HELD, expires, and the image display
URL of a chat message points at a route that exists.

Usage:
    ./.venv/bin/python scripts/smoke_chat_task_lifecycle.py

Runs WITHOUT the server, without a world DB and without a network: the
storage root is a temp dir, ``ChatTaskManager`` is pure asyncio and the URL
part reads app/routes/chat.py as TEXT (importing it would pull in FastAPI
dependencies and the whole route stack for a one-line question).

The findings under test (review 2026-09-20)
---------------------------------------------------------------------------
LLM-10 ``asyncio.create_task(mgr.feed_from_generator(...))`` threw the task
       away. The event loop keeps only a weak reference to a running task, so
       the feed could be collected mid-turn: the stream stops silently and the
       browser polls ``subscribe`` forever, because ``task.status`` never
       becomes done/error. And ``cleanup_old_tasks`` only ever removed
       done/error entries — an entry stuck in pending/running kept its
       ChatTask and its whole buffer for the lifetime of the process.
DE-23  ``app/routes/chat.py`` built ``f"/chat/upload-image/{image_id}"`` while
       the serving route is ``/chat/{user_id}/upload-image/{image_id}`` — a
       three-segment path that matches nothing and renders as a broken image.
       The shared helper a few hundred lines earlier had it right all along.

Expected values, derived by hand from the two sources
---------------------------------------------------------------------------
* ``start_feed`` returns the asyncio task AND stores it on the ChatTask, so
  ``mgr.get_task(tid).runner`` is that very object. A bare create_task would
  leave ``runner`` None.
* A finished entry younger than ``TASK_TTL_S`` survives a cleanup; the same
  entry aged past it is removed. Unchanged behaviour, kept under the new code.
* An entry that is still ``running`` survives while it is younger than
  ``STUCK_TTL_S`` (= 3 x TASK_TTL_S = 1800 s) and is removed once it is older
  — the old code kept it forever. A live runner of such an entry is cancelled
  (``runner.cancelled()`` after the loop has had a turn).
* ``resolve_chat_image`` is the ONE resolver, and every ``/chat/...``
  upload-image URL literal in app/routes/chat.py must have FOUR path segments
  — chat, <user segment>, upload-image, <id> — matching the declared route
  ``@router.get("/{user_id}/upload-image/{image_id}")`` under the ``/chat``
  prefix. Three segments is the bug.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_TMP = Path(tempfile.mkdtemp(prefix="smoke_chat_task_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(_TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(_TMP)

from app.core import chat_task_manager as ctm  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")
        failures.append(label)


async def _part_runner() -> None:
    print("\nLLM-10 a) the feed task is held by the manager")
    mgr = ctm.ChatTaskManager()
    tid = mgr.create_task(user_id="u")

    async def gen():
        yield "data: one\n\n"
        yield "data: two\n\n"

    runner = mgr.start_feed(tid, gen())
    check("start_feed returns an asyncio task", isinstance(runner, asyncio.Task))
    entry = mgr.get_task(tid)
    check("the task is stored on the ChatTask (strong reference)",
          entry is not None and entry.runner is runner,
          repr(getattr(entry, "runner", "no attribute")))
    await runner
    check("the feed drained the generator and finished",
          entry.status == "done" and len(entry.buffer) == 2,
          f"{entry.status} buffer={len(entry.buffer)}")

    check("start_feed on an unknown id returns None and creates nothing",
          mgr.start_feed("nope", gen()) is None)


async def _part_cleanup() -> None:
    print("\nLLM-10 b) a stuck entry expires instead of living forever")
    mgr = ctm.ChatTaskManager()

    # 1) a finished entry, young -> stays; aged -> goes.
    fin = mgr.create_task()
    mgr.get_task(fin).status = "done"
    check("a fresh finished entry survives the cleanup",
          mgr.cleanup_old_tasks() == 0 and mgr.get_task(fin) is not None)
    mgr.get_task(fin).created_at -= ctm.TASK_TTL_S + 1
    check("a finished entry older than TASK_TTL_S is removed",
          mgr.cleanup_old_tasks() == 1 and mgr.get_task(fin) is None)

    # 2) a hanging entry: its generator never ends.
    stuck = mgr.create_task()
    never = asyncio.Event()

    async def hang():
        await never.wait()
        yield "data: never\n\n"

    runner = mgr.start_feed(stuck, hang())
    await asyncio.sleep(0)  # let the feed start and set status "running"
    entry = mgr.get_task(stuck)
    check("the hanging feed is 'running'", entry.status == "running", entry.status)
    check("younger than STUCK_TTL_S it is kept",
          mgr.cleanup_old_tasks() == 0 and mgr.get_task(stuck) is not None)

    entry.created_at -= ctm.STUCK_TTL_S + 1
    check("older than STUCK_TTL_S it is removed",
          mgr.cleanup_old_tasks() == 1 and mgr.get_task(stuck) is None)
    for _ in range(5):  # give the loop a turn to deliver the cancellation
        await asyncio.sleep(0)
    check("its runner was cancelled", runner.cancelled() or runner.done(),
          f"done={runner.done()} cancelled={runner.cancelled()}")
    check("STUCK_TTL_S is three TTLs (1800 s)",
          ctm.STUCK_TTL_S == ctm.TASK_TTL_S * 3 == 1800,
          f"{ctm.STUCK_TTL_S} / {ctm.TASK_TTL_S}")


def _part_url() -> None:
    print("\nDE-23 — the upload-image display URL has all four segments")
    src = (REPO / "app" / "routes" / "chat.py").read_text(encoding="utf-8")

    check("the serving route is declared as /{user_id}/upload-image/{image_id}",
          '"/{user_id}/upload-image/{image_id}"' in src)

    urls = re.findall(r'["\']/chat/[^"\']*upload-image[^"\']*["\']', src)
    check("at least one display URL literal is built here", bool(urls),
          "none found — has the helper moved?")
    bad = [u for u in urls if len(u.strip('"\'').strip("/").split("/")) != 4]
    check(f"all {len(urls)} of them have four segments", not bad, ", ".join(bad))

    # And no second, hand-written resolution of an upload path is left over.
    check("the route body uses the shared resolver",
          "resolve_chat_image(image_id, image_url)" in src)


async def _main_async() -> None:
    await _part_runner()
    await _part_cleanup()


def main() -> int:
    print("smoke_chat_task_lifecycle")
    try:
        if hasattr(ctm.ChatTaskManager, "start_feed"):
            asyncio.run(_main_async())
        else:
            check("ChatTaskManager has start_feed (the held-reference entry "
                  "point)", False,
                  "the routes still call asyncio.create_task() directly")
        _part_url()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)

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
