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


def wall_ranking(outline_m, openings, piece_height_m: float) -> List[Tuple[str, float]]:
    """Rank usable wall lengths at this height so low pieces can use window walls.

    Use the solver centroid and edge classes, including diagonal edges that
    belong to two classes. Opening zones supply the same defaults and parsing
    as placement; their widths include the solver clearance of 0.4 metres.
    """
    from app.core import furnish_geometry as fg

    if not outline_m:
        return [(wall, 0.0) for wall in ("n", "e", "s", "w")]
    centroid = (sum(p[0] for p in outline_m) / len(outline_m),
                sum(p[1] for p in outline_m) / len(outline_m))
    openings = list(openings or [])
    blocked = []
    for zone in fg.opening_zones(outline_m, centroid, openings):
        op = openings[zone.opening]
        if str(op.get("type") or "door") == "window" and zone.y0 >= piece_height_m:
            continue
        edge = int(op.get("edge") or 0) % len(outline_m)
        width = math.dist(zone.corners[0], zone.corners[3])
        blocked.append((edge, width))
    ranked = []
    for wall in ("n", "e", "s", "w"):
        edges = fg.wall_edges(outline_m, centroid, wall)
        free = sum(fg.edge_geometry(outline_m, centroid, i)[3] for i in edges)
        free -= sum(width for edge, width in blocked if edge in edges)
        # Suppress floating arithmetic noise without changing geometric ordering.
        ranked.append((wall, round(free, 10)))
    return sorted(ranked, key=lambda row: -row[1])


def plan_room(*, kit: str, room_type: str, geom: Dict, library: Dict,
              room_id: str, template=None) -> Dict:
    """Resolve each template entry separately so repeated props keep their anchors.

    Drop dependencies to a fixed point before choosing main: otherwise a missing
    bed would still choose the wall of a wardrobe that survives it. Counts use
    plan instances only, and share the review count cap across repeated props.
    """
    from app.core.furnish_needs import MAX_COUNT
    from app.core.furnish_solver import _CORNER_ANCHORS

    template = (load_room_types()[room_type]["template"] if template is None else template)
    roles = list(dict.fromkeys(entry["role"] for entry in template))
    chosen = {role: pick_prop(kit_candidates(library, kit, role), room_id, role)
              for role in roles}
    missing = [role for role in roles if not chosen[role]]
    surviving = [entry for entry in template if chosen[entry["role"]]]
    while True:
        present = {entry["role"] for entry in surviving}
        kept = [entry for entry in surviving if not entry.get("ref") or entry["ref"] in present]
        if len(kept) == len(surviving):
            break
        surviving = kept

    counts, visiting = {}, set()

    def count_at(index):
        if index in counts:
            return counts[index]
        if index in visiting:
            raise ValueError("Cyclic furniture count references")
        visiting.add(index)
        entry = surviving[index]
        spec = entry.get("count", 1)
        refs = 0
        if isinstance(spec, dict) and "per_ref" in spec:
            refs = sum(count_at(i) for i, other in enumerate(surviving)
                       if other["role"] == entry.get("ref"))
        value = resolve_count(spec, area_m2=geom["area_m2"], ref_instances=refs)
        pid = chosen[entry["role"]]
        used = sum(count_at(i) for i in range(index)
                   if chosen[surviving[i]["role"]] == pid)
        counts[index] = min(value, max(0, MAX_COUNT - used))
        visiting.remove(index)
        return counts[index]

    resolved = [(entry, count_at(i)) for i, entry in enumerate(surviving)]
    entries, needs = [], []
    main, corners = None, set()
    for raw, count in resolved:
        # build_items normalises zero to one, so zero-count slots must disappear.
        if count == 0:
            continue
        pid = chosen[raw["role"]]
        prop = library[pid]
        anchor = raw["anchor"]
        slot = raw.get("wall") if anchor == "wall" else "corner" if anchor == "corner" else None
        if anchor == "wall":
            ranking = wall_ranking(geom["outline_m"], geom.get("openings"),
                                   float(prop.get("height_m") or 0))
            if main is None:
                main = ranking[0][0]
            wall = (main if slot == "main" else
                    next(w for w, _ in ranking if slot != "other" or w != main))
            anchor = f"wall_{wall}"
        elif anchor == "corner":
            anchor = next((c for c in _CORNER_ANCHORS if c not in corners),
                          _CORNER_ANCHORS[0])
            corners.add(anchor)
        entry = {"prop": pid, "count": count, "anchor": anchor, "slot": slot}
        for key in ("facing", "base_m"):
            if key in raw:
                entry[key] = raw[key]
        if raw.get("ref"):
            entry["ref"] = chosen[raw["ref"]]
        entries.append(entry)
        needs.append({
            "key": f"n{len(needs) + 1}", "kind": str(prop.get("name") or pid),
            "category": str(prop.get("category") or ""), "count": count,
            "mount": str(prop.get("mount") or "floor"),
            "width_m": prop.get("width_m"), "depth_m": prop.get("depth_m"),
            "height_m": prop.get("height_m"), "style": "",
            "description": str(prop.get("description") or ""),
            "marker": None, "key_areas": [], "from_description": False,
            "prop_id": pid, "build": False})
    return {"entries": entries, "missing_roles": missing, "needs": needs}


def solve_kit(*, kit: str, room_type: str, geom: Dict, library: Dict,
              room_id: str, existing, storey_height_m: float, template=None) -> Dict:
    """Solve and retry bounded alternatives without worsening any placement pass.

    Replaying the whole plan keeps dependent pieces attached to moved supports.
    Review items may merge props, but the solver always sees the separate slots.
    """
    from app.core import furnish_place as fp, furnish_solver as fs

    planned = plan_room(kit=kit, room_type=room_type, geom=geom, library=library,
                        room_id=room_id, template=template)
    plan = [dict(entry) for entry in planned["entries"]]
    items = fp.build_items(planned["needs"], library)
    props = fp.solver_props(items, library)
    mounts = {item["id"]: item["mount"] for item in items}

    def solve(entries):
        result = fs.solve(outline_m=geom["outline_m"], openings=geom.get("openings"),
                          existing=existing, plan=entries, props=props,
                          storey_height_m=storey_height_m)
        result["phase_counts"] = fp.phase_counts(result, mounts)
        return result

    def has_unplaced(index, entries, result):
        pid = entries[index]["prop"]
        if not any(u["name"] == pid for u in result["unplaced"]):
            return False
        if sum(e["prop"] == pid for e in entries) == 1:
            return True
        # Failures name props, not template entries. Replay execution prefixes
        # only for repeated props, so a failed sibling cannot move a fitted slot.
        # Wall/corner floor entries precede center batches; wall entries follow
        # the whole floor pass, so these prefixes preserve the solver state.
        def execution_key(i):
            mount = mounts[entries[i]["prop"]]
            phase = fp.MOUNT_PASS.get(mount, "floor")
            ranks = fs._FLOOR_RANK if phase == "floor" else fs._WALL_RANK
            return (fp.PASSES.index(phase), ranks.get(entries[i]["anchor"], 3), i)

        key = execution_key(index)
        prefix = [e for i, e in enumerate(entries) if execution_key(i) < key]
        before = solve(prefix)
        after = solve(prefix + [entries[index]])
        return (sum(u["name"] == pid for u in after["unplaced"])
                > sum(u["name"] == pid for u in before["unplaced"]))

    result = solve(plan)
    for index, entry in enumerate(plan):
        if entry["slot"] not in ("main", "other", "any", "corner"):
            continue
        if not has_unplaced(index, plan, result):
            continue
        if entry["slot"] == "corner":
            used = {e["anchor"] for i, e in enumerate(plan) if i != index
                    and e["anchor"] in fs._CORNER_ANCHORS}
            alternatives = [a for a in fs._CORNER_ANCHORS
                            if a not in used and a != entry["anchor"]]
        else:
            ranking = wall_ranking(geom["outline_m"], geom.get("openings"),
                                   float(props[entry["prop"]].get("height_m") or 0))
            anchors = [f"wall_{wall}" for wall, _ in ranking]
            start = anchors.index(entry["anchor"])
            alternatives = anchors[start + 1:] + anchors[:start]
        for anchor in alternatives[:3]:
            trial = [dict(e) for e in plan]
            trial[index]["anchor"] = anchor
            candidate = solve(trial)
            before = fp.pass_summary(result["phase_counts"])
            after = fp.pass_summary(candidate["phase_counts"])
            # A move must GAIN a piece: an equal trade would shuffle the
            # rest of the room for nothing and leave a still-failing slot.
            gained = (sum(after[p]["placed"] for p in fp.PASSES)
                      > sum(before[p]["placed"] for p in fp.PASSES))
            if gained and all(after[p]["placed"] >= before[p]["placed"]
                              and after[p]["unplaced"] <= before[p]["unplaced"]
                              for p in fp.PASSES):
                plan, result = trial, candidate
            if not has_unplaced(index, plan, result):
                break
    return {"plan": plan, **result, "missing_roles": planned["missing_roles"],
            "items": items, "needs": planned["needs"]}
