"""Usage: .venv/bin/python scripts/smoke_base_part_unclothed.py

Ruling A49: the base body resolves its extension groups as UNCLOTHED — by the mesh variant its own inputs were
rendered for (``model3d.stored_mesh_variant``), never by the outfit the character wears — and a group whose build
found nothing gets a light with the reason instead of reading as simply active.

Synthetic fixture (no pack, no world): one slot ``slot`` of package ``fixture``, covered by the clothing slot
``bottom``, with a separate mesh part (switch ``switch``) that maps the rig ``chain`` (op ``appendage_chain``) and a companion
group ``companion`` (op ``attached_part_bone``, applies only with ``attributes.switch: on``). The token of the slot is
``|mesh:fixture.slot=on`` (``body_slots.mesh_variant_token``: ``|mesh:<package>.<slot>=on``). The profile has the
switch ON and WEARS a piece on ``bottom`` — so the worn outfit covers the slot.

Hand-derived expectations (``extension_rig.rig_groups_for``: part on → ``appendage_chain`` becomes
``attached_part`` and the switch keeps "on", so ``companion`` applies; part off → the switch reads "off", ``chain`` stays
``appendage_chain`` and ``companion`` drops out):

  [1] clothed profile, base model recording the token          → part on:  chain attached_part, companion present
  [2] the same profile, outfit model whose outfit covers the slot
      (its manifest recorded mesh_variant "")                   → part off: chain appendage_chain, no companion;
      a copy of the base's built record carries both part groups → ``_stale_part_groups`` = [chain, companion]
  [3] old base record without the key; its front sidecar recorded the token and the front PNG is the one the
      model was built from (sha256 equal)                        → on, as [1]
  [4] old base record whose front sidecar recorded "" (rendered before the switch was turned on)
                                                                 → off, as [2]; and a front re-rendered since
      (sha256 differs) with the token                            → off (its inputs are unknown — never claim it)
  [5] lights: the Kai-shaped record (op appendage_chain, status not_found, metric reason "no protrusion
      candidates") read with the base's current groups (attached_part) → yellow "Not built" with
      ``EXT_REASON_PART_DUE``; the same record when the base still resolves appendage_chain and its inputs predate
      the switch → yellow ``EXT_REASON_OLD_INPUTS``; a failed metric → red; an applied record → green; due_reason
      "groups" when the record's ops differ from the current ones.
  [6] ``model_extension_state`` of the stored base [1] reports chain attached_part, its light and due_reason
      "groups" against the Kai-shaped record — the reader the Base body tab polls.
  [2b] the validation context (``extension_rig.extension_bone_names``) holds G1, G2 AND C for the clothed
      profile — the companion bone of the part resolution must not be refused while a piece is worn.
  [7] collision: an outfit inheriting the base's capsule set keeps the body capsules and drops "chain:*" when its
      own record carries no built chain.

Fails on the old code, pinned to ab33142c515f2c678f8508a0c4c03f59bc9c8608 (main before A49): its
``_extension_groups_for`` dropped every part op from a base body and its readers took ``meta.get("mesh_variant")
or ""`` — for [1] the chain vanishes from the base, for [3] it stays ``appendage_chain``.
"""
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OLD = "ab33142c515f2c678f8508a0c4c03f59bc9c8608"

from app.core import paths  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core.db import init_schema
    init_schema()
    from app.core import body_slots as bs, extension_rig as er, model3d
    from app.core.model_refs import get_model_refs_dir
    from app.plugins.registry import BodySlotSpec, MeshPartSpec, Package, RigSpec

    attrs = {'switch': {'type': 'select', 'options': ['off', 'on']}}
    chain = RigSpec.parse(dict(id='chain', op='appendage_chain', chains=[[
        {'bone': 'mixamorig:G1', 'parent': 'Hips'}, {'bone': 'mixamorig:G2', 'parent': 'mixamorig:G1'}]]))
    companion = RigSpec.parse(dict(id='companion', op='attached_part_bone', applies_to={'attributes.switch': ['on']},
                              chains=[[{'bone': 'mixamorig:C', 'parent': 'Hips'}]]))
    part = dict(switch='switch', tpose_prompt='flat slot', rigs={'chain': {'params': {}, 'attribute_params': {}}})
    slot = BodySlotSpec('slot', 'fixture', covered_by=['bottom'], attributes=attrs, rigs=[chain, companion],
                        mesh_part=MeshPartSpec.parse(part, attrs, [chain, companion]))
    pkg = Package('fixture', Path(tmp), {}, body_slots=[slot])
    TOKEN = bs.mesh_variant_token(slot)
    assert TOKEN == '|mesh:fixture.slot=on'
    clothed = {'body_slots': {'slot': {'switch': 'on'}}, 'equipped_pieces': {'bottom': 'item_x'}}
    NAME = 'Fixture'

    def ops(meta, profile=clothed):
        variant = model3d.stored_mesh_variant(NAME, meta)
        return {g['id']: g['op'] for g in model3d._extension_groups_for(
            meta, er.rig_groups_for(NAME, profile, variant))}

    refs = get_model_refs_dir(NAME)
    refs.mkdir(parents=True, exist_ok=True)
    front = refs / 'tpose_basefix.png'
    front.write_bytes(b'front-v1')
    sha_v1 = hashlib.sha256(b'front-v1').hexdigest()

    def front_record(variant):
        record = {'equipped_pieces': {}}
        if variant is not None:
            record['mesh_variant'] = variant
        front.with_suffix('.json').write_text(json.dumps(record))

    ON = {'chain': 'attached_part', 'companion': 'attached_part_bone'}
    OFF = {'chain': 'appendage_chain'}
    with patch.object(bs, '_species_packages_for', return_value=[pkg]), \
            patch('app.plugins.registry.packages', return_value=[pkg]):
        # The fixture profile really is clothed over the slot: the worn outfit alone resolves the part off.
        assert not bs.is_slot_exposed(slot, clothed) and bs.mesh_part_active(slot, clothed)
        assert {g['id']: g['op'] for g in er.rig_groups_for(NAME, clothed)} == OFF

        # [1] base model recording the token.
        base_new = {'base': True, 'mesh_variant': TOKEN}
        assert ops(base_new) == ON, ops(base_new)

        # [2] outfit model covering the slot; its rebuild must take the base's built part off.
        outfit = {'source': 'base_body', 'base_signature': 'basefix', 'mesh_variant': ''}
        assert ops(outfit) == OFF, ops(outfit)
        base_record = {'status': 'applied', 'has_applied': True, 'attempted': True,
                       'group_ops': dict(ON), 'metrics': {'chain': {'status': 'applied'},
                                                          'companion': {'status': 'applied'}}}
        declarations = model3d._extension_groups_for(outfit, er.rig_groups_for(NAME, clothed, ''))
        assert model3d._stale_part_groups(base_record, declarations) == ['chain', 'companion']
        # The base itself keeps them (nothing stale), and a part that failed on the base is not in the bytes.
        assert model3d._stale_part_groups(base_record, model3d._extension_groups_for(
            base_new, er.rig_groups_for(NAME, clothed, TOKEN))) == []
        failed = {**base_record, 'metrics': {'chain': {'status': 'failed'}, 'companion': {'status': 'failed'}}}
        assert model3d._stale_part_groups(failed, declarations) == []
        # The covered variant of a base (and an outfit body) never carries a part op.
        assert ops({'base': True, 'base_variant': 'covered', 'mesh_variant': TOKEN}) == {}
        assert ops({'outfit_body': {'x': 1}, 'mesh_variant': TOKEN}) == {}
        # An outfit built FROM the covered variant (no base key) still builds the part where it leaves it exposed.
        assert ops({'source': 'base_body', 'base_variant': 'covered', 'mesh_variant': TOKEN}) == ON

        # The validation context names the bones of the part resolution too, whatever outfit is worn: a base
        # that shows the part (and its companion bone C) is not refused while the character is clothed.
        assert set(er.extension_bone_names(NAME, clothed)) == {'mixamorig:G1', 'mixamorig:G2', 'mixamorig:C'}

        # [3] old base record without the key, inputs rendered with the part.
        base_old = {'base': True, 'source_image': front.name, 'source_image_sha256': sha_v1}
        front_record(TOKEN)
        assert model3d.stored_mesh_variant(NAME, base_old) == TOKEN
        assert ops(base_old) == ON, ops(base_old)

        # [4] inputs from before the switch: off; a front rendered again since: unknown → off.
        front_record('')
        assert ops(base_old) == OFF, ops(base_old)
        front_record(None)
        assert ops(base_old) == OFF
        front_record(TOKEN)
        front.write_bytes(b'front-v2')
        assert model3d.stored_mesh_variant(NAME, base_old) == '' and ops(base_old) == OFF
        front.write_bytes(b'front-v1')
        # A record without a source hash, or a path instead of a file name, never derives.
        assert model3d.stored_mesh_variant(NAME, {'base': True, 'source_image': front.name}) == ''
        assert model3d.stored_mesh_variant(NAME, {'base': True, 'source_image': '../x.png',
                                                  'source_image_sha256': sha_v1}) == ''

        # [5] lights.
        kai = {'status': 'not_found', 'reason': 'chain: no protrusion candidates', 'attempted': True,
               'groups': ['chain'], 'group_ops': {'chain': 'appendage_chain'},
               'metrics': {'chain': {'reason': 'no protrusion candidates'}}}
        now_on = [{**g, 'enabled': True} for g in model3d._extension_groups_for(
            base_new, er.rig_groups_for(NAME, clothed, TOKEN))]
        lights = model3d.extension_group_lights(clothed, base_new, now_on, kai, TOKEN)
        assert lights['chain'] == {'light': 'yellow', 'state': model3d.EXT_STATE_NOT_BUILT,
                                   'reason': model3d.EXT_REASON_PART_DUE, 'detail': 'no protrusion candidates'}
        assert lights['companion']['light'] == 'yellow' and lights['companion']['reason'] == model3d.EXT_REASON_NEW_GROUP
        assert model3d.extension_groups_changed({'extension_rig': kai}, now_on)
        still_off = [{**g, 'enabled': True} for g in er.rig_groups_for(NAME, clothed, '')]
        lights = model3d.extension_group_lights(clothed, base_old, still_off, kai, '')
        assert lights['chain']['light'] == 'yellow' and lights['chain']['reason'] == model3d.EXT_REASON_OLD_INPUTS
        assert not model3d.extension_groups_changed({'extension_rig': kai}, still_off)
        switch_off = {'body_slots': {'slot': {'switch': 'off'}}}
        lights = model3d.extension_group_lights(switch_off, base_old, still_off, kai, '')
        assert lights['chain']['reason'] == model3d.EXT_REASON_SWITCH_OFF
        broken = {**base_record, 'status': 'applied',
                  'metrics': {'chain': {'status': 'failed', 'reason': 'fixture failure'}, 'companion': {'status': 'applied'}}}
        lights = model3d.extension_group_lights(clothed, base_new, now_on, broken, TOKEN)
        assert lights['chain'] == {'light': 'red', 'state': model3d.EXT_STATE_FAILED,
                                   'reason': model3d.EXT_REASON_FAILED, 'detail': 'fixture failure'}
        assert lights['companion']['light'] == 'green'
        lights = model3d.extension_group_lights(clothed, base_new, [{**now_on[0], 'enabled': False}], base_record,
                                                TOKEN)
        assert lights['chain']['light'] == 'grey'

        # [6] the reader the Base body tab polls, on a stored base [1] with the Kai-shaped record.
        mdir = model3d.get_model3d_dir(NAME)
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / 'basefix.glb').write_bytes(b'glTF')
        # The record's fingerprint is the one of the groups it was built with (appendage_chain, no overrides).
        kai_stored = {**kai, 'fingerprint': er.extension_rig_fingerprint(er.rig_groups_for(NAME, clothed, ''), {})}
        (mdir / 'basefix.json').write_text(json.dumps({**base_new, 'rig': 'mixamo', 'extension_rig': kai_stored}))
        with patch('app.models.character.get_character_profile', return_value=clothed), \
                patch.object(model3d, '_current_base', return_value=None):
            state = model3d.model_extension_state(NAME, 'basefix')
        assert state is not None
        assert {g['id']: g['op'] for g in state['groups']} == ON
        assert state['lights']['chain']['reason'] == model3d.EXT_REASON_PART_DUE
        assert state['due'] is True and state['due_reason'] == 'groups'

    # [7] the inherited capsule set.
    from app.core import collision
    capsules = [{'id': 'left_thigh', 'a': 'mixamorig:LeftUpLeg', 'b': 'mixamorig:LeftLeg', 'r': 0.1, 'region': 'leg'},
                {'id': 'chain:g1', 'a': 'mixamorig:G1', 'b': 'mixamorig:G2', 'r': 0.02, 'region': 'attached_part'}]
    scales = {'leg': 1.0}
    meta = {'source': 'base_body', 'base_model_sha256': 'b' * 64, 'base_signature': 'basefix', 'rig': 'mixamo',
            'collision': {'version': collision.VERSION, 'sha256': 'b' * 64, 'scales': scales, 'source': 'own',
                          'capsules': capsules, 'extension_groups': ['chain']},   # the base's record: chain built
            'extension_rig': {'status': 'not_found', 'groups': ['chain'], 'group_ops': {'chain': 'appendage_chain'}}}
    assert collision.refresh(NAME, Path(tmp) / 'outfit.glb', meta, scales=scales)
    assert [c['id'] for c in meta['collision']['capsules']] == ['left_thigh']
    assert meta['collision']['source'] == 'base'

# Fails on the old code: its base dropped every part op, and its reader took the record's key or "".
old_source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD}:app/core/model3d.py'],
                            capture_output=True, text=True, check=True).stdout
tree = ast.parse(old_source)
old_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_extension_groups_for')
old_state = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'model_extension_state')
assert 'mesh_variant=meta.get("mesh_variant") or ""' in ast.get_source_segment(old_source, old_state)
scope = {'PART_OPS': ('attached_part', 'attached_part_bone', 'inset_part'), 'Dict': dict, 'Any': object}
exec(compile(ast.Module([old_fn], []), 'old', 'exec'), scope)
old_groups_for = scope['_extension_groups_for']
with tempfile.TemporaryDirectory() as tmp2:
    with patch.object(bs, '_species_packages_for', return_value=[pkg]), \
            patch('app.plugins.registry.packages', return_value=[pkg]):
        old_1 = {g['id']: g['op'] for g in old_groups_for(
            {'base': True, 'mesh_variant': TOKEN}, er.rig_groups_for(NAME, clothed, TOKEN))}
        old_3 = {g['id']: g['op'] for g in old_groups_for(
            {'base': True}, er.rig_groups_for(NAME, clothed, ''))}
assert old_1 == {} and old_3 == OFF, (old_1, old_3)
assert old_1 != ON and old_3 != ON

print('PASS base part unclothed: base token on [1], covering outfit off + stale parts [2], old base derived on [3], '
      'pre-switch / re-rendered off [4], lights [5], Base body reader [6], inherited capsules [7], '
      f'old code {OLD[:9]} fails [1]+[3]')
