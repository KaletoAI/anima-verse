#!/usr/bin/env python3
"""Pure bus smoke, with hand-derived expectations; no DB/server imports.

All cases are NEU: sync_topics is absent on a241a8aa (ModuleNotFoundError).
thread: one broadcast = one presence, wake >=1. bundle: p,s,p => p,s.
fog_move: X/Y recipients hit a/b, never Z; perceivers/owner hit only a.
world hits all three; wilderness empty location hits nobody.
overflow: 64+1 >64 => exactly one all-five resync, then empty.
rebind_drops_queue/rebind_race: old-avatar signals cannot survive a switch.
stale_recheck/stale_location: changed revision rejects the entire stale write.
reconcile_race: A/X read loses to A/Z move; fresh B/Y read wins with resync.
note_location: revision +1, no resync, only new location matches.
lag_pending/lag_inflight: t=29 is safe, t=31 exceeds 30; delivered clears
only in-flight. lag_interleaved: B queued at 1 is 31 seconds old at 32,
even if A was delivered at 29. never_raises: failing callbacks are contained.
register_resync: first take is exactly the five topics with resync=True.
NEU initial_resync_lag: registration at 0 remains pending until 31 => reaped.
NEU zero_timestamp: signal at 0 taken at 10 still ages from 0 => reaped at 31;
the snippet must not replace the valid timestamp 0.0 with the take time.
"""
import sys
import threading
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import sync_topics as b

ALL = ['presence', 'scene', 'notices', 'self', 'world']
t = [0.0]
b._clock = lambda: t[0]


def fresh(name='a', loc='X', **kw):
    c = b.register('demo', 'token', name, loc, **kw)
    assert c.take() == (ALL, True)
    c.delivered()
    return c


def case(name, fn):
    for c in b.connections():
        b.unregister(c)
    t[0] = 0.0
    fn()
    print('PASS', name)


def thread():
    wakes = []
    c = fresh(wake=lambda: wakes.append(1))
    th = threading.Thread(target=lambda: b.notify('presence', to=b.Everyone()))
    th.start(); th.join(2)
    assert not th.is_alive()
    assert c.take() == (['presence'], False) and wakes


def bundle():
    c = fresh()
    for topic in ['presence', 'scene', 'presence']:
        b.notify(topic, to=b.Everyone())
    assert c.take() == (['presence', 'scene'], False)


def recipients(kind):
    cs = [fresh(n, loc) for n, loc in [('a', 'X'), ('b', 'Y'), ('c', 'Z')]]
    topic, to, hit = {
        'fog_move': ('presence', [b.AtLocation('X'), b.AtLocation('Y'), b.Avatar('npc')], [0, 1]),
        'perceivers': ('scene', b.Avatars(('a',)), [0]),
        'owner': ('notices', b.Avatar('a'), [0]),
        'world': ('world', b.Everyone(), [0, 1, 2]),
    }[kind]
    b.notify(topic, to=to)
    assert [c.take() for c in cs] == [([topic] if i in hit else [], False) for i in range(3)]


def wilderness():
    c = fresh(loc='')
    b.notify('presence', to=b.AtLocation(''))
    assert c.take() == ([], False)


def overflow():
    c = fresh()
    for _ in range(65):
        b.notify('presence', to=b.Everyone())
    assert c.take() == (ALL, True)
    assert c.take() == ([], False)


def rebind_drops_queue():
    c = fresh('old')
    for _ in range(3):
        b.notify('scene', to=b.Avatar('old'))
    b.rebind(c, 'new', 'Y')
    assert c.take() == (ALL, True)
    c.delivered()
    b.notify('scene', to=b.Avatar('old'))
    assert c.take() == ([], False)
    b.notify('presence', to=b.Avatar('new'))
    assert c.take() == (['presence'], False)


def rebind_race():
    c = fresh('old')
    entered, resume = threading.Event(), threading.Event()
    def hook():
        entered.set()
        assert resume.wait(2)
    b._before_offer = hook
    th = threading.Thread(target=lambda: b.notify('scene', to=b.Avatar('old')))
    try:
        th.start()
        assert entered.wait(2)
        b.rebind(c, 'new', 'Y')
        assert c.take() == (ALL, True)
        c.delivered()
    finally:
        resume.set(); th.join(2); b._before_offer = None
    assert c.take() == ([], False)


def stale_recheck():
    c = fresh('A')
    r = c.binding()[2]
    b.rebind(c, 'B', 'Y')
    assert b.rebind(c, 'A', 'X', expect_rev=r) is False
    assert c.binding()[:2] == ('B', 'Y')


def reconcile_race():
    c = fresh('A')
    account, character = ModuleType('app.models.account'), ModuleType('app.models.character')
    reads = []
    def active(uid):
        reads.append(uid)
        return 'A' if len(reads) == 1 else 'B'
    def location(avatar):
        if avatar == 'A':
            b.note_location('A', 'Z')
            return 'X'
        return 'Y'
    account.get_active_character_for_user = active
    character.get_character_current_location = location
    with patch.dict(sys.modules, {'app.models.account': account, 'app.models.character': character}):
        assert b.reconcile(c)
    assert len(reads) == 2 and c.binding()[:2] == ('B', 'Y')
    assert c.take() == (ALL, True)
    c.delivered()
    b.notify('scene', to=b.AtLocation('Z'))
    assert c.take() == ([], False)


def location_case(stale=False):
    c = fresh()
    r = c.binding()[2]
    if stale:
        entered, resume = threading.Event(), threading.Event()
        result = []
        def stale_read():
            rev = c.binding()[2]
            entered.set()
            assert resume.wait(2)
            result.append(b.rebind(c, 'a', 'X', expect_rev=rev))
        th = threading.Thread(target=stale_read)
        th.start()
        try:
            assert entered.wait(2)
            b.note_location('a', 'Y')
        finally:
            resume.set()
            th.join(2)
        assert result == [False]
    else:
        b.note_location('a', 'Y')
    assert c.binding() == ('a', 'Y', r + 1)
    assert c.take() == ([], False)
    b.notify('scene', to=b.AtLocation('X'))
    assert c.take() == ([], False)
    b.notify('presence', to=b.AtLocation('Y'))
    assert c.take() == (['presence'], False)


def lag(kind, delivered=False):
    aborted = []
    c = fresh(abort=lambda: aborted.append(1))
    b.notify('presence', to=b.Everyone())
    if kind != 'pending':
        c.take()
    if kind == 'interleaved':
        t[0] = 1
        b.notify('scene', to=b.Everyone())
        t[0] = 29
        c.delivered()
    elif delivered:
        t[0] = 1
        c.delivered()
    t[0] = 29
    assert b.reap() == 0
    t[0] = 32 if kind == 'interleaved' else 31
    assert b.reap() == (0 if delivered else 1)
    assert c.closed == (not delivered)
    assert aborted == ([] if delivered else [1])


def initial_resync_lag():
    c = b.register('demo', 'token', 'a', 'X')
    t[0] = 31
    assert b.reap() == 1 and c.closed


def zero_timestamp():
    c = fresh()
    b.notify('scene', to=b.Everyone())
    t[0] = 10
    assert c.take() == (['scene'], False)
    t[0] = 31
    assert b.reap() == 1 and c.closed


def never_raises():
    def fail():
        raise RuntimeError('expected callback failure')
    c = fresh(wake=fail)
    b.notify('scene', to=b.Everyone())
    assert c.take() == (['scene'], False)
    b.notify(None, to=None)


case('thread', thread)
case('bundle', bundle)
for name in ['fog_move', 'perceivers', 'owner', 'world']:
    case(name, lambda name=name: recipients(name))
for name in ['wilderness', 'overflow', 'rebind_drops_queue', 'rebind_race', 'stale_recheck', 'reconcile_race', 'never_raises']:
    case(name, globals()[name])
case('stale_location', lambda: location_case(True))
case('note_location', location_case)
case('lag_pending', lambda: lag('pending'))
case('lag_inflight', lambda: lag('inflight'))
case('lag_inflight_delivered', lambda: lag('inflight', True))
case('lag_interleaved', lambda: lag('interleaved'))
case('register_resync', lambda: fresh())
case('initial_resync_lag', initial_resync_lag)
case('zero_timestamp', zero_timestamp)
for c in b.connections():
    b.unregister(c)
print('all checks passed')
