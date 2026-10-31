"""Shared OpenAI-compatible image user content for game and suitability calls."""
import base64
from pathlib import Path


def image_user_content(text: str, image_path: str | Path) -> list[dict]:
    """Read an image, retaining its extension MIME; missing files raise normally."""
    path = Path(image_path)
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    ext = path.suffix.lower().lstrip(".")
    mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "webp": "webp", "gif": "gif"}.get(ext, "png")
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{encoded}"}}]
