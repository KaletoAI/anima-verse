"""Refit before re-render — the SOURCE of an own-mesh garment and its framing on another base body.

WHY. The garment fingerprint (``garment_store.garment_fsig``) contains the base signature and the sha256 of the
base front + back views: new base IMAGES name a new fsig, and the whole chain (worn / haired views, piece-only
views, cut-outs, mesh — hub jobs) used to run again although the piece itself had not changed. User decision
2026-11-10: the piece is first REFITTED from its existing images + mesh onto the new body (CPU, including the
clothing scale retry, ``garment_fit.scale_retry``); only when the gates refuse is the image -> mesh chain
rendered again. "Re-render" stays an explicit action.

SOURCE. What a piece was made from: its accepted image finals, its prepared mesh (edit chain) and the base views
those images were made on. The base views are kept WITH the group, because a base view is replaced in place when
the base images are rendered again under the same base signature (``base_body._publish_staged``)::

    garments/images/{item}_{fsig}_base_{front,back}.png    copies of the base views
    garments/images/{item}_{fsig}_base_front.json          {bsig, base_images, origin_fsig, created_at
                                                           [, materialized_from, materialized_at]}

``origin_fsig`` is the fsig the images were first rendered under. A group's copy is written when its first image
step renders (``ensure_current``), by every fit of the current fsig that finds none (the base views of the current
fsig ARE the ones in it), by the boot refit sweep for the base views of every accepted fit still on disk unchanged
(``backfill``) and, as a last resort, by ``find_source`` itself (the old base's view still on disk, same sha256).

REFIT (``find_source`` + ``materialize``; dispatched by ``garments._run_locked`` on a default run whose current
image group has none of its own images yet):

1. The last accepted source: the item's newest accepted fit (base body) made with the CURRENT method — edit chain
   (clothing, edit-chain hair) or subtract hair — whose image group (edit chain: the fit's fsig; subtract: its
   ``image_fsig``) still holds every accepted image final of the method (``SOURCE_STEPS``), the prepared mesh (edit
   chain) / the hair source mesh of its haired views (subtract), and its base views; and whose images name the
   item's CURRENT inputs: ``garment_store.edit_fsig_on`` with the group's own base (``bsig``, ``base_images``)
   must give its ``origin_fsig`` — a changed description, slot list or ``GARMENT_VERSION`` is a re-render.
2. Materialised: the source's image finals, prepared mesh and base view copies are COPIED into the current image
   group under their usual names (each record marked ``copied_from``, the base record ``materialized_from``).
   Copies, not hard links: an image step publishes its final with ``shutil.copyfile`` (in place). From here every
   existing reader works unchanged: the image / mesh steps of the current fsig are done, the subtract source mesh
   is found by the same ``ssig`` (it is keyed by the haired views' content), the fit and the per-body fits read the
   group as their own, and the old group is no longer named by anything (the GC removes it).
3. The fit runs as usual (edit chain ``garments._fit``; subtract ``garment_subtract.run_cut`` + ``run_fit`` — the
   cut against the new base, on the CPU). The FRAME is the group's own base copy (``fit_masks`` / ``place_mask``).
4. Accepted -> the fit record names its source (``source``: origin fsig, ``bsig``, ``base_images``,
   ``materialized_from``) and ``refitted: true``; the Wardrobe / Hair tab show "Refitted from the previous base"
   with a Re-render action. Refused (gate, frame beyond the caps, a sleeve off its arm — ARMS —, a source file
   missing) -> the copies are dropped (``drop_materialized``) and the same run renders the whole chain, as before.

An explicit run of an IMAGE step on a materialised group (Re-render, Regenerate of one view) drops the copies
first and renders from the method's first step: images of two bases never mix in one group. A refused refit is
not persisted: the next default run of a group without own images tries again (CPU seconds) — automatic triggers
skip a failed chain anyway (``garment_store.chain_failure``).

FRAME. ``garment_fit.place_by_framing`` maps the garment through ITS mask frame and the body through the body
mask's frame, so the ghost mask must be in the frame of the view the body was meshed from. A source made on base
B0 fitted onto B1: the ghost (B0's frame) is padded onto B1's canvas (``garment_cut.pad_into``: crops of one
square canvas, centred) and registered by the existing outline registration ``garment_gates.register`` (shift +
uniform scale, caps |shift| <= 0.04 Hb, scale 0.93..1.07) of B0's base front onto B1's base front — on the TRUNK
only: columns within ``TRUNK_HALF`` x Hb of the head's centre column (head, neck, shoulder line, the inner leg
outline). The full outline is dominated by the T-pose arms, whose angle differs from base to base. Measured
2026-11-10 on Kira's Black Blazer (made on base20d5701a), against its fit on its own base (collar top above the
shoulder top 6.19 cm, hem above the crotch 6.66 cm): onto base5c5f3624 the full-outline registration leaves
the caps (scale 0.916; applied anyway it shrinks the blazer, hem +3.5 cm) and the plain bbox framing sits the
collar 1.4 cm low; the trunk registration (shift 0.006 Hb, scale 1.004) gives collar -0.56 cm / hem -1.28 cm
(its torso is 1.6 cm shorter), deep push 0.7 %. Onto base233fdd2a (2.3 % larger in its frame): trunk shift
0.005 Hb, scale 1.026, collar +0.18 cm / hem -1.13 cm. Beyond the caps the refit is refused (re-render).
A registration whose residual outline distance stays above ``FRAME_RESIDUAL_MAX`` x Hb (the real trunks: 0.003 -
0.004 Hb) did not find the body and is refused the same way. A group whose base copy IS the target base front
(the usual case) is fitted exactly as before: no registration.

LIMBS. The trunk registration places the torso; a sleeve (a trouser leg) would follow the limb where the source
images drew it, and a limb of another base has another length, angle and thickness. A refit therefore ALIGNS the
limbs (``garment_fit.align_limbs``, inside the skinned transfer before the rigged clearance pass): every vertex the
SOURCE fit skinned to an Arm / ForeArm / Hand (UpLeg / Leg / Foot — not for a skirt) is re-expressed from the
source base's limb chain into the target's — its distance along the chain from the shoulder (hip) kept in metres
(user ruling 2026-11-10: the length is irrelevant, it must sit on the body; clamped at the hand tip / ankle), its
radial offset normalised by the limb radius and its angle around the limb in a twist-aligned frame — blended with
the source skin weights into the torso placement (no crease at the shoulder / hip). The source is the source
group's fit GLB on its own base (vertices, skin weights, limb frames), kept with the refitted group as
``limbs/{item}_{fsig}.npz`` (``write_limb_source``, by ``materialize``) — the same prepared mesh gives the same
vertex order on every body (``garment_fit._out_index``).

The gate after it is "sits on the body" (``limb_gate``): per limb segment (upper arm / forearm, thigh / shin) the
share of the piece's vertices on that limb farther than the limb radius + ``LIMB_OFF_M`` from it may exceed the
source's own share by at most ``LIMB_OFF_DELTA``; a limb the source covers that the refit lost is refused; the
penetration share after the push-out is the clothing gate ``rigged_inside_share`` (<= 0.01) every fit passes. The
reach (how far along the limb the piece ends) is recorded, never a reason.

Measured 2026-11-10, Kira's Black Blazer (left / right arm, forearm share beyond r + 4 cm; reach = p99 along
elbow -> wrist), WITHOUT the alignment:
    source = native fit on base20d5701a     0.018 / 0.000    reach 0.943 / 0.932
    refit onto base5c5f3624                 0.000 / 0.278    reach 1.019 / 0.967   right cuff off the forearm
    refit onto base233fdd2a                 0.246 / 0.506    reach 0.881 / 0.835   forearm half hangs below
Beyond r + 3 cm the native loose cuff already counts (0.170 / 0.069); 4 cm separates — good <= 0.018, broken
>= 0.246; ``LIMB_OFF_DELTA`` 0.10 lies between the good deltas (<= 0) and the smallest broken one (+0.228).
WITH the alignment (same refits): forearm 0.016 / 0.000 and 0.025 / 0.000, upper arm 0.029 / 0.055 and
0.007 / 0.005 (source 0.015 / 0.012), reach 0.475 / 0.470 m on both (source 0.475 / 0.470 — the piece keeps its
length), penetration after the push-out 0.0 on both, hem / collar as before (5.27 / 5.63 cm, 5.54 / 6.45 cm):
both accepted. The blazer's hem carries thigh weights but covers no thigh, so no leg chain is aligned for it.

TORSO (outfit bodies). An outfit body (``garments.fit_on_body``) is meshed from its OWN dressed views: another
image framing (T-pose, 1024 or 1536 px high, cropped wider), heels (Kira: crotch 0.82 - 0.89 m against 0.84 on the
base), its own chest and its own arms (elbows 3 - 4 cm further in and up to 13 cm further back, forearms 1 - 3 cm
shorter). The ghost's frame is the base front's; laid onto the outfit body's front by the image framing alone the
blazer sat 6 cm low on 3b3a0adaf672 (collar -0.35 cm / hem 0.44 cm against the base fit's 6.19 / 6.66) and its
front was torn open on three of the five bodies (chest / belly front exposed 0.92 - 0.94 / 0.80 - 0.93 against
0.18 / 0.00, the V-neck), the sleeves hung beside the T-pose arms (off the upper arm 0.59 - 1.0) — and every gate
passed (deep push 0 - 0.12, penetration 0). Every outfit-body fit is therefore placed from the group's BASE FIT
(``limb_source_from_fit(..., torso=True)`` of it — the same prepared mesh): its limbs by ``align_limbs`` (LIMBS),
its trunk by ``garment_fit.map_torso`` (height proportional between hip and neck joint, the clearance over the
body surface kept per direction, every non-limb bone counting — the chest is an extension bone), the displacement
smoothed over the mesh. Gated twice against the base fit: the limbs (``limb_gate``) and the trunk coverage
(``torso_gate``): per front / side / back the covered share (a garment vertex within ``TORSO_COVER_M``) of the
trunk cells the base fit covers may fall at most ``TORSO_COVER_DELTA`` below the base fit's. Refused = the piece is
left off that body with its reason (``garment_assembly`` "left off"), never served torn.

Measured 2026-11-10, Kira's blazer on her five outfit bodies (front / side / back covered share; base fit 0.99):
    image framing only     22354 0.67 front, 2b67 0.78 front, 3b3a 0.70 / 0.72 / 0.74, 62aad 0.59 front: all four
                           refused (072149: torso 0.99, refused by its limbs) — the torn fronts
    from the base fit      0.94 - 0.98 / 0.96 - 0.99 / 0.92 - 1.00: all five accepted; collar 4.6 - 7.7 cm, hem
                           5.6 - 9.2 cm above shoulder top / below crotch (base fit 6.19 / 6.66), chest front exposed
                           0.07 - 0.28 (base fit 0.18, the V-neck), belly <= 0.004, off the upper arm <= 0.094
                           (source 0.012 - 0.015), reach 0.467 - 0.477 m, penetration 0.
``TORSO_COVER_DELTA`` 0.10 lies between the largest accepted drop (0.074, back of 22354) and the smallest
refused one (0.216). The displacement smoothing (``garment_fit.LIMB_SMOOTH_PASSES`` 150) took the upper-arm
skin showing through the sleeves of 3b3a / 62aad from 0.12 / 0.17 to 0.02 / 0.00 (body vertices outside the
sleeve).

A share cannot see ONE big hole. After the trunk transfer the skin still showed through at the side of the chest
(3b3a, 62aad) and on the upper back (3b3a): three of the five outfit bodies are hollow SHELLS whose cavity reaches
the outside through a slit or a 3 cm opening (``garment_fit.body_sdf`` / ``_seal_cavities``) — the body solid was
only the wall, a piece vertex mapped under the skin was pushed AWAY from the inner wall, deeper into the body. The
seal fixes that at the root; the hole gate (``torso_holes`` / ``torso_hole_gate``) is the backstop. The outer trunk
skin (the outermost trunk vertices per direction) is SEEN where no garment surface lies on its outward normal
(within ``TORSO_SEE_LATERAL_M``, up to ``TORSO_SEE_DEPTH_M``); with the piece found just UNDER the skin instead,
outside the body solid, the skin there is an outer layer over the piece — baked hair hanging over the blazer's
back, recorded (``under_layer_cm2``) and never a hole (the hair over a piece is a separate, pending question);
inside the solid the body pokes through — a hole. Seen patches that reach into a cell the base fit itself leaves
open (``torso_open``: neckline, below the hem) are EDGES (a deeper neckline, a higher hem — the share's business);
every other patch is a HOLE, and the largest may not exceed ``TORSO_HOLE_CM2``. Largest hole, cm2:
    base fits (own openings)       base20d5701a 8.6, the refits 5c5f / 233f 0
    the defects of sheet v4        3b3a 90 (upper back) / 42 / 35 (side of the chest), 62aad 16.9 (side); the torn
                                   image-framing fits 213 (22354; the others tear into the neckline: edges of
                                   1900 - 3100, refused by the share)
    after the seal, all five       072149 8.0, 22354 12.5, 2b67 6.0, 3b3a 4.8, 62aad 14.2 (a patch at the small of
                                   the back)
``TORSO_HOLE_CM2`` 15 lies between the largest accepted hole (14.2) and the smallest defect (16.9) — a narrow
margin, measured on one piece; the edges of the accepted fits reach 73 cm2 (22354's hem), the skin under baked hair
80 - 204 cm2.

The image placement of such a fit is discarded (every vertex is re-expressed from the base fit), so its push
numbers are recorded, not gated (``garment_fit.PLACEMENT_GATE_KEYS``): after the seal the outfit bodies' unrigged
push-out moved 0.12 - 0.19 of the blazer more than 3 cm. A fit of an older FIT_VERSION is never served on an outfit
body once the fit replacing it is refused (``garments.body_fit``): the piece is left off with the reason.

Subtract hair: the cut labels the hair by the haired view against ITS base view (``garment_subtract._views``
reads the group's base copy) and places the haired mesh through ``place_mask`` — the current base front
registered into the haired views' frame; ``garment_cut.cut_hair`` refines with its ICP. HairDeck: no rule needed
— its job is keyed by the profile picture (``hsig``, no base) and a base change only refits from the stored seeds.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_source")

#: The trunk the frames are registered on: columns within this x Hb of the head's centre column.
TRUNK_HALF = 0.08
#: The head row (y0 + t x Hb) whose span centre is the trunk's centre column.
TRUNK_HEAD_ROW = 0.05
#: A registration whose mean outline distance stays above this x Hb did not find the body (the real trunks
#: settle at 0.003-0.004 Hb, the outline distance is truncated at 0.01 Hb): refused like one beyond the caps.
FRAME_RESIDUAL_MAX = 0.006
#: Limbs (module docstring LIMBS): a vertex farther than the limb radius + this from its limb is off the limb.
LIMB_OFF_M = 0.04
#: The off-limb share of a segment may exceed the source's by at most this.
LIMB_OFF_DELTA = 0.10
#: Fewer of the piece's vertices on a limb segment than this: the piece does not cover it (nothing to check).
LIMB_MIN_VERTICES = 50
#: Torso coverage (module docstring TORSO): a trunk vertex is covered with a garment vertex within this.
TORSO_COVER_M = 0.04
#: The trunk heights measured (0 = hip joint, 1 = neck joint) in this many bands x this many angles.
TORSO_V_RANGE = (-0.1, 1.0)
TORSO_BANDS = 10
TORSO_SECTORS = 12
#: A cell the source covers at least this much belongs to the area the fit must keep covered.
TORSO_SOURCE_COVERED = 0.5
#: The covered share of that area may fall at most this below the source's (front / side / back each).
TORSO_COVER_DELTA = 0.10
#: Torso holes (module docstring TORSO): the outer trunk surface is seen through the piece where no garment surface
#: lies within ``TORSO_SEE_LATERAL_M`` of the ray from the skin outward (radially from the trunk axis) between
#: ``TORSO_SEE_FROM_M`` and ``TORSO_SEE_DEPTH_M``; outer = within ``TORSO_OUTER_M`` of the outermost trunk vertex of
#: its direction (0.01 height x 2.5 degrees).
TORSO_SEE_LATERAL_M = 0.012
TORSO_SEE_FROM_M = 0.002
TORSO_SEE_DEPTH_M = 0.08
#: Seen skin with the piece within this under it: the piece lies under an outer layer of the body (outside the body
#: solid: baked hair over it — not a hole of the piece) or the body pokes through it (inside the solid: a hole).
TORSO_UNDER_DEPTH_M = 0.05
TORSO_OUTER_M = 0.008
#: The cells of the base fit's own openings (neckline, below the hem): this height step x this many angles; a cell
#: whose outer skin the base fit leaves seen at more than ``TORSO_OPEN_SHARE`` is open, a hole there is no defect.
TORSO_OPEN_V = 0.05
TORSO_OPEN_SECTORS = 24
TORSO_OPEN_SHARE = 0.5
#: The largest connected patch of skin seen through the piece where the base fit covers it may not exceed this.
TORSO_HOLE_CM2 = 15.0
#: The image "step" name of the base view copies (``base_copy``).
BASE_STEP = "base"
#: Marker key of a copied record (``materialize``).
COPIED = "copied_from"
MATERIALIZED = "materialized_from"
FRAME_REFUSED = "The new base front's framing differs beyond the registration caps"


class FrameRefused(Exception):
    """The trunk registration from the source's base front onto the target's leaves the caps (or finds no
    outline): the source cannot be placed on that body."""

    def __init__(self, registration: Optional[Dict[str, Any]]):
        reg = registration or {}
        detail = (f" (shift {reg.get('shift_abs')} Hb, scale {reg.get('scale')})" if reg else " (no outline)")
        super().__init__(FRAME_REFUSED + detail)
        self.registration = registration


# --- Files ------------------------------------------------------------------------

def source_steps(kind: str, method: str) -> Tuple[str, ...]:
    """The image steps whose finals make the source of ``method``: every image step of the kind for the edit
    chain, the haired views for subtract (their own mesh is the hair source mesh, keyed by their content)."""
    from app.core import garment_store as gs
    return ("haired",) if method == gs.SUBTRACT else gs.image_steps(kind)


def base_copy(character_name: str, item_id: str, fsig: str, view: str) -> Path:
    """``images/{item}_{fsig}_base_{view}.png``. ValueError like ``garment_store.garment_path``."""
    from app.core import garment_store as gs
    image = gs.garment_path(character_name, item_id, fsig, "image", step="cutout", view=view)
    return image.with_name(f"{item_id}_{fsig}_{BASE_STEP}_{view}.png")


def source_of(character_name: str, item_id: str, fsig: str) -> Dict[str, Any]:
    """The base record of the group (``{bsig, base_images, origin_fsig, ...}``), {} without both copies."""
    from app.core import garment_store as gs
    paths = {v: base_copy(character_name, item_id, fsig, v) for v in gs.GARMENT_VIEWS}
    if not all(p.is_file() for p in paths.values()):
        return {}
    record = gs.read_record(paths["front"].with_suffix(".json"))
    return record if record.get("bsig") and isinstance(record.get("base_images"), dict) else {}


def is_materialized(character_name: str, item_id: str, fsig: str) -> bool:
    """Whether the group carries a source copied from another group (``materialize``)."""
    return bool(source_of(character_name, item_id, fsig).get(MATERIALIZED))


def _copy_file(src: Path, dst: Path) -> None:
    """Copy through a temp file + replace (never in place: ``dst`` may be read meanwhile)."""
    import os
    import threading
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        if src.suffix.lower() == dst.suffix.lower():
            shutil.copyfile(src, tmp)
        else:
            from PIL import Image
            with Image.open(src) as im:
                im.save(tmp, format="PNG")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_base_copy(character_name: str, item_id: str, fsig: str, *, bsig: str, expected: Dict[str, str],
                     origin_fsig: str = "") -> bool:
    """Keep the base views of ``bsig`` with the group ``fsig`` — when both are on disk with exactly the sha256
    of ``expected`` (the base views the group's images were made on). True when the group has its copies (now or
    already). A group that has them is never rewritten."""
    from app.core import base_body, garment_store as gs
    from app.core.model_refs import find_ref_image
    from app.core.timeutils import utc_now_iso
    if source_of(character_name, item_id, fsig):
        return True
    if not bsig or not isinstance(expected, dict):
        return False
    views = {}
    for view in gs.GARMENT_VIEWS:
        path = find_ref_image(character_name, base_body._kind(view), bsig)
        if path is None or not expected.get(view) or base_body.file_sha256(path) != expected.get(view):
            return False
        views[view] = path
    for view, path in views.items():
        _copy_file(path, base_copy(character_name, item_id, fsig, view))
    back = base_copy(character_name, item_id, fsig, "back")
    gs.write_record(back.with_suffix(".json"), {"bsig": bsig, "view": "back"})
    # The front's record last: it makes the copies a source (``source_of``).
    gs.write_record(base_copy(character_name, item_id, fsig, "front").with_suffix(".json"),
                    {"bsig": bsig, "base_images": {v: expected[v] for v in gs.GARMENT_VIEWS},
                     "origin_fsig": origin_fsig or fsig, "created_at": utc_now_iso()})
    return True


def current_base_images(character_name: str, bsig: str) -> Dict[str, str]:
    """view -> sha256 of the base views of ``bsig`` as they are on disk now ("" for a missing one)."""
    from app.core import base_body, garment_store as gs
    from app.core.model_refs import find_ref_image
    return {v: base_body.file_sha256(find_ref_image(character_name, base_body._kind(v), bsig))
            for v in gs.GARMENT_VIEWS}


def ensure_current(character_name: str, item_id: str, fsig: str, bsig: str) -> bool:
    """``ensure_base_copy`` with the CURRENT base views of ``bsig`` — for a group of the current image fsig,
    whose fingerprint names exactly these views."""
    return ensure_base_copy(character_name, item_id, fsig, bsig=bsig,
                            expected=current_base_images(character_name, bsig))


def backfill(character_name: str) -> int:
    """Keep the base views with every image group an accepted base-body fit was made from (the fit's own group;
    subtract: its ``image_fsig``), where they are still on disk unchanged (the boot refit sweep, so a group made
    before this module keeps its frame when the base images are rendered again). Returns the groups copied."""
    from app.core import garment_store as gs
    root = gs._root(character_name)
    done = 0
    for (item_id, fsig), files in sorted(gs.stored_groups(character_name).items()):
        for path in files:
            if path.suffix != ".glb" or path.parent != root:
                continue
            record = gs.read_record(path.with_suffix(".json"))
            inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
            if record.get("accepted") is not True or gs.fit_method(record) == gs.HAIRDECK:
                continue
            group = str(inputs.get("image_fsig") or "") if gs.fit_method(record) == gs.SUBTRACT else fsig
            try:
                if source_of(character_name, item_id, group):
                    continue
                if ensure_base_copy(character_name, item_id, group, bsig=str(record.get("base_signature") or ""),
                                    expected=inputs.get("base_images") or {}):
                    done += 1
            except (OSError, ValueError) as e:
                logger.warning("Base view copy %s/%s (%s) failed: %s", character_name, item_id, group, e)
    return done


# --- Finding and materialising a source -------------------------------------------

def _accepted(path: Path) -> bool:
    from app.core import garment_store as gs
    return path.is_file() and gs.read_record(path.with_suffix(".json")).get("accepted") is True


def has_own_images(character_name: str, item_id: str, kind: str, method: str, fsig: str) -> bool:
    """Whether the group ``fsig`` holds an accepted image of the method's first step that was rendered for it
    (not copied in by ``materialize``)."""
    from app.core import garment_store as gs
    step = source_steps(kind, method)[0]
    for view in gs.GARMENT_VIEWS:
        path = gs.garment_path(character_name, item_id, fsig, "image", step=step, view=view)
        if _accepted(path) and not gs.read_record(path.with_suffix(".json")).get(COPIED):
            return True
    return False


def _complete(character_name: str, item_id: str, kind: str, method: str, group: str) -> bool:
    """The group holds every accepted image final of the method, its prepared mesh (edit chain) or the hair
    source mesh of its haired views (subtract)."""
    from app.core import garment_store as gs
    for step in source_steps(kind, method):
        for view in gs.GARMENT_VIEWS:
            if not _accepted(gs.garment_path(character_name, item_id, group, "image", step=step, view=view)):
                return False
    if method == gs.SUBTRACT:
        from app.core import garment_subtract
        ssig = gs._md5({"haired": gs.haired_shas(character_name, item_id, group), "version": gs.SOURCE_VERSION})
        return garment_subtract.source_glb(character_name, item_id, ssig) is not None
    return _accepted(gs.garment_path(character_name, item_id, group, "prepared"))


def find_source(character_name: str, item_id: str, kind: str, method: str, profile: Dict[str, Any],
                current: str) -> Optional[Dict[str, Any]]:
    """The last accepted source of the item for ``method`` other than the image group ``current`` (module
    docstring, REFIT 1): ``{fsig (the group), origin_fsig, bsig, base_images, fit (file name)}``, None without
    one. Edit chain and subtract only."""
    from app.core import garment_store as gs
    if method not in (gs.EDIT_CHAIN, gs.SUBTRACT):
        return None
    root = gs._root(character_name)
    fits = []
    for (iid, fsig), files in gs.stored_groups(character_name).items():
        if iid != item_id:
            continue
        for path in files:
            if path.suffix != ".glb" or path.parent != root:
                continue
            record = gs.read_record(path.with_suffix(".json"))
            if record.get("accepted") is not True or gs.fit_method(record) != method:
                continue
            try:
                fits.append((path.stat().st_mtime_ns, fsig, path, record))
            except OSError:
                continue
    seen = set()
    for _mtime, fsig, path, record in sorted(fits, key=lambda f: f[0], reverse=True):
        inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
        group = str(inputs.get("image_fsig") or "") if method == gs.SUBTRACT else fsig
        if not group or group == current or group in seen:
            continue
        seen.add(group)
        try:
            origin = source_of(character_name, item_id, group) or {
                "bsig": str(record.get("base_signature") or ""), "base_images": inputs.get("base_images") or {},
                "origin_fsig": group}
            if gs.edit_fsig_on(character_name, item_id, kind, profile, bsig=str(origin.get("bsig") or ""),
                               base_images=origin.get("base_images") or {}) != origin.get("origin_fsig"):
                continue  # the piece's own inputs changed: a re-render
            if not _complete(character_name, item_id, kind, method, group):
                continue
            if not ensure_base_copy(character_name, item_id, group, bsig=str(origin.get("bsig") or ""),
                                    expected=origin.get("base_images") or {},
                                    origin_fsig=str(origin.get("origin_fsig") or group)):
                continue  # the frame of its images is gone
        except (OSError, ValueError) as e:
            logger.warning("Garment source %s/%s (%s) unusable: %s", character_name, item_id, group, e)
            continue
        origin = source_of(character_name, item_id, group)
        return {"fsig": group, "origin_fsig": origin.get("origin_fsig") or group, "bsig": origin.get("bsig"),
                "base_images": origin.get("base_images"), "fit": path.name}
    return None


def materialize(character_name: str, item_id: str, kind: str, method: str, source: str, target: str) -> None:
    """Copy the source group's image finals (+ records, marked ``copied_from``), its prepared mesh (edit chain)
    and its base view copies (the base record last, marked ``materialized_from``) into the group ``target``."""
    from app.core import garment_store as gs
    from app.core.timeutils import utc_now_iso

    def copy(src: Path, dst: Path, extra: Dict[str, Any]) -> None:
        _copy_file(src, dst)
        record = gs.read_record(src.with_suffix(".json"))
        gs.write_record(dst.with_suffix(".json"), {**record, **extra})

    for step in source_steps(kind, method):
        for view in gs.GARMENT_VIEWS:
            copy(gs.garment_path(character_name, item_id, source, "image", step=step, view=view),
                 gs.garment_path(character_name, item_id, target, "image", step=step, view=view),
                 {COPIED: source})
    if method == gs.EDIT_CHAIN:
        copy(gs.garment_path(character_name, item_id, source, "prepared"),
             gs.garment_path(character_name, item_id, target, "prepared"), {COPIED: source})
    copy(base_copy(character_name, item_id, source, "back"), base_copy(character_name, item_id, target, "back"),
         {COPIED: source})
    copy(base_copy(character_name, item_id, source, "front"), base_copy(character_name, item_id, target, "front"),
         {MATERIALIZED: source, "materialized_at": utc_now_iso(),
          "limbs": source_limbs(character_name, item_id, source)})
    write_limb_source(character_name, item_id, source, target)
    logger.info("Garment %s/%s: source %s copied into %s", character_name, item_id, source, target)


def drop_materialized(character_name: str, item_id: str, fsig: str) -> int:
    """Remove every file ``materialize`` copied into the group ``fsig`` (records marked ``copied_from`` /
    ``materialized_from``: image finals, the prepared mesh, the base copies); rendered files stay. Returns the
    files removed. The base record goes first: the group stops being a source at once."""
    from app.core import garment_store as gs
    paths = [base_copy(character_name, item_id, fsig, "front"), base_copy(character_name, item_id, fsig, "back")]
    paths += [gs.garment_path(character_name, item_id, fsig, "image", step=step, view=view)
              for step in gs.IMAGE_STEPS for view in gs.GARMENT_VIEWS]
    paths.append(gs.garment_path(character_name, item_id, fsig, "prepared"))
    removed = 0
    limbs = gs.garment_path(character_name, item_id, fsig, "limbs")
    if limbs.is_file():  # only ``materialize`` writes one
        limbs.unlink()
        removed += 1
    for path in paths:
        record = gs.read_record(path.with_suffix(".json"))
        if not (record.get(COPIED) or record.get(MATERIALIZED)):
            continue
        path.with_suffix(".json").unlink(missing_ok=True)
        if path.is_file():
            path.unlink()
            removed += 1
    if removed:
        logger.info("Garment %s/%s: copied source dropped from %s (%d files)", character_name, item_id, fsig,
                    removed)
    return removed


def fit_source(character_name: str, item_id: str, fsig: str, base_images: Dict[str, str]) -> Dict[str, Any]:
    """The fit record's ``source`` block of the image group ``fsig`` (``{fsig, bsig, base_images
    [, materialized_from]}``) and whether the fit is a refit: ``(source, refitted)`` as a dict with the two
    keys ``source`` / ``refitted``. ``refitted`` = the group's images were made on other base views than
    ``base_images`` (the base the fit stands on)."""
    try:
        record = source_of(character_name, item_id, fsig) if fsig else {}
    except ValueError:
        record = {}
    if not record:
        return {"source": None, "refitted": False}
    source = {"fsig": record.get("origin_fsig") or fsig, "bsig": record.get("bsig"),
              "base_images": record.get("base_images")}
    if record.get(MATERIALIZED):
        source["materialized_from"] = record.get(MATERIALIZED)
    return {"source": source, "refitted": dict(record.get("base_images") or {}) != dict(base_images or {})}


# --- Frames ---------------------------------------------------------------------------

def _pad(mask: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    """A full-frame mask moved onto another view's canvas (``garment_cut.pad_into``)."""
    from app.core import garment_cut
    mask = np.asarray(mask, bool)
    if mask.shape == tuple(shape):
        return mask
    return garment_cut.pad_into(np.zeros(mask.shape + (3,), np.float32), mask, shape)[1]


def trunk(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """``(the mask within TRUNK_HALF x Hb of the head's centre column, Hb in px)``; Hb 0 for an empty mask."""
    mask = np.asarray(mask, bool)
    rows = np.nonzero(mask.any(1))[0]
    if not len(rows):
        return mask, 0
    hb = int(rows.max() - rows.min() + 1)
    row = mask[min(len(mask) - 1, int(rows.min() + TRUNK_HEAD_ROW * hb))]
    cols = np.nonzero(row)[0]
    if not len(cols):
        return mask, hb
    centre = (cols.min() + cols.max()) / 2.0
    keep = np.zeros_like(mask)
    x0, x1 = int(round(centre - TRUNK_HALF * hb)), int(round(centre + TRUNK_HALF * hb)) + 1
    keep[:, max(0, x0):max(0, x1)] = True
    return mask & keep, hb


def register_frames(source_mask: np.ndarray, target_mask: np.ndarray) -> Dict[str, Any]:
    """The similarity that lays the body of ``source_mask`` (padded onto the target's canvas) onto the body of
    ``target_mask`` (``garment_gates.register`` on their trunks). ``FrameRefused`` when it leaves the caps, its
    residual outline distance stays above ``FRAME_RESIDUAL_MAX`` x Hb, or it finds no outline."""
    from app.core import garment_gates
    target = np.asarray(target_mask, bool)
    reference, hb = trunk(target)
    moving, _hb = trunk(_pad(source_mask, target.shape))
    reg = garment_gates.register(reference, moving, body_h=hb) if hb else None
    residual = (reg or {}).get("fit_px") or [None, None]
    if reg is None or not reg.get("within_caps") or residual[1] is None or residual[1] > FRAME_RESIDUAL_MAX * hb:
        raise FrameRefused(reg)
    return reg


def _flat_mask(path: Path, refs_dir: Path) -> Tuple[np.ndarray, Tuple[int, int]]:
    """The full-frame BiRefNet mask of a view flattened on the neutral grey (as the fit always took it)."""
    from app.core import garment_images as gi
    from app.core.model_refs import neutral_view_reference
    with neutral_view_reference(Path(path), refs_dir) as flat:
        size = gi._image_size(flat)
        return gi._mask(flat, size), size


def fit_masks(character_name: str, item_id: str, fsig: str, *, body_front: Path,
              base_front: Path) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """``(body mask, ghost mask, frame)`` for the fit of the group ``fsig``: the body mask of ``body_front`` (the
    view the body was meshed from) and the accepted ghost front's mask in its frame. The ghost was made on the
    group's base copy; when that is not ``base_front`` (the base front of the body's base), it is registered onto
    it (``register_frames``) — ``frame`` ``{registered, registration?, source_bsig?}``. ``FrameRefused`` beyond
    the caps."""
    from app.core import base_body, garment_images as gi, garment_store as gs
    from app.core.model_refs import get_model_refs_dir
    refs = get_model_refs_dir(character_name)
    ghost = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view="front")
    body_mask, size = _flat_mask(body_front, refs)
    copy = base_copy(character_name, item_id, fsig, "front")
    source = source_of(character_name, item_id, fsig)
    if not source or base_body.file_sha256(copy) == base_body.file_sha256(Path(base_front)):
        return body_mask, gi._mask(ghost, size), {"registered": False}
    source_mask, source_size = _flat_mask(copy, refs)
    target = body_mask if Path(base_front) == Path(body_front) else _flat_mask(base_front, refs)[0]
    reg = register_frames(source_mask, target)
    ghost_mask = _pad(warp_mask(_pad(gi._mask(ghost, source_size), target.shape), reg), body_mask.shape)
    return body_mask, ghost_mask, {"registered": True, "registration": reg, "source_bsig": source.get("bsig")}


def place_registration(character_name: str, item_id: str, fsig: str, base_front: Path,
                       shape: Tuple[int, int]) -> Optional[Dict[str, Any]]:
    """The similarity that lays ``base_front`` (the current base front), padded onto the canvas ``shape`` of the
    group's haired views, onto the group's base copy (trunks, ``register_frames``) — None when the copy IS that
    view (or there is none). ``FrameRefused`` beyond the caps."""
    from app.core import base_body, garment_cut
    copy = base_copy(character_name, item_id, fsig, "front")
    if not source_of(character_name, item_id, fsig) or \
            base_body.file_sha256(copy) == base_body.file_sha256(Path(base_front)):
        return None
    _rgb, source = garment_cut._figure_mask(copy.read_bytes())
    _rgb, current = garment_cut._figure_mask(Path(base_front).read_bytes())
    return register_frames(_pad(current, shape), _pad(source, shape))


def place_mask(character_name: str, item_id: str, fsig: str, base_front: Path,
               shape: Tuple[int, int]) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """The subtract cut's ``place_mask``: the silhouette of ``base_front`` (the current base front the unrigged
    body was meshed from) in the frame of the group's haired views (``shape``) — None (the cut's default, the base
    view of the group) when the group's base copy IS that view (``place_registration``). ``(mask, frame)``;
    ``FrameRefused`` beyond the caps."""
    from app.core import garment_cut
    reg = place_registration(character_name, item_id, fsig, base_front, shape)
    if reg is None:
        return None, {"registered": False}
    _rgb, current = garment_cut._figure_mask(Path(base_front).read_bytes())
    return warp_mask(_pad(current, shape), reg), {"registered": True, "registration": reg}


def warp_mask(mask: np.ndarray, reg: Dict[str, Any]) -> np.ndarray:
    """``garment_gates.warp`` unless the registration is negligible."""
    if reg.get("negligible"):
        return np.asarray(mask, bool)
    from app.core import garment_gates
    return garment_gates.warp(np.asarray(mask, bool), reg)


# --- Limbs ------------------------------------------------------------------------------------

def _limb_bones(kind: str) -> Tuple[str, ...]:
    return ("arm", "forearm", "hand") if kind == "arm" else ("upleg", "leg", "foot")


def limb_numbers(positions, body) -> Optional[Dict[str, Any]]:
    """Per limb chain (``garment_fit.limb_frames``) of the rigged ``body`` (``glb_mesh.BodyMesh``), the part of the
    garment vertices ``positions`` (same bind space) on it — those whose nearest body vertex is dominated by one of
    the chain's bones: ``{chain: {vertices, reach_m, off [segment 0, segment 1]} | None}`` (module docstring LIMBS;
    ``off`` per segment None below ``LIMB_MIN_VERTICES``, the chain None when neither segment has them; segment 0
    counts from a quarter of its length, past the shoulder / hip seam). ``reach_m``: the p99 distance along the
    chain from the proximal joint. None when the body has no limb chain."""
    from scipy.spatial import cKDTree
    from app.core import garment_fit
    from app.core.rig_contract import norm_bone_name
    frames = garment_fit.limb_frames(body)
    if not frames:
        return None
    X = np.asarray(positions, np.float64)
    P = np.asarray(body.positions, np.float64)
    dominant = garment_fit.dense_weights(body).argmax(1)
    nearest = cKDTree(P).query(X)[1] if len(X) else np.zeros(0, np.int64)
    out: Dict[str, Any] = {}
    for name, frame in frames.items():
        side = name.split("_")[0]
        cols = [garment_fit.joint_index(body, side + bone) for bone in _limb_bones(frame["kind"])
                if any(norm_bone_name(n) == side + bone for n in body.joint_names)]
        S = X[np.isin(dominant, cols)[nearest]] if len(X) and cols else np.zeros((0, 3))
        pts = np.asarray(frame["points"], np.float64)
        radii = frame["radii"]
        lengths = [float(np.linalg.norm(pts[i + 1] - pts[i])) for i in range(len(pts) - 1)]
        ts = [(S - pts[i]) @ (pts[i + 1] - pts[i]) / max(lengths[i] ** 2, 1e-12) for i in range(2)]
        excess = np.min([garment_fit.segment_distance(S, pts[i], pts[i + 1]) - radii[i]
                         for i in range(len(pts) - 1)], axis=0) if len(S) else np.zeros(0)
        masks = [(ts[0] >= 0.25) & (ts[1] < 0), (ts[1] >= 0) & (ts[1] <= 1)]
        off = [round(float((excess[m] > LIMB_OFF_M).mean()), 4) if int(m.sum()) >= LIMB_MIN_VERTICES else None
               for m in masks]
        if off == [None, None]:
            out[name] = None
            continue
        along = np.where(ts[1] >= 0, lengths[0] + ts[1] * lengths[1], ts[0] * lengths[0])
        out[name] = {"vertices": int(sum(int(m.sum()) for m in masks)),
                     "reach_m": round(float(np.percentile(along, 99)), 4), "off": off}
    return out


def limb_source_from_fit(blob: bytes, *, skirt: bool = False, torso: bool = False) -> Optional[Dict[str, Any]]:
    """``garment_fit.fit_clothing``'s ``limb_source`` from a fit GLB (the garment grafted on its body): its
    vertices, its skin weights on the limb (and with ``torso`` the trunk) bones, and the frames of the limb chains
    the piece COVERS (``limb_numbers`` not None — a blazer's hem carries thigh weights but is no trouser leg; legs
    never for a skirt) plus, with ``torso`` (a fit on an outfit body), the trunk (``garment_fit.torso_frame``).
    ``numbers`` = the covered limbs' numbers, ``torso_cover`` / ``torso_open`` (with ``torso``) the trunk coverage
    (``torso_cover``) and the base fit's openings (``torso_open``), the gates' sources. None without anything to
    align."""
    from app.core import garment_fit, glb_mesh
    from app.core.rig_contract import norm_bone_name
    garment = glb_mesh.garment_arrays(blob)
    body = glb_mesh.body_arrays(blob)
    covered = limb_numbers(garment.positions, body) or {}
    frames = {name: frame for name, frame in garment_fit.limb_frames(body).items()
              if covered.get(name) and not (skirt and frame["kind"] == "leg")}
    keep = {side + bone for side in ("left", "right") for kind in ("arm", "leg") for bone in _limb_bones(kind)}
    kinds = ["arm"] if skirt else ["arm", "leg"]
    cover = opening = None
    if torso:
        trunk = garment_fit.torso_frame(body)
        if trunk is not None:
            frames["torso"] = trunk
            kinds.append("torso")
            cover = torso_cover(garment.positions, body)
            opening = torso_open(garment.positions, garment.indices, body)
    names = [n for n in garment.joint_names
             if norm_bone_name(n) in keep or ("torso" in frames and garment_fit.torso_bone(norm_bone_name(n)))]
    if not frames or not names:
        return None
    col = {n: i for i, n in enumerate(names)}
    J, Wt = np.asarray(garment.joints, np.int64), np.asarray(garment.weights, np.float64)
    W0 = np.zeros((len(garment.positions), len(names)), np.float32)
    for c in range(J.shape[1]):
        for j, name in enumerate(garment.joint_names):
            if name in col:
                rows = J[:, c] == j
                W0[rows, col[name]] += Wt[rows, c]
    return {"x0": np.asarray(garment.positions, np.float32), "w0": W0, "names0": names, "frames": frames,
            "kinds": kinds, "numbers": covered, "torso_cover": cover, "torso_open": opening}


def write_limb_source(character_name: str, item_id: str, source: str, target: str) -> bool:
    """Keep the source group's limb source (``limb_source_from_fit`` of its fit) with the refitted group ``target``
    (``limbs/{item}_{target}.npz``). False when the source fit is unreadable or has no limb."""
    import io
    import json
    import os
    from app.core import garment_store as gs
    fit = gs.garment_path(character_name, item_id, source, "fit")
    try:
        skirt = bool((gs.read_record(fit.with_suffix(".json")).get("report") or {}).get("skirt"))
        data = limb_source_from_fit(fit.read_bytes(), skirt=skirt)
    except (OSError, ValueError, KeyError) as e:
        logger.warning("Garment source %s/%s (%s): no limb source: %s", character_name, item_id, source, e)
        return False
    if data is None:
        return False
    path = gs.garment_path(character_name, item_id, target, "limbs")
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    np.savez_compressed(buf, x0=data["x0"], w0=data["w0"].astype(np.float16),
                        meta=np.frombuffer(json.dumps({"names0": data["names0"], "frames": data["frames"],
                                                       "kinds": data["kinds"], "source": source}).encode(), np.uint8))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, path)
    return True


def limb_source(character_name: str, item_id: str, fsig: str) -> Optional[Dict[str, Any]]:
    """The group's kept limb source (``write_limb_source``), None without one."""
    import json
    from app.core import garment_store as gs
    path = gs.garment_path(character_name, item_id, fsig, "limbs")
    try:
        with np.load(path) as npz:
            meta = json.loads(bytes(npz["meta"]).decode())
            return {"x0": npz["x0"].astype(np.float64), "w0": npz["w0"].astype(np.float64), **meta}
    except (OSError, ValueError, KeyError):
        return None


def source_limbs(character_name: str, item_id: str, fsig: str) -> Optional[Dict[str, Any]]:
    """The limb numbers the group ``fsig``'s pieces are checked against: those its own base record carries (it is
    itself a refit) else ``limb_numbers`` of its fit on its own base. None without a limb (or a readable fit)."""
    from app.core import garment_store as gs, glb_mesh
    record = source_of(character_name, item_id, fsig)
    if record.get(MATERIALIZED):
        return record.get("limbs")
    fit = gs.garment_path(character_name, item_id, fsig, "fit")
    try:
        blob = fit.read_bytes()
        numbers = limb_numbers(glb_mesh.garment_arrays(blob).positions, glb_mesh.body_arrays(blob))
    except (OSError, ValueError, KeyError) as e:
        logger.warning("Garment source %s/%s (%s): limbs not measurable: %s", character_name, item_id, fsig, e)
        return None
    if not numbers or not any(numbers.values()):
        return None
    return numbers


def limb_gate(numbers: Optional[Dict[str, Any]], source: Dict[str, Any]) -> Dict[str, Any]:
    """``{ok, reasons, fit, source, limits}``: the refit's limb numbers against the source's (module docstring
    LIMBS) — only "sits on the limb": a segment the source covers whose off-limb share grew by more than
    ``LIMB_OFF_DELTA``, or a limb the source covers that the refit lost. The reach is recorded, never a reason."""
    reasons = []
    for name, want in sorted((source or {}).items()):
        if not isinstance(want, dict) or "off" not in want:
            continue
        got = (numbers or {}).get(name)
        label = name.replace("_", " ")
        if not got:
            reasons.append(f"{label}: the piece is gone from the limb")
            continue
        for seg, (w, g) in enumerate(zip(want["off"], got["off"])):
            if w is None:
                continue
            part = ("upper arm", "forearm") if name.endswith("arm") else ("thigh", "shin")
            if g is None or g - w > LIMB_OFF_DELTA:
                reasons.append(f"{label}: off the {part[seg]} — {g} of its vertices beyond the limb + "
                               f"{LIMB_OFF_M * 100:.0f} cm (source {w}, limit +{LIMB_OFF_DELTA})")
    return {"ok": not reasons, "reasons": reasons, "fit": numbers, "source": source,
            "limits": {"off_m": LIMB_OFF_M, "off_delta": LIMB_OFF_DELTA}}


def check_limbs(character_name: str, item_id: str, fsig: str, positions, rigged_glb: bytes,
                frame: Dict[str, Any], source: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """``limb_gate`` of a fit against ``source`` (limb numbers; an outfit-body fit: its base fit's) or, without
    one, of a REGISTERED fit (``frame.registered``) of the group ``fsig`` against its source's; None when there is
    nothing to check (a native fit, a source without limbs)."""
    if source is None:
        if not frame.get("registered"):
            return None
        source = source_of(character_name, item_id, fsig).get("limbs")
    if not source:
        return None
    from app.core import glb_mesh
    return limb_gate(limb_numbers(positions, glb_mesh.body_arrays(rigged_glb)), source)


# --- Torso coverage (outfit bodies) -----------------------------------------------------------------------

def torso_cover(positions, body) -> Optional[Dict[str, Any]]:
    """Which part of the trunk of the rigged ``body`` the garment ``positions`` cover (module docstring TORSO):
    the trunk vertices (dominated by a ``garment_fit.trunk_bone``) from just below the hip joint to the neck joint
    in ``TORSO_BANDS`` heights x ``TORSO_SECTORS`` angles around the trunk axis; a vertex is covered with a garment
    vertex within ``TORSO_COVER_M``. ``{covered [[share per sector] per band], count [[...]]}``; None without a
    trunk."""
    from scipy.spatial import cKDTree
    from app.core import garment_fit
    from app.core.rig_contract import norm_bone_name
    frame = garment_fit.torso_frame(body)
    if frame is None:
        return None
    names = [norm_bone_name(n) for n in body.joint_names]
    cols = [i for i, n in enumerate(names) if garment_fit.trunk_bone(n)]
    P = np.asarray(body.positions, np.float64)
    T = P[np.isin(garment_fit.dense_weights(body).argmax(1), cols)]
    v, theta, _rho = garment_fit._torso_coords(T, frame)
    lo, hi = TORSO_V_RANGE
    inside = (v >= lo) & (v < hi)
    T, v, theta = T[inside], v[inside], theta[inside]
    band = np.clip(((v - lo) / (hi - lo) * TORSO_BANDS).astype(int), 0, TORSO_BANDS - 1)
    sector = ((theta + np.pi) / (2 * np.pi) * TORSO_SECTORS).astype(int) % TORSO_SECTORS
    X = np.asarray(positions, np.float64)
    hit = (cKDTree(X).query(T)[0] <= TORSO_COVER_M) if len(X) else np.zeros(len(T), bool)
    covered = np.zeros((TORSO_BANDS, TORSO_SECTORS))
    count = np.zeros((TORSO_BANDS, TORSO_SECTORS))
    np.add.at(covered, (band, sector), hit)
    np.add.at(count, (band, sector), 1)
    return {"covered": (covered / np.maximum(count, 1)).round(4).tolist(), "count": count.astype(int).tolist()}


def _sector_group(k: int) -> str:
    centre = abs((k + 0.5) / TORSO_SECTORS * 360.0 - 180.0)  # 0 = front (+z)
    return "front" if centre <= 60 else ("back" if centre >= 120 else "side")


def torso_gate(fit: Optional[Dict[str, Any]], source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``{ok, reasons, shares, limits}``: per front / side / back the covered share of the trunk cells the SOURCE
    covers (share >= ``TORSO_SOURCE_COVERED``), each side counted with its own vertices; refused when the fit's
    share is more than ``TORSO_COVER_DELTA`` below the source's."""
    reasons: List[str] = []
    shares: Dict[str, Any] = {}
    if source and fit:
        cs, ns = np.asarray(source["covered"]), np.asarray(source["count"])
        cf, nf = np.asarray(fit["covered"]), np.asarray(fit["count"])
        region = cs >= TORSO_SOURCE_COVERED
        for group in ("front", "side", "back"):
            cols = np.array([_sector_group(k) == group for k in range(TORSO_SECTORS)])
            cells = region & cols[None, :]
            if ns[cells].sum() == 0 or nf[cells].sum() == 0:
                continue
            want = float((cs * ns)[cells].sum() / ns[cells].sum())
            got = float((cf * nf)[cells].sum() / nf[cells].sum())
            shares[group] = {"fit": round(got, 4), "source": round(want, 4)}
            if want - got > TORSO_COVER_DELTA:
                reasons.append(f"torso {group}: {got:.2f} of the area the source covers is covered within "
                               f"{TORSO_COVER_M * 100:.0f} cm (source {want:.2f}, limit -{TORSO_COVER_DELTA})")
    elif source and not fit:
        reasons.append("torso: not measurable on this body")
    return {"ok": not reasons, "reasons": reasons, "shares": shares,
            "limits": {"cover_m": TORSO_COVER_M, "cover_delta": TORSO_COVER_DELTA}}


# --- Torso holes (outfit bodies) --------------------------------------------------------------------------------

def _welded(body) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(positions, faces, representative original vertex)`` of the body welded by position (a GLB splits its
    vertices at the UV seams; a patch must not end there)."""
    P = np.asarray(body.positions, np.float64)
    _, first, inverse = np.unique(np.round(P / 1e-5).astype(np.int64), axis=0, return_index=True,
                                  return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    F = inverse[np.asarray(body.faces, np.int64).reshape(-1, 3)]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    return P[first], F, first


def _trunk_seen(positions, faces, body) -> Optional[Dict[str, Any]]:
    """The outer trunk skin of the rigged ``body`` (welded) and which of it is seen through the garment
    (``positions`` / ``faces``; block TORSO holes above): ``{P, F, area (per vertex, m2), region, seen (a hole:
    no piece over it, or the body through the piece), layered (the piece under an outer layer of the body), v,
    theta}``; None without a trunk."""
    from scipy.spatial import cKDTree
    from app.core import garment_fit
    from app.core.rig_contract import norm_bone_name
    frame = garment_fit.torso_frame(body)
    if frame is None:
        return None
    P, F, first = _welded(body)
    names = [norm_bone_name(n) for n in body.joint_names]
    dominant = garment_fit.dense_weights(body).argmax(1)[first]
    trunk = np.isin(dominant, [i for i, n in enumerate(names) if garment_fit.trunk_bone(n)])
    v, theta, rho = garment_fit._torso_coords(P, frame)
    lo, hi = TORSO_V_RANGE
    region = trunk & (v >= lo) & (v < hi)
    cell = np.floor(v / 0.01).astype(np.int64) * 1000 + np.floor((theta + np.pi) / np.radians(2.5)).astype(np.int64)
    rows = np.nonzero(region)[0]
    if len(rows):
        order = np.argsort(cell[rows])
        keys = cell[rows][order]
        starts = np.unique(keys, return_index=True)[1]
        top = np.repeat(np.maximum.reduceat(rho[rows][order], starts), np.diff(np.append(starts, len(keys))))
        outer = np.empty(len(rows), bool)
        outer[order] = rho[rows][order] >= top - TORSO_OUTER_M
        region[rows[~outer]] = False
    rows = np.nonzero(region)[0]
    # outward: the skin's normal, turned to face away from the trunk axis (a generated mesh may wind either way)
    normal = garment_fit.vertex_normals(P, F)[rows]
    radial = np.zeros((len(rows), 3))
    radial[:, 0], radial[:, 2] = np.sin(theta[rows]), np.cos(theta[rows])
    out = np.where(((normal * radial).sum(1) < 0)[:, None], -normal, normal)
    G = np.asarray(positions, np.float64)
    Fg = np.asarray(faces, np.int64).reshape(-1, 3)
    samples = garment_fit._surface_samples(G, Fg)[0] if len(Fg) else G
    covered = np.zeros(len(rows), bool)
    under = np.full(len(rows), -1, np.int64)   # the garment sample found under the skin's outer layer
    if len(samples) and len(rows):
        tree = cKDTree(samples)
        for step in np.arange(TORSO_SEE_FROM_M, TORSO_SEE_DEPTH_M, 0.008):
            todo = np.nonzero(~covered)[0]
            d = tree.query(P[rows[todo]] + step * out[todo], distance_upper_bound=TORSO_SEE_LATERAL_M)[0]
            covered[todo[d <= TORSO_SEE_LATERAL_M]] = True
        for step in np.arange(-TORSO_SEE_FROM_M, -TORSO_UNDER_DEPTH_M, -0.006):
            todo = np.nonzero(~covered & (under < 0))[0]
            d, j = tree.query(P[rows[todo]] + step * out[todo], distance_upper_bound=TORSO_SEE_LATERAL_M)
            under[todo[d <= TORSO_SEE_LATERAL_M]] = j[d <= TORSO_SEE_LATERAL_M]
    layered = np.zeros(len(rows), bool)
    found = np.nonzero(~covered & (under >= 0))[0]
    if len(found):
        # the piece lies under an outer layer of the body (baked hair over it) when it is outside the body solid
        # there; inside it, the body pokes through the piece — a hole
        Q = samples[under[found]]
        sdf = garment_fit.body_sdf(P, F, vox=garment_fit.VOX_M, bounds=(Q.min(0) - 0.02, Q.max(0) + 0.02))
        layered[found[sdf.sample(Q) > 0]] = True
    covered |= layered
    hidden = np.zeros(len(P), bool)
    hidden[rows[layered]] = True
    seen = np.zeros(len(P), bool)
    seen[rows[~covered]] = True
    tri = P[F]
    face_area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    area = np.zeros(len(P))
    for c in range(3):
        np.add.at(area, F[:, c], face_area / 3)
    return {"P": P, "F": F, "area": area, "region": region, "seen": seen, "layered": hidden, "v": v,
            "theta": theta}


def _open_cell(v: np.ndarray, theta: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    lo, hi = TORSO_V_RANGE
    bands = int(round((hi - lo) / TORSO_OPEN_V))
    band = np.clip(np.floor((v - lo) / TORSO_OPEN_V).astype(np.int64), 0, bands - 1)
    sector = np.floor((theta + np.pi) / (2 * np.pi) * TORSO_OPEN_SECTORS).astype(np.int64) % TORSO_OPEN_SECTORS
    return band, sector


def torso_open(positions, faces, body) -> Optional[List[List[bool]]]:
    """The base fit's own openings (block TORSO holes): per ``TORSO_OPEN_V`` band x ``TORSO_OPEN_SECTORS`` angle
    whether its outer trunk skin is seen at more than ``TORSO_OPEN_SHARE``. None without a trunk."""
    seen = _trunk_seen(positions, faces, body)
    if seen is None:
        return None
    lo, hi = TORSO_V_RANGE
    bands = int(round((hi - lo) / TORSO_OPEN_V))
    rows = np.nonzero(seen["region"])[0]
    band, sector = _open_cell(seen["v"][rows], seen["theta"][rows])
    total = np.zeros((bands, TORSO_OPEN_SECTORS))
    hidden = np.zeros((bands, TORSO_OPEN_SECTORS))
    np.add.at(total, (band, sector), seen["area"][rows])
    np.add.at(hidden, (band, sector), seen["area"][rows] * seen["seen"][rows])
    return (hidden > TORSO_OPEN_SHARE * np.maximum(total, 1e-12)).tolist()


def torso_holes(positions, faces, body, source_open: Optional[List[List[bool]]]) -> Optional[Dict[str, Any]]:
    """The connected patches of outer trunk skin seen through the garment (``_trunk_seen``), split by the base
    fit's openings (``source_open``, ``torso_open`` of the base fit): a patch that reaches into an open cell is an
    EDGE (the neckline or the hem lies elsewhere than on the base fit — the coverage share judges that), any other
    one a HOLE in the piece. ``{largest_cm2 (the largest hole), patches [{cm2, v, theta_deg}] (holes, largest first,
    at most 5), edge_cm2 (the largest edge, outside the open cells), under_layer_cm2 (skin over the piece: baked
    hair)}``, areas outside the open cells. None without a trunk or a source."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    if not source_open:
        return None
    seen = _trunk_seen(positions, faces, body)
    if seen is None:
        return None
    mask = seen["seen"]
    rows = np.nonzero(mask)[0]
    band, sector = _open_cell(seen["v"][rows], seen["theta"][rows])
    is_open = np.zeros(len(mask), bool)
    is_open[rows[np.asarray(source_open, bool)[band, sector]]] = True
    F = seen["F"]
    edges = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    edges = edges[mask[edges[:, 0]] & mask[edges[:, 1]]]
    n = len(seen["P"])
    _, label = connected_components(coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n)),
                                    directed=False)
    holes, edge = [], 0.0
    if mask.any():
        ids = label[mask]
        area = np.bincount(ids, weights=seen["area"][mask] * ~is_open[mask])
        touches = np.bincount(ids, weights=is_open[mask].astype(float)) > 0
        for c in np.argsort(-area):
            if area[c] <= 0:
                break
            if touches[c]:
                edge = max(edge, float(area[c]))
                continue
            if len(holes) < 5:
                m = mask & (label == c)
                th = seen["theta"][m]
                holes.append({"cm2": round(float(area[c]) * 1e4, 1), "v": round(float(seen["v"][m].mean()), 2),
                              "theta_deg": round(float(np.degrees(np.arctan2(np.sin(th).mean(),
                                                                             np.cos(th).mean()))))})
    return {"largest_cm2": holes[0]["cm2"] if holes else 0.0, "patches": holes,
            "edge_cm2": round(edge * 1e4, 1),
            "under_layer_cm2": round(float(seen["area"][seen["layered"]].sum()) * 1e4, 1)}


def torso_hole_gate(holes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``{ok, reasons, largest_cm2, limit_cm2}``: refused when the largest patch exceeds ``TORSO_HOLE_CM2``."""
    largest = float((holes or {}).get("largest_cm2") or 0.0)
    reasons = []
    if holes is not None and largest > TORSO_HOLE_CM2:
        where = (holes.get("patches") or [{}])[0]
        reasons.append(f"torso hole: {largest:.0f} cm2 of skin seen through the piece (height {where.get('v')}, "
                       f"angle {where.get('theta_deg')} deg; limit {TORSO_HOLE_CM2:.0f} cm2)")
    return {"ok": not reasons, "reasons": reasons, "largest_cm2": largest, "limit_cm2": TORSO_HOLE_CM2}
