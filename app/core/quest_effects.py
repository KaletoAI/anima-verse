"""Quest effects worker — applies owed payouts and cleans up ended runs' objects (stage 2, D6-D12).

A **payout** (``quest_run_payouts``) records an effect position owed by a run (``setup``,
``step:<i>``, ``reward``), written atomically with the run creation or step completion. A
**run object** (``quest_run_objects``) records a world entity created by an effect; reward
objects are always permanent.

WORKER THREAD (D8). One daemon thread named ``quest-effects``, woken immediately by
:func:`wake` (on run start, step completion, run end, or retry) and otherwise every
:data:`PASS_INTERVAL_S` seconds. It is NOT gated by world freeze or task-queue pause (a World
Dev run freezes the world while still expecting quest setup and cleanup to complete).

PASS ORDER (:func:`pass_once`). Serialized by a module lock so concurrent callers never apply
the same entry twice:
    (1) Pending ``setup`` payouts — apply ``setup_effects`` in order; when every entry is done
        and every setup object row is live, move the run out of ``preparing`` to ``hidden``
        (with a start condition) or ``open`` (stamping start/expiry and announcing it).
    (2) Pending ``step:<i>`` and ``reward`` payouts (creation order) — apply ``on_done`` /
        ``rewards`` for ``open``, ``hidden`` or ``done`` runs; mark failed with ``run_ended``
        if the run ended ``cancelled``, ``failed`` or ``broken``.
    (3) Cleanup — remove every non-permanent object of an ended run whose status is ``live``,
        ``pending`` or ``revert_pending`` via :mod:`app.core.quest_objects`.

IDEMPOTENCE & RESTART RECONCILIATION. An effect applies at most once per ``(run_id, effect_key)``.
Before an external write, an effect may call :meth:`EffectContext.record_pending` so a
``pending`` object row exists first. After a restart, a ``pending`` row is reconciled with
``exists(ref)``: ``True`` promotes it to ``live`` without re-running; ``False`` re-applies the
entry reusing the existing row(s); ``None`` skips the entry for this pass. Effects without
objects are covered by the payout row and by checking whether any later entry in the same list
already recorded an object.

LOCKS & PUSHES. An effect's ``apply`` and an object kind's ``remove`` run with NO quest lock
held and take only their own domain locks. This module never imports or calls ``sync_topics``;
when a pass changes anything it calls ``quest_engine._refresh_live()`` and
``quest_engine._quests_changed()`` outside every lock.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import quest_catalog, quest_objects
from app.core.log import get_logger

logger = get_logger("quest_effects")

PASS_INTERVAL_S = 15.0


class EffectFailed(Exception):
    """Raised by an effect's ``apply`` when it cannot complete.

    ``retryable=True`` leaves the payout pending for a later pass with no issue recorded.
    ``retryable=False`` (the default) marks the payout (or preparing run) failed with ``message``.
    """

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = bool(retryable)


@dataclass(frozen=True)
class CreatedObject:
    """One world object returned by an effect's ``apply``."""
    kind: str
    ref: dict
    label: str = ""
    status: str = "live"  # "live" or "pending"


@dataclass(frozen=True)
class EffectContext:
    """Context passed to ``QuestType.apply(params, ctx)`` (D12).

    Text parameters (``type == "text"`` without ``"placeholders": False``) have already had
    ``{role}`` placeholders rendered by :func:`app.core.quest_engine.render_text` before
    ``apply`` is called — effects must not render them again.

    ``objects`` maps each ``effect_key`` of this run to the ``ref`` of its first ``live`` object
    row at the time ``apply`` is called. ``previous`` holds the existing ``pending``/``live``
    object rows for this ``(run, effect_key)`` in id order so a re-applied effect (whose pending
    object answered ``exists == False``) can resume instead of creating a duplicate.
    """
    run: dict
    bindings: dict
    objects: dict
    avatar: str
    position: str
    effect_key: str
    permanent: bool
    previous: tuple = ()
    _recorder: Optional[Callable[[str, dict, str], None]] = field(default=None, repr=False, compare=False)

    def mint(self, prefix: str) -> str:
        """Return a fresh id an effect can record in a pending row before its external write."""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def record_pending(self, kind: str, ref: dict, label: str = "") -> None:
        """Write or update this entry's pending object row BEFORE the external write."""
        if self._recorder is not None:
            self._recorder(kind, ref, label)


# --- Worker thread state ----------------------------------------------------------------------

_pass_lock = threading.Lock()
_thread_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_wake_event = threading.Event()
_warned_unknown_kinds: set = set()


def _loop() -> None:
    while not _stop_event.is_set():
        _wake_event.clear()
        pass_once()
        if _stop_event.is_set():
            break
        _wake_event.wait(timeout=PASS_INTERVAL_S)


def start() -> None:
    """Start the ``quest-effects`` daemon thread if not already running (idempotent, restartable)."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event.clear()
        _wake_event.clear()
        _thread = threading.Thread(target=_loop, name="quest-effects", daemon=True)
        _thread.start()


def stop(timeout: float = 5.0) -> None:
    """Signal the ``quest-effects`` thread to exit and wait up to ``timeout`` seconds."""
    global _thread
    with _thread_lock:
        t = _thread
        _stop_event.set()
        _wake_event.set()
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
    with _thread_lock:
        if _thread is t and (t is None or not t.is_alive()):
            _thread = None


def wake() -> None:
    """Wake the ``quest-effects`` thread for an immediate pass (harmless when not running)."""
    _wake_event.set()


def _reset_for_tests() -> None:
    """Stop the thread if running and clear in-memory state as a fresh process would."""
    stop()
    with _thread_lock:
        _stop_event.clear()
        _wake_event.clear()
    _warned_unknown_kinds.clear()


# --- Entry application ------------------------------------------------------------------------

def _render_params(t: quest_catalog.QuestType, raw_params: dict, run: dict) -> dict:
    from app.core import quest_engine
    params = quest_catalog._with_defaults(t, raw_params or {})
    for spec in t.params:
        if spec.get("type") == "text" and spec.get("placeholders") is not False:
            key = spec.get("key")
            if key in params and isinstance(params[key], str):
                params[key] = quest_engine.render_text(params[key], run)
    return params


def _apply_entry(
    run: dict,
    entries: list,
    index: int,
    position: str,
    avatar: str,
) -> Tuple[str, Optional[str]]:
    """Apply entry ``index`` of ``entries`` for ``run`` at ``position``.

    Returns ``("done", None)``, ``("waiting", None)``, or ``("failed", message)``.
    """
    from app.models import quests

    run_id = run["id"]
    entry = entries[index] if isinstance(entries[index], dict) else {}
    key = str(entry.get("key") or "")

    all_objects = quests.list_objects(run_id)
    rows = [o for o in all_objects if o.get("effect_key") == key and o.get("status") in ("pending", "live")]

    if rows:
        if all(o.get("status") == "live" for o in rows):
            return ("done", None)
        pending_rows = [o for o in rows if o.get("status") == "pending"]
        all_present = True
        for row in pending_rows:
            kind_obj = quest_objects.get_kind(str(row.get("kind") or ""))
            if kind_obj is None:
                return ("waiting", None)
            try:
                present = kind_obj.exists(row.get("ref") or {})
            except Exception as e:  # noqa: BLE001 - unreadable status is not "gone"
                logger.warning("quest run %s: exists check failed for object %s (%s): %s",
                               run_id, row.get("id"), row.get("kind"), e)
                return ("waiting", None)
            if present is None:
                return ("waiting", None)
            if not present:
                all_present = False
        if all_present:
            for row in pending_rows:
                quests.set_object_status(row["id"], "live")
            return ("done", None)
    else:
        later_keys = {
            e.get("key") for e in entries[index + 1:]
            if isinstance(e, dict) and isinstance(e.get("key"), str) and e.get("key")
        }
        if later_keys and any(o.get("effect_key") in later_keys for o in all_objects):
            return ("done", None)

    type_id = entry.get("type") if isinstance(entry.get("type"), str) else ""
    t = quest_catalog.types().get(type_id) if type_id else None
    if t is None or t.apply is None:
        return ("waiting", None)

    live_objects: Dict[str, dict] = {}
    for obj in quests.list_objects(run_id, statuses=("live",)):
        ek = obj.get("effect_key")
        if ek and ek not in live_objects:
            live_objects[ek] = obj.get("ref") or {}

    permanent = bool(entry.get("permanent")) or position == "reward"
    added_ids: List[int] = []
    rec_index = [0]

    def _record_pending(kind: str, ref: dict, label: str = "") -> None:
        n = rec_index[0]
        rec_index[0] += 1
        if n < len(rows):
            quests.set_object_status(rows[n]["id"], "pending", ref=ref)
        else:
            oid = quests.add_object(
                run_id,
                effect_key=key,
                position=position,
                kind=kind,
                ref=ref,
                label=label,
                permanent=permanent,
                status="pending",
            )
            added_ids.append(oid)

    ctx = EffectContext(
        run=run,
        bindings=run.get("bindings") or {},
        objects=live_objects,
        avatar=avatar,
        position=position,
        effect_key=key,
        permanent=permanent,
        previous=tuple(rows),
        _recorder=_record_pending,
    )
    params = _render_params(t, entry.get("params") if isinstance(entry.get("params"), dict) else {}, run)

    try:
        created = t.apply(params, ctx)
    except EffectFailed as e:
        if e.retryable:
            return ("waiting", None)
        return ("failed", str(e.message))
    except Exception as e:  # noqa: BLE001
        logger.exception("quest run %s: effect %r (%s) raised", run_id, key, type_id)
        return ("failed", str(e))

    target_ids = [r["id"] for r in rows] + added_ids
    has_pending = False
    for i, obj in enumerate(created or ()):
        if i < len(target_ids):
            quests.set_object_status(target_ids[i], obj.status, ref=obj.ref)
        else:
            quests.add_object(
                run_id,
                effect_key=key,
                position=position,
                kind=obj.kind,
                ref=obj.ref,
                label=obj.label,
                permanent=permanent,
                status=obj.status,
            )
        if obj.status == "pending":
            has_pending = True

    return ("waiting", None) if has_pending else ("done", None)


# --- Pass steps -------------------------------------------------------------------------------

def _step_setup(payout: dict) -> Tuple[int, Optional[str], int]:
    """Handle one pending ``setup`` payout. Returns ``(applied_delta, opened_run_id_or_None, failed_delta)``."""
    from app.core import quest_engine
    from app.core.timeutils import game_time
    from app.models import quests

    run_id = payout["run_id"]
    run = quests.get_run(run_id)
    if run is None:
        quests.set_payout(
            run_id, "setup", "failed",
            issues=[{"path": "setup", "code": "run_missing", "message": "The run no longer exists"}],
        )
        return (0, None, 1)

    state = run.get("state")
    if state in quests.RUN_ENDED_STATES:
        quests.set_payout(
            run_id, "setup", "failed",
            issues=[{"path": "setup", "code": "run_ended", "message": "The run ended before this was paid"}],
        )
        return (0, None, 1)

    if state in ("hidden", "open"):
        quests.set_payout(run_id, "setup", "applied")
        return (1, None, 0)

    if state != "preparing":
        return (0, None, 0)

    if run.get("issues"):
        return (0, None, 0)

    snap = run.get("template_snapshot") or {}
    entries = snap.get("setup_effects") if isinstance(snap.get("setup_effects"), list) else []
    for j in range(len(entries)):
        outcome, msg = _apply_entry(run, entries, j, "setup", "")
        if outcome == "failed":
            quests.set_run_state(
                run_id,
                "preparing",
                issues=[{"path": f"setup_effects.{j}", "code": "effect_failed", "message": msg or ""}],
                from_states=("preparing",),
            )
            return (0, None, 1)
        if outcome != "done":
            return (0, None, 0)

    setup_objs = [
        o for o in quests.list_objects(run_id, statuses=("pending", "live"))
        if o.get("position") == "setup"
    ]
    if not all(o.get("status") == "live" for o in setup_objs):
        return (0, None, 0)

    now = game_time()
    to_state = "hidden" if snap.get("start_condition") else "open"
    started = now.canonical() if to_state == "open" else ""
    expires = quest_engine._expiry(snap, now) if to_state == "open" else ""
    if not quests.finish_preparing(run_id, to_state=to_state, started_game_ts=started, expires_at=expires):
        return (0, None, 0)

    quests.set_payout(run_id, "setup", "applied")
    if to_state == "open":
        fresh = quests.get_run(run_id)
        if fresh is not None:
            quest_engine._announce(fresh)
    return (1, run_id, 0)


def _step_payout(payout: dict) -> Tuple[int, int]:
    """Handle one pending ``step:<i>`` or ``reward`` payout. Returns ``(applied_delta, failed_delta)``."""
    from app.models import quests

    run_id = payout["run_id"]
    position = payout["position"]
    run = quests.get_run(run_id)
    if run is None:
        quests.set_payout(
            run_id, position, "failed",
            issues=[{"path": position, "code": "run_missing", "message": "The run no longer exists"}],
        )
        return (0, 1)

    state = run.get("state")
    if state in ("cancelled", "failed", "broken"):
        quests.set_payout(
            run_id, position, "failed",
            issues=[{"path": position, "code": "run_ended", "message": "The run ended before this was paid"}],
        )
        return (0, 1)

    if state not in ("open", "hidden", "done"):
        return (0, 0)

    snap = run.get("template_snapshot") or {}
    if position == "reward":
        entries = snap.get("rewards") if isinstance(snap.get("rewards"), list) else []
        path_prefix = "rewards"
    else:
        idx = int(position.split(":", 1)[1])
        steps = snap.get("steps") if isinstance(snap.get("steps"), list) else []
        step = steps[idx] if 0 <= idx < len(steps) and isinstance(steps[idx], dict) else {}
        entries = step.get("on_done") if isinstance(step.get("on_done"), list) else []
        path_prefix = f"steps.{idx}.on_done"

    avatar = str(payout.get("avatar") or "")
    for j in range(len(entries)):
        outcome, msg = _apply_entry(run, entries, j, position, avatar)
        if outcome == "failed":
            quests.set_payout(
                run_id, position, "failed",
                issues=[{"path": f"{path_prefix}.{j}", "code": "effect_failed", "message": msg or ""}],
            )
            return (0, 1)
        if outcome != "done":
            return (0, 0)

    quests.set_payout(run_id, position, "applied")
    return (1, 0)


def _step_cleanup_row(row: dict) -> int:
    """Remove one non-permanent object of an ended run. Returns 1 when marked reverted/gone, else 0."""
    from app.models import quests

    oid = row["id"]
    kind_name = str(row.get("kind") or "")
    kind = quest_objects.get_kind(kind_name)
    if kind is None:
        if kind_name not in _warned_unknown_kinds:
            _warned_unknown_kinds.add(kind_name)
            logger.warning("quest effects cleanup: unknown object kind %r (object %s)", kind_name, oid)
        if row.get("status") != "revert_pending":
            quests.set_object_status(oid, "revert_pending")
        return 0

    try:
        result = kind.remove(row.get("ref") or {})
    except Exception:  # noqa: BLE001
        logger.exception("quest effects cleanup: remove failed for object %s (%s)", oid, kind_name)
        result = quest_objects.REMOVE_LATER

    if result == quest_objects.REMOVE_DONE:
        quests.set_object_status(oid, "reverted")
        return 1
    if result == quest_objects.REMOVE_GONE:
        quests.set_object_status(oid, "gone")
        return 1
    if row.get("status") != "revert_pending":
        quests.set_object_status(oid, "revert_pending")
    return 0


def pass_once() -> Dict[str, Any]:
    """Run one serialized pass: (1) setup payouts, (2) step/reward payouts, (3) ended-run cleanup.

    Callable synchronously from smokes without starting the worker thread. Never raises.
    """
    applied = 0
    opened: List[str] = []
    reverted = 0
    failed = 0

    with _pass_lock:
        try:
            from app.models import quests

            # (1) Pending setup payouts
            for payout in quests.list_payouts(states=("pending",)):
                if payout.get("position") != "setup":
                    continue
                try:
                    a, o, f = _step_setup(payout)
                    applied += a
                    if o is not None:
                        opened.append(o)
                    failed += f
                except Exception:  # noqa: BLE001
                    logger.exception("quest effects: setup payout failed for run %s", payout.get("run_id"))

            # (2) Pending step:<i> and reward payouts (creation order)
            for payout in quests.list_payouts(states=("pending",)):
                pos = str(payout.get("position") or "")
                if not (pos.startswith("step:") or pos == "reward"):
                    continue
                try:
                    a, f = _step_payout(payout)
                    applied += a
                    failed += f
                except Exception:  # noqa: BLE001
                    logger.exception("quest effects: payout %s failed for run %s", pos, payout.get("run_id"))

            # (3) Cleanup of non-permanent objects of ended runs
            for row in quests.objects_to_clean():
                try:
                    reverted += _step_cleanup_row(row)
                except Exception:  # noqa: BLE001
                    logger.exception("quest effects: cleanup failed for object %s", row.get("id"))
        except Exception:  # noqa: BLE001
            logger.exception("quest effects: pass_once failed")

    if applied or opened or reverted or failed:
        from app.core import quest_engine
        try:
            quest_engine._refresh_live()
        except Exception:  # noqa: BLE001
            logger.exception("quest effects: _refresh_live failed")
        try:
            quest_engine._quests_changed()
        except Exception:  # noqa: BLE001
            logger.exception("quest effects: _quests_changed failed")

    return {"applied": applied, "opened": opened, "reverted": reverted, "failed": failed}


def retry(run_id: str) -> bool:
    """Re-arm every failed payout of a not-ended (or ``done``) run and clear a ``preparing`` run's issues.

    Returns True when at least one payout was re-armed or issues were cleared, and wakes the worker.
    """
    from app.models import quests

    run = quests.get_run(run_id)
    if run is None:
        return False
    state = run.get("state")
    if state in quests.RUN_ENDED_STATES and state != "done":
        return False

    changed = False
    for payout in quests.list_payouts(states=("failed",), run_id=run_id):
        if quests.rearm_payout(run_id, payout["position"]):
            changed = True
    if state == "preparing" and run.get("issues"):
        if quests.set_run_state(run_id, "preparing", issues=[], from_states=("preparing",)):
            changed = True
    if changed:
        wake()
    return changed
