"""A195 — the template dialog's picture: the character DRESSED, without the piece being parametrised.

The figure served for the worn outfit (``model3d.find_model3d_serving``: the outfit model, or the plain body) is
assembled in memory with every grafted garment EXCEPT the excluded item (``garment_assembly._build`` with the
excluded piece taken out of the wanted list — so the body under it is not cut away either) and rendered locally from
the front by Blender (``figure_front``: orthographic, transparent ground, the camera of ``front_camera``). The camera
travels with the picture, so the overlay maps metres to pixels exactly (``garment_preview.Registration`` with
``frame["camera"]``).

No image job, no hub, no LLM: a CPU Blender run of a few seconds. Rendered on demand in a background thread when the
dialog asks (``state``) and cached per key — the served bare model's revision, the grafted garments' state, the
hidden parts, the excluded item and ``RENDER_VERSION`` — under ``<character>/template_front/<key>.png`` (+ ``.json``
with the camera). The newest ``KEEP`` pictures per character are kept.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Bumped when the picture is rendered differently for the same inputs.
RENDER_VERSION = 1
#: The cache folder under the character directory.
DIR_NAME = "template_front"
#: Pictures kept per character.
KEEP = 8
#: How long a computed source key is reused (the preview is asked every few hundred ms while sliding).
KEY_TTL_S = 5.0

NO_FIGURE = "No 3D figure yet — the plain body front is shown (Figure tab → Build)"

_lock = threading.Lock()
_inflight: Dict[str, threading.Thread] = {}
_failed: Dict[str, str] = {}
_keys: Dict[Tuple[str, str], Tuple[float, Optional[Dict[str, Any]]]] = {}


def cache_dir(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / DIR_NAME


def source(character_name: str, item_id: str) -> Optional[Dict[str, Any]]:
    """What the picture is made of: ``{key, bare, directory, signature, wanted, hidden}`` — the served bare model
    and its grafted garments without ``item_id``; None without a served GLB."""
    from app.core import garment_assembly as ga
    from app.core import model3d
    path, _match = model3d.find_model3d_serving(character_name)
    if not path:
        return None
    bare = Path(path)
    if bare.suffix.lower() != ".glb" or not bare.is_file():
        return None
    directory, signature = bare.parent, bare.stem
    bare_meta = ga.bare_meta_of(character_name, directory, signature)
    wanted = [g for g in ga._wanted(character_name, bare_meta=bare_meta)
              if g["item_id"] != item_id and g.get("fit") is not None]
    hidden = ga._hidden_parts(character_name, bare_meta)
    state = ga._state(wanted, ga.FULL, character_name=character_name)
    raw = json.dumps([RENDER_VERSION, signature, ga.bare_revision(bare), state, hidden, item_id], sort_keys=True,
                     default=str)
    return {"key": hashlib.sha256(raw.encode()).hexdigest()[:16], "bare": bare, "directory": directory,
            "signature": signature, "wanted": wanted, "hidden": hidden}


def _source_memo(character_name: str, item_id: str) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    k = (character_name, item_id)
    with _lock:
        hit = _keys.get(k)
    if hit is not None and now - hit[0] < KEY_TTL_S:
        return hit[1]
    src = source(character_name, item_id)
    with _lock:
        if len(_keys) > 64:
            _keys.clear()
        _keys[k] = (now, src)
    return src


def cached(character_name: str, key: str) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """``(png, record)`` of a stored picture, None when missing or unreadable."""
    if not key or not all(c in "0123456789abcdef" for c in key):
        return None
    d = cache_dir(character_name)
    png, side = d / f"{key}.png", d / f"{key}.json"
    if not png.is_file() or not side.is_file():
        return None
    try:
        rec = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rec.get("camera"), dict):
        return None
    return png, rec


def _render(character_name: str, item_id: str, src: Dict[str, Any]) -> None:
    from app.blender import runner
    from app.core import garment_assembly as ga
    key = src["key"]
    work = Path(tempfile.mkdtemp(prefix="av-template-front-"))
    try:
        if src["wanted"]:
            blob = ga._build(character_name, src["directory"], src["bare"], src["wanted"], ga.FULL, [],
                             hidden=src["hidden"], validate=False)[0]
        else:
            blob = src["bare"].read_bytes()
        glb = work / "figure.glb"
        glb.write_bytes(blob)
        res: Dict[str, Any] = {}
        for engine in ("BLENDER_WORKBENCH", "CYCLES"):
            res = runner.run("figure_front", inputs={"model": glb}, params={"engine": engine}, out_dir=work / engine,
                             timeout_s=300)
            if res.get("ok"):
                break
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "render failed")
        d = cache_dir(character_name)
        d.mkdir(parents=True, exist_ok=True)
        tmp_png = d / f".{key}.png.tmp"
        shutil.move(res["outputs"]["front"], tmp_png)
        record = {"key": key, "item_id": item_id, "signature": src["signature"], "camera": res["data"]["camera"],
                  "engine": res["data"].get("engine"), "garments": sorted(g["item_id"] for g in src["wanted"]),
                  "version": RENDER_VERSION}
        tmp_json = d / f".{key}.json.tmp"
        tmp_json.write_text(json.dumps(record, indent=1), encoding="utf-8")
        tmp_png.replace(d / f"{key}.png")
        tmp_json.replace(d / f"{key}.json")
        _prune(d)
        logger.info("Template front of %s without %s rendered (%s, %d garment(s))", character_name, item_id, key,
                    len(src["wanted"]))
    except Exception as e:  # noqa: BLE001 — the dialog keeps the plain front and names the failure
        logger.warning("Template front of %s without %s failed: %s", character_name, item_id, e)
        with _lock:
            _failed[key] = str(e) or type(e).__name__
    finally:
        shutil.rmtree(work, ignore_errors=True)
        with _lock:
            _inflight.pop(key, None)


def _prune(d: Path) -> None:
    pngs = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in pngs[KEEP:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def state(character_name: str, item_id: str, *, start: bool = True) -> Dict[str, Any]:
    """The dressed picture's state: ``{state: ready, key, png, record}`` / ``{state: rendering, key}`` /
    ``{state: failed, key, error}`` / ``{state: none, reason}``. ``start``: begin the render when missing."""
    try:
        src = _source_memo(character_name, item_id)
    except Exception as e:  # noqa: BLE001 — the plain front stays, the reason is shown
        logger.debug("Template front source of %s unreadable", character_name, exc_info=True)
        return {"state": "none", "reason": f"{NO_FIGURE} ({e})"}
    if src is None:
        return {"state": "none", "reason": NO_FIGURE}
    key = src["key"]
    hit = cached(character_name, key)
    if hit is not None:
        return {"state": "ready", "key": key, "png": hit[0], "record": hit[1]}
    with _lock:
        if key in _failed:
            return {"state": "failed", "key": key, "error": _failed[key]}
        if key not in _inflight and start:
            t = threading.Thread(target=_render, args=(character_name, item_id, src), daemon=True,
                                 name=f"template-front-{key}")
            _inflight[key] = t
            t.start()
    return {"state": "rendering", "key": key}


def retry(character_name: str, item_id: str) -> None:
    """Forget a failure of the current key (the dialog's Retry)."""
    src = _source_memo(character_name, item_id)
    if src is not None:
        with _lock:
            _failed.pop(src["key"], None)
