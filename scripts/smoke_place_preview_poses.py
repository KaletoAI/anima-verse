"""The place preview's per-group pose pickers (pair scene, Task 1), in temporary storage — the server half: the poses
a base body's extension group offers, the one it pre-selects, and the motion played for a picked pose.

Usage: .venv/bin/python scripts/smoke_place_preview_poses.py

Fixture: one character "sample" (no clothing), one extension group ``g1`` (package rest_max_deg 90, defaults
otherwise) declaring the pose up {rest_deg 80} and ``preview_pose: up``; ``declared_motion_groups`` and
``rig_groups_for`` are patched to that one group.

Hand derivation:
[a] motion_payload(apply_clothing=False, preview_states=[], preview_poses={g1: up}): the pose's rest angle 80 is the
    largest named one and inside ±rest_max_deg 90, no clothing lift → rest_deg 80.
[b] preview_poses={g1: nope}: g1 declares no pose "nope" → nothing applies → the payload equals the rest payload
    (preview_poses None) — same groups AND same rev; rest_deg 0 there. An unknown group {zz: up} → also the rest.
[c] _with_preview_states({groups: [{id g1}]}): groups[0].poses == ["up"] (the declared ids, sorted),
    preview_pose == "up" (declared and naming a declared pose). A group without a declaration → poses [],
    preview_pose "".
[d] GET …/base-body/pose-motion?poses=g1:nope → 400 (undeclared pair); poses=zz:up → 400; poses=g1 (no colon) →
    400; poses=g1:up → {poses {g1: up}, motion with rest_deg 80}; poses="" → the rest motion (rest_deg 0);
    unknown character → 404. GET, admin-only.
[e] RigSpec.parse rejects a preview_pose that names no declared pose, and a non-string one.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

failures = []


def check(ok, label):
    print(('PASS ' if ok else 'FAIL ') + label)
    if not ok:
        failures.append(label)


def main():
    with tempfile.TemporaryDirectory(prefix='place-preview-poses-') as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        instance = root / 'instance'
        instance.mkdir(parents=True, exist_ok=True)
        (instance / 'config.json').write_text(json.dumps({
            'image_generation': {'blender_meshopt_delivery': False, 'backends': []},
        }))
        from app.core import db, config, extension_rig
        db.init_schema()
        config.load(paths.get_config_path(), instance_path=instance / 'config.json')
        from app.plugins.registry import RigSpec
        from dataclasses import asdict
        raw = {'id': 'g1', 'op': 'pair_protrusion', 'chains': [[{'bone': 'SampleBone', 'parent': 'Hips'}]],
               'rest_max_deg': 90, 'poses': {'up': {'rest_deg': 80}}, 'preview_pose': 'up'}
        try:
            group = asdict(RigSpec.parse(raw))
        except ValueError as exc:
            check(False, f'fixture: RigSpec.parse accepts preview_pose ({exc})')
            group = asdict(RigSpec.parse({k: v for k, v in raw.items() if k != 'preview_pose'}))
        declared = [{'id': 'g1', 'poses': group['poses'], 'preview_pose': group.get('preview_pose', ''),
                     'defaults': {'rest_max_deg': 90}}]
        with patch.object(extension_rig, 'rig_groups_for', return_value=[group]), \
                patch.object(extension_rig, 'declared_motion_groups', return_value=declared):
            from app.models.character import save_character_profile
            from fastapi import HTTPException
            check(save_character_profile('sample', {'template': 'human-default'}, create_new=True), 'profile fixture')
            from app.routes import figure

            rest = extension_rig.motion_payload('sample', apply_clothing=False, preview_states=[])
            check(rest['groups']['g1']['rest_deg'] == 0, '[b] the rest payload has rest_deg 0')
            # [a]
            try:
                up = extension_rig.motion_payload('sample', apply_clothing=False, preview_states=[],
                                                  preview_poses={'g1': 'up'})
                check(up['groups']['g1']['rest_deg'] == 80, '[a] preview_poses {g1: up} → rest_deg 80')
                # [b]
                nope = extension_rig.motion_payload('sample', apply_clothing=False, preview_states=[],
                                                    preview_poses={'g1': 'nope'})
                check(nope == rest, '[b] an undeclared pose → the rest payload (groups and rev)')
                other = extension_rig.motion_payload('sample', apply_clothing=False, preview_states=[],
                                                     preview_poses={'zz': 'up'})
                check(other['groups'] == rest['groups'], '[b] an unknown group → the rest groups')
            except TypeError as exc:
                check(False, f'[a] motion_payload takes preview_poses ({exc})')
            # [c]
            ext = figure._with_preview_states({'groups': [{'id': 'g1'}, {'id': 'undeclared'}]})
            g1, bare = ext['groups']
            check(g1.get('poses') == ['up'] and g1.get('preview_pose') == 'up',
                  '[c] the plain payload group lists poses ["up"], preview_pose "up"')
            check(bare.get('poses') == [] and bare.get('preview_pose') == '',
                  '[c] a group without a declaration: poses [], preview_pose ""')
            # [d]
            route_fn = getattr(figure, 'base_pose_motion', None)
            check(route_fn is not None, '[d] the pose-motion route exists')
            if route_fn is not None:
                for name, poses, code in (('sample', 'g1:nope', 400), ('sample', 'zz:up', 400),
                                          ('sample', 'g1', 400), ('nobody', 'g1:up', 404)):
                    try:
                        route_fn(name, poses, {'role': 'admin'})
                    except HTTPException as exc:
                        check(exc.status_code == code, f'[d] {name} {poses!r} → {code}')
                    else:
                        check(False, f'[d] {name} {poses!r} → {code}')
                answer = route_fn('sample', 'g1:up', {'role': 'admin'})
                check(answer['poses'] == {'g1': 'up'} and answer['motion']['groups']['g1']['rest_deg'] == 80,
                      '[d] g1:up → {poses {g1: up}, rest_deg 80}')
                check(route_fn('sample', '', {'role': 'admin'})['motion']['groups']['g1']['rest_deg'] == 0,
                      '[d] no poses → the rest motion')
                from app.core.auth_dependency import require_admin
                route = next(r for r in figure.router.routes if r.path.endswith('/base-body/pose-motion'))
                check(route.methods == {'GET'} and any(d.call is require_admin for d in route.dependant.dependencies),
                      '[d] GET, admin-only')
        # [e]
        for bad, label in (('nope', 'undeclared'), (3, 'non-string')):
            try:
                RigSpec.parse({**raw, 'preview_pose': bad})
            except ValueError:
                check(True, f'[e] a {label} preview_pose is rejected')
            else:
                check(False, f'[e] a {label} preview_pose is rejected')
    if failures:
        print(f'\nFAILED ({len(failures)})')
        sys.exit(1)
    print('\nALL OK')


if __name__ == '__main__':
    main()
