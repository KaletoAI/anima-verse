#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/figure_clips.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_figure_clips.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const root = fileURLToPath(new URL('../..', import.meta.url));
// ONE bundle for both modules, so clipCoverage reads the same walk.ts instance
// whose module-state defaults are checked below.
const bundled = await build({
  stdin: { contents: `export * as walk from './client3d/src/game/walk.ts';
    export * as coverage from './client3d/src/scene/clipCoverage.ts';`,
  resolveDir: root, loader: 'ts' },
  bundle: true, write: false, platform: 'node', format: 'esm' });
const { walk, coverage } = await import(
  `data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);

const file = loadVectors('figure_clips');
const { passed, failed } = runVectors(file, {
  resolveMovementPoses: walk.resolveMovementPoses,
  moveClip: walk.moveClip,
  idleClip: walk.idleClip,
  standingClipFor: (animation, groundIdle, poses) =>
    walk.standingClipFor(animation ?? undefined, groundIdle, poses),
  movementOf: walk.movementOf,
  canRun: walk.canRun,
  movementPoseOf: walk.movementPoseOf,
  resolveClipTransitions: walk.resolveClipTransitions,
  clipTransition: walk.clipTransition,
  bridgePace: walk.bridgePace,
  steerCancelsBridge: walk.steerCancelsBridge,
  clipKindChain: coverage.clipKindChain,
  resolveClipKind: coverage.resolveClipKind,
  proceduralGait: coverage.proceduralGait,
});

// The module-state wrappers the figures call must answer exactly what the
// explicit-table rules answer for the table they were handed.
const fx = file.fixtures;
assert.deepEqual(walk.setMovementPoses(fx.RAW_SERVER), fx.POSES_SERVER);
assert.equal(walk.moveClip('walk_run', false), 'mob1-walk');
assert.equal(walk.standingClipFor(undefined, ''), 'mob1-stand-relaxed-idle-v2');
assert.equal(walk.movementPoseOf('walk'), 'walking');
assert.equal(coverage.resolveClipKind('mob1-walk', ['idle', 'walk-cmu']), 'walk-cmu');
assert.equal(coverage.proceduralGait('mob1-walk'), 'walk');
assert.deepEqual(walk.setMovementPoses(null), fx.POSES_DEFAULT);
assert.equal(walk.moveClip('walk_run', false), 'walk');
assert.deepEqual(walk.setClipTransitions(fx.RAW_TABLE), fx.TABLE);
assert.deepEqual(walk.clipTransition('standing', 'sitting'), fx.TABLE[4]);
walk.setClipTransitions(null);
assert.equal(walk.clipTransition('standing', 'sitting'), null);

if (failed) process.exit(1);
console.log(`PASS figure clips: ${passed} vector cases, module-state wrappers agree`);
