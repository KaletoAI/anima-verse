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
   cut-out views (else its item picture) onto the panel UVs, skinned by
   nearest-face Data Transfer and exported as one garment node.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCRIPT = "garment_template_build"
#: The spike's evaluator script (modes mesh / panels / from_body / necklace).
SPIKE_SCRIPT = "garment_template_drape.py"
#: Bumped when the same parameters drape differently.
TEMPLATE_VERSION = 1
#: The LLM task (``llm_tasks.TASK_TYPES``; unrouted → ``image_recognition``) and its template.
TASK = "garment_template_params"
#: Completion cap for the JSON answer.
MAX_TOKENS = 400

KINDS = ("skirt", "dress", "top", "jacket", "trousers")
BUILT_KINDS = ("skirt", "dress")
WAIST_HEIGHTS = ("high", "natural", "low")
SLIT_SIDES = ("none", "left", "right", "front", "back")
SLEEVES = ("none", "short", "long")
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
    "length_m": ("number", (0.15, 1.2), 0.5),       # from the waist (skirt) / the waist line (dress) down
    "flare": ("number", (0.0, 1.0), 0.3),           # 0 pencil .. 1 near-circle hem
    "waist_height": ("choice", WAIST_HEIGHTS, "natural"),
    "slit": ("choice", SLIT_SIDES, "none"),
    "slit_m": ("number", (0.0, 0.6), 0.0),           # slit depth from the hem up
    "sleeves": ("choice", SLEEVES, "none"),          # recorded; P1 builds sleeveless pieces
    "fabric": ("choice", tuple(FABRICS), "medium"),
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
#: Stretch above which the drape is re-run once with doubled quality (spec section 6), then refused.
RETRY_STRETCH = 1.5

# Pin rings by piece kind (where the cloth hangs from).
PIN_BY_KIND = {"skirt": "waist", "trousers": "waist", "top": "shoulders", "jacket": "shoulders",
               "dress": "shoulders"}

# --- reasons (Ruling A119: a piece not ready is left off, with its reason) -----------------------
NEEDS_PARAMS = "Needs its template parameters — open Edit parameters (1 LLM call to suggest them)"
NOT_DRAPED = "Not draped yet — Build drapes it (CPU, 0 hub jobs)"
KIND_NOT_BUILT = "Template kind '{kind}' is not built yet (skirts and dresses are) — choose another mode"
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
    if params["slit"] == "none":
        params["slit_m"] = 0.0
    elif params["slit_m"] <= 0.0:
        params["slit_m"] = round(min(0.25, params["length_m"] * 0.4), 3)
    params["slit_m"] = round(min(params["slit_m"], params["length_m"] * 0.8), 3)
    return params, errors


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
    P = glb_mesh.body_arrays(glb).positions
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
    return {"height": round(height, 4), "floor_y": round(floor, 4), "waist_y": round(float(waist_y), 4),
            "waist_c": round(waist_c, 4), "hip_y": round(float(hip_y), 4), "hip_c": round(hip_c, 4),
            "band_y": round(float(band_y), 4), "band_c": round(perim(band_y), 4)}


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
    from the hem (0) to the top, the top height ``top_y`` (Y-up world) and the pinned top. A skirt
    runs waist → hem; a dress runs chest band → waist → hem."""
    waist_y = _waist_line(params, meas)
    # circumference at the waist line actually chosen
    frac = (waist_y - meas["hip_y"]) / max(1e-6, meas["waist_y"] - meas["hip_y"])
    waist_c = meas["hip_c"] + (meas["waist_c"] - meas["hip_c"]) * min(1.0, max(0.0, frac)) + EASE_M
    hem_c = max(meas["hip_c"] * 1.04, waist_c) * (1.0 + 1.5 * params["flare"])
    length = params["length_m"]
    knots = [(0.0, hem_c), (length, waist_c)]
    top_y = waist_y
    if params["kind"] == "dress":
        bodice = max(0.08, meas["band_y"] - waist_y)
        knots.append((length + bodice, meas["band_c"] + EASE_M))
        top_y = waist_y + bodice
    return {"knots": knots, "top_y": round(top_y, 4), "waist_y": round(waist_y, 4),
            "length": round(knots[-1][0], 4)}


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
    return {"rows": rows, "cols": COLS, "row_y": row_y, "panels": panels, "outline": shape, "measure": meas,
            "pygarment": {"version": "2.0.2", "panels": specs}}


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
    """``{front, back, source}``: the piece's newest cut-out views from the garment store
    (``images/{item}_{fsig}_cutout_{front,back}.png``) when both exist — what the old own-mesh chain
    already rendered —, else its item picture for both sides (``source`` "item_image"). {} without
    any picture."""
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
    if "front" in best and "back" in best:
        return {"front": best["front"][1], "back": best["back"][1], "source": "cutout"}
    picture = get_item_image_path(item_id)
    return {"front": picture, "back": picture, "source": "item_image"} if picture else {}


def lower_layers(sets: Any, item_id: str) -> List[str]:
    """The other worn mesh pieces (own-mesh and template) of a figure's worn sets — the lower
    layers in the cache key (module docstring)."""
    others = set(getattr(sets, "own", {}) or {}) | set(getattr(sets, "template", ()) or ())
    return sorted(others - {item_id})


def key_for(character_name: str, item_id: str, *, base_sha: str, lower: List[str],
            item: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """``(tsig, reason, texture sources)`` of a template piece: tsig None with the left-off
    reason when it cannot be draped (no parameters, a kind not built, no base, no picture)."""
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
    return tsig(params, base_sha=base_sha, texture_sha=tex, lower=lower), None, sources


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


# --- the drape run ----------------------------------------------------------------

def build_args(params: Dict[str, Any], spec: Dict[str, Any], *, item_id: str, render: bool = False,
               poses: Tuple[str, ...] = ("rest", "walk"), quality_scale: float = 1.0) -> Dict[str, Any]:
    """The ``params`` of one ``garment_template_build`` run."""
    fabric = dict(FABRICS[params["fabric"]])
    fabric["quality"] = int(round(fabric["quality"] * quality_scale))
    meas = spec.get("measure") or {}
    torso = max(meas.get("hip_c", 0.9), meas.get("band_c", 0.9)) / (2 * math.pi) * 1.6
    return {"spec": spec, "fabric": fabric, "torso_half_m": round(torso, 4), "slit": {"side": params["slit"], "depth_m": params["slit_m"]},
            "pin": "top", "kind": params["kind"], "item_id": item_id, "node": f"garment_template_{item_id}",
            "render": bool(render), "poses": list(poses), "frames": 50, "thickness": 0.004}


def judge_build(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pass rows of one build result (``data`` of the script): wall time (the gate), pin drift,
    stretch, rest poke and bake coverage — CPU is reported, never gated (Ruling A138)."""
    rows: List[Dict[str, Any]] = []

    def row(name, value, limit, ok, gate=True):
        rows.append({"check": name, "value": value, "limit": limit, "ok": bool(ok), "gate": gate})

    drape = data.get("drape") or {}
    if "wall_total_s" in data:
        row("build_wall_s", data["wall_total_s"], BUILD_WALL_S, data["wall_total_s"] <= BUILD_WALL_S)
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


def prepare_view(src: str, dst: Path, *, tolerance: int = 24) -> Dict[str, Any]:
    """Write ``src`` as RGBA to ``dst`` with the piece cut free: an image that already has a
    transparent background (a cut-out view) keeps its alpha; an opaque one (an item picture on a
    plain background) loses every border-connected pixel within ``tolerance`` (max channel difference)
    of the median border colour. Returns ``{alpha: "kept" | "border", share}`` (share = opaque
    pixels). The projection registers by the alpha bounding box, so the background must go."""
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
    # A picture of the piece WORN shows skin (legs under a skirt); skin texels would be projected
    # onto the fabric and the alpha box would not be the piece. Skin is dropped when it is a minority
    # of the opaque pixels (a skin-coloured piece keeps its pixels).
    rgb = px[..., :3].astype(np.int32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    skin = ((r > 95) & (g > 40) & (b > 20) & (r > g) & (r > b) & (r - g > 15) & (b * 10 > r * 3)
            & (rgb.max(axis=2) - rgb.min(axis=2) > 15)) & (px[..., 3] >= 128)
    opaque = px[..., 3] >= 128
    skin_share = float(skin.sum() / max(1, opaque.sum()))
    if 0.0 < skin_share < 0.5:
        px[..., 3] = np.where(skin, 0, px[..., 3]).astype(np.uint8)
    Image.fromarray(px).save(dst)
    return {"alpha": mode, "share": round(float((px[..., 3] >= 128).mean()), 4),
            "skin_dropped": round(skin_share, 4) if 0.0 < skin_share < 0.5 else 0.0}


def run_drape(body_glb: Path, params: Dict[str, Any], sources: Dict[str, str], *, item_id: str,
              out_dir: Path, render: bool = False, poses: Tuple[str, ...] = ("rest", "walk"),
              timeout_s: int = 300) -> Dict[str, Any]:
    """Measure, make the panels and drape on ``body_glb`` (one Blender run; one retry with doubled
    quality when the stretch is above ``RETRY_STRETCH``). Returns ``{ok, error, data, glb, rows}`` —
    ``ok`` False when Blender failed or a gate row failed (``error`` names it)."""
    import time
    from app.blender import runner
    started = time.time()
    meas = measure_body(Path(body_glb).read_bytes())
    spec = panel_spec(params, meas)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    views = {side: out_dir / f"view_{side}.png" for side in ("front", "back")}
    view_info = {side: prepare_view(sources[side], views[side]) for side in views}
    data: Dict[str, Any] = {}
    res: Dict[str, Any] = {}
    for scale in (1.0, 2.0):
        res = runner.run(SCRIPT, inputs={"body": Path(body_glb), "front": views["front"], "back": views["back"]},
                         params=build_args(params, spec, item_id=item_id, render=render, poses=poses,
                                           quality_scale=scale),
                         out_dir=Path(out_dir), timeout_s=timeout_s)
        data = dict(res.get("data") or {})
        if not res.get("ok"):
            break
        if (data.get("drape") or {}).get("stretch_max", 0) <= RETRY_STRETCH:
            break
    data["measure"] = meas
    data["outline"] = spec["outline"]
    data["views"] = {**view_info, "source": sources.get("source", "")}
    data["wall_total_s"] = round(time.time() - started, 2)
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "blender failed"), "data": data, "glb": None,
                "rows": []}
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
    the new ``drape_state``. A ready drape is kept unless ``force``."""
    import shutil
    import tempfile
    from app.core import base_body, figure
    from app.core.garment_store import write_record
    from app.core.timeutils import utc_now_iso
    from app.models.character import get_character_dir, get_character_profile
    from app.models.inventory import get_item
    profile = profile if profile is not None else (get_character_profile(character_name) or {})
    base = base_body.current_base(character_name, profile=profile)
    base_sha = base[1] if base else ""
    if lower is None:
        lower = lower_layers(figure.worn_sets(character_name, profile=profile), item_id)
    item = get_item(item_id)
    state = drape_state(character_name, item_id, base_sha=base_sha, lower=lower, item=item)
    if state["state"] == "blocked" or (state["state"] == "ready" and not force):
        return state
    sig = state["tsig"]
    sources = texture_sources(character_name, item_id)
    body = get_character_dir(character_name) / "model3d" / f"{base[0]}.glb"
    params = params_of(item)
    scratch = Path(tempfile.mkdtemp(prefix="av-template-"))
    try:
        result = run_drape(body, params, sources, item_id=item_id, out_dir=scratch)
        folder = templates_dir(character_name)
        folder.mkdir(parents=True, exist_ok=True)
        record = {"item_id": item_id, "tsig": sig, "params": params, "version": TEMPLATE_VERSION,
                  "base_signature": base[0], "base_model_sha256": base_sha, "lower": lower,
                  "texture": {k: Path(v).name if k != "source" else v for k, v in sources.items()},
                  "metrics": result["data"], "rows": result["rows"], "created_at": utc_now_iso()}
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
