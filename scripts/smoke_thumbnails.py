#!/usr/bin/env python3
"""Smoke: the thumbnail path for gallery tiles (UI-8).

Usage:
    ./.venv/bin/python scripts/smoke_thumbnails.py

Throwaway storage (``tempfile`` + ``paths.init`` BEFORE any app import), no
server, no world DB, no LLM, no image backend. The source images are written
here with PIL.

WHY (UI-8 of the 2026-09-20 review)
-----------------------------------
A player gallery tile is ~72-100 CSS px and used to load the ORIGINAL render —
a 1024x1536 PNG of 1-4 MB, decoded at full size (1024*1536*4 B = 6 MB of RGBA)
no matter how small it is drawn. There was no downscaling path in the backend
at all. ``app/core/thumbnails.py`` + ``app/routes/thumbnails.py`` are that
path; this check pins its contract.

EXPECTED VALUES, all derived by hand from the contract in
``app/core/thumbnails.py`` — never recorded from a run:

 1. SIZE. A 1024x1536 source at ``w=192`` gives 192 x round(1536*192/1024)
    = 192 x 288 pixels, format WEBP. (The aspect ratio is kept, the width is
    the bucket exactly.)
 2. CACHE. The second call for the same (source, width) must not render
    again. Checked by replacing ``thumbnails._render`` with a function that
    raises: a second call that still returns the file proves the hit.
 3. FRESHNESS. The cache key is source path + mtime + size + width. Rewriting
    the source with DIFFERENT content must therefore yield a different cache
    file — and the stale one must be gone (``_prune_older``).
 4. WIDTH BUCKETS. ``THUMB_WIDTHS`` is (96, 192, 384). Every other value —
    100, 0, -1, "", "abc", 1e9 — is a 400, so the cache cannot be flooded
    with arbitrary variants.
 5. TRAVERSAL. ``"../x.png"``, ``"a/b.png"``, ``"a\\b.png"`` are rejected with
    400, exactly as ``routes/characters.get_character_image`` and
    ``routes/world.get_gallery_image`` reject them ("Ungueltiger Dateiname" /
    "Invalid filename", both 400).
 6. NON-IMAGE. A file named ``.png`` whose bytes are text is a 415 (magic
    bytes decide, as in ``upload_limits.sniff_image_format``), not a 500.
 7. NO UPSCALE. A 64x64 source at ``w=384`` comes back 64x64 — a blown-up
    thumbnail would be larger than the original AND worse.
 8. ALPHA SURVIVES. An RGBA source keeps its alpha channel (WebP carries it),
    so a cut-out does not get a black box behind it.
 9. MISSING SOURCE. A file that is not there is a 404 (not a traceback).
10. CACHE LOCATION. The thumbnail lies under ``<storage>/.cache/thumbs`` and
    NOT in the gallery directory — galleries are listed by directory scan, so
    a thumbnail dropped beside the images would show up as an image.
11. PROFILE SHORTCUT. ``/thumbs/characters/{n}/images/profile`` must mean
    the profile PICTURE, not a file called "profile" — the route is declared
    before the generic one, exactly as ``routes/characters.py`` declares the
    full-size pair. Every small portrait in the UI points at it.
12. URL SHAPE vs AUTH. ``/thumbs/characters/{n}/images/{f}`` must classify in
    ``auth_dependency`` exactly like the full-size ``/characters/{n}/images/
    {f}``: non-sensitive (``images`` is in ``_PUBLIC_CHARACTER_SEGMENTS``),
    not public (a session is required) and not admin-only.

The check also PRINTS the before/after byte size of the 1024x1536 PNG.

Exits non-zero on the first failing expectation.
"""
import io
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="thumbs-smoke-"))

from app.core import paths  # noqa: E402
paths.init(STORAGE)

from fastapi import HTTPException  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import thumbnails  # noqa: E402
from app.routes import thumbnails as thumb_routes  # noqa: E402

FAILURES = []


def check(label: str, got, want):
    ok = got == want
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(label)


def check_status(label: str, fn, want: int):
    """``fn`` must raise an HTTPException with status ``want``."""
    try:
        fn()
    except HTTPException as exc:
        check(label, exc.status_code, want)
        return
    except Exception as exc:  # noqa: BLE001 - a non-HTTP error is a failure
        print(f"  [FAIL] {label}: raised {type(exc).__name__}: {exc}")
        FAILURES.append(label)
        return
    print(f"  [FAIL] {label}: no exception raised (expected {want})")
    FAILURES.append(label)


class FakeRequest:
    """Only what ``etag_file_response`` touches."""

    def __init__(self, if_none_match: str = ""):
        self.headers = {"if-none-match": if_none_match} if if_none_match else {}


def write_png(path: Path, size, seed: int = 0, mode="RGB") -> int:
    """A noisy PNG of ``size``, written to ``path``; returns its byte size.

    The pixels are random bytes on purpose: a flat or smooth test image
    compresses to a few kB and would make the before/after print meaningless,
    while noise puts a 1024x1536 PNG in the same 1-4 MB band as a real render
    (it is the incompressible worst case, so the printed source size is an
    upper bound rather than an average).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    bands = 4 if mode == "RGBA" else 3
    raw = bytearray(os.urandom(size[0] * size[1] * bands))
    if mode == "RGBA":
        # A deterministic alpha ramp instead of random alpha — a cut-out has
        # structure, and a fully random alpha channel says nothing.
        for i in range(3, len(raw), 4):
            raw[i] = (i // 4 + seed) % 256
    im = Image.frombytes(mode, size, bytes(raw))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    path.write_bytes(buf.getvalue())
    return len(buf.getvalue())


def thumb_size(path: Path):
    with Image.open(path) as im:
        return im.size, im.format


def main() -> int:
    char = "Demo"
    images_dir = STORAGE / "characters" / char / "images"
    src = images_dir / "shot.png"
    before = write_png(src, (1024, 1536))

    req = FakeRequest()

    print("1) a first request renders the bucket width, keeping the aspect ratio")
    thumb_routes.thumb_character_image(char, "shot.png", req, w="192")
    thumb = thumbnails.get_thumbnail(src, 192)
    size, fmt = thumb_size(thumb)
    check("thumbnail pixel size (1024x1536 @ w=192)", size, (192, 288))
    check("thumbnail format", fmt, "WEBP")
    after = thumb.stat().st_size
    print(f"     source 1024x1536 PNG: {before:,} bytes "
          f"-> thumbnail 192x288 WebP: {after:,} bytes "
          f"({before / max(after, 1):.0f}x smaller)")
    check("thumbnail is smaller than the source", after < before, True)

    print("10) the thumbnail lies under <storage>/.cache/thumbs, not in the gallery")
    check("cache dir", thumb.parent, STORAGE / ".cache" / "thumbs")
    check("gallery dir holds only the source",
          sorted(p.name for p in images_dir.iterdir()), ["shot.png"])

    print("2) the second request is served from the cache (no second render)")
    real_render = thumbnails._render

    def boom(*_a, **_kw):
        raise AssertionError("_render called again for a cached thumbnail")

    thumbnails._render = boom
    try:
        again = thumbnails.get_thumbnail(src, 192)
        check("same cache file returned", again, thumb)
        check("cache hit did not render", True, True)
    except AssertionError as exc:
        print(f"  [FAIL] cache hit: {exc}")
        FAILURES.append("cache hit")
    finally:
        thumbnails._render = real_render

    print("3) changing the source yields a NEW thumbnail and drops the stale one")
    old_name = thumb.name
    time.sleep(0.01)
    write_png(src, (1024, 1536), seed=7)
    os.utime(src, (time.time() + 2, time.time() + 2))
    fresh = thumbnails.get_thumbnail(src, 192)
    check("cache file name changed", fresh.name != old_name, True)
    check("stale thumbnail removed", (thumb.parent / old_name).exists(), False)

    print("4) only the fixed width buckets are accepted")
    check("THUMB_WIDTHS", thumbnails.THUMB_WIDTHS, (96, 192, 384))
    for bad in ("100", "0", "-1", "", "abc", "1000000000", "192.0"):
        check_status(f"w={bad!r} rejected",
                     lambda b=bad: thumb_routes.thumb_character_image(
                         char, "shot.png", req, w=b), 400)
    for good in (96, 192, 384):
        out = thumbnails.get_thumbnail(src, good)
        check(f"w={good} width", thumb_size(out)[0][0], good)

    print("5) traversal-shaped names are rejected exactly like the full-size route")
    for bad in ("../shot.png", "a/b.png", "a\\b.png", "../../etc/passwd"):
        check_status(f"filename {bad!r} rejected",
                     lambda b=bad: thumb_routes.thumb_character_image(
                         char, b, req, w="192"), 400)
    check_status("location gallery filename '../x.png' rejected",
                 lambda: thumb_routes.thumb_location_gallery_image(
                     "somewhere", "../x.png", req, w="192"), 400)
    check_status("invalid character name rejected",
                 lambda: thumb_routes.thumb_character_image(
                     "undefined", "shot.png", req, w="192"), 400)

    print("6) a non-image file is a 415")
    fake = images_dir / "notanimage.png"
    fake.write_bytes(b"<html>definitely not a picture</html>")
    check_status("text file named .png rejected",
                 lambda: thumb_routes.thumb_character_image(
                     char, "notanimage.png", req, w="192"), 415)

    print("7) a small source is never upscaled")
    small = images_dir / "tiny.png"
    write_png(small, (64, 64))
    out = thumbnails.get_thumbnail(small, 384)
    check("64x64 @ w=384 stays 64x64", thumb_size(out)[0], (64, 64))

    print("8) alpha survives the conversion")
    cut = images_dir / "cutout.png"
    write_png(cut, (300, 200), mode="RGBA")
    out = thumbnails.get_thumbnail(cut, 96)
    with Image.open(out) as im:
        check("alpha kept", im.mode in ("RGBA", "LA"), True)
        check("cutout width", im.size[0], 96)

    print("9) a missing source is a 404")
    check_status("missing file",
                 lambda: thumb_routes.thumb_character_image(
                     char, "gone.png", req, w="192"), 404)

    print("11) /images/profile resolves to the profile picture, not a file")
    from app.core import db
    db.init_schema()
    from app.models.character import save_character_profile
    save_character_profile(char, {"name": char, "profile_image": "shot.png"},
                           create_new=True)
    thumb_routes.thumb_character_profile_image(char, req, w="96")
    from app.models.character import get_character_profile_image
    prof_src = images_dir / get_character_profile_image(char)
    check("profile thumb points at the profile image", prof_src.name, "shot.png")
    check("profile thumb width", thumb_size(thumbnails.get_thumbnail(prof_src, 96))[0][0], 96)
    save_character_profile(char, {"name": char, "profile_image": ""})
    check_status("no profile image is a 404",
                 lambda: thumb_routes.thumb_character_profile_image(
                     char, req, w="96"), 404)

    print("12) the thumbnail URL classifies like the full-size URL")
    from app.core import auth_dependency as auth
    full = f"/characters/{char}/images/shot.png"
    thumbed = f"/thumbs{full}"
    check("full-size path is not sensitive",
          auth._is_sensitive_character_path(full), False)
    check("thumbnail path is not sensitive",
          auth._is_sensitive_character_path(thumbed), False)
    check("thumbnail path needs a session",
          auth.is_public_path(thumbed), False)
    check("full-size path needs a session",
          auth.is_public_path(full), False)
    check("thumbnail path is not admin-only",
          auth.is_admin_only_path(thumbed, "GET"), False)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("PASS: thumbnail path behaves as specified")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
