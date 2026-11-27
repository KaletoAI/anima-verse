"""World context and quest-type catalog builder for quest authoring (quest stage 3).

Gathers the read-only world facts an authoring LLM needs (giver situation, nearby
locations, present characters, items, prop library, quest type catalog) and
renders them into prompt-ready plain text. Also owns the canonical ``quest_types``
catalog text shared with World Dev's ``list_catalog``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("quest_context")

#: Character budget for the quest type catalog block.
MAX_CATALOG_CHARS = 5000

QUEST_TYPES_HEADER = (
    'Conditions go into steps[].condition and start_condition, prerequisite '
    'types into prerequisites.condition; an effect is an entry '
    '{"key", "type", "params", "permanent"?} of setup_effects, '
    'steps[].on_done or rewards.',
    "* = required. role[k] takes a role key of kind k. target[...] takes a "
    "role key of the listed kind or the key of an EARLIER effect that makes "
    "the listed object kind: a step condition reaches setup_effects and the "
    "on_done of earlier steps; an on_done entry also the earlier entries of "
    "its own list; a reward every effect key; a setup entry the earlier setup "
    "entries; start_condition and prerequisites setup keys only.",
)


def param_text(p: Dict[str, Any]) -> str:
    """Render one catalog parameter as ``key[*]:type-text``, with ``role[...]``
    (including ``avatar_default``), ``target[...]`` (``role_kinds`` /
    ``object_kinds``), and ``select[...]`` forms."""
    key = f"{p.get('key')}{'*' if p.get('required') else ''}"
    ptype = str(p.get("type") or "")
    if ptype == "role":
        kinds = "|".join(str(k) for k in (p.get("role_kinds") or []))
        if kinds and p.get("avatar_default"):
            ttext = f"role[{kinds}; empty = the avatar]"
        elif kinds:
            ttext = f"role[{kinds}]"
        elif p.get("avatar_default"):
            ttext = "role[empty = the avatar]"
        else:
            ttext = "role"
    elif ptype == "target":
        parts: List[str] = []
        if p.get("role_kinds"):
            parts.append("|".join(str(k) for k in p["role_kinds"]) + " role")
        if p.get("object_kinds"):
            parts.append("|".join(str(k) for k in p["object_kinds"]) + " effect key")
        ttext = f"target[{' or '.join(parts)}]" if parts else "target"
    elif ptype == "select":
        choices = "|".join(str(c) for c in (p.get("choices") or []))
        ttext = f"select[{choices}]" if choices else "select"
    else:
        ttext = ptype
    return f"{key}:{ttext}"


def catalog_lines() -> List[str]:
    """Return the header lines followed by one line per registered quest type."""
    from app.core.quest_catalog import catalog_payload

    out = list(QUEST_TYPES_HEADER)
    for group in catalog_payload().values():
        for t in group:
            obj_kind = t.get("object_kind") or ""
            makes = ""
            if obj_kind:
                makes = f", makes {obj_kind}"
                for param, kind2 in t.get("object_kind_when") or []:
                    makes += f" / {kind2} with {param}"
            step_only = ", step only" if t.get("step_only") else ""
            params = ", ".join(param_text(p) for p in t.get("params") or [])
            out.append(
                f"{t.get('id')} ({t.get('kind')}{makes}{step_only}) — {t.get('label')}: params "
                + (params or "(none)")
            )
    return out


def capped_catalog_lines(budget: int = MAX_CATALOG_CHARS) -> List[str]:
    """Return whole catalog lines in order while ``sum(len(line) + 1) <= budget``.

    Appends ``… +N more types`` when any lines are dropped.
    """
    lines = catalog_lines()
    out: List[str] = []
    used = 0
    for i, line in enumerate(lines):
        cost = len(line) + 1
        if used + cost > budget:
            dropped = len(lines) - i
            trailer = f"… +{dropped} more types"
            while out and used + len(trailer) + 1 > budget:
                removed = out.pop()
                used -= len(removed) + 1
                dropped += 1
                trailer = f"… +{dropped} more types"
            out.append(trailer)
            break
        out.append(line)
        used += cost
    return out


def _finite_coord(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    return val if math.isfinite(val) else None


def build(giver: str | None = None, brief: str = "") -> Dict[str, Any]:
    """Gather world context for quest authoring; never raises.

    ``brief`` is accepted for future relevance filtering and is not otherwise
    used yet.
    """
    from app.core import quest_catalog

    _ = brief  # reserved for future relevance filtering

    giver_info: Optional[Dict[str, str]] = None
    language = ""
    giver_name = (giver or "").strip() if isinstance(giver, str) else ""

    if giver_name:
        try:
            from app.models.character import LANGUAGE_MAP, get_character_profile
            from app.models.world import get_location_by_id, get_room_by_id

            prof = get_character_profile(giver_name, strict=True)
            if isinstance(prof, dict) and prof:
                loc_id = str(prof.get("current_location") or "")
                room_id = str(prof.get("current_room") or "")
                loc_name = ""
                room_name = ""
                if loc_id:
                    loc = get_location_by_id(loc_id)
                    if isinstance(loc, dict):
                        loc_name = str(loc.get("name") or loc_id)
                        if room_id:
                            room = get_room_by_id(loc, room_id)
                            if isinstance(room, dict):
                                room_name = str(room.get("name") or room_id)
                activity = str(prof.get("current_activity") or "")
                giver_info = {
                    "name": giver_name,
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "room_id": room_id,
                    "room_name": room_name,
                    "activity": activity,
                }
                lang_code = str(prof.get("language") or "").strip().lower()
                if lang_code:
                    language = LANGUAGE_MAP.get(lang_code, lang_code)
        except Exception as e:  # noqa: BLE001
            logger.warning("quest_context: failed to read giver %r: %s", giver_name, e)
            giver_info = None
            language = ""

    locations_out: List[str] = []
    try:
        from app.models.world import list_locations

        all_locs = [loc for loc in (list_locations() or []) if isinstance(loc, dict)]
        giver_loc_id = giver_info["location_id"] if giver_info else ""
        gx: Optional[float] = None
        gz: Optional[float] = None
        if giver_loc_id:
            for loc in all_locs:
                if loc.get("id") == giver_loc_id:
                    gx = _finite_coord(loc.get("pos_x"))
                    gz = _finite_coord(loc.get("pos_z"))
                    break

        entries = []
        for loc in all_locs:
            lid = str(loc.get("id") or "")
            if not lid:
                continue
            lname = str(loc.get("name") or lid)
            dist: Optional[float] = None
            if gx is not None and gz is not None:
                lx = _finite_coord(loc.get("pos_x"))
                lz = _finite_coord(loc.get("pos_z"))
                if lx is not None and lz is not None:
                    dist = math.hypot(lx - gx, lz - gz)
            entries.append((loc, lid, lname, dist))

        if gx is not None and gz is not None:
            entries.sort(key=lambda e: (
                0 if e[1] == giver_loc_id else 1,
                e[3] if e[3] is not None else float("inf"),
                e[2].lower(),
            ))
        else:
            entries.sort(key=lambda e: (
                0 if (giver_loc_id and e[1] == giver_loc_id) else 1,
                e[2].lower(),
            ))

        for loc, lid, lname, dist in entries[:12]:
            raw_rooms = loc.get("rooms") if isinstance(loc.get("rooms"), list) else []
            room_parts: List[str] = []
            for r in raw_rooms:
                if not isinstance(r, dict):
                    continue
                rid = str(r.get("id") or "")
                if not rid or rid.startswith("__"):
                    continue
                rname = str(r.get("name") or rid)
                room_parts.append(f'{rid} "{rname}"')
                if len(room_parts) >= 8:
                    break
            line = f'{lid} "{lname}"'
            if room_parts:
                line += " · rooms: " + ", ".join(room_parts)
            if dist is not None and lid != giver_loc_id:
                line += f" · {round(dist)} m away"
            locations_out.append(line)
    except Exception as e:  # noqa: BLE001
        logger.warning("quest_context: failed to read locations: %s", e)
        locations_out = []

    characters_out: List[str] = []
    try:
        from app.core.room_entry import characters_in_room
        from app.models.account import get_all_avatars
        from app.models.character import (
            is_character_sleeping,
            list_available_characters,
            list_character_places,
        )

        places = list_character_places() or {}
        avatars = set(get_all_avatars() or ())
        giver_loc_id = giver_info["location_id"] if giver_info else ""
        if giver_loc_id:
            names = list(characters_in_room(giver_loc_id, "") or [])
        else:
            names = list(list_available_characters() or [])

        for name in names[:30]:
            loc_id, room_id = places.get(name, ("", ""))
            place = f"{loc_id}/{room_id}" if (loc_id and room_id) else (loc_id or room_id or "unknown")
            tags: List[str] = []
            if giver_info and name == giver_info["name"]:
                tags.append(" (giver)")
            if name in avatars:
                tags.append(" (avatar)")
            try:
                if is_character_sleeping(name):
                    tags.append(" (asleep)")
            except Exception:  # noqa: BLE001
                pass
            characters_out.append(f"{name} — at {place}{''.join(tags)}")
    except Exception as e:  # noqa: BLE001
        logger.warning("quest_context: failed to read characters: %s", e)
        characters_out = []

    items_out: List[str] = []
    try:
        from app.models.inventory import list_items

        for item in (list_items() or [])[:40]:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id") or "")
            if not iid:
                continue
            iname = str(item.get("name") or iid)
            cat = str(item.get("category") or "").strip()
            items_out.append(f'{iid} "{iname}"' + (f" ({cat})" if cat else ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("quest_context: failed to read items: %s", e)
        items_out = []

    props_out: List[str] = []
    try:
        from app.core.props import list_props

        for prop in (list_props(read_only=True) or []):
            if not isinstance(prop, dict):
                continue
            if prop.get("quest_run"):
                continue
            pid = str(prop.get("id") or "")
            if not pid:
                continue
            pname = str(prop.get("name") or pid)
            cat = str(prop.get("category") or "").strip()
            props_out.append(f'{pid} "{pname}"' + (f" ({cat})" if cat else ""))
            if len(props_out) >= 40:
                break
    except Exception as e:  # noqa: BLE001
        logger.warning("quest_context: failed to read props: %s", e)
        props_out = []

    catalog_out: List[str] = []
    try:
        catalog_out = capped_catalog_lines()
    except Exception as e:  # noqa: BLE001
        logger.warning("quest_context: failed to read quest catalog: %s", e)
        catalog_out = []

    return {
        "giver": giver_info,
        "language": language,
        "locations": locations_out,
        "characters": characters_out,
        "items": items_out,
        "props": props_out,
        "catalog": catalog_out,
        "role_kinds": list(quest_catalog.ROLE_KINDS),
    }


def render(ctx: Dict[str, Any]) -> str:
    """Format the world context returned by :func:`build` as plain text sections
    for authoring prompts (the catalog is passed separately)."""
    sections: List[str] = []

    giver = ctx.get("giver")
    if isinstance(giver, dict) and giver.get("name"):
        loc_part = giver.get("location_id") or ""
        if giver.get("location_name") and giver["location_name"] != loc_part:
            loc_part = f'{loc_part} "{giver["location_name"]}"'
        room_part = giver.get("room_id") or ""
        if giver.get("room_name") and giver["room_name"] != room_part:
            room_part = f'{room_part} "{giver["room_name"]}"'
        where = " / ".join(p for p in (loc_part, room_part) if p) or "unknown"
        line = f"- {giver['name']} at {where}"
        if giver.get("activity"):
            line += f" (activity: {giver['activity']})"
        sections.append("Giver:\n" + line)

    for heading, key in (
        ("Nearby locations:", "locations"),
        ("Present characters:", "characters"),
        ("Items:", "items"),
        ("Prop library:", "props"),
    ):
        lines = ctx.get(key) or []
        if lines:
            sections.append(heading + "\n" + "\n".join(f"- {ln}" for ln in lines))
        else:
            sections.append(heading + "\n- (none)")

    return "\n\n".join(sections)
