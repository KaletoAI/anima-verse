#!/usr/bin/env python3
"""Remove authored prop actions whose pose a package now supplies.

Usage:
    ./.venv/bin/python scripts/prune_prop_actions_by_pose.py --world NAME --poses "key-a, key-b"
        [--worlds-dir DIR]   (default: <repo>/worlds)
        [--apply]

A package that adds furniture actions at runtime (``app/core/prop_action_sources.py``)
makes an authored copy of the same pose on a prop redundant — and the authored
copy travels with every export of the prop. This removes, from every prop of the
world, each OWN action whose pose (``pose_key``; a combined action: any phase
pose) is one of ``--poses``, plus every marker ``exclude_actions`` entry that
named it. Nothing else in a sidecar changes.

Dry run by default: lists what it would remove. ``--apply`` writes, and only
with the server STOPPED (it refuses while ``.pids/main.pid`` names a live
process); each changed sidecar is copied first to
``<repo>/migration_backup/prune-prop-actions-<stamp>/<prop id>/sidecar.json``.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _server_running() -> bool:
    pid_file = REPO / ".pids" / "main.pid"
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (OSError, ValueError):
        return False
    return True


def _poses_of(action: dict) -> set:
    if action.get("ability") == "combined":
        return {str(p.get("pose_key") or "").strip().lower() for p in action.get("phases") or [] if isinstance(p, dict)}
    return {str(action.get("pose_key") or "").strip().lower()}


def prune(document: dict, poses: set) -> tuple:
    """(new document, removed actions) — pure, the document is not touched."""
    removed = [a for a in document.get("actions") or [] if isinstance(a, dict) and _poses_of(a) & poses]
    if not removed:
        return document, []
    ids = {a.get("id") for a in removed}
    result = json.loads(json.dumps(document))
    result["actions"] = [a for a in result.get("actions") or [] if not (isinstance(a, dict) and a.get("id") in ids)]
    for variant in result.get("model_variants") or []:
        for marker in variant.get("markers") or []:
            if isinstance(marker, dict) and isinstance(marker.get("exclude_actions"), list):
                kept = [aid for aid in marker["exclude_actions"] if aid not in ids]
                if kept:
                    marker["exclude_actions"] = kept
                else:
                    marker.pop("exclude_actions")
    return result, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--world", required=True)
    parser.add_argument("--poses", required=True, help="comma-separated pose keys")
    parser.add_argument("--worlds-dir", type=Path, default=REPO / "worlds")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    poses = {p.strip().lower() for p in args.poses.split(",") if p.strip()}
    world = (args.worlds_dir / args.world).resolve()
    if not (world / "props").is_dir():
        print(f"no props directory in {world}", file=sys.stderr)
        return 2
    if args.apply and _server_running():
        print("the server is running — stop it before --apply", file=sys.stderr)
        return 2

    from app.core import paths
    paths.init(str(world))
    from app.core import props
    from app.core.timeutils import utc_now

    backup = REPO / "migration_backup" / f"prune-prop-actions-{utc_now().strftime('%Y%m%dT%H%M%S')}"
    total = changed = 0
    for directory in sorted(p for p in (world / "props").iterdir() if p.is_dir()):
        pid = directory.name
        document = props.read_sidecar(pid, read_only=True)
        if not document:
            continue
        result, removed = prune(document, poses)
        if not removed:
            continue
        changed += 1
        total += len(removed)
        print(f"{document.get('name') or pid} ({pid}): " + ", ".join(
            f"{a.get('name')} [{a.get('pose_key') or a.get('ability')}]" for a in removed))
        if args.apply:
            target = backup / pid
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / "sidecar.json", target / "sidecar.json")
            props._write_sidecar(pid, result)
    verb = "removed" if args.apply else "would remove"
    print(f"{verb} {total} action(s) on {changed} prop(s)"
          + (f"; backups in {backup}" if args.apply and changed else "")
          + ("" if args.apply else " — dry run, nothing written (add --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
