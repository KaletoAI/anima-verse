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
``footwear_source.run_source`` under the item lock, then ``fit`` — not wired
yet (plan Task 9/10, ``FIT_PENDING``): the chain ends after the insole.
``info`` is the Wardrobe panel; the footwear routes of
``app/routes/characters.py`` serve the files it names (``image_path``,
``mesh_path``, ``insole_path``).
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

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


def fsig_inputs(character_name: str, item: Dict[str, Any], *, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The footwear fingerprint inputs: the item's current source ``ssig``,
    the insole analysis version, the width cap and the fit version — no base
    signature, no base images, no base model."""
    from app.core import footwear_insole, footwear_source, garment_fit
    item_id = str(item.get("id") or "")
    return {"ssig": footwear_source.current_ssig(item_id), "insole_version": footwear_insole.INSOLE_VERSION,
            "width_cap": width_cap(profile, item_id), "fit_version": garment_fit.FIT_VERSION[KIND]}


# --- the run ------------------------------------------------------------------------------------------------------------

#: What a footwear run says about its fit step until the fit lands (plan Task 9/10): the chain ends after the insole.
FIT_PENDING = "The fit onto the wearer is not available yet — the chain ends after the insole"
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
    outputs before it copied), so it and every later item step run again. The fit is not wired yet
    (``FIT_PENDING``): the result carries ``fit: "pending"``.

    -> ``{ok: True, fsig, ran, fit}`` or ``{ok: False, fsig, step, error, gates, error_type, ran}`` plus
    ``retry_later: True`` for load / the media switch (``RETRY_LATER_ERRORS``: no failure record)."""
    from app.core import footwear_insole, footwear_source, garment_store as gs
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
        # ``fit``: lands with plan Task 9/10 (FIT_PENDING) — nothing to run, nothing produced.
        return {"ok": True, "fsig": fsig, "ran": ran, "fit": "pending"}
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


def fit_state(character_name: str, item_id: str, fsig: str, body_sha: str, *, body: str = "") -> str:
    """The state of the wearer's fit of ``fsig`` on ``body`` ("" = the base): ``missing`` (no accepted fit),
    ``stale`` (made on other body bytes, or by an older ``garment_fit.FIT_VERSION``), ``outdated`` (the
    source mesh it was fitted from was replaced or removed) or ``accepted``. Until the fit step lands
    (plan Task 10) no run writes such a record: every footwear fit is ``missing``."""
    from app.core import footwear_source, garment_store as gs
    from app.core.base_body import file_sha256
    from app.core.garment_fit import FIT_VERSION
    fit = gs.garment_path(character_name, item_id, fsig, "fit", body=body)
    record = gs.read_record(fit.with_suffix(".json"))
    if not fit.is_file() or record.get("accepted") is not True:
        return "missing"
    used = record.get("body_sha256") if body else record.get("base_model_sha256")
    if not body_sha or used != body_sha:
        return "stale"
    if record.get("fit_version") != FIT_VERSION.get(KIND):
        return "stale"
    source = (record.get("parents") or {}).get("source") or {}
    try:
        prepared = footwear_source.source_dir(item_id, str(source.get("ssig") or "")) / "prepared.glb"
    except ValueError:
        return "outdated"
    if not prepared.is_file() or source.get("mesh_sha256") != file_sha256(prepared):
        return "outdated"
    return "accepted"


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


def info(character_name: str, item_id: str, *, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The Wardrobe panel of a footwear piece (``garments.garment_info`` of kind ``footwear``):

    ``{item_id, kind "footwear", method "shoe", method_source "world", description, fsig, ssig (the shown
    source, ``shown_ssig``), current_ssig, running_step, started_at, queue_position, queue_running, failed,
    steps, item_image_url, mesh_url, insole, stale_reasons, preview_url None, served_fsig None, refit None,
    body None, body_id None}``.

    ``steps`` in chain order: ``source``, ``empty``, ``cutout``, ``mesh``, ``insole`` each ``{status
    accepted|refused|failed|waiting|missing, gates, metrics, url, freshness, backend, created_at, error}``
    (``refused`` = its gates refused it, ``failed`` = the backend failed, ``waiting`` = load or the media
    switch, retry later; ``empty`` adds ``attempts`` with their image URLs, ``mesh`` its ``attempts``, ``source`` its
    ``upscale``); ``freshness`` = ``{state, reason}`` computed here: ``stale`` with ``ITEM_IMAGE_CHANGED``
    when the shown source was made from another item image than the current one (``OLDER_SOURCE`` for the
    same image under an older source version), the insole also ``OLDER_ANALYSIS`` when its analysis version
    is not ``footwear_insole.INSOLE_VERSION``. ``fit`` = ``{status, pending True, detail FIT_PENDING, …}``:
    the chain ends after the insole until the fit lands.
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
    fit_status = fit_state(character_name, item_id, fsig, base[1]) if fsig else "missing"
    steps["fit"] = {"status": fit_status, "gates": {}, "metrics": {}, "url": None, "pending": True,
                    "detail": FIT_PENDING, "freshness": freshness(MISSING, FIT_PENDING)}

    insole = gs.read_record(folder / "insole.json")
    insole_view = ({k: insole.get(k) for k in ("version", "nominal", "gates", "overlay", "frame")}
                   if insole else None)
    image = get_item_image_path(item_id)
    image_stamp = _stamp(Path(image)) if image else None
    status = gs.status(character_name, item_id)
    queue = garments.queue_state(character_name, item_id)
    failed = status["failed"]
    if failed is None and not status["running_step"] and fsig:
        # After a restart: the persisted failure of the current fsig still holds the piece back.
        record = gs.chain_failure(character_name, item_id, fsig, base_model_sha=base[1] or "")
        if record is not None:
            failed = {"step": record.get("step"), "error": record.get("error"), "gates": None,
                      "failed_at": record.get("failed_at")}
    return {
        "item_id": item_id, "kind": KIND, "method": "shoe", "method_source": "world",
        "description": str(item.get("prompt_fragment") or ""), "fsig": fsig, "ssig": shown,
        "current_ssig": current, "steps": steps, "stale_reasons": stale,
        "running_step": status["running_step"], "started_at": status["started_at"],
        "queue_position": queue["queue_position"], "queue_running": queue["queue_running"], "failed": failed,
        "item_image_url": (_url(character_name, item_id, "image/source", image_stamp)
                           if image_stamp is not None else None),
        "mesh_url": steps["mesh"]["url"], "insole": insole_view,
        "preview_url": None, "served_fsig": None, "refit": None, "body": None, "body_id": None}
