"""Pause automatic generation per character (Ruling A42).

The user: "There must be a way to suspend generations, e.g. when a garment is
generated automatically but I want to redo the base body first." The Figure
tab's header carries the switch "Pause automatic generation"
(``POST /characters/{c}/figure/generation-pause``, admin-only).

WHERE IT LIVES. The pause is runtime state of the character persisted in the
world's ``task_queue.db`` (``TaskQueue.set_character_paused``: table
``character_generation_paused``, mirrored in memory) — next to the queue
pause it extends, never in the profile: the many trigger checks below read it
without a DB access and without the profile lock.

WHAT IT HOLDS — every automatic way generation work of the character starts
(the trigger list; each is checked at its ONE choke point):

* the automatic Build (``figure_build.request``: outfit change via the
  debounce timer, body change, piece ready, detail change, the auto-mesh hook
  on the pipeline, a deferred Build, the boot refit sweep's follow-ups) — held
  as the trigger ``build`` (its reason), Resume asks for it again;
* an automatic Build already running: the step in flight finishes, the Build
  stops before its next step and is held the same way (``state()['paused']``);
  its kept automatic follow-up is held too;
* automatic garment / hairstyle / footwear chain runs waiting in the
  character's garment FIFO (``garments``: queued by an automatic Build or an
  improvement) — they stay in the FIFO marked held, the worker skips them;
  a click's run (and a run a click attached to) is never held;
* the automatic outfit reference renders (``model_refs`` T-pose / pose kinds
  after an outfit change, off the pipeline) and the auto-mesh hook off the
  pipeline (``model3d.maybe_auto_generate_for_outfit``) and the mesh-part
  regeneration after a body-slot switch (``character_ops``) — held triggers;
* the Improvements queue's steps of types that generate media
  (``needs_media``) whose subject is the character — not submitted while
  paused, a submitted one goes back to pending;
* queued tasks submitted with ``character_hold`` (``npc_assets``) — not
  dequeued (``TaskQueue._dequeue``);
* automatic expression renders (``expression_regen.trigger_expression_
  generation``: a mood change, a scene image, a viewer's cache warm-up) —
  not started and not recorded: the next mood asks again.

What still runs: CPU work (the boot refit sweep, a fit-only refit, the
garment assembly, LOD builds, Improvements types with ``needs_media`` False),
everything a person clicks (a click never consults the pause), and a job that
already runs — it finishes.

Resume (``set_paused(name, False)``) lifts the hold: the held queue tasks and
garment runs run in their original order, then the held triggers are fired
again in the order they were first held. Cancel (``cancel``) drops ONE waiting
entry through the owning queue's own cancel — nothing of it has run, so
nothing is left half done.

A change of the pause or of the waiting list is signalled with the topic
``generation`` to the admins' connections (``sync_topics.Admins``) — a topic,
never data.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: The push topic of a pause change (``sync_topics.TOPICS``).
TOPIC = "generation"

#: A Build stopped by the pause before its next step (``figure_build``; the Figure tab shows it).
BUILD_PAUSED = "Paused before {step} — Resume builds the rest"
#: The Improvements step a Cancel in the Figure tab skipped (retryable in the Improvements tab).
IMPROVEMENT_CANCELLED = "Cancelled in the Figure tab while automatic generation was paused"

#: Labels of the Build reasons (``figure_build.request`` triggers).
BUILD_REASONS = {
    "outfit_change": "outfit change",
    "body_change": "new body",
    "piece_ready": "a piece became ready",
    "detail_change": "piece detail change",
    "superseded": "the figure changed meanwhile",
}

#: The tab each garment kind belongs to (``garment_set.garment_kind_of``).
GARMENT_TABS = {"hair": "Hairstyles", "clothing": "Wardrobe", "footwear": "Footwear"}


#: How often Resume fires one held trigger again before it gives up on it (a replay that raises stays held).
MAX_REPLAY_ATTEMPTS = 3
#: The payload field that counts the failed replays of a held trigger (the replays read only their own fields).
_ATTEMPTS = "_replay_attempts"

#: Held triggers whose record in ``task_queue.db`` failed: kept here instead (this process only), listed in the
#: waiting list and fired on Resume like the recorded ones. ``{character: {key: {key, label, payload}}}``.
_unrecorded: Dict[str, Dict[str, Dict[str, Any]]] = {}
_unrecorded_lock = threading.Lock()
_unreadable_logged = False


def _queue():
    from app.core.task_queue import get_task_queue
    return get_task_queue()


def is_paused(character_name: str) -> bool:
    """Whether the character's automatic generation is paused. Never raises.

    Fails CLOSED: the pause is mirrored in memory by the queue, so the only failure is that the queue cannot be
    opened at all — then the persisted pauses are unknown, and an unknown pause counts as paused (a trigger is
    held and fires on Resume) rather than letting automatic generation through behind the user's back."""
    global _unreadable_logged
    if not character_name:
        return False
    try:
        paused = _queue().character_paused(character_name)
    except Exception:  # noqa: BLE001 — a trigger check never breaks its caller
        if not _unreadable_logged:
            _unreadable_logged = True
            logger.warning("Generation pause state unreadable — automatic generation is held until it can be "
                           "read", exc_info=True)
        return True
    _unreadable_logged = False
    return paused


def _notify() -> None:
    from app.core import sync_topics
    sync_topics.notify(TOPIC, to=sync_topics.Admins())


def _record(character_name: str, key: str, label: str, payload: Optional[Dict[str, Any]]) -> None:
    """Record a held trigger in the queue; when that write fails, keep it in ``_unrecorded`` so it still fires
    on Resume (and shows in the waiting list). Never raises."""
    try:
        _queue().hold_trigger(character_name, key, label, payload)
    except Exception:  # noqa: BLE001 — kept in memory instead, never lost
        logger.warning("Held trigger %s of %s not recorded in the queue — kept in memory until Resume",
                       key, character_name, exc_info=True)
        with _unrecorded_lock:
            _unrecorded.setdefault(character_name, {})[key] = {"key": key, "label": label,
                                                               "payload": dict(payload or {})}
        return
    with _unrecorded_lock:
        # The recorded entry supersedes an in-memory one of the same key.
        _unrecorded.get(character_name, {}).pop(key, None)


def _unrecorded_of(character_name: str) -> List[Dict[str, Any]]:
    with _unrecorded_lock:
        return [dict(e) for e in (_unrecorded.get(character_name) or {}).values()]


def hold(character_name: str, key: str, label: str, payload: Optional[Dict[str, Any]] = None) -> bool:
    """A trigger's check: while the character is paused, record ``key`` as held (Resume fires it again through
    ``_REPLAY``) and return True — the caller starts nothing. False when not paused. Never raises.

    A failed record does not let the work through (the user paused it) and does not lose it either: the
    trigger is kept in memory (``_record``) and fires on Resume like a recorded one."""
    if not is_paused(character_name):
        return False
    _record(character_name, key, label, payload)
    logger.info("Automatic generation of %s paused — held: %s", character_name, label)
    try:
        _notify()
    except Exception:  # noqa: BLE001 — the signal is a courtesy, the hold stands
        logger.debug("Pause signal of %s not sent", character_name, exc_info=True)
    return True


def hold_build(character_name: str, reason: str) -> bool:
    """``hold`` for an automatic Build (``figure_build``): one entry per character, the newest reason."""
    return hold(character_name, "build", "Build (automatic) · " + BUILD_REASONS.get(reason, reason or "change"),
                {"reason": reason})


def notify_waiting(character_name: str) -> None:
    """The waiting list of a paused character changed outside ``hold`` (a held garment run)."""
    if is_paused(character_name):
        _notify()


# --- Replays (Resume) -----------------------------------------------------------------------------------------

def _replay_build(name: str, payload: Dict[str, Any]) -> None:
    from app.core import figure_build
    figure_build.request(name, str(payload.get("reason") or "outfit_change"))


def _replay_model_refs(name: str, payload: Dict[str, Any]) -> None:
    from app.core import model_refs
    kind = str(payload.get("kind") or "")
    if kind and model_refs.get_auto_kinds(name).get(kind):
        model_refs._fire_kinds(name, (kind,))


def _replay_auto_mesh(name: str, payload: Dict[str, Any]) -> None:
    from app.core import model3d
    model3d.maybe_auto_generate_for_outfit(name)


def _replay_mesh_part(name: str, payload: Dict[str, Any]) -> None:
    from app.core import character_ops
    character_ops._schedule_mesh_part_regeneration(name)


#: How Resume fires a held trigger again, by the key's head (``key.split(":")[0]``).
_REPLAY: Dict[str, Callable[[str, Dict[str, Any]], None]] = {
    "build": _replay_build,
    "model_refs": _replay_model_refs,
    "auto_mesh": _replay_auto_mesh,
    "mesh_part": _replay_mesh_part,
}


# --- The switch -----------------------------------------------------------------------------------------------

def set_paused(character_name: str, paused: bool) -> Dict[str, Any]:
    """The Figure tab's switch. Pausing never stops a running job. Resuming releases the held queue tasks and
    garment runs (their original order) and fires the held triggers again (the order they were first held).
    Returns ``state``."""
    queue = _queue()
    changed = queue.set_character_paused(character_name, bool(paused))
    if changed and not paused:
        _release(character_name)
    if changed:
        _notify()
    return state(character_name)


def _release(character_name: str) -> None:
    from app.core import garments
    try:
        garments.release_held(character_name)
    except Exception:  # noqa: BLE001 — one source never keeps the others held
        logger.exception("Held garment runs of %s not released", character_name)
    queue = _queue()
    recorded = queue.held_triggers(character_name)
    seen = {str(e["key"]) for e in recorded}
    entries = [(e, True) for e in recorded] + [(e, False) for e in _unrecorded_of(character_name)
                                                if str(e["key"]) not in seen]
    for entry, in_queue in entries:
        if is_paused(character_name):
            return   # paused again meanwhile: the rest stays held
        key = str(entry["key"])
        # Taken off the list BEFORE the replay (a replay that is held again re-records its own key), and put
        # back when the replay raises — a failed replay never loses the trigger.
        if in_queue:
            queue.drop_trigger(character_name, key)
        else:
            with _unrecorded_lock:
                (_unrecorded.get(character_name) or {}).pop(key, None)
        replay = _REPLAY.get(key.split(":", 1)[0])
        if replay is None:
            logger.warning("Held trigger %s of %s has no replay — dropped", key, character_name)
            continue
        payload = dict(entry.get("payload") or {})
        attempts = int(payload.pop(_ATTEMPTS, 0) or 0) + 1
        try:
            replay(character_name, payload)
            logger.info("Resume %s: %s fired again", character_name, entry.get("label") or key)
        except Exception:  # noqa: BLE001
            if attempts >= MAX_REPLAY_ATTEMPTS:
                logger.exception("Resume %s: %s not fired again (attempt %d of %d) — dropped", character_name,
                                 key, attempts, MAX_REPLAY_ATTEMPTS)
                continue
            logger.exception("Resume %s: %s not fired again (attempt %d of %d) — kept held for the next Resume",
                             character_name, key, attempts, MAX_REPLAY_ATTEMPTS)
            _record(character_name, key, str(entry.get("label") or key), {**payload, _ATTEMPTS: attempts})


# --- The waiting list -----------------------------------------------------------------------------------------

def _build_cost(character_name: str, held_items: set) -> Dict[str, Any]:
    """The automatic Build's first-attempt hub jobs now, without the chains that already wait as held garment
    runs (counted there)."""
    from app.core import figure_build
    try:
        steps = [s for s in figure_build.plan(character_name, explicit=False) if not (s.failed or s.manual)]
    except Exception:  # noqa: BLE001
        return {"jobs": None, "detail": "cost unknown"}
    steps = [s for s in steps if not (s.name in ("pieces", "hair") and s.item_id in held_items)]
    if not steps:
        return {"jobs": 0, "detail": "nothing to build now"}
    cost = figure_build.cost(character_name, steps)
    return {"jobs": cost.get("hub_jobs"), "detail": " · ".join(s.label for s in steps)}


def _garment_entries(character_name: str) -> List[Dict[str, Any]]:
    from app.core import garment_set, garments
    from app.models.inventory import get_item
    out = []
    for item_id in garments.held_items(character_name):
        item = get_item(item_id) or {}
        tab = GARMENT_TABS.get(str(garment_set.garment_kind_of(item) or ""), "Wardrobe") if item else "Wardrobe"
        try:
            estimate = garments.run_estimate(character_name, item_id)
        except Exception:  # noqa: BLE001
            estimate = {"hub_jobs": None, "note": ""}
        out.append({"id": f"garment:{item_id}", "source": "garment", "tab": tab,
                     "label": f"{tab} · {item.get('name') or item_id}",
                     "detail": str(estimate.get("note") or ""), "jobs": estimate.get("hub_jobs")})
    return out


def _task_label(task: Dict[str, Any]) -> str:
    if task.get("label"):
        return str(task["label"])
    return {"npc_assets": "NPC assets (portrait, outfit, 3D model)"}.get(str(task.get("task_type")),
                                                                        str(task.get("task_type") or "task"))


def _improvement_entries(character_name: str) -> List[Dict[str, Any]]:
    from app.core.improvements import engine
    out = []
    for row in engine.held_rows(character_name):
        out.append({"id": f"improvement:{row['improvement_id']}:{row['candidate_key']}", "source": "improvement",
                    "tab": "Improvements", "label": f"Improvements · {row['label']} · {row['candidate_label']}",
                    "detail": str(row.get("note") or ""), "jobs": row.get("hub_jobs")})
    return out


def waiting(character_name: str) -> List[Dict[str, Any]]:
    """Every waiting entry of the character, each ``{id, source, tab, label, detail, jobs}`` (``jobs`` None =
    unknown) — the held triggers in the order they were first held, then the garment FIFO's held runs in
    queue order, the held queue tasks in run order and the Improvements steps in queue order."""
    if not is_paused(character_name):
        return []   # nothing is held while the character runs freely
    queue = _queue()
    garments_held = _garment_entries(character_name)
    held_items = {e["id"].split(":", 1)[1] for e in garments_held}
    out: List[Dict[str, Any]] = []
    recorded = queue.held_triggers(character_name)
    seen = {str(e["key"]) for e in recorded}
    for entry in recorded + [e for e in _unrecorded_of(character_name) if str(e["key"]) not in seen]:
        key = str(entry["key"])
        row = {"id": f"trigger:{key}", "source": "trigger", "tab": "", "label": str(entry.get("label") or key),
               "detail": "", "jobs": None}
        if key == "build":
            row.update(_build_cost(character_name, held_items))
        out.append(row)
    out.extend(garments_held)
    for task in queue.held_tasks(character_name):
        out.append({"id": f"task:{task['task_id']}", "source": "task", "tab": "", "label": _task_label(task),
                    "detail": "", "jobs": None})
    out.extend(_improvement_entries(character_name))
    return out


def running(character_name: str) -> List[str]:
    """What of the character runs now and will finish (plain labels)."""
    from app.core import figure_build, garments
    out: List[str] = []
    build = figure_build.state(character_name)
    if build.get("running"):
        step = build.get("step") or {}
        out.append(f"Build · {step.get('label')}" if step.get("label") else "Build")
    current = garments.queue_state(character_name).get("queue_running")
    if current:
        from app.models.inventory import get_item
        out.append(f"Garment run · {(get_item(current) or {}).get('name') or current}")
    try:
        for task in _queue().running_tasks_of(character_name):
            if task.get("task_type") == figure_build.TRACK_TYPE:
                continue   # the Build, listed above
            out.append(_task_label(task))
    except Exception:  # noqa: BLE001
        logger.debug("Running tasks of %s not read", character_name, exc_info=True)
    return out


def state(character_name: str) -> Dict[str, Any]:
    """The Figure tab's pause block: ``{paused, since, waiting, running, resume_jobs, resume_unknown}`` —
    ``resume_jobs`` the known first-attempt hub jobs of the waiting entries, ``resume_unknown`` how many entries
    have no estimate. Never raises."""
    try:
        paused = is_paused(character_name)
        rows = waiting(character_name)
        known = [r["jobs"] for r in rows if r.get("jobs") is not None]
        return {"paused": paused, "since": _queue().character_paused_since(character_name) or None,
                "waiting": rows, "running": running(character_name),
                "resume_jobs": int(sum(int(j) for j in known)),
                "resume_unknown": len(rows) - len(known)}
    except Exception as e:  # noqa: BLE001 — the tab's poll never fails on it
        logger.exception("Pause state of %s failed", character_name)
        return {"paused": is_paused(character_name), "since": None, "waiting": [], "running": [],
                "resume_jobs": 0, "resume_unknown": 0, "error": str(e)}


# --- Cancel ---------------------------------------------------------------------------------------------------

def cancel(character_name: str, entry_id: str) -> Dict[str, Any]:
    """Cancel ONE waiting entry (``waiting``'s ``id``) through its queue's own cancel: a held trigger is
    forgotten (the change stays marked as pending, the Build button covers it), a held garment run leaves the
    FIFO (``garments.cancel_held``), a held task is cancelled (``TaskQueue.cancel_task`` — its hub operations
    go with it), an Improvements step is skipped (retryable in the Improvements tab). None of them has run, so
    nothing is half done. LookupError when the entry does not wait (any more). Returns ``state``."""
    source, _, rest = str(entry_id or "").partition(":")
    queue = _queue()
    done = False
    if source == "trigger" and rest:
        with _unrecorded_lock:
            in_memory = (_unrecorded.get(character_name) or {}).pop(rest, None) is not None
        done = queue.drop_trigger(character_name, rest) or in_memory
    elif source == "garment" and rest:
        from app.core import garments
        done = garments.cancel_held(character_name, rest) > 0
    elif source == "task" and rest:
        if any(t["task_id"] == rest for t in queue.held_tasks(character_name)):
            done = queue.cancel_task(rest)
    elif source == "improvement" and rest:
        from app.core.improvements import engine
        improvement_id, _, key = rest.partition(":")
        done = engine.cancel_held(character_name, improvement_id, key)
    if not done:
        raise LookupError("This job does not wait any more")
    logger.info("Waiting job %s of %s cancelled", entry_id, character_name)
    _notify()
    return state(character_name)
