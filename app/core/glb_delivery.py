"""Content-addressed, lossless GLB delivery copies built outside request/GPU queues.

Stored models are read only. A first request serves the source while the one
meshopt worker builds a cache entry. Only successful deterministic skips are
memoized on disk; crashes and timeouts may retry on a later request.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import tempfile
import threading
import time

from app.blender import runner
from app.core import config, paths
from app.core.log import get_logger

logger = get_logger(__name__)
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="glb-meshopt")
_lock = threading.Lock()
_pending: set[tuple[Path, str]] = set()
_hashes: OrderedDict[Path, tuple[int, int, int, int, str]] = OrderedDict()
_CACHE_NAME = re.compile(r"[0-9a-f]{64}\.(glb|skip)\Z")


def _sha(path: Path) -> str:
    resolved = path.resolve()
    stat = resolved.stat()
    # Inode and ctime detect replacements/edits that preserve size and mtime.
    signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)
    with _lock:
        memo = _hashes.get(resolved)
        if memo and memo[:4] == signature:
            _hashes.move_to_end(resolved)
            return memo[4]
    with resolved.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = resolved.stat()
    if (after.st_mtime_ns, after.st_size, after.st_ino, after.st_ctime_ns) != signature:
        raise OSError("source changed while hashing")
    with _lock:
        _hashes[resolved] = (*signature, digest)
        _hashes.move_to_end(resolved)
        while len(_hashes) > 4096:
            _hashes.popitem(last=False)
    return digest


def _cache_dir() -> Path:
    return paths.get_storage_dir() / ".cache" / "meshopt"


def _build(source: Path, cache: Path, sha: str) -> None:
    key = (cache, sha)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as tmp:
            work = Path(tmp)
            copied = work / "source.glb"
            # Capture and verify the exact bytes named by the request's hash,
            # even if the stored model was replaced while waiting for the worker.
            import shutil
            with source.open("rb") as src, copied.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            with copied.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != sha:
                    return
            result = runner.run("meshopt", inputs={"model": copied}, out_dir=work)
            if not result.get("ok"):
                logger.debug("Meshopt delivery failed: %s", result.get("error", "unknown error"))
                return
            skipped = result.get("data", {}).get("skipped")
            if skipped:
                marker = work / "result.skip"
                marker.write_text(str(skipped), encoding="utf-8")
                marker.replace(cache / f"{sha}.skip")
            elif result.get("outputs", {}).get("model"):
                output = Path(result["outputs"]["model"])
                output.replace(cache / f"{sha}.glb")
    except Exception:
        logger.exception("Meshopt delivery build failed")
    finally:
        with _lock:
            _pending.discard(key)


def delivery_path(path: Path) -> Path:
    """Serve a cached delivery copy, otherwise enqueue once and serve the source."""
    path = Path(path)
    if path.suffix.lower() != ".glb" or not config.get("image_generation.blender_meshopt_delivery", True):
        return path
    try:
        if not runner.status()["usable"]:
            return path
        sha, cache = _sha(path), _cache_dir()
        key = (cache, sha)
        with _lock:
            # Recheck under the scheduling lock: a worker may have published
            # between hashing and reaching this block.
            for suffix in ("glb", "skip"):
                entry = cache / f"{sha}.{suffix}"
                if entry.is_file():
                    try:
                        entry.touch(exist_ok=True)
                    except FileNotFoundError:
                        continue
                    return entry if suffix == "glb" else path
            if key not in _pending:
                _pending.add(key)
                try:
                    _worker.submit(_build, path.resolve(), cache, sha)
                except Exception:
                    _pending.discard(key)
                    raise
    except OSError:
        logger.debug("Meshopt delivery source/cache unavailable: %s", path)
    return path


def sweep_cache(*, now: float | None = None) -> int:
    """Remove only delivery GLBs/skip markers unused for more than 30 system days."""
    cache = _cache_dir()
    if not cache.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - 30*86400
    removed = 0
    # Serialize touches and deletion decisions so a just-used entry survives.
    with _lock:
        for entry in cache.iterdir():
            if not _CACHE_NAME.fullmatch(entry.name) or not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except FileNotFoundError:
                pass
    if removed:
        logger.info("Meshopt delivery: removed %d unused cache entries", removed)
    return removed
