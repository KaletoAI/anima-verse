#!/usr/bin/env python3
"""Smoke run for the marketplace RELEASE storage (plan-marketplace-props.md
Teil C, ``app/core/marketplace_store.py``).

No network: a fake Git host lives in memory behind ``httpx.MockTransport``, in
two flavours that differ exactly where the real hosts do — GitHub (raw upload
body to uploads.github.com, ``/releases/assets/<id>`` deletes, duplicate asset
names refused, anonymous downloads) and Forgejo (multipart ``attachment``
upload, ``/releases/<rid>/assets/<id>`` deletes, duplicate names ACCEPTED,
downloads need the token). Every expectation is derived by hand from the
protocol in the plan:

    packs-<type>   <slug>-<sha8>.zip per pack + index-<stamp>.json (newest wins)
    thumbs-<type>  <slug>-<sha8>.webp per pack
    a publish uploads NEXT TO the old files, writes a NEW index, deletes the
    older indexes; replaced files are swept only once older than the sweep age.

[1]  GitHub, empty repository → catalog has no packs.
[2]  publish prop A (slug "chair-1", content "aaaaaaaa…", thumb) → success;
     packs-prop holds {chair-1-aaaaaaaa.zip, 1 index}; thumbs-prop holds
     {chair-1-aaaaaaaa.webp}; the catalog lists A with size 7 (b"ZIP-v1-"),
     its checksum, download_url = the asset's URL, thumbnail asset name.
[3]  same publish again → no_change, packs-prop unchanged (2 assets — no new
     index was written).
[4]  only the description changes → success WITHOUT a new zip: packs-prop
     still holds 1 zip + 1 index (the old index is gone), the catalog shows the
     new description.
[5]  new content "bbbbbbbb…" → chair-1-bbbbbbbb.zip uploaded; the OLD zip is
     still there (young: a catalog cache may still name it); 1 index; the
     catalog points at the new zip.
[6]  every asset aged 2 h, then publish prop B → the sweep deletes the old
     chair-1-aaaaaaaa.zip and .webp; zips left = {chair-1-bbbbbbbb, table-1-cccccccc}.
[7]  a pack over the host limit (limit patched to 4 bytes) → status "error",
     nothing uploaded.
[8]  a second server writes a NEWER index right after ours → MarketplaceError
     ("another publish wrote the catalog index at the same time").
[9]  an index of format 99 → MarketplaceError (newer than this server).
[10] a PRIVATE GitHub repository → MarketplaceError on read.
[11] Forgejo: publish with the token works and the catalog reads with it; the
     same catalog WITHOUT the token fails (downloads answer 404).
[12] Route: install of a pack whose cached download answers 404 → the catalog
     is fetched fresh ONCE and the pack is installed from the new URL.
[13] the index download answers 404 → MarketplaceError (not a raw httpx
     streaming error, which the routes would map to 500).
[14] (fresh host) a publish that died after its ZIP upload left
     "stool-1-ffffffff.zip" in the release; publishing it again REUSES that file (GitHub would refuse a
     duplicate name) → success, exactly one asset of that name, indexed.
[15] "bench-1" published without a thumbnail, then the same content with new
     text AND a thumbnail → the thumbnail is uploaded and indexed.
[16] every DELETE fails (host hiccup) → the publish still succeeds; the sweep
     only logs, the catalog names the new pack.

Usage:  ./.venv/bin/python scripts/smoke_marketplace_release_store.py
"""
import asyncio
import email
import itertools
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="marketplace-store-smoke-"))
os.environ["STORAGE_DIR"] = str(STORAGE)

from app.core import paths  # noqa: E402
paths.init(STORAGE)

import httpx  # noqa: E402

from app.core import marketplace_store as ms  # noqa: E402

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


class FakeHost:
    """An in-memory Git host with releases and assets."""

    def __init__(self, kind: str, private: bool = False, token: str = ""):
        self.kind, self.private, self.token = kind, private, token
        self.releases = {}
        self.ids = itertools.count(1)
        self.on_upload = None
        self.fail_download = set()      # asset names whose download answers 404
        self.fail_delete = False        # every DELETE answers 500
        if kind == "github":
            self.api = "https://api.github.com/repos/o/r"
            self.up = "https://uploads.github.com/repos/o/r"
            self.dl = "https://github.com/o/r/releases/download"
        else:
            self.api = self.up = "http://forge/api/v1/repos/o/r"
            self.dl = "http://forge/attachments"

    # helpers
    def assets(self, tag):
        rel = next((r for r in self.releases.values() if r["tag_name"] == tag), None)
        return sorted(a["name"] for a in rel["assets"]) if rel else []

    def age_all(self, seconds):
        stamp = "2000-01-01T00:00:00Z" if seconds else None
        for rel in self.releases.values():
            for a in rel["assets"]:
                a["created_at"] = stamp

    def _public(self, a):
        return {k: v for k, v in a.items() if k != "data"}

    def _rel_json(self, rel):
        return {**{k: v for k, v in rel.items() if k != "assets"},
                "assets": [self._public(a) for a in rel["assets"]]}

    def add_asset(self, rel, name, data):
        if self.kind == "github" and any(a["name"] == name for a in rel["assets"]):
            return httpx.Response(422, json={"message": "already_exists"})
        aid = next(self.ids)
        url = (f"{self.dl}/{rel['tag_name']}/{name}" if self.kind == "github"
               else f"{self.dl}/uuid-{aid}")
        asset = {"id": aid, "name": name, "size": len(data), "data": data,
                 "browser_download_url": url, "created_at": "2099-01-01T00:00:00Z"}
        rel["assets"].append(asset)
        return httpx.Response(201, json=self._public(asset))

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url).split("?")[0]
        authed = req.headers.get("authorization") == f"token {self.token}" if self.token else True
        # downloads
        for rel in self.releases.values():
            for a in rel["assets"]:
                if url == a["browser_download_url"]:
                    if a["name"] in self.fail_download:
                        return httpx.Response(404, text="gone")
                    if self.kind == "forgejo" and self.private and not authed:
                        return httpx.Response(404)
                    return httpx.Response(200, content=a["data"])
        if self.kind == "forgejo" and self.private and not authed:
            return httpx.Response(404)
        if req.method == "GET" and url == self.api:
            return httpx.Response(200, json={"private": self.private})
        if req.method == "GET" and url == f"{self.api}/releases":
            page = int(req.url.params.get("page", "1"))
            rows = [self._rel_json(r) for r in self.releases.values()]
            return httpx.Response(200, json=rows if page == 1 else [])
        if req.method == "POST" and url == f"{self.api}/releases":
            body = json.loads(req.content)
            rid = next(self.ids)
            self.releases[rid] = {"id": rid, "tag_name": body["tag_name"], "assets": []}
            return httpx.Response(201, json=self._rel_json(self.releases[rid]))
        if req.method == "GET" and url.startswith(f"{self.api}/releases/tags/"):
            tag = url.rsplit("/", 1)[1]
            rel = next((r for r in self.releases.values() if r["tag_name"] == tag), None)
            return httpx.Response(200, json=self._rel_json(rel)) if rel else httpx.Response(404)
        if url.startswith(f"{self.up}/releases/") and url.endswith("/assets") and req.method == "POST":
            rid = int(url.split("/releases/")[1].split("/")[0])
            name = req.url.params["name"]
            if self.kind == "github":
                data = req.content
            else:
                msg = email.message_from_bytes(
                    b"Content-Type: " + req.headers["content-type"].encode() + b"\r\n\r\n"
                    + req.content)
                data = next(p.get_payload(decode=True) for p in msg.get_payload()
                            if 'name="attachment"' in p.get("Content-Disposition", ""))
            resp = self.add_asset(self.releases[rid], name, data)
            if self.on_upload:
                self.on_upload(self.releases[rid], name)
            return resp
        if url.startswith(f"{self.api}/releases/") and url.endswith("/assets") and req.method == "GET":
            rid = int(url.split("/releases/")[1].split("/")[0])
            page = int(req.url.params.get("page", "1"))
            rows = [self._public(a) for a in self.releases[rid]["assets"]]
            return httpx.Response(200, json=rows if page == 1 else [])
        if req.method == "DELETE":
            if self.fail_delete:
                return httpx.Response(500, text="host hiccup")
            aid = int(url.rsplit("/", 1)[1])
            for rel in self.releases.values():
                rel["assets"] = [a for a in rel["assets"] if a["id"] != aid]
            return httpx.Response(204)
        return httpx.Response(500, text=f"fake host: unhandled {req.method} {url}")


def repo_for(host: FakeHost, token: str = "") -> ms.CatalogRepo:
    url = ("https://github.com/o/r" if host.kind == "github"
           else "http://forge/o/r/raw/branch/main/index.json")
    return ms.CatalogRepo.from_url(url, token, transport=httpx.MockTransport(host.handler))


def upload(slug, sha, data, description="", thumb=b"WEBP"):
    return ms.PackUpload(
        entry={"id": f"prop-{slug}", "type": "prop", "slug": slug, "name": slug.title(),
               "description": description, "tags": [], "content_sha256": sha,
               "manifest_version": 1, "facts": {}},
        zip_bytes=data, checksum_sha256="sum-" + sha[:4], thumb_bytes=thumb)


def zips(host):
    return [n for n in host.assets("packs-prop") if n.endswith(".zip")]


def indexes(host):
    return [n for n in host.assets("packs-prop") if n.startswith("index-")]


A1, A2, B1 = "a" * 64, "b" * 64, "c" * 64

print("\n[1] empty GitHub repository")
gh = FakeHost("github")
repo = repo_for(gh, "tok")
check("host kind", repo.host_kind, "github")
check("no packs", ms.fetch_catalog(repo)["packs"], [])

print("\n[2] first publish")
res = ms.publish(repo, "prop", [upload("chair-1", A1, b"ZIP-v1-")])
check("status", res[0]["status"], "success")
check("packs-prop zips", zips(gh), ["chair-1-aaaaaaaa.zip"])
check("one index", len(indexes(gh)), 1)
check("thumbs-prop", gh.assets("thumbs-prop"), ["chair-1-aaaaaaaa.webp"])
cat = ms.fetch_catalog(repo)["packs"]
check("catalog lists one pack", [p["id"] for p in cat], ["prop-chair-1"])
check("size", cat[0]["size_bytes"], 7)
check("checksum", cat[0]["checksum_sha256"], "sum-aaaa")
check("download_url", cat[0]["download_url"],
      "https://github.com/o/r/releases/download/packs-prop/chair-1-aaaaaaaa.zip")
check("thumbnail", cat[0]["thumbnail"]["asset"], "chair-1-aaaaaaaa.webp")

print("\n[3] the same publish again")
before = gh.assets("packs-prop")
check("status", ms.publish(repo, "prop", [upload("chair-1", A1, b"ZIP-v1-")])[0]["status"],
      "no_change")
check("nothing uploaded", gh.assets("packs-prop"), before)

print("\n[4] only the description changes")
check("status", ms.publish(repo, "prop", [upload("chair-1", A1, b"ZIP-v1-",
                                                 description="Oak")])[0]["status"], "success")
check("still one zip", zips(gh), ["chair-1-aaaaaaaa.zip"])
check("still one index", len(indexes(gh)), 1)
check("new description", ms.fetch_catalog(repo)["packs"][0]["description"], "Oak")

print("\n[5] new content")
ms.publish(repo, "prop", [upload("chair-1", A2, b"ZIP-v2--", description="Oak")])
check("old zip kept (young), new zip added", zips(gh),
      ["chair-1-aaaaaaaa.zip", "chair-1-bbbbbbbb.zip"])
check("one index", len(indexes(gh)), 1)
check("catalog points at the new zip", ms.fetch_catalog(repo)["packs"][0]["asset"],
      "chair-1-bbbbbbbb.zip")

print("\n[6] the sweep removes replaced files once they are old")
gh.age_all(7200)
ms.publish(repo, "prop", [upload("table-1", B1, b"ZIP-T")])
check("zips", zips(gh), ["chair-1-bbbbbbbb.zip", "table-1-cccccccc.zip"])
check("thumbs", gh.assets("thumbs-prop"), ["chair-1-bbbbbbbb.webp", "table-1-cccccccc.webp"])
check("one index", len(indexes(gh)), 1)

print("\n[7] over the host limit")
saved = dict(ms.HOST_LIMIT_BYTES)
ms.HOST_LIMIT_BYTES["github"] = 4
before = gh.assets("packs-prop")
r7 = ms.publish(repo, "prop", [upload("huge-1", "d" * 64, b"ZIP-HUGE")])[0]
ms.HOST_LIMIT_BYTES.update(saved)
check("status", r7["status"], "error")
check("nothing uploaded", gh.assets("packs-prop"), before)

print("\n[8] another server writes a newer index right after ours")


def race(rel, name):
    if name.startswith(ms.INDEX_PREFIX) and not name.startswith("index-9"):
        gh.add_asset(rel, "index-99999999T999999999999Z.json", b'{"format":1,"packs":[]}')


gh.on_upload = race
try:
    ms.publish(repo, "prop", [upload("lamp-1", "e" * 64, b"ZIP-L")])
    check("race reported", "no error", "MarketplaceError")
except ms.MarketplaceError as e:
    check("race reported", "at the same time" in str(e), True)
gh.on_upload = None

print("\n[9] an index from a newer server")
gh9 = FakeHost("github")
r9 = repo_for(gh9, "tok")
rel9 = r9.ensure_release(r9.client(), "packs-prop")
gh9.add_asset(gh9.releases[rel9["id"]], "index-20261002T000000000000Z.json",
              b'{"format":99,"packs":[]}')
try:
    ms.fetch_catalog(r9)
    check("newer format refused", "read", "MarketplaceError")
except ms.MarketplaceError as e:
    check("newer format refused", "newer than this server" in str(e), True)

print("\n[10] a private GitHub repository")
try:
    ms.fetch_catalog(repo_for(FakeHost("github", private=True), "tok"))
    check("private GitHub refused", "read", "MarketplaceError")
except ms.MarketplaceError as e:
    check("private GitHub refused", "must be a PUBLIC repository" in str(e), True)

print("\n[11] private Forgejo: token in, token out")
fj = FakeHost("forgejo", private=True, token="secret")
fr = repo_for(fj, "secret")
check("host kind", fr.host_kind, "forgejo")
check("publish", ms.publish(fr, "prop", [upload("chair-1", A1, b"ZIP-v1-")])[0]["status"],
      "success")
check("catalog with token", [p["id"] for p in ms.fetch_catalog(fr)["packs"]], ["prop-chair-1"])
check("download_url is an attachment", ms.fetch_catalog(fr)["packs"][0]["download_url"]
      .startswith("http://forge/attachments/"), True)
try:
    ms.fetch_catalog(repo_for(fj, ""))
    check("catalog without token fails", "read", "MarketplaceError")
except ms.MarketplaceError:
    check("catalog without token fails", True, True)

print("\n[12] route: a 404 on a cached download refreshes the catalog once")
from app.routes import content_packs as cp  # noqa: E402

cp._list_catalogs = lambda: [{"_id": "test", "name": "Test", "url": "https://github.com/o/r",
                              "auth_token": ""}]
cp._write_cache("test", {"packs": [{"id": "prop-x", "type": "prop", "name": "X",
                                    "download_url": "https://old/x.zip",
                                    "checksum_sha256": ""}],
                         "source_url": "https://github.com/o/r"})
fetched, downloads = [], []


def fake_fetch(repo_):
    fetched.append(repo_.api_base)
    return {"packs": [{"id": "prop-x", "type": "prop", "name": "X",
                       "download_url": "https://new/x.zip", "checksum_sha256": ""}]}


async def fake_download(url, headers, **kw):
    downloads.append(url)
    if url == "https://old/x.zip":
        req = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
    tmp = STORAGE / "x.zip"
    tmp.write_bytes(b"PK")
    return tmp


cp.fetch_catalog = fake_fetch
cp._download = fake_download
cp._install_downloaded = lambda *a, **kw: {"status": "success"}


class Req:
    async def json(self):
        return {"pack_id": "prop-x", "catalog_id": "test"}


out = asyncio.run(cp.install_pack(Req()))
check("installed", out["status"], "success")
check("downloads", downloads, ["https://old/x.zip", "https://new/x.zip"])
check("catalog fetched once", len(fetched), 1)
check("cache now names the new URL",
      cp._read_cache("test")["packs"][0]["download_url"], "https://new/x.zip")

print("\n[13] an index download that answers 404")
gh13 = FakeHost("github")
r13 = repo_for(gh13, "tok")
ms.publish(r13, "prop", [upload("chair-1", A1, b"ZIP-v1-")])
gh13.fail_download = set(indexes(gh13))
try:
    ms.fetch_catalog(r13)
    check("MarketplaceError", "read", "MarketplaceError")
except ms.MarketplaceError as e:
    check("MarketplaceError with the status", "HTTP 404" in str(e), True)

print("\n[14] retry after a publish that died behind its ZIP upload")
# A fresh host: [8] left a foreign "newer" index on the first one on purpose.
gh = FakeHost("github")
repo = repo_for(gh, "tok")
with repo.client() as _c:
    repo.ensure_release(_c, "packs-prop")
rel14 = next(r for r in gh.releases.values() if r["tag_name"] == "packs-prop")
gh.add_asset(rel14, "stool-1-ffffffff.zip", b"ZIP-S")
r14 = ms.publish(repo, "prop", [upload("stool-1", "f" * 64, b"ZIP-S", thumb=None)])[0]
check("status", r14["status"], "success")
check("one file of that name", gh.assets("packs-prop").count("stool-1-ffffffff.zip"), 1)
check("indexed", any(p["id"] == "prop-stool-1" for p in ms.fetch_catalog(repo)["packs"]), True)

print("\n[15] a thumbnail added by a text-only change")
ms.publish(repo, "prop", [upload("bench-1", "9" * 64, b"ZIP-B", thumb=None)])
bench = next(p for p in ms.fetch_catalog(repo)["packs"] if p["id"] == "prop-bench-1")
check("no thumbnail at first", bench.get("thumbnail"), None)
ms.publish(repo, "prop", [upload("bench-1", "9" * 64, b"ZIP-B", description="Wood")])
bench = next(p for p in ms.fetch_catalog(repo)["packs"] if p["id"] == "prop-bench-1")
check("thumbnail now", (bench.get("thumbnail") or {}).get("asset"), "bench-1-99999999.webp")

print("\n[16] the sweep fails, the publish does not")
gh.age_all(7200)
gh.fail_delete = True
r16 = ms.publish(repo, "prop", [upload("shelf-1", "8" * 64, b"ZIP-SH")])[0]
gh.fail_delete = False
check("status", r16["status"], "success")
check("indexed", any(p["id"] == "prop-shelf-1"
                     for p in ms.fetch_catalog(repo)["packs"]), True)

print("\nall checks passed" if not FAILURES
      else f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
