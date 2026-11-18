"""The pure half of the mouth channel build (``mouth_part.py``, Ruling A203): numpy only, no bpy — the Blender
script imports it, and ``scripts/smoke_mouth_math.py`` checks it by hand without Blender."""
import numpy as np


def _smooth(values, n):
    """Running mean over ``n`` samples, ignoring NaN."""
    if n <= 1:
        return np.asarray(values, float)
    values = np.asarray(values, float)
    ok = np.isfinite(values)
    kernel = np.ones(n)
    total = np.convolve(np.where(ok, values, 0.), kernel, mode='same')
    count = np.convolve(ok.astype(float), kernel, mode='same')
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def lip_row(lum, red, v, nose, chin, line):
    """The lip line's row: ``(index, contrast)`` or a reason string. ``lum`` the band's luminance and ``red`` its
    red minus green per row (rows ascending in ``v``), ``nose`` / ``chin`` the rows' heights. Line contrast = the
    mean of the rows ``line.span`` above and below minus the row itself; the score weighs it by a Gaussian of
    ``line.prior_sigma`` x span around ``chin + line.prior`` x span and by 1 + ``line.red_gain`` x q, q = the
    redness (smoothed over 6 mm) minus its median between chin and nose, over its range there. Pure (the smoke
    derives a case by hand)."""
    step = float(v[1] - v[0])
    span = nose - chin
    if span <= .02:
        return 'no room between chin and nose'
    k = max(1, int(round(line['span'] / step)))
    smooth = _smooth(lum, max(1, int(round(.0015 / step))))
    contrast = np.full(len(v), np.nan)
    contrast[k:-k] = (smooth[2 * k:] + smooth[:-2 * k]) / 2 - smooth[k:-k]
    inside = (v > chin + .01) & (v < nose - .01) & np.isfinite(contrast)
    if not inside.any():
        return 'no rows between chin and nose'
    prior = np.exp(-.5 * ((v - (chin + line['prior'] * span)) / (line['prior_sigma'] * span)) ** 2)
    around = _smooth(red, max(1, int(round(.006 / step))))
    spread = float(np.nanmax(around[inside]) - np.nanmin(around[inside]))
    q = (around - np.nanmedian(around[inside])) / spread if spread > 1e-6 else np.zeros(len(v))
    score = np.where(inside, contrast * prior * np.clip(1 + line['red_gain'] * np.nan_to_num(q), 0, None), -np.inf)
    index = int(np.argmax(score))
    if contrast[index] < line['min_contrast']:
        return 'no lip line (contrast %.3f)' % contrast[index]
    return index, float(contrast[index])


def track_line(lum, start_row, start_col, line, step_s, step_v):
    """Follow the dark line sideways from ``(start_row, start_col)`` of the luminance grid ``lum`` (rows v, columns
    s): per column the darkest of the rows within one millimetre of the last, with its line contrast. Returns
    ``(columns, rows, contrasts)`` over the whole reach ``line.half_max`` plus a margin, sorted by column."""
    reach = int(round((line['half_max'] + .006) / step_s))
    k = max(1, int(round(.0035 / step_v)))
    near = max(1, int(round(.001 / step_v)))
    blur = np.stack([_smooth(_smooth(lum[:, j], 3), 1) for j in range(lum.shape[1])], 1)
    blur = np.stack([_smooth(blur[i], 3) for i in range(blur.shape[0])], 0)
    out = {}
    for direction in (1, -1):
        row = start_row
        for n in range(0 if direction == 1 else 1, reach + 1):
            col = start_col + direction * n
            if not 0 <= col < lum.shape[1]:
                break
            lo, hi = max(k, row - near), min(lum.shape[0] - k - 1, row + near)
            if lo > hi:
                break
            cand = blur[lo:hi + 1, col]
            if not np.isfinite(cand).any():
                break
            # The darkest row; a tie keeps the row nearest to the last one.
            order = np.lexsort((np.abs(np.arange(lo, hi + 1) - row), np.where(np.isfinite(cand), cand, np.inf)))
            row = lo + int(order[0])
            around = (blur[row + k, col] + blur[row - k, col]) / 2
            out[col] = (row, float(around - blur[row, col]) if np.isfinite(around) else 0.)
    cols = np.array(sorted(out))
    return cols, np.array([out[c][0] for c in cols]), np.array([out[c][1] for c in cols])


def corners(cols, contrasts, start_col, line, step_s):
    """The mouth corners ``(left column, right column)``: going out from ``start_col``, the last column before the
    contrast (median of three) stays under ``line.corner`` x the central contrast (the median within 8 mm of the
    start) for three columns; never past ``line.half_max``."""
    med = np.array([np.median(contrasts[max(0, i - 1):i + 2]) for i in range(len(contrasts))])
    centre = float(np.median(med[np.abs(cols - start_col) * step_s <= .008]))
    limit = line['corner'] * centre
    ends = []
    for direction in (-1, 1):
        last, low = start_col, 0
        for n in range(1, int(round(line['half_max'] / step_s)) + 1):
            col = start_col + direction * n
            hit = np.nonzero(cols == col)[0]
            if not len(hit):
                break
            if med[hit[0]] < limit:
                low += 1
                if low >= 3:
                    break
            else:
                low, last = 0, col
        ends.append(last)
    return ends[0], ends[1]


def ring_depths(depth, rings):
    """The pouch's ring depths: 0, then steps growing by ``rings.growth`` from ``rings.first``, ending at
    ``depth`` (a last step under half the growing one is merged into the one before)."""
    out, step = [0.], rings['first']
    while out[-1] + step < depth - step / 2:
        out.append(out[-1] + step)
        step *= rings['growth']
    out.append(depth)
    return out


def jaw_hinge(opening, hips, head, jaw):
    """The jaw's hinge point: ``jaw.back`` behind (+Y) and ``jaw.up`` above (+Z) the opening, both scaled by the
    body's Hips-to-Head distance over ``jaw.reference``, clamped to ``jaw.scale``."""
    k = float(np.clip(np.linalg.norm(np.asarray(head) - np.asarray(hips)) / jaw['reference'], *jaw['scale']))
    return np.asarray(opening, float) + np.array([0., jaw['back'] * k, jaw['up'] * k]), k


def lower_follow(d, depth):
    """How much of the jaw's turn the pouch's lower wall takes at depth ``d``: 1 at the lips, 0 at the back."""
    return 1. - _sstep(np.asarray(d, float) / depth)


def turned(points, hinge, angle):
    """``points`` (n x 3) turned about the side axis (+X) through ``hinge`` by ``angle`` (radians, per point or
    one): positive opens the jaw (the front goes down)."""
    points = np.asarray(points, float)
    rel = points - hinge
    a = np.broadcast_to(np.asarray(angle, float), (len(points),))
    c, s_ = np.cos(a), np.sin(a)
    out = rel.copy()
    out[:, 1] = rel[:, 1] * c - rel[:, 2] * s_
    out[:, 2] = rel[:, 1] * s_ + rel[:, 2] * c
    return out + hinge


def _sstep(x):
    x = np.clip(x, 0., 1.)
    return x * x * (3 - 2 * x)


def lip_fillet(t, radius, on_wall):
    """The move of a point at distance ``t`` from the cut's corner onto the fillet of ``radius`` that rounds it:
    ``(back, into)`` — back along the channel's wall and into the lip (down the skin). ``on_wall`` False = a skin
    point (t down the skin from the rim), True = a wall point (t back from the rim). With the corner at the origin,
    the skin along +into and the wall along +back, the arc is (r - r cos a, r - r sin a), a = 0 at the skin's
    tangent point (0, r) and 90 degrees at the wall's (r, 0): a skin point takes a = 45 deg (1 - t/r), a wall point
    90 deg minus that, so the corner itself (t = 0) lands on the arc's middle from both sides. (0, 0) from r on."""
    if t >= radius or radius <= 0:
        return 0., 0.
    a = np.pi / 4 * (1 - t / radius)
    if on_wall:
        a = np.pi / 2 - a
        return float(radius - radius * np.cos(a) - t), float(radius - radius * np.sin(a))
    return float(radius - radius * np.cos(a)), float(radius - radius * np.sin(a) - t)


def rim_share(x, ends_x, corner, lower_side):
    """The jaw share fixed on the cut's rim at world x: the lower rim carries 1 and the upper rim 0, and within
    ``corner`` of the path's ends (``ends_x``) both meet at 1/2 by a smoothstep — the opening closes like a lens."""
    x = np.asarray(x, float)
    t = _sstep(np.minimum(np.abs(x - ends_x[0]), np.abs(x - ends_x[1])) / corner)
    return .5 + .5 * t if lower_side else .5 - .5 * t


# THE TEETH (Ruling A206): the pure half of ``mouth_teeth.py``. Millimetre tables, metre results.

#: Per arch, from the midline outward: (kind, mesio-distal width, crown height, labio-lingual thickness) in mm —
#: the anatomical means of the permanent dentition (upper central incisor 8.5 x 10.5).
UPPER_TEETH = (('incisor', 8.5, 10.5, 7.0), ('incisor', 6.5, 9.0, 6.0), ('canine', 7.5, 10.0, 8.0),
               ('premolar', 7.0, 8.0, 9.0), ('premolar', 6.5, 7.5, 9.0))
LOWER_TEETH = (('incisor', 5.0, 9.0, 6.0), ('incisor', 5.5, 9.5, 6.0), ('canine', 7.0, 11.0, 7.5),
               ('premolar', 7.0, 8.0, 7.5), ('premolar', 7.0, 8.0, 8.0))
#: The molar block closing each side of an arch: (width, crown height, thickness) in mm.
UPPER_MOLAR = (10.0, 7.0, 10.0)
LOWER_MOLAR = (11.0, 7.0, 10.0)
#: The mouth half width the tables are drawn for (m), and the clamp of the mouth's scale against it.
TEETH_REFERENCE_HALF_WIDTH = .0265
TEETH_SCALE_CLAMP = (.85, 1.15)


def teeth_scale(half_width, size=1.):
    """The teeth's scale: the measured mouth half width over ``TEETH_REFERENCE_HALF_WIDTH`` (clamped to
    ``TEETH_SCALE_CLAMP``) times the character's ``size`` option."""
    return float(np.clip(half_width / TEETH_REFERENCE_HALF_WIDTH, *TEETH_SCALE_CLAMP)) * float(size)


def channel_half_width(d, widest, radius, taper):
    """The pouch's half width at depth ``d``: from the mouth's ``widest`` to ``radius`` by a smoothstep over
    ``taper`` (the ring rule of ``mouth_part.build``)."""
    return widest * (1 + (radius / widest - 1) * _sstep(np.asarray(d, float) / taper))


def arch_curve(d0, front_w, front_l, limit, d_max, step=.0005):
    """One half of a teeth arch's LABIAL line (x >= 0): samples ``(x, d, s)`` — side offset, depth behind the
    opening, arc length from the midline. The front is the parabola x = front_w sqrt((d - d0) / front_l) from the
    midline at depth ``d0``, capped by the narrowest ``limit`` (the channel's half width less the margin) from ``d``
    back to ``d_max``: the arch follows the channel but never narrows toward the back (a narrowing arch lines its
    back teeth up behind the canines); it runs to ``d_max``."""
    d = np.arange(d0, d_max + step / 2, step)
    cap = np.minimum.accumulate(np.asarray(limit(d), float)[::-1])[::-1]
    x = np.minimum(front_w * np.sqrt(np.clip((d - d0) / front_l, 0, None)), cap)
    x = np.maximum(x, 0.)
    s = np.concatenate([[0.], np.cumsum(np.hypot(np.diff(x), np.diff(d)))])
    return x, d, s


def tooth_spans(widths, total):
    """Where each tooth sits along the half arch: ``[(start, end)]`` arc lengths, the teeth side by side from the
    midline; the last entry (the molar block) is cut back to ``total`` when the arch is shorter. Teeth that start
    past ``total`` are left out."""
    out, at = [], 0.
    for w in widths:
        if at >= total - 1e-9:
            break
        out.append((at, min(at + w, total)))
        at += w
    return out


def teeth_gap(upper_tip, lower_tip, hinge, theta, up):
    """The free height between the upper and the lower incisal edge with the jaw turned by ``theta`` (radians)
    about the side axis through ``hinge``: (upper - lower turned) along ``up`` (metres; negative = they overlap)."""
    lower = turned(np.asarray(lower_tip, float)[None], np.asarray(hinge, float), theta)[0]
    return float((np.asarray(upper_tip, float) - lower) @ np.asarray(up, float))
