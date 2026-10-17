#!/usr/bin/env python3
"""Write deterministic 512-square facade placeholders into the shared library.

Usage: ./.venv/bin/python scripts/make_hull_placeholder_textures.py
Existing kind metadata is retained; no active selections are written.
"""
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "shared" / "surface_textures"
KINDS = {
    "plaster_infill": ("lime plaster infill", "whitewashed lime plaster wall, slightly uneven, seen straight on", 2.0),
    "timber_beam": ("oak timber", "weathered dark oak timber grain, seen straight on", 1.0),
    "clay_roof_tiles": ("clay roof tiles", "rows of overlapping red clay roof tiles, seen straight on", 2.0),
    "fieldstone": ("fieldstone masonry", "irregular grey fieldstone masonry with mortar joints, seen straight on", 2.5),
    "ashlar": ("ashlar blocks", "dressed sandstone ashlar blocks in regular courses, seen straight on", 2.5),
    "slate_roof": ("slate roof", "rows of dark grey slate roof shingles, seen straight on", 2.0),
    "log_wood": ("log wood", "horizontal round pine logs with bark patches, seen straight on", 2.0),
    "wood_shingles": ("wood shingles", "rows of weathered wooden roof shingles, seen straight on", 2.0),
    "castle_stone": ("castle stone", "large weathered grey castle stone blocks, seen straight on", 4.0),
    "door_planks": ("door planks", "vertical dark wooden door planks with iron studs, seen straight on", 1.5),
    "brick": ("brick", "red brick masonry in running bond, seen straight on", 1.5),
}
COLORS = {
    "plaster_infill": (224, 219, 202), "timber_beam": (78, 53, 34),
    "clay_roof_tiles": (161, 73, 45), "fieldstone": (126, 128, 119),
    "ashlar": (177, 159, 122), "slate_roof": (64, 72, 79),
    "log_wood": (130, 93, 53), "wood_shingles": (115, 99, 75),
    "castle_stone": (126, 125, 116), "door_planks": (72, 49, 32),
    "brick": (156, 73, 52),
}


def make_texture(kind: str) -> Image.Image:
    """Draw mortar grids, timber bands or plaster noise with a per-kind seed."""
    rng = random.Random(kind)
    base = COLORS[kind]
    image = Image.new("RGB", (512, 512), (64, 61, 55))
    draw = ImageDraw.Draw(image)

    def color():
        shift = rng.randint(-14, 14)
        return tuple(max(0, min(255, c + shift)) for c in base)

    if kind == "plaster_infill":
        # Small low-contrast patches compress well and suggest uneven plaster.
        for y in range(0, 512, 4):
            for x in range(0, 512, 4):
                draw.rectangle((x, y, x + 3, y + 3), fill=color())
    elif kind in {"timber_beam", "door_planks", "log_wood"}:
        vertical = kind != "log_wood"
        for start in range(0, 512, 64):
            box = (start + 2, 0, start + 62, 511) if vertical else (0, start + 2, 511, start + 62)
            draw.rectangle(box, fill=color())
            for _ in range(24):
                offset = start + rng.randint(4, 60)
                line = (offset, 0, offset, 511) if vertical else (0, offset, 511, offset)
                draw.line(line, fill=color())
            if kind == "door_planks":
                for y in (48, 464):
                    draw.ellipse((start + 28, y - 3, start + 34, y + 3), fill=(35, 35, 34))
    else:
        width, height = (64, 32) if kind == "brick" else (128, 64)
        if kind == "castle_stone":
            width, height = 256, 128
        for row, y in enumerate(range(0, 512, height)):
            offset = (row % 2) * (width // 2)
            for x in range(-width + offset, 512, width):
                draw.rectangle((x + 2, y + 2, x + width - 2, y + height - 2), fill=color())
                if kind == "fieldstone":
                    draw.line((x + 4, y + 6, x + width - 6, y + rng.randint(8, 20)), fill=color(), width=3)
    return image


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    meta_path = ROOT / "kinds.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    for kind, (name, description, size_m) in KINDS.items():
        path = ROOT / f"{kind}_1792300000.png"
        make_texture(kind).save(path, format="PNG")
        path.with_suffix(".json").write_text(json.dumps({
            "created_at": "2026-10-18T00:00:00+00:00",
            "source": "placeholder", "size_m": size_m,
        }, indent=2) + "\n", encoding="utf-8")
        metadata.setdefault(kind, {"name": name, "description": description})
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(KINDS)} facade placeholders")


if __name__ == "__main__":
    main()
