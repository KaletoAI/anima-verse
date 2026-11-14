"""The strand record of a hair fit (strand-hair spec 2026-11-13 § 6.2.3, stage H2).

Everything geometric the per-strand simulation needs is computed here, on the CPU, from the fit GLB and its fit
record; the clients (``@anima/scene-render`` ``hairSim``) decide no geometry. One record per hair fit, cached as
two sidecars beside the fit — ``<fit stem>.strands.json`` (what the clients get) and ``<fit stem>.strands.npz``
(the per-vertex binding the assembly writes into the served GLB, ``_STRAND_CARD`` / ``_STRAND_U``) — keyed by the
fit GLB's sha256 (and the character's collision scales, which the capsules carry), so existing fits need no refit.

The record (``build_record``):

- ``rest``: per card ``ROWS`` = 17 centreline points, root first, in the bind space of the served GLB (the fit's
  body is the body the figure stands on, ``garment_assembly.built_on_fit_base``). The head bone carries the head
  frame rigidly: ``world = Head_now · Head_bind⁻¹ · p`` (``frame "head_bind"``).
- ``pins``: per card the leading rows that follow their target rigidly (rule ``scalp_free`` of the HAAR spike's
  ``export_glb.pin_rows``, ``pin_rows``).
- ``free_arc`` / ``free_frac``: arc from the last pin (0 on pins) and its fraction of the card's free arc.
- ``follow``: per row the Head / Neck / Spine2 blend of today's skin (``garment_fit.hair_weights`` at the row);
  pinned rows are ``{Head: 1}`` (they sit on the scalp and move with it).
- ``sdf``: the head of the fit's body (``garment_fit.body_sdf``) cropped to the head and served from the chin up,
  the neck behind the jaw cut away (``SDF_FLOOR`` / ``SDF_NECK``, Ruling H-R8: the neck is the capsules'), int8
  millimetres, x fastest.
- ``face_box`` / ``eye_box`` from the head landmarks, ``ear_y`` the ear line, ``capsules`` the fit body's capsule
  set (``collision.fit_capsules``, with the extension capsules of the body the fit was made on — e.g.
  ``chest_hair`` —, ``fit_extension``; the client keeps the hair regions), ``params`` the mode's parameter set.

HairDeck's layout (``hairdeck_layout``): its cards are square tubes, 4 vertices per row, rows root first, the hair
vertices first in raw order and the scalp cap after them (``garment_hairdeck.fit_hairdeck``, ``report.vertices``).
HAAR's layout (``haar_layout``): its cards are strips of exactly ``ROWS`` rows of 2 vertices, root first, card k the
vertices ``[2 ROWS k, 2 ROWS (k + 1))``, the cap after them (``garment_haar.fit_haar``, ``hair_cards.haar_cards``).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import numpy as np

logger = logging.getLogger(__name__)

#: Bumped when the record's content changes meaning; a sidecar of another version is rebuilt (on the CPU, by the
#: next assembly or preview that asks for it). 2: the SDF ends at the head (Ruling H-R8, ``SDF_FLOOR``,
#: ``SDF_NECK``).
RECORD_VERSION = 2
#: Simulated rows per card (root first): 16 segments.
ROWS = 17
SEGMENTS = ROWS - 1
#: Pin rule ``scalp_free``: every row within ``PIN_ARC_M`` of arc, plus the leading rows within ``PIN_BODY_M`` of
#: the body up to ``PIN_BODY_ARC_M`` of arc; the root always.
PIN_ARC_M = 0.02
PIN_BODY_M = 0.006
PIN_BODY_ARC_M = 0.04
#: The head SDF crop around the Head-weighted box (m): x ``cx ± SDF_HALF_X``, y ``chin - SDF_BELOW_CHIN`` …
#: ``top + SDF_ABOVE_TOP``, z ``cz ± SDF_HALF_Z``; computed at ``garment_fit.VOX_M`` and kept every
#: ``SDF_STRIDE``-th voxel (6.8 mm); int8 millimetres clamped to ``SDF_CLAMP_MM`` (also the value outside).
SDF_HALF_X = 0.15
SDF_BELOW_CHIN = 0.05
SDF_ABOVE_TOP = 0.06
SDF_HALF_Z = 0.16
SDF_STRIDE = 2
SDF_CLAMP_MM = 127
#: Ruling H-R8: the SERVED SDF ends at this landmark of ``head_frame`` (its lowest payload row at most one payload
#: voxel below it), and with ``SDF_NECK`` every voxel below the ear line AND behind the head's centre plane ``cz``
#: reads outside. The SDF rides the head bone rigidly, so the neck volume below the head turned with the head and
#: put hair that rightly follows Neck / Spine2 35-50 mm "inside" (task-8/9 report); the body capsules and the fit
#: collider cover the neck. Measured on Kira and Lirien (sit / celebrating / walk, the game's turns and snaps,
#: task-9b report): ending at the chin alone left the neck between chin and ear (13.9 / 21.1 mm deep, celebrating
#: with a snap); ending at the ear line let hair 35-47 mm into the jaw; chin + the neck cut: ≤ 1.04 mm. The pins
#: still read the whole crop (``pin_rows``: hair resting on the nape).
SDF_FLOOR = "chin"
SDF_NECK = True
#: Face keep-out box (the spike's ``drape.eye_box(face=True)``): ``|x - cx| < FACE_HALF_X``, chin .. brow +
#: ``FACE_BROW_UP``, in front of ``cz + FACE_PLANE * head_d``.
FACE_HALF_X = 0.06
FACE_BROW_UP = 0.01
FACE_PLANE = 0.25
#: Eye box (``eye_box(margin=0)``, the checks only): ``|x - cx| < EYE_HALF_X``, nose + ``EYE_NOSE_UP`` .. brow +
#: ``EYE_BROW_UP``, same plane.
EYE_HALF_X = 0.04
EYE_NOSE_UP = 0.01
EYE_BROW_UP = 0.005
#: Landmark fallbacks of a head whose profile shows no face (the spike's ``drape.eye_box``): brow
#: ``top - BROW_BELOW_TOP``, nose tip ``chin + NOSE_ABOVE_CHIN``.
BROW_BELOW_TOP = 0.09
NOSE_ABOVE_CHIN = 0.06
#: Decimals of the record's per-row numbers (10 µm, 1e-5 of a weight): a HairDeck record is ~0.4-0.6 MB.
DIGITS = 5
#: The bones a follow row blends, by ``rig_contract.norm_bone_name``.
FOLLOW_KEYS = ("head", "neck", "spine2")
#: The two per-vertex attributes of the served full-tier hair primitive.
VERTEX_ATTRIBUTES = {"card": "_STRAND_CARD", "u": "_STRAND_U"}
#: The simulation parameters per hair mode (spec § 6.2.1, the user's round-3 defaults). HAAR: the tether only
#: (the spike's ``stiff=tether`` preset), so no angle limit.
_HAIRDECK_PARAMS: Dict[str, Any] = {
    "damping": 0.04, "stiffness": 1.0, "bend": 0.15, "iterations": 6,
    "root_deg": 10, "root_frac": 0.2, "fly_soft": True, "fly_arc": 0.30,
    "tether": True, "tether_r0": 0.015, "tether_r1": 0.06, "tether_head": 0.012, "head_clr": 0.03,
    "face_box": True}
PARAMS: Dict[str, Dict[str, Any]] = {"hairdeck": dict(_HAIRDECK_PARAMS),
                                     "haar": {**_HAIRDECK_PARAMS, "root_deg": 0}}
#: The fit methods (``garment_store.fit_method``) that get a strand record: their names are ``PARAMS``' keys.
STRAND_MODES = ("hairdeck", "haar")

_LOGGED: set = set()
_LOGGED_LOCK = threading.Lock()
_JSON_CACHE: Dict[str, Tuple[Tuple[int, int, int], str, Dict[str, Any]]] = {}
_JSON_LOCK = threading.Lock()


@dataclass
class StrandLayout:
    """The strands of one hair mesh: ``card`` (n,) int per vertex (-1 = rigid, the cap), ``u`` (n,) float in
    [0, ``SEGMENTS``] its place along the simulated rows, ``centrelines`` (S, ``ROWS``, 3) the rest rows."""
    card: np.ndarray
    u: np.ndarray
    centrelines: np.ndarray


# --- Layout -------------------------------------------------------------------------------------------------------

def hairdeck_layout(P: np.ndarray, F: np.ndarray, n_hair: int) -> StrandLayout:
    """The strand layout of a HairDeck hair mesh: cards = ``hair_cards.hairdeck_cards`` (the connected components
    of the hair faces); each card's vertices in raw order form its TRUE rows, 4 vertices each, root first. The row
    centres are resampled by arc length to ``ROWS`` rows; a vertex's ``u`` is its true row's arc fraction ×
    ``SEGMENTS``. Vertices from ``n_hair`` on (the cap) are rigid (card -1, u 0). ValueError for a card that is
    not whole rows of 4 or has no length (the record must never scramble the served vertices)."""
    from app.core import hair_cards
    P = np.asarray(P, np.float64).reshape(-1, 3)
    n = len(P)
    card = hair_cards.hairdeck_cards(F, n_hair, n)
    hair = np.flatnonzero(card >= 0)
    if not len(hair):
        raise ValueError("hairdeck_layout: no hair card")
    S = int(card.max()) + 1
    order = hair[np.argsort(card[hair], kind="stable")]
    counts = np.bincount(card[hair], minlength=S)
    u = np.zeros(n, np.float64)
    C = np.zeros((S, ROWS, 3), np.float64)
    t = np.linspace(0.0, 1.0, ROWS)
    for k, idx in enumerate(np.split(order, np.cumsum(counts)[:-1])):
        if len(idx) % 4 or len(idx) < 8:
            raise ValueError(f"hairdeck_layout: card {k} has {len(idx)} vertices, not whole rows of 4")
        R = len(idx) // 4
        Ct = P[idx].reshape(R, 4, 3).mean(1)
        a = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(Ct, axis=0), axis=1))]
        if not a[-1] > 1e-9:
            raise ValueError(f"hairdeck_layout: card {k} has no length")
        frac = a / a[-1]
        u[idx] = np.repeat(frac * SEGMENTS, 4)
        C[k] = np.stack([np.interp(t, frac, Ct[:, d]) for d in range(3)], 1)
    return StrandLayout(card=card, u=u, centrelines=C)


def haar_layout(V: np.ndarray, n_hair: int) -> StrandLayout:
    """The strand layout of a HAAR hair mesh (``garment_haar.fit_haar``): card k = vertices ``[34 k, 34 k + 34)``
    (``ROWS`` rows of 2, root first), ``u`` = the row index, the centreline row = the mean of its two vertices;
    vertices from ``n_hair`` on (the cap) are rigid (card -1, u 0). ValueError when ``n_hair`` is not whole cards
    or a card has no length."""
    V = np.asarray(V, np.float64).reshape(-1, 3)
    n_hair = int(n_hair)
    per = 2 * ROWS
    if n_hair <= 0 or n_hair % per or n_hair > len(V):
        raise ValueError(f"haar_layout: {n_hair} hair vertices of {len(V)} are not whole cards of {per}")
    S = n_hair // per
    idx = np.arange(n_hair)
    card = np.full(len(V), -1, np.int64)
    card[:n_hair] = idx // per
    u = np.zeros(len(V), np.float64)
    u[:n_hair] = (idx % per) // 2
    C = V[:n_hair].reshape(S, ROWS, 2, 3).mean(2)
    if not (np.linalg.norm(np.diff(C, axis=1), axis=2).sum(1) > 1e-9).all():
        raise ValueError("haar_layout: a card has no length")
    return StrandLayout(card=card, u=u, centrelines=C)


def _arc(C: np.ndarray) -> np.ndarray:
    """(S, ROWS) arc length from the root along each centreline."""
    return np.concatenate([np.zeros((len(C), 1)), np.cumsum(np.linalg.norm(np.diff(C, axis=1), axis=2), 1)], 1)


def pin_rows(C: np.ndarray, sdf) -> np.ndarray:
    """Per card the number of LEADING pinned rows (rule ``scalp_free``, the spike's ``export_glb.pin_rows``): a row
    is pinned within ``PIN_ARC_M`` of arc, or while every row up to it lies within ``PIN_BODY_M`` of the body and
    it is within ``PIN_BODY_ARC_M`` of arc; row 0 always; the pins are the leading run of pinned rows. ``sdf`` has
    ``sample(X)`` (``garment_fit.Sdf``, metres; ``_bounded`` reads +inf outside its grid)."""
    C = np.asarray(C, np.float64)
    arc = _arc(C)
    d = np.asarray(sdf.sample(C.reshape(-1, 3)), np.float64).reshape(C.shape[:2])
    pin = (arc <= PIN_ARC_M) | (np.cumprod(d <= PIN_BODY_M, axis=1).astype(bool) & (arc <= PIN_BODY_ARC_M))
    pin[:, 0] = True
    return np.cumprod(pin, axis=1).sum(1).astype(np.int64)


class _Bounded:
    """A ``garment_fit.Sdf`` that reads ``outside`` beyond its grid (``map_coordinates`` would repeat the edge)."""

    def __init__(self, sdf, outside: float):
        self.sdf, self.outside = sdf, float(outside)
        self.hi = np.asarray(sdf.lo, np.float64) + (np.asarray(sdf.field.shape) - 1) * float(sdf.vox)

    def sample(self, X) -> np.ndarray:
        X = np.asarray(X, np.float64).reshape(-1, 3)
        inside = ((X >= np.asarray(self.sdf.lo) - 1e-12) & (X <= self.hi + 1e-12)).all(1)
        out = np.full(len(X), self.outside)
        if inside.any():
            out[inside] = self.sdf.sample(X[inside])
        return out


# --- The head -----------------------------------------------------------------------------------------------------

def head_frame(body) -> Dict[str, Any]:
    """The head measurements of a rigged body (``glb_mesh.BodyMesh``): chin, crown (``top``), ear line, the
    Head-weighted box (``garment_hairdeck._head_box``), the landmarks (``garment_hairdeck.head_landmarks``; brow /
    nose tip fall back to ``top - BROW_BELOW_TOP`` / ``chin + NOSE_ABOVE_CHIN`` when the profile shows no face),
    the face and eye boxes ``[x0, x1, y0, y1, z0]``."""
    from app.core import garment_fit as gf
    from app.core import garment_hairdeck as gh
    P = np.asarray(body.positions, np.float64)
    head_v = gf.dense_weights(body)[:, gf.joint_index(body, "head")] > 0.5
    chin = gf.chin_height(body)
    top = float(P[head_v, 1].max())
    cx, cz, head_w, head_d = gh._head_box(P, head_v)
    lm = gh.head_landmarks(P, head_v, chin, top) or {}
    brow = float(lm.get("brow_y", top - BROW_BELOW_TOP))
    nose = float(lm.get("nose_tip_y", chin + NOSE_ABOVE_CHIN))
    fz = cz + FACE_PLANE * head_d
    return {"chin": chin, "top": top, "ear": gf.ear_line_height(body), "cx": cx, "cz": cz, "head_w": head_w,
            "head_d": head_d, "brow": brow, "nose": nose, "landmarks": "profile" if lm else "fallback",
            "face_box": [cx - FACE_HALF_X, cx + FACE_HALF_X, chin, brow + FACE_BROW_UP, fz],
            "eye_box": [cx - EYE_HALF_X, cx + EYE_HALF_X, nose + EYE_NOSE_UP, brow + EYE_BROW_UP, fz]}


def head_sdf(body, frame: Dict[str, Any]):
    """``garment_fit.body_sdf`` of the body at ``VOX_M``, cropped to the head (module constants)."""
    from app.core import garment_fit as gf
    lo = np.array([frame["cx"] - SDF_HALF_X, frame["chin"] - SDF_BELOW_CHIN, frame["cz"] - SDF_HALF_Z])
    hi = np.array([frame["cx"] + SDF_HALF_X, frame["top"] + SDF_ABOVE_TOP, frame["cz"] + SDF_HALF_Z])
    F = np.asarray(body.faces, np.int64).reshape(-1, 3)
    return gf.body_sdf(np.asarray(body.positions, np.float64), F, vox=gf.VOX_M, bounds=(lo, hi))


def sdf_payload(sdf, floor_y: Optional[float] = None, neck: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """The record's ``sdf``: every ``SDF_STRIDE``-th voxel of ``sdf`` from its ``lo``, int8 millimetres clamped
    to ±``SDF_CLAMP_MM``, x fastest, base64. ``floor_y`` (m, Ruling H-R8): the payload rows below it are left out —
    its lowest row is the last one at or below ``floor_y`` (at most one payload voxel below it), on the same grid.
    ``neck`` = ``(y, z)``: every payload voxel below ``y`` AND behind ``z`` reads ``SDF_CLAMP_MM`` (outside)."""
    field = np.asarray(sdf.field, np.float64)[::SDF_STRIDE, ::SDF_STRIDE, ::SDF_STRIDE]
    lo = np.asarray(sdf.lo, np.float64).copy()
    step = float(sdf.vox) * SDF_STRIDE
    if floor_y is not None:
        k = int(min(max(math.floor((float(floor_y) - lo[1]) / step + 1e-9), 0), field.shape[1] - 2))
        field = field[:, k:, :]
        lo[1] += k * step
    if neck is not None:
        field = field.copy()
        ys = lo[1] + step * np.arange(field.shape[1])
        zs = lo[2] + step * np.arange(field.shape[2])
        field[:, (ys < neck[0])[:, None] & (zs < neck[1])[None, :]] = SDF_CLAMP_MM / 1000.0
    q = np.clip(np.round(field * 1000.0), -SDF_CLAMP_MM, SDF_CLAMP_MM).astype(np.int8)
    data = np.ascontiguousarray(q.transpose(2, 1, 0)).tobytes()
    return {"dims": [int(v) for v in q.shape], "lo": [round(float(v), 6) for v in lo],
            "vox": round(float(sdf.vox) * SDF_STRIDE, 6), "order": "x_fastest", "unit": "mm_int8",
            "data": base64.b64encode(data).decode("ascii")}


def decode_sdf(payload: Dict[str, Any], X) -> np.ndarray:
    """The record's ``sdf`` at points ``X`` in metres (trilinear inside, ``SDF_CLAMP_MM`` mm outside the grid) —
    what a client reads; for the checks."""
    dims = [int(v) for v in payload["dims"]]
    q = np.frombuffer(base64.b64decode(payload["data"]), np.int8).reshape(dims[2], dims[1], dims[0])
    field = q.transpose(2, 1, 0).astype(np.float64) / 1000.0
    from app.core.garment_fit import Sdf
    return _Bounded(Sdf(field=field, lo=np.asarray(payload["lo"], np.float64), vox=float(payload["vox"])),
                    SDF_CLAMP_MM / 1000.0).sample(X)


# --- The record ---------------------------------------------------------------------------------------------------

def _follow(C: np.ndarray, body, pins: np.ndarray) -> Tuple[list, np.ndarray]:
    """``(bones, w)``: ``hair_weights`` at every row, reduced to ``FOLLOW_KEYS`` (a skin without a Neck: Head and
    Spine2), renormalised; pinned rows ``{Head: 1}``. ``w`` (S, ROWS, len(bones))."""
    from app.core.garment_fit import hair_weights
    names, J, W = hair_weights(C.reshape(-1, 3), body)
    nb = len(names)
    w = np.zeros((len(J), nb))
    for c in range(4):
        cols = J[:, c]
        ok = cols < nb
        np.add.at(w, (np.flatnonzero(ok), cols[ok]), W[ok, c])
    w = w / np.maximum(w.sum(1, keepdims=True), 1e-12)
    w = w.reshape(len(C), ROWS, nb)
    pinned = np.arange(ROWS)[None, :] < pins[:, None]
    w[pinned] = 0.0
    w[pinned, 0] = 1.0
    return list(names), w


def _round_rows(w: np.ndarray, digits: int) -> np.ndarray:
    """Rows rounded to ``digits``, the largest entry taking the rest so every row sums to 1 to float precision."""
    r = np.round(w, digits).reshape(-1, w.shape[-1])
    big = np.argmax(r, 1)
    rows = np.arange(len(r))
    r[rows, big] = 0.0
    r[rows, big] = 1.0 - r.sum(1)
    return r


def _floats(a: np.ndarray, digits: int) -> list:
    return [float(v) for v in np.round(np.asarray(a, np.float64).ravel(), digits)]


def build_record(fit_glb: bytes, *, mode: str, item_id: str, fsig: str, layout: StrandLayout,
                 scales: Dict[str, float], extension: Optional[list] = None
                 ) -> Tuple[Dict[str, Any], Dict[str, np.ndarray]]:
    """The strand record of ``fit_glb`` (module docstring; spec § 6.2.3) for ``layout`` (of the hair primitive in
    that GLB), plus the per-vertex arrays ``{"card": uint16 card + 1 (0 = rigid), "u": float32}``. ``extension``:
    the fit body's extension groups (``collision.extension_chains``, ``fit_extension``) — their capsules (e.g.
    ``chest_hair``) follow the table's, a chain bone the fit GLB lacks is skipped (Ruling H-R4). ValueError for an
    unknown ``mode`` or a GLB without a skinned body."""
    from app.core import collision
    from app.core import garment_fit as gf
    from app.core.glb_mesh import body_arrays
    if mode not in PARAMS:
        raise ValueError(f"unknown hair mode {mode!r}")
    body = body_arrays(fit_glb)
    if not body.joint_names:
        raise ValueError("The fit GLB has no skinned body")
    frame = head_frame(body)
    sdf = head_sdf(body, frame)
    C = np.asarray(layout.centrelines, np.float64)
    S = len(C)
    pins = pin_rows(C, _Bounded(sdf, math.inf))
    arc = _arc(C)
    last = arc[np.arange(S), pins - 1]
    pinned = np.arange(ROWS)[None, :] < pins[:, None]
    free_arc = np.where(pinned, 0.0, arc - last[:, None])
    total = free_arc[:, -1]
    free_frac = np.where(total[:, None] > 1e-9, free_arc / np.maximum(total[:, None], 1e-9), 0.0)
    bones, w = _follow(C, body, pins)
    fitted = collision.fit_capsules(fit_glb, scales=scales, extension=extension)
    record = {
        "version": RECORD_VERSION,
        "item_id": str(item_id), "fsig": str(fsig), "mode": mode,
        "fit_sha256": hashlib.sha256(fit_glb).hexdigest(),
        "frame": "head_bind",
        "head_bone": body.joint_names[gf.joint_index(body, "head")],
        "rows": ROWS,
        "cards": int(S),
        "rest": _floats(C, DIGITS),
        "pins": [int(v) for v in pins],
        "free_arc": _floats(free_arc, DIGITS),
        "free_frac": _floats(free_frac, DIGITS),
        "follow": {"bones": bones, "w": [float(v) for v in _round_rows(w, DIGITS).ravel()]},
        "ear_y": round(float(frame["ear"]), 6),
        "face_box": [round(float(v), 6) for v in frame["face_box"]],
        "eye_box": [round(float(v), 6) for v in frame["eye_box"]],
        "landmarks": frame["landmarks"],
        "sdf": sdf_payload(sdf, floor_y=frame[SDF_FLOOR], neck=(frame["ear"], frame["cz"]) if SDF_NECK else None),
        "capsules": {"version": fitted["version"], "capsules": fitted["capsules"], "scales": fitted["scales"]},
        "params": dict(PARAMS[mode]),
        "vertex_attributes": dict(VERTEX_ATTRIBUTES),
    }
    card = np.asarray(layout.card, np.int64)
    if card.max() >= 0xFFFF:
        raise ValueError("More hair cards than _STRAND_CARD can address")
    arrays = {"card": (card + 1).astype(np.uint16), "u": np.asarray(layout.u, np.float32)}
    return record, arrays


def encode(record: Dict[str, Any]) -> bytes:
    """The record's bytes as stored and served (compact JSON, insertion order): ``sha256`` of these is the
    record's identity (ETag, the assembly's ``strands`` state)."""
    return json.dumps(record, separators=(",", ":"), allow_nan=False).encode("utf-8")


# --- The sidecars -------------------------------------------------------------------------------------------------

def sidecar_paths(fit_path: Path) -> Tuple[Path, Path]:
    """``(<fit stem>.strands.json, <fit stem>.strands.npz)`` beside the fit."""
    fit_path = Path(fit_path)
    return (fit_path.with_name(fit_path.stem + ".strands.json"),
            fit_path.with_name(fit_path.stem + ".strands.npz"))


def _file_sha(path: Path) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


def _read_json(path: Path) -> Tuple[str, Dict[str, Any]]:
    """``(sha256 of the bytes, record)`` of a strands JSON, cached per stat; ``("", {})`` when unreadable."""
    try:
        st = path.stat()
    except OSError:
        return "", {}
    key = (st.st_size, st.st_mtime_ns, st.st_ino)
    with _JSON_LOCK:
        hit = _JSON_CACHE.get(str(path))
    if hit and hit[0] == key:
        return hit[1], hit[2]
    try:
        data = path.read_bytes()
        record = json.loads(data)
    except (OSError, ValueError):
        return "", {}
    if not isinstance(record, dict):
        return "", {}
    sha = hashlib.sha256(data).hexdigest()
    with _JSON_LOCK:
        _JSON_CACHE[str(path)] = (key, sha, record)
    return sha, record


def _fresh(record: Dict[str, Any], fit_sha: str, scales: Optional[Dict[str, float]]) -> bool:
    return (record.get("version") == RECORD_VERSION and bool(fit_sha) and record.get("fit_sha256") == fit_sha
            and (scales is None or (record.get("capsules") or {}).get("scales") == scales))


def current_sha(fit_path: Path, *, fit_sha256: Optional[str] = None,
                scales: Optional[Dict[str, float]] = None) -> str:
    """Read-only: the sha256 of the fit's strands JSON when it is current — this version, made of the fit file's
    bytes (``fit_sha256`` when the caller already has it) and, with ``scales``, of those collision scales —, else
    ""."""
    json_path, _ = sidecar_paths(fit_path)
    sha, record = _read_json(json_path)
    if not sha:
        return ""
    fit_sha = fit_sha256 if fit_sha256 is not None else _file_sha(Path(fit_path))
    return sha if _fresh(record, fit_sha, scales) else ""


def _log_once(key: Tuple[str, str], message: str, *args) -> None:
    with _LOGGED_LOCK:
        if key in _LOGGED:
            return
        _LOGGED.add(key)
    logger.warning(message, *args)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _npz_bytes(arrays: Dict[str, np.ndarray], fit_sha: str) -> bytes:
    import io
    out = io.BytesIO()
    np.savez(out, card=arrays["card"], u=arrays["u"], fit_sha256=np.array(fit_sha))
    return out.getvalue()


#: A fit record's ``body_id``: a base signature or an outfit body id (both name ``model3d/<body_id>.glb``).
_BODY_ID_RE = re.compile(r"(?:base|ob)[0-9a-f]{8}")


def fit_extension(character_name: str, fit_record: Dict[str, Any]) -> list:
    """The extension groups that get capsules on the body the fit was made on (Ruling H-R4):
    ``collision.extension_chains`` of that body's model sidecar (``model3d/<body_id>.json``, the fit record's
    ``body_id``); ``[]`` without a body id, a sidecar or an applied extension rig."""
    from app.core import collision
    from app.core.model3d import _read_sidecar
    from app.models.character import get_character_dir
    body_id = str(fit_record.get("body_id") or "")
    if not _BODY_ID_RE.fullmatch(body_id):
        return []
    meta = _read_sidecar(get_character_dir(character_name) / "model3d" / f"{body_id}.glb")
    return collision.extension_chains(meta) if meta else []


def record_for_fit(character_name: str, fit_path: Path) -> Optional[Dict[str, Any]]:
    """The strand record of the hair fit ``fit_path``: read from its sidecars when they are current (this
    version, the fit's sha256, the character's collision scales), else built and written atomically (the npz
    first, the JSON last) under ``keyed_lock("hair_strands", fit)``. The mode is the fit record's ``method``
    (HairDeck / HAAR: ``report.vertices.hair`` hair vertices, ``hairdeck_layout`` / ``haar_layout``). None — logged
    once per fit content — for a fit of another method, without a hair node or fit record, or with an unreadable
    GLB."""
    from app.core import collision
    from app.core import garment_store as gs
    from app.core.glb_mesh import garment_arrays
    from app.core.keyed_lock import keyed_lock
    fit_path = Path(fit_path)
    with keyed_lock("hair_strands", str(fit_path)):
        try:
            blob = fit_path.read_bytes()
        except OSError:
            return None
        fit_sha = hashlib.sha256(blob).hexdigest()
        key = (str(fit_path), fit_sha)
        fit_record = gs.read_record(fit_path.with_suffix(".json"))
        mode = gs.fit_method(fit_record)
        if mode not in STRAND_MODES:
            _log_once(key, "Hair strands %s: no record for a %s fit", fit_path.name, mode)
            return None
        scales = collision.character_scales(character_name)
        json_path, npz_path = sidecar_paths(fit_path)
        _sha, existing = _read_json(json_path)
        if existing and _fresh(existing, fit_sha, scales) and npz_path.is_file():
            return existing
        try:
            n_hair = int(((fit_record.get("report") or {}).get("vertices") or {})["hair"])
            garment = garment_arrays(blob, node_prefix="garment_hair_")
            if not 0 < n_hair <= len(garment.positions):
                raise ValueError(f"{n_hair} hair vertices of {len(garment.positions)}")
            layout = (haar_layout(garment.positions, n_hair) if mode == gs.HAAR
                      else hairdeck_layout(garment.positions, garment.indices, n_hair))
            record, arrays = build_record(blob, mode=mode, item_id=str(fit_record.get("item_id") or ""),
                                          fsig=str(fit_record.get("fsig") or ""), layout=layout, scales=scales,
                                          extension=fit_extension(character_name, fit_record))
        except Exception as exc:  # noqa: BLE001 — no record means static hair, never a failed assembly
            _log_once(key, "Hair strands %s: no record (%s)", fit_path.name, exc)
            return None
        _write_atomic(npz_path, _npz_bytes(arrays, fit_sha))
        _write_atomic(json_path, encode(record))
        logger.info("Hair strands %s: %d cards, %d pinned rows", fit_path.name, record["cards"],
                    int(sum(record["pins"])))
        return record


def vertex_arrays(fit_path: Path) -> Optional[Dict[str, np.ndarray]]:
    """``{"card": uint16, "u": float32}`` of the fit's CURRENT record (its JSON names the fit file's sha256 and
    the npz the same), None otherwise."""
    fit_path = Path(fit_path)
    json_path, npz_path = sidecar_paths(fit_path)
    _sha, record = _read_json(json_path)
    fit_sha = _file_sha(fit_path)
    if not record or not _fresh(record, fit_sha, None):
        return None
    try:
        with np.load(npz_path, allow_pickle=False) as z:
            if str(z["fit_sha256"]) != fit_sha:
                return None
            return {"card": np.asarray(z["card"], np.uint16), "u": np.asarray(z["u"], np.float32)}
    except (OSError, ValueError, KeyError):
        return None


# --- Serving ------------------------------------------------------------------------------------------------------

def preview_version(fit_path: Path) -> str:
    """The content version of the Hairstyles preview GLB of the fit ``fit_path`` (``preview_glb``): the fit
    file's (``http_files.content_version``), with ``.s<RECORD_VERSION>`` appended for a HairDeck or HAAR fit — its
    preview carries the strand binding, so a client cache of the bare fit never stands in for it. OSError for an
    unreadable fit."""
    from app.core import garment_store as gs
    from app.core.http_files import content_version
    version = content_version(Path(fit_path))
    record = gs.read_record(Path(fit_path).with_suffix(".json"))
    return f"{version}.s{RECORD_VERSION}" if gs.fit_method(record) in STRAND_MODES else version


def preview_glb(character_name: str, fit_path: Path) -> Optional[Tuple[bytes, str]]:
    """``(bytes, version)`` of the Hairstyles preview GLB of the fit ``fit_path`` (Ruling H-R5): a HairDeck or HAAR fit
    with ``_STRAND_CARD`` / ``_STRAND_U`` on its hair primitive — the same per-vertex binding the full tier
    carries (``garment_assembly._attach_strands``), so the preview's sim binds like the 3D client's — when its
    record (``record_for_fit``, built on the CPU when missing) was made of these very bytes; every other fit, or
    one without a record, as it is stored. ``version`` = ``preview_version`` of the bytes read. None for an
    unreadable fit."""
    from app.core import garment_store as gs
    from app.core.glb_mesh import add_vertex_attributes
    fit_path = Path(fit_path)
    try:
        blob = fit_path.read_bytes()
    except OSError:
        return None
    sha = hashlib.sha256(blob).hexdigest()
    if gs.fit_method(gs.read_record(fit_path.with_suffix(".json"))) not in STRAND_MODES:
        return blob, sha[:16]
    version = f"{sha[:16]}.s{RECORD_VERSION}"
    record = record_for_fit(character_name, fit_path)
    arrays = vertex_arrays(fit_path) if record is not None else None
    if record is None or arrays is None or record.get("fit_sha256") != sha:
        return blob, version
    try:
        blob = add_vertex_attributes(blob, {VERTEX_ATTRIBUTES["card"]: arrays["card"],
                                            VERTEX_ATTRIBUTES["u"]: arrays["u"]}, node_prefix="garment_hair_")
    except ValueError as exc:
        _log_once((str(fit_path), sha), "Hair strands %s: preview without the binding (%s)", fit_path.name, exc)
    return blob, version


def strands_url(character_name: str) -> str:
    return f"/characters/{quote(character_name)}/model/hair-strands"


def served_file(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                path: Optional[Path] = None) -> Optional[Tuple[Path, str]]:
    """``(strands JSON, its sha256)`` of the record whose sha256 the CURRENT served full-tier assembly carries
    (its sidecar's hair ``strands``) for the bare model ``path`` (default: the served model,
    ``model3d.find_model3d_serving``). None when Swing is off for the worn hairstyle, no assembly is served, the
    assembly grafts no hair with a record, or the record on disk is no longer that one."""
    from app.core import garment_assembly, hair_motion
    from app.core.keyed_lock import keyed_lock
    if not hair_motion.worn_settings(character_name, profile).get("swing"):
        return None
    if path is None:
        from app.core.model3d import find_model3d_serving
        path, _match = find_model3d_serving(character_name)
    if path is None:
        return None
    path = Path(path)
    with keyed_lock("model3d_publication", str(path.parent)):
        file = garment_assembly.served(character_name, path, garment_assembly.FULL)
        if file is None or Path(file) == path:
            return None
        side = garment_assembly.read_sidecar(Path(file))
    hair = {iid: str(e.get("strands") or "") for iid, e in (side.get("garments") or {}).items()
            if isinstance(e, dict) and e.get("kind") == "hair" and e.get("strands")}
    if not hair:
        return None
    for g in garment_assembly._wanted_for(character_name, path.parent, path.stem):
        if g["item_id"] in hair and g["fit"] is not None:
            json_path, _ = sidecar_paths(g["fit"])
            sha, _record = _read_json(json_path)
            if sha and sha == hair[g["item_id"]]:
                return json_path, sha
    return None


def served(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
           path: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """``{"url", "sha256"}`` of ``served_file`` (the model info's ``model.hair_strands``), None without one."""
    found = served_file(character_name, profile=profile, path=path)
    if found is None:
        return None
    return {"url": strands_url(character_name), "sha256": found[1]}
