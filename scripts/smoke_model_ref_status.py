#!/usr/bin/env python3
"""Smoke check for the model-ref render STATUS (app/core/model_refs.py).

No server, no world, no DB: every reader of world data the status path
touches (outfit state, humanoid flag, extra views, auto toggles) is replaced
by a stub, the render itself (``_fire_kinds`` / ``generate_model_ref_images``)
by a recorder, and the module's internal tables (``_pending_timers``,
``_running``) are driven directly. Nothing under worlds/ is read or written.

What the status must say, derived BY HAND from the contract in
``get_render_status``:

  [1] idle           — no timer, no thread:   running False, scheduled False,
                       all four stamps None.
  [2] scheduled      — ``schedule_outfit_render`` with auto {tpose: on,
                       pose: off} and a debounce of 3600 s arms EXACTLY one
                       timer (tpose): tpose scheduled True / running False,
                       pose both False. ``scheduled_at`` lies in [t0, t1] of
                       the call, ``due_at − scheduled_at`` is EXACTLY 3600 s
                       (timedelta(seconds=delay)), and ``now`` in the info
                       payload is >= scheduled_at (taken after the arm).
  [3] re-arm         — a second ``schedule_outfit_render`` replaces the entry:
                       the first Timer object is cancelled, the new
                       ``scheduled_at`` is >= the old one.
  [4] manual trigger — ``trigger_now(kinds=("pose",))`` must NOT touch the
                       tpose timer (per-kind timers); ``trigger_now(("tpose",))``
                       disarms it, cancels the Timer and fires the recorder
                       with force=True. Afterwards [1] holds again.
  [5] running        — ``_run_generation`` in a thread, with the render
                       blocked on an Event: running True, ``started_at`` in
                       [t0, t1] of the thread start, scheduled False. After
                       the Event is released the thread ends and [1] holds.
  [6] both           — running AND scheduled may coexist (outfit changed
                       during a render): both flags True, with their own
                       stamps.
  [7] stale timer    — a Timer that fires after being superseded (its entry
                       now points at ANOTHER Timer) must not render: the
                       recorder stays empty and the newer entry survives.
                       The live timer (delay 0.05 s) fires the recorder with
                       force False and clears its entry.
  [8] auto off       — ``schedule_outfit_render`` with every toggle off arms
                       nothing; with the feature disabled it arms nothing.
  [9] payload        — ``get_model_refs_info`` carries ``status`` + ``now``
                       and NO ``pending`` key any more (no compat alias).

Usage:  ./.venv/bin/python scripts/smoke_model_ref_status.py
"""
import sys
import threading
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import model_refs as mr  # noqa: E402
from app.core.timeutils import parse_iso, utc_now  # noqa: E402

FAILURES = []
CHAR = "smoke-status-char"   # never a real character name
DEBOUNCE = 3600.0


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --- stubs: no world data, no renders ---------------------------------------
AUTO = {"tpose": True, "pose": False}
ENABLED = [True]
FIRED = []      # (character, kinds, force) as _fire_kinds would receive them


def _stub_world():
    mr.current_outfit_state = lambda name: ({}, [], "")
    mr.is_humanoid = lambda name: False
    mr.enabled_tpose_views = lambda name: ()
    mr.get_auto_kinds = lambda name: dict(AUTO)
    mr._enabled = lambda: ENABLED[0]
    mr._debounce_seconds = lambda: DEBOUNCE
    mr._fire_kinds = lambda name, kinds, force=False: FIRED.append((name, tuple(kinds), force))


def _reset():
    with mr._lock:
        for entry in mr._pending_timers.values():
            entry.timer.cancel()
        mr._pending_timers.clear()
        mr._running.clear()
    FIRED.clear()


def _idle(status, kind):
    s = status[kind]
    return (s["running"] is False and s["scheduled"] is False
            and s["started_at"] is None and s["scheduled_at"] is None
            and s["due_at"] is None)


def test_idle():
    print("[1] idle")
    _reset()
    st = mr.get_render_status(CHAR)
    check("both kinds idle", all(_idle(st, k) for k in mr.REF_KINDS), str(st))


def test_scheduled():
    print("[2] scheduled")
    _reset()
    t0 = utc_now()
    mr.schedule_outfit_render(CHAR)
    t1 = utc_now()
    info = mr.get_model_refs_info(CHAR)
    st = info["status"]
    check("tpose scheduled, not running",
          st["tpose"]["scheduled"] is True and st["tpose"]["running"] is False, str(st["tpose"]))
    check("pose (auto off) idle", _idle(st, "pose"), str(st["pose"]))
    check("started_at None while only scheduled", st["tpose"]["started_at"] is None)
    sched = parse_iso(st["tpose"]["scheduled_at"])
    due = parse_iso(st["tpose"]["due_at"])
    # isoformat(timespec="seconds") truncates — allow the sub-second floor.
    check("scheduled_at within the call window",
          t0 - timedelta(seconds=1) <= sched <= t1, f"{t0} <= {sched} <= {t1}")
    check("due_at − scheduled_at == debounce (3600 s)",
          (due - sched) == timedelta(seconds=DEBOUNCE), str(due - sched))
    check("payload now >= scheduled_at", parse_iso(info["now"]) >= sched)
    check("exactly one timer armed", len(mr._pending_timers) == 1
          and (CHAR, "tpose") in mr._pending_timers)
    check("nothing fired", FIRED == [])


def test_rearm():
    print("[3] re-arm")
    _reset()
    mr.schedule_outfit_render(CHAR)
    first = mr._pending_timers[(CHAR, "tpose")]
    mr.schedule_outfit_render(CHAR)
    second = mr._pending_timers[(CHAR, "tpose")]
    check("entry replaced", first is not second and first.timer is not second.timer)
    check("old timer cancelled", first.timer.finished.is_set())
    check("new timer alive", not second.timer.finished.is_set())
    check("scheduled_at monotone", second.scheduled_at >= first.scheduled_at)
    check("still exactly one timer", len(mr._pending_timers) == 1)


def test_trigger_now():
    print("[4] manual trigger")
    _reset()
    mr.schedule_outfit_render(CHAR)
    entry = mr._pending_timers[(CHAR, "tpose")]
    mr.trigger_now(CHAR, kinds=("pose",))
    check("pose trigger leaves the tpose timer armed",
          mr._pending_timers.get((CHAR, "tpose")) is entry)
    check("pose fired with force", FIRED == [(CHAR, ("pose",), True)], str(FIRED))
    FIRED.clear()
    mr.trigger_now(CHAR, kinds=("tpose",))
    check("tpose trigger disarms its timer", (CHAR, "tpose") not in mr._pending_timers)
    check("timer object cancelled", entry.timer.finished.is_set())
    check("tpose fired with force", FIRED == [(CHAR, ("tpose",), True)], str(FIRED))
    check("idle again", all(_idle(mr.get_render_status(CHAR), k) for k in mr.REF_KINDS))


def test_running():
    print("[5] running")
    _reset()
    gate = threading.Event()
    entered = threading.Event()

    def fake_render(name, kinds=None, force=False, **kw):
        entered.set()
        gate.wait(5)
        return {}

    mr.generate_model_ref_images = fake_render
    t0 = utc_now()
    th = threading.Thread(target=mr._run_generation, args=[CHAR, "tpose"], daemon=True)
    th.start()
    entered.wait(5)
    t1 = utc_now()
    st = mr.get_render_status(CHAR)
    check("tpose running", st["tpose"]["running"] is True, str(st["tpose"]))
    check("tpose not scheduled", st["tpose"]["scheduled"] is False
          and st["tpose"]["scheduled_at"] is None and st["tpose"]["due_at"] is None)
    started = parse_iso(st["tpose"]["started_at"])
    check("started_at within the start window",
          t0 - timedelta(seconds=1) <= started <= t1, f"{t0} <= {started} <= {t1}")
    check("pose idle", _idle(st, "pose"))
    print("[6] both")
    mr.schedule_outfit_render(CHAR)
    st = mr.get_render_status(CHAR)
    check("running and scheduled coexist",
          st["tpose"]["running"] is True and st["tpose"]["scheduled"] is True)
    check("own stamps", st["tpose"]["started_at"] is not None
          and st["tpose"]["scheduled_at"] is not None and st["tpose"]["due_at"] is not None)
    gate.set()
    th.join(5)
    st = mr.get_render_status(CHAR)
    check("running cleared after the thread ends",
          st["tpose"]["running"] is False and st["tpose"]["started_at"] is None)
    check("scheduled survives the thread end", st["tpose"]["scheduled"] is True)
    _reset()


def test_stale_timer():
    print("[7] stale timer")
    _reset()
    now = utc_now()
    key = (CHAR, "tpose")
    stale = threading.Timer(0.05, mr._fire_kind, args=[CHAR, "tpose"])
    stale.daemon = True
    live = threading.Timer(0.05, mr._fire_kind, args=[CHAR, "tpose"])
    live.daemon = True
    # The entry already points at the LIVE timer when the stale one fires.
    with mr._lock:
        mr._pending_timers[key] = mr._Scheduled(timer=live, scheduled_at=now,
                                                due_at=now + timedelta(seconds=1))
    stale.start()
    stale.join(2)
    check("superseded timer renders nothing", FIRED == [], str(FIRED))
    check("live entry survives", mr._pending_timers.get(key) is not None
          and mr._pending_timers[key].timer is live)
    live.start()
    live.join(2)
    check("live timer fires without force", FIRED == [(CHAR, ("tpose",), False)], str(FIRED))
    check("live entry cleared", key not in mr._pending_timers)
    _reset()


def test_auto_off():
    print("[8] auto off / disabled")
    _reset()
    AUTO.update({"tpose": False, "pose": False})
    mr.schedule_outfit_render(CHAR)
    check("all toggles off arms nothing", mr._pending_timers == {})
    AUTO.update({"tpose": True, "pose": True})
    ENABLED[0] = False
    mr.schedule_outfit_render(CHAR)
    check("feature disabled arms nothing", mr._pending_timers == {})
    ENABLED[0] = True
    mr.schedule_outfit_render(CHAR)
    check("both on arms both kinds",
          set(mr._pending_timers) == {(CHAR, "tpose"), (CHAR, "pose")})
    AUTO.update({"tpose": True, "pose": False})
    _reset()


def test_payload():
    print("[9] payload shape")
    _reset()
    info = mr.get_model_refs_info(CHAR)
    check("status present per kind",
          set(info.get("status", {})) == set(mr.REF_KINDS))
    check("status keys", all(set(info["status"][k]) ==
                             {"running", "started_at", "scheduled", "scheduled_at", "due_at"}
                             for k in mr.REF_KINDS))
    check("now present and parseable", parse_iso(info["now"]) is not None)
    check("no 'pending' alias", "pending" not in info, str(sorted(info)))


def main() -> int:
    _stub_world()
    test_idle()
    test_scheduled()
    test_rearm()
    test_trigger_now()
    test_running()
    test_stale_timer()
    test_auto_off()
    test_payload()
    _reset()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
