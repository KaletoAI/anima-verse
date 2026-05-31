"""Post-processing trigger (pull model).

After an eligible image is saved, optionally notify an external post-processing
service. The notification carries ONLY an identifier — the world-relative image
path — never image bytes. The external service then pulls the image itself
(gallery API / filesystem), processes it, and writes the result back via the
API write endpoint.

Configuration (admin settings):
  image_generation.postprocess_enabled     bool   master on/off
  image_generation.postprocess_trigger_url  str    base URL to notify

Eligible image kinds (decided in code, not configurable): scene/chat, event,
instagram. Avatar/profile images, expression variants and outfit previews never
trigger — they are the reference sources, not post-processing targets.

Fire-and-forget: failures are logged and never affect image generation.
"""
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Union

from app.core import config
from app.core.log import get_logger
from app.core.paths import get_storage_dir

logger = get_logger("postprocess_trigger")


def _enabled() -> bool:
    return bool(config.get("image_generation.postprocess_enabled", False))


def _base_url() -> str:
    return (config.get("image_generation.postprocess_trigger_url") or "").strip()


def _relative_path(image_path: Union[str, Path]) -> Optional[str]:
    """Return the image path relative to the storage dir (posix), or None."""
    try:
        rel = Path(image_path).resolve().relative_to(get_storage_dir().resolve())
        return rel.as_posix()
    except (ValueError, OSError):
        logger.warning("postprocess trigger: path not under storage: %s", image_path)
        return None


def _send(url: str) -> None:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310 (configured URL)
            r.read(0)
    except Exception as e:  # noqa: BLE001 — fire-and-forget
        logger.warning("postprocess trigger failed (%s): %s", url, e)


def trigger(image_path: Union[str, Path], category: str) -> None:
    """Fire-and-forget notify the PP service about a finished image.

    image_path : absolute path to the saved image (must be under storage dir)
    category   : "scene" | "event" | "instagram" (informational, appended)
    No image bytes are sent; only the world-relative path + category.
    """
    if not _enabled():
        return
    base = _base_url()
    if not base:
        return
    rel = _relative_path(image_path)
    if not rel:
        return
    query = urllib.parse.urlencode({"path": rel, "category": category})
    sep = "&" if ("?" in base) else "?"
    url = f"{base}{sep}{query}"
    # fire-and-forget: never block the caller
    threading.Thread(target=_send, args=(url,), daemon=True).start()
    logger.info("postprocess trigger queued: category=%s path=%s", category, rel)
