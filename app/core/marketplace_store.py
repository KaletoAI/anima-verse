"""Marketplace catalogs on a Git host's RELEASES — no git, no history.

Plan: ``development_instructions/plan-marketplace-props.md`` Teil C. A catalog
is a repository that holds nothing but releases; the repository itself only
needs one commit for the tags to hang on. Per pack type there are two
releases with fixed tags:

    packs-<type>    <slug>-<sha8>.zip per pack  +  index-<utc stamp>.json
    thumbs-<type>   <slug>-<sha8>.webp per pack (when the pack has a picture)

``sha8`` is the head of the pack's ``content_sha256``, so every content gets a
name of its own: replacing a pack uploads NEXT TO the old file instead of
over it, and the catalog points at an existing file at every moment. The
NEWEST ``index-*.json`` (by name) is the catalog of that type; older indexes
and replaced pack files are swept once they are older than any catalog cache
could be (:func:`_sweep`).

GitHub and Forgejo differ in four calls only (upload format, asset listing,
asset delete URL, release pagination) — :class:`CatalogRepo` hides them. A
GitHub catalog must be PUBLIC: its asset downloads answer 404 for a private
repository even with a token, and httpx drops ``Authorization`` on the
cross-origin redirect anyway. Private catalogs live on Forgejo, whose
attachment downloads accept the token (measured 2026-10-02).

Synchronous on purpose (``httpx.Client``): the routes run it in the
threadpool, the bulk publish job runs it on its own thread, and the publish
lock is a plain ``keyed_lock`` per catalog.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now

logger = get_logger("marketplace_store")

INDEX_FORMAT = 1
INDEX_PREFIX = "index-"
PACKS_TAG = "packs-"
THUMBS_TAG = "thumbs-"
#: Hard per-file limits of the hosts (GitHub release asset; Forgejo reports
#: ``max_size`` 2048 MB on /api/v1/settings/attachment).
HOST_LIMIT_BYTES = {"github": 2 * 1024 ** 3, "forgejo": 2048 * 1024 ** 2}
#: GitHub refuses the 1001st asset of a release. N packs + the live index +
#: the transient second index during a publish = N + 2 ≤ 1000.
MAX_RELEASE_ASSETS = 1000
WARN_RELEASE_ASSETS = 950
#: A sweep never touches an asset younger than this — a catalog cache (or a
#: publish running elsewhere) may still point at it.
MIN_SWEEP_AGE_S = 3600
#: Index and thumbnails are small; anything bigger is not what we wrote.
MAX_INDEX_BYTES = 32 * 1024 * 1024
MAX_THUMB_BYTES = 2 * 1024 * 1024
_TIMEOUT = httpx.Timeout(30.0, read=600.0, write=600.0)
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class MarketplaceError(RuntimeError):
    """A catalog operation failed in a way the admin has to see."""


@dataclass
class CatalogRepo:
    """One catalog repository and how to talk to its host."""
    host_kind: str                     # "github" | "forgejo"
    api_base: str                      # …/repos/<owner>/<repo>
    upload_base: str                   # where asset uploads go
    branch: str
    token: str = ""
    transport: Optional[httpx.BaseTransport] = field(default=None, repr=False)

    # ── construction ────────────────────────────────────────────────────

    @classmethod
    def from_url(cls, url: str, token: str = "", *,
                 transport: Optional[httpx.BaseTransport] = None) -> "CatalogRepo":
        """Accepted catalog addresses (all name the REPOSITORY):

            https://github.com/<org>/<repo>[/tree/<branch>[/…]]
            http(s)://<host>/<owner>/<repo>[/src/branch/<branch>[/…]]     (Forgejo)
            http(s)://<host>/<owner>/<repo>/raw/branch/<branch>/…        (Forgejo raw file)
            https://raw.githubusercontent.com/<org>/<repo>/<branch>/…
        """
        parsed = urlparse((url or "").strip().rstrip("/"))
        host, parts = parsed.netloc, [p for p in parsed.path.split("/") if p]
        scheme = parsed.scheme or "https"
        if host in ("github.com", "raw.githubusercontent.com") and len(parts) >= 2:
            org, repo = parts[0], parts[1]
            branch = "main"
            if host == "github.com" and len(parts) >= 4 and parts[2] == "tree":
                branch = parts[3]
            elif host == "raw.githubusercontent.com" and len(parts) >= 3:
                branch = parts[2]
            return cls("github", f"https://api.github.com/repos/{org}/{repo}",
                       f"https://uploads.github.com/repos/{org}/{repo}",
                       branch, token, transport)
        if host and len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            branch = "main"
            if len(parts) >= 5 and parts[2] in ("src", "raw") and parts[3] == "branch":
                branch = parts[4]
            api = f"{scheme}://{host}/api/v1/repos/{owner}/{repo}"
            return cls("forgejo", api, api, branch, token, transport)
        raise MarketplaceError(
            f"cannot read a repository from {url!r} — use the repository page, "
            "e.g. https://github.com/<org>/<repo> or http://<host>/<owner>/<repo>")

    @property
    def host_limit(self) -> int:
        return HOST_LIMIT_BYTES[self.host_kind]

    def headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        token = (self.token or "").strip()
        if token:
            lower = token.lower()
            h["Authorization"] = (token if lower.startswith(("bearer ", "token "))
                                  else f"token {token}")
        return h

    def client(self) -> httpx.Client:
        return httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                            headers=self.headers(), transport=self.transport)

    # ── host calls ──────────────────────────────────────────────────────

    def _check(self, resp: httpx.Response, what: str) -> httpx.Response:
        if resp.status_code >= 400:
            raise MarketplaceError(
                f"{what} failed: HTTP {resp.status_code} {resp.text[:200]}")
        return resp

    def list_releases(self, c: httpx.Client) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            params = ({"per_page": 100, "page": page} if self.host_kind == "github"
                      else {"limit": 50, "page": page})
            rows = self._check(c.get(f"{self.api_base}/releases", params=params),
                               "listing releases").json()
            if not isinstance(rows, list) or not rows:
                return out
            out.extend(r for r in rows if isinstance(r, dict))
            if len(rows) < params.get("per_page", params.get("limit", 50)):
                return out
            page += 1

    def get_release(self, c: httpx.Client, tag: str) -> Optional[Dict[str, Any]]:
        resp = c.get(f"{self.api_base}/releases/tags/{tag}")
        if resp.status_code == 404:
            return None
        return self._check(resp, f"reading release {tag}").json()

    def ensure_release(self, c: httpx.Client, tag: str) -> Dict[str, Any]:
        rel = self.get_release(c, tag)
        if rel:
            return rel
        body = {"tag_name": tag, "name": tag, "target_commitish": self.branch,
                "body": "Anima Verse marketplace storage — managed by the publisher.",
                "draft": False, "prerelease": False}
        resp = c.post(f"{self.api_base}/releases", json=body)
        if resp.status_code == 422:
            raise MarketplaceError(
                f"creating release {tag} failed: HTTP 422 — the repository needs at "
                "least one commit (e.g. a README) before releases can be created")
        return self._check(resp, f"creating release {tag}").json()

    def list_assets(self, c: httpx.Client, release: Dict[str, Any]) -> List[Dict[str, Any]]:
        rid = release["id"]
        if self.host_kind == "forgejo":
            rows = self._check(c.get(f"{self.api_base}/releases/{rid}/assets"),
                               "listing assets").json()
            return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            rows = self._check(c.get(f"{self.api_base}/releases/{rid}/assets",
                                     params={"per_page": 100, "page": page}),
                               "listing assets").json()
            if not isinstance(rows, list) or not rows:
                return out
            out.extend(r for r in rows if isinstance(r, dict))
            if len(rows) < 100:
                return out
            page += 1

    def upload_asset(self, c: httpx.Client, release: Dict[str, Any], name: str,
                     data: bytes, content_type: str) -> Dict[str, Any]:
        rid = release["id"]
        url = f"{self.upload_base}/releases/{rid}/assets"
        if self.host_kind == "github":
            resp = c.post(url, params={"name": name}, content=data,
                          headers={"Content-Type": content_type})
        else:
            resp = c.post(url, params={"name": name},
                          files={"attachment": (name, data, content_type)})
        return self._check(resp, f"uploading {name}").json()

    def delete_asset(self, c: httpx.Client, release: Dict[str, Any],
                     asset: Dict[str, Any]) -> None:
        aid = asset["id"]
        url = (f"{self.api_base}/releases/assets/{aid}" if self.host_kind == "github"
               else f"{self.api_base}/releases/{release['id']}/assets/{aid}")
        resp = c.delete(url)
        if resp.status_code not in (200, 204, 404):
            self._check(resp, f"deleting {asset.get('name')}")

    def download(self, c: httpx.Client, url: str, max_bytes: int) -> bytes:
        with c.stream("GET", url) as resp:
            if resp.status_code >= 400:
                resp.read()                  # _check reads the error text
            self._check(resp, "download")
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise MarketplaceError(f"download larger than {max_bytes} bytes")
            return bytes(buf)

    def assert_public_if_github(self, c: httpx.Client) -> None:
        if self.host_kind != "github":
            return
        resp = c.get(self.api_base)
        if resp.status_code == 200 and resp.json().get("private"):
            raise MarketplaceError(
                "a GitHub catalog must be a PUBLIC repository — release downloads of a "
                "private GitHub repository fail even with a token; use Forgejo for private catalogs")

    # ── identity ────────────────────────────────────────────────────────

    @property
    def key(self) -> str:
        return self.api_base


# ── content identity ───────────────────────────────────────────────────

def content_hash(zip_bytes: bytes) -> str:
    """SHA-256 over what a pack CONTAINS: member names and bytes, with the
    manifest's ``exported_at`` left out. Every export stamps the moment it was
    made, so the ZIP checksum changes on every publish even when nothing else
    did — this hash is what tells "unchanged" apart, and its head names the
    release asset."""
    h = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in sorted(zf.namelist()):
            data = zf.read(name)
            if name == "manifest.json":
                try:
                    manifest = json.loads(data)
                except ValueError:
                    manifest = None
                if isinstance(manifest, dict):
                    manifest.pop("exported_at", None)
                    data = json.dumps(manifest, sort_keys=True,
                                      ensure_ascii=False).encode("utf-8")
            h.update(name.encode("utf-8") + b"\0")
            h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


# ── index ───────────────────────────────────────────────────────────────

def index_name(now=None) -> str:
    """``index-<YYYYMMDDTHHMMSSffffff>Z.json`` — sorts by name = by time."""
    t = now or utc_now()
    return f"{INDEX_PREFIX}{t.strftime('%Y%m%dT%H%M%S%f')}Z.json"


def _index_assets(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted((a for a in assets
                   if str(a.get("name", "")).startswith(INDEX_PREFIX)
                   and str(a.get("name", "")).endswith(".json")),
                  key=lambda a: str(a["name"]))


def pack_asset_name(slug: str, content_sha: str, ext: str) -> str:
    """``<slug>-<sha8>.<ext>`` — the content hash keeps two versions apart."""
    if not _SAFE_NAME.match(slug or ""):
        raise MarketplaceError(f"unusable pack slug {slug!r}")
    return f"{slug}-{(content_sha or '')[:8]}.{ext}"


def _read_index(repo: CatalogRepo, c: httpx.Client, release: Optional[Dict[str, Any]],
                assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    idx = _index_assets(assets)
    if not release or not idx:
        return {"format": INDEX_FORMAT, "packs": []}
    raw = repo.download(c, idx[-1]["browser_download_url"], MAX_INDEX_BYTES)
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise MarketplaceError(f"catalog index {idx[-1]['name']} is not JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("packs"), list):
        raise MarketplaceError(f"catalog index {idx[-1]['name']} has no pack list")
    if int(data.get("format") or 0) > INDEX_FORMAT:
        raise MarketplaceError(
            f"catalog index format {data.get('format')} is newer than this server "
            f"understands ({INDEX_FORMAT}) — update Anima Verse")
    return data


def fetch_catalog(repo: CatalogRepo) -> Dict[str, Any]:
    """Every pack of every type: one release listing, then the newest index of
    each ``packs-*`` release. The shape the catalog cache has always had."""
    packs: List[Dict[str, Any]] = []
    with repo.client() as c:
        repo.assert_public_if_github(c)
        for rel in repo.list_releases(c):
            tag = str(rel.get("tag_name") or "")
            if not tag.startswith(PACKS_TAG):
                continue
            assets = rel.get("assets")
            if not isinstance(assets, list):
                assets = repo.list_assets(c, rel)
            data = _read_index(repo, c, rel, assets)
            packs.extend(p for p in data["packs"] if isinstance(p, dict) and p.get("id"))
    return {"packs": packs, "host_kind": repo.host_kind}


# ── publish ─────────────────────────────────────────────────────────────

@dataclass
class PackUpload:
    """One pack to publish: the index entry (catalog text and facts) plus the
    bytes. ``entry`` carries at least id, type, slug, name, description, tags,
    content_sha256; the store adds the size, checksum and asset fields."""
    entry: Dict[str, Any]
    zip_bytes: bytes
    checksum_sha256: str
    thumb_bytes: Optional[bytes] = None


_TEXT_KEYS = ("name", "description", "tags", "facts")


def _unchanged(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> bool:
    return bool(old) and old.get("content_sha256") == new.get("content_sha256") and all(
        (old.get(k) or None) == (new.get(k) or None) for k in _TEXT_KEYS)


def _put(repo: CatalogRepo, c: httpx.Client, release: Dict[str, Any],
         have: Dict[str, Dict[str, Any]], name: str, data: bytes,
         content_type: str) -> Dict[str, Any]:
    """The asset ``name`` of ``release`` — the one already up there when a
    previous, half-finished publish left it (content-addressed names: same
    name, same bytes; GitHub would refuse the duplicate), else a fresh
    upload. ``have`` is the release's asset table, kept current."""
    asset = have.get(name)
    if asset is None:
        asset = repo.upload_asset(c, release, name, data, content_type)
        have[name] = asset
    return asset


def publish(repo: CatalogRepo, pack_type: str, uploads: List[PackUpload], *,
            sweep_age_s: int = MIN_SWEEP_AGE_S,
            progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
            flush_every: int = 10) -> List[Dict[str, Any]]:
    """Publish one or more packs of ONE type. Per pack the result is
    ``{pack_id, status: success|no_change|error, download_url?, error?,
    warnings?}``.

    Order per pack: put the ZIP (and thumbnail) under content-addressed
    names; the index is rewritten as a NEW ``index-*.json`` after every
    ``flush_every`` packs and at the end; only then older indexes go, and
    assets that no index names any more are swept once older than
    ``sweep_age_s``. Under one lock per catalog — two publishes of this server
    never interleave; a second SERVER could, which is why the written index
    is read back and a lost race is reported (``MarketplaceError``)."""
    if not uploads:
        return []
    for u in uploads:
        if u.entry.get("type") != pack_type:
            raise MarketplaceError("publish() takes packs of one type at a time")
    results: List[Dict[str, Any]] = []
    with keyed_lock("marketplace_publish", repo.key), repo.client() as c:
        packs_rel = repo.ensure_release(c, PACKS_TAG + pack_type)
        thumbs_rel = repo.ensure_release(c, THUMBS_TAG + pack_type)
        have_packs = {str(a.get("name")): a for a in repo.list_assets(c, packs_rel)}
        have_thumbs = {str(a.get("name")): a for a in repo.list_assets(c, thumbs_rel)}
        index = _read_index(repo, c, packs_rel, list(have_packs.values()))
        by_id = {p["id"]: p for p in index["packs"] if isinstance(p, dict) and p.get("id")}
        pending = 0
        for u in uploads:
            entry = dict(u.entry)
            pid = entry["id"]
            try:
                if len(u.zip_bytes) > repo.host_limit:
                    raise MarketplaceError(
                        f"pack is {len(u.zip_bytes) // (1024 * 1024)} MB — over the "
                        f"{repo.host_limit // (1024 * 1024)} MB per-file limit of the host")
                old = by_id.get(pid)
                if _unchanged(old, entry):
                    results.append({"pack_id": pid, "status": "no_change",
                                    "download_url": old.get("download_url")})
                    if progress:
                        progress(pid, results[-1])
                    continue
                name = pack_asset_name(entry["slug"], entry["content_sha256"], "zip")
                # The release must take the new ZIP AND the transient second
                # index — counted on what is really up there, sweep leftovers
                # included.
                if name not in have_packs and len(have_packs) + 2 > MAX_RELEASE_ASSETS:
                    raise MarketplaceError(
                        f"the {pack_type} release is full ({len(have_packs)} files)")
                asset = _put(repo, c, packs_rel, have_packs, name, u.zip_bytes,
                             "application/zip")
                entry.update({"asset": name,
                              "download_url": asset["browser_download_url"],
                              "size_bytes": len(u.zip_bytes),
                              "checksum_sha256": u.checksum_sha256})
                # The thumbnail derives from the content: same content, same
                # picture — an existing one is kept, a missing one is added.
                thumb = (old or {}).get("thumbnail") if old and old.get("asset") == name else None
                if not thumb and u.thumb_bytes:
                    tname = pack_asset_name(entry["slug"], entry["content_sha256"], "webp")
                    tasset = _put(repo, c, thumbs_rel, have_thumbs, tname, u.thumb_bytes,
                                  "image/webp")
                    thumb = {"asset": tname, "download_url": tasset["browser_download_url"]}
                entry["thumbnail"] = thumb
                entry["published_at"] = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
                by_id[pid] = entry
                pending += 1
                results.append({"pack_id": pid, "status": "success",
                                "download_url": entry["download_url"]})
            except (MarketplaceError, httpx.HTTPError) as e:
                logger.warning("publish %s failed: %s", pid, e)
                results.append({"pack_id": pid, "status": "error", "error": str(e)})
            if progress:
                progress(pid, results[-1])
            if pending and pending % flush_every == 0:
                _write_index(repo, c, packs_rel, pack_type, by_id)
        if pending and pending % flush_every:
            _write_index(repo, c, packs_rel, pack_type, by_id)
        try:
            _sweep(repo, c, packs_rel, thumbs_rel, by_id, sweep_age_s)
        except (MarketplaceError, httpx.HTTPError) as e:
            # The catalog is written; the next publish sweeps again.
            logger.warning("marketplace sweep failed (catalog is fine): %s", e)
        files = len(have_packs)
    if files + 2 > WARN_RELEASE_ASSETS:
        note = (f"The {pack_type} release holds {files} files — it takes at most "
                f"{MAX_RELEASE_ASSETS}.")
        for r in results:
            r.setdefault("warnings", []).append(note)
    return results


def _write_index(repo: CatalogRepo, c: httpx.Client, release: Dict[str, Any],
                 pack_type: str, by_id: Dict[str, Dict[str, Any]]) -> None:
    """Upload the catalog as a NEW index file, then drop the older ones — the
    newest file is the catalog, so readers never see a gap."""
    name = index_name()
    body = {"format": INDEX_FORMAT, "type": pack_type,
            "updated_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "packs": sorted(by_id.values(), key=lambda p: str(p.get("name") or p["id"]).lower())}
    repo.upload_asset(c, release, name,
                      json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8"),
                      "application/json")
    indexes = _index_assets(repo.list_assets(c, release))
    if not indexes or indexes[-1]["name"] != name:
        raise MarketplaceError(
            "another publish wrote the catalog index at the same time — publish again")
    # Best effort: readers take the newest index, and an older one that
    # survives here is swept later like any asset no index names.
    for old in indexes[:-1]:
        try:
            repo.delete_asset(c, release, old)
        except (MarketplaceError, httpx.HTTPError) as e:
            logger.warning("old catalog index %s not deleted: %s", old.get("name"), e)


def _age_s(asset: Dict[str, Any]) -> float:
    try:
        return (utc_now() - parse_iso(str(asset.get("created_at") or ""))).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _sweep(repo: CatalogRepo, c: httpx.Client, packs_rel: Dict[str, Any],
           thumbs_rel: Dict[str, Any], by_id: Dict[str, Dict[str, Any]],
           min_age_s: int) -> int:
    """Delete assets the current index no longer names (replaced versions,
    uploads of an aborted publish) once they are older than ``min_age_s``.
    The newest index is never touched. Returns the number deleted."""
    keep_zip = {p.get("asset") for p in by_id.values()}
    keep_thumb = {(p.get("thumbnail") or {}).get("asset") for p in by_id.values()}
    deleted = 0
    for rel, keep in ((packs_rel, keep_zip), (thumbs_rel, keep_thumb)):
        assets = repo.list_assets(c, rel)
        newest_index = (_index_assets(assets)[-1:] or [{}])[0].get("name")
        for a in assets:
            name = str(a.get("name") or "")
            if name in keep or name == newest_index:
                continue
            if _age_s(a) < max(min_age_s, MIN_SWEEP_AGE_S):
                continue
            repo.delete_asset(c, rel, a)
            deleted += 1
    if deleted:
        logger.info("marketplace sweep: %d stale asset(s) removed", deleted)
    return deleted


def release_capacity(repo: CatalogRepo, pack_type: str) -> Tuple[int, int]:
    """``(packs, limit)`` of one type's release — for a warning before the
    1000-asset wall."""
    with repo.client() as c:
        rel = repo.get_release(c, PACKS_TAG + pack_type)
        n = len(repo.list_assets(c, rel)) if rel else 0
    return n, MAX_RELEASE_ASSETS - 2
