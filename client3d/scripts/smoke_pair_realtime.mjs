#!/usr/bin/env node
/**
 * Smoke check for the PAIR-CLIP PHASE — `client3d/src/game/pairClip.ts`, the
 * one place that turns the server's game-clock numbers (§ A8a) into the time
 * the mixer of `scene/figures.ts` `playPair()` is seeked to.
 *
 * Usage:  node client3d/scripts/smoke_pair_realtime.mjs
 *         (needs esbuild — reachable as `node_modules/esbuild` from the repo
 *          root; the module itself is import-free and is transpiled, not
 *          bundled.)
 *
 * Every number below is derived BY HAND in this docstring from the rule of
 * plan-animationen-echtzeit-stehplatz.md E1/T1, never recorded from the
 * current output (§ B5a: numbers, not screenshots).
 *
 * THE RULE (E1). Every animation runs in REAL time, whatever the game-speed
 * factor is. The server states `elapsed_s` in GAME seconds and `rate` in game
 * seconds per real second. So the clip's own clock — real seconds since the
 * interaction started — is `elapsed_s / rate`, and the mixer runs at
 * `timeScale 1`. The factor decides only two things: WHERE the clip stands
 * when a poll arrives, and whether it stands still at all (`rate = 0`,
 * frozen world). The phase itself is then the clip clock wrapped or clamped:
 *
 *     clipT = rate > 0 ? elapsed_s / rate : (the local clock, unchanged)
 *     phase = loop ? clipT mod clip_duration_s : min(clipT, clip_duration_s)
 *
 * WHY IT MATTERS. Before this, `playPair` set `action.timeScale = rate`, so a
 * world running at factor 2 played the pair clips at double speed while the
 * solo clips next to them (timeScale 1) played at their authored speed — two
 * figures shaking hands twice as fast as the third one waving at them.
 *
 * ============================================================================
 * [1] THE CLIP CLOCK IS REAL TIME — the same real second gives the same phase
 * ============================================================================
 * Clip `handshake` as a CYCLE of 0.533 s. Three worlds standing at the SAME
 * real moment, 3 s into the interaction:
 *
 *   rate 2.0, elapsed 6.0 game-s -> clipT = 6.0 / 2.0 = 3 real s
 *   rate 1.0, elapsed 3.0 game-s -> clipT = 3.0 / 1.0 = 3 real s
 *   rate 0.5, elapsed 1.5 game-s -> clipT = 1.5 / 0.5 = 3 real s
 *
 * and 3 s of a 0.533 s cycle is the sixth pass through it:
 *   5 x 0.533 = 2.665;  3 - 2.665 = 0.335  -> phase 0.335 s in all three.
 * (The brief's hand case: rate 2, elapsed 6, cycle 0.533 -> (3 mod 0.533).)
 *
 * ============================================================================
 * [2] rate 0 FREEZES: the phase stays where it was
 * ============================================================================
 * A frozen world has no clip position to divide out — `elapsed_s / 0` is not a
 * number, and the last local phase is the right one to hold. With a local
 * clock of 0.4 s and any `elapsed_s` the server may still be reporting:
 *   clipT = 0.4 (unchanged)  -> phase = 0.4 mod 0.533 = 0.4
 * Adopting a NEW interaction in a frozen world has no local clock to keep, so
 * it starts at 0: clipT = 0 -> phase 0.
 *
 * ============================================================================
 * [3] A ONE-SHOT CLIP HOLDS ITS LAST FRAME
 * ============================================================================
 * `handshake` as a one-shot of 2.533 s (the brief's second hand case):
 *   rate 1, elapsed 10 game-s -> clipT = 10 real s -> phase = min(10, 2.533)
 *                                                          = 2.533  (clamped)
 * Below the end nothing is clamped: clipT 2.0 -> phase 2.0. And exactly at the
 * end: clipT 2.533 -> 2.533. The same clipT in a LOOPING clip of that length
 * would wrap instead: 10 - 3 x 2.533 = 10 - 7.599 = 2.401.
 *
 * ============================================================================
 * [4] A POLL SNAPS ONLY A GENUINE DRIFT (PAIR_SNAP_S = 0.3 real s)
 * ============================================================================
 * Between polls the client counts real frame seconds itself, so a poll that
 * merely confirms what the client already has must not re-seek the action —
 * that is what made the figure stutter once a second. Local clock 3.0 s:
 *
 *   rate 2, elapsed 6.5 -> server 3.25, drift 0.25 <= 0.3 -> keep 3.0
 *                          -> phase 3.0 - 2.665 = 0.335
 *   rate 2, elapsed 7.0 -> server 3.50, drift 0.50 >  0.3 -> take 3.5
 *                          -> 6 x 0.533 = 3.198; 3.5 - 3.198 = 0.302
 *   rate 2, elapsed 7.0, snapS 0.5 -> drift 0.5 is NOT more than 0.5
 *                          -> keep 3.0, phase 0.335
 *                          (the threshold is "more than", tested on numbers
 *                           that are exact in binary so the boundary is real)
 *
 * A frozen world never snaps at all (no server position, [2]), and adoption —
 * no local clock — always takes the server's value whatever the drift.
 *
 * ============================================================================
 * [5] THE FRAME ADVANCE (how `scene/npcs.ts` composes it)
 * ============================================================================
 * Per frame the caller adds the REAL frame time to the clip clock while the
 * world runs (`if (rate > 0) clipT += dt`) and asks for the phase with no
 * server value at all. Three frames of 1/60 s on top of clipT 3.0:
 *   3.0 + 3/60 = 3.05  -> phase = 3.05 - 2.665 = 0.385
 * The same three frames in a world at factor 2 give the same 0.385 — the frame
 * time is real seconds and nothing multiplies it. In a frozen world the three
 * frames add nothing: phase stays 0.335.
 *
 * ============================================================================
 * [6] DEGENERATE INPUTS never produce NaN
 * ============================================================================
 * A clip length of 0 (a listing without `clip_duration_s`) has no cycle to
 * wrap in: the phase is the clock itself, 3.0. A negative local clock cannot
 * happen but must not seek backwards either: clamped to 0.
 *
 * WHAT THIS FILE DOES NOT COVER: `playPair` applies the same wrap/clamp once
 * more against the ACTION's own duration (the loaded clip may be a frame
 * longer than the sidecar says) and drives `action.timeScale = frozen ? 0 : 1`
 * plus the three.js loop mode. That needs a mixer and a rig; the numbers it
 * works with are the ones pinned here.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** Transpile the import-free module and import it as plain ESM. */
async function loadModule(relPath) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'pairclip-'));
  try {
    const source = await readFile(join(ROOT, relPath), 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'mod.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let passed = 0;
let failed = 0;
function near(label, actual, expected, eps = 1e-6) {
  const ok = Number.isFinite(actual) && Math.abs(actual - expected) <= eps;
  if (ok) { passed += 1; console.log(`  ok   ${label}: ${actual.toFixed(4)}`); }
  else { failed += 1; console.log(`  FAIL ${label}: got ${actual}, want ${expected} ±${eps}`); }
}

const CYCLE = 0.533;
const ONCE = 2.533;

const { pairClipPhase, PAIR_SNAP_S } = await loadModule('client3d/src/game/pairClip.ts');

console.log('[1] the clip clock is REAL time — one phase for every game speed');
for (const [rate, elapsed] of [[2, 6], [1, 3], [0.5, 1.5]]) {
  const r = pairClipPhase({ elapsedGameS: elapsed, rate, loop: true, clipDurationS: CYCLE });
  near(`rate ${rate}, elapsed ${elapsed} game-s → clipT`, r.clipT, 3);
  near(`rate ${rate}, elapsed ${elapsed} game-s → phase`, r.phase, 0.335);
}

console.log('\n[2] rate 0 freezes the phase');
{
  const held = pairClipPhase({
    elapsedGameS: 6, rate: 0, loop: true, clipDurationS: CYCLE, localClipT: 0.4 });
  near('frozen, local clock 0.4 → clipT', held.clipT, 0.4);
  near('frozen, local clock 0.4 → phase', held.phase, 0.4);
  const fresh = pairClipPhase({ elapsedGameS: 6, rate: 0, loop: true, clipDurationS: CYCLE });
  near('frozen adoption → clipT', fresh.clipT, 0);
  near('frozen adoption → phase', fresh.phase, 0);
}

console.log('\n[3] a one-shot clip holds its last frame');
{
  const late = pairClipPhase({ elapsedGameS: 10, rate: 1, loop: false, clipDurationS: ONCE });
  near('rate 1, elapsed 10 → clipT', late.clipT, 10);
  near('… → phase clamped to the clip length', late.phase, 2.533);
  near('below the end nothing is clamped',
    pairClipPhase({ elapsedGameS: 2, rate: 1, loop: false, clipDurationS: ONCE }).phase, 2.0);
  near('exactly at the end',
    pairClipPhase({ elapsedGameS: 2.533, rate: 1, loop: false, clipDurationS: ONCE }).phase, 2.533);
  near('the same clock in a LOOPING clip of that length wraps',
    pairClipPhase({ elapsedGameS: 10, rate: 1, loop: true, clipDurationS: ONCE }).phase, 2.401);
}

console.log('\n[4] a poll snaps only a genuine drift');
{
  const base = { rate: 2, loop: true, clipDurationS: CYCLE, localClipT: 3.0 };
  const keep = pairClipPhase({ ...base, elapsedGameS: 6.5 });
  near('drift 0.25 ≤ 0.3 → the local clock stands', keep.clipT, 3.0);
  near('… → phase', keep.phase, 0.335);
  const snap = pairClipPhase({ ...base, elapsedGameS: 7.0 });
  near('drift 0.50 > 0.3 → the server value wins', snap.clipT, 3.5);
  near('… → phase', snap.phase, 0.302);
  near('the threshold is "more than" (snapS 0.5, drift 0.5 → keep)',
    pairClipPhase({ ...base, elapsedGameS: 7.0, snapS: 0.5 }).clipT, 3.0);
  near('a frozen world never snaps',
    pairClipPhase({ ...base, rate: 0, elapsedGameS: 99 }).clipT, 3.0);
  near('adoption takes the server value whatever the drift',
    pairClipPhase({ ...base, localClipT: undefined, elapsedGameS: 99 }).clipT, 49.5);
  near('PAIR_SNAP_S is the documented 0.3 real s', PAIR_SNAP_S, 0.3);
}

console.log('\n[5] the frame advance as scene/npcs.ts composes it');
{
  const step = (clipT, rate, dt) => {
    const next = rate > 0 ? clipT + dt : clipT;
    return pairClipPhase({
      elapsedGameS: null, rate, loop: true, clipDurationS: CYCLE, localClipT: next });
  };
  for (const rate of [1, 2]) {
    let clipT = 3.0;
    let phase = 0;
    for (let i = 0; i < 3; i += 1) ({ clipT, phase } = step(clipT, rate, 1 / 60));
    near(`rate ${rate}: three 1/60 s frames → clipT`, clipT, 3.05);
    near(`rate ${rate}: … → phase`, phase, 0.385);
  }
  let clipT = 3.0;
  let phase = 0;
  for (let i = 0; i < 3; i += 1) ({ clipT, phase } = step(clipT, 0, 1 / 60));
  near('frozen: three frames add nothing → clipT', clipT, 3.0);
  near('frozen: … → phase', phase, 0.335);
}

console.log('\n[6] degenerate inputs');
{
  near('clip length 0 → the phase is the clock itself',
    pairClipPhase({ elapsedGameS: 3, rate: 1, loop: true, clipDurationS: 0 }).phase, 3.0);
  near('clip length 0, one-shot → the same',
    pairClipPhase({ elapsedGameS: 3, rate: 1, loop: false, clipDurationS: 0 }).phase, 3.0);
  near('a negative local clock never seeks backwards',
    pairClipPhase({ elapsedGameS: null, rate: 1, loop: true, clipDurationS: CYCLE,
      localClipT: -2 }).phase, 0);
}

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
