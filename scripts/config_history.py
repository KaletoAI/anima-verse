#!/usr/bin/env python3
"""Inspect and restore config layer backups without loading a world.

Usage:
    ./.venv/bin/python scripts/config_history.py list [--layer DIR]
    ./.venv/bin/python scripts/config_history.py diff STAMP [--layer DIR]
    ./.venv/bin/python scripts/config_history.py restore STAMP [--layer DIR]

The default layer is <repo>/instance; restore requires a stopped server.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from app.core import config

PID_FILE = REPO / ".pids" / "main.pid"
FILES = ("config.json", "secrets.json")


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def diff_layers(old_cfg: dict, old_sec: dict, new_cfg: dict, new_sec: dict) -> List[str]:
    """Describe section and named-entry changes, exposing only secret paths."""
    lines = []

    def entries(old, new, path):
        if isinstance(old, dict) or isinstance(new, dict):
            old = old if isinstance(old, dict) else {}
            new = new if isinstance(new, dict) else {}
            for key in sorted(old.keys() | new.keys()):
                entries(old.get(key, []), new.get(key, []), f"{path}.{key}")
        elif isinstance(old, list) and isinstance(new, list):
            if not all(isinstance(item, dict) and isinstance(item.get("name"), str)
                       for item in old + new):
                return
            old_names = {item["name"] for item in old}
            new_names = {item["name"] for item in new}
            for label, names in (("removed", old_names - new_names),
                                 ("added", new_names - old_names)):
                if names:
                    lines.append(f"{path}: {label} entries {sorted(names)!r}")

    for key in sorted(old_cfg.keys() | new_cfg.keys()):
        if key not in old_cfg:
            lines.append(f"{key}: added")
        elif key not in new_cfg:
            lines.append(f"{key}: removed")
        elif old_cfg[key] != new_cfg[key]:
            lines.append(f"{key}: changed")
        else:
            continue
        entries(old_cfg.get(key, []), new_cfg.get(key, []), key)

    missing = object()

    def secrets(old, new, path):
        if old == new:
            return
        if isinstance(old, dict) or isinstance(new, dict):
            old_map = old if isinstance(old, dict) else {}
            new_map = new if isinstance(new, dict) else {}
            keys = old_map.keys() | new_map.keys()
            if keys:
                for key in sorted(keys):
                    secrets(old_map.get(key, missing), new_map.get(key, missing),
                            f"{path}.{key}" if path else key)
                return
        lines.append(f"secret changed: {path}")

    secrets(old_sec, new_sec, "")
    return lines


def _snapshot(layer: Path, stamp: str) -> Path:
    if not re.fullmatch(r"\d{8}T\d{12}Z(?:-[1-9]\d*)?", stamp):
        raise ValueError("invalid snapshot stamp")
    snapshot = layer / config.CONFIG_HISTORY_DIRNAME / stamp
    if not snapshot.is_dir() or snapshot.is_symlink():
        raise ValueError("snapshot not found")
    return snapshot


def _server_running(pid_file: Path) -> bool:
    try:
        pid = int(pid_file.read_text().strip())
    except FileNotFoundError:
        return False
    except ValueError:
        raise ValueError("invalid PID file") from None
    if pid <= 0:
        raise ValueError("invalid PID file")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _replace(path: Path, data: bytes) -> None:
    """Replace a file atomically with private permissions from creation."""
    fd, name = tempfile.mkstemp(prefix=".config-restore-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def restore(layer: Path, stamp: str, pid_file: Path) -> int:
    """Back up the current layer, then restore saved bytes with mode 0600."""
    try:
        if _server_running(pid_file):
            print("stop the server first (./start.sh --stop)", file=sys.stderr)
            return 2
        snapshot = _snapshot(layer, stamp)
        # Read before snapshotting: retention may remove the selected old backup.
        saved = {name: (snapshot / name).read_bytes()
                 for name in FILES if (snapshot / name).exists()}
        if not saved:
            raise ValueError("snapshot contains no layer files")
        for data in saved.values():
            if not isinstance(json.loads(data), dict):
                raise ValueError("expected a JSON object")
        config.snapshot_layer(layer)
        for name in FILES:
            target = layer / name
            if name in saved:
                _replace(target, saved[name])
            else:
                target.unlink(missing_ok=True)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("list", "diff", "restore"):
        sub = commands.add_parser(command)
        sub.add_argument("--layer", type=Path, default=REPO / "instance")
        if command != "list":
            sub.add_argument("stamp")
    args = parser.parse_args()
    if args.command == "restore":
        return restore(args.layer, args.stamp, PID_FILE)
    try:
        if args.command == "list":
            for snapshot in config.list_snapshots(args.layer):
                cfg = snapshot / "config.json"
                size = cfg.stat().st_size if cfg.exists() else 0
                sections = ", ".join(sorted(_read(cfg)))
                secret = "yes" if (snapshot / "secrets.json").exists() else "no"
                print(f"{snapshot.name}  {size}  secrets: {secret}  {sections}")
        else:
            snapshot = _snapshot(args.layer, args.stamp)
            for line in diff_layers(_read(snapshot / FILES[0]), _read(snapshot / FILES[1]),
                                    _read(args.layer / FILES[0]), _read(args.layer / FILES[1])):
                print(line)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Cannot read config history: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
