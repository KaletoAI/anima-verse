"""Shared World-Dev layout prompt context and fenced JSON extraction."""
import json
from typing import Any, Dict, List, Optional
from app.core.log import get_logger
from app.core.paths import get_schemas_dir as _get_schemas_dir
from app.models.world import get_location_by_id
logger = get_logger("world_dev")


def load_schema(schema_name: str, **kwargs) -> str:
    """Loads a schema definition file and fills in placeholders.

    Schemas use literal `{key}` placeholders. Do not use .format(): their
    JSON examples contain braces that must remain literal.
    """
    path = _get_schemas_dir() / f"{schema_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Schema '{schema_name}' nicht gefunden: {path}")
    content = path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        content = content.replace(f"{{{key}}}", str(value))
    return content


def layout_target(location_id: str) -> Optional[Dict[str, Any]]:
    """The location a layout draft is about, or None when none was picked."""
    loc_id = (location_id or "").strip()
    if not loc_id:
        return None
    return get_location_by_id(loc_id)


def format_layout_location(loc: Optional[Dict[str, Any]]) -> str:
    """`{layout_location}` — the plot: its outline in local metres, its size,
    its storey height, indoor/outdoor, and where one may already walk in.

    The outline is quoted POINT FOR POINT, not simplified: unlike a map draft
    (where a wood is a shape, not a tracing) a floor plan is measured against
    these very edges, and the model has to be able to snap a room flush to one.
    """
    from app.core.scene_recipe import DEFAULT_STOREY_REAL_M

    if not loc:
        return ("No location selected. Ask the user which place the plan is "
                "for — a floor plan always belongs to one location.")
    map3d = loc.get("map3d") if isinstance(loc.get("map3d"), dict) else {}
    boundary = map3d.get("boundary") or []
    lines: List[str] = [
        f"**{loc.get('name') or loc.get('id')}** (`{loc.get('id')}`)",
    ]
    desc = " ".join(str(loc.get("description") or "").split())
    if desc:
        lines.append(desc)
    indoor = str(loc.get("indoor") or "").strip() or "unspecified"
    storey = map3d.get("storey_height_m") or DEFAULT_STOREY_REAL_M
    lines.append(f"- indoor/outdoor: {indoor}")
    lines.append(f"- storey height: {float(storey):g} m "
                 f"(one `level` step is this tall)")
    if boundary:
        width = map3d.get("plan_width_m")
        xs = [float(p[0]) for p in boundary]
        zs = [float(p[1]) for p in boundary]
        lines.append(
            f"- plot outline ({len(boundary)} points, local metres, edge i "
            f"runs from point i to point i+1): "
            + json.dumps([[round(float(p[0]), 2), round(float(p[1]), 2)]
                          for p in boundary]))
        lines.append(f"- the plot spans x {min(xs):g} … {max(xs):g} and "
                     f"y {min(zs):g} … {max(zs):g} metres"
                     + (f" (widest side {float(width):g} m)" if width else ""))
    else:
        lines.append("- **This location has no drawn plot outline.** Nothing "
                     "can be checked against it and `boundary_openings` have "
                     "no edge to sit on — say so, and keep the plan modest "
                     "(a few tens of metres around the origin).")
    entry_room = str(loc.get("entry_room") or "").strip()
    if entry_room:
        lines.append(f"- current entry room: `{entry_room}`")
    bo = map3d.get("boundary_openings") or []
    if bo:
        lines.append(f"- {len(bo)} boundary opening(s) already exist: "
                     + json.dumps(bo))
    return "\n".join(lines)


def format_layout_rooms(loc: Optional[Dict[str, Any]]) -> str:
    """`{layout_rooms}` — every room of the location with its CURRENT plan.

    A room already carrying a layout is quoted with its exact numbers, so
    "leave the kitchen where it is" is something the model can actually obey by
    copying them back out.
    """
    from app.models.world import GROUND_ROOM_ID, is_floor_room
    if not loc:
        return "— (no location selected)"
    lines: List[str] = []
    for room in loc.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("id") or "")
        # Neither the ground nor a storey's corridor carries a plan of its
        # own — the server derives both, so the model must not be offered
        # them as rooms it may place (spec § 4).
        if room_id == GROUND_ROOM_ID or is_floor_room(room_id):
            continue
        head = f"- `{room_id}` — **{room.get('name') or room_id}**"
        lay = room.get("layout") if isinstance(room.get("layout"), dict) else {}
        if lay:
            head += (f" · at x={lay.get('x')}, y={lay.get('y')}, "
                     f"{lay.get('w')} × {lay.get('d')} m, level "
                     f"{lay.get('level', 0)}")
            if lay.get("no_walls"):
                head += ", open sub-area"
            if lay.get("outline"):
                head += f", drawn outline ({len(lay['outline'])} points)"
            if lay.get("openings"):
                head += f", {len(lay['openings'])} opening(s)"
        else:
            head += " · **no plan yet**"
        desc = " ".join(str(room.get("description") or "").split())
        if len(desc) > 200:
            desc = desc[:200].rstrip() + "…"
        lines.append(head + (f"\n  {desc}" if desc else ""))
    if not lines:
        return ("This location has no rooms yet — every room in your plan is a "
                "new one (give it a `name` and a `description`).")
    return "\n".join(lines)


def format_surface_kinds() -> str:
    """`{surface_kinds}` — the ids the shared surface-texture library holds."""
    from app.core.surface_textures import library_kinds
    kinds = sorted(library_kinds())
    if not kinds:
        return ("The surface library is empty — leave `surfaces` out of every "
                "room.")
    return ", ".join(f"`{k}`" for k in kinds)


def extract_json_block(text: str, block_type: str) -> Dict[str, Any] | None:
    """Extracts a JSON from ```json:<block_type> ... ``` code blocks."""
    import re
    # Match ```json:type with optional whitespace, newlines, and closing ```
    pattern = rf'```json:{re.escape(block_type)}\s*\n(.*?)```'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        # Missing closing fence — the model stopped right after the JSON or
        # the output was cut off mid-block. Try to parse from the opening
        # fence to the end of the text (raw_decode stops at the JSON end, so
        # trailing prose does not hurt). Truly truncated JSON still fails —
        # the caller reports that via extraction_warning.
        open_m = re.search(rf'```json:{re.escape(block_type)}\s*\n', text)
        if not open_m:
            return None
        tail = text[open_m.end():].strip()
        try:
            parsed, _ = json.JSONDecoder().raw_decode(tail)
            if isinstance(parsed, dict):
                logger.info("Extracted %s JSON (unclosed fence): %d keys",
                            block_type, len(parsed))
                return parsed
        except json.JSONDecodeError:
            logger.warning("json:%s block found but not parseable — output "
                           "truncated mid-JSON?", block_type)
        return None
    raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
        logger.info("Extracted %s JSON: %d keys", block_type, len(parsed))
        return parsed
    except json.JSONDecodeError:
        # Tolerate common LLM JSON glitches: leading "+" on positive numbers
        # ("attention_change": +5) and trailing commas before } or ].
        sanitized = re.sub(r'([:\[,]\s*)\+(\d)', r'\1\2', raw)
        sanitized = re.sub(r',(\s*[}\]])', r'\1', sanitized)
        # German prose quotes opened typographically but closed with an ASCII
        # quote („wie früher war") end the JSON string early. „ only ever
        # opens a quotation, so the next ASCII quote on its line is its
        # closing mark: turn it into “.
        sanitized = re.sub(r'„([^"“”„\n]*)"', '„\\1“', sanitized)
        try:
            parsed = json.loads(sanitized)
            logger.info("Extracted %s JSON (after sanitize): %d keys", block_type, len(parsed))
            return parsed
        except json.JSONDecodeError as e2:
            logger.warning("Failed to parse %s JSON: %s\nNear: %r", block_type, e2,
                           sanitized[max(0, e2.pos - 120):e2.pos + 40])
            return None


def world_setup_block() -> str:
    """World premise prefix shared by World-Dev schemas and building proposals."""
    from app.models.world_setup import get_world_setup_text
    text = get_world_setup_text()
    return (f"## World setup\n\nThe world this content goes into:\n\n{text}\n\n"
            if text else "")
