"""Build all open — one click for every character's open 3D work (character list, Game-Admin).

For every character of the roster with open work, the runner first clears its BASE (plain) body and then builds
its OUTFIT (the figure Build), strictly in that order per character; at most ``MAX_PARALLEL`` characters run at
the same time. It reuses exactly what the per-character buttons call, never this server's HTTP API:

* base phase — the Base body tab's "Run all" (``figure_build.start_base_run_all``), once per kind until it
  answers ``current``: the plain body, a face cleanup / retexture, the mesh repair, the tip smoothing, the
  extension rig and the collision channels. Each kind is waited for (``figure_build.base_step_in_flight``)
  before the next is asked for. A kind that is still planned right after it ran did not succeed — the base
  phase ends there with that reason. A failed PLAIN body (its own ``last.error``, a refused side view among
  them) is blocking: the outfit would be built on a base that is not there, so the character's outfit is
  skipped. Any other base failure is recorded and the outfit is still built.
* outfit phase — the Figure tab's Build (``figure_build.start``, a manual one: it also runs a base step a
  manual Build plans), waited for while it runs (``figure_build.running``); its recorded ``failed`` steps are
  the phase's failure.

Who is a candidate: the character list's own badges (``figure_build.open_steps``: a base or outfit step open, or
a Build running) plus a character whose Run all has a kind due (face / extension work the badges do not count).
The GPU side stays the queues' job: hub work is serialised per backend channel (``run_on_backend_channel``),
the cap of three only bounds how many characters' pipelines advance at once.

Background, server-side (survives a closed browser). A second start while one runs is refused; ``cancel`` stops
scheduling characters that have not begun (the ones running finish). The media master switch is checked at the
start and before each character. Every phase change pushes the admin-only topic ``generation`` (the list's
badges reload on it).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("figure_batch")

#: How many characters run at the same time (user request 2026-11-20).
MAX_PARALLEL = 3
#: How often a waiting character looks again whether its step ended (seconds).
POLL_S = 3.0
#: The longest one phase of one character may wait for its steps (a Build of many pieces takes long).
PHASE_MAX_S = 6 * 3600.0
#: Run all answers one kind per call; more rounds than kinds means it does not settle.
MAX_BASE_ROUNDS = 10

PHASE_WAITING, PHASE_BASE, PHASE_OUTFIT = "waiting", "base", "outfit"
PHASE_DONE, PHASE_FAILED, PHASE_SKIPPED = "done", "failed", "skipped"

MEDIA_OFF = "Media generation is switched off"
ALREADY_RUNNING = "Build all open runs already"
CANCELLED = "Cancelled before it started"
OFF_PIPELINE = "Not on the base-body pipeline"
TIMED_OUT = "Waited too long for {what} — left open"
BASE_STILL_DUE = "Base body: {kind} is still due after it ran"
BASE_NOT_SETTLED = "Base body: Run all did not settle"
BASE_FAILED = "Base body failed: {error}"
OUTFIT_SKIPPED = "Outfit skipped — the base body failed"

_lock = threading.Lock()
_state: Dict[str, Any] = {"running": False, "collecting": False, "cancel": False, "started_at": None,
                          "finished_at": None, "order": [], "characters": {}}


def _notify() -> None:
    """The admin-only topic ``generation`` — the character list reloads its badges on it (a topic, never data)."""
    try:
        from app.core import figure_build
        figure_build._notify_build_changed()
    except Exception:  # noqa: BLE001 — a push never breaks the batch
        logger.debug("Build all open: push failed", exc_info=True)


def _media_on() -> bool:
    from app.imagegen.base import media_generation_enabled
    return bool(media_generation_enabled())


def _set(name: str, phase: str, reason: str = "", **extra: Any) -> None:
    with _lock:
        row = _state["characters"].setdefault(name, {})
        row.update({"phase": phase, "reason": reason, **extra})
    _notify()


def _cancelled() -> bool:
    with _lock:
        return bool(_state["cancel"])


def status() -> Dict[str, Any]:
    """``{running, collecting, cancel, started_at, finished_at, characters: [{name, phase, reason}], counts:
    {phase: n}, total}`` — the last (or current) run, in roster order. Read-only."""
    with _lock:
        rows = [{"name": n, **dict(_state["characters"].get(n) or {})} for n in _state["order"]]
        out = {k: _state[k] for k in ("running", "collecting", "cancel", "started_at", "finished_at")}
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row.get("phase") or PHASE_WAITING] = counts.get(row.get("phase") or PHASE_WAITING, 0) + 1
    return {**out, "characters": rows, "counts": counts, "total": len(rows)}


def _roster() -> List[str]:
    from app.models.character import list_available_characters
    return list(list_available_characters(include_dormant=True))


def _run_all_extra(name: str) -> Tuple[str, Optional[int]]:
    """Run all's due kind and its hub jobs when it is one the badges do not count (face cleanup / retexture,
    extension rig), else ("", 0)."""
    from app.core import figure_build
    plan = figure_build.base_run_all(name)
    kind = str(plan.get("kind") or "")
    if kind in (figure_build.RUN_ALL_CLEANUP, figure_build.RUN_ALL_FACE, figure_build.RUN_ALL_EXTENSION):
        return kind, plan.get("hub_jobs")
    return kind, 0


def candidates() -> Dict[str, Any]:
    """Who a start would run and what it costs: ``{characters: [{name, base, outfit, hub_jobs}], hub_jobs (None =
    unknown), note}`` — ``base`` / ``outfit`` the open step counts of the list's badges (Run all's extra kinds count
    as one base step), ``hub_jobs`` the first-attempt estimate (retries extra). Read-only, no hub work."""
    from app.core import figure_build
    rows: List[Dict[str, Any]] = []
    total: Optional[int] = 0
    for name in _roster():
        try:
            info = figure_build.open_steps(name)
            extra_kind, extra_jobs = _run_all_extra(name)
        except Exception as e:  # noqa: BLE001 — one unreadable character never hides the rest
            logger.warning("Build all open: %s not planned: %s", name, e)
            continue
        base = int(info["base"]["count"] or 0)
        outfit = int(info["outfit"]["count"] or 0)
        extra = 1 if extra_kind and extra_kind not in (figure_build.RUN_ALL_PLAIN, figure_build.RUN_ALL_REPAIR,
                                                         figure_build.RUN_ALL_TIP, figure_build.RUN_ALL_COLLISION) else 0
        if not (base or outfit or extra or info.get("building")):
            continue
        parts = [info["base"]["hub_jobs"], info["outfit"]["hub_jobs"], extra_jobs]
        jobs = None if any(p is None for p in parts) else sum(int(p or 0) for p in parts)
        rows.append({"name": name, "base": base + extra, "outfit": outfit, "hub_jobs": jobs})
        total = None if total is None or jobs is None else total + jobs
    note = ("hub jobs unknown for some characters" if total is None
            else f"{total} hub jobs (estimate, retries extra)")
    return {"characters": rows, "hub_jobs": total, "note": note}


def _wait_idle(name: str, what: str) -> None:
    """Wait while a base step or a Build of the character goes; ``TimeoutError`` past ``PHASE_MAX_S``."""
    from app.core import figure_build
    deadline = time.monotonic() + PHASE_MAX_S
    while figure_build.base_step_in_flight(name) or figure_build.running(name):
        if time.monotonic() > deadline:
            raise TimeoutError(TIMED_OUT.format(what=what))
        time.sleep(POLL_S)


def _base_phase(name: str) -> Tuple[str, bool]:
    """Run all until ``current``: ``(error, blocking)`` — ``("", False)`` when the base body is current."""
    from app.core import figure_build
    deadline = time.monotonic() + PHASE_MAX_S
    last_kind = ""
    rounds = 0
    while rounds < MAX_BASE_ROUNDS:
        _wait_idle(name, "the base body")
        due = str(figure_build.base_run_all(name).get("kind") or "")
        if not due:
            return "", False
        if due == last_kind:
            return BASE_STILL_DUE.format(kind=due), due == figure_build.RUN_ALL_PLAIN
        try:
            result = figure_build.start_base_run_all(name)
        except (ValueError, LookupError) as e:   # a face redo its own guard refused
            return BASE_FAILED.format(error=str(e)), False
        status_now = result.get("status")
        if status_now == "current":
            return "", False
        if status_now == "off":
            return OFF_PIPELINE, True
        if status_now == "failed":
            return BASE_FAILED.format(error=result.get("reason") or "failed"), True
        if status_now in ("busy", "building"):
            # Something of the character slipped in between — wait for it and ask again (not a round).
            if time.monotonic() > deadline:
                return TIMED_OUT.format(what="the base body"), True
            time.sleep(POLL_S)
            continue
        kind = str(result.get("kind") or due)
        rounds += 1
        last_kind = kind
        _set(name, PHASE_BASE, "", step=kind)
        time.sleep(POLL_S)   # a hand-off kind registers its run from its own start; never read it too early
        _wait_idle(name, "the base body")
        if kind == figure_build.RUN_ALL_PLAIN:
            last = figure_build.base_run_all(name).get("last") or {}
            if last.get("error"):
                return BASE_FAILED.format(error=last["error"]), True
    return BASE_NOT_SETTLED, False


def _outfit_phase(name: str) -> str:
    """The figure Build (a manual one) until it ended: "" or its failure."""
    from app.core import figure_build
    deadline = time.monotonic() + PHASE_MAX_S
    while True:
        _wait_idle(name, "the outfit")
        result = figure_build.start(name, reason="build_all")
        status_now = result.get("status")
        if status_now in ("current", "off"):
            return ""
        if status_now == "failed":
            return str(result.get("reason") or "Build failed")
        if status_now == "base_busy":
            if time.monotonic() > deadline:
                return TIMED_OUT.format(what="the outfit")
            time.sleep(POLL_S)
            continue
        break   # started / queued (a Build ran — ours is its follow-up)
    _wait_idle(name, "the outfit")
    failed = figure_build.state(name).get("failed") or {}
    return "; ".join(f"{step}: {(v or {}).get('error') or 'failed'}" for step, v in failed.items())


def _run_character(name: str) -> None:
    from app.core import figure_build
    try:
        if _cancelled():
            _set(name, PHASE_SKIPPED, CANCELLED)
            return
        if not _media_on():
            _set(name, PHASE_SKIPPED, MEDIA_OFF)
            return
        if not figure_build.on_pipeline(name):
            _set(name, PHASE_SKIPPED, OFF_PIPELINE)
            return
        _set(name, PHASE_BASE)
        base_error, blocking = _base_phase(name)
        if blocking:
            _set(name, PHASE_FAILED, f"{base_error} — {OUTFIT_SKIPPED}")
            return
        _set(name, PHASE_OUTFIT, base_error)
        outfit_error = _outfit_phase(name)
        reasons = [r for r in (base_error, outfit_error) if r]
        _set(name, PHASE_FAILED if reasons else PHASE_DONE, " · ".join(reasons))
    except Exception as e:  # noqa: BLE001 — one character never stops the others
        logger.exception("Build all open: %s failed", name)
        _set(name, PHASE_FAILED, str(e) or type(e).__name__)


def _run() -> None:
    from app.core.timeutils import utc_now_iso
    try:
        names = [row["name"] for row in candidates()["characters"]]
        with _lock:
            _state["order"] = names
            _state["characters"] = {n: {"phase": PHASE_WAITING, "reason": ""} for n in names}
            _state["collecting"] = False
        _notify()
        logger.info("Build all open: %d characters (%s at once)", len(names), MAX_PARALLEL)
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL, thread_name_prefix="build-all") as pool:
            list(pool.map(_run_character, names))
    except Exception:  # noqa: BLE001
        logger.exception("Build all open failed")
    finally:
        with _lock:
            _state["running"] = False
            _state["collecting"] = False
            _state["finished_at"] = utc_now_iso()
        logger.info("Build all open ended")
        _notify()


def start() -> Dict[str, Any]:
    """Start the run in the background: ``{"status": "started"}`` · ``"running"`` (one goes — ``reason``) ·
    ``"media_off"`` (the media master switch is off — ``reason``)."""
    from app.core.timeutils import utc_now_iso
    if not _media_on():
        return {"status": "media_off", "reason": MEDIA_OFF}
    with _lock:
        if _state["running"]:
            return {"status": "running", "reason": ALREADY_RUNNING}
        _state.update({"running": True, "collecting": True, "cancel": False, "started_at": utc_now_iso(),
                       "finished_at": None, "order": [], "characters": {}})
    try:
        threading.Thread(target=_run, daemon=True, name="build-all-open").start()
    except Exception:
        with _lock:
            _state["running"] = False
            _state["collecting"] = False
        raise
    _notify()
    return {"status": "started"}


def cancel() -> bool:
    """Stop scheduling characters that have not begun (the running ones finish). True while a run goes."""
    with _lock:
        if not _state["running"]:
            return False
        _state["cancel"] = True
    _notify()
    return True
