#!/usr/bin/env python3
"""Hand-derived bindings: seat(cap 3), lie(cap 2), stand(cap 1).

Actions sit(solo seat), sleep(lie), pair(two-person lie), cook(stand).
Seat excludes sit: expected sit=[], sleep=[lie], pair=[lie], cook=[stand].
Removing the exclusion enables sit on seat; lowering lie capacity to one only
removes pair. Combined actions use the first phase group even if later phases
have other groups. Missing places warn; unknown exclusion IDs error.
Usage: .venv/bin/python scripts/smoke_prop_action_derived.py
"""
import copy
from pathlib import Path
import sys
import tempfile
from uuid import NAMESPACE_URL, uuid5
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory(prefix='prop-derived-') as root:
    paths.init(root)
    paths.init_instance(Path(root) / 'instance')
    from app.core.prop_actions import derive_bindings, validate_document
    from app.core.prop_action_migration import normalize_import
    from app.core import props
    poses = {'sit': {'group': 'seat'}, 'nap': {'group': 'lie'},
             'duo': {'group': 'lie', 'solo': False}, 'cook': {'group': 'stand'}}
    catalogs = dict(poses=poses, groups={g: {'default': k} for g, k in
                    [('seat', 'sit'), ('lie', 'nap'), ('stand', 'cook')]}, stats=set(), conditions=set())
    actions = [dict(id=i, name=i, description='', enabled=True, ability=a, pose_key=p,
                    participants=n, presence='any', interrupt_on_presence_change=False,
                    phases=[], requirements=[], effects=[]) for i, a, p, n in
               [('sit', 'pose', 'sit', 1), ('sleep', 'sleep', 'nap', 1),
                ('pair', 'pair', 'duo', 2), ('cook', 'pose', 'cook', 1)]]
    variant = dict(uid='11111111-1111-4111-8111-111111111111', stem='model', active=True,
                   markers=[dict(id=g, group=g, capacity=c, at=[.5, .5, .5])
                            for g, c in [('seat', 3), ('lie', 2), ('stand', 1)]])
    variant['markers'][0]['exclude_actions'] = ['sit']
    document = dict(id='fixture', actions=actions, model_variants=[variant])
    def bindings(doc=document, v=variant):
        return {b['action_id']: b['marker_ids'] for b in derive_bindings(doc, v, poses=poses)}
    before = copy.deepcopy(document)
    assert bindings() == dict(sit=[], sleep=['lie'], pair=['lie'], cook=['stand'])
    assert document == before
    issues = validate_document(document, catalogs=catalogs)
    assert [(i['message'], i['severity']) for i in issues] == [('No matching place on any variant', 'warning')]
    variant['markers'][0]['exclude_actions'] = []
    assert bindings()['sit'] == ['seat']
    variant['markers'][1]['capacity'] = 1
    assert bindings()['pair'] == [] and bindings()['sleep'] == ['lie']
    combined = copy.deepcopy(actions[3])
    combined.update(ability='combined', phases=[dict(id=str(i), label=k, duration_game_s=1, pose_key=k)
                                              for i, k in enumerate(['cook', 'sit'])])
    assert derive_bindings(dict(actions=[combined]), variant, poses=poses)[0]['marker_ids'] == ['stand']
    variant['markers'][0]['exclude_actions'] = ['missing']
    assert any(i['severity'] == 'error' and i['code'] == 'invalid_action_reference'
               for i in validate_document(document, catalogs=catalogs))
    variant['markers'][0]['exclude_actions'] = []
    revision = props._document_revision(document)
    variant['markers'][0]['exclude_actions'] = ['sit']
    assert props._document_revision(document) != revision
    variant['markers'][0]['exclude_actions'] = []
    variant['action_bindings'] = [dict(action_id='sit', supported=False)]
    migrated = normalize_import(document, catalogs=catalogs)
    assert 'action_bindings' not in migrated['model_variants'][0]
    assert migrated['model_variants'][0]['markers'][0]['exclude_actions'] == ['sit']
    assert normalize_import(migrated, catalogs=catalogs) == migrated
    legacy_id = str(uuid5(NAMESPACE_URL, 'anima:prop-action:fixture:sit'))
    actions[0]['id'] = legacy_id
    variant['action_bindings'] = [dict(action_id=legacy_id, supported=False)]
    assert not normalize_import(document, catalogs=catalogs)['model_variants'][0]['markers'][0]['exclude_actions']
    actions[0].update(id=str(uuid5(NAMESPACE_URL, 'anima:prop-action:fixture:removed')), ability='sleep', pose_key='removed')
    variant['action_bindings'] = [dict(action_id=actions[0]['id'], supported=False)]
    assert not normalize_import(document, catalogs=catalogs)['model_variants'][0]['markers'][1].get('exclude_actions')
    assert any(i['path'].endswith('.action_bindings') and i['severity'] == 'error'
               for i in validate_document(document, catalogs=catalogs))
    # Startup prerequisites use the normal store and may rewrite old variants.
    # Their reads must not erase an explicit false decision before conversion.
    import json
    from unittest.mock import patch
    from app.core.prop_action_migration import prepare_runtime
    directory = Path(root) / 'props' / 'fixture'
    directory.mkdir(parents=True)
    startup = copy.deepcopy(before)
    startup['model_variants'][0]['markers'][0]['exclude_actions'] = []
    startup['model_variants'][0]['action_bindings'] = [dict(action_id='sit', supported=False)]
    (directory / 'sidecar.json').write_text(json.dumps(startup))
    def prerequisite():
        props.read_sidecar('fixture')
        return {}
    with patch('app.core.places_migration.migrate_places_once', side_effect=prerequisite), \
         patch('app.core.prop_field_migration.migrate_prop_fields_once', side_effect=prerequisite), \
         patch('app.core.place_group_migration.migrate_place_groups_once', side_effect=prerequisite), \
         patch('app.core.prop_action_engine.register_owner'), \
         patch('app.core.prop_action_migration._catalog_snapshot', return_value=catalogs), \
         patch('app.core.pose_catalog.get_catalog', return_value=poses):
        prepare_runtime()
    published = props.read_sidecar('fixture', read_only=True)
    assert published['model_variants'][0]['markers'][0]['exclude_actions'] == ['sit']
print('PASS: hand-derived groups, capacity, exclusions, first phase, warnings, revision and migration')
