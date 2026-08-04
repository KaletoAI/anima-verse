"""Application-facing side of the Blender stage: what callers actually call.

``runner`` speaks in scripts and job directories; this is the layer that knows
what the app wants done and what belongs in a sidecar. Every model store
(characters, props) uses the SAME entry point, so a new store gets the whole
stage by calling one function rather than by copying a recipe.

Best-effort throughout: a host without Blender, a disabled refinement or a
failing script must never cost an asset that was just generated. Nothing here
modifies a mesh — measuring only reads.
"""
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)


def measure_file(path: Path) -> Optional[Dict[str, Any]]:
    """Real geometry of a model file, or None when it could not be measured.

    Adds ``at`` and ``blender`` to what the script reports, so a stored
    measurement says when it was taken and by which version — a number whose
    origin is unknown cannot be trusted later.
    """
    from app.blender import runner
    res = runner.run("measure", inputs={"model": Path(path)})
    if not res.get("ok"):
        logger.debug("nicht vermessen (%s): %s", Path(path).name,
                     res.get("error"))
        return None
    data = dict(res["data"])
    data["at"] = utc_now_iso()
    data["blender"] = runner.version()
    return data


def attach_measurement(meta: Dict[str, Any], path: Path,
                       key: str = "measured") -> bool:
    """Measures ``path`` and puts the result in ``meta[key]``. True when it
    landed. The caller writes the sidecar — one write, not two."""
    data = measure_file(path)
    if data is None:
        return False
    meta[key] = data
    return True


def unavailable_reason() -> str:
    """Why measuring is not possible right now, "" when it is.

    Callers turn this into an HTTP error; keeping the wording here means the
    admin reads the same sentence wherever the stage is offered.
    """
    from app.blender import runner
    st = runner.status()
    if not st["enabled"]:
        return "blender refinement is disabled"
    if not st["executable"]:
        return "no blender executable found"
    return ""
