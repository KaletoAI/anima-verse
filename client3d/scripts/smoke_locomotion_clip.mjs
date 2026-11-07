#!/usr/bin/env node
/**
 * The move-clip decisions of a figure on top of the server's words — PURE,
 * expected values derived BY HAND (default pose table: walking → 'walk',
 * running → 'run', swimming → 'breast-stroke', crawling → 'crawl').
 *
 * [1] moveClip + gait: a journey's `gait` 'run' asks moveClip(..., true).
 *     walk_run ground → 'run'; 'walk' gait → 'walk'. The GROUND decides first:
 *     swim → 'breast-stroke' and crawl → 'crawl' whatever the gait; a 'walk'
 *     ground (no running allowed) → 'walk' even for gait 'run'.
 *
 * [2] overrideMoveClip(clip, locomotion, has): only the WALK and RUN pose's
 *     clips are replaced, and only when the figure has the kind.
 *     {walk: 'hover'} with has(hover): 'walk' → 'hover'; 'run' → 'run' (no
 *     run slot). {walk: 'hover', run: 'float'}: 'run' → 'float'.
 *     has() false for 'hover' → 'walk' stays (the set lacks the clip).
 *     'breast-stroke' and 'crawl' pass through untouched (the ground's word).
 *     null / undefined locomotion → the clip unchanged.
 *
 * [3] avatarPaceFactor(raw): a positive finite number passes (2.5 → 2.5,
 *     0.5 → 0.5); null, undefined, 0, -1, NaN, Infinity and '2' → 1.
 *     The avatar's step then is 3.4 × dt × terrain × factor: at dt = 0.1 on
 *     plain ground and factor 2.5 that is 3.4 × 0.1 × 2.5 = 0.85 m.
 *
 * [4] Shift runs the avatar. sprintHeld(keys, dir): true only when 'shift' is
 *     held AND the keys gave a direction — {shift, w} with dir (0,-1) → true;
 *     {w} → false; {shift} with dir null (Shift alone, or a click order) →
 *     false. npcStep(..., sprint): the avatar's goal is only a lead ahead, so a
 *     goal 1 m away (dist 1 < RUN_DISTANCE 6) walks without the key and runs
 *     with it. At dt = 0.1, pace 1: walk 3.4 × 0.1 = 0.34 m, run
 *     3.4 × 0.1 × 1.8 = 0.612 m (below the 1 m goal, so the cap does not bite).
 *     With the 2.5× avatar factor: 3.4 × 0.1 × 2.5 × 1.8 = 1.53 m, capped at
 *     the 1 m goal → 1. The ground still decides: on 'swim' and 'walk' ground
 *     the key changes nothing (running false, step 0.34). Reckoning (a fogged
 *     traveller) never runs, key or not: 0.34. And `sprint` defaults to false,
 *     so every other caller keeps the old step: 0.34.
 *
 * Usage: node client3d/scripts/smoke_locomotion_clip.mjs
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const src = (rel) => fileURLToPath(new URL(`../src/${rel}`, import.meta.url));
const out = await build({
  stdin: {
    contents: `export * from ${JSON.stringify(src('game/walk.ts'))};
export { avatarPaceFactor, npcStep, npcGoal, WALK_SPEED, RUN_FACTOR } from ${JSON.stringify(src('game/npcWalk.ts'))};`,
    resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'ts',
  },
  bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent',
});
const mod = await import(`data:text/javascript,${encodeURIComponent(out.outputFiles[0].text)}`);
const { moveClip, overrideMoveClip, avatarPaceFactor, npcStep, npcGoal, sprintHeld, RUN_FACTOR } = mod;

let n = 0;
const eq = (label, actual, expected) => { assert.deepEqual(actual, expected, label); n++; };

// [1]
eq('[1] run gait on walk_run ground', moveClip('walk_run', true), 'run');
eq('[1] walk gait', moveClip('walk_run', false), 'walk');
eq('[1] swim ground wins over run', moveClip('swim', true), 'breast-stroke');
eq('[1] crawl ground wins over run', moveClip('crawl', true), 'crawl');
eq('[1] walk-only ground never runs', moveClip('walk', true), 'walk');

// [2]
const hasAll = () => true;
eq('[2] walk → hover', overrideMoveClip('walk', { walk: 'hover' }, hasAll), 'hover');
eq('[2] run without a run slot', overrideMoveClip('run', { walk: 'hover' }, hasAll), 'run');
eq('[2] run → float', overrideMoveClip('run', { walk: 'hover', run: 'float' }, hasAll), 'float');
eq('[2] the set lacks the kind', overrideMoveClip('walk', { walk: 'hover' }, (k) => k !== 'hover'), 'walk');
eq('[2] swimming is the ground\'s', overrideMoveClip('breast-stroke', { walk: 'hover', run: 'float' }, hasAll), 'breast-stroke');
eq('[2] crawling is the ground\'s', overrideMoveClip('crawl', { walk: 'hover', run: 'float' }, hasAll), 'crawl');
eq('[2] null override', overrideMoveClip('walk', null, hasAll), 'walk');
eq('[2] undefined override', overrideMoveClip('run', undefined, hasAll), 'run');

// [3]
eq('[3] 2.5 passes', avatarPaceFactor(2.5), 2.5);
eq('[3] 0.5 passes', avatarPaceFactor(0.5), 0.5);
for (const raw of [null, undefined, 0, -1, NaN, Infinity, '2']) {
  eq(`[3] ${String(raw)} → 1`, avatarPaceFactor(raw), 1);
}
const plan = npcGoal({ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }, []);
const { step } = npcStep(plan, 'walk_run', false, 0.1, 1 * avatarPaceFactor(2.5), 1);
eq('[3] the avatar step at 2.5×', Math.round(step * 1e6) / 1e6, 0.85);

// [4]
const r6 = (v) => Math.round(v * 1e6) / 1e6;
eq('[4] RUN_FACTOR', RUN_FACTOR, 1.8);
eq('[4] shift + direction', sprintHeld(new Set(['shift', 'w']), { x: 0, z: -1 }), true);
eq('[4] direction without shift', sprintHeld(new Set(['w']), { x: 0, z: -1 }), false);
eq('[4] shift alone', sprintHeld(new Set(['shift']), null), false);
const near = npcGoal({ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }, []);
const at = (movement, reckoning, pace, sprint) => {
  const r = npcStep(near, movement, reckoning, 0.1, pace, 1, null, sprint);
  return [r.running, r6(r.step)];
};
eq('[4] no key walks', at('walk_run', false, 1, false), [false, 0.34]);
eq('[4] key runs inside RUN_DISTANCE', at('walk_run', false, 1, true), [true, 0.612]);
eq('[4] key × 2.5 capped at the goal', at('walk_run', false, 2.5, true), [true, 1]);
eq('[4] swim ground ignores the key', at('swim', false, 1, true), [false, 0.34]);
eq('[4] walk-only ground ignores the key', at('walk', false, 1, true), [false, 0.34]);
eq('[4] reckoning ignores the key', at('walk_run', true, 1, true), [false, 0.34]);
{
  const r = npcStep(near, 'walk_run', false, 0.1, 1, 1);
  eq('[4] default sprint is off', [r.running, r6(r.step)], [false, 0.34]);
}

console.log(`smoke_locomotion_clip: ${n} ok`);
