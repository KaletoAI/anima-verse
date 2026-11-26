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
entry reusing the existing row(s); ``None`` skips the entry for this pass. An effect that
succeeds without creating any object (empty return and no pending row recorded) gets a durable
permanent ``marker`` row so it is never applied a second time if a later entry in the same list
waits or fails. Marker rows are excluded from :attr:`EffectContext.objects` and the admin run
view.

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

    type_id = entry.get("type") if isinstance(entry.get("type"), str) else ""
    t = quest_catalog.types().get(type_id) if type_id else None
    if t is None or t.apply is None:
        return ("waiting", None)

    live_objects: Dict[str, dict] = {}
    for obj in quests.list_objects(run_id, statuses=("live",)):
        if obj.get("kind") == "marker":
            continue
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
    if not created and not target_ids:
        quests.add_object(
            run_id,
            effect_key=key,
            position=position,
            kind="marker",
            ref={"effect_key": key},
            label=key,
            permanent=True,
            status="live",
        )
        return ("done", None)

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


# --- Built-in effect helpers ------------------------------------------------------------------

def _role_value(params: dict, ctx: EffectContext, key: str, field: str) -> str:
    role = params.get(key)
    binding = ctx.bindings.get(role) if isinstance(role, str) else None
    val = binding.get(field) if isinstance(binding, dict) else None
    return val.strip() if isinstance(val, str) else ""


def _recipient(params: dict, ctx: EffectContext) -> str:
    to = params.get("to")
    if isinstance(to, str) and to.strip():
        name = _role_value(params, ctx, "to", "name")
        if not name:
            raise EffectFailed(f"Role '{to}' is not bound")
        return name
    if ctx.avatar:
        return ctx.avatar
    raise EffectFailed("No character to receive this: the setup has no avatar")


def _target_ref(params: dict, ctx: EffectContext, key: str) -> Optional[dict]:
    val = params.get(key)
    if not isinstance(val, str) or not val:
        return None
    if val in ctx.bindings and isinstance(ctx.bindings[val], dict):
        return ctx.bindings[val]
    if val in ctx.objects and isinstance(ctx.objects[val], dict):
        return ctx.objects[val]
    return None


def _notify(character: str, en_text: str, run: dict, effect_key: str, **values: Any) -> None:
    try:
        from app.core.i18n import t
        from app.models import account
        from app.models.character import get_character_language
        from app.models.notifications import create_notification

        if not account.is_player_controlled(character):
            return
        try:
            lang = get_character_language(character) or ""
        except Exception:  # noqa: BLE001
            lang = ""
        text = t(en_text, lang)
        for k, v in values.items():
            text = text.replace("{" + k + "}", str(v))
        if not create_notification(
            character,
            text,
            notification_type="quest",
            metadata={"run_id": run["id"], "effect": effect_key},
        ):
            logger.warning("quest run %s: notification for %s (%s) was not stored",
                           run.get("id"), character, effect_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("quest run %s: notification for %s (%s) failed: %s",
                       run.get("id"), character, effect_key, e)


# --- Built-in effect types --------------------------------------------------------------------

def _apply_give_hint(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.core.linked_characters import mind_of
    from app.models import secrets

    holder_key = params.get("holder")
    holder = _role_value(params, ctx, "holder", "name")
    if not holder:
        raise EffectFailed(f"Role '{holder_key}' is not bound")
    owner = mind_of(holder)
    sid = (ctx.previous[0].get("ref") or {}).get("secret_id") if ctx.previous else ""
    if not sid:
        sid = ctx.mint("sec")
    ref = {"owner": owner, "secret_id": sid}
    text = str(params.get("text") or "")
    label = text[:80]
    ctx.record_pending("secret", ref, label)
    secrets.add_secret(
        holder,
        text,
        category="personal",
        severity=1,
        source="quest",
        source_ref=f"quest_run:{ctx.run['id']}",
        secret_id=sid,
    )
    if secrets.get_secret(owner, sid) is None:
        raise EffectFailed("The hint was not stored", retryable=True)
    return [CreatedObject("secret", ref, label)]


def _apply_reveal_secret(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.models import secrets

    secret_key = params.get("secret")
    ref = _target_ref(params, ctx, "secret")
    owner = str((ref or {}).get("owner") or "")
    secret_id = str((ref or {}).get("secret_id") or "")
    if not ref or not owner or not secret_id:
        raise EffectFailed(f"The secret '{secret_key}' does not exist yet")
    to = _recipient(params, ctx)
    sec = secrets.get_secret(owner, secret_id)
    if sec is None:
        raise EffectFailed(f"The secret '{secret_key}' is gone")
    if not secrets.add_known_by(owner, secret_id, to):
        raise EffectFailed("The secret could not be told", retryable=True)
    _notify(to, "You learned something: {content}", ctx.run, ctx.effect_key,
            content=sec.get("content") or "")
    return []


def _apply_change_stat(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.core.keyed_lock import keyed_lock
    from app.models.character import adjust_status_effects, get_character_profile

    to = _recipient(params, ctx)
    stat = str(params.get("stat") or "")
    delta = int(params.get("delta") or 0)
    # Hold the profile lock through the read-back so success is decided atomically
    # with the write; otherwise a concurrent writer can make a stored delta look
    # failed and cause the next pass to apply it a second time.
    with keyed_lock("character_profile", to):
        profile = get_character_profile(to) or {}
        status = profile.get("status_effects") or {}
        if stat not in status:
            raise EffectFailed(f"{to} has no stat {stat}")
        old = int(status[stat])
        want = max(0, min(100, old + delta))
        changes = adjust_status_effects(to, {stat: delta}, source=f"quest:{ctx.run['id']}")
        after_profile = get_character_profile(to) or {}
        after_status = after_profile.get("status_effects") or {}
        if stat not in after_status or int(after_status[stat]) != want:
            raise EffectFailed("The stat change was not stored", retryable=True)
    ref = {"character": to, "changes": changes}
    label = f"{stat} {delta:+d}"
    if changes:
        _notify(to, "Your {stat} changed by {delta}.", ctx.run, ctx.effect_key,
                stat=stat, delta=f"{delta:+d}")
    return [CreatedObject("stat", ref, label)]


def _apply_post_news(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.models import events

    place_key = params.get("place")
    if isinstance(place_key, str) and place_key.strip():
        location: Optional[str] = _role_value(params, ctx, "place", "location_id")
        if not location:
            raise EffectFailed(f"Role '{place_key}' is not bound")
    else:
        location = None
    eid = (ctx.previous[0].get("ref") or {}).get("event_id") if ctx.previous else ""
    if not eid:
        eid = ctx.mint("evt")
    ref = {"event_id": eid}
    text = str(params.get("text") or "")
    label = text[:80]
    ctx.record_pending("event", ref, label)
    category = str(params.get("category") or "social")
    ttl_hours = int(params["ttl_hours"]) if params.get("ttl_hours") is not None else 24
    evt = events.add_event(
        text,
        location_id=location,
        ttl_hours=ttl_hours,
        category=category,
        metadata={"quest_run": ctx.run["id"]},
        event_id=eid,
    )
    if events.event_exists(eid) is not True:
        raise EffectFailed("The news line was not stored", retryable=True)
    final_ref = {"event_id": eid, "expires_at": evt["expires_at"]} if evt.get("expires_at") else ref
    return [CreatedObject("event", final_ref, label)]


def _apply_narrate(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.core import perception
    from app.models.character import get_character_current_location, get_character_current_room

    to = _recipient(params, ctx)
    loc = get_character_current_location(to) or None
    room = get_character_current_room(to) or None
    uid = perception.record_utterance(
        speaker=perception.STORYTELLER_SPEAKER,
        content=str(params.get("text") or ""),
        location_id=loc,
        room_id=room,
        source="quest",
        anchor=to,
        perception_meta={"display_only": True, "quest": True},
    )
    if uid is None:
        raise EffectFailed("The line was not recorded", retryable=True)
    return []


def _apply_give_item(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.core.i18n import localized
    from app.core.keyed_lock import keyed_lock
    from app.models import inventory
    from app.models.character import get_character_language

    item_key = params.get("item")
    ref = _target_ref(params, ctx, "item")
    item_id = str((ref or {}).get("item_id") or "")
    if not item_id:
        raise EffectFailed(f"The item '{item_key}' does not exist yet")
    item = inventory.get_item(item_id)
    if item is None:
        raise EffectFailed(f"The item '{item_key}' is gone")
    to = _recipient(params, ctx)
    quantity = int(params.get("quantity") or 1)
    name = str(item.get("name") or "").strip() or item_id
    with keyed_lock("character_profile", to):
        ok = inventory.add_to_inventory(
            to,
            item_id,
            quantity,
            obtained_from=f"quest:{ctx.run['id']}",
            obtained_method="quest_reward",
        )
    if not ok:
        raise EffectFailed(f"{to} could not receive {name}: the inventory is full or the write failed")
    try:
        lang = get_character_language(to) or ""
    except Exception:  # noqa: BLE001
        lang = ""
    item_label = localized(item, "name", lang) or item_id
    if quantity == 1:
        _notify(to, "You received {item}.", ctx.run, ctx.effect_key, item=item_label)
    else:
        _notify(to, "You received {quantity} × {item}.", ctx.run, ctx.effect_key,
                quantity=quantity, item=item_label)
    return [CreatedObject("grant", {"character": to, "item_id": item_id, "quantity": quantity}, f"{name} -> {to}")]


def builtin_effect_types() -> list:
    """Return the core's built-in quest effect types (registered under owner ``"core"``)."""
    from app.core.quest_catalog import QuestType

    return [
        QuestType(
            id="give_hint",
            kind="effect",
            label="Give a hint",
            description="A character learns a hint as their own secret and may tell it to an adventurer who asks.",
            params=(
                {"key": "holder", "type": "role", "label": "Holder",
                 "description": "Who knows the hint", "role_kinds": ["character"], "required": True},
                {"key": "text", "type": "text", "label": "Hint",
                 "description": "What the holder knows", "required": True},
            ),
            apply=_apply_give_hint,
            object_kind="secret",
        ),
        QuestType(
            id="reveal_secret",
            kind="effect",
            label="Reveal a secret",
            description="A character learns a secret this quest created.",
            params=(
                {"key": "secret", "type": "target", "label": "Secret",
                 "description": "The key of a hint effect",
                 "role_kinds": [], "object_kinds": ["secret"], "required": True},
                {"key": "to", "type": "role", "label": "To",
                 "description": "Who learns it; empty = the avatar who did the step",
                 "role_kinds": ["character"], "avatar_default": True},
            ),
            apply=_apply_reveal_secret,
            object_kind="",
        ),
        QuestType(
            id="change_stat",
            kind="effect",
            label="Change a stat",
            description="Adds a value to a character's stat; never undone.",
            params=(
                {"key": "stat", "type": "str", "label": "Stat",
                 "description": "The stat key", "required": True},
                {"key": "delta", "type": "int", "label": "Change",
                 "description": "-100 to 100", "min": -100, "max": 100, "step": 1, "required": True},
                {"key": "to", "type": "role", "label": "Character",
                 "description": "Whose stat; empty = the avatar who did the step",
                 "role_kinds": ["character"], "avatar_default": True},
            ),
            apply=_apply_change_stat,
            object_kind="stat",
        ),
        QuestType(
            id="post_news",
            kind="effect",
            label="Post news",
            description="Posts a news line, everywhere or at one place.",
            params=(
                {"key": "text", "type": "text", "label": "Text",
                 "description": "The news line", "required": True},
                {"key": "place", "type": "role", "label": "Place",
                 "description": "Where it happens; empty = everywhere", "role_kinds": ["location"]},
                {"key": "category", "type": "select", "label": "Category",
                 "choices": ["ambient", "social", "disruption", "danger"],
                 "choice_labels": ["Ambient", "Social", "Disruption", "Danger"],
                 "default": "social"},
                {"key": "ttl_hours", "type": "int", "label": "Lasts (game hours)",
                 "description": "0 = until the quest ends", "min": 0, "max": 720, "step": 1, "default": 24},
            ),
            apply=_apply_post_news,
            object_kind="event",
        ),
        QuestType(
            id="narrate",
            kind="effect",
            label="Narrate",
            description="A storyteller line next to a character that only players see.",
            params=(
                {"key": "text", "type": "text", "label": "Text",
                 "description": "The line", "required": True},
                {"key": "to", "type": "role", "label": "Next to",
                 "description": "Who the line appears next to; empty = the avatar who did the step",
                 "role_kinds": ["character"], "avatar_default": True},
            ),
            apply=_apply_narrate,
            object_kind="",
        ),
        QuestType(
            id="give_item",
            kind="effect",
            label="Give an item",
            description="Puts an item into a character's inventory; taken back when the quest ends unless permanent.",
            params=(
                {"key": "item", "type": "target", "label": "Item",
                 "description": "An item role or the key of an item effect",
                 "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
                {"key": "to", "type": "role", "label": "To",
                 "description": "Who receives it; empty = the avatar who did the step",
                 "role_kinds": ["character"], "avatar_default": True},
                {"key": "quantity", "type": "int", "label": "Quantity",
                 "min": 1, "max": 20, "step": 1, "default": 1},
            ),
            apply=_apply_give_item,
            object_kind="grant",
        ),
    ]
