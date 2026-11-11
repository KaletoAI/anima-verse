"""The per-item, world-scoped shoe source (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 4, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.2,
§ 5.3, § 5.6): one source per item, whoever wears it.

``ssig`` = md5[:12] over the item image's sha256, ``FOOTWEAR_SOURCE_VERSION``
and the seed of a forced Regenerate (0 = never regenerated; the seed lives in
``<world>/footwear/<item>/current.json``).

Folder ``<world>/footwear/<item>/<ssig>/`` (``source_dir``):

- ``source`` -> ``upscaled.png``: the item image flattened on white; below
  ``MIN_SIDE`` through the routed ``upscale`` occasion (a failed upscale other
  than load / the media switch falls back to Lanczos, like the garment
  cut-out), topped up with Lanczos to ``MIN_SIDE`` when still smaller.
- ``empty`` -> ``empty.png``: one empty shoe in side view — always the routed
  image edit ``EDIT_OCCASION`` with the upscaled image as reference (one image
  job per item; the side view is part of what the edit makes, an item image
  is never used as it is), up to ``EMPTY_ATTEMPTS`` times; every attempt keeps
  ``empty.try{n}.png/.json``.
- ``cutout`` -> ``cutout.png``: the BiRefNet-DIS cut-out of ``empty.png``
  (local, no hub job), cropped to a square around the shoe like the garment
  cut-out, Lanczos up to ``MIN_SIDE``.
- ``mesh`` -> ``raw.glb`` + ``prepared.glb``: the routed ``MESH_OCCASION``
  from the cut-out alone, decimated to ``TARGET_TRIS``; gates
  ``footwear_gates.MESH_GATES`` (``component_share``, ``mesh_iou``), two
  attempts like ``garment_mesh.generate``.
- ``insole`` -> ``insole.json``: ``footwear_insole.analyse`` of ``prepared.glb`` (CPU, no hub job),
  written whether or not it passes; gates ``footwear_insole.INSOLE_GATES`` (``insole_cover``,
  ``vamp_cover``, ``opening_share``) and ``SHAFT_GATES`` (``shaft_closed_share``, ``overknee``) — a refusal
  names ``INSOLE_REFUSED`` / ``SOLID_REFUSED`` / ``OPEN_REFUSED`` / ``OVERKNEE_REFUSED`` /
  ``SHAFT_OPEN_REFUSED``. A shaft the mesher capped (``shaft.cap_removed`` > 0, boots spec § 6.1) has the
  cap taken out of ``prepared.glb`` here (``footwear_insole.strip_cap``; ``raw.glb`` stays), the mesh is
  measured again without it and the count is kept in ``insole.json`` and the step record; the shaft's
  material is marked double-sided at the fit, not here.

``record.json`` = ``{steps: {step: {accepted, gates, backend, routing,
created_at, ...}}}``. A step that is not accepted names why in ``failure``:
``gate`` (its gates refused the result), ``backend`` (the backend failed —
``error`` is the first real cause from the exception chain, the backend's own
words, never the follow-up "no backend available … (cooling down)" of the
routing re-run) or ``load`` (busy / the media switch: retry later). A step whose record is accepted and whose output exists
is done and is not run again unless ``force``; running a step drops its own
and every later step's outputs first. The item image itself is only ever
read (anti-goal: it never changes).
"""
import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("footwear_source")

#: Bumped when the source steps change what they produce (part of ``ssig``).
#: 2 (Task 21 fix round, 2026-11-11): an ``empty`` step recorded under the
#: pre-5ffbe762 rule — the item image accepted as the empty shoe
#: (``skipped``, "already empty") — is invalid: the edit always runs since
#: that fix, and a source whose ``empty`` was skipped fed the mesher a 3/4
#: view (every mesh of it failed the side-silhouette gate). The new ssig
#: makes those folders unreachable; the GC removes them as usual.
FOOTWEAR_SOURCE_VERSION = 2
#: Long side below which the item image goes through the upscale occasion.
MIN_SIDE = 1024
#: Image-edit attempts of the ``empty`` step before it is refused.
EMPTY_ATTEMPTS = 2
#: Mesher attempts of the ``mesh`` step before it is refused (``garment_mesh.MAX_ATTEMPTS``).
MESH_ATTEMPTS = 2
EDIT_OCCASION = "footwear_empty"
MESH_OCCASION = "mesh_footwear"
USE_CASE = "footwear_source"
#: Decimation target of the prepared shoe mesh (the shoe's share of a figure).
#: 60 000 since the P3 acceptance (Task 21, 2026-11-11): measured on the real
#: Business Heels delivery (UniForge, 98 507 tris; insole_cover 0.864 raw),
#: the 30 000 target with the seam merge collapsed the cavity — the prepared
#: mesh read insole_cover 0.18 / 0.30 (two deliveries) and its side IoU
#: dropped 0.782 → 0.732 — while 60 000 keeps it (0.890, IoU 0.778); 30 000
#: without the merge: 0.570. A pump's thin shell needs the triangles.
TARGET_TRIS = 60000
#: What the mesher is asked for.
FACE_NUM = 100000
#: The edit instruction. The exclusion clause comes LAST: the composer's negation guard moves only that clause
#: (``foot``, ``leg``) into the negative prompt and keeps the instruction before it positive.
EMPTY_PROMPT = ("the same shoe, alone and empty, seen exactly from the side, toe pointing to the left, "
                "plain white background, no foot or leg")
ITEM_STEPS: Tuple[str, ...] = ("source", "empty", "cutout", "mesh", "insole")
#: Square crop around the shoe in the cut-out (``garment_images.CUTOUT_PAD``).
CUTOUT_PAD = 1.15
#: Alpha above which a cut-out pixel counts for the crop box (``garment_images.CUTOUT_ALPHA_MIN``).
CUTOUT_ALPHA_MIN = 16

#: The outputs of each step; the first one decides whether the step is done.
_STEP_FILES: Dict[str, Tuple[str, ...]] = {
    "source": ("upscaled.png",),
    "empty": ("empty.png",),
    "cutout": ("cutout.png",),
    "mesh": ("prepared.glb", "raw.glb"),
    "insole": ("insole.json",),
}
_SSIG_RE = re.compile(r"^[0-9a-f]{12}$")
_RECORD = "record.json"
_CURRENT = "current.json"


#: ``failure`` of a step record that is not accepted.
GATE, BACKEND, LOAD = "gate", "backend", "load"


class StepRefused(RuntimeError):
    """A step's gates refused its result (or an attempt failed outright);
    ``gates`` and ``failure`` (``GATE`` / ``BACKEND`` / ``LOAD``) ride along
    into ``run_source``'s answer."""

    def __init__(self, error: str, gates: Dict[str, Any], failure: str = GATE):
        super().__init__(error)
        self.gates = gates
        self.failure = failure


def _chain(e: BaseException) -> List[BaseException]:
    """``e`` and its causes, outermost first (``__cause__``, else the context
    unless suppressed)."""
    out: List[BaseException] = []
    cur: Optional[BaseException] = e
    while cur is not None and all(cur is not seen for seen in out):
        out.append(cur)
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    return out


def failure_of(e: BaseException) -> Tuple[str, str]:
    """``(kind, text)`` of a failed attempt. ``kind`` = ``LOAD`` for load or
    the media switch anywhere in the chain (``BackendBusyError`` /
    ``MediaGenerationDisabled``: retry later), else ``BACKEND``. ``text`` = the
    first ``BackendFailedError`` of the chain — the backend's own words
    ("<backend>: <cause>") — so a routing re-run that ends in ``NoRouteError``
    ("… (cooling down)") reports what really failed; without one the
    exception's own text."""
    from app.imagegen.base import BackendBusyError, BackendFailedError, MediaGenerationDisabled
    chain = _chain(e)
    kind = LOAD if any(isinstance(x, (BackendBusyError, MediaGenerationDisabled)) for x in chain) else BACKEND
    failed = next((x for x in chain if isinstance(x, BackendFailedError)), None)
    text = str(failed if failed is not None else e) or type(e).__name__
    return kind, text


# --- signature --------------------------------------------------------------------------------------------------------

def _md5(payload: Dict[str, Any]) -> str:
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return digest.hexdigest()[:12]


def _item_image(item_id: str) -> Optional[Path]:
    from app.models.inventory import get_item_image_path
    path = get_item_image_path(item_id)
    return Path(path) if path else None


def item_image_sha256(item_id: str) -> str:
    """sha256 of the item's image file, "" without one."""
    from app.core.base_body import file_sha256
    return file_sha256(_item_image(item_id))


def ssig_for(item_id: str, seed: int) -> str:
    """md5[:12] over ``{image, version, seed}`` (module docstring)."""
    return _md5({"image": item_image_sha256(item_id), "version": FOOTWEAR_SOURCE_VERSION, "seed": int(seed)})


# --- store ------------------------------------------------------------------------------------------------------------

def root() -> Path:
    """``<world>/footwear``."""
    from app.core import paths
    return paths.get_storage_dir() / "footwear"


def item_dir(item_id: str) -> Path:
    """``<world>/footwear/<item>``; ValueError for an id that is no safe item
    id or would leave ``root()``. Never creates the folder."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid:
        raise ValueError(f"invalid item id {str(item_id)[:80]!r}")
    base = root().resolve()
    path = (base / iid).resolve()
    if path.parent != base:
        raise ValueError(f"item folder outside the footwear store: {iid!r}")
    return root() / iid


def current(item_id: str) -> Dict[str, Any]:
    """``{ssig, seed}`` of the item's current source: the seed from
    ``current.json`` (0 without one), the ssig computed from it and the
    item image as it is NOW (a new item image is a new source)."""
    from app.core.garment_store import read_record
    raw = read_record(item_dir(item_id) / _CURRENT).get("seed", 0)
    try:
        seed = max(0, int(raw))
    except (TypeError, ValueError):
        seed = 0
    return {"ssig": ssig_for(item_id, seed), "seed": seed}


def current_ssig(item_id: str) -> str:
    return current(item_id)["ssig"]


def source_dir(item_id: str, ssig: str) -> Path:
    if not _SSIG_RE.match(str(ssig or "")):
        raise ValueError(f"invalid shoe source signature {str(ssig)[:40]!r}")
    return item_dir(item_id) / ssig


def _read(d: Path) -> Dict[str, Any]:
    from app.core.garment_store import read_record
    rec = read_record(d / _RECORD)
    if not isinstance(rec.get("steps"), dict):
        rec["steps"] = {}
    return rec


def step_record(item_id: str, ssig: str, step: str) -> Dict[str, Any]:
    """The record entry of ``step`` under ``ssig``, {} without one."""
    entry = _read(source_dir(item_id, ssig))["steps"].get(step)
    return entry if isinstance(entry, dict) else {}


def refused_step(item_id: str, ssig: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The first item step of the CURRENT source (``ssig`` None = ``current_ssig``)
    whose last run was refused or failed — ``{ssig, step, error, failure}`` —
    or None. ``LOAD`` failures (busy / the media switch) do not count: they
    retry. What an AUTOMATIC trigger (equip, ``resolve_mesh_items``, any
    ``garments.run_queued`` / ``enqueue_garment`` path) honours for every
    wearer alike — the source is one per item — so a refused mesh is never
    meshed again until an explicit Run / Regenerate from the Wardrobe
    (``garments.cached_failure``; Task 21 fix round: the clone re-spent two
    mesher jobs on a refused cut-out through a run the equip had queued)."""
    try:
        sig = ssig or current_ssig(item_id)
        steps = _read(source_dir(item_id, sig))["steps"]
    except (ValueError, OSError):
        return None
    for step in ITEM_STEPS:
        entry = steps.get(step)
        if not isinstance(entry, dict) or entry.get("accepted") is not False:
            continue
        failure = str(entry.get("failure") or GATE)
        if failure == LOAD:
            continue
        error = str(entry.get("error") or "")
        if not error:
            reasons = (entry.get("gates") or {}).get("reasons") if isinstance(entry.get("gates"), dict) else None
            error = "; ".join(str(r) for r in reasons) if reasons else f"{step} refused"
        return {"ssig": sig, "step": step, "error": error, "failure": failure}
    return None


def step_done(item_id: str, ssig: str, step: str) -> bool:
    """Accepted record AND its output on disk."""
    if step not in _STEP_FILES:
        return False
    return (step_record(item_id, ssig, step).get("accepted") is True
            and (source_dir(item_id, ssig) / _STEP_FILES[step][0]).is_file())


def _set_step(d: Path, step: str, entry: Dict[str, Any]) -> None:
    from app.core.garment_store import write_record
    rec = _read(d)
    rec["steps"][step] = entry
    write_record(d / _RECORD, rec)


def _drop_from(d: Path, step: str) -> None:
    """Remove ``step`` and every later step: outputs, edit tries, records."""
    from app.core.garment_store import write_record
    later = ITEM_STEPS[ITEM_STEPS.index(step):]
    for s in later:
        for name in _STEP_FILES[s]:
            (d / name).unlink(missing_ok=True)
        if s == "empty" and d.is_dir():
            for p in d.glob("empty.try*"):
                p.unlink(missing_ok=True)
    rec = _read(d)
    if any(s in rec["steps"] for s in later):
        for s in later:
            rec["steps"].pop(s, None)
        write_record(d / _RECORD, rec)


def _entry(*, accepted: bool, gates: Dict[str, Any], backend: str = "", routing: Optional[Dict[str, Any]] = None,
           **extra: Any) -> Dict[str, Any]:
    from app.core.timeutils import utc_now_iso
    return {"accepted": bool(accepted), "gates": gates, "backend": backend or "", "routing": routing or {},
            "created_at": utc_now_iso(), **extra}


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# --- images -----------------------------------------------------------------------------------------------------------

def _flatten(im):
    """RGB on white (item images are RGBA with a transparent black background)."""
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        out = Image.new("RGB", rgba.size, (255, 255, 255))
        out.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
        return out
    return im.convert("RGB")


def _lanczos_to(im, side: int):
    """``im`` scaled so its long side is ``side`` (aspect kept)."""
    from PIL import Image
    scale = side / max(im.size)
    return im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.Resampling.LANCZOS)


def _matte(data: bytes):
    """The BiRefNet-DIS matte of ``data`` as a uint8 H x W array at the image's size."""
    import numpy as np
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    with Image.open(io.BytesIO(data)) as im:
        size = im.size
    with Image.open(io.BytesIO(run_rembg(data, MESH_INPUT_REMBG_MODEL, only_mask=True))) as m:
        mask = m.convert("L")
        if mask.size != size:
            mask = mask.resize(size, Image.Resampling.BILINEAR)
        return np.asarray(mask, dtype=np.uint8)


# --- steps ------------------------------------------------------------------------------------------------------------

def _step_source(iid: str, ssig: str, seed: int, d: Path) -> None:
    from PIL import Image
    from app.core.base_body import file_sha256
    from app.imagegen.base import BackendBusyError, MediaGenerationDisabled
    path = _item_image(iid)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"item {iid!r} has no image")
    data = path.read_bytes()            # read only: the item image never changes
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        image = _flatten(im)
    size = list(image.size)
    backend, routing, extra = "", {}, {}
    if max(image.size) >= MIN_SIDE:
        upscale: Dict[str, Any] = {"status": "not_needed"}
    else:
        from app.imagegen.service import get_image_service
        try:
            result = get_image_service().upscale_image(_png(image), character_name="")
        except (BackendBusyError, MediaGenerationDisabled):
            raise                         # load / switched off: the step runs again later
        except Exception as e:  # noqa: BLE001 — Lanczos alone is the documented fallback (garment cut-out)
            reason = failure_of(e)[1]
            logger.warning("Shoe source %s: upscale failed, Lanczos only: %s", iid, reason)
            upscale = {"status": "lanczos", "reason": reason}
        else:
            with Image.open(io.BytesIO(result["bytes"])) as up:
                image = up.convert("RGB")
            upscale = {k: v for k, v in result.items() if k not in ("bytes", "routing", "fallback_from")}
            backend, routing = str(result.get("backend") or ""), result.get("routing") or {}
            if result.get("fallback_from"):
                extra["fallback_from"] = result["fallback_from"]
        if max(image.size) < MIN_SIDE:
            image = _lanczos_to(image, MIN_SIDE)
            upscale["topped_up_to"] = list(image.size)
    _write_bytes(d / "upscaled.png", _png(image))
    _set_step(d, "source", _entry(accepted=True, gates={}, backend=backend, routing=routing, upscale=upscale,
                                  item_sha256=file_sha256(path), item_size=size, size=list(image.size), **extra))
    logger.info("Shoe source %s/%s: source %s -> %s (%s)", iid, ssig, size, list(image.size), upscale["status"])


def _edit(iid: str, upscaled: Path, seed: int, attempt: int):
    """One routed edit of the upscaled item image -> ``(png bytes, backend, route)``."""
    from app.core.prompt_compose import compose
    from app.imagegen import routing as _routing
    from app.imagegen.service import get_image_service
    svc = get_image_service()

    def _render(b):
        composed = compose(use_case=USE_CASE, subject=EMPTY_PROMPT, backend=b)
        for warning in composed.warnings:
            logger.info("Prompt composer (%s): %s", USE_CASE, warning)
        params: Dict[str, Any] = {"seed": seed * 1000 + attempt,
                                  "reference_images": {"input_reference_image_1": str(upscaled)}}
        log_meta = {"agent_name": f"Footwear {iid}", "original_prompt": EMPTY_PROMPT, "auto_enhance": False,
                    "compose": composed.meta}

        def _op(bb):
            # Every backend through its GPU channel: never two generations on one backend at once.
            return svc.run_on_backend_channel(
                bb, lambda: bb.generate(composed.prompt, composed.negative, params, log_meta=log_meta),
                task_type="footwear_empty", agent_name="system", label=f"Empty shoe: {iid}")
        return svc.run_on_backend(b, op=_op)

    (images, used), route = _routing.run_routed(EDIT_OCCASION, _render, has_ref=True, pool=svc.pool)
    if not isinstance(images, (list, tuple)) or not images or not isinstance(images[0], (bytes, bytearray)):
        raise RuntimeError("the empty-shoe edit delivered no image")
    from PIL import Image
    with Image.open(io.BytesIO(bytes(images[0]))) as im:
        im.load()
        data = _png(_flatten(im))
    return data, used, route


def _step_empty(iid: str, ssig: str, seed: int, d: Path) -> None:
    from app.core.footwear_gates import empty_gate
    from app.core.garment_store import write_record
    from app.imagegen.routing import route_meta
    upscaled = d / "upscaled.png"
    if not upscaled.is_file():
        raise FileNotFoundError("the upscaled item image is missing — run the source step first")
    item_matte = _matte(upscaled.read_bytes())

    attempts: List[Dict[str, Any]] = []
    for attempt in range(1, EMPTY_ATTEMPTS + 1):
        try:
            data, used, route = _edit(iid, upscaled, seed, attempt)
        except Exception as e:  # noqa: BLE001 — recorded with the attempts before it, the step fails
            failure, error = failure_of(e)
            attempts.append({"attempt": attempt, "ok": False, "failure": failure, "error": error})
            _set_step(d, "empty", _entry(accepted=False, gates=attempts[-2]["gates"] if len(attempts) > 1 else {},
                                         attempts=attempts, failure=failure, error=error))
            raise StepRefused(f"empty-shoe edit failed: {error}", {"attempts": attempts}, failure) from e
        try_png = d / f"empty.try{attempt}.png"
        _write_bytes(try_png, data)
        gates = empty_gate(_matte(data), item_matte=item_matte)
        entry = {"attempt": attempt, "ok": bool(gates["ok"]), "gates": gates, "seed": seed * 1000 + attempt,
                 "backend": getattr(used, "name", ""), **route_meta(route)}
        write_record(try_png.with_suffix(".json"), entry)
        attempts.append(entry)
        logger.info("Shoe source %s/%s: empty attempt %d %s %s", iid, ssig, attempt,
                    "accepted" if gates["ok"] else "refused", "; ".join(gates["reasons"]))
        if gates["ok"]:
            shutil.copyfile(try_png, d / "empty.png")
            _set_step(d, "empty", _entry(accepted=True, gates=gates, backend=entry["backend"],
                                         routing=entry.get("routing"), attempts=attempts,
                                         **({"fallback_from": entry["fallback_from"]}
                                            if entry.get("fallback_from") else {})))
            return
    last = attempts[-1]
    _set_step(d, "empty", _entry(accepted=False, gates=last["gates"], backend=last["backend"],
                                 routing=last.get("routing"), attempts=attempts, failure=GATE))
    reasons = "; ".join(f"attempt {a['attempt']}: " + ", ".join(a["gates"]["reasons"]) for a in attempts)
    raise StepRefused(f"empty shoe refused after {len(attempts)} attempts ({reasons})", last["gates"])


def _step_cutout(iid: str, ssig: str, seed: int, d: Path) -> None:
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    empty = d / "empty.png"
    if not empty.is_file():
        raise FileNotFoundError("the empty-shoe image is missing — run the empty step first")
    with Image.open(io.BytesIO(run_rembg(empty.read_bytes(), MESH_INPUT_REMBG_MODEL))) as im:
        cut = im.convert("RGBA")
    box = cut.getchannel("A").point(lambda v: 255 if v > CUTOUT_ALPHA_MIN else 0).getbbox()
    if box is None:
        raise ValueError("no shoe found in the empty-shoe image")
    x0, y0, x1, y1 = box
    side = int(CUTOUT_PAD * max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    out = cut.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side))
    if side < MIN_SIDE:
        out = out.resize((MIN_SIDE, MIN_SIDE), Image.Resampling.LANCZOS)
    _write_bytes(d / "cutout.png", _png(out))
    _set_step(d, "cutout", _entry(accepted=True, gates={}, model=MESH_INPUT_REMBG_MODEL, bbox=[x0, y0, x1, y1],
                                  side=side, size=list(out.size)))


def _mesh_attempt(iid: str, cutout: Path, raw: Path, candidate: Path, alpha, attempt: int) -> Dict[str, Any]:
    """One fresh mesher call + decimation + gates; the attempt's record. Raises when
    the generation or the decimation fails."""
    from app.imagegen.service import get_image_service
    res = get_image_service().generate_mesh(
        source_image_path=str(cutout), output_path=str(raw), occasion=MESH_OCCASION,
        mesh_name=f"footwear-{iid}", face_num=FACE_NUM, material="dielectric", alpha="opaque")
    if not res.get("ok"):
        raise RuntimeError(f"shoe mesh generation failed: {res.get('error') or 'unknown error'}")
    delivered = Path(str(res.get("path") or ""))
    if delivered.suffix.lower() != ".glb" or not delivered.is_file():
        raise RuntimeError(f"shoe mesh generation delivered no GLB ({delivered.name or 'nothing'})")
    if delivered != raw:
        os.replace(delivered, raw)
    return _prepare_mesh(raw, candidate, alpha, attempt, res)


def _prepare_mesh(raw: Path, candidate: Path, alpha, attempt: int, res: Dict[str, Any]) -> Dict[str, Any]:
    """Decimation + gates of a delivered raw shoe mesh — the half of an attempt after the generation, shared
    by a fresh attempt and a collected job (``collect_mesh_job``). Raises when the decimation fails."""
    from app.blender import refine
    from app.core import glb_mesh
    from app.core.footwear_gates import MESH_GATES, check_gates, component_shares, side_silhouette, silhouette_iou
    dec = refine.decimate_to(raw, TARGET_TRIS, candidate, merge_vertices=True)
    if not dec.get("ok"):
        raise RuntimeError(f"shoe mesh decimation failed: {dec.get('error') or 'unknown error'}")
    positions, faces = glb_mesh.static_arrays(candidate.read_bytes())[:2]
    largest, enclosed = component_shares(positions, faces)
    iou = silhouette_iou(side_silhouette(positions, faces), alpha >= 128)
    ok, reasons = check_gates({"component_share": enclosed, "mesh_iou": iou}, MESH_GATES)
    return {"attempt": attempt, "ok": ok,
            "gates": {"ok": ok, "reasons": reasons, "component_share": enclosed, "largest_share": largest,
                      "mesh_iou": iou},
            "backend": res.get("backend", ""), "routing": res.get("routing") or {},
            **({"fallback_from": res["fallback_from"]} if res.get("fallback_from") else {}),
            "tris_raw": dec.get("tris_before"), "tris_prepared": dec.get("tris"), "ratio": dec.get("ratio")}


def _cutout_alpha(cutout: Path):
    """The cut-out's alpha as a uint8 array (the mesh_iou gate's reference)."""
    import numpy as np
    from PIL import Image
    with Image.open(cutout) as im:
        return np.asarray(im.convert("RGBA").getchannel("A"), dtype=np.uint8)


def _mesh_record(last: Dict[str, Any], attempts: List[Dict[str, Any]], accepted: bool, **extra: Any) -> Dict[str, Any]:
    """The ``mesh`` step record; the numbers are those of ``last`` (a gated attempt, or {})."""
    return _entry(accepted=accepted, gates=last.get("gates") or {}, backend=last.get("backend", ""),
                  routing=last.get("routing"), attempts=attempts, target_tris=TARGET_TRIS, face_num=FACE_NUM,
                  tris_raw=last.get("tris_raw"), tris_prepared=last.get("tris_prepared"),
                  **({"fallback_from": last["fallback_from"]} if last.get("fallback_from") else {}), **extra)


def _step_mesh(iid: str, ssig: str, seed: int, d: Path) -> None:
    cutout = d / "cutout.png"
    if not cutout.is_file():
        raise FileNotFoundError("the shoe cut-out is missing — run the cutout step first")
    alpha = _cutout_alpha(cutout)
    raw, prepared = d / "raw.glb", d / "prepared.glb"
    # Decimated here first and renamed onto ``prepared`` only once accepted.
    candidate = d / ".prepared.candidate.glb"
    attempts: List[Dict[str, Any]] = []

    def _record(last: Dict[str, Any], accepted: bool, **extra: Any) -> Dict[str, Any]:
        return _mesh_record(last, attempts, accepted, **extra)
    try:
        for attempt in range(1, MESH_ATTEMPTS + 1):
            try:
                entry = _mesh_attempt(iid, cutout, raw, candidate, alpha, attempt)
            except Exception as e:  # noqa: BLE001 — recorded with the attempts before it, the step fails
                failure, error = failure_of(e)
                attempts.append({"attempt": attempt, "ok": False, "failure": failure, "error": error})
                gated = [a for a in attempts if "gates" in a]
                _set_step(d, "mesh", _record(gated[-1] if gated else {}, False, failure=failure, error=error))
                raise StepRefused(f"shoe mesh failed: {error}", {"attempts": attempts}, failure) from e
            attempts.append(entry)
            logger.info("Shoe source %s/%s: mesh attempt %d %s (component %.4f, iou %.4f)", iid, ssig, attempt,
                        "accepted" if entry["ok"] else "refused", entry["gates"]["component_share"],
                        entry["gates"]["mesh_iou"])
            if entry["ok"]:
                break
        last = attempts[-1]
        if last["ok"]:
            os.replace(candidate, prepared)
            _set_step(d, "mesh", _record(last, True))
            return
        _set_step(d, "mesh", _record(last, False, failure=GATE))
        reasons = "; ".join(f"attempt {a['attempt']}: " + ", ".join(a["gates"]["reasons"]) for a in attempts)
        raise StepRefused(f"shoe mesh refused after {len(attempts)} attempts ({reasons})", last["gates"])
    finally:
        candidate.unlink(missing_ok=True)


def _step_insole(iid: str, ssig: str, seed: int, d: Path) -> None:
    from app.core import footwear_insole
    from app.core.garment_store import write_record
    prepared = d / "prepared.glb"
    if not prepared.is_file():
        raise FileNotFoundError("the prepared shoe mesh is missing — run the mesh step first")
    import numpy as np
    from app.core import glb_mesh
    positions, faces, uvs, image, mime, material = glb_mesh.static_arrays(prepared.read_bytes())
    res = footwear_insole.analyse_arrays(positions, faces)
    cap = footwear_insole.cap_faces(positions, faces, res)
    removed = int(cap.sum())
    if removed:
        # A mesher cap on the shaft: prepared.glb goes on without it (the fit and the viewer read this file;
        # raw.glb keeps the delivery), measured again as it is served, the count carried over.
        F = np.asarray(faces, np.int64)
        used, inverse = np.unique(F[~cap].reshape(-1), return_inverse=True)
        P2, F2 = np.asarray(positions, np.float64)[used], inverse.reshape(-1, 3)
        _write_bytes(prepared, glb_mesh.static_glb(P2, F2, np.asarray(uvs, np.float64)[used], image=image,
                                                   mime=mime, material=material))
        res = footwear_insole.analyse_arrays(P2, F2)
        res["shaft"]["cap_removed"] = removed
        logger.info("Shoe source %s/%s: shaft cap of %d faces removed from prepared.glb", iid, ssig, removed)
    gates = res["gates"]
    # Written refused too: the Wardrobe row shows what the analysis found.
    write_record(d / "insole.json", res)
    shaft = res.get("shaft") or {}
    _set_step(d, "insole", _entry(accepted=bool(gates["ok"]), gates=gates, version=footwear_insole.INSOLE_VERSION,
                                  nominal=res["nominal"], shaft_class=shaft.get("class"),
                                  cap_removed=int(shaft.get("cap_removed") or 0),
                                  **({} if gates["ok"] else {"failure": GATE})))
    logger.info("Shoe source %s/%s: insole %s (cover %.3f, vamp %.3f, shaft %s)", iid, ssig,
                "accepted" if gates["ok"] else "refused", gates["insole_cover"], gates["vamp_cover"],
                shaft.get("class"))
    if not gates["ok"]:
        raise StepRefused(f"{gates.get('refusal') or 'insole refused'} ({'; '.join(gates['reasons'])})", gates)


#: The steps this module runs, in order.
_RUNNERS: Dict[str, Callable[[str, str, int, Path], None]] = {
    "source": _step_source, "empty": _step_empty, "cutout": _step_cutout, "mesh": _step_mesh,
    "insole": _step_insole,
}


# --- public -----------------------------------------------------------------------------------------------------------

def _lock(iid: str):
    from app.core.keyed_lock import keyed_lock
    return keyed_lock("footwear_source", iid)


def run_source(item_id: str, *, steps: Optional[List[str]] = None, force: bool = False,
               on_step: Callable[[str], None] = lambda s: None) -> Dict[str, Any]:
    """Run the item's source steps (all of them, or ``steps``) under the item
    lock; a done step is skipped unless ``force``. ``on_step(step)`` is called
    before a step runs. -> ``{ok True, ssig, ran}`` or ``{ok False, ssig,
    step, error, gates, error_type, failure, ran}`` (``failure`` = ``GATE`` /
    ``BACKEND`` / ``LOAD``; a step whose input is missing fails the same way,
    naming the step to run first)."""
    iid = item_dir(item_id).name
    wanted = list(_RUNNERS) if steps is None else list(steps)
    unknown = [s for s in wanted if s not in _RUNNERS]
    if unknown:
        raise ValueError(f"unknown shoe source step(s): {unknown}")
    with _lock(iid):
        cur = current(iid)
        ssig, seed = cur["ssig"], cur["seed"]
        d = source_dir(iid, ssig)
        ran: List[str] = []
        for step in _RUNNERS:
            if step not in wanted or (not force and step_done(iid, ssig, step)):
                continue
            on_step(step)
            d.mkdir(parents=True, exist_ok=True)
            _drop_from(d, step)
            try:
                _RUNNERS[step](iid, ssig, seed, d)
            except Exception as e:  # noqa: BLE001 — the caller gets the step, the error and the gates
                logger.warning("Shoe source %s/%s: step %s failed: %s", iid, ssig, step, e)
                cause = e.__cause__ if isinstance(e, StepRefused) and e.__cause__ is not None else e
                failure, error = (e.failure, str(e)) if isinstance(e, StepRefused) else failure_of(e)
                return {"ok": False, "ssig": ssig, "step": step, "error": error or type(e).__name__,
                        "gates": getattr(e, "gates", {}), "error_type": type(cause).__name__, "failure": failure,
                        "ran": ran}
            ran.append(step)
        return {"ok": True, "ssig": ssig, "ran": ran}


def regenerate(item_id: str, step: str) -> str:
    """Start a new source from ``step`` on: ``current.json`` gets ``seed + 1``,
    the accepted outputs of the steps BEFORE ``step`` are copied from the old
    ssig folder (records marked ``copied_from``), the new ssig is returned.
    Copying stops at the first step that is not done."""
    from app.core.garment_store import write_record
    if step not in ITEM_STEPS:
        raise ValueError(f"unknown shoe source step {step!r}")
    iid = item_dir(item_id).name
    with _lock(iid):
        cur = current(iid)
        old, seed = cur["ssig"], cur["seed"] + 1
        new = ssig_for(iid, seed)
        od, nd = source_dir(iid, old), source_dir(iid, new)
        nd.mkdir(parents=True, exist_ok=True)
        _drop_from(nd, ITEM_STEPS[0])
        for s in ITEM_STEPS[:ITEM_STEPS.index(step)]:
            if not step_done(iid, old, s):
                break
            for name in _STEP_FILES[s]:
                if (od / name).is_file():
                    _write_bytes(nd / name, (od / name).read_bytes())
            _set_step(nd, s, {**step_record(iid, old, s), "copied_from": old})
        write_record(item_dir(iid) / _CURRENT, {"ssig": new, "seed": seed})
        logger.info("Shoe source %s: regenerate from %s, %s -> %s", iid, step, old, new)
        return new


#: ``collect_mesh_job``'s answer when the step itself fails (decimation) — the job was fine.
STEP_FAILED = "step_failed"


class SourceBusy(RuntimeError):
    """A step of the item's shoe source is running (its item lock is held): a collected job would race it."""


def collect_mesh_job(item_id: str, job_id: str) -> Dict[str, Any]:
    """Collect a FINISHED gateway ``mesh_footwear`` job by its id as the ``mesh`` step of the item's CURRENT
    source — the way back to a mesh step whose run outlived our own poll (timeout, server restart).

    Under the item lock, taken WITHOUT waiting: ``SourceBusy`` while any step of the source runs. Needs the
    accepted cut-out (``FileNotFoundError`` otherwise — the mesh_iou gate reads it).
    ``get_image_service().fetch_mesh_job`` (rig ``none``) downloads into a staging folder, where the SAME
    decimation + gates as a fresh attempt run (``_prepare_mesh``). Accepted: the mesh step and every later one
    are dropped (like a step run), then ``raw.glb`` + ``prepared.glb`` and the same record (one attempt) plus
    ``collected_job`` = the job's full id; the insole (CPU) runs on the next run.

    A refused or failed fetch NEVER touches an accepted mesh or the insole after it (a wrong pasted id must not
    destroy a good shoe): nothing is written, the answer carries ``kept: True``. Only without an accepted mesh
    is it recorded like the step's own refusal / failure.

    Returns ``{status: "accepted" | "refused", ssig, job_id, record?, reasons?, gates?, error?, kept?}``,
    ``{status: STEP_FAILED, ssig, job_id, error, failure, kept}`` when the decimation fails, else the fetch's
    own answer with nothing written (``queued`` / ``running`` + ``progress``, or ``unknown`` / ``forbidden`` /
    ``failed`` / ``rig_mismatch`` / ``error`` + ``error``). Blocking (download + Blender)."""
    import tempfile
    from app.imagegen.service import get_image_service
    iid = item_dir(item_id).name
    lock = _lock(iid)
    if not lock.acquire(blocking=False):
        raise SourceBusy("A step of this shoe source is running — fetch the job once it has ended")
    try:
        ssig = current(iid)["ssig"]
        d = source_dir(iid, ssig)
        cutout = d / "cutout.png"
        if not step_done(iid, ssig, "cutout"):
            raise FileNotFoundError("the shoe cut-out is missing — run the cutout step first")
        alpha = _cutout_alpha(cutout)
        staging = Path(tempfile.mkdtemp(prefix=".fetch-", dir=d))
        candidate = staging / "candidate.glb"
        try:
            res = get_image_service().fetch_mesh_job(job_id, str(staging / "raw.glb"), rig="none")
            if res.get("status") != "stored":
                return res
            full = str(res.get("job_id") or job_id)
            delivered = Path(str(res.get("path") or ""))
            if delivered.suffix.lower() != ".glb" or not delivered.is_file():
                return {"status": "error", "ssig": ssig, "job_id": full,
                        "error": f"job {full} delivered no GLB ({delivered.name or 'nothing'})"}
            kept = step_done(iid, ssig, "mesh")
            try:
                entry = _prepare_mesh(delivered, candidate, alpha, 1,
                                      {"backend": res.get("backend", ""), "routing": {}})
            except Exception as e:  # noqa: BLE001 — the step failed, the job was fine
                failure, error = failure_of(e)
                attempts = [{"attempt": 1, "ok": False, "failure": failure, "error": error}]
                logger.warning("Shoe source %s/%s: collected job %s failed: %s", iid, ssig, full, error)
                if not kept:
                    _drop_from(d, "mesh")
                    _set_step(d, "mesh", _mesh_record({}, attempts, False, failure=failure, error=error,
                                                      collected_job=full))
                return {"status": STEP_FAILED, "ssig": ssig, "job_id": full, "error": error, "failure": failure,
                        "gates": {"attempts": attempts}, "kept": kept}
            entry["collected_job"] = full
            logger.info("Shoe source %s/%s: collected job %s %s (component %.4f, iou %.4f)", iid, ssig, full,
                        "accepted" if entry["ok"] else ("refused, accepted mesh kept" if kept else "refused"),
                        entry["gates"]["component_share"], entry["gates"]["mesh_iou"])
            if entry["ok"]:
                _drop_from(d, "mesh")
                os.replace(delivered, d / "raw.glb")
                os.replace(candidate, d / "prepared.glb")
                record = _mesh_record(entry, [entry], True, collected_job=full)
                _set_step(d, "mesh", record)
                return {"status": "accepted", "ssig": ssig, "job_id": full, "record": record}
            refused = {"status": "refused", "ssig": ssig, "job_id": full, "gates": entry["gates"],
                       "reasons": list(entry["gates"]["reasons"]), "kept": kept,
                       "error": f"shoe mesh refused ({', '.join(entry['gates']['reasons'])})"}
            if kept:
                return refused  # the accepted mesh and its insole stay exactly as they are
            _drop_from(d, "mesh")
            os.replace(delivered, d / "raw.glb")
            record = _mesh_record(entry, [entry], False, failure=GATE, collected_job=full)
            _set_step(d, "mesh", record)
            return {**refused, "record": record}
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    finally:
        lock.release()


# --- GC -------------------------------------------------------------------------------------------------------------

def collect(*, dry_run: bool = False) -> Dict[str, Any]:
    """GC of the world shoe sources ``<world>/footwear/`` (plan 2026-11-10-footwear-rigid-shoes Task 26). Roots:
    every EXISTING footwear item (``garment_set.garment_kind_of``) keeps its current ssig folder, and every ssig a
    kept footwear fit record names (``record.ssig`` of an accepted fit — on the base or an outfit body — of any
    character, dormant and pooled ones included) stays too; everything else under the root goes: the ssig folders
    nobody names, the whole folder of an item that no longer exists or is no footwear, and the dot entries of
    aborted writes (``.<name>.tmp``, ``.staging``) older than ``artefact_graph.TEMP_GRACE_S``. An item whose source
    chain runs (its ``footwear_source`` lock held) is left for the next sweep. ``{dry_run, roots, removed: [paths],
    deleted_files, freed_bytes, skipped: [item ids]}``; with ``dry_run`` nothing is deleted. Never raises on a
    single entry."""
    import shutil
    import time
    from app.core import garment_set, garment_store
    from app.core.artefact_graph import TEMP_GRACE_S
    from app.models.character import list_available_characters
    from app.models.inventory import get_item, list_items
    report: Dict[str, Any] = {"dry_run": dry_run, "roots": 0, "removed": [], "deleted_files": 0, "freed_bytes": 0,
                              "skipped": []}
    base = root()
    if not base.is_dir():
        return report
    keep: Dict[str, set] = {}
    for item in list_items():
        iid = str(item.get("id") or "")
        if iid and garment_set.garment_kind_of(item) == garment_set.FOOTWEAR:
            try:
                keep.setdefault(iid, set()).add(current_ssig(iid))
            except ValueError:
                continue
    for name in list_available_characters(include_pooled=True, include_dormant=True):
        try:
            groups = garment_store.stored_groups(name)
        except Exception:  # noqa: BLE001 — one character never blocks the sweep
            logger.exception("Footwear source GC: garments of %s unreadable", name)
            continue
        for (iid, _fsig), files in groups.items():
            for path in files:
                # the fit records: ``garments/<item>_<fsig>.json`` and ``bodies/<body>/<item>_<fsig>.json``
                in_root = path.parent == garment_store._root(name)
                if path.suffix != ".json" or not (in_root or garment_store.body_of(path)):
                    continue
                record = garment_store.read_record(path)
                if record.get("accepted") is True and record.get("kind") == garment_set.FOOTWEAR and record.get("ssig"):
                    keep.setdefault(iid, set()).add(str(record["ssig"]))
    report["roots"] = sum(len(v) for v in keep.values())
    now = time.time()

    def remove(path: Path) -> None:
        report["removed"].append(str(path))
        if dry_run:
            return
        files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
        size = sum(p.stat().st_size for p in files if p.exists())
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        report["deleted_files"] += len(files)
        report["freed_bytes"] += size

    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        iid = folder.name
        if iid not in keep or get_item(iid) is None:
            try:
                remove(folder)
            except OSError as e:
                logger.warning("Footwear source GC: %s not removed: %s", folder, e)
            continue
        lock = _lock(iid)
        if not lock.acquire(blocking=False):
            report["skipped"].append(iid)
            continue
        try:
            for entry in sorted(folder.iterdir()):
                name = entry.name
                if name.startswith("."):
                    try:
                        newest = max([entry.stat().st_mtime] + [p.stat().st_mtime for p in entry.rglob("*")]) \
                            if entry.is_dir() else entry.stat().st_mtime
                    except OSError:
                        continue
                    if now - newest >= TEMP_GRACE_S:
                        remove(entry)
                    continue
                if entry.is_dir() and _SSIG_RE.match(name) and name not in keep[iid]:
                    remove(entry)
        except OSError as e:
            logger.warning("Footwear source GC: %s not walked: %s", folder, e)
        finally:
            lock.release()
    if report["removed"] and not dry_run:
        logger.info("Footwear source GC: %d entr%s removed (%d file(s), %.1f MB)", len(report["removed"]),
                    "y" if len(report["removed"]) == 1 else "ies", report["deleted_files"],
                    report["freed_bytes"] / 1e6)
    return report
