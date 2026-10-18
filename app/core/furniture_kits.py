"""Shared furniture seeds and deterministic, storage-free role resolution.

World and hull access is lazy and confined to the optional catalog context.
"""
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROLES: Tuple[str, ...] = (
    "bed", "nightstand", "wardrobe", "chest", "dining_table", "chair",
    "sofa", "armchair", "coffee_table", "desk", "shelf", "cupboard",
    "counter", "stove", "washstand", "bathtub", "rug", "ceiling_light",
    "workbench", "bar_counter", "toilet",
)
_SEED_DIR = Path(__file__).resolve().parents[2] / "shared" / "furniture"
_CACHE: Dict[Path, Tuple[int, Dict]] = {}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_kits(kits: Dict) -> None:
    for kid, kit in kits.items():
        _require(isinstance(kit, dict), f"Invalid kit: {kid}")
        _require(isinstance(kit.get("name"), str) and bool(kit["name"]), f"Missing kit name: {kid}")
        _require(isinstance(kit.get("hull_styles"), list) and all(isinstance(s, str) and s for s in kit["hull_styles"]), f"Invalid hull styles: {kid}")
        props = kit.get("props")
        _require(isinstance(props, list) and len(props) == 20, f"Expected 20 props: {kid}")
        seen = set()
        for prop in props:
            _require(isinstance(prop, dict), f"Invalid prop: {kid}")
            role = prop.get("role")
            _require(role in ROLES and role not in seen, f"Invalid or duplicate role: {kid}/{role}")
            seen.add(role)
            for key in ("name", "prompt", "category"):
                _require(isinstance(prop.get(key), str) and bool(prop[key].strip()), f"Invalid {key}: {kid}/{role}")
            for key in ("width_m", "depth_m", "height_m"):
                value = prop.get(key)
                _require(type(value) in (int, float) and math.isfinite(value) and value > 0, f"Invalid {key}: {kid}/{role}")
            _require(prop.get("mount") == ("ceiling" if role == "ceiling_light" else "floor"), f"Invalid mount: {kid}/{role}")
            _require(role != "rug" or prop["height_m"] <= .05, f"Rug too high: {kid}")


def _validate_room_types(types: Dict) -> None:
    from app.core.furnish_solver import (
        _FLOOR_ANCHORS, _WALL_PASS_ANCHORS, _CEILING_PASS_ANCHORS,
        _SURFACE_PASS_ANCHORS,
    )
    anchors = (_FLOOR_ANCHORS | _WALL_PASS_ANCHORS | _CEILING_PASS_ANCHORS |
               _SURFACE_PASS_ANCHORS | {"wall", "corner"})
    for tid, room_type in types.items():
        _require(isinstance(room_type, dict) and isinstance(room_type.get("name"), str) and bool(room_type["name"]), f"Invalid room type: {tid}")
        keywords = room_type.get("keywords")
        _require(isinstance(keywords, list) and bool(keywords) and all(isinstance(k, str) and k.strip() for k in keywords), f"Invalid keywords: {tid}")
        template = room_type.get("template")
        _require(isinstance(template, list) and bool(template), f"Invalid template: {tid}")
        for entry in template:
            _require(isinstance(entry, dict), f"Invalid entry: {tid}")
            _require(entry.get("role") in ROLES and ("ref" not in entry or entry["ref"] in ROLES), f"Invalid role/ref: {tid}")
            _require(entry.get("anchor") in anchors, f"Invalid anchor: {tid}")
            _require(entry["anchor"] != "wall" or entry.get("wall") in ("main", "other", "any"), f"Invalid wall: {tid}")
            count = entry.get("count", 1)
            _require(type(count) is int or isinstance(count, dict), f"Invalid count: {tid}")
            if isinstance(count, dict):
                _require(set(count) <= {"base", "per_m2", "per_ref", "max"} and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in count.values()), f"Invalid count formula: {tid}")
            else:
                _require(count >= 0, f"Negative count: {tid}")


def _load(filename: str, key: str, validate) -> Dict:
    path = _SEED_DIR / filename
    mtime = path.stat().st_mtime_ns
    cached = _CACHE.get(path)
    if cached is None or cached[0] != mtime:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)[key]
        _require(isinstance(data, dict) and bool(data), f"Invalid seed: {filename}")
        validate(data)
        _CACHE[path] = (mtime, data)
    return _CACHE[path][1]


def load_kits() -> Dict[str, Dict]:
    return _load("kits.json", "kits", _validate_kits)


def load_room_types() -> Dict[str, Dict]:
    return _load("room_types.json", "room_types", _validate_room_types)


def guess_room_type(room: Dict) -> str:
    types = load_room_types()
    for field in ("name", "description", "activity_hint"):
        text = str(room.get(field) or "").lower()
        winner, length = "", 0
        for tid, spec in types.items():
            for keyword in spec["keywords"]:
                keyword = keyword.lower()
                match = keyword in text if len(keyword) >= 4 else re.search(r"\b" + re.escape(keyword) + r"\b", text)
                if match and len(keyword) > length:
                    winner, length = tid, len(keyword)
        if winner:
            return winner
    return ""


def room_type_of(room: Dict) -> str:
    explicit = room.get("room_type")
    return explicit if isinstance(explicit, str) and explicit in load_room_types() else guess_room_type(room)


def kit_for_location(location_id: str) -> Optional[str]:
    if not location_id:
        return None
    try:
        from app.core.hull_model import hull_status
        status = hull_status(location_id)
        if not status.get("active"):
            return None
        style = (status.get("description") or {}).get("style") or ""
        return next((kid for kid, kit in load_kits().items() if style in kit["hull_styles"]), None)
    except Exception:
        # Optional context: missing storage, hull or location means no suggestion.
        return None


def kit_candidates(library: Dict[str, Dict], kit: str, role: str) -> List[str]:
    required = {f"kit:{kit.strip().lower()}", f"role:{role.strip().lower()}"}
    return sorted(pid for pid, prop in library.items()
                  if required <= {tag.strip().lower() for tag in (prop.get("tags") or []) if isinstance(tag, str)})


def pick_prop(candidates: List[str], room_id: str, role: str) -> str:
    if not candidates:
        return ""
    ordered = sorted(candidates)
    index = int(hashlib.sha1(f"{room_id}|{role}".encode("utf-8")).hexdigest(), 16) % len(ordered)
    return ordered[index]


def resolve_count(spec: Any, *, area_m2: float, ref_instances: int) -> int:
    from app.core.furnish_needs import MAX_COUNT
    if isinstance(spec, dict):
        value = (spec["per_ref"] * ref_instances if "per_ref" in spec
                 else spec.get("base", 1) + math.floor(area_m2 * spec.get("per_m2", 0)))
        value = min(spec.get("max", MAX_COUNT), value)
    else:
        value = 1 if spec is None else spec
    return max(0, min(MAX_COUNT, int(value)))


def catalog(location_id: str = "", room_id: str = "", *, library: Dict[str, Dict]) -> Dict:
    kits, types = load_kits(), load_room_types()
    room = None
    if room_id:
        try:
            from app.models.world import (find_location_by_room,
                                          get_location_by_id, get_room_by_id)
            # Room ids are unique per LOCATION only (every location has the
            # ground room) — the location, when named, decides.
            location = (get_location_by_id(location_id) if location_id
                        else find_location_by_room(room_id))
            room = get_room_by_id(location, room_id) if location else None
        except Exception:
            room = None
    roles = {tid: list(dict.fromkeys(e["role"] for e in spec["template"])) for tid, spec in types.items()}
    explicit = (room or {}).get("room_type")
    return {
        "kits": [{"id": kid, "name": kit["name"]} for kid, kit in kits.items()],
        "room_types": [{"id": tid, "name": spec["name"], "roles": roles[tid]} for tid, spec in types.items()],
        "location_kit": kit_for_location(location_id),
        "room_type": explicit if isinstance(explicit, str) and explicit in types else None,
        "room_type_guess": (guess_room_type(room) or None) if room else None,
        "missing_roles": {kid: {tid: [role for role in roles[tid] if not kit_candidates(library, kid, role)] for tid in types} for kid in kits},
    }
