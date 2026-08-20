/**
 * Smoke: the AUTHORED props of the world plane (§ A9a) on the client side.
 *
 * Usage: direct node call, self-bundling via esbuild:
 *     node client3d/scripts/smoke_world_props.mjs
 *
 * Three questions, all of them arithmetic, all expectations derived BY HAND
 * from the contract below (§ B5a — never recorded from a run):
 *
 * ── 1. The LOD distances ──────────────────────────────────────────────────
 * A world prop is a LANDMARK, not one of a thousand tufts, so it keeps its
 * meshes `WORLD_PROP_LOD_SCALE` = 3 times as far as the scatter. The scatter
 * defaults are 35 / 45 / 120 m (`scene/scatterLod.ts`), hence
 *
 *     near = 3·35  = 105 m
 *     far  = 3·45  = 135 m
 *     cull = 3·120 = 360 m
 *
 * and `instanceTier` (the SAME hysteresis function the scatter uses) then has
 * to answer, for a prop last drawn as full (tier 0):
 *
 *     100 m  <  105  -> 0 (full)
 *     120 m  in the 105…135 band, exclusive at both ends -> keeps 0
 *     140 m  >  135  -> 1 (low)
 *     400 m  >  360  -> 2 (not drawn)
 *
 * and coming back from hidden (tier 2), the un-hide edge is
 * `SCATTER_UNHIDE_FACTOR` = 0.92 of the cull distance = 0.92·360 = 331.2 m:
 *
 *     340 m  >  331.2 -> stays 2
 *     300 m  <  331.2 -> re-enters, and 300 > 135, so tier 1
 *
 * ── 2. The placement spec ─────────────────────────────────────────────────
 * `worldPropSceneSpec` turns ONE payload row plus a ground height into the
 * § B2 spec `place()` reads. The row states `x`/`z`/`offset_y`; the BOTTOM is
 * the caller's — the server never sends one. `worldPropBottom` is that sum,
 * and it has three summands with three owners (§ A9a, ground offset
 * 2026-08-20): the relief, THIS placement's `offset_y`, and the PROP's own
 * `ground_offset_m`. On a ground of 2.5 m with `offset_y` 0.5:
 *
 *     no ground_offset_m        -> 3.00
 *     ground_offset_m = -0.20   -> 2.80   (a trunk without a root ball)
 *     +0.35 and no placement trim -> 2.85
 *
 * An absent key is 0 — the server ships it only when it differs.
 *
 * ── 3. The mount itself, measured ─────────────────────────────────────────
 * `placeModelSpec` is the shared routine; here it is fed a hand-built box so
 * the resulting world bounding box can be predicted exactly.
 *
 *   Source A: a 1 x 1 x 1 box centred on the origin, `max_m` = 3, `xyz`.
 *     measured extent = max(1,1,1) = 1  ->  scale = 3/1 = 3
 *     scaled box: 3 x 3 x 3, still centred on the origin
 *     anchor = [10, -4], ground 2.5 m, offset_y 0.5  ->  bottom_y = 3.0
 *     position.y = bottom_y - box.min.y = 3.0 - (-1.5) = 4.5
 *     world box: x 8.5…11.5,  y 3.0…6.0,  z -5.5…-2.5
 *
 *   Source B: a 2 x 1 x 1 box, `max_m` = 3, yaw 90°.
 *     measured extent = max(2,1,1) = 2  ->  scale = 3/2 = 1.5
 *     scaled box: 3 x 1.5 x 1.5 (long along local x)
 *     three.js Ry(+90°) maps  x = lz,  z = -lx  (§ A1.1, place.ts)
 *       -> the 3 m length lands on the Z axis, the 1.5 m on X
 *     world box size: x 1.5,  y 1.5,  z 3.0
 *
 *   Yaw is measured AFTER the fix but the scale is measured BEFORE it, which
 *   is exactly why a turned prop must not change size — checked as the last
 *   assertion.
 */

import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_world_props_bundled.mjs'
    const needsBundle = !fs.existsSync(bundlePath) || process.env.REBUNDLE
    if (needsBundle) {
      const esbuildResult = spawnSync('node_modules/.bin/esbuild', [
        __filename,
        '--bundle',
        '--platform=node',
        '--format=esm',
        `--outfile=${bundlePath}`,
      ], { cwd: path.join(__dirname, '../../'), stdio: 'inherit' })
      if (esbuildResult.status !== 0) process.exit(esbuildResult.status)
    }
    const runResult = spawnSync('node', [bundlePath], {
      stdio: 'inherit',
      env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(runResult.status)
  }

  const THREE = await import('three')
  const { placeModelSpec, pickModelVariant } =
    await import('../../packages/scene-render/src/index.ts')
  const { instanceTier, SCATTER_LOD_DEFAULTS } =
    await import('../src/scene/scatterLod.ts')
  const { WORLD_PROP_LOD_SCALE, worldPropLodCfg, worldPropSceneSpec,
    worldPropBottom } = await import('../src/scene/worldProps.ts')

  const FAILED = []
  const r3 = (v) => Math.round(v * 1000) / 1000
  function check(label, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want)
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${JSON.stringify(got)}`
      + (ok ? '' : `  (expected ${JSON.stringify(want)})`))
    if (!ok) FAILED.push(label)
  }

  console.log('\n[1] the LOD distances')
  check('scale factor', WORLD_PROP_LOD_SCALE, 3)
  const cfg = worldPropLodCfg(SCATTER_LOD_DEFAULTS)
  check('scaled bands', [cfg.nearM, cfg.farM, cfg.cullM], [105, 135, 360])
  check('100 m stays full', instanceTier(100, 0, cfg), 0)
  check('120 m keeps what it has (full)', instanceTier(120, 0, cfg), 0)
  check('120 m keeps what it has (low)', instanceTier(120, 1, cfg), 1)
  check('140 m drops to low', instanceTier(140, 0, cfg), 1)
  check('400 m is not drawn', instanceTier(400, 0, cfg), 2)
  check('340 m stays hidden', instanceTier(340, 2, cfg), 2)
  check('300 m comes back as low', instanceTier(300, 2, cfg), 1)

  console.log('\n[2] the placement spec')
  const PID = 'boulder-abc123'
  const P = `/assets/props/${PID}/model`
  const row = {
    id: 'wp_1a2b3c4d', prop_id: PID,
    x: 10, z: -4, yaw_deg: 0, offset_y: 0.5, max_m: 3,
    fix_euler: { x: 0, y: 0, z: 0 },
    variants: { full: `${P}?tier=full` },
  }
  const spec = worldPropSceneSpec(row, 3.0)
  check('role', spec.role, 'prop')
  check('one scale law', [spec.measure, spec.max_m], ['xyz', 3])
  check('anchor is the world point', spec.anchor, [10, -4])
  check('bottom is the callers', spec.bottom_y, 3.0)
  check('no variant list for one variant',
    'model_variants' in spec, false)

  // A row of a prop with TWO variants: the index is the SERVER's, and the
  // shared resolver reads it — the client never picks a mesh itself.
  const two = {
    ...row, id: 'wp_deadbeef', variant: 1,
    model_variants: [
      { full: `${P}?tier=full`, low: `${P}?tier=low` },
      { full: `${P}?variant=1&tier=full` },
    ],
  }
  const spec2 = worldPropSceneSpec(two, 0)
  check('variant travels', spec2.variant, 1)
  check('full of variant 1', pickModelVariant(spec2, 'full'),
    `${P}?variant=1&tier=full`)
  // Variant 1 has no low mesh: the tier falls back INSIDE the chosen variant,
  // never into another variant's low mesh (that would draw a different object).
  check('low falls back inside the variant', pickModelVariant(spec2, 'low'),
    `${P}?variant=1&tier=full`)

  console.log('\n[2a] the bottom — three summands, three owners')
  // `worldPropBottom(row, groundY)` is what BOTH seat sites call (mount and
  // the relief re-drape), so the arithmetic is checked once and cannot drift
  // between them. Hand-derived on the ground height 2.5 m:
  //   offset_y 0.5, no ground_offset_m         -> 3.0
  //   the same row with ground_offset_m -0.2   -> 2.8
  //   a lift of +0.35 and no placement trim    -> 2.85
  check('ground + the placement trim', worldPropBottom(row, 2.5), 3.0)
  check('…plus the prop\'s own sink of -0.2',
    r3(worldPropBottom({ ...row, ground_offset_m: -0.2 }, 2.5)), 2.8)
  check('a lift with no trim', r3(worldPropBottom(
    { ...row, offset_y: 0, ground_offset_m: 0.35 }, 2.5)), 2.85)
  check('an absent key is 0, not NaN',
    worldPropBottom({ ...row, ground_offset_m: undefined }, 2.5), 3.0)
  check('and so is junk on the wire',
    worldPropBottom({ ...row, ground_offset_m: 'x' }, 2.5), 3.0)
  // The RED probe: the sum before the field existed. A fir dialled 20 cm into
  // the soil would stand on the grass out here while it is correctly buried
  // in every room — the very split the field exists to close.
  const blindBottom = (wp, groundY) => groundY + (wp.offset_y || 0)
  check('the offset-blind sum answers 3.0 for the sunk row',
    blindBottom({ ...row, ground_offset_m: -0.2 }, 2.5), 3.0)
  check('…which is NOT what the real sum answers',
    r3(worldPropBottom({ ...row, ground_offset_m: -0.2 }, 2.5)) !== 3.0, true)
  // …and it reaches `place()`: the spec's bottom_y IS this sum.
  check('the spec carries it', worldPropSceneSpec(
    { ...row, ground_offset_m: -0.2 },
    worldPropBottom({ ...row, ground_offset_m: -0.2 }, 2.5)).bottom_y, 2.8)

  console.log('\n[3] the mount, measured')
  const boxOf = (w, h, d) => new THREE.Mesh(
    new THREE.BoxGeometry(w, h, d), new THREE.MeshBasicMaterial())

  const outA = placeModelSpec(THREE, boxOf(1, 1, 1),
    worldPropSceneSpec(row, 2.5 + 0.5), { clone: false, clip: false })
  outA.updateMatrixWorld(true)
  const bA = new THREE.Box3().setFromObject(outA)
  check('A: min corner', [r3(bA.min.x), r3(bA.min.y), r3(bA.min.z)],
    [8.5, 3, -5.5])
  check('A: max corner', [r3(bA.max.x), r3(bA.max.y), r3(bA.max.z)],
    [11.5, 6, -2.5])

  const turned = { ...row, yaw_deg: 90 }
  const outB = placeModelSpec(THREE, boxOf(2, 1, 1),
    worldPropSceneSpec(turned, 0), { clone: false, clip: false })
  outB.updateMatrixWorld(true)
  const sB = new THREE.Box3().setFromObject(outB).getSize(new THREE.Vector3())
  check('B: the length lands on Z', [r3(sB.x), r3(sB.y), r3(sB.z)],
    [1.5, 1.5, 3])

  const straight = placeModelSpec(THREE, boxOf(2, 1, 1),
    worldPropSceneSpec({ ...row, yaw_deg: 0 }, 0), { clone: false, clip: false })
  straight.updateMatrixWorld(true)
  const sS = new THREE.Box3().setFromObject(straight).getSize(new THREE.Vector3())
  check('turning does not resize', [r3(sS.x) + r3(sS.z), r3(sS.y)],
    [r3(sB.x) + r3(sB.z), r3(sB.y)])

  console.log(FAILED.length
    ? `\nFAILED (${FAILED.length}): ${FAILED.join(', ')}`
    : '\nsmoke_world_props: OK')
  process.exit(FAILED.length ? 1 : 0)
}

void main()
