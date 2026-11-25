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
"""
import asyncio
import sys
import threading
import time
import traceback

from app.core.log import get_logger

logger = get_logger("event_loop_watchdog")

_heartbeat: float = 0.0
_asyncio_task: asyncio.Task = None
_thread: threading.Thread = None
_stop_event = threading.Event()

#: A stall of this length is counted in the loop guard's report line.
LAG_NOTE_MS = 200.0


async def _heartbeat_loop(tick: float) -> None:
    global _heartbeat
    while True:
        _heartbeat = time.monotonic()
        try:
            await asyncio.sleep(tick)
        except asyncio.CancelledError:
            return


def _format_all_threads() -> str:
    """Format the stacks of all threads for the log."""
    frames = sys._current_frames()
    out = []
    for th in threading.enumerate():
        frame = frames.get(th.ident)
        if frame is None:
            continue
        out.append(f"--- Thread {th.name!r} (id={th.ident}, daemon={th.daemon}) ---")
        out.append("".join(traceback.format_stack(frame)))
    return "\n".join(out)


def _watchdog_thread(threshold_ms: float, check_interval: float) -> None:
    """OS thread: checks the heartbeat and dumps when the event loop is blocked."""
    from app.core import loop_guard
    threshold_s = threshold_ms / 1000.0
    already_dumped = False
    lag_noted = False
    block_started_at = 0.0
    logger.info("Watchdog-Thread aktiv (check=%.0fms, threshold=%.0fms)",
                check_interval * 1000, threshold_ms)
    while not _stop_event.is_set():
        time.sleep(check_interval)
        if _heartbeat == 0.0:
            continue
        lag = time.monotonic() - _heartbeat
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
                block_started_at = _heartbeat
                already_dumped = True
                stacks = _format_all_threads()
                logger.warning(
                    "Event-Loop blockiert seit %.0fms — Thread-Stacks:\n%s",
                    lag * 1000, stacks)
        else:
            if already_dumped:
                total_block = time.monotonic() - block_started_at
                logger.warning(
                    "Event-Loop wieder frei nach %.0fms Block", total_block * 1000)
            already_dumped = False
    logger.info("Watchdog-Thread beendet")


def start(tick: float = 0.1, threshold_ms: float = 1000.0,
          check_interval: float = 0.2) -> None:
    global _asyncio_task, _thread, _heartbeat
    if _asyncio_task and not _asyncio_task.done():
        return
    _stop_event.clear()
    _heartbeat = time.monotonic()
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
