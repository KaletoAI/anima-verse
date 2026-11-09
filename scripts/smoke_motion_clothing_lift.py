"""Clothing product and lift in the effective extension motion.

Usage: .venv/bin/python scripts/smoke_motion_clothing_lift.py

Runs in a temp world with a fixture package; no server, no live world.
Spec: docs/plugins.md "Extension motion layers" (clothing product, lift) and
docs/schnittstellen-3d.md "Effective extension motion".

Fixture group: freq_hz 2, zeta .5, gravity .4, gain 1, max_deg 40,
translate .6, spill .5, sag_max_deg 30, rest_max_deg 30; covered_by
[top, underwear_top, underwear_bottom]; clothing_lift_default
{underwear_top: .25, top: 0}. Pieces: bra = slot underwear_top, damping .5;
top = slot top, damping .8; lifted top = slot top, lift .6; sheer = slot
legs, partially_covers underwear_top, damping .6; light layer = slot legs,
partially_covers top, lift .5; slip = slot underwear_bottom, lift .9; stiff =
slot underwear_top, damping 0.

Hand derivation (c = clothing product, L = lift):
[D1] bra: c=.5 -> gain .5, max_deg 40*.5=20, translate .6*.5=.3, spill
     .5*.5=.25, freq 2/sqrt(.5)=2.8284271247461903, zeta .5/sqrt(.5)=
     .7071067811865476. L=.25 (slot default) -> gravity .4*.75=.3, sag
     30*.75=22.5, rest .25*30=7.5.
[D2] bra + top: c=.5*.8=.4 -> gain .4, max_deg 16, translate .24, spill .2,
     freq 2/sqrt(.4)=3.1622776601683795, zeta .5/sqrt(.4)=.7905694150420949;
     L=max(.25, 0)=.25 -> gravity .3, rest 7.5 (the top's default 0 does not
     lower the bra's lift).
[D3] top alone: c=.8 -> gain .8, max_deg 32, freq 2/sqrt(.8)=2.23606797749979;
     L=0 -> gravity .4, sag 30, rest 0.
[D4] bra + lifted top: c=.5*1=.5; L=max(.25,.6)=.6 -> gravity .4*.4=.16,
     sag 30*.4=12, rest 18.
[D5] sheer alone (partial): c=1-(1-.6)/2=.8; L=.25/2=.125 -> gravity
     .4*.875=.35, sag 26.25, rest 3.75.
[D6] light layer (partial over top, own lift .5): c=1 (freq stays 2);
     L=.5/2=.25 -> gravity .3, rest 7.5.
[D7] slip: underwear_bottom is covered but not a lift slot -> L=0, rest 0,
     gravity .4 although the piece says lift .9.
[D8] clamps: state rest 28 + bra lift 7.5 = 35.5 -> clamped to 30. stiff
     (c=0): gain/max_deg/translate/spill 0, freq 2*100=200 -> 20 (upper
     clamp), zeta .5*100=50 -> 10; L=.25 still applies (gravity .3).
[D9] apply_clothing=False: c=1, L=0 -> the package values unchanged.
[D10] own lift 1 on the bra: gravity 0, sag 0, rest 30.
[D11] editing the bra's lift (.3) changes motion.rev and gives rest 9.
Items: lift absent is stored absent; out-of-range/bool/NaN/text rejected; a
partial update without lift keeps it; an explicit null resets to default.
Registry: clothing_lift_default above 1 or naming a slot outside covered_by
drops the rig. Route: lift_defaults {top: 0, underwear_top: .25},
motion_damping_slots [top, underwear_bottom, underwear_top].
Before this change (e1e106d4) only gain followed the clothing
product and no lift existed (rest stayed 0, gravity .4 in D1).
"""
import json
import math
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

FAILED = []


def check(ok, label):
    print(('PASS ' if ok else 'FAIL ') + label)
    if not ok:
        FAILED.append(label)


def near(a, b, eps=1e-12):
    return abs(a - b) <= eps


def main():
    with tempfile.TemporaryDirectory(prefix='motion-lift-') as tmp:
        root = Path(tmp)
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import db, config
        db.init_schema()
        paths.get_config_path().write_text(json.dumps({'packages': {'enabled': 'sample'}}))
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        import yaml
        from app.plugins.loader import discover_packages
        from app.plugins.registry import RigSpec
        rig = {'id': 'sample_group', 'op': 'pair_protrusion',
               'chains': [[{'bone': 'SampleBone', 'parent': 'Hips'}]],
               'freq_hz': 2, 'zeta': .5, 'gravity': .4, 'gain': 1, 'max_deg': 40,
               'translate': .6, 'spill': .5, 'sag_max_deg': 30, 'rest_max_deg': 30,
               'clothing_lift_default': {'underwear_top': .25, 'top': 0}}
        package = root / 'plugins' / 'sample'
        package.mkdir(parents=True)
        (package / 'plugin.yaml').write_text(yaml.safe_dump({
            'name': 'Sample', 'apply_to': '*', 'body_slots': [
                {'id': 'sample_slot', 'covered_by': ['top', 'underwear_top', 'underwear_bottom'],
                 'rigs': [rig]}]}))
        discover_packages(root / 'plugins', force=True)

        # Registry validation.
        covered = ['top', 'underwear_top', 'underwear_bottom']
        for bad in ({'underwear_top': 1.5}, {'underwear_top': True}, {'legs': .2}, ['top']):
            try:
                RigSpec.parse({**rig, 'clothing_lift_default': bad}, covered_by=covered)
            except ValueError:
                check(True, f'registry rejects clothing_lift_default {bad!r}')
            else:
                check(False, f'registry rejects clothing_lift_default {bad!r}')
        check(RigSpec.parse(rig, covered_by=covered).clothing_lift_default == {'underwear_top': .25, 'top': 0.0},
              'registry keeps the declared defaults')

        from app.models import inventory
        from app.core.extension_rig import motion_payload

        def piece(iid, slots, **extra):
            return inventory.add_item(iid, category='outfit_piece', item_id=iid,
                                      outfit_piece={'slots': slots, **extra})
        bra = piece('bra', ['underwear_top'], motion_damping=.5)
        top = piece('top', ['top'], motion_damping=.8)
        lifted = piece('lifted_top', ['top'], lift=.6)
        sheer = piece('sheer', ['legs'], motion_damping=.6, partially_covers=['underwear_top'])
        layer = piece('light_layer', ['legs'], partially_covers=['top'], lift=.5)
        slip = piece('slip', ['underwear_bottom'], lift=.9)
        stiff = piece('stiff', ['underwear_top'], motion_damping=0)
        check('lift' not in bra['outfit_piece'], 'absent lift is stored absent')
        check(lifted['outfit_piece']['lift'] == .6, 'create keeps lift')

        def group(equipped, **kwargs):
            profile = {'template': 'human-default', 'equipped_pieces': equipped}
            return motion_payload('sample', profile, **kwargs)['groups']['sample_group']

        g = group({'underwear_top': bra['id']})
        check(near(g['gain'], .5) and near(g['max_deg'], 20) and near(g['translate'], .3) and near(g['spill'], .25),
              '[D1] damping .5 scales gain, max_deg, translate, spill')
        check(near(g['freq_hz'], 2.8284271247461903) and near(g['zeta'], .7071067811865476),
              '[D1] freq and zeta stiffer by 1/sqrt(.5)')
        check(near(g['gravity'], .3) and near(g['sag_max_deg'], 22.5) and near(g['rest_deg'], 7.5),
              '[D1] slot default lift .25: gravity .3, sag 22.5, rest 7.5')
        g = group({'underwear_top': bra['id'], 'top': top['id']})
        check(near(g['gain'], .4) and near(g['max_deg'], 16) and near(g['translate'], .24) and near(g['spill'], .2)
              and near(g['freq_hz'], 3.1622776601683795) and near(g['zeta'], .7905694150420949),
              '[D2] product .4 on every damped field')
        check(near(g['gravity'], .3) and near(g['rest_deg'], 7.5), '[D2] top default 0 keeps the bra lift (max rule)')
        g = group({'top': top['id']})
        check(near(g['gain'], .8) and near(g['max_deg'], 32) and near(g['freq_hz'], 2.23606797749979)
              and near(g['gravity'], .4) and near(g['sag_max_deg'], 30) and g['rest_deg'] == 0,
              '[D3] top alone: damping .8, no lift')
        g = group({'underwear_top': bra['id'], 'top': lifted['id']})
        check(near(g['gain'], .5) and near(g['gravity'], .16) and near(g['sag_max_deg'], 12) and near(g['rest_deg'], 18),
              '[D4] own lift .6 beats default .25')
        g = group({'legs': sheer['id']})
        check(near(g['gain'], .8) and near(g['gravity'], .35) and near(g['sag_max_deg'], 26.25) and near(g['rest_deg'], 3.75),
              '[D5] partial cover: damping .8, lift .125')
        g = group({'legs': layer['id']})
        check(g['freq_hz'] == 2 and near(g['gravity'], .3) and near(g['rest_deg'], 7.5),
              '[D6] partial own lift .5 counts .25')
        g = group({'underwear_bottom': slip['id']})
        check(g['gravity'] == .4 and g['rest_deg'] == 0, '[D7] a covered slot without a lift default never lifts')

        from app.routes.admin_settings import _prompt_filters_save_sync
        _prompt_filters_save_sync(None, {'id': 'raised', 'bone_pose': {'sample_group': {'rest_deg': 28}}})
        g = group({'underwear_top': bra['id']}, preview_states=['raised'])
        check(g['rest_deg'] == 30, '[D8] state rest 28 + lift 7.5 clamps to rest_max_deg 30')
        g = group({'underwear_top': stiff['id']})
        check(g['gain'] == 0 and g['max_deg'] == 0 and g['translate'] == 0 and g['spill'] == 0
              and g['freq_hz'] == 20 and g['zeta'] == 10 and near(g['gravity'], .3)
              and all(math.isfinite(v) for v in (g['freq_hz'], g['zeta'])),
              '[D8] damping 0 stops the motion; freq/zeta clamp at 20/10')
        g = group({'underwear_top': bra['id']}, apply_clothing=False)
        check(g['gain'] == 1 and g['max_deg'] == 40 and g['translate'] == .6 and g['spill'] == .5 and g['freq_hz'] == 2
              and g['zeta'] == .5 and g['gravity'] == .4 and g['sag_max_deg'] == 30 and g['rest_deg'] == 0,
              '[D9] apply_clothing=False bypasses product and lift')

        # Partial-update semantics and validation.
        for bad in (-.1, 1.1, float('nan'), True, 'x'):
            try:
                piece('invalid', ['top'], lift=bad)
            except ValueError:
                check(True, f'create rejects lift {bad!r}')
            else:
                check(False, f'create rejects lift {bad!r}')
        before = motion_payload('sample', {'template': 'human-default', 'equipped_pieces': {'underwear_top': bra['id']}})
        inventory.update_item(bra['id'], {'outfit_piece': {**inventory.get_item(bra['id'])['outfit_piece'], 'lift': 1}})
        g = group({'underwear_top': bra['id']})
        check(g['gravity'] == 0 and g['sag_max_deg'] == 0 and g['rest_deg'] == 30, '[D10] own lift 1')
        inventory.update_item(bra['id'], {'outfit_piece': {**inventory.get_item(bra['id'])['outfit_piece'], 'lift': .3}})
        after = motion_payload('sample', {'template': 'human-default', 'equipped_pieces': {'underwear_top': bra['id']}})
        check(after['rev'] != before['rev'] and near(after['groups']['sample_group']['rest_deg'], 9),
              '[D11] a lift edit changes motion.rev (rest 9)')
        stored = dict(inventory.get_item(bra['id'])['outfit_piece'])
        stored.pop('lift')
        inventory.update_item(bra['id'], {'outfit_piece': {**stored, 'motion_damping': .7}})
        check(inventory.get_item(bra['id'])['outfit_piece'].get('lift') == .3
              and inventory.get_item(bra['id'])['outfit_piece']['motion_damping'] == .7,
              'update without lift keeps the stored lift')
        inventory.update_item(bra['id'], {'name': 'renamed'})
        check(inventory.get_item(bra['id'])['outfit_piece'].get('lift') == .3, 'update without outfit_piece keeps lift')
        inventory.update_item(bra['id'], {'outfit_piece': {**stored, 'lift': None}})
        check('lift' not in inventory.get_item(bra['id'])['outfit_piece'], 'explicit null resets to the slot default')
        try:
            inventory.update_item(bra['id'], {'outfit_piece': {**stored, 'lift': 2}})
        except ValueError:
            check(True, 'update rejects lift 2')
        else:
            check(False, 'update rejects lift 2')

        from app.routes.inventory import body_under_piece_route
        info = body_under_piece_route()
        check(info['lift_defaults'] == {'top': 0.0, 'underwear_top': .25}, 'route lift defaults from the package')
        check(info['motion_damping_slots'] == ['top', 'underwear_bottom', 'underwear_top'], 'route damping slots')
        check(info['exposed_detail_slots'] == [], 'route exposed-only slots (none declared)')
    if FAILED:
        print(f'{len(FAILED)} FAILED')
        sys.exit(1)
    print('ALL OK')


if __name__ == '__main__':
    main()
