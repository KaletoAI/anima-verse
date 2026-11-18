"""Puts the fingers of a rigged humanoid back where the mesher had them — numpy only, no bpy.

WHY. The external rigger (Make-It-Animatable behind ``mesh-mia``) does not only place joints: it re-poses the
mesh into its own rest, and for some figures it bends the FINGERS relative to the palm while doing so (hand
analysis 2026-11-18, § 1.3: Dario, Gelina, Arvid and Friedrich median 10-40 mm per finger, axis turns up to
149 deg, hooks and fanned fingers the mesher never made; Ines and Jonas not moved at all, <= 1 mm). The
unrigged mesh is the ground truth of the hand, exactly as it is of the trunk for normalize's posture restore.

WHAT. Per hand:
  1. Vertex correspondence by UV (the rigger keeps the topology and the UVs): a rigged vertex maps to the ONE
     source vertex whose UV lies within ``UV_EPS``; two or none = no match (the hand analysis' rule,
     99.9 % unique).
  2. A similarity fit (rotation + uniform scale + translation, Umeyama) of the source PALM onto the rigged palm
     — the palm is what the rigger did not bend (vertices skinned mostly to the Hand bone near its joint). It
     carries the source into the rigged model's scale, place and wrist attitude.
  3. Un-pose: per finger chain, parent first, the rotation about the (already moved) joint that best carries
     the bone's own vertices onto their source positions (Kabsch with a fixed pivot). The skin follows by
     linear blend skinning with the EXISTING weights, so the blend at the knuckles and webs is the rig's own;
     each joint head moves with its parent bone, so the joint stays at the same place inside its finger.
  4. Snap: every matched vertex goes the rest of the way to its source position, by its finger share (a palm
     vertex keeps its place, a pure finger vertex lands exactly where the mesher had it).
Nothing else changes: weights, bone names, hierarchy and every joint's REST ROTATION stay; only the finger
joints' positions and the hand's vertices move (the client's rest correction and the joint-frame gate of
``refine.apply_script`` compare rotations only — ``model_validate.rig_frames_preserved``).

GATE (per hand; a hand that fails keeps the rigger's version — a post-step never discards the main product):
  * trigger: the rigger moved some finger chain by a median of at least ``TRIGGER_M`` (below: untouched),
  * direction spread of the four long fingers (largest pairwise angle) and their elevation range against the
    palm plane must not grow by more than ``ANGLE_TOL_DEG``; the palm roll must not grow either,
  * curl test: bending each chain by 30 deg per joint (the clients' world rotation about the front axis) must
    still move its own finger's distal part by half the chain length and every other finger's by under 25 %;
    the pass count must not drop,
  * gaps: neighbouring fingers that were apart (>= ``GAP_M`` between their distal halves) stay apart,
  * stretch: no edge of the hand longer than ``STRETCH_MAX`` times the LONGER of its two measured lengths
    (rigged, mesher scaled) — undoing the rigger's bend gives back the mesher's own edge lengths, which the
    rigger had squashed at the knuckles by up to 5x, so the rigged length alone would refuse every reset; what
    this catches is an edge that neither measured shape had (a wrong match, a torn blend),
  * the transition band (vertices partly skinned to a finger) keeps its surface continuous: its 99th
    percentile normal break (dihedral angle across an edge) must not grow by more than ``BAND_TOL_DEG``,
  * self-intersections (counted by the caller, which has a BVH) must not grow.

All lengths are metres of the model as handed in (normalize has already scaled it to the real height).
"""
import math

import numpy as np

FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
LONG = ("Index", "Middle", "Ring", "Pinky")
SIDES = ("Left", "Right")

UV_EPS = 2e-5             # one source UV within this = a match (hand analysis stagediff rule)
PALM_HAND_SHARE = 0.5     # palm vertex: at least half its weight on the Hand bone ...
PALM_FINGER_SHARE = 0.1   # ... under 10 % on the fingers together (the rigger skins most palm meat to them) ...
PALM_RADIUS_H = 0.08      # ... and within 8 % of the body height of the Hand joint (not the forearm)
REGION_RADIUS_H = 0.16    # the hand region: within 16 % of the height of the Hand joint (extract.py's window)
DOMINANT = 0.5            # a vertex belongs to a bone/chain when it carries at least half its weight
MIN_FIT_VERTS = 10        # fewer own vertices than this: the bone keeps its parent's motion
# Trigger. The noise floor of an UNMOVED hand (Ines, Jonas: the rigger moved nothing) after the palm fit is a
# per-chain median of 0.0-0.2 mm (measured 2026-11-18 on their prerig copies); the smallest real re-pose seen
# is Merle's thumb at 5-7 mm. 2 mm is ten times the noise and well under any real bend.
TRIGGER_M = 0.002
ANGLE_TOL_DEG = 1.0       # direction spread / elevation range / palm roll may not grow by more than this
CURL_DEG = 30.0           # per joint, cumulative (extract.py / the clients' fingers_curl)
CURL_TRAVEL = 0.5         # own distal part travels >= half the chain length ...
CURL_LEAK = 0.25          # ... others' distal parts under a quarter of the own travel
GAP_M = 0.001             # two finger surfaces closer than 1 mm touch
STRETCH_MAX = 1.3         # longest edge vs the longer of its two measured lengths
BAND_TOL_DEG = 10.0       # p99 normal break in the transition band may grow by at most this
MIN_EDGE_M = 2e-4         # edges shorter than 0.2 mm carry no length information


# --- correspondence ------------------------------------------------------------

def uv_match(src_uv, dst_uv, rows):
    """Index of the unique source vertex within ``UV_EPS`` of each ``dst_uv[rows]`` UV, -1 otherwise."""
    src_uv = np.asarray(src_uv, dtype=np.float64)
    ok = np.isfinite(src_uv).all(1)
    cell = np.floor(src_uv / UV_EPS).astype(np.int64)
    grid = {}
    for i in np.where(ok)[0]:
        grid.setdefault((int(cell[i, 0]), int(cell[i, 1])), []).append(int(i))
    out = np.full(len(dst_uv), -1, dtype=np.int64)
    for r in rows:
        uv = dst_uv[r]
        if not np.isfinite(uv).all():
            continue
        cu, cv = int(math.floor(uv[0] / UV_EPS)), int(math.floor(uv[1] / UV_EPS))
        near = []
        for du in (-1, 0, 1):
            for dv in (-1, 0, 1):
                for i in grid.get((cu + du, cv + dv), ()):
                    if math.hypot(src_uv[i, 0] - uv[0], src_uv[i, 1] - uv[1]) < UV_EPS:
                        near.append(i)
                        if len(near) > 1:
                            break
        if len(near) == 1:
            out[r] = near[0]
    return out


# --- small geometry --------------------------------------------------------------

def umeyama(P, Q):
    """(s, R, t) with Q ~ s R P + t, least squares."""
    mp, mq = P.mean(0), Q.mean(0)
    X, Y = P - mp, Q - mq
    U, S, Vt = np.linalg.svd(X.T @ Y / len(P))
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    s = float(np.trace(np.diag(S) @ D) / max((X ** 2).sum(1).mean(), 1e-18))
    return s, R, mq - s * R @ mp


def rotation_about(X, Y, pivot):
    """Rotation R about ``pivot`` minimising |R (X - p) - (Y - p)|."""
    U, _, Vt = np.linalg.svd((X - pivot).T @ (Y - pivot))
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    return Vt.T @ np.diag([1.0, 1.0, d]) @ U.T


def rigid(R, pivot):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = pivot - R @ pivot
    return M


def apply(T, X):
    return X @ T[:3, :3].T + T[:3, 3]


def axis_rotation(axis, degrees):
    x, y, z = np.asarray(axis, float) / np.linalg.norm(axis)
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def angle_deg(u, v):
    u = u / (np.linalg.norm(u) + 1e-12)
    v = v / (np.linalg.norm(v) + 1e-12)
    return float(np.degrees(np.arccos(np.clip(u @ v, -1.0, 1.0))))


def min_distance(A, B, chunk=2048):
    if len(A) == 0 or len(B) == 0:
        return float("inf")
    best = float("inf")
    for i in range(0, len(A), chunk):
        d = ((A[i:i + chunk, None, :] - B[None, :, :]) ** 2).sum(-1)
        best = min(best, float(d.min()))
    return math.sqrt(best)


def region_edges(tris, inside):
    t = tris[inside[tris].all(1)]
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    return t, np.unique(np.sort(e, 1), axis=0)


def dihedral(pos, t):
    """Per interior edge of triangles ``t`` the angle between its two faces' normals (deg) and the edge."""
    n = np.cross(pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-18
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    f = np.tile(np.arange(len(t)), 3)
    e = np.sort(e, 1)
    order = np.lexsort((e[:, 1], e[:, 0]))
    e, f = e[order], f[order]
    same = (e[1:] == e[:-1]).all(1)
    a, b = f[:-1][same], f[1:][same]
    cos = np.clip((n[a] * n[b]).sum(1), -1.0, 1.0)
    return np.degrees(np.arccos(cos)), e[:-1][same]


# --- the hand ---------------------------------------------------------------------

class Hand:
    """Everything about one side's skinning that the reset and the gate read."""

    def __init__(self, side, weights, wtot, heads, verts, height):
        self.side = side
        self.ok = all(f"{side.lower()}hand{f.lower()}{k}" in weights for f in FINGERS for k in (1, 2, 3)) \
            and f"{side.lower()}hand" in weights and f"{side.lower()}hand" in heads
        if not self.ok:
            return
        tot = np.maximum(np.asarray(wtot, float), 1e-12)
        self.bone = {(f, k): np.asarray(weights[f"{side.lower()}hand{f.lower()}{k}"], float) / tot
                     for f in FINGERS for k in (1, 2, 3)}
        self.hand_share = np.asarray(weights[f"{side.lower()}hand"], float) / tot
        self.finger_share = sum(self.bone.values())
        self.chain = {f: self.bone[(f, 1)] + self.bone[(f, 2)] + self.bone[(f, 3)] for f in FINGERS}
        self.heads = {(f, k): np.asarray(heads[f"{side.lower()}hand{f.lower()}{k}"], float)
                      for f in FINGERS for k in (1, 2, 3)}
        hand_joint = np.asarray(heads[f"{side.lower()}hand"], float)
        dist = np.linalg.norm(verts - hand_joint, axis=1)
        self.region = np.where(dist < REGION_RADIUS_H * height)[0]
        self.palm_rows = self.region[(self.hand_share[self.region] >= PALM_HAND_SHARE)
                                     & (self.finger_share[self.region] < PALM_FINGER_SHARE)
                                     & (dist[self.region] < PALM_RADIUS_H * height)]
        self.hand_joint = hand_joint
        # the curl turns a palm-down T-pose finger towards the palm (world -Z): left fingers point +X
        self.curl_axis = np.array([0.0, 1.0, 0.0]) if side == "Left" else np.array([0.0, -1.0, 0.0])


def finger_axes(hand, pos):
    """Where each finger points as a whole: from the centroid of its proximal phalanx to the centroid of its
    distal phalanx (vertices dominated by bone 1 / bone 3 that carry >= 90 % finger weight — no palm meat).

    Chosen over the principal axis of the whole chain (which the knuckle and palm meat pull towards the hand)
    and over the hand analysis' geometric base direction (its finger detection jumps between segmentations on
    unusual hands — Hannibal R 0 -> 54 deg for a sub-millimetre change); measured 2026-11-18 on 18 hands."""
    out = {}
    reg = hand.region
    for f in FINGERS:
        c = []
        for k in (1, 3):
            rows = reg[(hand.bone[(f, k)][reg] >= DOMINANT) & (hand.finger_share[reg] >= 0.9)]
            if len(rows) < 5:
                break
            c.append(pos[rows].mean(0))
        if len(c) == 2 and np.linalg.norm(c[1] - c[0]) > 1e-6:
            out[f] = (c[1] - c[0]) / np.linalg.norm(c[1] - c[0])
    return out


def palm_normal(hand, pos):
    P = pos[hand.palm_rows]
    if len(P) < 3:
        return None
    _, _, vt = np.linalg.svd(P - P.mean(0), full_matrices=False)
    n = vt[2]
    return n if n[2] <= 0 else -n         # palm-down convention: the palmar normal points to world -Z


def direction_metrics(hand, pos):
    axes = finger_axes(hand, pos)
    long_axes = [axes[f] for f in LONG if f in axes]
    n = palm_normal(hand, pos)
    spread = max((angle_deg(a, b) for i, a in enumerate(long_axes) for b in long_axes[i + 1:]), default=0.0)
    elev = [math.degrees(math.asin(float(np.clip(a @ -n, -1, 1)))) for a in long_axes] if n is not None else []
    return {"spread_deg": round(spread, 2),
            "elev_range_deg": round(max(elev) - min(elev), 2) if elev else 0.0,
            "palm_roll_deg": round(angle_deg(n, np.array([0.0, 0.0, -1.0])), 2) if n is not None else None}


def curl_pass(hand, pos, heads):
    """Per chain: does a 30-deg-per-joint curl move its own distal part and nothing else's? (numpy LBS, the
    rule of the hand analysis' extract.py / proto_refit.py)."""
    rows = hand.region
    distal = {f: rows[(hand.bone[(f, 2)][rows] + hand.bone[(f, 3)][rows]) >= DOMINANT] for f in FINGERS}
    out = {}
    for f in FINGERS:
        moved = np.zeros((len(rows), 3))
        # cumulative world rotation per joint, pivot at the posed head (extract.apply_deformations)
        mats = []
        for k in (1, 2, 3):
            h = heads[(f, k)]
            Rk = axis_rotation(hand.curl_axis, CURL_DEG * k)
            hp = h if not mats else apply(mats[-1], h[None])[0]
            M = np.eye(4)
            M[:3, :3] = Rk
            M[:3, 3] = hp - Rk @ h
            mats.append(M)
        for k, M in zip((1, 2, 3), mats):
            w = hand.bone[(f, k)][rows][:, None]
            moved += w * (apply(M, pos[rows]) - pos[rows])
        disp = np.linalg.norm(moved, axis=1)
        index = {r: i for i, r in enumerate(rows.tolist())}
        own = np.array([index[r] for r in distal[f].tolist()], dtype=np.int64)
        if len(own) < MIN_FIT_VERTS:
            out[f] = False
            continue
        own_rows = hand.region[hand.chain[f][hand.region] >= DOMINANT]
        length = float(np.linalg.norm(pos[own_rows] - heads[(f, 1)], axis=1).max()) if len(own_rows) else 0.0
        own_mean = float(disp[own].mean())
        ok = length > 0 and float(np.percentile(disp[own], 95)) >= CURL_TRAVEL * length
        for g in FINGERS:
            if g == f or len(distal[g]) == 0:
                continue
            other = np.array([index[r] for r in distal[g].tolist()], dtype=np.int64)
            if float(disp[other].mean()) >= CURL_LEAK * own_mean:
                ok = False
        out[f] = bool(ok)
    return out


def gaps(hand, pos):
    """Smallest distance between the distal halves of neighbouring fingers (m)."""
    rows = hand.region
    distal = {f: rows[(hand.bone[(f, 2)][rows] + hand.bone[(f, 3)][rows]) >= DOMINANT] for f in FINGERS}
    return {f"{a}-{b}": min_distance(pos[distal[a]], pos[distal[b]])
            for a, b in zip(FINGERS[:-1], FINGERS[1:])}


def measure(hand, pos, heads, tris):
    out = direction_metrics(hand, pos)
    curl = curl_pass(hand, pos, heads)
    out["curl"] = curl
    out["curl_pass"] = sum(curl.values())
    out["gaps_mm"] = {k: round(v * 1000, 2) for k, v in gaps(hand, pos).items()}
    inside = np.zeros(len(pos), bool)
    inside[hand.region] = True
    t, _ = region_edges(tris, inside)
    ang, e = dihedral(pos, t)
    fs = hand.finger_share
    band = ((fs[e[:, 0]] > 0.02) & (fs[e[:, 0]] < 0.98)) | ((fs[e[:, 1]] > 0.02) & (fs[e[:, 1]] < 0.98))
    out["band_break_p99_deg"] = round(float(np.percentile(ang[band], 99)), 1) if band.any() else 0.0
    out["band_break_max_deg"] = round(float(ang[band].max()), 1) if band.any() else 0.0
    return out


def restore_side(hand, verts, tris, src_verts, match):
    """Candidate positions + joint heads of one hand, and the numbers that describe the move."""
    reg = hand.region
    palm = hand.palm_rows[match[hand.palm_rows] >= 0]
    info = {"palm_vertices": int(len(palm))}
    if len(palm) < 3 * MIN_FIT_VERTS:
        info["error"] = "too few matched palm vertices"
        return None, None, info
    s, R, t = umeyama(src_verts[match[palm]], verts[palm])
    target = np.full((len(verts), 3), np.nan)
    m = reg[match[reg] >= 0]
    target[m] = s * src_verts[match[m]] @ R.T + t
    info["palm_fit_rms_mm"] = round(float(np.sqrt(np.mean(np.sum((target[palm] - verts[palm]) ** 2, 1)))) * 1000, 2)
    info["matched_share"] = round(float(len(m)) / max(len(reg), 1), 4)
    disp = {}
    for f in FINGERS:
        rows = reg[(hand.chain[f][reg] >= DOMINANT) & (match[reg] >= 0)]
        disp[f] = float(np.median(np.linalg.norm(verts[rows] - target[rows], axis=1))) if len(rows) else 0.0
    info["displacement_mm"] = {f: round(v * 1000, 1) for f, v in disp.items()}
    info["max_displacement_mm"] = round(max(disp.values()) * 1000, 1)
    if max(disp.values()) < TRIGGER_M:
        return None, None, info
    new = verts.copy()
    heads = dict(hand.heads)
    acc = np.zeros((len(reg), 3))
    for f in FINGERS:
        T = np.eye(4)
        for k in (1, 2, 3):
            pivot = apply(T, hand.heads[(f, k)][None])[0]
            heads[(f, k)] = pivot
            rows = reg[(hand.bone[(f, k)][reg] >= DOMINANT) & (match[reg] >= 0)]
            if len(rows) >= MIN_FIT_VERTS:
                Rk = rotation_about(apply(T, verts[rows]), target[rows], pivot)
            else:
                Rk = np.eye(3)
            T = rigid(Rk, pivot) @ T
            acc += hand.bone[(f, k)][reg][:, None] * (apply(T, verts[reg]) - verts[reg])
    new[reg] = verts[reg] + acc
    ok = match[reg] >= 0
    r = reg[ok]
    new[r] += hand.finger_share[r][:, None] * (target[r] - new[r])
    left = []
    for f in FINGERS:
        rows = reg[(hand.chain[f][reg] >= DOMINANT) & (match[reg] >= 0)]
        if len(rows):
            left.append(float(np.median(np.linalg.norm(new[rows] - target[rows], axis=1))))
    info["displacement_left_mm"] = round(max(left, default=0.0) * 1000, 1)
    # stretch: against the LONGER of the two measured lengths (rigged, mesher scaled), and against the rigged
    inside = np.zeros(len(verts), bool)
    inside[reg] = True
    _, e = region_edges(tris, inside)
    l_rig = np.linalg.norm(verts[e[:, 0]] - verts[e[:, 1]], axis=1)
    l_new = np.linalg.norm(new[e[:, 0]] - new[e[:, 1]], axis=1)
    both = (match[e[:, 0]] >= 0) & (match[e[:, 1]] >= 0)
    l_src = l_rig.copy()
    l_src[both] = s * np.linalg.norm(src_verts[match[e[both, 0]]] - src_verts[match[e[both, 1]]], axis=1)
    keep = l_rig > MIN_EDGE_M
    info["stretch_max"] = round(float((l_new[keep] / np.maximum(l_rig[keep], l_src[keep])).max()), 3)
    info["stretch_vs_rigged_max"] = round(float((l_new[keep] / l_rig[keep]).max()), 3)
    info["stretch_vs_rigged_p99"] = round(float(np.percentile(l_new[keep] / l_rig[keep], 99)), 3)
    return new, heads, info


def judge(before, after, info, intersections=None):
    """Reasons why the reset is refused for this hand (empty = apply)."""
    why = []
    for key in ("spread_deg", "elev_range_deg"):
        if after[key] > before[key] + ANGLE_TOL_DEG:
            why.append(f"{key} {before[key]} -> {after[key]}")
    if before.get("palm_roll_deg") is not None and after.get("palm_roll_deg") is not None \
            and after["palm_roll_deg"] > before["palm_roll_deg"] + ANGLE_TOL_DEG:
        why.append(f"palm roll {before['palm_roll_deg']} -> {after['palm_roll_deg']}")
    if after["curl_pass"] < before["curl_pass"]:
        why.append(f"curl test {before['curl_pass']} -> {after['curl_pass']}")
    for pair, gap in before["gaps_mm"].items():
        if gap >= GAP_M * 1000 and after["gaps_mm"][pair] < GAP_M * 1000:
            why.append(f"fingers {pair} touch ({gap} -> {after['gaps_mm'][pair]} mm)")
    if info["stretch_max"] > STRETCH_MAX:
        why.append(f"edge stretch {info['stretch_max']}x")
    if after["band_break_p99_deg"] > before["band_break_p99_deg"] + BAND_TOL_DEG:
        why.append(f"band normal break p99 {before['band_break_p99_deg']} -> {after['band_break_p99_deg']} deg")
    if intersections is not None and intersections[1] > intersections[0]:
        why.append(f"self-intersections {intersections[0]} -> {intersections[1]}")
    return why


def restore(verts, tris, uv, weights, wtot, heads, src_verts, src_uv, *, intersections=None):
    """Both hands. ``weights``/``heads`` are keyed by normalised bone name (``lefthandindex1``).

    Returns ``(new_verts, new_heads, report)``: ``new_verts`` None when no hand changed; ``new_heads`` maps the
    normalised name of every moved finger joint to its new world head; ``report[side]`` says what happened.
    ``intersections(rows, before, after)`` -> (count_before, count_after), when the caller can count them.
    """
    verts = np.asarray(verts, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64)
    height = float(np.ptp(verts[:, 2])) if len(verts) else 0.0
    out = verts.copy()
    new_heads = {}
    report = {}
    changed = False
    for side in SIDES:
        hand = Hand(side, weights, wtot, heads, verts, height)
        if not hand.ok:
            report[side] = {"status": "skipped", "reason": "no finger bones"}
            continue
        match = uv_match(src_uv, uv, hand.region)
        cand, cand_heads, info = restore_side(hand, verts, tris, np.asarray(src_verts, float), match)
        entry = {k: v for k, v in info.items() if not k.startswith("_")}
        if cand is None:
            entry["status"] = "error" if info.get("error") else "untouched"
            if not info.get("error"):
                entry["reason"] = (f"rigger moved the fingers by at most {info['max_displacement_mm']} mm "
                                   f"(< {TRIGGER_M * 1000:.0f} mm)")
            report[side] = entry
            continue
        before = measure(hand, verts, hand.heads, tris)
        after = measure(hand, cand, cand_heads, tris)
        counts = intersections(hand.region, verts, cand) if intersections else None
        if counts is not None:
            entry["self_intersections"] = list(counts)
        why = judge(before, after, info, counts)
        entry["before"], entry["after"] = before, after
        if why:
            entry["status"] = "refused"
            entry["reason"] = "; ".join(why)
        else:
            entry["status"] = "applied"
            out[hand.region] = cand[hand.region]
            for (f, k), h in cand_heads.items():
                new_heads[f"{side.lower()}hand{f.lower()}{k}"] = h
            changed = True
        report[side] = entry
    return (out if changed else None), new_heads, report
