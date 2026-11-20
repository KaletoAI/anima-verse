"""Contact sheets of the template dialog's drawing: one PNG per kind and parameter, every option side by side.

Usage: ./.venv/bin/python scripts/garment_preview_sheets.py <plain base GLB> <out dir> [--front <front PNG>]
                                                           [--only <kind>[,<kind>]]

  <plain base GLB>  a COPY of a character's plain base body (``characters/<c>/model3d/base<sig>.glb``) — never a
                    live world file in place
  <out dir>         the sheets land here as ``<kind>_<param>.png``
  --front           the base body's front picture (``model_refs/tpose_base<sig>.png``, also a copy): registered by
                    its silhouette as the dialog does without a dressed render; without it the body's own front is
                    projected from the GLB (exact mapping)

No server, no world: ``garment_preview.body_measure`` reads the GLB, ``garment_preview_sheet`` draws.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="gp-sheets-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
from pathlib import Path  # noqa: E402

from app.core import garment_preview as gp  # noqa: E402
from app.core import garment_preview_sheet as gs  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    glb, out = Path(argv[0]), Path(argv[1])
    front = Path(argv[argv.index("--front") + 1]) if "--front" in argv else None
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    out.mkdir(parents=True, exist_ok=True)
    meas = gp.body_measure(glb)
    if front is not None:
        from PIL import Image
        base = Image.open(front).convert("RGBA")
        frame = gp.picture_frame(front)
    else:
        base, frame = gs.model_front(glb.read_bytes())
    reg = gp.register(frame, meas)
    n = 0
    for opt in gs.option_sets():
        if only and opt["kind"] not in only:
            continue
        tiles, drawns = [], []
        for v in opt["values"]:
            p = gs.params_for(opt["kind"], opt["param"], v, opt["context"])
            if p is None:
                continue
            drawns.append((v, gp.shapes(p, meas, reg)))
        if len(drawns) < 2:
            continue
        box = gs.crop_box([d for _v, d in drawns], *base.size)
        for v, d in drawns:
            tiles.append((f"{opt['param']} = {v}", gs.render(base, d).crop(box)))
        ctx = ", ".join(f"{k}={v}" for k, v in opt["context"].items())
        title = f"{opt['kind']} · {opt['label']}" + (f"   ({ctx})" if ctx else "")
        name = f"{opt['kind']}_{opt['label'].replace(' ', '_').replace('(', '').replace(')', '')}.png"
        gs.sheet(tiles, title).save(out / name)
        n += 1
    print(f"{n} sheets in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
