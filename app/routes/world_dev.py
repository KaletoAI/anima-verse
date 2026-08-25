"""World Development routes - Chat with LLM to create/edit world elements."""
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Depends
from app.core.auth_dependency import require_admin
from fastapi.responses import StreamingResponse
from app.core.log import get_logger

logger = get_logger("world_dev")

from app.core.llm_router import create_llm_instance
from app.core.streaming import StreamingAgent, ContentEvent
from app.models.world import get_location_by_id, add_location
from app.models.character import (
    get_character_profile, save_character_profile,
    get_character_config, save_character_config,
    add_character_outfit)

router = APIRouter(prefix="/world-dev", tags=["world-dev"],
                   dependencies=[Depends(require_admin)])

from app.core.paths import get_schemas_dir as _get_schemas_dir

# In-memory session store
_sessions: Dict[str, Dict[str, Any]] = {}


def _load_schema(schema_name: str, **kwargs) -> str:
    """Loads a schema definition file and fills in placeholders.

    Schemas verwenden `{key}`-Notation (einfache Klammern) — wie in den .md-
    Dateien sichtbar. KEIN .format() weil die Schemas auch JSON-Beispiele mit
    geschweiften Klammern enthalten, die als Literal stehen bleiben muessen.
    """
    path = _get_schemas_dir() / f"{schema_name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Schema '{schema_name}' nicht gefunden: {path}")
    content = path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        content = content.replace(f"{{{key}}}", str(value))
    return content


def _create_llm(model: str, provider: str = "", max_tokens: Optional[int] = None):
    """Creates an LLMClient + LLMInstance for the given model."""
    instance = create_llm_instance(
        task="chat",
        model=model,
        provider_name=provider,
        max_tokens=max_tokens)
    if not instance:
        return None, None
    return instance.create_llm(), instance


def _format_generable_fields_for_templates(selected_template: str = "") -> str:
    """Generates a Markdown description of generable fields for the LLM.

    If selected_template is set, only that template's fields are shown.
    Otherwise all templates are listed.
    """
    from app.models.character_template import get_template

    if selected_template:
        template_names = [selected_template]
    else:
        template_names = ["human-default", "human-roleplay", "animal-default"]
    sections = []

    for tname in template_names:
        tmpl = get_template(tname)
        if not tmpl:
            continue

        label = tmpl.get("label", tname)
        fields_desc = []

        for section in tmpl.get("sections", []):
            for field in section.get("fields", []):
                if not field.get("llm_generable"):
                    continue
                key = field["key"]
                flabel = field.get("label_de", field.get("label", key))
                ftype = field.get("type", "text")
                required = " (Pflicht)" if field.get("required") else ""
                store = " [config]" if field.get("store") == "config" else ""

                # Build type description
                if ftype == "select" and "options" in field:
                    opts = [o["value"] for o in field["options"]]
                    type_info = f"Auswahl: {' | '.join(opts)}"
                elif ftype == "date":
                    type_info = "Datum (YYYY-MM-DD)"
                elif ftype == "number":
                    type_info = "Zahl (0-100)"
                else:
                    type_info = "Text"

                hint = field.get("hint_de", field.get("hint", ""))
                visible = field.get("visible_when")
                vis_note = ""
                if visible:
                    vis_note = f" (nur bei {visible['field']}={', '.join(visible['values'])})"

                default = field.get("default", "")
                if default and isinstance(default, str):
                    # Truncate long defaults but show enough context
                    if len(default) > 120:
                        default_note = f' Default (BEIBEHALTEN!): "{default[:120]}..."'
                    else:
                        default_note = f' Default (BEIBEHALTEN!): "{default}"'
                else:
                    default_note = ""

                fields_desc.append(
                    f"- `{key}` — {flabel} (PFLICHT){store}{vis_note}: {type_info}.{' ' + hint if hint else ''}{default_note}"
                )

        if fields_desc:
            sections.append(f"### {label} (`{tname}`)\n\n" + "\n".join(fields_desc))

    # Always-available fields
    always = [
        "- `character_name` — Name (Pflicht): Text. Eindeutiger Name des Characters.",
        "- `template` — Template (Pflicht): Auswahl: human-default | human-roleplay | animal-default",
        "- `outfits` — Outfit-Liste: Array von Objekten (siehe Outfit-Sektion unten).",
    ]
    header = "### Immer verfuegbare Felder\n\n" + "\n".join(always)

    return header + "\n\n" + "\n\n".join(sections)


def _format_existing_outfit_types() -> str:
    """Deprecated: outfit_types wurden durch Decency + style_hint ersetzt
    (Variante A). World Dev vergibt keine outfit_types mehr."""
    return ""


def _format_context_locations(location_ids: list) -> str:
    """Formats selected locations as detailed context for the LLM.

    Liefert nur die Bullet-Body-Zeilen (kein eigener Header) — der Header
    kommt aus dem Schema-Template (`## Bestehende Orte`).
    """
    if not location_ids:
        return ""
    lines: list = []
    for loc_id in location_ids:
        try:
            loc = get_location_by_id(loc_id)
        except Exception as e:
            logger.warning("Konnte Location %s nicht laden: %s", loc_id, e)
            continue
        if not loc or not isinstance(loc, dict):
            continue
        loc_name = loc.get("name") or loc.get("id") or loc_id
        lines.append(f"### {loc_name}")
        desc = loc.get("description", "")
        if desc:
            lines.append(f"{desc}\n")
        for room in (loc.get("rooms", []) or []):
            if not isinstance(room, dict):
                continue
            lines.append(f"**Raum: {room.get('name', '?')}**")
            room_desc = room.get("description", "")
            if room_desc:
                lines.append(f"{room_desc}")
            hint = (room.get("activity_hint") or "").strip()
            if hint:
                lines.append(f"Activity hint: {hint}")
            lines.append("")
    return "\n".join(lines)


def _format_context_characters(character_names: list) -> str:
    """Formats selected characters as detailed context for the LLM.

    Liefert nur die Bullet-Body-Zeilen (kein eigener Header) — der Header
    kommt aus dem Schema-Template (`## Bestehende Characters`).
    """
    if not character_names:
        return ""
    lines: list = []
    # Fields aus Profil-JSON
    context_keys = [
        "character_name", "template", "gender", "age", "language",
        "species", "breed", "communication",
    ]
    # Soul-Files: Inhalt aus MD-Datei (Source of Truth seit Plan 2)
    soul_files = [
        ("character_personality", "soul/personality.md"),
        ("character_task",        "soul/tasks.md"),
    ]
    for name in character_names:
        try:
            profile = get_character_profile(name)
        except Exception as e:
            logger.warning("Konnte Profil %s nicht laden: %s", name, e)
            continue
        if not profile or not profile.get("character_name"):
            continue
        lines.append(f"### {profile.get('character_name', name)}")
        for key in context_keys:
            val = profile.get(key)
            if val and key != "character_name":
                lines.append(f"- **{key}**: {val}")
        # Soul-MD-Inhalte
        try:
            from app.models.character import get_character_dir
            char_dir = get_character_dir(name)
            for key, rel in soul_files:
                md_path = char_dir / rel
                if not md_path.exists():
                    continue
                content = md_path.read_text(encoding="utf-8").strip()
                # Headings entfernen fuer kompakten Kontext, max 300 Zeichen
                clean = "\n".join(l for l in content.splitlines() if not l.startswith("#")).strip()
                if clean:
                    lines.append(f"- **{key}**: {clean[:300]}{'...' if len(clean) > 300 else ''}")
        except Exception as _se:
            logger.debug("Soul-Files fuer %s nicht lesbar: %s", name, _se)
        # Appearance (shortened)
        appearance = profile.get("character_appearance", "")
        if appearance:
            lines.append(f"- **character_appearance**: {appearance[:200]}{'...' if len(appearance) > 200 else ''}")
        # Outfit names — outfits.json statt embedded
        try:
            from app.models.character import get_character_outfits as _get_outfits
            outfits = _get_outfits(name)
        except Exception:
            outfits = []
        if outfits:
            outfit_names = [o.get("name", "?") for o in outfits
                            if isinstance(o, dict) and o.get("name")]
            if outfit_names:
                lines.append(f"- **outfits**: {', '.join(outfit_names)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Map schema context — the four placeholders `map.md` carries (E10 task 1).
# Everything the model needs to draw a map it cannot guess: which ground kinds
# exist in THIS world, which places may be positioned and how big they are,
# how far the world reaches today, and (edit mode) what is already painted.
# ---------------------------------------------------------------------------

def _format_terrain_kinds() -> str:
    """`{terrain_kinds}` — the world's EFFECTIVE terrain catalog as a list.

    Passability is spelled out in words rather than as a flag: it is the one
    property that makes a placement wrong, and "impassable" has to survive
    being skim-read.
    """
    from app.core.terrain_types import effective_catalog
    lines: List[str] = []
    for kind, entry in sorted(effective_catalog().items()):
        name = str(entry.get("name") or kind)
        passable = bool(entry.get("passable", True))
        try:
            speed = float(entry.get("speed_factor", 1.0))
        except (TypeError, ValueError):
            speed = 1.0
        lines.append(f"- `{kind}` — {name}, "
                     f"{'passable' if passable else '**IMPASSABLE**'}, "
                     f"walking pace ×{speed:g}")
    return "\n".join(lines) or "No terrain kinds configured."


def _format_placeable_locations(location_ids: Optional[List[str]] = None) -> str:
    """`{placeable_locations}` — the EXISTING places the model may position.

    The map schema also lets it propose NEW places as stubs (name +
    description + pin), which is why this list is not the whole world any more:
    it is the set of ids that may be positioned, and everything else the draft
    names is created. ``location_ids`` narrows the list to what the user ticked
    in the UI; None offers all of them.

    The width comes from ``location_model3d.derive_plan_width_m``, i.e. the
    bounding box of the drawn boundary — the same number the overlap warning
    measures with, so what the model is told to keep apart is what it is
    later measured against. A location without a boundary has none (0).
    """
    from app.core.location_model3d import derive_plan_width_m
    from app.models.world import list_locations

    wanted = set(location_ids or [])
    lines: List[str] = []
    for loc in list_locations():
        loc_id = loc.get("id") or ""
        if wanted and loc_id not in wanted:
            continue
        width = derive_plan_width_m(loc_id, loc.get("map3d"))
        px, pz = loc.get("pos_x"), loc.get("pos_z")
        if px is None or pz is None:
            where = "unplaced"
        else:
            where = (f"currently at x={float(px):g}, z={float(pz):g}, "
                     f"yaw {float(loc.get('yaw_deg') or 0.0):g}°")
        indoor = str(loc.get("indoor") or "").strip() or "unspecified"
        size = f"footprint {width:g} m" if width > 0 else "footprint not set"
        desc = " ".join(str(loc.get("description") or "").split())
        if len(desc) > 160:
            desc = desc[:160].rstrip() + "…"
        parts = [f"`{loc_id}` — **{loc.get('name') or loc_id}**",
                 size, indoor, where]
        line = " · ".join(parts)
        if desc:
            line += f"\n  {desc}"
        lines.append(f"- {line}")
    if not lines:
        return ("No locations exist yet — every place on this map has to be a "
                "new stub (`name` instead of `id`).")
    return "\n".join(lines)


def _format_world_bounds() -> str:
    """`{world_bounds}` — how far the world reaches today, in metres."""
    from app.core.map_layout_apply import current_world_bounds
    box = current_world_bounds()
    if not box:
        return ("The world has no extent yet — nothing is painted and no place "
                "is positioned. Propose your own `bounds`; a few hundred metres "
                "per side is a village, a few thousand a region.")
    span_x = box["max_x"] - box["min_x"]
    span_z = box["max_z"] - box["min_z"]
    return (f"The world currently spans x {box['min_x']:g} … {box['max_x']:g} "
            f"and z {box['min_z']:g} … {box['max_z']:g} metres "
            f"({span_x:g} × {span_z:g} m). Stay inside this box, or declare a "
            f"larger one in `bounds` and stay inside that.")


def _format_existing_map() -> str:
    """`{existing_map}` — the map as it stands, simplified (edit mode only).

    Polygons are boiled down to at most 12 points
    (``map_layout_apply.simplify_polygon``): the model has to recognise the
    shapes it is asked to change, not reproduce them to the centimetre, and a
    full map at 256 points per area would be most of the prompt.
    """
    from app.core.map_layout_apply import SIMPLIFY_MAX_POINTS, simplify_polygon
    from app.core.location_model3d import derive_plan_width_m
    from app.models.heightfield import list_height_areas
    from app.models.terrain import list_areas
    from app.models.world import list_locations

    def _pts(polygon: Any) -> str:
        simple = simplify_polygon(polygon, SIMPLIFY_MAX_POINTS)
        return json.dumps([[round(x, 1), round(z, 1)] for x, z in simple])

    blocks: List[str] = []

    area_lines: List[str] = []
    for area in list_areas():
        meta = area.get("meta") if isinstance(area.get("meta"), dict) else {}
        label = str(meta.get("label") or "").strip()
        stroke = meta.get("stroke") if isinstance(meta.get("stroke"), dict) else None
        head = f"- `{area.get('kind')}`"
        if label:
            head += f" \"{label}\""
        head += f" (z_order {area.get('z_order', 0)})"
        if stroke:
            line = simplify_polygon(stroke.get("points"), SIMPLIFY_MAX_POINTS) \
                or [[round(float(p[0]), 1), round(float(p[1]), 1)]
                    for p in (stroke.get("points") or [])]
            head += (f" — stroke width {stroke.get('width_m')} m, style "
                     f"{stroke.get('style') or 'straight'}, centre line "
                     + json.dumps([[round(x, 1), round(z, 1)] for x, z in line]))
        else:
            head += " — polygon " + _pts(area.get("polygon"))
        area_lines.append(head)
    blocks.append("### Painted areas\n\n"
                  + ("\n".join(area_lines) if area_lines
                     else "None — nothing is painted yet."))

    height_lines: List[str] = []
    for h in list_height_areas():
        meta = h.get("meta") if isinstance(h.get("meta"), dict) else {}
        label = str(meta.get("label") or "").strip()
        head = "- " + (f"\"{label}\" " if label else "")
        head += (f"height {h.get('height_m')} m, falloff "
                 f"{h.get('falloff_m')} m — polygon " + _pts(h.get("polygon")))
        height_lines.append(head)
    blocks.append("### Height areas\n\n"
                  + ("\n".join(height_lines) if height_lines
                     else "None — the ground is flat."))

    place_lines: List[str] = []
    for loc in list_locations():
        px, pz = loc.get("pos_x"), loc.get("pos_z")
        if px is None or pz is None:
            continue
        width = derive_plan_width_m(loc.get("id") or "", loc.get("map3d"))
        place_lines.append(
            f"- `{loc.get('id')}` **{loc.get('name') or ''}** at "
            f"x={float(px):g}, z={float(pz):g}, yaw "
            f"{float(loc.get('yaw_deg') or 0.0):g}°"
            + (f", footprint {width:g} m" if width > 0 else ""))
    blocks.append("### Placed locations\n\n"
                  + ("\n".join(place_lines) if place_lines
                     else "None — no place is positioned yet."))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Layout schema context — the three placeholders `layout.md` carries.
# A floor plan is drawn INSIDE one location, so everything here is about that
# one place: how big its plot is and what shape, which rooms exist and where
# they stand today, and which surface kinds the world's texture library holds.
# ---------------------------------------------------------------------------

def _layout_target(location_id: str) -> Optional[Dict[str, Any]]:
    """The location a layout draft is about, or None when none was picked."""
    loc_id = (location_id or "").strip()
    if not loc_id:
        return None
    return get_location_by_id(loc_id)


def _format_layout_location(loc: Optional[Dict[str, Any]]) -> str:
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


def _format_layout_rooms(loc: Optional[Dict[str, Any]]) -> str:
    """`{layout_rooms}` — every room of the location with its CURRENT plan.

    A room already carrying a layout is quoted with its exact numbers, so
    "leave the kitchen where it is" is something the model can actually obey by
    copying them back out.
    """
    from app.models.world import GROUND_ROOM_ID
    if not loc:
        return "— (no location selected)"
    lines: List[str] = []
    for room in loc.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("id") or "")
        if room_id == GROUND_ROOM_ID:
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


def _format_surface_kinds() -> str:
    """`{surface_kinds}` — the ids the shared surface-texture library holds."""
    from app.core.surface_textures import library_kinds
    kinds = sorted(library_kinds())
    if not kinds:
        return ("The surface library is empty — leave `surfaces` out of every "
                "room.")
    return ", ".join(f"`{k}`" for k in kinds)


def _extract_json_block(text: str, block_type: str) -> Dict[str, Any] | None:
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
        try:
            parsed = json.loads(sanitized)
            logger.info("Extracted %s JSON (after sanitize): %d keys", block_type, len(parsed))
            return parsed
        except json.JSONDecodeError as e2:
            logger.warning("Failed to parse %s JSON: %s\nRaw: %s", block_type, e2, raw[:200])
            return None


def _validate_character_fields(char_data: Dict[str, Any], selected_template: str = "") -> list[str]:
    """Checks which expected fields are missing or empty in character data.

    Returns a list of missing field descriptions for the LLM to complete.
    """
    from app.models.character_template import get_template

    missing = []

    # Always-required fields
    if not char_data.get("character_name"):
        missing.append("character_name (Name des Characters)")
    if not char_data.get("character_personality"):
        missing.append("character_personality (Persoenlichkeit)")
    if not char_data.get("character_appearance"):
        missing.append("character_appearance (Aussehen-Prompt)")

    # Determine template
    template = selected_template or char_data.get("template", "")
    if not template:
        missing.append("template (human-default | human-roleplay | animal-default)")
        return missing

    tmpl = get_template(template)
    if not tmpl:
        return missing

    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            if not field.get("llm_generable"):
                continue
            key = field["key"]
            # Skip fields already checked above
            if key in ("character_name", "character_personality", "character_appearance"):
                continue

            value = char_data.get(key)
            is_empty = value is None or value == "" or value == []

            if is_empty:
                flabel = field.get("label_de", field.get("label", key))
                vis = field.get("visible_when")
                # Only flag visible_when fields if condition is met
                if vis:
                    cond_field = vis.get("field", "")
                    cond_vals = vis.get("values", [])
                    actual = char_data.get(cond_field, "")
                    if actual not in cond_vals:
                        continue
                missing.append(f"{key} ({flabel})")

    # Note: popularity, trustworthiness, social_dialog_probability are already
    # covered by the template iteration above (llm_generable + store=config).

    # Check outfits
    if not char_data.get("outfits"):
        missing.append("outfits (Outfit-Liste)")

    return missing


def _extract_location_json(text: str) -> Dict[str, Any] | None:
    """Extracts a location JSON from ```json:location ... ``` code blocks."""
    return _extract_json_block(text, "location")


def _extract_character_json(text: str) -> Dict[str, Any] | None:
    """Extracts a character JSON from ```json:character ... ``` code blocks."""
    return _extract_json_block(text, "character")


def _extract_map_json(text: str) -> Dict[str, Any] | None:
    """```json:map ... ``` — a whole map layout (terrain, heights, placements).

    Expects: {summary, bounds?, terrain_areas[], height_areas[], locations[]}
    """
    return _extract_json_block(text, "map")


def _extract_layout_json(text: str) -> Dict[str, Any] | None:
    """```json:layout ... ``` — one location's whole floor plan.

    Expects: {summary, entry_room, rooms[], boundary_openings[]}
    """
    return _extract_json_block(text, "layout")


# Sub-Block-Extraktoren fuer granulare Updates (LLM muss nicht das gesamte
# Character-JSON neu generieren wenn nur ein Outfit / eine Soul-Section /
# einzelne Profil-Felder geaendert werden sollen).

def _extract_outfit_json(text: str) -> Dict[str, Any] | None:
    """```json:outfit ... ``` — einzelnes Outfit anhaengen/aktualisieren.

    Erwartet: {"character_name": "...", "outfit": {name, pieces, ...}}
    """
    return _extract_json_block(text, "outfit")


def _extract_soul_json(text: str) -> Dict[str, Any] | None:
    """```json:soul ... ``` — eine Soul-MD-Section ueberschreiben.

    Erwartet: {"character_name": "...", "section": "personality|tasks|...", "content": "..."}
    """
    return _extract_json_block(text, "soul")


def _extract_profile_patch_json(text: str) -> Dict[str, Any] | None:
    """```json:profile-patch ... ``` — Subset von Profil-Feldern updaten.

    Erwartet: {"character_name": "...", "fields": {"current_feeling": "...", ...}}
    """
    return _extract_json_block(text, "profile-patch")


@router.get("/schemas")
def get_available_schemas() -> Dict[str, Any]:
    """Lists available schema types for world development."""
    schemas = []
    if _get_schemas_dir().exists():
        for f in sorted(_get_schemas_dir().glob("*.md")):
            schemas.append({
                "name": f.stem,
                "label": f.stem.replace("_", " ").title(),
            })
    return {"schemas": schemas}


@router.post("/chat")
async def world_dev_chat(request: Request):
    """Chat with LLM for world development. Streams response."""
    data = await request.json()
    model = data.get("model", "")
    provider = data.get("provider", "")
    session_id = data.get("session_id", "")
    message = data.get("message", "").strip()
    schema = data.get("schema", "location")
    character_template = data.get("character_template", "")
    user_id = data.get("user_id", "")
    edit_location_id = data.get("edit_location_id", "")
    # `map` schema only: "new" starts from an empty sheet, "edit" hands the
    # model the map as it stands (decision D5 — without it the iteration
    # breaks off after the first apply).
    map_mode = (data.get("mode") or "new").strip().lower()
    context_location_ids = data.get("context_location_ids", [])
    context_character_names = data.get("context_character_names", [])
    # Completion budget from the UI field next to the model picker.
    # EMPTY = default: the model's LLM-ROUTING entry max_tokens when one is
    # configured (the per-model place to tune this), else 32768.
    # EXPLICIT 0 = send NO max_tokens at all (provider default) — required
    # for vLLM, which REJECTS prompt+max_tokens > context instead of
    # clamping. CAUTION: Together applies a TINY default when none is sent
    # (observed finish_reason='length' after ~30 tokens) — for Together
    # models set a value here or in LLM Routing.
    def _routing_max_tokens(prov: str, mdl: str):
        try:
            from app.core import config as _cfg
            for entry in (_cfg.get("llm_routing", []) or []):
                if not isinstance(entry, dict) or entry.get("enabled") is False:
                    continue
                if ((entry.get("provider") or "").strip() == prov
                        and (entry.get("model") or "").strip() == mdl):
                    mt = entry.get("max_tokens")
                    if mt not in ("", None, 0):
                        return int(mt)
        except Exception:
            pass
        return None

    _raw_mt = data.get("max_tokens", None)
    _mt_source = "field"
    if _raw_mt in (None, ""):
        max_tokens = _routing_max_tokens(provider, model)
        _mt_source = "routing" if max_tokens else "default"
        if not max_tokens:
            max_tokens = 32768
    else:
        try:
            _v = int(_raw_mt)
        except (TypeError, ValueError):
            _v = 32768
        max_tokens = None if _v <= 0 else _v
        if max_tokens is None:
            _mt_source = "none (explicit 0)"
    logger.info("WorldDev LLM: %s/%s max_tokens=%s (source: %s)",
                provider or "?", model, max_tokens, _mt_source)

    if not model:
        raise HTTPException(status_code=400, detail="model erforderlich")
    if not message:
        raise HTTPException(status_code=400, detail="message erforderlich")

    # New or existing session
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
    else:
        session_id = f"wd-{uuid.uuid4().hex[:8]}"
        # Build system prompt from schema. Nur die in der GUI ausgewaehlten
        # Orte/Characters wandern in den Prompt — vollstaendige Listen wuerden
        # den Prompt unnoetig aufblaehen.
        try:
            existing_locations = _format_context_locations(context_location_ids) \
                or "Keine Orte ausgewaehlt — der Benutzer hat keine als Kontext markiert."
            existing_characters = _format_context_characters(context_character_names) \
                or "Keine Characters ausgewaehlt — der Benutzer hat keine als Kontext markiert."
            generable_fields = _format_generable_fields_for_templates(character_template) if schema == "character" else ""
            if character_template:
                selected_template_text = f"Der Benutzer hat das Template **`{character_template}`** gewaehlt. Verwende GENAU dieses Template und setze `\"template\": \"{character_template}\"` im JSON."
            else:
                selected_template_text = (
                    "Verfuegbare Templates:\n"
                    "- **human-default**: Standard-Mensch (einfach, ohne Roleplay-Regeln)\n"
                    "- **human-roleplay**: Mensch mit Roleplay-Regeln und detaillierten Koerpermerkmalen\n"
                    "- **animal-default**: Tier-Character (Hund, Katze, Fuchs, etc.)\n\n"
                    "Frage den Benutzer oder waehle basierend auf dem Kontext."
                )
            existing_outfit_types = _format_existing_outfit_types()
            # World setup block — prefixed before the schema's role text so
            # the LLM sees the world's tone / era / premise before any
            # task-specific instructions. Empty when the user hasn't set
            # one yet (the placeholder collapses to nothing).
            from app.models.world_setup import get_world_setup_text
            _ws_text = get_world_setup_text()
            world_setup_block = (
                f"## World setup\n\nThe world this content goes into:\n\n{_ws_text}\n\n"
                if _ws_text else ""
            )
            # The map schema's four placeholders. Computed ONLY for `map` —
            # every one of them costs DB reads (catalog, locations, painted
            # areas), and no other schema contains the placeholder to fill.
            if schema == "map":
                terrain_kinds = _format_terrain_kinds()
                placeable_locations = _format_placeable_locations(
                    context_location_ids or None)
                world_bounds_text = _format_world_bounds()
                existing_map = (_format_existing_map() if map_mode == "edit"
                                else "The map is empty — you are drawing it "
                                     "from scratch.")
            else:
                terrain_kinds = placeable_locations = ""
                world_bounds_text = existing_map = ""
            # The layout schema's three placeholders — same rule as the map's:
            # computed ONLY for `layout`, because each one costs DB/disk reads
            # and no other schema carries the placeholder to fill.
            if schema == "layout":
                _target = _layout_target(edit_location_id)
                layout_location = _format_layout_location(_target)
                layout_rooms = _format_layout_rooms(_target)
                surface_kinds = _format_surface_kinds()
            else:
                layout_location = layout_rooms = surface_kinds = ""
            system_prompt = _load_schema(
                schema,
                existing_locations=existing_locations,
                existing_characters=existing_characters,
                existing_outfit_types=existing_outfit_types,
                generable_fields=generable_fields,
                selected_template=selected_template_text,
                terrain_kinds=terrain_kinds,
                placeable_locations=placeable_locations,
                world_bounds=world_bounds_text,
                existing_map=existing_map,
                layout_location=layout_location,
                layout_rooms=layout_rooms,
                surface_kinds=surface_kinds,
                world_setup_block=world_setup_block)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

        # (Selected-Context wird oben direkt in {existing_locations} /
        # {existing_characters} eingespielt — kein zusaetzlicher Append noetig.)

        # If editing an existing element, inject its data into system prompt
        edit_context = ""
        if edit_location_id:
            if schema == "character":
                # edit_location_id is reused as character name for characters
                profile = get_character_profile(edit_location_id)
                if profile and profile.get("character_name"):
                    # Use template from existing profile if not explicitly set
                    existing_template = profile.get("template", "")
                    if existing_template and not character_template:
                        character_template = existing_template
                        # Rebuild generable fields + template text for correct template
                        generable_fields = _format_generable_fields_for_templates(character_template)
                        selected_template_text = f"Der Benutzer hat das Template **`{character_template}`** gewaehlt. Verwende GENAU dieses Template und setze `\"template\": \"{character_template}\"` im JSON."
                        system_prompt = _load_schema(
                            schema,
                            existing_locations=existing_locations,
                            existing_characters=existing_characters,
                            existing_outfit_types=existing_outfit_types,
                            generable_fields=generable_fields,
                            selected_template=selected_template_text)

                    # Also inject config fields into edit data
                    edit_config = get_character_config(edit_location_id)
                    config_inject = {}
                    for ck in ("popularity", "trustworthiness", "social_dialog_probability",
                               "allowed_locations"):
                        if ck in edit_config:
                            config_inject[ck] = edit_config[ck]

                    # Strip internal fields
                    skip_keys = {"created_by", "profile_image", "images",
                                 "current_location", "current_activity", "current_room",
                                 "current_feeling", "current_outfit", "location_changed_at"}
                    edit_data = {k: v for k, v in profile.items() if k not in skip_keys}
                    edit_data.update(config_inject)
                    edit_context = (
                        "\n\n## Aktuell zu bearbeitender Character\n\n"
                        "Der Benutzer moechte folgenden bestehenden Character bearbeiten. "
                        "Zeige ihm zuerst eine Zusammenfassung und frage, was er aendern moechte. "
                        "Wenn du das finale JSON ausgibst, MUSS der Name exakt gleich bleiben "
                        "(damit das System den Character aktualisiert statt einen neuen zu erstellen).\n\n"
                        f"```json\n{json.dumps(edit_data, ensure_ascii=False, indent=2)}\n```"
                    )
                    system_prompt += edit_context
            elif schema == "layout":
                # The layout schema already got this location through its own
                # placeholders, in the shape a floor plan needs (outline,
                # metres, current room plans). Dumping the whole location JSON
                # on top would repeat it and drown it in image prompts.
                pass
            else:
                loc = get_location_by_id(edit_location_id)
                if loc:
                    # Strip fields not relevant for editing
                    edit_data = {k: v for k, v in loc.items()
                                 if k not in ("id", "background_images", "grid_x", "grid_y")}
                    edit_context = (
                        "\n\n## Aktuell zu bearbeitender Ort\n\n"
                        "Der Benutzer moechte folgenden bestehenden Ort bearbeiten. "
                        "Zeige ihm zuerst eine Zusammenfassung und frage, was er aendern moechte. "
                        "Wenn du das finale JSON ausgibst, MUSS der Name exakt gleich bleiben "
                        "(damit das System den Ort aktualisiert statt einen neuen zu erstellen).\n\n"
                        f"```json\n{json.dumps(edit_data, ensure_ascii=False, indent=2)}\n```"
                    )
                    system_prompt += edit_context

        session = {
            "model": model,
            "provider": provider,
            "schema": schema,
            "system_prompt": system_prompt,
            "messages": [],
            "user_id": user_id,
            "edit_location_id": edit_location_id,
            "selected_template": character_template,
            "cost_total": 0.0,
            "tokens_total_in": 0,
            "tokens_total_out": 0,
        }
        _sessions[session_id] = session

    # Completion budget INCLUDES the hidden reasoning tokens of thinking
    # models (GLM, DeepSeek-R1, …). None = no max_tokens sent (provider
    # default; vLLM-safe). Set per request via the UI field next to the
    # model picker.
    llm, llm_instance = _create_llm(model, provider, max_tokens=max_tokens)
    if not llm:
        raise HTTPException(status_code=500, detail=f"Kein Provider fuer Model '{model}' gefunden")

    agent = StreamingAgent(
        llm=llm,
        tool_format="tag",
        tools_dict={},
        agent_name="WorldDev",
        max_iterations=1,
        log_task="world_dev_chat")

    history = list(session["messages"])

    # Resolve pricing for cost tracking
    _pricing = {"input": 0.0, "output": 0.0}
    try:
        import asyncio as _asyncio
        from app.core.provider_manager import get_provider_manager
        _pm = get_provider_manager()
        _prov_obj = _pm.get_provider(provider) if provider else _pm.find_provider_for_model(model)
        if _prov_obj:
            # list_models() macht ggf. einen sync HTTP-Call (Cache-Miss) →
            # Threadpool, damit der Event-Loop nicht 10s blockiert.
            _models = await _asyncio.to_thread(_prov_obj.list_models)
            for _m in _models:
                if _m["name"] == model:
                    _pricing = _m.get("pricing", _pricing)
                    break
    except Exception:
        pass

    def _track_cost(input_text: str, output_text: str):
        """Estimate tokens and accumulate session cost. Pricing is per 1M tokens."""
        from app.utils.llm_logger import estimate_tokens
        tok_in = estimate_tokens(input_text)
        tok_out = estimate_tokens(output_text)
        cost = (tok_in * _pricing["input"] / 1_000_000) + (tok_out * _pricing["output"] / 1_000_000)
        session["tokens_total_in"] = session.get("tokens_total_in", 0) + tok_in
        session["tokens_total_out"] = session.get("tokens_total_out", 0) + tok_out
        session["cost_total"] = session.get("cost_total", 0.0) + cost

    async def generate():
        from app.core.llm_queue import get_llm_queue
        _llm_queue = get_llm_queue()
        _task_id = await _llm_queue.register_chat_active_async(
            "WorldDev", llm_instance=llm_instance,
            task_type="world_dev", label="World Dev Chat")
        full_response = ""
        try:
            # Send session_id in first chunk
            yield f"data: {json.dumps({'session_id': session_id})}\n\n"

            async for event in agent.stream(session["system_prompt"], history, message):
                if isinstance(event, ContentEvent):
                    full_response += event.content
                    yield f"data: {json.dumps({'content': event.content})}\n\n"

            # Update session
            session["messages"].append({"role": "user", "content": message})
            session["messages"].append({"role": "assistant", "content": full_response})

            # Track cost (system prompt + history + user input → output)
            all_input = session["system_prompt"] + " ".join(
                m["content"] for m in history) + message
            _track_cost(all_input, full_response)

            # Check if response contains extractable JSON. When the model was
            # cut off mid-block last turn and the user asked it to continue,
            # the fence spans TWO assistant messages — retry the extraction on
            # the previous assistant message joined with this one.
            _prev_assist = next((m.get("content", "") for m in
                                 reversed(session["messages"][:-1])
                                 if m.get("role") == "assistant"), "")

            def _extract2(extractor):
                d = extractor(full_response)
                if not d and _prev_assist:
                    d = extractor(_prev_assist + "\n" + full_response)
                return d

            location_data = _extract2(_extract_location_json)
            if location_data:
                yield f"data: {json.dumps({'location_data': location_data})}\n\n"

            # Granulare Sub-Block-Updates (Outfit / Soul-Section / Profil-Patch).
            outfit_data = _extract2(_extract_outfit_json)
            if outfit_data:
                yield f"data: {json.dumps({'outfit_data': outfit_data})}\n\n"
            soul_data = _extract2(_extract_soul_json)
            if soul_data:
                yield f"data: {json.dumps({'soul_data': soul_data})}\n\n"
            profile_patch_data = _extract2(_extract_profile_patch_json)
            if profile_patch_data:
                yield f"data: {json.dumps({'profile_patch_data': profile_patch_data})}\n\n"

            # A whole map layout. It travels RAW — the frontend runs it through
            # /world-dev/preview-map, which is the ONE normalizer, so the
            # preview and the apply can never disagree about what was drawn.
            map_data = _extract2(_extract_map_json)
            if map_data:
                yield f"data: {json.dumps({'map_data': map_data})}\n\n"

            # One location's floor plan. Travels RAW for the same reason the
            # map draft does — the frontend runs it through
            # /world-dev/preview-layout, which is the ONE normalizer, so the
            # drawn preview and the apply can never disagree.
            layout_data = _extract2(_extract_layout_json)
            if layout_data:
                yield f"data: {json.dumps({'layout_data': layout_data})}\n\n"

            character_data = _extract2(_extract_character_json)
            if character_data:
                # Validate fields — auto-request missing ones
                selected_tmpl = session.get("selected_template", "") or character_data.get("template", "")
                missing = _validate_character_fields(character_data, selected_tmpl)

                if missing:
                    # Ask LLM to complete missing fields
                    missing_list = "\n".join(f"- {f}" for f in missing)
                    completion_msg = (
                        f"Im JSON fehlen noch folgende Felder:\n{missing_list}\n\n"
                        "Bitte ergaenze ALLE fehlenden Felder und gib das KOMPLETTE JSON nochmal aus "
                        "(mit ```json:character markiert). Fuer Select-Felder waehle passende Werte. "
                        "Fuer Zahlen-Felder (0-100) waehle zum Character passende Werte."
                    )
                    yield f"data: {json.dumps({'content': '\n\n---\n\n*Prüfe fehlende Felder...*\n\n'})}\n\n"

                    # Add to history and request completion
                    session["messages"].append({"role": "user", "content": completion_msg})
                    completion_history = list(session["messages"])

                    completion_response = ""
                    async for event in agent.stream(session["system_prompt"], completion_history[:-1], completion_msg):
                        if isinstance(event, ContentEvent):
                            completion_response += event.content
                            yield f"data: {json.dumps({'content': event.content})}\n\n"

                    session["messages"].append({"role": "assistant", "content": completion_response})

                    # Track cost for completion turn
                    comp_input = session["system_prompt"] + " ".join(
                        m["content"] for m in completion_history[:-1]) + completion_msg
                    _track_cost(comp_input, completion_response)

                    # Try to extract completed JSON
                    completed_data = _extract_character_json(completion_response)
                    if completed_data:
                        character_data = completed_data
                    else:
                        # Merge: fill gaps from first attempt with second attempt's raw data
                        logger.warning("Completion response had no extractable JSON, using partial data")

                yield f"data: {json.dumps({'character_data': character_data})}\n\n"

            # A json:<type> fence was emitted but NOTHING could be parsed —
            # tell the user WHY there are no Validate/Apply buttons (typically
            # the model stopped mid-JSON) instead of failing silently.
            import re as _re
            _fence_types = _re.findall(r'```json:([\w-]+)', full_response)
            if _fence_types and not any([location_data, outfit_data, soul_data,
                                         profile_patch_data, character_data,
                                         map_data, layout_data]):
                _warn = (f"The json:{_fence_types[0]} block could not be parsed — "
                         f"the output appears to be cut off mid-JSON. Ask the "
                         f"model to output the COMPLETE JSON block again (or to "
                         f"continue exactly where it stopped).")
                logger.warning("WorldDev: %s", _warn)
                yield f"data: {json.dumps({'extraction_warning': _warn})}\n\n"

            # Send session cost info
            yield f"data: {json.dumps({'usage': {'tokens_in': session['tokens_total_in'], 'tokens_out': session['tokens_total_out'], 'cost_total': round(session['cost_total'], 6)}})}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            logger.error("WorldDev chat error: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            _llm_queue.register_chat_done(_task_id)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/apply")
async def apply_world_data(request: Request):
    """Applies generated location/room data to the world."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_world_data_sync, data)


def _apply_world_data_sync(data: Any):
    """The blocking body of ``apply_world_data`` — runs in the threadpool."""
    user_id = data.get("user_id", "")
    location_data = data.get("location_data", {})
    if not location_data or not location_data.get("name"):
        raise HTTPException(status_code=400, detail="location_data mit name erforderlich")

    name = location_data["name"]
    description = location_data.get("description", "")
    rooms = location_data.get("rooms", [])
    image_prompt_day = location_data.get("image_prompt_day")
    image_prompt_night = location_data.get("image_prompt_night")
    # The live 2D map renders from image_prompt_map_2d — the only map prompt
    # the schema generates.
    image_prompt_map_2d = location_data.get("image_prompt_map_2d")

    # Normalize image_prompt fields
    for room in rooms:
        # LLM generates "image_prompt" but system reads "image_prompt_day"/"image_prompt_night"
        if "image_prompt" in room and "image_prompt_day" not in room:
            room["image_prompt_day"] = room.pop("image_prompt")
        if "image_prompt_night" not in room:
            room["image_prompt_night"] = ""

    result = add_location(
        name=name,
        description=description,
        rooms=rooms,
        image_prompt_day=image_prompt_day,
        image_prompt_night=image_prompt_night,
        image_prompt_map_2d=image_prompt_map_2d,
        image_prompt_building=location_data.get("image_prompt_building"),
        decency=location_data.get("decency"),
        style_hint=location_data.get("style_hint"),
        swim_allowed=location_data.get("swim_allowed"),
        indoor=location_data.get("indoor"),
        activity_hint=location_data.get("activity_hint"),
        danger_level=location_data.get("danger_level"))

    logger.info("WorldDev: Location '%s' applied for user %s", name, user_id)
    return {"status": "success", "location": result}


# ---------------------------------------------------------------------------
# Map layout — preview, apply, snapshot, restore (E10 task 1)
# ---------------------------------------------------------------------------

def _map_world_context() -> Tuple[Dict[str, Any], Dict[str, Any], Any, str]:
    """(catalog, locations_by_id, world bounds, default terrain kind).

    The four world facts ``map_layout_apply.sanitize_map_layout`` needs handed
    in — it is a pure function on purpose, so this is the ONE place that reads
    them out of the world.
    """
    from app.core import config
    from app.core.location_model3d import derive_plan_width_m
    from app.core.map_layout_apply import current_world_bounds
    from app.core.terrain_types import effective_catalog
    from app.models.world import list_locations

    locations_by_id: Dict[str, Any] = {}
    for loc in list_locations():
        loc_id = loc.get("id") or ""
        if not loc_id:
            continue
        map3d = loc.get("map3d") or {}
        locations_by_id[loc_id] = {
            "name": loc.get("name") or loc_id,
            # The DRAWN outline (contract v6) — the ONLY shape a location
            # has since 2026-08-19; a place without one has no area and the
            # overlap test simply skips it. ``plan_width_m`` rides along as
            # the derived bounding-box width the prompt quotes, never as a
            # shape of its own.
            "boundary": map3d.get("boundary"),
            "plan_width_m": derive_plan_width_m(loc_id, map3d),
        }
    default_kind = str(config.get("game.default_terrain_kind", "grass")
                       or "grass")
    return (effective_catalog(), locations_by_id, current_world_bounds(),
            default_kind)


def _normalize_map_body(map_data: Any) -> Tuple[Dict[str, Any],
                                                List[Dict[str, str]]]:
    """Run one raw draft through the sanitizer, turning its hard errors into
    a 400. Used by BOTH preview and apply, so the two can never disagree."""
    from app.core.map_layout_apply import sanitize_map_layout
    catalog, locations_by_id, bounds, default_kind = _map_world_context()
    try:
        return sanitize_map_layout(map_data, catalog=catalog,
                                   locations_by_id=locations_by_id,
                                   bounds=bounds, default_kind=default_kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/preview-map")
async def preview_map(request: Request):
    """Normalize a map draft WITHOUT writing anything.

    Body:     {"map_data": {...the json:map block...}}
    Returns:  {"status": "ok",
               "normalized": {summary, bounds, terrain_areas[], height_areas[],
                              locations[]},
               "warnings": [{code, ref, message}, ...],
               "counts": {areas, heights, positions}}

    The normalized layout is exactly what an apply would write (plus `name` /
    `plan_width_m` / `why` on each placement, so the draft can be drawn
    without a second round trip) — the preview map and the applied map are
    the same geometry by construction.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_preview_map_sync, data)


def _preview_map_sync(data: Any):
    """The blocking body of ``preview_map`` — runs in the threadpool."""
    from app.core.map_layout_apply import layout_counts
    normalized, warnings = _normalize_map_body(data.get("map_data"))
    return {"status": "ok", "normalized": normalized, "warnings": warnings,
            "counts": layout_counts(normalized)}


@router.post("/apply-map")
async def apply_map(request: Request):
    """Write a map draft to the world.

    Body:     {"map_data": {...}, "mode": "merge"|"replace_terrain",
               "snapshot": true}
    Returns:  {"status": "success",
               "applied": {areas, heights, positions, created},
               "warnings": [{code, ref, message}, ...],
               "snapshot_id": "<id>"|null}

    ``mode`` ``merge`` paints on top of what is there; ``replace_terrain``
    deletes every painted area and height area first (placements are never
    wiped — only the locations the layout names are moved). ``created`` counts
    the NEW places the draft proposed as stubs.

    ``snapshot`` (default true) freezes the whole painted world first, so
    ``/world-dev/map-restore`` can undo the apply. That is the undo the map
    editor itself does not have.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_map_sync, data)


def _apply_map_sync(data: Any):
    """The blocking body of ``apply_map`` — runs in the threadpool."""
    from app.core.map_layout_apply import (apply_map_layout, map_snapshot)
    mode = (data.get("mode") or "merge").strip()
    if mode not in ("merge", "replace_terrain"):
        raise HTTPException(status_code=400,
                            detail=f"unknown mode '{mode}' "
                                   f"(merge | replace_terrain)")
    normalized, warnings = _normalize_map_body(data.get("map_data"))

    snapshot_id = None
    if data.get("snapshot", True):
        try:
            snapshot_id = map_snapshot()
        except OSError as e:
            # A cache directory we cannot write is not a reason to refuse the
            # apply — but the user must know the undo is missing.
            logger.warning("Map snapshot failed: %s", e)
            warnings = warnings + [{
                "code": "snapshot_failed", "ref": "",
                "message": f"Could not write the undo snapshot: {e}"}]
    try:
        # The snapshot rides along so the apply can note the places it CREATES
        # in it — that is the only way the restore below can take them back.
        applied = apply_map_layout(normalized, mode=mode,
                                   snapshot_id=snapshot_id or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("WorldDev: map layout applied (%s) %s", mode, applied)
    return {"status": "success", "applied": applied, "warnings": warnings,
            "snapshot_id": snapshot_id}


@router.get("/map-snapshots")
def get_map_snapshots():
    """The stored map snapshots, newest first:
    ``[{id, created_at, counts: {areas, heights, positions}}]``."""
    from app.core.map_layout_apply import list_snapshots
    return list_snapshots()


@router.post("/map-restore")
async def restore_map_snapshot(request: Request):
    """Put a snapshot back — the undo for an apply.

    Body:     {"snapshot_id": "<id>"}
    Returns:  {"status": "success",
               "restored": {areas, heights, positions, removed}}

    ``removed`` counts the places the apply after this snapshot CREATED and the
    restore deleted again — a place made by hand afterwards is never touched.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_restore_map_snapshot_sync, data)


def _restore_map_snapshot_sync(data: Any):
    """The blocking body of ``restore_map_snapshot`` — runs in the
    threadpool."""
    from app.core.map_layout_apply import restore_snapshot
    snapshot_id = (data.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id required")
    try:
        restored = restore_snapshot(snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "restored": restored}


# ---------------------------------------------------------------------------
# Room layouts — preview, apply, snapshot, restore
# ("Prop-Welt statt Dioramen", stage 3)
# ---------------------------------------------------------------------------

def _layout_world_context(location_id: str) -> Tuple[Dict[str, Any],
                                                     List[str]]:
    """(location dict, surface-library kinds) for one layout draft.

    ``layout_apply.sanitize_layout`` is a pure function on purpose, so this is
    the ONE place that reads its two world facts out of the world.
    """
    from app.core.surface_textures import library_kinds
    loc = _layout_target(location_id)
    if not loc:
        raise HTTPException(status_code=404,
                            detail=f"no such location: {location_id!r}")
    return loc, sorted(library_kinds())


def _normalize_layout_body(layout_data: Any, location_id: str
                           ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Run one raw draft through the sanitizer, turning its hard errors into a
    400. Used by BOTH preview and apply, so the two can never disagree."""
    from app.core.layout_apply import sanitize_layout
    loc, kinds = _layout_world_context(location_id)
    try:
        return sanitize_layout(layout_data, location=loc, surface_kinds=kinds)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/preview-layout")
async def preview_layout(request: Request):
    """Normalize a floor-plan draft WITHOUT writing anything.

    Body:     {"layout_data": {...the json:layout block...},
               "location_id": "<id>"}
    Returns:  {"status": "ok",
               "normalized": {summary, location_id, location_name, boundary,
                              entry_room, rooms[], boundary_openings},
               "warnings": [{code, ref, message}, ...],
               "counts": {rooms, new_rooms, openings, boundary_openings}}

    The normalized plan is exactly what an apply would write, so the drawn
    preview and the applied floor plan are the same geometry by construction.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_preview_layout_sync, data)


def _preview_layout_sync(data: Any):
    """The blocking body of ``preview_layout`` — runs in the threadpool."""
    from app.core.layout_apply import layout_counts
    normalized, warnings = _normalize_layout_body(
        data.get("layout_data"), str(data.get("location_id") or ""))
    return {"status": "ok", "normalized": normalized, "warnings": warnings,
            "counts": layout_counts(normalized)}


@router.post("/apply-layout")
async def apply_layout_route(request: Request):
    """Write a floor-plan draft to its location.

    Body:     {"layout_data": {...}, "location_id": "<id>", "snapshot": true}
    Returns:  {"status": "success",
               "applied": {location_id, updated[], created[], entry_room,
                           boundary_openings},
               "warnings": [{code, ref, message}, ...],
               "snapshot_id": "<id>"|null}

    ``snapshot`` (default true) freezes the location's whole plan first, so
    ``/world-dev/layout-restore`` can undo the apply — the undo the floor-plan
    editor itself does not have.

    A warning never blocks the write: a room over the plot edge or two rooms
    sharing floor are authoring states the ``problems[]`` system reports on the
    finished world; only junk was dropped, in the sanitizer, before this point.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_layout_route_sync, data)


def _apply_layout_route_sync(data: Any):
    """The blocking body of ``apply_layout_route`` — runs in the threadpool."""
    from app.core.layout_apply import apply_layout, layout_snapshot
    location_id = str(data.get("location_id") or "").strip()
    normalized, warnings = _normalize_layout_body(data.get("layout_data"),
                                                  location_id)

    snapshot_id = None
    if data.get("snapshot", True):
        try:
            snapshot_id = layout_snapshot(normalized["location_id"])
        except OSError as e:
            # A cache directory we cannot write is not a reason to refuse the
            # apply — but the user must know the undo is missing.
            logger.warning("Layout snapshot failed: %s", e)
            warnings = warnings + [{
                "code": "snapshot_failed", "ref": "",
                "message": f"Could not write the undo snapshot: {e}"}]
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    try:
        applied = apply_layout(normalized)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("WorldDev: layout applied %s", applied)
    return {"status": "success", "applied": applied, "warnings": warnings,
            "snapshot_id": snapshot_id}


@router.get("/layout-snapshots")
def get_layout_snapshots(location_id: str = ""):
    """The stored floor-plan snapshots, newest first:
    ``[{id, created_at, location_id, location_name, rooms}]``.
    ``location_id`` filters to one location; empty lists all."""
    from app.core.layout_apply import list_layout_snapshots
    return list_layout_snapshots(location_id)


@router.post("/layout-restore")
async def restore_layout(request: Request):
    """Put a floor-plan snapshot back — the undo for an apply.

    Body:     {"snapshot_id": "<id>"}
    Returns:  {"status": "success",
               "restored": {location_id, rooms, entry_room}}
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_restore_layout_sync, data)


def _restore_layout_sync(data: Any):
    """The blocking body of ``restore_layout`` — runs in the threadpool."""
    from app.core.layout_apply import restore_layout_snapshot
    snapshot_id = (data.get("snapshot_id") or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id required")
    try:
        restored = restore_layout_snapshot(snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "restored": restored}


def _get_generable_fields(template_name: str) -> tuple[set, set]:
    """Returns (profile_fields, config_fields) that the LLM may set for a template.

    Reads the merged template and collects all field keys with llm_generable=True.
    Fields with store="config" go to config_fields, the rest to profile_fields.
    'character_name' and 'template' are always profile fields.
    """
    from app.models.character_template import get_template

    profile_fields = {"character_name", "template"}
    config_fields: set[str] = set()

    tmpl = get_template(template_name)
    if not tmpl:
        # Fallback: allow basic fields
        profile_fields.update({"language", "gender", "age",
                               "character_personality", "character_appearance"})
        return profile_fields, config_fields

    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            if not field.get("llm_generable"):
                continue
            key = field.get("key", "")
            if not key:
                continue
            if field.get("store") == "config":
                config_fields.add(key)
            else:
                profile_fields.add(key)

    return profile_fields, config_fields


def _apply_character_internal(char_data: Dict[str, Any],
                              selected_template: str = "",
                              created_by: str = "") -> Dict[str, Any]:
    """Apply character JSON in-process (profile + soul MD + outfits + config).

    Used by both /apply-character (HTTP) and /apply-json (smart import). Caller
    is responsible for handing in a *normalized* dict — flat fields, no nested
    soul object. Sub-sections without a template source_file mapping (e.g.
    soul/soul.md, soul/tasks.md) can be passed via the special key
    ``_extra_soul_md`` as ``{"<section>": "<full markdown>"}``.
    """
    char_name = char_data["character_name"]
    template = char_data.get("template") or selected_template or "human-default"
    char_data["template"] = template

    # Detect whether this is a new character — if so, save_character_profile
    # needs create_new=True to bypass the "Geister-Character"-Guard. Without
    # this, the very first save silently returns and we end up with a row
    # that only has config_json filled (created later by save_character_config
    # / add_character_outfit), but profile_json stays {} and template "".
    from app.core.db import get_connection as _get_conn
    _is_new = True
    try:
        _conn = _get_conn()
        _row = _conn.execute(
            "SELECT 1 FROM characters WHERE name=? LIMIT 1", (char_name,)
        ).fetchone()
        _is_new = not bool(_row)
    except Exception:
        pass

    profile_fields, config_fields = _get_generable_fields(template)

    from app.models.character_template import get_template
    from app.models.character import get_character_dir

    # SERIALIZED PER CHARACTER (``character_profile``): from the read to the
    # save this is one read-modify-write of the whole profile. The apply runs
    # in the threadpool like every other route body, so a concurrent writer of
    # the same character (a profile patch, an equip) would otherwise be
    # overwritten with the pre-state this call read.
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("character_profile", char_name):
        profile = get_character_profile(char_name)
        if not profile.get("character_name"):
            profile["character_name"] = char_name
            profile["template"] = template
            profile["created_by"] = created_by or "world_dev"

        tmpl = get_template(template)
        soul_field_map: Dict[str, str] = {}
        if tmpl:
            for section in tmpl.get("sections", []):
                for field in section.get("fields", []):
                    fk = field.get("key", "")
                    sf = field.get("source_file", "")
                    if fk and sf:
                        soul_field_map[fk] = sf

        for key in profile_fields:
            if key in soul_field_map:
                continue
            if key in char_data:
                profile[key] = char_data[key]

        if tmpl:
            for section in tmpl.get("sections", []):
                for field in section.get("fields", []):
                    key = field.get("key", "")
                    default = field.get("default")
                    if not key or default is None:
                        continue
                    if key in soul_field_map:
                        continue
                    if key not in profile:
                        profile[key] = default
                    elif key == "roleplay_instructions" and isinstance(default, str) and default:
                        current = str(profile[key])
                        if default not in current:
                            profile[key] = default + "\n\n" + current

        for k in list(profile.keys()):
            if k in soul_field_map:
                profile.pop(k, None)

        save_character_profile(char_name, profile, create_new=_is_new)

    if soul_field_map:
        char_dir = get_character_dir(char_name, create=True)
        for fk, rel_path in soul_field_map.items():
            content = char_data.get(fk)
            if content is None or not str(content).strip():
                continue
            md_path = char_dir / rel_path
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(str(content).rstrip() + "\n", encoding="utf-8")

    # Extra soul MDs (sections without template source_file mapping —
    # Smart-Import rendert dort z.B. nested ``"# Soul"``/``"# Tasks"`` rein).
    extra_md = char_data.get("_extra_soul_md") or {}
    if isinstance(extra_md, dict) and extra_md:
        from app.core.soul_sections import SECTION_FILE_MAP
        char_dir = get_character_dir(char_name, create=True)
        for section_key, content in extra_md.items():
            rel = SECTION_FILE_MAP.get(section_key)
            if not rel or not str(content or "").strip():
                continue
            md_path = char_dir / rel
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text(str(content).rstrip() + "\n", encoding="utf-8")

    config = get_character_config(char_name)
    config_changed = False
    for key in config_fields:
        if key in char_data:
            config[key] = str(char_data[key])
            config_changed = True

    # allowed_locations abgeschafft — wird ignoriert wenn der LLM es trotzdem
    # im JSON schickt (Backwards-Compat, keine Warnung).
    char_data.pop("allowed_locations", None)

    # known_locations bei Neu-Erstellung explizit als leere Liste setzen.
    # Ohne das Feld greift im SetLocation-Skill der Legacy-Bypass und der
    # Char darf zu beliebigen Orten teleportieren — frische World-Dev-Chars
    # sollen nirgends hin koennen, bis sie platziert oder gefuehrt werden.
    if _is_new and "known_locations" not in config:
        config["known_locations"] = []
        config_changed = True

    if config_changed:
        save_character_config(char_name, config)

    outfits_applied = []
    for outfit in char_data.get("outfits", []):
        outfits_applied.append(_apply_one_outfit(char_name, outfit))

    logger.info("WorldDev: Character '%s' (template=%s) applied", char_name, template)
    return {"status": "success", "character": char_name, "template": template,
            "outfits": outfits_applied}


@router.post("/apply-character")
async def apply_character_data(request: Request):
    """Applies generated character data (profile + outfits)."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_character_data_sync, data)


def _apply_character_data_sync(data: Any):
    """The blocking body of ``apply_character_data`` — runs in the
    threadpool."""
    user_id = data.get("user_id", "")
    char_data = data.get("character_data", {})
    if not char_data or not char_data.get("character_name"):
        raise HTTPException(status_code=400, detail="character_data mit character_name erforderlich")
    selected_template = data.get("selected_template", "")
    return _apply_character_internal(char_data, selected_template, created_by=user_id)


# ---------------------------------------------------------------------------
# Granulare Apply-Routes — kleinere Updates ohne komplettes Character-JSON
# ---------------------------------------------------------------------------

def _apply_one_outfit(char_name: str, outfit: Dict[str, Any]) -> Dict[str, Any]:
    """Legt EIN Outfit an (Pieces-Format mit Dedupe oder Freitext-Fallback).

    Returns: {name, pieces_created, pieces_reused}
    """
    if not outfit.get("name"):
        return {"name": "", "pieces_created": 0, "pieces_reused": 0}
    raw_pieces = outfit.get("pieces") or []
    if raw_pieces and isinstance(raw_pieces[0], dict):
        from app.models.inventory import (
            add_item, add_to_inventory, find_inventory_piece_by_name_slot,
            VALID_PIECE_SLOTS)
        piece_ids: List[str] = []
        created = reused = 0
        for p in raw_pieces:
            # Schema: {slots: [...], name, prompt_fragment, outfit_types, covers, partially_covers}.
            # Falls der Caller noch den alten "slot"+"additional_slots"-Stil schickt, werten wir
            # das nicht aus — das schlaegt in add_item() mit "needs non-empty 'slots' list" fehl.
            slots = [str(s or "").strip().lower() for s in (p.get("slots") or []) if s]
            slots = [s for s in slots if s in VALID_PIECE_SLOTS]
            name = (p.get("name") or "").strip()
            fragment = (p.get("prompt_fragment") or "").strip()
            if not slots or not name:
                logger.warning("WorldDev outfit '%s': Piece skipped (slots=%r, name=%r)",
                               outfit.get("name"), slots, name)
                continue
            existing = find_inventory_piece_by_name_slot(
                char_name, name, slots[0], prompt_fragment=fragment)
            if existing:
                piece_ids.append(existing)
                reused += 1
                continue
            item = add_item(
                name=name,
                description=(p.get("description") or "").strip(),
                category="outfit_piece",
                image_prompt="",
                prompt_fragment=fragment,
                outfit_piece={
                    "slots": slots,
                    "covers": p.get("covers") or [],
                    "partially_covers": p.get("partially_covers") or [],
                })
            iid = item.get("id")
            if not iid:
                logger.warning("WorldDev outfit '%s': add_item failed for '%s'",
                               outfit.get("name"), name)
                continue
            add_to_inventory(character_name=char_name, item_id=iid,
                obtained_method="generated", obtained_from="world_dev")
            piece_ids.append(iid)
            created += 1
        frags = [(p.get("prompt_fragment") or "").strip()
                 for p in raw_pieces if isinstance(p, dict)]
        outfit_text = "wearing: " + ", ".join(f for f in frags if f) if any(frags) else ""
        add_character_outfit(char_name, {
            "name": outfit["name"],
            "outfit": outfit_text,
            "pieces": piece_ids,
            "locations": outfit.get("locations") or [],
            "activities": outfit.get("activities") or [],
            "excluded_locations": outfit.get("excluded_locations") or [],
        })
        logger.info("WorldDev outfit '%s': %d neu, %d reused", outfit["name"], created, reused)
        return {"name": outfit["name"], "pieces_created": created, "pieces_reused": reused}
    # Alter Pfad: Freitext-Outfit (Backwards-Compat).
    add_character_outfit(char_name, outfit)
    return {"name": outfit["name"], "pieces_created": 0, "pieces_reused": 0}


@router.post("/apply-outfit")
async def apply_outfit_data(request: Request):
    """Granulares Apply: ein einzelnes Outfit anhaengen / aktualisieren.

    Body: {character_name, outfit: {name, pieces, locations?, activities?, excluded_locations?}}
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_outfit_data_sync, data)


def _apply_outfit_data_sync(data: Any):
    """The blocking body of ``apply_outfit_data`` — runs in the threadpool."""
    char_name = (data.get("character_name") or "").strip()
    outfit = data.get("outfit") or {}
    if not char_name:
        raise HTTPException(status_code=400, detail="character_name erforderlich")
    if not outfit.get("name"):
        raise HTTPException(status_code=400, detail="outfit.name erforderlich")
    profile = get_character_profile(char_name)
    if not profile.get("character_name"):
        raise HTTPException(status_code=404, detail=f"Character '{char_name}' nicht gefunden")
    result = _apply_one_outfit(char_name, outfit)
    return {"status": "success", "character": char_name, **result}


@router.post("/apply-soul")
async def apply_soul_data(request: Request):
    """Granulares Apply: eine einzelne Soul-MD-Section ueberschreiben.

    Body: {character_name, section: "personality"|"tasks"|..., content: "..."}
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_soul_data_sync, data)


def _apply_soul_data_sync(data: Any):
    """The blocking body of ``apply_soul_data`` — runs in the threadpool."""
    char_name = (data.get("character_name") or "").strip()
    section = (data.get("section") or "").strip()
    content = data.get("content") or ""
    if not char_name:
        raise HTTPException(status_code=400, detail="character_name erforderlich")
    if not section:
        raise HTTPException(status_code=400, detail="section erforderlich")
    from app.core.soul_sections import SECTION_FILE_MAP
    if section not in SECTION_FILE_MAP:
        raise HTTPException(status_code=400,
            detail=f"Unbekannte section '{section}' (erlaubt: {sorted(SECTION_FILE_MAP.keys())})")
    profile = get_character_profile(char_name)
    if not profile.get("character_name"):
        raise HTTPException(status_code=404, detail=f"Character '{char_name}' nicht gefunden")

    from app.models.character import get_character_dir
    char_dir = get_character_dir(char_name)
    md_path = char_dir / SECTION_FILE_MAP[section]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(str(content).rstrip() + "\n", encoding="utf-8")
    logger.info("WorldDev: Soul '%s/%s' (%d chars) geschrieben",
                char_name, section, len(content))
    return {"status": "success", "character": char_name,
            "section": section, "size": len(content)}


@router.post("/apply-profile-patch")
async def apply_profile_patch_data(request: Request):
    """Granulares Apply: Subset von Profil-Feldern updaten.

    Body: {character_name, fields: {key: value, ...}}
    Soul-Felder (source_file) werden ignoriert — die laufen ueber /apply-soul.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_profile_patch_data_sync, data)


def _apply_profile_patch_data_sync(data: Any):
    """The blocking body of ``apply_profile_patch_data`` — runs in the
    threadpool.

    SERIALIZED PER CHARACTER (``character_profile``): read the profile, patch
    fields, write the whole profile back. In the threadpool that races every
    other profile writer of the same character (equip, decency, a second
    patch) and the later write would drop the earlier change.
    """
    from app.core.keyed_lock import keyed_lock
    char_name = (data.get("character_name") or "").strip()
    fields = data.get("fields") or {}
    if not char_name:
        raise HTTPException(status_code=400, detail="character_name erforderlich")
    if not isinstance(fields, dict) or not fields:
        raise HTTPException(status_code=400, detail="fields (dict) erforderlich")
    with keyed_lock("character_profile", char_name):
        profile = get_character_profile(char_name)
        if not profile.get("character_name"):
            raise HTTPException(status_code=404, detail=f"Character '{char_name}' nicht gefunden")

        # Soul fields are filtered out (they go through /apply-soul).
        template = profile.get("template", "")
        soul_field_keys: set = set()
        if template:
            from app.models.character_template import get_template
            tmpl = get_template(template)
            if tmpl:
                for sec in tmpl.get("sections", []):
                    for fld in sec.get("fields", []):
                        if fld.get("source_file") and fld.get("key"):
                            soul_field_keys.add(fld["key"])
        applied = {}
        for k, v in fields.items():
            if k in soul_field_keys:
                logger.info("WorldDev profile-patch: '%s' skipped (soul field)", k)
                continue
            profile[k] = v
            applied[k] = v
        save_character_profile(char_name, profile)
    logger.info("WorldDev: profile patch for '%s' (%d fields)", char_name, len(applied))
    return {"status": "success", "character": char_name,
            "applied_fields": list(applied.keys())}


@router.post("/cleanup")
async def cleanup_session(request: Request):
    """Removes a world dev session from memory."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_cleanup_session_sync, data)


def _cleanup_session_sync(data: Any):
    """The blocking body of ``cleanup_session`` — runs in the threadpool."""
    session_id = data.get("session_id", "")
    _sessions.pop(session_id, None)
    return {"status": "ok"}


# ── Global Pause / Resume ──

def _get_pause_state() -> Dict[str, bool]:
    """Returns the current pause state of all subsystems.

    Ersetzt llm_queue.paused: statt globaler LLM-Pause nutzen wir das
    Runtime-Preset "world_dev" im llm_task_state (disabled Tasks).
    """
    from app.core.task_queue import get_task_queue
    from app.routes.scheduler import get_scheduler_manager
    from app.core.llm_task_state import runtime_disabled_tasks

    task_queue = get_task_queue()
    scheduler_mgr = get_scheduler_manager()

    queue_paused = task_queue._is_paused("default") if task_queue else False
    llm_paused = bool(runtime_disabled_tasks())
    scheduler_paused = False
    if scheduler_mgr and hasattr(scheduler_mgr, '_global_paused'):
        scheduler_paused = scheduler_mgr._global_paused

    # AgentLoop pause state mirrors task_queue 'default' pause flag, so
    # ``queue_paused`` already covers it.
    all_paused = queue_paused and scheduler_paused and llm_paused
    return {
        "paused": all_paused,
        "queue_paused": queue_paused,
        "llm_paused": llm_paused,
        "scheduler_paused": scheduler_paused,
    }


@router.post("/pause-all")
async def pause_all():
    """Pauses all LLM and background activities (except World Dev Chat).

    Ersetzt llm_queue.pause durch Runtime-Preset "world_dev" (Task-Disable).
    Chat/Story bleiben aktiv — nur Hintergrund-Tasks werden deaktiviert.
    """
    from app.core.task_queue import get_task_queue
    from app.routes.scheduler import get_scheduler_manager
    from app.core.llm_task_state import activate_preset_runtime

    disabled = activate_preset_runtime("world_dev")
    logger.info("LLM-Task-Disable aktiv (world_dev): %d Tasks aus", len(disabled))

    # Note: ThoughtRunner.pause() removed — pausing the task_queue 'default'
    # below also halts the AgentLoop (its pause source).

    task_queue = get_task_queue()
    if task_queue:
        task_queue.pause_queue("default")

    scheduler_mgr = get_scheduler_manager()
    if scheduler_mgr:
        for job in scheduler_mgr.scheduler.get_jobs():
            job.pause()
        scheduler_mgr._global_paused = True
        logger.info("Scheduler pausiert (%d Jobs)", len(scheduler_mgr.scheduler.get_jobs()))

    logger.info("Hintergrund-Aktivitaeten pausiert (World-Dev-Modus)")
    return _get_pause_state()


@router.post("/resume-all")
async def resume_all():
    """Resumes all LLM and background activities."""
    from app.core.task_queue import get_task_queue
    from app.routes.scheduler import get_scheduler_manager
    from app.core.llm_task_state import clear_runtime

    clear_runtime()

    task_queue = get_task_queue()
    if task_queue:
        task_queue.resume_queue("default")

    scheduler_mgr = get_scheduler_manager()
    if scheduler_mgr:
        for job in scheduler_mgr.scheduler.get_jobs():
            job.resume()
        scheduler_mgr._global_paused = False
        logger.info("Scheduler fortgesetzt (%d Jobs)", len(scheduler_mgr.scheduler.get_jobs()))

    logger.info("Hintergrund-Aktivitaeten fortgesetzt")
    return _get_pause_state()


@router.get("/pause-status")
def get_pause_status():
    """Returns the current pause state."""
    return _get_pause_state()


@router.post("/trigger-thought")
async def trigger_thought(character_name: str,
    context_hint: str = "",
    fast: bool = False,
    tool_whitelist: str = "",
    suppress_notification: bool = False):
    """Forciert einen Gedanken-Tick fuer einen bestimmten Character.

    Umgeht Idle-Check, Cooldown, Probability. Nuetzlich zum Debuggen /
    Antreten ohne auf den 60s-Loop zu warten.

    Call: POST /world-dev/trigger-thought?user_id=XYZ&character_name=Kira
    Optional: context_hint, fast, tool_whitelist (kommasepariert), suppress_notification
    """
    from app.core.thoughts import get_thought_runner
    tl = get_thought_runner()
    if not tl:
        raise HTTPException(status_code=503, detail="ThoughtRunner nicht aktiv")

    _whitelist = [t.strip() for t in tool_whitelist.split(",") if t.strip()] or None

    import asyncio
    try:
        await asyncio.wait_for(
            tl.run_thought_turn(character_name,
                                context_hint=context_hint, fast=fast,
                                tool_whitelist=_whitelist,
                                suppress_notification=suppress_notification),
            timeout=300)
        return {"ok": True, "character": character_name, "context_hint": context_hint[:80]}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Thought-Turn Timeout (>300s)")
    except Exception as e:
        logger.error("Thought trigger error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Smart JSON-Import — type detection, soul-flattening, manual apply dialog
# ---------------------------------------------------------------------------

_SOUL_HEADING_TO_FIELD = {
    "personality":    ("character_personality", "section"),
    "presence":       ("character_presence",    "section"),
    "roleplay rules": ("roleplay_instructions", "section"),
    "roleplay_rules": ("roleplay_instructions", "section"),
    "soul":           ("soul",                  "extra"),
    "tasks":          ("tasks",                 "extra"),
    "beliefs":        ("beliefs",               "extra"),
    "lessons":        ("lessons",               "extra"),
    "goals":          ("goals",                 "extra"),
}


def _strip_md_heading(s: str) -> str:
    """'# Personality' / '## Core nature' → 'personality' / 'core nature'."""
    return s.lstrip("#").strip().lower()


def _render_md_section(top_heading: str, sub_dict: Dict[str, Any]) -> str:
    """Renders {'# Personality': {'## Core nature': '...', ...}} → markdown.

    ``sub_dict`` may also be a plain string (no sub-sections) or a dict
    of subheading→body. Headings are written verbatim.
    """
    if isinstance(sub_dict, str):
        return f"{top_heading.strip()}\n\n{sub_dict.strip()}\n"
    if not isinstance(sub_dict, dict):
        return ""
    parts = [top_heading.strip(), ""]
    for sub_h, body in sub_dict.items():
        parts.append(str(sub_h).strip())
        parts.append("")
        parts.append(str(body).strip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _normalize_character_json(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Flattens nested ``soul`` objects + maps unknown templates.

    Returns ``(char_data, warnings)``. ``char_data`` is the flat, ready-to-apply
    dict. Sections that do not have a ``source_file`` template field land in
    ``char_data["_extra_soul_md"]`` and are written to the matching ``soul/*.md``.
    """
    from app.models.character_template import get_template, resolve_template_name

    out = dict(payload)  # shallow copy — caller still owns nested lists
    warnings: List[str] = []

    # Normalize "name" → "character_name"
    if not out.get("character_name") and out.get("name"):
        out["character_name"] = out.pop("name")

    # Validate / map template. resolve_template_name maps common family names
    # (…roleplay…, human/default, animal/pet) to an installed template; an
    # unresolvable name is kept as-is with a corrective warning.
    template = out.get("template", "")
    if template and not get_template(template):
        alias = resolve_template_name(template)
        if alias and alias != template:
            warnings.append(f"Template '{template}' existiert nicht — auf '{alias}' gemappt.")
            out["template"] = alias
        else:
            warnings.append(f"Template '{template}' existiert nicht — bitte korrigieren.")

    # Flatten nested soul object: {"# Personality": {"## Core nature": "..."}}
    soul = out.pop("soul", None)
    extra_md: Dict[str, str] = {}
    if isinstance(soul, dict):
        for raw_heading, body in soul.items():
            key = _strip_md_heading(str(raw_heading))
            mapping = _SOUL_HEADING_TO_FIELD.get(key)
            if not mapping:
                warnings.append(f"Soul-Section '{raw_heading}' unbekannt — uebersprungen.")
                continue
            target, kind = mapping
            md = _render_md_section(str(raw_heading), body)
            if not md.strip():
                continue
            if kind == "section":
                if out.get(target):
                    # Prefer nested (richer) version over flat top-level summary
                    warnings.append(f"Feld '{target}' aus 'soul.{raw_heading}' uebernommen "
                                    f"(top-level Wert wurde ueberschrieben).")
                out[target] = md
            else:
                extra_md[target] = md
    if extra_md:
        out["_extra_soul_md"] = extra_md

    return out, warnings


def _detect_json_type(payload: Dict[str, Any]) -> str:
    """Best-effort type detection from JSON shape. '' if unknown."""
    if not isinstance(payload, dict):
        return ""
    has_char = bool(payload.get("character_name") or payload.get("name"))
    # Granular outfit update: {character_name, outfit: {...}}
    if has_char and isinstance(payload.get("outfit"), dict):
        return "outfit"
    # Soul section update: {character_name, section, content}
    if has_char and "section" in payload and "content" in payload:
        return "soul"
    # Profile patch: {character_name, fields: {...}}
    if has_char and isinstance(payload.get("fields"), dict):
        return "profile-patch"
    # Full character: has character markers
    char_markers = ("template", "character_personality", "character_appearance",
                    "outfits", "soul")
    if has_char and any(m in payload for m in char_markers):
        return "character"
    # Location: name + rooms (list)
    if "name" in payload and isinstance(payload.get("rooms"), list):
        return "location"
    return ""


def _coerce_json_payload(raw: Any) -> Dict[str, Any]:
    """Accepts either a parsed dict or a JSON string."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Ungueltiges JSON: {e}")
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="json muss ein Objekt sein")
    return raw


@router.get("/character-templates")
def list_character_templates_route():
    """List all selectable character templates — name + label.

    Frontend uses this to populate the template dropdown when creating a
    new character via the World Dev chat. Stays in sync with whatever
    JSON files exist in shared/templates/character/.
    """
    from app.models.character_template import list_templates
    items = list_templates(template_type="character")
    return {"templates": items}


@router.post("/validate-json")
async def validate_json_route(request: Request):
    """Run a tool LLM over the current draft JSON + the schema file and
    return a plain-text list of fields that are missing, empty or use
    placeholder values.

    Body: ``{"schema": "location"|"character"|...,
              "data": {...the LLM-extracted JSON...},
              "model": "<override>"?,
              "provider": "<override>"?}``

    Returns: ``{"gaps": "<plain-text bullet list>", "model_used": "..."}``
    Frontend writes the gaps text into the chat input so the user can
    Send it to the RP LLM and have it fill in the missing pieces.
    """
    body = await request.json()
    schema_name = (body.get("schema") or "").strip() or "location"
    data = body.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="data must be a JSON object")

    try:
        # Schemas carry several placeholders that the chat path fills
        # with runtime context (locations, characters, generable fields,
        # selected template, world premise). For validation we don't
        # want the tool LLM to see any of that — just the schema's own
        # rules — so we collapse every placeholder to empty. Anything
        # left as a literal `{key}` string is then stripped post-load,
        # so the validator sees a clean spec without imagined fields.
        import re as _re
        schema_text = _load_schema(
            schema_name,
            world_setup_block="",
            existing_locations="",
            existing_characters="",
            existing_outfit_types="",
            generable_fields="",
            selected_template="",
        )
        # Belt-and-braces: drop any placeholders we missed so the LLM
        # never sees raw `{some_var}` and treats it as a schema field.
        schema_text = _re.sub(r"\{[a-z_][a-z0-9_]*\}", "", schema_text)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # The validate model is picked in the World-Dev UI right next to the
    # chat model — frontend always sends model + provider. We use the
    # same provider machinery as the chat task so prices and capabilities
    # are consistent. Cap max_tokens tight; the validation output is a
    # short bullet list, and without a cap the LLM can run away into a
    # 200-line repetition loop.
    model = (body.get("model") or "").strip()
    provider = (body.get("provider") or "").strip()
    if not model:
        raise HTTPException(
            status_code=400,
            detail="model required — pick a Validator model in the World Dev header",
        )
    _VALIDATE_MAX_TOKENS = 1024
    instance = create_llm_instance(
        task="chat", model=model,
        provider_name=provider, max_tokens=_VALIDATE_MAX_TOKENS)
    if not instance:
        raise HTTPException(
            status_code=503,
            detail=f"Could not create LLM for {provider}/{model} — provider unavailable or model unknown",
        )

    llm = instance.create_llm() if hasattr(instance, "create_llm") else instance

    from app.core.prompt_templates import render_task
    system_prompt, user_message = render_task(
        "world_dev_validate",
        schema_text=schema_text,
        draft_json=json.dumps(data, ensure_ascii=False, indent=2),
    )

    # One-shot completion — bypass StreamingAgent (its tool-detection /
    # deferred-tool plumbing was holding the response open even after
    # the LLM was done). Stream chunks directly off the LLM client.
    #
    # Anti-runaway guards: tool LLMs occasionally loop on the same line
    # ("character_appearance — should not contain X" repeated 200×).
    # We watch for that during streaming and cancel as soon as the same
    # line has been emitted more than _MAX_REPEAT times. Post-process
    # also dedupes identical lines and caps the final list length.
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    _MAX_REPEAT = 4
    _MAX_LINES = 60
    full = ""
    try:
        line_counts: Dict[str, int] = {}
        bailout = False
        async for chunk in llm.astream(messages):
            content = getattr(chunk, "content", None)
            if not content:
                continue
            full += content
            # Cheap mid-stream loop detection: split current accumulator
            # into newline-trimmed lines and count duplicates. As soon as
            # any line repeats more than _MAX_REPEAT times, stop.
            lines = [ln.strip() for ln in full.split("\n") if ln.strip()]
            line_counts.clear()
            for ln in lines:
                line_counts[ln] = line_counts.get(ln, 0) + 1
                if line_counts[ln] > _MAX_REPEAT:
                    bailout = True
                    break
            if bailout or len(lines) > _MAX_LINES * 2:
                logger.info("validate-json: cancelling stream — runaway loop detected")
                break
    except Exception as e:
        logger.error("validate-json LLM error: %s", e)
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")

    # Post-process: dedupe lines (preserving first-seen order) and cap
    # the list length so the result stays reasonable for the chat input.
    raw_lines = [ln.rstrip() for ln in full.splitlines()]
    seen: Dict[str, int] = {}
    deduped: List[str] = []
    for ln in raw_lines:
        key = ln.strip()
        if not key:
            if not deduped or deduped[-1] != "":
                deduped.append("")
            continue
        if key in seen:
            continue
        seen[key] = 1
        deduped.append(ln)
    if len(deduped) > _MAX_LINES:
        deduped = deduped[:_MAX_LINES] + [
            "",
            f"… ({len(seen)} more issues truncated — fix the above first and re-validate)",
        ]
    gaps = "\n".join(deduped).strip()

    return {
        "gaps": gaps,
        "model_used": getattr(instance, "model", "") or model or "tool",
    }


@router.post("/preview-json")
async def preview_json(request: Request):
    """Type-detect + normalize JSON without applying. Used by the import dialog
    for live-feedback while the user pastes/edits.

    Body: {"json": <obj|string>, "type_hint"?: "character|location|outfit|soul|profile-patch"}
    Returns: {detected_type, type_hint_used, normalized: {...}, warnings: [...],
              valid: bool, error?: "..."}
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_preview_json_sync, data)


def _preview_json_sync(data: Any):
    """The blocking body of ``preview_json`` — runs in the threadpool."""
    try:
        payload = _coerce_json_payload(data.get("json"))
    except HTTPException as e:
        return {"valid": False, "error": e.detail, "detected_type": "",
                "warnings": [], "normalized": None}

    type_hint = (data.get("type_hint") or "").strip()
    detected = type_hint or _detect_json_type(payload)
    warnings: List[str] = []
    normalized: Dict[str, Any] = payload

    if detected == "character":
        normalized, warnings = _normalize_character_json(payload)
    elif detected == "":
        return {"valid": False, "error": "Typ konnte nicht erkannt werden — bitte Override waehlen.",
                "detected_type": "", "warnings": [], "normalized": payload}

    # Sanity preview info
    info: Dict[str, Any] = {"name": ""}
    if detected == "character":
        info["name"] = normalized.get("character_name", "")
        info["template"] = normalized.get("template", "")
        info["outfits"] = len(normalized.get("outfits", []) or [])
        info["soul_md_files"] = list((normalized.get("_extra_soul_md") or {}).keys())
    elif detected == "location":
        info["name"] = normalized.get("name", "")
        info["rooms"] = len(normalized.get("rooms", []) or [])
    elif detected == "outfit":
        info["name"] = (normalized.get("outfit") or {}).get("name", "")
        info["character_name"] = normalized.get("character_name", "")
    elif detected == "soul":
        info["name"] = normalized.get("character_name", "")
        info["section"] = normalized.get("section", "")
    elif detected == "profile-patch":
        info["name"] = normalized.get("character_name", "")
        info["fields"] = list((normalized.get("fields") or {}).keys())

    return {"valid": True, "detected_type": detected,
            "type_hint_used": bool(type_hint),
            "normalized": normalized, "warnings": warnings, "info": info}


@router.post("/apply-json")
async def apply_json(request: Request):
    """Smart import: detect type, normalize, route to the right apply logic.

    Body: {"json": <obj|string>, "type_hint"?: "...", "user_id"?: "..."}
    Returns: {status, type, name, warnings, ...result}
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_apply_json_sync, data)


def _apply_json_sync(data: Any):
    """The blocking body of ``apply_json`` — runs in the threadpool."""
    payload = _coerce_json_payload(data.get("json"))
    type_hint = (data.get("type_hint") or "").strip()
    user_id = data.get("user_id", "")

    detected = type_hint or _detect_json_type(payload)
    if not detected:
        raise HTTPException(status_code=400,
            detail="Typ konnte nicht erkannt werden — bitte type_hint setzen")

    if detected == "character":
        char_data, warnings = _normalize_character_json(payload)
        if not char_data.get("character_name"):
            raise HTTPException(status_code=400, detail="character_name fehlt")
        result = _apply_character_internal(char_data, created_by=user_id)
        return {"status": "success", "type": "character", "name": result["character"],
                "warnings": warnings, **result}

    if detected == "location":
        if not payload.get("name"):
            raise HTTPException(status_code=400, detail="location.name fehlt")
        rooms = payload.get("rooms", []) or []
        for room in rooms:
            if not isinstance(room, dict):
                continue
            if "image_prompt" in room and "image_prompt_day" not in room:
                room["image_prompt_day"] = room.pop("image_prompt")
            if "image_prompt_night" not in room:
                room["image_prompt_night"] = ""
        result = add_location(
            name=payload["name"],
            description=payload.get("description", ""),
            rooms=rooms,
            image_prompt_day=payload.get("image_prompt_day"),
            image_prompt_night=payload.get("image_prompt_night"),
            image_prompt_map_2d=payload.get("image_prompt_map_2d"),
            image_prompt_building=payload.get("image_prompt_building"),
            decency=payload.get("decency"),
            style_hint=payload.get("style_hint"),
            swim_allowed=payload.get("swim_allowed"),
            indoor=payload.get("indoor"),
            activity_hint=payload.get("activity_hint"),
            danger_level=payload.get("danger_level"))
        return {"status": "success", "type": "location", "name": payload["name"],
                "warnings": [], "location": result}

    if detected == "outfit":
        char_name = (payload.get("character_name") or "").strip()
        outfit = payload.get("outfit") or {}
        if not char_name or not outfit.get("name"):
            raise HTTPException(status_code=400,
                detail="outfit braucht character_name + outfit.name")
        profile = get_character_profile(char_name)
        if not profile.get("character_name"):
            raise HTTPException(status_code=404, detail=f"Character '{char_name}' nicht gefunden")
        r = _apply_one_outfit(char_name, outfit)
        return {"status": "success", "type": "outfit", "name": r["name"],
                "character": char_name, "warnings": [], **r}

    if detected == "soul":
        char_name = (payload.get("character_name") or "").strip()
        section = (payload.get("section") or "").strip()
        content = payload.get("content") or ""
        from app.core.soul_sections import SECTION_FILE_MAP
        if not char_name:
            raise HTTPException(status_code=400, detail="character_name erforderlich")
        if section not in SECTION_FILE_MAP:
            raise HTTPException(status_code=400,
                detail=f"section '{section}' unbekannt (erlaubt: {sorted(SECTION_FILE_MAP)})")
        profile = get_character_profile(char_name)
        if not profile.get("character_name"):
            raise HTTPException(status_code=404, detail=f"Character '{char_name}' nicht gefunden")
        from app.models.character import get_character_dir
        char_dir = get_character_dir(char_name, create=True)
        md_path = char_dir / SECTION_FILE_MAP[section]
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(str(content).rstrip() + "\n", encoding="utf-8")
        return {"status": "success", "type": "soul", "name": char_name,
                "section": section, "warnings": [], "size": len(content)}

    if detected == "profile-patch":
        # ONE patch implementation, not two: the smart import hands the
        # payload to the same helper the /apply-profile-patch route uses, so
        # the soul-field filter AND the per-character profile lock (the
        # read-modify-write of the whole profile) exist exactly once.
        char_name = (payload.get("character_name") or "").strip()
        res = _apply_profile_patch_data_sync({
            "character_name": char_name,
            "fields": payload.get("fields") or {},
        })
        return {"status": "success", "type": "profile-patch", "name": char_name,
                "applied_fields": res.get("applied_fields") or [], "warnings": []}

    raise HTTPException(status_code=400, detail=f"Unbekannter Typ: {detected}")
