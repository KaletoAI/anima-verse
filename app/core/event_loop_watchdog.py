"""Event-loop watchdog with a stack dump while the block lasts.

Two parts:
1. An asyncio task refreshes a heartbeat stamp every `tick` seconds.
2. A separate OS thread checks how old the heartbeat is. Once the event loop
   has not answered for longer than the threshold it dumps the frames of all
   threads — including the main thread with the call that blocks right now,
   so the blocker is seen live and not only after it is over.

Below the dump threshold, a lag of `LAG_NOTE_MS` is noted once per stall in
the loop guard's per-minute line (``lag:<entry>><leaf>``) — one frame walk of
the loop thread, no dump.

The reported block length runs from the last heartbeat before the block to
the FIRST heartbeat after it (recorded by the heartbeat task itself), not to
the watchdog's next check, which can come up to one check interval later.
In the dump, a pool thread that only waits for work takes one line; every
thread with an application frame keeps its full stack.
"""
import asyncio
import sys
import threading
import time
import traceback

from app.core.log import get_logger

logger = get_logger("event_loop_watchdog")

_heartbeat: float = 0.0
#: (last beat before, first beat after) the most recent gap of at least
#: LAG_NOTE_MS — written by the heartbeat task when the loop comes back.
_last_gap: tuple = (0.0, 0.0)
_asyncio_task: asyncio.Task = None
_thread: threading.Thread = None
_stop_event = threading.Event()

#: A stall of this length is counted in the loop guard's report line.
LAG_NOTE_MS = 200.0


async def _heartbeat_loop(tick: float) -> None:
    global _heartbeat, _last_gap
    while True:
        now = time.monotonic()
        if _heartbeat and (now - _heartbeat) * 1000.0 >= LAG_NOTE_MS:
            _last_gap = (_heartbeat, now)
        _heartbeat = now
        try:
            await asyncio.sleep(tick)
        except asyncio.CancelledError:
            return


#: Innermost frames of a thread that only waits for work: (path suffix,
#: function). A pool worker blocked in SimpleQueue.get (C code) shows its
#: ``_worker`` frame; a queue.Queue / Condition waiter shows threading's wait.
_IDLE_FRAMES = (("concurrent/futures/thread.py", "_worker"),
                ("/queue.py", "get"),
                ("/threading.py", "wait"))


def _is_app_frame(filename: str) -> bool:
    return "/app/" in filename or "/plugins/" in filename


def _idle_line(frame) -> str:
    """``file:line func`` when the thread is an idle waiter without any
    application frame on its stack, else empty."""
    code = frame.f_code
    if not any(code.co_filename.endswith(path) and code.co_name == name
               for path, name in _IDLE_FRAMES):
        return ""
    walk = frame
    while walk is not None:
        if _is_app_frame(walk.f_code.co_filename):
            return ""
        walk = walk.f_back
    return f"{code.co_filename}:{frame.f_lineno} {code.co_name}"


def _format_all_threads() -> str:
    """Format the stacks of all threads for the log; idle waiters in one line."""
    frames = sys._current_frames()
    out = []
    for th in threading.enumerate():
        frame = frames.get(th.ident)
        if frame is None:
            continue
        head = f"--- Thread {th.name!r} (id={th.ident}, daemon={th.daemon})"
        idle = _idle_line(frame)
        if idle:
            out.append(f"{head} idle: {idle}")
            continue
        out.append(head + " ---")
        out.append("".join(traceback.format_stack(frame)))
    return "\n".join(out)


def _watchdog_thread(threshold_ms: float, check_interval: float) -> None:
    """OS thread: checks the heartbeat and dumps when the event loop is blocked."""
    from app.core import loop_guard
    threshold_s = threshold_ms / 1000.0
    already_dumped = False
    lag_noted = False
    block_started_at = 0.0
    logger.info("Watchdog thread active (check=%.0fms, threshold=%.0fms)",
                check_interval * 1000, threshold_ms)
    while not _stop_event.is_set():
        time.sleep(check_interval)
        if _heartbeat == 0.0:
            continue
        # Read the heartbeat ONCE: the loop may beat between two reads, and the
        # block start must be the beat this lag was measured from.
        beat = _heartbeat
        lag = time.monotonic() - beat
        # Catch-all below the dump threshold: once per stall, name what the
        # loop thread is doing — a lock, a file, a wait for the GIL.
        if lag * 1000.0 >= LAG_NOTE_MS:
            if not lag_noted:
                lag_noted = True
                try:
                    tid = loop_guard.server_loop_tid()
                    if tid is not None:
                        loop_guard.note_lag(sys._current_frames().get(tid), lag * 1000.0)
                except Exception:
                    pass
        else:
            lag_noted = False
        loop_guard.report_if_due()
        if lag >= threshold_s:
            if not already_dumped:
                block_started_at = beat
                already_dumped = True
                stacks = _format_all_threads()
                logger.warning(
                    "Event loop blocked for %.0fms — thread stacks:\n%s",
                    lag * 1000, stacks)
        else:
            if already_dumped:
                gap_start, gap_end = _last_gap
                # The heartbeat task recorded the first beat after the block;
                # without that record, the latest beat is the best bound.
                end = gap_end if gap_start == block_started_at else _heartbeat
                logger.warning(
                    "Event loop free again after %.0fms block",
                    (end - block_started_at) * 1000)
            already_dumped = False
    logger.info("Watchdog thread stopped")


def start(tick: float = 0.1, threshold_ms: float = 1000.0,
          check_interval: float = 0.2) -> None:
    global _asyncio_task, _thread, _heartbeat, _last_gap
    if _asyncio_task and not _asyncio_task.done():
        return
    _stop_event.clear()
    _heartbeat = time.monotonic()
    _last_gap = (0.0, 0.0)
    _asyncio_task = asyncio.create_task(_heartbeat_loop(tick))
    _thread = threading.Thread(
        target=_watchdog_thread,
        args=(threshold_ms, check_interval),
        name="EventLoopWatchdog",
        daemon=True)
    _thread.start()


def stop() -> None:
    global _asyncio_task, _thread
    _stop_event.set()
    if _asyncio_task and not _asyncio_task.done():
        _asyncio_task.cancel()
    _asyncio_task = None
    _thread = None
