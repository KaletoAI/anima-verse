"""Body-slot region declarations (kind ``channel``) and the op on motion groups.

Usage: ./.venv/bin/python scripts/smoke_region_declarations.py

Plan docs/superpowers/plans/2026-11-14-cross-person-collision.md, Task 10; spec
docs/superpowers/specs/2026-11-13-cross-person-collision-design.md Part 4 "Declaration".
Runs in a temp world + instance with a temp ``plugins/`` dir holding one synthetic
package ``pkgx`` (neutral ids); no server, no live world, no network.

Fixture ``pkgx`` (apply_to "*"):
- slot ``slotx``, covered_by [bottom], select attributes switch [off, on],
  size [s, m, l], kind [a, b]; rig ``pkgx_chain`` (appendage_chain, two links
  PkgxA <- Hips, PkgxB <- PkgxA); mesh_part switch ``switch`` naming that rig.
  Regions:
  - ``chan``: kind channel, bone Hips, offset [0, -0.10, 0.05], axis [0, 1, 0],
    depth 0.12, radius 0.02, cone_deg 30, funnel 0.03,
    accepts {ops: [appendage_chain, attached_part]}, min_length 1.5,
    compress_min 0.5, interaction_kinds [kind_x], from_rig pkgx_chain,
    attribute_params radius {size: {s: 0.8, l: 1.2}}, depth {size: {l: 1.5}}.
  - ``gated``: the minimal channel (bone Spine, offset [0,0,0], axis [0,0,1],
    depth 0.1, radius 0.01, cone_deg 20, funnel 0.02, accepts [appendage_chain])
    with applies_to {attributes.kind: [b]}.
  - ``here``: the minimal channel with templates [human-default].
  - ``elsewhere``: the minimal channel with templates [no-such-template].
- slot ``sloty``: rig ``pkgx_other`` (appendage_chain, one link PkgxC <- Hips).
- slot ``slotz``, applies_to {gender: [g1]}: region ``zchan`` (minimal).

Expected, by hand from the brief:
[1] A valid package loads with no loader error. For template human-default,
    slot values {switch off, size m, kind a} and no gender, the declarations
    are, in declaration order, pkgx:chan and pkgx:here (gated fails kind a,
    elsewhere names another template, zchan's slot does not apply). pkgx:chan
    is exactly {id pkgx:chan, slot slotx, bone Hips, offset [0, -0.1, 0.05],
    axis [0, 1, 0], depth 0.12, radius 0.02 (size m is not mapped, so x1),
    cone_deg 30, funnel 0.03, accepts [appendage_chain, attached_part],
    min_length 1.5, compress_min 0.5, exposed_only True, interaction_kinds
    [kind_x], from_rig pkgx_chain, covered_by [bottom]}. The minimal region
    parses to the defaults min_length 1.0, compress_min 1.0, exposed_only True,
    interaction_kinds None, from_rig None.
[2] Each malformed ``chan`` rejects the WHOLE package (``pkgx`` missing from
    the registry) with exactly one ERROR record of the loader: kind tube,
    cone_deg 0, cone_deg 61, depth -1, accepts.ops [], bone Nope, from_rig
    pkgx_other (a rig of ANOTHER slot), from_rig missing_rig, axis [0, 0, 0],
    min_length 5 (> 4), compress_min 0, attribute_params cone_deg (only
    radius/depth), attribute_params radius naming option xl (undeclared),
    attribute_params radius value 0 (not positive), an unknown key, and a
    duplicate region id in the package.
[3] Like a rig: kind b adds pkgx:gated (order chan, gated, here); gender g1
    adds pkgx:zchan (slot applies); no template drops pkgx:here and, because
    no species package applies without a template, every slot-scoped region
    too (result []); pkgx:elsewhere never appears.
[4] size l: radius 0.02 * 1.2 = 0.024, depth 0.12 * 1.5 = 0.18; size s:
    radius 0.02 * 0.8 = 0.016, depth 0.12 (s not in the depth mapping).
[5] motion_payload (human-default dresses by free text, so ``outfit_worn``
    decides exposure): switch off -> pkgx_chain op appendage_chain; switch on
    and outfit_worn False (slot exposed, the mesh part counts) ->
    attached_part, the op rig_groups_for decides; switch on but dressed
    (outfit_worn absent = worn) -> appendage_chain; pkgx_other stays
    appendage_chain. A hair
    group (served_chains patched to chain 3, weighted [_00, _01], stiffness
    0.4, swing on) is present as hair_c03 and carries NO op key.
"""
import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

FAILED = []


def check(ok, label):
    print(('PASS ' if ok else 'FAIL ') + label)
    if not ok:
        FAILED.append(label)


def near(a, b, eps=1e-12):
    return abs(a - b) <= eps


MINIMAL = {'kind': 'channel', 'bone': 'Spine', 'offset': [0, 0, 0], 'axis': [0, 0, 1], 'depth': .1,
           'radius': .01, 'cone_deg': 20, 'funnel': .02, 'accepts': {'ops': ['appendage_chain']}}
CHAN = {'id': 'chan', 'kind': 'channel', 'bone': 'Hips', 'offset': [0, -.10, .05], 'axis': [0, 1, 0],
        'depth': .12, 'radius': .02, 'cone_deg': 30, 'funnel': .03,
        'accepts': {'ops': ['appendage_chain', 'attached_part']}, 'min_length': 1.5, 'compress_min': .5,
        'interaction_kinds': ['kind_x'], 'from_rig': 'pkgx_chain',
        'attribute_params': {'radius': {'attribute': 'size', 'values': {'s': .8, 'l': 1.2}},
                             'depth': {'attribute': 'size', 'values': {'l': 1.5}}}}


def manifest(chan=None, extra_regions=()):
    attrs = {'switch': {'type': 'select', 'options': ['off', 'on']},
             'size': {'type': 'select', 'options': ['s', 'm', 'l']},
             'kind': {'type': 'select', 'options': ['a', 'b']}}
    chain = {'id': 'pkgx_chain', 'op': 'appendage_chain', 'chains': [[
        {'bone': 'mixamorig:PkgxA', 'parent': 'Hips'}, {'bone': 'mixamorig:PkgxB', 'parent': 'mixamorig:PkgxA'}]]}
    return {'name': 'Pkgx', 'apply_to': '*', 'body_slots': [
        {'id': 'slotx', 'covered_by': ['bottom'], 'attributes': attrs, 'rigs': [chain],
         'mesh_part': {'switch': 'switch', 'rigs': {'pkgx_chain': {'params': {}, 'attribute_params': {}}}},
         'regions': [chan if chan is not None else CHAN,
                     {**MINIMAL, 'id': 'gated', 'applies_to': {'attributes.kind': ['b']}},
                     {**MINIMAL, 'id': 'here', 'templates': ['human-default']},
                     {**MINIMAL, 'id': 'elsewhere', 'templates': ['no-such-template']},
                     *extra_regions]},
        {'id': 'sloty', 'rigs': [{'id': 'pkgx_other', 'op': 'appendage_chain',
                                  'chains': [[{'bone': 'mixamorig:PkgxC', 'parent': 'Hips'}]]}]},
        {'id': 'slotz', 'applies_to': {'gender': ['g1']}, 'regions': [{**MINIMAL, 'id': 'zchan'}]}]}


class Errors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def main():
    with tempfile.TemporaryDirectory(prefix='region-decl-') as tmp:
        root = Path(tmp)
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import db, config
        db.init_schema()
        paths.get_config_path().write_text(json.dumps({'packages': {'enabled': 'pkgx'}}))
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        import yaml
        from app.plugins import registry
        from app.plugins.loader import discover_packages
        from app.plugins.registry import RegionSpec
        from app.core.extension_rig import motion_payload, region_declarations_for
        package = root / 'plugins' / 'pkgx'
        package.mkdir(parents=True)
        errors = Errors()
        logging.getLogger('plugin_loader').addHandler(errors)

        def load(meta):
            (package / 'plugin.yaml').write_text(yaml.safe_dump(meta))
            errors.records.clear()
            discover_packages(root / 'plugins', force=True)
            return 'pkgx' in {p.id for p in registry.packages()}, len(errors.records)

        # [1]
        loaded, count = load(manifest())
        check(loaded and count == 0, f'[1] the valid package loads without an error (loaded {loaded}, errors {count})')

        def profile(**values):
            gender = values.pop('gender', None)
            template = values.pop('template', 'human-default')
            row = {'switch': 'off', 'size': 'm', 'kind': 'a', **values}
            out = {'template': template, 'body_slots': {'slotx': row}}
            if gender:
                out['gender'] = gender
            return out

        def ids(prof):
            return [entry['id'] for entry in region_declarations_for('pkgx_char', prof)]

        rows = region_declarations_for('pkgx_char', profile())
        check([r['id'] for r in rows] == ['pkgx:chan', 'pkgx:here'], f'[1] declarations chan, here: {[r["id"] for r in rows]}')
        expected = {'id': 'pkgx:chan', 'slot': 'slotx', 'bone': 'Hips', 'offset': [0.0, -0.1, 0.05],
                    'axis': [0.0, 1.0, 0.0], 'depth': 0.12, 'radius': 0.02, 'cone_deg': 30.0, 'funnel': 0.03,
                    'accepts': ['appendage_chain', 'attached_part'], 'min_length': 1.5, 'compress_min': 0.5,
                    'exposed_only': True, 'interaction_kinds': ['kind_x'], 'from_rig': 'pkgx_chain',
                    'covered_by': ['bottom']}
        check(rows and rows[0] == expected, f'[1] pkgx:chan entry {rows[0] if rows else None}')
        minimal = RegionSpec.parse({**MINIMAL, 'id': 'm'}, {}, set())
        check((minimal.min_length, minimal.compress_min, minimal.exposed_only, minimal.interaction_kinds,
               minimal.from_rig, minimal.accepts_ops) == (1.0, 1.0, True, None, None, ['appendage_chain']),
              '[1] minimal region defaults')

        # [2]
        bad = {
            'kind tube': {**CHAN, 'kind': 'tube'},
            'cone_deg 0': {**CHAN, 'cone_deg': 0},
            'cone_deg 61': {**CHAN, 'cone_deg': 61},
            'depth -1': {**CHAN, 'depth': -1},
            'accepts.ops []': {**CHAN, 'accepts': {'ops': []}},
            'bone Nope': {**CHAN, 'bone': 'Nope'},
            'from_rig of another slot': {**CHAN, 'from_rig': 'pkgx_other'},
            'from_rig unknown': {**CHAN, 'from_rig': 'missing_rig'},
            'axis zero': {**CHAN, 'axis': [0, 0, 0]},
            'min_length 5': {**CHAN, 'min_length': 5},
            'compress_min 0': {**CHAN, 'compress_min': 0},
            'attribute_params cone_deg': {**CHAN, 'attribute_params': {
                'cone_deg': {'attribute': 'size', 'values': {'l': 1.2}}}},
            'attribute_params undeclared option': {**CHAN, 'attribute_params': {
                'radius': {'attribute': 'size', 'values': {'xl': 1.2}}}},
            'attribute_params value 0': {**CHAN, 'attribute_params': {
                'radius': {'attribute': 'size', 'values': {'l': 0}}}},
            'unknown key': {**CHAN, 'shape': 'round'},
        }
        for label, chan in bad.items():
            loaded, count = load(manifest(copy.deepcopy(chan)))
            check(not loaded and count == 1, f'[2] {label}: package rejected with one error (loaded {loaded}, errors {count})')
        loaded, count = load(manifest(extra_regions=[{**MINIMAL, 'id': 'chan'}]))
        check(not loaded and count == 1, f'[2] duplicate region id: package rejected with one error (loaded {loaded}, errors {count})')
        loaded, count = load(manifest())
        check(loaded and count == 0, '[2] the valid manifest loads again')

        # [3]
        check(ids(profile(kind='b')) == ['pkgx:chan', 'pkgx:gated', 'pkgx:here'], '[3] kind b adds gated')
        check(ids(profile(gender='g1')) == ['pkgx:chan', 'pkgx:here', 'pkgx:zchan'], '[3] gender g1 adds zchan')
        check(ids(profile(template='')) == [], f'[3] no template: nothing ({ids(profile(template=""))})')
        check(all('pkgx:elsewhere' not in ids(p) for p in (profile(), profile(kind='b'), profile(gender='g1'))),
              '[3] elsewhere never applies')

        # [4]
        large = region_declarations_for('pkgx_char', profile(size='l'))[0]
        small = region_declarations_for('pkgx_char', profile(size='s'))[0]
        check(near(large['radius'], .024) and near(large['depth'], .18), f'[4] size l: radius {large["radius"]}, depth {large["depth"]}')
        check(near(small['radius'], .016) and near(small['depth'], .12), f'[4] size s: radius {small["radius"]}, depth {small["depth"]}')

        # [5]
        from app.core import hair_motion
        summary = {'chains': [{'index': 3, 'stiffness': .4,
                               'weighted': ['HairGen_c03_00', 'HairGen_c03_01'], 'rigid': []}]}
        with patch.object(hair_motion, 'served_chains', return_value=summary), \
                patch.object(hair_motion, 'worn_settings', return_value={'swing': True, 'stiffness': 1.0}):
            off = motion_payload('pkgx_char', profile(switch='off'))['groups']
            on = motion_payload('pkgx_char', {**profile(switch='on'), 'outfit_worn': False})['groups']
            dressed = motion_payload('pkgx_char', profile(switch='on'))['groups']
        check(off.get('pkgx_chain', {}).get('op') == 'appendage_chain', '[5] switch off: appendage_chain')
        check(on.get('pkgx_chain', {}).get('op') == 'attached_part', '[5] switch on, exposed: attached_part')
        check(dressed.get('pkgx_chain', {}).get('op') == 'appendage_chain', '[5] switch on, dressed: appendage_chain')
        check(off.get('pkgx_other', {}).get('op') == 'appendage_chain'
              and on.get('pkgx_other', {}).get('op') == 'appendage_chain', '[5] the other slot stays appendage_chain')
        check('hair_c03' in on and 'op' not in on['hair_c03'] and 'op' not in off.get('hair_c03', {'op': 1}),
              '[5] the hair group carries no op')
        logging.getLogger('plugin_loader').removeHandler(errors)
    if FAILED:
        print(f'FAILED {len(FAILED)}')
        sys.exit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
