"""Image gates of the garment chain — pure numpy on arrays
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R7).

Every function takes same-shaped arrays: RGB as ``(H, W, 3)`` (any numeric
dtype) and masks as ``(H, W)`` bool. The caller resamples an edit to the
base view's size first (pure scale, R6). The zones come from the BASE mask:
``y0`` = its top row, ``Hb`` = its last row minus ``y0``.

The hair gates of the removed hair edit chain went with it (hair-from-body,
2026-11-11); what stays is the clothing chain's: an own-mesh outfit piece
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``,
Task 2) has two gates and a pair check, see "Clothing" below.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

#: The image height the spike's pixel numbers were measured at.
SPIKE_HEIGHT = 1536

# --- Zones (fractions of the base figure height Hb, below its top y0) --------
SHOULDER_ROW = 0.19     # the row whose mask span gives centre + shoulder half-width
CHIN_ROW = 0.13         # the chin row (the head zone's fallback end, ``HEAD_ZONE``)


def _check(rgb_a, mask_a, rgb_b, mask_b) -> None:
    shapes = {np.shape(mask_a), np.shape(mask_b), np.shape(rgb_a)[:2], np.shape(rgb_b)[:2]}
    if len(shapes) != 1:
        raise ValueError(f"gate inputs differ in size: {sorted(shapes)}")


def _diff(a, b) -> np.ndarray:
    """Per-pixel mean |ΔRGB|."""
    return np.abs(np.asarray(a, dtype=np.float32)[..., :3] - np.asarray(b, dtype=np.float32)[..., :3]).mean(2)


def _zones(mask) -> Optional[tuple]:
    """``(y0, Hb)`` of a mask, None when it is empty."""
    rows = np.nonzero(np.asarray(mask).any(1))[0]
    if not len(rows):
        return None
    return int(rows.min()), int(rows.max() - rows.min())


def _span(mask, row: int) -> Optional[tuple]:
    """``(centre x, half-width)`` of the mask's extent on ``row``."""
    xs = np.nonzero(np.asarray(mask)[row])[0]
    if not len(xs):
        return None
    return (xs.min() + xs.max()) / 2.0, (xs.max() - xs.min()) / 2.0


def _bbox(mask) -> Optional[List[int]]:
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def _mean(values) -> float:
    return float(values.mean()) if values.size else float("inf")


def _r(value: float, digits: int) -> Optional[float]:
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def _iterations(base: int, height: int) -> int:
    return max(1, int(round(base * height / SPIKE_HEIGHT)))


# --- Clothing ---------------------------------------------------------------
#
# The clothing chain edits the bald, bare base view into ``worn`` (the figure
# wearing only the piece) and that into ``ghost`` (the piece alone on an
# invisible body). Every pixel number below is a fraction of the base figure
# height Hb (``_zones`` of the base mask), every area a share of an area, so
# the limits hold at any image size.
#
# Calibration (``~/claude-out/phase5-calib/calibrate.py`` on the S1 spike:
# ``kleid/dress_front|back.png`` against the bald base views
# ``bald/cur_apose_s41.png`` / ``bald/userback_a0f40bdb.png``, the ghosts
# ``kleid/ghost_front_s51..s53.png`` + ``ghost_back.png``; 1536², BiRefNet-DIS
# masks as ``garment_images._mask``; base figure y0 30 / 27, Hb 1452 / 1427):
#
# worn                    front     back      limit
#   garment_share         0.701     0.7102    >= 0.002  (something was put on; 0.01 before worn gate v3)
#   outside_dRGB          5.26      4.30      (recorded, no refusal since gate version 2)
#   outside_xor           0.0074    0.0048    < 0.015
#   head_garment          0.0       0.0       <= 0.05
# refused on purpose: the worn front moved 3 px right (outside_xor 0.0366),
# 6 px (dRGB 8.86, xor 0.0392, head 0.074), the other view's worn image
# (xor 0.1314, head 0.381), the head 20 % darker (head_garment 0.869).
#
# Worn gate version 2 (2026-11-10, Kai's "Black Lederjacket", fitted back,
# BiRefNet-DIS masks, 893 x 1536, base y0 51, Hb 1389; both attempts were
# a correct jacket back and both were refused):
#                       attempt 1   attempt 2   v1 verdict
#   outside_dRGB        10.30       9.61        refused (>= 8.0)
#   head_garment v1     0.0879      0.0808      refused (> 0.05; zone ends at the chin row 231)
#   head_garment v2     0.0038      0.0         (zone ends at the neck row 211, rule "neck")
#   outside_xor         0.0330      0.0334      (< 0.04, the fitted back's limit)
# Colour: the edit model tints the skin warmer. That colour never reaches
# the model — the chain is worn -> ghost (the garment alone) -> mesh -> CPU
# fit — so ``outside_dRGB`` protects nothing and is only recorded (the
# Wardrobe chip shows it as information). Head: the head zone ended at the
# chin row y0 + 0.13·Hb; the stand-up collar at the nape of a BACK view lies
# above that row (row 0.13 Hb is in the middle of the neck there). The zone
# now ends at the neck's narrowest row (``head_zone``): Kai's base back is
# 140 px wide at the ears (row 146, 0.068 Hb) and 91 px on rows 214..237
# (0.117..0.134 Hb), widening to 354 px at the shoulder row; the 7-row mean
# comes within 2 % of 91 px first at row 211 (0.1152 Hb). The collar starts
# at rows 212 / 214 (a 5 px seam line from row 197 on attempt 1).
#
# ghost (front vs the worn front's garment region; back vs the worn back's)
#                 top_dy     centre_dx  w_ratio  skin_left  outside  neck_fill
#   s52 (taken)   +0.00069   +0.00034   0.998    0.00014    0.0010   0.542
#   s51           -0.00413    0.0       1.004    0.0002     0.0005   0.774
#   s53           -0.00482    0.0       1.004    0.00009    0.0003   0.802
#   unseeded      -0.00207   +0.00069   1.088    0.00096    0.2478   0.594
#   s52 + legs    +0.00069   -0.00413   1.207    0.2223     0.3065   0.542
#   worn front    -0.146     +0.00069   1.580    0.4389     0.5829   0.998
#   back (taken)  -0.0028    +0.00035   1.007    0.0        0.0002   (no neckline)
#   limit       |..|<=0.0055 |..|<=0.007 [0.95,1.05] <=0.005 <=0.05  (reported)
# s51 and s53 differ from s52 at the neckline: the inside of the back
# fills 77 % / 80 % of the worn neckline opening instead of 54 %. A gate at
# 0.70 was cut between them and RETIRED after the first end-to-end run
# (2026-11-09, Kira, a green linen dress): the ghost front refused at
# neck_fill 0.832 was meshed and fitted anyway (UniForge3D-Multiview, fit on
# the same base) against the accepted ghost (0.411) — the neck opening of
# the prepared mesh, seen from above, was 144 cm² against 166 cm² (both
# wider than the neck), no face within 1 cm of the neck in the 3 cm below the
# neckline in either fit, 0/63 throat rays covered, fit accepted (max push
# 5.4 cm against 4.9 cm). The generator closes no sheet over a filled
# notch, so ``neck_fill`` is recorded and shown, never refused. The s51/s53
# shoulders also sit 6 and 7 px higher (top_dy -0.0041 / -0.0048 against
# +0.0007), but the accepted BACK ghost moved 4 px (-0.0028), so top_dy kept
# the hair gate's 8 px (0.0055 Hb) instead of a cut between 4 and 6 px on
# one sample — since ghost gate version 2 a recorded warning, no refusal
# (``GHOST_GATE_VERSION``).
# The front neckline is 31 px deep (0.0213 Hb), the back's 13 px (0.0091 Hb):
# a neckline counts from NECKLINE_MIN_DEPTH, so only the front reports neck_fill.
# ``outside`` leaves the neckline opening out (s52 shows the inside of the
# back there: 0.0036 with it, 0.0010 without).
#
# hems_agree: the ghost bottoms against each view's own figure — front s52
# (975 − 30) / 1452 = 0.65083, back (968 − 27) / 1427 = 0.65943, |Δ| 0.0086
# <= HEM_AGREE 0.02 (≈ 3.4 cm on a 1.70 m figure).
GARMENT_DRGB = 20.0         # a worn pixel this far from the base belongs to the garment
GARMENT_OPEN = 2            # opening iterations @1536 (thin outline fringes go)
GARMENT_CLOSE = 4           # closing iterations @1536
GARMENT_MIN_COMPONENT = 0.002   # smallest kept part, share of the base body area
GARMENT_MARGIN = 8          # px @1536 around the garment region that belong to its edge
# Worn gate version 3 (2026-11-12, gate audit ``~/claude-out/gate-audit``,
# ruling: a gate refuses only what would put something wrong into the
# figure). ``garment_share`` refused Kira's choker (item_1ae56416, worn
# front 0.0049 / 0.0068 — the choker sits right in both images) at the old
# 0.01; a worn view with nothing put on measures 0.0 (Kai, 4 attempts), the
# smallest accepted piece 0.0187. Every part the region keeps is at least
# GARMENT_MIN_COMPONENT (0.002) of the body area, so a share >= 0.002 means
# exactly "one part survived": GARMENT_MIN = GARMENT_MIN_COMPONENT.
GARMENT_MIN = 0.002         # garment region / base body area, at least (= one kept part)
#: The version of ``worn_gate``; every worn record carries it as
#: ``gate_version`` (missing = 1). A refused worn view whose stored attempts
#: were gated by an older version is re-gated from its files before anything
#: renders again (``garment_images``, ``kind.GATE_VERSIONS``). 2: the colour
#: outside the garment is recorded, not refused; the head zone ends at the
#: neck's narrowest row (``head_zone``). 3: ``GARMENT_MIN`` 0.002 and an
#: edit's ``OUTSIDE_DRIFT_PX`` 2.0 (the gate audit, see both constants). 4: a CPU
#: composite's head share leaves its support out (``worn_gate(composite_support=…)``,
#: Task 11g fix round 1: Kai's open jacket, a stand-up collar above the neck row,
#: was refused at 0.066 although the composite takes every head pixel from the base).
WORN_GATE_VERSION = 4
OUTSIDE_XOR_MAX = 0.015     # outline change outside the garment region / base body area
HEAD_ZONE = CHIN_ROW        # fallback end of the head: base figure rows above y0 + 0.13·Hb
HEAD_GARMENT_MAX = 0.05     # share of the head zone inside the garment region
# The head zone ends at the neck (``head_zone``): the narrowest row of the
# base silhouette between the head's widest row (above the chin row) and the
# shoulder row — the first row whose width, a mean over NECK_SMOOTH·Hb rows,
# comes within NECK_TOL of the narrowest width. A clear neck is at most
# NECK_NARROW of the head's widest row and the shoulder row is at least
# NECK_RISE times it; else the chin row (``HEAD_ZONE``) stays the end.
NECK_SMOOTH = 0.005         # smoothing window / Hb (7 rows at Hb 1389)
NECK_TOL = 0.02             # within this share of the narrowest width
NECK_NARROW = 0.85          # a neck is at most this share of the head's widest row
NECK_RISE = 1.25            # ... and the shoulder row at least this multiple of the neck
#: The protected zones of the worn gate a piece may change because it is worn
#: there: piece slot -> zones. ONE zone today, ``head`` (rows above the neck's
#: narrowest row, ``head_zone``); only a ``head`` piece (hat, hood) frees it.
#: ``neck`` is not in it: a scarf or collar lies below the neck's narrowest
#: row and needs nothing freed.
SLOT_ZONES: Dict[str, Tuple[str, ...]] = {"head": ("head",)}


def occupied_zones(slots: Iterable[str]) -> Tuple[str, ...]:
    """The protected zones (``SLOT_ZONES``) a piece with ``slots`` occupies,
    sorted; the worn gate does not check them."""
    return tuple(sorted({zone for slot in slots or () for zone in SLOT_ZONES.get(str(slot), ())}))
# Ghost gate version 2 (2026-11-12, ruling: the image stage refuses only
# what would put something WRONG into the mesh — body or skin left, more than
# the garment, an empty or cut-off garment, the wrong side; small geometric
# differences are the mesher's and the per-body fit's, and the fit gates the
# mesh). Live, Kai: "Black Lederjacket" back 2 of 2 refused (top 0.0147 /
# 0.0118 Hb, centre 0.0077 Hb, "skin" 0.0161), "Jeans" back 2 of 2 refused
# (width 0.875 / 0.833) — every image a correct back.
#
# Position — ``top_dy`` / ``centre_dx`` are RECORDED (``warnings``), never
# refused: ``garment_images.cut_out`` crops each view to its own square
# (1.15 × the mask box) before the mesher, so where the piece sits in the
# frame never reaches the mesh; what is left after the registration is a
# shape residual of a few mm (Kai's jacket 0.0147 Hb ≈ 2.5 cm on 1.70 m, and
# the region's bbox includes the re-shaded hands below the cuffs — x 12 vs
# the sleeve's 27). The limits stay as the warning thresholds (the hair
# gate's 8 px / the S1 calibration above). The wrong side is not measured
# here — the position limits caught the open front a ``GHOST`` back once drew
# only by its numbers (``garment_clothing.GHOST_KEEP``: +0.0259 / -0.0130);
# the back prompt names the side since ruling 13e.
#
# Width — ``w_ratio`` is WIDENED, not dropped: it is the guard against a
# cut-off piece (a lost sleeve takes a jacket to ~0.6-0.75). The mesher gets
# front and back as two separately framed views (``generate_mesh(…,
# view_images={"back": …})``, each cut-out normalised on its own box) and the
# result is fitted onto the body anyway. Correct ghosts measured
# (residual after registration):
#   Kai jacket back (live) 0.986 / 0.959      Rosi skirt back 0.920 / 0.950
#   Kira bodysuit back (clone) 0.855 / 0.863 (region bbox incl. the hands)
#   Kira dress / blazer 0.968..1.009          Kai trousers back (clone) 0.991..1.067
# -> [0.80, 1.25]: 0.055 below the lowest correct one, and the same factor
# (1 / 0.80) above. Wider ghosts beyond the garment are ``outside``'s
# (the S1 "s52 + legs" 1.207, Glut's harness 1.236, Rosi's 1.221 all have
# outside >= 0.13 or skin_left >= 0.2).
#
# Ghost gate version 3 (2026-11-12, gate audit ``~/claude-out/gate-audit``:
# every stored ghost attempt of the live world re-gated, BiRefNet-DIS masks).
# ``outside`` was the AREA of every ghost pixel beyond the region's 8 px
# margin over the region's area: a piece's own hem, waistband and visible
# inside lie a few cm beyond its worn region and, over a small piece, that
# rim alone is 0.1..0.3. Rosi's corset back (item_67e702f2) measured 0.1417 /
# 0.1215 — 0.125 / 0.115 of it on the region's own rows, hip and hem rim,
# farthest pixel 0.026 Hb (p95 0.022) from the region; the corset covers 13 %
# of the body. The old rule refused 5 correct images (corset 2x, Glut's slip
# 2x, Kira's skirt 1x). Now ``outside`` = the LARGEST CONNECTED part of the
# ghost pixels lying more than CLOTH_FAR·Hb (0.02 Hb, ≈ 3.4 cm on 1.70 m)
# from the region (Euclidean distance), over the region's area, <= 0.05;
# the whole area beyond the margin is ``outside_near`` — a warning above
# 0.05, never a refusal. Re-gated with this version (``garment_images``
# re-registers an attempt that no registration had moved):
#   correct    Rosi corset 0.0077 / 0.0055, Glut slip (glut_schurz) 0 / 0,
#              Rosi skirt back 0 / 0 and front 0 (registered by its
#              waistband now), Kira skirt 0.0055 (0.0294 with the old hem,
#              below), Kira blazer 0..0.0007, Kai jacket 0..0.0002
#   defects    Glut's boots drawn as a bodysuit 1.43 / 1.33, Lirien's belt
#              drawn as the figure 23.4 / 23.3, Glut's harness back 0.104
# -> 0.05 sits 6.5x over the highest correct one and 2x under the lowest
# defect. Two defects are refused by other gates: Kira's skirt with the legs
# (0.26 to the old hem; the length is free below the new one) for its skin
# (0.40), Rosi's skirt drawn as a dress (1.07 unregistered) for its width
# (1.649 registered by the waistband). Glut's harness back attempt 1 passes
# (0.0, near 0.088): the ghost follows its worn back, and that worn back
# shows the front (``BACK_OPENING_MIN``) — a gap of the worn gate.
#
# ``length_free`` (a waistband piece): the ghost rows below the region's HEM
# are not counted. The hem was the last row of the region's bbox; Kira's
# skirt (item_3024cbe4, back) has a slit and the worn region runs through it
# as a 5..8 px strand of the re-shaded leg edge from the hem (row ~945) down
# to row 1042 — the correct attempt 2 (0.163, ghost down to row 1010) counted
# its own slit tips as "more". The hem is now ``_hem_row``: the last row of
# the region opened by the margin (a strand narrower than twice the margin
# is no cloth) without its small parts (``_main_parts``) — 951 there.
#
# Ghost gate version 4 (Ruling A17, 2026-11-13): the hem against the WORN
# piece and the open / closed look of a closable front — the block "Hem and
# centre gap" below ``HEM_AGREE``.
# Ghost gate version 5 (Ruling A27, 2026-11-13): a ghost whose ONLY refusal
# is the hem, within ``HEM_SNAP_MAX``, is snapped to the worn hem on the CPU
# (the block "Hem snap" after ``hem_deviation``); attempts stored under
# version 4 are judged again by the chain before it renders.
# Ghost gate version 6 (Ruling A32, 2026-11-13): ``skin_left`` counts a
# pixel as skin only when it is nearer the skin than the piece in the
# same light, and never on the ghost's own outline — the block "Skin or
# piece" below ``SKIN_LEFT_MAX``; the attempts refused under 5 are judged
# again by the chain before it renders.
# Ghost gate version 7 (Ruling A46, 2026-11-14): a part the ghost ADDS beyond
# the worn piece is refused by how far it REACHES, not by its area — the block
# "Added parts" below ``CLOTH_FAR``.
GHOST_GATE_VERSION = 7
CLOTH_TOP_DY_WARN = 0.0055  # |top edge offset| / Hb from which it is recorded as a warning
CLOTH_CENTRE_DX_WARN = 0.007  # |centre offset| / Hb from which it is recorded as a warning
CLOTH_W_RATIO_MIN = 0.80
CLOTH_W_RATIO_MAX = 1.25
# The skin sample: the base THIGHS. The face rows (0.04..0.10 Hb) sampled
# the bald base until the base carried its hair (hair-from-body, 2026-11-11):
# on Kai's base back they are his dark hair, median RGB (35, 30, 25), so the
# black leather of the jacket and its dark inside at the hem counted as
# "skin" (attempt 2: 2667 px on rows 701..720, skin_left 0.0161). Rows
# 0.60..0.66 Hb are mid-thigh on both views — below any hair and the hips,
# the bare base body; a hand reaching there is skin too.
SKIN_SAMPLE_ROWS = (0.60, 0.66)
SKIN_DRGB = 30.0            # a ghost pixel this close to the sampled skin is skin
SKIN_LEFT_MAX = 0.005       # skin outside the garment region / garment area
# Skin or piece (Ruling A32, 2026-11-13). Ylva's laced linen blouse
# (item_laced_linen_blouse, fsig a4166095ab54): both ghost backs show the
# cream blouse alone, no skin to the eye, and were refused "skin left"
# 0.0151 / 0.0129 (605 / 517 px over the region's 40006). The skin sample
# is (174, 122, 98), the worn region's median (``piece_colour``) (210,
# 195, 178); the flagged pixels' median (135, 114, 100) is the cream in
# shadow (the inside of a sleeve, the underside of the peplum: 0.56 of the
# piece's brightness), mean |ΔRGB| 16 to the skin but 78 to the lit piece —
# no plain RGB comparison tells them apart (0 of 605 nearer the piece). In
# the SAME light they are: a pixel is compared with each colour scaled to
# its own brightness (``shade_distance``): 6.2 to the piece, 12.8 to the
# skin. And 142 / 155 of them lay on the ghost silhouette's outermost
# pixel, blended into the background. So a ghost pixel beyond the region
# is skin only when it is within ``SKIN_DRGB`` of the skin (as before),
# at least as near the skin as the piece in the same light (a tie counts
# as skin: a piece in the skin's own hue cannot be told from it, the test
# before), and not within ``GHOST_RIM`` of the ghost's outline. Ylva:
# rim 142 / 155, shaded piece 348 / 319, still counted 115 / 43 px (warm
# shading where the sleeve meets the body and under the peplum) -> 0.00287
# / 0.00107; leftover skin (an arm, a neck) is lit skin and stays skin
# (scripts/smoke_ghost_skin_vs_garment.py).
# GHOST_RIM reuses GARMENT_OPEN, the width the worn region already drops
# as "thin outline fringes": 1 px at 1024 — the outermost pixel, where the
# matte's edge mixes the piece with the background.
GHOST_RIM = GARMENT_OPEN    # px @1536 of the ghost's outline left out of skin_left
CLOTH_OUTSIDE_MAX = 0.05    # largest ghost part beyond CLOTH_FAR / garment area (and the near warning)
CLOTH_FAR = 0.02            # Hb: ghost pixels farther than this from the region form ``outside``'s parts
# Added parts (Ruling A46, 2026-11-14). Glut's scale top (item_glut_harnisch,
# fsig 4ef4525e4ac1): the worn front is strapless — scale cups, crossed chains
# below — and the ACCEPTED ghost front (attempt 2) drew two shoulder straps
# up from the cups. ``outside`` passed it at 0.0197 (limit 0.05): a strap
# is thin, the far part of each one holds 2 % of the region's area.
# The straps are what reaches FARTHEST: ``added_reach`` = per connected
# part of the ghost pixels beyond the region's margin that are no opening
# (the parts ``outside_near`` counts), at least ADDED_MIN_PART of the region's
# area, the distance of its farthest pixel from the worn region's bounding
# box (Euclidean, 0 inside it), over Hb; the largest over the parts. Re-gated
# on copies (BiRefNet-DIS masks, the files as stored, 2026-11-14):
#   Glut scale top ghost front (accepted, the straps)   0.0428 / 0.0428   (two straps, 0.033 / 0.032 of the area)
#   Glut scale top ghost back  (accepted, cup insides)  0.0204
#   Kira  skirt 3024cbe4 front / back        0.0 / 0.0
#   Kira  bodysuit 5bfe0cbc (2966 front, 8a64 both)  0.0021, 0.0 / 0.0  (2966 back attempts 0.0057 / 0.0)
#   Ylva  laced linen blouse back attempts 1 / 2      0.0021 / 0.0
#   Kai   jacket 555a7a01 backs (accepted)            0.0246 (3749, a5e7), fronts 0.0 .. 0.0146
#   Kai   jeans 6c41aa2c                              back 0.0232 / 0.0014, front 0.0057 / 0.0049
#   Glut  slip (glut_schurz) front / back             0.0076 / 0.0;  Rosi 2d62894b all 0.0
#   refused defects: Kai jeans back attempt 1 0.0344 (width 1.26), Kai jacket back attempt 1 0.0855,
#                    Glut scale top back attempts of 16:28 0.1745 / 0.064
# -> 0.03 Hb (≈ 5 cm on a 1.70 m figure): 1.22x the highest correct one (Kai's jacket back, its sleeve
# cuffs a little longer than worn), 0.70x the straps. A part below ADDED_MIN_PART (0.001 of the region,
# 16x under a strap's) is a speck of the matte, never measured. Only a THIN part counts: its pixels over its
# reach (a strap's width; a hem that hangs lower has the piece's width) at most ADDED_THIN_MAX — a longer
# hem is the hem gate's (``hem_refused``) and its snap's (Ruling A27), not an added part. Thickness of the
# farthest part on the same copies: Glut's straps 0.0102 Hb; the correct ones 0.0048 (Glut's slip, reach
# 0.0076) and 0.039 .. 0.125 (Kai's jacket cuffs 0.0389, his jeans 0.1249); the hem smokes' longer hems
# (smoke_ghost_hem_snap / _reference, reach 0.034 / 0.031) the piece's width.
# -> 0.02 Hb (≈ 3.4 cm): 2x a strap, half of Kai's cuffs.
ADDED_REACH_MAX = 0.03      # Hb: farthest an added part may reach past the worn piece's box
ADDED_MIN_PART = 0.001      # share of the region's area from which a part beyond it is measured
ADDED_THIN_MAX = 0.02       # Hb: a part up to this thick (its pixels over its reach) is a strap, not a hem
NECKLINE_MIN_DEPTH = 0.012  # notch depth / Hb from which the garment has a neckline
NECKLINE_BAND = 0.03        # ± this share of the garment width around its centre column
HEM_AGREE = 0.02            # |hem front − hem back| and |ghost hem − worn hem|, fractions of Hb
# Hem and centre gap (Ruling A17, 2026-11-13). Kai's leather jacket
# (item_555a7a01, fsig 3fc8dd52a021): the ghost BACK (attempt 2) was
# accepted hanging below the worn back's hem with a dark underside bulge;
# every ghost front was then measured against it (``hems_reason``, |Δ|
# 0.0243 / 0.0405 Hb) and refused, and a restart reused the stored back —
# refused forever. The bbox bottom (``hem_t``) cannot see that: in the
# A-pose the lowest garment pixel is a sleeve cuff or a re-shaded hand — the
# worn back region ends at row 796 (the fingertips, hem_t 0.5295) and the
# bad ghost back at 0.514, "above" its worn piece. ``hem_c`` (``centre_hem``)
# is the hem where the torso is: per column within ± HEM_BAND·Hb of the base
# figure's centre (the shoulder row's span centre) the last row of the
# column's LONGEST vertical run of the mask — a separate re-shaded patch
# below is shorter than the torso's run —, kept when that run is at least
# HEM_RUN_MIN of the mask's own height (a collar above an open front is no
# hem), the median over the kept columns; None when fewer than HEM_BAND_MIN
# of the band's columns are kept (an open front, a cutaway, nothing at the
# centre: gloves, a shrug — no hem rule then, the ghost pair falls back to
# the bbox ``hem_t``). The worn region is measured WITHOUT its skin-coloured
# pixels (within SKIN_DRGB of the skin sample): an edit re-shades the belly
# or crotch below a hem, and Kira's Black Blazer front (a cutaway) read
# 0.494 with them — the crotch — against its ghost's 0.458. Measured on
# copies of the stored images (BiRefNet-DIS masks, the attempts as stored —
# attempt 1 of the front registered):
#   worn back region    0.45716   ghost back attempt 2 (accepted) 0.51124  |Δ| 0.0541
#                                 ghost back attempt 1            0.52949  |Δ| 0.0723
#   worn front region   0.46512   ghost front attempt 1 (OPEN)    0.45525  |Δ| 0.0099, worn back 0.0019
#                                 ghost front attempt 2           0.45877  |Δ| 0.0063, worn back 0.0016
# Worn front against worn back 0.0080. Every accepted ghost of the live world
# re-gated the same way (8 images, 2026-11-13): only that ghost back is
# refused by the hem; Kai's open-state jacket front and Kira's cutaway blazer
# front measure no worn hem; Kai's closed jacket front (ceda6b488194) and
# Rosi's piece lie 0.0021 / 0.0100 from their worn views (Kai's waistband
# jeans are length-free).
# So the ghost of each view is gated against its
# own WORN view (a) — the worn views are what the composite and the worn
# gates validated —, the front attempt against the worn back too (b,
# ``worn_hems_reason``), never against the ghost back; the ghost pair still
# has to agree (``hems_agree``, on ``hem_c``) and the view that is farther
# from its worn view is the one rendered again (c, ``hem_deviation``).
# A waistband piece's length is free (ruling 13d): no hem rule there.
#
# Open / closed (same ruling): attempt 1 of that front came out OPEN —
# unzipped, the black inside between the panels — while the piece is worn
# closed, and only the hem refused it. ``centre_gap`` = the widest run of
# OPEN columns within ± GAP_BAND·Hb of the centre, in Hb: a pixel is open
# when it is not garment or darker than GAP_DARK × the median luminance of
# the garment's panels (GAP_BAND..GAP_PANEL·Hb off the centre, the same
# rows), a column when at least half its rows are. Rows: GAP_ROWS of the
# figure (chest to waist), below the worn region's neckline + 0.02 Hb and
# above its hem − 0.02 Hb; fewer than GAP_ROWS_MIN·Hb rows measure nothing.
# The worn view is measured the same way on its garment region (an open
# piece shows the body there: not garment), so a dark placket by design is
# open in both. Kai's copies (front rows 387..614, the panels' median
# luminance 17.7..21.3, dark at <= 7.1..8.5 — black leather on black):
#   worn front 0.0014    ghost front attempt 1 (OPEN) 0.0345    attempt 2 0.0021
#   Kai's OPEN-state front (2b72c222b6ae, accepted): worn 0.0881, ghost 0.0543
# A closable piece's ghost FRONT is refused when one of the two reaches
# GAP_MIN and the other does not — 7x the highest closed one, 0.43 of the
# lowest open one. One open piece only, black: a ghost whose inside is
# lighter than GAP_DARK of its panels reads closed.
HEM_BAND = 0.04             # ± Hb around the figure's centre column whose garment rows give the hem
HEM_BAND_MIN = 0.5          # share of the band's columns that must be kept for a measured hem
HEM_RUN_MIN = 0.25          # a column's run counts from this share of the mask's own height
GAP_ROWS = (0.24, 0.40)     # Hb: the rows the centre gap is looked for on (chest to waist)
GAP_ROWS_MIN = 0.04         # Hb: fewer rows than this between neckline and hem measure no gap
GAP_EDGE = 0.02             # Hb kept clear of the worn region's neckline and hem
GAP_BAND = 0.05             # ± Hb around the centre column searched for the gap
GAP_PANEL = 0.15            # Hb: the panels are the garment pixels from GAP_BAND to this far off the centre
GAP_DARK = 0.4              # a pixel this share of the panels' median luminance (or darker) shows the inside
GAP_MIN = 0.015             # Hb: the widest open run from which a front counts as open
# The worn BACK against the accepted worn FRONT (``back_follows_front``; the
# back is drafted from that front, ``garment_images``). Measured 2026-11-09 on
# the live "Black Blazer" (Kira) — the single-edit back turned the BODY toward
# the camera under a back-of-head: lapels, buttons, flap pockets and the open
# V with the chest in it, on the back view. Neckline depth of the worn
# garment region (``neckline`` / Hb):
#   worn front (accepted)            0.1182   hem_t 0.9315
#   worn back attempt 1 (front copy) 0.1124   hem_t 0.9576   (refused for colour)
#   worn back attempt 2 (front copy) 0.0926   hem_t 0.9491   (ACCEPTED then)
#   S1 dress, a real back            0.0091   (front 0.0213, the calibration block above)
# Both front copies reach 0.78-0.95 of the front's depth; a real back of the
# same pieces stays near zero. A back opening counts from 0.04 Hb (≈ 7 cm on
# a 1.70 m figure — a deep scoop, never a collar line) and is refused when it
# reaches half the front's depth: the back then shows the FRONT opening. A
# garment whose back is cut as deep as its front (a deep V front and back)
# is refused by this — known limit, Regenerate does not help there.
# First real draft + fit run (clone, Kira, the same blazer, 2026-11-09; front
# neckline 0.1113, cloth hem 0.4834): fit 1 copied the front again (neckline
# 0.0857 -> refused here), fit 2 a real blazer back (0.0007). NO hem rule on
# the worn images: a fit re-shades the skin below the hem, so the worn region
# of the correct back ended at hem_t 0.568 while its dark cloth ends at 0.4845
# (front 0.4834) — the garment hems are compared on the ghosts (``hems_agree``).
# The fit re-renders the whole figure, so its outline outside the garment
# moves more than an edit's (direct edits 0.004-0.018): fit 1 0.0259, fit 2
# 0.0334, three quarters of it in the legs (rows below 0.5 Hb); the torso
# band 0.30-0.50 Hb only 0.0035 / 0.0052. A fitted back was gated at a
# looser 0.04 (FIT_OUTSIDE_XOR_MAX). Since Task 11g (Ruling C1) the drafted
# back is a CPU COMPOSITE (``view_composite``): the base back outside the
# garment mask is kept pixel for pixel, so it is gated at the edit limits —
# measured on the ten accepted worn backs of a live world copy
# (2026-11-12) the composites' outline XOR is 0.0004-0.0014 (drift
# 0.02-0.12 px); FIT_OUTSIDE_XOR_MAX / FIT_OUTSIDE_DRIFT_PX are gone.
BACK_OPENING_MIN = 0.04     # back neckline depth / Hb from which the back has an opening
BACK_OPENING_SHARE = 0.5    # ... refused when it reaches this share of the front's depth
# Known gap (gate audit, 2026-11-12): Glut's harness worn back was ACCEPTED
# showing cups and cleavage — the front. Back depth 0.0369, front 0.0165:
# the rule needs the FRONT to have an opening, so no lower minimum down to
# 0.0165 catches it (0.03 would not). At <= 0.0165 the correct accepted
# backs come within reach: Glut's slip back 0.0213 (front 0.051, kept only
# by the share rule, 0.0213 < 0.0255), Rosi's corset back 0.0205 (front
# 0.0097), Glut's boots back 0.0609 (front 0.0 — two boots leave a notch at
# the centre, the depth is no opening there). Not changed: the depth alone
# does not tell this front copy from a correct back.
# The outline XOR is an AREA share, so what it measures grows with how much
# of the outline lies outside the garment: the same drift costs a small
# piece far more than a big one. Measured 2026-11-10 (Kira, BiRefNet-DIS
# masks, H 1536, base back area 302 309 px, base outline 6 499 px): a 1 px
# shift of the bare figure alone is XOR 0.0204 (> 0.015), 2 px 0.0408, a 1 %
# re-frame 0.0417. Exposed outline L (base outline px outside the grown
# garment) and the mean drift on it (``outside_drift_px`` = XOR px / L, at
# 1536):
#                                 L      XOR     drift   (old verdict)
#   Black Stilettos edit back 1   5999   0.0264  1.33    refused
#   Black Stilettos edit back 2   5994   0.0238  1.20    refused
#   Black Stilettos front 1       6074   0.0201  1.01    refused
#   Black Stilettos front 2       6023   0.0100  0.51    accepted
#   sport shoes front             6094   0.0140  0.70    accepted
#   Black Blazer front 1          4291   0.0181  1.29    refused
#   Black Blazer front 2          1659   0.0023  0.42    accepted
#   Black Blazer edit backs 1/2   ~1450  0.0040  0.84/0.91 accepted
#   Black Blazer fit backs 1/2    3028/3437 0.0132/0.0171 1.32/1.50 (accepted 2)
#   Black Stilettos fit backs 1/2 4922/5127 0.0495/0.0483 3.04/2.85 refused
# The refused edits are clean (overlays: a 1 px fringe along the whole
# figure, about half of it one whole-figure pixel — best shift dx +1 takes
# 0.0264 to 0.0150); the feet carry 0.0007 / 0.0010 of the stiletto backs'
# XOR (the shoe is the garment), so heels do not change the outline outside
# it. The refused fits invented underwear / a sheer bodysuit and slimmed the
# shins (row 0.85 Hb 130 -> 102 px). An attempt is refused only when the
# area limit AND the drift limit are both reached: the effective limit is
# ``max(xor_max, drift_px · H/1536 · L / area)`` (``outside_xor_limit``).
# Big pieces keep the area limit (blazer: 1.5 px over 1450 px = 0.0072 <
# 0.015); a shoe gets 1.5 px over ~6000 px ≈ 0.030. A whole-figure drift of
# 2 px (1.90) or a 1 % re-frame (1.94) still fails an edit; the stiletto fits
# (2.85 / 3.04) still fail a fit (limit max(0.04, 2.0 · 5127 / 302309 =
# 0.0339)), the blazer's (1.50) passes.
# Worn gate version 3 (the gate audit): an EDIT's drift limit 1.5 -> 2.0 px.
# Glut's boots, worn front attempt 1 (2026-11-12): XOR 0.0218 against the
# limit 0.0178, drift 1.84 px — the overlay is a uniform 1-2 px seam around
# the whole figure, the boots are right (attempt 2: 0.52). Accepted edits
# measured 0.29..1.36 px. Kira's skirt (item_3024cbe4) worn front attempt 1,
# 2.40 px, moved the legs (and pulled them into the garment region): still
# refused. A whole-figure shift of 2 px (1.90) or a 1 % re-frame (1.94)
# passes now: the garment region compares colour, so a seam outside the
# piece never becomes garment, and the ghost is registered onto the region.
OUTSIDE_DRIFT_PX = 2.0      # mean outline drift @1536 an EDITED view may have outside the garment
# A FITTED back of a piece that covers little re-renders the bare figure and
# the fit puts clothes on it the front does not have (Kira, 2026-11-10,
# footwear: a bra + briefs, a sheer bodysuit, a leather bodysuit — ACCEPTED
# by the outline at 0.038 < 0.04 and then refused at the ghost —, a camisole
# + briefs twice). ``extra_part`` = the largest connected part of the back's
# garment region outside the FRONT garment's rows (as fractions of Hb,
# ± BACK_ROWS_MARGIN), share of the base body area:
#   Black Stilettos fits (front rows 0.890-1.008)  0.0544 0.3365 0.2293
#   business heels fits  (front rows 0.905-1.012)  0.2468 0.1624
#   Black Blazer fits    (front rows 0.140-0.483)  0.0055 0.0054 (a re-shaded knee / foot)
# Refused above BACK_EXTRA_MAX (2.7x under the smallest invented garment,
# 3.6x over the blazer's re-shading). A piece whose back reaches rows its
# front does not show (a cape seen only from behind) would be refused —
# known limit.
BACK_ROWS_MARGIN = 0.02     # ± Hb around the front garment's rows
BACK_EXTRA_MAX = 0.02       # largest garment part of a back outside them / base body area


def garment_region(base_rgb, base_mask, worn_rgb, worn_mask) -> np.ndarray:
    """The garment of a worn view: worn mask AND (|ΔRGB| to the base > 20 OR
    outside the base mask), opened 2 and closed 4 iterations (scaled by
    H / 1536, at least 1), parts below 0.2 % of the base body area dropped,
    holes filled (a garment colour close to the skin leaves no gap)."""
    from scipy import ndimage
    _check(base_rgb, base_mask, worn_rgb, worn_mask)
    m0, m1 = np.asarray(base_mask, dtype=bool), np.asarray(worn_mask, dtype=bool)
    height = m0.shape[0]
    region = m1 & ((_diff(base_rgb, worn_rgb) > GARMENT_DRGB) | ~m0)
    region = ndimage.binary_closing(
        ndimage.binary_opening(region, iterations=_iterations(GARMENT_OPEN, height)),
        iterations=_iterations(GARMENT_CLOSE, height))
    labels, count = ndimage.label(region)
    if count:
        sizes = np.bincount(labels.ravel())
        keep = np.nonzero(sizes >= GARMENT_MIN_COMPONENT * max(int(m0.sum()), 1))[0]
        region = np.isin(labels, keep[keep > 0])
    return ndimage.binary_fill_holes(region)


def _margin(region, height: int) -> np.ndarray:
    from scipy import ndimage
    return ndimage.binary_dilation(region, iterations=_iterations(GARMENT_MARGIN, height))


def head_zone(base_mask) -> Optional[Dict[str, Any]]:
    """Where the head zone of the worn gate ends: ``{row, rule, t}`` — the
    zone is the base figure's rows above ``row``; ``t`` = (row − y0) / Hb.

    ``rule`` ``neck``: the base silhouette's width per row (mask pixels),
    a mean over ``NECK_SMOOTH``·Hb rows (at least 1, odd); between the
    head's widest row (in rows y0 .. y0 + ``CHIN_ROW``·Hb) and the shoulder
    row (y0 + ``SHOULDER_ROW``·Hb) the narrowest width w; ``row`` = the
    first row there whose width is at most w·(1 + ``NECK_TOL``) — the top
    of the neck's narrowest stretch. Taken when it is a clear neck: w <=
    ``NECK_NARROW`` × the head's widest width and the shoulder row's width
    >= ``NECK_RISE`` × w. ``rule`` ``chin``: otherwise (a silhouette that
    narrows all the way down to the shoulder row) ``row`` = y0 +
    ``HEAD_ZONE``·Hb, the zone before gate version 2. None without a
    figure."""
    from scipy import ndimage
    m0 = np.asarray(base_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return None
    y0, hb = zones
    chin = int(y0 + HEAD_ZONE * hb)
    shoulder = int(y0 + SHOULDER_ROW * hb)
    window = max(1, int(round(NECK_SMOOTH * hb)) | 1)
    width = ndimage.uniform_filter1d(m0.sum(1).astype(np.float64), window, mode="nearest")
    out = {"row": chin, "rule": "chin", "t": _r((chin - y0) / hb, 4)}
    if chin <= y0 or shoulder <= chin:
        return out
    widest = y0 + int(np.argmax(width[y0:chin]))
    seg = width[widest:shoulder + 1]
    narrow = float(seg.min())
    if not (narrow <= NECK_NARROW * float(width[widest]) and float(width[shoulder]) >= NECK_RISE * narrow):
        return out
    row = widest + int(np.nonzero(seg <= narrow * (1 + NECK_TOL))[0][0])
    return {"row": row, "rule": "neck", "t": _r((row - y0) / hb, 4)}


def worn_gate(base_rgb, base_mask, worn_rgb, worn_mask, *, view: str,
              occupied: Iterable[str] = (), xor_max: float = OUTSIDE_XOR_MAX,
              drift_px: float = OUTSIDE_DRIFT_PX,
              front_rows: Optional[Tuple[float, float]] = None,
              composite_support: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Step 1 gate of clothing: the base view with the piece put on.

    The garment region G = ``garment_region``; everything of the figure
    outside G grown by 8 px @1536 (head, arms, hands, legs, feet for a dress)
    must stay as it was in outline: ``outside_dRGB`` = mean |ΔRGB| where
    both masks hold there is RECORDED only (gate version 2: the edit model's
    skin tint never reaches the mesh, see the calibration block),
    ``outside_xor`` = (base XOR worn mask) there / base body
    area (< ``outside_xor_limit`` — a moved limb or a re-framed figure).
    ``outside_xor_limit`` = max(``xor_max``, ``drift_px`` · H/1536 ·
    ``outside_outline`` / base body area), ``outside_outline`` = the base
    outline pixels (mask minus its erosion) outside G grown: the area limit
    for a big piece, a mean outline drift of ``drift_px`` for a small one
    (a shoe leaves the whole figure's outline exposed); ``outside_drift_px``
    = XOR px / ``outside_outline`` at 1536 is reported. ``head_garment`` =
    share of the base head zone (the figure's rows above the neck's
    narrowest row, ``head_zone``; recorded as ``head_rule`` ``neck`` /
    ``chin`` and ``head_row_t``) inside G (<= 0.05: a changed face joins G
    and must not pass as garment) — measured always,
    gated only when the piece does not occupy the head (``occupied``, from
    its slots via ``occupied_zones``; ``head_gated`` says which). ``garment_share`` =
    G / base body area (>= ``GARMENT_MIN`` 0.002: the edit put something on). ``garment_top``
    / ``garment_bottom`` are G's rows; ``neckline_depth`` (G's ``neckline``
    / Hb) and ``hem_t`` are reported for ``back_follows_front``. ``xor_max``:
    the area limit (recorded as ``outside_xor_max`` when it differs from
    ``OUTSIDE_XOR_MAX``); ``drift_px``: the drift limit. ``front_rows``: the accepted
    front garment's rows (``garment_rows`` of its record) — then
    ``extra_part`` = the largest connected part of G outside those rows
    (± ``BACK_ROWS_MARGIN`` Hb) / base body area is reported for
    ``back_follows_front``. ``composite_support``: the worn image is a CPU
    composite (``view_composite``, the drafted back) and this is its support —
    every pixel it may have changed (bool, the base view's shape); outside it
    the composite IS the base. The head share then counts only G outside the
    support (``head_garment``, gated): a collar or hood the composite put over
    the neck is the garment, not a changed face, while a head change anywhere
    else still refuses. ``head_in_support`` (G ∩ support in the head zone) is
    recorded; ``head_support`` True says the rule applied. None for a model
    edit (the front): every head pixel of G counts.
    ``gate_version`` = ``WORN_GATE_VERSION``.
    Limits and their calibration: see the "Clothing" block above."""
    from scipy import ndimage
    _check(base_rgb, base_mask, worn_rgb, worn_mask)
    m0, m1 = np.asarray(base_mask, dtype=bool), np.asarray(worn_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return {"view": view, "ok": False, "reasons": ["no figure in the base view"]}
    y0, hb = zones
    height = m0.shape[0]
    region = garment_region(base_rgb, base_mask, worn_rgb, worn_mask)
    area = int(m0.sum())
    share = float(region.sum() / area)
    grown = _margin(region, height)
    outside = m0 & m1 & ~grown
    d_out = _mean(_diff(base_rgb, worn_rgb)[outside])
    xor_px = int(((m0 ^ m1) & ~grown).sum())
    xor = float(xor_px / area)
    outline = int((m0 & ~ndimage.binary_erosion(m0) & ~grown).sum())
    xor_limit = max(float(xor_max), drift_px * height / SPIKE_HEIGHT * outline / area)
    drift = xor_px / outline * SPIKE_HEIGHT / height if outline else None
    zone = head_zone(m0)
    head = np.zeros_like(m0)
    head[:zone["row"]] = True
    head &= m0
    head_px = max(int(head.sum()), 1)
    in_support = None
    if composite_support is not None:
        support = np.asarray(composite_support, dtype=bool)
        if support.shape != m0.shape:
            raise ValueError(f"composite support {support.shape} does not match the base view {m0.shape}")
        in_support = float((region & head & support).sum() / head_px)
        head_garment = float((region & head & ~support).sum() / head_px)
    else:
        head_garment = float((region & head).sum() / head_px)
    box = _bbox(region)
    extra = None
    if front_rows is not None:
        t = (np.arange(height) - y0) / hb
        band = (t >= front_rows[0] - BACK_ROWS_MARGIN) & (t <= front_rows[1] + BACK_ROWS_MARGIN)
        labels, count = ndimage.label(region & ~band[:, None])
        extra = float(np.bincount(labels.ravel())[1:].max() / area) if count else 0.0
    reasons = []
    if not share >= GARMENT_MIN:
        reasons.append(f"nothing put on: garment {_r(share, 4)} < {GARMENT_MIN}")
    if not xor < xor_limit:
        reasons.append(f"body outline outside the garment changed: XOR {_r(xor, 4)} >= {_r(xor_limit, 4)}"
                       + (f" (drift {_r(drift, 2)} px >= {drift_px} px)" if drift is not None else ""))
    head_gated = "head" not in set(occupied or ())
    if head_gated and head_garment > HEAD_GARMENT_MAX:
        reasons.append(f"head changed: {_r(head_garment, 3)} of the head > {HEAD_GARMENT_MAX}")
    depth = neckline(region)["depth"] / hb if box else None
    return {"view": view, "garment_share": _r(share, 4), "outside_dRGB": _r(d_out, 2),
            "outside_xor": _r(xor, 4), "outside_xor_limit": _r(xor_limit, 4), "outside_outline": outline,
            "outside_drift_px": _r(drift, 2) if drift is not None else None,
            "head_garment": _r(head_garment, 4), "head_gated": head_gated,
            **({"head_support": True, "head_in_support": _r(in_support, 4)} if in_support is not None else {}),
            "head_rule": zone["rule"], "head_row_t": zone["t"],
            "garment_bbox": box,
            "garment_top": box[1] if box else None, "garment_bottom": box[3] if box else None,
            "neckline_depth": _r(depth, 4) if depth is not None else None,
            "hem_t": _r((box[3] - y0) / hb, 5) if box else None,
            **({"outside_xor_max": xor_max} if xor_max != OUTSIDE_XOR_MAX else {}),
            **({"extra_part": _r(extra, 4)} if extra is not None else {}),
            "body_top": y0, "body_h": hb, "gate_version": WORN_GATE_VERSION,
            "ok": not reasons, "reasons": reasons}


def garment_rows(record: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """The rows of a worn gate record's garment as fractions of its figure
    height: ``((garment_top - body_top) / body_h, (garment_bottom -
    body_top) / body_h)``; None for a record without them."""
    try:
        y0, hb = float(record["body_top"]), float(record["body_h"])
        top, bottom = float(record["garment_top"]), float(record["garment_bottom"])
    except (KeyError, TypeError, ValueError):
        return None
    return ((top - y0) / hb, (bottom - y0) / hb) if hb > 0 else None


def back_follows_front(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> List[str]:
    """The refusal reasons of a worn BACK attempt against the accepted worn
    FRONT's gate record (both ``worn_gate``; [] = it follows the front):

    the back shows the front opening: the front has an opening
    (``neckline_depth`` >= ``BACK_OPENING_MIN``) and the back's reaches
    ``BACK_OPENING_MIN`` and ``BACK_OPENING_SHARE`` of the front's depth —
    lapels / a V turned onto the back view.

    the back puts on more than the front: ``extra_part`` (the back's
    largest garment part outside the front garment's rows, ``worn_gate``
    with ``front_rows``) > ``BACK_EXTRA_MAX`` — the fit dressed the figure
    in something the front does not wear. The hem is not compared here
    (see the calibration block: the worn region of a fit runs past the
    cloth); the ghosts compare it.

    A record without the numbers (an older front) checks nothing."""
    reasons: List[str] = []
    try:
        front, back = float(front_gate["neckline_depth"]), float(back_gate["neckline_depth"])
    except (KeyError, TypeError, ValueError):
        front = back = None
    if (front is not None and back is not None and front >= BACK_OPENING_MIN
            and back >= BACK_OPENING_MIN and back >= BACK_OPENING_SHARE * front):
        reasons.append(f"back shows the front opening: neckline {_r(back, 4)} Hb deep, front {_r(front, 4)} Hb "
                       f"(limit {BACK_OPENING_SHARE} x front from {BACK_OPENING_MIN} Hb)")
    extra = back_gate.get("extra_part")
    if isinstance(extra, (int, float)) and extra > BACK_EXTRA_MAX:
        reasons.append(f"back puts on more than the front: a part of {_r(extra, 4)} of the body outside the "
                       f"front piece's rows > {BACK_EXTRA_MAX}")
    return reasons


def piece_colour(worn_rgb, region) -> Optional[np.ndarray]:
    """The piece's own colour: the median RGB of the worn view's pixels in
    the garment ``region`` (``garment_region``); None without a worn image
    or an empty region (block "Skin or piece")."""
    if worn_rgb is None:
        return None
    region = np.asarray(region, dtype=bool)
    if not region.any():
        return None
    return np.median(np.asarray(worn_rgb, dtype=np.float32)[..., :3][region], 0)


def shade_distance(rgb, colour) -> np.ndarray:
    """Per pixel the mean |ΔRGB| to ``colour`` scaled to the pixel's own
    brightness (mean of RGB; ``colour`` in the pixel's light or shadow) —
    a hue comparison in RGB units (block "Skin or piece"). ``colour`` is one
    RGB colour or an image of the same shape (per pixel; Ruling A46's piece
    from the worn view compares the worn view with the base this way)."""
    rgb = np.asarray(rgb, dtype=np.float32)[..., :3]
    colour = np.asarray(colour, dtype=np.float32)[..., :3]
    scale = rgb.mean(-1, keepdims=True) / np.maximum(colour.mean(-1, keepdims=True), 1.0)
    return np.abs(rgb - scale * colour).mean(-1)


def attempt_distance(worn_rgb, region, edit_rgb, edit_mask) -> Optional[Dict[str, Any]]:
    """How far a passing attempt is from the worn piece (Ruling A37: of several stored attempts that pass, the
    nearest is published): measured on the OVERLAP of the worn garment ``region`` and the attempt's mask, both
    images in the gate frame (the attempt registered as gated). Two terms in RGB units, summed into ``score``
    (lower = nearer):

    ``colour``: per pixel the mean |ΔRGB| of the attempt to the worn pixel scaled to the attempt pixel's own
    brightness — ``shade_distance`` with the worn pixel as the colour: a hue comparison that a lighter or darker
    rendering of the same cloth does not change.

    ``structure``: per pixel the |difference| of the brightness (mean of RGB) of the worn pixel and of the attempt
    pixel scaled by median(worn brightness) / median(attempt brightness) over the overlap — the light and shade
    pattern (folds, a ruffle, an opening showing the inside) with the overall exposure taken out.

    ``{colour, structure, score, overlap}`` (``overlap`` in pixels); None without a worn image or an empty
    overlap. Reads arrays only."""
    if worn_rgb is None or region is None:
        return None
    overlap = np.asarray(region, dtype=bool) & np.asarray(edit_mask, dtype=bool)
    if not overlap.any():
        return None
    worn = np.asarray(worn_rgb, dtype=np.float32)[..., :3][overlap]
    edit = np.asarray(edit_rgb, dtype=np.float32)[..., :3][overlap]
    worn_l, edit_l = worn.mean(1), edit.mean(1)
    scale = edit_l / np.maximum(worn_l, 1.0)
    colour = float(np.abs(edit - scale[:, None] * worn).mean(1).mean())
    exposure = float(np.median(worn_l)) / max(float(np.median(edit_l)), 1.0)
    structure = float(np.abs(edit_l * exposure - worn_l).mean())
    return {"colour": round(colour, 3), "structure": round(structure, 3),
            "score": round(colour + structure, 3), "overlap": int(overlap.sum())}


def skin_pixels(ghost_rgb, ghost_mask, skin, piece, height: int) -> np.ndarray:
    """The ghost pixels that count as skin (block "Skin or piece"): within
    ``SKIN_DRGB`` of ``skin`` (mean |ΔRGB|), at least as near the skin as
    ``piece`` in the pixel's own light (``shade_distance``; without a piece
    colour the first test alone) and inside the ghost mask eroded by
    ``GHOST_RIM`` iterations @1536 (its outline is anti-aliased into the
    background)."""
    from scipy import ndimage
    rgb = np.asarray(ghost_rgb, dtype=np.float32)[..., :3]
    near = np.abs(rgb - np.asarray(skin, dtype=np.float32)).mean(2) <= SKIN_DRGB
    if piece is not None:
        near &= shade_distance(rgb, skin) <= shade_distance(rgb, piece)
    core = ndimage.binary_erosion(np.asarray(ghost_mask, dtype=bool), iterations=_iterations(GHOST_RIM, height))
    return near & core


def skin_colour(base_rgb, base_mask) -> Optional[np.ndarray]:
    """The skin of the base view: the median RGB of the base figure's pixels
    on rows y0 + 0.60·Hb .. y0 + 0.66·Hb (``SKIN_SAMPLE_ROWS``, the bare
    thighs on both views — the head rows are hair since the base carries it,
    see the block at the constants). None without a figure."""
    m0 = np.asarray(base_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return None
    y0, hb = zones
    r0 = int(y0 + SKIN_SAMPLE_ROWS[0] * hb)
    r1 = max(int(y0 + SKIN_SAMPLE_ROWS[1] * hb), r0 + 1)
    pixels = np.asarray(base_rgb, dtype=np.float32)[r0:r1, :, :3][m0[r0:r1]]
    return np.median(pixels, 0) if len(pixels) else None


def neckline(region) -> Dict[str, Any]:
    """The neckline of a garment region: ``depth`` = how far the region's
    top edge dips at its centre (median first row of the columns within
    ± 3 % of its width around the bbox centre, minus the region's top row,
    in px) and ``notch`` = the opening as a mask — on every row from the top
    down to the centre's first row, the pixels between the innermost region
    pixels left and right of the centre."""
    region = np.asarray(region, dtype=bool)
    box = _bbox(region)
    notch = np.zeros_like(region)
    if box is None:
        return {"depth": 0, "notch": notch}
    x0, top, x1, _bottom = box
    cx = (x0 + x1) / 2.0
    band = max(1, int(round(NECKLINE_BAND * (x1 - x0))))
    firsts = []
    for x in range(int(cx) - band, int(cx) + band + 1):
        rows = np.nonzero(region[:, x])[0]
        if len(rows):
            firsts.append(int(rows.min()))
    if not firsts:
        return {"depth": 0, "notch": notch}
    centre_top = int(np.median(firsts))
    for row in range(top, centre_top):
        xs = np.nonzero(region[row])[0]
        left, right = xs[xs < cx], xs[xs > cx]
        if len(left) and len(right):
            notch[row, left.max() + 1:right.min()] = True
    return {"depth": centre_top - top, "notch": notch}


def body_openings(region, ghost, base_mask) -> np.ndarray:
    """Where the worn view showed the BODY through the garment and the ghost
    draws the garment: base figure pixels outside the garment region that
    lie, on their row, between two pixels the ghost and the region share —
    one on the left, one on the right (the front of an open jacket or
    shirt, a deep V, a keyhole). The ghost shows the inside of the garment
    there — the inside of its back — which is garment, not "more".

    Anchored on ghost ∩ region, not on the region alone: the region of a
    worn view also holds re-shaded hands below the cuffs (Kai's jacket back,
    rows down to 0.58 Hb against the hem at 0.52), and the hips between them
    are no opening — a ghost that draws trousers there has no garment pixel
    of the region on those rows and still counts. A gap the base does not
    fill (between the legs, between a sleeve and the torso in the A-pose) is
    background, never an opening."""
    region = np.asarray(region, dtype=bool)
    anchor = region & np.asarray(ghost, dtype=bool)
    m0 = np.asarray(base_mask, dtype=bool)
    width = anchor.shape[1]
    cols = np.arange(width)
    has = anchor.any(1)
    first = np.where(has, anchor.argmax(1), width)
    last = np.where(has, width - 1 - anchor[:, ::-1].argmax(1), -1)
    between = (cols[None, :] > first[:, None]) & (cols[None, :] < last[:, None])
    return between & m0 & ~region


def _touching(region, ghost, height: int) -> np.ndarray:
    """The parts (connected components) of the garment region that the ghost
    mask grown by 8 px @1536 touches; the whole region when it touches none.
    A part it does not reach is no garment the ghost lost but skin the worn
    view re-shaded: the fitted Black Blazer back (Kira, 2026-11-10) had a hand
    in its region (columns 4..33, 40 px from the ghost's sleeve), which moved
    the region's bbox centre by 0.006 Hb, plus a knee and both feet that set
    its bottom. ``outside`` / ``skin_left`` are the same
    either way (a ghost pixel within the margin of a dropped part would have
    reached it).
    The LARGEST part always stays — it is the garment: Kai's "Jeans" back
    (2026-11-12) registered onto a re-shaded patch of the lower back came
    out a 20 px jeans that touched only that patch, and measured against it
    alone it passed the widened width gate (0.833); against the jeans region
    it is 0.06 wide and refused."""
    from scipy import ndimage
    labels, count = ndimage.label(region)
    if count <= 1:
        return region
    near = _margin(ghost, height)
    keep = np.unique(labels[near & region])
    keep = keep[keep > 0]
    if not len(keep):
        return region
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return np.isin(labels, np.union1d(keep, [int(sizes.argmax())]))


def _centre_column(base_mask) -> Optional[Tuple[int, int, int]]:
    """``(centre x, y0, Hb)`` of the base figure: the span centre of its
    shoulder row (``SHOULDER_ROW``); None without a figure."""
    m0 = np.asarray(base_mask, dtype=bool)
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return None
    y0, hb = zones
    span = _span(m0, int(y0 + SHOULDER_ROW * hb))
    if span is None:
        return None
    return int(round(span[0])), y0, hb


def centre_hem(mask, base_mask, *, exclude=None) -> Optional[float]:
    """``hem_c`` of a garment mask (the block "Hem and centre gap"): ``mask``
    without ``exclude``; per column within ± ``HEM_BAND``·Hb of the base
    figure's centre the last row of the column's longest vertical run, kept
    when that run is at least ``HEM_RUN_MIN`` of the mask's own height (a
    collar above an open front is no hem); the median over the kept columns,
    as (row − y0) / Hb of the base figure. None when fewer than
    ``HEM_BAND_MIN`` of the band's columns are kept."""
    centre = _centre_column(base_mask)
    if centre is None:
        return None
    cx, y0, hb = centre
    mask = np.asarray(mask, dtype=bool)
    if exclude is not None:
        mask = mask & ~np.asarray(exclude, dtype=bool)
    box = _bbox(mask)
    if box is None:
        return None
    least = HEM_RUN_MIN * (box[3] - box[1] + 1)
    half = max(1, int(round(HEM_BAND * hb)))
    lo, hi = max(0, cx - half), min(mask.shape[1], cx + half + 1)
    bottoms: List[int] = []
    for x in range(lo, hi):
        rows = np.nonzero(mask[:, x])[0]
        if not len(rows):
            continue
        breaks = np.nonzero(np.diff(rows) > 1)[0]
        starts = np.concatenate(([0], breaks + 1))
        ends = np.concatenate((breaks, [len(rows) - 1]))
        longest = int(np.argmax(ends - starts))
        if rows[ends[longest]] - rows[starts[longest]] + 1 >= least:
            bottoms.append(int(rows[ends[longest]]))
    if len(bottoms) < HEM_BAND_MIN * (hi - lo):
        return None
    return (float(np.median(bottoms)) - y0) / hb


def gap_rows(region, base_mask, hem: Optional[float]) -> Optional[Tuple[int, int]]:
    """The rows ``[r0, r1)`` the centre gap is measured on: ``GAP_ROWS`` of
    the base figure, below the worn region's centre top (its neckline) +
    ``GAP_EDGE`` and, when the worn hem ``hem`` (``centre_hem``) is measured,
    above it − ``GAP_EDGE`` (an open front has none: its centre is body);
    None when fewer than ``GAP_ROWS_MIN``·Hb rows are left or the region is
    empty."""
    centre = _centre_column(base_mask)
    region = np.asarray(region, dtype=bool)
    box = _bbox(region)
    if centre is None or box is None:
        return None
    _cx, y0, hb = centre
    top = box[1] + neckline(region)["depth"]
    r0 = int(max(y0 + GAP_ROWS[0] * hb, top + GAP_EDGE * hb))
    r1 = int(y0 + GAP_ROWS[1] * hb if hem is None else min(y0 + GAP_ROWS[1] * hb, y0 + (hem - GAP_EDGE) * hb))
    return (r0, r1) if r1 - r0 >= GAP_ROWS_MIN * hb else None


def centre_gap(rgb, mask, base_mask, rows: Tuple[int, int]) -> Optional[float]:
    """The widest run of OPEN columns within ± ``GAP_BAND``·Hb of the base
    figure's centre on ``rows`` (``gap_rows``), in Hb (the block "Hem and
    centre gap"): a pixel is open when ``mask`` does not hold it or its
    luminance (mean of RGB) is at most ``GAP_DARK`` × the median luminance of
    the mask's pixels ``GAP_BAND``..``GAP_PANEL``·Hb off the centre on those
    rows (the panels); a column when at least half its rows are. None
    without panels."""
    centre = _centre_column(base_mask)
    if centre is None:
        return None
    cx, _y0, hb = centre
    r0, r1 = rows
    mask = np.asarray(mask, dtype=bool)[r0:r1]
    lum = np.asarray(rgb, dtype=np.float32)[r0:r1, :, :3].mean(2)
    off = np.abs(np.arange(mask.shape[1]) - cx)
    half = max(1, int(round(GAP_BAND * hb)))
    panel = mask & ((off > half) & (off <= GAP_PANEL * hb))[None, :]
    if not panel.any():
        return None
    dark = GAP_DARK * float(np.median(lum[panel]))
    lo, hi = max(0, cx - half), min(mask.shape[1], cx + half + 1)
    opened = (~mask[:, lo:hi]) | (lum[:, lo:hi] <= dark)
    columns = opened.mean(0) >= 0.5
    best = run = 0
    for is_open in columns:
        run = run + 1 if is_open else 0
        best = max(best, run)
    return best / hb


def ghost_clothing_gate(base_rgb, base_mask, garment_mask, ghost_rgb, ghost_mask, *,
                        view: str, length_free: bool = False, worn_rgb=None,
                        closable: bool = False) -> Dict[str, Any]:
    """Step 2 gate of clothing: the piece alone against the garment region of
    the accepted worn view (``garment_region``).

    Gate version 2 (``GHOST_GATE_VERSION``, the block at the constants):
    refused only for what would put something wrong into the mesh.
    ``top_dy`` / ``centre_dx`` (fractions of Hb) and ``w_ratio`` / ``h_ratio``
    from the bounding boxes of the region and the ghost mask; the position
    is RECORDED — |top_dy| > 0.0055 / |centre_dx| > 0.007 go into
    ``warnings``, not ``reasons`` (the cut-out re-frames every view on its
    own box) — and only a width outside [0.80, 1.25] refuses (a cut-off
    piece); ``skin_left`` =
    ghost pixels outside the region grown by 8 px @1536 whose mean |ΔRGB| to
    the base's skin (``skin_colour``, the thighs) is <= 30, over the region's
    area (<= 0.005: no head, arm, leg or foot left; a skin-coloured garment
    is not counted inside its own region; since gate version 6, Ruling A32,
    only pixels at least as near the skin as the piece's own colour
    ``piece_colour`` of ``worn_rgb`` in the same light and off the ghost's
    outline, ``skin_pixels``); ``outside_near`` = every ghost
    pixel out there except in the neckline opening and the body openings
    (``body_openings``: the inside of the garment shows there, e.g. through
    an open jacket), over the region's area — a warning above 0.05 (the
    piece's own rim, gate version 3); ``outside`` = the largest connected
    part of those pixels farther than ``CLOTH_FAR``·Hb from the region, over
    the region's area (<= 0.05: no legs, figure, stand or other garment
    drawn on). When the region has a neckline (``neckline`` depth >= 0.012·Hb)
    ``neck_fill`` = the share of its opening the ghost mask covers — reported,
    not gated (a filled notch still meshes into an open neckline, see the
    calibration block).
    ``bottom`` (row) and ``hem_t`` = (bottom − y0) / Hb feed ``hems_agree``.
    The region is measured by its parts the ghost reaches (``_touching``).
    The chain registers the ghost onto the region before this gate
    (``register``), so the offsets are the residual of that correction.
    ``length_free`` (a waistband piece's ghost, registered by
    ``register_waistband``): ``outside`` / ``outside_near`` leave out the
    ghost rows below the region's hem (``_hem_row``, recorded as
    ``hem_row``) grown by the margin — the length is the edit's, not
    measured (ruling 13d); ``skin_left`` still counts there (feet left in the
    image), ``h_ratio`` / ``hem_t`` are reported.
    Gate version 4 (Ruling A17, the block "Hem and centre gap"): ``hem_c`` of
    the ghost and ``worn_hem_c`` of the region without its skin-coloured
    pixels (``worn_rgb`` within ``SKIN_DRGB`` of the skin sample;
    ``centre_hem``) — refused when they differ by more than ``HEM_AGREE``
    (not for ``length_free``; ``hem_refused``); a ``closable`` piece's FRONT
    with ``worn_rgb`` records ``centre_gap`` / ``worn_centre_gap``
    (``centre_gap`` on ``gap_rows``) and is refused when exactly one of
    them reaches ``GAP_MIN`` (the ghost open where the piece is worn
    closed, or closed where it is worn open; ``look_refused``).
    Gate version 7 (Ruling A46, the block "Added parts"): ``added_reach`` /
    ``added_part`` of the parts ``outside_near`` counts (``added_parts``) —
    refused above ``ADDED_REACH_MAX`` (``added_refused``: a strap or chain the
    worn piece does not have; thin, so ``outside`` misses it).
    Calibration: the "Clothing" block above."""
    from scipy import ndimage
    _check(base_rgb, base_mask, ghost_rgb, ghost_mask)
    m0 = np.asarray(base_mask, dtype=bool)
    region = np.asarray(garment_mask, dtype=bool)
    ghost = np.asarray(ghost_mask, dtype=bool)
    if region.shape != m0.shape:
        raise ValueError("garment_mask differs in size from the base")
    height = m0.shape[0]
    zones = _zones(m0)
    if zones is None or zones[1] <= 0:
        return {"view": view, "gate_version": GHOST_GATE_VERSION, "ok": False,
                "reasons": ["no figure in the base view"]}
    y0, hb = zones
    region = _touching(region, ghost, height)
    a, b = _bbox(region), _bbox(ghost)
    out: Dict[str, Any] = {"view": view, "H": height, "body_top": y0, "body_h": hb,
                           "bbox_garment": a, "bbox_ghost": b, "gate_version": GHOST_GATE_VERSION}
    if a is None:
        return {**out, "ok": False, "reasons": ["no garment found in the worn view"]}
    if b is None:
        return {**out, "ok": False, "reasons": ["no garment in the ghost image"]}
    top_dy = (b[1] - a[1]) / hb
    centre_dx = (b[0] + b[2] - a[0] - a[2]) / 2.0 / hb
    w_ratio = (b[2] - b[0]) / max(a[2] - a[0], 1)
    h_ratio = (b[3] - b[1]) / max(a[3] - a[1], 1)
    area = max(int(region.sum()), 1)
    beyond = ghost & ~_margin(region, height)
    skin = skin_colour(base_rgb, base_mask)
    skin_beyond = beyond
    hem = None
    if length_free:
        # Below the region's hem (plus the margin) only skin counts: the length is free.
        hem = _hem_row(region, height)
        beyond = beyond.copy()
        beyond[hem + 1 + _iterations(GARMENT_MARGIN, height):] = False
    if skin is None:
        skin_left = 0.0
    else:
        # Ruling A32: skin only where nearer the skin than the piece, off the ghost's outline.
        near = skin_pixels(ghost_rgb, ghost, skin, piece_colour(worn_rgb, region), height)
        skin_left = float((skin_beyond & near).sum() / area)
    neck = neckline(region)
    depth = neck["depth"] / hb
    has_neckline = depth >= NECKLINE_MIN_DEPTH and bool(neck["notch"].any())
    # The inside of the garment seen through the neckline or an opening of the
    # front (an open jacket) is garment, not "more".
    inside = body_openings(region, ghost, m0)
    if has_neckline:
        inside |= neck["notch"]
    rest = beyond & ~inside
    outside_near = float(rest.sum() / area)
    far = rest & (ndimage.distance_transform_edt(~region) > CLOTH_FAR * hb)
    labels, count = ndimage.label(far)
    outside = float(np.bincount(labels.ravel())[1:].max() / area) if count else 0.0
    opening_seen = float((beyond & inside).sum() / area)
    added = added_parts(rest, a, hb, area)
    neck_fill = float((ghost & neck["notch"]).sum() / neck["notch"].sum()) if has_neckline else None
    iou = float((region & ghost).sum() / max((region | ghost).sum(), 1))
    warnings = []
    if abs(top_dy) > CLOTH_TOP_DY_WARN:
        warnings.append(f"garment top moved: {_r(top_dy, 4)} Hb (recorded from {CLOTH_TOP_DY_WARN})")
    if abs(centre_dx) > CLOTH_CENTRE_DX_WARN:
        warnings.append(f"garment centre moved: {_r(centre_dx, 4)} Hb (recorded from {CLOTH_CENTRE_DX_WARN})")
    if outside_near > CLOTH_OUTSIDE_MAX:
        warnings.append(f"garment rim beyond the worn piece: {_r(outside_near, 4)} "
                        f"(recorded from {CLOTH_OUTSIDE_MAX}, within {CLOTH_FAR} Hb)")
    reasons = []
    if not CLOTH_W_RATIO_MIN <= w_ratio <= CLOTH_W_RATIO_MAX:
        reasons.append(f"garment width changed: ratio {round(w_ratio, 3)} outside "
                       f"[{CLOTH_W_RATIO_MIN}, {CLOTH_W_RATIO_MAX}]")
    if skin_left > SKIN_LEFT_MAX:
        reasons.append(f"skin left in the image: {_r(skin_left, 4)} > {SKIN_LEFT_MAX}")
    if outside > CLOTH_OUTSIDE_MAX:
        reasons.append(f"more than the garment in the image: a part of {_r(outside, 4)} more than "
                       f"{CLOTH_FAR} Hb beyond the worn piece > {CLOTH_OUTSIDE_MAX}")
    # Ruling A46: a thin added part (a strap) carries little area, so ``outside`` misses it — its reach does not.
    added_refused = added["reach"] > ADDED_REACH_MAX
    if added_refused:
        reasons.append(f"a part the worn piece does not have: it reaches {_r(added['reach'], 4)} Hb past the "
                       f"worn piece > {ADDED_REACH_MAX} Hb (a strap, chain or band added by the edit)")
    # The worn region without skin (a belly or crotch the edit re-shaded) —
    # the ghost as it is: its openings are NOT left out (``body_openings``
    # counts the hips between two cuffs as one, and the bulge below Kai's
    # jacket back lay exactly there).
    worn_skin = None
    if worn_rgb is not None and skin is not None:
        worn_skin = np.abs(np.asarray(worn_rgb, dtype=np.float32)[..., :3] - skin).mean(2) <= SKIN_DRGB
    hem_c, worn_hem_c = centre_hem(ghost, m0), centre_hem(region, m0, exclude=worn_skin)
    hem_refused = (not length_free and hem_c is not None and worn_hem_c is not None
                   and abs(hem_c - worn_hem_c) > HEM_AGREE)
    look_refused = False
    if hem_refused:
        reasons.append(f"garment ends at another height than the worn piece: |Δ| {_r(abs(hem_c - worn_hem_c), 4)} "
                       f"Hb > {HEM_AGREE} Hb (ghost {_r(hem_c, 5)}, worn {_r(worn_hem_c, 5)})")
    gaps: Dict[str, Any] = {}
    if closable and view == "front" and worn_rgb is not None:
        rows = gap_rows(region, m0, worn_hem_c)
        gap = centre_gap(ghost_rgb, ghost, m0, rows) if rows else None
        worn_gap = centre_gap(worn_rgb, region, m0, rows) if rows else None
        gaps = {"centre_gap": _r(gap, 4), "worn_centre_gap": _r(worn_gap, 4)}
        look_refused = gap is not None and worn_gap is not None and (gap >= GAP_MIN) != (worn_gap >= GAP_MIN)
        if look_refused:
            look = ("open where the worn piece is closed" if gap >= GAP_MIN
                    else "closed where the worn piece is open")
            reasons.append(f"garment {look}: a centre gap of {_r(gap, 4)} Hb (worn {_r(worn_gap, 4)} Hb, "
                           f"open from {GAP_MIN} Hb)")
    return {**out, "top_dy": _r(top_dy, 5), "centre_dx": _r(centre_dx, 5), "w_ratio": round(w_ratio, 3),
            "h_ratio": round(h_ratio, 3), "iou": round(iou, 3), "skin_left": _r(skin_left, 5),
            "outside": _r(outside, 5), "outside_near": _r(outside_near, 5), "opening_seen": _r(opening_seen, 5),
            "neckline_depth": _r(depth, 4), "neck_fill": _r(neck_fill, 3),
            "added_reach": _r(added["reach"], 4), "added_part": _r(added["part"], 5),
            "added_thick": _r(added["thick"], 4),
            "added_refused": bool(added_refused),
            "bottom": b[3], "hem_t": _r((b[3] - y0) / hb, 5),
            "hem_c": _r(hem_c, 5), "worn_hem_c": _r(worn_hem_c, 5), **gaps,
            "hem_refused": bool(hem_refused), "look_refused": bool(look_refused),
            **({"length_free": True, "hem_row": hem} if length_free else {}),
            "gate_version": GHOST_GATE_VERSION, "warnings": warnings,
            "ok": not reasons, "reasons": reasons}


def added_parts(rest, bbox, hb: int, area: int) -> Dict[str, float]:
    """How far the ghost's THIN added parts reach past the worn piece (Ruling A46, the block "Added parts"):
    ``rest`` = the ghost pixels beyond the worn region's margin that are no opening (``ghost_clothing_gate``),
    ``bbox`` = the worn region's box ``[x0, y0, x1, y1]``. Per connected part of ``rest`` of at least
    ``ADDED_MIN_PART`` of the region's ``area``: its farthest pixel's distance from the box (Euclidean, 0
    inside it) and its thickness = its pixels over that distance (a strap: its width; a hem hanging lower:
    the piece's width), both over Hb. ``{reach, part, thick}`` of the THIN part (thickness up to
    ``ADDED_THIN_MAX``) that reaches farthest (``part`` its area over the region's); all 0.0 without one."""
    from scipy import ndimage
    none = {"reach": 0.0, "part": 0.0, "thick": 0.0}
    rest = np.asarray(rest, dtype=bool)
    if not rest.any() or bbox is None or hb <= 0:
        return none
    x0, y0, x1, y1 = bbox
    h, w = rest.shape
    xs = np.arange(w, dtype=np.float32)
    ys = np.arange(h, dtype=np.float32)
    dx = np.maximum(np.maximum(x0 - xs, xs - x1), 0.0)
    dy = np.maximum(np.maximum(y0 - ys, ys - y1), 0.0)
    dist = np.hypot(dy[:, None], dx[None, :])
    labels, count = ndimage.label(rest)
    if not count:
        return none
    pixels = np.bincount(labels.ravel(), minlength=count + 1)[1:].astype(float)
    reach_px = np.asarray(ndimage.maximum(dist, labels, np.arange(1, count + 1)), dtype=float)
    share = pixels / max(int(area), 1)
    thick = pixels / np.maximum(reach_px, 1.0) / hb
    reach = reach_px / hb
    reach[(share < ADDED_MIN_PART) | (thick > ADDED_THIN_MAX)] = 0.0
    k = int(np.argmax(reach))
    if reach[k] <= 0.0:
        return none
    return {"reach": float(reach[k]), "part": float(share[k]), "thick": float(thick[k])}


def _hem_row(region: np.ndarray, height: int) -> int:
    """The hem of a garment region for ``length_free``: the last row of the
    region opened by ``GARMENT_MARGIN`` iterations @1536 (a strand narrower
    than twice the margin — the re-shaded edge of a leg in a slit — is no
    cloth) without its parts below ``WAIST_PART_MIN`` of the largest
    (``_main_parts``: a foot). The region's own last row when the opening
    leaves nothing (a piece narrower than that everywhere)."""
    from scipy import ndimage
    region = np.asarray(region, dtype=bool)
    opened = _main_parts(ndimage.binary_opening(region, iterations=_iterations(GARMENT_MARGIN, height)))
    box = _bbox(opened) or _bbox(region)
    return int(box[3])


def _hem_pair(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[Tuple[float, float, str]]:
    """``(front hem, back hem, key)`` of two ghost records: their ``hem_c``
    when both have one (gate version 4, the block "Hem and centre gap"), else
    their bbox ``hem_t`` (a piece with nothing at the centre); None when a
    record has neither."""
    for key in ("hem_c", "hem_t"):
        try:
            return float(front_gate[key]), float(back_gate[key]), key
        except (KeyError, TypeError, ValueError):
            continue
    return None


def hems_gap(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[tuple]:
    """``(|hem front − hem back|, HEM_AGREE)`` of the ghost pair — both hems
    against their own view's figure (fractions of Hb), the centre hems
    (``_hem_pair``); None when a record lacks a hem."""
    pair = _hem_pair(front_gate, back_gate)
    if pair is None:
        return None
    return abs(pair[0] - pair[1]), HEM_AGREE


def hems_agree(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> bool:
    """The front and back ghost end at the same height of the figure:
    |hem front − hem back| <= 0.02 (fractions of the body height Hb)."""
    gap = hems_gap(front_gate, back_gate)
    return gap is not None and gap[0] <= gap[1]


def hems_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """The refusal reason of a front ghost attempt whose hem is not where the
    accepted back ghost's is (``hems_agree``); None when they agree or the
    attempt has no measured hem. Since Ruling A17 only the pair repair of
    the chain checks a front against the ghost back (``garments``); a front
    attempt is checked against the WORN back (``worn_hems_reason``)."""
    gap = hems_gap(front_gate, back_gate)
    if gap is None or gap[0] <= gap[1]:
        return None
    key = _hem_pair(front_gate, back_gate)[2]
    return (f"garment ends at another height than in the back view: |Δ| {_r(gap[0], 4)} Hb > {gap[1]} Hb "
            f"(front {front_gate.get(key)}, back {back_gate.get(key)})")


def worn_hems_reason(front_gate: Dict[str, Any], back_gate: Dict[str, Any]) -> Optional[str]:
    """Ruling A17 (b): the refusal reason of a front ghost attempt whose centre
    hem (``hem_c``) is more than ``HEM_AGREE`` from the WORN back's
    (``worn_hem_c`` of the accepted back ghost's record, measured on the worn
    back's garment region); the front against its own worn view is the
    gate's (``ghost_clothing_gate``). None when they agree or a hem is not
    measured (an open front, nothing at the centre) — never the ghost back's
    hem in its place; the ghost pair still has to agree (``hems_agree``)."""
    front, worn_back = front_gate.get("hem_c"), back_gate.get("worn_hem_c")
    if not isinstance(front, (int, float)) or not isinstance(worn_back, (int, float)):
        return None
    gap = abs(front - worn_back)
    if gap <= HEM_AGREE:
        return None
    return (f"garment ends at another height than in the back view: |Δ| {_r(gap, 4)} Hb > {HEM_AGREE} Hb "
            f"(front {_r(front, 5)}, worn back {_r(worn_back, 5)})")


def hem_deviation(record: Dict[str, Any]) -> Optional[float]:
    """|``hem_c`` − ``worn_hem_c``| of a ghost record: how far the ghost's hem
    is from its own worn view's (Ruling A17 c); None when unmeasured."""
    try:
        return abs(float(record["hem_c"]) - float(record["worn_hem_c"]))
    except (KeyError, TypeError, ValueError):
        return None


# --- Hem snap (Ruling A27, 2026-11-13) -------------------------------------
#
# The worn view on the body is the truth for the LENGTH of a piece; the ghost
# only supplies the unseen inside and back. Kai's leather jacket
# (item_555a7a01, fsig 3749e6028b55, live 2026-11-13 21:42): ghost back
# attempt 2 was refused ONLY for its hem, ghost 0.50281 against the worn
# 0.4684 (|Δ| 0.0344 Hb > HEM_AGREE) — the same jacket drawn about 8 % larger
# (outline registration 0.923, just beyond its cap, so gated as rendered),
# its sleeves hanging lower. Attempt 1 was a LONGER jacket (|Δ| 0.0758 and a
# part of 0.1418 beyond the worn piece) — a true refusal. A refusal of such
# an attempt costs a queued or paid render for a few centimetres.
#
# So a ghost record whose only reason is the hem rule (``HEM_REASON``),
# |hem_c − worn_hem_c| <= HEM_SNAP_MAX, is corrected (``hem_snap_due``): the
# rows of the ghost image from the UNDERARM line down are rescaled
# vertically about that line by ``scale`` = (worn hem row − line) / (ghost
# hem row − line), so the ghost's centre hem (``centre_hem``, the gate's own
# measure) lands on the worn piece's; the rows above the line (collar,
# shoulders — what the registration laid onto the worn region) stay pixel
# for pixel. The underarm line (``underarm_row``) is read on the worn
# view's garment region — the reference the registration lays the ghost onto
# —: the first row from the shoulder row down where the run of the region
# through the figure's centre column has region pixels on BOTH sides (the
# sleeves part from the body); a region without sleeves (a vest, an open
# front with nothing at the centre) takes the base figure's own underarm,
# measured the same way on its mask. Kai's copies (Hb 1424, y0 42, centre
# column 428, BiRefNet masks as cached): the region parts at row 428
# (0.27107 Hb; the base figure at 412, 0.25983); ghost hem row 758.0, worn
# hem row 709.0 -> scale 281.0 / 330.0 = 0.85152 (the sidecar's
# ``hem_snap``); snapped, attempt 2 passes every rule (hem 0.4684 = the
# worn hem, ``outside`` 0.0286 -> 0.0034, width 1.08 unchanged), attempt 1
# is not snapped (two reasons). The line must lie at least HEM_SNAP_SPAN·Hb above both hems
# (a piece whose hem is at the underarm has nothing to rescale). The
# corrected image is gated again in full (the chain's pair check too) and
# only kept when it passes; otherwise the attempt stays refused as rendered
# (``hem_snap_refused`` records why). Beyond HEM_SNAP_MAX, or with any other
# reason, nothing is corrected. A waistband piece (``length_free``) has no
# hem rule. Cost if wrong: a ghost rescaled by up to ~10 % of its torso
# length below the underarm.
HEM_SNAP_MAX = 0.05         # |ghost hem − worn hem| / Hb up to which a hem-only refusal is snapped
HEM_SNAP_SPAN = 0.05        # Hb the underarm line must lie above both hems
HEM_REASON = "garment ends at another height than the worn piece"


def hem_snap_due(record: Dict[str, Any]) -> bool:
    """Whether a ghost gate record is refused by the hem rule ALONE
    (``hem_refused``, its one reason ``HEM_REASON``), not ``length_free``,
    with |``hem_c`` − ``worn_hem_c``| <= ``HEM_SNAP_MAX`` — the attempt the
    chain snaps (the block "Hem snap")."""
    if not isinstance(record, dict) or record.get("ok") or record.get("hem_refused") is not True:
        return False
    if record.get("length_free"):
        return False
    reasons = record.get("reasons") or []
    if len(reasons) != 1 or not str(reasons[0]).startswith(HEM_REASON):
        return False
    deviation = hem_deviation(record)
    return deviation is not None and deviation <= HEM_SNAP_MAX


def _parted_row(mask: np.ndarray, cx: int, start: int, stop: int) -> Optional[int]:
    """The first row in ``[start, stop)`` where the run of ``mask`` through
    column ``cx`` has mask pixels on both sides of it; None when none has."""
    for row in range(max(start, 0), min(stop, mask.shape[0])):
        line = mask[row]
        if not line[cx]:
            continue
        xs = np.nonzero(~line[:cx])[0]
        left = (xs.max() + 1) if len(xs) else 0
        xs = np.nonzero(~line[cx:])[0]
        right = cx + int(xs.min()) if len(xs) else line.shape[0]
        if line[:left].any() and line[right:].any():
            return row
    return None


def underarm_row(region, base_mask, *, stop: Optional[int] = None) -> Optional[int]:
    """The underarm line of a garment (the block "Hem snap"), as a row of the
    gate frame: the first row from the base figure's shoulder row
    (``SHOULDER_ROW``) down to ``stop`` (default: the figure's last row)
    where the worn ``region`` parts into the body and both sleeves; a region
    that never does (no sleeves, nothing at the centre) takes the base
    figure's own underarm. None when neither parts."""
    centre = _centre_column(base_mask)
    if centre is None:
        return None
    cx, y0, hb = centre
    start = int(y0 + SHOULDER_ROW * hb)
    stop = int(y0 + hb) if stop is None else int(stop)
    for mask in (region, base_mask):
        row = _parted_row(np.asarray(mask, dtype=bool), cx, start, stop)
        if row is not None:
            return row
    return None


def hem_snap(record: Dict[str, Any], ghost_mask, region, base_mask) -> Optional[Dict[str, Any]]:
    """The hem snap of a ghost record that is due (``hem_snap_due``):
    ``{from, to, scale, underarm, row}`` — ``from`` the ghost's ``hem_c``
    (measured again on ``ghost_mask``, the mask the gate measured), ``to``
    the record's ``worn_hem_c``, ``underarm`` the line in Hb and ``row`` in
    px of the gate frame (``underarm_row`` of the worn ``region``), ``scale``
    = (to row − row) / (from row − row), rounded to 5 digits (the value
    ``snap_rows`` applies). None when not due, unmeasured, or the line is
    not ``HEM_SNAP_SPAN``·Hb above both hems."""
    if not hem_snap_due(record):
        return None
    centre = _centre_column(base_mask)
    ghost_hem = centre_hem(ghost_mask, base_mask)
    if centre is None or ghost_hem is None:
        return None
    _cx, y0, hb = centre
    worn = float(record["worn_hem_c"])
    src, dst = y0 + ghost_hem * hb, y0 + worn * hb
    row = underarm_row(region, base_mask, stop=int(min(src, dst)))
    if row is None or min(src, dst) - row < HEM_SNAP_SPAN * hb:
        return None
    scale = round((dst - row) / (src - row), 5)
    return {"from": _r(ghost_hem, 5), "to": _r(worn, 5), "scale": scale,
            "underarm": _r((row - y0) / hb, 5), "row": int(row)}


def snap_rows(array, snap: Dict[str, Any], *, factor: float = 1.0,
              fill: Optional[Sequence[float]] = None) -> np.ndarray:
    """``array`` (an ``(H, W)`` bool mask or an ``(H, W, 3)`` RGB image)
    with its rows from ``snap["row"]`` down rescaled vertically by
    ``snap["scale"]`` about that row (``hem_snap``): output row q >= line
    takes the input at line + (q − line) / scale, linearly between two rows;
    the rows above stay as they are. ``factor`` = rows of this array per row
    of the gate frame (an image of another size than the masks). A mask is
    thresholded at 0.5; rows that map beyond the image take 0 / ``fill``
    (default: the median of the image's border pixels — the plain
    background)."""
    arr = np.asarray(array)
    h = arr.shape[0]
    line = float(snap["row"]) * float(factor)
    scale = float(snap["scale"])
    q = np.arange(h, dtype=np.float64)
    src = np.where(q < line, q, line + (q - line) / scale)
    inside = src <= h - 1
    lo = np.clip(np.floor(src).astype(int), 0, h - 1)
    hi = np.clip(lo + 1, 0, h - 1)
    frac = np.where(inside, src - np.floor(src), 0.0)
    if arr.ndim == 2:
        a = arr.astype(np.float32)
        out = a[lo] * (1.0 - frac)[:, None] + a[hi] * frac[:, None]
        out[~inside] = 0.0
        return out >= 0.5
    rgb = arr[..., :3].astype(np.float32)
    if fill is None:
        border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        fill = np.median(border, 0)
    out = rgb[lo] * (1.0 - frac)[:, None, None] + rgb[hi] * frac[:, None, None]
    out[~inside] = np.asarray(fill, dtype=np.float32)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


# --- Registration of a piece-only (ghost) image -------------------------------
#
# The edit model redraws the piece alone, and it may redraw it a centimetre or
# two off or a few per cent larger (live, Kira's "Black Blazer" back,
# 2026-11-10: attempt 1 drawn 5 % larger and 9 px higher — refused for
# top_dy -0.0064 / centre_dx 0.0088 — although the piece itself is right).
# A pure 2-D offset/scale is corrected before the position gates: ``register``
# estimates a similarity (translation + uniform scale about the ghost's
# centroid, no rotation) of the ghost silhouette onto the reference (the
# worn view's garment region / the haired view's hair), ``warp`` applies it,
# and the gates then measure the RESIDUAL with their unchanged limits.
#
# The estimate: the outline points of the ghost mask, minus those whose
# outward normal faces down (cos > REG_DOWN_FACING: hems, cuffs, the hair's
# ends — the ghost shows the inside there and the worn region of a fitted
# back runs on into the re-shaded legs) and minus those below the
# reference's last row (the hair reference stops at 0.22·Hb), are moved
# onto the reference outline: Nelder-Mead on the mean distance to that
# outline (distance transform, bilinear), truncated first at REG_SHIFT_MAX
# then at REG_TRUNC_FINE (fragments of the reference — a re-shaded hand —
# pull at most that far). A correction beyond REG_SHIFT_MAX (|centroid
# shift| / Hb) or outside [REG_SCALE_MIN, REG_SCALE_MAX] (the hair width
# gate's range) is not applied: the gates measure the image as it is.
# Measured on the blazer back (``~/claude-out/blazer-ghost``): attempt 1
# shift (0.0035, -0.0036) Hb, scale 0.950, outline distance 6.55 -> 0.72 px;
# attempt 2 (0.0004, 0.0006) Hb, scale 1.002 (1.03 -> 0.87 px).
REG_SHIFT_MAX = 0.04        # |centroid shift| / Hb a registration may correct
REG_SCALE_MIN = 0.93
REG_SCALE_MAX = 1.07
REG_TRUNC_FINE = 0.01       # second-stage truncation of the outline distance / Hb
REG_DOWN_FACING = 0.7       # outline points facing down more than this (cos) are left out
REG_SMOOTH = 2.0            # Gaussian sigma @1536 of the mask for the outline normals
REG_MAX_POINTS = 3000       # outline points used (evenly thinned)
REG_NEGLIGIBLE_PX = 1.0     # a correction moving no ghost pixel further than this is not applied


def _outline(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage
    return mask & ~ndimage.binary_erosion(mask)


def register(reference_mask, ghost_mask, *, body_h: int) -> Optional[Dict[str, Any]]:
    """The similarity that lays the ghost silhouette onto ``reference_mask``
    (both full-frame bool masks of one size; ``body_h`` = Hb in px), see the
    "Registration" block: ``{centre: [row, col], shift_px: [dy, dx], scale,
    shift: [dx, dy] / Hb, fit_px: [mean outline distance before, after]
    (truncated at REG_TRUNC_FINE·Hb), within_caps, negligible}``. A ghost
    pixel p maps to ``centre + scale·(p − centre) + shift_px``. None when
    either mask is empty or the ghost has no usable outline."""
    from scipy import ndimage, optimize
    ref = np.asarray(reference_mask, dtype=bool)
    ghost = np.asarray(ghost_mask, dtype=bool)
    if ref.shape != ghost.shape:
        raise ValueError("reference and ghost masks differ in size")
    if not ref.any() or not ghost.any() or body_h <= 0:
        return None
    height = ghost.shape[0]
    dist = ndimage.distance_transform_edt(~_outline(ref))
    smooth = ndimage.gaussian_filter(ghost.astype(np.float32), REG_SMOOTH * height / SPIKE_HEIGHT)
    grad_y, grad_x = np.gradient(smooth)
    pts = np.argwhere(_outline(ghost))
    ny, nx = -grad_y[pts[:, 0], pts[:, 1]], -grad_x[pts[:, 0], pts[:, 1]]
    keep = ny / (np.hypot(ny, nx) + 1e-9) <= REG_DOWN_FACING
    keep &= pts[:, 0] <= np.nonzero(ref.any(1))[0].max()
    pts = pts[keep].astype(np.float64)
    if len(pts) < 8:
        return None
    if len(pts) > REG_MAX_POINTS:
        pts = pts[np.linspace(0, len(pts) - 1, REG_MAX_POINTS).astype(int)]
    centre = np.argwhere(ghost).mean(0)

    def cost(p, trunc):
        moved = centre + np.exp(p[2]) * (pts - centre) + p[:2]
        d = ndimage.map_coordinates(dist, moved.T, order=1, mode="nearest")
        return float(np.minimum(d, trunc).mean())

    p = np.zeros(3)
    for trunc in (REG_SHIFT_MAX * body_h, REG_TRUNC_FINE * body_h):
        simplex = [p, p + (5.0, 0, 0), p + (0, 5.0, 0), p + (0, 0, 0.01)]
        p = optimize.minimize(cost, p, args=(trunc,), method="Nelder-Mead",
                              options={"xatol": 0.05, "fatol": 1e-4, "initial_simplex": simplex}).x
    fine = REG_TRUNC_FINE * body_h
    dy, dx, scale = float(p[0]), float(p[1]), float(np.exp(p[2]))
    shift = float(np.hypot(dx, dy)) / body_h
    # The farthest any ghost pixel moves: the shift plus the scale at the bbox corners.
    rows, cols = np.nonzero(ghost)
    reach = max(abs(rows.min() - centre[0]), abs(rows.max() - centre[0]),
                abs(cols.min() - centre[1]), abs(cols.max() - centre[1]))
    moved_px = float(np.hypot(dx, dy)) + abs(scale - 1.0) * float(reach) * np.sqrt(2.0)
    return {"centre": [round(float(centre[0]), 3), round(float(centre[1]), 3)],
            "shift_px": [round(dy, 3), round(dx, 3)], "scale": round(scale, 5),
            "shift": [_r(dx / body_h, 5), _r(dy / body_h, 5)], "shift_abs": _r(shift, 5),
            "fit_px": [_r(cost(np.zeros(3), fine), 3), _r(cost(p, fine), 3)],
            "within_caps": bool(shift <= REG_SHIFT_MAX and REG_SCALE_MIN <= scale <= REG_SCALE_MAX),
            "negligible": bool(moved_px < REG_NEGLIGIBLE_PX)}


def warp(array, registration: Dict[str, Any], *, factor: Tuple[float, float] = (1.0, 1.0),
         fill: Optional[Sequence[float]] = None) -> np.ndarray:
    """``array`` (an ``(H, W)`` bool mask or an ``(H, W, 3)`` RGB image)
    moved by ``registration`` (``register``): every output pixel q takes the
    input at ``centre + (q − centre − shift_px) / scale``. ``factor`` =
    (rows, cols) of this array per pixel of the registration's frame (an
    image of another size than the masks). A mask is resampled bilinearly
    and thresholded at 0.5; an image bilinearly per channel, the uncovered
    border filled with ``fill`` (default: the median of the image's border
    pixels — the plain background)."""
    from scipy import ndimage
    arr = np.asarray(array)
    f = np.asarray(factor, dtype=np.float64)
    centre = np.asarray(registration["centre"], dtype=np.float64) * f
    shift = np.asarray(registration["shift_px"], dtype=np.float64) * f
    scale = float(registration["scale"])
    offset = centre - (centre + shift) / scale
    matrix = np.full(2, 1.0 / scale)
    if arr.ndim == 2:
        out = ndimage.affine_transform(arr.astype(np.float32), matrix, offset=offset, order=1,
                                       mode="constant", cval=0.0)
        return out >= 0.5
    if fill is None:
        border = np.concatenate([arr[0, :, :3], arr[-1, :, :3], arr[:, 0, :3], arr[:, -1, :3]])
        fill = np.median(border.astype(np.float32), 0)
    channels = [ndimage.affine_transform(arr[..., k].astype(np.float32), matrix, offset=offset, order=1,
                                         mode="constant", cval=float(fill[k])) for k in range(3)]
    return np.clip(np.rint(np.stack(channels, -1)), 0, 255).astype(np.uint8)


# --- Waistband registration of a bottom's ghost (ruling 13d back, 13f front) --
#
# The edit model turns the ghost back of a bottom into a centred product shot
# (clone, Kai's "Tailored Black Trousers" item_750811f7, 2026-11-11: the worn
# back's garment spans rows 612..1407, attempt 1 114..1381 = height x1.59 and
# width x1.27, attempt 2 243..1399 = x1.45 / x1.34; ``register`` estimated
# 0.786 and 1.049 — beyond the caps or caught on the wrong outline). A piece
# whose top edge is a waistband (``waistband_piece``) has its ghost (13f: the
# front too — it reframed the same way, ×1.19..1.37 wide) laid onto the worn
# view's garment region by ONE uniform scale — the waistband
# width — and a shift that puts the ghost's top row and waistband centre on
# the region's; no outline caps (only WAIST_SCALE_RANGE, below), the length is the edit's (``length_ratio`` reported,
# ``ghost_clothing_gate(length_free=True)``). The waistband width is the
# median row span over the rows WAIST_BAND·Hb below the top — the ghost's rows
# scaled by the estimate (WAIST_ITERATIONS fixed-point steps from the bbox
# width ratio). Measured on the two refused attempts (BiRefNet masks, Hb
# 1389): region waistband 240 px; ghost 359 / 382 px -> scale 0.6685 /
# 0.6283 (band 0.005..0.03: 0.6671 / 0.6234, 0.02..0.06: 0.6725 / 0.6294).
# Gated after it: top_dy 0.0 / 0.0, centre_dx -0.0004 / +0.0004,
# length_ratio 1.065 / 0.913, w_ratio 0.850 / 0.844, outside 0.159 / 0.039 —
# both still refused for their WIDTH: the product shot draws the legs
# straight down (span at 0.95 of the garment height / waistband: 407 / 359
# = 1.13, 438 / 382 = 1.15) where the worn legs stand apart (318 / 240 =
# 1.33), and attempt 1's straight legs lie in the worn region's
# gap between the ankles (its ``outside``). Neither a scale nor the length
# explains that; the width gate keeps checking the shape.
# Tops keep ``register``: under a collar the band runs into the shoulder
# slope, its width changes fast with the row — the accepted Black Blazer back
# (Kira) measured 0.656 with this band (0.954 / 0.992 with the other two)
# where ``register`` found 0.997.
# The region a waistband is measured on is its garment, not every part of
# it: Kai's "Jeans" back (live, 2026-11-12, ghost gate version 1) had a
# re-shaded patch of the lower back in its worn region — 907 px on rows
# 544..599 (0.351..0.391 Hb), cols 314..338 — above the jeans (149 530 px,
# rows 640..1391). Its top was the region's top, its 20 px the "waistband"
# against the ghost's 357 px: scale 0.056 (0.040 / 0.042 on the next run),
# the attempt file rewritten as a 20 px jeans and refused for its width
# (0.875 / 0.833) — the measurement, not the image. Glut's boots ("legs"
# slot) went the same way (0.015). So: parts below WAIST_PART_MIN of the
# largest part are left out (two boots stay, a patch goes), and an estimate
# outside WAIST_SCALE_RANGE is not applied (the ghost is gated as rendered,
# the file stays as rendered) — the product shots it exists for measured
# 0.57..0.80 (Rosi's skirt 0.671 / 0.798, Glut's apron 0.569 / 0.801, the
# trousers block above 0.628 / 0.669).
WAIST_BAND = (0.01, 0.04)   # rows below the garment top whose median span is the waistband width, × Hb
WAIST_ITERATIONS = 4
WAIST_PART_MIN = 0.1        # a part of the region below this share of its largest part is no garment
WAIST_SCALE_RANGE = (1.0 / 3.0, 3.0)   # a waistband scale outside this is a failed measurement
#: Slots whose piece has a waistband as its top edge — unless it also has an upper-body slot.
WAIST_SLOTS = frozenset({"bottom", "underwear_bottom", "legs"})
UPPER_SLOTS = frozenset({"top", "underwear_top", "outer", "neck", "head"})


def waistband_piece(slots: Iterable[str]) -> bool:
    """Whether a piece with ``slots`` is registered by its waistband: a
    bottom slot (``WAIST_SLOTS``) and no upper-body one (``UPPER_SLOTS``)."""
    found = {str(s) for s in slots or ()}
    return bool(found & WAIST_SLOTS) and not found & UPPER_SLOTS


def _waist(mask: np.ndarray, top: int, body_h: int, scale: float) -> Optional[Tuple[float, float]]:
    """``(median span, median centre column)`` of the mask's rows
    ``top + WAIST_BAND·Hb / scale``; None when no row there has a pixel."""
    lo, hi = (int(round(top + t * body_h / scale)) for t in WAIST_BAND)
    widths, centres = [], []
    for row in range(max(lo, 0), min(hi, mask.shape[0] - 1) + 1):
        xs = np.nonzero(mask[row])[0]
        if len(xs):
            widths.append(xs.max() - xs.min() + 1)
            centres.append((xs.min() + xs.max()) / 2.0)
    if not widths:
        return None
    return float(np.median(widths)), float(np.median(centres))


def register_waistband(reference_mask, ghost_mask, *, body_h: int) -> Optional[Dict[str, Any]]:
    """The uniform scale + shift that lays a waistband piece's ghost onto
    ``reference_mask`` (the worn view's garment region; see the block above),
    in ``register``'s form for ``warp``: ``centre`` = the ghost's top row and
    waistband centre, ``shift_px`` = the region's minus the ghost's, ``scale``
    = region waistband / ghost waistband; plus ``method`` "waistband",
    ``waist_px`` [region, ghost], ``length_ratio`` (scaled ghost height /
    region height), ``within_caps`` = the scale lies in ``WAIST_SCALE_RANGE``
    (no cap on the shift; outside the range the estimate is a failed
    measurement and is not applied), ``negligible`` as in ``register``. The
    region is measured without its small parts (``WAIST_PART_MIN``, a
    re-shaded patch above the waistband). None when either mask is empty or
    has no waistband row."""
    ref = _main_parts(np.asarray(reference_mask, dtype=bool))
    ghost = np.asarray(ghost_mask, dtype=bool)
    if ref.shape != ghost.shape:
        raise ValueError("reference and ghost masks differ in size")
    a, b = _bbox(ref), _bbox(ghost)
    if a is None or b is None or body_h <= 0:
        return None
    ref_waist = _waist(ref, a[1], body_h, 1.0)
    if ref_waist is None:
        return None
    scale = (a[2] - a[0] + 1) / (b[2] - b[0] + 1)
    ghost_waist = None
    for _ in range(WAIST_ITERATIONS):
        ghost_waist = _waist(ghost, b[1], body_h, scale)
        if ghost_waist is None:
            return None
        scale = ref_waist[0] / ghost_waist[0]
    dy, dx = float(a[1] - b[1]), ref_waist[1] - ghost_waist[1]
    reach = max(abs(b[0] - ghost_waist[1]), abs(b[2] - ghost_waist[1]), b[3] - b[1])
    moved_px = float(np.hypot(dx, dy)) + abs(scale - 1.0) * float(reach) * np.sqrt(2.0)
    return {"method": "waistband", "centre": [float(b[1]), round(ghost_waist[1], 3)],
            "shift_px": [round(dy, 3), round(dx, 3)], "scale": round(scale, 5),
            "shift": [_r(dx / body_h, 5), _r(dy / body_h, 5)], "shift_abs": _r(np.hypot(dx, dy) / body_h, 5),
            "waist_px": [round(ref_waist[0], 1), round(ghost_waist[0], 1)],
            "length_ratio": _r((b[3] - b[1] + 1) * scale / (a[3] - a[1] + 1), 4),
            "within_caps": bool(WAIST_SCALE_RANGE[0] <= scale <= WAIST_SCALE_RANGE[1]),
            "negligible": bool(moved_px < REG_NEGLIGIBLE_PX)}


def _main_parts(mask: np.ndarray) -> np.ndarray:
    """``mask`` without its connected parts smaller than ``WAIST_PART_MIN``
    of the largest one."""
    from scipy import ndimage
    labels, count = ndimage.label(mask)
    if count <= 1:
        return mask
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = np.nonzero(sizes >= WAIST_PART_MIN * sizes.max())[0]
    return np.isin(labels, keep)


def gate_summary(records: Sequence[Dict[str, Any]]) -> str:
    """One line for a refusal: every attempt's reasons."""
    parts = []
    for n, record in enumerate(records, 1):
        parts.append(f"attempt {record.get('attempt', n)}: " + ("; ".join(record.get("reasons") or []) or "ok"))
    return " | ".join(parts)


def limits(kind: str = "clothing") -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The image-gate limits per step of a garment ``kind`` (only
    ``clothing`` has an image chain), for the gate chips — read from the constants above so the
    UI never keeps its own copy. ``op``: ``lt`` / ``le`` / ``ge`` (value must
    stay below / at most / at least), ``abs_le`` (|value| at most), ``range``
    (``value`` = [min, max]); clothing records are fractions of the figure
    height; ``views``: the views the limit is gated
    on (all when absent); ``warn`` True: a value beyond the limit is a
    warning, the gate never refuses for it; ``generated_only`` True: the
    number exists for a generated image only and never applies to one made
    from the worn view (Ruling A46c). ValueError for another kind."""
    if kind == "clothing":
        return {
            "worn": {
                "garment_share": {"op": "ge", "value": GARMENT_MIN},
                # ``outside_dRGB`` has no limit (gate version 2): its chip is information only.
                # The limit of a record is its own ``outside_xor_limit``
                # (``record_key``; the area limit grown by the drift limit
                # over the exposed outline). A record without it (before
                # 2026-11-10) falls back to ``value``; a back fitted before
                # Task 11g had a looser limit and its reasons name the refusal.
                "outside_xor": {"op": "lt", "value": OUTSIDE_XOR_MAX, "record_key": "outside_xor_limit",
                                "views": ["front"]},
                # Not gated for a piece worn on one of ``free_slots`` (SLOT_ZONES).
                "head_garment": {"op": "le", "value": HEAD_GARMENT_MAX,
                                 "free_slots": sorted(s for s, z in SLOT_ZONES.items() if "head" in z)},
            },
            "ghost": {
                # ``top_dy`` / ``centre_dx`` have no limit (ghost gate version 2):
                # recorded only, their chips are information (``warnings``).
                "w_ratio": {"op": "range", "value": [CLOTH_W_RATIO_MIN, CLOTH_W_RATIO_MAX]},
                "skin_left": {"op": "le", "value": SKIN_LEFT_MAX},
                "outside": {"op": "le", "value": CLOTH_OUTSIDE_MAX},
                "added_reach": {"op": "le", "value": ADDED_REACH_MAX},
                **_registration_limits(),
            },
        }
    raise ValueError(f"no image gates for garment kind {kind!r}")


def _registration_limits() -> Dict[str, Dict[str, Any]]:
    """The caps of the ghost registration as chips (record keys ``reg_shift``
    / ``reg_scale``, set by the chain): beyond them nothing was corrected.
    Ruling A46c: they are no refusal — ``ghost_clothing_gate`` never reads
    them; beyond a cap ``garment_images._register`` leaves the attempt as
    rendered and the gate measures that image — so a value outside is a
    ``warn``ing. They are ``generated_only``: a view made from the worn view
    is in the worn view's frame by construction and never registered."""
    return {"reg_shift": {"op": "le", "value": REG_SHIFT_MAX, "warn": True, "generated_only": True},
            "reg_scale": {"op": "range", "value": [REG_SCALE_MIN, REG_SCALE_MAX], "warn": True,
                          "generated_only": True}}
