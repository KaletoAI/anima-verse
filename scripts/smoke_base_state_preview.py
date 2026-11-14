"""The Base body tab's state preview (Ruling A66), in temporary storage — its server half: the states it offers and
the motion it plays for one of them.

Usage: .venv/bin/python scripts/smoke_base_state_preview.py

Fixture: one character "sample" whose free-text outfit is "a long coat" (no item pieces), one extension group
``sample_group`` (package gravity .35, gain 1, max_deg 30, rest_max_deg 45, freetext_clothing_gain .5) and four
states:
  lifted    label "Lifted"     bone_pose {sample_group: {rest_deg 12, gravity .5, length 1.5}}
  calm      label ""           bone_pose {sample_group: {rest_deg -6}}
  elsewhere label "Elsewhere"  bone_pose {other_group: {rest_deg 20}}     (moves no group of this model)
  plain     label "Plain"      no bone_pose

Hand derivation:
[1] bone_pose_states(["sample_group"]): lifted and calm name the group, elsewhere and plain do not. calm has no label,
    so its name is its id; sorted by name, case folded: "calm" < "lifted" → [{calm, calm}, {lifted, Lifted}].
    bone_pose_states([]) → [] (no groups, nothing to offer).
[2] _with_preview_states({groups: [{id sample_group}]}) carries the list of [1] as ``states``; None stays None.
[3] GET …/base-body/state-motion?state=lifted — the bare base with only that state:
      gravity .35 × .5 = .175, rest_deg 12 (inside ±45), length 1.5;
      no clothing: the free-text coat would scale gain 1 × .5 = .5 and max_deg 30 × .5 = 15 — the preview keeps
      gain 1 and max_deg 30 (the base body is bare, like ``plain_body.extension.motion``).
    The character's own motion (worldmap/model3d, clothing applied, no state active) has gain .5 — so the preview is
    not the outfit's motion. calm → rest_deg −6.
[4] state=plain (no bone pose) and state=missing → 404; an unknown character → 404.
[5] Nothing is stored: the profile and the filter definitions are the same before and after every preview call.
[6] The route is admin-only (``require_admin`` among its dependencies) and a GET.
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
    with tempfile.TemporaryDirectory(prefix='base-state-preview-') as tmp:
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
        from app.core import db, config, prompt_filters, extension_rig
        db.init_schema()
        config.load(paths.get_config_path(), instance_path=instance / 'config.json')
        from app.plugins.registry import RigSpec
        from dataclasses import asdict
        group = asdict(RigSpec.parse({'id': 'sample_group', 'op': 'pair_protrusion',
                                      'chains': [[{'bone': 'SampleBone', 'parent': 'Hips'}]],
                                      'max_deg': 30, 'rest_max_deg': 45, 'freetext_clothing_gain': .5}))
        shared = root / 'shared-filters.json'
        shared.write_text('{"filters": []}')
        states = [
            {'id': 'lifted', 'label': 'Lifted', 'bone_pose': {'sample_group': {'rest_deg': 12, 'gravity': .5, 'length': 1.5}}},
            {'id': 'calm', 'label': '', 'bone_pose': {'sample_group': {'rest_deg': -6}}},
            {'id': 'elsewhere', 'label': 'Elsewhere', 'bone_pose': {'other_group': {'rest_deg': 20}}},
            {'id': 'plain', 'label': 'Plain'},
        ]
        with patch.object(extension_rig, 'rig_groups_for', return_value=[group]), \
                patch.object(extension_rig, 'declared_motion_groups', return_value=[
                    {'id': 'sample_group', 'defaults': {'rest_max_deg': 45}}]), \
                patch.object(prompt_filters, '_SHARED_FILE', shared):
            from app.routes.admin_settings import _prompt_filters_save_sync
            from app.models.character import get_character_profile, save_character_profile
            from fastapi import HTTPException
            check(save_character_profile('sample', {'template': 'human-default', 'outfit_description': 'a long coat'},
                                         create_new=True), 'profile fixture')
            for state in states:
                _prompt_filters_save_sync(None, state)
            from app.routes import figure

            # [1]
            check(prompt_filters.bone_pose_states(['sample_group']) == [
                {'id': 'calm', 'label': 'calm'}, {'id': 'lifted', 'label': 'Lifted'}],
                '[1] the states that move the group, by name; a missing label is the id')
            check(prompt_filters.bone_pose_states([]) == [], '[1] no groups → nothing offered')
            # [2]
            extension = figure._with_preview_states({'groups': [{'id': 'sample_group'}]})
            check(extension['states'] == [{'id': 'calm', 'label': 'calm'}, {'id': 'lifted', 'label': 'Lifted'}],
                  '[2] plain_body.extension carries the states')
            check(figure._with_preview_states(None) is None, '[2] no extension state stays None')

            before_profile = get_character_profile('sample')
            before_filters = prompt_filters.load_filters()
            # [3]
            answer = figure.base_state_motion('sample', 'lifted', {'role': 'admin'})
            values = answer['motion']['groups']['sample_group']
            check(answer['state'] == 'lifted', '[3] answers the state it was asked for')
            check(abs(values['gravity'] - .175) < 1e-12 and values['rest_deg'] == 12 and values['length'] == 1.5,
                  '[3] gravity .35 × .5 = .175, rest_deg 12, length 1.5')
            check(values['gain'] == 1 and values['max_deg'] == 30, '[3] bare: no clothing factor (gain 1, max_deg 30)')
            worn = extension_rig.motion_payload('sample')['groups']['sample_group']
            check(abs(worn['gain'] - .5) < 1e-12 and abs(worn['max_deg'] - 15) < 1e-12,
                  '[3] the outfit motion has the coat (gain .5, max_deg 15) — the preview is not it')
            check(figure.base_state_motion('sample', 'calm', {'role': 'admin'})['motion']['groups']['sample_group']['rest_deg'] == -6,
                  '[3] calm → rest_deg −6')
            # [4]
            for name, state in (('sample', 'plain'), ('sample', 'missing'), ('nobody', 'lifted')):
                try:
                    figure.base_state_motion(name, state, {'role': 'admin'})
                except HTTPException as exc:
                    check(exc.status_code == 404, f'[4] {name}/{state} → 404')
                else:
                    check(False, f'[4] {name}/{state} → 404')
            # [5]
            check(get_character_profile('sample') == before_profile, '[5] the profile is unchanged')
            check(prompt_filters.load_filters() == before_filters, '[5] the state definitions are unchanged')
            # [6]
            from app.core.auth_dependency import require_admin
            route = next(r for r in figure.router.routes if r.path.endswith('/base-body/state-motion'))
            check(route.methods == {'GET'} and any(d.call is require_admin for d in route.dependant.dependencies),
                  '[6] GET, admin-only')
    if failures:
        print(f'\nFAILED ({len(failures)})')
        sys.exit(1)
    print('\nALL OK')


if __name__ == '__main__':
    main()
