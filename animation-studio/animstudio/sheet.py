"""Contact sheet: rows = views (front, the figure's left), columns = frames."""
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import animstudio
from animstudio import StudioError


def sheet(kind: str, columns: int = 6) -> Path:
    from app.blender import runner
    out = animstudio.OUT / kind
    fbx = out / f"{kind}.fbx"
    if not fbx.is_file():
        raise StudioError(f"{fbx} missing - build first")
    meta = json.loads((out / f"{kind}.json").read_text(encoding="utf-8"))
    n = int(meta["frames"])
    cols = max(2, min(columns, n))
    frames = [1 + round(i * (n - 1) / (cols - 1)) for i in range(cols)]
    views = ["front", "side"]
    w, h = 300, 380
    with tempfile.TemporaryDirectory(prefix="animstudio-sheet-") as tmp_dir:
        tmp = Path(tmp_dir)
        res = None
        for engine in ("BLENDER_WORKBENCH", "CYCLES"):
            res = runner.run("clip_sheet", inputs={"clip": fbx},
                             params={"frames": frames, "views": views, "size": [w, h],
                                     "engine": engine}, out_dir=tmp, timeout_s=1200)
            if res["ok"]:
                break
        if not res or not res["ok"]:
            raise StudioError(f"clip_sheet failed: {res['error'] if res else '?'}")
        grid = Image.new("RGB", (w * cols, h * len(views) + 24), "white")
        draw = ImageDraw.Draw(grid)
        for r, view in enumerate(views):
            for c in range(cols):
                with Image.open(res["outputs"][f"{view}_{c}"]) as img:
                    grid.paste(img.convert("RGB"), (c * w, 24 + r * h))
    for c, f in enumerate(frames):
        draw.text((c * w + 6, 6), f"t={(f - 1) / int(meta['fps']):.2f}s", fill="black")
    dst = out / "sheet.png"
    grid.save(dst)
    return dst
