"""Smoke: which background matte postprocess_outfit_image picks.

Expected (decision 2026-11-08, measured on T-pose fronts/backs and portraits):
  A mesh input (T-pose and its views, mesh_input=True) is matted with BiRefNet-DIS,
    because the portrait model leaves background between spread fingers.
  An expression image (portrait_matte=True) keeps BiRefNet portrait, because DIS
    leaves loose hair strands with bright rims.
  A render flagged as both counts as a mesh input.
  A plain outfit image (neither flag) keeps the default u2net cutout.
  The mesh-input mask is put on the ORIGINAL colours: an opaque pixel keeps its RGB.

No server, no world DB, no model download: run_rembg is replaced by a recorder.

Usage: ./.venv/bin/python scripts/smoke_mesh_input_matte.py
"""
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_matte_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from PIL import Image  # noqa: E402

from app.core import paths  # noqa: E402
paths.init(TMP / "world")
from app.models import character as ch  # noqa: E402

failures = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


SRC_RGB = (200, 120, 40)


def white_mask_png(size):
    b = io.BytesIO()
    Image.new("L", size, 255).save(b, "PNG")
    return b.getvalue()


def run(**flags):
    src = TMP / f"in_{len(calls)}.png"
    Image.new("RGB", (8, 8), SRC_RGB).save(src)
    calls.append(None)

    def fake(data, model="u2net", **kw):
        calls[-1] = (model, kw.get("only_mask", False))
        if kw.get("only_mask"):
            return white_mask_png((8, 8))
        b = io.BytesIO()
        Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(b, "PNG")
        return b.getvalue()

    with patch.object(ch, "run_rembg", fake):
        out = ch.postprocess_outfit_image(src, **flags)
    return calls[-1], out


calls = []
(model, only_mask), out = run(mesh_input=True)
check(model == "birefnet-dis" and only_mask, f"mesh input -> birefnet-dis mask (got {model}, only_mask={only_mask})")
check(Image.open(out).convert("RGBA").getpixel((4, 4)) == SRC_RGB + (255,),
      "mesh input keeps the original colours under the mask")
(model, only_mask), _ = run(portrait_matte=True)
check(model == "birefnet-portrait" and only_mask, f"expression image -> birefnet-portrait mask (got {model})")
(model, _), _ = run(mesh_input=True, portrait_matte=True)
check(model == "birefnet-dis", f"both flags -> mesh input wins (got {model})")
(model, only_mask), _ = run()
check(model == "u2net" and not only_mask, f"plain outfit image -> default u2net cutout (got {model})")

print("FAILED" if failures else "ALL OK")
sys.exit(1 if failures else 0)
