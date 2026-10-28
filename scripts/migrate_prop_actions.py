#!/usr/bin/env python3
"""Rewrite prop action sidecars for derived bindings and per-slot access, server STOPPED.

Usage:
    ./.venv/bin/python scripts/migrate_prop_actions.py --storage /path/to/world
    ./.venv/bin/python scripts/migrate_prop_actions.py --storage /path/to/world --apply

The default is a read-only dry run. Old binding access_points are discarded
because sidecars do not identify whether they were authored or generated.
All action_bindings are dropped. Explicit false nonlegacy action bindings become
exclude_actions on matching markers; UUID5 legacy generated actions never do.
Explicit marker access overrides are retained. Local support is recalculated
from pose group and participant capacity, never from room walkability.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Persist changes; server must be stopped')
    args = parser.parse_args()
    if not args.storage.is_dir():
        parser.error('--storage must name an existing world directory')
    from app.core import paths
    paths.init(args.storage.resolve())
    from app.core.prop_action_migration import migrate_actions
    report = migrate_actions(dry_run=not args.apply)
    for row in report['props']:
        row.pop('document', None)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return int(bool(report['issues']))


if __name__ == '__main__':
    raise SystemExit(main())
