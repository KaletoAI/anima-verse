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
        ``pending`` or ``revert_pending`` via :mod:`app.core.quest_objects`: effects in reverse
        creation order, so dependents such as placements and grants go before the items they
        reference; the rows of one effect in creation order, so e.g. a placement goes before the
        library entry it shows.
    (4) Untag permanent quest props — clear the ``quest_run`` sidecar tag on every live
        permanent ``prop`` object whose run has ended (D17), so it joins the prop library.

BUILT-IN EFFECTS (:func:`builtin_effect_types`). Registered under owner ``"core"``:
``give_hint``, ``reveal_secret``, ``change_stat``, ``post_news``, ``narrate``, ``give_item``,
``create_item``, ``place_item``, ``create_prop``, ``place_prop``.

IDEMPOTENCE & RESTART RECONCILIATION. An effect applies at most once per ``(run_id, effect_key)``.
Before an external write, an effect may call :meth:`EffectContext.record_pending` so a
``pending`` object row exists first. After a restart, a ``pending`` row is reconciled with
``exists(ref)``: ``True`` promotes it to ``live`` without re-running (stripping
:data:`PENDING_ONLY_KEYS` from its ref); ``False`` re-applies the entry reusing the existing
row(s); ``None`` skips the entry for this pass. An effect that succeeds without creating any
object (empty return and no pending row recorded) gets a durable permanent ``marker`` row so it
is never applied a second time if a later entry in the same list waits or fails. Marker rows are
excluded from :attr:`EffectContext.objects` and the admin run view.

LOCKS & PUSHES. An effect's ``apply`` and an object kind's ``remove`` run with NO quest lock
held and take only their own domain locks. This module never imports or calls ``sync_topics``;
when a pass changes anything it calls ``quest_engine._refresh_live()`` and
``quest_engine._quests_changed()`` outside every lock.
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import quest_catalog, quest_objects
from app.core.log import get_logger

logger = get_logger("quest_effects")

PASS_INTERVAL_S = 15.0
MESH_TIMEOUT_S = 30 * 60
PENDING_ONLY_KEYS = ("before", "mesh_failed", "mesh_started_at")
CREATE_ITEM_CATEGORIES = ("tool", "key", "consumable", "evidence", "gift", "quest", "decoration", "document")
# Literal choice labels so the admin client can translate them; same order as CREATE_ITEM_CATEGORIES.
CREATE_ITEM_CATEGORY_LABELS = ("Tool", "Key", "Consumable", "Evidence", "Gift", "Quest", "Decoration", "Document")
DIFFICULTY_SCALE = 10


class EffectFailed(Exception):
    """Raised by an effect's ``apply`` when it cannot complete.

    ``retryable=True`` leaves the payout pending for a later pass with no issue recorded.
    ``retryable=False`` (the default) marks the payout (or preparing run) failed with ``message``
    and issue ``code``.
    """

    def __init__(self, message: str, retryable: bool = False, code: str = "effect_failed"):
        super().__init__(message)
        self.message = message
        self.retryable = bool(retryable)
        self.code = str(code or "effect_failed")


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
_untagged_props: set = set()


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
    _untagged_props.clear()


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
) -> Tuple[str, Optional[str], str]:
    """Apply entry ``index`` of ``entries`` for ``run`` at ``position``.

    Returns ``("done", None, "")``, ``("waiting", None, "")``, or ``("failed", message, code)``.
    """
    from app.models import quests

    run_id = run["id"]
    entry = entries[index] if isinstance(entries[index], dict) else {}
    key = str(entry.get("key") or "")

    all_objects = quests.list_objects(run_id)
    key_rows = [o for o in all_objects if o.get("effect_key") == key]
    if key_rows and not any(o.get("status") == "pending" for o in key_rows):
        return ("done", None, "")
    rows = [o for o in key_rows if o.get("status") in ("pending", "live")]

    if rows:
        pending_rows = [o for o in rows if o.get("status") == "pending"]
        all_present = True
        for row in pending_rows:
            kind_obj = quest_objects.get_kind(str(row.get("kind") or ""))
            if kind_obj is None:
                return ("waiting", None, "")
            try:
                present = kind_obj.exists(row.get("ref") or {})
            except Exception as e:  # noqa: BLE001 - unreadable status is not "gone"
                logger.warning("quest run %s: exists check failed for object %s (%s): %s",
                               run_id, row.get("id"), row.get("kind"), e)
                return ("waiting", None, "")
            if present is None:
                return ("waiting", None, "")
            if not present:
                all_present = False
        if all_present:
            for row in pending_rows:
                clean_ref = {k: v for k, v in (row.get("ref") or {}).items() if k not in PENDING_ONLY_KEYS}
                quests.set_object_status(row["id"], "live", ref=clean_ref)
            return ("done", None, "")

    type_id = entry.get("type") if isinstance(entry.get("type"), str) else ""
    t = quest_catalog.types().get(type_id) if type_id else None
    if t is None or t.apply is None:
        return ("waiting", None, "")

    live_objects = quests.live_object_refs(run_id)

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
            return ("waiting", None, "")
        return ("failed", str(e.message), e.code or "effect_failed")
    except Exception as e:  # noqa: BLE001
        logger.exception("quest run %s: effect %r (%s) raised", run_id, key, type_id)
        return ("failed", str(e), "effect_failed")

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
        return ("done", None, "")

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

    return ("waiting", None, "") if has_pending else ("done", None, "")


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
        outcome, msg, code = _apply_entry(run, entries, j, "setup", "")
        if outcome == "failed":
            quests.set_run_state(
                run_id,
                "preparing",
                issues=[{"path": f"setup_effects.{j}", "code": code or "effect_failed", "message": msg or ""}],
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
        after = quests.get_run(run_id)
        if after is None or after.get("state") != "open":
            quest_engine._withdraw_announcement(run_id)
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
        outcome, msg, code = _apply_entry(run, entries, j, position, avatar)
        if outcome == "failed":
            quests.set_payout(
                run_id, position, "failed",
                issues=[{"path": f"{path_prefix}.{j}", "code": code or "effect_failed", "message": msg or ""}],
            )
            return (0, 1)
        if outcome != "done":
            return (0, 0)

    if quests.set_payout(run_id, position, "applied") and position == "reward" and avatar:
        from app.core import quest_book
        from app.models.character import get_character_language
        try:
            lang = get_character_language(avatar) or ""
        except Exception:  # noqa: BLE001
            lang = ""
        items = quest_book.reward_items_label(run_id, avatar, lang)
        if items:
            _notify(avatar, "Reward: {items}", run, "reward", items=items)
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


def _cleanup_order(rows: list) -> list:
    """Order cleanup rows so effects are undone in reverse creation order while
    rows of one effect keep their creation order."""
    first_id: Dict[Tuple[str, str], int] = {}
    for row in rows:
        pair = (str(row.get("run_id") or ""), str(row.get("effect_key") or ""))
        rid = int(row["id"])
        if pair not in first_id or rid < first_id[pair]:
            first_id[pair] = rid
    return sorted(
        rows,
        key=lambda r: (-first_id[(str(r.get("run_id") or ""), str(r.get("effect_key") or ""))], int(r["id"])),
    )


def _untag_permanent_props() -> None:
    """Clear the ``quest_run`` sidecar tag on live or pending permanent props of ended runs (D17)."""
    from app.core import props
    from app.models import quests

    try:
        rows = quests.permanent_props_of_ended_runs()
    except Exception:  # noqa: BLE001
        logger.exception("quest effects: permanent prop untag scan failed")
        return

    for row in rows:
        pid = str((row.get("ref") or {}).get("prop_id") or "")
        if not pid or pid in _untagged_props:
            continue
        try:
            if props.set_quest_run(pid, ""):
                _untagged_props.add(pid)
        except Exception:  # noqa: BLE001
            logger.exception("quest effects: failed untagging permanent prop %s", pid)


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

            # (3) Cleanup of non-permanent objects of ended runs: effects in reverse creation
            # order, so dependents such as placements and grants go before the items they
            # reference; the rows of one effect in creation order, so e.g. a placement goes
            # before the library entry it shows. Wait while the run still has pending payouts.
            runs_with_pending_payouts = {
                p.get("run_id") for p in quests.list_payouts(states=("pending",))
            }
            for row in _cleanup_order(quests.objects_to_clean()):
                if row.get("run_id") in runs_with_pending_payouts:
                    continue
                try:
                    reverted += _step_cleanup_row(row)
                except Exception:  # noqa: BLE001
                    logger.exception("quest effects: cleanup failed for object %s", row.get("id"))

            # (4) Untag permanent quest props of ended runs so they join the library (D17).
            _untag_permanent_props()
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


# change_stat writes no pending row because a stat change cannot be checked for
# "already applied" afterwards (a stat moves for many reasons); a crash between
# adjust_status_effects and the object row can therefore apply it a second time
# - accepted, the window is one function call.
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
        try:
            before = inventory.get_item_quantity(to, item_id, strict=True)
        except Exception as e:  # noqa: BLE001
            raise EffectFailed("The inventory could not be read", retryable=True) from e
        ctx.record_pending(
            "grant",
            {"character": to, "item_id": item_id, "quantity": quantity, "before": before},
            f"{name} -> {to}",
        )
        ok = inventory.add_to_inventory(
            to,
            item_id,
            quantity,
            obtained_from=f"quest:{ctx.run['id']}",
            obtained_method="quest_reward",
        )
    if not ok:
        raise EffectFailed(f"{to} could not receive {name}: the inventory is full or the write failed")
    # Reward grants to the fulfilling avatar are summarized once by the reward payout notice.
    if not (ctx.position == "reward" and to == ctx.avatar):
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


def _apply_take_item(params: dict, ctx: EffectContext) -> List[CreatedObject]:
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

    from_key = params.get("from")
    if isinstance(from_key, str) and from_key.strip():
        giver = _role_value(params, ctx, "from", "name")
        if not giver:
            raise EffectFailed(f"Role '{from_key}' is not bound")
    elif ctx.avatar:
        giver = ctx.avatar
    else:
        raise EffectFailed("No character to take this from: the setup has no avatar")

    to_key = params.get("to")
    receiver = ""
    if isinstance(to_key, str) and to_key.strip():
        receiver = _role_value(params, ctx, "to", "name")
        if not receiver:
            raise EffectFailed(f"Role '{to_key}' is not bound")

    quantity = int(params.get("quantity") or 1)
    name = str(item.get("name") or "").strip() or item_id
    with keyed_lock("character_profile", giver):
        try:
            held = inventory.get_item_quantity(giver, item_id, strict=True)
        except Exception as e:  # noqa: BLE001
            raise EffectFailed("The inventory could not be read", retryable=True) from e
        n = min(held, quantity)
        if n <= 0:
            return []
        ok = inventory.remove_from_inventory(giver, item_id, n)
        if not ok:
            raise EffectFailed(f"Could not take {name} from {giver}", retryable=True)

    if receiver:
        with keyed_lock("character_profile", receiver):
            ok_add = inventory.add_to_inventory(
                receiver,
                item_id,
                n,
                obtained_from=f"quest:{ctx.run['id']}",
                obtained_method="given",
            )
        if not ok_add:
            raise EffectFailed(f"{receiver} could not receive {name}: the inventory is full or the write failed")

    try:
        from_lang = get_character_language(giver) or ""
    except Exception:  # noqa: BLE001
        from_lang = ""
    from_label = localized(item, "name", from_lang) or item_id
    if n == 1:
        _notify(giver, "You handed over {item}.", ctx.run, ctx.effect_key, item=from_label)
    else:
        _notify(giver, "You handed over {quantity} × {item}.", ctx.run, ctx.effect_key,
                quantity=n, item=from_label)

    if receiver:
        try:
            to_lang = get_character_language(receiver) or ""
        except Exception:  # noqa: BLE001
            to_lang = ""
        to_label = localized(item, "name", to_lang) or item_id
        if n == 1:
            _notify(receiver, "You received {item}.", ctx.run, ctx.effect_key, item=to_label)
        else:
            _notify(receiver, "You received {quantity} × {item}.", ctx.run, ctx.effect_key,
                    quantity=n, item=to_label)

    return []


def _render_item_image(item_id: str) -> None:
    from app.core import item_images
    from app.imagegen.base import MediaGenerationDisabled
    try:
        item_images.generate_item_image_sync(item_id, raise_errors=True)
    except MediaGenerationDisabled:
        logger.info("quest item %s: media generation is off, the item keeps no image", item_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("quest item %s: background image render failed: %s", item_id, e)


def _validate_create_item(params: dict, bindings: dict | None) -> list:
    from app.core.activity_engine import ConditionIssue
    from app.models import inventory

    issues: list = []
    raw_effects = params.get("effects")
    if isinstance(raw_effects, str) and raw_effects.strip():
        try:
            parsed_effects = json.loads(raw_effects)
        except ValueError:
            issues.append(ConditionIssue("bad_json", "Effects must be a JSON object"))
        else:
            if not isinstance(parsed_effects, dict):
                issues.append(ConditionIssue("bad_json", "Effects must be a JSON object"))

    raw_bonuses = params.get("stat_bonuses")
    if isinstance(raw_bonuses, str) and raw_bonuses.strip():
        try:
            parsed_bonuses = json.loads(raw_bonuses)
        except ValueError:
            issues.append(ConditionIssue("bad_json", "Stat bonuses must be a JSON object"))
        else:
            if not isinstance(parsed_bonuses, dict):
                issues.append(ConditionIssue("bad_json", "Stat bonuses must be a JSON object"))
            else:
                bonus_when = str(params.get("bonus_when") or "equipped")
                try:
                    inventory._validate_passive_bonuses({"stat_bonuses": parsed_bonuses, "bonus_when": bonus_when})
                except ValueError as e:
                    issues.append(ConditionIssue("bad_param", str(e)))
    return issues


def _apply_create_item(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.models import inventory

    iid = (ctx.previous[0].get("ref") or {}).get("item_id") if ctx.previous else ""
    if not iid:
        iid = ctx.mint("item_q")
    name = str(params.get("name") or "").strip()
    ctx.record_pending("item", {"item_id": iid}, name)

    raw_effects = str(params.get("effects") or "").strip()
    effects = None
    if raw_effects:
        try:
            parsed_effects = json.loads(raw_effects)
        except ValueError as e:
            raise EffectFailed(f"Effects must be a JSON object: {e}") from e
        if not isinstance(parsed_effects, dict):
            raise EffectFailed("Effects must be a JSON object")
        effects = parsed_effects

    raw_bonuses = str(params.get("stat_bonuses") or "").strip()
    properties = None
    if raw_bonuses:
        try:
            parsed_bonuses = json.loads(raw_bonuses)
        except ValueError as e:
            raise EffectFailed(f"Stat bonuses must be a JSON object: {e}") from e
        if not isinstance(parsed_bonuses, dict):
            raise EffectFailed("Stat bonuses must be a JSON object")
        bonus_when = str(params.get("bonus_when") or "equipped")
        properties = {
            "enables_locations": [],
            "enables_activities": [],
            "stat_bonuses": parsed_bonuses,
            "uses": None,
            "bonus_when": bonus_when,
        }

    try:
        inventory.add_item(
            name,
            description=str(params.get("description") or ""),
            category=str(params.get("category") or "quest"),
            image_prompt=str(params.get("image_prompt") or ""),
            consumable=bool(params.get("consumable", False)),
            properties=properties,
            effects=effects,
            item_id=iid,
        )
    except ValueError as e:
        raise EffectFailed(str(e)) from e

    if inventory.get_item(iid) is None:
        raise EffectFailed("The item was not stored", retryable=True)

    threading.Thread(
        target=_render_item_image,
        args=(iid,),
        daemon=True,
        name=f"quest-item-image-{iid}",
    ).start()
    return [CreatedObject("item", {"item_id": iid}, name)]


def _apply_place_item(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.models import inventory

    item_key = params.get("item")
    ref = _target_ref(params, ctx, "item")
    item_id = str((ref or {}).get("item_id") or "")
    if not item_id:
        raise EffectFailed(f"The item '{item_key}' does not exist yet")
    item = inventory.get_item(item_id)
    if item is None:
        raise EffectFailed(f"The item '{item_key}' is gone")

    room_key = params.get("room")
    location_id = _role_value(params, ctx, "room", "location_id")
    room_id = _role_value(params, ctx, "room", "room_id")
    if not location_id or not room_id:
        raise EffectFailed(f"Role '{room_key}' is not bound")

    quantity = int(params.get("quantity") or 1)
    hidden = bool(params.get("hidden", False))
    difficulty = int(params.get("difficulty") or 0)
    note = str(params.get("note") or "")
    name = str(item.get("name") or "").strip() or item_id
    label = f"{name} in {location_id}/{room_id}"

    try:
        room_items = inventory.get_room_items(location_id, room_id, strict=True)
    except Exception as e:  # noqa: BLE001
        raise EffectFailed("The room could not be read", retryable=True) from e
    before = sum(int(ri.get("quantity", 1) or 1) for ri in room_items if ri.get("item_id") == item_id)

    ctx.record_pending(
        "room_item",
        {
            "location_id": location_id,
            "room_id": room_id,
            "item_id": item_id,
            "quantity": quantity,
            "before": before,
        },
        label,
    )
    ok = inventory.add_item_to_room(
        location_id,
        room_id,
        item_id,
        quantity,
        hidden=hidden,
        discovery_difficulty=difficulty * DIFFICULTY_SCALE,
        note=note,
    )
    if not ok:
        raise EffectFailed(f"{name} could not be placed in {location_id}/{room_id}")
    return [
        CreatedObject(
            "room_item",
            {"location_id": location_id, "room_id": room_id, "item_id": item_id, "quantity": quantity},
            label,
        )
    ]


# --- Prop helpers and built-in prop effects ---------------------------------------------------

def _prop_media_problem() -> str:
    """Return an empty string when media generation and both prop routes are ready, else why not."""
    from app.imagegen import routing
    from app.imagegen.base import media_generation_enabled

    try:
        if not media_generation_enabled():
            return "Media generation is off: a quest prop needs a 3D model"
    except Exception as e:  # noqa: BLE001
        return f"Media generation check failed: {e}"
    try:
        routing.resolve_image_route("prop", advance_rotation=False)
    except Exception as e:  # noqa: BLE001
        return f"No backend is routed for prop images (Media Generation -> Routing, occasion prop): {e}"
    try:
        routing.resolve_image_route("mesh_object", advance_rotation=False)
    except Exception as e:  # noqa: BLE001
        return f"No backend is routed for 3D object meshes (Media Generation -> Routing, occasion mesh_object): {e}"
    return ""


def _prop_has_model(prop_id: str) -> bool:
    """Return True when the prop currently has a published 3D model."""
    from app.core import props
    return bool((props.get_prop(prop_id, read_only=True) or {}).get("has_model"))


def _mesh_sizes(w: Any, d: Any, h: Any) -> Tuple[int, int]:
    """Compute ``(face_num, texture_size)`` using the room_furnish sizing rule."""
    vals: List[float] = []
    for raw in (w, d, h):
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and v > 0:
            vals.append(v)
    base = max(vals) if vals else 1.0
    max_dim = base or 1.0
    face_num = max(2000, min(20000, int(round(6000 * max_dim))))
    texture_size = 512 if max_dim <= 0.5 else (1024 if max_dim < 1.5 else 2048)
    return (face_num, texture_size)


def _prop_placement_kind(params: dict) -> str:
    room = params.get("room") if isinstance(params, dict) else None
    return "room_prop" if isinstance(room, str) and room.strip() else "world_prop"


def _validate_prop_placement(params: dict, bindings: dict | None) -> list:
    from app.core.activity_engine import ConditionIssue

    has_room = isinstance(params.get("room"), str) and bool(params["room"].strip())
    has_near = isinstance(params.get("near"), str) and bool(params["near"].strip())
    if has_room == has_near:
        return [ConditionIssue("bad_param", "Choose either a room or a place near a location")]
    return []


def _validate_place_prop(params: dict, bindings: dict | None) -> list:
    from app.core import props
    from app.core.activity_engine import ConditionIssue

    issues = _validate_prop_placement(params, bindings)
    raw_id = params.get("prop_id")
    pid = props.safe_prop_id(str(raw_id or ""))
    if not pid:
        issues.append(ConditionIssue("bad_param", f"'{raw_id}' is not a prop id"))
        return issues
    if bindings is not None and not props.read_sidecar(pid, read_only=True):
        issues.append(ConditionIssue("unknown_prop", f"Prop '{pid}' does not exist"))
    return issues


def _is_finite_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_prop_placement_target(params: dict, ctx: EffectContext) -> Dict[str, Any]:
    from app.models import world, world_props

    yaw = int(params.get("yaw") or 0) % 360
    room_key = params.get("room")
    if isinstance(room_key, str) and room_key.strip():
        location_id = _role_value(params, ctx, "room", "location_id")
        room_id = _role_value(params, ctx, "room", "room_id")
        if not location_id or not room_id:
            raise EffectFailed(f"Role '{room_key}' is not bound")
        loc = world.get_location_by_id(location_id)
        room = world.get_room_by_id(loc, room_id) if loc is not None else None
        if loc is None or room is None:
            raise EffectFailed(f"Room '{room_id}' does not exist")
        if room_id == world.GROUND_ROOM_ID:
            at = [0.0, 0.0]
        else:
            layout = room.get("layout")
            if not isinstance(layout, dict) or not _is_finite_num(layout.get("w")) or not _is_finite_num(layout.get("d")):
                raise EffectFailed(f"Room '{room_id}' has no floor plan")
            at = [round(float(layout["w"]) / 2.0, 3), round(float(layout["d"]) / 2.0, 3)]
        return {
            "kind": "room_prop",
            "location_id": location_id,
            "room_id": room_id,
            "at": at,
            "yaw": yaw,
        }

    near_key = params.get("near")
    if not isinstance(near_key, str) or not near_key.strip():
        raise EffectFailed("Choose either a room or a place near a location")
    location_id = _role_value(params, ctx, "near", "location_id")
    if not location_id:
        raise EffectFailed(f"Role '{near_key}' is not bound")
    loc = world.get_location_by_id(location_id)
    if loc is None:
        raise EffectFailed(f"Location '{location_id}' does not exist")
    pos_x = loc.get("pos_x")
    pos_z = loc.get("pos_z")
    if not _is_finite_num(pos_x) or not _is_finite_num(pos_z):
        raise EffectFailed(f"Location '{location_id}' has no position on the map")
    if world_props.count_world_props() >= world_props.MAX_WORLD_PROPS:
        raise EffectFailed(f"At most {world_props.MAX_WORLD_PROPS} world props per world")
    offset_x = float(params.get("offset_x") or 0.0)
    offset_z = float(params.get("offset_z") or 0.0)
    return {
        "kind": "world_prop",
        "location_id": location_id,
        "x": float(pos_x) + offset_x,
        "z": float(pos_z) + offset_z,
        "yaw": yaw,
    }


def _prop_place_label(name: str, target: Dict[str, Any], placement_id: str) -> str:
    if target["kind"] == "world_prop":
        return f"{name} ({placement_id})"
    return f"{name} in {target['location_id']}/{target['room_id']}"


def _write_prop_placement(target: Dict[str, Any], pid: str, placement_id: str) -> Dict[str, Any]:
    from app.models import world, world_props

    if target["kind"] == "world_prop":
        if world_props.count_world_props() >= world_props.MAX_WORLD_PROPS:
            raise EffectFailed(f"At most {world_props.MAX_WORLD_PROPS} world props per world")
        raw = {
            "id": placement_id,
            "prop_id": pid,
            "x": target["x"],
            "z": target["z"],
            "yaw_deg": target["yaw"],
            "offset_y": 0.0,
        }
        try:
            entry = world_props.sanitize_world_prop(raw)
            world_props.save_world_prop(entry)
        except ValueError as e:
            raise EffectFailed(str(e)) from e
        stored = next((r for r in world_props.list_world_props() if r.get("id") == placement_id), None)
        if stored is None:
            raise EffectFailed("The world prop placement was not stored", retryable=True)
        return {"placement_id": placement_id, "written": stored}

    entry: Dict[str, Any] = {"id": placement_id, "prop_id": pid, "at": target["at"]}
    if target["yaw"]:
        entry["yaw"] = target["yaw"]
    ok = world.append_room_props(target["location_id"], target["room_id"], [entry])
    if not ok:
        raise EffectFailed(f"The prop could not be placed in {target['location_id']}/{target['room_id']}")
    loc = world.get_location_by_id(target["location_id"])
    room = world.get_room_by_id(loc, target["room_id"]) if loc is not None else None
    room_props = ((room or {}).get("layout") or {}).get("props") or []
    if not any(isinstance(p, dict) and p.get("id") == placement_id for p in room_props):
        raise EffectFailed("The room is full: the prop could not be placed")
    return {
        "location_id": target["location_id"],
        "room_id": target["room_id"],
        "place_id": placement_id,
        "prop_id": pid,
    }


def _now_iso() -> str:
    """Current system time as an ISO UTC string (seconds precision), via ``timeutils.utc_now``."""
    from app.core import timeutils
    return timeutils.utc_now().isoformat(timespec="seconds")


def _parse_stamp(value: Any) -> Optional[Any]:
    """Parse a system-time ISO timestamp, returning ``None`` when empty or unparsable."""
    if not isinstance(value, str) or not value.strip():
        return None
    from app.core import timeutils
    try:
        return timeutils.parse_iso(value)
    except (ValueError, TypeError):
        return None


def _apply_create_prop(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.core import places_migration, props, timeutils
    from app.models import quests

    prev = list(ctx.previous)
    place_row = prev[0] if len(prev) >= 1 else None
    prop_row = prev[1] if len(prev) >= 2 else None

    name = str(params.get("name") or "").strip() or "Prop"
    prompt = str(params.get("prompt") or "").strip()
    width_m = params.get("width_m")
    depth_m = params.get("depth_m")
    height_m = params.get("height_m")
    face_num, texture_size = _mesh_sizes(width_m, depth_m, height_m)
    quest_run = "" if ctx.run.get("state") in quests.RUN_ENDED_STATES else str(ctx.run.get("id") or "")

    # Fresh run (no prop object row yet).
    if prop_row is None:
        problem = _prop_media_problem()
        if problem:
            raise EffectFailed(problem)
        target = _check_prop_placement_target(params, ctx)
        pid = props.new_prop_id(name)
        if target["kind"] == "world_prop":
            existing_id = str(((place_row or {}).get("ref") or {}).get("placement_id") or "")
            placement_id = existing_id or ctx.mint("wp")
            pending_place_ref: Dict[str, Any] = {"placement_id": placement_id, "written": {}}
        else:
            existing_id = str(((place_row or {}).get("ref") or {}).get("place_id") or "")
            placement_id = existing_id or places_migration.new_place_id()
            pending_place_ref = {
                "location_id": target["location_id"],
                "room_id": target["room_id"],
                "place_id": placement_id,
                "prop_id": pid,
            }
        place_label = _prop_place_label(name, target, placement_id)
        pending_prop_ref: Dict[str, Any] = {
            "prop_id": pid,
            "mesh_started_at": _now_iso(),
        }
        ctx.record_pending(target["kind"], pending_place_ref, place_label)
        ctx.record_pending("prop", pending_prop_ref, name)
        try:
            props.create_prop(
                prop_id=pid,
                name=name,
                width_m=width_m,
                depth_m=depth_m,
                height_m=height_m,
                description=prompt,
                prompt=prompt,
                source="generated",
                quest_run=quest_run,
            )
            props.trigger_generation(pid, face_num=face_num, texture_size=texture_size)
        except ValueError as e:
            raise EffectFailed(str(e)) from e
        return [
            CreatedObject(target["kind"], pending_place_ref, place_label, status="pending"),
            CreatedObject("prop", pending_prop_ref, name, status="pending"),
        ]

    # Resume (prop row exists; placement row answered exists == False).
    place_ref = dict((place_row or {}).get("ref") or {})
    prop_ref = dict(prop_row.get("ref") or {})
    pid = str(prop_ref.get("prop_id") or "")
    place_kind = str((place_row or {}).get("kind") or _prop_placement_kind(params))
    place_label = str((place_row or {}).get("label") or name)

    if not props.read_sidecar(pid, read_only=True):
        problem = _prop_media_problem()
        if problem:
            raise EffectFailed(problem)
        _check_prop_placement_target(params, ctx)
        fresh_prop_ref: Dict[str, Any] = {
            "prop_id": pid,
            "mesh_started_at": _now_iso(),
        }
        ctx.record_pending(place_kind, place_ref, place_label)
        ctx.record_pending("prop", fresh_prop_ref, name)
        try:
            props.create_prop(
                prop_id=pid,
                name=name,
                width_m=width_m,
                depth_m=depth_m,
                height_m=height_m,
                description=prompt,
                prompt=prompt,
                source="generated",
                quest_run=quest_run,
            )
            props.trigger_generation(pid, face_num=face_num, texture_size=texture_size)
        except ValueError as e:
            raise EffectFailed(str(e)) from e
        return [
            CreatedObject(place_kind, place_ref, place_label, status="pending"),
            CreatedObject("prop", fresh_prop_ref, name, status="pending"),
        ]

    if _prop_has_model(pid):
        target = _check_prop_placement_target(params, ctx)
        if target["kind"] == "world_prop":
            placement_id = str(place_ref.get("placement_id") or "") or ctx.mint("wp")
        else:
            placement_id = str(place_ref.get("place_id") or "") or places_migration.new_place_id()
        final_place_ref = _write_prop_placement(target, pid, placement_id)
        final_place_label = _prop_place_label(name, target, placement_id)
        return [
            CreatedObject(target["kind"], final_place_ref, final_place_label),
            CreatedObject("prop", {"prop_id": pid}, name),
        ]

    if props.is_pending(pid):
        if prop_ref.get("mesh_failed") is True:
            fresh_prop_ref = {"prop_id": pid, "mesh_started_at": _now_iso()}
            ctx.record_pending(place_kind, place_ref, place_label)
            ctx.record_pending("prop", fresh_prop_ref, name)
            return [
                CreatedObject(place_kind, place_ref, place_label, status="pending"),
                CreatedObject("prop", fresh_prop_ref, name, status="pending"),
            ]
        raw_started = prop_ref.get("mesh_started_at")
        anchor_dt = _parse_stamp(raw_started)
        if anchor_dt is not None:
            anchor_iso = str(raw_started)
        else:
            raw_created = prop_row.get("created_at")
            anchor_dt = _parse_stamp(raw_created)
            anchor_iso = str(raw_created) if anchor_dt is not None else ""
        if anchor_dt is None:
            logger.warning(
                "quest run %s: unparsable mesh anchor for prop %s (mesh_started_at=%r, created_at=%r)",
                ctx.run.get("id"), pid, raw_started, prop_row.get("created_at"),
            )
            return [
                CreatedObject(place_kind, place_ref, place_label, status="pending"),
                CreatedObject("prop", prop_ref, name, status="pending"),
            ]
        if (timeutils.utc_now() - anchor_dt).total_seconds() > MESH_TIMEOUT_S:
            failed_prop_ref = {"prop_id": pid, "mesh_started_at": anchor_iso, "mesh_failed": True}
            ctx.record_pending(place_kind, place_ref, place_label)
            ctx.record_pending("prop", failed_prop_ref, name)
            raise EffectFailed(
                f"The 3D model for '{name}' did not finish within 30 minutes",
                code="mesh_timeout",
            )
        return [
            CreatedObject(place_kind, place_ref, place_label, status="pending"),
            CreatedObject("prop", prop_ref, name, status="pending"),
        ]

    # Not pending and no model.
    if prop_ref.get("mesh_failed") is True:
        try:
            props.trigger_generation(pid, face_num=face_num, texture_size=texture_size)
        except ValueError as e:
            raise EffectFailed(str(e)) from e
        fresh_prop_ref = {"prop_id": pid, "mesh_started_at": _now_iso()}
        ctx.record_pending(place_kind, place_ref, place_label)
        ctx.record_pending("prop", fresh_prop_ref, name)
        return [
            CreatedObject(place_kind, place_ref, place_label, status="pending"),
            CreatedObject("prop", fresh_prop_ref, name, status="pending"),
        ]

    anchor_iso = str(prop_ref.get("mesh_started_at") or prop_row.get("created_at") or "")
    failed_prop_ref = {"prop_id": pid, "mesh_started_at": anchor_iso, "mesh_failed": True}
    ctx.record_pending(place_kind, place_ref, place_label)
    ctx.record_pending("prop", failed_prop_ref, name)
    raise EffectFailed(
        f"The 3D model for '{name}' could not be generated (see the queue panel); Retry generates it again",
        code="mesh_failed",
    )


def _apply_place_prop(params: dict, ctx: EffectContext) -> List[CreatedObject]:
    from app.core import places_migration, props

    raw_id = params.get("prop_id")
    pid = props.safe_prop_id(str(raw_id or ""))
    meta = props.read_sidecar(pid, read_only=True) if pid else {}
    if not pid or not meta:
        raise EffectFailed(f"Prop '{raw_id}' does not exist")

    target = _check_prop_placement_target(params, ctx)
    prev_ref = (ctx.previous[0].get("ref") or {}) if ctx.previous else {}
    name = str(meta.get("name") or "").strip() or pid
    if target["kind"] == "world_prop":
        placement_id = str(prev_ref.get("placement_id") or "") or ctx.mint("wp")
        pending_ref: Dict[str, Any] = {"placement_id": placement_id, "written": {}}
    else:
        placement_id = str(prev_ref.get("place_id") or "") or places_migration.new_place_id()
        pending_ref = {
            "location_id": target["location_id"],
            "room_id": target["room_id"],
            "place_id": placement_id,
            "prop_id": pid,
        }
    label = _prop_place_label(name, target, placement_id)
    ctx.record_pending(target["kind"], pending_ref, label)
    final_ref = _write_prop_placement(target, pid, placement_id)
    return [CreatedObject(target["kind"], final_ref, label)]


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
        QuestType(
            id="take_item",
            kind="effect",
            label="Take an item",
            description="Takes an item from a character, optionally handing it to another; never undone.",
            params=(
                {"key": "item", "type": "target", "label": "Item",
                 "description": "An item role or the key of an item effect",
                 "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
                {"key": "from", "type": "role", "label": "From",
                 "description": "Who gives it up; empty = the avatar who did the step",
                 "role_kinds": ["character"], "avatar_default": True},
                {"key": "to", "type": "role", "label": "To",
                 "description": "Who receives it; empty = it is used up",
                 "role_kinds": ["character"]},
                {"key": "quantity", "type": "int", "label": "Quantity",
                 "min": 1, "max": 20, "step": 1, "default": 1},
            ),
            apply=_apply_take_item,
            object_kind="",
        ),
        QuestType(
            id="create_item",
            kind="effect",
            label="Create an item",
            description="Creates a new item; deleted everywhere when the quest ends unless permanent.",
            params=(
                {"key": "name", "type": "str", "label": "Name", "required": True},
                {"key": "description", "type": "text", "label": "Description"},
                {"key": "category", "type": "select", "label": "Category",
                 "choices": list(CREATE_ITEM_CATEGORIES),
                 "choice_labels": list(CREATE_ITEM_CATEGORY_LABELS),
                 "default": "quest"},
                {"key": "consumable", "type": "bool", "label": "Consumable", "default": False},
                {"key": "effects", "type": "text", "label": "Effects (JSON)",
                 "description": 'A JSON object in the item effects format, e.g. {"<stat>_change": 5}',
                 "placeholders": False},
                {"key": "stat_bonuses", "type": "text", "label": "Stat bonuses (JSON)",
                 "description": "A JSON object {stat: whole number -100..100}",
                 "placeholders": False},
                {"key": "bonus_when", "type": "select", "label": "Bonus when",
                 "choices": ["equipped", "carried"],
                 "choice_labels": ["Equipped", "Carried"],
                 "default": "equipped"},
                {"key": "image_prompt", "type": "text", "label": "Image prompt",
                 "description": "Empty = the name"},
            ),
            validate=_validate_create_item,
            apply=_apply_create_item,
            object_kind="item",
        ),
        QuestType(
            id="place_item",
            kind="effect",
            label="Place an item",
            description="Puts an item into a room, optionally hidden; taken away when the quest ends unless permanent.",
            params=(
                {"key": "item", "type": "target", "label": "Item",
                 "description": "An item role or the key of an item effect",
                 "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
                {"key": "room", "type": "role", "label": "Room",
                 "role_kinds": ["room"], "required": True},
                {"key": "quantity", "type": "int", "label": "Quantity",
                 "min": 1, "max": 20, "step": 1, "default": 1},
                {"key": "hidden", "type": "bool", "label": "Hidden", "default": False},
                {"key": "difficulty", "type": "int", "label": "Difficulty",
                 "description": "0-10; times 10 against the discovery stat (0-100)",
                 "min": 0, "max": 10, "step": 1, "default": 0},
                {"key": "note", "type": "str", "label": "Note"},
            ),
            apply=_apply_place_item,
            object_kind="room_item",
        ),
        QuestType(
            id="create_prop",
            kind="effect",
            label="Create a prop",
            description="Creates a new 3D prop from a description and places it; the quest waits until its model exists. Removed when the quest ends unless permanent.",
            params=(
                {"key": "name", "type": "str", "label": "Name", "required": True},
                {"key": "prompt", "type": "text", "label": "Prompt",
                 "description": "What the prop looks like", "required": True},
                {"key": "width_m", "type": "float", "label": "Width (m)",
                 "min": 0.1, "max": 20.0, "step": 0.1},
                {"key": "depth_m", "type": "float", "label": "Depth (m)",
                 "min": 0.1, "max": 20.0, "step": 0.1},
                {"key": "height_m", "type": "float", "label": "Height (m)",
                 "min": 0.1, "max": 20.0, "step": 0.1},
                {"key": "room", "type": "role", "label": "Room",
                 "description": "Place inside this room (either Room or Near)",
                 "role_kinds": ["room"]},
                {"key": "near", "type": "role", "label": "Near",
                 "description": "Place outdoors near this location (either Room or Near)",
                 "role_kinds": ["location"]},
                {"key": "offset_x", "type": "float", "label": "Offset X (m)",
                 "min": -200.0, "max": 200.0, "step": 0.5, "default": 0.0},
                {"key": "offset_z", "type": "float", "label": "Offset Z (m)",
                 "min": -200.0, "max": 200.0, "step": 0.5, "default": 0.0},
                {"key": "yaw", "type": "int", "label": "Yaw (deg)",
                 "min": 0, "max": 359, "step": 1, "default": 0},
            ),
            validate=_validate_prop_placement,
            apply=_apply_create_prop,
            object_kind="world_prop",
            object_kind_when=(("room", "room_prop"),),
        ),
        QuestType(
            id="place_prop",
            kind="effect",
            label="Place a prop",
            description="Places an existing library prop in a room or near a place; removed when the quest ends unless permanent.",
            params=(
                {"key": "prop_id", "type": "str", "label": "Prop",
                 "description": "Library prop id", "required": True},
                {"key": "room", "type": "role", "label": "Room",
                 "description": "Place inside this room (either Room or Near)",
                 "role_kinds": ["room"]},
                {"key": "near", "type": "role", "label": "Near",
                 "description": "Place outdoors near this location (either Room or Near)",
                 "role_kinds": ["location"]},
                {"key": "offset_x", "type": "float", "label": "Offset X (m)",
                 "min": -200.0, "max": 200.0, "step": 0.5, "default": 0.0},
                {"key": "offset_z", "type": "float", "label": "Offset Z (m)",
                 "min": -200.0, "max": 200.0, "step": 0.5, "default": 0.0},
                {"key": "yaw", "type": "int", "label": "Yaw (deg)",
                 "min": 0, "max": 359, "step": 1, "default": 0},
            ),
            validate=_validate_place_prop,
            apply=_apply_place_prop,
            object_kind="world_prop",
            object_kind_when=(("room", "room_prop"),),
        ),
    ]
