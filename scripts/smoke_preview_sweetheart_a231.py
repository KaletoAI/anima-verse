"""A231 — the template dialog's preview draws a corset top's sweetheart top edge with the drape's own rule.

Usage: ./.venv/bin/python scripts/smoke_preview_sweetheart_a231.py   (no server, no world, no files)

Before A231 the preview drew a strapless top's / a straps top's top edge straight across (``shapes`` never read the
sweetheart), so the dip never showed. ``garment_preview.top_edge_curve`` now uses ``garment_template.sweetheart_drop``
(the same function as the drape's ``top_drop``). Hand-derived, CURVE_N = 24, rims (+-0.10, 1.20), depth 0.05
(neck_depth_m 0 -> SWEETHEART_DIP_M 0.05), half_rad 0.5:

* i = 12 (s = 0, a = 0):       (0.0, 1.20 - 0.05)                         = (0.0, 1.15)
* i = 9  (s = 0.25):           a = asin 0.25 = 0.252680; (1 - 0.252680 / 0.5)^2 = 0.494640^2 = 0.244669;
                               drop 0.012233 -> (0.025, 1.187767)
* i = 6  (s = 0.5):            a = pi/6 = 0.5236 > 0.5 -> no drop -> (0.05, 1.20)
* i = 0 / 24 (rims):           (0.10, 1.20) / (-0.10, 1.20)
* top_drop(cols = 5): column angles off centre pi/2, pi/4, 0 -> drops 0, 0, 0.05, 0, 0 (pi/4 = 0.785 > 0.5).
* depth 0.08 -> centre 1.12; depth 0.3 -> capped at SWEETHEART_MAX_M 0.10 -> centre 1.10.
* ``shapes`` end to end (band_y 1.275; a test registration px = (x * 1000, (2 - y) * 1000)):
  strapless sweetheart top: top edge = band_y - STRAPLESS_UNDERARM_M 0.02 = 1.255, centre 1.255 - 0.05 = 1.205
  -> px y 795; straps sweetheart top: the band 1.275, centre 1.225 -> px y 775; a straight neckline draws no
  ``top_edge`` line.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="a231-smoke-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
from app.core import garment_preview as gp  # noqa: E402
from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(name, got, want, tol=1e-6):
    ok = all(abs(a - b) <= tol for a, b in zip(got, want)) if isinstance(want, (list, tuple)) else abs(got - want) <= tol
    print(("ok  " if ok else "FAIL"), name, got, "want", want)
    if not ok:
        FAILS.append(name)


c = gp.top_edge_curve(0.0, [0.10, 1.20], [-0.10, 1.20], 0.05)
check("centre", c[12], (0.0, 1.15))
check("s=0.25", c[9], (0.025, 1.187767))
check("s=-0.25", c[15], (-0.025, 1.187767))
check("s=0.5 outside", c[6], (0.05, 1.20))
check("right rim", c[0], (0.10, 1.20))
check("left rim", c[24], (-0.10, 1.20))
p = {"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "neck_depth_m": 0.0}
check("depth default", gt.sweetheart_depth(p), 0.05)
check("top_drop cols 5", gt.top_drop(p, 5), (0.0, 0.0, 0.05, 0.0, 0.0))
check("depth 0.08", gp.top_edge_curve(0.0, [0.1, 1.2], [-0.1, 1.2], gt.sweetheart_depth(dict(p, neck_depth_m=0.08)))[12][1], 1.12)
check("depth capped", gt.sweetheart_depth(dict(p, neck_depth_m=0.3)), 0.10)
M = {"height": 1.70, "floor_y": 0.0, "waist_y": 1.05, "waist_c": 0.70, "hip_y": 0.90, "hip_c": 0.96,
     "band_y": 1.275, "band_c": 0.86, "shoulder_y": 1.40, "shoulder_w": 0.40, "neck_y": 1.47, "neck_c": 0.33,
     "arm_len": 0.50, "arm_c": [[0.05, 0.30], [0.97, 0.16]], "upper_arm_c": 0.28, "wrist_c": 0.16,
     "torso": [[round(0.68 + 0.02 * i, 3), 0.80] for i in range(37)],
     "joints": {"leftarm": [0.16, 1.40, 0.0], "rightarm": [-0.16, 1.40, 0.0], "neck": [0.0, 1.47, 0.0],
                "spine2": [0.0, 1.25, 0.0], "leftupleg": [0.09, 0.86, 0.0]}}


class Reg:
    x0 = 0.0
    exact = True

    def px(self, x, y):
        return [x * 1000.0, (2.0 - y) * 1000.0]

    def body_half(self, y, cap_m):
        return 0.17, 0.17

    def joint_arm_axis(self, side):
        return (side * 0.16, 1.40), (float(side), 0.0)


def edge_of(**kw):
    params = gt.validate_params({"kind": "top", "length_m": 0.4, **kw})[0]
    edges = [s for s in gp.shapes(params, M, Reg())["shapes"] if s["role"] == "top_edge"]
    return edges[0]["points"] if edges else None


e = edge_of(shoulders="strapless", neckline="sweetheart")
check("strapless centre px", e[12], (0.0, 795.0), 1e-3)
check("strapless rim y px", e[0][1], 745.0, 1e-3)
e = edge_of(shoulders="straps", neckline="sweetheart")
check("straps centre px", e[12], (0.0, 775.0), 1e-3)
check("straps rim y px", e[0][1], 725.0, 1e-3)
check("straight: no edge", 0 if edge_of(shoulders="strapless", neckline="straight") is None else 1, 0)
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
