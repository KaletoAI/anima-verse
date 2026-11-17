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

Ruling A48a: every REFUSED attempt keeps its decimated mesh and its raw output
(``garments/attempts/mesh/{item}_{fsig}.try{n}[.raw].glb``, ``keep_attempt``) — the Wardrobe's Mesh row shows
each beside the mesh in use; an attempt that failed outright has no file.

Ruling A58 — the KEPT meshes of an fsig: slots ``try1`` .. ``try{KEPT_MAX}`` of that folder, each described by
an entry of the step record's ``kept`` list (``{n, origin, ok, reasons, created_at, tris_raw, tris_prepared,
largest_component_share, backend, …}``). Origins: ``attempt`` (a refused attempt), ``previous`` (the mesh that was
in use before a run or a pick replaced it) and ``job`` (a run's result that finished while the user had chosen
another mesh). The record is the piece's mesh JSON; every write of it — a run's publish, a kept attempt, the
user's pick (``use_kept``) — happens under ``mesh_lock`` (``keyed_lock("garment_mesh", "<name>:<item>")``), which
is NEVER held across the hub call. While a run's mesh job runs (``running_job``: its id, start, hub-job count),
the user may pick any kept mesh ("Use this"); the pick writes ``chosen_during_job`` (the job's id) into the
record. When the job ends, its publish reads that marker under the same lock: picked during the run, its result
becomes a kept mesh (origin ``job``, ``chosen_during_job`` True) and the user's pick stays; else it becomes the
piece's mesh as before and the mesh it replaces is kept (origin ``previous``). A full set of slots drops its
oldest refused attempt first, then its oldest kept mesh. The generator writes into a staging file beside the raw
mesh, so the raw file of the mesh in use is never overwritten mid-run.

Runs on the caller's worker thread (the orchestration holds
``garment_store.char_lock``); the generation itself goes through
``get_image_service().generate_mesh`` and thus the backend channel, the
decimation is a Blender process on the CPU.
"""
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
#: Fresh backend calls before the step is refused (R5). A176: ONE — a refused mesh is kept and offered ("Use this"
#: / Regenerate), never meshed again on its own.
MAX_ATTEMPTS = 1
#: Ruling A58: slots of the kept meshes of one fsig (refused attempts, the meshes a run or a pick replaced, a
#: result that finished while another mesh was chosen). Enough for two runs of two attempts plus the meshes in
#: between; a full set drops its oldest refused attempt first (``_free_slot``).
KEPT_MAX = 6
#: ``kept`` entry origins (Ruling A58).
KEPT_ATTEMPT = "attempt"
KEPT_PREVIOUS = "previous"
KEPT_JOB = "job"
#: The line a result that finished while the user had chosen another mesh carries (Ruling A58).
NOT_APPLIED = "Finished while another mesh was chosen — not applied"


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
    number; Ruling A122: a mirrored pair's two components together, ``component_pair`` True),
    ``largest_component_share_all`` = the largest's share of the whole area,
    ``dropped_share`` / ``dropped_components`` = the crumbs (components below
    ``garment_fit.MIN_COMPONENT_SHARE`` of the whole area — the rule of the
    fit's ``drop_small``, so the fit sees exactly the kept components) and
    ``components_kept``."""
    import numpy as np
    from app.core import garment_fit, glb_mesh
    positions, faces, uvs = glb_mesh.static_arrays(Path(path).read_bytes())[:3]
    welded, welded_faces, _inv = garment_fit.weld(positions, faces, uvs)
    labels, shares = garment_fit.components(welded, welded_faces)
    shares = np.asarray(shares, dtype=float).ravel()
    crumb = shares < garment_fit.MIN_COMPONENT_SHARE
    kept = float(shares[~crumb].sum())
    largest = float(shares.max()) if shares.size else 0.0
    # Ruling A122: a mirrored pair (boots, gloves) counts as one piece (``garment_fit.pair_share``).
    gated, paired = garment_fit.pair_share(welded, labels, shares)
    return {"largest_component_share": gated / kept if kept > 0 else 0.0,
            "component_pair": bool(paired),
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


class KeptUnusable(ValueError):
    """``use_kept``: the slot holds no kept mesh (a route answers 409)."""


# --- Ruling A58: the running mesh job and the piece's mesh lock -------------------------------------------------

_jobs_lock = threading.Lock()
#: (name, item) -> the mesh job of the run in flight: ``{id, fsig, started_at, hub_jobs, max_hub_jobs, phase}``.
_jobs: Dict[Tuple[str, str], Dict[str, Any]] = {}


def mesh_lock(name: str, item_id: str):
    """The piece's mesh lock (Ruling A58): every write of the step record, of the prepared / raw mesh and of the kept
    meshes of any fsig of the piece. Never held across a hub call; lock order: the run locks
    (``garment_store.char_lock`` / ``run_item_lock``) before it, nothing holding it waits for them."""
    from app.core.keyed_lock import keyed_lock
    return keyed_lock("garment_mesh", f"{name}:{item_id}")


def running_job(name: str, item_id: str, fsig: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A copy of the piece's mesh job in flight (``generate``) — of ``fsig`` when given — or None."""
    with _jobs_lock:
        job = _jobs.get((name, item_id))
        if job is None or (fsig is not None and job.get("fsig") != fsig):
            return None
        return dict(job)


def _begin_job(name: str, item_id: str, fsig: str) -> str:
    from app.core.timeutils import utc_now_iso
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[(name, item_id)] = {"id": job_id, "fsig": fsig, "started_at": utc_now_iso(), "hub_jobs": 0,
                                  "max_hub_jobs": MAX_ATTEMPTS, "phase": "starting"}
    return job_id


def _job_update(name: str, item_id: str, job_id: str, **changes: Any) -> None:
    with _jobs_lock:
        job = _jobs.get((name, item_id))
        if job is not None and job.get("id") == job_id:
            job.update(changes)


def _end_job(name: str, item_id: str, job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get((name, item_id))
        if job is not None and job.get("id") == job_id:
            _jobs.pop((name, item_id), None)


# --- Ruling A58: kept meshes --------------------------------------------------------------------------------------

#: The numbers a kept entry carries from its attempt (or from the record of the mesh it was).
_ENTRY_KEYS = ("tris_raw", "tris_prepared", "ratio", "backend", "routing", "largest_component_share",
               "fallback_from", "collected_job", "stored_raw", "largest_component_share_all", "dropped_share",
               "dropped_components", "components_kept")


def kept_entries(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The valid ``kept`` entries of a step record (Ruling A58), slot numbers 1..KEPT_MAX, each slot once, in slot
    order (a tile keeps its place when "Use this" swaps its mesh)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for entry in record.get("kept") or []:
        if not isinstance(entry, dict):
            continue
        n = entry.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= KEPT_MAX or n in seen:
            continue
        seen.add(n)
        out.append(entry)
    return sorted(out, key=lambda e: e["n"])


def _drop_slot(name: str, item_id: str, fsig: str, n: int) -> None:
    from app.core import garment_store as gs
    for part in MESH_PARTS:
        gs.garment_path(name, item_id, fsig, part, attempt=n).unlink(missing_ok=True)


#: The file parts of a kept slot.
MESH_PARTS = ("mesh_attempt", "mesh_attempt_raw")


def _free_slot(name: str, item_id: str, fsig: str, kept: List[Dict[str, Any]]) -> int:
    """A free slot for a new kept mesh; a full set drops its oldest refused attempt first, then its oldest kept
    mesh (``kept`` is changed in place; the caller writes the record)."""
    used = {e["n"] for e in kept}
    for n in range(1, KEPT_MAX + 1):
        if n not in used:
            _drop_slot(name, item_id, fsig, n)  # a stray file of an older record
            return n
    refused = [e for e in kept if e.get("origin") == KEPT_ATTEMPT]
    victim = min(refused or kept, key=lambda e: (str(e.get("created_at") or ""), e["n"]))
    kept.remove(victim)
    _drop_slot(name, item_id, fsig, victim["n"])
    return victim["n"]


def _move_into(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, dest)


def _keep(name: str, item_id: str, fsig: str, kept: List[Dict[str, Any]], prepared: Path, raw: Optional[Path],
          entry: Dict[str, Any], *, move: bool) -> int:
    """Store a mesh as a kept slot (caller holds ``mesh_lock``): its decimated ``prepared`` and its ``raw`` file
    (moved, or copied when ``move`` is False — ``keep_attempt``), plus ``entry`` (with its new ``n``) appended to
    ``kept``. The slot number."""
    from app.core import garment_store as gs
    n = _free_slot(name, item_id, fsig, kept)
    if move:
        _move_into(prepared, gs.garment_path(name, item_id, fsig, "mesh_attempt", attempt=n))
        if raw is not None and Path(raw).is_file():
            _move_into(raw, gs.garment_path(name, item_id, fsig, "mesh_attempt_raw", attempt=n))
    else:
        keep_attempt(name, item_id, fsig, n, prepared, raw if raw is not None else Path(""))
    kept.append({**entry, "n": n})
    return n


def _entry_of_attempt(entry: Dict[str, Any], origin: str, **extra: Any) -> Dict[str, Any]:
    from app.core.timeutils import utc_now_iso
    out = {"origin": origin, "ok": bool(entry.get("ok")), "reasons": list(entry.get("reasons") or []),
           "attempt": entry.get("attempt"), "created_at": entry.get("created_at") or utc_now_iso(),
           **{k: entry[k] for k in _ENTRY_KEYS if k in entry}}
    out.update(extra)
    return out


def _entry_of_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """The kept entry of the mesh a record describes now (it is about to be replaced): ``previous``."""
    return {"origin": KEPT_PREVIOUS, "ok": not record.get("user_accepted"),
            "reasons": list(record.get("user_reasons") or []), "created_at": record.get("created_at"),
            **{k: record[k] for k in _ENTRY_KEYS if k in record}}


def _picked_during(record: Dict[str, Any], job_id: str) -> bool:
    marker = record.get("chosen_during_job")
    return isinstance(marker, dict) and marker.get("job") == job_id


def _keep_refused(name: str, item_id: str, fsig: str, entry: Dict[str, Any], candidate: Path, raw: Path) -> None:
    """A refused attempt becomes a kept mesh at once (Ruling A48a/A58), under the mesh lock; the mesh in use stays."""
    from app.core import garment_store as gs
    if not Path(candidate).is_file():
        return
    record_path = gs.garment_path(name, item_id, fsig, "prepared").with_suffix(".json")
    try:
        with mesh_lock(name, item_id):
            record = gs.read_record(record_path)
            kept = kept_entries(record)
            _keep(name, item_id, fsig, kept, candidate, raw, _entry_of_attempt(entry, KEPT_ATTEMPT), move=False)
            if record:
                record["kept"] = kept
            else:
                record = {"accepted": False, "kind": "clothing", "item_id": item_id, "fsig": fsig, "attempts": [],
                          "kept": kept}
            gs.write_record(record_path, record)
    except (OSError, ValueError) as e:
        logger.warning("garment mesh %s/%s: refused attempt %s not kept: %s", name, item_id, entry.get("attempt"), e)


def _publish(name: str, item_id: str, fsig: str, kind: str, job_id: str, last: Dict[str, Any],
             attempts: List[Dict[str, Any]], candidate: Path, staged_raw: Path, *,
             extra: Optional[Dict[str, Any]] = None, error: str = "") -> bool:
    """The end of a run's mesh step, under the mesh lock (Ruling A58). Picked during the run (the record's
    ``chosen_during_job`` names ``job_id``): an accepted result becomes a kept mesh (origin ``job``) and the pick
    stays — False. Else the result is published as before — accepted: the new prepared + raw mesh and record, the
    mesh it replaces kept as ``previous``; refused (``last`` not ok): the record says refused and the mesh in use is
    kept as ``previous`` — True."""
    from app.core import garment_store as gs
    from app.core.timeutils import utc_now_iso
    prepared = gs.garment_path(name, item_id, fsig, "prepared")
    record_path = prepared.with_suffix(".json")
    raw = gs.garment_path(name, item_id, fsig, "raw")
    with mesh_lock(name, item_id):
        current = gs.read_record(record_path)
        kept = kept_entries(current)
        if _picked_during(current, job_id):
            if last.get("ok") and Path(candidate).is_file():
                _keep(name, item_id, fsig, kept, candidate, staged_raw,
                      _entry_of_attempt({**last, "created_at": utc_now_iso()}, KEPT_JOB, job=job_id,
                                        chosen_during_job=True), move=True)
            current["kept"] = kept
            gs.write_record(record_path, current)
            return False
        if prepared.is_file() and current.get("accepted") is True:
            _keep(name, item_id, fsig, kept, prepared, raw if raw.is_file() else None, _entry_of_record(current),
                  move=True)
        record = _record(kind, item_id, fsig, last, attempts, accepted=bool(last.get("ok")), error=error)
        record.update(extra or {})
        record["kept"] = kept
        if Path(staged_raw).is_file():
            os.replace(staged_raw, raw)
        if last.get("ok"):
            os.replace(candidate, prepared)
        else:
            # Refused: an older accepted mesh of this fsig must not stay behind a record that now says otherwise
            # (it was kept above).
            prepared.unlink(missing_ok=True)
        gs.write_record(record_path, record)
        return True


def generate(name: str, item_id: str, fsig: str, *, force: bool = False,
             outcome: Optional[Dict[str, Any]] = None) -> Path:
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

    Ruling A58: the run is the piece's mesh job (``running_job``) from its first attempt to its publish; each
    refused attempt is kept at once, the result is published under ``mesh_lock`` (``_publish``). When the user
    chose another mesh during the run (``use_kept``), the result is kept beside it and NOT applied:
    ``outcome["applied"]`` False (``outcome`` is filled when given), the returned path is the mesh in use, and
    neither ``MeshGateRefused`` nor ``MeshAttemptFailed`` is raised (the attempts are kept / logged).

    FileNotFoundError when a cut-out is missing; ``MeshGateRefused`` after
    two gate refusals; ``MeshAttemptFailed`` (a RuntimeError, chained to the
    cause — ``NoRouteError``, ``BackendBusyError``, ``MediaGenerationDisabled``,
    a failed generation or decimation) when an attempt fails outright: no
    further attempt, every attempt's record rides on the exception. After an
    earlier refused attempt the step record is written as refused (with all
    attempts, the error last) and the prepared mesh removed; a failure of
    the FIRST attempt writes nothing.
    """
    from app.core import garment_store as gs

    if outcome is None:
        outcome = {}
    outcome["applied"] = True
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
    job_id = _begin_job(name, item_id, fsig)
    # Decimated here first and renamed onto ``prepared`` only once accepted, so a prepared GLB never exists without
    # its accepted record; the generator writes beside the raw mesh in use (Ruling A58: it stays until the publish).
    candidate = prepared.with_name(f".{prepared.stem}.{job_id}.candidate.glb")
    staged_raw = raw.with_name(f".{raw.stem}.{job_id}.glb")

    attempts: List[Dict[str, Any]] = []
    try:
        if not force:
            old = gs.read_record(record_path)
            _job_update(name, item_id, job_id, phase="prepare")
            stored = _stored_attempt(name, item_id, kind, cut, raw, candidate, old)
            if stored is not None:
                extra: Dict[str, Any] = {}
                if stored.get("collected_job"):
                    extra["collected_job"] = stored["collected_job"]
                if old.get("attempts"):
                    extra["earlier_attempts"] = old["attempts"]  # what the older gate made of them
                applied = _publish(name, item_id, fsig, kind, job_id, stored, [stored], candidate, staged_raw,
                                   extra=extra)
                outcome["applied"] = applied
                return prepared
        for attempt in range(1, MAX_ATTEMPTS + 1):
            _job_update(name, item_id, job_id, hub_jobs=attempt, phase="hub")
            try:
                entry = _attempt(name, kind, cut, staged_raw, candidate, attempt)
            except Exception as e:  # noqa: BLE001 — recorded with the attempts before it, then re-raised
                error = str(e) or type(e).__name__
                attempts.append({"attempt": attempt, "ok": False, "error": error, "reasons": [error]})
                logger.info("garment mesh %s/%s attempt %d failed: %s", name, item_id, attempt, error)
                gated = [a for a in attempts if "largest_component_share" in a]
                with mesh_lock(name, item_id):
                    picked = _picked_during(gs.read_record(record_path), job_id)
                    if gated and not picked:
                        _publish(name, item_id, fsig, kind, job_id, gated[-1], attempts, candidate, staged_raw,
                                 error=error)
                if picked:
                    outcome.update(applied=False, error=error)
                    return prepared
                raise MeshAttemptFailed(error, attempts) from e
            _job_update(name, item_id, job_id, phase="prepare")
            from app.core.timeutils import utc_now_iso
            entry["created_at"] = utc_now_iso()
            attempts.append(entry)
            if not entry["ok"]:
                _keep_refused(name, item_id, fsig, entry, candidate, staged_raw)
            logger.info("garment mesh %s/%s attempt %d: %s tris -> %s, largest component %.4f%s",
                        name, item_id, attempt, entry["tris_raw"], entry["tris_prepared"],
                        entry["largest_component_share"], "" if entry["ok"] else " (refused)")
            if entry["ok"]:
                break
        last = attempts[-1]
        _job_update(name, item_id, job_id, phase="publish")
        applied = _publish(name, item_id, fsig, kind, job_id, last, attempts, candidate, staged_raw)
        outcome["applied"] = applied
        if applied and not last["ok"]:
            raise MeshGateRefused("mesh", None, attempts)
        if not applied:
            logger.info("garment mesh %s/%s: %s (job %s)", name, item_id, NOT_APPLIED, job_id)
        return prepared
    finally:
        _end_job(name, item_id, job_id)
        candidate.unlink(missing_ok=True)
        staged_raw.unlink(missing_ok=True)


def use_kept(name: str, item_id: str, fsig: str, n: int) -> Dict[str, Any]:
    """Ruling A58, "Use this" on kept mesh ``n`` of ``fsig``: it becomes the piece's mesh (prepared + raw + the
    step record's numbers, ``user_accepted`` when its gate refused it) and the mesh in use until now takes its slot
    (origin ``previous``) — a swap of files, no job. Under ``mesh_lock``: a running job's publish never interleaves.
    While the piece's mesh job of this fsig runs, the record gets ``chosen_during_job`` = ``{job, at, n}`` — the
    job's result is then kept beside it, not applied (``_publish``). The caller makes the fit due / runs it.
    ``{n, user_accepted, during_job}``. ``KeptUnusable`` for a slot without a kept mesh file."""
    import shutil
    import tempfile
    from app.core import garment_store as gs
    from app.core.timeutils import utc_now_iso
    prepared = gs.garment_path(name, item_id, fsig, "prepared")
    record_path = prepared.with_suffix(".json")
    raw = gs.garment_path(name, item_id, fsig, "raw")
    kind = _kind(item_id)
    with mesh_lock(name, item_id):
        record = gs.read_record(record_path)
        kept = kept_entries(record)
        entry = next((e for e in kept if e["n"] == n), None)
        files = attempt_files(name, item_id, fsig, n) if 1 <= n <= KEPT_MAX else {"prepared": None, "raw": None}
        if entry is None or files["prepared"] is None:
            raise KeptUnusable(f"No kept mesh {n} of this piece")
        kept.remove(entry)
        prepared.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".use-", dir=prepared.parent))
        try:
            os.replace(files["prepared"], staging / "prepared.glb")
            if files["raw"] is not None:
                os.replace(files["raw"], staging / "raw.glb")
            if prepared.is_file() and record.get("accepted") is True:
                # The mesh in use takes the freed slot: "Use this" there brings it back.
                previous = _entry_of_record(record)
                _move_into(prepared, gs.garment_path(name, item_id, fsig, "mesh_attempt", attempt=n))
                if raw.is_file():
                    _move_into(raw, gs.garment_path(name, item_id, fsig, "mesh_attempt_raw", attempt=n))
                kept.append({**previous, "n": n})
            else:
                prepared.unlink(missing_ok=True)
            if (staging / "raw.glb").is_file():
                os.replace(staging / "raw.glb", raw)
            os.replace(staging / "prepared.glb", prepared)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        last = {"tris_raw": entry.get("tris_raw"), "tris_prepared": entry.get("tris_prepared"),
                "ratio": entry.get("ratio"), "backend": entry.get("backend", ""), "routing": entry.get("routing") or {},
                "largest_component_share": entry.get("largest_component_share"),
                **{k: entry[k] for k in _ENTRY_KEYS if k in entry and k not in ("stored_raw",)}}
        user_accepted = not entry.get("ok")
        new = _record(kind, item_id, fsig, last,
                      [{**{k: v for k, v in entry.items() if k not in ("n", "origin")},
                        "attempt": entry.get("attempt") or 1, "ok": bool(entry.get("ok"))}], accepted=True)
        new["created_at"] = entry.get("created_at") or new["created_at"]
        new.update(picked_from=n, picked_at=utc_now_iso(), kept=kept)
        if user_accepted:
            new.update(user_accepted=True, user_reasons=list(entry.get("reasons") or []))
        job = running_job(name, item_id, fsig)
        if job is not None:
            new["chosen_during_job"] = {"job": job["id"], "at": utc_now_iso(), "n": n}
        gs.write_record(record_path, new)
    logger.info("garment mesh %s/%s: kept mesh %d (%s) in use%s", name, item_id, n, entry.get("origin"),
                f" — during mesh job {job['id']}, its result stays a kept mesh" if job else "")
    return {"n": n, "user_accepted": user_accepted, "during_job": job is not None}


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


def clear_attempts(name: str, item_id: str, fsig: str) -> None:
    """Drop every kept mesh file of ``fsig`` (Ruling A48a/A58) — with the step record they belong to
    (``garments._drop_mesh``: new images replace the mesh step's input)."""
    from app.core import garment_store as gs
    folder = gs.garment_path(name, item_id, fsig, "mesh_attempt", attempt=1).parent
    if not folder.is_dir():
        return
    for path in folder.glob(f"{item_id}_{fsig}.try*.glb"):
        if gs.parse_name(path) == (item_id, fsig):
            path.unlink(missing_ok=True)


def keep_attempt(name: str, item_id: str, fsig: str, attempt: int, candidate: Path, raw: Path) -> None:
    """Copy a mesh into kept slot ``attempt``: its decimated ``candidate`` and its ``raw`` output (Ruling A48a; the
    files are replaced atomically; the caller records the slot's ``kept`` entry). Best effort — a failed copy loses
    the tile, never the run."""
    import shutil
    from app.core import garment_store as gs
    for part, source in (("mesh_attempt", candidate), ("mesh_attempt_raw", raw)):
        try:
            if not Path(source).is_file():
                continue
            dest = gs.garment_path(name, item_id, fsig, part, attempt=attempt)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
            shutil.copyfile(source, tmp)
            os.replace(tmp, dest)
        except (OSError, ValueError) as e:
            logger.warning("garment mesh %s/%s: refused attempt %d not kept (%s): %s", name, item_id, attempt,
                           part, e)


def attempt_files(name: str, item_id: str, fsig: str, attempt: int) -> Dict[str, Optional[Path]]:
    """``{"prepared": path | None, "raw": path | None}`` of kept slot ``attempt`` (Ruling A48a/A58)."""
    from app.core import garment_store as gs
    out: Dict[str, Optional[Path]] = {}
    for which, part in (("prepared", "mesh_attempt"), ("raw", "mesh_attempt_raw")):
        path = gs.garment_path(name, item_id, fsig, part, attempt=attempt)
        out[which] = path if path.is_file() else None
    return out


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
    from app.core import mesh_pick
    from app.imagegen.service import get_image_service
    res = get_image_service().generate_mesh(
        source_image_path=str(cut["front"]), output_path=str(raw),
        character_name=name, mesh_name=f"{name}-{kind}",
        view_images={view: str(path) for view, path in cut.items() if view != "front"},
        occasion=mesh_occasion(kind), backend_glob=mesh_pick.current(),
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
            with mesh_lock(name, item_id):
                # Ruling A58: the mesh it replaces is kept (``previous``), the kept meshes stay with the record.
                current = gs.read_record(record_path)
                slots = kept_entries(current)
                if prepared.is_file() and current.get("accepted") is True:
                    _keep(name, item_id, fsig, slots, prepared, raw if raw.is_file() else None,
                          _entry_of_record(current), move=True)
                record["kept"] = slots
                os.replace(delivered, raw)
                os.replace(candidate, prepared)
                gs.write_record(record_path, record)
            return {"status": "accepted", "job_id": full, "record": record}
        refused = {"status": "refused", "job_id": full, "reasons": list(entry["reasons"]), "kept": kept,
                   "largest_component_share": entry["largest_component_share"],
                   "error": f"garment mesh refused ({', '.join(entry['reasons'])})"}
        if kept:
            return refused  # the accepted mesh stays exactly as it is
        with mesh_lock(name, item_id):
            slots = kept_entries(gs.read_record(record_path))
            os.replace(delivered, raw)
            _keep(name, item_id, fsig, slots, candidate, raw,
                  _entry_of_attempt({**entry, "created_at": record.get("created_at")}, KEPT_ATTEMPT), move=False)
            record["kept"] = slots
            prepared.unlink(missing_ok=True)
            gs.write_record(record_path, record)
        return {**refused, "record": record}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
