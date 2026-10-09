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
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const { outputFiles } = await build({
  entryPoints: ['client3d/src/scene/cameraFraming.ts'],
  bundle: true, platform: 'node', format: 'esm', write: false,
});
const framing = await import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`);
assert.equal(typeof framing.FirstPersonZoom, 'function', 'camera needs a delayed first-person transition');
const zoom = new framing.FirstPersonZoom();
const step = (distance, seconds, expected, enabled = true) => {
  assert.equal(zoom.update(distance, enabled, seconds), expected,
    `${distance} m for ${seconds} s, enabled=${enabled}`);
};

// A brief touch cannot switch; interrupted entry must restart its delay.
step(1.2, 0.1, false);
step(1.3, 0.1, false);
step(1.2, 0.1, false);
step(1.2, 0.079, false);
step(1.2, 0.001, true);
// Either side of the band keeps first person, however long it lasts.
step(1.2001, 1, true);
step(1.7999, 1, true);
// A brief outward nudge cannot exit; interrupted exit must restart.
step(1.8, 0.1, true);
step(1.7, 0.1, true);
step(1.8, 0.1, true);
step(1.8, 0.079, true);
step(1.8, 0.001, false);
step(1.2001, 1, false);
step(1.7999, 1, false);
// No first person in overview, nor a leftover delay on taking control again.
step(0.8, 0.18, false, false);
step(0.8, 0.1, false);
step(0.8, 0.001, false, false);
step(0.8, 0.1, false);
step(0.8, 0.08, true);
step(0.8, 0.001, false, false);
console.log('PASS: first-person dwell, hysteresis, interrupted input and control reset');
