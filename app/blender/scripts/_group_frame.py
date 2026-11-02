"""The frame of reference and the contact fit of a MULTI-ROLE clip — plain
math, no bpy, so ``scripts/smoke_group_frame.py`` checks it by hand.

A pair is the case N = 2 and comes out exactly as before the group
generalisation (plan-gruppen-animationen.md, G1): every rule below reduces
to the old pair rule for two roles. Roles are the letters ``a``..``e`` in
order; ``a`` is the HUB — the one the frame turns on and the one every other
role is fitted to first.

Frame (``frame``):
* anchor frame: the frame where everybody is closest to A — the smallest
  sum of the distances A → role over the other roles (for a pair: the
  smallest A–B distance), unless the caller names ``anchor_s``;
* rotation: A → B onto +X, then the import dial ``yaw_deg``
  (``theta = atan2(bz - az, bx - ax) + yaw``, a rotation about +Y with the
  right-handed convention of ``mathutils.Matrix.Rotation(theta, 3, "Y")``:
  ``x' = c·x + s·z``, ``z' = -s·x + c·z``);
* origin: the CENTROID of all roots at the anchor frame (for a pair: the
  midpoint of A and B).

Contact fit (``fit``): the rig's arms are not the actors', so a hand that
touched something in the source stands off it on the rig. Per role the
closest contact — a HAND on a hand, an upper arm, the head or the hips —
is measured on the actors and on the rig at the anchor frame, and the rig
gap is closed by moving the role horizontally along the rig contact line:
* a pair splits the gap, each half moves half of it toward the other (the
  rule since the first pair import);
* a group grows from A: of the roles not fitted yet, the one with the
  closest ACTOR contact to an already fitted role goes next and moves by
  the whole remaining gap toward that role (measured against where that
  role already stands after its own fit) — A itself never moves, so every
  contact closes once and no role is pulled twice.
"""
import math

ROLES = ("a", "b", "c", "d", "e")

#: Contact points per figure: the rig bone name and the CMU joint name. A
#: contact needs a HAND on at least one side.
HANDS = {"LeftHand": "lhand", "RightHand": "rhand"}
TARGETS = {**HANDS, "LeftArm": "lhumerus", "RightArm": "rhumerus",
           "Head": "head", "Hips": "root"}


def rotate_y(theta, x, z):
    """``Matrix.Rotation(theta, 3, "Y") @ (x, 0, z)`` → ``(x', z')``."""
    c, s = math.cos(theta), math.sin(theta)
    return c * x + s * z, -s * x + c * z


def anchor_index(roots, fps, anchor_s=None):
    """The anchor frame of ``roots`` (``{role: [(x, z) per frame]}``)."""
    n = min(len(v) for v in roots.values())
    if anchor_s is not None:
        return min(n - 1, int(round(float(anchor_s) * fps)))
    others = [r for r in sorted(roots) if r != "a"]

    def spread(i):
        ax, az = roots["a"][i]
        return sum(math.dist((ax, az), roots[r][i]) for r in others)

    return min(range(n), key=spread)


def frame(at_anchor, yaw_deg=0.0):
    """``(theta, (mx, mz))`` for the roots at the anchor frame
    (``{role: (x, z)}``): every point is mapped by ``rotate_y(theta) - m``."""
    (ax, az), (bx, bz) = at_anchor["a"], at_anchor["b"]
    theta = math.atan2(bz - az, bx - ax) + math.radians(float(yaw_deg or 0.0))
    n = len(at_anchor)
    cx = sum(p[0] for p in at_anchor.values()) / n
    cz = sum(p[1] for p in at_anchor.values()) / n
    return theta, rotate_y(theta, cx, cz)


def place(theta, m, x, z):
    """A source point in the clip frame."""
    rx, rz = rotate_y(theta, x, z)
    return rx - m[0], rz - m[1]


def _closest(actor_a, actor_b):
    """``(distance, bone_a, bone_b)`` of the closest contact between two
    figures (``{bone: (x, y, z)}`` keyed by the rig bone name)."""
    best = None
    for ha, pa in actor_a.items():
        for hb, pb in actor_b.items():
            if ha not in HANDS and hb not in HANDS:
                continue
            d = math.dist(pa, pb)
            if best is None or d < best[0]:
                best = (d, ha, hb)
    return best


def fit(actor, rig):
    """Offsets ``{role: (dx, dz)}`` (cm) and the contact records.

    ``actor`` / ``rig``: ``{role: {bone: (x, y, z)}}`` at the anchor frame,
    the bones of ``TARGETS``, in the clip frame. Returns ``(offsets,
    contacts)`` with ``contacts = {role: {"to", "hands", "actor_cm",
    "rig_cm", "shift_cm"}}`` for every moved or measured role but A.
    """
    roles = [r for r in ROLES if r in actor]
    offsets = {r: (0.0, 0.0) for r in roles}
    contacts = {}
    if len(roles) == 2:
        a, b = roles
        d, ha, hb = _closest(actor[a], actor[b])
        ra, rb = rig[a][ha], rig[b][hb]
        rig_d = math.dist(ra, rb)
        vx, vz = rb[0] - ra[0], rb[2] - ra[2]
        length = math.hypot(vx, vz)
        delta = rig_d - d
        if length > 1e-6 and delta > 0:
            ux, uz = vx / length, vz / length
            offsets[a] = (ux * delta / 2, uz * delta / 2)
            offsets[b] = (-ux * delta / 2, -uz * delta / 2)
        contacts[b] = {"to": a, "hands": [ha, hb], "actor_cm": d, "rig_cm": rig_d,
                       "shift_cm": max(delta, 0.0)}
        return offsets, contacts
    fitted = [roles[0]]
    todo = roles[1:]
    while todo:
        best = None
        for r in todo:
            for s in fitted:
                d, hs, hr = _closest(actor[s], actor[r])
                key = (d, roles.index(r), roles.index(s))
                if best is None or key < best[0]:
                    best = (key, r, s, hs, hr)
        (d, _ri, _si), r, s, hs, hr = best
        ox, oz = offsets[s]
        ps = rig[s][hs]
        ps = (ps[0] + ox, ps[1], ps[2] + oz)
        pr = rig[r][hr]
        rig_d = math.dist(pr, ps)
        vx, vz = ps[0] - pr[0], ps[2] - pr[2]
        length = math.hypot(vx, vz)
        delta = rig_d - d
        if length > 1e-6 and delta > 0:
            offsets[r] = (vx / length * delta, vz / length * delta)
        contacts[r] = {"to": s, "hands": [hs, hr], "actor_cm": d, "rig_cm": rig_d,
                       "shift_cm": max(delta, 0.0)}
        fitted.append(r)
        todo.remove(r)
    return offsets, contacts
