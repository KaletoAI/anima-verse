#!/usr/bin/env python3
"""Who may take part, and in front of whom — the core capability
``participation.check`` (plan-intim-privatsphaere.md, part B) on the free
pair-pose path. The furniture path (presence "policy") is covered in
``smoke_prop_action_runs.py`` (test_policy_presence_asks_the_participation_providers).
Against a temporary world only.

Usage: ./.venv/bin/python scripts/smoke_participation.py

Fixture: A and B stand in the open 1 m apart (OPEN_FIELD_REACH_M is far
more), no location. Fakes on ``participation.check``:
  quiet  → "" always (none of its business)
  boom   → raises
  hug    → kind "pose", key "hug": {reason "privacy", message "not with others present"}

[1] No provider: check(...) → {}; check_can_pair(A, B, "hug") → "".
[2] quiet + boom + hug: check("pose", "hug", [A, B], "", "") → the hug
    refusal (quiet allowed, boom skipped); key "wave" → {}.
[3] check_can_pair(A, B) without a pose → "" (the pose-free checks pass);
    with "Hug" → the key is lower-cased → "not with others present". The call
    carried kind "pose", members [A, B], location "" and room "" (the open).
[4] Inside a room (location "loc1", room "r1" for both): the call carries
    "loc1"/"r1".
[5] start_interaction(A, B, "hug") with a stub pair clip raises ValueError
    "not with others present"; with ``_reserved`` (a prop run that asked its
    furniture rule already) the provider is not asked again.
[6] A refusal without a message falls back to its reason code; a provider
    answering a non-dict or an empty reason is no refusal.
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def main():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as clips:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        os.environ['ANIMATION_CLIPS_DIR'] = clips
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.core import participation
        from app.core import interaction_engine as IE
        from app.core.hooks import register_provider, unregister_owned_providers
        from app.models.character import save_character_profile, set_character_pos

        for name, x in (('A', 10.0), ('B', 11.0)):
            save_character_profile(name, {'template': 'human-default'}, create_new=True)
            set_character_pos(name, x, 10.0)

        calls = []

        def quiet(kind, key, members, location_id, room_id, *, offer=False):
            return ""

        def boom(kind, key, members, location_id, room_id, *, offer=False):
            raise RuntimeError("broken package")

        def hug(kind, key, members, location_id, room_id, *, offer=False):
            calls.append((kind, key, list(members), location_id, room_id, offer))
            if kind == "pose" and key == "hug":
                return {"reason": "privacy", "message": "not with others present"}
            return ""

        print('[1] no provider')
        check('check', participation.check('pose', 'hug', ['A', 'B'], '', ''), {})
        check('check_can_pair', IE.check_can_pair('A', 'B', 'hug'), '')

        print('[2] first refusal wins, a raising provider is skipped')
        for owner, fn in (('t_quiet', quiet), ('t_boom', boom), ('t_hug', hug)):
            register_provider(participation.CAPABILITY, fn, owner=owner, multiple=True)
        check('hug', participation.check('pose', 'hug', ['A', 'B'], '', ''),
              {'reason': 'privacy', 'message': 'not with others present'})
        check('wave', participation.check('pose', 'wave', ['A', 'B'], '', ''), {})

        print('[3] check_can_pair asks only with a pose')
        calls.clear()
        check('without pose', IE.check_can_pair('A', 'B'), '')
        check('not asked', calls, [])
        check('with pose', IE.check_can_pair('A', 'B', 'Hug'), 'not with others present')
        check('call', calls[-1], ('pose', 'hug', ['A', 'B'], '', '', False))

        print('[4] inside a room')
        with patch('app.models.character.get_character_current_location', return_value='loc1'), \
                patch('app.models.character.get_character_current_room', return_value='r1'):
            check('with pose', IE.check_can_pair('A', 'B', 'hug'), 'not with others present')
        check('call', calls[-1][3:5], ('loc1', 'r1'))

        print('[5] start_interaction')
        with patch.object(IE, 'pair_kind_for_pose', return_value='hug'), \
                patch('app.core.animation_clips.clip_meta', return_value={'duration_s': 2.0}), \
                patch('app.core.animation_clips.clip_loops', return_value=True):
            try:
                IE.start_interaction('A', 'B', 'hug')
                check('refused', 'started', 'ValueError')
            except ValueError as e:
                check('refused', str(e), 'not with others present')
            calls.clear()
            reserved = {'data': {'clip_roles': {'a': 'A', 'b': 'B'}}}
            try:
                IE.start_interaction('A', 'B', 'hug', _reserved=reserved)
            except Exception:
                pass  # what happens after the check is not this smoke's business
            check('reserved run not asked again', calls, [])

        print('[6] answer shapes')
        unregister_owned_providers('t_hug')
        register_provider(participation.CAPABILITY,
                          lambda *a, **k: {'reason': 'sated'}, owner='t_bare', multiple=True)
        check('no message', participation.check('pose', 'x', ['A'], '', ''),
              {'reason': 'sated', 'message': 'sated'})
        unregister_owned_providers('t_bare')
        for owner, answer in (('t_list', ['privacy']), ('t_empty', {'reason': ''})):
            register_provider(participation.CAPABILITY,
                              lambda *a, _r=answer, **k: _r, owner=owner, multiple=True)
            check(owner, participation.check('pose', 'x', ['A'], '', ''), {})
            unregister_owned_providers(owner)
        for owner in ('t_quiet', 't_boom'):
            unregister_owned_providers(owner)

    print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
