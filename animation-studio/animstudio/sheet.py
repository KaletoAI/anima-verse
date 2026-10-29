"""Contact sheet: rows = views, columns = frames. Solo: front and the
figure's left. Pair: both halves in one scene, seen from the front (the
pair in profile, A left), front-left at 45° and from above."""
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import animstudio
from animstudio import StudioError


def sheet(kind: str, columns: int = 6) -> Path:
    from app.blender import runner
    out = animstudio.OUT / kind
    meta_path = out / f"{kind}.json"
    if not meta_path.is_file():
        raise StudioError(f"{meta_path} missing - build first")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pair = bool(meta.get("pair"))
    inputs = ({"clip": out / f"{kind}__a.fbx", "clip_b": out / f"{kind}__b.fbx"} if pair
              else {"clip": out / f"{kind}.fbx"})
    for p in inputs.values():
        if not p.is_file():
            raise StudioError(f"{p} missing - build first")
    n = int(meta["frames"])
    cols = max(2, min(columns, n))
    frames = [1 + round(i * (n - 1) / (cols - 1)) for i in range(cols)]
    views = ["front", "diag", "top"] if pair else ["front", "side"]
    w, h = 300, 380
    motion = meta.get("geometry", {}).get("root_motion", {})
    travel = motion.get("travel_m") if motion.get("mode") == "keep" else None
    header = 110 if travel is not None else 24
    with tempfile.TemporaryDirectory(prefix="animstudio-sheet-") as tmp_dir:
        tmp = Path(tmp_dir)
        res = None
        for engine in ("BLENDER_WORKBENCH", "CYCLES"):
            res = runner.run("clip_sheet", inputs=inputs,
                             params={"frames": frames, "views": views, "size": [w, h],
                                     "engine": engine}, out_dir=tmp, timeout_s=1200)
            if res["ok"]:
                break
        if not res or not res["ok"]:
            raise StudioError(f"clip_sheet failed: {res['error'] if res else '?'}")
        grid = Image.new("RGB", (w * cols, h * len(views) + header), "white")
        draw = ImageDraw.Draw(grid)
        for r, view in enumerate(views):
            for c in range(cols):
                with Image.open(res["outputs"][f"{view}_{c}"]) as img:
                    grid.paste(img.convert("RGB"), (c * w, header + r * h))
    for c, f in enumerate(frames):
        draw.text((c * w + 6, 6), f"t={(f - 1) / int(meta['fps']):.2f}s", fill="black")
    if travel is not None:
        # Top-down clip frame: +X is the figure's left, +Z points up here.
        import math
        dx, dz = travel
        length = math.hypot(dx, dz)
        ox, oy = 170, 67
        draw.text((6, 26), f"Root travel X={dx:+.3f} m, Z={dz:+.3f} m (+Z forward, +X left)", fill="black")
        if length:
            ux, uy = -dx / length, -dz / length
            ex, ey = ox + 32 * ux, oy + 32 * uy
            draw.line((ox, oy, ex, ey), fill="black", width=3)
            draw.polygon([(ex, ey), (ex - 9*ux + 5*uy, ey - 9*uy - 5*ux),
                          (ex - 9*ux - 5*uy, ey - 9*uy + 5*ux)], fill="black")
        draw.text((ox + 45, oy - 5), "start -> end (top view)", fill="black")
    dst = out / "sheet.png"
    grid.save(dst)
    return dst
