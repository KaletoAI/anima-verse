"""Plan group B, phase G — the corset top's darts and its back line, as construction ids of
``garment_template_build.wrap`` (pure Python, no bpy: ``scripts/smoke_corset_darts.py`` imports it).

A strapless top (a corset, a bustier) is two ``wrap`` panels: front = panel 0, back = panel 1, each ``rows`` x ``cols``
vertices (vertex ``p * rows * cols + r * cols + c``; row 0 the top edge, column c at the angle (pi or 0) +
pi * c / (cols - 1)). Over a lifted bust the front panel is no developable surface: flattened whole it measured stretch
p95 1.26-1.28 and area 0.97 (Rosi's Red Corset Top). Cut edges inside the panel (marked ``uv_seam``, the mesh stays
whole — only the UV opens) let it lie flat, as a sewn corset's seams do:

- the centre front from the top edge down ``CENTRE_SHARE`` of the panel (the sweetheart's middle seam);
- a bust dart either side, ``DART_COLS`` of 40 columns off the centre (8 * pi / 40 = 0.63 rad round the body: under
  the bust's apex), from the top edge down ``DART_SHARE``.

Measured on copies of Rosi's body (sweetheart 10 cm, lift 1.0): p95 1.262 -> 1.125, area 0.975 -> 0.994; on the plain
body 1.276 / 0.969 -> 1.187 / 0.986. A dart from the hem up gained nothing (1.258): the strain sits at the top edge.

The back line: the back panel's centre column, top to bottom — the placket line of a corset (a corset laces at the
back; the front has the centre cut).
"""

CENTRE_SHARE = 1.0 / 3.0
DART_SHARE = 1.0 / 6.0
#: Columns off the centre per 40 columns of a half panel.
DART_COLS = 8


def _column(rows: int, cols: int, c: int, n: int, base: int = 0) -> list:
    return [(base + r * cols + c, base + (r + 1) * cols + c) for r in range(min(n, rows - 1))]


def dart_seams(rows: int, cols: int) -> list:
    """The cut edges of the front panel (vertex-id pairs): the centre cut and the two bust darts."""
    c0 = (cols - 1) // 2
    n_c = centre_rows(rows)
    n_d = int(round((rows - 1) * DART_SHARE))
    off = int(round(DART_COLS * (cols - 1) / 40.0))
    out = _column(rows, cols, c0, n_c)
    for c in (c0 - off, c0 + off):
        out += _column(rows, cols, c, n_d)
    return out


#: Corset v3 (review 2026-11-22: the item's picture shows its seams and boning, the atlas was plain): the sewn seam
#: lines painted onto the cut atlas (``seam_lines`` -> the cut's ``marks.json`` ``seam_*`` lines ->
#: ``cut_texture_post.draw_seams``): on the front the continuation of each bust dart (``DART_COLS``) and one more
#: ``SEAM_FRONT_OUTER_COLS`` off the centre, on the back ``SEAM_BACK_COLS`` either side of the lacing; all top to hem
#: (columns per 40 of a half panel, as ``DART_COLS``).
SEAM_FRONT_OUTER_COLS = 16
SEAM_BACK_COLS = 10


def seam_lines(rows: int, cols: int, cup_rows: dict = None) -> dict:
    """``{name: (part, construction ids top to bottom)}`` of the painted seams (front = part 1, back = part 2, as the
    placket line ``centre_back``): ``seam_front_<k>`` / ``seam_back_<k>``, k left to right in column order.
    Corset v7 (review 2026-11-23: the item's picture shows a seam under each cup, the front's seams start there):
    ``cup_rows`` = {front column: row} of the line under the cups (``cup_seams``) — a front seam in such a column
    starts at that row instead of the top edge."""
    c0 = (cols - 1) // 2
    cup_rows = cup_rows or {}
    out = {}
    for part, base, offs in ((1, 0, (DART_COLS, SEAM_FRONT_OUTER_COLS)), (2, rows * cols, (SEAM_BACK_COLS,))):
        cs = sorted({c0 + sg * int(round(o * (cols - 1) / 40.0)) for o in offs for sg in (-1, 1)})
        for k, c in enumerate(cs):
            r0 = int(cup_rows.get(c, 0)) if part == 1 else 0
            out[f"seam_{'front' if part == 1 else 'back'}_{k}"] = (part, [base + r * cols + c
                                                                           for r in range(r0, rows)])
    return out


#: Corset v8 (review 2026-11-23 of v7: the seam under the cups formed an "M" whose two arcs met the centre front at
#: different heights, with a kink): the centre cut (``dart_seams``, the centre column cut from row 0 down to row n_c)
#: opens the front's pattern, and its two sides OVERLAP in the atlas — a wedge from the top edge down to the cut's
#: end, measured on Rosi's corset over columns c0 - 4 .. c0 + 4 at row 5 and c0 - 2 .. c0 + 2 at row 9 (6 px deep at
#: c0 + 1). A line painted into that wedge shows on both sides of the body (v7: a short spike up from the centre).
#: The seam therefore meets the centre front ``CUP_CENTRE_BELOW_ROWS`` under the cut's end, on a vertex the cut does not
#: split (one atlas point for both halves), and the columns beside it stay out of the wedge: ``CUP_CENTRE_CLEAR_COLS``
#: columns either side at least on that row, every column further out one row less (measured on Rosi's: every point
#: of the line at least 9 px outside the wedge, 0.47 cm at 19.2 px/cm).
CUP_CENTRE_BELOW_ROWS = 1
CUP_CENTRE_CLEAR_COLS = 2


def centre_rows(rows: int) -> int:
    """The row where the centre cut ends (``dart_seams``: the centre column cut from row 0 down to this row)."""
    return int(round((rows - 1) * CENTRE_SHARE))


def centre_cup_rows(rows: int, cols: int, cup_rows: dict) -> dict:
    """Corset v8: ``cup_rows`` ({front column: row}, ``under_cup_rows``) with every column ``k`` columns off the centre
    column at least on row n_c + ``CUP_CENTRE_BELOW_ROWS`` - max(0, k - ``CUP_CENTRE_CLEAR_COLS``) (n_c =
    ``centre_rows``), never under the hem row; a row is never raised. The centre column lands on the shared point under
    the cut. {} stays {}."""
    c0 = (cols - 1) // 2
    low = centre_rows(rows) + CUP_CENTRE_BELOW_ROWS
    return {int(c): min(rows - 1, max(int(r), low - max(0, abs(int(c) - c0) - CUP_CENTRE_CLEAR_COLS)))
            for c, r in cup_rows.items()}


def cup_seams(cols: int, cup_rows: dict) -> dict:
    """Corset v7: the seam under each cup — ``{"seam_cup_<k>": (1, construction ids)}`` through the front vertex of
    row ``cup_rows[c]`` in each column ``c``, one line per run of neighbouring columns (k left to right in column
    order; a run of one column draws nothing).
    Corset v8: a run through the centre column is split there into two lines that BOTH hold the centre column's vertex
    — the left half ends on it, the right half starts on it (each half runs one way across the panel, so the atlas
    line never steps back, and the two halves share their centre point)."""
    c0 = (cols - 1) // 2
    cs = sorted(int(c) for c in cup_rows)
    runs, run = [], []
    for c in cs:
        if run and c != run[-1] + 1:
            runs.append(run)
            run = []
        run.append(c)
    if run:
        runs.append(run)
    halves = []
    for r in runs:
        if r[0] < c0 < r[-1]:
            halves += [[c for c in r if c <= c0], [c for c in r if c >= c0]]
        else:
            halves.append(r)
    return {f"seam_cup_{k}": (1, [int(cup_rows[c]) * cols + c for c in r]) for k, r in enumerate(x for x in halves
                                                                                              if len(x) > 1)}


def back_line(rows: int, cols: int) -> list:
    """The back panel's centre column, top to bottom (construction ids)."""
    base = rows * cols
    c0 = (cols - 1) // 2
    return [base + r * cols + c0 for r in range(rows)]
