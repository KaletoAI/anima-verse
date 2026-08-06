"""Pose/expression catalog - the finite render-key axes (plan-pose-katalog.md).

The catalog entry key is the ONLY key under which 2D image variants are
cached and 3D animation clips are resolved. Free text never reaches a
render path; it survives only as sanitized "flavor" prompt text.
"""
import json
import threading
from pathlib import Path
from typing import Dict, List

from app.core.log import get_logger

logger = get_logger("pose_catalog")

AXES = ("pose", "expression")
_FILES = {
    "pose": ("pose", "pose_catalog.json"),
    "expression": ("expression", "expression_catalog.json"),
}
_FALLBACK_DEFAULT = {"pose": "standing", "expression": "neutral"}

_lock = threading.Lock()
_cache: Dict[str, Dict[str, dict]] = {}


def _catalog_path(axis: str) -> Path:
    from app.core.paths import get_shared_dir
    sub, name = _FILES[axis]
    return get_shared_dir() / "templates" / sub / name


def _load(axis: str) -> Dict[str, dict]:
    try:
        data = json.loads(_catalog_path(axis).read_text(encoding="utf-8"))
        entries = data.get("entries") or {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("catalog %s unreadable: %s", axis, e)
        entries = {}
    out: Dict[str, dict] = {}
    for key, entry in entries.items():
        out[str(key).strip().lower()] = {
            "prompt": str(entry.get("prompt") or ""),
            "synonyms": [str(s).strip().lower() for s in (entry.get("synonyms") or []) if str(s).strip()],
            "animation": str(entry.get("animation") or ""),
            "solo": bool(entry.get("solo", True)),
            "_default": bool(entry.get("_default", False)),
        }
    return out


def get_catalog(axis: str) -> Dict[str, dict]:
    with _lock:
        if axis not in _cache:
            _cache[axis] = _load(axis)
        return _cache[axis]


def reload_catalogs() -> None:
    with _lock:
        _cache.clear()


def get_default_key(axis: str) -> str:
    for key, entry in get_catalog(axis).items():
        if entry["_default"]:
            return key
    return _FALLBACK_DEFAULT[axis]


def validate_catalog(axis: str) -> List[str]:
    """Returns human-readable problems; empty list = catalog is sound."""
    problems: List[str] = []
    catalog = get_catalog(axis)
    if not catalog:
        problems.append(f"{axis}: catalog is empty or unreadable")
        return problems
    seen: Dict[str, str] = {}
    defaults = 0
    for key, entry in catalog.items():
        if not entry["prompt"]:
            problems.append(f"{axis}/{key}: empty prompt")
        if axis == "pose" and not entry["animation"]:
            problems.append(f"{axis}/{key}: missing animation kind")
        if entry["_default"]:
            defaults += 1
        for alias in [key] + entry["synonyms"]:
            if alias in seen and seen[alias] != key:
                problems.append(f"{axis}: alias '{alias}' claimed by both '{seen[alias]}' and '{key}'")
            seen[alias] = key
    if defaults != 1:
        problems.append(f"{axis}: expected exactly 1 _default entry, found {defaults}")
    return problems
