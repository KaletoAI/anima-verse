"""Posture match of an outfit body to its base body (mesh mode of the
outfit bodies, plan 2026-11-10-outfit-body-mesh-mode; user decision
2026-11-10: every outfit body gets the base body's posture automatically).

WHY. The auto-rigger stands every delivery at an attitude of its own: it
reads the T-pose mesh, re-poses it into its canonical rest and pitches the
whole figure forward by a noisy amount. Measured on Kira's clone
(2026-11-10, rest bones, hips->head line against vertical): base body
5.1°, outfit bodies 11.0° and 14.3° — with hips pitch, leg line and foot
attitude tilted by the same amount, i.e. the WHOLE figure leans like a
plank. normalize's posture restore (``normalize._restore_posture``) works
in the hips frame and leaves that global attitude alone on purpose (the
clients divide the root frame out when they play a clip, clipRetarget.ts).
The bind pose keeps it, though: the T-pose an outfit body is shown in, the
own-mesh garments fitted onto it and the collision check all see the lean.

WHAT. After normalize (``model3d._auto_posture_match``), the outfit body is
turned RIGIDLY — armature and skin as one piece, about the ground point,
re-grounded and baked (``app/blender/scripts/posture_match.py``) — so its
rest hips->head line leans exactly as the base body's does, forward/back
and sideways (``rest_lean``: the same measure the E2E used, read from the
GLB's node tree). A rigid turn changes only the root bone's rest frame:
every joint keeps its frame relative to its parent, so skin, weights,
extension bones and the client's clip transplant (root frame divided out)
stay exactly as they were — what changes is the bind pose, which is the
point. Measured on body ``ob5c5f9bf2``: hips pitch 14.2° -> 5.0° (base 4.6°),
leg lines -16° -> -7° (base -9°), ball-of-foot pitch 50° -> 41° (base 40°).

RECORD. The body's sidecar keeps ``blender.posture_match`` =
``{version, base_signature, base_sha256, target, before, after,
applied_deg, axis, status, error, at}``; the Outfit body tab shows it as the
step "Posture matched to base" (``model_overview``). The record is STALE
(``stale_reason``) when it is missing, has another ``version`` than
``POSTURE_MATCH_VERSION``, recorded an error or was matched to another base
model — such a
body is matched on the CPU (``model3d.match_outfit_body_posture``, no hub
job) by the garment refit boot sweep, the tab's "Re-fit all" and the next
outfit build on it; a re-rig matches inside its chain. A changed body file
makes the outfit models on it stale (``body_sha256``) and its garment fits
refit (``garments.body_fit`` keys them by body sha).

TILT. The Tilt sliders of the Base body / Outfit body viewers are a
preview rotation of the displayed figure only (``applyPreviewTilt``), never
stored and never baked: the match reads the stored REST bones of both
models, so the base's own lean is the target and nothing is added twice —
a viewer tilt then turns base and body alike on top of the same posture.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

#: Bumped when the posture match changes; an older record is matched again (CPU).
POSTURE_MATCH_VERSION = 1
#: Below this angle (degrees) between body and base the body is left as it is.
TOLERANCE_DEG = 0.25

STALE_MISSING = "missing"
STALE_VERSION = "version"
STALE_BASE = "base"
STALE_FAILED = "failed"


def rest_lean(glb: bytes) -> Dict[str, float]:
    """``{forward_deg, side_deg}`` of a rigged humanoid GLB: the rest
    hips->head line against the vertical, from the node tree (glTF: +Y up,
    the figure faces +Z). ``forward_deg`` positive = head in front of the
    hips, ``side_deg`` positive = head toward +X. ValueError without both
    joints or with the head not above the hips."""
    from app.core.glb_mesh import _local_matrix
    from app.core.model_validate import parse_glb
    from app.core.rig_contract import norm_bone_name
    nodes = parse_glb(glb)["gltf"].get("nodes") or []
    parents = {c: i for i, n in enumerate(nodes) for c in n.get("children") or []}
    index: Dict[str, int] = {}
    for i, node in enumerate(nodes):
        index.setdefault(norm_bone_name(str(node.get("name") or "")), i)

    def position(name: str) -> np.ndarray:
        if name not in index:
            raise ValueError(f"the model has no {name} joint")
        i = index[name]
        matrix = _local_matrix(nodes[i])
        seen = {i}
        while i in parents:
            i = parents[i]
            if i in seen:
                raise ValueError("node hierarchy has a cycle")
            seen.add(i)
            matrix = _local_matrix(nodes[i]) @ matrix
        return matrix[:3, 3]

    d = position("head") - position("hips")
    if d[1] <= 1e-6:
        raise ValueError("the head is not above the hips")
    return {"forward_deg": round(math.degrees(math.atan2(float(d[2]), float(d[1]))), 4),
            "side_deg": round(math.degrees(math.atan2(float(d[0]), float(d[1]))), 4)}


def lean_delta(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """The angle (degrees) between the two hips->head directions."""
    def unit(lean: Dict[str, Any]) -> np.ndarray:
        v = np.array([math.tan(math.radians(float(lean["side_deg"]))), 1.0,
                      math.tan(math.radians(float(lean["forward_deg"])))])
        return v / np.linalg.norm(v)
    return math.degrees(math.acos(max(-1.0, min(1.0, float(unit(a) @ unit(b))))))


def base_model_file(character_name: str, bsig: str) -> Path:
    """The rigged base model ``model3d/<bsig>.glb`` of the REAL model directory
    (also from inside a staged run on the body's signature)."""
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "model3d" / f"{bsig}.glb"


def base_target(character_name: str, bsig: str) -> Dict[str, Any]:
    """``{lean, sha256}`` of the base model ``bsig``; ValueError without one."""
    from app.core.base_body import is_base_signature
    if not is_base_signature(bsig):
        raise ValueError("the outfit body names no base signature")
    path = base_model_file(character_name, bsig)
    try:
        data = path.read_bytes()
    except OSError:
        raise ValueError(f"the base model {bsig} is missing") from None
    import hashlib
    return {"lean": rest_lean(data), "sha256": hashlib.sha256(data).hexdigest()}


def record_of(meta: Dict[str, Any]) -> Dict[str, Any]:
    record = (meta.get("blender") or {}).get("posture_match") if isinstance(meta.get("blender"), dict) else None
    return record if isinstance(record, dict) else {}


def stale_reason(character_name: str, meta: Dict[str, Any]) -> str:
    """Why the posture of the outfit body with sidecar ``meta`` is to be
    matched (again): ``"missing"`` (never matched), ``"version"`` (an older
    ``POSTURE_MATCH_VERSION``), ``"failed"`` (the last match recorded an
    error — retried, CPU), ``"base"`` (matched to another base model than
    the stored one of its base signature); "" when current or when ``meta``
    is no rigged outfit body."""
    parent = meta.get("outfit_body")
    if not isinstance(parent, dict) or meta.get("rig") != "mixamo" or meta.get("rig_error"):
        return ""
    record = record_of(meta)
    if not record:
        return STALE_MISSING
    if record.get("version") != POSTURE_MATCH_VERSION:
        return STALE_VERSION
    if record.get("error"):
        return STALE_FAILED
    from app.core.base_body import base_model_sha256
    bsig = str(parent.get("base_signature") or "")
    current = base_model_sha256(character_name, bsig) if bsig else ""
    if current and record.get("base_sha256") != current:
        return STALE_BASE
    return ""


def is_stale(character_name: str, body_id: str) -> bool:
    """Whether the stored outfit body ``body_id`` waits for a posture match."""
    from app.core.base_body import outfit_body_path
    from app.core.model3d import _read_sidecar
    path = outfit_body_path(character_name, body_id)
    return path.is_file() and bool(stale_reason(character_name, _read_sidecar(path)))
