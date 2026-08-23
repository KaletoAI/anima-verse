#!/usr/bin/env python3
"""Smoke run for the marketplace pack DOWNLOAD: size cap + streaming to disk.

Runs against a THROWAWAY storage directory and a STUBBED httpx — no network,
no world DB, no server. Only `app.routes.content_packs` is exercised.

Usage:
    ./.venv/bin/python scripts/smoke_content_pack_limit.py

What is under test
------------------
`_download()` streams a pack chunk-by-chunk into a unique temp file under
`<storage>/.cache/` and aborts as soon as the running total passes the cap
from `content_marketplace.max_pack_mb`. Nothing is buffered in RAM, and no
partial file may survive an abort.

Expectations, derived by hand from the code, not recorded from a run:

  [1] `_max_pack_mb()` — default 500, clamp [1, 4096]:
        missing key / None / ""  -> 500  (schema default)
        "not-a-number"           -> 500  (unparsable = unset)
        0, -5                    -> 1    (clamped up)
        1, 250, "250", 500       -> unchanged (in range)
        12.9                     -> 12   (int(float(x)), truncating)
        4096                     -> 4096 (upper bound is inclusive)
        9999                     -> 4096 (clamped down)

  [2] `_mb_label()` renders the cap for the message:
        1 MiB -> "1", 500 MiB -> "500", 512 KiB -> "0.5"

  [3] Over the cap, explicit `max_bytes=1 MiB`, body 4 MiB in 64 KiB chunks:
        ValueError with EXACTLY
          "pack exceeds the 1 MB limit (content_marketplace.max_pack_mb)"
        The abort is STREAMING: 1 MiB / 64 KiB = 16 chunks reach the cap
        exactly (16*65536 == 1048576, not yet ">"), the 17th pushes the total
        to 1114112 > 1048576 and raises. So the stub yielded 17 of its 64
        chunks — the remaining 47 were never pulled.
        `<storage>/.cache/` holds NO pack_* file afterwards.

  [4] The same abort driven by CONFIG instead of the argument:
        content_marketplace.max_pack_mb = 1, no `max_bytes` -> same message.
        With max_pack_mb = 2 the same 4 MiB body says "2 MB".

  [5] Under the cap: a real 3-member ZIP (~140 bytes) arrives as a PATH.
        The path exists, lives in `<storage>/.cache`, is named pack_*.zip.part,
        its bytes equal the streamed body, and `zipfile.ZipFile(path)` opens
        it from disk: namelist == the three members, manifest.json parses.
        `_assert_readable_zip(path)` passes. Two downloads never collide —
        the two paths differ and both exist at the same time.

  [6] `_verify_checksum(path, sha)` hashes from the FILE: the real sha256
        passes, a wrong one raises ValueError starting "checksum mismatch:".
        An empty expectation is a no-op.

  [7] `_assert_readable_zip` rejects a non-ZIP body ("invalid pack ZIP: ")
        and an empty file — both ValueError, which the routes map to 400.

  [8] Route level, `install_pack_url` (allow_install_url = true):
        oversized body      -> HTTPException 400, detail == the [3] message
        non-ZIP body        -> HTTPException 400, detail starts "invalid pack ZIP"
        after BOTH, `<storage>/.cache/` holds no pack_* file: the route's
        `finally` unlinks the temp file even on the success-then-fail path.
"""
import asyncio
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="content-pack-limit-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="content-pack-limit-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)

import httpx as _real_httpx  # noqa: E402
from app.core import config  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
from app.routes import content_packs as cp  # noqa: E402

MAX_PACK_FIELD = SECTIONS["content_marketplace"]["fields"]["max_pack_mb"]

CHECKED = 0
FAILURES = []


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    shown = repr(actual)
    if len(shown) > 160:
        shown = shown[:157] + "…"
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {shown}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def set_cfg(**kwargs):
    """Replace the content_marketplace section in the loaded config."""
    config._CONFIG["content_marketplace"] = dict(kwargs)


def cache_temps():
    """The download temp files currently lying around."""
    d = STORAGE / ".cache"
    return sorted(p.name for p in d.glob("pack_*")) if d.exists() else []


# ── the httpx stub ───────────────────────────────────────────────────────

class _Stream:
    def __init__(self, chunks, counter):
        self._chunks = chunks
        self._counter = counter

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        for c in self._chunks:
            self._counter["yielded"] += 1
            yield c


class _Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url):
        return _Stream(STUB["chunks"], STUB["counter"])


STUB = {"chunks": [], "counter": {"yielded": 0}}
cp.httpx = SimpleNamespace(AsyncClient=_Client, HTTPError=_real_httpx.HTTPError)


def serve(body: bytes, chunk_size: int = 65536):
    """Arm the stub with `body`, split into fixed-size chunks."""
    STUB["chunks"] = [body[i:i + chunk_size] for i in range(0, len(body), chunk_size)]
    STUB["counter"] = {"yielded": 0}
    return len(STUB["chunks"])


def download(**kw):
    return asyncio.run(cp._download("https://example.invalid/pack.zip", {}, **kw))


MB = 1024 * 1024

# ── [1] config default + clamp ───────────────────────────────────────────

print("\n[1] max_pack_mb: default 500, clamp [1, 4096]")
set_cfg()
check("missing key -> default", cp._max_pack_mb(), 500)
set_cfg(max_pack_mb=None)
check("None -> default", cp._max_pack_mb(), 500)
set_cfg(max_pack_mb="")
check("empty string -> default", cp._max_pack_mb(), 500)
set_cfg(max_pack_mb="   ")
check("blank string -> default", cp._max_pack_mb(), 500)
set_cfg(max_pack_mb="not-a-number")
check("unparsable -> default", cp._max_pack_mb(), 500)
set_cfg(max_pack_mb=0)
check("0 -> clamped up to 1", cp._max_pack_mb(), 1)
set_cfg(max_pack_mb=-5)
check("-5 -> clamped up to 1", cp._max_pack_mb(), 1)
set_cfg(max_pack_mb=1)
check("1 -> 1 (lower bound)", cp._max_pack_mb(), 1)
set_cfg(max_pack_mb=250)
check("250 -> 250", cp._max_pack_mb(), 250)
set_cfg(max_pack_mb="250")
check("'250' -> 250", cp._max_pack_mb(), 250)
set_cfg(max_pack_mb=12.9)
check("12.9 -> 12 (truncating)", cp._max_pack_mb(), 12)
set_cfg(max_pack_mb=4096)
check("4096 -> 4096 (upper bound inclusive)", cp._max_pack_mb(), 4096)
set_cfg(max_pack_mb=9999)
check("9999 -> clamped down to 4096", cp._max_pack_mb(), 4096)
check("the admin field advertises the same default",
      MAX_PACK_FIELD["default"], 500)
check("...the same bounds",
      [MAX_PACK_FIELD["min"], MAX_PACK_FIELD["max"]], [1, 4096])
check("...and is an int field labelled for the UI",
      [MAX_PACK_FIELD["type"], MAX_PACK_FIELD["label"]],
      ["int", "Max pack size (MB)"])

# ── [2] the MB label ─────────────────────────────────────────────────────

print("\n[2] _mb_label")
check("1 MiB", cp._mb_label(MB), "1")
check("500 MiB", cp._mb_label(500 * MB), "500")
check("512 KiB", cp._mb_label(512 * 1024), "0.5")

# ── [3] over the cap, streaming abort ────────────────────────────────────

print("\n[3] over the cap: abort mid-stream, no temp file left behind")
set_cfg()
total_chunks = serve(b"x" * (4 * MB))
check("the stub holds 64 chunks of 64 KiB", total_chunks, 64)
try:
    download(max_bytes=MB)
    check("oversized download raises", "no error", "ValueError")
except ValueError as e:
    check("oversized download raises ValueError with the actionable message",
          str(e),
          "pack exceeds the 1 MB limit (content_marketplace.max_pack_mb)")
check("aborted after 17 of 64 chunks (streaming, not buffered)",
      STUB["counter"]["yielded"], 17)
check("no temp file left behind", cache_temps(), [])

# ── [4] the cap comes from the config ────────────────────────────────────

print("\n[4] the cap comes from content_marketplace.max_pack_mb")
set_cfg(max_pack_mb=1)
serve(b"x" * (4 * MB))
try:
    download()
    check("config cap 1 MB raises", "no error", "ValueError")
except ValueError as e:
    check("config cap 1 MB, message names the limit", str(e),
          "pack exceeds the 1 MB limit (content_marketplace.max_pack_mb)")
check("still no temp file", cache_temps(), [])

set_cfg(max_pack_mb=2)
serve(b"x" * (4 * MB))
try:
    download()
    check("config cap 2 MB raises", "no error", "ValueError")
except ValueError as e:
    check("config cap 2 MB, message follows the config", str(e),
          "pack exceeds the 2 MB limit (content_marketplace.max_pack_mb)")
check("still no temp file", cache_temps(), [])

# ── [5] under the cap: a readable ZIP path ───────────────────────────────

print("\n[5] under the cap: the pack lands as a readable ZIP path")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("manifest.json", json.dumps({"version": 1, "type": "item",
                                             "name": "Test Pack"}))
    zf.writestr("files/a.txt", "a")
    zf.writestr("files/b.txt", "b")
ZIP_BYTES = buf.getvalue()

set_cfg(max_pack_mb=500)
serve(ZIP_BYTES)
p1 = download()
check("returns a Path", isinstance(p1, Path), True)
check("the file exists", p1.exists(), True)
check("it lives in the world cache dir", p1.parent, STORAGE / ".cache")
check("named pack_*.zip.part",
      p1.name.startswith("pack_") and p1.name.endswith(".zip.part"), True)
check("bytes are the streamed body", p1.read_bytes(), ZIP_BYTES)
check("_assert_readable_zip passes", cp._assert_readable_zip(p1), None)
with zipfile.ZipFile(p1) as zf:
    check("zipfile opens the PATH directly", sorted(zf.namelist()),
          ["files/a.txt", "files/b.txt", "manifest.json"])
    check("manifest reads back",
          json.loads(zf.read("manifest.json"))["name"], "Test Pack")

serve(ZIP_BYTES)
p2 = download()
check("a second download gets its own unique temp name", p1.name != p2.name, True)
check("both files coexist", [p1.exists(), p2.exists()], [True, True])

# ── [6] checksum from the file ───────────────────────────────────────────

print("\n[6] checksum is hashed from the file")
SHA = hashlib.sha256(ZIP_BYTES).hexdigest()
check("matching sha256 passes", cp._verify_checksum(p1, SHA), None)
check("uppercase sha256 passes too", cp._verify_checksum(p1, SHA.upper()), None)
check("an empty expectation is a no-op", cp._verify_checksum(p1, ""), None)
try:
    cp._verify_checksum(p1, "0" * 64)
    check("a wrong sha256 raises", "no error", "ValueError")
except ValueError as e:
    check("a wrong sha256 raises ValueError",
          str(e).startswith("checksum mismatch: pack rejected"), True)

# ── [7] structure check ──────────────────────────────────────────────────

print("\n[7] a broken download fails as a ValueError (route -> 400)")
serve(b"this is not a zip file, not even close" * 4)
p3 = download()
try:
    cp._assert_readable_zip(p3)
    check("a non-ZIP body raises", "no error", "ValueError")
except ValueError as e:
    check("a non-ZIP body raises ValueError",
          str(e).startswith("invalid pack ZIP: "), True)
serve(b"")
p4 = download()
check("an empty body still produces a file", p4.exists(), True)
try:
    cp._assert_readable_zip(p4)
    check("an empty body raises", "no error", "ValueError")
except ValueError as e:
    check("an empty body raises ValueError too",
          str(e).startswith("invalid pack ZIP: "), True)

for p in (p1, p2, p3, p4):
    p.unlink(missing_ok=True)
check("cache dir clean again", cache_temps(), [])

# ── [8] route level: the finally unlinks ─────────────────────────────────

print("\n[8] install_url route: 400 + no leftovers")
from fastapi import HTTPException  # noqa: E402


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


set_cfg(allow_install_url=True, max_pack_mb=1)
serve(b"x" * (4 * MB))
try:
    asyncio.run(cp.install_pack_url(_Req({"url": "https://example.invalid/p.zip",
                                          "type": "item"})))
    check("oversized install raises", "no error", "HTTPException")
except HTTPException as e:
    check("oversized install -> 400", e.status_code, 400)
    check("...with the actionable detail", e.detail,
          "pack exceeds the 1 MB limit (content_marketplace.max_pack_mb)")
check("no temp file after the abort", cache_temps(), [])

set_cfg(allow_install_url=True, max_pack_mb=500)
serve(b"definitely not a zip")
try:
    asyncio.run(cp.install_pack_url(_Req({"url": "https://example.invalid/p.zip",
                                          "type": "item"})))
    check("non-ZIP install raises", "no error", "HTTPException")
except HTTPException as e:
    check("non-ZIP install -> 400", e.status_code, 400)
    check("...with the ZIP detail",
          str(e.detail).startswith("invalid pack ZIP: "), True)
check("the downloaded temp file was unlinked by the finally", cache_temps(), [])

# ── Summary ──────────────────────────────────────────────────────────────

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("OK")
