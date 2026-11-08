#!/usr/bin/env node
/**
 * Smoke check for the FINALE clip of a running action —
 * `client3d/src/game/finaleClip.ts` (schnittstellen-3d.md § A8c).
 *
 * Usage: timeout 120 node client3d/scripts/smoke_finale_clip.mjs
 *
 * Every number is derived BY HAND here from the rule of § A8c, never recorded
 * from the current output.
 *
 * THE RULE. A client plays a finale once per `id`, from the start, the first
 * time it sees the block; its clock runs on the frame time and stands while
 * frozen; at its length the figure is back in the action's own clip.
 *
 * [1] A NEW id starts at 0 even when the poll says elapsed_s 0.9 of 1.033:
 *     play {id f1, kind standing-dancer-climax, role b, t 0, duration 1.033}.
 * [2] Frames: 0.5 s -> clip `standing-dancer-climax__b` at t 0.5; frozen
 *     0.5 s -> still 0.5; 0.5 s -> 1.0; 0.04 s -> t 1.04 >= 1.033 -> over
 *     (play null, clip null): back in the action's clip.
 * [3] The SAME id in the next poll (the server shows it 4 s past the end)
 *     never restarts it: play stays null, seen stays f1.
 * [4] A second finale (id f2) starts again from 0.
 * [5] Solo (role null): the clip is the plain kind `resting-mast-climax`.
 * [6] The action ended (no interaction, no place): a running finale is
 *     dropped at once; a block arriving with it starts nothing, but its id is
 *     seen. Junk (no id / duration 0) starts nothing.
 * [7] Near the end the handed-out time stays 1 ms short: duration 1.0,
 *     t 0.9995 -> 0.999.
 * [8] A GROUP member (G3, plan-gruppen-animationen.md): role c plays its own
 *     half `standing-dancer-climax__c`, role e `…__e`; a role outside a..e
 *     (`f`) is no role — the plain kind, like a solo block.
 * [9] An ALT half (G6): role c with alt `wave` plays
 *     `standing-dancer-climax__c~wave`, base `standing-dancer-climax__c` (what
 *     a rig without the alt plays); alt "" plays the base, base = clip. A solo
 *     block has no role, so an alt on it is dropped (alt "", clip
 *     `resting-mast-climax`); an alt name outside [a-z0-9-] (`Wave!`) is
 *     dropped too.
 * [10] CYCLES (sidecar `loop_count`, § A8c): duration_s is the WHOLE finale.
 *     Block duration_s 3.099, loop_count 3 -> one cycle 3.099 / 3 = 1.033.
 *     Frames of 0.5 s: t 0.5 -> cycle 0, in-cycle 0.5, loop true;
 *     t 1.5 -> cycle floor(1.5 / 1.033) = 1, in-cycle 1.5 − 1.033 = 0.467,
 *     loop true; t 2.5 -> cycle 2 (the LAST), in-cycle 2.5 − 2.066 = 0.434,
 *     loop false (it holds, it does not wrap); t 3.0 -> in-cycle
 *     3.0 − 2.066 = 0.934; t 3.5 >= 3.099 -> over (play null). Three cycles,
 *     then back — never a fourth.
 *     A block without loop_count, or with 0 / 2.5 / "3", plays ONE cycle:
 *     loopCount 1, in-cycle t = t, loop false (the old one-shot rule [2]).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../src/game/finaleClip.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { adoptFinale, stepFinale } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
const block = (id, extra = {}) => ({ id, kind: 'standing-dancer-climax', role: 'b', elapsed_s: 0.9, duration_s: 1.033, ...extra });

// [1]
let { play, seen } = adoptFinale(null, '', block('f1'), true);
assert.deepEqual(play, { id: 'f1', kind: 'standing-dancer-climax', role: 'b', alt: '', t: 0, duration: 1.033,
  loopCount: 1 });
assert.equal(seen, 'f1');

// [2]
let step = stepFinale(play, 0.5, false);
assert.equal(step.clip, 'standing-dancer-climax__b');
close(step.t, 0.5);
assert.equal(step.loop, false);
step = stepFinale(step.play, 0.5, true);
close(step.t, 0.5);
step = stepFinale(step.play, 0.5, false);
close(step.t, 1.0);
step = stepFinale(step.play, 0.04, false);
assert.deepEqual(step, { play: null, clip: null, base: null, t: 0, loop: false });
play = step.play;

// [3]
({ play, seen } = adoptFinale(play, seen, block('f1', { elapsed_s: 3.2 }), true));
assert.equal(play, null);
assert.equal(seen, 'f1');

// [4]
({ play, seen } = adoptFinale(play, seen, block('f2'), true));
assert.equal(play.t, 0);
assert.equal(seen, 'f2');

// [5]
const solo = adoptFinale(null, '', block('s1', { kind: 'resting-mast-climax', role: null, duration_s: 1.333 }), true);
assert.equal(stepFinale(solo.play, 0.1, false).clip, 'resting-mast-climax');

// [6]
assert.equal(adoptFinale(play, seen, null, false).play, null);
const ended = adoptFinale(null, '', block('f3'), false);
assert.deepEqual(ended, { play: null, seen: 'f3' });
assert.deepEqual(adoptFinale(null, '', block(''), true), { play: null, seen: '' });
assert.deepEqual(adoptFinale(null, '', block('f4', { duration_s: 0 }), true), { play: null, seen: 'f4' });

// [7]
step = stepFinale({ id: 'x', kind: 'k', role: 'a', alt: '', t: 0.9, duration: 1.0, loopCount: 1 }, 0.0995, false);
close(step.t, 0.999);

// [8]
for (const role of ['c', 'e']) {
  const group = adoptFinale(null, '', block(`g${role}`, { role }), true);
  assert.equal(stepFinale(group.play, 0.1, false).clip, `standing-dancer-climax__${role}`);
}
assert.equal(stepFinale(adoptFinale(null, '', block('gf', { role: 'f' }), true).play, 0.1, false).clip,
  'standing-dancer-climax');

// [9]
const alt = stepFinale(adoptFinale(null, '', block('a1', { role: 'c', alt: 'wave' }), true).play, 0.1, false);
assert.equal(alt.clip, 'standing-dancer-climax__c~wave');
assert.equal(alt.base, 'standing-dancer-climax__c');
const plain = stepFinale(adoptFinale(null, '', block('a2', { role: 'c', alt: '' }), true).play, 0.1, false);
assert.equal(plain.clip, 'standing-dancer-climax__c');
assert.equal(plain.base, plain.clip);
const soloAlt = adoptFinale(null, '', block('a3', { kind: 'resting-mast-climax', role: null, alt: 'wave' }), true);
assert.equal(soloAlt.play.alt, '');
assert.equal(stepFinale(soloAlt.play, 0.1, false).clip, 'resting-mast-climax');
assert.equal(adoptFinale(null, '', block('a4', { role: 'c', alt: 'Wave!' }), true).play.alt, '');

// [10]
let cyc = adoptFinale(null, '', block('c1', { duration_s: 3.099, loop_count: 3 }), true).play;
assert.equal(cyc.loopCount, 3);
const expect = [[0.5, 0.5, true], [1.5, 0.467, true], [2.5, 0.434, false], [3.0, 0.934, false]];
let total = 0;
for (const [at, inCycle, loops] of expect) {
  step = stepFinale(cyc, at - total, false);
  total = at;
  cyc = step.play;
  assert.equal(step.clip, 'standing-dancer-climax__b');
  close(step.t, inCycle);
  assert.equal(step.loop, loops, `loop at ${at}`);
}
step = stepFinale(cyc, 0.5, false);
assert.deepEqual(step, { play: null, clip: null, base: null, t: 0, loop: false });
for (const loop_count of [undefined, 0, 2.5, '3']) {
  const one = adoptFinale(null, '', block(`o${loop_count}`, loop_count === undefined ? {} : { loop_count }), true).play;
  assert.equal(one.loopCount, 1, String(loop_count));
  step = stepFinale(one, 0.8, false);
  close(step.t, 0.8);
  assert.equal(step.loop, false);
}

console.log('PASS smoke_finale_clip [1]-[10]');
