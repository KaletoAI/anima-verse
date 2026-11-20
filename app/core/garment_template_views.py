"""A205: the piece-only views a TEMPLATE piece bakes its texture from.

User decision 2026-11-18: "The sheer fabric definitely needs different images for the texture. It is useless when
the legs are on the texture." Before, a template piece baked from its ITEM picture (``garment_template.
texture_sources``); a picture of a sheer skirt worn shows the legs through it, and the bake painted them onto the
cloth. Now a template piece can have two piece-only views of its own — ``front`` and ``back``, the piece alone, cut
out, no body:

* rendered from the item picture (occasion ``garment_view``, use case ``garment_edit``) with the ghost text of the
  piece's class (``garment_clothing.ghost_prompt``, A183) — plus, for the back, the turn-around line, and for a
  SHEER piece (``fabric == "sheer"``) the fabric-only line ``SHEER_LINE``;
* at most ``JOBS_PER_VIEW`` (= ``garment_images.GHOST_RUN_JOBS``, A190) image jobs per view and click; when every
  attempt is refused the view offers "Use this" on an attempt, Upload and Regenerate (A183's shape);
* cut out on the CPU (``garment_template.prepare_view`` → ``garment_matte.cut``, A230: backdrop key + BiRefNet
  consensus, rim un-mixed and filled from inside; an upload's own alpha bounds the piece) and cropped square around the piece;
* a SHEER piece's view is refused when skin-coloured pixels lie inside the piece mask (``skin_check``: the
  YCrCb box ``garment_template.skin_mask``, narrowed to the character's own skin tone from the base front view when
  there is one) — the refusal counts as one of the view's attempts.

Which views the bake reads (``garment_template.texture_sources``): these views when one exists, else the clothing
chain's cut-outs (Ruling A141), else the item picture — except for a SHEER piece, which has no item-picture
fallback: it is due (``missing_views`` hub jobs) until both views exist. The bake key already folds the sha256 of
both source images in (``key_for``), so a new, used or uploaded view re-drapes the piece at the next Build (CPU).

Files: ``templates/views/{item}_{view}.png`` (+ ``.json``: ``accepted``, ``source`` render / upload,
``check``, ``accepted_by_user``) and the attempts ``{item}_{view}.try{n}.png`` (+ ``.json`` the check record)."""
from __future__ import annotations

import io
import json
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_template_views")

VIEWS = ("front", "back")
#: A190's cap: the image jobs one piece-only view may spend per click (Generate / Regenerate).
JOBS_PER_VIEW = 2
#: A SHEER piece's piece-only view: the fabric alone, so the bake never paints a body onto it.
SHEER_LINE = ("Show the fabric alone, flat-lit, with nothing behind it but the backdrop and nothing "
              "showing through it: no legs, no body, no skin — a picture of the fabric only.")
#: A230: every piece-only view asks for a green screen — since A235 the line lives with the ghost texts
#: (``garment_clothing.GREEN_LINE``) and ends every piece-only prompt, here after the sheer line.
from app.core.garment_clothing import GREEN_LINE  # noqa: E402
#: The back view of a template piece is made from the item picture (a front): turned around.
BACK_LINE = "Turn the garment around and show its back, seen from behind."
#: The extra negative of a sheer piece.
SHEER_NEGATIVE = ("legs", "skin", "body", "person", "mannequin")
#: Skin inside the piece mask above this share refuses a sheer view (``garment_gates.SKIN_LEFT_MAX`` = 0.005 is the
#: ghost's limit for skin OUTSIDE the piece; inside a sheer piece a few warm folds pass, a leg does not).
SKIN_MAX = 0.01
#: Pixels of the piece's rim left out of the skin count (anti-aliased into the background).
RIM_PX = 2
#: A pixel within this mean |ΔRGB| of the character's skin tone counts (the tone narrows the YCrCb box).
SKIN_TONE_DRGB = 45.0
#: Square side of the cut-out relative to the piece's larger side (``garment_images.CUTOUT_PAD``).
PAD = 1.15

#: Missing views of a sheer piece: the Figure row's / dialog's reason.
SHEER_NEEDS_VIEWS = "Sheer fabric needs its piece-only views first — 1 hub job per view, in the piece dialog"

_running: Dict[Tuple[str, str, str], str] = {}
_lock = threading.Lock()


class ViewRefused(RuntimeError):
    def __init__(self, view: str, records: List[Dict[str, Any]]):
        self.view, self.records = view, records
        super().__init__(f"{view} refused — " + "; ".join(
            r for rec in records for r in rec.get("reasons") or []))


# --- paths ---------------------------------------------------------------------------

def views_dir(character_name: str) -> Path:
    from app.core.garment_template import templates_dir
    return templates_dir(character_name) / "views"


def view_path(character_name: str, item_id: str, view: str) -> Path:
    if view not in VIEWS:
        raise ValueError(f"view must be one of {', '.join(VIEWS)}")
    return views_dir(character_name) / f"{item_id}_{view}.png"


def attempt_path(character_name: str, item_id: str, view: str, n: int) -> Path:
    return views_dir(character_name) / f"{item_id}_{view}.try{int(n)}.png"


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, record: Dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    tmp.replace(path)


def accepted(character_name: str, item_id: str, view: str) -> Optional[Path]:
    """The accepted view file, else None."""
    path = view_path(character_name, item_id, view)
    return path if path.is_file() and _read(path.with_suffix(".json")).get("accepted") is True else None


def is_sheer(item: Optional[Dict[str, Any]]) -> bool:
    from app.core.garment_template import params_of
    params = params_of(item)
    return bool(params) and params.get("fabric") == "sheer"


def projection_optional(item: Optional[Dict[str, Any]]) -> bool:
    """Whether the piece's texture comes from the cut (param ``texture`` "cut"): its piece-only views then only feed
    the projection fallback — never due, and a sheer piece is not blocked without them (user finding 2026-11-20)."""
    from app.core.garment_template import params_of
    params = params_of(item)
    return bool(params) and params.get("texture") == "cut"


def missing_views(character_name: str, item_id: str) -> List[str]:
    return [v for v in VIEWS if accepted(character_name, item_id, v) is None]


# --- prompt --------------------------------------------------------------------------

#: Bug round 2026-11-20: the template's own parameters, said in the view prompt — the bake projects the view onto the
#: template's shape, so a strap, a chain or a finger the picture invents lands on cloth that is not there (Glut's
#: strapless bra was pictured with straps and chains: coverage 0.43; her fingerless gloves with full fingers).
#: ``{field: {value: line}}``, read per kind (``template_lines``); the lines describe what IS there.
TEMPLATE_LINES: Dict[str, Dict[str, str]] = {
    "fingers": {"fingerless": "The gloves are fingerless: they end at the knuckles and the fingers come out bare.",
                "none": "The gloves have no hand part: they end at the wrist and the whole hand is bare."},
    "straps": {"none": "The piece is strapless: nothing runs over the shoulders, and nothing hangs from it."},
    "shoulders": {"strapless": "The piece is strapless: nothing runs over the shoulders."},
    "sleeves": {"none": "The piece is sleeveless."},
    "slit": {"none": "The hem runs all the way round without a slit.",
             "left": "Its only slit is at the wearer's left side seam.",
             "right": "Its only slit is at the wearer's right side seam.",
             "front": "Its only slit is at the centre front.",
             "back": "Its only slit is at the centre back."},
    "feet": {"footless": "The legs end at the ankles; the feet are bare.",
             "stirrup": "The legs end in a strap under the arch; the heel and the toes are bare."},
}
#: A strapless top's top edge follows its template neckline (``garment_template.STRAPLESS_NECKLINES``; the drape's
#: ``top_drop`` dips a sweetheart edge at the centre front) — said after the strapless line.
STRAPLESS_EDGE_LINES: Dict[str, str] = {
    "straight": "Its top edge runs straight round the chest.",
    "sweetheart": "Its top edge dips at the centre front in a sweetheart curve.",
}
#: Gloves are pictured upright as a pair: the bake's pose search raises the arms to match (``garment_template_build.
#: GLOVE_ARM_DEG``) — a pair lying flat or hanging down would be painted upside down.
GLOVES_LINE = "Show the pair side by side and upright, the fingers pointing up and the cuffs at the bottom."


def template_lines(params: Optional[Dict[str, Any]]) -> List[str]:
    """The ``TEMPLATE_LINES`` of the fields the piece's kind has (``garment_template.KIND_FIELDS``), in field order;
    the gloves' orientation line first; a strapless top's edge line (``STRAPLESS_EDGE_LINES``) after its strapless
    line. [] without template parameters."""
    if not params:
        return []
    from app.core.garment_template import KIND_FIELDS
    kind = params.get("kind") or ""
    lines = [GLOVES_LINE] if kind == "gloves" else []
    for field in KIND_FIELDS.get(kind, ()):
        line = TEMPLATE_LINES.get(field, {}).get(str(params.get(field)))
        if line and line not in lines:
            lines.append(line)
        if field == "shoulders" and params.get(field) == "strapless":
            edge = STRAPLESS_EDGE_LINES.get(str(params.get("neckline")))
            if edge:
                lines.append(edge)
    return lines


def prompt_for(item: Dict[str, Any], view: str) -> Tuple[str, str]:
    """``(prompt, negative)`` of one piece-only view: the ghost text of the piece's class (A183 —
    ``ghost_prompt`` of the ``outfit_piece``, the back's side line included), the turn-around line on the back, the
    template's own parameters (``template_lines``, bug round 2026-11-20), the fabric-only line for a sheer piece,
    the green-screen line last (A230)."""
    from app.core.garment_clothing import GHOST_NEGATIVE, ghost_prompt
    from app.core.garment_template import params_of
    parts = [ghost_prompt((item or {}).get("outfit_piece") or {}, view, green=False)]
    if view == "back":
        parts.append(BACK_LINE)
    parts += template_lines(params_of(item))
    negative = list(GHOST_NEGATIVE)
    if is_sheer(item):
        parts.append(SHEER_LINE)
        negative += [n for n in SHEER_NEGATIVE if n not in negative]
    parts.append(GREEN_LINE)
    return " ".join(parts), ", ".join(negative)


# --- CPU: cut-out and the skin check ------------------------------------------------------

def cut_out(src: Path, dst: Path) -> Dict[str, Any]:
    """The piece cut free (``garment_template.prepare_view`` without the skin cut — the check must SEE the skin) and
    cropped to a square of ``PAD`` × its larger side around the alpha box. ``{alpha, share, bbox, side}``;
    ValueError when nothing is left."""
    import numpy as np
    from PIL import Image
    from app.core.garment_template import prepare_view
    info = prepare_view(str(src), dst, garment_only=False)
    with Image.open(dst) as im:
        rgba = im.convert("RGBA")
    box = Image.fromarray((np.asarray(rgba)[..., 3] >= 128).astype(np.uint8) * 255).getbbox()
    if box is None:
        raise ValueError("No piece found in the image")
    x0, y0, x1, y1 = box
    side = int(PAD * max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    # A230: the padding past the picture's edge repeats the edge colours (the cut filled every transparent pixel with
    # the piece's nearest colour) — never black next to the piece
    arr = np.asarray(rgba)
    x0p, y0p = cx - side // 2, cy - side // 2
    pad = max(0, -x0p, -y0p, x0p + side - arr.shape[1], y0p + side - arr.shape[0])
    rgb = np.pad(arr[..., :3], ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    al = np.pad(arr[..., 3], pad)
    sl = (slice(y0p + pad, y0p + pad + side), slice(x0p + pad, x0p + pad + side))
    out = Image.fromarray(np.dstack([rgb[sl], al[sl]]).astype(np.uint8), "RGBA")
    out.save(dst, format="PNG")
    return {**info, "bbox": [x0, y0, x1, y1], "side": side}


def skin_tone(character_name: str) -> Optional[List[float]]:
    """The character's skin: the median RGB of the base front view's thigh rows (``garment_gates.skin_colour``),
    with the figure found by the border-background rule (no matte) — None without a base front view."""
    try:
        import numpy as np
        from PIL import Image
        from app.core import base_body, garment_gates
        from app.core.model_refs import find_ref_image
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        path = find_ref_image(character_name, base_body._kind("front"),
                              base_body.base_signature(character_name, profile=profile))
        if path is None:
            return None
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB")).astype(np.int32)
        border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        mask = np.abs(rgb - np.median(border, axis=0)).max(axis=2) > 24
        tone = garment_gates.skin_colour(rgb, mask)
        return None if tone is None else [round(float(v), 1) for v in tone]
    except Exception as e:  # noqa: BLE001 — the YCrCb box alone then
        logger.info("Template views %s: no skin tone (%s) — the skin box alone", character_name, e)
        return None


def skin_check(path: Path, *, tone: Optional[List[float]] = None) -> Dict[str, Any]:
    """The sheer check of one cut-out: the share of the piece mask (eroded by ``RIM_PX``) that is skin-coloured —
    ``garment_template.skin_mask`` (YCrCb) and, with the character's ``tone``, within ``SKIN_TONE_DRGB`` of it.
    ``{ok, skin, limit, pixels, reasons}``; refused above ``SKIN_MAX``."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    from app.core.garment_template import skin_mask
    with Image.open(path) as im:
        px = np.asarray(im.convert("RGBA"))
    piece = ndimage.binary_erosion(px[..., 3] >= 128, iterations=RIM_PX)
    skin = skin_mask(px[..., :3]) & piece
    if tone is not None:
        skin &= np.abs(px[..., :3].astype(np.float32) - np.asarray(tone, dtype=np.float32)).mean(2) <= SKIN_TONE_DRGB
    share = float(skin.sum() / max(1, piece.sum()))
    ok = share <= SKIN_MAX
    return {"ok": ok, "skin": round(share, 4), "limit": SKIN_MAX, "pixels": int(skin.sum()), "tone": tone,
            "reasons": [] if ok else [f"skin inside the piece: {share:.4f} > {SKIN_MAX} — legs or body show "
                                      f"through the fabric"]}


def check_file(character_name: str, item: Dict[str, Any], src: Path, dst: Path) -> Dict[str, Any]:
    """Cut ``src`` out into ``dst`` and judge it: a sheer piece runs ``skin_check``; every piece needs a piece."""
    try:
        info = cut_out(src, dst)
    except ValueError as e:
        return {"ok": False, "reasons": [str(e)]}
    if not is_sheer(item):
        return {"ok": True, "reasons": [], "cutout": info}
    return {**skin_check(dst, tone=skin_tone(character_name)), "cutout": info}


# --- render ----------------------------------------------------------------------------

def _render(character_name: str, item_id: str, view: str, *, prompt: str, negative: str, source: Path,
            target: Path, attempt: int) -> Optional[Path]:
    """ONE image job: the item picture edited into the piece-only view (occasion ``garment_view``). Stubbed in the
    smokes. The rendered file cut back to the picture's frame at ``target`` — at the render's resolution
    (``crop_back(native=True)``) — or None when the render failed."""
    from app.core import expression_regen
    from app.core import garment_images as gi
    from app.core.model_refs import get_model_refs_dir
    from app.imagegen import routing as _image_routing
    with _image_routing.retry_attempt(attempt), \
            gi.square_reference(source, get_model_refs_dir(character_name)) as (reference, side, offset, size):
        path = expression_regen.render_character_image(
            character_name, output_stem=target.with_suffix(""), equipped_pieces={}, equipped_items=[],
            pose_prompt="", expression_prompt="", bare_prompt=prompt, extra_negative=negative,
            image_use_case="garment_edit", occasion="garment_view", override_width=side, override_height=side,
            apply_state_modifiers=False, back_view=view == "back", reference_image=reference,
            sidecar_extra={"template_view": {"item_id": item_id, "view": view, "attempt": attempt}},
            character_loras=False, postprocess=False, raise_load=True)
        if path is None:
            return None
        # bug round 2026-11-20: at the render's own resolution — the bake's source pixels (P-H3 answers 2048²;
        # cut back to the 512 px item frame a view was 121-447 px wide on a 1024 atlas)
        return gi.crop_back(Path(path), target, side, offset, size, native=True)


def _publish(character_name: str, item_id: str, view: str, cut: Path, record: Dict[str, Any]) -> Path:
    from app.core.timeutils import utc_now_iso
    final = view_path(character_name, item_id, view)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f".{final.name}.pub")
    shutil.copyfile(cut, tmp)
    _write(final.with_suffix(".json"), {**record, "accepted": True, "created_at": utc_now_iso()})
    tmp.replace(final)
    return final


def _cut_of(attempt: Path) -> Path:
    return attempt.with_name(attempt.stem + ".cut.png")


def generate(character_name: str, item_id: str, view: str) -> Path:
    """Up to ``JOBS_PER_VIEW`` image jobs for ``view``: each attempt cut out and checked; the first that passes is
    the view. ``ViewRefused`` when every attempt is refused (they stay offered). Attempt slots are reused oldest
    first."""
    from app.core import base_body
    from app.models.inventory import get_item, get_item_image_path
    item = get_item(item_id) or {}
    picture = get_item_image_path(item_id)
    if not picture:
        raise base_body.MissingInput("The item has no picture to make the piece-only view from")
    prompt, negative = prompt_for(item, view)
    views_dir(character_name).mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    for attempt in range(1, JOBS_PER_VIEW + 1):
        target = attempt_path(character_name, item_id, view, attempt)
        rendered = _render(character_name, item_id, view, prompt=prompt, negative=negative, source=Path(picture),
                           target=target, attempt=attempt)
        if rendered is None:
            record: Dict[str, Any] = {"ok": False, "reasons": ["render failed"]}
        else:
            record = check_file(character_name, item, target, _cut_of(target))
        record.update({"attempt": attempt, "prompt": prompt, "item_picture": Path(picture).name})
        _write(target.with_suffix(".json"), record)
        records.append(record)
        if record["ok"]:
            return _publish(character_name, item_id, view, _cut_of(target),
                            {"source": "render", "attempt": attempt, "check": record})
    raise ViewRefused(view, records)


def use_attempt(character_name: str, item_id: str, view: str, attempt: int) -> Path:
    """"Use this": a stored attempt (passed or refused — a refusal is accepted by the user and recorded)."""
    target = attempt_path(character_name, item_id, view, attempt)
    cut = _cut_of(target)
    if not cut.is_file():
        raise ValueError(f"No attempt {attempt} of the {view} view")
    record = _read(target.with_suffix(".json"))
    return _publish(character_name, item_id, view, cut,
                    {"source": "render", "attempt": int(attempt), "check": record,
                     "accepted_by_user": not record.get("ok", False)})


def upload(character_name: str, item_id: str, view: str, data: bytes) -> Dict[str, Any]:
    """An uploaded image becomes the view: cut out and checked like a render; a refused upload is accepted by the
    user with its reasons recorded (A183's rule). Spends no job."""
    from PIL import Image
    from app.models.inventory import get_item
    view_path(character_name, item_id, view)  # validates the view
    item = get_item(item_id) or {}
    folder = views_dir(character_name)
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f"{item_id}_{view}.upload.png"
    with Image.open(io.BytesIO(data)) as im:
        im.convert("RGBA").save(raw, format="PNG")
    cut = _cut_of(raw)
    record = check_file(character_name, item, raw, cut)
    if not cut.is_file():
        raise ValueError("; ".join(record.get("reasons") or ["No piece found in the image"]))
    _publish(character_name, item_id, view, cut, {"source": "upload", "check": record,
                                                  "accepted_by_user": not record.get("ok", False)})
    return status(character_name, item_id)


def remove(character_name: str, item_id: str, view: str) -> Dict[str, Any]:
    """Drop the accepted view (the bake falls back; a sheer piece reads due again)."""
    path = view_path(character_name, item_id, view)
    for p in (path, path.with_suffix(".json")):
        p.unlink(missing_ok=True)
    return status(character_name, item_id)


# --- background start (the dialog's Generate / Regenerate) ---------------------------------

class Busy(RuntimeError):
    """Another hub-job flow of the same piece runs (``piece_jobs``): the route answers 409 with this text."""


def start(character_name: str, item_id: str, view: str, *,
          run: Optional[Callable[[str, str, str], Path]] = None) -> bool:
    """Start ``generate`` of one view in a thread; False when that view already runs. Raises ``Busy`` while
    ANOTHER hub-job flow of the piece holds it (``piece_jobs``: the texture from cut, the other view) — one flow per
    piece at a time, so a second click, a second tab or a click during the cut never spends a job."""
    from app.core import piece_jobs
    view_path(character_name, item_id, view)
    key = (character_name, item_id, view)
    what = f"view:{view}"
    with _lock:
        if key in _running and _running[key] == "running":
            return False
        held = piece_jobs.claim(character_name, item_id, what)
        if held:
            raise Busy(held)
        _running[key] = "running"
    fn = run or generate

    def work() -> None:
        outcome = ""
        try:
            fn(character_name, item_id, view)
        except ViewRefused as e:
            outcome = str(e)
        except Exception as e:  # noqa: BLE001 — shown in the dialog
            logger.warning("Template view %s %s %s: %s", character_name, item_id, view, e)
            outcome = str(e) or type(e).__name__
        with _lock:
            _running[key] = outcome or "done"
        piece_jobs.release(character_name, item_id, what)

    threading.Thread(target=work, name=f"template-view-{item_id}-{view}", daemon=True).start()
    return True


def status(character_name: str, item_id: str) -> Dict[str, Any]:
    """The dialog's view grid: per view ``{view, accepted (url key / None), record, attempts [{n, ok, reasons}],
    running, error, max_jobs}``, plus ``sheer``, ``required``, ``missing`` and ``hub_jobs`` (the first attempts of
    the missing views)."""
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    out: List[Dict[str, Any]] = []
    for view in VIEWS:
        final = accepted(character_name, item_id, view)
        attempts = []
        for n in range(1, JOBS_PER_VIEW + 1):
            target = attempt_path(character_name, item_id, view, n)
            if _cut_of(target).is_file():
                rec = _read(target.with_suffix(".json"))
                attempts.append({"n": n, "ok": bool(rec.get("ok")), "reasons": list(rec.get("reasons") or []),
                                 "skin": rec.get("skin"), "stamp": int(_cut_of(target).stat().st_mtime)})
        with _lock:
            state = _running.get((character_name, item_id, view), "")
        record = _read(final.with_suffix(".json")) if final else {}
        out.append({"view": view, "accepted": bool(final),
                    "stamp": int(final.stat().st_mtime) if final else 0,
                    "source": record.get("source") or "", "accepted_by_user": bool(record.get("accepted_by_user")),
                    "skin": (record.get("check") or {}).get("skin"), "attempts": attempts,
                    "running": state == "running",
                    "error": state if state not in ("", "running", "done") else "",
                    "max_jobs": JOBS_PER_VIEW})
    missing = [v["view"] for v in out if not v["accepted"]]
    sheer = is_sheer(item)
    # user finding 2026-11-20: with the texture from cut the views only feed the projection FALLBACK — never due
    # here (no hub jobs counted), and a sheer piece is not blocked without them. The BACK view is Picture 2 of the
    # cut's back job (``garment_cut_texture``): the cut flow makes it when it is missing and counts it on its own
    # button, so it is not due here either (``cut_uses``).
    optional = projection_optional(item)
    due = [] if optional else missing
    from app.core import piece_jobs
    holder = piece_jobs.holder(character_name, item_id)
    if holder == "cut":
        # the cut flow makes a missing back view itself (inside its own claim): show it as rendering
        from app.core import garment_cut_texture as gct
        if gct.progress_step(character_name, item_id) == "back_view":
            for cell in out:
                if cell["view"] == "back":
                    cell["running"] = True
    return {"views": out, "sheer": sheer, "required": sheer and not optional, "optional": optional,
            "cut_uses": ["back"] if optional else [],
            "missing": missing, "hub_jobs": len(due), "max_jobs": JOBS_PER_VIEW * len(due),
            # the plain reason every job button of the piece is disabled for ("" = free): ``piece_jobs``
            "busy": piece_jobs.reason(character_name, item_id)}
