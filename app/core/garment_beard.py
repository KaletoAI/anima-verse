"""A beard-free copy of the HairDeck input (HairDeck hair, plan 2026-11-09-hairdeck-hair).

HairDeck turns ONE portrait into hair cards and reads everything that looks like hair as hair: on a bearded
character the beard came back as a tuft of cards in front of the chin (Kai, 2026-11-09: 11 of 106 cards, a
detached clump ~1.3 proxy radii below the head-proxy centre, in front of the face), and the placement's hairline
search had to learn to ignore strands below the eyes (commit 41df0e6d). So a character WITH facial hair sends
HairDeck an edited copy of the profile picture with the beard removed; the 2D look, the base body and the
profile picture itself keep the beard — only the HairDeck input changes.

- **Trigger** (``has_facial_hair``): the character's own appearance words — the ``always`` text of every body
  slot that applies (human: ``facial_hair`` = ``light stubble`` / ``short beard`` / ``mustache`` …) and every
  clause of ``character_appearance`` — name facial hair (``FACIAL_HAIR_TERMS``), not negated ("no beard",
  "without a moustache"). Declarative words, no character names; "clean-shaven" names no term and never triggers.
- **Fingerprint** (``hsig_inputs``): ``{"beard_free": BEARD_FREE_VERSION}`` only while it triggers, so the hsig
  — and with it the fsig of the HairDeck hair — of a character without facial hair stays what it was, and a
  switch either way re-runs HairDeck on the other input.
- **The edit** (``beard_free_input``): one image edit of the profile picture on the routed ``garment_view``
  occasion (use case ``garment_edit``: empty style, no character LoRAs, unprocessed — the square-canvas
  machinery of ``garment_images``), prompt ``PROMPT``. Cached in the HairDeck job folder as ``beard_free.png``
  + ``beard_free.json``, keyed by the source picture's sha256 and ``BEARD_FREE_VERSION``.
- **The gate** (``beard_gate``): the figure outside the beard zone must stay as it was (mean |ΔRGB|, the
  silhouette above the nose line), and the beard zone must have changed. The zone has no landmark model behind
  it — the project has none — so it is measured on the figure mask in units of the HEAD WIDTH (``head_frame``):
  the nose line at ``NOSE_T`` head widths below the crown, the face oval a half-ellipse from there,
  ``OVAL_HALF_T`` head widths to each side and ``CHIN_T`` head widths deep. Up to ``ATTEMPTS`` edits; when
  every attempt is refused, HairDeck gets the original picture and the job record says so (a beard tuft on
  the hair is better than no hair — the fit's own gates stay the judge).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_beard")

#: Bumped when the edit (prompt, negative, gate meaning) changes: part of the hsig and of the cache key.
BEARD_FREE_VERSION = 1
#: The whole edit prompt (short and positive: Qwen re-invents what a long prompt describes).
PROMPT = "Keep the image exactly as it is. Remove the beard; the chin and cheeks are clean-shaven."
#: Added to the ``garment_edit`` negative.
NEGATIVE = "beard, moustache, stubble"
#: The cached result in the HairDeck job folder (``garment_store.hairdeck_dir``).
RESULT_NAME = "beard_free.png"
RECORD_NAME = "beard_free.json"
#: Edit attempts (each a fresh backend call).
ATTEMPTS = 2

# --- Trigger ------------------------------------------------------------------

#: Facial-hair words (regex alternatives, whole words, case-insensitive). Sideburns are left out on purpose:
#: they grow from the scalp hairline and belong to the hair HairDeck should make.
FACIAL_HAIR_TERMS: Tuple[str, ...] = (
    r"beards?", r"bearded", r"moustaches?", r"mustaches?", r"moustached", r"mustached", r"stubbl(?:e|y)",
    r"goatees?", r"facial hair", r"five o'?clock shadow", r"mutton ?chops", r"soul patch",
)
_TERM_RE = re.compile(r"\b(?:" + "|".join(FACIAL_HAIR_TERMS) + r")\b", re.IGNORECASE)
#: A term right after one of these (at most one word between: "no visible beard") is denied.
_NEGATION_RE = re.compile(r"\b(?:no|without(?:\s+(?:a|an|any))?|not)\s+(?:[\w-]+\s+)?$", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[,;.!?\n]+")


def mentions_facial_hair(text: str) -> bool:
    """Whether one clause names facial hair that it does not deny."""
    for match in _TERM_RE.finditer(text or ""):
        if not _NEGATION_RE.search(text[:match.start()]):
            return True
    return False


def facial_hair_texts(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every appearance text of the character that names facial hair: the neutral ``always`` text of each body
    slot that applies, then each clause of ``character_appearance`` (a clause with an unresolved
    ``{placeholder}`` is left out, like ``garment_hair``'s hair clauses)."""
    from app.core.body_slots import slot_fragment, slots_for_character
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    texts: List[str] = []
    for spec in slots_for_character(character_name, profile=profile):
        always, _ = slot_fragment(character_name, spec.id, profile=profile)
        texts.extend(c for c in (" ".join(c.split()) for c in _CLAUSE_SPLIT.split(always or "")) if c)
    for clause in _CLAUSE_SPLIT.split(str(profile.get("character_appearance") or "")):
        clause = " ".join(clause.split())
        if clause and "{" not in clause:
            texts.append(clause)
    return [text for text in texts if mentions_facial_hair(text)]


def has_facial_hair(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the HairDeck input of the character gets its beard removed (``facial_hair_texts``)."""
    return bool(facial_hair_texts(character_name, profile=profile))


def hsig_inputs(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The hsig keys of the beard-free input: ``{"beard_free": BEARD_FREE_VERSION}`` while it triggers, else
    ``{}`` (the hsig of a character without facial hair is unchanged)."""
    return {"beard_free": BEARD_FREE_VERSION} if has_facial_hair(character_name, profile=profile) else {}


# --- Gate (pure numpy) ----------------------------------------------------------

#: The head width is the widest mask row between the crown and this many head widths below it (a fixed point,
#: so shoulders further down never count). Measured on Kai's portrait: crown→nose tip 1.02, crown→mouth 1.25.
HEAD_SCAN_T = 1.1
#: The nose line: crown + NOSE_T head widths (Kai: eyes at 0.76, nose tip at 1.02, the cheek beard from ~0.9).
NOSE_T = 0.88
#: The face oval: half-width OVAL_HALF_T head widths at the nose line, CHIN_T head widths below the crown at
#: its bottom (Kai: jaw half-width 0.41 at the mouth, beard bottom 1.6, neck stubble below it).
OVAL_HALF_T = 0.43
CHIN_T = 2.0
#: The ΔRGB measures run on the images pooled to about this many pixels per head width: an edit model
#: re-synthesises fine texture (hair strands, pores) everywhere, a shift or re-framing moves whole shapes.
#: Kai, clone 2026-11-09 (Qwen2.1 Turbo, head width 504 px): the accepted edit scored outside 7.16 at full
#: resolution / 3.77 pooled ×4; the same edit shifted 6 px 19.1 / 14.6, scaled by 2 % 16.7 / 13.0.
POOL_HEAD_PX = 128
#: Gate limits. OUTSIDE: mean |ΔRGB| (pooled) on the figure outside the oval; XOR: silhouette change above
#: the nose line as a share of the figure area there (``garment_gates.BODY_XOR_MAX``; Kai 0.0037);
#: BEARD_CHANGE_MIN: mean |ΔRGB| (pooled) inside the oval, below it the edit removed nothing (Kai 27+).
OUTSIDE_DRGB_MAX = 7.0
UPPER_XOR_MAX = 0.015
BEARD_CHANGE_MIN = 4.0


def head_frame(mask) -> Optional[Dict[str, float]]:
    """``{y0, width, cx}`` of the head of a portrait mask: the crown row, the head width (``HEAD_SCAN_T``
    fixed point) and the centre column of its widest row. None for an empty mask."""
    mask = np.asarray(mask, bool)
    rows = np.flatnonzero(mask.any(1))
    if not len(rows):
        return None
    height = mask.shape[0]
    widths = mask.sum(1)
    y0 = int(rows[0])
    width = float(widths[y0:min(height, y0 + max(4, height // 20))].max())
    for _ in range(32):
        hi = min(height, y0 + int(HEAD_SCAN_T * width) + 1)
        grown = float(widths[y0:hi].max())
        if grown <= width:
            break
        width = grown
    hi = min(height, y0 + int(HEAD_SCAN_T * width) + 1)
    widest = y0 + int(np.argmax(widths[y0:hi]))
    xs = np.flatnonzero(mask[widest])
    return {"y0": float(y0), "width": width, "cx": (float(xs[0]) + float(xs[-1])) / 2.0}


def beard_zone(shape: Tuple[int, int], frame: Dict[str, float]) -> np.ndarray:
    """The face oval below the nose line (``NOSE_T``, ``OVAL_HALF_T``, ``CHIN_T``) as a bool mask."""
    height, width = int(shape[0]), int(shape[1])
    nose = frame["y0"] + NOSE_T * frame["width"]
    a = OVAL_HALF_T * frame["width"]
    b = (CHIN_T - NOSE_T) * frame["width"]
    yy, xx = np.mgrid[0:height, 0:width]
    inside = ((xx - frame["cx"]) / a) ** 2 + ((yy - nose) / b) ** 2 <= 1.0
    return inside & (yy >= nose)


def _pool(values: np.ndarray, k: int) -> np.ndarray:
    """Mean over ``k``×``k`` blocks (the edge rows/columns that do not fill a block are dropped)."""
    if k <= 1:
        return values
    h, w = values.shape[0] // k * k, values.shape[1] // k * k
    return values[:h, :w].reshape(h // k, k, w // k, k, *values.shape[2:]).mean((1, 3))


def beard_gate(src_rgb, src_mask, edit_rgb, edit_mask) -> Dict[str, Any]:
    """Gate a beard-free edit against its source (same-shaped arrays, ``garment_gates`` conventions):
    ``outside_dRGB`` (the figure outside the beard zone) ≤ ``OUTSIDE_DRGB_MAX``, ``upper_xor`` (the
    silhouette above the nose line) ≤ ``UPPER_XOR_MAX``, ``beard_dRGB`` (inside the zone) ≥
    ``BEARD_CHANGE_MIN``; the ΔRGB measures on blocks of ``pool`` px (``POOL_HEAD_PX``).
    ``{ok, reasons, outside_dRGB, upper_xor, beard_dRGB, pool, zone}``."""
    from app.core.garment_gates import _check, _diff, _mean, _r
    _check(src_rgb, src_mask, edit_rgb, edit_mask)
    src_mask = np.asarray(src_mask, bool)
    edit_mask = np.asarray(edit_mask, bool)
    frame = head_frame(src_mask)
    if frame is None:
        return {"ok": False, "reasons": ["no figure in the picture"], "outside_dRGB": None, "upper_xor": None,
                "beard_dRGB": None, "pool": None, "zone": None}
    zone = beard_zone(src_mask.shape, frame)
    k = max(1, int(round(frame["width"] / POOL_HEAD_PX)))
    diff = _diff(_pool(np.asarray(src_rgb, np.float32), k), _pool(np.asarray(edit_rgb, np.float32), k))
    outside_sel = _pool((src_mask | edit_mask) & ~zone, k) > 0.5
    beard_sel = _pool(src_mask & zone, k) > 0.5
    outside = _mean(diff[outside_sel])
    beard = _mean(diff[beard_sel])
    nose = int(round(frame["y0"] + NOSE_T * frame["width"]))
    upper_area = int(src_mask[:nose].sum())
    xor = float((src_mask[:nose] ^ edit_mask[:nose]).sum()) / upper_area if upper_area else float("inf")
    reasons: List[str] = []
    if not outside <= OUTSIDE_DRGB_MAX:
        reasons.append(f"face or hair outside the beard changed (ΔRGB {outside:.1f} > {OUTSIDE_DRGB_MAX})")
    if not xor <= UPPER_XOR_MAX:
        reasons.append(f"head outline changed ({xor:.3f} > {UPPER_XOR_MAX})")
    if not beard >= BEARD_CHANGE_MIN:
        reasons.append(f"beard not removed (ΔRGB {beard:.1f} < {BEARD_CHANGE_MIN})")
    return {"ok": not reasons, "reasons": reasons, "outside_dRGB": _r(outside, 2), "upper_xor": _r(xor, 4),
            "beard_dRGB": _r(beard, 2), "pool": k,
            "zone": {"y0": int(frame["y0"]), "head_width": int(frame["width"]), "cx": round(frame["cx"], 1),
                     "nose_row": nose}}


# --- The edit -------------------------------------------------------------------

def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached(folder: Path, source: Path) -> Optional[Path]:
    """The accepted beard-free copy of ``source`` in a HairDeck job folder: ``beard_free.png`` whose record
    names the source's sha256 and ``BEARD_FREE_VERSION``; None otherwise."""
    from app.core.garment_store import read_record
    result = Path(folder) / RESULT_NAME
    record = read_record(Path(folder) / RECORD_NAME)
    if (result.is_file() and record.get("accepted") is True and record.get("version") == BEARD_FREE_VERSION
            and record.get("source_sha256") == _sha(Path(source))):
        return result
    return None


def beard_free_input(character_name: str, source: Path, folder: Path) -> Tuple[Path, Dict[str, Any]]:
    """``(the image HairDeck gets, record)``: the cached or freshly edited beard-free copy of ``source``
    (the profile picture) in the job ``folder``, or ``source`` itself when every attempt was refused (record
    ``accepted: False`` with the attempts' gate records). Blocking: the edit goes through the image service's
    routed ``garment_view`` occasion (``expression_regen.render_character_image``)."""
    from app.core import expression_regen
    from app.core.garment_images import _crop_back, _mask, _rgb, square_reference
    from app.core.garment_store import read_record, write_record
    from app.core.model_refs import get_model_refs_dir
    from app.core.timeutils import utc_now_iso
    folder = Path(folder)
    hit = cached(folder, source)
    if hit is not None:
        return hit, read_record(folder / RECORD_NAME)
    folder.mkdir(parents=True, exist_ok=True)
    source_sha = _sha(Path(source))
    size = _image_size(source)
    src_rgb = _rgb(Path(source), size)
    src_mask = _mask(Path(source), size)
    refs_dir = get_model_refs_dir(character_name)
    attempts: List[Dict[str, Any]] = []
    target = folder / RESULT_NAME
    for attempt in range(1, ATTEMPTS + 1):
        candidate = folder / f"beard_free.try{attempt}.png"
        with square_reference(Path(source), refs_dir) as (reference, side, offset, source_size):
            path = expression_regen.render_character_image(
                character_name,
                output_stem=candidate.with_suffix(""),
                equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="",
                bare_prompt=PROMPT, extra_negative=NEGATIVE,
                image_use_case="garment_edit",
                occasion="garment_view",
                override_width=side, override_height=side,
                apply_state_modifiers=False,
                reference_image=reference,
                sidecar_extra={"hairdeck_beard_free": {"attempt": attempt, "source_sha256": source_sha},
                               "edit_canvas": {"side": side, "offset": list(offset), "crop": list(source_size)}},
                character_loras=False,
                postprocess=False)
        if path is None:
            gate: Dict[str, Any] = {"ok": False, "reasons": ["render failed"]}
        else:
            path = _crop_back(Path(path), candidate, side, offset, source_size)
            gate = beard_gate(src_rgb, src_mask, _rgb(path, size), _mask(path, size))
        gate["attempt"] = attempt
        attempts.append(gate)
        logger.info("Beard-free HairDeck input %s attempt %d: %s %s", character_name, attempt,
                    "accepted" if gate["ok"] else "refused", gate.get("reasons") or "")
        if gate["ok"]:
            sidecar = read_record(candidate.with_suffix(".json"))
            candidate.replace(target)
            candidate.with_suffix(".json").unlink(missing_ok=True)
            record = {"accepted": True, "version": BEARD_FREE_VERSION, "source_sha256": source_sha,
                      "prompt": PROMPT, "negative": NEGATIVE, "attempt": attempt, "attempts": attempts,
                      "backend": sidecar.get("service") or "", "model": sidecar.get("model") or "",
                      "routing": sidecar.get("routing"), "duration_s": sidecar.get("duration_s"),
                      "created_at": utc_now_iso()}
            write_record(folder / RECORD_NAME, record)
            return target, record
    record = {"accepted": False, "version": BEARD_FREE_VERSION, "source_sha256": source_sha, "prompt": PROMPT,
              "negative": NEGATIVE, "attempts": attempts, "created_at": utc_now_iso()}
    write_record(folder / RECORD_NAME, record)
    return Path(source), record


def _image_size(path: Path) -> Tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def note(record: Dict[str, Any]) -> str:
    """The job-record note of a beard-free run (shown under the HairDeck tiles)."""
    if record.get("accepted") is True:
        return "Beard removed from the HairDeck input (the 2D look keeps it)"
    from app.core.garment_gates import gate_summary
    return f"Beard removal refused — HairDeck got the profile picture ({gate_summary(record.get('attempts') or [])})"
