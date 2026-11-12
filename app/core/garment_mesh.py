"""The garment mesh step — routed generation and decimation (plan
``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R5, R8, R10,
R13, Task 5).

From the two cut-outs of the garment (front + back) the routed mesh
occasion (``mesh_occasion``: ``mesh_garment``; hair has no mesh step since the
hair edit chain was removed) builds a raw mesh (``garments/raw/{item}_{fsig}.glb``,
asked for ``face_num=100000`` like the spike), Blender's ``lod.py`` reduces it
to about ``target_tris(kind)`` triangles (clothing 60000 — the spike dress
worked on its undecimated 71k-vertex mesh, a body-sized piece needs more
triangles than the 25000 of ``TARGET_TRIS``) with UV seams kept (vertices welded at
the seams on import, ``merge_vertices``), and the reduced mesh
becomes ``garments/prepared/{item}_{fsig}.glb`` — the input of the fit. The
fit and every mesh gate run on this reduced mesh, so the gates measure what
ships (R8).

Gate of this step (R7, ``component_numbers``): crumbs — detached components
below ``garment_fit.MIN_COMPONENT_SHARE`` (0.002) of the area, the ones the
fit's weld step drops anyway (R8) — leave the measurement; of the rest the
largest connected component must carry at least ``MIN_COMPONENT_SHARE`` of
the area. Only a truly fragmented mesh (a torn or split surface) is refused;
a few crumbs or a detached strip beside the body are not worth a new mesher
run. Two attempts, each a fresh backend call with the backend's own random
seed (R5); two refusals raise ``MeshGateRefused`` with both records and leave
no prepared mesh. The prepared GLB is the decimation's output unchanged — the
crumbs stay in it and the fit drops them, so the gate measures what the fit
ships.

A stored raw mesh refused under an older gate (``GATE_VERSION``) is judged
again before the mesher is asked (``generate``): a better gate must not cost
a new mesher run for a mesh it accepts.

Record ``prepared/{item}_{fsig}.json``: ``accepted``, ``tris_raw``,
``tris_prepared``, ``target_tris``, ``ratio``, ``backend``, ``routing`` (the
route meta of the result), ``largest_component_share`` (after the crumbs),
``largest_component_share_all`` (with them), ``dropped_share`` /
``dropped_components`` (the crumbs), ``crumb_share``, ``min_component_share``,
``gate_version`` and ``attempts`` (one entry per attempt with the same
numbers plus ``ok`` / ``reasons``; ``stored_raw`` on a re-judged stored
raw). The prepared GLB exists only when its
record is accepted; an accepted pair is reused unless ``force`` (R13).

Runs on the caller's worker thread (the orchestration holds
``garment_store.char_lock``); the generation itself goes through
``get_image_service().generate_mesh`` and thus the backend channel, the
decimation is a Blender process on the CPU.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("garment_mesh")

#: Triangle budget of a prepared garment mesh (R8); kinds with their own in ``TARGET_TRIS_BY_KIND``.
TARGET_TRIS = 25000
#: Per-kind triangle budgets that differ from ``TARGET_TRIS`` (phase 5: a clothing piece covers the body).
TARGET_TRIS_BY_KIND = {"clothing": 60000}
#: What the generator is asked for (the hair spike's ``uniforge_hair.py``).
FACE_NUM = 100000
#: Gate: share of the surface area the largest connected component must carry, measured after the crumbs
#: (``garment_fit.drop_small``, components below 0.002 of the area) are left out (R7).
#:
#: Was 0.98 on the whole mesh, crumbs included (spike value). Measured 2026-11-12 on the prepared (decimated)
#: meshes, every detached component within 0.008 of the garment height of the main one (seam strips and slivers
#: the mesher split off, none floating) — share with crumbs / without / crumbs dropped:
#:   Kira's Black Blazer (accepted)     0.9968 / 0.9971 /  7 crumbs 0.03 %
#:   spike dress (accepted, phase 5)    0.9859 / 0.9886 / 31 crumbs 0.27 %
#:   Kai's Black Lederjacket            0.9619 / 0.9672 / 57 crumbs 0.55 %, 7 strips kept (1.5 %, 0.5 %, < 0.3 %)
#: The jacket looks right (user ruling 2026-11-12) and the fit handles kept strips per vertex — the spike dress
#: shipped with two of them. What the gate stops is a torn or split surface: the hair mesh decimated without
#: welding its UV seams fell to 0.724 (commit 32249153), the seam-split sphere of ``smoke_garment_mesh`` to
#: 0.50. 0.90 lies between 0.967 and 0.724: it tolerates three times the jacket's detached area and refuses a
#: mesh whose second piece is the size of a sleeve or a panel (10 % of the area). The fit gates the same number
#: with the same limit (``garment_fit.CLOTHING_GATES``).
MIN_COMPONENT_SHARE = 0.90
#: Version of the gate rule, stamped on the step record: a stored raw refused under an older version is judged
#: again before the mesher is asked (``generate``). 2 = crumbs left out, limit 0.90 (2026-11-12).
GATE_VERSION = 2
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


def component_numbers(path: Path) -> Dict[str, Any]:
    """The component numbers of a static GLB after welding coincident
    vertices (``garment_fit.weld``): ``largest_component_share`` = the
    largest component's share of the area WITHOUT the crumbs (the gate
    number), ``largest_component_share_all`` = its share of the whole area,
    ``dropped_share`` / ``dropped_components`` = the crumbs (components below
    ``garment_fit.MIN_COMPONENT_SHARE`` of the whole area — the rule of the
    fit's ``drop_small``, so the fit sees exactly the kept components) and
    ``components_kept``."""
    import numpy as np
    from app.core import garment_fit, glb_mesh
    positions, faces, uvs = glb_mesh.static_arrays(Path(path).read_bytes())[:3]
    welded, welded_faces, _inv = garment_fit.weld(positions, faces, uvs)
    _labels, shares = garment_fit.components(welded, welded_faces)
    shares = np.asarray(shares, dtype=float).ravel()
    crumb = shares < garment_fit.MIN_COMPONENT_SHARE
    kept = float(shares[~crumb].sum())
    largest = float(shares.max()) if shares.size else 0.0
    return {"largest_component_share": largest / kept if kept > 0 else 0.0,
            "largest_component_share_all": largest,
            "dropped_share": float(shares[crumb].sum()),
            "dropped_components": int(crumb.sum()),
            "components_kept": int((~crumb).sum())}


def largest_component_share(path: Path) -> float:
    """The gate number of ``component_numbers``: the largest connected
    component's share of the area without the crumbs."""
    return component_numbers(path)["largest_component_share"]


def _kind(item_id: str) -> str:
    """The garment kind whose mesh this module makes (clothing); ValueError
    for footwear (its mesh is the item's shoe source, ``footwear_source``),
    for hair (no mesh step: HairDeck or the body mesh) and for anything that
    is no garment item."""
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    kind = garment_set.garment_kind_of(item)
    if kind == garment_set.FOOTWEAR:
        raise ValueError(f"{item_id!r} is footwear: its mesh is the shoe source's")
    if kind == garment_set.CLOTHING:
        return garment_set.CLOTHING
    if kind == garment_set.HAIR:
        raise ValueError(f"{item_id!r} is hair: it has no mesh step")
    raise ValueError(f"{item_id!r} is no garment item with a mesh step")


def target_tris(kind: str) -> int:
    """The decimation target of a garment kind's prepared mesh."""
    return int(TARGET_TRIS_BY_KIND.get(kind, TARGET_TRIS))


def mesh_occasion(kind: str) -> str:
    """The routing occasion of a kind's mesh step: ``mesh_garment`` (clothing,
    the only kind with one)."""
    return "mesh_garment"


def _gate(share: float) -> List[str]:
    """The refusal reasons of the gate number (``component_numbers``)."""
    if share < MIN_COMPONENT_SHARE:
        return [f"largest component share {share:.4f} < {MIN_COMPONENT_SHARE} (crumbs left out)"]
    return []


def generate(name: str, item_id: str, fsig: str, *, force: bool = False) -> Path:
    """The prepared (decimated) garment mesh of ``item_id`` under ``fsig``.

    Reuses an accepted prepared mesh unless ``force``. Without ``force`` a
    stored raw mesh that the current gate has not judged yet (no record, or
    a record of an older ``GATE_VERSION``; newer than both cut-outs — new
    images drop the raw anyway) is decimated and gated again first
    (``_stored_attempt``): accepted, it becomes the prepared mesh without a
    mesher call; refused, the fresh attempts follow. Otherwise up to
    ``MAX_ATTEMPTS`` times: ``generate_mesh`` on the kind's occasion
    (``mesh_occasion``) from the front cut-out with the back cut-out as extra view (none
    when the piece's drafted back is EMPTY — ``garment_images.skipped_view``: nothing of it
    shows from behind, the mesher gets the front alone), then
    ``refine.decimate_to(raw, target_tris(kind), …)`` and the component gate.

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
    from app.core.garment_images import skipped_view
    # An empty drafted back has no cut-out: the mesh is made from the front alone.
    cut = {view: gs.garment_path(name, item_id, fsig, "image", step="cutout", view=view)
           for view in gs.GARMENT_VIEWS if not skipped_view(name, item_id, fsig, "cutout", view)}
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
        if not force:
            old = gs.read_record(record_path)
            stored = _stored_attempt(name, item_id, kind, cut, raw, candidate, old)
            if stored is not None:
                record = _record(kind, item_id, fsig, stored, [stored], accepted=True)
                if stored.get("collected_job"):
                    record["collected_job"] = stored["collected_job"]
                if old.get("attempts"):
                    record["earlier_attempts"] = old["attempts"]  # what the older gate made of them
                os.replace(candidate, prepared)
                gs.write_record(record_path, record)
                return prepared
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
    from app.core.garment_fit import MIN_COMPONENT_SHARE as CRUMB_SHARE
    record = {"accepted": accepted, "kind": kind, "item_id": item_id, "fsig": fsig,
              "target_tris": target_tris(kind), "face_num": FACE_NUM,
              "min_component_share": MIN_COMPONENT_SHARE, "crumb_share": CRUMB_SHARE,
              "gate_version": GATE_VERSION,
              "tris_raw": last["tris_raw"], "tris_prepared": last["tris_prepared"],
              "ratio": last["ratio"], "backend": last["backend"], "routing": last["routing"],
              "largest_component_share": last["largest_component_share"],
              **{key: last[key] for key in _CRUMB_KEYS if key in last},
              "attempts": attempts, "created_at": utc_now_iso()}
    if "fallback_from" in last:
        record["fallback_from"] = last["fallback_from"]
    if error:
        record["error"] = error
    return record


#: The crumb numbers of ``component_numbers`` an attempt entry and the step record carry.
_CRUMB_KEYS = ("largest_component_share_all", "dropped_share", "dropped_components", "components_kept")


def _stored_attempt(name: str, item_id: str, kind: str, cut: Dict[str, Path], raw: Path, candidate: Path,
                    old: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The stored raw mesh judged again by the current gate — the accepted
    attempt entry (``stored_raw`` True, ``candidate`` written) or None.

    Only when the current gate has not judged it yet: ``old`` (the step
    record) is missing or of another ``GATE_VERSION``, and the raw is newer
    than both cut-outs. The entry keeps the stored attempt's number,
    backend, routing and collected job (those of ``old``'s last gated
    attempt). A refusal or a failed decimation returns None: the fresh
    attempts follow, as without a stored raw."""
    if not raw.is_file() or old.get("gate_version") == GATE_VERSION:
        return None
    if raw.stat().st_mtime < max(path.stat().st_mtime for path in cut.values()):
        return None
    gated = [a for a in old.get("attempts") or [] if "largest_component_share" in a]
    last = gated[-1] if gated else {}
    res = {"backend": last.get("backend", old.get("backend", "")),
           "routing": last.get("routing") or old.get("routing") or {},
           "fallback_from": last.get("fallback_from")}
    try:
        entry = _prepare(kind, raw, candidate, int(last.get("attempt") or 1), res)
    except Exception as e:  # noqa: BLE001 — the fresh attempts decide
        logger.info("garment mesh %s/%s: stored raw not judged again: %s", name, item_id, e)
        return None
    logger.info("garment mesh %s/%s: stored raw judged again (gate %d, was %s): largest component %.4f%s",
                name, item_id, GATE_VERSION, old.get("gate_version", 1 if old else "unjudged"),
                entry["largest_component_share"], "" if entry["ok"] else " (refused)")
    if not entry["ok"]:
        candidate.unlink(missing_ok=True)
        return None
    entry["stored_raw"] = True
    collected = last.get("collected_job") or old.get("collected_job")
    if collected:
        entry["collected_job"] = collected
    return entry


def _attempt(name: str, kind: str, cut: Dict[str, Path], raw: Path, candidate: Path,
             attempt: int) -> Dict[str, Any]:
    """One fresh generation + decimation + gate; the attempt's record.
    Raises when the generation or the decimation fails."""
    from app.imagegen.service import get_image_service
    res = get_image_service().generate_mesh(
        source_image_path=str(cut["front"]), output_path=str(raw),
        character_name=name, mesh_name=f"{name}-{kind}",
        view_images={view: str(path) for view, path in cut.items() if view != "front"},
        occasion=mesh_occasion(kind),
        face_num=FACE_NUM, material="dielectric", alpha="opaque")
    if not res.get("ok"):
        raise RuntimeError(f"garment mesh generation failed: {res.get('error') or 'unknown error'}")
    delivered = Path(str(res.get("path") or ""))
    if delivered.suffix.lower() != ".glb" or not delivered.is_file():
        raise RuntimeError(f"garment mesh generation delivered no GLB ({delivered.name or 'nothing'})")
    if delivered != raw:
        os.replace(delivered, raw)
    return _prepare(kind, raw, candidate, attempt, res)


def _prepare(kind: str, raw: Path, candidate: Path, attempt: int, res: Dict[str, Any]) -> Dict[str, Any]:
    """Decimation + gate of a delivered raw mesh — the half of an attempt
    after the generation, shared by a fresh attempt and a collected job
    (``collect_job``). ``res`` is the generation's result (``backend``,
    ``routing``, ``fallback_from``). Raises when the decimation fails."""
    from app.blender import refine
    # Welded on import: split at its UV seams the mesh would tear
    # apart under the collapse (2026-11-09: share 0.982 -> 0.724).
    dec = refine.decimate_to(raw, target_tris(kind), candidate, merge_vertices=True)
    if not dec.get("ok"):
        raise RuntimeError(f"garment mesh decimation failed: {dec.get('error') or 'unknown error'}")
    numbers = component_numbers(candidate)
    reasons = _gate(numbers["largest_component_share"])
    entry = {"attempt": attempt, "ok": not reasons, "reasons": reasons,
             "backend": res.get("backend", ""),
             "routing": res.get("routing") or {},
             **({"fallback_from": res["fallback_from"]} if res.get("fallback_from") else {}),
             "tris_raw": dec.get("tris_before"), "tris_prepared": dec.get("tris"),
             "ratio": dec.get("ratio"), **numbers}
    return entry


#: What a collected job's answer is when the step itself fails (decimation) — the job was fine.
STEP_FAILED = "step_failed"


def collect_job(name: str, item_id: str, fsig: str, job_id: str) -> Dict[str, Any]:
    """Collect a FINISHED gateway mesh job by its id as this fsig's mesh —
    the way back to a mesh step whose run outlived our own poll (timeout,
    server restart) but finished on the gateway.

    ``get_image_service().fetch_mesh_job`` (rig ``none``: a garment mesh is
    unrigged) downloads the result into a staging folder; the SAME
    ``_prepare`` (decimation + component gate) as a fresh attempt runs on
    the staged file. Accepted: ``raw`` + ``prepared`` + the step record (one
    attempt) plus ``collected_job`` = the job's full id, so the next run
    reuses the pair (R13) and runs only the fit.

    A refused or failed fetch NEVER touches an accepted mesh of this fsig (a
    wrong pasted id must not destroy a good mesh): nothing is written and
    the answer carries ``kept: True``. Only without an accepted mesh is a
    refusal written like a refused step (raw + the refused record).

    Returns ``{status: "accepted" | "refused", job_id, record?, reasons?,
    error?, kept?}``; ``{status: STEP_FAILED, job_id, error, kept}`` when the
    decimation fails (nothing written); else the fetch's own answer with
    nothing written: ``queued`` / ``running`` (+ ``progress``) or
    ``unknown`` / ``forbidden`` / ``failed`` / ``rig_mismatch`` / ``error``
    (+ ``error``). Blocking (download + Blender); the caller holds
    ``garment_store.char_lock`` (``garments.collect_mesh_job``)."""
    import shutil
    import tempfile
    from app.core import garment_store as gs
    from app.imagegen.service import get_image_service

    kind = _kind(item_id)
    prepared = gs.garment_path(name, item_id, fsig, "prepared")
    record_path = prepared.with_suffix(".json")
    raw = gs.garment_path(name, item_id, fsig, "raw")
    raw.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".fetch-", dir=raw.parent))
    candidate = staging / "candidate.glb"
    try:
        res = get_image_service().fetch_mesh_job(job_id, str(staging / raw.name), rig="none")
        if res.get("status") != "stored":
            return res
        full = str(res.get("job_id") or job_id)
        delivered = Path(str(res.get("path") or ""))
        if delivered.suffix.lower() != ".glb" or not delivered.is_file():
            return {"status": "error", "job_id": full,
                    "error": f"job {full} delivered no GLB ({delivered.name or 'nothing'})"}
        kept = prepared.is_file() and gs.read_record(record_path).get("accepted") is True
        try:
            entry = _prepare(kind, delivered, candidate, 1, {"backend": res.get("backend", ""), "routing": {}})
        except Exception as e:  # noqa: BLE001 — the step failed, the job was fine
            error = str(e) or type(e).__name__
            logger.info("garment mesh %s/%s: collected job %s failed: %s", name, item_id, full, error)
            return {"status": STEP_FAILED, "job_id": full, "error": error, "kept": kept}
        entry["collected_job"] = full
        record = _record(kind, item_id, fsig, entry, [entry], accepted=bool(entry["ok"]))
        record["collected_job"] = full
        logger.info("garment mesh %s/%s: collected job %s: %s tris -> %s, largest component %.4f%s", name,
                    item_id, full, entry["tris_raw"], entry["tris_prepared"], entry["largest_component_share"],
                    "" if entry["ok"] else (" (refused, accepted mesh kept)" if kept else " (refused)"))
        if entry["ok"]:
            prepared.parent.mkdir(parents=True, exist_ok=True)
            os.replace(delivered, raw)
            os.replace(candidate, prepared)
            gs.write_record(record_path, record)
            return {"status": "accepted", "job_id": full, "record": record}
        refused = {"status": "refused", "job_id": full, "reasons": list(entry["reasons"]), "kept": kept,
                   "largest_component_share": entry["largest_component_share"],
                   "error": f"garment mesh refused ({', '.join(entry['reasons'])})"}
        if kept:
            return refused  # the accepted mesh stays exactly as it is
        os.replace(delivered, raw)
        prepared.unlink(missing_ok=True)
        gs.write_record(record_path, record)
        return {**refused, "record": record}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
