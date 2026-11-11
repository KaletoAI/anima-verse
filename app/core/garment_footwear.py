"""Footwear as its own mesh — an outfit piece flagged ``outfit_piece.own_mesh``
worn in slot ``feet`` (plan ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``;
spec ``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.1, § 5.6).

The kind module of garment kind ``footwear`` (``garment_set.FOOTWEAR``),
method ``shoe`` (``garment_store.SHOE``). The steps ``source → empty →
cutout → mesh → insole`` are per ITEM (``footwear_source``, world-scoped);
only ``fit`` is per wearer and body (``footwear_fit``). The fingerprint has
no base in it: a base change makes a fit stale, never the source.

The chain runs inside the garment run (``garments._run_locked`` dispatches a
footwear piece to ``run_chain``, the character's garment queue and cancel
are the same as for every garment): the item steps through
``footwear_source.run_source`` under the item lock, then ``fit`` on the
wearer's base model (CPU only, never a hub job).
``info`` is the Wardrobe panel; the footwear routes of
``app/routes/characters.py`` serve the files it names (``image_path``,
``mesh_path``, ``insole_path``).

The fit (plan Tasks 10 and 15, spec § 5.5–§ 5.7, § 7.1, § 8): ``fit`` runs ``footwear_fit.fit_pair`` of the
item's CURRENT source (``prepared.glb`` + ``insole.json`` under the current ssig) on one body — the base model
(``body`` "") or an outfit body (``body`` = its id, ``garment_store.body_root``) —, applies the fit's ``cut`` to
that body's primitives (``footwear_cut.apply_cut`` + ``glb_mesh.rewrite_body_primitives``: the foot under the
shoe is slimmed, conformed to the throat and removed, the cut faces bisected on the topline) and runs the cut
gates (``footwear_cut.cut_gates``: ``deep_outside``, ``visible_poke``, ``throat_ledge_p95_mm``) on the result
— they refuse like the fit's own gates. It publishes ``{item}_{fsig}.glb`` = that cut rigged body with two
grafted shoe nodes ``garment_footwear_<item>_left`` / ``_right`` (``graft`` refuses a repeated name, so one
node per side; extras ``{kind, item_id, fsig, side}``), its record (the fit's, ``cut`` included, every gate
of both tables under ``gates`` with ``gating`` True, the cut's stats and per-side diagnostics under
``diagnostics.<side>.cut``) and the ``low/`` tier decimated from it. The body sha in the record is the
UNCUT body's (what ``fit_state`` compares to the stored model). A fit is
keyed (item, fsig, body id) like a garment fit: two wearers make two fits of ONE source. Footwear never derives
a body fit from the base fit (``body_fit`` fits the source on the outfit body directly; there is no
``base_fit_sha256``). A refused fit publishes nothing: the failure is recorded per fsig (the base: the run's
``garments._note_outcome``; an outfit body: ``garment_store.record_body_failure``) and a fit of another body or
an older ``garment_fit.FIT_VERSION`` is never served in its place (R11 ruling; the fsig holds the fit version).
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_footwear")

KIND = "footwear"
#: Profile key of the per-fit width cap overrides: ``{item_id: float}``.
WIDTH_CAP_KEY = "footwear_width_cap"


def width_cap(profile: Dict[str, Any], item_id: str) -> float:
    """The width cap of the character's fit of ``item_id``: the profile
    override (``WIDTH_CAP_KEY``) clamped to ``footwear_fit.WIDTH_CAP_MIN`` ..
    ``footwear_fit.WIDTH_CAP``, the cap itself without a valid one."""
    from app.core import footwear_fit
    caps = profile.get(WIDTH_CAP_KEY) if isinstance(profile, dict) else None
    value = caps.get(item_id) if isinstance(caps, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return footwear_fit.WIDTH_CAP
    return round(min(footwear_fit.WIDTH_CAP, max(footwear_fit.WIDTH_CAP_MIN, float(value))), 4)


def set_width_cap(character_name: str, item_id: str, cap: Optional[float]) -> bool:
    """Store the per-fit width cap override of ``item_id`` (profile key ``WIDTH_CAP_KEY``, ``{item_id: cap}``);
    None removes it (back to ``footwear_fit.WIDTH_CAP``). ValueError for a value that is no number or lies
    outside ``footwear_fit.WIDTH_CAP_MIN`` .. ``footwear_fit.WIDTH_CAP``, and for an item that is no footwear
    piece of the character — nothing is stored then. One read-modify-write under the profile lock; returns
    ``save_character_profile``'s bool (True without a change). Only the fit fingerprint changes: the next run
    re-fits from the cached source on the CPU."""
    from app.core import footwear_fit
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    _check(character_name, item_id)
    value: Optional[float] = None
    if cap is not None:
        if isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap != cap:
            raise ValueError("The width cap must be a number or null")
        value = round(float(cap), 4)
        if not footwear_fit.WIDTH_CAP_MIN <= value <= footwear_fit.WIDTH_CAP:
            raise ValueError(f"The width cap must lie between {footwear_fit.WIDTH_CAP_MIN:.2f} and "
                             f"{footwear_fit.WIDTH_CAP:.2f}")
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        caps = dict(profile.get(WIDTH_CAP_KEY)) if isinstance(profile.get(WIDTH_CAP_KEY), dict) else {}
        if value is None:
            if item_id not in caps:
                return True
            caps.pop(item_id)
        else:
            if caps.get(item_id) == value:
                return True
            caps[item_id] = value
        if caps:
            profile[WIDTH_CAP_KEY] = caps
        else:
            profile.pop(WIDTH_CAP_KEY, None)
        return bool(save_character_profile(character_name, profile))


def fsig_inputs(character_name: str, item: Dict[str, Any], *, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The footwear fingerprint inputs: the item's current source ``ssig``,
    the insole analysis version, the width cap and the fit version — no base
    signature, no base images, no base model."""
    from app.core import footwear_insole, footwear_source, garment_fit
    item_id = str(item.get("id") or "")
    return {"ssig": footwear_source.current_ssig(item_id), "insole_version": footwear_insole.INSOLE_VERSION,
            "width_cap": width_cap(profile, item_id), "fit_version": garment_fit.FIT_VERSION[KIND]}


# --- the run ------------------------------------------------------------------------------------------------------------

#: ``fit`` of a run result whose wearer has no base model yet: the item steps ran, nothing to fit onto.
NO_BASE = "no_base"
#: ``error_type`` of a failed item step that is load or the media switch, not a defect of the item: the run
#: fails without a persisted failure record (``retry_later``), so automatic triggers try again.
RETRY_LATER_ERRORS: Tuple[str, ...] = ("BackendBusyError", "MediaGenerationDisabled")


def _fsig(character_name: str, item_id: str, profile: Dict[str, Any]) -> str:
    from app.core import garment_store as gs
    return gs.garment_fsig(character_name, item_id, profile=profile)


def run_chain(character_name: str, item: Dict[str, Any], wanted: Optional[List[str]],
              force: bool) -> Dict[str, Any]:
    """The footwear chain of one wearer (called by ``garments._run_locked`` under the character's run lock):
    the item steps ``source → empty → cutout → mesh → insole`` through ``footwear_source.run_source`` (under
    the ITEM lock, so two wearers never run a step twice — the later one finds it done), then ``fit``.

    ``wanted`` None: every item step that is not done (an insole of an older analysis version counts as not
    done). A step name (or several): from the earliest of them on, cached steps reused; with ``force`` that
    item step starts a new source first (``footwear_source.regenerate``: next seed, new ssig, the accepted
    outputs before it copied), so it and every later item step run again.

    Then the fit on the wearer's base model (CPU, ``fit``): it runs when the fit of the current fsig is not
    ``accepted`` on the current base model bytes (``fit_state``), when an item step ran, or when ``fit`` is
    wanted with ``force`` (Re-fit). A wearer without a base model yet ends after the item steps with
    ``fit: NO_BASE``. ``fit`` in the result = the fit state after the run.

    -> ``{ok: True, fsig, ran, fit}`` or ``{ok: False, fsig, step, error, gates, error_type, ran}`` plus
    ``retry_later: True`` for load / the media switch (``RETRY_LATER_ERRORS``: no failure record). A refused
    fit is ``{ok: False, step "fit", error, gates}`` (``garments._note_outcome`` records it per fsig)."""
    from app.core import base_body, footwear_insole, footwear_source, garment_store as gs
    from app.core.garments import _Refused
    from app.models.character import get_character_profile
    item_id = str(item.get("id") or "")
    profile = get_character_profile(character_name) or {}
    order = gs.FOOTWEAR_STEPS
    item_steps = list(footwear_source.ITEM_STEPS)
    first = order[0] if not wanted else min(wanted, key=order.index)
    fsig = ""
    running: List[str] = []
    step = first

    def on_step(name: str) -> None:
        nonlocal step
        if running:
            gs.end(character_name, item_id, running.pop())
        running.append(name)
        step = name
        gs.start(character_name, item_id, name)

    ran: List[str] = []
    try:
        fsig = _fsig(character_name, item_id, profile)
        if first in item_steps:
            if force and wanted:
                footwear_source.regenerate(item_id, first)
                fsig = _fsig(character_name, item_id, profile)
            steps = item_steps[item_steps.index(first):]
            res = footwear_source.run_source(item_id, steps=steps, on_step=on_step)
            ran = list(res.get("ran") or [])
            if res.get("ok") and "insole" in steps and "insole" not in ran:
                version = footwear_source.step_record(item_id, res["ssig"], "insole").get("version")
                if version != footwear_insole.INSOLE_VERSION:
                    # An insole of an older analysis version: measured again (CPU, no hub job).
                    again = footwear_source.run_source(item_id, steps=["insole"], force=True, on_step=on_step)
                    ran += list(again.get("ran") or [])
                    res = {**again, "ran": ran}
            if not res.get("ok"):
                step = str(res.get("step") or step)
                if running:
                    running.pop()
                return _failure(character_name, item_id, fsig, step, str(res.get("error") or ""),
                                res.get("gates"), ran, str(res.get("error_type") or ""))
        if running:
            gs.end(character_name, item_id, running.pop())
        base = base_body.current_base(character_name, profile=profile)
        if not base or not base[1]:
            logger.info("Footwear run %s/%s: no base model yet — nothing to fit onto", character_name, item_id)
            return {"ok": True, "fsig": fsig, "ran": ran, "fit": NO_BASE}
        refit = bool(force and wanted and "fit" in wanted)
        if refit or ran or fit_state(character_name, item_id, fsig, base[1]) != "accepted":
            on_step("fit")
            fit(character_name, item_id, fsig, profile=profile)
            ran.append("fit")
            gs.end(character_name, item_id, running.pop())
        return {"ok": True, "fsig": fsig, "ran": ran, "fit": fit_state(character_name, item_id, fsig, base[1])}
    except _Refused as e:
        if running:
            running.pop()
        return _failure(character_name, item_id, fsig, e.step, e.error, e.gates, ran, "GateRefused")
    except Exception as e:  # noqa: BLE001 — reported as the step's failure, like garments._run_locked
        logger.warning("Footwear run %s/%s failed at %s: %s", character_name, item_id, step, e)
        if running:
            running.pop()
        return _failure(character_name, item_id, fsig, step, str(e) or type(e).__name__, None, ran,
                        type(e).__name__)


def _failure(character_name: str, item_id: str, fsig: str, step: str, error: str, gates: Any, ran: List[str],
             error_type: str) -> Dict[str, Any]:
    from app.core import garment_store as gs
    logger.info("Footwear run %s/%s refused at %s: %s", character_name, item_id, step, error)
    gs.end(character_name, item_id, step, error=error, gates=gates)
    out = {"ok": False, "fsig": fsig, "step": step, "error": error, "gates": gates, "error_type": error_type,
           "ran": ran}
    if error_type in RETRY_LATER_ERRORS:
        out["retry_later"] = True
    return out


def step_done(item_id: str, step: str) -> bool:
    """``garments._done`` of a footwear item step: done under the item's CURRENT ssig (an insole also needs
    the current analysis version)."""
    from app.core import footwear_insole, footwear_source
    ssig = footwear_source.current_ssig(item_id)
    if not footwear_source.step_done(item_id, ssig, step):
        return False
    if step == "insole":
        return footwear_source.step_record(item_id, ssig, step).get("version") == footwear_insole.INSOLE_VERSION
    return True


#: Why a fit cannot run yet: the item's source is not through the insole (``step_done``).
SOURCE_NOT_READY = "The shoe source is not ready — run the shoe chain up to the insole first"
#: The fingerprint changed between the caller computing it and the fit (the source or the width cap).
FSIG_CHANGED = "The shoe source or the width cap changed during the run — run the chain again"
#: Fit step freshness reasons (fixed English phrases; the React badge translates them).
FIT_BODY_CHANGED = "Body changed — refit pending"
FIT_SOURCE_CHANGED = "Shoe source changed — refit pending"
FIT_REFITTED = "Refitted from the previous base"
FIT_REFUSED = "Fit refused on this body: {gate}"


def node_name(item_id: str, side: str) -> str:
    """The grafted shoe node of one side: ``garment_footwear_<item>_<side>``."""
    return f"garment_{KIND}_{item_id}_{side}"


def source_ready(item_id: str) -> bool:
    """Whether the item's CURRENT source has an accepted mesh and an accepted insole of the current analysis
    version (what ``fit`` reads)."""
    return step_done(item_id, "mesh") and step_done(item_id, "insole")


def _source_parents(item_id: str, ssig: str) -> Dict[str, Any]:
    """``parents.source`` of a fit record: ``{ssig, empty_sha256, mesh_sha256, insole_version}``."""
    from app.core import footwear_source
    from app.core.base_body import file_sha256
    folder = footwear_source.source_dir(item_id, ssig)
    return {"ssig": ssig, "empty_sha256": file_sha256(folder / "empty.png"),
            "mesh_sha256": file_sha256(folder / "prepared.glb"),
            "insole_version": footwear_source.step_record(item_id, ssig, "insole").get("version")}


def fit(character_name: str, item_id: str, fsig: str, *, body: str = "", profile: Dict[str, Any],
        schedule: bool = False) -> Path:
    """Fit the item's current shoe source onto ``body`` ("" = the base model, else an outfit body id) and
    publish it under ``garment_store.garment_path(…, "fit", body=body)`` (module docstring): the rigged body
    with the fit's cut applied + the two shoe nodes, the record (spec § 5.7 with ``cut``, plus ``accepted``,
    ``fit_version``, ``body_id``, ``body_sha256``, ``base_model_sha256`` on the base only, ``base_signature``,
    ``parents.source`` and ``foot_pose`` with its ``source``), and the ``low/`` tier decimated from the fit GLB.
    ``schedule`` asks for the outfit assembly afterwards (P2: never — the served model stays unchanged).

    ``garments._Refused("fit", …)`` when a gate refuses — the fit's (``BOOT_REFUSED`` first for a boot) or the
    cut's — or the fsig is no longer ``fsig``; ``base_body.MissingInput`` when the source is not ready or the
    outfit body is missing; ``base_body.OutfitError`` without a base model. CPU only: never a hub job."""
    import hashlib
    from app.blender import refine
    from app.core import base_body, footwear_cut, footwear_fit, footwear_rest, footwear_source, garment_fit, glb_mesh
    from app.core import garment_store as gs
    from app.core.garments import _Refused, _snapshot_body, _write_atomic
    from app.core.timeutils import utc_now_iso
    _item_, kind = _item_kind(character_name, item_id)
    if _fsig(character_name, item_id, profile) != fsig:
        raise _Refused("fit", FSIG_CHANGED, None)
    if not source_ready(item_id):
        raise base_body.MissingInput(SOURCE_NOT_READY)
    ssig = footwear_source.current_ssig(item_id)
    folder = footwear_source.source_dir(item_id, ssig)
    prepared = (folder / "prepared.glb").read_bytes()
    insole = gs.read_record(folder / "insole.json")
    if body:
        if not gs.is_body_id(body):
            raise ValueError(f"not an outfit body id: {str(body)[:40]!r}")
        snapshot = _snapshot_body(character_name, body)
        rigged, body_sha = snapshot["rigged"], snapshot["sha"]
        bsig = str((snapshot["meta"].get("outfit_body") or {}).get("base_signature") or "")
        body_id = body
    else:
        base = base_body.current_base(character_name, profile=profile)
        if not base:
            raise ValueError(f"{character_name} is not on the base-body pipeline")
        bsig = base[0]
        rigged = base_body._snapshot_base_model(character_name, bsig)["rigged"]
        body_sha = hashlib.sha256(rigged).hexdigest()
        body_id = bsig

    positions, faces, uvs, image, mime, material = glb_mesh.static_arrays(prepared)
    n = len(positions)
    shoe = glb_mesh.GarmentMesh(positions=positions, normals=None, uvs=uvs, indices=faces,
                                joints=np.zeros((n, 4), np.int64), weights=np.zeros((n, 4)), joint_names=[],
                                image=image, mime=mime, material=material)
    cap = width_cap(profile, item_id)
    result = footwear_fit.fit_pair(insole, shoe, glb_mesh.body_arrays(rigged), glb_mesh.joint_bind_matrices(rigged),
                                   width_cap=cap)
    if not result.ok:
        gates = {"ok": False, "reasons": list(result.reasons), **(result.record.get("gates") or {})}
        raise _Refused("fit", "fit refused — " + "; ".join(result.reasons), gates)

    # The cut on every body primitive, then the cut gates on the body as a whole (spec § 7.1, § 8).
    cut = result.record["cut"]
    joints = glb_mesh.joint_bind_matrices(rigged)
    prims = glb_mesh.body_primitive_arrays(rigged)
    replaced: Dict[int, glb_mesh.Prim] = {}
    cut_stats: Dict[str, Any] = {"removed_faces": 0, "bisected_faces": 0, "new_vertices": 0,
                                 "slim_share": {}, "slim_needed": {}, "throat_moved": {}, "toe_conform": {},
                                 "toe_pull": {}}
    for i, prim in enumerate(prims):
        replaced[i], stats = footwear_cut.apply_cut(prim, cut, joints)
        for key in ("removed_faces", "bisected_faces", "new_vertices"):
            cut_stats[key] += int(stats[key])
        for side in footwear_fit.SIDES:
            for key in ("slim_share", "slim_needed", "toe_conform", "toe_pull"):
                cut_stats[key][side] = max(float(cut_stats[key].get(side, 0.0)), float(stats[key].get(side, 0.0)))
            cut_stats["throat_moved"][side] = int(cut_stats["throat_moved"].get(side, 0)) + int(
                stats["throat_moved"].get(side, 0))
    cut_gates = footwear_cut.cut_gates(_merged(list(replaced.values())), result.shoes, cut, joints=joints,
                                       body_before=_merged(prims))
    result.record["gates"].update(footwear_fit._r({name: {**gate, "gating": True}
                                                   for name, gate in cut_gates["gates"].items()}))
    for side in footwear_fit.SIDES:
        result.record["diagnostics"][side]["cut"] = footwear_fit._r({
            **(cut_gates["sides"].get(side) or {}),
            **{key: cut_stats[key].get(side) for key in ("slim_share", "slim_needed", "throat_moved")}})
        # the conform's own numbers of the merged body are already in the side gates (toe_conform_m / toe_pull_m)
    result.record["cut_stats"] = {key: cut_stats[key] for key in ("removed_faces", "bisected_faces", "new_vertices")}
    if not cut_gates["ok"]:
        gates = {"ok": False, "reasons": list(cut_gates["reasons"]), **result.record["gates"]}
        raise _Refused("fit", "fit refused — " + "; ".join(cut_gates["reasons"]), gates)

    blob = glb_mesh.rewrite_body_primitives(rigged, replaced)
    for side in footwear_fit.SIDES:
        blob = glb_mesh.graft(blob, result.shoes[side], name=node_name(item_id, side),
                              extras={"kind": kind, "item_id": item_id, "fsig": fsig, "side": side})
    now = utc_now_iso()
    parents: Dict[str, Any] = {"body_id": body_id, "body_sha256": body_sha, "base_signature": bsig,
                               "source": _source_parents(item_id, ssig)}
    record: Dict[str, Any] = {
        "method": "shoe", "kind": kind, "item_id": item_id, "fsig": fsig, "ssig": ssig, **result.record,
        "parents": parents, "accepted": True, "fit_version": garment_fit.FIT_VERSION[kind],
        "body_id": body_id, "body_sha256": body_sha, "base_signature": bsig,
        # ``rest``: the BARE body's figure box and rest soles (``footwear_rest``) for the shod preview
        # (whose body is cut); the assembly re-measures its own bare file.
        "foot_pose": {**result.foot_pose, "rest": footwear_rest.rest_measurement(rigged),
                      "source": {"item_id": item_id, "fsig": fsig,
                                 "glb_sha256": hashlib.sha256(blob).hexdigest()}},
        "fitted_at": now, "created_at": now}
    if not body:
        parents["base_model_sha256"] = body_sha
        record["base_model_sha256"] = body_sha
    path = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body)
    # A refit after a body change (the fsig has no base in it: the same path): the record remembers the
    # body it came from (``refitted.from_body_sha256``, Task 25) — the Wardrobe says so, the GC keeps nothing by it.
    previous = gs.read_record(path.with_suffix(".json")) if path.is_file() else {}
    if previous.get("accepted") is True and previous.get("body_sha256") \
            and previous.get("body_sha256") != body_sha:
        record["refitted"] = {"from_body_sha256": previous["body_sha256"], "at": now}
    # A distance tier of the previous fit must never pair with the new one.
    low.unlink(missing_ok=True)
    _write_atomic(path, blob)
    gs.write_record(path.with_suffix(".json"), record)
    logger.info("Footwear fit %s/%s (%s): accepted on %s, width x%.3f, lift %.1f mm, cut %d faces removed / %d "
                "bisected", character_name, item_id, fsig, body or bsig, result.record["scale"]["width_factor"],
                1000.0 * result.record["root_lift_m"], cut_stats["removed_faces"], cut_stats["bisected_faces"])
    tris = len(glb_mesh.static_arrays(blob)[1])
    target = max(1, int(round(refine.lod_ratio("character") * tris)))
    try:
        dec = refine.decimate_to(path, target, low)
    except Exception as e:  # noqa: BLE001 — the distance tier falls back to the full fit
        dec = {"ok": False, "error": str(e) or type(e).__name__}
    if dec.get("ok"):
        record["low"] = {"ok": True, "tris": dec.get("tris"), "ratio": dec.get("ratio")}
    else:
        logger.warning("Footwear fit %s/%s: distance tier failed: %s", character_name, item_id, dec.get("error"))
        record["low"] = {"ok": False, "error": dec.get("error") or "decimation failed"}
    gs.write_record(path.with_suffix(".json"), record)
    if body:
        gs.clear_failure_on_body(character_name, item_id, fsig, body)
    if schedule:
        from app.core import garment_assembly
        garment_assembly.schedule(character_name)
    return path


def _merged(prims: List["glb_mesh.Prim"]) -> "glb_mesh.Prim":
    """The geometry and skinning of ``prims`` as ONE ``Prim`` (faces offset) for ``footwear_cut.cut_gates``, which
    reads a body as one primitive; attributes and morph targets are not carried (the gates read none)."""
    from app.core import glb_mesh
    if len(prims) == 1:
        return prims[0]
    P, F, J, W, base = [], [], [], [], 0
    for prim in prims:
        P.append(np.asarray(prim.positions, np.float64))
        F.append(np.asarray(prim.faces, np.int64) + base)
        J.append(np.asarray(prim.joints, np.int64))
        W.append(np.asarray(prim.weights, np.float64))
        base += len(prim.positions)
    return glb_mesh.Prim(positions=np.concatenate(P), faces=np.concatenate(F), joints=np.concatenate(J),
                         weights=np.concatenate(W), joint_names=list(prims[0].joint_names))


def _item_kind(character_name: str, item_id: str) -> Tuple[Dict[str, Any], str]:
    """``garments._item`` of a footwear piece; ValueError for anything else."""
    from app.core import garments
    item, kind = garments._item(character_name, item_id)
    if kind != KIND:
        raise ValueError(f"{item_id} is no footwear piece")
    return item, kind


def fit_state(character_name: str, item_id: str, fsig: str, body_sha: str, *, body: str = "") -> str:
    """The state of the wearer's fit of ``fsig`` on ``body`` ("" = the base model, ``body_sha`` its model
    sha256; an outfit body id with its rigged sha256): ``missing`` (no accepted fit), ``stale`` (made on other
    body bytes, or by an older ``garment_fit.FIT_VERSION``), ``outdated`` (the source mesh it was fitted from
    was replaced or removed, or its insole is gone, no longer accepted or of another analysis version) or
    ``accepted``."""
    from app.core import footwear_source, garment_store as gs
    from app.core.base_body import file_sha256
    from app.core.garment_fit import FIT_VERSION
    try:
        path = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
    except ValueError:
        return "missing"
    record = gs.read_record(path.with_suffix(".json"))
    if not path.is_file() or record.get("accepted") is not True:
        return "missing"
    if body:
        if not body_sha or record.get("body_id") != body or record.get("body_sha256") != body_sha:
            return "stale"
    elif not body_sha or record.get("base_model_sha256") != body_sha:
        return "stale"
    if record.get("fit_version") != FIT_VERSION.get(KIND):
        return "stale"
    source = (record.get("parents") or {}).get("source") or {}
    ssig = str(source.get("ssig") or "")
    try:
        folder = footwear_source.source_dir(item_id, ssig)
    except ValueError:
        return "outdated"
    prepared = folder / "prepared.glb"
    if not prepared.is_file() or source.get("mesh_sha256") != file_sha256(prepared):
        return "outdated"
    insole = footwear_source.step_record(item_id, ssig, "insole")
    if (not (folder / "insole.json").is_file() or insole.get("accepted") is not True
            or insole.get("version") != source.get("insole_version")):
        return "outdated"
    return "accepted"


def body_fit(character_name: str, item_id: str, *, body_id: str, body_sha: str, profile: Dict[str, Any],
             build: bool = False) -> Dict[str, Any]:
    """``garments.body_fit`` of a footwear piece: what an outfit model on the outfit body ``body_id`` (made of the
    body bytes ``body_sha``) carries of it — ``{fit, low, record, fsig, pending, error}``, same shape.

    Fits the item's source on the outfit body directly (``fit`` with ``body``), never from the base fit (there
    is no ``base_fit_sha256``). ``build`` (the assembly build, never serving) fits a missing / stale / outdated
    one first, serialised per body; a refusal or failure is recorded per body (``record_body_failure``, the
    fit version as the third key) and nothing of another body or an older fit version is served then (R11
    ruling). Without a ready source nothing is fitted and nothing recorded (``SOURCE_NOT_READY``); nothing is
    fitted on a body whose stored bytes are no longer ``body_sha``."""
    from app.core import garment_fit, garment_store as gs, garments
    from app.core.keyed_lock import keyed_lock
    empty = {"fit": None, "low": None, "record": {}, "fsig": "", "pending": False}
    if not gs.is_body_id(body_id) or not body_sha:
        return {**empty, "error": "no outfit body to fit on"}
    try:
        fsig = _fsig(character_name, item_id, profile)
    except ValueError as e:
        return {**empty, "error": str(e)}
    fit_path = gs.garment_path(character_name, item_id, fsig, "fit", body=body_id)
    version = garment_fit.FIT_VERSION[KIND]

    def current() -> Tuple[str, Optional[Dict[str, Any]]]:
        state = fit_state(character_name, item_id, fsig, body_sha, body=body_id)
        failure = (gs.body_failure(character_name, item_id, fsig, body_id, body_sha=body_sha, base_fit_sha="",
                                   fit_version=version) if state != "accepted" else None)
        return state, failure

    state, failure = current()
    ready = source_ready(item_id)
    on_body = state != "accepted" and ready and garments.body_sha256(character_name, body_id) == body_sha
    if on_body and failure is None and build:
        with keyed_lock("garment_body_fit", f"{character_name}:{body_id}"):
            state, failure = current()
            if state != "accepted" and failure is None:
                try:
                    fit(character_name, item_id, fsig, body=body_id, profile=profile, schedule=False)
                except Exception as e:  # noqa: BLE001 — recorded per body, the assembly goes on
                    error = e.error if isinstance(e, garments._Refused) else (str(e) or type(e).__name__)
                    logger.warning("Footwear fit %s/%s (%s) on outfit body %s failed: %s", character_name, item_id,
                                   fsig, body_id, error)
                    gs.record_body_failure(character_name, item_id, fsig, body_id, error=error, body_sha=body_sha,
                                           base_fit_sha="", fit_version=version)
                state, failure = current()
    record = gs.read_record(fit_path.with_suffix(".json"))
    usable = (fit_path.is_file() and record.get("accepted") is True and record.get("body_id") == body_id
              and record.get("body_sha256") == body_sha and record.get("fit_version") == version)
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body_id)
    pending = on_body and failure is None and not build
    if state == "accepted":
        error = ""
    elif failure is not None:
        error = str(failure.get("error") or "")
    elif not ready:
        error = SOURCE_NOT_READY
    else:
        error = "not fitted on this outfit body yet" if pending or on_body else "the outfit body was rebuilt"
    return {"fit": fit_path if usable else None, "low": low if usable and low.is_file() else None,
            "record": record if usable else {}, "fsig": fsig, "pending": pending, "error": error}


# --- info ---------------------------------------------------------------------------------------------------------------

#: Per-step freshness reasons (fixed English phrases; the React badge translates them).
ITEM_IMAGE_CHANGED = "Item image changed"
OLDER_ANALYSIS = "Older analysis version"
#: The shown source is not the current one although the item image is the same: an older
#: ``footwear_source.FOOTWEAR_SOURCE_VERSION``.
OLDER_SOURCE = "Older source version"
#: The images the footwear image route serves: the item image itself and the source step outputs.
IMAGES: Tuple[str, ...] = ("source", "upscaled", "empty", "cutout")
_IMAGE_FILES = {"upscaled": "upscaled.png", "empty": "empty.png", "cutout": "cutout.png"}
_SSIG_RE = re.compile(r"^[0-9a-f]{12}$")


def shown_ssig(item_id: str) -> str:
    """The source the Wardrobe shows: the CURRENT ssig when anything was recorded under it, else the newest
    ssig folder of the item with a recorded step (a new item image names a new, still empty source — the old
    one stays visible, marked ``ITEM_IMAGE_CHANGED``), else the current ssig."""
    from app.core import footwear_source, garment_store as gs
    current = footwear_source.current_ssig(item_id)
    folder = footwear_source.item_dir(item_id)

    def recorded(d: Path) -> bool:
        steps = gs.read_record(d / "record.json").get("steps")
        return isinstance(steps, dict) and bool(steps)
    if recorded(folder / current):
        return current
    best: Optional[Tuple[int, str]] = None
    if folder.is_dir():
        for d in folder.iterdir():
            if not (d.is_dir() and _SSIG_RE.match(d.name) and recorded(d)):
                continue
            try:
                stamp = (d / "record.json").stat().st_mtime_ns
            except OSError:
                continue
            if best is None or stamp > best[0]:
                best = (stamp, d.name)
    return best[1] if best else current


def _check(character_name: str, item_id: str) -> None:
    """ValueError unless ``item_id`` is a footwear piece of the character (held or worn)."""
    from app.core import garments
    _item, kind = garments._item(character_name, item_id)
    if kind != KIND:
        raise ValueError(f"{item_id} is no footwear piece")


def image_path(character_name: str, item_id: str, which: str, attempt: int = 0) -> Optional[Path]:
    """The file behind one footwear image of the SHOWN source (``shown_ssig``): ``source`` = the item image
    itself, ``upscaled`` / ``empty`` / ``cutout`` = the step outputs; ``attempt`` n (``empty`` only) = that
    edit attempt. None when absent. ValueError for an unknown ``which`` / attempt or an item that is no
    footwear piece of the character."""
    from app.core import footwear_source
    if which not in IMAGES:
        raise ValueError(f"image must be one of {', '.join(IMAGES)}")
    if not 0 <= int(attempt) <= footwear_source.EMPTY_ATTEMPTS or (attempt and which != "empty"):
        raise ValueError(f"attempt must be 0 (or 1..{footwear_source.EMPTY_ATTEMPTS} for the empty shoe)")
    _check(character_name, item_id)
    if which == "source":
        from app.models.inventory import get_item_image_path
        path = get_item_image_path(item_id)
        return Path(path) if path and Path(path).is_file() else None
    folder = footwear_source.source_dir(item_id, shown_ssig(item_id))
    path = folder / (f"empty.try{int(attempt)}.png" if attempt else _IMAGE_FILES[which])
    return path if path.is_file() else None


def mesh_path(character_name: str, item_id: str) -> Optional[Path]:
    """The prepared shoe GLB of the SHOWN source; None when absent. ValueError like ``image_path``."""
    from app.core import footwear_source
    _check(character_name, item_id)
    path = footwear_source.source_dir(item_id, shown_ssig(item_id)) / "prepared.glb"
    return path if path.is_file() else None


def insole_path(character_name: str, item_id: str) -> Optional[Path]:
    """``insole.json`` of the SHOWN source; None when absent. ValueError like ``image_path``."""
    from app.core import footwear_source
    _check(character_name, item_id)
    path = footwear_source.source_dir(item_id, shown_ssig(item_id)) / "insole.json"
    return path if path.is_file() else None


def _url(character_name: str, item_id: str, tail: str, version: Any, extra: str = "") -> str:
    return (f"/characters/{quote(character_name, safe='')}/garments/{quote(item_id, safe='')}/footwear/{tail}"
            f"?v={version}{extra}")


def _stamp(path: Optional[Path]) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns if path is not None else None
    except OSError:
        return None


def _numbers(values: Any) -> Dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {k: v for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _gate_of(error: Any) -> str:
    """The gate clause of a fit refusal — ``"fit refused — slim_needed 0.22 > 0.18 (…)"`` → ``"slim_needed 0.22
    > 0.18 (…)"`` (the error's text after the first dash); the whole text when it has none."""
    text = str(error or "")
    for sep in (" — ", " - "):
        if sep in text:
            return text.split(sep, 1)[1].strip()
    return text


def _fit_info(character_name: str, item_id: str, fsig: Optional[str], body_sha: str, *,
              body: str = "") -> Dict[str, Any]:
    """One fit of ``info`` — ``steps.fit`` (the base model, ``body`` "") or a row of ``fits`` (an outfit body id):
    ``{status, gates, metrics, url None, freshness, created_at, error}``. ``status`` is ``fit_state``, or
    ``refused`` when the persisted failure of the fsig holds on this body (the base: ``chain_failure`` of a
    ``fit`` step on ``body_sha``; an outfit body: ``body_failure`` on ``body_sha`` by the current fit version).
    ``gates`` is the record's gate table ``{name: {value, limit, ok, gating}}``; ``metrics`` the record's width
    factor / cap, root lift, scale (``k_m_per_unit``, shoe ``length_m``) and per side the width needed, the
    slimming needed, the extension and the toe room."""
    from app.core import garment_store as gs
    from app.core.garment_fit import FIT_VERSION
    from app.core.model_overview import CURRENT, MISSING, STALE, freshness
    status = fit_state(character_name, item_id, fsig, body_sha, body=body) if fsig and body_sha else "missing"
    try:
        record = (gs.read_record(gs.garment_path(character_name, item_id, fsig, "fit", body=body).with_suffix(".json"))
                  if fsig else {})
    except ValueError:
        record = {}
    error = None
    if status != "accepted" and fsig:
        if body:
            failure = gs.body_failure(character_name, item_id, fsig, body, body_sha=body_sha, base_fit_sha="",
                                      fit_version=FIT_VERSION.get(KIND))
        else:
            failure = gs.chain_failure(character_name, item_id, fsig, base_model_sha=body_sha)
            if failure is not None and failure.get("step") != "fit":
                failure = None
        if failure is not None:
            status, error = "refused", failure.get("error")
    if status == "missing" or not record.get("accepted"):
        record = {}
    scale = record.get("scale") or {}
    sides = record.get("sides") or {}
    needed = scale.get("width_needed") or {}
    slim = scale.get("slim_needed") or {}
    metrics = _numbers({
        "width_factor": scale.get("width_factor"), "width_cap": scale.get("width_cap"),
        "root_lift_m": record.get("root_lift_m"), "k_m_per_unit": scale.get("k_m_per_unit"),
        "length_m": scale.get("length_m"),
        **{f"{key}_{side}": value for side in ("left", "right") for key, value in (
            ("width_needed", needed.get(side) if isinstance(needed, dict) else None),
            ("slim_needed", slim.get(side) if isinstance(slim, dict) else None),
            ("extension_deg", ((sides.get(side) or {}).get("extension") or {}).get("deg")),
            ("toe_room_mm", (sides.get(side) or {}).get("toe_room_mm")))}})
    if status == "accepted" and isinstance(record.get("refitted"), dict):
        fresh = freshness(CURRENT, FIT_REFITTED)
    elif status == "refused":
        fresh = freshness(MISSING, FIT_REFUSED.format(gate=_gate_of(error)))
    else:
        fresh = {"accepted": freshness(CURRENT), "stale": freshness(STALE, FIT_BODY_CHANGED),
                 "outdated": freshness(STALE, FIT_SOURCE_CHANGED)}.get(status, freshness(MISSING))
    return {"status": status, "gates": record.get("gates") or {}, "metrics": metrics, "url": None,
            "freshness": fresh, "created_at": record.get("fitted_at"), "error": error}


def stored_outfit_bodies(character_name: str) -> List[str]:
    """The outfit body ids with a stored rigged body (``model3d/<body id>.glb``), sorted. Creates nothing."""
    from app.core import base_body
    from app.models.character import get_character_dir
    folder = get_character_dir(character_name) / "model3d"
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.glb")
                  if p.is_file() and base_body.is_outfit_body_signature(p.stem))


def _fits(character_name: str, item_id: str, fsig: Optional[str], base: Tuple[str, str], base_fit: Dict[str, Any],
          *, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """``fits`` of ``info``: the fit of ``fsig`` per body — the base model first (``base_fit`` = ``steps.fit``),
    then in outfit body mode ``mesh`` one row per stored outfit body (``stored_outfit_bodies``). Each row is
    ``_fit_info`` plus ``body_id`` (the base signature / the outfit body id) and ``base`` (True on the base)."""
    from app.core import base_body, garments
    rows: List[Dict[str, Any]] = [{"body_id": base[0] or None, "base": True, **base_fit}]
    if base_body.outfit_body_mode(character_name, profile=profile) != base_body.MESH_MODE:
        return rows
    for body_id in stored_outfit_bodies(character_name):
        body_sha = garments.body_sha256(character_name, body_id)
        rows.append({"body_id": body_id, "base": False,
                     **_fit_info(character_name, item_id, fsig, body_sha, body=body_id)})
    return rows


def _preview(character_name: str, item_id: str,
             fsig: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """``(preview_url, foot_pose)`` of ``info``: the shod base model of the CURRENT fsig (the file
    ``garments.preview_path`` resolves first, served by GET …/garments/{item}/model) when its record is
    accepted, versioned by content, and that record's ``foot_pose`` (with its ``source``: item, fsig, the fit
    GLB's sha). ``(None, None)`` without one — an older fsig's fit is never previewed with this pose."""
    from app.core import garment_store as gs
    from app.core.http_files import content_version
    if not fsig:
        return None, None
    try:
        path = gs.garment_path(character_name, item_id, fsig, "fit")
    except ValueError:
        return None, None
    record = gs.read_record(path.with_suffix(".json"))
    if not path.is_file() or record.get("accepted") is not True:
        return None, None
    try:
        version = content_version(path)
    except OSError:
        return None, None
    pose = record.get("foot_pose")
    source = pose.get("source") if isinstance(pose, dict) else None
    if not (isinstance(source, dict) and source.get("fsig") == fsig and source.get("item_id") == item_id):
        pose = None
    url = (f"/characters/{quote(character_name, safe='')}/garments/{quote(item_id, safe='')}/model"
           f"?v={version}")
    return url, pose


def info(character_name: str, item_id: str, *, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The Wardrobe panel of a footwear piece (``garments.garment_info`` of kind ``footwear``):

    ``{item_id, kind "footwear", method "shoe", method_source "world", description, fsig, ssig (the shown
    source, ``shown_ssig``), current_ssig, running_step, started_at, queue_position, queue_running, failed,
    steps, item_image_url, mesh_url, insole, stale_reasons, fits, preview_url, preview_freshness, foot_pose,
    served_fsig None, refit None, body None, body_id None}``.

    ``steps`` in chain order: ``source``, ``empty``, ``cutout``, ``mesh``, ``insole`` each ``{status
    accepted|refused|failed|waiting|missing, gates, metrics, url, freshness, backend, created_at, error}``
    (``refused`` = its gates refused it, ``failed`` = the backend failed, ``waiting`` = load or the media
    switch, retry later; ``empty`` adds ``attempts`` with their image URLs, ``mesh`` its ``attempts``, ``source`` its
    ``upscale``); ``freshness`` = ``{state, reason}`` computed here: ``stale`` with ``ITEM_IMAGE_CHANGED``
    when the shown source was made from another item image than the current one (``OLDER_SOURCE`` for the
    same image under an older source version), the insole also ``OLDER_ANALYSIS`` when its analysis version
    is not ``footwear_insole.INSOLE_VERSION``. ``fit`` = the fit of the CURRENT fsig on the base model:
    ``{status accepted|stale|outdated|refused|missing, gates, metrics, url None, freshness, created_at, error}``
    (``fit_state``; ``refused`` = the persisted failure of the fsig holds on this base model; freshness
    ``FIT_BODY_CHANGED`` for stale, ``FIT_SOURCE_CHANGED`` for outdated), ``metrics`` the record's width factor /
    cap, root lift, scale, shoe length and per side the width needed, slimming needed, extension and toe room.
    ``fits`` (``_fits``) = the fit of the current fsig per body: the base model first (``steps.fit`` again), then
    in outfit body mode ``mesh`` one row per stored outfit body, each with ``body_id`` and ``base``.
    ``preview_url`` / ``foot_pose`` (``_preview``) = the shod base model of the current fsig and its record's
    ``foot_pose`` (with ``source.fsig``) — the Wardrobe's shod preview; None without an accepted fit there;
    ``preview_freshness`` = the base fit's freshness. ``width_cap`` = the cap the next fit uses (``width_cap``).
    ``insole`` = ``insole.json``'s ``{version, nominal, gates, overlay, frame}`` (None without one);
    ``stale_reasons`` codes ``item_image_changed`` / ``source_version_changed`` / ``analysis_updated``."""
    from app.core import base_body, footwear_insole, footwear_source, garment_store as gs, garments
    from app.core.http_files import content_version
    from app.core.model_overview import CURRENT, MISSING, STALE, freshness
    from app.models.inventory import get_item, get_item_image_path
    item = get_item(item_id) or {}
    current = footwear_source.current_ssig(item_id)
    shown = shown_ssig(item_id)
    folder = footwear_source.source_dir(item_id, shown)
    try:
        fsig: Optional[str] = gs.garment_fsig(character_name, item_id, profile=profile)
    except ValueError:
        fsig = None
    source_reasons: List[str] = []
    stale: List[str] = []
    if shown != current:
        made_from = footwear_source.step_record(item_id, shown, "source").get("item_sha256")
        if made_from != footwear_source.item_image_sha256(item_id):
            source_reasons.append(ITEM_IMAGE_CHANGED)
            stale.append("item_image_changed")
        else:
            source_reasons.append(OLDER_SOURCE)
            stale.append("source_version_changed")

    steps: Dict[str, Any] = {}
    for step in footwear_source.ITEM_STEPS:
        record = footwear_source.step_record(item_id, shown, step)
        if footwear_source.step_done(item_id, shown, step):
            status = "accepted"
        elif record:
            # Why it is not accepted (footwear_source module docstring): the gates refused it, the backend
            # failed (its own words in ``error``), or load / the media switch (waiting, retry later).
            status = {footwear_source.BACKEND: "failed", footwear_source.LOAD: "waiting"}.get(
                record.get("failure"), "refused")
        else:
            status = "missing"
        reasons = list(source_reasons) if record else []
        if step == "insole" and record and record.get("version") != footwear_insole.INSOLE_VERSION:
            reasons.append(OLDER_ANALYSIS)
            if "analysis_updated" not in stale:
                stale.append("analysis_updated")
        entry: Dict[str, Any] = {
            "status": status, "gates": record.get("gates") or {}, "metrics": {}, "url": None,
            "freshness": (freshness(MISSING) if not record
                          else freshness(STALE, " · ".join(reasons)) if reasons else freshness(CURRENT)),
            "backend": record.get("backend") or "", "created_at": record.get("created_at"),
            "error": record.get("error")}
        if step == "source":
            out = folder / "upscaled.png"
            entry["upscale"] = record.get("upscale")
            size, item_size = record.get("size") or [], record.get("item_size") or []
            entry["metrics"] = _numbers({"width": size[0] if len(size) > 1 else None,
                                         "height": size[1] if len(size) > 1 else None,
                                         "item_width": item_size[0] if len(item_size) > 1 else None,
                                         "item_height": item_size[1] if len(item_size) > 1 else None})
            if _stamp(out) is not None:
                entry["url"] = _url(character_name, item_id, "image/upscaled", _stamp(out))
        elif step == "empty":
            out = folder / "empty.png"
            entry["metrics"] = _numbers(record.get("gates"))
            attempts = []
            for a in record.get("attempts") or []:
                if not isinstance(a, dict):
                    continue
                n = a.get("attempt")
                tried = folder / f"empty.try{n}.png" if isinstance(n, int) else None
                stamp = _stamp(tried)
                attempts.append({"attempt": n, "ok": a.get("ok"), "gates": a.get("gates") or {},
                                 "seed": a.get("seed"), "backend": a.get("backend") or "", "error": a.get("error"),
                                 "failure": a.get("failure"),
                                 "url": (_url(character_name, item_id, "image/empty", stamp, f"&attempt={n}")
                                         if stamp is not None else None)})
            entry["attempts"] = attempts
            if _stamp(out) is not None:
                entry["url"] = _url(character_name, item_id, "image/empty", _stamp(out))
        elif step == "cutout":
            out = folder / "cutout.png"
            size = record.get("size") or []
            entry["metrics"] = _numbers({"side": record.get("side"),
                                         "width": size[0] if len(size) > 1 else None,
                                         "height": size[1] if len(size) > 1 else None})
            if _stamp(out) is not None:
                entry["url"] = _url(character_name, item_id, "image/cutout", _stamp(out))
        elif step == "mesh":
            out = folder / "prepared.glb"
            entry["metrics"] = _numbers({**_numbers(record.get("gates")), "tris_raw": record.get("tris_raw"),
                                         "tris_prepared": record.get("tris_prepared")})
            entry["attempts"] = [a for a in record.get("attempts") or [] if isinstance(a, dict)]
            if out.is_file():
                try:
                    entry["url"] = _url(character_name, item_id, "mesh", content_version(out))
                except OSError:
                    pass
        else:  # insole
            out = folder / "insole.json"
            entry["metrics"] = _numbers(record.get("gates"))
            entry["version"] = record.get("version")
            if _stamp(out) is not None:
                entry["url"] = _url(character_name, item_id, "insole", _stamp(out))
        steps[step] = entry
    base = base_body.current_base(character_name, profile=profile) or ("", "")
    steps["fit"] = _fit_info(character_name, item_id, fsig, base[1])
    fits = _fits(character_name, item_id, fsig, base, steps["fit"], profile=profile)
    preview_url, foot_pose = _preview(character_name, item_id, fsig)

    insole = gs.read_record(folder / "insole.json")
    insole_view = ({k: insole.get(k) for k in ("version", "nominal", "gates", "overlay", "frame")}
                   if insole else None)
    image = get_item_image_path(item_id)
    image_stamp = _stamp(Path(image)) if image else None
    status = gs.status(character_name, item_id)
    queue = garments.queue_state(character_name, item_id)
    failed = status["failed"]
    if failed is not None and failed.get("step") == "fit" and steps["fit"]["status"] == "accepted":
        # The item's last-run failure is per item, not per fsig: a fit refused under another width cap must
        # not be shown beside the accepted fit of the current fsig (T27 acceptance: the cap reset).
        failed = None
    if failed is None and not status["running_step"] and fsig:
        # After a restart: the persisted failure of the current fsig still holds the piece back.
        record = gs.chain_failure(character_name, item_id, fsig, base_model_sha=base[1] or "")
        if record is not None:
            failed = {"step": record.get("step"), "error": record.get("error"), "gates": None,
                      "failed_at": record.get("failed_at")}
        elif footwear_source.refused_step(item_id) is not None:
            # The shoe source is one per item: a refusal another wearer's run recorded holds THIS wearer's
            # automatic runs back too (``garments.cached_failure``), and the chip says so.
            refused = footwear_source.refused_step(item_id)
            failed = {"step": refused["step"], "error": refused["error"], "gates": None, "failed_at": None}
    return {
        "item_id": item_id, "kind": KIND, "method": "shoe", "method_source": "world",
        "description": str(item.get("prompt_fragment") or ""), "fsig": fsig, "ssig": shown,
        "current_ssig": current, "steps": steps, "stale_reasons": stale,
        "running_step": status["running_step"], "started_at": status["started_at"],
        "queue_position": queue["queue_position"], "queue_running": queue["queue_running"], "failed": failed,
        "item_image_url": (_url(character_name, item_id, "image/source", image_stamp)
                           if image_stamp is not None else None),
        "mesh_url": steps["mesh"]["url"], "insole": insole_view, "width_cap": width_cap(profile, item_id),
        "fits": fits, "preview_url": preview_url,
        "preview_freshness": steps["fit"]["freshness"] if preview_url else None, "foot_pose": foot_pose,
        "served_fsig": None, "refit": None, "body": None, "body_id": None}
