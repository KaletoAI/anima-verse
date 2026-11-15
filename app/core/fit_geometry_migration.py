"""One-time judgement of the fit records made before geometry ids (Ruling A107).

Every geometry-only dependant of the base model now carries ``base_geometry_id`` next to
``base_model_sha256`` (``model_geometry``). A record written before has only the file sha; the base file it
names is usually gone (rewritten in place by a face retexture or a matte floor). It is judged ONCE here:

* its ``base_model_sha256`` is the current base file → it gets the current geometry id;
* it is a FIT record with its GLB beside it (``{item}_{fsig}.glb``) → the fit GLB carries the very body it was
  fitted on (the garment is grafted next to it, ``glb_mesh.graft``); that body's ``model_geometry.descriptor``
  is compared with the current base's (``model_geometry.equivalent``) — equivalent → the current id;
* a refused-fit record (``failed/``), a layered fit (``layers/``) or a HAAR seed verdict (``raw/*/record.json``
  ``results``) has no body of its own → it gets the current id when a fit GLB of the same character with the
  same old file sha was judged equivalent above.

Anything else stays without an id and is judged by its file sha, as before — stale; nothing is refitted, no
hub job is asked for. Outfit-body records (``bodies/``) are keyed by their own body and untouched. Done once
per character per ``model_geometry.GEOMETRY_VERSION`` (marker ``garments/.geometry_judged``). Read-only for a
character without a current base model.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MARKER = ".geometry_judged"


def _write(path: Path, record: Dict[str, Any]) -> None:
    from app.core import garment_store
    garment_store.write_record(path, record)


def judge_character(character_name: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """Judge one character's records (module doc). ``{stamped: [names], kept: [names], skipped: reason}``;
    ``dry_run`` writes nothing (no record, no marker)."""
    from app.core import base_body, garment_store, model_geometry
    from app.core.keyed_lock import keyed_lock
    out: Dict[str, Any] = {"stamped": [], "kept": [], "skipped": ""}
    root = garment_store.garments_dir(character_name)
    if not root.is_dir():
        out["skipped"] = "no garments"
        return out
    marker = root / MARKER
    if not dry_run and marker.is_file() and marker.read_text(encoding="utf-8").strip() == str(
            model_geometry.GEOMETRY_VERSION):
        out["skipped"] = "already judged"
        return out
    base = base_body.current_base(character_name)
    if not base or not base[1]:
        out["skipped"] = "no current base model"
        return out
    bsig, sha = base
    gid = model_geometry.of_file_sha(sha)  # ``current_base`` judged it (``base_body.base_model_sha256``)
    current = model_geometry.descriptor_of(character_name, bsig, gid)
    if not gid or current is None:
        out["skipped"] = "the current base model has no geometry id"
        return out
    judged: Dict[str, bool] = {sha: True}

    def stamp(path: Path, record: Dict[str, Any], seen: List[Dict[str, Any]], *, holder: Optional[Dict] = None,
              name: str = "") -> None:
        target = holder if holder is not None else record
        if target.get(model_geometry.FIELD) or not target.get("base_model_sha256"):
            return
        old = str(target["base_model_sha256"])
        if judged.get(old):
            target[model_geometry.FIELD] = gid
            seen.append(record)
            out["stamped"].append(name or path.name)
        else:
            out["kept"].append(name or path.name)

    with keyed_lock("garment_geometry_judgement", character_name):
        fits = sorted(p for p in root.glob("*.json") if p.with_suffix(".glb").is_file())
        # 1. Fit GLBs carry their body: judge their old file shas first.
        for path in fits:
            record = garment_store.read_record(path)
            old = str(record.get("base_model_sha256") or "")
            if not old or old in judged or record.get(model_geometry.FIELD):
                continue
            try:
                desc = model_geometry.descriptor(path.with_suffix(".glb").read_bytes())
                judged[old] = model_geometry.equivalent(desc, current)
            except Exception as exc:  # noqa: BLE001 — an unreadable fit stays judged by its file sha
                logger.info("Geometry judgement of %s/%s: %s", character_name, path.name, exc)
                judged[old] = False
        # 2. Stamp every record whose old file sha was judged equivalent.
        others = [*sorted((root / "failed").glob("*.json")), *sorted((root / "layers").glob("*.json"))]
        for path in [*fits, *others]:
            record = garment_store.read_record(path)
            if garment_store.is_body_id(str(record.get("body_id") or "")):
                continue
            changed: List[Dict[str, Any]] = []
            stamp(path, record, changed)
            if changed and not dry_run:
                _write(path, record)
        for path in sorted((root / "raw").glob("*/record.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            results = record.get("results") if isinstance(record, dict) else None
            if not isinstance(results, dict):
                continue
            changed = []
            for seed, result in results.items():
                if isinstance(result, dict):
                    stamp(path, record, changed, holder=result, name=f"{path.parent.name}#s{seed}")
            if changed and not dry_run:
                _write(path, record)
        if not dry_run:
            marker.write_text(str(model_geometry.GEOMETRY_VERSION), encoding="utf-8")
    return out


def judge_world() -> Dict[str, Dict[str, Any]]:
    """``judge_character`` for every character directory of the world; never raises."""
    from app.core.paths import get_storage_dir
    results: Dict[str, Dict[str, Any]] = {}
    folder = Path(get_storage_dir()) / "characters"
    for directory in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not (directory / "garments").is_dir():
            continue
        try:
            results[directory.name] = judge_character(directory.name)
        except Exception as exc:  # noqa: BLE001 — one character never stops the others
            logger.warning("Geometry judgement of %s failed: %s", directory.name, exc)
    stamped = sum(len(r.get("stamped") or []) for r in results.values())
    if stamped:
        logger.info("Fit geometry judgement (Ruling A107): %d records kept current across texture-only rewrites",
                    stamped)
    return results
