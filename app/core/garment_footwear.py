"""Footwear as its own mesh — an outfit piece in mode ``own_mesh`` (``outfit_piece.mesh_mode``)
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
— they refuse like the fit's own gates. It publishes ``{item}_{fsig}.glb`` = that cut rigged body with the
grafted shoe nodes ``garment_footwear_<item>_left`` / ``_right`` — and for a boot (a fit split at the ankle,
``footwear_fit`` step 9) ``…_left_shaft`` / ``…_right_shaft`` too, four nodes, the shaft's material
``doubleSided`` (``graft`` refuses a repeated name, so one node per side and part; extras ``{kind, item_id,
fsig, side, part}``), its record (the fit's, ``cut`` included, every gate
of both tables under ``gates`` with ``gating`` True, the cut's stats and per-side diagnostics under
``diagnostics.<side>.cut``) and the ``low/`` tier decimated from it. The body sha in the record is the
UNCUT body's (what ``fit_state`` compares to the stored model). A fit is
keyed (item, fsig, body id) like a garment fit: two wearers make two fits of ONE source. An outfit body's fit is
DERIVED from the accepted base fit of the same fsig (``derive_compute``, Ruling A35: the shoe rides the foot joints
of the body shape, the base fit's cut is applied there; ``base_fit_sha256`` in its record — a replaced base fit makes
it stale; without an accepted base fit there is none, ``BASE_FIT_MISSING``). A derived shoe the gates refuse (a body
shape whose foot is much bigger than the plain body's: Kira's legacy body 22354, deep_outside 0.028) is kept as an
attempt (``fit_attempts`` slot ``derived``) and the shoe is fitted FRESH on that body (``fit_compute``, Ruling A40);
the record's ``fit_method`` says which (``DERIVED`` / ``FRESH_FALLBACK``), the Details preview names it. A refused fit
publishes nothing: the failure is recorded per fsig (the base: the run's
``garments._note_outcome``; an outfit body: ``garment_store.record_body_failure``) and a fit of another body or
an older ``garment_fit.FIT_VERSION`` is never served in its place (R11 ruling; the fsig holds the fit version).
"""
import os
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
    """The width cap of the character's fit of ``item_id`` as the fingerprint and the Wardrobe slider read it:
    the profile override (``width_cap_override``), ``footwear_fit.WIDTH_CAP`` without one — the default, which
    for a shoe without a shaft means "widened to the foot up to ``footwear_fit.SHOE_WIDTH_CAP``"
    (``footwear_fit.applied_width_cap``, fit version 13)."""
    from app.core import footwear_fit
    value = width_cap_override(profile, item_id)
    return footwear_fit.WIDTH_CAP if value is None else value


def width_cap_override(profile: Dict[str, Any], item_id: str) -> Optional[float]:
    """The profile override (``WIDTH_CAP_KEY``) clamped to ``footwear_fit.WIDTH_CAP_MIN`` ..
    ``footwear_fit.WIDTH_CAP``; None without a valid one or at ``WIDTH_CAP`` itself (the slider's maximum is the
    default) — what the fit gets (``footwear_fit.fit_pair``'s ``width_cap``)."""
    from app.core import footwear_fit
    caps = profile.get(WIDTH_CAP_KEY) if isinstance(profile, dict) else None
    value = caps.get(item_id) if isinstance(caps, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    value = round(min(footwear_fit.WIDTH_CAP, max(footwear_fit.WIDTH_CAP_MIN, float(value))), 4)
    return None if value >= footwear_fit.WIDTH_CAP else value


def set_width_cap(character_name: str, item_id: str, cap: Optional[float]) -> bool:
    """Store the per-fit width cap override of ``item_id`` (profile key ``WIDTH_CAP_KEY``, ``{item_id: cap}``);
    None — or ``footwear_fit.WIDTH_CAP`` itself, the slider's maximum — removes it (back to the default,
    ``width_cap_override``). ValueError for a value that is no number or lies
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
        if value >= footwear_fit.WIDTH_CAP:
            value = None  # the slider's maximum is the default (a shoe without a shaft widens to the foot)
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


#: The parts a fit may publish per side (``footwear_fit.FootwearFit.parts``): a shoe has ``foot`` only.
PARTS: Tuple[str, ...] = ("foot", "shaft")


def node_name(item_id: str, side: str, part: str = "foot") -> str:
    """The grafted node of one side and part: ``garment_footwear_<item>_<side>`` for the foot part,
    ``garment_footwear_<item>_<side>_shaft`` for a boot's shaft (boots spec 2026-11-11 § 2 goal 1)."""
    if part not in PARTS:
        raise ValueError(f"unknown footwear part {part!r}")
    return f"garment_{KIND}_{item_id}_{side}" + ("" if part == "foot" else f"_{part}")


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

    ``garments._Refused("fit", …)`` when a gate refuses — the fit's or the cut's — or the fsig is no longer
    ``fsig``; ``base_body.MissingInput`` when the source is not ready or the
    outfit body is missing; ``base_body.OutfitError`` without a base model. CPU only: never a hub job."""
    import hashlib
    from app.blender import refine
    from app.core import base_body, footwear_source, garment_fit
    from app.core import garment_store as gs
    from app.core.garments import _Refused, _snapshot_body
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
    base_fit: Optional[Tuple[bytes, Dict[str, Any], bytes]] = None
    if body:
        if not gs.is_body_id(body):
            raise ValueError(f"not an outfit body id: {str(body)[:40]!r}")
        snapshot = _snapshot_body(character_name, body)
        rigged, body_sha = snapshot["rigged"], snapshot["sha"]
        bsig = str((snapshot["meta"].get("outfit_body") or {}).get("base_signature") or "")
        body_id = body
        # Ruling A35: an outfit body wears the shoe of the plain body's fit (``derive_compute``)
        base_fit = _accepted_base_fit(character_name, item_id, fsig, profile)
        if base_fit is None:
            raise base_body.MissingInput(BASE_FIT_MISSING)
    else:
        base = base_body.current_base(character_name, profile=profile)
        if not base:
            raise ValueError(f"{character_name} is not on the base-body pipeline")
        bsig = base[0]
        rigged = base_body._snapshot_base_model(character_name, bsig)["rigged"]
        body_sha = hashlib.sha256(rigged).hexdigest()
        body_id = bsig

    path = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
    low = gs.garment_path(character_name, item_id, fsig, "low", body=body)
    # The compute (``fit_compute``: shoe fit, cut, gates, graft — pure, bytes and plain values in) runs on the refit
    # pool when it is on (``refit_pool``) and writes the fit GLB to a private temp path beside it; the record, the
    # rename into place and the distance tier are published here.
    from app.core import refit_pool
    tmp = refit_pool.temp_path(path)

    def record_of(out: Dict[str, Any], accepted: bool, method: str = "") -> Dict[str, Any]:
        now = utc_now_iso()
        parents: Dict[str, Any] = {"body_id": body_id, "body_sha256": body_sha, "base_signature": bsig,
                                   "source": _source_parents(item_id, ssig)}
        record: Dict[str, Any] = {
            "method": "shoe", "kind": kind, "item_id": item_id, "fsig": fsig, "ssig": ssig, **out["record"],
            "parents": parents, "accepted": accepted, "fit_version": garment_fit.FIT_VERSION[kind],
            "body_id": body_id, "body_sha256": body_sha, "base_signature": bsig,
            # ``rest``: the BARE body's figure box and rest soles (``footwear_rest``) for the shod preview
            # (whose body is cut); the assembly re-measures its own bare file.
            "foot_pose": {**out["foot_pose"], "rest": out["rest"],
                          "source": {"item_id": item_id, "fsig": fsig, "glb_sha256": out["glb_sha256"]}},
            "fitted_at": now, "created_at": now}
        if not body:
            parents["base_model_sha256"] = body_sha
            record["base_model_sha256"] = body_sha
        elif base_fit is not None:
            parents["base_fit_sha256"] = record["base_fit_sha256"] = hashlib.sha256(base_fit[0]).hexdigest()
        if method:
            record["fit_method"] = method
        return record

    from app.core import fit_attempts

    def keep(out: Dict[str, Any], error: str, method: str, slot: str = "") -> None:
        # Ruling A31: the refused attempt is kept per (item, body) — with its GLB when the cut ran; a body shape's
        # refused derived shoe in its own slot beside the fresh fit's attempt (Ruling A40).
        attempt = out.get("attempt")
        fit_attempts.store(character_name, item_id, fsig, body=body, kind=kind,
                           record=record_of(attempt, False, method) if attempt else
                           {"kind": kind, "item_id": item_id, "fsig": fsig, "body_id": body_id,
                            "body_sha256": body_sha, "fit_version": garment_fit.FIT_VERSION[kind],
                            **({"fit_method": method} if method else {}),
                            **({"base_model_sha256": body_sha} if not body else {}),
                            **({"base_fit_sha256": hashlib.sha256(base_fit[0]).hexdigest()}
                               if base_fit is not None else {})},
                           error=error, gates=out["gates"], glb=tmp if attempt else None,
                           tris=(attempt or {}).get("tris"), marks={"foot": out.get("marks")}, slot=slot)

    method = ""
    try:
        if base_fit is not None:
            method = DERIVED
            out = refit_pool.run(derive_compute, base_fit[0], base_fit[1], base_fit[2], insole, rigged, kind,
                                 item_id, fsig, str(tmp))
            if not out["ok"]:
                # Ruling A40: the plain body's shoe does not fit this body shape (a much bigger foot) — kept as an
                # attempt, then the shoe is fitted fresh on the shape, as on the plain body.
                derived_error = "fit refused — " + "; ".join(out["reasons"])
                keep(out, derived_error, method, fit_attempts.DERIVED)
                tmp.unlink(missing_ok=True)
                logger.info("Footwear fit %s/%s (%s) on %s: the derived shoe was refused (%s) — fitting it fresh",
                            character_name, item_id, fsig, body, derived_error)
                method = FRESH_FALLBACK
                out = refit_pool.run(fit_compute, prepared, insole, rigged, width_cap_override(profile, item_id),
                                     kind, item_id, fsig, str(tmp))
        else:
            out = refit_pool.run(fit_compute, prepared, insole, rigged, width_cap_override(profile, item_id), kind,
                                 item_id, fsig, str(tmp))
        if not out["ok"]:
            error = "fit refused — " + "; ".join(out["reasons"])
            keep(out, error, method)
            raise _Refused("fit", error, out["gates"])
        fit_record, cut_stats = out["record"], out["cut_stats"]
        record = record_of(out, True, method)
        now = record["created_at"]
        # A refit after a body change (the fsig has no base in it: the same path): the record remembers the
        # body it came from (``refitted.from_body_sha256``, Task 25) — the Wardrobe says so, the GC keeps nothing by it.
        previous = gs.read_record(path.with_suffix(".json")) if path.is_file() else {}
        if previous.get("accepted") is True and previous.get("body_sha256") \
                and previous.get("body_sha256") != body_sha:
            record["refitted"] = {"from_body_sha256": previous["body_sha256"], "at": now}
        # A distance tier of the previous fit must never pair with the new one.
        low.unlink(missing_ok=True)
        os.replace(tmp, path)
        gs.write_record(path.with_suffix(".json"), record)
        logger.info("Footwear fit %s/%s (%s): accepted on %s%s, width x%.3f, lift %.1f mm, cut %d faces removed / "
                    "%d bisected", character_name, item_id, fsig, body or bsig, f" ({method})" if method else "",
                    fit_record["scale"]["width_factor"], 1000.0 * fit_record["root_lift_m"],
                    cut_stats["removed_faces"], cut_stats["bisected_faces"])
    finally:
        tmp.unlink(missing_ok=True)
    tris = out["tris"]
    target = max(1, int(round(refine.lod_ratio("character") * tris)))
    try:
        dec = refine.decimate_to(path, target, low, tris=tris)
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
    fit_attempts.drop(character_name, item_id, body=body, keep_derived=method == FRESH_FALLBACK)
    if schedule:
        from app.core import garment_assembly
        garment_assembly.schedule(character_name)
    return path


BASE_FIT_MISSING = "The shoe is not fitted on the plain body yet — an outfit body wears the plain body's fit"
#: How a body shape's shoe was fitted (record ``fit_method``, Ruling A40): ``DERIVED`` from the plain body's
#: accepted fit (``derive_compute``, Ruling A35), or — that refused — fitted fresh on the shape (``fit_compute``).
DERIVED = "derived"
FRESH_FALLBACK = "fresh_fallback"


def _base_fit_sha(character_name: str, item_id: str, fsig: str) -> str:
    """sha256 of the stored base fit GLB of ``fsig`` ("" without one)."""
    from app.core import garment_store as gs
    from app.core.base_body import file_sha256
    path = gs.garment_path(character_name, item_id, fsig, "fit")
    return file_sha256(path) if path.is_file() else ""


def _accepted_base_fit(character_name: str, item_id: str, fsig: str,
                       profile: Dict[str, Any]) -> Optional[Tuple[bytes, Dict[str, Any], bytes]]:
    """``(fit GLB, record, uncut base model)`` of the ACCEPTED base fit of ``fsig`` on the current base model
    (``fit_state`` "accepted"), else None — what an outfit body's fit derives from (``derive_compute``)."""
    import hashlib
    from app.core import base_body, garment_store as gs
    base = base_body.current_base(character_name, profile=profile)
    if not base:
        return None
    rigged = base_body._snapshot_base_model(character_name, base[0])["rigged"]
    if fit_state(character_name, item_id, fsig, hashlib.sha256(rigged).hexdigest()) != "accepted":
        return None
    path = gs.garment_path(character_name, item_id, fsig, "fit")
    return path.read_bytes(), gs.read_record(path.with_suffix(".json")), rigged


def fit_compute(prepared: bytes, insole: Dict[str, Any], rigged: bytes, cap: Optional[float], kind: str,
                item_id: str, fsig: str, out: str) -> Dict[str, Any]:
    """The pure part of ``fit`` (a refit-pool worker runs it — ``refit_pool``): fit the prepared shoe
    (``footwear_fit.fit_pair``) on the rigged body, cut every body primitive (``footwear_cut.apply_cut``), judge
    the cut (``cut_gates``) and graft the shoe parts — once more with the upper fitted to the foot's height when the
    first attempt is refused and the shoe is a closed toe box ready for it (fit version 15, ``footwear_fit`` module
    docstring "Shoe height"). Reads nothing but its arguments; writes the fit GLB to the
    private temp path ``out`` when accepted. ``{ok: False, reasons, gates}`` when a gate refuses — plus, when a cut
    gate refused a fit that was cut (Ruling A31), ``attempt`` (the shape below; the refused GLB written to ``out``)
    and ``marks`` (``footwear_cut.cut_gates``) —, else ``{ok: True, record, foot_pose, cut_stats, rest, glb_sha256,
    tris}`` (``record`` = the fit's own record part with the cut gates and diagnostics)."""
    from app.core import footwear_fit, glb_mesh
    positions, faces, uvs, image, mime, material = glb_mesh.static_arrays(prepared)
    n = len(positions)
    shoe = glb_mesh.GarmentMesh(positions=positions, normals=None, uvs=uvs, indices=faces,
                                joints=np.zeros((n, 4), np.int64), weights=np.zeros((n, 4)), joint_names=[],
                                image=image, mime=mime, material=material)
    body, joints = glb_mesh.body_arrays(rigged), glb_mesh.joint_bind_matrices(rigged)
    prims = glb_mesh.body_primitive_arrays(rigged)
    # Two attempts (fit version 15, boots plan Ruling 15i): the fit as it is; only when that is refused — by the fit's
    # gates or the cut's — and the shoe has a closed toe box to raise (``scale.height_ready``), once more with the
    # upper fitted to the foot's height. An accepted first attempt is the whole answer (an accepted look never
    # changes); the second attempt's outcome stands, a toe box it cannot raise enough names the mesh as the defect.
    att = _fit_attempt(footwear_fit.fit_pair(insole, shoe, body, joints, width_cap=cap), prims, joints)
    if not att.get("ok") and (att["result"].record.get("scale") or {}).get("height_ready"):
        att = _fit_attempt(footwear_fit.fit_pair(insole, shoe, body, joints, width_cap=cap, fit_height=True),
                           prims, joints)
        flat = footwear_fit.too_flat_reason(att["result"].record)
        if not att["ok"] and flat:
            att["reasons"] = [flat] + att["reasons"]
            att["gates"]["reasons"] = [flat] + list(att["gates"].get("reasons") or [])
    if not att["ok"]:
        refused: Dict[str, Any] = {"ok": False, "reasons": att["reasons"], "gates": att["gates"]}
        if "replaced" in att:
            # Ruling A31: the refused attempt as it would have been published (the cut body + the shoe parts), its
            # record and the foot points the refusing cut gates counted — the Details preview shows it, marked.
            refused["attempt"] = _attempt_out(att, rigged, kind, item_id, fsig, out)
            refused["marks"] = att.get("marks")
        return refused
    return {"ok": True, **_attempt_out(att, rigged, kind, item_id, fsig, out)}


def _attempt_out(att: Dict[str, Any], rigged: bytes, kind: str, item_id: str, fsig: str,
                 out: str) -> Dict[str, Any]:
    """Graft one cut attempt of ``fit_compute`` (accepted or refused) onto the cut body, write it to ``out`` and
    return ``{record, foot_pose, cut_stats, rest, glb_sha256, tris}``."""
    import hashlib
    from app.core import footwear_fit, footwear_rest, glb_mesh
    result, replaced, cut_stats = att["result"], att["replaced"], att["cut_stats"]

    blob = glb_mesh.rewrite_body_primitives(rigged, replaced)
    for side in footwear_fit.SIDES:
        for part in PARTS:
            mesh = result.parts[side].get(part)
            if mesh is None:
                continue
            # the shaft is an open tube looked into from the collar: both faces of its wall are drawn; its node names
            # the collar's bind height (footwear_fit step 9) — the shaft's top for every reader of the GLB
            extras = {"kind": kind, "item_id": item_id, "fsig": fsig, "side": side, "part": part}
            if part == "shaft":
                extras["collar_bind_m"] = result.record["sides"][side]["split"]["collar_bind_m"]
            blob = glb_mesh.graft(blob, mesh, name=node_name(item_id, side, part), extras=extras,
                                  material_overrides={"doubleSided": True} if part == "shaft" else None)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return {"record": result.record, "foot_pose": result.foot_pose, "cut_stats": cut_stats,
            "rest": footwear_rest.rest_measurement(rigged), "glb_sha256": hashlib.sha256(blob).hexdigest(),
            "tris": len(glb_mesh.static_arrays(blob)[1])}


def derive_compute(base_fit: bytes, base_record: Dict[str, Any], base_rigged: bytes, insole: Dict[str, Any],
                   rigged: bytes, kind: str, item_id: str, fsig: str, out: str) -> Dict[str, Any]:
    """The fit of an OUTFIT body (a body shape) derived from the accepted base fit of the same fsig (Ruling A35) —
    ``fit_compute``'s contract. A body shape's foot is meshed from its own views (Kai's ``obf6474c3b``: the forefoot
    30 mm high at the ball against 25.5 / 27.6 mm on the plain body, deep_outside 2.4 %): fitted fresh, the shoe's
    toe box had to be raised (``fit_height``) and the foot was refused ("Foot too high"). The shoe a character wears
    is the one fitted on the plain body; on the shape it rides the same bones:

    - every vertex of the base fit's shoe parts is carried by its own skin — joint by joint the shape's bind frame
      times the inverse of the base's (``J_shape · J_base^-1``), blended with its weights: the shoe keeps its place
      in each bone's frame (placement, extension, toe counter and contacts are bone-local in the record) — the foot
      part raised by how much higher the shape's sole sits under its Foot joint than the plain body's
      (``SOLE_SHIFT``: the mean of the heel and ball contacts of ``footwear_fit.measure_feet``, bind height above
      the Foot joint; the uncut ``base_rigged`` is the plain body). Kai's ``obf6474c3b`` sits 4.5 / 11.3 mm
      (left / right) higher on its soles than ``base634402e5``; without it the shoes kept the plain body's
      ankle-to-sole heights, the right foot floated inside its shoe and the lifts differed by 11.9 mm;
    - the base fit's ``cut`` (bone-local, ``footwear_cut.cut_description``) is applied to the shape's primitives
      with the shape's joints — the foot under the shoe is conformed, slimmed and removed there, never the shoe
      raised — and judged by the cut gates (``_fit_attempt``);
    - per side the lift onto the shape's floor (``floor − Pf[1, 3]``, ``Pf = B_f · J_f · placement · FrameM^-1``
      with the extension ``B_f`` about the shape's foot joint), the root lift, the lift asymmetry and the stand
      floor (the posed shoe's lowest point) are measured again and gated like a fit (``footwear_fit.FIT_GATES``);
      a boot's ``collar_bind_m`` rides the Leg joint; ``foot_pose`` carries the shape's bind contacts.

    ``{ok: False, reasons, gates}`` (plus ``attempt`` / ``marks`` when the cut gates refused a cut fit, as
    ``fit_compute``, Ruling A31) or ``{ok: True, record, foot_pose, cut_stats, rest, glb_sha256, tris}``; the record
    names the base fit (``derived.base_fit_sha256``), its bone names are the shape's own spelling."""
    import copy
    import hashlib
    from types import SimpleNamespace
    from app.core import footwear_fit, glb_mesh
    from app.core.footwear_fit import _about, _apply, _frame_matrix, _unit
    from app.core.rig_contract import norm_bone_name
    record = copy.deepcopy(base_record)
    for key in ("accepted", "parents", "fitted_at", "created_at", "low", "refitted", "body_id", "body_sha256",
                "base_model_sha256", "base_signature", "foot_pose", "fit_version", "method", "kind", "item_id",
                "fsig", "ssig"):
        record.pop(key, None)
    Jb, Js = glb_mesh.joint_bind_matrices(base_fit), glb_mesh.joint_bind_matrices(rigged)
    moved = {name: Js[name] @ np.linalg.inv(Jb[name]) for name in Jb if name in Js}
    body = glb_mesh.body_arrays(rigged)
    # bone names in the record are the body's own (``measure_feet``): the shape's spelling ("mixamorig:LeftFoot")
    own_names = {norm_bone_name(str(n)): str(n) for n in body.joint_names}

    def own(name: Any) -> str:
        return own_names.get(norm_bone_name(str(name)), str(name))
    try:
        feet_b = footwear_fit.measure_feet(glb_mesh.body_arrays(base_rigged), glb_mesh.joint_bind_matrices(base_rigged))
        feet_s = footwear_fit.measure_feet(body, Js)
    except ValueError as e:
        return {"ok": False, "reasons": [str(e)], "gates": {"ok": False}}

    def sole(fm: Any) -> float:
        return 0.5 * (float(fm.heel_contact[1]) + float(fm.ball_contact[1])) - float(fm.ankle[1])
    floor = float(np.asarray(body.positions, np.float64)[:, 1].min())
    FrameM_inv = np.linalg.inv(_frame_matrix(insole))
    parts: Dict[str, Dict[str, Any]] = {}
    lifts: Dict[str, float] = {}
    lowest: List[float] = []
    contacts_pose: Dict[str, List[Dict[str, Any]]] = {}
    for side, rec in (record.get("sides") or {}).items():
        parts[side] = {}
        side_parts: Dict[str, Any] = {}
        for part in PARTS:
            try:
                mesh = glb_mesh.garment_arrays(base_fit, node_prefix=node_name(item_id, side, part), exact=True)
            except ValueError:
                continue
            side_parts[part] = mesh
        if "foot" not in side_parts:
            return {"ok": False, "reasons": [f"The base fit has no {side} shoe"], "gates": {"ok": False}}
        fkey, tkey = f"{side}foot", f"{side}toebase"
        if fkey not in Js or tkey not in Js or fkey not in Jb or tkey not in Jb:
            return {"ok": False, "reasons": [f"The body has no {side} foot joints"], "gates": {"ok": False}}
        Jf, Jt = Js[fkey], Js[tkey]
        shift = np.eye(4)
        shift[1, 3] = sole(feet_s[side]) - sole(feet_b[side])
        rec["sole_shift_m"] = float(shift[1, 3])
        side_moved = {**moved, fkey: shift @ moved[fkey], tkey: shift @ moved[tkey]}
        # the cut and the placement ride the raised foot part: world -> cut through the shift back
        rec["placement_bind"] = np.linalg.inv(Jf) @ shift @ Jf @ np.asarray(rec["placement_bind"], np.float64)
        desc = ((record.get("cut") or {}).get("sides") or {}).get(side)
        if desc is not None:
            desc["foot_joint"], desc["toe_joint"] = own(desc["foot_joint"]), own(desc["toe_joint"])
            desc["frame"] = (np.asarray(desc["frame"], np.float64) @ np.linalg.inv(Jf) @ np.linalg.inv(shift)
                             @ Jf).tolist()
        axis = _unit(Jf[:3, :3] @ np.asarray(rec["extension"]["axis_local"], np.float64))
        Bf = _about(Jf[:3, 3], axis, np.radians(float(rec["extension"]["deg"])))
        Bt = _about(_apply(Bf, Jt[:3, 3]), axis, np.radians(float(rec["toe_counter"]["deg"]))) @ Bf
        posed_by = {fkey: Bf, tkey: Bt}
        side_low = np.inf
        for part, mesh in side_parts.items():
            names = [norm_bone_name(n) for n in mesh.joint_names]
            X = np.asarray(mesh.positions, np.float64)
            Xh = np.concatenate([X, np.ones((len(X), 1))], axis=1)
            new, posed = np.zeros_like(X), np.zeros_like(X)
            J, W = np.asarray(mesh.joints, np.int64), np.asarray(mesh.weights, np.float64)
            for slot in range(J.shape[1]):
                for col, name in enumerate(names):
                    sel = (J[:, slot] == col) & (W[:, slot] > 0)
                    if not sel.any():
                        continue
                    T = side_moved.get(name, np.eye(4))
                    Y = (Xh[sel] @ T.T)[:, :3]
                    new[sel] += W[sel, slot, None] * Y
                    B = posed_by.get(name, np.eye(4))
                    posed[sel] += W[sel, slot, None] * _apply(B, Y)
            total = W.sum(1, keepdims=True)
            new = np.where(total > 0, new / np.maximum(total, 1e-12), X)
            posed = np.where(total > 0, posed / np.maximum(total, 1e-12), X)
            side_low = min(side_low, float(posed[:, 1].min()))
            parts[side][part] = glb_mesh.GarmentMesh(
                positions=new, normals=mesh.normals, uvs=mesh.uvs, indices=mesh.indices, joints=mesh.joints,
                weights=mesh.weights, joint_names=list(mesh.joint_names), image=mesh.image, mime=mesh.mime,
                material=mesh.material, colors=mesh.colors)
        placement = np.asarray(rec["placement_bind"], np.float64)
        Pf = Bf @ Jf @ placement @ FrameM_inv
        placement_base = np.asarray(base_record["sides"][side]["placement_bind"], np.float64)
        Pf_base = (_about(Jb[fkey][:3, 3], _unit(Jb[fkey][:3, :3] @ np.asarray(rec["extension"]["axis_local"],
                                                                                np.float64)),
                          np.radians(float(rec["extension"]["deg"]))) @ Jb[fkey] @ placement_base @ FrameM_inv)
        lifts[side] = floor - float(Pf[1, 3])
        rec["lift_m"] = lifts[side]
        lowest.append(side_low)
        # contacts: the same point of the shoe frame, posed on this body and taken back to its bind
        recs, pose = [], []
        base_b = {fkey: _about(Jb[fkey][:3, 3], _unit(Jb[fkey][:3, :3] @ np.asarray(rec["extension"]["axis_local"],
                                                                                    np.float64)),
                               np.radians(float(rec["extension"]["deg"])))}
        base_b[tkey] = (_about(_apply(base_b[fkey], Jb[tkey][:3, 3]),
                               _unit(Jb[fkey][:3, :3] @ np.asarray(rec["extension"]["axis_local"], np.float64)),
                               np.radians(float(rec["toe_counter"]["deg"]))) @ base_b[fkey])
        for c in rec.get("contacts") or []:
            key = norm_bone_name(str(c["bone"]))
            if key not in base_b or key not in Jb:
                continue
            posed_base = _apply(base_b[key], _apply(Jb[key], np.asarray(c["pos_local"], np.float64)))
            pt = _apply(np.linalg.inv(Pf_base), posed_base)
            pos = _apply(np.linalg.inv(posed_by[key]), _apply(Pf, pt))
            recs.append({**c, "bone": own(c["bone"]), "pos_local": _apply(np.linalg.inv(Js[key]), pos)})
            pose.append({"bone": own(c["bone"]), "pos": pos, "role": c.get("role")})
        rec["contacts"] = recs
        contacts_pose[side] = pose
        split = rec.get("split") or {}
        if split.get("is_boot") and split.get("collar_bind_m") is not None and "shaft" in side_parts:
            leg = norm_bone_name(side_parts["shaft"].joint_names[2]) if len(side_parts["shaft"].joint_names) > 2 else ""
            if leg in moved:
                p = np.array([Jb[leg][0, 3], float(split["collar_bind_m"]), Jb[leg][2, 3]])
                split["collar_bind_m"] = float(_apply(moved[leg], p)[1])
    if not lifts:
        return {"ok": False, "reasons": ["The base fit has no sides"], "gates": {"ok": False}}
    root_lift = max(lifts.values())
    record["root_lift_m"] = root_lift
    metrics = {"lift_asymmetry_mm": abs(lifts.get("left", root_lift) - lifts.get("right", root_lift)) * 1000.0,
               "stand_floor_mm": (min(lowest) + root_lift - floor) * 1000.0}
    table = {name: (footwear_fit.FIT_GATES[name][0], footwear_fit.FIT_GATES[name][1], footwear_fit.GATE_LABELS[name])
             for name in metrics}
    ok, reasons = footwear_fit.check_gates(metrics, table)
    gates = record.setdefault("gates", {})
    for name, value in metrics.items():
        kind_, limit = footwear_fit.FIT_GATES[name]
        gates[name] = {"value": value, "limit": list(limit) if isinstance(limit, tuple) else limit,
                       "ok": footwear_fit.check_gates({name: value}, {name: table[name]})[0], "gating": True}
    record["derived"] = {"base_fit_sha256": hashlib.sha256(base_fit).hexdigest(),
                         "base_lifts_m": {s: (base_record.get("sides") or {}).get(s, {}).get("lift_m") for s in lifts}}
    if not ok:
        return {"ok": False, "reasons": list(reasons), "gates": {"ok": False, "reasons": list(reasons), **gates}}
    # the bones' axes and angles are bone-local: the base fit's, unchanged (under the shape's bone names)
    bones = {own(name): value for name, value in ((base_record.get("foot_pose") or {}).get("bones") or {}).items()}
    foot_pose = footwear_fit._r({"version": footwear_fit.FOOT_POSE_VERSION, "bones": bones,
                                 "root_lift_m": root_lift, "contacts": contacts_pose})
    result = SimpleNamespace(ok=True, reasons=[], record=record, parts=parts, foot_pose=foot_pose)
    att = _fit_attempt(result, glb_mesh.body_primitive_arrays(rigged), Js)
    result.record = footwear_fit._r(result.record)
    if not att["ok"]:
        refused: Dict[str, Any] = {"ok": False, "reasons": att["reasons"], "gates": att["gates"]}
        if "replaced" in att:  # Ruling A31: the refused attempt, as ``fit_compute`` keeps it
            refused["attempt"] = _attempt_out(att, rigged, kind, item_id, fsig, out)
            refused["marks"] = att.get("marks")
        return refused
    return {"ok": True, **_attempt_out(att, rigged, kind, item_id, fsig, out)}


def _fit_attempt(result: Any, prims: List["glb_mesh.Prim"], joints: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """One attempt of ``fit_compute``: a fit that ran (``footwear_fit.fit_pair``) cut on every body primitive and
    judged by the cut gates. ``{ok, result, reasons, gates}`` + ``replaced`` / ``cut_stats`` when the fit ran."""
    from app.core import footwear_cut, footwear_fit, glb_mesh
    if not result.ok:
        return {"ok": False, "result": result, "reasons": list(result.reasons),
                "gates": {"ok": False, "reasons": list(result.reasons), **(result.record.get("gates") or {})}}

    # The cut on every body primitive, then the cut gates on the body as a whole (spec § 7.1, § 8).
    cut = result.record["cut"]
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
    # every part: a boot's shaft joins the enclosure and is judged by ``shaft_poke`` (spec § 7, § 9)
    cut_gates = footwear_cut.cut_gates(_merged(list(replaced.values())), result.parts, cut, joints=joints,
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
        return {"ok": False, "result": result, "reasons": list(cut_gates["reasons"]),
                "gates": {"ok": False, "reasons": list(cut_gates["reasons"]), **result.record["gates"]},
                "replaced": replaced, "cut_stats": cut_stats, "marks": cut_gates.get("marks")}
    return {"ok": True, "result": result, "replaced": replaced, "cut_stats": cut_stats}


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
        # derived from the plain body's fit (Ruling A35): stale once that fit is replaced
        if record.get("base_fit_sha256") != _base_fit_sha(character_name, item_id, fsig):
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

    Derives the fit from the accepted base fit of the same fsig (``fit`` with ``body`` -> ``derive_compute``,
    Ruling A35; ``base_fit_sha256`` in the record and in the failure key). ``build`` (the assembly build, never serving) fits a missing / stale / outdated
    one first, serialised per body; a refusal or failure is recorded per body (``record_body_failure``, the
    fit version as the third key). While the current fsig's fit is not usable and none is pending, the newest
    graftable fit of the item on these body bytes under another fsig (an older fit version: the version is part
    of the footwear fsig) is served, ``error`` naming why (Ruling R7b, plan 2026-11-12 fit-sdf-speed-drape: a shoe
    never goes missing because of a version bump; was R11: nothing). Nothing of another body is served. Without a
    ready source nothing is fitted and nothing recorded (``SOURCE_NOT_READY``); nothing is fitted on a body whose
    stored bytes are no longer ``body_sha``."""
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
        failure = (gs.body_failure(character_name, item_id, fsig, body_id, body_sha=body_sha,
                                   base_fit_sha=_base_fit_sha(character_name, item_id, fsig),
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
                                           base_fit_sha=_base_fit_sha(character_name, item_id, fsig),
                                           fit_version=version)
                state, failure = current()
    record = gs.read_record(fit_path.with_suffix(".json"))
    # A fit the USER accepted (Ruling A31) serves only while it is the accepted fit by today's state (the shoe
    # source too) — a changed input voids it.
    usable = (fit_path.is_file() and record.get("accepted") is True and record.get("body_id") == body_id
              and record.get("body_sha256") == body_sha and record.get("fit_version") == version
              and (not isinstance(record.get("user_accepted"), dict) or state == "accepted"))
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
    if not usable and not pending:
        older = gs.newest_body_footwear_fit(character_name, item_id, body_id, body_sha)
        if older is not None:
            old_fsig = gs.parse_name(older[0])[1]
            old_low = gs.garment_path(character_name, item_id, old_fsig, "low", body=body_id)
            return {"fit": older[0], "low": old_low if old_low.is_file() else None, "record": older[1],
                    "fsig": old_fsig, "pending": False, "error": error}
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
    factor / cap, root lift (SIGNED — negative when the shod root descends, spec 2026-11-11 § 13.2), scale
    (``k_m_per_unit``, shoe ``length_m``) and per side the width needed, the
    slimming needed, the extension and the toe room; ``split`` / ``shaft`` = ``_split_view`` / ``_fit_shaft_view``
    of the accepted record (None without one)."""
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
            failure = gs.body_failure(character_name, item_id, fsig, body, body_sha=body_sha,
                                      base_fit_sha=_base_fit_sha(character_name, item_id, fsig),
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
    tall = scale.get("height_needed") or {}
    metrics = _numbers({
        "width_factor": scale.get("width_factor"), "width_cap": scale.get("width_cap"),
        "width_cap_applied": scale.get("width_cap_applied"), "height_factor": scale.get("height_factor"),
        "root_lift_m": record.get("root_lift_m"), "k_m_per_unit": scale.get("k_m_per_unit"),
        "length_m": scale.get("length_m"),
        **{f"{key}_{side}": value for side in ("left", "right") for key, value in (
            ("width_needed", needed.get(side) if isinstance(needed, dict) else None),
            ("slim_needed", slim.get(side) if isinstance(slim, dict) else None),
            ("height_needed", tall.get(side) if isinstance(tall, dict) else None),
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
            # the row's pill already says "Refused (gate)": the reason without the fit path's own prefix
            "freshness": fresh, "created_at": record.get("fitted_at"),
            "error": _strip_refused(error) if isinstance(error, str) else error,
            "split": _split_view(record), "shaft": _fit_shaft_view(record)}


def _strip_refused(error: str) -> str:
    from app.core.fit_attempts import strip_prefix
    return strip_prefix(error)


def _split_view(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``split`` of a fit row (boots spec 2026-11-11 § 15): ``{is_boot, band_m, margin_m, sides: {side: {y_m, topline_m,
    collar_above_ankle_mm, parts: {foot, shaft?}}}}`` from the record's ``split`` and ``sides.<side>`` (``parts``
    = the face count per node part); None for a record without a split (an older fit version, no fit). A shoe
    carries it too: ``is_boot`` False, ``collar_above_ankle_mm`` the diagnostic."""
    split = record.get("split")
    if not isinstance(split, dict):
        return None
    sides: Dict[str, Any] = {}
    for side, data in (record.get("sides") or {}).items():
        if not isinstance(data, dict):
            continue
        own = data.get("split") if isinstance(data.get("split"), dict) else {}
        sides[side] = {**_numbers({"y_m": own.get("y_m"), "topline_m": own.get("topline_m"),
                                   "collar_above_ankle_mm": own.get("collar_above_ankle_mm")}),
                       "parts": _numbers(data.get("parts"))}
    return {"is_boot": bool(split.get("is_boot")), "band_m": split.get("band_m"), "margin_m": split.get("margin_m"),
            "sides": sides}


def _fit_shaft_view(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``shaft`` of a fit row: the record's ``shaft`` summary (``class``, worse-side push / inside / seam / follow
    numbers, cap removed, closed share, top, clip, knee margin) for a SPLIT fit; None for a shoe."""
    split = record.get("split")
    shaft = record.get("shaft")
    if not (isinstance(split, dict) and split.get("is_boot") and isinstance(shaft, dict)):
        return None
    return {"class": shaft.get("class"), **_numbers(shaft)}


def _insole_view(insole: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``insole`` of ``info``: ``insole.json``'s ``{version, nominal, gates, overlay, frame}`` plus ``shaft`` — for a
    boot (shaft class other than ``none``) ``{class, collar_h_m (nominal), top_m (the top closed slab above the
    ground, nominal), closed_share, cap_removed, slabs, slabs_closed}``, else None — and ``overlay.slabs``: per tube
    slab its measured extent as a closed ring ``{points [[x, y, z] x5], closed}`` in the mesh's own coordinates (the
    third overlay colour of the mesh preview). None without an insole.json."""
    if not insole:
        return None
    from app.core import footwear_insole
    view = {k: insole.get(k) for k in ("version", "nominal", "gates", "overlay", "frame")}
    shaft = insole.get("shaft") if isinstance(insole.get("shaft"), dict) else {}
    if shaft.get("class") in (None, "none"):
        view["shaft"] = None
        return view
    k = (insole.get("nominal") or {}).get("k")
    slabs = [s for s in shaft.get("slabs") or [] if isinstance(s, dict)]
    top = shaft.get("top_raw")
    view["shaft"] = {
        "class": shaft.get("class"), "collar_h_m": shaft.get("collar_h_nominal"),
        "top_m": float(top) * float(k) if isinstance(top, (int, float)) and isinstance(k, (int, float)) else None,
        "closed_share": shaft.get("closed_share"), "cap_removed": shaft.get("cap_removed"),
        "slabs": len(slabs), "slabs_closed": sum(1 for s in slabs if s.get("closed"))}
    rings: List[Dict[str, Any]] = []
    try:
        frame = footwear_insole.frame_of(insole)
    except (KeyError, TypeError, ValueError):
        frame = None
    if frame is not None:
        for s in slabs:
            box = [s.get(key) for key in ("x_min", "x_max", "z_min", "z_max")]
            if not all(isinstance(v, (int, float)) for v in box) or not isinstance(s.get("y"), (int, float)):
                continue
            x0, x1, z0, z1 = (float(v) for v in box)
            y = float(s["y"])
            corners = np.array([[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1], [x0, y, z0]])
            rings.append({"points": [[round(float(c), 6) for c in p] for p in frame.to_mesh(corners)],
                          "closed": bool(s.get("closed"))})
    view["overlay"] = {**(view.get("overlay") or {}), "slabs": rings}
    return view


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
    then one row per stored outfit body (meshed shape, ``stored_outfit_bodies``). Each row is
    ``_fit_info`` plus ``body_id`` (the base signature / the outfit body id) and ``base`` (True on the base)."""
    from app.core import garments
    rows: List[Dict[str, Any]] = [{"body_id": base[0] or None, "base": True, **base_fit}]
    for body_id in stored_outfit_bodies(character_name):
        body_sha = garments.body_sha256(character_name, body_id)
        rows.append({"body_id": body_id, "base": False,
                     **_fit_info(character_name, item_id, fsig, body_sha, body=body_id)})
    return rows


def _built_at(path: Optional[Path]) -> Optional[str]:
    from app.core.model_overview import built_at
    try:
        return built_at(path)
    except ValueError:
        return None


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
    source, ``shown_ssig``), current_ssig, running_step, started_at, queue_position, queue_running,
    queue_beside, failed, steps, item_image_url, mesh_url, insole, stale_reasons, fits, preview_url,
    preview_freshness, foot_pose, served_fsig None, refit None, body None, body_id None}``.

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
    ``insole`` = ``_insole_view``: ``insole.json``'s ``{version, nominal, gates, overlay, frame}`` plus the boot's
    ``shaft`` summary and the slab rings ``overlay.slabs`` (None without one); every fit row carries ``split`` and
    ``shaft`` (``_split_view`` / ``_fit_shaft_view``);
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
    insole_view = _insole_view(insole)
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
        "queue_position": queue["queue_position"], "queue_running": queue["queue_running"],
        "queue_beside": queue["queue_beside"], "failed": failed,
        "item_image_url": (_url(character_name, item_id, "image/source", image_stamp)
                           if image_stamp is not None else None),
        "mesh_url": steps["mesh"]["url"], "insole": insole_view, "width_cap": width_cap(profile, item_id),
        "fits": fits, "preview_url": preview_url,
        # Ruling UI3 a: when the shown shoe mesh / the shod preview were made (the 3D previews' caption).
        "mesh_built_at": _built_at(mesh_path(character_name, item_id)) if steps["mesh"]["url"] else None,
        "preview_built_at": (_built_at(gs.garment_path(character_name, item_id, fsig, "fit"))
                             if preview_url and fsig else None),
        "preview_freshness": steps["fit"]["freshness"] if preview_url else None, "foot_pose": foot_pose,
        "served_fsig": None, "refit": None, "body": None, "body_id": None}
