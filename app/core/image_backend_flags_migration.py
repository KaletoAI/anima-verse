"""Remove retired character backend enable flags without changing render overrides.

Global backend activation and profile.outfit_imagegen are the routing controls.
The old skill-config flags have no reader. Sweep by format on every boot so an
imported old character is cleaned too; unrelated skill and sizing settings stay.
"""
import json
import os
import tempfile
from pathlib import Path

from app.core.log import get_logger

logger = get_logger("image_backend_flags_migration")


def remove_character_backend_flags() -> int:
    """Strip instances.<backend>.enabled in this world's character skill files.

    Return the number of removed flags. Files without flags remain byte-for-byte
    unchanged; invalid files are logged and never overwritten.
    """
    from app.models.character import get_user_characters_dir

    root = get_user_characters_dir().resolve()
    removed = 0
    for character_dir in root.iterdir():
        path = character_dir / "skills" / "image_generation.json"
        if not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Cannot clean backend flags in %s: %s", path, exc)
            continue
        if not isinstance(data, dict) or not isinstance(data.get("instances"), dict):
            continue
        instances = data["instances"]
        count = 0
        for name, settings in list(instances.items()):
            if not isinstance(settings, dict):
                continue
            if "enabled" in settings:
                del settings["enabled"]
                count += 1
            if not settings:
                del instances[name]
        if not count:
            continue
        if not instances:
            del data["instances"]
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=path.parent, suffix=".tmp",
                                             delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        removed += count
    return removed
