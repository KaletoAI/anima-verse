"""The image steps of a garment chain: gated edits and the cut-out
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R4–R7,
Task 4).

``run_edit_step`` renders one edit step of one view — up to two attempts
(R5: each a fresh backend call with the backend's own seed), every attempt
gated by the garment kind's gate (``garment_gates``). The accepted attempt
is copied to the step's final file; two refusals raise ``GateRefused`` with
both gate records. The edit is an image EDIT of its source on the routed
``garment_view`` occasion: the base view (step ``haired``) or the accepted
image of the step before (``ghost``), use case ``garment_edit`` (empty style,
the spike negative), no character LoRAs, and published unprocessed
(``postprocess=False``) so the gates and the placement see the full frame.

The edit runs on a SQUARE canvas: the source is centred on neutral grey in a
square of side ``max(w, h)`` rounded up to 16 and rendered at that square;
the result is cropped back at the known offset to the source's size BEFORE
it is gated and stored. Sent at its own narrow crop size (e.g. 656×1536) the
edit model re-frames the figure by ~2 % and the body gate refuses a correct
image (2026-11-09 end-to-end run: body XOR 0.111 narrow vs 0.005–0.007
square).

``cut_out`` turns an accepted hair-only image into the generator input
(R6): BiRefNet-DIS mask on the original colours, a square of side
``1.15 × max(w, h)`` around the mask, routed upscale below 1024², Lanczos
top-up to ≥ 1024²; a failed upscale falls back to Lanczos alone and says so
in the sidecar.

Blocking — called from the garment run's worker thread, which holds
``garment_store.char_lock`` (nothing here takes it). Status bookkeeping
(``garment_store.start/end``) belongs to that run as well.
"""
import io
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_images")

#: The square edit canvas has a side that is a multiple of this.
SIZE_STEP = 16
#: The generator wants at least this square (a 381² input crashed the worker).
CUTOUT_MIN_SIDE = 1024
#: Square side of the cut-out relative to the larger side of the mask box.
CUTOUT_PAD = 1.15
#: Alpha above this counts for the cut-out box (rembg leaves faint specks).
CUTOUT_ALPHA_MIN = 16
#: Mask threshold of the gate masks.
MASK_THRESHOLD = 128
#: The edit attempts per step (R5).
ATTEMPTS = 2
_ORDINALS = ("first", "second", "third")


class GateRefused(RuntimeError):
    """Every attempt of an edit step failed its gate."""

    def __init__(self, step: str, view: str, records: List[Dict[str, Any]]):
        from app.core.garment_gates import gate_summary
        self.step, self.view, self.records = step, view, list(records)
        super().__init__(f"{step} {view} refused — {gate_summary(self.records)}")


def render_size(size: Tuple[int, int]) -> Tuple[int, int]:
    """``(width, height)`` rounded up to ``SIZE_STEP``."""
    return tuple(-(-int(v) // SIZE_STEP) * SIZE_STEP for v in size)  # type: ignore[return-value]


def _kind_module(item_id: str):
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    if garment_set.garment_kind_of(item) == garment_set.CLOTHING:
        kind = garment_set.CLOTHING
    elif item.get("category") != "garment":
        raise ValueError(f"{item_id!r} is no garment item")
    else:
        kind = str((item.get("garment") or {}).get("kind") or "")
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair
    raise ValueError(f"no image chain for garment kind {kind!r}")


def _rgb(path: Path, size: Optional[Tuple[int, int]] = None):
    """The image as an RGB uint8 array, resampled (pure scale) to ``size``."""
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    if size is not None and rgb.size != tuple(size):
        rgb = rgb.resize(tuple(size), Image.Resampling.LANCZOS)
    return np.asarray(rgb)


def _mask_image(data: bytes, size: Tuple[int, int]):
    """BiRefNet-DIS mask of an encoded image as an L image of ``size``."""
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    raw = run_rembg(data, MESH_INPUT_REMBG_MODEL, only_mask=True)
    with Image.open(io.BytesIO(raw)) as im:
        mask = im.convert("L")
    if mask.size != tuple(size):
        mask = mask.resize(tuple(size), Image.Resampling.BILINEAR)
    return mask


def _mask(path: Path, size: Tuple[int, int]):
    import numpy as np
    return np.asarray(_mask_image(Path(path).read_bytes(), size)) >= MASK_THRESHOLD


def _image_size(path: Path) -> Tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def square_frame(size: Tuple[int, int]) -> Tuple[int, Tuple[int, int]]:
    """``(side, (dx, dy))`` of the square edit canvas for a source of
    ``size``: side = ``max(w, h)`` rounded up to ``SIZE_STEP``, the source
    centred at offset ``((side - w) // 2, (side - h) // 2)``."""
    w, h = int(size[0]), int(size[1])
    side = render_size((max(w, h), max(w, h)))[0]
    return side, ((side - w) // 2, (side - h) // 2)


@contextmanager
def square_reference(path: Path, refs_dir: Path):
    """The edit source centred on a neutral-grey square (``square_frame``);
    yields ``(reference path, side, offset, source size)``.

    Transparent pixels become the grey of ``model_refs.neutral_view_reference``
    (an RGBA cut-out would otherwise reach the backend black). The copy keeps
    the source's file name (the sidecar records the reference by name) and
    lives in a private temp dir inside ``refs_dir``, where the reference
    containment gate accepts it."""
    from PIL import Image
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
    side, offset = square_frame(rgba.size)
    canvas = Image.new("RGBA", (side, side), VIEW_REFERENCE_BACKGROUND + (255,))
    canvas.alpha_composite(rgba, offset)
    with tempfile.TemporaryDirectory(prefix=".viewref_", dir=refs_dir) as tmp:
        out = Path(tmp) / Path(path).name
        canvas.convert("RGB").save(out, format="PNG")
        yield out, side, offset, rgba.size


def _crop_back(path: Path, target: Path, side: int, offset: Tuple[int, int],
               size: Tuple[int, int]) -> Path:
    """The square render cut back to the source frame, as PNG at ``target``:
    a render of another size is first scaled (pure scale) to the requested
    ``side``², then the source's ``size`` is cropped at ``offset``. The
    renderer's sidecar moves along."""
    from PIL import Image
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    if rgb.size != (side, side):
        rgb = rgb.resize((side, side), Image.Resampling.LANCZOS)
    dx, dy = offset
    cropped = rgb.crop((dx, dy, dx + int(size[0]), dy + int(size[1])))
    tmp = target.with_name(f".{target.name}.tmp")
    cropped.save(tmp, format="PNG")
    tmp.replace(target)
    if path != target:
        path.unlink(missing_ok=True)
        side_file = path.with_suffix(".json")
        if side_file.is_file() and side_file != target.with_suffix(".json"):
            side_file.replace(target.with_suffix(".json"))
    return target


def _drop_later(character_name: str, item_id: str, fsig: str, step: str, view: str) -> None:
    """A new accepted image makes the later image steps of the view stale."""
    from app.core.garment_store import IMAGE_STEPS, garment_path
    for later in IMAGE_STEPS[IMAGE_STEPS.index(step) + 1:]:
        path = garment_path(character_name, item_id, fsig, "image", step=later, view=view)
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)


def _accepted(path: Path) -> bool:
    from app.core.garment_store import read_record
    return path.is_file() and read_record(path.with_suffix(".json")).get("accepted") is True


def run_edit_step(character_name: str, item_id: str, fsig: str, step: str, view: str, *,
                  force: bool = False,
                  pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None) -> Path:
    """Render, gate and store one edit step of one view; returns the final
    image ``images/{item}_{fsig}_{step}_{view}.png``.

    ``pair_check`` (the orchestration's check against the OTHER view, e.g.
    the hair-only front against the accepted back's bottom edge) gets every
    attempt's gate record; a reason it returns refuses that attempt like a
    gate reason does, so the check uses the attempts of this step.

    Cached: an accepted final of this fsig is returned unless ``force``.
    ``base_body.MissingInput`` when the base view or the source step's
    accepted image is missing; ``GateRefused`` after ``ATTEMPTS`` failed
    attempts (the attempt files and their gate records stay for the UI)."""
    from app.core import base_body, expression_regen
    from app.core.garment_store import garment_path, read_record, write_record
    from app.core.model_refs import find_ref_image, get_model_refs_dir, neutral_view_reference
    from app.models.character import get_character_profile

    final = garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    if not force and _accepted(final):
        return final
    kind = _kind_module(item_id)
    if step not in kind.EDIT_STEPS:
        raise ValueError(f"no edit step {step!r}")
    profile = get_character_profile(character_name) or {}
    bsig = base_body.base_signature(character_name, profile=profile)
    base = find_ref_image(character_name, base_body._kind(view), bsig)
    if base is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
    source_step = kind.EDIT_STEPS[step]["source"]
    if source_step == "base":
        source = base
    else:
        source = garment_path(character_name, item_id, fsig, "image", step=source_step, view=view)
        if not _accepted(source):
            raise base_body.MissingInput(f"The {source_step} {view} image is missing — run that step first")
    prompt, negative = kind.edit_prompt(character_name, step, view, profile=profile)
    refs_dir = get_model_refs_dir(character_name)
    final.parent.mkdir(parents=True, exist_ok=True)

    with neutral_view_reference(base, refs_dir) as flat_base:
        base_size = _image_size(flat_base)
        base_rgb = _rgb(flat_base)
        base_mask = _mask(flat_base, base_size)
    source_rgb = source_mask = None
    if source != base:
        source_rgb = _rgb(source, base_size)
        source_mask = _mask(source, base_size)

    records: List[Dict[str, Any]] = []
    for attempt in range(1, ATTEMPTS + 1):
        target = garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=attempt)
        stem = target.with_suffix("")
        with square_reference(source, refs_dir) as (reference, side, offset, source_size):
            path = expression_regen.render_character_image(
                character_name,
                output_stem=stem,
                equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="",
                bare_prompt=prompt, extra_negative=negative,
                image_use_case="garment_edit",
                occasion="garment_view",
                override_width=side, override_height=side,
                apply_state_modifiers=False,
                back_view=view == "back",
                reference_image=reference,
                sidecar_extra={"garment": {"item_id": item_id, "fsig": fsig, "step": step,
                                           "view": view, "attempt": attempt},
                              "edit_canvas": {"side": side, "offset": list(offset),
                                              "crop": list(source_size)}},
                character_loras=False,
                postprocess=False)
        if path is None:
            record: Dict[str, Any] = {"view": view, "ok": False, "reasons": ["render failed"]}
        else:
            path = _crop_back(Path(path), target, side, offset, source_size)
            record = kind.gate(step, view, base_rgb=base_rgb, base_mask=base_mask,
                               source_rgb=source_rgb, source_mask=source_mask,
                               edit_rgb=_rgb(path, base_size), edit_mask=_mask(path, base_size))
            reason = pair_check(record) if pair_check is not None else None
            if reason:
                record = {**record, "ok": False, "reasons": [*(record.get("reasons") or []), reason]}
        record["attempt"] = attempt
        records.append(record)
        if path is not None:
            sidecar = read_record(target.with_suffix(".json"))
            write_record(target.with_suffix(".json"), {**sidecar, "gate": record})
        logger.info("Garment %s %s %s attempt %d: %s %s", character_name, step, view, attempt,
                    "accepted" if record["ok"] else "refused", record.get("reasons") or "")
        if record["ok"]:
            shutil.copyfile(target, final)
            sidecar = read_record(target.with_suffix(".json"))
            sidecar.pop("gate", None)
            write_record(final.with_suffix(".json"), {
                **sidecar, "accepted": True, "attempt": attempt,
                "gates": {_ORDINALS[n]: r for n, r in enumerate(records)}})
            _drop_later(character_name, item_id, fsig, step, view)
            return final
    raise GateRefused(step, view, records)


def cut_out(character_name: str, item_id: str, fsig: str, view: str, *, force: bool = False) -> Path:
    """The generator input of one view, ``images/{item}_{fsig}_cutout_{view}.png``
    (R6), from the accepted hair-only image (step ``ghost``).

    RGBA: the BiRefNet-DIS mask as alpha on the original colours, cropped to a
    square of side ``int(1.15 × max(w, h))`` around the mask box (padding
    outside the frame is transparent). Below ``CUTOUT_MIN_SIDE`` the colours
    go through the routed upscale (``upscale`` occasion) and then a Lanczos
    top-up; an upscale that fails leaves Lanczos alone (sidecar
    ``upscale: {status: "lanczos", reason}``). The sidecar records the box,
    the side and the upscale route. Cached unless ``force``."""
    from PIL import Image
    from app.core import base_body
    from app.core.garment_store import garment_path, write_record
    from app.core.timeutils import utc_now_iso

    target = garment_path(character_name, item_id, fsig, "image", step="cutout", view=view)
    if not force and _accepted(target):
        return target
    _kind_module(item_id)
    ghost = garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
    if not _accepted(ghost):
        raise base_body.MissingInput(f"The ghost {view} image is missing — run that step first")
    data = ghost.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
    alpha = _mask_image(data, rgb.size)
    box = alpha.point(lambda v: 255 if v > CUTOUT_ALPHA_MIN else 0).getbbox()
    if box is None:
        raise ValueError(f"No hair found in the ghost {view} image")
    x0, y0, x1, y1 = box
    side = int(CUTOUT_PAD * max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    crop = (cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)
    colours = rgb.crop(crop)       # outside the frame: black, but alpha 0 there
    alpha_sq = alpha.crop(crop)

    upscale: Dict[str, Any]
    if side >= CUTOUT_MIN_SIDE:
        upscale = {"status": "not_needed"}
    else:
        buf = io.BytesIO()
        colours.save(buf, format="PNG")
        try:
            from app.imagegen.service import get_image_service
            result = get_image_service().upscale_image(buf.getvalue(), character_name=character_name)
            with Image.open(io.BytesIO(result["bytes"])) as up:
                colours = up.convert("RGB")
            upscale = {k: v for k, v in result.items() if k != "bytes"}
        except Exception as e:  # noqa: BLE001 — Lanczos alone is the documented fallback
            logger.warning("Garment cut-out %s %s: upscale failed, Lanczos only: %s", character_name, view, e)
            upscale = {"status": "lanczos", "reason": str(e) or type(e).__name__}
    final_side = max(colours.width, CUTOUT_MIN_SIDE) if side < CUTOUT_MIN_SIDE else side
    if colours.size != (final_side, final_side):
        colours = colours.resize((final_side, final_side), Image.Resampling.LANCZOS)
    if alpha_sq.size != (final_side, final_side):
        alpha_sq = alpha_sq.resize((final_side, final_side), Image.Resampling.LANCZOS)
    out = colours.convert("RGBA")
    out.putalpha(alpha_sq)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    out.save(tmp, format="PNG")
    tmp.replace(target)
    from app.core.base_body import file_sha256
    write_record(target.with_suffix(".json"), {
        "garment": {"item_id": item_id, "fsig": fsig, "step": "cutout", "view": view},
        "source": ghost.name, "source_sha256": file_sha256(ghost),
        "bbox": [x0, y0, x1, y1], "side": side, "size": [final_side, final_side],
        "upscale": upscale, "accepted": True, "created_at": utc_now_iso()})
    logger.info("Garment cut-out %s %s: side %d -> %d (%s)", character_name, view, side, final_side,
                upscale.get("status"))
    return target
