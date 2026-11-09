"""Collision capsules — one body collider set per character model (spec
``docs/superpowers/specs/2026-11-08-collision-capsules-design.md``).

Garment and hair meshes skinned to the body's skeleton, and the spring-driven extension bones, pass through
the body once the pose leaves the bind pose. A small set of capsules around the body's bones, computed here
once per model and applied by both renderers every frame (``@anima/scene-render``), keeps them outside.

PAYLOAD (sidecar key ``collision``, delivered next to ``extension_rig``)::

    {"version": 1,
     "capsules": [{"id": "left_thigh", "a": "mixamorig:LeftUpLeg", "b": "mixamorig:LeftLeg",
                   "r": 0.1, "region": "leg"},
                  {"id": "head", "a": "mixamorig:Head", "b": "mixamorig:Head",
                   "b_pos": [0.0, 1.62, 0.13], "r": 0.075, "region": "head"}, ...],
     "skipped":  [{"id": "left_shin", "a": "mixamorig:LeftLeg", "b": "LeftFoot",
                   "reason": "joint LeftFoot missing"}],
     "scales":   {"leg": 1.0, "arm": 1.0, "torso": 1.0, "head": 1.0},
     "source":   "own" | "base",       # fitted on this file / the base body it was built on
     "base_signature": "<bsig>",       # only with source "base"
     "sha256":   "<file the set describes>",
     "computed_at": "<ISO>"}

``a``/``b`` are the joint names AS IN THE MODEL (matched through ``rig_contract.norm_bone_name``), ``r`` in
metres of the model's bind space. A capsule whose joint is missing (or whose start bone owns too few vertices)
is not in ``capsules`` but in ``skipped`` with the reason — never a crash.

ENDPOINT RULE. Each endpoint may carry an optional bind-space position, ``a_pos`` / ``b_pos`` (``[x, y, z]``
in the space of the body's POSITION accessor). Absent → the joint's own bind position (inverse bind matrix).
Present → a point FIXED TO THAT JOINT: it moves exactly like a body vertex skinned 100 % to the joint,
``p_now = boneWorld · inverse(boneBindWorld) · p_bind`` (three.js: the joint's ``matrixWorld`` times its
``skeleton.boneInverses`` entry, inside the skinned mesh's bind frame). The head capsule uses it: ``a`` = ``b``
= Head, ``b_pos`` = a point above the Head joint (the rig contract has no crown joint).

WHICH MODEL GETS WHICH SET. Humanoid (``rig "mixamo"``) GLB models only. A model of its own (generated,
uploaded, the base body itself) is fitted on its own file (``source "own"``, ``sha256`` = the file). An outfit
model on the base-body pipeline (sidecar ``source "base_body"``, ``base_model_sha256``) carries the set of the
base body it was BUILT ON (``source "base"``, ``sha256`` = that base model's sha): its outfit is painted onto a
copy of that body, so the base's set is its set — the base sidecar's record is copied with the rest of the base
meta (``base_body.build_outfit_model``), and when it is missing or outdated the outfit's own file is fitted
under the same identity (body nodes only — ``glb_mesh.body_arrays`` skips grafted garments). A rebuilt or
retextured base never leaves a stale set on the outfit served: the outfit's record names the base sha it was
built on, so it always describes the body actually in the file.

A record is CURRENT when ``version``, ``sha256`` (the identity above) and ``scales`` (the character's region
scales, ``model3d_opts.collision_scales``) all match. ``ensure`` / ``ensure_path`` recompute and store anything
else; the post-rig chain (``model3d._auto_collision``) refreshes it right after the extension rig.

FITTING (``fit_capsules``) — the S1 spike's method: for each capsule the body vertices whose DOMINANT skin
weight is the capsule's start bone, their distances to the bone segment ``a→b`` (bind pose; joint positions =
inverse bind matrices), radius = quantile of those distances + margin, times the region scale. No normals: the
UniForge/Trellis body is a double-walled shell with mixed winding.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("collision")

VERSION = 1
REGIONS = ("leg", "arm", "torso", "head")
SCALE_MIN, SCALE_MAX = 0.5, 1.5
#: A start bone owning fewer body vertices than this gives no capsule (a quantile of a handful is noise).
MIN_VERTICES = 16

#: THE capsule table: ``(id, start joint, end joint, region, quantile, margin m, end rule)``. Joint names are the
#: Mixamo base names (compared after ``norm_bone_name``). End rule ``"joint"``: the segment ends at the end
#: joint. ``"crown"`` (head): the end is a ``b_pos`` fixed to the end joint (module docstring, ENDPOINT RULE):
#: body axis ``u`` = Hips→Head; crown = the highest vertex owned by the start bone along ``u``; radius =
#: quantile of the distances of those vertices to Head→crown (+ margin, × scale); ``b_pos`` = crown − r·u, so the
#: capsule's cap ends AT the crown instead of r above it (never below the Head joint — then it is a sphere).
#:
#: Limbs — p95 + 6 mm: the S1 spike's leg capsules at that radius cut garment penetration to ≤ 0.6 % on walk
#: and run without ballooning the skirt (p100 did).
#:
#: Torso — measured 2026-11-09 on Kira's three base bodies (read-only copies of
#: ``characters/Kira/model3d/base{20d5701a,233fdd2a,5c5f3624}.glb``) and the two S1 spike bodies
#: (``s1ap``, ``s1pf``). The spine joints sit close to the BACK of the trunk: per 1-cm slice along each segment the
#: side-view (profile) limit is min(front, back distance of the trunk surface from the bone axis), median over
#: the inner slices: hips→spine1 4.1 / 4.1 / 4.2 / 6.9 / 5.5 cm (the back; the front is 11.5–15.2 cm),
#: spine1→spine2 6.8 / 5.8 / 5.6 / 6.4 / 6.2 cm, spine2→neck 8.1 / 8.3 / 7.8 / 8.0 / 7.6 cm (the neck in front).
#: The trunk's half-width is 11.8–13.9 cm — the ellipse the spec warns about. A round p95 capsule (hips 15.5–17.5,
#: spine 12.2–14.8, chest 14.1–18.1 cm) sticks 6–10 cm out of the back. Quantiles of the start bone's vertex
#: distances (same five bodies):
#:   hips→spine1   p2 4.4–6.7  p5 5.9–9.7  p10 8.1–10.8 cm  → p2 is the largest that stays within the
#:                 profile (two bodies 3–4 mm over: the 5-mm penetration threshold); the hips vertices are the
#:                 whole pelvis, buttocks and hip sides, so any higher quantile leaves the lower back;
#:   spine1→spine2 p10 4.9–6.4  p15 5.4–7.1 cm → p10 (inside on all five; p15 over on four by ≤ 8 mm);
#:   spine2→neck   p10 5.4–7.7  p15 5.8–8.2 cm → p10 (inside on all five).
#: Margin 0: a torso capsule protects hair and extension bones from sinking DEEP, it must never float them.
#:
#: Head — ``HeadTop_End`` is not part of the 52-joint rig contract (``shared/models/rig/joints.json``), so the
#: head capsule uses the crown rule. p50, margin 0: hair lies on the scalp, a fatter head capsule floats it
#: (HEAD_MEASURED below; p95 is 2–4 cm larger — the face and jaw widen the tail).
CAPSULES: Tuple[Tuple[str, str, str, str, float, float, str], ...] = (
    ("left_thigh", "LeftUpLeg", "LeftLeg", "leg", 0.95, 0.006, "joint"),
    ("left_shin", "LeftLeg", "LeftFoot", "leg", 0.95, 0.006, "joint"),
    ("right_thigh", "RightUpLeg", "RightLeg", "leg", 0.95, 0.006, "joint"),
    ("right_shin", "RightLeg", "RightFoot", "leg", 0.95, 0.006, "joint"),
    ("left_upper_arm", "LeftArm", "LeftForeArm", "arm", 0.95, 0.006, "joint"),
    ("left_forearm", "LeftForeArm", "LeftHand", "arm", 0.95, 0.006, "joint"),
    ("right_upper_arm", "RightArm", "RightForeArm", "arm", 0.95, 0.006, "joint"),
    ("right_forearm", "RightForeArm", "RightHand", "arm", 0.95, 0.006, "joint"),
    ("hips", "Hips", "Spine1", "torso", 0.02, 0.0, "joint"),
    ("spine", "Spine1", "Spine2", "torso", 0.10, 0.0, "joint"),
    ("chest", "Spine2", "Neck", "torso", 0.10, 0.0, "joint"),
    ("head", "Head", "Head", "head", 0.50, 0.0, "crown"),
)
#: The joint that, with the start bone, gives the body axis of the crown rule.
CROWN_AXIS_FROM = "Hips"

#: HEAD_MEASURED (crown rule, 2026-11-09, same five bodies as the torso; body axis Hips→Head): crown above the
#: Head joint 18.9 / 20.3 / 19.4 / 16.1 / 18.7 cm; p50 radius 7.1 / 7.8 / 7.5 / 6.9 / 8.1 cm; ``b_pos`` 11.7 /
#: 12.5 / 11.9 / 9.3 / 10.6 cm above the Head joint; the capsule's top lands within 6 mm of the body's top
#: (1.694–1.701 m on 1.700-m bodies).


# --- region scales (per character) ---------------------------------------------------------------------------------

def default_scales() -> Dict[str, float]:
    return {region: 1.0 for region in REGIONS}


def validate_scales(raw: Any) -> Dict[str, float]:
    """The full region-scale map of ``raw`` (missing regions = 1.0). ValueError on an unknown region, a
    non-number or a value outside ``[SCALE_MIN, SCALE_MAX]``."""
    if raw is None:
        return default_scales()
    if not isinstance(raw, dict):
        raise ValueError("collision scales must be a region -> number map")
    out = default_scales()
    for region, value in raw.items():
        if region not in REGIONS:
            raise ValueError(f"unknown collision region '{region}'")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"collision scale of '{region}' must be a number")
        if not SCALE_MIN <= float(value) <= SCALE_MAX:
            raise ValueError(f"collision scale of '{region}' must be between {SCALE_MIN} and {SCALE_MAX}")
        out[region] = round(float(value), 3)
    return out


def character_scales(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """The character's region scales (``model3d_opts.collision_scales``); an unreadable profile or an invalid
    stored value counts as the defaults."""
    if profile is None:
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        except Exception:  # noqa: BLE001 — defaults rather than no capsules
            profile = {}
    try:
        return validate_scales((profile.get("model3d_opts") or {}).get("collision_scales"))
    except ValueError as exc:
        logger.warning("Collision scales of %s ignored: %s", character_name, exc)
        return default_scales()


# --- fitting -------------------------------------------------------------------------------------------------------

def _matrices(parsed: dict, index: int) -> np.ndarray:
    """A MAT4 float accessor as ``(n, 4, 4)`` row-major matrices (glTF stores column-major)."""
    gltf, binary = parsed["gltf"], parsed["bin"]
    accessor = gltf["accessors"][index]
    if accessor.get("type") != "MAT4" or accessor.get("componentType") != 5126 or accessor.get("sparse"):
        raise ValueError("inverseBindMatrices must be a dense float MAT4 accessor")
    view = gltf["bufferViews"][accessor["bufferView"]]
    count = int(accessor["count"])
    stride = int(view.get("byteStride", 64))
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    if view.get("buffer", 0) != 0 or stride < 64 or start + (count - 1) * stride + 64 > len(binary):
        raise ValueError("inverseBindMatrices accessor is truncated")
    array = np.ndarray((count, 16), dtype="<f4", buffer=binary, offset=start, strides=(stride, 4))
    return np.asarray(array, np.float64).reshape(count, 4, 4).transpose(0, 2, 1)


def _world_matrix(nodes: List[dict], index: int, parents: Dict[int, int]) -> np.ndarray:
    from app.core.glb_mesh import _local_matrix
    matrix = _local_matrix(nodes[index])
    seen = {index}
    while index in parents:
        index = parents[index]
        if index in seen:
            raise ValueError("node hierarchy has a cycle")
        seen.add(index)
        matrix = _local_matrix(nodes[index]) @ matrix
    return matrix


def _segment_distances(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((points - a) @ ab) / float(ab @ ab), 0.0, 1.0)
    return np.linalg.norm(points - (a + t[:, None] * ab), axis=1)


def fit_capsules(rigged_glb: bytes, *, scales: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The capsule set of a rigged humanoid GLB: ``{version, capsules, skipped, scales}`` (pure; module
    docstring). ValueError for a file without a skinned body."""
    from app.core import glb_mesh
    from app.core.rig_contract import norm_bone_name
    scales = validate_scales(scales)
    parsed = glb_mesh._parse(rigged_glb, "Model")
    gltf = parsed["gltf"]
    skins, nodes = gltf.get("skins") or [], gltf.get("nodes") or []
    if not skins or "inverseBindMatrices" not in skins[0]:
        raise ValueError("The model has no skin with inverse bind matrices")
    joints = skins[0].get("joints") or []
    ibm = _matrices(parsed, skins[0]["inverseBindMatrices"])
    if len(ibm) != len(joints) or not joints:
        raise ValueError("The skin's inverse bind matrices do not match its joints")
    body = glb_mesh.body_arrays(rigged_glb)
    if not body.joint_names or not np.any(body.weights):
        raise ValueError("The body mesh is not skinned")
    names = [str(nodes[j].get("name") or "") for j in joints]
    keys = [norm_bone_name(n) for n in names]
    index_of: Dict[str, int] = {}
    for i, key in enumerate(keys):
        index_of.setdefault(key, i)
    positions = np.linalg.inv(ibm)[:, :3, 3]
    # Bind space -> metres at rest: the root joint's world matrix times its inverse bind matrix (identity for
    # every normalised model; an FBX-style armature scale would show here).
    parents = {c: i for i, n in enumerate(nodes) for c in n.get("children") or []}
    rest = _world_matrix(nodes, joints[0], parents) @ ibm[0]
    unit = abs(float(np.linalg.det(rest[:3, :3]))) ** (1.0 / 3.0)
    if not math.isfinite(unit) or unit <= 0:
        unit = 1.0
    rows = np.arange(len(body.weights))
    strongest = body.weights.argmax(axis=1)
    dominant = body.joints[rows, strongest]
    dominant = np.where(body.weights[rows, strongest] > 0, dominant, -1)
    capsules: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for capsule_id, start, end, region, quantile, margin, end_rule in CAPSULES:
        a_index, b_index = index_of.get(norm_bone_name(start)), index_of.get(norm_bone_name(end))
        a_name = names[a_index] if a_index is not None else start
        b_name = names[b_index] if b_index is not None else end
        needed = [(start, a_index), (end, b_index)]
        if end_rule == "crown":
            needed.append((CROWN_AXIS_FROM, index_of.get(norm_bone_name(CROWN_AXIS_FROM))))
        missing = list(dict.fromkeys(n for n, i in needed if i is None))
        if missing:
            skipped.append({"id": capsule_id, "a": a_name, "b": b_name,
                            "reason": "joint " + " and ".join(missing) + " missing"})
            continue
        # The body's skin indexes ITS joint list (skin 0 = the same list as above).
        owned = body.positions[dominant == a_index]
        if len(owned) < MIN_VERTICES:
            skipped.append({"id": capsule_id, "a": a_name, "b": b_name,
                            "reason": f"too few vertices on {start} ({len(owned)})"})
            continue
        a = positions[a_index]
        if end_rule == "crown":
            axis = a - positions[index_of[norm_bone_name(CROWN_AXIS_FROM)]]
            if float(np.linalg.norm(axis)) < 1e-4:
                skipped.append({"id": capsule_id, "a": a_name, "b": b_name, "reason": "no body axis"})
                continue
            axis = axis / np.linalg.norm(axis)
            height = float(((owned - a) @ axis).max())
            if height < 1e-3:
                skipped.append({"id": capsule_id, "a": a_name, "b": b_name,
                                "reason": f"no vertices above {start}"})
                continue
            b = a + axis * height
        else:
            b = positions[b_index]
        if float(np.linalg.norm(b - a)) < 1e-4:
            skipped.append({"id": capsule_id, "a": a_name, "b": b_name, "reason": "degenerate segment"})
            continue
        distance = float(np.quantile(_segment_distances(owned, a, b), quantile))
        radius = (distance * unit + margin) * scales[region]
        capsule = {"id": capsule_id, "a": a_name, "b": b_name, "r": round(radius, 4), "region": region}
        if end_rule == "crown":
            # The cap ends at the crown: the segment end lies r below it (never below the Head joint).
            capsule["b_pos"] = [round(float(v), 4) for v in a + axis * max(height - radius / unit, 0.0)]
        capsules.append(capsule)
    return {"version": VERSION, "capsules": capsules, "skipped": skipped, "scales": scales}


# --- the stored record ---------------------------------------------------------------------------------------------

def _file_sha256(path: Path) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


def identity(path: Path, meta: Dict[str, Any]) -> Tuple[str, str]:
    """``(source, sha256)`` the record of the model ``path`` must carry (module docstring)."""
    if meta.get("source") == "base_body" and not meta.get("base") and meta.get("base_model_sha256"):
        return "base", str(meta["base_model_sha256"])
    return "own", _file_sha256(path)


def is_current(record: Any, sha256: str, scales: Dict[str, float]) -> bool:
    return (isinstance(record, dict) and record.get("version") == VERSION and bool(sha256)
            and record.get("sha256") == sha256 and record.get("scales") == scales)


def applies(path: Optional[Path], meta: Dict[str, Any]) -> bool:
    """Whether a model gets a capsule set: a humanoid GLB."""
    return (path is not None and path.suffix.lower() == ".glb"
            and (meta.get("rig") or "mixamo") == "mixamo")


def _record(fitted: Dict[str, Any], *, source: str, sha256: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.timeutils import utc_now_iso
    record = {**fitted, "source": source, "sha256": sha256, "computed_at": utc_now_iso()}
    if source == "base":
        record["base_signature"] = str(meta.get("base_signature") or "")
    return record


def refresh(character_name: str, path: Path, meta: Dict[str, Any], *,
            scales: Optional[Dict[str, float]] = None, force: bool = False) -> bool:
    """Bring ``meta["collision"]`` of the model file ``path`` up to date IN MEMORY (the caller publishes the
    sidecar — the post-rig chain). Returns True when the record changed. Never raises: a failed fit is stored
    as a record with ``error`` and no capsules (so a poll does not refit it), a non-humanoid model drops it."""
    if not applies(path, meta):
        return meta.pop("collision", None) is not None
    if scales is None:
        scales = character_scales(character_name)
    source, sha = identity(path, meta)
    record = meta.get("collision")
    if not force and is_current(record, sha, scales):
        if record.get("source") == source and (source != "base"
                                               or record.get("base_signature") == meta.get("base_signature")):
            return False
        # The base body's record copied with the base meta: the same set, labelled as inherited.
        relabelled = {k: v for k, v in record.items() if k != "base_signature"}
        relabelled["source"] = source
        if source == "base":
            relabelled["base_signature"] = str(meta.get("base_signature") or "")
        meta["collision"] = relabelled
        return True
    try:
        fitted = fit_capsules(path.read_bytes(), scales=scales)
    except Exception as exc:  # noqa: BLE001 — a model without capsules is still a model
        logger.warning("Collision capsules of %s (%s) failed: %s", character_name, path.name, exc)
        fitted = {"version": VERSION, "capsules": [], "skipped": [], "scales": scales, "error": str(exc)}
    meta["collision"] = _record(fitted, source=source, sha256=sha, meta=meta)
    return True


def ensure_path(character_name: str, path: Optional[Path], *, scales: Optional[Dict[str, float]] = None,
                force: bool = False) -> Optional[Dict[str, Any]]:
    """The current capsule record of the stored model file ``path`` — computed and written into its sidecar
    when missing or stale (``force``: always). None for a model that gets none (``applies``) or one replaced
    while it was being fitted (the next call fits the new file)."""
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import _publish_sidecar, _read_sidecar
    if path is None or not path.is_file():
        return None
    meta = _read_sidecar(path)
    if not applies(path, meta):
        return None
    if scales is None:
        scales = character_scales(character_name)
    before = meta.get("collision")
    sha_before = _file_sha256(path)
    if not refresh(character_name, path, meta, scales=scales, force=force):
        return before
    record = meta["collision"]
    with keyed_lock("model3d_publication", str(path.parent)):
        if _file_sha256(path) != sha_before:
            return None
        current = _read_sidecar(path)
        if identity(path, current) != (record["source"], record["sha256"]):
            return None
        current["collision"] = record
        _publish_sidecar(path, current)
    logger.info("Collision capsules %s (%s): %d capsules, %d skipped, source %s", character_name, path.name,
                len(record.get("capsules") or []), len(record.get("skipped") or []), record["source"])
    return record


def ensure(character_name: str, signature: str, *, force: bool = False) -> Optional[Dict[str, Any]]:
    """``ensure_path`` for the stored full-tier model ``model3d/<signature>.glb`` of a character."""
    from app.core.face_retexture import safe_signature
    from app.core.model3d import get_model3d_dir
    signature = safe_signature(signature)
    return ensure_path(character_name, get_model3d_dir(character_name) / f"{signature}.glb", force=force)


def recompute_character(character_name: str) -> Dict[str, Any]:
    """After a region-scale change (``model3d_opts.collision_scales``): bring the capsule set of every stored
    full-tier model of the character (``model3d/*.glb``; retired state forks, the distance tier and the covered
    variant carry none) up to date with the character's scales. On the base-body pipeline the CURRENT base model
    goes first — it owns the set — then every outfit model, whose inherited set is refitted under the base identity
    (``refresh``: body nodes only = the base body it was built on). Only the sidecar key ``collision`` is written;
    the model files, renders and every other sidecar key stay as they are.

    Returns ``{"scales": {...}, "models": {signature: {"ok", "count", "skipped", "source"} | {"ok", "error"}}}``;
    a model that gets no set (not a humanoid GLB) reports ``{"ok": True, "count": 0, "none": True}``."""
    from app.core.model3d import _current_base, get_model3d_dir
    from app.core.model_refs import is_state_fork
    scales = character_scales(character_name)
    current = _current_base(character_name)
    directory = get_model3d_dir(character_name)
    paths = sorted((path for path in directory.glob("*.glb") if not is_state_fork(path.stem)),
                   key=lambda path: (not current or path.stem != current[0], path.stem))
    models: Dict[str, Any] = {}
    for path in paths:
        try:
            record = ensure_path(character_name, path, scales=scales)
        except Exception as exc:  # noqa: BLE001 — one unreadable model does not stop the others
            logger.warning("Collision capsules of %s (%s) not recomputed: %s", character_name, path.name, exc)
            models[path.stem] = {"ok": False, "error": str(exc)}
            continue
        if record is None:
            models[path.stem] = {"ok": True, "count": 0, "none": True}
        elif record.get("error"):
            models[path.stem] = {"ok": False, "error": str(record["error"])}
        else:
            models[path.stem] = {"ok": True, "count": len(record.get("capsules") or []),
                                 "skipped": len(record.get("skipped") or []), "source": record.get("source")}
    return {"scales": scales, "models": models}


def summary(record: Any) -> Dict[str, Any]:
    """Display numbers of a record: ``{count, skipped, radii: {region: [min, max] cm}}``."""
    if not isinstance(record, dict):
        return {}
    radii: Dict[str, List[float]] = {}
    for capsule in record.get("capsules") or []:
        r = float(capsule.get("r") or 0) * 100
        low, high = radii.get(capsule.get("region"), [r, r])
        radii[capsule.get("region")] = [min(low, r), max(high, r)]
    return {"count": len(record.get("capsules") or []), "skipped": len(record.get("skipped") or []),
            "radii": {k: [round(v[0], 1), round(v[1], 1)] for k, v in radii.items()}}
