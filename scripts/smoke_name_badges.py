#!/usr/bin/env python3
"""Icons behind a character's name (plan-intim-privatsphaere.md, part E) —
against a temporary world only.

Usage: ./.venv/bin/python scripts/smoke_name_badges.py

Contributors are fakes registered on ``character.name_badges``:
  good  → A: [{icon "🔒", title "Private", title_de "Privat"}], others: []
  boom  → raises
  junk  → [ "str", {icon ""}, {title "no icon"}, {icon " ⭐ ", title 5} ]
  notal → "x" (not a list)

[1] No contributor: badges_for → [], badges_map → {}.
[2] Order and isolation: A in English → [🔒 "Private", ⭐ ""] — boom and notal
    are skipped, of junk only the stripped "⭐" survives (title 5 is no string
    → ""). In German the first title is "Privat".
[3] badges_map(["A", "B"]): junk badges everyone, so {"A": [🔒, ⭐],
    "B": [⭐]}; with junk unregistered B has none and drops out → {"A": [🔒]}.
[4] Worldmap (avatar A, language "en"): A's row carries badges
    [{🔒, "Private"}]; B's row has no "badges" key at all.
[5] Scene (avatar A, B addressable, language "de"):
    present_badges == {"B": [{🔒, "Privat"}]} with a contributor that badges B.
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
        from app.core.hooks import register_provider, unregister_owned_providers
        from app.core.name_badges import CAPABILITY, badges_for, badges_map
        from app.models.character import save_character_profile

        LOCK = {"icon": "🔒", "title": "Private", "title_de": "Privat"}

        def good(name, profile):
            return [dict(LOCK)] if name == "A" else []

        def good_b(name, profile):
            return [dict(LOCK)] if name == "B" else []

        def boom(name, profile):
            raise RuntimeError("broken package")

        def junk(name, profile):
            return ["str", {"icon": ""}, {"title": "no icon"}, {"icon": " ⭐ ", "title": 5}]

        def notal(name, profile):
            return "x"

        print('[1] no contributor')
        check('badges_for', badges_for('A', profile={}), [])
        check('badges_map', badges_map(['A', 'B']), {})

        print('[2] order and isolation')
        for owner, fn in (('t_good', good), ('t_boom', boom), ('t_junk', junk), ('t_notal', notal)):
            register_provider(CAPABILITY, fn, owner=owner, multiple=True)
        check('en', badges_for('A', profile={}, lang='en'),
              [{'icon': '🔒', 'title': 'Private'}, {'icon': '⭐', 'title': ''}])
        check('de title', badges_for('A', profile={}, lang='de')[0]['title'], 'Privat')

        print('[3] badges_map')
        check('with junk', {k: [b['icon'] for b in v] for k, v in badges_map(['A', 'B']).items()},
              {'A': ['🔒', '⭐'], 'B': ['⭐']})
        unregister_owned_providers('t_junk')
        check('without junk', {k: [b['icon'] for b in v] for k, v in badges_map(['A', 'B']).items()},
              {'A': ['🔒']})

        print('[4] worldmap rows')
        save_character_profile('A', {'template': 'human-default', 'language': 'en'}, create_new=True)
        save_character_profile('B', {'template': 'human-default', 'language': 'en'}, create_new=True)
        # A row needs a place on the map: a free metre point in the open.
        from app.models.character import set_character_pos
        set_character_pos('A', 10.0, 10.0)
        set_character_pos('B', 12.0, 10.0)
        from app.core.world_ops import build_worldmap_payload
        rows = {c['name']: c for c in build_worldmap_payload('A', show_all=True).get('characters', [])}
        check('A badges', (rows.get('A') or {}).get('badges'), [{'icon': '🔒', 'title': 'Private'}])
        check('B has no key', 'badges' in (rows.get('B') or {'badges': 1}), False)

        print('[5] scene present_badges')
        unregister_owned_providers('t_good')
        register_provider(CAPABILITY, good_b, owner='t_good_b', multiple=True)
        save_character_profile('A', {'language': 'de'})
        from app.routes import play
        with patch('app.models.account.get_active_character', return_value='A'), \
                patch('app.routes.play.get_active_character', return_value='A', create=True), \
                patch('app.core.perception.addressable_for', return_value=['B']):
            payload = play.play_scene(user={'role': 'admin', 'username': 'demo'}, limit=5)
        check('present', payload.get('present'), ['B'])
        check('present_badges', payload.get('present_badges'), {'B': [{'icon': '🔒', 'title': 'Privat'}]})
        for owner in ('t_good_b', 't_boom', 't_notal'):
            unregister_owned_providers(owner)

    print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
