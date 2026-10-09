"""P4 state composition and E3, in temporary storage.

Usage: .venv/bin/python scripts/smoke_extension_rig_p4.py
Hand derivation: package gravity .35 * state .5 * state .8 = .14;
frequency 2.2 * 2 * .5 = 2.2; zeta .7 * .5 * 2 = .7.
Clothing gain .5 precedes state gain 3, so min(1,.5*3)=1.
Flatten .4*4=1.6 clamps to 1; spill .2*3=.6.
Rest angles 12 and 24 compose to max=24. Missing gain preserves 1;
explicit gain=0 yields 0. State flatten/spill/gain multiply then clamp at 1.
State angles accept [-180,180] independently of the fixture rest limit 45. Legacy fork files: 6 folders x 3
files plus 4 T-pose views = 22 unreachable files, all must be removed.
An active state changes motion only; mesh signatures stay outfit-only.
Two unchanged polls require zero definition and profile reloads on the second.
Finite state factors 1e308 squared overflow; effective limits require frequency
20, damping 10 and gravity 10, with every payload number finite.
"""
import io
import json
import zipfile
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check(ok, label):
    assert ok, label
    print('PASS', label)


def main():
    with tempfile.TemporaryDirectory(prefix='extension-p4-') as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import db, config, prompt_filters, extension_rig, model_refs
        db.init_schema()
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        from app.plugins.registry import RigSpec
        from dataclasses import asdict
        group = asdict(RigSpec.parse({'id': 'sample_group', 'op': 'pair_protrusion',
            'chains': [[{'bone': 'SampleBone', 'parent': 'Hips'}]],
            'flatten': .4, 'spill': .2, 'zeta': .7, 'rest_max_deg': 45}))
        filters = [
            {'id': 'first', 'bone_pose': {'sample_group': {'rest_deg': 12, 'gravity': .5, 'freq': 2, 'zeta': .5, 'length': 1.5, 'girth': .8}}},
            {'id': 'second', 'condition': 'sample>0', 'bone_pose': {'sample_group': {'rest_deg': 24, 'gravity': .8, 'freq': .5, 'zeta': 2, 'length': .5, 'girth': 1.5}}},
        ]
        shared = root / 'shared-filters.json'
        shared.write_text('{"filters": []}')
        with patch.object(extension_rig, 'rig_groups_for', return_value=[group]),                 patch.object(extension_rig, 'declared_motion_groups', return_value=[
                    {'id': 'sample_group', 'defaults': {'rest_max_deg': 45}}]),                 patch.object(prompt_filters, '_SHARED_FILE', shared):
            from app.routes.admin_settings import (_prompt_filters_save_sync,
                                                   _prompt_filters_move_sync)
            from app.core.content_io import export_states_to_zip, import_states_from_zip
            from app.models.character import (get_character_profile, save_character_profile,
                                              get_character_dir, set_character_pos)
            from app.core.keyed_lock import keyed_lock
            from fastapi import HTTPException
            check(save_character_profile('sample', {'template': 'human-default'}, create_new=True), 'profile fixture')
            def change(**fields):
                with keyed_lock('character_profile', 'sample'):
                    profile = get_character_profile('sample')
                    profile.update(fields)
                    check(save_character_profile('sample', profile), 'profile update')
            def motion():
                return extension_rig.motion_payload('sample')
            def values():
                return motion()['groups']['sample_group']
            for state in filters:
                _prompt_filters_save_sync(None, state)
            held = get_character_profile('sample')
            with patch.object(prompt_filters, '_load_shared', wraps=prompt_filters._load_shared) as sr, patch.object(prompt_filters, '_load_world', wraps=prompt_filters._load_world) as wr, patch('app.models.character.get_character_profile', side_effect=AssertionError('profile reload')):
                extension_rig.motion_payload('sample', profile=held)
                check(sr.call_count == wr.call_count == 1, 'first poll: one shared and one world definition read, zero profile reloads')
                sr.reset_mock(); wr.reset_mock()
                extension_rig.motion_payload('sample', profile=held)
                check(sr.call_count == wr.call_count == 0, 'unchanged second poll: zero definition/profile reloads')
            combined = extension_rig.motion_payload('sample', preview_states=['first','second'])['groups']['sample_group']
            check(abs(combined['length']-.75)<1e-12 and abs(combined['girth']-1.2)<1e-12, 'state extent multiplies: 1.5*.5=.75, .8*1.5=1.2')
            check(motion()['rev'] == motion()['rev'], 'unchanged consecutive motion polls have stable revision')
            poll_base = extension_rig.motion_payload('sample', profile=held)
            held['active_conditions'] = [{'name': 'first'}]
            with patch('app.models.character.get_character_profile', side_effect=AssertionError('profile reload')):
                check(extension_rig.motion_payload('sample', profile=held)['rev'] != poll_base['rev'], 'held-profile tag toggle changes revision without reload')
            held['active_conditions'] = []
            filters[1]['condition'] = 'sample>0 AND NOT is_sleeping'
            _prompt_filters_save_sync(None, filters[1])
            held['status_effects'] = {'sample': 0}
            with patch('app.models.character.get_character_profile', side_effect=AssertionError('profile reload')):
                poll_base = extension_rig.motion_payload('sample', profile=held)
                held['status_effects']['sample'] = 1
                check(extension_rig.motion_payload('sample', profile=held)['rev'] != poll_base['rev'], 'held-profile expression flip changes revision without reload')
            filters[1]['condition'] = 'sample>0'
            _prompt_filters_save_sync(None, filters[1])
            for connection in db._connections.values():
                connection.close()
            db._connections.clear()
            paths.init(root / 'other-world')
            db.init_schema()
            check(prompt_filters.load_filters() == [], 'world switch invalidates filter definitions')
            for connection in db._connections.values():
                connection.close()
            db._connections.clear()
            paths.init(root / 'world')
            check(len(prompt_filters.load_filters()) == 2, 'returning world restores its definitions')
            base = motion()
            change(active_conditions=[{'name': 'first'}, {'name': 'second'}])
            result = motion()
            check(values()['rest_deg'] == 24, 'maximum of present rest angles')
            stored_preview = get_character_profile('sample')
            forced = extension_rig.motion_payload('sample', preview_states=['first'])
            check(forced['groups']['sample_group']['rest_deg'] == 12, 'preview replaces active states')
            check(extension_rig.motion_payload('sample', preview_states=[])['groups']['sample_group']['rest_deg'] == 0, 'none preview has no state')
            check(get_character_profile('sample') == stored_preview and motion() == result, 'preview never persists')
            from app.routes.characters import get_character_model3d
            from starlette.requests import Request
            request = Request({'type': 'http', 'headers': []})
            with patch('app.core.auth_dependency.get_current_user', return_value={'role': 'player'}):
                check(get_character_model3d('sample', request)['motion'] == result, 'current live read needs no preview admin check')
                for selection in ('first', 'none', ''):
                    try:
                        get_character_model3d('sample', request, selection)
                    except HTTPException as exc:
                        check(exc.status_code == 403, 'non-admin preview rejected before reading data')
                    else:
                        raise AssertionError('player preview accepted')
            with patch('app.core.auth_dependency.get_current_user', return_value={'role': 'admin'}):
                check(get_character_model3d('sample', request, 'first')['motion']['groups']['sample_group']['rest_deg'] == 12, 'admin route selects preview state')
                check(get_character_model3d('sample', request, 'none')['motion']['groups']['sample_group']['rest_deg'] == 0, 'admin route none has no state')
                check(get_character_model3d('sample', request, 'first,second')['motion'] == result, 'comma list composes preview states')
            check(get_character_profile('sample') == stored_preview and motion() == result, 'route preview never persists')
            check(abs(values()['gravity'] - .14) < 1e-12, 'gravity .35 x .5 x .8')
            check(values()['freq_hz'] == 2.2 and values()['zeta'] == .7, 'frequency and damping products')
            check(result['rev'] != base['rev'], 'tag on changes revision')
            change(active_conditions=[])
            check(motion()['rev'] == base['rev'], 'tag off restores revision')
            # Use an expression whose truth is controlled independently of either state id.
            filters[1]['condition'] = 'condition:signal'
            _prompt_filters_save_sync(None, filters[1])
            base = motion()
            change(active_conditions=[{'name': 'signal'}])
            check(values()['rest_deg'] == 24 and motion()['rev'] != base['rev'], 'expression on changes revision')
            check(prompt_filters.collect_image_modifiers('sample') == ([], []), 'pose-only state needs no image directive')
            change(active_conditions=[])
            check(motion()['rev'] == base['rev'], 'expression off restores revision')
            from app.core.game_time import GameTime
            from app.core.activity_engine import cleanup_expired_conditions
            change(active_conditions=[{'name': 'first', 'started_at': 'Y0001-D001T00:00:00', 'duration_hours': 1}])
            check(values()['rest_deg'] == 12, 'timed state activates')
            with patch('app.core.activity_engine.game_time', return_value=GameTime.parse('Y0001-D001T02:00:00')):
                check(cleanup_expired_conditions('sample') == 1, 'expiry removes tag')
            check(motion()['rev'] == base['rev'] and values()['rest_deg'] == 0, 'expiry restores neutral motion')
            change(active_conditions=[{'name': 'first'}])
            filters[0]['enabled'] = False
            _prompt_filters_save_sync(None, filters[0])
            check(values()['rest_deg'] == 0, 'disabled tag ignored')
            filters[0]['enabled'] = True
            filters[0]['bone_pose']['sample_group'].update(flatten=4, spill=3)
            _prompt_filters_save_sync(None, filters[0])
            check(values()['flatten'] == 1 and abs(values()['spill'] - .6) < 1e-12, 'flatten and spill multiply and clamp')
            check(values()['gain'] == 1, 'absent gain inherits')
            absent = motion()['rev']
            filters[0]['bone_pose']['sample_group']['gain'] = 0
            _prompt_filters_save_sync(None, filters[0])
            check(values()['gain'] == 0 and motion()['rev'] != absent, 'explicit zero differs from absent')
            filters[0]['bone_pose']['sample_group']['freq'] = 0
            _prompt_filters_save_sync(None, filters[0])
            check(values()['freq_hz'] == 0, 'explicit zero frequency retained')
            filters[0]['bone_pose']['sample_group'].update(freq=1, gain=3)
            _prompt_filters_save_sync(None, filters[0])
            from app.models import inventory
            item = inventory.add_item('Cover', category='outfit_piece', item_id='p4_cover',
                outfit_piece={'slots': ['top'], 'covers': ['top'], 'motion_damping': .5})
            from types import SimpleNamespace
            with patch('app.core.body_slots.slots_for_character', return_value=[
                    SimpleNamespace(id='slot', rig=SimpleNamespace(id='sample_group'), covered_by=['top'])]):
                change(equipped_pieces={'top': item['id']})
                check(values()['gain'] == 1, 'state after clothing: .5 x 3 clamps to 1')
            change(equipped_pieces={})
            filters[0]['bone_pose']['sample_group'].update(freq=1e308, zeta=1e308, gravity=1e308)
            filters[1]['bone_pose']['sample_group'].update(freq=1e308, zeta=1e308, gravity=1e308)
            for state in filters:
                _prompt_filters_save_sync(None, state)
            change(active_conditions=[{'name': 'first'}, {'name': 'second'}])
            extreme = values()
            check(extreme['freq_hz'] == 20 and extreme['zeta'] == 10 and extreme['gravity'] == 10, 'composed overflow saturates at effective limits')
            json.dumps(motion(), allow_nan=False)
            filters[0]['bone_pose']['sample_group'].update(freq=1, zeta=.5, gravity=.5)
            filters[1]['bone_pose']['sample_group'].update(freq=.5, zeta=2, gravity=.8)
            for state in filters:
                _prompt_filters_save_sync(None, state)
            change(active_conditions=[{'name': 'first'}])
            expected = filters[0]['bone_pose']
            check(next(f for f in prompt_filters._load_world() if f['id'] == 'first')['bone_pose'] == expected, 'save/load round trip')
            _prompt_filters_move_sync('first', None, {'target': 'shared'})
            check(next(f for f in prompt_filters._load_shared() if f['id'] == 'first')['bone_pose'] == expected, 'move world to shared')
            _prompt_filters_move_sync('first', None, {'target': 'world'})
            check(next(f for f in prompt_filters._load_world() if f['id'] == 'first')['bone_pose'] == expected, 'move shared to world')
            packed = export_states_to_zip()
            check(import_states_from_zip(packed, replace_all=True)['filters_imported'] == 2, 'pack export/import')
            check(next(f for f in prompt_filters._load_world() if f['id'] == 'first')['bone_pose'] == expected, 'pack retains sparse values')
            from app.routes.content_packs import _dispatch_install
            check(_dispatch_install('states', packed)['filters_imported'] == 2, 'marketplace pack installation carries bone_pose')
            # Unloaded groups survive storage and never become runtime groups.
            _prompt_filters_save_sync(None, {'id': 'unknown', 'bone_pose': {'unloaded_group': {'gain': 0}}})
            change(active_conditions=[{'name': 'unknown'}])
            check(set(motion()['groups']) == {'sample_group'} and values()['gain'] == 1, 'unloaded group ignored')
            for angle in (150, -60):
                _prompt_filters_save_sync(None, {'id': 'signed_rest', 'bone_pose': {'sample_group': {'rest_deg': angle}}})
                for limit in (180, 45):
                    change(model3d_opts={'extension_motion': {'sample_group': {'rest_max_deg': limit}}})
                    resolved = extension_rig.motion_payload('sample', preview_states=['signed_rest'])['groups']['sample_group']
                    check(resolved['rest_deg'] == max(-limit, min(limit, angle)) and resolved['rest_max_deg'] == limit, 'signed rest and effective character limit reach payload')
            for bad in (None, [], {'sample_group': {'length': .49}}, {'sample_group': {'girth': 2.01}}, {'sample_group': {'length': True}}, {'sample_group': {'axis_gain': [1, 1, .2]}}, {'sample_group': {'rest_deg': 181}},
                        {'sample_group': {'rest_deg': -181}},
                        {'sample_group': {'rest_deg': float('nan')}},
                        {'sample_group': {'gain': -1}}, {'sample_group': {'gain': True}},
                        {'sample_group': {'gravity': float('nan')}},
                        {'sample_group': {'freq': float('inf')}}, {'sample_group': {'unknown': 1}}, {'sample_group': {'straighten_deg': 60}}, {'sample_group': {'freetext_clothing_gain': .5}},
                        {'sample_group': {'gain': 10**500}}):
                try:
                    _prompt_filters_save_sync(None, {'id': 'invalid', 'bone_pose': bad})
                except HTTPException as exc:
                    check(exc.status_code == 400, 'invalid state rejected')
                else:
                    raise AssertionError('invalid bone_pose accepted')
            # A malformed imported state cannot partially replace valid state rows.
            with zipfile.ZipFile(io.BytesIO(packed)) as archive:
                entries = json.loads(archive.read('db/prompt_filters.json'))
                manifest = archive.read('manifest.json')
            entries.append({'id': 'bad_import', 'bone_pose': {'sample_group': {'gain': -1}}})
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('manifest.json', manifest)
                archive.writestr('db/prompt_filters.json', json.dumps(entries))
            stored = prompt_filters._load_world()
            try:
                import_states_from_zip(stream.getvalue(), replace_all=True)
            except ValueError:
                check(prompt_filters._load_world() == stored, 'invalid pack rolls back atomically')
            else:
                raise AssertionError('invalid imported state accepted')
            # Migration is idempotent and preserves rows created under P3.
            with db.transaction() as conn:
                conn.execute('ALTER TABLE prompt_filters DROP COLUMN bone_pose')
            db.init_schema()
            db.init_schema()
            check(next(f for f in prompt_filters._load_world() if f['id'] == 'first')['bone_pose'] == {}, 'legacy schema gains empty JSON column')
            for state in filters:
                state['image_modifier'] = 'bright colors'
                _prompt_filters_save_sync(None, state)
            change(active_conditions=[{'name': 'first'}])
            neutral = model_refs.current_outfit_state('sample')[2]
            check('-s' not in neutral, 'mesh signature neutral while state active')
            check('bright colors' in prompt_filters.apply_image_modifiers('sample', 'plain'), 'ordinary image modifier preserved')
            refs = get_character_dir('sample') / 'model_refs'
            calls = []
            def generate(*args, **kwargs):
                calls.append(kwargs)
                path = Path(str(kwargs['output_stem']) + '.png')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
                return path
            with (
                patch('app.core.expression_regen.generate_expression_image', side_effect=generate),
                patch.object(model_refs, 'enabled_tpose_views', return_value=('back', 'left', 'right')),
                patch.object(model_refs, 'is_humanoid', return_value=True),
            ):
                model_refs.generate_model_ref_images('sample', kinds=('tpose', 'pose'), force=True)
            mesh_calls = [call for call in calls if call['image_use_case'].startswith('tpose')]
            check(len(mesh_calls) == 4 and all(not call['apply_state_modifiers'] for call in mesh_calls), 'all four mesh views exclude image modifiers')
            check(all(str(call['output_stem']).endswith(neutral) for call in mesh_calls), 'all mesh views use neutral signature')
            pose_call = next(call for call in calls if call['image_use_case'] == 'outfit')
            check(pose_call['apply_state_modifiers'] and '-p' in str(pose_call['output_stem']), 'ordinary pose retains state signature and modifier')
            check(all('-s' not in path.name for path in refs.iterdir()), 'no retired fork file generated')
            def transition(*args, **kwargs):
                if kwargs['image_use_case'] == 'tpose':
                    change(active_conditions=[])
                else:
                    expected_sig = model_refs.pose_reference_signature('sample', neutral)
                    check(str(kwargs['output_stem']).endswith(expected_sig), 'pose key captured after preceding render')
                    change(active_conditions=[{'name': 'first'}])
                    check(prompt_filters.apply_image_modifiers('sample', 'plain') == 'plain', 'pose prompt uses pinned neutral snapshot')
                return generate(*args, **kwargs)
            with patch('app.core.expression_regen.generate_expression_image', side_effect=transition), patch.object(model_refs, 'enabled_tpose_views', return_value=()), patch.object(model_refs, 'is_humanoid', return_value=True):
                for explicit in ({}, {'pieces': {}, 'items': [], 'signature': neutral}):
                    change(active_conditions=[{'name': 'first'}])
                    model_refs.generate_model_ref_images('sample', kinds=('tpose', 'pose'), force=True, **explicit)
            calls.clear()
            with (
                patch('app.core.expression_regen.generate_expression_image', side_effect=generate),
                patch.object(model_refs, 'enabled_tpose_views', return_value=()),
                patch.object(model_refs, 'is_humanoid', return_value=True),
            ):
                model_refs.generate_model_ref_images('sample', kinds=('tpose', 'pose'), force=True,
                                                     pieces={}, items=[], signature=neutral)
            check(not calls[0]['apply_state_modifiers'] and str(calls[0]['output_stem']).endswith(neutral),
                  'explicit combination mesh input stays neutral')
            check(calls[1]['apply_state_modifiers'] and '-p' in str(calls[1]['output_stem']),
                  'explicit ordinary pose retains state identity and modifier')
            calls.clear()
            with (
                patch('app.core.expression_regen.generate_expression_image', side_effect=generate),
                patch.object(model_refs, 'is_humanoid', return_value=False),
            ):
                model_refs.generate_model_ref_images('sample', kinds=('tpose',), force=True)
            check(len(calls) == 1 and calls[0]['image_use_case'] == 'tpose_animal'
                  and not calls[0]['apply_state_modifiers'] and str(calls[0]['output_stem']).endswith(neutral), 'animal mesh input neutral')
            from app.core import model3d, outfit_batch, outfit_cache_gc as gc
            meshes = model3d.get_model3d_dir('sample')
            meshes.mkdir(parents=True, exist_ok=True)
            fork = neutral + '-sdeadbeef'
            old_files = []
            for folder in (meshes, meshes / 'low', meshes / 'raw', meshes / 'prerig',
                           meshes / 'low/raw', meshes / 'low/prerig'):
                folder.mkdir(parents=True, exist_ok=True)
                for ext in ('.glb', '.json', '.png'):
                    path = folder / (fork + ext)
                    path.write_text(json.dumps({'pieces': {}, 'items': []}) if ext == '.json' else 'fixture')
                    old_files.append(path)
            for kind in ('tpose', 'tpose_back', 'tpose_left', 'tpose_right'):
                path = refs / f'{kind}_{fork}.png'
                path.write_bytes(b'fixture')
                old_files.append(path)
            check(model3d.find_model3d('sample') is None and model3d.find_model3d('sample', fork) is None, 'only fork exists: exact never serves it')
            check(model3d.find_model3d_serving('sample') == (None, ''), 'only fork exists: nearest never serves it')
            check(model3d.find_model3d_serving_tier('sample', 'low') == (None, '', ''), 'only fork exists: tier never serves it')
            check(fork not in outfit_batch.mesh_signatures('sample') and fork not in outfit_batch.ref_signatures('sample'), 'enumeration excludes forks')
            check(model_refs.find_ref_image('sample', 'tpose', fork) is None, 'explicit fork T-pose rejected')
            check(model3d.generate_for_current_outfit('sample', signature=fork)['error'] == 'state_fork_retired', 'generation rejects explicit fork')
            check(model3d.fetch_job_for_current_outfit('sample', 'old-job', signature=fork)['status'] == 'invalid', 'job retrieval rejects explicit fork')
            try:
                model3d.save_uploaded_model('sample', 'model.glb', b'fixture', rig='mixamo', signature=fork)
            except ValueError:
                check(True, 'upload rejects explicit fork')
            else:
                raise AssertionError('fork upload accepted')
            from app.core.improvements.types import subjects
            check(not subjects.character_model_pending('sample'), 'Improvements pending check remains usable')
            from app.core.improvements.types.mesh_from_tpose import MeshFromTpose
            from app.core.improvements.types.extension_rig_rebuild import ExtensionRigRebuild
            from app.core.improvements.base import Candidate
            candidate = Candidate('sample:' + fork, 'Old fork')
            check(MeshFromTpose().is_done(candidate, {}), 'persisted mesh candidate retires without retry')
            try:
                MeshFromTpose().apply(candidate, {'backend': ''}, 'test')
            except RuntimeError:
                check(True, 'persisted mesh candidate cannot regenerate fork')
            else:
                raise AssertionError('retired candidate applied')
            check(ExtensionRigRebuild().find_candidates({'character': 'sample'}) == [], 'fork-only cache offers no rig rebuild candidate')
            check(model3d.tier_variant(meshes / (fork + '.glb'), 'low') is None, 'direct tier lookup excludes fork')
            try:
                subjects.generate_character_model('sample', '', fork)
            except RuntimeError:
                check(True, 'stale Improvements candidate rejected')
            else:
                raise AssertionError('stale candidate generated')
            from app.core.character_io import export_character_to_zip, import_character_from_zip
            keep = [meshes / (neutral + '.glb'), refs / ('pose_' + neutral + '-p12345678.png')]
            for path in keep:
                path.write_bytes(b'fixture')
            charpack = export_character_to_zip('sample')
            with zipfile.ZipFile(io.BytesIO(charpack)) as archive:
                names = archive.namelist()
                check(not any('-sdeadbeef' in name for name in names), 'character export excludes retired files and companions')
                check(all('files/' + str(path.relative_to(get_character_dir('sample'))) in names for path in keep), 'character export keeps neutral and ordinary pose references')
                incoming = {name: archive.read(name) for name in names}
            incoming['files/model3d/low/raw/' + fork + '.json'] = b'{}'
            incoming['files/model_refs/tpose_' + fork + '.png'] = b'fixture'
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                for name, data in incoming.items():
                    archive.writestr(name, data)
            import_character_from_zip(stream.getvalue(), overwrite=True)
            check(not any('-sdeadbeef' in path.name for path in get_character_dir('sample').rglob('*')), 'character import excludes retired files and companions')
            check(all(path.exists() for path in keep), 'character import retains valid files')
            # Recreate the GC fixture removed by the pack replacement.
            for path in old_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}' if path.suffix == '.json' else 'fixture')
            for path in keep:
                path.unlink()
            report = gc.verify_cache('sample')
            check(fork in report['stale_signatures'], 'GC marks reachable-base forks unreachable')
            check(gc.purge_stale('sample', [fork])['deleted_files'] >= 22, 'GC deletes forks and all derivatives')
            check(all(not path.exists() for path in old_files), 'no fork derivative survives')
            # Worldmap and metadata transport state changes without mesh identity changes.
            from scripts.smoke_extension_rig_p0 import glb
            from app.core.rig_contract import BASE_JOINT_NAMES
            path = meshes / (neutral + '.glb')
            path.write_bytes(glb(['mixamorig:' + name for name in BASE_JOINT_NAMES]))
            set_character_pos('sample', 0, 0)
            from app.core.world_ops import build_worldmap_payload
            def row():
                return next(r for r in build_worldmap_payload(show_all=True)['characters'] if r['name'] == 'sample')
            before = row()
            change(active_conditions=[])
            after = row()
            check(before['motion']['rev'] != after['motion']['rev'], 'worldmap reflects state motion revision')
            check((before['model_sig'], before['model_rev']) == (after['model_sig'], after['model_rev']), 'state toggle keeps mesh identity')
            check(after['motion'] == model3d.get_model3d_info('sample')['motion'], 'metadata and worldmap motion parity')
        print('P4 smoke passed')


if __name__ == '__main__':
    main()
