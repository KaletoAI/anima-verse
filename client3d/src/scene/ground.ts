/**
 * The GROUND of the seamless metre world (plan-freie-weltkarte-e4-3d-client.md,
 * task 2).
 *
 * ONE SURFACE SINCE E3. The world's ground is the CDLOD terrain mesh
 * (`scene/terrainLod.ts`) and nothing else: the painted areas of
 * `GET /play/terrain` are CUT INTO ITS MATERIAL per texel out of the masks the
 * server bakes (`scene/layerGround.ts`, plan-ein-boden.md § G3), instead of
 * being N transparent drape meshes stacked on it. What went with the drapes:
 * the `renderOrder` ladder at −10000 + i, the `polygonOffset` ladder down to
 * −32, the hairline y ladder of 0.4 mm per level, the alpha fringe and its
 * refined edge band. The only drape left in the world is WATER's, until E4
 * gives it a level mirror.
 *
 * WHAT LIVES WHERE
 *  - the polygon geometry is SHARED (`@anima/scene-render/groundAreas`), because
 *    the admin preview shows the same areas;
 *  - the CUT is shared as well (`@anima/scene-render/layerCut`): the mask
 *    format, the blend arithmetic and the GLSL are one source for both
 *    renderers and for the smoke;
 *  - how a KIND is painted is shared too (`surfaceMaterial` + the surface-texture
 *    library the tiles already feed);
 *  - what is in THIS file is view state: which meshes stand in the scene, the
 *    prop scatter and its distance cut-off, plus the FAR half of the scatter —
 *    beyond the cull line an entry with a model is drawn as billboards out to
 *    400 m (`scene/impostors.ts` bakes them, this file bins them onto the
 *    entry's own positions);
 *  - the automatic undergrowth (the layer nobody authored, § A9) is its OWN
 *    module since 2026-08-16 (`scene/undergrowth.ts`): it is not built per
 *    painted shape any more but per 64 m cell around the anchor, which is a
 *    different lifetime from everything else here. This file feeds it the
 *    shapes, the anchor and the LOD beat.
 *
 * GROUND_Y DISCIPLINE, as rewritten by "Ein Boden" E2. The ground is one
 * height and one only — `ground_y(x, z)`, which since § A16 is the heightfield
 * sampled at that point instead of the constant 0, and since E2 there is ONE
 * reading of it: `@anima/scene-render` `heightAt`, bilinear on the data,
 * finest loaded tile before overview. It is what the figures stand on, what
 * the props and the scatter and the undergrowth sit on, what the painted areas
 * are draped by, what a click resolves against — and, through the CDLOD
 * terrain (`scene/terrainLod.ts`), what the picture is BUILT from: the vertex
 * shader fetches the very same lattice with the very same bilinear mix.
 *
 * WHAT DIED WITH IT: the "drawn ground" sampler that re-read the field along
 * the triangles of the one big base plate. That plate is gone, and with it the
 * 64 m cells its 40 000-cell budget had coarsened the live world to — the
 * measured 2.433 m by which the surface a figure stood on differed from the
 * field the server judged its walk by. The base mesh's `gridPlate` and the ONE
 * world-wide cell size that went with it are gone too.
 *
 * REFETCH. Neither the terrain nor the relief is ever withheld, so both are
 * fetched ONCE and again only when the worldmap poll reports a different
 * signature — `terrain_sig` for the painted areas AND for the layer masks
 * (they are baked from exactly those areas plus the type catalog), `height_sig`
 * for the field. `sync()` takes both and does nothing while they are unchanged.
 *
 * THE RELIEF ARRIVES TWICE SINCE v2 (§ A16.3), and this file is where the two
 * meet: the coarsenable OVERVIEW comes with the signature above, and the fine
 * 256 m tiles are a WINDOW that follows the player — `setHeightAnchor` says
 * where, `scene/heightTiles.ts` says which, and every sampler below reads the
 * pair through the shared composite ladder (tile first, overview behind it).
 * Nothing waits for a tile: the ground is simply draped again when one lands,
 * exactly as it is when the overview does.
 */
import * as THREE from 'three';
import { buildAreaGeometry,
  heightAt as worldHeightAt, pickVariant, pointInRing,
  propGroundFit, rayGroundHit,
  scatterCellInstances, scatterCellSeed, scatterClearM,
  SCATTER_CELL_M,
  surfaceMaterial, surfaceTimeUniform, tileKeyAt, wantedScatterCells,
  worldHeightRange } from '@anima/scene-render';
import type { Point2, ScatterFootprint, ScatterInstance,
  SurfaceMaterialSpec, TerrainLayer, TerrainLayerBatch, TerrainLayerFormat,
  TerrainLayerIndex, TerrainLayerTile, WorldHeightField,
  WorldHeightTileStats,
  WorldHeightTiles } from '@anima/scene-render';
import { fetchHeightfield, fetchHeightTiles, fetchTerrain,
  fetchTerrainLayers } from '../api';
import type { HeightTileBatch } from '../api';
import { localToWorld } from '../game/enterLocation';
import { footprintSignature, TERRAIN_FALLBACK_COLOR } from '../game/minimap';
import { sanitizePolygon } from '../game/polygon';
import type { MapLocation, TerrainArea, TerrainPayload, TerrainScatterEntry, TerrainType,
  WorldBounds } from '../types';
import { HEIGHT_TILE_CACHE_MAX, HEIGHT_TILE_RADIUS_M, tileBatches,
  wantedTiles } from './heightTiles';
import { hasSurfaceTexture, preloadSurfaceTexture, setWorldGround, surfaceFor,
  surfaceMaterialSpec } from './tiles';
import { acquireImpostor, createImpostorMesh, disposeImpostorMesh,
  releaseImpostor } from './impostors';
import { applyTerrainLayers, disposeLayerGround, layerIndexOfKind,
  setLayerOverview, setLayerTable, setLayerTiles,
  topLayerIndexAt } from './layerGround';
import { applyNaturalGround, setNaturalGroundField } from './naturalGround';
import { isWaterClass } from './naturalGroundMath';
import { applyOcclusionFade } from './occlusion';
import { loadGlb } from './propAssets';
import { IMPOSTOR_FAR_M, impostorQuad, impostorVisible, impostorYaw,
  instanceTier, instanceVisible, SCATTER_LOD_DEFAULTS, scatterGroundOffset,
  scatterSway, scatterTargetH } from './scatterLod';
import type { ImpostorQuad, InstanceTier, ScatterLodCfg } from './scatterLod';
import { createTerrainLod } from './terrainLod';
import type { TerrainCullStats } from './terrainLod';
import { createUndergrowthField } from './undergrowth';
import { buildWaterPlane, patchWaterShore } from './waterPlane';
import { waterLevelAt, waterProfileOf } from './waterPlaneMath';
import type { WaterProfile } from './waterPlaneMath';
import type { UndergrowthArea } from './undergrowth';

/** The world's ground height WITHOUT a relief — the flat world of § A1.2, and
 *  the level every height in the payload is measured from. Since E8 the ground
 *  under a point is `Ground.heightAt(x, z)`; this constant is what that answers
 *  where nobody has authored a hill, and it stays the one place that says the
 *  unshaped world lies at zero. */
export const GROUND_Y = 0;

/** How far the base plane reaches beyond `world_bounds`, in metres. The bounds
 *  end at the outermost footprint; a player walking out there must not fall off
 *  the visible world.
 *
 *  Exported because it is where the DRAWN world ends: the backdrop ring closes
 *  the view behind it, and anything else that has to stop exactly there reads
 *  it here. ONE number, one home. */
export const BASE_MARGIN_M = 60;
/** Edge length of the base plane when nothing is placed at all (metres). */
const BASE_FALLBACK_M = 200;
/*
 * THE LIFTS ARE ALL GONE (E4).
 *
 * E3 deleted three ladders at once — a `renderOrder` ladder at −10000 + i, a
 * `polygonOffset` ladder down to −32 and a hairline y ladder of 0.4 mm per
 * level — because the painted grounds became a CUT in the one terrain surface
 * (`scene/layerGround.ts`) and nothing coplanar was left to separate. It left
 * `WATER_DRAPE_LIFT_M = 0.02` standing for the one drape it could not yet
 * replace. E4 replaced it: a water is a MIRROR of its own
 * (`scene/waterPlane.ts`) — flat then, a ruled surface over its profile since
 * W2 — which is not coplanar with the bed under it by construction, because
 * the bed is carved to `h ≤ water_level_at(x, z) − ε`.
 * There is no lift left in this file, and no drape.
 */

/** Mask tiles asked for in ONE request — the server's own
 *  `terrain_layers.BATCH_MAX`. Far below the height batch's 64 because one mask
 *  tile is 384 kB of raw bytes against a height tile's 130 kB, and a tile that
 *  has to be baked from cold costs about a second. A client that wants more
 *  asks twice, which is what this loop does. */
const LAYER_BATCH_MAX = 16;

/** Fallback tuft size when a scatter entry names no model — HIP-HIGH next to a
 *  1.70 m figure, not knee-high (finding 2 of the E8 acceptance round: the old
 *  0.55 m / 0.16 m tuft read as moss from eye level). ONE place for the two
 *  numbers. */
const TUFT_RADIUS_M = 0.22;
const TUFT_HEIGHT_M = 0.8;

// How tall a scattered MODEL stands is `scatterTargetH` in `scatterLod.ts`:
// authored height, else the prop's own library height, else the flat
// fallback. It lives there because it is pure arithmetic that the smoke can
// load — this file imports three.js and cannot be.
//
// THE AUTOMATIC UNDERGROWTH IS NOT BUILT HERE ANY MORE (2026-08-16). It used
// to be a third layer of every painted area, sampled over the whole shape and
// capped at 20 000 instances — which on a square-kilometre wood WAS the
// density and left the ground bare. It is now grown per 64 m cell around the
// anchor, in `scene/undergrowth.ts`; this file only feeds that field the
// shapes, the anchor and the LOD beat.

/**
 * THE BASEMENT HOLE (moved here from `main.ts` with E4 task 3).
 *
 * A storey below ground lies UNDER the world's ground, so looking into a
 * cellar means taking the ground away over that location's footprint. The grid
 * world had one plane to cut and the patch sat on it; the metre world's ground
 * is a base plane PLUS every painted area, and each one of them would roof the
 * cellar on its own — so the patch belongs to the module that owns them all.
 *
 * Same shader technique as the room clip (@anima/scene-render `clip.ts`), just
 * inverted: INSIDE the rectangle the fragment is discarded. The two uniform
 * objects are shared by every ground material, so the frame hook steers the
 * hole per frame without a single recompile.
 */
const holeRect = { value: new THREE.Vector4(0, 0, 0, 0) };  // minX, minZ, maxX, maxZ
const holeOn = { value: 0 };

/** The cache key this patch contributes. Exported so the smoke can pin the
 *  COMBINED key without carrying a copy of the string. */
export const HOLE_CACHE_KEY = 'ground-hole';

/** Materials that already carry the hole test. The patch CHAINS onto whatever
 *  sits in the slot, so applying it twice would declare `vHoleWorld` twice and
 *  the shader would not compile — the old assignment was idempotent only by
 *  accident, and the guard keeps the promise the assignment used to make. */
const holePatched = new WeakSet<THREE.Material>();

/**
 * Give a ground material the hole test.
 *
 * CHAINED, never assigned. A painted water area arrives here with the ripple
 * patch of `surfaceMaterial` (@anima/scene-render `materials.ts`) already in
 * `onBeforeCompile`, and an assignment threw it away: one slot, two writers,
 * last one wins. That is why painted lakes lay dead still while scene floors,
 * tile plates and the admin previews rippled — the water shader was built and
 * then overwritten one line later. So the previous callback runs FIRST (water
 * ripple, tint, roughness mask, sky fresnel), the hole discard after it; the
 * two touch different anchors and different varyings.
 *
 * The cache key is COMBINED for the same reason: three keys the compiled
 * program on this string, so a rippling ground area and a matte one must not
 * answer with the same key.
 */
export function patchHole(mat: THREE.Material): void {
  if (holePatched.has(mat)) return;
  holePatched.add(mat);
  const prev = mat.onBeforeCompile;
  // three's DEFAULT `customProgramCacheKey` returns `onBeforeCompile.toString()`
  // — only a patch that declared a key of its OWN (water: 'anima-water') is
  // worth carrying. Read here, before the slot below is overwritten.
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    shader.uniforms.uHole = holeRect;
    shader.uniforms.uHoleOn = holeOn;
    shader.vertexShader = `varying vec3 vHoleWorld;\n${shader.vertexShader}`
      .replace('#include <project_vertex>',
        '#include <project_vertex>\n\tvHoleWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
    const head = 'uniform vec4 uHole;\nuniform float uHoleOn;\nvarying vec3 vHoleWorld;\n';
    const test = `
  if ( uHoleOn > 0.5 &&
       vHoleWorld.x > uHole.x && vHoleWorld.x < uHole.z &&
       vHoleWorld.z > uHole.y && vHoleWorld.z < uHole.w ) discard;
`;
    const body = head + shader.fragmentShader;
    shader.fragmentShader = body.includes('#include <clipping_planes_fragment>')
      ? body.replace('#include <clipping_planes_fragment>', `${test}\n#include <clipping_planes_fragment>`)
      : body.replace('void main() {', `void main() {\n${test}`);
  };
  // One cache key per PATCH COMBINATION: ground materials differ in maps and
  // colours, not in the patch, and three.js keys the compiled program on this
  // string PLUS the material's own defines.
  mat.customProgramCacheKey = () => (prevKey ? `${prevKey}+${HOLE_CACHE_KEY}` : HOLE_CACHE_KEY);
}

/**
 * THE WIND (terrain animations, task 2).
 *
 * What a ground GROWS may bend: a terrain kind declares `meta.sway_m`, the
 * maximum sideways deflection of a blade's TIP in metres (§ A9), and every
 * scatter entry of an area of that kind sways — the built-in tufts as much as
 * the loaded models. HOW it bends is not authored and never will be: frequency
 * and wind direction are these two constants, because a catalog of wind
 * settings is a wind machine, not a meadow.
 *
 * WHAT bends by how much IS authored, on the second axis: each prop of the
 * library carries a `sway_factor` (0..1, default 1) that the payload puts on
 * the scatter entry, and the effective amplitude is the product of the two
 * (`scatterSway`). The kind answers "how hard does it blow here", the prop
 * "how much do I move in it" — a boulder set to 0 stands still in the very
 * meadow whose ferns bend fully.
 *
 * The deflection grows QUADRATICALLY with the height above the ground and is
 * measured against `uSwayRef`, the prop's own height — so the foot stands
 * still, the tip carries exactly `sway_m`, and an 8 m tree bends as far at its
 * crown as a tuft does at its blade instead of 100 times as far. That is why
 * the reference is a per-material uniform and not a constant: it is the one
 * number that differs between a tuft and a tree, and it must not split the
 * compiled programs.
 */
const SWAY_SPEED = 1.7;
/** A unit vector, so `sway_m` really is metres — the instanced branch of the
 *  shader divides it by the instance's own scale for exactly that reason (see
 *  `applySway`). WORLD-fixed: the instance's own yaw is rotated out below,
 *  otherwise every blade would bend along its own turn and a field would look
 *  combed rather than blown. */
const SWAY_DIR: [number, number] = [0.8, 0.6];
/** Mirror of the server clamp (`terrain_types.SWAY_MIN/MAX`) — the client
 *  never trusts a number it did not clamp itself; a hand-edited row must not
 *  shear a meadow off its ground. */
const SWAY_MIN_M = 0.01;
const SWAY_MAX_M = 0.5;

/** The cache key this patch contributes, without its amplitude. Exported so
 *  the smoke can pin the combined key without carrying a copy of the string. */
export const SWAY_CACHE_KEY = 'ground-sway';

/** The key of ONE amplitude: the deflection is a GLSL literal, so two values
 *  are two programs — and two areas of the same kind are one. Quantised to the
 *  two decimals the catalog stores, which is what keeps that number small. */
export function swayCacheKey(swayM: number): string {
  return `${SWAY_CACHE_KEY}@${swayM.toFixed(2)}`;
}

/** Materials that already bend. Same guard as `holePatched`, same reason: the
 *  patch CHAINS, so applying it twice would declare its locals twice. Note the
 *  consequence: an amplitude change requires a NEW material — the guard
 *  silently ignores re-patch attempts on one that already bends. */
const swayPatched = new WeakSet<THREE.Material>();

/**
 * Let a scatter material bend in the wind.
 *
 * CHAINED, never assigned — the rule the hole patch had to learn (see
 * `patchHole`): one slot, and whoever assigns into it throws away what the
 * previous writer built. Nothing in the scatter path patches before this
 * today, and that is exactly why the discipline has to be in the code and not
 * in the caller's memory.
 *
 * `refH` is the height of the GEOMETRY, i.e. the object-space y at which the
 * deflection reaches `swayM`. A value that says nothing (no model height yet)
 * falls back to one metre rather than dividing by zero. Together with the
 * scale division in the instanced branch below that is the whole of the § A9
 * promise: whatever an instance is scaled to, the tip of it moves `sway_m`
 * metres and no more.
 *
 * The whole displacement rides on `#include <begin_vertex>`: `transformed` is
 * still in OBJECT coordinates there and the geometry is grounded (B16), so its
 * y IS the height above the ground — no varying, no second anchor. A missing
 * anchor (a three upgrade) simply leaves the prop standing still.
 *
 * Known limitation: the displacement happens in the vertex shader, so the
 * bounding sphere three culls against does NOT know about it. A prop deflected
 * by up to `swayM` (≤ 0.5 m) can therefore pop at the screen border when its
 * unbent bounds leave the frustum — the symptom to look for here.
 */
export function applySway(mat: THREE.Material, swayM: number,
                          refH: number): void {
  const amp = Math.round(Math.min(Math.max(swayM, 0), SWAY_MAX_M) * 100) / 100;
  if (!(amp >= SWAY_MIN_M)) return;
  if (swayPatched.has(mat)) return;
  swayPatched.add(mat);
  const swayRef = { value: refH > 0 ? refH : 1 };
  const prev = mat.onBeforeCompile;
  // Only a patch with a key of its OWN is worth carrying — three's default
  // returns `onBeforeCompile.toString()`. Read before the slot is rewritten.
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  const key = swayCacheKey(amp);
  const anchor = '#include <begin_vertex>';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    shader.uniforms.uTime = surfaceTimeUniform;
    shader.uniforms.uSwayRef = swayRef;
    if (!shader.vertexShader.includes(anchor)) return;
    // The phase comes out of the instance's own position (`instanceMatrix`
    // column 3 is its translation), so every blade of one field starts
    // somewhere else in the same wave — no second attribute, and it survives
    // every tier swap because the matrices are never rewritten. Without
    // instancing there is one prop and no phase to spread.
    // The hash degrades in float32 far from the origin: at ~1 km the dot
    // product is around 1e5, where consecutive positions no longer separate
    // and the phases start to cluster. Harmless at the world sizes we render.
    // THE AMPLITUDE IS WORLD METRES, AND THE INSTANCE SCALE WOULD EAT THAT.
    // `transformed` is still in OBJECT coordinates here, so everything written
    // into it is multiplied by the instance's own scale afterwards: a tuft
    // scaled to 1.27 of its geometry (the automatic undergrowth scales every
    // blade to its own height) deflected by 1.27·sway_m, and § A9 promises
    // `sway_m` IS the maximum deflection of the tip. So the direction carries
    // the correction — divided by the instance's uniform scale, read off the
    // length of the matrix's first column, it is no longer a unit vector but
    // the vector that becomes `sway_m` metres AFTER the instance transform.
    // The divisor is exactly 1 for every unscaled user (the authored scatter,
    // whose instances carry rotation and translation only), so nothing that
    // waved before this line existed moves differently now. `max(…, 1e-6)`
    // keeps a degenerate zero-scale instance from dividing by zero.
    const bend = `
  {
    #ifdef USE_INSTANCING
      vec3 swayDir = normalize( ( vec4( ${SWAY_DIR[0]}, 0.0, ${SWAY_DIR[1]}, 0.0 ) * instanceMatrix ).xyz ) / max( length( instanceMatrix[ 0 ].xyz ), 1e-6 );
      float swayPhase = fract( sin( dot( instanceMatrix[ 3 ].xz, vec2( 12.9898, 78.233 ) ) ) * 43758.5453 ) * 6.2831853;
    #else
      vec3 swayDir = vec3( ${SWAY_DIR[0]}, 0.0, ${SWAY_DIR[1]} );
      float swayPhase = 0.0;
    #endif
    float swayUp = pow( max( transformed.y, 0.0 ) / uSwayRef, 2.0 );
    transformed.xz += ${amp.toFixed(2)} * swayUp * sin( uTime * ${SWAY_SPEED.toFixed(2)} + swayPhase ) * swayDir.xz;
  }
`;
    shader.vertexShader = `uniform float uTime;\nuniform float uSwayRef;\n${shader.vertexShader}`
      .replace(anchor, `${anchor}\n${bend}`);
  };
  mat.customProgramCacheKey = () => (prevKey ? `${prevKey}+${key}` : key);
}

/**
 * A loaded prop mesh as a geometry that STANDS on the ground (finding B16).
 *
 * Two things were wrong with handing `mesh.geometry` to the instance as it
 * came out of the file. The placeholder cone it replaces is built with its
 * BASE at y = 0 (`geo.translate(0, h/2, 0)`), while a GLB keeps whatever origin
 * its author chose — a tree modelled around the middle of its trunk therefore
 * sank by half its height, which is the metre the finding reports. And the
 * mesh may sit anywhere INSIDE its file: a prop exported inside a turned or
 * offset node carries that transform on the node, not in the vertices, and an
 * instance only ever takes the geometry.
 *
 * So: bake the mesh's own world matrix within the GLB into a CLONE, then lift
 * the clone until its lowest point is 0. The clone is essential — `loadGlb`
 * CACHES the loaded file, and every other user of that prop (a placement in a
 * scene, a second area scattering the same tree) would inherit a mutation.
 * `updateWorldMatrix` only recomputes matrices from what the nodes already
 * say, so the cached asset is read, never changed.
 *
 * How far to lift, and how much to scale, is `propGroundFit`
 * (@anima/scene-render) — pure arithmetic on the bounding box, checked with
 * hand-derived numbers in `client3d/scripts/smoke_scatter_math.mjs`.
 */
function groundedGeometry(mesh: THREE.Mesh,
                          targetH: number | null): THREE.BufferGeometry {
  const geo = mesh.geometry.clone();
  mesh.updateWorldMatrix(true, false);
  geo.applyMatrix4(mesh.matrixWorld);
  geo.computeBoundingBox();
  const box = geo.boundingBox;
  if (box) {
    const fit = propGroundFit(box.min.y, box.max.y, targetH);
    if (fit.scale !== 1) geo.scale(fit.scale, fit.scale, fit.scale);
    if (fit.offsetY !== 0) geo.translate(0, fit.offsetY, 0);
    geo.computeBoundingBox();
  }
  geo.computeBoundingSphere();
  return geo;
}

/**
 * How WIDE a prop mesh is, per metre of its own height — the ledger behind the
 * scatter's clearance (user finding 2026-08-20).
 *
 * `max(bboxX, bboxZ) / bboxHeight` of the grounded geometry, i.e. a pure
 * SHAPE fact of the file and therefore independent of the target height any
 * entry scales it to: the fit is uniform (`propGroundFit`), so the width at a
 * planted height `h` is simply `spread · h`. Keyed by URL and module-global,
 * because the very same tree is scattered by every area that names it and by
 * every rebuild of every one of them.
 *
 * A prop nobody has loaded yet is NOT in here, and that is a state and not a
 * gap: the sampler then estimates the width from the height (`scatterClearM`),
 * exactly as the map editor's dot preview must, and the entry is re-sampled
 * once the real measurement lands (`noteSpread`).
 */
const propSpread = new Map<string, number>();

/** How long a measured prop width waits for its neighbours before the areas
 *  are re-sampled (`noteSpread`) — long enough that a wood's files arrive in
 *  ONE batch, short enough that the correction lands while the player is still
 *  walking up to it. */
const SPREAD_RESAMPLE_MS = 250;

/** Read the ledger for the tiers of ONE entry — the WIDEST answer any of its
 *  meshes gave, so the low mesh cannot overhang what the full one respects.
 *  `null` = nothing measured yet (see `propSpread`). */
function spreadOf(urls: readonly string[]): number | null {
  let best: number | null = null;
  for (const url of urls) {
    const s = url ? propSpread.get(url) : undefined;
    if (s !== undefined && (best === null || s > best)) best = s;
  }
  return best;
}

/** One built area: what the scatter LOD needs of it. A painted ground has NO
 *  mesh of its own — since E3 it is a CUT in the one terrain surface
 *  (`scene/layerGround.ts`), and since E5b the one thing that still gets a mesh,
 *  the water mirror, is kept in `waterMeshes` because a mirror is not only ever
 *  a painted area: a room's water FLOOR is one too (§ A19 no. 5). */
interface AreaMesh {
  /** one scatter entry per authored row AND model variant — empty when nothing
   *  grows here (finding B17: the list hangs on the AREA, not on the terrain
   *  type; § B2 addendum: a prop with four meshes is four entries, each holding
   *  the instances the shared formula gave it) */
  scatter: ScatterProp[];
  /**
   * WHAT THE SCATTER IS SAMPLED FROM, kept so it can be sampled AGAIN without
   * rebuilding the ground under it.
   *
   * Since the scatter became a camera WINDOW (2026-08-19, `buildScatter`) it
   * has a second occasion the drapes do not have: the anchor crossing a cell
   * border. Re-cutting the area geometry for that would be earcut plus a grid
   * subdivision of the whole painted shape every 64 m walked — so `rebuildScatter`
   * re-samples out of these three and touches nothing else.
   */
  area: TerrainArea;
  ring: Point2[];
  occluders: Point2[][];
  /** the disposables of THIS area's scatter — its own bag, because the props
   *  are thrown away and rebuilt on their own beat while the drape material in
   *  `areaOwned` stands. */
  scatterOwned: { dispose(): void }[];
}

/**
 * One instanced prop kind of an area, with everything the LOD needs to bin it
 * per instance without rebuilding it.
 *
 * TWO MESHES, ONE INSTANCE LIST. The list of matrices is written ONCE, at
 * build time, and never touched again — it stays as the seed-stable sampler
 * produced it. What the LOD moves per tick is which BUFFER each of those
 * matrices is copied into: the `high` mesh (the full-detail model), the `low`
 * mesh (the cheap one, and the tuft before anything is loaded), or neither.
 * That is the whole difference to the area-wide swap this replaces: a wood is
 * not one distance, so the tree at the player's feet may stand on the full
 * mesh while the far edge of the same wood is thinned out.
 *
 * BOTH BUFFERS ARE ALLOCATED AT BUILD SIZE and never grow: in the worst case
 * every instance of the entry is in one of them, and a realloc inside the tick
 * would be a fresh vertex-buffer upload for a camera that merely walked a
 * metre.
 *
 * ONE MODEL VARIANT, NOT ONE AUTHORED ROW (§ B2 addendum, 2026-08-20). A prop
 * with four active meshes gives its row four of these, each holding the
 * instances the shared formula handed it (`buildScatter`). Everything in here
 * is per-MESH already — two tiers, one tuft, one sphere, one impostor, one
 * download wish — which is why a wood of four kinds of tree costs no second
 * mechanism, only more entries in the list.
 */
interface ScatterProp {
  /** the cheap mesh — the tuft cone at build time, the `low` tier once it has
   *  arrived. It exists from the first frame, because SOMETHING has to stand
   *  where props were placed while the model is still on the wire. */
  low: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>;
  /** the full-detail mesh, created the first time an instance of this entry is
   *  near enough to deserve it (`null` until then, and for ever for an entry
   *  whose two tiers resolve to the same URL — see `hasHigh`). */
  high: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material> | null;
  /** how many instances the sampler placed — the size of every array here */
  baseCount: number;
  /** the instance matrices as built, 16 floats each: the SOURCE both buffers
   *  are filled from, and the reason the phase of the wind survives every
   *  re-bin (`applySway` reads the translation out of `instanceMatrix`, and a
   *  matrix is copied, never rewritten). */
  srcMatrix: Float32Array;
  /** world position of every instance, 3 floats each — the distance the LOD
   *  measures. Kept beside the matrices instead of read out of them per tick:
   *  this is the one array the LOD touches for EVERY instance of EVERY entry
   *  on every tick, and it should be three contiguous floats, not a stride of
   *  sixteen. */
  pos: Float32Array;
  /** what each instance was classed as on the last tick (`InstanceTier`) —
   *  the `prev` the hysteresis of `instanceTier` reads. One byte per instance;
   *  see the type for why it is a number and not a tier string. */
  tiers: Uint8Array;
  /** which buffer each instance was really copied into last tick: 0 = high,
   *  1 = low, 2 = neither. NOT the same as `tiers`: an instance classed high
   *  while the full mesh is still loading is drawn in the low buffer, and it
   *  is this array — the buffer membership — that decides whether a buffer has
   *  to be uploaded again. */
  slots: Uint8Array;
  /** bounding sphere over ALL instances of the entry, padded by the prop's own
   *  height. TWO jobs, both of which the per-instance geometry needs:
   *  three.js culls the instanced mesh against it (its own lazy computation
   *  would measure whatever `count` happened to be at the time and then keep
   *  that answer for ever), and the tick asks it first — an entry whose
   *  NEAREST possible instance is beyond the cull is hidden whole, without
   *  looping over its instances at all. */
  sphere: THREE.Sphere;
  /** the whole entry is currently hidden by that sphere test, so a tick that
   *  finds it hidden again does nothing at all */
  hidden: boolean;
  /** the area is gone (`clearAreas`) — the mark a pending `loadGlb` reads
   *  before it writes into a mesh that is no longer in the scene */
  disposed: boolean;
  /** tier URLs from the payload (`{}` when the answer carried none) */
  variants: Record<string, string>;
  /** the authored, canonical URL — what is loaded when `variants` is empty */
  model: string;
  /** the two resolved URLs, computed once at build: the payload's variants do
   *  not change while the area stands, so resolving them per tick would be the
   *  same string every second. */
  loUrl: string;
  hiUrl: string;
  /** the entry really HAS two meshes — a full URL that differs from the low
   *  one. `false` for the built-in tuft (no model at all) and for a prop
   *  without a `low` variant, where `pickVariant` falls back to the full mesh:
   *  both are ONE representation, drawn in the low mesh whatever the tier
   *  says, and a second InstancedMesh holding the same geometry would be a
   *  second draw call for nothing. */
  hasHigh: boolean;
  /** target height for `groundedGeometry`, already defaulted */
  targetH: number;
  /** How far THIS prop bends in the wind, in metres — the area kind's
   *  `meta.sway_m` times the entry's own `sway_factor` (`scatterSway`), or 0.
   *  The weather hangs on the area, the share on the prop, so a boulder can
   *  stand still in a meadow whose ferns bend fully. It is kept here because
   *  `mountUrl` has to bend the material of every mesh it mounts. */
  sway: number;
  /** area centre, handed to `loadGlb` so the download queue serves the props
   *  the camera is looking at first */
  near: THREE.Vector3;
  /** the URL each of the two meshes has been ASKED for. It is the wish and the
   *  "already requested" mark in one, so a tick that comes round again does
   *  not queue the same file a second time; a load that fails hands it back
   *  (see `abandon`), which is what lets a later approach retry. */
  wantLow: string;
  wantHigh: string;
  /** the URL each mesh really stands on (`''` = the tuft / nothing mounted).
   *  What the performance readout counts, because a wish is not a picture. */
  shownLow: string;
  shownHigh: string;
  /** the grounded geometry CLONE per tier URL — ours, and disposed with the
   *  area. Kept per tier instead of thrown away on every swap: there are two
   *  of them at most, the hysteresis makes swaps rare, and re-deriving one
   *  means re-uploading a vertex buffer for a mesh we already had. */
  owned: Map<string, THREE.BufferGeometry>;
  /** the FAR half of the entry: its billboards beyond the cull line
   *  (`scene/impostors.ts`). `null` until an instance of the entry really
   *  stands out there AND the bake has landed — an entry nobody has looked at
   *  from a distance never allocates one, and one whose prop cannot be baked
   *  never will. */
  impostor: ImpostorLayer | null;
  /** the material each loaded tier is drawn with — ALWAYS a CLONE of the GLB's
   *  own, ours, and freed with the area. Patching the cached material would set
   *  every scene that ever placed this prop waving and dissolve it in the
   *  camera corridor; the wind alone used to spare a still prop that clone, the
   *  corridor fade patches every scatter material and no longer can. */
  mats: Map<string, THREE.Material>;
}

/**
 * The billboards of ONE scatter entry — the entry's far half.
 *
 * It carries NO positions of its own, and that is the whole promise of the
 * stage (§ A9): the matrices are composed per tick out of `ScatterProp.pos`,
 * the very array the meshes are binned from, so a tree crossing the cull line
 * swaps its representation exactly where it stood.
 *
 * NO `slots` LEDGER EITHER, unlike every other layer here. The others upload
 * their buffer only when the SET of drawn instances changed; a billboard turns
 * with the camera, so its matrix is different whenever the camera moved at all
 * and there is nothing a ledger could save. What keeps that affordable is the
 * beat: this is the 1 Hz LOD tick, not a frame hook.
 */
interface ImpostorLayer {
  mesh: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>;
  /** the quad this entry's billboards are drawn on, in world metres — derived
   *  once from the entry's target height and the bake's frame */
  quad: ImpostorQuad;
  /** the whole layer is switched off by its sphere test, so a tick that finds
   *  it off again does nothing at all */
  hidden: boolean;
}

/** The ground at ONE world point, as `typeAt` reads it out of the payload —
 *  the client's half of `terrain_query.entry_at`. */
export interface TerrainPoint {
  /** the kind of the topmost area, or the world's default kind */
  kind: string;
  /** catalog `passable`; a kind without a catalog entry is walkable */
  passable: boolean;
  /** catalog `speed_factor`; a kind without an entry walks at 1 */
  speed_factor: number;
  /** catalog `meta.move_anim`, or `''` — the clip a moving figure plays here */
  move_anim: string;
  /** catalog `meta.idle_anim`, or `''` — the clip a STANDING figure plays
   *  here instead of its own standing one (`treading-water` on water) */
  idle_anim: string;
  /** catalog `meta.move_sink_m`, or 0 — how deep the figure stands IN this
   *  ground while it MOVES over it, in metres */
  move_sink_m: number;
  /** catalog `meta.idle_sink_m`, or 0 — the same while it WAITS on it. Two
   *  numbers, because the two poses hang differently in the water (§ A9). */
  idle_sink_m: number;
  /**
   * The MIRROR HEIGHT over THIS POINT in world metres, or `null` where the
   * point is not water (E4, § G4; local since W2).
   *
   * It is the AREA's own PROFILE evaluated here (`waterLevelAt` on
   * `meta.water_profile`), not the kind's number and not the area's mid level:
   * two lakes in one world stand at two heights, the same `water` kind paints
   * both, and a river's mirror is a different height at every metre of its
   * length. A swimmer's float height reads this, so reading the mid level
   * would put him 2.4 m over his own bed at one end of the river and 2.4 m
   * under it at the other.
   *
   * It rides here because it is decided by the very same loop as the kind —
   * the last containing area wins, and if that one is a sandbank painted over
   * the lake, the point is not water any more.
   */
  water_level: number | null;
}

export interface Ground {
  /** everything this module owns, in one group the caller adds to the scene */
  readonly group: THREE.Group;
  /**
   * Bring the ground up to date. `sig` is `WorldMap.terrain_sig`; the fetch
   * happens on the first call and afterwards only when the signature differs.
   * `bounds` is `WorldMap.world_bounds` — a changed frame rebuilds the base
   * plane alone, the areas are untouched by it.
   *
   * `locations` are the worldmap rows, handed in for their FOOTPRINTS: nothing
   * is scattered inside a placed location (finding B18). They are a second
   * rebuild trigger of their own, because moving a place does NOT change
   * `terrain_sig` — without that trigger the trees stood inside a freshly
   * placed building until the next reload.
   *
   * THE KNOWLEDGE FILTER ON THAT LIST IS DELIBERATE (review ruling, rounds
   * 3+4). The payload carries only the places the avatar knows, so an
   * undiscovered location is not in `locations` and its ground gets scattered
   * like any other. That is the RIGHT way round: a clearing in the wood
   * exactly the size of a building would announce a place the player has not
   * found yet. The props correct themselves the moment the place is discovered
   * (the row arrives, the signature moves, the area re-samples), and a few
   * trees standing where a building then appears is the cheaper of the two
   * wrongs. Never "fix" this by fetching the unfiltered list.
   *
   * Resolves to `true` when something was rebuilt. Never throws: a ground that
   * could not be fetched leaves the previous one standing (and the very first
   * failure leaves the base plane in the default look), because a client that
   * tears its world down over one failed poll is worse than a stale one.
   */
  sync(sig: string, bounds: WorldBounds | null,
       locations: readonly MapLocation[], heightSig: string): Promise<boolean>;
  /**
   * WHERE the fine height tiles are needed, in world metres (§ A16.3).
   *
   * The relief is delivered twice since v2: one coarsenable overview for the
   * whole world, and 256 m tiles at the server's fine step around wherever the play
   * is. This is that "wherever" — the avatar's position while the player is in
   * control of it, the point the camera looks at otherwise (`main.ts`, which
   * computes both anyway).
   *
   * CHEAP TO CALL and meant to be called on a tick: it does nothing at all
   * until the anchor crosses into another tile, and then it starts ONE batch
   * fetch in the background. Nothing waits for it — the ground under the point
   * is drawn from the overview until the tiles land and is re-draped then.
   */
  setHeightAnchor(x: number, z: number): void;
  /**
   * The world's ground height at a point (§ A16), in metres — THE one answer.
   *
   * Since "Ein Boden" E2 there is no second one. It is the bilinear reading of
   * the data (`@anima/scene-render` `heightAt`: finest loaded tile, else
   * overview), which is at once
   *
   *  - what the SERVER judges a walk by (`heightfield.world_height` →
   *    `POST /play/pos`), so the client's mirror of the slope rule predicts
   *    the same refusals;
   *  - what the PICTURE is built from — the CDLOD terrain fetches this very
   *    lattice in its vertex shader (`scene/terrainLod.ts`), asserted equal to
   *    1e-4 in `smoke_terrain_lod.mjs`;
   *  - and what every figure, prop, tuft and marker stands on.
   *
   * It used to be two functions (`heightAt` for the drawn triangles,
   * `fieldHeightAt` for the field) that differed by up to 2.433 m on the live
   * world. 0 until the field has arrived, and 0 for ever in a world nobody has
   * shaped — the flat world is a relief like any other, it just happens to be
   * level.
   */
  heightAt(x: number, z: number): number;
  // `maxHeightIn` and `heightRangeIn` — the highest ground inside a world
  // rectangle and how much it moves there — went with the veil (contract v6
  // Nr. 8): they existed to hang the fog quads and to decide which of them was
  // worth tiling, and nothing else ever asked. The primitives behind them went
  // with them (`maxCompositeHeightIn`/`compositeHeightRangeIn` in
  // `@anima/scene-render`) rather than staying as dormant code; a future fog
  // round writes them against the field it actually needs.
  /**
   * Where a pointer ray meets the ground, or `null` when it misses.
   *
   * The click-to-walk goal used to be read against a horizontal plane at the
   * figure's own height, which on a slope puts the goal metres away from the
   * pointer (at 40° and a flat camera angle: 7-14 m). Then it was a raycast
   * against the one big drawn plate — which since E2 does not exist, and could
   * not be trusted if it did: the CDLOD terrain's triangles change with the
   * camera, so the same pixel would answer a different goal at a different
   * zoom. It is solved ANALYTICALLY against the field instead
   * (`rayGroundHit`), which is the same surface `heightAt` describes and the
   * same one the server will judge the walk on.
   *
   * Costs a march at the lattice step plus a bisection — a few hundred
   * bilinear reads for a click, and nothing at all per frame.
   */
  groundPointAt(ray: THREE.Raycaster): THREE.Vector3 | null;
  /** Counts how often the RELIEF was taken over — a signature of its own,
   *  because the field arrives long after the first picture is built, and
   *  everything drawn off it (the minimap's shading, the travel line) has to
   *  know that it moved. */
  heightRevision(): number;
  /** The OVERVIEW height field itself (§ A16), for readers that DRAW the
   *  relief instead of standing on it — the minimap shades it. `null` until
   *  the first field has arrived. Everything that asks how high the ground is
   *  at a point uses `heightAt`/`fieldHeightAt` instead: those go through the
   *  fine tiles, and this deliberately does not. */
  heightField(): WorldHeightField | null;
  /**
   * Re-decide the level of detail of the prop scatter for a camera position:
   * resolution tier, thinning and the far cull, PER INSTANCE.
   *
   * Called by the 1 Hz LOD tick of `main.ts`, which drives the model tiers of
   * the buildings and the figures from the same beat. The scatter's own
   * distances and its hysteresis live in `scene/scatterLod.ts` — it used to
   * borrow the buildings' far distance for a plain on/off switch, and a wood
   * that vanishes at the line the houses change tier at was never the same
   * question.
   *
   * Every instance is asked at ITS OWN distance since 2026-08-15 and lands in
   * one of the entry's two buffers or in neither. One area used to be one
   * answer, which is the wrong shape for a wood: the trees at the player's
   * feet dropped to the cheap mesh because the far edge of the same wood was
   * 100 m away, and a 300 m meadow was either wholly drawn or wholly gone.
   *
   * THE AUTOMATIC UNDERGROWTH RIDES ON THE SAME BEAT (2026-08-15) with its own
   * numbers: no mesh tier to choose, visible to 60 m and thinned from 30 m,
   * none of it settable — a knee-high tuft is out of the picture long before
   * the props are. It is binned per CELL of its own raster since 2026-08-16
   * (`scene/undergrowth.ts`), which is a window around the anchor and not a
   * list of painted shapes.
   *
   * AND SO DOES THE FAR HALF (2026-08-15): beyond the cull distance an entry
   * with a model is drawn as billboards out to 400 m (`scene/impostors.ts`),
   * on the very positions its meshes stand on. That stage is asked FIRST in
   * `binProp`, because the entry-wide early-out that switches a distant wood
   * off is exactly the case its billboards exist for.
   */
  tickScatterLod(cameraPos: THREE.Vector3): void;
  /**
   * The three detail distances the player set (`game/prefs.ts`, localStorage).
   *
   * A LOCAL view setting, so it comes in from the HUD rather than from the
   * server, and it takes effect AT ONCE: the instances are re-binned against
   * the camera of the last tick instead of waiting up to a second for the next
   * one — a settings field that only answers on the next beat reads as broken.
   */
  setScatterLod(cfg: ScatterLodCfg): void;
  /** One sample per DRAWN scatter mesh for the performance readout's tier
   *  split (`game/perfstats.tierCounts`): the tier URLs of the entry and the
   *  URL that mesh really stands on (`''` while the placeholder tuft stands).
   *  Up to TWO per entry since the per-instance binning — the full and the
   *  cheap mesh of one wood are drawn at the same time, and a readout that
   *  counted one of them would miss exactly the load it exists to show. */
  scatterTiers(): { variants: Record<string, string>; url: string }[];
  /**
   * Cut a rectangle out of the ground so one can look into a basement, or
   * `null` to close it again (world metres, `[minX, minZ, maxX, maxZ]`).
   *
   * Steered per FRAME by `main.ts` — the hole grows towards the viewer while a
   * storey below ground is displayed — which is why it writes shared uniforms
   * instead of touching materials: nothing recompiles.
   *
   * The prop scatter is deliberately NOT cut: a tuft is an object standing on
   * the ground, not the ground, and a location with a cellar is a building
   * whose footprint scatters nothing in the first place.
   */
  setHole(rect: [number, number, number, number] | null): void;
  /** The terrain as delivered, or null before the first successful fetch.
   *  The minimap paints the same areas from this. */
  payload(): TerrainPayload | null;
  /**
   * WHAT GROUND is at that world point — the client's mirror of
   * `app/core/terrain_query.entry_at`, and the ONE reading behind every
   * terrain question the walk asks: topmost painted area wins, unpainted is
   * the default kind, a kind the catalog does not know is walkable at normal
   * speed. The same holds while the terrain is still loading — a wall that is
   * not there beats a world one cannot walk in.
   *
   * It answers for the GROUND, not for the world. `passable` judges the
   * WILDERNESS only (footprint wins, § A15), `speed_factor` and the two clip
   * keys count everywhere (finding 3). The rules that combine each with the
   * footprint live in `game/walk.ts` (`terrainBlocks`, `terrainPace`,
   * `moveClip`, `idleClip`) and every caller goes through them — never
   * through this answer alone.
   */
  typeAt(x: number, z: number): TerrainPoint;
  /** May the avatar STAND on that point, as far as the ground is concerned —
   *  `typeAt(x, z).passable`, kept as its own name because that is what the
   *  blocking predicates read. */
  passableAt(x: number, z: number): boolean;
  /** Counts rebuilds — a cheap "has the ground changed" for redraw signatures. */
  revision(): number;
  /** How many quadtree pieces the terrain drew in the last frame. */
  terrainNodeCount(): number;
  /** DIAGNOSTIC: three.js' frozen instance cap vs the buffer capacity. */
  terrainInstanceCap(): { cap: number; capacity: number };
  /** How many NON-DEGENERATE triangles those pieces cost
   *  (`TerrainLod.triangleCount`). */
  terrainTriangleCount(): number;
  /** How many FINE height tiles (§ A16.3) are held right now. */
  heightTileCount(): number;
  /** The CDLOD terrain's own material, for the isolation panel's wireframe
   *  test — `null` while the placeholder is still standing. */
  terrainMaterial(): THREE.Material | null;
  /** Freeze the terrain's quadtree selection (`TerrainLod.setFrozen`). */
  setTerrainFrozen(on: boolean): void;
  /** Draw every selected terrain node, frustum or not
   *  (`TerrainLod.setCullOff`, the isolation panel's toggle 20). */
  setTerrainCullOff(on: boolean): void;
  /** What the last terrain selection culled (`TerrainLod.cullStats`). */
  terrainCullStats(): TerrainCullStats;
  /**
   * THE SCENE OBJECTS PER ISOLATION CATEGORY (`debug3d.ts`, toggles 11-13
   * and 17) — rebuilt on every call, never a live array: the scatter entries
   * and their impostor layers come and go with the LOD window, and a list
   * handed out once would soon name meshes that are no longer in the scene.
   *
   * Only for the debug panel. Nothing in the game reads it.
   */
  debugParts(): {
    terrain: THREE.Object3D[];
    water: THREE.Object3D[];
    undergrowth: THREE.Object3D[];
    scatter: THREE.Object3D[];
  };
  dispose(): void;
}

/** Bounding box of a ring: `[minX, minZ, maxX, maxZ]`.
 *
 *  Takes the CLEANED ring of `buildAreaGeometry`, never the raw payload
 *  polygon: one non-finite corner would make every bound NaN, and NaN fails
 *  quietly here — the scatter would find no point inside its own box and the
 *  LOD would compare a NaN distance, both of which just look like "no props". */
function ringBounds(polygon: Point2[]): [number, number, number, number] {
  let minX = Infinity; let minZ = Infinity; let maxX = -Infinity; let maxZ = -Infinity;
  for (const [x, z] of polygon) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  return [minX, minZ, maxX, maxZ];
}

/** Channels that have already had their say — see `warnOnce`. */
const warnedChannels = new Set<string>();

/** Say it ONCE per channel and never again. What this file refuses is
 *  invisible from the outside — a dropped height tile reads exactly like flat
 *  ground — so the log is the only place it can still be noticed, and a line
 *  per poll would bury it. The server warns once on the same endpoint for the
 *  same reason (`routes/play.py`). */
function warnOnce(channel: string, message: string): void {
  if (warnedChannels.has(channel)) return;
  warnedChannels.add(channel);
  console.warn(message);
}

/**
 * The scatter list an area declares, read through a check.
 *
 * `meta` is free-form JSON the server passes through, so nothing in the type
 * system guarantees a stored `scatter` has the declared shape — an old area
 * still carries none at all. The server whitelists what it stores
 * (`app/models/terrain._sanitize_scatter_list`); this is the reader's half of
 * the same contract, and anything that is not a list of objects grows nothing.
 */
function readScatterList(area: TerrainArea): TerrainScatterEntry[] {
  const raw = (area.meta as { scatter?: unknown } | undefined)?.scatter;
  if (!Array.isArray(raw)) return [];
  return raw.filter((e): e is TerrainScatterEntry => !!e && typeof e === 'object');
}

/**
 * The MESHES one scatter row may draw — one tier map per active model variant
 * of its prop, the primary one first (§ B2 addendum).
 *
 * `model_variants` is the list the server ships, and it ships it ONLY for a
 * prop that really has more than one variant. Everything else — a single
 * variant, a foreign URL, an old cached answer — is the one `variants` map
 * this reader has always produced, so the list is never empty and the caller
 * has exactly one shape to reason about: `n = maps.length`, and `n === 1` is
 * the whole world as it was before variants existed.
 *
 * The FIRST element of `model_variants` IS `variants` by contract, so the list
 * is taken whole rather than merged with it — reading both would be two names
 * for the primary variant and one chance to disagree.
 */
function readVariantMaps(entry: TerrainScatterEntry): Record<string, string>[] {
  const list = entry.model_variants;
  if (Array.isArray(list)) {
    const maps = list.filter(
      (m): m is Record<string, string> => !!m && typeof m === 'object');
    if (maps.length) return maps;
  }
  return [(entry.variants && typeof entry.variants === 'object')
    ? entry.variants : {}];
}

/**
 * WHICH SURFACE-LIBRARY ENTRY A TERRAIN TYPE WEARS — the type says so, and
 * this reads what it says. Nothing else.
 *
 * It used to be the NAME: `surfaceFor(area.kind, …)` asked the library for an
 * entry called exactly like the terrain kind, so `grass` wore `grass` because
 * of the spelling and for no other reason. A type could never wear
 * `deep_forest`, renaming a library entry undressed every ground using it, and
 * two types could not share one material. The server ships the assignment now
 * (`types[].surface`, § A1.5) and the name match is GONE — no fallback to
 * `kind`, because a fallback is exactly the guess the field exists to replace.
 *
 * A type that names nothing (or that the catalog does not know at all) answers
 * '' — the caller then gets no library entry and the ground falls back to the
 * catalog colour, which is what a kind without a same-named entry did before.
 */
export function surfaceOfType(type: TerrainType | undefined | null): string {
  return String(type?.surface ?? '').trim().toLowerCase();
}

export function createGround(): Ground {
  const group = new THREE.Group();
  group.name = 'terrain-ground';

  let payload: TerrainPayload | null = null;
  let loadedSig: string | null = null;
  let inFlight: Promise<boolean> | null = null;
  let rev = 0;

  /**
   * The world relief (§ A16.3) — the coarse overview plus the fine tiles that
   * have arrived, in the ONE shape both renderers sample (`WorldHeightTiles`).
   *
   * An empty overview means "not yet arrived", which answers a flat world —
   * the same answer a world without a single authored hill gives, and
   * deliberately so: nothing waits for the field, the ground is simply draped
   * again when it lands.
   *
   * MUTATED IN PLACE, never replaced: `heightAt` runs per figure per frame and
   * per texel of the terrain pyramid, and a fresh wrapper object per call
   * would be a few hundred thousand allocations for nothing.
   *
   * `stats`/`mipLevelsM` are the E1 addendum (§ G2): per tile a height span
   * and an exact vertical error bound per mip level. Nothing that STANDS on
   * the ground reads them — they steer the terrain quadtree (which node at
   * which level, and whether its error is worth another split).
   */
  const relief: WorldHeightTiles = {
    tileM: 0, overview: null, tiles: new Map(),
    stats: new Map<string, WorldHeightTileStats>(), mipLevelsM: [],
  };
  /** The server's FINE step in metres (`tile_step_m`) — the lattice every rule
   *  reads and the one the terrain's leaf node is sized from. Held apart from
   *  the overview's own `step_m`, which coarsens with the world. */
  let tileStepM = 0;
  let loadedHeightSig: string | null = null;
  let heightRev = 0;
  /** Every tile the world HAS a ground in (`tiles` of `GET /play/heightfield`).
   *  Not part of `relief`: for the sampler an unindexed tile and an unfetched
   *  one read the same (through the overview), and a second copy of "which
   *  tiles exist" is a state that can go stale. This one steers the loading. */
  let tileIndex: ReadonlySet<string> = new Set<string>();
  /** Where the fine tiles are wanted, in world metres, and which tile that
   *  was in when the want set was last computed (`null` = never). Fed by
   *  `setHeightAnchor` from the client's 1 Hz tick. */
  let anchorX = 0;
  let anchorZ = 0;
  let anchorTile: string | null = null;
  /** True while the tile loader is fetching or rebuilding. `sync` steps aside
   *  for it and it steps aside for `sync` (`inFlight`): both re-cut the areas
   *  and the plate, and two of those at once would have the second clear what
   *  the first has just mounted. Nothing is lost by stepping aside — neither
   *  advances a signature, so the next poll does the work. */
  let tilesBusy = false;
  /** The world frame of the last `sync`, so the tile loader can rebuild the
   *  plate without one being handed to it. */
  let lastBounds: WorldBounds | null = null;
  /** `worldHeightRange` over EVERYTHING held — the overview when it arrives,
   *  widened by each tile batch. Taken once per arrival: it walks every support
   *  point (up to 120 000 of them, § A16) and both readers ask on the poll path
   *  — the ray start when the field lands, the cell size on every single sync.
   *
   *  The tiles have to be in it. A coarsened overview can be missing the 22 m
   *  hill entirely (seven of eight support points per axis are gone at 32 m),
   *  and a ray started under that hill finds nothing — a figure falling back to
   *  the flat world on the very ground it should stand on. It only ever GROWS
   *  within one signature; an evicted tile does not shrink it back, because a
   *  ray that starts too high costs nothing while one that starts too low is
   *  the bug above. */
  let fieldRange = { min: 0, max: 0 };

  /** Has any relief arrived at all — the overview, or at least one tile? */
  const hasRelief = (): boolean => !!relief.overview || relief.tiles.size > 0;

  /**
   * THE ground under a point — bilinear on the data, and the only reading
   * there is ("Ein Boden" E2).
   *
   * It used to have a twin: this one answered the DRAWN surface (the two
   * triangles the base plate had cut its cell into) while `fieldHeightAt`
   * answered the field, and on the live world the two stood up to 2.433 m
   * apart because the mesh budget had coarsened the plate to 64 m cells. The
   * plate is gone; the terrain is now built by sampling this very function in
   * the vertex shader (`scene/terrainLod.ts`), so the surface the player sees,
   * the number the rules read and the number the SERVER reads are one.
   */
  const heightAt = (x: number, z: number): number =>
    (hasRelief() ? worldHeightAt(relief, x, z) : GROUND_Y);

  // THE GROUND HOOK (E8 task 4): a location's tile stands on the ground under
  // its centre, and this is where `scene/tiles.ts` gets that height from. The
  // sampler is a closure over `relief`, so it stays correct across every
  // refetch without anyone re-registering it.
  setWorldGround(heightAt);

  /**
   * THE TERRAIN ITSELF — one instanced patch, a quadtree, and the height taken
   * from the lattice above in the vertex shader (`scene/terrainLod.ts`).
   *
   * It is created once and lives as long as this ground does: what changes is
   * the field it samples (`setField`, on every relief arrival), the rectangle
   * it covers (`setExtent`, when the world frame moves) and the material it
   * wears (`setMaterial`, when the default kind or its texture changes).
   */
  const terrain = createTerrainLod();
  group.add(terrain.mesh);

  /**
   * THE LAYER NOBODY AUTHORED (§ A9), grown where it is seen.
   *
   * It is its own module and its own group because it is not built like
   * anything else here: the painted shapes are one mesh each and stand until
   * the terrain changes, while the undergrowth is a WINDOW of 64 m cells that
   * follows the anchor and re-samples as the player walks. This file feeds it
   * three things and nothing else — the shapes (`setAreas`, on every rebuild),
   * where the play is (`setAnchor`, the height tiles' own anchor) and the LOD
   * beat (`tick`).
   *
   * `heightAt` is handed in so a tuft stands on the DRAWN surface, `applySway`
   * because the wind patch lives here — importing it the other way round would
   * close a cycle between the two modules.
   */
  const undergrowth = createUndergrowthField({
    heightAt, applySway, topLayerAt: topLayerIndexAt });
  group.add(undergrowth.group);

  /** The footprints the scatter keeps clear (finding B18) — drawn outlines in
   *  WORLD metres (`worldFootprints`) — and the signature the areas standing
   *  in the scene were sampled against. `null` means "never built", which is
   *  not the same as "built against no locations at all". */
  let footprints: readonly ScatterFootprint[] = [];
  let builtFpSig: string | null = null;

  /** What the terrain's material was last built for — the default kind and the
   *  layer table, so a poll that changes neither costs no material at all. */
  let baseKey = '';

  /**
   * THE LAYER CUT (§ G3) — the baked masks the terrain material is painted
   * from, and the loader that keeps them under the player.
   *
   * It follows the HEIGHT tiles exactly: same keys, same want set, same
   * radius — one anchor, one window, so the ground's shape and the ground's
   * material can never be sharpened over different squares of the world.
   * `layerFmt` is the format block of the last answer (how the bytes decode);
   * `layerIndexKeys` is which tiles carry anything at all, and everything
   * outside it is bare ground and is never asked for.
   */
  const layerTiles = new Map<string, TerrainLayerTile>();
  let layerFmt: TerrainLayerFormat | null = null;
  let layerIndexKeys: ReadonlySet<string> = new Set<string>();
  let layerSig: string | null = null;
  /** The layer table as one string — part of `baseKey`, because a world that
   *  gains a painted ground gains a slice in the compositor's array and the
   *  program has to be rebuilt for it. */
  let layerKey = '';
  let layersBusy = false;
  const areaMeshes: AreaMesh[] = [];
  /** THE MIRRORS OF THE WORLD (E4; ruled since W2) — one per PAINTED water
   *  area, and there is no second source: a room does not define water any
   *  more (W1 § 6, the zone-water stage is deleted), it merely lies in a
   *  painted one. One list, one builder, one material cache. */
  const waterMeshes: THREE.Mesh[] = [];
  /** Where the camera stood at the last `tickScatterLod` — the scatter LOD's
   *  only piece of view state. A REBUILD needs it too (an area has to come
   *  into the world binned, not with every instance at full detail), and that
   *  runs on the terrain refetch, not on the tick. `null` = no tick yet. */
  let lodCam: THREE.Vector3 | null = null;
  /** The three detail distances in force. The module's DEFAULTS until the HUD
   *  hands the player's own in (`setScatterLod`) — this file must draw a
   *  ground before anything has read `localStorage`, and 35/45/120 is what a
   *  player who never opens the menu plays with anyway. */
  let lodCfg: ScatterLodCfg = SCATTER_LOD_DEFAULTS;
  /**
   * The cells the authored scatter is sampled in — the camera's window
   * (`wantedScatterCells`), recomputed from the anchor and the cull distance.
   *
   * It is STATE and not an argument because two very different occasions read
   * it: the full rebuild (a terrain refetch) and the anchor crossing a cell
   * border, which is the one that happens while the player walks. `scatterSig`
   * is the same set as a string — the anchor moves every tick and the set only
   * every 64 m, and re-sampling a wood on a metre of walking is the cost this
   * comparison exists to avoid.
   */
  let scatterCells: [number, number][] = [];
  let scatterSig = '';
  /** Disposables this module created, split by LIFETIME: the base plane's go
   *  when the frame moves, the areas' when the terrain is refetched. One
   *  shared bag would keep every material of every edit alive until teardown —
   *  and an admin painting terrain refetches this every few seconds. */
  const baseOwned: { dispose(): void }[] = [];
  const areaOwned: { dispose(): void }[] = [];

  function drain(bag: { dispose(): void }[]): void {
    for (const o of bag) o.dispose();
    bag.length = 0;
  }

  const catalog = new Map<string, TerrainType>();

  function rebuildCatalog(): void {
    catalog.clear();
    for (const t of payload?.types ?? []) {
      if (t?.kind) catalog.set(t.kind.toLowerCase(), t);
    }
  }

  /** Fallback fill of a kind: the catalog colour, else the neutral grey the
   *  server itself uses for a kind without one — ONE constant per app
   *  (`TERRAIN_FALLBACK_COLOR`, the minimap's copy of the server's
   *  `terrain_types.DEFAULT_COLOR`). NEVER a palette of our own — the ground
   *  is data. */
  function kindColor(kind: string): string {
    return catalog.get((kind || '').toLowerCase())?.color || TERRAIN_FALLBACK_COLOR;
  }

  /** How far what grows on a kind bends, in metres — `meta.sway_m` (§ A9), or
   *  0 for a ground whose scatter stands still. Clamped like the server
   *  clamps it, because junk in `meta` must cost a still meadow and never a
   *  sheared one. */
  function swayFor(kind: string): number {
    const raw = Number(catalog.get((kind || '').toLowerCase())?.meta?.sway_m);
    if (!Number.isFinite(raw) || raw <= 0) return 0;
    return Math.min(Math.max(raw, SWAY_MIN_M), SWAY_MAX_M);
  }

  /** How much grows on a kind ALL BY ITSELF — `meta.undergrowth` (§ A9), 0 for
   *  a ground nobody said anything about. The clamp is the client's own, like
   *  every number that arrives over the wire; `undergrowthDensityPer100m2`
   *  clamps it a second time, and neither of them trusts the other. */
  function undergrowthFor(kind: string): number {
    const raw = Number(catalog.get((kind || '').toLowerCase())?.meta?.undergrowth);
    if (!Number.isFinite(raw) || raw <= 0) return 0;
    return Math.min(raw, 1);
  }

  /** The surface-library id of a terrain kind — the catalog entry's own
   *  answer (`surfaceOfType`), '' for a kind that names none or that the
   *  catalog does not know. THE one place a kind becomes a material here. */
  /** WHICH library entry a ground kind wears. The terrain TYPE's own answer
   *  first (`surfaces` of the catalog) — and where the catalog does not know
   *  the kind at all, THE KIND CARRIES ITSELF, which is the server's own rule
   *  for a ROOM FLOOR (§ A19 no. 4: `surfaces.floor` is a library id directly).
   *  A zone water's `kind` arrives that way, and without this it would have
   *  looked up nothing and come out as a matte plane instead of water. */
  function surfaceOf(kind: string): string {
    const key = (kind || '').toLowerCase();
    const named = surfaceOfType(catalog.get(key));
    return named || (key && hasSurfaceTexture(key) ? key : '');
  }

  /**
   * Material of one ground kind.
   *
   * Texture first (the surface-texture library the tiles already feed), the
   * catalog colour second. WHICH library entry is asked for is the TYPE's
   * answer, never the kind's spelling (`surfaceOf`) — a kind that names no
   * surface gets no texture and keeps its colour. The lookup goes through the
   * `'wall'` chain: `surfaceFor(id, 'floor')` would fall back to the global
   * indoor `floor` kind, which is the wrong ground for a painted meadow — the
   * `'wall'` chain asks for the named entry and nothing else (`tiles.ts`).
   *
   * `uvScaleM` is how many metres one UV unit spans: the shape geometry's UVs
   * ARE the world coordinates (1 unit = 1 m), the base plane's run 0..1 over
   * its whole edge.
   *
   * IT BUILDS TWO KINDS OF THING, and only one of them still carries a
   * texture: the WATER MIRROR (its own shader, its own image, `waterPlane.ts`)
   * and the TERRAIN (`rebuildBase`), which gets NO map at all — its albedo
   * comes out of the layer compositor's texture array. See `applyTerrainLayers`.
   *
   * `draw` is how the surface takes part in the depth buffer, and only the
   * mirror sets it: a lake is TRANSPARENT (the bed shows through its shore
   * ramp) and writes NO depth (it is a sheet over a world that has to stay
   * visible through it). The terrain leaves both alone and stays opaque.
   */
  function materialFor(kind: string, uvScaleM: number,
                       sink: { dispose(): void }[],
                       draw?: { transparent?: boolean; depthWrite?: boolean }
  ): THREE.Material {
    const surface = surfaceOf(kind);
    const lib = surfaceFor(surface, 'wall');
    const spec: SurfaceMaterialSpec | null = surfaceMaterialSpec(surface);
    let map: THREE.Texture | null = null;
    if (lib) {
      // Every piece gets its OWN clone: `repeat` is per mesh, and the cached
      // texture is shared with the tiles.
      map = lib.texture.clone();
      map.needsUpdate = true;
      map.wrapS = THREE.RepeatWrapping;
      map.wrapT = THREE.RepeatWrapping;
      map.repeat.set(uvScaleM / lib.sizeM, uvScaleM / lib.sizeM);
      sink.push(map);
    }
    const mat = surfaceMaterial(THREE, { material: spec, map, color: kindColor(kind),
      transparent: draw?.transparent, depthWrite: draw?.depthWrite });
    // EVERY ground material carries the basement hole — base plane and painted
    // areas alike. Patching only the plane would leave a painted meadow lying
    // over the open cellar.
    patchHole(mat);
    // …and then, on everything that is not water, the natural-ground stages
    // (`scene/naturalGround.ts`): anti-tile, colour patches, height AO. CHAINED
    // after the hole, so the key of an open-world ground reads
    // `ground-hole+natural-ground`.
    //
    // WATER AND ICE STEP ASIDE. Those two arrive from `surfaceMaterial` with a
    // full shader of their own — scrolling normal maps, sky fresnel, roughness
    // mask — and a second sample of the water texture blended into it would
    // fight every one of them. It is the CLASS that decides, never the colour
    // or the kind's name (`isWaterClass`). It also means a painted lake keeps
    // a HARD shore: the soft edge rides on this patch, and water is out of it
    // — a shoreline that dissolved into the meadow behind it would be a bank
    // nobody could see, and the water shader is where a shore would belong.
    if (!isWaterClass(spec?.class)) applyNaturalGround(mat);
    sink.push(mat);
    return mat;
  }

  /** What the base plate has to cover, as `[minX, minZ, maxX, maxZ]`: the
   *  world frame grown by the ground margin, or the fallback square when
   *  nothing is placed at all. */
  function plateExtent(bounds: WorldBounds | null
  ): [number, number, number, number] {
    if (!bounds) {
      const h = BASE_FALLBACK_M / 2;
      return [-h, -h, h, h];
    }
    return [bounds.min_x - BASE_MARGIN_M, bounds.min_z - BASE_MARGIN_M,
            bounds.max_x + BASE_MARGIN_M, bounds.max_z + BASE_MARGIN_M];
  }

  /**
   * The LANDSCAPE under everything — the frame it covers and the look it wears.
   *
   * There is no geometry to build here any more: `scene/terrainLod.ts` places
   * every vertex from the height lattice in its own vertex shader, per frame,
   * at the resolution the camera deserves. What this function still owns is
   * the two things the terrain cannot know — how far the world reaches
   * (`setExtent`) and what the unpainted ground looks like (`setMaterial`).
   *
   * ONE UV UNIT IS ONE METRE, which is what the painted-area drapes have used
   * all along: the base plate used to stretch a single UV span over its whole
   * edge, so a world that grew re-scaled its own grass. The terrain reads its
   * UV from the world position in the vertex shader, so the repeat comes out
   * of the surface library's own `sizeM` and stays put whatever the frame does.
   *
   * The material is rebuilt only when the DEFAULT KIND changes — not on a
   * moved frame, not on a new relief: neither can change what the ground is
   * made of, and a rebuild would recompile a program and re-clone a texture
   * for a picture that does not move.
   */
  function rebuildBase(bounds: WorldBounds | null): void {
    const [wantX0, wantZ0, wantX1, wantZ1] = plateExtent(bounds);
    terrain.setExtent([wantX0, wantZ0, Math.max(wantX1, wantX0 + 1),
                       Math.max(wantZ1, wantZ0 + 1)]);
    const kind = payload?.default_kind || '';
    // The key carries the LAYER TABLE as well, because the terrain's material is
    // no longer about one kind: a world that gains a painted ground gains a
    // slice in the compositor's array, and the program has to be rebuilt for it.
    const key = `${kind}|${layerKey}`;
    if (key === baseKey) return;
    baseKey = key;
    drain(baseOwned);
    // NO MAP, NO COLOUR OF ITS OWN. The albedo is composited from the layer
    // array (`scene/layerGround.ts`); a `map` beside it would switch on the
    // anti-tile stage of `applyNaturalGround`, which would blend the DEFAULT
    // kind's wide sample over every forest in the world. White is the neutral
    // multiplier the compositor writes into.
    const mat = surfaceMaterial(THREE, { material: null, map: null,
                                         color: 0xffffff });
    patchHole(mat);
    applyNaturalGround(mat);
    // LAST IN THE CHAIN AND THEREFORE FIRST IN THE SHADER: every ground patch
    // inserts its body directly after `#include <map_fragment>`, so the one
    // applied last runs first. The compositor writes the albedo, the natural
    // stages then work on what it wrote — the order plan § G3 asks for.
    applyTerrainLayers(mat);
    baseOwned.push(mat);
    terrain.setMaterial(mat);
  }

  /**
   * Deterministic prop scatter of one area — up to TWO InstancedMeshes per
   * entry AND VARIANT (the cheap one from the start, the full one when it is
   * deserved).
   *
   * WHAT GROWS HERE IS THE AREA'S OWN BUSINESS (finding B17). It used to hang
   * on the terrain TYPE, which could only ever say "all forest everywhere
   * grows this one tree"; a wood with two kinds of tree and a clearing without
   * any is one painted shape each, so the list moved to `meta.scatter` of the
   * area. No list, or an empty one, means nothing grows — there is no default.
   *
   * WHERE the instances stand is not decided here: `scatterCellInstances`
   * (@anima/scene-render) is the ONE sampler, and the map editor draws its
   * preview from the very same call. That is the whole point of the shared
   * module — preview and world agree by construction, not by two files being
   * kept in step. Footprints of the placed locations go in with it, so nothing
   * grows inside a building (finding B18), and the rings of the areas stacked
   * ABOVE this one, so only the topmost area of a spot scatters there.
   *
   * A CAMERA WINDOW OF 64 m CELLS, NOT THE WHOLE PAINTED SHAPE (2026-08-19).
   * Sampling a shape meant spending a fixed ceiling of instances over ground of
   * any size, i.e. an effective density proportional to 1/A: the reporting
   * world's 13.71 km2 wood came out at 0.1021 props per 100 m2 and the 0.84 km2
   * wood beside it, authored identically, at 1.4261 — 46 against 645 trees
   * inside the player's own cull radius. Now every cell of the window is filled
   * at the AUTHORED density from its own seed (`scatterCellSeed`) and the
   * area's ring only decides which of those points are this area's, so:
   *
   *   · the density is the density of the GROUND, whatever shape it was
   *     painted in — the two woods above are the same wood to look at;
   *   · what it costs hangs on the WINDOW, not on the world: `(2k+1)^2` cells
   *     of 4096 m2 with k = ceil(cullM / 64), i.e. 25 cells = 102 400 m2 at
   *     the standing 120 m cull distance;
   *   · the same cell always grows the same props, so walking out of a wood
   *     and back into it finds it unchanged.
   *
   * `SCATTER_MAX_PER_CELL` is what a hand-edited density runs into now, and it
   * bites at the same 97.66 props per 100 m2 in every cell of every area —
   * a ceiling can no longer make two woods differ.
   *
   * A ROW IS AS MANY ENTRIES AS THE PROP HAS MESHES (§ B2 addendum, 2026-08-20).
   * A prop may carry several models of the same object; a wood of 14 000 trees
   * built from ONE of them is 14 000 copies of one tree, which is exactly what
   * the variants exist to end. So the sampler is told how many there are
   * (`variantCount`), hands every instance the variant it shows — the one
   * shared formula `(hash(cell seed) + candidate) mod n`, `scatterVariantIndex`
   * — and the points are split into one `ScatterProp` per (row, variant).
   * Everything below is per PROP already (its own tuft, its own two tiers, its
   * own sphere, its own LOD, its own impostor), so a variant is simply another
   * one of them; a prop with a single variant produces the single entry it
   * always produced, down to the same objects in the same order.
   *
   * WHAT IS DRAWN OF IT is not decided here either: the finished entry is
   * handed straight to `binProp` with the camera of the last tick, so a
   * rebuild (a terrain refetch, a new relief, a crossed cell border) comes into
   * the world with the instances the camera deserves RIGHT NOW — and asks for
   * the full-detail mesh of a far-away wood exactly as little as the tick
   * would. Without a camera yet (the very first build) everything is drawn on
   * the cheap mesh until the first tick, which is a second at most and never a
   * bare ground.
   */
  function buildScatter(area: TerrainArea, ring: Point2[],
                        occluders: Point2[][], sink: { dispose(): void }[]
  ): ScatterProp[] {
    const out: ScatterProp[] = [];
    // ONE wind question per area, not per entry: how hard it BLOWS hangs on
    // the KIND of the painted shape (§ A9), so a meadow's tufts and its trees
    // can never disagree about the weather. How much each of them takes part
    // in it is the entry's own `sway_factor` below.
    const sway = swayFor(area.kind);
    // The window's cells, and the box of the ring — the cheap rejection that
    // keeps an area from being asked about the 24 cells it does not reach
    // into. `ringBounds` is the same box the drape was built from.
    const [rMinX, rMinZ, rMaxX, rMaxZ] = ringBounds(ring);
    const cells = scatterCells.filter(([cx, cz]) => {
      const x0 = cx * SCATTER_CELL_M;
      const z0 = cz * SCATTER_CELL_M;
      return rMaxX >= x0 && rMinX <= x0 + SCATTER_CELL_M
        && rMaxZ >= z0 && rMinZ <= z0 + SCATTER_CELL_M;
    });
    if (!cells.length) return out;
    readScatterList(area).forEach((entry, index) => {
      const density = Number(entry.density_per_100m2 ?? 0);
      // An entry WITH a model gets its cone at the height the mesh will have —
      // the cone is that prop's stand-in, and a knee-high one that turns into
      // an 8 m tree is a pop where the sizes could simply agree. Only the
      // built-in tuft (no model at all) keeps the hip-high tuft size.
      const h = entry.model
        ? scatterTargetH(entry.height_m, entry.prop_height_m)
        : (Number(entry.height_m) > 0 ? Number(entry.height_m) : TUFT_HEIGHT_M);
      const model = typeof entry.model === 'string' ? entry.model : '';
      // THE MESHES THIS ROW MAY DRAW (§ B2 addendum). One tier map per active
      // model variant of the prop, the primary one first; a prop with a single
      // variant answers the one map it always did, so everything below runs
      // once and produces the entry it always produced.
      //
      // Only the PRIMARY variant falls back to the authored `model` URL: that
      // is the string the entry names, and the further variants exist only as
      // the tier maps the server resolved for them.
      const kinds = readVariantMaps(entry).map((variants, v) => {
        const fallback = v === 0 ? model : '';
        return {
          variants,
          model: fallback,
          loUrl: pickVariant(variants, 'low') || fallback,
          hiUrl: pickVariant(variants, 'full') || fallback,
        };
      });
      // HOW FAR THIS PROP HAS TO STAY OFF A PLACED LOCATION (finding
      // 2026-08-20): half its own horizontal extent, measured on the loaded
      // mesh at the height it is planted at (`propSpread`) and estimated from
      // that height while no mesh of the entry has landed yet. Read BEFORE the
      // sampling because it is an input to the rejection — it never touches the
      // candidate stream, so a later refinement only ever adds or removes props
      // at the rim of a footprint and leaves every other one where it stood.
      //
      // ONE clearance for the whole ROW, over the meshes of EVERY variant: the
      // sampling happens once and the split comes after it, so a clearance per
      // variant would be a number the stream cannot have. The widest answer
      // wins (`spreadOf`), which is the same rule the two tiers of one mesh
      // already follow — a narrow variant keeps a little more distance from a
      // wall than it needs, a wide one never overhangs it.
      const spread = spreadOf(kinds.flatMap((k) => [k.hiUrl, k.loUrl]));
      const clearM = scatterClearM(h, spread === null ? null : spread * h);
      // ONE BUCKET PER VARIANT, filled in cell order. The bucket a point falls
      // into is the sampler's answer (`variant`), never a count of its own: the
      // formula needs the CANDIDATE ordinal, and only the sampler knows it.
      const buckets: ScatterInstance[][] = kinds.map(() => []);
      for (const [cx, cz] of cells) {
        for (const p of scatterCellInstances({
          ring,
          cx,
          cz,
          densityPer100m2: density,
          seed: scatterCellSeed(area.id, index, cx, cz),
          footprints,
          clearM,
          occluders,
          variantCount: kinds.length,
        })) (buckets[p.variant ?? 0] ?? buckets[0]).push(p);
      }
      // THE one place the two authors of the wind meet (§ A9): the area's
      // amplitude times this prop's factor. Everything downstream — the tuft
      // below, `mountUrl`'s material, the clone-or-share decision — reads this
      // one number off `prop.sway`, so a stone with factor 0 arrives at 0 and
      // takes the existing "no sway, no clone" path without a second rule.
      const entrySway = scatterSway(sway, entry.sway_factor);
      // HOW DEEP THIS PROP STANDS IN THE GROUND (§ A9, ground offset): a fact
      // about the object, shipped on the entry, added to every instance's own
      // ground sample below. Read once per entry — it cannot vary per
      // instance, and asking per instance would only cost.
      const entrySink = scatterGroundOffset(entry.ground_offset_m);
      kinds.forEach((kind, variantPos) => {
        const points = buckets[variantPos];
        // A variant no candidate of this window picked gets no mesh at all —
        // and no download either, which is the point of splitting AFTER the
        // sampling rather than building n meshes and filling them.
        if (!points.length) return;
        const { variants, loUrl, hiUrl } = kind;
        // v1 prop: a low cone in the kind's own colour. A `model` URL is honoured
        // asynchronously below — the tufts stand immediately and are replaced by
        // the mesh when it arrives, so a slow asset never delays the ground.
        const geo = new THREE.ConeGeometry(TUFT_RADIUS_M, h, 5);
        geo.translate(0, h / 2, 0);
        const mat = new THREE.MeshStandardMaterial({
          color: new THREE.Color(kindColor(area.kind)).multiplyScalar(0.75),
          roughness: 0.95,
        });
        // The tuft's material is this entry's own, so it is simply patched —
        // the reference height is the cone's, whose tip is what bends.
        applySway(mat, entrySway, h);
        // …and the corridor between camera and avatar takes it away where it
        // stands in the way (`scene/occlusion.ts`). Chained after the wind, so
        // the key of a swaying tuft reads `ground-sway@x+occlusion-corridor`.
        applyOcclusionFade(mat);
        sink.push(geo, mat);
        // Typed on the BASE classes: `mountUrl` swaps geometry and material for
        // the loaded ones, which are not a cone and not this material.
        const low: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>
          = new THREE.InstancedMesh(geo, mat, points.length);
        // One of each, reused: a big meadow places thousands of instances, and a
        // fresh Vector3 per instance is garbage for nothing.
        const m = new THREE.Matrix4();
        const q = new THREE.Quaternion();
        const up = new THREE.Vector3(0, 1, 0);
        const at = new THREE.Vector3();
        const s = new THREE.Vector3(1, 1, 1);
        // The matrices are kept HERE, not in the mesh: they are the source both
        // instance buffers are filled from per tick, and a mesh's buffer holds
        // whatever the last binning put into it. `pos` is the same translation
        // once more, as three tight floats — see `ScatterProp.pos`.
        const srcMatrix = new Float32Array(points.length * 16);
        const pos = new Float32Array(points.length * 3);
        points.forEach((p, i) => {
          q.setFromAxisAngle(up, p.yaw);
          // EVERY instance samples its own ground (§ A16): the sampler decides
          // where the tuft stands, the scatter only where it stands in XZ. A
          // shared height would float half a wood over the slope it grows on.
          // The props stay UPRIGHT on a slope — a tree grows towards the sky,
          // and tilting one into the surface normal is a look, not a fix.
          // …plus the prop's own sink: the ground under THIS instance is the
          // sampler's answer, the prop's base is that answer plus the offset
          // the library dialled for the object (a trunk without a root ball).
          const y = heightAt(p.x, p.z) + entrySink;
          m.compose(at.set(p.x, y, p.z), q, s);
          m.toArray(srcMatrix, i * 16);
          pos[i * 3] = p.x;
          pos[i * 3 + 1] = y;
          pos[i * 3 + 2] = p.z;
        });
        low.castShadow = false;
        low.frustumCulled = true;
        // Nothing is drawn until the entry has been binned (a few lines below,
        // and every tick after that): a mesh whose buffer holds the matrices of
        // the last camera position must not be shown at the count of the one
        // before it.
        low.count = 0;
        low.visible = false;

        // The sphere over the instances themselves, padded by how tall the prop
        // stands and how far the wind takes it — see `ScatterProp.sphere` for
        // the two jobs it does. Its CENTRE is also what the download queue sorts
        // by (`near`): since the scatter is a camera window, that centre is a
        // stone's throw from the camera, while the painted shape's own centre
        // can be kilometres away in a wood this big — and a queue sorted by
        // that would fetch the far wood's mesh before the one underfoot.
        const sphere = instanceSphere(pos, h + SWAY_MAX_M);
        const prop: ScatterProp = {
          low,
          high: null,
          baseCount: points.length,
          srcMatrix,
          pos,
          // EVERY INSTANCE STARTS AS `low`, and the 1 is the whole point: the
          // hysteresis answers "whatever is already there" inside the 35…45 m
          // band, so the starting value decides what a freshly built entry shows
          // in it. A 0 (full) would download the good mesh for a wood 44 m away
          // that the next tick demotes anyway; a 2 (hidden) would be a DEAD BAND
          // — an entry built at 110.4…120 m would stay invisible, because coming
          // back from hidden needs 0.92·cull, although at that distance it is
          // plainly low and should be drawn.
          tiers: new Uint8Array(points.length).fill(1),
          // …and in NO buffer yet, so the first binning finds every instance
          // changed and uploads both buffers once.
          slots: new Uint8Array(points.length).fill(2),
          // Both meshes share it: they hold subsets of these very positions,
          // and nothing writes into it after this line.
          sphere,
          hidden: false,
          disposed: false,
          variants,
          model: kind.model,
          loUrl,
          hiUrl,
          // A prop whose two tiers resolve to the same file is ONE mesh, and so
          // is a tuft (both URLs empty) — see `hasHigh`.
          hasHigh: !!hiUrl && hiUrl !== loUrl,
          // The authored height wins, the prop's real one governs when none was
          // authored, the flat fallback is the last resort (§ A9).
          targetH: scatterTargetH(entry.height_m, entry.prop_height_m),
          sway: entrySway,
          near: sphere.center,
          wantLow: '',
          wantHigh: '',
          shownLow: '',
          shownHigh: '',
          owned: new Map(),
          mats: new Map(),
          // The far half is grown on demand, by the very tick that finds an
          // instance of this entry beyond the cull line (`binImpostors`).
          impostor: null,
        };
        // THE SPHERE IS SET, NOT COMPUTED, and both meshes of the entry get the
        // same one. three.js would derive it from the instance buffer on the
        // first frustum test and then keep that answer for ever — measured over
        // whatever `count` happened to be at that moment, which after a binning
        // is a subset near the camera. A wood would then be culled by the bounds
        // of the four trees that were drawn when it was first looked at.
        low.boundingSphere = prop.sphere;
        // The tuft stands until the first mesh arrives; a prop with no model at
        // all keeps it forever, and takes part in cull and thinning all the same.
        // NOTHING is downloaded for an entry beyond the cull distance: its
        // instances are not drawn, and a world of far-away woods would otherwise
        // fetch every mesh in it at build time only to hide it. `binProp` is
        // what asks — for this entry, at its own nearest instance.
        if (lodCam) binProp(prop, lodCam);
        else fillAll(prop);
        out.push(prop);
      });
    });
    return out;
  }

  /**
   * The bounding sphere over every instance of an entry, padded by `padM`.
   *
   * `pos` is the x/y/z triple list of `ScatterProp.pos`, and the padding is
   * how far the drawn prop reaches beyond the point it stands on — its height
   * plus the wind. Centre and radius come from the AXIS-ALIGNED box, which is
   * a hair larger than the tightest sphere and costs one pass instead of two.
   */
  function instanceSphere(pos: Float32Array, padM: number): THREE.Sphere {
    let minX = Infinity; let minY = Infinity; let minZ = Infinity;
    let maxX = -Infinity; let maxY = -Infinity; let maxZ = -Infinity;
    for (let i = 0; i < pos.length; i += 3) {
      if (pos[i] < minX) minX = pos[i];
      if (pos[i] > maxX) maxX = pos[i];
      if (pos[i + 1] < minY) minY = pos[i + 1];
      if (pos[i + 1] > maxY) maxY = pos[i + 1];
      if (pos[i + 2] < minZ) minZ = pos[i + 2];
      if (pos[i + 2] > maxZ) maxZ = pos[i + 2];
    }
    const centre = new THREE.Vector3((minX + maxX) / 2, (minY + maxY) / 2,
                                     (minZ + maxZ) / 2);
    const radius = Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2 + padM;
    return new THREE.Sphere(centre, radius);
  }

  /**
   * Mount a URL onto ONE of an entry's two meshes — in place, without touching
   * a single instance matrix.
   *
   * `high` says which mesh is meant, and the full-detail one is CREATED HERE
   * when its file arrives: an entry whose nearest instance never comes inside
   * the far distance never has a second InstancedMesh at all, which is what
   * makes "two meshes per entry" affordable in a world full of distant woods.
   *
   * THE LAST WISH WINS, NEVER THE LAST ANSWER. A load takes as long as it
   * takes; the answer checks the wish again before it mounts, so a file that
   * was superseded while it travelled is filed away (its geometry is derived
   * and kept under its URL) but never shown.
   */
  function mountUrl(prop: ScatterProp, url: string, high: boolean): void {
    if (!url) return;
    if ((high ? prop.wantHigh : prop.wantLow) === url) return;
    if (high) prop.wantHigh = url; else prop.wantLow = url;
    const have = prop.owned.get(url);
    const haveMat = prop.mats.get(url);
    if (have && haveMat) {
      // Been here before — the mount is two assignments and no download.
      place(prop, url, high, have, haveMat);
      return;
    }
    // A LOAD THAT NEVER MOUNTED MUST NOT PIN THE WISH. `wantLow`/`wantHigh` is
    // both the wish and the "already asked" mark, so a failed load would leave
    // the prop wanting a URL it does not have: the early return above then
    // blocks every later request for that mesh for the life of the area — a
    // full mesh that failed once while the low one mounted would never be
    // tried again. So the failing branches hand the field back to what is
    // actually on screen (`''` = the tuft), and only while this load is still
    // the current wish: a newer one owns the field, and last wish wins stays
    // untouched.
    const abandon = () => {
      if (high) { if (prop.wantHigh === url) prop.wantHigh = prop.shownHigh; }
      else if (prop.wantLow === url) prop.wantLow = prop.shownLow;
    };
    // Only the first mesh of the file is used — a prop that is really several
    // meshes is a v2 problem, and a silently missing prop would be worse than
    // a simplified one. `near` puts this download into the distance queue of
    // `propAssets.ts` instead of at its end: the wood being walked into is
    // fetched before the one across the map.
    void loadGlb(url, prop.near).then((obj) => {
      // A terrain refetch between request and answer took this entry out of
      // the scene and disposed it — writing into it would resurrect nothing
      // and hold the loaded mesh alive. The test is the DISPOSED mark
      // `clearAreas` leaves, not the parent: since the build-then-swap a mesh
      // is legitimately parentless for as long as its rebuild takes, and
      // reading that as "gone" would drop the model of every prop whose file
      // arrives before the swap.
      if (!obj) { abandon(); return; }
      if (prop.disposed) return;
      let src: THREE.Mesh | null = null;
      obj.traverse((o) => { if (!src && (o as THREE.Mesh).isMesh) src = o as THREE.Mesh; });
      if (!src) { abandon(); return; }
      const mesh = src as THREE.Mesh;
      // `targetH` is the TARGET height since B17: the prop is scaled until
      // its bounding box is that tall, and grounded either way (B16). The
      // model is never instanced at its file size — that number survived no
      // normalisation (`scatterTargetH`).
      const geometry = prop.owned.get(url) ?? groundedGeometry(mesh, prop.targetH);
      // The mesh is grounded and scaled — so this is the moment its real width
      // is known, and the clearance the scatter keeps from a placed location
      // stops being an estimate (finding 2026-08-20).
      noteSpread(url, geometry);
      // The clone is OURS and nothing else disposes it — the owned bag of
      // this rebuild was drained into `areaOwned` long before this answer
      // arrived (the load is asynchronous, the swap is not). So it rides on
      // the prop and `clearAreas` frees it with the meshes. One per URL, and
      // the map is the ledger of what has to be freed — it covers BOTH tiers
      // of the entry, which is why the two meshes need no ledger of their own.
      prop.owned.set(url, geometry);
      // THE MATERIAL OF A SCATTERED PROP IS ALWAYS A CLONE. `loadGlb` caches
      // the file, so `mesh.material` belongs to every area that scatters this
      // tree and to every scene that places it; patching it here would set them
      // all waving and dissolve a placed tree in a room the moment the player
      // walks past a wood. Until the corridor fade only a SWAYING prop had to
      // be cloned (a still one was patched by nobody); the corridor patch
      // applies to every scatter material, so the shared cache material can no
      // longer be handed out at all. The clone keeps the same cache key, so the
      // extra material costs no extra program.
      // Whatever this URL already has wins, exactly as the geometry above:
      // two loads of one URL can be in flight at once (a band crossed twice
      // while the first was travelling), and a second clone would replace the
      // first in the ledger with nobody left to free it.
      const material = prop.mats.get(url) ?? (mesh.material as THREE.Material).clone();
      // CENTRAL, in the ONE place a tier is mounted: a mount replaces the
      // material of a mesh, so a patch applied anywhere else would be lost the
      // first time an entry loaded its second tier. BOTH meshes of an entry
      // come through here, so both bend — and both open up for the camera.
      applySway(material, prop.sway, prop.targetH);
      applyOcclusionFade(material);
      prop.mats.set(url, material);
      if ((high ? prop.wantHigh : prop.wantLow) !== url) return;  // superseded
      place(prop, url, high, geometry, material);
    }).catch(() => {
      // The tuft stands; a missing prop is not a broken world — but the wish
      // is released all the same, see `abandon`.
      abandon();
    });
  }

  /**
   * Hang a loaded geometry/material pair on one of the entry's meshes.
   *
   * The full-detail mesh is BORN HERE — with the buffer at build size, the
   * shared instance sphere and nothing drawn yet; the very next binning fills
   * it. That binning is done straight away when a camera is known, because
   * otherwise the near trees would keep standing on the cheap mesh for up to a
   * second after their model landed, which is exactly the moment the player is
   * looking at them.
   */
  function place(prop: ScatterProp, url: string, high: boolean,
                 geometry: THREE.BufferGeometry, material: THREE.Material): void {
    if (high) {
      if (!prop.high) {
        const mesh: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>
          = new THREE.InstancedMesh(geometry, material, prop.baseCount);
        mesh.castShadow = false;
        mesh.frustumCulled = true;
        mesh.boundingSphere = prop.sphere;
        mesh.count = 0;
        mesh.visible = false;
        prop.high = mesh;
        group.add(mesh);
      } else {
        prop.high.geometry = geometry;
        prop.high.material = material;
      }
      prop.shownHigh = url;
    } else {
      prop.low.geometry = geometry;
      prop.low.material = material;
      prop.shownLow = url;
    }
    if (lodCam) binProp(prop, lodCam);
  }

  /** Copy ONE instance matrix out of the entry's source list into a buffer.
   *  Sixteen floats by hand rather than `set(subarray(…))`: the subarray is a
   *  fresh view object, and this runs once per drawn instance per tick. */
  function copyMatrix(src: Float32Array, i: number,
                      dst: Float32Array, slot: number): void {
    const a = i * 16;
    const b = slot * 16;
    for (let j = 0; j < 16; j += 1) dst[b + j] = src[a + j];
  }

  /**
   * Draw EVERYTHING of an entry on the cheap mesh — the answer while no camera
   * is known at all (the very first build, before the first LOD tick).
   *
   * Not a second LOD rule: it is what "no distance to measure against" has to
   * mean, and the first tick replaces it a fraction of a second later. The
   * alternative was a ground that stands bare until then.
   */
  function fillAll(prop: ScatterProp): void {
    prop.hidden = false;
    prop.tiers.fill(1);
    prop.slots.fill(1);
    const buf = prop.low.instanceMatrix.array as Float32Array;
    for (let i = 0; i < prop.baseCount; i += 1) copyMatrix(prop.srcMatrix, i, buf, i);
    prop.low.count = prop.baseCount;
    prop.low.visible = prop.baseCount > 0;
    prop.low.instanceMatrix.needsUpdate = true;
    mountUrl(prop, prop.loUrl, false);
  }

  /** One of each for the billboard matrices, reused across every entry and
   *  every tick: composing a matrix per drawn billboard is the price of the
   *  stage, and a fresh Vector3 per instance would be garbage for nothing. */
  const impM = new THREE.Matrix4();
  const impQ = new THREE.Quaternion();
  const impUp = new THREE.Vector3(0, 1, 0);
  const impAt = new THREE.Vector3();
  const impScale = new THREE.Vector3();

  /** Switch an entry's far half off whole — the answer to every sphere test
   *  that misses, and to a bake that has not landed yet. A layer that is
   *  already off costs nothing. */
  function hideImpostors(prop: ScatterProp): void {
    const layer = prop.impostor;
    if (!layer || layer.hidden) return;
    layer.hidden = true;
    layer.mesh.count = 0;
    layer.mesh.visible = false;
  }

  /**
   * Draw the entry's billboards — every instance between the cull line and
   * `IMPOSTOR_FAR_M`, on the very positions the meshes use.
   *
   * WHAT IT REFUSES, in the order it refuses it, because that order is what
   * keeps a world of woods affordable:
   *  - an entry WITHOUT a model has no far half at all. The built-in tuft is a
   *    cone in the ground's own colour; a billboard of it would be a smudge,
   *    and knee-high growth is out of the picture long before 120 m anyway.
   *  - an entry whose nearest instance is beyond `IMPOSTOR_FAR_M`, and one
   *    whose FARTHEST instance is still inside the cull distance: the first
   *    has nothing left to draw, the second is drawn entirely as meshes. Both
   *    are answered from the instance sphere, without a loop.
   *  - a prop that has not been baked yet draws NOTHING — no placeholder, no
   *    grey quad. The bake is asked for here (`impostorBake`, which starts one
   *    pass in the background and answers null meanwhile), so the wood appears
   *    a tick later rather than flashing a stand-in first.
   *
   * The matrix of one billboard is `impostorQuad` (its size and how high its
   * centre stands) and `impostorYaw` (which way it turns) — both pure, both
   * checked by hand in `client3d/scripts/smoke_impostors.mjs`. The yaw is
   * around Y and nothing else: a tree stands upright, and a quad that tilted
   * back towards a camera looking down from 60° would lay the whole wood over.
   */
  function binImpostors(prop: ScatterProp, cam: THREE.Vector3,
                        cfg: ScatterLodCfg): void {
    if (!prop.loUrl) return;
    const centreD = cam.distanceTo(prop.sphere.center);
    // Nothing of the entry can be inside the window: too far for a billboard,
    // or near enough that every instance of it is a mesh.
    if (centreD - prop.sphere.radius > IMPOSTOR_FAR_M
        || centreD + prop.sphere.radius <= cfg.cullM) {
      hideImpostors(prop);
      return;
    }
    let layer = prop.impostor;
    if (!layer) {
      // A CLAIM, not a lookup: the bake cache may not free a texture this
      // mesh is drawing with, so the entry holds it until `clearAreas`
      // releases it again (`scene/impostors.ts`).
      const bake = acquireImpostor(prop.loUrl, prop.near);
      if (!bake) return;   // nothing is drawn until the texture is there
      layer = {
        mesh: createImpostorMesh(bake, prop.baseCount),
        quad: impostorQuad(prop.targetH, bake.frame),
        hidden: true,
      };
      // The instances of this entry are what it holds, so it is culled against
      // the entry's own sphere — set, never computed, for the reason
      // `ScatterProp.sphere` gives.
      layer.mesh.boundingSphere = prop.sphere;
      prop.impostor = layer;
      group.add(layer.mesh);
    }
    layer.hidden = false;
    const cull2 = cfg.cullM * cfg.cullM;
    const far2 = IMPOSTOR_FAR_M * IMPOSTOR_FAR_M;
    const buf = layer.mesh.instanceMatrix.array as Float32Array;
    impScale.set(layer.quad.w, layer.quad.h, 1);
    let n = 0;
    for (let i = 0; i < prop.baseCount; i += 1) {
      const px = prop.pos[i * 3];
      const py = prop.pos[i * 3 + 1];
      const pz = prop.pos[i * 3 + 2];
      const dx = px - cam.x;
      const dy = py - cam.y;
      const dz = pz - cam.z;
      const d2 = dx * dx + dy * dy + dz * dz;
      // Written so a NaN position fails the test and is simply not drawn — the
      // discipline of `binProp` and `instanceTier`, and the reason a
      // degenerate instance costs no NaN matrix.
      if (!(d2 > cull2 && d2 <= far2)) continue;
      const d = Math.sqrt(d2);
      if (!impostorVisible(i, d, cfg)) continue;
      impQ.setFromAxisAngle(impUp, impostorYaw(px, pz, cam.x, cam.z));
      // The quad's CENTRE stands above the point the instance sits on, by
      // exactly as much as puts the baked foot on the ground (`impostorQuad`).
      impM.compose(impAt.set(px, py + layer.quad.centreY, pz), impQ, impScale);
      impM.toArray(buf, n * 16);
      n += 1;
    }
    layer.mesh.count = n;
    layer.mesh.visible = n > 0;
    // ALWAYS uploaded when anything is drawn, unlike the mesh buffers: every
    // billboard turns with the camera, so a tick that drew something wrote
    // something new. See `ImpostorLayer` for why there is no ledger.
    if (n > 0) layer.mesh.instanceMatrix.needsUpdate = true;
  }

  /**
   * Sort every instance of ONE entry into the two buffers — the whole
   * per-object LOD, once per entry per tick.
   *
   * THE THREE QUESTIONS ARE ASKED PER INSTANCE (`scene/scatterLod.ts`, all of
   * it pure and hand-checked): which mesh it deserves at its own distance
   * (`instanceTier`, with the band's hysteresis reading `prop.tiers`), whether
   * it survives the thinning out there (`instanceVisible`, a stable hash of
   * the instance index — the same trees regrow as one walks closer), and
   * whether it is inside the cull distance at all.
   *
   * WHAT COSTS WHAT, because this loop is the price of the feature:
   *  - the ENTRY is answered first, against its own instance sphere. A wood
   *    whose nearest possible instance is beyond the cull is switched off
   *    whole, and a tick that finds it already off returns without touching
   *    anything at all — which is what most entries of a large world do.
   *  - inside, the distance is compared SQUARED, and the square root is drawn
   *    only for an instance that is not already beyond the cull by it. The
   *    root is needed after that: both the band and the thinning line are
   *    linear in metres, not in metres squared.
   *  - the buffers are always refilled, the UPLOAD is not: `needsUpdate` is
   *    set per mesh and only when that mesh's set of instances really changed
   *    (an instance entering or leaving its slot). A camera standing still
   *    costs no vertex-buffer traffic at all.
   */
  function binProp(prop: ScatterProp, cam: THREE.Vector3): void {
    const cfg = lodCfg;
    // THE FAR HALF FIRST, and outside the entry-wide early-out below on
    // purpose: an entry whose nearest instance lies beyond the cull distance
    // is switched off there as a whole, and that is exactly the entry whose
    // billboards have to be drawn.
    binImpostors(prop, cam, cfg);
    if (cam.distanceTo(prop.sphere.center) - prop.sphere.radius > cfg.cullM) {
      if (prop.hidden) return;
      prop.hidden = true;
      // Hidden is the tier every instance really has out here, so the state
      // stays honest for the tick that brings the entry back.
      prop.tiers.fill(2);
      prop.slots.fill(2);
      prop.low.count = 0;
      prop.low.visible = false;
      if (prop.high) { prop.high.count = 0; prop.high.visible = false; }
      return;
    }
    prop.hidden = false;
    // WHERE AN IMPOSTOR STANDS, THE CULL HYSTERESIS HAS NOTHING LEFT TO DO.
    // `instanceTier` lets a HIDDEN instance back in only at 0.92·cull, so that
    // a tree at the line does not pop in and out with every centimetre of
    // camera drift. Beyond the line this entry now shows a billboard instead
    // of nothing, so there is no pop to damp — and keeping the band would open
    // a 9.6 m gap in which the billboard is already gone and the mesh not yet
    // there. So an instance of an impostor-capable entry re-enters as `low`
    // and is judged by the 35…45 m band like everything else; the swap itself
    // happens at ONE line, between two pictures of the same tree in the same
    // place. An entry without a model (the built-in tuft) has no far half and
    // keeps the band.
    const hasFarHalf = !!prop.loUrl;
    const cull2 = cfg.cullM * cfg.cullM;
    const loBuf = prop.low.instanceMatrix.array as Float32Array;
    const hiBuf = prop.high
      ? (prop.high.instanceMatrix.array as Float32Array) : null;
    let loN = 0;
    let hiN = 0;
    let loDirty = false;
    let hiDirty = false;
    let minD = Infinity;
    for (let i = 0; i < prop.baseCount; i += 1) {
      const dx = prop.pos[i * 3] - cam.x;
      const dy = prop.pos[i * 3 + 1] - cam.y;
      const dz = prop.pos[i * 3 + 2] - cam.z;
      const d2 = dx * dx + dy * dy + dz * dz;
      let tier: InstanceTier = 2;
      let slot = 2;
      // The test is written so that a NaN distance FAILS it and keeps the
      // hidden defaults above — the same discipline as `instanceTier`'s
      // negated comparisons, and the reason a degenerate position draws
      // nothing instead of a NaN matrix.
      if (d2 <= cull2) {
        const d = Math.sqrt(d2);
        if (d < minD) minD = d;
        const prev = prop.tiers[i] as InstanceTier;
        tier = instanceTier(d, hasFarHalf && prev === 2 ? 1 : prev, cfg);
        if (tier !== 2 && instanceVisible(i, d, cfg)) {
          // An instance that deserves the full mesh is drawn on the cheap one
          // as long as the full one is not there yet — a gap would be worse
          // than a coarse tree, and the tick after the arrival moves it over.
          slot = tier === 0 && hiBuf ? 0 : 1;
        }
      }
      prop.tiers[i] = tier;
      const was = prop.slots[i];
      if (was !== slot) {
        prop.slots[i] = slot;
        // A buffer's CONTENT is exactly the matrices of the instances in its
        // slot, in index order — so it changed if and only if this slot was
        // entered or left.
        if (slot === 0 || was === 0) hiDirty = true;
        if (slot === 1 || was === 1) loDirty = true;
      }
      // Post-increment: the slot an instance is written to is the count BEFORE
      // it, so the first drawn instance lands at 0 and `count` ends up right.
      if (slot === 0 && hiBuf) { copyMatrix(prop.srcMatrix, i, hiBuf, hiN); hiN += 1; }
      else if (slot === 1) { copyMatrix(prop.srcMatrix, i, loBuf, loN); loN += 1; }
    }
    prop.low.count = loN;
    prop.low.visible = loN > 0;
    if (loDirty) prop.low.instanceMatrix.needsUpdate = true;
    if (prop.high) {
      prop.high.count = hiN;
      prop.high.visible = hiN > 0;
      if (hiDirty) prop.high.instanceMatrix.needsUpdate = true;
    }
    // WHAT TO LOAD hangs on the NEAREST instance of the entry, not on where
    // the area's edge lies: the cheap mesh as soon as anything of the entry is
    // drawn at all, the full one as soon as anything could be classed high.
    // `farM` and not `nearM` on purpose — that is ten metres of walking in
    // which the file can arrive before the first instance really needs it.
    if (minD <= cfg.cullM) mountUrl(prop, prop.loUrl, false);
    if (prop.hasHigh && minD <= cfg.farM) mountUrl(prop, prop.hiUrl, true);
  }

  /**
   * Take the props of one area out of the scene and free everything they own.
   *
   * Split out of `clearAreas` (2026-08-19) because the scatter has a lifetime
   * of its own now: it is re-sampled whenever the camera's cell window moves,
   * while the drape it grows on stands. Everything below was `clearAreas`'
   * inner loop, verbatim.
   */
  function disposeProps(props: ScatterProp[]): void {
    for (const prop of props) {
      // BOTH meshes, and the full one only exists where it was deserved.
      group.remove(prop.low);
      if (prop.high) group.remove(prop.high);
      // The mark a pending `loadGlb` reads — see `mountUrl`.
      prop.disposed = true;
      // The grounded CLONES of the loaded tiers, however many arrived (see
      // there). `InstancedMesh.dispose` frees the instance buffers, never
      // the geometry, and these belong to nobody else — the MATERIALS do
      // (they came with the shared GLB) and are left alone.
      for (const geo of prop.owned.values()) geo.dispose();
      prop.owned.clear();
      // The tier MATERIALS are ALL ours (see `ScatterProp.mats`): every
      // scattered prop draws through a clone of the cached one since the
      // corridor fade, and a clone nobody frees is a leak per rebuild — an
      // admin painting terrain rebuilds this every few seconds.
      for (const m of prop.mats.values()) m.dispose();
      prop.mats.clear();
      prop.low.dispose();
      prop.high?.dispose();
      // …and the far half, where one was ever grown. Its MATERIAL is the
      // entry's own and goes; the baked TEXTURE does not — it belongs to the
      // bake cache of `scene/impostors.ts`, is shared by every entry
      // scattering that prop and outlives this ground on purpose (an admin
      // painting terrain rebuilds the areas every few seconds, and re-baking
      // the same tree each time would be a GPU pass per edit).
      if (prop.impostor) {
        group.remove(prop.impostor.mesh);
        disposeImpostorMesh(prop.impostor.mesh);
        prop.impostor = null;
        // …and the claim on the shared texture goes with the mesh that held
        // it — one release per `acquireImpostor` in `binImpostors`.
        releaseImpostor(prop.loUrl);
      }
    }
    props.length = 0;
  }

  function clearAreas(): void {
    for (const a of areaMeshes) {
      disposeProps(a.scatter);
      drain(a.scatterOwned);
    }
    areaMeshes.length = 0;
    for (const mesh of waterMeshes) {
      group.remove(mesh);
      mesh.geometry.dispose();
    }
    waterMeshes.length = 0;
    drain(areaOwned);
  }

  /**
   * Re-sample the authored scatter of every standing area — the cell window
   * moved, the ground under it did not.
   *
   * THE OCCASION IS A CROSSED CELL BORDER (`setHeightAnchor`) or a changed cull
   * distance (`setScatterLod`), both of which move the window of
   * `wantedScatterCells` and nothing else. Re-cutting the drapes for that would
   * be earcut plus a grid subdivision of every painted shape in the world every
   * 64 m walked; this touches the props alone, which is why an `AreaMesh` keeps
   * its ring, its occluders and a scatter bag of its own.
   *
   * The props are thrown away and rebuilt rather than diffed per cell: an entry
   * is ONE InstancedMesh over all its cells (that is what keeps a wood at two
   * draw calls instead of two per cell), so a window that gained a cell has a
   * different instance buffer either way. What survives it is the WORLD: every
   * cell's seed is its own, so the cells that stayed grow the very same props
   * in the very same places.
   */
  function rebuildScatter(): void {
    for (const a of areaMeshes) {
      disposeProps(a.scatter);
      drain(a.scatterOwned);
      a.scatter = buildScatter(a.area, a.ring, a.occluders, a.scatterOwned);
      for (const prop of a.scatter) {
        group.add(prop.low);
        if (prop.high) group.add(prop.high);
      }
    }
  }

  /** A pending re-sample after a prop was MEASURED (`noteSpread`) — one timer
   *  for all of them: a wood mounts several files within a few hundred
   *  milliseconds, and re-sampling once per arrival would rebuild every area
   *  of the world once per tree. */
  let spreadTimer: ReturnType<typeof setTimeout> | null = null;

  /**
   * File how wide a loaded prop really is, and re-sample if that changes the
   * clearance the entry was planted with.
   *
   * The sampler needs a width BEFORE the mesh exists, so it starts with the
   * estimate (`scatterClearM` without an extent). When the file lands the true
   * one is known — and since the clearance is a REJECTION and never touches
   * the candidate stream, the correction subtracts (or gives back) props at the
   * rim of a footprint and moves no other one by a millimetre.
   *
   * Once per URL per session: the second and every later mount of the same file
   * finds the identical number and schedules nothing, so this converges after
   * the first pass over a world instead of rebuilding on every load.
   */
  function noteSpread(url: string, geo: THREE.BufferGeometry): void {
    const box = geo.boundingBox;
    if (!url || !box) return;
    const height = box.max.y - box.min.y;
    if (!(height > 1e-6)) return;
    const width = Math.max(box.max.x - box.min.x, box.max.z - box.min.z);
    if (!Number.isFinite(width) || width <= 0) return;
    const spread = width / height;
    const prev = propSpread.get(url);
    if (prev !== undefined && Math.abs(prev - spread) < 1e-6) return;
    propSpread.set(url, spread);
    if (!areaMeshes.length || spreadTimer !== null) return;
    // NOT straight away: this runs inside the load callback of a prop that is
    // about to be mounted, and `rebuildScatter` disposes exactly that entry.
    spreadTimer = setTimeout(() => {
      spreadTimer = null;
      if (areaMeshes.length) rebuildScatter();
    }, SPREAD_RESAMPLE_MS);
  }

  /**
   * Point the scatter window at (x, z) and re-sample if it really moved.
   *
   * `true` when the set of cells changed — the caller decides what to do with
   * that (the anchor re-samples, the first build merely takes note).
   */
  function moveScatterWindow(x: number, z: number): boolean {
    const cells = wantedScatterCells(x, z, lodCfg.cullM);
    const sig = `${lodCfg.cullM}|${cells.length ? cells[0].join(',') : ''}`
      + `|${cells.length}`;
    if (sig === scatterSig) return false;
    scatterSig = sig;
    scatterCells = cells;
    return true;
  }

  /**
   * Rebuild the painted areas — BUILD FIRST, SWAP LAST.
   *
   * Everything the new ground needs is built into local lists while the old
   * one still stands: the surface textures are awaited, the meshes and the
   * scatter are made, and only then does the old ground go and the new one
   * take its place, within one turn of the event loop. Tearing the old areas
   * down first (as this did until E5) left the world lying on its bare base
   * plane for as long as the texture preload took — an admin painting terrain
   * refetches this every few seconds and saw the ground flash grey each time.
   *
   * The DISPOSABLES follow the same order, which is why the new ones are
   * collected in `nextOwned`: draining `areaOwned` is what `clearAreas` does,
   * and a material built into that same bag before the drain would be disposed
   * the moment it was hung into the scene.
   */
  async function rebuildAreas(): Promise<void> {
    const areas = payload?.areas ?? [];
    // The scatter window, before anything is sampled in it. Normally the
    // anchor has set it long ago; on the very first ground it is set here, so
    // a build that happens before the first `setHeightAnchor` samples the
    // cells around the origin instead of an empty window.
    moveScatterWindow(anchorX, anchorZ);
    // Textures first, ALL of them: `surfaceFor` only hands out fully loaded
    // images (a clone of a loading texture stays blank), so the whole ground
    // is built once the library has what it needs. What is loaded are the
    // SURFACES the types name, not the kinds themselves — the kind is a
    // catalog id and has not been a texture id since the assignment became
    // explicit.
    const surfaces = new Set<string>([surfaceOf(payload?.default_kind || ''),
      ...areas.map((a) => surfaceOf(a.kind))]);
    await Promise.all([...surfaces].map((s) => preloadSurfaceTexture(s)));

    const next: AreaMesh[] = [];
    const nextOwned: { dispose(): void }[] = [];
    /** every painted shape as the undergrowth field reads it — collected in
     *  LIST ORDER, because that is the stacking order its occluders rely on */
    const undergrowthAreas: UndergrowthArea[] = [];
    // ALL geometries first, in list order — the scatter of an area needs the
    // rings of the areas ABOVE it (see `buildScatter`), and the list order is
    // the stacking order the server sorted (z_order ASC, created_at ASC).
    // `null` = a ring that encloses nothing: it draws nothing and covers
    // nothing. Each area is still built exactly once.
    const builtAreas = areas.map((area) => buildAreaGeometry(THREE, area.polygon));
    /** ONE mirror material per water KIND, for the whole world (E4). Both the
     *  things that differ per AREA ride on the GEOMETRY — the level in each
     *  vertex's y, the flow in the `aWaterFlow` attribute — and never in a
     *  uniform, so a lake, a second lake at another height and a tilted river
     *  share one shader and cost three draw calls instead of three programs.
     *  Filled lazily: a world without water builds none. */
    const waterMats = new Map<string, THREE.Material>();
    /** THE ONE MIRROR BUILDER. `geometry` is the earcut of the outline in the
     *  XZ plane; `buildWaterPlane` lifts every vertex onto the area's own
     *  profile and hangs the flow direction on it as an attribute. */
    const nextWater: THREE.Mesh[] = [];
    const addMirror = (geometry: THREE.BufferGeometry, kind: string,
                       profile: WaterProfile): void => {
      let mat = waterMats.get(kind);
      if (!mat) {
        // 1 m per UV unit: the shape geometry's UVs are the world
        // coordinates, so the texture runs seamlessly across area borders.
        // Transparent and depth-write-free — the shore ramp is an alpha, and
        // a sheet of water must not hide the world behind it.
        mat = materialFor(kind, 1, nextOwned,
                          { transparent: true, depthWrite: false });
        // …and LAST in the chain, after the ripple and the basement hole:
        // the shore reads the height pyramids and writes the alpha
        // (`waterPlane.ts`).
        patchWaterShore(mat);
        waterMats.set(kind, mat);
      }
      nextWater.push(buildWaterPlane(geometry, profile, mat));
    };
    areas.forEach((area, index) => {
      const built = builtAreas[index];
      if (!built) return;   // a ring that encloses nothing has nothing to draw
      // WHO STILL GETS A MESH: water, and nothing else. Every other painted
      // ground is a CUT in the terrain surface since E3 — the compositor reads
      // the server's baked masks and paints it into the one material
      // (`scene/layerGround.ts`), which is why the whole ladder of renderOrder,
      // depth bias and hairline lifts that used to stand here is gone.
      //
      // ONE CONDITION SINCE W1, and it is data: `meta.water_profile`. The
      // server owns the single water predicate (`terrain_types.is_water_kind`)
      // and only an area that really carved a bed carries a profile, so asking
      // for the profile IS asking "is this water, and against which mirror".
      // The surface CLASS is not consulted here any more — it says what water
      // LOOKS like (ripple or matte) and was a second book about what water IS,
      // which is exactly the pair W1 collapsed into one.
      const profile = waterProfileOf(area.meta);
      if (profile) {
        addMirror(built.geometry, area.kind, profile);
      } else {
        // Not a mirror, so the earcut is not drawn — and a geometry nobody
        // holds is a buffer nobody frees. Only the RING lives on (below); the
        // triangles were only ever needed by the drape this stage deleted.
        built.geometry.dispose();
      }

      // The CLEANED ring, the one the mesh was built from — see `ringBounds`.
      const [minX, minZ, maxX, maxZ] = ringBounds(built.ring);
      // Everything painted OVER this area hides the ground it grows on.
      const occluders = builtAreas.slice(index + 1)
        .filter((b): b is NonNullable<typeof b> => !!b)
        .map((b) => b.ring);
      // The scatter gets a bag of its own: it is thrown away and rebuilt every
      // time the camera's cell window moves, while the drape material above
      // lives in `nextOwned` and stands until the terrain itself changes.
      const scatterOwned: { dispose(): void }[] = [];
      const scatter = buildScatter(area, built.ring, occluders, scatterOwned);
      next.push({ scatter, area, ring: built.ring, occluders, scatterOwned });
      // …and what grows here without anybody having said so (§ A9). The FIELD
      // grows it, per 64 m cell around the anchor (`scene/undergrowth.ts`), so
      // all this shape has to do is describe itself. NO occluder list: the
      // field takes them out of the LIST ORDER, which is the stacking order,
      // and only the ones whose box really meets the cell it samples — over a
      // 64 m square that is a handful instead of every shape above this one.
      // A kind that says nothing (`value` 0) is handed over all the same: the
      // field skips it for sampling but still needs it as an occluder.
      undergrowthAreas.push({
        id: area.id,
        kind: area.kind,
        // WHICH LAYER THIS SHAPE IS, so the field can ask the baked mask
        // whether the ground it grows on is really the topmost one at a
        // candidate point (user decision 5.2). The polygon occluders stay as
        // the cheap first pass; the mask is the truth behind them.
        layer: layerIndexOfKind(area.kind),
        ring: built.ring,
        bounds: [minX, minZ, maxX, maxZ],
        value: undergrowthFor(area.kind),
        color: kindColor(area.kind),
        swayM: swayFor(area.kind),
      });
    });

    // THERE IS NO SECOND SOURCE OF WATER (W1 § 6). Until W1 a room whose floor
    // kind was a water surface carved its own bed (`heightfield`'s fifth stage)
    // and got a mirror of its own out of the layer index's `waters` list. That
    // stage, that list and the room water fields are deleted: water is an ART
    // on the MAP, and a room that lies in one merely says so in its floor plan
    // (`map_water`, a derived reference). The loop that stood here is gone with
    // them.

    // THE SWAP. Nothing above touched the scene, so the old ground stood until
    // this line and the new one is in place before the frame after it.
    clearAreas();
    for (const mesh of nextWater) {
      group.add(mesh);
      waterMeshes.push(mesh);
    }
    for (const a of next) {
      for (const prop of a.scatter) {
        group.add(prop.low);
        // A full-detail mesh can exist before the swap: `buildScatter` bins
        // the entry against the camera of the last tick, and a model already
        // in the asset cache mounts within that very call.
        if (prop.high) group.add(prop.high);
      }
      areaMeshes.push(a);
    }
    areaOwned.push(...nextOwned);
    // …and the camera-local layer takes over the new shapes in the same
    // breath: it rebuilds the cells it holds, which is what puts the
    // undergrowth on a freshly draped relief instead of on the old one.
    undergrowth.setAreas(undergrowthAreas, footprints);
    rev += 1;
  }

  /**
   * The scatter-relevant state of the placed locations, as one string.
   *
   * NOT `locationsSignature` (the minimap's): that one watches id and position
   * only, and a footprint is four numbers — a location TURNED or resized
   * changes the ground it covers without moving its centre one metre. This is
   * `footprintSignature` per row, which is exactly those four, plus the id so
   * one place replaced by another at the same metre is its own state.
   *
   * Computed once per poll, never per frame: `sync` is the only caller.
   */
  function footprintSig(locations: readonly MapLocation[]): string {
    return locations.map((l) => `${l.id}:${footprintSignature(l)}`).join(';');
  }

  /**
   * The worldmap rows as scatter footprints — their DRAWN outlines, turned
   * into WORLD metres (contract v6 "Gebiete", § A1.1).
   *
   * THE TURN HAPPENS HERE, ONCE PER LOCATION, and that is the whole reason the
   * shared sampler takes world points: it would otherwise be paid per
   * CANDIDATE, on every sample of every painted area, and the package would
   * have to know what a pin is.
   *
   * A row without a usable boundary is DROPPED rather than passed on with an
   * empty outline: since v6 Nr. 1 such a location has no area at all — it is a
   * pin — and a place with no area covers no ground and clears no props. That
   * is the server's own answer (`world_geometry.effective_boundary` returns
   * nothing for it), so the ground the client keeps bare is the ground the
   * server calls occupied and no other.
   *
   * The square is gone with it: a bay bitten out of a lake used to be excluded
   * from scatter because the SQUARE covered it, while the corners of the drawn
   * shape that reached past that square grew props on ground the place owns.
   */
  function worldFootprints(locations: readonly MapLocation[]): ScatterFootprint[] {
    const out: ScatterFootprint[] = [];
    for (const loc of locations) {
      const local = sanitizePolygon(loc.boundary ?? loc.map3d?.boundary);
      if (!local) continue;
      const cx = loc.pos_x;
      const cz = loc.pos_z;
      if (typeof cx !== 'number' || !Number.isFinite(cx)) continue;
      if (typeof cz !== 'number' || !Number.isFinite(cz)) continue;
      const yawDeg = Number.isFinite(loc.yaw_deg) ? loc.yaw_deg : 0;
      const yaw = (yawDeg * Math.PI) / 180;
      out.push({
        points: local.map(([lx, lz]): Point2 => {
          const p = localToWorld(lx, lz, cx, cz, yaw);
          return [p.x, p.z];
        }),
      });
    }
    return out;
  }

  /**
   * Take over the world relief (§ A16).
   *
   * Failure keeps the field that stands and does NOT advance the signature, so
   * the next poll tries again — the same rule the terrain follows. A world
   * whose relief never arrives is drawn flat, which is wrong by the height of
   * its hills and right in every other respect; a client that refused to draw
   * a ground at all would be wrong about the whole world.
   */
  async function reloadHeight(heightSig: string): Promise<boolean> {
    try {
      const payload = await fetchHeightfield();
      relief.overview = payload;
      // A NEW SIGNATURE THROWS THE TILES AWAY WITH THE OVERVIEW (§ A16.3).
      // `height_sig` is the ONE signature of the relief; a tile that outlived it
      // would be a piece of a world that no longer exists, sitting in front of
      // the overview that replaced it — and the sampler prefers the tile.
      relief.tiles.clear();
      relief.stats?.clear();
      relief.tileM = Number(payload.tile_m) || 0;
      tileStepM = Number(payload.tile_step_m) || 0;
      // The quadtree half of the payload (E1 addendum § 4). `tile_stats` is
      // capped at the server's `TILE_STATS_MAX`; whatever is missing rides in
      // with the tiles themselves, and a node with no statistics simply falls
      // back to the field's whole range — which culls nothing and is never
      // wrong.
      relief.mipLevelsM = Array.isArray(payload.mip_levels_m)
        ? payload.mip_levels_m.map(Number) : [];
      for (const [key, s] of Object.entries(payload.tile_stats ?? {})) {
        relief.stats?.set(key, { min: Number(s.min) || 0, max: Number(s.max) || 0,
                                 err: (s.err ?? []).map(Number) });
      }
      tileIndex = new Set<string>(Array.isArray(payload.tiles) ? payload.tiles : []);
      anchorTile = null;   // …so the next anchor recomputes the want set
      loadedHeightSig = payload.sig || heightSig;
      heightRev += 1;
      fieldRange = worldHeightRange(payload);
      // The relief reaches the ground SHADER here and nowhere else (§ A16, the
      // AO of `scene/naturalGround.ts`): the overview is packed into a data
      // texture once per signature, and every patched ground material reads it
      // through shared uniforms — nothing recompiles, and a world with no
      // relief at all switches the stage off instead of shading against zero.
      setNaturalGroundField(payload);
      // …and the TERRAIN takes it over here: the overview becomes its far
      // pyramid, the (now empty) tile set its near one. Mip levels are derived
      // by decimation on the client, which is exact because every coarse
      // lattice is a subset of the fine one (§ G2).
      terrain.setField(relief, tileStepM, anchorX, anchorZ);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Take over one batch of fine tiles — the merge, with its two refusals.
   *
   * A grid comes WITHOUT a `step_m` of its own (every tile of a batch shares
   * the one at the top level), so it is merged in here; that is the whole
   * difference between the wire shape and `WorldHeightField`.
   *
   * KEY AGAINST ORIGIN IS CHECKED, once per tile. The key says which square of
   * the world this grid belongs to and the origin says where its support points
   * are; if the two disagree, the tile is filed under a square it does not
   * cover, and every reading in it is silently displaced — no error, no gap,
   * just ground from somewhere else. Cheap to test (two comparisons), and the
   * alternative is a class of bug that looks like an authoring mistake.
   *
   * Answers how many tiles were actually taken.
   */
  function takeTiles(batch: HeightTileBatch): number {
    const step = Number(batch.step_m) || 0;
    let taken = 0;
    for (const [key, grid] of Object.entries(batch.tiles || {})) {
      const [tx, tz] = key.split(',').map(Number);
      const fits = Number.isFinite(tx) && Number.isFinite(tz)
        && grid.origin_x === tx * relief.tileM
        && grid.origin_z === tz * relief.tileM;
      if (!fits) {
        warnOnce('tile-origin',
          `[ground] height tile "${key}" claims origin `
          + `(${grid.origin_x}, ${grid.origin_z}) — dropped`);
        continue;
      }
      relief.tiles.set(key, {
        origin_x: grid.origin_x, origin_z: grid.origin_z, step_m: step,
        rows: grid.rows, cols: grid.cols, heights: grid.heights,
      });
      // The tile carries its own quadtree statistics since E1 (§ G2). It may
      // already be in the map from `GET /play/heightfield`; the tile's own copy
      // is the same arithmetic on the same raster, so overwriting is a no-op
      // that costs nothing and keeps the uncapped case complete.
      if (grid.stats) {
        relief.stats?.set(key, {
          min: Number(grid.stats.min) || 0,
          max: Number(grid.stats.max) || 0,
          err: (grid.stats.err ?? []).map(Number),
        });
      }
      taken += 1;
    }
    return taken;
  }

  /**
   * Fetch the tiles the anchor wants, in batches, and re-drape ONCE per batch.
   *
   * The want set is `scene/heightTiles.wantedTiles` — pure, hand-checked, and
   * the only place that decides WHICH. Everything policy-shaped about the
   * loading is in these few lines instead:
   *
   *  - ONE loader at a time, and none while `sync` is rebuilding. Both cut the
   *    same meshes (see `tilesBusy`).
   *  - A FAILED batch keeps what stands: the tiles that did arrive stay, the
   *    ones that did not stay wanted, and the next anchor tick or poll asks
   *    again. The rule `reload` follows for the terrain, per tile.
   *  - A batch answering for ANOTHER signature is dropped whole. The relief was
   *    taken over while it was in flight, so its ground belongs to a world that
   *    is no longer on screen.
   *  - ONE `rebuildAreas` + `rebuildBase` per arrived batch, never per tile: a
   *    rebuild is the expensive half and 64 of them would be 64 times the work
   *    for one picture.
   *
   * Never throws — a relief that will not load leaves the ground it drew.
   */
  async function refreshTiles(): Promise<void> {
    if (tilesBusy || inFlight) return;
    if (!(relief.tileM > 0) || !tileIndex.size) return;
    const want = wantedTiles(tileIndex, relief.tileM, anchorX, anchorZ,
                             HEIGHT_TILE_RADIUS_M);
    // Wanting a tile is USING it: re-inserting moves it to the back of the map,
    // which is the eviction order below. Without this the cache would drop by
    // arrival time and throw away the ground under the player's feet in favour
    // of a tile fetched later and long since left behind.
    for (const key of want) {
      const held = relief.tiles.get(key);
      if (!held) continue;
      relief.tiles.delete(key);
      relief.tiles.set(key, held);
    }
    const missing = want.filter((k) => !relief.tiles.has(k));
    if (!missing.length) {
      evictTiles(want);
      return;
    }
    tilesBusy = true;
    const sig = loadedHeightSig;
    try {
      for (const batch of tileBatches(missing)) {
        let payload: HeightTileBatch;
        try {
          payload = await fetchHeightTiles(batch);
        } catch {
          return;   // keep what stands; the missing keys stay wanted
        }
        if (loadedHeightSig !== sig || (payload.sig && payload.sig !== sig)) return;
        if (!takeTiles(payload)) continue;
        evictTiles(want);
        heightRev += 1;
        // The tiles carry the relief the overview coarsened away, so the ray
        // start has to grow with them — see `fieldRange`.
        for (const tile of relief.tiles.values()) {
          const r = worldHeightRange(tile);
          if (r.max > fieldRange.max) fieldRange.max = r.max;
          if (r.min < fieldRange.min) fieldRange.min = r.min;
        }
        // The near pyramid is rebuilt from the tiles that now stand, through
        // `heightAt` itself — so the texture the vertex shader reads carries
        // the tile-first precedence and answers the same number every rule
        // does. Its window is the loaded tiles plus a margin, and out in that
        // margin near and far agree, which is what makes the switch between
        // them invisible.
        terrain.setField(relief, tileStepM, anchorX, anchorZ);
        await rebuildAreas();
        rebuildBase(lastBounds);
      }
    } finally {
      tilesBusy = false;
    }
  }

  /**
   * Take over the layer INDEX — the table, the coarse world mask, which tiles
   * exist. Called when `terrain_sig` moves, which is the signature the masks
   * really hang on (they are baked from the painted areas and the catalog).
   *
   * Failure keeps what stands and does NOT advance `layerSig`, so the next poll
   * tries again — the rule every fetch in this file follows. A world whose
   * masks never arrive draws bare ground everywhere, which is wrong about every
   * wood and right about where the ground IS; a client that refused to draw a
   * ground at all would be wrong about the whole world.
   */
  async function reloadLayers(sig: string): Promise<void> {
    let index: TerrainLayerIndex;
    try {
      index = await fetchTerrainLayers() as TerrainLayerIndex;
    } catch {
      return;
    }
    layerFmt = index;
    layerSig = index.sig || sig;
    layerIndexKeys = new Set<string>(index.tile_keys ?? []);
    layerTiles.clear();
    setLayerTiles(layerTiles, layerFmt);
    setLayerOverview(index.overview ?? null);
    const table: TerrainLayer[] = index.layers ?? [];
    // The BED belongs in the key (W1 § 5): two lakes of one kind on two beds
    // are two layers wearing two images, and it is this string that decides
    // whether the compositor's slice array is rebuilt.
    layerKey = table.map((l) => `${l.index}:${l.kind}:${l.surface}:`
      + `${l.edge_blend_m}:${l.water ? 1 : 0}:${l.bed_kind ?? ''}`).join('|');
    await setLayerTable(table, kindColor, (kind) => {
      const lib = surfaceFor(surfaceOf(kind), 'wall');
      return lib?.sizeM ?? 3;
    });
    // The masks moved, so the tiles under the player have to come with them.
    await refreshLayerTiles();
  }

  /**
   * Fetch the mask tiles the anchor wants, in batches, and hand the window over
   * ONCE per batch.
   *
   * The want set is `wantedTiles` — the height tiles' own, with the height
   * tiles' own radius: one window, one anchor. What differs is the BATCH SIZE
   * (the server's `terrain_layers.BATCH_MAX`, far below the height batch's,
   * because one mask tile is 384 kB of bytes against a height tile's 130 kB)
   * and that nothing here is ever evicted piecemeal: the window is packed whole
   * from whatever is held, so a tile leaving the set simply stops being copied.
   */
  async function refreshLayerTiles(): Promise<void> {
    if (layersBusy || !layerFmt || !layerIndexKeys.size) return;
    const tileM = Number(layerFmt.tile_m) || 0;
    if (!(tileM > 0)) return;
    const want = wantedTiles(layerIndexKeys, tileM, anchorX, anchorZ,
                             HEIGHT_TILE_RADIUS_M);
    const missing = want.filter((k) => !layerTiles.has(k));
    if (!missing.length) return;
    layersBusy = true;
    const sig = layerSig;
    try {
      for (let i = 0; i < missing.length; i += LAYER_BATCH_MAX) {
        let batch: TerrainLayerBatch;
        try {
          batch = await fetchTerrainLayers(
            missing.slice(i, i + LAYER_BATCH_MAX)) as TerrainLayerBatch;
        } catch {
          return;   // keep what stands; the missing keys stay wanted
        }
        if (layerSig !== sig || (batch.sig && batch.sig !== sig)) return;
        let taken = 0;
        for (const [key, tile] of Object.entries(batch.tiles || {})) {
          layerTiles.set(key, tile);
          taken += 1;
        }
        if (!taken) continue;
        // Everything the want set no longer holds leaves in the same breath:
        // the window is packed from what is in the map, so an old tile would
        // only stretch the rectangle and cost texels for ground nobody sees.
        const keep = new Set(want);
        for (const key of [...layerTiles.keys()]) {
          if (!keep.has(key)) layerTiles.delete(key);
        }
        setLayerTiles(layerTiles, layerFmt);
      }
    } finally {
      layersBusy = false;
    }
  }

  /** Drop the tiles nobody wants until the cache is back under its cap. The
   *  map is in "last wanted" order (see `refreshTiles`), so the front is the
   *  oldest — and a tile in the CURRENT want set is never dropped, however old,
   *  because dropping it would mean fetching it again in the same breath. */
  function evictTiles(want: readonly string[]): void {
    if (relief.tiles.size <= HEIGHT_TILE_CACHE_MAX) return;
    const keep = new Set(want);
    for (const key of [...relief.tiles.keys()]) {
      if (relief.tiles.size <= HEIGHT_TILE_CACHE_MAX) break;
      if (keep.has(key)) continue;
      relief.tiles.delete(key);
    }
  }

  /**
   * The ground at one world point — the client's mirror of
   * `app/core/terrain_query.entry_at`, on the very same data
   * (`GET /play/terrain`) and with the same loop: the TOPMOST containing area
   * wins (`areas` arrives in ascending z_order/paint order, so the LAST hit is
   * the one on top) and an unpainted point is the default kind.
   *
   * An area with an EMPTY kind falls back to the DEFAULT kind and does not
   * keep the area underneath it — the server's `hit` is overwritten by every
   * containing area and only resolved against the default at the end
   * (`kind_at`). Two readings of one square metre are how the halves of a
   * mirror start to drift.
   *
   * A kind the catalog does not know is walkable at normal speed (a painted
   * area whose type was deleted later must never strand a figure), and so is a
   * world whose terrain has not arrived yet: an empty payload would otherwise
   * turn the whole map into a wall for the first seconds.
   */
  function typeAt(x: number, z: number): TerrainPoint {
    let hit = '';
    // The MIRROR at THIS POINT (E4; local since W2). Written in the same breath
    // as the kind and by the same rule — the last containing area decides both
    // — so a sandbank painted over a lake takes the water away with the kind
    // instead of leaving a level behind that nothing draws.
    //
    // ONE WATER SOURCE. The painted areas are it: the zone-water lookup that
    // used to rank above them is deleted with the bake stage that fed it
    // (W1 § 6), and so is the catalog borrowing that used to fetch swimming
    // numbers for a room floor kind the terrain catalog had never heard of.
    // A water kind on the map is a catalogued terrain kind by construction.
    let level: number | null = null;
    for (const a of payload?.areas ?? []) {
      if (!pointInRing(x, z, a.polygon)) continue;
      hit = a.kind || '';
      const profile = waterProfileOf(a.meta);
      // The LOCAL level, never the area's mid one: over a river the figure has
      // to float on the water line it can see at its own metre.
      level = profile ? waterLevelAt(profile, x, z) : null;
    }
    const kind = hit || payload?.default_kind || '';
    const entry = catalog.get(kind.toLowerCase());
    if (!entry) {
      return { kind, passable: true, speed_factor: 1, move_anim: '',
        idle_anim: '', move_sink_m: 0, idle_sink_m: 0, water_level: level };
    }
    // A ground that says nothing sinks nobody — and junk is nothing, never
    // NaN: one NaN in the drop and the figure is at no height for good.
    const depth = (raw: unknown) => {
      const num = Number(raw);
      return Number.isFinite(num) && num > 0 ? num : 0;
    };
    return {
      kind,
      passable: entry.passable !== false,
      speed_factor: Number.isFinite(entry.speed_factor) ? entry.speed_factor : 1,
      move_anim: String(entry.meta?.move_anim ?? '').trim(),
      idle_anim: String(entry.meta?.idle_anim ?? '').trim(),
      move_sink_m: depth(entry.meta?.move_sink_m),
      idle_sink_m: depth(entry.meta?.idle_sink_m),
      water_level: level,
    };
  }

  /**
   * Fetch what changed and rebuild the ground once — relief first.
   *
   * The ORDER is the point: the field decides where every vertex of the plate
   * and of every area sits, so it has to be in before either is built. After
   * it come the areas (they preload the surface textures of every kind in
   * play, the default kind included) and only then the plate — building the
   * plate first would give it the flat catalog colour and never rebuild it,
   * because its key would not have moved by the time the texture arrived.
   */
  async function reload(sig: string, bounds: WorldBounds | null,
                        heightSig: string, wantTerrain: boolean,
                        wantHeight: boolean): Promise<boolean> {
    if (wantHeight) await reloadHeight(heightSig);
    let ok = true;
    if (wantTerrain) {
      try {
        payload = await fetchTerrain();
        loadedSig = payload.sig || sig;
        rebuildCatalog();
        // THE MASKS HANG ON `terrain_sig` TOO, and on nothing else: the bake is
        // a function of the painted areas plus the type catalog, which is
        // exactly what that signature covers. Fetched here rather than on its
        // own beat so the table, the catalog and the areas are always one
        // world — the compositor's slices are built from the catalog's colours.
        await reloadLayers(loadedSig);
      } catch {
        // Keep whatever stands. `loadedSig` is deliberately NOT advanced, so
        // the next poll with the same signature tries again.
        ok = false;
      }
    }
    // A failed terrain fetch does NOT cost the relief its rebuild: the areas
    // are re-cut from the payload that stands, and standing on the old ground
    // while the world is draped around it is the one state that would look
    // broken.
    if (ok || wantHeight) await rebuildAreas();
    rebuildBase(bounds);
    return ok;
  }

  return {
    group,
    sync(sig, bounds, locations, heightSig) {
      // Remembered FIRST, before any of the doors below close: the tile loader
      // rebuilds the plate on its own and has to do it in the frame the world
      // is in now, not in the one of the last sync that got through.
      lastBounds = bounds;
      if (inFlight) return inFlight;
      // The tile loader cuts the same meshes, so the two never run together —
      // and nothing is lost by standing down, because no signature has moved
      // and the next poll asks the identical question (see `tilesBusy`).
      if (tilesBusy) return Promise.resolve(false);
      const fpSig = footprintSig(locations);
      const fpMoved = builtFpSig !== null && builtFpSig !== fpSig;
      footprints = worldFootprints(locations);
      // The relief has its own signature and its own fetch (§ A16). `null`
      // is "never fetched", so the first sync always asks — a world whose
      // `height_sig` is the empty string of an older server asks once and is
      // then done with it.
      const wantHeight = loadedHeightSig !== heightSig;
      const wantTerrain = loadedSig === null || loadedSig !== sig;
      if (!wantTerrain && !wantHeight) {
        // Same terrain, same relief. Either only the frame moved — then the
        // base plate is the whole job — or a location did, and then the areas
        // have to be sampled again around the new footprints (finding B18).
        // No refetch for that: neither the painted ground nor the relief has
        // changed.
        rebuildBase(bounds);
        if (!fpMoved) {
          // THE IDLE POLL IS THE TILE LOADER'S SECOND OCCASION (§ A16.3): the
          // anchor kicks it when it crosses a tile border, and this catches
          // everything that missed — a batch whose request failed, a want set
          // computed before the index arrived. It costs a set difference when
          // there is nothing to fetch.
          void refreshTiles();
          // …and the MASK window rides the very same occasion, over the very
          // same want set (§ G3).
          void refreshLayerTiles();
          return Promise.resolve(false);
        }
        builtFpSig = fpSig;
        inFlight = rebuildAreas()
          .then(() => true)
          .finally(() => { inFlight = null; });
        return inFlight;
      }
      builtFpSig = fpSig;
      inFlight = reload(sig, bounds, heightSig, wantTerrain, wantHeight)
        .finally(() => { inFlight = null; });
      return inFlight;
    },
    setHeightAnchor(x, z) {
      if (!Number.isFinite(x) || !Number.isFinite(z)) return;
      anchorX = x;
      anchorZ = z;
      // ONE anchor, TWO windows (§ A16.3 and the undergrowth's 64 m raster).
      // The layer that grows around the player and the relief that is sharpened
      // around the player must follow the very same point, or the ground under
      // the tufts is drawn from a different source than the tufts themselves.
      // The layer derives its own want set from this and does nothing when it
      // has not moved — 25 candidate cells per tick.
      undergrowth.setAnchor(x, z);
      // …and the AUTHORED scatter rides the same anchor on its own 64 m raster
      // (`buildScatter`). The window is the square of cells around the
      // anchor's OWN cell, so this answers "no" on every tick but the one that
      // crosses a border — and only then is a wood re-sampled.
      if (moveScatterWindow(x, z) && areaMeshes.length) rebuildScatter();
      // A BORDER CROSSING IS THE IMMEDIATE OCCASION, and not the only one: the
      // idle poll asks again from wherever the anchor stands then, every three
      // seconds (`sync`). That division is deliberate. The want set does move
      // with every metre — the radius does — so a crossing alone would let the
      // rim of the window fall behind a walker; the poll keeps it up with him.
      // What the crossing buys is the JUMP: a camera flown across the world has
      // its ground on the way before the next poll would have noticed. One
      // string compare per tick, and the set difference only when it changed.
      // `tileKeyAt` is the ONE mapping from a point to a tile; the loader must
      // not have a second opinion about it.
      const key = tileKeyAt(relief.tileM, x, z);
      if (key === anchorTile) return;
      anchorTile = key;
      void refreshTiles();
      void refreshLayerTiles();
    },
    heightAt,
    groundPointAt(ray) {
      if (!hasRelief()) return null;
      const o = ray.ray.origin;
      const d = ray.ray.direction;
      // The slab the march is clipped to is the field's own range, and it only
      // ever grows within a signature, so a ray never starts inside a hill it
      // cannot see.
      const hit = rayGroundHit(relief, o.x, o.y, o.z, d.x, d.y, d.z,
                               { minY: fieldRange.min, maxY: fieldRange.max });
      return hit ? new THREE.Vector3(hit.x, hit.y, hit.z) : null;
    },
    heightRevision: () => heightRev,
    // THE OVERVIEW FIELD ITSELF, for the readers that draw the relief instead
    // of standing on it (the minimap's hillshade). The overview and nothing
    // else on purpose (§ A16.3): a picture of the whole world is the distant
    // view, and the fine tiles only exist around the camera — a map mixing the
    // two would be sharp in one square and coarse everywhere else. `null` until
    // the first field has arrived, which is "no relief" for every caller.
    heightField: () => relief.overview,
    setHole(rect) {
      holeOn.value = rect ? 1 : 0;
      if (rect) holeRect.value.set(rect[0], rect[1], rect[2], rect[3]);
    },
    tickScatterLod(cameraPos) {
      // Remembered for the next REBUILD, which happens outside this tick and
      // has to bin its fresh entries against a camera (see `buildScatter`).
      // A copy, not the live vector: it is read a second later from another
      // call stack, and a reference the engine mutates would be a different
      // camera by then.
      if (!lodCam) lodCam = new THREE.Vector3();
      lodCam.copy(cameraPos);
      for (const a of areaMeshes) {
        for (const prop of a.scatter) binProp(prop, cameraPos);
      }
      // The undergrowth rides on the same beat with its own, shorter
      // distances — it has no settable ones, so `setScatterLod` leaves it
      // alone and the next tick is the only thing that moves it.
      undergrowth.tick(cameraPos);
    },
    setScatterLod(cfg) {
      lodCfg = cfg;
      // A NEW CULL DISTANCE IS A NEW WINDOW (`scatterCellSpan`): a player who
      // raises it from 120 to 300 m asks for cells that were never sampled, and
      // no amount of re-binning can draw props that were never placed. Lowering
      // it gives the cells back. Everything else about the setting — which of
      // the placed instances is drawn as what — is the binning below.
      if (moveScatterWindow(anchorX, anchorZ) && areaMeshes.length) {
        rebuildScatter();
      }
      // AT ONCE, not on the next beat: the player is looking at the very
      // meadow whose numbers they just typed. The camera of the last tick is
      // the one the world is being drawn from, so re-binning against it is
      // exactly what the next tick would do, a second earlier.
      if (!lodCam) return;
      for (const a of areaMeshes) {
        for (const prop of a.scatter) binProp(prop, lodCam);
      }
    },
    scatterTiers() {
      const out: { variants: Record<string, string>; url: string }[] = [];
      for (const a of areaMeshes) {
        for (const prop of a.scatter) {
          // One sample per DRAWN mesh: an entry with instances on both tiers
          // reports both, which is what makes the readout's full/low split add
          // up to what is really on screen.
          if (prop.low.visible) out.push({ variants: prop.variants, url: prop.shownLow });
          if (prop.high?.visible) {
            out.push({ variants: prop.variants, url: prop.shownHigh });
          }
        }
      }
      return out;
    },
    payload: () => payload,
    typeAt,
    passableAt: (x, z) => typeAt(x, z).passable,
    revision: () => rev,
    terrainNodeCount: () => terrain.nodeCount(),
    terrainInstanceCap: () => terrain.instanceCap(),
    terrainTriangleCount: () => terrain.triangleCount(),
    heightTileCount: () => relief.tiles.size,
    // The terrain is ONE mesh with ONE material by construction (`terrainLod`),
    // so the array case cannot occur — it is narrowed rather than handled.
    terrainMaterial: () => (Array.isArray(terrain.mesh.material)
      ? terrain.mesh.material[0] ?? null : terrain.mesh.material ?? null),
    setTerrainFrozen: (on) => terrain.setFrozen(on),
    setTerrainCullOff: (on) => terrain.setCullOff(on),
    terrainCullStats: () => terrain.cullStats(),
    debugParts() {
      const scatter: THREE.Object3D[] = [];
      for (const a of areaMeshes) {
        for (const prop of a.scatter) {
          scatter.push(prop.low);
          if (prop.high) scatter.push(prop.high);
          if (prop.impostor) scatter.push(prop.impostor.mesh);
        }
      }
      return {
        terrain: [terrain.mesh],
        water: [...waterMeshes],
        undergrowth: [undergrowth.group],
        scatter,
      };
    },
    dispose() {
      clearAreas();
      // The terrain's height pyramids are shared module uniforms and outlive
      // this closure, so they are handed back explicitly — the very reason the
      // ground shader's own field is handed back a few lines below.
      group.remove(terrain.mesh);
      terrain.dispose();
      drain(baseOwned);
      drain(areaOwned);
      // The height texture of the ground shader is module state, not a member
      // of this closure, so it outlives the group it was built for — hand it
      // back explicitly or a client that tears its world down keeps the whole
      // overview on the GPU.
      setNaturalGroundField(null);
      // …and the layer cut: three textures and one array, all module state and
      // in no `*Owned` bag, so this is the only place they are freed.
      disposeLayerGround();
      // …and the camera-local layer, for the same reason: its blade texture,
      // its one geometry and its material per kind outlive every rebuild and
      // are in no `*Owned` bag, so this is the only place they are freed.
      undergrowth.dispose();
      // …and the one timer this module keeps: a re-sample waiting on a measured
      // prop width would rebuild areas into a group that is already gone
      // (`noteSpread`).
      if (spreadTimer !== null) {
        clearTimeout(spreadTimer);
        spreadTimer = null;
      }
    },
  };
}
