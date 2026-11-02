#!/usr/bin/env python3
"""States override character fields (plan-intim-privatsphaere.md, part A) —
against a temporary world only.

Usage: ./.venv/bin/python scripts/smoke_field_overrides.py

Fixture: one template ``demo`` with
  * ``privacy`` — select private/partners/open, default "private",
    ``state_override``, ``in_prompt`` (label "Privacy");
  * ``broken_text`` — text, ``state_override`` (not a select → ignored);
  * ``config_sel`` — select stored in ``config``, ``state_override`` (ignored);
and a second template ``other`` that defines ``privacy`` again with the
options x/y (first template wins, by file name order: ``demo`` < ``other``).
States (world rows, saved through the admin save): shy → private,
drunk → open, tipsy → partners, broken → "nope" (written raw, bypassing the
save, as an old row whose option has since gone), off → open but disabled,
focused → stat boost attention +40 (refactor check).
The game clock stands at T = Y0001-D010T12:00:00.

[1] Overridable fields: exactly ``privacy`` (2 fields marked but invalid are
    skipped), with the demo options private/partners/open, not x/y.
[2] No condition: no override; effective = stored "partners"; a profile
    without the key gets the default "private".
[3] drunk started T-2h, no duration → "open", source state drunk.
[4] drunk T-2h + shy T-1h → shy started later → "private".
[5] drunk + tipsy both T-1h (tie) → alphabetically first id: drunk → "open".
[6] drunk T-2h for 1h → 2 > 1, expired; shy T-3h open-ended → "private".
[7] broken only → "nope" is no option → ignored → stored "partners".
[8] off only → disabled → ignored → stored "partners".
[9] a row without started_at counts as the oldest: drunk (no start) + shy
    T-4h → shy → "private".
[10] Prompt: build_prompt_section renders the EFFECTIVE value — under drunk
     "Privacy: open", stored "partners" without a state.
[11] Admin save: privacy=open saves and reloads; unknown field, unknown value,
     non-string value and a non-object are 400.
[12] states.zip export → wipe → import keeps field_overrides of drunk.
[13] Stat boosts after the active_states refactor: focused +40 started T-1h
     for 2h → attention 50 + 40 = 90; started T-3h for 2h → expired → 50.
"""
import io
import json
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
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['STORAGE_DIR'] = tmp
        os.environ['INSTANCE_DIR'] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from fastapi import HTTPException
        from app.core.db import init_schema, transaction
        from app.core.game_time import GameDuration, GameTime
        from app.core.timeutils import set_game_time, set_game_factor
        from app.core.field_overrides import active_overrides, effective_field
        from app.core.stat_boosts import effective_stat
        from app.core.prompt_filters import invalidate_filter_snapshot
        from app.core.content_io import export_states_to_zip, import_states_from_zip
        from app.models.character_template import (build_prompt_section, clear_template_cache,
                                                   state_override_fields)
        from app.routes.admin_settings import _prompt_filters_save_sync
        init_schema()
        set_game_factor(0)
        T = 'Y0001-D010T12:00:00'
        set_game_time(GameTime.parse(T))

        sel = [{'value': 'private', 'label': 'Private'}, {'value': 'partners', 'label': 'Partners'},
               {'value': 'open', 'label': 'Open'}]
        demo = {'sections': [{'fields': [
            {'key': 'privacy', 'label': 'Privacy', 'type': 'select', 'options': sel,
             'default': 'private', 'state_override': True, 'in_prompt': True},
            {'key': 'broken_text', 'type': 'text', 'state_override': True},
            {'key': 'config_sel', 'type': 'select', 'store': 'config', 'options': ['a'],
             'state_override': True},
            {'key': 'attention', 'store': 'status_effects', 'default': 50}]}]}
        other = {'sections': [{'fields': [
            {'key': 'privacy', 'type': 'select', 'options': ['x', 'y'], 'state_override': True}]}]}
        tdir = Path(tmp) / 'templates'
        tdir.mkdir()
        (tdir / 'demo.json').write_text(json.dumps(demo))
        (tdir / 'other.json').write_text(json.dumps(other))

        with patch('app.models.character_template.get_templates_dir', return_value=tdir):
            clear_template_cache()
            print('[1] overridable fields')
            fields = state_override_fields()
            check('keys', [f['key'] for f in fields], ['privacy'])
            check('options', [o['value'] for o in fields[0]['options']], ['private', 'partners', 'open'])

            def save(fid, **kw):
                body = {'id': fid, 'label': fid.title(), 'enabled': kw.pop('enabled', True), **kw}
                return _prompt_filters_save_sync(None, body)

            save('shy', field_overrides={'privacy': 'private'})
            save('drunk', field_overrides={'privacy': 'open'}, icon='🍷')
            save('tipsy', field_overrides={'privacy': 'partners'})
            save('off', field_overrides={'privacy': 'open'}, enabled=False)
            save('focused', stat_boosts={'attention': 40})
            with transaction() as conn:
                conn.execute("INSERT INTO prompt_filters (id, condition, label, enabled, meta) VALUES "
                             "('broken', '', 'Broken', 1, ?)",
                             (json.dumps({'field_overrides': {'privacy': 'nope'}}),))
            invalidate_filter_snapshot()

            def at(hours_ago):
                return GameTime.parse(T) - GameDuration.of(hours=hours_ago)

            def cond(name, hours_ago=None, duration=0):
                row = {'name': name, 'duration_hours': duration}
                if hours_ago is not None:
                    row['started_at'] = str(at(hours_ago))
                return row

            def prof(*conds, **extra):
                return {'privacy': 'partners', 'active_conditions': list(conds),
                        'status_effects': {'attention': 50}, **extra}

            print('[2] no condition')
            check('overrides', active_overrides(prof()), {})
            check('effective', effective_field(prof(), 'privacy'), ('partners', None))
            check('default', effective_field({'active_conditions': []}, 'privacy')[0], 'private')

            print('[3] one state')
            v, src = effective_field(prof(cond('drunk', 2)), 'privacy')
            check('value', v, 'open')
            check('source', (src or {}).get('state'), 'drunk')
            check('icon', (src or {}).get('icon'), '🍷')

            print('[4] later start wins')
            check('value', effective_field(prof(cond('drunk', 2), cond('shy', 1)), 'privacy')[0], 'private')

            print('[5] tie → first id')
            check('value', effective_field(prof(cond('tipsy', 1), cond('drunk', 1)), 'privacy')[0], 'open')

            print('[6] expired')
            check('value', effective_field(prof(cond('drunk', 2, 1), cond('shy', 3)), 'privacy')[0], 'private')

            print('[7] invalid stored option')
            check('value', effective_field(prof(cond('broken', 1)), 'privacy')[0], 'partners')

            print('[8] disabled state')
            check('value', effective_field(prof(cond('off', 1)), 'privacy')[0], 'partners')

            print('[9] missing start = oldest')
            check('value', effective_field(prof(cond('drunk'), cond('shy', 4)), 'privacy')[0], 'private')

            print('[10] prompt renders the effective value')
            from app.models.character_template import get_template
            tmpl = get_template('demo')
            lines = build_prompt_section(tmpl, prof(cond('drunk', 2)))
            check('drunk', [l for l in lines if l.startswith('Privacy')], ['Privacy: open'])
            lines = build_prompt_section(tmpl, prof())
            check('stored', [l for l in lines if l.startswith('Privacy')], ['Privacy: partners'])

            print('[11] admin validation')
            from app.core.prompt_filters import load_filters
            got = {f['id']: f.get('field_overrides') for f in load_filters()}
            check('drunk saved', got.get('drunk'), {'privacy': 'open'})
            for label, bad in [('unknown field', {'mood': 'open'}),
                               ('unknown value', {'privacy': 'loud'}),
                               ('non-string', {'privacy': 1}),
                               ('non-object', ['privacy'])]:
                try:
                    save('bad', field_overrides=bad)
                    check(label, 'saved', 400)
                except HTTPException as e:
                    check(label, e.status_code, 400)

            print('[12] states.zip round trip')
            blob = export_states_to_zip()
            import_states_from_zip(blob, replace_all=True)
            invalidate_filter_snapshot()
            got = {f['id']: f.get('field_overrides') for f in load_filters()}
            check('drunk after import', got.get('drunk'), {'privacy': 'open'})

            print('[13] stat boosts unchanged')
            check('active', effective_stat(prof(cond('focused', 1, 2)), 'attention'), 90)
            check('expired', effective_stat(prof(cond('focused', 3, 2)), 'attention'), 50)

    print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
