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
gated fit). A view run does not cascade: the back follows the front through
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
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import quote

from app.core.log import get_logger

logger = get_logger("outfit_bodies")

RUN_KINDS = ("regenerate", "rerig", "refit", "view")
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


def body_ids(character_name: str, outfit_models: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    """Every outfit body the character has files of (model, refs) or an
    outfit model names, sorted."""
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
    with _lock:
        for job in list(_queues.get(character_name) or ()) + (
                [_current[character_name]] if character_name in _current else []):
            ids.add(job.body_id)
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
    """``{view: (running|queued, queue position)}`` of the body's view runs."""
    out: Dict[str, Tuple[str, Optional[int]]] = {}
    with _lock:
        current = _current.get(character_name)
        if current is not None and current.body_id == body_id and current.kind == "view":
            out[current.view] = ("running", None)
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


def body_info(character_name: str, body_id: str, *, profile: Dict[str, Any], bsig: str,
              models: Dict[str, Dict[str, Any]], saved: List[Dict[str, Any]], worn: str) -> Dict[str, Any]:
    from app.core import base_body, model3d
    from app.core.model_overview import freshness, outfit_body_overview
    path = base_body.outfit_body_path(character_name, body_id)
    meta = _json(path.with_suffix(".json")) if path.is_file() else {}
    record = _body_record(character_name, body_id)
    tsig = str(record.get("texture_signature") or "")
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
        "fits": fits_on_body(character_name, body_id, profile=profile, on_body=on_body),
        "can_regenerate": bool(source), "regenerate_from": source or None,
        "can_rerig": unrigged.is_file(),
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
    in mesh mode or when bodies are stored; ``textures`` (the painted bodies
    of the retexture mode: ``{texture_signature, outfits, views, painted,
    dress_text}``) only in retexture mode."""
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
    for body_id in body_ids(character_name, models):
        try:
            out["bodies"].append(body_info(character_name, body_id, profile=profile, bsig=bsig, models=models,
                                           saved=saved, worn=worn))
        except Exception as e:  # noqa: BLE001 — one unreadable body does not hide the others
            logger.exception("Outfit body %s of %s unreadable", body_id, character_name)
            out["bodies"].append({"body_id": body_id, "status": "failed", "error": str(e), "views": {},
                                  "outfits": [], "steps": [], "fits": [], "freshness": None})
    # The worn outfit's body first, then the newest (stable sorts, the last key first).
    out["bodies"].sort(key=lambda b: str(b.get("created_at") or ""), reverse=True)
    out["bodies"].sort(key=lambda b: not any(o.get("worn") for o in b.get("outfits") or []))
    if mode != base_body.MESH_MODE:
        for tsig, sigs in sorted(base_body.texture_users(character_name).items()):
            views, view_meta = _view_urls(character_name, tsig)
            try:
                painted = base_body.texture_body_path(character_name, tsig).is_file()
            except ValueError:
                painted = False
            out["textures"].append({
                "texture_signature": tsig,
                "outfits": [{"signature": s, "name": _outfit_name(models.get(s) or {}, saved), "worn": s == worn}
                            for s in sigs],
                "views": views, "image_meta": view_meta, "painted": painted,
                "dress_text": str(base_body._ref_sidecar(base_body._texture_view(character_name, "front", tsig))
                                  .get("dress_text") or "")})
    out["active"] = bool(out["queue"]["running"] or out["queue"]["waiting"]
                         or any(b.get("status") == "running" for b in out["bodies"]))
    return out


# --- runs ---------------------------------------------------------------------------

def check_run(character_name: str, kind: str, body_id: str, item_id: str = "", view: str = "") -> None:
    """``ValueError`` (400) / ``LookupError`` (409) before a run is queued:
    an unknown kind, id or view, off the pipeline, not mesh mode
    (regenerate), nothing to mesh from, no unrigged mesh (re-rig), no body
    (re-rig / refit), a view that cannot be rendered (``view_blocked``)."""
    from app.core import base_body
    if kind not in RUN_KINDS:
        raise ValueError(f"run must be one of {', '.join(RUN_KINDS)}")
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
    elif kind == "rerig":
        if not (path.parent / "unrigged" / path.name).is_file():
            raise LookupError(NO_UNRIGGED)
    elif not path.is_file():
        raise LookupError(NO_BODY)
    if item_id and (kind != "refit" or item_id not in [f["item_id"] for f in fits_on_body(
            character_name, body_id, profile=profile)]):
        raise ValueError(f"{item_id[:60]!r} is no garment on this outfit body")


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
              "view": f"Outfit body {job.view} view"}
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
