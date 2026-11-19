"""A223 — the fitted garment templates (briefs, bra, gloves): cut from the plain body's own surface.

Called by ``garment_template_build.run`` for a ``spec["fitted"]`` (``app.core.garment_template.fitted_spec``; glTF
Y-up metres there, Blender Z-up here: glTF y = Blender z, glTF z = -Blender y, the front is -Y, the character's left
+X). A close-fitting piece is not wrapped from panel rows: the faces of the body's region are copied (rest pose,
consistent outward winding), cut clean where the edge is a plane (``bmesh.ops.bisect_plane``: a waistband, a cuff,
the band's lower edge), the holes left by a procedural part's faces (an inset part, ``attached_part``) are closed,
every vertex is laid ``offset_m`` out along the outward body normal, the surface is evened (umbrella passes, a border
only along the border, so a cut through the triangles loses its zigzag) and laid out of the rest collider. The
caller then pins the returned vertices and runs the short cloth relax (``frames``).

* briefs: waistband plane at ``top_y``; the leg opening per face centroid: under the gusset (|x| < gusset half width)
  the crotch less 5 mm, rising to ``top - side_width`` at the hip's side over a curve shaped by ``leg_cut``; on the
  back the full-height part reaches ``back_coverage`` of the way to the side. Pinned: the waistband and the gusset.
* bra: the underband plane at ``under_y - band``; per side a cup from the underbust line to its top edge
  (``style`` / ``coverage``), the gore between them, the straps (``straps``) as strips within half their width of a
  path laid on the surface; push-up moves the cups up, in and out before the evening. Pinned: the band, the straps,
  the gore and — molded — the cups whole (rigid).
* gloves: per side the faces whose skin follows the arm / hand / finger bones, up to ``reach_m`` from the wrist
  (cuff plane); fingerless leaves the finger-weighted faces, none the hand. The fingers lie ``finger_offset_m`` over
  the skin and are pinned with the hand and the cuff's edge (no finger is draped).
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import garment_template_drape as gd

#: Umbrella passes of the evening (fitted kinds), and the extra ones of a molded cup (it bridges the bust).
SMOOTH_PASSES = {"briefs": 6, "bra": 6, "gloves": 2, "tights": 6}
MOLDED_PASSES = 14
#: The closure's extra thickness (a hook patch on the back band / a front clasp), metres, and its half width.
CLOSURE_M = 0.0015
CLOSURE_HALF_M = 0.025
#: A bra cup is pinned within this distance of the bust point (the cloth over a breast's tip was the one edge a
#: triangle cup's drape stretched to 1.34).
TIP_PIN_M = 0.03
#: Gloves up to this fit are pinned whole (``build_fitted``).
TIGHT_GLOVE_FIT = 0.3
#: A strap path is sampled this densely.
STRAP_STEP_M = 0.01


def _gltf_y(v):
    """A glTF Y-up height is Blender's z."""
    return float(v)


def _weights(body, names):
    """``{bone: per-vertex weight}`` of the body for the bones named (``mixamorig:`` prefix added)."""
    gi = {g.name: g.index for g in body.vertex_groups}
    want = {gi[gd.P + n]: n for n in names if gd.P + n in gi}
    out = {n: np.zeros(len(body.data.vertices)) for n in names}
    for v in body.data.vertices:
        for g in v.groups:
            n = want.get(g.group)
            if n is not None:
                out[n][v.index] = g.weight
    return out


def _part_faces(body):
    """Per polygon: whether its material is a procedural part's (``attached_part`` / ``inset_part`` extras)."""
    mats = body.data.materials
    part = []
    for m in mats:
        keys = set(m.keys()) if m is not None else set()
        part.append(bool(m is not None and ("attached_part" in keys or m.name.startswith("part_"))))
    idx = np.empty(len(body.data.polygons), np.int32)
    body.data.polygons.foreach_get("material_index", idx)
    flags = np.array(part + [False], bool)
    return flags[np.minimum(idx, len(part))] if len(part) else np.zeros(len(idx), bool)


def _surface_tree(body):
    """The rest body with consistent outward winding: ``(co, outward normals, BVH)`` (``gd.body_state``)."""
    return gd.body_state(body)


def _ray(tree, origin, direction, reach=1.0):
    hit = tree.ray_cast(Vector(origin), Vector(direction).normalized(), reach)
    return None if hit[0] is None else np.array(hit[0])


def _seg_dist(p, a, b):
    """Distance of the points ``p`` (n, 3) to the segment a-b."""
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(1e-12, ab @ ab), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def _path_dist(p, path):
    d = np.full(len(p), 9.0)
    for a, b in zip(path[:-1], path[1:]):
        d = np.minimum(d, _seg_dist(p, a, b))
    return d


# --- regions ---------------------------------------------------------------------------------------------------

def _crotch(co, w_hips, cx, top):
    """The crotch height: the lowest vertex within 3 cm of the centre line with Hips weight > 0.3 below the
    waistband (``garment_fit.crotch_height``'s rule; a procedural part rigged to the hips counts — it is covered)."""
    m = (np.abs(co[:, 0] - cx) < 0.03) & (w_hips > 0.3) & (co[:, 2] < top)
    return float(co[m, 2].min()) if m.any() else top - 0.2


def briefs_region(f, co, w, cx, cy):
    """``(face keep predicate on centroids, planes, info)`` of briefs."""
    top = _gltf_y(f["top_y"])
    crotch = _crotch(co, w["Hips"], cx, top)
    cy = _mid_y(co, cx, (crotch + top) / 2)
    near = (co[:, 2] < top) & (co[:, 2] > crotch - 0.05)
    hip_half = float(np.percentile(np.abs(co[near, 0] - cx), 99)) if near.any() else 0.17
    g = float(f["gusset_half_m"])
    base = crotch - 0.005
    side = top - float(f["side_width_m"])
    lc = float(f["leg_cut"])
    low_side = crotch - float(f["boyshort_drop_m"])
    l_side = low_side + lc * (side - low_side)
    power = 1.6 - 1.2 * lc                       # a high cut rises soon past the gusset, a boyshort stays low
    bc = float(f["back_coverage"])
    w_back = g * 0.4 + bc * 0.9 * (hip_half - g * 0.4)

    def leg_line(ax, back):
        wid = np.where(back, w_back, g)
        t = np.clip((ax - wid) / np.maximum(hip_half - wid, 1e-3), 0.0, 1.0)
        rise = t ** power
        if bc < 0.999:
            # a string / Brazilian back: past its width the line climbs within 3 cm to the side's height
            steep = np.clip((ax - wid) / 0.03, 0.0, 1.0) * (1.0 - bc) ** 0.5
            rise = np.where(back, np.maximum(rise, steep), rise)
        return base + (l_side - base) * rise

    def keep(c):
        ax = np.abs(c[:, 0] - cx)
        back = c[:, 1] > cy
        return (c[:, 2] <= top + 0.02) & (c[:, 2] >= leg_line(ax, back))

    planes = [(np.array([0.0, 0.0, top]), np.array([0.0, 0.0, 1.0]))]
    band = float(f["band_m"])

    def pins(v):
        ax = np.abs(v[:, 0] - cx)
        return (v[:, 2] > top - band - 0.002) | ((ax < g) & (v[:, 2] < crotch + 0.03))

    return keep, planes, pins, {"cy": cy, "crotch_z": round(crotch, 4), "hip_half_m": round(hip_half, 4),
                                "leg_side_z": round(l_side, 4), "back_width_m": round(w_back, 4)}


def _mid_y(co, cx, z, half=0.15):
    """The middle between the front and the back of the body's slice at height ``z`` (the bones of a generated
    rig sit nearer the back or the front than the middle)."""
    m = (np.abs(co[:, 2] - z) < 0.01) & (np.abs(co[:, 0] - cx) < half)
    return float((co[m, 1].min() + co[m, 1].max()) / 2) if m.any() else 0.0


def _apex(co, cx, cy, s, bust, under):
    m = (s * (co[:, 0] - cx) > 0.03) & (s * (co[:, 0] - cx) < 0.17) & (co[:, 1] < cy) \
        & (co[:, 2] > under) & (co[:, 2] < bust + 0.08)
    if not m.any():
        return np.array([cx + s * 0.09, cy - 0.1, bust])
    i = np.where(m)[0][int(np.argmin(co[m, 1]))]
    return co[i].copy()


#: The fold under a breast is looked for this far under the apex, in steps of FOLD_STEP_M.
FOLD_SCAN_M = 0.14
FOLD_STEP_M = 0.004


def _fold(tree, apex, cy):
    """The height of the breast's fold under ``apex``: going down from the apex along the front surface (rays from
    the front at the apex's x), the first height after the steepest recession where the surface recedes less than a
    fifth as fast (the breast's underside ends on the ribs); None without a recession of 4 mm per step."""
    ys = []
    for k in range(int(FOLD_SCAN_M / FOLD_STEP_M)):
        z = float(apex[2]) - FOLD_STEP_M * (k + 1)
        h = _ray(tree, (float(apex[0]), cy - 0.6, z), (0, 1, 0))
        ys.append((z, None if h is None else float(h[1])))
    zs = [z for z, y in ys if y is not None]
    yv = [y for z, y in ys if y is not None]
    if len(yv) < 5:
        return None
    dy = np.diff(yv)                         # > 0: the surface recedes going down
    k = int(np.argmax(dy))
    if dy[k] < 0.004:                        # no breast to speak of
        return None
    for i in range(k + 1, len(dy)):
        if dy[i] < 0.2 * dy[k]:
            return float(zs[i])
    return None


def strap_path(tree, st, start, cx, cy, s, under):
    """A223 — one strap as a polyline on the body surface (``strap_spec``): from ``start`` (the cup top) up the
    front to the shoulder at ``shoulder_x`` (rays from the front), over the shoulder (rays from above), down the back
    to the band at ``back_x`` (rays from behind); a halter instead runs up to the side of the neck and round its back
    (rays from the neck axis out)."""
    sx = cx + s * float(st["shoulder_x"])
    neck_z = _gltf_y(st["neck_y"])
    top = _ray(tree, (sx, cy, neck_z + 0.3), (0, 0, -1), 0.6)
    sh_z = float(top[2]) if top is not None else neck_z - 0.06
    pts = []
    if st["style"] == "halter":
        nx = cx + s * float(st["neck_r"]) * 0.9
        n = max(2, int(math.dist(start[[0, 2]], (nx, neck_z)) / STRAP_STEP_M))
        for t in np.linspace(0, 1, n):
            x, z = start[0] + (nx - start[0]) * t, start[2] + (neck_z - start[2]) * t
            h = _ray(tree, (x, cy - 0.5, z), (0, 1, 0))
            if h is not None:
                pts.append(h)
        for ang in np.linspace(0, math.pi / 2, 10):     # round the back of the neck to the spine
            d = (s * math.cos(ang), math.sin(ang), 0.0)
            h = _ray(tree, (cx + d[0] * 0.3, cy + d[1] * 0.3, neck_z), (-d[0], -d[1], 0), 0.3)
            if h is not None:
                pts.append(h)
        return np.array(pts)
    n = max(2, int(abs(sh_z - start[2]) / STRAP_STEP_M))
    for t in np.linspace(0, 1, n):
        x, z = start[0] + (sx - start[0]) * t, start[2] + (sh_z - 0.02 - start[2]) * t
        h = _ray(tree, (x, cy - 0.5, z), (0, 1, 0))
        if h is not None:
            pts.append(h)
    front_y = pts[-1][1] if pts else cy - 0.08
    for y in np.linspace(front_y, cy + 0.08, 12):
        h = _ray(tree, (sx, y, sh_z + 0.2), (0, 0, -1), 0.4)
        if h is not None:
            pts.append(h)
    bx = cx + s * float(st["back_x"])
    n = max(2, int(abs(sh_z - under) / STRAP_STEP_M))
    for t in np.linspace(0, 1, n):
        x, z = sx + (bx - sx) * t, sh_z - 0.02 + (under - (sh_z - 0.02)) * t
        h = _ray(tree, (x, cy + 0.5, z), (0, -1, 0))
        if h is not None:
            pts.append(h)
    return np.array(pts)


def bra_region(f, co, tree, cx, cy):
    under = _gltf_y(f["under_y"])
    bust = _gltf_y(f["bust_y"])
    band = max(float(f["band_m"]), float(f["back_strap_m"]))
    cov = float(f["coverage"])
    style = f["style"]
    gore_half, gore_h = float(f["gore_half_m"]), float(f["gore_h_m"])
    apex = {s: _apex(co, cx, cy, s, bust, under) for s in (1, -1)}
    # the underbust line is the breast's fold under each apex where the body shows one (the narrowest torso slice
    # can lie on the ribs below it): the front surface furthest back between the apex and FOLD_SCAN_M under it
    folds = [z for z in (_fold(tree, a, cy) for a in apex.values()) if z is not None]
    info_fold = {"folds": [round(z, 4) for z in folds]}
    if folds:
        under = max(under, min(folds))
    info = {"apex": {("l" if s > 0 else "r"): [round(float(x), 4) for x in a] for s, a in apex.items()},
            "under_z": round(under, 4), **info_fold}
    tops = {}
    for s, a in apex.items():
        H = max(0.03, float(a[2]) - under)
        zc = float(a[2]) + (cov - 0.5) * 2.0 * H
        r_in = max(0.02, abs(float(a[0]) - cx) - gore_half)
        r_out = 0.075
        tops[s] = (a, H, zc, r_in, r_out)

    def cup_top(c, s):
        a, H, zc, r_in, r_out = tops[s]
        dx = c[:, 0] - a[0]
        r = np.where(s * dx < 0, r_in, r_out)
        u = np.clip(np.abs(dx) / r, 0.0, 1.0)
        if style == "molded":
            z = zc - 0.5 * H * u ** 2
        elif style == "triangle":
            peak = zc + 0.8 * H
            z = peak - (peak - (under + 0.015)) * u
        else:                                   # balconette (and the bandeau's edge)
            z = np.full(len(c), zc)
        return np.maximum(z, under + 0.01), np.abs(dx) <= r

    def cups(c):
        out = np.zeros(len(c), bool)
        if style == "bandeau":
            zc = max(t[2] for t in tops.values())
            return (c[:, 2] >= under - 1e-4) & (c[:, 2] <= zc)
        front = c[:, 1] < cy
        for s in (1, -1):
            side = s * (c[:, 0] - cx) >= gore_half
            zt, inside = cup_top(c, s)
            out |= front & side & inside & (c[:, 2] >= under - 1e-4) & (c[:, 2] <= zt)
        return out

    def gore(c):
        if style == "bandeau":
            return np.zeros(len(c), bool)
        return (c[:, 1] < cy) & (np.abs(c[:, 0] - cx) < gore_half + 0.004) & (c[:, 2] >= under - 1e-4) \
            & (c[:, 2] <= under + gore_h)

    paths = []
    st = f.get("straps")
    if st:
        for s, a in apex.items():
            zt, _ins = cup_top(a[None, :], s) if style != "bandeau" else (np.array([tops[s][2]]), None)
            start = np.array([a[0] + s * 0.005, a[1], float(zt[0]) - 0.01])
            h = _ray(tree, (start[0], cy - 0.5, start[2]), (0, 1, 0))
            paths.append(strap_path(tree, st, h if h is not None else start, cx, cy, s, under))
        info["strap_points"] = [len(p) for p in paths]
    half_w = float(st["width_m"]) / 2 if st else 0.0
    arm_x = max(abs(float(a[0]) - cx) for a in apex.values()) + 0.09

    def straps(c):
        if not paths:
            return np.zeros(len(c), bool)
        d = np.full(len(c), 9.0)
        for p in paths:
            if len(p) > 1:
                d = np.minimum(d, _path_dist(c, p))
        return (d < half_w) & (c[:, 2] >= under - 1e-4) & (np.abs(c[:, 0] - cx) < arm_x)

    def band_ring(c):
        return (c[:, 2] <= under + 1e-4) & (np.abs(c[:, 0] - cx) < arm_x + 0.05)

    def keep(c):
        return (band_ring(c) & (c[:, 2] >= under - band - 0.01)) | cups(c) | gore(c) | straps(c)

    planes = [(np.array([0.0, 0.0, under - band]), np.array([0.0, 0.0, -1.0]))]

    def pins(v):
        p = (v[:, 2] <= under + 0.003) | straps(v) | gore(v)
        if f.get("rigid_cups") or style == "bandeau":
            p |= cups(v)
        return p

    def push(v):
        """Per vertex (dz, dx toward the centre, out) of the push-up, 1 inside a cup and 0 outside."""
        if style == "bandeau":
            return np.zeros(len(v))
        return cups(v).astype(float)

    def closure(v):
        if f["closure"] == "back_hook":
            return (v[:, 1] > cy) & (np.abs(v[:, 0] - cx) < CLOSURE_HALF_M) & (v[:, 2] <= under + 0.003)
        if f["closure"] == "front":
            return (v[:, 1] < cy) & (np.abs(v[:, 0] - cx) < gore_half + 0.004) & (v[:, 2] <= under + gore_h)
        return np.zeros(len(v), bool)

    info["band_m"] = round(band, 4)
    return keep, planes, pins, push, closure, cups, info


def _arm_chain(arm, side):
    sh = np.array(arm.matrix_world @ arm.data.bones[gd.P + side + "Arm"].head_local)
    el = np.array(arm.matrix_world @ arm.data.bones[gd.P + side + "ForeArm"].head_local)
    wr = np.array(arm.matrix_world @ arm.data.bones[gd.P + side + "Hand"].head_local)
    return sh, el, wr


def along_arm(p, sh, el, wr):
    """Distance up the arm from the wrist joint (negative into the hand) of the points ``p``: along the forearm,
    then the upper arm."""
    fa = el - wr
    lf = np.linalg.norm(fa)
    t = (p - wr) @ (fa / lf)
    ua = sh - el
    lu = np.linalg.norm(ua)
    t2 = (p - el) @ (ua / lu)
    return np.where(t <= lf, t, lf + np.maximum(t2, 0.0))


def point_up_arm(d, sh, el, wr):
    """The point ``d`` metres up the arm from the wrist joint and the arm's direction there."""
    lf = np.linalg.norm(el - wr)
    if d <= lf:
        u = (el - wr) / lf
        return wr + u * d, u
    u = (sh - el) / np.linalg.norm(sh - el)
    return el + u * (d - lf), u


GLOVE_BONES = ["Arm", "ForeArm", "Hand"] + [f"Hand{fn}{k}" for fn in ("Thumb", "Index", "Middle", "Ring", "Pinky")
                                             for k in (1, 2, 3)]


def gloves_region(f, co, w, arm):
    reach = float(f["reach_m"])
    sides = {}
    planes = []
    for side, s in (("Left", 1), ("Right", -1)):
        sh, el, wr = _arm_chain(arm, side)
        member = sum(w[side + b] for b in GLOVE_BONES)
        fing = sum(w[side + b] for b in GLOVE_BONES[3:])
        hand = w[side + "Hand"] + fing
        sides[s] = (sh, el, wr, member, fing, hand)
        p, u = point_up_arm(reach, sh, el, wr)
        planes.append((p, u, s))
        if f["fingers"] == "none":
            planes.append((wr, -(el - wr) / np.linalg.norm(el - wr), s))

    def side_of(c):
        return np.where(c[:, 0] > 0, 1, -1)

    def keep_v(v, member_v, fing_v, hand_v):
        out = np.zeros(len(v), bool)
        for s, (sh, el, wr, _m, _f, _h) in sides.items():
            on = (side_of(v) == s) & (member_v[s] > 0.5)
            d = along_arm(v, sh, el, wr)
            k = on & (d <= reach + 0.01)
            if f["fingers"] == "fingerless":
                k &= fing_v[s] < 0.5
            elif f["fingers"] == "none":
                k &= (hand_v[s] < 0.5) & (d >= -0.01)
            out |= k
        return out

    def dist(v):
        d = np.full(len(v), 9.0)
        for s, (sh, el, wr, *_r) in sides.items():
            d = np.where(side_of(v) == s, along_arm(v, sh, el, wr), d)
        return d

    return sides, keep_v, planes, dist, {"reach_m": reach}


LEG_BONES = ("UpLeg", "Leg", "Foot", "ToeBase")


def _bone_head(arm, name):
    return np.array(arm.matrix_world @ arm.data.bones[gd.P + name].head_local)


def tights_region(f, co, w, arm, cx):
    """A223 tights: ``(keep_v on collider vertices with their nearest body vertex's weights, planes, band(v), info)``.
    Full tights take the hips and both legs up to ``top_y``; a stocking / sock is per leg up to its top (a horizontal
    plane per side: under the crotch, under the knee). The foot: closed, footless (cut at the ankle joint) or a stirrup
    (footless + a band round the middle of the foot)."""
    style = f["style"]
    crotch = _crotch(co, w["Hips"], cx, _gltf_y(f["top_y"]) if f.get("top_y") else 2.0)
    sides = {}
    for side, s in (("Left", 1), ("Right", -1)):
        knee = _bone_head(arm, side + "Leg")
        ankle = _bone_head(arm, side + "Foot")
        toe = _bone_head(arm, side + "ToeBase")
        if style == "tights":
            top = _gltf_y(f["top_y"])
        elif style == "knee_high":
            top = float(knee[2]) - float(f["knee_drop_m"])
        else:
            top = crotch - float(f["thigh_drop_m"])
        sides[s] = {"top": top, "ankle": ankle, "toe": toe, "knee": knee,
                    "leg_x": float(_bone_head(arm, side + "UpLeg")[0])}
    legs = sum(w[sd + b] for sd in ("Left", "Right") for b in LEG_BONES)
    foot = sum(w[sd + b] for sd in ("Left", "Right") for b in ("Foot", "ToeBase"))

    def side_of(v):
        return np.where(v[:, 0] > cx, 1, -1)

    def keep_v(v, legs_v, hips_v, foot_v):
        sd = side_of(v)
        top = np.where(sd > 0, sides[1]["top"], sides[-1]["top"])
        member = legs_v + (hips_v if style == "tights" else 0.0)
        k = (member > 0.5) & (v[:, 2] <= top + 0.005)
        if f["garters"] == "tabs":
            for s_, d in sides.items():
                on = (sd == s_) & (np.abs(v[:, 0] - d["leg_x"]) < float(f["tab_half_m"])) \
                    & (v[:, 2] > d["top"]) & (v[:, 2] <= d["top"] + float(f["tab_h_m"])) & (member > 0.5)
                k |= on
        if f["feet"] != "closed":
            ank = np.where(sd > 0, sides[1]["ankle"][2], sides[-1]["ankle"][2])
            open_foot = (foot_v > 0.5) & (v[:, 2] < ank - 0.01)
            if f["feet"] == "stirrup":
                mid = np.where(sd[:, None] > 0, (sides[1]["ankle"] + sides[1]["toe"]) / 2,
                               (sides[-1]["ankle"] + sides[-1]["toe"]) / 2)
                ring = np.abs(v[:, 1] - mid[:, 1]) < 0.025
                open_foot &= ~ring
            k &= ~open_foot
        return k

    planes = []
    if style != "tights":
        for s_, d in sides.items():
            if f["garters"] != "tabs":
                planes.append((np.array([0.0, 0.0, d["top"]]), np.array([0.0, 0.0, 1.0]), s_))
    else:
        planes.append((np.array([0.0, 0.0, sides[1]["top"]]), np.array([0.0, 0.0, 1.0])))

    def band(v):
        """The thicker band at the top: the waistband (full tights), the grip band (hold-up), the sock's cuff."""
        sd = side_of(v)
        top = np.where(sd > 0, sides[1]["top"], sides[-1]["top"])
        h = float(f["waistband_m"]) if style == "tights" else float(f["band_m"])
        return (h > 0) & (v[:, 2] > top - h)

    info = {"crotch_z": round(crotch, 4), "tops": {str(s_): round(d["top"], 4) for s_, d in sides.items()}}
    return keep_v, planes, band, legs, foot, info


# --- the builder -----------------------------------------------------------------------------------------------

def _umbrella(bm, passes, movable, boundary_only_along=True):
    """Even the surface: per pass every movable vertex moves half way to its neighbours' mean (a border vertex only
    to its border neighbours' — it slides along the cut, the zigzag of a cut through triangles goes)."""
    bm.verts.ensure_lookup_table()
    for _ in range(passes):
        new = {}
        for v in bm.verts:
            if not movable[v.index]:
                continue
            if boundary_only_along and v.is_boundary:
                nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
            else:
                nb = [e.other_vert(v) for e in v.link_edges]
            if len(nb) < 2:
                continue
            m = sum((u.co for u in nb), Vector()) / len(nb)
            new[v.index] = v.co.lerp(m, 0.5)
        for i, c in new.items():
            bm.verts[i].co = c


def build_fitted(prm, spec, arm, body, ctree, col=None):
    """The fitted piece as a new mesh object (``prm["node"]``) with planar UVs; returns ``(obj, pin indices,
    info)``."""
    f = spec["fitted"]
    kind = f["kind"]
    co, nrm, stree = _surface_tree(body)
    sp = np.array(arm.matrix_world @ arm.data.bones[gd.P + "Spine1"].head_local)
    cx, cy = float(sp[0]), float(sp[1])
    names = ["Hips"] + [s + b for s in ("Left", "Right") for b in GLOVE_BONES + list(LEG_BONES)]
    w = _weights(body, names)
    info = {"kind": kind}
    # the piece is cut from the rest collider (``gd.rest_collider``: the body voxel-remeshed — closed, one outward
    # skin; the generated body itself is a thick shell with an inner wall, mixed windings and procedural parts whose
    # skin under them is missing, so a copy of its faces had holes and inward patches)
    bm = bmesh.new()
    bm.from_mesh(col.data)
    bm.transform(col.matrix_world)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    cent = np.array([fa.calc_center_median() for fa in bm.faces])
    keep_layer = bm.faces.layers.int.new("keep")
    push = closure = cups = None
    if kind == "briefs":
        keep, planes, pins, extra = briefs_region(f, co, w, cx, cy)
        info.update(extra)
        mask = keep(cent)
    elif kind == "bra":
        keep, planes, pins, push, closure, cups, extra = bra_region(f, co, stree, cx, cy)
        info.update(extra)
        mask = keep(cent)
    elif kind == "tights":
        keep_v, planes, tband, legs_w, foot_w, extra = tights_region(f, co, w, arm, cx)
        info.update(extra)
        kd = _kd(co)
        cco = np.array([v.co for v in bm.verts])
        near = np.array([kd.find(Vector(p))[1] for p in cco])
        vk = keep_v(cco, legs_w[near], w["Hips"][near], foot_w[near])
        mask = np.array([all(vk[v.index] for v in fa.verts) for fa in bm.faces])
    else:
        sides, keep_v, planes, dist, extra = gloves_region(f, co, w, arm)
        info.update(extra)
        member_v = {s: v[3] for s, v in sides.items()}
        fing_v = {s: v[4] for s, v in sides.items()}
        hand_v = {s: v[5] for s, v in sides.items()}
        # the collider's vertices take the bone weights of their nearest body vertex
        kd = _kd(co)
        cco = np.array([v.co for v in bm.verts])
        near = np.array([kd.find(Vector(p))[1] for p in cco])
        pick = {s: m[near] for s, m in member_v.items()}, {s: m[near] for s, m in fing_v.items()}, \
            {s: m[near] for s, m in hand_v.items()}
        vk = keep_v(cco, *pick)
        if not vk.any():
            raise RuntimeError(f"gloves: no region (member>0.5: {[int((m > 0.5).sum()) for m in pick[0].values()]}, "
                               f"collider verts {len(cco)}, x range {cco[:, 0].min():.2f}..{cco[:, 0].max():.2f})")
        mask = np.array([all(vk[v.index] for v in fa.verts) for fa in bm.faces])
        fing_any = np.maximum(fing_v[1], fing_v[-1])
        hand_any = np.maximum(hand_v[1], hand_v[-1])
    for fa, k in zip(bm.faces, mask):
        fa[keep_layer] = int(bool(k))
    bmesh.ops.delete(bm, geom=[fa for fa in bm.faces if not fa[keep_layer]], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    # vertex attributes the planes / passes need, read before the cuts (new vertices take their edge's)
    for plane in planes:
        p, n = plane[0], plane[1]
        if len(plane) > 2:              # a plane of one arm cuts only that side's geometry
            sd = plane[2]
            geom = ([v for v in bm.verts if v.co.x * sd > 0] + [e for e in bm.edges if e.verts[0].co.x * sd > 0]
                    + [fa for fa in bm.faces if fa.calc_center_median().x * sd > 0])
        else:
            geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector(p), plane_no=Vector(n), clear_outer=True, dist=1e-5)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    # keep the largest connected parts only (a stray triangle cut off by the planes is no cloth)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    comp = {}
    seen = set()
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack, isl = [f0], []
        seen.add(f0.index)
        while stack:
            fa = stack.pop()
            isl.append(fa)
            for e in fa.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        comp[len(comp)] = isl
    sizes = sorted((len(v) for v in comp.values()), reverse=True)
    floor = max(30, int(0.02 * sizes[0])) if sizes else 0
    drop = [fa for isl in comp.values() if len(isl) < floor for fa in isl]
    info["islands"] = sum(1 for v in comp.values() if len(v) >= floor)
    info["dropped_faces"] = len(drop)
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    # orient outward: the mean of the face normals against the body's outward normal there
    vote = 0.0
    for fa in list(bm.faces)[:: max(1, len(bm.faces) // 500)]:
        loc, n, _i, _d = stree.find_nearest(fa.calc_center_median())
        if loc is not None:
            vote += fa.normal.dot(n)
    if vote < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        bm.normal_update()
    V = np.array([v.co for v in bm.verts])
    out = np.zeros((len(V), 3))
    for i, v in enumerate(bm.verts):
        loc, n, _f, _d = stree.find_nearest(v.co)
        out[i] = np.array(n) if loc is not None else np.array(v.normal)
    off = np.full(len(V), float(f["offset_m"]))
    movable = np.ones(len(V), bool)
    if kind == "gloves":
        fg = np.zeros(len(V))
        hd = np.zeros(len(V))
        # a vertex's finger / hand weight: its nearest body vertex's
        kd = _kd(co)
        for i, p in enumerate(V):
            j = kd.find(Vector(p))[1]
            fg[i], hd[i] = fing_any[j], hand_any[j]
        d = dist(V)
        off = np.where(fg > 0.5, float(f["finger_offset_m"]), off)
        if f["cuff"] != "none":
            near_edge = np.clip(1.0 - (float(f["reach_m"]) - d) / float(f["cuff_m"]), 0.0, 1.0)
            off += (float(f["cuff_flare_m"]) * near_edge ** 2 if f["cuff"] == "flared"
                    else float(f["cuff_fold_m"]) * (near_edge > 0))
        movable = fg <= 0.5                          # the fingers stay as they lie (no evening, no drape)
        pin_mask = (fg > 0.5) | (hd > 0.5) | (d > float(f["reach_m"]) - 0.015)
        if float(f.get("fit", 1.0)) <= TIGHT_GLOVE_FIT:
            # a tight glove is a second skin: nothing hangs, it is pinned whole (left free, the forearm tube of a
            # stiff elbow glove sagged in the T-pose and stretched to 1.38)
            pin_mask[:] = True
        info["finger_verts"] = int((fg > 0.5).sum())
    if kind == "tights":
        off = off + float(f["band_extra_m"]) * tband(V)
        pin_mask = np.ones(len(V), bool)                # hosiery is a second skin: pinned whole
    if kind == "bra":
        cl = closure(V)
        off = off + CLOSURE_M * cl
        wcup = push(V)
        pz, pin_, pout = f["push_m"]
        k = float(f["push"])
        if k > 0:
            sgn = np.where(V[:, 0] > cx, 1.0, -1.0)
            V[:, 2] += k * pz * wcup
            V[:, 0] -= sgn * k * pin_ * wcup
            V += out * (k * pout * wcup)[:, None]
        info["closure_verts"] = int(cl.sum())
    V = V + out * off[:, None]
    for v, p in zip(bm.verts, V):
        v.co = Vector(p)
    # evening and laying out alternate: an evening pass bridges a crease (the cleft of the seat, the groin) and pulls a
    # bulge in, laying out puts what went under the skin back to ``offset`` over it — the cloth spans the hollows
    for _round in range(ROUNDS):
        _umbrella(bm, SMOOTH_PASSES[kind], movable)
        _lay_out(bm, ctree, off, movable)
    if kind == "bra":
        # the cups bridge the breast's tip (cloth spans it; laid on it, the edges round the tip were 2.5 mm and the
        # drape stretched them to 1.33); a molded cup is a shell and gets more
        cm = cups(np.array([v.co for v in bm.verts])) & movable
        for _round in range(2):
            _umbrella(bm, MOLDED_PASSES if f.get("rigid_cups") else SMOOTH_PASSES["bra"], cm, boundary_only_along=True)
            _lay_out(bm, ctree, off, cm)
    V = np.array([v.co for v in bm.verts])
    if kind == "briefs":
        pin_mask = pins(V)
    elif kind == "bra":
        # the cups' rim is pinned as well (it holds the cut's line: an unpinned triangle rim stretched to 1.36)
        rim = np.array([v.is_boundary for v in bm.verts])
        tip = np.zeros(len(V), bool)
        for a in info["apex"].values():
            tip |= np.linalg.norm(V - np.array(a), axis=1) < TIP_PIN_M
        pin_mask = pins(V) | (rim & cups(V)) | (tip & cups(V))
    # planar UVs: front-facing faces on the left half, back-facing ones on the right (mirrored), x / z of the box
    lo, hi = V.min(0), V.max(0)
    uvl = bm.loops.layers.uv.new("UVMap")
    for fa in bm.faces:
        back = fa.normal.y > 0
        for lp in fa.loops:
            p = lp.vert.co
            u = (p.x - lo[0]) / max(1e-6, hi[0] - lo[0])
            u = 0.51 + 0.47 * (1.0 - u) if back else 0.02 + 0.47 * u
            lp[uvl].uv = (u, 0.02 + 0.96 * (p.z - lo[2]) / max(1e-6, hi[2] - lo[2]))
    mesh = bpy.data.meshes.new("template")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(prm["node"], mesh)
    bpy.context.scene.collection.objects.link(obj)
    thick = float(f["offset_m"]) - gd.BUILD_CLEAR_EXTRA_M
    info["clear"] = gd.clear_of_body(obj, ctree, thickness=thick)
    pin_mask = _pin_free_islands(mesh, pin_mask)
    pin = np.where(pin_mask)[0]
    info["verts"] = len(mesh.vertices)
    info["pinned_share"] = round(len(pin) / max(1, len(mesh.vertices)), 3)
    return obj, pin, info


def _outer_faces(cent, fnorm, arm):
    """Per face: whether it faces away from its nearest skeleton point (``gd.core_segments``) — the skin; a thick
    shell's inner wall faces in, toward the bones (``gd._drop_inner_walls``' rule)."""
    segs = gd.core_segments(arm, rest=True)
    q = np.concatenate([gd.axis_points(cent[k:k + 4000], segs) for k in range(0, len(cent), 4000)])
    return np.einsum("ij,ij->i", fnorm, cent - q) > 0


#: A selected face whose centroid lies this deep inside the rest collider is inner geometry, never cloth.
INSIDE_M = 0.004
#: Rounds of evening + laying out (``build_fitted``).
ROUNDS = 4


def _lay_out(bm, tree, off, movable):
    """Every movable vertex closer than its ``off`` to the skin (or under it) goes to ``off`` out along the outward
    direction at its nearest skin point (``gd.signed_out``)."""
    for v in bm.verts:
        if not movable[v.index]:
            continue
        loc, o = gd.signed_out(tree, v.co, 0.1)
        if loc is None:
            continue
        if (v.co - loc).dot(o) < off[v.index]:
            v.co = loc + o * float(off[v.index])


def _pin_free_islands(mesh, pin_mask):
    """A part of the piece with no pinned vertex would fall off in the cloth run: it is pinned whole (as laid)."""
    n = len(mesh.vertices)
    e = np.empty(len(mesh.edges) * 2, np.int64)
    mesh.edges.foreach_get("vertices", e)
    e = e.reshape(-1, 2)
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in e:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in range(n)])
    out = pin_mask.copy()
    for r in np.unique(roots):
        m = roots == r
        if not out[m].any():
            out[m] = True
    return out


def _kd(co):
    from mathutils.kdtree import KDTree
    kd = KDTree(len(co))
    for i, p in enumerate(co):
        kd.insert(Vector(p), i)
    kd.balance()
    return kd


#: Passes of the weight evening of a fitted piece (``even_weights``).
WEIGHT_PASSES = 10


def even_weights(obj, weight_matrix, write_weights):
    """A fitted piece lies on the skin, so every vertex keeps the nearest-face weights of the body — which jump
    where the cloth spans a gap the skin does not (the gusset between the thighs, the gore between the cups): a
    walk tore those edges. ``WEIGHT_PASSES`` passes move each vertex's weights half way to its neighbours' mean,
    then the four strongest are kept, normalised. Returns ``{passes}``."""
    names, W = weight_matrix(obj)
    E = gd.edges_of(obj)
    n = len(W)
    deg = np.bincount(E.ravel(), minlength=n).astype(float)
    S = W.copy()
    for _ in range(WEIGHT_PASSES):
        acc = np.zeros_like(S)
        np.add.at(acc, E[:, 0], S[E[:, 1]])
        np.add.at(acc, E[:, 1], S[E[:, 0]])
        S = 0.5 * S + 0.5 * acc / np.maximum(deg, 1.0)[:, None]
    order = np.argsort(-S, axis=1)[:, 4:]
    np.put_along_axis(S, order, 0.0, axis=1)
    S /= np.maximum(S.sum(1, keepdims=True), 1e-9)
    write_weights(obj, S)
    return {"passes": WEIGHT_PASSES}


def part_cover(body, piece, reach=0.06):
    """Briefs: the share of the procedural parts' vertices (and of the crotch skin within 3 cm of the centre line
    under the waistband) that the piece covers — a ray out along the outward body normal meets the piece within
    ``reach``. ``{part_verts, part_covered, crotch_verts, crotch_covered}``."""
    co, nrm, _t = gd.body_state(body)
    pf = _part_faces(body)
    pv = set()
    for poly, is_part in zip(body.data.polygons, pf):
        if is_part:
            pv.update(poly.vertices)
    gco, _gn, gtri = gd.world_coords(piece)
    gb = gd.bvh_of(gco, gtri)

    def share(idx):
        hit = 0
        for i in idx:
            o = Vector(co[i]) + Vector(nrm[i]) * 0.0005
            if gb.ray_cast(o, Vector(nrm[i]), reach)[0] is not None:
                hit += 1
        return hit
    pv = sorted(pv)
    lo, hi = gco.min(0), gco.max(0)
    cx = float((lo[0] + hi[0]) / 2)
    crotch = [i for i in range(len(co)) if abs(co[i][0] - cx) < 0.03 and lo[2] - 0.01 < co[i][2] < lo[2] + 0.06]
    return {"part_verts": len(pv), "part_covered": share(pv), "crotch_verts": len(crotch),
            "crotch_covered": share(crotch)}
