"""Smoke: the template dialog's overlay answers ``{ok: False, reason}`` — not a 500 — for a plain body whose arm /
neck joints cannot be read (A198, review 06C #4).

Usage:
    ./.venv/bin/python scripts/smoke_preview_no_upper_joints.py

No server, no world DB: the base-model / picture lookups of ``garment_preview.overlay`` are stubbed onto a temp
folder. ``garment_template.measure_body`` returns the upper block (``shoulder_y``, ``neck_y``, ...) only with
leftarm/rightarm/lefthand/righthand/neck present, so a body without them measures without ``shoulder_y`` /
``neck_y``. By hand: overlay -> ok False, reason NO_UPPER_JOINTS, picture still named. Pre-fix (e846d7d02): KeyError
('shoulder_y' / 'neck_y') out of ``register`` / ``landmarks`` -> HTTP 500 (the route catches only ValueError).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import base_body, garment_preview as gp, garment_preview_front  # noqa: E402
import app.models.character as character  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


with tempfile.TemporaryDirectory(prefix="a198-preview-") as tmp:
    root = Path(tmp)
    (root / "model3d").mkdir()
    (root / "model3d" / "bsig.glb").write_bytes(b"glb")
    (root / "front.png").write_bytes(b"png")
    base_body.current_base = lambda c: ("bsig", "sha")
    character.get_character_dir = lambda c: root
    garment_preview_front.state = lambda c, i: {"state": "none"}
    base_body.base_image_path = lambda c, view: root / "front.png"
    gp.picture_frame = lambda path: {"w": 100, "h": 200}
    gp.body_measure = lambda glb: {"height": 1.7, "floor": 0.0, "band_y": 1.2, "waist_y": 1.0, "hip_y": 0.9}
    try:
        out = gp.overlay("Demo", "item_x", {})
        check("ok False with the reason", (out.get("ok"), out.get("reason")) == (False, gp.NO_UPPER_JOINTS), out)
        check("picture named", (out.get("picture") or {}).get("w") == 100, out.get("picture"))
    except KeyError as exc:
        check("no KeyError", False, exc)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
