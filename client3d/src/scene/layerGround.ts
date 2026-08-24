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
 *    integer fetch and an interpolated distance compose into a sub-texel-sharp
 *    edge.
 *  - `sd` (R8, NEAREST) — per half metre the signed distance in metres to that
 *    boundary, quantised as the payload states. The four texels under ONE id
 *    texel are the ones the bake signed against ONE pair, so the compositor
 *    interpolates exactly those four itself (`lcSdAt`) instead of letting the
 *    sampler blend across the id texel's rim into a neighbour's sign.
 *  - `uLcSurf` (`sampler2DArray`) — one slice per layer, every surface texture
 *    resized onto ONE square. A kind without a library texture gets a slice of
 *    its flat catalog colour, so the fallback is a texel and not a branch.
 *
 * WATER WEARS ITS BED, AND THE SERVER SAYS WHICH (W1 § 5). A water layer stays
 * a full layer — the mask has to answer "here is water" for the undergrowth
 * gate and every point query — but what it PAINTS is the ground underneath:
 * the water itself is a SHADING of the same pixel (`scene/waterShade.ts`, and
 * a separate mirror mesh until Wasser v2 K-A E5), and painting the lake twice
 * made the two fight each other. Until W1 this file
 * decided that itself, substituting layer 0's image for every water layer; now
 * `surface` already IS the bed's (`meta.bed_kind`, defaulting to the bare
 * world) and `bed_kind` names the kind it came from. So there is nothing to
 * substitute any more — a slice wears the surface its table row names, water
 * or not — and an authored gravel bed reaches the ground instead of being
 * flattened back to the default kind.
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
  // NEAREST: the compositor fetches the sd by TEXEL and interpolates the four
  // of its own id texel itself (`lcSdAt`), because a hardware filter reaches
  // into the neighbouring id texel — whose texels are signed against another
  // boundary. A linear sampler here would be a filter nobody asks for.
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
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

/** Anisotropic samples the surface array is built with. Named because the
 *  isolation panel's filtering test (toggle 18) has to put exactly this number
 *  back when it is switched off again. */
const SURFACE_ANISOTROPY = 4;

// ── The state this module owns ──────────────────────────────────────────────

let layers: TerrainLayer[] = [];
let window_: LayerMaskWindow | null = null;
let ownedNearId: THREE.DataTexture | null = null;
let ownedNearSd: THREE.DataTexture | null = null;
let ownedFarId: THREE.DataTexture | null = null;
let ownedArray: THREE.DataArrayTexture | null = null;

// ── The isolation switches (`debug3d.ts`, toggles 7 and 18) ─────────────────
//
// WHAT THE WORLD SAYS, kept apart from what is BOUND. The payload writes the
// three `live*` values below; `pushLayerWindows` decides what the shader really
// gets. Two states can therefore not drift: a terrain signature that lands
// while the compositor is switched off updates the live set, and switching the
// toggle back on binds THAT one rather than a copy taken minutes ago.

/** The surface array the payload built — `neutralArray` while there is none. */
let liveSurf: THREE.Texture = neutralArray;
/** `uLcNear.w`: the edge length of the fine mask window, 0 = no window. */
let liveNearN = 0;
/** `uLcFarSize`: the coarse mask's columns and rows, 0/0 = no coarse mask. */
let liveFarCols = 0;
let liveFarRows = 0;
/** Isolation toggle 7: paint the ground in one flat colour. */
let lcFlat = false;
/** Isolation toggle 18: the surface array without mipmaps and without
 *  anisotropy. */
let lcLoFilter = false;

/** The ONE place the three switchable uniforms are bound. */
function pushLayerWindows(): void {
  uSurf.value = lcFlat ? neutralArray : liveSurf;
  uNear.value.w = lcFlat ? 0 : liveNearN;
  uFarSize.value.set(lcFlat ? 0 : liveFarCols, lcFlat ? 0 : liveFarRows);
}

/**
 * Switch the layer compositor off: no masks, no surface array, the ground in
 * ONE flat colour — the heights stay exactly as they were.
 *
 * With both windows at size 0 `lcCompose` takes its `else` branch, the layer
 * pair is (0, 0), and the one neutral texel of `neutralArray` is what the whole
 * ground is multiplied by. Uniform writes only, so no program is rebuilt.
 */
export function setLayerCompositorFlat(on: boolean): void {
  if (lcFlat === on) return;
  lcFlat = on;
  pushLayerWindows();
}

/**
 * The texture-filtering test: the surface array with LINEAR minification (no
 * mip chain) and anisotropy 1, or back to its built state.
 *
 * This one is NOT free — three re-uploads the whole array (32 slices at 512²
 * RGBA in the live world), so expect a hitch on either edge. That is a
 * transfer, not a compile.
 */
export function setLayerSurfaceFiltering(lowRes: boolean): void {
  if (lcLoFilter === lowRes) return;
  lcLoFilter = lowRes;
  applySurfaceFiltering();
}

/** Bring `liveSurf` to whatever `lcLoFilter` currently asks for. Called on
 *  every toggle AND after a fresh array was built, so a terrain signature that
 *  lands while the test is running does not quietly restore the mip chain. */
function applySurfaceFiltering(): void {
  const tex = liveSurf;
  if (tex === neutralArray) return;    // nothing built yet, nothing to filter
  const minFilter = lcLoFilter ? THREE.LinearFilter : THREE.LinearMipmapLinearFilter;
  const anisotropy = lcLoFilter ? 1 : SURFACE_ANISOTROPY;
  const mips = !lcLoFilter;
  if (tex.minFilter === minFilter && tex.anisotropy === anisotropy
      && tex.generateMipmaps === mips) return;
  tex.minFilter = minFilter;
  tex.anisotropy = anisotropy;
  tex.generateMipmaps = mips;
  tex.needsUpdate = true;
}

/**
 * Hang the NEAR id mask and its window into a shader that is not this patch —
 * under names of that shader's own choosing (Wasser v2, K-A E4).
 *
 * ITS ONE CALLER is the terrain's WATER variant (`scene/terrainLod.ts`), which
 * has to know which KIND a water pixel stands in to pick its tint, and the id
 * mask is the one thing in this client that answers that per fragment. It
 * cannot use `uLcNearId`/`uLcNear`: the compositor's chunk is declared BELOW
 * the terrain's in the finished shader, so those names are not in scope there
 * — a second sampler bound to the SAME texture object is one texture unit and
 * no second upload.
 *
 * The objects themselves are handed over, never their values: a window swap
 * mutates `.value` in place, so the borrowing program follows every update
 * without a second book to keep.
 */
export function bindLayerIdUniforms(uniforms: Record<string, unknown>,
                                    idName: string, geomName: string): void {
  uniforms[idName] = uNearId;
  uniforms[geomName] = uNear;
}

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
 * Every slice is drawn onto one `SLICE_PX` square: the library texture the
 * layer's own `surface` names, or the flat catalog colour where it names none.
 * On a WATER layer that surface is already the bed's (see the file header), so
 * the colour fallback and the tile size have to ask the BED kind too —
 * `bed_kind` is what the row carries for exactly that. `colorOf` is handed in
 * because the catalog lives in `scene/ground.ts` and importing it back here
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
  for (let index = 0; index < layers.length; index += 1) {
    const layer = layers[index];
    // WHICH KIND'S LOOK THIS SLICE WEARS. The surface is the row's own — on a
    // water row the server already put the BED's there — and the kind behind
    // it is `bed_kind` where the row names one. No substitution happens here;
    // the client renders the surface the table names (W1 § 5).
    const kind = layer.bed_kind || layer.kind;
    const lib = surfaceFor(layer.surface, 'wall');
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
      const c = new THREE.Color(colorOf(kind) || '#888888');
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
    const size = sizeOf ? sizeOf(kind) : (lib?.sizeM ?? 3);
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
  tex.anisotropy = SURFACE_ANISOTROPY;
  tex.needsUpdate = true;
  ownedArray?.dispose();
  ownedArray = tex;
  liveSurf = tex;
  applySurfaceFiltering();
  pushLayerWindows();
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
    liveFarCols = 0;
    liveFarRows = 0;
    pushLayerWindows();
    return;
  }
  const bytes = base64Bytes(ov.id);
  if (!bytes || bytes.length < ov.cols * ov.rows * 2) {
    uFarId.value = neutralId;
    liveFarCols = 0;
    liveFarRows = 0;
    pushLayerWindows();
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
  liveFarCols = ov.cols;
  liveFarRows = ov.rows;
  pushLayerWindows();
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
    liveNearN = 0;
    pushLayerWindows();
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
  // NEAREST — the compositor reconstructs the field from the four texels of the
  // fragment's own id texel (`lcSdAt`); see `makeNeutralSd`.
  sdTex.minFilter = THREE.NearestFilter;
  sdTex.magFilter = THREE.NearestFilter;
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
  liveNearN = win.idSize;
  pushLayerWindows();
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
  uNear.value.set(0, 0, 1, 0);
  liveSurf = neutralArray;
  liveNearN = 0;
  liveFarCols = 0;
  liveFarRows = 0;
  pushLayerWindows();
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
