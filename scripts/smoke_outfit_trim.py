#!/usr/bin/env python3
"""Check horizontal outfit trimming without rembg or world data.

Usage: ./.venv/bin/python scripts/smoke_outfit_trim.py

Expected bounds, derived by hand (right bounds are exclusive):
* On a 600x100 canvas, the opaque block [430, 590) is 590 - 430 = 160
  pixels wide. Alpha-2 specks at x=5 and x=20 must not affect that box.
* Alpha 200 on x=100..199 gives [100, 200), width 200 - 100 = 100.
* Alpha 8 at x=99 is excluded; opaque x=100..199 still gives width 100.
* Alpha 16 at x=98 is excluded and alpha 17 at x=99 is included, so with
  opaque x=100..199 the width is 200 - 99 = 101 (strict alpha > 16).
All crops retain all 100 rows, including the transparent top and bottom.
Empty, below-threshold-only, and RGB images have no crop and stay unchanged.
"""
from pathlib import Path
import sys
import tempfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix="smoke_outfit_trim_") as tmp:
        paths.init(tmp)
        from app.models.character import trim_transparent_sides

        for label, left, alpha, fringe, expected_left, expected_width in [
            ("stray specks", 430, 255, [(5, 2), (20, 2)], 430, 160),
            ("translucent content", 100, 200, [], 100, 100),
            ("soft edge", 100, 255, [(99, 8)], 100, 100),
            ("strict threshold", 100, 255, [(98, 16), (99, 17)], 99, 101),
        ]:
            img = Image.new("RGBA", (600, 100))
            right = 590 if left == 430 else 200
            img.paste((40, 80, 120, alpha), (left, 20, right, 80))
            for x, fringe_alpha in fringe:
                img.putpixel((x, 50), (10, 20, 30, fringe_alpha))
            result = trim_transparent_sides(img)
            assert result.size == (expected_width, 100), (label, result.size)
            expected = img.crop((expected_left, 0, right, 100))
            assert result.tobytes() == expected.tobytes(), label
            print(f"PASS: {label}: {result.width}x{result.height}")

        for label, img in [
            ("empty", Image.new("RGBA", (600, 100))),
            ("below threshold only", Image.new("RGBA", (600, 100), (0, 0, 0, 16))),
            ("RGB", Image.new("RGB", (600, 100))),
        ]:
            assert trim_transparent_sides(img) is img, label
            print(f"PASS: {label}: unchanged")


if __name__ == "__main__":
    main()
