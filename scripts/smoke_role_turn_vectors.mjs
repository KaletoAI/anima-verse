#!/usr/bin/env node
/**
 * ROLE TURN vectors (owner decision 2026-11-23): every role of a pair/group clip may carry a renderer-only turn,
 * the listing's `orientation.role_turn_deg` = { "<role a..e>": [tilt, roll, yaw] } degrees (absent role = no turn).
 * A figure playing the role-r half is turned by role_turn_deg[r] about its bind hips: frame F = eulerYXZ(0, yaw, 0),
 * pivot = fixPivot(root, F, hipsBind), fix = roleTurnFix(tilt, roll, F, yaw), then fixRoot(fix, pivot, root)
 * (packages/scene-render/src/pairFit.ts; the browser 3D scene's npcs.ts applyPairFix; native Core/Figures/RoleTurn.cs).
 * This smoke runs shared/test-vectors/role_turn.json through the TypeScript; native/tests/RoleTurnVectorTests.cs runs
 * it through the C# port. Every expected number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_role_turn_vectors.mjs   (no server, no world; bundles pairFit.ts with esbuild)
 *
 * Conventions: matrices row-major; rotY(φ) = [cφ,0,sφ; 0,1,0; −sφ,0,cφ], rotX(φ) = [1,0,0; 0,cφ,−sφ; 0,sφ,cφ],
 * rotZ(φ) = [cφ,−sφ,0; sφ,cφ,0; 0,0,1]; a rotation vector θ = angle·axis. I = the identity frame,
 * F90 = eulerYXZ(0, 90°, 0) = rotY(90°) = [0,0,1; 0,1,0; −1,0,0]: side (column 0) = (0,0,−1), up (column 1) = (0,1,0),
 * forward (column 2) = (1,0,0). k = (2π/3)/√3 = 1.2091995761561452. s45 = sin 45° = cos 45° = 0.7071067811865476.
 * All cases eps 1e-12.
 *
 * [1] tilt = roll = yaw = 0: turn = side·0 + forward·0 = (0,0,0), shift (0,0,0); no composition (yaw 0).
 * [2] I, tilt 10°: turn = (1,0,0)·10° = (0.17453292519943295, 0, 0) (10π/180). Roll 10°: (0, 0, 0.17453292519943295).
 * [3] F90, yaw 90° alone: roleYawFix = up·π/2 = (0, π/2, 0); composed with the zero tilt/roll fix R = rotY(90°)·I,
 *     matrixTurn: trace 1 → cos a = 0, a = π/2; v = (m7−m5, m2−m6, m3−m1) = (0, 2, 0) → (0, π/2, 0) = (0, 1.5707963267948966, 0).
 *     I, yaw 180° alone: R = rotY(π) = [−1,0,0; 0,1,0; 0,0,−1] (+ ~1e-16 off-diagonals), trace −1 → a = π; v ≈ 0, so the
 *     half-turn branch: S = (R + Rᵀ)/4 + I/2 has diagonal (0, 1, 0) → axis row 1 = (0, 1, 0), sign + (v·n = 2 sin π ≥ 0)
 *     → (0, π, 0) = (0, 3.141592653589793, 0) — a half turn, never "no turn".
 * [4] I, yaw 90° then tilt 90°: R = rotX(90°)·rotY(90°) = [1,0,0; 0,0,−1; 0,1,0]·[0,0,1; 0,1,0; −1,0,0] = [0,0,1; 1,0,0; 0,1,0]
 *     (x→y→z→x). Trace 0 → cos a = −1/2, a = 2π/3; v = (1−0, 1−0, 1−0) = (1,1,1), |v| = √3 → (k, k, k).
 *     F90, the same turn about F's axes: R' = F·R·Fᵀ, its axis F·(1,1,1) = (0·1+0·1+1·1, 1, −1) = (1, 1, −1) → (k, k, −k).
 * [5] F90, tilt 90° alone: turn = side·π/2 = (0, 0, −π/2) = (0, 0, −1.5707963267948966).
 * [6] turnMatrix((0, π/2, 0)) = rotY(90°) = [0,0,1, 0,1,0, −1,0,0]. matrixTurn of [0,0,1; 1,0,0; 0,1,0] = (k,k,k) ([4]).
 *     matrixTurn of the exact [−1,0,0; 0,1,0; 0,0,−1]: a = π, v = (0,0,0), S diagonal (0,1,0) → (0, π, 0), sign + (v·n = 0).
 * [7] fixPivot((1, 0.5, −2), F90, (0.1, 0.95, 0.2)): F·h = (0.2, 0.95, −0.1) → (1.2, 1.45, −2.1).
 * [8] fixRoot(turn (0,0,−π/2), pivot (1, 1.45, −2), root (1, 0.5, −2)): rotZ(−90°) maps (x, y) → (y, −x); root − pivot =
 *     (0, −0.95, 0) → (−0.95, 0, 0); + pivot → (0.05, 1.45, −2). Quaternion: angle π/2 about −Z → (0, 0, −s45, s45).
 * roleTurnPlaced(map, role, root, yawDeg, hipsBind) — the whole placement of npcs.ts applyPairFix as a pure chain: the
 *     role's turn = map[role] when it is an array of exactly three finite numbers, else [0,0,0] (native
 *     RoleTurnDeg.Parse); F = eulerYXZ(0, yawDeg·π/180, 0); pivot = fixPivot(root, F, hipsBind); fix = roleTurnFix(…, F,
 *     yaw); result = fixRoot(fix, pivot, root).
 * [9]  {b: [10,0,0]}, b, root 0, yaw 0, hips (0,1,0): rotX(10°) of (0, −1, 0) = (0, −cos 10°, −sin 10°); + (0,1,0) →
 *      (0, 1 − cos 10°, −sin 10°) = (0, 0.01519224698779198, −0.17364817766693033) — tilting forward swings the feet back.
 *      Quaternion (sin 5°, 0, 0, cos 5°) = (0.08715574274765817, 0, 0, 0.9961946980917455).
 * [10] group map {a: [0,0,45], b: [10,0,0], c: [0,90,0]}, role c, root (2,0,3), yaw 0, hips (0,0.9,0): roll 90° = rotZ(90°),
 *      (x, y) → (−y, x): (0, −0.9, 0) → (0.9, 0, 0); + pivot (2, 0.9, 3) → (2.9, 0.9, 3); quaternion (0, 0, s45, s45).
 * [11] the same map, role d (absent) → identity: position (2, 0, 3), quaternion (0,0,0,1) (fixRoot of a zero turn: s = 0.5,
 *      w = cos 0). A malformed entry {b: [10, "x", 0]} → identity likewise.
 * [12] {b: [0,0,180]}, root (1,0,0), yaw 0, hips (0,0.9,0): the turn is (0, π, 0) ([3]), about the vertical through the
 *      hips (1, 0.9, 0); root − pivot = (0, −0.9, 0) lies ON that axis → the root stays at (1, 0, 0). Quaternion
 *      (0, sin 90°, 0, cos 90°) = (0, 1, 0, 0).
 * [13] {b: [90,0,0]}, root (1, 0.5, −2), yaw 90°, hips (0, 0.95, 0): F = F90, pivot = (1, 1.45, −2), turn (0,0,−π/2) ([5])
 *      → position (0.05, 1.45, −2), quaternion (0, 0, −s45, s45) ([8]).
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../shared/test-vectors/vectors.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const dir = await mkdtemp(join(root, 'scripts/.smoke-role-turn-'));
let m;
try {
  const esbuild = await import(join(root, 'node_modules/esbuild/lib/main.js'));
  const built = await esbuild.build({
    stdin: { contents: `export { roleTurnFix, fixPivot, fixRoot, turnMatrix, matrixTurn } from '${root}packages/scene-render/src/pairFit.ts';
export { eulerYXZ } from '${root}packages/scene-render/src/clipCalibration.ts';`, resolveDir: root, loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false,
    outfile: join(dir, 'rt.mjs'), external: ['three', 'three/*'], logLevel: 'error',
  });
  const file = join(dir, 'rt.mjs');
  await writeFile(file, built.outputFiles[0].text);
  m = await import(`file://${file}`);
} finally { await rm(dir, { recursive: true, force: true }); }

/** The role's stored turn as both clients read it: exactly three finite numbers, else none. */
const turnOf = (map, role) => {
  const t = map && typeof map === 'object' ? map[role] : undefined;
  return Array.isArray(t) && t.length === 3 && t.every((v) => typeof v === 'number' && Number.isFinite(v)) ? t : [0, 0, 0];
};
const { passed, failed } = runVectors(loadVectors('role_turn'), {
  roleTurnFix: (tilt, roll, frame, yaw) => m.roleTurnFix(tilt, roll, frame, yaw),
  turnMatrix: (w) => m.turnMatrix(w),
  matrixTurn: (r) => m.matrixTurn(r),
  fixPivot: (p, frame, hips) => m.fixPivot(p, frame, hips),
  fixRoot: (fix, pivot, p) => m.fixRoot(fix, pivot, p),
  roleTurnPlaced: (map, role, p, yawDeg, hips) => {
    const [tilt, roll, yaw] = turnOf(map, role);
    const frame = m.eulerYXZ(0, yawDeg * Math.PI / 180, 0);
    const pivot = m.fixPivot(p, frame, hips);
    return m.fixRoot(m.roleTurnFix(tilt, roll, frame, yaw), pivot, p);
  },
});
console.log(`role_turn: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
