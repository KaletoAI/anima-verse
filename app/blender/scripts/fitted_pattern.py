"""Sewing-pattern pieces of the FITTED template kinds (briefs, bra, gloves, tights, trousers): numpy only, no bpy.

Step 3a of the pattern plan (``garment_template_fitted.build_fitted`` imports it inside Blender;
``scripts/smoke_fitted_pattern.py`` checks it by hand without Blender). A fitted piece has no construction rows — it
is cut from the voxel-remeshed rest collider by region predicates and planes — so the part of a face comes from the
REGION RULE AT CUT TIME, never from a later relabel:

1. ``seam_planes`` — the seam planes of the kind; ``build_fitted`` bisects them (``clear_outer`` False) BEFORE the
   labels are taken, each only on its side / region (``in_region``), so every face lies on one side of every seam and
   a centroid test gives straight seams.
2. ``parts`` — the ``uv_part`` id (``uv_pattern.PARTS``) of every face from its centroid, by the kind's precedence.
3. ``cuts`` — the seam edges that are no part border: the opening of a ring part (the waistband, a cuff) and the
   tube cut of a tights leg (the inseam, and on a closed foot the slit along the sole), both picked as the edges of
   one part that lie on a bisected plane within a half-plane (``plane_cut``).
4. ``open_islands`` — every island must be a disk (Euler characteristic 1) or ARAP folds it: an island that is still a
   tube or holds a slit not reaching its border (the Kira failure: a back slit from the crotch down, area 0.94) gets
   the shortest edge path between two of its boundary loops as a seam, until it is a disk. Reported, never silent.
5. ``axes`` / ``rings`` / ``rows`` — what ``uv_pattern.pattern_uv`` needs: the grain and outward axis per panel part,
   the ring-strip frame per ring part, the atlas rows of the kind.

Coordinates as ``garment_template_fitted``: Blender Z-up metres, front = -Y, the character's left = +X, ``cx, cy`` =
Spine1's head; ``joints`` = {bone name without the ``mixamorig:`` prefix: head (3,)}. "left" / "right" in part names
are the WEARER's (+X = left).
"""
import heapq

import numpy as np

import uv_pattern as uvp

#: Briefs / tights: the gusset reaches this far in front of and behind the crotch point, and this far over it.
GUSSET_FRONT_M = 0.04
GUSSET_BACK_M = 0.08
GUSSET_RISE_M = 0.03
#: Tights: the gusset's half width and how far under the crotch it may reach (the crotch's own skin, not the thighs).
TIGHTS_GUSSET_HALF_M = 0.03
TIGHTS_GUSSET_DROP_M = 0.02
#: A part component under this many faces is a sliver (reported, fails the acceptance; never relabelled).
MIN_ISLAND_FACES = 30
#: A vertex this close to a seam plane lies on it (``bisect_plane`` leaves its cut vertices within 1e-5).
ON_PLANE_M = 1e-4
#: Gloves: the cuff ring at the reach edge (``garment_template.CUFF_M``).
#: Tights / trousers: the closed foot's sole slit is taken this far under the ankle joint and lower.
SOLE_BELOW_ANKLE_M = 0.03

P = {v: k for k, v in uvp.PARTS.items()}

FINGERS = ("Index", "Middle", "Ring", "Pinky")


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _side(c, cx):
    return np.where(np.asarray(c)[:, 0] > cx, 1, -1)


def _leg_plane(joints, side):
    """The per-leg seam plane: through the hip joint (``UpLeg`` head) and the ankle joint (``Foot`` head), spanned by
    X; its normal points to -Y (front = the + side). It meets the leg tube at its outermost line (the side seam) and
    its innermost (the inseam)."""
    sd = "Left" if side > 0 else "Right"
    hip, ankle = np.asarray(joints[sd + "UpLeg"], float), np.asarray(joints[sd + "Foot"], float)
    n = _unit(np.cross(ankle - hip, (1.0, 0.0, 0.0)))
    if n[1] > 0:
        n = -n
    return hip, n, ankle


def _arm_planes(joints, side, centres=None):
    """Gloves: per side the seam planes of the dorsal / palmar split — (tag, point, normal), the normal pointing to the
    dorsal side: the upper arm and the forearm (through the bone line, spanned by the horizontal perpendicular), the
    hand (through Hand, Index1, Pinky1; also the thenar under Thumb1 -> Thumb2). Dorsal = the hand normal's side,
    turned to +Z (palms down in the rest pose). The planes of neighbouring regions share their joint (ForeArm, Hand),
    so the split line runs on at the region border. The thumb past Thumb2 is a piece of its own (``_thumb``).
    ``centres`` ({tag: point}, ``glove_centres``) moves each plane along its normal to the middle of its region's
    cloth: a bone line lies off the middle of the limb (Glut's forearm: split 8.9 / 16.4 cm through the bone line)."""
    sd = "Left" if side > 0 else "Right"
    j = lambda n: np.asarray(joints[sd + n], float)  # noqa: E731
    hand, idx, pky = j("Hand"), j("HandIndex1"), j("HandPinky1")
    nh = _unit(np.cross(idx - hand, pky - hand))
    if nh[2] < 0:
        nh = -nh
    out = []
    for tag, a, b in (("upper", j("Arm"), j("ForeArm")), ("fore", j("ForeArm"), hand)):
        d = _unit(b - a)
        hp = _unit(np.cross((0.0, 0.0, 1.0), d))
        n = _unit(np.cross(d, hp))
        if n @ nh < 0:
            n = -n
        out.append((tag, a, n))
    out.append(("hand", hand, nh))
    if centres:
        out = [(t, p + ((np.asarray(centres[t], float) - p) @ n) * n if t in centres else p, n) for t, p, n in out]
    return out


def glove_centres(c, joints, cx):
    """{str(side): {region tag: the mean of the region's face centroids}} — ``_arm_planes``' ``centres`` (taken at
    cut time, before the seam planes are bisected; info["arm_centres"])."""
    c = np.asarray(c, float)
    out = {}
    for s in (1, -1):
        m = (c[:, 0] - cx) * s > 0
        if not m.any():
            continue
        reg = arm_region(c[m], joints, s)
        out[str(s)] = {t: c[m][reg == t].mean(0) for t in ("upper", "fore", "hand") if (reg == t).sum() >= 10}
    return out


def _thumb(joints, side):
    """Gloves (decision D11 b, taken by the plan's own rule: the thumb as a lobe of the back / palm stretched to
    p95 1.56 on Glut's elbow gloves and holed the palm where the thumb's plane met the hand's): the thumb past Thumb2 is
    one piece (a Bolton thumb). Returns (T2, d = the thumb's direction Thumb2 -> Thumb3, the slit plane's normal, the
    slit side): the piece starts at the plane through T2 normal to d; it is opened along the line of the thumb that
    faces the index finger (the plane through the thumb's axis and the direction to Index1)."""
    sd = "Left" if side > 0 else "Right"
    t2, t3 = np.asarray(joints[sd + "HandThumb2"], float), np.asarray(joints[sd + "HandThumb3"], float)
    d = _unit(t3 - t2)
    to_idx = np.asarray(joints[sd + "HandIndex1"], float) - t2
    half = _unit(to_idx - (to_idx @ d) * d)
    return t2, d, _unit(np.cross(d, half)), half


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(1e-12, ab @ ab), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def arm_region(c, joints, side):
    """Gloves: per point the bone region its nearest bone segment belongs to — "upper" (Arm -> ForeArm), "fore"
    (ForeArm -> Hand), "hand" (Hand -> Middle1 and the four fingers, the last bone extended by its own length), "thumb"
    (Thumb1 -> Thumb3, extended; ``parts`` gives only its part past Thumb2 the thumb piece)."""
    sd = "Left" if side > 0 else "Right"
    j = lambda n: np.asarray(joints[sd + n], float)  # noqa: E731
    segs = [("upper", j("Arm"), j("ForeArm")), ("fore", j("ForeArm"), j("Hand")),
            ("hand", j("Hand"), j("HandMiddle1"))]
    for fn in FINGERS:
        p1, p2, p3 = j(f"Hand{fn}1"), j(f"Hand{fn}2"), j(f"Hand{fn}3")
        segs += [("hand", j("Hand"), p1), ("hand", p1, p2), ("hand", p2, p3), ("hand", p3, p3 + (p3 - p2))]
    t1, t2, t3 = j("HandThumb1"), j("HandThumb2"), j("HandThumb3")
    segs += [("thumb", t1, t2), ("thumb", t2, t3), ("thumb", t3, t3 + (t3 - t2))]
    c = np.asarray(c, float)
    d = np.stack([_seg_dist(c, a, b) for _t, a, b in segs], axis=1)
    tags = np.array([t for t, _a, _b in segs])
    return tags[np.argmin(d, axis=1)]


def _brief_crotch(info):
    return float(info["crotch_z"]), float(info.get("crotch_y", info["cy"]))


def boxers(kind, f):
    return kind == "briefs" and float(f.get("leg_length_m") or 0.0) > 0


def seam_planes(kind, f, joints, info):
    """The seam planes of a fitted piece: [(point, normal, side | None, region tag | None)] — ``build_fitted``
    bisects each (``clear_outer`` False) on the geometry of its side (x - cx has that sign) and region (``in_region``)
    AFTER the region planes, BEFORE ``parts``. The planes are the part borders that are straight lines in the pattern:
    the centre seams, the side seams / inseams, the band heights, the gusset box, the balconette's cup seam."""
    cx, cy = float(info["cx"]), float(info["cy"])
    X, Y, Z = np.eye(3)
    out = []

    def hz(z, side=None, tag=None):
        out.append((np.array([cx, cy, float(z)]), Z.copy(), side, tag))

    if kind == "trousers" or boxers(kind, f):
        out.append((np.array([cx, cy, 0.0]), X.copy(), None, None))
        for s in (1, -1):
            hip, n, _a = _leg_plane(joints, s)
            out.append((hip, n, s, None))
        top = float(f["top_y"])
        wb = float(f.get("waistband_m") or 0.0)
        if wb > 0:
            hz(top - wb)
        if kind == "trousers" and f.get("hem") == "cuffed":
            for s in (1, -1):
                hz(float(info["hems"][str(s)]) + float(f["cuff_m"]), s)
    elif kind == "briefs":
        top = float(f["top_y"])
        crotch, crotch_y = _brief_crotch(info)
        out.append((np.array([cx, cy, 0.0]), X.copy(), None, None))
        out.append((np.array([cx, cy, 0.0]), Y.copy(), None, None))
        for y in (crotch_y - GUSSET_FRONT_M, crotch_y + GUSSET_BACK_M):
            out.append((np.array([cx, y, 0.0]), Y.copy(), None, None))
        hz(crotch + GUSSET_RISE_M)
        wb = float(f.get("waistband_m") or 0.0)
        if wb > 0:
            hz(top - wb)
        if f.get("sides") == "string":
            for tag, corner in (("front", float(info["corner_front_m"])), ("back", float(info["corner_back_m"]))):
                for s in (1, -1):
                    out.append((np.array([cx + s * corner, cy, 0.0]), X.copy(), s, tag))
    elif kind == "tights":
        style = f["style"]
        crotch = float(info["crotch_z"])
        if style == "tights":
            out.append((np.array([cx, cy, 0.0]), X.copy(), None, None))
            g = TIGHTS_GUSSET_HALF_M
            for x in (cx - g, cx + g):
                out.append((np.array([x, cy, 0.0]), X.copy(), None, None))
            hz(crotch + GUSSET_RISE_M)
            hz(crotch - TIGHTS_GUSSET_DROP_M)
            wb = float(f.get("waistband_m") or 0.0)
            if wb > 0:
                hz(float(f["top_y"]) - wb)
        elif float(f.get("band_m") or 0.0) > 0:
            for s in (1, -1):
                hz(float(info["tops"][str(s)]) - float(f["band_m"]), s)
        for s in (1, -1):
            hip, n, ankle = _leg_plane(joints, s)
            out.append((hip, n, s, None))
            if f["feet"] == "closed":
                sd = "Left" if s > 0 else "Right"
                toe = np.asarray(joints[sd + "ToeBase"], float)
                out.append((ankle, _unit(np.cross(toe - ankle, Z)), s, "foot"))
    elif kind == "bra":
        if f["style"] == "bandeau":
            out.append((np.array([cx, cy, 0.0]), Y.copy(), None, None))
        else:
            out.append((np.array([cx, cy, 0.0]), X.copy(), None, None))
            hz(float(info["under_z"]))
            gh = float(f["gore_half_m"])
            for s in (1, -1):
                out.append((np.array([cx + s * gh, cy, 0.0]), X.copy(), s, "front"))
            if f["style"] == "balconette":
                for s, key in ((1, "l"), (-1, "r")):
                    hz(float(info["apex"][key][2]), s, "front")
    elif kind == "gloves":
        for s in (1, -1):
            for tag, p, n in _arm_planes(joints, s, info.get("arm_centres", {}).get(str(s))):
                out.append((p, n, s, tag))
                if tag == "hand":
                    out.append((p, n, s, "thumb"))          # the thenar behind Thumb2 splits by the hand plane
            t2, d, n_slit, _half = _thumb(joints, s)
            out.append((t2, d, s, "thumb"))
            out.append((t2, n_slit, s, "thumb"))
            if f.get("cuff", "none") != "none":
                p, u = info["cuff_plane"][str(s)]
                out.append((np.asarray(p, float), np.asarray(u, float), s, None))
    return out


def in_region(kind, tag, c, joints, info, side):
    """Per point of ``c`` whether it lies in the region ``tag`` of a seam plane (None = everywhere): "front" / "back"
    (y against cy), "foot" (under the ankle joint less ``SOLE_BELOW_ANKLE_M``), or a glove bone region
    (``arm_region``)."""
    c = np.asarray(c, float)
    if tag is None:
        return np.ones(len(c), bool)
    cy = float(info["cy"])
    if tag == "front":
        return c[:, 1] < cy
    if tag == "back":
        return c[:, 1] > cy
    if tag == "foot":
        sd = "Left" if side > 0 else "Right"
        return c[:, 2] < float(joints[sd + "Foot"][2]) - SOLE_BELOW_ANKLE_M
    return arm_region(c, joints, side) == tag


#: ``pre_parts`` classes of a bra face (taken BEFORE the seam planes are bisected).
PRE_CUP, PRE_GORE, PRE_STRAP_L, PRE_STRAP_R, PRE_BAND = 1, 2, 3, 4, 5


def pre_parts(kind, f, c, info):
    """A bra face's region class (cup > gore > strap — the side its path starts on: a cross-back strap crosses the
    centre — > band; 0 = none) by ``bra_region``'s predicates on the centroids ``c``. ``build_fitted`` takes it BEFORE
    the seam planes are bisected (every face then matches a class: ``keep`` kept it by these predicates) and stores it
    in a face layer the split faces inherit; ``parts`` takes it again AFTER the bisect and falls back to the inherited
    class only where a split face's centroid left every region (the cup's curved outline) — a plane border (the gore
    at gore_half, the band at the underbust line) is decided by the new centroid, so no split face is a sliver of the
    class across the plane. None for the other kinds (every rule of theirs is a bisected plane)."""
    if kind != "bra":
        return None
    c = np.asarray(c, float)
    pred = info["pred"]
    out = np.zeros(len(c), np.int64)
    out[pred["band"](c)] = PRE_BAND
    st = pred["straps"](c)
    sside = _side(c, float(info["cx"]))
    if info.get("strap_paths"):
        d = np.stack([_path_dist(c, np.asarray(p, float)) for p in info["strap_paths"]], axis=1)
        sside = np.array(info["strap_sides"])[np.argmin(d, axis=1)]
    out[st] = np.where(sside > 0, PRE_STRAP_L, PRE_STRAP_R)[st]
    out[pred["gore"](c)] = PRE_GORE
    out[pred["cups"](c)] = PRE_CUP
    return out


def parts(kind, f, c, joints, info, pre=None):
    """The ``uv_part`` id of every face from its centroid ``c`` (n, 3), at cut time (after ``seam_planes`` were
    bisected), by the kind's precedence — never 0 (``pre`` = the ``pre_parts`` classes, a bra's):

    * trousers / boxers: waistband > cuff (trousers ``hem`` cuffed) > the leg halves by the per-leg plane (front_l /
      front_r / back_l / back_r, the side by x against cx);
    * briefs: gusset (between the planes ``GUSSET_FRONT_M`` before and ``GUSSET_BACK_M`` behind the crotch point, under
      ``GUSSET_RISE_M`` over it — across the whole crotch: its sides are the leg openings, so no strip beside it is cut
      off) > waistband > hip band (``sides`` string, past the panel corners) > front / back (y against cy);
    * tights: (full tights) waistband > gusset; (the others) top band; then leg_l / leg_r;
    * bra: cups (balconette: cup / cup_top at the apex height) > gore > straps > band halves; a bandeau: straps >
      front / back;
    * gloves: cuff > thumb (past Thumb2) > back of the hand (dorsal side of the region's plane) / palm."""
    c = np.asarray(c, float)
    n = len(c)
    cx, cy = float(info["cx"]), float(info["cy"])
    s = _side(c, cx)
    left = s > 0
    out = np.zeros(n, np.int64)

    def lr(name, mask=None):
        v = np.where(left, P[name + "_l"], P[name + "_r"])
        return v if mask is None else v[mask]

    if kind == "trousers" or boxers(kind, f):
        front = np.zeros(n, bool)
        for sd in (1, -1):
            hip, nrm, _a = _leg_plane(joints, sd)
            m = s == sd
            front[m] = (c[m] - hip) @ nrm > 0
        out[:] = np.where(front, lr("front"), lr("back"))
        if kind == "trousers" and f.get("hem") == "cuffed":
            hem = np.where(left, float(info["hems"]["1"]), float(info["hems"]["-1"]))
            cuff = c[:, 2] < hem + float(f["cuff_m"])
            out[cuff] = lr("cuff", cuff)
        wb = float(f.get("waistband_m") or 0.0)
        if wb > 0:
            out[c[:, 2] > float(f["top_y"]) - wb] = P["waistband"]
        return out
    if kind == "briefs":
        top = float(f["top_y"])
        crotch, crotch_y = _brief_crotch(info)
        out[:] = np.where(c[:, 1] < cy, P["front"], P["back"])
        if f.get("sides") == "string":
            sw = float(f["string_width_m"])
            corner = np.where(c[:, 1] < cy, float(info["corner_front_m"]), float(info["corner_back_m"]))
            hb = (c[:, 2] > top - sw) & (np.abs(c[:, 0] - cx) > corner)
            out[hb] = lr("hip_band", hb)
        wb = float(f.get("waistband_m") or 0.0)
        if wb > 0:
            out[c[:, 2] > top - wb] = P["waistband"]
        gus = (c[:, 1] > crotch_y - GUSSET_FRONT_M) & (c[:, 1] < crotch_y + GUSSET_BACK_M) \
            & (c[:, 2] < crotch + GUSSET_RISE_M)
        out[gus] = P["gusset"]
        return out
    if kind == "tights":
        out[:] = lr("leg")
        if f["style"] == "tights":
            crotch = float(info["crotch_z"])
            wb = float(f.get("waistband_m") or 0.0)
            gus = (np.abs(c[:, 0] - cx) < TIGHTS_GUSSET_HALF_M) & (c[:, 2] < crotch + GUSSET_RISE_M) \
                & (c[:, 2] > crotch - TIGHTS_GUSSET_DROP_M)
            out[gus] = P["gusset"]
            if wb > 0:
                out[c[:, 2] > float(f["top_y"]) - wb] = P["waistband"]
        elif float(f.get("band_m") or 0.0) > 0:
            top = np.where(left, float(info["tops"]["1"]), float(info["tops"]["-1"]))
            band = (c[:, 2] > top - float(f["band_m"])) & (c[:, 2] <= top + 0.005)
            out[band] = lr("top_band", band)
        return out
    if kind == "bra":
        now = pre_parts(kind, f, c, info)
        pre = np.where(now > 0, now, np.asarray(pre if pre is not None else now))
        if f["style"] == "bandeau":
            out[:] = np.where(c[:, 1] < cy, P["front"], P["back"])
        else:
            out[:] = lr("band")
            out[pre == PRE_GORE] = P["gore"]
            cups = pre == PRE_CUP
            out[cups] = lr("cup", cups)
        out[pre == PRE_STRAP_L] = P["strap_l"]
        out[pre == PRE_STRAP_R] = P["strap_r"]
        if f["style"] == "bandeau":
            return out
        if f["style"] == "balconette":
            apex_z = np.where(left, float(info["apex"]["l"][2]), float(info["apex"]["r"][2]))
            up = cups & (c[:, 2] > apex_z)
            out[up] = lr("cup_top", up)
        return out
    if kind == "gloves":
        dors = np.zeros(n, bool)
        thumb = np.zeros(n, bool)
        for sd in (1, -1):
            m = s == sd
            if not m.any():
                continue
            reg = arm_region(c[m], joints, sd)
            t2, d, _n, _h = _thumb(joints, sd)
            th = (reg == "thumb") & ((c[m] - t2) @ d > 0)
            reg = np.where((reg == "thumb") & ~th, "hand", reg)
            dm = np.zeros(m.sum(), bool)
            for tag, p, nrm in _arm_planes(joints, sd, info.get("arm_centres", {}).get(str(sd))):
                r = reg == tag
                dm[r] = (c[m][r] - p) @ nrm > 0
            dors[m] = dm
            thumb[np.where(m)[0][th]] = True
        out[:] = np.where(dors, lr("glove_back"), lr("palm"))
        out[thumb] = lr("thumb", thumb)
        if f.get("cuff", "none") != "none":
            cuff = info["dist"](c) > float(f["reach_m"]) - float(f["cuff_m"])
            out[cuff] = lr("cuff", cuff)
        return out
    raise ValueError(f"fitted_pattern.parts: unknown kind {kind!r}")


def _path_dist(p, path):
    d = np.full(len(p), 9.0)
    for a, b in zip(path[:-1], path[1:]):
        d = np.minimum(d, _seg_dist(p, a, b))
    return d


def _edges_of(faces):
    """{(a, b) sorted: [face ids]}."""
    e = {}
    for fi, f in enumerate(faces):
        for k in range(len(f)):
            a, b = int(f[k]), int(f[(k + 1) % len(f)])
            e.setdefault((min(a, b), max(a, b)), []).append(fi)
    return e


def plane_cut(faces, part, xyz, pids, plane_p, plane_n, line_p, line_d, half_dir, z_lo=-9.0, z_hi=9.0, edges=None):
    """The seam edges of a ring / tube opening: every edge shared by two faces whose parts are both in ``pids``, both
    of its vertices on the plane (``plane_p``, ``plane_n``; within ``ON_PLANE_M`` — ``bisect_plane`` put them there),
    its midpoint on the ``half_dir`` side of the line (``line_p``, ``line_d``) that lies in the plane, and its midpoint
    height within [``z_lo``, ``z_hi``]. Returns {(a, b)} (a < b)."""
    xyz = np.asarray(xyz, float)
    part = np.asarray(part)
    pids = set(int(p) for p in np.atleast_1d(pids))
    pp, pn = np.asarray(plane_p, float), _unit(plane_n)
    lp, ld, hd = np.asarray(line_p, float), _unit(line_d), np.asarray(half_dir, float)
    on = np.abs((xyz - pp) @ pn) < ON_PLANE_M
    out = set()
    for (a, b), fs in (edges if edges is not None else _edges_of(faces)).items():
        if len(fs) != 2 or not (on[a] and on[b]):
            continue
        if int(part[fs[0]]) not in pids or int(part[fs[1]]) not in pids:
            continue
        m = 0.5 * (xyz[a] + xyz[b])
        if not (z_lo <= m[2] <= z_hi):
            continue
        q = lp + ((m - lp) @ ld) * ld
        if (m - q) @ hd > 0:
            out.add((a, b))
    return out


def cuts(kind, f, faces, part, xyz, joints, info):
    """The seam edges of a fitted piece that are no part border (``plane_cut`` on the bisected planes):

    * a waistband (trousers, boxers, briefs, tights): at the centre back (x = cx, y > cy) — never at the fly: ``fly``
      changes the picture only (``TEXTURE_ONLY``), never the cut;
    * a trouser cuff and a tights top band: at the inseam (the leg plane, inner half);
    * a glove cuff: where the arm planes meet its +Y side (behind the arm in the rest pose); a glove's thumb: along
      its line facing the index finger (``_thumb``);
    * a tights leg (decision D2 a): the inseam — the leg plane's inner half from the top down to the ankle, and on a
      closed foot (D3 a) the slit along the sole (the foot plane under the ankle less ``SOLE_BELOW_ANKLE_M``);
      ``open_islands`` joins the two where they do not meet.
    Returns {(a, b)}."""
    cx, cy = float(info["cx"]), float(info["cy"])
    X, Y, Z = np.eye(3)
    E = _edges_of(faces)
    out = set()
    centre = np.array([cx, cy, 0.0])
    if P["waistband"] in set(np.asarray(part).tolist()):
        out |= plane_cut(faces, part, xyz, P["waistband"], centre, X, centre, Z, Y, edges=E)
    if kind == "trousers" and f.get("hem") == "cuffed":
        for s in (1, -1):
            hip, n, ankle = _leg_plane(joints, s)
            out |= plane_cut(faces, part, xyz, P["cuff_l" if s > 0 else "cuff_r"], hip, n, hip, ankle - hip,
                             -s * X, edges=E)
    if kind == "tights":
        for s in (1, -1):
            hip, n, ankle = _leg_plane(joints, s)
            leg = [P["leg_l" if s > 0 else "leg_r"], P["top_band_l" if s > 0 else "top_band_r"]]
            z_lo = float(ankle[2]) if f["feet"] == "closed" else -9.0
            out |= plane_cut(faces, part, xyz, leg, hip, n, hip, ankle - hip, -s * X, z_lo=z_lo, edges=E)
            if f["feet"] == "closed":
                sd = "Left" if s > 0 else "Right"
                toe = np.asarray(joints[sd + "ToeBase"], float)
                fn = _unit(np.cross(toe - ankle, Z))
                # the sole: under the foot plane's line through the ankle along the foot, the half facing down
                out |= plane_cut(faces, part, xyz, leg, ankle, fn, ankle, toe - ankle, -Z,
                                 z_hi=float(ankle[2]) - SOLE_BELOW_ANKLE_M, edges=E)
    if kind == "gloves":
        for s in (1, -1):
            t2, d, n_slit, half = _thumb(joints, s)
            out |= plane_cut(faces, part, xyz, P["thumb_l" if s > 0 else "thumb_r"], t2, n_slit, t2, d, half,
                             edges=E)
    if kind == "gloves" and f.get("cuff", "none") != "none":
        for s in (1, -1):
            sd = "Left" if s > 0 else "Right"
            bones = {"upper": ("Arm", "ForeArm"), "fore": ("ForeArm", "Hand")}
            for tag, p, n in _arm_planes(joints, s, info.get("arm_centres", {}).get(str(s))):
                if tag in bones:
                    a, b = (np.asarray(joints[sd + k], float) for k in bones[tag])
                    out |= plane_cut(faces, part, xyz, P["cuff_l" if s > 0 else "cuff_r"], p, n, a, b - a, Y,
                                     edges=E)
    return out


def _euler(island):
    """V - E + F of an island (its local vertices, edges, faces)."""
    e = set()
    for poly in island.corner_vid:
        for k in range(len(poly)):
            a, b = poly[k], poly[(k + 1) % len(poly)]
            e.add((min(a, b), max(a, b)))
    return len(island.vmap) - len(e) + len(island.corner_vid)


def open_islands(faces, part, xyz, seams, max_rounds=8):
    """Make every island a disk: while an island has Euler characteristic < 1 (a tube: two boundary loops; a slit not
    reaching its border: a hole), the shortest edge path (3D length, through the island) from its longest boundary loop
    to the nearest vertex of another loop becomes a seam. Returns (seams, report) — report = [{island, euler, added}]
    for every island that needed it (a ring part whose ``ring_cut`` did not reach both edges shows up here)."""
    xyz = np.asarray(xyz, float)
    seams = set((min(a, b), max(a, b)) for a, b in seams)
    report = []
    for _ in range(max_rounds):
        changed = False
        for isl in uvp.split_islands(len(xyz), faces, part, seams, xyz=xyz):
            chi = _euler(isl)
            if chi >= 1:
                continue
            loops = uvp.boundary_loops(isl)
            if len(loops) < 2:
                report.append({"island": isl.name, "euler": chi, "added": 0, "loops": len(loops)})
                continue
            src = set(loops[0])
            dst = set(v for lp in loops[1:] for v in lp)
            adj = {}
            for poly in isl.corner_vid:
                for k in range(len(poly)):
                    a, b = poly[k], poly[(k + 1) % len(poly)]
                    w = float(np.linalg.norm(xyz[isl.vmap[a]] - xyz[isl.vmap[b]]))
                    adj.setdefault(a, {})[b] = w
                    adj.setdefault(b, {})[a] = w
            dist = {v: 0.0 for v in src}
            prev = {}
            heap = [(0.0, v) for v in src]
            heapq.heapify(heap)
            hit = None
            while heap:
                d, v = heapq.heappop(heap)
                if d > dist.get(v, 1e18):
                    continue
                if v in dst:
                    hit = v
                    break
                for u, w in adj.get(v, {}).items():
                    nd = d + w
                    if nd < dist.get(u, 1e18):
                        dist[u] = nd
                        prev[u] = v
                        heapq.heappush(heap, (nd, u))
            if hit is None:
                report.append({"island": isl.name, "euler": chi, "added": 0, "loops": len(loops)})
                continue
            path = [hit]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            added = 0
            for a, b in zip(path[:-1], path[1:]):
                ga, gb = int(isl.vmap[a]), int(isl.vmap[b])
                if ga != gb:
                    seams.add((min(ga, gb), max(ga, gb)))
                    added += 1
            report.append({"island": isl.name, "euler": chi, "added": added, "loops": len(loops)})
            changed = True
        if not changed:
            break
    return seams, report


def slivers(faces, part, xyz, seams):
    """The islands under ``MIN_ISLAND_FACES`` faces: [{name, faces}] (reported, never relabelled)."""
    return [{"name": i.name, "faces": len(i.faces)}
            for i in uvp.split_islands(len(xyz), faces, part, seams, xyz=xyz) if len(i.faces) < MIN_ISLAND_FACES]


def axes(kind, f, joints, info):
    """{part id: (up, axis_p, axis_d | None)} for ``uv_pattern.orient`` (decision D1: gloves fingers up)."""
    cx, cy = float(info["cx"]), float(info["cy"])
    up = (0.0, 0.0, 1.0)
    vert = (up, (cx, cy, 0.0), None)
    out = {}
    if kind == "trousers" or boxers(kind, f) or kind == "tights":
        for s, nm in ((1, "l"), (-1, "r")):
            hip, _n, ankle = _leg_plane(joints, s)
            ax = (up, tuple(hip), tuple(ankle - hip))
            for name in ("front_", "back_", "leg_"):
                out[P[name + nm]] = ax
    if kind in ("briefs", "tights"):
        out[P["front"]] = vert
        out[P["back"]] = vert
        crotch = float(info["crotch_z"])
        out[P["gusset"]] = ((0.0, -1.0, 0.0), (cx, cy, crotch + 0.08), (1.0, 0.0, 0.0))
    if kind == "bra":
        out[P["front"]] = vert
        out[P["back"]] = vert
        out[P["gore"]] = vert
        under = float(info["under_z"])
        for nm in ("l", "r"):
            a = np.asarray(info["apex"][nm], float)
            cup = (up, (float(a[0]), float(a[1]) + 0.12, float(a[2])), None)
            out[P["cup_" + nm]] = cup
            out[P["cup_top_" + nm]] = cup
            out[P["strap_" + nm]] = ((0.0, -1.0, 0.0), (cx, cy, under), (1.0, 0.0, 0.0))
    if kind == "gloves":
        for s, nm in ((1, "l"), (-1, "r")):
            sd = "Left" if s > 0 else "Right"
            fa, hd = np.asarray(joints[sd + "ForeArm"], float), np.asarray(joints[sd + "Hand"], float)
            ax = (tuple(hd - fa), tuple(fa), tuple(hd - fa))
            out[P["glove_back_" + nm]] = ax
            out[P["palm_" + nm]] = ax
            t2, d, _n, _h = _thumb(joints, s)
            out[P["thumb_" + nm]] = (tuple(d), tuple(t2), tuple(d))
    return out


def ring_centres(faces, part, xyz):
    """The axis points of the ring parts, from the labelled geometry: {"vertical": (x, y) — the middle of the bbox of
    every vertical ring part's vertices together (the waistband, the bra band halves, the hip bands: a half ring's own
    mean lies off the axis), part id: mean of the part's vertices (a closed limb ring: a cuff, a top band)}. A bone
    or Spine1's head lies off the middle of the cloth (Glut's bra band round Spine1's y: area ratio 2.40)."""
    xyz = np.asarray(xyz, float)
    part = np.asarray(part)
    vert_ids = {P[n] for n in ("waistband", "band_l", "band_r", "hip_band_l", "hip_band_r")}
    limb_ids = {P[n] for n in ("cuff_l", "cuff_r", "top_band_l", "top_band_r")}
    out = {}
    vs = sorted({v for f, p in zip(faces, part) if int(p) in vert_ids for v in f})
    if vs:
        lo, hi = xyz[vs, :2].min(0), xyz[vs, :2].max(0)
        out["vertical"] = tuple(float(v) for v in (lo + hi) / 2)
    for pid in limb_ids:
        vl = sorted({v for f, p in zip(faces, part) if int(p) == pid for v in f})
        if vl:
            out[pid] = tuple(float(v) for v in xyz[vl].mean(0))
    return out


def rings(kind, f, joints, info):
    """{part id: (axis_p, axis_d, cut_dir)} for ``uv_pattern.ring_strip_uv`` (decision D6): the waistband and the
    bra band / hip bands round the vertical line through (cx, cy), opened at the back; a cuff / top band round its
    limb's axis, opened at the inseam (legs) or behind the arm (gloves)."""
    cx, cy = float(info["cx"]), float(info["cy"])
    rc = info.get("ring_centres") or {}
    vx, vy = rc.get("vertical", (cx, cy))
    vert = ((vx, vy, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))
    out = {P[n]: vert for n in ("waistband", "band_l", "band_r", "hip_band_l", "hip_band_r")}
    if kind in ("trousers", "tights"):
        for s, nm in ((1, "l"), (-1, "r")):
            hip, _n, ankle = _leg_plane(joints, s)
            sd = "Left" if s > 0 else "Right"
            knee = np.asarray(joints[sd + "Leg"], float)
            cuff, band = P["cuff_" + nm], P["top_band_" + nm]
            out[cuff] = (rc.get(cuff, tuple(ankle)), tuple(knee - ankle), (-float(s), 0.0, 0.0))
            out[band] = (rc.get(band, tuple(hip)), tuple(hip - ankle), (-float(s), 0.0, 0.0))
    if kind == "gloves":
        for s, nm in ((1, "l"), (-1, "r")):
            p, u = info.get("cuff_plane", {}).get(str(s), (None, None))
            if p is not None:
                out[P["cuff_" + nm]] = (rc.get(P["cuff_" + nm], tuple(p)), tuple(u), (0.0, 1.0, 0.0))
    return out


def rows(kind, f):
    """The atlas rows (``uv_pattern.ROWS``): boxers take the trousers' rows, a bandeau its own."""
    if boxers(kind, f):
        return uvp.ROWS["boxers"]
    if kind == "bra" and f.get("style") == "bandeau":
        return uvp.ROWS["bandeau"]
    return uvp.ROWS[kind]
