"""Pose presets — the activity library of this codebase.

A preset maps free-text activity ("leaning against the coffee machine") onto a
canonical key, a body-pose prompt (for image generation) and — since AV3D-6 —
an ANIMATION kind (idle/walk/sit/…) a 3D client turns into a clip. Synonyms
make the free text land on the right key.

Two files, one view:
  * ``pose_presets.json``           curated, in git
  * ``pose_presets_generated.json`` written by the LLM when it meets an unknown
    activity (gitignored)
An edit writes back to the file the entry lives in. The animation vocabulary is
NOT hardcoded: it is whatever /assets/animation-clips currently offers.
"""
import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import expression_pose_maps as epm
from app.core.auth_dependency import require_admin
from app.core.log import get_logger
from app.core.paths import get_pose_presets_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/poses", tags=["poses"])

CURATED = "pose_presets.json"
GENERATED = "pose_presets_generated.json"


def _read(filename: str) -> Dict[str, Any]:
    path = get_pose_presets_dir() / filename
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"presets": {}}


def _write(filename: str, data: Dict[str, Any]) -> None:
    path = get_pose_presets_dir() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    epm.reload_presets()


def _locate(key: str) -> tuple:
    """(filename, parsed doc) of the file holding this key (curated wins) —
    ("", None) if it is unknown. Handing back the doc lets the handler edit
    the parse it already paid for instead of re-reading the file."""
    for filename in (CURATED, GENERATED):
        data = _read(filename)
        if key in (data.get("presets") or {}):
            return filename, data
    return "", None


@router.get("")
def list_poses(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """All presets + the animation kinds that currently have clips."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for filename, source in ((CURATED, "curated"), (GENERATED, "generated")):
        for key, entry in (_read(filename).get("presets") or {}).items():
            if key in seen:
                continue  # curated wins over a generated entry of the same key
            seen.add(key)
            out.append({
                "key": key,
                "prompt": entry.get("prompt", ""),
                "synonyms": entry.get("synonyms", []) or [],
                "animation": entry.get("animation", "") or "",
                "solo": entry.get("solo", True),
                "is_default": bool(entry.get("_default")),
                "source": source,
            })
    out.sort(key=lambda p: p["key"])
    return {"presets": out, "kinds": epm.available_animation_kinds()}


@router.put("/{key}")
async def update_pose(key: str, request: Request,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Updates prompt / synonyms / animation of a preset (in the file it lives in)."""
    key = key.strip().lower()
    filename, data = _locate(key)
    if not filename:
        raise HTTPException(status_code=404, detail="Preset not found")
    body = await request.json()
    entry = data["presets"][key]
    if "prompt" in body:
        entry["prompt"] = str(body["prompt"] or "").strip()
    if "synonyms" in body:
        syns = body["synonyms"] or []
        if not isinstance(syns, list):
            raise HTTPException(status_code=400, detail="synonyms must be a list")
        entry["synonyms"] = [str(s).strip().lower() for s in syns if str(s).strip()]
    if "animation" in body:
        anim = str(body["animation"] or "").strip().lower()
        # Empty is valid and means "the client guesses from the text".
        if anim:
            entry["animation"] = anim
        else:
            entry.pop("animation", None)
    if "solo" in body:
        entry["solo"] = bool(body["solo"])
    _write(filename, data)
    return {"status": "success", "key": key, "source": filename}


@router.post("")
async def create_pose(request: Request,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Creates a curated preset."""
    body = await request.json()
    key = str(body.get("key") or "").strip().lower()
    if not key:
        raise HTTPException(status_code=400, detail="key missing")
    if _locate(key)[0]:
        raise HTTPException(status_code=409, detail="Preset already exists")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt missing")
    data = _read(CURATED)
    entry: Dict[str, Any] = {"prompt": prompt, "synonyms": []}
    syns = body.get("synonyms") or []
    if isinstance(syns, list):
        entry["synonyms"] = [str(s).strip().lower() for s in syns if str(s).strip()]
    anim = str(body.get("animation") or "").strip().lower()
    if anim:
        entry["animation"] = anim
    data.setdefault("presets", {})[key] = entry
    _write(CURATED, data)
    return {"status": "success", "key": key}


@router.delete("/{key}")
def delete_pose(key: str,
                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Deletes a preset from the file it lives in."""
    key = key.strip().lower()
    filename, data = _locate(key)
    if not filename:
        raise HTTPException(status_code=404, detail="Preset not found")
    data["presets"].pop(key, None)
    _write(filename, data)
    return {"status": "success"}
