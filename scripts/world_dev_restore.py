#!/usr/bin/env python3
"""Restore a World Dev free-mode safety backup — OFFLINE, with the server stopped.

Usage:
    ./.venv/bin/python scripts/world_dev_restore.py <run_id> --world NAME
    ./.venv/bin/python scripts/world_dev_restore.py <run_id> --storage DIR [--force]
    (without --world/--storage the STORAGE_DIR environment variable decides)

The backup lives in ``<storage>/.cache/world_dev_backups/<run_id>/`` (the run
detail in Game-Admin → World Dev shows the path). The restore replaces
``world.db`` (stray ``world.db-wal``/``-shm`` are deleted first), copies the
character text files back and moves character directories created after the
backup into ``<backup>/removed_after_restore/`` — nothing is deleted.

It is the last resort when the run journal itself failed; the normal undo is
Discard in the UI.

Refuses with exit code 2 while the server may run: ``.pids/main.pid`` (repo
root, ``start.sh`` PID_DIR) names a live process, or a process matches the
``uvicorn app.server:app`` pattern. ``--force`` skips that check with a
warning (Docker, where the check cannot see the container's server).
``--pid-dir`` points the pid-file check elsewhere (tests).
"""
import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.core import world_dev_backup  # noqa: E402

SERVER_PATTERN = ("uvicorn", "app.server:app")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def server_running(pid_dir: Path) -> str:
    """A reason string when a server may be running, else ''."""
    pid_file = pid_dir / "main.pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text().strip())
        except ValueError:
            pid = 0
        if pid > 0 and _pid_alive(pid):
            return f"{pid_file} names live pid {pid}"
    proc = Path("/proc")
    if proc.is_dir():
        me = os.getpid()
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == me:
                continue
            try:
                cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                    "utf-8", "replace")
            except OSError:
                continue
            if all(p in cmd for p in SERVER_PATTERN):
                return f"pid {entry.name} runs {cmd.strip()[:120]}"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Restore a World Dev safety backup (server stopped).")
    ap.add_argument("run_id")
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--storage", help="world storage directory")
    where.add_argument("--world", help="world name under <repo>/worlds/")
    ap.add_argument("--force", action="store_true",
                    help="skip the running-server check (Docker)")
    ap.add_argument("--pid-dir", default=str(REPO / ".pids"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.storage:
        storage = Path(args.storage)
    elif args.world:
        storage = REPO / "worlds" / args.world
    elif os.environ.get("STORAGE_DIR"):
        storage = Path(os.environ["STORAGE_DIR"])
    else:
        print("error: give --storage DIR or --world NAME (or set STORAGE_DIR)",
              file=sys.stderr)
        return 2
    if not (storage / "world.db").is_file():
        print(f"error: no world.db in {storage}", file=sys.stderr)
        return 2

    if args.force:
        print("WARNING: --force — not checking whether the server is running.",
              file=sys.stderr)
    else:
        reason = server_running(Path(args.pid_dir))
        if reason:
            print(f"refused: the server seems to be running ({reason}). "
                  "Stop it first (./start.sh --stop) or pass --force.", file=sys.stderr)
            return 2

    try:
        report = world_dev_backup.restore_backup(args.run_id, storage)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"restored backup {report['backup']}")
    print(f"  world.db replaced: {report['db']}")
    if report["removed_sidecars"]:
        print(f"  deleted: {', '.join(report['removed_sidecars'])}")
    print(f"  character text files restored: {report['text_files']}")
    if report["moved_dirs"]:
        print(f"  character dirs moved to removed_after_restore/: "
              f"{', '.join(report['moved_dirs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
