"""Validated shipped door styles, read fresh in stable filename order."""
import json
import math

from app.core.hull_util import tone
from app.core.log import get_logger
from app.core.paths import get_shared_dir

SHARED_DIR = get_shared_dir() / 'door_styles'
logger = get_logger('door_styles')


def _choice(value, choices, default):
    return value if isinstance(value, str) and value in choices else default


def _number(value, low, high, default):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return max(low, min(high, value)) if math.isfinite(value) else default


def _material(value, default):
    if not isinstance(value, str) or not value.strip():
        return default
    value = value.strip()
    return tone(value, default) if value.startswith('#') else value


def validate_door_style(raw: dict) -> dict:
    """Normalize known fields without looking up texture kinds or world data."""
    raw = raw if isinstance(raw, dict) else {}
    result = {}
    for key, default, limit in (('id', 'panel', 200), ('name', 'Panel', 200),
                                ('description', '', 600)):
        value = raw.get(key, default)
        result[key] = value[:limit] if isinstance(value, str) else default
    result.update(
        leaf=_choice(raw.get('leaf'), ('plank','panel','glazed','glass','flush'), 'panel'),
        leaf_material=_material(raw.get('leaf_material'), '#5a3b2a'),
        leaf_tint=tone(raw.get('leaf_tint'), ''),
        frame_material=_material(raw.get('frame_material'), '#efe9dc'),
        glass_rows=int(_number(raw.get('glass_rows'), 1, 4, 2)),
        glass_cols=int(_number(raw.get('glass_cols'), 1, 4, 3)),
        panels=raw.get('panels') if type(raw.get('panels')) is int and raw['panels'] in (0,2,4) else 4,
        hardware=_choice(raw.get('hardware'), ('ring','lever','knob','bar'), 'lever'),
        hardware_color=tone(raw.get('hardware_color'), '#333333'),
        studs=raw.get('studs') if isinstance(raw.get('studs'), bool) else False,
        strap_hinges=raw.get('strap_hinges') if isinstance(raw.get('strap_hinges'), bool) else False,
        double_from_m=_number(raw.get('double_from_m'), .1, 100, 1.5),
    )
    return result


def load_door_styles() -> dict[str, dict]:
    """Read shared JSON seeds only; malformed files are logged and skipped."""
    styles = {}
    for path in sorted(SHARED_DIR.glob('*.json')):
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            logger.warning('Shared door style %s unreadable: %s', path.stem, error)
            continue
        raw = raw if isinstance(raw, dict) else {}
        styles[path.stem] = validate_door_style({**raw, 'id': path.stem})
    return styles
