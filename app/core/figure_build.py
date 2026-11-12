"""The Build — ONE action per character that brings the delivered figure to
the wanted one (plan ``docs/superpowers/plans/2026-11-12-unified-worn-
pieces.md`` Task 7; spec ``docs/superpowers/specs/2026-11-12-unified-worn-
pieces-design.md`` "The flow when Build runs", rulings 1–2).

``plan`` lists exactly the missing steps for what is worn, in the fixed
order ``STEP_ORDER`` (a step with nothing to do is not in it):

1. ``plain_body`` — the plain body is missing or was rendered with older
   prompts (``base_body.base_refresh_plan(missing=True)``): its views, then
   its mesh run (``generate_base_images`` / ``generate_base_model``).
2. ``interim`` — the wanted figure needs a shape or an own mesh that is not
   built (the delivered figure paints a piece meanwhile, ``Figure.interim``)
   and no outfit model of that interim figure is stored: its views
   (``generate_dressed_images``) and its outfit model (ruling 2: shown
   painted until the real thing exists; scheduled FIRST, counted in the cost).
3. ``shape`` — the wanted meshed shape is not stored
   (``base_body.prepare_shape``).
4. ``pieces`` — one step per own-mesh piece whose chain has something to
   run (``garments.run_estimate``), run through the character's garment
   FIFO (``garments.run_queued``).
5. ``hair`` — HairDeck hair whose chain has something to run
   (``garment_hair.ensure_hair_item`` + ``run_queued``).
6. ``texture`` — the wanted painted set: its views, when they are missing
   (the paint itself is Blender on the CPU, done by the assembly).
7. ``fits`` — the CPU refits (``garment_refit.refit_character``, tracked).
8. ``assemble`` — the outfit model of the figure delivered THEN, built from
   whatever is built (the interim rule), then the garment assembly
   (``garment_assembly.schedule``).

A rebuilt plain body re-renders the views every other image is edited from:
with ``plain_body`` in a MANUAL plan every view counts as missing and a stored
shape as not stored.

Ruling 8a: an AUTOMATIC Build never spends base-body hub jobs. The
``plain_body`` step is listed in every plan that needs it, marked ``manual``
("Base body outdated — Build to refresh" / "No base body yet — Build to
create", ``figure.BASE_OUTDATED`` / ``figure.BASE_MISSING``) with its cost, and only a
manual Build (or the ``base_refresh`` improvement) runs it. An automatic plan
builds the rest on the stored plain body (no view counts as missing because
of it); without any plain body it has nothing to build on and plans nothing
else.

Cost (``cost``) reuses the producers' own arithmetic, never a second table:
the plain body = ``base_rebuild_steps``; interim / texture =
``base_body.dressed_view_jobs()`` when their views are missing, else 0;
shape = views (when missing) + ``model3d.mesh_hub_stages``; pieces / hair =
``run_estimate``; fits / assemble = 0. ``hub_jobs`` None as soon as one step
is unknown (the note says which).

The run (``start``): one FIFO per character (a deque + one worker thread). A
``start`` while a run goes keeps ONE follow-up (repeated calls keep one);
every run re-plans at its start, so a follow-up with nothing left ends at
once. Each run, from its plan to its last step, holds the character's
``build_lock``: the Figure tab's Delete of a stored body or texture
(``figure.delete_stored``) takes it too and re-judges deletability under it,
so a Build never plans on a body that is deleted under it (Ruling 10a). Model work (plain body, interim, shape,
texture, assemble) holds ``model3d.generation_slot``. A failed step is
recorded (``failed[step]``; for ``pieces`` the first failing piece, every
failing piece under ``items``) and skips only the steps whose ``DEPENDS``
name it; the others run. The run shows as one tracked task "Build · <name>
(<i>/<n> <label>)".

Automatic (Task 8; rulings 7a, 7b): ``request(character, trigger)`` is how the
triggers of today reach the Build — the outfit change (``model_refs``'s
debounce timer), the body change (``garments.after_base_model``), a piece
ready (``base_body.after_mesh_item_ready``), a detail change
(``base_body.after_piece_detail_change``), the auto hook
(``model3d.maybe_auto_generate_for_outfit``). It starts an AUTOMATIC Build
only on the pipeline with "Build automatically" on (``auto_build_on``:
profile ``figure_auto_build``, absent = on, and the world switch
``model_refs._enabled()``); otherwise the change only stays marked
(``figure.pending_changes``). A trigger during a run coalesces into the ONE
follow-up (``start``), never interleaving steps. A mode change of an item
(``inventory.update_item``) calls nothing — its wearers are listed by
``wearers`` and built on request (the Items' "Build for them").

A garment chain that failed for its current fsig (``garments.cached_failure``)
is listed as "failed — Retry" with 0 counted jobs (``Step.failed``). An
automatic Build never runs it (the failure is reported, nothing spent); a
manual one (``start(…, automatic=False)``: the Build button / Retry, "Build
for them", "Build current outfit") clears that failure and runs the chain
from the failed step (``garments.run_queued(explicit=True)``; the chain
re-judges stored attempts under the current gate versions first).
"""
import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STEP_ORDER = ("plain_body", "interim", "shape", "pieces", "hair", "texture", "fits", "assemble")
#: What a step needs: a failed (or skipped) step skips every step naming it here.
DEPENDS = {"interim": {"plain_body"}, "shape": {"plain_body"}, "pieces": {"plain_body"},
           "hair": {"plain_body"}, "texture": {"plain_body", "shape"}, "fits": {"plain_body"},
           "assemble": {"plain_body"}}
#: Steps that hold the character's 3D generation slot (model work).
SLOT_STEPS = frozenset({"plain_body", "interim", "shape", "texture", "assemble"})

#: ``start`` / the route's 409 off the pipeline.
OFF_PIPELINE = "Off the figure pipeline — the character is not on the base-body pipeline"
#: Task-queue row type of a Build.
TRACK_TYPE = "figure_build"


#: The plan label's tail of a chain that failed for its current fsig (ruling 7a).
FAILED_SUFFIX = " — failed — Retry"
#: What replaces it while a manual Build retries that chain (T8 concern 7).
RETRY_SUFFIX = " — retrying"


@dataclass(frozen=True)
class Step:
    name: str            # one of STEP_ORDER
    label: str           # "Plain body: views 4 + mesh + rig", "Own mesh · Tailored Black"
    jobs: Optional[int]  # first-attempt hub jobs, None = unknown
    item_id: str = ""
    #: A garment chain that failed for its current fsig (ruling 7a): the cached
    #: error; an automatic Build skips the step, a manual one retries it.
    failed: str = ""
    #: Base-body work (ruling 8a): why it is listed; only a manual Build runs it.
    manual: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "label": self.label, "jobs": self.jobs, "item_id": self.item_id,
                "failed": self.failed, "manual": self.manual}

    def running_label(self, explicit: bool) -> str:
        """The label while the step runs: a cached chain failure that a manual
        Build retries reads "… — retrying", not "… — failed — Retry"."""
        if explicit and self.failed and self.label.endswith(FAILED_SUFFIX):
            return self.label[:-len(FAILED_SUFFIX)] + RETRY_SUFFIX
        return self.label


# --- Plan ---------------------------------------------------------------------------

def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _item_name(item_id: str) -> str:
    from app.models import inventory
    return str((inventory.get_item(item_id) or {}).get("name") or item_id)


def on_pipeline(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the character builds a figure at all (``base_body.is_base_pipeline``)."""
    from app.core import base_body
    return base_body.is_base_pipeline(character_name, profile=_profile_of(character_name, profile))


def _model_figure(character_name: str, signature: str):
    """The figure the stored outfit model of ``signature`` was built as
    (``figure.built_figure``), None without a current model or a record."""
    from app.core import figure, model3d
    path = model3d.find_model3d(character_name, signature)
    return figure.built_figure(model3d._read_sidecar(path)) if path is not None else None


def _views_missing(character_name: str, fig, signature: str) -> bool:
    """Whether a ``dressed_views()`` view of ``fig`` is not stored for ``signature``."""
    from app.core import base_body
    return any(base_body.dressed_image(character_name, v, signature, fig.bsig, fig=fig) is None
               for v in base_body.dressed_views())


def _views_label(what: str, views: int) -> str:
    return f"{what}: views {views}" if views else f"{what}: paint on the CPU"


def _chain_step(character_name: str, name: str, item_id: str, label: str,
                profile: Dict[str, Any]) -> Optional[Step]:
    """A garment chain step (``pieces`` / ``hair``) when its chain has something to run or
    its cost is unknown (``run_estimate``); a chain that failed for its current fsig
    (``garments.cached_failure``) as "failed — Retry" with 0 jobs (ruling 7a)."""
    from app.core import garments
    failure = garments.cached_failure(character_name, item_id, profile=profile)
    if failure is not None:
        error = str(failure.get("error") or "chain failed")
        if failure.get("step"):
            error = f"{failure['step']} — {error}"
        return Step(name, f"{label}{FAILED_SUFFIX}", 0, item_id, failed=error)
    estimate = garments.run_estimate(character_name, item_id, profile=profile)
    if estimate.get("hub_jobs") is None:
        return Step(name, f"{label} ({estimate.get('note') or 'cost unknown'})", None, item_id)
    if not estimate.get("steps"):
        return None
    return Step(name, label, int(estimate["hub_jobs"]), item_id)


def _hair_step(character_name: str, profile: Dict[str, Any]) -> Optional[Step]:
    """The HairDeck chain of the hair item; without an item yet (``ensure_hair_item``
    makes it in the run) the method's chain from the start (``garments.HUB_JOBS``)."""
    from app.core import garment_hair, garments
    method = garment_hair.hair_method(character_name, profile=profile)
    label = f"Hair · {'HairDeck' if method == 'hairdeck' else method}"
    item = garment_hair.find_hair_item(character_name, profile)
    if item and item.get("id"):
        return _chain_step(character_name, "hair", str(item["id"]), label, profile)
    if not garment_hair.hair_description(character_name, profile=profile):
        return None  # bald: no hair item to make (``ensure_hair_item`` refuses it), nothing to build
    costs = garments.HUB_JOBS.get(f"hair:{method}")
    if costs is None:
        return Step("hair", f"{label} (no cost table for {method})", None)
    return Step("hair", label, sum(costs.values())) if costs else None


def _runnable(steps: List[Step], explicit: bool) -> List[Step]:
    """The steps that do work: a cached chain failure (ruling 7a) and the
    plain body (ruling 8a) only in a manual Build."""
    return [s for s in steps if explicit or not (s.failed or s.manual)]


def plan(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
         explicit: bool = True) -> List[Step]:
    """The steps a Build runs now, in ``STEP_ORDER`` (module docstring).
    ``[]`` off the pipeline or when the delivered figure is the wanted one and
    built. ``explicit`` (default — what the Build button runs, the plan the UI
    shows): a manual Build; False: an automatic one. A chain that failed for
    its fsig is listed with ``failed`` and 0 jobs; it makes the fits and the
    assembly follow only when ``explicit`` (a manual Build retries it). The
    plain body is listed with ``manual`` in both; only an explicit plan builds
    on its refresh (ruling 8a). Read-only."""
    from app.core import base_body, figure, garment_refit, model3d
    profile = _profile_of(character_name, profile)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        return []
    wanted, delivered = figure._delivered(character_name, profile=profile)
    signature, bsig = wanted.signature, wanted.bsig
    steps: List[Step] = []

    refresh = base_body.base_refresh_plan(character_name, profile=profile, missing=True)
    stale = bool(refresh.get("views") or refresh.get("model"))
    if stale:
        rebuild = base_body.base_rebuild_steps(character_name, refresh)
        views = sum(jobs for step, jobs in rebuild if step.startswith("view "))
        parts = ([f"views {views}"] if views else []) + [step for step, _jobs in rebuild
                                                         if not step.startswith("view ")]
        no_base = refresh.get("reason") == "missing"   # no stored front or no base model
        steps.append(Step("plain_body", "Plain body: " + " + ".join(parts),
                          sum(jobs for _step, jobs in rebuild),
                          manual=figure.BASE_MISSING if no_base else figure.BASE_OUTDATED))
        if no_base and not explicit:
            return steps  # ruling 8a: nothing to build on until a manual Build makes it
    # Ruling 8a: only a manual Build refreshes the plain body; an automatic one builds on the stored one.
    rebased = stale and explicit

    built = _model_figure(character_name, signature)
    set_jobs = base_body.dressed_view_jobs()
    if delivered.interim and (rebased or built is None or built.as_dict() != delivered.as_dict()):
        views = set_jobs if rebased or _views_missing(character_name, delivered, signature) else 0
        steps.append(Step("interim", _views_label("Interim texture", views), views))

    meshed = not figure.is_plain(wanted.shape)
    if meshed and (rebased or not figure._shape_stored(character_name, wanted.shape, bsig)):
        views_missing = rebased or any(base_body.shape_view(character_name, v, wanted.shape, bsig) is None
                                       for v in base_body.dressed_views())
        stages = model3d.mesh_hub_stages(character_name, wanted.shape)
        views = set_jobs if views_missing else 0
        steps.append(Step("shape", "Body shape: " + " + ".join(([f"views {views}"] if views else []) + stages),
                          views + len(stages)))

    for item_id in wanted.own:
        step = _chain_step(character_name, "pieces", item_id, f"Own mesh · {_item_name(item_id)}", profile)
        if step is not None:
            steps.append(step)

    if wanted.hair == figure.HAIR_HAIRDECK:
        step = _hair_step(character_name, profile)
        if step is not None:
            steps.append(step)

    if wanted.texture:
        shape_built = not any(s.name == "shape" for s in steps)
        views_missing = rebased or not shape_built or _views_missing(character_name, wanted, signature)
        if views_missing or built is None or built.texture != wanted.texture or built.shape != wanted.shape:
            views = set_jobs if views_missing else 0
            steps.append(Step("texture", _views_label("Texture", views), views))

    grafted = bool(wanted.own) or wanted.hair == figure.HAIR_HAIRDECK
    work = _runnable(steps, explicit)
    if grafted and (any(s.name in ("plain_body", "shape", "pieces", "hair") for s in work)
                    or garment_refit.work_count(character_name, profile=profile) > 0):
        steps.append(Step("fits", "Fits on the CPU", 0))

    if _runnable(steps, explicit) or built is None or built.as_dict() != delivered.as_dict():
        steps.append(Step("assemble", "Assemble the figure", 0))
    return steps


def cost(character_name: str, steps: Optional[List[Step]] = None) -> Dict[str, Any]:
    """``{hub_jobs, steps: [Step.as_dict()], note}`` of ``steps`` (default:
    ``plan``) on their first attempts; ``hub_jobs`` None when a step's cost
    is unknown — the note names those steps. Never raises."""
    try:
        steps = plan(character_name) if steps is None else steps
    except Exception as e:  # noqa: BLE001 — an estimate, never a failure
        logger.warning("Build cost of %s not computable: %s", character_name, e)
        return {"hub_jobs": None, "steps": [], "note": f"cost unknown — {e}"}
    unknown = [s.label for s in steps if s.jobs is None]
    total = None if unknown else sum(int(s.jobs or 0) for s in steps)
    if unknown:
        note = "cost unknown — " + "; ".join(unknown)
    elif steps:
        note = f"{total} hub jobs (first attempts)"
    else:
        note = "nothing to build"
    return {"hub_jobs": total, "steps": [s.as_dict() for s in steps], "note": note}


# --- Run ----------------------------------------------------------------------------

_lock = threading.Lock()
_queues: Dict[str, Deque[Tuple[str, bool]]] = {}  # character -> follow-up (reason, automatic), at most one
_active: set = set()                      # characters whose worker thread is alive
_current: Dict[str, Dict[str, Any]] = {}  # character -> the run in flight
_last: Dict[str, Dict[str, Any]] = {}     # character -> the last run that had steps
_build_locks: Dict[str, threading.Lock] = {}  # character -> held by a run from its plan to its last step


def build_lock(character_name: str) -> threading.Lock:
    """The character's Build lock: a run holds it from its plan to its last
    step (``_worker``); ``figure.delete_stored`` takes it without waiting and
    refuses while a Build holds it (Ruling 10a)."""
    with _lock:
        return _build_locks.setdefault(character_name, threading.Lock())


def _keep_followup_locked(character_name: str, reason: str, automatic: bool) -> None:
    """Keep ONE follow-up (caller holds ``_lock``): a manual request replaces an
    automatic one (it may retry cached failures), never the other way round."""
    queue = _queues.setdefault(character_name, deque())
    if not queue:
        queue.append((reason, automatic))
    elif queue[0][1] and not automatic:
        queue[0] = (reason, automatic)


def start(character_name: str, *, reason: str, automatic: bool = False) -> Dict[str, Any]:
    """Start a Build of the character: ``{"status": "started"}`` (the worker
    took it), ``"queued"`` (a run goes — ONE follow-up is kept, repeated calls
    keep one; it re-plans when it starts), ``"current"`` (nothing to build —
    for an ``automatic`` Build also when only cached chain failures are left,
    which only a manual Build retries), ``"off"`` (off the pipeline, with
    ``reason``). ``automatic``: started by a trigger (``request``), not by a
    click (ruling 7a)."""
    if not on_pipeline(character_name):
        return {"status": "off", "reason": OFF_PIPELINE}
    with _lock:
        if character_name in _active:
            _keep_followup_locked(character_name, reason, automatic)
            return {"status": "queued"}
    if not _runnable(plan(character_name, explicit=not automatic), not automatic):
        return {"status": "current"}
    with _lock:
        if character_name in _active:  # another start won the race
            _keep_followup_locked(character_name, reason, automatic)
            return {"status": "queued"}
        _queues[character_name] = deque([(reason, automatic)])
        _active.add(character_name)
        _current[character_name] = {"reason": reason, "step": None, "steps": []}
    threading.Thread(target=_worker, args=(character_name,), daemon=True,
                     name=f"figure-build-{character_name}").start()
    logger.info("Build %s started (%s%s)", character_name, reason, ", automatic" if automatic else "")
    return {"status": "started"}


# --- Automatic ------------------------------------------------------------------------

#: Profile key of the Figure tab's "Build automatically" (absent = on).
AUTO_BUILD_KEY = "figure_auto_build"


def auto_build_on(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether triggers start the character's Build: the profile's
    ``figure_auto_build`` (absent = on) and the world switch of the automatic
    outfit renders (``model_refs._enabled()``, as for the T-pose pass before)."""
    from app.core import model_refs
    if not model_refs._enabled():
        return False
    return _profile_of(character_name, profile).get(AUTO_BUILD_KEY) is not False


def set_auto_build(character_name: str, enabled: bool) -> bool:
    """Store "Build automatically" (profile read-modify-write under the
    character's profile lock). Switching it off never stops a run going.
    The save's bool."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        profile[AUTO_BUILD_KEY] = bool(enabled)
        return bool(save_character_profile(character_name, profile))


def request(character_name: str, trigger: str) -> bool:
    """A trigger's way to the Build (module docstring): on the pipeline with
    ``auto_build_on`` → an automatic ``start(reason=trigger)``; True when it
    started or was kept as the follow-up. Else False — the change stays in
    ``figure.pending_changes``. Never raises."""
    try:
        profile = _profile_of(character_name, None)
        if not on_pipeline(character_name, profile=profile) or not auto_build_on(character_name, profile=profile):
            logger.debug("Build %s not requested (%s): off the pipeline or not automatic", character_name, trigger)
            return False
        return start(character_name, reason=trigger, automatic=True).get("status") in ("started", "queued")
    except Exception:  # noqa: BLE001 — a trigger never breaks its caller
        logger.exception("Build request of %s (%s) failed", character_name, trigger)
        return False


def wearers(item_id: str) -> List[str]:
    """The characters on the pipeline whose ``equipped_pieces`` hold
    ``item_id`` — every stored character, dormant and pooled ones included
    (they keep their figure). Sorted by name."""
    from app.models.character import get_character_profile, list_available_characters
    out: List[str] = []
    for name in list_available_characters(include_pooled=True):
        try:
            profile = get_character_profile(name) or {}
        except Exception:  # noqa: BLE001 — one unreadable profile never hides the rest
            logger.warning("Profile of %s unreadable for the wearers of %s", name, item_id, exc_info=True)
            continue
        if item_id not in (profile.get("equipped_pieces") or {}).values():
            continue
        if on_pipeline(name, profile=profile):
            out.append(name)
    return sorted(out, key=str.lower)


def state(character_name: str) -> Dict[str, Any]:
    """``{running, step, queued, failed, skipped, reason, finished_at}``:
    ``step`` the step in flight (``{name, label, jobs, item_id, index,
    count}``), ``queued`` the follow-ups kept (0 or 1); ``failed`` /
    ``skipped`` / ``finished_at`` of the last run that had steps."""
    with _lock:
        running = character_name in _active
        current = dict(_current.get(character_name) or {})
        queued = len(_queues.get(character_name) or ())
        last = dict(_last.get(character_name) or {})
    return {"running": running, "step": current.get("step") if running else None, "queued": queued,
            "failed": dict(last.get("failed") or {}), "skipped": list(last.get("skipped") or []),
            "reason": current.get("reason") if running else last.get("reason"),
            "finished_at": last.get("finished_at")}


def _worker(character_name: str) -> None:
    while True:
        with _lock:
            queue = _queues.get(character_name)
            if not queue:
                _active.discard(character_name)
                _current.pop(character_name, None)
                return
            reason, automatic = queue.popleft()
            _current[character_name] = {"reason": reason, "step": None, "steps": []}
        try:
            with build_lock(character_name):
                _run(character_name, reason, automatic=automatic)
        except Exception:  # noqa: BLE001 — a worker reports, never raises
            logger.exception("Build %s (%s) failed", character_name, reason)


def _tracked(character_name: str, label: str):
    """A task-queue display row (``track_start``); (queue, id) or (None, "")."""
    try:
        from app.core.task_queue import get_task_queue
        queue = get_task_queue()
        return queue, queue.track_start(TRACK_TYPE, label, agent_name=character_name, start_running=True)
    except Exception:  # noqa: BLE001 — the display row is optional
        logger.debug("Build of %s not tracked", character_name, exc_info=True)
        return None, ""


def _run(character_name: str, reason: str, *, automatic: bool = False) -> None:
    """One Build: re-plan, then every step in order (module docstring). An
    ``automatic`` run reports a cached chain failure without running it; a
    manual one retries it."""
    from app.core.timeutils import utc_now_iso
    explicit = not automatic
    steps = plan(character_name, explicit=explicit)
    if automatic:
        # Ruling 8a: the plain body stays listed (the UI's pending change), an automatic run never builds it.
        steps = [s for s in steps if not s.manual]
    if not _runnable(steps, explicit):
        logger.info("Build %s (%s): nothing to build", character_name, reason)
        return
    with _lock:
        _current[character_name] = {"reason": reason, "step": None, "steps": [s.as_dict() for s in steps]}
    queue, task_id = _tracked(character_name, f"Build · {character_name} (0/{len(steps)})")
    failed: Dict[str, Dict[str, Any]] = {}
    skipped: List[str] = []
    try:
        for index, step in enumerate(steps, 1):
            shown = step.running_label(explicit)
            label = f"Build · {character_name} ({index}/{len(steps)} {shown})"
            with _lock:
                _current[character_name]["step"] = {**step.as_dict(), "label": shown, "index": index,
                                                    "count": len(steps)}
            if queue is not None and task_id:
                try:
                    queue.track_update_label(task_id, label)
                except Exception:  # noqa: BLE001
                    logger.debug("Build track %s not relabelled", task_id, exc_info=True)
            if DEPENDS.get(step.name, set()) & (set(failed) | set(skipped)):
                if step.name not in skipped:
                    skipped.append(step.name)
                logger.info("Build %s: %s skipped — it needs %s", character_name, step.label,
                            sorted(DEPENDS[step.name] & (set(failed) | set(skipped))))
                continue
            if step.failed and automatic:
                # Ruling 7a: an automatic Build never spends a chain that failed for this input.
                error = step.failed
            else:
                error = _run_step(character_name, step, explicit)
            if error:
                logger.warning("Build %s: %s failed: %s", character_name, step.label, error)
                entry = failed.get(step.name)
                if entry is None:
                    failed[step.name] = {"error": error, "item_id": step.item_id}
                else:
                    entry.setdefault("items", {entry["item_id"]: entry["error"]})[step.item_id] = error
            else:
                logger.info("Build %s: %s done", character_name, step.label)
    finally:
        with _lock:
            _last[character_name] = {"failed": failed, "skipped": skipped, "reason": reason,
                                     "finished_at": utc_now_iso()}
        if queue is not None and task_id:
            try:
                queue.track_finish(task_id, error="; ".join(f"{k}: {v['error']}" for k, v in failed.items()))
            except Exception:  # noqa: BLE001
                logger.debug("Build track %s not finished", task_id, exc_info=True)


# --- Steps (each returns "" or the error) --------------------------------------------

def _run_step(character_name: str, step: Step, explicit: bool) -> str:
    """Run one step: "" or its error (an exception is the error)."""
    from app.core import model3d
    try:
        if step.name in SLOT_STEPS:
            with model3d.generation_slot(character_name):
                return _RUNNERS[step.name](character_name, step, explicit)
        return _RUNNERS[step.name](character_name, step, explicit)
    except Exception as e:  # noqa: BLE001 — the step failed, the run goes on
        logger.exception("Build %s: %s failed", character_name, step.label)
        return str(e) or type(e).__name__


def _now(character_name: str):
    """``(profile, wanted, delivered, items)`` judged now."""
    from app.core import figure
    profile = _profile_of(character_name, None)
    wanted, delivered = figure._delivered(character_name, profile=profile)
    return profile, wanted, delivered, figure._items_of(profile, None)


def _run_plain_body(character_name: str, step: Step, explicit: bool = False) -> str:
    """The plain body's views (all four in one run when the front is among them — the
    others edit the new front — else each view alone), then its model; forced."""
    from app.core import base_body
    refresh = base_body.base_refresh_plan(character_name, missing=True)
    views = list(refresh.get("views") or ())
    if views:
        if "front" in views:
            results = base_body.generate_base_images(character_name, force=True)
        else:
            results = {}
            for view in views:
                results.update(base_body.generate_base_images(character_name, view=view, force=True))
        missing = [v for v in views if not results.get(v)]
        if missing:
            status = base_body.base_status(character_name)
            error = next((status[v].get("error") for v in missing if (status.get(v) or {}).get("error")), None)
            return f"views {', '.join(missing)} — {error or 'render failed'}"
    if refresh.get("model") or views:
        result = base_body.generate_base_model(character_name, force=True)
        if not result.get("ok"):
            return str(result.get("error") or "Base model generation failed")
    return ""


def _outfit_model(character_name: str, signature: str) -> str:
    """The outfit model of the figure delivered now, without the shape
    preparation (the Build's own steps make shapes). Not forced: a model of
    exactly this figure is kept, and a texture painted before is reused
    (``base_body.stored_texture_body``) — an automatic Build runs on every
    trigger, it must not repaint what is stored (Task 8)."""
    from app.core import model3d
    result = model3d.generate_for_current_outfit(character_name, signature=signature, prepare=False)
    return "" if result.get("ok") else str(result.get("error") or "Outfit model build failed")


def _dressed(character_name: str, wanted) -> None:
    """The views of the figure delivered NOW for the worn outfit (missing ones only)."""
    from app.core import base_body
    _profile, _w, _d, items = _now(character_name)
    base_body.generate_dressed_images(character_name, pieces=dict(wanted.pieces), items=items,
                                      signature=wanted.signature)


def _run_interim(character_name: str, step: Step, explicit: bool = False) -> str:
    """The interim figure: its views, then its outfit model — served while the
    shape / own meshes are built (ruling 2)."""
    _profile, wanted, _delivered, _items = _now(character_name)
    _dressed(character_name, wanted)
    return _outfit_model(character_name, wanted.signature)


def _run_shape(character_name: str, step: Step, explicit: bool = False) -> str:
    from app.core import base_body, figure
    _profile, wanted, _delivered, items = _now(character_name)
    if figure.is_plain(wanted.shape):
        return ""
    result = base_body.prepare_shape(character_name, wanted, items=items, signature=wanted.signature)
    if result is None or result.get("ok"):
        return ""
    return str(result.get("error") or "Body shape build failed")


def _chain(character_name: str, item_id: str, explicit: bool) -> str:
    """The item's chain through the character's garment FIFO; ``explicit`` (a
    manual Build) clears a cached failure first and retries it (ruling 7a)."""
    from app.core import garments
    runs = garments.run_queued(character_name, [item_id], explicit=True) if explicit else \
        garments.run_queued(character_name, [item_id])
    result = runs.get(item_id) or {}
    if result.get("ok"):
        return ""
    error = str(result.get("error") or "chain failed")
    return f"{result['step']} — {error}" if result.get("step") else error


def _run_pieces(character_name: str, step: Step, explicit: bool = False) -> str:
    return _chain(character_name, step.item_id, explicit)


def _run_hair(character_name: str, step: Step, explicit: bool = False) -> str:
    from app.core import garment_hair
    try:
        item_id = garment_hair.ensure_hair_item(character_name)
    except (ValueError, RuntimeError) as e:
        return str(e)
    return _chain(character_name, item_id, explicit)


def _run_texture(character_name: str, step: Step, explicit: bool = False) -> str:
    """The views of the painted set on the shape delivered now (the paint is the assembly's)."""
    _profile, wanted, _delivered, _items = _now(character_name)
    _dressed(character_name, wanted)
    return ""


def _run_fits(character_name: str, step: Step, explicit: bool = False) -> str:
    from app.core import garment_refit
    done = garment_refit.tracked(character_name, lambda: garment_refit.refit_character(character_name))
    if done is None:
        logger.info("Build %s: refits skipped — a garment chain of the character runs", character_name)
    return ""


def _run_assemble(character_name: str, step: Step, explicit: bool = False) -> str:
    """The outfit model of the figure delivered now (whatever is built), then the assembly."""
    from app.core import base_body, garment_assembly
    _profile, wanted, _delivered, _items = _now(character_name)
    views = base_body.ensure_figure_views(character_name, wanted.signature)
    if views is not None and not views.get("ok"):
        return str(views.get("error") or "views failed")
    error = _outfit_model(character_name, wanted.signature)
    if not error:
        garment_assembly.schedule(character_name, wanted.signature)
    return error


_RUNNERS: Dict[str, Callable[[str, Step, bool], str]] = {
    "plain_body": _run_plain_body, "interim": _run_interim, "shape": _run_shape, "pieces": _run_pieces,
    "hair": _run_hair, "texture": _run_texture, "fits": _run_fits, "assemble": _run_assemble}


# --- The Figure tab's payload ----------------------------------------------------------

def _hair_row(character_name: str, profile: Dict[str, Any], wanted, delivered,
              failed: Dict[str, Dict[str, Any]], running: bool) -> Dict[str, Any]:
    from app.core import figure, garment_hair
    mode = garment_hair.hair_method(character_name, profile=profile)
    if (failed.get("hair") or {}).get("error"):
        return {"mode": mode, "state": "failed", "note": str(failed["hair"]["error"])}
    if wanted.hair == delivered.hair:
        return {"mode": mode, "state": "ready", "note": ""}
    shown = "in the body" if delivered.hair == figure.HAIR_BODY else "bald"
    return {"mode": mode, "state": "building" if running else "pending",
            "note": f"Shown {shown} until its HairDeck mesh is built"}


def _worn_rows(character_name: str, wanted, delivered, failed: Dict[str, Dict[str, Any]],
               running: bool) -> List[Dict[str, Any]]:
    from app.core import garment_set
    from app.models import inventory
    piece_failures: Dict[str, str] = {}
    entry = failed.get("pieces") or {}
    if entry:
        piece_failures = dict(entry.get("items") or {entry.get("item_id"): entry.get("error")})
    rows: List[Dict[str, Any]] = []
    seen = set()
    for slot, item_id in sorted(wanted.pieces.items()):
        if item_id in seen:
            continue
        seen.add(item_id)
        item = inventory.get_item(item_id) or {}
        want, have = wanted.state_of(item_id), delivered.state_of(item_id)
        failure = str(piece_failures.get(item_id) or "")
        if failure:
            state = "failed"
        elif want == have:
            state = "ready"
        elif running:
            state = "building"
        elif item_id in delivered.left_out:
            state = "left_out"
        elif item_id in delivered.interim:
            state = "interim"
        else:
            state = "pending"
        rows.append({"slot": slot, "item_id": item_id, "name": str(item.get("name") or item_id),
                     "mode": garment_set.mesh_mode_of(item) or garment_set.PAINTED, "state": state,
                     "note": (delivered.interim.get(item_id) or delivered.left_out.get(item_id)
                              or delivered.notes.get(item_id) or ""),
                     "interim": item_id in delivered.interim, "left_out": delivered.left_out.get(item_id) or "",
                     "failure": failure})
    return rows


def _with_cached_failures(failed: Dict[str, Dict[str, Any]], steps: List[Step]) -> Dict[str, Dict[str, Any]]:
    """The last run's ``failed`` plus the planned chains that failed for their
    current fsig (``Step.failed``), in the same shape — a cached failure shows
    as "failed — Retry" before any Build ran."""
    out = {name: {**entry, **({"items": dict(entry["items"])} if entry.get("items") else {})}
           for name, entry in failed.items()}
    for step in steps:
        if not step.failed:
            continue
        entry = out.get(step.name)
        if entry is None:
            out[step.name] = {"error": step.failed, "item_id": step.item_id}
        elif step.item_id != entry.get("item_id"):
            entry.setdefault("items", {entry.get("item_id"): entry.get("error")}).setdefault(step.item_id,
                                                                                           step.failed)
    return out


def _served_url(character_name: str) -> Optional[str]:
    from urllib.parse import quote
    from app.core import model3d
    try:
        return model3d.versioned_model_urls(
            character_name, f"/characters/{quote(character_name, safe='')}/model3d/file").get("url")
    except Exception:  # noqa: BLE001 — the preview is optional
        logger.debug("Served model URL of %s unreadable", character_name, exc_info=True)
        return None


def _item_jobs(steps: List[Step], name: str, item_id: str) -> Optional[int]:
    """The planned hub jobs of a piece's (``pieces``, by item) or the hair's
    chain step: 0 when nothing of it is planned, None when unknown."""
    for step in steps:
        if step.name == name and (not item_id or step.item_id == item_id):
            return step.jobs
    return 0


def _plain_jobs(character_name: str, bsig: str) -> Dict[str, Any]:
    """What the single actions on the plain body cost (the Figure tab's Body
    details write it under each button): ``view`` (a side or back view),
    ``front`` (with the skin detail step while it is on), ``model`` (its mesh
    run, ``model3d.mesh_hub_stages``) and ``after_front`` (what the next
    Build then rebuilds after a new front or skin step: the three other
    views, which edit the front, and the model). None when not computable."""
    from app.core import base_body, base_skin, model3d
    try:
        others = [v for v in base_body.BASE_VIEWS if v != "front"]
        return {"view": base_body.BASE_VIEW_JOBS,
                "front": base_body.BASE_VIEW_JOBS + (base_body.SKIN_STEP_JOBS if base_skin.enabled() else 0),
                "model": len(model3d.mesh_hub_stages(character_name, bsig)),
                "after_front": sum(jobs for _step, jobs in base_body.base_rebuild_steps(
                    character_name, {"signature": bsig, "views": others, "model": True}))}
    except Exception:  # noqa: BLE001 — an estimate, never a failure
        logger.debug("Plain body job counts of %s not computable", character_name, exc_info=True)
        return {"view": None, "front": None, "model": None, "after_front": None}


def _outfit_name(character_name: str, pieces: Dict[str, str]) -> str:
    """The saved outfit whose pieces are exactly the worn ones, else ""."""
    ids = sorted({str(v) for v in (pieces or {}).values() if v})
    if not ids:
        return ""
    try:
        from app.models.character import get_character_outfits
        for outfit in get_character_outfits(character_name) or []:
            if sorted({str(i) for i in outfit.get("pieces") or [] if i}) == ids:
                return str(outfit.get("name") or "")
    except Exception:  # noqa: BLE001 — a label, never a failure
        logger.debug("Saved outfits of %s unreadable", character_name, exc_info=True)
    return ""


def figure_info(character_name: str) -> Dict[str, Any]:
    """``GET /characters/{c}/figure``: ``{pipeline, humanoid, auto_build,
    status, changes, cost, build, wanted, delivered, served_url, outfit (the
    saved outfit worn now, "" when none matches), worn (each row with the
    ``jobs`` its chain step plans), hair (with ``jobs``), body (``plain.jobs``:
    ``_plain_jobs``)}``. ``status``: ``building`` while a run goes, else ``failed`` /
    ``changes`` when the plan has steps (failed: the last run recorded a
    failure, or a planned chain failed for its input — ``Step.failed``),
    else ``up_to_date``. ``auto_build`` = ``auto_build_on``."""
    from app.core import figure, model_refs
    profile = _profile_of(character_name, None)
    pipeline = on_pipeline(character_name, profile=profile)
    build = state(character_name)
    out: Dict[str, Any] = {
        "pipeline": pipeline, "humanoid": model_refs.is_humanoid(character_name, profile=profile),
        "auto_build": auto_build_on(character_name, profile=profile),
        "build": build, "served_url": _served_url(character_name)}
    if not pipeline:
        return {**out, "status": "up_to_date", "changes": [], "cost": cost(character_name, []),
                "wanted": None, "delivered": None, "outfit": "", "worn": [], "hair": None, "body": None}
    wanted, delivered = figure._delivered(character_name, profile=profile)
    steps = plan(character_name, profile=profile)
    failures = _with_cached_failures(build["failed"], steps)
    if build["running"]:
        status = "building"
    elif steps:
        status = "failed" if failures else "changes"
    else:
        status = "up_to_date"
    changes = figure.pending_changes(character_name, profile=profile)
    body_change = next((c for c in changes if c.get("key") == figure.BODY_KEY), None)
    built = _model_figure(character_name, wanted.signature)
    meshed = not figure.is_plain(wanted.shape)
    plain_state = ("ready" if body_change is None
                   else "missing" if body_change.get("delivered") == "missing" else "older_prompts")
    body = {"plain": {"key": wanted.bsig, "state": plain_state,
                      "note": "" if body_change is None or plain_state == "missing"
                      else str(body_change.get("delivered") or "")},
            "shape": {"key": wanted.shape if meshed else "",
                      "state": ("ready" if delivered.shape == wanted.shape else "missing") if meshed else "plain"},
            "texture": {"key": wanted.texture,
                        "state": ("ready" if built is not None and built.texture == wanted.texture
                                  and built.shape == wanted.shape else "missing") if wanted.texture else "none"}}
    body["plain"]["jobs"] = _plain_jobs(character_name, wanted.bsig)
    worn = _worn_rows(character_name, wanted, delivered, failures, build["running"])
    hair = _hair_row(character_name, profile, wanted, delivered, failures, build["running"])
    for row in worn:
        row["jobs"] = _item_jobs(steps, "pieces", row["item_id"])
    hair["jobs"] = _item_jobs(steps, "hair", "")
    return {**out, "status": status, "changes": changes, "cost": cost(character_name, steps),
            "wanted": wanted.as_dict(), "delivered": delivered.as_dict(),
            "outfit": _outfit_name(character_name, wanted.pieces),
            "worn": worn, "hair": hair, "body": body}
