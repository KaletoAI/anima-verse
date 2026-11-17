#!/usr/bin/env python3
"""Re-measure non-strip clip turns in BOTH libraries, without opening a world.

Usage: ALSOFT_DRIVERS=null ./.venv/bin/python scripts/backfill_clip_turn.py --dry-run
The default only measures and prints. Only --write changes sidecars; it refuses while
``.pids/main.pid`` names a live server and replaces each sidecar atomically.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner
from app.core import paths
from app.core.http_files import atomic_replace, sibling_stage


def write_sidecar(sidecar: Path, meta: dict) -> None:
    """Stage beside the sidecar and replace it: a server listing the clips reads the old or the new
    document, never a truncated one."""
    mode = sidecar.stat().st_mode & 0o777
    with sibling_stage(sidecar) as tmp:
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.chmod(tmp, mode)
        atomic_replace(tmp, sidecar)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Measure and list only (default)')
    mode.add_argument('--write', action='store_true', help='Write measured turn_deg into sidecars')
    args = parser.parse_args()
    if args.write:
        import config_history
        if config_history._server_running(config_history.PID_FILE):
            parser.error('the server is running; stop it before --write (./start.sh --stop)')
    os.environ.setdefault('ALSOFT_DRIVERS', 'null')
    changed = failed = measured = 0
    for library in (paths.get_animation_clips_dir(), paths.get_licensed_clips_dir()):
        print(f'LIBRARY {library}', flush=True)
        for sidecar in sorted(library.rglob('*.json')):
            meta = json.loads(sidecar.read_text(encoding='utf-8'))
            if not isinstance(meta, dict):
                continue
            root = (meta.get('geometry') or {}).get('root_motion')
            if not isinstance(root, dict) or root.get('mode', 'strip') == 'strip':
                continue
            clip = sidecar.with_suffix('.fbx')
            result = runner.run('clip_root_motion', inputs={'rig': paths.get_rig_file(), 'src': clip},
                                params={'fps': 30, 'measure_only': True})
            turn = result.get('data', {}).get('turn_deg')
            if not result.get('ok') or not isinstance(turn, (int, float)) or not math.isfinite(turn):
                print(f'ERROR {sidecar}: {result.get("error") or "no finite turn"}', flush=True)
                failed += 1
                continue
            measured += 1
            old = root.get('turn_deg')
            if old == turn:
                print(f'UNCHANGED {sidecar}: {turn:.6f}', flush=True)
                continue
            changed += 1
            print(f'{"WRITE" if args.write else "WOULD CHANGE"} {sidecar}: {old!r} -> {turn:.6f}', flush=True)
            if args.write:
                # Refuse to overwrite edits made while Blender measured the clip.
                current = json.loads(sidecar.read_text(encoding='utf-8'))
                if current != meta:
                    raise RuntimeError(f'Sidecar changed during measurement: {sidecar}')
                root['turn_deg'] = turn
                write_sidecar(sidecar, meta)
    print(f'{"WRITE" if args.write else "DRY RUN"}: measured={measured}, changed={changed}, failed={failed}', flush=True)
    return int(failed > 0)


if __name__ == '__main__':
    sys.exit(main())
