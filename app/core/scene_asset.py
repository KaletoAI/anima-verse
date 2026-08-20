"""The scene-context pipeline — from a context plate to a placed, ground-checked mesh.

Stage 2–5 of the pipeline whose stage 1 is :mod:`app.core.scene_context`
(``docs/scene-asset-pipeline.md``, plan ``plan-assets-im-szenenkontext.md``
Etappe 4). The plate answers "what does this spot look like"; this module
answers "what stands there now":

1. **insert**  — an image model draws the object INTO the plate. Inpaint with
   the sidecar's mask polygon (grown) when the backend can take a mask, a full
   img2img edit of the whole plate otherwise.
2. **cutout**  — the difference between the plate before and after, inside the
   masked region, cleaned morphologically and intersected with ``rembg``. It
   becomes the target variant's SOURCE IMAGE (``props.save_source_image``),
   because that is what its mesh is made from and what a later re-mesh of the
   same variant must find. It is stamped ``origin "scene_context"`` with the
   location and the run's own start stamp: a cutout carries the light and the
   ground of ONE spot, so the admin has to be able to tell it from a product
   shot at a glance. The picture this spot showed BEFORE the run is copied into
   the run directory as ``before.png`` at trigger time — a run that refines the
   same variant overwrites the original a moment later, and a live URL would
   then show the after twice.
3. **mesh**    — the cutout (transparent background) through
   ``service.generate_mesh(rig="none")`` and Blender ``normalize`` to the
   prop's DECLARED height. The metric scale comes from the spec, never from
   the picture (deviation E4.4 from the WorldClaw paper).
4. **place**   — position stays the AUTHORED anchor; the yaw follows from the
   plate camera; a numeric contact check against the ground decides whether
   the placement sinks.

Everything geometric in here is a PURE function of numbers (mask maths, crop
affine, expected pixel size, yaw, contact/sink) so ``scripts/smoke_scene_asset.py``
can derive every value by hand. The impure half is one linear chain plus the
bounded retry loop around it.
"""
from __future__ import annotations

import json
import math
import random
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now, utc_now_iso

logger = get_logger("scene_asset")

Vec2 = Tuple[float, float]

# ── Dials (mirrored in config_schema as image_generation.scene_asset_*) ──
# Repeated here so the module also runs with no world loaded (smoke, CLI) —
# the same rule scene_context.render_params follows.

#: How far the sidecar's mask polygon grows before it becomes the inpaint
#: mask, as a fraction of its bounding box's LONGER side.
DEFAULT_MASK_MARGIN = 0.12
#: Per-channel difference (0..255) above which a pixel counts as changed.
DEFAULT_DIFF_THRESHOLD = 12
#: Extra margin around the cutout before it is enlarged for the mesher.
DEFAULT_CROP_MARGIN = 0.15
#: Edge length the cutout patch is enlarged to before image-to-3D.
DEFAULT_CROP_PX = 1024
#: Accepted deviation of the normalised mesh height from the declared one.
DEFAULT_HEIGHT_TOLERANCE = 0.10
#: Accepted band for (cutout pixel height) / (expected pixel height).
DEFAULT_PX_RATIO_MIN = 0.40
DEFAULT_PX_RATIO_MAX = 2.50
#: How close a footprint sample must be to the ground to count as contact.
DEFAULT_CONTACT_TOLERANCE_M = 0.05
#: Fraction of the 3×3 footprint samples that must be in contact.
DEFAULT_CONTACT_RATIO = 0.60
#: Drop across the footprint above which the result SUGGESTS local levelling.
DEFAULT_LEVEL_SLOPE_M = 0.10
#: Extra attempts with a fresh seed after the first one failed.
DEFAULT_RETRIES = 2
#: Clean the difference mask with rembg's alpha (u2net) as well.
DEFAULT_REMBG = True

#: Alpha above which a rembg pixel counts as foreground.
REMBG_ALPHA_MIN = 128

#: The use case both prompt families are configured under.
USE_CASE = "scene_asset"

#: Sub-directory of the prop dir every run writes into.
RUN_DIR_NAME = "scene_asset"

#: The sanitizer's clamp for ``offset_y`` — the sink must not propose a value
#: the placement sanitizer would then silently cut (world_ops._sanitize_props).
OFFSET_Y_LIMIT = 5.0

_lock = threading.Lock()
_running: set = set()


def params(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The pipeline's dials — schema defaults, world config, then overrides.

    An override key the dial list does not name survives as-is: that is how the
    optional ``seed`` reaches :func:`generate` without a second parameter
    channel beside the one the admin route already fills.
    """
    def cfg(key: str, default: Any) -> Any:
        try:
            from app.core import config
            val = config.get(f"image_generation.scene_asset_{key}", None)
        except Exception:
            return default
        return default if val is None or val == "" else val

    out: Dict[str, Any] = {
        "mask_margin": float(cfg("mask_margin", DEFAULT_MASK_MARGIN)),
        "diff_threshold": int(cfg("diff_threshold", DEFAULT_DIFF_THRESHOLD)),
        "crop_margin": float(cfg("crop_margin", DEFAULT_CROP_MARGIN)),
        "crop_px": int(cfg("crop_px", DEFAULT_CROP_PX)),
        "height_tolerance": float(cfg("height_tolerance",
                                      DEFAULT_HEIGHT_TOLERANCE)),
        "px_ratio_min": float(cfg("px_ratio_min", DEFAULT_PX_RATIO_MIN)),
        "px_ratio_max": float(cfg("px_ratio_max", DEFAULT_PX_RATIO_MAX)),
        "contact_tolerance_m": float(cfg("contact_tolerance_m",
                                         DEFAULT_CONTACT_TOLERANCE_M)),
        "contact_ratio": float(cfg("contact_ratio", DEFAULT_CONTACT_RATIO)),
        "level_slope_m": float(cfg("level_slope_m", DEFAULT_LEVEL_SLOPE_M)),
        "retries": int(cfg("retries", DEFAULT_RETRIES)),
        "rembg": bool(cfg("rembg", DEFAULT_REMBG)),
    }
    for key, value in (overrides or {}).items():
        if value is not None:
            out[key] = value
    return out


# ── Mask geometry (pure) ────────────────────────────────────────────────

def polygon_bbox(poly: Sequence[Sequence[float]]) -> List[float]:
    """``[x0, y0, x1, y1]`` of a pixel polygon."""
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def grow_px_for(poly: Sequence[Sequence[float]], margin: float) -> float:
    """How many pixels the mask grows: ``margin`` × the bbox's LONGER side.

    The longer side and not the diagonal or the area: the margin exists so the
    object's contact with the ground and its shadow fall inside the region,
    and both of those scale with the object's size on screen, not with its
    aspect ratio.
    """
    x0, y0, x1, y1 = polygon_bbox(poly)
    return max(0.0, float(margin)) * max(x1 - x0, y1 - y0)


def grow_polygon(poly: Sequence[Sequence[float]],
                 grow_px: float) -> List[List[float]]:
    """Grow a pixel polygon about its own centroid by ``grow_px`` pixels.

    The same rule ``scene_context.mask_polygon`` dilates with — every vertex
    moves outward along its own direction from the centroid — so a mask grown
    here and one grown at render time are the same shape.
    """
    pts = [[float(p[0]), float(p[1])] for p in poly or ()]
    if grow_px <= 0 or len(pts) < 3:
        return pts
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    out: List[List[float]] = []
    for px, py in pts:
        dx, dy = px - cx, py - cy
        n = math.hypot(dx, dy) or 1.0
        out.append([px + dx / n * grow_px, py + dy / n * grow_px])
    return out


def rasterize_polygon(poly: Sequence[Sequence[float]], width: int, height: int):
    """Polygon → boolean mask array ``(height, width)``, True inside.

    Even-odd crossing test on PIXEL CENTRES (``x + 0.5``): a mask is a set of
    pixels, and asking whether the pixel's corner is inside shifts the whole
    region by half a pixel — which is exactly the kind of error that only
    shows up as a one-pixel seam after the cutout.
    """
    import numpy as np

    mask = np.zeros((int(height), int(width)), dtype=bool)
    pts = [(float(p[0]), float(p[1])) for p in poly or ()]
    if len(pts) < 3:
        return mask
    ys = [p[1] for p in pts]
    y_lo = max(0, int(math.floor(min(ys))))
    y_hi = min(int(height) - 1, int(math.ceil(max(ys))))
    xs_grid = np.arange(int(width), dtype=float) + 0.5
    n = len(pts)
    for row in range(y_lo, y_hi + 1):
        yc = row + 0.5
        crossings: List[float] = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 > yc) == (y2 > yc):
                continue
            crossings.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
        crossings.sort()
        for i in range(0, len(crossings) - 1, 2):
            mask[row] |= (xs_grid >= crossings[i]) & (xs_grid <= crossings[i + 1])
    return mask


# ── Difference mask + morphology (pure) ─────────────────────────────────

def difference_mask(before, after, threshold: int = DEFAULT_DIFF_THRESHOLD):
    """Per-pixel change between two RGB arrays → boolean mask.

    The distance is the LARGEST absolute channel difference, not the mean and
    not the L2 norm: a change in brightness and a change in colour alone must
    both count, and an average lets a strong single-channel change hide under
    a threshold that was tuned on grey.
    """
    import numpy as np

    a = np.asarray(before).astype(np.int16)
    b = np.asarray(after).astype(np.int16)
    if a.shape != b.shape:
        raise ValueError(f"difference_mask: shapes differ {a.shape} vs {b.shape}")
    if a.ndim == 2:
        delta = np.abs(b - a)
    else:
        delta = np.max(np.abs(b - a), axis=2)
    return delta >= int(threshold)


def _shifted_all(mask):
    """Erosion by a 3×3 square: a pixel survives only with all 8 neighbours.

    Outside the image counts as EMPTY, so the border erodes — an object that
    runs out of the plate is not silently completed.
    """
    import numpy as np

    out = mask.copy()
    h, w = mask.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(mask)
            ys = slice(max(0, dy), h + min(0, dy))
            yd = slice(max(0, -dy), h + min(0, -dy))
            xs = slice(max(0, dx), w + min(0, dx))
            xd = slice(max(0, -dx), w + min(0, -dx))
            shifted[yd, xd] = mask[ys, xs]
            out &= shifted
    return out


def _shifted_any(mask):
    """Dilation by a 3×3 square."""
    import numpy as np

    out = mask.copy()
    h, w = mask.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(mask)
            ys = slice(max(0, dy), h + min(0, dy))
            yd = slice(max(0, -dy), h + min(0, -dy))
            xs = slice(max(0, dx), w + min(0, dx))
            xd = slice(max(0, -dx), w + min(0, -dx))
            shifted[yd, xd] = mask[ys, xs]
            out |= shifted
    return out


def morph_open(mask):
    """Erode, then dilate — kills specks, keeps a solid region's shape."""
    return _shifted_any(_shifted_all(mask))


def morph_close(mask):
    """Dilate, then erode — fills pinholes, keeps a solid region's shape."""
    return _shifted_all(_shifted_any(mask))


def clean_mask(mask):
    """Open THEN close. The order matters: closing first would grow a speck
    into a blob that the opening can no longer remove."""
    return morph_close(morph_open(mask))


def mask_bbox(mask) -> Optional[List[int]]:
    """``[x0, y0, x1, y1]`` (inclusive) of the True pixels, or None."""
    import numpy as np

    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return None
    y0, y1 = int(np.argmax(rows)), int(len(rows) - 1 - np.argmax(rows[::-1]))
    x0, x1 = int(np.argmax(cols)), int(len(cols) - 1 - np.argmax(cols[::-1]))
    return [x0, y0, x1, y1]


# ── Crop affine (pure) ──────────────────────────────────────────────────

def crop_affine(bbox: Sequence[float], img_w: int, img_h: int, *,
                out_px: int = DEFAULT_CROP_PX,
                margin: float = DEFAULT_CROP_MARGIN) -> Dict[str, Any]:
    """The crop+enlarge transform that feeds image-to-3D.

    A SQUARE crop around the cutout, grown by ``margin`` of its longer side and
    clamped into the plate, scaled to ``out_px``. The paper calls the result
    "equivalent intrinsics": the crop is an affine change of image coordinates,
    so the camera that took the plate also describes the patch — with
    ``fx' = fx·s`` and ``cx' = (cx − x0)·s``. Every later measurement in patch
    pixels can therefore be read back in plate pixels, which is what
    :func:`to_plate` does.
    """
    x0, y0, x1, y1 = (float(v) for v in bbox)
    side = max(x1 - x0, y1 - y0)
    side = side * (1.0 + 2.0 * max(0.0, float(margin)))
    side = min(side, float(min(img_w, img_h)))
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    left = min(max(cx - side / 2.0, 0.0), float(img_w) - side)
    top = min(max(cy - side / 2.0, 0.0), float(img_h) - side)
    scale = float(out_px) / side
    return {"x0": left, "y0": top, "side": side,
            "scale": scale, "size": int(out_px)}


def to_patch(u: float, v: float, aff: Dict[str, Any]) -> Vec2:
    """Plate pixel → patch pixel."""
    return ((float(u) - aff["x0"]) * aff["scale"],
            (float(v) - aff["y0"]) * aff["scale"])


def to_plate(u: float, v: float, aff: Dict[str, Any]) -> Vec2:
    """Patch pixel → plate pixel (the exact inverse of :func:`to_patch`)."""
    return (float(u) / aff["scale"] + aff["x0"],
            float(v) / aff["scale"] + aff["y0"])


def equivalent_intrinsics(camera: Dict[str, Any],
                          aff: Dict[str, Any]) -> Dict[str, float]:
    """The plate camera expressed in PATCH pixels (paper § 2.3)."""
    s = float(aff["scale"])
    return {"fx": float(camera["fx"]) * s, "fy": float(camera["fy"]) * s,
            "cx": (float(camera["cx"]) - aff["x0"]) * s,
            "cy": (float(camera["cy"]) - aff["y0"]) * s}


# ── Expected size on screen (pure) ──────────────────────────────────────

def expected_px_bbox(footprint: Sequence[Sequence[float]], base_y: float,
                     height_m: float, camera: Dict[str, Any]) -> List[float]:
    """The pixel box the target's own dimensions must occupy.

    Literally the undilated mask hull of ``scene_context.mask_polygon``: the
    box over the footprint, projected with the plate camera. The insert stage
    is judged against it — an object drawn half the size of its own footprint
    is a failed edit, not a small object.
    """
    from app.core.scene_context import mask_polygon

    hull = mask_polygon(footprint, base_y, height_m, camera, dilate_px=0.0)
    if len(hull) < 2:
        return [0.0, 0.0, 0.0, 0.0]
    return polygon_bbox(hull)


def px_size_ratio(cutout_bbox: Sequence[float],
                  expected_bbox: Sequence[float]) -> float:
    """Cutout pixel HEIGHT over expected pixel height.

    Height and not area: a mask that leaked into the ground shadow doubles the
    area long before it doubles the height, and the ratio has to say something
    about the OBJECT.
    """
    exp_h = float(expected_bbox[3]) - float(expected_bbox[1])
    got_h = float(cutout_bbox[3]) - float(cutout_bbox[1])
    if exp_h <= 0:
        return 0.0
    return got_h / exp_h


# ── Yaw (pure) ──────────────────────────────────────────────────────────

def placement_yaw_deg(camera_azimuth_deg: float) -> float:
    """The yaw that turns the reconstructed mesh's front back to the camera.

    THE DERIVATION, because a sign error here is invisible until a chair faces
    a wall:

    * The plate camera stands at map azimuth ``ψ`` AS SEEN FROM THE TARGET:
      ``position = centre + d·(cos ε·sin ψ, sin ε, cos ε·cos ψ)``
      (``scene_context.solve_camera``). So the direction target → camera is
      ``(sin ψ, cos ψ)``; the VIEWING direction, camera → target, is ``ψ+180``.
    * Image-to-3D reconstructs in the input view's frame: what the picture
      showed faces the viewer. In glTF terms that is local ``+Z``, and the
      glTF specification says as much — "the front of an asset faces +Z".
      Our scene frame is x east, y up, **z south**, so a mesh at yaw 0 faces
      SOUTH, which is exactly the contract's prop convention (facing 0 = south,
      ``room_recipe.compose_prop_marker``: "assume the prop's front is south in
      object space").
    * ``rot_y(yaw)`` maps the local direction ``(0, 1)`` — local south — to
      ``(sin yaw, cos yaw)``. A prop's front therefore points at map azimuth
      ``yaw``.
    * The front must point AT the camera, i.e. along ``(sin ψ, cos ψ)``:

          yaw = ψ  (mod 360)

    Not ``ψ + 180``: that is the direction the camera LOOKS, and turning the
    object into it would show the plate's picture from behind. With the plate's
    azimuth offset at 0 the formula returns the AUTHORED yaw unchanged, which
    is the sanity check the offset makes measurable — the default 45° offset is
    the whole difference between the authored orientation and the drawn one,
    and the picture is what the mesh has to reproduce. The per-model rotation
    fix stays available for a mesher that does not honour the glTF convention.
    """
    return float(camera_azimuth_deg) % 360.0


# ── Contact and sink (pure) ─────────────────────────────────────────────

def footprint_samples(anchor: Sequence[float], width_m: float, depth_m: float,
                      yaw_deg: float) -> List[List[float]]:
    """The 3×3 lattice over the bbox BOTTOM rectangle, in the scene frame.

    Nine points and not four: the corners alone miss a ridge running under the
    middle of an object, and a single centre point misses everything a slope
    does. Order is row-major in object space (−w, 0, +w) × (−d, 0, +d), so a
    hand-derived expectation can be written down in reading order.
    """
    from app.core.scene_context import mat_apply, rot_y

    rot = rot_y(float(yaw_deg or 0.0))
    hw, hd = float(width_m) / 2.0, float(depth_m) / 2.0
    out: List[List[float]] = []
    for sz in (-1.0, 0.0, 1.0):
        for sx in (-1.0, 0.0, 1.0):
            p = mat_apply(rot, (sx * hw, 0.0, sz * hd))
            out.append([float(anchor[0]) + p[0], float(anchor[1]) + p[2]])
    return out


def contact_check(bottom_y: float, ground: Sequence[float], *,
                  tolerance_m: float = DEFAULT_CONTACT_TOLERANCE_M
                  ) -> Dict[str, Any]:
    """How well a horizontal bottom edge at ``bottom_y`` meets the ground.

    ``contact_ratio`` is the fraction of samples within ``tolerance_m`` — the
    paper's contact ratio, measured on our own numbers instead of on voxels.
    ``floating`` says the whole object hovers (every sample below the bottom),
    which is the one defect a placement can fix by itself.
    """
    vals = [float(g) for g in ground]
    if not vals:
        return {"contact_ratio": 0.0, "samples": 0, "min_ground": 0.0,
                "max_ground": 0.0, "slope_m": 0.0, "gap_min": 0.0,
                "gap_max": 0.0, "floating": False}
    tol = float(tolerance_m)
    gaps = [float(bottom_y) - g for g in vals]      # > 0 = hovering
    hits = sum(1 for g in gaps if abs(g) <= tol)
    return {
        "contact_ratio": hits / len(vals),
        "samples": len(vals),
        "min_ground": min(vals),
        "max_ground": max(vals),
        "slope_m": max(vals) - min(vals),
        "gap_min": min(gaps),
        "gap_max": max(gaps),
        "floating": min(gaps) > tol,
    }


def sink_offset_y(bottom_y: float, ground: Sequence[float], offset_y: float, *,
                  tolerance_m: float = DEFAULT_CONTACT_TOLERANCE_M
                  ) -> Optional[float]:
    """The new ``offset_y`` that puts the bottom on the LOWEST ground sample.

    None when nothing needs doing (the object already touches somewhere) or
    when it sits BELOW its lowest sample — a buried object was authored that
    way or is a modelling defect, and lifting it here would overrule the
    author. Terrain is never touched: levelling stays a SUGGESTION in the
    result (the plan's "lokal planieren", strictly local, never global).
    """
    vals = [float(g) for g in ground]
    if not vals:
        return None
    lift = float(bottom_y) - min(vals)
    if lift <= float(tolerance_m):
        return None
    new_off = float(offset_y) - lift
    return max(-OFFSET_Y_LIMIT, min(OFFSET_Y_LIMIT, round(new_off, 3)))


# ── Ground truth in the scene frame ─────────────────────────────────────

def ground_sampler(loc: Dict[str, Any], floor_y: float = 0.0,
                   ground_offset_m: float = 0.0,
                   ) -> Callable[[float, float], float]:
    """``(lx, lz) → ground height`` in the location's SCENE frame.

    Both halves of the ground, exactly as ``relief`` splits them: the world
    height field (``world_geometry.ground_y``) plus the location's own scene
    relief (``relief.scene_ground_lift``). The world half is taken RELATIVE TO
    THE PIN, because the scene frame's y = 0 is the pin's ground — that is the
    same constant the plate's sidecar records as ``frame.world_ground_y``. On a
    plateaued location the world half is flat and the term vanishes; on a
    location without a plateau it is the difference that decides whether a prop
    hovers.

    ``floor_y`` is the THIRD term and the datum of the other two: the floor
    the placement stands on (``target.floor_y``, § B1 addendum 2026-08-20) —
    the room's plate, the yard's storey plate. The relief rides ON it, the way
    the payload composes a ``bottom_y``; without it the check compares a
    payload height against a bare terrain height and reads the floor itself as
    a gap (0.09 at a 0.05 tolerance = nothing in contact, and the run sinks a
    correctly standing prop into its own floor).

    ``ground_offset_m`` is the PROP's own sink (§ B2 addendum 2026-08-20) and
    rides on the same side of the comparison for exactly the same reason: a
    tree dialled 0.20 m into the soil is not a defect, it is where that object
    is SUPPOSED to stand. The expected base of the placement is therefore
    ``floor_y + ground_offset_m + terrain``, and only what is left over —
    the per-placement ``offset_y`` and the relief the payload could not know —
    is measured as a gap. Blind to it, the check would read the full sink as a
    prop piercing the ground and undo it as a "correction".
    """
    from app.core.relief import scene_ground_lift
    from app.core.world_geometry import ground_y, local_to_world

    cx = float(loc.get("pos_x") or 0.0)
    cz = float(loc.get("pos_z") or 0.0)
    yaw = float(loc.get("yaw_deg") or 0.0)
    try:
        base = float(ground_y(cx, cz))
    except Exception:                        # pragma: no cover - no heightfield
        base = 0.0

    def sample(lx: float, lz: float) -> float:
        wx, wz = local_to_world(lx, lz, cx, cz, yaw)
        try:
            world = float(ground_y(wx, wz)) - base
        except Exception:                    # pragma: no cover
            world = 0.0
        # floor first, terrain ON it — the same order the payload composes a
        # `bottom_y` in (plate top + clearance + the relief lift) — and the
        # prop's own sink with the floor, because it is part of the datum, not
        # part of the gap.
        return (float(floor_y) + float(ground_offset_m) + world
                + float(scene_ground_lift(loc, wx, wz)))

    return sample


# ── Backend choice ──────────────────────────────────────────────────────

def backend_takes_mask(backend: Any) -> bool:
    """Can this backend inpaint?

    Two ways, and BOTH are the imagegen contract's, not ours: a backend
    categorised ``inpaint``, or one whose api_type routes a mask at all.
    Today that is ``openai_diffusion`` alone — its ``_is_inpaint`` flips to
    ``POST /v1/images/edits`` as soon as a ``input_mask`` reference slot is
    present, whatever its category. Every other backend class silently drops
    the slot (LocalAI/Together fold reference images into ``ref_images``, A1111
    and CivitAI take none), which would look like a successful edit and quietly
    repaint the whole plate.
    """
    if getattr(backend, "category", "") == "inpaint":
        return True
    return getattr(backend, "api_type", "") == "openai_diffusion"


def select_backend(glob: str = "") -> Tuple[Any, str]:
    """The backend for the insert step and WHICH path it will run.

    An explicit glob wins and is taken at its word (an exact inpaint alias
    resolves through ``resolve_imagegen_target``). Without one the pool's own
    matching would never offer an inpaint backend — they are excluded from
    normal render matching by design — so the preference is applied here, over
    the pool's list: cheapest available inpaint-capable backend first, the
    normal image default second.

    Returns ``(backend, "inpaint" | "img2img")``; ``(None, "")`` when the pool
    has nothing available.
    """
    from app.imagegen.service import get_image_service

    svc = get_image_service()
    if (glob or "").strip():
        backend = svc.resolve_imagegen_target(glob.strip())
        if backend:
            return backend, ("inpaint" if backend_takes_mask(backend)
                             else "img2img")
        logger.warning("scene asset: backend %r not available", glob)
    usable = [b for b in getattr(svc, "backends", [])
              if getattr(b, "available", False)
              and getattr(b, "instance_enabled", False)
              and getattr(b, "MEDIA_TYPE", "image") == "image"]
    cheapest = lambda bs: sorted(bs, key=lambda b: b.effective_cost)[0]  # noqa: E731
    masking = [b for b in usable if backend_takes_mask(b)]
    if masking:
        return cheapest(masking), "inpaint"
    # No mask anywhere: the fallback is a full edit, and an img2img-tagged
    # backend is the one built for it. The pool's own img2img preference is
    # not reachable here — the service's ``_select_backend`` delegator takes
    # no ``has_input_image`` — so the same rule is applied over the same list.
    img2img = [b for b in usable if getattr(b, "category", "") == "img2img"]
    if img2img:
        return cheapest(img2img), "img2img"
    fallback = svc._select_backend()
    return (fallback, "img2img") if fallback else (None, "")


# ── The insert step ─────────────────────────────────────────────────────

def compose_insert_prompt(subject: str, backend: Any) -> Dict[str, str]:
    """Final prompt + negative for the insert — use case ``scene_asset``."""
    from app.core.prompt_compose import compose

    composed = compose(use_case=USE_CASE,
                       subject=(subject or "").strip() or "a single object",
                       backend=backend)
    return {"prompt": composed.prompt, "negative": composed.negative}


def _run_backend(backend: Any, prompt: str, negative: str,
                 gen_params: Dict[str, Any], label: str) -> List[bytes]:
    """One image generation on the backend's own GPU channel."""
    from app.core.llm_queue import Priority, get_llm_queue

    log_meta = {"agent_name": "Scene asset", "original_prompt": prompt,
                "auto_enhance": False,
                "compose": {"use_case": USE_CASE, "settings_applied": True}}
    return get_llm_queue().submit_gpu_task(
        provider_name=backend.name,
        task_type="scene_asset_edit",
        priority=Priority.IMAGE_GEN,
        callable_fn=lambda: backend.generate(prompt, negative, gen_params,
                                             log_meta=log_meta),
        agent_name="system",
        label=label,
        gpu_type=backend.api_type)


def _first_image(result: Any) -> Optional[bytes]:
    """The first real image out of a backend result, or None.

    A backend may answer with the string sentinel ``"NO_NEW_IMAGE"`` instead of
    bytes when it served a cache hit; indexing that string yields a character
    and the next stage dies far away from the cause. No backend in the tree
    returns it today, but the rule outlives any single backend, so the guard is
    here rather than in a comment.
    """
    if isinstance(result, (str, bytes, bytearray)):
        return None if isinstance(result, str) else bytes(result)
    if not isinstance(result, list) or not result:
        return None
    first = result[0]
    if isinstance(first, str):
        return None
    return bytes(first)


def insert_object(context_png: Path, mask_png: Optional[Path], backend: Any,
                  path_kind: str, prompt: str, negative: str, seed: int,
                  size: Tuple[int, int]) -> Optional[bytes]:
    """Draw the object into the plate. Returns the edited PNG bytes.

    ``inpaint`` sends plate + mask (the surroundings stay pixel-identical and
    the position is guaranteed); ``img2img`` sends the plate alone as reference
    slot 1, which is the fallback for a backend that cannot take a mask — the
    result is then only as positioned as the model felt like being, and the
    cutout stage is what notices.
    """
    refs: Dict[str, str] = {"input_image": str(context_png)}
    if path_kind == "inpaint" and mask_png is not None:
        # The mask goes LAST and its slot name carries "mask" — that is what
        # openai_diffusion._collect_ref_bytes keys the multipart field on.
        refs["input_mask"] = str(mask_png)
    gen_params: Dict[str, Any] = {
        "width": int(size[0]), "height": int(size[1]),
        "seed": int(seed),
        "reference_images": refs,
        # Deliberately NO image_use_case: the central downscale would resize
        # the result away from the plate and break the pixel correspondence
        # the difference mask lives on.
    }
    result = _run_backend(backend, prompt, negative, gen_params,
                          f"Scene asset: {backend.name}")
    return _first_image(result)


# ── The cutout step ─────────────────────────────────────────────────────

def cut_out(before_png: Path, after_png: Path, region_poly: Sequence[Sequence[float]],
            *, threshold: int = DEFAULT_DIFF_THRESHOLD,
            use_rembg: bool = DEFAULT_REMBG) -> Dict[str, Any]:
    """Difference mask between the two plates, cleaned, inside the region.

    Deviation **E4.3, decided**: the mask difference IS v1. The paper needs
    SAM3 because it does not know WHERE it put the object; we do — the spot is
    authored, the region is the mask we inpainted — so the cheapest correct
    answer is what changed inside that region. SAM3 stays the documented
    upgrade path for the day this proves too coarse (a text-guided segment of
    the same crop would slot in exactly here, as another intersection).

    ``rembg`` (u2net, the session helpers in ``models/character``) runs on the
    changed region's crop as CLEANUP only, and its alpha is INTERSECTED with
    the difference — never used alone: it segments "the foreground", which on a
    plate full of scenery is not necessarily the thing we just added.
    """
    import numpy as np
    from PIL import Image

    before = np.asarray(Image.open(before_png).convert("RGB"))
    after_img = Image.open(after_png).convert("RGB")
    if after_img.size != (before.shape[1], before.shape[0]):
        after_img = after_img.resize((before.shape[1], before.shape[0]),
                                     Image.LANCZOS)
    after = np.asarray(after_img)

    diff = difference_mask(before, after, threshold)
    region = rasterize_polygon(region_poly, before.shape[1], before.shape[0])
    mask = clean_mask(diff & region)
    out: Dict[str, Any] = {"diff_px": int(diff.sum()),
                           "region_px": int(region.sum()),
                           "rembg": False}
    if use_rembg and mask.any():
        alpha = _rembg_alpha(after_img, mask_bbox(mask))
        if alpha is not None:
            refined = mask & (alpha >= REMBG_ALPHA_MIN)
            # An intersection that eats the object means rembg segmented
            # something else — then the difference alone is the better answer.
            if refined.sum() >= 0.2 * mask.sum():
                mask = clean_mask(refined)
                out["rembg"] = True
            else:
                logger.info("scene asset: rembg alpha kept %d of %d px — "
                            "ignored", int(refined.sum()), int(mask.sum()))
    out["mask"] = mask
    out["mask_px"] = int(mask.sum())
    out["bbox"] = mask_bbox(mask)
    return out


def _rembg_alpha(image, box: Optional[Sequence[int]]):
    """u2net alpha of the changed region, placed back into a full-size array.

    Runs on the CROP, not on the plate: u2net is trained on subject-filling
    pictures, and a 2 m object in a 20 m frame is not that.
    """
    if not box:
        return None
    try:
        import io

        import numpy as np
        from PIL import Image
        from rembg import remove

        from app.models.character import _get_rembg_session

        x0, y0, x1, y1 = (int(v) for v in box)
        pad = max(8, int(0.1 * max(x1 - x0, y1 - y0)))
        w, h = image.size
        crop = (max(0, x0 - pad), max(0, y0 - pad),
                min(w, x1 + 1 + pad), min(h, y1 + 1 + pad))
        buf = io.BytesIO()
        image.crop(crop).save(buf, format="PNG")
        cut = Image.open(io.BytesIO(remove(buf.getvalue(),
                                           session=_get_rembg_session())))
        cut = cut.convert("RGBA")
        full = np.zeros((h, w), dtype=np.uint8)
        full[crop[1]:crop[3], crop[0]:crop[2]] = np.asarray(
            cut.getchannel("A"))
        return full
    except Exception as exc:
        logger.info("scene asset: rembg cleanup unavailable (%s)", exc)
        return None


def write_cutout(after_png: Path, mask, aff: Dict[str, Any],
                 out_path: Path) -> Path:
    """The masked object as an RGBA patch on a transparent background."""
    import numpy as np
    from PIL import Image

    img = Image.open(after_png).convert("RGBA")
    alpha = Image.fromarray((np.asarray(mask).astype(np.uint8) * 255), mode="L")
    img.putalpha(alpha)
    box = (int(round(aff["x0"])), int(round(aff["y0"])),
           int(round(aff["x0"] + aff["side"])),
           int(round(aff["y0"] + aff["side"])))
    patch = img.crop(box).resize((aff["size"], aff["size"]), Image.LANCZOS)
    patch.save(out_path, "PNG")
    return out_path


# ── The mesh step ───────────────────────────────────────────────────────

def mesh_from_cutout(prop_id: str, cutout: Path, target_height_m: float, *,
                     variant: Any = None, backend_glob: str = "",
                     tolerance: float = DEFAULT_HEIGHT_TOLERANCE
                     ) -> Dict[str, Any]:
    """Cutout → mesh → normalised to the DECLARED height, as a NEW variant.

    ``generate_mesh(rig="none")`` never falls back between mesh backends (a
    wrong-rig mesh binds unusably), ``normalize`` scales the delivery to
    ``target_height_m`` behind the four gates of ``refine.apply_script``, and
    the measurement afterwards is the validator this pipeline judges by: a mesh
    whose height is outside ±``tolerance`` did not survive normalisation and
    counts as a failed attempt.
    """
    from app.blender import refine
    from app.core import props as prop_store
    from app.core.model_store import write_sidecar as write_model_sidecar
    from app.core.model_validate import validate_static_glb
    from app.imagegen.service import get_image_service

    gallery = prop_store.model_gallery(prop_id, variant)
    if not gallery:
        return {"ok": False, "error": "bad prop id"}
    if not backend_glob.strip():
        from app.core.model3d import list_mesh_backends
        backend_glob = str(list_mesh_backends("none").get("default") or "").strip()
    res = get_image_service().generate_mesh(
        source_image_path=str(cutout), output_path=str(gallery.new_path()),
        backend_glob=backend_glob, mesh_name=prop_id, rig="none")
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "mesh failed")}

    path = Path(res["path"])
    norm = refine.normalize(path, float(target_height_m),
                            validator=validate_static_glb)
    measured = refine.measure_file(path) or {}
    dims = [float(v) for v in (measured.get("dims_m") or [0.0, 0.0, 0.0])]
    height = dims[2] if len(dims) > 2 else 0.0
    ok = bool(target_height_m) and abs(height - float(target_height_m)) \
        <= float(tolerance) * float(target_height_m)
    write_model_sidecar(path, {
        "created_at": utc_now_iso(),
        "source": "scene_asset",
        "format": res.get("format", path.suffix.lstrip(".").lower() or "glb"),
        "rig": res.get("rig", "none"),
        "tier": prop_store.DEFAULT_TIER,
        "backend": res.get("backend", ""),
        "normalized": bool((norm or {}).get("applied")),
        "target_height_m": float(target_height_m),
        "measured_height_m": round(height, 4),
    })
    # Only a mesh that PASSED becomes the variant's active file. A rejected one
    # stays in the gallery unselected — the history is worth keeping (an admin
    # can promote it), but a mesh that would not scale to its declared height
    # must not be what the world shows.
    if ok:
        gallery.select(path.name, prop_store.DEFAULT_TIER)
    return {"ok": ok, "path": str(path), "file": path.name,
            "backend": res.get("backend", ""),
            "normalized": bool((norm or {}).get("applied")),
            "height_m": round(height, 4),
            # Blender is Z-up: dims_m = [x, y, z] = scene [width, depth, height].
            "width_m": round(dims[0], 4) if dims else 0.0,
            "depth_m": round(dims[1], 4) if len(dims) > 1 else 0.0,
            "error": "" if ok else f"height {height:.3f} m off "
                                   f"{float(target_height_m):.3f} m"}


# ── The placement step ──────────────────────────────────────────────────

def place(sidecar: Dict[str, Any], loc: Dict[str, Any], mesh: Dict[str, Any],
          offset_y: float, par: Dict[str, Any]) -> Dict[str, Any]:
    """Yaw, contact check and — if it hovers — the sink, all numeric.

    The POSITION never moves: it is the authored anchor, which is the whole
    reason this pipeline needs no back-projection (the paper recovers the
    position from the picture; we put the picture where the position is).
    """
    target = sidecar.get("target") or {}
    camera = sidecar.get("camera") or {}
    anchor = [float(target["anchor"][0]), float(target["anchor"][1])]
    ground_y = float(target.get("ground_y") or 0.0)
    yaw = placement_yaw_deg(float(camera.get("azimuth_deg") or 0.0))
    # The footprint is the MESH's own measured box (Blender is Z-up, so
    # dims_m = [width, depth, height] in scene terms), falling back to the
    # prop's declared dims when nothing could be measured. It is the RAW box:
    # a freshly generated mesh carries no orientation fix yet, and once an
    # admin sets one, the fix dial is also where the correction belongs.
    width = float(mesh.get("width_m") or 0.0) or float(
        (target.get("dims_m") or [1.0, 1.0, 1.0])[0])
    depth = float(mesh.get("depth_m") or 0.0) or float(
        (target.get("dims_m") or [1.0, 1.0, 1.0])[1])

    # ONE datum for both sides of the comparison (§ B1 addendum 2026-08-20):
    # `ground_y` is the payload's own `bottom_y`, so the sampler is lifted
    # onto the same floor the payload composed it from — and by the prop's own
    # ground offset (§ B2 addendum 2026-08-20), which the payload put into
    # `bottom_y` as well and which is a deliberate base, not a defect.
    sample = ground_sampler(loc, float(target.get("floor_y") or 0.0),
                            float(target.get("ground_offset_m") or 0.0))
    points = footprint_samples(anchor, width, depth, yaw)
    ground = [sample(p[0], p[1]) for p in points]
    bottom = ground_y + float(offset_y)
    before = contact_check(bottom, ground,
                           tolerance_m=par["contact_tolerance_m"])
    sunk = sink_offset_y(bottom, ground, float(offset_y),
                         tolerance_m=par["contact_tolerance_m"])
    after = before
    if sunk is not None:
        after = contact_check(ground_y + sunk, ground,
                              tolerance_m=par["contact_tolerance_m"])
    out: Dict[str, Any] = {
        "yaw_deg": round(yaw, 1),
        "offset_y": round(sunk if sunk is not None else float(offset_y), 3),
        "sank_m": round(float(offset_y) - sunk, 3) if sunk is not None else 0.0,
        "footprint_m": [round(width, 4), round(depth, 4)],
        "samples": [[round(p[0], 4), round(p[1], 4)] for p in points],
        "ground": [round(g, 4) for g in ground],
        "before": before, "after": after,
        "contact_ratio": after["contact_ratio"],
        "ok": after["contact_ratio"] >= float(par["contact_ratio"]),
    }
    if after["slope_m"] > float(par["level_slope_m"]):
        # The plan's "lokal planieren" — reported, never done: terrain edits
        # belong to the author, and a pipeline that levels the ground behind
        # their back changes the world to fit one object.
        out["suggest_level"] = {
            "reason": "slope under the footprint",
            "slope_m": round(after["slope_m"], 4),
            "threshold_m": float(par["level_slope_m"]),
            "at": [round(anchor[0], 3), round(anchor[1], 3)],
        }
    return out


# ── The run ─────────────────────────────────────────────────────────────

def run_dir(prop_id: str, stamp: str = "") -> Path:
    """``<prop dir>/scene_asset/<ts>/`` — one directory per run."""
    from app.core import props as prop_store

    base = prop_store.prop_dir(prop_id, create=True)
    if base is None:
        raise ValueError(f"unknown prop: {prop_id}")
    stamp = stamp or utc_now().strftime("%Y%m%d-%H%M%S")
    out = base / RUN_DIR_NAME / stamp
    out.mkdir(parents=True, exist_ok=True)
    return out


def generate(location_id: str, room_id: str, index: int, *,
             subject: str = "", image_backend_glob: str = "",
             mesh_backend_glob: str = "",
             overrides: Optional[Dict[str, Any]] = None,
             game: Any = None) -> Dict[str, Any]:
    """The whole chain for ONE placement, blocking. Returns the result record.

    The context plate is rendered ONCE — it does not depend on the image seed —
    and every retry re-runs insert → cutout → mesh on a fresh seed. The bounded
    loop is the paper's render-inspect-refine with its vision inspection
    replaced by geometry (our rule: findings are numeric).
    """
    from app.core import props as prop_store
    from app.core.scene_context import render_context

    par = params(overrides)
    target = {"kind": "prop", "room_id": room_id, "index": int(index)}
    started = utc_now()

    plate = render_context(location_id, target, _tmp_plate_dir(), game=game)
    sidecar = json.loads(Path(plate["sidecar"]).read_text(encoding="utf-8"))
    tgt = sidecar.get("target") or {}
    prop_id = str(tgt.get("prop_id") or "")
    if not prop_id:
        raise ValueError("placement carries no prop id")
    meta = prop_store.read_sidecar(prop_id) or {}
    subject = (subject or meta.get("description")
               or meta.get("name") or prop_id).strip()

    out = run_dir(prop_id)
    context_png = out / "context.png"
    context_png.write_bytes(Path(plate["png"]).read_bytes())

    # The inpaint region: the sidecar's mask polygon, grown by the margin.
    poly = [[float(p[0]), float(p[1])] for p in (sidecar.get("mask") or {})
            .get("polygon_px") or []]
    if len(poly) < 3:
        # No region means nothing to inpaint and nothing to diff against — the
        # spot projected behind the camera or degenerated. Fail loudly here
        # rather than send an all-black mask to a gateway.
        raise ValueError("context plate carries no mask polygon")
    grow_px = grow_px_for(poly, par["mask_margin"])
    region = grow_polygon(poly, grow_px)
    width, height = (sidecar.get("camera") or {}).get("resolution") or [1024, 1024]
    mask_png = out / "mask.png"
    _write_mask_png(region, int(width), int(height), mask_png)

    backend, path_kind = select_backend(image_backend_glob)
    if backend is None:
        raise RuntimeError("no image backend available")
    composed = compose_insert_prompt(subject, backend)

    expected = expected_px_bbox(tgt.get("footprint") or [],
                                float(tgt.get("ground_y") or 0.0),
                                float(tgt.get("height_m") or 0.0),
                                sidecar.get("camera") or {})
    record: Dict[str, Any] = {
        "version": 1,
        "location_id": location_id, "room_id": room_id, "index": int(index),
        "prop_id": prop_id, "subject": subject,
        "started_at": utc_now_iso(),
        "backend": backend.name, "path": path_kind,
        "prompt": composed["prompt"], "negative": composed["negative"],
        "mask": {"grow_px": round(grow_px, 2), "margin": par["mask_margin"],
                 "polygon_px": [[round(p[0], 2), round(p[1], 2)]
                                for p in region]},
        "expected_px_bbox": [round(v, 2) for v in expected],
        "files": {"context": str(context_png), "mask": str(mask_png)},
        "params": par,
        "attempts": [],
    }

    # The variant is decided ONCE for the whole run: a retry refines the same
    # slot (its gallery keeps every attempt as a file), it does not eat another
    # of the prop's active variants.
    variant = prop_store.target_variant(prop_id)
    record["variant"] = variant

    # WHAT THIS SPOT SHOWED UNTIL NOW. Resolved and COPIED at trigger time,
    # before a single pixel is written: the "before" of the comparison is the
    # source image of the variant the placement pointed at, and when the run
    # refines that very variant, the picture is overwritten a few lines below.
    # A live URL would therefore show the AFTER in both frames. The run
    # directory is immutable once written, so the copy stays true forever.
    from app.models.world import get_location_by_id
    loc_rec = get_location_by_id(location_id) or {}
    placement_before = authored_placement(loc_rec, room_id, int(index))
    prev = previous_variant(prop_id, placement_before)
    record["previous_variant"] = prev
    prev_src = prop_store.source_path(prop_id, prev) if prev is not None else None
    if prev_src is not None:
        before_png = out / "before.png"
        before_png.write_bytes(prev_src.read_bytes())
        record["files"]["before"] = str(before_png)

    # The stamp the cutout's provenance carries is the RUN's own start — the
    # same string this record already published — never a fresh clock read, so
    # the badge in the admin and the run directory name one moment, not two.
    origin = {"origin": prop_store.ORIGIN_SCENE_CONTEXT,
              "origin_location": str(loc_rec.get("name") or location_id),
              "origin_location_id": str(location_id),
              "origin_ts": record["started_at"]}
    # A pinned seed fixes the FIRST attempt only — a reproduction reproduces
    # one attempt, and a retry that repeated the same seed would repeat the
    # same picture and therefore the same failure.
    pinned = par.get("seed")
    loop = run_attempts(
        lambda attempt, seed: _attempt(
            out, attempt, seed, context_png, mask_png, region, backend,
            path_kind, composed, sidecar, expected, prop_id, variant, par,
            mesh_backend_glob, origin),
        retries=int(par["retries"]),
        seeds=[int(pinned)] if pinned else None)
    record["attempts"] = loop["attempts"]
    ok = loop["ok"]
    if ok:
        last = loop["attempts"][-1]
        record.update({k: last[k] for k in ("placement", "mesh", "variant")
                       if k in last})
        record["files"].update(last.get("files") or {})

    record["ok"] = ok
    record["failures"] = loop["failures"]
    record["seconds"] = round((utc_now() - started).total_seconds(), 2)
    record["finished_at"] = utc_now_iso()
    (out / "result.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Scene asset %s (%s/%s#%d): %s in %.1fs", prop_id,
                location_id, room_id, index, "ok" if ok else "failed",
                record["seconds"])
    return record


def run_attempts(attempt_fn: Callable[[int, int], Dict[str, Any]], *,
                 retries: int = DEFAULT_RETRIES,
                 seeds: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """The bounded refinement loop: run ``attempt_fn(index, seed)`` until one
    reports ``ok``, at most ``retries`` times more than once.

    The paper's render–inspect–refine with its vision inspection replaced by
    the geometric checks the attempt itself runs. A raising attempt is a FAILED
    attempt, not a failed run — a gateway hiccup on the second seed must not
    throw away the first one's record. ``seeds`` is for the smoke; production
    draws them.
    """
    attempts: List[Dict[str, Any]] = []
    for i in range(max(0, int(retries)) + 1):
        seed = int(seeds[i]) if seeds and i < len(seeds) \
            else random.randint(1, 2**31 - 1)
        try:
            res = dict(attempt_fn(i, seed))
        except Exception as exc:               # one attempt, not the run
            logger.error("scene asset attempt %d failed: %s", i, exc)
            res = {"ok": False, "failures": [f"exception: {exc}"]}
        res["attempt"] = i
        res["seed"] = seed
        attempts.append(res)
        if res.get("ok"):
            return {"ok": True, "attempts": attempts, "failures": []}
    failures = (attempts[-1].get("failures") or ["failed"]) if attempts \
        else ["no attempt ran"]
    return {"ok": False, "attempts": attempts, "failures": list(failures)}


def _attempt(out: Path, attempt: int, seed: int, context_png: Path,
             mask_png: Path, region: Sequence[Sequence[float]], backend: Any,
             path_kind: str, composed: Dict[str, str],
             sidecar: Dict[str, Any], expected: Sequence[float],
             prop_id: str, variant: int, par: Dict[str, Any],
             mesh_backend_glob: str,
             origin: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One insert → cutout → mesh → place pass. Every check is recorded."""
    suffix = "" if attempt == 0 else f"-{attempt + 1}"
    res: Dict[str, Any] = {"attempt": attempt, "failures": [], "files": {}}
    camera = sidecar.get("camera") or {}
    size = tuple(int(v) for v in (camera.get("resolution") or [1024, 1024]))

    blob = insert_object(context_png, mask_png, backend, path_kind,
                         composed["prompt"], composed["negative"], seed, size)
    if not blob:
        res["failures"].append("insert produced no image")
        return res
    edit_png = out / f"edit{suffix}.png"
    edit_png.write_bytes(blob)
    res["files"]["edit"] = str(edit_png)

    cut = cut_out(context_png, edit_png, region,
                  threshold=par["diff_threshold"], use_rembg=par["rembg"])
    res["cutout"] = {k: cut[k] for k in ("diff_px", "region_px", "mask_px",
                                         "bbox", "rembg")}
    if not cut["bbox"]:
        res["failures"].append("nothing changed inside the mask region")
        return res

    ratio = px_size_ratio(cut["bbox"], expected)
    res["px_ratio"] = round(ratio, 3)
    if not (par["px_ratio_min"] <= ratio <= par["px_ratio_max"]):
        res["failures"].append(
            f"drawn object {ratio:.2f}× the expected pixel height "
            f"(band {par['px_ratio_min']}–{par['px_ratio_max']})")
        return res

    aff = crop_affine(cut["bbox"], size[0], size[1],
                      out_px=par["crop_px"], margin=par["crop_margin"])
    cutout_png = out / f"cutout{suffix}.png"
    write_cutout(edit_png, cut["mask"], aff, cutout_png)
    res["files"]["cutout"] = str(cutout_png)
    # The cutout IS this variant's source image (props.py, "THE SOURCE IMAGE
    # FOLLOWS THE MESH"): the mesh below is made from this very picture, so a
    # later re-mesh of the same variant has to find it and no other. Written
    # before the mesh, because it is what the attempt was made from whether or
    # not the mesh survives the height gate — and a retry overwrites it with
    # its own cutout, which is again the picture the stored mesh came from.
    #
    # The ORIGIN goes with it. A cutout carries the light, the ground and the
    # surroundings of ONE spot, so a variant made this way is not a product
    # shot and must not read as one — the store writes the marker only when it
    # is handed one, and an image without it IS a product shot (props.py).
    from app.core import props as prop_store
    prop_store.save_source_image(
        prop_id, cutout_png.read_bytes(), variant,
        backend=str(getattr(backend, "name", "") or ""),
        prompt=composed["prompt"], negative=composed["negative"],
        **(origin or {}))
    res["crop"] = {"x0": round(aff["x0"], 2), "y0": round(aff["y0"], 2),
                   "side": round(aff["side"], 2), "scale": round(aff["scale"], 5),
                   "size": aff["size"],
                   "intrinsics": {k: round(v, 3) for k, v in
                                  equivalent_intrinsics(camera, aff).items()}}

    res["variant"] = variant
    mesh = mesh_from_cutout(prop_id, cutout_png,
                            float((sidecar.get("target") or {}).get("height_m") or 0.0),
                            variant=variant, backend_glob=mesh_backend_glob,
                            tolerance=par["height_tolerance"])
    res["mesh"] = mesh
    if not mesh.get("ok"):
        res["failures"].append(f"mesh: {mesh.get('error')}")
        return res

    from app.models.world import get_location_by_id
    loc = get_location_by_id(sidecar.get("location_id") or "") or {}
    placement = place(sidecar, loc, mesh, _authored_offset_y(sidecar, loc), par)
    res["placement"] = placement
    if not placement.get("ok"):
        # A terrain-caused contact failure repeats on every seed — it is
        # reported as a failure, and the levelling suggestion beside it is what
        # a human can act on.
        res["failures"].append(
            f"contact ratio {placement['contact_ratio']:.2f} < "
            f"{par['contact_ratio']}")
        return res

    # The placement now points at the mesh that was made FOR it: the variant it
    # landed in, the yaw the plate camera implies and the offset the contact
    # check settled on. Written through the sanitizer, like every other edit.
    #
    # ``variant`` here is the STORE index (props.target_variant), but a
    # placement's field is resolved by the renderers as the POSITION within
    # the active, meshed variants (scene_recipe._variant_index over
    # model_variants). The two diverge the moment any variant is switched
    # off or mesh-less — writing the store index would then point the
    # placement at a DIFFERENT mesh than the one just generated. Convert at
    # the boundary between the two vocabularies, exactly where the asset
    # URLs already do it the other way around (§ B2 addendum).
    from app.core.props import active_variant_tiers
    positions = [e.get("variant") for e in active_variant_tiers(prop_id)]
    try:
        render_pos = positions.index(variant)
    except ValueError:
        res["failures"].append(
            f"generated variant {variant} is not active+meshed "
            f"(active: {positions})")
        return res
    from app.core.world_ops import update_prop_placement
    stored = update_prop_placement(
        str(sidecar.get("location_id") or ""),
        str((sidecar.get("target") or {}).get("room_id") or ""),
        int((sidecar.get("target") or {}).get("index") or 0),
        {"variant": render_pos, "yaw": placement["yaw_deg"],
         "offset_y": placement["offset_y"]})
    res["stored_placement"] = stored
    if stored is None:
        res["failures"].append("placement vanished while generating")
        return res
    res["ok"] = True
    return res


def authored_placement(loc: Dict[str, Any], room_id: str,
                       index: int) -> Dict[str, Any]:
    """The STORED placement dict of ``<room>#<index>``, or ``{}``.

    Stored and not drafted, like everything this pipeline reads: the editor's
    unsaved draft does not exist for it (``routes/scene_asset._placement``
    enforces the same rule at the HTTP boundary)."""
    for room in (loc.get("rooms") or []):
        if str(room.get("id") or "") != str(room_id):
            continue
        props = ((room.get("layout") or {}).get("props") or [])
        if 0 <= int(index) < len(props):
            entry = props[int(index)]
            return dict(entry) if isinstance(entry, dict) else {}
        return {}
    return {}


def previous_variant(prop_id: str,
                     placement: Dict[str, Any]) -> Optional[int]:
    """Which STORE variant this placement showed before the run — or None when
    the prop has no active, meshed variant at all (a first generation).

    The two vocabularies of § B2 again, in the other direction than
    :func:`_attempt` needs them: a placement's ``variant`` is a POSITION in the
    prop's active meshed variants, and the store index is what addresses a
    file. The position is taken MODULO the count, because that is exactly what
    both renderers do with it — the "before" picture has to be the one that was
    on screen, not the one a stricter reading would have shown.
    """
    from app.core.props import active_variant_tiers

    positions = [e.get("variant") for e in active_variant_tiers(prop_id)]
    if not positions:
        return None
    try:
        pos = int(placement.get("variant") or 0)
    except (TypeError, ValueError):
        pos = 0
    return positions[pos % len(positions)]


def _authored_offset_y(sidecar: Dict[str, Any], loc: Dict[str, Any]) -> float:
    """The placement's stored ``offset_y``, or 0.0."""
    tgt = sidecar.get("target") or {}
    entry = authored_placement(loc, str(tgt.get("room_id") or ""),
                               int(tgt.get("index")
                                   if tgt.get("index") is not None else -1))
    try:
        return float(entry.get("offset_y") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tmp_plate_dir() -> Path:
    """Where the Blender runner drops the plate before it is copied into the
    run directory (the runner writes declared outputs, the run directory is
    ours to name)."""
    import tempfile

    return Path(tempfile.mkdtemp(prefix="av-scene-asset-"))


def _write_mask_png(poly: Sequence[Sequence[float]], width: int, height: int,
                    path: Path) -> Path:
    """The inpaint mask as an L-PNG, WHITE = the region to fill.

    That polarity is the imagegen contract's (``openai_diffusion.mask_format``
    'grayscale' sends the L mask through unchanged, 'openai' inverts it to RGBA
    alpha itself) — the pipeline produces one shape and the backend setting
    decides how it reaches the gateway.
    """
    import numpy as np
    from PIL import Image

    mask = rasterize_polygon(poly, width, height)
    Image.fromarray((np.asarray(mask).astype(np.uint8) * 255),
                    mode="L").save(path, "PNG")
    return path


def trigger_scene_asset(location_id: str, room_id: str, placement_index: int, *,
                        subject: str = "", image_backend_glob: str = "",
                        mesh_backend_glob: str = "",
                        overrides: Optional[Dict[str, Any]] = None) -> bool:
    """Start the chain in the background — the props job idiom, verbatim.

    Daemon thread, ONE tracked header task around the whole chain (the GPU jobs
    show up in the queue panel through their own channel entries), and a
    double-start guard per placement. False when this very placement is already
    running.
    """
    key = f"{location_id}|{room_id}|{int(placement_index)}"
    with _lock:
        if key in _running:
            return False
        _running.add(key)

    def _run() -> None:
        from app.core.task_queue import get_task_queue
        task_id = ""
        error = ""
        try:
            task_id = get_task_queue().track_start(
                "model3d_generation",
                f"Scene asset: {room_id or 'ground'}#{placement_index}",
                start_running=True)
        except Exception:
            task_id = ""
        try:
            res = generate(location_id, room_id, int(placement_index),
                           subject=subject,
                           image_backend_glob=image_backend_glob,
                           mesh_backend_glob=mesh_backend_glob,
                           overrides=overrides)
            if not res.get("ok"):
                error = "; ".join(res.get("failures") or ["failed"])
        except Exception as exc:
            error = str(exc)
            logger.error("Scene asset for %s failed: %s", key, exc)
        finally:
            if task_id:
                try:
                    get_task_queue().track_finish(task_id, error=error)
                except Exception:
                    pass
            with _lock:
                _running.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return True


def is_running(location_id: str = "") -> List[str]:
    """Keys of the running scene-asset jobs (``location|room|index``)."""
    with _lock:
        keys = sorted(_running)
    if not location_id:
        return keys
    return [k for k in keys if k.split("|", 1)[0] == location_id]
