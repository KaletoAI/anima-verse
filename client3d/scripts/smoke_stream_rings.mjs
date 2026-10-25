#!/usr/bin/env node
/** NEU: absent on a241a8aa. Hand oracles: near enters at 150, exits at
 * 180; far enters at 520+40=560, exits at 560*1.2=672. Pins override.
 * Square centred at (200,0), half-side 60: west edge 140. No boundary:
 * 100-40*sqrt(1/2)=71.7157287525. Two points: min(300,120)=120.
 * Rotated square: yaw PI/2 moves the local z edge to world x; inside = 0.
 */
import { build } from 'esbuild';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const out = await build({ entryPoints: ['client3d/src/game/streamRings.ts'], bundle: true, write: false, format: 'esm', platform: 'node' });
const fns = await import(`data:text/javascript;base64,${Buffer.from(out.outputFiles[0].text).toString('base64')}`);
const file = loadVectors('scene_view');
// G1–G19 preserve all nineteen original assertions, including the composed
// square-distance -> near-ring check (G15/G16).
const { passed, failed } = runVectors({ ...file, cases: file.cases.filter(c => c.label.startsWith('[G')) }, fns);
console.log(`${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
