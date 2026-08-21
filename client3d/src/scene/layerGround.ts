/**
 * layerGround — the ground's MATERIAL, cut into the one terrain surface
 * (plan-ein-boden.md § G3, contract addendum "Ein Boden — E3").
 *
 * WHAT DIED HERE. Until E3 every painted shape of `GET /play/terrain` was its
 * own transparent mesh, draped over the terrain, held off its neighbours by a
 * `renderOrder` ladder, a `polygonOffset` ladder and a hairline y ladder, and
 * faded into them over a fixed 1.5 m alpha fringe with a refined edge band of
 * extra triangles. Three depth crutches and a sorting problem for something
 * that is not a stack: at any point of the ground exactly ONE material is on
 * top. All of it is gone. The terrain is one mesh, and this file is the shader
 * patch that paints it.
 *
 * WHAT IT READS. Two masks the server bakes (`app/core/terrain_layers.py`) and
 * one texture array this file builds:
 *
 *  - `id` (RG8UI, NEAREST) — per metre the PAIR (A, B) of layer indices at the
 *    nearest boundary: A the layer painted on top there, B the one under it.
 *    THE PAIR IS THE SAME ON BOTH SIDES of the line; only the sign of the
 *    distance says which side a fragment is on. That is what lets a NEAREST
 *    integer fetch and a LINEAR distance compose into a sub-texel-sharp edge.
 *  - `sd` (R8, LINEAR) — per half metre the signed distance in metres to that
 *    boundary, quantised as the payload states.
 *  - `uLcSurf` (`sampler2DArray`) — one slice per layer, every surface texture
 *    resized onto ONE square. A kind without a library texture gets a slice of
 *    its flat catalog colour, so the fallback is a texel and not a branch.
 *
 * WATER, THIS STAGE. A water layer's slice holds BARE GROUND's image: until E4
 * the lake surface is still drawn by its own ripple drape (`scene/ground.ts`),
 * and what the compositor paints under it is the bed. The mask still knows the
 * water layer — it has to, or the undergrowth would grow in the lake and the
 * priority would be a lie.
 *
 * WHERE IT SITS IN THE CHAIN. `patchHole` (the basement cut) → `applyNaturalGround`
 * (colour patches + height AO) → THIS. Each patch inserts its body directly
 * after `#include <map_fragment>`, so the LAST one applied runs FIRST — which
 * is the order the plan asks for: the compositor writes the albedo, the natural
 * stages then work on the composited one.
 */
import * as THREE from 'three';
import { packLayerWindow, terrainLayerGlsl, terrainLayerVertexGlsl,
  topLayerAt } from '@anima/scene-render';
import type { LayerMaskWindow, TerrainLayer, TerrainLayerFormat,
  TerrainLayerOverview, TerrainLayerTile } from '@anima/scene-render';
import { preloadSurfaceTexture, surfaceFor } from './tiles';

/**
 * Edge length of one slice of the surface array, in texels.
 *
 * A `sampler2DArray` needs every slice the same size, and the library's images
 * are not (a generated ground is 512 or 1024 square, a hand-made one anything).
 * 512 is what the generated ones already are, so the common case is a straight
 * copy and only an odd one is resampled; 32 layers at 512² RGBA with a mip
 * chain are 32 · 1.4 MB ≈ 45 MB, which is the same order the drapes spent on
 * their own texture clones and is paid once per terrain signature instead of
 * once per painted shape.
 */
const SLICE_PX = 512;

/** Layers the shader's uniform array is sized for. It is a COMPILE-TIME
 *  constant in GLSL, so the program is built for the world's own table rounded
 *  up to this — one size for every terrain material in the process, which is
 *  what keeps them on one compiled program. 64 covers every world that has
 *  ever been painted and costs 64 · 16 bytes of uniform space. */
export const LC_MAX_LAYERS = 64;

/** The cache key this patch contributes. Exported so the smoke can pin the
 *  COMBINED key without carrying a copy of the string. */
export const LC_CACHE_KEY = 'layer-cut';

// ── The shared uniforms ─────────────────────────────────────────────────────
// ONE object per value for every patched material — the pattern of
// `naturalGround.ts` and `terrainLod.ts`. Swapping a window is one assignment
// and nothing recompiles.

/** One texel of nothing, so no sampler is ever unbound: a driver handed a null
 *  sampler is a warning at best and a black ground at worst. */
function makeNeutralId(): THREE.DataTexture {
  const tex = new THREE.DataTexture(new Uint8Array([0, 0, 0, 0]), 1, 1,
                                    THREE.RGIntegerFormat, THREE.UnsignedByteType);
  tex.internalFormat = 'RG8UI';
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  return tex;
}

function makeNeutralSd(): THREE.DataTexture {
  const tex = new THREE.DataTexture(new Uint8Array([255]), 1, 1,
                                    THREE.RedFormat, THREE.UnsignedByteType);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.generateMipmaps = false;
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  return tex;
}

function makeNeutralArray(): THREE.DataArrayTexture {
  const tex = new THREE.DataArrayTexture(new Uint8Array([128, 128, 128, 255]),
                                         1, 1, 1);
  tex.format = THREE.RGBAFormat;
  tex.type = THREE.UnsignedByteType;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.needsUpdate = true;
  return tex;
}

const neutralId = makeNeutralId();
const neutralSd = makeNeutralSd();
const neutralArray = makeNeutralArray();

const uNearId: { value: THREE.Texture } = { value: neutralId };
const uNearSd: { value: THREE.Texture } = { value: neutralSd };
const uFarId: { value: THREE.Texture } = { value: neutralId };
const uSurf: { value: THREE.Texture } = { value: neutralArray };
/** originX, originZ, idStep, idSize — 0 size switches the near window off. */
const uNear = { value: new THREE.Vector4(0, 0, 1, 0) };
/** originX, originZ, sdStep, sdSize. */
const uNearSdGeom = { value: new THREE.Vector4(0, 0, 1, 1) };
/** originX, originZ, step, 0. */
const uFar = { value: new THREE.Vector4(0, 0, 1, 0) };
const uFarSize = { value: new THREE.Vector2(0, 0) };
/** The quantisation of the sd byte: zero code, codes per metre. */
const uSdCode = { value: new THREE.Vector2(128, 1) };
const uBandM = { value: 8 };

function makeLayerArray(): THREE.Vector4[] {
  const out: THREE.Vector4[] = [];
  for (let i = 0; i < LC_MAX_LAYERS; i += 1) out.push(new THREE.Vector4(1.5, 3, 0, 0));
  return out;
}
/** Per layer: edge_blend_m, metres per texture tile, unused, unused. */
const uLayer = { value: makeLayerArray() };

// ── The state this module owns ──────────────────────────────────────────────

let layers: TerrainLayer[] = [];
let window_: LayerMaskWindow | null = null;
let ownedNearId: THREE.DataTexture | null = null;
let ownedNearSd: THREE.DataTexture | null = null;
let ownedFarId: THREE.DataTexture | null = null;
let ownedArray: THREE.DataArrayTexture | null = null;

/** The layer table in force — read by the undergrowth gate, which has to turn a
 *  painted kind into the index the mask speaks. */
export function layerTable(): readonly TerrainLayer[] {
  return layers;
}

/** The layer index of a terrain KIND, or 0 (bare ground) for a kind the table
 *  does not hold. The mask speaks indices; everything else speaks kinds. */
export function layerIndexOfKind(kind: string): number {
  const want = (kind || '').trim().toLowerCase();
  for (const layer of layers) {
    if (layer.kind.toLowerCase() === want) return layer.index;
  }
  return 0;
}

/** WHICH GROUND IS ON TOP at a world point, as a layer index — the CPU reading
 *  of the very mask the shader composites from (`topLayerAt`). The undergrowth
 *  gate is its one caller (user decision 5.2). Outside the loaded window the
 *  answer is bare ground, which is what an unloaded tile draws. */
export function topLayerIndexAt(x: number, z: number): number {
  return topLayerAt(window_, x, z);
}

/** The loaded window itself, for the smoke and for anything that needs the raw
 *  reading rather than the gate. */
export function layerWindow(): LayerMaskWindow | null {
  return window_;
}

/**
 * Take over the layer TABLE and build the surface array from it.
 *
 * Every slice is drawn onto one `SLICE_PX` square: the library texture where
 * the kind names one, the flat catalog colour where it does not, and BARE
 * GROUND's image for a water layer (see the file header). `colorOf` is handed
 * in because the catalog lives in `scene/ground.ts` and importing it back here
 * would close a cycle.
 *
 * Awaits the library first — `surfaceFor` only hands out fully loaded images,
 * and a slice drawn from a loading texture would be a black square that never
 * repaints.
 */
export async function setLayerTable(next: readonly TerrainLayer[],
                                    colorOf: (kind: string) => string,
                                    sizeOf?: (kind: string) => number
): Promise<void> {
  layers = next.slice(0, LC_MAX_LAYERS).map((l) => ({ ...l }));
  await Promise.all(layers.map((l) => preloadSurfaceTexture(l.surface)));
  const canvas = document.createElement('canvas');
  canvas.width = SLICE_PX;
  canvas.height = SLICE_PX;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const depth = Math.max(1, layers.length);
  const data = new Uint8Array(SLICE_PX * SLICE_PX * 4 * depth);
  const bare = layers[0];
  for (let index = 0; index < layers.length; index += 1) {
    const layer = layers[index];
    // A WATER layer wears the BED, not the lake: the ripple drape still draws
    // the surface until E4, and painting the water texture under it as well
    // would be the same image twice with the shader fighting itself.
    const source = layer.water ? bare : layer;
    const lib = surfaceFor(source.surface, 'wall');
    const at = index * SLICE_PX * SLICE_PX * 4;
    if (ctx && lib?.texture.image) {
      ctx.clearRect(0, 0, SLICE_PX, SLICE_PX);
      ctx.drawImage(lib.texture.image as CanvasImageSource,
                    0, 0, SLICE_PX, SLICE_PX);
      data.set(ctx.getImageData(0, 0, SLICE_PX, SLICE_PX).data, at);
    } else {
      // No library entry: the flat catalog colour, written once into the slice.
      // A texel is cheaper than a shader branch and behaves identically under
      // the anti-tile blend (two samples of one colour ARE that colour).
      const c = new THREE.Color(colorOf(source.kind) || '#888888');
      const r = Math.round(c.r * 255);
      const g = Math.round(c.g * 255);
      const b = Math.round(c.b * 255);
      for (let p = 0; p < SLICE_PX * SLICE_PX; p += 1) {
        const k = at + p * 4;
        data[k] = r;
        data[k + 1] = g;
        data[k + 2] = b;
        data[k + 3] = 255;
      }
    }
    const size = sizeOf ? sizeOf(source.kind) : (lib?.sizeM ?? 3);
    uLayer.value[index].set(layer.edge_blend_m, size > 0 ? size : 3, 0, 0);
  }
  for (let index = layers.length; index < LC_MAX_LAYERS; index += 1) {
    uLayer.value[index].set(0, 3, 0, 0);
  }
  const tex = new THREE.DataArrayTexture(data, SLICE_PX, SLICE_PX, depth);
  tex.format = THREE.RGBAFormat;
  tex.type = THREE.UnsignedByteType;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.RepeatWrapping;
  tex.generateMipmaps = true;
  tex.anisotropy = 4;
  tex.needsUpdate = true;
  ownedArray?.dispose();
  ownedArray = tex;
  uSurf.value = tex;
}

/** Take over the COARSE world-wide id mask — what the ground wears beyond the
 *  fine tiles. Read with NEAREST like the fine one; it carries no distance, so
 *  its edges are hard, which past the haze is a fraction of a pixel. */
export function setLayerOverview(ov: TerrainLayerOverview | null): void {
  ownedFarId?.dispose();
  ownedFarId = null;
  if (!ov || !(ov.cols > 1) || !(ov.rows > 1) || !(ov.step_m > 0) || !ov.id) {
    uFarId.value = neutralId;
    uFar.value.set(0, 0, 1, 0);
    uFarSize.value.set(0, 0);
    return;
  }
  const bytes = base64Bytes(ov.id);
  if (!bytes || bytes.length < ov.cols * ov.rows * 2) {
    uFarId.value = neutralId;
    uFarSize.value.set(0, 0);
    return;
  }
  const tex = new THREE.DataTexture(bytes, ov.cols, ov.rows,
                                    THREE.RGIntegerFormat, THREE.UnsignedByteType);
  tex.internalFormat = 'RG8UI';
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.generateMipmaps = false;
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  ownedFarId = tex;
  uFarId.value = tex;
  uFar.value.set(ov.origin_x, ov.origin_z, ov.step_m, 0);
  uFarSize.value.set(ov.cols, ov.rows);
}

/**
 * Take over the FINE masks — the tiles that have arrived, packed into ONE
 * window (`packLayerWindow`).
 *
 * Packing rather than sampling per tile is the same bargain `terrainLod`'s near
 * pyramid strikes: a fragment shader that had to find its tile first would
 * branch per pixel over a set that changes as the player walks. A tile that is
 * missing stays at the neutral fill, which reads as bare ground — exactly what
 * an unindexed tile IS.
 */
export function setLayerTiles(tiles: Map<string, TerrainLayerTile>,
                              fmt: TerrainLayerFormat | null): void {
  ownedNearId?.dispose();
  ownedNearSd?.dispose();
  ownedNearId = null;
  ownedNearSd = null;
  const win = fmt ? packLayerWindow(tiles, fmt) : null;
  window_ = win;
  if (!win) {
    uNearId.value = neutralId;
    uNearSd.value = neutralSd;
    uNear.value.set(0, 0, 1, 0);
    return;
  }
  const idTex = new THREE.DataTexture(win.id, win.idSize, win.idSize,
                                      THREE.RGIntegerFormat, THREE.UnsignedByteType);
  idTex.internalFormat = 'RG8UI';
  idTex.minFilter = THREE.NearestFilter;
  idTex.magFilter = THREE.NearestFilter;
  idTex.wrapS = THREE.ClampToEdgeWrapping;
  idTex.wrapT = THREE.ClampToEdgeWrapping;
  idTex.generateMipmaps = false;
  idTex.unpackAlignment = 1;
  idTex.needsUpdate = true;
  const sdTex = new THREE.DataTexture(win.sd, win.sdSize, win.sdSize,
                                      THREE.RedFormat, THREE.UnsignedByteType);
  sdTex.minFilter = THREE.LinearFilter;
  sdTex.magFilter = THREE.LinearFilter;
  sdTex.wrapS = THREE.ClampToEdgeWrapping;
  sdTex.wrapT = THREE.ClampToEdgeWrapping;
  sdTex.generateMipmaps = false;
  sdTex.unpackAlignment = 1;
  sdTex.needsUpdate = true;
  ownedNearId = idTex;
  ownedNearSd = sdTex;
  uNearId.value = idTex;
  uNearSd.value = sdTex;
  uNear.value.set(win.originX, win.originZ, win.idStep, win.idSize);
  uNearSdGeom.value.set(win.originX, win.originZ, win.sdStep, win.sdSize);
  uSdCode.value.set(win.sdZero, win.sdCodesPerM);
  uBandM.value = win.sdBandM;
}

/** Everything back to "no cut": bare ground, no GPU memory held. */
export function disposeLayerGround(): void {
  ownedNearId?.dispose();
  ownedNearSd?.dispose();
  ownedFarId?.dispose();
  ownedArray?.dispose();
  ownedNearId = null;
  ownedNearSd = null;
  ownedFarId = null;
  ownedArray = null;
  window_ = null;
  layers = [];
  uNearId.value = neutralId;
  uNearSd.value = neutralSd;
  uFarId.value = neutralId;
  uSurf.value = neutralArray;
  uNear.value.set(0, 0, 1, 0);
  uFarSize.value.set(0, 0);
}

/** base64 -> bytes (browser). */
function base64Bytes(b64: string): Uint8Array | null {
  if (!b64) return null;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

// ── The patch ───────────────────────────────────────────────────────────────

/** Materials that already carry the compositor. The patch CHAINS, so applying
 *  it twice would declare `vLcWorld` a second time and the shader would not
 *  compile — the guard `patchHole`, `applyNaturalGround` and `patchTerrainLod`
 *  all keep, for the same reason. */
const lcPatched = new WeakSet<THREE.Material>();

/** Where the world position is taken — AFTER `project_vertex`, i.e. after the
 *  CDLOD displacement has put the vertex where it really is. Measuring before
 *  it would paint the ground where it used to be. */
const ANCHOR_VERT = '#include <project_vertex>';
/** …and the colour work goes after the map chunk, the anchor every ground patch
 *  in this client uses. Because each patch inserts DIRECTLY after the anchor,
 *  the one applied LAST runs FIRST — which is why this must be applied after
 *  `applyNaturalGround`: the compositor writes the albedo, the natural stages
 *  then work on what it wrote. */
const ANCHOR_FRAG = '#include <map_fragment>';

/**
 * Give the terrain material the layer compositor.
 *
 * NO `map` ON THE MATERIAL, deliberately. The albedo comes entirely out of the
 * texture array, and a `map` beside it would make `USE_MAP` true — which would
 * switch on the anti-tile stage of `applyNaturalGround`, and that one would
 * blend the DEFAULT kind's wide sample over a forest. The anti-tile lives in
 * the compositor instead (`lcSurface`), per layer, where it belongs.
 */
export function applyTerrainLayers(mat: THREE.Material): void {
  if (lcPatched.has(mat)) return;
  lcPatched.add(mat);
  const prev = mat.onBeforeCompile;
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    shader.uniforms.uLcNearId = uNearId;
    shader.uniforms.uLcNearSd = uNearSd;
    shader.uniforms.uLcFarId = uFarId;
    shader.uniforms.uLcSurf = uSurf;
    shader.uniforms.uLcNear = uNear;
    shader.uniforms.uLcNearSdGeom = uNearSdGeom;
    shader.uniforms.uLcFar = uFar;
    shader.uniforms.uLcFarSize = uFarSize;
    shader.uniforms.uLcSdCode = uSdCode;
    shader.uniforms.uLcBandM = uBandM;
    shader.uniforms.uLcLayer = uLayer;
    if (!shader.vertexShader.includes(ANCHOR_VERT)) return;
    if (!shader.fragmentShader.includes(ANCHOR_FRAG)) return;
    shader.vertexShader = terrainLayerVertexGlsl() + shader.vertexShader
      .replace(ANCHOR_VERT,
        `${ANCHOR_VERT}\n\tvLcWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;`);
    shader.fragmentShader = terrainLayerGlsl(LC_MAX_LAYERS)
      + shader.fragmentShader
        .replace(ANCHOR_FRAG, `${ANCHOR_FRAG}\n\tlcCompose( diffuseColor );`);
  };
  mat.customProgramCacheKey = () => (prevKey
    ? `${prevKey}+${LC_CACHE_KEY}`
    : LC_CACHE_KEY);
}
