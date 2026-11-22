#!/usr/bin/env node
/**
 * The channel readout REPORTER (`client3d/src/game/readoutReports.ts`, plan pair scene Task 5): per (scene, receiver,
 * channel, entering) at most one row per second — the MEANS of insertionOfDepth and partRadiusM over the window, the
 * LAST restRadiusM and depthM, and the number of reach EDGES (insertionOfDepth going from < 1, or from not engaged,
 * to >= 1) — one send per scene with all its due rows.
 *
 * Usage: node client3d/scripts/smoke_readout_reports.mjs
 *
 * EXPECTATIONS, DERIVED BY HAND (interval 1000 ms; sceneOf: R -> "S1", R2 -> "S2", Q -> "")
 * Key A = (R, inset, E), key B = (R2, mouth, E), key C = (Q, inset, E) — values (insertionOfDepth, partRadiusM,
 * restRadiusM, depthM):
 *   t 0     A (0.5, 0.02, 0.03, 0.2)   B (0.2, 0.01, 0.03, 0.2)   C (1.0, 0.02, 0.03, 0.2)
 *   t 250   A (1.0, 0.03, 0.03, 0.2)   -> edge 1 (0.5 -> 1.0)
 *   t 500   A (1.2, 0.03, 0.03, 0.2)   -> still >= 1, no edge
 *   t 750   A (0.8, 0.025, 0.03, 0.2)
 *   t 1000  A (1.0, 0.02, 0.031, 0.21) -> edge 2;  B (0.4, 0.03, 0.03, 0.2)
 * [1] nothing is sent before t 1000.
 * [2] at t 1000 (1000 - 0 >= 1000) two sends: S1 with A — insertion_of_depth (0.5 + 1 + 1.2 + 0.8 + 1) / 5 = 0.9,
 *     part_radius_m (0.02 + 0.03 + 0.03 + 0.025 + 0.02) / 5 = 0.025, rest 0.031, depth 0.21 (the last frame),
 *     reaches 2; S2 with B — (0.2 + 0.4) / 2 = 0.3, (0.01 + 0.03) / 2 = 0.02, rest 0.03, depth 0.2, reaches 0.
 *     C (receiver in no scene) is never sent.
 *   t 1100  A (1.0, 0.02, 0.03, 0.2)   -> the previous frame was >= 1: no edge (the edge state outlives the window)
 *   t 1600  nothing engaged            -> the edge state of A resets
 *   t 1700  A (1.0, 0.04, 0.03, 0.2)   -> edge 1
 *   t 2100  nothing engaged            -> A's window (opened at 1100) is due: 2100 - 1100 = 1000
 * [3] at t 2100 one send: S1 with A — (1 + 1) / 2 = 1.0, (0.02 + 0.04) / 2 = 0.03, rest 0.03, depth 0.2, reaches 1.
 * [4] t 2200 nothing engaged -> nothing more: three sends in all.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../src/game/readoutReports.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { createReadoutReporter, REPORT_INTERVAL_MS } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));

const close = (a, b, what) => assert.ok(Math.abs(a - b) < 1e-12, `${what}: ${a} != ${b}`);
const ro = (receiver, channel, insertionOfDepth, partRadiusM, restRadiusM = 0.03, depthM = 0.2) =>
  ({ receiver, channel, entering: 'E', insertionOfDepth, partRadiusM, restRadiusM, depthM });
const scenes = { R: 'S1', R2: 'S2', Q: '' };
const sent = [];
const report = createReadoutReporter((r) => sent.push({ ...r }), (name) => scenes[name] ?? '');
assert.equal(REPORT_INTERVAL_MS, 1000);

report([ro('R', 'inset', 0.5, 0.02), ro('R2', 'mouth', 0.2, 0.01), ro('Q', 'inset', 1.0, 0.02)], 0);
report([ro('R', 'inset', 1.0, 0.03)], 250);
report([ro('R', 'inset', 1.2, 0.03)], 500);
report([ro('R', 'inset', 0.8, 0.025)], 750);
// [1]
assert.equal(sent.length, 0, '[1] nothing before 1000 ms');
report([ro('R', 'inset', 1.0, 0.02, 0.031, 0.21), ro('R2', 'mouth', 0.4, 0.03)], 1000);
// [2]
assert.equal(sent.length, 2, '[2] two sends at 1000 ms');
const s1 = sent.find((s) => s.scene_id === 'S1'), s2 = sent.find((s) => s.scene_id === 'S2');
assert.equal(s1.readouts.length, 1);
const a = s1.readouts[0];
assert.deepEqual([a.receiver, a.channel, a.entering], ['R', 'inset', 'E']);
close(a.insertion_of_depth, 0.9, '[2] A mean insertion share');
close(a.part_radius_m, 0.025, '[2] A mean part radius');
assert.deepEqual([a.rest_radius_m, a.depth_m, a.reaches], [0.031, 0.21, 2], '[2] A last rest/depth, two edges');
const b = s2.readouts[0];
close(b.insertion_of_depth, 0.3, '[2] B mean insertion share');
close(b.part_radius_m, 0.02, '[2] B mean part radius');
assert.deepEqual([b.rest_radius_m, b.depth_m, b.reaches], [0.03, 0.2, 0], '[2] B');
assert.ok(!sent.some((s) => s.scene_id === ''), '[2] no scene, no report');

report([ro('R', 'inset', 1.0, 0.02)], 1100);
report([], 1600);
report([ro('R', 'inset', 1.0, 0.04)], 1700);
report([], 2100);
// [3]
assert.equal(sent.length, 3, '[3] one send at 2100 ms');
const a2 = sent[2].readouts[0];
assert.equal(sent[2].scene_id, 'S1');
close(a2.insertion_of_depth, 1.0, '[3] mean');
close(a2.part_radius_m, 0.03, '[3] part radius');
assert.deepEqual([a2.rest_radius_m, a2.depth_m, a2.reaches], [0.03, 0.2, 1], '[3] one edge');
// [4]
report([], 2200);
assert.equal(sent.length, 3, '[4] nothing more');
console.log('all readout report checks passed');
