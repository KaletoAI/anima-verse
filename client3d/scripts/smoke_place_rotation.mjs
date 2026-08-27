/**
 * Smoke: how BIG a model is must not depend on how it is TURNED.
 *
 * Usage: direct node call, self-bundling via esbuild:
 *     node client3d/scripts/smoke_place_rotation.mjs
 *
 * The package is TypeScript, so the script bundles itself into /tmp on EVERY
 * run and executes that. It used to keep the bundle and re-run it — which
 * measured the source of whenever the cache happened to be built (caught
 * 2026-08-27: an edited place.ts kept reporting the old numbers). esbuild
 * takes ~70 ms; a check that may measure yesterday's code is worth nothing.
 *
 * Runs headless (three needs no DOM for Group/Box3 maths) against the SHARED
 * placeModelSpec — the one routine both renderers use.
 */

// Self-bundling guard — esbuild is required to resolve TypeScript imports
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  // Bundle ourselves and re-run — always, see the header.
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_place_rotation_bundled.mjs'
    // WHERE esbuild actually is: the workspace install puts it in
    // client3d/node_modules, and the root path this used to hard-code does
    // not exist. spawnSync then answers status `null`, `process.exit(null)`
    // is exit 0 — and the run reported "green" without executing a single
    // check (found 2026-08-27). Missing tooling has to be LOUD.
    const root = path.join(__dirname, '../../')
    const bin = ['client3d/node_modules/.bin/esbuild',
                 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const esbuildResult = spawnSync(bin, [
      __filename,
      '--bundle',
      '--platform=node',
      '--format=esm',
      `--outfile=${bundlePath}`
    ], {
      cwd: root,
      stdio: 'inherit'
    })

    if (esbuildResult.status !== 0) {
      process.exit(esbuildResult.status ?? 1)
    }

    const runResult = spawnSync('node', [bundlePath], {
      stdio: 'inherit',
      env: { ...process.env, SMOKE_BUNDLED: '1' }
    })

    process.exit(runResult.status ?? 1)
  }

  // Bundled version: dynamically import with resolved TypeScript
  const THREE = await import('three')
  const { placeModelSpec } = await import('../../packages/scene-render/src/place.ts')

/**
 * The rule (contract v5.1 Nr. 4, extended 2026-07-28): the orientation fix is
 * rounded to 90° FOR THE MEASUREMENT. The axis-aligned hull of a tilted box is
 * bigger than the box, so a fine-angle fix used to inflate the measured extent
 * and the model came out smaller — first noticed on room models (fix 0/110/357
 * blew a 1.000 side up to 1.306 and shrank the model by 23 %), then on
 * location models, which measure `yawed_xz` and were still measuring the
 * UNSNAPPED fix inside the yawed hull.
 *
 * WHAT IS MEASURED HERE: the uniform scale factor place() applies — that IS
 * "how big the model was made". NOT the axis-aligned bounding box of the
 * result: a tilted 4 m cube has a hull of up to 4*sqrt(3), and that is
 * correct, not a defect. Conflating the two is what made the bug hard to see.
 *
 * Expected, worked out by hand for a 1 x 1 x 1 box and max_m = 4:
 *
 *   xyz / xz / yawed_xz at yaw 0:  the snapped fix leaves a unit cube a unit
 *                                  cube, so the factor is 4 / 1 = 4 for EVERY
 *                                  fix, fine angles included.
 *   yawed_xz at yaw 45:            the turned hull IS the target (a house set
 *                                  at an angle must still fit its plot), so
 *                                  the factor is 4 / sqrt(2) = 2.8284 and the
 *                                  hull comes out at 4.
 *
 * Sections 1-5 are SIGN-BLIND: a unit cube and a 45° hull measure the same
 * whichever way they were turned, so the E4 yaw flip (`-rad` -> `+rad`,
 * § A1.1) left every one of their hand-derived numbers untouched. That is a
 * finding, not an omission — it is exactly why section 6 exists.
 *
 * SECTION 6 — the turning SENSE (§ A1.1, added with E4). The contract's
 * mapping is the server's `world_geometry.local_to_world`:
 *
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * and three.js' `rotation.y = +rad(yaw)` is that same matrix, which is why the
 * renderers now turn PLUS. Hand-derived, the docstring case of
 * `frontend/src/tabs/map/mapMath.ts`: a location at (10, 20), 10 m wide, at
 * yaw 90, whose local corner (+5, +5) has to land on world (15, 15).
 *
 *   Source: a 10 x 1 x 10 slab centred on the local origin (so the footprint
 *   is the [-5, 5] square in both axes) plus a 1 x 1 x 1 MARKER centred on
 *   local (4.5, 0, 4.5) — the marker sits fully inside the slab's box, so the
 *   measured extent stays 10 and `max_m = 10` gives scale exactly 1.
 *   At yaw 90 (cos 0, sin 1) the marker's centre (lx = lz = 4.5) maps to
 *       x = 10 + 4.5·0 + 4.5·1   = 14.5
 *       z = 20 − 4.5·1 + 4.5·0   = 15.5
 *   A cube turned by 90° is still axis-aligned, so its box is x [14, 15],
 *   z [15, 16] — and its corner (max.x, min.z) = (15, 15) IS the contract's
 *   answer for the local corner (+5, +5).
 *   With the old minus the same centre would land on
 *       x = 10 + 4.5·0 + 4.5·(−1) = 5.5,  z = 20 + 4.5·1 + 0 = 24.5
 *   — mirrored through the centre, which is what this check exists to catch.
 */
  const FAILED = []

  function check(label, got, want, tol = 1e-3) {
    const ok = Math.abs(got - want) <= tol
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${got.toFixed(4)}`
      + (ok ? '' : `  (expected ${want})`))
    if (!ok) FAILED.push(label)
  }

  function unitBox() {
    return new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
                          new THREE.MeshBasicMaterial())
  }

  function place(fix, yaw, measure, maxM = 4) {
    const spec = {
      role: 'building', id: 'x', url: '', level: 0,
      fix_euler: fix, yaw_deg: yaw, max_m: maxM, measure,
      anchor: [0, 0], bottom_y: 0,
    }
    const g = placeModelSpec(THREE, unitBox(), spec)
    g.updateMatrixWorld(true)
    return {
      scale: g.scale.x,
      hull: new THREE.Box3().setFromObject(g).getSize(new THREE.Vector3()),
    }
  }

  const FIXES = [
    ['none', { x: 0, y: 0, z: 0 }],
    ['90 deg', { x: 0, y: 90, z: 0 }],
    ['fine 0/110/357', { x: 0, y: 110, z: 357 }],
    ['fine 5/110/355', { x: 5, y: 110, z: 355 }],
  ]

  console.log('1. measure "xyz" (props) — the factor ignores the fix')
  for (const [label, fix] of FIXES) {
    check(`fix ${label}`, place(fix, 0, 'xyz').scale, 4)
  }

  console.log('\n2. measure "xz" (room dioramas)')
  for (const [label, fix] of FIXES) {
    check(`fix ${label}`, place(fix, 0, 'xz').scale, 4)
  }

  console.log('\n3. measure "yawed_xz" (location models), yaw 0')
  for (const [label, fix] of FIXES) {
    check(`fix ${label}`, place(fix, 0, 'yawed_xz').scale, 4)
  }

  console.log('\n4. "yawed_xz" with a 45 deg YAW — the TURNED hull is the target')
  {
    const r = place({ x: 0, y: 0, z: 0 }, 45, 'yawed_xz')
    check('factor', r.scale, 4 / Math.SQRT2)
    check('the turned hull fills the frame', Math.max(r.hull.x, r.hull.z), 4)
  }

  console.log('\n5. a fine fix must not change the factor at any yaw')
  for (const yaw of [0, 30, 90, 217]) {
    const a = place({ x: 0, y: 0, z: 0 }, yaw, 'yawed_xz').scale
    const b = place({ x: 5, y: 110, z: 355 }, yaw, 'yawed_xz').scale
    check(`yaw ${yaw}`, b, a)
  }

  console.log('\n6. the turning SENSE (§ A1.1): yaw 90 puts local +x on world -z')
  {
    const slab = new THREE.Mesh(new THREE.BoxGeometry(10, 1, 10),
                                new THREE.MeshBasicMaterial())
    const marker = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
                                  new THREE.MeshBasicMaterial())
    marker.position.set(4.5, 0, 4.5)
    marker.name = 'marker'
    const source = new THREE.Group()
    source.add(slab, marker)

    const g = placeModelSpec(THREE, source, {
      role: 'building', id: 'x', url: '', level: 0,
      fix_euler: { x: 0, y: 0, z: 0 }, yaw_deg: 90, max_m: 10, measure: 'xz',
      anchor: [10, 20], bottom_y: 0,
    })
    g.updateMatrixWorld(true)
    check('scale (the marker hides inside the slab)', g.scale.x, 1)

    let placedMarker = null
    g.traverse((o) => { if (o.name === 'marker') placedMarker = o })
    const box = new THREE.Box3().setFromObject(placedMarker)
    check('marker centre x', (box.min.x + box.max.x) / 2, 14.5)
    check('marker centre z', (box.min.z + box.max.z) / 2, 15.5)
    check('local corner (+5,+5) -> world x', box.max.x, 15)
    check('local corner (+5,+5) -> world z', box.min.z, 15)
  }

  console.log('\n7. measure "fit" (door props, v5) — the OPENING is the ruler')
  /**
   * The one non-uniform mode, and the one that does not hang on its centre.
   * Hand-derived for a 0.5 x 2 x 0.1 box (w x h x d) fitted onto an opening
   * of size_m [1.0, 2.1]:
   *
   *   sx = 1.0 / 0.5 = 2.0      x is the width
   *   sy = 2.1 / 2   = 1.05     y is the height
   *   sz = sx = 2.0             the depth keeps its proportion to the width
   *                             → 0.1 * 2.0 = 0.2 m thick
   *
   * The anchor is the HINGE EDGE: place() puts the model's local −x edge and
   * its underside into the group origin, so at yaw 0, anchor (3, 7),
   * bottom_y 0.5 the placed box runs
   *
   *   x 3.0 … 4.0,   y 0.5 … 2.6,   z 6.9 … 7.1   (z stays centred)
   *
   * and at yaw 270 — which is what the server sends for an opening along
   * (0, 1), because Ry(+θ) puts local +x on (cos θ, −sin θ) — the width runs
   * along +z instead: x 2.9 … 3.1, z 7.0 … 8.0. A leaf that stuck out on the
   * wrong side of its hinge, or one scaled uniformly, fails both rows.
   */
  {
    const leaf = () => new THREE.Mesh(new THREE.BoxGeometry(0.5, 2, 0.1),
                                      new THREE.MeshBasicMaterial())
    const fitSpec = (yaw) => ({
      role: 'prop', id: 'door', url: '', level: 0,
      fix_euler: { x: 0, y: 0, z: 0 }, yaw_deg: yaw, measure: 'fit',
      size_m: [1.0, 2.1], anchor: [3, 7], bottom_y: 0.5,
      door: { opening: 0, hinge: 'left', swing: 1 },
    })
    const g0 = placeModelSpec(THREE, leaf(), fitSpec(0))
    g0.updateMatrixWorld(true)
    const b0 = new THREE.Box3().setFromObject(g0)
    check('width  scaled to size_m[0]', b0.max.x - b0.min.x, 1.0)
    check('height scaled to size_m[1]', b0.max.y - b0.min.y, 2.1)
    check('depth  scaled with the WIDTH factor (0.1 x 2)',
      b0.max.z - b0.min.z, 0.2)
    check('the hinge edge sits ON the anchor (x)', b0.min.x, 3.0)
    check('...and the leaf runs from it along local +x', b0.max.x, 4.0)
    check('bottom_y is the underside', b0.min.y, 0.5)
    check('z stays centred on the anchor', (b0.min.z + b0.max.z) / 2, 7.0)
    const g270 = placeModelSpec(THREE, leaf(), fitSpec(270))
    g270.updateMatrixWorld(true)
    const b270 = new THREE.Box3().setFromObject(g270)
    check('yaw 270: the width runs +z from the anchor', b270.min.z, 7.0)
    check('...to 8.0', b270.max.z, 8.0)
    check('...and the depth is what straddles x', b270.max.x - b270.min.x, 0.2)
    check('...still 2.1 tall', b270.max.y - b270.min.y, 2.1)
  }

  console.log()
  if (FAILED.length) {
    console.log(`FAILED (${FAILED.length}): ${FAILED.join(', ')}`)
    process.exit(1)
  }
  console.log('all checks passed')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
