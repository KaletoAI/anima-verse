#!/usr/bin/env python3
"""Check portrait cutout storage, not segmentation model quality.

Usage: ./.venv/bin/python scripts/smoke_portrait_transparency.py

The inference boundary returns a deterministic 12x16 RGBA silhouette whose
hair extends to y=14 below the neck. Processing must retain the full canvas,
all alpha values and those lower hair tips; the original remains byte-identical.
Concurrent readers must see one complete cached PNG. Replacing an original
must invalidate the cutout even with identical size and mtime. Empty or fully
opaque segmentation must fail, never masquerade as a transparent portrait.
All storage is temporary; no model download or real world is touched.
"""
import io
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def png(image):
    out = io.BytesIO()
    image.save(out, format="PNG", compress_level=0)
    return out.getvalue()


with tempfile.TemporaryDirectory(prefix="portrait-alpha-") as tmp:
    from app.core import paths
    paths.init(tmp)
    paths.init_instance(Path(tmp) / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
    from app.models.character import get_character_images_dir
    from app.core.portrait_images import transparent_portrait_path

    root = get_character_images_dir("demo")
    root.mkdir(parents=True, exist_ok=True)
    source = root / "portrait.png"
    original = png(Image.new("RGB", (12, 16), "white"))
    source.write_bytes(original)
    cutout = Image.new("RGBA", (12, 16), (0, 0, 0, 0))
    for x in range(3, 9):
        for y in range(2, 15):
            cutout.putpixel((x, y), (80, 50, 20, 255))
    cutout.putpixel((2, 14), (80, 50, 20, 96))
    output = png(cutout)
    # Only neural inference is mocked; real file/caching/validation code runs.
    with patch("app.models.character._get_rembg_session", return_value=object()), \
            patch("rembg.remove", return_value=output) as remove:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: transparent_portrait_path("demo", source.name), range(6)))
        assert remove.call_count == 1, "concurrent requests repeated neural inference"
        target = results[0]
        assert all(p == target for p in results)
        with Image.open(target) as result:
            assert result.size == (12, 16), "portrait canvas was cropped"
            assert result.convert("RGBA").tobytes() == cutout.tobytes(), "hair or alpha changed"
        assert source.read_bytes() == original, "original identity reference was modified"
        assert target.parent != root, "cutout leaked into original gallery"
        before = source.stat()
        replacement = png(Image.new("RGB", (12, 16), "black"))
        source.write_bytes(replacement)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert source.stat().st_size == before.st_size
        updated = transparent_portrait_path("demo", source.name)
        assert updated != target and remove.call_count == 2, "replaced original kept stale cutout"
        assert source.read_bytes() == replacement

    outside = Path(tmp) / "outside.png"
    outside.write_bytes(original)
    (root / "escape.png").symlink_to(outside)
    for name in ("../outside.png", "escape.png", "folder/portrait.png", "folder\\portrait.png"):
        try:
            transparent_portrait_path("demo", name)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe image accepted: {name}")

    for color in ((17, 17, 17, 0), (31, 31, 31, 255)):
        source.write_bytes(png(Image.new("RGB", (12, 16), color[:3])))
        with patch("app.models.character._get_rembg_session", return_value=object()), \
                patch("rembg.remove", return_value=png(Image.new("RGBA", (12, 16), color))):
            try:
                transparent_portrait_path("demo", source.name)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid alpha output was published")

    # JPEG orientation changes the displayed canvas, not the portrait crop.
    exif = Image.Exif()
    exif[274] = 6
    jpeg = io.BytesIO()
    Image.new("RGB", (12, 16), "white").save(jpeg, format="JPEG", exif=exif)
    rotated_source = root / "rotated.jpg"
    rotated_source.write_bytes(jpeg.getvalue())
    rotated = cutout.transpose(Image.Transpose.ROTATE_270)
    with patch("app.models.character._get_rembg_session", return_value=object()), \
            patch("rembg.remove", return_value=png(rotated)):
        result_path = transparent_portrait_path("demo", rotated_source.name)
        with Image.open(result_path) as result:
            assert result.size == (16, 12), "EXIF portrait orientation was lost"
            assert result.convert("RGBA").tobytes() == rotated.tobytes()
        assert rotated_source.read_bytes() == jpeg.getvalue()

    already_alpha = root / "already-transparent.png"
    already_alpha.write_bytes(output)
    with patch("rembg.remove", side_effect=AssertionError("existing cutout segmented again")):
        result_path = transparent_portrait_path("demo", already_alpha.name)
        with Image.open(result_path) as result:
            assert result.convert("RGBA").tobytes() == cutout.tobytes()

print("OK: original preserved, full hair/canvas/alpha retained, single-flight cache, source replacement, containment and invalid alpha")
