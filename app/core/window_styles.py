"""Validated shipped window styles, read fresh in stable filename order."""
import json

from app.core.door_styles import _choice, _material
from app.core.hull_util import tone
from app.core.log import get_logger
from app.core.paths import get_shared_dir

logger = get_logger('window_styles')


def validate_window_style(raw: dict) -> dict:
    """Normalize known fields without looking up texture kinds or world data."""
    raw = raw if isinstance(raw, dict) else {}
    result = {}
    for key, default, limit in (('id', 'plain', 200), ('name', 'Plain', 200),
                                ('description', '', 600)):
        value = raw.get(key, default)
        result[key] = value[:limit] if isinstance(value, str) else default
    frame = _choice(raw.get('frame'), ('timber','stone','metal','plain'), 'plain')
    result.update(
        frame=frame,
        frame_material=_material(raw.get('frame_material'),
                                 {'stone':'#ece8df', 'metal':'#2f3236'}.get(frame, '#efe9dc')),
        glass_tint=tone(raw.get('glass_tint'), '#2f3d47' if frame == 'metal' else '#3a4a55'),
        bars=raw['bars'] if isinstance(raw.get('bars'), bool) else frame != 'plain',
    )
    return result


def load_window_styles() -> dict[str, dict]:
    """Read shared JSON seeds only; malformed files are logged and skipped."""
    styles = {}
    for path in sorted((get_shared_dir() / 'window_styles').glob('*.json')):
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            logger.warning('Shared window style %s unreadable: %s', path.stem, error)
            continue
        raw = raw if isinstance(raw, dict) else {}
        styles[path.stem] = validate_window_style({**raw, 'id': path.stem})
    return styles
