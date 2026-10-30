#!/usr/bin/env python3
"""Offer equivalence and visibility work in a private, partitioned room.

Usage: ./.venv/bin/python scripts/smoke_prop_action_offers_cost.py

The reused fixture calls paths.init(tempdir) before any world-DB import.
A full-depth divider at x=6 separates the actor (1,3.5) from nine seats.
Nine placements are beyond the divider; one is on the actor's side. Three slots per seat force
repeated planning. No full-rule route can cross the divider, including the
direct-entry fallback. Expected offers: one enabled and nine no_route.
The explicit 6674717a module supplies the independent old routing baseline;
restoring per-candidate endpoint linking must fail the >=10x work assertion.
"""
import subprocess
import types
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import smoke_prop_action_runs as S
from app.core import paths
# The fixture already initialized this private root before its DB imports.
# Keep the redirect explicit here for the standalone script storage guard.
paths.init(S.F.ROOT / 'world')
from app.core import prop_actions as offers_api
F, A = S.F, S.A


def fixture():
    name, target, pid = S.setup_run()
    doc = F.props.read_sidecar(pid)
    doc['model_variants'][0]['markers'][0].update(capacity=3, spacing_m=.2)
    F.props._write_sidecar(pid, doc)
    divider = F.furniture_prop('Divider', width=.2, depth=10, height=1)
    loc = F.W.get_location_by_id(target['location_id'])
    layout = loc['rooms'][0]['layout']
    layout['props'] = [dict(id='divider', prop_id=divider, at=[6, 5])]
    layout['props'] += [dict(id=f'seat-{i}', prop_id=pid, at=at)
                        for i, at in enumerate([(3, 5)] + [(x, z) for x in (7.5, 9, 10.5) for z in (2, 5, 8)])]
    F.W.upsert_location(loc, sync_world=True)
    F.C.set_character_pos(name, 1, 3.5)
    F.places.invalidate()
    return name


def counted(module, name):
    count = 0
    free_count = 0
    original = module._Space.visible
    original_free = module._Space.free

    def visible(self, a, b):
        nonlocal count
        count += 1
        return original(self, a, b)

    def free(self, point):
        nonlocal free_count
        free_count += 1
        return original_free(self, point)

    # Each measurement is cold, including the server-side offer cache.
    offers_api.invalidate_offers_cache()
    with patch.object(module._Space, 'visible', visible), patch.object(module._Space, 'free', free), patch.object(
            module._VisibilityGraph, '_build_graph', autospec=True,
            side_effect=module._VisibilityGraph._build_graph) as graphs, patch.object(
            F.S, 'approach_departure', wraps=F.S.approach_departure) as starts, patch.object(
            F.N, 'plan_approach', module.plan_approach):
        result = offers_api.offers(name)
    return result, count, (graphs.call_count, starts.call_count), free_count


def cache_and_refusals():
    """Cached reads cannot hide lifecycle, profile, freeze or author changes."""
    name, target, pid = S.setup_run()
    expected = offers_api.offers(name)
    assert expected[0]['enabled'], expected
    # Some cold catalog readers seed DB defaults; warm that fresh version too.
    expected = offers_api.offers(name)
    with patch.object(A, '_plan', side_effect=AssertionError('cached offer planned')):
        cached = offers_api.offers(name)
        assert cached == expected
        cached[0]['effects'].append({'mutation': 'caller'})
        assert offers_api.offers(name) == expected
    with patch.object(offers_api, 'monotonic', return_value=offers_api.monotonic() + 4), patch.object(
            A, '_plan', wraps=A._plan) as planning:
        assert offers_api.offers(name) == expected
        assert planning.call_count > 0, 'expired cache reused'
    request = S.request(name, target)
    assert request['status'] == 'approaching', request
    with patch.object(A, '_plan', side_effect=AssertionError('refused offer planned')):
        rows = offers_api.offers(name)
        assert rows[0]['reason'] == 'participant_claimed', rows
        F.W.set_world_frozen(True)
        assert offers_api.offers(name)[0]['reason'] == 'world_frozen'
        F.W.set_world_frozen(False)
        doc = F.props.read_sidecar(pid)
        doc['actions'][0]['enabled'] = False
        F.props._write_sidecar(pid, doc)
        # Definition validity precedes both frozen state and participant claims.
        F.W.set_world_frozen(True)
        assert offers_api.offers(name)[0]['reason'] == 'action_disabled'
        F.W.set_world_frozen(False)
        doc['actions'][0]['enabled'] = True
        F.props._write_sidecar(pid, doc)
    A.cancel(name, request['execution_id'])
    assert offers_api.offers(name)[0]['enabled']
    # Bypass action writers: data_version must notice another connection's
    # write even without process-local invalidation callbacks.
    import sqlite3
    with sqlite3.connect(str(F.db.get_db_path())) as conn:
        conn.execute("UPDATE characters SET status='unavailable' WHERE name=?", (name,))
    with patch.object(A, '_plan', side_effect=AssertionError('unavailable actor planned')):
        assert offers_api.offers(name)[0]['reason'] == 'participant_unavailable'
    with sqlite3.connect(str(F.db.get_db_path())) as conn:
        conn.execute("UPDATE characters SET status='' WHERE name=?", (name,))
    doc['actions'][0]['requirements'] = [dict(
        id='energy', target='actor', type='stat', stat='run_energy', op='ge', value=51)]
    F.props._write_sidecar(pid, doc)
    with patch.object(A, '_plan', side_effect=AssertionError('unmet requirement planned')):
        assert offers_api.offers(name)[0]['reason'] == 'requirement_not_met'
    print('PASS: cache hit, copy isolation, TTL, claims, freeze, definition precedence, requirements and external DB writes')


def route_equivalence(old):
    """Compare exact waypoint/tie decisions, not only enabled projections."""
    box = dict(at=[6, 5], width_m=2, depth_m=2, placement_id='table')
    for polygon, blockers in ((F.SQUARE, [box]), (F.L_ROOM, [])):
        geometry = (polygon, blockers, [])
        graph = F.N._VisibilityGraph(geometry)
        baseline = old._VisibilityGraph(geometry)
        reached = F.N._Reachability(graph, (1, 5))
        for goal in ((1, 5), (11, 5), (9, 7), (6, 5), (3, 2), (3, 8)):
            assert reached.route(goal) == baseline.route((1, 5), goal)
            final = F.N.access_space(geometry, 'table')
            assert reached.route(goal, final_space=final) == baseline.route((1, 5), goal, final_space=final)
    geometry = (F.SQUARE, [], [])
    assert F.N.slot_route(('1', '1'), {'x': 2, 'z': 2}, (3, 3), geometry, '') == old.slot_route(
        ('1', '1'), {'x': 2, 'z': 2}, (3, 3), geometry, '')
    tiny = ([(0, 0), (.71, 0), (.71, .71), (0, .71)], [], [])
    for start in (None, (1,), ('bad', 1), (float('nan'), 1)):
        assert F.N.slot_route(start, {'x': .355, 'z': .355}, (.355, .355), tiny, '') == old.slot_route(
            start, {'x': .355, 'z': .355}, (.355, .355), tiny, '')
    print('PASS: exact routes, zero distance, lexical ties, concave walls, relaxed final edges and endpoint contract')


def late_reachable_candidate(old):
    """A wall at x=6 spans z=[0,10] (keepout x in [5.6, 6.4]); the actor is at (1,5).

    The anchor (6.6,5) lies on the far side. Its .05 m rings up to r=1.0 are
    free only on the far side, so every early candidate is unreachable. The
    first near-side point is r=1.05 at 165 deg: (6.6+1.05cos165, 5+1.05sin165)
    = (5.5858, 5.2718), 0.014 m left of the keepout and straight-visible from
    the actor. More than 24 unreachable candidates precede it, so a fixed
    candidate cap would wrongly report no_route. The access lies outside the
    room, so every counted route call is one fallback candidate.
    """
    geometry = (F.SQUARE, [dict(at=[6, 5], width_m=.2, depth_m=10)], [])
    graph = F.N._VisibilityGraph(geometry)
    reached = F.N._Reachability(graph, (1, 5))
    with patch.object(reached, 'route', wraps=reached.route) as routes:
        result = F.N.slot_route((1, 5), dict(x=-1, z=5), (6.6, 5), geometry, '',
                               graph=graph, reachability=reached)
    route, mode, reason = result
    assert mode == 'direct' and reason == 'access_not_walkable', result
    assert route[0] == (1.0, 5.0) and len(route) == 2, route
    assert abs(route[1][0] - 5.5858) < 1e-3 and abs(route[1][1] - 5.2718) < 1e-3, route
    assert routes.call_count > 24, routes.call_count
    assert result == old.slot_route((1, 5), dict(x=-1, z=5), (6.6, 5), geometry, ''), result
    print(f'PASS: reachable candidate ranked {routes.call_count} still routes direct, like 6674717a')


def query_reuse():
    """Two identical actions per placement must route each actual slot once."""
    name = fixture()
    query = F.places._GeometryQuery(cache_profiles=True)
    location, room = F.places.where(name, profile=query.profile(name))
    inventory = query.room_places(location, room)
    pid = next(p['prop_id'] for p in inventory if p['placement_id'] == 'seat-0')
    doc = F.props.read_sidecar(pid)
    doc['actions'].append(dict(doc['actions'][0], id='second-rest'))
    F.props._write_sidecar(pid, doc)
    query = F.places._GeometryQuery(cache_profiles=True)
    offers_api.invalidate_offers_cache()
    with patch.object(F.places, '_GeometryQuery', return_value=query), patch.object(
            F.N, 'slot_route', wraps=F.N.slot_route) as slots:
        rows = offers_api.offers(name)
    assert len(rows) == 20 and sum(row['enabled'] for row in rows) == 2, rows
    assert slots.call_count == 30, slots.call_count  # 10 placements x 3 slots, not 60.
    # Different access points cannot share slot results, but DO share the
    # ordered free points at their common anchor within the same query.
    geometry = query.room_geometry(location, room)
    key = (location, room, id(geometry))
    graph = query._action_graphs[key]
    start = (1, 3.5)
    reached = F.N._Reachability(graph, start)
    anchor = (10.5, 8)  # Right of the full-height divider, inside its chair.
    original = F.N._Space.nearby_free
    with patch.object(F.N._Space, 'nearby_free', autospec=True, side_effect=original) as samples:
        first = F.N._query_slot_route(query, key, start, dict(x=-1, z=5), anchor,
                                     geometry, 'seat-9', graph, reached)
        second = F.N._query_slot_route(query, key, start, dict(x=-2, z=5), anchor,
                                      geometry, 'seat-9', graph, reached)
    assert first == second == (None, 'blocked', 'no_route'), (first, second)
    # The earlier real offer already sampled this anchor, so neither new
    # access may regenerate it. A fresh query must still plan independently.
    assert samples.call_count == 0, samples.call_count
    offers_api.invalidate_offers_cache()
    assert offers_api.offers(name) == rows
    print('PASS: duplicate actions reuse 30 slot results; changed access reuses anchor candidates; fresh query agrees')


def main():
    old = types.ModuleType('prop_action_paths_6674717a')
    source = subprocess.check_output(['git', 'show', '6674717a:app/core/prop_action_paths.py'], text=True)
    exec(compile(source, '<6674717a:prop_action_paths>', 'exec'), old.__dict__)
    route_equivalence(old)
    late_reachable_candidate(old)
    name = fixture()
    before, old_calls, old_reuse, old_free = counted(old, name)
    after, new_calls, new_reuse, new_free = counted(F.N, name)
    assert new_reuse == (1, 1), new_reuse
    print(f"Graph builds / departure reads: old={old_reuse}, current={new_reuse}", flush=True)
    assert after == before, (before, after)
    assert len(after) == 10, after
    assert sum(row['enabled'] for row in after) == 1, after
    assert sum(row['reason'] == 'no_route' for row in after) == 9, after
    print(f'6674717a -> current visible/free: {old_calls}/{old_free} -> {new_calls}/{new_free}; visible reduction={old_calls / max(1, new_calls):.1f}x', flush=True)
    assert new_calls * 10 <= old_calls, (old_calls, new_calls)
    print('PASS: identical offers; >=10x fewer visibility calls')
    query_reuse()
    cache_and_refusals()
    F.assert_no_external_work()


if __name__ == '__main__':
    main()
