"""The base views a SHELL piece's worn views are made on (A190).

A clothing piece in mode "Shell from the body" (``garment_shell.SHELL``) reads its worn views twice: the piece-only
views are made from them, and the shell is projected from those onto the base body. Two things of the plain base
view get in the way there, and this module makes the base view the worn views start from without them:

- **Hair** (``BALD``): a plain body whose hairstyle is in the body (``base_body.hair_text`` not empty) carries that
  hair in every base view — long hair covers a bra's straps and back band. The worn views of a shell piece are made
  on a BALD copy of each base view (an edit: "Only change their head: completely bald …"). A plain body that is
  already bald needs nothing: its base views are used as they are (variant "").
- **Arms** (``ARMS_UP``): in the side views the arm hangs in front of the flank and hides the piece's side band. The
  worn side views ("Side views for the shell") are made on a side view with BOTH ARMS RAISED straight up (an edit of
  the base side view). The shell reads such a side view on the body posed the same way
  (``garment_shell.pose_arms_up``), and the edit is gated by that pose: its figure must match the posed body's
  silhouette (``garment_shell.arms_up_check``, IoU ≥ ``ARMS_UP_IOU_MIN`` and better than the arms at rest).

A variant is an image edit (occasion ``garment_view``, the garment edit's route; attempt N on chain entry N, A167),
cut out on the CPU (``base_body.cut_out``), stored per base signature under ``model_refs/variants/<kind>_<bsig>.
<variant>.png`` with a record naming the base view's content (``base_image_sha256``) and the prompt — a base view
rendered again makes it due. One job per variant view on first attempts, up to ``ATTEMPTS``.

What a worn view was made on is recorded in its sidecar (``base_variant``); a worn view whose variant differs from
the one its piece needs now is stale (``garment_images.stale_accepted``) and made again — the views after it with it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("shell_base_views")

BALD = "bald"
ARMS_UP = "arms_up"
#: The edit attempts of a variant view (attempt N on routing chain entry N, A167).
ATTEMPTS = 2
#: The edit's sentences. Said positively (the edit models ignore negatives); the keep sentence holds the rest.
KEEP = ("Keep the image exactly as it is: the same person, same body shape, same skin, same framing, the same "
        "view.")
BALD_TEXT = "Only change their head: completely bald with a smooth bare scalp, no hair at all."
ARMS_UP_TEXT = ("Only change the arms: both arms raised straight up above the head, held close to the head, hands "
                "open, the whole flank and the side of the chest fully visible.")
BALD_AND_ARMS_UP_TEXT = ("Only change their head and their arms: completely bald with a smooth bare scalp, no hair at "
                         "all; both arms raised straight up above the head, held close to the head, hands open, the "
                         "whole flank and the side of the chest fully visible.")
NEGATIVE = "clothing, hair, wig, hat, extra limbs, extra arms"
#: The line every worn edit / draft of a shell piece on a bald variant adds (``garment_clothing``).
WORN_BALD_LINE = "Their head stays completely bald with a smooth bare scalp."
#: The line a worn SIDE draft of a shell piece adds (the draft turns the worn front; the arms go up in it).
DRAFT_ARMS_UP_LINE = ("both arms raised straight up above the head, held close to the head, the whole flank and the "
                      "side of the chest fully visible.")
VARIANT_DIR = "variants"
SIDE_VIEWS = ("left", "right")


def _shell_piece(item_id: str) -> bool:
    from app.core import garment_set, garment_shell
    from app.models.inventory import get_item
    item = get_item(item_id) if isinstance(item_id, str) and item_id else None
    return bool(item) and garment_set.garment_kind_of(item) == garment_set.CLOTHING \
        and garment_shell.shape_of(item) == garment_shell.SHELL


def variant_for(character_name: str, item_id: str, view: str, *,
                profile: Optional[Dict[str, Any]] = None) -> str:
    """The base-view variant the worn ``view`` of ``item_id`` is made on: "" for a piece that is no shell piece (and
    for a shell front / back on a bald plain body), else ``bald`` (a haired plain body), ``arms_up`` (a side view),
    ``bald+arms_up`` (both)."""
    if not _shell_piece(item_id):
        return ""
    from app.core.base_body import hair_text
    parts = []
    if hair_text(character_name, profile=profile):
        parts.append(BALD)
    if view in SIDE_VIEWS:
        parts.append(ARMS_UP)
    return "+".join(parts)


def edit_text(variant: str) -> Tuple[str, str]:
    """``(prompt, negative)`` of the edit that makes ``variant`` from the base view."""
    parts = set(variant.split("+")) if variant else set()
    if parts == {BALD}:
        line = BALD_TEXT
    elif parts == {ARMS_UP}:
        line = ARMS_UP_TEXT
    elif parts == {BALD, ARMS_UP}:
        line = BALD_AND_ARMS_UP_TEXT
    else:
        raise ValueError(f"unknown base view variant {variant!r}")
    return f"{KEEP} {line}", NEGATIVE


def arms_up(variant: str) -> bool:
    return ARMS_UP in (variant or "").split("+")


def path_of(character_name: str, view: str, bsig: str, variant: str) -> Path:
    from app.core.base_body import _kind
    from app.core.model_refs import get_model_refs_dir
    return get_model_refs_dir(character_name) / VARIANT_DIR / f"{_kind(view)}_{bsig}.{variant}.png"


def _record(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def current(character_name: str, view: str, bsig: str, variant: str, base: Path) -> Optional[Path]:
    """The stored ``variant`` of the base ``view`` while it was made from the base view as it is now (its content)
    with today's prompt and passed its gate; None otherwise."""
    from app.core.base_body import file_sha256
    path = path_of(character_name, view, bsig, variant)
    if not path.is_file():
        return None
    record = _record(path)
    if (record.get("base_image_sha256") != file_sha256(base) or record.get("prompt") != edit_text(variant)[0]
            or not record.get("accepted")):
        return None
    return path


def due(character_name: str, item_id: str, view: str, *, profile: Optional[Dict[str, Any]] = None) -> int:
    """1 when the worn ``view`` of ``item_id`` needs a variant base view that is not made yet (the job it costs on
    first attempts), else 0. Reads files only."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    variant = variant_for(character_name, item_id, view, profile=profile)
    if not variant:
        return 0
    try:
        bsig = base_body.base_signature(character_name, profile=profile)
    except Exception:  # noqa: BLE001 — an estimate never raises
        return 0
    base = find_ref_image(character_name, base_body._kind(view), bsig)
    if base is None:
        return 1   # the base view comes first; its variant is made after it
    return 0 if current(character_name, view, bsig, variant, base) is not None else 1


class VariantRefused(RuntimeError):
    """Every attempt of a variant base view was refused (``records`` the gates)."""

    def __init__(self, view: str, variant: str, records):
        self.records = list(records)
        reasons = "; ".join(r for rec in self.records for r in (rec.get("reasons") or []))
        super().__init__(f"The {view} base view with {variant.replace('+', ' and ').replace('_', ' ')} was refused"
                         f" — {reasons or 'no image'}")


def _gate(character_name: str, bsig: str, variant: str, path: Path, size: Tuple[int, int]) -> Dict[str, Any]:
    """The variant's check: a figure must be there; an arms-up side view must match the posed body
    (``garment_shell.arms_up_check``) — skipped (and recorded so) while the base model is not built."""
    import numpy as np
    from PIL import Image
    from app.core import base_body, garment_shell
    with Image.open(path) as im:
        alpha = np.asarray(im.convert("RGBA").resize(size).getchannel("A")) > 128
    if alpha.sum() < 0.01 * alpha.size:
        return {"ok": False, "reasons": ["no figure in the image"]}
    if not arms_up(variant):
        return {"ok": True, "reasons": []}
    try:
        snapshot = base_body._snapshot_base_model(character_name, bsig)
    except Exception as e:  # noqa: BLE001 — no base model yet: the shell fit checks the pose again
        return {"ok": True, "reasons": [], "pose_check": f"skipped: {e}"}
    check = garment_shell.arms_up_check(snapshot["rigged"], snapshot["unrigged"], alpha)
    reasons = [] if check["ok"] else [
        f"the arms do not match the raised pose (silhouette IoU {check['iou_posed']} posed vs {check['iou_rest']} at "
        f"rest; needs ≥ {garment_shell.ARMS_UP_IOU_MIN} and better than at rest)"]
    return {"ok": check["ok"], "reasons": reasons, "pose_check": check}


def ensure(character_name: str, view: str, bsig: str, variant: str, base: Path) -> Path:
    """The ``variant`` of the base ``view`` (``current``), rendered when it is not: up to ``ATTEMPTS`` edits of the
    base view, each cut out on the CPU and gated (``_gate``). ``VariantRefused`` when every attempt is refused; load
    (``BackendBusyError``) passes through as it is."""
    from PIL import Image
    from app.core import base_body, expression_regen
    from app.core.base_body import file_sha256
    from app.core.garment_images import crop_back, square_reference
    from app.core.model_refs import get_model_refs_dir
    from app.core.timeutils import utc_now_iso
    from app.imagegen import routing as image_routing
    hit = current(character_name, view, bsig, variant, base)
    if hit is not None:
        return hit
    prompt, negative = edit_text(variant)
    target = path_of(character_name, view, bsig, variant)
    target.parent.mkdir(parents=True, exist_ok=True)
    refs_dir = get_model_refs_dir(character_name)
    with Image.open(base) as im:
        size = im.size
    records = []
    for attempt in range(1, ATTEMPTS + 1):
        stem = target.with_name(f"{target.stem}.try{attempt}")
        with image_routing.retry_attempt(attempt), square_reference(base, refs_dir) as (reference, side, offset,
                                                                                         source_size):
            rendered = expression_regen.render_character_image(
                character_name, output_stem=stem, equipped_pieces={}, equipped_items=[],
                pose_prompt="", expression_prompt="", bare_prompt=prompt, extra_negative=negative,
                image_use_case="garment_edit", occasion="garment_view",
                override_width=side, override_height=side, apply_state_modifiers=False,
                back_view=view == "back", reference_image=reference,
                sidecar_extra={"base_variant": {"view": view, "bsig": bsig, "variant": variant, "attempt": attempt}},
                character_loras=False, postprocess=False, raise_load=True)
        if rendered is None:
            records.append({"attempt": attempt, "ok": False, "reasons": ["render failed"]})
            continue
        cropped = crop_back(Path(rendered), stem.with_suffix(".png"), side, offset, source_size)
        cut = base_body.cut_out(cropped)
        cut.save(cropped, format="PNG")
        record = {**_gate(character_name, bsig, variant, cropped, size), "attempt": attempt}
        records.append(record)
        logger.info("Base view variant %s %s %s attempt %d: %s %s", character_name, view, variant, attempt,
                    "accepted" if record["ok"] else "refused", record.get("reasons") or "")
        if record["ok"]:
            cropped.replace(target)
            target.with_suffix(".json").write_text(json.dumps({
                "view": view, "bsig": bsig, "variant": variant, "prompt": prompt, "negative": negative,
                "base_image": base.name, "base_image_sha256": file_sha256(base), "accepted": True,
                "attempt": attempt, "gates": records, "created_at": utc_now_iso()}, indent=2), encoding="utf-8")
            return target
    raise VariantRefused(view, variant, records)


def base_for(character_name: str, item_id: str, view: str, bsig: str, base: Path, *,
             profile: Optional[Dict[str, Any]] = None, make: bool = True) -> Tuple[Path, str]:
    """``(base view, variant)`` the worn / piece-only ``view`` of ``item_id`` is made and judged on: the plain base
    view for variant "", else the variant (``ensure`` when ``make``; without ``make`` the stored one or the plain
    base view when it is missing)."""
    variant = variant_for(character_name, item_id, view, profile=profile)
    if not variant:
        return base, ""
    if make:
        return ensure(character_name, view, bsig, variant, base), variant
    hit = current(character_name, view, bsig, variant, base)
    return (hit, variant) if hit is not None else (base, variant)
