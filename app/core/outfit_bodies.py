"""The Outfit body tab — the outfit bodies of a character (mesh mode) and the
explicit runs on one body (plan
``docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md``, Task 4; spec
``docs/superpowers/specs/2026-11-10-outfit-body-mesh-mode-design.md``).

An outfit body (``ob<8hex>``, ``base_body.outfit_body_id``) is the meshed and
rigged body of one texture signature: the dressed views of the painted pieces
→ mesher → rig → normalize → extension rig → collision capsules
(``base_body.prepare_outfit_body``). Own-mesh garments and hair are fitted onto
it (``garments.body_fit``, keyed ``(item, fsig, body id)``), and every outfit
model that wears those painted pieces is a copy of it.

``info`` is what the tab shows: every body of the character with its views,
the outfits on it (names), its dress text, freshness, step list, fits and
run state; in retexture mode the painted bodies (``texture_users``) read-only.

Its views (``view_info``) are the CURRENT dressed views of the body's texture
(the texture store ``model_refs/texture/tpose[_<view>]_<tsig>``, which every
render of a dressed view publishes into; the body's own mesher inputs
``tpose[_<view>]_<body id>`` only when the store has none) — what the next
regeneration meshes from — each with a server freshness
(``model_overview.outfit_body_view_freshness``: base body / base view, dress
text, and for a back/side whether it was drafted from the current dressed
front), its run state and why it cannot be rendered (``view_blocked``).
The body's model is judged against those views as before
(``DRESSED_VIEWS_CHANGED``), so a re-rendered view leaves the model
"outdated: Dressed views changed" until its own Regenerate run.

The runs (``start``): ``regenerate`` (mesh again from its views — the old
path's chain through the routed occasions, hub jobs), ``rerig`` (the rig
chain on the retained unrigged mesh, hub job), ``refit`` (every fit on the
body anew from the base fits, CPU), ``view`` (ONE dressed view rendered
anew — ``render_view``: image jobs only, never the mesh; the front is one
edit of the base front, a back/side a draft from the dressed front plus the
gated fit), ``views`` (the WORN outfit's missing dressed views —
``render_worn_views``: image jobs only, never chained to the mesh; the
body the worn outfit will stand on is listed before they exist,
``worn_body``). A view run does not cascade: the back follows the front through
its draft, so after a new front the back shows "outdated: Made from an older
dressed front" and is rendered again only by its own click (the pipeline
accepts a back of an older front — ``base_body.dressed_image`` judges the
base view only). They join ONE FIFO per character and
never refuse (the explicit-run rule of the garment queue, 4c81488b): a run
waits behind the running one, and each run holds model3d's per-character
generation guard (``model3d.generation_slot``) — a body is never rebuilt
while another 3D run of the character goes. Delete is not a run: it is the
artefact graph's explicit walk (``artefact_graph.delete_body``). ``cancel``
takes a body's waiting runs out of the FIFO (never the one in flight).

Retexture mode (``textures``, ``texture_info``): every painted body of the
character keyed by its texture signature, the WORN outfit's first and marked
``current`` (``worn_texture``) — before its dressed views exist a pending
entry keyed by the outfit signature. Bodies of other outfits are listed below
with the outfits that use them, never as current. Two runs join the same
FIFO, Cancel and generation slot: ``paint`` (Generate / Build outfit model,
the worn entry only — ``paint_worn``: the worn outfit's missing dressed
views, then its outfit model, never forced, so a stored painted body of the
key is reused on the CPU) and ``repaint`` (Regenerate a painted body —
``repaint_texture``: every dressed view rendered anew for an outfit standing
on it, then that outfit's model built forced, the body painted again). In
both modes a body is ``current`` only when the worn outfit stands on it;
an outfit body of the other mode stays stored (artefact GC: a body hangs on
its texture in both modes, so switching back costs no hub job).
"""
from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("outfit_bodies")

#: The retexture mode's runs on a painted body (key: texture signature, or the worn outfit's signature
#: while its body is pending).
TEXTURE_RUN_KINDS = ("paint", "repaint")
RUN_KINDS = ("regenerate", "rerig", "refit", "view", "views") + TEXTURE_RUN_KINDS
NO_SOURCE = ("No outfit stands on this body's dressed views any more — "
             "render the outfit's pose images first")
NO_UNRIGGED = "The outfit body has no retained unrigged mesh — regenerate it"
NOT_MESH_MODE = "Outfit bodies are built in the mesh mode only"
NOT_PIPELINE = "The outfit body needs the base-body pipeline"
NO_BODY = "No such outfit body"
DRESSED_VIEWS_CHANGED = "Dressed views changed"
OLDER_BODY_VERSION = "Built by an older outfit body version"
NO_OUTFIT_ON_IT = "No outfit model stands on it"
NOT_BUILT = "Not built"
# A body from before the posture match, or matched to another base model (outfit_body_posture.py):
# the next "Re-fit all", outfit build on it or server start matches it (CPU).
POSTURE_NOT_MATCHED = "Posture not matched to the base body yet"
# The worn outfit's body before its dressed views exist (``worn_body``) and the
# reasons the tab shows under a disabled action (``body_info``'s ``blocked``).
WORN_VIEWS_MISSING = "The worn outfit's dressed views are missing — Generate views renders them"
WORN_VIEWS_PRESENT = "The worn outfit's dressed views exist already"
NOT_WORN_BODY = "Not the worn outfit's body — Generate views renders the worn outfit's views only"
NO_MODEL = "No model stored — regenerate the body first"
NO_GARMENTS = "No own-mesh garment or hair on this body"
NOTHING_STORED = "Nothing of this body is stored yet"
# What a pending worn entry's view tile shows instead of a freshness badge (``body_info``).
PENDING_TEXTURE_VIEW = ("Dressed view of this texture made for another outfit — the worn outfit has none yet, "
                        "not used")
PENDING_BODY_VIEW = "Older mesher input of this body — not the worn outfit's dressed view, not used"
LOCKED_BUILD = "Locked: a 3D model job is running for this body"
LOCKED_RUNNING = "Locked: a run on this body is running"
LOCKED_QUEUED = "Locked: a run on this body is queued"
# The retexture mode's painted bodies (``texture_info``'s ``blocked``).
NOT_RETEXTURE_MODE = "Painted bodies are built in the retexture mode only"
NOT_WORN_TEXTURE = "Not the worn outfit's body — Generate builds the worn outfit only"
WORN_MODEL_PRESENT = "The worn outfit's model is built and current — Regenerate renders its views and paints it anew"
PENDING_NO_BODY = "Nothing to regenerate yet — Generate renders the worn outfit's dressed views and paints its body"
_OUTFIT_SIG_RE = re.compile(r"[0-9a-f]{12}")
_FRONT_REF_RE = re.compile(r"tpose_([0-9a-f]{12})")


class UnknownBody(LookupError):
    """``check_run``: the run names a body it cannot work on at all (404)."""


@dataclass
class _Job:
    kind: str
    body_id: str
    #: a refit of ONE garment on the body ("" = every garment on it)
    item_id: str = ""
    #: the dressed view of a ``view`` run
    view: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: Dict[str, Any] = field(default_factory=dict)

    def key(self) -> Tuple[str, str, str, str]:
        return self.kind, self.body_id, self.item_id, self.view


_lock = threading.Lock()
_queues: Dict[str, Deque[_Job]] = {}
_current: Dict[str, _Job] = {}
_active: set = set()
#: (character, body id) -> {kind, ok, error, finished_at, detail}: the last run's outcome.
_results: Dict[Tuple[str, str], Dict[str, Any]] = {}


# --- helpers ----------------------------------------------------------------------

def _json(path: Path) -> Dict[str, Any]:
    from app.core.garment_store import read_record
    return read_record(path)


def _profile(character_name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _enc(character_name: str) -> str:
    return quote(character_name, safe="")


def view_path(character_name: str, key: str, view: str) -> Optional[Path]:
    """The stored view image of an outfit body (its mesher input,
    ``model_refs/tpose[_<view>]_<body id>``) or of a texture (``model_refs/
    texture/…``); None for anything else."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    if view not in base_body.BASE_VIEWS:
        return None
    if base_body.is_outfit_body_signature(key):
        return find_ref_image(character_name, base_body._kind(view), key)
    if base_body.is_texture_signature(key):
        return base_body._texture_view(character_name, view, key)
    return None


def _view_urls(character_name: str, key: str) -> Tuple[Dict[str, Optional[str]], Dict[str, Any]]:
    from app.core import base_body
    from app.core.model_refs import image_tile_meta
    urls: Dict[str, Optional[str]] = {}
    metas: Dict[str, Any] = {}
    for view in base_body.BASE_VIEWS:
        path = view_path(character_name, key, view)
        try:
            stamp = path.stat().st_mtime_ns if path else None
        except OSError:
            stamp = None
        urls[view] = (f"/characters/{_enc(character_name)}/outfit-bodies/{key}/views/{view}?v={stamp}"
                      if stamp is not None else None)
        metas[view] = image_tile_meta(path) if stamp is not None else None
    return urls, metas


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
    the painted bodies' "used by")."""
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
    """Every outfit body the character has files of (model, refs) or an
    outfit model names, plus ``extra`` (the worn outfit's body, ``worn_body``),
    sorted."""
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
    with _lock:
        for job in list(_queues.get(character_name) or ()) + (
                [_current[character_name]] if character_name in _current else []):
            if base_body.is_outfit_body_signature(job.body_id):
                ids.add(job.body_id)  # a painted body's run is not an outfit body's
    return sorted(ids)


def _body_record(character_name: str, body_id: str) -> Dict[str, Any]:
    from app.core import artefact_graph
    from app.models.character import get_character_dir
    return artefact_graph._body_record(get_character_dir(character_name), body_id)


def source_outfit(character_name: str, body_id: str, *, profile: Optional[Dict[str, Any]] = None,
                  outfit_models: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """An outfit whose dressed views stand for ``body_id`` NOW (the record's
    ``built_for`` first, then every outfit model on the body, the worn
    outfit last) — what a regeneration meshes from; "" when none does."""
    from app.core import base_body
    from app.core.model_refs import current_outfit_state
    record = _body_record(character_name, body_id)
    models = outfit_models if outfit_models is not None else _outfit_models(character_name)
    candidates = [str(record.get("built_for") or "")]
    candidates += [sig for sig, meta in models.items() if meta.get("body_id") == body_id]
    try:
        candidates.append(current_outfit_state(character_name)[2])
    except Exception:  # noqa: BLE001
        pass
    seen = set()
    for sig in candidates:
        if not sig or sig in seen:
            continue
        seen.add(sig)
        if base_body.outfit_body_of_outfit(character_name, sig, profile=profile) == body_id:
            return sig
    return ""


# --- the fits on a body -----------------------------------------------------------

def _body_items(character_name: str, body_id: str, on_body: List[Dict[str, Any]],
                profile: Dict[str, Any]) -> List[str]:
    """Items fitted (or to fit) onto ``body_id``: stored fits on it, the
    own-mesh pieces its outfit models carry, the worn hair when the worn
    outfit stands on it."""
    from app.core import garment_store as gs
    from app.core.garment_assembly import effective_mesh_items
    items = {item for (item, _fsig), files in gs.stored_groups(character_name).items()
             if any(gs.body_of(p) == body_id for p in files)}
    worn_on_it = False
    for entry in on_body:
        items.update(effective_mesh_items(entry["meta"]))
        worn_on_it = worn_on_it or entry["worn"]
    worn = profile.get("equipped_mesh_pieces")
    if worn_on_it and isinstance(worn, dict):
        items.update(str(v) for v in worn.values() if v)
    return sorted(items)


def fits_on_body(character_name: str, body_id: str, *, profile: Optional[Dict[str, Any]] = None,
                 on_body: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """``[{item_id, name, fsig, status, error, created_at}]`` — each garment
    on the body, judged against the base fit served now (``status``:
    ``garments.body_fit_state`` — accepted / stale / outdated / missing —,
    ``failed`` for a recorded refusal that still holds, ``no_base_fit``
    without an accepted fit on the base model to derive from)."""
    from app.core import base_body, garment_fit, garment_store as gs, garments
    profile = profile if profile is not None else _profile(character_name)
    if on_body is None:
        on_body = _outfits_on_body(character_name, body_id, _outfit_models(character_name), [], "")
    base = base_body.current_base(character_name, profile=profile)
    body_sha = garments.body_sha256(character_name, body_id)
    out = []
    for item_id in _body_items(character_name, body_id, on_body, profile):
        row: Dict[str, Any] = {"item_id": item_id, "name": _item_name(item_id), "fsig": None,
                               "status": "no_base_fit", "error": "", "created_at": None}
        try:
            base_fit = gs.accepted_fit(character_name, item_id, base_model_sha=base[1],
                                       profile=profile) if base and base[1] else None
        except Exception as e:  # noqa: BLE001 — an item that is no garment any more
            row["error"] = str(e)
            out.append(row)
            continue
        parsed = gs.parse_name(base_fit[0]) if base_fit else None
        if not parsed:
            row["error"] = "no accepted fit on the base model to derive from"
            out.append(row)
            continue
        fsig = parsed[1]
        base_fit_sha = garments._sha(base_fit[0])
        status = garments.body_fit_state(character_name, item_id, fsig, body_id, body_sha, base_fit_sha)
        failure = (gs.body_failure(character_name, item_id, fsig, body_id, body_sha=body_sha,
                                   base_fit_sha=base_fit_sha,
                                   fit_version=garment_fit.FIT_VERSION.get(str(base_fit[1].get("kind") or "")))
                   if status != "accepted" else None)
        record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit", body=body_id)
                                .with_suffix(".json"))
        row.update(fsig=fsig, status="failed" if failure else status,
                   error=str((failure or {}).get("error") or ""), created_at=record.get("created_at"))
        out.append(row)
    return out


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
    on_body = _outfits_on_body(character_name, body_id, _outfit_models(character_name), [], "")
    only = item_id
    fitted: List[str] = []
    failed: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    for item_id in [i for i in _body_items(character_name, body_id, on_body, profile)
                    if not only or i == only]:
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
                                       fit_version=garment_fit.FIT_VERSION.get(str(base_fit[1].get("kind") or "")))
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


def rebuild_worn_on(character_name: str, body_id: str) -> bool:
    """After the body ``body_id`` changed under its outfit models: rebuild
    the WORN outfit's model when it stands on that body — through the auto
    hook (``model3d.maybe_auto_generate_for_outfit``; inside a generation
    slot it runs as the follow-up once the slot ends). Only in mesh mode and
    only when the body is current for the worn outfit's dressed views, so
    the rebuild is the CPU copy onto the body, never a mesh run. True when
    a build was started or queued."""
    from app.core import base_body, model3d
    from app.core.model_refs import current_outfit_state
    profile = _profile(character_name)
    if base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
        return False
    worn = current_outfit_state(character_name)[2]
    if not worn or base_body.outfit_body_of_outfit(character_name, worn, profile=profile) != body_id:
        return False
    bsig = base_body.base_signature(character_name, profile=profile)
    if _body_record(character_name, body_id).get("views") != base_body.texture_view_shas(character_name, worn, bsig):
        return False
    model3d.maybe_auto_generate_for_outfit(character_name)
    return True


def match_stale_postures(character_name: str) -> List[str]:
    """The boot sweep's part (``garment_refit.sweep``): every stored body of
    a character in mesh mode whose posture record is stale is matched, its
    garments are refitted onto the turned body (``refit_body``) and the worn
    outfit's model on it is rebuilt (``rebuild_worn_on``) — each body inside
    the character's generation slot. CPU only. Returns the bodies matched."""
    from app.core import base_body, model3d
    from app.core.outfit_body_posture import is_stale
    profile = _profile(character_name)
    if (not base_body.is_base_pipeline(character_name, profile=profile)
            or base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE):
        return []
    done: List[str] = []
    for body_id in body_ids(character_name):
        if not is_stale(character_name, body_id):
            continue
        with model3d.generation_slot(character_name):
            matched = match_posture(character_name, body_id)
            if not matched.get("changed"):
                if matched and not matched.get("ok"):
                    logger.warning("Outfit body %s of %s: posture match failed (%s)", body_id, character_name,
                                   matched.get("error"))
                continue
            done.append(body_id)
            refit_body(character_name, body_id)
            rebuild_worn_on(character_name, body_id)
    return done


# --- the dressed views of a body -----------------------------------------------------

def view_blocked(character_name: str, body_id: str, view: str, *, profile: Optional[Dict[str, Any]] = None,
                 source: Optional[str] = None) -> str:
    """Why the dressed ``view`` of the body cannot be rendered anew now
    (server English the tab translates), "" when it can: a view that is not
    dressed (the side views while they are off), not mesh mode, no outfit
    standing on the body's views (``NO_SOURCE``), the base view missing, a
    back/side without a current dressed front to draft from. ``source``:
    ``source_outfit`` when the caller has it."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    profile = profile if profile is not None else _profile(character_name)
    if view not in base_body.dressed_views():
        return base_body.SIDE_VIEW_NOT_DRESSED
    if base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
        return NOT_MESH_MODE
    source = source if source is not None else source_outfit(character_name, body_id, profile=profile)
    if not source:
        return NO_SOURCE
    bsig = base_body.base_signature(character_name, profile=profile)
    if find_ref_image(character_name, base_body._kind(view), bsig) is None:
        return base_body.BASE_IMAGES_MISSING
    if view != "front" and base_body.dressed_image(character_name, "front", source, bsig) is None:
        return base_body.DRESSED_FRONT_FIRST
    return ""


def _texts_now(character_name: str, candidates: List[str], *, bsig: str,
               profile: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """``{view: dress text}`` the first candidate outfit with a stored front
    computes NOW (``base_body._outfit_texture`` of that front's manifest) —
    what a view of the body would be sent today; None when none can."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    seen = set()
    for sig in candidates:
        if not sig or sig in seen:
            continue
        seen.add(sig)
        front = find_ref_image(character_name, "tpose", sig)
        if front is None:
            continue
        try:
            texts = base_body._outfit_texture(character_name, front, bsig=bsig, profile=profile)["inputs"]["dress_text"]
        except Exception:  # noqa: BLE001 — a display hint, never a failure
            logger.debug("Dress text of %s / %s not computable", character_name, sig, exc_info=True)
            continue
        return {str(k): str(v) for k, v in (texts or {}).items()}
    return None


def _view_runs(character_name: str, body_id: str) -> Dict[str, Tuple[str, Optional[int]]]:
    """``{view: (running|queued, queue position)}`` of the body's view runs;
    a running ``views`` run counts as running for every dressed view (its
    waiting run is the body's, cancelled with the body's Cancel)."""
    from app.core import base_body
    out: Dict[str, Tuple[str, Optional[int]]] = {}
    with _lock:
        current = _current.get(character_name)
        if current is not None and current.body_id == body_id and current.kind == "view":
            out[current.view] = ("running", None)
        if current is not None and current.body_id == body_id and current.kind == "views":
            out.update({v: ("running", None) for v in base_body.dressed_views()})
        for n, job in enumerate(_queues.get(character_name) or (), start=1):
            if job.body_id == body_id and job.kind == "view":
                out.setdefault(job.view, ("queued", n))
    return out


def view_infos(character_name: str, body_id: str, *, record: Dict[str, Any], tsig: str, source: str, bsig: str,
               profile: Dict[str, Any], candidates: List[str],
               last: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """``{view: {url, meta, source, status, queue_position, error, warning,
    blocked}}`` — every dressed view of the body (and any other view that
    has an image), in ``BASE_VIEWS`` order. ``url``/``meta``: the texture
    store's view of ``tsig`` (``source: "texture"``), else the body's mesher
    input (``"body"``), else None; ``meta`` = ``image_tile_meta`` +
    ``freshness`` (``outfit_body_view_freshness``). ``status``: running /
    queued (a ``view`` run of the tab) / failed (the body's last run was this
    view's and failed, ``error``) / "". ``warning``: the kept fit's gate
    warning. ``blocked``: ``view_blocked``."""
    from app.core import base_body
    from app.core.model_overview import outfit_body_view_freshness
    from app.core.model_refs import find_ref_image, image_tile_meta
    dressed = base_body.dressed_views()
    has_store = base_body.is_texture_signature(tsig)
    store = {v: base_body._texture_view(character_name, v, tsig) for v in base_body.BASE_VIEWS} if has_store else {}
    front_sha = base_body.file_sha256(store.get("front"))
    texts = _texts_now(character_name, candidates, bsig=bsig, profile=profile)
    runs = _view_runs(character_name, body_id)
    last = last or {}
    out: Dict[str, Dict[str, Any]] = {}
    for v in base_body.BASE_VIEWS:
        path, key, origin = store.get(v), tsig, "texture"
        if path is None:
            path, key, origin = view_path(character_name, body_id, v), body_id, "body"
        if path is None and v not in dressed:
            continue
        url, tile = None, None
        meta = base_body._ref_sidecar(path)
        if path is not None:
            try:
                url = f"/characters/{_enc(character_name)}/outfit-bodies/{key}/views/{v}?v={path.stat().st_mtime_ns}"
            except OSError:
                url = None
        if url is not None:
            follows: Optional[bool] = None
            if v != "front" and origin == "texture" and meta.get(f"{v}_draft_sha256"):
                follows = base_body.follows_front(v, meta, base_body._texture_draft(character_name, v, tsig),
                                                  front_sha)
            tile = {**image_tile_meta(path, meta), "freshness": outfit_body_view_freshness(
                meta, bsig=bsig,
                base_view_sha=base_body.file_sha256(find_ref_image(character_name, base_body._kind(v), bsig)),
                mesh_ready=bool(base_body.mesh_items_ready(character_name, meta, bsig=bsig)),
                follows_front=follows, text_now=(texts or {}).get(v) if texts is not None else None)}
        run, position = runs.get(v, ("", None))
        failed = (not run and last.get("kind") == "view" and last.get("view") == v and not last.get("ok"))
        gate = meta.get("fit_gate") if isinstance(meta.get("fit_gate"), dict) else {}
        out[v] = {"url": url, "meta": tile, "source": origin if url else None,
                  "status": run or ("failed" if failed else ""), "queue_position": position,
                  "error": str(last.get("error") or "") if failed else "",
                  "warning": str(gate.get("warning") or "") if url else "",
                  "blocked": view_blocked(character_name, body_id, v, profile=profile, source=source)}
    return out


def render_view(character_name: str, body_id: str, view: str) -> Dict[str, Any]:
    """Render ONE dressed view of the body anew (image jobs only, never the
    mesh): the outfit standing on the body's views (``source_outfit``) and
    the texture store become one set first (``base_body._sync_texture_views``
    — a back is drafted from the texture's current front), then
    ``generate_dressed_images(view=…, force=True)`` with the pieces of that
    outfit's dressed front; the render is published into the texture store
    (what the tab shows). Caller holds the character's generation slot.
    ``{ok, error}``."""
    from app.core import base_body
    from app.core.keyed_lock import keyed_lock
    from app.core.model_refs import find_ref_image
    profile = _profile(character_name)
    source = source_outfit(character_name, body_id, profile=profile)
    blocked = view_blocked(character_name, body_id, view, profile=profile, source=source)
    if blocked:
        return {"ok": False, "error": blocked}
    bsig = base_body.base_signature(character_name, profile=profile)
    front = base_body.dressed_image(character_name, "front", source, bsig)
    if front is None:
        return {"ok": False, "error": NO_SOURCE}
    texture = base_body._outfit_texture(character_name, front, bsig=bsig, profile=profile)
    registrations = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in base_body.BASE_VIEWS}
    manifest = texture["manifest"]
    with keyed_lock("outfit_body", f"{character_name}:{body_id}"):
        base_body._sync_texture_views(character_name, signature=source, tsig=texture["tsig"], bsig=bsig,
                                      base_views=registrations, texts=texture["inputs"]["dress_text"],
                                      manifest=manifest, profile=texture["mesh_profile"])
    logger.info("Outfit body %s of %s: rendering the dressed %s anew (outfit %s)", body_id, character_name, view,
                source)
    results = base_body.generate_dressed_images(character_name, pieces=manifest.get("pieces") or {},
                                                items=manifest.get("items") or [], signature=source,
                                                force=True, view=view)
    if results.get(base_body._kind(view)):
        return {"ok": True, "error": ""}
    with base_body._status_lock:
        failure = dict(base_body._outfit_failed.get((character_name, source)) or {})
    return {"ok": False, "error": str(failure.get("error") or f"Dressed {view} render failed")}


# --- the worn outfit's body ------------------------------------------------------------

def worn_body(character_name: str, *, profile: Dict[str, Any], bsig: str) -> Optional[Dict[str, Any]]:
    """Mesh mode: the body the WORN outfit stands on — or will stand on once
    its dressed views exist. ``{signature, pieces, items, body_id, tsig,
    predicted, views_missing, image_jobs}``; None off mesh mode, with nothing
    worn, for an undressed combination (it stands on the base body) or when
    it cannot be computed.

    With a dressed front of the current base the body is
    ``base_body.outfit_body_of_outfit``'s (``predicted`` False). Without
    one it is predicted from the worn pieces by the rule
    ``generate_dressed_images`` signs the views with in mesh mode
    (``resolve_mesh_items``: every flagged own-mesh piece is left out —
    ``unpainted`` = ``intended`` —, ``texture_variant`` / ``texture_inputs``
    of the pieces), read-only: no garment chain runs. ``views_missing``: the
    dressed views (``dressed_views()``) without a current image
    (``dressed_image``); ``image_jobs``: what rendering them costs at least —
    one edit for the front, a draft plus a fit for each other view (a view
    the texture store holds is copied, no job)."""
    from copy import deepcopy
    from app.core import base_body, garment_set
    from app.core.model_refs import current_outfit_state
    from app.models.inventory import get_item
    if base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
        return None
    try:
        pieces, items, worn = current_outfit_state(character_name)
        if not worn:
            return None
        front = base_body.dressed_image(character_name, "front", worn, bsig)
        if front is not None:
            body_id = base_body.outfit_body_of_outfit(character_name, worn, profile=profile)
            if not body_id:
                return None  # an undressed front: the outfit stands on the base body
            dressed = True
            tsig = str(base_body._outfit_texture(character_name, front, bsig=bsig, profile=profile)["tsig"])
        else:
            mesh_profile = deepcopy(profile)
            mesh_profile["equipped_pieces"] = dict(pieces or {})
            mesh_profile["equipped_items"] = list(items or [])
            intended = [i for i in garment_set.worn_garments(character_name, profile=mesh_profile,
                                                             pieces=dict(pieces or {}))
                        if garment_set.garment_kind_of(get_item(i)) in garment_set.OWN_MESH_PIECE_KINDS]
            dressed = bool(base_body.dress_text(character_name, "front", pieces=pieces, items=items,
                                                profile=mesh_profile, mesh_items=intended))
            variant = base_body.texture_variant(character_name, pieces, dressed=dressed,
                                                mesh={"intended": intended}, profile=profile)
            tsig = base_body.texture_signature(base_body.texture_inputs(
                character_name, pieces=pieces, items=items, variant=variant, mesh_effective=intended, bsig=bsig,
                profile=mesh_profile))
            body_id = base_body.outfit_body_id(tsig)
        if not dressed:
            return None
        missing = [v for v in base_body.dressed_views()
                   if base_body.dressed_image(character_name, v, worn, bsig) is None]
    except Exception:  # noqa: BLE001 — a display entry, never a failure
        logger.debug("Worn outfit body of %s not computable", character_name, exc_info=True)
        return None
    return {"signature": worn, "pieces": dict(pieces or {}), "items": list(items or []), "body_id": body_id,
            "tsig": tsig, "predicted": front is None, "views_missing": missing,
            "image_jobs": (1 if "front" in missing else 0) + 2 * len([v for v in missing if v != "front"])}


def render_worn_views(character_name: str, body_id: str) -> Dict[str, Any]:
    """The ``views`` run: render the worn outfit's missing dressed views
    (``generate_dressed_images`` without ``force`` — image jobs only, a view
    the texture store holds is copied) when the worn outfit stands on
    ``body_id`` (``worn_body``). Never chained to the mesh: the body's own
    Regenerate meshes it. Caller holds the character's generation slot.
    ``{ok, error}``."""
    from app.core import base_body
    profile = _profile(character_name)
    bsig = base_body.base_signature(character_name, profile=profile)
    worn = worn_body(character_name, profile=profile, bsig=bsig)
    if worn is None or worn["body_id"] != body_id:
        return {"ok": False, "error": NOT_WORN_BODY}
    logger.info("Outfit body %s of %s: rendering the worn outfit's dressed views %s (outfit %s)", body_id,
                character_name, worn["views_missing"], worn["signature"])
    base_body.generate_dressed_images(character_name, pieces=worn["pieces"], items=worn["items"],
                                      signature=worn["signature"], force=False)
    missing = [v for v in base_body.dressed_views()
               if base_body.dressed_image(character_name, v, worn["signature"], bsig) is None]
    now = base_body.outfit_body_of_outfit(character_name, worn["signature"], profile=profile)
    if now and now != body_id:
        logger.warning("Outfit body of %s: the worn outfit's views stand for %s, %s was predicted",
                       character_name, now, body_id)
    if not missing:
        return {"ok": True, "error": ""}
    with base_body._status_lock:
        failure = dict(base_body._outfit_failed.get((character_name, worn["signature"])) or {})
    return {"ok": False, "error": str(failure.get("error") or "Dressed views missing: " + ", ".join(missing))}


# --- the painted bodies of the retexture mode --------------------------------------------

def worn_texture(character_name: str, *, profile: Dict[str, Any], bsig: str) -> Optional[Dict[str, Any]]:
    """Retexture mode: the painted body the WORN outfit stands on. ``{signature,
    pieces, items, tsig, key, pending, views_missing, image_jobs, model}`` —
    ``tsig`` from its dressed front of the current base (``_outfit_texture``,
    the build's key), "" while that front is missing or not current
    (``pending``; ``key`` is then the outfit signature, else the tsig);
    ``views_missing`` the dressed views without a current image, ``image_jobs``
    what rendering them costs at least (as ``worn_body``); ``model`` whether
    its outfit model is stored and current (``model3d.find_model3d``). None
    off the retexture mode, with nothing worn or when it cannot be computed.
    Read-only."""
    from app.core import base_body, model3d
    from app.core.model_refs import current_outfit_state
    if base_body.outfit_body_mode(character_name, profile=profile) == base_body.MESH_MODE:
        return None
    try:
        pieces, items, worn = current_outfit_state(character_name)
        if not worn:
            return None
        front = base_body.dressed_image(character_name, "front", worn, bsig)
        tsig = (str(base_body._outfit_texture(character_name, front, bsig=bsig, profile=profile)["tsig"])
                if front is not None else "")
        missing = [v for v in base_body.dressed_views()
                   if base_body.dressed_image(character_name, v, worn, bsig) is None]
        built = model3d.find_model3d(character_name, worn) is not None
    except Exception:  # noqa: BLE001 — a display entry, never a failure
        logger.debug("Worn painted body of %s not computable", character_name, exc_info=True)
        return None
    return {"signature": worn, "pieces": dict(pieces or {}), "items": list(items or []), "tsig": tsig,
            "key": tsig or worn, "pending": not tsig, "views_missing": missing,
            "image_jobs": (1 if "front" in missing else 0) + 2 * len([v for v in missing if v != "front"]),
            "model": built}


def _texture_front_users(character_name: str) -> Dict[str, List[str]]:
    """``{tsig: [outfit signature, ...]}`` of the outfits whose stored dressed
    front (``model_refs/tpose_<sig>``) names the texture — the outfits standing
    on it with or without a model."""
    from app.core import base_body
    from app.core.model_refs import get_model_refs_dir
    out: Dict[str, List[str]] = {}
    refs = get_model_refs_dir(character_name)
    if not refs.is_dir():
        return out
    for sidecar in sorted(refs.glob("tpose_*.json")):
        match = _FRONT_REF_RE.fullmatch(sidecar.stem)
        if not match:
            continue
        tsig = base_body._ref_sidecar(sidecar).get("texture_signature")
        if base_body.is_texture_signature(tsig):
            out.setdefault(str(tsig), []).append(match.group(1))
    return out


def texture_source(character_name: str, tsig: str, candidates: List[str], *, profile: Dict[str, Any],
                   bsig: str, limit: int = 8) -> str:
    """The first of ``candidates`` whose CURRENT dressed front stands for
    ``tsig`` (what a Regenerate renders the views for), "" when none of the
    first ``limit`` does."""
    from app.core import base_body
    seen = set()
    for sig in candidates:
        if not sig or sig in seen or len(seen) >= limit:
            continue
        seen.add(sig)
        try:
            front = base_body.dressed_image(character_name, "front", sig, bsig)
            if front is not None and base_body._outfit_texture(character_name, front, bsig=bsig,
                                                               profile=profile)["tsig"] == tsig:
                return sig
        except Exception:  # noqa: BLE001 — a lookup, never a failure
            logger.debug("Texture of %s / %s not computable", character_name, sig, exc_info=True)
    return ""


def _keys_state(character_name: str, keys: List[str]) -> Tuple[str, Optional[str], Optional[int]]:
    """``_run_state`` over several keys (a pending worn entry's run is keyed by the outfit signature)."""
    for key in keys:
        state = _run_state(character_name, key)
        if state[0]:
            return state
    return "", None, None


def _base_ready(character_name: str, bsig: str) -> str:
    """"" when the base model is ready and every dressed base view exists, else why not."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    if (base_body.base_model_info(character_name, bsig) or {}).get("status") != "ready":
        return base_body.BASE_MODEL_MISSING
    if any(find_ref_image(character_name, base_body._kind(v), bsig) is None for v in base_body.dressed_views()):
        return base_body.BASE_IMAGES_MISSING
    return ""


def texture_body_url(character_name: str, tsig: str) -> Optional[str]:
    """Versioned URL of the stored painted body of ``tsig``
    (``/characters/<c>/outfit-bodies/<tsig>/model?v=<content>``, served by
    the outfit-bodies route with ``http_files.snapshot_response``), None
    without one."""
    from app.core import base_body
    from app.core.http_files import content_version
    try:
        path = base_body.texture_body_path(character_name, tsig)
        version = content_version(path)
    except (ValueError, OSError):
        return None
    return f"/characters/{quote(character_name, safe='')}/outfit-bodies/{tsig}/model?v={version}"


def texture_body_freshness(character_name: str, record: Dict[str, Any], *, painted: bool, source: str,
                           bsig: str) -> Dict[str, str]:
    """The painted body's freshness badge (``model_overview.freshness``):
    missing "Not built" without one; stale when its record names another
    base model than the current one, or dressed views of its source outfit
    (``texture_source``) other than the ones it was painted from; else
    current. Stat-cached hashes only — the tab polls."""
    from app.core import base_body
    from app.core.model_overview import DRESSED_VIEWS_CHANGED, OLDER_BASE_BODY, freshness
    if not painted:
        return freshness("missing", NOT_BUILT)
    reasons = []
    if (record.get("base_signature") != bsig
            or record.get("base_model_sha256") != base_body.base_model_sha256(character_name, bsig)):
        reasons.append(OLDER_BASE_BODY)
    if source and record.get("views") != base_body.texture_view_shas(character_name, source, bsig):
        reasons.append(DRESSED_VIEWS_CHANGED)
    return freshness("stale", " · ".join(reasons)) if reasons else freshness("current")


def texture_info(character_name: str, tsig: str, *, worn_entry: Optional[Dict[str, Any]],
                 users: List[Tuple[str, bool]], models: Dict[str, Dict[str, Any]], saved: List[Dict[str, Any]],
                 worn: str, profile: Dict[str, Any], bsig: str, base_reason: str) -> Dict[str, Any]:
    """One painted body of the retexture mode (``tsig`` "" = the worn
    outfit's pending entry): ``{key, texture_signature, current, pending,
    outfits: [{signature, name, worn, has_model}], views, image_meta,
    painted, dress_text, created_at, status, error, run_kind,
    queue_position, last_run, worn_outfit, regenerate_from, blocked, url,
    freshness, outfit_url}``: ``url`` the stored painted body (the texture
    body itself, without own-mesh garments — ``texture_body_url``),
    ``outfit_url`` the worn outfit's served model (garments assembled) on
    the current entry once it is built. ``current`` only for the worn
    outfit's body; ``blocked`` (server English,
    the tab translates): ``generate`` (``paint``) / ``regenerate``
    (``repaint``), a run of the tab's queue on it first (``Locked: …``).
    ``status``: running / queued / failed (its last run) / ready (painted) /
    missing."""
    from app.core import base_body
    current = worn_entry is not None and worn_entry["tsig"] == tsig
    key = tsig or (worn_entry or {}).get("signature") or ""
    keys = [key] + ([worn_entry["signature"]] if current and worn_entry["signature"] != key else [])
    if tsig:
        views, view_meta = _view_urls(character_name, tsig)
        body = base_body.texture_body_path(character_name, tsig)
        painted = body.is_file()
        record = base_body._ref_sidecar(body) if painted else {}
        dress = str(base_body._ref_sidecar(base_body._texture_view(character_name, "front", tsig))
                    .get("dress_text") or "")
    else:
        views, view_meta, painted, record, dress = {}, {}, False, {}, ""
    outfits = [{"signature": sig, "name": outfit_label(character_name, sig, models=models, saved=saved),
                "worn": sig == worn, "has_model": has_model} for sig, has_model in users]
    outfits.sort(key=lambda o: (not o["worn"], not o["has_model"], o["name"], o["signature"]))
    candidates = ([worn_entry["signature"]] if current else []) + [o["signature"] for o in outfits]
    source = texture_source(character_name, tsig, candidates, profile=profile, bsig=bsig) if tsig else ""
    run, kind, position = _keys_state(character_name, keys)
    lasts = [dict(_results[(character_name, k)]) for k in keys if (character_name, k) in _results]
    last = max(lasts, key=lambda r: str(r.get("finished_at") or "")) if lasts else {}
    if run:
        status, error = run, ""
    elif last and not last.get("ok"):
        status, error = "failed", str(last.get("error") or "")
    else:
        status, error = ("ready" if painted else "missing"), ""
    lock = (LOCKED_RUNNING if run == "running" else LOCKED_QUEUED) if run else ""
    if not current:
        generate = NOT_WORN_TEXTURE
    elif base_reason:
        generate = base_reason
    elif not worn_entry["views_missing"] and worn_entry["model"]:
        generate = WORN_MODEL_PRESENT
    else:
        generate = ""
    regenerate = PENDING_NO_BODY if not tsig else (NO_SOURCE if not source else base_reason)
    worn_outfit = None
    if current:
        worn_outfit = {"signature": worn_entry["signature"],
                       "name": _outfit_name({"pieces": worn_entry["pieces"]}, saved),
                       "views_missing": list(worn_entry["views_missing"]),
                       "image_jobs": int(worn_entry["image_jobs"]), "model": bool(worn_entry["model"])}
    return {"key": key, "texture_signature": tsig or None, "current": current, "pending": not tsig,
            "outfits": outfits, "views": views, "image_meta": view_meta, "painted": painted,
            "dress_text": dress, "created_at": record.get("created_at") or None,
            "status": status, "error": error, "run_kind": kind, "queue_position": position,
            "last_run": last or None, "worn_outfit": worn_outfit, "regenerate_from": source or None,
            "blocked": {"generate": lock or generate, "regenerate": lock or regenerate},
            "url": texture_body_url(character_name, tsig) if painted else None,
            "freshness": (texture_body_freshness(character_name, record, painted=painted, source=source, bsig=bsig)
                          if tsig else None),
            "outfit_url": (f"/characters/{quote(character_name, safe='')}/model3d/file"
                           if worn_outfit and worn_outfit["model"] else None)}


def textures(character_name: str, *, profile: Dict[str, Any], bsig: str, models: Dict[str, Dict[str, Any]],
             saved: List[Dict[str, Any]], worn: str) -> List[Dict[str, Any]]:
    """The retexture mode's painted bodies (``texture_info`` each): every
    texture a stored outfit model names, that has a stored painted body or
    store view, and the worn outfit's — which is ALWAYS listed, first, and
    is the only ``current`` one (pending while its dressed views are
    missing). The others follow, newest first, each with the outfits that
    use it (model or dressed front)."""
    from app.core import base_body
    from app.models.character import get_character_dir
    worn_entry = worn_texture(character_name, profile=profile, bsig=bsig)
    users: Dict[str, Dict[str, bool]] = {}
    for sig, meta in models.items():
        tsig = meta.get("texture_signature")
        if base_body.is_texture_signature(tsig):
            users.setdefault(str(tsig), {})[sig] = True
    tsigs = set(users)
    root = get_character_dir(character_name)
    for folder, pattern in ((root / "model3d" / base_body.TEXTURE_DIR, "tex*.json"),
                            (base_body.texture_refs_dir(character_name), "tpose_tex*.json")):
        if folder.is_dir():
            for path in folder.glob(pattern):
                tsig = path.stem.rsplit("_", 1)[-1]
                if base_body.is_texture_signature(tsig):
                    tsigs.add(tsig)
    if worn_entry is not None and worn_entry["tsig"]:
        tsigs.add(worn_entry["tsig"])
    for tsig, sigs in _texture_front_users(character_name).items():
        if tsig in tsigs:
            for sig in sigs:
                users.setdefault(tsig, {}).setdefault(sig, sig in models)
    if worn_entry is not None and worn_entry["tsig"]:
        users.setdefault(worn_entry["tsig"], {}).setdefault(worn, worn in models)
    base_reason = _base_ready(character_name, bsig)
    out = []
    keys = sorted(tsigs) + ([""] if worn_entry is not None and not worn_entry["tsig"] else [])
    for tsig in keys:
        try:
            out.append(texture_info(character_name, tsig, worn_entry=worn_entry,
                                    users=sorted((users.get(tsig) or {}).items()), models=models, saved=saved,
                                    worn=worn, profile=profile, bsig=bsig, base_reason=base_reason))
        except Exception as e:  # noqa: BLE001 — one unreadable body does not hide the others
            logger.exception("Painted body %s of %s unreadable", tsig or "(pending)", character_name)
            out.append({"key": tsig or worn, "texture_signature": tsig or None, "current": False,
                        "pending": not tsig, "outfits": [], "views": {}, "painted": False, "dress_text": "",
                        "status": "failed", "error": str(e), "worn_outfit": None, "blocked": {}})
    out.sort(key=lambda t: str(t.get("created_at") or ""), reverse=True)
    out.sort(key=lambda t: not t.get("current"))
    return out


def paint_worn(character_name: str, key: str) -> Dict[str, Any]:
    """The ``paint`` run (Generate / Build outfit model): the worn outfit's
    missing dressed views (``generate_dressed_images`` without ``force`` —
    image jobs only for what is missing, a view the texture store holds is
    copied), then its outfit model through ``model3d.generate_for_current_outfit``
    without ``force`` — a stored painted body of its key is reused (CPU),
    else it is painted (CPU worker). Never a hub job. Caller holds the
    character's generation slot. ``{ok, error}``."""
    from app.core import base_body, model3d
    profile = _profile(character_name)
    bsig = base_body.base_signature(character_name, profile=profile)
    worn = worn_texture(character_name, profile=profile, bsig=bsig)
    if worn is None or key not in (worn["key"], worn["signature"]):
        return {"ok": False, "error": NOT_WORN_TEXTURE}
    signature = worn["signature"]
    if worn["views_missing"]:
        logger.info("Painted body of %s: rendering the worn outfit's dressed views %s (outfit %s)", character_name,
                    worn["views_missing"], signature)
        base_body.generate_dressed_images(character_name, pieces=worn["pieces"], items=worn["items"],
                                          signature=signature, force=False)
        missing = [v for v in base_body.dressed_views()
                   if base_body.dressed_image(character_name, v, signature, bsig) is None]
        if missing:
            with base_body._status_lock:
                failure = dict(base_body._outfit_failed.get((character_name, signature)) or {})
            return {"ok": False, "error": str(failure.get("error") or "Dressed views missing: " + ", ".join(missing))}
    logger.info("Painted body of %s: building the worn outfit's model %s", character_name, signature)
    result = model3d.generate_for_current_outfit(character_name, signature=signature, force=False)
    return {"ok": bool(result.get("ok")), "error": str(result.get("error") or "")}


def repaint_texture(character_name: str, tsig: str) -> Dict[str, Any]:
    """The ``repaint`` run (Regenerate a painted body): an outfit standing
    on ``tsig`` (``texture_source``, the worn outfit first) gets every
    dressed view rendered anew (``generate_dressed_images(force=True)``:
    image jobs, the store follows), then its outfit model built forced — the
    body painted again (CPU worker, no hub job). Caller holds the
    character's generation slot. ``{ok, error}``."""
    from app.core import base_body, model3d
    from app.core.model_refs import current_outfit_state
    profile = _profile(character_name)
    bsig = base_body.base_signature(character_name, profile=profile)
    users = [current_outfit_state(character_name)[2]]
    users += [sig for sig, meta in _outfit_models(character_name).items() if meta.get("texture_signature") == tsig]
    users += _texture_front_users(character_name).get(tsig) or []
    source = texture_source(character_name, tsig, users, profile=profile, bsig=bsig)
    if not source:
        return {"ok": False, "error": NO_SOURCE}
    front = base_body.dressed_image(character_name, "front", source, bsig)
    manifest = model3d._ref_manifest(front) if front is not None else {}
    logger.info("Painted body %s of %s: rendering the dressed views anew and painting it (outfit %s)", tsig,
                character_name, source)
    base_body.generate_dressed_images(character_name, pieces=manifest.get("pieces") or {},
                                      items=manifest.get("items") or [], signature=source, force=True)
    missing = [v for v in base_body.dressed_views()
               if base_body.dressed_image(character_name, v, source, bsig) is None]
    if missing:
        with base_body._status_lock:
            failure = dict(base_body._outfit_failed.get((character_name, source)) or {})
        return {"ok": False, "error": str(failure.get("error") or "Dressed views missing: " + ", ".join(missing))}
    result = model3d.generate_for_current_outfit(character_name, signature=source, force=True)
    return {"ok": bool(result.get("ok")), "error": str(result.get("error") or "")}


# --- info ---------------------------------------------------------------------------

def _outfits_on_body(character_name: str, body_id: str, models: Dict[str, Dict[str, Any]],
                     saved: List[Dict[str, Any]], worn: str) -> List[Dict[str, Any]]:
    """The outfit models on the body: ``{signature, name, worn, stale_reason,
    missing_mesh_items, meta}`` — ``missing_mesh_items`` the own-mesh pieces
    it is missing because they have no accepted fit yet (ruling 2026-11-10,
    ``base_body.mesh_items_missing``): ``[{item_id, name, reason}]``."""
    from app.core import base_body
    from app.models.inventory import get_item
    out = []
    for sig, meta in models.items():
        if meta.get("body_id") != body_id:
            continue
        stale = base_body.outfit_body_stale(character_name, meta)
        missing = [{"item_id": item_id, "name": str((get_item(item_id) or {}).get("name") or item_id),
                    "reason": reason} for item_id, reason in base_body.mesh_items_missing(character_name, meta)]
        out.append({"signature": sig, "name": _outfit_name(meta, saved), "worn": sig == worn,
                    "stale_reason": stale or None, "missing_mesh_items": missing, "meta": meta})
    return sorted(out, key=lambda e: (not e["worn"], e["name"], e["signature"]))


def _run_state(character_name: str, body_id: str) -> Tuple[str, Optional[str], Optional[int]]:
    """``(state, kind, position)``: running / queued / "" of the tab's own runs."""
    with _lock:
        current = _current.get(character_name)
        if current is not None and current.body_id == body_id:
            return "running", current.kind, None
        for n, job in enumerate(_queues.get(character_name) or (), start=1):
            if job.body_id == body_id:
                return "queued", job.kind, n
    return "", None, None


def stale_posture(character_name: str, meta: Dict[str, Any]) -> str:
    from app.core.outfit_body_posture import stale_reason
    try:
        return stale_reason(character_name, meta)
    except Exception:  # noqa: BLE001 — a display hint, never a failure
        return ""


def _blocked(*, run: str, kind: Optional[str], source: str, worn_entry: bool,
             built: bool, unrigged: bool, fits: int, stored: bool, views_missing: List[str]) -> Dict[str, str]:
    """Why each action of the body cannot start now (server English the tab
    translates), "" when it can: ``regenerate`` / ``rerig`` / ``refit`` /
    ``delete`` / ``views`` (the worn outfit's Generate views). A run the
    tab's own queue holds on the body comes first (``Locked: …``); the tab
    adds what only it knows (a request in flight)."""
    if run == "running":
        lock = LOCKED_BUILD if kind == "build" else LOCKED_RUNNING
    elif run == "queued":
        lock = LOCKED_QUEUED
    else:
        lock = ""
    out = {
        "regenerate": "" if source else (WORN_VIEWS_MISSING if worn_entry else NO_SOURCE),
        "rerig": "" if unrigged else NO_UNRIGGED,
        "refit": "" if built and fits else (NO_GARMENTS if built else NO_MODEL),
        "delete": "" if stored else NOTHING_STORED,
        "views": ("" if views_missing else WORN_VIEWS_PRESENT) if worn_entry else NOT_WORN_BODY,
    }
    return {k: lock or v for k, v in out.items()}


def body_info(character_name: str, body_id: str, *, profile: Dict[str, Any], bsig: str,
              models: Dict[str, Dict[str, Any]], saved: List[Dict[str, Any]], worn: str,
              worn_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One body of the tab. ``worn_entry``: ``worn_body`` when the worn
    outfit stands (or will stand) on this body — it then carries
    ``worn_outfit`` ``{signature, name, predicted, views_missing,
    image_jobs}`` and its view tiles say to Generate views while no outfit
    stands on them yet; an image such a tile still finds loses its freshness
    badge and gets ``pending_note`` (``PENDING_TEXTURE_VIEW`` /
    ``PENDING_BODY_VIEW``) — it is not this body's current dressed view. ``current``: the worn outfit's
    body (``worn_entry`` names it). ``orphaned``: never built, no outfit standing on its
    views, no outfit model on it, not the worn one (ruling 2026-11-10: listed
    collapsed, never hidden — the artefact GC keeps such a body while a live
    outfit names its texture). ``blocked``: ``_blocked``."""
    from app.core import base_body, model3d
    from app.core.model_overview import freshness, outfit_body_overview
    if worn_entry is not None and worn_entry.get("body_id") != body_id:
        worn_entry = None
    path = base_body.outfit_body_path(character_name, body_id)
    meta = _json(path.with_suffix(".json")) if path.is_file() else {}
    record = _body_record(character_name, body_id)
    tsig = str(record.get("texture_signature") or "") or (str(worn_entry["tsig"]) if worn_entry else "")
    on_body = _outfits_on_body(character_name, body_id, models, saved, worn)
    views, view_meta = _view_urls(character_name, body_id)
    source = source_outfit(character_name, body_id, profile=profile, outfit_models=models)
    dress = ""
    if base_body.is_texture_signature(tsig):
        dress = str(base_body._ref_sidecar(base_body._texture_view(character_name, "front", tsig))
                    .get("dress_text") or "")
    reasons = []
    if record.get("base_signature") and bsig and record.get("base_signature") != bsig:
        reasons.append(base_body.OLDER_BASE)
    if record and record.get("version") != base_body.OUTFIT_BODY_VERSION:
        reasons.append(OLDER_BODY_VERSION)
    if source and record.get("views") != base_body.texture_view_shas(character_name, source, bsig):
        reasons.append(DRESSED_VIEWS_CHANGED)
    if meta and stale_posture(character_name, meta):
        reasons.append(POSTURE_NOT_MATCHED)
    if not path.is_file():
        fresh = freshness("missing", NOT_BUILT)
    elif reasons:
        fresh = freshness("stale", " · ".join(reasons))
    elif not source and not on_body:
        fresh = freshness("missing", NO_OUTFIT_ON_IT)
    else:
        fresh = freshness("current")
    run, kind, position = _run_state(character_name, body_id)
    if not run and any(sig == body_id and name == character_name for name, sig in model3d.active_stages().values()):
        run, kind = "running", "build"
    last = dict(_results.get((character_name, body_id)) or {})
    if run:
        status, error = run, ""
    elif last and not last.get("ok"):
        status, error = "failed", str(last.get("error") or "")
    elif not path.is_file():
        status, error = "missing", ""
    elif meta.get("rig_error"):
        status, error = "failed", str(meta["rig_error"])
    elif meta.get("rig") != "mixamo":
        status, error = "unrigged", ""
    else:
        status, error = "ready", ""
    overview = outfit_body_overview(character_name, body_id) if path.is_file() else None
    unrigged = path.parent / "unrigged" / path.name
    candidates = [source, str(record.get("built_for") or "")] + [e["signature"] for e in on_body]
    view_info = view_infos(character_name, body_id, record=record, tsig=tsig, source=source, bsig=bsig,
                           profile=profile, candidates=candidates, last=last)
    if worn_entry is not None and not source:
        # No outfit stands on the views yet: the worn outfit's own Generate views makes them. An image
        # the tile still finds (the texture store's view made for another outfit, or an older mesher
        # input of the body) is NOT this body's current dressed view: no freshness badge, an honest note.
        for entry in view_info.values():
            if entry.get("blocked") == NO_SOURCE:
                entry["blocked"] = WORN_VIEWS_MISSING
            if entry.get("url"):
                entry["meta"] = {**(entry.get("meta") or {}), "freshness": None}
                entry["pending_note"] = PENDING_TEXTURE_VIEW if entry.get("source") == "texture" \
                    else PENDING_BODY_VIEW
    fits = fits_on_body(character_name, body_id, profile=profile, on_body=on_body)
    stored = path.is_file() or unrigged.is_file() or any(views.values())
    worn_outfit = None
    if worn_entry is not None:
        worn_outfit = {"signature": worn_entry["signature"],
                       "name": _outfit_name({"pieces": worn_entry["pieces"]}, saved),
                       "predicted": bool(worn_entry["predicted"]),
                       "views_missing": list(worn_entry["views_missing"]),
                       "image_jobs": int(worn_entry["image_jobs"])}
    return {
        "body_id": body_id, "texture_signature": tsig or None, "status": status, "error": error,
        "run_kind": kind, "queue_position": position, "last_run": last or None,
        "created_at": meta.get("created_at") or None,
        "url": model3d.signature_model_url(character_name, body_id) if path.is_file() else None,
        "views": views, "image_meta": view_meta, "used_views": list(record.get("used_views") or []),
        "view_warnings": [w for w in record.get("view_warnings") or [] if isinstance(w, str)],
        "dress_text": dress, "freshness": fresh, "view_info": view_info,
        "outfits": [{k: v for k, v in e.items() if k != "meta"} for e in on_body],
        "steps": (overview or {}).get("steps") or [],
        "collision": meta.get("collision") if path.is_file() else None,
        "fits": fits,
        "can_regenerate": bool(source), "regenerate_from": source or None,
        "can_rerig": unrigged.is_file(),
        "worn_outfit": worn_outfit,
        # The worn outfit stands (or will stand) on THIS body — never a body another outfit uses, nor an
        # older body an outdated model of the worn outfit still names.
        "current": worn_entry is not None,
        "orphaned": not path.is_file() and not source and not on_body and worn_entry is None and not run,
        "blocked": _blocked(run=run, kind=kind, source=source, worn_entry=worn_entry is not None,
                            built=path.is_file(), unrigged=unrigged.is_file(), fits=len(fits), stored=stored,
                            views_missing=list((worn_entry or {}).get("views_missing") or [])),
    }


def queue_state(character_name: str) -> Dict[str, Any]:
    def entry(job: _Job) -> Dict[str, Any]:
        # ``view`` only on a view run.
        return {"kind": job.kind, "body_id": job.body_id, "item_id": job.item_id or None,
                **({"view": job.view} if job.view else {})}

    with _lock:
        current = _current.get(character_name)
        waiting = [entry(j) for j in _queues.get(character_name) or ()]
        running = entry(current) if current else None
    return {"running": running,
            "waiting": waiting}


def info(character_name: str) -> Dict[str, Any]:
    """The tab payload: ``{humanoid, pipeline, mode, signature, bodies: [...],
    textures: [...], queue, active, generation_running}``. ``bodies`` only
    in mesh mode or when bodies are stored (the other mode's bodies stay
    stored); ``textures`` (the painted bodies of the retexture mode,
    ``textures``) only in retexture mode."""
    from app.core import base_body, model3d
    from app.core.model_refs import current_outfit_state, is_humanoid
    profile = _profile(character_name)
    humanoid = bool(is_humanoid(character_name, profile=profile))
    pipeline = humanoid and base_body.is_base_pipeline(character_name, profile=profile)
    mode = base_body.outfit_body_mode(character_name, profile=profile)
    bsig = base_body.base_signature(character_name, profile=profile) if humanoid else ""
    out: Dict[str, Any] = {"humanoid": humanoid, "pipeline": pipeline, "mode": mode, "signature": bsig,
                           "bodies": [], "textures": [], "queue": queue_state(character_name),
                           "generation_running": model3d.generation_running(character_name)}
    if not pipeline:
        out["active"] = bool(out["queue"]["running"] or out["queue"]["waiting"])
        return out
    try:
        worn = current_outfit_state(character_name)[2]
    except Exception:  # noqa: BLE001
        worn = ""
    models = _outfit_models(character_name)
    saved = _saved_outfits(character_name)
    worn_entry = worn_body(character_name, profile=profile, bsig=bsig)
    for body_id in body_ids(character_name, models, extra=(worn_entry or {}).get("body_id")):
        try:
            out["bodies"].append(body_info(character_name, body_id, profile=profile, bsig=bsig, models=models,
                                           saved=saved, worn=worn, worn_entry=worn_entry))
        except Exception as e:  # noqa: BLE001 — one unreadable body does not hide the others
            logger.exception("Outfit body %s of %s unreadable", body_id, character_name)
            out["bodies"].append({"body_id": body_id, "status": "failed", "error": str(e), "views": {},
                                  "outfits": [], "steps": [], "fits": [], "freshness": None, "worn_outfit": None,
                                  "current": False, "orphaned": False, "blocked": {}})
    # The worn outfit's body first, the orphaned ones last, else the newest (stable sorts, the last key first).
    out["bodies"].sort(key=lambda b: str(b.get("created_at") or ""), reverse=True)
    out["bodies"].sort(key=lambda b: (bool(b.get("orphaned")), not b.get("current")))
    if mode != base_body.MESH_MODE:
        out["textures"] = textures(character_name, profile=profile, bsig=bsig, models=models, saved=saved,
                                   worn=worn)
    out["active"] = bool(out["queue"]["running"] or out["queue"]["waiting"]
                         or any(b.get("status") == "running" for b in out["bodies"]))
    return out


# --- runs ---------------------------------------------------------------------------

def check_run(character_name: str, kind: str, body_id: str, item_id: str = "", view: str = "") -> None:
    """``ValueError`` (400) / ``LookupError`` (409) before a run is queued:
    an unknown kind, id or view, off the pipeline, not mesh mode
    (regenerate, views), nothing to mesh from, no unrigged mesh (re-rig), no
    body (re-rig / refit), a view that cannot be rendered (``view_blocked``),
    the worn outfit's views present or its base views missing (views).
    ``UnknownBody`` (404, a ``LookupError``): a ``views`` run on a body the
    worn outfit does not stand on.

    The retexture mode's runs (``TEXTURE_RUN_KINDS``, ``body_id`` = a
    painted body's key): off that mode ``NOT_RETEXTURE_MODE``; the base model
    or a dressed base view missing (409); ``paint`` on anything but the worn
    outfit's entry ``UnknownBody`` (``NOT_WORN_TEXTURE``), its model current
    and nothing missing ``WORN_MODEL_PRESENT``; ``repaint`` without an
    outfit standing on the texture ``NO_SOURCE``."""
    from app.core import base_body
    if kind not in RUN_KINDS:
        raise ValueError(f"run must be one of {', '.join(RUN_KINDS)}")
    if kind in TEXTURE_RUN_KINDS:
        _check_texture_run(character_name, kind, body_id, item_id, view)
        return
    if not base_body.is_outfit_body_signature(body_id):
        raise ValueError("not an outfit body id")
    if (kind == "view") != bool(view):
        raise ValueError("a view run names one view, the other runs none")
    if view and view not in base_body.BASE_VIEWS:
        raise ValueError(f"view must be one of {', '.join(base_body.BASE_VIEWS)}")
    profile = _profile(character_name)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        raise LookupError(NOT_PIPELINE)
    path = base_body.outfit_body_path(character_name, body_id)
    if kind == "view":
        blocked = view_blocked(character_name, body_id, view, profile=profile)
        if blocked:
            raise LookupError(blocked)
    elif kind == "regenerate":
        if base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
            raise LookupError(NOT_MESH_MODE)
        if not source_outfit(character_name, body_id, profile=profile):
            raise LookupError(NO_SOURCE)
    elif kind == "views":
        if base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
            raise LookupError(NOT_MESH_MODE)
        bsig = base_body.base_signature(character_name, profile=profile)
        worn = worn_body(character_name, profile=profile, bsig=bsig)
        if worn is None or worn["body_id"] != body_id:
            raise UnknownBody(NOT_WORN_BODY)
        if not worn["views_missing"]:
            raise LookupError(WORN_VIEWS_PRESENT)
        from app.core.model_refs import find_ref_image
        if any(find_ref_image(character_name, base_body._kind(v), bsig) is None for v in base_body.dressed_views()):
            raise LookupError(base_body.BASE_IMAGES_MISSING)
    elif kind == "rerig":
        if not (path.parent / "unrigged" / path.name).is_file():
            raise LookupError(NO_UNRIGGED)
    elif not path.is_file():
        raise LookupError(NO_BODY)
    if item_id and (kind != "refit" or item_id not in [f["item_id"] for f in fits_on_body(
            character_name, body_id, profile=profile)]):
        raise ValueError(f"{item_id[:60]!r} is no garment on this outfit body")


def _check_texture_run(character_name: str, kind: str, key: str, item_id: str, view: str) -> None:
    """``check_run`` for ``paint`` / ``repaint`` (its docstring)."""
    from app.core import base_body
    from app.core.model_refs import current_outfit_state
    if item_id or view:
        raise ValueError("a painted body's run names no garment and no view")
    if kind == "repaint" and not base_body.is_texture_signature(key):
        raise ValueError("not a texture signature")
    if kind == "paint" and not (base_body.is_texture_signature(key) or _OUTFIT_SIG_RE.fullmatch(key or "")):
        raise ValueError("not a painted body key")
    profile = _profile(character_name)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        raise LookupError(NOT_PIPELINE)
    if base_body.outfit_body_mode(character_name, profile=profile) == base_body.MESH_MODE:
        raise LookupError(NOT_RETEXTURE_MODE)
    bsig = base_body.base_signature(character_name, profile=profile)
    if kind == "paint":
        worn = worn_texture(character_name, profile=profile, bsig=bsig)
        if worn is None or key not in (worn["key"], worn["signature"]):
            raise UnknownBody(NOT_WORN_TEXTURE)
    reason = _base_ready(character_name, bsig)
    if reason:
        raise LookupError(reason)
    if kind == "paint":
        if not worn["views_missing"] and worn["model"]:
            raise LookupError(WORN_MODEL_PRESENT)
        return
    users = [current_outfit_state(character_name)[2]]
    users += [sig for sig, meta in _outfit_models(character_name).items() if meta.get("texture_signature") == key]
    users += _texture_front_users(character_name).get(key) or []
    if not texture_source(character_name, key, users, profile=profile, bsig=bsig):
        raise LookupError(NO_SOURCE)


def _position_locked(character_name: str, job: _Job) -> Dict[str, Any]:
    """``{started, queued, position, behind}`` of ``job``: started = the
    worker works on it or takes it next with nothing ahead; else its 1-based
    place among the waiting runs and the run right ahead of it."""
    current = _current.get(character_name)
    waiting = list(_queues.get(character_name) or ())
    position = waiting.index(job) + 1 if job in waiting else 0
    if current is job or (current is None and position == 1):
        return {"started": True, "queued": False, "position": 0, "behind": None}
    ahead = waiting[position - 2] if position > 1 else current
    return {"started": False, "queued": True, "position": position,
            "behind": {"kind": ahead.kind, "body_id": ahead.body_id} if ahead is not None else None}


def start(character_name: str, kind: str, body_id: str, item_id: str = "", view: str = "") -> Dict[str, Any]:
    """Queue a run on the body (``check_run`` first) in the character's FIFO
    — never refused for a running run. An identical waiting run is not added
    twice. ``{kind, body_id, started, queued, position, behind}``:
    ``started`` True when the worker took it at once (it may still wait for
    another 3D run of the character to end — ``generation_running``)."""
    check_run(character_name, kind, body_id, item_id, view)
    wanted = _Job(kind, body_id, item_id, view)
    with _lock:
        queue = _queues.setdefault(character_name, deque())
        job = next((j for j in queue if j.key() == wanted.key()), None)
        if job is None:
            job = wanted
            queue.append(job)
        _results.pop((character_name, body_id), None)
        if character_name not in _active:
            _active.add(character_name)
            threading.Thread(target=_worker, args=(character_name,), daemon=True,
                             name=f"outfit-body-{character_name}").start()
        out = _position_locked(character_name, job)
    return {"kind": kind, "body_id": body_id, "item_id": item_id or None, "view": view or None, **out}


class RunStarted(Exception):
    """``cancel``: the body's run has started — it cannot be cancelled."""


ALREADY_RUNNING = "The run on this outfit body has already started — a running run cannot be cancelled"
NOT_QUEUED = "No run on this outfit body waits in the queue"
CANCELLED = "Cancelled while queued"


def cancel(character_name: str, body_id: str, view: str = "") -> Dict[str, Any]:
    """Take the body's WAITING runs (``view``: only the waiting run of that
    dressed view) out of the character's FIFO (atomic under ``_lock``; the
    runs behind them move up). The run in flight is never touched:
    ``RunStarted`` when the body (view) only has that one, ``LookupError``
    when no run is on it. A cancelled job's waiter gets ``{ok: False,
    cancelled: True, error}``; the body's last result is not rewritten.
    ``{body_id, cancelled (count), queue}`` (``queue_state``'s shape)."""
    def matches(job: _Job) -> bool:
        return job.body_id == body_id and (not view or (job.kind == "view" and job.view == view))

    with _lock:
        queue = _queues.get(character_name)
        dropped = [j for j in queue or () if matches(j)]
        current = _current.get(character_name)
        if not dropped:
            if current is not None and matches(current):
                raise RunStarted(ALREADY_RUNNING)
            raise LookupError(NOT_QUEUED)
        for job in dropped:
            queue.remove(job)
            job.result = {"ok": False, "cancelled": True, "error": CANCELLED}
            job.done.set()
    logger.info("Outfit body %s of %s: %d waiting run(s) cancelled", body_id, character_name, len(dropped))
    return {"body_id": body_id, "cancelled": len(dropped), "queue": queue_state(character_name)}


def _worker(character_name: str) -> None:
    from app.core import model3d
    while True:
        with _lock:
            queue = _queues.get(character_name)
            if not queue:
                _active.discard(character_name)
                _current.pop(character_name, None)
                return
            job = queue.popleft()
            _current[character_name] = job
        result: Dict[str, Any] = {"ok": False, "error": "Outfit body run failed"}
        try:
            with model3d.generation_slot(character_name):
                result = _run(character_name, job)
        except Exception as e:  # noqa: BLE001 — a worker reports, never raises
            logger.exception("Outfit body %s of %s: %s failed", job.body_id, character_name, job.kind)
            result = {"ok": False, "error": str(e) or type(e).__name__}
        finally:
            from app.core.timeutils import utc_now_iso
            job.result = result
            with _lock:
                _results[(character_name, job.body_id)] = {
                    "kind": job.kind, "view": job.view or None, "ok": bool(result.get("ok")),
                    "error": str(result.get("error") or ""), "finished_at": utc_now_iso(),
                    "detail": {k: result[k] for k in ("fitted", "failed", "skipped") if k in result}}
                if _current.get(character_name) is job:
                    _current.pop(character_name, None)
            job.done.set()


def _tracked(character_name: str, label: str):
    """A task-queue display row for the run (``track_start``); (queue, id) or (None, "")."""
    try:
        from app.core.task_queue import get_task_queue
        queue = get_task_queue()
        return queue, queue.track_start("model3d_outfit_body", label, agent_name=character_name,
                                        start_running=True)
    except Exception:  # noqa: BLE001 — the display row is optional
        logger.debug("Outfit body run of %s not tracked", character_name, exc_info=True)
        return None, ""


def _run(character_name: str, job: _Job) -> Dict[str, Any]:
    """One run, inside the generation slot. The checks of ``check_run``
    again (the state may have changed while it waited)."""
    from app.core import base_body, model3d
    try:
        check_run(character_name, job.kind, job.body_id, job.item_id, job.view)
    except (ValueError, LookupError) as e:
        return {"ok": False, "error": str(e)}
    labels = {"regenerate": "Outfit body", "rerig": "Re-rig outfit body", "refit": "Re-fit on outfit body",
              "view": f"Outfit body {job.view} view", "views": "Outfit body dressed views",
              "paint": "Worn outfit model", "repaint": "Painted body"}
    queue, task_id = _tracked(character_name, f"{labels[job.kind]}: {character_name} ({job.body_id})")
    result: Dict[str, Any] = {"ok": False, "error": ""}
    try:
        if job.kind == "regenerate":
            source = source_outfit(character_name, job.body_id)
            built = base_body.prepare_outfit_body(character_name, source, rebuild=True)
            if built is None:
                result = {"ok": False, "error": NO_SOURCE}
            elif built.get("body_id") != job.body_id:
                result = {"ok": False, "error": f"the outfit's views stand for {built.get('body_id')} now"}
            else:
                result = {"ok": bool(built.get("ok")), "error": str(built.get("error") or "")}
        elif job.kind == "view":
            result = render_view(character_name, job.body_id, job.view)
        elif job.kind == "views":
            result = render_worn_views(character_name, job.body_id)
        elif job.kind == "paint":
            result = paint_worn(character_name, job.body_id)
        elif job.kind == "repaint":
            result = repaint_texture(character_name, job.body_id)
        elif job.kind == "rerig":
            rigged = model3d.rerig_model(character_name, job.body_id, track_id=task_id)
            result = {"ok": bool(rigged.get("ok")), "error": str(rigged.get("error") or "")}
        else:
            # A body from before the posture match gets its base's posture first (CPU);
            # the refit below then fits onto the turned body.
            posture = match_posture(character_name, job.body_id)
            if posture and not posture.get("ok"):
                logger.warning("Outfit body %s of %s: posture match failed (%s) — refitted as it is",
                               job.body_id, character_name, posture.get("error"))
            result = refit_body(character_name, job.body_id, job.item_id)
            if posture.get("changed"):
                rebuild_worn_on(character_name, job.body_id)
    finally:
        if queue is not None and task_id:
            try:
                queue.track_finish(task_id, error="" if result.get("ok") else result.get("error") or "failed")
            except Exception:  # noqa: BLE001
                logger.debug("Outfit body track %s not finished", task_id, exc_info=True)
    return result


def delete(character_name: str, body_id: str) -> Dict[str, Any]:
    """Delete the body and its chain (``artefact_graph.delete_body``).
    ``LookupError`` while a run of the tab waits for or works on it."""
    from app.core import artefact_graph
    state, _kind, _position = _run_state(character_name, body_id)
    if state:
        raise LookupError("A run on this outfit body is " + state + " — delete it after the run")
    report = artefact_graph.delete_body(character_name, body_id)
    with _lock:
        _results.pop((character_name, body_id), None)
    return report
