"""What an improvement type may ask about a SUBJECT, and how it regenerates it.

One place for the four subject kinds the built-in types work on — characters,
location buildings, props and character expressions — so a type stays a
declaration of *which* subjects it wants and never learns where a mesh sidecar
lives or which producer function is the blocking one.

Two rules hold for every ``generate_*`` here, because the engine calls them
synchronously in a queue worker:

* the BLOCKING producer is called directly, never a ``trigger_*`` wrapper —
  a wrapper starts a daemon thread and would report success while nothing had
  been generated;
* the producers swallow their failures and answer ``{"ok": False, "error": …}``,
  so the error is raised here.  A subject that is already being generated
  elsewhere raises :class:`CandidateBusy` instead — that is load, not a defect,
  and the engine leaves the step pending without counting an attempt.
"""
from typing import Any, Dict, List, Optional

from app.core.improvements.base import CandidateBusy


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

def characters() -> List[str]:
    """The roster an improvement may work on: every living character except the
    temporary NPCs (their assets are the spawn gate's job, and they are gone
    again before an idle pass would finish).  ``list_available_characters``
    already leaves the pooled ones out."""
    from app.models.character import is_temporary_npc, list_available_characters
    return sorted(n for n in list_available_characters() if not is_temporary_npc(n))


def character_model(name: str) -> Optional[Dict[str, Any]]:
    """The mesh entry served for this character's CURRENT outfit (carrying
    ``backend`` and ``rig``), or None when there is none."""
    from app.core.model3d import get_model3d_info
    info = get_model3d_info(name)
    return info.get("model") or None


def character_model_pending(name: str) -> bool:
    """True while a mesh generation for this character is already running."""
    from app.core import model3d
    with model3d._lock:
        return name in model3d._generating


def generate_character_model(name: str, backend: str) -> None:
    """Blocking mesh generation for the worn outfit, on ``backend``.

    Takes over ``model3d``'s own double-start guard: the producer is called
    directly (not through ``trigger_generation``, which is the thread
    wrapper), so the guard has to be held here or a parallel admin action
    would generate into the same file.
    """
    from app.core import model3d
    with model3d._lock:
        if name in model3d._generating:
            raise CandidateBusy(f"{name}: model generation already running")
        model3d._generating.add(name)
    try:
        result = model3d.generate_for_current_outfit(
            name, force=True, backend_glob=backend)
    finally:
        with model3d._lock:
            model3d._generating.discard(name)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


# ---------------------------------------------------------------------------
# Location buildings
# ---------------------------------------------------------------------------

def locations() -> List[Dict[str, Any]]:
    from app.models.world import list_locations
    return list_locations()


def building_model(location_id: str) -> Optional[Dict[str, Any]]:
    """Sidecar of the ACTIVE building model (``backend`` …), or None when the
    location has no model.  An existing model whose sidecar is unreadable
    answers ``{}`` — present, but nothing is known about it."""
    from app.core.location_model3d import get_building_info
    info = get_building_info(location_id)
    if not info.get("exists"):
        return None
    return dict(info.get("meta") or {})


def building_source_image(location_id: str) -> str:
    """Gallery file name the building mesh is generated FROM, ``""`` when the
    location has none.

    The active model's own source image first — regenerating a building means
    re-meshing the very picture it was made from.  Without one (or when that
    file is gone) the newest gallery image typed ``"building"`` takes over;
    that type is the marker ``location_model3d`` itself reads.
    """
    from app.models.world import get_gallery_dir, get_gallery_image_types
    gallery = get_gallery_dir(location_id)
    meta = building_model(location_id) or {}
    stored = str(meta.get("source_image") or "").strip()
    if stored and (gallery / stored).exists():
        return stored
    newest, newest_mtime = "", -1.0
    for name, image_type in (get_gallery_image_types(location_id) or {}).items():
        if image_type != "building":
            continue
        path = gallery / name
        if not path.exists():
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest, newest_mtime = name, mtime
    return newest


def generate_building_model(location_id: str, backend: str) -> None:
    """Blocking mesh generation for a location's building, on ``backend``."""
    from app.core import location_model3d
    if location_model3d.is_pending(location_id):
        raise CandidateBusy(f"{location_id}: model generation already running")
    source_image = building_source_image(location_id)
    if not source_image:
        raise RuntimeError("no building image")
    result = location_model3d._generate(location_id, source_image, backend)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


# ---------------------------------------------------------------------------
# Props
# ---------------------------------------------------------------------------

def props() -> List[Dict[str, Any]]:
    from app.core.props import list_props
    return list_props()


def prop_model(prop_id: str) -> Optional[Dict[str, Any]]:
    """The prop's ACTIVE mesh entry (carrying ``backend``), or None."""
    from app.core.props import list_models
    for entry in list_models(prop_id):
        if entry.get("active"):
            return entry
    return None


def prop_has_source(prop_id: str) -> bool:
    """Whether the prop's primary variant has the product shot a re-mesh needs.
    Without it there is nothing to generate FROM — such a prop is not a
    candidate for anything here."""
    from app.core.props import source_path
    return source_path(prop_id) is not None


def generate_prop_model(prop_id: str, backend: str) -> None:
    """Blocking re-mesh of the prop's existing source image, on ``backend``.

    ``mesh_only``: the picture stays, only the mesh is made again — an idle
    improvement must not spend an image render on a product shot that is
    already there.
    """
    from app.core import props as props_module
    if props_module.is_pending(prop_id):
        raise CandidateBusy(f"{prop_id}: model generation already running")
    result = props_module._generate(prop_id, "", "", "", backend, mesh_only=True)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "generation failed"))


# ---------------------------------------------------------------------------
# Character expressions
# ---------------------------------------------------------------------------

def expression_missing(name: str) -> bool:
    """Whether the DEFAULT expression variant (mood "", pose "", worn outfit)
    is missing — the same question the NPC finish gate asks, and a PEEK: a
    check must not forge the variant's LRU bookkeeping."""
    from app.core.expression_regen import peek_cached_expression
    from app.core.model_refs import current_outfit_state
    try:
        pieces, items, _sig = current_outfit_state(name)
        return peek_cached_expression(name, "", "", equipped_pieces=pieces,
                                      equipped_items=items) is None
    except Exception:  # noqa: BLE001 — an unreadable cache is "not done"
        return True


def generate_expression(name: str) -> None:
    """Blocking render of that default variant — the generator directly, so the
    per-character ``expression_variants_enabled`` gate stays out of it (the
    same call ``npc_assets`` makes).  It swallows every failure and answers
    None, so the complaint is worded here."""
    from app.core.expression_regen import generate_expression_image
    from app.core.model_refs import current_outfit_state
    pieces, items, _sig = current_outfit_state(name)
    if generate_expression_image(name, "", "", equipped_pieces=pieces,
                                 equipped_items=items) is None:
        raise RuntimeError("expression render failed")


# ---------------------------------------------------------------------------
# Mesh backends
# ---------------------------------------------------------------------------

def mesh_backend_options() -> List[Dict[str, str]]:
    """The mesh backends the admin form offers, in ``ParamField.options``
    shape."""
    from app.core import model3d
    return [{"value": b["name"], "label": b["name"]}
            for b in model3d.list_mesh_backends()["backends"]]


def default_mesh_backend() -> str:
    """The admin's default mesh backend, ``""`` when none is configured."""
    from app.core import model3d
    return str(model3d.list_mesh_backends().get("default") or "").strip()
