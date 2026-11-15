"""The skin detail step of the base body front (spike 2026-11-12,
``claude-out/kai-base-skin/edit-step/``: ``edit_spike.py``, ``analyse.py``,
``measurements.json``).

WHY. The base front was rendered with a "smooth featureless" body text — and
it looked like plastic: no pores, no tone variation (``base_body.BODY_TEXT``
names natural skin since 2026-11-13, and since Ruling A74a the base prompts
no longer keep the body plain; this step stays as the second safeguard for
the skin). The winner of the spike keeps the neutral render and adds the
skin afterwards in two steps:

1. ONE image edit of the stored neutral front (occasion ``outfit_front``,
   the routing of the dressed front edit; use case
   ``base_body.DRESS_USE_CASE`` — no style, no negative), the front on
   neutral grey padded to the square T-pose size, prompt ``skin_prompt``.
   The edit draws real skin — and also moves the face, and paints shapes
   or creases the neutral front does not have.
2. A local CPU frequency transfer (``transfer_detail``): shape, colour and
   face come from the neutral front, only the fine detail (the edit minus
   its Gaussian blur at ``SKIN_SIGMA``) from the edit, and not where the
   edit's fine-shape band (``_band``) departs from the neutral one by more
   than ``SKIN_GUARD_DL`` L* (a shape the edit invented or moved). The alpha
   is the neutral front's.

Measured on the spike (Kai, Glut; Qwen2.1 Turbo, the winner ``A+hf3.0g``):
skin detail (``body_hf``; reference photo 3.26) Kai 0.78 -> 1.69, Glut
1.04 -> 1.57; torso blob/contrast x1.00-1.01 of the neutral; silhouette
IoU 1.0; face SSIM 1.0; hand gate ok. The raw edit alone: face SSIM
0.60-0.64, torso blob x1.44 on Kai.

THE GUARD SINCE RULING A74a. The base front now shows the body's own detail
on purpose, so the guard no longer stands for "the neutral body has none".
It never did compare against a plain body, though: it compares the edit
with the NEUTRAL front it edits, and it refuses nothing — it only takes no
fine detail from the edit where the two depart (the one refusal of the step
is the silhouette, ``MIN_DIRECT_IOU``). Detail the neutral front already
shows and the edit keeps passes; detail the edit moves or redraws keeps the
neutral front's own there — taking the edit's high-pass over a shifted shape
would draw it twice. So the guard stays as it is: its purpose (shape comes
from the neutral front) is unchanged, and ``SKIN_GUARD_DL`` is part of
``fingerprint_part``, so retuning it would age every stored base.

STORAGE. The neutral front stays as ``model_refs/tpose_neutral_<bsig>.png``
(+ sidecar; ``outfit_cache_gc.REF_PREFIXES`` files it under the base
signature, so the artefact collector keeps and drops it with its base). The
skin-detailed result IS the base front ``tpose_<bsig>.png`` — what the
mesher, the back/side views (edits of the front, so they inherit the skin),
the dressed front and every other reader of the front take. The front's
sidecar records the step under ``skin_step``.

NEVER FAILS THE BASE ("Nachschritte verwerfen nie"): an edit that is busy,
refused or fails, a matte or transfer error — the neutral front stays the
front and ``skin_step`` says why. ``apply_skin_step`` re-runs the step from
the stored neutral without re-rendering the front.

The world switch ``base_body.skin_detail_step`` (default on) turns it off;
it is part of ``base_body.prompt_fingerprint`` (``fingerprint_part``) only
while on, so a base built without it shows ``OLDER_PROMPTS`` once it is on.

NOT FOR A FRONT MADE FROM THE FULL-BODY REFERENCE (Ruling A92). The step was
made for fronts rendered from text, which looked plastic; a front that is an
edit of the full-body reference (Ruling A87, ``front_reference.source ==
"full_body"``) already has real skin. ``applies`` — the switch on AND the
front not made from the full-body reference — decides at every place the
step runs or is offered: the render (``after_front_render`` records ``OFF``
with ``NOT_USED_FULL_BODY``), the plans and job counts
(``base_body.base_rebuild_steps``, ``figure_build._plain_jobs``), the "Run
skin step" route (409) and ``info`` (``enabled`` drives the button). Such a
front's fingerprint has no skin part; a profile-image or text front keeps
its fingerprint byte for byte, and the world switch is untouched — switching
it would age every front made with the step.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("base_skin")

#: Bump when the step changes in a way that must re-render every base front.
SKIN_STEP_VERSION = 1
#: The image kind of the stored neutral front (``model_refs/<kind>_<bsig>``).
NEUTRAL_KIND = "tpose_neutral"
#: The edit's routing: the dressed front edit's occasion (an edit of the base
#: front, ``base_body.generate_dressed_images``).
SKIN_OCCASION = "outfit_front"

# The prompt of the spike, verbatim (variant A, edit_spike.py).
SKIN_KEEP = ("Keep the image exactly as it is: the same person, same face, same body shape, same pose, same arm "
             "and hand position, same framing and background.")
SKIN_SURFACE = ("Only change the surface of the skin: realistic natural human skin with fine visible pores, subtle "
                "skin tone variation and a matte finish")
SKIN_BODY_HAIR_MALE = ", with fine natural body hair on the forearms and the lower legs"

#: Gaussian sigma (px, at the stored front's size) splitting shape from detail.
SKIN_SIGMA = 3.0
#: L* departure of the fine-shape band (G3 - G15 of L*) above which the
#: edit invented or moved a shape there — no detail is taken from it.
SKIN_GUARD_DL = 3.0
#: The invented-shape mask grows by this many pixels.
SKIN_GUARD_DILATE = 6
#: The figure (neutral alpha >= ``SKIN_ALPHA``) shrinks by this many pixels
#: before detail is taken (no matte edge).
SKIN_BODY_ERODE = 3
#: Gaussian sigma (px) feathering the detail weight.
SKIN_FEATHER = 4.0
#: Alpha from which a pixel belongs to the figure.
SKIN_ALPHA = 128
#: The protected face: the top ``FACE_SHARE`` of the figure height (from 4 px
#: above its top), ``FACE_WIDTH`` x the half width of the head run at
#: ``FACE_HEAD_ROW`` of the figure height around its centre, extended
#: downwards by ``FACE_DROP`` of the image height (the chin and neck).
FACE_SHARE = 0.115
FACE_HEAD_ROW = 0.05
FACE_WIDTH = 1.25
FACE_DROP = 0.03
#: The edit's silhouette (before registration) must overlap the neutral one
#: at least this much — else the edit re-posed the figure and is refused.
#: Spike: 0.982-0.989 on every edit.
MIN_DIRECT_IOU = 0.9

#: ``skin_step.outcome`` values.
APPLIED, OFF, BUSY, FAILED, REFUSED = "applied", "off", "busy", "failed", "refused"
#: Why the step does not run on a front made from the full-body reference
#: (Ruling A92): the front record's ``reason``, ``info``'s ``note`` and the
#: "Run skin step" route's 409.
NOT_USED_FULL_BODY = ("The skin detail step is not used for a front made from a full-body reference — that "
                      "picture already has real skin")


# --- Setting, prompt, fingerprint ------------------------------------------------

def enabled() -> bool:
    """The world setting ``base_body.skin_detail_step`` (read live)."""
    from app.core import config
    from app.core.config_schema import field_default
    return config.get("base_body.skin_detail_step", field_default("base_body", "skin_detail_step")) is True


def front_source(character_name: str, bsig: Optional[str] = None, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """The source of the front the step belongs to: the stored front of
    ``bsig`` (the current base when None) — its ``front_reference.source`` —
    else, without a stored front, what the front is made from NOW
    (``base_body.front_source_image``). ``"full_body"`` or ``""``."""
    from app.core import base_body
    profile = base_body._profile_of(character_name, profile)
    bsig = bsig or base_body.base_signature(character_name, profile=profile)
    stored = base_body.stored_front_reference(character_name, bsig)
    if stored is not None:
        return str(stored.get("source") or "")
    return base_body.front_source_image(character_name, profile=profile)[1]


def applies(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
            source: Optional[str] = None) -> bool:
    """Whether the step runs on (or is offered for) a front: the world switch
    on (``enabled``) AND the front not made from the full-body reference
    (Ruling A92). ``source`` None = what a front is made from NOW
    (``base_body.front_source_image`` — the front a render or a plan makes);
    pass ``front_source`` for the stored one."""
    if not enabled():
        return False
    if source is None:
        from app.core import base_body
        source = base_body.front_source_image(character_name, profile=profile)[1]
    from app.core.base_body import SOURCE_FULL_BODY
    return source != SOURCE_FULL_BODY


def _male(profile: Dict[str, Any]) -> bool:
    return str((profile or {}).get("gender") or "").strip().lower() in ("male", "man", "m")


def skin_prompt(profile: Dict[str, Any]) -> str:
    """The whole prompt of the edit: ``SKIN_KEEP`` + ``SKIN_SURFACE`` (+ the
    body hair clause for a male character)."""
    return f"{SKIN_KEEP} {SKIN_SURFACE}{SKIN_BODY_HAIR_MALE if _male(profile) else ''}."


def transfer_params() -> Dict[str, Any]:
    return {"sigma": SKIN_SIGMA, "guard_dl": SKIN_GUARD_DL, "guard_dilate": SKIN_GUARD_DILATE,
            "body_erode": SKIN_BODY_ERODE, "feather": SKIN_FEATHER, "face_share": FACE_SHARE,
            "face_width": FACE_WIDTH, "face_drop": FACE_DROP, "min_direct_iou": MIN_DIRECT_IOU}


def fingerprint_part(profile: Dict[str, Any], *, source: str = "") -> Optional[Dict[str, Any]]:
    """What the step adds to ``base_body.prompt_fingerprint`` — None while
    the switch is off (the fingerprint is then the one of a base without the
    step, so switching it off again makes such a base current) and for a
    front made from the full-body reference (``source`` ``"full_body"``,
    Ruling A92: the step does not run there). For any other ``source`` the
    part is what it was before the ruling."""
    from app.core.base_body import SOURCE_FULL_BODY
    if not enabled() or source == SOURCE_FULL_BODY:
        return None
    return {"version": SKIN_STEP_VERSION, "occasion": SKIN_OCCASION, "prompt": skin_prompt(profile),
            "transfer": transfer_params()}


# --- The transfer (pure, CPU) ----------------------------------------------------

def _lstar(rgb: np.ndarray) -> np.ndarray:
    """CIE L* (D65) of an sRGB array 0..255 — as skimage's ``rgb2lab``."""
    c = np.clip(np.asarray(rgb, dtype=np.float64) / 255.0, 0.0, 1.0)
    lin = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    y = lin[..., 0] * 0.212671 + lin[..., 1] * 0.715160 + lin[..., 2] * 0.072169
    f = np.where(y > 0.008856, np.cbrt(y), 7.787 * y + 16.0 / 116.0)
    return 116.0 * f - 16.0


def _runs(row: np.ndarray):
    idx = np.where(row)[0]
    if idx.size == 0:
        return []
    splits = np.where(np.diff(idx) > 1)[0]
    starts = np.r_[idx[0], idx[splits + 1]]
    ends = np.r_[idx[splits], idx[-1]]
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e - s >= 6]


def _figure_rows(mask: np.ndarray) -> Tuple[int, int]:
    rows = np.where(mask.any(1))[0]
    return int(rows[0]), int(rows[-1] - rows[0] + 1)


def face_region(mask: np.ndarray) -> np.ndarray:
    """The protected face of a figure mask (see ``FACE_*``) as a bool mask."""
    out = np.zeros(mask.shape, dtype=bool)
    if not mask.any():
        return out
    top, height = _figure_rows(mask)
    runs = _runs(mask[min(mask.shape[0] - 1, top + int(FACE_HEAD_ROW * height))])
    h0, h1 = max(runs, key=lambda r: r[1] - r[0]) if runs else (0, mask.shape[1] - 1)
    hx, hh = (h0 + h1) // 2, (h1 - h0) // 2
    y0, y1 = max(0, top - 4), top + int(FACE_SHARE * height) + int(FACE_DROP * mask.shape[0])
    x0, x1 = max(0, hx - int(FACE_WIDTH * hh)), max(0, hx + int(FACE_WIDTH * hh))
    out[y0:y1, x0:x1] = True
    return out


def _band(lstar: np.ndarray) -> np.ndarray:
    from scipy import ndimage
    return ndimage.gaussian_filter(lstar, 3) - ndimage.gaussian_filter(lstar, 15)


def frequency_transfer(neutral: np.ndarray, edit: np.ndarray, neutral_mask: np.ndarray,
                       edit_mask: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """``(rgb, record)``: the neutral RGB (H x W x 3, 0..255) with the
    edit's fine detail where it may come from (the edit already in the
    neutral's frame). Detail = image minus its Gaussian blur at
    ``SKIN_SIGMA``; it replaces the neutral's own detail with the weight of
    the feathered keep mask: the figure of both (the neutral's shrunk by
    ``SKIN_BODY_ERODE``) minus the face (``face_region``) minus where the
    fine-shape band of L* departs by more than ``SKIN_GUARD_DL`` (dilated
    ``SKIN_GUARD_DILATE``) — a shape the edit invented or moved."""
    from scipy import ndimage
    a = np.asarray(neutral, dtype=np.float64)
    b = np.asarray(edit, dtype=np.float64)

    def low(x):
        return np.stack([ndimage.gaussian_filter(x[..., c], SKIN_SIGMA) for c in range(3)], -1)

    body = ndimage.binary_erosion(neutral_mask, iterations=SKIN_BODY_ERODE) & edit_mask
    face = face_region(neutral_mask)
    keep = body & ~face
    new_shape = np.abs(_band(_lstar(b)) - _band(_lstar(a))) > SKIN_GUARD_DL
    guarded = keep & ndimage.binary_dilation(new_shape, iterations=SKIN_GUARD_DILATE)
    keep &= ~guarded
    weight = ndimage.gaussian_filter(keep.astype(np.float64), SKIN_FEATHER)[..., None]
    out = a + weight * ((b - low(b)) - (a - low(a)))
    n_body = max(1, int(body.sum()))
    record = {"kept_share": round(float(keep.sum()) / n_body, 4),
              "guarded_share": round(float(guarded.sum()) / n_body, 4),
              "face_px": int(face.sum())}
    return np.clip(out, 0, 255), record


def _detail(rgb: np.ndarray, mask: np.ndarray) -> float:
    """Mean |grey - its 1.5 px blur| over the shrunk figure — a cheap skin
    detail number for the record (higher = more texture)."""
    from scipy import ndimage
    grey = np.asarray(rgb, dtype=np.float64).mean(-1)
    inner = ndimage.binary_erosion(mask, iterations=SKIN_BODY_ERODE) & ~face_region(mask)
    if not inner.any():
        return 0.0
    return round(float(np.abs(grey - ndimage.gaussian_filter(grey, 1.5))[inner].mean()), 4)


def register(edit_rgba, neutral_mask: np.ndarray):
    """``(edit in the neutral's frame, record)``: the edit scaled and moved
    so its figure (alpha >= ``SKIN_ALPHA``) has the neutral figure's height,
    top and horizontal centre."""
    from PIL import Image
    om = np.asarray(edit_rgba.getchannel("A")) >= SKIN_ALPHA
    it, ih = _figure_rows(neutral_mask)
    ot, oh = _figure_rows(om)
    icx = np.where(neutral_mask.any(0))[0]
    ocx = np.where(om.any(0))[0]
    s = ih / oh
    big = edit_rgba.resize((max(1, round(edit_rgba.width * s)), max(1, round(edit_rgba.height * s))),
                           Image.LANCZOS)
    dx = round((icx[0] + icx[-1]) / 2 - (ocx[0] + ocx[-1]) / 2 * s)
    dy = round(it - ot * s)
    canvas = Image.new("RGBA", (neutral_mask.shape[1], neutral_mask.shape[0]), (0, 0, 0, 0))
    canvas.paste(big, (dx, dy))
    return canvas, {"scale": round(s, 4), "dx": int(dx), "dy": int(dy)}


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return round(float((a & b).sum() / max(1, (a | b).sum())), 4)


def transfer_detail(neutral_rgba, edit_rgba) -> Tuple[Any, Dict[str, Any]]:
    """``(detailed RGBA image, record)`` of the neutral front and the matted
    edit cropped to its frame (same size): ``REFUSED`` (ValueError) when the
    edit's silhouette left the neutral one (``MIN_DIRECT_IOU``), else
    ``register`` + ``frequency_transfer``; the alpha is the neutral's."""
    from PIL import Image
    nm = np.asarray(neutral_rgba.getchannel("A")) >= SKIN_ALPHA
    em = np.asarray(edit_rgba.getchannel("A")) >= SKIN_ALPHA
    if not nm.any() or not em.any():
        raise ValueError("no figure in the neutral front or the edit")
    direct = _iou(em, nm)
    if direct < MIN_DIRECT_IOU:
        raise ValueError(f"the edit changed the silhouette (IoU {direct} < {MIN_DIRECT_IOU})")
    reg, reg_record = register(edit_rgba, nm)
    neutral_rgb = np.asarray(neutral_rgba.convert("RGB"), dtype=np.float64)
    rgb, record = frequency_transfer(neutral_rgb, np.asarray(reg.convert("RGB"), dtype=np.float64), nm,
                                     np.asarray(reg.getchannel("A")) >= SKIN_ALPHA)
    out = Image.fromarray(rgb.round().astype(np.uint8), "RGB")
    out.putalpha(neutral_rgba.getchannel("A"))
    record.update(iou_direct=direct, registration=reg_record,
                  detail_neutral=_detail(neutral_rgb, nm), detail_out=_detail(rgb, nm))
    return out, record


# --- Pad, crop back ------------------------------------------------------------

def pad_reference(neutral_rgba, size: Tuple[int, int], dst: Path) -> Dict[str, Any]:
    """The neutral front on grey (``model_refs.VIEW_REFERENCE_BACKGROUND``),
    centred on a ``size`` canvas (scaled down only when it does not fit),
    saved as RGB to ``dst``; returns the placement."""
    from PIL import Image
    from app.core.model_refs import VIEW_REFERENCE_BACKGROUND
    im = neutral_rgba
    w, h = size
    s = min(1.0, h / im.height, w / im.width)
    if s < 1.0:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x0, y0 = (w - im.width) // 2, (h - im.height) // 2
    canvas = Image.new("RGBA", (w, h), VIEW_REFERENCE_BACKGROUND + (255,))
    canvas.alpha_composite(im, (x0, y0))
    canvas.convert("RGB").save(dst)
    return {"x0": x0, "y0": y0, "w": im.width, "h": im.height, "scale": round(s, 6), "size": [w, h]}


def edit_to_frame(raw_path: Path, pad: Dict[str, Any], neutral_size: Tuple[int, int]):
    """The backend's full-frame edit, matted (the mesh-input BiRefNet mask on
    the original colours, as ``postprocess_outfit_image``), cropped back to
    the window the neutral front stood in and sized like it."""
    import io
    from PIL import Image
    from app.models.character import MESH_INPUT_REMBG_MODEL, run_rembg
    data = raw_path.read_bytes()
    with Image.open(io.BytesIO(data)) as opened:
        raw = opened.convert("RGB")
    mask = Image.open(io.BytesIO(run_rembg(data, MESH_INPUT_REMBG_MODEL, only_mask=True))).convert("L")
    if mask.size != raw.size:
        mask = mask.resize(raw.size)
    w, h = pad["size"]
    sx, sy = raw.width / w, raw.height / h
    box = (round(pad["x0"] * sx), round(pad["y0"] * sy),
           round((pad["x0"] + pad["w"]) * sx), round((pad["y0"] + pad["h"]) * sy))
    rgba = raw.copy()
    rgba.putalpha(mask)
    rgba = rgba.crop(box)
    if rgba.size != tuple(neutral_size):
        rgba = rgba.resize(tuple(neutral_size), Image.LANCZOS)
    return rgba


# --- Files ----------------------------------------------------------------------

def neutral_stem(refs_dir: Path, bsig: str) -> Path:
    return refs_dir / f"{NEUTRAL_KIND}_{bsig}"


def neutral_path(character_name: str, bsig: str) -> Optional[Path]:
    """The stored neutral front of the base ``bsig``, None without one."""
    from app.core.model_refs import get_model_refs_dir
    path = neutral_stem(get_model_refs_dir(character_name), bsig).with_suffix(".png")
    return path if path.is_file() else None


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(target: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_json(target: Path, meta: Dict[str, Any]) -> None:
    _write_atomic(target, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))


def _png_bytes(image) -> bytes:
    import io
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def step_record(character_name: str, bsig: str) -> Dict[str, Any]:
    """The front sidecar's ``skin_step`` record ({} without one)."""
    from app.core.model_refs import find_ref_image
    front = find_ref_image(character_name, "tpose", bsig)
    record = _read_json(front.with_suffix(".json")).get("skin_step") if front else None
    return record if isinstance(record, dict) else {}


def _set_front_record(front: Path, record: Dict[str, Any]) -> None:
    sidecar = front.with_suffix(".json")
    meta = _read_json(sidecar)
    meta["skin_step"] = record
    _write_json(sidecar, meta)


# --- The step -------------------------------------------------------------------

def _render_edit(character_name: str, reference: Path, stem: Path, *, size: Tuple[int, int],
                 profile: Dict[str, Any], prompt: str) -> Optional[Path]:
    """The edit render (raises load: ``BackendBusyError`` /
    ``MediaGenerationDisabled``; None when it rendered nothing)."""
    from copy import deepcopy
    from app.core import expression_regen
    from app.core.base_body import DRESS_USE_CASE
    mesh_profile = deepcopy(profile)
    mesh_profile["equipped_pieces"] = {}
    mesh_profile["equipped_items"] = []
    return expression_regen.render_character_image(
        character_name, output_stem=stem, equipped_pieces={}, equipped_items=[],
        pose_prompt="", expression_prompt="", bare_prompt=prompt,
        image_use_case=DRESS_USE_CASE, occasion=SKIN_OCCASION,
        override_width=size[0], override_height=size[1], apply_state_modifiers=False,
        mesh_input_profile=mesh_profile, reference_image=reference,
        # The full frame: the step crops it back onto the neutral front.
        postprocess=False, sidecar_extra={"skin_step_edit": True}, raise_load=True)


def run_step(character_name: str, front: Path, neutral: Path, *,
             profile: Dict[str, Any]) -> Dict[str, Any]:
    """Run the step on ``neutral`` and, when it lands, write the detailed
    image onto ``front`` (atomic). Returns the ``skin_step`` record — never
    raises: load is ``BUSY``, a refused edit (silhouette) ``REFUSED``, every
    other end ``FAILED``; the front then stays as it is."""
    from PIL import Image
    from app.core.base_body import _is_load
    from app.core.model_refs import _tpose_size
    from app.core.timeutils import utc_now_iso
    prompt = skin_prompt(profile)
    record: Dict[str, Any] = {"version": SKIN_STEP_VERSION, "occasion": SKIN_OCCASION, "prompt": prompt,
                              "transfer": transfer_params(), "neutral": neutral.name}
    try:
        if front.suffix.lower() != ".png":
            raise ValueError(f"the front is not a PNG ({front.name})")
        with Image.open(neutral) as opened:
            neutral_rgba = opened.convert("RGBA")
        size = _tpose_size()
        with tempfile.TemporaryDirectory(prefix=".skinstep_", dir=str(front.parent),
                                         ignore_cleanup_errors=True) as staging:
            reference = Path(staging) / front.name
            pad = pad_reference(neutral_rgba, size, reference)
            record["pad"] = pad
            raw = _render_edit(character_name, reference, Path(staging) / "edit", size=size,
                               profile=profile, prompt=prompt)
            if raw is None:
                return {**record, "applied": False, "outcome": FAILED, "error": "the edit rendered nothing",
                        "at": utc_now_iso()}
            meta = _read_json(raw.with_suffix(".json"))
            record["edit"] = {k: meta.get(k) for k in ("service", "provider", "model", "seed", "duration_s",
                                                       "final_prompt", "negative_prompt", "routing",
                                                       "created_at") if meta.get(k) not in (None, "")}
            edit = edit_to_frame(raw, pad, neutral_rgba.size)
        try:
            detailed, numbers = transfer_detail(neutral_rgba, edit)
        except ValueError as e:
            return {**record, "applied": False, "outcome": REFUSED, "error": str(e), "at": utc_now_iso()}
        _write_atomic(front, _png_bytes(detailed))
        return {**record, **numbers, "applied": True, "outcome": APPLIED, "at": utc_now_iso()}
    except Exception as e:  # noqa: BLE001 — the step never fails the base
        busy = _is_load(e)
        logger.warning("Skin step %s (%s): %s — the neutral front stays: %s", character_name, front.name,
                       "busy" if busy else "failed", e)
        return {**record, "applied": False, "outcome": BUSY if busy else FAILED,
                "error": str(e) or type(e).__name__, "at": utc_now_iso()}


def after_front_render(character_name: str, front: Path, *, bsig: str, profile: Dict[str, Any],
                       source: str = "") -> Path:
    """Right after a new base front landed on ``front`` (the hand-gated
    render; ``source`` its ``front_reference.source``): keep it as the
    neutral front, then — while the step ``applies`` (switch on, not made
    from the full-body reference) — run the step (``run_step``) and record it
    in the front's sidecar; else record ``OFF`` (with ``NOT_USED_FULL_BODY``
    as ``reason`` for a full-body front). Returns ``front``; never raises."""
    import shutil
    try:
        stem = neutral_stem(front.parent, bsig)
        for old in front.parent.glob(f"{stem.name}.*"):
            old.unlink(missing_ok=True)
        if not applies(character_name, profile=profile, source=source):
            record: Dict[str, Any] = {"applied": False, "outcome": OFF}
            if enabled():
                record["reason"] = NOT_USED_FULL_BODY
                logger.info("Skin step %s (%s): not used — the front is made from the full-body reference",
                            character_name, bsig)
            _set_front_record(front, record)
            return front
        neutral = stem.with_suffix(".png")
        shutil.copyfile(front, neutral)
        if front.with_suffix(".json").is_file():
            shutil.copyfile(front.with_suffix(".json"), neutral.with_suffix(".json"))
        record = run_step(character_name, front, neutral, profile=profile)
        _set_front_record(front, record)
        logger.info("Skin step %s (%s): %s%s", character_name, bsig, record.get("outcome"),
                    f" ({record.get('error')})" if record.get("error") else "")
    except Exception:  # noqa: BLE001 — the neutral front stays, the base never fails
        logger.exception("Skin step %s (%s) failed outside the edit", character_name, bsig)
    return front


class NotUsed(ValueError):
    """The step does not run on this front (Ruling A92: made from the
    full-body reference)."""


def refused(character_name: str, bsig: Optional[str] = None, *,
            profile: Optional[Dict[str, Any]] = None) -> str:
    """Why "Run skin step" is refused for the stored front of ``bsig`` (the
    current base when None): ``NOT_USED_FULL_BODY`` when that front is made
    from the full-body reference, else "" (Ruling A92)."""
    from app.core.base_body import SOURCE_FULL_BODY
    return NOT_USED_FULL_BODY if front_source(character_name, bsig, profile=profile) == SOURCE_FULL_BODY else ""


def apply_skin_step(character_name: str) -> Dict[str, Any]:
    """Re-run the step on the stored neutral front of the CURRENT base,
    without re-rendering it (the Figure tab's "Run skin step"); a
    front without a stored neutral (rendered with the switch off) is taken
    as the neutral first. Blocking — call from a worker thread. Returns the
    ``skin_step`` record; ``MissingInput`` without a front, ``NotUsed`` for a
    front made from the full-body reference (Ruling A92). The front keeps
    its ``created_at`` and ``prompt_fingerprint`` (the views stay current; the
    base model turns stale by the front's bytes)."""
    import shutil
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    with base_body._char_lock(character_name):
        profile = base_body._profile_of(character_name, None)
        bsig = base_body.base_signature(character_name, profile=profile)
        front = find_ref_image(character_name, "tpose", bsig)
        if front is None:
            raise base_body.MissingInput("No base front. Render the base body first")
        if refused(character_name, bsig, profile=profile):
            raise NotUsed(NOT_USED_FULL_BODY)
        neutral = neutral_path(character_name, bsig)
        if neutral is None:
            if step_record(character_name, bsig).get("applied"):
                raise base_body.MissingInput("The neutral front is gone. Regenerate the front")
            neutral = neutral_stem(front.parent, bsig).with_suffix(".png")
            shutil.copyfile(front, neutral)
            if front.with_suffix(".json").is_file():
                shutil.copyfile(front.with_suffix(".json"), neutral.with_suffix(".json"))
        base_body.reserve_views(character_name, ("front",), step=base_body.SKIN_STEP)
        try:
            record = run_step(character_name, front, neutral, profile=profile)
            record["rerun"] = True
            _set_front_record(front, record)
        finally:
            base_body.release_views(character_name, ("front",))
        # One line either way (audit 2026-11-13: whether a re-run landed could not be read from the log).
        if record.get("applied"):
            logger.info("Skin step re-run %s (%s): applied on the stored neutral front", character_name, bsig)
        else:
            logger.info("Skin step re-run %s (%s): skipped — %s%s", character_name, bsig, record.get("outcome"),
                        f": {record.get('error')}" if record.get("error") else "")
        return record


def start_skin_step(character_name: str) -> None:
    """``apply_skin_step`` in a worker thread; the front counts as running
    from THIS moment (the UI polls ``base_info``)."""
    import threading
    from app.core import base_body
    base_body.reserve_views(character_name, ("front",), step=base_body.SKIN_STEP)

    def run() -> None:
        try:
            apply_skin_step(character_name)
        except Exception as e:  # noqa: BLE001 — a worker thread reports, never raises
            logger.error("Skin step re-run for %s failed: %s", character_name, e)
        finally:
            base_body.release_views(character_name, ("front",))

    threading.Thread(target=run, daemon=True, name=f"base-skin-{character_name}").start()


def info(character_name: str, bsig: str) -> Dict[str, Any]:
    """``{enabled, world_enabled, note, neutral_url, neutral_meta, step}``
    for the plain body's front tile: ``enabled`` whether the step applies to
    the stored front (``applies`` with ``front_source`` — it drives the "Run
    skin step" button; false for a front made from the full-body reference,
    Ruling A92), ``world_enabled`` the world switch, ``note``
    ``NOT_USED_FULL_BODY`` or "", the stored neutral front (URL with its
    mtime) and the front's ``skin_step`` record (outcome, error, reason)."""
    from urllib.parse import quote
    from app.core.model_refs import image_tile_meta
    world = enabled()
    used = applies(character_name, source=front_source(character_name, bsig or None)) if world else False
    out: Dict[str, Any] = {"enabled": used, "world_enabled": world,
                           "note": NOT_USED_FULL_BODY if world and not used else "",
                           "neutral_url": None, "neutral_meta": None, "step": None}
    if not bsig:
        return out
    neutral = neutral_path(character_name, bsig)
    if neutral is not None:
        try:
            stamp = neutral.stat().st_mtime_ns
            out["neutral_url"] = (f"/characters/{quote(character_name, safe='')}/base-body/images/front"
                                  f"?variant=neutral&v={stamp}")
            out["neutral_meta"] = image_tile_meta(neutral)
        except OSError:
            pass
    record = step_record(character_name, bsig)
    if record:
        out["step"] = {k: record.get(k) for k in ("applied", "outcome", "error", "reason", "at")}
    return out
