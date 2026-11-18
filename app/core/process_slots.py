"""A cross-process limit: at most N holders of one kind of slot across EVERY process of the installation.

Used by the Blender runner (``runner.blender_slot``: ``server.blender_max_concurrent``) and by GPU compute
(``gpu_compute``: ``server.gpu_compute_parallel``). A ``SlotPool`` names its slot folder under the instance
(``<instance>/<dir_name>/slot-<i>.lock``) and its setting; ``hold`` keeps one of the slot files under an exclusive
``flock`` for the block. The kernel drops the lock when the holder's descriptor closes, so a killed process frees
its slot by itself; a caller that finds every slot taken polls every ``SLOT_POLL_S`` until one is free, and the
limit is re-read on every try, so a changed setting applies to callers that already wait.

A process without a loaded config (a refit pool worker, at spawn) gets the server's folder and limit pinned
(``SlotPool.pin`` with the parent's ``SlotPool.spawn_spec()``); they stay until it ends. Without an instance (a
script) the folder is one per user in the system temp folder.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

#: How often a caller that found every slot taken tries again.
SLOT_POLL_S = 0.25


def try_slots(folder: Path, limit: int) -> Optional[int]:
    """An open descriptor holding one of slots ``0..limit-1`` of ``folder`` exclusively, else None."""
    import fcntl
    for i in range(limit):
        fd = os.open(str(folder / f"slot-{i}.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            continue
        return fd
    return None


@contextlib.contextmanager
def hold(folder: Path, limit: Callable[[], int], *, what: str, label: str = "",
         on_wait: Optional[Callable[[bool], None]] = None) -> Iterator[Dict[str, float]]:
    """Hold one of ``limit()`` slot files of ``folder`` for the block — waiting, polled every ``SLOT_POLL_S``,
    while all are taken (``limit`` is called on every try). ``on_wait(True)`` / ``on_wait(False)`` when the caller
    starts / stops waiting (a failing callback is logged and ignored). Yields ``{"wait_s": <seconds waited>}``. A
    slot folder that cannot be created runs the block unlimited (logged). ``what`` / ``label`` name the holder in
    the log lines."""
    def notify(waiting: bool) -> None:
        if on_wait is None:
            return
        try:
            on_wait(waiting)
        except Exception:  # noqa: BLE001 — visibility only
            logger.exception("%s wait notice failed", what)

    started = time.monotonic()
    info = {"wait_s": 0.0}
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("%s limit: slot folder %s unusable (%s) — running unlimited", what, folder, e)
        yield info
        return
    fd: Optional[int] = None
    waited = False
    try:
        while True:
            fd = try_slots(folder, max(1, int(limit())))
            if fd is not None:
                break
            if not waited:
                waited = True
                logger.info("%s %s: waiting for a free slot (limit %d)", what, label or "run", limit())
                notify(True)
            time.sleep(SLOT_POLL_S)
        info["wait_s"] = time.monotonic() - started
        if waited:
            logger.info("%s %s: slot free after %.1fs", what, label or "run", info["wait_s"])
            notify(False)
        yield info
    finally:
        if fd is not None:
            os.close(fd)  # closing the descriptor drops the flock


class SlotPool:
    """One kind of slot: its folder name under the instance, its setting (``section.key`` of the server config,
    an int >= 1, read live) and the fallback default when the schema cannot be read. ``read(path, default)``
    replaces the plain ``config.get`` read (the Blender runner passes its own ``_config``)."""

    def __init__(self, dir_name: str, setting: str, fallback: int,
                 read: Optional[Callable[[str, Any], Any]] = None) -> None:
        self.dir_name = dir_name
        self.setting = setting
        self.fallback = int(fallback)
        self._read = read
        self._pinned: Dict[str, Any] = {}

    def _default(self) -> int:
        try:
            from app.core.config_schema import SECTIONS
            section, key = self.setting.split(".", 1)
            return int(SECTIONS[section]["fields"][key]["default"])
        except Exception:  # noqa: BLE001 — the limit never stops a run
            return self.fallback

    def limit(self) -> int:
        """The setting resolved live (at least 1); the value pinned at spawn in a process without a config, else
        the schema default."""
        if "limit" in self._pinned:
            return max(1, int(self._pinned["limit"]))
        default = self._default()
        try:
            if self._read is not None:
                raw = self._read(self.setting, default)
            else:
                from app.core import config
                raw = config.get(self.setting, None)
            return max(1, int(default if raw is None or raw == "" else raw))
        except Exception:  # noqa: BLE001 — no config loaded (a script), or an unparsable value
            return max(1, default)

    def folder(self) -> Path:
        """The folder of the slot files: pinned at spawn, else ``<instance>/<dir_name>``, else (a script without
        an instance) one per user in the system temp folder."""
        if self._pinned.get("dir"):
            return Path(self._pinned["dir"])
        try:
            from app.core import paths
            if paths.instance_initialised():
                return paths.get_instance_dir() / self.dir_name
        except Exception:  # noqa: BLE001
            pass
        uid = os.getuid() if hasattr(os, "getuid") else 0
        return Path(tempfile.gettempdir()) / f"anima-{self.dir_name.lstrip('.')}-{uid}"

    def pin(self, directory: Optional[str], limit: Optional[int]) -> None:
        """Fix folder and limit for this process (a spawned worker gets the server's values at spawn)."""
        self._pinned.clear()
        if directory:
            self._pinned["dir"] = str(directory)
        if limit:
            self._pinned["limit"] = int(limit)

    def spawn_spec(self) -> Tuple[str, int]:
        """What ``pin`` needs in a child process: ``(folder, limit)`` now."""
        return str(self.folder()), self.limit()
