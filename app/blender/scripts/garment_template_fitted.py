"""A223 — the fitted garment templates (briefs, bra, gloves): cut from the plain body's own surface.

Called by ``garment_template_build.run`` for a ``spec["fitted"]`` (``app.core.garment_template.fitted_spec``; glTF
Y-up metres there, Blender Z-up here: glTF y = Blender z, glTF z = -Blender y, the front is -Y, the character's left
+X). A close-fitting piece is not wrapped from panel rows: the faces of the body's region are copied (rest pose,
consistent outward winding), cut clean where the edge is a plane (``bmesh.ops.bisect_plane``: a waistband, a cuff,
the band's lower edge), the holes left by a procedural part's faces (an inset part, ``attached_part``) are closed,
every vertex is laid ``offset_m`` out along the outward body normal, the surface is evened (umbrella passes, a border
only along the border, so a cut through the triangles loses its zigzag) and laid out of the rest collider. The
caller then pins the returned vertices and runs the short cloth relax (``frames``).

The crotch every leg line and hem is measured from (``_crotch``, A239) is where the body closes over the centre
line between the thighs — the highest of the per-column lowest hits of upward rays at the centre — never lower than
the lowest Hips-weighted vertex near the centre (a part rigged to the hips stays covered).

* briefs: waistband plane at ``top_y``; the leg opening per face centroid: under the gusset (|x| < gusset half width)
  the crotch less 5 mm, rising to ``top - side_width`` at the hip's side over a curve shaped by ``leg_cut``; on the
  back the full-height part reaches ``back_coverage`` of the way to the side. Pinned: the waistband and the gusset.
  A235 ``sides`` "string": the leg line reaches the hip band (``string_width_m`` under ``top_y``) at the panels' top
  corners (``string_corner``, ``garment_template.STRING_CORNER``) — past them only that band runs round the hips; the bands are pinned too.
  A232 boxers (``leg_length_m`` > 0): the hips and both thighs from ``top_y`` to a straight hem ``leg_length_m`` under
  the crotch (``boxer_region``, the tights' per-vertex way: no arm / hand); pinned the waistband and — ``hem_pinned``
  (snug) — a band at each hem and the gusset; a loose boxer hangs from its waistband.
* trousers (A233): the hips and both legs from the waistband plane at ``top_y`` to a hem plane per length (``trouser_hem``
  of the side's crotch / knee / ankle; a stirrup keeps a band under the arch instead), no arm / hand and no foot; laid
  out at ``offset_m`` like every fitted piece, then each leg is widened round its bone axis (hip -> knee -> ankle
  joint) to the leg shape's radius (``trouser_widen``) and evened once more; then the seat (bug round 2026-11-20,
  ``trouser_seat``): a regular / relaxed seat bridges each slice to its convex hull and eases it out, the skin facing
  up or down and the legs under the crotch follow that move smoothly — a fitted seat stays a second skin. Pinned
  (taken after the seat): the waist band, the centre seam over the crotch (a bridged seat's from
  ``SEAT_SEAM_LIFT_M`` over it) and — skinny — a band at each hem (a stirrup: whole, a second skin, its seat always
  fitted); a widened leg hangs from the waist band.
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
from mathutils.bvhtree import BVHTree

import fitted_pattern as fpat
import garment_template_drape as gd

#: Umbrella passes of the evening (fitted kinds), and the extra ones of a molded cup (it bridges the bust).
SMOOTH_PASSES = {"briefs": 6, "bra": 6, "gloves": 2, "tights": 6, "trousers": 6}
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
#: Round 2026-11-25 (owner ruling 1): a bra's strap is its own regular strip along its path (``strap_strip``) — the
#: path's loops cut out (a point back within STRIP_LOOP_M of an earlier one), resampled every STRIP_STEP_M, evened
#: STRIP_SMOOTH times, STRIP_ACROSS quads across its width; it reaches STRIP_END_M past the path's back end into the
#: band and lies STRIP_LIFT_M over the cloth it overlaps there (a cross-back strap's second strip once more over the
#: first); the cup's push-up lifts it along, fading out over STRIP_PUSH_FADE_M from the cup.
STRIP_STEP_M = 0.005
STRIP_SMOOTH = 40
STRIP_LOOP_M = 0.004
STRIP_ACROSS = 4
STRIP_END_M = 0.012
STRIP_LIFT_M = 0.0025
STRIP_PUSH_FADE_M = 0.12
#: ... and its front end starts this far under the cup's top edge (sewn onto the cup).
STRIP_INTO_CUP_M = 0.015
#: Round 2026-11-25 (owner ruling 6): a cup reaches at most CUP_OUT_M out from its apex, and per height only as far
#: as its cloth stays inside the body's outline seen from behind (``_side_reach``, CUP_REACH_ROWS heights from the
#: fold to over the cup's top, CUP_SIL_MARGIN_M inside the torso's widest point, the cloth laid out ``offset_m`` +
#: CUP_SIL_THICK_M; the torso is what lies nearer the middle than CUP_ARM_X_M): a cup over the breast's side stood
#: past the torso outline in the back view — a dark crescent each side. The push-up fades out over the outer
#: CUP_PUSH_FADE of that reach, so the cup's side edge lies on the body instead of lifted off it.
CUP_OUT_M = 0.075
CUP_MIN_REACH_M = 0.02
CUP_REACH_ROWS = 9
CUP_SIL_MARGIN_M = 0.002
CUP_SIL_THICK_M = 0.001
CUP_ARM_X_M = 0.21
CUP_PUSH_FADE = 0.35
#: The push-up's draw toward the middle fades in over this distance from the gore's edge.
GORE_PUSH_FADE_M = 0.025
CUP_REACH_STEP_M = 0.004


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

#: A239: the crotch is looked for on the centre plane and up to this far either side of it (Spine1's x lies a few mm
#: off the middle of the gap between the thighs on a generated body), in steps of CROTCH_STEP_M ...
CROTCH_SLIT_M = 0.005
CROTCH_STEP_M = 0.001
#: ... and from this far under the Hips-weight rule's height, from the front to the back of that rule's vertices.
CROTCH_BELOW_M = 0.03


def _crotch(co, w_hips, cx, top, tree):
    """The crotch height: the lowest vertex within 3 cm of the centre line with Hips weight > 0.3 below the
    waistband (``garment_fit.crotch_height``'s rule; a procedural part rigged to the hips counts — it is covered),
    raised to where the body closes over the centre line (A239). The Hips weight reaches several cm down the inner
    thighs where they stand apart (Kira 0.742 vs 0.819, Glut 0.737 vs 0.811), so a gusset cut from that height was a
    tongue of thigh skin between the legs. The closing point: per ray column (x within ``cx`` +- ``CROTCH_SLIT_M``,
    cast straight up at 5 mm steps in y) its lowest hit, and of those the HIGHEST — the column that lies in the gap.
    A column at the slit's edge may graze an inner thigh where the gap is narrow or off ``cx`` (Ylva 0.790 against
    0.859, Rosi 0.715 against 0.789); the lowest of all hits was that thigh. Touching thighs or a part hanging lower
    than the rule (a male bulge) keep the rule's height — the result is never lower than it."""
    m = (np.abs(co[:, 0] - cx) < 0.03) & (w_hips > 0.3) & (co[:, 2] < top)
    if not m.any():
        return top - 0.2
    rule = float(co[m, 2].min())
    start = rule - CROTCH_BELOW_M
    y0, y1 = float(co[m, 1].min()), float(co[m, 1].max())
    lowest = []
    n_x = int(round(2 * CROTCH_SLIT_M / CROTCH_STEP_M)) + 1
    for x in np.linspace(cx - CROTCH_SLIT_M, cx + CROTCH_SLIT_M, n_x):
        hits = []
        for y in np.arange(y0, y1 + 1e-9, 0.005):
            h = _ray(tree, (float(x), float(y), start), (0, 0, 1), top - start)
            if h is not None:
                hits.append(float(h[2]))
        if hits:
            lowest.append(min(hits))
    return max(rule, max(lowest)) if lowest else rule


def briefs_region(f, co, w, cx, cy, tree):
    """``(face keep predicate on centroids, planes, info)`` of briefs."""
    top = _gltf_y(f["top_y"])
    crotch = _crotch(co, w["Hips"], cx, top, tree)
    cy = _mid_y(co, cx, (crotch + top) / 2)
    near = (co[:, 2] < top) & (co[:, 2] > crotch - 0.05)
    hip_half = float(np.percentile(np.abs(co[near, 0] - cx), 99)) if near.any() else 0.17
    g = float(f["gusset_half_m"])
    base = crotch - 0.005
    side = top - float(f["side_width_m"])
    lc = float(f["leg_cut"])
    low_side = crotch - float(f["boyshort_drop_m"])
    # a high cut rises soon past the gusset, a boyshort stays low; past leg_cut 1 (step 3a, D8) the line meets the
    # side's height ``reach`` from the centre instead of at the hip's side (``garment_template.brief_leg_shape``)
    share = min(lc, 1.0)
    power = max(0.4, 1.6 - 1.2 * share)
    reach_f = hip_half - max(lc - 1.0, 0.0) / 0.5 * float(f.get("high_leg", 0.6)) * (hip_half - g)
    l_side = low_side + share * (side - low_side)
    bc = float(f["back_coverage"])
    w_back = g * 0.4 + bc * 0.9 * (hip_half - g * 0.4)
    string = f.get("sides") == "string"
    if string:
        # A235: a string brief — the leg line climbs to the hip band (``string_width_m`` under the waist line) at the
        # panels' top corners; past them only the band runs round the hips
        sw = float(f["string_width_m"])
        l_side = top - sw
        c_min, c_span = (float(v) for v in f["string_corner"])
        corner_f = g + (reach_f - g) * (c_min + c_span * (1.0 - share))
        corner_b = w_back + (hip_half - w_back) * c_min

    def leg_line(ax, back):
        wid = np.where(back, w_back, g)
        reach = np.where(back, corner_b, corner_f) if string else np.where(back, hip_half, reach_f)
        t = np.clip((ax - wid) / np.maximum(reach - wid, 1e-3), 0.0, 1.0)
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
        m = (v[:, 2] > top - band - 0.002) | ((ax < g) & (v[:, 2] < crotch + 0.03))
        if string:
            # A235: the hip bands are pinned whole (a band of a few mm has no cloth to relax)
            m |= (v[:, 2] > top - sw - 0.002) & (ax > corner_f * 0.9)
        return m

    info = {"cy": cy, "crotch_z": round(crotch, 4), "hip_half_m": round(hip_half, 4),
            "leg_side_z": round(l_side, 4), "back_width_m": round(w_back, 4)}
    if string:
        info.update(sides="string", corner_front_m=round(corner_f, 4), corner_back_m=round(corner_b, 4))
    return keep, planes, pins, info


def boxer_region(f, co, w, cx, tree):
    """A232 boxers: ``(keep_v(v, arm_v), planes, pins(v), info)`` — every collider vertex from the waistband down to
    the hem ``leg_length_m`` under the crotch that is not an arm's / hand's (an A-pose hand hangs beside the thigh);
    the hem is one horizontal plane (both legs at the same height in the rest pose)."""
    top = _gltf_y(f["top_y"])
    crotch = _crotch(co, w["Hips"], cx, top, tree)
    hem = crotch - float(f["leg_length_m"])
    band = float(f["band_m"])
    g = float(f["gusset_half_m"])
    hem_pin = float(f["hem_pin_m"]) if f.get("hem_pinned") else 0.0

    def keep_v(v, arm_v):
        return (arm_v < 0.5) & (v[:, 2] <= top + 0.005) & (v[:, 2] >= hem - 0.005)

    planes = [(np.array([0.0, 0.0, top]), np.array([0.0, 0.0, 1.0])),
              (np.array([0.0, 0.0, hem]), np.array([0.0, 0.0, -1.0]))]

    def pins(v):
        m = v[:, 2] > top - band - 0.002
        if hem_pin > 0:
            m |= v[:, 2] < hem + hem_pin
            m |= (np.abs(v[:, 0] - cx) < g) & (np.abs(v[:, 2] - crotch) < 0.03)
        return m

    return keep_v, planes, pins, {"crotch_z": round(crotch, 4), "hem_z": round(hem, 4),
                                  "hem_pinned": bool(hem_pin > 0)}


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


def _side_reach(tree, co, apex, s, cx, cy, zs, off):
    """Owner ruling 6: per height of ``zs`` how far out from ``apex`` (to side ``s``) the cup may reach, so that its
    cloth (``off`` along the outward normal) stays inside the body's outline seen from behind: rays from the front
    every CUP_REACH_STEP_M outward; the first one that misses the body, whose hit laid ``off`` out stands past the
    torso's widest point at that height (``co`` within 5 mm of it, nearer the middle than the arms) less
    CUP_SIL_MARGIN_M, or from which a ray straight back meets no body (a camera behind would see the cloth there)
    ends the reach (at most CUP_OUT_M, at least CUP_MIN_REACH_M)."""
    out = []
    for z in zs:
        band = co[(np.abs(co[:, 2] - z) < 0.005) & (s * (co[:, 0] - cx) > 0) & (s * (co[:, 0] - cx) < CUP_ARM_X_M)]
        wide = float(np.max(s * (band[:, 0] - cx))) if len(band) else 9.0
        d, reach = 0.0, CUP_OUT_M
        while d < CUP_OUT_M:
            x = float(apex[0]) + s * d
            hit = tree.ray_cast(Vector((x, cy - 0.6, float(z))), Vector((0.0, 1.0, 0.0)), 1.0)
            if hit[0] is None or s * (float(hit[0][0] + hit[1][0] * off) - cx) > wide - CUP_SIL_MARGIN_M:
                reach = d - CUP_REACH_STEP_M
                break
            cloth = hit[0] + hit[1] * off
            if tree.ray_cast(cloth + Vector((0.0, 0.001, 0.0)), Vector((0.0, 1.0, 0.0)), 1.0)[0] is None:
                reach = d - CUP_REACH_STEP_M          # a camera straight behind would see the cloth here
                break
            d += CUP_REACH_STEP_M
        out.append(max(CUP_MIN_REACH_M, reach))
    return np.array(out)


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
    if f.get("hem_y") is not None:
        # round 2026-11-25: a top with cups — its band runs from the fold found here down to the top's hem (an
        # absolute height, ``garment_template.fitted_spec``); a bra has no ``hem_y`` and keeps the band above
        band = max(under - _gltf_y(f["hem_y"]), float(f["back_strap_m"]))
    info = {"apex": {("l" if s > 0 else "r"): [round(float(x), 4) for x in a] for s, a in apex.items()},
            "under_z": round(under, 4), **info_fold}
    tops = {}
    for s, a in apex.items():
        H = max(0.03, float(a[2]) - under)
        zc = float(a[2]) + (cov - 0.5) * 2.0 * H
        r_in = max(0.02, abs(float(a[0]) - cx) - gore_half)
        zs = np.linspace(under, max(zc, float(a[2])), CUP_REACH_ROWS)
        r_out = (zs, _side_reach(tree, co, a, s, cx, cy, zs, float(f["offset_m"]) + CUP_SIL_THICK_M))
        tops[s] = (a, H, zc, r_in, r_out)
    info["cup_reach_m"] = {("l" if s > 0 else "r"): [round(float(r), 3) for r in t[4][1]] for s, t in tops.items()}

    def reach_at(s, z):
        zs, rs = tops[s][4]
        return np.interp(z, zs, rs)

    def cup_top(c, s):
        a, H, zc, r_in, r_out = tops[s]
        dx = c[:, 0] - a[0]
        r = np.where(s * dx < 0, r_in, reach_at(s, c[:, 2]))
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
        # owner ruling 6: a cup lies on what the front sees — the torso's side under the breast's overhang (the same x,
        # further back) is no cup (it was a loose lobe under the arm, its own island)
        for k in np.where(out)[0]:
            if tree.ray_cast(Vector(c[k]) + Vector((0.0, -0.002, 0.0)), Vector((0.0, -1.0, 0.0)), 0.5)[0] is not None:
                out[k] = False
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
            start = np.array([a[0] + s * 0.005, a[1], float(zt[0]) - STRIP_INTO_CUP_M])
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
        # owner ruling 1: the straps are no body faces any more — each is its own strip (``strap_strip``)
        return (band_ring(c) & (c[:, 2] >= under - band - 0.01)) | cups(c) | gore(c)

    planes = [(np.array([0.0, 0.0, under - band]), np.array([0.0, 0.0, -1.0]))]

    def pins(v):
        p = (v[:, 2] <= under + 0.003) | gore(v)
        if f.get("rigid_cups") or style == "bandeau":
            p |= cups(v)
        return p

    def push(v):
        """Per vertex the weight of the push-up (dz, dx toward the centre, out): 1 inside a cup, fading to 0 over the
        outer ``CUP_PUSH_FADE`` share of the cup's reach toward its side edge (owner ruling 6: the edge lies on the
        body, not lifted off it), 0 outside."""
        if style == "bandeau":
            return np.zeros(len(v))
        w = cups(v).astype(float)
        for s, (a, _H, _zc, _ri, _r) in tops.items():
            m = s * (v[:, 0] - a[0]) > 0
            u = np.clip((np.abs(v[m, 0] - a[0]) / reach_at(s, v[m, 2]) - (1.0 - CUP_PUSH_FADE)) / CUP_PUSH_FADE,
                        0.0, 1.0)
            w[m] *= 1.0 - u * u * (3.0 - 2.0 * u)
        return w

    def closure(v):
        if f["closure"] == "back_hook":
            return (v[:, 1] > cy) & (np.abs(v[:, 0] - cx) < CLOSURE_HALF_M) & (v[:, 2] <= under + 0.003)
        if f["closure"] == "front":
            return (v[:, 1] < cy) & (np.abs(v[:, 0] - cx) < gore_half + 0.004) & (v[:, 2] <= under + gore_h)
        return np.zeros(len(v), bool)

    info["band_m"] = round(band, 4)
    # step 3a: the predicates the pattern parts are taken by (``fitted_pattern.pre_parts``); popped by build_fitted
    info["_pattern"] = {"pred": {"cups": cups, "gore": gore, "straps": lambda c: np.zeros(len(c), bool),
                                 "band": lambda c: band_ring(c) & (c[:, 2] >= under - band - 0.01)},
                        "strap_paths": [p for p in paths if len(p) > 1],
                        "strap_sides": [s for (s, _a), p in zip(apex.items(), paths) if len(p) > 1]}
    info["_tack"] = gore   # laid on the breastbone after the evening (``build_fitted``)
    info["_strips"] = {"paths": [p for p in paths if len(p) > 1],
                       "sides": [s for (s, _a), p in zip(apex.items(), paths) if len(p) > 1],
                       "width_m": float(st["width_m"]) if st else 0.0, "cross": bool(st and st["style"] == "cross"),
                       "extend_end": bool(st and st["style"] != "halter")}
    return keep, planes, pins, push, closure, cups, info


def _strip_path(path, tree, extend_end):
    """A strap path made even for its strip: extended ``STRIP_END_M`` past its back end (into the band), its loops cut
    out (``STRIP_LOOP_M``), resampled
    every ``STRIP_STEP_M`` by arc length, evened ``STRIP_SMOOTH`` times (the ends stay) and put back on the body."""
    P = np.asarray(path, float)
    if extend_end and len(P) > 1:
        d = P[-1] - P[-2]
        d = d / max(1e-9, float(np.linalg.norm(d)))
        loc, _n, _i, _d = tree.find_nearest(Vector(P[-1] + d * STRIP_END_M))
        if loc is not None:
            P = np.vstack([P, np.array(loc)])
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    keep = np.concatenate([[True], seg > 1e-6])
    P = P[keep]
    # a loop is cut out: the path's sections meet with an overlap (over the shoulder it ran down the back past where
    # the back section starts, which then went up again — a fold in the strip), so where a later point comes back
    # within STRIP_LOOP_M of an earlier one, every point between them goes
    out, i = [], 0
    while i < len(P):
        out.append(P[i])
        d = np.linalg.norm(P[i + 2:] - P[i], axis=1)
        back = np.where(d < STRIP_LOOP_M)[0]
        i = i + 2 + int(back[-1]) + 1 if len(back) else i + 1
    P = np.array(out)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    n = max(2, int(round(cum[-1] / STRIP_STEP_M)) + 1)
    t = np.linspace(0.0, cum[-1], n)
    Q = np.stack([np.interp(t, cum, P[:, k]) for k in range(3)], axis=1)
    for _ in range(STRIP_SMOOTH):
        Q[1:-1] = 0.25 * Q[:-2] + 0.5 * Q[1:-1] + 0.25 * Q[2:]
        for k in range(1, len(Q) - 1):
            loc, _n, _i, _d = tree.find_nearest(Vector(Q[k]))
            if loc is not None:
                Q[k] = np.array(loc)
    return Q


def strap_strip(bm, path, width, tree, extend_end):
    """Owner ruling 1 (round 2026-11-25): one strap as its own regular strip in ``bm`` — rows across the evened path
    (``_strip_path``), ``STRIP_ACROSS`` + 1 vertices across its ``width`` along the body (each put back on the body),
    two triangles per cell wound outward (the body normal of ``tree``, outward). Returns the new faces and vertices: a
    straight edge and an even surface in the cloth, so in the pattern too (the straps cut from the body's faces
    followed its triangles: a wavy surface and a sawtooth edge)."""
    Q = _strip_path(path, tree, extend_end)
    rows = []
    for i, p in enumerate(Q):
        t = Q[min(i + 1, len(Q) - 1)] - Q[max(i - 1, 0)]
        t = t / max(1e-9, float(np.linalg.norm(t)))
        _loc, nrm, _f, _d = tree.find_nearest(Vector(p))
        nv = np.array(nrm) if nrm is not None else np.array([0.0, -1.0, 0.0])
        b = np.cross(t, nv)
        b = b / max(1e-9, float(np.linalg.norm(b)))
        row = []
        for k in range(STRIP_ACROSS + 1):
            q = p + b * width * (k / STRIP_ACROSS - 0.5)
            loc, _n, _f2, _d2 = tree.find_nearest(Vector(q))
            row.append(bm.verts.new(Vector(loc) if loc is not None else Vector(q)))
        rows.append((row, nv))
    faces = []
    for i in range(len(rows) - 1):
        (a, na), b_ = rows[i], rows[i + 1][0]
        for k in range(STRIP_ACROSS):
            for tri in ((a[k], b_[k], b_[k + 1]), (a[k], b_[k + 1], a[k + 1])):
                e1, e2 = tri[1].co - tri[0].co, tri[2].co - tri[0].co
                if e1.cross(e2).dot(Vector(na)) < 0:
                    tri = (tri[0], tri[2], tri[1])
                faces.append(bm.faces.new(tri))
    return faces, [row for row, _n in rows]


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


def tights_region(f, co, w, arm, cx, tree):
    """A223 tights: ``(keep_v on collider vertices with their nearest body vertex's weights, planes, band(v), info)``.
    Full tights take the hips and both legs up to ``top_y``; a stocking / sock is per leg up to its top (a horizontal
    plane per side: under the crotch, under the knee). The foot: closed, footless (cut at the ankle joint) or a stirrup
    (footless + a band round the middle of the foot)."""
    style = f["style"]
    crotch = _crotch(co, w["Hips"], cx, _gltf_y(f["top_y"]) if f.get("top_y") else 2.0, tree)
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


def trouser_hem(rule, anchors):
    """A233: ``garment_template.trouser_hem`` — from + share x (to - from) + extra over the side's anchors."""
    a, b, share, extra = rule
    return float(anchors[a]) + float(share) * (float(anchors[b]) - float(anchors[a])) + float(extra)


def trousers_region(f, co, w, arm, cx, tree):
    """A233 trousers: ``(keep_v(v, arm_v, foot_v), planes, pins(v), sides, info)`` — every collider vertex between the
    waistband plane and the side's hem that is not an arm's / hand's (as the boxers) and not the foot's (below the
    ankle joint less 1 cm; a stirrup keeps a 5 cm band under the middle of the foot). ``sides[s]`` = the side's
    crotch / knee / ankle anchors, hem and leg axis (hip, knee, ankle joints)."""
    top = _gltf_y(f["top_y"])
    crotch = _crotch(co, w["Hips"], cx, top, tree)
    stirrup = f["hem"] == "stirrup"
    sides = {}
    for side, s in (("Left", 1), ("Right", -1)):
        hip, knee, ankle, toe = (_bone_head(arm, side + b) for b in ("UpLeg", "Leg", "Foot", "ToeBase"))
        anchors = {"crotch": crotch, "knee": float(knee[2]), "ankle": float(ankle[2])}
        sides[s] = {"hem": trouser_hem(f["hem_rule"], anchors), "axis": [hip, knee, ankle], "ankle_p": ankle,
                    "toe": toe, **anchors}

    def side_of(v):
        return np.where(v[:, 0] > cx, 1, -1)

    def keep_v(v, arm_v, foot_v):
        sd = side_of(v)
        hem = np.where(sd > 0, sides[1]["hem"], sides[-1]["hem"])
        ank = np.where(sd > 0, sides[1]["ankle"], sides[-1]["ankle"])
        k = (arm_v < 0.5) & (v[:, 2] <= top + 0.005)
        foot = (foot_v > 0.5) & (v[:, 2] < ank - 0.01)
        if stirrup:
            mid = np.where(sd[:, None] > 0, (sides[1]["ankle_p"] + sides[1]["toe"]) / 2,
                           (sides[-1]["ankle_p"] + sides[-1]["toe"]) / 2)
            foot &= ~(np.abs(v[:, 1] - mid[:, 1]) < 0.025)
        else:
            k &= v[:, 2] >= hem - 0.005
        return k & ~foot

    planes = [(np.array([0.0, 0.0, top]), np.array([0.0, 0.0, 1.0]))]
    if not stirrup:
        for s_, d in sides.items():
            planes.append((np.array([0.0, 0.0, d["hem"]]), np.array([0.0, 0.0, -1.0]), s_))
    band = float(f["band_m"])
    hem_pin = float(f["hem_pin_m"]) if f.get("hem_pinned") else 0.0

    def pins(v):
        if stirrup:
            # stirrup leggings are a second skin, pinned whole as hosiery (the leg's foot edge follows the foot
            # weights, not a plane: left free above it, one edge at the Achilles tendon stretched to 1.34)
            return np.ones(len(v), bool)
        m = v[:, 2] > top - band - 0.002
        if hem_pin > 0:
            sd = side_of(v)
            hem = np.where(sd > 0, sides[1]["hem"], sides[-1]["hem"])
            m |= v[:, 2] < hem + hem_pin
        return m

    info = {"crotch_z": round(crotch, 4), "hems": {str(s_): round(d["hem"], 4) for s_, d in sides.items()}}
    return keep_v, planes, pins, sides, info


def _polyline_foot(p, pts):
    """Per point of ``p`` (n, 3): its nearest point on the polyline ``pts``."""
    best = np.zeros_like(p)
    dist = np.full(len(p), 9.0)
    for a, b in zip(pts[:-1], pts[1:]):
        ab = b - a
        t = np.clip(((p - a) @ ab) / max(1e-12, ab @ ab), 0.0, 1.0)
        q = a + t[:, None] * ab
        d = np.linalg.norm(p - q, axis=1)
        m = d < dist
        best[m], dist[m] = q[m], d[m]
    return best


def trouser_widen(V, f, sides, cx):
    """A233: each leg widened round its bone axis (hip -> knee -> ankle joint) — a vertex below the crotch moves out
    along its radial direction to max(its radius, R(z)), faded in over ``ramp_m`` under the crotch. R runs straight
    (in z) from the thigh radius ``r_t`` at the crotch to ``shape_r[0] x r_t`` at the knee and ``shape_r[1] x r_t`` at
    the ankle; ``r_t`` = the median radius of the side's vertices 2-4 cm under the crotch x (1 + ``radial_ease``). An
    inner side stays ``centre_gap_m`` off the centre plane. A cuffed hem stands ``cuff_fold_m`` further out over
    ``cuff_m``. Returns ``(V, info)``."""
    V = V.copy()
    info = {}
    for s_, d in sides.items():
        side = (V[:, 0] - cx) * s_ > 0
        if not side.any():
            continue
        q = _polyline_foot(V[side], np.array(d["axis"]))
        r = V[side] - q
        rl = np.maximum(np.linalg.norm(r, axis=1), 1e-6)
        z = V[side][:, 2]
        new = rl.copy()
        if f.get("shape_r"):
            band = (z < d["crotch"] - 0.02) & (z > d["crotch"] - 0.04)
            r_t = float(np.median(rl[band])) if band.sum() > 5 else 0.08
            r_t *= 1.0 + float(f["radial_ease"])
            k, h = f["shape_r"]
            zs = [d["ankle"], d["knee"], d["crotch"]]
            R = np.interp(z, zs, [h * r_t, k * r_t, r_t])
            t = np.clip((d["crotch"] - z) / float(f["ramp_m"]), 0.0, 1.0)
            new = np.maximum(rl, rl + t * (R - rl))
            info[str(s_)] = {"r_t": round(r_t, 4), "r_knee": round(k * r_t, 4), "r_ankle": round(h * r_t, 4),
                             "widened_p50_mm": round(float(np.median(new - rl)) * 1000, 1)}
        if f["hem"] == "cuffed":
            new = new + float(f["cuff_fold_m"]) * (z < d["hem"] + float(f["cuff_m"]))
        P = q + r / rl[:, None] * new[:, None]
        moved = new > rl + 1e-6
        gap = float(f["centre_gap_m"])
        inner = moved & ((P[:, 0] - cx) * s_ < gap)
        P[inner, 0] = cx + s_ * gap
        V[side] = P
    return V, info


def _hull2(P):
    """The 2D convex hull of the points ``P`` (n, 2), counter-clockwise (Andrew's monotone chain)."""
    pts = sorted(set(map(tuple, np.round(P, 6))))
    if len(pts) < 3:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return np.array(lo[:-1] + hi[:-1])


def _ray_to_hull(c, P, H):
    """Per point of ``P`` (n, 2): where the ray from ``c`` (one point, or one per point) through it leaves the convex
    polygon ``H`` (``c`` inside; a ray that meets no edge keeps its point)."""
    c = np.broadcast_to(np.asarray(c, float), P.shape)
    d = P - c
    dl = np.maximum(np.linalg.norm(d, axis=1), 1e-9)
    d = d / dl[:, None]
    a, b = H, np.roll(H, -1, axis=0)
    e = b - a
    best = np.full(len(P), np.inf)
    for (ax, ay), (ex, ey) in zip(a, e):
        den = d[:, 0] * ey - d[:, 1] * ex
        ok = np.abs(den) > 1e-12
        wx, wy = ax - c[:, 0], ay - c[:, 1]
        t = np.where(ok, (wx * ey - wy * ex) / np.where(ok, den, 1.0), np.inf)
        u = np.where(ok, (wx * d[:, 1] - wy * d[:, 0]) / np.where(ok, den, 1.0), -1.0)
        hit = ok & (t > 0) & (u >= -1e-9) & (u <= 1 + 1e-9)
        best = np.where(hit & (t < best), t, best)
    best = np.where(np.isfinite(best), best, dl)
    return c + d * best[:, None]


def _on_hulls(P, C, ids, hulls):
    """Per point of ``P`` (n, 2): where the ray from its centre ``C[i]`` through it leaves its hull
    ``hulls[ids[i]]``."""
    out = P.copy()
    for h in np.unique(ids):
        m = ids == h
        out[m] = _ray_to_hull(C[m], P[m], hulls[h])
    return out


def trouser_seat(V, N, E, f, cx, crotch, top, band_lo):
    """Bug round 2026-11-20 (review fix) — the seat of a trouser (``f["seat"]``: ``garment_template.seat_spec``). A
    trouser is not a second skin above the crotch. On the laid-out cut (``V``, its vertex normals ``N``, its edges
    ``E``), BEFORE the pins are taken (the A237 centre seam is then held as shaped):

    * bridge + ease, above the crotch: per horizontal slice up to the top edge (``slice_m`` thick, its hull read over
      ``hull_m`` of the laid-out cut) the slice's 2D convex hull, scaled about its centroid so the slice's median
      radius grows by ``ease_m`` (0 at the waistband's lower edge ``band_lo``, full ``ramp_m`` under it; the band
      itself is bridged, never eased). A ring vertex's target is on the ray from the centroid, at the hulls of the
      two slices round its height blended by it — the cloth spans the seat's cleft, the groin and the small of the
      back. The targets are approached by ``relax_passes`` rounds of an evening
      along each slice (umbrella, horizontal only) followed by putting every ring vertex back on its target radius:
      a vertex in the cleft slides along the hull instead of landing on the point its neighbours land on;
    * the fill: skin facing up or down (``|n_z|`` over ``FLAT_NZ``: under the seat, the top of the hip, between the
      legs at the crotch) has no ray from its slice's centre and is no ring vertex, and the legs under the crotch are
      no slice at all. Their horizontal MOVE is the mean of their neighbours' (``fill_passes`` Jacobi rounds,
      harmonic): it follows the ring vertices round it and fades to 0 at ``fade_m`` under the crotch, where the leg
      is as laid. Left as laid (the first version), each such patch was a step against the moved ring next to it —
      the folds over the crotch, round the thighs and over the small of the back.

    Returns ``(V, info)``; a fitted seat returns V untouched."""
    st = f.get("seat") or {}
    ease, bridge = float(st.get("ease_m") or 0.0), bool(st.get("bridge"))
    info = {"name": st.get("name"), "ease_m": ease, "bridge": bridge}
    if not bridge:
        return V, info
    V0 = V
    z = V0[:, 2]
    ring_ok = np.abs(N[:, 2]) <= FLAT_NZ
    above = (z > crotch) & (z <= top + 1e-4)
    step, half, ramp_e = float(st["slice_m"]), float(st["hull_m"]), float(st["ramp_m"])
    rows = []               # per slice: (its mid z, its centroid, its hull eased)
    for z0 in np.arange(crotch, top + step, step):
        zc = z0 + step / 2
        ring = above & ring_ok & (np.abs(z - zc) < half)
        if not ring.any():
            continue
        H = _hull2(V0[ring][:, :2])
        if len(H) < 3:
            continue
        c = H.mean(0)
        R = float(np.median(np.linalg.norm(V0[ring][:, :2] - c, axis=1)))
        k = ease * float(np.clip((band_lo - zc) / ramp_e, 0.0, 1.0)) / max(R, 1e-3)
        rows.append((zc, c, c + (H - c) * (1.0 + k)))
    info["slices"] = len(rows)
    hulls = [Hk for _zc, _c, Hk in rows]
    move = above & ring_ok & bool(rows)
    idx = np.where(move)[0]
    # a ring vertex's target lies between the two slices round its height, blended by it: a vertex is never put on
    # its slice's hull alone (each slice a vertical band, a step to the next — a staircase of folds over the back)
    zcs = np.array([r[0] for r in rows]) if rows else np.zeros(1)
    cs = np.array([r[1] for r in rows]) if rows else np.zeros((1, 2))
    j = np.clip(np.searchsorted(zcs, z[idx]), 1, max(1, len(zcs) - 1))
    i0, i1 = j - 1, np.minimum(j, len(zcs) - 1)
    span = np.maximum(zcs[i1] - zcs[i0], 1e-9)
    t = np.where(i1 > i0, np.clip((z[idx] - zcs[i0]) / span, 0.0, 1.0), 0.0)
    centre = cs[i0] * (1.0 - t)[:, None] + cs[i1] * t[:, None]

    def target(P):
        D = P - centre
        U = D / np.maximum(np.linalg.norm(D, axis=1), 1e-9)[:, None]
        r0 = np.linalg.norm(_on_hulls(P, centre, i0, hulls) - centre, axis=1)
        r1 = np.linalg.norm(_on_hulls(P, centre, i1, hulls) - centre, axis=1)
        return centre + U * ((1.0 - t) * r0 + t * r1)[:, None]

    # the filled vertices: no ring vertex (or one tilted past ``FLAT_NZ_CORE``: it blends from its target to the fill,
    # so the edge of the skin facing down under the seat is no kink), above the crotch or on the legs down to twice
    # ``fade_m`` under it; on the legs the fill is then faded out by a smoothstep from the crotch to ``fade_m`` under
    # it (a hard stop drew a line round the thighs). The skin between the legs under the crotch
    # (``CROTCH_STRIP_HALF_M`` of the centre plane) takes only ``CROTCH_STRIP_SHARE`` of its filled move: moved in full
    # with the seat's front and back, its narrow triangles crumpled (a high flowing trouser failed the stretch gate
    # there); held as laid, a tight trouser (fit 0) tore at the crotch in the drape
    fade = float(st["fade_m"])
    nz = np.abs(N[:, 2])
    core = move & (nz <= FLAT_NZ_CORE)
    blend = np.clip((FLAT_NZ - nz) / (FLAT_NZ - FLAT_NZ_CORE), 0.0, 1.0)
    blend = np.where(move, blend * blend * (3.0 - 2.0 * blend), 0.0)
    strip = (z <= crotch) & (np.abs(V0[:, 0] - cx) < CROTCH_STRIP_HALF_M)
    free = np.where(~core & (z <= top + 1e-4) & (z > crotch - 2.0 * fade))[0]
    w_leg = np.clip((z - (crotch - fade)) / fade, 0.0, 1.0)
    w_leg = np.where(z <= crotch, w_leg * w_leg * (3.0 - 2.0 * w_leg), 1.0)
    deg = np.bincount(E.ravel(), minlength=len(V)).astype(float)
    a, b = E[:, 0], E[:, 1]

    def nmean(X):
        out = np.empty_like(X)
        for k in range(X.shape[1]):
            out[:, k] = (np.bincount(a, X[b, k], len(V)) + np.bincount(b, X[a, k], len(V))) / np.maximum(deg, 1.0)
        return out

    V = V0.copy()
    if len(idx):
        V[idx, :2] = target(V0[idx, :2])
        for _ in range(int(st["relax_passes"])):
            mean = nmean(V[:, :2])
            V[idx, :2] = target(0.5 * V[idx, :2] + 0.5 * mean[idx])
    Dt = V[:, :2] - V0[:, :2]
    D = np.where(core[:, None], Dt, 0.0)
    for _ in range(int(st["fill_passes"])):
        D[free] = nmean(D)[free]
    D = blend[:, None] * Dt + (1.0 - blend[:, None]) * D
    D = D * w_leg[:, None]
    D[strip] *= CROTCH_STRIP_SHARE
    V = V0.copy()
    V[:, :2] += D
    info["free_verts"] = int(len(free))
    moved = np.linalg.norm(V[:, :2] - V0[:, :2], axis=1)
    info["moved_verts"] = int((moved > 1e-4).sum())
    info["moved_p90_mm"] = round(float(np.percentile(moved[moved > 1e-4], 90)) * 1000, 1) if (moved > 1e-4).any() else 0.0
    info["moved_max_mm"] = round(float(moved.max()) * 1000, 1)
    return V, info


#: A vertex whose normal's vertical part is above this faces up or down: no ring vertex of a seat slice, its move is
#: filled in from its neighbours (``trouser_seat``).
FLAT_NZ = 0.7
#: Up to this the ring vertex lies on its target alone; from it to ``FLAT_NZ`` it blends into the fill.
FLAT_NZ_CORE = 0.5
#: Under the crotch the skin this close to the centre plane (between the legs) takes this share of its filled move
#: (``trouser_seat``).
CROTCH_STRIP_HALF_M = 0.03
CROTCH_STRIP_SHARE = 0.5


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


def _joints(arm):
    """{bone name without the ``mixamorig:`` prefix: head (Blender world, rest)} of every bone."""
    return {b.name[len(gd.P):] if b.name.startswith(gd.P) else b.name: np.array(arm.matrix_world @ b.head_local)
            for b in arm.data.bones}


def _cut_pattern(bm, kind, f, arm, info, cx, cy, co, extra, dist):
    """Step 3a — the sewing-pattern pieces of a fitted piece, cut on the rest geometry right after the region cut
    (``fitted_pattern``): the seam planes are bisected (each on its side / region only), then every face gets its
    ``uv_part`` (int face layer) from its centroid and the ring / tube openings plus what ``open_islands`` adds become
    ``uv_seam`` edges (int edge layer); both ride through the evening and laying out (positions only) into the mesh.
    Returns what ``garment_template_build.pattern_uv_of_fitted`` needs: {axes, rings, rows, planes, cut_edges,
    opened, slivers}."""
    joints = _joints(arm)
    pat = extra.pop("_pattern", {}) if kind == "bra" else {}
    info.pop("_pattern", None)
    pinfo = {k: v for k, v in info.items()}
    pinfo.update(pat)
    pinfo["cx"], pinfo["cy"] = cx, float(extra.get("cy", cy))
    if kind == "briefs" and "crotch_z" in info:
        # the crotch point's y: the middle of the body's skin round the centre line at the crotch height
        m = (np.abs(co[:, 0] - cx) < 0.015) & (np.abs(co[:, 2] - float(info["crotch_z"])) < 0.015)
        pinfo["crotch_y"] = float(np.median(co[m, 1])) if m.any() else pinfo["cy"]
        info["crotch_y"] = round(pinfo["crotch_y"], 4)
    if kind == "gloves":
        pinfo["dist"] = dist
        bm.faces.ensure_lookup_table()
        pinfo["arm_centres"] = fpat.glove_centres(np.array([fa.calc_center_median() for fa in bm.faces]), joints, cx)
        if f.get("cuff", "none") != "none":
            cp = {}
            for side, s in (("Left", 1), ("Right", -1)):
                sh, el, wr = _arm_chain(arm, side)
                p, u = point_up_arm(float(f["reach_m"]) - float(f["cuff_m"]), sh, el, wr)
                cp[str(s)] = (p, u)
            pinfo["cuff_plane"] = cp
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    pre = None
    if kind == "bra":
        # a bra's cup / gore / strap class is no plane: taken BEFORE the seam bisects, inherited by the split faces
        lay_pre = bm.faces.layers.int.new("fp_pre")
        cls = fpat.pre_parts(kind, f, np.array([fa.calc_center_median() for fa in bm.faces]), pinfo)
        for fa, c in zip(bm.faces, cls):
            fa[lay_pre] = int(c)
    planes = fpat.seam_planes(kind, f, joints, pinfo)
    for p, n, side, tag in planes:
        bm.faces.ensure_lookup_table()
        cent = np.array([fa.calc_center_median() for fa in bm.faces])
        ok = fpat.in_region(kind, tag, cent, joints, pinfo, side)
        if side is not None:
            ok &= (cent[:, 0] - cx) * side > 0
        faces = [fa for fa, k in zip(bm.faces, ok) if k]
        if not faces:
            continue
        edges = {e for fa in faces for e in fa.edges}
        verts = {v for fa in faces for v in fa.verts}
        bmesh.ops.bisect_plane(bm, geom=list(verts) + list(edges) + faces, plane_co=Vector(p),
                               plane_no=Vector(n), clear_outer=False, clear_inner=False, dist=1e-5)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    cent = np.array([fa.calc_center_median() for fa in bm.faces])
    if kind == "bra":
        pre = np.array([fa[lay_pre] for fa in bm.faces])
        bm.faces.layers.int.remove(lay_pre)
    part = fpat.parts(kind, f, cent, joints, pinfo, pre=pre)
    xyz = np.array([v.co for v in bm.verts])
    faces = [tuple(v.index for v in fa.verts) for fa in bm.faces]
    cut = fpat.cuts(kind, f, faces, part, xyz, joints, pinfo)
    seams, opened = fpat.open_islands(faces, part, xyz, cut)
    slv = fpat.slivers(faces, part, xyz, seams)
    pinfo["ring_centres"] = fpat.ring_centres(faces, part, xyz)
    lay_part = bm.faces.layers.int.new("uv_part")
    lay_seam = bm.edges.layers.int.new("uv_seam")
    for fa, pid in zip(bm.faces, part):
        fa[lay_part] = int(pid)
    for a, b in seams:
        e = bm.edges.get((bm.verts[a], bm.verts[b]))
        if e is not None:
            e[lay_seam] = 1
    counts = {}
    for pid in part:
        nm = fpat.uvp.PARTS.get(int(pid), f"part{int(pid)}")
        counts[nm] = counts.get(nm, 0) + 1
    return {"axes": fpat.axes(kind, f, joints, pinfo), "rings": fpat.rings(kind, f, joints, pinfo),
            "rows": fpat.rows(kind, f), "planes": len(planes), "cut_edges": len(cut), "seam_edges": len(seams),
            "opened": opened, "slivers": slv, "faces_per_part": counts}


EDGE_RELAX_STEPS = 6


def _relax_edges(bm, tree, skip=()):
    """The free edges of a bra region smoothed: faces are kept by their centroids, so an edge the region predicate
    draws across the collider (a strap's side, a cup's top) follows the triangles in a sawtooth. Each boundary vertex
    moves halfway to the mean of its two boundary neighbours, ``EDGE_RELAX_STEPS`` times, and back onto the collider
    surface (``tree``) after every step. A straight cut edge (the band top, already bisected) stays on its line.
    Returns the largest move in mm."""
    nb = {}
    for e in bm.edges:
        if e.is_boundary:
            a, b = e.verts
            nb.setdefault(a, []).append(b)
            nb.setdefault(b, []).append(a)
    ids = [v for v, n in nb.items() if len(n) == 2 and v not in skip]
    if not ids:
        return 0.0
    start = {v: v.co.copy() for v in ids}
    for _ in range(EDGE_RELAX_STEPS):
        new = {}
        for v in ids:
            a, b = nb[v]
            p = v.co * 0.5 + (a.co + b.co) * 0.25
            loc, _n, _f, _d = tree.find_nearest(p)
            new[v] = loc if loc is not None else p
        for v, p in new.items():
            v.co = p
    bm.normal_update()
    return round(max((v.co - start[v]).length for v in ids) * 1000.0, 2)


def build_fitted(prm, spec, arm, body, ctree, col=None, cut=None, boots=()):
    """The fitted piece as a new mesh object (``prm["node"]``) with its sewing-pattern parts (``_cut_pattern``: int
    layers ``uv_part`` / ``uv_seam``, an empty ``UVMap``); returns ``(obj, pin indices, info)`` — ``info["pattern"]``
    is what ``garment_template_build.pattern_uv_of_fitted`` needs. ``cut`` (A237): the body-only rest collider the faces are cut from when ``col`` / ``ctree`` hold lower
    layers too — the piece is cut from the body and laid out over the layers (``ctree``). ``boots`` (A237): footwear colliders a trouser leg hangs over
    (``_over_boot``)."""
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
    src = cut if cut is not None else col
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.transform(src.matrix_world)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    # bra edges: the collider surface the smoothed edge vertices are put back onto
    src_tree = BVHTree.FromBMesh(bm) if kind == "bra" else None
    cent = np.array([fa.calc_center_median() for fa in bm.faces])
    keep_layer = bm.faces.layers.int.new("keep")
    push = closure = cups = None
    tsides = None
    if kind == "trousers":
        keep_v, planes, pins, tsides, extra = trousers_region(f, co, w, arm, cx, stree)
        info.update(extra)
        arm_w = sum(w[sd + b] for sd in ("Left", "Right") for b in GLOVE_BONES)
        foot_w = sum(w[sd + b] for sd in ("Left", "Right") for b in ("Foot", "ToeBase"))
        kd = _kd(co)
        cco = np.array([v.co for v in bm.verts])
        near = np.array([kd.find(Vector(p))[1] for p in cco])
        vk = keep_v(cco, arm_w[near], foot_w[near])
        mask = np.array([all(vk[v.index] for v in fa.verts) for fa in bm.faces])
    elif kind == "briefs" and float(f.get("leg_length_m") or 0.0) > 0:
        keep_v, planes, pins, extra = boxer_region(f, co, w, cx, stree)
        info.update(extra)
        arm_w = sum(w[sd + b] for sd in ("Left", "Right") for b in GLOVE_BONES)
        kd = _kd(co)
        cco = np.array([v.co for v in bm.verts])
        near = np.array([kd.find(Vector(p))[1] for p in cco])
        vk = keep_v(cco, arm_w[near])
        mask = np.array([all(vk[v.index] for v in fa.verts) for fa in bm.faces])
    elif kind == "briefs":
        keep, planes, pins, extra = briefs_region(f, co, w, cx, cy, stree)
        info.update(extra)
        if extra.get("sides") == "string":
            # A235: a hip band a few mm high is narrower than the collider's faces — the collider is first cut along
            # both of its edges, so a whole row of faces lies inside the band
            top = _gltf_y(f["top_y"])
            for z in (top, top - float(f["string_width_m"])):
                geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
                bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector((0.0, 0.0, z)), plane_no=Vector((0.0, 0.0, 1.0)),
                                       clear_outer=False, clear_inner=False, dist=1e-5)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.normal_update()
            cent = np.array([fa.calc_center_median() for fa in bm.faces])
        mask = keep(cent)
    elif kind == "bra":
        keep, planes, pins, push, closure, cups, extra = bra_region(f, co, stree, cx, cy)
        info.update(extra)
        # bra edges (BRA_EDGE_VERSION): the collider is cut along the underbust line first — faces are kept by their
        # centroids, so without the cut the band's top edge round the back followed the collider's triangles in a
        # sawtooth (a light fringe along it, round 2026-11-25); the cut's own seam plane lies on the same line
        z = float(extra["under_z"])
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector((0.0, 0.0, z)), plane_no=Vector((0.0, 0.0, 1.0)),
                               clear_outer=False, clear_inner=False, dist=1e-5)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        cent = np.array([fa.calc_center_median() for fa in bm.faces])
        mask = keep(cent)
    elif kind == "tights":
        keep_v, planes, tband, legs_w, foot_w, extra = tights_region(f, co, w, arm, cx, stree)
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
    # step 3a: the pattern pieces are cut here, on the rest geometry, before anything moves a vertex
    strips = extra.pop("_strips", None) if kind == "bra" else None
    tack_of = extra.pop("_tack", None) if kind == "bra" else None
    info.pop("_strips", None)
    info.pop("_tack", None)
    pattern = _cut_pattern(bm, kind, f, arm, info, cx, cy, co, extra, locals().get("dist"))
    strip_v = set()
    strip_rows = []
    strip_faces = []
    if strips and strips["paths"]:
        # owner ruling 1: each strap its own regular strip, a part of its own (its island: no seam needed, it is not
        # joined to the cup or the band it overlaps)
        lay_part = bm.faces.layers.int.get("uv_part")
        n_strip = {}
        for path, sd in zip(strips["paths"], strips["sides"]):
            faces_s, rows_s = strap_strip(bm, path, strips["width_m"], src_tree, strips["extend_end"])
            verts_s = [v for row in rows_s for v in row]
            strip_rows.append(rows_s)
            strip_faces.append(faces_s)
            pid = fpat.P["strap_l" if sd > 0 else "strap_r"]
            for fa in faces_s:
                fa[lay_part] = int(pid)
            lift = STRIP_LIFT_M * (2 if strips["cross"] and sd < 0 else 1)
            strip_v |= {(v, lift) for v in verts_s}
            n_strip[fpat.uvp.PARTS[int(pid)]] = len(faces_s)
        pattern["faces_per_part"].update(n_strip)
        info["strap_strips"] = n_strip
        bm.verts.index_update()
        bm.faces.index_update()
    strip_lift = {v: lift for v, lift in strip_v}
    if kind == "bra":
        # bra edges (BRA_EDGE_VERSION): the free edges smoothed AFTER the parts are taken — a moved edge face must not
        # leave its region predicate and fall to the band (the band split into islands when this ran before the cut)
        info["edge_relax_moved_mm"] = _relax_edges(bm, src_tree, skip=set(strip_lift))
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
    for faces_s in strip_faces:
        # a strip is a piece of its own: wound outward by its own vote
        sv = 0.0
        for fa in faces_s:
            loc, n, _i, _d = stree.find_nearest(fa.calc_center_median())
            if loc is not None:
                sv += fa.normal.dot(n)
        if sv < 0:
            bmesh.ops.reverse_faces(bm, faces=faces_s)
            bm.normal_update()
    V = np.array([v.co for v in bm.verts])
    out = np.zeros((len(V), 3))
    for i, v in enumerate(bm.verts):
        loc, n, _f, _d = stree.find_nearest(v.co)
        out[i] = np.array(n) if loc is not None else np.array(v.normal)
    off = np.full(len(V), float(f["offset_m"]))
    movable = np.ones(len(V), bool)
    is_strip = np.zeros(len(V), bool)
    if strip_lift:
        for v, lift in strip_lift.items():
            off[v.index] += lift
            is_strip[v.index] = True
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
    if kind == "trousers":
        off = off + float(f["waist_extra_m"]) * (V[:, 2] > float(f["top_y"]) - float(f["band_m"]))
    if kind == "tights":
        off = off + float(f["band_extra_m"]) * tband(V)
        pin_mask = np.ones(len(V), bool)                # hosiery is a second skin: pinned whole
    if kind == "bra":
        cl = closure(V)
        off = off + CLOSURE_M * cl
        wcup = push(V)
        for rows_s in strip_rows:
            # a strip follows the push-up of the cup it starts in, fading out along it over STRIP_PUSH_FADE_M past
            # the cup (a step of the push at the cup's edge would fold it)
            w_row = [float(max(wcup[v.index] for v in row)) for row in rows_s]
            for i in range(1, len(w_row)):
                w_row[i] = max(w_row[i], w_row[i - 1] - STRIP_STEP_M / STRIP_PUSH_FADE_M)
            for row, w_ in zip(rows_s, w_row):
                for v in row:
                    wcup[v.index] = w_
        pz, pin_, pout = f["push_m"]
        k = float(f["push"])
        if k > 0:
            sgn = np.where(V[:, 0] > cx, 1.0, -1.0)
            V[:, 2] += k * pz * wcup
            # a strip keeps its line: lifted and laid out with its cup, never drawn in toward the middle (a strip end
            # drawn in bent sideways over the cup)
            # ... and the draw toward the middle fades out over GORE_PUSH_FADE_M next to the gore (the cup's inner edge
            # slid over the gore, 7.9 mm off the breastbone there)
            g_ = np.clip((np.abs(V[:, 0] - cx) - float(f["gore_half_m"])) / GORE_PUSH_FADE_M, 0.0, 1.0)
            V[:, 0] -= sgn * k * pin_ * wcup * ~is_strip * g_ * g_ * (3.0 - 2.0 * g_)
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
    if tack_of is not None:
        # round 2026-11-25 (plan acceptance: the gore lies on the breastbone): the gore is tacked to the body — laid at
        # its ``off`` over its nearest skin point; the evening had bridged it across the cleft like the cups
        gm = tack_of(np.array([v.co for v in bm.verts])) & movable & ~is_strip
        for v in bm.verts:
            if gm[v.index]:
                loc, o = gd.signed_out(ctree, v.co, 0.1)
                if loc is not None:
                    v.co = loc + o * float(off[v.index])
        info["tacked"] = int(gm.sum())
    if kind == "bra":
        # the cups bridge the breast's tip (cloth spans it; laid on it, the edges round the tip were 2.5 mm and the
        # drape stretched them to 1.33); a molded cup is a shell and gets more
        cm = cups(np.array([v.co for v in bm.verts])) & movable & ~is_strip
        for _round in range(2):
            _umbrella(bm, MOLDED_PASSES if f.get("rigid_cups") else SMOOTH_PASSES["bra"], cm, boundary_only_along=True)
            _lay_out(bm, ctree, off, cm)
    if kind == "trousers":
        # the legs widened to the leg shape, then evened once more (the widening is a fan of radial moves: the
        # evening rounds the knee's / the calf's rings into the tube) and laid out where the evening pulled one in
        Vw, info["widen"] = trouser_widen(np.array([v.co for v in bm.verts]), f, tsides, cx)
        for v, p in zip(bm.verts, Vw):
            v.co = Vector(p)
        if f.get("shape_r"):
            _umbrella(bm, SMOOTH_PASSES["trousers"], movable)
            _lay_out(bm, ctree, off, movable)
        # bug round 2026-11-20: the seat — bridged, eased and the crotch dropped (``trouser_seat``), laid out again
        # where a move went under the skin; the pins below are taken from these positions
        top_z = _gltf_y(f["top_y"])
        bm.verts.ensure_lookup_table()
        bm.normal_update()
        Vs, info["seat"] = trouser_seat(np.array([v.co for v in bm.verts]), np.array([v.normal for v in bm.verts]),
                                        np.array([(e.verts[0].index, e.verts[1].index) for e in bm.edges], int),
                                        f, cx, float(info["crotch_z"]), top_z, top_z - float(f["band_m"]))
        if info["seat"].get("moved_verts"):
            for v, p in zip(bm.verts, Vs):
                v.co = Vector(p)
            _lay_out(bm, ctree, off, movable)
        if boots:
            info["over_boot"] = _over_boot(bm, boots, arm, off)
    V = np.array([v.co for v in bm.verts])
    if kind == "trousers":
        pin_mask = pins(V)
        # A237: the centre seam over the crotch's front and back hollows (the mons, the seat's cleft) is held as laid —
        # after the seat bridged them (``trouser_seat``): the cloth bridging them was drawn into them in the drape
        # (Ylva: 4 edges on the centre line, stretch 2.09)
        # (a bridged seat's seam starts ``SEAT_SEAM_LIFT_M`` over the crotch: pinned down to the crotch point, the cloth
        # meeting the skin between the legs there was stretched over the gate in the drape — a high flowing trouser)
        lift = SEAT_SEAM_LIFT_M if (f.get("seat") or {}).get("bridge") else 0.0
        seam = (np.abs(V[:, 0] - cx) < SEAM_HALF_M) & (V[:, 2] > float(info["crotch_z"]) + lift)
        pin_mask = pin_mask | seam
        info["seam_pins"] = int(seam.sum())
        if boots:
            # A237: the leg over the boot is pinned as laid out over it (``_over_boot``): the fit is posed with the
            # boot's foot pose while the drape body stands in its rest pose, so a free leg caught on the collar
            pin_mask = pin_mask | (V[:, 2] <= info["over_boot"]["top"] + OVER_BOOT_ABOVE_M)
    elif kind == "briefs":
        pin_mask = pins(V)
    elif kind == "bra":
        # the cups' rim is pinned as well (it holds the cut's line: an unpinned triangle rim stretched to 1.36)
        rim = np.array([v.is_boundary for v in bm.verts])
        tip = np.zeros(len(V), bool)
        for a in info["apex"].values():
            tip |= np.linalg.norm(V - np.array(a), axis=1) < TIP_PIN_M
        cv = cups(V) & ~is_strip
        pin_mask = pins(V) | (rim & cv) | (tip & cv) | is_strip
    # the UV map is written by ``garment_template_build.pattern_uv_of_fitted`` from the ``uv_part`` / ``uv_seam``
    # layers after ``clear_of_body`` (step 3a: sewing-pattern islands, no planar box UV)
    bm.loops.layers.uv.new("UVMap")
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
    info["pattern"] = pattern
    return obj, pin, info


#: A237: half the width of the trousers' centre seam held as laid over the crotch (``build_fitted``).
SEAM_HALF_M = 0.012
#: Bug round 2026-11-20: a bridged seat's centre seam is held from this far over the crotch up (``build_fitted``).
SEAT_SEAM_LIFT_M = 0.01
#: A237: a trouser vertex this far above a boot's top is still pushed out of it (the hem bells over the collar).
OVER_BOOT_ABOVE_M = 0.02
#: A237: where the inward ray starts, from the leg's axis — inside the gap between the legs, so a ray toward the other
#: leg never meets the other boot (from 0.3 m it did: 25 cm "boot" radii, nothing moved).
OVER_BOOT_RAY_M = 0.14
#: A237: the farthest a vertex is moved out over a boot (a ray past the boot's toe is left to the drape).
OVER_BOOT_MAX_M = 0.08


def _over_boot(bm, boots, arm, off):
    """A237 — a trouser leg worn OVER a boot: every vertex up to the boot's top (+ ``OVER_BOOT_ABOVE_M``) goes out
    to its ``off`` beyond the boot's OUTER surface along the horizontal ray from its leg's axis (knee -> ankle joint,
    by height). The boot is a shell round the ankle: a leg cut from the body lies in the air between the shaft and the
    skin, which is outside the collider, so laying out left it there and the drape caught it inside the shaft (Lirien
    straight leg: stretch 25.9). The ray is cast from ``OVER_BOOT_RAY_M`` out inward — its first hit is the outer
    surface. Returns the count moved and what was looked at."""
    from mathutils.bvhtree import BVHTree
    trees, top = [], -1e9
    dg = bpy.context.evaluated_depsgraph_get()
    for b in boots:
        trees.append(BVHTree.FromObject(b, dg))
        top = max(top, max((b.matrix_world @ v.co).z for v in b.data.vertices))
    axes = {sd: (_bone_head(arm, f"{name}Leg"), _bone_head(arm, f"{name}Foot"))
            for sd, name in ((1, "Left"), (-1, "Right"))}
    sx = 1 if axes[1][0][0] > axes[-1][0][0] else -1     # which side of x the left leg is on
    n = 0
    stat = {"top": round(top, 3), "below": 0, "hit": 0, "inside": 0}
    for v in bm.verts:
        p = np.array(v.co)
        if p[2] > top + OVER_BOOT_ABOVE_M:
            continue
        stat["below"] += 1
        knee, ankle = axes[1] if (p[0] * sx > 0) else axes[-1]
        t = np.clip((knee[2] - p[2]) / max(1e-6, knee[2] - ankle[2]), 0.0, 1.0)
        a = knee + t * (ankle - knee)
        d = np.array([p[0] - a[0], p[1] - a[1], 0.0])
        r = float(np.linalg.norm(d))
        if r < 1e-6:
            continue
        d /= r
        best = None
        for tr in trees:
            hit = tr.ray_cast(Vector(a + d * OVER_BOOT_RAY_M + np.array([0.0, 0.0, p[2] - a[2]])), Vector(-d),
                              OVER_BOOT_RAY_M)
            if hit[0] is not None:
                rb = OVER_BOOT_RAY_M - hit[3]
                best = rb if best is None else max(best, rb)
        if best is None:
            continue
        stat["hit"] += 1
        want = best + float(off[v.index])
        stat["inside"] += int(r < want)
        if r < want and want - r <= OVER_BOOT_MAX_M:
            q = a + d * want
            v.co = Vector((q[0], q[1], p[2]))
            n += 1
    return {"moved": n, **stat}


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
