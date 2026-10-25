#!/usr/bin/env node
/**
 * Smoke check for the baked-surface sampler — packages/scene-render/src/surface.ts.
 * Usage:  node client3d/scripts/smoke_surface_math.mjs
 * Every expected number is derived BY HAND (spec-surface-height § 6.2); the SAME
 * table drives scripts/smoke_model_surface.py part 2 — that equality is the proof
 * that client and server compute one height.
 *
 * S1: step 1, origin [-1,-1], cols 3, rows 3, box_min [-1,0,-1], box_max [1,1,1],
 *     extent_snapped [2,1,2], values (j rows of i):
 *       j=0: [0, 100, 200]   j=1: [0, 100, 200]   j=2: [null, 100, 200]
 *     -> height = 100*(mx+1) cm on the model's x, one null node at (i=0, j=2).
 * P1: anchor [4,-3], yaw_deg 90, bottom_y 0.5, max_m 4, measure 'xz'
 *     s = 4 / max(2,2) = 2;  c = (0, 0.5, 0)
 *     inverse of three's Ry(+90): lx = -qz, lz = qx   (q = world - anchor)
 *     model coords m = l / s + c.xz;  u = m.x + 1,  v = m.z + 1
 *   A  (4,-3)    q=(0,0)      l=(0,0)      m=(0,0)       u=1,    v=1   -> 100 -> 0.5 + 2*1.00 = 2.5
 *   B  (4,-5)    q=(0,-2)     l=(2,0)      m=(1,0)       u=2,    v=1   -> 200 -> 0.5 + 2*2.00 = 4.5
 *   C  (2,-2.5)  q=(-2,0.5)   l=(-0.5,-2)  m=(-0.25,-1)  u=0.75, v=0   ->  75 -> 0.5 + 2*0.75 = 2.0
 *   D  (5,-2)    q=(1,1)      l=(-1,1)     m=(-0.5,0.5)  u=0.5,  v=1.5 -> null neighbour (0,2) -> null
 *   E  (4,-6)    q=(0,-3)     l=(3,0)      m=(1.5,0)     u=2.5 > cols-1        -> null
 * P2: like P1 but measure 'xyz', extent_snapped [2,3,2], max_m 4 -> s = 4/3
 *   F  (4,-3)    as A                                                  -> 100 -> 0.5 + (4/3)*1.00 = 1.8333333
 * P3: like P1 but yaw_deg 0, so l = q
 *   G  (3.5,-5)  q=(-0.5,-2)  l=(-0.5,-2)  m=(-0.25,-1)  u=0.75, v=0   ->  75 -> 0.5 + 2*0.75 = 2.0
 *   H  (4,-3) on S1 with `values` truncated to four entries [0,100,200,0]: A's corner
 *      indices are 4, 5, 7, 8 — all past the end -> no node -> null. A corrupt sidecar
 *      reads as a hole (terrain takes over), in TS as in Python, never as an error.
 *   I  (4,-3) = A with the § A16.9 terrain LIFT 0.75 the placement was moved by after
 *      place(): the lattice stands where its model stands, so the whole answer moves
 *      with it -> 2.5 + 0.75 = 3.25. Lift 0 reproduces A exactly.
 * Highest: [S1@P1, S1@P1 with bottom_y 1.0] at A -> max(2.5, 3.0) = 3.0
 *          [S1@P1, S1@P1 with bottom_y 1.0] at D -> both null -> null
 *          [S1@P1, S2] where S2 = S1 with values all null -> A -> 2.5
 *          each entry with ITS OWN lift: [S1@P1 lift 0.75, S1@P1 lift 0] at A ->
 *          max(3.25, 2.5) = 3.25, and the lower entry alone stays 2.5 — the lift
 *          is read off the entry, never off the list.
 * C and G sample v = 0 on purpose: a point at v = 1 sits in the cell spanning rows
 * j=1..2, which touches the null node (0,2) and is therefore null by design (D). The
 * bilinear reading is tested one row of nodes away from that hole, at the same u = 0.75.
 */
import { runModelVectors } from './smoke_scene_models.mjs';
const { passed, failed } = await runModelVectors(c => c.label.startsWith('[H]'));
console.log(`\n${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
