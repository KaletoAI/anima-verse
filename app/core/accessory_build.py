"""Per character × body builds of thin accessories (Ruling A118; spec
``docs/superpowers/specs/2026-11-16-accessories-design.md`` § 4–§ 7, plan Task 6).

An outfit piece in mode ``accessory`` (``garment_set.ACCESSORY``) with a ``jewellery`` description
(``accessory_spec``) is built on the CPU from the character's plain rigged body — 0 hub jobs. Phase P1 builds the
necklace: ``accessory_curve.neck_curve`` (on the skin, ``GAP_M`` + the tube radius off it) swept into a tube
(``accessory_mesh.tube``) skinned with the nearest body vertices' weights.

Store (per character)::

    <character>/jewellery/<item>_<asig>.npz   positions, faces, normals, joints, weights
    <character>/jewellery/<item>_<asig>.json  the record: asig, spec, base_model_sha256 (+ base_geometry_id),
                                              joint_names, metrics, landmarks, built_at

``asig`` = md5[:12] over the GEOMETRY inputs only (``geometry_inputs``: kind, chain, version) — the metal is a
material and re-assembles on the CPU without a rebuild. A record holds for the body it was built on
(``model_geometry.record_matches``: the same base file or the same geometry). ``accessory_state`` judges:

- ``current`` — a record of the current asig on the current body;
- ``due`` — with the reason in words: "body changed" (a record of this asig on another body), "chain settings
  changed" (a record of another asig), "not built yet";
- ``blocked`` — no kind chosen, a kind not built yet (a later phase), no plain body;
- ``failed`` — the last build of this asig on this body raised (``<item>_<asig>.failed.json``).

The garment assembly grafts a current build as the node ``accessory_mesh.node_name`` (``garment_assembly``).
"""
import hashlib
import json
import re
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Bumped when an accessory is built differently for the same inputs.
ACCESSORY_VERSION = 2
#: The air between the skin and the chain's surface. The plan's 1.5 mm left one ring of Lirien's chain at 0.94 mm
#: in the sit clip (A216 acceptance: rest 1.50–2.57 mm, sit min 0.94 mm); 1.7 mm keeps every ring inside the
#: 1–3 mm band in rest, walk and sit (the skinning moves a ring by at most ~0.6 mm there).
GAP_M = 0.0017
#: The folder of the builds in a character's directory.
DIR_NAME = "jewellery"

#: ``accessory_state`` reasons (English words, shown in the Wardrobe and the Figure tab).
REASON_NOT_BUILT = "Not built yet — Build makes it on the CPU (0 hub jobs)"
REASON_BODY = "Body changed — Build makes it again on the CPU (0 hub jobs)"
REASON_SETTINGS = "Chain settings changed — Build makes it again on the CPU (0 hub jobs)"
REASON_NO_KIND = "Choose the accessory kind in the Wardrobe"
REASON_KIND_LATER = "{kind}: not built yet in this version — shown on the figure once its phase lands"
REASON_NO_BODY = "No plain body yet"
REASON_FAILED = "Build failed — {error}"


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def store_dir(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / DIR_NAME


def geometry_inputs(spec: Dict[str, Any]) -> Dict[str, Any]:
    """What an accessory's GEOMETRY is made of (the metal is not)."""
    inputs: Dict[str, Any] = {"version": ACCESSORY_VERSION, "kind": spec["kind"]}
    if spec["kind"] == "necklace":
        inputs["chain"] = dict(spec["chain"])
    return inputs


def asig(spec: Dict[str, Any]) -> str:
    """md5[:12] of ``geometry_inputs`` (canonical JSON)."""
    raw = json.dumps(geometry_inputs(spec), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:12]


def record_path(character_name: str, item_id: str, sig: str, suffix: str = ".json") -> Path:
    return store_dir(character_name) / f"{item_id}_{sig}{suffix}"


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _records(character_name: str, item_id: str) -> Dict[str, Dict[str, Any]]:
    """asig -> record of every stored build of ``item_id`` (failure records excluded)."""
    folder = store_dir(character_name)
    out: Dict[str, Dict[str, Any]] = {}
    if not folder.is_dir():
        return out
    prefix = f"{item_id}_"
    for path in folder.glob(f"{item_id}_*.json"):
        name = path.name[len(prefix):-len(".json")]
        if "." in name or len(name) != 12:
            continue
        rec = _read(path)
        if rec and path.with_suffix(".npz").is_file():
            out[name] = rec
    return out


def material_key(item: Optional[Dict[str, Any]]) -> str:
    """The material identity of an accessory (``metal`` + colour + roughness): a change re-assembles, never rebuilds."""
    from app.core import accessory_spec
    spec = accessory_spec.of_item(item)
    if spec is None:
        return ""
    color, rough = accessory_spec.metal_material(spec)
    return f"accessory:{spec['metal']}:{color}:{rough}"


def _current_base(character_name: str, profile: Dict[str, Any]):
    from app.core import base_body
    base = base_body.current_base(character_name, profile=profile)
    if not base or not base[1]:
        return None
    return base


def base_sha(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The content sha of the current plain body ('' without one) — the preview's cache key (A216 review L2)."""
    base = _current_base(character_name, _profile_of(character_name, profile))
    return str(base[1]) if base else ""


def accessory_state(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
                    item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{state, reason, asig, record}`` of a worn accessory (module docstring). Read-only."""
    from app.core import accessory_spec, model_geometry
    profile = _profile_of(character_name, profile)
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    spec = accessory_spec.of_item(item)
    if spec is None:
        return {"state": "blocked", "reason": REASON_NO_KIND, "asig": "", "record": None}
    if spec["kind"] not in accessory_spec.BUILT_KINDS:
        return {"state": "blocked", "reason": REASON_KIND_LATER.format(kind=spec["kind"].capitalize()),
                "asig": "", "record": None}
    base = _current_base(character_name, profile)
    if base is None:
        return {"state": "blocked", "reason": REASON_NO_BODY, "asig": "", "record": None}
    sig = asig(spec)
    records = _records(character_name, item_id)
    rec = records.get(sig)
    if rec is not None and model_geometry.record_matches(rec, base[1]):
        return {"state": "current", "reason": "", "asig": sig, "record": rec}
    failed = _read(record_path(character_name, item_id, sig, ".failed.json"))
    if failed and failed.get("base_model_sha256") == base[1]:
        return {"state": "failed", "reason": REASON_FAILED.format(error=failed.get("error") or "unknown"),
                "asig": sig, "record": None}
    if rec is not None:
        return {"state": "due", "reason": REASON_BODY, "asig": sig, "record": None}
    if records:
        return {"state": "due", "reason": REASON_SETTINGS, "asig": sig, "record": None}
    return {"state": "due", "reason": REASON_NOT_BUILT, "asig": sig, "record": None}


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def make_necklace(rigged: bytes, spec: Dict[str, Any]) -> Dict[str, Any]:
    """The necklace geometry on the rigged plain body ``rigged`` (GLB bytes): ``{V, F, N, J, W, joint_names, curve,
    landmarks, metrics}``. Pure CPU, no I/O beyond the bytes given."""
    from app.core import accessory_curve, accessory_mesh, glb_mesh
    from app.core.garment_fit import dense_weights
    started = time.monotonic()
    body = glb_mesh.body_arrays(rigged)
    radius = float(spec["chain"]["thickness_mm"]) / 2000.0
    detail = accessory_curve.neck_curve_detail(body.positions, body.faces, body.joint_positions,
                                               drop_m=float(spec["chain"]["drop_cm"]) / 100.0,
                                               offset_m=GAP_M + radius)
    curve = np.asarray(detail["curve"])
    surface = np.asarray(detail["surface"])
    V, F, N = accessory_mesh.tube(curve, radius, outward=curve - surface)
    J, W = accessory_mesh.skin_weights(V, np.asarray(body.positions, np.float64), dense_weights(body))
    J, W = accessory_mesh.fold_to_base(J, W, list(body.joint_names), glb_mesh.skin_joint_parents(rigged))
    Pw, skin = detail["welded"]
    metrics = gap_metrics(V, len(curve), Pw, skin, outward=np.asarray(detail["outward"]))
    seg = np.linalg.norm(np.diff(np.vstack([curve, curve[:1]]), axis=0), axis=1)
    metrics.update({"triangles": int(len(F)), "vertices": int(len(V)),
                    "length_m": round(float(seg.sum()), 4),
                    "max_segment_ratio": round(float(seg.max() / max(float(np.median(seg)), 1e-9)), 2),
                    "neck_ellipse_m": detail["landmarks"]["neck_ellipse_m"],
                    "joints": {str(body.joint_names[j]): round(float(W[J == j].max()), 3)
                               for j in np.unique(J[W > PLAUSIBLE_WEIGHT])},
                    "cpu_s": round(time.monotonic() - started, 2)})
    plausible(metrics, float(spec["chain"]["drop_cm"]) / 100.0)
    return {"V": V, "F": F, "N": N, "J": J, "W": W, "joint_names": list(body.joint_names), "curve": curve,
            "landmarks": detail["landmarks"], "metrics": metrics}


#: The plausibility gate (A216 review H2) — a chain that misses one of these fails its build instead of being shown:
#: length at most ``LENGTH_PER_NECK`` × the neck ellipse (side points + notch + back, ``neck_ellipse_m``) +
#: ``LENGTH_PER_DROP`` × the drop (a U hanging the drop below the notch adds about twice the drop) and at least the
#: ellipse × ``LENGTH_MIN_PER_NECK``;
#: no segment longer than ``MAX_SEGMENT_RATIO`` × the median (a jump to hair or a shoulder); weight above
#: ``PLAUSIBLE_WEIGHT`` only on the neck, the spine and the shoulders (the head / jaw up to ``HEAD_WEIGHT_MAX``,
#: never an arm); nothing inside. ``metrics["joints"]``: joint -> its largest weight on the chain.
LENGTH_PER_NECK = 1.35
LENGTH_PER_DROP = 2.6
LENGTH_MIN_PER_NECK = 0.9
MAX_SEGMENT_RATIO = 3.0
PLAUSIBLE_WEIGHT = 0.2
PLAUSIBLE_JOINTS = frozenset({"neck", "spine", "spine1", "spine2", "leftshoulder", "rightshoulder"})
#: The head and the jaw may move a stretch of the chain by at most this weight: the skin just under the chin follows
#: the head a little (moving that weight to the neck pressed Lirien's chain to 0.85 mm in the sit clip), a chain
#: riding ON the jaw is wrong.
HEAD_WEIGHT_MAX = 0.5
HEAD_JOINTS = frozenset({"head", "jaw"})
IMPLAUSIBLE = "The chain does not fit this body ({why}) — it is left off"


def plausible(metrics: Dict[str, Any], drop_m: float) -> None:
    """Raise ``ValueError`` (``IMPLAUSIBLE``) when ``metrics`` of a built necklace break the gate above."""
    from app.core.rig_contract import norm_bone_name
    why = []
    neck = float(metrics["neck_ellipse_m"])
    length = float(metrics["length_m"])
    if length > LENGTH_PER_NECK * neck + LENGTH_PER_DROP * drop_m:
        why.append(f"{length:.2f} m long for a {neck:.2f} m neck")
    if length < LENGTH_MIN_PER_NECK * neck:
        why.append(f"{length:.2f} m is shorter than the {neck:.2f} m neck")
    if float(metrics["max_segment_ratio"]) > MAX_SEGMENT_RATIO:
        why.append("it jumps between two points")
    others = [j for j, w in metrics["joints"].items() if norm_bone_name(j) not in PLAUSIBLE_JOINTS
              and not (norm_bone_name(j) in HEAD_JOINTS and w <= HEAD_WEIGHT_MAX)]
    if others:
        why.append("it would move with " + ", ".join(norm_bone_name(j) for j in others))
    if float(metrics["inside_share"]) > 0.0:
        why.append("part of it lies inside the body")
    if why:
        raise ValueError(IMPLAUSIBLE.format(why="; ".join(why)))


def gap_metrics(V: np.ndarray, rings: int, P: np.ndarray, F: np.ndarray,
                outward: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """The tube's air to the skin: per ring (``rings`` rings of ``len(V) / rings`` vertices) the smallest signed
    distance of its vertices to the body ``(P, F)`` — p05 / p50 / p95 / min in mm — and the share of tube vertices
    more than 0.5 mm inside the skin (``inside_share``). ``outward`` (per ring, the skin's normal under it): ``F`` is
    the skin patch under the chain and the sign comes from that normal; else ``F`` is the whole closed body
    (``garment_shell.signed_distance``)."""
    if outward is None:
        from app.core.accessory_curve import weld
        from app.core.garment_shell import signed_distance
        Pw, Fw = weld(np.asarray(P, np.float64), np.asarray(F, np.int64))
        sd = signed_distance(np.asarray(V, np.float64), Pw, Fw)
    else:
        # The skin patch has no inside of its own: per ring its CENTRE's distance to the skin, signed by the ring's
        # outward normal, minus the tube radius (exact for a flat skin; a vertex's own closest point can sit on an
        # edge of a crease beside the chain, where a face's plane gives the wrong side).
        from scipy.spatial import cKDTree
        from app.core.accessory_curve import _closest
        Pf = np.asarray(P, np.float64)
        Fs = np.asarray(F, np.int64)
        X = np.asarray(V, np.float64).reshape(rings, -1, 3)
        centre = X.mean(1)
        radius = np.linalg.norm(X - centre[:, None], axis=2).mean(1)
        cp = _closest(centre, Pf, Fs, cKDTree(Pf[Fs].mean(1)))
        side = np.einsum("ij,ij->i", centre - cp, np.asarray(outward))
        sd = (np.linalg.norm(centre - cp, axis=1) * np.where(side < 0, -1.0, 1.0) - radius)[:, None]
    sd = sd.reshape(rings, -1)
    gap = sd.min(1) * 1000.0
    return {"gap_mm": {"p05": round(float(np.percentile(gap, 5)), 2), "p50": round(float(np.median(gap)), 2),
                       "p95": round(float(np.percentile(gap, 95)), 2), "min": round(float(gap.min()), 2)},
            "inside_share": round(float((sd < -0.0005).mean()), 4)}


def drop_other_builds(folder: Path, item_id: str, sig: str) -> List[str]:
    """Delete the files of ``item_id``'s builds other than ``sig`` in ``folder`` — names matching exactly
    ``^<item_id>_<12 hex>\.`` (A216 review L1: never another item whose id starts with this one); the deleted
    names."""
    own = re.compile(rf"^{re.escape(item_id)}_([0-9a-f]{{12}})\.")
    gone = []
    for other in sorted(folder.iterdir()):
        m = own.match(other.name)
        if m and m.group(1) != sig:
            other.unlink(missing_ok=True)
            gone.append(other.name)
    return gone


def failure_text(e: BaseException) -> str:
    """The words a failed build shows (A216 review L3): a missing bone named, a ``ValueError`` as it is, anything
    else with its type."""
    if isinstance(e, KeyError):
        return f"The plain body has no {str(e.args[0] if e.args else '').strip(chr(39))} bone"
    if isinstance(e, ValueError):
        return str(e)
    return f"{type(e).__name__}: {e}"


def build(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the accessory ``item_id`` of ``character_name`` on its current plain body (CPU, 0 hub jobs) and store
    it; returns ``accessory_state`` afterwards (+ ``metrics``). A blocked accessory is returned unbuilt; a build
    that raises writes the failure record and returns state ``failed``."""
    from app.core import figure, model_geometry
    from app.core.keyed_lock import keyed_lock
    from app.core.timeutils import utc_now_iso
    from app.models.inventory import get_item
    profile = _profile_of(character_name, profile)
    item = get_item(item_id) or {}
    state = accessory_state(character_name, item_id, profile=profile, item=item)
    if state["state"] == "blocked":
        return state
    from app.core import accessory_spec
    spec = accessory_spec.of_item(item)
    bsig, sha = _current_base(character_name, profile)
    sig = asig(spec)
    folder = store_dir(character_name)
    with keyed_lock("accessory_build", f"{character_name}/{item_id}"):
        folder.mkdir(parents=True, exist_ok=True)
        failed_path = record_path(character_name, item_id, sig, ".failed.json")
        try:
            from app.models.character import get_character_dir
            blob = (get_character_dir(character_name) / "model3d" / f"{bsig}.glb").read_bytes()
            made = make_necklace(blob, spec)
        except Exception as e:  # noqa: BLE001 — recorded as the step's failure, the figure leaves it off
            logger.exception("Accessory %s of %s failed", item_id, character_name)
            _write_atomic(failed_path, json.dumps({"error": failure_text(e)[:300], "base_model_sha256": sha,
                                                   "asig": sig, "at": utc_now_iso()}).encode("utf-8"))
            figure.invalidate()
            return accessory_state(character_name, item_id, profile=profile, item=item)
        import io
        buf = io.BytesIO()
        np.savez_compressed(buf, V=made["V"].astype(np.float32), F=made["F"].astype(np.int32),
                            N=made["N"].astype(np.float32), J=made["J"].astype(np.int32),
                            W=made["W"].astype(np.float32), curve=made["curve"].astype(np.float32))
        _write_atomic(record_path(character_name, item_id, sig, ".npz"), buf.getvalue())
        record = {"version": ACCESSORY_VERSION, "item_id": item_id, "asig": sig, "kind": spec["kind"],
                  "inputs": geometry_inputs(spec), "bsig": bsig, "base_model_sha256": sha,
                  **model_geometry.stamp_on(character_name, bsig, sha),
                  "joint_names": made["joint_names"], "landmarks": made["landmarks"], "metrics": made["metrics"],
                  "hub_jobs": 0, "built_at": utc_now_iso()}
        _write_atomic(record_path(character_name, item_id, sig), json.dumps(record, indent=1).encode("utf-8"))
        failed_path.unlink(missing_ok=True)
        # One build per item is kept: the other settings' builds go (a switch back rebuilds on the CPU).
        drop_other_builds(folder, item_id, sig)
    figure.invalidate()
    out = accessory_state(character_name, item_id, profile=profile, item=item)
    out["metrics"] = made["metrics"]
    return out


def garment_mesh(character_name: str, item_id: str, record: Dict[str, Any],
                 item: Optional[Dict[str, Any]] = None):
    """The stored build of ``record`` as a ``glb_mesh.GarmentMesh`` with the item's CURRENT metal."""
    from app.core import accessory_mesh, accessory_spec
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    spec = accessory_spec.of_item(item) or accessory_spec.normalize({"kind": record.get("kind") or "necklace"})
    color, rough = accessory_spec.metal_material(spec)
    with np.load(record_path(character_name, item_id, str(record["asig"]), ".npz")) as z:
        return accessory_mesh.garment_mesh(z["V"], z["F"], z["N"], z["J"], z["W"], list(record["joint_names"]),
                                           color=color, roughness=rough)


def npz_path(character_name: str, item_id: str, record: Dict[str, Any]) -> Path:
    return record_path(character_name, item_id, str(record["asig"]), ".npz")


def preview_glb(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[bytes]:
    """The plain rigged body with the current build grafted (the Wardrobe's 3D view); the plain body alone while the
    piece is not built (the live curve is drawn over it); None without a plain body."""
    from app.core import accessory_mesh, glb_mesh
    from app.models.character import get_character_dir
    profile = _profile_of(character_name, profile)
    base = _current_base(character_name, profile)
    if base is None:
        return None
    blob = (get_character_dir(character_name) / "model3d" / f"{base[0]}.glb").read_bytes()
    state = accessory_state(character_name, item_id, profile=profile)
    if state["state"] != "current":
        return blob
    mesh = garment_mesh(character_name, item_id, state["record"])
    return glb_mesh.graft(blob, mesh, name=accessory_mesh.node_name(item_id),
                          extras={"kind": "accessory", "item_id": item_id, "fsig": state["asig"]})


def preview_curve(character_name: str, item_id: str, *, drop_cm: float, thickness_mm: float,
                  profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The chain's centre line for other settings, without storing anything (the Wardrobe's live slider preview):
    ``{points: [[x, y, z]…], landmarks}`` on the current plain body. CPU only."""
    from app.core import accessory_curve, glb_mesh
    from app.models.character import get_character_dir
    profile = _profile_of(character_name, profile)
    base = _current_base(character_name, profile)
    if base is None:
        raise ValueError(REASON_NO_BODY)
    body = glb_mesh.body_arrays((get_character_dir(character_name) / "model3d" / f"{base[0]}.glb").read_bytes())
    radius = max(float(thickness_mm), 0.5) / 2000.0
    detail = accessory_curve.neck_curve_detail(body.positions, body.faces, body.joint_positions,
                                               drop_m=float(drop_cm) / 100.0, offset_m=GAP_M + radius,
                                               n=48, settle=False)
    return {"points": np.round(np.asarray(detail["curve"]), 5).tolist(), "landmarks": detail["landmarks"],
            "radius_m": radius}
