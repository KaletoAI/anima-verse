/** Shared unread rules, bundled exactly as the browser consumes them. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const result = await build({ entryPoints: ['packages/player-ui/src/openTopics.ts'], bundle: true, write: false, format: 'esm', platform: 'browser' });
const { unreadCounts } = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'));
const posts = [{ id: 'c' }, { id: 'b' }, { id: 'a' }];
assert.deepEqual(unreadCounts({ conversations: [{ unread: 2 }, { unread: 0 }, {}] }, { posts }, 'b'), { phone: 2, instagram: 1 });
assert.deepEqual(unreadCounts(null, { posts }, 'x'), { phone: 0, instagram: 3 });
assert.deepEqual(unreadCounts(null, null, null), { phone: 0, instagram: 0 });
assert.equal(unreadCounts(null, { posts: Array.from({ length: 120 }, (_, i) => ({ id: String(i) })) }, 'zz').instagram, 99);
assert.deepEqual(unreadCounts({}, { posts }, null), { phone: 0, instagram: 0 });
assert.equal(unreadCounts(null, { posts }, 'c').instagram, 0);
console.log('PASS smoke_open_topics');
