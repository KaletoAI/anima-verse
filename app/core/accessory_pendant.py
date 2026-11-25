"""The pendant of a necklace (Ruling A118 phase P2, A225; spec ``docs/superpowers/specs/2026-11-16-accessories-design.md``
§ 3 option D, § 4): ONE img2mesh job per ITEM, shared by every wearer.

The item image is cut out (the footwear cut-out step: BiRefNet-DIS, square crop), then meshed through the routed
occasion ``MESH_OCCASION`` (``get_image_service().generate_mesh`` — the routed, queued channel path, never a backend
directly). The delivered mesh is gated (``mesh_gates``: one piece — shells that meet count as one, ``piece_share`` —, a plausible shape) and kept as it came;
the size (``size_mm``, the longer front side) and the placement are applied per character on the CPU
(``accessory_build``), so a size change never spends a job.

The job is spent ONLY by an explicit user action: "Build mesh (1 hub job)" in Items or the Wardrobe, or a manual Build
of the character (``figure_build``'s ``pendant`` step is ``manual``). A refused or failed mesh is never meshed again
automatically (one try per image). Besides ``mesh_gates`` the delivery must show its image: some turn of it has the
cut-out's width : height (``front_reason``) — else it would hang twisted on every wearer.

Store (world-wide, per item)::

    <world>/jewellery/<item>/<psig>/cutout.png    the cut-out the mesher got
    <world>/jewellery/<item>/<psig>/raw.glb       the delivered mesh
    <world>/jewellery/<item>/<psig>/record.json   {accepted, gates, backend, routing (+ fallback_from), ...}

``psig`` = md5[:12] over ``{image sha256, PENDANT_VERSION}`` — a new item image is a new pendant. Accepting a psig
removes the other psig folders of THAT item (exact 12-hex names only, A216 review L1).

Placement (``place``): the mesh is read with +Y up and its front (the image) toward +Z (``orient``: the depth axis is
the one whose two others match the image's outline), centred, scaled so its longer front side is ``size_mm`` and hung with its top centre at the chain's lowest point, its back on the chain's centre line;
then tilted about that point in the sagittal plane (``TILT_DEG``) and pushed out along the skin normal so the whole
mesh is at least ``GAP_M`` off the body — the least push first (it stays on its cord), then the flattest tilt. It is rigid: every vertex takes the chain's skin at that point.
A necklace's pendant with an eyelet the cord fits through (``eyelet``) hangs threaded instead (``threaded_place``): the eyelet centre on the cord, ``THREAD_GAP_M`` off the body, the cord lifted where the eyelet holds it off the skin (``accessory_build.lift_cord``); the placement above is kept when a test pose would put the threaded pendant into the body.
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
#: Bumped when the gates judge a delivered mesh differently (never part of ``psig``: the mesh stays). A record refused
#: by the gates of another version with its ``raw.glb`` kept is judged again, without a job, the next time its state
#: is read (``regate``). 2: shells that meet count as one piece (``piece_share``).
GATE_VERSION = 2
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
#: ``piece_share``: pieces whose vertices come within this share of the mesh's longest side count as one piece. A
#: mesher delivers jewellery as shells that meet without shared vertices (the disc in its rim, the bail through its
#: jump ring — 0.2 % of the size apart on the real UniForge pendant of 2026-11-25); a loose piece stands further off.
JOIN_SHARE = 0.01
MAX_ASPECT = 20.0
MIN_TRIANGLES = 12
#: Tilts whose push is within this of the least push count as equal; the flattest of them wins.
PUSH_SLACK_M = 0.0005
#: Push steps of ``place`` when no tilt keeps the gap.
PUSH_PASSES = 8
#: A posed pendant vertex deeper than this below the skin counts as inside (the chain's 0.5 mm rule).
INSIDE_M = 0.0005

#: Words shown in the Wardrobe and the Figure row.
#: Role-neutral: the same mesh store serves a necklace's pendant, a belt's buckle and charms and the earrings' drop, so
#: no text names a chain or a pendant (the hosts add their own role words, ``accessory_parts.part_states``).
REASON_NO_IMAGE = "The item has no image to make the part mesh from"
REASON_MISSING = "Part mesh not built yet — Build mesh spends 1 hub job"
REASON_RUNNING = "Part mesh is being built (1 hub job)"
REASON_REFUSED = "Part mesh refused — {error}; shown without it"
REASON_FAILED = "Part mesh job failed — {error}; shown without it"
REASON_LOAD = "Part mesh job could not start ({error}) — try again later"
REASON_LEFT_OFF = "Part left off — {error}"
#: ``front_reason``: no turn of the mesh shows the outline of its image.
REASON_FRONT = "its outline does not match the image (width : height {mesh:.2f} on the mesh, {image:.2f} in the image)"

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
    """``{state, reason, psig, record}`` of the item's pendant mesh (read-only, but for ``regate``: a gate refusal of
    another ``GATE_VERSION`` is judged again first, once, without a job): ``ready`` (accepted, raw.glb on disk),
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
    if (rec.get("accepted") is False and rec.get("gate_version") != GATE_VERSION
            and str(rec.get("failure") or "gate") == "gate" and regate(item_id, psig)):
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


def piece_share(positions: np.ndarray, faces: np.ndarray) -> float:
    """The area share of the main piece of a mesh: its edge-connected components (after ``garment_fit.weld``) joined
    when a vertex of one lies within ``JOIN_SHARE`` of the longest side of a vertex of the other; the largest group
    plus every group whose box lies inside its box (``footwear_gates.component_shares``' rule). 0.0 without faces."""
    from scipy.spatial import cKDTree
    from app.core.garment_fit import components, weld
    Pw, Fw, _ = weld(positions, faces)
    if len(Fw) == 0:
        return 0.0
    labels, share = components(Pw, Fw)
    n = len(share)
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i
    reach = JOIN_SHARE * float(np.ptp(Pw, 0).max())
    if n > 1 and reach > 0:
        pairs = cKDTree(Pw).query_pairs(reach, output_type="ndarray")
        pairs = pairs[labels[pairs[:, 0]] != labels[pairs[:, 1]]]
        for a, b in np.unique(np.sort(labels[pairs], axis=1), axis=0):
            ra, rb = find(int(a)), find(int(b))
            if ra != rb:
                parent[ra] = rb
    root_of = np.array([find(i) for i in range(n)])
    group = root_of[labels]
    gshare = np.zeros(n)
    np.add.at(gshare, root_of, share)
    lo = np.full((n, 3), np.inf)
    hi = np.full((n, 3), -np.inf)
    np.minimum.at(lo, group, Pw)
    np.maximum.at(hi, group, Pw)
    best = int(np.argmax(gshare))
    eps = 1e-9 * max(1.0, float(np.linalg.norm(hi[best] - lo[best])))
    inside = np.all(lo >= lo[best] - eps, axis=1) & np.all(hi <= hi[best] + eps, axis=1)
    return float(gshare[inside].sum())


def mesh_gates(positions: np.ndarray, faces: np.ndarray) -> Tuple[bool, List[str], Dict[str, Any]]:
    """``(ok, reasons, numbers)`` of a delivered pendant mesh (module docstring)."""
    P = np.asarray(positions, np.float64)
    F = np.asarray(faces, np.int64)
    reasons: List[str] = []
    ext = (P.max(0) - P.min(0)) if len(P) else np.zeros(3)
    longest, shortest = float(ext.max()), float(ext.min())
    aspect = longest / shortest if shortest > 0 else float("inf")
    enclosed = piece_share(P, F) if len(F) else 0.0
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
            ok, reasons, numbers = judge(d)
        except Exception as e:  # noqa: BLE001 — recorded; the host is shown without the part
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
        record.update({"accepted": ok, "gates": {"ok": ok, "reasons": reasons, **numbers}, "gate_version": GATE_VERSION,
                       **routed})
        if not ok:
            record.update({"failure": "gate", "error": "; ".join(reasons)})
        _write(d / "record.json", json.dumps(record, indent=1).encode("utf-8"))
        if ok:
            drop_other_pendants(item_id, psig)
        logger.info("Pendant %s/%s %s: %s", item_id, psig, "accepted" if ok else "refused", numbers)


def judge(d: Path) -> Tuple[bool, List[str], Dict[str, Any]]:
    """The gates on the delivered ``raw.glb`` of the pendant folder ``d``: ``mesh_gates`` and the outline against the
    cut-out (``front_reason`` — a mesh no turn of which has the cut-out's outline would hang twisted)."""
    from app.core import glb_mesh
    P, F = glb_mesh.static_arrays((d / "raw.glb").read_bytes())[:2]
    ok, reasons, numbers = mesh_gates(P, F)
    cut = d / "cutout.png"
    ratio = image_front_ratio(cut.read_bytes()) if cut.is_file() else None
    numbers["image_ratio"] = round(ratio, 3) if ratio else None
    outline = front_reason(P, ratio)
    if outline:
        ok = False
        reasons.append(outline)
    return ok, reasons, numbers


def regate(item_id: str, psig: str) -> bool:
    """A record refused by the gates of another ``GATE_VERSION`` whose ``raw.glb`` is kept, judged again (``judge``)
    without a job and rewritten (accepted or refused, with this ``gate_version``); an accepted one drops the item's
    other pendant folders. True when the record was rewritten. Any other record is left alone."""
    from app.core.keyed_lock import keyed_lock
    d = pendant_dir(item_id, psig)
    with keyed_lock("jewellery_pendant", item_id):
        rec = _read(d / "record.json")
        if (rec.get("accepted") is not False or str(rec.get("failure") or "gate") != "gate"
                or rec.get("gate_version") == GATE_VERSION or not (d / "raw.glb").is_file()):
            return False
        try:
            ok, reasons, numbers = judge(d)
        except Exception as e:  # noqa: BLE001 — an unreadable mesh stays refused, judged once
            ok, reasons, numbers = False, [f"the mesh could not be read ({type(e).__name__})"], {}
        new = {k: v for k, v in rec.items() if k not in ("failure", "error")}
        new.update({"accepted": ok, "gates": {"ok": ok, "reasons": reasons, **numbers}, "gate_version": GATE_VERSION})
        if not ok:
            new.update({"failure": "gate", "error": "; ".join(reasons)})
        _write(d / "record.json", json.dumps(new, indent=1).encode("utf-8"))
    logger.info("Pendant %s/%s judged again by gate version %d: %s", item_id, psig, GATE_VERSION,
                "accepted" if ok else "refused")
    if ok:
        drop_other_pendants(item_id, psig)
    from app.core import figure
    figure.invalidate()
    return True


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
    """The ready pendant's delivered mesh: ``{V, F, UV, image, mime, material, front_ratio}`` (positions as delivered;
    ``front_ratio`` = ``image_front_ratio`` of the cut-out the mesher got, None without one)."""
    from app.core import glb_mesh
    d = pendant_dir(item_id, psig)
    P, F, U, image, mime, material = glb_mesh.static_arrays((d / "raw.glb").read_bytes())
    cut = d / "cutout.png"
    ratio = image_front_ratio(cut.read_bytes()) if cut.is_file() else None
    return {"V": P, "F": F, "UV": U, "image": image, "mime": mime, "material": material, "front_ratio": ratio}


def image_front_ratio(png: bytes) -> Optional[float]:
    """Width : height of what the cut-out shows (the box of its alpha above ``CUTOUT_ALPHA_MIN``); None when it shows
    nothing or cannot be read."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(png)) as im:
            box = im.convert("RGBA").getchannel("A").point(lambda v: 255 if v > CUTOUT_ALPHA_MIN else 0).getbbox()
    except Exception:  # noqa: BLE001 — an unreadable cut-out has no outline to compare
        return None
    if box is None or box[3] <= box[1] or box[2] <= box[0]:
        return None
    return (box[2] - box[0]) / (box[3] - box[1])


#: ``orient_thin_to_depth``: z stays the depth while its extent is within this share of the thinnest side (a nearly
#: as thin x or y never tips the part over).
THIN_TIE = 0.10
#: ``orient``: the turned box's front (width : height) may differ from the image's by at most this factor
#: (``front_reason``). A mesher keeps the outline it was shown; what it invents (a loop, a prong, a bail) sits behind.
FRONT_RATIO_TOLERANCE = 1.35
#: ``orient``: turns whose front is within this (natural log of the ratio) of the best one count as equal — the
#: thinnest depth of them wins (a square image cannot tell the turns of a cube apart).
FRONT_RATIO_TIE = 0.05


def _depth_turns(V: np.ndarray) -> List[np.ndarray]:
    """The three turns that put one box axis into depth (z): z stays; x by −90° about +Y (+X → +Z); y by +90° about +X
    (+Y → +Z, the old z → −Y) — the turns of ``orient_thin_to_depth``."""
    return [V, V @ _rot_y(-np.pi / 2).T, V @ _rot_x(np.pi / 2).T]


def _front_score(V: np.ndarray, front_ratio: float) -> float:
    e = V.max(0) - V.min(0)
    if float(e[1]) <= 0 or float(e[0]) <= 0:
        return float("inf")
    return abs(float(np.log((float(e[0]) / float(e[1])) / float(front_ratio))))


def orient(V: np.ndarray, front_ratio: Optional[float] = None, flip: bool = False) -> np.ndarray:
    """``V`` turned so its depth is z (+Y up, front +Z). With the image's ``front_ratio`` (width : height,
    ``image_front_ratio``) the depth is the axis whose two others match it best (``_depth_turns``; within
    ``FRONT_RATIO_TIE`` of the best the thinner depth, then z, x, y) — a loop or a prong the mesher put behind the
    part makes the depth long, never the front. Without one: ``orient_thin_to_depth``. ``flip`` then turns it 180°
    about +Y."""
    V = np.asarray(V, np.float64)
    if not front_ratio or not len(V):
        return orient_thin_to_depth(V, flip)
    scored = []
    for i, T in enumerate(_depth_turns(V)):
        scored.append((_front_score(T, front_ratio), float(T[:, 2].max() - T[:, 2].min()), i, T))
    best = min(s[0] for s in scored)
    V = min((s for s in scored if s[0] <= best + FRONT_RATIO_TIE), key=lambda s: (s[1], s[2]))[3]
    if flip:
        V = V @ _rot_y(np.pi).T
    return V


def front_reason(V: np.ndarray, front_ratio: Optional[float]) -> str:
    """Why the mesh ``V`` does not show its image (``REASON_FRONT``): even the best turn's front differs from
    ``front_ratio`` by more than ``FRONT_RATIO_TOLERANCE``. '' when it matches or no ratio is known."""
    V = np.asarray(V, np.float64)
    if not front_ratio or not len(V):
        return ""
    T = orient(V, front_ratio)
    if _front_score(T, front_ratio) <= float(np.log(FRONT_RATIO_TOLERANCE)) + 1e-9:
        return ""
    e = T.max(0) - T.min(0)
    return REASON_FRONT.format(mesh=float(e[0]) / max(float(e[1]), 1e-12), image=float(front_ratio))


def orient_thin_to_depth(V: np.ndarray, flip: bool = False) -> np.ndarray:
    """``V`` turned so the thinnest side of its box is z (the depth: a buckle or a pendant lies flat on the body,
    whatever axis the mesher put its thickness on). z stays when ``e_z ≤ (1 + THIN_TIE) · min(e)``; else the thinner of
    x and y (x on a tie) becomes z — x by −90° about +Y (+X → +Z), y by +90° about +X (+Y → +Z, the old z → −Y).
    ``flip`` then turns it 180° about +Y (the other side shows to the front)."""
    V = np.asarray(V, np.float64)
    if len(V):
        e = V.max(0) - V.min(0)
        m = float(e.min())
        if float(e[2]) > (1.0 + THIN_TIE) * m:
            if float(e[0]) <= float(e[1]):
                V = V @ _rot_y(-np.pi / 2).T
            else:
                V = V @ _rot_x(np.pi / 2).T
    if flip:
        V = V @ _rot_y(np.pi).T
    return V


def normalise(V: np.ndarray, size_mm: float, flip: bool = False,
              front_ratio: Optional[float] = None) -> np.ndarray:
    """``V`` turned depth to z (``orient``; +Y up, front +Z), centred in x and z, its top at y = 0, its back at z = 0
    and scaled so the longer FRONT side of its box (width or height — what the image shows) is ``size_mm``; a depth
    the mesher made longer never shrinks the part (module docstring)."""
    V = orient(V, front_ratio, flip)
    lo, hi = V.min(0), V.max(0)
    scale = (float(size_mm) / 1000.0) / max(float((hi - lo)[:2].max()), 1e-12)
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


#: ``eyelet``: the side projection is rasterised at this many pixels over the part's height.
EYELET_RASTER = 400
#: ``eyelet``: a hole narrower than this many pixels (radius) is a raster seam, not an eyelet.
EYELET_MIN_PX = 3
#: ``threaded_place``: the air the threaded part keeps to the body — the eyelet sits on the cord, which itself runs
#: this close to the skin; ``pose_check`` then refuses anything inside.
THREAD_GAP_M = 0.001


def eyelet(Vn: np.ndarray, F: np.ndarray) -> Optional[Tuple[np.ndarray, float]]:
    """The eyelet of the normalised part ``Vn`` (``normalise``: +Y up, front +Z, top at y = 0): the hole a cord running
    left–right passes through. The faces are projected along x onto the (y, z) plane and rasterised
    (``EYELET_RASTER`` pixels over the height); a hole is an empty region not connected to the raster's border; of the
    holes with an inscribed radius of at least ``EYELET_MIN_PX`` the topmost wins, its centre being the centre of its
    largest inscribed circle (what intrudes into the hole — a jump ring — never pulls the centre onto it).
    ``(centre (0, y, z), inscribed radius in metres)``, None without such a hole (a solid bail)."""
    from PIL import Image, ImageDraw
    from scipy import ndimage
    V = np.asarray(Vn, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if not len(V) or not len(F):
        return None
    lo, hi = V.min(0), V.max(0)
    px = float(hi[1] - lo[1]) / EYELET_RASTER
    if px <= 0:
        return None
    pad = 4
    w = int(np.ceil((hi[2] - lo[2]) / px)) + 2 * pad + 1
    h = EYELET_RASTER + 2 * pad + 1
    col = (V[:, 2] - lo[2]) / px + pad          # z -> column
    row = (hi[1] - V[:, 1]) / px + pad          # y (top first) -> row
    im = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(im)
    for a, b, c in F:
        draw.polygon([(col[a], row[a]), (col[b], row[b]), (col[c], row[c])], fill=255, outline=255)
    solid = np.asarray(im) > 0
    labels, count = ndimage.label(~solid)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    best = None
    for lab in range(1, count + 1):
        if lab in border:
            continue
        hole = labels == lab
        dist = ndimage.distance_transform_edt(hole)
        r = float(dist.max())
        if r < EYELET_MIN_PX:
            continue
        i, j = np.unravel_index(int(np.argmax(dist)), dist.shape)
        if best is None or i < best[0]:
            best = (int(i), int(j), r)
    if best is None:
        return None
    i, j, r = best
    return np.array([0.0, float(hi[1] - (i - pad) * px), float(lo[2] + (j - pad) * px)]), r * px


def threaded_place(Vn: np.ndarray, F: np.ndarray, point: np.ndarray, outward: np.ndarray, Pb: np.ndarray,
                   Fb: np.ndarray, cord_radius: float) -> Optional[Tuple[np.ndarray, Dict[str, Any]]]:
    """The part hung with the cord through its eyelet: ``Vn`` moved so the eyelet centre (``eyelet``) is at ``point``
    (on the cord's centre line), then placed about that point (``place``, gap ``THREAD_GAP_M`` — it tilts about the
    cord and is pushed along ``outward`` to clear the body). None — the caller keeps the old placement — without an
    eyelet or when the cord is thicker than the eyelet. Else ``place``'s result with ``threaded: True``, the eyelet
    (``eyelet_mm``: its centre in the part, ``eyelet_radius_mm``), ``centre`` (metres) and ``cord_lift_mm``: how far
    the cord must be lifted along ``outward`` at ``point`` to stay inside the eyelet — the push beyond the room the
    eyelet leaves around the cord (its radius − the cord radius); 0 when the push stays within it."""
    found = eyelet(Vn, F)
    if found is None:
        return None
    centre, r = found
    room = r - float(cord_radius)
    if room <= 0:
        return None
    V, how = place(np.asarray(Vn, np.float64) - centre, point, outward, Pb, Fb, gap_m=THREAD_GAP_M)
    lift = max(0.0, how["push_mm"] / 1000.0 - room)
    how.update({"threaded": True, "eyelet_mm": [round(float(x) * 1000.0, 2) for x in centre],
                "eyelet_radius_mm": round(r * 1000.0, 2), "centre": centre, "cord_lift_mm": round(lift * 1000.0, 3)})
    return V, how


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
