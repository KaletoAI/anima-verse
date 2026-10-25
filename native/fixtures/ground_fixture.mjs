#!/usr/bin/env node
/**
 * Writes the ground-surface fixtures of the native client's --check (Task S3b) — a cut-down
 * `/play/terrain-layers` bake, encoded exactly the way the server encodes it (contract § A16.7,
 * app/core/terrain_layers.py), from a rule simple enough to derive every byte by hand:
 *
 *   terrain_layers.json        GET /play/terrain-layers            (the index)
 *   terrain_layers_tiles.json  GET /play/terrain-layers?keys=…     (every tile; the fixture source answers only
 *                                                                    the requested AND indexed keys)
 *   surface_textures.json      GET /assets/surface-textures        (the library, a bare array like the server's)
 *   ground_grass.png           a 4 × 2 RGBA image of ONE colour (60, 140, 50, 255)
 *
 * THE TILES ARE SCALED DOWN, and that is the one liberty: tile_m = 32 instead of 256, so one tile is a 32² id
 * mask and a 64² sd mask instead of 256² / 512² (half a megabyte of base64 each). Every reader takes tile_m,
 * id_step_m and sd_step_m from the payload (`packLayerWindow`, `wantedTiles`), so nothing in the client
 * knows the difference. (32 and not smaller: `wantedTiles` refuses more than 64 tiles per axis inside its
 * 560 m radius, which a 16 m tile already exceeds.) The other numbers are the server's: id 1 m, sd 0.5 m, band 8 m, zero 128,
 * 127/8 codes per metre, `code = clamp(round(sd · 127/8) + 128, 1, 255)`.
 *
 * The little map (layers: 0 grass, 1 forest, 2 path, 3 lake (water, bed grass), 4 meadow):
 *   tile 2,3   x 64..96,   z 96..128   uniform forest
 *   tile 3,3   x 96..128,  z 96..128   forest | path at x = 100 (the path is painted later = A)
 *   tile 4,3   x 128..160, z 96..128   path | forest at x = 140
 *   tile 2,4   x 64..96,   z 128..160  forest | grass at z = 139 (forest below 139 = A over bare grass)
 *   tile 3,4   x 96..128,  z 128..160  uniform meadow
 *   tile 5,3   x 160..192, z 96..128   uniform lake
 * Rule 3 of § A16.7 is applied: an id texel whose nearest sd texel lies farther from the line than
 * `collapse_band_m` = ½ blend(A) + min(0.5, ½ blend(A)) + 1 m collapses to (own, own).
 * The overview: origin (32, 64), step 8, 24 × 24 cells, forest everywhere except cell (0, 0) = lake and the
 * columns i ≥ 20 (x ≥ 192) = meadow.
 *
 * Usage (repository root): node native/fixtures/ground_fixture.mjs   — deterministic, plain node, no deps.
 */
import * as fs from 'fs'
import * as path from 'path'
import * as zlib from 'zlib'
import { fileURLToPath } from 'url'

const DIR = path.dirname(fileURLToPath(import.meta.url))
const FMT = { sig: 'fixture-s3b', tile_m: 32, id_step_m: 1, sd_step_m: 0.5, sd_band_m: 8, sd_zero: 128,
              sd_codes_per_m: 127 / 8 }
const LAYERS = [
  { index: 0, kind: 'grass', surface: 'grass', edge_blend_m: 1.5, water: false },
  { index: 1, kind: 'forest', surface: 'forest', edge_blend_m: 1.5, water: false },
  { index: 2, kind: 'path', surface: 'path_blend', edge_blend_m: 0, water: false },
  { index: 3, kind: 'lake', surface: 'grass', edge_blend_m: 1.5, water: true, bed_kind: 'grass' },
  { index: 4, kind: 'meadow', surface: 'meadow_tex', edge_blend_m: 1.5, water: false },
]
const ID_N = FMT.tile_m / FMT.id_step_m       // 32
const SD_N = FMT.tile_m / FMT.sd_step_m       // 64

const encode = (sd) => Math.min(Math.max(Math.round(sd * FMT.sd_codes_per_m) + FMT.sd_zero, 1), 255)
const collapse = (blendA) => 0.5 * blendA + Math.min(0.5, 0.5 * blendA) + 1

/** A tile with ONE straight boundary. `sdOf(x, z)` is the signed distance (+ on A's side), `ownOf(x, z)` the
 *  layer a point really lies on, `a`/`b` the canonical pair. */
function boundaryTile(tx, tz, a, b, sdOf, ownOf) {
  const ox = tx * FMT.tile_m
  const oz = tz * FMT.tile_m
  const sd = new Uint8Array(SD_N * SD_N)
  for (let j = 0; j < SD_N; j += 1) {
    for (let i = 0; i < SD_N; i += 1) {
      sd[j * SD_N + i] = encode(sdOf(ox + (i + 0.5) * FMT.sd_step_m, oz + (j + 0.5) * FMT.sd_step_m))
    }
  }
  const band = collapse(LAYERS[a].edge_blend_m)
  const id = new Uint8Array(ID_N * ID_N * 2)
  for (let j = 0; j < ID_N; j += 1) {
    for (let i = 0; i < ID_N; i += 1) {
      let near = Infinity
      for (let dj = 0; dj < 2; dj += 1) {
        for (let di = 0; di < 2; di += 1) {
          const x = ox + (2 * i + di + 0.5) * FMT.sd_step_m
          const z = oz + (2 * j + dj + 0.5) * FMT.sd_step_m
          near = Math.min(near, Math.abs(sdOf(x, z)))
        }
      }
      const k = (j * ID_N + i) * 2
      if (near > band) {
        const own = ownOf(ox + i + 0.5, oz + j + 0.5)
        id[k] = own
        id[k + 1] = own
      } else {
        id[k] = a
        id[k + 1] = b
      }
    }
  }
  return { origin_x: ox, origin_z: oz, id_size: ID_N, sd_size: SD_N,
           id: Buffer.from(id).toString('base64'), sd: Buffer.from(sd).toString('base64') }
}

const uniform = (tx, tz, layer) => ({ origin_x: tx * FMT.tile_m, origin_z: tz * FMT.tile_m, uniform: layer })

const tiles = {
  '2,3': uniform(2, 3, 1),
  '2,4': boundaryTile(2, 4, 1, 0, (x, z) => 139 - z, (x, z) => (z < 139 ? 1 : 0)),
  '3,3': boundaryTile(3, 3, 2, 1, (x) => x - 100, (x) => (x > 100 ? 2 : 1)),
  '3,4': uniform(3, 4, 4),
  '4,3': boundaryTile(4, 3, 2, 1, (x) => 140 - x, (x) => (x < 140 ? 2 : 1)),
  '5,3': uniform(5, 3, 3),
}

const OV = { origin_x: 32, origin_z: 64, step_m: 8, cols: 24, rows: 24 }
const ovId = new Uint8Array(OV.cols * OV.rows * 2)
for (let j = 0; j < OV.rows; j += 1) {
  for (let i = 0; i < OV.cols; i += 1) {
    const layer = i === 0 && j === 0 ? 3 : i >= 20 ? 4 : 1
    ovId[(j * OV.cols + i) * 2] = layer
    ovId[(j * OV.cols + i) * 2 + 1] = layer
  }
}

const index = { ...FMT, layers: LAYERS, overview: { ...OV, id: Buffer.from(ovId).toString('base64') },
                tile_keys: Object.keys(tiles).sort((p, q) => {
                  const [a1, b1] = p.split(',').map(Number)
                  const [a2, b2] = q.split(',').map(Number)
                  return a1 - a2 || b1 - b2
                }) }
const batch = { ...FMT, layers: LAYERS, tiles }

const library = [
  { kind: 'grass', name: 'Grass', url: '/assets/surface-textures/ground_grass.png', size_m: 4 },
  { kind: 'forest', name: 'Forest', url: '/assets/surface-textures/dark_stone_2.jpg', size_m: 6,
    material: { class: 'matte' } },
  { kind: 'path_blend', name: 'Path blend', blend: { base: 'grass', over: 'forest', band_m: 2 } },
  { kind: 'meadow_tex', name: 'Meadow', url: '/assets/surface-textures/meadow_missing.png', size_m: 5 },
  { kind: 'unused', name: 'Unused', url: '/assets/surface-textures/unused.png', size_m: 2 },
]

/** A minimal PNG: 8-bit RGBA, no filter, zlib level 9 — deterministic. */
function png(w, h, rgba) {
  const crcTable = new Int32Array(256).map((_, n) => {
    let c = n
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    return c
  })
  const crc = (buf) => {
    let c = -1
    for (const byte of buf) c = crcTable[(c ^ byte) & 255] ^ (c >>> 8)
    return (c ^ -1) >>> 0
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4)
    len.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
    const sum = Buffer.alloc(4)
    sum.writeUInt32BE(crc(body))
    return Buffer.concat([len, body, sum])
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(w, 0)
  ihdr.writeUInt32BE(h, 4)
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0
  const raw = Buffer.alloc(h * (1 + w * 4))
  for (let y = 0; y < h; y += 1) {
    raw[y * (1 + w * 4)] = 0
    for (let x = 0; x < w; x += 1) raw.set(rgba, y * (1 + w * 4) + 1 + x * 4)
  }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))])
}

fs.writeFileSync(path.join(DIR, 'terrain_layers.json'), JSON.stringify(index, null, 1) + '\n')
fs.writeFileSync(path.join(DIR, 'terrain_layers_tiles.json'), JSON.stringify(batch, null, 1) + '\n')
fs.writeFileSync(path.join(DIR, 'surface_textures.json'), JSON.stringify(library, null, 1) + '\n')
fs.writeFileSync(path.join(DIR, 'ground_grass.png'), png(4, 2, [60, 140, 50, 255]))
console.log(`tiles=${Object.keys(tiles).length} keys=${index.tile_keys.join(';')} overview=${OV.cols}x${OV.rows}`)
