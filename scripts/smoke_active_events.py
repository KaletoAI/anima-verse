"""Usage: ./.venv/bin/python scripts/smoke_active_events.py
SQL must discard the expired row before Python decoding: two rows, exactly one decode.
No expiry, empty expiry, and equality with now remain active.
At 501e30cc, _row_to_event swallowed invalid/empty JSON and returned an
active event with row id, created_at and game_ts; these rows remain returned.
Valid non-object JSON instead raised, triggering the events.json fallback;
absent/unreadable fallback returned [], so such rows contributed no worldmap
markers. Skip them without reading that file, preserving valid DB events.
The null/[]/string/number rows count as zero _row_to_event decodes (SQL
rejects them); the valid active row still counts as exactly one decode.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
from app.core import paths
paths.init(Path(_tmp.name))
from app.core import db
db.init_schema()
import json
from app.models import events
from app.core.game_time import GameTime
now = GameTime.parse('Y0002-D100T12:00:00')
def insert(pid, expiry):
    payload = {'id': pid, 'location_id': 'site', 'category': 'danger', 'text': pid}
    if expiry is not None:
        payload['expires_at'] = expiry
    with db.transaction() as conn:
        conn.execute("INSERT INTO events(kind, ts, game_ts, payload) VALUES ('world_event', ?, ?, ?)", ('stamp', now.canonical(), json.dumps(payload)))
insert('expired', 'Y0002-D100T11:00:00')
insert('active', 'Y0002-D100T13:00:00')
with db.transaction() as conn:
    for payload in ('null', '[]', '"x"', '3'):
        conn.execute("INSERT INTO events(kind, ts, game_ts, payload) VALUES ('world_event', ?, ?, ?)", ('stamp', now.canonical(), payload))
with patch.object(events, 'game_time', return_value=now), patch.object(events, '_row_to_event', wraps=events._row_to_event) as decode:
    assert [e['id'] for e in events.list_active_world_events()] == ['active']
    assert decode.call_count == 1, decode.call_count
    from app.core.world_ops import build_worldmap_payload
    assert build_worldmap_payload(show_all=True)['events_by_location']['site'] == [{'category': 'danger', 'text': 'active'}]
insert('forever', None)
insert('empty', '')
insert('equal', now.canonical())
insert('malformed', 'broken')
insert('zero', 0)
insert('invalid-clock', 'Y0001-D100T99:00:00')
with patch.object(events, 'game_time', return_value=now):
    assert {e['id'] for e in events.list_active_world_events()} == {'active', 'forever', 'empty', 'equal', 'malformed', 'zero', 'invalid-clock'}
with db.transaction() as conn:
    invalid_ids = []
    for payload in ('{invalid', ''):
        row = conn.execute("INSERT INTO events(kind, ts, game_ts, payload) VALUES ('world_event', ?, ?, ?)", ('stamp', now.canonical(), payload))
        invalid_ids.append(str(row.lastrowid))
with patch.object(events, 'game_time', return_value=now), patch.object(events, '_row_to_event', wraps=events._row_to_event) as decode:
    active = events.list_active_world_events()
    assert len(active) == 9
    assert decode.call_count == 9, decode.call_count
    assert [e for e in active if e['id'] in invalid_ids] == [
        {'id': pid, 'created_at': 'stamp', 'game_ts': now.canonical()}
        for pid in invalid_ids]
    assert build_worldmap_payload(show_all=True)['events_by_location']['site'] == [
        {'category': 'danger', 'text': pid}
        for pid in ('active', 'forever', 'empty', 'equal', 'malformed', 'zero', 'invalid-clock')]
print('smoke_active_events: OK')
