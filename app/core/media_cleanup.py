"""Removing the media files a deleted record owned.

WHY. A delete path that drops a DB row but leaves its directory or image
files behind leaks disk for good: galleries are listed by directory scan, so
nothing ever collects a folder whose owner is gone. Every delete path that
owns files calls into this module AFTER its DB step succeeded.

RULES (the callers follow them, this module enforces the path half):

* Files go only after the DB delete has succeeded.
* Removing a file never fails the operation: an ``OSError`` is logged with
  the path and the caller continues.
* No file work while holding ``world_write_lock`` or a ``keyed_lock`` other
  writers wait on — collect the ids inside the lock, remove after leaving it.
  (Boot-only migrations are excepted: nothing else runs yet.)
* A directory named by an id is removed only when the id is a safe key AND
  the resolved directory lies strictly inside its root. Character names do
  not fit the key shape (umlauts, spaces) — this helper is not for them.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable

from app.core.log import get_logger

logger = get_logger("media_cleanup")

# Same shape as ``inventory.safe_item_id``; also covers prop ids, the
# ``uuid4().hex[:8]`` location ids and the ``evt_<hex>`` event ids.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def safe_key(key: str) -> str:
    """``key`` when it is a safe directory/file key, else ''."""
    k = key if isinstance(key, str) else ""
    return k if _KEY_RE.match(k) else ""


def contained(root: Path, path: Path) -> bool:
    """True when ``path`` resolves strictly inside ``root`` (resolved)."""
    try:
        base = Path(root).resolve()
        target = Path(path).resolve()
    except OSError:
        return False
    return target != base and target.is_relative_to(base)


def remove_owned_dir(root: Path, key: str) -> bool:
    """rmtree ``root/key`` when ``key`` is a safe id and the directory lies
    strictly inside ``root``. Never creates ``root``.

    False = nothing there, refused (unsafe key, outside the root, a symlink)
    or failed (logged)."""
    if not safe_key(key):
        logger.warning("media cleanup: refused unsafe key %r under %s",
                       str(key)[:80], root)
        return False
    target = Path(root) / key
    if target.is_symlink():
        logger.warning("media cleanup: refused symlinked dir %s", target)
        return False
    if not target.is_dir():
        return False
    if not contained(root, target):
        logger.warning("media cleanup: refused %s (outside %s)", target, root)
        return False
    try:
        shutil.rmtree(target)
    except OSError as exc:
        logger.warning("media cleanup: could not remove %s: %s", target, exc)
        return False
    return True


def remove_files(paths: Iterable[Path]) -> int:
    """Unlink each path (missing ones are skipped). An ``OSError`` is logged,
    never raised. Returns how many files were actually removed."""
    removed = 0
    for p in paths:
        p = Path(p)
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
                removed += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("media cleanup: could not remove %s: %s", p, exc)
    return removed
