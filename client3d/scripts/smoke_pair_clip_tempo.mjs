#!/usr/bin/env node
/**
 * Smoke check for the scene TEMPO in the two client clocks of a running pose
 * (plan pair scene Task 4, schnittstellen-3d.md § A8a / § A8c):
 * `client3d/src/game/pairClip.ts` (`pairClipPhase`, the pair clip) and
 * `client3d/src/game/finaleClip.ts` (`adoptFinale` / `stepFinale`).
 *
 * Usage: timeout 120 node client3d/scripts/smoke_pair_clip_tempo.mjs [pairClip.ts finaleClip.ts]
 *        (the two optional paths check other copies of the sources, e.g. a
 *        before-state taken with `git show <commit>:client3d/src/game/pairClip.ts`)
 *
 * Every number is derived BY HAND here, never recorded from the output.
 *
 * THE RULE. The server keeps one clip clock per scene and sends `clip_s`
 * (CLIP seconds since the clip began) and `tempo` (clip seconds per real
 * second, 0.2..1). The client advances its own copy by dt · tempo — nothing
 * while frozen — and a new poll snaps it only beyond PAIR_SNAP_S (0.3).
 *
 * [1] tempo 0.5, dt 1 s, local clock 3.0 (cycle 0.533): 3.0 + 1 · 0.5 = 3.5.
 *     tempo 1, dt 1: 4.0.
 * [2] SNAP after the advance (local 3.0, tempo 0.5, dt 1 -> 3.5): a poll with
 *     clip_s 4.0 is 0.5 off (> 0.3) -> 4.0; clip_s 3.7 is 0.2 off -> keep 3.5.
 * [3] FROZEN: tempo 0.5, dt 1, frozen -> 3.0 (no advance); a poll's clip_s 3.5
 *     (0.5 off) still snaps -> 3.5: the server's clock is the truth, the
 *     freeze only stops the local advance.
 * [4] THE TEMPO IS CLAMPED to [0.2, 1], 1 for no number: tempo 5, dt 1 ->
 *     3.0 + 1 = 4.0; tempo 0.05 -> 3.0 + 0.2 = 3.2; tempo missing -> 4.0.
 *     clipTempo: 0.5 -> 0.5, NaN -> 1, "0.5" -> 1, undefined -> 1.
 * [5] ADOPTION takes clip_s as it is — already clip seconds, nothing divides
 *     it: no local clock, clip_s 2.0, tempo 0.5 -> 2.0; phase in a 0.533
 *     cycle: 2.0 − 3 · 0.533 = 0.401.
 * [6] THE FINALE AT TEMPO 0.5. The server's block: clip 1.033 s, loop_count
 *     2, tempo 0.5 -> duration_s = 1.033 · 2 / 0.5 = 4.132 real s. The play
 *     clock counts clip seconds (dt · 0.5); the whole finale is
 *     4.132 · 0.5 = 2.066 clip s, one cycle 2.066 / 2 = 1.033 = the clip.
 *       dt 1 -> t 0.5: cycle 0, in-cycle 0.5, loop true
 *       frozen dt 1 -> t 0.5 (stands)
 *       dt 1 -> t 1.0: cycle 0, in-cycle 1.0, loop true
 *       dt 1 -> t 1.5: cycle 1 (the last), in-cycle 1.5 − 1.033 = 0.467, loop false
 *       dt 1 -> t 2.0: in-cycle 0.967
 *       dt 0.2 -> t 2.1 >= 2.066 -> over (play null)
 *     Real time spent playing: 4 + 0.2 = 4.2 s >= 4.132 — and one cycle lasted
 *     1.033 / 0.5 = 2.066 real s. A block without tempo plays at 1 (t += dt);
 *     tempo 5 is clamped to 1; the adopted play carries tempo 0.5.
 * [7] A SOLO FURNITURE SCENE (fix wave): the row's `place` block carries
 *     `scene_id`, `clip_s`, `tempo` (adoptHeldClock / stepHeldClock).
 *     place {scene_id S, clip_s 2.0, tempo 0.5}, stamp 1, no clock yet
 *       -> adopted as it is: clipT 2.0, tempo 0.5.
 *     frame dt 1 -> 2.0 + 1 · 0.5 = 2.5; frozen dt 1 -> stays 2.5.
 *     same poll again (stamp 1, clip_s 2.0 is 0.5 off) -> NOT reconciled: 2.5.
 *     new poll (stamp 2) clip_s 2.7 (0.2 off) -> kept 2.5; tempo 0.25 -> 0.25.
 *     new poll (stamp 3) clip_s 3.0 (0.5 off) -> snapped to 3.0.
 *     a frame at tempo 0.25, dt 2 -> 3.0 + 2 · 0.25 = 3.5.
 *     another scene T (clip_s 0.4) -> adopted fresh: 0.4.
 *     place without clip_s, or no place -> null (the clip runs on its own).
 *     tempo 5 on a new scene -> 1 (clamped).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
async function load(path, fallback) {
  const source = readFileSync(path ?? new URL(fallback, import.meta.url), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  return import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
}
const { pairClipPhase, clipTempo, adoptHeldClock, stepHeldClock } = await load(process.argv[2], '../src/game/pairClip.ts');
const { adoptFinale, stepFinale } = await load(process.argv[3], '../src/game/finaleClip.ts');

let failed = 0;
let passed = 0;
function check(label, fn) {
  try { fn(); passed++; console.log(`ok    ${label}`); }
  catch (e) { failed++; console.log(`FAIL  ${label}: ${e.message}`); }
}
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
const base = { loop: true, clipDurationS: 0.533, localClipT: 3, frozen: false };
const clipT = (extra) => pairClipPhase({ ...base, clipS: null, tempo: 1, ...extra }).clipT;

check('[1] tempo 0.5, dt 1 advances by 0.5', () => close(clipT({ tempo: 0.5, dt: 1 }), 3.5));
check('[1] tempo 1, dt 1 advances by 1', () => close(clipT({ tempo: 1, dt: 1 }), 4.0));
check('[2] poll 0.5 off snaps', () => close(clipT({ tempo: 0.5, dt: 1, clipS: 4.0 }), 4.0));
check('[2] poll 0.2 off is kept', () => close(clipT({ tempo: 0.5, dt: 1, clipS: 3.7 }), 3.5));
check('[3] frozen does not advance', () => close(clipT({ tempo: 0.5, dt: 1, frozen: true }), 3.0));
check('[3] frozen still snaps to the server', () => close(clipT({ tempo: 0.5, dt: 1, frozen: true, clipS: 3.5 }), 3.5));
check('[4] tempo 5 -> 1', () => close(clipT({ tempo: 5, dt: 1 }), 4.0));
check('[4] tempo 0.05 -> 0.2', () => close(clipT({ tempo: 0.05, dt: 1 }), 3.2));
check('[4] tempo missing -> 1', () => close(clipT({ tempo: undefined, dt: 1 }), 4.0));
check('[4] clipTempo', () => {
  assert.equal(clipTempo(0.5), 0.5);
  assert.equal(clipTempo(Number.NaN), 1);
  assert.equal(clipTempo('0.5'), 1);
  assert.equal(clipTempo(undefined), 1);
});
check('[5] adoption takes clip_s as it is', () => {
  const r = pairClipPhase({ ...base, localClipT: undefined, clipS: 2.0, tempo: 0.5 });
  close(r.clipT, 2.0);
  close(r.phase, 2.0 - 3 * 0.533);
});

const block = { id: 'f1', kind: 'fixture-finale', role: 'b', elapsed_s: 0, duration_s: 4.132, loop_count: 2, tempo: 0.5 };
check('[6] finale at tempo 0.5: clip seconds, cycles of the clip length', () => {
  let { play } = adoptFinale(null, '', block, true);
  assert.equal(play.tempo, 0.5);
  const frames = [[1, false, 0.5, 0.5, true], [1, true, 0.5, 0.5, true], [1, false, 1.0, 1.0, true],
    [1, false, 1.5, 1.5 - 1.033, false], [1, false, 2.0, 2.0 - 1.033, false]];
  for (const [dt, frozen, t, inCycle, loop] of frames) {
    const step = stepFinale(play, dt, frozen);
    play = step.play;
    close(play.t, t);
    close(step.t, inCycle);
    assert.equal(step.loop, loop);
    assert.equal(step.clip, 'fixture-finale__b');
  }
  const end = stepFinale(play, 0.2, false);
  assert.equal(end.play, null);
  assert.equal(end.clip, null);
});
check('[6] no tempo plays at 1, tempo 5 at 1', () => {
  for (const tempo of [undefined, 5]) {
    const { play } = adoptFinale(null, '', { ...block, id: `t${tempo}`, tempo, duration_s: 2.066 }, true);
    assert.equal(play.tempo, 1);
    close(stepFinale(play, 0.5, false).play.t, 0.5);
  }
});

check('[7] solo scene clock on the place block', () => {
  let held = adoptHeldClock(null, { scene_id: 'S', clip_s: 2.0, tempo: 0.5 }, 1);
  assert.deepEqual(held, { sceneId: 'S', clipT: 2.0, tempo: 0.5, stamp: 1 });
  held = stepHeldClock(held, 1, false);
  close(held.clipT, 2.5);
  held = stepHeldClock(held, 1, true);
  close(held.clipT, 2.5);
  held = adoptHeldClock(held, { scene_id: 'S', clip_s: 2.0, tempo: 0.5 }, 1);
  close(held.clipT, 2.5);
  held = adoptHeldClock(held, { scene_id: 'S', clip_s: 2.7, tempo: 0.25 }, 2);
  close(held.clipT, 2.5);
  assert.equal(held.tempo, 0.25);
  held = adoptHeldClock(held, { scene_id: 'S', clip_s: 3.0, tempo: 0.25 }, 3);
  close(held.clipT, 3.0);
  held = stepHeldClock(held, 2, false);
  close(held.clipT, 3.5);
  held = adoptHeldClock(held, { scene_id: 'T', clip_s: 0.4, tempo: 0.25 }, 4);
  assert.deepEqual(held, { sceneId: 'T', clipT: 0.4, tempo: 0.25, stamp: 4 });
  assert.equal(adoptHeldClock(held, { id: 'p' }, 5), null);
  assert.equal(adoptHeldClock(held, null, 5), null);
  assert.equal(adoptHeldClock(null, { scene_id: 'U', clip_s: 1, tempo: 5 }, 6).tempo, 1);
});

console.log(`\n${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
