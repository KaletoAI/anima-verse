"""Opt-in, read-only source check; every output stays in a temporary directory.

Usage: RUN_EXTENSION_RIG_REAL=1 .venv/bin/python scripts/smoke_extension_rig_real.py
       --model SOURCE.glb --declaration MANIFEST.yaml --group GROUP_ID [--normalize --target-height-m METRES]

The declaration is read unchanged. Version-5 example parameters are injected
into an in-memory copy; obsolete blend fields are removed there. All other
declaration values are preserved. Use --normalize
only for a raw source that has not already been normalized.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--declaration', type=Path, required=True)
    parser.add_argument('--group', required=True)
    parser.add_argument('--normalize', action='store_true')
    parser.add_argument('--target-height-m', type=float)
    args = parser.parse_args()
    if os.environ.get('RUN_EXTENSION_RIG_REAL') != '1':
        parser.error('requires RUN_EXTENSION_RIG_REAL=1')
    if args.normalize and (args.target_height_m is None or args.target_height_m <= 0):
        parser.error('--normalize requires positive --target-height-m')
    import yaml
    manifest = yaml.safe_load(args.declaration.read_text())
    matches = [slot['rig'] for slot in manifest.get('body_slots', [])
               if (slot.get('rig') or {}).get('id') == args.group]
    if len(matches) != 1:
        parser.error('expected one matching rig declaration')
    group = copy.deepcopy(matches[0])
    group['params'].update(segment_radius_factor=1.35, contact_ramp=.01,
                           segment_min_vertices=3, segment_radius_percentile=.95,
                           segment_radius_margin=1.2, segment_radius_growth_max=1.5,
                           segment_passes=3, centerline_slab=.08, link_blend=.06)
    group['params'].pop('blend_start', None)
    group['params'].pop('blend_width', None)
    source_hash = hashlib.sha256(args.model.read_bytes()).hexdigest()
    declaration_hash = hashlib.sha256(args.declaration.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='extension-real-') as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root/'storage')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root/'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root/'reference.fbx')
        from app.blender import runner
        source = root/'source.glb'
        shutil.copy2(args.model, source)
        if args.normalize:
            result = runner.run('normalize', inputs={'model': source},
                                params={'target_height_m': args.target_height_m},
                                out_dir=root/'normalized', timeout_s=180)
            if not result['ok']:
                raise RuntimeError(result['error'])
            source = Path(result['outputs']['model'])
        result = runner.run('extension_bones', inputs={'model': source},
                            params={'groups': [group]}, out_dir=root/'output',
                            timeout_s=600)
        if not result['ok'] or result['data'].get('status') != 'applied':
            raise RuntimeError(json.dumps(result))
        print(json.dumps(result['data']['metrics'][args.group], indent=2, sort_keys=True))
        for key in ('thigh_weight_in_part', 'uncaptured_in_part', 'captured_beyond_radius'):
            assert result['data']['metrics'][args.group][key] == 0, key
    assert hashlib.sha256(args.model.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(args.declaration.read_bytes()).hexdigest() == declaration_hash
    print('PASS real source and declaration unchanged; outputs were temporary')


if __name__ == '__main__':
    main()
