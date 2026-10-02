"""Publishing world entities to a marketplace catalog: the ONE pack builder
(export + preview + catalog text) and the bulk publish job.

Plan: ``development_instructions/plan-marketplace-props.md`` Teil B/D/E. The
storage protocol itself lives in ``marketplace_store``; this module turns an
entity of the active world into a :class:`PackUpload` and feeds the store.

The bulk job builds and publishes in CHUNKS of ``CHUNK`` packs: a whole prop
library held in memory at once would be gigabytes, and every chunk is one
store call that rewrites the index — an aborted job loses at most one chunk
of catalog lines (the uploaded files are swept later by the store).
"""
from __future__ import annotations

import hashlib
import io
import json
import threading
import uuid
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.log import get_logger
from app.core.marketplace_store import (CatalogRepo, MarketplaceError, PackUpload,
                                        content_hash, publish)

logger = get_logger("marketplace_publish")

#: A pack at or above this size is published with a warning (decision
#: 2026-10-02: large packs go public, the admin is told).
LARGE_PACK_BYTES = 50 * 1024 * 1024
#: Packs per store call in the bulk job.
CHUNK = 10


def build_upload(pack_type: str, entity_id: str, name: str, description: str,
                 tags: List[str], *, max_pack_mb: int) -> Tuple[PackUpload, List[str]]:
    """Export ONE entity and describe it for the catalog — shared by publish,
    the publish preview, the bulk job. ``ValueError`` for an entity that
    cannot be exported. ``max_pack_mb`` is this world's install limit (a pack
    above it gets a warning: installs with that limit refuse it)."""
    from app.core.content_io import (_pack_slug, export_zip_for, make_thumbnail,
                                     pack_preview)
    zip_bytes = export_zip_for(pack_type, entity_id)
    preview = pack_preview(pack_type, entity_id)
    # The ENTITY ID names the pack (two props may share a display name, never
    # an id); only `states`, which has no id, falls back to the name.
    slug = _pack_slug(entity_id or name or pack_type)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except (KeyError, ValueError):
            manifest = {}
    entry: Dict[str, Any] = {
        "id": f"{pack_type}-{slug}",
        "type": pack_type,
        "slug": slug,
        "name": name,
        "description": description,
        "tags": tags,
        "content_sha256": content_hash(zip_bytes),
        "manifest_version": manifest.get("version"),
        "facts": preview["facts"],
    }
    if preview.get("labels"):
        entry["fact_labels"] = preview["labels"]
    warnings: List[str] = []
    size = len(zip_bytes)
    if size >= LARGE_PACK_BYTES:
        warnings.append(f"Large pack ({size // (1024 * 1024)} MB) — slow to download.")
    if size > max_pack_mb * 1024 * 1024:
        warnings.append(
            f"Larger than this world's install limit ({max_pack_mb} MB, "
            "content_marketplace.max_pack_mb) — installs with that limit refuse it.")
    upload = PackUpload(entry=entry, zip_bytes=zip_bytes,
                        checksum_sha256=hashlib.sha256(zip_bytes).hexdigest(),
                        thumb_bytes=make_thumbnail(preview["image"]))
    return upload, warnings


def default_text(pack_type: str, entity_id: str) -> Tuple[str, str]:
    """``(name, description)`` a bulk publish gives a pack: the entity's own
    name and, for a prop, the description of its primary variant."""
    if pack_type == "prop":
        from app.core import props
        meta = props.read_sidecar(props.safe_prop_id(entity_id) or "")
        if meta:
            primary = props.primary_variant(entity_id)
            return (str(meta.get("name") or entity_id),
                    props.variant_description(meta, primary))
    return entity_id, ""


# ── bulk job ────────────────────────────────────────────────────────────

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    j = dict(job)
    j["items"] = [dict(i) for i in job["items"]]
    return j


def _update(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id].update(fields)


def _set_item(job_id: str, index: int, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS[job_id]
        job["items"][index].update(fields)
        job["done"] = sum(1 for i in job["items"] if i["status"] != "pending")


def _run(job_id: str, repo: CatalogRepo, pack_type: str, tags: List[str],
         max_pack_mb: int, sweep_age_s: int) -> None:
    with _JOBS_LOCK:
        entity_ids = [i["entity_id"] for i in _JOBS[job_id]["items"]]
    try:
        for start in range(0, len(entity_ids), CHUNK):
            chunk: List[Tuple[int, PackUpload, List[str]]] = []
            for k in range(start, min(start + CHUNK, len(entity_ids))):
                eid = entity_ids[k]
                try:
                    name, description = default_text(pack_type, eid)
                    upload, warnings = build_upload(pack_type, eid, name, description,
                                                    tags, max_pack_mb=max_pack_mb)
                except (ValueError, OSError) as e:
                    _set_item(job_id, k, status="error", error=str(e))
                    continue
                if len(upload.zip_bytes) > repo.host_limit:
                    _set_item(job_id, k, status="error", pack_id=upload.entry["id"],
                              error="over the host's per-file limit")
                    continue
                chunk.append((k, upload, warnings))
            if not chunk:
                continue
            results = publish(repo, pack_type, [u for _, u, _ in chunk],
                              sweep_age_s=sweep_age_s, flush_every=len(chunk))
            for (k, upload, warnings), res in zip(chunk, results):
                _set_item(job_id, k, status=res["status"], pack_id=res["pack_id"],
                          error=res.get("error") or "",
                          warnings=warnings + list(res.get("warnings") or []))
        _update(job_id, status="done")
    except (MarketplaceError, httpx.HTTPError) as e:
        # A whole store call failed (lost index race, host down): what was
        # published before stays published; the rest is reported, not retried.
        logger.warning("bulk publish %s stopped: %s", job_id, e)
        with _JOBS_LOCK:
            job = _JOBS[job_id]
            for item in job["items"]:
                if item["status"] == "pending":
                    item["status"] = "skipped"
            job["status"] = "error"
            job["error"] = str(e)
    except Exception as e:  # noqa: BLE001 — a crashed thread must still end the job
        logger.error("bulk publish %s crashed: %s", job_id, e)
        _update(job_id, status="error", error=str(e))


def start_bulk(repo: CatalogRepo, catalog_id: str, pack_type: str,
               entity_ids: List[str], tags: List[str], *, max_pack_mb: int,
               sweep_age_s: int) -> Dict[str, Any]:
    """Start a bulk publish in the background; one running job per catalog
    (the store serializes publishes anyway) — a second start returns the
    running job instead."""
    with _JOBS_LOCK:
        for job in _JOBS.values():
            if job["catalog_id"] == catalog_id and job["status"] == "running":
                return _snapshot(job)
        job_id = uuid.uuid4().hex[:12]
        ids = list(dict.fromkeys(e for e in entity_ids if e))
        _JOBS[job_id] = {
            "id": job_id, "catalog_id": catalog_id, "pack_type": pack_type,
            "status": "running", "total": len(ids), "done": 0, "error": "",
            "items": [{"entity_id": e, "status": "pending", "pack_id": "",
                       "error": "", "warnings": []} for e in ids],
        }
    threading.Thread(target=_run, args=(job_id, repo, pack_type, tags,
                                        max_pack_mb, sweep_age_s),
                     daemon=True, name="marketplace-bulk").start()
    return get_job(job_id) or {}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return _snapshot(job) if job else None


def list_jobs() -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        return [_snapshot(j) for j in _JOBS.values()]
