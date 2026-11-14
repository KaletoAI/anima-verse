"""Garment fit math: place a generated garment mesh on the unrigged base body, push it out of the body, carry it
into the rigged bind space and weight it — pure numpy/scipy on arrays (plan 2026-11-09 phase 4, R1).

A port of the hair spike (``fit_hair.py`` run as ``GARMENT_KIND=hairframe HAIR_SPREAD=0.005
HAIR_SPREAD_DEPTH=0.07``, ``hair_metrics.py``, ``poke.py``). Facts the code relies on:

- The generator body (UniForge) is DOUBLE-WALLED: winding and normals are about 50:50 and never trusted. The body
  is voxelised, its walls closed into one solid by a hole fill, and the push follows the gradient of the signed
  distance of that solid.
- A generated garment has UV-seam duplicates: all geometry work runs on welded positions (``weld``); results are
  scattered back through ``inv``.
- The unrigged base (the generator's mesh) and the rigged base share the UV atlas: a body vertex is found in the
  rigged mesh by its UV, and a garment vertex follows a local similarity (Kabsch with scale) of the body around it.

Units: the unrigged base has its own units (height ~1.0); the rigged base is in metres. Every constant is declared
in METRES (R9) and converted by ``k = rigged / unrigged``, measured by a similarity over the garment's
carrier region (for hair: the Head-weighted vertices, the rigid part between an A-pose source and a T-pose rig).

Clothing (an own-mesh outfit piece, plan ``2026-11-09-base-body-phase5-mesh-items.md`` Task 3) is a port of the dress
spike ``fit_dress.py`` (``fit_clothing``): the same framing; depth by a torso band; the push-out without the crown
spread; a transfer that lets sleeves ride the arms (only forearm/hand excluded above the waist, every arm/shoulder
bone below it); weights by inverse distance from the 8 nearest rigged body vertices, restricted to the rig contract,
and a skirt whose leg weights are smoothed across the gap between the legs and blended partly toward Hips down to the
hem. Its placement constants are FRACTIONS OF THE BODY HEIGHT (the spike worked in units of a 1.0-high body =
1.70 m, so at that height they are the spike's numbers); ``k`` is the height ratio rigged / unrigged (the whole body
is the carrier; A- and T-pose share the height).

The clothing transfer is SKINNED (``transfer_skinned``, 2026-11-09 sleeve fix): the rigged body IS the unrigged body
posed by linear blend skinning (measured on the e2e base: per-bone rigid fits residual p50 0.6 mm, the whole body as
LBS p99 9 mm, dual quaternions worse), so the garment is carried by the same motion — one rigid transform per bone
recovered from the body correspondence, blended with the skin weights of the body under each garment vertex. The
nearest-donor local-Kabsch transfer (removed with the hair edit chain) tore a sleeve around the 70-degree A -> T
rotation of the upper arm (adjacent vertices with different donors landed centimetres apart: sleeve area x1.9) and
its 25 smoothing passes folded the tear into the puffed shoulder cap (15 % of the sleeve triangles flipped).

Hair: the edit chain's hair fit (``fit_hair``, its gates and metrics) went with that chain (hair-from-body,
2026-11-11); HairDeck (``garment_hairdeck``) uses the push-out, the SDF and ``hair_weights`` from here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.core import fit_kernels
from app.core.footwear_fit import FOOTWEAR_FIT_VERSION
from app.core.garment_mesh import MIN_COMPONENT_SHARE as MESH_MIN_COMPONENT_SHARE
from app.core.glb_mesh import BodyMesh, GarmentMesh, static_mr_image

# R9 — fit constants in METRES (the spike's unit constants x 1.70)
# Clearance from the REAL body surface. The spike asked for 0.004 units (0.0068 m), but its raw voxel field put the
# zero level ~1.8 voxels outside the surface, and with the field's two-voxel jump in the boundary cell its pushes
# landed 1.5 voxels further out than asked (measured on spheres of 30..75 voxels radius: 3.48..3.52 voxels for a
# 2-voxel request). Its visually verified look therefore had 0.0068 + 1.5 * 0.0034 = 0.0119 m of real clearance.
# ``body_sdf`` measures from the real surface, so the default asks for that distance directly (controller ruling
# 2026-11-09: the default reproduces the spike's look).
CLEAR_M = 0.0119
VOX_M = 0.0034
SPREAD_M = 0.0085
# The hair clearance (6 mm, less than CLEAR_M: hair rides the rigid Head; measured on the former edit-chain hair fit,
# Kai 2026-11-10, scalp -> hair p50 15-17 mm at 11.9 mm, 10-11 mm at 6 mm) — the collision capsules' ``chest_hair``
# margin (``collision.HAIR_CLEARANCE_M`` pins the equality).
HAIR_CLEAR_M = 0.006
SPREAD_DEPTH_M = 0.119
# Hair weights (``hair_weights``): the ear line lies this fraction of the head height (chin -> crown) above the chin
# — the earlobe / jaw angle (measured on Kira's base: 1.513 m; its Head joint 1.515 m, nose tip 1.503 m).
HAIR_EAR_LINE_FRACTION = 0.25
POKE_TOL_M = 0.0034
SDF_MARGIN_M = 0.05
# Raw zero level of the voxel SDF outside the true surface, in voxels (see ``body_sdf``).
SDF_ZERO_OFFSET_VOX = 1.3
# Outside the body, voxels up to this many voxels away carry the exact distance to the surface triangles.
SDF_EXACT_BAND_VOX = 6.0
# A cavity of the body solid that the hole fill leaves open (``body_sdf``): kept as inside when it is enclosed along
# all six axis directions and at least 2 x this many voxels + 1 thick (10 at 3.4 mm: 7 cm — a trunk, not the
# pocket between baked hair and the nape, 3 - 6 cm, nor an armpit or a gap between the legs).
SDF_SEAL_THICK_VOX = 10
# A vertex counts as moved by the push-out above this displacement (spike 1e-4 units x 1.70).
MOVED_EPS_M = 0.00017
# Loose components below this share of the garment area are dropped in the weld step (R8).
MIN_COMPONENT_SHARE = 0.002
# Spike push-out loop: 8 iterations, the displacement smoothed (6 passes) and spread over the crown in the first 6.
PUSH_ITERATIONS = 8
PUSH_SMOOTH_UNTIL = 6
PUSH_SPREAD_UNTIL = 6
PUSH_SPREAD_K = 48
SMOOTH_PASSES = 6
RIGGED_ITERATIONS = 10
RIGGED_SMOOTH_UNTIL = 7
#: The clothing pushes keep every vertex on its side of the body (``push_kept``): a smoothed displacement may carry
#: a vertex at most its own start depth + the clearance + this far (metres) before it keeps its own push (the plain
#: loop carries Kai's jacket / jeans and Kira's blazer at most 25 mm beyond depth + clearance).
SIDE_MARGIN_M = 0.03
#: Samples along a smoothed displacement checked for a crossing of the body (``push_kept``).
SIDE_PATH_SAMPLES = 12
#: A vertex the transfer put inside the rigged body leaves by the side it had before (``_transfer_sides``) when that
#: side is more than acos(SIDE_COS) = 60 deg from the field's gradient: it is projected onto the nearest body surface
#: whose outward normal lies within acos(SIDE_COS) of that side (``_side_projection``).
SIDE_COS = 0.5
#: Gradient steps that settle a side projection's landing point at the clearance (``_side_projection``).
SIDE_SETTLE_ITERATIONS = 8
#: ... and only when it lies deeper than this (metres): the transfer left it in the body's interior.
SIDE_DEEP_M = 0.03

#: Fit algorithm version per garment kind, written into every fit record (``fit_version``, ``garments._publish_fit``).
#: A record with an older or missing version is stale (``garments._fit_state``): the chain re-runs the FIT only — CPU,
#: no hub job; images and mesh stay cached under the unchanged fsig. Bump a kind whenever its fit output changes.
#: 2 (2026-11-10): clothing — skinned transfer (sleeves, 3b4b0abf) and the smoothed skirt leg weights; hair — the
#: Head -> Neck -> Spine2 ramp between the ear line and the shoulder top.
#: 3 (2026-11-10): clothing — long sleeves below the waist ride the arm (``sleeve_vertices``); the deep push share
#: replaces the moved share in the gate.
#: 4 (2026-11-10): clothing — the garment over extension-bone tissue takes the extension share of its weights
#: (``EXTENSION_FULL_M``), so it moves with the chest instead of letting the chest jiggle through it.
#: 5 (2026-11-10): clothing — a fit on an outfit body (and a refit from another base) aligns its sleeves / trouser
#: legs onto the body's own limbs (``align_limbs``); a native base fit is unchanged.
#: 6 (2026-11-10): clothing — a fit on an outfit body places its trunk from the base fit too (``map_torso``) and
#: smooths the alignment's displacement over the mesh; v5 outfit-body fits could be torn open at the front.
#: 7 (2026-11-10): clothing — the body solid is sealed (``_seal_cavities``: a hollow outfit body let the piece sink
#: into its cavity, the skin showed through) and a fit placed from the base fit is not gated on the image placement.
#: hair 3 (2026-11-10): the hair's clearance is ``HAIR_CLEAR_M`` (6 mm, was CLEAR_M 11.9) in the push AND the rigged
#: pass (the edit chain's hair floated 15-17 mm off the scalp).
#: hair 4 (2026-11-11): HairDeck cards on the head pushed layer-keeping (``garment_hairdeck.layer_push``).
#: hair 5 (2026-11-11): HairDeck side strands moved out of the face (``garment_hairdeck._clear_face``).
#: hair 6 (2026-11-11): the HairDeck scalp cap takes the hair's median colour (was the 20th percentile).
#: hair 7 (2026-11-11): the HairDeck smoothed push runs without the crown spread (``garment_hairdeck._push``): its
#: flood entered the layer-push blend band as a ring round the head at eye level (Rosi, 32.5 mm p50 at 1.55 m).
#: hair 8 (2026-11-12): the HairDeck back curtain is draped behind the nape before the push
#: (``garment_hairdeck.drape_back``): pushed to its nearest surface it wrapped round the neck as a collar (Rosi).
#: hair 9 (2026-11-12): HairDeck spring chains — the cards bound to HairDeck's own chains (``hair_chains``), the chain
#: joints ``HairGen_c<CC>_<KK>`` / ``_end`` emitted with bind frames and appended to the skin by ``glb_mesh.graft``
#: (fit and both assembly tiers); the cards' rest positions are unchanged. Re-fits every HairDeck hair from its
#: stored seeds on the CPU refit pool; no hub job.
#: hair 10 (2026-11-12, Ruling H11): Swing is a fit input (profile ``hair_swing``, ``hair_motion.swing_on``, default
#: OFF). With Swing off the fit is today's hair again — ``hair_weights``' skin byte for byte, no chain joint — so the
#: refit of every hair 9 fit (made with the chains bound: 1.2-4.5 % penetration against today's 0.01-0.21 %) lands
#: it back in today's state; with Swing on each chain records its ``anchor_blend``. Refit on the CPU pool; no hub job.
#: 8 / hair 11 (2026-11-12, plan fit-sdf-speed-drape phase A — ONE CPU refit of every stored fit, no hub job):
#: the body field is the filled solid (Task 1: a double wall is closed by the three-axis slice fill, the clothing
#: push keeps each vertex on its side, ``push_kept``), computed by the same numbers faster (Task 2: label fill,
#: numba band, threaded KD queries), cached per body on a body-anchored lattice (Task 5, ``body_field``: the grid no
#: longer moves with the garment's bounds) — and clothing gates the rigged clearance pass (Task 7:
#: ``rigged_deep_push_share``, the existing 0.12 on the push that really happens; Ruling R7a). A fit the correct
#: field now refuses keeps serving its old fit, the refusal recorded with its numbers and not retried at every start
#: (Rulings D4 / R7c).
#: clothing 9 (2026-11-13, plan fit-sdf-speed-drape Task 7 fix 1, Ruling A8c — one more CPU refit, no hub job): a
#: vertex the transfer buried on the wrong side is PROJECTED onto the nearest body surface of its own side
#: (``_side_projection``: inside the field's crop, settled at the clearance along the gradient), no longer walked up to
#: 30 cm along a fixed direction (the walk left Kai's jacket with shards over the right hip and the back; against the
#: fit before phase A 346 vertices moved more than 10 cm on the base body, 388 on the outfit body — 77 / 103 now, every
#: one of them settled on the body). A vertex without such a surface inside the crop keeps where the transfer put it
#: and is counted (``side_unreached``).
#: hair 12 (2026-11-13, plan fit-sdf-speed-drape Task 11, acceptance B — one CPU refit of every HairDeck fit, no hub
#: job): the hair below the ear line is draped (``garment_hairdeck.drape_below_ear``, XPBD, ``HAIR_DRAPE_ON``):
#: flare over the shoulders Rosi 7.11 -> 0.76 %, Kira 11.78 -> 1.44 %, no face-box vertex, the head untouched.
#: Known limitation (accepted): a raised arm crossing the draped FRONT strands squeezes them into the chest — the
#: upper-arm capsule pushes them onto its own surface, which lies inside the chest (Kira celebrating excess with the
#: served capsules 0.21 -> 0.85 %, depth p50 12 mm); the cross-person spec's squeeze rule (Ruling B11j) fixes it.
#: hair 13 (2026-11-13, strand-hair plan Task 2 — one CPU refit of every HairDeck fit, no hub job): the cards carry
#: the strip atlas of ``hair_cards`` as base colour (UVs mapped into the card's variant column, the cap on the opaque
#: patch) and are grafted as glTF MASK with the world cutoff ``base_body.hair_alpha_cutoff``.
#: hair 14 (2026-11-14, user test T-U1/T-U2 — one CPU refit of every HairDeck fit, no hub job): a card's strip is
#: drawn at the card's own width per row (``hair_cards.width_uvs``; the whole strip used to be squeezed into the
#: tapering tip, 0.08 of the card's width in its last 5 %, and alpha-tested into stray threads); the overlapping 8th
#: atlas column is left out; a card the drape tears is draped once more from the fit (``DRAPE_TEAR_STRETCH``; Kira 5
#: cards, segments drawn out 10-15x across the shoulder); open scalp gets flat fill cards over a shaded cap
#: (``scalp_fill_cards``; Ylva's forehead band 50 -> 77 % hair); without a manual width the width is automatic
#: (``auto_width_scale``; Ylva's reach beyond the head at the ears 32.1 -> 23.8 mm placed). Ruling T-U2b (same
#: version, no hair 14 fit was live yet): the cap is cut along a level line CAP_TUCK_M above the hairline instead of
#: keeping whole triangles (Ylva's front edge: 5 teeth up to 10.6 mm -> 0), the fill cards run 3 mm past it, fill the
#: band along it and lie 3 mm apart (forehead window hair 77 -> 90 %, cap 21 -> 7 %).
#: clothing 10 (2026-11-14, Ruling A35 — one CPU refit of every clothing fit, no hub job): the limb and trunk frames
#: of a refit / outfit-body transfer come from the skeleton's bind joints (``FRAME_BASIS``; Kai's jeans on
#: ``obf6474c3b``: off the left thigh 0.1478 -> 0.0002), the sleeves are re-centred on their arms
#: (``center_sleeves``) and their cuffs ride the arm (``sleeve_cuffs``; Kira's blazer: the forearm halves no longer
#: stay at the hips), the garment's inside seen through an opening is left out (``opening_lining``; the blazer's V
#: stays open), a native fit's sleeves are gated (``garment_source.check_sleeves``).
#: clothing 11 (2026-11-14, Ruling A47 — one CPU refit of every clothing fit, no hub job): per piece and side the
#: sleeves are placed by the piece's fit settings (``place_sleeves``; Auto lays a sleeve that sits off its arm or
#: inside it onto the arm at 12 mm clearance — Kai's jacket on ``base634402e5``: skin seen in the sleeves 93 / 115 ->
#: 2 / 1 cm2), the stretched strips of the placement are gated (``sleeve_shards``), an accepted fit that lies tight
#: may widen by the width allowance (``scale_retry``, never beyond 1.08), the fit records its arm light
#: (``arm_light``) and its settings (``inputs.fit_settings``, ``garment_fit_settings``).
#: clothing 12 (2026-11-14, Ruling A50 — one CPU refit of every clothing fit, no hub job; only fits on body shapes
#: and refits from another base change): ``map_torso`` bridges a hollow of the source body down to
#: ``TORSO_BRIDGE_M`` where the target grew, instead of carrying the piece out with the growth (Kai's open jacket
#: on ``obf6474c3b``: trunk front 0.75 / source 0.85, largest hole 35 cm2 -> 0.82 / 0.85, 2.5 cm2 — accepted).
#: clothing 13 (2026-11-14, Ruling A51 — a CPU refit of the clothing fits it can change, no hub job): an opening
#: the worn view shows as body counts however flush the mesh fills it (``opening_lining``, ``OPEN_SHOWN_SHARE``;
#: Kira's blazer on the remeshed ``8a64a2576446``: 0 -> 3591 faces left out, the V 0.5 / 0.1 / 0.9 -> 13.7 / 10.5 /
#: 7.3 cm wide at 0.17 / 0.21 / 0.25). Only a fit whose opening report kept a component at least
#: ``OPEN_SHOWN_RECESS_PX`` deep could change: a version 12 clothing fit without one stayed current until 14.
#: clothing 14 (2026-11-14, Ruling A72 — one CPU refit of every clothing fit, no hub job): a body vertex whose UV
#: match lies elsewhere on the rigged body donates the skin of its nearest matched neighbour
#: (``trusted_donor_weights``; Kira's ``base20d5701a``: 490 such vertices, 54 at the navel matched onto the right
#: arm — the waistband of her black slit skirt rode the arm as a "sleeve" and stood 37 cm out to the right, 118
#: vertices, edges up to 23 cm -> no sleeve, longest edge 4.8 cm, as placed), and the fit is gated on its longest
#: new edge (``new_edge_max_m``, ``NEW_EDGE_MAX_M``). Every clothing fit is refitted: the repaired donors change the
#: weights wherever such a vertex is among a garment vertex's nearest, so Ruling A51's exemption of version 12 fits
#: without a deep opening went with this version.
#: footwear: its own fit (``footwear_fit``), versioned there.
FIT_VERSION: Dict[str, int] = {"hair": 14, "clothing": 14, "footwear": FOOTWEAR_FIT_VERSION}


def fit_version_for(kind: str, method: str = "") -> Optional[int]:
    """The current fit version of a ``kind`` fit made with ``method``: HAAR hair has its own
    (``garment_haar.HAAR_FIT_VERSION``), every other fit ``FIT_VERSION[kind]``; None for an unknown kind."""
    if kind == "hair" and method == "haar":
        from app.core.garment_haar import HAAR_FIT_VERSION
        return HAAR_FIT_VERSION
    return FIT_VERSION.get(kind)


def expected_fit_version(record: Dict[str, Any]) -> Optional[int]:
    """``fit_version_for`` of a fit record (its ``kind`` and ``method``) — what its ``fit_version`` must say to be
    current."""
    return fit_version_for(str(record.get("kind") or ""), str(record.get("method") or ""))


# Clothing (phase 5) — the dress spike ``fit_dress.py``. Placement: fractions of the unrigged body height.
#: Depth band of the garment below its top (spike 0.03 .. 0.15 units on a 1.0-high body).
CLOTHING_DEPTH_BAND = (0.03, 0.15)
#: Half width of the body band the garment band is centred on (spike |x| < 0.12 units).
CLOTHING_BODY_HALF_X = 0.12
#: The waist of the transfer rule: garment top minus this (spike 0.20 units).
CLOTHING_WAIST_DROP = 0.20
# Weights, rigged metres: inverse distance over the 8 nearest rigged body vertices, w = 1 / max(d, 1e-4).
CLOTHING_IDW_K = 8
CLOTHING_IDW_EPS_M = 1e-4
#: A body vertex donates weights to a garment vertex whose neighbours carry only extension bones when at least this
#: share of its weight sits on rig-contract bones.
CONTRACT_DONOR_MIN = 0.5
# Extension bones (a pack's secondary-motion chains, e.g. the chest pair) carry the garment over their tissue: a
# garment vertex takes the EXTENSION SHARE of the inverse-distance blend of its 8 nearest body vertices' full weights
# — all of it up to ``EXTENSION_FULL_M`` from the nearest body vertex, falling linearly to none at
# ``EXTENSION_ZERO_M`` (fabric bridging away from the tissue stays on the torso) — and the contract blend fills the
# rest. Towards the torso the body's own weight gradient is the falloff. Measured 2026-11-10 on Kira's Black Blazer
# (fit 2966, base20d5701a; 8123 garment vertices with an extension share > 0.05): distance to the nearest body vertex
# 10-15 mm 7258 (mean share 0.76), 15-20 mm 702 (0.46), 20-30 mm 144 (0.46), 30-40 mm 19 (0.20), none beyond 40 mm
# — twice the clearance (``CLEAR_M``) keeps every fitted layer whole. Contract-only weights left the chest jiggling
# under a static blazer: run clip with the secondary motion, 21 % of the covered chest skin in front of the fabric on
# average, 44 % at the worst sample (``scripts/check_garment_collision.mjs --motion``); the capsule push changed none.
EXTENSION_FULL_M = 0.025
EXTENSION_ZERO_M = 0.05
# Skinned transfer (clothing): a bone gets its own rigid transform from its RIGID CORE — the body vertices carrying
# at least ``BONE_CORE_WEIGHT`` of their weight on it — when that core has ``BONE_CORE_MIN`` vertices (measured on
# the e2e base: every core fits to < 1 mm median, the upper arm's deltoid to 13.6 mm at p99); a blend-only bone (Spine,
# Spine1, the Shoulders, Neck, Thumb1 on the mixamo rig) folds into the bone its vertices co-weight most. Core
# vertices farther than ``BONE_CORE_OUTLIER_M`` from their first fit are UV-twin mismatches and are dropped for a
# second fit. The garment's transfer weights are inverse-distance blends of the body weights of the
# ``TRANSFER_IDW_K`` nearest eligible body vertices.
BONE_CORE_WEIGHT = 0.8
BONE_CORE_MIN = 20
BONE_CORE_OUTLIER_M = 0.05
TRANSFER_IDW_K = 8
# Donor PARTS of the skinned transfer: each arm chain (folded weight on Arm/ForeArm/Hand of one side > this) against
# the rest of the body. A garment vertex takes the weights of the part whose skin is NEAREST to it, blended by inverse
# distance within that part only. In the A-pose the sleeve's underside hangs 1-3 cm from BOTH the inner arm and the
# torso side; an inverse-distance blend over the 8 nearest body vertices of all parts there is a noisy mix of the two
# (adjacent sleeve vertices with arm weight 0 and 1, 3 mm apart on a double-walled garment) and the 70-degree A -> T
# motion tears such neighbours apart. Measured on the e2e dress (sleeve edges whose two faces fold against each
# other, left/right): mixed blend 86/153 flipped triangles; nearest part 16/13 fold edges; a distance RAMP between
# the parts instead (2.5 / 5 / 10 / 20 / 40 mm wide) 27/19, 31/17, 49/21, 65/36, 97/108 — intermediate weights
# across a 70-degree joint collapse toward the pivot and the sleeve underside fans out (dual quaternions did not
# help: 42/25 at 5 mm, 275/282 at 40 mm). So: the nearest part, no ramp.
TRANSFER_PART_ARM_MIN = 0.5
# Web relaxation: triangles stretched beyond this area ratio by the transfer (the fabric that bridged the closed armpit
# of the A-pose and spans the open one in T-pose) have their vertices Laplacian-relaxed for this many passes, the
# rest of the garment fixed, so the stretch spreads over the band instead of alternating slits and folds (renders
# 2026-11-09: 0 passes leaves a sharp pleat under each sleeve, 10 and 25 look alike).
STRETCH_RELAX_RATIO = 3.0
STRETCH_RELAX_PASSES = 10
# Skirt: below crotch + ``SKIRT_ZONE_M`` the leg weights of a garment vertex are the Gaussian average (sigma =
# ``SKIRT_SMOOTH_M`` / 2, neighbours within ``SKIRT_SMOOTH_M``) of the leg weights of the zone's vertices, so the
# switch from the left to the right leg spreads over the gap between the legs instead of the few centimetres the
# inverse-distance donors give; then the vertex keeps ``SKIRT_KEEP_TOP`` of them at the crotch, falling linearly to
# ``SKIRT_KEEP_HEM`` at the hem, and the rest goes to Hips. Crotch = the lowest rigged vertex within
# ``CROTCH_HALF_X_M`` of the centre line with Hips weight > ``CROTCH_HIPS_MIN``.
# Measured 2026-11-10 on the phase-5 e2e dress on Kira's base (dense checker with the capsule push, 8 samples; skirt
# triangles stretched > 2x by the pose / thigh skin left visible beside the skirt, mean of five views): the old blend
# (0.5 -> 0, no smoothing) walk 0.85 % / 3.0 %, run 1.07 % / 25.9 %, sit 0.63 % / 73.9 % (the thighs came out in
# front of a skirt hanging from the hips); more leg weight without smoothing tore the skirt between the legs (1 -> 0.5:
# walk 2.1 %, run 2.6 %, sit 3.1 %, centre line up to 15 %); 1 -> 0.75 smoothed over 0.16 m: 0.00 % / 2.0 %,
# 0.00 % / 3.6 %, 0.00 % / 10.2 %. Smoothing radius 0.12 m left 0.9 % of the triangles > 1.5x, 0.16 m 0.16-0.31 %.
SKIRT_ZONE_M = 0.05
SKIRT_KEEP_TOP = 1.0
SKIRT_KEEP_HEM = 0.75
SKIRT_SMOOTH_M = 0.16
CROTCH_HALF_X_M = 0.03
CROTCH_HIPS_MIN = 0.3
#: Slots whose piece may hang over the legs as a skirt (a dress is top + bottom).
SKIRT_SLOTS = frozenset({"bottom", "legs"})
#: ``is_skirt``: the cut through the garment between these heights below the crotch, garment vertices within
#: ``SKIRT_CENTRE_M`` of the centre line.
SKIRT_PROBE_M = (0.01, 0.10)
SKIRT_CENTRE_M = 0.02

# Mesh gates of a fitted clothing piece. Measured 2026-11-09 on the spike dress (UniForge ghost-s52 mesh, decimated
# to 59721 triangles, on the spike bases kira_bald_dis_apose / s1ap_ext) through ``fit_clothing``: max push 0.0501 m
# (spike script: 0.0293 units x 1.70 = 0.0498 m), moved share 0.929 (spike 38720 / 44950 = 0.861 — the product asks
# its clearance from the real surface, see ``CLEAR_M``), largest component 0.9888 after ``drop_small``, rigged inside
# share 0.0 (spike 0.0). Limits: twice the measured push; the moved share refuses only a piece pushed nearly
# everywhere (a loose dress moves 0.93, a tight piece legitimately more); the largest component as the mesh step
# gates it (``garment_mesh.MIN_COMPONENT_SHARE``, 0.90 since 2026-11-12 — was 0.98 "one component as for hair": the
# kept seam strips beside the body are fitted per vertex like the rest, only a torn or split piece is refused); at
# most 1 % of the vertices left inside the rigged body.
#
# ``moved_share`` is REPORTED, no longer gated (2026-11-10, Kira's Black Blazer refused at 0.991): it counts every
# vertex the push moved by more than 0.17 mm, and the displacement smoothing carries any push to the whole piece, so a
# close-fitting piece scores ~1 when it is placed right and LESS when it is misplaced (one side then floats free).
# Measured through the unrigged push-out (blazer on Kira's base20d5701a; e2e dress on the base of that run; spike
# dress on the spike bases) — moved_share / share of vertices pushed more than 3 cm / max push:
#   blazer 2966 (correct)        0.991 / 0.031 / 42 mm      blazer 2966 scaled 0.95   0.990 / 0.146 / 46 mm
#   blazer 8ee7 (correct)        0.972 / 0.073 / 50 mm      blazer 2966 scaled 0.90   0.985 / 0.323 / 56 mm
#   e2e dress (correct)          0.743 / 0.041 / 54 mm      blazer 2966 scaled 0.85   0.977 / 0.431 / 68 mm
#   spike dress (correct)        0.926 / 0.079 / 50 mm      blazer 2966 depth +3 cm   0.816 / 0.203 / 80 mm
#                                                           blazer 2966 depth -3 cm   0.833 / 0.329 / 72 mm
# The DEEP push share (``DEEP_PUSH_M`` = 3 cm, 2.5 x ``CLEAR_M``) separates them: correct <= 0.079, misplaced >= 0.146
# — the limit 0.12 lies between; the max push gate passes every one of the misplaced pieces.
#
# The rigged clearance pass (``transfer_skinned`` step 4) is gated by its DEEP push share with the same limit
# (2026-11-12, plan fit-sdf-speed-drape Task 7, Ruling R7a): ``rigged_deep_push_share`` measures the push that
# really happens on the body the piece is worn on. A leaky field read a double wall's core as outside and pushed
# nothing there; the filled field pushes such a piece out by its whole depth, and the gate refuses it instead of
# passing a piece that stood inside the body. ``rigged_push_max_m`` / ``rigged_push_p95_m`` are REPORTED, not gated:
# as on the unrigged push, the max passes every misplaced piece and refuses real ones — Kai's jacket carries the
# side panel the transfer buried in the chest out by its own side (``_transfer_sides``, ``_side_projection``).
# Measured that day on the phase-A evidence (accept.py, ``~/claude-out/fit-sdf-speed-drape/accept/t7``) — rigged
# push max / p95 / deep share: Kai's jacket base 0.3026 m / 0.0317 / 0.0525 (437 vertices side-marched then, the
# walk Task 7 fix 1 replaced), jacket obf 0.0432 / 0.0114 / 0.0013, jeans base 0.0483 / 0.0007 / 0.0019, jeans obf
# 0.0411 / 0.022 / 0.0147, Kira's blazer 0.0199 / 0.0074 / 0.0. With the side projection (Task 7 fix 1,
# ``accept/A8c``): jacket base 0.1601 / 0.0296 / 0.0493 (437 projected, 0 unreached), jacket obf 0.0352 / 0.0118 /
# 0.0009; the others unchanged.
DEEP_PUSH_M = 0.03
#: Ruling A47 — a SHARD: a triangle of the region the sleeve placement moved whose longest edge is longer than
#: ``SLEEVE_SHARD_M`` and more than ``SLEEVE_SHARD_RATIO`` times its pre-push length — the stretched strips the spike
#: saw under the armpit (``sleeve_shards``). Kai's jacket ``item_555a7a01`` on ``base634402e5``: the push-out tearing
#: the sleeves as generated leaves 243 such triangles in that region, laid onto the arm 0 - 2.
SLEEVE_SHARD_M = 0.03
SLEEVE_SHARD_RATIO = 3.0
SLEEVE_SHARDS_MAX = 6
#: Ruling A72 — the longest NEW edge (``new_edge_max``): the largest growth of an edge of the fitted piece over its
#: length in the placed piece (the placement before the push-out, at the fit's width allowance), metres. Nothing in
#: the fit may carry two neighbours that far apart but the pose change from the A-pose generator body to the T-pose
#: rig, and its largest opening is the ARMPIT: the arm turns by theta about the shoulder joint, and the fabric at the
#: armpit fold, r below the joint, that rides the arm leaves the fabric beside it that rides the trunk by
#: 2 r sin(theta / 2). Measured on the three bases (theta between the Arm and Spine2 bone transforms, r from the Arm
#: joint to the nearest trunk vertex below it): Kira ``base20d5701a`` 76.8 deg, 0.114 m -> 0.142 m; Ylva
#: ``base5fe6bd6a`` 75.9 deg, 0.131 m -> 0.161 m; Kai ``base634402e5`` 59.8 deg, 0.168 m -> 0.167 m. The limit is the
#: largest, rounded up: 0.17 m. A vertex that rides a limb from farther than the armpit (Kira's skirt waistband on the
#: right arm, its UV-mismatched navel donors) opens more: 0.209 - 0.224 m on the four widths of that fit. Every other
#: fit re-run that day stays far below: Kira's blazer 0.080 - 0.094 m and Kai's leather jacket 0.082 - 0.094 m (both
#: with the sleeves laid onto the arm), Kai's jeans 0.071 m, Ylva's wrap skirt 0.103 m, the repaired slit skirt
#: 0.015 - 0.021 m.
NEW_EDGE_MAX_M = 0.17

CLOTHING_GATES = {
    "max_push_m": ("max", 0.10, "largest push-out"),
    "deep_push_share": ("max", 0.12, "share of vertices pushed out more than 3 cm"),
    "largest_component_share": ("min", MESH_MIN_COMPONENT_SHARE, "area share of the largest component"),
    "rigged_inside_share": ("max", 0.01, "share of vertices inside the rigged body after the transfer"),
    "rigged_deep_push_share": ("max", 0.12, "share of vertices pushed out more than 3 cm on the rigged body"),
    # Ruling A47: no stretched strip in the sleeves placed onto the arm (``sleeve_shards``; 0 without such a sleeve).
    "sleeve_shards": ("max", SLEEVE_SHARDS_MAX, "stretched strips where the sleeves were placed onto the arm"),
    # Ruling A72: no sliver the placed piece does not have (``new_edge_max``).
    "new_edge_max_m": ("max", NEW_EDGE_MAX_M, "longest edge the fit grew beyond the placed piece"),
}

# Scale retry (2026-11-10): a clothing fit refused ONLY because the piece is too small for the body — every failing
# gate one of ``SCALE_RETRY_KEYS`` — is fitted again with the placed piece widened by the steps of
# ``SCALE_RETRY_STEPS``; the smallest step whose fit passes every gate is taken, the first that fails for any other
# reason does not end the walk (a larger one may still pass). A refusal for another gate is never retried; a fit that
# passes unwidened is the unchanged fit (the factor 1.0, the same arrays as before).
#
# Axes and centre, measured 2026-11-10 on Kira's Black Blazer (fit-reuse spike: prepared mesh, ghost front warped to
# the outfit body 2b6731cd04b4, refused there for deep_push_share 0.133 > 0.12) through the unrigged push-out —
# deep push share / max push / hem height / top height (unrigged frame x k, m):
#   unwidened                     0.133 / 60 mm / 0.0456 / 0.627
#   x, z  1.02 / 1.04 / 1.08      0.118 / 0.104 / 0.085   hem 0.0456 at every step, top 0.628 .. 0.632
#   isotropic about the centroid  0.104 / 0.084 / 0.054   hem 0.040 / 0.033 / 0.021, top 0.638 / 0.632 / 0.644
# The isotropic scale makes the piece LONGER (the hem 2.4 cm lower at 1.08) — a blazer must not grow a hem. Widening
# x and z only keeps the hem and the collar where they were (the top moves by the push-out alone, < 6 mm). Every deep
# vertex of that case lay within the torso (|x| < 0.25 m); beyond the torso's half width (``CLOTHING_BODY_HALF_X`` of
# the body height, the band ``align_band_depth`` centres on) x is SHIFTED by the shoulder's widening instead of
# scaled, so a sleeve keeps its length and moves out with the shoulder seam (same deep shares, 0.118 / 0.104 / 0.085:
# no deep vertex lies there). The centre is the body's vertical axis through the torso band: x = the body's median x,
# z = the middle of the body band's depth (where ``align_band_depth`` put the garment band's middle).
#: Widening factors tried after a too-small refusal, smallest first.
SCALE_RETRY_STEPS: Tuple[float, ...] = (1.02, 1.04, 1.06, 1.08)
#: The clothing gates whose refusal means "too small for the body".
SCALE_RETRY_KEYS: Tuple[str, ...] = ("deep_push_share", "max_push_m")
#: The clothing gates that judge the image-framing placement (the unrigged push-out). Not gated for a piece whose
#: trunk is placed from its base fit (``fit_clothing`` with a torso source): Kira's blazer on the outfit body
#: 3b3a0adaf672 2026-11-10 — framed 6 cm low, pushed out of the sealed body (``_seal_cavities``) by more than 3 cm
#: at 0.19 of its vertices, a placement the torso transfer then replaced entirely.
PLACEMENT_GATE_KEYS: Tuple[str, ...] = ("deep_push_share", "max_push_m")
#: Stamped on a refused fit's failure record (``garment_store.record_failure``): the refusal was made WITH the scale
#: retry. A too-small refusal recorded without it is retried once by the refit sweep (``garment_refit``).
SCALE_RETRY_VERSION = 1

_ARM_TOKENS = ("arm", "hand", "shoulder")
_LOWER_ARM_TOKENS = ("forearm", "hand")
_LEG_TOKENS = ("leg", "foot", "toe")


# --- welding / components ------------------------------------------------------------------------------------------

def weld(P, F, U=None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weld duplicates (positions rounded to 1e-6) -> ``(Pw, Fw, inv)`` with ``Pw[inv]`` ~ ``P``.

    Faces collapsing onto fewer than three welded vertices are dropped. ``U`` (the UVs) is only checked for its
    length: UV seams are exactly what is welded away, the caller keeps its per-vertex UVs through ``inv``.
    """
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if U is not None and len(U) != len(P):
        raise ValueError("UV count differs from the vertex count")
    _, first, inv = np.unique(np.round(P, 6), axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    Fw = inv[F]
    keep = (Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])
    return P[first], Fw[keep], inv


def triangle_areas(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    if len(F) == 0:
        return np.zeros(0)
    return 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)


def components(Pw, Fw) -> Tuple[np.ndarray, np.ndarray]:
    """``(labels per vertex, area share per label)`` of the edge-connected components."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    Pw = np.asarray(Pw, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    n = len(Pw)
    E = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n))
    count, labels = connected_components(graph, directed=False)
    area = np.bincount(labels[Fw[:, 0]], weights=triangle_areas(Pw, Fw), minlength=count) if len(Fw) \
        else np.zeros(count)
    total = area.sum()
    return labels, (area / total if total > 0 else np.zeros(count))


def drop_small(Pw, Fw, min_share: float = MIN_COMPONENT_SHARE) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop components below ``min_share`` of the area -> ``(Pk, Fk, keep)``; ``keep`` indexes ``Pw`` (vertices
    used by no remaining face go too)."""
    Pw = np.asarray(Pw, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    labels, share = components(Pw, Fw)
    Fk = Fw[share[labels[Fw[:, 0]]] >= min_share] if len(Fw) else Fw
    keep = np.unique(Fk)
    new = np.full(len(Pw), -1, np.int64)
    new[keep] = np.arange(len(keep))
    return Pw[keep], new[Fk], keep


# --- placement --------------------------------------------------------------------------------------------------------

def _frame(P: np.ndarray, mask) -> Tuple[float, np.ndarray, np.ndarray]:
    """``(mesh units per pixel, mask bbox centre (x, y) px, mesh bbox centre)``; the height is the reliable axis."""
    ys, xs = np.nonzero(np.asarray(mask, bool))
    if len(xs) == 0:
        raise ValueError("Empty mask: nothing to frame")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    lo, hi = P.min(0), P.max(0)
    return float((hi - lo)[1] / (y1 - y0)), np.array([(x0 + x1) / 2, (y0 + y1) / 2]), (lo + hi) / 2


def place_by_framing(Pd, body_P, body_mask, garment_mask) -> np.ndarray:
    """Map garment mesh coordinates into unrigged body coordinates through the shared image framing.

    Both meshes were generated from views with the same framing: the garment vertex goes to image pixels through
    its own mesh/mask frame and from there into the body's. x right = +x, image y down = -y; the depth is scaled
    like x/y and centred on the body (``align_depth`` sets it afterwards).
    """
    Pd = np.asarray(Pd, np.float64)
    body_P = np.asarray(body_P, np.float64)
    sb, cb, mb = _frame(body_P, body_mask)
    sd, cd, md = _frame(Pd, garment_mask)
    px = cd[0] + (Pd[:, 0] - md[0]) / sd
    py = cd[1] - (Pd[:, 1] - md[1]) / sd
    Q = np.empty_like(Pd)
    Q[:, 0] = mb[0] + (px - cb[0]) * sb
    Q[:, 1] = mb[1] - (py - cb[1]) * sb
    Q[:, 2] = mb[2] + (Pd[:, 2] - md[2]) * (sb / sd)
    return Q


# --- openings (Ruling A35) -------------------------------------------------------------------------------------------
# A ghost view shows the garment without its wearer, so through an OPENING — the V of a blazer, a neckline — it shows
# the garment's own inside, and the mesher builds that inside as a surface across the opening. Worn, the body stands in
# front of it: in the worn view the same pixels show skin. Laid on the body by the framing, that surface lies inside
# the trunk and the push-out carried it onto the skin — it CLOSED the opening (Kira's black blazer ``item_5bfe0cbc``
# fit 8a64a2576446, 2026-11-14: the V 10.5 / 9.6 / 7.5 cm wide at 0.17 / 0.21 / 0.25 of the body height below its top
# after the placement, 0.3 / 0.6 / 0.9 cm after the push; the 37 - 41 vertices over the sternum came from 2.6 - 3.0 cm
# inside the chest, at the midline). The inside is found on the IMAGES and the mesh alone (``opening_lining``), never
# on the body, so every fit of one prepared mesh leaves out the same faces and keeps one vertex order
# (``_out_index``). All lengths are pixels of the ghost view (the mesh framed onto its mask like ``place_by_framing``,
# depth scaled like the height):
# 1. the opening: the ghost-mask pixels where the worn view differs from the ghost by more than ``OPEN_DIFF``
#    (``garment_source.opening_masks``), opened by ``OPEN_ERODE_PX``, components of at least ``OPEN_MIN_SHARE`` of the
#    mask;
# 2. the mesh's front and back per pixel (its faces sampled ``OPEN_FACE_SAMPLES`` steps per edge, closed over
#    ``OPEN_GAP_PX``); a vertex is on the front within ``OPEN_FRONT_TOL_PX`` of it, LAYERED when the garment reaches
#    ``OPEN_LAYER_PX`` behind it too — a surface that is the only layer at its pixel is a back wall (the back panel,
#    the back of the collar) and is never left out, or the piece would get a hole;
# 3. a component is an opening when its front lies at least ``OPEN_RECESS_PX`` (median) behind the front in a ring
#    ``OPEN_RING_PX`` around it — a recessed inside, not a hand the worn view held in front of the garment; its
#    layered front vertices that lie ``OPEN_STEP_PX`` behind the front within ``OPEN_LOCAL_PX`` are the seeds (the
#    opening's own rim, where the mask's border pixels fall, is the front itself);
# 4. the inside reaches past the worn view's opening (worn, the lapels close in over it): from the seeds over the
#    mesh through layered front vertices within ``OPEN_REACH_PX`` of the opening that lie ``OPEN_STEP_PX`` behind the
#    front within ``OPEN_LOCAL_PX`` (a recessed surface; the lapel's own fold is not), then ``OPEN_FILL_PASSES``
#    passes close the pinholes (a layered front vertex there whose neighbours are mostly inside).
# A face whose three vertices are inside is not fitted: through the opening the body shows, as in the worn view. On
# the blazer: one opening of 13666 px (recess 24.8 px), 1538 faces left out, the back intact; fitted, the V is
# 7.0 / 6.1 / 2.6 cm wide at 0.17 / 0.21 / 0.25 (the neckline's top stays closed where the inside is the back of the
# collar, a single layer).
# Ruling A51 (2026-11-14): the recess test of step 3 misses an inside the mesher builds almost FLUSH with the front.
# The blazer's mesh of the same image group made again (UniForge3D multiview, 16:50) closes the V with a sheet that
# runs from the back of the collar forward to the V's lowest point: the same 13666 px opening measured a recess of
# only 10.4 px, nothing was left out, and the fit laid the dark sheet onto the chest — the V black again. The worn
# view says what the opening is: there the worn front shows the BODY itself inside the garment's outline. ``shown``
# (the third mask of ``garment_source.opening_masks``) holds those pixels — the ghost-mask pixels on the base figure
# where the worn view does not differ from the base view it was edited from (``garment_from_worn.piece_mask``, the A46
# worn-minus-base mask: everything outside the piece is the body as the base shows it). A component the recess test
# keeps is an opening all the same when at least ``OPEN_SHOWN_SHARE`` of it is shown body, its inside still lies
# ``OPEN_SHOWN_RECESS_PX`` behind its ring (shallow, but behind: a skirt's slit or a belly above a waistband shows the
# body too, with the garment's front around it) and the garment encloses it (at most ``OPEN_SHOWN_OUTLINE_MAX`` of its
# ring outside the garment mask: an opening inside the outline, not a notch at its edge); its seeds are its vertices
# on shown pixels with garment ``OPEN_LAYER_PX`` behind them, and the inside grows from them as in step 4. A hand the
# worn view held in front of the garment is no shown body (the base has no hand there: worn and base differ), and a
# single layer — the back panel, the back of the collar — still never goes (``layered``). Without the evidence (no
# base copy of the image group, another framing) the recess test alone decides, as before. On the remeshed blazer: the
# 13666 px V (shown 0.965, outline 0.146) goes, 3591 faces; the hem's 3074 px (recess 5.1, outline 0.396, at the edge)
# stays; fitted, the V is 13.7 / 10.5 / 7.3 cm wide at 0.17 / 0.21 / 0.25 on the base body and 11.7 / 9.9 / 7.4 on the
# outfit body (the earlier mesh ``2860e5a646c0``, by the recess alone: 13.3 / 11.8 / 8.0). Unchanged, vertex for
# vertex: that earlier mesh (2220 faces), Kai's jacket (its 628 px recess 1.3), Kai's jeans (the waistband's 4868 px,
# outline 0.467), Kira's skirt (the slit, recess -33.9) and Glut's scale top (the gaps between its straps: outline
# 0.456 / 0.564 at its two largest).
OPEN_DIFF = 80
OPEN_ERODE_PX = 3
OPEN_MIN_SHARE = 0.002
OPEN_GAP_PX = 3
OPEN_FACE_SAMPLES = 4
OPEN_FRONT_TOL_PX = 12
OPEN_RING_PX = 6
OPEN_RECESS_PX = 15
OPEN_LAYER_PX = 30
OPEN_REACH_PX = 10
OPEN_LOCAL_PX = 40
OPEN_STEP_PX = 10
OPEN_FILL_PASSES = 6
#: Share of an opening component that must be shown body in the worn view (``shown``) for it to count without the
#: full recess (Ruling A51) ...
OPEN_SHOWN_SHARE = 0.5
#: ... while its inside still lies at least this far (median, px) behind the ring around it — shallow, but behind ...
OPEN_SHOWN_RECESS_PX = 5
#: ... and the garment encloses it: at most this share of its ring (``OPEN_RING_PX``) lies outside the garment mask.
OPEN_SHOWN_OUTLINE_MAX = 0.25
#: Most sampling steps per face edge of the dense depth images (``_depth_images``, Ruling A51): a face that long gets
#: (401 x 402) / 2 = 80 601 samples; the remeshed blazer's longest face is 57 px, its median 10.
OPEN_DENSE_MAX = 400


def opening_lining(Pd: np.ndarray, Fd: np.ndarray, opening, garment_mask,
                   shown=None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Per vertex of the garment mesh (``Pd`` / ``Fd``, its own coordinates) whether it is the inside seen through
    an opening (block above) — a face whose three vertices are is left out (``_open_faces``); ``opening`` /
    ``garment_mask`` / ``shown`` (optional: the pixels where the worn view shows the body, Ruling A51) in the ghost
    view's OWN frame (one size, unregistered).
    ``(lining, report {components: [{pixels, recess_px, shown?, outline?, by?, dropped}], shown, faces})`` —
    ``shown`` the component's share of shown body and ``outline`` its ring's share outside the garment mask (with the
    evidence), ``by`` ``"recess"`` / ``"shown"`` for a dropped one."""
    from scipy import ndimage
    Pd = np.asarray(Pd, np.float64)
    F = np.asarray(Fd, np.int64).reshape(-1, 3)
    report: Dict[str, Any] = {"components": [], "faces": 0}
    lining = np.zeros(len(Pd), bool)
    gm = _mask(garment_mask)
    op = _mask(opening)
    if op.shape != gm.shape or not (op & gm).any() or len(Pd) == 0:
        return lining, report
    op = ndimage.binary_opening(op & gm, iterations=OPEN_ERODE_PX) & gm
    sh = _mask(shown) & gm if shown is not None and np.asarray(shown).shape == gm.shape else None
    report["shown"] = sh is not None
    labels, n = ndimage.label(op)
    sd, cd, md = _frame(Pd, gm)
    h, w = gm.shape
    ix = np.clip(np.round(cd[0] + (Pd[:, 0] - md[0]) / sd).astype(int), 0, w - 1)
    iy = np.clip(np.round(cd[1] - (Pd[:, 1] - md[1]) / sd).astype(int), 0, h - 1)
    depth = (Pd[:, 2] - md[2]) / sd                  # pixels toward the viewer
    S = np.stack([cd[0] + (Pd[:, 0] - md[0]) / sd, cd[1] - (Pd[:, 1] - md[1]) / sd, depth], 1)
    front, back = _depth_images(S, F, (h, w))
    # front-most there AND with garment behind it: a surface that is the only layer at its pixel is a back wall
    # (the back panel, the back of the collar), which stays — leaving it out would leave a hole through the piece.
    on_front = depth >= front[iy, ix] - OPEN_FRONT_TOL_PX
    layered = on_front & (depth - back[iy, ix] >= OPEN_LAYER_PX)
    # recessed: at least OPEN_STEP_PX behind the front within OPEN_LOCAL_PX — the opening's own rim (the lapel edge
    # the mask's border pixels fall on) is the front itself and never the inside
    recessed = ndimage.maximum_filter(front, size=2 * OPEN_LOCAL_PX + 1)[iy, ix] - depth >= OPEN_STEP_PX
    seeds = np.zeros(len(Pd), bool)
    accepted = np.zeros((h, w), bool)
    accepted_shown = np.zeros((h, w), bool)
    sizes = np.bincount(labels.ravel(), minlength=n + 1)
    for c in range(1, n + 1):
        if sizes[c] < OPEN_MIN_SHARE * gm.sum():
            continue
        comp = labels == c
        ring = ndimage.binary_dilation(comp, iterations=OPEN_RING_PX) & ~op & gm
        inside = on_front & comp[iy, ix]
        around = on_front & ring[iy, ix]
        if inside.sum() < 3 or around.sum() < 3:
            continue
        recess = float(np.median(depth[around]) - np.median(depth[inside]))
        entry: Dict[str, Any] = {"pixels": int(sizes[c]), "recess_px": round(recess, 1)}
        by = "recess" if recess >= OPEN_RECESS_PX else None
        if sh is not None:
            share = float((comp & sh).sum()) / float(sizes[c])
            full_ring = ndimage.binary_dilation(comp, iterations=OPEN_RING_PX) & ~op
            outline = float((full_ring & ~gm).sum()) / max(float(full_ring.sum()), 1.0)
            entry.update(shown=round(share, 3), outline=round(outline, 3))
            if (by is None and share >= OPEN_SHOWN_SHARE and recess >= OPEN_SHOWN_RECESS_PX
                    and outline <= OPEN_SHOWN_OUTLINE_MAX):
                by = "shown"     # the worn view shows the body here: an opening however flush the mesh fills it
        entry["dropped"] = by is not None
        if by:
            entry["by"] = by
        report["components"].append(entry)
        if by == "recess":
            seeds |= inside & layered & recessed
            accepted |= comp
        elif by == "shown":
            accepted_shown |= comp
    A = (_adjacency(F, len(Pd))[0] > 0).astype(np.float64) if (accepted | accepted_shown).any() else None
    if seeds.any():
        # Grow over the mesh: the inside reaches past the worn view's opening, under the lapels that close in when
        # worn — front-most there, recessed behind the front within OPEN_LOCAL_PX, connected to a seed.
        region = ndimage.binary_dilation(accepted, iterations=OPEN_REACH_PX)[iy, ix] & layered
        lining |= _grow_lining(F, A, seeds, region, recessed)
    # Ruling A51, a component shown as body: its seeds are its vertices on shown pixels with garment at least
    # OPEN_LAYER_PX behind them (``ahead``), front-most or not — a flush inside is a sheet with two faces, and its rear
    # face, hidden behind the front one in the ghost, would be the surface left on the skin. The back wall is never
    # ahead. ``ahead`` is measured on depth images sampled at every pixel of each face (``dense``): the multiview
    # mesher's long faces leave the 4-step sampling's back image with holes, where the inside itself is the deepest
    # surface and so counts as a back wall.
    seeds_shown = np.zeros(len(Pd), bool)
    if accepted_shown.any():
        _front_d, back_d = _depth_images(S, F, (h, w), dense=True)
        ahead = depth - back_d[iy, ix] >= OPEN_LAYER_PX
        seeds_shown = (accepted_shown & sh)[iy, ix] & ahead & recessed
    if seeds_shown.any():
        # The same growth through the vertices ahead; then a vertex that is ahead and recessed joins when it is the
        # third vertex of a face whose other two are inside: the mesher spans long faces from the inside sheet to the
        # lining under the lapels, and each such face, kept for its one outside vertex, lay across the opening once
        # fitted.
        region = ndimage.binary_dilation(accepted_shown, iterations=OPEN_REACH_PX)[iy, ix] & ahead
        inner = _grow_lining(F, A, seeds_shown, region, recessed)
        count = inner[F].sum(1)
        bridge = F[count == 2][~inner[F[count == 2]]]
        join = np.zeros(len(Pd), bool)
        join[bridge] = True
        inner |= join & ahead & recessed
        lining |= inner
    report["faces"] = int(lining[F].all(1).sum())
    return lining, report


def _grow_lining(F: np.ndarray, A, seeds: np.ndarray, region: np.ndarray, recessed: np.ndarray) -> np.ndarray:
    """The inside grown from ``seeds`` over the mesh ``F`` (``opening_lining`` step 4): the vertices of ``region``
    recessed behind the front, connected to a seed, then ``OPEN_FILL_PASSES`` passes closing the pinholes (a vertex
    of the region whose neighbours in ``A`` are mostly inside is inside)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(seeds)
    grow = seeds | (region & recessed)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = E[grow[E].all(1)]
    graph = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n))
    _, comp_of = connected_components(graph, directed=False)
    lining = grow & np.isin(comp_of, np.unique(comp_of[seeds]))
    half = 0.5 * np.asarray(A.sum(1)).ravel()
    for _ in range(OPEN_FILL_PASSES):
        lining = lining | (region & (A @ lining.astype(np.float64) >= np.maximum(half, 0.5)))
    return lining


def _depth_images(S: np.ndarray, F: np.ndarray, shape: Tuple[int, int],
                  dense: bool = False) -> Tuple[np.ndarray, np.ndarray]:
    """``(front, back)``: per pixel the largest / smallest depth of the faces ``F`` over the pixel-space points
    ``S`` (x px, y px, depth px), sampled ``OPEN_FACE_SAMPLES`` steps per edge and closed over ``OPEN_GAP_PX``;
    ``dense`` (Ruling A51): each face sampled at least once per pixel of its longest edge (up to
    ``OPEN_DENSE_MAX`` steps), so a long face leaves no hole."""
    from scipy import ndimage
    h, w = shape
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if dense and len(F):
        edge = np.max([np.linalg.norm(S[F[:, i], :2] - S[F[:, (i + 1) % 3], :2], axis=1) for i in range(3)], axis=0)
        steps = np.clip(np.ceil(edge).astype(int), OPEN_FACE_SAMPLES, OPEN_DENSE_MAX)
    else:
        steps = np.full(len(F), OPEN_FACE_SAMPLES)
    front, back = np.full((h, w), -np.inf), np.full((h, w), np.inf)
    for n in np.unique(steps):
        G = F[steps == n]
        t = np.linspace(0.0, 1.0, int(n) + 1)
        uv = np.array([(a, b) for a in t for b in t if a + b <= 1.0 + 1e-9])
        A, B, C = S[G[:, 0]], S[G[:, 1]], S[G[:, 2]]
        pts = (A[:, None] * (1.0 - uv.sum(1))[None, :, None] + B[:, None] * uv[None, :, 0, None]
               + C[:, None] * uv[None, :, 1, None]).reshape(-1, 3)
        sx = np.clip(np.round(pts[:, 0]).astype(int), 0, w - 1)
        sy = np.clip(np.round(pts[:, 1]).astype(int), 0, h - 1)
        np.maximum.at(front, (sy, sx), pts[:, 2])
        np.minimum.at(back, (sy, sx), pts[:, 2])
    return (ndimage.maximum_filter(front, size=OPEN_GAP_PX), ndimage.minimum_filter(back, size=OPEN_GAP_PX))


def _open_faces(F: np.ndarray, lining: Optional[np.ndarray]) -> np.ndarray:
    """Per face of ``F`` (indices into ``lining``'s vertices) whether it stays: not all three vertices lining."""
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if lining is None or not len(F):
        return np.ones(len(F), bool)
    return ~np.asarray(lining, bool)[F].all(1)


# --- body SDF / push-out ---------------------------------------------------------------------------------------------

@dataclass
class Sdf:
    """Signed distance of a voxelised solid (negative inside), trilinear sampling."""
    field: np.ndarray
    lo: np.ndarray
    vox: float
    _grad: Tuple[np.ndarray, ...] = ()

    def __post_init__(self):
        self._grad = tuple(np.gradient(self.field))

    def _coords(self, X) -> np.ndarray:
        return ((np.asarray(X, np.float64) - self.lo) / self.vox).T

    def sample(self, X) -> np.ndarray:
        from scipy import ndimage
        return ndimage.map_coordinates(self.field, self._coords(X), order=1, mode="nearest")

    def grad(self, X) -> np.ndarray:
        """The (unnormalised) spatial gradient at ``X``."""
        from scipy import ndimage
        c = self._coords(X)
        return np.stack([ndimage.map_coordinates(g, c, order=1, mode="nearest") for g in self._grad], 1) / self.vox


def _surface_samples(P: np.ndarray, F: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The spike's 5 x 5 barycentric samples (15 per triangle) -> ``(points, triangle index per point)``."""
    tri = P[F]
    steps = np.linspace(0, 1, 5)
    out = [tri[:, 0] * (1 - u - v) + tri[:, 1] * u + tri[:, 2] * v
           for u in steps for v in steps if u + v <= 1 + 1e-9]
    return np.concatenate(out), np.tile(np.arange(len(F)), len(out))


def point_triangle_distance(X: np.ndarray, A: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """Euclidean distance of points ``X`` to triangles ``(A, B, C)`` (broadcasting, last axis xyz; Ericson's
    closest-point regions, degenerate triangles fall back to their edges)."""
    return np.linalg.norm(X - point_triangle_closest(X, A, B, C), axis=-1)


def point_triangle_closest(X: np.ndarray, A: np.ndarray, B: np.ndarray, C: np.ndarray) -> np.ndarray:
    """The closest point of triangles ``(A, B, C)`` to points ``X`` (see ``point_triangle_distance``)."""
    ab, ac, ap = B - A, C - A, X - A
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = X - B
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = X - C
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    eps = 1e-30
    # interior
    denom = va + vb + vc
    v = vb / np.where(np.abs(denom) > eps, denom, eps)
    w = vc / np.where(np.abs(denom) > eps, denom, eps)
    closest = A + ab * v[..., None] + ac * w[..., None]

    def seg(P0, P1):
        d = P1 - P0
        t = np.clip(((X - P0) * d).sum(-1) / np.maximum((d * d).sum(-1), eps), 0, 1)
        return P0 + d * t[..., None]
    regions = [
        (d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (d6 >= 0) & (d5 <= d6),
        (vc <= 0) & (d1 >= 0) & (d3 <= 0), (vb <= 0) & (d2 >= 0) & (d6 <= 0),
        (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0),
    ]
    points = [A, B, C, seg(A, B), seg(A, C), seg(B, C)]
    done = np.zeros(d1.shape, bool)
    for region, point in zip(regions, points):
        region = region & ~done
        closest = np.where(region[..., None], np.broadcast_to(point, closest.shape), closest)
        done |= region
    # degenerate triangles: nearest of the three edges
    degenerate = np.linalg.norm(np.cross(ab, ac), axis=-1) <= 1e-18
    if degenerate.any():
        edge = [seg(A, B), seg(A, C), seg(B, C)]
        dist = np.stack([np.linalg.norm(X - e, axis=-1) for e in edge], -1)
        pick = np.take_along_axis(np.stack(edge, -2), dist.argmin(-1)[..., None, None], -2)[..., 0, :]
        closest = np.where(degenerate[..., None], pick, closest)
    return closest


def body_sdf(P, F, *, vox: float, bounds, zero_offset_vox: Optional[float] = None,
             exact_band_vox: float = SDF_EXACT_BAND_VOX) -> Sdf:
    """Signed distance field of the body solid on a grid cropped to ``bounds = (lo, hi)``, snapped outward to the
    body's lattice: ``body_field.field(body_field.body_solid(P, F, vox=vox), bounds, ...)`` — the solid (surface
    voxelisation, hole fill, seal, three-axis slice fill) is built once per body content and cached per process;
    the crop's EDT, zero-level offset and exact outside band are taken from it (``app/core/body_field.py``, plan
    2026-11-12 fit-sdf-speed-drape, Task 5)."""
    from app.core import body_field
    return body_field.field(body_field.body_solid(P, F, vox=vox), bounds, zero_offset_vox=zero_offset_vox,
                            exact_band_vox=exact_band_vox)


def _adjacency(F: np.ndarray, n: int):
    """Row-normalised edge adjacency (edges counted per face, like the spike's ``np.add.at``)."""
    from scipy.sparse import coo_matrix
    F = np.asarray(F, np.int64).reshape(-1, 3)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = np.concatenate([E, E[:, ::-1]])
    A = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n)).tocsr()
    deg = np.asarray(A.sum(1)).ravel()
    return A, np.maximum(deg, 1)[:, None]


def _smooth(D: np.ndarray, adjacency, passes: int) -> np.ndarray:
    A, deg = adjacency
    for _ in range(passes):
        D = 0.5 * D + 0.5 * (A @ D) / deg
    return D


def _unit(g: np.ndarray) -> np.ndarray:
    return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)


def push_out(Q0, Fd, sdf: Sdf, *, clear: float, spread: float = 0.0, spread_depth: float = 0.0,
             iterations: int = PUSH_ITERATIONS, smooth_until: int = PUSH_SMOOTH_UNTIL,
             spread_until: int = PUSH_SPREAD_UNTIL) -> Tuple[np.ndarray, np.ndarray]:
    """Push garment vertices to at least ``clear`` outside the body -> ``(Q, disp)``.

    Each iteration adds ``max(clear - d, 0)`` along the SDF gradient. While ``it < spread_until`` the crown
    (``y > top - spread_depth``) takes, per vertex, the largest displacement found within ``spread`` (cKDTree, up to
    48 neighbours): an inner hair layer pushed out carries the outer layer with it instead of poking through. While
    ``it < smooth_until`` the displacement is smoothed over the mesh (6 passes); the last iterations enforce the
    clearance exactly.
    """
    from scipy.spatial import cKDTree
    Q0 = np.asarray(Q0, np.float64)
    n = len(Q0)
    adjacency = _adjacency(Fd, n)
    crown = Q0[:, 1] > Q0[:, 1].max() - spread_depth
    disp = np.zeros_like(Q0)
    rows = np.arange(n)
    for it in range(iterations):
        X = Q0 + disp
        need = np.clip(clear - sdf.sample(X), 0, None)
        disp = disp + need[:, None] * _unit(sdf.grad(X))
        if spread > 0 and it < spread_until and crown.any():
            X = Q0 + disp
            dist, nn = cKDTree(X).query(X, k=min(PUSH_SPREAD_K, n), distance_upper_bound=spread)
            dist, nn = dist.reshape(n, -1), nn.reshape(n, -1)
            nn = np.where(np.isinf(dist), rows[:, None], nn)
            mag = np.linalg.norm(disp, axis=1)[nn]
            spread_disp = disp[nn[rows, mag.argmax(1)]]
            disp = np.where(crown[:, None], spread_disp, disp)
        if it < smooth_until:
            disp = _smooth(disp, adjacency, SMOOTH_PASSES)
    return Q0 + disp, disp


def push_kept(Q0, adjacency, sdf: Sdf, *, clear: float, iterations: int, smooth_until: int,
              margin: float, passes: int = SMOOTH_PASSES, start: Optional[np.ndarray] = None) -> np.ndarray:
    """The clothing push (unrigged ``fit_clothing`` and rigged ``transfer_skinned``) -> the displacement of ``Q0``.

    ``push_out``'s loop without the crown spread — each iteration adds ``max(clear - d, 0)`` along the field's
    gradient, smoothed over the mesh (``passes``) while ``it < smooth_until``, the last iterations enforce the
    clearance exactly — except that the smoothing may not carry a vertex across the body. Since fit-sdf-speed-drape
    Task 1 the body field is solid (``body_sdf``: double walls filled), and a vertex the transfer leaves deep in the
    trunk is pushed out through solid body, where BASE's leaky field had stopped it in the cavity; its neighbours
    were dragged along (Kai's jacket 2026-11-12: up to 30 cm, front to back, the obf torso-hole gate failed).
    - A vertex's own step follows the gradient at its current position, which leads out on the near side: a step
      of ``clear - d`` from depth ``-d`` lands outside on that side and never crosses a medial plane by itself.
    - After each smoothing, a vertex whose smoothed displacement crosses the body — its straight path from the
      start (``SIDE_PATH_SAMPLES`` samples) goes deeper than ``min(start depth, 0)`` by more than a voxel — or ends
      further from the start than its own depth + ``clear`` + ``margin``, keeps its OWN displacement of this
      iteration (the unsmoothed one) instead. Every other vertex keeps the smoothed sheet exactly as before: where
      nothing is carried the result equals the plain loop bit for bit.
    - ``start`` (rows of displacements, zero rows = none): where a vertex the transfer buried on the wrong side starts
      (``_side_projection``: on its own side of the body, not at the nearest exit of the solid it was dropped into).
    """
    Q0 = np.asarray(Q0, np.float64)
    s0 = sdf.sample(Q0)
    floor = np.minimum(s0, 0.0) - sdf.vox
    reach = np.maximum(-s0, 0.0) + clear + margin
    D = np.zeros_like(Q0) if start is None else np.array(start, np.float64)
    for it in range(iterations):
        Y = Q0 + D
        D = D + np.clip(clear - sdf.sample(Y), 0, None)[:, None] * _unit(sdf.grad(Y))
        if it < smooth_until:
            S = _smooth(D, adjacency, passes)
            carried = np.linalg.norm(S, axis=1) > reach
            for t in np.linspace(0.0, 1.0, SIDE_PATH_SAMPLES + 1)[1:]:
                carried |= sdf.sample(Q0 + t * S) < floor
            D = np.where(carried[:, None], D, S)
    return D


def _in_crop(sdf: Sdf, X: np.ndarray) -> np.ndarray:
    """Per row: inside the field's grid (where ``Sdf.sample`` reads the field itself, never a clamped border value)."""
    lo = np.asarray(sdf.lo, np.float64)
    hi = lo + (np.asarray(sdf.field.shape) - 1) * sdf.vox
    X = np.asarray(X, np.float64).reshape(-1, 3)
    return np.all((X >= lo) & (X <= hi), axis=1)


def _side_projection(sdf: Sdf, X: np.ndarray, toward: np.ndarray, P: np.ndarray, F: np.ndarray, clear: float
                     ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The start of the rigged push for the vertices ``_transfer_sides`` names (rows of ``toward`` that are not zero):
    a PROJECTION onto the nearest surface of the body ``(P, F)`` on the vertex's own side -> ``(displacements, report)``.

    The surface is the body's samples (``_surface_samples``) inside the field's crop, each with its outward normal =
    the field's gradient there. A vertex goes to the nearest sample whose normal lies within acos(``SIDE_COS``) of its
    side ``u``, lifted ``clear`` along that normal, then settled at the clearance by gradient steps
    (``SIDE_SETTLE_ITERATIONS``, ``max(clear - d, 0)`` along the gradient) — its move is the distance to that surface,
    never a walk through the body (Ruling A8c; the fixed 30 cm march it replaces left Kai's jacket with shards over the
    hip). Nothing is read outside the crop: a vertex without such a sample in the crop, or whose landing point leaves
    the crop or does not reach ``clear``, keeps a zero row (the push treats it like any other vertex) and is counted.
    ``report``: ``side_projected``, ``side_unreached``, ``side_reach_max_m`` (the largest projection)."""
    from scipy.spatial import cKDTree
    D = np.zeros_like(np.asarray(X, np.float64))
    rows = np.nonzero(np.any(toward != 0, axis=1))[0]
    report = {"side_projected": 0, "side_unreached": 0, "side_reach_max_m": 0.0}
    if len(rows) == 0:
        return D, report
    pts, _ = _surface_samples(np.asarray(P, np.float64), np.asarray(F, np.int64).reshape(-1, 3))
    pts = pts[_in_crop(sdf, pts)]
    target = np.full((len(rows), 3), np.nan)
    if len(pts):
        normal = _unit(sdf.grad(pts))
        tree = cKDTree(pts)
        u = toward[rows]
        todo = np.arange(len(rows))
        k = 64
        while len(todo):
            kk = min(k, len(pts))
            _, nn = tree.query(X[rows[todo]], k=kk)
            nn = nn.reshape(len(todo), kk)
            facing = np.einsum("nkj,nj->nk", normal[nn], u[todo]) > SIDE_COS
            hit = facing.any(1)
            j = nn[hit, facing[hit].argmax(1)]
            target[todo[hit]] = pts[j] + normal[j] * clear
            todo = todo[~hit]
            if kk == len(pts):
                break
            k *= 16
    ok = ~np.isnan(target[:, 0])
    T = np.where(ok[:, None], target, X[rows])
    ok &= _in_crop(sdf, T)
    for _ in range(SIDE_SETTLE_ITERATIONS):
        s = sdf.sample(T)
        step = ok & (s < clear)
        if not step.any():
            break
        T[step] += (clear - s[step])[:, None] * _unit(sdf.grad(T[step]))
        ok &= _in_crop(sdf, T)
    ok &= sdf.sample(T) >= clear - 0.1 * sdf.vox
    D[rows[ok]] = T[ok] - X[rows[ok]]
    report.update(side_projected=int(ok.sum()), side_unreached=int((~ok).sum()),
                  side_reach_max_m=float(np.linalg.norm(D[rows[ok]], axis=1).max()) if ok.any() else 0.0)
    return D, report


def _transfer_sides(Q, X, body_unrigged: BodyMesh, bones, W, sdf: Sdf) -> np.ndarray:
    """The side of the body each garment vertex had BEFORE the transfer, for the ones the transfer put inside the
    rigged body on another side (``push_kept`` ``toward``): rows of unit vectors, zero rows = none.

    A vertex counts when it is deeper than ``SIDE_DEEP_M`` (nearer the surface the gradient's side is the right
    one: a shallow vertex is pushed as the plain loop always did) and the direction of its unrigged side — the
    outward direction from the nearest unrigged surface sample to its unrigged position ``Q`` (pushed out there, so
    outside), carried into the bind space by the linear part of its own blend skinning — is more than
    acos(``SIDE_COS``) away from the rigged field's gradient. Kai's jacket 2026-11-12: the side panel below the
    armpit (outside the unrigged body, facing +x) is skinned into the chest's medial plane, 9 - 10 cm deep; its
    gradient leads out by the front OR the back, which left the side bare (the obf torso-hole gate, 22 - 36 cm2).
    """
    from scipy.spatial import cKDTree
    out = np.zeros_like(X)
    s = sdf.sample(X)
    rows = np.nonzero(s < -SIDE_DEEP_M)[0]
    if len(rows) == 0:
        return out
    pts, _ = _surface_samples(body_unrigged.positions, body_unrigged.faces)
    _, nn = cKDTree(pts).query(Q[rows])
    n = _unit(Q[rows] - pts[nn])
    side = _unit(bones.apply(n, W[rows]) - bones.apply(np.zeros_like(n), W[rows]))
    g = _unit(sdf.grad(X[rows]))
    off = (side * g).sum(1) < SIDE_COS
    out[rows[off]] = side[off]
    return out


# --- transfer into the rigged bind space ----------------------------------------------------------------------------

def similarity(A: np.ndarray, B: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """Least-squares similarity ``B ~ s R (A - a) + b`` (Umeyama) -> ``(s, R, a, b)``."""
    a, b = A.mean(0), B.mean(0)
    A0, B0 = A - a, B - b
    U, S, Vt = np.linalg.svd(A0.T @ B0)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    s = float((S * np.array([1.0, 1.0, d])).sum() / max((A0 ** 2).sum(), 1e-30))
    return s, R, a, b


def dense_weights(body: BodyMesh) -> np.ndarray:
    """``(n, n_joints)`` weights of a skinned body."""
    nj = max(len(body.joint_names), int(body.joints.max()) + 1 if body.joints.size else 0)
    W = np.zeros((len(body.positions), nj))
    np.add.at(W, (np.repeat(np.arange(len(body.positions)), 4), body.joints.ravel()), body.weights.ravel())
    return W


def joint_index(body: BodyMesh, key: str) -> int:
    """Skin index of the joint whose ``norm_bone_name`` is ``key``; KeyError naming it otherwise."""
    from app.core.rig_contract import norm_bone_name
    for i, name in enumerate(body.joint_names):
        if norm_bone_name(name) == key:
            return i
    raise KeyError(f"The rigged body has no joint '{key}'")


def uv_correspondence(body_unrigged: BodyMesh, body_rigged: BodyMesh) -> Tuple[np.ndarray, np.ndarray]:
    """``(rigged index per unrigged body vertex, UV distance)`` through the shared UV atlas."""
    from scipy.spatial import cKDTree
    dist, corr = cKDTree(body_rigged.uvs).query(body_unrigged.uvs)
    if np.median(dist) > 1e-4:
        raise ValueError("The rigged base does not share the UV atlas of the unrigged base "
                         f"(median UV distance {np.median(dist):.2e})")
    return corr, dist


# --- skinned transfer (clothing) ------------------------------------------------------------------------------------------

@dataclass
class BoneTransforms:
    """One rigid transform per skin joint, ``k * unrigged -> rigged`` (metres): ``X = R[b] @ x + t[b]``.

    ``has[b]`` says the joint carries enough body weight for its own transform; ``fold[b]`` is the joint whose
    transform a joint without one uses (itself when ``has``). ``report`` holds the body's own LBS residual.
    """
    R: np.ndarray                      # (nj, 3, 3)
    t: np.ndarray                      # (nj, 3)
    has: np.ndarray                    # (nj,) bool
    fold: np.ndarray                   # (nj,) int
    report: Dict[str, Any] = field(default_factory=dict)

    def fold_weights(self, W: np.ndarray) -> np.ndarray:
        """Dense weights ``(n, nj)`` with every weight moved onto a joint that has a transform."""
        out = np.zeros_like(W)
        for j in range(W.shape[1]):
            out[:, self.fold[j]] += W[:, j]
        return out

    def apply(self, Xk: np.ndarray, W: np.ndarray) -> np.ndarray:
        """Linear blend skinning of points ``Xk`` (already scaled by ``k``) with folded dense weights ``W``."""
        out = np.zeros_like(Xk)
        for j in np.nonzero(self.has)[0]:
            w = W[:, j]
            rows = np.nonzero(w)[0]
            if len(rows):
                out[rows] += w[rows, None] * (Xk[rows] @ self.R[j].T + self.t[j])
        return out

def _kabsch(P: np.ndarray, Q: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Rigid ``Q ~ R P + t`` (least squares, det +1) -> ``(R, t)``."""
    a, b = P.mean(0), Q.mean(0)
    U, _, Vt = np.linalg.svd((P - a).T @ (Q - b))
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return R, b - R @ a


def bone_transforms(body_unrigged: BodyMesh, body_rigged: BodyMesh, corr: np.ndarray, k: float, *,
                    core_weight: float = BONE_CORE_WEIGHT, core_min: int = BONE_CORE_MIN) -> BoneTransforms:
    """Recover the pose change unrigged -> rigged as one rigid transform per bone.

    The rigged body is the unrigged body posed by linear blend skinning with its own weights. Each bone with a
    rigid core (``core_min`` body vertices with >= ``core_weight`` of their weight on it) gets the Kabsch fit of
    that core, ``k * unrigged -> rigged``, refit once without vertices farther than ``BONE_CORE_OUTLIER_M`` from
    the first fit (UV-twin mismatches). A bone without a core — a blend-only bone — folds into the bone its
    vertices co-weight most (a joint least-squares over all bones puts arbitrary affine motion on such bones:
    measured p99 44 mm against 9 mm for the folds). The report carries the residual of the whole body skinned by
    the result (p50 / p99, metres) and the folds.
    """
    Pb, Pr = body_unrigged.positions, body_rigged.positions
    W = dense_weights(body_rigged)[corr]
    W = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
    nj = W.shape[1]
    A = Pb * float(k)
    B = Pr[corr]
    R = np.tile(np.eye(3), (nj, 1, 1))
    t = np.zeros((nj, 3))
    has = np.zeros(nj, bool)
    for j in range(nj):
        core = np.nonzero(W[:, j] >= core_weight)[0]
        if len(core) < core_min:
            continue
        R[j], t[j] = _kabsch(A[core], B[core])
        keep = np.linalg.norm(A[core] @ R[j].T + t[j] - B[core], axis=1) <= BONE_CORE_OUTLIER_M
        if keep.sum() >= max(core_min, 4) and not keep.all():
            R[j], t[j] = _kabsch(A[core[keep]], B[core[keep]])
        has[j] = True
    if not has.any():
        raise ValueError("No bone of the rigged body has a rigid core")
    total = W.sum(0)
    fold = np.arange(nj)
    for j in np.nonzero(~has)[0]:
        rows = W[:, j] > 0
        co = W[rows].sum(0) if rows.any() else np.zeros(nj)
        co[~has] = -1.0
        fold[j] = int(co.argmax()) if co.max() > 0 else int(np.where(has, total, -1.0).argmax())
    out = BoneTransforms(R=R, t=t, has=has, fold=fold)
    res = np.linalg.norm(out.apply(A, out.fold_weights(W)) - B, axis=1)
    out.report = {
        "bones": int(has.sum()),
        "folded": {body_rigged.joint_names[j]: body_rigged.joint_names[fold[j]] for j in np.nonzero(~has)[0]
                   if total[j] > 0},
        "body_lbs_res_p50_m": float(np.median(res)),
        "body_lbs_res_p99_m": float(np.percentile(res, 99)),
    }
    return out


def trusted_donor_weights(Pb: np.ndarray, Pr_corr: np.ndarray, bones: BoneTransforms, Wb: np.ndarray, k: float
                          ) -> Tuple[np.ndarray, np.ndarray]:
    """Ruling A72 — the donor skin of the unrigged body, with every UV MISMATCH repaired -> ``(Wb', mismatched)``.

    ``Wb`` (folded, normalised) holds per unrigged body vertex the skin of its UV match ``Pr_corr`` on the rigged
    body (``uv_correspondence``). Where the rigged base does not carry the unrigged vertex's UV, the nearest UV can
    lie on another island: on Kira's ``base20d5701a`` 490 of 67038 vertices (243 of them without an exact UV) —
    54 at the navel matched onto the right upper arm / forearm and the left shoulder. ``bone_transforms`` already
    drops such vertices from its bone cores (``BONE_CORE_OUTLIER_M``), but the transfer took their skin as it was:
    the waistband of Kira's black slit skirt beside the navel had the right arm as its nearest donor PART, became a
    "sleeve" (``sleeve_vertices``), rode the whole arm chain into the T-pose and stood 37 cm out to the right — the
    sliver from the skirt's centre to the right side (fit ``a9bb05bf45f3``, 118 vertices, edges up to 23 cm).

    A vertex is mismatched when the bones carry it, by the skin of its match, farther than ``BONE_CORE_OUTLIER_M``
    from that match: measured on ``base20d5701a`` the body's own residual is p99 16 mm, and nothing lies between
    5 and 10 cm (5 vertices 4 - 5 cm, then 22 at 10 - 15 cm and 468 beyond); on ``obf043ed6a`` nothing between 2 and
    10 cm (64 UV twins beyond). Such a vertex takes the skin of the nearest matched vertex of the unrigged body."""
    from scipy.spatial import cKDTree
    res = np.linalg.norm(bones.apply(np.asarray(Pb, np.float64) * float(k), Wb) - np.asarray(Pr_corr), axis=1)
    bad = res > BONE_CORE_OUTLIER_M
    if not bad.any() or bad.all():
        return Wb, bad
    good = np.nonzero(~bad)[0]
    nn = cKDTree(Pb[good]).query(Pb[bad], workers=fit_kernels.threads())[1]
    out = Wb.copy()
    out[bad] = Wb[good[nn]]
    return out, bad


def relax_stretched(X: np.ndarray, X0: np.ndarray, faces, adjacency, *, ratio: float = STRETCH_RELAX_RATIO,
                    passes: int = STRETCH_RELAX_PASSES) -> int:
    """Laplacian-relax (in place) the vertices of triangles whose area grew beyond ``ratio`` times their area in
    ``X0``, every other vertex fixed -> the number of relaxed vertices."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    if passes <= 0 or len(F) == 0:
        return 0
    a0, a1 = triangle_areas(X0, F), triangle_areas(X, F)
    stretched = a1 > ratio * np.maximum(a0, 1e-12)
    free = np.zeros(len(X), bool)
    free[F[stretched].ravel()] = True
    if not free.any():
        return 0
    A, deg = adjacency
    for _ in range(passes):
        mean = (A @ X) / deg
        X[free] = 0.5 * X[free] + 0.5 * mean[free]
    return int(free.sum())


def _donor_parts(Wb: np.ndarray, joint_names) -> np.ndarray:
    """Part per body vertex from its (folded) weights: 0 = the rest of the body, 1 = the left arm chain, 2 = the
    right (Arm / ForeArm / Hand bones of that side carry more than ``TRANSFER_PART_ARM_MIN``)."""
    from app.core.rig_contract import norm_bone_name
    parts = np.zeros(len(Wb), np.int64)
    for part, side in ((1, "left"), (2, "right")):
        cols = [i for i, n in enumerate(joint_names)
                if norm_bone_name(n).startswith(side) and any(t in norm_bone_name(n) for t in ("arm", "hand"))]
        if cols:
            parts[Wb[:, cols].sum(1) > TRANSFER_PART_ARM_MIN] = part
    return parts


def sleeve_vertices(Q, body_P, parts, faces, upper) -> np.ndarray:
    """The SLEEVES of a garment (unrigged units): the vertices whose nearest body vertex lies on an arm chain
    (``parts`` 1 / 2, ``_donor_parts``) and that are connected through such vertices of the SAME arm — within the
    garment mesh — to one at or above the waist (``upper``). A long sleeve hangs below the waist in the A-pose (the
    cuff beside the hip); it is still the sleeve and rides the whole arm, while a skirt panel beside a hanging hand
    reaches no sleeve through arm-nearest vertices and stays a skirt.

    Measured 2026-11-10, Kira's Black Blazer (long sleeves, waist at the garment top minus 0.20 of the body height):
    without this, the forearm half of each sleeve took torso weights and stayed at the hips in the T-pose while the
    upper half rode the arm."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    Q = np.asarray(Q, np.float64)
    near = np.asarray(parts)[cKDTree(np.asarray(body_P, np.float64)).query(Q, workers=fit_kernels.threads())[1]]
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = E[(near[E[:, 0]] > 0) & (near[E[:, 0]] == near[E[:, 1]])]
    n = len(Q)
    _, labels = connected_components(coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n, n)),
                                      directed=False)
    seeds = np.unique(labels[(near > 0) & np.asarray(upper, bool)])
    return (near > 0) & np.isin(labels, seeds)


#: How far (metres, along the garment mesh) a sleeve's cuff may reach beyond its arm-nearest part (``sleeve_cuffs``).
SLEEVE_CUFF_REACH_M = 0.10


def sleeve_cuffs(Q, body_P, parts, faces, upper, sleeve, k: float) -> np.ndarray:
    """Per garment vertex the arm part (1 / 2, ``_donor_parts``; 0 none) of a sleeve's CUFF: a vertex below the
    waist that is not a sleeve (``sleeve_vertices``) but lies within ``SLEEVE_CUFF_REACH_M`` (``Q`` in unrigged
    units, ``k`` to metres) of that arm's sleeve along the garment mesh, through such vertices only. The ghost may
    draw the sleeves nearer the trunk than the body's arms hang: placed on the A-pose body, the cuff hangs beside the
    thigh, its nearest skin is the leg, ``sleeve_vertices`` stops where the arm-nearest part ends and the cuff took
    the thigh's weights — in the T-pose it stayed at the hips, a web of fabric from the sleeve to the hip (Kira's
    black blazer ``item_5bfe0cbc`` fit 8a64a2576446, 2026-11-14: 1143 cuff vertices beside 10040 sleeve vertices,
    5058 of those below the waist). The cuff takes its weights from that arm's skin only. Within the reach,
    nothing but the cuff is met on that fit (the cuff tubes are their own surfaces); a skirt panel fused to a
    hanging cuff would ride the arm for at most the reach."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree
    Q = np.asarray(Q, np.float64)
    n = len(Q)
    out = np.zeros(n, np.int64)
    sleeve = np.asarray(sleeve, bool)
    cand = ~np.asarray(upper, bool) & ~sleeve
    if not cand.any() or not sleeve.any():
        return out
    near = np.asarray(parts)[cKDTree(np.asarray(body_P, np.float64)).query(Q, workers=fit_kernels.threads())[1]]
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    length = np.linalg.norm(Q[E[:, 0]] - Q[E[:, 1]], axis=1) * float(k)
    best = np.full(n, np.inf)
    for side in (1, 2):
        seeds = np.nonzero(sleeve & (near == side))[0]
        if not len(seeds):
            continue
        ok = (sleeve & (near == side)) | cand
        m = ok[E[:, 0]] & ok[E[:, 1]]
        graph = coo_matrix((np.maximum(length[m], 1e-9), (E[m, 0], E[m, 1])), shape=(n, n)).tocsr()
        dist = dijkstra(graph, directed=False, indices=seeds, min_only=True, limit=SLEEVE_CUFF_REACH_M)
        take = cand & (dist <= SLEEVE_CUFF_REACH_M) & (dist < best)
        out[take], best[take] = side, dist[take]
    return out


# --- sleeve centring (Ruling A35) --------------------------------------------------------------------------------------
# A sleeve is re-centred on its arm in the rigged space, before the clearance pass. The mesher may draw a sleeve off
# its arm: Kai's leather jacket came from two views that disagree on the sleeves' reach, and the mesher bent the
# RIGHT sleeve back — its forearm ring centred 4.9 cm behind the forearm, 21 % of the forearm sleeve more than 4 cm
# off the arm (and off the skin), the forearm's front out of the sleeve; the left sleeve sat within 1 cm. Per
# station (``SLEEVE_STATION_M`` along the arm chain from the shoulder joint, ``limb_frames``) the centre of the
# sleeve ring (the vertices the transfer gave mostly to that arm, the mid-range of their 2nd - 98th percentile in the
# plane across the arm) is compared with the centre of the ARM'S OWN cross-section there (the body vertices
# dominated by that arm's bones) — not the joint line, which stands 1 - 2 cm above the skin centre on the generated
# arms (centred on it a sleeve's top would be pushed into the arm). Whatever the offset has beyond
# ``SLEEVE_SLACK_M`` (the drape of a loose sleeve in the T-pose keeps its place) is taken back; a station without a
# closed ring (fewer than ``SLEEVE_RING_MIN`` vertices, or fewer than ``SLEEVE_RING_SECTORS`` of 8 directions around
# its own centre occupied) takes its neighbours' correction. The correction ramps in from the shoulder joint to the
# middle of the upper arm (``SLEEVE_RAMP_SHARE``: the armhole stays where the trunk holds it), scales with the
# vertex's share of the arm in the transfer's weights (the blend into the shoulder) and is smoothed over the mesh
# (``SLEEVE_SMOOTH_PASSES``). The gate behind it is ``garment_source.check_sleeves``.
SLEEVE_STATION_M = 0.02
SLEEVE_SLACK_M = 0.01
SLEEVE_RING_MIN = 12
SLEEVE_RING_SECTORS = 6
SLEEVE_RAMP_SHARE = 0.5
SLEEVE_SMOOTH_PASSES = 10
SLEEVE_ARM_SHARE = 0.5


def _arm_columns(joint_names, side: str) -> List[int]:
    """Skin columns of one arm chain (``_donor_parts``' rule: the side's bones naming an arm or a hand)."""
    from app.core.rig_contract import norm_bone_name
    return [i for i, n in enumerate(joint_names)
            if norm_bone_name(n).startswith(side) and any(t in norm_bone_name(n) for t in ("arm", "hand"))]


def _chain_coords(Y: np.ndarray, pts: np.ndarray, reference) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(s, seg, a, b)`` of the points ``Y`` against the polyline ``pts``: the arc length along it of the nearest
    point (the first segment extended backwards, the last forwards), its segment and the two coordinates across
    that segment (``_segment_frame`` axes v, w)."""
    nseg = len(pts) - 1
    frames = [_segment_frame(pts[i], pts[i + 1], reference) for i in range(nseg)]
    cum = np.concatenate([[0.0], np.cumsum([f[3] for f in frames])])
    best = np.full(len(Y), np.inf)
    s = np.zeros(len(Y))
    seg = np.zeros(len(Y), np.int64)
    a = np.zeros(len(Y))
    b = np.zeros(len(Y))
    for i, (u, v, w, length) in enumerate(frames):
        rel = Y - pts[i]
        t = rel @ u
        tc = np.clip(t, -np.inf if i == 0 else 0.0, np.inf if i == nseg - 1 else length)
        radial = rel - tc[:, None] * u
        d = np.linalg.norm(radial, axis=1)
        m = d < best
        best[m], s[m], seg[m] = d[m], cum[i] + tc[m], i
        a[m], b[m] = (rel[m] - t[m, None] * u) @ v, (rel[m] - t[m, None] * u) @ w
    return s, seg, a, b


def _ring_centre(a: np.ndarray, b: np.ndarray, closed: bool) -> Optional[np.ndarray]:
    """The mid-range centre of one station's ring (2nd - 98th percentile); None for too few points or, with
    ``closed``, a ring open on more than ``8 - SLEEVE_RING_SECTORS`` of 8 directions around that centre."""
    if len(a) < SLEEVE_RING_MIN:
        return None
    c = np.array([0.5 * (np.percentile(a, 2) + np.percentile(a, 98)), 0.5 * (np.percentile(b, 2) + np.percentile(b, 98))])
    if closed:
        sectors = ((np.arctan2(b - c[1], a - c[0]) + np.pi) / (2 * np.pi) * 8).astype(int) % 8
        if len(np.unique(sectors)) < SLEEVE_RING_SECTORS:
            return None
    return c


def center_sleeves(X: np.ndarray, Wg: np.ndarray, body: BodyMesh, *, adjacency=None,
                   sides: Sequence[str] = ("left", "right")) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Re-centre the sleeves of ``X`` (rigged space; ``Wg`` the transfer's weights over ``body``'s joints) on the
    arms of the rigged ``body`` (block above). ``(X, report {side: {stations, offset_max_m, shift_max_m}})``;
    an arm without sleeve vertices is left alone and not reported. ``sides``: the arms to re-centre (Ruling A47:
    a sleeve laid onto its arm, ``fit_sleeve``, is not re-centred)."""
    X = np.asarray(X, np.float64)
    P = np.asarray(body.positions, np.float64)
    Wb = dense_weights(body)
    frames = limb_frames(body)
    D = np.zeros_like(X)
    report: Dict[str, Any] = {}
    for side in sides:
        frame = frames.get(f"{side}_arm")
        cols = _arm_columns(body.joint_names, side)
        if frame is None or not cols:
            continue
        share = Wg[:, cols].sum(1) if Wg.shape[1] > max(cols) else np.zeros(len(X))
        rows = np.nonzero(share > 1e-4)[0]
        ring = share[rows] > SLEEVE_ARM_SHARE
        if int(ring.sum()) < SLEEVE_RING_MIN:
            continue
        pts = np.asarray(frame["points"], np.float64)
        ref = frame["reference"]
        s, seg, a, b = _chain_coords(X[rows], pts, ref)
        arm = Wb[:, cols].sum(1) > SLEEVE_ARM_SHARE
        sa, _sega, aa, ba = _chain_coords(P[arm], pts, ref)
        top = float(max(s[ring].max(), 0.0))
        n = int(top // SLEEVE_STATION_M) + 1
        k = np.clip((s // SLEEVE_STATION_M).astype(int), -1, n - 1)
        ka = (sa // SLEEVE_STATION_M).astype(int)
        excess = np.full((n, 2), np.nan)
        offset_max = 0.0
        for i in range(n):
            m = ring & (k == i)
            c = _ring_centre(a[m], b[m], True)
            ma = ka == i
            ca = _ring_centre(aa[ma], ba[ma], False)
            if c is None or ca is None:
                continue
            d = c - ca
            norm = float(np.linalg.norm(d))
            offset_max = max(offset_max, norm)
            excess[i] = d * max(0.0, 1.0 - SLEEVE_SLACK_M / norm) if norm > 0 else 0.0
        ok = ~np.isnan(excess[:, 0])
        if not ok.any():
            continue
        idx = np.arange(n)
        excess = np.stack([np.interp(idx, idx[ok], excess[ok, j]) for j in range(2)], 1)
        padded = np.concatenate([excess[:1], excess, excess[-1:]])
        excess = 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]
        upper = float(np.linalg.norm(pts[1] - pts[0]))
        ramp = np.clip(s / max(SLEEVE_RAMP_SHARE * upper, 1e-6), 0.0, 1.0)
        e = excess[np.clip(k, 0, n - 1)]
        segframes = [_segment_frame(pts[i], pts[i + 1], ref) for i in range(len(pts) - 1)]
        V = np.stack([segframes[j][1] for j in seg])
        Wv = np.stack([segframes[j][2] for j in seg])
        D[rows] -= ((ramp * share[rows])[:, None] * (e[:, :1] * V + e[:, 1:] * Wv))
        report[side] = {"stations": int(ok.sum()), "offset_max_m": round(offset_max, 4)}
    if adjacency is not None and SLEEVE_SMOOTH_PASSES > 0 and np.any(D):
        D = _smooth(D, adjacency, SLEEVE_SMOOTH_PASSES)
    shift = np.linalg.norm(D, axis=1)
    for side in report:
        cols = _arm_columns(body.joint_names, side)
        on = Wg[:, cols].sum(1) > SLEEVE_ARM_SHARE
        report[side]["shift_max_m"] = round(float(shift[on].max()) if on.any() else 0.0, 4)
    return X + D, report


# --- sleeves laid onto the arm (Ruling A47) ----------------------------------------------------------------------------
# A generated sleeve may hang 8 - 17 degrees steeper than the arm, up to 8 cm toward the body at the wrist, and be no
# wider than the arm (spike 2026-11-14, ``a47-spike.md``: placed on the A-pose body, Kai's jacket / Kira's blazer —
# sleeve radius minus arm radius after re-centring p50 -0.2 .. +0.1 cm, 0.37 - 0.79 of the upper-arm sleeve inside
# the arm). The push-out then shoves the walls inside the arm out sideways and the front of the sleeve tears at the
# elbow and forearm (skin seen inside the sleeves, front + back: Kai 268 cm2, Kira 24 cm2); re-centring after the push
# (``center_sleeves``) comes too late, widening about the arm axis by 10 / 20 % leaves the holes.
#
# "Fitted to the arm" (``fit_sleeve``): every sleeve vertex of the PRE-PUSH placement, carried into the bind space by
# the transfer's own skinning, is taken in the arm's cylindrical coordinates — its arc length along the arm chain, its
# angle and distance around the sleeve's OWN centre line (per ``SLEEVE_STATION_M`` station the mid-range centre of
# its ring) — and rebuilt around the rigged arm: angle kept, radius = the arm's own radius in that direction
# (``_ArmSections``: per station x ``SLEEVE_SECTORS`` directions the median distance of the arm's skin vertices from
# the arm's centre) + ``SLEEVE_FIT_CLEAR_M`` + ``SLEEVE_FIT_DETAIL`` of the vertex's own radial detail (its distance
# minus the ring's median; the folds). The change blends in along the arm between ``SLEEVE_FIT_BLEND_M`` (from the
# shoulder joint) and with the vertex's share of the arm in the transfer's weights; the displacement is then carried
# harmonically into the garment within ``SLEEVE_BAND_M`` of the moved vertices (the armhole and the side seam: the
# spike's straight blend left stretched shards under the armpit where it met torso vertices that did not move), and
# the shards still left against the pre-push placement (``sleeve_shards``) are relaxed — again after the rigged
# clearance pass, which may draw new ones; the rest is gated (``CLOTHING_GATES`` ``sleeve_shards``). The texture
# and the UVs are the generator's. Measured in the spike on Kai's jacket / Kira's blazer: skin seen in the sleeves
# 268 -> 30 cm2 and 24 -> 7 cm2; posed (arm down 60 deg, elbow 90 deg) inside share 0.032 / 0.011 against 0.028 /
# 0.008 as generated; 6 mm clearance went inside more often posed (0.052 / 0.027).
#
# The choice per sleeve (``SLEEVE_CHOICES``, the piece's fit settings): "generated" = as generated, re-centred
# (``center_sleeves``, today's fit); "wider" = that, then ``SLEEVE_WIDER`` radially about the arm's centre;
# "fitted" = ``fit_sleeve``; "auto" = "fitted" when the measured sleeve (``measure_sleeve``, on the pre-push
# placement) sits more than ``SLEEVE_AUTO_OFFSET_M`` off the arm's centre at a station beyond the armhole, its median
# room around the arm is below ``SLEEVE_AUTO_CLEAR_M``, or more than ``SLEEVE_AUTO_INSIDE`` of it lies inside the arm —
# else "generated" (a loose or puffy sleeve keeps its volume).
SLEEVE_CHOICES: Tuple[str, ...] = ("auto", "generated", "wider", "fitted")
SLEEVE_FIT_CLEAR_M = 0.012
SLEEVE_FIT_DETAIL = 0.3
SLEEVE_FIT_BLEND_M = (0.03, 0.10)
SLEEVE_WIDER = 1.2
SLEEVE_AUTO_OFFSET_M = 0.02
SLEEVE_AUTO_CLEAR_M = 0.012
SLEEVE_AUTO_INSIDE = 0.20
SLEEVE_SECTORS = 16
SLEEVE_BAND_M = 0.06
SLEEVE_BAND_PASSES = 150
#: The area ratio beyond which a triangle of the moved region counts as stretched (reported, ``sleeve_stretch``).
SLEEVE_STRETCH_RATIO = 3.0
SLEEVE_RELAX_PASSES = 10
SLEEVE_RELAX_ROUNDS = 6
#: Clearance (metres) below which a torso vertex of the fitted piece lies tight (``torso_tight_share``).
TORSO_TIGHT_M = 0.015
TORSO_MIN_SHARE = 0.10


def _chain_param(Y: np.ndarray, pts: np.ndarray, reference) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(s, seg, a, b)`` of the points ``Y`` against the polyline ``pts`` like ``_chain_coords``, but ``s`` is the
    UNCLAMPED arc length (``cum[seg]`` + the position along that segment), so ``_chain_point`` rebuilds ``Y`` exactly."""
    nseg = len(pts) - 1
    frames = [_segment_frame(pts[i], pts[i + 1], reference) for i in range(nseg)]
    cum = np.concatenate([[0.0], np.cumsum([f[3] for f in frames])])
    best = np.full(len(Y), np.inf)
    s, a, b = np.zeros(len(Y)), np.zeros(len(Y)), np.zeros(len(Y))
    seg = np.zeros(len(Y), np.int64)
    for i, (u, v, w, length) in enumerate(frames):
        rel = Y - pts[i]
        t = rel @ u
        tc = np.clip(t, -np.inf if i == 0 else 0.0, np.inf if i == nseg - 1 else length)
        d = np.linalg.norm(rel - tc[:, None] * u, axis=1)
        m = d < best
        best[m], seg[m], s[m] = d[m], i, cum[i] + t[m]
        perp = rel[m] - t[m, None] * u
        a[m], b[m] = perp @ v, perp @ w
    return s, seg, a, b


def _chain_point(pts: np.ndarray, reference, s: np.ndarray, seg: np.ndarray, a: np.ndarray, b: np.ndarray
                 ) -> np.ndarray:
    """The inverse of ``_chain_param``."""
    nseg = len(pts) - 1
    frames = [_segment_frame(pts[i], pts[i + 1], reference) for i in range(nseg)]
    cum = np.concatenate([[0.0], np.cumsum([f[3] for f in frames])])
    U = np.stack([frames[j][0] for j in seg])
    V = np.stack([frames[j][1] for j in seg])
    Wv = np.stack([frames[j][2] for j in seg])
    return np.asarray(pts, np.float64)[seg] + (s - cum[seg])[:, None] * U + a[:, None] * V + b[:, None] * Wv


def _fill_stations(values: np.ndarray, ok: np.ndarray) -> Optional[np.ndarray]:
    """Rows of ``values`` (stations) without ``ok`` interpolated from the others along the station index (held at
    the ends), then smoothed 1-2-1; None without any ``ok`` row."""
    if not ok.any():
        return None
    idx = np.arange(len(values))
    flat = values.reshape(len(values), -1)
    out = np.stack([np.interp(idx, idx[ok], flat[ok, j]) for j in range(flat.shape[1])], 1)
    padded = np.concatenate([out[:1], out, out[-1:]])
    out = 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]
    return out.reshape(values.shape)


def _station_value(table: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Linear interpolation of a per-station table (station ``i`` centred at ``(i + 0.5) * SLEEVE_STATION_M``,
    held beyond both ends) at the arc lengths ``s``."""
    x = (np.asarray(s, np.float64) / SLEEVE_STATION_M) - 0.5
    i0 = np.clip(np.floor(x).astype(np.int64), 0, len(table) - 1)
    i1 = np.clip(i0 + 1, 0, len(table) - 1)
    f = np.clip(x - np.floor(x), 0.0, 1.0)
    f = np.where(x < 0, 0.0, np.where(x > len(table) - 1, 0.0, f))
    shape = (-1,) + (1,) * (table.ndim - 1)
    return table[i0] * (1 - f).reshape(shape) + table[i1] * f.reshape(shape)


@dataclass
class _ArmSections:
    """One rigged arm in cylindrical stations: the chain (``pts``, ``reference``, segment lengths ``cum``), per
    station (0 at the shoulder joint, ``SLEEVE_STATION_M`` apart) the arm's centre in the plane across the chain and
    its radius in ``SLEEVE_SECTORS`` directions around that centre."""
    pts: np.ndarray
    reference: Any
    cum: np.ndarray
    centres: np.ndarray          # (n, 2)
    radii: np.ndarray            # (n, SLEEVE_SECTORS)

    def centre(self, s: np.ndarray) -> np.ndarray:
        return _station_value(self.centres, s)

    def radius(self, s: np.ndarray, theta: np.ndarray) -> np.ndarray:
        """The arm's radius at arc length ``s`` toward ``theta`` (bilinear over stations x sectors)."""
        table = _station_value(self.radii, s)                     # (m, sectors)
        x = (np.asarray(theta, np.float64) + np.pi) / (2 * np.pi) * SLEEVE_SECTORS - 0.5
        j0 = np.floor(x).astype(np.int64) % SLEEVE_SECTORS
        j1 = (j0 + 1) % SLEEVE_SECTORS
        f = x - np.floor(x)
        rows = np.arange(len(table))
        return table[rows, j0] * (1 - f) + table[rows, j1] * f

    def where(self, s: float) -> str:
        """The part of the arm at arc length ``s``: ``upper arm``, ``forearm`` or ``wrist`` (beyond the wrist joint)."""
        if len(self.cum) > 1 and s < self.cum[1]:
            return "upper arm"
        if len(self.cum) > 2 and s < self.cum[2]:
            return "forearm"
        return "wrist"


def arm_sections(body: BodyMesh, side: str, *, frames: Optional[Dict[str, Dict[str, Any]]] = None,
                 Wb: Optional[np.ndarray] = None) -> Optional[_ArmSections]:
    """``_ArmSections`` of the ``side`` arm of the rigged ``body`` from its skin vertices dominated by that arm
    (arm-chain weight share > ``SLEEVE_ARM_SHARE``) from the shoulder joint outward; None without the arm chain."""
    frames = limb_frames(body) if frames is None else frames
    frame = frames.get(f"{side}_arm")
    cols = _arm_columns(body.joint_names, side)
    if frame is None or not cols:
        return None
    Wb = dense_weights(body) if Wb is None else Wb
    P = np.asarray(body.positions, np.float64)
    arm = Wb[:, cols].sum(1) > SLEEVE_ARM_SHARE
    pts = np.asarray(frame["points"], np.float64)
    ref = frame["reference"]
    s, _seg, a, b = _chain_param(P[arm], pts, ref)
    keep = s >= 0
    s, a, b = s[keep], a[keep], b[keep]
    if len(s) < SLEEVE_RING_MIN:
        return None
    n = int(s.max() // SLEEVE_STATION_M) + 1
    k = np.clip((s // SLEEVE_STATION_M).astype(int), 0, n - 1)
    centres = np.full((n, 2), np.nan)
    radii = np.full((n, SLEEVE_SECTORS), np.nan)
    for i in range(n):
        m = k == i
        c = _ring_centre(a[m], b[m], False)
        if c is None:
            continue
        centres[i] = c
        theta = np.arctan2(b[m] - c[1], a[m] - c[0])
        r = np.hypot(a[m] - c[0], b[m] - c[1])
        sector = ((theta + np.pi) / (2 * np.pi) * SLEEVE_SECTORS).astype(int) % SLEEVE_SECTORS
        row = np.full(SLEEVE_SECTORS, np.nan)
        for j in range(SLEEVE_SECTORS):
            if (sector == j).any():
                row[j] = float(np.median(r[sector == j]))
        okj = ~np.isnan(row)
        if okj.sum() >= 3:
            idx = np.arange(SLEEVE_SECTORS)
            radii[i] = np.interp(idx, idx[okj], row[okj], period=SLEEVE_SECTORS)
    okc = ~np.isnan(centres[:, 0])
    okr = ~np.isnan(radii[:, 0])
    centres_f, radii_f = _fill_stations(centres, okc), _fill_stations(radii, okr)
    if centres_f is None or radii_f is None:
        return None
    segs = [_segment_frame(pts[i], pts[i + 1], ref)[3] for i in range(len(pts) - 1)]
    return _ArmSections(pts=pts, reference=ref, cum=np.concatenate([[0.0], np.cumsum(segs)]),
                        centres=centres_f, radii=radii_f)


def _sleeve_rings(s: np.ndarray, a: np.ndarray, b: np.ndarray, ring: np.ndarray, n: int
                  ) -> Tuple[Optional[np.ndarray], np.ndarray, np.ndarray]:
    """The sleeve's own centre line per station (closed rings only, the rest interpolated, smoothed), which stations
    had a closed ring, and the ring's median radius about that centre per station -> ``(centres, closed, radius)``;
    centres None without a closed ring."""
    k = np.clip((s // SLEEVE_STATION_M).astype(int), 0, n - 1)
    centres = np.full((n, 2), np.nan)
    for i in range(n):
        m = ring & (k == i) & (s >= 0)
        c = _ring_centre(a[m], b[m], True)
        if c is not None:
            centres[i] = c
    closed = ~np.isnan(centres[:, 0])
    filled = _fill_stations(centres, closed)
    if filled is None:
        return None, closed, np.zeros(n)
    c = _station_value(filled, s)
    r = np.hypot(a - c[:, 0], b - c[:, 1])
    radius = np.full(n, np.nan)
    for i in range(n):
        m = ring & (k == i)
        if m.sum() >= 3:
            radius[i] = float(np.median(r[m]))
    rf = _fill_stations(radius[:, None], ~np.isnan(radius))
    return filled, closed, (rf[:, 0] if rf is not None else np.zeros(n))


def measure_sleeve(Xs: np.ndarray, share: np.ndarray, arm: _ArmSections, inside: Optional[np.ndarray] = None
                   ) -> Optional[Dict[str, Any]]:
    """How one sleeve sits on its arm (block above): ``Xs`` the garment in the bind space (the pre-push placement),
    ``share`` per vertex the transfer weight on that arm's chain, ``inside`` per vertex whether it lies inside the
    body. Over the sleeve's ring (``share`` > ``SLEEVE_ARM_SHARE``) beyond the armhole (stations from
    ``SLEEVE_FIT_BLEND_M[1]`` on, the cuff's last station left out): ``{offset_max_m, offset_where (upper arm /
    forearm / wrist), clear_p10_m, clear_p50_m, clear_p90_m (its distance from its own centre minus the arm's
    radius in that direction), inside_share, stations, vertices}``. None without a closed ring there."""
    rows = np.nonzero(share > 1e-4)[0]
    ring_all = share[rows] > SLEEVE_ARM_SHARE
    if int(ring_all.sum()) < SLEEVE_RING_MIN:
        return None
    s, _seg, a, b = _chain_param(Xs[rows], arm.pts, arm.reference)
    top = float(s[ring_all].max())
    n = max(int(top // SLEEVE_STATION_M) + 1, 1)
    centres, closed, _radius = _sleeve_rings(s, a, b, ring_all, n)
    if centres is None:
        return None
    first = int(np.ceil(SLEEVE_FIT_BLEND_M[1] / SLEEVE_STATION_M))
    last = max(int(np.nonzero(closed)[0].max()) if closed.any() else -1, first)
    stations = [i for i in range(first, last) if closed[i]]
    if not stations:
        return None
    centre_s = (np.asarray(stations) + 0.5) * SLEEVE_STATION_M
    offset = np.linalg.norm(centres[stations] - arm.centre(centre_s), axis=1)
    worst = int(offset.argmax())
    sel = ring_all & (s >= first * SLEEVE_STATION_M) & (s < last * SLEEVE_STATION_M)
    c = _station_value(centres, s[sel])
    theta = np.arctan2(b[sel] - c[:, 1], a[sel] - c[:, 0])
    room = np.hypot(a[sel] - c[:, 0], b[sel] - c[:, 1]) - arm.radius(s[sel], theta)
    p10, p50, p90 = (np.percentile(room, (10, 50, 90)) if len(room) else (np.nan,) * 3)
    inner = float(np.asarray(inside)[rows[sel]].mean()) if inside is not None and sel.any() else float("nan")
    return {"offset_max_m": round(float(offset[worst]), 4), "offset_where": arm.where(float(centre_s[worst])),
            "clear_p10_m": round(float(p10), 4), "clear_p50_m": round(float(p50), 4),
            "clear_p90_m": round(float(p90), 4), "inside_share": round(inner, 4),
            "stations": len(stations), "vertices": int(sel.sum())}


def auto_sleeve(numbers: Optional[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """The Auto choice for one measured sleeve (``measure_sleeve``) -> ``(choice, why)``: "fitted" when any rule of
    the block above holds, each that holds in ``why`` (``{rule: offset, cm, where}`` / ``{rule: room, cm}`` /
    ``{rule: inside, percent}``); else "generated" with the numbers that kept it (``rule: fits``). No numbers (no
    sleeve measured): "generated", ``why`` empty."""
    if not numbers:
        return "generated", []
    why: List[Dict[str, Any]] = []
    if numbers["offset_max_m"] > SLEEVE_AUTO_OFFSET_M:
        why.append({"rule": "offset", "cm": round(numbers["offset_max_m"] * 100, 1), "where": numbers["offset_where"]})
    if math.isfinite(numbers["clear_p50_m"]) and numbers["clear_p50_m"] < SLEEVE_AUTO_CLEAR_M:
        why.append({"rule": "room", "cm": round(numbers["clear_p50_m"] * 100, 1)})
    if math.isfinite(numbers["inside_share"]) and numbers["inside_share"] > SLEEVE_AUTO_INSIDE:
        why.append({"rule": "inside", "percent": int(round(numbers["inside_share"] * 100))})
    if why:
        return "fitted", why
    return "generated", [{"rule": "fits", "cm": round(numbers["offset_max_m"] * 100, 1),
                          "room_cm": round(numbers["clear_p50_m"] * 100, 1)}]


def sleeve_reason_text(choice: str, why: List[Dict[str, Any]]) -> str:
    """The plain-words reason of an Auto choice (``auto_sleeve``) — the English record text; the Wardrobe composes
    the same words from ``why`` through its translation layer."""
    parts = []
    for item in why:
        if item["rule"] == "offset":
            parts.append(f"the sleeve sits {item['cm']:g} cm off the {item['where']}")
        elif item["rule"] == "room":
            parts.append("it is as thin as the arm" if item["cm"] <= 0.3
                         else f"it is only {item['cm']:g} cm wider than the arm")
        elif item["rule"] == "inside":
            parts.append(f"{item['percent']} % of it lies inside the arm")
        elif item["rule"] == "fits":
            parts.append(f"the sleeve sits on the arm ({item['cm']:g} cm off its centre, "
                         f"{item['room_cm']:g} cm of room)")
    label = {"fitted": "Fitted to the arm", "generated": "As generated"}.get(choice, choice)
    return f"Auto -> {label}" + (": " + " and ".join(parts) if parts else "")


def fit_sleeve(X: np.ndarray, Xs: np.ndarray, share: np.ndarray, arm: _ArmSections) -> np.ndarray:
    """The displacement (rows of ``X``) that lays one sleeve onto its arm (block above): ``X`` the garment in the
    bind space now, ``Xs`` the same vertices as placed before the push (their sleeve shape), ``share`` per vertex
    the transfer weight on that arm's chain. Rows of vertices off the sleeve are zero; the blend
    (``SLEEVE_FIT_BLEND_M`` x ``share``) is in it, the band smoothing (``blend_sleeves``) is not."""
    D = np.zeros_like(X)
    rows = np.nonzero(share > 1e-4)[0]
    ring = share[rows] > SLEEVE_ARM_SHARE
    if int(ring.sum()) < SLEEVE_RING_MIN:
        return D
    s, seg, a, b = _chain_param(Xs[rows], arm.pts, arm.reference)
    n = max(int(max(float(s[ring].max()), 0.0) // SLEEVE_STATION_M) + 1, 1)
    centres, _closed, radius = _sleeve_rings(s, a, b, ring, n)
    if centres is None:
        return D
    c = _station_value(centres, s)
    theta = np.arctan2(b - c[:, 1], a - c[:, 0])
    detail = np.hypot(a - c[:, 0], b - c[:, 1]) - _station_value(radius, s)
    r = (arm.radius(s, theta) + SLEEVE_FIT_CLEAR_M
         + np.maximum(SLEEVE_FIT_DETAIL * detail, -0.5 * SLEEVE_FIT_CLEAR_M))
    ca = arm.centre(s)
    T = _chain_point(arm.pts, arm.reference, s, seg, ca[:, 0] + r * np.cos(theta), ca[:, 1] + r * np.sin(theta))
    lo, hi = SLEEVE_FIT_BLEND_M
    beta = np.clip((s - lo) / (hi - lo), 0.0, 1.0) * np.clip(share[rows], 0.0, 1.0)
    D[rows] = beta[:, None] * (T - X[rows])
    return D


def widen_sleeve(X: np.ndarray, share: np.ndarray, arm: _ArmSections, scale: float = SLEEVE_WIDER) -> np.ndarray:
    """The displacement that widens one (re-centred) sleeve by ``scale`` radially about its arm's centre, blended in
    like ``fit_sleeve``."""
    D = np.zeros_like(X)
    rows = np.nonzero(share > 1e-4)[0]
    if not len(rows):
        return D
    s, seg, a, b = _chain_param(X[rows], arm.pts, arm.reference)
    ca = arm.centre(s)
    T = _chain_point(arm.pts, arm.reference, s, seg, ca[:, 0] + scale * (a - ca[:, 0]),
                     ca[:, 1] + scale * (b - ca[:, 1]))
    lo, hi = SLEEVE_FIT_BLEND_M
    beta = np.clip((s - lo) / (hi - lo), 0.0, 1.0) * np.clip(share[rows], 0.0, 1.0)
    D[rows] = beta[:, None] * (T - X[rows])
    return D


def _longest_edge(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    return np.maximum.reduce([np.linalg.norm(P[F[:, i]] - P[F[:, (i + 1) % 3]], axis=1) for i in range(3)])


def sleeve_shards(X: np.ndarray, X0: np.ndarray, faces, region: np.ndarray) -> np.ndarray:
    """Per face of ``faces``: a shard (block above) — it touches ``region``, its longest edge in ``X`` exceeds
    ``SLEEVE_SHARD_M`` and ``SLEEVE_SHARD_RATIO`` times its longest edge in ``X0`` (the pre-push placement)."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    e = _longest_edge(X, F)
    return (np.asarray(region, bool)[F].any(1) & (e > SLEEVE_SHARD_M)
            & (e > SLEEVE_SHARD_RATIO * np.maximum(_longest_edge(X0, F), 1e-9)))


def relax_sleeve_region(Y: np.ndarray, X0: np.ndarray, faces, adjacency, region: np.ndarray) -> int:
    """Relax (in place) the vertices of the shards of ``region`` (``sleeve_shards`` against ``X0``):
    ``SLEEVE_RELAX_PASSES`` Laplacian passes, the shards found anew for up to ``SLEEVE_RELAX_ROUNDS`` rounds -> the
    number of vertices relaxed. Only the shards' own vertices move — relaxing every triangle whose AREA grew (the
    crushed folds of the source opened up) or a ring around them pulled the neighbours long (Kai's jacket: 10 shards
    before, 24 - 34 after)."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    A, deg = adjacency
    loose_all = np.zeros(len(Y), bool)
    for _ in range(SLEEVE_RELAX_ROUNDS):
        bad = sleeve_shards(Y, X0, F, region)
        if not bad.any():
            break
        loose = np.zeros(len(Y), bool)
        loose[F[bad].ravel()] = True
        loose_all |= loose
        for _ in range(SLEEVE_RELAX_PASSES):
            Y[loose] = 0.5 * Y[loose] + 0.5 * ((A @ Y) / deg)[loose]
    return int(loose_all.sum())


def blend_sleeves(X: np.ndarray, D: np.ndarray, Xs: np.ndarray, faces, adjacency
                  ) -> Tuple[np.ndarray, Dict[str, Any], np.ndarray]:
    """Apply the sleeve displacement ``D`` (``fit_sleeve`` / ``widen_sleeve`` rows) to ``X`` with its edge carried
    into the garment (block above): the moved vertices keep their (blended) displacement, every other vertex within
    ``SLEEVE_BAND_M`` (along the mesh) of a moved one takes the harmonic blend between them and the unmoved rest
    (``SLEEVE_BAND_PASSES`` Jacobi passes); then the shards left against the pre-push placement ``Xs`` are relaxed
    (``relax_sleeve_region``). ``(X', report {band_vertices,
    relaxed_vertices}, region)`` — ``region`` the vertices the step may have moved."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    moved = np.linalg.norm(D, axis=1) > 1e-6
    report = {"band_vertices": 0, "relaxed_vertices": 0}
    if not moved.any():
        return X, report, moved
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    n = len(X)
    length = np.maximum(np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1), 1e-9)
    graph = coo_matrix((length, (E[:, 0], E[:, 1])), shape=(n, n)).tocsr()
    dist = dijkstra(graph, directed=False, indices=np.nonzero(moved)[0], min_only=True, limit=SLEEVE_BAND_M)
    A, deg = adjacency
    region = np.isfinite(dist)
    free = region & ~moved
    report["band_vertices"] = int(free.sum())
    out = D.copy()
    for _ in range(SLEEVE_BAND_PASSES):
        out[free] = ((A @ out) / deg)[free]
    Y = X + out
    report["relaxed_vertices"] = relax_sleeve_region(Y, Xs, F, adjacency, region)
    return Y, report, region


def sleeve_stretch(X: np.ndarray, X0: np.ndarray, faces, region: np.ndarray) -> Dict[str, Any]:
    """Area ratio of the triangles of ``faces`` touching ``region`` (vertex mask) in ``X`` against ``X0`` (the
    pre-push placement in the bind space): ``{faces, over (beyond SLEEVE_STRETCH_RATIO), p99, max}``."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    tri = np.asarray(region, bool)[F].any(1)
    if not tri.any():
        return {"faces": 0, "over": 0, "shards": 0, "p99": 1.0, "max": 1.0}
    ratio = triangle_areas(X, F[tri]) / np.maximum(triangle_areas(X0, F[tri]), 1e-12)
    return {"faces": int(tri.sum()), "over": int((ratio > SLEEVE_STRETCH_RATIO).sum()),
            "shards": int(sleeve_shards(X, X0, F, region).sum()),
            "p99": round(float(np.percentile(ratio, 99)), 3), "max": round(float(ratio.max()), 3)}


def sleeve_choices(settings: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """``{left, right}`` sleeve choices of a piece's fit settings (``sleeves_left`` / ``sleeves_right``); a missing
    or unknown value is "auto"."""
    settings = settings or {}
    out = {}
    for side in ("left", "right"):
        value = settings.get(f"sleeves_{side}")
        out[side] = value if value in SLEEVE_CHOICES else "auto"
    return out


def _arm_share(Wg: np.ndarray, joint_names, side: str) -> np.ndarray:
    cols = _arm_columns(joint_names, side)
    if not cols or Wg.shape[1] <= max(cols):
        return np.zeros(len(Wg))
    return Wg[:, cols].sum(1)


def trunk_band(X: np.ndarray, Wg: np.ndarray, body: BodyMesh) -> np.ndarray:
    """The trunk of a fitted piece (``torso_tight_share``): its vertices not carried by an arm, between the hips joint
    and the shoulder joints of ``body`` — a leg or a sleeve is meant to sit close and is not counted. Empty when that is
    less than ``TORSO_MIN_SHARE`` of the piece (trousers: the waistband alone)."""
    from app.core.rig_contract import norm_bone_name
    joints = {norm_bone_name(k): np.asarray(v, np.float64) for k, v in (body.joint_positions or {}).items()}
    on_arm = _arm_share(Wg, body.joint_names, "left") + _arm_share(Wg, body.joint_names, "right")
    trunk = on_arm <= SLEEVE_ARM_SHARE
    hips = joints.get("hips")
    shoulders = [joints[k][1] for k in ("leftarm", "rightarm") if k in joints]
    if hips is not None and shoulders:
        trunk &= (X[:, 1] > hips[1]) & (X[:, 1] < min(shoulders))
    if not len(X) or trunk.mean() < TORSO_MIN_SHARE:
        return np.zeros(len(X), bool)
    return trunk


def _front_back_gaps(X: np.ndarray, d: np.ndarray, trunk: np.ndarray, body_P) -> Dict[str, Optional[float]]:
    """Ruling A68: ``trunk_front_gap_p50_m`` / ``trunk_back_gap_p50_m`` — the median clearance ``d`` of the trunk
    vertices in front of / behind the trunk (``front_back_rows`` about the torso axis of the piece ``X`` on the body
    ``body_P``, ``torso_axis``); None for an empty sector or without a trunk."""
    out: Dict[str, Optional[float]] = {"trunk_front_gap_p50_m": None, "trunk_back_gap_p50_m": None}
    if not trunk.any():
        return out
    try:
        cx, cz = torso_axis(X, body_P, height_u=float(np.ptp(np.asarray(body_P)[:, 1])))
    except ValueError:
        return out
    front, back = front_back_rows(X[trunk], cx, cz)
    dt = d[trunk]
    for key, rows in (("trunk_front_gap_p50_m", front), ("trunk_back_gap_p50_m", back)):
        out[key] = float(np.median(dt[rows])) if rows.any() else None
    return out


def place_sleeves(X: np.ndarray, Xs: np.ndarray, Wg: np.ndarray, body: BodyMesh, *, faces, adjacency,
                  choices: Dict[str, str], inside: Optional[np.ndarray] = None
                  ) -> Tuple[np.ndarray, Dict[str, Any], np.ndarray, np.ndarray]:
    """Per side the sleeve choice (block above; ``choices`` from ``sleeve_choices``), measured on ``Xs`` (the
    pre-push placement in the bind space; ``inside`` per vertex whether it lies inside the body there) and applied to
    ``X`` -> ``(X', report {side: {setting, applied, why, reason, numbers, shift_max_m}}, fitted, region)`` —
    ``fitted`` the vertex mask the fit laid onto the arm (their placement push is discarded: ``clothing_metrics``
    counts them as not pushed), ``region`` the vertices the placement may have moved (``blend_sleeves``).
    "generated" / "wider" re-centre that side first (``center_sleeves``)."""
    X = np.asarray(X, np.float64)
    Xs = np.asarray(Xs, np.float64)
    frames = limb_frames(body)
    Wb = dense_weights(body)
    report: Dict[str, Any] = {}
    applied: Dict[str, str] = {}
    arms: Dict[str, _ArmSections] = {}
    shares: Dict[str, np.ndarray] = {}
    for side in ("left", "right"):
        share = _arm_share(Wg, body.joint_names, side)
        if int((share > SLEEVE_ARM_SHARE).sum()) < SLEEVE_RING_MIN:
            continue
        arm = arm_sections(body, side, frames=frames, Wb=Wb)
        if arm is None:
            continue
        arms[side], shares[side] = arm, share
        numbers = measure_sleeve(Xs, share, arm, inside)
        setting = choices.get(side, "auto")
        why: List[Dict[str, Any]] = []
        if setting == "auto":
            choice, why = auto_sleeve(numbers)
        else:
            choice = setting
        applied[side] = choice
        report[side] = {"setting": setting, "applied": choice, "why": why,
                        "reason": sleeve_reason_text(choice, why) if setting == "auto" else "",
                        "numbers": numbers}
    centred = [side for side, choice in applied.items() if choice in ("generated", "wider")]
    if centred:
        X, centre_report = center_sleeves(X, Wg, body, adjacency=adjacency, sides=centred)
        for side, rep in centre_report.items():
            report[side]["centring"] = rep
    D = np.zeros_like(X)
    fitted = np.zeros(len(X), bool)
    for side, choice in applied.items():
        if choice == "fitted":
            Ds = fit_sleeve(X, Xs, shares[side], arms[side])
            fitted |= (np.linalg.norm(Ds, axis=1) > 0) & (shares[side] > SLEEVE_ARM_SHARE)
        elif choice == "wider":
            Ds = widen_sleeve(X, shares[side], arms[side])
        else:
            continue
        D += Ds
        report[side]["shift_max_m"] = round(float(np.linalg.norm(Ds, axis=1).max()), 4)
    region = np.zeros(len(X), bool)
    if np.any(D):
        X, blend, region = blend_sleeves(X, D, Xs, faces, adjacency)
        report["blend"] = blend
    return X, report, fitted, region


# --- skin seen in the sleeves (Ruling A47, the arm light) --------------------------------------------------------------
# The fitted piece and its rigged body are drawn orthographically from the front and from the back (bind pose, the arms
# out) into depth buffers of ``SKIN_PX_M`` pixels; per side, the sleeve's outline (the pixels of its faces —
# vertices with more than ``SLEEVE_ARM_SHARE`` of their weight on that arm — holes filled, closed over
# ``SKIN_CLOSE_PX``) is where the sleeve should hide the arm, and every pixel of it where the BODY is the nearest
# surface is skin seen in the sleeve. Front + back, cm2 per side. The spike's numbers (``a47-spike.md``): Kai's jacket
# as generated 125 / 143, fitted to the arm 12 / 18; Kira's blazer 15 / 9 and 3 / 4. The light: green with none,
# yellow below ``SKIN_RED_CM2``, red from it.
SKIN_PX_M = 0.002
SKIN_CLOSE_PX = 2
SKIN_DEPTH_EPS_M = 0.001
SKIN_RED_CM2 = 30.0


def _raster(P: np.ndarray, F: np.ndarray, lo: np.ndarray, shape: Tuple[int, int], px: float, sign: float
            ) -> np.ndarray:
    """Nearest depth per pixel of the triangles ``F`` over ``P`` seen along -z (``sign`` 1: from the front, the
    largest z; -1: from the back) — barycentric samples at most half a pixel apart; -inf where nothing is."""
    h, w = shape
    depth = np.full(h * w, -np.inf)
    if not len(F):
        return depth.reshape(shape)
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    edge = np.maximum.reduce([np.linalg.norm((B - A)[:, :2], axis=1), np.linalg.norm((C - B)[:, :2], axis=1),
                              np.linalg.norm((A - C)[:, :2], axis=1)])
    steps = np.clip(np.ceil(edge / (0.5 * px)).astype(np.int64), 1, 64)
    for n in np.unique(steps):
        sel = np.nonzero(steps == n)[0]
        t = np.arange(n + 1) / n
        uv = np.array([(a, b) for a in t for b in t if a + b <= 1.0 + 1e-9])
        X = (A[sel, None] * (1.0 - uv.sum(1))[None, :, None] + B[sel, None] * uv[None, :, 0, None]
             + C[sel, None] * uv[None, :, 1, None]).reshape(-1, 3)
        col = np.floor((X[:, 0] - lo[0]) / px).astype(np.int64)
        row = np.floor((X[:, 1] - lo[1]) / px).astype(np.int64)
        ok = (col >= 0) & (col < w) & (row >= 0) & (row < h)
        np.maximum.at(depth, row[ok] * w + col[ok], sign * X[ok, 2])
    return depth.reshape(shape)


def sleeve_skin_seen(X: np.ndarray, F: np.ndarray, shares: Dict[str, np.ndarray], body: BodyMesh,
                     px: float = SKIN_PX_M) -> Dict[str, float]:
    """Skin seen inside each sleeve's outline (block above) of the garment ``X`` / ``F`` on the rigged ``body``:
    ``{side: cm2}`` for the sides of ``shares`` (per garment vertex its weight on that arm) that have a sleeve."""
    from scipy import ndimage
    X = np.asarray(X, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    P = np.asarray(body.positions, np.float64)
    Fb = np.asarray(body.faces, np.int64).reshape(-1, 3)
    out: Dict[str, float] = {}
    sleeves = {side: share[F].min(1) > SLEEVE_ARM_SHARE for side, share in shares.items()
               if (share[F].min(1) > SLEEVE_ARM_SHARE).sum() >= SLEEVE_RING_MIN}
    if not sleeves:
        return out
    lo = np.minimum(X.min(0), P.min(0))[:2] - 4 * px
    hi = np.maximum(X.max(0), P.max(0))[:2] + 4 * px
    shape = (int(np.ceil((hi[1] - lo[1]) / px)) + 1, int(np.ceil((hi[0] - lo[0]) / px)) + 1)
    disc = ndimage.generate_binary_structure(2, 1)
    for sign in (1.0, -1.0):
        body_d = _raster(P, Fb, lo, shape, px, sign)
        garment_d = _raster(X, F, lo, shape, px, sign)
        skin = np.isfinite(body_d) & (body_d > garment_d + SKIN_DEPTH_EPS_M)
        for side, faces in sleeves.items():
            outline = np.isfinite(_raster(X, F[faces], lo, shape, px, sign))
            outline = ndimage.binary_closing(outline, disc, iterations=SKIN_CLOSE_PX, border_value=0)
            outline = ndimage.binary_fill_holes(outline)
            out[side] = out.get(side, 0.0) + float((outline & skin).sum()) * px * px * 1e4
    return {side: round(cm2, 1) for side, cm2 in out.items()}


def arm_light(skin: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The arm light of a fit from its ``sleeve_skin_cm2`` (``{side: cm2}``): ``{state (green / yellow / red / none),
    sides {side: state}, worst_cm2}`` — green without skin seen (rounded to whole cm2), yellow below
    ``SKIN_RED_CM2``, red from it; ``none`` without a measured sleeve."""
    sides: Dict[str, str] = {}
    for side, cm2 in sorted((skin or {}).items()):
        if not isinstance(cm2, (int, float)) or isinstance(cm2, bool):
            continue
        sides[side] = "green" if round(cm2) <= 0 else ("yellow" if cm2 < SKIN_RED_CM2 else "red")
    order = ("none", "green", "yellow", "red")
    state = max(sides.values(), key=order.index) if sides else "none"
    worst = max((float(v) for v in (skin or {}).values() if isinstance(v, (int, float))), default=0.0)
    return {"state": state, "sides": sides, "worst_cm2": round(worst, 1)}


def transfer_skinned(Q, body_unrigged: BodyMesh, body_rigged: BodyMesh, *, faces, k: float, split_y: float,
                     idw_k: int = TRANSFER_IDW_K, clear_m: float = CLEAR_M, vox_m: float = VOX_M,
                     margin_m: float = SDF_MARGIN_M,
                     rigged_iterations: int = RIGGED_ITERATIONS,
                     limbs: Optional[Dict[str, Any]] = None, Q_pre=None,
                     sleeves: Optional[Dict[str, str]] = None,
                     ease_z: Optional[np.ndarray] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Carry welded clothing positions ``Q`` (unrigged units) into the rigged bind space (metres) by the body's own
    skinning -> ``(X, report)``. ``limbs`` (a refit, ``fit_clothing``): the source fit per welded vertex (``x0``,
    ``w0``, ``names0``, ``frames``, ``kinds``) — its limb part is aligned onto this body's limbs (``align_limbs``)
    before step 4.

    1. ``bone_transforms``: one rigid transform per bone, ``k * unrigged -> rigged``.
    2. Each garment vertex takes the inverse-distance blend (``idw_k`` nearest, ``w = 1 / max(d, 1e-4 / k)``) of the
       body weights of the ELIGIBLE unrigged body vertices around it — the same rule as ``transfer``: at or above
       ``split_y`` only forearm/hand donors are excluded (a sleeve rides the upper arm through the A -> T motion),
       below it every arm/shoulder bone (a skirt next to a hanging hand stays on the hips) — except on the SLEEVES
       (``sleeve_vertices``), which take the whole arm chain at any height, and their CUFFS (``sleeve_cuffs``,
       Ruling A35), which take their own arm's skin only. The blend is taken within
       ONE PART (``_donor_parts``: each arm chain, the rest) — the part whose skin is nearest to the garment vertex —
       so a sleeve hanging next to the torso is a sleeve and not a noisy mix of arm and torso.
    3. Linear blend skinning of ``k * Q`` with those weights (the body itself is skinned that way). A vertex far
       from the skin keeps its distance to the bone it rides (a rigid motion), the blend zone of a joint deforms like
       the skin under it — no tear between neighbours with different donors, nothing to smooth over. The fabric
       that bridged the closed armpit of the A-pose spans the open one in T-pose; ``relax_stretched`` spreads that
       stretch over its band.
    3b. The sleeves are placed per side (``place_sleeves``, Ruling A47; ``sleeves`` = ``sleeve_choices``, None =
       Auto on both): laid onto the arm (``fit_sleeve``) from their pre-push shape (``Q_pre``, the placement before
       the push-out, skinned by the same weights; a refit takes its limb-aligned sleeves, None = ``Q``), or
       re-centred on it (``center_sleeves``, Ruling A35) and, "wider", widened about it — after the limb alignment
       of a refit, so a sleeve the source left off its arm is taken back too. ``report["sleeves"]`` holds the choice
       and its numbers per side; ``report["sleeve_fitted"]`` (a vertex mask, not JSON — ``fit_clothing`` takes it
       out) the vertices laid onto the arm.
    4. The clearance pass on the rigged body (SDF in metres, ``rigged_iterations`` iterations, smoothed in the
       first ``RIGGED_SMOOTH_UNTIL``), side-kept (``push_kept``); a vertex the skinning buried on the wrong side
       starts on the nearest body surface of its own side (``_transfer_sides``, ``_side_projection``).
    5. Ruling A68: ``ease_z`` (per vertex, unrigged units — ``depth_shift`` of ``Q``) is added to the rigged z
       (times ``k``) as the last step: the depth allowance never changes which part a vertex rides or how the
       clearance pass moves it, and every number of the report is measured with it.
    """
    from scipy.spatial import cKDTree
    from app.core.rig_contract import norm_bone_name
    Q = np.asarray(Q, np.float64)
    Pb, Pr = body_unrigged.positions, body_rigged.positions
    adjacency = _adjacency(faces, len(Q))
    corr, uv_dist = uv_correspondence(body_unrigged, body_rigged)
    bones = bone_transforms(body_unrigged, body_rigged, corr, k)
    Wb = bones.fold_weights(dense_weights(body_rigged)[corr])
    Wb /= np.maximum(Wb.sum(1, keepdims=True), 1e-12)
    # Ruling A72: a body vertex whose UV match lies elsewhere on the rigged body donates its neighbour's skin.
    Wb, mismatched = trusted_donor_weights(Pb, Pr[corr], bones, Wb, k)

    def eligible(tokens) -> np.ndarray:
        cols = [i for i, n in enumerate(body_rigged.joint_names) if any(t in norm_bone_name(n) for t in tokens)]
        ok = Wb[:, cols].sum(1) < 0.2 if cols else np.ones(len(Pb), bool)
        candidates = np.nonzero(ok)[0]
        if len(candidates) == 0:
            raise ValueError("No body vertex is eligible for the garment transfer")
        return candidates

    parts = _donor_parts(Wb, body_rigged.joint_names)

    def blend(candidates, rows) -> np.ndarray:
        """Inverse-distance weights of the garment rows over the ``candidates`` of their nearest part."""
        best_d = np.full(len(rows), np.inf)
        out = np.zeros((len(rows), Wb.shape[1]))
        found = False
        for part in range(3):
            cand = candidates[parts[candidates] == part]
            if len(cand) == 0:
                continue
            found = True
            kk = min(idw_k, len(cand))
            dist, nn = cKDTree(Pb[cand]).query(Q[rows], k=kk, workers=fit_kernels.threads())
            dist, nn = dist.reshape(len(rows), -1), nn.reshape(len(rows), -1)
            w = 1.0 / np.maximum(dist, CLOTHING_IDW_EPS_M / k)
            w /= w.sum(1, keepdims=True)
            nearer = dist[:, 0] < best_d
            out[nearer] = np.einsum("nk,nkj->nj", w[nearer], Wb[cand[nn[nearer]]])
            best_d[nearer] = dist[nearer, 0]
        if not found:
            raise ValueError("No body vertex is eligible for the garment transfer")
        return out
    upper = Q[:, 1] >= split_y
    sleeve = sleeve_vertices(Q, Pb, parts, faces, upper)
    cuff = sleeve_cuffs(Q, Pb, parts, faces, upper, sleeve, k)
    Wg = np.zeros((len(Q), Wb.shape[1]))
    lower, top = ~upper & ~sleeve & (cuff == 0), upper & ~sleeve
    if lower.any():
        Wg[lower] = blend(eligible(_ARM_TOKENS), np.nonzero(lower)[0])
    if top.any():
        Wg[top] = blend(eligible(_LOWER_ARM_TOKENS), np.nonzero(top)[0])
    if sleeve.any():
        Wg[sleeve] = blend(np.arange(len(Pb)), np.nonzero(sleeve)[0])
    for side in (1, 2):
        if (cuff == side).any():
            Wg[cuff == side] = blend(np.nonzero(parts == side)[0], np.nonzero(cuff == side)[0])
    X = bones.apply(Q * float(k), Wg)
    relaxed = relax_stretched(X, Q * float(k), faces, adjacency)
    limb_report = None
    if limbs is not None:
        target = _frames_like(body_rigged, limbs["frames"])
        X, limb_report = align_limbs(X, limbs["x0"], limbs["w0"], limbs["names0"], limbs["frames"], target,
                                     kinds=limbs.get("kinds", ("arm", "leg")), adjacency=adjacency)
    if limbs is not None or Q_pre is None:
        Xs = X.copy()
    else:
        Qk = np.asarray(Q_pre, np.float64) * float(k)
        Xs = bones.apply(Qk, Wg)
        relax_stretched(Xs, Qk, faces, adjacency)
    lo = np.minimum(X.min(0), Xs.min(0)) - margin_m
    hi = np.maximum(X.max(0), Xs.max(0)) + margin_m
    sdf = body_sdf(Pr, body_rigged.faces, vox=vox_m, bounds=(lo, hi))
    X, sleeve_report, fitted, sleeve_region = place_sleeves(X, Xs, Wg, body_rigged, faces=faces,
                                                            adjacency=adjacency, choices=sleeves or {},
                                                            inside=sdf.sample(Xs) < 0)
    if (X.min(0) < lo + 0.5 * margin_m).any() or (X.max(0) > hi - 0.5 * margin_m).any():
        lo, hi = np.minimum(lo, X.min(0) - margin_m), np.maximum(hi, X.max(0) + margin_m)
        sdf = body_sdf(Pr, body_rigged.faces, vox=vox_m, bounds=(lo, hi))
    toward = _transfer_sides(Q, X, body_unrigged, bones, Wg, sdf)
    start, side_report = _side_projection(sdf, X, toward, Pr, body_rigged.faces, clear_m)
    Xd = push_kept(X, adjacency, sdf, clear=clear_m, iterations=rigged_iterations,
                   smooth_until=RIGGED_SMOOTH_UNTIL, margin=SIDE_MARGIN_M, start=start)
    if sleeve_region.any() and sleeve_shards(X + Xd, Xs, faces, sleeve_region).any():
        # Ruling A47: a strip the clearance pass stretched in the placed sleeves is evened out, then held clear.
        Y = X + Xd
        relax_sleeve_region(Y, Xs, faces, adjacency, sleeve_region)
        Xd = Y - X
        Xd = Xd + push_kept(Y, adjacency, sdf, clear=clear_m, iterations=3, smooth_until=0, margin=SIDE_MARGIN_M)
    X = X + Xd
    rigged_push = np.linalg.norm(Xd, axis=1)
    if ease_z is not None and np.any(ease_z):
        X[:, 2] += np.asarray(ease_z, np.float64) * float(k)
        if (X.min(0) < lo + 0.5 * margin_m).any() or (X.max(0) > hi - 0.5 * margin_m).any():
            lo, hi = np.minimum(lo, X.min(0) - margin_m), np.maximum(hi, X.max(0) + margin_m)
            sdf = body_sdf(Pr, body_rigged.faces, vox=vox_m, bounds=(lo, hi))
    d = sdf.sample(X)
    arm_cols = [i for i, n in enumerate(body_rigged.joint_names) if "arm" in norm_bone_name(n)]
    # Ruling A47: how tight the trunk of the piece lies (the width allowance, ``scale_retry``) and how much the
    # sleeve placement stretched the fabric against its pre-push shape.
    trunk = trunk_band(X, Wg, body_rigged)
    stretch = sleeve_stretch(X, Xs, faces, sleeve_region) if sleeve_region.any() else None
    report = {
        "method": "skinned",
        "scale_k": float(k),
        **side_report,
        "uv_dist_p99": float(np.percentile(uv_dist, 99)),
        "uv_mismatched_donors": int(mismatched.sum()),
        **bones.report,
        "sleeve_share": float((Wg[:, arm_cols].sum(1) > 0.5).mean()) if arm_cols and len(Wg) else 0.0,
        "sleeve_vertices": int(sleeve.sum()),
        "sleeve_below_waist": int((sleeve & ~upper).sum()),
        "sleeve_cuff_vertices": int((cuff > 0).sum()),
        "relaxed_vertices": int(relaxed),
        "rigged_push_max_m": float(rigged_push.max()) if len(rigged_push) else 0.0,
        "rigged_push_p95_m": float(np.percentile(rigged_push, 95)) if len(rigged_push) else 0.0,
        "rigged_deep_push_share": float((rigged_push > DEEP_PUSH_M).mean()) if len(rigged_push) else 0.0,
        "rigged_clearance_p1_m": float(np.percentile(d, 1)),
        "rigged_inside_share": float((d < 0).mean()),
        "torso_tight_share": float((d[trunk] < TORSO_TIGHT_M).mean()) if trunk.any() else 0.0,
        "torso_gap_p50_m": float(np.median(d[trunk])) if trunk.any() else 0.0,
        **_front_back_gaps(X, d, trunk, Pr),
        "sleeve_stretch": stretch,
        "sleeve_fitted": fitted,
    }
    if limb_report is not None:
        report["limbs"] = limb_report
    if sleeve_report:
        report["sleeves"] = sleeve_report
    return X, report


# --- weights ---------------------------------------------------------------------------------------------------------------

# --- limb alignment (refit before re-render, garment_source) -----------------------------------------------------------
# A piece made on one base and fitted onto another keeps its torso by the silhouette registration; its sleeves and
# trouser legs follow the TARGET limbs: every garment vertex the SOURCE fit skinned to a limb bone is re-expressed
# from the source base's limb frames into the target base's (``align_limbs``) before the rigged clearance pass.
# Chain = proximal joint -> middle joint -> distal joint (-> tip): the joint points are the skeleton's BIND joints
# (``BodyMesh.joint_positions``, the heads of Arm / ForeArm / Hand, UpLeg / Leg / Foot — ``FRAME_BASIS`` "joints",
# Ruling A35); a body without them (or a source frame of the older basis, ``_frames_like``) takes the mean of the
# body vertices carrying both neighbouring bones above ``LIMB_JOINT_SHARED`` (basis "weights"). The weight ring is
# where the rigger's blend lies, not the joint: on Kai's plain body ``base634402e5`` the hip ring of the leg sits at
# x 0.043 while the LeftUpLeg joint is at 0.091 (the blend reaches into the groin), its thigh axis tilted 8.6 / 9.1
# deg (L / R) against 0.4 / 3.4 on the body shape ``obf6474c3b``, whose ring sits at the joint — the transfer
# re-expressed his jeans from a tilted, thin thigh into a straight, thick one and flared the upper thigh 4 - 5 cm
# (off the thigh 0.1478, source 0.0); from the joints the same jeans sit 0.0002 off. A
# segment's radius is the median distance of its bone's dominant vertices to it. Per bone: the vertex's distance
# ALONG the chain from the proximal joint is kept in metres (the piece keeps its own length — user ruling
# 2026-11-10: the length is irrelevant, it must sit on the body) and clamped to the chain's end (hand tip, ankle);
# its radial offset, normalised by the source segment's radius, and its angle around the segment (a frame whose
# second axis is the projection of ``reference`` — world up for an arm, forward for a leg — so both bases' frames
# twist alike) are re-expressed on the target segment at that distance. The bones' results are blended with the
# source garment's own skin weights (the transition into the shoulder / hip runs over the same blend as the skin,
# no crease); the rest of the vertex stays where the torso placement put it.
LIMB_JOINT_SHARED = 0.25
#: Passes of the displacement smoothing after the alignment (``align_limbs``).
LIMB_SMOOTH_PASSES = 150
LIMB_CHAINS: Dict[str, Dict[str, Any]] = {
    f"{side}_{limb}": spec
    for side in ("left", "right")
    for limb, spec in (
        ("arm", {"joints": [("shoulder", "arm"), ("arm", "forearm"), ("forearm", "hand")],
                 "tip": "hand", "bones": {"arm": 0, "forearm": 1, "hand": 2}, "reference": (0.0, 1.0, 0.0),
                 "kind": "arm"}),
        ("leg", {"joints": [("hips", "upleg"), ("upleg", "leg"), ("leg", "foot")],
                 "tip": None, "bones": {"upleg": 0, "leg": 1, "foot": 1}, "reference": (0.0, 0.0, 1.0),
                 "kind": "leg"}),
    )}


def _limb_key(side: str, bone: str) -> str:
    return bone if bone == "hips" else f"{side}{bone}"


def segment_distance(X: np.ndarray, a, b) -> np.ndarray:
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    X = np.asarray(X, np.float64)
    d = b - a
    t = np.clip(((X - a) @ d) / max(float(d @ d), 1e-12), 0.0, 1.0)
    return np.linalg.norm(X - (a + t[:, None] * d), axis=1)


#: Where the chain points of the limb and trunk frames come from (block above): "joints" (the bind joints) or
#: "weights" (the weight-ring centroids — the fallback, and every frame stored before Ruling A35).
FRAME_BASIS = "joints"


def _weight_joint(W: np.ndarray, P: np.ndarray, a: int, b: int) -> Optional[np.ndarray]:
    """The weight-ring centroid of the joint between bones ``a`` and ``b`` (skin columns): the body vertices
    carrying both above ``LIMB_JOINT_SHARED``; None for fewer than 3."""
    shared = (W[:, a] > LIMB_JOINT_SHARED) & (W[:, b] > LIMB_JOINT_SHARED)
    return P[shared].mean(0) if shared.sum() >= 3 else None


def _chain_points(body: BodyMesh, W: np.ndarray, P: np.ndarray, pairs, keys, basis: str
                  ) -> Tuple[Optional[List[np.ndarray]], str]:
    """The points of the joints ``pairs`` (skin columns of the two neighbouring bones) whose child bones are
    ``keys`` (normalised names): with ``basis`` "joints" and every key among ``body.joint_positions`` the bind
    joints, else the weight rings (None when one is missing). ``(points, basis used)``."""
    joints = getattr(body, "joint_positions", None) or {}
    if basis == "joints" and all(k in joints for k in keys):
        return [np.asarray(joints[k], np.float64) for k in keys], "joints"
    points = [_weight_joint(W, P, a, b) for a, b in pairs]
    return (None if any(p is None for p in points) else points), "weights"


def limb_frames(body: BodyMesh, basis: str = FRAME_BASIS) -> Dict[str, Dict[str, Any]]:
    """The limb chains of a rigged body (block above): ``{chain: {points [[x, y, z], ...], radii [...], bones {bone
    key: segment}, reference, kind, basis}}`` (JSON-ready). ``basis`` (``FRAME_BASIS``): the chain points from the
    bind joints ("joints"; a chain whose joints the body does not carry falls back) or the weight rings
    ("weights"); ``basis`` in the result is the one used. A chain whose joints cannot be found is missing."""
    W = dense_weights(body)
    P = np.asarray(body.positions, np.float64)
    dominant = W.argmax(1)
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in LIMB_CHAINS.items():
        side = name.split("_")[0]
        try:
            idx = {bone: joint_index(body, _limb_key(side, bone))
                   for pair in spec["joints"] for bone in pair}
        except KeyError:
            continue
        points, used = _chain_points(body, W, P, [(idx[a], idx[b]) for a, b in spec["joints"]],
                                     [_limb_key(side, b) for _a, b in spec["joints"]], basis)
        if points is None:
            continue
        if spec["tip"]:
            tip = P[dominant == idx[spec["tip"]]]
            if len(tip):
                u = points[-1] - points[-2]
                u = u / max(float(np.linalg.norm(u)), 1e-12)
                reach = float(np.percentile((tip - points[-1]) @ u, 99))
                if reach > 0:
                    points.append(points[-1] + reach * u)
        nseg = len(points) - 1
        radii = []
        for seg in range(nseg):
            bone = next((b for b, s in spec["bones"].items() if s == seg), None)
            own = P[dominant == idx[bone]] if bone in idx else np.zeros((0, 3))
            radii.append(float(np.median(segment_distance(own, points[seg], points[seg + 1]))) if len(own)
                         else (radii[-1] if radii else 0.0))
        out[name] = {"points": [[float(c) for c in p] for p in points], "radii": radii,
                     "bones": {_limb_key(side, b): min(seg, nseg - 1) for b, seg in spec["bones"].items()},
                     "reference": list(spec["reference"]), "kind": spec["kind"], "basis": used}
    return out


def frame_basis(frame: Dict[str, Any]) -> str:
    """The basis a stored frame was made with (``limb_frames`` / ``torso_frame``): one without the key predates
    Ruling A35 and is "weights"."""
    return str(frame.get("basis") or "weights")


def _frames_like(body: BodyMesh, source: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """This body's frames for the source frames ``source`` (``align_limbs``), each made with the SAME basis as
    the source's chain — a limb source stored before Ruling A35 (weight rings, ``garment_source.limb_source``)
    is re-expressed between weight-ring frames, as it was made."""
    target: Dict[str, Dict[str, Any]] = {}
    limbs = {name: frame for name, frame in source.items() if name != "torso"}
    for basis in sorted({frame_basis(f) for f in limbs.values()}):
        target.update({name: frame for name, frame in limb_frames(body, basis=basis).items()
                       if name in limbs and frame_basis(limbs[name]) == basis})
    if "torso" in source:
        torso = torso_frame(body, basis=frame_basis(source["torso"]))
        if torso is not None:
            target["torso"] = torso
    return target


def _segment_frame(a, b, reference) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """``(u, v, w, length)``: u along a -> b, v the projection of ``reference`` perpendicular to u, w = u x v."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    length = float(np.linalg.norm(b - a))
    u = (b - a) / max(length, 1e-12)
    r = np.asarray(reference, np.float64)
    v = r - (r @ u) * u
    if np.linalg.norm(v) < 1e-6:
        v = np.cross(u, [1.0, 0.0, 0.0])
    v = v / np.linalg.norm(v)
    return u, v, np.cross(u, v), length


def align_limbs(X, X0, W0, names0, source: Dict[str, Dict[str, Any]], target: Dict[str, Dict[str, Any]], *,
                kinds=("arm", "leg"), adjacency=None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Re-express the limb part of ``X`` (the torso-placed garment in the target's rigged space) from the source
    fit ``X0`` (same vertices, the source's rigged space; ``W0`` its skin weights over ``names0``) — block above.
    Chains missing on either side, or of a kind not in ``kinds``, are left alone; a ``torso`` chain (``torso_frame``)
    goes through ``map_torso``. With ``adjacency`` (the garment's, ``_adjacency``) the displacement from ``X0`` is
    smoothed over the mesh (``LIMB_SMOOTH_PASSES``): where the skin blends two maps that disagree by centimetres
    (upper arm / shoulder / trunk) their positions would stretch the triangles across the body; the smoothed
    displacement keeps the garment's own local shape. ``(X, report)``."""
    from app.core.rig_contract import norm_bone_name
    X = np.asarray(X, np.float64)
    X0 = np.asarray(X0, np.float64)
    W0 = np.asarray(W0, np.float64)
    col = {norm_bone_name(n): i for i, n in enumerate(names0)}
    Y = np.zeros_like(X)
    S = np.zeros(len(X))
    report: Dict[str, Any] = {"chains": {}}
    for name, src in source.items():
        tgt = target.get(name)
        if not tgt or src.get("kind") not in kinds:
            continue
        if src["kind"] == "torso":
            w = np.zeros(len(X))
            for bone, c in col.items():
                if torso_bone(bone):
                    w += W0[:, c]
            rows = np.nonzero(w > 1e-4)[0]
            if len(rows):
                Y[rows] += w[rows, None] * map_torso(X0[rows], src, tgt)
                S[rows] += w[rows]
            report["chains"][name] = {"vertices": int(len(rows)),
                                      "source_span_m": round(src["neck_y"] - src["hip_y"], 4),
                                      "target_span_m": round(tgt["neck_y"] - tgt["hip_y"], 4)}
            continue
        ps, pt = np.asarray(src["points"], np.float64), np.asarray(tgt["points"], np.float64)
        nseg = min(len(ps), len(pt)) - 1
        if nseg < 1:
            continue
        fs = [_segment_frame(ps[i], ps[i + 1], src["reference"]) for i in range(nseg)]
        ft = [_segment_frame(pt[i], pt[i + 1], tgt["reference"]) for i in range(nseg)]
        cum_s = np.concatenate([[0.0], np.cumsum([f[3] for f in fs])])
        cum_t = np.concatenate([[0.0], np.cumsum([f[3] for f in ft])])
        moved = 0
        for bone, seg in src["bones"].items():
            c = col.get(bone)
            if c is None:
                continue
            seg = min(int(seg), nseg - 1)
            w = W0[:, c]
            rows = np.nonzero(w > 1e-4)[0]
            if not len(rows):
                continue
            u, v, ww, _length = fs[seg]
            rel = X0[rows] - ps[seg]
            along = rel @ u
            radial = rel - along[:, None] * u
            rho = np.linalg.norm(radial, axis=1) / max(float(src["radii"][seg]), 1e-6)
            theta = np.arctan2(radial @ ww, radial @ v)
            dist = np.minimum(cum_s[seg] + along, cum_t[-1])
            j = np.clip(np.searchsorted(cum_t, dist, side="right") - 1, 0, nseg - 1)
            # The offset scales with the target radius of the vertex's OWN bone segment: a forearm vertex that
            # lands on the target's (longer) upper arm keeps the forearm's thickness — no step at the elbow.
            radius = float(tgt["radii"][min(seg, len(tgt["radii"]) - 1)])
            out = np.empty((len(rows), 3))
            for k in range(nseg):
                m = j == k
                if not m.any():
                    continue
                tu, tv, tw, _ = ft[k]
                out[m] = (pt[k] + (dist[m] - cum_t[k])[:, None] * tu
                          + (rho[m] * radius)[:, None] * (np.cos(theta[m])[:, None] * tv
                                                          + np.sin(theta[m])[:, None] * tw))
            Y[rows] += w[rows, None] * out
            S[rows] += w[rows]
            moved += len(rows)
        report["chains"][name] = {"vertices": int(moved), "source_length_m": round(float(cum_s[-1]), 4),
                                  "target_length_m": round(float(cum_t[-1]), 4)}
    total = np.maximum(S, 1e-12)
    Y = np.where(S[:, None] > 0, Y / total[:, None], X)
    S = np.clip(S, 0.0, 1.0)
    Xa = (1.0 - S)[:, None] * X + S[:, None] * Y
    if adjacency is not None and LIMB_SMOOTH_PASSES > 0 and (S > 0).any():
        Xa = X0 + _smooth(Xa - X0, adjacency, LIMB_SMOOTH_PASSES)
    shift = np.linalg.norm(Xa - X, axis=1)
    moved = S > 0
    report.update({"vertices": int(moved.sum()),
                   "shift_p50_m": round(float(np.median(shift[moved])), 4) if moved.any() else 0.0,
                   "shift_max_m": round(float(shift.max()), 4) if len(shift) else 0.0})
    return Xa, report


# --- torso alignment (fits on outfit bodies, garment_source) -------------------------------------------------------
# An outfit body is meshed from its own dressed views (another framing, heels, another chest), so the image framing
# that places a piece on its base does not place it on the outfit body (Kira's blazer: collar 0.4 - 6.5 cm and hem up
# to 6 cm off). ``map_torso`` re-expresses every vertex the SOURCE fit skinned to a trunk bone (``torso_bone``: any
# bone that is no limb bone — extension bones such as the chest included, whatever the rig names them; without
# them the radius table misses the chest and the front panel lands inside it) from the source body's trunk into
# the target's: height proportional between the hip joint (the mean of both
# Hips / UpLeg joints) and the neck joint (Spine2 / Neck), in metres below and above them; around the trunk axis
# (the chain of joint points, interpolated by height) its clearance over the body SURFACE in its direction is kept
# in metres (a bridge over a hollow only down to ``TORSO_BRIDGE_M`` where the target grew) — the surface radius
# ``R(v, theta)`` per normalised height v (``TORSO_V`` bins) and angle (``TORSO_THETA`` bins) is the outermost trunk
# vertex there, gaps filled along the height and smoothed 3 x 3 — so a deeper chest
# carries the front panel out with it. Blended with the limbs by the source skin weights (``align_limbs``).
_LIMB_BONE_PARTS = ("arm", "hand", "leg", "foot", "toe")
_HEAD_BONE_PARTS = ("head", "eye", "jaw")


def torso_bone(name: str) -> bool:
    """A normalised bone name (``rig_contract.norm_bone_name``) the trunk carries: no arm / hand / leg / foot / toe
    bone. The head counts (a collar's weights), but not for the trunk's surface (``trunk_bone``)."""
    return not any(part in name for part in _LIMB_BONE_PARTS)


def trunk_bone(name: str) -> bool:
    """A bone whose dominant vertices are the trunk's SURFACE (radius table, coverage): ``torso_bone`` without the
    head (whose hair would read as a trunk)."""
    return torso_bone(name) and not any(part in name for part in _HEAD_BONE_PARTS)
TORSO_V = (-0.6, 1.4, 0.02)
TORSO_THETA = 36
#: ``map_torso`` (Ruling A50): clearance over the source surface up to this is kept in metres; beyond it the piece
#: BRIDGES a hollow (the small of the back, under the open front's edges) and the target's outward growth there
#: (``R_target - R_source`` in that direction, its in-body shirt) is taken out of the bridge, never below this. Kai's
#: open leather jacket on obf6474c3b (in-body underwear + t-shirt; R +3.3 cm at the small of the back, +1.8 cm at
#: the lower front) was carried out 5 - 7 cm off the shirt and refused — front 0.75 / source 0.85, side 0.85 / 0.92,
#: back 0.88 / 0.95, a 35 cm2 hole at the lower back; with the bridge rule 0.82 / 0.85, 0.93 / 0.92, 1.00 / 0.95,
#: largest hole 2.5 cm2: accepted. Kira's blazer and skirt on obf043ed6a and Kai's jeans on obf6474c3b move by at
#: most 0.007 of any share. 1 / 2 / 3 cm for the jacket: front 0.85 / 0.82 / 0.79, trunk closer than 1.5 cm
#: 0.36 / 0.30 / 0.24 (the plain body's fit 0.16) — 2 cm passes every gate with margin and stays looser than 1 cm.
TORSO_BRIDGE_M = 0.02


def torso_frame(body: BodyMesh, basis: str = FRAME_BASIS) -> Optional[Dict[str, Any]]:
    """The trunk of a rigged body (block above): ``{points [[x, y, z], ...] (hip, joints up to the neck),
    hip_y, neck_y, radius [[...] per v bin] (TORSO_THETA per bin), kind "torso", basis}``; None without the
    joints. ``basis`` like ``limb_frames``: the points are the bind joints (the hip = the mean of both UpLeg joints,
    then Spine / Spine1 / Spine2 / Neck) or, falling back per point, the weight rings between the neighbouring
    bones. On Kai's plain body the weight ring of Spine stood 7.7 cm in front of the body shape's at the lower back
    (z +0.035 against -0.042), so ``map_torso`` read the clearance of his jacket in mismatched directions."""
    from app.core.rig_contract import norm_bone_name
    W = dense_weights(body)
    P = np.asarray(body.positions, np.float64)
    names = [norm_bone_name(n) for n in body.joint_names]
    joints = getattr(body, "joint_positions", None) or {}
    used = {"joints" if basis == "joints" else "weights"}

    def joint(a: str, b: str) -> Optional[np.ndarray]:
        if a not in names or b not in names:
            return None
        if basis == "joints" and b in joints:
            return np.asarray(joints[b], np.float64)
        used.add("weights")
        return _weight_joint(W, P, names.index(a), names.index(b))

    legs = [joint("hips", "leftupleg"), joint("hips", "rightupleg")]
    chain = [joint("hips", "spine"), joint("spine", "spine1"), joint("spine1", "spine2"), joint("spine2", "neck")]
    if any(p is None for p in legs) or chain[-1] is None:
        return None
    hip = (legs[0] + legs[1]) / 2
    points = [hip] + [p for p in chain if p is not None]
    neck = chain[-1]
    trunk = np.isin(W.argmax(1), [i for i, n in enumerate(names) if trunk_bone(n)])
    T = P[trunk]
    frame = {"points": [[float(c) for c in p] for p in points], "hip_y": float(hip[1]), "neck_y": float(neck[1]),
             "kind": "torso", "basis": "weights" if "weights" in used else "joints"}
    v, theta, rho = _torso_coords(T, frame)
    lo, hi, step = TORSO_V
    nv = int(round((hi - lo) / step))
    iv = np.clip(((v - lo) / step).astype(int), 0, nv - 1)
    it = _theta_bin(theta)
    R = np.full((nv, TORSO_THETA), np.nan)
    np.fmax.at(R, (iv, it), rho)
    rows = np.arange(nv)
    for k in range(TORSO_THETA):  # gaps along the height: nearest defined bins
        ok = ~np.isnan(R[:, k])
        if ok.any():
            R[:, k] = np.interp(rows, rows[ok], R[ok, k])
    for k in np.nonzero(np.isnan(R).all(0))[0]:  # an angle without any vertex: its neighbours
        R[:, k] = np.nanmean(R[:, [(k - 1) % TORSO_THETA, (k + 1) % TORSO_THETA]], axis=1)
    R = np.nan_to_num(R, nan=float(np.nanmedian(R)))
    padded = np.concatenate([R[:, -1:], R, R[:, :1]], axis=1)
    padded = np.concatenate([padded[:1], padded, padded[-1:]], axis=0)
    R = sum(padded[1 + dv:1 + dv + nv, 1 + dt:1 + dt + TORSO_THETA] for dv in (-1, 0, 1) for dt in (-1, 0, 1)) / 9.0
    frame["radius"] = R.round(5).tolist()
    return frame


def _theta_bin(theta: np.ndarray) -> np.ndarray:
    return ((np.asarray(theta) + np.pi) / (2 * np.pi) * TORSO_THETA).astype(int) % TORSO_THETA


def _torso_v(y: np.ndarray, frame: Dict[str, Any]) -> np.ndarray:
    return (np.asarray(y, np.float64) - frame["hip_y"]) / max(frame["neck_y"] - frame["hip_y"], 1e-6)


def _torso_axis(y: np.ndarray, frame: Dict[str, Any]) -> np.ndarray:
    pts = np.asarray(frame["points"], np.float64)
    order = np.argsort(pts[:, 1])
    return np.stack([np.interp(y, pts[order, 1], pts[order, 0]), np.interp(y, pts[order, 1], pts[order, 2])], 1)


def _torso_coords(X: np.ndarray, frame: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(v, theta, rho)``: normalised height, angle around the trunk axis (0 = +z, front), radial distance."""
    X = np.asarray(X, np.float64)
    rel = X[:, [0, 2]] - _torso_axis(X[:, 1], frame)
    return _torso_v(X[:, 1], frame), np.arctan2(rel[:, 0], rel[:, 1]), np.linalg.norm(rel, axis=1)


def _torso_radius(frame: Dict[str, Any], v: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """``R(v, theta)`` bilinear over the bins (clamped in v, circular in theta)."""
    R = np.asarray(frame["radius"], np.float64)
    lo, _hi, step = TORSO_V
    fv = np.clip((np.asarray(v) - lo) / step - 0.5, 0, len(R) - 1)
    ft = (np.asarray(theta) + np.pi) / (2 * np.pi) * TORSO_THETA - 0.5
    v0 = np.minimum(np.floor(fv).astype(int), len(R) - 2)
    t0 = np.floor(ft).astype(int)
    av, at = fv - v0, ft - t0
    t0, t1 = t0 % TORSO_THETA, (t0 + 1) % TORSO_THETA
    return ((1 - av) * ((1 - at) * R[v0, t0] + at * R[v0, t1])
            + av * ((1 - at) * R[v0 + 1, t0] + at * R[v0 + 1, t1]))


def map_torso(X0, source: Dict[str, Any], target: Dict[str, Any]) -> np.ndarray:
    """``X0`` (source rigged space) re-expressed on the target trunk (block above)."""
    X0 = np.asarray(X0, np.float64)
    v, theta, rho = _torso_coords(X0, source)
    clearance = rho - _torso_radius(source, v, theta)
    y = X0[:, 1]
    span_s = source["neck_y"] - source["hip_y"]
    span_t = target["neck_y"] - target["hip_y"]
    y_t = np.where(y < source["hip_y"], target["hip_y"] + (y - source["hip_y"]),
                   np.where(y > source["neck_y"], target["neck_y"] + (y - source["neck_y"]),
                            target["hip_y"] + v * span_t))
    if span_s <= 0:
        return X0.copy()
    r_t = _torso_radius(target, _torso_v(y_t, target), theta)
    # Ruling A50: clearance beyond ``TORSO_BRIDGE_M`` bridges a hollow of the source body; where the target's surface
    # lies further out, that growth fills the hollow under the bridge instead of carrying the piece out with it.
    grow = np.maximum(r_t - _torso_radius(source, v, theta), 0.0)
    clearance = np.where(clearance > TORSO_BRIDGE_M, np.maximum(clearance - grow, TORSO_BRIDGE_M), clearance)
    radius = np.maximum(r_t + clearance, 0.0)
    axis = _torso_axis(y_t, target)
    return np.stack([axis[:, 0] + np.sin(theta) * radius, y_t, axis[:, 1] + np.cos(theta) * radius], 1)


def chin_height(body_rigged: BodyMesh) -> float:
    """Height of the lowest rigged vertex with Head weight > 0.5."""
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    if not head.any():
        raise ValueError("The rigged body has no Head-weighted vertex")
    return float(body_rigged.positions[head, 1].min())


def ear_line_height(body_rigged: BodyMesh) -> float:
    """The ear line (earlobe / jaw angle): ``HAIR_EAR_LINE_FRACTION`` of the head height (chin -> crown, both
    measured on the Head-weighted vertices) above the chin."""
    head = dense_weights(body_rigged)[:, joint_index(body_rigged, "head")] > 0.5
    chin = chin_height(body_rigged)
    return float(chin + HAIR_EAR_LINE_FRACTION * (body_rigged.positions[head, 1].max() - chin))


def shoulder_top_height(body_rigged: BodyMesh) -> float:
    """The top of the shoulders: per side the highest rigged vertex whose dominant bone is that side's Shoulder
    (clavicle) bone, averaged over the sides found (Kira's base: 1.437 / 1.440 m — the trapezius top at |x| 9-10 cm).
    A skin without Shoulder-dominated vertices (a reduced test rig): the highest Spine2-dominated vertex. ValueError
    when neither exists."""
    W = dense_weights(body_rigged)
    dominant = W.argmax(1)
    tops = []
    for key in ("leftshoulder", "rightshoulder"):
        try:
            side = dominant == joint_index(body_rigged, key)
        except KeyError:
            continue
        if side.any():
            tops.append(float(body_rigged.positions[side, 1].max()))
    if tops:
        return float(np.mean(tops))
    trunk = dominant == joint_index(body_rigged, "spine2")
    if not trunk.any():
        raise ValueError("The rigged body has no vertex dominated by a Shoulder or the Spine2 bone")
    return float(body_rigged.positions[trunk, 1].max())


def hair_weights(X, body_rigged: BodyMesh):
    """Head -> Neck -> Spine2 by height -> ``(joint_names, joints (n,4), weights (n,4))``; column 0 is always Head.

    A smooth vertical ramp between two measured landmarks: at the ear line (``ear_line_height``) and above all Head,
    at the shoulder top (``shoulder_top_height``) and below all Spine2. In between ``t`` = the fraction of the way
    down, ``s = smoothstep(t)``, and the three weights are the quadratic B-spline basis of ``s``: Head (1-s)^2,
    Neck 2s(1-s), Spine2 s^2 — they sum to 1, each is C1 in the height, and the middle of the ramp rides the neck.
    Hair below the ear line hangs beside the neck and on the shoulders; weighted to the Head it swept 1.5-2 cm into
    the shoulder tops on every head tilt (collision ruling C7, Kira: excess sit 9.4 %, celebrating 7.6 %). Joints are
    resolved by ``norm_bone_name`` (``head``, ``neck``, ``spine2`` — rig-contract bones), never by index; a skin
    without a Neck joint (a reduced test rig) gives the Neck share to Spine2.
    """
    X = np.asarray(X, np.float64)
    head, spine2 = joint_index(body_rigged, "head"), joint_index(body_rigged, "spine2")
    try:
        neck: Optional[int] = joint_index(body_rigged, "neck")
    except KeyError:
        neck = None
    ear, shoulder = ear_line_height(body_rigged), shoulder_top_height(body_rigged)
    if not shoulder < ear:
        raise ValueError(f"The shoulder top ({shoulder:.3f} m) is not below the ear line ({ear:.3f} m)")
    t = np.clip((ear - X[:, 1]) / (ear - shoulder), 0, 1)
    s = t * t * (3 - 2 * t)
    W = np.zeros((len(X), 4))
    if neck is None:
        names = [body_rigged.joint_names[i] for i in (head, spine2)]
        J = np.tile(np.array([0, 1, 0, 0], np.int64), (len(X), 1))
        W[:, 0] = (1 - s) ** 2
        W[:, 1] = 1 - W[:, 0]
    else:
        names = [body_rigged.joint_names[i] for i in (head, neck, spine2)]
        J = np.tile(np.array([0, 1, 2, 0], np.int64), (len(X), 1))
        W[:, 0], W[:, 1], W[:, 2] = (1 - s) ** 2, 2 * s * (1 - s), s ** 2
    return names, J, W


def _contract_columns(body: BodyMesh) -> np.ndarray:
    """Bool per skin joint: a rig-contract bone (``rig_contract.BASE_JOINT_KEYS``), never an extension bone."""
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    return np.array([norm_bone_name(n) in BASE_JOINT_KEYS for n in body.joint_names], bool)


def crotch_height(body_rigged: BodyMesh) -> float:
    """Height of the lowest rigged vertex within ``CROTCH_HALF_X_M`` of the centre line (the median x of the
    Hips-weighted vertices) with Hips weight > ``CROTCH_HIPS_MIN``."""
    hips = dense_weights(body_rigged)[:, joint_index(body_rigged, "hips")] > CROTCH_HIPS_MIN
    if not hips.any():
        raise ValueError("The rigged body has no Hips-weighted vertex")
    P = body_rigged.positions
    xc = float(np.median(P[hips, 0]))
    centre = hips & (np.abs(P[:, 0] - xc) < CROTCH_HALF_X_M)
    if not centre.any():
        raise ValueError("The rigged body has no Hips-weighted vertex on its centre line")
    return float(P[centre, 1].min())


def is_skirt(X, body_rigged: BodyMesh, slots) -> bool:
    """Whether a fitted piece hangs over both legs as ONE surface below the crotch (a skirt or a dress).

    Only a piece on a skirt slot (``SKIRT_SLOTS``) can be one. Its rigged vertices between ``SKIRT_PROBE_M`` below
    the crotch (the hem, when it ends higher up) that lie within ``SKIRT_CENTRE_M`` of the centre line must reach in
    front of the body's front AND behind its back at those heights: a skirt crosses the centre line on both sides of
    the legs, trousers (one tube per leg) never cover the gap between them.
    """
    if not SKIRT_SLOTS & {str(s) for s in (slots or [])}:
        return False
    X = np.asarray(X, np.float64)
    if len(X) == 0:
        return False
    crotch = crotch_height(body_rigged)
    hi = crotch - SKIRT_PROBE_M[0]
    lo = max(float(X[:, 1].min()), crotch - SKIRT_PROBE_M[1])
    if lo >= hi:
        return False
    P = body_rigged.positions
    hips = dense_weights(body_rigged)[:, joint_index(body_rigged, "hips")] > CROTCH_HIPS_MIN
    xc = float(np.median(P[hips, 0]))
    body = P[(P[:, 1] >= lo) & (P[:, 1] <= hi)]
    garment = X[(X[:, 1] >= lo) & (X[:, 1] <= hi) & (np.abs(X[:, 0] - xc) < SKIRT_CENTRE_M)]
    if len(body) == 0 or len(garment) == 0:
        return False
    return bool(garment[:, 2].max() > body[:, 2].max() and garment[:, 2].min() < body[:, 2].min())


def clothing_weights(points, body: BodyMesh, *, skirt: bool,
                     columns: Optional[Sequence[int]] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Skin weights of rigged clothing positions -> ``(joints (n, 4), weights (n, 4))``, joints indexing
    ``body.joint_names``; zero-weight slots point at joint 0.

    ``columns`` (skin indices; boots spec 2026-11-11 § 6.3) restricts the donor weights of step 1 to those bones and
    renormalises — a boot shaft takes only its side's Leg / UpLeg (fit version 7; the Foot share of the ankle band is
    the foot part's own term), never a stray Hips, Foot or other-leg donor of the IDW; the fallback donors are then
    the body vertices weighted on those columns and step 3 (extension bones) is skipped. ``None`` = the default
    behaviour, unchanged.

    1. Inverse distance over the ``CLOTHING_IDW_K`` (8) nearest rigged body vertices, ``w = 1 / max(d, 1e-4)``
       (spike ``fit_dress.py``), of the body weights RESTRICTED to the rig-contract bones and renormalised. A point
       whose neighbours carry only extension bones takes the same inverse distance over the nearest body vertices
       with at least ``CONTRACT_DONOR_MIN`` of their weight on contract bones.
    2. ``skirt`` (``skirt_leg_weights``): below crotch + ``SKIRT_ZONE_M`` the leg weights are smoothed over the zone
       (``SKIRT_SMOOTH_M``) and a vertex keeps ``SKIRT_KEEP_TOP`` of them from the crotch up, falling linearly to
       ``SKIRT_KEEP_HEM`` at the hem (the lowest point); the rest goes to Hips. The skirt follows the thighs when
       sitting and spans the gap between the legs smoothly when they scissor.
    3. Extension bones: the same inverse distance over the 8 nearest body vertices, of their FULL weights (rows
       normalised), restricted to the extension bones = ``E`` (row sum ``e``); times the distance factor
       ``clip((EXTENSION_ZERO_M - d) / (EXTENSION_ZERO_M - EXTENSION_FULL_M), 0, 1)``, ``d`` = distance to the
       nearest body vertex. The weights are ``(1 - e) * contract + E``: over the tissue the garment rides the
       extension bone as the skin does, beside it the contract blend of steps 1-2 is unchanged.
    4. The four largest weights, renormalised.
    """
    from scipy.spatial import cKDTree
    from app.core.rig_contract import norm_bone_name
    X = np.asarray(points, np.float64)
    Wr = dense_weights(body)
    contract = _contract_columns(body)
    contract = np.concatenate([contract, np.zeros(Wr.shape[1] - len(contract), bool)])
    if columns is not None:
        allowed = np.zeros(Wr.shape[1], bool)
        allowed[list(columns)] = True
        contract = contract & allowed
    Wc = Wr * contract[None, :]

    def neighbours(positions, rows):
        k = min(CLOTHING_IDW_K, len(positions))
        dist, nn = cKDTree(positions).query(X[rows], k=k)
        dist, nn = dist.reshape(len(dist), -1), nn.reshape(len(nn), -1)
        w = 1.0 / np.maximum(dist, CLOTHING_IDW_EPS_M)
        return dist, nn, w / w.sum(1, keepdims=True)

    def idw(index, positions, rows):
        _dist, nn, w = neighbours(positions, rows)
        return np.einsum("nk,nkj->nj", w, Wc[index[nn]])
    every = np.arange(len(body.positions))
    W = idw(every, body.positions, np.ones(len(X), bool)) if len(X) else np.zeros((0, Wr.shape[1]))
    empty = W.sum(1) <= 1e-9
    if empty.any():
        total = Wr.sum(1)
        donors = np.nonzero(Wc.sum(1) >= CONTRACT_DONOR_MIN * np.maximum(total, 1e-12))[0]
        donors = donors[total[donors] > 0]
        if len(donors) == 0:
            raise ValueError("The rigged body has no vertex weighted on rig-contract bones")
        W[empty] = idw(donors, body.positions[donors], empty)
    W /= np.maximum(W.sum(1, keepdims=True), 1e-12)

    if skirt and len(X):
        legs = [i for i, n in enumerate(body.joint_names)
                if contract[i] and any(t in norm_bone_name(n) for t in _LEG_TOKENS)]
        W = skirt_leg_weights(X, W, legs=legs, hips=joint_index(body, "hips"), crotch=crotch_height(body))

    if len(X) and columns is None and not contract.all():
        dist, nn, w = neighbours(body.positions, np.ones(len(X), bool))
        full = Wr / np.maximum(Wr.sum(1, keepdims=True), 1e-12)
        E = np.einsum("nk,nkj->nj", w, full[nn]) * ~contract[None, :]
        E *= np.clip((EXTENSION_ZERO_M - dist[:, 0]) / (EXTENSION_ZERO_M - EXTENSION_FULL_M), 0, 1)[:, None]
        W = W * (1 - E.sum(1, keepdims=True)) + E

    J = np.argsort(-W, 1, kind="stable")[:, :4]
    top = np.take_along_axis(W, J, 1)
    top /= np.maximum(top.sum(1, keepdims=True), 1e-12)
    J = np.where(top > 0, J, 0)
    return J.astype(np.int64), top


def skirt_leg_weights(X, W, *, legs, hips: int, crotch: float, smooth_m: float = SKIRT_SMOOTH_M,
                      keep_top: float = SKIRT_KEEP_TOP, keep_hem: float = SKIRT_KEEP_HEM,
                      zone_m: float = SKIRT_ZONE_M) -> np.ndarray:
    """The skirt step of ``clothing_weights`` on dense weights ``W`` (n, joints; rows sum to 1) -> new dense weights.

    Zone = the vertices below ``crotch + zone_m``. Per zone vertex: (1) its leg columns become the Gaussian average
    (sigma ``smooth_m / 2``) of the leg columns of the zone vertices within ``smooth_m`` (itself included); its other
    columns are rescaled to the remaining weight (all on ``hips`` when it had none); (2) with ``t`` = the fraction of
    the way from the crotch down to the hem (the lowest point, 0 above the crotch), it keeps ``keep_top + (keep_hem -
    keep_top) * t`` of its leg weight and the rest goes to ``hips``. Rows still sum to 1.
    """
    from scipy.spatial import cKDTree
    X = np.asarray(X, np.float64)
    W = np.array(W, np.float64)
    zone = np.nonzero(X[:, 1] < crotch + zone_m)[0]
    if not len(zone) or not legs:
        return W
    legs = list(legs)
    L = W[np.ix_(zone, legs)]
    Ls = np.empty_like(L)
    Z = X[zone]
    tree = cKDTree(Z)
    sigma = max(smooth_m / 2, 1e-9)
    for a in range(0, len(zone), 1024):
        rows = tree.query_ball_point(Z[a:a + 1024], max(smooth_m, 0.0))
        for r, nb in enumerate(rows):
            nb = np.asarray(nb if len(nb) else [a + r], np.int64)
            g = np.exp(-0.5 * (np.linalg.norm(Z[nb] - Z[a + r], axis=1) / sigma) ** 2)
            Ls[a + r] = g @ L[nb] / g.sum()
    other = np.setdiff1d(np.arange(W.shape[1]), legs)
    O = W[np.ix_(zone, other)]
    rest = np.clip(1 - Ls.sum(1), 0, 1)
    osum = O.sum(1)
    O = np.where(osum[:, None] > 1e-12, O / np.maximum(osum[:, None], 1e-12) * rest[:, None], 0.0)
    O[osum <= 1e-12, list(other).index(hips)] = rest[osum <= 1e-12]
    hem = float(X[:, 1].min())
    t = np.clip((crotch - Z[:, 1]) / max(crotch - hem, 1e-6), 0, 1)
    keep = keep_top + (keep_hem - keep_top) * t
    W[np.ix_(zone, other)] = O
    W[np.ix_(zone, legs)] = Ls * keep[:, None]
    W[zone, hips] += Ls.sum(1) * (1 - keep)
    return W


# --- metrics + gate -----------------------------------------------------------------------------------------------------

def new_edge_max(X: np.ndarray, X0: np.ndarray, faces) -> float:
    """Ruling A72 — the largest growth (metres) of an edge of ``faces`` from ``X0`` (the placed piece) to ``X`` (the
    fit), 0.0 without faces."""
    F = np.asarray(faces, np.int64).reshape(-1, 3)
    if not len(F):
        return 0.0
    E = np.unique(np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1), axis=0)
    X, X0 = np.asarray(X, np.float64), np.asarray(X0, np.float64)
    grown = (np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1) - np.linalg.norm(X0[E[:, 0]] - X0[E[:, 1]], axis=1))
    return float(grown.max())


def clothing_metrics(X, Fw, Q0_pre, Q_post, transfer_report: Dict[str, Any],
                     exclude: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Mesh gate numbers of a fitted clothing piece (``CLOTHING_GATES``), positions as in ``metrics``. ``exclude``
    (a vertex mask): counted as not pushed — the sleeves laid onto the arm (Ruling A47), whose placement push is
    discarded (they are placed at the sleeve clearance instead; their own check is ``sleeve_shards``). They stay in
    the share's denominator, as every vertex did when the gate limits were measured. ``new_edge_max_m`` (Ruling A72):
    the longest edge the fit grew beyond the placed piece ``Q0_pre``."""
    X = np.asarray(X, np.float64)
    Fw = np.asarray(Fw, np.int64).reshape(-1, 3)
    push = np.linalg.norm(np.asarray(Q_post, np.float64) - np.asarray(Q0_pre, np.float64), axis=1)
    if exclude is not None and len(exclude) == len(push) and np.any(exclude):
        push = np.where(np.asarray(exclude, bool), 0.0, push)
    _, share = components(X, Fw)
    stretch = transfer_report.get("sleeve_stretch") or {}
    return {
        "max_push_m": round(float(push.max()) if len(push) else 0.0, 4),
        "moved_share": round(float((push > MOVED_EPS_M).mean()) if len(push) else 0.0, 4),
        "deep_push_share": round(float((push > DEEP_PUSH_M).mean()) if len(push) else 0.0, 4),
        "largest_component_share": round(float(share.max()) if len(share) else 0.0, 4),
        "rigged_inside_share": round(float(transfer_report.get("rigged_inside_share", float("nan"))), 4),
        "rigged_push_max_m": round(float(transfer_report.get("rigged_push_max_m", float("nan"))), 4),
        "rigged_push_p95_m": round(float(transfer_report.get("rigged_push_p95_m", float("nan"))), 4),
        "rigged_deep_push_share": round(float(transfer_report.get("rigged_deep_push_share", float("nan"))), 4),
        "rigged_clearance_p1_m": round(float(transfer_report.get("rigged_clearance_p1_m", float("nan"))), 4),
        "torso_tight_share": round(float(transfer_report.get("torso_tight_share", float("nan"))), 4),
        "torso_gap_p50_m": round(float(transfer_report.get("torso_gap_p50_m", float("nan"))), 4),
        **{key: (round(float(transfer_report[key]), 4) if transfer_report.get(key) is not None else None)
           for key in ("trunk_front_gap_p50_m", "trunk_back_gap_p50_m")},
        "sleeve_stretch_over": int(stretch.get("over") or 0),
        "sleeve_shards": int(stretch.get("shards") or 0),
        "sleeve_stretch_p99": float(stretch.get("p99") or 1.0),
        "new_edge_max_m": round(new_edge_max(X, Q0_pre, Fw), 4),
        "tris": int(len(Fw)),
    }


def clothing_gates(*, torso_mapped: bool) -> Dict[str, Tuple[str, float, str]]:
    """The ``CLOTHING_GATES`` a clothing fit is judged by. A piece whose trunk is re-expressed from its base fit
    (``map_torso``, outfit bodies) no longer stands where the image framing put it: the push numbers of that
    placement (``PLACEMENT_GATE_KEYS``) are recorded, not gated. The rigged pass's gates (``rigged_inside_share``,
    ``rigged_deep_push_share``) hold for every fit — that push really happens on the body the piece is worn on."""
    return {key: spec for key, spec in CLOTHING_GATES.items() if not (torso_mapped and key in PLACEMENT_GATE_KEYS)}


def gate(m: Dict[str, Any], gates: Dict[str, Tuple[str, float, str]]) -> Tuple[bool, List[str]]:
    """``(ok, reasons)`` against ``gates`` (``{key: (kind, limit, label)}``); a missing or non-finite number
    refuses."""
    reasons = []
    for key, (kind, limit, label) in gates.items():
        value = m.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            reasons.append(f"{key}: missing ({label})")
        elif kind == "max" and value > limit:
            reasons.append(f"{key} {value:g} > {limit:g} ({label})")
        elif kind == "min" and value < limit:
            reasons.append(f"{key} {value:g} < {limit:g} ({label})")
    return not reasons, reasons


# --- composition ------------------------------------------------------------------------------------------------------------

@dataclass
class FitResult:
    garment: GarmentMesh            # per prepared-GLB vertex (minus dropped components), rigged space, weighted
    metrics: Dict[str, Any]
    ok: bool
    reasons: List[str]
    report: Dict[str, Any] = field(default_factory=dict)


def _mask(mask) -> np.ndarray:
    """A bool mask as is; a uint8 BiRefNet mask thresholded at 17 like the spike."""
    arr = np.asarray(mask)
    return arr if arr.dtype == bool else arr >= 17


def vertex_normals(X: np.ndarray, F: np.ndarray) -> np.ndarray:
    N = np.zeros_like(X)
    fn = np.cross(X[F[:, 1]] - X[F[:, 0]], X[F[:, 2]] - X[F[:, 0]])
    for i in range(3):
        np.add.at(N, F[:, i], fn)
    norm = np.linalg.norm(N, axis=1, keepdims=True)
    return np.where(norm > 1e-12, N / np.maximum(norm, 1e-12), np.array([0.0, 1.0, 0.0]))


def _garment_out(Pd, Fd, Ud, inv, new_of_welded, X, Fk, J, W, names, image, mime, material,
                 lining: Optional[np.ndarray] = None) -> GarmentMesh:
    """The fitted garment on the prepared GLB's vertices (UV seams intact), minus the dropped components: ``X``,
    ``J``, ``W`` are per kept welded vertex (``Fk`` their faces), ``new_of_welded`` maps welded -> kept (-1 dropped)
    and ``inv`` prepared -> welded; ``lining`` (per kept vertex): the faces seen through an opening are left out
    (``opening_lining``), and with them the vertices only they used."""
    face_ok = _out_faces(Fd, inv, new_of_welded, lining)
    vmap = new_of_welded[inv]
    kept_v = np.nonzero(vmap >= 0)[0]
    orig_new = np.full(len(Pd), -1, np.int64)
    orig_new[kept_v] = np.arange(len(kept_v))
    Fo = np.asarray(Fd, np.int64).reshape(-1, 3)
    faces = orig_new[Fo[face_ok]]
    used = np.unique(faces)
    final = np.full(len(kept_v), -1, np.int64)
    final[used] = np.arange(len(used))
    src = vmap[kept_v[used]]
    normals = vertex_normals(X, Fk)
    return GarmentMesh(positions=X[src], normals=normals[src], uvs=np.asarray(Ud, np.float64)[kept_v[used]],
                       indices=final[faces], joints=J[src], weights=W[src], joint_names=names,
                       image=image, mime=mime, material=material)


def _out_faces(Fd, inv, new_of_welded, lining: Optional[np.ndarray] = None) -> np.ndarray:
    """Per prepared face whether ``_garment_out`` keeps it: not degenerate after the weld, all vertices kept, not
    lining (``_open_faces``)."""
    vmap = new_of_welded[inv]
    Fo = np.asarray(Fd, np.int64).reshape(-1, 3)
    Fwo = inv[Fo]
    face_ok = ((Fwo[:, 0] != Fwo[:, 1]) & (Fwo[:, 1] != Fwo[:, 2]) & (Fwo[:, 0] != Fwo[:, 2])
               & (vmap[Fo] >= 0).all(1))
    if lining is not None and face_ok.any():
        face_ok[face_ok] = _open_faces(vmap[Fo[face_ok]], lining)
    return face_ok


def _out_index(Pd, Fd, inv, new_of_welded, lining: Optional[np.ndarray] = None) -> np.ndarray:
    """Per output vertex of ``_garment_out`` its kept welded vertex (the same rule) — the vertex order of every fit
    of this prepared mesh, whatever body it was fitted on (the lining is found on the mesh and the ghost images
    alone, so it is the same on every body)."""
    face_ok = _out_faces(Fd, inv, new_of_welded, lining)
    vmap = new_of_welded[inv]
    kept_v = np.nonzero(vmap >= 0)[0]
    orig_new = np.full(len(Pd), -1, np.int64)
    orig_new[kept_v] = np.arange(len(kept_v))
    Fo = np.asarray(Fd, np.int64).reshape(-1, 3)
    used = np.unique(orig_new[Fo[face_ok]])
    return vmap[kept_v[used]]


def _prepare(prepared_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes):
    """Read and weld a prepared garment and both bases -> ``(static arrays, bases, welded, kept)``."""
    from app.core.glb_mesh import body_arrays, static_arrays
    Pd, Fd, Ud, image, mime, material = static_arrays(prepared_glb)
    body_u, body_r = body_arrays(unrigged_base_glb), body_arrays(rigged_base_glb)
    if not body_r.joint_names:
        raise ValueError("The rigged base has no skin")
    Pw, Fw0, inv = weld(Pd, Fd, Ud)
    Pk, Fk, keep = drop_small(Pw, Fw0)
    new_of_welded = np.full(len(Pw), -1, np.int64)
    new_of_welded[keep] = np.arange(len(keep))
    return (Pd, Fd, Ud, image, mime, material), (body_u, body_r), (Pw, Fw0, inv), (Pk, Fk, new_of_welded)


def _depth_bands(Q, body_P, *, height_u: float, band, half_x: float
                 ) -> Tuple[np.ndarray, np.ndarray, float]:
    """``(garment band, body band, body centre x)`` of ``align_band_depth``."""
    top = Q[:, 1].max()
    bq = Q[(Q[:, 1] < top - band[0] * height_u) & (Q[:, 1] > top - band[1] * height_u)]
    if len(bq) == 0:
        raise ValueError("No garment vertices in the depth band below its top")
    yl, yh = bq[:, 1].min(), bq[:, 1].max()
    xc = float(np.median(body_P[:, 0]))
    bb = body_P[(body_P[:, 1] > yl) & (body_P[:, 1] < yh) & (np.abs(body_P[:, 0] - xc) < half_x * height_u)]
    if len(bb) == 0:
        raise ValueError("No body vertices at the garment's depth band")
    return bq, bb, xc


def align_band_depth(Q, body_P, *, height_u: float, band=CLOTHING_DEPTH_BAND,
                     half_x: float = CLOTHING_BODY_HALF_X) -> Tuple[np.ndarray, float]:
    """Shift the garment in z so its band ``band`` (fractions of ``height_u`` below its top) is centred on the body
    band at the same heights within ``half_x * height_u`` of the body's centre line (the median x) -> ``(Q, dz)``
    (spike ``fit_dress.py``: the torso band of a dress)."""
    Q = np.array(Q, np.float64)
    bq, bb, _xc = _depth_bands(Q, np.asarray(body_P, np.float64), height_u=height_u, band=band, half_x=half_x)
    dz = float((bb[:, 2].min() + bb[:, 2].max()) / 2 - (bq[:, 2].min() + bq[:, 2].max()) / 2)
    Q[:, 2] += dz
    return Q, dz


def torso_axis(Q, body_P, *, height_u: float, band=CLOTHING_DEPTH_BAND,
               half_x: float = CLOTHING_BODY_HALF_X) -> Tuple[float, float]:
    """``(x, z)`` of the body's vertical axis through the torso band of ``align_band_depth``: the body's median x
    and the middle of the body band's depth — the centre the scale retry widens about (``widen``)."""
    _bq, bb, xc = _depth_bands(np.asarray(Q, np.float64), np.asarray(body_P, np.float64), height_u=height_u,
                               band=band, half_x=half_x)
    return xc, float((bb[:, 2].min() + bb[:, 2].max()) / 2)


def widen(Q, scale: float, *, centre_x: float, centre_z: float, half_width: float) -> np.ndarray:
    """The placed garment ``Q`` widened by ``scale`` about the vertical axis ``(centre_x, centre_z)``: z scaled
    about ``centre_z``; x scaled about ``centre_x`` within ``half_width`` of it and beyond that shifted by the
    widening at ``half_width`` (``x' = x + (scale - 1) * clip(x - centre_x, -half_width, half_width)``), so a
    sleeve keeps its length. y (the length) is never changed. ``scale`` 1.0 returns ``Q`` as a copy."""
    Q = np.array(Q, np.float64)
    if scale == 1.0:
        return Q
    dx = Q[:, 0] - centre_x
    Q[:, 0] = Q[:, 0] + (scale - 1.0) * np.clip(dx, -half_width, half_width)
    Q[:, 2] = centre_z + (Q[:, 2] - centre_z) * scale
    return Q


# Depth allowance (Ruling A68): room in front of and behind the trunk. Measured 2026-11-14 on Kira's Black Blazer
# (``a68-report.md``): the width allowance's ``widen`` already scales z about the torso band's depth centre, but BEFORE
# the push-out — at chest height the placed front lies 19 to 32 mm inside the body, so the push sets the front and the
# back to its clearance at every factor (fitted front / back median 11.9 / 12.9 mm at x1.00, 12.0 / 13.8 mm at x1.10).
# A scale before the push cannot give room there, so the depth allowance acts AFTER the push-out: ``depth_shift`` of
# the pushed placement moves z away from the torso's depth centre ``centre_z`` (the middle of the torso band's depth,
# ``torso_axis`` — not a bone, which lies behind it) by ``ease``, the choice in percent of the torso band's half depth
# (``torso_half_depth``): +10 % stands the front and the back off as a 10 % deeper torso would. The shift is full
# beyond ``DEPTH_RAMP`` of the height from ``centre_z`` and ramps linearly through it (the sides stay joined); it fades
# out over the same distance before ``x_limit`` (the arm joints' distance from the centre line less one ramp: a sleeve
# is never made deeper) and below ``y_limit`` (the arm joints' height: the collar and the neck opening keep their
# size). The fit adds it to the rigged piece's z as the last step of the transfer (``transfer_skinned`` step 5), so it
# never changes which part a vertex rides; the push numbers (``deep_push_share``, ``max_push_m``) measure the push
# alone, every gate of the rigged body judges the fit with the room added. 0 = no shift — the default, so a fit made
# before A68 is unchanged and not due. Auto (the width allowance) never adds depth.
DEPTH_CHOICES: Tuple[int, ...] = (0, 3, 6, 10)
DEPTH_RAMP = 0.03


def depth_choice(settings: Optional[Dict[str, Any]]) -> int:
    """The depth allowance of a piece's fit settings (``depth``): a percent of ``DEPTH_CHOICES`` (a missing or
    unknown value is 0)."""
    value = (settings or {}).get("depth", 0)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in DEPTH_CHOICES:
        return int(value)
    return 0


def torso_half_depth(Q, body_P, *, height_u: float, band=CLOTHING_DEPTH_BAND,
                     half_x: float = CLOTHING_BODY_HALF_X) -> float:
    """Half the depth of the body band of ``torso_axis`` (its z extent / 2) — what a depth percent is a share of."""
    _bq, bb, _xc = _depth_bands(np.asarray(Q, np.float64), np.asarray(body_P, np.float64), height_u=height_u,
                                band=band, half_x=half_x)
    return float((bb[:, 2].max() - bb[:, 2].min()) / 2)


def depth_limits(body_u_P, body_r, *, height_u: float) -> Tuple[float, float]:
    """``(x_limit, y_limit)`` of ``depth_shift`` in the unrigged body's frame: the arm joints' mean distance from the
    body's centre line in x less one ``DEPTH_RAMP``, and the lower arm joint's height — carried from the rigged body
    by its share of the height (the frames differ by a scale and an origin). Without arm joints: 0.75 of the
    widening's half width less one ramp, and 0.21 of the height below the body's top (about the shoulders)."""
    from app.core.rig_contract import norm_bone_name
    P = np.asarray(body_u_P, np.float64)
    ramp = DEPTH_RAMP * height_u
    joints = {norm_bone_name(k): np.asarray(v, np.float64) for k, v in (getattr(body_r, "joint_positions", None)
                                                                         or {}).items()}
    arms = [joints[k] for k in ("leftarm", "rightarm") if k in joints]
    R = np.asarray(body_r.positions, np.float64)
    span_r, span_u = float(np.ptp(R[:, 1])), float(np.ptp(P[:, 1]))
    if arms and span_r > 0 and span_u > 0:
        sc = span_u / span_r
        cx_r = float(np.median(R[:, 0]))
        x_limit = float(np.mean([abs(a[0] - cx_r) for a in arms]) * sc) - ramp
        y_limit = float(P[:, 1].min() + (min(a[1] for a in arms) - R[:, 1].min()) * sc)
        return x_limit, y_limit
    return 0.75 * CLOTHING_BODY_HALF_X * height_u - ramp, float(P[:, 1].max() - 0.21 * height_u)


def depth_shift(Q, ease: float, *, centre_x: float, centre_z: float, x_limit: float, y_limit: float,
                ramp: float) -> np.ndarray:
    """The depth allowance (block above) per position of ``Q`` (body frame): the z shift ``ease · wz · wx · wy`` with
    ``wz = clip((z - centre_z) / ramp, -1, 1)``, ``wx = clip((x_limit - |x - centre_x|) / ramp, 0, 1)``,
    ``wy = clip((y_limit - y) / ramp, 0, 1)``. x and y never change."""
    Q = np.asarray(Q, np.float64)
    if ease == 0.0 or not len(Q):
        return np.zeros(len(Q))
    wz = np.clip((Q[:, 2] - centre_z) / ramp, -1.0, 1.0)
    wx = np.clip((x_limit - np.abs(Q[:, 0] - centre_x)) / ramp, 0.0, 1.0)
    wy = np.clip((y_limit - Q[:, 1]) / ramp, 0.0, 1.0)
    return ease * wz * wx * wy


#: The front / back of the trunk (``front_back_rows``): within this angle (degrees) of straight ahead (+z) / behind.
FRONT_BACK_DEG = 35.0


def front_back_rows(Q, centre_x: float, centre_z: float) -> Tuple[np.ndarray, np.ndarray]:
    """``(front, back)`` row masks of the positions ``Q``: within ``FRONT_BACK_DEG`` of +z / -z seen from the vertical
    axis ``(centre_x, centre_z)`` — the gaps "front / back" of the depth allowance (Ruling A68)."""
    Q = np.asarray(Q, np.float64)
    if not len(Q):
        return np.zeros(0, bool), np.zeros(0, bool)
    ang = np.degrees(np.arctan2(Q[:, 0] - centre_x, Q[:, 2] - centre_z))
    return np.abs(ang) <= FRONT_BACK_DEG, np.abs(ang) >= 180.0 - FRONT_BACK_DEG


def depth_ease(Q, ease: float, **frame: float) -> np.ndarray:
    """``Q`` with ``depth_shift`` added to z (a copy) — what the mesh view previews (``fitWiden.ts``
    ``easeInPlace``)."""
    Q = np.array(Q, np.float64)
    Q[:, 2] += depth_shift(Q, ease, **frame)
    return Q


def push_numbers(Q0_pre, Q_post, exclude: Optional[np.ndarray] = None) -> Dict[str, float]:
    """``max_push_m`` and ``deep_push_share`` of a push-out (positions in metres, as ``clothing_metrics``; ``exclude``
    as there)."""
    push = np.linalg.norm(np.asarray(Q_post, np.float64) - np.asarray(Q0_pre, np.float64), axis=1)
    if exclude is not None and len(exclude) == len(push) and np.any(exclude):
        push = np.where(np.asarray(exclude, bool), 0.0, push)
    return {"max_push_m": round(float(push.max()) if len(push) else 0.0, 4),
            "deep_push_share": round(float((push > DEEP_PUSH_M).mean()) if len(push) else 0.0, 4)}


def gate_keys(reasons: List[str]) -> List[str]:
    """The metric keys of ``gate`` reasons (each reason starts with its key)."""
    return [str(r).split(" ", 1)[0].rstrip(":") for r in reasons]


def too_small(reasons: List[str]) -> bool:
    """A refusal whose every reason is a ``SCALE_RETRY_KEYS`` gate: the piece is too small for the body."""
    keys = gate_keys(reasons)
    return bool(keys) and all(key in SCALE_RETRY_KEYS for key in keys)


# Width allowance (Ruling A47): a fit that PASSES may still lie tight — the spike on Kai's jacket (``a47-spike.md``,
# width-only about the torso axis): x1.00 deep push 0.111 / torso < 1.5 cm 21 %, x1.03 0.091 / 18 %, x1.06 0.079 /
# 15 %, x1.10 0.069 / 11 % with flaps standing off below the armpits, x1.15 refused (a sleeve off the upper arm); the
# hem and the collar moved at most 5 mm. So the automatic retry also widens an ACCEPTED fit whose deep push share
# exceeds ``ALLOWANCE_DEEP`` or whose trunk lies tight (clearance below ``TORSO_TIGHT_M``) beyond
# ``ALLOWANCE_TIGHT``: the steps of ``SCALE_RETRY_STEPS`` above the accepted scale (1.0, or the step a too-small
# retry passed at; never beyond 1.08), smallest first; it takes the smallest step that passes every gate and clears
# both numbers, else the smallest passing step that improves them (neither worse, one lower), else the fit as
# accepted. A piece's fit settings may fix the allowance instead (``ALLOWANCE_CHOICES``, percent: that ``widen``
# factor and no retry — the sides, and the depth in proportion before the push-out; room in front and behind after
# the push-out is the separate depth allowance, Ruling A68). A fit whose trunk is mapped from its base fit (outfit bodies) takes
# its width from the base fit: no allowance there.
ALLOWANCE_CHOICES: Tuple[Any, ...] = ("auto", 0, 3, 6, 10)
ALLOWANCE_DEEP = 0.08
ALLOWANCE_TIGHT = 0.18


def allowance_choice(settings: Optional[Dict[str, Any]]) -> Any:
    """The fit allowance of a piece's fit settings (``allowance``): "auto" or a percent of ``ALLOWANCE_CHOICES``
    (a missing or unknown value is "auto")."""
    value = (settings or {}).get("allowance", "auto")
    if isinstance(value, bool):
        return "auto"
    if isinstance(value, (int, float)) and value in ALLOWANCE_CHOICES:
        return int(value)
    return "auto"


def allowance_trigger(m: Dict[str, Any]) -> List[str]:
    """The width-allowance rules an accepted fit's metrics meet (block above): ``deep_push_share`` /
    ``torso_tight_share``."""
    out = []
    deep, tight = m.get("deep_push_share"), m.get("torso_tight_share")
    if isinstance(deep, (int, float)) and math.isfinite(deep) and deep > ALLOWANCE_DEEP:
        out.append("deep_push_share")
    if isinstance(tight, (int, float)) and math.isfinite(tight) and tight > ALLOWANCE_TIGHT:
        out.append("torso_tight_share")
    return out


def _improves(first: Dict[str, Any], other: Dict[str, Any]) -> bool:
    keys = ("deep_push_share", "torso_tight_share")
    a = [float(first.get(k) or 0.0) for k in keys]
    b = [float(other.get(k) or 0.0) for k in keys]
    return all(y <= x + 1e-9 for x, y in zip(a, b)) and any(y < x - 1e-9 for x, y in zip(a, b))


def scale_retry(Q, push, finish, *, centre_x: float, centre_z: float, half_width: float,
                steps: Tuple[float, ...] = SCALE_RETRY_STEPS, allowance: Any = "auto",
                widen_accepted: bool = True) -> Tuple["FitResult", Dict[str, Any]]:
    """Fit the placed garment ``Q``; when refused as ``too_small``, again widened (``widen``) by each of ``steps``
    until one passes -> ``(result, info)``. Ruling A47: ``allowance`` a percent (``allowance_choice``) fits once at
    that width and nothing else; "auto" with ``widen_accepted`` also widens an accepted fit that lies tight (the
    width allowance, block above) — ``info["allowance"]`` ``{setting, trigger, numbers, factor, attempts}``.

    ``push(Qs)`` -> ``(Qp, disp, numbers)`` (the push-out of the placed positions and its ``push_numbers``),
    ``finish(Qs, Qp, disp)`` -> the ``FitResult`` of that push-out. A step whose push numbers already fail the
    ``SCALE_RETRY_KEYS`` gates is not finished (no transfer). ``info``: ``factor`` = the scale of the returned
    result (1.0 unwidened — a pass at 1.0, another refusal, or no step passed: then the unwidened refusal is
    returned), ``max_tried`` = the largest scale tried (1.0 without a retry), ``attempts`` = per tried scale
    (1.0 first) ``{scale, ok, reasons, deep_push_share, max_push_m}`` — empty without a retry."""
    info: Dict[str, Any] = {"factor": 1.0, "max_tried": 1.0, "attempts": [], "centre": [centre_x, centre_z],
                            "half_width_u": half_width}
    if allowance != "auto":
        scale = round(1.0 + float(allowance) / 100.0, 4)
        Qs = widen(Q, scale, centre_x=centre_x, centre_z=centre_z, half_width=half_width)
        Qp, disp, _numbers = push(Qs)
        fixed = finish(Qs, Qp, disp)
        info.update(factor=scale, max_tried=scale)
        info["allowance"] = {"setting": allowance, "trigger": [], "factor": scale, "attempts": [],
                             "numbers": {k: fixed.metrics.get(k) for k in ("deep_push_share", "torso_tight_share")}}
        return fixed, info
    def widen_more(accepted: "FitResult", at: float) -> "FitResult":
        """The width allowance of an accepted fit at scale ``at`` (block above)."""
        trigger = allowance_trigger(accepted.metrics) if widen_accepted else []
        info["allowance"] = {"setting": "auto", "trigger": trigger, "factor": at, "attempts": [],
                             "numbers": {k: accepted.metrics.get(k) for k in ("deep_push_share", "torso_tight_share")}}
        if not trigger:
            return accepted
        improving: Optional[Tuple[float, "FitResult"]] = None
        for scale in (s_ for s_ in steps if s_ > at + 1e-9):
            info["max_tried"] = max(info["max_tried"], scale)
            Qs = widen(Q, scale, centre_x=centre_x, centre_z=centre_z, half_width=half_width)
            Qp, disp, _numbers = push(Qs)
            result = finish(Qs, Qp, disp)
            better = result.ok and _improves(accepted.metrics, result.metrics)
            clears = better and not allowance_trigger(result.metrics)
            info["allowance"]["attempts"].append({
                "scale": scale, "ok": bool(result.ok), "reasons": list(result.reasons), "improves": bool(better),
                "clears": bool(clears),
                **{k: result.metrics.get(k) for k in ("deep_push_share", "torso_tight_share", "max_push_m")}})
            if better and improving is None:
                improving = (scale, result)
            if clears:
                improving = (scale, result)
                break
        if improving is None:
            return accepted
        info["factor"] = info["allowance"]["factor"] = improving[0]
        return improving[1]

    Qp, disp, _numbers = push(Q)
    first = finish(Q, Qp, disp)
    if first.ok:
        return widen_more(first, 1.0), info
    if not too_small(first.reasons):
        return first, info

    def attempt(scale, ok, reasons, m):
        info["attempts"].append({"scale": scale, "ok": bool(ok), "reasons": list(reasons),
                                 **{key: m.get(key) for key in SCALE_RETRY_KEYS}})

    attempt(1.0, False, first.reasons, first.metrics)
    push_gates = {key: CLOTHING_GATES[key] for key in SCALE_RETRY_KEYS}
    for scale in steps:
        info["max_tried"] = scale
        Qs = widen(Q, scale, centre_x=centre_x, centre_z=centre_z, half_width=half_width)
        Qp, disp, numbers = push(Qs)
        ok, reasons = gate(numbers, push_gates)
        if not ok:
            attempt(scale, False, reasons, numbers)
            continue
        result = finish(Qs, Qp, disp)
        attempt(scale, result.ok, result.reasons, result.metrics)
        if result.ok:
            info["factor"] = scale
            return widen_more(result, scale), info
    return first, info


def fit_clothing(unrigged_garment_glb: bytes, unrigged_base_glb: bytes, rigged_base_glb: bytes, *,
                 masks, slots, limb_source: Optional[Dict[str, Any]] = None,
                 settings: Optional[Dict[str, Any]] = None) -> FitResult:
    """Fit a prepared (decimated) clothing mesh onto the rigged base body (dress spike ``fit_dress.py``).

    ``masks``: ``{"body": ..., "garment": ...}`` — the full-frame body mask of the bald front view the unrigged base
    was generated from and the full-frame garment mask of the accepted ghost front view (same framing, never the
    cut-out). ``slots``: the piece's outfit slots (a skirt blend needs a ``SKIRT_SLOTS`` slot).

    ``k`` = rigged height / unrigged height. Placement by the shared framing, depth by the torso band
    (``align_band_depth``), push-out to ``CLEAR_M`` without the crown spread, side-kept (``push_kept``; 6 smoothing
    passes in the first 6 of 8 iterations), the skinned transfer (``transfer_skinned``) with the waist at the
    garment top minus ``CLOTHING_WAIST_DROP`` of the body height (sleeves ride the arms above it),
    ``clothing_weights`` (skirt when ``is_skirt``), the gate ``CLOTHING_GATES``. The output joints are the bones the
    weights use (contract bones and, over their tissue, extension bones), in skin order.

    A fit refused only because the piece is too small (``too_small``) is fitted again widened about the torso axis
    (``scale_retry``, ``widen``, steps ``SCALE_RETRY_STEPS``); the push numbers of a widened fit are measured from
    the widened placement. ``metrics["scale_retry"]`` = the applied factor (1.0 unwidened), ``scale_retry_max`` =
    the largest tried (1.0 without a retry), ``report["scale_retry"]`` the attempts with their gate numbers.

    ``masks["opening"]`` (optional, ``garment_source.opening_masks``): ``(opening, ghost mask[, shown])`` in the
    ghost's own frame — the garment's inside seen through an opening is left out before the fit (``opening_lining``,
    Ruling A35; ``shown``, the worn view's body pixels, Ruling A51), ``report["opening"]``.

    ``limb_source`` (a refit — ``garment_source``): the source fit of the same prepared mesh on another base,
    ``{x0 (output vertices, 3), w0 (output vertices, len(names0)), names0, frames (its body's limb_frames),
    kinds}``; its limbs are aligned onto this body's (``align_limbs`` inside ``transfer_skinned``). Skipped
    (``report["transfer"]["limbs"]["skipped"]``) when its vertex count is not this fit's.

    ``settings`` (Ruling A47, the piece's fit settings — ``garments.fit_settings``): ``sleeves_left`` /
    ``sleeves_right`` (``SLEEVE_CHOICES``; ``place_sleeves``, report ``transfer.sleeves``) and ``allowance``
    (``ALLOWANCE_CHOICES``; ``scale_retry``, report ``scale_retry.allowance``) and ``depth`` (Ruling A68,
    ``DEPTH_CHOICES``; ``depth_shift`` after the push-out, report ``depth``). The vertices laid onto the arm are
    left out of the placement push numbers. ``metrics`` adds the skin seen in each sleeve
    (``sleeve_skin_left_cm2`` / ``sleeve_skin_right_cm2``, ``sleeve_skin_seen``; ``report["arm_light"]``), the
    trunk's tight share and the sleeve stretch.
    """
    body_mask, garment_mask = _mask(masks["body"]), _mask(masks["garment"])
    if body_mask.shape != garment_mask.shape:
        raise ValueError("The masks must share one image size (same framing): "
                         f"{body_mask.shape} vs {garment_mask.shape}")
    (Pd, Fd, Ud, image, mime, material), (body_u, body_r), (Pw, Fw0, inv), (Pk, Fk, new_of_welded) = \
        _prepare(unrigged_garment_glb, unrigged_base_glb, rigged_base_glb)
    if len(Pk) == 0:
        raise ValueError("The garment mesh has no faces")
    lining, open_report = None, None
    if masks.get("opening") is not None:
        lining, open_report = opening_lining(Pk, Fk, *masks["opening"])
        if lining.any():
            stay = _open_faces(Fk, lining)
            keep2 = np.unique(Fk[stay])
            new2 = np.full(len(Pk), -1, np.int64)
            new2[keep2] = np.arange(len(keep2))
            Pk, Fk, lining = Pk[keep2], new2[Fk[stay]], lining[keep2]
            new_of_welded = np.where(new_of_welded >= 0, new2[np.maximum(new_of_welded, 0)], -1)
        else:
            lining = None
    uv_correspondence(body_u, body_r)
    height_u = float(np.ptp(body_u.positions[:, 1]))
    height_r = float(np.ptp(body_r.positions[:, 1]))
    k = height_r / height_u if height_u > 0 else float("nan")
    if not (k > 0 and math.isfinite(k)):
        raise ValueError("Could not measure the unrigged -> rigged scale")

    Q = place_by_framing(Pk, body_u.positions, body_mask, garment_mask)
    Q, dz = align_band_depth(Q, body_u.positions, height_u=height_u)
    limbs, limbs_skipped = None, ""
    if limb_source is not None:
        src = _out_index(Pd, Fd, inv, new_of_welded, lining)
        x0 = np.asarray(limb_source["x0"], np.float64)
        if len(x0) != len(src):
            limbs_skipped = f"the source has {len(x0)} vertices, this fit {len(src)}"
        else:
            w0 = np.asarray(limb_source["w0"], np.float64)
            x0k, w0k = np.zeros((len(Pk), 3)), np.zeros((len(Pk), w0.shape[1]))
            x0k[src], w0k[src] = x0, w0
            limbs = {"x0": x0k, "w0": w0k, "names0": list(limb_source["names0"]),
                     "frames": limb_source["frames"], "kinds": tuple(limb_source.get("kinds") or ("arm", "leg"))}
    margin = SDF_MARGIN_M / k
    choices = sleeve_choices(settings)
    allowance = allowance_choice(settings)
    depth = depth_choice(settings)
    # Ruling A68: the depth allowance's shift in body units and its frame (set below, before the first finish).
    ease_u: List[float] = [0.0]
    depth_args: List[Dict[str, float]] = [{}]
    # the vertices the first finished fit laid onto the arm: left out of every later push number (scale steps)
    fitted_rows: List[Optional[np.ndarray]] = [None]

    def push(Qs):
        sdf = body_sdf(body_u.positions, body_u.faces, vox=VOX_M / k,
                       bounds=(Qs.min(0) - margin, Qs.max(0) + margin))
        disp = push_kept(Qs, _adjacency(Fk, len(Qs)), sdf, clear=CLEAR_M / k, iterations=PUSH_ITERATIONS,
                         smooth_until=PUSH_SMOOTH_UNTIL, margin=SIDE_MARGIN_M / k)
        Qp = Qs + disp
        return Qp, disp, push_numbers(Qs * k, Qp * k, exclude=fitted_rows[0])

    def finish(Qs, Qp, disp) -> FitResult:
        split_y = float(Qp[:, 1].max() - CLOTHING_WAIST_DROP * height_u)
        # Ruling A68: the depth allowance of the pushed placement, added on the rigged body (``depth_shift``).
        ease_z = depth_shift(Qp, ease_u[0], **depth_args[0]) if ease_u[0] else None
        X, transfer_report = transfer_skinned(Qp, body_u, body_r, faces=Fk, k=k, split_y=split_y, limbs=limbs,
                                              Q_pre=Qs, sleeves=choices, ease_z=ease_z)
        fitted = transfer_report.pop("sleeve_fitted", None)
        if fitted_rows[0] is None and fitted is not None and np.any(fitted):
            fitted_rows[0] = fitted
        if limbs_skipped:
            transfer_report["limbs"] = {"skipped": limbs_skipped}
        skirt = is_skirt(X, body_r, slots)
        J, W = clothing_weights(X, body_r, skirt=skirt)
        used = np.unique(J[W > 0])
        remap = np.zeros(max(len(body_r.joint_names), int(J.max()) + 1 if J.size else 0), np.int64)
        remap[used] = np.arange(len(used))
        J = np.where(W > 0, remap[J], 0)
        names = [body_r.joint_names[i] for i in used]
        m = clothing_metrics(X, Fk, Qs * k, Qp * k, transfer_report, exclude=fitted)
        torso_mapped = "torso" in ((transfer_report.get("limbs") or {}).get("chains") or {})
        ok, reasons = gate(m, clothing_gates(torso_mapped=torso_mapped))

        garment = _garment_out(Pd, Fd, Ud, inv, new_of_welded, X, Fk, J, W, names, image, mime, material,
                               lining)
        # The generator's roughness map rides on the same UVs (Ruling A36: the fit keeps it).
        garment.mr_image, garment.mr_mime = static_mr_image(unrigged_garment_glb)
        crotch = crotch_height(body_r)
        hips = names.index(body_r.joint_names[joint_index(body_r, "hips")]) if skirt else -1
        report = {
            "k": float(k),
            "vertices": {"prepared": int(len(Pd)), "welded": int(len(Pw)), "kept": int(len(Pk)),
                         "out": int(len(garment.positions))},
            "dropped_components_faces": int(len(Fw0) - len(Fk)),
            "opening": open_report,
            "depth_shift_u": dz,
            "push": {"moved": int((np.linalg.norm(disp, axis=1) > MOVED_EPS_M / k).sum()),
                     "max_m": float(np.linalg.norm(disp, axis=1).max() * k) if len(disp) else 0.0},
            "waist_y_u": split_y,
            "transfer": transfer_report,
            "crotch_y_m": crotch,
            "hem_y_m": float(X[:, 1].min()),
            "skirt": bool(skirt),
            "skirt_zone_share": float((X[:, 1] < crotch + SKIRT_ZONE_M).mean()) if skirt else 0.0,
            "hem_hips_weight": (float(((J == hips) * W).sum(1)[X[:, 1] <= X[:, 1].min() + 0.01].mean())
                                if skirt else None),
            "joints": names,
        }
        return FitResult(garment=garment, metrics=m, ok=ok, reasons=reasons, report=report)

    centre_x, centre_z = torso_axis(Q, body_u.positions, height_u=height_u)
    # A trunk mapped from its base fit (outfit bodies) takes its width from that fit: no allowance here.
    torso_source = bool(limbs) and "torso" in (limbs.get("frames") or {})
    # Ruling A68: the depth allowance — on such a trunk inherited from the base fit as well.
    half_depth = torso_half_depth(Q, body_u.positions, height_u=height_u)
    x_limit, y_limit = depth_limits(body_u.positions, body_r, height_u=height_u)
    depth_args[0] = {"centre_x": centre_x, "centre_z": centre_z, "x_limit": x_limit, "y_limit": y_limit,
                     "ramp": DEPTH_RAMP * height_u}
    ease_u[0] = 0.0 if torso_source else depth / 100.0 * half_depth
    result, info = scale_retry(Q, push, finish, centre_x=centre_x, centre_z=centre_z,
                               half_width=CLOTHING_BODY_HALF_X * height_u,
                               allowance="auto" if torso_source else allowance, widen_accepted=not torso_source)
    if torso_source and allowance != "auto" and isinstance(info.get("allowance"), dict):
        info["allowance"]["inherited"] = True
    result.metrics["scale_retry"] = info["factor"]
    result.metrics["scale_retry_max"] = info["max_tried"]
    result.report["scale_retry"] = info
    # Ruling A47: the skin seen in each sleeve of the fit as published (the arm light).
    g = result.garment
    Wd = np.zeros((len(g.positions), len(g.joint_names)))
    np.add.at(Wd, (np.repeat(np.arange(len(g.positions)), g.joints.shape[1]), g.joints.ravel()), g.weights.ravel())
    skin = sleeve_skin_seen(g.positions, g.indices,
                            {side: _arm_share(Wd, g.joint_names, side) for side in ("left", "right")}, body_r)
    for side in ("left", "right"):
        result.metrics[f"sleeve_skin_{side}_cm2"] = skin.get(side)
    result.report["arm_light"] = arm_light(skin)
    result.report["fit_settings"] = {"sleeves_left": choices["left"], "sleeves_right": choices["right"],
                                     "allowance": allowance, "depth": depth}
    result.report["depth"] = {"setting": depth, "ease_mm": round(ease_u[0] * k * 1000.0, 1),
                              "half_depth_mm": round(half_depth * k * 1000.0, 1),
                              "inherited": bool(torso_source and depth)}
    return result
