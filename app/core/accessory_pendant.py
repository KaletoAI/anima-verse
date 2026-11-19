"""The pendant of a necklace (Ruling A118 phase P2, A225; spec ``docs/superpowers/specs/2026-11-16-accessories-design.md``
§ 3 option D, § 4): ONE img2mesh job per ITEM, shared by every wearer.

The item image is cut out (the footwear cut-out step: BiRefNet-DIS, square crop), then meshed through the routed
occasion ``MESH_OCCASION`` (``get_image_service().generate_mesh`` — the routed, queued channel path, never a backend
directly). The delivered mesh is gated (``mesh_gates``: one connected piece, a plausible shape) and kept as it came;
the size (``size_mm``, the longest side) and the placement are applied per character on the CPU
(``accessory_build``), so a size change never spends a job.

The job is spent ONLY by an explicit user action: "Build pendant (1 hub job)" in the Wardrobe or a manual Build of the
character when the pendant is switched on (``figure_build``'s ``pendant`` step is ``manual``). A refused or failed
mesh is never meshed again automatically (one paid try; the Wardrobe offers "Build pendant again").

Store (world-wide, per item)::

    <world>/jewellery/<item>/<psig>/cutout.png    the cut-out the mesher got
    <world>/jewellery/<item>/<psig>/raw.glb       the delivered mesh
    <world>/jewellery/<item>/<psig>/record.json   {accepted, gates, backend, routing (+ fallback_from), ...}

``psig`` = md5[:12] over ``{image sha256, PENDANT_VERSION}`` — a new item image is a new pendant. Accepting a psig
removes the other psig folders of THAT item (exact 12-hex names only, A216 review L1).

Placement (``place``): the mesh is read with +Y up and its front (the image) toward +Z, centred, scaled so its longest
side is ``size_mm`` and hung with its top centre at the chain's lowest point, its back on the chain's centre line;
then tilted about that point in the sagittal plane (``TILT_DEG``) and pushed out along the skin normal so the whole
mesh is at least ``GAP_M`` off the body — the least push first (it stays on its cord), then the flattest tilt. It is rigid: every vertex takes the chain's skin at that point.
``pose_check`` then poses body and pendant through ``TEST_POSES`` (rest / walk / sit / run, linear blend skinning on
the CPU) and reports the pendant's smallest gap per pose; a pendant inside the body in any pose is left off.
"""
import hashlib
import io
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("accessory_pendant")

#: Bumped when the pendant job produces something else for the same image (part of ``psig``).
PENDANT_VERSION = 1
MESH_OCCASION = "jewellery_mesh"
#: What the mesher is asked for — a pendant is a small object.
FACE_NUM = 20000
#: The pendant's air to the skin (or the clothing painted on it) — "a few mm".
GAP_M = 0.003
#: Tilts tried about the hanging point, degrees (positive: the bottom moves away from the body).
TILT_DEG = tuple(range(-30, 61, 2))
#: The mesh gates: the largest connected piece (with what lies inside its box) carries at least this area share;
#: the longest side at most this many times the shortest (a needle or a sheet is no pendant); at least this many
#: triangles.
MIN_COMPONENT_SHARE = 0.9
MAX_ASPECT = 20.0
MIN_TRIANGLES = 12
#: Tilts whose push is within this of the least push count as equal; the flattest of them wins.
PUSH_SLACK_M = 0.0005
#: Push steps of ``place`` when no tilt keeps the gap.
PUSH_PASSES = 8
#: A posed pendant vertex deeper than this below the skin counts as inside (the chain's 0.5 mm rule).
INSIDE_M = 0.0005

#: Words shown in the Wardrobe and the Figure row.
REASON_NO_IMAGE = "The item has no image to make the pendant from"
REASON_MISSING = "Pendant not built yet — Build pendant spends 1 hub job"
REASON_RUNNING = "Pendant is being built (1 hub job)"
REASON_REFUSED = "Pendant mesh refused — {error}; the chain is shown without it"
REASON_FAILED = "Pendant job failed — {error}; the chain is shown without it"
REASON_LOAD = "Pendant job could not start ({error}) — try again later"
REASON_LEFT_OFF = "Pendant left off — {error}"

_PSIG_RE = re.compile(r"^[0-9a-f]{12}$")
_RUNNING: set = set()
_RUNNING_LOCK = threading.Lock()


# --- store ------------------------------------------------------------------------------------------------------------

def root() -> Path:
    from app.core import paths
    return paths.get_storage_dir() / "jewellery"


def item_dir(item_id: str) -> Path:
    """``<world>/jewellery/<item>``; ValueError for an unsafe id. Never creates the folder."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid:
        raise ValueError(f"invalid item id {str(item_id)[:80]!r}")
    base = root().resolve()
    if (base / iid).resolve().parent != base:
        raise ValueError(f"item folder outside the jewellery store: {iid!r}")
    return root() / iid


def _item_image(item_id: str) -> Optional[Path]:
    from app.models.inventory import get_item_image_path
    path = get_item_image_path(item_id)
    return Path(path) if path and Path(path).is_file() else None


def psig_for(image_sha256: str) -> str:
    raw = json.dumps({"image": image_sha256, "version": PENDANT_VERSION}, sort_keys=True).encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:12]


_SHA_CACHE: Dict[Tuple[str, int, int], str] = {}


def current_psig(item_id: str) -> str:
    """The psig of the item image as it is NOW; '' without an image. The image hash is cached by path + mtime +
    size (the state is read on every figure plan and assembly)."""
    image = _item_image(item_id)
    if image is None:
        return ""
    st = image.stat()
    key = (str(image), st.st_mtime_ns, st.st_size)
    sha = _SHA_CACHE.get(key)
    if sha is None:
        sha = hashlib.sha256(image.read_bytes()).hexdigest()
        if len(_SHA_CACHE) > 512:
            _SHA_CACHE.clear()
        _SHA_CACHE[key] = sha
    return psig_for(sha)


def pendant_dir(item_id: str, psig: str) -> Path:
    if not _PSIG_RE.match(str(psig or "")):
        raise ValueError(f"invalid pendant signature {str(psig)[:40]!r}")
    return item_dir(item_id) / psig


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def drop_other_pendants(item_id: str, psig: str) -> List[str]:
    """Remove the item's pendant folders other than ``psig`` — exact 12-hex names only (A216 review L1); their names."""
    folder = item_dir(item_id)
    gone = []
    if not folder.is_dir():
        return gone
    for other in sorted(folder.iterdir()):
        if other.is_dir() and _PSIG_RE.match(other.name) and other.name != psig:
            shutil.rmtree(other, ignore_errors=True)
            gone.append(other.name)
    return gone


# --- state ------------------------------------------------------------------------------------------------------------

def is_running(item_id: str) -> bool:
    with _RUNNING_LOCK:
        return item_id in _RUNNING


def pendant_state(item_id: str) -> Dict[str, Any]:
    """``{state, reason, psig, record}`` of the item's pendant mesh (read-only): ``ready`` (accepted, raw.glb on disk),
    ``running``, ``missing`` (never built for this image, or the last try met load — retry), ``refused`` (the gates
    refused the delivery), ``failed`` (the backend failed), ``no_image``. Neither refused nor failed is ever retried
    automatically."""
    psig = current_psig(item_id)
    if not psig:
        return {"state": "no_image", "reason": REASON_NO_IMAGE, "psig": "", "record": None}
    if is_running(item_id):
        return {"state": "running", "reason": REASON_RUNNING, "psig": psig, "record": None}
    d = pendant_dir(item_id, psig)
    rec = _read(d / "record.json")
    if rec.get("accepted") is True and (d / "raw.glb").is_file():
        return {"state": "ready", "reason": "", "psig": psig, "record": rec}
    if rec.get("accepted") is False:
        failure = str(rec.get("failure") or "gate")
        error = str(rec.get("error") or "unknown")
        if failure == "load":
            return {"state": "missing", "reason": REASON_LOAD.format(error=error), "psig": psig, "record": rec}
        if failure == "gate":
            return {"state": "refused", "reason": REASON_REFUSED.format(error=error), "psig": psig, "record": rec}
        return {"state": "failed", "reason": REASON_FAILED.format(error=error), "psig": psig, "record": rec}
    return {"state": "missing", "reason": REASON_MISSING, "psig": psig, "record": None}


# --- the job ----------------------------------------------------------------------------------------------------------

#: Square crop around the pendant in the cut-out (the footwear cut-out's padding and alpha floor).
CUTOUT_PAD = 1.15
CUTOUT_ALPHA_MIN = 16
CUTOUT_MIN_SIDE = 1024


def cut_out(image_bytes: bytes) -> bytes:
    """The item image cut out (BiRefNet-DIS, local — no hub job) and cropped to a square around the pendant, PNG;
    ValueError when nothing is left."""
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    with Image.open(io.BytesIO(run_rembg(image_bytes, MESH_INPUT_REMBG_MODEL))) as im:
        cut = im.convert("RGBA")
    box = cut.getchannel("A").point(lambda v: 255 if v > CUTOUT_ALPHA_MIN else 0).getbbox()
    if box is None:
        raise ValueError("no pendant found in the item image")
    x0, y0, x1, y1 = box
    side = int(CUTOUT_PAD * max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    out = cut.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side))
    if side < CUTOUT_MIN_SIDE:
        out = out.resize((CUTOUT_MIN_SIDE, CUTOUT_MIN_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def mesh_gates(positions: np.ndarray, faces: np.ndarray) -> Tuple[bool, List[str], Dict[str, Any]]:
    """``(ok, reasons, numbers)`` of a delivered pendant mesh (module docstring)."""
    from app.core.footwear_gates import component_shares
    P = np.asarray(positions, np.float64)
    F = np.asarray(faces, np.int64)
    reasons: List[str] = []
    ext = (P.max(0) - P.min(0)) if len(P) else np.zeros(3)
    longest, shortest = float(ext.max()), float(ext.min())
    aspect = longest / shortest if shortest > 0 else float("inf")
    _largest, enclosed = component_shares(P, F) if len(F) else (0.0, 0.0)
    if len(F) < MIN_TRIANGLES:
        reasons.append(f"only {len(F)} triangles")
    if enclosed < MIN_COMPONENT_SHARE:
        reasons.append(f"it falls apart into pieces (main piece {enclosed:.2f} of the surface)")
    if aspect > MAX_ASPECT:
        reasons.append("it is a needle or a sheet, not a pendant" if np.isfinite(aspect) else "it is flat")
    numbers = {"triangles": int(len(F)), "component_share": round(float(enclosed), 4),
               "aspect": round(aspect, 2) if np.isfinite(aspect) else None,
               "extent": [round(float(x), 5) for x in ext]}
    return not reasons, reasons, numbers


def _failure_of(e: BaseException) -> Tuple[str, str]:
    from app.core.footwear_source import failure_of
    return failure_of(e)


def run(item_id: str) -> Dict[str, Any]:
    """The pendant job of ``item_id`` (explicit callers only — module docstring): cut-out, ONE routed
    ``MESH_OCCASION`` job, gates. A ready pendant is returned as it is (no job). Returns ``pendant_state``."""
    with _RUNNING_LOCK:
        _RUNNING.add(item_id)
    try:
        _run(item_id)
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(item_id)
    from app.core import figure
    figure.invalidate()
    return pendant_state(item_id)


def _run(item_id: str) -> None:
    from app.core.keyed_lock import keyed_lock
    from app.core.timeutils import utc_now_iso
    with keyed_lock("jewellery_pendant", item_id):
        psig = current_psig(item_id)
        if not psig:
            return
        d = pendant_dir(item_id, psig)
        prior = _read(d / "record.json")
        if prior.get("accepted") is True and (d / "raw.glb").is_file():
            return
        d.mkdir(parents=True, exist_ok=True)
        image = _item_image(item_id)
        record: Dict[str, Any] = {"psig": psig, "version": PENDANT_VERSION, "created_at": utc_now_iso(),
                                  "occasion": MESH_OCCASION, "hub_jobs": 0}
        try:
            _write(d / "cutout.png", cut_out(image.read_bytes()))
        except Exception as e:  # noqa: BLE001 — a cut-out that finds nothing is a refusal, no job spent
            _write(d / "record.json", json.dumps({**record, "accepted": False, "failure": "gate",
                                                  "error": str(e) or type(e).__name__}).encode("utf-8"))
            return
        raw = d / "raw.glb"
        res: Dict[str, Any] = {}
        try:
            from app.imagegen.service import get_image_service
            record["hub_jobs"] = 1
            res = get_image_service().generate_mesh(
                source_image_path=str(d / "cutout.png"), output_path=str(raw), occasion=MESH_OCCASION,
                mesh_name=f"pendant-{item_id}", face_num=FACE_NUM, alpha="opaque")
            if not res.get("ok"):
                raise RuntimeError(f"pendant mesh generation failed: {res.get('error') or 'unknown error'}")
            delivered = Path(str(res.get("path") or ""))
            if delivered.suffix.lower() != ".glb" or not delivered.is_file():
                raise RuntimeError(f"pendant mesh generation delivered no GLB ({delivered.name or 'nothing'})")
            if delivered != raw:
                os.replace(delivered, raw)
            from app.core import glb_mesh
            P, F = glb_mesh.static_arrays(raw.read_bytes())[:2]
            ok, reasons, numbers = mesh_gates(P, F)
        except Exception as e:  # noqa: BLE001 — recorded; the chain is shown without the pendant
            failure, error = _failure_of(e)
            if failure == "load":
                record["hub_jobs"] = 0
            logger.warning("Pendant %s/%s: %s (%s)", item_id, psig, error, failure)
            raw.unlink(missing_ok=True)
            _write(d / "record.json", json.dumps({**record, "accepted": False, "failure": failure,
                                                  "error": error[:300]}).encode("utf-8"))
            return
        routed = {"backend": res.get("backend", ""), "routing": res.get("routing") or {},
                  **({"fallback_from": res["fallback_from"]} if res.get("fallback_from") else {})}
        record.update({"accepted": ok, "gates": {"ok": ok, "reasons": reasons, **numbers}, **routed})
        if not ok:
            record.update({"failure": "gate", "error": "; ".join(reasons)})
        _write(d / "record.json", json.dumps(record, indent=1).encode("utf-8"))
        if ok:
            drop_other_pendants(item_id, psig)
        logger.info("Pendant %s/%s %s: %s", item_id, psig, "accepted" if ok else "refused", numbers)


def start(item_id: str) -> bool:
    """Run the pendant job in a background thread; False when one is already running for the item."""
    if is_running(item_id):
        return False

    def work() -> None:
        try:
            run(item_id)
        except Exception:  # noqa: BLE001 — logged; the state reads the record
            logger.exception("Pendant job of %s failed", item_id)
    with _RUNNING_LOCK:
        _RUNNING.add(item_id)   # visible as "running" before the thread starts; ``run`` clears it at the end
    threading.Thread(target=work, name=f"pendant-{item_id}", daemon=True).start()
    return True


# --- geometry (pure, CPU) ---------------------------------------------------------------------------------------------

def load_mesh(item_id: str, psig: str) -> Dict[str, Any]:
    """The ready pendant's delivered mesh: ``{V, F, UV, image, mime, material}`` (positions as delivered)."""
    from app.core import glb_mesh
    P, F, U, image, mime, material = glb_mesh.static_arrays((pendant_dir(item_id, psig) / "raw.glb").read_bytes())
    return {"V": P, "F": F, "UV": U, "image": image, "mime": mime, "material": material}


def normalise(V: np.ndarray, size_mm: float) -> np.ndarray:
    """``V`` (+Y up, front +Z) centred in x and z, its top at y = 0, its back at z = 0 and scaled so the longest side
    of its box is ``size_mm`` (module docstring)."""
    V = np.asarray(V, np.float64)
    lo, hi = V.min(0), V.max(0)
    scale = (float(size_mm) / 1000.0) / max(float((hi - lo).max()), 1e-12)
    out = (V - np.array([(lo[0] + hi[0]) / 2, hi[1], lo[2]])) * scale
    return out


def _rot_y(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_x(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def place(Vn: np.ndarray, anchor: np.ndarray, outward: np.ndarray, Pb: np.ndarray, Fb: np.ndarray,
          gap_m: float = GAP_M) -> Tuple[np.ndarray, Dict[str, Any]]:
    """The normalised pendant ``Vn`` hung at ``anchor`` (module docstring): turned about +Y so its front faces the
    horizontal part of ``outward``; per tilt of ``TILT_DEG`` the push along ``outward`` that gives the closed body
    ``(Pb, Fb)`` at least ``gap_m`` (``gap_m`` − the smallest signed distance, ≥ 0); the tilts with the least push
    (within ``PUSH_SLACK_M`` — the pendant stays on its cord) and of those the smallest median distance once pushed
    (it lies flattest on the body; ties: the first) wins. ``(V, {tilt_deg, push_mm, gap_mm, rotation})`` — ``rotation`` the
    3×3 that took ``Vn`` into place."""
    from app.core.garment_shell import signed_distance
    anchor = np.asarray(anchor, np.float64)
    h = np.array([outward[0], 0.0, outward[2]], np.float64)
    h = h / max(float(np.linalg.norm(h)), 1e-12) if np.linalg.norm(h) > 1e-9 else np.array([0.0, 0.0, 1.0])
    yaw = _rot_y(float(np.arctan2(h[0], h[2])))
    n = np.asarray(outward, np.float64)
    n = n / max(float(np.linalg.norm(n)), 1e-12)
    tried = []
    for deg in TILT_DEG:
        # A positive rotation about +x would swing the hanging (−y) part toward −z (into the body): the angle is
        # negated so a positive tilt swings the bottom away from the body.
        R = yaw @ _rot_x(-np.radians(deg))
        sd = signed_distance(Vn @ R.T + anchor, Pb, Fb)
        push = max(0.0, gap_m - float(sd.min()))
        tried.append((push, float(np.median(sd)) + push, deg, R))
    # The pendant stays on its cord: the least push first (within ``PUSH_SLACK_M``), then the flattest (the median
    # distance once pushed).
    least = min(t[0] for t in tried)
    push, _median, deg, R = min((t for t in tried if t[0] <= least + PUSH_SLACK_M), key=lambda t: t[1])
    V = Vn @ R.T + anchor + n * push
    d = float(signed_distance(V, Pb, Fb).min())
    # The nearest skin point changes as it moves out: a few more steps until the gap holds.
    for _ in range(PUSH_PASSES):
        if d >= gap_m - 1e-5:
            break
        step = gap_m - d + 1e-4
        V = V + n * step
        push += step
        d = float(signed_distance(V, Pb, Fb).min())
    return V, {"tilt_deg": int(deg), "push_mm": round(push * 1000, 2), "gap_mm": round(d * 1000, 2),
               "rotation": R}


#: The CPU test poses: normalised joint name -> (axis, degrees) about the joint's head in bind space (+Z front,
#: +X = the body's left). A positive x rotation leans what is above forward.
TEST_POSES: Dict[str, Dict[str, Tuple[str, float]]] = {
    "rest": {},
    "walk": {"spine": ("y", 8.0), "spine2": ("y", -4.0), "leftarm": ("x", 25.0), "rightarm": ("x", -25.0),
             "neck": ("x", 5.0)},
    "sit": {"spine": ("x", 12.0), "spine1": ("x", 8.0), "spine2": ("x", 6.0), "neck": ("x", 15.0),
            "head": ("x", 12.0), "leftupleg": ("x", -90.0), "rightupleg": ("x", -90.0)},
    "run": {"spine": ("x", 10.0), "spine1": ("x", 6.0), "spine2": ("y", 8.0), "neck": ("x", -8.0),
            "leftarm": ("x", 55.0), "rightarm": ("x", -55.0), "leftforearm": ("x", 70.0),
            "rightforearm": ("x", 70.0)},
}


def _axis_rot(axis: str, deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def joint_transforms(joint_names: List[str], parents: Dict[str, str], heads: Dict[str, np.ndarray],
                     pose: Dict[str, Tuple[str, float]]) -> np.ndarray:
    """``(joints, 4, 4)`` world transforms in bind space of ``pose``: each joint's own rotation about its head,
    composed down the hierarchy (``parents``: joint name -> parent name)."""
    from app.core.rig_contract import norm_bone_name
    by_name = {str(n): i for i, n in enumerate(joint_names)}
    out: Dict[int, np.ndarray] = {}

    def world(i: int, seen=()) -> np.ndarray:
        if i in out:
            return out[i]
        name = str(joint_names[i])
        key = norm_bone_name(name)
        local = np.eye(4)
        if key in pose and key in heads:
            axis, deg = pose[key]
            h = np.asarray(heads[key], np.float64)
            R = _axis_rot(axis, deg)
            local[:3, :3] = R
            local[:3, 3] = h - R @ h
        parent = parents.get(name)
        M = local
        if parent in by_name and by_name[parent] not in seen:
            M = world(by_name[parent], seen + (i,)) @ local
        out[i] = M
        return M
    return np.stack([world(i) for i in range(len(joint_names))]) if joint_names else np.zeros((0, 4, 4))


def skin(X: np.ndarray, J: np.ndarray, W: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Linear blend skinning of ``X`` with ``(J, W)`` (n, 4) under the joint transforms ``M``."""
    Xh = np.c_[np.asarray(X, np.float64), np.ones(len(X))]
    out = np.zeros((len(X), 3))
    for k in range(J.shape[1]):
        T = M[J[:, k]]
        out += W[:, k:k + 1] * np.einsum("nij,nj->ni", T, Xh)[:, :3]
    return out


def pose_check(Pb: np.ndarray, Fb: np.ndarray, Jb: np.ndarray, Wb: np.ndarray, V: np.ndarray, Jp: np.ndarray,
               Wp: np.ndarray, joint_names: List[str], parents: Dict[str, str],
               heads: Dict[str, np.ndarray], kq: int = 12) -> Dict[str, Dict[str, float]]:
    """Per ``TEST_POSES`` pose: ``{gap_min_mm, gap_p50_mm, inside_share}`` of the pendant ``V`` (skinned ``Jp/Wp``)
    against the body ``(Pb, Fb)`` (skinned ``Jb/Wb``, closed). ``kq``: the candidate faces per point of
    ``garment_shell.signed_distance`` (A234: the long thin faces round an ankle need more than 12)."""
    from app.core.garment_shell import signed_distance
    out: Dict[str, Dict[str, float]] = {}
    for name, pose in TEST_POSES.items():
        M = joint_transforms(joint_names, parents, heads, pose)
        Pp = skin(Pb, Jb, Wb, M)
        Vp = skin(V, Jp, Wp, M)
        sd = signed_distance(Vp, Pp, Fb, kq=kq)
        out[name] = {"gap_min_mm": round(float(sd.min()) * 1000, 2), "gap_p50_mm": round(float(np.median(sd)) * 1000, 2),
                     "inside_share": round(float((sd < -INSIDE_M).mean()), 4)}
    return out
