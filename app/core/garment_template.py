"""Garment templates — a worn piece in mode ``template`` is a sewing pattern
draped onto the character's plain body (spec
``docs/superpowers/specs/2026-11-16-garment-templates-design.md``; spike A135,
P1 Ruling A138).

The path, per (piece, body):

1. **Parameters** (once per item): the vision task ``TASK`` reads the item's
   picture + text and answers JSON (``suggest_params``); ``validate_params``
   checks it against ``PARAM_SPEC``. The user edits them in the Figure tab's
   parameter dialog; ``set_params`` stores them on the item as
   ``outfit_piece.template = {params, source, updated_at}``. No parameters → the
   piece is left off ("needs parameters", Ruling A119).
2. **Panels** (``panel_spec``, CPU, < 1 s): the body is measured from the plain
   rigged base model (``measure_body``: waist / hip / chest band heights and
   circumferences off horizontal slices, Y-up glTF metres); the pygarment
   (vendored, ``app/third_party/pygarment``) panels of the kind are sized from
   those measurements and sampled to quad grids.
3. **Drape** (Blender, one CPU run, ``app/blender/scripts/garment_template_build.py``):
   the panels are wrapped round the body, the seams merged, the top row pinned
   at a radius that follows the body (the spike's open point), cloth-draped on a
   voxel-remeshed posed-body collider with the ``fabric`` preset
   (``FABRICS``), thickened, textured by projecting the piece's front / back
   cut-out views (else its item picture, masked to the garment) onto the panel UVs,
   skinned by nearest-face Data Transfer with the free-hanging cloth's weights
   inpainted from its neighbours, and given one pose shape per ``SHAPE_POSES``
   pose (Ruling A141: the cloth draped again in that pose, taken back through the
   inverse skinning, stored as a morph target; the renderers blend them by the leg
   directions, ``record["pose_shapes"]``). Exported as one garment node.
4. **Assembly**: the drape GLB is grafted like an own-mesh clothing piece
   (``garment_assembly``; Ruling A133 hides the body faces it covers).

Cache: ``templates/{item}_{tsig}.glb + .json`` under the character's garment
store; ``tsig`` = md5[:12] over the parameters, ``TEMPLATE_VERSION``, the base
model sha256, the texture source sha256 and what the drape is cut against: the worn
pieces UNDER it (their drape keys / fit identities, a boot it hangs over), the jacket
allowance and the chest shaping (``key_for``) — never a piece worn over it. A top's drape also keeps its pattern islands beside it
(``{item}_{tsig}.islands.json``, ``islands_path``; the record's ``islands`` = file, sha256, px_per_cm).
With the param ``texture`` "cut" the assembly swaps the drape's projection image for the "texture from cut" atlas
(``atlas_for``; keyed by the islands sha, never by ``tsig`` — ``texture`` is ``TEXTURE_ONLY``). The islands do not
wait for the drape: ``garment_template_cut`` cuts the pattern alone (the same builder with ``cut_only``, seconds) and
a drape of the same cut writes the same bytes (its record's ``cut_sig``).
A failed drape is recorded in ``templates/failed/`` and the piece
is left off with its reason until Retry. 0 hub jobs; the only paid call is the
one parameter suggestion.

Kinds: every kind of ``KINDS`` is built (``BUILT_KINDS``; A233 trousers last). A kind named but not built would
be left off with ``KIND_NOT_BUILT``.
"""
import glob as _glob
import hashlib
import json
import logging
import math
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCRIPT = "garment_template_build"
#: The spike's evaluator script (modes mesh / panels / from_body / necklace).
SPIKE_SCRIPT = "garment_template_drape.py"
#: Bumped when the same parameters drape differently.
#: 6 (A198): the texture projection paints the outer layer only (prints were mirrored), the bake pose search tries
#: the arm angles it names, a lower layer's collider is thickened inward, a dress with a bodice keeps its slit and
#: the rim metrics read the open borders.
#: 7: a hollow drape collider (a thick-shell body open to the outside) loses its inner wall (``_drop_inner_walls``).
#: (A221 adds the strapless top — a new kind of piece; the existing drapes keep their keys, so no bump.)
#: 8 (A230): the source pictures are cut by ``garment_matte`` (key + BiRefNet consensus, rim un-mixed and filled from
#: inside) and the projection bake fills its empty texels by push-pull — CPU only, the stored views stay.
#: 9 (A239): the fitted kinds' crotch is where the body closes over the centre line (``_crotch``: the highest of the
#: per-column lowest hits of upward rays at the centre, so a column grazing an inner thigh does not decide), no
#: longer the lowest Hips-weighted vertex several cm down the inner thighs — a brief's gusset, a boxer's or a
#: stocking's hem and a trouser's crotch anchor move up on a body whose thighs stand apart.
#: 10: tops get pattern-piece UVs (front/back/sleeves/band at one px/cm) and an islands output
#: (``{item}_{tsig}.islands.json`` beside the drape; plan 2026-11-20-template-cut-uv-texture).
TEMPLATE_VERSION = 10
#: Step 3a (decision D7 b): the fitted kinds' own version, in the drape key of a ``FITTED_KINDS`` piece only — so a
#: change of the fitted cut re-drapes the fitted pieces and no top / skirt / dress / jacket.
#: 1: the fitted kinds get sewing-pattern UV islands (``fitted_pattern``) instead of the planar box UV.
FITTED_VERSION = 1
#: The LLM task (``llm_tasks.TASK_TYPES``; unrouted → ``image_recognition``) and its template.
TASK = "garment_template_params"
#: Completion cap for the JSON answer.
MAX_TOKENS = 400

KINDS = ("skirt", "dress", "top", "jacket", "trousers", "briefs", "bra", "gloves", "tights")
BUILT_KINDS = ("skirt", "dress", "top", "jacket", "trousers", "briefs", "bra", "gloves", "tights")
#: A223: the close-fitting kinds — cut from the body's own surface (``fitted_spec``: a region of the plain body, laid
#: out of it and relaxed by a short pinned cloth run), not wrapped from panel rows: briefs (waistband + gusset
#: pinned), a bra (underband + straps pinned; molded cups are pinned whole = rigid) and gloves (the cuff and the hand
#: pinned; the fingers are a tight overlay, never draped one by one). Chains, belts and jewellery are no part of the
#: cut.
#: A233: trousers are cut the same way (the hips and both legs from the waistband to the hem), then widened round
#: each leg's bone axis by the leg shape (``trouser_spec``).
FITTED_KINDS = ("briefs", "bra", "gloves", "tights", "trousers")
#: Kinds with a bodice over the shoulders (Ruling A142): built as a tube from the hem to the shoulder line, a yoke
#: over the shoulders up to the neckline, armholes and sleeves (``bodice_spec``). A dress is one of them unless it is
#: strapless. A221: a top may be strapless as well (bodice / bustier / corset: a tube pinned under the arms, built
#: like a strapless dress's top); a jacket is always covered.
UPPER_KINDS = ("top", "jacket")
#: The layer rank of a kind: a piece drapes over the READY template drapes of a lower rank (Ruling A142: a jacket
#: over a top or a dress; the lower drape is a collider of the cloth run).
LAYER_RANK = {"skirt": 1, "trousers": 1, "dress": 1, "top": 1, "jacket": 2, "briefs": 0, "bra": 0, "gloves": 1,
              "tights": 0}
WAIST_HEIGHTS = ("high", "natural", "low")
SLIT_SIDES = ("none", "left", "right", "front", "back")
SLEEVES = ("none", "cap", "short", "elbow", "long")
#: Sleeve length as a share of the arm (shoulder joint to wrist joint): a cap sleeve just covers the shoulder
#: joint, a short one reaches a third down the upper arm, elbow = the elbow joint (half the arm on the reference
#: body: 0.249 m upper arm + 0.245 m forearm), long = to the wrist.
SLEEVE_SHARE = {"none": 0.0, "cap": 0.12, "short": 0.3, "elbow": 0.52, "long": 0.97}
NECKLINES = ("crew", "v", "scoop", "boat", "straight", "sweetheart")
#: A221: the corset top edges of a top without a covered bodice — strapless or with straps (straight across the chest,
#: or a sweetheart dip at the front centre); a covered bodice takes the others (``validate_params`` resets a mismatch).
STRAPLESS_NECKLINES = ("straight", "sweetheart")
#: The neckline's depth at the front centre below the jugular notch (``front_y`` = the shoulder-joint height, Ruling
#: A144) when ``neck_depth_m`` is 0 (metres; a crew neck sits ~1 cm under the notch).
NECK_DEPTH = {"crew": 0.01, "v": 0.12, "scoop": 0.08, "boat": 0.0, "straight": 0.0, "sweetheart": 0.0}
#: A221: a sweetheart top edge dips this far at the front centre (``neck_depth_m`` 0), at most SWEETHEART_MAX_M,
#: over +-SWEETHEART_HALF_RAD round the front centre: drop = depth * (1 - |angle off centre| / half)^2 (0 outside).
SWEETHEART_DIP_M = 0.05
SWEETHEART_MAX_M = 0.10
SWEETHEART_HALF_RAD = 0.5
#: A221: a strapless top's top edge lies this far under the chest band: at the band the pinned top row met the
#: underside of the T-posed arm on a real body (one edge stretched 1.5x, the strapless dress's same row).
STRAPLESS_UNDERARM_M = 0.02
#: A221: a strapless top reaches at least this far below its top edge (the chest band).
STRAPLESS_MIN_M = 0.08
SHOULDERS = ("strapless", "straps", "covered", "off_shoulder")
# --- A229: the off-shoulder (Carmen / Bardot) blouse --------------------------------------------------------------
#: An off-shoulder top or dress is built as a covered bodice with sleeves and cut below the shoulders along an elastic
#: band: across the chest and the back at ``band_drop_m`` under the shoulder line, and round the top of each upper arm
#: ``OFF_SHOULDER_ARM_M`` out from the shoulder joint (T-posed). The band (``band_m`` high) is pinned, so it stays
#: below the shoulders and holds the sleeves; ``off_shoulder_spec``.
OFF_SHOULDER_ARM_M = 0.07
#: The sleeves an off-shoulder piece may have (a cap sleeve or none would be cut away whole with the shoulder).
OFF_SHOULDER_SLEEVES = ("short", "elbow", "long")
#: Front lacing: none, or a laced opening at the centre front from the band down ``lace_depth_m`` (the cord is the
#: picture's, painted by the texture projection; the opening is ``LACE_GAP_M`` wide at the band, closing to 0).
LACINGS = ("none", "front")
LACE_GAP_M = 0.03
#: The parameters only an off-shoulder piece reads — left out of ``tsig`` for every other piece, so adding them kept
#: the existing drapes' keys.
OFF_SHOULDER_FIELDS = ("band_m", "band_drop_m", "lacing", "lace_depth_m")
FRONTS = ("closed", "open")
# --- A223: the fitted kinds' choices -----------------------------------------------------------------------------
#: Briefs: where the waistband sits (``fitted_spec``: low = 30 %, mid = 65 % of the way from the hip line to the
#: waist, high = the waist).
RISES = ("low", "mid", "high")
RISE_SHARE = {"low": 0.3, "mid": 0.65, "high": 1.0}
#: A waistband's height (metres; it is the pinned band) — none still pins the top 12 mm.
WAISTBANDS = ("none", "thin", "wide")
#: A235 briefs: "fabric" = side panels (``side_width_m``); "string" = only a front and a back panel, joined over the
#: hips by thin bands ``string_width_m`` high along the waist line (string bikini, tanga, side-tie).
BRIEF_SIDES = ("fabric", "string")
WAISTBAND_M = {"none": 0.0, "thin": 0.012, "wide": 0.03}
#: Bra cup shapes: molded (a rigid shell, pinned whole), triangle (a peak over the bust point), bandeau (a band
#: round the chest, no separate cups), balconette (a straight top edge).
CUP_STYLES = ("molded", "triangle", "bandeau", "balconette")
#: The fabric between the cups: (half width, height above the underbust line), metres.
CENTER_GORES = ("none", "narrow", "wide")
GORE = {"none": (0.008, 0.0), "narrow": (0.012, 0.03), "wide": (0.022, 0.05)}
CLOSURES = ("back_hook", "front", "none")
#: A223 — the straps of a piece with a band under the chest (shared: ``strap_spec``). none · thin · wide (over the
#: shoulders, down the back to the band) · halter (round the back of the neck) · cross (over the shoulders, crossing
#: on the back to the other side of the band).
STRAPS = ("none", "thin", "wide", "halter", "cross")
STRAP_WIDTH_M = {"none": 0.0, "thin": 0.012, "wide": 0.022, "halter": 0.016, "cross": 0.014}
#: Gloves.
FINGERS = ("full", "fingerless", "none")
GLOVE_LENGTHS = ("wrist", "forearm", "elbow", "opera")
CUFFS = ("none", "flared", "folded")
#: A223 tights / stockings / socks: full tights to the waist, hold-up stockings (a grip band on the thigh), thigh-high
#: stockings (garter tabs optional), knee-high socks; the foot closed, footless or a stirrup under the arch.
TIGHTS_STYLES = ("tights", "hold_up", "thigh_high", "knee_high")
TIGHTS_FEET = ("closed", "footless", "stirrup")
GARTERS = ("none", "tabs")
COLLARS = ("none", "stand", "lapel")
# --- A233: trousers --------------------------------------------------------------------------------------------
#: How far a trouser leg reaches: shorts (a third of the way from the crotch to the knee), knee, capri (mid-calf),
#: ankle (above the ankle bone) or full (to the ankle joint, over the top of the shoe).
TROUSER_LENGTHS = ("shorts", "knee", "capri", "ankle", "full")
#: The hem height per length: ``(from, to, share, extra_m)`` = from + share x (to - from) + extra_m, the anchors read
#: off the body per side (``crotch`` where the body closes over the centre line, ``garment_template_fitted._crotch``
#: A239; ``knee`` / ``ankle`` the Leg / Foot joints). The builder computes the same sum
#: (``garment_template_fitted.trouser_hem``).
TROUSER_HEM = {"shorts": ("crotch", "knee", 0.3, 0.0), "knee": ("knee", "ankle", 0.06, 0.0),
               "capri": ("knee", "ankle", 0.5, 0.0), "ankle": ("knee", "ankle", 0.85, 0.0),
               "full": ("knee", "ankle", 1.0, -0.01)}
#: Leg shapes. ``LEG_SHAPE_R`` = the leg's target radius round its bone axis at the knee and at the ankle, as shares
#: of the thigh radius (read 3 cm under the crotch, with the ease): the cloth is widened to it where the leg is
#: thinner (never pulled in), straight down from the crotch to the knee to the ankle. skinny = no widening (the leg
#: plus the offset), flared = fitted to the knee (share 0: the leg itself) and wide at the hem.
LEG_SHAPES = ("skinny", "straight", "wide", "flared", "cargo")
LEG_SHAPE_R: Dict[str, Optional[Tuple[float, float]]] = {"skinny": None, "straight": (0.80, 0.75),
                                                          "wide": (1.0, 1.15), "flared": (0.0, 1.10),
                                                          "cargo": (0.95, 0.85)}
#: The thigh radius's ease: x (1 + TROUSER_RADIAL_EASE x fit); the cloth's gap over the skin FITTED_OFFSET_M +
#: TROUSER_FIT_M x fit (the seat and the hips too).
TROUSER_RADIAL_EASE = 0.25
TROUSER_FIT_M = 0.012
#: The widening fades in over this far under the crotch (the seat keeps the body's shape).
TROUSER_RAMP_M = 0.08
#: A widened inner leg never crosses the body's centre plane closer than this (the two legs stay apart).
TROUSER_CENTRE_GAP_M = 0.006
#: Bug round 2026-11-20 — the seat: how a trouser sits ABOVE the crotch. ``fitted`` = a second skin over the hips, the
#: seat and the crotch (leggings, skinny jeans, a stirrup: the A233 cut unchanged); ``regular`` / ``relaxed`` = woven
#: trousers — every slice from the crotch to the top edge is bridged to its convex hull (the cloth spans the seat's
#: cleft, the groin and the small of the back) and eased out by ``SEAT_EASE_M``; the skin facing up or down and the
#: legs down to ``SEAT_FADE_M`` under the crotch follow that move smoothly (``garment_template_fitted.trouser_seat``).
#: A missing seat defaults by the leg (``default_seat``): fitted for a skinny leg or a stirrup, regular otherwise.
SEATS = ("fitted", "regular", "relaxed")
SEAT_EASE_M = {"fitted": 0.0, "regular": 0.01, "relaxed": 0.025}
#: The bridge's slices (thickness) and the band each slice's hull is read over (half height).
SEAT_SLICE_M = 0.005
SEAT_HULL_M = 0.01
#: The ease grows from 0 at the waistband's lower edge to full this far under it.
SEAT_RAMP_M = 0.06
#: The seat's move fades into the leg over this far under the crotch.
SEAT_FADE_M = 0.08
#: Rounds of evening along the slices + back onto the target, and the Jacobi rounds of the fill (``trouser_seat``).
SEAT_RELAX_PASSES = 8
SEAT_FILL_PASSES = 200
#: The leggings preset of the dialog: trousers that are a second skin from the waist to the ankle.
LEGGINGS = {"kind": "trousers", "leg_shape": "skinny", "seat": "fitted", "fit": 0.0, "trouser_length": "full"}
#: The waist finish: an elastic band, a belt band (belt loops are the picture's) or none — its height (the pinned
#: band, at least MIN_PIN_BAND_M) and how much thicker it lies.
TROUSER_WAISTS = ("elastic", "belt", "none")
TROUSER_WAIST_M = {"elastic": 0.03, "belt": 0.04, "none": 0.0}
TROUSER_WAIST_EXTRA_M = {"elastic": 0.0015, "belt": 0.003, "none": 0.0}
#: The fly is painted by the picture (no geometry): the field is for the dialog and the preview, never in the key.
FLIES = ("none", "zip", "buttons")
#: The hem: plain, cuffed (a turn-up TROUSER_CUFF_M high, TROUSER_CUFF_FOLD_M thicker) or a stirrup under the arch
#: (skinny full-length only: leggings / ski pants).
TROUSER_HEMS = ("plain", "cuffed", "stirrup")
TROUSER_CUFF_M = 0.04
TROUSER_CUFF_FOLD_M = 0.004
#: A skinny leg is pinned at the hem as well, in a band this high (a stirrup: pinned whole, a second skin).
TROUSER_HEM_PIN_M = 0.015
#: The cloth frames of a trouser relax (a widened leg settles longer than a second skin).
TROUSER_FRAMES = 20
#: The fields only trousers read — out of every other piece's ``tsig`` (the existing keys stay).
TROUSER_FIELDS = ("trouser_length", "leg_shape", "seat", "trouser_waist", "fly", "hem")
#: Plan 2026-11-20-template-cut-uv-texture: where a top's texture comes from — the projection bake of the piece-only
#: views (inside the drape GLB, always made) or the "texture from cut" atlas (``garment_cut_texture``), swapped in at
#: assembly when a ready one matches the current islands and item picture (``atlas_for``).
TEXTURE_SOURCES = ("projection", "cut")
#: User test 2026-11-21: where the sleeves of a texture from cut come from — "plain" (default): a seamless patch of
#: the front panel's fabric (the model painted a chest embroidery onto one sleeve); "picture": the model's answer,
#: for an item with a print ON a sleeve. The neckband is always the fabric patch.
SLEEVE_PRINTS = ("plain", "picture")
#: The kinds cut into pattern pieces (``uv_mode`` "pattern": ``islands.json``, the texture from cut): a top, and since
#: step 3a every fitted kind; a jacket and a dress with a bodice keep the grid UV until step 3b of the pattern plan.
PATTERN_KINDS = ("top", "briefs", "bra", "gloves", "tights", "trousers")
#: The fields that change neither the drape nor the material (painted by the picture): never in ``tsig``.
TEXTURE_ONLY = ("fly", "texture", "sleeve_print")
#: Fabric presets of the cloth run (Blender cloth settings). Stiff = holds a
#: shape (denim, wool), medium = cotton, flowing = silk / chiffon / jersey.
FABRICS: Dict[str, Dict[str, float]] = {
    "stiff": {"bending": 2.0, "mass": 0.4, "quality": 6, "shrink": 0.0},
    "medium": {"bending": 0.3, "mass": 0.3, "quality": 6, "shrink": 0.0},
    "flowing": {"bending": 0.05, "mass": 0.2, "quality": 7, "shrink": 0.0},
    # A204: chiffon / voile / organza — very light and see-through. Only this preset hands the cloth run its own
    # ``cloth_mass`` / ``air_damping`` (the others keep the run's fixed 0.3 / 5.0, so their drapes stay identical):
    # a quarter of the mass and a fifth of flowing's bending stiffness let it fall into finer folds and flutter more.
    # The see-through part is the assembly's material (``material_overrides``), never the drape.
    "sheer": {"bending": 0.01, "mass": 0.08, "quality": 7, "shrink": 0.0, "cloth_mass": 0.08, "air_damping": 2.0},
    # A214: leather — Blender's shipped "Leather" cloth preset taken whole (quality 15, mass 0.4, tension /
    # compression / shear 80, bending 150, structural damping 25, air 1): heavy, barely stretching, few wide folds.
    # Both finishes drape identically (``DRAPE_FABRIC``); only the surface differs (``LEATHER_SURFACES``).
    "leather_glossy": dict(_LEATHER_CLOTH := {"bending": 150.0, "mass": 0.4, "quality": 15, "shrink": 0.0,
                                              "cloth_mass": 0.4, "air_damping": 1.0, "tension": 80.0,
                                              "compression": 80.0, "shear": 80.0, "structural_damping": 25.0}),
    "leather_rough": dict(_LEATHER_CLOTH),
}
#: A214: fabrics that share one drape — ``tsig`` keys them by the shared name, so a switch between them only
#: re-assembles (the material changes, the cloth run does not).
DRAPE_FABRIC = {"leather_glossy": "leather", "leather_rough": "leather"}
#: A214: the surface of each leather finish (``material_overrides``). Glossy = low roughness under a full clear
#: coat (KHR_materials_clearcoat); rough = matte suede / nubuck with a faint velvety sheen, no clear coat. Never metal.
LEATHER_SURFACES: Dict[str, Dict[str, Any]] = {
    "leather_glossy": {"roughness": 0.2, "clearcoat": (1.0, 0.08), "sheen": None},
    "leather_rough": {"roughness": 0.85, "clearcoat": None, "sheen": (0.25, 0.7)},
}
#: Bumped when a ``LEATHER_SURFACES`` value changes (part of ``material_key``, so the assembly is redone).
LEATHER_SURFACE_VERSION = 1
#: A204: the fabric drawn see-through. Its piece is grafted with alphaMode BLEND at ``opacity``, double-sided, and
#: hides nothing: neither the body faces under it (``body_cover``, A133) nor an inner piece's faces (A192).
SHEER = "sheer"
#: The parameters that change only the material, never the drape: left out of ``tsig`` (an opacity change
#: re-assembles on the CPU but never re-drapes).
MATERIAL_ONLY = ("opacity",)
#: ``{field: (type, choices | (min, max), default)}`` — the one parameter schema (LLM answer,
#: the dialog and ``validate_params``).
PARAM_SPEC: Dict[str, Tuple[str, Any, Any]] = {
    "kind": ("choice", KINDS, "skirt"),
    "length_m": ("number", (0.15, 1.2), 0.5),       # skirt / dress: from the waist down; top / jacket: from the shoulder line down
    "flare": ("number", (0.0, 1.0), 0.3),           # 0 pencil .. 1 near-circle hem (skirt part)
    "waist_height": ("choice", WAIST_HEIGHTS, "natural"),
    "slit": ("choice", SLIT_SIDES, "none"),
    "slit_m": ("number", (0.0, 0.6), 0.0),           # slit depth from the hem up
    "shoulders": ("choice", SHOULDERS, "strapless"),  # dress and top (A221); a jacket is always covered
    "sleeves": ("choice", SLEEVES, "none"),
    # A229 off-shoulder: the elastic band's height, how far it lies under the shoulder line, the front lacing
    "band_m": ("number", (0.01, 0.05), 0.025),
    "band_drop_m": ("number", (0.02, 0.08), 0.05),
    "lacing": ("choice", LACINGS, "none"),
    "lace_depth_m": ("number", (0.05, 0.35), 0.15),
    "sleeve_fit": ("number", (0.0, 1.0), 0.3),       # 0 tight .. 1 loose
    "fit": ("number", (0.0, 1.0), 0.3),              # bodice ease: 0 tight .. 1 loose
    "neckline": ("choice", NECKLINES, "crew"),
    "neck_depth_m": ("number", (0.0, 0.35), 0.0),    # 0 = the neckline's usual depth (NECK_DEPTH)
    "front": ("choice", FRONTS, "closed"),           # jacket: open front
    "collar": ("choice", COLLARS, "none"),           # jacket
    "fabric": ("choice", tuple(FABRICS), "medium"),
    "opacity": ("number", (0.2, 1.0), 0.4),          # A204: sheer only — how much of the cloth's colour covers
    # A223 briefs
    "rise": ("choice", RISES, "mid"),
    "leg_cut": ("number", (0.0, 1.0), 0.5),          # 0 boyshort .. 0.5 classic .. 1 high-cut (French cut)
    "back_coverage": ("number", (0.0, 1.0), 1.0),    # 0 string .. 0.3 Brazilian .. 1 full seat
    "side_width_m": ("number", (0.01, 0.10), 0.05),  # the side panel between the waistband and the leg opening
    "waistband": ("choice", WAISTBANDS, "thin"),
    # A232: 0 = a brief cut by ``leg_cut``; > 0 = short legs this far down the thigh from the crotch (trunks,
    # boxer briefs, boxer shorts with ``fit``)
    "leg_length_m": ("number", (0.0, 0.30), 0.0),
    # A235: the sides of a brief — side panels or thin hip bands (string / tanga / side-tie) of this height
    "sides": ("choice", BRIEF_SIDES, "fabric"),
    "string_width_m": ("number", (0.004, 0.02), 0.008),
    # A223 bra
    "cup_style": ("choice", CUP_STYLES, "molded"),
    "cup_coverage": ("number", (0.3, 1.0), 0.7),     # 0.3 demi .. 1 full cup
    "push_up": ("number", (0.0, 1.0), 0.0),          # 0 none .. 1 strong lift towards the centre
    "underband_m": ("number", (0.0, 0.08), 0.02),    # 0 = no band, the cup edge only (a thin back strap holds it)
    "center_gore": ("choice", CENTER_GORES, "narrow"),
    "closure": ("choice", CLOSURES, "back_hook"),
    "straps": ("choice", STRAPS, "thin"),
    # A223 gloves
    "fingers": ("choice", FINGERS, "full"),
    "length": ("choice", GLOVE_LENGTHS, "wrist"),
    "cuff": ("choice", CUFFS, "none"),
    "tights_style": ("choice", TIGHTS_STYLES, "tights"),
    "feet": ("choice", TIGHTS_FEET, "closed"),
    "garters": ("choice", GARTERS, "none"),
    # A233 trousers (with ``rise``, ``fit`` and ``fabric``)
    "trouser_length": ("choice", TROUSER_LENGTHS, "full"),
    "leg_shape": ("choice", LEG_SHAPES, "straight"),
    "seat": ("choice", SEATS, "regular"),
    "trouser_waist": ("choice", TROUSER_WAISTS, "belt"),
    "fly": ("choice", FLIES, "zip"),
    "hem": ("choice", TROUSER_HEMS, "plain"),
    # the texture source (``TEXTURE_SOURCES``): a CPU re-assemble, never a re-drape (``TEXTURE_ONLY``)
    "texture": ("choice", TEXTURE_SOURCES, "projection"),
    # the sleeves of the texture from cut (``SLEEVE_PRINTS``): a CPU re-compose of the atlas, never a re-drape
    "sleeve_print": ("choice", SLEEVE_PRINTS, "plain"),
}
#: The fields that mean something per kind (the dialog shows these; ``validate_params`` resets the others to their
#: defaults so a stale field never changes the drape key).
KIND_FIELDS: Dict[str, Tuple[str, ...]] = {
    "skirt": ("kind", "fabric", "opacity", "length_m", "flare", "waist_height", "slit", "slit_m"),
    "trousers": ("kind", "fabric", "opacity", "rise", "trouser_length", "leg_shape", "seat", "fit", "trouser_waist",
                 "fly", "hem"),
    "dress": ("kind", "fabric", "opacity", "length_m", "flare", "waist_height", "slit", "slit_m", "shoulders", "sleeves",
              "sleeve_fit", "fit", "neckline", "neck_depth_m", *OFF_SHOULDER_FIELDS),
    "top": ("kind", "fabric", "opacity", "length_m", "shoulders", "fit", "sleeves", "sleeve_fit", "neckline", "neck_depth_m",
            *OFF_SHOULDER_FIELDS, "texture", "sleeve_print"),
    "jacket": ("kind", "fabric", "opacity", "length_m", "fit", "sleeves", "sleeve_fit", "neckline", "neck_depth_m", "front",
               "collar"),
    "briefs": ("kind", "fabric", "opacity", "rise", "leg_cut", "back_coverage", "side_width_m", "waistband",
               "leg_length_m", "fit", "sides", "string_width_m"),
    "bra": ("kind", "fabric", "opacity", "cup_style", "cup_coverage", "push_up", "underband_m", "center_gore", "closure",
            "straps"),
    "gloves": ("kind", "fabric", "opacity", "fingers", "length", "cuff", "fit"),
    "tights": ("kind", "fabric", "opacity", "tights_style", "feet", "waistband", "garters"),
}

#: Spec section 8 pass marks (hand-derived in ``scripts/smoke_garment_template_spike.py``).
THRESHOLDS = {
    "drape_cpu_s": 60.0,          # spike: CPU seconds of the cloth run (all threads summed)
    "poke_share": 0.005,          # body vertices poking through, per pose
    "pin_drift_mm": 5.0,          # largest displacement of a pinned vertex
    "stretch_max": 1.3,           # longest edge / its pre-drape length, after the drape
    "bake_coverage": 0.85,        # template texels that received a view colour
    "bake_iou": 0.5,              # bug round 2026-11-20: the registered silhouette IoU of the views (the poorer one)
}
#: Bug round 2026-11-20: a baked texture this poor is WARNED about in the Figure row (``texture_warning``; never a
#: refusal): under 60 % of the texels got a picture colour (the rest is push-pull fill from the colours round it), or
#: the views' outline matches the template's by under half (the picture shows another cut: straps, chains, a pose).
#: Glut's bra baked 0.43 coverage with the box fit (0.68 registered, IoU 0.20 on the back view), Kira's tights 0.49.
TEXTURE_WARN = {"coverage": 0.6, "iou": 0.5}
#: The wall-time budget of one drape (Ruling A138: a Build is waited for in wall seconds; the spike's CPU sum
#: counts every Blender thread). Same 60 s, hand-derived in ``scripts/smoke_garment_template.py``. Since 2026-11-18
#: (owner) it is a REPORTED row, never a gate: a drape that passes every quality row is accepted however long it
#: took ("slow" in the Figure tab), and the time counted is the work alone — the wait for a free Blender slot is
#: taken out (``work_wall_s``). It still bounds the stretch retry (``run_drape``: only when the first run left room).
BUILD_WALL_S = 60.0
#: A204: the wall budget's factor per fabric (a fabric not named keeps 1.0, so its rows stay as before). The sheer
#: cloth runs a softer, lighter solve: measured on Gelina's skirt 59.3 / 64.5 s against flowing's 57.8 s.
#: A214: leather solves at quality 15 with stiff springs: Gelina's 76 cm skirt took 64.8 s work wall against medium's
#: 46.3 s on the same host (x1.40); 1.5 leaves the same headroom the other fabrics have.
LEATHER_WALL = 1.5
WALL_FACTOR = {"sheer": 2.0, "leather_glossy": LEATHER_WALL, "leather_rough": LEATHER_WALL}


def wall_limit(params: Optional[Dict[str, Any]]) -> float:
    """The wall gate of a drape of ``params`` (``BUILD_WALL_S`` x ``WALL_FACTOR``)."""
    return BUILD_WALL_S * WALL_FACTOR.get(str((params or {}).get("fabric") or ""), 1.0)
#: The wall seconds a drape takes, for the cost line (measured A141 on Kira with the two pose shapes:
#: 28–47 s per piece; A138 without them 13.4–17.8 s; A142 tops with four shapes 40–50 s; A144 tops / jackets 40–50 s).
CPU_ESTIMATE_S = 45
#: Ruling A141: the poses that get a corrective shape (a drape of their own, a morph target blended by
#: the leg directions at runtime) and the poses every Build measures.
SHAPE_POSES = ("sit", "kneel")
MEASURED_POSES = ("rest", "walk", "sit", "kneel")
#: Ruling A142 — the arm poses of a piece with a bodice. The bind pose is the T-pose (arms out), so the skinned
#: drape is right only with the arms out: "arms_down" (the idle / walk arms, the most frequent runtime pose),
#: "arms_forward" (reaching, holding) and "arms_up" (raised) each get a corrective drape. The shape is split per
#: side (``_l`` / ``_r`` targets, blended by that side's arm alone), so one arm up and one down mixes correctly.
ARM_SHAPE_POSES = ("arms_down", "arms_forward", "arms_up")
#: A dress with sleeves carries the leg shapes AND arm shapes; to stay in the wall budget only the most frequent
#: arm pose is draped for it (measured A142: every extra pose drape costs 6–10 s wall).
DRESS_ARM_SHAPE_POSES = ("arms_down",)
UPPER_LEG_POSES = ("sit",)
#: Ruling A142 wall budget (60 s per piece, reported since 2026-11-18, no longer a gate): a bodice drapes BODICE_FRAMES frames, an arm shape ARM_SHAPE_FRAMES (the
#: arm shapes settle from the skinned pose and move 14–29 mm at p90; measured A142 with 40 frames: 12–15 s wall each,
#: a long-sleeved jacket was 66 s with 25 frames). Ruling A144: 30 / 12 / 16 frames and the arm poses collide with a
#: skinned rest collider (no remesh per pose): the blazer 70.7 -> 44.6 s, its pose numbers unchanged (stretch p99
#: arms_down 1.25, arms_up 1.40; sit poke 0).
BODICE_FRAMES = 30
#: A179: the main drape of a bodice runs at this multiple of the fabric's cloth quality (the pose shapes keep the
#: fabric's own). Measured on two copies: at quality 6-7 the largest stretch sat on single edges beside the armholes
#: and moved between 1.17 and 1.40 with every small change of the built mesh (under-resolved: the solver, not the
#: load); at x1.5 it is 1.16 / 1.23, at x2 1.12 / 1.20. x1.5 costs ~4.5 s wall.
BODICE_DRAPE_QUALITY = 1.5
ARM_SHAPE_FRAMES = 12
UPPER_SIT_FRAMES = 16
#: Ruling A144: a dress with a bodice drapes its sit / kneel shapes with this many frames (40 put a sleeved dress at
#: 63 s wall, 28 still 62 s; a skirt keeps the default SHAPE_FRAMES of the builder).
DRESS_LEG_FRAMES = 20
MEASURED_UPPER_POSES = ("rest", "walk", "arms_down", "arms_forward", "arms_up", "sit")
#: The pose-shape groups (driver segments are joint pairs; ``frame`` = the joint whose rotation since the bind pose
#: is taken out of the directions; ``sigma`` = Gaussian width in radians of summed segment angle). The arm samples lie
#: ~70–130 degrees apart, the leg samples closer. Arm sigma 0.55 (two segments): the rest pose takes 2.7 % of the
#: arms-up shape (d^2 = 2 x 1.047^2 -> exp(-2.19 / 0.605)), the walk arms (30 degrees down) ~29 % of arms-down.
LEG_GROUP = {"name": "legs", "frame": "Hips", "sigma": 0.5, "anchors": ["rest", "walk"], "mirror": True,
             "segments": [["LeftUpLeg", "LeftLeg"], ["RightUpLeg", "RightLeg"], ["LeftLeg", "LeftFoot"],
                          ["RightLeg", "RightFoot"]]}
ARM_GROUPS = [{"name": "arm_" + side[0].lower(), "side": side[0].lower(), "frame": "Spine2", "sigma": 0.55,
               "frames": ARM_SHAPE_FRAMES,
               "anchors": ["rest"], "mirror": False,
               "segments": [[side + "Arm", side + "ForeArm"], [side + "ForeArm", side + "Hand"]]}
              for side in ("Left", "Right")]


def has_bodice(params: Dict[str, Any]) -> bool:
    """A jacket, a top that is not strapless (A221), or a dress with straps or a covered bodice (Ruling A142)."""
    return params["kind"] in ("top", "jacket", "dress") and (params["kind"] == "jacket"
                                                             or params["shoulders"] != "strapless")


def strapless_top(params: Dict[str, Any]) -> bool:
    """A221: a top with nothing over the shoulders (bodice, bustier, corset)."""
    return params["kind"] == "top" and params["shoulders"] == "strapless"


def corset_top(params: Dict[str, Any]) -> bool:
    """A221: a top cut as a corset bodice — strapless or with straps; its top edge is the chest band (straight or
    sweetheart), the straps (if any) run from it over the shoulders."""
    return params["kind"] == "top" and params["shoulders"] in ("strapless", "straps")


def has_sleeves(params: Dict[str, Any]) -> bool:
    return has_bodice(params) and params["shoulders"] in ("covered", "off_shoulder") and params["sleeves"] != "none"


def layer_ease(params: Dict[str, Any], over_sleeves: bool) -> float:
    """Bug round 2026-11-20: the extra sleeve / armhole ease of a jacket with sleeves draped over a lower layer with
    sleeves (``JACKET_SLEEVE_EASE``), else 0."""
    return JACKET_SLEEVE_EASE if over_sleeves and params["kind"] == "jacket" and has_sleeves(params) else 0.0


def over_sleeved_layer(kind: str, colliders: List[Dict[str, Any]]) -> bool:
    """Bug round 2026-11-20: whether a jacket drapes over a TEMPLATE layer with sleeves (``has_sleeves``) among
    ``colliders`` — the items of the lower template layers whose drape is READY, i.e. the colliders really handed to
    the drape (``_build_drape``: a lower layer not draped is no collider, so it widens nothing; ``collider_states``
    for the key and the preview). Own-mesh pieces under it say nothing about their sleeves; they keep the A200
    shrink / drop fallback (``drape_with_fallback``)."""
    if kind != "jacket":
        return False
    for it in colliders:
        p = params_of(it)
        if p is not None and has_sleeves(p):
            return True
    return False


def off_shoulder(params: Dict[str, Any]) -> bool:
    """A229: a top or dress cut off the shoulders (Carmen / Bardot)."""
    return params["kind"] in ("top", "dress") and params.get("shoulders") == "off_shoulder"


def _validate_off_shoulder(params: Dict[str, Any]) -> None:
    """A229: an off-shoulder piece always has sleeves of at least ``short`` (``OFF_SHOULDER_SLEEVES``; none / cap
    -> short), its neckline is the band (crew, depth 0 — the yoke is cut away whole); every other piece keeps the
    off-shoulder fields at their defaults, and without lacing the lacing depth is the default too."""
    if not off_shoulder(params):
        for key in OFF_SHOULDER_FIELDS:
            params[key] = PARAM_SPEC[key][2]
        return
    if params["sleeves"] not in OFF_SHOULDER_SLEEVES:
        params["sleeves"] = "short"
    params["neckline"] = "crew"
    params["neck_depth_m"] = 0.0
    if params["lacing"] == "none":
        params["lace_depth_m"] = PARAM_SPEC["lace_depth_m"][2]


def shape_groups(params: Dict[str, Any], long_top: bool = False) -> List[Dict[str, Any]]:
    """The pose-shape groups of a piece (Rulings A141 / A142): skirts and dresses get the leg group (sit, kneel); a
    piece with a bodice gets the two arm groups (``ARM_SHAPE_POSES``; a dress only ``DRESS_ARM_SHAPE_POSES``); a top
    or jacket whose hem reaches below the hip joints (``long_top``) also the sit shape (its hem lies on the lap)."""
    groups: List[Dict[str, Any]] = []
    if params["kind"] in FITTED_KINDS:
        # A223: a fitted piece follows the skin by its weights alone (a sit shape drape of briefs was tried on Glut's
        # body: the pinned cloth folded through the chest, stretch 648 — left out)
        return []
    if params["kind"] in ("skirt", "dress"):
        leg = {**LEG_GROUP, "poses": list(SHAPE_POSES)}
        if has_bodice(params):
            leg["frames"] = DRESS_LEG_FRAMES
        groups.append(leg)
    elif params["kind"] in UPPER_KINDS and long_top:
        groups.append({**LEG_GROUP, "poses": list(UPPER_LEG_POSES), "frames": UPPER_SIT_FRAMES})
    if has_bodice(params):
        poses = list(DRESS_ARM_SHAPE_POSES if params["kind"] == "dress" else ARM_SHAPE_POSES)
        groups.extend({**g, "poses": poses} for g in ARM_GROUPS)
    return groups


#: A223: the poses a fitted piece is measured in (briefs: the leg poses; a bra: the arm poses that pull the chest;
#: gloves: the arm poses).
FITTED_POSES = {"briefs": MEASURED_POSES, "bra": ("rest", "walk", "arms_down", "arms_up"),
                "gloves": ("rest", "arms_down", "arms_forward", "arms_up"), "tights": MEASURED_POSES,
                "trousers": MEASURED_POSES}


def measured_poses(params: Dict[str, Any]) -> Tuple[str, ...]:
    if params["kind"] in FITTED_POSES:
        return FITTED_POSES[params["kind"]]
    if has_bodice(params):
        return MEASURED_UPPER_POSES if params["kind"] != "dress" else (*MEASURED_POSES, "arms_down", "arms_up")
    return MEASURED_POSES


def shape_targets(payload: Optional[Dict[str, Any]]) -> List[str]:
    """The pose names a drape carries a shape for, side suffixes folded ("arms_down_l" + "_r" -> "arms_down")."""
    out: List[str] = []
    for name in (payload or {}).get("targets") or []:
        base = re.sub(r"_[lr]$", "", str(name))
        if base not in out:
            out.append(base)
    return out
#: Stretch above which the drape is re-run once with doubled quality (spec section 6), then refused.
RETRY_STRETCH = 1.5
#: Bug round 2026-11-20: a NARROW miss — the gated stretch at or over its limit but no higher than RETRY_STRETCH, on
#: at most this many edges over 1.3 (``stretch_at.over_1_3``) — is re-run once with doubled quality too. Many edges
#: over the limit are a real fault of the fit that more quality does not mend; they are refused at once as before.
#: Like every retry it only runs when the first run left half the wall budget (Ruling A142): Lirien's top at 0.24
#: (first run 1.307) is mended by it (1.221); Kai's leather jacket copy (one edge at 1.329, p99 1.03) is NOT — its
#: first run worked 122 s, over the 45 s half of its leather wall limit, so it stays refused (a forced retry passes
#: at 1.182 in 232 s). Its stretch sits under the upper sleeves, over the lower layer's sleeve: a matter of the
#: sleeve's layer ease, not of this retry.
NARROW_MISS_EDGES = 4


def retry_due(drape: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why a first drape run (``data.drape`` of ``garment_template_build``) is re-run with doubled quality: "stretch"
    above ``RETRY_STRETCH``, "narrow" for a narrow miss (``NARROW_MISS_EDGES``), None when it is not."""
    drape = drape or {}
    value = _number(drape.get("stretch_max"))
    if value is None or value < THRESHOLDS["stretch_max"]:
        return None
    if value > RETRY_STRETCH:
        return "stretch"
    over = _number((drape.get("stretch_at") or {}).get("over_1_3"))
    return "narrow" if over is not None and over <= NARROW_MISS_EDGES else None

# Pin rings by piece kind (where the cloth hangs from).
PIN_BY_KIND = {"skirt": "waist", "trousers": "waist", "top": "shoulders", "jacket": "shoulders",
               "dress": "shoulders"}

# --- reasons (Ruling A119: a piece not ready is left off, with its reason) -----------------------
NEEDS_PARAMS = "Needs its template parameters — open Edit parameters (1 LLM call to suggest them)"
NOT_DRAPED = "Not draped yet — Build drapes it (CPU, 0 hub jobs)"
KIND_NOT_BUILT = "Template kind '{kind}' is not built yet (every kind in the dialog is) — choose another mode"
DRAPE_FAILED = "Drape failed: {error} — Retry in the Figure tab"
NO_BASE = "No plain body model yet — build the plain body first"
#: The reason of a drape whose Blender run ended retryable (``app.blender.outcome``): nothing judged the drape, so
#: no failure is recorded. The Figure tab shows it as a note through ``t()`` (``failure_info``'s line).
LEFT_DUE = {
    "timeout": "The drape ran out of time (the machine was busy). Nothing was recorded as failed — Build again.",
    "interrupted": "The drape was stopped before it finished (the server stopped or Blender was ended). Nothing "
                   "was recorded as failed — Build again.",
    "unavailable": "Blender is not available right now, so the piece was not draped. Nothing was recorded as "
                   "failed — Build again once Blender is back.",
}


# --- a failed drape in plain words (owner 2026-11-18) ------------------------------------------------------------
#: One sentence per GATED drape check (``judge_build``): what is wrong in the user's terms and what to do next.
#: English with ``{value}`` / ``{limit}`` placeholders — the Figure tab puts the text through ``t()`` and fills them
#: (``failure_info`` formats the numbers). What each check measures (``garment_template_build.py``):
#:
#: * ``stretch_max`` — after the main drape (rest pose), the longest edge of the cloth over its length in the cut
#:   pattern. The pattern is cut no narrower than the body plus ease (``_skirt_knots`` / the bodice ease), so a cloth
#:   stretched far beyond its cut has caught on something: on the body model (e08e95fdb — a hollow collider held a
#:   vertex inside the hips, stretch 4.77) or on a piece under it — not a pattern too tight for the body.
#: * ``poke_share[rest]`` — the share of the body's skin in the piece's region where the piece lies UNDER the skin
#:   (a ray from the bone meets the cloth before the skin), in the rest pose: the body shows through.
#: * ``pin_drift_mm`` — how far the fastened top rows (waistband or shoulder line) moved during the cloth run.
FAILURE_SENTENCES = {
    "stretch_max": ("The fabric is stretched to {value}× its cut length in one place (the limit is {limit}×). The "
                    "pattern is cut wider than the body, so the cloth has most likely caught on the body model or on "
                    "a piece under it rather than being too tight. Change the length, fit or waistband so it hangs "
                    "differently, then Build again."),
    # A236: the stretch sits at the neck or on the shoulders of a top / jacket / dress — length, fit and waistband
    # change nothing there (``stretch_line``)
    "stretch_max_neck": ("The fabric is stretched to {value}× its cut length at the neck or on the shoulders (the "
                         "limit is {limit}×). Length, fit and waistband do not change that part: try another "
                         "neckline, shoulders or sleeves, then Build again. Hair or a beard lying on the shoulders is "
                         "no longer in the way; if it stays, the body model itself has a ridge there."),
    # bug round 2026-11-20: the stretch sits under the chest of a top / jacket whose hem ends between the underbust
    # fold and the bust line (``stretch_line``) — only a LONGER piece helps there, never a shorter one
    "stretch_max_underbust": ("The fabric is stretched to {value}× its cut length under the chest (the limit is "
                              "{limit}×): the hem ends between the bust and the underbust fold, where the cloth "
                              "spans the step down to the ribs. Make the piece longer — a length of at least "
                              "{length} m puts the hem below the fold — then Build again."),
    "poke_share": ("The body shows through the fabric on {value} % of the skin it covers in the rest pose (the limit "
                   "is {limit} %): the cloth slipped under the body's surface there. Change the length, fit or "
                   "waistband so it hangs differently, then Build again."),
    "pin_drift_mm": ("The fastened top edge of the piece (waistband or shoulder line) moved {value} mm during the "
                     "drape (the limit is {limit} mm). Change the fit or the waistband, then Build again."),
}
#: The checks passed but no 3D model came back (``run_drape``: "no GLB written", outcome ``crashed``).
NO_GLB_SENTENCE = ("The drape passed its checks but wrote no 3D model — a defect on our side, not a problem of the "
                   "piece. The Blender output shows what happened; Build again to retry.")
#: Blender itself failed (outcome ``crashed``).
CRASHED_SENTENCE = ("The drape stopped with an error on our side — a defect, not a problem of the piece. The Blender "
                    "output shows what went wrong; Build again to retry.")
#: The Blender script refused the piece itself (outcome ``rejected`` without a failed check row).
REJECTED_SENTENCE = ("Blender could not drape this piece — its reason is under Details. Change the parameters, then "
                     "Build again.")


def _num(value: Any, scale: float = 1.0) -> str:
    """A check value for a sentence: at most two decimals, no trailing zeros ("4.77", "1.3", "0.5")."""
    try:
        return f"{float(value) * scale:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"


#: A236: a stretch this close below the shoulder line (metres) or higher counts as "at the neck or on the shoulders".
NECK_STRETCH_BELOW_M = 0.05


def stretch_line(failed: Dict[str, Any]) -> str:
    """A236 — which stretch sentence fits a failure record: ``stretch_max_neck`` when the worst edge
    (``metrics.drape.stretch_at.z``, Blender Z = height) lies no lower than NECK_STRETCH_BELOW_M under the body's
    shoulder line (``metrics.measure.shoulder_y``) on a piece with a bodice; ``stretch_max_underbust`` when a top's /
    jacket's hem ends between the underbust fold and the bust line and the worst edge is no higher than
    ``UNDERBUST_HEM_M`` over the bust line (``underbust_length``); else ``stretch_max``."""
    metrics = failed.get("metrics") or failed.get("data") or {}
    z = _number(((metrics.get("drape") or {}).get("stretch_at") or {}).get("z"))
    sy = _number((metrics.get("measure") or {}).get("shoulder_y"))
    params = failed.get("params") or {}
    if z is None or sy is None or not isinstance(params, dict) or not params.get("kind"):
        return "stretch_max"
    try:
        bodice = has_bodice(params)
    except Exception:
        bodice = False
    if bodice and z >= sy - NECK_STRETCH_BELOW_M:
        return "stretch_max_neck"
    return "stretch_max_underbust" if underbust_length(failed) is not None else "stretch_max"


def underbust_length(failed: Dict[str, Any]) -> Optional[float]:
    """Bug round 2026-11-20 — the length (metres, rounded up to the cm) that puts a failed top's / jacket's hem
    ``UNDERBUST_HEM_M`` under the underbust fold, when its hem (``metrics.outline``: ``top_y`` - ``length``) ends
    between the fold and the bust line (``_bust_lines`` of ``metrics.measure``) and the worst edge
    (``stretch_at.z``) lies no higher than ``UNDERBUST_HEM_M`` over the bust line; else None (also on a body without
    a fold, ``_underbust_fold``). The length is counted from the line ``length_m`` counts from (``_length_origin``),
    not from the length asked: a strapless top's hem is held ``STRAPLESS_MIN_M`` under its top edge, so a short asked
    length does not say where the hem is (review of the bug round: asked 0.15 read hem 1.20 and advised 0.22, which
    changed nothing). Never shorter than the length asked."""
    metrics = failed.get("metrics") or failed.get("data") or {}
    params = failed.get("params") or {}
    outline_ = metrics.get("outline") or {}
    meas = metrics.get("measure") or {}
    z = _number(((metrics.get("drape") or {}).get("stretch_at") or {}).get("z"))
    top_y, length, asked = (_number(outline_.get("top_y")), _number(outline_.get("length")),
                            _number(params.get("length_m") if isinstance(params, dict) else None))
    if (not isinstance(params, dict) or params.get("kind") not in ("top", "jacket") or None in (z, top_y, length, asked)
            or "band_y" not in meas or "waist_y" not in meas):
        return None
    try:
        fold = _underbust_fold(meas)
        origin = _length_origin(meas, top_y if strapless_top(params) else None)
    except (KeyError, TypeError, ValueError):
        return None
    if fold is None:
        return None
    under_y, bust_y = fold
    hem_y = top_y - length
    if not (under_y <= hem_y <= bust_y) or z > bust_y + UNDERBUST_HEM_M:
        return None
    need = math.ceil((origin - (under_y - UNDERBUST_HEM_M)) * 100.0 - 1e-6) / 100.0
    return max(need, math.ceil(asked * 100.0 - 1e-6) / 100.0)


def failure_info(failed: Dict[str, Any]) -> Dict[str, Any]:
    """A failed or left-due drape as data for the UI — ``{outcome, lines, rows, log_tail, error}``: ``lines`` the
    plain sentences ``[{text, values}]`` (``FAILURE_SENTENCES`` per failed gate row; else ``LEFT_DUE`` for a run
    left due, ``NO_GLB_SENTENCE`` / ``CRASHED_SENTENCE`` / ``REJECTED_SENTENCE``), ``rows`` every check of the run
    (``judge_build``), ``log_tail`` the end of Blender's output, ``error`` the raw message. ``failed`` = a failure
    record (``_build_drape``) or the same keys of a run's result. Never raises."""
    from app.blender import outcome as oc
    rows = [r for r in failed.get("rows") or [] if isinstance(r, dict)]
    bad = [r for r in rows if r.get("gate") and not r.get("ok")]
    error = str(failed.get("error") or "")
    outcome = str(failed.get("outcome") or (oc.REJECTED if bad else oc.CRASHED))
    lines: List[Dict[str, Any]] = []
    for r in bad:
        base = str(r.get("check") or "").split("[")[0]
        if base in FAILURE_SENTENCES:
            scale = 100.0 if base == "poke_share" else 1.0
            key = stretch_line(failed) if base == "stretch_max" else base
            values = {"value": _num(r.get("value"), scale), "limit": _num(r.get("limit"), scale)}
            if key == "stretch_max_underbust":
                values["length"] = _num(underbust_length(failed))
            lines.append({"text": FAILURE_SENTENCES[key], "values": values})
    if not lines:
        text = (LEFT_DUE.get(outcome) if oc.is_retryable(outcome)
                else NO_GLB_SENTENCE if rows and not bad
                else REJECTED_SENTENCE if outcome == oc.REJECTED else CRASHED_SENTENCE)
        lines.append({"text": text or LEFT_DUE[oc.INTERRUPTED], "values": {}})
    return {"outcome": outcome, "lines": lines, "rows": rows, "log_tail": str(failed.get("log_tail") or ""),
            "error": error}


# --- parameters ---------------------------------------------------------------

def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_params(raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    """``(params, errors)`` of a parameter dict against ``PARAM_SPEC``: every field present
    (a missing one takes its default and is NOT an error), choices lower-cased, numbers
    clamped into their range (a clamp is reported). Unknown keys are dropped. ``errors``
    lists what was wrong; a non-dict is one error and all defaults."""
    params: Dict[str, Any] = {}
    errors: List[str] = []
    if not isinstance(raw, dict):
        return {k: spec[2] for k, spec in PARAM_SPEC.items()}, ["parameters must be a JSON object"]
    for key, (kind, rule, default) in PARAM_SPEC.items():
        value = raw.get(key)
        if value is None or value == "":
            params[key] = default
            continue
        if kind == "choice":
            text = str(value).strip().lower()
            if text not in rule:
                errors.append(f"{key}: {value!r} is not one of {', '.join(rule)}")
                text = default
            params[key] = text
        else:
            number = _number(value)
            if number is None:
                errors.append(f"{key}: {value!r} is not a number")
                number = default
            lo, hi = rule
            if not lo <= number <= hi:
                errors.append(f"{key}: {number} is outside {lo}..{hi}")
                number = min(hi, max(lo, number))
            params[key] = round(number, 3)
    kind = params["kind"]
    # A221: a top's shoulders default to covered (the schema default, strapless, is a dress's), so an answer or a
    # stored top without the field keeps its bodice
    if kind == "top" and raw.get("shoulders") in (None, ""):
        params["shoulders"] = "covered"
    for key in PARAM_SPEC:
        if key not in KIND_FIELDS.get(kind, tuple(PARAM_SPEC)):
            params[key] = PARAM_SPEC[key][2]
    if kind == "jacket":
        params["shoulders"] = "covered"
    if corset_top(params):
        params["sleeves"] = "none"
        if params["neckline"] not in STRAPLESS_NECKLINES:
            params["neckline"] = "straight"
        if params["neckline"] == "straight":
            params["neck_depth_m"] = 0.0
        else:
            params["neck_depth_m"] = round(min(params["neck_depth_m"], SWEETHEART_MAX_M), 3)
    elif params["neckline"] in STRAPLESS_NECKLINES:
        params["neckline"] = "crew"
    if kind == "dress" and params["shoulders"] not in ("covered", "off_shoulder"):
        params["sleeves"] = "none"
    _validate_off_shoulder(params)
    if params["sleeves"] == "none":
        params["sleeve_fit"] = PARAM_SPEC["sleeve_fit"][2]
    if params["fabric"] != SHEER:
        params["opacity"] = PARAM_SPEC["opacity"][2]
    if kind == "briefs":
        # A232: a brief's leg opening is ``leg_cut``, a boxer's the straight hem ``leg_length_m`` down the thigh (with
        # the ease ``fit``) — the field the cut does not read keeps its default, so it never changes the drape key
        # A235: a string brief has no legs and no side panel; a fabric one no string width
        if params["sides"] == "string":
            params["leg_length_m"] = 0.0
            params["side_width_m"] = PARAM_SPEC["side_width_m"][2]
        else:
            params["string_width_m"] = PARAM_SPEC["string_width_m"][2]
        if params["leg_length_m"] > 0:
            params["leg_cut"] = PARAM_SPEC["leg_cut"][2]
        else:
            params["fit"] = PARAM_SPEC["fit"][2]
    if kind == "trousers":
        _validate_trousers(params, seat_given=raw.get("seat") not in (None, ""))
    if params["slit"] == "none":
        params["slit_m"] = 0.0
    elif params["slit_m"] <= 0.0:
        params["slit_m"] = round(min(0.25, params["length_m"] * 0.4), 3)
    params["slit_m"] = round(min(params["slit_m"], params["length_m"] * 0.8), 3)
    return params, errors


def _validate_trousers(params: Dict[str, Any], seat_given: bool = True) -> None:
    """A233: a stirrup only under a skinny full-length leg (else the hem is plain). Bug round 2026-11-20: a seat not
    given takes ``default_seat``; a stirrup is pinned whole as a second skin, so its seat is always fitted."""
    if params["hem"] == "stirrup" and not (params["leg_shape"] == "skinny" and params["trouser_length"] == "full"):
        params["hem"] = "plain"
    if not seat_given:
        params["seat"] = default_seat(params)
    if params["hem"] == "stirrup":
        params["seat"] = "fitted"


def default_seat(params: Dict[str, Any]) -> str:
    """Bug round 2026-11-20: the seat of trousers whose seat is not given (an answer without it, a piece stored before
    the field) — fitted for a skinny leg (leggings, skinny jeans: a second skin, as they were cut before the seat
    existed), regular for every other leg shape."""
    return "fitted" if params.get("leg_shape") == "skinny" else "regular"


def tucked_into_shoes(params: Optional[Dict[str, Any]]) -> bool:
    """A233: trousers whose leg goes into the shoe (``garment_set.under_footwear``: the shoe's body cut takes it in,
    as hosiery) — a skinny full-length leg (leggings, skinny jeans, a stirrup). Every other leg hangs over the shoe."""
    return bool(params) and params.get("kind") == "trousers" and params.get("leg_shape") == "skinny" \
        and params.get("trouser_length") == "full"


#: A172: the starting values of a kind that differ from ``PARAM_SPEC``'s (those are a skirt's) — what the dialog
#: shows for a piece with no stored parameters and what a kind change resets to. Lengths are measured as in
#: ``PARAM_SPEC`` (top / jacket from the shoulder line down: 0.6 m ends at the hip on the 1.70 m reference body).
KIND_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "skirt": {},
    "trousers": {"fabric": "stiff"},
    "dress": {"length_m": 0.6, "shoulders": "straps"},
    "top": {"length_m": 0.6, "sleeves": "short", "fit": 0.4, "shoulders": "covered"},
    "jacket": {"length_m": 0.7, "sleeves": "long", "fit": 0.5, "collar": "lapel", "front": "open"},
    "briefs": {},
    "bra": {},
    "gloves": {"fit": 0.1},
    "tights": {"fabric": "sheer", "opacity": 0.5},
}
_TROUSER_WORDS = re.compile(r"\b(trousers?|pants|jeans|shorts|leggings|slacks|chinos)\b", re.IGNORECASE)
_DRESS_WORDS = re.compile(r"\b(dress|gown|sundress|frock)\b", re.IGNORECASE)
_JACKET_WORDS = re.compile(r"\b(jacket|blazer|coat|cardigan|hoodie|parka)\b", re.IGNORECASE)
#: A223: the words of the fitted kinds (English and German; a compound counts at its end: "Schuppen-BH", "Schuppenslip").
_BRA_WORDS = re.compile(r"(\bbra\b|bralette|bikini[ -]?top|\bbh\b|büstenhalter)", re.IGNORECASE)
_BRIEFS_WORDS = re.compile(r"(briefs?\b|panties|knickers|thong|g-string|\bstring\b|slip\b|unterhose|höschen|"
                           r"bikini[ -]?(bottom|hose)|tanga)", re.IGNORECASE)
_GLOVE_WORDS = re.compile(r"(gloves?\b|gauntlets?\b|mittens?\b|arm ?warmers?\b|handschuhe?\b|stulpen\b|"
                          r"armstulpen)", re.IGNORECASE)


_TIGHTS_WORDS = re.compile(r"(tights|pantyhose|stocking|hold-?ups?\b|\bsocks?\b|strumpf|strümpfe|struempfe|"
                           r"strumpfhose|kniestr)", re.IGNORECASE)


def default_kind(item: Optional[Dict[str, Any]]) -> str:
    """A172: the template kind an outfit piece most likely is, from its slots, then its name and prompt text — the
    starting kind of the parameter dialog when nothing is stored (Suggest and Save still decide). ``outer`` →
    jacket; ``top`` with ``bottom`` → dress; ``top`` → top (a dress / jacket word wins); ``bottom`` → trousers for a
    trouser word, else skirt (a dress word → dress); nothing that fits → skirt (``PARAM_SPEC``'s default).
    A223 first: ``hands`` or a glove word → gloves; ``underwear_top`` or a bra word (no dress word) → bra;
    ``underwear_bottom`` or a briefs word (no trouser / dress word) → briefs."""
    item = item if isinstance(item, dict) else {}
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    slots = {str(x) for x in piece.get("slots") or []}
    text = f"{item.get('name') or ''} {item.get('prompt_fragment') or ''}"
    name = str(item.get("name") or "")
    if "hands" in slots or _GLOVE_WORDS.search(name):
        return "gloves"
    if _TIGHTS_WORDS.search(name) or (slots and slots <= {"legs", "feet"} and "legs" in slots):
        return "tights"
    if not _DRESS_WORDS.search(text):
        if "underwear_top" in slots or _BRA_WORDS.search(name):
            return "bra"
        if "underwear_bottom" in slots or (_BRIEFS_WORDS.search(name) and not _TROUSER_WORDS.search(name)):
            return "briefs"
    if _DRESS_WORDS.search(text) or {"top", "bottom"} <= slots:
        return "dress"
    if "outer" in slots or ("top" in slots and _JACKET_WORDS.search(text)):
        return "jacket"
    if "top" in slots:
        return "top"
    if "bottom" in slots and _TROUSER_WORDS.search(text):
        return "trousers"
    return "skirt"


def kind_defaults(kind: str) -> Dict[str, Any]:
    """The validated starting parameters of ``kind`` (``PARAM_SPEC`` defaults + ``KIND_DEFAULTS``)."""
    return validate_params({k: v[2] for k, v in PARAM_SPEC.items()} | {"kind": kind} | KIND_DEFAULTS.get(kind, {}))[0]


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def parse_answer(text: Any) -> Dict[str, Any]:
    """The JSON object of an LLM answer (a fenced block, else the outermost ``{...}``).
    ValueError when there is none."""
    body = _THINK.sub("", str(text or ""))
    match = _FENCE.search(body)
    candidate = match.group(1) if match else body[body.find("{"): body.rfind("}") + 1]
    if not candidate:
        raise ValueError("the answer holds no JSON object")
    try:
        data = json.loads(candidate)
    except ValueError as e:
        raise ValueError(f"the answer's JSON is unreadable: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("the answer's JSON is no object")
    return data


def template_of(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The stored ``outfit_piece.template`` record of an item, {} when none."""
    piece = (item or {}).get("outfit_piece") if isinstance(item, dict) else None
    record = piece.get("template") if isinstance(piece, dict) else None
    return record if isinstance(record, dict) else {}


def params_of(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The item's validated template parameters, None when it has none stored."""
    stored = template_of(item).get("params")
    if not isinstance(stored, dict):
        return None
    return validate_params(stored)[0]


def suggest_params(item_id: str, *, character_name: str = "") -> Dict[str, Any]:
    """``{params, errors, raw}`` — the template parameters the vision task ``TASK`` reads off the item's picture
    and text (ONE queued ``llm_router.llm_call``; saves nothing). ValueError for an item that is no outfit piece
    or has no picture; RuntimeError when the LLM fails or answers no JSON."""
    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task
    from app.models.inventory import get_item, get_item_image_path
    item = get_item(item_id)
    if not item or item.get("category") != "outfit_piece":
        raise ValueError(f"{item_id} is no outfit piece")
    picture = get_item_image_path(item_id)
    if not picture:
        raise ValueError(f"{item.get('name') or item_id} has no picture — add one in the Items tab first")
    piece = item.get("outfit_piece") or {}
    system, user = render_task(TASK, piece_name=" ".join(str(item.get("name") or "").split()),
                               piece_text=" ".join(str(item.get("prompt_fragment") or "").split()),
                               slots=", ".join(str(s) for s in piece.get("slots") or []))
    response = llm_call(task=TASK, system_prompt=system, user_prompt=user, agent_name=character_name,
                        max_tokens=MAX_TOKENS, label=f"{TASK}:{item_id}", image_path=picture)
    text = getattr(response, "content", "") or ""
    try:
        raw = parse_answer(text)
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    params, errors = validate_params(raw)
    return {"params": params, "errors": errors, "raw": raw}


def set_params(item_id: str, params: Dict[str, Any], *, source: str = "user") -> Dict[str, Any]:
    """Store validated parameters on the item (``outfit_piece.template``); returns the stored
    record. ValueError for an item that is no outfit piece or for parameters with errors (nothing is
    stored then). Storing spends nothing: the next Build re-drapes (a new ``tsig``)."""
    from app.core.timeutils import utc_now_iso
    from app.models.inventory import get_item, outfit_piece_lock, update_item
    # One read-modify-write of the shared piece under its item lock (review 05#12).
    with outfit_piece_lock(item_id):
        item = get_item(item_id)
        if not item or item.get("category") != "outfit_piece":
            raise ValueError(f"{item_id} is no outfit piece")
        clean, errors = validate_params(params)
        if errors:
            raise ValueError("; ".join(errors))
        piece = dict(item.get("outfit_piece") or {})
        record = {"params": clean, "source": source if source in ("llm", "user") else "user",
                  "updated_at": utc_now_iso()}
        piece["template"] = record
        if update_item(item_id, {"outfit_piece": piece}) is None:
            raise ValueError(f"{item_id} could not be saved")
    from app.core import figure
    figure.invalidate()
    return record


# --- body measurements + panels ------------------------------------------------

def _hull_perimeter(points) -> float:
    import numpy as np
    from scipy.spatial import ConvexHull
    if len(points) < 4:
        return 0.0
    try:
        return float(ConvexHull(np.asarray(points)).area)   # 2-D: area = perimeter
    except Exception:  # noqa: BLE001 — degenerate slice
        return 0.0


def measure_body(glb: bytes) -> Dict[str, float]:
    """Heights (Y-up, metres) and circumferences of a plain rigged body: ``height``; ``waist_y``
    = the narrowest torso slice between 55 % and 75 % of the height; ``hip_y`` = the widest between
    45 % and the waist; ``band_y`` = the chest band under the arms (``BAND_SHARE``); ``waist_c`` /
    ``hip_c`` / ``band_c`` their convex-hull perimeters (slices 12 mm thick, |x| < 0.2 m so a
    T-posed arm never counts)."""
    import numpy as np
    from app.core import glb_mesh
    arrays = glb_mesh.body_arrays(glb)
    P = arrays.positions
    height = float(P[:, 1].max() - P[:, 1].min())
    floor = float(P[:, 1].min())

    def perim(y: float) -> float:
        sl = P[(np.abs(P[:, 1] - y) < 0.006) & (np.abs(P[:, 0]) < 0.2)][:, [0, 2]]
        return _hull_perimeter(sl)

    ys = np.arange(floor + 0.55 * height, floor + 0.75 * height, 0.01)
    waists = [(perim(y), y) for y in ys]
    waists = [w for w in waists if w[0] > 0]
    if not waists:
        raise ValueError("the body has no measurable torso")
    waist_c, waist_y = min(waists)
    hips = [(perim(y), y) for y in np.arange(floor + 0.45 * height, waist_y, 0.01)]
    hip_c, hip_y = max(hips) if hips else (waist_c, waist_y)
    band_y = floor + BAND_SHARE * height
    out = {"height": round(height, 4), "floor_y": round(floor, 4), "waist_y": round(float(waist_y), 4),
           "waist_c": round(waist_c, 4), "hip_y": round(float(hip_y), 4), "hip_c": round(hip_c, 4),
           "band_y": round(float(band_y), 4), "band_c": round(perim(band_y), 4)}
    out.update(_upper_measure(P, arrays.joint_positions, perim, floor, height))
    return out


#: The neck girth is read this far above the neck joint (mid neck: lower, the slice runs into the trapezius slope
#: — 0.436 m at +1.5 cm on the reference body against 0.33 m at +4 cm).
NECK_SLICE_M = 0.04
#: Where the arm girth is read, as shares of the arm (shoulder joint -> wrist joint).
ARM_SAMPLES = (0.05, 0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 0.97)
#: A slice of the arm takes the points within this distance of the arm axis (the T-posed arm is ~5 cm thick; the
#: chest is farther than this from the axis beyond the first 5 % of the arm).
ARM_SLICE_R = 0.09


def _upper_measure(P, joints: Dict[str, Any], perim, floor: float, height: float) -> Dict[str, Any]:
    """Ruling A142 — the upper body for a bodice (glTF Y-up metres, the bind pose = T-pose): ``shoulder_y`` (the
    arm joints' mean height), ``shoulder_w`` (the arm joints' distance + 8 cm: the deltoid either side, ~4 cm on the
    reference body), ``neck_y`` / ``neck_c`` (the neck joint and the neck girth ``NECK_SLICE_M`` above it), ``arm_len`` (shoulder
    joint -> wrist joint, the mean of both sides), ``arm_c`` = [[share, girth]] at ``ARM_SAMPLES`` (left arm; slices
    across the arm axis), ``upper_arm_c`` / ``wrist_c`` (the 0.25 / 0.97 samples), ``torso`` = [[y, girth]] every 2 cm
    from 40 % of the height to the shoulder line, and the joints a builder needs (``joints``). {} without a skin."""
    import numpy as np
    need = ("leftarm", "rightarm", "lefthand", "righthand", "neck")
    if not all(k in joints for k in need):
        return {}
    J = {k: np.asarray(v, float) for k, v in joints.items()}
    la, ra, lh, rh, nk = (J[k] for k in need)
    arm_len = float((np.linalg.norm(lh - la) + np.linalg.norm(rh - ra)) / 2)

    def arm_girth(share: float) -> float:
        axis = (lh - la) / max(1e-9, np.linalg.norm(lh - la))
        c = la + axis * share * np.linalg.norm(lh - la)
        rel = P - c
        along = rel @ axis
        radial = rel - np.outer(along, axis)
        sel = (np.abs(along) < 0.006) & (np.linalg.norm(radial, axis=1) < ARM_SLICE_R)
        if sel.sum() < 4:
            return 0.0
        e1 = np.cross(axis, [0.0, 1.0, 0.0])
        e1 /= max(1e-9, np.linalg.norm(e1))
        e2 = np.cross(axis, e1)
        pts = np.c_[radial[sel] @ e1, radial[sel] @ e2]
        return _hull_perimeter(pts)

    arm_c = [[s, round(arm_girth(s), 4)] for s in ARM_SAMPLES]
    neck_sl = P[(np.abs(P[:, 1] - (nk[1] + NECK_SLICE_M)) < 0.006) & (np.abs(P[:, 0] - nk[0]) < 0.08)][:, [0, 2]]
    shoulder_y = float((la[1] + ra[1]) / 2)
    torso = [[round(float(y), 3), round(perim(float(y)), 4)]
             for y in np.arange(floor + 0.40 * height, shoulder_y + 0.001, 0.02)]
    return {"shoulder_y": round(shoulder_y, 4), "shoulder_w": round(float(abs(la[0] - ra[0])) + 0.08, 4),
            "neck_y": round(float(nk[1]), 4), "neck_c": round(_hull_perimeter(neck_sl), 4),
            "arm_len": round(arm_len, 4), "arm_c": arm_c, "upper_arm_c": arm_c[2][1], "wrist_c": arm_c[-1][1],
            "torso": torso,
            "joints": {k: [round(float(x), 4) for x in J[k]] for k in ("leftarm", "rightarm", "leftforearm",
                                                                         "rightforearm", "lefthand", "righthand",
                                                                         "neck", "spine2") if k in J}}


def _waist_line(params: Dict[str, Any], meas: Dict[str, float]) -> float:
    w, h = meas["waist_y"], meas["hip_y"]
    return {"high": w + 0.03, "natural": w, "low": w - 0.5 * (w - h)}[params["waist_height"]]


#: Ease added to a body circumference (metres) where the piece closes round the body.
EASE_M = 0.02
#: The chest band under the arms, as a share of the body height (the T-posed upper arm and the armpit reach down to about 0.765 on the reference body).
BAND_SHARE = 0.75
#: Target edge length of the sampled grid.
GRID_M = 0.015
COLS = 41


def outline(params: Dict[str, Any], meas: Dict[str, float], *, over_sleeves: bool = False) -> Dict[str, Any]:
    """The piece's side profile: ``knots`` = [(height above the hem in metres, full circumference)]
    ascending from the hem (0) to the top, the top height ``top_y`` (Y-up world) and the pinned top. A skirt
    runs waist → hem; a dress runs chest band → waist → hem.

    The skirt part starts as a straight cone: at the waist line chosen the waist / hip girths interpolated
    linearly + ``EASE_M``, at the hem ``max(hip_c * 1.04, that) * (1 + 1.5 * flare)``. The body is not linear
    between waist and hips, so the cone alone can start INSIDE a wide hip (a low waist line); ``_skirt_knots``
    therefore holds the skirt part to max(cone, body girth + ``EASE_M``) at every height inside the measured torso
    profile (a knot at each torso sample, the top knot included). The hem knot keeps the cone value (the legs below
    the profile get no body floor), the profile is never narrower than the cone, and a body the cone already clears
    (or a measure without a ``torso`` profile) keeps the two cone knots unchanged."""
    waist_y = _waist_line(params, meas)
    # circumference at the waist line actually chosen
    frac = (waist_y - meas["hip_y"]) / max(1e-6, meas["waist_y"] - meas["hip_y"])
    waist_c = meas["hip_c"] + (meas["waist_c"] - meas["hip_c"]) * min(1.0, max(0.0, frac)) + EASE_M
    hem_c = max(meas["hip_c"] * 1.04, waist_c) * (1.0 + 1.5 * params["flare"])
    length = params["length_m"]
    top_y = waist_y
    if has_bodice(params):
        return _bodice_outline(params, meas, waist_y, waist_c, hem_c, over_sleeves=over_sleeves)
    if strapless_top(params):
        return _strapless_top_outline(params, meas, waist_y)
    knots = _skirt_knots(meas, waist_y, length, hem_c, waist_c)
    if params["kind"] == "dress":
        # A223: the top edge lies STRAPLESS_UNDERARM_M under the chest band, as a strapless top's (A221): at the band
        # the pinned top row met the underside of the T-posed arm on Lirien's body and one edge stretched to 1.503
        bodice = max(0.08, meas["band_y"] - STRAPLESS_UNDERARM_M - waist_y)
        knots.append((length + bodice, meas["band_c"] + EASE_M))
        top_y = waist_y + bodice
    return {"knots": knots, "top_y": round(top_y, 4), "waist_y": round(waist_y, 4),
            "length": round(knots[-1][0], 4)}


#: The shoulder line above the arm joint (the top of the T-posed upper arm at the joint, ~4.5 cm on the reference
#: body whose upper-arm girth at the joint is ~0.34 m -> radius 5.4 cm, less the slope towards the neck).
SHOULDER_TOP_M = 0.045
#: Bodice ease: the body girth times (1 + BODICE_EASE[0] + BODICE_EASE[1] * fit) + EASE_M; a jacket adds JACKET_EASE
#: (it is worn over a top).
BODICE_EASE = (0.03, 0.17)
JACKET_EASE = 0.05
#: Sleeve ease: the arm girth times (1 + SLEEVE_EASE[0] + SLEEVE_EASE[1] * sleeve_fit) + EASE_M.
SLEEVE_EASE = (0.05, 0.40)
#: Bug round 2026-11-20: a jacket draped over a READY lower TEMPLATE layer with sleeves (``over_sleeved_layer``) adds
#: this to its sleeve ease, and the same to its bodice ease from the chest band (the armhole's bottom) up, blended in
#: over ``ARMHOLE_BLEND_M`` below it (armhole room). Without it the jacket sleeve had exactly the rest girth of the
#: sleeve under it (both sleeve_fit 0.3: 0.371 m x 1.17 + 0.02 = 0.454 m at the shirt's hem) and one edge stretched
#: to 1.329 (limit 1.3). The value is MEASURED, not derived: the top of the approved range 0.05 .. 0.10, on Kai's
#: jacket over underwear + T-shirt + jeans (copies, first drape): 0.05 / 0.08 refused at the armpit (1.406 / 1.372),
#: 0.10 passes with a long sleeve (1.181) and a short one (1.181; 0.12 refused the short one at 1.312). The response
#: is not monotonic and 0.08 already fails, so 0.10 sits close to that edge; it was verified on one body and one fit
#: pair only. One cloth layer round the arm (2 x pi x 8 mm = 0.050 m, ~0.12 of Kai's arm girth) is only the order of
#: magnitude: the sleeve gap alone does not decide the drape (a jacket sleeve_fit 0 over the same shirt passes with
#: a ring gap of 0). Series and girths: ``scripts/smoke_jacket_layer_ease.py``.
JACKET_SLEEVE_EASE = 0.10
ARMHOLE_BLEND_M = 0.06
#: Neck opening: the neck girth's radius + NECK_CLEAR_M (crew); a boat neck opens to BOAT_SHARE of the half shoulder
#: width.
NECK_CLEAR_M = 0.012
BOAT_SHARE = 0.62
#: Ruling A142 pin rule (spike A135): the top PIN_BAND_M of a bodice within PIN_SHARE x the shoulder width.
PIN_BAND_M = 0.04
PIN_SHARE = 0.75
#: Spacing of the sleeve rings along the arm (coarser than the torso grid: a sleeve is a near-cylinder, and a long
#: sleeve at 1.5 cm doubled a jacket's vertices).
SLEEVE_RING_M = 0.025
#: Strap width of a dress with straps.
STRAP_W_M = 0.032


def _torso_girth(meas: Dict[str, Any], y: float) -> float:
    import numpy as np
    prof = meas.get("torso") or []
    if not prof:
        return float(meas.get("band_c") or 0.9)
    ys = [p[0] for p in prof]
    cs = [p[1] for p in prof]
    return float(np.interp(y, ys, cs, left=meas.get("hip_c", cs[0]), right=cs[-1]))


#: A torso sample closer than this to the hem or the top of a skirt part adds no knot of its own (no near-zero
#: panel edge); the end knot itself still keeps clear of the body there.
SKIRT_KNOT_GAP_M = 0.001


def _skirt_knots(meas: Dict[str, Any], top_y: float, length: float, hem_c: float,
                 top_c: float) -> List[Tuple[float, float]]:
    """The skirt part's side profile [(height above the hem, full circumference)] from the hem (``top_y -
    length``, height 0) up to ``top_y`` (height ``length``): the straight cone ``hem_c`` -> ``top_c``, but never
    narrower than the body. At every height inside the measured torso profile (``meas["torso"]``, sampled every
    2 cm from 40 % of the height up) the circumference is max(cone, ``_torso_girth`` + ``EASE_M``), with a knot at
    each torso sample between the ends and at both ends; below the profile's lowest sample there are only legs and no
    body floor: the hem knot keeps the cone value and the profile runs straight from it to the lowest sample's knot
    — the cone itself while that sample is on the cone, otherwise a straighter line above it (never narrower than
    the cone, and no step under the thighs). The body is linear between its samples and so is the cone, so the
    profile interpolated between these knots clears body + ``EASE_M`` everywhere in the torso range, not only at
    the knots.
    Exactly the two cone knots ``[(0, hem_c), (length, top_c)]`` when nothing is narrower than the body, and when
    the measure has no torso profile (``_torso_girth`` then answers the chest band, no floor for a skirt)."""
    cone = [(0.0, hem_c), (length, top_c)]
    prof = meas.get("torso") or []
    if not prof or length <= 0:
        return cone
    hem_y = top_y - length
    lo, hi = float(prof[0][0]) - 1e-9, float(prof[-1][0]) + 1e-9
    governed = False

    def at(y: float, c: float) -> float:
        nonlocal governed
        if not lo <= y <= hi:
            return c
        body = _torso_girth(meas, y) + EASE_M
        if body > c:
            governed = True
            return body
        return c

    knots = [(0.0, at(hem_y, hem_c))]
    for y, _g in prof:
        h = float(y) - hem_y
        if SKIRT_KNOT_GAP_M < h < length - SKIRT_KNOT_GAP_M:
            knots.append((h, at(float(y), hem_c + (top_c - hem_c) * h / length)))
    knots.append((length, at(top_y, top_c)))
    return knots if governed else cone


def _bodice_outline(params: Dict[str, Any], meas: Dict[str, Any], waist_y: float, waist_c: float,
                    hem_c: float, *, over_sleeves: bool = False) -> Dict[str, Any]:
    """The side profile of a piece with a bodice (Ruling A142): from the hem up the body's own girth with the ease
    (``BODICE_EASE``; a dress's skirt part follows the skirt profile ``_skirt_knots`` below its waist line, read at
    this 2 cm grid) to the shoulder line
    ``top_y`` = shoulder joints + ``SHOULDER_TOP_M``. A jacket ``over_sleeves`` has armhole room: + ``layer_ease``
    from the chest band up, blended in over ``ARMHOLE_BLEND_M`` below it."""
    import numpy as np
    if "shoulder_y" not in meas:
        raise ValueError("the body has no arm / neck joints to fit a bodice to")
    top_y = _length_origin(meas, None)
    ease = 1.0 + BODICE_EASE[0] + BODICE_EASE[1] * params["fit"] + (JACKET_EASE if params["kind"] == "jacket" else 0)
    room = layer_ease(params, over_sleeves)

    def eased(y: float) -> float:
        w = min(1.0, max(0.0, 1.0 - (meas["band_y"] - y) / ARMHOLE_BLEND_M)) if room else 0.0
        return _torso_girth(meas, y) * (ease + room * w) + EASE_M
    skirt_h: List[float] = []
    skirt_c: List[float] = []
    if params["kind"] == "dress":
        hem_y = waist_y - params["length_m"]
        # the skirt part: the skirt's own profile (never narrower than the body), read at this grid
        skirt = _skirt_knots(meas, waist_y, waist_y - hem_y, hem_c, waist_c)
        skirt_h, skirt_c = [h for h, _c in skirt], [c for _h, c in skirt]
    else:
        hem_y = max(meas["floor_y"] + 0.2, top_y - params["length_m"])
    hem_y, moved = _clear_underbust(params, meas, hem_y, top_y)
    knots = []
    for y in np.arange(hem_y, top_y - 1e-6, 0.02):
        y = float(y)
        if params["kind"] == "dress" and y <= waist_y:
            c = float(np.interp(y - hem_y, skirt_h, skirt_c))
        else:
            c = eased(y)
        knots.append((round(y - hem_y, 4), round(c, 4)))
    knots.append((round(top_y - hem_y, 4), round(eased(top_y), 4)))
    return {"knots": knots, "top_y": round(top_y, 4), "waist_y": round(waist_y, 4), "length": knots[-1][0],
            **({"hem_moved": moved} if moved else {})}


#: Bug round 2026-11-20: a top's or jacket's hem closer than this to the measured underbust fold (``_bust_lines``,
#: the same line as ``bust_shaping.landmarks`` ``under_y``) is moved this far BELOW the fold — never up, a piece is
#: never made shorter. On the fold the hem's cloth spans the step from the chest to the rib cage and a few edges
#: there take the drape's pull: Lirien's top at length 0.27 (hem 1.178 m, fold 1.168 m) failed at stretch 1.48 with
#: p99 1.03; at 0.31 (hem 1.138 m, 3 cm under the fold) it drapes at 1.09.
UNDERBUST_HEM_M = 0.03


#: Review of the bug round 2026-11-20: the fold is only a fold when the torso girth climbs at least this much (full
#: circumference, metres) from the underbust line to the bust line. ``_bust_lines`` always names a line — on a torso
#: that widens evenly (a flat chest) it is simply the lowest sample of its window — and a hem there spans no step:
#: 8 cm more girth over 10 cm of height is 1.3 cm of radius, nothing the cloth has to bridge. The measured bodies of
#: the bug round climb 0.24-0.34 m (Lirien 0.98 - 0.64), the even probe of the review 0.08 m.
UNDERBUST_STEP_M = 0.10


def _length_origin(meas: Dict[str, Any], strapless_top_y: Optional[float]) -> float:
    """The line a top's / jacket's ``length_m`` counts down from (Y-up metres): the shoulder line (joints +
    ``SHOULDER_TOP_M``); a strapless top on a body without arm / neck joints counts from 12 cm over its top edge
    (``strapless_top_y``). A bodice without the joints is no piece (``_bodice_outline`` refuses it first)."""
    if "shoulder_y" in meas:
        return float(meas["shoulder_y"]) + SHOULDER_TOP_M
    if strapless_top_y is None:
        raise ValueError("the body has no arm / neck joints to fit a bodice to")
    return strapless_top_y + 0.12


def _underbust_fold(meas: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """``(under_y, bust_y)`` of ``_bust_lines`` when the body has an underbust fold to clear: a measured torso profile
    (not the band-less-15-cm stand-in) whose girth climbs at least ``UNDERBUST_STEP_M`` from the underbust line to the
    bust line; else None (a flat or evenly widening chest — no hem is moved, no underbust sentence is given)."""
    if len(_bust_profile(meas)) < 3:
        return None
    under_y, bust_y = _bust_lines(meas)
    if _torso_girth(meas, bust_y) - _torso_girth(meas, under_y) < UNDERBUST_STEP_M:
        return None
    return under_y, bust_y


def _clear_underbust(params: Dict[str, Any], meas: Dict[str, Any], hem_y: float,
                     length_from: float) -> Tuple[float, Optional[Dict[str, Any]]]:
    """``(hem_y, moved)`` — the hem height of a top / jacket off the underbust fold (``UNDERBUST_HEM_M``): a hem
    within that distance of the fold goes ``UNDERBUST_HEM_M`` under it, and ``moved`` records it for the drape
    record and the UI (``{under_y, from_y, hem_y, length_m (asked), draped_length_m}``, lengths counted from
    ``length_from``, the line ``length_m`` counts from); any other hem stays (``moved`` None), and so does every hem
    on a body without a fold (``_underbust_fold``)."""
    fold = _underbust_fold(meas) if params.get("kind") in ("top", "jacket") else None
    if fold is None:
        return hem_y, None
    under_y = fold[0]
    if abs(hem_y - under_y) >= UNDERBUST_HEM_M:
        return hem_y, None
    new = under_y - UNDERBUST_HEM_M
    return new, {"under_y": round(under_y, 4), "from_y": round(hem_y, 4), "hem_y": round(new, 4),
                 "length_m": round(float(params["length_m"]), 4),
                 "draped_length_m": round(length_from - new, 4)}


def _strapless_top_outline(params: Dict[str, Any], meas: Dict[str, Any], waist_y: float) -> Dict[str, Any]:
    """A221: the side profile of a strapless top — a tube from the hem up to ``STRAPLESS_UNDERARM_M`` under the
    chest band (``band_y``, the top of a strapless dress), the body's own girth with the bodice ease (``BODICE_EASE``, so fit 0
    is a snug corset) + ``EASE_M`` every 2 cm. ``length_m`` counts from the shoulder line (joints +
    ``SHOULDER_TOP_M``) like every top; the hem stays at least ``STRAPLESS_MIN_M`` below the top edge and 0.2 m above
    the floor."""
    import numpy as np
    top_y = float(meas["band_y"]) - STRAPLESS_UNDERARM_M
    shoulder = _length_origin(meas, top_y)
    hem_y = min(top_y - STRAPLESS_MIN_M, max(meas["floor_y"] + 0.2, shoulder - params["length_m"]))
    hem_y, moved = _clear_underbust(params, meas, hem_y, shoulder)
    ease = 1.0 + BODICE_EASE[0] + BODICE_EASE[1] * params["fit"]
    knots = [(round(float(y) - hem_y, 4), round(_torso_girth(meas, float(y)) * ease + EASE_M, 4))
             for y in np.arange(hem_y, top_y - 1e-6, 0.02)]
    knots.append((round(top_y - hem_y, 4), round(_torso_girth(meas, top_y) * ease + EASE_M, 4)))
    return {"knots": knots, "top_y": round(top_y, 4), "waist_y": round(waist_y, 4), "length": knots[-1][0],
            **({"hem_moved": moved} if moved else {})}


def sweetheart_depth(params: Dict[str, Any]) -> float:
    """A221: the sweetheart dip at the front centre in metres (``neck_depth_m`` 0 = ``SWEETHEART_DIP_M``)."""
    return min(SWEETHEART_MAX_M, params["neck_depth_m"] or SWEETHEART_DIP_M)


def top_drop(params: Dict[str, Any], cols: int) -> Optional[List[float]]:
    """A221: how far each column of the FRONT panel's top edge of a strapless top lies under the band (metres; column
    c at the angle pi + pi * c / (cols - 1), the front centre 1.5 pi) — a sweetheart dip, None for every other
    piece (a top with straps carries its dip in ``bodice_spec``'s ``top_edge``)."""
    if not strapless_top(params) or params["neckline"] != "sweetheart":
        return None
    depth = sweetheart_depth(params)
    return [round(sweetheart_drop(depth, abs(math.pi * c / (cols - 1) - math.pi / 2)), 5) for c in range(cols)]


def sweetheart_drop(depth: float, off: float, half_rad: float = SWEETHEART_HALF_RAD) -> float:
    """A221: how far a sweetheart top edge lies under the band at ``off`` radians round from the front centre:
    depth * (1 - off / half_rad)^2 inside +-half_rad, 0 outside (the drape's ``top_drop``, the straps builder's cut
    and the dialog preview's top edge)."""
    return depth * (1.0 - off / half_rad) ** 2 if off < half_rad else 0.0


def bodice_spec(params: Dict[str, Any], meas: Dict[str, Any], *, over_sleeves: bool = False) -> Dict[str, Any]:
    """What the Blender builder needs beyond the torso rows for a piece with a bodice (Ruling A142), glTF Y-up
    metres: armhole ``band_y`` (the chest band under the arms) to ``top_y``; the neck opening ``neck_r`` (radius
    round the neck joint), ``neckline`` and its front ``depth_m`` below the neck base; ``shoulders`` with the strap
    centre ``strap_x`` / ``strap_w``; ``pin_half_x`` / ``pin_band_m``; ``sleeve`` {len_m, rings: [[metres from the
    shoulder joint along the arm, circumference]]} (None without sleeves); ``front_open``; ``collar``. A jacket
    ``over_sleeves`` adds ``layer_ease`` to the sleeve ease."""
    import numpy as np
    shape = outline(params, meas, over_sleeves=over_sleeves)
    neck_r = meas["neck_c"] / (2 * math.pi) + NECK_CLEAR_M
    half_sh = meas["shoulder_w"] / 2.0
    neckline = params["neckline"]
    top_edge = None
    if neckline in STRAPLESS_NECKLINES:
        # A221: a corset top with straps — the yoke is built as a crew neck's and cut away above the chest band
        # (``top_edge``: the band, lowered by the sweetheart dip round the front centre); only the straps stay
        top_edge = {"neckline": neckline, "dip_m": sweetheart_depth(params) if neckline == "sweetheart" else 0.0,
                    "half_rad": SWEETHEART_HALF_RAD}
        neckline = "crew"
    collar = params["collar"] if params["kind"] == "jacket" else "none"
    front_open = params["kind"] == "jacket" and (params["front"] == "open" or collar == "lapel")
    depth = params["neck_depth_m"] or NECK_DEPTH[neckline]
    if collar == "lapel":
        neckline = "v"
        depth = max(depth, meas["shoulder_y"] - meas["band_y"] + 0.04)
    if neckline == "boat":
        neck_r = max(neck_r, BOAT_SHARE * half_sh)
    sleeve = None
    if has_sleeves(params):
        length = SLEEVE_SHARE[params["sleeves"]] * meas["arm_len"]
        ease = 1.0 + SLEEVE_EASE[0] + SLEEVE_EASE[1] * params["sleeve_fit"] + layer_ease(params, over_sleeves)
        shares = [a for a, _c in meas["arm_c"]]
        girths = [c for _a, c in meas["arm_c"]]
        rings = []
        for d in np.arange(0.0, length + 1e-6, SLEEVE_RING_M):
            share = float(d) / meas["arm_len"]
            rings.append([round(float(d), 4), round(float(np.interp(share, shares, girths)) * ease + EASE_M, 4)])
        if rings[-1][0] < length - 1e-3:
            if length - rings[-1][0] < SLEEVE_RING_M / 2 and len(rings) > 1:
                rings.pop()                # Ruling A144: a last ring a few mm past its neighbour drapes as a pucker
            rings.append([round(length, 4), round(float(np.interp(length / meas["arm_len"], shares, girths)) * ease
                                                  + EASE_M, 4)])
        sleeve = {"len_m": round(length, 4), "rings": rings}
    return {"band_y": meas["band_y"], "top_y": shape["top_y"], "neck_y": meas["neck_y"], "neck_r": round(neck_r, 4),
            "front_y": meas["shoulder_y"],
            "neckline": neckline, "depth_m": round(float(depth), 4), "shoulders": params["shoulders"],
            "strap_x": round(strap_shoulder_x(meas, neck_r), 4), "strap_w": STRAP_W_M,
            "pin_half_x": round(PIN_SHARE * half_sh, 4), "pin_band_m": PIN_BAND_M, "sleeve": sleeve,
            "front_open": front_open, "collar": collar, "joints": meas.get("joints") or {}, "top_edge": top_edge,
            "off_shoulder": off_shoulder_spec(params, meas)}


def off_shoulder_spec(params: Dict[str, Any], meas: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A229 — the cut and the pins of an off-shoulder piece (glTF Y-up metres; None for every other piece):
    ``line_y`` = the band's top edge on the chest and the back = shoulder joints + ``SHOULDER_TOP_M`` -
    ``band_drop_m``; ``arm_out_m`` = where it crosses each upper arm, out from the shoulder joint
    (``OFF_SHOULDER_ARM_M``); ``band_m`` = the pinned band's height under that edge; ``lace`` = the front opening
    ``{depth_m, gap_m}`` from the band down (None without lacing)."""
    if not off_shoulder(params) or "shoulder_y" not in meas:
        return None
    lace = ({"depth_m": round(params["lace_depth_m"], 4), "gap_m": LACE_GAP_M}
            if params["lacing"] == "front" else None)
    return {"line_y": round(meas["shoulder_y"] + SHOULDER_TOP_M - params["band_drop_m"], 4),
            "arm_out_m": OFF_SHOULDER_ARM_M, "band_m": round(params["band_m"], 4), "lace": lace}


def _sleeve_panel(sleeve: Dict[str, Any]):
    """The sleeve as a pygarment panel (cm): cap width = the first ring, cuff = the last, length along the arm."""
    from app.third_party.pygarment.garmentcode.edge import Edge
    from app.third_party.pygarment.garmentcode.panel import Panel
    rings = sleeve["rings"]
    cap, cuff, length = rings[0][1] * 100, rings[-1][1] * 100, max(1.0, sleeve["len_m"] * 100)
    panel = Panel("sleeve")
    pts = [[0, 0], [cuff, 0], [cuff / 2 + cap / 2, length], [cuff / 2 - cap / 2, length]]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        panel.edges.append(Edge(a, b))
    return json.loads(json.dumps(panel.assembly().pattern, default=str))


def panel_spec(params: Dict[str, Any], meas: Dict[str, float], *, over_sleeves: bool = False) -> Dict[str, Any]:
    """The pattern of a built kind as two pygarment panels (front, back; each half the
    circumference), sampled to quad grids: ``{rows, cols, row_y (Y-up world height per row, row 0 =
    the pinned top), panels: [{name, grid_m: rows x cols x 2}], pygarment: {front, back}}``.
    ``over_sleeves``: the piece drapes over a lower layer with sleeves (``over_sleeved_layer``; a jacket gets
    ``layer_ease``). ValueError for a kind not built yet."""
    import numpy as np
    from app.third_party.pygarment.garmentcode.edge import Edge
    from app.third_party.pygarment.garmentcode.edge_factory import CurveEdgeFactory
    from app.third_party.pygarment.garmentcode.panel import Panel
    if params["kind"] not in BUILT_KINDS:
        raise ValueError(KIND_NOT_BUILT.format(kind=params["kind"]))
    if params["kind"] in FITTED_KINDS:
        return fitted_spec(params, meas)
    shape = outline(params, meas, over_sleeves=over_sleeves)
    knots = shape["knots"]
    total = knots[-1][0]
    rows = int(min(81, max(12, round(total / GRID_M) + 1)))
    panels, specs = [], {}
    for name, dip in (("front", 0.01), ("back", 0.004)):
        half = [(y, c / 2.0) for y, c in knots]
        hem_w = half[0][1]
        cx = hem_w / 2.0
        # pygarment panel (cm): hem curve, right side up through the knots, top, left side down
        cm = [(y * 100.0, w * 100.0) for y, w in half]
        right = [[cx * 100 + w / 2, y] for y, w in cm]
        left = [[cx * 100 - w / 2, y] for y, w in cm][::-1]
        panel = Panel(name)
        hem = CurveEdgeFactory.curve_3_points(left[-1], right[0], target=[cx * 100, -dip * 200])
        panel.edges.append(hem)
        for a, b in zip(right[:-1], right[1:]):
            panel.edges.append(Edge(a, b))
        panel.edges.append(Edge(right[-1], left[0]))
        for a, b in zip(left[:-1], left[1:]):
            panel.edges.append(Edge(a, b))
        specs[name] = json.loads(json.dumps(panel.assembly().pattern, default=str))
        ys = [y for y, _w in half]
        ws = [w for _y, w in half]
        grid = []
        for r in range(rows):
            y = total * (1.0 - r / (rows - 1))                  # row 0 = top
            w = float(np.interp(y, ys, ws))
            xs = np.linspace(cx - w / 2.0, cx + w / 2.0, COLS)
            grid.append([[float(x), float(y)] for x in xs])
        panels.append({"name": name, "grid_m": grid})
    row_y = [round(shape["top_y"] - total * r / (rows - 1), 5) for r in range(rows)]
    out = {"rows": rows, "cols": COLS, "row_y": row_y, "panels": panels, "outline": shape, "measure": meas,
           "pygarment": {"version": "2.0.2", "panels": specs}}
    drop = top_drop(params, COLS)
    if drop:
        out["top_drop"] = {"front": drop}
    if has_bodice(params):
        out["bodice"] = bodice_spec(params, meas, over_sleeves=over_sleeves)
        if layer_ease(params, over_sleeves):
            out["layer_ease"] = JACKET_SLEEVE_EASE
        if out["bodice"]["sleeve"]:
            specs["sleeve"] = _sleeve_panel(out["bodice"]["sleeve"])
    return out


# --- A223: the fitted kinds (briefs, bra, gloves) --------------------------------------------------------------
#: The gap a fitted piece is laid out at over the skin (metres; the cloth run's collision distance comes on top of
#: nothing: the builder lays it out of the collider first). Gloves add ``GLOVE_FIT_M`` x fit.
FITTED_OFFSET_M = 0.004
GLOVE_FIT_M = 0.012
#: The cloth run's collision distance of a fitted piece (a skirt's is 4 mm: a fitted piece lies on the skin).
FITTED_THICKNESS_M = 0.0015
#: The fingers of a glove (``fingers`` full): a tight overlay this far over the skin, pinned (never draped).
FINGER_OFFSET_M = 0.0015
#: The cloth frames of a fitted piece's relax run (it starts on the body: a few frames settle it).
FITTED_FRAMES = 15
#: Briefs: the gusset's half width at the crotch, and where the leg opening reaches at the side when ``leg_cut`` is 0
#: (a boyshort: this far below the crotch).
GUSSET_HALF_M = 0.03
BOYSHORT_DROP_M = 0.03
#: Briefs / bra: the band at the top that is pinned at the least (metres).
MIN_PIN_BAND_M = 0.012
#: Bra: a bra without an underband (``underband_m`` 0) still has a strap this high round the back (it holds it).
BACK_STRAP_M = 0.012
#: Bra: the push-up's largest lift / pull to the centre / push forward of the cup (metres, at ``push_up`` 1).
PUSH_LIFT_M = 0.02
PUSH_IN_M = 0.012
PUSH_OUT_M = 0.008
#: Gloves: how far the cuff reaches from the wrist joint up the arm — a share of the forearm (wrist, forearm) or the
#: whole forearm plus a share of the upper arm (elbow, opera).
GLOVE_REACH = {"wrist": (0.18, 0.0), "forearm": (0.55, 0.0), "elbow": (1.0, 0.12), "opera": (1.0, 0.7)}
#: Gloves: a flared cuff stands this far out at its edge, over CUFF_M; a folded one is doubled (this much thicker).
CUFF_FLARE_M = 0.015
CUFF_FOLD_M = 0.004
#: A223 tights: the hosiery lies this far over the skin (fit 0: a second skin, pinned whole).
HOSIERY_OFFSET_M = 0.0035
#: Tights: a grip band (hold-up) / a sock's cuff this high at the top, HOSIERY_BAND_EXTRA_M thicker; a waistband of
#: full tights is ``WAISTBAND_M`` high and as much thicker.
HOLDUP_BAND_M = 0.04
SOCK_CUFF_M = 0.025
HOSIERY_BAND_EXTRA_M = 0.0015
#: Tights: a stocking's top lies this far under the crotch, a knee sock's this far under the knee joint.
THIGH_TOP_DROP_M = 0.07
KNEE_TOP_DROP_M = 0.05
#: Tights: a garter tab — this half width at the front and the back of each thigh, this far up over the top.
GARTER_TAB_HALF_M = 0.012
GARTER_TAB_H_M = 0.04
CUFF_M = 0.06
#: A232 boxers (briefs with ``leg_length_m`` > 0): the cloth lies FITTED_OFFSET_M + this x ``fit`` over the skin; up to
#: BOXER_SNUG_FIT the hems are pinned with the waistband (trunks, boxer briefs), looser ones hang from the waistband.
BOXER_FIT_M = 0.02
BOXER_SNUG_FIT = 0.3
#: A232 boxers: the pinned band at each leg hem (snug fits).
BOXER_HEM_PIN_M = 0.015
#: A235 string briefs: the front panel's top corner lies the first share of the way from the gusset to the hip's side
#: at ``leg_cut`` 1 and the second share further at ``leg_cut`` 0; the back panel's corner the first share past its
#: width (``back_coverage``). Past the corners only the hip band runs.
STRING_CORNER = (0.35, 0.35)


def _bust_profile(meas: Dict[str, Any]) -> List[Any]:
    """The torso samples ``_bust_lines`` looks for the bust line in: between the waist + 5 cm and the chest band."""
    return [p for p in meas.get("torso") or [] if meas["waist_y"] + 0.05 <= p[0] <= meas["band_y"]]


def _bust_lines(meas: Dict[str, Any]) -> Tuple[float, float]:
    """A223 — ``(underbust_y, bust_y)`` off the torso profile (glTF Y-up metres): the bust line is the widest torso
    slice between the waist + 5 cm and the chest band under the arms; the underbust line the narrowest between 14 and
    4 cm under it. Without a profile: the band less 7 / 15 cm (the reference body's proportions)."""
    prof = _bust_profile(meas)
    if len(prof) < 3:
        return round(meas["band_y"] - 0.15, 4), round(meas["band_y"] - 0.07, 4)
    bust_y = max(prof, key=lambda p: p[1])[0]
    under = [p for p in meas.get("torso") or [] if bust_y - 0.14 <= p[0] <= bust_y - 0.04]
    under_y = min(under, key=lambda p: p[1])[0] if under else bust_y - 0.08
    return round(float(under_y), 4), round(float(bust_y), 4)


def strap_shoulder_x(meas: Dict[str, Any], neck_r: float) -> float:
    """Where a strap crosses the shoulder, sideways from the neck joint (metres): half way between the neck opening
    and ``PIN_SHARE`` of the half shoulder width — the straps of a dress / corset top (A221, ``bodice_spec``) and of a
    bra (A223, ``strap_spec``) alike."""
    return 0.5 * (neck_r + PIN_SHARE * meas["shoulder_w"] / 2.0)


def strap_spec(params: Dict[str, Any], meas: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A223 — the straps of a piece with a band under the chest, shared by every kind that has them (the bra now; a
    corset top can take the same record): ``{style, width_m, shoulder_x, back_x, neck_y, neck_r}`` in glTF Y-up metres
    (``shoulder_x`` = where a strap crosses the shoulder, measured from the neck joint sideways: half way between the
    neck opening and ``PIN_SHARE`` of the half shoulder width, as a dress's straps; ``back_x`` = where it meets the
    band on the back, the opposite side for ``cross``; a halter runs round the back of the neck at ``neck_y`` +
    ``NECK_SLICE_M`` instead). None for ``straps`` none or a body without arm / neck joints."""
    style = params.get("straps") or "none"
    if style == "none" or "shoulder_w" not in meas:
        return None
    neck_r = meas["neck_c"] / (2 * math.pi) + NECK_CLEAR_M
    shoulder_x = strap_shoulder_x(meas, neck_r)
    return {"style": style, "width_m": STRAP_WIDTH_M[style], "shoulder_x": round(shoulder_x, 4),
            "back_x": round(-shoulder_x if style == "cross" else shoulder_x, 4),
            "neck_y": round(meas["neck_y"] + NECK_SLICE_M, 4), "neck_r": round(neck_r, 4)}


def trouser_hem(length: str, anchors: Dict[str, float]) -> float:
    """A233: the hem height of a trouser leg (``TROUSER_HEM``) from its anchors ``{crotch, knee, ankle}`` (Y-up
    metres): from + share x (to - from) + extra."""
    a, b, share, extra = TROUSER_HEM[length]
    return anchors[a] + share * (anchors[b] - anchors[a]) + extra


def trouser_spec(params: Dict[str, Any], meas: Dict[str, Any]) -> Dict[str, Any]:
    """A233 — the trouser part of ``fitted_spec``: ``top_y`` (the briefs' rise rule: the hip line + ``RISE_SHARE`` x
    (waist - hip line)), the waist band (``TROUSER_WAIST_M``, pinned at least ``MIN_PIN_BAND_M``), the hem rule
    (``TROUSER_HEM``: the builder reads the anchors off the body), the leg shape's radii (``LEG_SHAPE_R``) with the
    ease, the cloth's gap (``FITTED_OFFSET_M`` + ``TROUSER_FIT_M`` x fit), the cuff / stirrup, the pins (the
    waist band always; the hem too for a skinny leg or a stirrup) and the seat (``seat_spec``)."""
    top = meas["hip_y"] + RISE_SHARE[params["rise"]] * (meas["waist_y"] - meas["hip_y"])
    waist = params["trouser_waist"]
    skinny = params["leg_shape"] == "skinny"
    return {"top_y": round(top, 4), "band_m": round(max(MIN_PIN_BAND_M, TROUSER_WAIST_M[waist]), 4),
            "waistband_m": TROUSER_WAIST_M[waist],
            "waist_extra_m": TROUSER_WAIST_EXTRA_M[waist], "length": params["trouser_length"],
            "hem_rule": list(TROUSER_HEM[params["trouser_length"]]), "shape": params["leg_shape"],
            "shape_r": list(LEG_SHAPE_R[params["leg_shape"]]) if LEG_SHAPE_R[params["leg_shape"]] else None,
            "radial_ease": round(TROUSER_RADIAL_EASE * params["fit"], 4),
            "offset_m": round(FITTED_OFFSET_M + TROUSER_FIT_M * params["fit"], 4),
            "ramp_m": TROUSER_RAMP_M, "centre_gap_m": TROUSER_CENTRE_GAP_M, "hem": params["hem"],
            "cuff_m": TROUSER_CUFF_M, "cuff_fold_m": TROUSER_CUFF_FOLD_M,
            "hem_pinned": skinny or params["hem"] == "stirrup", "hem_pin_m": TROUSER_HEM_PIN_M,
            "seat": seat_spec(params["seat"]), "frames": TROUSER_FRAMES}


def seat_spec(seat: str) -> Dict[str, Any]:
    """Bug round 2026-11-20: the seat's part of ``trouser_spec`` (``SEATS``; the builder's
    ``garment_template_fitted.trouser_seat``) — a fitted seat moves nothing."""
    return {"name": seat, "ease_m": SEAT_EASE_M[seat], "bridge": seat != "fitted",
            "slice_m": SEAT_SLICE_M, "hull_m": SEAT_HULL_M, "ramp_m": SEAT_RAMP_M, "fade_m": SEAT_FADE_M,
            "relax_passes": SEAT_RELAX_PASSES, "fill_passes": SEAT_FILL_PASSES}


def fitted_spec(params: Dict[str, Any], meas: Dict[str, Any]) -> Dict[str, Any]:
    """A223 — what the builder cuts a fitted piece from (``FITTED_KINDS``), glTF Y-up metres: ``{fitted: {kind, …},
    row_y: [top, bottom], outline, measure}``. The region is read off the plain body in Blender (its bones and
    surface); the heights and lengths are decided here:

    * briefs: ``top_y`` = the hip line + ``RISE_SHARE`` x (waist - hip line); the pinned band ``band_m`` (at least
      ``MIN_PIN_BAND_M``); ``leg_cut`` / ``back_coverage`` / ``side_width_m`` shape the leg openings (builder);
    * bra: ``under_y`` / ``bust_y`` (``_bust_lines``), the band ``band_m`` under the underbust line (``BACK_STRAP_M``
      round the back without one), the gore (``GORE``), ``push`` and the straps (``strap_spec``);
    * trousers (A233): ``trouser_spec`` — the waistband, the hem rule, the leg shape's radii, the gap, the pins;
    * gloves: ``reach_m`` = how far the cuff reaches from the wrist up the arm (``GLOVE_REACH`` of the measured
      forearm / upper arm), the gap ``offset_m`` (``FITTED_OFFSET_M`` + ``GLOVE_FIT_M`` x fit), the cuff."""
    kind = params["kind"]
    fit: Dict[str, Any] = {"kind": kind, "offset_m": FITTED_OFFSET_M, "frames": FITTED_FRAMES}
    if kind == "briefs":
        top = meas["hip_y"] + RISE_SHARE[params["rise"]] * (meas["waist_y"] - meas["hip_y"])
        fit.update({"top_y": round(top, 4), "band_m": round(max(MIN_PIN_BAND_M, WAISTBAND_M[params["waistband"]]), 4),
                    "waistband_m": WAISTBAND_M[params["waistband"]], "leg_cut": params["leg_cut"],
                    "back_coverage": params["back_coverage"], "side_width_m": params["side_width_m"],
                    "gusset_half_m": GUSSET_HALF_M, "boyshort_drop_m": BOYSHORT_DROP_M})
        if params.get("sides") == "string":
            # A235: front and back panel only, thin hip bands ``string_width_m`` high under the waist line
            fit.update({"sides": "string", "string_width_m": round(float(params["string_width_m"]), 4),
                        "string_corner": list(STRING_CORNER)})
        leg = float(params.get("leg_length_m") or 0.0)
        if leg > 0:
            # A232: short legs to a straight hem ``leg`` under the crotch; leg_cut / back_coverage do not apply
            fit.update({"leg_length_m": round(leg, 4), "fit": params["fit"],
                        "offset_m": round(FITTED_OFFSET_M + BOXER_FIT_M * params["fit"], 4),
                        "hem_pinned": params["fit"] <= BOXER_SNUG_FIT, "hem_pin_m": BOXER_HEM_PIN_M})
        rows = [round(top, 4), round(meas["hip_y"] - 0.2 - leg, 4)]
    elif kind == "trousers":
        fit.update(trouser_spec(params, meas))
        rows = [fit["top_y"], round(meas.get("floor_y", 0.0), 4)]
    elif kind == "bra":
        under, bust = _bust_lines(meas)
        gore_half, gore_h = GORE[params["center_gore"]]
        band = params["underband_m"]
        fit.update({"under_y": under, "bust_y": bust, "style": params["cup_style"], "coverage": params["cup_coverage"],
                    "push": params["push_up"], "band_m": round(band, 4), "back_strap_m": BACK_STRAP_M,
                    "gore_half_m": gore_half, "gore_h_m": gore_h, "closure": params["closure"],
                    "rigid_cups": params["cup_style"] == "molded",
                    "push_m": [PUSH_LIFT_M, PUSH_IN_M, PUSH_OUT_M], "straps": strap_spec(params, meas)})
        rows = [round(meas.get("shoulder_y", bust + 0.15), 4), round(under - max(band, BACK_STRAP_M), 4)]
    elif kind == "tights":
        style = params["tights_style"]
        top = meas["waist_y"] if style == "tights" else None      # the others: per leg, read off the bones (builder)
        fit.update({"style": style, "feet": params["feet"], "garters": params["garters"] if style == "thigh_high"
                    else "none", "top_y": round(top, 4) if top is not None else None,
                    "offset_m": HOSIERY_OFFSET_M,
                    "waistband_m": WAISTBAND_M[params["waistband"]] if style == "tights" else 0.0,
                    "band_m": HOLDUP_BAND_M if style == "hold_up" else (SOCK_CUFF_M if style == "knee_high" else 0.0),
                    "band_extra_m": HOSIERY_BAND_EXTRA_M, "thigh_drop_m": THIGH_TOP_DROP_M,
                    "knee_drop_m": KNEE_TOP_DROP_M, "tab_half_m": GARTER_TAB_HALF_M, "tab_h_m": GARTER_TAB_H_M})
        rows = [round(meas["waist_y"], 4), round(meas.get("floor_y", 0.0), 4)]
    else:
        j = meas.get("joints") or {}
        if not all(k in j for k in ("leftarm", "leftforearm", "lefthand")):
            raise ValueError("the body has no arm joints to fit gloves to")
        fore = math.dist(j["leftforearm"], j["lefthand"])
        upper = math.dist(j["leftarm"], j["leftforearm"])
        a, b = GLOVE_REACH[params["length"]]
        fit.update({"reach_m": round(a * fore + b * upper, 4), "fingers": params["fingers"], "cuff": params["cuff"],
                    "fit": params["fit"],
                    "offset_m": round(FITTED_OFFSET_M + GLOVE_FIT_M * params["fit"], 4),
                    "finger_offset_m": FINGER_OFFSET_M, "cuff_m": CUFF_M, "cuff_flare_m": CUFF_FLARE_M,
                    "cuff_fold_m": CUFF_FOLD_M})
        rows = [round(meas.get("shoulder_y", 1.4) + 0.1, 4), round(meas.get("shoulder_y", 1.4) - 0.1, 4)]
    shape = {"knots": [], "top_y": rows[0], "waist_y": meas["waist_y"], "length": round(rows[0] - rows[1], 4)}
    return {"fitted": fit, "row_y": rows, "outline": shape, "measure": meas, "rows": 0, "cols": 0, "panels": []}


# --- cache ----------------------------------------------------------------------

def sheer_opacity(params: Optional[Dict[str, Any]]) -> Optional[float]:
    """A204: the opacity of a sheer piece's cloth (``PARAM_SPEC`` range), None for every other fabric."""
    if not params or params.get("fabric") != SHEER:
        return None
    lo, hi = PARAM_SPEC["opacity"][1]
    value = _number(params.get("opacity"))
    return round(min(hi, max(lo, PARAM_SPEC["opacity"][2] if value is None else value)), 3)


def material_key(params: Optional[Dict[str, Any]]) -> str:
    """The assembly identity of a template piece's fabric material: ``sheer:<opacity>``,
    ``leather_<finish>.v<LEATHER_SURFACE_VERSION>`` (A214) or "" (the plain fabrics)."""
    fabric = (params or {}).get("fabric")
    if fabric in LEATHER_SURFACES:
        return f"{fabric}.v{LEATHER_SURFACE_VERSION}"
    opacity = sheer_opacity(params)
    return "" if opacity is None else f"{SHEER}:{opacity}"


def material_overrides(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A204: the ``glb_mesh.graft`` material keys of a sheer piece — alphaMode BLEND with the base colour's alpha =
    the opacity (the baked picture keeps the item's colour as the tint), double-sided (the inside of a skirt is seen
    through its front), ``extras.anima_sheer`` for the renderers (depth write off, drawn after the body). None for an
    opaque fabric (the graft stays exactly as before).

    A214: a leather finish sets its fixed surface over whatever the piece's material preset gave — roughness, metal 0,
    the generator's roughness map dropped, a clear coat (glossy) or a faint sheen (rough); the extension it does
    not use is removed (``None``), so a cotton preset's sheen never lands on glossy leather."""
    surface = LEATHER_SURFACES.get(str((params or {}).get("fabric") or ""))
    if surface is not None:
        ext: Dict[str, Any] = {"KHR_materials_clearcoat": None, "KHR_materials_sheen": None}
        if surface["clearcoat"]:
            factor, rough = surface["clearcoat"]
            ext["KHR_materials_clearcoat"] = {"clearcoatFactor": factor, "clearcoatRoughnessFactor": rough}
        if surface["sheen"]:
            colour, rough = surface["sheen"]
            ext["KHR_materials_sheen"] = {"sheenColorFactor": [colour] * 3, "sheenRoughnessFactor": rough}
        return {"pbrMetallicRoughness": {"metallicRoughnessTexture": None, "roughnessFactor": surface["roughness"],
                                         "metallicFactor": 0.0},
                "extensions": ext,
                "extras": {"anima_material": params["fabric"], "explicit_metallic": False}}
    opacity = sheer_opacity(params)
    if opacity is None:
        return None
    return {"alphaMode": "BLEND", "doubleSided": True,
            "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, opacity]},
            "extras": {"anima_sheer": True, "opacity": opacity}}


def _md5(payload: Any) -> str:
    return hashlib.md5(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def keyed_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """The parameters a drape is keyed by (``tsig``): without ``MATERIAL_ONLY`` / ``TEXTURE_ONLY`` and the fields
    that mean nothing for the piece's kind; the leather finishes share one drape fabric. ``garment_template_cut``
    keys the cut by the same set less the drape-only fields."""
    params = {k: v for k, v in params.items() if k not in MATERIAL_ONLY and k not in TEXTURE_ONLY}
    if params.get("kind") != "trousers":                # A233: the trouser fields key only trousers
        params = {k: v for k, v in params.items() if k not in TROUSER_FIELDS}
    if params.get("shoulders") != "off_shoulder":      # A229: the off-shoulder fields key only an off-shoulder piece
        params = {k: v for k, v in params.items() if k not in OFF_SHOULDER_FIELDS}
    if not params.get("leg_length_m"):                  # A232: a brief without legs keeps the key it had
        params.pop("leg_length_m", None)
    if params.get("sides") != "string":                 # A235: a brief with side panels keeps the key it had
        params.pop("sides", None)
        params.pop("string_width_m", None)
    if params.get("fabric") in DRAPE_FABRIC:          # A214: the leather finishes share one drape
        params["fabric"] = DRAPE_FABRIC[params["fabric"]]
    return params


def tsig(params: Dict[str, Any], *, base_sha: str, texture_sha: str, lower: List[str]) -> str:
    """The cache key of one drape (module docstring)."""
    params = keyed_params(params)
    payload = {"params": params, "version": TEMPLATE_VERSION, "base": base_sha, "texture": texture_sha,
               "lower": sorted(lower)}
    if params.get("kind") == "dress" and not has_bodice(params):
        # A223: a strapless dress's top edge moved under the chest band — only these drapes are due again
        payload["strapless_top_m"] = STRAPLESS_UNDERARM_M
    if params.get("kind") in FITTED_KINDS and FITTED_VERSION:
        # step 3a (D7 b): the fitted kinds' own version — only their drapes are due again (0 = the keys before it)
        payload["fitted"] = FITTED_VERSION
    return _md5(payload)


def templates_dir(character_name: str) -> Path:
    from app.core.garment_store import garments_dir
    return garments_dir(character_name) / "templates"


def drape_path(character_name: str, item_id: str, sig: str) -> Path:
    return templates_dir(character_name) / f"{item_id}_{sig}.glb"


def islands_path(character_name: str, item_id: str, sig: str) -> Path:
    """The drape's pattern islands (``uv_pattern.islands_payload``) beside its GLB — written for a ``PATTERN_KINDS``
    piece (a top with a bodice, every fitted kind)."""
    return templates_dir(character_name) / f"{item_id}_{sig}.islands.json"


def failed_path(character_name: str, item_id: str, sig: str) -> Path:
    return templates_dir(character_name) / "failed" / f"{item_id}_{sig}.json"


def _file_sha(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def texture_sources(character_name: str, item_id: str) -> Dict[str, str]:
    """``{front, back, source}`` (A205 first): the template piece's own piece-only views
    (``garment_template_views``, ``source`` "piece_only"; a missing side takes the other side's view) — for a SHEER
    piece ONLY these, both of them, never the item picture ({} until they exist) — unless its texture comes from the
    cut (``garment_template_views.projection_optional``: the projection is only the fallback). Else the piece's newest cut-out (piece-only) views from the garment store
    (``images/{item}_{fsig}_cutout_{front,back}.png``) whenever ANY exists — a missing side takes the other
    side's view (Ruling A141: the cut-outs are always preferred) —, else its item picture for both sides
    (``source`` "item_image"; ``run_drape`` masks it to the garment). {} without any picture."""
    from app.core import garment_template_views as tv
    from app.core.garment_store import garments_dir
    from app.models.inventory import get_item, get_item_image_path
    own = {v: tv.accepted(character_name, item_id, v) for v in tv.VIEWS}
    item = get_item(item_id)
    # with the texture from cut the projection is only the fallback: a sheer piece then takes what any piece takes
    if tv.is_sheer(item) and not tv.projection_optional(item):
        if own["front"] is None or own["back"] is None:
            return {}
        return {"front": str(own["front"]), "back": str(own["back"]), "source": "piece_only"}
    if own["front"] is not None or own["back"] is not None:
        return {"front": str(own["front"] or own["back"]), "back": str(own["back"] or own["front"]),
                "source": "piece_only"}
    folder = garments_dir(character_name) / "images"
    best: Dict[str, Tuple[float, str]] = {}
    if folder.is_dir():
        for side in ("front", "back"):
            for path in folder.glob(f"{item_id}_*_cutout_{side}.png"):
                if ".try" in path.name:
                    continue
                stamp = path.stat().st_mtime
                if side not in best or stamp > best[side][0]:
                    best[side] = (stamp, str(path))
    if best:
        front = (best.get("front") or best["back"])[1]
        back = (best.get("back") or best["front"])[1]
        return {"front": front, "back": back, "source": "cutout"}
    picture = get_item_image_path(item_id)
    return {"front": picture, "back": picture, "source": "item_image"} if picture else {}


def lower_layers(mesh_ids: Any, item_id: str) -> List[str]:
    """The other worn mesh pieces (own-mesh and template: ``figure.WornSets.own``, or the outfit
    model's ``mesh_items.intended``) — the lower layers in the cache key (module docstring). An ACCESSORY piece is
    never one: it is built on the plain body over everything and no drape lies on it — and ``mesh_items.intended``
    lists it while ``WornSets.own`` does not, so the assembly's key differed from the Build's and a ready drape was
    left off (2026-11-20, Lirien: naked figure, "Not the whole outfit")."""
    from app.core import garment_set
    from app.models.inventory import get_item
    others = {str(i) for i in (mesh_ids or ())} - {item_id}
    return sorted(i for i in others if garment_set.mesh_mode_of(get_item(i) or {}) != garment_set.ACCESSORY)


def _template_kind(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """The built kind of a template piece, else None."""
    from app.core import garment_set
    if garment_set.mesh_mode_of(item) != garment_set.TEMPLATE:
        return None
    params = params_of(item)
    return params["kind"] if params and params["kind"] in BUILT_KINDS else None


def inner_pieces(item_id: str, kind: str, lower: List[str]) -> Tuple[List[Tuple[str, Dict[str, Any]]],
                                                                     List[Tuple[str, Dict[str, Any]]]]:
    """The worn pieces a template piece drapes OVER — ``(templates, own)``, each ``[(item id, item)]`` in id order.

    A piece is under ``item_id`` when ``garment_set.layer_order`` over the worn set puts it there (``LAYER_STACKS``
    and ``covers``, A200) or — for a template piece — by ``LAYER_RANK`` (Ruling A142: a jacket over a top or a
    dress), unless the order puts it over ``item_id``. ``templates``: their drapes are colliders and their keys part
    of this key; ``own``: own-mesh / shell clothing whose plain-body fit is a collider (A200, a draped jacket over a
    generated top) and whose fit file's sha256 is part of this key."""
    from app.core import garment_set
    from app.models.inventory import get_item
    others = sorted({str(i) for i in lower} - {item_id})
    if not others:
        return [], []
    order = garment_set.layer_order(set(others) | {item_id})
    below = set(order["under"].get(item_id, []))
    rank = LAYER_RANK.get(kind, 1)
    templates, own = [], []
    for other in others:
        it = get_item(other)
        okind = _template_kind(it)
        if okind is not None:
            by_rank = LAYER_RANK.get(okind, 1) < rank and item_id not in order["under"].get(other, [])
            if other in below or by_rank:
                templates.append((other, it))
        elif other in below and garment_set.garment_kind_of(it) == garment_set.CLOTHING:
            own.append((other, it))
    return templates, own


def collider_pieces(item_id: str, kind: str, lower: List[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """The worn TEMPLATE pieces ``item_id`` drapes over (``inner_pieces``) — ``[(item id, item)]`` in id order."""
    return inner_pieces(item_id, kind, lower)[0]


def own_colliders(character_name: str, item_id: str, kind: str, lower: List[str], *,
                  base_sha: str) -> List[Tuple[str, Optional[Path]]]:
    """A200: the own-mesh / shell pieces under a template piece (``inner_pieces``) with their accepted fit on the
    current base model (``garment_store.accepted_fit``; None while there is none — that piece is no collider yet,
    and its ``-`` in the key re-drapes once it is fitted)."""
    from app.core import garment_store
    out: List[Tuple[str, Optional[Path]]] = []
    for other, _it in inner_pieces(item_id, kind, lower)[1]:
        fit = garment_store.accepted_fit(character_name, other, base_model_sha=base_sha) if base_sha else None
        out.append((other, Path(fit[0]) if fit else None))
    boot = boot_collider(character_name, item_id, kind, lower, base_sha=base_sha)
    if boot is not None:
        out.append(boot)
    return out


def boot_hem_mode(character_name: str, item_id: str, kind: str, lower: List[str], *,
                  base_sha: str) -> Optional[Tuple[str, str, Path]]:
    """A237: ``(mode, boot item, boot fit)`` when template trousers whose leg hangs over the shoe
    (``tucked_into_shoes`` False) are worn with a boot (``outfit_options.is_boot_record``) — ``mode`` the profile's
    boot hem (``outfit_options.boot_hem``): ``over`` = the leg hangs over the shaft (the boot is a collider of the
    drape), ``tucked`` = the leg is taken into the boot at the assembly (``garment_assembly._into_shoe``). Else None."""
    if kind != "trousers" or not base_sha:
        return None
    from app.core import garment_set, garment_store, outfit_options
    from app.models.character import get_character_profile
    from app.models.inventory import get_item
    if tucked_into_shoes(params_of(get_item(item_id))):
        return None
    for other in sorted({str(i) for i in lower} - {item_id}):
        if garment_set.garment_kind_of(get_item(other)) != garment_set.FOOTWEAR:
            continue
        try:
            fit = garment_store.accepted_fit(character_name, other, base_model_sha=base_sha)
        except ValueError:
            fit = None
        if fit and outfit_options.is_boot_record(fit[1]):
            mode = outfit_options.boot_hem(get_character_profile(character_name) or {})
            return mode, other, Path(fit[0])
    return None


def boot_collider(character_name: str, item_id: str, kind: str, lower: List[str], *,
                  base_sha: str) -> Optional[Tuple[str, Optional[Path]]]:
    """A237: the boot as a collider of template trousers worn OVER its shaft (``boot_hem_mode`` ``over``)."""
    hem = boot_hem_mode(character_name, item_id, kind, lower, base_sha=base_sha)
    return (hem[1], hem[2]) if hem and hem[0] == "over" else None


def _lower_of(other: str, item_id: str, lower: List[str]) -> List[str]:
    """The lower-layer list of the collider piece ``other`` within the same worn set."""
    return sorted((set(lower) | {item_id}) - {other})


def collider_states(character_name: str, item_id: str, kind: str, lower: List[str], *,
                    base_sha: str) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """``[(item id, item, drape_state)]`` of the lower template layers ``item_id`` drapes over (``collider_pieces``),
    each judged within the same worn set (``_lower_of``). Read-only."""
    return [(other, it, drape_state(character_name, other, base_sha=base_sha, lower=_lower_of(other, item_id, lower),
                                    item=it))
            for other, it in collider_pieces(item_id, kind, lower)]


def key_for(character_name: str, item_id: str, *, base_sha: str, lower: List[str],
            item: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """``(tsig, reason, texture sources)`` of a template piece: tsig None with the left-off
    reason when it cannot be draped (no parameters, a kind not built, no base, no picture). A piece worn over
    lower template layers (``collider_pieces``) folds their keys into its own: a changed top re-drapes the jacket.
    ``lower`` is the whole worn set; only the pieces of it under this one enter the key — a piece over it does not."""
    return _key(character_name, item_id, base_sha=base_sha, lower=lower, item=item)[:3]


def texture_sha_of(sources: Dict[str, str]) -> Optional[str]:
    """The texture part of the drape key: md5 of the two source pictures' sha256 (``key_for``; stored on a drape's
    record as ``texture_sha`` since the cut-texture rework, 2026-11-20). None without both sources (a grid kind):
    such a record never stands in (``cut_stand_in``)."""
    if not sources.get("front") or not sources.get("back"):
        return None
    return _md5([_file_sha(sources["front"]), _file_sha(sources["back"])])


def _key(character_name: str, item_id: str, *, base_sha: str, lower: List[str],
         item: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Dict[str, str],
                                                         Optional[Dict[str, Any]], List[str]]:
    """``key_for`` plus what the key was made of besides the texture: ``(tsig, reason, sources, params, under)`` — so ``cut_stand_in`` can recompute the key of an older drape with ITS texture part."""
    from app.models.inventory import get_item
    item = item if item is not None else get_item(item_id)
    params = params_of(item)
    if params is None:
        return None, NEEDS_PARAMS, {}, None, []
    if params["kind"] not in BUILT_KINDS:
        return None, KIND_NOT_BUILT.format(kind=params["kind"]), {}, None, []
    if not base_sha:
        return None, NO_BASE, {}, None, []
    sources = texture_sources(character_name, item_id)
    if not sources:
        from app.core import garment_template_views as tv
        if tv.is_sheer(item) and not tv.projection_optional(item):
            return None, tv.SHEER_NEEDS_VIEWS, {}, None, []
        return None, NEEDS_PARAMS.replace("parameters", "picture"), {}, None, []
    tex = texture_sha_of(sources)
    under = under_tokens(character_name, item_id, params, base_sha=base_sha, lower=lower, item=item)
    # Only what the drape is really cut against keys it: the pieces UNDER it (their drape keys / fit identities, the
    # boot it hangs over), the jacket allowance, the chest shaping. A piece worn OVER it (or beside it) changes nothing
    # of this drape — keying by the whole worn set re-draped the shirt when the jacket over it came off (2026-11-20).
    return tsig(params, base_sha=base_sha, texture_sha=tex, lower=under), None, sources, params, under


def under_tokens(character_name: str, item_id: str, params: Dict[str, Any], *, base_sha: str, lower: List[str],
                 item: Optional[Dict[str, Any]] = None,
                 states: Optional[List[Tuple[str, Dict[str, Any], Dict[str, Any]]]] = None) -> List[str]:
    """The ``lower`` part of a drape key (``_key``) — what the piece is cut and draped against: the template drapes
    under it (their keys), the own-mesh fits under it (their identities), the jacket allowance, the fitted cut's
    mark, the chest shaping. ``garment_template_cut`` keys the cut by the same tokens. ``states`` = the
    ``collider_states`` the caller already read (else they are read here). Read-only."""
    under = []
    ready = []
    if states is None:
        states = collider_states(character_name, item_id, params["kind"], lower, base_sha=base_sha)
    for other, it, sub in states:
        under.append(f"{other}:{sub['tsig'] or '-'}")
        if sub["state"] == "ready":
            ready.append(it)
    # A200: an own-mesh piece under it is a collider; its fit's identity re-drapes this piece when it changes
    for other, fit in own_colliders(character_name, item_id, params["kind"], lower, base_sha=base_sha):
        from app.core.base_body import file_sha256
        under.append(f"{other}:fit:{file_sha256(fit) if fit is not None else '-'}")
    if layer_ease(params, over_sleeved_layer(params["kind"], ready)):
        # bug round 2026-11-20: a jacket over a draped sleeved layer is cut wider (``layer_ease``) — only these
        # re-drape, and again when that layer's drape becomes ready or goes, or the allowance changes
        under.append(f"ease:over_sleeves:{JACKET_SLEEVE_EASE}")
    if under and params["kind"] in FITTED_KINDS:
        # A237: a fitted piece over lower layers (a loose one clipped, a boot left out of the cut) — only these re-drape
        under.append("cut:body")
    # A228: a piece that shapes the chest under it re-drapes when its lift changes (``bust_shaping``)
    from app.core import bust_shaping
    under += bust_shaping.key_tokens(item_id, item, lower)
    return under


def cut_stand_in(character_name: str, item_id: str, *, base_sha: str, params: Dict[str, Any],
                 key_lower: List[str]) -> Optional[Dict[str, Any]]:
    """Cut-texture rework (user finding 2026-11-20, Dario): a piece whose texture comes from the cut shows the cut
    atlas, never the projection the drape baked — so a drape whose key differs from the current one ONLY in its
    texture part (a piece-only view made, re-made, uploaded or removed after the drape) still stands for the piece:
    no re-drape at the next Build, and the piece never drops off the figure. Exact, not a guess: the record's own
    ``texture_sha`` put into the CURRENT key's other parts must give the record's ``tsig``. A drape from before the
    record carried ``texture_sha`` never stands in (it re-drapes once, as before). The newest such drape wins.
    ``{tsig, path, record}`` or None."""
    from app.core.garment_store import read_record
    folder = templates_dir(character_name)
    if not folder.is_dir():
        return None
    best = None
    for meta in folder.glob(f"{_glob.escape(item_id)}_*.json"):
        rec = read_record(meta)
        glb = meta.with_suffix(".glb")
        tex = rec.get("texture_sha")
        if rec.get("accepted") is not True or not tex or not glb.is_file() or rec.get("item_id") != item_id:
            continue
        if tsig(params, base_sha=base_sha, texture_sha=str(tex), lower=key_lower) != rec.get("tsig"):
            continue
        stamp = str(rec.get("created_at") or "")
        if best is None or stamp > best[0]:
            best = (stamp, {"tsig": rec.get("tsig"), "path": glb, "record": rec})
    return best[1] if best else None


def stamp_texture_sha(character_name: str, item_id: str) -> bool:
    """Write ``texture_sha`` into the piece's CURRENT ready drape record when it has none (a drape from before the
    cut-texture rework) — called by ``garment_template_views`` right BEFORE a piece-only view changes (made, used,
    uploaded, removed; the cut flow's own back view too). Exact, not a guess: the record sits under the current key,
    so its texture part IS ``texture_sha_of`` of the current sources at this moment. Without it the view change moves
    the key and an old drape cannot stand in (``cut_stand_in``): the piece dropped off the figure until another Build
    (review finding 2026-11-20). True when a record was written; never raises (the view change goes on)."""
    try:
        from app.core import base_body, figure
        from app.core.garment_store import read_record, write_record
        from app.models.character import get_character_profile
        from app.models.inventory import get_item
        profile = get_character_profile(character_name) or {}
        item = get_item(item_id)
        sets = figure.worn_sets(character_name, profile=profile)
        worn = item_id in set(sets.pieces.values())
        base = base_body.current_base(character_name, profile=profile)
        if not base:
            return False
        sig, _reason, sources, _params, _lower = _key(
            character_name, item_id, base_sha=base[1], lower=lower_layers(sets.own, item_id) if worn else [],
            item=item)
        if sig is None:
            return False
        path = drape_path(character_name, item_id, sig)
        meta = path.with_suffix(".json")
        record = read_record(meta)
        if not path.is_file() or record.get("accepted") is not True or record.get("texture_sha"):
            return False
        tex = texture_sha_of(sources)
        if not tex:
            return False
        write_record(meta, {**record, "texture_sha": tex})
        return True
    except Exception as e:  # noqa: BLE001 — the view change must not fail on it
        logger.warning("Template %s %s: texture_sha not stamped: %s", character_name, item_id, e)
        return False


def refused_only_by_time(failed: Dict[str, Any]) -> bool:
    """Whether a failure record's ONLY failed gate row is ``build_wall_s`` — written while the wall time still
    gated (before 2026-11-18). Such a drape passed every quality row, so it is no refusal now: ``drape_state``
    treats its key as not draped yet (its GLB was not kept), the next Build — automatic too — drapes it again, and
    the record goes when that drape is accepted or is overwritten by a real verdict. No ``TEMPLATE_VERSION`` bump:
    the same parameters drape the same, and a bump would re-drape every READY piece of every character as well."""
    bad = [r for r in failed.get("rows") or [] if isinstance(r, dict) and r.get("gate") and not r.get("ok")]
    return bool(bad) and all(r.get("check") == "build_wall_s" for r in bad)


def drape_state(character_name: str, item_id: str, *, base_sha: str, lower: List[str],
                item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{state, reason, tsig, path, record}`` — ``ready`` (the drape GLB of the current key exists
    and its record passed), ``failed`` (the current key failed; reason = ``DRAPE_FAILED``, plus ``failure`` =
    ``failure_info`` of the record),
    ``missing`` (``NOT_DRAPED``; also a failure record ``refused_only_by_time``; ``CUT_REDRAPE`` for a drape of
    another cut, ``cut_behind``) or ``blocked`` (no key: reason from ``key_for``). Read-only."""
    from app.core.garment_store import read_record
    sig, reason, _sources, params, key_lower = _key(character_name, item_id, base_sha=base_sha, lower=lower,
                                                    item=item)
    if sig is None:
        return {"state": "blocked", "reason": reason, "tsig": None, "path": None, "record": {}}
    path = drape_path(character_name, item_id, sig)
    record = read_record(path.with_suffix(".json"))
    behind = False
    if path.is_file() and record.get("accepted") is True:
        if not cut_behind(character_name, item_id, record, params, base_sha=base_sha, lower=lower, item=item):
            return {"state": "ready", "reason": "", "tsig": sig, "path": path, "record": record}
        behind = True
    if params and params.get("texture") == "cut":
        # the texture from cut replaces the projection: a drape that differs only in its texture part stands in
        stand = cut_stand_in(character_name, item_id, base_sha=base_sha, params=params, key_lower=key_lower)
        if stand is not None and not cut_behind(character_name, item_id, stand["record"], params, base_sha=base_sha,
                                                lower=lower, item=item):
            return {"state": "ready", "reason": "", **stand, "stand_in": True}
    failed = read_record(failed_path(character_name, item_id, sig))
    if failed and not refused_only_by_time(failed):
        return {"state": "failed", "reason": DRAPE_FAILED.format(error=failed.get("error") or "?"), "tsig": sig,
                "path": None, "record": failed, "failure": failure_info(failed)}
    return {"state": "missing", "reason": CUT_REDRAPE if behind else NOT_DRAPED, "tsig": sig, "path": None,
            "record": {}}


def cut_behind(character_name: str, item_id: str, record: Dict[str, Any], params: Optional[Dict[str, Any]], *,
               base_sha: str, lower: List[str], item: Optional[Dict[str, Any]] = None) -> bool:
    """Cut-first review (2026-11-21): whether a drape ``record`` was laid out of ANOTHER cut than the piece's current
    one — its recorded ``cut_sig`` differs from ``garment_template_cut.sig_of`` now (a new ``uv_pattern.py``, a lower
    layer that became ready after the drape). Such a drape counts as not draped (``drape_state`` "missing",
    ``CUT_REDRAPE``) and the next Build drapes it again under the SAME ``tsig`` — no other drape moves, and the
    islands it writes are the current cut's, so the cut texture lands on it. False for a record without
    ``cut_sig`` (a drape from before cut-first, or one laid out of shrunk / dropped own-mesh colliders: neither is
    re-draped for it — ``cut_info`` "drape_other" says so) and while the current cut has no sig (not a pattern
    piece, a lower layer still to be draped: the Build drapes that first)."""
    recorded = (record or {}).get("cut_sig")
    if not recorded or not params or params.get("kind") not in PATTERN_KINDS:
        return False
    from app.core import garment_template_cut
    now = garment_template_cut.sig_of(character_name, item_id, params, base_sha=base_sha, lower=lower, item=item)[0]
    return now is not None and now != recorded


# --- live progress of a drape in flight (A172) ---------------------------------------
#: What a drape in flight is doing now, per (character, item): ``{stage, started, stage_at, attempt, file}`` —
#: ``build`` / ``run_drape`` set the server-side stages, the Blender run writes its own (frame, pose shape i/n, bake,
#: measure) into ``file`` (``progress_file`` of the job params). Read by ``live_progress``; gone when the run ends.
_live: Dict[Tuple[str, str], Dict[str, Any]] = {}
_live_lock = threading.Lock()
#: The stage labels the dialog shows (translatable keys); Blender's stages are the last four.
LIVE_STAGES = {
    "waiting": "Waiting for the layers under it",
    "measure_body": "Measuring the body",
    "views": "Preparing the picture views",
    "setup": "Cutting the panels in Blender",
    "drape": "Draping the cloth on the CPU",
    "shapes": "Draping the pose shapes",
    "bake": "Texturing from the picture",
    "measure": "Measuring the poses",
    "judge": "Checking the drape",
}


def _register_cpu_labels() -> None:
    """A194: the drape's stage keys are ``cpu_progress`` labels too (the shared live line)."""
    from app.core import cpu_progress
    cpu_progress.register_labels({k: v for k, v in LIVE_STAGES.items()})


_register_cpu_labels()


def _live_stage(key: Optional[Tuple[str, str]], stage: str, **fields: Any) -> None:
    if stage != "blender":
        # A194: the same stage into the shared live line (the Blender run attaches itself in ``runner.run``).
        from app.core import cpu_progress
        cpu_progress.stage(stage)
    if key is None:
        return
    import time
    with _live_lock:
        entry = _live.setdefault(key, {"started": time.monotonic(), "attempt": 1, "file": None})
        entry.update(fields)
        entry["stage"] = stage
        entry["stage_at"] = time.monotonic()


def _live_end(key: Optional[Tuple[str, str]]) -> None:
    if key is not None:
        with _live_lock:
            _live.pop(key, None)


def live_progress(character_name: str, item_id: str) -> Optional[Dict[str, Any]]:
    """A172: the drape of ``item_id`` on ``character_name`` in flight now — ``{stage, label, frame, frames, pose,
    index, count, attempt, elapsed_s, stage_s}`` (the Blender run's own record from its progress file wins over the
    server stage while the run is in Blender) — or None when none runs. Read-only, never raises."""
    import time
    with _live_lock:
        entry = dict(_live.get((character_name, item_id)) or {})
    if not entry:
        return None
    out: Dict[str, Any] = {"stage": entry.get("stage") or "", "frame": None, "frames": None, "pose": None,
                           "index": None, "count": None, "attempt": int(entry.get("attempt") or 1)}
    path = entry.get("file")
    if path and entry.get("stage") == "blender":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            out.update({k: data.get(k) for k in ("frame", "frames", "pose", "index", "count")})
            out["stage"] = str(data.get("stage") or "setup")
        else:
            out["stage"] = "setup"
    if out["stage"] == "blender":
        out["stage"] = "setup"
    now = time.monotonic()
    out["label"] = LIVE_STAGES.get(out["stage"], out["stage"])
    out["elapsed_s"] = round(now - float(entry.get("started") or now), 1)
    out["stage_s"] = round(now - float(entry.get("stage_at") or now), 1)
    from app.core import cpu_progress
    out["cpu"] = cpu_progress.snapshot(f"piece:{character_name}:{item_id}")  # A194: the shared live line
    return out


#: The drape step's detail while the character's Build runs but has not reached this piece's drape yet (A172).
WAITING_FOR_STEP = "The Build runs — the drape starts at its step"
#: The steps of a template piece's progress (``piece_progress``), in chain order.
PROGRESS_STEPS: Tuple[Tuple[str, str], ...] = (("params", "Parameters"), ("picture", "Picture"),
                                               ("drape", "Drape (CPU)"))


def piece_progress(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
                   item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the parameter dialog shows of ONE template piece on ``character_name`` (A168) — the same rule as the
    Figure tab's row (``drape_state`` on the current base model, with the other worn mesh pieces as lower layers):
    ``{state ("ready" / "missing" / "failed" / "blocked" / "running"), reason, built_at, error, worn, steps,
    failure, inner_collider, hem_moved}`` (``failure``: ``failure_info`` of a failed drape, else None;
    ``hem_moved``: the outline's record of a hem moved off the underbust fold, ``_clear_underbust``, else None) —
    ``steps`` in the step-list shape of ``model_overview`` (``{id, label, status, detail, numbers}``: parameters
    stored, a picture to colour it from, the drape). ``running``: a Build of the character runs (it drapes the worn
    template pieces). Read-only."""
    from app.core import base_body, figure, figure_build
    from app.models.inventory import get_item
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    item = item if item is not None else get_item(item_id)
    sets = figure.worn_sets(character_name, profile=profile)
    worn = item_id in set(sets.pieces.values())
    base = base_body.current_base(character_name, profile=profile)
    drape = drape_state(character_name, item_id, base_sha=base[1] if base else "",
                        lower=lower_layers(sets.own, item_id) if worn else [], item=item)
    record = drape["record"] or {}
    params = params_of(item)
    sources = texture_sources(character_name, item_id)
    from app.core import garment_template_views as tv
    sheer_missing = (tv.missing_views(character_name, item_id)
                     if tv.is_sheer(item) and not tv.projection_optional(item) else [])
    # A176: only while the Build still has this piece's drape ahead of it (or runs it) — a Build that already
    # draped it and now waits on another piece (Dario, 2026-11-17: 11 min behind a shoe mesh) shows the outcome,
    # never "running" until the whole Build ends.
    building = worn and figure_build.fits_piece(character_name, item_id)
    live = live_progress(character_name, item_id)
    state = "running" if (building or live) and drape["state"] != "ready" else drape["state"]
    metrics = record.get("metrics") or {}
    steps = [
        {"id": "params", "label": "Parameters", "status": "done" if params else "due",
         "detail": "" if params else NEEDS_PARAMS,
         "numbers": {"kind": params["kind"], "fabric": params["fabric"]} if params else {}},
        {"id": "picture", "label": "Picture", "status": "done" if sources else "due",
         "detail": {"piece_only": "the piece-only views", "cutout": "the piece-only cut-out views",
                    "item_image": "the item picture"}.get(sources.get("source", ""), "") if sources
         else (tv.SHEER_NEEDS_VIEWS if sheer_missing else "No picture of the piece yet"),
         "numbers": {"hub_jobs": len(sheer_missing)} if sheer_missing else {}},
        {"id": "drape", "label": "Drape (CPU)",
         "status": {"ready": "done", "failed": "failed", "blocked": "skipped"}.get(state, "due"),
         "detail": (live["label"] if live else WAITING_FOR_STEP) if state == "running" else drape["reason"] or "",
         "numbers": {k: v for k, v in (("wall_s", work_wall_s(metrics)),
                                       ("stretch_max", (metrics.get("drape") or {}).get("stretch_max")),
                                       ("coverage", (metrics.get("bake") or {}).get("coverage"))) if v is not None}},
    ]
    return {"state": state, "reason": drape["reason"], "built_at": record.get("created_at") or "",
            "error": str(record.get("error") or "") if drape["state"] == "failed" else "", "worn": worn, "steps": steps,
            "live": live if state == "running" else None,
            "failure": drape.get("failure") if drape["state"] == "failed" else None,
            "inner_collider": record.get("inner_collider") if drape["state"] == "ready" else None,
            # bug round 2026-11-20: the hem moved off the underbust fold (``_clear_underbust``) in the drape shown
            "hem_moved": (metrics.get("outline") or {}).get("hem_moved") if drape["state"] in ("ready", "failed")
            else None}


# --- the drape run ----------------------------------------------------------------

def build_args(params: Dict[str, Any], spec: Dict[str, Any], *, item_id: str, render: bool = False,
               poses: Optional[Tuple[str, ...]] = None, quality_scale: float = 1.0,
               corrective: bool = True, lower_shapes: Optional[List[Any]] = None,
               lower_offsets: Optional[List[float]] = None) -> Dict[str, Any]:
    """The ``params`` of one ``garment_template_build`` run. ``corrective`` False = the A138 drape
    (nearest-face weights, no pose shapes) — kept for the before/after measurement. ``lower_shapes`` = the pose-shape
    payloads of the lower drapes (inputs ``lower_<i>``; Ruling A142 layering), in input order."""
    fabric = dict(FABRICS[params["fabric"]])
    fabric["quality"] = int(round(fabric["quality"] * quality_scale))
    meas = spec.get("measure") or {}
    torso = max(meas.get("hip_c", 0.9), meas.get("band_c", 0.9)) / (2 * math.pi) * 1.6
    hem_y = (spec.get("row_y") or [0.0])[-1]
    long_top = bool(meas) and hem_y < meas.get("hip_y", 0.0)
    groups = shape_groups(params, long_top=long_top) if corrective else []
    return {"spec": spec, "fabric": fabric, "torso_half_m": round(torso, 4), "slit": {"side": params["slit"], "depth_m": params["slit_m"]},
            "drape_quality": int(round(fabric["quality"] * (BODICE_DRAPE_QUALITY if has_bodice(params) else 1.0))),
            "pin": "top", "kind": params["kind"], "item_id": item_id, "node": f"garment_template_{item_id}",
            "render": bool(render), "poses": list(poses or measured_poses(params)),
            "frames": (BODICE_FRAMES if has_bodice(params) else
                       int((spec.get("fitted") or {}).get("frames") or 50)),
            "thickness": FITTED_THICKNESS_M if spec.get("fitted") else 0.004,
            "smooth_weights": bool(corrective), "shape_groups": groups,
            "shape_poses": [p for g in groups if g["name"] == "legs" for p in g["poses"]],
            "lower_shapes": list(lower_shapes or []), "lower_offsets": list(lower_offsets or []),
            # pattern-piece UV islands for a top and the fitted kinds; a jacket and a dress with a bodice keep the grid
            # UV until step 3b
            "uv_mode": "pattern" if params["kind"] in PATTERN_KINDS else "grid"}


def work_wall_s(data: Dict[str, Any]) -> Optional[float]:
    """The wall seconds a drape WORKED (``data`` of ``run_drape``): ``wall_total_s`` less the proof runs' sheet
    renders (a Build never renders, Ruling A142) and less the waits for a free Blender slot (``slot_wait_s``, the
    queue, not the work). None without ``wall_total_s``."""
    if data.get("wall_total_s") is None:
        return None
    return round(float(data["wall_total_s"]) - float(data.get("render_wall_s") or 0.0)
                 - float(data.get("slot_wait_s") or 0.0), 2)


def judge_build(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pass rows of one build result (``data`` of the script): pin drift, stretch and rest poke gate; the work
    time (``build_wall_s``, ``work_wall_s`` against ``BUILD_WALL_S`` — over it the Figure tab says "slow"), CPU,
    bake coverage and the views' silhouette IoU (``bake_iou``, bug round 2026-11-20) are reported, never gated
    (Ruling A138; the wall row since 2026-11-18)."""
    rows: List[Dict[str, Any]] = []

    def row(name, value, limit, ok, gate=True):
        rows.append({"check": name, "value": value, "limit": limit, "ok": bool(ok), "gate": gate})

    drape = data.get("drape") or {}
    wall = work_wall_s(data)
    if wall is not None:
        # reported, never a gate (2026-11-18); the limit shown is the fabric's (A204 ``wall_limit``)
        limit = float(data.get("wall_limit_s") or BUILD_WALL_S)
        row("build_wall_s", wall, limit, wall <= limit, gate=False)
    if "cpu_s" in drape:
        row("drape_cpu_s", drape["cpu_s"], THRESHOLDS["drape_cpu_s"], drape["cpu_s"] < THRESHOLDS["drape_cpu_s"],
            gate=False)
    if "pin_drift_mm" in drape:
        row("pin_drift_mm", drape["pin_drift_mm"], THRESHOLDS["pin_drift_mm"],
            drape["pin_drift_mm"] < THRESHOLDS["pin_drift_mm"])
    if "stretch_max" in drape:
        row("stretch_max", drape["stretch_max"], THRESHOLDS["stretch_max"],
            drape["stretch_max"] < THRESHOLDS["stretch_max"])
    for pose, m in (data.get("draped") or {}).items():
        row(f"poke_share[{pose}]", m["poke_share"], THRESHOLDS["poke_share"],
            m["poke_share"] < THRESHOLDS["poke_share"], gate=pose == "rest")
    bake = data.get("bake") or {}
    if "coverage" in bake:
        row("bake_coverage", bake["coverage"], THRESHOLDS["bake_coverage"],
            bake["coverage"] > THRESHOLDS["bake_coverage"], gate=False)
    iou = _bake_iou(bake)
    if iou is not None:
        row("bake_iou", iou, THRESHOLDS["bake_iou"], iou >= THRESHOLDS["bake_iou"], gate=False)
    return rows


def _bake_iou(bake: Dict[str, Any]) -> Optional[float]:
    """The registered silhouette IoU of ``metrics.bake``. A drape baked before the bug round 2026-11-20 stored the
    arm-pose search scores under ``iou`` as ``{deg: score}`` — no registered IoU, so None."""
    iou = bake.get("iou")
    return float(iou) if isinstance(iou, (int, float)) and not isinstance(iou, bool) else None


#: The Figure row's words for a wanted cut texture the figure cannot use (``texture_warning``; English, the React
#: client puts them through ``t()``).
CUT_STALE_TEXT = "Texture from cut is out of date — make it again in the piece dialog (Texture tab)"
CUT_OPTION_TEXT = ("The sleeve option of the texture from cut changed — use the answer again in the piece dialog "
                   "(Texture tab, CPU, 0 hub jobs)")
CUT_REJECTED_TEXT = "Texture from cut was rejected: {reason}"
CUT_FAILED_TEXT = "Texture from cut failed: {reason}"
CUT_DRAPE_BEHIND_TEXT = ("Texture from cut is made for a newer cut than this drape — the next Build drapes the new "
                         "cut (CPU, 0 hub jobs)")
#: A drape that no Build re-drapes for the cut (``cut_info`` "drape_other"): laid out of shrunk / dropped own-mesh
#: colliders, or made before drapes recorded their cut.
CUT_DRAPE_OTHER_TEXT = ("Texture from cut does not fit this drape — it was laid out of other layers under it than "
                        "the cut, or before the cut was recorded, so its pattern pieces differ")
#: ``drape_state``'s reason for a drape of another cut than the piece's current one (``cut_behind``).
CUT_REDRAPE = "The pattern was cut anew — the next Build drapes it again (CPU, 0 hub jobs)"


def texture_warning(bake: Optional[Dict[str, Any]],
                    cut: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The Figure row's texture warning of a drape's ``metrics.bake`` (``TEXTURE_WARN``): ``{coverage, iou,
    low_coverage, low_iou}`` when either is under its mark, else None. A drape baked before the bug round
    2026-11-20 has no registered ``iou`` (absent, or the old ``{deg: score}`` map) — its coverage alone decides.

    ``cut`` is the piece's ``cut_info``: while the cut atlas is in use the projection bake is not what the figure
    shows, so its marks warn of nothing (None). A WANTED cut texture that is stale, rejected or failed adds
    ``cut = {state, reason, text}`` (the projection is shown meanwhile); "missing" (nothing made yet) and "off" are
    no warning — the row says those as a plain line."""
    cut = cut or {}
    if cut.get("texture") == "cut":
        return None
    bake = bake or {}
    cov, iou = bake.get("coverage"), _bake_iou(bake)
    low_cov = cov is not None and float(cov) < TEXTURE_WARN["coverage"]
    low_iou = iou is not None and float(iou) < TEXTURE_WARN["iou"]
    state = cut.get("cut_state")
    texts = {"stale": CUT_STALE_TEXT, "option": CUT_OPTION_TEXT, "rejected": CUT_REJECTED_TEXT,
             "failed": CUT_FAILED_TEXT, "drape_behind": CUT_DRAPE_BEHIND_TEXT, "drape_other": CUT_DRAPE_OTHER_TEXT}
    cut_warning = None
    if state in texts:
        reason = str(cut.get("reason") or "")
        cut_warning = {"state": state, "reason": reason, "text": texts[state].format(reason=reason or "no reason")}
    if not (low_cov or low_iou or cut_warning):
        return None
    out: Dict[str, Any] = {"coverage": cov, "iou": iou, "low_coverage": low_cov, "low_iou": low_iou}
    if cut_warning:
        out["cut"] = cut_warning
    return out


def cut_info(character_name: str, item_id: str, record: Optional[Dict[str, Any]], *,
             item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Which texture a template piece's drape ``record`` is shown with (no image bytes read):
    ``{texture ("cut" / "projection"), cut_state, reason, csig, metrics, px_per_cm}``.

    - "ready" (``texture`` "cut"): the item's ``texture`` param is "cut" and a ready cut record exists for
      ``garment_cut_texture.csig(record.islands.sha256, current item picture sha)`` with its atlas on disk;
    - otherwise ``texture`` "projection" and ``cut_state``: "off" (the param is "projection", or the drape has no
      pattern islands — a kind still on the grid UV), "rejected" / "failed" (that csig's record, with its reason),
      "stale" (no record for this csig, but a ready one for an OLDER csig of the item: new islands, a new item
      picture, a new back view, a new prompt or post version — an old atlas is never painted onto new islands),
      "missing" (nothing made yet, or the item has no picture), "option" (a ready atlas composed with another
      ``sleeve_print`` than the item's now — ``garment_cut_texture.set_sleeve_print`` composes it again on the CPU),
      "drape_behind" (cut-first, 2026-11-21: a ready atlas exists for OTHER islands — another cut — made after this
      drape, and the drape's recorded ``cut_sig`` differs from the current cut's: ``cut_behind``, the next Build
      drapes the new cut — ``drape_state`` already calls such a drape not draped, so this is the moment between),
      "drape_other" (the same atlas, but the drape carries no ``cut_sig`` or the current one: laid out of shrunk /
      dropped own-mesh colliders, or made before drapes recorded their cut — no Build re-drapes it for the cut).

    Keyed by the islands sha and never by ``tsig``: a re-drape that only re-rendered a piece-only view keeps the cut,
    and every drape of the same cut writes the same islands bytes (``garment_template_cut``), so an atlas made from
    the cut alone fits each of them and no drape of another cut."""
    from app.core import garment_cut_texture as gct
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id)
    params = params_of(item) or (record or {}).get("params") or {}
    islands = (record or {}).get("islands") or {}
    out: Dict[str, Any] = {"texture": "projection", "cut_state": "off", "reason": "", "csig": None,
                           "metrics": None, "px_per_cm": islands.get("px_per_cm")}
    if not islands.get("sha256") or params.get("texture") != "cut":
        return out
    sig = gct.csig_for(character_name, item_id, str(islands["sha256"]),
                       has_back_panel=gct.has_back_file(templates_dir(character_name) / str(islands.get("file") or ""),
                                                        str(islands["sha256"])))
    if sig is None:
        out.update(cut_state="missing", reason=f"The item {item_id!r} has no picture")
        return out
    out["csig"] = sig
    rec = gct.read_record(character_name, item_id, sig)
    if rec.get("csig") not in (None, sig):
        rec = {}
    if rec:
        out["metrics"] = rec.get("metrics") or None
        out["px_per_cm"] = rec.get("px_per_cm") or out["px_per_cm"]
    state = rec.get("state")
    if state == "ready" and str(rec.get("sleeve_print") or "plain") != str(params.get("sleeve_print") or "plain"):
        out.update(cut_state="option", reason=CUT_OPTION_TEXT)
    elif state == "ready" and gct.atlas_path(character_name, item_id, sig).is_file():
        out.update(texture="cut", cut_state="ready")
    elif state in ("rejected", "failed"):
        out.update(cut_state=state, reason=str(rec.get("reason") or ""))
    elif gct.newer_cut_ready(character_name, item_id, str(islands["sha256"]),
                             str((record or {}).get("created_at") or "")):
        from app.core import garment_template_cut
        recorded = (record or {}).get("cut_sig")
        now = garment_template_cut.cut_key(character_name, item_id, item=item)["sig"] if recorded else None
        if recorded and now and now != recorded:
            out.update(cut_state="drape_behind", reason=CUT_DRAPE_BEHIND_TEXT)
        else:
            out.update(cut_state="drape_other", reason=CUT_DRAPE_OTHER_TEXT)
    elif gct.older_ready(character_name, item_id, sig):
        out.update(cut_state="stale", reason=CUT_STALE_TEXT)
    else:
        out["cut_state"] = "missing"
    return out


def atlas_for(character_name: str, item_id: str, record: Optional[Dict[str, Any]], *,
              item: Optional[Dict[str, Any]] = None) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """``(atlas PNG bytes | None, cut_info)``: the cut atlas the assembly grafts in place of the drape GLB's
    projection image, or None (the projection stays — it is always inside the GLB as the fallback)."""
    info = cut_info(character_name, item_id, record, item=item)
    if info["texture"] != "cut":
        return None, info
    from app.core import garment_cut_texture as gct
    try:
        return gct.atlas_path(character_name, item_id, info["csig"]).read_bytes(), info
    except OSError:
        return None, {**info, "texture": "projection", "cut_state": "missing"}


#: Ruling A141 — skin in YCrCb (also shaded skin: a leg in the shadow of a slit); a garment pixel within
#: SKIN_GROW_PX of skin goes too (the anti-aliased rim between leg and fabric is half skin).
SKIN_CR = (133, 180)
SKIN_CB = (77, 127)
SKIN_MIN_Y = 25
SKIN_GROW_PX = 2


def skin_mask(rgb):
    """Skin-coloured pixels of an (h, w, 3) uint8 array (YCrCb box, see SKIN_CR / SKIN_CB / SKIN_MIN_Y)."""
    import numpy as np
    r, g, b = (rgb[..., k].astype(np.float64) for k in range(3))
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    return ((cr >= SKIN_CR[0]) & (cr <= SKIN_CR[1]) & (cb >= SKIN_CB[0]) & (cb <= SKIN_CB[1])
            & (y >= SKIN_MIN_Y))


#: Bug round 2026-11-20 (Ylva's skirt): a see-through opening of a view — a slit, the gap of a wrap, the inside of
#: a leg opening — is opaque in the cut-out, and the projection painted it onto closed fabric. A pixel is "dark" when
#: its luminance is under OPEN_REL x the piece's median AND at least OPEN_MIN_DROP (0..255) under it: the drop is
#: RELATIVE to the piece, so black fabric (median 10-30) has no dark pixels at all.
OPEN_REL = 0.35
OPEN_MIN_DROP = 40.0
#: A dark region is an opening when it is OPEN_MIN_SHARE .. OPEN_MAX_SHARE of the piece, reaches the hem or the
#: top edge (the piece's outside lies within OPEN_EDGE_PX straight below / above it in at least OPEN_EDGE_COLS
#: columns) and fabric surrounds most of it — at most OPEN_OUTSIDE_SHARE of its rim borders the outside (a slit
#: touches the hem with its base only; a dark band along the top edge borders the outside with its whole length).
OPEN_MIN_SHARE = 0.003
OPEN_MAX_SHARE = 0.25
OPEN_EDGE_PX = 3
OPEN_EDGE_COLS = 2
OPEN_OUTSIDE_SHARE = 0.35
#: Review of the bug round 2026-11-20: an opening TAPERS away from the edge it opens at — a slit or the gap of a wrap
#: is widest at the hem and runs out to a point (Ylva's slit: 36 px wide in the quarter of its rows at the hem, 3 px
#: in the far quarter). A dark detail that merely starts at an edge (a placket, a stripe, a tie, a zip line) keeps its
#: width. A region is an opening only when its mean width (pixels per row) over the OPEN_TAPER_PART of its rows
#: farthest from the edge is at most OPEN_TAPER x that over the same share nearest to it.
OPEN_TAPER = 0.5
OPEN_TAPER_PART = 0.25


def opening_mask(rgba) -> Tuple[Any, Dict[str, Any]]:
    """The see-through openings of a cut-out view (``OPEN_*``): an (h, w) bool mask (row 0 = top, as the file) and
    ``{px, regions}``. The bake leaves these pixels out (``project_bake``), so push-pull fills them with the fabric
    around them; they still count as the piece for the silhouette registration. The size filter runs on the label
    sums before any per-region work, and each region is examined inside its own bounding box (a fine dark print
    makes thousands of labels on a render-sized view)."""
    import numpy as np
    from scipy import ndimage
    rgba = np.asarray(rgba)
    opaque = rgba[..., 3] >= 128
    out = np.zeros(opaque.shape, bool)
    if opaque.sum() < 16:
        return out, {"px": 0, "regions": 0}
    rgb = rgba[..., :3].astype(np.float64)
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    med = float(np.median(lum[opaque]))
    dark = opaque & (lum < OPEN_REL * med) & (med - lum >= OPEN_MIN_DROP)
    labels, count = ndimage.label(dark, structure=np.ones((3, 3), bool))
    if not count:
        return out, {"px": 0, "regions": 0}
    total = float(opaque.sum())
    h, w = opaque.shape
    outside = ~opaque
    sizes = np.asarray(ndimage.sum(dark, labels, range(1, count + 1)), np.float64)
    keep = np.nonzero((sizes / total >= OPEN_MIN_SHARE) & (sizes / total <= OPEN_MAX_SHARE))[0]
    boxes = ndimage.find_objects(labels)
    found = 0
    pad = OPEN_EDGE_PX + 1
    for i in keep:
        sl = boxes[i]
        r0, c0 = max(0, sl[0].start - pad), max(0, sl[1].start - pad)
        r1, c1 = min(h, sl[0].stop + pad), min(w, sl[1].stop + pad)
        reg = labels[r0:r1, c0:c1] == i + 1
        out_l = outside[r0:r1, c0:c1]
        rows, cols = np.nonzero(reg)
        top = bottom = 0
        for c in np.unique(cols):
            rs = rows[cols == c]
            lo_r, hi_r = int(rs.min()), int(rs.max())
            if out_l[hi_r + 1:hi_r + 1 + OPEN_EDGE_PX, c].any() or r0 + hi_r == h - 1:
                bottom += 1
            elif out_l[max(0, lo_r - OPEN_EDGE_PX):lo_r, c].any() or r0 + lo_r == 0:
                top += 1
        if top + bottom < OPEN_EDGE_COLS:
            continue
        rim = reg & ~ndimage.binary_erosion(reg)
        rim_out = rim & ndimage.binary_dilation(out_l)
        if rim_out.sum() > OPEN_OUTSIDE_SHARE * max(1, rim.sum()):
            continue
        width = reg.sum(1)
        width = width[width > 0]
        if bottom >= top:
            width = width[::-1]                    # nearest the edge it opens at (the hem: the last rows) first
        q = max(1, int(round(len(width) * OPEN_TAPER_PART)))
        if width[-q:].mean() > OPEN_TAPER * width[:q].mean():
            continue                               # keeps its width: a dark detail, not an opening
        out[r0:r1, c0:c1] |= reg
        found += 1
    return out, {"px": int(out.sum()), "regions": found}


def open_mask_path(view: Path) -> Path:
    """Where ``prepare_view`` writes a view's opening mask (``opening_mask``; L, 255 = opening)."""
    view = Path(view)
    return view.with_name(f"{view.stem}_open.png")


def prepare_view(src: str, dst: Path, *, garment_only: bool = True, matte: Any = "birefnet",
                 open_mask: Optional[Path] = None) -> Dict[str, Any]:
    """Write ``src`` as RGBA to ``dst`` with the piece cut free — A230: ``garment_matte.cut`` (backdrop colour from the
    border or, for a picture that already has alpha, from its transparent ring; the backdrop-distance key with a
    soft ramp and the BiRefNet-DIS matte in consensus; small holes filled, strays dropped; the rim un-mixed from the
    backdrop and despilled, the outer px and the outside filled with the colour further in). Returns ``{alpha:
    "kept" | "border", share, skin_dropped, mode, bg, ...}`` (share = opaque pixels). The projection registers by
    the alpha silhouette, so the background must go; the footprint is hard alpha, its colours never backdrop.
    ``matte``: ``"birefnet"`` (default), None (the key alone) or a callable (the smokes). ``open_mask`` (the drape's
    views): the see-through openings (``opening_mask``) are written there as L (255 = opening), and the result
    carries ``openings``.

    ``garment_only`` (the item picture — a picture of the piece WORN shows legs): skin (``skin_mask``,
    grown by SKIN_GROW_PX) is cut when it is a minority of the opaque pixels (a skin-coloured piece keeps
    its pixels), then only the largest opaque region stays (stray leg / hand islands) and its rim loses one
    pixel. A cut-out view is the piece alone already and is taken as it is."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    from app.core import garment_matte
    image = Image.open(src).convert("RGBA")
    fn = garment_matte.birefnet_matte if matte == "birefnet" else matte
    px, info = garment_matte.cut(np.asarray(image), matte=fn)
    dropped = 0.0
    if garment_only:
        opaque = px[..., 3] >= 128
        skin = skin_mask(px[..., :3]) & opaque
        share = float(skin.sum() / max(1, opaque.sum()))
        if 0.0 < share < 0.5:
            dropped = share
            grown = ndimage.binary_dilation(skin, iterations=SKIN_GROW_PX)
            opaque &= ~grown
            labels, count = ndimage.label(opaque)
            if count > 1:
                sizes = ndimage.sum(opaque, labels, range(1, count + 1))
                opaque = labels == (int(np.argmax(sizes)) + 1)
            opaque = ndimage.binary_erosion(opaque, iterations=1)
            px[..., :3] = garment_matte.decontaminate(px[..., :3], opaque.astype(float), opaque, info["bg"])
            px[..., 3] = np.where(opaque, 255, 0).astype(np.uint8)
    Image.fromarray(px).save(dst)
    out = {**info, "share": round(float((px[..., 3] >= 128).mean()), 4), "skin_dropped": round(dropped, 4)}
    if open_mask is not None:
        opening, out["openings"] = opening_mask(px)
        Image.fromarray(np.where(opening, 255, 0).astype(np.uint8), "L").save(open_mask)
    return out


def wall_only_failure(result: Dict[str, Any]) -> bool:
    """A204: whether a drape failed on its wall time ALONE (host load, not geometry): Blender returned a GLB and the
    only failed gate row is ``build_wall_s``."""
    bad = [r for r in result.get("rows") or [] if r.get("gate") and not r.get("ok")]
    return bool(result.get("glb")) and len(bad) == 1 and bad[0].get("check") == "build_wall_s"


def run_drape(body_glb: Path, params: Dict[str, Any], sources: Dict[str, str], *, item_id: str,
              out_dir: Path, **kw: Any) -> Dict[str, Any]:
    """``_run_drape_once``; a run that failed only on its wall time (``wall_only_failure``) is run once more — the
    second result stands, and carries ``data.wall_retry`` with the first wall."""
    result = _run_drape_once(body_glb, params, sources, item_id=item_id, out_dir=out_dir, **kw)
    if not wall_only_failure(result):
        return result
    first = next(r["value"] for r in result["rows"] if r["check"] == "build_wall_s")
    logger.info("Template drape %s: wall %s s over the budget only — retrying once (host load)", item_id, first)
    again = _run_drape_once(body_glb, params, sources, item_id=item_id, out_dir=Path(out_dir) / "wall_retry", **kw)
    again.setdefault("data", {})["wall_retry"] = {"first_wall_s": first}
    return again


def _run_drape_once(body_glb: Path, params: Dict[str, Any], sources: Dict[str, str], *, item_id: str,
              out_dir: Path, render: bool = False, poses: Optional[Tuple[str, ...]] = None,
              timeout_s: int = 300, corrective: bool = True,
              lower: Optional[List[Tuple[Path, Any]]] = None,
              live: Optional[Tuple[str, str]] = None,
              lower_offsets: Optional[List[float]] = None, over_sleeves: bool = False) -> Dict[str, Any]:
    """Measure, make the panels and drape on ``body_glb`` (one Blender run; one retry with doubled
    quality when the stretch is above ``RETRY_STRETCH`` or a narrow miss, ``retry_due``; the retry's result is
    judged and carries ``data.retry``). ``lower`` = [(drape GLB, its pose-shape payload)] of the
    lower layers the piece drapes over (colliders, Ruling A142); ``over_sleeves`` one of them has sleeves
    (``panel_spec``). Returns ``{ok, error, data, glb, rows, outcome,
    log_tail}`` — ``ok`` False when Blender failed or a gate row failed (``error`` names it); ``outcome``
    (``app.blender.outcome``) is the Blender run's when it failed, ``REJECTED`` for a failed gate row, ``CRASHED``
    when no GLB came back."""
    import time
    from app.blender import outcome as oc
    from app.blender import runner
    started = time.time()
    _live_stage(live, "measure_body")
    meas = measure_body(Path(body_glb).read_bytes())
    spec = panel_spec(params, meas, over_sleeves=over_sleeves)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_file = out_dir / "progress.json"
    _live_stage(live, "views")
    views = {side: out_dir / f"view_{side}.png" for side in ("front", "back")}
    view_info = {side: prepare_view(sources[side], views[side],
                                    garment_only=sources.get("source") not in ("cutout", "piece_only"),
                                    open_mask=open_mask_path(views[side])) for side in views}
    data: Dict[str, Any] = {}
    res: Dict[str, Any] = {}
    first: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
    slot_wait = 0.0       # the waits for a free Blender slot in ``wall_total_s`` (``work_wall_s`` takes them out)
    for scale in (1.0, 2.0):
        inputs = {"body": Path(body_glb), "front": views["front"], "back": views["back"],
                  "front_open": open_mask_path(views["front"]), "back_open": open_mask_path(views["back"])}
        for i, (path, _payload) in enumerate(lower or []):
            inputs[f"lower_{i}"] = Path(path)
        args = build_args(params, spec, item_id=item_id, render=render, poses=poses, quality_scale=scale,
                          corrective=corrective, lower_shapes=[payload for _p, payload in lower or []],
                          lower_offsets=lower_offsets)
        if live is not None:
            progress_file.unlink(missing_ok=True)
            args["progress_file"] = str(progress_file)
            _live_stage(live, "blender", file=str(progress_file), attempt=1 if scale == 1.0 else 2)
        res = runner.run(SCRIPT, inputs=inputs, params=args,
                         out_dir=Path(out_dir), timeout_s=timeout_s)
        slot_wait += float(res.get("slot_wait_s") or 0.0)
        data = dict(res.get("data") or {})
        if not res.get("ok"):
            if first is not None:          # the retry failed (e.g. its timeout): the first drape is judged
                res, data = first
                data["retry_error"] = str(res.get("error") or "") or "retry failed"
            break
        if scale != 1.0:
            data["retry"] = {"reason": why, "first_stretch_max": (first[1].get("drape") or {}).get("stretch_max")}
            break
        why = retry_due(data.get("drape"))
        if why is None:
            break
        # Ruling A142: a retry doubles the cloth cost; it is only tried when the first run left room for it
        if float(data.get("script_wall_s") or 0.0) - float(data.get("render_wall_s") or 0.0) > wall_limit(params) / 2:
            data["retry_skipped"] = "the first drape took more than half the wall budget"
            break
        first = (res, data)
    data["measure"] = meas
    data["outline"] = spec["outline"]
    data["views"] = {**view_info, "source": sources.get("source", "")}
    data["wall_total_s"] = round(time.time() - started, 2)
    if wall_limit(params) != BUILD_WALL_S:
        data["wall_limit_s"] = wall_limit(params)
    data["render_wall_s"] = float(data.get("render_wall_s") or 0.0)
    data["slot_wait_s"] = round(slot_wait, 2)
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "blender failed"), "data": data, "glb": None,
                "rows": [], "outcome": res.get("outcome") or oc.CRASHED, "log_tail": res.get("log_tail") or ""}
    _live_stage(live, "judge")
    rows = judge_build(data)
    bad = [r for r in rows if r["gate"] and not r["ok"]]
    glb = (res.get("outputs") or {}).get("glb")
    error = "; ".join(f"{r['check']} {r['value']} (limit {r['limit']})" for r in bad)
    return {"ok": not bad and bool(glb), "error": error or ("" if glb else "no GLB written"), "data": data,
            "glb": glb, "rows": rows, "outputs": res.get("outputs") or {},
            "outcome": oc.REJECTED if bad else (oc.OK if glb else oc.CRASHED), "log_tail": ""}


#: A200 fallback: the inward offset of an own-mesh collider in the second attempt (metres, along its normals).
INNER_SHRINK_M = -0.008
#: The gate rows whose failure makes a drape with own-mesh colliders try again with less of them.
FALLBACK_GATES = ("stretch_max", "poke_share")


def _gate_failed(result: Dict[str, Any]) -> bool:
    """Whether ``result`` (``run_drape``) failed a stretch or poke gate (not the wall, not Blender itself)."""
    return any(r.get("gate") and not r.get("ok") and str(r.get("check") or "").startswith(FALLBACK_GATES)
               for r in result.get("rows") or [])


def drape_with_fallback(run: Any, drapes: List[Tuple[Path, Any]],
                        own: List[Tuple[Path, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A200: drape with the own-mesh colliders ``own`` after the template ``drapes``; when that fails a stretch / poke
    gate, once more with them shrunk ``INNER_SHRINK_M`` toward the body, and when that fails too, without them
    (the template drapes only, as before A200 — the assembly still hides the inner piece's faces under the drape).
    ``run(colliders, offsets, sub)`` runs one drape (``sub``: its scratch sub-folder). Returns ``(result,
    {mode: "full" / "shrunk" / "dropped", failed: [{mode, error, stretch_max}]})``."""
    def attempt(mode: str, cols, offsets):
        return run(cols, offsets, mode)
    if not own:
        return attempt("full", drapes, None), {"mode": "full", "failed": []}
    failed: List[Dict[str, Any]] = []
    plans = (("full", drapes + own, [0.0] * len(drapes) + [0.0] * len(own)),
             ("shrunk", drapes + own, [0.0] * len(drapes) + [INNER_SHRINK_M] * len(own)),
             ("dropped", drapes, None))
    result: Dict[str, Any] = {}
    for mode, cols, offsets in plans:
        result = attempt(mode, cols, offsets)
        if result.get("ok") or not _gate_failed(result) or mode == "dropped":
            if failed:
                logger.info("Template drape: own-mesh colliders %s after %s", mode,
                            "; ".join(f"{f['mode']}: {f['error']}" for f in failed))
            return result, {"mode": mode, "failed": failed}
        failed.append({"mode": mode, "error": str(result.get("error") or ""),
                       "stretch_max": ((result.get("data") or {}).get("drape") or {}).get("stretch_max")})
    return result, {"mode": "dropped", "failed": failed}


def build(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
          lower: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
    """Drape one template piece for the character's CURRENT plain body (the Build's ``template``
    step). Writes ``templates/{item}_{tsig}.glb + .json`` (accepted) or the failure record. Returns
    the new ``drape_state``. A ready drape is kept unless ``force``. While it runs, ``live_progress`` reports what
    it does (A172)."""
    from app.core import base_body, figure
    from app.models.character import get_character_dir, get_character_profile
    from app.models.inventory import get_item
    profile = profile if profile is not None else (get_character_profile(character_name) or {})
    base = base_body.current_base(character_name, profile=profile)
    base_sha = base[1] if base else ""
    if lower is None:
        lower = lower_layers(figure.worn_sets(character_name, profile=profile).own, item_id)
    item = get_item(item_id)
    state = drape_state(character_name, item_id, base_sha=base_sha, lower=lower, item=item)
    if state["state"] == "blocked" or (state["state"] == "ready" and not force):
        return state
    sig = state["tsig"]
    sources = texture_sources(character_name, item_id)
    body = get_character_dir(character_name) / "model3d" / f"{base[0]}.glb"
    params = params_of(item)
    key = (character_name, item_id)
    from app.core import cpu_progress
    try:
        with cpu_progress.scope(f"piece:{character_name}:{item_id}"):  # A194: the piece dialog's live line
            _live_stage(key, "waiting")
            return _build_drape(character_name, item_id, key=key, profile=profile, base=base, base_sha=base_sha,
                                lower=lower, item=item, sig=sig, sources=sources, body=body, params=params)
    finally:
        _live_end(key)


def _build_drape(character_name: str, item_id: str, *, key: Tuple[str, str], profile: Dict[str, Any], base,
                 base_sha: str, lower: List[str], item: Optional[Dict[str, Any]], sig: str, sources: Dict[str, str],
                 body: Path, params: Dict[str, Any]) -> Dict[str, Any]:
    """``build``'s drape itself, with its live progress registered under ``key`` (A172)."""
    import shutil
    import tempfile
    from app.core import figure
    from app.core.garment_store import write_record
    from app.core.timeutils import utc_now_iso
    # Ruling A142: the lower template layers first (a jacket drapes over the top's drape); one not drapable is
    # simply not a collider
    colliders = []
    ready = []
    for other, it in collider_pieces(item_id, params["kind"], lower):
        sub = build(character_name, other, profile=profile, lower=_lower_of(other, item_id, lower))
        if sub["state"] == "ready":
            colliders.append((sub["path"], sub["record"].get("pose_shapes")))
            ready.append(it)
    # bug round 2026-11-20: the allowance follows the colliders really handed to the drape (``over_sleeved_layer``);
    # a lower layer that became ready (or failed) just now changes the key's ``ease:over_sleeves`` token, so the key
    # of a piece that can carry it is read again here and the drape is stored under the key it was cut for
    over = over_sleeved_layer(params["kind"], ready)
    if layer_ease(params, True):
        sig = key_for(character_name, item_id, base_sha=base_sha, lower=lower, item=item)[0] or sig
    # A200: the own-mesh pieces under it — their plain-body fit, skinned, no pose shapes
    own = [(fit, None) for _o, fit in own_colliders(character_name, item_id, params["kind"], lower,
                                                    base_sha=base_sha) if fit is not None]
    _live_stage(key, "measure_body")
    from app.blender import outcome as oc
    left_due = ""
    scratch = Path(tempfile.mkdtemp(prefix="av-template-"))
    try:
        # A228: a shaping piece drapes on the plain body shaped under it (``bust_shaping``)
        from app.core import bust_shaping
        body, shaping, shaping_note = bust_shaping.prepare(body, item_id, item, lower, scratch / "shaping")
        result, inner = drape_with_fallback(
            lambda cols, offsets, sub: run_drape(body, params, sources, item_id=item_id, out_dir=scratch / sub,
                                                 lower=cols, live=key, lower_offsets=offsets, over_sleeves=over),
            colliders, own)
        colliders = colliders + (own if inner["mode"] != "dropped" else [])
        # cut-first (2026-11-21): the cut this drape was laid out of (``garment_template_cut.cut_sig``) — only when
        # its colliders were the cut's ("full": an own-mesh collider shrunk or dropped laid the panels out of others)
        cut_sig = None
        if params["kind"] in PATTERN_KINDS and inner["mode"] == "full":
            # ``wait=False``: the sig of the colliders really handed over, also when a lower layer was left due — the
            # layer's drape later makes the current sig differ, and ``cut_behind`` re-drapes this one
            from app.core import garment_template_cut
            cut_sig = garment_template_cut.sig_of(character_name, item_id, params, base_sha=base_sha, lower=lower,
                                                  item=item, wait=False)[0]
        folder = templates_dir(character_name)
        folder.mkdir(parents=True, exist_ok=True)
        record = {"item_id": item_id, "tsig": sig, "params": params, "version": TEMPLATE_VERSION,
                  "base_signature": base[0], "base_model_sha256": base_sha, "lower": lower,
                  "texture": {k: Path(v).name if k != "source" else v for k, v in sources.items()},
                  # the key's texture part (``cut_stand_in``: a cut-textured piece keeps this drape when only
                  # a projection view changes)
                  "texture_sha": texture_sha_of(sources),
                  "colliders": [Path(c[0]).name for c in colliders],
                  **({"inner_collider": inner} if own else {}),
                  "metrics": result["data"], "rows": result["rows"], "created_at": utc_now_iso(),
                  "pose_shapes": (result["data"] or {}).get("pose_shapes"),
                  **({"shaping": shaping} if shaping else {}),
                  **({"shaping_note": shaping_note} if shaping_note else {}),
                  **({"layer_ease": JACKET_SLEEVE_EASE} if layer_ease(params, over) else {}),
                  **({"cut_sig": cut_sig} if cut_sig else {})}
        if result["ok"]:
            target = drape_path(character_name, item_id, sig)
            shutil.move(str(result["glb"]), str(target))
            islands = (result.get("outputs") or {}).get("islands")
            if islands and Path(islands).is_file():
                ipath = islands_path(character_name, item_id, sig)
                shutil.move(str(islands), str(ipath))
                raw = ipath.read_bytes()
                record["islands"] = {"file": ipath.name, "sha256": hashlib.sha256(raw).hexdigest(),
                                     "px_per_cm": json.loads(raw).get("px_per_cm")}
            write_record(target.with_suffix(".json"), {**record, "accepted": True})
            failed = failed_path(character_name, item_id, sig)
            if failed.is_file():
                failed.unlink()
        elif oc.is_retryable(result["outcome"]):
            # A timeout, an interrupted run or no Blender judges nothing: no failure record, the drape stays due.
            left_due = LEFT_DUE.get(result["outcome"], LEFT_DUE[oc.INTERRUPTED])
            logger.warning("Template drape of %s for %s left due (%s): %s", item_id, character_name,
                           result["outcome"], result["error"])
        else:
            write_record(failed_path(character_name, item_id, sig),
                         {**record, "error": result["error"], "outcome": result["outcome"],
                          "log_tail": result["log_tail"]})
            logger.warning("Template drape of %s for %s failed: %s", item_id, character_name, result["error"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    figure.invalidate()
    state = drape_state(character_name, item_id, base_sha=base_sha, lower=lower, item=item)
    if left_due and state["state"] == "missing":
        state = {**state, "reason": left_due, "outcome": result["outcome"],
                 "failure": failure_info({"outcome": result["outcome"], "error": result["error"],
                                          "log_tail": result["log_tail"]})}
    return state


def estimate_s(character_name: str, item_id: str) -> int:
    """The wall seconds a drape of ``item_id`` on ``character_name`` will likely work: the ``work_wall_s`` of its
    newest JUDGED drape record (accepted or refused, any key — new parameters drape in about the same time; a run
    that ended without a verdict has no rows and says nothing), else ``CPU_ESTIMATE_S``. One listing of the
    character's template folder and the records read newest first until one has a time. Never raises."""
    from app.core.garment_store import read_record
    folder = templates_dir(character_name)
    name = re.compile(re.escape(item_id) + r"_[0-9a-f]{12}\.json")
    found = []
    for directory in (folder, folder / "failed"):
        try:
            for path in directory.iterdir():
                if name.fullmatch(path.name):
                    found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _stamp, path in sorted(found, reverse=True):
        record = read_record(path)
        wall = work_wall_s(record.get("metrics") or {}) if record.get("rows") else None
        if wall:
            return max(1, int(round(wall)))
    return CPU_ESTIMATE_S


def clear_failure(character_name: str, item_id: str) -> int:
    """Forget every failed drape of the item (Retry); returns how many records went."""
    folder = templates_dir(character_name) / "failed"
    count = 0
    if folder.is_dir():
        for path in folder.glob(f"{item_id}_*.json"):
            path.unlink()
            count += 1
    return count


def mesh_args(fit_glb: Path, plain_body: Path, kind: str, tag: str, **over: Any) -> Dict[str, Any]:
    """Spike job args for draping an EXISTING generated piece (mode ``mesh`` of ``SPIKE_SCRIPT``)."""
    args = {"mode": "mesh", "tag": tag, "fit_glb": str(fit_glb), "plain_body": str(plain_body),
            "pin": PIN_BY_KIND.get(kind, "shoulders"), "voxel_m": 0.006, "target_faces": 12000,
            "frames": 40, "quality": 6}
    args.update(over)
    return args


def judge(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Spike pass/fail rows for one drape result (``data`` of the spike script)."""
    rows: List[Dict[str, Any]] = []

    def row(name, value, limit, ok):
        rows.append({"check": name, "value": value, "limit": limit, "ok": bool(ok)})

    drape = result.get("drape") or {}
    if "cpu_s" in drape:
        row("drape_cpu_s", drape["cpu_s"], THRESHOLDS["drape_cpu_s"], drape["cpu_s"] < THRESHOLDS["drape_cpu_s"])
    if "pin_drift_mm" in drape:
        row("pin_drift_mm", drape["pin_drift_mm"], THRESHOLDS["pin_drift_mm"],
            drape["pin_drift_mm"] < THRESHOLDS["pin_drift_mm"])
    if "stretch_max" in drape:
        row("stretch_max", drape["stretch_max"], THRESHOLDS["stretch_max"],
            drape["stretch_max"] < THRESHOLDS["stretch_max"])
    for pose, m in (result.get("draped") or {}).items():
        row(f"poke_share[{pose}]", m["poke_share"], THRESHOLDS["poke_share"],
            m["poke_share"] < THRESHOLDS["poke_share"])
    bake = result.get("bake") or {}
    if "coverage" in bake:
        row("bake_coverage", bake["coverage"], THRESHOLDS["bake_coverage"],
            bake["coverage"] > THRESHOLDS["bake_coverage"])
    return rows
