/** Hand calculation: two slots start C (1), B (5), before A (10), D (20).
 * Avatar V (99) wins the next slot without preemption. B's rejection frees
 * a slot for A, then V's completion starts D. With one slot, changing A's
 * distance from 10 to 1 makes it beat B (5). Equal distances retain FIFO.
 * NaN distances [NaN, 1, 0] start C, B, A (NaN means Infinity).
 * Mixed [Infinity, 2, Infinity, 1] starts D, B, A, C; the two infinities tie.
 * All-Infinity and uncancelled equal finite distances start A, B, C (FIFO).
 * [NaN, Infinity, NaN] also starts A, B, C after normalisation.
 * Cancelling waiting A yields cancelled; running X cannot be cancelled.
 * Successful, rejected and synchronously throwing runs all yield done.
 */
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { transformSync } from 'esbuild';
const dir = await mkdtemp(join(tmpdir(), 'focus-queue-'));
try {
  const source = await readFile(new URL('../src/game/focusQueue.ts', import.meta.url), 'utf8');
  const file = join(dir, 'focusQueue.mjs');
  await writeFile(file, transformSync(source, { loader: 'ts', format: 'esm' }).code);
  const { createFocusQueue } = await import(`file://${file}`);
  const tick = () => new Promise(r => setTimeout(r, 0));
  const fixture = max => {
    const q = createFocusQueue({ max }), started = [], done = {};
    const job = (id, d, priority) => ({ key: id, priority,
      distance: typeof d === 'function' ? d : () => d,
      run: () => new Promise((res, rej) => { started.push(id); done[id] = { res, rej }; }) });
    return { q, started, done, job };
  };
  {
    const { q, started, done, job } = fixture(2);
    const ps = ['A','B','C','D'].map((id,i) => q.push(job(id,[10,5,1,20][i])));
    assert.equal(q.size(), 4);
    await tick(); assert.deepEqual(started, ['C','B']); assert.equal(q.active(), 2);
    ps.push(q.push(job('V',99,'avatar')));
    done.C.res(); await tick(); assert.deepEqual(started, ['C','B','V']);
    done.B.rej(new Error('x')); await tick(); assert.deepEqual(started, ['C','B','V','A']);
    done.V.res(); await tick(); assert.deepEqual(started, ['C','B','V','A','D']);
    done.A.res(); done.D.res(); assert.deepEqual(await Promise.all(ps), Array(5).fill('done'));
    assert.equal(q.active(),0); assert.equal(q.size(),0);
  }
  {
    const { q, started, done, job } = fixture(1); let d = 10;
    const ps = [q.push(job('X',0)), q.push(job('A',() => d)), q.push(job('B',5))];
    await tick(); d = 1; done.X.res(); await tick(); assert.deepEqual(started,['X','A']);
    done.A.res(); await tick(); done.B.res(); await Promise.all(ps);
  }
  {
    const { q, started, done, job } = fixture(1);
    const x = q.push(job('X',0)), a = q.push(job('A',0)), b = q.push(job('B',0));
    await tick(); assert.deepEqual(started,['X']);
    assert.equal(q.cancel('X'),false); assert.equal(q.cancel('A'),true);
    assert.equal(await a,'cancelled'); assert.equal(q.cancel('missing'),false);
    done.X.res(); await tick(); assert.deepEqual(started,['X','B']); done.B.res(); await Promise.all([x,b]);
    assert.equal(await q.push({ distance: () => 0, run: () => { throw new Error('sync'); } }), 'done');
  }
  for (const [distances, expected] of [
    [[NaN, 1, 0], ['C', 'B', 'A']],
    [[Infinity, 2, Infinity, 1], ['D', 'B', 'A', 'C']],
    [[Infinity, Infinity, Infinity], ['A', 'B', 'C']],
    [[7, 7, 7], ['A', 'B', 'C']],
    [[NaN, Infinity, NaN], ['A', 'B', 'C']],
  ]) {
    const { q, started, done, job } = fixture(1);
    const ps = distances.map((d, i) => q.push(job(['A', 'B', 'C', 'D'][i], d)));
    for (let i = 0; i < expected.length; i++) {
      await tick();
      assert.deepEqual(started, expected.slice(0, i + 1));
      done[expected[i]].res();
    }
    assert.deepEqual(await Promise.all(ps), Array(expected.length).fill('done'));
  }
  console.log('smoke_focus_queue: OK');
} finally { await rm(dir,{ recursive:true, force:true }); }
