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


def rim_share(x, ends_x, corner, lower_side):
    """The jaw share fixed on the cut's rim at world x: the lower rim carries 1 and the upper rim 0, and within
    ``corner`` of the path's ends (``ends_x``) both meet at 1/2 by a smoothstep — the opening closes like a lens."""
    x = np.asarray(x, float)
    t = _sstep(np.minimum(np.abs(x - ends_x[0]), np.abs(x - ends_x[1])) / corner)
    return .5 + .5 * t if lower_side else .5 - .5 * t
