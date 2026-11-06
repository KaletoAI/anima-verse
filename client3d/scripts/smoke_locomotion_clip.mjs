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
 * Usage: node client3d/scripts/smoke_locomotion_clip.mjs
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const src = (rel) => fileURLToPath(new URL(`../src/${rel}`, import.meta.url));
const out = await build({
  stdin: {
    contents: `export * from ${JSON.stringify(src('game/walk.ts'))};
export { avatarPaceFactor, npcStep, npcGoal, WALK_SPEED } from ${JSON.stringify(src('game/npcWalk.ts'))};`,
    resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'ts',
  },
  bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent',
});
const mod = await import(`data:text/javascript,${encodeURIComponent(out.outputFiles[0].text)}`);
const { moveClip, overrideMoveClip, avatarPaceFactor, npcStep, npcGoal } = mod;

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

console.log(`smoke_locomotion_clip: ${n} ok`);
