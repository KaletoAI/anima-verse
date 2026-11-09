"""The garment mesh step — routed generation and decimation (plan
``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R5, R8, R10,
R13, Task 5).

From the two cut-outs of the garment (front + back) the routed
``mesh_garment`` occasion builds a raw mesh (``garments/raw/{item}_{fsig}.glb``,
asked for ``face_num=100000`` like the spike), Blender's ``lod.py`` reduces it
to about ``TARGET_TRIS`` triangles with UV seams kept (vertices welded at
the seams on import, ``merge_vertices``), and the reduced mesh
becomes ``garments/prepared/{item}_{fsig}.glb`` — the input of the fit. The
fit and every mesh gate run on this reduced mesh, so the gates measure what
ships (R8).

Gate of this step: the largest connected component must carry at least
``MIN_COMPONENT_SHARE`` of the surface area (R7). A generator that splits the
garment into floating pieces is refused. Two attempts, each a fresh backend
call with the backend's own random seed (R5); two refusals raise
``MeshGateRefused`` with both records and leave no prepared mesh.

Record ``prepared/{item}_{fsig}.json``: ``accepted``, ``tris_raw``,
``tris_prepared``, ``target_tris``, ``ratio``, ``backend``, ``routing`` (the
route meta of the result), ``largest_component_share``,
``min_component_share`` and ``attempts`` (one entry per attempt with the
same numbers plus ``ok`` / ``reasons``). The prepared GLB exists only when its
record is accepted; an accepted pair is reused unless ``force`` (R13).

Runs on the caller's worker thread (the orchestration holds
``garment_store.char_lock``); the generation itself goes through
``get_image_service().generate_mesh`` and thus the backend channel, the
decimation is a Blender process on the CPU.
"""
import os
from pathlib import Path
from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger("garment_mesh")

#: Triangle budget of a prepared garment mesh (R8).
TARGET_TRIS = 25000
#: What the generator is asked for (spike ``uniforge_hair.py``).
FACE_NUM = 100000
#: Gate: share of the surface area the largest connected component must carry (R7).
MIN_COMPONENT_SHARE = 0.98
#: Fresh backend calls before the step is refused (R5).
MAX_ATTEMPTS = 2


class MeshAttemptFailed(RuntimeError):
    """An attempt of the mesh step failed outright — generation (no backend,
    worker crash), delivery or decimation — instead of being gated.
    ``records`` holds EVERY attempt so far, the failed one last as
    ``{attempt, ok False, error, reasons}``, so an earlier refusal's numbers
    are not lost. The message is the error, plus the earlier refusals."""

    def __init__(self, error: str, records: List[Dict[str, Any]]):
        self.step = "mesh"
        self.view = None
        self.error = error
        self.records = list(records)
        earlier = "; ".join(f"attempt {r.get('attempt')} refused: " + ", ".join(r.get("reasons") or [])
                            for r in self.records[:-1])
        super().__init__(error + (f" (after {earlier})" if earlier else ""))


class MeshGateRefused(RuntimeError):
    """Both attempts of the mesh step failed the gate. ``records`` holds every
    attempt's numbers (shape of ``attempts`` in the step record)."""

    def __init__(self, step: str, view, records: List[Dict[str, Any]]):
        self.step = step
        self.view = view
        self.records = records
        shares = ", ".join(f"{r.get('largest_component_share')}" for r in records)
        super().__init__(f"garment mesh refused after {len(records)} attempts "
                         f"(largest component share {shares})")


def largest_component_share(path: Path) -> float:
    """Share of the surface area carried by the largest connected component
    of a static GLB, after welding coincident vertices (``garment_fit``)."""
    import numpy as np
    from app.core import garment_fit, glb_mesh
    positions, faces, uvs = glb_mesh.static_arrays(Path(path).read_bytes())[:3]
    welded, welded_faces, _inv = garment_fit.weld(positions, faces, uvs)
    _labels, shares = garment_fit.components(welded, welded_faces)
    shares = np.asarray(shares, dtype=float).ravel()
    return float(shares.max()) if shares.size else 0.0


def _kind(item_id: str) -> str:
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    if garment_set.garment_kind_of(item) == garment_set.CLOTHING:
        return garment_set.CLOTHING
    kind = str((item.get("garment") or {}).get("kind") or "")
    if item.get("category") != "garment" or not kind:
        raise ValueError(f"{item_id!r} is no garment item")
    return kind


def _gate(share: float) -> List[str]:
    if share < MIN_COMPONENT_SHARE:
        return [f"largest component share {share:.4f} < {MIN_COMPONENT_SHARE}"]
    return []


def generate(name: str, item_id: str, fsig: str, *, force: bool = False) -> Path:
    """The prepared (decimated) garment mesh of ``item_id`` under ``fsig``.

    Reuses an accepted prepared mesh unless ``force``. Otherwise up to
    ``MAX_ATTEMPTS`` times: ``generate_mesh`` on the ``mesh_garment``
    occasion from the front cut-out with the back cut-out as extra view, then
    ``refine.decimate_to(raw, TARGET_TRIS, …)`` and the component gate.

    ``view_body`` is left at ``"humanoid"`` (the ``generate_mesh`` default):
    there it only decides the slot handling — humanoid = the main image is the
    front, ``view_images`` adds back/left/right; ``"animal"`` would treat the
    main image as a LEFT profile. Props use the same default.

    FileNotFoundError when a cut-out is missing; ``MeshGateRefused`` after
    two gate refusals; ``MeshAttemptFailed`` (a RuntimeError, chained to the
    cause — ``NoRouteError``, ``BackendBusyError``, ``MediaGenerationDisabled``,
    a failed generation or decimation) when an attempt fails outright: no
    further attempt, every attempt's record rides on the exception. After an
    earlier refused attempt the step record is written as refused (with all
    attempts, the error last) and the prepared mesh removed; a failure of
    the FIRST attempt writes nothing beyond the raw file.
    """
    from app.core import garment_store as gs

    prepared = gs.garment_path(name, item_id, fsig, "prepared")
    record_path = prepared.with_suffix(".json")
    if not force and prepared.is_file() and gs.read_record(record_path).get("accepted") is True:
        return prepared

    kind = _kind(item_id)
    cut = {view: gs.garment_path(name, item_id, fsig, "image", step="cutout", view=view)
           for view in gs.GARMENT_VIEWS}
    for view, path in cut.items():
        if not path.is_file():
            raise FileNotFoundError(f"garment cut-out ({view}) missing: {path.name}")
    raw = gs.garment_path(name, item_id, fsig, "raw")
    raw.parent.mkdir(parents=True, exist_ok=True)
    prepared.parent.mkdir(parents=True, exist_ok=True)
    # Decimated here first and renamed onto ``prepared`` only once accepted,
    # so a prepared GLB never exists without its accepted record.
    candidate = prepared.with_name(f".{prepared.stem}.candidate.glb")

    attempts: List[Dict[str, Any]] = []
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                entry = _attempt(name, kind, cut, raw, candidate, attempt)
            except Exception as e:  # noqa: BLE001 — recorded with the attempts before it, then re-raised
                error = str(e) or type(e).__name__
                attempts.append({"attempt": attempt, "ok": False, "error": error, "reasons": [error]})
                logger.info("garment mesh %s/%s attempt %d failed: %s", name, item_id, attempt, error)
                gated = [a for a in attempts if "largest_component_share" in a]
                if gated:
                    prepared.unlink(missing_ok=True)
                    gs.write_record(record_path, _record(kind, item_id, fsig, gated[-1], attempts,
                                                         accepted=False, error=error))
                raise MeshAttemptFailed(error, attempts) from e
            attempts.append(entry)
            logger.info("garment mesh %s/%s attempt %d: %s tris -> %s, largest component %.4f%s",
                        name, item_id, attempt, entry["tris_raw"], entry["tris_prepared"],
                        entry["largest_component_share"], "" if entry["ok"] else " (refused)")
            if entry["ok"]:
                break
        last = attempts[-1]
        record = _record(kind, item_id, fsig, last, attempts, accepted=bool(last["ok"]))
        if last["ok"]:
            os.replace(candidate, prepared)
            gs.write_record(record_path, record)
            return prepared
        # Refused: an older accepted mesh of this fsig must not stay behind
        # a record that now says otherwise.
        prepared.unlink(missing_ok=True)
        gs.write_record(record_path, record)
        raise MeshGateRefused("mesh", None, attempts)
    finally:
        candidate.unlink(missing_ok=True)


def _record(kind: str, item_id: str, fsig: str, last: Dict[str, Any], attempts: List[Dict[str, Any]], *,
            accepted: bool, error: str = "") -> Dict[str, Any]:
    """The step record; the numbers are those of ``last`` (a gated attempt)."""
    from app.core.timeutils import utc_now_iso
    record = {"accepted": accepted, "kind": kind, "item_id": item_id, "fsig": fsig,
              "target_tris": TARGET_TRIS, "face_num": FACE_NUM,
              "min_component_share": MIN_COMPONENT_SHARE,
              "tris_raw": last["tris_raw"], "tris_prepared": last["tris_prepared"],
              "ratio": last["ratio"], "backend": last["backend"], "routing": last["routing"],
              "largest_component_share": last["largest_component_share"],
              "attempts": attempts, "created_at": utc_now_iso()}
    if "fallback_from" in last:
        record["fallback_from"] = last["fallback_from"]
    if error:
        record["error"] = error
    return record


def _attempt(name: str, kind: str, cut: Dict[str, Path], raw: Path, candidate: Path,
             attempt: int) -> Dict[str, Any]:
    """One fresh generation + decimation + gate; the attempt's record.
    Raises when the generation or the decimation fails."""
    from app.blender import refine
    from app.imagegen.service import get_image_service
    res = get_image_service().generate_mesh(
        source_image_path=str(cut["front"]), output_path=str(raw),
        character_name=name, mesh_name=f"{name}-{kind}",
        view_images={"back": str(cut["back"])}, occasion="mesh_garment",
        face_num=FACE_NUM, material="dielectric", alpha="opaque")
    if not res.get("ok"):
        raise RuntimeError(f"garment mesh generation failed: {res.get('error') or 'unknown error'}")
    delivered = Path(str(res.get("path") or ""))
    if delivered.suffix.lower() != ".glb" or not delivered.is_file():
        raise RuntimeError(f"garment mesh generation delivered no GLB ({delivered.name or 'nothing'})")
    if delivered != raw:
        os.replace(delivered, raw)
    # Welded on import: split at its UV seams the mesh would tear
    # apart under the collapse (2026-11-09: share 0.982 -> 0.724).
    dec = refine.decimate_to(raw, TARGET_TRIS, candidate, merge_vertices=True)
    if not dec.get("ok"):
        raise RuntimeError(f"garment mesh decimation failed: {dec.get('error') or 'unknown error'}")
    share = largest_component_share(candidate)
    reasons = _gate(share)
    entry = {"attempt": attempt, "ok": not reasons, "reasons": reasons,
             "backend": res.get("backend", ""),
             "routing": res.get("routing") or {},
             **({"fallback_from": res["fallback_from"]} if res.get("fallback_from") else {}),
             "tris_raw": dec.get("tris_before"), "tris_prepared": dec.get("tris"),
             "ratio": dec.get("ratio"), "largest_component_share": share}
    return entry
