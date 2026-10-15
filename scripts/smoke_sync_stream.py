#!/usr/bin/env python3
"""Real-stack ASGI smoke with hand-derived expectations.

All cases NEU on a241a8aa: no sync_stream/peek_session (ImportError), and
GET /events/sync has no handler (404). Both ASGI 2.4 and 2.0 run every case.
anon =>401. connect =>200, SSE/no-cache/no-buffer/no-gzip, first open body
has retry 5000 and exactly five resync topics. heartbeat =>ping before 1s.
batch REGRESSION: hold the batch wait until p,s,p are queued =>one p,s frame.
two_users NEU: shared fallback must never grant private avatar/location topics.
switch_during_connect NEU: a switch during initial binding must not be missed.
reap_during_init/disconnect_during_init NEU: stalled initial reconciliation
previously had no cancellation task or disconnect watcher; finish before the
barrier is released, without sending headers.
peek: read leaves expiry/activity unchanged. logout =>bye within 2s;
expiry: now+1s =>bye within 2s after expiry. rebind/recheck_avatar: Ava/X
switches to Bea/Y =>resync; Y hits and X does not. disconnect: no heartbeat
or signal is needed to finish within 1s. blocked_send/ping/header/bye:
clock +31 exceeds 30 =>reap closes one connection and cancels blocked send.
timing_log => /events/sync streams>=1, no <unmatched>. At most one receive
waiter in every case, independently of ASGI version. All DBs are temporary.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix='sync-stream-smoke-')
ROOT = Path(TMP.name)
os.environ['STORAGE_DIR'] = str(ROOT / 'world')
os.environ['INSTANCE_DIR'] = str(ROOT / 'instance')
from app.core import paths
paths.init(ROOT / 'world')
paths.init_instance(ROOT / 'instance')
from app import server
from app.core import db, sessions, sync_topics as b, users, request_timing
from app.core import sync_stream
from app.core.timeutils import utc_now
from app.models import account
from app.models.character import save_character_profile

ALL = ['presence', 'scene', 'notices', 'self', 'world']
uid = users.create_user('demo', 'demo-password', allowed_characters=['Ava', 'Bea'])
# Empty synthetic login: no personal username is needed for this fixture.
uid_b = users.create_user('', 'demo-password', allowed_characters=[])
account.save_user_profile({'active_character': 'Ava'})
for name, loc in [('Ava', 'X'), ('Bea', 'Y')]:
    save_character_profile(name, {'current_location': loc}, create_new=True)


class Call:
    max_readers = 0

    def __init__(self, version, token='', block=None):
        self.messages = []
        self.disconnect = asyncio.Event()
        self.blocked = asyncio.Event()
        self.never = asyncio.Event()
        self.readers = 0
        self.first_request = True
        self.bodies = 0
        self.block = block
        self.scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': version},
                      'method': 'GET', 'path': '/events/sync', 'raw_path': b'/events/sync',
                      'query_string': b'', 'headers': [(b'accept-encoding', b'gzip')],
                      'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1), 'root_path': ''}
        if token:
            self.scope['headers'].append((b'cookie', f'av_session={token}'.encode()))
        self.task = asyncio.create_task(server.app(self.scope, self.receive, self.send))

    async def receive(self):
        self.readers += 1
        Call.max_readers = max(Call.max_readers, self.readers)
        try:
            if self.first_request:
                self.first_request = False
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            await self.disconnect.wait()
            return {'type': 'http.disconnect'}
        finally:
            self.readers -= 1

    async def send(self, message):
        if message['type'] == 'http.response.body':
            self.bodies += 1
        body = message.get('body', b'')
        if ((self.block == 'header' and message['type'] == 'http.response.start')
                or (self.block == 'second' and self.bodies == 2)
                or (self.block == 'ping' and body.startswith(b'event: ping'))
                or (self.block == 'bye' and body.startswith(b'event: bye'))):
            self.blocked.set()
            await self.never.wait()
        self.messages.append((time.monotonic(), dict(message)))

    def bodies_list(self):
        return [m for _, m in self.messages if m['type'] == 'http.response.body']

    def data(self):
        return [json.loads(m['body'].split(b'data: ', 1)[1]) for m in self.bodies_list()
                if b'data: ' in m.get('body', b'') and b'event: ' not in m['body']]

    async def until(self, predicate, seconds=1):
        async def wait():
            while not predicate():
                if self.task.done():
                    await self.task
                    raise AssertionError('app ended before expectation')
                await asyncio.sleep(.005)
        await asyncio.wait_for(wait(), seconds)

    async def connected(self):
        await self.until(lambda: bool(self.data()))
        assert self.data()[0] == {'topics': ALL, 'resync': True}

    async def finished(self):
        await asyncio.wait_for(asyncio.shield(self.task), 1)
        assert not b.connections()

    async def close(self):
        self.disconnect.set()
        try:
            await self.finished()
        finally:
            if not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)


def row(token):
    return dict(db.get_connection().execute('SELECT * FROM user_sessions WHERE token=?', (token,)).fetchone())


def switch():
    users.update_user(uid, settings={'active_character': 'Bea'})


async def run_case(version, name):
    assert not b.connections()
    users.update_user(uid, settings={'active_character': 'Ava'},
                      allowed_characters=['Ava'] if name == 'two_users' else ['Ava', 'Bea'])
    token = sessions.create_session(uid)
    b.HEARTBEAT_S, b.CHECK_S, b.BATCH_S = .3, .5, .05
    b._clock = time.monotonic
    if name == 'disconnect':
        b.HEARTBEAT_S = 30
    block = {'blocked_send': 'second', 'blocked_ping': 'ping',
             'blocked_header': 'header', 'blocked_bye': 'bye'}.get(name)
    original_read = account.get_active_character_for_user
    read_entered, read_release = threading.Event(), threading.Event()
    if name == 'switch_during_connect':
        def held_read(user_id):
            active = original_read(user_id)
            if not read_entered.is_set():
                read_entered.set()
                assert read_release.wait(2), 'initial read barrier timed out'
            return active
        account.get_active_character_for_user = held_read
    batch_entered, batch_release = asyncio.Event(), asyncio.Event()
    original_sleep = getattr(sync_stream, '_batch_sleep', asyncio.sleep)
    async def held_batch_sleep(delay):
        batch_entered.set()
        await batch_release.wait()
    if name == 'batch':
        sync_stream._batch_sleep = held_batch_sleep
    original_reconcile = b.reconcile
    init_entered, init_ended = asyncio.Event(), asyncio.Event()
    init_release = threading.Event()
    loop = asyncio.get_running_loop()
    if name in ('reap_during_init', 'disconnect_during_init'):
        now = [time.monotonic()]
        b._clock = lambda: now[0]
        def held_reconcile(conn):
            loop.call_soon_threadsafe(init_entered.set)
            try:
                assert init_release.wait(5), 'initial reconcile barrier timed out'
                return original_reconcile(conn)
            finally:
                loop.call_soon_threadsafe(init_ended.set)
        b.reconcile = held_reconcile
    c = Call(version, '' if name == 'anon' else token, block)
    try:
        if name in ('reap_during_init', 'disconnect_during_init'):
            await asyncio.wait_for(init_entered.wait(), 1)
            assert not c.messages, 'no response before initial reconciliation'
            if name == 'reap_during_init':
                now[0] += b.SLOW_S + 1
                assert b.reap() == 1
            else:
                c.disconnect.set()
            await c.finished()
            assert not any(m['type'] == 'http.response.start' for _, m in c.messages)
            return
        if name == 'switch_during_connect':
            await c.until(read_entered.is_set, 2)
            try:
                conn, = b.connections()
                assert conn.binding()[:2] == ('', ''), conn.binding()
                assert not c.messages, 'no frame before initial reconciliation'
                switch()
                b.rebind_user(uid)
            finally:
                read_release.set()
        if name == 'anon':
            await c.finished()
            assert c.messages[0][1]['status'] == 401
            assert json.loads(c.bodies_list()[0]['body']) == {'detail': 'Not authenticated'}
            return
        if name == 'blocked_header':
            await asyncio.wait_for(c.blocked.wait(), 1)
        else:
            await c.connected()
        if name == 'connect':
            start = c.messages[0][1]
            headers = dict(start['headers'])
            assert start['status'] == 200
            assert headers[b'content-type'].startswith(b'text/event-stream')
            assert headers[b'cache-control'] == b'no-cache'
            assert headers[b'x-accel-buffering'] == b'no'
            assert b'content-encoding' not in headers
            assert b'retry: 5000\n' in c.bodies_list()[0]['body']
            assert c.bodies_list()[0]['more_body'] is True and not c.task.done()
        elif name == 'heartbeat':
            await c.until(lambda: any(m['body'] == b'event: ping\ndata: {}\n\n' for m in c.bodies_list()))
        elif name == 'batch':
            b.notify('presence', to=b.Avatar('Ava'))
            await asyncio.wait_for(batch_entered.wait(), 1)
            b.notify('scene', to=b.Avatar('Ava'))
            b.notify('presence', to=b.Avatar('Ava'))
            batch_release.set()
            await c.until(lambda: len(c.data()) >= 2)
            await c.close()
            assert c.data()[1:] == [{'topics': ['presence', 'scene'], 'resync': False}]
        elif name == 'two_users':
            other_token = sessions.create_session(uid_b)
            other = Call(version, other_token)
            try:
                await other.connected()
                bindings = {conn.user_id: conn.binding()[:2] for conn in b.connections()}
                assert bindings == {uid: ('Ava', 'X'), uid_b: ('', '')}, bindings
                b.notify('scene', to=b.Avatar('Ava'))
                b.notify('presence', to=b.AtLocation('X'))
                await c.until(lambda: len(c.data()) >= 2)
                assert c.data()[1:] == [{'topics': ['presence', 'scene'], 'resync': False}]
                assert other.data() == [{'topics': ALL, 'resync': True}]
                assert not next(conn for conn in b.connections() if conn.user_id == uid_b).has_pending()
            finally:
                other.disconnect.set()
                await asyncio.wait_for(other.task, 1)
                sessions.delete_session(other_token)
                users.update_user(uid, allowed_characters=['Ava', 'Bea'])
        elif name == 'switch_during_connect':
            conn, = b.connections()
            assert conn.binding()[:2] == ('Bea', 'Y'), conn.binding()
            b.notify('scene', to=b.AtLocation('X'))
            assert not conn.has_pending()
            await c.close()
            assert c.data() == [{'topics': ALL, 'resync': True}]
        elif name == 'peek':
            before = row(token)
            assert sessions.peek_session(token)['user_id'] == uid
            assert row(token) == before
        elif name in ('logout', 'expiry'):
            if name == 'logout':
                sessions.delete_session(token)
            else:
                with db.transaction() as con:
                    con.execute('UPDATE user_sessions SET expires_at=? WHERE token=?',
                                ((utc_now() + timedelta(seconds=1)).isoformat(), token))
            await c.until(lambda: any(m['body'].startswith(b'event: bye\ndata: {}') for m in c.bodies_list()), 3 if name == 'expiry' else 2)
            assert c.bodies_list()[-1]['more_body'] is False
            await c.finished()
        elif name in ('rebind', 'recheck_avatar'):
            switch()
            if name == 'rebind':
                await asyncio.to_thread(b.rebind_user, uid)
            await c.until(lambda: len(c.data()) == 2, 2)
            assert c.data()[1] == {'topics': ALL, 'resync': True}
            b.notify('scene', to=b.AtLocation('X'))
            await asyncio.sleep(.12)
            assert len(c.data()) == 2
            b.notify('presence', to=b.AtLocation('Y'))
            await c.until(lambda: len(c.data()) == 3)
            assert c.data()[2] == {'topics': ['presence'], 'resync': False}
        elif name == 'disconnect':
            c.disconnect.set()
            await c.finished()
        elif name.startswith('blocked_'):
            if name == 'blocked_send':
                b.notify('presence', to=b.Avatar('Ava'))
            elif name == 'blocked_bye':
                sessions.delete_session(token)
            await asyncio.wait_for(c.blocked.wait(), 2)
            now = time.monotonic()
            b._clock = lambda: now + 31
            assert b.reap() == 1
            await c.finished()
        elif name == 'timing_log':
            await c.close()
            stats = request_timing.route_stats()
            assert any(r['route'] == '/events/sync' and r['streams'] >= 1 for r in stats)
            assert not any(r['route'] == '<unmatched>' for r in stats)
    finally:
        init_release.set()
        if init_entered.is_set():
            await asyncio.wait_for(init_ended.wait(), 1)
        b.reconcile = original_reconcile
        read_release.set()
        account.get_active_character_for_user = original_read
        sync_stream._batch_sleep = original_sleep
        await c.close()
        b._clock = time.monotonic
        sessions.delete_session(token)


async def main():
    for version in ('2.4', '2.0'):
        for name in ('reap_during_init', 'disconnect_during_init', 'two_users', 'switch_during_connect', 'anon', 'connect', 'heartbeat', 'batch', 'peek', 'logout', 'expiry',
                     'rebind', 'recheck_avatar', 'disconnect', 'blocked_send', 'blocked_ping',
                     'blocked_header', 'blocked_bye', 'timing_log'):
            await run_case(version, name)
            print('PASS', version, name)
    assert Call.max_readers == 1, Call.max_readers
    print('PASS maximum concurrent receive readers = 1')
    print('all checks passed')


if __name__ == '__main__':
    asyncio.run(main())
