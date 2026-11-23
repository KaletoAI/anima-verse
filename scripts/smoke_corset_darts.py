"""Smoke: the corset top's darts and back line (plan group B, phase G) — the pure rules, no Blender.

Usage:
    ./.venv/bin/python scripts/smoke_corset_darts.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job. The real cut is
``scripts/smoke_template_cut_tops.py --corset-body`` [6]. Derived by hand:

[1] ``corset_darts.dart_seams(19, 41)`` — ``garment_template_build.wrap``'s front panel (panel 0, vertex
    ``r * cols + c``) of 19 rows x 41 columns, the front centre column c0 = (41 - 1) // 2 = 20:
    - the centre cut from the top edge down round(18 / 3) = 6 rows: the vertical edges (r * 41 + 20, (r + 1) * 41 + 20)
      for r = 0..5 — the first (20, 61), the last (225, 266);
    - a bust dart each side ``DART_COLS`` = round(8 * 40 / 40) = 8 columns off it (columns 12 and 28 — 8 * pi / 40 =
      0.628 rad round the body), from the top edge down round(18 / 6) = 3 rows: (12, 53), (53, 94), (94, 135) and
      (28, 69), (69, 110), (110, 151);
    12 edges in all, none on the back panel (ids < 19 * 41 = 779). Measured on copies of Rosi's body (the Red Corset
    Top, sweetheart 10 cm, lift 1.0): the front panel's stretch p95 1.262 -> 1.125, area 0.975 -> 0.994 (plain body
    1.276 / 0.969 -> 1.187 / 0.986); a dart from the hem instead gained nothing (1.258).
[2] ``dart_seams(19, 81)`` (a finer grid): c0 = 40, DART_COLS = round(8 * 80 / 40) = 16 -> columns 24 and 56; the
    centre still 6 rows, the darts 3: 12 edges.
[3] ``back_line(19, 41)``: the back panel's (panel 1, base 779) centre column 20, top to bottom: 19 ids, the first
    779 + 20 = 799, the last 779 + 18 * 41 + 20 = 1537.
[4] ``garment_template.CORSET_VERSION`` is 8 (v8, review 2026-11-23 of v7: the seam under the cups mirror-symmetric,
    its two halves meeting under the centre cut; v7, review 2026-11-23 of v6: the side blend of the edge and the strips,
    the flatter diagonals, the side fold gate, the seam under the cups; v6: the closed section over the cleavage, one
    scoop under the arms mirrored left/right, the strip drawn onto the body; v5: the edge under the arms, the stiff
    front strip;
    v4: the cup edge on the chest tissue, the dip over the apex; v3: the front hull, the settle onto the body, the
    hem tucked under a worn skirt's waistband, the painted seam lines) and keys the
    CUT of a strapless top: ``cut_sig`` of a strapless top
    is md5 of the payload ``{params: cut_params, version, uv_pattern, base, lower, panels: 1}`` PLUS ``"corset": 5``
    and ``"corset_rules"`` = md5[:12] of ``corset_darts.py`` (a changed rule re-cuts it, like ``fitted_pattern``);
    a skirt carries ``panels`` and, since stage "geometry" of round D, ``"legs": 1`` (``garment_template.leg_piece``:
    a skirt's rows below the crotch may follow the legs) — but no ``corset``.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-darts-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

import corset_darts as cd  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


s1 = cd.dart_seams(19, 41)
centre = [(r * 41 + 20, (r + 1) * 41 + 20) for r in range(6)]
darts = [(r * 41 + c, (r + 1) * 41 + c) for c in (12, 28) for r in range(3)]
check("[1] 12 edges: the centre cut 6 rows, the darts at columns 12 / 28 3 rows", sorted(s1) == sorted(centre + darts),
      sorted(set(s1) ^ set(centre + darts)))
check("[1] first / last centre edge (20, 61) / (225, 266)", (20, 61) in s1 and (225, 266) in s1)
check("[1] nothing on the back panel", all(a < 779 and b < 779 for a, b in s1))
s2 = cd.dart_seams(19, 81)
check("[2] 81 columns: darts at 24 / 56, 12 edges", len(s2) == 12 and (24, 105) in s2 and (56, 137) in s2
      and (40, 121) in s2, sorted(s2)[:4])
b3 = cd.back_line(19, 41)
check("[3] the back line: 19 ids 799 .. 1537", len(b3) == 19 and b3[0] == 799 and b3[-1] == 1537, (len(b3), b3[:2]))

check("[4] CORSET_VERSION is 8", getattr(gt, "CORSET_VERSION", None) == 8)
corset = gt.validate_params({"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "fit": 0.0})[0]
skirt = gt.validate_params({"kind": "skirt"})[0]


def md(payload):
    return hashlib.md5(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def base(p):
    return {"params": gtc.cut_params(p), "version": gt.TEMPLATE_VERSION, "uv_pattern": gtc.uv_pattern_key(p),
            "base": "b" * 64, "lower": [], "panels": 1}


check("[4] a strapless top's cut key = payload + corset 8",
      gtc.cut_sig(corset, base_sha="b" * 64, lower=[]) == md({**base(corset), "corset": 8,
                                                              "corset_rules": gtc.CORSET_DARTS_SHA}))
check("[4] a skirt's cut key carries no corset",
      gtc.cut_sig(skirt, base_sha="b" * 64, lower=[]) == md({**base(skirt), "legs": 1}))

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
