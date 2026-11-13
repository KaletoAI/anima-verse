"""What the Game-Admin 3D tab's actions mean on the base-body pipeline.

A character on the pipeline (``base_body.is_base_pipeline``) never gets an
outfit model from a mesh backend: ``base_body.build_outfit_model`` paints the
outfit's dressed views onto the rigged base model (CPU, no img2mesh, no rig
job). The 3D tab's actions therefore split three ways (audit 2026-11-09):

* **Generate / Regenerate** (``POST …/model3d/generate``) is the
  character's Build (Ruling FR-I4, ``routes.figure.start_manual_build``):
  the same lock, 409, plan and estimate as the Figure tab's Build — there is
  no rebuild cascade of the 3D tab's own any more (it ran dressed renders and
  a forced model run beside the Build).
* **Act on the base body**: re-rig, face retexture and its revert. The base
  model is the only rigged mesh with a retained unrigged source; changing it
  marks every outfit model stale (``base_model_sha256``), and they are
  rebuilt on their next trigger.
* **Refused** (``refusal``): upload, "Fetch by job ID", the upload rig
  label — they would store a whole-body model the pipeline does not use
  and the next trigger replaces as stale.
* **Build current outfit** (``build_current_outfit``) when the tab serves a
  stand-in (``annotate``'s ``fallback``: another outfit's model, or none):
  the character's Build (``figure_build.start``) — only missing views cost an
  image job, a stored body of the outfit's key is reused (painted body /
  outfit body: CPU, no hub job).

Everything else (download, delete, measure/diagnose, shrink textures,
distance mesh, extension bones, motion sliders) works on the served outfit
file the same way on both paths.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Detail of a refused action (route 409). ``{action}`` names it.
REFUSED = ("{action} does not apply on the base-body pipeline — the outfit model is built "
           "from the base body. Use the Figure tab's Build instead.")
#: Detail of a mesh-backend argument on the pipeline (route 400).
NO_BACKEND = ("The base-body pipeline uses no mesh backend — the outfit model is built from "
              "the base body (no backend, face count or texture size)")


def pipeline_state(character_name: str) -> Optional[Dict[str, Any]]:
    """None off the pipeline, else ``{base_signature, base_model,
    rerig_source, dressed_current}``: ``base_model`` the
    status of the current base model (``base_body.base_model_info``; None
    when there is none), ``rerig_source`` whether its unrigged source is
    retained (what a re-rig needs), ``dressed_current`` whether every
    dressed view of the current outfit lines up with the current base."""
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
    return {"base_signature": bsig,
            "base_model": (model or {}).get("status"),
            "rerig_source": (get_model3d_dir(character_name) / "unrigged" / f"{bsig}.glb").is_file(),
            "dressed_current": dressed}


def fallback_state(character_name: str, info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The served model is NOT the current outfit's (``model`` None, or a
    ``nearest`` stand-in of another combination): ``{current_signature,
    current_name, served_signature, served_name}`` (names: the saved outfit
    whose pieces match, else the piece names — ``outfit_bodies.outfit_label``;
    served "" when nothing is served). None when the current outfit's own
    model is served (stale or not — a stale one has its own hint) or the
    payload names no current signature."""
    from app.core.outfit_bodies import outfit_label
    model = info.get("model") or None
    if model and model.get("match") != "nearest":
        return None
    current = str(info.get("signature") or "")
    if not current:
        return None
    served = str((model or {}).get("signature") or "")
    return {"current_signature": current, "current_name": outfit_label(character_name, current) if current else "",
            "served_signature": served, "served_name": outfit_label(character_name, served) if served else ""}


def annotate(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """``GET /characters/{n}/model3d`` + ``pipeline`` (``pipeline_state``,
    None off the pipeline, plus ``fallback`` — ``fallback_state``). Never
    raises."""
    try:
        state = pipeline_state(character_name)
        if state is not None:
            state["fallback"] = fallback_state(character_name, info)
    except Exception:  # noqa: BLE001
        logger.exception("Pipeline state of %s failed", character_name)
        state = None
    info["pipeline"] = state
    return info


def refusal(character_name: str, action: str) -> str:
    """The 409 detail for an action that does not apply on the pipeline,
    "" off the pipeline."""
    from app.core.base_body import is_base_pipeline
    return REFUSED.format(action=action) if is_base_pipeline(character_name) else ""


def build_current_outfit(character_name: str) -> Dict[str, Any]:
    """Build the CURRENT outfit's figure: the character's Build
    (``figure_build.start(reason="build_current_outfit")``, a click — it
    retries chains that failed for their input, plan
    2026-11-12-unified-worn-pieces ruling 7a). ``{"status": …}``:
    ``started``, ``queued`` (a Build runs — this is its one follow-up),
    ``current`` (nothing to build). ``ValueError`` off the pipeline,
    ``LookupError`` when the profile could not be read (ruling F13 e) or a
    base-body step of the character runs (Ruling A26 a, the step named)."""
    from app.core import figure_build
    result = figure_build.start(character_name, reason="build_current_outfit")
    if result.get("status") == "off":
        raise ValueError("The character is not on the base-body pipeline")
    if result.get("status") in ("failed", "base_busy"):   # base_busy: Ruling A26 a, the route's 409
        raise LookupError(str(result.get("reason") or "Build failed"))
    return {"status": str(result.get("status") or "")}
