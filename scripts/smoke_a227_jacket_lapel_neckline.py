"""Smoke: A227 — a jacket with a lapel collar has no neckline choice: the lapel's V replaces it.

Usage:
    ./.venv/bin/python scripts/smoke_a227_jacket_lapel_neckline.py

No server, no world DB, no Blender. ``bodice_spec`` is fed a hand-made measurement (shoulder_y 1.40, band_y 1.25,
neck_c 0.38, shoulder_w 0.40), so every expected number is arithmetic:

[1] collar lapel, neckline crew / v / scoop / boat, neck_depth_m 0: the spec is neckline "v", depth
    max(NECK_DEPTH[n], 1.40 - 1.25 + 0.04) = 0.19 for every one of them — the same cut (the reason the dialog
    hides the field), and front_open True.
[2] collar none: crew 0.01, v 0.12, scoop 0.08 deep; boat 0.0 deep with neck_r = max(0.38 / 2pi + NECK_CLEAR_M,
    BOAT_SHARE * 0.20) — four different cuts, so the dialog keeps the field there.
[3] the dialog: TemplateParamsDialog.tsx hides 'neckline' for kind jacket + collar lapel (``lapelNeck``) and its
    hint string is translated in de.json.
"""
import json, math, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp())
from app.core import paths  # noqa: E402
paths.init(os.environ["STORAGE_DIR"])
from app.core import garment_template as gt  # noqa: E402

MEAS = {"shoulder_y": 1.40, "band_y": 1.25, "neck_y": 1.45, "neck_c": 0.38, "shoulder_w": 0.40, "arm_len": 0.55,
        "arm_c": [[0.0, 0.30], [1.0, 0.16]], "joints": {}}
fails = []


def check(name, ok, got=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({got})" if got else ""))
    if not ok:
        fails.append(name)


def spec(collar, neck):
    p, _e = gt.validate_params({"kind": "jacket", "collar": collar, "neckline": neck, "front": "closed",
                                "sleeves": "none", "length_m": 0.6})
    orig = gt.outline
    gt.outline = lambda _p, _m, **_k: {"top_y": 1.42}
    try:
        return gt.bodice_spec(p, MEAS)
    finally:
        gt.outline = orig


for n in ("crew", "v", "scoop", "boat"):
    b = spec("lapel", n)
    check(f"[1] lapel {n} -> v 0.19 open", (b["neckline"], b["depth_m"], b["front_open"]) == ("v", 0.19, True),
          f"{b['neckline']} {b['depth_m']} {b['front_open']}")
want = {"crew": ("crew", 0.01), "v": ("v", 0.12), "scoop": ("scoop", 0.08), "boat": ("boat", 0.0)}
for n, w in want.items():
    b = spec("none", n)
    check(f"[2] none {n} -> {w}", (b["neckline"], b["depth_m"]) == w, f"{b['neckline']} {b['depth_m']}")
boat_r = round(max(0.38 / (2 * math.pi) + gt.NECK_CLEAR_M, gt.BOAT_SHARE * 0.20), 4)
check("[2] boat neck_r", spec("none", "boat")["neck_r"] == boat_r, f"{spec('none', 'boat')['neck_r']} vs {boat_r}")
tsx = (ROOT / "frontend/src/tabs/characters/TemplateParamsDialog.tsx").read_text()
check("[3] dialog hides neckline for a lapel jacket",
      "if (key === 'neckline' && lapelNeck(p)) return false" in tsx and "p.kind === 'jacket' && p.collar === 'lapel'" in tsx)
hint = "A lapel opens the front in a V down to the chest; it replaces the neckline."
check("[3] hint translated", hint in tsx and hint in json.loads((ROOT / "shared/languages/de.json").read_text())["translations"])
print("FAILED: " + ", ".join(fails) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
