"""Which way the figure of a side view faces — and the CPU mirror that turns it round (Ruling A91).

CONVENTION. The ``left`` view shows the figure's LEFT flank, so the figure faces the LEFT edge of the image; the
``right`` view faces the RIGHT edge. Everything that makes or reads a side view says the same:

* the prompts — ``model_refs.TPOSE_SIDE_PROMPT_TEMPLATE`` ("in profile facing the {side} edge of the frame"),
  ``base_body.DRESS_VIEW``, the animal main render (``model_refs.ANIMAL_POSE_PROMPT_DEFAULT``: "facing the left
  edge of the frame, left flank facing the camera" — handed to a multi-view mesher as its ``left`` view,
  ``openai_mesh.mesh_slot_views``) and the animal ``right`` view ("facing the right edge");
* the body-retexture worker that paints the dressed views onto the mesh (ComfyUI-GLB-Body-Retexture
  ``body_core.VIEW_YAW_OFFSETS``: ``left`` = yaw +90°, "the camera of ``left`` looks at the character's own left
  side", glTF +X; its orthographic projection puts the character's front, +Z, at the image's LEFT edge);
* the stored views: 57 of the 59 side views of a live world copy (2026-11-15, hand-labelled) follow it — the
  two that do not are one character's right view (it faces left like her left view) and none else.

A view that faces the wrong way hands the mesher two identical profiles (or a profile seen from behind the
mirror) and the worker paints the near flank onto the far one.

THE DETECTOR (``measure``) is pure CPU on the view's alpha matte (every mesh-input view is matted): the TOES. In
the bottom ``FOOT_BAND`` of the figure every connected part (a foot, both feet overlapping, a paw pair) is split
into its upper rows (the leg above the ankle) and its lowest rows (the sole); the sole reaches much further
forward of the leg than behind it, heel or high heel included. ``score`` is that reach balance, weighted by the
parts' areas: > 0 the figure faces image-right, < 0 image-left. Measured on the 59 stored side views (see
``scripts/smoke_view_facing.py`` for the table): every one signed right, ``|score|`` 0.17 .. 0.71, 0.30 or more
on 56 of them; the arms (held forward, backward or hanging), long hair, dresses to the knee, boots, sandals,
high heels and a four-legged animal did not move it. The head and the torso were measured as well and dropped:
hair behind the head reverses the head's balance, the arms cover the chest. ``confidence`` grows with
``|score|`` up to ``SCORE_FULL`` and halves when one part points the other way (a stride).

What a view's state is (``tile_state``): ``ok`` / ``wrong`` from ``AUTO_CONFIDENCE`` on, else ``unsure`` (also a
view that cannot be measured — no matte, no feet in the frame, a gown to the floor). Only a confident ``wrong``
is mirrored on its own (``auto_correct``, right after the render of a base side view, an off-pipeline side
view or a dressed side view's draft); an unsure view stays as it is and the tile asks the user to look.

THE MIRROR (``toggle_mirror``) flips the stored file in place — 0 image jobs — and records it in the sidecar
(``mirrored``: ``{auto, reason, confidence, at, original_sha256, mirrored_sha256}``); the original bytes stay
in ``model_refs/mirrored/<file name>`` (``MIRROR_DIR``, collected with their signature like the drafts), so a
second toggle restores them byte for byte. The sidecar's ``created_at`` and prompt fingerprint are left
alone: a base view's freshness (older than the front? older prompts?) is the same after its mirror — the view
is not rendered again — while every reader of its CONTENT (the base model's ``view_images_sha256``, a dressed
view's ``base_image_sha256``, a painted body's view shas) sees the new bytes and follows. ``mirror_changed_at``
says when the content last changed by a mirror (``model_overview.dressed_changed``)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("view_facing")

#: The side views and the image edge each must face.
EXPECTED = {"left": "left", "right": "right"}
SIDE_VIEWS = tuple(EXPECTED)

#: Bottom share of the figure height the feet are looked for in.
FOOT_BAND = 0.12
#: Share of a foot part's own rows that is its leg (top) and its sole (bottom).
LEG_ROWS = 0.3
SOLE_ROWS = 0.3
#: A part smaller than this share of height² is noise (a shadow speck, a strap end).
MIN_PART_AREA = 0.0004
#: A part flatter than this share of the figure height is no foot (a toe tip cut off by the band).
MIN_PART_HEIGHT = 0.03
#: The figure must be at least this tall in pixels to be measured.
MIN_FIGURE_PX = 120
#: ``|score|`` that counts as full confidence.
SCORE_FULL = 0.4
#: A part pointing the other way by at least this much halves the confidence.
DISAGREE_PART = 0.15
#: From this confidence on a view's direction is taken as known: ``ok`` / ``wrong``, and a wrong one is
#: mirrored automatically (``|score|`` 0.30 at ``SCORE_FULL`` 0.4).
AUTO_CONFIDENCE = 0.75
#: Both side views measured at least this sure and facing the same edge: one of them is wrong.
SAME_CONFIDENCE = 0.5

#: Subfolder of ``model_refs`` that keeps a mirrored view's original bytes.
MIRROR_DIR = "mirrored"

OK = "ok"
WRONG = "wrong"
UNSURE = "unsure"


def side_view(kind_or_view: str) -> str:
    """``left`` / ``right`` for a side view name or a ref kind (``tpose_left``), else ""."""
    name = str(kind_or_view or "")
    if name.startswith("tpose_"):
        name = name[len("tpose_"):]
    return name if name in EXPECTED else ""


# --- The detector ---------------------------------------------------------------------------------------------

def measure_mask(mask) -> Optional[Dict[str, Any]]:
    """The facing of the figure in a boolean ``mask`` (rows top-down): ``{facing: "left" | "right", score,
    confidence, parts: [score per foot part]}``; None when there is no figure, it is too small, or no foot part
    is found in its bottom ``FOOT_BAND``."""
    import numpy as np
    from scipy import ndimage
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2 or not mask.any():
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    top, bottom = int(rows[0]), int(rows[-1])
    height = bottom - top + 1
    if height < MIN_FIGURE_PX:
        return None
    region = mask[bottom - int(FOOT_BAND * height): bottom + 1]
    labels, count = ndimage.label(region)
    total = weight = 0.0
    parts = []
    for index in range(1, count + 1):
        ys, xs = np.nonzero(labels == index)
        if len(ys) < MIN_PART_AREA * height * height:
            continue
        y0, y1 = int(ys.min()), int(ys.max())
        rows_of = y1 - y0 + 1
        if rows_of < MIN_PART_HEIGHT * height:
            continue
        leg = float(xs[ys <= y0 + LEG_ROWS * rows_of].mean())
        sole = xs[ys >= y1 - SOLE_ROWS * rows_of]
        back, front = float(sole.min()), float(sole.max())
        if front - back < 3:
            continue
        part = ((front - leg) - (leg - back)) / (front - back)
        parts.append(round(part, 3))
        total += part * len(ys)
        weight += len(ys)
    if not weight:
        return None
    score = total / weight
    confidence = min(1.0, abs(score) / SCORE_FULL)
    if any(p * score < 0 and abs(p) >= DISAGREE_PART for p in parts):
        confidence *= 0.5
    return {"facing": "right" if score > 0 else "left", "score": round(score, 3),
            "confidence": round(confidence, 3), "parts": parts}


def _mask_of(path: Path):
    """The alpha matte of an image as a boolean array, or None (unreadable, or no transparent pixel — an
    image without a matte cannot be measured)."""
    import numpy as np
    from PIL import Image
    try:
        with Image.open(path) as opened:
            if "A" not in opened.getbands() and opened.mode != "P":
                return None
            alpha = opened.convert("RGBA").getchannel("A")
    except (OSError, ValueError):
        return None
    array = np.asarray(alpha)
    if array.min() == 255:
        return None
    return array > 127


_cache_lock = threading.Lock()
_cache: "OrderedDict[Tuple[str, int, int], Optional[Dict[str, Any]]]" = OrderedDict()
_CACHE_SIZE = 512


def measure(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """``measure_mask`` of a stored view (its alpha matte), memoised per file identity (path, mtime, size);
    None when it cannot be measured or the file is gone."""
    if path is None:
        return None
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    mask = _mask_of(Path(path))
    result = measure_mask(mask) if mask is not None else None
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def judge(view: str, measured: Optional[Dict[str, Any]], expected: Optional[str] = None) -> str:
    """``ok`` / ``wrong`` / ``unsure`` of a measured side view against ``expected`` (default: the convention)."""
    expected = expected or EXPECTED.get(view, "")
    if not measured or not expected or float(measured.get("confidence") or 0) < AUTO_CONFIDENCE:
        return UNSURE
    return OK if measured["facing"] == expected else WRONG


# --- The mirror -----------------------------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def original_path(path: Path) -> Path:
    """Where a mirrored view keeps its original bytes."""
    return Path(path).parent / MIRROR_DIR / Path(path).name


def read_sidecar(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(dir=target.parent, prefix=".mirror-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(staged, target)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def mirrored_bytes(data: bytes) -> bytes:
    """The image ``data`` flipped left-right, in its own format and mode (PNG lossless; JPEG / WebP at quality
    95). Flipping twice gives the same pixels back."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as opened:
        fmt = opened.format or "PNG"
        flipped = ImageOps.mirror(opened)
        out = io.BytesIO()
        flipped.save(out, format=fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
    return out.getvalue()


def mirror_record(path: Path) -> Optional[Dict[str, Any]]:
    """The sidecar's ``mirrored`` record of a stored view, None when it is not mirrored."""
    record = read_sidecar(path).get("mirrored")
    return record if isinstance(record, dict) else None


def restorable(path: Path) -> bool:
    """Whether un-mirroring ``path`` gives its kept original back byte for byte: it is mirrored, it is still
    the mirrored file (its content is the recorded one) and the original is kept with its recorded content."""
    record = mirror_record(path)
    if not record:
        return False
    original = original_path(path)
    try:
        return (sha256_bytes(Path(path).read_bytes()) == record.get("mirrored_sha256")
                and sha256_bytes(original.read_bytes()) == record.get("original_sha256"))
    except OSError:
        return False


def _lock(path: Path):
    from app.core.keyed_lock import keyed_lock
    return keyed_lock("view_mirror", str(Path(path).resolve()))


def toggle_mirror(path: Path, *, auto: bool = False, reason: str = "", confidence: Optional[float] = None,
                  keep_original: bool = True) -> Dict[str, Any]:
    """Mirror a stored view left-right in place, or — when its sidecar says it is mirrored — turn it back.

    Mirroring keeps the original bytes in ``original_path`` (``keep_original``; a staged draft keeps none) and
    writes ``mirrored`` into the sidecar; turning back restores the kept original when it is still the file's
    other side (``restorable``), else flips the pixels again, removes the original and the record. Either way
    ``mirror_changed_at`` is stamped and the figure memo is invalidated. Returns ``{mirrored: bool, record}``.
    Raises ``FileNotFoundError`` when the file is gone, ``OSError`` / ``ValueError`` when it cannot be read as
    an image."""
    from app.core.timeutils import utc_now_iso
    path = Path(path)
    with _lock(path):
        if not path.is_file():
            raise FileNotFoundError(str(path))
        current = path.read_bytes()
        meta = read_sidecar(path)
        record = meta.get("mirrored") if isinstance(meta.get("mirrored"), dict) else None
        original = original_path(path)
        now = utc_now_iso()
        if record is not None:
            data = original.read_bytes() if restorable(path) else mirrored_bytes(current)
            _atomic_write(path, data)
            original.unlink(missing_ok=True)
            meta.pop("mirrored", None)
            result: Dict[str, Any] = {"mirrored": False, "record": None}
        else:
            data = mirrored_bytes(current)
            if keep_original:
                _atomic_write(original, current)
            _atomic_write(path, data)
            record = {"auto": bool(auto), "reason": str(reason or ("" if auto else "mirrored by hand")), "at": now,
                      "original_sha256": sha256_bytes(current), "mirrored_sha256": sha256_bytes(data),
                      "original_kept": bool(keep_original)}
            if confidence is not None:
                record["confidence"] = round(float(confidence), 3)
            meta["mirrored"] = record
            result = {"mirrored": True, "record": record}
        meta["mirror_changed_at"] = now
        _atomic_write(path.with_suffix(".json"), json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    _invalidate_figure()
    logger.info("View %s %s%s", path.name, "mirrored" if result["mirrored"] else "turned back",
                f" automatically ({reason})" if auto else "")
    return result


def _invalidate_figure() -> None:
    try:
        from app.core import figure
        figure.invalidate()
    except Exception:  # noqa: BLE001 — a memo, never a failure
        logger.debug("Figure memo not invalidated", exc_info=True)


def auto_correct(view: str, path: Optional[Path], *, expected: Optional[str] = None,
                 keep_original: bool = True) -> Optional[Dict[str, Any]]:
    """Right after a side view rendered: mirror it when the detector is SURE it faces the wrong way
    (``judge`` = ``wrong``; ``expected`` defaults to the convention). Returns the ``mirrored`` record when it
    mirrored, else None — an unsure view is left as it is (its tile asks the user). Never raises: a view that
    cannot be read or written stays as rendered."""
    view = side_view(view)
    if not view or path is None:
        return None
    try:
        measured = measure(Path(path))
        expected = expected or EXPECTED[view]
        state = judge(view, measured, expected)
        if state != WRONG:
            if state == UNSURE:
                logger.info("View %s: facing direction unsure (%s) — left as rendered", Path(path).name,
                            measured and measured.get("score"))
            return None
        reason = f"faced the {measured['facing']} edge; the {view} view faces the {expected} edge"
        return toggle_mirror(Path(path), auto=True, reason=reason, confidence=measured["confidence"],
                             keep_original=keep_original)["record"]
    except Exception:  # noqa: BLE001 — a check after a render never loses the render
        logger.warning("View %s: facing check failed", path, exc_info=True)
        return None


def match_facing(view: str, path: Optional[Path], against: Optional[Path]) -> Optional[Dict[str, Any]]:
    """``auto_correct`` of a dressed side view's DRAFT: it is composited onto the base view ``against``, so it
    must face the way that view faces when that is measured sure, else the convention. No original is kept
    (a draft has no tile of its own)."""
    view = side_view(view)
    if not view:
        return None
    base = measure(against) if against is not None else None
    expected = base["facing"] if base and float(base.get("confidence") or 0) >= AUTO_CONFIDENCE else None
    return auto_correct(view, path, expected=expected, keep_original=False)


# --- What a tile shows ----------------------------------------------------------------------------------------

def tile_state(view: str, path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The facing part of a side view tile: ``{expected, facing, confidence, state, mirrored, restorable}`` —
    ``state`` ``ok`` / ``wrong`` / ``unsure`` (``judge``); ``facing`` / ``confidence`` None when it cannot be
    measured; ``mirrored`` the sidecar record without its hashes (None when not mirrored). None for a view that
    is no side view or a missing file."""
    view = side_view(view)
    if not view or path is None or not Path(path).is_file():
        return None
    measured = measure(Path(path))
    record = mirror_record(Path(path))
    public = ({k: record[k] for k in ("auto", "reason", "confidence", "at") if k in record}
              if record else None)
    return {"expected": EXPECTED[view], "facing": measured["facing"] if measured else None,
            "confidence": measured["confidence"] if measured else None,
            "state": judge(view, measured), "mirrored": public,
            "restorable": restorable(Path(path)) if record else False}


def pair_state(left: Optional[Path], right: Optional[Path]) -> Dict[str, Any]:
    """``{same, facing}``: ``same`` when both side views are measured at least ``SAME_CONFIDENCE`` sure and
    face the same edge (``facing``) — then one of them is wrong."""
    a, b = measure(left), measure(right)
    if (a and b and a["facing"] == b["facing"]
            and min(float(a["confidence"]), float(b["confidence"])) >= SAME_CONFIDENCE):
        return {"same": True, "facing": a["facing"]}
    return {"same": False, "facing": None}
