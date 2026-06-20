"""Content Marketplace routes — catalog fetch + pack install.

Multi-catalog: `content_marketplace.catalogs` is a list of
`{name, url, auth_token, enabled}` entries. Each catalog has its own
on-disk cache under `worlds/<w>/.cache/content_catalog_<slug>.json`.

Auth: if `auth_token` is set, it is sent as the `Authorization` header on
catalog and download requests. A bare token is prepended with `token `
(works for GitHub PATs and Forgejo); an already-prefixed value
(`Bearer xyz`, `token xyz`) is passed through 1:1.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse, quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query

from app.core import config
from app.core.auth_dependency import require_admin
from app.core.log import get_logger
from app.core.paths import get_storage_dir

logger = get_logger("content_packs")

router = APIRouter(prefix="/api/content", tags=["marketplace"],
                   dependencies=[Depends(require_admin)])

SUPPORTED_TYPES = {"character", "item", "item_bundle", "rule", "states", "location", "collection"}

_inflight_catalog: Dict[str, float] = {}


# ── Config / catalog selection ────────────────────────────────────────────

def _cfg() -> Dict[str, Any]:
    return config.get("content_marketplace", {}) or {}


def _slugify(name: str) -> str:
    """Stable on-disk slug derived from the catalog name."""
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip()).strip("_") or "default"
    return s.lower()[:60]


def _list_catalogs() -> List[Dict[str, Any]]:
    """Return enabled catalog entries with `_id` (slug) added."""
    raw = _cfg().get("catalogs") or []
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        url = (entry.get("url") or "").strip()
        if not url:
            continue
        name = (entry.get("name") or url).strip()
        out.append({
            "_id": _slugify(name),
            "name": name,
            "url": url,
            "auth_token": entry.get("auth_token") or "",
        })
    return out


def _resolve_catalog(catalog_id: Optional[str]) -> Optional[Dict[str, Any]]:
    catalogs = _list_catalogs()
    if not catalogs:
        return None
    if not catalog_id:
        return catalogs[0]
    for c in catalogs:
        if c["_id"] == catalog_id:
            return c
    return None


def _auth_header(token: str) -> Dict[str, str]:
    token = (token or "").strip()
    if not token:
        return {}
    lower = token.lower()
    if lower.startswith("bearer ") or lower.startswith("token "):
        value = token
    else:
        value = f"token {token}"
    return {"Authorization": value}


# ── Cache ────────────────────────────────────────────────────────────────

def _cache_path(slug: str) -> Path:
    p = get_storage_dir() / ".cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"content_catalog_{slug}.json"


def _read_cache(slug: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(slug)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("catalog cache parse failed (%s): %s", slug, e)
        return None


def _write_cache(slug: str, data: Dict[str, Any]) -> None:
    try:
        _cache_path(slug).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception as e:
        logger.warning("catalog cache write failed (%s): %s", slug, e)


# ── HTTP ─────────────────────────────────────────────────────────────────

def _derive_listing_endpoints(catalog_url: str) -> Dict[str, str]:
    """From a repo URL or a legacy index.json URL, derive:
        listing_url – API URL that returns the packs/ directory listing
        raw_base    – prefix for direct ZIP downloads (used in clone too)
        host_kind   – 'github' | 'forgejo'
        branch      – branch name

    Supported user inputs (all map to the same backend operation):
        https://github.com/<org>/<repo>
        https://github.com/<org>/<repo>/tree/<branch>
        https://github.com/<org>/<repo>/tree/<branch>/packs
        http(s)://<host>/<owner>/<repo>                          (Forgejo)
        http(s)://<host>/<owner>/<repo>/src/branch/<branch>      (Forgejo)
        legacy: …/<branch>/index.json (raw URL)                  (backwards-compat)
    """
    parsed = urlparse(catalog_url.strip().rstrip("/"))
    host = parsed.netloc
    parts = [p for p in parsed.path.split("/") if p]

    # GitHub repo page: github.com/<org>/<repo>(/tree/<branch>(/<sub>)?)?
    if host == "github.com" and len(parts) >= 2:
        org, repo = parts[0], parts[1]
        branch = "main"
        if len(parts) >= 4 and parts[2] == "tree":
            branch = parts[3]
        return {
            "host_kind": "github",
            "branch": branch,
            "listing_url": f"https://api.github.com/repos/{org}/{repo}/contents/packs?ref={branch}",
            "raw_base": f"https://raw.githubusercontent.com/{org}/{repo}/{branch}",
            "clone_url": f"https://github.com/{org}/{repo}.git",
        }

    # Legacy raw index.json: raw.githubusercontent.com/<org>/<repo>/<branch>/index.json
    if host == "raw.githubusercontent.com" and len(parts) >= 4:
        org, repo, branch = parts[0], parts[1], parts[2]
        return {
            "host_kind": "github",
            "branch": branch,
            "listing_url": f"https://api.github.com/repos/{org}/{repo}/contents/packs?ref={branch}",
            "raw_base": f"https://raw.githubusercontent.com/{org}/{repo}/{branch}",
            "clone_url": f"https://github.com/{org}/{repo}.git",
        }

    # Forgejo repo page: <host>/<owner>/<repo>(/src/branch/<branch>(/<sub>)?)?
    if len(parts) >= 2 and "src" not in parts[:2] and "raw" not in parts[:2]:
        owner, repo = parts[0], parts[1]
        branch = "main"
        if len(parts) >= 5 and parts[2] == "src" and parts[3] == "branch":
            branch = parts[4]
        scheme = parsed.scheme or "http"
        return {
            "host_kind": "forgejo",
            "branch": branch,
            "listing_url": f"{scheme}://{host}/api/v1/repos/{owner}/{repo}/contents/packs?ref={branch}",
            "raw_base": f"{scheme}://{host}/{owner}/{repo}/raw/branch/{branch}",
            "clone_url": f"{scheme}://{host}/{owner}/{repo}.git",
        }

    # Legacy raw forgejo: <host>/<owner>/<repo>/raw/branch/<branch>/index.json
    if "raw" in parts and "branch" in parts:
        i = parts.index("raw")
        if i >= 2 and len(parts) >= i + 3 and parts[i + 1] == "branch":
            owner, repo, branch = parts[0], parts[1], parts[i + 2]
            scheme = parsed.scheme or "http"
            return {
                "host_kind": "forgejo",
                "branch": branch,
                "listing_url": f"{scheme}://{host}/api/v1/repos/{owner}/{repo}/contents/packs?ref={branch}",
                "raw_base": f"{scheme}://{host}/{owner}/{repo}/raw/branch/{branch}",
                "clone_url": f"{scheme}://{host}/{owner}/{repo}.git",
            }

    raise ValueError(
        f"cannot derive listing endpoint from URL {catalog_url!r} — "
        "use the repo page URL (e.g. https://github.com/<org>/<repo>) "
        "or Forgejo equivalent"
    )


def _decode_content(entry: Dict[str, Any]) -> Optional[bytes]:
    """GitHub & Forgejo include base64 content inline for small files."""
    encoding = (entry.get("encoding") or "").lower()
    content = entry.get("content")
    if not content or encoding != "base64":
        return None
    import base64
    try:
        return base64.b64decode(content)
    except Exception:
        return None


async def _fetch_catalog(url: str, headers: Dict[str, str], timeout: float = 15.0) -> Dict[str, Any]:
    """Scan the catalog's `packs/` directory via the host's contents API.

    No central index.json — each pack is described by a sidecar JSON
    (`<slug>.json`) alongside the `<slug>.zip`. This produces the same
    shape `{packs: [...]}` that the UI already consumes.
    """
    endpoints = _derive_listing_endpoints(url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = await client.get(endpoints["listing_url"])
        if resp.status_code == 404:
            raise ValueError("no `packs/` directory found in the catalog repo")
        resp.raise_for_status()
        listing = resp.json()
        if not isinstance(listing, list):
            raise ValueError(f"unexpected listing shape: {type(listing).__name__}")

        zips: Dict[str, Dict[str, Any]] = {}
        sidecars: Dict[str, Dict[str, Any]] = {}
        for entry in listing:
            if not isinstance(entry, dict) or entry.get("type") != "file":
                continue
            name = entry.get("name") or ""
            if name.lower().endswith(".zip"):
                zips[name[:-4]] = entry
            elif name.lower().endswith(".json"):
                sidecars[name[:-5]] = entry

        # For sidecars whose content was not inlined (over the API's size
        # limit), fetch them individually. Most are tiny so the inline
        # content path is the common case.
        packs: List[Dict[str, Any]] = []
        for slug, zip_entry in zips.items():
            side_entry = sidecars.get(slug)
            meta: Dict[str, Any] = {}
            if side_entry:
                data = _decode_content(side_entry)
                if data is None:
                    side_url = side_entry.get("download_url") or ""
                    if side_url:
                        sr = await client.get(side_url)
                        if sr.status_code == 200:
                            data = sr.content
                if data:
                    try:
                        meta = json.loads(data)
                    except json.JSONDecodeError:
                        meta = {}
            pack = {
                "id": meta.get("id") or f"{meta.get('type', 'pack')}-{slug}",
                "type": meta.get("type") or "item",
                "name": meta.get("name") or slug,
                "slug": slug,
                "size_bytes": zip_entry.get("size"),
                "checksum_sha256": meta.get("checksum_sha256") or meta.get("sha256") or "",
                "tags": meta.get("tags") or [],
                "description": meta.get("description") or "",
                "contents": meta.get("contents") or None,
                "download_url": zip_entry.get("download_url") or f"{endpoints['raw_base']}/packs/{slug}.zip",
            }
            packs.append(pack)

    return {"packs": packs, "source_url": url, "host_kind": endpoints["host_kind"]}


async def _download(url: str, headers: Dict[str, str], *, max_bytes: int = 100 * 1024 * 1024) -> bytes:
    """Stream-download a pack, capped at `max_bytes`."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            buf = io.BytesIO()
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"pack exceeds {max_bytes} bytes limit")
                buf.write(chunk)
            return buf.getvalue()


def _is_fresh(cached: Dict[str, Any], ttl_minutes: int) -> bool:
    if ttl_minutes <= 0:
        return False
    fetched = cached.get("_fetched_at") or 0
    return (time.time() - float(fetched)) < (ttl_minutes * 60)


def _annotate(cached: Dict[str, Any], stale: bool, catalog: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(cached)
    out["stale"] = stale
    out["catalog_id"] = catalog["_id"]
    out["catalog_name"] = catalog["name"]
    return out


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/catalogs")
async def list_catalogs() -> Dict[str, Any]:
    """List configured catalogs (id, name, url) — no auth tokens leak out."""
    return {
        "catalogs": [
            {"id": c["_id"], "name": c["name"], "url": c["url"]}
            for c in _list_catalogs()
        ],
    }


@router.get("/catalog")
async def get_catalog(
    catalog_id: str = Query("", description="catalog id from /catalogs; empty = first enabled"),
    force: bool = Query(False),
) -> Dict[str, Any]:
    """Return one catalog. Cached unless `force=true` or the TTL has expired."""
    catalog = _resolve_catalog(catalog_id)
    if not catalog:
        return {"packs": [], "configured": False, "stale": False, "catalog_id": "", "catalog_name": ""}

    slug = catalog["_id"]
    url = catalog["url"]
    headers = _auth_header(catalog["auth_token"])
    ttl = int(_cfg().get("cache_ttl_minutes") or 60)

    cached = _read_cache(slug)
    if not force and cached and cached.get("source_url") == url and _is_fresh(cached, ttl):
        cached["configured"] = True
        return _annotate(cached, stale=False, catalog=catalog)

    try:
        if url in _inflight_catalog and (time.time() - _inflight_catalog[url]) < 5:
            if cached:
                cached["configured"] = True
                return _annotate(cached, stale=True, catalog=catalog)
        _inflight_catalog[url] = time.time()
        data = await _fetch_catalog(url, headers)
        data["_fetched_at"] = time.time()
        data["source_url"] = url
        data["configured"] = True
        _write_cache(slug, data)
        return _annotate(data, stale=False, catalog=catalog)
    except Exception as e:
        logger.warning("catalog fetch failed (%s): %s", slug, e)
        if cached:
            cached["configured"] = True
            return _annotate(cached, stale=True, catalog=catalog)
        raise HTTPException(status_code=502, detail=f"catalog fetch failed: {e}")
    finally:
        _inflight_catalog.pop(url, None)


def _find_pack(catalog_data: Dict[str, Any], pack_id: str) -> Optional[Dict[str, Any]]:
    for p in catalog_data.get("packs") or []:
        if p.get("id") == pack_id:
            return p
    return None


def _verify_checksum(content: bytes, expected: str) -> None:
    if not expected:
        return
    actual = hashlib.sha256(content).hexdigest()
    if actual.lower() != expected.strip().lower():
        raise ValueError(
            f"checksum mismatch: pack rejected (expected {expected[:12]}…, got {actual[:12]}…)"
        )


def _dispatch_install(pack_type: str, content: bytes) -> Dict[str, Any]:
    """Route the ZIP to the matching importer based on `pack_type`.

    Marketplace installs always land in the active world, never in the
    shared/ baseline that ships with the repo — otherwise a `git pull` can
    collide with previously installed packs. Users can promote an item/rule
    to shared manually via the "Move to shared" button if they want to.
    """
    if pack_type == "character":
        from app.core.character_io import import_character_from_zip
        return import_character_from_zip(content, overwrite=False)
    if pack_type == "item":
        from app.core.content_io import import_item_from_zip
        return import_item_from_zip(content, target="world", overwrite=False)
    if pack_type == "item_bundle":
        from app.core.content_io import import_bundle_from_zip
        return import_bundle_from_zip(content, target="world", overwrite=False)
    if pack_type == "rule":
        from app.core.content_io import import_rule_from_zip
        return import_rule_from_zip(content, target="world", overwrite=False)
    if pack_type == "states":
        from app.core.content_io import import_states_from_zip
        return import_states_from_zip(content, replace_all=False)
    if pack_type == "location":
        from app.core.content_io import import_location_from_zip
        return import_location_from_zip(content)
    if pack_type == "collection":
        return _install_collection(content)
    raise ValueError(f"unsupported pack type: {pack_type!r}")


def _install_collection(content: bytes) -> Dict[str, Any]:
    """Iterate the sub-packs in a collection ZIP and install each one.

    Collection layout:
        manifest.json    {version:1, type:"collection", name, contents:[
                            {type, name, file:"packs/...zip"}, ...
                         ]}
        packs/<file>.zip — each is a regular pack of its declared type.

    Sub-pack failures don't abort the rest — we collect a per-item result.
    """
    import zipfile as _zf
    try:
        zf = _zf.ZipFile(io.BytesIO(content))
    except _zf.BadZipFile as e:
        raise ValueError(f"invalid collection ZIP: {e}")
    try:
        manifest_raw = zf.read("manifest.json")
    except KeyError:
        raise ValueError("collection ZIP has no manifest.json")
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"collection manifest invalid JSON: {e}")
    if manifest.get("type") != "collection":
        raise ValueError(f"manifest type mismatch: got {manifest.get('type')!r}, expected 'collection'")
    sub_packs = manifest.get("contents") or []
    if not isinstance(sub_packs, list) or not sub_packs:
        raise ValueError("collection has no contents")

    results: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    for entry in sub_packs:
        if not isinstance(entry, dict):
            continue
        sub_type = (entry.get("type") or "").strip()
        sub_name = entry.get("name") or entry.get("file") or sub_type
        sub_file = (entry.get("file") or "").strip()
        if not sub_file or sub_type not in SUPPORTED_TYPES or sub_type == "collection":
            results.append({"name": sub_name, "type": sub_type, "status": "skipped",
                            "error": "invalid type or missing file"})
            fail_count += 1
            continue
        try:
            sub_bytes = zf.read(sub_file)
        except KeyError:
            results.append({"name": sub_name, "type": sub_type, "status": "skipped",
                            "error": f"file {sub_file!r} not in ZIP"})
            fail_count += 1
            continue
        try:
            sub_result = _dispatch_install(sub_type, sub_bytes)
            results.append({"name": sub_name, "type": sub_type, "status": "success",
                            "result": sub_result})
            ok_count += 1
        except FileExistsError as e:
            results.append({"name": sub_name, "type": sub_type, "status": "exists",
                            "error": str(e)})
            fail_count += 1
        except (ValueError, RuntimeError) as e:
            results.append({"name": sub_name, "type": sub_type, "status": "failed",
                            "error": str(e)})
            fail_count += 1
    zf.close()
    logger.info("collection install: %d ok, %d failed/skipped", ok_count, fail_count)
    return {
        "status": "success" if ok_count > 0 else "failed",
        "collection_name": manifest.get("name") or "(unnamed)",
        "installed": ok_count,
        "failed": fail_count,
        "results": results,
    }


@router.post("/install")
async def install_pack(request: Request) -> Dict[str, Any]:
    """Body: `{"pack_id": "...", "catalog_id": "..."}` — download from the
    catalog and install via the matching importer. Verifies checksum."""
    body = await request.json()
    pack_id = (body.get("pack_id") or "").strip()
    catalog_id = (body.get("catalog_id") or "").strip()
    if not pack_id:
        raise HTTPException(status_code=400, detail="pack_id required")

    catalog = _resolve_catalog(catalog_id)
    if not catalog:
        raise HTTPException(status_code=400, detail="no catalog configured")
    cached = _read_cache(catalog["_id"])
    if not cached:
        raise HTTPException(status_code=409, detail="catalog not loaded — fetch /api/content/catalog first")
    pack = _find_pack(cached, pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"pack '{pack_id}' not in catalog")
    pack_type = pack.get("type") or ""
    if pack_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported pack type: {pack_type!r}")
    download_url = (pack.get("download_url") or "").strip()
    if not download_url:
        raise HTTPException(status_code=400, detail="pack has no download_url")

    headers = _auth_header(catalog["auth_token"])
    try:
        content = await _download(download_url, headers)
        _verify_checksum(content, (pack.get("checksum_sha256") or ""))
        result = _dispatch_install(pack_type, content)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"download failed: {e}")

    return {
        "status": "success",
        "pack_id": pack_id,
        "pack_type": pack_type,
        "pack_name": pack.get("name") or pack_id,
        "catalog_id": catalog["_id"],
        "result": result,
    }


@router.post("/install_url")
async def install_pack_url(request: Request) -> Dict[str, Any]:
    """Install a one-off pack from any URL. Gated by `allow_install_url`.

    Body: `{"url", "sha256", "type", "auth_token"?}`. If `auth_token` is
    given, it overrides any per-catalog token.
    """
    if not bool(_cfg().get("allow_install_url")):
        raise HTTPException(
            status_code=403,
            detail="ad-hoc URL install disabled — enable in content_marketplace settings",
        )
    body = await request.json()
    url = (body.get("url") or "").strip()
    sha = (body.get("sha256") or "").strip()
    pack_type = (body.get("type") or "").strip()
    token = (body.get("auth_token") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    if pack_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported pack type: {pack_type!r}")

    headers = _auth_header(token)
    try:
        content = await _download(url, headers)
        _verify_checksum(content, sha)
        result = _dispatch_install(pack_type, content)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"download failed: {e}")

    return {"status": "success", "pack_type": pack_type, "result": result}


@router.post("/install_upload")
async def install_pack_upload(
    file: UploadFile = File(...),
    pack_type: str = Query(..., description="character / item / item_bundle / rule / states / location"),
) -> Dict[str, Any]:
    """Offline path: upload a pack ZIP directly."""
    if pack_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported pack type: {pack_type!r}")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        result = _dispatch_install(pack_type, content)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "pack_type": pack_type, "result": result}


def _manifest_type(content: bytes) -> str:
    import io as _io, json as _json, zipfile as _zip
    zf = _zip.ZipFile(_io.BytesIO(content))
    try:
        m = _json.loads(zf.read("manifest.json"))
        return m.get("type") or ("character" if m.get("character_name") else "")
    finally:
        zf.close()


def _dispatch_install_selected(content: bytes, *, selected_ids, overwrite: bool,
                               mode: str = "full", intro: str = "") -> Dict[str, Any]:
    """Generic import that honours a per-element selection + overwrite flag.
    Multi-element types (item_bundle, states) respect selected_ids; single-element
    types import as a whole. `mode`/`intro` only apply to character imports."""
    mtype = _manifest_type(content)
    if mtype == "character":
        from app.core.character_io import import_character_from_zip
        return import_character_from_zip(content, overwrite=overwrite, mode=mode, intro_text=intro)
    if mtype == "item":
        from app.core.content_io import import_item_from_zip
        return import_item_from_zip(content, target="world", overwrite=overwrite)
    if mtype == "item_bundle":
        from app.core.content_io import import_bundle_from_zip
        return import_bundle_from_zip(content, target="world", overwrite=overwrite,
                                      selected_ids=selected_ids)
    if mtype == "rule":
        from app.core.content_io import import_rule_from_zip
        return import_rule_from_zip(content, target="world", overwrite=overwrite)
    if mtype == "states":
        from app.core.content_io import import_states_from_zip
        return import_states_from_zip(content, replace_all=False, selected_ids=selected_ids)
    if mtype == "location":
        from app.core.content_io import import_location_from_zip
        return import_location_from_zip(content)
    if mtype == "map_layout":
        from app.core.content_io import import_map_layout_from_zip
        return import_map_layout_from_zip(content)
    raise ValueError(f"unsupported export type: {mtype!r}")


@router.post("/preview")
async def preview_import(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Inspect an export ZIP and list its importable elements (with clash flags),
    without importing. Generic across all export types."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    from app.core.content_io import preview_import_zip
    try:
        return preview_import_zip(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import")
async def import_selected(
    file: UploadFile = File(...),
    selected_ids: str = Form("", description="comma-separated element ids; empty = all"),
    overwrite: bool = Form(False),
    mode: str = Form("full", description="character import: full | fresh"),
    intro: str = Form("", description="fresh-start intro memory text"),
) -> Dict[str, Any]:
    """Generic import for any export ZIP. `selected_ids` (multi-element types) and
    `overwrite` are honoured per element. `mode`/`intro` apply to character imports."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    sel = {s.strip() for s in selected_ids.split(",") if s.strip()} or None
    try:
        result = _dispatch_install_selected(content, selected_ids=sel, overwrite=overwrite,
                                            mode=mode, intro=intro)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "result": result}


@router.post("/character-intro-suggest")
async def character_intro_suggest(
    file: UploadFile = File(...),
    hint: str = Form(""),
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Suggest one intro memory for a fresh-start character import. Reads the
    personality + name from the uploaded ZIP (the character isn't imported yet)
    and uses the per-world briefing (world_setup). Returns {character, intro}."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()

    char_name = ""
    personality = ""
    try:
        import zipfile as _zip
        z = _zip.ZipFile(io.BytesIO(content))
        try:
            try:
                m = json.loads(z.read("manifest.json"))
                char_name = (m.get("character_name") or "").strip()
            except Exception:
                pass
            if "files/soul/personality.md" in z.namelist():
                personality = z.read("files/soul/personality.md").decode("utf-8", "ignore").strip()
            if not personality and "db/characters.json" in z.namelist():
                try:
                    rows = json.loads(z.read("db/characters.json"))
                    prof = json.loads(rows[0].get("profile_json") or "{}") if rows else {}
                    personality = (prof.get("personality") or prof.get("character_personality") or "").strip()
                except Exception:
                    pass
        finally:
            z.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid ZIP: {e}")

    from app.core.prompt_templates import render_task
    from app.core.llm_router import llm_call
    from app.models.world_setup import get_world_setup_text
    from app.core.paths import get_storage_dir
    try:
        sys_p, user_p = render_task(
            "intro_memory",
            character_name=char_name or "the character",
            character_personality=personality or "",
            world_name=get_storage_dir().name,
            world_setup=get_world_setup_text() or "",
            user_hint=(hint or "").strip(),
        )
        resp = llm_call("intro_memory", sys_p, user_p, agent_name=char_name, label="intro_memory")
        intro = (getattr(resp, "content", "") or "").strip()
    except Exception as e:
        logger.exception("intro suggest failed")
        raise HTTPException(status_code=500, detail=f"intro suggestion failed: {e}")
    return {"character": char_name, "intro": intro}


@router.get("/types")
async def supported_types() -> Dict[str, Any]:
    return {"types": sorted(SUPPORTED_TYPES)}


# ── Publish ──────────────────────────────────────────────────────────────

# When publishing we need to derive (a) the clone URL of the catalog's repo
# and (b) the raw-path prefix for download_urls. Both are derived from the
# catalog_url. We support GitHub-raw and Forgejo-raw patterns; anything
# else needs manual repo_url configuration (not implemented in v1).

_CLONE_DIR_NAME = "publish_repos"


def _publish_root() -> Path:
    p = get_storage_dir() / ".cache" / _CLONE_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def _derive_repo_info(catalog_url: str) -> Tuple[str, str, str]:
    """Thin wrapper around _derive_listing_endpoints for the publish path.

    Returns (clone_url, branch, raw_base) for git operations.
    """
    ep = _derive_listing_endpoints(catalog_url)
    return ep["clone_url"], ep["branch"], ep["raw_base"]


def _embed_token_in_url(clone_url: str, token: str) -> str:
    """Embed the PAT into the clone URL so a non-interactive git push works.

    For both GitHub and Forgejo the pattern `https://<token>@host/...` is
    accepted; for git the username can be anything when a token is supplied,
    so we use `git`.
    """
    if not token:
        return clone_url
    parsed = urlparse(clone_url)
    if not parsed.scheme.startswith("http"):
        return clone_url
    netloc = f"git:{quote(token, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _run_git(cwd: Path, *args: str, timeout: int = 60) -> str:
    """Run git non-interactively. Token must be in the URL, not the prompt."""
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": "/usr/bin:/usr/local/bin",
        "HOME": str(cwd),
    }
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, env=env, check=True,
            capture_output=True, text=True, timeout=timeout,
        )
        return proc.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git {' '.join(args)} failed: {e.stderr.strip() or e.stdout.strip()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git {' '.join(args)} timed out after {timeout}s")


def _ensure_clone(catalog: Dict[str, Any]) -> Tuple[Path, str, str]:
    """Make sure a local clone exists & is up-to-date. Returns
    (repo_dir, branch, base_url). Clones on first use, otherwise
    fetches + resets the working tree to origin's HEAD."""
    catalog_url = catalog["url"]
    token = catalog["auth_token"]
    clone_url, branch, base_url = _derive_repo_info(catalog_url)
    auth_clone_url = _embed_token_in_url(clone_url, token)

    repo_dir = _publish_root() / catalog["_id"]
    if not (repo_dir / ".git").exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        # clone with token; immediately scrub it from the remote URL
        _run_git(_publish_root(), "clone", "--depth", "1", "--branch", branch,
                 auth_clone_url, str(repo_dir), timeout=120)
        _run_git(repo_dir, "remote", "set-url", "origin", clone_url)
        _run_git(repo_dir, "config", "user.email", "marketplace@anima-verse.local")
        _run_git(repo_dir, "config", "user.name", "Anima-Verse Publisher")
    else:
        # Refresh: fetch + hard reset so prior local commits don't desync.
        # Token-injected URL is only used for the fetch, not stored.
        _run_git(repo_dir, "fetch", auth_clone_url, branch, timeout=60)
        _run_git(repo_dir, "reset", "--hard", "FETCH_HEAD")
    return repo_dir, branch, base_url


# ── Export helpers (mirror local UI export, but in-memory) ────────────────

def _export_zip_for(pack_type: str, entity_id: str) -> bytes:
    if pack_type == "character":
        from app.core.character_io import export_character_to_zip
        return export_character_to_zip(entity_id)
    if pack_type == "item":
        from app.core.content_io import export_item_to_zip
        return export_item_to_zip(entity_id)
    if pack_type == "rule":
        from app.core.content_io import export_rule_to_zip
        return export_rule_to_zip(entity_id)
    if pack_type == "location":
        from app.core.content_io import export_location_to_zip
        return export_location_to_zip(entity_id)
    if pack_type == "states":
        from app.core.content_io import export_states_to_zip
        return export_states_to_zip()
    raise ValueError(f"publish not supported for pack type {pack_type!r}")


def _slug_for_pack(name: str, fallback: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9._-]+", "-", (name or fallback).strip()).strip("-_.").lower()
    return base or "pack"


@router.post("/publish")
async def publish_pack(request: Request) -> Dict[str, Any]:
    """Publish an entity from the current world to one of the configured
    catalogs.

    Body:
      catalog_id   – which catalog to push to
      pack_type    – character | item | rule | states | location
      entity_id    – id of the thing being exported (ignored for states)
      name         – display name in the catalog
      description  – optional
      tags         – optional comma-separated string or list
    """
    body = await request.json()
    catalog_id = (body.get("catalog_id") or "").strip()
    pack_type = (body.get("pack_type") or "").strip()
    entity_id = (body.get("entity_id") or "").strip()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    raw_tags = body.get("tags") or []
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]

    if pack_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported pack type: {pack_type!r}")
    if pack_type != "states" and not entity_id:
        raise HTTPException(status_code=400, detail="entity_id required")
    if not name:
        raise HTTPException(status_code=400, detail="name required")

    catalog = _resolve_catalog(catalog_id)
    if not catalog:
        raise HTTPException(status_code=400, detail="catalog not found")

    # 1. Build the ZIP
    try:
        zip_bytes = _export_zip_for(pack_type, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2. Clone / refresh the target repo
    try:
        repo_dir, branch, base_url = _ensure_clone(catalog)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=f"repo prep failed: {e}")

    # 3. Place ZIP + sidecar JSON side by side under packs/
    slug = _slug_for_pack(name, entity_id or pack_type)
    packs_dir = repo_dir / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    zip_path = packs_dir / f"{slug}.zip"
    sidecar_path = packs_dir / f"{slug}.json"
    zip_path.write_bytes(zip_bytes)
    sha = hashlib.sha256(zip_bytes).hexdigest()

    sidecar = {
        "id": f"{pack_type}-{slug}",
        "type": pack_type,
        "name": name,
        "slug": slug,
        "tags": tags,
        "description": description,
        "checksum_sha256": sha,
        "size_bytes": len(zip_bytes),
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 5. Commit + push (token re-embedded only for the push call)
    try:
        _run_git(repo_dir, "add", "-A")
        commit_msg = f"Publish {pack_type}: {name}"
        try:
            _run_git(repo_dir, "commit", "-m", commit_msg)
        except RuntimeError as e:
            if "nothing to commit" in str(e):
                logger.info("publish: nothing changed for %s", entry["id"])
                return {
                    "status": "no_change",
                    "pack_id": entry["id"],
                    "message": "Pack content identical to what's already in the catalog.",
                }
            raise
        clone_url, _, _ = _derive_repo_info(catalog["url"])
        auth_push_url = _embed_token_in_url(clone_url, catalog["auth_token"])
        _run_git(repo_dir, "push", auth_push_url, f"HEAD:{branch}", timeout=120)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"git push failed: {e}")

    # 6. Bust local catalog cache so the next /catalog fetch sees the new pack.
    cp = _cache_path(catalog["_id"])
    if cp.exists():
        cp.unlink()

    download_url = f"{base_url}/packs/{slug}.zip"
    logger.info("publish: %s → %s (%d bytes)", sidecar["id"], catalog["name"], len(zip_bytes))
    return {
        "status": "success",
        "pack_id": sidecar["id"],
        "pack_name": name,
        "catalog_id": catalog["_id"],
        "catalog_name": catalog["name"],
        "download_url": download_url,
        "size_bytes": len(zip_bytes),
    }
