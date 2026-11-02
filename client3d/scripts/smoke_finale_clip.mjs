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
assert.deepEqual(play, { id: 'f1', kind: 'standing-dancer-climax', role: 'b', t: 0, duration: 1.033 });
assert.equal(seen, 'f1');

// [2]
let step = stepFinale(play, 0.5, false);
assert.equal(step.clip, 'standing-dancer-climax__b');
close(step.t, 0.5);
step = stepFinale(step.play, 0.5, true);
close(step.t, 0.5);
step = stepFinale(step.play, 0.5, false);
close(step.t, 1.0);
step = stepFinale(step.play, 0.04, false);
assert.deepEqual(step, { play: null, clip: null, t: 0 });
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
step = stepFinale({ id: 'x', kind: 'k', role: 'a', t: 0.9, duration: 1.0 }, 0.0995, false);
close(step.t, 0.999);

console.log('PASS smoke_finale_clip [1]-[7]');
