#!/usr/bin/env node
/**
 * Usage: node client3d/scripts/smoke_first_person.mjs
 *
 * First-person zoom: enter at <= 1.2 m, leave at >= 1.8 m, only after
 * 180 ms continuously beyond the respective threshold. The band preserves
 * the current perspective. Leaving avatar control resets both the mode and
 * the pending delay. These hand-derived sequences catch immediate switches,
 * accumulated interrupted delays, inverted hysteresis and stale re-entry.
 */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { embodyDispatch } from './embodyVectorDispatch.mjs';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: ['client3d/src/scene/cameraFraming.ts'],
  bundle: true, platform: 'node', format: 'esm', write: false,
});
const framing = await import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`);
assert.equal(typeof framing.FirstPersonZoom, 'function', 'camera needs a delayed first-person transition');
const result = runVectors({ ...loadVectors('camera'), cases: loadVectors('camera').cases
  .filter(c => c.fn === 'firstPersonZoomSequence') }, embodyDispatch);
assert.equal(result.failed, 0, 'shared first-person zoom sequences');
console.log('PASS: first-person dwell, hysteresis, interrupted input and control reset');
