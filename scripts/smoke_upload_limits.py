#!/usr/bin/env python3
"""Checks the upload caps (SEC-7) and the skill-package trust gate (SEC-9a).

Usage:
    ./.venv/bin/python scripts/smoke_upload_limits.py

Pure: no server, no world DB, no LLM, no network. A throwaway storage root is
pinned before the first app import; every ZIP and every image is built in
memory. The two route calls in part [5] all return BEFORE the importer runs,
so nothing is ever written anywhere.

WHY

SEC-7: chat upload / user gallery / profile picture / rule import read the
whole request body into memory with ``await file.read()``, with no size cap
and no content check at all — the FILE NAME decided whether something was an
"image". One ordinary logged-in user could fill the disk, or park an arbitrary
file under a ``.png`` name.

SEC-9a: ``POST /api/content/install_upload?pack_type=skill_package`` installs
EXECUTABLE code and skipped the ``confirm_code`` confirmation that ``/install``
enforces for exactly the same pack type.

EXPECTED VALUES, all derived by hand — from the config schema, from the file
format specs, and from the two guard functions' contracts:

[1] ``max_upload_bytes()`` with no config loaded = the SCHEMA default,
    ``SECTIONS["server"]["fields"]["max_upload_mb"]["default"]`` = 25 MB
    = 25 * 1024 * 1024 = 26214400 bytes. ``config.get`` answers None for a
    plain scalar until the settings page has been saved once (migrate_file
    seeds no scalar defaults) — the same quirk ``server._cors_origins`` works
    around, so the schema default has to be the fallback here too.

[2] ``guard_content_length``: a declared length of limit+1 raises 413, a
    declared length of exactly ``limit`` passes (the cap is inclusive), a
    missing header passes (the chunked read enforces the same cap downstream),
    and an unparsable header passes for the same reason.

[3] ``read_upload_capped`` with max_bytes=1000:
      * 1000 bytes  -> returns all 1000 (boundary is inclusive)
      * 1001 bytes  -> HTTPException 413
    and the returned object is ``bytes``, not ``bytearray``.

[4] Magic bytes, taken from the format specs:
      PNG   89 50 4E 47 0D 0A 1A 0A          -> "png"
      JPEG  FF D8 FF                          -> "jpeg"
      GIF   "GIF89a" / "GIF87a"               -> "gif"
      WebP  "RIFF" + 4 size bytes + "WEBP"    -> "webp"
      ZIP   "PK\\x03\\x04"                      -> ""  (not an image)
    ``ensure_image`` therefore: a real PNG passes; the same PNG under the name
    "x.jpg" is 415 (the name lies); a ZIP under the name "x.png" is 415; and a
    PNG header declaring 20000 x 20000 = 400 megapixels is 413, because
    MAX_IMAGE_PIXELS is 64 megapixels. The 400 MP header also trips Pillow's
    own decompression-bomb limit (~178 MP), which ``ensure_image`` catches —
    either way the answer must not be "accepted".

[5] ``content_packs``:
    a) ``_archive_declared_type`` reads the type out of the ARCHIVE:
         manifest.json {"type": "item"}          -> "item"
         manifest.json {"character_name": "..."} -> "character"
         plugin.yaml at the ZIP root             -> "skill_package"
         plugin.yaml in one top folder           -> "skill_package"
         neither                                 -> ""
         not a ZIP at all                        -> ""  (never raises)
    b) ``install_pack_upload`` with pack_type="skill_package" and
       confirm_code NOT set -> HTTPException 428, and the message names the
       package that would be installed. Same shape as ``/install`` (which
       answers 428 with "resend with confirm_code=true"), so the upload path
       stops breaking the project's own rule "executable packages only with
       an explicit confirmation".
    c) the same skill-package ZIP uploaded as pack_type="item" -> 400: the
       archive declares skill_package, so the declared/actual mismatch is
       refused instead of being quietly dispatched.
    d) ALL THREE install entry points gate code packs. Read by AST, each of
       ``install_pack`` / ``install_pack_url`` / ``install_pack_upload`` names
       ``CODE_PACK_TYPES`` in its own body. ``/install`` always did;
       ``/install_url`` and ``/install_upload`` did not, and an ad-hoc URL is
       the least trustworthy of the three sources.
"""
import asyncio
import io
import os
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Throwaway storage root BEFORE any app import (scripts storage lint rule).
_TMP_STORAGE = tempfile.mkdtemp(prefix="smoke_upload_limits_")
os.environ.setdefault("ANIMATION_CLIPS_DIR", str(Path(_TMP_STORAGE) / "clips"))
from app.core import paths  # noqa: E402
paths.init(_TMP_STORAGE)

from fastapi import HTTPException  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402

from app.core import upload_limits as ul  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")
        print(f"FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"ok   {name}")


def status_of(fn, *a, **kw):
    """Run and report the HTTP status it raises, or "ok"/the error name."""
    try:
        fn(*a, **kw)
        return "ok"
    except HTTPException as e:
        return e.status_code
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def _upload(data: bytes, filename: str = "f.bin") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename,
                      headers=Headers({"content-type": "application/octet-stream"}))


class FakeRequest:
    def __init__(self, length):
        self.headers = Headers({} if length is None
                               else {"content-length": str(length)})


# ── [1] the configured cap ───────────────────────────────────────────────
check("[1] schema default is 25 MB",
      SECTIONS["server"]["fields"]["max_upload_mb"]["default"], 25)
check("[1] max_upload_bytes falls back to the schema default",
      ul.max_upload_bytes(), 25 * 1024 * 1024)


# ── [2] content-length guard ─────────────────────────────────────────────
LIMIT = ul.max_upload_bytes()
check("[2] content-length over the cap -> 413",
      status_of(ul.guard_content_length, FakeRequest(LIMIT + 1)), 413)
check("[2] content-length exactly at the cap -> ok",
      status_of(ul.guard_content_length, FakeRequest(LIMIT)), "ok")
check("[2] no content-length header -> ok",
      status_of(ul.guard_content_length, FakeRequest(None)), "ok")
check("[2] unparsable content-length -> ok",
      status_of(ul.guard_content_length, FakeRequest("many")), "ok")


# ── [3] chunked capped read ──────────────────────────────────────────────
def _read(data, cap):
    return asyncio.run(ul.read_upload_capped(_upload(data), max_bytes=cap))


exact = _read(b"x" * 1000, 1000)
check("[3] exactly the cap is returned whole", (type(exact), len(exact)),
      (bytes, 1000))
try:
    _read(b"x" * 1001, 1000)
    over = "ok"
except HTTPException as e:
    over = e.status_code
check("[3] one byte over the cap -> 413", over, 413)


# ── [4] magic bytes + image guard ────────────────────────────────────────
def _png(width: int, height: int) -> bytes:
    """A minimal, structurally valid PNG with the given header dimensions.

    Only the IHDR is meaningful here — ``ensure_image`` reads the header and
    never decodes pixel data, so a single empty IDAT is enough.
    """
    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" * (3 * width + 1)))
            + chunk(b"IEND", b""))


GIF = b"GIF89a" + b"\x01\x00\x01\x00\x80\x00\x00"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 10
WEBP = b"RIFF" + struct.pack("<I", 20) + b"WEBP" + b"VP8 " + b"\x00" * 8
ZIP = b"PK\x03\x04" + b"\x00" * 20

check("[4] PNG magic", ul.sniff_image_format(_png(1, 1)), "png")
check("[4] JPEG magic", ul.sniff_image_format(JPEG), "jpeg")
check("[4] GIF magic", ul.sniff_image_format(GIF), "gif")
check("[4] WebP magic", ul.sniff_image_format(WEBP), "webp")
check("[4] ZIP is no image", ul.sniff_image_format(ZIP), "")
check("[4] empty body is no image", ul.sniff_image_format(b""), "")

check("[4] a real PNG passes",
      status_of(ul.ensure_image, _png(4, 4), filename="x.png"), "ok")
check("[4] a PNG named .jpg -> 415",
      status_of(ul.ensure_image, _png(4, 4), filename="x.jpg"), 415)
check("[4] a ZIP named .png -> 415",
      status_of(ul.ensure_image, ZIP, filename="x.png"), 415)
check("[4] 20000x20000 (400 MP) -> refused",
      status_of(ul.ensure_image, _png(20000, 20000), filename="x.png") != "ok",
      True)
check("[4] the pixel ceiling is 64 MP", ul.MAX_IMAGE_PIXELS, 64_000_000)


# ── [5] the skill-package trust gate ─────────────────────────────────────
from app.routes import content_packs as cp  # noqa: E402


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


SKILL_ZIP = _zip({"plugin.yaml": "name: smoke_pkg\nskills:\n  - skill_id: do_thing\n"})
SKILL_ZIP_FOLDER = _zip({"smoke_pkg/plugin.yaml": "name: smoke_pkg\n",
                         "smoke_pkg/skill.py": "pass\n"})

check("[5a] manifest type wins",
      cp._archive_declared_type(_zip({"manifest.json": '{"type": "item"}'})), "item")
check("[5a] a character export declares character",
      cp._archive_declared_type(_zip({"manifest.json": '{"character_name": "Demo"}'})),
      "character")
check("[5a] plugin.yaml at the root -> skill_package",
      cp._archive_declared_type(SKILL_ZIP), "skill_package")
check("[5a] plugin.yaml in one folder -> skill_package",
      cp._archive_declared_type(SKILL_ZIP_FOLDER), "skill_package")
check("[5a] neither -> undecidable",
      cp._archive_declared_type(_zip({"readme.txt": "hi"})), "")
check("[5a] not a ZIP -> undecidable, never raises",
      cp._archive_declared_type(b"not a zip at all"), "")


def _install(data, pack_type, confirm, filename="pack.zip"):
    return asyncio.run(cp.install_pack_upload(
        file=_upload(data, filename), pack_type=pack_type, overwrite=False,
        mode="full", intro="", confirm_code=confirm))


try:
    _install(SKILL_ZIP, "skill_package", False)
    code, detail = "ok", ""
except HTTPException as e:
    code, detail = e.status_code, str(e.detail)
check("[5b] skill_package upload without confirmation -> 428", code, 428)
check("[5b] the 428 names what would be installed",
      ("smoke_pkg" in detail and "do_thing" in detail
       and "confirm_code=true" in detail), True)

try:
    _install(SKILL_ZIP, "item", False)
    code2 = "ok"
except HTTPException as e:
    code2 = e.status_code
check("[5c] a skill package uploaded as 'item' -> 400", code2, 400)

import ast  # noqa: E402

tree = ast.parse((ROOT / "app/routes/content_packs.py").read_text(encoding="utf-8"))
gated = sorted(
    fn.name for fn in ast.walk(tree)
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
    and fn.name in {"install_pack", "install_pack_url", "install_pack_upload"}
    and any(isinstance(n, ast.Name) and n.id == "CODE_PACK_TYPES"
            for n in ast.walk(fn)))
check("[5d] every install entry point gates code packs", gated,
      ["install_pack", "install_pack_upload", "install_pack_url"])

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ALL CHECKS PASSED")
