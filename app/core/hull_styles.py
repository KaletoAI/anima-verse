"""Building styles: shipped JSON seeds with whole-entry world overrides."""
import json
import math
import sqlite3
from typing import Any, Dict, Optional

from app.core.log import get_logger
from app.core.paths import get_shared_dir
from app.core.roof_model import _tone
from app.core.surface_textures import safe_kind

SHARED_DIR = get_shared_dir() / "building_styles"
STORES = ("shared", "world")
WORLD_TABLE = "building_styles_world"
MATERIAL_KEYS = ("wall", "wall_ground", "plinth", "roof", "trim", "door", "chimney")
ROOF_FORMS = ("gable", "hip", "shed", "flat")
logger = get_logger("hull_styles")


def _doc(raw: Any) -> dict:
    return raw if isinstance(raw, dict) else {}


def _number(value: Any, low: float, high: float, default: float) -> float:
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return max(low, min(high, value)) if math.isfinite(value) else default


def _range(value: Any, low: float, high: float, default: list, integer: bool = False) -> list:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return list(default)
    values = [_number(v, low, high, d) for v, d in zip(value, default)]
    return sorted(int(v) if integer else v for v in values)


def _choice(value: Any, choices: tuple, default: str) -> str:
    return value if isinstance(value, str) and value in choices else default


def _subset(value: Any, choices: tuple, default: list) -> list:
    if not isinstance(value, list):
        return list(default)
    return list(dict.fromkeys(v for v in value if isinstance(v, str) and v in choices)) or list(default)


def validate_style(raw: Any, style_id: str) -> Dict[str, Any]:
    """Clamp the known schema; material IDs are sanitized without library lookup."""
    raw = _doc(raw)
    materials, palette = _doc(raw.get("materials")), _doc(raw.get("palette"))
    roof, towers = _doc(raw.get("roof")), _doc(raw.get("towers"))
    result = {
        "name": raw.get("name", style_id)[:200] if isinstance(raw.get("name", style_id), str) else style_id[:200],
        "description": raw.get("description", "")[:600] if isinstance(raw.get("description", ""), str) else "",
        "materials": {key: safe_kind(materials.get(key)) if isinstance(materials.get(key), str) else ""
                      for key in MATERIAL_KEYS},
        "palette": {"glass": _tone(palette.get("glass"), "#3a4a55"),
                    "interior": _tone(palette.get("interior"), "#4a443e")},
        "corners": _choice(raw.get("corners"), ("none", "quoins", "posts", "log_ends"), "none"),
        "frames": _choice(raw.get("frames"), ("none", "timber", "stone"), "timber"),
        "timber_frame": _choice(raw.get("timber_frame"), ("none", "upper", "all"), "none"),
        "roof": {
            "forms": _subset(roof.get("forms"), ROOF_FORMS, ["gable"]),
            "pitch_deg": _range(roof.get("pitch_deg"), 5, 60, [30, 40]),
            "overhang_m": _range(roof.get("overhang_m"), 0, 1, [0.3, 0.5]),
            "parapet": roof.get("parapet") if isinstance(roof.get("parapet"), bool) else False,
        },
        "towers": {
            "chance": _number(towers.get("chance"), 0, 1, 0),
            "radius_m": _range(towers.get("radius_m"), 0.8, 4, [1.4, 2.2]),
            "rise_m": _range(towers.get("rise_m"), 0, 10, [2.5, 5]),
            "roof": _subset(towers.get("roof"), ("cone", "crenel"), ["cone"]),
        },
        "chimneys": _range(raw.get("chimneys"), 0, 4, [0, 1], integer=True),
    }
    for key in ("cornice", "log_walls", "crenellations", "porch"):
        result[key] = raw.get(key) if isinstance(raw.get(key), bool) else False
    for key, low, high, default in (
        ("chimney_width_m", 0.3, 1.5, 0.6),
        ("wall_thickness_m", 0.2, 1.2, 0.4), ("plinth_height_m", 0, 1.5, 0.4),
        ("shutters", 0, 1, 0), ("jetty_m", 0, 0.3, 0), ("dormers", 0, 1, 0),
        ("tint_jitter", 0, 0.2, 0.06), ("weathering", 0, 1, 0.5),
    ):
        result[key] = _number(raw.get(key), low, high, default)
    return result


def _world_rows() -> Dict[str, dict]:
    """Missing schema means an empty layer; other database errors propagate."""
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(f"SELECT id, doc FROM {WORLD_TABLE}").fetchall()
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        return {}
    result = {}
    for key, doc in rows:
        try:
            parsed = json.loads(doc)
        except ValueError:
            logger.warning("World building style %s unreadable", key)
            continue
        if isinstance(parsed, dict):
            result[str(key)] = parsed
    return result


def load_styles() -> Dict[str, Dict[str, Any]]:
    """Read fresh shared seeds, then replace each world entry in full."""
    styles = {}
    for path in sorted(SHARED_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            logger.warning("Shared building style %s unreadable: %s", path.stem, error)
            continue
        styles[path.stem] = {**validate_style(raw, path.stem), "origin": "shared"}
    for key, raw in _world_rows().items():
        styles[key] = {**validate_style(raw, key), "origin": "world"}
    return styles


def get_style(style_id: str) -> Optional[Dict[str, Any]]:
    return load_styles().get(style_id)


def set_world_style(style_id: str, doc: Any) -> Dict[str, Any]:
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    validated = validate_style(doc, style_id)
    with transaction() as conn:
        conn.execute(
            f"INSERT INTO {WORLD_TABLE} (id, doc, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc, updated_at=excluded.updated_at",
            (style_id, json.dumps(validated, ensure_ascii=False), utc_now_iso()),
        )
    return validated


def delete_world_style(style_id: str) -> bool:
    from app.core.db import transaction
    with transaction() as conn:
        cursor = conn.execute(f"DELETE FROM {WORLD_TABLE} WHERE id=?", (style_id,))
        return cursor.rowcount > 0


def validate_description(raw: Any, styles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Keep only supported description overrides and a bounded deterministic seed."""
    raw = _doc(raw)
    style = raw.get("style")
    if not isinstance(style, str) or style not in styles:
        style = "steinhaus"
    try:
        seed = max(0, min(2**31 - 1, int(raw.get("seed", 0))))
    except (ValueError, TypeError, OverflowError):
        seed = 0
    source = _doc(raw.get("overrides"))
    overrides = {}
    try:
        total = max(0, min(40, int(source.get("storeys_total", 0))))
    except (ValueError, TypeError, OverflowError):
        total = 0
    if total > 0:
        overrides["storeys_total"] = total
    if isinstance(source.get("roof_form"), str) and source["roof_form"] in ROOF_FORMS:
        overrides["roof_form"] = source["roof_form"]
    if "pitch_deg" in source:
        overrides["pitch_deg"] = _number(source["pitch_deg"], 5, 60, 30)
    overrides["ornament_density"] = _number(source.get("ornament_density"), 0, 1, 0.5)
    tint = _tone(source.get("tint"), "")
    if tint:
        overrides["tint"] = tint
    return {"style": style, "seed": seed, "overrides": overrides}
