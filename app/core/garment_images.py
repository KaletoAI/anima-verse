"""The image steps of a garment chain: gated edits and the cut-out
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R4–R7,
Task 4).

``run_edit_step`` renders one edit step of one view — up to two attempts
(R5: each a fresh backend call with the backend's own seed), every attempt
gated by the garment kind's gate (``garment_gates``). The accepted attempt
is copied to the step's final file; two refusals raise ``GateRefused`` with
both gate records. The edit is an image EDIT of its source on the routed
``garment_view`` occasion: the base view (the kind's first step — hair
``haired``, clothing ``worn``) or the accepted image of the step before
(``ghost``), use case ``garment_edit`` (empty style,
the spike negative), no character LoRAs, and published unprocessed
(``postprocess=False``) so the gates and the placement see the full frame.

The edit runs on a SQUARE canvas: the source is centred on neutral grey in a
square of side ``max(w, h)`` rounded up to 16 and rendered at that square;
the result is cropped back at the known offset to the source's size BEFORE
it is gated and stored. Sent at its own narrow crop size (e.g. 656×1536) the
edit model re-frames the figure by ~2 % and the body gate refuses a correct
image (2026-11-09 end-to-end run: body XOR 0.111 narrow vs 0.005–0.007
square).

A step with a ``position_reference`` (the ghost: the worn view's garment
region / the haired view's hair) is REGISTERED onto it before its gate
(``_register``): the edit model may redraw the piece a centimetre off or a
few per cent larger (Kira's Black Blazer back, 2026-11-10), so a similarity
(shift + uniform scale, capped: ``garment_gates.REG_SHIFT_MAX`` /
``REG_SCALE_MIN..MAX``) is estimated from the silhouettes and the attempt
file is rewritten moved; the gate then measures the residual. The record
keeps the correction (``registration``, chip keys ``reg_shift`` /
``reg_scale``). Everything after the ghost reads the moved file.

The kind's own module (``kind_module``: ``garment_hair``,
``garment_clothing``) gives the edit steps, prompts and gates.

A step whose back is DRAFTED (``EDIT_STEPS[step]["back"] == "draft"``:
clothing ``worn``) does not edit the base back. It takes the outfit's two
steps (``base_body.render_draft`` / ``render_fit``, the occasions
``outfit_back_draft`` / ``outfit_back``): a draft rendered fresh from the
step's accepted FRONT (``kind.draft_prompt``), stored as
``images/{item}_{fsig}_{step}draft_back.png``, then up to ``ATTEMPTS`` fits
of the cut-out draft onto the cut-out base back (``kind.fit_prompt``),
both on neutral grey in a square canvas, published unprocessed and cropped
back onto the base back's frame. Each fit is gated like an edit (the kind's
gate against the base back: a poor registration = changed outline/colour
outside the garment refuses it and the next fit renders from the same
draft; the fit's outline limit is the looser ``FIT_OUTSIDE_XOR_MAX`` — a fit
re-renders the whole figure) plus ``kind.back_reasons`` against the accepted
front's record (the front opening on the back). The accepted back records
the front it follows (``front_sha256``); a new accepted front drops the back
and everything after it.

A step whose gate changed (``kind.GATE_VERSIONS``: clothing ``worn``,
``garment_gates.WORN_GATE_VERSION``) RE-GATES its stored attempts before it
renders again (``_regate_stored``): when the view's final is not accepted,
every attempt file whose gate record is of an older version is gated again
from the file (masks only, no image job) — a drafted back only while the
attempt was fitted from the current front (``front_sha256``). The first
that passes is published like a fresh accepted attempt; the others keep
their new records. Nothing passes: the step renders as before. That runs on
the next chain run of the piece and on the step's Regenerate / Run all.

``cut_out`` turns an accepted ghost image into the generator input
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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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


def kind_module(kind: str):
    """The module of a garment kind's image chain (``EDIT_STEPS``,
    ``edit_prompt``, ``gate``, ``position_reference``, ``SUBJECT`` and the pair hooks ``PAIR_STEP``,
    ``pair_agree``, ``pair_reason``, ``PAIR_REFUSED``, ``front_hints``).
    ValueError for a kind without one."""
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair
    if kind == "clothing":
        from app.core import garment_clothing
        return garment_clothing
    raise ValueError(f"no image chain for garment kind {kind!r}")


def _item_kind(item_id: str) -> str:
    from app.core import garment_set
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    if garment_set.garment_kind_of(item) == garment_set.CLOTHING:
        return garment_set.CLOTHING
    if item.get("category") != "garment":
        raise ValueError(f"{item_id!r} is no garment item")
    return str((item.get("garment") or {}).get("kind") or "")


def _kind_module(item_id: str):
    return kind_module(_item_kind(item_id))


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


def _crop_back(path: Path, target: Path, side, offset: Tuple[int, int],
               size: Tuple[int, int]) -> Path:
    """The square render cut back to the source frame, as PNG at ``target``:
    a render of another size is first scaled (pure scale) to the requested
    ``side``² (or ``side`` = ``(w, h)``, the fit canvas), then the source's
    ``size`` is cropped at ``offset``. The renderer's sidecar moves along."""
    from PIL import Image
    canvas = tuple(side) if isinstance(side, (tuple, list)) else (side, side)
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    if rgb.size != canvas:
        rgb = rgb.resize(canvas, Image.Resampling.LANCZOS)
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


def _drop_later(character_name: str, item_id: str, fsig: str, step: str, view: str, *,
                inclusive: bool = False) -> None:
    """A new accepted image makes the later image steps of the view stale
    (the steps of the item's kind, ``garment_store.image_steps``);
    ``inclusive``: the step itself too."""
    from app.core.garment_store import garment_path, image_steps
    order = image_steps(_item_kind(item_id))
    for later in order[order.index(step) + (0 if inclusive else 1):]:
        path = garment_path(character_name, item_id, fsig, "image", step=later, view=view)
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)


def _drafted(kind, step: str) -> bool:
    """Whether the kind's ``step`` drafts its back from its front."""
    return (getattr(kind, "EDIT_STEPS", {}).get(step) or {}).get("back") == "draft"


def draft_path(character_name: str, item_id: str, fsig: str, step: str) -> Path:
    """The draft of a drafted back: ``images/{item}_{fsig}_{step}draft_back.png``
    (a stored garment name, swept with its fsig group)."""
    from app.core.garment_store import garment_path
    final = garment_path(character_name, item_id, fsig, "image", step=step, view="back")
    return final.with_name(f"{item_id}_{fsig}_{step}draft_back.png")


def accepted_record(path: Path) -> Optional[Dict[str, Any]]:
    """The gate record of the accepted attempt of a final image (``gates``
    by ordinal, ``attempt``), None when it is not accepted."""
    from app.core.garment_store import read_record
    if not _accepted(path):
        return None
    record = read_record(path.with_suffix(".json"))
    gates = record.get("gates") or {}
    try:
        return gates.get(_ORDINALS[int(record.get("attempt") or 1) - 1])
    except (IndexError, TypeError, ValueError):
        return None


def _follows_front(character_name: str, item_id: str, fsig: str, step: str, back: Path) -> bool:
    """A drafted back counts only while it was made from the CURRENT
    accepted front (``front_sha256`` of its record)."""
    from app.core.base_body import file_sha256
    from app.core.garment_store import garment_path, read_record
    front = garment_path(character_name, item_id, fsig, "image", step=step, view="front")
    sha = read_record(back.with_suffix(".json")).get("front_sha256")
    return bool(sha) and _accepted(front) and sha == file_sha256(front)


def _publish(character_name: str, item_id: str, fsig: str, step: str, view: str, kind, target: Path,
             final: Path, records: List[Dict[str, Any]], attempt: int,
             extra: Optional[Dict[str, Any]] = None) -> Path:
    """Copy an accepted attempt onto the step's final file with its record
    (every attempt's gate by ordinal); the later steps of the view go stale,
    and a new front of a drafted step drops the back it was drafted from."""
    from app.core.garment_store import read_record, write_record
    shutil.copyfile(target, final)
    sidecar = read_record(target.with_suffix(".json"))
    sidecar.pop("gate", None)
    write_record(final.with_suffix(".json"), {
        **sidecar, **(extra or {}), "accepted": True, "attempt": attempt,
        "gates": {_ORDINALS[n]: r for n, r in enumerate(records)}})
    _drop_later(character_name, item_id, fsig, step, view)
    if view == "front" and _drafted(kind, step):
        _drop_later(character_name, item_id, fsig, step, "back", inclusive=True)
    return final


def _accepted(path: Path) -> bool:
    from app.core.garment_store import read_record
    return path.is_file() and read_record(path.with_suffix(".json")).get("accepted") is True


def run_edit_step(character_name: str, item_id: str, fsig: str, step: str, view: str, *,
                  force: bool = False,
                  pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
                  prompt_hints: Optional[Dict[str, Any]] = None) -> Path:
    """Render, gate and store one edit step of one view; returns the final
    image ``images/{item}_{fsig}_{step}_{view}.png``.

    ``pair_check`` (the orchestration's check against the OTHER view, e.g.
    the hair-only front against the accepted back's bottom edge) gets every
    attempt's gate record; a reason it returns refuses that attempt like a
    gate reason does, so the check uses the attempts of this step.
    ``prompt_hints`` go to the kind's ``edit_prompt`` as keyword arguments
    (hair: ``length_t``, see ``haired_length``); ``item_id`` always does.

    Cached: an accepted final of this fsig is returned unless ``force``.
    ``base_body.MissingInput`` when the base view or the source step's
    accepted image is missing; ``GateRefused`` after ``ATTEMPTS`` failed
    attempts (the attempt files and their gate records stay for the UI)."""
    from app.core import base_body, expression_regen
    from app.core.garment_store import garment_path, read_record, write_record
    from app.core.model_refs import find_ref_image, get_model_refs_dir, neutral_view_reference
    from app.models.character import get_character_profile

    final = garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    kind = _kind_module(item_id)
    drafted = view == "back" and _drafted(kind, step)
    if not force and _accepted(final) and (
            not drafted or _follows_front(character_name, item_id, fsig, step, final)):
        return final
    if step not in kind.EDIT_STEPS:
        raise ValueError(f"no edit step {step!r}")
    profile = get_character_profile(character_name) or {}
    bsig = base_body.base_signature(character_name, profile=profile)
    base = find_ref_image(character_name, base_body._kind(view), bsig)
    if base is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
    refs_dir = get_model_refs_dir(character_name)
    final.parent.mkdir(parents=True, exist_ok=True)
    if drafted:
        return _drafted_back(character_name, item_id, fsig, step, kind, profile=profile, base=base,
                             refs_dir=refs_dir, final=final, pair_check=pair_check)
    source_step = kind.EDIT_STEPS[step]["source"]
    if source_step == "base":
        source = base
    else:
        source = garment_path(character_name, item_id, fsig, "image", step=source_step, view=view)
        if not _accepted(source):
            raise base_body.MissingInput(f"The {source_step} {view} image is missing — run that step first")
    prompt, negative = kind.edit_prompt(character_name, step, view, profile=profile, item_id=item_id,
                                        **(prompt_hints or {}))

    with neutral_view_reference(base, refs_dir) as flat_base:
        base_size = _image_size(flat_base)
        base_rgb = _rgb(flat_base)
        base_mask = _mask(flat_base, base_size)
    source_rgb = source_mask = None
    if source != base:
        source_rgb = _rgb(source, base_size)
        source_mask = _mask(source, base_size)

    if not _accepted(final):
        def regate(path: Path, old: Dict[str, Any]) -> Dict[str, Any]:
            record = kind.gate(step, view, base_rgb=base_rgb, base_mask=base_mask, source_rgb=source_rgb,
                               source_mask=source_mask, edit_rgb=_rgb(path, base_size),
                               edit_mask=_mask(path, base_size), item_id=item_id)
            # A registered attempt file is already moved: its correction stays recorded.
            record.update({k: old[k] for k in ("registration", "reg_shift", "reg_scale") if k in old})
            return _with_pair(record, pair_check)
        hit = _regate_stored(character_name, item_id, fsig, step, view, kind, final=final, regate=regate)
        if hit is not None:
            return hit

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
                postprocess=False,
                # Load is no refusal: the chain answers retry_later, never a record.
                raise_load=True)
        if path is None:
            record: Dict[str, Any] = {"view": view, "ok": False, "reasons": ["render failed"]}
        else:
            path = _crop_back(Path(path), target, side, offset, source_size)
            edit_rgb, edit_mask = _rgb(path, base_size), _mask(path, base_size)
            reference = (kind.position_reference(step, base_rgb=base_rgb, base_mask=base_mask,
                                                 source_rgb=source_rgb, source_mask=source_mask)
                         if source_rgb is not None else None)
            registration = None
            if reference is not None:
                edit_rgb, edit_mask, registration = _register(
                    kind, step, view, path, base_size, reference,
                    gate_args={"base_rgb": base_rgb, "base_mask": base_mask, "source_rgb": source_rgb,
                               "source_mask": source_mask, "item_id": item_id},
                    edit_rgb=edit_rgb, edit_mask=edit_mask)
            record = kind.gate(step, view, base_rgb=base_rgb, base_mask=base_mask,
                               source_rgb=source_rgb, source_mask=source_mask,
                               edit_rgb=edit_rgb, edit_mask=edit_mask, item_id=item_id)
            if registration is not None:
                record = _with_registration(record, registration)
            record = _with_pair(record, pair_check)
        record["attempt"] = attempt
        records.append(record)
        if path is not None:
            sidecar = read_record(target.with_suffix(".json"))
            write_record(target.with_suffix(".json"), {**sidecar, "gate": record})
        logger.info("Garment %s %s %s attempt %d: %s %s", character_name, step, view, attempt,
                    "accepted" if record["ok"] else "refused", record.get("reasons") or "")
        if record["ok"]:
            return _publish(character_name, item_id, fsig, step, view, kind, target, final, records, attempt)
    raise GateRefused(step, view, records)


def _with_pair(record: Dict[str, Any], pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]],
               extra: Sequence[str] = ()) -> Dict[str, Any]:
    """The gate record refused by ``extra`` reasons and the pair check's reason, if any."""
    reasons = list(extra)
    reason = pair_check(record) if pair_check is not None else None
    if reason:
        reasons.append(reason)
    if not reasons:
        return record
    return {**record, "ok": False, "reasons": [*(record.get("reasons") or []), *reasons]}


def _stale_gate(kind, step: str, record: Any) -> bool:
    """Whether a stored attempt's gate record predates the step's gate
    version (``kind.GATE_VERSIONS``; a record without ``gate_version`` is
    version 1). False for a step without a version or no record."""
    version = (getattr(kind, "GATE_VERSIONS", None) or {}).get(step)
    if version is None or not isinstance(record, dict) or not record:
        return False
    try:
        return int(record.get("gate_version") or 1) < int(version)
    except (TypeError, ValueError):
        return True


def _regate_stored(character_name: str, item_id: str, fsig: str, step: str, view: str, kind, *,
                   final: Path, regate: Callable[[Path, Dict[str, Any]], Dict[str, Any]],
                   keep: Optional[Callable[[Dict[str, Any]], bool]] = None,
                   follow_keys: Sequence[str] = ()) -> Optional[Path]:
    """Gate the stored attempt files of a refused view again (module
    docstring): every attempt whose gate record is stale (``_stale_gate``)
    and that ``keep`` accepts (its sidecar; a drafted back: fitted from the
    current front) gets ``regate(path, old record)`` as its new record —
    written into its sidecar, ``regated_from`` = the old version. The first
    that passes is published (``_publish``; ``follow_keys`` of its sidecar
    go into the final's record) and returned; None when none passes or none
    is stale. Reads files and masks only: never renders."""
    from app.core.garment_store import garment_path, read_record, write_record
    records: List[Dict[str, Any]] = []
    stale_any = False
    for attempt in range(1, ATTEMPTS + 1):
        target = garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=attempt)
        sidecar = read_record(target.with_suffix(".json")) if target.is_file() else {}
        old = sidecar.get("gate") if isinstance(sidecar.get("gate"), dict) else None
        if old is None:
            records.append({"view": view, "ok": False, "reasons": ["no stored attempt"], "attempt": attempt})
            continue
        if not _stale_gate(kind, step, old) or (keep is not None and not keep(sidecar)):
            records.append(old)
            continue
        stale_any = True
        record = {**regate(target, old), "attempt": attempt, "regated_from": int(old.get("gate_version") or 1)}
        records.append(record)
        write_record(target.with_suffix(".json"), {**sidecar, "gate": record})
        logger.info("Garment %s %s %s attempt %d re-gated (gate version %s -> %s): %s %s", character_name, step,
                    view, attempt, record["regated_from"], record.get("gate_version"),
                    "accepted" if record.get("ok") else "refused", record.get("reasons") or "")
        if record.get("ok"):
            extra = {k: sidecar[k] for k in follow_keys if k in sidecar}
            return _publish(character_name, item_id, fsig, step, view, kind, target, final, records, attempt,
                            extra or None)
    if stale_any:
        logger.info("Garment %s %s %s: no stored attempt passes the current gate — rendering", character_name,
                    step, view)
    return None


#: The gate numbers a registration corrects; after it they are the residual.
POSITION_KEYS = ("top_dy", "centre_dx", "w_ratio")


def _register(kind, step: str, view: str, path: Path, base_size: Tuple[int, int], reference, *,
              gate_args: Dict[str, Any], edit_rgb, edit_mask) -> Tuple[Any, Any, Optional[Dict[str, Any]]]:
    """Register an attempt of a step with a ``position_reference`` (the
    ghost) onto that reference (``garment_gates.register``) BEFORE its gate:
    within the caps and not negligible, the attempt file at ``path`` is
    rewritten moved (``garment_gates.warp``, in the file's own pixels) — the
    cut-out, the mesh views and the fit's framing all read that file — and
    the returned arrays are the moved image (re-read) and the moved mask.
    Returns ``(edit_rgb, edit_mask, registration)``; the registration
    record carries the estimate, ``applied``, a ``note`` when not applied,
    and ``before`` = the position numbers of the image as rendered. None
    when nothing can be estimated (no figure, empty masks)."""
    import numpy as np
    from PIL import Image
    from app.core import garment_gates
    zones = garment_gates._zones(gate_args["base_mask"])
    if zones is None or zones[1] <= 0:
        return edit_rgb, edit_mask, None
    estimate = garment_gates.register(reference, edit_mask, body_h=zones[1])
    if estimate is None:
        return edit_rgb, edit_mask, None
    before = kind.gate(step, view, edit_rgb=edit_rgb, edit_mask=edit_mask, **gate_args)
    applied = estimate["within_caps"] and not estimate["negligible"]
    info: Dict[str, Any] = {**estimate, "applied": applied,
                            "before": {k: before.get(k) for k in (*POSITION_KEYS, "ok")}}
    if not applied:
        info["note"] = ("negligible" if estimate["within_caps"]
                        else "beyond the correction caps — gated as rendered")
        return edit_rgb, edit_mask, info
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"))
    factor = (rgb.shape[0] / base_size[1], rgb.shape[1] / base_size[0])
    tmp = path.with_name(f".{path.name}.tmp")
    Image.fromarray(garment_gates.warp(rgb, estimate, factor=factor)).save(tmp, format="PNG")
    tmp.replace(path)
    return _rgb(path, base_size), garment_gates.warp(edit_mask, estimate), info


def _with_registration(record: Dict[str, Any], registration: Dict[str, Any]) -> Dict[str, Any]:
    """The gate record with its registration: ``registration`` (+ the
    ``residual`` = the record's position numbers) and the chip keys
    ``reg_shift`` (|centroid shift| / Hb) and ``reg_scale``."""
    residual = {k: record.get(k) for k in POSITION_KEYS}
    return {**record, "reg_shift": registration.get("shift_abs"), "reg_scale": registration.get("scale"),
            "registration": {**registration, "residual": residual}}


def _drafted_back(character_name: str, item_id: str, fsig: str, step: str, kind, *,
                  profile: Dict[str, Any], base: Path, refs_dir: Path, final: Path,
                  pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None) -> Path:
    """The back of a drafted step (module docstring): one DRAFT from the
    accepted front, then up to ``ATTEMPTS`` FITs of it onto the base back,
    each gated (the kind's gate against the base back + ``kind.back_reasons``
    against the front's accepted record). ``MissingInput`` without an
    accepted front, ``RuntimeError`` when the draft renders nothing,
    ``GateRefused`` after the fits."""
    from app.core import base_body
    from app.core.base_body import file_sha256
    from app.core.garment_store import garment_path, read_record, write_record
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND, _tpose_size, neutral_view_reference
    fit_text, fit_keywords = kind.fit_prompt(step, item_id=item_id)
    front = garment_path(character_name, item_id, fsig, "image", step=step, view="front")
    front_gate = accepted_record(front)
    if front_gate is None:
        raise base_body.MissingInput(f"The {step} front image is missing — the back is drafted from it")
    front_sha = file_sha256(front)
    meta = {"item_id": item_id, "fsig": fsig, "step": step, "view": "back"}
    with neutral_view_reference(base, refs_dir) as flat_base:
        base_size = _image_size(flat_base)
        base_rgb = _rgb(flat_base)
        base_mask = _mask(flat_base, base_size)

    def gate_fit(path: Path) -> Dict[str, Any]:
        record = kind.gate(step, "back", base_rgb=base_rgb, base_mask=base_mask, source_rgb=None, source_mask=None,
                           edit_rgb=_rgb(path, base_size), edit_mask=_mask(path, base_size),
                           item_id=item_id, fitted=True, front_gate=front_gate)
        return _with_pair(record, pair_check, list(kind.back_reasons(front_gate, record)))

    if not (_accepted(final) and _follows_front(character_name, item_id, fsig, step, final)):
        hit = _regate_stored(character_name, item_id, fsig, step, "back", kind, final=final,
                             regate=lambda path, _old: gate_fit(path),
                             keep=lambda sidecar: sidecar.get("front_sha256") == front_sha,
                             follow_keys=("front_sha256", "draft", "draft_sha256"))
        if hit is not None:
            return hit

    # The render arguments of the outfit's draft and fit, nothing worn on
    # the profile (the text names the piece, the reference shows it).
    mesh_profile = {**profile, "equipped_pieces": {}, "equipped_items": []}
    # ``raise_load``: the draft and the fit are garment steps — load is
    # retry_later, never a refusal record (the outfit's own dressed views
    # keep their None-on-failure contract).
    common = {**base_body._dress_common("back", pieces={}, items=[], profile=mesh_profile, size=_tpose_size()),
              "raise_load": True}
    draft_stem = draft_path(character_name, item_id, fsig, step).with_suffix("")
    draft = base_body.render_draft(
        character_name, "back", stem=draft_stem, front=front, refs_dir=refs_dir,
        prompt=kind.draft_prompt(character_name, step, profile=profile, item_id=item_id),
        profile=profile, common=common,
        sidecar_extra={"garment": {**meta, "stage": "draft"}, "front_sha256": front_sha})
    if draft is None:
        raise RuntimeError(f"The {step} back draft rendered nothing")
    draft = Path(draft)
    follow = {"front_sha256": front_sha, "draft": draft.name, "draft_sha256": file_sha256(draft)}

    records: List[Dict[str, Any]] = []
    with base_body.fit_references(base, draft, refs_dir, (1, 1), background=VIEW_REFERENCE_BACKGROUND) \
            as (base_reference, draft_reference, canvas):
        offset = ((canvas[0] - base_size[0]) // 2, 0)
        for attempt in range(1, ATTEMPTS + 1):
            target = garment_path(character_name, item_id, fsig, "image", step=step, view="back", attempt=attempt)
            path = base_body.render_fit(
                character_name, "back", stem=target.with_suffix(""), base_reference=base_reference,
                draft_reference=draft_reference, canvas=canvas, common=common, postprocess=False,
                prompt=fit_text, prompt_keywords=fit_keywords,
                extra={"garment": {**meta, "attempt": attempt, "stage": "fit"}, **follow,
                       "edit_canvas": {"side": list(canvas), "offset": list(offset), "crop": list(base_size)}})
            if path is None:
                record: Dict[str, Any] = {"view": "back", "ok": False, "reasons": ["render failed"]}
            else:
                path = _crop_back(Path(path), target, canvas, offset, base_size)
                record = gate_fit(path)
            record["attempt"] = attempt
            records.append(record)
            if path is not None:
                sidecar = read_record(target.with_suffix(".json"))
                write_record(target.with_suffix(".json"), {**sidecar, "gate": record})
            logger.info("Garment %s %s back (draft + fit) attempt %d: %s %s", character_name, step, attempt,
                        "accepted" if record["ok"] else "refused", record.get("reasons") or "")
            if record["ok"]:
                return _publish(character_name, item_id, fsig, step, "back", kind, target, final, records,
                                attempt, follow)
    raise GateRefused(step, "back", records)


def haired_length(character_name: str, item_id: str, fsig: str, view: str = "back") -> Optional[Dict[str, Any]]:
    """Where the hair of the accepted ``haired`` image of ``view`` ends
    against the base figure (``garment_gates.hair_length``: ``{bottom, t}``),
    on the same masks as the gates; None when the image or the base view is
    missing or no hair is found."""
    from app.core import base_body
    from app.core.garment_gates import hair_length
    from app.core.garment_store import garment_path
    from app.core.model_refs import find_ref_image, get_model_refs_dir, neutral_view_reference
    from app.models.character import get_character_profile
    haired = garment_path(character_name, item_id, fsig, "image", step="haired", view=view)
    if not _accepted(haired):
        return None
    profile = get_character_profile(character_name) or {}
    base = find_ref_image(character_name, base_body._kind(view),
                          base_body.base_signature(character_name, profile=profile))
    if base is None:
        return None
    with neutral_view_reference(base, get_model_refs_dir(character_name)) as flat_base:
        size = _image_size(flat_base)
        base_rgb, base_mask = _rgb(flat_base), _mask(flat_base, size)
    return hair_length(base_rgb, base_mask, _rgb(haired, size), _mask(haired, size))


def cut_out(character_name: str, item_id: str, fsig: str, view: str, *, force: bool = False) -> Path:
    """The generator input of one view, ``images/{item}_{fsig}_cutout_{view}.png``
    (R6), from the accepted ghost image (hair-only / garment-only).

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
    kind = _kind_module(item_id)
    ghost = garment_path(character_name, item_id, fsig, "image", step="ghost", view=view)
    if not _accepted(ghost):
        raise base_body.MissingInput(f"The ghost {view} image is missing — run that step first")
    data = ghost.read_bytes()
    with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
    alpha = _mask_image(data, rgb.size)
    box = alpha.point(lambda v: 255 if v > CUTOUT_ALPHA_MIN else 0).getbbox()
    if box is None:
        raise ValueError(f"No {kind.SUBJECT} found in the ghost {view} image")
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
