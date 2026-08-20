"""The scene-asset pipeline's HTTP surface — start a run, watch it, read it.

Thin adapter over :mod:`app.core.scene_asset` (``docs/scene-asset-pipeline.md``,
plan ``plan-assets-im-szenenkontext.md`` Etappe 4 Punkt 6): the route parses,
maps to HTTP and serves files; every decision — what runs, what counts as a
failure, where an artefact lands — stays in the core.

Four things live here:

* ``POST /generate`` starts the chain for ONE placement. 409 means this very
  placement is already running (the core's double-start guard, not an error).
* ``GET /status`` answers the poll the floor-plan editor runs while a job is
  out: is it still going, and what did the newest run for THIS placement say.
* ``GET /runs/{prop_id}`` is the same summary for every run a prop ever had.
* ``GET /runs/{prop_id}/{stamp}/{file}`` serves the four PNGs of one run —
  the triple preview reads its images from here.

The summary shape is the whole contract of the UI wave and is built in ONE
place (:func:`_summary`): the run's own ``result.json`` is a full record with
every attempt in it, and a strip showing three pictures needs the newest of
each plus the numbers a human judges by. Failures travel as the core's own
sentences — they are written to be read, not to be re-worded here.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.core.log import get_logger

logger = get_logger("scene_asset_route")

router = APIRouter(prefix="/world/scene-asset", tags=["world"])

#: How many runs a listing returns at most without being asked for more.
DEFAULT_RUN_LIMIT = 20


async def _body(request: Request) -> Dict[str, Any]:
    if (request.headers.get("content-length") or "0") == "0":
        return {}
    data = await request.json()
    return data if isinstance(data, dict) else {}


def _int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be a number")


# ── The placement a request talks about ─────────────────────────────────

def _placement(location_id: str, room_id: str, index: int) -> Dict[str, Any]:
    """The STORED placement, or the matching 404.

    Stored, not drafted: the pipeline renders the world as it is persisted, so
    a placement the floor-plan editor has not saved yet does not exist for it.
    The yard is an ordinary room here — its reserved id (``__ground__``) names
    it like any other; an empty ``room_id`` names nothing and is a 404.
    """
    from app.models.world import get_location_by_id

    loc = get_location_by_id(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    for room in (loc.get("rooms") or []):
        if str(room.get("id") or "") != str(room_id):
            continue
        props = ((room.get("layout") or {}).get("props") or [])
        if not 0 <= index < len(props):
            raise HTTPException(status_code=404, detail="Placement not found")
        entry = dict(props[index])
        entry["room_id"] = str(room_id)
        return entry
    raise HTTPException(status_code=404, detail="Room not found")


# ── Runs on disk ────────────────────────────────────────────────────────

def _run_root(prop_id: str) -> Optional[Path]:
    """``<prop dir>/scene_asset`` — None for an unknown or unsafe prop id."""
    from app.core.props import prop_dir
    from app.core.scene_asset import RUN_DIR_NAME

    base = prop_dir(prop_id)
    return (base / RUN_DIR_NAME) if base else None


def _summary(prop_id: str, stamp: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """One run's ``result.json`` reduced to what a reader needs.

    Two merges make the difference between "the record" and "the summary":
    the FILES of the last attempt are folded over the run's own (a failed run
    never promotes them, but its edit and cutout are exactly what explains the
    failure), and the checks are read from the last attempt as well — the run
    level carries them only on success.
    """
    attempts = rec.get("attempts") or []
    last = attempts[-1] if attempts else {}
    par = rec.get("params") or {}

    raw_files = dict(rec.get("files") or {})
    raw_files.update(last.get("files") or {})
    files: Dict[str, str] = {}
    for key, raw in raw_files.items():
        name = Path(str(raw)).name
        if name:
            files[key] = (f"/world/scene-asset/runs/{quote(prop_id)}"
                          f"/{quote(stamp)}/{quote(name)}")

    placement = rec.get("placement") or last.get("placement") or {}
    mesh = rec.get("mesh") or last.get("mesh") or {}
    stored = last.get("stored_placement") or {}
    return {
        "stamp": stamp,
        "ok": bool(rec.get("ok")),
        "location_id": rec.get("location_id", ""),
        "room_id": rec.get("room_id", ""),
        "index": rec.get("index", -1),
        "prop_id": prop_id,
        "subject": rec.get("subject", ""),
        "started_at": rec.get("started_at", ""),
        "finished_at": rec.get("finished_at", ""),
        "seconds": rec.get("seconds", 0.0),
        # WHICH way the insert went and on what — the two facts that explain a
        # result more often than any threshold does.
        "backend": rec.get("backend", ""),
        "path": rec.get("path", ""),
        "seed": last.get("seed"),
        "attempts": len(attempts),
        "variant": rec.get("variant"),
        "stored_variant": stored.get("variant"),
        "failures": list(rec.get("failures") or []),
        "checks": {
            "px_ratio": last.get("px_ratio"),
            "px_ratio_band": [par.get("px_ratio_min"), par.get("px_ratio_max")],
            "contact_ratio": placement.get("contact_ratio"),
            "contact_ratio_min": par.get("contact_ratio"),
            "yaw_deg": placement.get("yaw_deg"),
            "offset_y": placement.get("offset_y"),
            "sank_m": placement.get("sank_m"),
            "suggest_level": placement.get("suggest_level"),
            "mesh_ok": mesh.get("ok"),
            "mesh_height_m": mesh.get("height_m"),
            "mesh_backend": mesh.get("backend"),
            "mesh_error": mesh.get("error"),
        },
        "files": files,
    }


def _runs(prop_id: str, *, limit: int = 0) -> List[Dict[str, Any]]:
    """Every run of a prop, NEWEST FIRST — the directory names are timestamps
    (``%Y%m%d-%H%M%S``), so their reverse sort IS the chronology.

    A directory without a readable ``result.json`` is skipped rather than
    reported: it is a run that is still writing, or one whose process died,
    and neither has anything to show yet.
    """
    root = _run_root(prop_id)
    if not root or not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        if not entry.is_dir():
            continue
        try:
            rec = json.loads((entry / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        out.append(_summary(prop_id, entry.name, rec))
        if limit and len(out) >= limit:
            break
    return out


def _artifact_path(prop_id: str, rel: str) -> Optional[Path]:
    """``<stamp>/<file>.png`` → the artefact, or None when the reference is
    not a legal one.

    Deliberately strict, because this is the one place a client names a path:
    exactly the two segments the layout has, no empty/relative segment, no
    backslash, a PNG, and the resolved path must still sit inside the prop's
    run directory (a symlinked run directory pointing out of it is rejected
    too). Same rule as ``routes/assets.resolve_clip_path``.
    """
    segments = rel.split("/")
    if len(segments) != 2:
        return None
    for seg in segments:
        if not seg or seg in (".", "..") or "\\" in seg:
            return None
    if not segments[1].lower().endswith(".png"):
        return None
    root = _run_root(prop_id)
    if root is None:
        return None
    root = root.resolve()
    path = root.joinpath(*segments).resolve()
    if not path.is_relative_to(root):
        return None
    return path


# ── Routes ──────────────────────────────────────────────────────────────

@router.post("/generate")
async def scene_asset_generate(request: Request) -> Dict[str, Any]:
    """Start the scene-asset chain for ONE placement.

    Body: ``{location_id, room_id, placement_index}`` plus the optional
    overrides ``{subject, image_backend, mesh_backend, seed}``. ``subject``
    overrides what the prop's own description says the object is;
    ``image_backend``/``mesh_backend`` are globs pinning the two generators;
    ``seed`` fixes the FIRST attempt's seed (retries keep drawing fresh ones —
    a reproduction is a reproduction of one attempt, not of a loop).

    409 = this very placement is already running. That is the core's
    double-start guard reporting load, not a defect: the run in flight will
    write the variant this one would have.
    """
    from app.core.scene_asset import trigger_scene_asset

    body = await _body(request)
    location_id = str(body.get("location_id") or "").strip()
    room_id = str(body.get("room_id") or "")
    index = _int(body.get("placement_index"), "placement_index")
    placement = _placement(location_id, room_id, index)

    overrides: Dict[str, Any] = {}
    seed = body.get("seed")
    if seed is not None and f"{seed}".strip() != "":
        overrides["seed"] = _int(seed, "seed")

    started = trigger_scene_asset(
        location_id, room_id, index,
        subject=str(body.get("subject") or "").strip(),
        image_backend_glob=str(body.get("image_backend") or "").strip(),
        mesh_backend_glob=str(body.get("mesh_backend") or "").strip(),
        overrides=overrides or None)
    if not started:
        raise HTTPException(status_code=409,
                            detail="This placement is already generating")
    logger.info("Scene asset started for %s/%s#%d (%s)", location_id, room_id,
                index, placement.get("prop_id", ""))
    return {"status": "generating", "prop_id": placement.get("prop_id", "")}


@router.get("/status")
def scene_asset_status(location_id: str = "", room_id: str = "",
                       placement_index: int = 0) -> Dict[str, Any]:
    """Is a run out for this placement, and what did the newest one say?

    ``{running, prop_id, placement: {variant, yaw, offset_y}, last_run}`` —
    ``last_run`` is the newest run OF THIS PLACEMENT (a prop stands in many
    places; its run directory holds all of them), or ``null``.
    """
    from app.core.scene_asset import is_running

    placement = _placement(location_id, room_id, placement_index)
    prop_id = str(placement.get("prop_id") or "")
    key = f"{location_id}|{room_id}|{int(placement_index)}"
    runs = [r for r in _runs(prop_id)
            if r["room_id"] == str(room_id) and r["index"] == placement_index]
    return {
        "running": key in is_running(location_id),
        "prop_id": prop_id,
        "placement": {"variant": placement.get("variant"),
                      "yaw": placement.get("yaw"),
                      "offset_y": placement.get("offset_y")},
        "last_run": runs[0] if runs else None,
    }


@router.get("/runs/{prop_id}")
def scene_asset_runs(prop_id: str, limit: int = DEFAULT_RUN_LIMIT
                     ) -> Dict[str, Any]:
    """Every scene-asset run of ONE prop, newest first — the same summary the
    status route returns, for the whole history."""
    from app.core.props import get_prop

    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"runs": _runs(prop_id, limit=max(1, min(int(limit or 1), 200)))}


@router.get("/runs/{prop_id}/{rel:path}")
def scene_asset_artifact(prop_id: str, rel: str, request: Request):
    """Serve one run artefact — ``<stamp>/context.png`` and its three
    siblings. ETag + If-None-Match; a run directory never changes after it is
    written, so revalidation is cheap and caching may be generous."""
    from app.core.http_files import etag_file_response

    path = _artifact_path(prop_id, rel)
    if path is None:
        raise HTTPException(status_code=400, detail="Invalid artefact path")
    if not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "image/png",
                              cache_control="public, max-age=3600")


@router.post("/placement")
async def scene_asset_placement(request: Request) -> Dict[str, Any]:
    """Patch ONE stored placement — ``{location_id, room_id, placement_index}``
    plus any of ``variant`` / ``yaw`` / ``offset_y``.

    The persistent twin of the floor-plan editor's placement dials, and the
    same writer the pipeline itself uses (``world_ops.update_prop_placement``,
    sanitiser included): the variant picker needs a value to land the moment it
    is chosen, because the mesh a placement shows is what the 3D preview
    renders next. Returns the SANITISED placement, so the caller sees what was
    actually stored.
    """
    from app.core.world_ops import update_prop_placement

    body = await _body(request)
    location_id = str(body.get("location_id") or "").strip()
    room_id = str(body.get("room_id") or "")
    index = _int(body.get("placement_index"), "placement_index")
    _placement(location_id, room_id, index)

    patch: Dict[str, Any] = {}
    for field in ("variant", "yaw", "offset_y"):
        raw = body.get(field)
        if raw is None or f"{raw}".strip() == "":
            continue
        try:
            patch[field] = int(raw) if field == "variant" else float(raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                                detail=f"{field} must be a number")
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to patch")

    stored = update_prop_placement(location_id, room_id, index, patch)
    if stored is None:
        raise HTTPException(status_code=404, detail="Placement not found")
    return {"status": "ok", "placement": stored}
