"""State bone poses NAME a package pose (owner decision 2026-11-20), in temporary storage.

Usage: .venv/bin/python scripts/smoke_state_pose_names.py

A package's extension group declares named poses (``rigs[].poses: {<id>: {BONE_POSE_FIELDS values, rigid 0|1}}``); a
state's ``bone_pose`` is ``{<group id>: "<pose id>"}``. Fixture package "sample" (temp plugins dir), groups:
  tail_chain  two links TailA -> TailB under Hips; freq_hz 2, zeta .3, gravity .35, gain 1, max_deg 25, length 1,
              girth 1, rest_max_deg 90; ONE pose raised {rest_deg 80, girth 1.2, length 1.15, gain 0, rigid 1}
  tip_group   one link; controls [length, girth]; pose raised {length 1.5}
  multi_group one link; poses a {rest_deg 10, gain .5}, b {rest_deg 20, gain .25}
  plain_group one link; no poses

[1] MANIFEST: the pose values are parsed as floats ({rest_deg 80.0, …, rigid 1.0}); refused: rigid .5 / 2 / true,
    an unknown field, an empty pose, a pose id with a blank or empty, rest_deg 181, length .4, girth 2.1, gain -1,
    a non-mapping ``poses``, and under controls [length, girth] a pose that sets gravity / rest_deg.
[2] STATE: {tail_chain: raised} is accepted; refused with 400 and a message naming the cause: a dict value (the old
    raw form — no reader for it), an unknown group (named), an undeclared pose (named, with the declared list), a
    group that declares no pose.
[3] MOTION (preview_states, no clothing). The pose's values apply exactly as the same raw values did before:
      raised on tail_chain: rest_deg 80 (inside ±90), girth 1 × 1.2 = 1.2, length 1 × 1.15 = 1.15, gain 1 × 0 = 0
      (explicit zero), freq_hz 2, gravity .35 unchanged; rigid 1.
      no state: rest_deg 0, girth 1, length 1, gain 1, rigid 0 — and a different rev.
      raised on tip_group: length 1.5.
      a + b on multi_group: rest_deg max(10, 20) = 20, gain .5 × .25 = .125; a alone: 10 and .5; rigid 0.
[4] MIGRATION (``bone_pose_migration.migrate_bone_pose_names``), rows written in the old form:
      exact       {tail_chain: {gain 0, rest_deg 80, girth 1.2, length 1.15}}   -> {tail_chain: raised} (equal values,
                  the pose's rigid aside)
      tip         {tip_group: {length 1.5}}                                    -> {tip_group: raised}
      single      {tail_chain: {rest_deg 40}}  (no pose matches, ONE declared) -> {tail_chain: raised} + WARNING naming
                  the state, the group and the dropped values
      no_poses    {plain_group: {gain .5}}                                      -> {} + WARNING
      multi       {multi_group: {gain .9}}  (no match, two declared)           -> {} + WARNING
      mixed       {tip_group: {length 1.5}, plain_group: {gain .5}}            -> {tip_group: raised}
      ghost       {ghost_group: {gain 1}}  (no package declares it)            -> unchanged + WARNING
      named       {tail_chain: raised}                                          -> unchanged
    6 rows change (all but ghost and named); a second run changes 0 rows and leaves every row as it was.
"""
import json
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


def refused(fn, needle=''):
    """True when fn raises ValueError (or an HTTP 400) whose message contains needle."""
    from fastapi import HTTPException
    try:
        fn()
    except ValueError as exc:
        return needle in str(exc)
    except HTTPException as exc:
        return exc.status_code == 400 and needle in str(exc.detail)
    return False


def main():
    with tempfile.TemporaryDirectory(prefix='state-pose-names-') as tmp:
        root = Path(tmp)
        paths.init(root / 'world')
        paths.init_instance(root / 'instance')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root / 'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root / 'rig.fbx')
        from app.core import db, config, prompt_filters
        db.init_schema()
        paths.get_config_path().write_text(json.dumps({'packages': {'enabled': 'sample'}}))
        config.load(paths.get_config_path(), instance_path=root / 'instance/config.json')
        import yaml
        from app.plugins.loader import discover_packages
        from app.plugins.registry import RigSpec, get_package

        def rig(gid, bones, **extra):
            chain, parent = [], 'Hips'
            for bone in bones:
                chain.append({'bone': bone, 'parent': parent})
                parent = bone
            return {'id': gid, 'op': 'fixture', 'chains': [chain], **extra}
        raised = {'rest_deg': 80, 'girth': 1.2, 'length': 1.15, 'gain': 0, 'rigid': 1}
        tail = rig('tail_chain', ['TailA', 'TailB'], freq_hz=2, zeta=.3, gravity=.35, gain=1, max_deg=25,
                   rest_max_deg=90, poses={'raised': raised})
        tip = rig('tip_group', ['TipBone'], controls=['length', 'girth'], poses={'raised': {'length': 1.5}})
        multi = rig('multi_group', ['MultiBone'], poses={'a': {'rest_deg': 10, 'gain': .5}, 'b': {'rest_deg': 20, 'gain': .25}})
        plain = rig('plain_group', ['PlainBone'])
        package = root / 'plugins' / 'sample'
        package.mkdir(parents=True)
        (package / 'plugin.yaml').write_text(yaml.safe_dump({
            'name': 'Sample', 'apply_to': '*', 'body_slots': [
                {'id': 'sample_slot', 'covered_by': ['top'], 'rigs': [tail, tip, multi, plain]}]}))
        discover_packages(root / 'plugins', force=True)

        # [1] manifest
        rigs = {r.id: r for r in get_package('sample').body_slots[0].rigs}
        check(sorted(rigs) == ['multi_group', 'plain_group', 'tail_chain', 'tip_group'], '[1] all four groups load')
        check(rigs['tail_chain'].poses == {'raised': {'rest_deg': 80.0, 'girth': 1.2, 'length': 1.15, 'gain': 0.0, 'rigid': 1.0}},
              '[1] the pose values parse as floats')
        check(rigs['plain_group'].poses == {}, '[1] no poses declared = {}')
        for label, poses, needle in (
                ('rigid .5', {'p': {'rigid': .5}}, 'rigid'), ('rigid 2', {'p': {'rigid': 2}}, 'rigid'),
                ('rigid true', {'p': {'rigid': True}}, 'rigid'), ('unknown field', {'p': {'swing': 1}}, 'unknown'),
                ('empty pose', {'p': {}}, 'non-empty'), ('blank in id', {'a b': {'gain': 1}}, 'pose'),
                ('empty id', {'': {'gain': 1}}, 'pose'), ('rest_deg 181', {'p': {'rest_deg': 181}}, 'rest_deg'),
                ('length .4', {'p': {'length': .4}}, 'length'), ('girth 2.1', {'p': {'girth': 2.1}}, 'girth'),
                ('gain -1', {'p': {'gain': -1}}, 'gain'), ('poses a list', ['raised'], 'poses')):
            check(refused(lambda: RigSpec.parse(rig('x', ['X'], poses=poses)), needle), f'[1] refused: {label}')
        for field in ('gravity', 'rest_deg'):
            check(refused(lambda: RigSpec.parse(rig('x', ['X'], controls=['length', 'girth'], poses={'p': {field: 1}})),
                          'controls'), f'[1] refused under controls [length, girth]: a pose with {field}')

        # [2] state
        shared = root / 'shared-filters.json'
        shared.write_text('{"filters": []}')
        with patch.object(prompt_filters, '_SHARED_FILE', shared):
            from app.routes.admin_settings import _prompt_filters_save_sync
            check(prompt_filters.validate_bone_pose({'tail_chain': 'raised'}) == {'tail_chain': 'raised'}, '[2] a declared pose is accepted')
            save = lambda pose: _prompt_filters_save_sync(None, {'id': 'probe', 'bone_pose': pose})
            check(refused(lambda: save({'tail_chain': {'rest_deg': 80}}), 'must be a pose id'), '[2] 400: the old raw dict form')
            check(refused(lambda: save({'ghost_group': 'raised'}), "unknown extension group 'ghost_group'"), '[2] 400: unknown group, named')
            check(refused(lambda: save({'multi_group': 'c'}), "declares no pose 'c' (declared: a, b)"), '[2] 400: undeclared pose, with the declared list')
            check(refused(lambda: save({'plain_group': 'raised'}), 'it declares no poses'), '[2] 400: a group without poses')

            # [3] motion
            for state in ({'id': 'raise', 'bone_pose': {'tail_chain': 'raised', 'tip_group': 'raised'}},
                          {'id': 'pose_a', 'bone_pose': {'multi_group': 'a'}},
                          {'id': 'pose_b', 'bone_pose': {'multi_group': 'b'}}):
                _prompt_filters_save_sync(None, state)
            from app.core.extension_rig import motion_payload
            profile = {'template': 'human-default'}
            def groups(states):
                return motion_payload('sample', profile, apply_clothing=False, preview_states=states)
            base, lifted = groups([]), groups(['raise'])
            t = lifted['groups']['tail_chain']
            check(t['rest_deg'] == 80 and abs(t['girth'] - 1.2) < 1e-12 and abs(t['length'] - 1.15) < 1e-12 and t['gain'] == 0,
                  '[3] raised: rest 80, girth 1.2, length 1.15, gain 0 — the raw values\' result')
            check(t['freq_hz'] == 2 and t['gravity'] == .35 and t['rigid'] == 1, '[3] raised: freq 2, gravity .35 unchanged; rigid 1')
            b = base['groups']['tail_chain']
            check(b['rest_deg'] == 0 and b['girth'] == 1 and b['length'] == 1 and b['gain'] == 1 and b['rigid'] == 0,
                  '[3] no state: neutral, rigid 0')
            check(base['rev'] != lifted['rev'], '[3] the named pose changes motion.rev')
            check(lifted['groups']['tip_group']['length'] == 1.5, '[3] raised on tip_group: length 1.5')
            m = groups(['pose_a', 'pose_b'])['groups']['multi_group']
            check(m['rest_deg'] == 20 and abs(m['gain'] - .125) < 1e-12 and m['rigid'] == 0, '[3] a + b: rest max 20, gain .5 × .25 = .125')
            m = groups(['pose_a'])['groups']['multi_group']
            check(m['rest_deg'] == 10 and m['gain'] == .5, '[3] a alone: rest 10, gain .5')

            # [4] migration
            from app.core import bone_pose_migration
            rows = {
                'exact': {'tail_chain': {'gain': 0, 'rest_deg': 80, 'girth': 1.2, 'length': 1.15}},
                'tip': {'tip_group': {'length': 1.5}},
                'single': {'tail_chain': {'rest_deg': 40}},
                'no_poses': {'plain_group': {'gain': .5}},
                'multi': {'multi_group': {'gain': .9}},
                'mixed': {'tip_group': {'length': 1.5}, 'plain_group': {'gain': .5}},
                'ghost': {'ghost_group': {'gain': 1}},
                'named': {'tail_chain': 'raised'},
            }
            with db.transaction() as conn:
                conn.execute('DELETE FROM prompt_filters')
                for sid, pose in rows.items():
                    conn.execute("INSERT INTO prompt_filters (id, condition, bone_pose) VALUES (?, '', ?)", (sid, json.dumps(pose)))
            def stored():
                with db.transaction() as conn:
                    return {sid: json.loads(raw) for sid, raw in conn.execute('SELECT id, bone_pose FROM prompt_filters')}
            warnings = []
            with patch.object(bone_pose_migration.logger, 'warning', side_effect=lambda msg, *a: warnings.append(msg % a)):
                changed = bone_pose_migration.migrate_bone_pose_names()
            after = stored()
            check(changed == 6, f'[4] six rows change (got {changed})')
            check(after['exact'] == {'tail_chain': 'raised'}, '[4] exact values -> the pose id')
            check(after['tip'] == {'tip_group': 'raised'}, '[4] exact values (tip) -> the pose id')
            check(after['single'] == {'tail_chain': 'raised'}, '[4] no match, one pose declared -> that pose')
            check(any("'single'" in w and 'tail_chain' in w and '"rest_deg": 40' in w for w in warnings),
                  '[4] … with a WARNING naming state, group and the dropped values')
            check(after['no_poses'] == {} and any("'no_poses'" in w and 'plain_group' in w and 'declares no pose' in w for w in warnings),
                  '[4] a group without poses: entry removed with a WARNING')
            check(after['multi'] == {} and any("'multi'" in w and 'matches none' in w for w in warnings),
                  '[4] no match among several poses: removed with a WARNING')
            check(after['mixed'] == {'tip_group': 'raised'}, '[4] mixed row: one entry named, one removed')
            check(after['ghost'] == rows['ghost'] and any("'ghost'" in w and 'ghost_group' in w for w in warnings),
                  '[4] a group no package declares: left as it is, with a WARNING')
            check(after['named'] == {'tail_chain': 'raised'}, '[4] an already named row is untouched')
            again = bone_pose_migration.migrate_bone_pose_names()
            check(again == 0 and stored() == after, '[4] idempotent: a second run changes nothing')
            check(prompt_filters.load_filters() and next(f for f in prompt_filters.load_filters() if f['id'] == 'exact')['bone_pose'] == {'tail_chain': 'raised'},
                  '[4] the filter snapshot sees the migrated rows')
    if FAILED:
        print(f'\nFAILED ({len(FAILED)})')
        sys.exit(1)
    print('\nALL OK')


if __name__ == '__main__':
    main()
