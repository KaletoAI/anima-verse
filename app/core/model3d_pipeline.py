"""What the Game-Admin 3D tab's actions mean on the base-body pipeline.

A character on the pipeline (``base_body.is_base_pipeline``) never gets an
outfit model from a mesh backend: ``base_body.build_outfit_model`` paints the
outfit's dressed views onto the rigged base model (CPU, no img2mesh, no rig
job). The 3D tab's actions therefore split three ways (audit 2026-11-09):

* **Rebuild from the base body** (``rebuild_from_base``) replaces
  "Generate/Regenerate": no mesh backend, no face count, always a rebuild of
  the CURRENT outfit. Dressed views that are missing or no longer line up
  with the current base (``base_body.dressed_image`` is None — an older base,
  re-rendered base views, an own-mesh piece that has its garment mesh now)
  are rendered first in the T-pose lane (``model_refs.trigger_now`` blocking,
  ``force=False``: current views are kept, only the stale ones cost a GPU
  edit); then the outfit model is built with ``force`` — a model that is
  already current is rebuilt as well (the admin asked for it). A rebuild
  asked for while another model job of the character runs is never lost:
  it is recorded per (character, outfit signature) — repeated clicks keep
  one — and runs, forced, once the character's model jobs have ended
  (``_wait_and_run``; every job kind holds ``model3d._generating``, the
  re-rig and face jobs included, so the waiter watches that guard rather
  than the outfit follow-up of ``model3d._run``). If the character wears
  another outfit by then, the recorded rebuild is dropped with a log line:
  the outfit change builds the new outfit's model itself.
* **Act on the base body**: re-rig, face retexture and its revert. The base
  model is the only rigged mesh with a retained unrigged source; changing it
  marks every outfit model stale (``base_model_sha256``), and they are
  rebuilt on their next trigger.
* **Refused** (``refusal``): upload, "Fetch by job ID", the upload rig
  label — they would store a whole-body model the pipeline does not use
  and the next trigger replaces as stale.

Everything else (download, delete, measure/diagnose, shrink textures,
distance mesh, extension bones, motion sliders) works on the served outfit
file the same way on both paths.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Detail of a refused action (route 409). ``{action}`` names it.
REFUSED = ("{action} does not apply on the base-body pipeline — the outfit model is built "
           "from the base body. Use \"Rebuild from base body\" instead.")
#: Detail of a mesh-backend argument on the pipeline (route 400).
NO_BACKEND = ("The base-body pipeline uses no mesh backend — the outfit model is built from "
              "the base body (no backend, face count or texture size)")
#: Detail when the rigged base model is missing (route 409).
BASE_MODEL_FIRST = "Generate the rigged base model first (Base body tab)"

_lock = threading.Lock()
_rebuilding: set = set()
# Forced rebuilds asked for while a model job ran: {(character, outfit
# signature)}, and the characters whose waiter thread is alive.
_pending: set = set()
_waiters: set = set()
#: How often a waiter looks at the generation guard (seconds).
POLL_SECONDS = 2.0


def pipeline_state(character_name: str) -> Optional[Dict[str, Any]]:
    """None off the pipeline, else ``{base_signature, base_model,
    rerig_source, dressed_current, rebuilding}``: ``base_model`` the
    status of the current base model (``base_body.base_model_info``; None
    when there is none), ``rerig_source`` whether its unrigged source is
    retained (what a re-rig needs), ``dressed_current`` whether every
    dressed view of the current outfit lines up with the current base,
    ``rebuilding`` whether a ``rebuild_from_base`` run is in progress,
    ``queued`` whether a forced rebuild of the current outfit waits for a
    running model job."""
    from app.core import base_body
    from app.core.model3d import get_model3d_dir
    from app.core.model_refs import current_outfit_state
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    if not base_body.is_base_pipeline(character_name, profile=profile):
        return None
    bsig = base_body.base_signature(character_name, profile=profile)
    model = base_body.base_model_info(character_name, bsig)
    try:
        signature = current_outfit_state(character_name)[2]
    except Exception:  # noqa: BLE001 — a status read never fails on it
        signature = ""
    dressed = bool(signature) and all(
        base_body.dressed_image(character_name, view, signature, bsig) is not None
        for view in base_body.dressed_views())
    with _lock:
        rebuilding = character_name in _rebuilding
        queued = (character_name, signature) in _pending
    return {"base_signature": bsig,
            "base_model": (model or {}).get("status"),
            "rerig_source": (get_model3d_dir(character_name) / "unrigged" / f"{bsig}.glb").is_file(),
            "dressed_current": dressed,
            "rebuilding": rebuilding,
            "queued": queued}


def annotate(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """``GET /characters/{n}/model3d`` + ``pipeline`` (``pipeline_state``,
    None off the pipeline). On the pipeline a running rebuild counts as
    ``pending`` (its dressed views render before the model run starts).
    Never raises."""
    try:
        state = pipeline_state(character_name)
    except Exception:  # noqa: BLE001
        logger.exception("Pipeline state of %s failed", character_name)
        state = None
    info["pipeline"] = state
    if state and state["rebuilding"]:
        info["pending"] = True
    return info


def refusal(character_name: str, action: str) -> str:
    """The 409 detail for an action that does not apply on the pipeline,
    "" off the pipeline."""
    from app.core.base_body import is_base_pipeline
    return REFUSED.format(action=action) if is_base_pipeline(character_name) else ""


def rebuild_from_base(character_name: str) -> Dict[str, Any]:
    """Rebuild the CURRENT outfit's model from the base body (see the module
    docstring). Starts a worker thread; ``{"status": "generating"}``;
    ``{"status": "already_running"}`` while a rebuild is in progress (it
    does this one); ``{"status": "queued"}`` while another model job of the
    character runs (the rebuild runs, forced, once it has ended).
    ``ValueError`` off the pipeline, ``LookupError`` (``BASE_MODEL_FIRST``)
    without a ready base model."""
    from app.core import model3d
    from app.core.model_refs import current_outfit_state
    state = pipeline_state(character_name)
    if state is None:
        raise ValueError("The character is not on the base-body pipeline")
    if state["base_model"] != "ready":
        raise LookupError(BASE_MODEL_FIRST)
    with _lock:
        if character_name in _rebuilding:
            return {"status": "already_running"}
        with model3d._lock:
            busy = character_name in model3d._generating
        if not busy:
            _rebuilding.add(character_name)
    if busy:
        _queue_forced(character_name, current_outfit_state(character_name)[2])
        return {"status": "queued"}
    return _start_claimed(character_name, state)


def _start_claimed(character_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Start the ``_rebuild`` worker; the caller has already put the
    character into ``_rebuilding`` (the worker releases it)."""
    threading.Thread(target=_rebuild, args=[character_name, state["dressed_current"]],
                     daemon=True).start()
    return {"status": "generating", "dress": not state["dressed_current"]}


def _rebuild(character_name: str, dressed_current: bool) -> None:
    """Worker of ``rebuild_from_base``: stale dressed views first (in the
    T-pose lane, current ones kept), then the forced model run. The guard
    is released only after the model run is registered, so the tab never
    sees a gap between the two."""
    from app.core import model3d
    try:
        if not dressed_current:
            from app.core.model_refs import trigger_now
            trigger_now(character_name, ("tpose",), force=False, blocking=True)
        state = pipeline_state(character_name)
        if state is None or not state["dressed_current"]:
            # The dressed edits failed (their error is in the outfit status)
            # or the character left the pipeline meanwhile.
            logger.warning("Model3D %s: rebuild from the base body stopped — dressed views not current",
                           character_name)
            return
        if not model3d.trigger_generation(character_name, force=True):
            # A job started meanwhile: the forced rebuild waits for it.
            from app.core.model_refs import current_outfit_state
            _queue_forced(character_name, current_outfit_state(character_name)[2])
    except Exception:  # noqa: BLE001
        logger.exception("Model3D %s: rebuild from the base body failed", character_name)
    finally:
        with _lock:
            _rebuilding.discard(character_name)


def _queue_forced(character_name: str, signature: str) -> None:
    """Record a forced rebuild of ``signature`` for when the character's
    running model job ends; one waiter thread per character."""
    with _lock:
        _pending.add((character_name, signature))
        if character_name in _waiters:
            return
        _waiters.add(character_name)
    logger.info("Model3D %s: rebuild from the base body queued behind the running model job",
                character_name)
    threading.Thread(target=_wait_and_run, args=[character_name], daemon=True).start()


def _wait_and_run(character_name: str) -> None:
    """Waiter of ``_queue_forced``: once neither a model job nor a rebuild
    of the character runs, take its recorded rebuilds and run the one of
    the outfit worn now. Taking the records and claiming ``_rebuilding``
    happen in ONE step under ``_lock``, together with the guard check: there
    is no instant in which the rebuild is neither pending nor running (a
    status poll would see it vanish, a click would start a second worker).
    A job that starts after the claim makes the worker's model run queue the
    rebuild again (``_rebuild``), never drops it."""
    from app.core import model3d
    from app.core.model_refs import current_outfit_state
    while True:
        time.sleep(POLL_SECONDS)
        try:
            signature = current_outfit_state(character_name)[2]
        except Exception:  # noqa: BLE001
            signature = ""
        with _lock:
            with model3d._lock:
                busy = character_name in model3d._generating
            if busy or character_name in _rebuilding:
                continue
            wanted = {sig for name, sig in _pending if name == character_name}
            _pending.difference_update((character_name, sig) for sig in wanted)
            _waiters.discard(character_name)
            run = signature in wanted
            if run:
                _rebuilding.add(character_name)
            break
    for dropped in sorted(wanted - {signature}):
        logger.info("Model3D %s: queued rebuild of %s dropped — another outfit is worn now",
                    character_name, dropped)
    if not run:
        return
    try:
        state = pipeline_state(character_name)
        if state is None:
            reason = "the character left the base-body pipeline"
        elif state["base_model"] != "ready":
            reason = BASE_MODEL_FIRST
        else:
            result = _start_claimed(character_name, state)
            logger.info("Model3D %s: queued rebuild from the base body: %s", character_name, result["status"])
            return
        logger.warning("Model3D %s: queued rebuild from the base body not started: %s", character_name, reason)
    except Exception:  # noqa: BLE001
        logger.exception("Model3D %s: queued rebuild from the base body failed", character_name)
    with _lock:
        _rebuilding.discard(character_name)
