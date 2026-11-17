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
model sha256, the texture source sha256 and the other worn mesh pieces (the
lower layers — they become colliders in P3; recorded now so the key does not
change then). A failed drape is recorded in ``templates/failed/`` and the piece
is left off with its reason until Retry. 0 hub jobs; the only paid call is the
one parameter suggestion.

Kinds: ``skirt`` and ``dress`` are built in P1 (``BUILT_KINDS``); ``top``,
``jacket`` and ``trousers`` are valid parameters already (the LLM may name
them) and are left off with ``KIND_NOT_BUILT`` until their panels exist.
"""
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
TEMPLATE_VERSION = 5
#: The LLM task (``llm_tasks.TASK_TYPES``; unrouted → ``image_recognition``) and its template.
TASK = "garment_template_params"
#: Completion cap for the JSON answer.
MAX_TOKENS = 400

KINDS = ("skirt", "dress", "top", "jacket", "trousers")
BUILT_KINDS = ("skirt", "dress", "top", "jacket")
#: Kinds with a bodice over the shoulders (Ruling A142): built as a tube from the hem to the shoulder line, a yoke
#: over the shoulders up to the neckline, armholes and sleeves (``bodice_spec``). A dress is one of them unless it is
#: strapless.
UPPER_KINDS = ("top", "jacket")
#: The layer rank of a kind: a piece drapes over the READY template drapes of a lower rank (Ruling A142: a jacket
#: over a top or a dress; the lower drape is a collider of the cloth run).
LAYER_RANK = {"skirt": 1, "trousers": 1, "dress": 1, "top": 1, "jacket": 2}
WAIST_HEIGHTS = ("high", "natural", "low")
SLIT_SIDES = ("none", "left", "right", "front", "back")
SLEEVES = ("none", "cap", "short", "elbow", "long")
#: Sleeve length as a share of the arm (shoulder joint to wrist joint): a cap sleeve just covers the shoulder
#: joint, a short one reaches a third down the upper arm, elbow = the elbow joint (half the arm on the reference
#: body: 0.249 m upper arm + 0.245 m forearm), long = to the wrist.
SLEEVE_SHARE = {"none": 0.0, "cap": 0.12, "short": 0.3, "elbow": 0.52, "long": 0.97}
NECKLINES = ("crew", "v", "scoop", "boat")
#: The neckline's depth at the front centre below the jugular notch (``front_y`` = the shoulder-joint height, Ruling
#: A144) when ``neck_depth_m`` is 0 (metres; a crew neck sits ~1 cm under the notch).
NECK_DEPTH = {"crew": 0.01, "v": 0.12, "scoop": 0.08, "boat": 0.0}
SHOULDERS = ("strapless", "straps", "covered")
FRONTS = ("closed", "open")
COLLARS = ("none", "stand", "lapel")
#: Fabric presets of the cloth run (Blender cloth settings). Stiff = holds a
#: shape (denim, wool), medium = cotton, flowing = silk / chiffon / jersey.
FABRICS: Dict[str, Dict[str, float]] = {
    "stiff": {"bending": 2.0, "mass": 0.4, "quality": 6, "shrink": 0.0},
    "medium": {"bending": 0.3, "mass": 0.3, "quality": 6, "shrink": 0.0},
    "flowing": {"bending": 0.05, "mass": 0.2, "quality": 7, "shrink": 0.0},
}
#: ``{field: (type, choices | (min, max), default)}`` — the one parameter schema (LLM answer,
#: the dialog and ``validate_params``).
PARAM_SPEC: Dict[str, Tuple[str, Any, Any]] = {
    "kind": ("choice", KINDS, "skirt"),
    "length_m": ("number", (0.15, 1.2), 0.5),       # skirt / dress: from the waist down; top / jacket: from the shoulder line down
    "flare": ("number", (0.0, 1.0), 0.3),           # 0 pencil .. 1 near-circle hem (skirt part)
    "waist_height": ("choice", WAIST_HEIGHTS, "natural"),
    "slit": ("choice", SLIT_SIDES, "none"),
    "slit_m": ("number", (0.0, 0.6), 0.0),           # slit depth from the hem up
    "shoulders": ("choice", SHOULDERS, "strapless"),  # dress only; a top / jacket is always covered
    "sleeves": ("choice", SLEEVES, "none"),
    "sleeve_fit": ("number", (0.0, 1.0), 0.3),       # 0 tight .. 1 loose
    "fit": ("number", (0.0, 1.0), 0.3),              # bodice ease: 0 tight .. 1 loose
    "neckline": ("choice", NECKLINES, "crew"),
    "neck_depth_m": ("number", (0.0, 0.35), 0.0),    # 0 = the neckline's usual depth (NECK_DEPTH)
    "front": ("choice", FRONTS, "closed"),           # jacket: open front
    "collar": ("choice", COLLARS, "none"),           # jacket
    "fabric": ("choice", tuple(FABRICS), "medium"),
}
#: The fields that mean something per kind (the dialog shows these; ``validate_params`` resets the others to their
#: defaults so a stale field never changes the drape key).
KIND_FIELDS: Dict[str, Tuple[str, ...]] = {
    "skirt": ("kind", "fabric", "length_m", "flare", "waist_height", "slit", "slit_m"),
    "trousers": ("kind", "fabric", "length_m", "waist_height"),
    "dress": ("kind", "fabric", "length_m", "flare", "waist_height", "slit", "slit_m", "shoulders", "sleeves",
              "sleeve_fit", "fit", "neckline", "neck_depth_m"),
    "top": ("kind", "fabric", "length_m", "fit", "sleeves", "sleeve_fit", "neckline", "neck_depth_m"),
    "jacket": ("kind", "fabric", "length_m", "fit", "sleeves", "sleeve_fit", "neckline", "neck_depth_m", "front",
               "collar"),
}

#: Spec section 8 pass marks (hand-derived in ``scripts/smoke_garment_template_spike.py``).
THRESHOLDS = {
    "drape_cpu_s": 60.0,          # spike: CPU seconds of the cloth run (all threads summed)
    "poke_share": 0.005,          # body vertices poking through, per pose
    "pin_drift_mm": 5.0,          # largest displacement of a pinned vertex
    "stretch_max": 1.3,           # longest edge / its pre-drape length, after the drape
    "bake_coverage": 0.85,        # template texels that received a view colour
}
#: P1 gates on WALL time (Ruling A138: a Build is waited for in wall seconds; the spike's CPU sum
#: counts every Blender thread). Same 60 s budget, hand-derived in ``scripts/smoke_garment_template.py``.
BUILD_WALL_S = 60.0
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
#: Ruling A142 wall budget (60 s per piece): a bodice drapes BODICE_FRAMES frames, an arm shape ARM_SHAPE_FRAMES (the
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
    """A top, a jacket, or a dress with straps or a covered bodice (Ruling A142)."""
    return params["kind"] in UPPER_KINDS or (params["kind"] == "dress" and params["shoulders"] != "strapless")


def has_sleeves(params: Dict[str, Any]) -> bool:
    return has_bodice(params) and params["shoulders"] == "covered" and params["sleeves"] != "none"


def shape_groups(params: Dict[str, Any], long_top: bool = False) -> List[Dict[str, Any]]:
    """The pose-shape groups of a piece (Rulings A141 / A142): skirts and dresses get the leg group (sit, kneel); a
    piece with a bodice gets the two arm groups (``ARM_SHAPE_POSES``; a dress only ``DRESS_ARM_SHAPE_POSES``); a top
    or jacket whose hem reaches below the hip joints (``long_top``) also the sit shape (its hem lies on the lap)."""
    groups: List[Dict[str, Any]] = []
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


def measured_poses(params: Dict[str, Any]) -> Tuple[str, ...]:
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

# Pin rings by piece kind (where the cloth hangs from).
PIN_BY_KIND = {"skirt": "waist", "trousers": "waist", "top": "shoulders", "jacket": "shoulders",
               "dress": "shoulders"}

# --- reasons (Ruling A119: a piece not ready is left off, with its reason) -----------------------
NEEDS_PARAMS = "Needs its template parameters — open Edit parameters (1 LLM call to suggest them)"
NOT_DRAPED = "Not draped yet — Build drapes it (CPU, 0 hub jobs)"
KIND_NOT_BUILT = "Template kind '{kind}' is not built yet (skirts, dresses, tops and jackets are) — choose another mode"
DRAPE_FAILED = "Drape failed: {error} — Retry in the Figure tab"
NO_BASE = "No plain body model yet — build the plain body first"


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
    for key in PARAM_SPEC:
        if key not in KIND_FIELDS.get(kind, tuple(PARAM_SPEC)):
            params[key] = PARAM_SPEC[key][2]
    if kind in UPPER_KINDS:
        params["shoulders"] = "covered"
    if kind == "dress" and params["shoulders"] != "covered":
        params["sleeves"] = "none"
    if params["sleeves"] == "none":
        params["sleeve_fit"] = PARAM_SPEC["sleeve_fit"][2]
    if params["slit"] == "none":
        params["slit_m"] = 0.0
    elif params["slit_m"] <= 0.0:
        params["slit_m"] = round(min(0.25, params["length_m"] * 0.4), 3)
    params["slit_m"] = round(min(params["slit_m"], params["length_m"] * 0.8), 3)
    return params, errors


#: A172: the starting values of a kind that differ from ``PARAM_SPEC``'s (those are a skirt's) — what the dialog
#: shows for a piece with no stored parameters and what a kind change resets to. Lengths are measured as in
#: ``PARAM_SPEC`` (top / jacket from the shoulder line down: 0.6 m ends at the hip on the 1.70 m reference body).
KIND_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "skirt": {},
    "trousers": {"length_m": 1.0},
    "dress": {"length_m": 0.6, "shoulders": "straps"},
    "top": {"length_m": 0.6, "sleeves": "short", "fit": 0.4},
    "jacket": {"length_m": 0.7, "sleeves": "long", "fit": 0.5, "collar": "lapel", "front": "open"},
}
_TROUSER_WORDS = re.compile(r"\b(trousers?|pants|jeans|shorts|leggings|slacks|chinos)\b", re.IGNORECASE)
_DRESS_WORDS = re.compile(r"\b(dress|gown|sundress|frock)\b", re.IGNORECASE)
_JACKET_WORDS = re.compile(r"\b(jacket|blazer|coat|cardigan|hoodie|parka)\b", re.IGNORECASE)


def default_kind(item: Optional[Dict[str, Any]]) -> str:
    """A172: the template kind an outfit piece most likely is, from its slots, then its name and prompt text — the
    starting kind of the parameter dialog when nothing is stored (Suggest and Save still decide). ``outer`` →
    jacket; ``top`` with ``bottom`` → dress; ``top`` → top (a dress / jacket word wins); ``bottom`` → trousers for a
    trouser word, else skirt (a dress word → dress); nothing that fits → skirt (``PARAM_SPEC``'s default)."""
    item = item if isinstance(item, dict) else {}
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    slots = {str(x) for x in piece.get("slots") or []}
    text = f"{item.get('name') or ''} {item.get('prompt_fragment') or ''}"
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
    from app.models.inventory import get_item, update_item
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


def outline(params: Dict[str, Any], meas: Dict[str, float]) -> Dict[str, Any]:
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
        return _bodice_outline(params, meas, waist_y, waist_c, hem_c)
    knots = _skirt_knots(meas, waist_y, length, hem_c, waist_c)
    if params["kind"] == "dress":
        bodice = max(0.08, meas["band_y"] - waist_y)
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
                    hem_c: float) -> Dict[str, Any]:
    """The side profile of a piece with a bodice (Ruling A142): from the hem up the body's own girth with the ease
    (``BODICE_EASE``; a dress's skirt part follows the skirt profile ``_skirt_knots`` below its waist line, read at
    this 2 cm grid) to the shoulder line
    ``top_y`` = shoulder joints + ``SHOULDER_TOP_M``."""
    import numpy as np
    if "shoulder_y" not in meas:
        raise ValueError("the body has no arm / neck joints to fit a bodice to")
    top_y = meas["shoulder_y"] + SHOULDER_TOP_M
    ease = 1.0 + BODICE_EASE[0] + BODICE_EASE[1] * params["fit"] + (JACKET_EASE if params["kind"] == "jacket" else 0)
    skirt_h: List[float] = []
    skirt_c: List[float] = []
    if params["kind"] == "dress":
        hem_y = waist_y - params["length_m"]
        # the skirt part: the skirt's own profile (never narrower than the body), read at this grid
        skirt = _skirt_knots(meas, waist_y, waist_y - hem_y, hem_c, waist_c)
        skirt_h, skirt_c = [h for h, _c in skirt], [c for _h, c in skirt]
    else:
        hem_y = max(meas["floor_y"] + 0.2, top_y - params["length_m"])
    knots = []
    for y in np.arange(hem_y, top_y - 1e-6, 0.02):
        y = float(y)
        if params["kind"] == "dress" and y <= waist_y:
            c = float(np.interp(y - hem_y, skirt_h, skirt_c))
        else:
            c = _torso_girth(meas, y) * ease + EASE_M
        knots.append((round(y - hem_y, 4), round(c, 4)))
    knots.append((round(top_y - hem_y, 4), round(_torso_girth(meas, top_y) * ease + EASE_M, 4)))
    return {"knots": knots, "top_y": round(top_y, 4), "waist_y": round(waist_y, 4), "length": knots[-1][0]}


def bodice_spec(params: Dict[str, Any], meas: Dict[str, Any]) -> Dict[str, Any]:
    """What the Blender builder needs beyond the torso rows for a piece with a bodice (Ruling A142), glTF Y-up
    metres: armhole ``band_y`` (the chest band under the arms) to ``top_y``; the neck opening ``neck_r`` (radius
    round the neck joint), ``neckline`` and its front ``depth_m`` below the neck base; ``shoulders`` with the strap
    centre ``strap_x`` / ``strap_w``; ``pin_half_x`` / ``pin_band_m``; ``sleeve`` {len_m, rings: [[metres from the
    shoulder joint along the arm, circumference]]} (None without sleeves); ``front_open``; ``collar``."""
    import numpy as np
    shape = outline(params, meas)
    neck_r = meas["neck_c"] / (2 * math.pi) + NECK_CLEAR_M
    half_sh = meas["shoulder_w"] / 2.0
    neckline = params["neckline"]
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
        ease = 1.0 + SLEEVE_EASE[0] + SLEEVE_EASE[1] * params["sleeve_fit"]
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
            "strap_x": round(0.5 * (neck_r + PIN_SHARE * half_sh), 4), "strap_w": STRAP_W_M,
            "pin_half_x": round(PIN_SHARE * half_sh, 4), "pin_band_m": PIN_BAND_M, "sleeve": sleeve,
            "front_open": front_open, "collar": collar, "joints": meas.get("joints") or {}}


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


def panel_spec(params: Dict[str, Any], meas: Dict[str, float]) -> Dict[str, Any]:
    """The pattern of a built kind as two pygarment panels (front, back; each half the
    circumference), sampled to quad grids: ``{rows, cols, row_y (Y-up world height per row, row 0 =
    the pinned top), panels: [{name, grid_m: rows x cols x 2}], pygarment: {front, back}}``.
    ValueError for a kind not built yet."""
    import numpy as np
    from app.third_party.pygarment.garmentcode.edge import Edge
    from app.third_party.pygarment.garmentcode.edge_factory import CurveEdgeFactory
    from app.third_party.pygarment.garmentcode.panel import Panel
    if params["kind"] not in BUILT_KINDS:
        raise ValueError(KIND_NOT_BUILT.format(kind=params["kind"]))
    shape = outline(params, meas)
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
    if has_bodice(params):
        out["bodice"] = bodice_spec(params, meas)
        if out["bodice"]["sleeve"]:
            specs["sleeve"] = _sleeve_panel(out["bodice"]["sleeve"])
    return out


# --- cache ----------------------------------------------------------------------

def _md5(payload: Any) -> str:
    return hashlib.md5(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def tsig(params: Dict[str, Any], *, base_sha: str, texture_sha: str, lower: List[str]) -> str:
    """The cache key of one drape (module docstring)."""
    return _md5({"params": params, "version": TEMPLATE_VERSION, "base": base_sha, "texture": texture_sha,
                 "lower": sorted(lower)})


def templates_dir(character_name: str) -> Path:
    from app.core.garment_store import garments_dir
    return garments_dir(character_name) / "templates"


def drape_path(character_name: str, item_id: str, sig: str) -> Path:
    return templates_dir(character_name) / f"{item_id}_{sig}.glb"


def failed_path(character_name: str, item_id: str, sig: str) -> Path:
    return templates_dir(character_name) / "failed" / f"{item_id}_{sig}.json"


def _file_sha(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def texture_sources(character_name: str, item_id: str) -> Dict[str, str]:
    """``{front, back, source}``: the piece's newest cut-out (piece-only) views from the garment store
    (``images/{item}_{fsig}_cutout_{front,back}.png``) whenever ANY exists — a missing side takes the other
    side's view (Ruling A141: the cut-outs are always preferred) —, else its item picture for both sides
    (``source`` "item_image"; ``run_drape`` masks it to the garment). {} without any picture."""
    from app.core.garment_store import garments_dir
    from app.models.inventory import get_item_image_path
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
    model's ``mesh_items.intended``) — the lower layers in the cache key (module docstring)."""
    return sorted({str(i) for i in (mesh_ids or ())} - {item_id})


def collider_pieces(item_id: str, kind: str, lower: List[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """Ruling A142 layering: the other worn TEMPLATE pieces of a lower layer rank than ``kind`` — ``[(item id, item)]``
    in id order. A jacket drapes over these (their drapes are colliders, their keys part of its key)."""
    from app.core import garment_set
    from app.models.inventory import get_item
    rank = LAYER_RANK.get(kind, 1)
    out = []
    for other in sorted(set(lower) - {item_id}):
        it = get_item(other)
        if garment_set.mesh_mode_of(it) != garment_set.TEMPLATE:
            continue
        params = params_of(it)
        if params and params["kind"] in BUILT_KINDS and LAYER_RANK.get(params["kind"], 1) < rank:
            out.append((other, it))
    return out


def _lower_of(other: str, item_id: str, lower: List[str]) -> List[str]:
    """The lower-layer list of the collider piece ``other`` within the same worn set."""
    return sorted((set(lower) | {item_id}) - {other})


def key_for(character_name: str, item_id: str, *, base_sha: str, lower: List[str],
            item: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """``(tsig, reason, texture sources)`` of a template piece: tsig None with the left-off
    reason when it cannot be draped (no parameters, a kind not built, no base, no picture). A piece worn over
    lower template layers (``collider_pieces``) folds their keys into its own: a changed top re-drapes the jacket."""
    from app.models.inventory import get_item
    item = item if item is not None else get_item(item_id)
    params = params_of(item)
    if params is None:
        return None, NEEDS_PARAMS, {}
    if params["kind"] not in BUILT_KINDS:
        return None, KIND_NOT_BUILT.format(kind=params["kind"]), {}
    if not base_sha:
        return None, NO_BASE, {}
    sources = texture_sources(character_name, item_id)
    if not sources:
        return None, NEEDS_PARAMS.replace("parameters", "picture"), {}
    tex = _md5([_file_sha(sources["front"]), _file_sha(sources["back"])])
    under = []
    for other, it in collider_pieces(item_id, params["kind"], lower):
        sub, _r, _s = key_for(character_name, other, base_sha=base_sha, lower=_lower_of(other, item_id, lower),
                              item=it)
        under.append(f"{other}:{sub or '-'}")
    return tsig(params, base_sha=base_sha, texture_sha=tex, lower=lower + under), None, sources


def drape_state(character_name: str, item_id: str, *, base_sha: str, lower: List[str],
                item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{state, reason, tsig, path, record}`` — ``ready`` (the drape GLB of the current key exists
    and its record passed), ``failed`` (the current key failed; reason = ``DRAPE_FAILED``),
    ``missing`` (``NOT_DRAPED``) or ``blocked`` (no key: reason from ``key_for``). Read-only."""
    from app.core.garment_store import read_record
    sig, reason, _sources = key_for(character_name, item_id, base_sha=base_sha, lower=lower, item=item)
    if sig is None:
        return {"state": "blocked", "reason": reason, "tsig": None, "path": None, "record": {}}
    path = drape_path(character_name, item_id, sig)
    record = read_record(path.with_suffix(".json"))
    if path.is_file() and record.get("accepted") is True:
        return {"state": "ready", "reason": "", "tsig": sig, "path": path, "record": record}
    failed = read_record(failed_path(character_name, item_id, sig))
    if failed:
        return {"state": "failed", "reason": DRAPE_FAILED.format(error=failed.get("error") or "?"), "tsig": sig,
                "path": None, "record": failed}
    return {"state": "missing", "reason": NOT_DRAPED, "tsig": sig, "path": None, "record": {}}


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


def _live_stage(key: Optional[Tuple[str, str]], stage: str, **fields: Any) -> None:
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
    ``{state ("ready" / "missing" / "failed" / "blocked" / "running"), reason, built_at, error, worn, steps}`` —
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
         "detail": {"cutout": "the piece-only cut-out views", "item_image": "the item picture"}.get(
             sources.get("source", ""), "") if sources else "No picture of the piece yet", "numbers": {}},
        {"id": "drape", "label": "Drape (CPU)",
         "status": {"ready": "done", "failed": "failed", "blocked": "skipped"}.get(state, "due"),
         "detail": (live["label"] if live else WAITING_FOR_STEP) if state == "running" else drape["reason"] or "",
         "numbers": {k: v for k, v in (("wall_s", metrics.get("wall_total_s")),
                                       ("stretch_max", (metrics.get("drape") or {}).get("stretch_max")),
                                       ("coverage", (metrics.get("bake") or {}).get("coverage"))) if v is not None}},
    ]
    return {"state": state, "reason": drape["reason"], "built_at": record.get("created_at") or "",
            "error": str(record.get("error") or "") if drape["state"] == "failed" else "", "worn": worn, "steps": steps,
            "live": live if state == "running" else None}


# --- the drape run ----------------------------------------------------------------

def build_args(params: Dict[str, Any], spec: Dict[str, Any], *, item_id: str, render: bool = False,
               poses: Optional[Tuple[str, ...]] = None, quality_scale: float = 1.0,
               corrective: bool = True, lower_shapes: Optional[List[Any]] = None) -> Dict[str, Any]:
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
            "frames": BODICE_FRAMES if has_bodice(params) else 50, "thickness": 0.004,
            "smooth_weights": bool(corrective), "shape_groups": groups,
            "shape_poses": [p for g in groups if g["name"] == "legs" for p in g["poses"]],
            "lower_shapes": list(lower_shapes or [])}


def judge_build(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pass rows of one build result (``data`` of the script): wall time (the gate), pin drift,
    stretch, rest poke and bake coverage — CPU is reported, never gated (Ruling A138)."""
    rows: List[Dict[str, Any]] = []

    def row(name, value, limit, ok, gate=True):
        rows.append({"check": name, "value": value, "limit": limit, "ok": bool(ok), "gate": gate})

    drape = data.get("drape") or {}
    if "wall_total_s" in data:
        # a Build never renders; the proof runs' sheet renders are taken out (Ruling A142)
        wall = round(data["wall_total_s"] - float(data.get("render_wall_s") or 0.0), 2)
        row("build_wall_s", wall, BUILD_WALL_S, wall <= BUILD_WALL_S)
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
    return rows


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


def prepare_view(src: str, dst: Path, *, tolerance: int = 24, garment_only: bool = True) -> Dict[str, Any]:
    """Write ``src`` as RGBA to ``dst`` with the piece cut free: an image that already has a
    transparent background (a cut-out view) keeps its alpha; an opaque one (an item picture on a
    plain background) loses every border-connected pixel within ``tolerance`` (max channel difference)
    of the median border colour. Returns ``{alpha: "kept" | "border", share, skin_dropped}`` (share =
    opaque pixels). The projection registers by the alpha bounding box, so the background must go.

    ``garment_only`` (the item picture — a picture of the piece WORN shows legs): skin (``skin_mask``,
    grown by SKIN_GROW_PX) is cut when it is a minority of the opaque pixels (a skin-coloured piece keeps
    its pixels), then only the largest opaque region stays (stray leg / hand islands) and its rim loses one
    pixel. A cut-out view is the piece alone already and is taken as it is."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    image = Image.open(src).convert("RGBA")
    px = np.asarray(image).copy()
    alpha = px[..., 3]
    if (alpha < 128).mean() > 0.02:
        mode = "kept"
    else:
        rgb = px[..., :3].astype(np.int32)
        border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        bg = np.median(border, axis=0)
        near = np.abs(rgb - bg).max(axis=2) <= tolerance
        labels, _n = ndimage.label(near)
        edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        background = np.isin(labels, edge[edge > 0])
        px[..., 3] = np.where(background, 0, 255).astype(np.uint8)
        mode = "border"
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
            px[..., 3] = np.where(opaque, 255, 0).astype(np.uint8)
    Image.fromarray(px).save(dst)
    return {"alpha": mode, "share": round(float((px[..., 3] >= 128).mean()), 4),
            "skin_dropped": round(dropped, 4)}


def run_drape(body_glb: Path, params: Dict[str, Any], sources: Dict[str, str], *, item_id: str,
              out_dir: Path, render: bool = False, poses: Optional[Tuple[str, ...]] = None,
              timeout_s: int = 300, corrective: bool = True,
              lower: Optional[List[Tuple[Path, Any]]] = None,
              live: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """Measure, make the panels and drape on ``body_glb`` (one Blender run; one retry with doubled
    quality when the stretch is above ``RETRY_STRETCH``). ``lower`` = [(drape GLB, its pose-shape payload)] of the
    lower layers the piece drapes over (colliders, Ruling A142). Returns ``{ok, error, data, glb, rows}`` —
    ``ok`` False when Blender failed or a gate row failed (``error`` names it)."""
    import time
    from app.blender import runner
    started = time.time()
    _live_stage(live, "measure_body")
    meas = measure_body(Path(body_glb).read_bytes())
    spec = panel_spec(params, meas)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_file = out_dir / "progress.json"
    _live_stage(live, "views")
    views = {side: out_dir / f"view_{side}.png" for side in ("front", "back")}
    view_info = {side: prepare_view(sources[side], views[side],
                                    garment_only=sources.get("source") != "cutout") for side in views}
    data: Dict[str, Any] = {}
    res: Dict[str, Any] = {}
    first: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None
    for scale in (1.0, 2.0):
        inputs = {"body": Path(body_glb), "front": views["front"], "back": views["back"]}
        for i, (path, _payload) in enumerate(lower or []):
            inputs[f"lower_{i}"] = Path(path)
        args = build_args(params, spec, item_id=item_id, render=render, poses=poses, quality_scale=scale,
                          corrective=corrective, lower_shapes=[payload for _p, payload in lower or []])
        if live is not None:
            progress_file.unlink(missing_ok=True)
            args["progress_file"] = str(progress_file)
            _live_stage(live, "blender", file=str(progress_file), attempt=1 if scale == 1.0 else 2)
        res = runner.run(SCRIPT, inputs=inputs, params=args,
                         out_dir=Path(out_dir), timeout_s=timeout_s)
        data = dict(res.get("data") or {})
        if not res.get("ok"):
            if first is not None:          # the retry failed (e.g. its timeout): the first drape is judged
                res, data = first
                data["retry_error"] = str(res.get("error") or "") or "retry failed"
            break
        if (data.get("drape") or {}).get("stretch_max", 0) <= RETRY_STRETCH:
            break
        # Ruling A142: a retry doubles the cloth cost; it is only tried when the first run left room for it
        if float(data.get("script_wall_s") or 0.0) - float(data.get("render_wall_s") or 0.0) > BUILD_WALL_S / 2:
            data["retry_skipped"] = "the first drape took more than half the wall budget"
            break
        first = (res, data)
    data["measure"] = meas
    data["outline"] = spec["outline"]
    data["views"] = {**view_info, "source": sources.get("source", "")}
    data["wall_total_s"] = round(time.time() - started, 2)
    data["render_wall_s"] = float(data.get("render_wall_s") or 0.0)
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "blender failed"), "data": data, "glb": None,
                "rows": []}
    _live_stage(live, "judge")
    rows = judge_build(data)
    bad = [r for r in rows if r["gate"] and not r["ok"]]
    glb = (res.get("outputs") or {}).get("glb")
    error = "; ".join(f"{r['check']} {r['value']} (limit {r['limit']})" for r in bad)
    return {"ok": not bad and bool(glb), "error": error or ("" if glb else "no GLB written"), "data": data,
            "glb": glb, "rows": rows, "outputs": res.get("outputs") or {}}


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
    _live_stage(key, "waiting")
    try:
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
    for other, it in collider_pieces(item_id, params["kind"], lower):
        sub = build(character_name, other, profile=profile, lower=_lower_of(other, item_id, lower))
        if sub["state"] == "ready":
            colliders.append((sub["path"], sub["record"].get("pose_shapes")))
    _live_stage(key, "measure_body")
    scratch = Path(tempfile.mkdtemp(prefix="av-template-"))
    try:
        result = run_drape(body, params, sources, item_id=item_id, out_dir=scratch, lower=colliders, live=key)
        folder = templates_dir(character_name)
        folder.mkdir(parents=True, exist_ok=True)
        record = {"item_id": item_id, "tsig": sig, "params": params, "version": TEMPLATE_VERSION,
                  "base_signature": base[0], "base_model_sha256": base_sha, "lower": lower,
                  "texture": {k: Path(v).name if k != "source" else v for k, v in sources.items()},
                  "colliders": [Path(c[0]).name for c in colliders],
                  "metrics": result["data"], "rows": result["rows"], "created_at": utc_now_iso(),
                  "pose_shapes": (result["data"] or {}).get("pose_shapes")}
        if result["ok"]:
            target = drape_path(character_name, item_id, sig)
            shutil.move(str(result["glb"]), str(target))
            write_record(target.with_suffix(".json"), {**record, "accepted": True})
            failed = failed_path(character_name, item_id, sig)
            if failed.is_file():
                failed.unlink()
        else:
            write_record(failed_path(character_name, item_id, sig), {**record, "error": result["error"]})
            logger.warning("Template drape of %s for %s failed: %s", item_id, character_name, result["error"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    figure.invalidate()
    return drape_state(character_name, item_id, base_sha=base_sha, lower=lower, item=item)


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
