#!/usr/bin/env node
/**
 * The per-strand hair sim, pure (`packages/scene-render/src/hairSimMath.ts`; strand-hair plan 2026-11-13,
 * Task 7; spec § 6.2.1, a port of the HAAR spike's `sim.js` round 3). Hand-derived.
 *
 * Usage: node scripts/smoke_hair_sim.mjs   (no server, no world, no three; bundles itself with esbuild)
 *
 * FIXTURE (metres, bind space = world at rest, built here as the server would build the record):
 *   HEAD: the head sphere of Task 4 (centre (0, 1.60, 0), r 0.09) as an analytic SDF quantized into the record
 *     format: lo (−0.15, 1.46, −0.16), vox 0.0068, dims (45, 44, 48), int8 round(1000·(|p − c| − 0.09)) clamped
 *     to ±127. ear_y 1.5625 (Task 4's fixture). face_box [−0.06, 0.06, 1.48, 1.66, 0.0225] (z0 = 0.25 · 0.09),
 *     eye_box [−0.04, 0.04, 1.555, 1.645, 0.0225]. follow {Head: 1}. No capsules except in [7].
 *     params = the spike's round-3 DEFAULTS (sim.js): damping 0.04, stiffness 1, bend 0.15, iterations 6,
 *     root_deg 10, root_frac 0.2, fly_soft, fly_arc 0.30 (FLY_ARC), tether, tether_r0 0.015, tether_r1 0.06,
 *     tether_head 0.012, head_clr 0.03, face_box.
 *   CARDS: 60 cards at azimuth θ_k = 75° + (k + ½)·3.5° (the back and both sides, dir (sin θ, 0, cos θ), up to
 *     the face plane: the first card's rows lie at z ≤ 0.092·cos 76.75° = 0.0211 < z0 0.0225 — the scalp of [5]
 *     ends at z0, so the cards cover all of it; a fan ending at 90° leaves the scalp strip 0 < z < z0 to one edge
 *     card, and walking swings that edge open: +2.45 pp at 135°/225° with this sim AND with the spike's own
 *     `ChainSim` on the same fixture (they agree within 0.04 mm over 14 s)), each a
 *     path 2 mm off the sphere (ρ = 0.092) from the polar angle α0 = 30° down the sphere to its equator (arc
 *     ρ·(90° − 30°) = 0.092 · 1.047198 = 0.096342), then straight down; 17 rows 0.02 m of path apart (rows 0..4
 *     on the sphere, row 16 at y 1.60 − (0.32 − 0.096342) = 1.376342). 2 vertices per row, ±4 mm along the
 *     horizontal tangent (cos θ, 0, −sin θ); `_STRAND_U` = the row, `_STRAND_CARD` = k + 1. A rigid 4-vertex cap
 *     quad (card 0) at y 1.695, x/z ±0.02.
 *   PINS (Task 4's rule `scalp_free`, by hand): the chord of 0.02 m of arc on ρ = 0.092 is 2ρ·sin(0.01/ρ) =
 *     0.184 · sin(0.108696) = 0.019961, so row 1 is at arc 0.019961 ≤ 0.02 (pinned by arc), row 2 at 0.039922 ≤
 *     0.04 with rows 0..2 all 2 mm ≤ 6 mm off the body (pinned by contact), row 3 at 0.059883 > 0.04 → pins = 3.
 *     free_arc / free_frac are the chord sums from row 2 (the server's `_arc`).
 *   The rows resting above the ear line < 3 cm off the head (rows 3..6: y 1.6354, 1.6163, 1.5963, 1.5763 >
 *     1.5625) are tethered to 12 mm; no row is "fly" (none rests > 3 cm off).
 *   MOTION (the spike's `rootMotion`, pivot (0, ear, 0); the whole figure moves rigidly, so head = follow =
 *     the root matrix): sway = yaw 15°·sin(πt), pitch 5°·sin(πt + π/2); walk = z 0.25·sin(πt), y
 *     0.015·(1 − cos 2πt); amplitude ramp `amp += (target − amp)·min(1, dt/0.5)`, 60 steps/s.
 *
 * [1] REST: 120 steps of 1/60 s, the frame constant (identity) → max |rebuilt − rest| == 0 for positions AND
 *     normals, exactly (the spike's restErrMm 0): every term of the step is zero at rest, the targets are the
 *     float32 rest, and the offsets reproduce the bind vertices within 1e-16 before rounding to float32.
 * [2] limitSegmentAngle: prev (0,0,0), restDir (0,−1,0), cur at 30° (0.05, −0.0866025, 0), cosLim cos 10° →
 *     (0.0173648, −0.0984808, 0) within 1e-6 (= 0.1 · (sin 10°, −cos 10°)); a cur at 5° comes back unchanged.
 * [3] TETHER: after a sway of 4 s every free row with f ≤ 1/3 is within r(f) = 0.015 + 0.045·3f of its target
 *     (+1e-6; the tether runs last in the step, so it holds exactly), and every tethered head row within 12 mm.
 * [4] sway and walk, 8 s + 6 s settle (the spike's `bench`, measured every 6 steps): maxSdfDepthMm ≤ 3,
 *     eyePointsEntered == 0 (no row rests inside the eye box: every row has |x| > 0.04 or z < 0.0225).
 * [5] SCALP EXPOSURE (the spike's `scalpAll`, 8 s, measured every 4 steps after the first second): three
 *     head-fixed cameras (yaw 180/135/225°, 0.85 m, 0.05 m up, aimed at (0, ear + 0.04, 0)); scalp = the
 *     sphere's triangles above the ear line behind the face plane (z < 0.0225) + the cap; the cards opaque →
 *     peak − rest ≤ 0.02 per camera, sway and walk.
 * [6] HAAR params (root_deg 0): one card hanging straight down at x 0.5 (outside the SDF grid: no collision),
 *     pins 2, rows 2..16 turned rigidly 30° about row 1 (Xp = X, dt 0 — no velocity, no pull; bend 0 and the
 *     tether off, so only the angle limit could act) → after a step nothing moved (1e-6). The same state with
 *     the HairDeck set (root_deg 10; row 2's f = 0.02/0.30 ≤ root_frac) → the segment 1→2 is turned back to
 *     10° (+1e-4) of the target direction.
 * [7] FOLLOW ROWS: Spine2 pitched +30° about +X at (0, 1.30, 0), Head the same matrix (unchanged relative to
 *     it). A straight card at z −0.10 from y 1.60 down (0.02 apart; rows with y < 1.52 follow {Spine2: 1}, the
 *     others {Head: 1}): row 10 at bind (0, 1.40, −0.10) has target (0, 1.30 + 0.1·cos30 + 0.1·sin30,
 *     0.1·sin30 − 0.1·cos30) == (0, 1.43660, −0.03660) within 1e-5. One torso capsule (a (0, 1.0, 0),
 *     b (0, 1.45, 0), r 0.08, on Spine2) under the bind rule; the 60 curved cards + that card + a LONG card at
 *     z −0.095 (rows 0.03 apart, down to y 1.12; 15 mm outside the capsule at bind), reset at the bind pose, then
 *     2 s in the pitched pose. The pitch swings the capsule's lower part back INTO the hanging long card (its
 *     axis point (0, 1.15, 0) goes to (0, 1.30 − 0.15·cos30, −0.15·sin30) = (0, 1.1701, −0.075), 20 mm from the
 *     row at (0, 1.15, −0.095) — 60 mm deep): without the capsule a row passes > 10 mm deep through it during the
 *     2 s (the case is real); with it no row is inside deeper than its bind depth after 2 s (+1e-6), nor at the
 *     end of any step on the way deeper than the sagitta of one clamped segment (Ruling H-R10: the length clamp's
 *     last shortening may cut the capsule by a chord, 0.08 − √(0.08² − (0.03·1.05/2)²) = 1.57 mm).
 * [8] StrandMismatch: a `_STRAND_CARD` of 62 for a 61-card record, and a `_STRAND_U` one value short.
 * RULING H-R10 (each step with dt 0 starts from X = Xp: no velocity, no pull; iterations 0, bend 0, root_deg 0 —
 * only the part under test acts):
 * [9] LENGTH CLAMP: a straight card at x 0.5 (outside the SDF grid), pins 2, row 9 held 0.10 m out along +x →
 *     the card's arc 0.32 − 0.04 + 2·hypot(0.10, 0.02) = 0.48396 (1.51× — the case is real). After one step
 *     every free segment ≤ 1.05 × 0.02 (+1e-6) and row 9 = row 8 + (0.10, −0.02, 0) · 0.021 / 0.1019804 =
 *     (0.5205922, 1.4358816, 0) within 1e-6 (shortened towards its parent, follow-the-leader).
 * [10] HEAD TETHER, LEADING RUN ONLY: the curved card at θ 180° with row 3 lifted 4 cm off the sphere (radially;
 *     not resting on the head), so rows 4..6 rest on the head AFTER a free row; upper-third tether out of reach
 *     (tether_r0 = tether_r1 = 10 m). Rows 4..16 turned 25° about +X through row 3, away from the head (lengths
 *     kept: the clamp does nothing; every row stays outside the head SDF + 3 mm and behind the face plane): row 6
 *     ends > 12 mm from its target, so the old rule (every head-resting row within tether_head) would have
 *     moved it → after one step rows 4..16 are where they were (1e-6).
 * [11] DAMPING RELATIVE TO THE TARGET: the straight card at x 0.5 on a figure moving at 3.4 m/s along +z (the
 *     game's WALK_SPEED) from a rest start, 4 s: at the end every row is within 1 mm of its target (the start's
 *     swing decays by 0.96^240 = 5.6e-5). Damped in world, the steady lag of the tip (free arc 0.30, k = 9.81/0.30)
 *     would be e = d·v·dt / (k·dt²) = 0.04 · 3.4 · (1/60) / (32.7 / 3600) = 0.2496 m before the constraints — the
 *     gale that blew every card horizontal; pulled towards the NEXT step's target the rows settled 107 mm behind.
 * [12] THE HEAD HAS THE LAST WORD: a straight card at the back, z −0.095 from y 1.60 down (row 2 at (0, 1.56,
 *     −0.095): 13.1 mm off the sphere, clearance min(3 mm, 13.1) = 3 mm); one capsule a = b = (0, 1.56, −0.135),
 *     r 0.06 (bind far away: radius factor 1). The capsule pushes row 2 to z −0.075 — hypot(0.04, 0.075) =
 *     0.085, 5 mm inside the head → after one step every free row's SDF ≥ its clearance − 0.5 mm (the SDF
 *     pushed once more, one gradient step on the quantized field).
 * [13] RootInertia (STRAND_ROOT_LIMITS accel 0.25π² = 2.4674 m/s², angAccel (15°)·π² = 2.5839 rad/s², 60 fps):
 *     (a) a root moving at 1 m/s along x from its first frame: every carry the identity (1e-9) — felt whole;
 *     (b) a root at rest that accelerates at 1 m/s² (< 2.4674) for 1 s: every carry the identity (1e-9);
 *     (c) a 1 m snap along x after rest: the felt velocity grows by 2.4674/60 = 0.0411234 m/s, the felt move is
 *         0.0411234/60 = 0.000685390 m → the carry is a translation by 0.999314610 m (1e-9), no rotation;
 *     (d) a 90° yaw snap after rest: the felt angle (2.5839/60)/60 = 0.000717738 rad → the carry is Ry(π/2 −
 *         0.000717738) (1e-9);
 *     (e) StrandSim.carry by Ry(90°): a card's rows and their previous positions turn with it (relative velocity
 *         kept: X − Xp turned by the same rotation, 1e-6).
 * [T] TIMING (printed, not asserted): 700 curved cards (the same fan, 0.3° apart), sway, ms per step and per
 *     rebuild (spike reference: 4.4–5.9 ms per step).
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'

if (!process.env.HAIR_SIM_BUNDLED) {
  const here = fileURLToPath(import.meta.url)
  const repo = path.resolve(path.dirname(here), '..')
  const bin = ['client3d/node_modules/esbuild/bin/esbuild', 'node_modules/esbuild/bin/esbuild']
    .map(rel => path.join(repo, rel)).find(existsSync)
  assert.ok(bin, 'esbuild unavailable (npm install) — nothing was checked')
  const out = `/tmp/smoke_hair_sim.${process.pid}.mjs`
  const built = spawnSync(bin, [here, '--bundle', '--platform=node', '--format=esm', `--outfile=${out}`,
    '--log-level=error'], { stdio: 'inherit' })
  assert.equal(built.status, 0)
  const run = spawnSync('node', [out], { stdio: 'inherit', env: { ...process.env, HAIR_SIM_BUNDLED: '1' } })
  spawnSync('rm', ['-f', out])
  process.exit(run.status ?? 1)
}

const M = await import('../packages/scene-render/src/hairSimMath.ts')
const { STRAND_ROWS, StrandSim, StrandMismatch, bindStrands, strandTargets, strandParams, limitSegmentAngle,
  eyePointsEntered, restInsideBox, maxSdfDepthMm, scalpExposure, scalpCameras, invertAffine } = M

let failures = 0
const check = (label, ok, detail = '') => {
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

const R = STRAND_ROWS
const C = [0, 1.60, 0], RAD = 0.09, RHO = 0.092, EAR = 1.5625
const ALPHA0 = 30 * Math.PI / 180, SPHERE_ARC = RHO * (Math.PI / 2 - ALPHA0)
const FACE_BOX = [-0.06, 0.06, 1.48, 1.66, 0.0225], EYE_BOX = [-0.04, 0.04, 1.555, 1.645, 0.0225]
const PARAMS = { damping: 0.04, stiffness: 1.0, bend: 0.15, iterations: 6, root_deg: 10, root_frac: 0.2,
  fly_soft: true, fly_arc: 0.30, tether: true, tether_r0: 0.015, tether_r1: 0.06, tether_head: 0.012,
  head_clr: 0.03, face_box: true }
const DT = 1 / 60

// --- the fixture -------------------------------------------------------------------------------------------------

function sdfPayload() {
  const lo = [-0.15, 1.46, -0.16], vox = 0.0068, dims = [45, 44, 48]
  const q = new Int8Array(dims[0] * dims[1] * dims[2])
  for (let iz = 0; iz < dims[2]; iz++) for (let iy = 0; iy < dims[1]; iy++) for (let ix = 0; ix < dims[0]; ix++) {
    const x = lo[0] + ix * vox, y = lo[1] + iy * vox, z = lo[2] + iz * vox
    const d = Math.hypot(x - C[0], y - C[1], z - C[2]) - RAD
    q[ix + dims[0] * (iy + dims[1] * iz)] = Math.max(-127, Math.min(127, Math.round(d * 1000)))
  }
  return { dims, lo, vox, order: 'x_fastest', unit: 'mm_int8', data: Buffer.from(q.buffer).toString('base64') }
}
const SDF = sdfPayload()

/** A curved card's rows (the path described in the docstring). */
function curvedRows(theta) {
  const st = Math.sin(theta), ct = Math.cos(theta), rows = []
  for (let i = 0; i < R; i++) {
    const s = 0.02 * i
    if (s <= SPHERE_ARC) {
      const a = ALPHA0 + s / RHO
      rows.push([RHO * Math.sin(a) * st, C[1] + RHO * Math.cos(a), RHO * Math.sin(a) * ct])
    } else rows.push([RHO * st, C[1] - (s - SPHERE_ARC), RHO * ct])
  }
  return rows
}
const straightRows = (x, z, y0 = 1.60, gap = 0.02) => Array.from({ length: R }, (_, i) => [x, y0 - gap * i, z])

/**
 * A record + hair primitive of `cards` ([{rows, pins, side}]): 2 vertices per row ±4 mm along `side`, the cap
 * after them. `followOf(row)` → weights over `bones`.
 */
function build(cards, { bones = ['mixamorig:Head'], followOf = () => [1], capsules = [], params = PARAMS } = {}) {
  const rest = [], pins = [], freeArc = [], freeFrac = [], w = [], pos = [], nrm = [], card = [], u = []
  cards.forEach((cd, k) => {
    pins.push(cd.pins)
    const arc = [0]
    for (let i = 1; i < R; i++) arc.push(arc[i - 1] + Math.hypot(...cd.rows[i].map((v, d) => v - cd.rows[i - 1][d])))
    const last = arc[cd.pins - 1], total = arc[R - 1] - last
    cd.rows.forEach((p, i) => {
      rest.push(...p)
      const fa = i < cd.pins ? 0 : arc[i] - last
      freeArc.push(fa); freeFrac.push(i < cd.pins ? 0 : fa / total)
      w.push(...followOf(p, i))
      const n = [p[0] - C[0], p[1] - C[1], p[2] - C[2]], nl = Math.hypot(...n)
      for (const sgn of [-1, 1]) {
        pos.push(p[0] + sgn * 0.004 * cd.side[0], p[1] + sgn * 0.004 * cd.side[1], p[2] + sgn * 0.004 * cd.side[2])
        nrm.push(n[0] / nl, n[1] / nl, n[2] / nl)
        card.push(k + 1); u.push(i)
      }
    })
  })
  for (const [x, z] of [[-0.02, -0.02], [0.02, -0.02], [0.02, 0.02], [-0.02, 0.02]]) {
    pos.push(x, 1.695, z); nrm.push(0, 1, 0); card.push(0); u.push(0)
  }
  const record = { version: 1, item_id: 'hair_fixture', fsig: '0123456789ab', mode: 'hairdeck', fit_sha256: '0',
    frame: 'head_bind', head_bone: 'mixamorig:Head', rows: R, cards: cards.length, rest, pins,
    free_arc: freeArc, free_frac: freeFrac, follow: { bones, w }, ear_y: EAR, face_box: FACE_BOX, eye_box: EYE_BOX,
    landmarks: 'fallback', sdf: SDF, capsules: { version: 4, capsules, scales: {} }, params,
    vertex_attributes: { card: '_STRAND_CARD', u: '_STRAND_U' } }
  const prim = { pos: Float32Array.from(pos), nrm: Float32Array.from(nrm), card: Uint16Array.from(card),
    u: Float32Array.from(u) }
  return { record, prim }
}

const curvedCard = theta => ({ rows: curvedRows(theta), pins: 3, side: [Math.cos(theta), 0, -Math.sin(theta)] })
const fan = n => Array.from({ length: n }, (_, k) => curvedCard((75 + (k + 0.5) * 210 / n) * Math.PI / 180))

/** The spike's `rootMotion` as a column-major Mat4: world = Rm·(local − pivot) + pivot + off. */
function rootMotion(kind, t, amp, pivot = [0, EAR, 0]) {
  let yaw = 0, pitch = 0, ox = 0, oy = 0, oz = 0
  if (kind === 'sway') {
    yaw = amp * (15 * Math.PI / 180) * Math.sin(2 * Math.PI * 0.5 * t)
    pitch = amp * (5 * Math.PI / 180) * Math.sin(2 * Math.PI * 0.5 * t + Math.PI / 2)
  } else if (kind === 'walk') {
    oz = amp * 0.25 * Math.sin(2 * Math.PI * 0.5 * t)
    oy = amp * 0.015 * (1 - Math.cos(2 * Math.PI * 1.0 * t))
  }
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
  const Rm = [cy, sy * sp, sy * cp, 0, cp, -sp, -sy, cy * sp, cy * cp]   // row-major Ry(yaw)·Rx(pitch)
  const T = [0, 1, 2].map(r => pivot[r] - (Rm[3 * r] * pivot[0] + Rm[3 * r + 1] * pivot[1] + Rm[3 * r + 2] * pivot[2]))
  T[0] += ox; T[1] += oy; T[2] += oz
  return [Rm[0], Rm[3], Rm[6], 0, Rm[1], Rm[4], Rm[7], 0, Rm[2], Rm[5], Rm[8], 0, T[0], T[1], T[2], 1]
}

function makeSim(fx) {
  const b = bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, fx.prim.card, fx.prim.u)
  return new StrandSim(b, fx.record)
}
function frameOf(record, m, capsules = []) {
  const targets = new Float32Array(record.cards * R * 3)
  strandTargets(record, record.follow.bones.map(() => m), targets)
  return { targets, head: m, capsules }
}

const main = build(fan(60))
const prm = strandParams(main.record.params)
check('[0] strandParams maps the record params', prm.rootDeg === 10 && prm.tetherR1 === 0.06 && prm.flyArc === 0.30
  && prm.faceBox === true && prm.iterations === 6)

// [1] rest
{
  const sim = makeSim(main), I = rootMotion('off', 0, 0)
  const f = frameOf(main.record, I)
  sim.reset(f.targets)
  for (let s = 0; s < 120; s++) sim.step(DT, f, prm)
  const pos = new Float32Array(main.prim.pos.length), nrm = new Float32Array(main.prim.nrm.length)
  sim.rebuild(invertAffine(I), pos, nrm)
  let dp = 0, dn = 0
  for (let i = 0; i < pos.length; i++) {
    dp = Math.max(dp, Math.abs(pos[i] - main.prim.pos[i])); dn = Math.max(dn, Math.abs(nrm[i] - main.prim.nrm[i]))
  }
  check('[1] rest: 120 steps, max |rebuilt − rest| == 0 (positions, normals)', dp === 0 && dn === 0,
    `positions ${dp}, normals ${dn}`)
}

// [2] limitSegmentAngle
{
  const out = limitSegmentAngle([0, 0, 0], [0.05, -0.0866025, 0], [0, -1, 0], Math.cos(10 * Math.PI / 180))
  const want = [0.0173648, -0.0984808, 0]
  check('[2] 30° limited to 10°: (0.0173648, −0.0984808, 0)', out.every((v, i) => Math.abs(v - want[i]) < 1e-6),
    out.map(v => v.toFixed(7)).join(', '))
  const five = [0.1 * Math.sin(5 * Math.PI / 180), -0.1 * Math.cos(5 * Math.PI / 180), 0]
  const kept = limitSegmentAngle([0, 0, 0], five, [0, -1, 0], Math.cos(10 * Math.PI / 180))
  check('[2] 5° within the limit: unchanged', kept.every((v, i) => v === five[i]))
}

/** The spike's bench loop: `seconds` of motion then `settle`, calling `each(s, m)` after every step. */
function run(sim, record, kind, seconds, settle, each, p = prm, capsulesOf = () => []) {
  let amp = 0
  sim.reset(frameOf(record, rootMotion(kind, 0, 0)).targets)
  const N = Math.round((seconds + settle) / DT)
  for (let s = 0; s < N; s++) {
    const t = s * DT
    amp += ((t < seconds ? 1 : 0) - amp) * Math.min(1, DT / 0.5)
    const m = rootMotion(kind, t, amp)
    const f = frameOf(record, m, capsulesOf(m))
    sim.step(DT, f, p)
    each(s, m, f)
  }
}

// [3] tether
{
  const sim = makeSim(main)
  let worst = -Infinity, worstHead = -Infinity
  run(sim, main.record, 'sway', 4, 0, (s, m, f) => {
    if (s !== 239) return
    for (let q = 0; q < sim.n; q++) {
      if (sim.pin[q]) continue
      const d = Math.hypot(sim.X[3 * q] - f.targets[3 * q], sim.X[3 * q + 1] - f.targets[3 * q + 1],
        sim.X[3 * q + 2] - f.targets[3 * q + 2])
      if (sim.f[q] <= 1 / 3) worst = Math.max(worst, d - (0.015 + 0.045 * 3 * sim.f[q]))
      const y = sim.binding.C0[3 * q + 1]
      if (y > EAR && sim.sdf0[q] < 0.03) worstHead = Math.max(worstHead, d - 0.012)
    }
  })
  check('[3] after 4 s of sway every free row with f ≤ 1/3 is within r(f) of its target', worst <= 1e-6,
    `max excess ${(worst * 1000).toFixed(4)} mm`)
  check('[3] every row resting on the head within 12 mm', worstHead <= 1e-6, `max excess ${(worstHead * 1000).toFixed(4)} mm`)
}

// [4] sway and walk: SDF depth, eye box
for (const kind of ['sway', 'walk']) {
  const sim = makeSim(main), restEye = restInsideBox(sim, EYE_BOX)
  let deep = 0, eye = 0, tip = 0
  run(sim, main.record, kind, 8, 6, (s, m, f) => {
    if (s % 6) return
    deep = Math.max(deep, maxSdfDepthMm(sim, m, sim.sdf))
    eye = Math.max(eye, eyePointsEntered(sim, m, EYE_BOX, restEye))
    for (let c = 0; c < sim.n; c += R) {
      const q = 3 * (c + R - 1)
      tip = Math.max(tip, Math.hypot(sim.X[q] - f.targets[q], sim.X[q + 1] - f.targets[q + 1], sim.X[q + 2] - f.targets[q + 2]))
    }
  })
  check(`[4] ${kind}: maxSdfDepthMm ≤ 3`, deep <= 3, `${deep.toFixed(2)} mm`)
  check(`[4] ${kind}: eyePointsEntered == 0`, eye === 0, `${eye}`)
  check(`[4] ${kind}: the tips swing (max tip off its target > 5 mm)`, tip > 0.005, `${(tip * 1000).toFixed(1)} mm`)
}

// [5] scalp exposure
{
  const scalp = [], NU = 64, NV = 32
  const sp = (iu, iv) => {
    const th = 2 * Math.PI * iu / NU, ph = Math.PI * iv / NV
    return [C[0] + RAD * Math.sin(ph) * Math.cos(th), C[1] + RAD * Math.cos(ph), C[2] + RAD * Math.sin(ph) * Math.sin(th)]
  }
  for (let iv = 0; iv < NV; iv++) for (let iu = 0; iu < NU; iu++) {
    const a = sp(iu, iv), b = sp(iu + 1, iv), c = sp(iu + 1, iv + 1), d = sp(iu, iv + 1)
    for (const tri of [[a, b, c], [a, c, d]]) {
      if (tri.every(p => p[1] > EAR && p[2] < FACE_BOX[4])) scalp.push(...tri.flat())
    }
  }
  const n = main.prim.pos.length / 3, capBase = n - 4
  for (const t of [[0, 1, 2], [0, 2, 3]]) for (const i of t) scalp.push(...main.prim.pos.slice(3 * (capBase + i), 3 * (capBase + i) + 3))
  const scalpTris = Float32Array.from(scalp)
  const cardTris = pos => {
    const out = new Float32Array(main.record.cards * (R - 1) * 18)
    let o = 0
    for (let k = 0; k < main.record.cards; k++) for (let i = 0; i < R - 1; i++) {
      const v = 2 * (k * R + i), quad = [v, v + 1, v + 3, v, v + 3, v + 2]
      for (const j of quad) { out[o++] = pos[3 * j]; out[o++] = pos[3 * j + 1]; out[o++] = pos[3 * j + 2] }
    }
    return out
  }
  const cams = scalpCameras([0, EAR + 0.04, 0])
  const rest = scalpExposure(cardTris(main.prim.pos), scalpTris, cams)
  check('[5] the cameras see scalp at rest (exposure in (0, 1))', rest.every(e => e > 0 && e < 1),
    rest.map(e => e.toFixed(4)).join(' / '))
  for (const kind of ['sway', 'walk']) {
    const sim = makeSim(main), pos = new Float32Array(main.prim.pos.length), nrm = new Float32Array(pos.length)
    const peak = cams.map(() => 0)
    run(sim, main.record, kind, 8, 0, (s, m) => {
      if (s % 4 || s <= 60) return
      sim.rebuild(invertAffine(m), pos, nrm)
      scalpExposure(cardTris(pos), scalpTris, cams).forEach((e, i) => { peak[i] = Math.max(peak[i], e) })
    })
    const delta = peak.map((p, i) => p - rest[i])
    check(`[5] ${kind}: peak − rest ≤ 0.02 per camera`, delta.every(d => d <= 0.02),
      `rest ${rest.map(e => e.toFixed(4)).join('/')}, peak ${peak.map(e => e.toFixed(4)).join('/')}, `
      + `Δ ${delta.map(d => (d * 100).toFixed(2)).join('/')} pp`)
  }
}

// [6] HAAR: no angle limit
{
  const fx = build([{ rows: straightRows(0.5, 0), pins: 2, side: [1, 0, 0] }])
  const sim = makeSim(fx), I = rootMotion('off', 0, 0), f = frameOf(fx.record, I)
  const turned = () => {
    sim.reset(f.targets)
    const c = Math.cos(Math.PI / 6), s = Math.sin(Math.PI / 6), p1 = [0.5, 1.58, 0]
    for (let i = 2; i < R; i++) {      // rows 2..16 turned 30° about +Z through row 1
      const dx = sim.X[3 * i] - p1[0], dy = sim.X[3 * i + 1] - p1[1]
      sim.X[3 * i] = sim.Xp[3 * i] = p1[0] + c * dx - s * dy
      sim.X[3 * i + 1] = sim.Xp[3 * i + 1] = p1[1] + s * dx + c * dy
    }
    return Float32Array.from(sim.X)
  }
  const before = turned()
  sim.step(0, f, { ...strandParams(fx.record.params), rootDeg: 0, bend: 0, tether: false })
  let moved = 0
  for (let i = 0; i < before.length; i++) moved = Math.max(moved, Math.abs(sim.X[i] - before[i]))
  check('[6] HAAR (root_deg 0): the 30° chain is not limited', moved <= 1e-6, `max move ${moved.toExponential(2)} m`)
  turned()
  sim.step(0, f, { ...strandParams(fx.record.params), bend: 0, tether: false })
  const d = [sim.X[6] - sim.X[3], sim.X[7] - sim.X[4], sim.X[8] - sim.X[5]]
  const ang = Math.acos(-d[1] / Math.hypot(...d)) * 180 / Math.PI
  check('[6] HairDeck (root_deg 10): the same segment turned back to 10°', Math.abs(ang - 10) <= 1e-4, `${ang.toFixed(5)}°`)
}

// [7] follow rows under a pitched spine
{
  const pitch = 30 * Math.PI / 180, c = Math.cos(pitch), s = Math.sin(pitch)
  // T(0, 1.30, 0) · Rx(+30°) · T(0, −1.30, 0), column-major
  const P = [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 1.30 - 1.30 * c, -1.30 * s, 1]
  const followOf = p => (p[1] < 1.52 ? [0, 1] : [1, 0])
  const back = { rows: straightRows(0, -0.10), pins: 2, side: [1, 0, 0] }
  const long = { rows: straightRows(0, -0.095, 1.60, 0.03), pins: 2, side: [1, 0, 0] }
  const torso = { id: 'chest', a: 'mixamorig:Spine2', b: 'mixamorig:Spine2', r: 0.08, region: 'torso',
    a_pos: [0, 1.0, 0], b_pos: [0, 1.45, 0] }
  const fx = build([...fan(60), back, long], { bones: ['mixamorig:Head', 'mixamorig:Spine2'], followOf, capsules: [torso] })
  const T = new Float32Array(fx.record.cards * R * 3)
  strandTargets(fx.record, [P, P], T)
  const q = 3 * (60 * R + 10)
  const want = [0, 1.30 + 0.1 * c + 0.1 * s, 0.1 * s - 0.1 * c]
  check('[7] row 10 of the back card ({Spine2: 1}, bind (0, 1.40, −0.10)) → (0, 1.43660, −0.03660)',
    [0, 1, 2].every(d => Math.abs(T[q + d] - want[d]) < 1e-5), `(${[T[q], T[q + 1], T[q + 2]].map(v => v.toFixed(5)).join(', ')})`)
  const sim = makeSim(fx)
  const xf = (m, p) => [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12], m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
    m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14]]
  const capsuleNow = m => [{ a: xf(m, torso.a_pos), b: xf(m, torso.b_pos), r: 0.08, bind: { a: torso.a_pos, b: torso.b_pos } }]
  const segDist = (p, a, b) => {
    const ab = [0, 1, 2].map(i => b[i] - a[i]), ap = [0, 1, 2].map(i => p[i] - a[i])
    const t = Math.max(0, Math.min(1, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / (ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2)))
    return Math.hypot(ap[0] - ab[0] * t, ap[1] - ab[1] * t, ap[2] - ab[2] * t)
  }
  const I = rootMotion('off', 0, 0), C0 = sim.binding.C0, caps = capsuleNow(P)
  /** 2 s in the pitched pose from the bind pose: the largest depth beyond bind at the end and over the run. */
  const pitched = capsules => {
    sim.reset(frameOf(fx.record, I).targets)
    const f = frameOf(fx.record, P, capsules)
    let worst = -Infinity, worstEnd = -Infinity
    for (let st = 0; st < 120; st++) {
      sim.step(DT, f, prm)
      for (let r = 0; r < sim.n; r++) {
        const now = Math.max(0, 0.08 - segDist([sim.X[3 * r], sim.X[3 * r + 1], sim.X[3 * r + 2]], caps[0].a, caps[0].b))
        const bind = Math.max(0, 0.08 - segDist([C0[3 * r], C0[3 * r + 1], C0[3 * r + 2]], torso.a_pos, torso.b_pos))
        worst = Math.max(worst, now - bind)
        if (st === 119) worstEnd = Math.max(worstEnd, now - bind)
      }
    }
    return [worstEnd, worst]
  }
  const [, freeWorst] = pitched([])
  check('[7] without the capsule the long card passes through the pitched torso (> 10 mm: the case is real)',
    freeWorst > 0.010, `${(freeWorst * 1000).toFixed(1)} mm`)
  const [end, worst] = pitched(caps)
  check('[7] with it, after 2 s no row is inside the torso capsule deeper than at bind (on the way: a chord, 1.57 mm)',
    end <= 1e-6 && worst <= 0.00157,
    `end ${(end * 1000).toFixed(4)} mm, worst over the 2 s ${(worst * 1000).toFixed(4)} mm`)
}

// [8] StrandMismatch
{
  const fx = build([...fan(60), { rows: straightRows(0, -0.10), pins: 2, side: [1, 0, 0] }])
  const card = Uint16Array.from(fx.prim.card); card[0] = 62
  let threw = null
  try { bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, card, fx.prim.u) } catch (e) { threw = e }
  check('[8] _STRAND_CARD 62 for 61 cards → StrandMismatch', threw instanceof StrandMismatch, String(threw?.message))
  threw = null
  try { bindStrands(fx.record, fx.prim.pos, fx.prim.nrm, fx.prim.card, fx.prim.u.subarray(1)) } catch (e) { threw = e }
  check('[8] _STRAND_U one short → StrandMismatch', threw instanceof StrandMismatch, String(threw?.message))
}

// --- Ruling H-R10 ------------------------------------------------------------------------------------------------
const { RootInertia, STRAND_ROOT_LIMITS, STRAND_STRETCH_MAX } = M
const still = { ...prm, iterations: 0, bend: 0, rootDeg: 0, tether: false }
const near = (a, b, tol) => a.every((v, i) => Math.abs(v - b[i]) <= tol)
const rowOf = (sim, q) => [sim.X[3 * q], sim.X[3 * q + 1], sim.X[3 * q + 2]]

// [9] the length clamp
{
  const fx = build([{ rows: straightRows(0.5, 0), pins: 2, side: [0, 0, 1] }])
  const sim = makeSim(fx), I = rootMotion('off', 0, 0), f = frameOf(fx.record, I)
  sim.reset(f.targets)
  sim.X[27] += 0.10; sim.Xp[27] += 0.10
  let arc = 0
  for (let i = 1; i < R; i++) arc += Math.hypot(...[0, 1, 2].map(d => sim.X[3 * i + d] - sim.X[3 * i - 3 + d]))
  check('[9] row 9 held out: the card 1.51× its length (the case is real)', Math.abs(arc / 0.32 - 1.5124) < 1e-3,
    `${(arc / 0.32).toFixed(4)}×`)
  sim.step(0, f, still)
  let worst = 0
  for (let i = 2; i < R; i++) worst = Math.max(worst, Math.hypot(...[0, 1, 2].map(d => sim.X[3 * i + d] - sim.X[3 * i - 3 + d])))
  check('[9] after one step every free segment ≤ 1.05 × 0.02', STRAND_STRETCH_MAX === 1.05 && worst <= 0.021 + 1e-6,
    `${worst.toFixed(7)} m`)
  check('[9] row 9 → (0.5205922, 1.4358816, 0)', near(rowOf(sim, 9), [0.5205922, 1.4358816, 0], 1e-6),
    rowOf(sim, 9).map(v => v.toFixed(7)).join(', '))
}

// [10] the head tether holds the leading run of head-resting rows only
{
  const theta = Math.PI, rows = curvedRows(theta)
  const r3 = rows[3], rr = Math.hypot(r3[0] - C[0], r3[1] - C[1], r3[2] - C[2])
  rows[3] = r3.map((v, d) => C[d] + (v - C[d]) * (rr + 0.04) / rr)
  const fx = build([{ rows, pins: 3, side: [Math.cos(theta), 0, -Math.sin(theta)] }])
  const sim = makeSim(fx), I = rootMotion('off', 0, 0), f = frameOf(fx.record, I)
  const p = { ...still, tether: true, tetherR0: 10, tetherR1: 10 }
  const turn = sign => {
    sim.reset(f.targets)
    const a = sign * 25 * Math.PI / 180, c = Math.cos(a), sn = Math.sin(a), p3 = rowOf(sim, 3)
    for (let i = 4; i < R; i++) {
      const dy = sim.X[3 * i + 1] - p3[1], dz = sim.X[3 * i + 2] - p3[2]
      sim.X[3 * i + 1] = sim.Xp[3 * i + 1] = p3[1] + c * dy - sn * dz
      sim.X[3 * i + 2] = sim.Xp[3 * i + 2] = p3[2] + sn * dy + c * dz
    }
    return Math.hypot(...[0, 1, 2].map(d => sim.X[18 + d] - C[d]))
  }
  const sign = turn(1) > turn(-1) ? 1 : -1
  turn(sign)
  const before = Float32Array.from(sim.X)
  const sdf = M.decodeStrandSdf(fx.record.sdf)
  let clear = Infinity
  for (let i = 4; i < R; i++) clear = Math.min(clear, M.strandSdfAt(sdf, ...rowOf(sim, i)))
  const d6 = Math.hypot(...[0, 1, 2].map(d => sim.X[18 + d] - f.targets[18 + d]))
  check('[10] rows 4..6 rest on the head after the lifted row 3; row 6 turned > 12 mm off its target, all clear',
    sim.onHead[3] >= 0.03 && [4, 5, 6].every(i => sim.onHead[i] > 0 && sim.onHead[i] < 0.03) && d6 > 0.012
    && clear > 0.003, `row 6 ${(d6 * 1000).toFixed(1)} mm, clearance ${(clear * 1000).toFixed(1)} mm`)
  sim.step(0, f, p)
  let moved = 0
  for (let i = 12; i < 3 * R; i++) moved = Math.max(moved, Math.abs(sim.X[i] - before[i]))
  check('[10] after one step rows 4..16 untouched (no head tether after a free row)', moved <= 1e-6,
    `max move ${moved.toExponential(2)} m`)
}

// [11] damping relative to the target: a constant walk drags nothing
{
  const fx = build([{ rows: straightRows(0.5, 0), pins: 2, side: [0, 0, 1] }])
  const sim = makeSim(fx), at = t => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 3.4 * t, 1]
  sim.reset(frameOf(fx.record, at(0)).targets)
  let f
  for (let st = 1; st <= 240; st++) {
    f = frameOf(fx.record, at(st * DT)); sim.step(DT, f, prm)
  }
  let lag = 0
  for (let q = 0; q < R; q++) lag = Math.max(lag, Math.hypot(...[0, 1, 2].map(d => sim.X[3 * q + d] - f.targets[3 * q + d])))
  check('[11] 4 s at 3.4 m/s: every row within 1 mm of its target', lag <= 0.001, `${(lag * 1000).toFixed(3)} mm`)
}

// [12] a capsule never leaves a row inside the head
{
  const fx = build([{ rows: straightRows(0, -0.095), pins: 2, side: [1, 0, 0] }])
  const sim = makeSim(fx), I = rootMotion('off', 0, 0)
  const cap = { a: [0, 1.56, -0.135], b: [0, 1.56, -0.135], r: 0.06, bind: { a: [0, 0, 5], b: [0, 0, 5] } }
  const f = frameOf(fx.record, I, [cap])
  sim.reset(f.targets)
  const sdf = M.decodeStrandSdf(fx.record.sdf)
  sim.step(0, f, { ...still, faceBox: false })
  let worst = Infinity, at = -1
  for (let i = 2; i < R; i++) {
    const m = M.strandSdfAt(sdf, ...rowOf(sim, i)) - Math.min(0.003, M.strandSdfAt(sdf, ...fx.record.rest.slice(3 * i, 3 * i + 3)))
    if (m < worst) { worst = m; at = i }
  }
  check('[12] after one step every free row keeps its clearance (−0.5 mm)', worst >= -0.0005,
    `worst ${(worst * 1000).toFixed(2)} mm at row ${at}, row 2 at z ${sim.X[8].toFixed(4)}`)
}

// [13] RootInertia
{
  const tr = (x, y = 0, z = 0) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]
  const ry = a => [Math.cos(a), 0, -Math.sin(a), 0, 0, 1, 0, 0, Math.sin(a), 0, Math.cos(a), 0, 0, 0, 0, 1]
  const isId = m => m === null || near(m, tr(0), 1e-9)
  check('[13] limits 2.4674 m/s², 2.5839 rad/s²', Math.abs(STRAND_ROOT_LIMITS.accel - 2.4674011) < 1e-6
    && Math.abs(STRAND_ROOT_LIMITS.angAccel - 2.5838563) < 1e-6,
    `${STRAND_ROOT_LIMITS.accel.toFixed(7)}, ${STRAND_ROOT_LIMITS.angAccel.toFixed(7)}`)
  let ri = new RootInertia(), all = true
  for (let st = 0; st < 120; st++) all = isId(ri.update(tr(st * DT), DT)) && all
  check('[13a] 1 m/s from the first frame: every carry the identity', all)
  ri = new RootInertia(); all = true
  for (let st = 0; st < 120; st++) {
    const t = Math.max(0, st * DT - 1)
    all = isId(ri.update(tr(0.5 * t * t), DT)) && all
  }
  check('[13b] at rest, then 1 m/s² for 1 s: every carry the identity', all)
  ri = new RootInertia()
  for (let st = 0; st < 10; st++) ri.update(tr(0), DT)
  const c = ri.update(tr(1), DT)
  check('[13c] a 1 m snap: the carry is a translation by 0.999314610 m',
    c !== null && near(c, tr(0.99931461), 1e-9), c ? c.slice(12, 15).map(v => v.toFixed(9)).join(', ') : 'null')
  ri = new RootInertia()
  for (let st = 0; st < 10; st++) ri.update(tr(0), DT)
  const r = ri.update(ry(Math.PI / 2), DT)
  check('[13d] a 90° yaw snap: the carry is Ry(π/2 − 0.000717738)', r !== null && near(r, ry(Math.PI / 2 - 0.000717738), 1e-9),
    r ? `angle ${Math.atan2(r[8], r[0]).toFixed(9)}` : 'null')
  const fx = build([{ rows: straightRows(0.5, 0), pins: 2, side: [0, 0, 1] }])
  const sim = makeSim(fx)
  sim.reset(frameOf(fx.record, tr(0)).targets)
  for (let q = 0; q < sim.X.length; q++) sim.Xp[q] -= 0.001 * (q % 3 === 2 ? 1 : 0)
  const X0 = Float32Array.from(sim.X), Xp0 = Float32Array.from(sim.Xp), m = ry(Math.PI / 2)
  sim.carry(m)
  const turned = A => (q, d) => m[d] * A[3 * q] + m[4 + d] * A[3 * q + 1] + m[8 + d] * A[3 * q + 2]
  let err = 0
  for (let q = 0; q < sim.n; q++) for (let d = 0; d < 3; d++) {
    err = Math.max(err, Math.abs(sim.X[3 * q + d] - turned(X0)(q, d)), Math.abs(sim.Xp[3 * q + d] - turned(Xp0)(q, d)))
  }
  check('[13e] carry(Ry 90°): rows and previous rows turned with it', err <= 1e-6, `max ${err.toExponential(2)}`)
}

// [T] timing, 700 cards
{
  const big = build(fan(700)), sim = makeSim(big)
  const pos = new Float32Array(big.prim.pos.length), nrm = new Float32Array(pos.length)
  let tStep = 0, tRebuild = 0, steps = 0
  run(sim, big.record, 'sway', 6, 0, (s, m) => {
    const a = performance.now()
    sim.rebuild(invertAffine(m), pos, nrm)
    tRebuild += performance.now() - a
  }, prm)
  // the step alone, timed apart from the targets
  const frames = Array.from({ length: 360 }, (_, s) => frameOf(big.record, rootMotion('sway', s * DT, 1)))
  sim.reset(frames[0].targets)
  const a = performance.now()
  for (const f of frames) { sim.step(DT, f, prm); steps++ }
  tStep = performance.now() - a
  console.log(`[T] 700 cards (${sim.n} rows, ${pos.length / 3} vertices): step ${(tStep / steps).toFixed(3)} ms, `
    + `rebuild ${(tRebuild / 360).toFixed(3)} ms per frame (spike: 4.4–5.9 ms per step)`)
}

console.log(failures ? `FAIL (${failures})` : 'PASS')
process.exit(failures ? 1 : 0)
