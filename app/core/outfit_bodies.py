"""Outfit bodies — the stored body shapes of a character (``ob<8hex>``, a
shape key — ``figure.shape_key``) and what the Figure tab and the sweeps need
of them (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md). The
tab of plan 2026-11-10-outfit-body-mesh-mode and its per-body runs were
removed in Task 11 — the Figure tab's Build makes a body
(``app/core/figure_build.py``).

An outfit body is the meshed and rigged body of one shape: the dressed views
of the pieces in the body → mesher → rig → normalize → extension rig →
collision capsules (``base_body.prepare_shape``). Own-mesh garments and hair
are fitted onto it (``garments.body_fit``, keyed ``(item, fsig, body id)``),
and every outfit model that wears those painted pieces is a copy of it.

What is left here:

* ``body_ids`` — every stored body of a character;
* ``refit_body`` / ``match_posture`` and ``stale_posture_bodies`` /
  ``match_stale_postures`` — the posture match of a stored body and its
  refits (the boot sweep, the ``fit_refit`` improvement); what stands on a
  turned body is rebuilt by the character's Build (``figure_build.request``);
* ``outfit_label`` — the display name of an outfit combination;
* ``delete`` / ``delete_texture`` — the explicit Delete of ONE stored body or
  painted body (``figure.delete_stored``, the Figure tab's "Stored bodies and
  textures"; Ruling 5a: only an explicit Delete removes a body stored for a
  live outfit).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("outfit_bodies")

NO_BODY = "No such outfit body"
# Delete refused (409) / unknown (404).
PAINTED_NEEDED = "Not deleted: an outfit would be built on this painted body now — see why it is kept."
NO_PAINTED_BODY = "No such painted body"


class UnknownBody(LookupError):
    """``delete`` / ``delete_texture``: nothing of the body is stored (404)."""


# --- helpers ----------------------------------------------------------------------

def _json(path: Path) -> Dict[str, Any]:
    from app.core.garment_store import read_record
    return read_record(path)


def _profile(character_name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _outfit_models(character_name: str) -> Dict[str, Dict[str, Any]]:
    """signature -> sidecar of every top-level outfit model (not a base, not
    a body, not a retired fork)."""
    from app.core import base_body
    from app.core.model3d import get_model3d_dir
    from app.core.model_refs import is_state_fork
    out: Dict[str, Dict[str, Any]] = {}
    directory = get_model3d_dir(character_name)
    if not directory.is_dir():
        return out
    for sidecar in sorted(directory.glob("*.json")):
        stem = sidecar.stem
        if (base_body.is_base_signature(stem) or base_body.is_outfit_body_signature(stem)
                or is_state_fork(stem) or not any(sidecar.with_suffix(ext).is_file() for ext in (".glb", ".fbx"))):
            continue
        out[stem] = _json(sidecar)
    return out


def _item_name(item_id: str) -> str:
    from app.models.inventory import get_item
    try:
        return str((get_item(item_id) or {}).get("name") or item_id)
    except Exception:  # noqa: BLE001
        return item_id


def _outfit_name(meta: Dict[str, Any], saved: List[Dict[str, Any]]) -> str:
    """The saved outfit whose pieces are exactly the model's, else its piece
    names in alphabetical order joined (``Skirt + Top``), else ""."""
    pieces = meta.get("pieces") if isinstance(meta.get("pieces"), dict) else {}
    ids = sorted({str(v) for v in pieces.values() if v})
    for outfit in saved:
        if ids and sorted({str(i) for i in outfit.get("pieces") or [] if i}) == ids:
            return str(outfit.get("name") or "")
    return " + ".join(sorted(_item_name(i) for i in ids))


def _saved_outfits(character_name: str) -> List[Dict[str, Any]]:
    try:
        from app.models.character import get_character_outfits
        return list(get_character_outfits(character_name) or [])
    except Exception:  # noqa: BLE001
        return []


def outfit_label(character_name: str, signature: str, *, models: Optional[Dict[str, Dict[str, Any]]] = None,
                 saved: Optional[List[Dict[str, Any]]] = None) -> str:
    """The display name of the outfit combination ``signature``
    (``_outfit_name`` of its pieces — the stored model's manifest, else its
    T-pose input's, else the worn pieces when it is the worn combination —
    the saved outfit's name first), else "" (the 3D tab's "Showing …" line,
    the Figure tab's stored bodies' "built for")."""
    meta = (models or {}).get(signature)
    if meta is None:
        try:
            from app.core.model3d import _stored_manifest
            meta = _stored_manifest(character_name, signature) or {}
            if not meta:
                from app.core.model_refs import current_outfit_state
                pieces, _items, worn = current_outfit_state(character_name)
                meta = {"pieces": dict(pieces or {})} if worn == signature else {}
        except Exception:  # noqa: BLE001 — a label, never a failure
            meta = {}
    return _outfit_name(meta, saved if saved is not None else _saved_outfits(character_name))


def body_ids(character_name: str, outfit_models: Optional[Dict[str, Dict[str, Any]]] = None,
             extra: Optional[str] = None) -> List[str]:
    """Every outfit body (stored shape) the character has files of (model,
    refs) or an outfit model names, plus ``extra``, sorted."""
    from app.core import base_body
    from app.models.character import get_character_dir
    root = get_character_dir(character_name)
    ids = set()
    for folder, pattern in ((root / "model3d", "ob*.*"), (root / "model_refs", "tpose*_ob*.*"),
                            (root / "model3d" / "unrigged", "ob*.*")):
        if folder.is_dir():
            for p in folder.glob(pattern):
                key = p.stem.rsplit("_", 1)[-1]
                if base_body.is_outfit_body_signature(key):
                    ids.add(key)
    for meta in (outfit_models if outfit_models is not None else _outfit_models(character_name)).values():
        if base_body.is_outfit_body_signature(meta.get("body_id")):
            ids.add(str(meta["body_id"]))
    if base_body.is_outfit_body_signature(extra):
        ids.add(str(extra))
    return sorted(ids)


def _body_record(character_name: str, body_id: str) -> Dict[str, Any]:
    from app.core import artefact_graph
    from app.models.character import get_character_dir
    return artefact_graph._body_record(get_character_dir(character_name), body_id)


# --- the fits on a body -----------------------------------------------------------

def _body_items(character_name: str, body_id: str) -> List[str]:
    """Items fitted (or to fit) onto ``body_id``: stored fits on it and the
    own-mesh pieces its outfit models carry."""
    from app.core import garment_store as gs
    from app.core.garment_assembly import effective_mesh_items
    items = {item for (item, _fsig), files in gs.stored_groups(character_name).items()
             if any(gs.body_of(p) == body_id for p in files)}
    for meta in _outfit_models(character_name).values():
        if meta.get("body_id") == body_id:
            items.update(effective_mesh_items(meta))
    return sorted(items)


def refit_body(character_name: str, body_id: str, item_id: str = "") -> Dict[str, Any]:
    """Fit every garment on the body (``item_id``: only that one) anew from
    the base fit served now — CPU only (``garments.fit_on_body``), a recorded
    refusal cleared first.
    ``{ok, fitted: [names], failed: [{name, error}], skipped: [{name,
    error}]}``; ``ok`` False only when something was to fit and nothing
    could."""
    from app.core import base_body, garment_fit, garment_store as gs, garments
    from app.core.keyed_lock import keyed_lock
    profile = _profile(character_name)
    base = base_body.current_base(character_name, profile=profile)
    body_sha = garments.body_sha256(character_name, body_id)
    if not body_sha:
        return {"ok": False, "error": NO_BODY, "fitted": [], "failed": [], "skipped": []}
    only = item_id
    fitted: List[str] = []
    failed: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    for item_id in [i for i in _body_items(character_name, body_id) if not only or i == only]:
        name = _item_name(item_id)
        try:
            base_fit = gs.accepted_fit(character_name, item_id, base_model_sha=base[1],
                                       profile=profile) if base and base[1] else None
        except Exception as e:  # noqa: BLE001
            skipped.append({"name": name, "error": str(e)})
            continue
        parsed = gs.parse_name(base_fit[0]) if base_fit else None
        if not parsed:
            skipped.append({"name": name, "error": "no accepted fit on the base model"})
            continue
        fsig = parsed[1]
        with keyed_lock("garment_body_fit", f"{character_name}:{body_id}"):
            gs.clear_failure_on_body(character_name, item_id, fsig, body_id)
            try:
                garments.fit_on_body(character_name, item_id, body_id=body_id, base_fit=base_fit, profile=profile)
                fitted.append(name)
            except Exception as e:  # noqa: BLE001 — recorded per body, the next item goes on
                error = getattr(e, "error", None) or str(e) or type(e).__name__
                gs.record_body_failure(character_name, item_id, fsig, body_id, error=str(error), body_sha=body_sha,
                                       base_fit_sha=garments._sha(base_fit[0]),
                                       fit_version=garment_fit.expected_fit_version(base_fit[1]))
                failed.append({"name": name, "error": str(error)})
    ok = bool(fitted) or not failed
    logger.info("Outfit body %s of %s refitted: %d fitted, %d failed, %d skipped", body_id, character_name,
                len(fitted), len(failed), len(skipped))
    return {"ok": ok, "error": "" if ok else "; ".join(f"{f['name']}: {f['error']}" for f in failed),
            "fitted": fitted, "failed": failed, "skipped": skipped}


# --- the posture match of a stored body (outfit_body_posture.py) ---------------------

def match_posture(character_name: str, body_id: str) -> Dict[str, Any]:
    """Give the STORED body ``body_id`` its base body's posture when its
    record is stale (``model3d.match_outfit_body_posture``, CPU only).
    ``{}`` when there is nothing to match, else that function's answer with
    ``changed`` (the body file was replaced). Caller holds the character's
    generation slot."""
    from app.core import model3d
    from app.core.outfit_body_posture import is_stale
    if not is_stale(character_name, body_id):
        return {}
    result = model3d.match_outfit_body_posture(character_name, body_id)
    result["changed"] = bool(result.get("ok")) and not result.get("noop")
    return result


def stale_posture_bodies(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """The read-only half of ``match_stale_postures``: the stored outfit
    bodies of a character whose posture record is stale
    (``outfit_body_posture.is_stale``), sorted; empty off the pipeline. What
    the ``fit_refit`` improvement lists."""
    from app.core import base_body
    from app.core.outfit_body_posture import is_stale
    if profile is None:
        profile = _profile(character_name)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        return []
    return [body_id for body_id in body_ids(character_name) if is_stale(character_name, body_id)]


def match_stale_postures(character_name: str) -> List[str]:
    """The boot sweep's part (``garment_refit.sweep``): every stored body of
    a character whose posture record is stale
    (``stale_posture_bodies``) is matched and its garments are refitted onto
    the turned body (``refit_body``) — each body inside the character's
    generation slot, CPU only. When a body was turned, the character's Build
    is asked once (``figure_build.request(…, "body_change")``, after the
    slots): it plans what stands on the body — never a build of its own here
    (Ruling FR-minors; the auto hook it called before bypassed the Build).
    Returns the bodies matched."""
    from app.core import model3d
    done: List[str] = []
    for body_id in stale_posture_bodies(character_name):
        with model3d.generation_slot(character_name):
            matched = match_posture(character_name, body_id)
            if not matched.get("changed"):
                if matched and not matched.get("ok"):
                    logger.warning("Outfit body %s of %s: posture match failed (%s)", body_id, character_name,
                                   matched.get("error"))
                continue
            done.append(body_id)
            refit_body(character_name, body_id)
    if done:
        from app.core import figure, figure_build
        figure.invalidate()
        figure_build.request(character_name, "body_change")
    return done


# --- delete -------------------------------------------------------------------------

def delete(character_name: str, body_id: str) -> Dict[str, Any]:
    """Delete the body and its chain (``artefact_graph.delete_body``; work in
    progress on a node protects it there) — or, for a texture signature, the
    painted body (``delete_texture``)."""
    from app.core import artefact_graph, base_body
    if base_body.is_texture_signature(body_id):
        return delete_texture(character_name, body_id)
    return artefact_graph.delete_body(character_name, body_id)


def delete_texture(character_name: str, tsig: str) -> Dict[str, Any]:
    """Delete ONE painted body of the retexture mode — the Delete of the
    painted-body list: the artefact graph's explicit collect of its texture
    node (``artefact_graph.delete_texture``), only while no live outfit
    would be built on it. ``UnknownBody`` (404) when nothing of it is
    stored, ``LookupError`` ``PAINTED_NEEDED`` (409) when it is still
    needed, ``LookupError`` with the ``artefact_graph.RUNNING_UNKNOWN`` text
    (409) when what runs cannot be read (the collect deleted nothing).
    Returns the collect report."""
    from app.core import artefact_graph
    try:
        report = artefact_graph.delete_texture(character_name, tsig)
    except artefact_graph.TextureNeeded as e:
        logger.info("Painted body %s of %s not deleted: %s", tsig, character_name, e)
        # An aborted collect (running work unreadable) is no "still needed" — name the true reason.
        unknown = artefact_graph.running_state(character_name)[2]
        raise LookupError(unknown or PAINTED_NEEDED)
    except LookupError:
        raise UnknownBody(NO_PAINTED_BODY)
    return report
