"""WebM (VP9) companions for MP4 gallery videos.

WHY. Generated clips are H.264 MP4. The native client shows the HUD in CEF,
whose stock binaries ship without proprietary codecs, so ``<video>`` cannot
decode them there; browsers can. VP9 in WebM plays in both, so every MP4 gets
a hidden WebM copy and the players list both sources (WebM first).

STORAGE. ``<dir of the mp4>/.video-webm/<mp4 stem>.webm`` -- a hidden
sub-directory outside flat gallery/thumbnail/media scans (same idea as
``screenshot_sources``). Character exports skip it, deleting the video deletes
it, and a daily sweep removes orphans.

GENERATION. Right after a video lands (``schedule_webm``, daemon thread, never
blocks the caller) and lazily on the first request for an existing video
(``ensure_webm``). Both go through one single-flight table keyed by the
companion path, so concurrent requests run ONE ffmpeg job. A missing ffmpeg is
logged once and answered with ``None``; it never raises.

ENCODER. ``libvpx-vp9 -deadline realtime -cpu-used 8 -row-mt 1 -crf 33 -b:v 0``:
generated clips are a few seconds long, a request may be waiting for the
result, and speed matters more than the last percent of size. Resolution and
frame rate are kept; audio (Opus) only when the source has an audio stream.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, Iterable, Optional

from app.core.log import get_logger

logger = get_logger("video_webm")

WEBM_DIR = ".video-webm"
WEBM_MEDIA_TYPE = "video/webm"
#: Upper bound of one encode; a clip that needs longer is not a gallery clip.
ENCODE_TIMEOUT_S = 300

_lock = threading.Lock()
_inflight: Dict[str, threading.Event] = {}
_ffmpeg_missing_logged = False


def _inside(directory: Path, path: Path) -> Path:
    try:
        base = directory.resolve()
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("Invalid video path") from exc
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError("Video path leaves its directory")
    return resolved


def companion_path(video: Path) -> Path:
    """The companion path of an MP4 (it need not exist yet). Raises
    ``ValueError`` for a non-mp4 name or a symlinked directory/file."""
    video = Path(video)
    if video.suffix.lower() != ".mp4" or not video.name or video.name.startswith("."):
        raise ValueError("Not an mp4 gallery video")
    directory = video.parent / WEBM_DIR
    if directory.is_symlink():
        raise ValueError("WebM directory is a symlink")
    directory = _inside(video.parent, directory)
    target = directory / f"{video.stem}.webm"
    if target.is_symlink():
        raise ValueError("WebM companion is a symlink")
    return _inside(directory, target)


def _fresh(video: Path, webm: Path) -> bool:
    try:
        return webm.is_file() and webm.stat().st_size > 0 \
            and webm.stat().st_mtime_ns >= video.stat().st_mtime_ns
    except OSError:
        return False


def _encode(video: Path, target: Path) -> bool:
    global _ffmpeg_missing_logged
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if not _ffmpeg_missing_logged:
            _ffmpeg_missing_logged = True
            logger.warning("ffmpeg not found -- WebM companions for gallery videos are skipped")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.stem}.{os.getpid()}.{threading.get_ident()}.tmp.webm")
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(video),
           "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
           "-row-mt", "1", "-crf", "33", "-b:v", "0", "-pix_fmt", "yuv420p",
           "-c:a", "libopus", "-f", "webm", str(tmp)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=ENCODE_TIMEOUT_S)
        if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            logger.warning("WebM encode failed for %s: %s", video.name,
                           result.stderr.decode("utf-8", "replace")[-300:])
            return False
        os.replace(tmp, target)
        return True
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("WebM encode failed for %s: %s", video.name, exc)
        return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def ensure_webm(video: Path, wait: Optional[float] = None) -> Optional[Path]:
    """The up-to-date companion, creating it when needed. Single-flight: a
    concurrent caller waits for the running job (at most ``wait`` seconds,
    ``None`` = until it ends) instead of starting a second one. ``None`` when
    it could not be produced (or the wait ran out)."""
    try:
        video = Path(video)
        if not video.is_file():
            return None
        target = companion_path(video)
    except (ValueError, OSError):
        return None
    if _fresh(video, target):
        return target
    key = str(target)
    with _lock:
        event = _inflight.get(key)
        owner = event is None
        if owner:
            event = _inflight[key] = threading.Event()
    if not owner:
        event.wait(wait)
        return target if _fresh(video, target) else None
    try:
        # Re-check inside the flight: a finished job may have landed meanwhile.
        if _fresh(video, target) or _encode(video, target):
            return target
        return None
    finally:
        with _lock:
            _inflight.pop(key, None)
        event.set()


def schedule_webm(video: Path) -> None:
    """Produce the companion in a background thread. Never raises, never blocks."""
    def run():
        try:
            ensure_webm(video)
        except Exception as exc:  # a background helper must not die loudly
            logger.warning("WebM companion for %s failed: %s", Path(video).name, exc)
    threading.Thread(target=run, daemon=True, name="video-webm").start()


def remove_companion(video: Path) -> int:
    """Delete the companion of ``video`` (also when the mp4 is already gone)."""
    from app.core import media_cleanup
    try:
        target = companion_path(Path(video))
    except (ValueError, OSError):
        return 0
    return media_cleanup.remove_files([target])


def sweep_orphans(video_dirs: Iterable[Path]) -> int:
    """Remove companions whose mp4 no longer exists in each directory."""
    from app.core import media_cleanup
    removed = 0
    for directory in video_dirs:
        companions = Path(directory) / WEBM_DIR
        if companions.is_symlink() or not companions.is_dir():
            continue
        for webm in companions.glob("*.webm"):
            if not (Path(directory) / f"{webm.stem}.mp4").is_file():
                removed += media_cleanup.remove_files([webm])
        for stray in companions.glob(".*.tmp.webm"):
            removed += media_cleanup.remove_files([stray])
    return removed


def sweep_all_orphans() -> int:
    """Periodic job: character galleries and the Instagram directory."""
    from app.core.paths import get_storage_dir
    root = get_storage_dir() / "characters"
    dirs = [d / "images" for d in root.iterdir() if d.is_dir()] if root.is_dir() else []
    instagram = get_storage_dir() / "instagram"
    if instagram.is_dir():
        dirs.append(instagram)
    removed = sweep_orphans(dirs)
    if removed:
        logger.info("video_webm: %d orphan companion(s) removed", removed)
    return removed
