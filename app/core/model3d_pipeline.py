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
  already current is rebuilt as well (the admin asked for it).
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


def pipeline_state(character_name: str) -> Optional[Dict[str, Any]]:
    """None off the pipeline, else ``{base_signature, base_model,
    rerig_source, dressed_current, rebuilding}``: ``base_model`` the
    status of the current base model (``base_body.base_model_info``; None
    when there is none), ``rerig_source`` whether its unrigged source is
    retained (what a re-rig needs), ``dressed_current`` whether every
    dressed view of the current outfit lines up with the current base,
    ``rebuilding`` whether a ``rebuild_from_base`` run is in progress."""
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
    return {"base_signature": bsig,
            "base_model": (model or {}).get("status"),
            "rerig_source": (get_model3d_dir(character_name) / "unrigged" / f"{bsig}.glb").is_file(),
            "dressed_current": dressed,
            "rebuilding": rebuilding}


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
    docstring). Starts a worker thread; ``{"status": "generating"}``, or
    ``{"status": "already_running"}`` while a rebuild or any model job of
    the character runs. ``ValueError`` off the pipeline, ``LookupError``
    (``BASE_MODEL_FIRST``) without a ready base model."""
    from app.core import model3d
    state = pipeline_state(character_name)
    if state is None:
        raise ValueError("The character is not on the base-body pipeline")
    if state["base_model"] != "ready":
        raise LookupError(BASE_MODEL_FIRST)
    with _lock:
        if character_name in _rebuilding:
            return {"status": "already_running"}
        with model3d._lock:
            if character_name in model3d._generating:
                return {"status": "already_running"}
        _rebuilding.add(character_name)
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
        if not model3d.trigger_generation(character_name, force=True, followup=True):
            logger.info("Model3D %s: rebuild from the base body queued behind the running job",
                        character_name)
    except Exception:  # noqa: BLE001
        logger.exception("Model3D %s: rebuild from the base body failed", character_name)
    finally:
        with _lock:
            _rebuilding.discard(character_name)
