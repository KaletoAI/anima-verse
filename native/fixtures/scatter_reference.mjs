#!/usr/bin/env node
/**
 * Reference values for the native client's scatter + undergrowth (Task S3), computed by the
 * BROWSER'S OWN FUNCTIONS:
 *
 *   packages/scene-render/src/scatter.ts     scatterInstances, scatterCellInstances, seeds, PRNG
 *   packages/scene-render/src/occupancy.ts   OccupancyGrid, cellOccupancy
 *   client3d/src/scene/scatterLod.ts         instanceTier / instanceVisible / inViewCone / viewCone,
 *                                            the undergrowth density/visibility helpers
 *   client3d/src/scene/undergrowth.ts        wantedUndergrowthCells, undergrowthCellSeed,
 *                                            undergrowthTexturePixels, undergrowthShade
 *
 * Output: native/fixtures/scatter_reference.json with
 *   cases       hand-chosen sampler inputs (plain ring; footprint hole + clearance; occluder above;
 *               spacing; a maxPoints prefix; a cell with variants/pin/aligned/occupancy) and every
 *               instance the TS sampler returns for them;
 *   fixture     the --check world (native/fixtures/terrain.json + worldmap.json, anchor of
 *               --goto=harbour): the authored spread rows of every painted area in the camera window,
 *               sampled exactly as client3d/src/scene/ground.ts `buildScatter` orchestrates the shared
 *               sampler (window cells, one OccupancyGrid per cell shared by every area of the pass,
 *               occupyR = clearM, occupyTag = the cell-independent row seed), once with the ESTIMATED
 *               clearance (no mesh landed yet) and once with the MEASURED one (the prop GLB's own
 *               bbox, both tiers, widest wins — `spreadOf`); plus the per-entry LOD bins of `binProp`
 *               at a fixed camera, and the undergrowth cells/instances/bins of `createUndergrowthField`;
 *   e4          rows from e4_terrain.json at epochs 2 and 3 (14465/21665 game seconds),
 *               plus near/far/culled world props from worldmap.json. Kept separate from
 *               fixture.estimate/measured until the row port lands: current ScatterCheck
 *               explicitly rejects non-spread rows in its baseline terrain.
 *   texture     sha256 of the procedural blade texture; a few shade/hash values.
 *
 * The orchestration lines below mirror ground.ts / undergrowth.ts; every number comes out of the
 * imported TS functions. `Check/ScatterCheck.cs` demands its C# port to land within 1e-6 m.
 *
 * Usage (from the repository root, needs `npm install` for three + esbuild):
 *   node native/fixtures/scatter_reference.mjs
 * Bundles itself with esbuild like rest_reference.mjs. Read-only on every input.
 */
import { spawnSync } from 'child_process'
import * as crypto from 'crypto'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT = path.join(__dirname, '../../')

/** The fixture camera of the LOD bins: near the wood, looking east-north-east. */
const CAMERA = { pos: [40, 30, 110], fwd: [1, 0, 0.5], vfov_deg: 45, aspect: 16 / 9 }
/** The prop GLBs of the fixture (tracked demo-world files, read in place). */
const PROP_FILES = {
  '/assets/props/broadleaf/model.glb?tier=full': 'worlds/demo/props/broadleaf-df5830/model_1792265756.glb',
  '/assets/props/broadleaf/model.glb?tier=low': 'worlds/demo/props/broadleaf-df5830/model_1792265757.glb',
}
const TUFT_HEIGHT_M = 0.8   // ground.ts TUFT_HEIGHT_M
const SWAY_MAX_M = 0.5      // ground.ts SWAY_MAX_M

async function main() {
  if (!process.env.SCATTER_REFERENCE_BUNDLED) {
    const bundlePath = '/tmp/anima_native_scatter_reference_bundled.mjs'
    const { build } = await import('esbuild')
    await build({ entryPoints: [__filename], bundle: true, platform: 'node', format: 'esm',
      outfile: bundlePath, logLevel: 'warning', external: ['esbuild'] })
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', cwd: ROOT,
      env: { ...process.env, SCATTER_REFERENCE_BUNDLED: '1', SCATTER_REFERENCE_ROOT: ROOT },
    })
    process.exit(run.status ?? 1)
  }

  const root = process.env.SCATTER_REFERENCE_ROOT
  const S = await import('../../packages/scene-render/src/scatter.ts')
  const { OccupancyGrid, cellOccupancy } = await import('../../packages/scene-render/src/occupancy.ts')
  const { cleanRing, polygonArea, buildAreaGeometry } = await import('../../packages/scene-render/src/groundAreas.ts')
  const { pickVariant } = await import('../../packages/scene-render/src/types.ts')
  const A = await import('../../packages/scene-render/src/scatterAxis.ts')
  const T = await import('../../packages/scene-render/src/stroke.ts')
  const W = await import('../../client3d/src/scene/worldProps.ts')
  const L = await import('../../client3d/src/scene/scatterLod.ts')
  const U = await import('../../client3d/src/scene/undergrowth.ts')
  const THREE = await import('three')

  const pts = (list) => list.map((p) => [p.x, p.z, p.yaw, p.variant ?? null])

  // ---- 1. the hand-chosen sampler cases ------------------------------------------------------
  const rect = [[0, 0], [50, 0], [50, 40], [0, 40]]
  const lShape = [[0, 0], [60, 0], [60, 20], [25, 20], [25, 50], [0, 50]]
  const hole = [[20, 15], [30, 15], [30, 25], [20, 25]]
  const box = { x: 40, z: 30, yaw_deg: 30, half_w: 4, half_d: 2 }
  const occluder = [[35, -5], [55, -5], [55, 45]]
  const caseInputs = [
    { name: 'plain-ring', ring: lShape, areaM2: polygonArea(lShape), density: 5, seed: S.scatterSeed('case-a', 0) },
    { name: 'footprint-hole-clearance', ring: rect, areaM2: polygonArea(rect), density: 6, seed: S.scatterSeed('case-b', 0),
      footprints: [hole], prop_boxes: [box], clearM: 1.5 },
    { name: 'occluder-above', ring: rect, areaM2: polygonArea(rect), density: 6, seed: S.scatterSeed('case-c', 1),
      occluders: [occluder] },
    { name: 'spacing', ring: rect, areaM2: polygonArea(rect), density: 30, seed: S.scatterSeed('case-d', 0),
      minSpacingM: 2.5 },
    { name: 'maxpoints-prefix', ring: rect, areaM2: polygonArea(rect), density: 30, seed: S.scatterSeed('case-d', 0),
      minSpacingM: 2.5, maxPoints: 25, prefix_of: 'spacing' },
  ]
  const cases = []
  for (const c of caseInputs) {
    const footprints = (c.footprints ?? []).map((points) => ({ points }))
      .concat(S.propBoxFootprints(c.prop_boxes ?? []))
    const out = S.scatterInstances({
      ring: c.ring, areaM2: c.areaM2, densityPer100m2: c.density, seed: c.seed, footprints,
      clearM: c.clearM, occluders: c.occluders, minSpacingM: c.minSpacingM, maxPoints: c.maxPoints,
    })
    cases.push({ kind: 'instances', ...c, wanted: S.scatterWantedCount(c.areaM2, c.density, c.maxPoints),
                 points: pts(out) })
  }
  // A cell: half of it painted, three variants with the formula, the same with a pin, an aligned
  // turn (no axis → the angle alone), an epoch seed, and a foreign row already in the occupancy.
  {
    const ring = [[70, 10], [140, 10], [140, 50], [70, 50]]   // reaches into cell (1, 0) and beyond
    const epoch = S.reshuffleEpoch(7265, 30)                 // floor(7265 / 1800) = 4
    const seed = S.scatterCellSeed('case-f', 2, 1, 0, epoch)
    // The third entry carries the row's OWN tag: it must not block (the row is excused from itself), and
    // occupyR 2 > the spacing 1.5 makes the own-tag exemption visible between the row's own survivors too.
    const prefill = [[80, 20, 3, 'other-row'], [100, 30, 2, 'other-row'], [110, 30, 6, S.scatterSeed('case-f', 2)]]
    for (const [name, variant, yawMode, yawDeg] of [['cell-variants-occupancy', undefined, undefined, undefined],
                                                    ['cell-pinned-aligned', 1, 'aligned', 90]]) {
      const grids = new Map()
      const { gridOf } = cellOccupancy(grids)
      for (const [x, z, r, tag] of prefill) gridOf(1, 0).add(x, z, r, tag)
      const out = S.scatterCellInstances({
        ring, cx: 1, cz: 0, densityPer100m2: 4, seed, minSpacingM: 1.5, variantCount: 3, variant,
        yawMode, yawDeg, occupied: gridOf(1, 0), occupyR: 2, occupyTag: S.scatterSeed('case-f', 2),
      })
      cases.push({ kind: 'cell', name, ring, cx: 1, cz: 0, density: 4, seed, epoch_total_s: 7265, reshuffle_min: 30,
                   area_id: 'case-f', index: 2, minSpacingM: 1.5, variantCount: 3, variant: variant ?? null,
                   yawMode: yawMode ?? null, yawDeg: yawDeg ?? null, occupyR: 2,
                   occupyTag: S.scatterSeed('case-f', 2), prefill, points: pts(out) })
    }
  }

  // ---- 2. the --check world --------------------------------------------------------------------
  const fixtures = path.join(root, 'native/fixtures')
  const terrain = JSON.parse(fs.readFileSync(path.join(fixtures, 'terrain.json'), 'utf8'))
  const e4Terrain = JSON.parse(fs.readFileSync(path.join(fixtures, 'e4_terrain.json'), 'utf8'))
  const worldmap = JSON.parse(fs.readFileSync(path.join(fixtures, 'worldmap.json'), 'utf8'))
  const anchor = { x: 64, z: 128 }    // --goto=harbour → loc-house (fixtures/README.md "Anchor")
  // Fixture height: tile (0, 0) of tiles.json is h = 2·i + j at 64 m steps, i.e. x/32 + z/64 on
  // [0, 256)², and every instance of the fixture stands on it (the wood is 8..200 × 72..200).
  const heightAt = (x, z) => x / 32 + z / 64

  // worldFootprints (ground.ts): boundary → world through § A1.1, plus propBoxFootprints.
  const footprints = []
  for (const loc of worldmap.locations) {
    const b = loc.boundary ?? loc.map3d?.boundary
    if (!Array.isArray(b) || b.length < 3) continue
    if (typeof loc.pos_x !== 'number' || typeof loc.pos_z !== 'number') continue
    const yaw = ((Number.isFinite(loc.yaw_deg) ? loc.yaw_deg : 0) * Math.PI) / 180
    const c = Math.cos(yaw), s = Math.sin(yaw)
    footprints.push({ points: b.map(([lx, lz]) => [loc.pos_x + lx * c + lz * s, loc.pos_z - lx * s + lz * c]) })
  }
  footprints.push(...S.propBoxFootprints(terrain.prop_boxes))

  // The measured spread of the prop (ground.ts noteSpread/spreadOf) from the GLBs' POSITION bounds.
  const spreadOfFile = (rel) => {
    const b = fs.readFileSync(path.join(root, rel))
    const n = b.readUInt32LE(12)
    const j = JSON.parse(b.subarray(20, 20 + n).toString('utf8'))
    let best = 0
    for (const m of j.meshes.slice(0, 1)) for (const p of m.primitives.slice(0, 1)) {
      const a = j.accessors[p.attributes.POSITION]
      const w = Math.max(a.max[0] - a.min[0], a.max[2] - a.min[2])
      best = w / (a.max[1] - a.min[1])
    }
    return best
  }
  const measured = {}
  for (const [url, rel] of Object.entries(PROP_FILES)) measured[url] = spreadOfFile(rel)

  const cfg = L.SCATTER_LOD_DEFAULTS
  const cells = S.wantedScatterCells(anchor.x, anchor.z, cfg.cullM)
  const cone = L.viewCone(CAMERA.fwd[0], CAMERA.fwd[2], L.horizontalFovRad(CAMERA.vfov_deg, CAMERA.aspect))
  const cam = { x: CAMERA.pos[0], y: CAMERA.pos[1], z: CAMERA.pos[2] }

  /** ground.ts binProp from fresh tiers (1) and empty slots, the full mesh present (`hiBuf`). */
  const binProp = (pos, h, hasHigh, loUrl) => {
    const n = pos.length / 3
    const sphere = new THREE.Box3()
    for (let i = 0; i < n; i += 1) sphere.expandByPoint(new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]))
    const centre = sphere.getCenter(new THREE.Vector3())
    const size = sphere.getSize(new THREE.Vector3())
    const radius = Math.hypot(size.x, size.y, size.z) / 2 + h + SWAY_MAX_M
    if (Math.hypot(cam.x - centre.x, cam.y - centre.y, cam.z - centre.z) - radius > cfg.cullM) return { low: 0, high: 0, hidden: true }
    const cull2 = cfg.cullM * cfg.cullM
    let low = 0, high = 0
    for (let i = 0; i < n; i += 1) {
      const dx = pos[i * 3] - cam.x, dy = pos[i * 3 + 1] - cam.y, dz = pos[i * 3 + 2] - cam.z
      const d2 = dx * dx + dy * dy + dz * dz
      let slot = 2
      if (d2 <= cull2) {
        const d = Math.sqrt(d2)
        const prev = 1
        const tier = L.instanceTier(d, !!loUrl && prev === 2 ? 1 : prev, cfg)
        if (tier !== 2 && L.instanceVisible(i, d, cfg) && L.inViewCone(dx, dz, cone.fwdX, cone.fwdZ, cone.cosHalf)) {
          slot = tier === 0 && hasHigh ? 0 : 1
        }
      }
      if (slot === 0) high += 1
      else if (slot === 1) low += 1
    }
    return { low, high, hidden: false }
  }

  const sampleWorld = (phase) => {
    const grids = new Map()
    const areasOut = []
    const builtAreas = terrain.areas.map((a) => buildAreaGeometry(THREE, a.polygon))
    terrain.areas.forEach((area, areaIndex) => {
      const built = builtAreas[areaIndex]
      if (!built) return
      const ring = built.ring
      const occluders = builtAreas.slice(areaIndex + 1).filter((b) => !!b).map((b) => b.ring)
      let rMinX = Infinity, rMinZ = Infinity, rMaxX = -Infinity, rMaxZ = -Infinity
      for (const [x, z] of ring) { rMinX = Math.min(rMinX, x); rMaxX = Math.max(rMaxX, x); rMinZ = Math.min(rMinZ, z); rMaxZ = Math.max(rMaxZ, z) }
      const areaCells = cells.filter(([cx, cz]) => {
        const x0 = cx * S.SCATTER_CELL_M, z0 = cz * S.SCATTER_CELL_M
        return rMaxX >= x0 && rMinX <= x0 + S.SCATTER_CELL_M && rMaxZ >= z0 && rMinZ <= z0 + S.SCATTER_CELL_M
      })
      const { gridOf } = cellOccupancy(grids)
      const rows = []
      ;(area.meta?.scatter ?? []).forEach((entry, index) => {
        if (entry.place === 'edge' || entry.place === 'center') return
        if (!areaCells.length) return
        const h = entry.model ? L.scatterTargetH(entry.prop_height_m) : TUFT_HEIGHT_M
        const model = typeof entry.model === 'string' ? entry.model : ''
        const maps = Array.isArray(entry.model_variants) && entry.model_variants.length ? entry.model_variants : [entry.variants ?? {}]
        const kinds = maps.map((variants, v) => {
          const fallback = v === 0 ? model : ''
          return { loUrl: pickVariant(variants, 'low') || fallback, hiUrl: pickVariant(variants, 'full') || fallback }
        })
        let spread = null
        if (phase === 'measured') {
          for (const k of kinds) for (const u of [k.hiUrl, k.loUrl]) {
            const s = u ? measured[u] : undefined
            if (s !== undefined && (spread === null || s > spread)) spread = s
          }
        }
        const clearM = S.scatterClearM(h, spread === null ? null : spread * h)
        const all = []
        for (const [cx, cz] of areaCells) {
          for (const p of S.scatterCellInstances({
            ring, cx, cz, densityPer100m2: Number(entry.density_per_100m2 ?? 0),
            seed: S.scatterCellSeed(area.id, index, cx, cz, S.reshuffleEpoch(NaN, entry.reshuffle_min)),
            footprints, clearM, occluders,
            minSpacingM: Number(entry.min_spacing_m) > 0 ? Number(entry.min_spacing_m) : undefined,
            variantCount: kinds.length, variant: entry.variant, yawMode: entry.yaw_mode, yawDeg: entry.yaw_deg,
            occupied: gridOf(cx, cz), occupyR: clearM, occupyTag: S.scatterSeed(area.id, index),
          })) all.push(p)
        }
        const sink = L.scatterGroundOffset(entry.ground_offset_m)
        const props = kinds.map((k, v) => {
          const mine = all.filter((p) => (p.variant ?? 0) === v)
          const pos = new Float32Array(mine.length * 3)
          mine.forEach((p, i) => { pos[i * 3] = p.x; pos[i * 3 + 1] = heightAt(p.x, p.z) + sink; pos[i * 3 + 2] = p.z })
          const hasHigh = !!k.hiUrl && k.hiUrl !== k.loUrl
          return { variant: v, count: mine.length, bins: mine.length ? binProp(Array.from(pos), h, hasHigh, k.loUrl) : null }
        })
        rows.push({ index, h, clearM, cells: areaCells.length, points: pts(all), props })
      })
      areasOut.push({ id: area.id, rows })
    })
    return areasOut
  }

  // The undergrowth (undergrowth.ts buildCell + binLayer) at the same anchor and camera.
  const undergrowthOf = () => {
    const kindValue = (kind) => {
      const t = terrain.types.find((x) => x.kind.toLowerCase() === (kind || '').toLowerCase())
      const raw = Number(t?.meta?.undergrowth)
      return !Number.isFinite(raw) || raw <= 0 ? 0 : Math.min(raw, 1)
    }
    const areas = terrain.areas.map((a) => {
      const built = buildAreaGeometry(THREE, a.polygon)
      if (!built) return null
      let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity
      for (const [x, z] of built.ring) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z) }
      return { id: a.id, ring: built.ring, bounds: [minX, minZ, maxX, maxZ], value: kindValue(a.kind) }
    }).filter((a) => a)
    const fpBox = (fp) => {
      let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity
      for (const [x, z] of fp.points) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z) }
      return [minX, minZ, maxX, maxZ]
    }
    const fps = footprints.map((fp) => ({ fp, bounds: fpBox(fp) }))
    const keys = U.wantedUndergrowthCells(anchor.x, anchor.z)
    const cellsOut = []
    for (const key of keys) {
      const [cx, cz] = key.split(',').map(Number)
      const cell = L.UNDERGROWTH_CELL_M
      const x0 = cx * cell, z0 = cz * cell, x1 = x0 + cell, z1 = z0 + cell
      const meets = (b) => b[2] >= x0 && b[0] <= x1 && b[3] >= z0 && b[1] <= z1
      const near = fps.filter((f) => meets(f.bounds)).map((f) => f.fp)
      const layers = []
      areas.forEach((area, index) => {
        if (L.undergrowthCellCount(area.value) < 1) return
        if (!meets(area.bounds)) return
        const occluders = []
        for (let j = index + 1; j < areas.length; j += 1) if (meets(areas[j].bounds)) occluders.push(areas[j].ring)
        const points = S.scatterInstances({
          ring: [[x0, z0], [x1, z0], [x1, z1], [x0, z1]], areaM2: cell * cell,
          densityPer100m2: L.undergrowthDensityPer100m2(area.value), seed: U.undergrowthCellSeed(area.id, cx, cz),
          footprints: near, occluders, maxPoints: L.UNDERGROWTH_MAX_PER_CELL, triesPerPoint: 1,
        })
        // The topLayerAt gate of the browser is left out on purpose: the occluders above already
        // drop every point an area painted later covers (see ScatterCheck / the S3 report).
        const kept = points.filter((p) => S.pointInRing(p.x, p.z, area.ring))
        if (!kept.length) return
        // binLayer at the fixture camera
        const reach = U.UNDERGROWTH_H_MAX + (U.UNDERGROWTH_H_MAX * 1.25) / 2 + 0.5
        const pos = new Float32Array(kept.length * 3)
        kept.forEach((p, i) => { pos[i * 3] = p.x; pos[i * 3 + 1] = heightAt(p.x, p.z); pos[i * 3 + 2] = p.z })
        const box = new THREE.Box3()
        for (let i = 0; i < kept.length; i += 1) box.expandByPoint(new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]))
        const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3())
        const radius = Math.hypot(s.x, s.y, s.z) / 2 + reach
        let visible = 0
        if (!(Math.hypot(cam.x - c.x, cam.y - c.y, cam.z - c.z) - radius > L.UNDERGROWTH_CULL_M)) {
          const cull2 = L.UNDERGROWTH_CULL_M * L.UNDERGROWTH_CULL_M
          for (let i = 0; i < kept.length; i += 1) {
            const dx = pos[i * 3] - cam.x, dy = pos[i * 3 + 1] - cam.y, dz = pos[i * 3 + 2] - cam.z
            const d2 = dx * dx + dy * dy + dz * dz
            if (d2 <= cull2 && L.undergrowthVisible(i, Math.sqrt(d2))) visible += 1
          }
        }
        layers.push({ area: area.id, seed: U.undergrowthCellSeed(area.id, cx, cz), points: pts(kept), visible,
                      shade0: U.undergrowthShade(kept[0].x, kept[0].z), height0: L.undergrowthHeight(kept[0].yaw) })
      })
      cellsOut.push({ key, layers })
    }
    return cellsOut
  }

  // World props outside the fine tile stand on the overview. At z=128 its
  // clamped east edge is (8+16)/2=12 m. All three authored props have z=128.
  // E4-T1: rows use the same fixture window, footprints and pass-local occupancy.
  // Along -> edge/center -> spread is the browser build order. The new stroke is
  // disjoint from the original spread areas, preserving their S3 baseline.
  const gameSeconds = 14465 // floor(14465/(120*60)) = 2; also sample the next epoch.
  const rowReference = (clock) => {
    const { grid } = cellOccupancy(new Map())
    const result = []
    for (const area of e4Terrain.areas) {
      const ring = cleanRing(area.polygon)
      const line = area.meta?.stroke ? T.strokeCentreLine(area.meta.stroke) : undefined
      const windowed = (points) => points.filter(p => cells.some(([cx, cz]) =>
        S.scatterCellAt(p.x) === cx && S.scatterCellAt(p.z) === cz))
      const sample = (entry, index, kind) => {
        const epoch = S.reshuffleEpoch(clock, entry.reshuffle_min)
        const seed = kind === 'along' ? T.alongSeed(area.id, index, epoch) : S.scatterSeed(area.id, index, epoch)
        const occupyTag = kind === 'along' ? T.alongSeed(area.id, index) : S.scatterSeed(area.id, index)
        const variantCount = entry.model_variants?.length || 1
        const h = L.scatterTargetH(entry.prop_height_m)
        const clearM = S.scatterClearM(h)
        const common = { seed, variantCount, variant: entry.variant, footprints, clearM,
          occupied: grid, occupyR: clearM, occupyTag, yawMode: entry.yaw_mode, yawDeg: entry.yaw_deg,
          jitterM: entry.spacing_jitter_m }
        const args = kind === 'along'
          ? { ...common, line, spacingM: entry.spacing_m, offsetM: entry.offset_m, side: entry.side, startM: entry.start_m }
          : kind === 'edge'
          ? { ...common, spacingM: entry.min_spacing_m, offsetM: entry.offset_m, sides: entry.sides,
              edges: line ? A.ribbonSelectedEdges(ring, entry.sides) : undefined }
          : { ...common, axisAt: A.areaAxis(line, ring, entry.sides) }
        const points = windowed(kind === 'along' ? T.strokeStations(args)
          : kind === 'edge' ? A.scatterEdgeInstances(ring, args) : A.scatterCenterInstance(ring, args))
        result.push({ area: area.id, index, kind, entry, ring, line, seed, occupyTag, epoch: epoch ?? null,
          clearM, points: pts(points) })
      }
      ;(area.meta?.along ?? []).forEach((e, i) => sample(e, i, 'along'))
      ;(area.meta?.scatter ?? []).forEach((e, i) => {
        if (e.place === 'edge' || e.place === 'center') sample(e, i, e.place)
      })
    }
    return { gameSeconds: clock, rows: result }
  }
  const worldProps = (worldmap.world_props ?? []).map(spec => {
    const distance = Math.hypot(spec.x - CAMERA.pos[0], spec.z - CAMERA.pos[2])
    const lod = W.worldPropLodCfg(cfg)
    return { id: spec.id, distance, lod, tier: L.instanceTier(distance, 1, lod),
      spec: W.worldPropSceneSpec(spec, W.worldPropBottom(spec,
        spec.x >= 0 && spec.x < 256 && spec.z >= 0 && spec.z < 256
          ? heightAt(spec.x, spec.z) : 12)) }
  })

  const tex = U.undergrowthTexturePixels()
  const out = {
    generated_by: 'native/fixtures/scatter_reference.mjs (scatter.ts / scatterAxis.ts / stroke.ts / occupancy.ts / scatterLod.ts / undergrowth.ts / worldProps.ts)',
    cases,
    fixture: {
      anchor, camera: CAMERA, lod: cfg, cells, footprints: footprints.map((f) => f.points), measured_spread: measured,
      estimate: sampleWorld('estimate'),
      measured: sampleWorld('measured'),
      undergrowth: undergrowthOf(),
    },
    e4: { epochs: [rowReference(gameSeconds), rowReference(gameSeconds + 7200)], worldProps },
    texture: { size: U.UNDERGROWTH_TEX_SIZE, bytes: tex.length,
               sha256: crypto.createHash('sha256').update(Buffer.from(tex.buffer, tex.byteOffset, tex.byteLength)).digest('hex'),
               samples: [[0, 0], [5, 3], [31, 20], [63, 63]].map(([r, c]) => [r, c, Array.from(tex.slice((r * 64 + c) * 4, (r * 64 + c) * 4 + 4))]) },
    hashes: [0, 1, 7, 12345, -3, 2147483647].map((i) => [i, L.instanceHash(i)]),
    shades: [[0, 0], [12.345, -67.891], [150.5, 99.25], [-1000.017, 2000.003]].map(([x, z]) => [x, z, U.undergrowthShade(x, z)]),
    seeds: [['abc', S.scatterSeedHash('abc')], [S.scatterCellSeed('a-1', 0, -2, 5, 4), S.scatterSeedHash(S.scatterCellSeed('a-1', 0, -2, 5, 4))]],
  }
  const file = path.join(root, 'native/fixtures/scatter_reference.json')
  fs.writeFileSync(file, JSON.stringify(out) + '\n')
  const rowsOf = (phase) => out.fixture[phase].flatMap((a) => a.rows.map((r) => `${a.id}#${r.index}=${r.points.length}`)).join(' ')
  console.log(`cases: ${cases.map((c) => `${c.name}=${c.points.length}`).join(' ')}`)
  console.log(`fixture cells=${cells.length} estimate: ${rowsOf('estimate')} | measured: ${rowsOf('measured')}`)
  console.log(`undergrowth cells=${out.fixture.undergrowth.length} instances=${out.fixture.undergrowth.reduce((s, c) => s + c.layers.reduce((t, l) => t + l.points.length, 0), 0)}`)
  console.log(`E4 rows=${out.e4.epochs.map(e => e.rows.map(r => `${r.kind}=${r.points.length}`).join(' ')).join(' | ')} worldProps=${worldProps.map(p => `${p.id}:${p.tier}`).join(' ')}`)
  console.log(`wrote ${path.relative(root, file)}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
