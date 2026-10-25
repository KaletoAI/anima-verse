"""Fixed movement poses and their played/public clip resolution."""
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

MOVEMENT_TYPES: Tuple[str, ...] = ("walk_run", "walk", "swim", "crawl")
MOVEMENT_POSES: Tuple[str, ...] = (
    "standing", "walking", "running", "swimming", "treading_water",
    "crawling", "crawling_rest",
)
MOVEMENT_ONLY_POSES: FrozenSet[str] = frozenset({
    "swimming", "treading_water", "crawling", "crawling_rest",
})
SITUATION_POSES: Dict[str, Tuple[str, str]] = {
    "walk_run": ("walking", "standing"),
    "walk": ("walking", "standing"),
    "swim": ("swimming", "treading_water"),
    "crawl": ("crawling", "crawling_rest"),
}


def movement_of(meta: Any) -> str:
    """Return a valid movement type, defaulting to walking and running."""
    value = meta.get("movement") if isinstance(meta, dict) else None
    return value if isinstance(value, str) and value in MOVEMENT_TYPES else "walk_run"


def shared_pose_kind(key: str) -> str:
    """Read a pose's clip kind from the shipped layer only."""
    from app.core.pose_catalog_edit import read_store
    entry = read_store("pose", "shared")["entries"].get(key) or {}
    return str(entry.get("animation") or "")


def played_pose_kind(key: str) -> str:
    """Read a pose's clip kind including world overrides."""
    from app.core.pose_catalog import get_catalog
    entry = get_catalog("pose").get(key) or {}
    return str(entry.get("animation") or "")


def movement_pose_kinds() -> Dict[str, Dict[str, str]]:
    """Resolve both clip kinds for all seven fixed movement poses."""
    from app.core.pose_catalog import get_catalog
    from app.core.pose_catalog_edit import read_store
    played = get_catalog("pose")
    shipped = read_store("pose", "shared")["entries"]
    return {pose: {"kind": str((played.get(pose) or {}).get("animation") or ""),
                   "public_kind": str((shipped.get(pose) or {}).get("animation") or "")}
            for pose in MOVEMENT_POSES}


def clip_file_for(kind: str, chain: List[str], *,
                  free_only: bool) -> Optional[Dict[str, str]]:
    """Find the first solo file along the set chain, then the neutral set."""
    from app.core.animation_clips import _scan_library, clip_entries, clip_view
    from app.core.paths import get_animation_clips_dirs
    if free_only:
        # Scan before merging: licensed twins must not hide public files.
        entries = [entry for root, source in get_animation_clips_dirs()
                   if source == "free" and root.exists()
                   for entry in _scan_library(root, source)]
    else:
        entries = clip_entries()
    for cset in chain + [""]:
        for entry in entries:
            if entry["kind"] == kind and entry["set"] == cset and not entry["role"]:
                view = clip_view(entry)
                return {field: view[field] for field in ("set", "library", "url")}
    return None
