"""The image steps of a garment chain: gated edits and the cut-out
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R4–R7,
Task 4).

``run_edit_step`` renders one edit step of one view — up to two attempts
(R5: each a fresh backend call with the backend's own seed), every attempt
gated by the garment kind's gate (``garment_gates``). The accepted attempt
is copied to the step's final file; two refusals raise ``GateRefused`` with
both gate records. The edit is an image EDIT of its source on the routed
``garment_view`` occasion: the base view (the kind's first step — clothing
``worn``) or the accepted image of the step before
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
region) is REGISTERED onto it before its gate
(``_register``): the edit model may redraw the piece a centimetre off or a
few per cent larger (Kira's Black Blazer back, 2026-11-10), so a similarity
(shift + uniform scale, capped: ``garment_gates.REG_SHIFT_MAX`` /
``REG_SCALE_MIN..MAX``) is estimated from the silhouettes and the attempt
file is rewritten moved; the gate then measures the residual. The record
keeps the correction (``registration``, chip keys ``reg_shift`` /
``reg_scale``). Everything after the ghost reads the moved file. A kind may
estimate its own correction (``register_estimate``): the clothing ghost (both
views) of a waistband piece is scaled by its waistband width and shifted onto the
waistband top, without the outline caps (``garment_gates.register_waistband``, rulings 13d/13f;
record key ``registered``).

The kind's own module (``kind_module``: ``garment_clothing`` — the only kind
with an image chain; hair has none since the hair-from-body change) gives the
edit steps, prompts and gates.

A step whose back is DRAFTED (``EDIT_STEPS[step]["back"] == "draft"``:
clothing ``worn``) does not edit the base back. It takes the outfit's two
steps (Task 11g, Ruling C1): a DRAFT (``base_body.render_draft``, occasion
``outfit_back_draft``, the step's only hub job) rendered fresh from the
step's accepted FRONT (``kind.draft_prompt``), stored as
``images/{item}_{fsig}_{step}draft_back.png``, then the CPU COMPOSITE of the
draft's piece onto the base back (``view_composite.compose``, rule
"piece"; no hub job, no model fallback), flattened onto neutral grey in the
base back's frame and stored as the attempt. The composite's checks
(alignment IoU >= ``view_composite.IOU_MIN``, coverage >= ``COVERAGE_MIN``)
come first: a composite that fails them is refused without a gate and
never published. One that passes is gated like an edit, at an edit's
outline limits — the base back outside the garment mask is kept pixel for
pixel — (the kind's gate against the base back) plus ``kind.back_reasons``
against the accepted front's record (the front opening on the back). The
composite's SUPPORT (every pixel it may have changed) is kept beside the
attempt as ``….try{n}.support.png`` (``support_path``) and handed to the
gate: the head share leaves it out (``garment_gates.worn_gate``), so a
collar or hood over the neck passes while a changed head elsewhere still
refuses. A stored attempt without one gets it made again from the stored
draft while that is the draft it was composited from (``draft_sha256``).

The draft's PROMPT is part of what a stored draft and a stored attempt are
reused under (Ruling A29: the draft prompt stopped naming the piece). An
attempt records the prompt its draft was made with (``draft_prompt``); a
REFUSED back reuses neither a stored draft nor a stored attempt made with
another prompt — they drew what the old text named, so they are never
composited or re-gated into passing — and drafts anew. An ACCEPTED back
stays as it is (its record names no prompt and is never re-judged by it),
and the boot re-make of a model fit (``stored_only``) keeps its stored draft.

An EMPTY composite (fix round 1: the draft lines up but nothing of the
piece shows from behind — a necklace, a front-only detail) is accepted
without the gate: the back IS the base back, sidecar ``composite:
"empty"``, gate record ``empty`` True. The steps after the drafted one have
no back then (``skipped_view``: no ghost back, no cut-out back — there is
no garment in it to cut out) and the mesh is made from the front cut-out
alone (``garment_mesh``; a mesh alias takes its back view as optional).
The chain had no "piece without a back" path before: this is it. Such a
group never serves as a ``garment_source`` (that needs both views of every
step), so a new base renders it again. A
refused attempt makes a new draft; after ``ATTEMPTS`` drafts the step is
refused with the composite's numbers. The accepted back records the front
it follows (``front_sha256``), its draft, ``fit: "composite"`` and the
composite's record; a new accepted front drops the back and everything
after it. Backs FITTED by the edit model before Task 11g keep their records
and stay accepted while they follow the front.

The piece rule differs from the outfit's dressed views (``view_composite.
RULES``): a single piece can be small — a belt measured a put-on region of
0.014 of the figure, a necklace 0.0055 (a live world copy, 2026-11-12), both
refused by the outfit rule's 0.03 — so the piece rule keeps every garment
component down to 30 px (no opening), scores the put-on at full resolution
with a smaller head share and no dilation, and accepts a region from 0.002
of the figure.

A step whose gate changed (``kind.GATE_VERSIONS``: clothing ``worn``,
``garment_gates.WORN_GATE_VERSION``, and ``ghost``,
``garment_gates.GHOST_GATE_VERSION``) RE-GATES its stored attempts before it
renders again (``_regate_stored``): when the view's final is not accepted,
every attempt file whose gate record is of an older version is gated again
from the file (masks only, no image job) — a drafted back only while the
attempt is a composite that passed its checks, made from the current front
(``front_sha256``; a stored model fit is never re-gated). Of those that
pass, the one NEAREST the worn piece is published like a fresh accepted
attempt (Ruling A37, ``garment_gates.attempt_distance`` in the worn region —
the ghost; the worn views have no worn piece to compare and take the first);
every judged attempt keeps its new record. Nothing passes: the step renders
as before. That runs on the next chain run of the piece and on the step's
Regenerate / Run all.

"USE THIS" (Ruling A37, ``use_attempt``): any stored attempt of an edit
step can be made the view's accepted image by hand — no render, no job.
A passing attempt is published as the chain publishes it; a refused one
is accepted BY THE USER (``user_accepted``), which holds only while the
file and every image it was made from are unchanged
(``garment_store.image_accept_holds``) and is never re-gated. An attempt
made from an image that is no longer the accepted one cannot be used
(``attempt_inputs``).
An ACCEPTED image of a step the kind names in ``REGATE_ACCEPTED_STEPS``
(clothing ``ghost``, Ruling A17 d) is re-gated from its file at the next
run when its record predates the gate (``regate_accepted``, called by the
run before it decides what is done); one the current gate refuses is stale
(``stale_accepted``): never done, rendered again — not reused.
A registered attempt is re-gated from the image AS RENDERED: its raw
sibling (``raw_path``, written before the registration rewrites the file),
or the file itself when no registration moved it — and registered again;
a file moved before raw siblings were kept (2026-11-12) is gated as stored.

HEM SNAP (Ruling A27): an attempt whose gate refuses it for the hem ALONE,
within ``garment_gates.HEM_SNAP_MAX`` (the kind's ``hem_snap``: clothing
``ghost``), is corrected on the CPU (``_snap_hem``) — its rows below the
underarm line rescaled so its hem meets the worn hem — and gated again in
full (the pair check too). Only a corrected image that passes is kept: the
attempt file is rewritten (the rendering kept as its raw sibling, like a
registration) and its record and sidecar carry ``hem_snap`` = ``{from, to,
scale, underarm}`` (the published final's sidecar too). A corrected image
that fails leaves the attempt as rendered, refused, its record noting
``hem_snap_refused``. The snap runs on fresh attempts, on stored attempts
judged again (``_regate_stored``: ghost gate version 5 re-judges what
version 4 refused, before any render) and on an accepted ghost re-gated
from its file (``regate_accepted``). ``rejudge_expected`` tells the
estimate and the failure cache (``garments``) — from the stored records
only — that a refused view will be accepted from a stored attempt.

The OPEN state of a closable clothing piece (ruling F15 i-1, fix round
T12-F1): an open jacket looks the same from behind as a closed one, and the
edit model split it open down the back when the back's text said "worn open"
(hub job c9e10d2b, 2026-11-12). So its BACK views are never rendered with
state words: an image step's back is COPIED from the closed state's accepted
back of that step (``closed_back``; 0 jobs; the copy's record names it under
``copied_from`` and follows it — ``_follows_front``), and without one it is
rendered with the CLOSED texts (``_back_profile``). The closed group itself
is left alone: a back drafted from the OPEN front never follows the closed
front, so it could not serve the closed state.

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
import re
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


def pad_into(rgb, mask, shape: Tuple[int, int]):
    """An image + mask moved into another view's frame of ``shape`` (h, w): both are crops of the same square
    edit canvas (side = max(w, h)), each centred horizontally, so the shift is the difference of the two centring
    offsets; a different height is scaled to ``shape`` first (pure scale). ``(rgb float32, mask bool)``."""
    import numpy as np
    hh, wh = int(shape[0]), int(shape[1])
    rgb = np.asarray(rgb, np.float32)
    mask = np.asarray(mask, bool)
    if rgb.shape[0] != hh:
        from PIL import Image
        f = hh / rgb.shape[0]
        size = (max(1, int(round(rgb.shape[1] * f))), hh)
        rgb = np.asarray(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize(
            size, Image.Resampling.LANCZOS), np.float32)
        mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize(
            size, Image.Resampling.BILINEAR)) >= 128
    wb = rgb.shape[1]
    side = max(hh, wh)
    shift = (side - wb) // 2 - (side - wh) // 2
    out_rgb = np.full((hh, wh, 3), 128.0, np.float32)
    out_mask = np.zeros((hh, wh), bool)
    x0, x1 = max(shift, 0), min(wh, shift + wb)
    if x1 > x0:
        out_rgb[:, x0:x1] = rgb[:, x0 - shift:x1 - shift, :3]
        out_mask[:, x0:x1] = mask[:, x0 - shift:x1 - shift]
    return out_rgb, out_mask


def kind_module(kind: str):
    """The module of a garment kind's image chain (``EDIT_STEPS``,
    ``edit_prompt``, ``gate``, ``position_reference``, ``SUBJECT``, ``REGATE_ACCEPTED_STEPS`` and the pair
    hooks ``PAIR_STEP``, ``pair_agree``, ``pair_reason``, ``pair_repair_reason``, ``pair_redo``,
    ``PAIR_REFUSED``, ``front_hints``).
    ValueError for a kind without one (hair, footwear)."""
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


#: The mask cache keeps at most this many files; a write beyond it deletes the oldest by mtime (a hit touches its
#: file, so "oldest" is the least recently used).
MASK_CACHE_MAX = 4000


def mask_cache_dir() -> Path:
    """Where ``_mask_image`` keeps its masks: ``<storage>/.cache/masks`` (``StorageNotInitialised`` without a
    storage root)."""
    from app.core import paths
    return paths.get_storage_dir() / ".cache" / "masks"


def _read_cached_mask(path: Path, size: Tuple[int, int]):
    """The cached L mask at ``path``, or None when it is missing or unreadable (a truncated file is re-matted)."""
    import os
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.load()
            if im.mode != "L" or im.size != tuple(size):
                return None
            mask = im.copy()
    except Exception:  # noqa: BLE001 — missing, truncated, not a PNG: re-matte
        return None
    try:
        os.utime(path)
    except OSError:
        pass
    return mask


def _write_cached_mask(path: Path, mask) -> None:
    """Write ``mask`` as an L PNG atomically (temp file + ``os.replace``), then trim the cache to
    ``MASK_CACHE_MAX`` files. A failed write only logs: the caller has its mask."""
    import os
    import threading
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(tmp, "PNG")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("Mask cache: could not write %s: %s", path.name, e)
        tmp.unlink(missing_ok=True)
        return
    try:
        entries = []
        for p in path.parent.glob("*.png"):
            try:
                entries.append((p.stat().st_mtime_ns, p))
            except OSError:
                pass
        excess = len(entries) - MASK_CACHE_MAX
        if excess > 0:
            for _mtime, p in sorted(entries)[:excess]:
                p.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Mask cache: trimming failed: %s", e)


def _matte(data: bytes, size: Tuple[int, int]):
    """BiRefNet-DIS mask of an encoded image as an L image of ``size`` (uncached)."""
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    raw = run_rembg(data, MESH_INPUT_REMBG_MODEL, only_mask=True)
    with Image.open(io.BytesIO(raw)) as im:
        mask = im.convert("L")
    if mask.size != tuple(size):
        mask = mask.resize(tuple(size), Image.Resampling.BILINEAR)
    return mask


def _mask_image(data: bytes, size: Tuple[int, int]):
    """BiRefNet-DIS mask of an encoded image as an L image of ``size``, cached by image hash: the key is
    ``sha256(data)`` + ``MESH_INPUT_REMBG_MODEL`` + ``w×h``, the file ``mask_cache_dir()/<key>.png`` (lossless L,
    so a hit is the very mask a miss returns). The fit's masks are those the ghost gate already matted.
    ``keyed_lock("mask_cache", key)`` is taken before the matte, so a second asker of the same image waits for
    the first and reads its file — a hit never queues on the process-wide rembg lock. Without a storage root the
    mask is matted uncached."""
    import hashlib
    from app.core import paths
    from app.core.keyed_lock import keyed_lock
    from app.models.character import MESH_INPUT_REMBG_MODEL
    w, h = (int(v) for v in size)
    try:
        folder = mask_cache_dir()
    except paths.StorageNotInitialised:
        return _matte(data, size)
    key = f"{hashlib.sha256(data).hexdigest()}_{MESH_INPUT_REMBG_MODEL}_{w}x{h}"
    path = folder / f"{key}.png"
    with keyed_lock("mask_cache", key):
        mask = _read_cached_mask(path, (w, h))
        if mask is not None:
            return mask
        mask = _matte(data, size)
        _write_cached_mask(path, mask)
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


#: Relative aspect difference below which a render counts as the canvas's (or
#: the source's) aspect: 686×1536 sent, 1376×3072 back is 0.3 % off.
ASPECT_TOLERANCE = 0.02


def crop_back_box(result: Tuple[int, int], side, offset: Tuple[int, int],
                  size: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int, int, int]]:
    """``(scaled size, (x0, y0, x1, y1))``: how a render of ``result`` (w, h)
    of the edit canvas ``side``² (or ``side`` = ``(w, h)``) is cut back to the
    source frame ``size`` placed at ``offset`` in that canvas — the render is
    first resized to ``scaled size``, then the box is cropped (it may reach
    past the scaled render's edges). By the render's aspect (within
    ``ASPECT_TOLERANCE``):

    - the CANVAS's (any size): a pure scale to the canvas, the box is the
      source frame at ``offset``;
    - the SOURCE's: the backend answered in the source's own frame (MiniMax /
      P-H3 answer 1376×3072 for a 686×1536 source) — a pure scale to
      ``size``, nothing cropped;
    - another: scaled UNIFORMLY to the canvas height and taken as centred on
      the canvas horizontally — never stretched (fix round T12-F1, ruling
      F14 g)."""
    cw, ch = (int(side[0]), int(side[1])) if isinstance(side, (tuple, list)) else (int(side), int(side))
    rw, rh = int(result[0]), int(result[1])
    sw, sh = int(size[0]), int(size[1])
    aspect = rw / float(rh)

    def near(w: int, h: int) -> bool:
        return abs(aspect / (w / float(h)) - 1.0) <= ASPECT_TOLERANCE
    if near(cw, ch):
        return (cw, ch), (int(offset[0]), int(offset[1]), int(offset[0]) + sw, int(offset[1]) + sh)
    if near(sw, sh):
        return (sw, sh), (0, 0, sw, sh)
    scaled = (max(1, round(rw * ch / float(rh))), ch)
    x0 = (scaled[0] - cw) // 2 + int(offset[0])
    y0 = int(offset[1])
    return scaled, (x0, y0, x0 + sw, y0 + sh)


def crop_back(path: Path, target: Path, side, offset: Tuple[int, int],
              size: Tuple[int, int]) -> Path:
    """The edit render cut back to the source frame, as PNG at ``target``
    (``crop_back_box``: scaled by the render's aspect, then the source's
    ``size`` cropped; what lies past the render's edge is neutral grey).
    Shared by every square-canvas edit — the garment chain, the beard and
    the outfit's dressed views (``base_body``, ``expression_regen.
    render_character_image(crop_back_to=…)``). The renderer's sidecar moves
    along."""
    from PIL import Image
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    scaled, box = crop_back_box(rgb.size, side, offset, size)
    if rgb.size != scaled:
        rgb = rgb.resize(scaled, Image.Resampling.LANCZOS)
    cropped = Image.new("RGB", (int(size[0]), int(size[1])), VIEW_REFERENCE_BACKGROUND)
    cropped.paste(rgb, (-box[0], -box[1]))
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


#: Why a view of an image step is not made (``skipped_view``).
EMPTY_BACK = "nothing of the piece shows from behind — no back image; the mesh is made from the front"


def support_path(path: Path) -> Path:
    """The support sibling of a composite attempt — ``….try{n}.support.png``
    (``view_composite.write_support``; module docstring)."""
    return path.with_name(f"{path.stem}.support.png")


def empty_back(character_name: str, item_id: str, fsig: str) -> bool:
    """Whether the accepted back of the kind's drafted step is an EMPTY
    composite (module docstring)."""
    from app.core import view_composite
    from app.core.garment_store import garment_path, read_record
    kind = _kind_module(item_id)
    for step in getattr(kind, "EDIT_STEPS", {}) or {}:
        if not _drafted(kind, step):
            continue
        path = garment_path(character_name, item_id, fsig, "image", step=step, view="back")
        if _accepted(path) and view_composite.is_empty(read_record(path.with_suffix(".json")).get("composite")):
            return True
    return False


def skipped_view(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Optional[str]:
    """``EMPTY_BACK`` for the back of an image step AFTER a drafted step whose
    back is EMPTY (``empty_back``): that view is not made. None otherwise."""
    from app.core.garment_store import image_steps
    if view != "back":
        return None
    kind = _kind_module(item_id)
    order = list(image_steps(_item_kind(item_id)))
    drafted = [i for i, s in enumerate(order) if _drafted(kind, s)]
    if not drafted or step not in order or order.index(step) <= drafted[0]:
        return None
    return EMPTY_BACK if empty_back(character_name, item_id, fsig) else None


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
    accepted front (``front_sha256`` of its record). A back COPIED from the
    closed state (``copied_from``, ruling F15 i-1) counts while the closed
    back is still that file and follows ITS front."""
    from app.core.base_body import file_sha256
    from app.core.garment_store import garment_path, read_record
    record = read_record(back.with_suffix(".json"))
    copied = record.get("copied_from")
    if isinstance(copied, dict):
        source_fsig = str(copied.get("fsig") or "")
        try:
            source = garment_path(character_name, item_id, source_fsig, "image", step=step, view="back")
        except ValueError:
            return False
        return (_accepted(source) and file_sha256(source) == copied.get("sha256")
                and (not _drafted(_kind_module(item_id), step)
                     or _follows_front(character_name, item_id, source_fsig, step, source)))
    front = garment_path(character_name, item_id, fsig, "image", step=step, view="front")
    sha = record.get("front_sha256")
    if record.get("fit") != "composite":
        return False  # Ruling C2: a model fit of before Task 11g is stale (``stale_model_fit``)
    return bool(sha) and _accepted(front) and sha == file_sha256(front)


def stale_model_fit(character_name: str, item_id: str, fsig: str, step: str, view: str) -> bool:
    """Whether the accepted ``view`` of ``step`` is a drafted back made by the
    MODEL fit of before Task 11g (Ruling C2, fix round 2): accepted, not a
    copy of the closed state's back (``copied_from``), no ``fit:
    "composite"``. Never counted as done (``garments``); re-made from its
    stored draft (``remake_model_fit_back``, once at boot) or rendered anew."""
    from app.core.garment_store import garment_path, read_record
    if view != "back" or not _drafted(_kind_module(item_id), step):
        return False
    path = garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    if not _accepted(path):
        return False
    record = read_record(path.with_suffix(".json"))
    return not isinstance(record.get("copied_from"), dict) and record.get("fit") != "composite"


def _open_state(character_name: str, item_id: str, profile: Dict[str, Any], state: Optional[str]) -> bool:
    """Whether a run of ``item_id`` is for the OPEN state of a closable clothing piece (``state``, None = the
    state ``profile`` wears it in)."""
    from app.core.garment_store import item_state
    from app.core.outfit_options import OPEN
    return item_state(character_name, item_id, profile, state) == OPEN


def _back_profile(item_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """The profile an open piece's BACK is rendered from: the piece CLOSED — no state words in the back's texts
    (ruling F15 i-1: from behind an open piece looks like a closed one)."""
    from app.core.outfit_options import CLOSED, with_item_state
    return with_item_state(profile, item_id, CLOSED)


def closed_back(character_name: str, item_id: str, step: str, *,
                profile: Dict[str, Any]) -> Optional[Tuple[str, Path]]:
    """``(closed fsig, back)``: the CLOSED state's accepted back image of ``step`` that the open state reuses
    (ruling F15 i-1) — accepted and, for a drafted step, following its closed front. None without one."""
    from app.core.garment_store import garment_fsig, garment_path
    from app.core.outfit_options import CLOSED
    if step not in getattr(_kind_module(item_id), "EDIT_STEPS", {}):
        return None
    try:
        fsig = garment_fsig(character_name, item_id, profile=profile, state=CLOSED)
    except ValueError:
        return None
    path = garment_path(character_name, item_id, fsig, "image", step=step, view="back")
    if not _accepted(path):
        return None
    if _drafted(_kind_module(item_id), step) and not _follows_front(character_name, item_id, fsig, step, path):
        return None
    return fsig, path


def _copy_closed_back(character_name: str, item_id: str, fsig: str, step: str, final: Path,
                      source: Tuple[str, Path]) -> Path:
    """The closed back ``source`` copied onto the open group's ``final`` with its record and ``copied_from``
    ``{fsig, state, sha256}``; a changed copy makes the later image steps of the back stale (``_drop_later``)."""
    from app.core.base_body import file_sha256
    from app.core.garment_store import read_record, write_record
    from app.core.outfit_options import CLOSED
    closed_fsig, path = source
    sha = file_sha256(path)
    if final.is_file() and file_sha256(final) == sha and _accepted(final):
        return final
    shutil.copyfile(path, final)
    write_record(final.with_suffix(".json"), {**read_record(path.with_suffix(".json")),
                                              "copied_from": {"fsig": closed_fsig, "state": CLOSED, "sha256": sha}})
    _drop_later(character_name, item_id, fsig, step, "back")
    logger.info("Garment %s %s back of %s: copied from the closed state (%s) — no render", character_name, step,
                item_id, closed_fsig)
    return final


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
    from app.core.garment_store import accepted_image
    return accepted_image(path)


def run_edit_step(character_name: str, item_id: str, fsig: str, step: str, view: str, *,
                  force: bool = False,
                  pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
                  prompt_hints: Optional[Dict[str, Any]] = None,
                  state: Optional[str] = None,
                  before_composite: Optional[Callable[[], None]] = None) -> Path:
    """Render, gate and store one edit step of one view; returns the final
    image ``images/{item}_{fsig}_{step}_{view}.png``.

    ``before_composite`` (the chain's base-view check, Ruling A20): called
    before every composite of a drafted back onto the base view; it raises
    to refuse with the true reason before anything is composited.

    ``state`` (plan 2026-11-12-unified-worn-pieces Task 11b): the open /
    closed state of the run's piece — the prompts read the profile with the
    piece in that state (``outfit_options.with_item_state``); None = the
    state it is worn in.

    ``pair_check`` (the orchestration's check against the OTHER view, e.g.
    the garment-only front against the accepted back's hem) gets every
    attempt's gate record; a reason it returns refuses that attempt like a
    gate reason does, so the check uses the attempts of this step.
    ``prompt_hints`` go to the kind's ``edit_prompt`` as keyword arguments;
    ``item_id`` always does.

    Cached: an accepted final of this fsig is returned unless ``force``.
    ``base_body.MissingInput`` when the base view or the source step's
    accepted image is missing; ``GateRefused`` after ``ATTEMPTS`` failed
    attempts (the attempt files and their gate records stay for the UI)."""
    from app.core import base_body, expression_regen
    from app.core.garment_store import garment_path, read_record, write_record
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    from app.models.character import get_character_profile

    final = garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    kind = _kind_module(item_id)
    drafted = view == "back" and _drafted(kind, step)
    copied = isinstance(read_record(final.with_suffix(".json")).get("copied_from"), dict)
    if not force and _accepted(final) and (
            not (drafted or copied) or _follows_front(character_name, item_id, fsig, step, final)):
        return final
    if step not in kind.EDIT_STEPS:
        raise ValueError(f"no edit step {step!r}")
    profile = get_character_profile(character_name) or {}
    if state is not None:
        from app.core.outfit_options import with_item_state
        profile = with_item_state(profile, item_id, state)
    if view == "back" and _open_state(character_name, item_id, profile, state):
        # Ruling F15 i-1: the open state's back is the closed one's — copied, or rendered from closed texts.
        source = None if force else closed_back(character_name, item_id, step, profile=profile)
        if source is not None:
            final.parent.mkdir(parents=True, exist_ok=True)
            return _copy_closed_back(character_name, item_id, fsig, step, final, source)
        profile = _back_profile(item_id, profile)
    bsig = base_body.base_signature(character_name, profile=profile)
    base = find_ref_image(character_name, base_body._kind(view), bsig)
    if base is None:
        raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
    refs_dir = get_model_refs_dir(character_name)
    final.parent.mkdir(parents=True, exist_ok=True)
    if drafted:
        return _drafted_back(character_name, item_id, fsig, step, kind, profile=profile, base=base, force=force,
                             refs_dir=refs_dir, final=final, pair_check=pair_check,
                             before_composite=before_composite)
    source_step = kind.EDIT_STEPS[step]["source"]
    if source_step == "base":
        source = base
    else:
        source = garment_path(character_name, item_id, fsig, "image", step=source_step, view=view)
        if not _accepted(source):
            raise base_body.MissingInput(f"The {source_step} {view} image is missing — run that step first")
    prompt, negative = kind.edit_prompt(character_name, step, view, profile=profile, item_id=item_id,
                                        **(prompt_hints or {}))

    base_size, gate_args, position = _gate_inputs(kind, step, base, source, refs_dir, item_id)

    def gate_file(path: Path) -> Dict[str, Any]:
        """Register the attempt file at ``path`` onto ``position`` (a step
        with one; ``_register`` rewrites the file and keeps the rendered
        bytes as its raw sibling) and gate it."""
        edit_rgb, edit_mask = _rgb(path, base_size), _mask(path, base_size)
        registration = None
        if position is not None:
            edit_rgb, edit_mask, registration = _register(kind, step, view, path, base_size, position,
                                                          gate_args=gate_args, edit_rgb=edit_rgb,
                                                          edit_mask=edit_mask)
        record = kind.gate(step, view, edit_rgb=edit_rgb, edit_mask=edit_mask, **gate_args)
        if registration is not None:
            record = _with_registration(record, registration)
        # Ruling A27: a hem-only refusal is snapped to the worn hem (and gated again in full).
        return _snap_hem(kind, step, view, path, base_size, gate_args, position, edit_mask, record, pair_check)

    if not _accepted(final):
        def regate(path: Path, old: Dict[str, Any]) -> Dict[str, Any]:
            raw = raw_path(path)
            moved = bool((old.get("registration") or {}).get("applied"))
            if position is not None and (raw.is_file() or not moved):
                # The file as rendered is at hand (its raw sibling, or the
                # file itself when nothing moved it): registered anew.
                if raw.is_file():
                    shutil.copyfile(raw, path)
                return _with_pair(gate_file(path), pair_check)
            mask = _mask(path, base_size)
            record = kind.gate(step, view, edit_rgb=_rgb(path, base_size), edit_mask=mask, **gate_args)
            # A file moved before raw siblings were kept stays as it is: its
            # correction stays recorded (``registered`` too: ``pair_agree``
            # reads it on a waistband back).
            record.update({k: old[k] for k in ("registration", "reg_shift", "reg_scale", "registered")
                           if k in old})
            record = _snap_hem(kind, step, view, path, base_size, gate_args, position, mask, record, pair_check)
            return _with_pair(record, pair_check)
        def closeness(path: Path) -> Optional[Dict[str, Any]]:
            # Ruling A37: the attempt as re-gated (registered) against the worn piece in its region.
            from app.core import garment_gates
            return garment_gates.attempt_distance(gate_args["source_rgb"], position, _rgb(path, base_size),
                                                  _mask(path, base_size))

        hit = _regate_stored(character_name, item_id, fsig, step, view, kind, final=final, regate=regate,
                             closeness=closeness if position is not None else None)
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
            path = crop_back(Path(path), target, side, offset, source_size)
            record = _with_pair(gate_file(path), pair_check)
        record["attempt"] = attempt
        records.append(record)
        if path is not None:
            sidecar = read_record(target.with_suffix(".json"))
            write_record(target.with_suffix(".json"), _attempt_sidecar(sidecar, record))
        logger.info("Garment %s %s %s attempt %d: %s %s", character_name, step, view, attempt,
                    "accepted" if record["ok"] else "refused", record.get("reasons") or "")
        if record["ok"]:
            return _publish(character_name, item_id, fsig, step, view, kind, target, final, records, attempt)
    raise GateRefused(step, view, records)


def _gate_inputs(kind, step: str, base: Path, source: Path, refs_dir: Path,
                 item_id: str) -> Tuple[Tuple[int, int], Dict[str, Any], Any]:
    """``(base size, gate arguments, position reference)`` of an edit step's
    gate: the base view flattened on neutral grey, its mask, the source's
    (when it is not the base) and the kind's ``position_reference``."""
    from app.core.model_refs import neutral_view_reference
    with neutral_view_reference(base, refs_dir) as flat_base:
        base_size = _image_size(flat_base)
        base_rgb = _rgb(flat_base)
        base_mask = _mask(flat_base, base_size)
    source_rgb = source_mask = None
    if source != base:
        source_rgb = _rgb(source, base_size)
        source_mask = _mask(source, base_size)
    position = (kind.position_reference(step, base_rgb=base_rgb, base_mask=base_mask,
                                        source_rgb=source_rgb, source_mask=source_mask)
                if source_rgb is not None else None)
    return base_size, {"base_rgb": base_rgb, "base_mask": base_mask, "source_rgb": source_rgb,
                       "source_mask": source_mask, "item_id": item_id}, position


def _stale_keys(kind, step: str) -> Tuple[str, ...]:
    """The record keys that make a re-gated accepted image of ``step`` stale
    (``kind.REGATE_ACCEPTED_STEPS``); () for a step that is not re-gated."""
    return tuple((getattr(kind, "REGATE_ACCEPTED_STEPS", None) or {}).get(step) or ())


def regate_accepted(character_name: str, item_id: str, fsig: str, step: str, view: str, *,
                    state: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Ruling A17 (d): gate the ACCEPTED image of ``view`` again when its
    gate record predates the step's gate version (``_stale_gate``) and the
    kind names the step in ``REGATE_ACCEPTED_STEPS`` (clothing ``ghost``).
    The file is gated as stored — it is the registered attempt, so it is
    not registered again; the old record's registration keys stay — and the
    new record (``regated_from`` = the old version) replaces the accepted
    one in its sidecar; ``accepted`` stays. A record refused by a rule the
    kind names for the step (clothing: ``hem_refused`` / ``look_refused``)
    makes the view stale (``stale_accepted``): the next run renders it again
    instead of reusing it; a refusal by an older rule is only recorded.
    Refused by its hem alone within the snap (Ruling A27, ``_snap_hem``) the
    final is snapped in place instead — it stays accepted, the sidecar names
    ``hem_snap`` and the view's later images go (``_drop_later``).
    Returns the new record, None when
    nothing was due (not accepted, a copy of the closed state's back, a
    current record, no accepted source). Reads files and masks only: never
    renders. ``state``: the run's open / closed state (``run_edit_step``)."""
    from app.core import base_body
    from app.core.garment_store import garment_path, read_record, write_record
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    from app.models.character import get_character_profile
    kind = _kind_module(item_id)
    if not _stale_keys(kind, step) or step not in kind.EDIT_STEPS:
        return None
    final = garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    if not _accepted(final):
        return None
    sidecar = read_record(final.with_suffix(".json"))
    if isinstance(sidecar.get("copied_from"), dict):
        return None  # the closed state's back: re-gated by the closed group's run
    if isinstance(sidecar.get("user_accepted"), dict):
        return None  # Ruling A37: taken by the user against its gate — never judged again
    try:
        ordinal = _ORDINALS[int(sidecar.get("attempt") or 1) - 1]
    except (IndexError, TypeError, ValueError):
        return None
    gates = sidecar.get("gates") or {}
    old = gates.get(ordinal)
    if not isinstance(old, dict) or old.get("empty") or not _stale_gate(kind, step, old):
        return None
    source_step = kind.EDIT_STEPS[step]["source"]
    if source_step == "base":
        return None  # an edit of the base view: nothing to regate against here
    source = garment_path(character_name, item_id, fsig, "image", step=source_step, view=view)
    if not _accepted(source):
        return None
    profile = get_character_profile(character_name) or {}
    if state is not None:
        from app.core.outfit_options import with_item_state
        profile = with_item_state(profile, item_id, state)
    if view == "back" and _open_state(character_name, item_id, profile, state):
        profile = _back_profile(item_id, profile)
    base = find_ref_image(character_name, base_body._kind(view),
                          base_body.base_signature(character_name, profile=profile))
    if base is None:
        return None
    base_size, gate_args, position = _gate_inputs(kind, step, base, source, get_model_refs_dir(character_name),
                                                  item_id)
    mask = _mask(final, base_size)
    record = kind.gate(step, view, edit_rgb=_rgb(final, base_size), edit_mask=mask, **gate_args)
    record.update({k: old[k] for k in ("registration", "reg_shift", "reg_scale", "registered") if k in old})
    # Ruling A27: refused by its hem alone -> the final itself snapped (no raw sibling beside a final); its
    # later images were made from the file as it was and go.
    record = _snap_hem(kind, step, view, final, base_size, gate_args, position, mask, record, None, keep_raw=False)
    record.update(attempt=old.get("attempt", sidecar.get("attempt")),
                  regated_from=int(old.get("gate_version") or 1))
    if record.get("hem_snap"):
        sidecar = {**sidecar, "hem_snap": record["hem_snap"]}
    write_record(final.with_suffix(".json"), {**sidecar, "gates": {**gates, ordinal: record}})
    if record.get("hem_snap"):
        _drop_later(character_name, item_id, fsig, step, view)
    stale = any(record.get(k) is True for k in _stale_keys(kind, step))
    logger.info("Garment %s %s %s (accepted) re-gated (gate version %s -> %s): %s %s", character_name, step, view,
                record["regated_from"], record.get("gate_version"),
                "stale — rendered again, not reused" if stale
                else "still accepted" if record.get("ok") else "kept (refused by an older rule only)",
                record.get("reasons") or "")
    return record


def stale_accepted(character_name: str, item_id: str, fsig: str, step: str, view: str) -> bool:
    """Whether the accepted ``view`` of ``step`` was re-gated
    (``regate_accepted``) and refused by a rule that makes it stale (the
    kind's keys for the step) — never counted as done (``garments``),
    rendered again, not reused (Ruling A17 d)."""
    keys = _stale_keys(_kind_module(item_id), step)
    if not keys:
        return False
    record = accepted_record(_final(character_name, item_id, fsig, step, view))
    return (isinstance(record, dict) and "regated_from" in record
            and any(record.get(k) is True for k in keys))


def _final(character_name: str, item_id: str, fsig: str, step: str, view: str) -> Path:
    from app.core.garment_store import garment_path
    return garment_path(character_name, item_id, fsig, "image", step=step, view=view)


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


def _attempt_sidecar(sidecar: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """An attempt's sidecar with its gate ``record`` — and the record's
    ``hem_snap`` (Ruling A27) as a sidecar key of its own, dropped when the
    record has none (``_publish`` carries the sidecar's keys to the final)."""
    out = {k: v for k, v in sidecar.items() if k != "hem_snap"}
    out["gate"] = record
    if record.get("hem_snap"):
        out["hem_snap"] = record["hem_snap"]
    return out


def _snap_hem(kind, step: str, view: str, path: Path, base_size: Tuple[int, int], gate_args: Dict[str, Any],
              region, edit_mask, record: Dict[str, Any],
              pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]], *,
              keep_raw: bool = True) -> Dict[str, Any]:
    """Ruling A27 (module docstring "HEM SNAP"): ``record`` when the kind
    snaps nothing for it (``kind.hem_snap`` None: not refused by the hem
    alone, beyond ``HEM_SNAP_MAX``, no underarm line). Else the image at
    ``path`` rescaled below the underarm line (``garment_gates.snap_rows``,
    in the file's own pixels) and gated again in full with ``pair_check``:
    passing, the file is rewritten (``keep_raw``: the rendering kept as its
    raw sibling first, unless one is there) and the new record, with
    ``hem_snap`` = ``{from, to, scale, underarm}`` and ``before_snap``, is
    returned; failing, the file stays and ``record`` is returned with
    ``hem_snap_refused`` (the snap and the corrected image's reasons).
    ``edit_mask`` is the mask the record was gated with (the registered
    one); ``region`` the step's position reference."""
    import numpy as np
    from PIL import Image
    from app.core import garment_gates
    snap_of = getattr(kind, "hem_snap", None)
    if snap_of is None or region is None:
        return record
    snap = snap_of(step, view, record, ghost_mask=edit_mask, region=region, base_mask=gate_args["base_mask"])
    if snap is None:
        return record
    info = {k: snap[k] for k in ("from", "to", "scale", "underarm")}
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"))
    tmp = path.with_name(f".{path.name}.snap.tmp")
    try:
        Image.fromarray(garment_gates.snap_rows(rgb, snap, factor=rgb.shape[0] / base_size[1])).save(
            tmp, format="PNG")
        snapped = kind.gate(step, view, edit_rgb=_rgb(tmp, base_size),
                            edit_mask=garment_gates.snap_rows(edit_mask, snap), **gate_args)
        snapped.update({k: record[k] for k in ("registration", "reg_shift", "reg_scale", "registered")
                        if k in record})
        snapped = _with_pair(snapped, pair_check)
        if not snapped.get("ok"):
            logger.info("Garment %s %s hem snap %s refused: %s", step, view, info, snapped.get("reasons"))
            return {**record, "hem_snap_refused": {**info, "reasons": snapped.get("reasons") or []}}
        raw = raw_path(path)
        if keep_raw and not raw.is_file():
            shutil.copyfile(path, raw)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    logger.info("Garment %s %s hem snapped to the worn hem: %s", step, view, info)
    return {**snapped, "hem_snap": info,
            "before_snap": {"hem_c": record.get("hem_c"), "reasons": record.get("reasons") or []}}


def rejudge_expected(character_name: str, item_id: str, fsig: str, step: str, view: str) -> bool:
    """Ruling A27: whether the next run takes ``view`` of ``step`` from a
    STORED attempt without a render — the view is not accepted and one of
    its attempts holds a gate record of an older gate version
    (``_stale_gate``: ``_regate_stored`` judges it again first) that the
    kind's ``hem_snap_due`` names: refused by its hem alone within
    ``HEM_SNAP_MAX``, so the snap is expected to pass it. Read from the
    sidecars only (no image, no write) — the estimate's and the failure
    cache's view (``garments``); the run itself decides on the images."""
    from app.core.garment_store import garment_path, read_record
    try:
        kind = _kind_module(item_id)
        due = getattr(kind, "hem_snap_due", None)
        if due is None or step not in getattr(kind, "EDIT_STEPS", {}):
            return False
        if _accepted(garment_path(character_name, item_id, fsig, "image", step=step, view=view)):
            return False
        for attempt in range(1, ATTEMPTS + 1):
            target = garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=attempt)
            if not target.is_file():
                continue
            old = read_record(target.with_suffix(".json")).get("gate")
            if isinstance(old, dict) and _stale_gate(kind, step, old) and due(step, old):
                return True
    except ValueError:
        return False
    return False


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
                   follow_keys: Sequence[str] = (),
                   closeness: Optional[Callable[[Path], Optional[Dict[str, Any]]]] = None) -> Optional[Path]:
    """Gate the stored attempt files of a refused view again (module
    docstring): every attempt whose gate record is stale (``_stale_gate``)
    and that ``keep`` accepts (its sidecar; a drafted back: fitted from the
    current front) gets ``regate(path, old record)`` as its new record —
    written into its sidecar, ``regated_from`` = the old version. Every
    stale attempt is judged; of those that pass, the NEAREST to the worn
    piece is published (Ruling A37: two passing ghost backs of Ylva's
    blouse, the first without the worn back's ruffle): ``closeness(path)``
    (``garment_gates.attempt_distance`` on the step's position reference —
    the ghost) scores each, the lowest ``score`` wins, a tie or a missing
    score keeps the attempt order; without ``closeness`` (a step with no
    worn piece to compare: the worn views) the first that passes wins. The
    winner is published (``_publish``; ``follow_keys`` of its sidecar go
    into the final's record, the scores under ``picked``) and returned; None
    when none passes or none is stale. Reads files and masks only: never
    renders."""
    from app.core.garment_store import garment_path, read_record, write_record
    records: List[Dict[str, Any]] = []
    passed: List[Tuple[int, Path, Dict[str, Any]]] = []
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
        sidecar = _attempt_sidecar(sidecar, record)
        write_record(target.with_suffix(".json"), sidecar)
        logger.info("Garment %s %s %s attempt %d re-gated (gate version %s -> %s): %s %s", character_name, step,
                    view, attempt, record["regated_from"], record.get("gate_version"),
                    "accepted" if record.get("ok") else "refused", record.get("reasons") or "")
        if record.get("ok"):
            passed.append((attempt, target, sidecar))
    if passed:
        attempt, target, sidecar = passed[0]
        extra = {k: sidecar[k] for k in follow_keys if k in sidecar}
        if closeness is not None and len(passed) > 1:
            scores = {n: closeness(path) for n, path, _s in passed}
            ranked = sorted(passed, key=lambda p: (scores[p[0]] is None,
                                                   (scores[p[0]] or {}).get("score", 0.0), p[0]))
            attempt, target, sidecar = ranked[0]
            extra = {k: sidecar[k] for k in follow_keys if k in sidecar}
            extra["picked"] = {"by": "nearest to the worn piece",
                               "scores": {str(n): score for n, score in scores.items()}}
            logger.info("Garment %s %s %s: %d stored attempts pass — attempt %d is nearest the worn piece %s",
                        character_name, step, view, len(passed), attempt, scores)
        return _publish(character_name, item_id, fsig, step, view, kind, target, final, records, attempt,
                        extra or None)
    if stale_any:
        logger.info("Garment %s %s %s: no stored attempt passes the current gate — rendering", character_name,
                    step, view)
    return None


# --- "Use this" (Ruling A37) ------------------------------------------------------

#: The sidecar keys a drafted back's attempt carries into its final (``_drafted_back``'s ``follow_keys``).
DRAFT_FOLLOW_KEYS = ("front_sha256", "draft", "draft_sha256", "draft_prompt", "fit", "composite", "composite_record")


#: Why a stored attempt cannot be used (``attempt_inputs``) — plain words the Wardrobe shows on its tile.
NO_ATTEMPTS = "This step keeps no attempts"
FRONT_NOT_ACCEPTED = "The front it was drafted from is not accepted"
EARLIER_FRONT = "Drafted from an earlier front"
SOURCE_NOT_ACCEPTED = "The image it was made from is not accepted"
EARLIER_SOURCE = "Made from an earlier image of the step before"


class AttemptUnusable(ValueError):
    """``use_attempt``: the stored attempt cannot be taken (none stored, made from an image that is no longer
    the accepted one, or a step without attempts)."""


def _made_before(sidecar: Dict[str, Any], source: Path) -> bool:
    """Whether an attempt (its sidecar's ``created_at``) was rendered before the accepted ``source`` image it
    edits was made (that final's ``created_at``): it was made from an earlier source. False when either time
    is unknown."""
    from app.core.garment_store import read_record
    from app.core.timeutils import parse_iso
    made, src = sidecar.get("created_at"), read_record(source.with_suffix(".json")).get("created_at")
    if not made or not src:
        return False
    try:
        return parse_iso(str(made)) < parse_iso(str(src))
    except (TypeError, ValueError):
        return False


def attempt_inputs(character_name: str, item_id: str, fsig: str, step: str, view: str,
                   sidecar: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    """``(why not, inputs)`` of a stored attempt of ``view`` of edit ``step`` (Ruling A37): ``why not`` is ""
    when the attempt may be used — it was made from the images accepted now — else the plain reason; ``inputs``
    the images it was made from, ``{file name: sha256}`` (none for an edit of the base view: the base is part of
    the fsig). A drafted back follows the front its draft was made from (``front_sha256``) and must be a
    composite; another edit reads the source step's accepted image of the view and must not be older than it."""
    from app.core.base_body import file_sha256
    from app.core.garment_store import garment_path
    kind = _kind_module(item_id)
    spec = (getattr(kind, "EDIT_STEPS", {}) or {}).get(step)
    if spec is None:
        return NO_ATTEMPTS, {}
    if view == "back" and _drafted(kind, step):
        front = garment_path(character_name, item_id, fsig, "image", step=step, view="front")
        if not _accepted(front):
            return FRONT_NOT_ACCEPTED, {}
        sha = file_sha256(front)
        if sidecar.get("front_sha256") != sha or sidecar.get("fit") != "composite":
            return EARLIER_FRONT, {}
        return "", {front.name: sha}
    source_step = spec.get("source")
    if source_step in (None, "base"):
        return "", {}
    source = garment_path(character_name, item_id, fsig, "image", step=source_step, view=view)
    if not _accepted(source):
        return SOURCE_NOT_ACCEPTED, {}
    if _made_before(sidecar, source):
        return EARLIER_SOURCE, {}
    return "", {source.name: file_sha256(source)}


def use_attempt(character_name: str, item_id: str, fsig: str, step: str, view: str, attempt: int) -> Dict[str, Any]:
    """Ruling A37, "Use this": publish the stored ``attempt`` of ``view`` of edit ``step`` as the view's
    accepted image — no render, no job. A PASSING attempt (its gate record ``ok``) is published like the chain
    publishes it; a REFUSED one is published accepted by the user: its record carries ``user_accepted {at,
    attempt, attempt_sha256, inputs, reasons, gate_version}`` and holds only while the file and every input are
    unchanged (``garment_store.image_accept_holds``). Either way the later images of the view go
    (``_publish``: a new front of a drafted step drops its back too); the caller drops the mesh. ``{changed,
    passing, user_accepted}`` — ``changed`` False when that attempt is the accepted image already.
    ``AttemptUnusable`` when it cannot be taken (``attempt_inputs``). The caller holds the item's run lock."""
    from app.core.base_body import file_sha256
    from app.core.garment_store import garment_path, read_record
    from app.core.timeutils import utc_now_iso
    kind = _kind_module(item_id)
    if step not in (getattr(kind, "EDIT_STEPS", {}) or {}):
        raise AttemptUnusable(NO_ATTEMPTS)
    if attempt not in range(1, ATTEMPTS + 1):
        raise AttemptUnusable(f"No attempt {attempt} (1..{ATTEMPTS})")
    target = garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=attempt)
    if not target.is_file():
        raise AttemptUnusable(f"No stored attempt {attempt} of the {step} {view}")
    sidecar = read_record(target.with_suffix(".json"))
    gate = sidecar.get("gate") if isinstance(sidecar.get("gate"), dict) else None
    passing = bool(gate and gate.get("ok") is True)
    final = garment_path(character_name, item_id, fsig, "image", step=step, view=view)
    current = read_record(final.with_suffix(".json"))
    if (_accepted(final) and int(current.get("attempt") or 0) == attempt
            and file_sha256(final) == file_sha256(target)):
        return {"changed": False, "passing": passing, "user_accepted": isinstance(current.get("user_accepted"), dict)}
    why, inputs = attempt_inputs(character_name, item_id, fsig, step, view, sidecar)
    if why:
        raise AttemptUnusable(why)
    records: List[Dict[str, Any]] = []
    for n in range(1, ATTEMPTS + 1):
        other = garment_path(character_name, item_id, fsig, "image", step=step, view=view, attempt=n)
        rec = read_record(other.with_suffix(".json")).get("gate") if other.is_file() else None
        records.append(rec if isinstance(rec, dict) else
                       {"view": view, "ok": False, "reasons": ["no stored attempt"], "attempt": n})
    extra: Dict[str, Any] = {}
    if view == "back" and _drafted(kind, step):
        extra.update({k: sidecar[k] for k in DRAFT_FOLLOW_KEYS if k in sidecar})
    extra["used_by_hand"] = {"at": utc_now_iso(), "attempt": attempt}
    if not passing:
        extra["user_accepted"] = {
            "at": utc_now_iso(), "attempt": attempt, "attempt_sha256": file_sha256(target), "inputs": inputs,
            "reasons": list((gate or {}).get("reasons") or ["no gate record"]),
            "gate_version": (gate or {}).get("gate_version")}
    final.parent.mkdir(parents=True, exist_ok=True)
    _publish(character_name, item_id, fsig, step, view, kind, target, final, records, attempt, extra)
    logger.info("Garment %s %s %s of %s: attempt %d used by hand (%s)", character_name, step, view, item_id,
                attempt, "passing" if passing else "refused — accepted by the user")
    return {"changed": True, "passing": passing, "user_accepted": not passing}


#: The gate numbers a registration corrects; after it they are the residual.
POSITION_KEYS = ("top_dy", "centre_dx", "w_ratio")


def raw_path(path: Path) -> Path:
    """The raw sibling of an attempt file — ``….try{n}.raw.png``: the bytes
    as rendered, kept while the attempt file itself holds the registered
    (moved) image, so a re-gate registers from the rendering again
    (``run_edit_step``) instead of from an earlier registration's result.
    Kai's "Jeans" back (2026-11-12) was rewritten as a 20 px jeans by a
    failed waistband estimate and could never pass again."""
    return path.with_name(f"{path.stem}.raw.png")


def _register(kind, step: str, view: str, path: Path, base_size: Tuple[int, int], reference, *,
              gate_args: Dict[str, Any], edit_rgb, edit_mask) -> Tuple[Any, Any, Optional[Dict[str, Any]]]:
    """Register an attempt of a step with a ``position_reference`` (the
    ghost) onto that reference (the kind's ``register_estimate``, else
    ``garment_gates.register``) BEFORE its gate: within the caps and not
    negligible, the attempt file at ``path`` is
    rewritten moved (``garment_gates.warp``, in the file's own pixels) — the
    cut-out, the mesh views and the fit's framing all read that file — and
    the returned arrays are the moved image (re-read) and the moved mask.
    Returns ``(edit_rgb, edit_mask, registration)``; the registration
    record carries the estimate, ``applied``, a ``note`` when not applied,
    and ``before`` = the position numbers of the image as rendered. None
    when nothing can be estimated (no figure, empty masks). The rendered
    bytes are kept as ``raw_path`` before the file is rewritten; a raw
    sibling left from an earlier rendering goes whenever the file stays as
    it is (it is then its own raw)."""
    import numpy as np
    from PIL import Image
    from app.core import garment_gates
    raw = raw_path(path)
    zones = garment_gates._zones(gate_args["base_mask"])
    if zones is None or zones[1] <= 0:
        raw.unlink(missing_ok=True)
        return edit_rgb, edit_mask, None
    estimate_of = getattr(kind, "register_estimate", None)
    estimate = (estimate_of(step, view, reference, edit_mask, body_h=zones[1], item_id=gate_args.get("item_id"))
                if estimate_of is not None else garment_gates.register(reference, edit_mask, body_h=zones[1]))
    if estimate is None:
        raw.unlink(missing_ok=True)
        return edit_rgb, edit_mask, None
    before = kind.gate(step, view, edit_rgb=edit_rgb, edit_mask=edit_mask, **gate_args)
    applied = estimate["within_caps"] and not estimate["negligible"]
    info: Dict[str, Any] = {**estimate, "applied": applied,
                            "before": {k: before.get(k) for k in (*POSITION_KEYS, "ok")}}
    if not applied:
        info["note"] = ("negligible" if estimate["within_caps"]
                        else "beyond the correction caps — gated as rendered")
        raw.unlink(missing_ok=True)
        return edit_rgb, edit_mask, info
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"))
    factor = (rgb.shape[0] / base_size[1], rgb.shape[1] / base_size[0])
    shutil.copyfile(path, raw)
    tmp = path.with_name(f".{path.name}.tmp")
    Image.fromarray(garment_gates.warp(rgb, estimate, factor=factor)).save(tmp, format="PNG")
    tmp.replace(path)
    return _rgb(path, base_size), garment_gates.warp(edit_mask, estimate), info


def _with_registration(record: Dict[str, Any], registration: Dict[str, Any]) -> Dict[str, Any]:
    """The gate record with its registration: ``registration`` (+ the
    ``residual`` = the record's position numbers) and the chip keys
    ``reg_shift`` (|centroid shift| / Hb) and ``reg_scale``. A waistband
    registration (``garment_gates.register_waistband``) has no
    chip keys — their chips show the outline registration's caps — but
    ``registered`` = ``{scale, dx, dy, length_ratio}`` (dx / dy in px of the
    gate frame) when it was applied."""
    residual = {k: record.get(k) for k in POSITION_KEYS}
    out = {**record, "registration": {**registration, "residual": residual}}
    if registration.get("method") != "waistband":
        return {**out, "reg_shift": registration.get("shift_abs"), "reg_scale": registration.get("scale")}
    if registration.get("applied"):
        dy, dx = registration.get("shift_px") or (None, None)
        out["registered"] = {"scale": registration.get("scale"), "dx": dx, "dy": dy,
                             "length_ratio": registration.get("length_ratio")}
    return out


class StoredDraftUnusable(RuntimeError):
    """``_drafted_back(stored_only=True)``: no stored draft made from the current front, or its composite
    did not pass — a new draft (a hub job) would be needed."""


def _drafted_back(character_name: str, item_id: str, fsig: str, step: str, kind, *,
                  profile: Dict[str, Any], base: Path, refs_dir: Path, final: Path,
                  pair_check: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
                  stored_only: bool = False, force: bool = False,
                  before_composite: Optional[Callable[[], None]] = None) -> Path:
    """The back of a drafted step (module docstring): up to ``ATTEMPTS``
    DRAFTs from the accepted front, each COMPOSITED onto the base back on the
    CPU (``view_composite``, rule "piece") and — when the composite passes
    its checks — gated (the kind's gate against the base back +
    ``kind.back_reasons`` against the front's accepted record). A composite
    that fails its checks is refused without a gate and makes a new draft.
    ``MissingInput`` without an accepted front, ``RuntimeError`` when a draft
    renders nothing, ``GateRefused`` after the drafts (the records carry the
    composite's numbers).

    The STORED draft comes first (Ruling C2, fix round 2): while it was made
    from the current front (its sidecar's ``front_sha256``) it is composited
    again as attempt 1 — no hub job — and only when that fails is ONE new
    draft rendered (attempt 2). ``stored_only`` (the boot re-make of a model
    fit, ``remake_model_fit_back``): never renders — ``StoredDraftUnusable``
    instead. ``before_composite`` (Ruling A20) runs before every composite
    and refuses (raises) when the base view changed meanwhile."""
    from app.core import base_body, view_composite
    from app.core.base_body import file_sha256
    from app.core.garment_store import garment_path, read_record, write_record
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND, _tpose_size, neutral_view_reference
    from app.core.timeutils import utc_now_iso
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

    def gate_composite(path: Path, support) -> Dict[str, Any]:
        record = kind.gate(step, "back", base_rgb=base_rgb, base_mask=base_mask, source_rgb=None, source_mask=None,
                           edit_rgb=_rgb(path, base_size), edit_mask=_mask(path, base_size),
                           item_id=item_id, front_gate=front_gate, composite_support=support)
        return _with_pair(record, pair_check, list(kind.back_reasons(front_gate, record)))

    def empty_record() -> Dict[str, Any]:
        # The base back unchanged: nothing to gate (module docstring).
        return {"view": "back", "ok": True, "reasons": [], "empty": True,
                "gate_version": (getattr(kind, "GATE_VERSIONS", None) or {}).get(step)}

    def support_of(path: Path, sidecar: Dict[str, Any]):
        """The support of a stored attempt (module docstring); None: every head pixel counts."""
        stored = view_composite.read_support(support_path(path), base_size)
        if stored is not None:
            return stored
        draft = draft_path(character_name, item_id, fsig, step)
        if not sidecar.get("draft_sha256") or not draft.is_file() or file_sha256(draft) != sidecar["draft_sha256"]:
            return None
        view_composite.write_support(view_composite.support_mask(base, draft, rule="piece"), support_path(path))
        return view_composite.read_support(support_path(path), base_size)

    def regate_attempt(path: Path) -> Dict[str, Any]:
        sidecar = read_record(path.with_suffix(".json"))
        if view_composite.is_empty(sidecar.get("composite")):
            return empty_record()
        return gate_composite(path, support_of(path, sidecar))

    def composite_ok(sidecar: Dict[str, Any]) -> bool:
        composite = sidecar.get("composite")
        return sidecar.get("fit") == "composite" and (
            view_composite.is_empty(composite) or (isinstance(composite, dict) and composite.get("ok") is True))

    current_prompt: List[Optional[str]] = []

    def draft_text() -> Optional[str]:
        """The prompt a new draft is made with now (None: the piece has no text to draft it)."""
        if not current_prompt:
            try:
                current_prompt.append(kind.draft_prompt(character_name, step, profile=profile, item_id=item_id)[0])
            except ValueError:
                current_prompt.append(None)
        return current_prompt[0]

    def made_with_current_prompt(prompt: Any) -> bool:
        """Ruling A29: whether a stored draft / attempt was drafted with today's draft prompt."""
        return bool(prompt) and prompt == draft_text()

    if not (_accepted(final) and _follows_front(character_name, item_id, fsig, step, final)):
        # Only a stored COMPOSITE that passed its checks is re-gated — never a
        # model fit of before Task 11g, never a refused composite, never one
        # whose draft was made with another prompt (Ruling A29).
        hit = _regate_stored(character_name, item_id, fsig, step, "back", kind, final=final,
                             regate=lambda path, _old: regate_attempt(path),
                             keep=lambda sidecar: (sidecar.get("front_sha256") == front_sha and composite_ok(sidecar)
                                                   and made_with_current_prompt(sidecar.get("draft_prompt"))),
                             follow_keys=DRAFT_FOLLOW_KEYS)
        if hit is not None:
            return hit

    # The render arguments of the outfit's draft, nothing worn on the
    # profile (the reference shows the piece; the text never names it, Ruling A29).
    mesh_profile = {**profile, "equipped_pieces": {}, "equipped_items": []}
    # ``raise_load``: the draft is a garment step — load is retry_later,
    # never a refusal record (the outfit's own dressed views keep their
    # None-on-failure contract).
    common = {**base_body._dress_common("back", pieces={}, items=[], profile=mesh_profile, size=_tpose_size()),
              "raise_load": True}
    draft_stem = draft_path(character_name, item_id, fsig, step).with_suffix("")
    stored = draft_path(character_name, item_id, fsig, step)
    # ``force`` (Regenerate): a new draft, never the stored one again. Ruling A29: a stored draft made with
    # another prompt is not composited again — except by the boot re-make (``stored_only``) of an ACCEPTED back.
    stored_record = read_record(stored.with_suffix(".json")) if stored.is_file() else {}
    reuse = (not force and stored.is_file() and stored_record.get("front_sha256") == front_sha
             and (stored_only or made_with_current_prompt(stored_record.get("prompt"))))
    if stored_only and not reuse:
        raise StoredDraftUnusable(f"The {step} back has no stored draft made from the current front")
    records: List[Dict[str, Any]] = []
    for attempt in range(1, ATTEMPTS + 1):
        if attempt == 1 and reuse:
            draft = stored   # Ruling C2: the stored draft of this front, composited again — no hub job
            drafted_with = stored_record.get("prompt")
        elif stored_only:
            raise StoredDraftUnusable(f"The composite of the stored {step} back draft did not pass: "
                                      + "; ".join(str(r) for r in (records[-1].get("reasons") or [])))
        else:
            # Every new attempt drafts into the one draft file: the stored
            # draft is the one the last attempt was composited from.
            prompt = kind.draft_prompt(character_name, step, profile=profile, item_id=item_id)
            drafted_with = prompt[0]
            draft = base_body.render_draft(
                character_name, "back", stem=draft_stem, front=front, refs_dir=refs_dir, prompt=prompt,
                profile=profile, common=common,
                sidecar_extra={"garment": {**meta, "attempt": attempt, "stage": "draft"},
                               "front_sha256": front_sha})
        if draft is None:
            raise RuntimeError(f"The {step} back draft rendered nothing")
        draft = Path(draft)
        target = garment_path(character_name, item_id, fsig, "image", step=step, view="back", attempt=attempt)
        if before_composite is not None:
            before_composite()   # Ruling A20: never a composite onto a base view rendered again meanwhile
        composite = view_composite.compose(base, draft, target, rule="piece", background=VIEW_REFERENCE_BACKGROUND,
                                           mask_target=support_path(target))
        follow = {"front_sha256": front_sha, "draft": draft.name, "draft_sha256": file_sha256(draft),
                  **({"draft_prompt": drafted_with} if drafted_with else {}),
                  **view_composite.sidecar_fields(composite)}
        if composite["ok"] and view_composite.is_empty(composite):
            record = empty_record()
        elif composite["ok"]:
            record = gate_composite(target, view_composite.read_support(support_path(target), base_size))
        else:
            # Refused without a gate: the numbers go into the refusal text.
            record = {"view": "back", "ok": False,
                      "reasons": [f"composite refused — {view_composite.summary(composite)}"]}
        record.update(attempt=attempt, composite=view_composite.summary(composite))
        records.append(record)
        write_record(target.with_suffix(".json"), {
            "garment": {**meta, "attempt": attempt, "stage": "composite"}, **follow,
            "base_image_sha256": file_sha256(base), "created_at": utc_now_iso(), "gate": record})
        logger.info("Garment %s %s back (draft + composite) attempt %d: %s %s", character_name, step, attempt,
                    "accepted" if record["ok"] else "refused", record.get("reasons") or "")
        if record["ok"]:
            return _publish(character_name, item_id, fsig, step, "back", kind, target, final, records,
                            attempt, follow)
    raise GateRefused(step, "back", records)


def cut_out(character_name: str, item_id: str, fsig: str, view: str, *, force: bool = False) -> Path:
    """The generator input of one view, ``images/{item}_{fsig}_cutout_{view}.png``
    (R6), from the accepted ghost image (garment-only).

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


#: A final back image of an image step: ``{item}_{fsig}_{step}_back.png``.
_FINAL_BACK_RE = re.compile(r"(?P<item>[A-Za-z0-9][A-Za-z0-9_-]*)_(?P<fsig>[0-9a-f]{12})_(?P<step>[a-z]+)_back\.png")


def remake_model_fit_back(character_name: str, item_id: str, fsig: str, step: str) -> str:
    """Re-make ONE accepted worn back that the MODEL fit made (``stale_model_fit``;
    Ruling C2, ``model_fit_remake``): the stored draft of the current front composited
    again and gated (``_drafted_back(stored_only=True)`` — never a render) onto the base
    back the group was made on (its base copy, ``garment_source.base_copy``; the
    character's current base back for a group without one). ``"remade"``, or
    ``"removed: <why>"``: the back and the later back steps are dropped
    (``_drop_later``) and the chain renders them on its next run. ``"current"`` when it
    is no stale model fit. A MATERIALISED back (``copied_from`` the source fsig,
    ``garment_source.materialize``) has no draft of its own: ``_remake_copy``."""
    from app.core import base_body, garment_source
    from app.core.garment_store import garment_path, read_record
    from app.core.model_refs import find_ref_image, get_model_refs_dir
    from app.models.character import get_character_profile
    if not stale_model_fit(character_name, item_id, fsig, step, "back"):
        return "current"
    final = garment_path(character_name, item_id, fsig, "image", step=step, view="back")
    copied = read_record(final.with_suffix(".json")).get("copied_from")
    if isinstance(copied, str) and copied:
        return _remake_copy(character_name, item_id, fsig, step, copied)
    try:
        profile = get_character_profile(character_name) or {}
        base = garment_source.base_copy(character_name, item_id, fsig, "back")
        if not base.is_file():
            base = find_ref_image(character_name, base_body._kind("back"),
                                  base_body.base_signature(character_name, profile=profile))
        if base is None:
            raise base_body.MissingInput(base_body.BASE_IMAGES_MISSING)
        _drafted_back(character_name, item_id, fsig, step, _kind_module(item_id), profile=profile, base=base,
                      refs_dir=get_model_refs_dir(character_name), final=final, stored_only=True)
        return "remade"
    except Exception as e:  # noqa: BLE001 — the stale back never stays
        _drop_later(character_name, item_id, fsig, step, "back", inclusive=True)
        return f"removed: {e}"


def _remake_copy(character_name: str, item_id: str, fsig: str, step: str, source_fsig: str) -> str:
    """A materialised stale back (``remake_model_fit_back``): copied again from its source group's back once
    that is re-made (a composite — the copy keeps ``copied_from`` like ``garment_source.materialize``; the
    later back steps of the copy go stale), else dropped with the later back steps like any refused re-make."""
    from app.core.garment_store import garment_path, read_record, write_record
    final = garment_path(character_name, item_id, fsig, "image", step=step, view="back")
    try:
        source = garment_path(character_name, item_id, source_fsig, "image", step=step, view="back")
    except ValueError:
        source = None
    if source is None or not _accepted(source) or stale_model_fit(character_name, item_id, source_fsig, step,
                                                                  "back"):
        _drop_later(character_name, item_id, fsig, step, "back", inclusive=True)
        return f"removed: its source back ({source_fsig}) was not re-made"
    shutil.copyfile(source, final)
    write_record(final.with_suffix(".json"), {**read_record(source.with_suffix(".json")), "copied_from": source_fsig})
    _drop_later(character_name, item_id, fsig, step, "back")
    return "remade"


def remake_model_fit_backs(character_name: str) -> Dict[str, str]:
    """``remake_model_fit_back`` of every stale worn back of the character: ``{file: outcome}``.
    Under the character's garment run lock (``garment_store.char_lock``): no chain run of the
    character changes its files meanwhile; each back under its item's run lock too
    (``garment_store.run_item_lock``): a CPU refit beside the chain FIFO (Ruling A30) holds only that one."""
    from app.core.garment_store import PART_DIRS, char_lock, garments_dir
    folder = garments_dir(character_name) / PART_DIRS["image"]
    out: Dict[str, str] = {}
    if not folder.is_dir():
        return out
    with char_lock(character_name):
        return _remake_backs_locked(character_name, folder, out)


def _remake_backs_locked(character_name: str, folder: Path, out: Dict[str, str]) -> Dict[str, str]:
    from app.core.garment_store import read_record, run_item_lock

    def materialised(path: Path) -> bool:
        return isinstance(read_record(path.with_suffix(".json")).get("copied_from"), str)
    # The rendered backs first: a materialised copy follows its source group's re-made back (``_remake_copy``).
    for path in sorted(folder.iterdir(), key=lambda p: (materialised(p), p.name)):
        match = _FINAL_BACK_RE.fullmatch(path.name)
        if match is None:
            continue
        try:
            with run_item_lock(character_name, match.group("item")):
                outcome = remake_model_fit_back(character_name, match.group("item"), match.group("fsig"),
                                                match.group("step"))
        except Exception as e:  # noqa: BLE001 — e.g. an item of an unknown kind: left as it is
            logger.warning("Model fit back %s of %s not re-made: %s", path.name, character_name, e)
            continue
        if outcome != "current":
            out[path.name] = outcome
    return out
