"""Terrain-type catalog (Seamless World, E1).

Data-driven ground vocabulary for the painted terrain areas: what a kind
looks like on the schematic 2D map (color), whether it can be walked on
and how fast. NO terrain property is ever hardcoded anywhere else — every
consumer (passability, payload, editor palette) reads this catalog.

Two layers, override-replace per kind (the activity-library rule): the
shared seed ``shared/terrain/types.json`` ships the defaults, a world row
in ``terrain_types`` replaces the whole entry of the same kind. Deleting a
world row brings the shared entry back; shared entries are never deleted.

``kind`` follows the surface-texture id rule and SHOULD match a
surface-texture kind so the 3D ground can pick up a real texture — that
link is a convention, never enforced here.
"""

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SPEED_MIN, SPEED_MAX = 0.0, 2.0
DEFAULT_COLOR = "#888888"


def _shared_path() -> Path:
    from app.core.paths import get_shared_dir
    return get_shared_dir() / "terrain" / "types.json"


def _shared_types() -> Dict[str, Dict[str, Any]]:
    try:
        raw = json.loads(_shared_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("shared terrain types unreadable — empty catalog base")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for entry in (raw.get("types") or []):
        try:
            entry = sanitize_type(entry)
        except ValueError:
            continue
        out[entry["kind"]] = entry
    return out


def sanitize_type(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one catalog entry; raises ValueError on junk."""
    if not isinstance(raw, dict):
        raise ValueError("terrain type must be an object")
    kind = str(raw.get("kind") or "").strip()
    if not _KIND_RE.match(kind):
        raise ValueError(f"invalid terrain kind: {kind!r}")
    name = str(raw.get("name") or "").strip()[:60] or kind
    color = str(raw.get("color") or "").strip()
    if color and not _COLOR_RE.match(color):
        raise ValueError(f"invalid color for {kind}: {color!r}")
    try:
        speed = float(raw.get("speed_factor", 1.0))
    except (TypeError, ValueError):
        speed = 1.0
    # NaN/inf must never reach the clamp: every NaN comparison is False, so
    # min/max hand it straight through and the un-renderable value poisons
    # every later JSON response. Non-finite is junk — fall back to the default.
    if not math.isfinite(speed):
        speed = 1.0
    speed = min(max(speed, SPEED_MIN), SPEED_MAX)
    meta = raw.get("meta")
    return {
        "kind": kind,
        "name": name,
        "color": color or DEFAULT_COLOR,
        "passable": bool(raw.get("passable", True)),
        "speed_factor": round(speed, 2),
        "meta": meta if isinstance(meta, dict) else {},
    }


def _world_types() -> Dict[str, Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT kind, name, color, passable, speed_factor, meta "
        "FROM terrain_types").fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            meta = json.loads(r[5] or "{}")
        except ValueError:
            meta = {}
        out[r[0]] = {"kind": r[0], "name": r[1] or r[0],
                     "color": r[2] or DEFAULT_COLOR, "passable": bool(r[3]),
                     "speed_factor": float(r[4]),
                     "meta": meta if isinstance(meta, dict) else {}}
    return out


def effective_catalog() -> Dict[str, Dict[str, Any]]:
    """shared overlaid by world rows — override-replace per kind."""
    catalog = _shared_types()
    catalog.update(_world_types())
    return catalog


def sources() -> Dict[str, str]:
    """Where each effective kind comes from: ``"shared"`` or ``"world"``."""
    shared = set(_shared_types())
    world = set(_world_types())
    return {k: ("world" if k in world else "shared")
            for k in shared | world}


def get_type(kind: str) -> Optional[Dict[str, Any]]:
    """One effective entry, or None when the kind is unknown."""
    return effective_catalog().get((kind or "").strip())


def save_world_type(raw: Any) -> Dict[str, Any]:
    """Create/replace the WORLD override of one kind; returns the sanitized
    entry. Raises ValueError when the entry is not usable."""
    entry = sanitize_type(raw)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO terrain_types (kind, name, color, passable, "
            "speed_factor, meta, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(kind) DO UPDATE SET name=excluded.name, "
            "color=excluded.color, passable=excluded.passable, "
            "speed_factor=excluded.speed_factor, meta=excluded.meta, "
            "updated_at=excluded.updated_at",
            (entry["kind"], entry["name"], entry["color"],
             1 if entry["passable"] else 0, entry["speed_factor"],
             json.dumps(entry["meta"], ensure_ascii=False), utc_now_iso()))
    return entry


def delete_world_type(kind: str) -> bool:
    """Drop the world override of one kind. A shared entry of the same kind
    stays untouched and becomes effective again."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM terrain_types WHERE kind=?",
                           ((kind or "").strip(),))
        deleted = cur.rowcount > 0
    return deleted
