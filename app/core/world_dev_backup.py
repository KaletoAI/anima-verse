"""Safety backup of a world for World Dev free-mode runs, and its offline restore.

The journal (``world_dev_runs``) is the undo; this backup is the LAST RESORT for
the case that the journal itself fails. Before the first write tool of a run the
caller (the run manager) takes one with :func:`take_backup` and records the
returned path with ``world_dev_runs.set_backup`` — this module does not know the
run store.

A backup lives in ``<storage>/.cache/world_dev_backups/<run_id>/``:

- ``world.db`` — a SQLite online backup (``sqlite3.Connection.backup``), so it
  is consistent while the server keeps writing;
- ``characters/<name>/…`` — copies of the character TEXT files (``*.md``,
  ``*.json``: soul markdown, config, skills, outfits), not images or the media
  directories (``images``, ``model3d``, ``model_refs``, hidden dirs);
- ``meta.json`` — run id and system stamp, written LAST, so a directory
  without it is an unfinished backup.

The newest :data:`MAX_BACKUPS` are kept.

:func:`restore_backup` is the core of ``scripts/world_dev_restore.py`` and runs
ONLY with the server stopped (the script checks). It touches nothing but plain
files under the given storage directory and never opens the world through
``app.core.db``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.core.log import get_logger
from app.core.timeutils import utc_now

logger = get_logger("world_dev_backup")

MAX_BACKUPS = 10
BACKUPS_SUBDIR = Path(".cache") / "world_dev_backups"
REMOVED_SUBDIR = "removed_after_restore"
TEXT_SUFFIXES = {".md", ".json"}
# Media directories inside a character directory: their JSON files are image /
# model sidecars, not character data.
SKIP_DIRS = {"images", "model3d", "model_refs"}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def safe_run_id(run_id: Any) -> str:
    """The run id as a single safe path segment; ValueError otherwise."""
    value = str(run_id or "")
    if not _RUN_ID_RE.match(value):
        raise ValueError(f"unsafe run id: {run_id!r}")
    return value


def backups_root(storage_dir: Union[str, Path]) -> Path:
    return Path(storage_dir) / BACKUPS_SUBDIR


def backup_dir(storage_dir: Union[str, Path], run_id: str) -> Path:
    """The backup directory of *run_id*, contained in the backups root."""
    root = backups_root(storage_dir).resolve()
    target = (root / safe_run_id(run_id)).resolve()
    if target.parent != root:
        raise ValueError(f"unsafe run id: {run_id!r}")
    return target


def _iter_text_files(characters_dir: Path):
    """Relative paths of every text file under *characters_dir* (sorted)."""
    if not characters_dir.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(characters_dir):
        rel_dir = Path(dirpath).relative_to(characters_dir)
        # depth 1 = inside one character directory: drop the media dirs there
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".")
            and not (len(rel_dir.parts) == 1 and d in SKIP_DIRS))
        for name in sorted(filenames):
            if Path(name).suffix.lower() in TEXT_SUFFIXES and len(rel_dir.parts) >= 1:
                yield rel_dir / name


def _copy_text_files(src_chars: Path, dst_chars: Path) -> int:
    count = 0
    for rel in _iter_text_files(src_chars):
        dst = dst_chars / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_chars / rel, dst)
        count += 1
    return count


def _character_dirs(characters_dir: Path) -> List[str]:
    if not characters_dir.is_dir():
        return []
    return sorted(p.name for p in characters_dir.iterdir()
                  if p.is_dir() and not p.name.startswith("."))


def _backup_stamp(path: Path) -> str:
    """Sort key of a finished backup: its meta stamp, else '' (oldest)."""
    try:
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        return str(meta.get("taken_at") or "")
    except (OSError, ValueError):
        return ""


def _prune(storage_dir: Path, keep: str) -> List[str]:
    """Delete all but the newest MAX_BACKUPS backups; never *keep*."""
    root = backups_root(storage_dir).resolve()
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    dirs.sort(key=lambda p: (_backup_stamp(p), p.stat().st_mtime_ns, p.name),
              reverse=True)
    removed = []
    for path in dirs[MAX_BACKUPS:]:
        if path.name == keep or path.resolve().parent != root:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    if removed:
        logger.info("world-dev backups pruned: %s", ", ".join(removed))
    return removed


def take_backup(run_id: str, storage_dir: Optional[Union[str, Path]] = None) -> str:
    """Back up the world DB and the character text files for *run_id*.

    Returns the backup directory as a string. Raises on any failure — the
    caller decides whether a run may write without a backup (it must not).
    An existing finished backup of the same run is kept and returned: the
    backup is the state BEFORE the run's first write, and a later call must
    never replace it (nor drop a ``removed_after_restore/`` folder in it).
    """
    if storage_dir is None:
        from app.core.paths import get_storage_dir
        storage_dir = get_storage_dir()
    storage = Path(storage_dir)
    target = backup_dir(storage, run_id)
    src_db = storage / "world.db"
    if not src_db.is_file():
        raise FileNotFoundError(f"world DB not found: {src_db}")
    if (target / "meta.json").is_file() and (target / "world.db").is_file():
        return str(target)

    work = target.with_name(target.name + ".partial")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        src = sqlite3.connect(str(src_db), timeout=10)
        try:
            dst = sqlite3.connect(str(work / "world.db"))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        files = _copy_text_files(storage / "characters", work / "characters")
        (work / "meta.json").write_text(json.dumps({
            "run_id": target.name,
            # every character directory of the moment, also those without text
            # files: the restore moves only directories NOT named here
            "characters": _character_dirs(storage / "characters"),
            "taken_at": utc_now().isoformat(timespec="microseconds"),
            "text_files": files,
        }, indent=2), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        os.replace(work, target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    logger.info("world-dev backup %s: world.db + %d text files", target, files)
    _prune(storage, keep=target.name)
    return str(target)


def _free_name(parent: Path, name: str) -> Path:
    candidate = parent / name
    n = 2
    while candidate.exists():
        candidate = parent / f"{name}-{n}"
        n += 1
    return candidate


def restore_backup(run_id: str, storage_dir: Union[str, Path]) -> Dict[str, Any]:
    """Put the backup of *run_id* back into *storage_dir*. Server must be stopped.

    - deletes ``world.db-wal`` / ``world.db-shm`` (a stray WAL would replay
      newer frames onto the restored file), copies the backup DB to a temp
      name beside ``world.db`` and ``os.replace``s it;
    - copies the backed-up text files back over the character directories;
    - moves character directories that did not exist at backup time into
      ``<backup>/removed_after_restore/`` (never deleted).

    Returns what it did: ``{"backup", "db", "removed_sidecars", "text_files",
    "moved_dirs"}``.
    """
    storage = Path(storage_dir)
    source = backup_dir(storage, run_id)
    src_db = source / "world.db"
    if not src_db.is_file() or not (source / "meta.json").is_file():
        raise FileNotFoundError(f"no finished backup at {source}")
    meta = json.loads((source / "meta.json").read_text(encoding="utf-8"))
    # Check the backup DB before anything in the world is touched.
    conn = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
    try:
        ok = conn.execute("PRAGMA quick_check").fetchone()
    finally:
        conn.close()
    if not ok or ok[0] != "ok":
        raise RuntimeError(f"backup DB failed quick_check: {ok}")

    world_db = storage / "world.db"
    # Copy first: a failed copy must leave the current DB and its WAL intact.
    tmp = storage / "world.db.restore-tmp"
    shutil.copy2(src_db, tmp)
    removed_sidecars = []
    for suffix in ("-wal", "-shm"):
        side = storage / f"world.db{suffix}"
        if side.exists():
            side.unlink()
            removed_sidecars.append(side.name)
    os.replace(tmp, world_db)

    world_chars = storage / "characters"
    backup_chars = source / "characters"
    files = _copy_text_files(backup_chars, world_chars)

    moved = []
    if world_chars.is_dir():
        known = set(meta.get("characters") or [])
        if backup_chars.is_dir():
            known |= {p.name for p in backup_chars.iterdir()}
        removed_root = source / REMOVED_SUBDIR
        for entry in sorted(world_chars.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in known:
                continue
            removed_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(_free_name(removed_root, entry.name)))
            moved.append(entry.name)

    return {
        "backup": str(source),
        "db": str(world_db),
        "removed_sidecars": removed_sidecars,
        "text_files": files,
        "moved_dirs": moved,
    }
