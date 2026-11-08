#!/usr/bin/env node
/**
 * Smoke check for the REPEAT COUNT of a looped clip — the sidecar / listing
 * field `loop_count` (§ A8): `client3d/src/game/clipLoop.ts` (the mixer mode
 * of a solo clip, `Figure.play`), the counted case of
 * `client3d/src/game/pairClip.ts` (a pair half, `playPair`), and a REAL
 * Three.js `AnimationMixer` driven with those answers.
 *
 * Usage: timeout 120 node client3d/scripts/smoke_clip_loop_count.mjs
 *
 * Every number is derived BY HAND here, never recorded from the output.
 *
 * THE RULE. `loop` false = once, hold the last frame. `loop` true without a
 * count = endless. `loop` true with `loop_count` N (a whole number 1..99) =
 * N cycles, then hold the last frame. A count without `loop` changes nothing.
 *
 * [1] clipLoopMode:
 *     (false, —)   -> {repeat false, repetitions 1, clamp true}
 *     (false, 3)   -> the same (a count belongs to a loop)
 *     (true, —)    -> {repeat true, repetitions Infinity, clamp false}
 *     (true, 3)    -> {repeat true, repetitions 3, clamp true}
 *     (true, 0 / 100 / 2.5 / "3" / null) -> endless, like no count.
 * [2] A REAL MIXER, solo clip of 1.0 s (a position track x 0 -> 1), counted
 *     loop 3, stepped in 0.25 s frames (exact in binary, so the mixer's own
 *     sum lands ON 3.0): "finished" fires once, at mixer time 3.0 (frame 12:
 *     12 x 0.25) and not at 2.75; afterwards the action stays paused at its end
 *     (time 1.0, x 1.0) — at 4.0 s still x 1.0, not the 0.0 a fourth cycle
 *     would start with. The endless loop at 4.0 s: never finished, time
 *     4.0 mod 1.0 = 0 -> x 0.0 (a new cycle); at 4.5 s x 0.5.
 * [3] The spell clip `spell_casting` (duration_s 5.0, loop_count 3, the
 *     migration of 2026-11-09): mixer finished at 5.0 x 3 = 15.0 s, not before
 *     (at 14.75 s still running, in-cycle 14.75 − 10.0 = 4.75 -> x 0.95).
 * [4] pairClipPhase, counted (cycle 2.0 s, loop_count 3, rate 1):
 *     clipT 1.0 -> phase 1.0, cycling true; clipT 3.0 -> phase 1.0, cycling
 *     true; clipT 4.0 -> 4.0 >= (3 − 1) x 2.0 -> the last cycle: phase 0.0,
 *     cycling false; clipT 5.5 -> phase 1.5, cycling false; clipT 6.0 ->
 *     6.0 >= 3 x 2.0 -> phase 2.0 (held), cycling false; clipT 50 -> 2.0.
 *     loop_count 1 -> cycling false from the start (a loop of one = once):
 *     clipT 1.5 -> 1.5, clipT 3.0 -> 2.0. Endless (null) at clipT 7.0 ->
 *     7.0 mod 2.0 = 1.0, cycling true. A one-shot with loop_count 3 ignores
 *     it: clipT 3.0 -> 2.0, cycling false.
 * [5] THE MODE SWITCH `playPair` makes when a counted pair half enters its
 *     last cycle: the SAME action, LoopRepeat (Infinity) for 2 cycles of
 *     1.0 s, then setLoop(LoopOnce) + clampWhenFinished at mixer time 2.0
 *     (the action wrapped to in-cycle 0.0): it plays the third cycle and holds
 *     — not finished at 2.75, finished at 3.0, x 1.0 at 3.5 (never wrapped
 *     back to 0.0).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const load = async (rel) => {
  const source = readFileSync(new URL(rel, import.meta.url), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  return import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
};
const { clipLoopMode } = await load('../src/game/clipLoop.ts');
const { pairClipPhase } = await load('../src/game/pairClip.ts');
const THREE = await import('three');

const close = (a, b, what) => assert.ok(Math.abs(a - b) < 1e-6, `${what}: ${a} != ${b}`);

// [1]
const ONCE = { repeat: false, repetitions: 1, clamp: true };
const ENDLESS = { repeat: true, repetitions: Infinity, clamp: false };
assert.deepEqual(clipLoopMode(false, undefined), ONCE);
assert.deepEqual(clipLoopMode(false, 3), ONCE);
assert.deepEqual(clipLoopMode(true, undefined), ENDLESS);
assert.deepEqual(clipLoopMode(true, 3), { repeat: true, repetitions: 3, clamp: true });
for (const junk of [0, 100, 2.5, '3', null]) assert.deepEqual(clipLoopMode(true, junk), ENDLESS, String(junk));

/** A mixer playing a `duration` s clip whose x runs 0 -> 1, in `mode`. */
function rig(duration, mode) {
  const obj = new THREE.Object3D();
  obj.name = 'o';
  const clip = new THREE.AnimationClip('c', duration, [
    new THREE.NumberKeyframeTrack('o.position[x]', [0, duration], [0, 1])]);
  const mixer = new THREE.AnimationMixer(obj);
  const action = mixer.clipAction(clip);
  action.setLoop(mode.repeat ? THREE.LoopRepeat : THREE.LoopOnce, mode.repetitions);
  action.clampWhenFinished = mode.clamp;
  action.play();
  const finished = [];
  let now = 0;
  mixer.addEventListener('finished', () => finished.push(now));
  const run = (until, dt = 0.25) => {
    while (now < until - 1e-9) { now = Math.round((now + dt) * 1e6) / 1e6; mixer.update(dt); }
  };
  return { obj, action, finished, run, now: () => now };
}

// [2]
let r = rig(1.0, clipLoopMode(true, 3));
r.run(2.75);
assert.deepEqual(r.finished, []);
r.run(3.0);
assert.deepEqual(r.finished, [3.0]);
close(r.action.time, 1.0, 'held time');
close(r.obj.position.x, 1.0, 'held x at 3.0');
r.run(4.0);
assert.deepEqual(r.finished, [3.0]);
close(r.obj.position.x, 1.0, 'held x at 4.0');
r = rig(1.0, clipLoopMode(true, null));
r.run(4.0);
assert.deepEqual(r.finished, []);
close(r.obj.position.x, 0.0, 'endless x at 4.0');
r.run(4.5);
close(r.obj.position.x, 0.5, 'endless x at 4.5');

// [3]
r = rig(5.0, clipLoopMode(true, 3));
r.run(14.75);
assert.deepEqual(r.finished, []);
close(r.obj.position.x, 0.95, 'spell x at 14.75');
r.run(15.0);
assert.deepEqual(r.finished, [15.0]);
r.run(20.0);
close(r.obj.position.x, 1.0, 'spell held');

// [4]
const pair = (clipT, loop, loopCount) => {
  const { phase, cycling } = pairClipPhase({ elapsedGameS: clipT, rate: 1, loop, loopCount, clipDurationS: 2.0 });
  return [Math.round(phase * 1e6) / 1e6, cycling];
};
assert.deepEqual(pair(1.0, true, 3), [1.0, true]);
assert.deepEqual(pair(3.0, true, 3), [1.0, true]);
assert.deepEqual(pair(4.0, true, 3), [0.0, false]);
assert.deepEqual(pair(5.5, true, 3), [1.5, false]);
assert.deepEqual(pair(6.0, true, 3), [2.0, false]);
assert.deepEqual(pair(50, true, 3), [2.0, false]);
assert.deepEqual(pair(1.5, true, 1), [1.5, false]);
assert.deepEqual(pair(3.0, true, 1), [2.0, false]);
assert.deepEqual(pair(7.0, true, null), [1.0, true]);
assert.deepEqual(pair(3.0, false, 3), [2.0, false]);

// [5]
r = rig(1.0, clipLoopMode(true, null));
r.run(2.0);
close(r.action.time, 0.0, 'wrapped at 2.0');
r.action.setLoop(THREE.LoopOnce, 1);
r.action.clampWhenFinished = true;
r.run(2.75);
assert.deepEqual(r.finished, []);
r.run(3.0);
assert.deepEqual(r.finished, [3.0]);
r.run(3.5);
close(r.obj.position.x, 1.0, 'last cycle held');

console.log('PASS smoke_clip_loop_count [1]-[5]');
