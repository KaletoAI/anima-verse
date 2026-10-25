"""One-time conversion of terrain clips to movement types and world poses."""
from collections import Counter
from copy import deepcopy
import json
from typing import Dict, List, Tuple

from app.core.log import get_logger
from app.core.movement import shared_pose_kind

logger = get_logger("terrain_movement_migration")
_GUARD_KEY = "migrated_terrain_movement_v1"


def plan_terrain_movement(rows: List[Dict], swim_clip: str,
                          tread_clip: str) -> Tuple[List[Dict], Dict[str, str], List[str]]:
    """Return changed rows, pose overrides and warnings without mutating input.

    Count all nonempty water clips, including shipped ones: the most common
    historical choice wins. Alphabetical order resolves equal counts.
    """
    changed, overrides, warnings = [], {}, []
    votes = {"swimming": Counter(), "treading_water": Counter()}
    for row in rows:
        meta = row.get("meta") or {}
        if not any(key in meta for key in ("move_anim", "idle_anim")):
            continue
        updated = deepcopy(row)
        updated["meta"] = meta = deepcopy(meta)
        water = bool(meta.get("water"))
        meta["movement"] = "swim" if water else "walk_run"
        for key, pose in (("move_anim", "swimming"), ("idle_anim", "treading_water")):
            clip = meta.pop(key, None)
            if water and isinstance(clip, str) and clip.strip():
                votes[pose][clip.strip()] += 1
        if not water:
            warnings.append(f"Terrain {row['kind']!r}: non-water clips replaced with walk_run")
        changed.append(updated)
    for pose, shipped in (("swimming", swim_clip), ("treading_water", tread_clip)):
        counts = votes[pose]
        if not counts:
            continue
        winner = min(counts, key=lambda clip: (-counts[clip], clip))
        if len(counts) > 1:
            warnings.append(f"Terrain clips for {pose}: {dict(sorted(counts.items()))}; selected {winner!r}")
        if winner != shipped:
            overrides[pose] = winner
    return changed, overrides, warnings


def migrate_terrain_movement_once() -> Dict[str, int]:
    """Migrate the selected world's rows once; leave failed work retryable.

    Pose writes precede terrain writes, so a failed catalog write never
    discards the legacy clips needed for retry. The guard is set last.
    """
    from app.core.db import transaction
    from app.core.pose_catalog_edit import catalog_txn, read_store, write_store
    from app.core.terrain_types import _bump_types_generation
    from app.models.world import get_world_setting, set_world_setting

    if get_world_setting(_GUARD_KEY):
        return {}
    with transaction() as conn:
        rows = [{"kind": kind, "meta": json.loads(meta or "{}")}
                for kind, meta in conn.execute("SELECT kind, meta FROM terrain_types").fetchall()]
    changed, overrides, warnings = plan_terrain_movement(
        rows, shared_pose_kind("swimming"), shared_pose_kind("treading_water"))
    for warning in warnings:
        logger.warning("%s", warning)
    if overrides:
        with catalog_txn("pose"):
            data = read_store("pose", "world")
            shared = read_store("pose", "shared")["entries"]
            for key, clip in overrides.items():
                # The STORED entry, never get_catalog's normalised one: that adds
                # places/yaw_offset/_default/label, which a solo pose must not carry.
                entry = deepcopy(data["entries"].get(key) or shared[key])
                entry["animation"] = clip
                data["entries"][key] = entry
            write_store("pose", data, "world")
    if changed:
        with transaction() as conn:
            for row in changed:
                conn.execute("UPDATE terrain_types SET meta=? WHERE kind=?",
                             (json.dumps(row["meta"], ensure_ascii=False), row["kind"]))
        _bump_types_generation()
    set_world_setting(_GUARD_KEY, "1")
    return {"rows": len(rows), "changed": len(changed), "overrides": len(overrides),
            "warnings": len(warnings)}
