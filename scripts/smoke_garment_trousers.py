"""A233 — trousers, the last garment template kind: parameters, the cut numbers, the shoe rule, the drawing, the key.

No server, no world DB, no Blender: ``app.core.garment_template`` / ``garment_preview`` / ``garment_set`` on a
synthetic body measure. Usage: ./.venv/bin/python scripts/smoke_garment_trousers.py

Hand-derived expectations (the synthetic measure ``M``: waist_y 1.05, hip_y 0.90, hip joint 0.86, knee 0.48, ankle
0.08; the crotch of the drawing = the hip joints - 0.06 = 0.80):

[K1] trousers are built and fitted; the starting values (``kind_defaults``): rise mid, full length, straight leg,
     regular seat (bug round 2026-11-20), fit 0.3, belt band, zip, plain hem, fabric stiff. A trouser answer keeps only its fields (length_m 0.9 -> 0.5).
[K2] a stirrup only under a skinny full-length leg: capri + skinny + stirrup -> plain; skinny full keeps it;
     straight full + stirrup -> plain. An unknown leg shape -> straight + error.
[H1] ``trouser_hem`` over crotch 0.78 / knee 0.48 / ankle 0.08: shorts 0.78 + 0.3 x (0.48 - 0.78) = 0.69;
     knee 0.48 + 0.06 x (0.08 - 0.48) = 0.456; capri 0.48 + 0.5 x -0.40 = 0.28; ankle 0.48 + 0.85 x -0.40 = 0.14;
     full 0.08 - 0.01 = 0.07.
[S1] ``trouser_spec`` on M: rise mid 0.90 + 0.65 x 0.15 = 0.9975 (low 0.945, high 1.05); belt band 0.04 (elastic
     0.03, none -> the least pinned band 0.012), its extra 0.003 / 0.0015 / 0; fit 0.5: gap 0.004 + 0.012 x 0.5 =
     0.010, radial ease 0.25 x 0.5 = 0.125; shape radii straight (0.80, 0.75), skinny none; pins at the hem for
     skinny and a stirrup only.
[F1] tucked into the shoe (``tucked_into_shoes`` / ``garment_set.under_footwear`` of a template item): skinny full
     yes; skinny ankle, straight full no; tights on ``legs`` yes (as before); own-mesh trousers no.
[P1] the drawing (registration 1:1000, every leg run 0.06 either side of the joint x 0.09): a wide leg with fit 0.3
     (gap 0.004 + 0.0036 = 0.0076, r_t = 0.06 x (1 + 0.075) = 0.0645) ends at the full hem 0.07 m (under the ankle:
     np.interp holds the ankle's radius) with half width max(0.06 + 0.0076, 1.15 x 0.0645 = 0.074175) = 0.074175 ->
     x 0.015825 .. 0.164175; a skinny leg there 0.0676 -> 0.0224 .. 0.1576. The fly is a line at x 0 when not none.
[T1] the drape key: the trouser fields never enter another kind's key — skirt / tights / top / briefs keys equal
     those of commit f6f881e49 (98dcaeb9f7ea, d7a5c853ad56, afdb42cc49ef, d59cdee6cfa8 for these parameters, base
     "b" x 64, texture "t" x 12, lower ["x"], computed with that commit's TEMPLATE_VERSION 8 — A239 bumped it to 9,
     which changes every key and is not what this check is about; and with ``FITTED_VERSION`` 0, i.e. without it —
     step 3a set it to 1, which changes every fitted kind's key, tights and briefs here); a trouser's fly is painted (its key does not change), its leg shape is
     cut (the key changes).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import garment_template as gt  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def close(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol


M = {"height": 1.70, "floor_y": 0.0, "waist_y": 1.05, "waist_c": 0.70, "hip_y": 0.90, "hip_c": 0.96,
     "band_y": 1.275, "band_c": 0.86,
     "joints": {"leftupleg": [0.09, 0.86, 0.0], "rightupleg": [-0.09, 0.86, 0.0], "leftleg": [0.09, 0.48, 0.0],
                "leftfoot": [0.09, 0.08, 0.0]}}


def tr(**kw):
    return gt.validate_params({"kind": "trousers", **kw})[0]


# [K1]
check("[K1] trousers built + fitted", "trousers" in gt.BUILT_KINDS and "trousers" in gt.FITTED_KINDS)
d = gt.kind_defaults("trousers")
want = {"rise": "mid", "trouser_length": "full", "leg_shape": "straight", "seat": "regular", "fit": 0.3, "trouser_waist": "belt",
        "fly": "zip", "hem": "plain", "fabric": "stiff"}
check("[K1] starting values", all(d[k] == v for k, v in want.items()), {k: d[k] for k in want})
check("[K1] length_m is no trouser field", tr(length_m=0.9)["length_m"] == 0.5)
check("[K1] the dialog fields", gt.KIND_FIELDS["trousers"] == ("kind", "fabric", "opacity", "rise", "trouser_length",
                                                                "leg_shape", "seat", "fit", "trouser_waist", "fly",
                                                                "hem"))
check("[K1] measured in rest / walk / sit / kneel, no shape groups",
      gt.measured_poses(tr()) == ("rest", "walk", "sit", "kneel") and gt.shape_groups(tr()) == [])

# [K2]
check("[K2] capri skinny stirrup -> plain", tr(trouser_length="capri", leg_shape="skinny", hem="stirrup")["hem"] == "plain")
check("[K2] skinny full keeps the stirrup", tr(leg_shape="skinny", hem="stirrup")["hem"] == "stirrup")
check("[K2] straight full stirrup -> plain", tr(hem="stirrup")["hem"] == "plain")
p, e = gt.validate_params({"kind": "trousers", "leg_shape": "baggy"})
check("[K2] unknown leg shape -> straight + error", p["leg_shape"] == "straight" and any("leg_shape" in x for x in e))

# [H1]
A = {"crotch": 0.78, "knee": 0.48, "ankle": 0.08}
for length, h in (("shorts", 0.69), ("knee", 0.456), ("capri", 0.28), ("ankle", 0.14), ("full", 0.07)):
    check(f"[H1] {length} hem {h}", close(gt.trouser_hem(length, A), h), gt.trouser_hem(length, A))

# [S1]
for rise, top in (("low", 0.945), ("mid", 0.9975), ("high", 1.05)):
    f = gt.fitted_spec(tr(rise=rise), M)["fitted"]
    check(f"[S1] {rise} rise top {top}", close(f["top_y"], top) and f["kind"] == "trousers", f["top_y"])
for waist, band, extra in (("belt", 0.04, 0.003), ("elastic", 0.03, 0.0015), ("none", 0.012, 0.0)):
    f = gt.trouser_spec(tr(trouser_waist=waist), M)
    check(f"[S1] {waist}: band {band}, extra {extra}", close(f["band_m"], band) and close(f["waist_extra_m"], extra), f)
f = gt.trouser_spec(tr(fit=0.5), M)
check("[S1] fit 0.5: gap 0.010, radial ease 0.125", close(f["offset_m"], 0.010) and close(f["radial_ease"], 0.125), f)
check("[S1] straight radii (0.80, 0.75), not pinned at the hem", f["shape_r"] == [0.80, 0.75] and not f["hem_pinned"])
f = gt.trouser_spec(tr(leg_shape="skinny"), M)
check("[S1] skinny: no widening, pinned at the hem", f["shape_r"] is None and f["hem_pinned"])
check("[S1] the spec's frames", gt.fitted_spec(tr(), M)["fitted"]["frames"] == gt.TROUSER_FRAMES)

# [F1]
from app.core import garment_set  # noqa: E402


def item(params, slots=("bottom",), mode="template"):
    return {"name": "x", "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode, "template": {"params": params}}}


check("[F1] skinny full into the shoe", garment_set.under_footwear(item(tr(leg_shape="skinny"))))
check("[F1] skinny ankle over", not garment_set.under_footwear(item(tr(leg_shape="skinny", trouser_length="ankle"))))
check("[F1] straight full over", not garment_set.under_footwear(item(tr())))
check("[F1] tights on legs into the shoe", garment_set.under_footwear(item({"kind": "tights"}, slots=("legs",))))
check("[F1] own-mesh trousers over", not garment_set.under_footwear(item(tr(leg_shape="skinny"), mode="own_mesh")))


# [P1]
class Reg:
    x0 = 0.0

    def px(self, x, y):
        return [x * 1000.0, (2.0 - y) * 1000.0]

    def body_half(self, y, cap_m):
        return 0.17, 0.17

    def leg_run(self, y, guess):
        return (0.09 - 0.06, 0.09 + 0.06) if guess > 0 else (-0.09 - 0.06, -0.09 + 0.06)


from app.core import garment_preview as gp  # noqa: E402


def hem_span(params):
    out = gp.shapes(params, M, Reg())
    legs = [s for s in out["shapes"] if s["role"] == "leg" and len(s["points"]) > 3]
    left = [q for q in legs if q["points"][0][0] > 0][0]["points"]
    low = [q for q in left if abs((2.0 - q[1] / 1000.0) - 0.07) < 1e-6]
    return sorted(q[0] / 1000.0 for q in low), out


span, out = hem_span(tr(leg_shape="wide"))
check("[P1] wide hem 0.015825 .. 0.164175", len(span) == 2 and close(span[0], 0.015825) and close(span[1], 0.164175),
      span)
span, out = hem_span(tr(leg_shape="skinny"))
check("[P1] skinny hem 0.0224 .. 0.1576", len(span) == 2 and close(span[0], 0.0224) and close(span[1], 0.1576), span)
check("[P1] the fly line", any(s["role"] == "fly" for s in out["shapes"]))
check("[P1] no fly line without a fly", not any(s["role"] == "fly" for s in gp.shapes(tr(fly="none"), M, Reg())["shapes"]))

# [T1]
_version, gt.TEMPLATE_VERSION = gt.TEMPLATE_VERSION, 8
_fitted, gt.FITTED_VERSION = gt.FITTED_VERSION, 0
for raw, key in (({"kind": "skirt", "length_m": 0.45, "flare": 0.4}, "98dcaeb9f7ea"),
                 ({"kind": "tights", "fabric": "sheer", "opacity": 0.5}, "d7a5c853ad56"),
                 ({"kind": "top", "shoulders": "covered", "sleeves": "short"}, "afdb42cc49ef"),
                 ({"kind": "briefs"}, "d59cdee6cfa8")):
    got = gt.tsig(gt.validate_params(raw)[0], base_sha="b" * 64, texture_sha="t" * 12, lower=["x"])
    check(f"[T1] {raw['kind']} key as at f6f881e49 ({key})", got == key, got)
gt.TEMPLATE_VERSION = _version
gt.FITTED_VERSION = _fitted


def key(params):
    return gt.tsig(params, base_sha="b" * 64, texture_sha="t" * 12, lower=[])


check("[T1] the fly is painted: same key", key(tr(fly="zip")) == key(tr(fly="buttons")))
check("[T1] the leg shape is cut: another key", key(tr()) != key(tr(leg_shape="wide")))

print("ALL OK" if not FAILED else f"FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
