"""Messaging frame for the phone-chat layout.

Each world can have one frame (smartphone, mirror, crystal ball, notice board)
generated from an LLM image prompt. Pipeline:

  1. the image service renders "<frame> with a pure-green display area"
  2. rembg removes the outer background (frame edge becomes transparent)
  3. chroma key: every green pixel -> alpha=0
  4. bounding box of the green region -> sidecar JSON
  5. the frontend stacks: character image inside the bbox + frame overlay

Files:
  worlds/<world>/ui/messaging_frame.png    (frame with a transparent display area)
  worlds/<world>/ui/messaging_frame.json   {prompt, bbox, frame_size, generated_at}
"""
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("messaging_frame")


def _ui_dir() -> Path:
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "ui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_frame_path() -> Path:
    return _ui_dir() / "messaging_frame.png"


def get_frame_meta_path() -> Path:
    return _ui_dir() / "messaging_frame.json"


def load_frame_meta() -> Optional[Dict[str, Any]]:
    p = get_frame_meta_path()
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Loading the frame meta failed: %s", e)
        return None


def has_frame() -> bool:
    return get_frame_path().exists() and get_frame_meta_path().exists()


def _process_chroma_key(image_bytes: bytes) -> Tuple[bytes, Dict[str, Any]]:
    """Applies rembg + chroma key to the generated frame image.

    Args:
        image_bytes: PNG/JPEG bytes from the image backend.

    Returns:
        (processed_png_bytes, meta dict with bbox + frame_size)

    Raises:
        ValueError when no green display area was found.
    """
    import io
    import numpy as np
    from PIL import Image

    # 1. Load the image as RGBA
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    arr = np.array(img)  # shape (H, W, 4)
    h, w = arr.shape[:2]
    logger.info("Frame source: %dx%d", w, h)

    # 2. rembg for the outer background — isolate the frame contour
    try:
        from app.models.character import _get_rembg_session
        from rembg import remove
        session = _get_rembg_session()
        # rembg expects bytes
        rembg_out = remove(image_bytes, session=session)
        rembg_img = Image.open(io.BytesIO(rembg_out)).convert("RGBA")
        arr = np.array(rembg_img)
        logger.info("rembg applied (background removed)")
    except Exception as e:
        # Not fatal — without rembg only the outer edge stays opaque. The frame
        # still works, it just looks rectangular instead of cut out.
        logger.warning("rembg skipped (%s) — the frame stays rectangular", e)

    # 3. Chroma key: find the green pixels
    # An HSV classification would be more tolerant; the RGB heuristic is enough.
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    # "green" = G clearly above R and B
    is_green = (g > 100) & (g > r + 30) & (g > b + 30) & (a > 100)
    green_count = int(is_green.sum())
    logger.info("Green pixels: %d of %d (%.1f%%)", green_count, h * w, 100.0 * green_count / max(h * w, 1))
    if green_count < 1000:
        raise ValueError(
            f"No sufficiently green display area found in the image "
            f"({green_count} pixels). Adjust the prompt — the display area must "
            f"be clearly green (e.g. 'pure green screen', 'chroma green')."
        )

    # 4. Bounding box of the green region (the largest connected region):
    # simplified — the min/max coordinates of all green pixels, assuming the
    # model renders one connected display area.
    ys, xs = np.where(is_green)
    bbox_x = int(xs.min())
    bbox_y = int(ys.min())
    bbox_w = int(xs.max() - xs.min() + 1)
    bbox_h = int(ys.max() - ys.min() + 1)
    logger.info("Bounding box: x=%d y=%d w=%d h=%d", bbox_x, bbox_y, bbox_w, bbox_h)

    # 5. Make the green pixels transparent
    new_arr = arr.copy()
    new_arr[is_green, 3] = 0  # alpha=0

    # 6. Trim: cut away every fully transparent (alpha=0) column and row at the
    # border. That makes the frame PNG match the visible area exactly, so the
    # profile-image placement in the frontend no longer depends on how much
    # empty space the model rendered around the frame.
    alpha = new_arr[:, :, 3]
    visible_cols = (alpha > 0).any(axis=0)
    visible_rows = (alpha > 0).any(axis=1)
    nonzero_x = np.where(visible_cols)[0]
    nonzero_y = np.where(visible_rows)[0]
    if len(nonzero_x) > 0 and len(nonzero_y) > 0:
        crop_left = int(nonzero_x.min())
        crop_right = int(nonzero_x.max() + 1)  # exclusive for slicing
        crop_top = int(nonzero_y.min())
        crop_bottom = int(nonzero_y.max() + 1)
        new_arr = new_arr[crop_top:crop_bottom, crop_left:crop_right, :]
        # Correct the bbox coordinates relative to the new image anchor
        bbox_x = max(0, bbox_x - crop_left)
        bbox_y = max(0, bbox_y - crop_top)
        new_w = crop_right - crop_left
        new_h = crop_bottom - crop_top
        if (crop_left > 0 or crop_right < w or crop_top > 0 or crop_bottom < h):
            logger.info(
                "Trim: %d L + %d R + %d T + %d B removed -> %dx%d (was %dx%d)",
                crop_left, w - crop_right, crop_top, h - crop_bottom,
                new_w, new_h, w, h)
        w, h = new_w, new_h

    # 7. Save
    out_img = Image.fromarray(new_arr, mode="RGBA")
    out_buf = io.BytesIO()
    out_img.save(out_buf, format="PNG")
    meta = {
        "bbox": {"x": bbox_x, "y": bbox_y, "w": bbox_w, "h": bbox_h},
        "frame_size": [w, h],
        "green_pixel_count": green_count,
    }
    return out_buf.getvalue(), meta


def parse_target(target: str) -> Tuple[str, str]:
    """Turns the configured render target into a plain backend-name glob.

    The canonical form is a bare backend glob ("Flux2*", or an exact backend
    name as served by /admin/settings/imagegen-targets); ``backend:<glob>`` is
    the tolerated legacy prefix. The ComfyUI-era ``workflow:<glob>`` is NOT a
    target format any more — it resolves to nothing at render time, so it is
    rejected here instead of silently falling back to some other backend.

    Returns:
        (glob, error) — ``glob`` empty means auto-selection; ``error`` empty
        means the spec was accepted. Pure function, no service access.
    """
    spec = (target or "").strip()
    if not spec:
        return "", ""
    if spec.lower().startswith("backend:"):
        return spec.split(":", 1)[1].strip(), ""
    if spec.lower().startswith("workflow:"):
        return "", (
            f"Legacy target format '{target}': ComfyUI workflows were removed. "
            f"Use a backend-name glob (e.g. 'Flux2*') or leave it empty for "
            f"automatic selection.")
    if ":" in spec:
        return "", (
            f"Invalid target format: '{target}'. Expected a backend-name glob "
            f"(e.g. 'Flux2*'), the legacy form 'backend:<glob>', or an empty "
            f"value for automatic selection.")
    return spec, ""


def unknown_backend_error(glob: str, backend_names) -> str:
    """Checks the glob against the backends the admin select actually offers.

    The ComfyUI era left WORKFLOW names in this field ("Z-Image", "Flux") —
    after the legacy prefix is stripped they look canonical but match no
    backend (those are called "CivitAI-Z-Image", "Flux2-9B Normal", ...). The
    render would then die deep inside the service with a message about a
    timeout that never happened, so the mismatch is caught here instead.

    Returns the error message, or "" when the glob matches at least one name.
    """
    import fnmatch
    names = [str(n) for n in (backend_names or [])]
    pattern = (glob or "").strip().lower()
    if not pattern or any(fnmatch.fnmatch(n.lower(), pattern) for n in names):
        return ""
    offered = ", ".join(sorted(names)) if names else "none"
    return (f"No enabled backend matches '{glob}' — pick a backend in "
            f"Admin → Settings → Messaging frame. Enabled backends: {offered}")


def generate_frame(prompt: str, target: str = "") -> Dict[str, Any]:
    """Renders the messaging-frame image via the image service and stores it.

    Args:
        prompt: image prompt (e.g. "modern smartphone, pure green screen, isolated").
        target: render target as served by /admin/settings/imagegen-targets —
            a backend-name glob, the legacy "backend:<glob>", or empty = auto.

    Returns:
        dict with status, path, bbox, frame_size, or error.
    """
    if not prompt or not prompt.strip():
        return {"status": "error", "error": "Prompt missing"}

    # 1. Resolve the target spec first — a bad format must not cost a render.
    backend_glob, target_error = parse_target(target)
    if target_error:
        return {"status": "error", "error": target_error}

    # 2. Fetch the image service
    try:
        from app.imagegen.service import get_image_service
        image_skill = get_image_service()
        if not image_skill.enabled:
            return {"status": "error", "error": "image service not available"}
    except Exception as e:
        return {"status": "error", "error": f"image service missing: {e}"}

    # 3. The glob must name a backend the pool knows — same list the admin
    # select offers (/admin/settings/imagegen-targets: enabled image backends).
    if backend_glob:
        known = [b.name for b in getattr(image_skill, "backends", [])
                 if getattr(b, "instance_enabled", False)
                 and getattr(b, "MEDIA_TYPE", "image") == "image"]
        unknown = unknown_backend_error(backend_glob, known)
        if unknown:
            return {"status": "error", "error": unknown}

    # 4. Generate — everything goes through the image service (its pipeline
    # owns model resolution, seeds, reference slots and the cloud fallback).
    try:
        import json as _json
        # Materialize the _messaging_frame pseudo-character base dir so the
        # skill's image save (get_character_images_dir) has a real base — the
        # dir getters no longer create ghost dirs on read/write for missing
        # characters, and this pseudo-character has no profile-creation flow.
        from app.models.character import get_character_dir
        get_character_dir("_messaging_frame", create=True)
        payload = {
            "prompt": prompt.strip(),
            "input": prompt.strip(),
            "agent_name": "_messaging_frame",
            "user_id": "",
            "set_profile": False,
            "skip_gallery": True,
            "auto_enhance": False,
            "negative_prompt": "person, people, face, reflection, text, watermark, blurry, lowres",
        }
        if backend_glob:
            # Explicit pick: the user chose this backend in the admin select —
            # match it or fail, never render on a different one silently.
            payload["backend"] = backend_glob
        logger.info("Frame generation: target=%s prompt=%.80s", backend_glob or "auto", prompt)
        img_result = image_skill.generate_from_input(_json.dumps(payload))

        # The service returns a status/path string — extract the path
        import re as _re
        m = _re.search(r"/images/([^?\s\)\n]+)", img_result or "")
        if not m:
            return {"status": "error",
                    "error": f"Generation returned no image: {(img_result or '')[:400]}"}
        from app.models.character import get_character_images_dir
        src_path = get_character_images_dir("_messaging_frame") / m.group(1)
        if not src_path.exists():
            return {"status": "error", "error": f"File not found: {src_path}"}
        raw_bytes = src_path.read_bytes()
        # Clean up — remove the whole _messaging_frame pseudo-character
        # directory so neither the image file nor profile/outfit/meta files are
        # left behind. The service creates them during the render.
        try:
            import shutil
            char_dir = src_path.parent.parent  # images/<file> -> char_dir
            if char_dir.exists() and char_dir.name == "_messaging_frame":
                shutil.rmtree(char_dir, ignore_errors=True)
        except Exception as _cleanup_err:
            logger.debug("Cleanup of _messaging_frame failed: %s", _cleanup_err)
        # And the DB row, in case _ensure_agent_config created one
        try:
            from app.core.db import get_connection as _conn
            with _conn() as _c:
                _c.execute("DELETE FROM characters WHERE name = ?", ("_messaging_frame",))
                _c.commit()
        except Exception:
            pass
    except Exception as e:
        logger.error("Frame generation failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}

    # 5. Chroma key + rembg
    try:
        processed_bytes, meta = _process_chroma_key(raw_bytes)
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error("Post-processing failed: %s", e)
        return {"status": "error", "error": f"Post-processing: {str(e)[:200]}"}

    # 6. Save
    frame_path = get_frame_path()
    frame_path.write_bytes(processed_bytes)
    meta["prompt"] = prompt
    meta["target"] = backend_glob or "auto"
    meta["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(get_frame_meta_path(), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info("Frame saved: %s (bbox=%s)", frame_path, meta["bbox"])
    return {
        "status": "ok",
        "path": str(frame_path),
        "bbox": meta["bbox"],
        "frame_size": meta["frame_size"],
        "target": backend_glob or "auto",
        "generated_at": meta["generated_at"],
    }
