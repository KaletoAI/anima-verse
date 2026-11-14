"""The last fit attempt per (piece, body) and the user's acceptance of a refused fit (Ruling A31).

WHY. A fit refused by its gates published nothing: the Details preview showed the fit on the plain body only, so
a fit refused on a body shape could not be seen, and nothing but a new mesh could get the piece onto the figure.
Here every refused fit of clothing and footwear (``garments._fit`` / ``garments.fit_on_body`` /
``garment_footwear.fit``) keeps its LAST attempt per (item, body): the GLB it would have published, its record
(the gates' verdict included) and the region the refusing gate measured. The Details preview shows each body's
attempt with that region marked, and an admin may ACCEPT a refused fit.

FILES (``garment_store`` parts ``attempt`` / ``attempt_prev`` / ``attempt_prev_low`` / ``attempt_derived``; the base
body's under ``garments/``, an outfit body's under ``garments/bodies/<body id>/``)::

    attempts/{item}_{fsig}.glb + .json + .npz       the attempt: the GLB as a fit would be published (none when the
                                                    gate refused before a fit was made), its record (``accepted``
                                                    False + ``attempt {at, error, reasons, gates, glb_sha256,
                                                    marks, tris}``) and the marked points (``MARK_KINDS``: bind
                                                    positions with their skin, per kind)
    attempts/prev/{item}_{fsig}.glb + .json         the fit an acceptance displaced (``accept``), put back by
    attempts/prev/low/{item}_{fsig}.glb             ``undo``
    attempts/derived/{item}_{fsig}.glb + .json + .npz
                                                    a body shape's refused DERIVED shoe (Ruling A40), kept beside the
                                                    fresh fit that followed it (slot ``DERIVED``): the Details preview
                                                    shows it as an entry of its own and it can be accepted like any
                                                    attempt; voided like the others, dropped when a derived shoe is
                                                    accepted on that body

One attempt per (item, body): a new attempt of the item on that body replaces the older ones (another fsig's
too, unless the user accepted it); a fit the gates accept drops the body's attempts (``drop``). The files are in
the group of their ``(item, fsig)`` (``garment_store.stored_groups``), so the artefact GC keeps them exactly as
long as it keeps that group's fits on that body.

THE MARKED REGION is what the refusing gate itself counted, never re-derived: ``garment_source.limb_marks``
(the piece's vertices off the limb segments the limb gate refused), ``garment_source.torso_marks`` (the trunk
vertices left uncovered in the front / side / back groups the torso gate refused) and ``footwear_cut.cut_gates``
``marks`` (the foot points outside the shoe that the refusing enclosure gates counted). At most ``MAX_MARKS``
points per kind are kept. The preview GLB (``marked_glb``) grafts them as small octahedra skinned like the
vertex they mark, one garment node per kind in its own colour (a garment node keeps its own material in the
viewers), so they move with the body.

ACCEPTANCE (``accept``): the attempt — when it is still CURRENT for its body (``_current``: the same fit
fingerprint, body bytes, fit algorithm version, and for a body shape the same base fit; for footwear the same
shoe source) — is published AS the fit of (item, fsig, body): its GLB at the fit path, its record with
``accepted`` True and ``user_accepted {at, error, reasons, attempt_sha256, body_id, fit_version, failure}``, a
distance tier decimated from it. The fit that path held is moved to ``attempts/prev/``, the recorded refusal
(``failed/``) is kept in ``user_accepted.failure`` and removed. So every reader that serves accepted fits —
the assembly, the figure resolver, the Build's plan and estimate, the status rows — counts it as accepted
without knowing about acceptances, and the assembly state (each fit's sha256) makes the figure due:
re-assembly, CPU only. ``undo`` puts the displaced fit and the refusal back.

VOIDED automatically: a changed body, base fit or fit version makes the accepted fit stale for the readers like
any fit (``garments.body_fit_state`` / ``garment_footwear.fit_state`` / ``garment_store.accepted_fit``); a
user-accepted fit is never served once it is not current (``garments.body_fit``, ``garment_footwear.body_fit``,
``garment_store.newest_accepted_fits`` / ``newest_body_footwear_fit`` skip it) — never in the place of the fit
that replaces it. A new attempt on the same (item, fsig, body) whose GLB differs from the accepted one undoes the
acceptance (``store``); the same GLB keeps it. A fit the gates accept overwrites it (``drop``).

Hair is out of scope: its fits are never kept or accepted here.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("fit_attempts")

ATTEMPT, PREV, PREV_LOW = "attempt", "attempt_prev", "attempt_prev_low"
#: The refused DERIVED shoe of a body shape, kept beside the fresh fit that followed it (Ruling A40).
ATTEMPT_DERIVED = "attempt_derived"
#: The attempt slots: "" the body's last attempt, ``DERIVED`` a body shape's refused derived shoe (Ruling A40).
DERIVED = "derived"
SLOTS: Dict[str, str] = {"": ATTEMPT, DERIVED: ATTEMPT_DERIVED}
#: The Details preview key of a body's derived-shoe attempt: ``<body id>`` + this.
DERIVED_KEY_SUFFIX = "-derived"
#: The most points kept per mark kind (evenly thinned beyond it).
MAX_MARKS = 1500
#: Half the size of one marker octahedron (metres).
MARK_SIZE_M = 0.006
#: The mark kinds: colour (sRGB hex — the GLB material and the legend) and the legend's words.
MARK_KINDS: Dict[str, Dict[str, str]] = {
    "limb": {"colour": "#ff8c00", "label": "Piece off the limb"},
    "torso": {"colour": "#ff2d2d", "label": "Torso left uncovered"},
    "foot": {"colour": "#e040fb", "label": "Foot outside the shoe"},
}
#: The kinds whose refused fits are kept and can be accepted.
KINDS = ("clothing", "footwear")
#: The status light's words of a user-accepted fit.
ACCEPTED_BY_YOU = "Accepted by you"
#: How a body shape's shoe was fitted (``garment_footwear.fit``, record ``fit_method``, Ruling A40) in the Details
#: preview's words (the React switch translates them).
FIT_METHOD_NOTES: Dict[str, str] = {
    "derived": "the shoe as fitted on the plain body",
    "fresh_fallback": "fitted fresh on this body shape — the shoe as fitted on the plain body did not fit here",
}


class AcceptError(ValueError):
    """An acceptance (or its undo) that cannot be made — the message says why (409)."""


class Busy(RuntimeError):
    """A run of the character holds the fit now (409)."""


# --- Marks --------------------------------------------------------------------------------------------------

def mesh_marks(mesh: Any, idx: Any) -> Optional[Dict[str, Any]]:
    """The points ``idx`` of ``mesh`` (a ``glb_mesh.GarmentMesh`` or ``BodyMesh``: positions, joints, weights,
    joint_names) as one mark kind's arrays, None when ``idx`` is empty."""
    idx = np.asarray(idx, np.int64).reshape(-1)
    if not len(idx):
        return None
    return {"positions": np.asarray(mesh.positions, np.float64)[idx],
            "joints": np.asarray(mesh.joints, np.int64)[idx],
            "weights": np.asarray(mesh.weights, np.float64)[idx],
            "joint_names": [str(n) for n in mesh.joint_names]}


def _thin(mark: Dict[str, Any]) -> Dict[str, Any]:
    n = len(mark["positions"])
    if n <= MAX_MARKS:
        return mark
    keep = np.linspace(0, n - 1, MAX_MARKS).round().astype(np.int64)
    return {**mark, "positions": mark["positions"][keep], "joints": mark["joints"][keep],
            "weights": mark["weights"][keep], "total": n}


def _write_marks(path: Path, marks: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """Write the kept marks to ``path`` (npz); ``{kind: points counted}`` (before thinning)."""
    arrays: Dict[str, np.ndarray] = {}
    meta: Dict[str, Any] = {}
    counts: Dict[str, int] = {}
    for kind, mark in marks.items():
        mark = _thin(mark)
        arrays[f"{kind}_p"] = np.asarray(mark["positions"], np.float32)
        arrays[f"{kind}_j"] = np.asarray(mark["joints"], np.uint16)
        arrays[f"{kind}_w"] = np.asarray(mark["weights"], np.float32)
        meta[kind] = {"joint_names": list(mark["joint_names"])}
        counts[kind] = int(mark.get("total") or len(mark["positions"]))
    buf = io.BytesIO()
    np.savez_compressed(buf, meta=np.frombuffer(json.dumps(meta).encode("utf-8"), np.uint8), **arrays)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return counts


def load_marks(path: Path) -> Dict[str, Dict[str, Any]]:
    """The marks of an attempt (``_write_marks``), {} without (or unreadable)."""
    try:
        with np.load(path) as npz:
            meta = json.loads(bytes(npz["meta"]).decode("utf-8"))
            return {kind: {"positions": npz[f"{kind}_p"].astype(np.float64),
                           "joints": npz[f"{kind}_j"].astype(np.int64),
                           "weights": npz[f"{kind}_w"].astype(np.float64),
                           "joint_names": list(info.get("joint_names") or [])}
                    for kind, info in meta.items() if kind in MARK_KINDS}
    except (OSError, ValueError, KeyError):
        return {}


def _rgb(hex_colour: str) -> List[float]:
    """sRGB hex -> linear RGB (glTF factors are linear)."""
    out = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


#: The 8 faces of one octahedron over its 6 corners (+x, -x, +y, -y, +z, -z), outward.
_OCTA_FACES = np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]],
                       np.int64)
_OCTA_DIRS = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float64)


def marker_mesh(kind: str, mark: Dict[str, Any]):
    """One mark kind as a skinned ``glb_mesh.GarmentMesh``: an octahedron of ``MARK_SIZE_M`` per point, each
    corner skinned like the point (its joints / weights), in the kind's colour, emissive and double-sided."""
    from app.core import glb_mesh
    P = np.asarray(mark["positions"], np.float64)
    n = len(P)
    V = (P[:, None, :] + MARK_SIZE_M * _OCTA_DIRS[None]).reshape(-1, 3)
    F = (_OCTA_FACES[None] + 6 * np.arange(n)[:, None, None]).reshape(-1, 3)
    J = np.repeat(np.asarray(mark["joints"], np.int64), 6, axis=0)
    W = np.repeat(np.asarray(mark["weights"], np.float64), 6, axis=0)
    empty = W.sum(1) <= 0
    W[empty] = [1.0, 0.0, 0.0, 0.0]
    rgb = _rgb(MARK_KINDS[kind]["colour"])
    material = {"pbrMetallicRoughness": {"baseColorFactor": [*rgb, 1.0], "metallicFactor": 0.0,
                                         "roughnessFactor": 0.6},
                "emissiveFactor": [0.35 * c for c in rgb], "doubleSided": True}
    return glb_mesh.GarmentMesh(positions=V, normals=np.tile(_OCTA_DIRS, (n, 1)), uvs=np.zeros((len(V), 2)),
                                indices=F, joints=J, weights=W, joint_names=list(mark["joint_names"]),
                                material=material)


_marked_cache: "OrderedDict[Tuple[Any, ...], bytes]" = OrderedDict()
_marked_lock = threading.Lock()
#: Marked preview GLBs kept in memory (keyed by the attempt GLB's and marks file's identity).
MARKED_CACHE_SIZE = 2


def marked_glb(glb: Path, marks_path: Optional[Path], item_id: str) -> bytes:
    """The attempt GLB with its marks grafted (``marker_mesh``, one node ``garment_marks_<kind>`` per kind)."""
    from app.core import glb_mesh

    def ident(p: Optional[Path]) -> Any:
        if p is None or not p.is_file():
            return None
        st = p.stat()
        return (str(p), st.st_size, st.st_mtime_ns)
    key = (ident(glb), ident(marks_path))
    with _marked_lock:
        if key in _marked_cache:
            _marked_cache.move_to_end(key)
            return _marked_cache[key]
    blob = glb.read_bytes()
    for kind, mark in sorted(load_marks(marks_path).items() if marks_path else []):
        if not len(mark["positions"]):
            continue
        blob = glb_mesh.graft(blob, marker_mesh(kind, mark), name=f"garment_marks_{kind}",
                              extras={"kind": "marks", "mark": kind, "item_id": item_id})
    with _marked_lock:
        _marked_cache[key] = blob
        while len(_marked_cache) > MARKED_CACHE_SIZE:
            _marked_cache.popitem(last=False)
    return blob


# --- Store ----------------------------------------------------------------------------------------------

def _file_sha(path: Optional[Path]) -> str:
    if path is None or not Path(path).is_file():
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lock(character_name: str, body: str):
    """The lock of a body's fits — the one ``garments.body_fit`` / ``garment_footwear.body_fit`` fit under
    (``garment_body_fit``) for an outfit body, a lock of the plain body's attempts for the plain body."""
    from app.core.keyed_lock import keyed_lock
    if body:
        return keyed_lock("garment_body_fit", f"{character_name}:{body}")
    return keyed_lock("fit_attempt_plain", character_name)


def _attempt_files(character_name: str, item_id: str, body: str, slot: str = "") -> Dict[str, Dict[str, Path]]:
    """fsig -> ``{glb, json, npz}`` of the item's attempt files on ``body`` in ``slot`` (``SLOTS``; present or
    not)."""
    from app.core import garment_store as gs
    out: Dict[str, Dict[str, Path]] = {}
    for (iid, fsig), files in gs.stored_groups(character_name).items():
        if iid != item_id:
            continue
        for p in files:
            if gs.body_of(p) != body:
                continue
            try:
                attempt = gs.garment_path(character_name, item_id, fsig, SLOTS[slot], body=body)
            except ValueError:
                continue
            if p.parent == attempt.parent:
                out[fsig] = {"glb": attempt, "json": attempt.with_suffix(".json"), "npz": attempt.with_suffix(".npz")}
    return out


def _user_accepted_fit(character_name: str, item_id: str, fsig: str, body: str) -> Dict[str, Any]:
    """The ``user_accepted`` block of the fit record at (item, fsig, body), {} when it holds none."""
    from app.core import garment_store as gs
    try:
        record = gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit", body=body).with_suffix(".json"))
    except ValueError:
        return {}
    block = record.get("user_accepted")
    return block if record.get("accepted") is True and isinstance(block, dict) else {}


def _remove_attempt(files: Dict[str, Path]) -> None:
    for p in files.values():
        p.unlink(missing_ok=True)


def _remove_prev(character_name: str, item_id: str, fsig: str, body: str) -> None:
    from app.core import garment_store as gs
    prev = gs.garment_path(character_name, item_id, fsig, PREV, body=body)
    for p in (prev, prev.with_suffix(".json"), gs.garment_path(character_name, item_id, fsig, PREV_LOW, body=body)):
        p.unlink(missing_ok=True)


def store(character_name: str, item_id: str, fsig: str, *, body: str, kind: str, record: Dict[str, Any],
          error: str, gates: Any, rigged: Optional[bytes] = None, garment: Any = None, glb: Optional[Path] = None,
          tris: Optional[int] = None, marks: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
          slot: str = "") -> None:
    """Keep a REFUSED fit of (item, fsig) on ``body`` ("" = the base model, else an outfit body id) as the body's
    last attempt (module docstring): the GLB — grafted here from ``rigged`` + ``garment`` as ``garments._publish_fit``
    grafts it, or the file ``glb`` a compute already wrote (moved in) —, ``record`` as the fit would be published
    with ``accepted`` False and ``attempt``, and ``marks`` (kind -> ``mesh_marks`` or None). ``slot`` (``SLOTS``):
    ``DERIVED`` keeps a body shape's refused derived shoe beside the body's last attempt (Ruling A40). Never
    raises: a refusal stays a refusal when its attempt cannot be kept."""
    if kind not in KINDS or slot not in SLOTS:
        return
    try:
        _store(character_name, item_id, fsig, body=body, kind=kind, record=record, error=error, gates=gates,
               rigged=rigged, garment=garment, glb=glb, tris=tris, marks=marks, slot=slot)
    except Exception:  # noqa: BLE001 — the attempt is a view on the refusal, never its outcome
        logger.exception("Fit attempt %s/%s (%s) on %s not kept", character_name, item_id, fsig, body or "plain body")


def _store(character_name: str, item_id: str, fsig: str, *, body: str, kind: str, record: Dict[str, Any],
           error: str, gates: Any, rigged: Optional[bytes], garment: Any, glb: Optional[Path], tris: Optional[int],
           marks: Optional[Dict[str, Optional[Dict[str, Any]]]], slot: str = "") -> None:
    from app.core import garment_store as gs, refit_pool
    from app.core.timeutils import utc_now_iso
    from app.models.character import get_character_dir
    if not get_character_dir(character_name).is_dir():
        return  # never mint the folders of a vanished character
    path = gs.garment_path(character_name, item_id, fsig, SLOTS[slot], body=body)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = refit_pool.temp_path(path)
    try:
        source: Optional[Path] = None
        if garment is not None and rigged is not None:
            tris = refit_pool.run(refit_pool.graft_file, rigged, garment, f"garment_{kind}_{item_id}",
                                  {"kind": kind, "item_id": item_id, "fsig": fsig}, str(tmp))
            source = tmp
        elif glb is not None and Path(glb).is_file():
            source = Path(glb)
        sha = _file_sha(source)
        kept = {k: v for k, v in (marks or {}).items() if k in MARK_KINDS and v and len(v["positions"])}
        with _lock(character_name, body):
            accepted = _user_accepted_fit(character_name, item_id, fsig, body)
            # an acceptance is voided by a new attempt of ITS slot only (the fresh fit's attempt never voids the
            # accepted derived shoe, Ruling A40)
            if accepted and str(accepted.get("slot") or "") == slot and accepted.get("attempt_sha256") != sha:
                # The fit changed: the acceptance of the old one is void (module docstring VOIDED).
                logger.info("Fit acceptance %s/%s (%s) on %s void: a new attempt differs", character_name, item_id,
                            fsig, body or "plain body")
                _undo_locked(character_name, item_id, fsig, body)
            for other, files in _attempt_files(character_name, item_id, body, slot).items():
                if other != fsig and not _user_accepted_fit(character_name, item_id, other, body):
                    _remove_attempt(files)
                    _remove_prev(character_name, item_id, other, body)
            if source is not None:
                os.replace(source, path)
            else:
                path.unlink(missing_ok=True)
            npz = path.with_suffix(".npz")
            counts = _write_marks(npz, kept) if kept else {}
            if not kept:
                npz.unlink(missing_ok=True)
            reasons = list((gates or {}).get("reasons") or []) if isinstance(gates, dict) else []
            gs.write_record(path.with_suffix(".json"), {
                **record, "accepted": False,
                "attempt": {"at": utc_now_iso(), "error": error, "reasons": reasons, "gates": gates,
                            "glb_sha256": sha or None, "tris": tris, "marks": counts,
                            "body_id": body or str(record.get("body_id") or "")}})
        logger.info("Fit attempt %s/%s (%s) on %s kept%s (refused%s)", character_name, item_id, fsig,
                    body or "plain body", f" as the {slot} attempt" if slot else "",
                    ", marked " + ", ".join(f"{k} {n}" for k, n in counts.items())
                    if counts else "")
    finally:
        tmp.unlink(missing_ok=True)


def drop(character_name: str, item_id: str, *, body: str, keep_derived: bool = False) -> None:
    """A fit the gates accepted on ``body``: the item's attempts there go (and the displaced fits kept for an
    undo), except those of another fsig the user accepted. ``keep_derived``: the refused derived shoe stays (the
    accepted fit is the fresh fit that followed it, Ruling A40). Never raises."""
    try:
        with _lock(character_name, body):
            for slot in SLOTS:
                if slot == DERIVED and keep_derived:
                    continue
                for fsig, files in _attempt_files(character_name, item_id, body, slot).items():
                    if _user_accepted_fit(character_name, item_id, fsig, body):
                        continue
                    _remove_attempt(files)
                    _remove_prev(character_name, item_id, fsig, body)
    except Exception:  # noqa: BLE001 — a cleanup, never a failure of the fit
        logger.exception("Fit attempts %s/%s on %s not dropped", character_name, item_id, body or "plain body")


def attempt_of(character_name: str, item_id: str, body: str, slot: str = ""
               ) -> Optional[Tuple[Optional[Path], Dict[str, Any], Optional[Path]]]:
    """``(glb or None, record, marks npz or None)`` of the item's newest attempt on ``body`` in ``slot``
    (``SLOTS``), None without."""
    from app.core import garment_store as gs
    best: Optional[Tuple[str, Optional[Path], Dict[str, Any], Optional[Path]]] = None
    for _fsig, files in _attempt_files(character_name, item_id, body, slot).items():
        record = gs.read_record(files["json"])
        if not record.get("attempt"):
            continue
        at = str(record["attempt"].get("at") or "")
        if best is None or at > best[0]:
            best = (at, files["glb"] if files["glb"].is_file() else None, record,
                    files["npz"] if files["npz"].is_file() else None)
    return (best[1], best[2], best[3]) if best else None


# --- Currency -----------------------------------------------------------------------------------------------

def _profile(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def fit_status(character_name: str, item_id: str, body: str, *,
               profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The item's fit on ``body`` as the readers judge it NOW: ``{fsig, state, failure, body_sha, base_fit_sha}``
    — ``fsig`` the fit fingerprint that body is fitted under (clothing on a body shape: the served base fit's),
    ``state`` ``accepted`` / ``stale`` / ``outdated`` / ``missing`` (the kind's state function), ``failure`` the
    recorded refusal that holds (None). ``fsig`` "" when there is nothing to fit from."""
    from app.core import base_body, garment_fit, garment_store as gs, garments
    profile = _profile(character_name, profile)
    kind = gs._garment_kind(item_id)
    base = base_body.current_base(character_name, profile=profile)
    base_sha = base[1] if base else ""
    out: Dict[str, Any] = {"fsig": "", "state": "missing", "failure": None, "body_sha": "", "base_fit_sha": ""}
    if kind == "footwear":
        from app.core import garment_footwear
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
        body_sha = garments.body_sha256(character_name, body) if body else base_sha
        state = garment_footwear.fit_state(character_name, item_id, fsig, body_sha, body=body)
        failure = None
        if state != "accepted":
            failure = (gs.body_failure(character_name, item_id, fsig, body, body_sha=body_sha, base_fit_sha="",
                                       fit_version=garment_fit.FIT_VERSION[kind]) if body
                       else gs.chain_failure(character_name, item_id, fsig, base_model_sha=base_sha))
        return {**out, "fsig": fsig, "state": state, "failure": failure, "body_sha": body_sha}
    if kind != "clothing" or not base_sha:
        return out
    if body:
        base_fit = gs.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile)
        parsed = gs.parse_name(base_fit[0]) if base_fit else None
        if not parsed:
            return out
        fsig = parsed[1]
        body_sha = garments.body_sha256(character_name, body)
        base_fit_sha = garments._sha(base_fit[0])
        state = garments.body_fit_state(character_name, item_id, fsig, body, body_sha, base_fit_sha)
        failure = (gs.body_failure(character_name, item_id, fsig, body, body_sha=body_sha, base_fit_sha=base_fit_sha,
                                   fit_version=garment_fit.expected_fit_version(base_fit[1]))
                   if state != "accepted" else None)
        return {**out, "fsig": fsig, "state": state, "failure": failure, "body_sha": body_sha,
                "base_fit_sha": base_fit_sha}
    fsig = gs.garment_fsig(character_name, item_id, profile=profile)
    method = gs.garment_method(character_name, item_id, profile=profile)
    state = garments._fit_state(character_name, item_id, fsig, base_sha, method)
    failure = gs.chain_failure(character_name, item_id, fsig, base_model_sha=base_sha) if state != "accepted" else None
    if failure is not None and failure.get("step") != "fit":
        failure = None
    return {**out, "fsig": fsig, "state": state, "failure": failure, "body_sha": base_sha}


def _current(character_name: str, item_id: str, body: str, record: Dict[str, Any],
             profile: Dict[str, Any]) -> str:
    """Why the attempt ``record`` on ``body`` is NOT the current refused fit there ("" when it is — the one an
    acceptance may publish): the fit fingerprint, the body bytes, the fit algorithm, the base fit (clothing on a
    body shape) and the shoe source (footwear) it was made of must all be today's, and the body must not hold a
    fit the gates accepted."""
    from app.core import garment_fit, garment_store as gs
    kind = str(record.get("kind") or "")
    if kind not in KINDS:
        return "Only clothing and footwear fits can be accepted"
    if record.get("fit_version") != garment_fit.expected_fit_version(record):
        return "The fit algorithm changed since this attempt — re-fit to see the current one"
    status = fit_status(character_name, item_id, body, profile=profile)
    if status["state"] == "accepted":
        return "This body already has an accepted fit"
    if not status["fsig"] or record.get("fsig") != status["fsig"]:
        return "The piece changed since this attempt — re-fit to see the current one"
    if not status["body_sha"] or record.get("body_sha256") != status["body_sha"]:
        return "The body changed since this attempt — re-fit to see the current one"
    if kind == "clothing" and body and record.get("base_fit_sha256") != status["base_fit_sha"]:
        return "The piece's fit on the plain body changed since this attempt — re-fit to see the current one"
    if kind == "clothing" and not body:
        prepared = gs.garment_path(character_name, item_id, status["fsig"], "prepared")
        if (record.get("inputs") or {}).get("prepared_sha256") != _file_sha(prepared):
            return "The piece's mesh changed since this attempt — re-fit to see the current one"
    if kind == "footwear":
        from app.core import footwear_source, garment_footwear
        source = (record.get("parents") or {}).get("source")
        try:
            now = garment_footwear._source_parents(item_id, footwear_source.current_ssig(item_id))
        except (OSError, ValueError):
            now = None
        if not source or source != now:
            return "The shoe source changed since this attempt — re-fit to see the current one"
    return ""


# --- Accept / undo ------------------------------------------------------------------------------------------

def _plain_guard(character_name: str, item_id: str):
    """The plain body's fits are written by the item's garment runs, which all hold the item's run lock
    (``garment_store.run_item_lock``, Ruling A30 — a FIFO run after the character's lock, a CPU refit beside the
    FIFO alone): an acceptance there never waits behind a run — ``Busy`` while one holds it."""
    from contextlib import contextmanager
    from app.core import garment_store as gs

    @contextmanager
    def guard():
        lock = gs.run_item_lock(character_name, item_id)
        if not lock.acquire(blocking=False):
            raise Busy("A garment run of this piece is in progress — accept or undo after it")
        try:
            yield
        finally:
            lock.release()
    return guard()


def accept(character_name: str, item_id: str, body: str, *, profile: Optional[Dict[str, Any]] = None,
           slot: str = "") -> Dict[str, Any]:
    """Publish the item's refused attempt on ``body`` (in ``slot``: ``DERIVED`` = a body shape's refused derived
    shoe, Ruling A40) as its fit, accepted by the user (module docstring). ``AcceptError`` when there is no current
    refused attempt with a mesh; ``Busy`` while a garment run of the piece holds the plain body's fits. Spends no
    job: a copy, a record and a distance tier (Blender, CPU). ``{item_id, body, accepted True, follow_up}``."""
    from contextlib import nullcontext
    if slot not in SLOTS:
        raise AcceptError(f"Unknown attempt {slot!r}")
    profile = _profile(character_name, profile)
    with (_plain_guard(character_name, item_id) if not body else nullcontext()):
        with _lock(character_name, body):
            _accept_locked(character_name, item_id, body, profile, slot)
    # Ruling A69: the last Build's failure of this piece at the fit is answered — the Figure tab's row follows the
    # accepted fit ("Ready — Accepted by you"), never "Failed" until the next Build.
    from app.core import figure_build
    figure_build.answer_piece_failure(character_name, item_id, ("fit",))
    return {"item_id": item_id, "body": body, "accepted": True, "follow_up": follow_up(character_name)}


def _accept_locked(character_name: str, item_id: str, body: str, profile: Dict[str, Any], slot: str = "") -> None:
    import shutil
    from app.blender import refine
    from app.core import garment_store as gs, glb_mesh
    from app.core.timeutils import utc_now_iso
    found = attempt_of(character_name, item_id, body, slot)
    if found is None:
        raise AcceptError("No refused fit on this body to accept")
    glb, record, _marks = found
    if glb is None:
        raise AcceptError("This refusal came before a fit was made — there is nothing to accept")
    fsig = str(record.get("fsig") or "")
    sha = (record.get("attempt") or {}).get("glb_sha256")
    if _user_accepted_fit(character_name, item_id, fsig, body).get("attempt_sha256") == sha:
        return  # already accepted
    why = _current(character_name, item_id, body, record, profile)
    if why:
        raise AcceptError(why)
    if _file_sha(glb) != sha:
        raise AcceptError("The kept attempt is damaged — re-fit to make it again")
    fit = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body)
    failed = gs.garment_path(character_name, item_id, fsig, "failed", body=body)
    prev = gs.garment_path(character_name, item_id, fsig, PREV, body=body)
    prev_low = gs.garment_path(character_name, item_id, fsig, PREV_LOW, body=body)
    _remove_prev(character_name, item_id, fsig, body)
    if fit.is_file():
        prev.parent.mkdir(parents=True, exist_ok=True)
        os.replace(fit, prev)
        if fit.with_suffix(".json").is_file():
            os.replace(fit.with_suffix(".json"), prev.with_suffix(".json"))
        if low.is_file():
            prev_low.parent.mkdir(parents=True, exist_ok=True)
            os.replace(low, prev_low)
    fit.with_suffix(".json").unlink(missing_ok=True)
    low.unlink(missing_ok=True)
    failure = gs.read_record(failed) if failed.is_file() else {}
    tmp = fit.with_name(f".{fit.name}.{os.getpid()}.accept.tmp")
    try:
        shutil.copyfile(glb, tmp)
        os.replace(tmp, fit)
    finally:
        tmp.unlink(missing_ok=True)
    attempt = record.get("attempt") or {}
    published = {k: v for k, v in record.items() if k != "attempt"}
    published.update(accepted=True, user_accepted={
        "at": utc_now_iso(), "error": attempt.get("error") or "", "reasons": list(attempt.get("reasons") or []),
        "gates": attempt.get("gates"), "attempt_sha256": sha, "body_id": body or str(record.get("body_id") or ""),
        "fit_version": record.get("fit_version"), "failure": failure or None, "slot": slot})
    gs.write_record(fit.with_suffix(".json"), published)
    failed.unlink(missing_ok=True)
    tris = attempt.get("tris")
    try:
        if not tris:
            tris = len(glb_mesh.static_arrays(fit.read_bytes())[1])
        dec = refine.decimate_to(fit, max(1, int(round(refine.lod_ratio("character") * int(tris)))), low,
                                 tris=int(tris))
    except Exception as e:  # noqa: BLE001 — the distance tier falls back to the full fit
        dec = {"ok": False, "error": str(e) or type(e).__name__}
    published["low"] = ({"ok": True, "tris": dec.get("tris"), "ratio": dec.get("ratio")} if dec.get("ok")
                        else {"ok": False, "error": dec.get("error") or "decimation failed"})
    gs.write_record(fit.with_suffix(".json"), published)
    if not body:
        gs.end(character_name, item_id, "fit")   # the run status's refusal of this fit is answered
    logger.info("Fit %s/%s (%s) on %s accepted by the user (refused: %s)", character_name, item_id, fsig,
                body or "plain body", attempt.get("error"))


def undo(character_name: str, item_id: str, body: str) -> Dict[str, Any]:
    """Revert the user's acceptance of the item's fit on ``body``: the accepted fit goes, the fit it displaced
    and the recorded refusal come back. ``AcceptError`` when no acceptance holds there. ``{item_id, body,
    accepted False, follow_up}``."""
    from contextlib import nullcontext
    with (_plain_guard(character_name, item_id) if not body else nullcontext()):
        with _lock(character_name, body):
            found = attempt_of(character_name, item_id, body)
            fsigs = [str(found[1].get("fsig") or "")] if found else []
            for slot in SLOTS:
                fsigs += [f for f in _attempt_files(character_name, item_id, body, slot) if f not in fsigs]
            for fsig in fsigs:
                if _user_accepted_fit(character_name, item_id, fsig, body):
                    _undo_locked(character_name, item_id, fsig, body)
                    break
            else:
                raise AcceptError("No fit accepted by you on this body")
    return {"item_id": item_id, "body": body, "accepted": False, "follow_up": follow_up(character_name)}


def _undo_locked(character_name: str, item_id: str, fsig: str, body: str) -> None:
    from app.core import garment_store as gs
    fit = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body)
    prev = gs.garment_path(character_name, item_id, fsig, PREV, body=body)
    prev_low = gs.garment_path(character_name, item_id, fsig, PREV_LOW, body=body)
    block = _user_accepted_fit(character_name, item_id, fsig, body)
    fit.unlink(missing_ok=True)
    low.unlink(missing_ok=True)
    fit.with_suffix(".json").unlink(missing_ok=True)
    if prev.is_file():
        os.replace(prev, fit)
        if prev.with_suffix(".json").is_file():
            os.replace(prev.with_suffix(".json"), fit.with_suffix(".json"))
        if prev_low.is_file():
            os.replace(prev_low, low)
    _remove_prev(character_name, item_id, fsig, body)
    failure = block.get("failure")
    if isinstance(failure, dict) and failure:
        gs.write_record(gs.garment_path(character_name, item_id, fsig, "failed", body=body), failure)
    else:
        from app.core import figure
        figure.invalidate()
    logger.info("Fit %s/%s (%s) on %s: the user's acceptance undone", character_name, item_id, fsig,
                body or "plain body")


def follow_up(character_name: str) -> Dict[str, Any]:
    """What the figure needs after an acceptance or its undo: the Build's estimate now
    (``figure_build.cost``: ``{hub_jobs, steps, note}``) — a re-assembly alone is CPU only (0 hub jobs)."""
    from app.core import figure_build
    return figure_build.cost(character_name)


# --- Reading ------------------------------------------------------------------------------------------------

def user_acceptance(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``{at, error, reasons}`` of a fit record the user accepted, None for any other."""
    block = (record or {}).get("user_accepted")
    if (record or {}).get("accepted") is not True or not isinstance(block, dict):
        return None
    return {"at": block.get("at"), "error": str(block.get("error") or ""),
            "reasons": list(block.get("reasons") or [])}


def shape_names(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """body id -> the names of the pieces in it, for the shapes of the wanted and the delivered figure now
    ("t-shirt, underwear"). Never raises."""
    out: Dict[str, str] = {}
    try:
        from app.core import figure
        from app.models.inventory import get_item
        profile = _profile(character_name, profile)
        wanted, delivered = figure._delivered(character_name, profile=profile)
        for fig in (delivered, wanted):
            if fig.in_body and fig.shape not in out:
                out[fig.shape] = ", ".join(str((get_item(i) or {}).get("name") or i) for i in fig.in_body)
        if delivered.fit_refused_on and delivered.fit_refused_on not in out:
            out[delivered.fit_refused_on] = out.get(wanted.shape, "")
    except Exception:  # noqa: BLE001 — a label, never a failure
        logger.debug("Shape names of %s failed", character_name, exc_info=True)
    return out


def accepted_by_user(character_name: str, item_id: str, shape: str, *,
                     profile: Optional[Dict[str, Any]] = None,
                     names: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """``{on, reason, detail}`` when a fit the figure on ``shape`` uses for the item was refused by its checks
    and accepted by the user — its fit on the body shape ``shape`` (an outfit body id), else its plain-body fit —
    None otherwise. Never raises."""
    from app.core import garment_store as gs
    try:
        if gs._garment_kind(item_id) not in KINDS:
            return None
        bodies_ = ([shape] if gs.is_body_id(shape) else []) + [""]
        for body in bodies_:
            status = fit_status(character_name, item_id, body, profile=profile)
            if status["state"] != "accepted" or not status["fsig"]:
                continue
            record = gs.read_record(gs.garment_path(character_name, item_id, status["fsig"], "fit",
                                                    body=body).with_suffix(".json"))
            block = user_acceptance(record)
            if block is None:
                continue
            plain = plain_reason(block["error"], (record.get("user_accepted") or {}).get("gates"),
                                 on_shape=bool(body))
            return {"on": body_label(character_name, body, profile=profile, names=names or {}),
                    "reason": plain["text"], "detail": plain["detail"], "at": block["at"]}
    except Exception:  # noqa: BLE001 — a marker, never a failure
        logger.debug("Accepted-by-user of %s/%s failed", character_name, item_id, exc_info=True)
    return None


def body_label(character_name: str, body: str, *, profile: Optional[Dict[str, Any]] = None,
               names: Optional[Dict[str, str]] = None) -> str:
    """The words for a body: "Plain body", or "Body shape (<what is in it>)" — the in-body pieces of the figure
    standing on that shape now (``names``: ``shape_names``), else the outfit it was built for, else its id."""
    if not body:
        return "Plain body"
    if names is None:
        names = shape_names(character_name, profile=profile)
    name = names.get(body, "")
    if not name:
        try:
            from app.core import base_body, outfit_bodies
            from app.core.model3d import _read_sidecar
            parent = _read_sidecar(base_body.outfit_body_path(character_name, body)).get("outfit_body") or {}
            built_for = str(parent.get("built_for") or "")
            name = outfit_bodies.outfit_label(character_name, built_for) if built_for else ""
        except Exception:  # noqa: BLE001 — a label, never a failure
            logger.debug("Body label of %s/%s failed", character_name, body, exc_info=True)
    return f"Body shape ({name})" if name else f"Body shape {body}"


# --- Plain words ----------------------------------------------------------------------------------------------

#: The prefixes the fit paths put before a refusal's reasons — one is enough for a reader.
_PREFIXES = ("fit on the outfit body refused — ", "refit refused — ", "fit refused — ")
_SEGMENTS = {"arm": ("upper arm", "forearm"), "leg": ("thigh", "shin")}
_LIMB_PIECE = {"arm": "sleeve", "leg": "trouser leg"}
_TORSO_SIDE = {"front": "front", "side": "sides", "back": "back"}
#: footwear cut / fit gate key -> the plain words (the numbers stay in the detail).
_FOOT_GATES = {
    "deep_outside": "the foot pokes out through the shoe",
    "visible_poke": "the foot shows above the shoe's rim",
    "throat_ledge_p95_mm": "the foot stands up out of the shoe's opening",
    "toe_conform_m": "the toes do not fit under the toe box",
    "shaft_poke": "the leg pokes out of the boot's shaft",
    "collar_conform_m": "the leg does not fit into the boot's opening",
    "collar_flex_poke": "the leg pokes out of the boot's opening when the ankle bends",
}
_GATE_KEY_RE = re.compile(r"^([a-z0-9_]+)(?::| [-0-9.e]+ (?:<|>|outside))")
#: The limb / torso gates' reasons (``garment_source.limb_gate`` / ``torso_gate`` / ``torso_hole_gate``) — read
#: only for a refusal kept without its gate record (made before attempts were kept).
_LIMB_RE = re.compile(r"^(left|right) (arm|leg): off the (upper arm|forearm|thigh|shin) — ([0-9.]+) of its")
_TORSO_RE = re.compile(r"^torso (front|side|back): ([0-9.]+) of the area .*\(source ([0-9.]+)")
_TOO_HIGH_RE = re.compile(r"\(foot (\d+) mm, shoe (\d+) mm at ([^)]+)\)")


def strip_prefix(error: str) -> str:
    """``error`` without the fit paths' "fit refused — " prefixes (one or several)."""
    text = str(error or "").strip()
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if text.lower().startswith(prefix):
                text, changed = text[len(prefix):].strip(), True
    return text


def plain_reason(error: str, gates: Any = None, *, on_shape: bool = False) -> Dict[str, Any]:
    """A refusal in plain words: ``{text, detail, piece}`` — ``text`` what went wrong, from the refusing gate's
    own keys and numbers (``gates``: the refusal's gate record; without one, the gate keys named in its reasons),
    ``detail`` the measured reasons (the tooltip), ``piece`` True when the reason points at the piece itself (a
    new mesh helps — e.g. a shoe mesh flatter than its image), False when it is about the body."""
    detail = strip_prefix(error)
    gates = gates if isinstance(gates, dict) else {}
    texts: List[str] = []
    piece = False
    limbs = gates.get("limbs") if isinstance(gates.get("limbs"), dict) else None
    for name, seg in (limbs or {}).get("failing") or []:
        side, _, limb = str(name).partition("_")
        if limb not in _SEGMENTS:
            continue
        got = (((limbs.get("fit") or {}).get(name) or {}).get("off") or [None, None])
        share = got[seg] if seg < len(got) else None
        tail = f" ({share * 100:.0f} % of it more than 4 cm from it)" if isinstance(share, (int, float)) else ""
        texts.append(f"the {side} {_LIMB_PIECE[limb]} stands off the {_SEGMENTS[limb][int(seg)]}{tail}")
    torso = gates.get("torso") if isinstance(gates.get("torso"), dict) else None
    for group in (torso or {}).get("failing") or []:
        share = ((torso.get("shares") or {}).get(group) or {})
        tail = (f" ({share['fit'] * 100:.0f} % covered, {share['source'] * 100:.0f} % on the plain body)"
                if isinstance(share.get("fit"), (int, float)) and isinstance(share.get("source"), (int, float))
                else "")
        texts.append(f"the {_TORSO_SIDE.get(group, group)} of the piece stands off the "
                     f"{'body shape' if on_shape else 'body'}{tail}")
    if gates.get("holes") is not None:
        texts.append("the body shows through a hole in the piece")
    if gates.get("registration") is not None:
        texts.append("the piece's pictures do not line up with this body")
    if not texts:
        for part in [x.strip() for x in detail.split(";") if x.strip()]:
            high = _TOO_HIGH_RE.search(part)
            if part.startswith("Foot too high"):
                who = "the body shape's foot" if on_shape else "the foot"
                texts.append(f"{who} is too high for this shoe" + (
                    f" (foot {high.group(1)} mm, the shoe has {high.group(2)} mm at {high.group(3)})" if high else ""))
                continue
            if part.startswith("Shoe mesh too flat"):
                texts.append("the shoe mesh is flatter than its picture — a new mesh helps")
                piece = True
                continue
            limb = _LIMB_RE.match(part)
            if limb:
                texts.append(f"the {limb.group(1)} {_LIMB_PIECE[limb.group(2)]} stands off the {limb.group(3)} "
                             f"({float(limb.group(4)) * 100:.0f} % of it more than 4 cm from it)")
                continue
            torso_m = _TORSO_RE.match(part)
            if torso_m:
                texts.append(f"the {_TORSO_SIDE[torso_m.group(1)]} of the piece stands off the "
                             f"{'body shape' if on_shape else 'body'} ({float(torso_m.group(2)) * 100:.0f} % covered, "
                             f"{float(torso_m.group(3)) * 100:.0f} % on the plain body)")
                continue
            if part.startswith("torso hole:"):
                texts.append("the body shows through a hole in the piece")
                continue
            key = _GATE_KEY_RE.match(part)
            words = _FOOT_GATES.get(key.group(1)) if key else None
            if words and words not in texts:
                texts.append(words)
    if not texts and "regenerate" in detail.lower():
        piece = True
    if not texts:
        texts = [detail[:1].lower() + detail[1:] if detail else "refused by its checks"]
    return {"text": "; ".join(texts[:3]), "detail": detail, "piece": piece}


def refusal_words(character_name: str, item_id: str, body: str, error: str) -> Dict[str, Any]:
    """``plain_reason`` of the refusal ``error`` of the item's fit on ``body`` — with the gate record of the
    body's kept attempt when it is that refusal (the same reasons). Never raises."""
    gates = None
    try:
        found = attempt_of(character_name, item_id, body)
        if found is not None:
            attempt = found[1].get("attempt") or {}
            if strip_prefix(attempt.get("error") or "") == strip_prefix(error):
                gates = attempt.get("gates")
    except Exception:  # noqa: BLE001 — the words, never a failure
        logger.debug("Refusal words of %s/%s failed", character_name, item_id, exc_info=True)
    return plain_reason(error, gates, on_shape=bool(body))


#: Ruling A67: the piece dialog's two bodies — the plain base and the body shape the worn outfit calls for.
ROLE_BASE, ROLE_CURRENT = "base", "current"
#: Why the current body shape cannot be re-fitted (its rigged body is not stored yet).
CURRENT_NOT_BUILT = "This body shape is not built yet — the Figure tab's Build makes it"


def dialog_shape(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None
                 ) -> Tuple[str, bool]:
    """Ruling A67 — ``(body id, stored)``: the body shape the piece dialog shows beside the base body. It is the
    shape the worn outfit calls for (``figure.wanted_figure``: the current outfit body), "" when that is the plain
    body, when the piece is meshed into it (an in-body piece is no fit there) or when the piece is neither an
    own-mesh piece of that figure nor has a fit, refusal or attempt on it. ``stored``: its rigged body is stored
    (``garment_footwear.stored_outfit_bodies``) — Re-fit needs it. Older body shapes are never returned: their fits
    stay on disk for the artefact GC. Never raises."""
    from app.core import figure, garment_footwear, garment_store as gs
    try:
        fig = figure.wanted_figure(character_name, profile=_profile(character_name, profile))
        shape = fig.shape if gs.is_body_id(fig.shape) else ""
        if not shape or (item_id in fig.in_body and item_id not in fig.in_body_own):
            return "", False
        if item_id not in fig.own and shape not in {gs.body_of(p) for (iid, _f), files
                                                    in gs.stored_groups(character_name).items()
                                                    if iid == item_id for p in files}:
            return "", False
        return shape, shape in set(garment_footwear.stored_outfit_bodies(character_name))
    except Exception:  # noqa: BLE001 — the dialog shows the base body alone
        logger.debug("Dialog shape of %s/%s failed", character_name, item_id, exc_info=True)
        return "", False


def bodies(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
           url_base: str = "") -> List[Dict[str, Any]]:
    """The piece dialog's body switch (Ruling A31; Ruling A67: two bodies at most) — the base body, then the body
    shape the worn outfit calls for (``dialog_shape``) when there is one; older body shapes never appear. Per entry
    ``{body ("" = plain), key ("plain" | body id), role (``ROLE_BASE`` | ``ROLE_CURRENT``), label, status, reason,
    refit_block (why Re-fit cannot run on it, "" when it can: ``CURRENT_NOT_BUILT``), url (the model to show,
    versioned; None: nothing to show), built_at, marks [{kind, count, colour, label}], foot_pose, can_accept,
    accept_block (why not), accepted_at, arm_light (Ruling A47: ``garment_fit.arm_light`` of what is shown, None
    without), numbers (Ruling A50, ``body_numbers`` of what is shown: this body's own), fit (Ruling A50b,
    ``body_fit_view``: what the dialog's fit row, chips and settings box show for this body; None = nothing)}``.
    ``status``: ``accepted`` (the gates accepted it), ``user_accepted`` (light green, "Accepted by you", ``reason``
    the gates' refusal), ``refused`` (``reason``), ``stale`` (made on an older body / piece / algorithm; refitted by
    the next Build), ``missing``. ``method_note``: how a body shape's shoe was fitted (``FIT_METHOD_NOTES``, ""
    otherwise), ``variant`` "" or ``DERIVED``: the current body shape's refused derived shoe, kept beside the fresh
    fit that followed it, is an entry of its own right after its body (key ``<body id>`` + ``DERIVED_KEY_SUFFIX``,
    Ruling A40). Read-only."""
    from urllib.parse import quote
    from app.core import garment_store as gs
    from app.core.http_files import content_version
    profile = _profile(character_name, profile)
    try:
        if gs._garment_kind(item_id) not in KINDS:
            return []
    except ValueError:
        return []
    shape, stored = dialog_shape(character_name, item_id, profile=profile)
    names = shape_names(character_name, profile=profile) if shape else {}
    out: List[Dict[str, Any]] = []
    for body in [""] + ([shape] if shape else []):
        entries = [_entry(character_name, item_id, body, profile, names)]
        if body:
            derived = _derived_entry(character_name, item_id, body, profile, names)
            if derived is not None:
                entries.append(derived)
        for entry in entries:
            entry["role"] = ROLE_CURRENT if body else ROLE_BASE
            entry["refit_block"] = CURRENT_NOT_BUILT if body and not stored else ""
            if body and not stored and entry["status"] == "missing":
                entry["reason"] = CURRENT_NOT_BUILT
            shown = entry.pop("_shown", None)
            if shown is not None:
                try:
                    entry["url"] = (f"{url_base or ''}/characters/{quote(character_name, safe='')}/garments/"
                                    f"{quote(item_id, safe='')}/fits/{entry['key']}/model?"
                                    f"v={content_version(shown[0])}{'m' if shown[1] else ''}")
                except OSError:
                    entry["url"] = None
            out.append(entry)
    return out


def _built_at(path: Optional[Path]) -> Optional[str]:
    from app.core.model_overview import built_at
    try:
        return built_at(path) if path is not None else None
    except ValueError:
        return None


def body_fit_view(item_id: str, record: Dict[str, Any], profile: Dict[str, Any], *,
                  accepted: bool) -> Optional[Dict[str, Any]]:
    """Ruling A50b — what the piece dialog's fit row, gate chips and fit settings box show of THIS body's fit
    (``record``: the fit or kept attempt the entry shows; None when it shows nothing): ``{metrics, tris,
    created_at, gates_ok, reasons (the refusing gate's, [] when accepted), fit_settings}`` — ``fit_settings`` ``garments.fit_settings_view`` of the record against
    the piece's settings now (sleeves and allowance are per piece, shared by every body; their Auto resolution
    comes from this body's fit), None for footwear."""
    if not record:
        return None
    from app.core import garment_fit_settings, garment_store as gs, garments
    metrics = record.get("metrics") or {}
    attempt = record.get("attempt") or {}
    fit_settings = None
    if gs._garment_kind(item_id) == "clothing":
        fit_settings = garments.fit_settings_view(record, garment_fit_settings.fit_settings(profile, item_id),
                                                  accepted=accepted)
    gates = attempt.get("gates") if attempt else record.get("gates")
    reasons = [] if accepted else [str(r) for r in ((gates or {}).get("reasons") or [])]
    return {"metrics": metrics, "tris": metrics.get("tris") or attempt.get("tris"),
            "created_at": record.get("created_at") or attempt.get("at"),
            "gates_ok": accepted, "reasons": reasons, "fit_settings": fit_settings}


#: ``body_numbers``: the metrics a body's entry carries (Ruling A50).
BODY_NUMBER_KEYS = ("sleeve_skin_left_cm2", "sleeve_skin_right_cm2", "deep_push_share", "torso_tight_share",
                    "scale_retry")


def body_numbers(record: Dict[str, Any]) -> Dict[str, Any]:
    """Ruling A50 — the numbers of the fit or attempt a body's entry SHOWS (``record``: its fit record or its kept
    attempt; {} when nothing is shown), so the dialog never shows another body's: ``BODY_NUMBER_KEYS`` from its
    metrics (None when not measured) and ``torso`` {front, side, back: {fit, source}} — the trunk coverage the
    outfit-body gate compares (``frame.torso`` of a fit, the refusing ``gates.torso`` of an attempt), None without."""
    if not record:
        return {}
    metrics = record.get("metrics") or {}
    out: Dict[str, Any] = {k: metrics.get(k) for k in BODY_NUMBER_KEYS}
    torso = ((record.get("attempt") or {}).get("gates") or {}).get("torso") \
        or (record.get("frame") or {}).get("torso") or {}
    shares = torso.get("shares") if isinstance(torso, dict) else None
    out["torso"] = shares if isinstance(shares, dict) and shares else None
    return out


def _entry(character_name: str, item_id: str, body: str, profile: Dict[str, Any],
           names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    from app.core import garment_store as gs
    status = fit_status(character_name, item_id, body, profile=profile)
    fsig = status["fsig"]
    fit_record: Dict[str, Any] = {}
    fit_path: Optional[Path] = None
    if fsig:
        fit_path = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
        fit_record = gs.read_record(fit_path.with_suffix(".json"))
        if not fit_path.is_file():
            fit_path = None
    found = attempt_of(character_name, item_id, body)
    glb, record, marks_path = found if found else (None, {}, None)
    attempt = record.get("attempt") or {}
    current_attempt = bool(found) and record.get("fsig") == fsig
    entry: Dict[str, Any] = {"body": body, "key": body or "plain",
                             "label": body_label(character_name, body, profile=profile, names=names or {}),
                             "status": "missing", "reason": "", "reason_detail": "", "piece_broken": False,
                             "url": None, "built_at": None, "marks": [],
                             "foot_pose": None, "can_accept": False, "accept_block": "", "accepted_at": None,
                             "method_note": "", "variant": "", "_shown": None}

    def words(error: str, gates: Any) -> None:
        plain = plain_reason(error, gates, on_shape=bool(body))
        entry.update(reason=plain["text"], reason_detail=plain["detail"], piece_broken=plain["piece"])

    accepted = user_acceptance(fit_record) if status["state"] == "accepted" else None
    if accepted is not None:
        entry.update(status="user_accepted", accepted_at=accepted["at"])
        words(accepted["error"], (fit_record.get("user_accepted") or {}).get("gates"))
    elif status["state"] == "accepted":
        entry["status"] = "accepted"
    elif status["failure"] is not None or (current_attempt and attempt
                                           and not _current(character_name, item_id, body, record, profile)):
        entry["status"] = "refused"
        error = str((status["failure"] or {}).get("error") or attempt.get("error") or "")
        same = current_attempt and strip_prefix(attempt.get("error") or "") == strip_prefix(error)
        words(error, attempt.get("gates") if same else None)
    elif status["state"] in ("stale", "outdated") or (current_attempt and attempt):
        entry.update(status="stale", reason=("Made on an older body, piece or fit algorithm, or with other fit "
                                             "settings — Re-fit with this body selected, or the next Build, fits "
                                             "it again"))
    # how a body shape's shoe was fitted (Ruling A40): the fit's record when it is the body's fit, else the attempt's
    method_of = fit_record if entry["status"] in ("accepted", "user_accepted") else (
        record if entry["status"] == "refused" and current_attempt else {})
    entry["method_note"] = FIT_METHOD_NOTES.get(str(method_of.get("fit_method") or ""), "") if body else ""
    # What the preview shows: the kept attempt (marked) when it is the body's last word — refused, or accepted
    # by the user —, else the fit itself.
    show_attempt = glb is not None and entry["status"] in ("refused", "user_accepted") and (
        entry["status"] == "refused" or attempt.get("glb_sha256") ==
        (fit_record.get("user_accepted") or {}).get("attempt_sha256"))
    if show_attempt:
        entry["_shown"] = (glb, marks_path is not None)
        entry["built_at"] = attempt.get("at")
        entry["marks"] = [{"kind": k, "count": int(n), **MARK_KINDS[k]}
                          for k, n in sorted((attempt.get("marks") or {}).items()) if k in MARK_KINDS]
        entry["foot_pose"] = record.get("foot_pose")
    elif fit_path is not None and entry["status"] in ("accepted", "user_accepted", "stale"):
        entry["_shown"] = (fit_path, False)
        entry["built_at"] = _built_at(fit_path)
        entry["foot_pose"] = fit_record.get("foot_pose")
    # Ruling A47: the arm light of what the preview shows (skin seen inside the sleeves), None before it existed.
    shown_record = record if show_attempt else (fit_record if entry["_shown"] is not None else {})
    entry["arm_light"] = (shown_record.get("report") or {}).get("arm_light")
    entry["numbers"] = body_numbers(shown_record)
    entry["fit"] = body_fit_view(item_id, shown_record, profile, accepted=entry["status"] in ("accepted",
                                                                                           "user_accepted"))
    if entry["status"] == "refused":
        if found is None or not current_attempt:
            entry["accept_block"] = ("No attempt kept for this refusal (made before attempts were kept) — "
                                     "Re-fit in the Figure tab shows it")
        elif glb is None:
            entry["accept_block"] = "This refusal came before a fit was made — there is nothing to accept"
        else:
            entry["accept_block"] = _current(character_name, item_id, body, record, profile)
        entry["can_accept"] = not entry["accept_block"]
    return entry


def _derived_entry(character_name: str, item_id: str, body: str, profile: Dict[str, Any],
                   names: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """The body switch's entry of a body shape's refused DERIVED shoe (Ruling A40: kept beside the fresh fit that
    followed it), ``_entry``'s shape; None without one of the body's current fit fingerprint. ``refused`` (it may
    be accepted while it is current and the body holds no accepted fit), ``user_accepted`` (the body's fit IS
    it), ``stale`` (made on an older body, shoe source or algorithm)."""
    from app.core import garment_store as gs
    found = attempt_of(character_name, item_id, body, DERIVED)
    if found is None:
        return None
    glb, record, marks_path = found
    status = fit_status(character_name, item_id, body, profile=profile)
    if not status["fsig"] or record.get("fsig") != status["fsig"]:
        return None
    attempt = record.get("attempt") or {}
    fit_record = gs.read_record(gs.garment_path(character_name, item_id, status["fsig"], "fit",
                                                body=body).with_suffix(".json"))
    block = fit_record.get("user_accepted") if isinstance(fit_record.get("user_accepted"), dict) else {}
    entry: Dict[str, Any] = {"body": body, "key": body + DERIVED_KEY_SUFFIX,
                             "label": body_label(character_name, body, profile=profile, names=names or {}),
                             "status": "refused", "reason": "", "reason_detail": "", "piece_broken": False,
                             "url": None, "built_at": attempt.get("at"), "marks": [], "foot_pose":
                             record.get("foot_pose"), "can_accept": False, "accept_block": "", "accepted_at": None,
                             "method_note": FIT_METHOD_NOTES["derived"], "variant": DERIVED,
                             "_shown": (glb, marks_path is not None) if glb is not None else None,
                             "arm_light": (record.get("report") or {}).get("arm_light"),
                             "numbers": body_numbers(record), "fit": body_fit_view(item_id, record, profile,
                                                                                    accepted=False)}
    plain = plain_reason(str(attempt.get("error") or ""), attempt.get("gates"), on_shape=True)
    entry.update(reason=plain["text"], reason_detail=plain["detail"], piece_broken=plain["piece"])
    entry["marks"] = [{"kind": k, "count": int(n), **MARK_KINDS[k]}
                      for k, n in sorted((attempt.get("marks") or {}).items()) if k in MARK_KINDS]
    if (status["state"] == "accepted" and str(block.get("slot") or "") == DERIVED
            and block.get("attempt_sha256") == attempt.get("glb_sha256")):
        entry.update(status="user_accepted", accepted_at=block.get("at"))
        return entry
    why = _current(character_name, item_id, body, record, profile)
    if why and status["state"] != "accepted":
        entry.update(status="stale", reason=("Made on an older body, piece or fit algorithm — "
                                             "the next Build fits it again"), reason_detail="")
        return entry
    entry["accept_block"] = ("This refusal came before a fit was made — there is nothing to accept"
                             if glb is None else why)
    entry["can_accept"] = not entry["accept_block"]
    return entry


def parse_key(key: str) -> Tuple[str, str]:
    """``(body, slot)`` of a body switch key: "plain", an outfit body id, or an outfit body id +
    ``DERIVED_KEY_SUFFIX`` (its derived-shoe attempt, Ruling A40). ValueError for anything else."""
    from app.core import garment_store as gs
    key = str(key or "")
    slot = ""
    if key.endswith(DERIVED_KEY_SUFFIX):
        key, slot = key[:-len(DERIVED_KEY_SUFFIX)], DERIVED
    body = "" if key == "plain" and not slot else key
    if (body or slot) and not gs.is_body_id(body):
        raise ValueError(f"invalid body {str(key)[:40]!r}")
    return body, slot


def shown_file(character_name: str, item_id: str, key: str) -> Optional[Tuple[Path, Optional[Path]]]:
    """``(GLB, marks npz or None)`` the body switch shows for the body ``key`` (``parse_key``: "plain", an outfit
    body id, or a body shape's derived-shoe attempt) — ``bodies``' choice; None when it shows nothing. ValueError
    for a bad key or item."""
    from app.core import garment_store as gs
    body, slot = parse_key(key)
    if gs._garment_kind(item_id) not in KINDS:
        raise ValueError(f"{item_id} has no fits to show here")
    profile = _profile(character_name, None)
    entry = (_derived_entry(character_name, item_id, body, profile, {}) if slot
             else _entry(character_name, item_id, body, profile, {}))
    shown = (entry or {}).get("_shown")
    if not shown:
        return None
    path, marked = shown
    if not marked:
        return path, None
    found = attempt_of(character_name, item_id, body, slot)
    return path, (found[2] if found else None)
