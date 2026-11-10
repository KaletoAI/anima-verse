"""The subtract hair method's steps ``mesh_source`` / ``cut`` / ``fit`` (plan
``docs/superpowers/plans/2026-11-10-hair-subtract-method.md``; ``garments`` dispatches to them, the files are
described in ``garment_store``).

- ``mesh_source``: the accepted haired front + back views (the edit chain's ``haired`` step, stored under the
  edit-chain fsig ``garment_store.image_fsig``) are cut out locally (BiRefNet-DIS, full frame — the cut-out keeps
  the haired view's framing, which the cut's projection relies on) and ONE routed ``hair_source_mesh`` job meshes
  the haired character: ``source/{item}_{ssig}/``. Cached per ``ssig`` (the haired views' content): a method
  switch, a new base model or another shape never asks for a new job.
- ``cut``: ``garment_cut.cut_hair`` against the CURRENT base model on the CPU -> ``prepared/{item}_{fsig}.glb``
  with its record (``ssig``, ``source_sha256``, the base model + unrigged sha256, shape, thickness, the fit's
  clearance / spread, the cut's metrics and gates). Refused cuts leave a record ``accepted: false`` and no GLB.
- ``fit``: ``garment_fit.fit_hair(placed=True)`` with the cut's clearance and the gates of the hair's length
  class (``garment_fit.hair_gates``; a shell is gated like short hair) -> the usual fit GLB + record
  (``method: "subtract"``), published by ``garments._publish_fit``.

On an outfit body (``fit_on_body``) the cut runs again against THAT body (its unrigged source; its front view
frames the initial placement), then the placed fit onto its rigged model — CPU only, never a job.

Refit before re-render (``garment_source``): haired views copied in from a source made on an older base keep that
base's views with them (``garment_source.base_copy``) — the cut labels the hair against THOSE (``_views``), and
the current base front, registered into the haired views' frame, places the haired mesh (``place_mask``).
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_subtract")

SOURCE_GLB = "haired.glb"
STEPS: Tuple[str, ...] = ("mesh_source", "cut")


def _sha(path: Optional[Path]) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


def _haired(character_name: str, item_id: str, ifsig: str, view: str) -> Path:
    from app.core import garment_store as gs
    return gs.garment_path(character_name, item_id, ifsig, "image", step="haired", view=view)


def cutout_name(view: str) -> str:
    return f"haired_{view}_cut.png"


# --- mesh_source ------------------------------------------------------------------

def source_record(character_name: str, item_id: str, ssig: str) -> Dict[str, Any]:
    from app.core import garment_store as gs
    return gs.read_record(gs.source_dir(character_name, item_id, ssig) / gs.SOURCE_RECORD)


def source_glb(character_name: str, item_id: str, ssig: str) -> Optional[Path]:
    """The accepted source mesh of ``ssig`` (its record accepted, the GLB and both cut-outs on disk), else
    None."""
    from app.core import garment_store as gs
    folder = gs.source_dir(character_name, item_id, ssig)
    glb = folder / SOURCE_GLB
    if source_record(character_name, item_id, ssig).get("accepted") is not True or not glb.is_file():
        return None
    if not all((folder / cutout_name(v)).is_file() for v in gs.GARMENT_VIEWS):
        return None
    return glb


def run_source(character_name: str, item_id: str, ifsig: str, ssig: str, *, force: bool = False) -> Path:
    """The source mesh of ``ssig`` — cached unless ``force``; else the haired views' cut-outs and ONE
    ``hair_source_mesh`` job (``garment_mesh.generate_hair_source``). ``MissingInput`` without both accepted
    haired views; ``garment_mesh.MeshAttemptFailed`` (step ``mesh_source``) when the job fails — the record then
    says why (``accepted: false``)."""
    from app.core import base_body, garment_mesh, garment_store as gs
    from app.core import garment_images as gi
    from app.core.timeutils import utc_now_iso
    if not force:
        cached = source_glb(character_name, item_id, ssig)
        if cached is not None:
            return cached
    haired = {v: _haired(character_name, item_id, ifsig, v) for v in gs.GARMENT_VIEWS}
    shas = gs.haired_shas(character_name, item_id, ifsig)
    if not all(shas.values()):
        raise base_body.MissingInput("The haired views are missing — run the haired step first")
    folder = gs.source_dir(character_name, item_id, ssig)
    folder.mkdir(parents=True, exist_ok=True)
    record_path = folder / gs.SOURCE_RECORD
    cutouts: Dict[str, Path] = {}
    from PIL import Image
    for view, path in haired.items():
        data = path.read_bytes()
        with Image.open(io.BytesIO(data)) as im:
            rgb = im.convert("RGB")
        alpha = gi._mask_image(data, rgb.size)
        out = rgb.convert("RGBA")
        out.putalpha(alpha)
        target = folder / cutout_name(view)
        tmp = target.with_name(f".{target.name}.tmp")
        out.save(tmp, format="PNG")
        tmp.replace(target)
        cutouts[view] = target
    glb = folder / SOURCE_GLB
    candidate = folder / f".{SOURCE_GLB}.candidate.glb"
    base = {"ssig": ssig, "image_fsig": ifsig, "haired": shas, "face_num": garment_mesh.SOURCE_FACE_NUM,
            "cutouts": {v: _sha(p) for v, p in cutouts.items()}}
    try:
        meta = garment_mesh.generate_hair_source(character_name, cutouts, candidate)
    except garment_mesh.MeshAttemptFailed as e:
        gs.write_record(record_path, {**base, "accepted": False, "error": e.error, "created_at": utc_now_iso()})
        raise
    candidate.replace(glb)
    gs.write_record(record_path, {**base, **meta, "accepted": True, "sha256": _sha(glb), "error": None,
                                  "created_at": utc_now_iso()})
    logger.info("Hair source mesh %s/%s (%s): %s tris from %s", character_name, item_id, ssig, meta.get("tris"),
                meta.get("backend"))
    return glb


# --- cut ----------------------------------------------------------------------------

def _views(character_name: str, item_id: str, ifsig: str, ssig: str, bsig: str):
    """The cut's ``garment_cut.View`` per view: the haired view, its cut-out in the source folder and the base
    view the haired view was made on — the image group's copy of it (``garment_source.base_copy``), else the base
    view of ``bsig``. ``MissingInput`` when one is gone."""
    from app.core import base_body, garment_cut, garment_source, garment_store as gs
    from app.core.model_refs import find_ref_image
    folder = gs.source_dir(character_name, item_id, ssig)
    own = bool(garment_source.source_of(character_name, item_id, ifsig))
    views = {}
    for view in gs.GARMENT_VIEWS:
        haired = _haired(character_name, item_id, ifsig, view)
        cut = folder / cutout_name(view)
        base = (garment_source.base_copy(character_name, item_id, ifsig, view) if own
                else find_ref_image(character_name, base_body._kind(view), bsig))
        if not haired.is_file() or not cut.is_file():
            raise base_body.MissingInput("The haired views or their cut-outs are gone — run the hair chain")
        if base is None:
            raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
        views[view] = garment_cut.load_view(haired, cut, base)
    return views


def _shape(character_name: str, profile: Dict[str, Any]) -> Tuple[str, float]:
    from app.core import garment_hair
    return (garment_hair.subtract_shape(character_name, profile=profile),
            garment_hair.shell_mm(profile) / 1000.0)


def cut_done(character_name: str, item_id: str, fsig: str, ssig: str) -> bool:
    """An accepted cut of ``fsig`` made from the CURRENT source mesh of ``ssig``."""
    from app.core import garment_store as gs
    prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
    record = gs.read_record(prepared.with_suffix(".json"))
    glb = source_glb(character_name, item_id, ssig)
    return (prepared.is_file() and record.get("accepted") is True and record.get("method") == gs.SUBTRACT
            and record.get("ssig") == ssig and glb is not None and record.get("source_sha256") == _sha(glb))


def run_cut(character_name: str, item_id: str, fsig: str, ifsig: str, ssig: str, bsig: str,
            profile: Dict[str, Any], *, force: bool = False) -> Path:
    """The cut of ``fsig`` (cached unless ``force``) against the current base model. ``MissingInput`` when a
    source is gone; ``garments._Refused`` (step ``cut``) when its gates refuse — the record keeps the numbers."""
    from app.core import base_body, garment_cut, garment_store as gs
    from app.core.garments import _Refused, _write_atomic
    from app.core.timeutils import utc_now_iso
    prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
    if not force and cut_done(character_name, item_id, fsig, ssig):
        return prepared
    source = source_glb(character_name, item_id, ssig)
    if source is None:
        raise base_body.MissingInput("The hair source mesh is missing — run the mesh_source step first")
    views = _views(character_name, item_id, ifsig, ssig, bsig)
    # Haired views made on another base (a refit, ``garment_source``): the current base front, registered into
    # their frame, places the haired mesh on the current body.
    from app.core import garment_source
    from app.core.model_refs import find_ref_image
    front = find_ref_image(character_name, base_body._kind("front"), bsig)
    if front is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
    try:
        place, frame = garment_source.place_mask(character_name, item_id, ifsig, front,
                                                 views["front"].haired_mask.shape)
    except garment_source.FrameRefused as e:
        raise _Refused("cut", f"cut refused — {e}", {"ok": False, "reasons": [str(e)],
                                                      "registration": e.registration})
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    shape, thickness = _shape(character_name, profile)
    source_bytes = source.read_bytes()
    result = garment_cut.cut_hair(source_bytes, snapshot["unrigged"], snapshot["rigged"], views,
                                  shape=shape, thickness_m=thickness, place_mask=place)
    gates = {"ok": bool(result.ok), "reasons": list(result.reasons),
             "limits": {key: [kind, limit] for key, (kind, limit, _label) in garment_cut.CUT_GATES.items()}}
    record = {"accepted": bool(result.ok), "kind": "hair", "item_id": item_id, "fsig": fsig, "method": gs.SUBTRACT,
              "shape": shape, "shell_mm": round(thickness * 1000, 2), "ssig": ssig, "image_fsig": ifsig,
              "source_sha256": hashlib.sha256(source_bytes).hexdigest(), "base_signature": bsig,
              "base_model_sha256": hashlib.sha256(snapshot["rigged"]).hexdigest(),
              "unrigged_sha256": hashlib.sha256(snapshot["unrigged"]).hexdigest(),
              "clearance_m": result.clearance_m, "spread_m": result.spread_m, "cut_version": garment_cut.CUT_VERSION,
              "metrics": result.metrics, "gates": gates, "report": result.report, "frame": frame,
              "created_at": utc_now_iso()}
    if not result.ok:
        prepared.unlink(missing_ok=True)
        gs.write_record(prepared.with_suffix(".json"), record)
        raise _Refused("cut", "cut refused — " + "; ".join(result.reasons), {**gates, "metrics": result.metrics})
    _write_atomic(prepared, result.glb)
    gs.write_record(prepared.with_suffix(".json"), record)
    return prepared


# --- fit ----------------------------------------------------------------------------

def _gates(character_name: str, shape: str, profile: Dict[str, Any]):
    from app.core import garment_fit, garment_hair
    return garment_fit.hair_gates(garment_hair.hair_length_class(character_name, profile=profile),
                                  shell=shape == "shell")


def _limits(gates) -> Dict[str, Any]:
    return {key: [kind, limit] for key, (kind, limit, _label) in gates.items()}


def run_fit(character_name: str, item_id: str, kind: str, fsig: str, bsig: str, profile: Dict[str, Any]) -> Path:
    """Fit the accepted cut of ``fsig`` onto the current base model and publish it (``garments._publish_fit``).
    ``MissingInput`` without an accepted cut or when the cut was made on another base model; ``_Refused`` (step
    ``fit``) when the gates refuse."""
    from app.core import base_body, garment_fit, garment_hair, garment_store as gs
    from app.core.garments import _Refused, _kind_inputs, _publish_fit
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
    cut = gs.read_record(prepared.with_suffix(".json"))
    if not prepared.is_file() or cut.get("accepted") is not True or cut.get("method") != gs.SUBTRACT:
        raise base_body.MissingInput("The hair cut is missing — run the cut step first")
    snapshot = base_body._snapshot_base_model(character_name, bsig)
    if cut.get("unrigged_sha256") != hashlib.sha256(snapshot["unrigged"]).hexdigest():
        raise base_body.MissingInput("The hair cut was made on another base model — run the cut step")
    cut_bytes = prepared.read_bytes()
    shape = str(cut.get("shape") or "cut")
    gates = _gates(character_name, shape, profile)
    result = garment_fit.fit_hair(cut_bytes, snapshot["unrigged"], snapshot["rigged"], placed=True,
                                  clearance_m=float(cut["clearance_m"]), spread_m=float(cut["spread_m"]),
                                  gates=gates)
    verdict = {"ok": bool(result.ok), "reasons": list(result.reasons), "limits": _limits(gates)}
    if not result.ok:
        raise _Refused("fit", "fit refused — " + "; ".join(result.reasons), {**verdict, "metrics": result.metrics})
    base_sha = hashlib.sha256(snapshot["rigged"]).hexdigest()
    base_views = {v: find_ref_image(character_name, base_body._kind(v), bsig) for v in gs.GARMENT_VIEWS}
    base_images = {v: _sha(p) for v, p in base_views.items()}
    from app.core import garment_source
    record: Dict[str, Any] = {
        "accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig, "method": gs.SUBTRACT,
        "metrics": result.metrics, "gates": verdict, "report": result.report, "cut": cut.get("metrics"),
        "shape": shape, "length_class": garment_hair.hair_length_class(character_name, profile=profile),
        "base_signature": bsig, "base_model_sha256": base_sha, "body_id": bsig, "body_sha256": base_sha,
        "inputs": {**_kind_inputs(kind, character_name, profile, item_id),
                   "base_images": base_images,
                   "prepared_sha256": hashlib.sha256(cut_bytes).hexdigest(),
                   "ssig": cut.get("ssig"), "image_fsig": cut.get("image_fsig"),
                   "shape": shape, "shell_mm": cut.get("shell_mm")},
        **garment_source.fit_source(character_name, item_id, str(cut.get("image_fsig") or ""), base_images),
        "created_at": utc_now_iso()}
    return _publish_fit(character_name, item_id, kind, fsig, bsig, snapshot["rigged"], result, record)


def fit_on_body(character_name: str, item_id: str, *, body_id: str, body: Dict[str, Any],
                base_record: Dict[str, Any], profile: Dict[str, Any]):
    """The cut + placed fit of the base fit's hair on the outfit body ``body`` (``garments._snapshot_body``)
    -> ``(FitResult, record fields)``. ``MissingInput`` when a source is gone, ``_Refused`` (step ``fit``) when
    the cut's or the fit's gates refuse on this body."""
    from app.core import base_body, garment_cut, garment_fit
    from app.core.garments import _Refused
    from app.core.model_refs import find_ref_image
    inputs = base_record.get("inputs") or {}
    ssig, ifsig = str(inputs.get("ssig") or ""), str(inputs.get("image_fsig") or "")
    bsig = str(base_record.get("base_signature") or "")
    try:
        source = source_glb(character_name, item_id, ssig)
    except ValueError:
        source = None
    if source is None or not ifsig:
        raise base_body.MissingInput("The hair source mesh of the base fit is gone — run the hair chain")
    views = _views(character_name, item_id, ifsig, ssig, bsig)
    front = find_ref_image(character_name, base_body._kind("front"), body_id)
    if front is None:
        raise base_body.MissingInput("The outfit body's front view is missing — rebuild the outfit body")
    rgb, mask = garment_cut._figure_mask(Path(front).read_bytes())
    _rgb, place_mask = garment_cut.pad_into(rgb, mask, views["front"].haired_mask.shape)
    # Haired views made on another base (a refit, ``garment_source``): the body's front moves into their frame
    # by the registration of the base it was dressed from onto theirs.
    from app.core import garment_source
    base_front = find_ref_image(character_name, base_body._kind("front"),
                                str(body["meta"]["outfit_body"].get("base_signature") or bsig))
    try:
        reg = (garment_source.place_registration(character_name, item_id, ifsig, base_front,
                                                 views["front"].haired_mask.shape) if base_front else None)
    except garment_source.FrameRefused as e:
        raise _Refused("fit", f"cut on the outfit body refused — {e}",
                       {"ok": False, "reasons": [str(e)], "registration": e.registration})
    if reg is not None:
        place_mask = garment_source.warp_mask(place_mask, reg)
    shape = str(base_record.get("shape") or inputs.get("shape") or "cut")
    thickness = float(inputs.get("shell_mm") or garment_cut.DEFAULT_SHELL_M * 1000) / 1000.0
    cut = garment_cut.cut_hair(source.read_bytes(), body["unrigged"], body["rigged"], views, shape=shape,
                               thickness_m=thickness, place_mask=place_mask)
    if not cut.ok:
        raise _Refused("fit", "cut on the outfit body refused — " + "; ".join(cut.reasons),
                       {"ok": False, "reasons": list(cut.reasons), "metrics": cut.metrics})
    gates = _gates(character_name, shape, profile)
    result = garment_fit.fit_hair(cut.glb, body["unrigged"], body["rigged"], placed=True,
                                  clearance_m=cut.clearance_m, spread_m=cut.spread_m, gates=gates)
    verdict = {"ok": bool(result.ok), "reasons": list(result.reasons), "limits": _limits(gates)}
    if not result.ok:
        raise _Refused("fit", "fit on the outfit body refused — " + "; ".join(result.reasons),
                       {**verdict, "metrics": result.metrics})
    fields = {"method": "subtract", "metrics": result.metrics, "gates": verdict, "report": result.report,
              "cut": cut.metrics, "shape": shape,
              "inputs": {**{k: inputs.get(k) for k in ("ssig", "image_fsig", "shape", "shell_mm")},
                         "source_sha256": _sha(source), "body_front_sha256": _sha(front),
                         "cut_sha256": hashlib.sha256(cut.glb).hexdigest()}}
    return result, fields


# --- status for the dispatcher and the Hair tab ----------------------------------------

def step_done(character_name: str, item_id: str, step: str, fsig: str, *,
              profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether ``mesh_source`` / ``cut`` holds an accepted output for the item's current inputs."""
    from app.core import garment_store as gs
    ssig = gs.subtract_ssig(character_name, item_id, profile=profile)
    if step == "mesh_source":
        return source_glb(character_name, item_id, ssig) is not None
    if step == "cut":
        return cut_done(character_name, item_id, fsig, ssig)
    raise ValueError(f"no subtract step {step!r}")


def step_info(character_name: str, item_id: str, step: str, fsig: str, *,
              profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The Hair tab's record of ``mesh_source`` (``{status, ssig, backend, tris, error, created_at}``) or
    ``cut`` (``{status, shape, shell_mm, metrics, gates, report, created_at}``); status ``accepted`` /
    ``refused`` / ``missing`` (``stale``: an accepted cut from another source mesh)."""
    from app.core import garment_store as gs
    ssig = gs.subtract_ssig(character_name, item_id, profile=profile)
    if step == "mesh_source":
        record = source_record(character_name, item_id, ssig)
        status = ("accepted" if source_glb(character_name, item_id, ssig) is not None
                  else "refused" if record else "missing")
        return {"status": status, "ssig": ssig, "backend": record.get("backend"), "tris": record.get("tris"),
                "error": record.get("error"), "routing": record.get("routing"),
                "created_at": record.get("created_at")}
    prepared = gs.garment_path(character_name, item_id, fsig, "prepared")
    record = gs.read_record(prepared.with_suffix(".json"))
    if cut_done(character_name, item_id, fsig, ssig):
        status = "accepted"
    elif record.get("accepted") is True:
        status = "stale"
    elif record:
        status = "refused"
    else:
        status = "missing"
    report = record.get("report") or {}
    return {"status": status, "shape": record.get("shape"), "shell_mm": record.get("shell_mm"),
            "metrics": record.get("metrics") or {}, "gates": record.get("gates") or {},
            "report": {k: report.get(k) for k in ("registration", "hairline", "label", "edge", "closed", "shell",
                                                  "cut", "seconds") if k in report},
            "created_at": record.get("created_at")}

