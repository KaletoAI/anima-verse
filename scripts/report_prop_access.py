#!/usr/bin/env python3
"""Read-only prop-action access census for a STOPPED world.

Usage: ./.venv/bin/python scripts/report_prop_access.py --storage <world dir> [--out <file.md>]

Run with the server stopped, including servers started outside start.sh. Like
config_history.py, the repository's .pids/main.pid guard refuses a running
server (conservatively even if it serves another world). The database and WAL
are copied into a private temporary snapshot, opened mode=ro, query_only, so
even SQLite sidecar creation cannot modify the source. No schema migration runs.
A 170cm reference figure determines measured bridge travel. Reachability starts
at the room's full-rule-free candidate nearest its vertex mean (ties X/Z).
Disconnected room parts can therefore report no_route; occupancy is excluded.
Every action/marker/slot/role is listed. Status uses runtime slot_route; geometry
and bridge obstruction diagnostics use the runtime spaces, with <=1mm bridge
sampling for the reported penetration, never for admission. Clearance deficit
means displacement out of the grown keepout, rounded to cm. Own footprint
is explicitly exempt context, never a final-rule obstruction.
"""
import argparse
from collections import Counter, defaultdict
import math
from pathlib import Path
import sqlite3
import shutil
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cell(value):
    return str(value).replace('|', r'\|').replace('\n', ' ')


def report():
    from app.core import places
    from app.core.prop_action_access import slot_access
    from app.core.prop_action_paths import _VisibilityGraph, slot_route, access_obstructions
    from app.core.i18n import localized
    from app.models.world import list_locations

    lines = ['# Prop action access', '', 'Reference figure: **170 cm**. Full-rule room origin; no occupancy checks.',
             'Deficits: cm to leave the grown keepout; bridge penetration sampled at ≤1 mm. Own footprint is exempt.', '']
    totals = Counter()
    groups = defaultdict(Counter)
    query = places._GeometryQuery()
    for location in sorted(list_locations(), key=lambda x: (localized(x, 'name', 'de'), x['id'])):
        location_lines = []
        for room in sorted(location.get('rooms', []), key=lambda x: (localized(x, 'name', 'de'), x['id'])):
            inventory = query.room_places(location['id'], room['id'])
            actionable = [p for p in inventory if p.get('placement_id') and p.get('action_bindings')]
            if not actionable:
                continue
            geometry = query.room_geometry(location['id'], room['id'])
            graph = _VisibilityGraph(geometry) if geometry else None
            origin = None
            if graph and graph.space.valid:
                poly = graph.space.poly
                center = tuple(sum(p[i] for p in poly) / len(poly) for i in (0, 1))
                candidates = [center, *graph.space.candidates]
                candidates = [tuple(round(v, 2) for v in p) for p in candidates]
                free = [p for p in candidates if graph.space.free(p)]
                if free:
                    origin = min(free, key=lambda p: (math.dist(center, p), p))
            rows = []
            placement_props = {p.get('id'): p.get('prop_id', '')
                               for p in (room.get('layout') or {}).get('props', [])}
            for place in sorted(actionable, key=lambda p: (p['placement_id'], p['marker_id'])):
                document = query.prop_document(place['prop_id'])
                label = localized(document, 'name', 'de') or place['prop_id']
                for binding in sorted(place['action_bindings'], key=lambda b: b['action_id']):
                    action = next((a for a in document.get('actions', []) if a['id'] == binding['action_id']), {})
                    for slot, anchor in enumerate(place['slots']):
                        for role in ('actor', 'partner') if action.get('participants') == 2 else ('actor',):
                            status, reason, details = 'blocked', '', []
                            access = None
                            if not binding.get('supported') or binding.get('validation') != 'local_valid':
                                reason = binding.get('reason') or 'binding_not_supported'
                            else:
                                try:
                                    access, reason = slot_access(place, slot, role, action, {'height': 170})
                                except (KeyError, TypeError, ValueError, OverflowError):
                                    reason = 'invalid_binding_geometry'
                                if not reason:
                                    if graph is None:
                                        reason = 'room_geometry_unavailable'
                                    elif not graph.space.valid:
                                        reason = 'invalid_room_geometry'
                                    elif origin is None:
                                        reason = 'start_not_walkable'
                                    else:
                                        _, status, reason = slot_route(origin, access, anchor, geometry,
                                            place['placement_id'], graph=graph)
                            if status != 'bridge' and access and geometry:
                                obstructions = access_obstructions(access, anchor, geometry, place['placement_id'])
                                if reason == 'no_route' and origin is not None:
                                    # Explain the failed straight line, without claiming this
                                    # diagnostic alone proves the whole component disconnected.
                                    route_obstructions = access_obstructions(
                                        dict(x=origin[0], z=origin[1]), (access['x'], access['z']),
                                        geometry, place['placement_id'], final_rules=False)
                                    for item in route_obstructions:
                                        item['route'] = True
                                    obstructions += route_obstructions
                                for obstruction in obstructions:
                                    kind = obstruction['kind']
                                    if kind == 'furniture':
                                        other_id = obstruction['placement_id']
                                        other = next((p for p in inventory if p.get('placement_id') == other_id), None)
                                        # Non-action furniture has no place; resolve through the room recipe below.
                                        pid = other['prop_id'] if other else placement_props.get(other_id, '')
                                        kind = localized(query.prop_document(pid), 'name', 'de') or pid or other_id
                                    missing = obstruction['missing_m']
                                    prefix = 'straight route: ' if obstruction.get('route') else ''
                                    details.append(prefix + kind + (f': {missing * 100:.1f} cm' if missing is not None else ''))
                            totals[status] += 1
                            groups[place['group']][status] += 1
                            rows.append([label, place['placement_id'], place['marker_id'], slot,
                                         binding['action_id'], role, place['group'], status, reason,
                                         '; '.join(details)])
            location_lines += [f"### {cell(localized(room, 'name', 'de') or room['id'])}", '',
                               f"Routing origin (m): `{origin}`", '',
                               '| Furniture | Placement | Marker | Slot | Action | Role | Group | Status | Reason | Clearance deficit / cause |',
                               '|---|---|---|---:|---|---|---|---|---|---|']
            location_lines += ['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows]
            location_lines.append('')
        if location_lines:
            lines += [f"## {cell(localized(location, 'name', 'de') or location['id'])}", '', *location_lines]
    lines += ['## Totals', '', '| Group | bridge | direct | blocked | Total |', '|---|---:|---:|---:|---:|']
    for group, counts in [('All', totals), *((g, groups[g]) for g in ('seat', 'lie', 'stand', 'ground'))]:
        lines.append(f"| {group} | {counts['bridge']} | {counts['direct']} | {counts['blocked']} | {sum(counts.values())} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', required=True, type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    from config_history import _server_running
    if _server_running(Path(__file__).resolve().parents[1] / '.pids/main.pid'):
        parser.error('server is running; stop it before reading a world')
    database = args.storage.resolve() / 'world.db'
    if not database.is_file():
        parser.error(f'world.db not found: {database}')
    if args.out and args.out.resolve() == database:
        parser.error('--out must not overwrite world.db')
    from app.core import paths
    paths.init(args.storage)
    from app.core import db
    # A mode=ro connection can still create WAL/SHM sidecars. Read a stopped
    # world's DB + outstanding WAL as bytes, then let SQLite open only a copy.
    with tempfile.TemporaryDirectory(prefix='prop-access-report-') as temporary:
        snapshot = Path(temporary) / 'world.db'
        shutil.copyfile(database, snapshot)
        wal = database.with_name(database.name + '-wal')
        if wal.is_file():
            shutil.copyfile(wal, snapshot.with_name(snapshot.name + '-wal'))
        connection = sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        original = db.get_connection
        db.get_connection = lambda: connection
        try:
            output = report()
        finally:
            db.get_connection = original
            connection.close()
    if args.out:
        args.out.write_text(output, encoding='utf-8')
    else:
        print(output, end='')


if __name__ == '__main__':
    main()
