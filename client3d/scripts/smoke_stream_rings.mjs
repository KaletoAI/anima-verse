#!/usr/bin/env node
/** NEU: absent on a241a8aa. Hand oracles: near enters at 150, exits at
 * 180; far enters at 520+40=560, exits at 560*1.2=672. Pins override.
 * Square centred at (200,0), half-side 60: west edge 140. No boundary:
 * 100-40*sqrt(1/2)=71.7157287525. Two points: min(300,120)=120.
 * Rotated square: yaw PI/2 moves the local z edge to world x; inside = 0.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const out = await build({ entryPoints: ['client3d/src/game/streamRings.ts'], bundle: true, write: false, format: 'esm', platform: 'node' });
const { ringFor, placeDistance } = await import(`data:text/javascript;base64,${Buffer.from(out.outputFiles[0].text).toString('base64')}`);
for (const [cur, d, want] of [['gone', 130, 'near'], ['gone', 400, 'far'], ['gone', 561, 'gone'], ['near', 170, 'near'], ['near', 181, 'far'], ['near', 700, 'gone'], ['far', 600, 'far'], ['far', 673, 'gone'], ['far', 149, 'near'], ['gone', 150, 'near'], ['near', 180, 'near'], ['gone', 560, 'far'], ['far', 672, 'far']])
    assert.equal(ringFor(d, cur, false, 520), want, `${cur}/${d}`);
assert.equal(ringFor(900, 'gone', true, 520), 'near');
const square = { center: { x: 200, z: 0 }, yaw: 0, boundary: [[-60, -60], [60, -60], [60, 60], [-60, 60]], width: 120 };
assert.equal(placeDistance(square, [{ x: 0, z: 0 }]), 140);
assert.equal(ringFor(140, 'gone', false, 520), 'near');
assert.equal(placeDistance({ ...square, yaw: Math.PI / 2 }, [{ x: 200, z: 0 }]), 0);
assert.ok(Math.abs(placeDistance({ ...square, center: { x: 100, z: 0 }, boundary: null, width: 40 }, [{ x: 0, z: 0 }]) - 71.7157287525381) < 1e-9);
assert.equal(placeDistance({ ...square, center: { x: 0, z: 0 }, boundary: null, width: 0 }, [{ x: 300, z: 0 }, { x: 120, z: 0 }]), 120);
console.log('PASS stream rings');
