"""Model-owned water sidecars, placement composition and shared region lookup.

Detection stores XZ polygons in the model's glTF axes AFTER the sidecar
orientation fix. Heights (level and bed) are model units above box_min.y;
box_min/box_max describe that fixed frame, while extent_snapped determines
placement scale just as it does for baked walkable surfaces.
compose_regions alone converts these numbers to tile-local metres. It leaves
terrain/storey lift to the consumer so water follows its mesh exactly once.

Validity belongs to the FILE, not to a placement: version, source identity
(size and mtime), rotation and usable geometry must agree. Missing, malformed
or stale files read as no water, so an obsolete bake cannot carry a walker
or prevent scene composition. The editor can offer detection again.

Re-detection carries admin choices by containment of each new outline's
centroid, rather than unstable detection IDs. Manual regions survive intact.
The old file is read and merged under the publication lock AFTER Blender
finishes, so a PATCH made during detection wins over the detector's defaults.
Atomic replacement publishes one complete file; cache invalidation then makes
both scene payloads and the server's walk gate see the published water.
"""

import copy
import json
import logging
import math
import os
import re
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from app.core.model_surface import _norm_rotation, _source_of, block_sig, surface_scale
from app.core.timeutils import utc_now_iso
from app.core.keyed_lock import keyed_lock

logger = logging.getLogger(__name__)
#: Sidecar schema version; a different version must be detected again.
WATER_VERSION = 1
#: Default sRGB tints and clarity values from spec § 5.1; custom uses pool fallbacks.
LOOK_PRESETS = {
    "pool": {"tint": "#3aa7c4", "clarity": 0.75},
    "bath": {"tint": "#bfe3ea", "clarity": 0.85},
    "pond": {"tint": "#4f6a3c", "clarity": 0.3},
    "hot_spring": {"tint": "#9fd0d8", "clarity": 0.45},
    "lake": {"tint": "#2d6a86", "clarity": 0.5},
}
_load_cache = OrderedDict()


def water_path(model_path):
    """Return the model-owned sidecar path: room.glb -> room.glb.water.json.

    Keeping the model filename makes each drawn variant own its water; the
    gallery deletes this sidecar with the model, like its baked surface."""
    path = Path(model_path)
    return path.with_name(path.name + ".water.json")


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def sanitize_look(look):
    """Return a valid preset/tint/clarity look using the defaults in spec § 5.1.

    Unknown presets use custom only when a tint was supplied. Invalid tints
    use the preset colour, and finite clarity is clamped to [0, 1]."""
    look = look if isinstance(look, dict) else {}
    preset = look.get("preset", "pool")
    if not isinstance(preset, str):
        preset = "custom" if look.get("tint") else "pool"
    if preset not in LOOK_PRESETS and preset != "custom":
        preset = "custom" if look.get("tint") else "pool"
    defaults = LOOK_PRESETS.get(preset, LOOK_PRESETS["pool"])
    tint = str(look.get("tint") or "").lower()
    if not re.fullmatch("#[0-9a-f]{6}", tint):
        tint = defaults["tint"]
    return {
        "preset": preset,
        "tint": tint,
        "clarity": max(
            0.0, min(1.0, _number(look.get("clarity"), defaults["clarity"]))
        ),
    }


def point_in_ring(x, z, ring):
    """Even/odd polygon containment; the outline boundary counts as inside."""
    inside = False
    for index, (start_x, start_z) in enumerate(ring):
        end_x, end_z = ring[index - 1]
        cross = (x - start_x) * (end_z - start_z) - (z - start_z) * (end_x - start_x)
        if (
            abs(cross) < 1e-09
            and min(start_x, end_x) - 1e-09 <= x <= max(start_x, end_x) + 1e-09
            and (min(start_z, end_z) - 1e-09 <= z <= max(start_z, end_z) + 1e-09)
        ):
            return True
        if (start_z > z) != (end_z > z) and x < (end_x - start_x) * (z - start_z) / (
            end_z - start_z
        ) + start_x:
            inside = not inside
    return inside


def _contains(region, x, z):
    return point_in_ring(x, z, region["outline"]) and (
        not any((point_in_ring(x, z, hole) for hole in region.get("holes", [])))
    )


def _centroid(ring):
    # Signed polygon centroid; a degenerate ring falls back to vertex mean.
    cross_products = [
        ring[index - 1][0] * point[1] - point[0] * ring[index - 1][1]
        for index, point in enumerate(ring)
    ]
    six_times_area = 3 * sum(cross_products)
    if abs(six_times_area) < 1e-12:
        return [sum((point[axis] for point in ring)) / len(ring) for axis in (0, 1)]
    return [
        sum(
            (
                (ring[index - 1][axis] + point[axis]) * cross_products[index]
                for index, point in enumerate(ring)
            )
        )
        / six_times_area
        for axis in (0, 1)
    ]


def manual_region(shape, center, size, level):
    """Build a sure, enabled rectangle or 32-point ellipse in the model frame.

    Reject non-finite dimensions and non-positive sizes. The caller assigns
    the manual ID, clamps the level to the box and scales metric metadata."""
    if shape not in ("rect", "ellipse"):
        raise ValueError("shape must be rect or ellipse")
    try:
        center_x, center_z = map(float, center)
        width, depth = map(float, size)
        level = float(level)
    except (TypeError, ValueError):
        raise ValueError("Invalid manual region dimensions") from None
    if (
        not all(
            (
                math.isfinite(value)
                for value in (center_x, center_z, width, depth, level)
            )
        )
        or min(width, depth) <= 0
    ):
        raise ValueError("Invalid manual region dimensions")
    ring = (
        [
            [center_x - width / 2, center_z - depth / 2],
            [center_x + width / 2, center_z - depth / 2],
            [center_x + width / 2, center_z + depth / 2],
            [center_x - width / 2, center_z + depth / 2],
        ]
        if shape == "rect"
        else [
            [
                center_x + width / 2 * math.cos(index * math.tau / 32),
                center_z + depth / 2 * math.sin(index * math.tau / 32),
            ]
            for index in range(32)
        ]
    )
    return dict(
        kind="manual",
        confidence="sure",
        enabled=True,
        outline=ring,
        holes=[],
        level=level,
        bed=0.0,
        level_user=True,
        area_m2=width * depth * (1 if shape == "rect" else math.pi / 4),
        depth_m=max(0.0, level),
        look=sanitize_look({}),
    )


def _load(model_path):
    path = water_path(model_path)
    try:
        identity = path.stat()
        key = (str(path), identity.st_size, identity.st_mtime_ns, identity.st_ino)
        if key in _load_cache:
            return _load_cache[key]
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        _load_cache[key] = data
        while len(_load_cache) > 256:
            _load_cache.popitem(last=False)
        return data
    except (OSError, ValueError):
        return None


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and (not isinstance(value, bool))
        and math.isfinite(value)
    )


def _detection_scale(data):
    target_m = _number(data.get("target_m"))
    return (
        surface_scale(data, {"max_m": target_m, "measure": data.get("measure", "xz")})
        if target_m > 0
        else 1.0
    )


def _valid(data, model_path, rotation):
    try:
        if (
            data["version"] != WATER_VERSION
            or not _source_of(model_path)
            or data["source"] != _source_of(model_path)
            or (_norm_rotation(data["rotation"]) != _norm_rotation(rotation))
        ):
            return False
        for key in ("box_min", "box_max", "extent_snapped"):
            if len(data[key]) != 3 or not all(
                (_finite_number(value) for value in data[key])
            ):
                return False
        if not isinstance(data["regions"], list):
            return False
        ids = set()
        for region in data["regions"]:
            if region["id"] in ids:
                return False
            ids.add(region["id"])
            for ring in [region["outline"], *region.get("holes", [])]:
                if len(ring) < 3 or any(
                    (
                        len(point) != 2
                        or not all((_finite_number(value) for value in point))
                        for point in ring
                    )
                ):
                    return False
            if not all((_finite_number(region[field]) for field in ("level", "bed"))):
                return False
            if not isinstance(region["enabled"], bool) or not isinstance(
                region["look"], dict
            ):
                return False
            look = region["look"]
            if (
                not isinstance(look.get("preset", "pool"), str)
                or not isinstance(look.get("tint", ""), str)
                or (not _finite_number(look.get("clarity", 0.75)))
            ):
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def read_water(model_path, rotation):
    """Return valid model-owned water, or None for missing/stale/corrupt files.

    Invalid sidecars deliberately behave as no water rather than raising:
    scene composition and walking must continue without an obsolete surface.
    Validity is checked against the current source and fix on every read,
    even when the parsed JSON came from the file-identity cache."""
    if not model_path:
        return None
    data = _load(model_path)
    return data if data and _valid(data, model_path, rotation) else None


def water_status(model_path, rotation):
    """Distinguish an absent sidecar (none) from a valid or stale one.

    The editor uses stale to offer detection again; consumers use read_water
    and receive no water for either absent or invalid files."""
    if not model_path or not water_path(model_path).exists():
        return {"status": "none"}
    return {"status": "valid" if read_water(model_path, rotation) else "stale"}


def forget_water(location_id=""):
    """Invalidate parsed water and all derived scene/walk-gate caches.

    Surface caches also hold water-bearing placement specs for carry height.
    The prop-library token feeds scene fingerprints and cached payloads, so
    clearing only the parsed sidecar would leave published edits invisible."""
    from app.core.model_surface import forget_surfaces
    from app.core.scene_recipe import invalidate_prop_lib_token

    _load_cache.clear()
    forget_surfaces(location_id)
    invalidate_prop_lib_token()


def _write(model_path, data):
    destination = water_path(model_path)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=destination.parent,
            prefix=destination.name,
            suffix=".tmp",
            encoding="utf-8",
            delete=False,
        ) as stream:
            name = stream.name
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        os.replace(name, destination)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    forget_water()


def detect_water(model_path, rotation, *, target_m, measure, wait_s=0.0, preview=None):
    """Detect under a LOD slot, then atomically publish with admin edits intact.

    Return (water, reason), sharing the surface wrapper's unavailable/busy/
    failure handling. Detection runs outside the per-model lock. Publication
    reads and merges the latest valid file under that lock so concurrent
    PATCHes are retained. Match each new outline centroid to an old region
    because raster topology and numbered IDs may change on re-detection.
    Carry enabled/look and explicitly edited levels; copy manual regions."""
    from app.blender import refine, runner

    source = _source_of(model_path)
    if not source:
        return (None, "unreadable")
    if not runner.is_available():
        return (None, "no_blender")
    if not refine.take_lod_slot(wait_s):
        return (None, "busy")
    try:
        result = runner.run(
            "waterdetect",
            inputs={"model": Path(model_path)},
            params={
                "rotation": _norm_rotation(rotation),
                "target_m": target_m,
                "measure": measure,
                "step": 0.02,
                "max_cells": 250000,
                "preview": bool(preview),
            },
            out_dir=Path(preview).parent if preview else None,
        )
    except Exception:
        logger.exception("Water detection failed: %s", model_path)
        return (None, "failed")
    finally:
        refine.free_lod_slot()
    if not result.get("ok"):
        logger.info("Water detection failed: %s: %s", model_path, result.get("error"))
        return (None, "failed")
    data = dict(result.get("data") or {})
    data.update(
        version=1,
        source=source,
        rotation=_norm_rotation(rotation),
        detected_at=utc_now_iso(),
        target_m=target_m,
        measure=measure,
    )
    # Read the latest edits only at publication, after the slow Blender pass.
    with keyed_lock("model_water", str(Path(model_path).resolve())):
        if not _valid(data, model_path, rotation):
            return (None, "failed")
        old = read_water(model_path, rotation) or {"regions": []}
        for index, region in enumerate(data["regions"], 1):
            region["id"] = f"r{index}"
            centroid_x, centroid_z = _centroid(region["outline"])
            match = next(
                (
                    old_region
                    for old_region in old["regions"]
                    if _contains(old_region, centroid_x, centroid_z)
                ),
                None,
            )
            if match:
                region["enabled"] = match["enabled"]
                region["look"] = copy.deepcopy(match["look"])
                if match.get("level_user"):
                    region["level"] = match["level"]
                    region["level_user"] = True
                    region["depth_m"] = max(
                        0.0, region["level"] - region["bed"]
                    ) * _detection_scale(data)
        data["regions"].extend(
            (
                copy.deepcopy(old_region)
                for old_region in old["regions"]
                if old_region.get("kind") == "manual"
            )
        )
        try:
            _write(model_path, data)
            if preview and result.get("outputs", {}).get("preview"):
                preview_source = Path(result["outputs"]["preview"])
                if preview_source.resolve() != Path(preview).resolve():
                    os.replace(preview_source, preview)
        except OSError:
            logger.exception("Water not stored: %s", model_path)
            return (None, "unstorable")
    return (data, "ok")


def patch_water(model_path, rotation, patch):
    """Apply admin edits to valid water under the same lock as publication.

    Work on a copy so validation failures cannot mutate the parse cache.
    Sanitize looks, clamp levels, and allow removal only of manual regions.
    A successful atomic write invalidates derived scene and walking caches."""
    if not isinstance(patch, dict):
        raise ValueError("Body must be an object")
    with keyed_lock("model_water", str(Path(model_path).resolve())):
        data = copy.deepcopy(read_water(model_path, rotation))
        if data is None:
            raise ValueError("No valid water file; detect water first")
        try:
            by_id = {region["id"]: region for region in data["regions"]}
            for change in patch.get("regions", []):
                region = by_id[change["id"]]
                if "enabled" in change:
                    if not isinstance(change["enabled"], bool):
                        raise ValueError("enabled must be a boolean")
                    region["enabled"] = change["enabled"]
                if "look" in change:
                    region["look"] = sanitize_look(change["look"])
                if "level" in change:
                    region["level"] = max(
                        region["bed"],
                        min(
                            data["box_max"][1] - data["box_min"][1],
                            _number(change["level"], region["level"]),
                        ),
                    )
                    region["level_user"] = True
                    region["depth_m"] = (
                        region["level"] - region["bed"]
                    ) * _detection_scale(data)
            remove = patch.get("remove", [])
            for region_id in remove:
                if by_id[region_id].get("kind") != "manual":
                    raise ValueError("Only manual regions can be removed")
            data["regions"] = [
                region for region in data["regions"] if region["id"] not in remove
            ]
            if patch.get("add"):
                addition = patch["add"]
                region = manual_region(
                    addition["shape"],
                    addition["center"],
                    addition["size"],
                    addition["level"],
                )
                manual_index = 1
                while f"m{manual_index}" in by_id:
                    manual_index += 1
                region["id"] = f"m{manual_index}"
                region["level"] = max(
                    0.0, min(data["box_max"][1] - data["box_min"][1], region["level"])
                )
                scale = _detection_scale(data)
                region["area_m2"] *= scale * scale
                region["depth_m"] = region["level"] * scale
                data["regions"].append(region)
        except (KeyError, TypeError, IndexError):
            raise ValueError("Invalid patch or unknown region id") from None
        _write(model_path, data)
        return data


def compose_regions(water, spec):
    """Compose enabled model regions into tile-local metres (spec § 7).

    This is the exact inverse of surface_height_at's XZ lookup. With scale s,
    box centre (cx, cz), anchor (ax, az), c = cos(yaw), sn = sin(yaw):
        tile_x = ax + s * ((model_x - cx) * c + (model_z - cz) * sn)
        tile_z = az + s * (-(model_x - cx) * sn + (model_z - cz) * c)
    The surface reader subtracts the anchor, applies the opposite yaw and
    divides by s before adding the box centre. Both use surface_scale against
    extent_snapped, so the water outline follows the placed mesh exactly.
    Heights are bottom_y + s * level (or bed), already relative to box_min.y.
    Omit terrain/storey lift: consumers apply the mesh's lift once. Opacity
    is 1 - 0.6 * clarity. No enabled regions means no water payload."""
    if not water:
        return None
    scale = surface_scale(water, spec)
    box_min, box_max = (water["box_min"], water["box_max"])
    center_x, center_z = ((box_min[0] + box_max[0]) / 2, (box_min[2] + box_max[2]) / 2)
    anchor_x, anchor_z = spec["anchor"]
    yaw_radians = math.radians(float(spec.get("yaw_deg") or 0))
    cos_yaw, sin_yaw = (math.cos(yaw_radians), math.sin(yaw_radians))

    def ring(points):
        return [
            [
                anchor_x
                + scale * ((x - center_x) * cos_yaw + (z - center_z) * sin_yaw),
                anchor_z
                + scale * (-(x - center_x) * sin_yaw + (z - center_z) * cos_yaw),
            ]
            for x, z in points
        ]

    regions = []
    for region in water["regions"]:
        if not region.get("enabled"):
            continue
        look = sanitize_look(region.get("look"))
        regions.append(
            {
                "outline": ring(region["outline"]),
                "holes": [ring(hole) for hole in region.get("holes", [])],
                "y": float(spec.get("bottom_y") or 0) + scale * region["level"],
                "bed_y": float(spec.get("bottom_y") or 0) + scale * region["bed"],
                "tint": look["tint"],
                "opacity": 1 - 0.6 * look["clarity"],
                "swim_from_m": 1.0,
            }
        )
    return {"regions": regions} if regions else None


def water_region_at(specs, x, z, lift_of=None):
    """Return the highest lifted region containing (x, z), excluding its holes.

    Overlapping placements must carry a walker on the upper water surface,
    matching the highest-surface rule and the client lookup (spec § 9).
    The caller selects eligible storeys and supplies their placement lifts.
    Return only y, bed_y and swim_from_m, or None where no region answers."""
    best = None
    for spec in specs:
        for region in (spec.get("water") or {}).get("regions", []):
            if _contains(region, x, z):
                lift = lift_of(spec) if lift_of else 0.0
                answer = {field: region[field] + lift for field in ("y", "bed_y")}
                answer["swim_from_m"] = region["swim_from_m"]
                if best is None or answer["y"] > best["y"]:
                    best = answer
    return best


_detect_lock = threading.Lock()
_detect_jobs = {}


def request_detection(resolve, *, wait=False):
    """Resolve model/fix at execution time and coalesce repeated background requests.

    The resolver returns (model path, rotation, target_m, measure). Waiting
    for the LOD slot happens in the worker unless a script asks for wait=1.
    """
    initial = resolve()

    def run(args):
        model_path, rotation, target_m, measure = args
        water, reason = detect_water(
            model_path, rotation, target_m=target_m, measure=measure, wait_s=300
        )
        if reason != "ok":
            logger.info("Water detection %s: %s", model_path, reason)
        return {
            "status": water_status(model_path, rotation)["status"],
            "water": water,
            **({"reason": reason} if reason != "ok" else {}),
        }

    if wait:
        return run(initial)
    key = str(Path(initial[0]).resolve())
    with _detect_lock:
        if key in _detect_jobs:
            _detect_jobs[key] = resolve
            return {"started": True}
        _detect_jobs[key] = None

    def work():
        current = resolve
        try:
            while True:
                try:
                    run(current())
                except Exception:
                    logger.exception("Water detection worker failed: %s", key)
                with _detect_lock:
                    pending = _detect_jobs[key]
                    if pending is None:
                        del _detect_jobs[key]
                        return
                    _detect_jobs[key] = None
                    current = pending
        except BaseException:
            with _detect_lock:
                _detect_jobs.pop(key, None)
            raise

    try:
        threading.Thread(target=work, daemon=True, name="model-water-detect").start()
    except RuntimeError:
        with _detect_lock:
            _detect_jobs.pop(key, None)
        raise
    return {"started": True}
