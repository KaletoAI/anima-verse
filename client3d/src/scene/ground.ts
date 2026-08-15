/**
 * The GROUND of the seamless metre world (plan-freie-weltkarte-e4-3d-client.md,
 * task 2).
 *
 * One base plane over the whole world in the default kind's look, and on top of
 * it the painted areas of `GET /play/terrain` — polygons in world metres, in
 * the order the server sorted them (bottom to top). This replaces the grid
 * world's per-cell plates: there are no cells any more, the ground is a plane
 * and the terrain is painted on it.
 *
 * WHAT LIVES WHERE
 *  - the polygon geometry is SHARED (`@anima/scene-render/groundAreas`), because
 *    the admin preview shows the same areas;
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
 * GROUND_Y DISCIPLINE, as amended by the world relief (E8 task 3). The ground
 * is still one height and one only — `ground_y(x, z)`, which since § A16 is
 * the heightfield sampled at that point instead of the constant 0. Nothing
 * here invents a height of its own: the base plate and every painted area are
 * cut on the FIELD's grid (`@anima/scene-render` `gridMesh`) and every vertex
 * is lifted by `sampleGroundHeight` at its own world x/z — the sampler that
 * reads the TRIANGULATED surface the mesh really is, so plate, areas, props
 * and figures describe one surface inside a cell and not merely at its
 * corners. Stacked areas are still separated by `renderOrder` + a depth
 * bias and NOT by a height ladder; the sub-millimetre hairline lift
 * (`AREA_Y_STEP_M`, capped at `AREA_Y_MAX_M`) now rides ON TOP of the sampled
 * height, which is the one place where "the areas sit a hair above the plate"
 * is allowed to be true.
 *
 * REFETCH. Neither the terrain nor the relief is ever fogged, so both are
 * fetched ONCE and again only when the worldmap poll reports a different
 * signature — `terrain_sig` for the painted areas, `height_sig` for the field.
 * `sync()` takes both and does nothing while they are unchanged.
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
import { AREA_POLYGON_OFFSET, buildAreaGeometry, compositeHeightRangeIn,
  gridPlate, gridStepFor, maxCompositeHeightIn, pickVariant, pointInRing,
  propGroundFit, sampleCompositeGroundHeight, sampleCompositeHeight,
  scatterInstances, scatterSeed, subdivideOnGrid, surfaceMaterial,
  surfaceTimeUniform, tileKeyAt, worldHeightRange } from '@anima/scene-render';
import type { GridBox, Point2, ScatterFootprint, SurfaceMaterialSpec,
  WorldHeightField, WorldHeightTiles } from '@anima/scene-render';
import { fetchHeightfield, fetchHeightTiles, fetchTerrain } from '../api';
import type { HeightTileBatch } from '../api';
import { footprintSignature, TERRAIN_FALLBACK_COLOR } from '../game/minimap';
import type { MapLocation, TerrainArea, TerrainPayload, TerrainScatterEntry, TerrainType,
  WorldBounds } from '../types';
import { HEIGHT_TILE_CACHE_MAX, HEIGHT_TILE_RADIUS_M, tileBatches,
  wantedTiles } from './heightTiles';
import { preloadSurfaceTexture, setWorldGround, setWorldRayStart, surfaceFor,
  surfaceMaterialSpec } from './tiles';
import { acquireImpostor, createImpostorMesh, disposeImpostorMesh,
  releaseImpostor } from './impostors';
import { applyNaturalGround, NG_EDGE_ATTRIBUTE,
  setNaturalGroundField } from './naturalGround';
import { isWaterClass, ngRefineEdgeBand } from './naturalGroundMath';
import { applyOcclusionFade } from './occlusion';
import { loadGlb } from './propAssets';
import { IMPOSTOR_FAR_M, impostorQuad, impostorVisible, impostorYaw,
  instanceTier, instanceVisible, SCATTER_LOD_DEFAULTS, scatterSway,
  scatterTargetH } from './scatterLod';
import type { ImpostorQuad, InstanceTier, ScatterLodCfg } from './scatterLod';
import { createUndergrowthField } from './undergrowth';
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
 *  Exported because the FOG has to reach exactly as far (E4 task 6): the veil
 *  is the world frame grown by this very margin, minus the known footprints.
 *  A cover that stopped at the bounds would leave a ring of bare ground
 *  glowing around the map, and one that reached further would hang over
 *  nothing at all. ONE number, one home. */
export const BASE_MARGIN_M = 60;
/** Edge length of the base plane when nothing is placed at all (metres). */
const BASE_FALLBACK_M = 200;
/** Depth-bias-free hairline lift per stacking level, and its ceiling. Read the
 *  file header: this is a rendering crutch, not a height model. */
const AREA_Y_STEP_M = 0.0004;
const AREA_Y_MAX_M = 0.01;
/** Ceiling of the stacking depth bias. The bias only has to separate the layer
 *  from the one below it, and a world with two hundred painted areas must not
 *  ask the driver for a two-hundred-fold offset. */
const AREA_OFFSET_MAX = 32;
/**
 * Where the painted areas sit in the TRANSPARENT pass: drawn far BEFORE
 * everything else in it, at `BASE + index + 1`.
 *
 * The areas became transparent materials with the soft edge (§ stage 4 of
 * `scene/naturalGround.ts`), and that moved them out of the opaque pass — where
 * they were drawn before every overlay in the world — into the pass three sorts
 * by `renderOrder`. At the natural ladder (1, 2, 3, …) they would land AFTER
 * every overlay that leaves its render order at the default 0: the fog clouds,
 * the selection ring under an NPC, a path line, the door and boundary marks.
 * Those overlays deliberately do not write depth, so the opaque CORE of a drape
 * drawn after them simply paints over them — a selection ring vanishes on a
 * painted meadow, and every painted area punches a hole in the fog.
 *
 * A large negative base restores the old truth ("the ground is drawn first")
 * without touching anything else: the areas keep their order AMONG themselves,
 * which is what stacks them, and they stay behind the whole of the default-0
 * world. Ten thousand is simply more layers than any world will ever paint.
 * Exported so the smoke can pin the number instead of a copy of it.
 */
export const AREA_RENDER_ORDER_BASE = -10000;

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

/** One built area: what stands in the scene, plus what the scatter LOD needs. */
interface AreaMesh {
  mesh: THREE.Mesh;
  /** one scatter entry per authored row — empty when nothing grows here
   *  (finding B17: the list hangs on the AREA, not on the terrain type) */
  scatter: ScatterProp[];
  /** centre of the area's bounding box. NOT a LOD distance any more (that is
   *  per instance since 2026-08-15) — it is what the download queue sorts by,
   *  handed to `loadGlb` as the place the props of this area stand. */
  centre: THREE.Vector3;
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
   * THE FOG FILTER ON THAT LIST IS DELIBERATE (review ruling, rounds 3+4).
   * Under the fog the payload carries only the places the avatar knows, so an
   * undiscovered location is not in `locations` and its ground gets scattered
   * like any other. That is the RIGHT way round: a clearing in the wood
   * exactly the size of a building would announce a place the player has not
   * found yet — the veil would hide the tile and the missing trees would give
   * it away. The props correct themselves the moment the place is discovered
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
   * The world's ground height at a point (§ A16), in metres.
   *
   * THE one height source of the client: the base plate and the painted areas
   * are draped with it, the figures stand on it, and `main.ts` `groundY()`
   * falls back to it wherever no location's own model answers. 0 until the
   * field has arrived, and 0 for ever in a world nobody has shaped — the flat
   * world is a relief like any other, it just happens to be level.
   */
  heightAt(x: number, z: number): number;
  /**
   * The world's ground as THE SERVER reads it — bilinear, not triangulated.
   *
   * The other height, and the difference is a rule rather than a picture: the
   * field is defined bilinear (§ A16) and the walking gate judges a step by
   * THAT reading (`relief.ground_lift_at` → `POST /play/pos`). A mesh cannot
   * be bilinear, so `heightAt` answers the drawn surface, which inside a cell
   * differs by up to a quarter of its twist — a measured metre on a steep
   * hill. Everything that has to PREDICT the server (the client's mirror of
   * the slope rule) asks here; everything that has to touch the ground the
   * player sees asks `heightAt`.
   */
  fieldHeightAt(x: number, z: number): number;
  /**
   * Highest ground inside an axis-aligned rectangle (world metres) — what the
   * fog quads hang above (§ A12 + § A16). One flat quad over a hilly patch has
   * to clear the highest thing under it, or the mountain stands in the cloud.
   */
  maxHeightIn(x0: number, z0: number, x1: number, z1: number): number;
  /**
   * How much the ground RISES AND FALLS inside that same rectangle, in metres.
   *
   * The fog's tiling question (E8 task 5): a veil rectangle is only cut into
   * 64 m quads where the ground under it actually moves, so over level ground
   * one rectangle stays one draw call. 0 in a world with no relief.
   */
  heightRangeIn(x0: number, z0: number, x1: number, z1: number): number;
  /**
   * Where a pointer ray meets the DRAWN ground, or `null` when it misses.
   *
   * The click-to-walk goal used to be read against a horizontal plane at the
   * figure's own height, which on a slope puts the goal metres away from the
   * pointer (at 40° and a flat camera angle: 7-14 m). The draped plate is the
   * surface the player sees, so that is what the ray asks.
   *
   * Costs a brute-force triangle test over the plate (three.js has no BVH) —
   * fine for a click, never for a frame.
   */
  groundPointAt(ray: THREE.Raycaster): THREE.Vector3 | null;
  /** Counts how often the RELIEF was taken over. Part of the fog's rebuild key
   *  (the veil's height comes from the field) — a signature of its own,
   *  because the field arrives long after the first fog is built. */
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
   * MUTATED IN PLACE, never replaced: `heightAt` runs per vertex of the plate
   * and per figure per frame, and a fresh wrapper object per call would be a
   * few hundred thousand allocations for nothing.
   */
  const relief: WorldHeightTiles = { tileM: 0, overview: null, tiles: new Map() };
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
  /** The cell size plate and areas are cut at — ONE for the whole ground, so
   *  the two always meet on the same lines (`gridStepFor`, gridMesh.ts). 0
   *  while there is no relief at all: then nothing is subdivided. */
  let cellM = 0;

  /** Has any relief arrived at all — the overview, or at least one tile? */
  const hasRelief = (): boolean => !!relief.overview || relief.tiles.size > 0;

  /**
   * The ground under a point — the DRAWN one
   * (`sampleCompositeGroundHeight`), not the bilinear field.
   *
   * The mesh is triangles: within a cell the plate is two planes, and a vertex
   * or a figure placed at the field's bilinear reading sits off that surface by
   * up to a quarter of the cell's twist — a measured metre on a 5 m hill with a
   * 10 m falloff. ONE sampler for the plate, the areas, the props and every
   * figure is what makes them describe one surface (§ A16). `cellM` is what
   * ties it to the mesh: it is the size the ground was really cut at, and the
   * sampler answers for the very cell the plate is made of.
   */
  const heightAt = (x: number, z: number): number =>
    (hasRelief() ? sampleCompositeGroundHeight(relief, x, z, cellM) : GROUND_Y);

  /** The BILINEAR reading of the field — the server's own (see the interface).
   *  Used by the walk-rule mirror, never by anything that is drawn, and it goes
   *  through the same ladder: the server judges a step by the fine TILE
   *  (`heightfield.world_height`), so a mirror reading the overview would
   *  predict a refusal on ground nobody is walking on. */
  const fieldHeightAt = (x: number, z: number): number =>
    (hasRelief() ? sampleCompositeHeight(relief, x, z) : GROUND_Y);

  // THE GROUND HOOK (E8 task 4): a location's tile stands on the ground under
  // its centre, and this is where `scene/tiles.ts` gets that height from. The
  // sampler is a closure over `field`/`cellM`, so it stays correct across every
  // refetch without anyone re-registering it — and it is the DRAWN ground on
  // purpose: the tile has to sit on the surface the player sees. Under a
  // footprint that levels its ground (`level_ground`, § A16.1, opt-in) the two
  // readings agree anyway, because the server flattens the field there.
  setWorldGround(heightAt);

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
  const undergrowth = createUndergrowthField({ heightAt, applySway });
  group.add(undergrowth.group);

  /** Lift a flat vertex list onto the ground, in place. `pos` is `[x, y, z, …]`
   *  in WORLD metres (both the plate and the subdivided areas are), so the
   *  sample point is the vertex itself. */
  function liftToField(pos: number[]): void {
    if (!hasRelief()) return;
    for (let i = 0; i < pos.length; i += 3) {
      pos[i + 1] += sampleCompositeGroundHeight(relief, pos[i], pos[i + 2], cellM);
    }
  }

  /** The box the FIELD describes (§ A16): `origin + (cols−1) · step`. Outside
   *  it the ground is the field's border value, which the server pins to 0 —
   *  flat, and the plate covers it with plain quads. `null` = no relief.
   *
   *  THE OVERVIEW ANSWERS IT, not the tiles, and that is exact rather than an
   *  approximation: the overview is rastered over everything authored anywhere
   *  (§ A16), and a tile is only ever indexed where it meets one of those very
   *  boxes. There is no ground outside this box for a tile to hold. */
  function reliefBox(): GridBox | null {
    const ov = relief.overview;
    const rows = ov?.heights?.length ?? 0;
    const cols = ov?.heights?.[0]?.length ?? 0;
    const step = ov?.step_m ?? 0;
    if (!ov || rows < 2 || cols < 2 || !(step > 0)) return null;
    return {
      x0: ov.origin_x,
      z0: ov.origin_z,
      x1: ov.origin_x + (cols - 1) * step,
      z1: ov.origin_z + (rows - 1) * step,
    };
  }

  /** The footprints the scatter keeps clear (finding B18), and the signature
   *  the areas standing in the scene were sampled against. `null` means "never
   *  built", which is not the same as "built against no locations at all". */
  let footprints: readonly ScatterFootprint[] = [];
  let builtFpSig: string | null = null;

  let baseMesh: THREE.Mesh | null = null;
  let baseKey = '';
  const areaMeshes: AreaMesh[] = [];
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

  /**
   * Material of one ground kind.
   *
   * Texture first (the surface-texture library the tiles already feed), the
   * catalog colour second. The library entry is asked for THIS KIND ALONE:
   * `surfaceFor(kind, 'floor')` would fall back to the global indoor `floor`
   * kind, which is the wrong ground for a painted meadow — the `'wall'` chain
   * is the one that asks for the kind and nothing else (`tiles.ts`).
   *
   * `uvScaleM` is how many metres one UV unit spans: the shape geometry's UVs
   * ARE the world coordinates (1 unit = 1 m), the base plane's run 0..1 over
   * its whole edge.
   *
   * `edgeFade` is for the painted-area DRAPES alone: their geometry carries
   * the distance to their own ring (`drapeArea`), so their material may fade
   * out along it. The base plate has no ring and no such attribute — it is
   * what the drapes fade out ONTO, and it stays opaque.
   */
  function materialFor(kind: string, uvScaleM: number,
                       sink: { dispose(): void }[],
                       edgeFade = false): THREE.Material {
    const lib = surfaceFor(kind, 'wall');
    const spec: SurfaceMaterialSpec | null = surfaceMaterialSpec(kind);
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
    const mat = surfaceMaterial(THREE, { material: spec, map, color: kindColor(kind) });
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
    if (!isWaterClass(spec?.class)) applyNaturalGround(mat, edgeFade);
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
   * The cell size the WHOLE ground is cut at, in metres — 0 for a flat world,
   * where nothing is subdivided at all.
   *
   * ONE number for the plate and every painted area (`gridStepFor` doubles the
   * field's own step until the plate stays under `GRID_MAX_CELLS`). A plate
   * cut coarser than the areas on it would have the areas sampling the field
   * where the plate only interpolates between two of its vertices — the
   * meadow would sink into the hill it is painted on.
   *
   * IT IS THE OVERVIEW'S STEP THIS STARTS FROM, not the tiles' finer one, and
   * that is a mesh decision rather than a height one: the plate spans the whole
   * world frame and its budget is 40 000 cells whatever raster it samples. The
   * tiles sharpen every CORNER of that mesh (each vertex is lifted through the
   * composite ladder) and every reading the rules take — they do not make the
   * plate finer. The seam where the loaded tiles end sits at 560 m, behind the
   * fog (`heightTiles.ts`).
   *
   * A field of nothing but zeroes is FLAT and says so: today's worlds have no
   * relief at all, and giving them forty thousand cells for a surface that is
   * level would be paid every rebuild for nothing.
   */
  function cellFor(bounds: WorldBounds | null): number {
    const step = relief.overview?.step_m ?? 0;
    const box = reliefBox();
    if (!(step > 0) || !box) return 0;
    if (fieldRange.min === 0 && fieldRange.max === 0) return 0;
    const [px0, pz0, px1, pz1] = plateExtent(bounds);
    // The budget is spent where there IS relief: the field's box, clipped to
    // what the plate shows of it. A hill in the corner of a huge world keeps
    // the native cell size instead of paying for the plain around it.
    const x0 = Math.max(px0, box.x0);
    const z0 = Math.max(pz0, box.z0);
    const x1 = Math.min(px1, box.x1);
    const z1 = Math.min(pz1, box.z1);
    if (!(x1 > x0) || !(z1 > z0)) return 0;   // the relief is off the plate
    return gridStepFor(x0, z0, x1, z1, step);
  }

  /**
   * The plane under everything, in the look of the unpainted ground — and
   * since E8 the LANDSCAPE under everything.
   *
   * Without a relief it stays the two triangles it always was. With one it is
   * a grid of cells on the field's own lines (`gridPlate`), every vertex
   * lifted by the sampled height: the plate IS the world's terrain, and the
   * painted areas are cut on the same grid so they lie on it instead of
   * cutting through it.
   *
   * The plate is built in WORLD coordinates and the mesh sits at the origin —
   * not at the plate's centre with local coordinates around it. That is what
   * lets one and the same sampled height serve the plate, the areas and the
   * figures without a transform in between, and it costs nothing: a mesh's
   * bounding sphere is what culls it, and that is computed either way.
   */
  function rebuildBase(bounds: WorldBounds | null): void {
    const [wantX0, wantZ0, wantX1, wantZ1] = plateExtent(bounds);
    const kind = payload?.default_kind || '';
    const key = `${kind}|${wantX0}|${wantZ0}|${wantX1}|${wantZ1}|${heightRev}`;
    if (baseMesh && key === baseKey) return;
    if (baseMesh) {
      group.remove(baseMesh);
      baseMesh.geometry.dispose();
      baseMesh = null;
      drain(baseOwned);
    }
    baseKey = key;
    const plate = gridPlate(wantX0, wantZ0, Math.max(wantX1, wantX0 + 1),
                            Math.max(wantZ1, wantZ0 + 1), cellM,
                            relief.overview?.origin_x ?? 0,
                            relief.overview?.origin_z ?? 0,
                            reliefBox());
    liftToField(plate.pos);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(plate.pos, 3));
    geo.setAttribute('uv', new THREE.Float32BufferAttribute(plate.uv, 2));
    geo.setIndex(plate.index);
    geo.computeVertexNormals();
    geo.computeBoundingSphere();
    const w = plate.maxX - plate.minX;
    const d = plate.maxZ - plate.minZ;
    // The base tiles over its WHOLE edge, so one UV unit is `w` metres wide
    // and `d` deep. Non-square worlds would stretch the texture; the shorter
    // edge decides, which repeats a little more often than it stretches.
    const mesh = new THREE.Mesh(geo, materialFor(kind, Math.min(w, d), baseOwned));
    mesh.receiveShadow = true;
    mesh.renderOrder = 0;
    baseMesh = mesh;
    group.add(mesh);
  }

  /**
   * Deterministic prop scatter of one area — up to TWO InstancedMeshes per
   * entry (the cheap one from the start, the full one when it is deserved).
   *
   * WHAT GROWS HERE IS THE AREA'S OWN BUSINESS (finding B17). It used to hang
   * on the terrain TYPE, which could only ever say "all forest everywhere
   * grows this one tree"; a wood with two kinds of tree and a clearing without
   * any is one painted shape each, so the list moved to `meta.scatter` of the
   * area. No list, or an empty one, means nothing grows — there is no default.
   *
   * WHERE the instances stand is not decided here: `scatterInstances`
   * (@anima/scene-render) is the ONE sampler, and the map editor draws its
   * preview from the very same call. That is the whole point of the shared
   * module — preview and world agree by construction, not by two files being
   * kept in step. Footprints of the placed locations go in with it, so nothing
   * grows inside a building (finding B18), and the rings of the areas stacked
   * ABOVE this one, so only the topmost area of a spot scatters there.
   *
   * WHAT IS DRAWN OF IT is not decided here either: the finished entry is
   * handed straight to `binProp` with the camera of the last tick, so a
   * rebuild (a terrain refetch, a new relief) comes into the world with the
   * instances the camera deserves RIGHT NOW — and asks for the full-detail
   * mesh of a far-away wood exactly as little as the tick would. Without a
   * camera yet (the very first build) everything is drawn on the cheap mesh
   * until the first tick, which is a second at most and never a bare ground.
   */
  function buildScatter(area: TerrainArea, ring: Point2[], areaM2: number,
                        occluders: Point2[][], sink: { dispose(): void }[],
                        centre: THREE.Vector3
  ): ScatterProp[] {
    const out: ScatterProp[] = [];
    // ONE wind question per area, not per entry: how hard it BLOWS hangs on
    // the KIND of the painted shape (§ A9), so a meadow's tufts and its trees
    // can never disagree about the weather. How much each of them takes part
    // in it is the entry's own `sway_factor` below.
    const sway = swayFor(area.kind);
    readScatterList(area).forEach((entry, index) => {
      const points = scatterInstances({
        ring,
        areaM2,
        densityPer100m2: Number(entry.density_per_100m2 ?? 0),
        seed: scatterSeed(area.id, index),
        footprints,
        occluders,
      });
      if (!points.length) return;

      // An entry WITH a model gets its cone at the height the mesh will have —
      // the cone is that prop's stand-in, and a knee-high one that turns into
      // an 8 m tree is a pop where the sizes could simply agree. Only the
      // built-in tuft (no model at all) keeps the hip-high tuft size.
      const h = entry.model
        ? scatterTargetH(entry.height_m, entry.prop_height_m)
        : (Number(entry.height_m) > 0 ? Number(entry.height_m) : TUFT_HEIGHT_M);
      // THE one place the two authors of the wind meet (§ A9): the area's
      // amplitude times this prop's factor. Everything downstream — the tuft
      // below, `mountUrl`'s material, the clone-or-share decision — reads this
      // one number off `prop.sway`, so a stone with factor 0 arrives at 0 and
      // takes the existing "no sway, no clone" path without a second rule.
      const entrySway = scatterSway(sway, entry.sway_factor);
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
        const y = heightAt(p.x, p.z);
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

      const variants = (entry.variants && typeof entry.variants === 'object')
        ? entry.variants : {};
      const model = typeof entry.model === 'string' ? entry.model : '';
      const loUrl = pickVariant(variants, 'low') || model;
      const hiUrl = pickVariant(variants, 'full') || model;
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
        // The sphere over the instances themselves, padded by how tall the
        // prop stands and how far the wind takes it — see `ScatterProp.sphere`
        // for the two jobs it does. Both meshes share it: they hold subsets of
        // these very positions, and nothing writes into it after this line.
        sphere: instanceSphere(pos, h + SWAY_MAX_M),
        hidden: false,
        disposed: false,
        variants,
        model,
        loUrl,
        hiUrl,
        // A prop whose two tiers resolve to the same file is ONE mesh, and so
        // is a tuft (both URLs empty) — see `hasHigh`.
        hasHigh: !!hiUrl && hiUrl !== loUrl,
        // The authored height wins, the prop's real one governs when none was
        // authored, the flat fallback is the last resort (§ A9).
        targetH: scatterTargetH(entry.height_m, entry.prop_height_m),
        sway: entrySway,
        near: centre,
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

  function clearAreas(): void {
    for (const a of areaMeshes) {
      group.remove(a.mesh);
      a.mesh.geometry.dispose();
      for (const prop of a.scatter) {
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
    }
    areaMeshes.length = 0;
    drain(areaOwned);
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
  /**
   * A painted area, cut on the ground grid and laid on the relief.
   *
   * The flat geometry of `buildAreaGeometry` is a handful of big triangles
   * from earcut; over a hill those four corners would drape and the metres in
   * between would cut straight through it. So the triangles are clipped along
   * the SAME grid lines the base plate is built on (`subdivideOnGrid`) and
   * every vertex is lifted by the field. The UVs survive because they are
   * world metres and the cut interpolates them linearly — a texture that ran
   * seamlessly across an area border still does.
   *
   * AND IT CARRIES ITS OWN RIM. Every vertex gets the distance to the nearest
   * edge of the area's ring as the `aEdgeDist` attribute, which is what lets
   * the ground shader fade the area out over its last metre and a half
   * (`scene/naturalGround.ts`, stage 4) instead of ending it on a drawn line.
   * The ring is known HERE and nowhere else — the fragment shader has no idea
   * what shape it is drawing — and the same pass refines the triangles
   * wherever that distance cannot be interpolated across one
   * (`ngRefineEdgeBand`): a flat world's earcut triangles have all three
   * corners ON the ring, and a linear reading of "0, 0, 0" would fade the
   * whole area away. The refinement happens AFTER the lift, so it splits the
   * drape's own planes and describes the very same surface.
   *
   * A `null` ring is a kind that gets NO fringe — water, today: its material
   * carries its own shader and never compiles the branch, so refining its
   * triangles and filling a buffer nothing reads would be work for a picture
   * that does not change.
   *
   * The input geometry is consumed: it is read out and disposed here, because
   * from that moment on nothing else knows about it.
   */
  function drapeArea(flat: THREE.BufferGeometry,
                     ring: readonly Point2[] | null): THREE.BufferGeometry {
    const ov = relief.overview;
    const src = flat.index ? flat.toNonIndexed() : flat;
    const pos = Array.from(src.getAttribute('position').array as ArrayLike<number>);
    const uvAttr = src.getAttribute('uv');
    const uv = uvAttr ? Array.from(uvAttr.array as ArrayLike<number>) : null;
    if (src !== flat) src.dispose();
    flat.dispose();
    // The relief cut, when there is a relief: without one the earcut triangles
    // go into the band refinement as they are — they lie flat, and flat is the
    // one thing a subdivision would not change about them.
    let cutPos = pos;
    let cutUv = uv;
    if (cellM > 0 && ov) {
      const cut = subdivideOnGrid(pos, uv, cellM, ov.origin_x, ov.origin_z);
      cutPos = cut.pos;
      cutUv = uv ? cut.uv : null;
      liftToField(cutPos);
    }
    const band = ring ? ngRefineEdgeBand(cutPos, cutUv, ring) : null;
    const outPos = band ? band.pos : cutPos;
    const outUv = band ? band.uv : cutUv;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(outPos, 3));
    if (outUv) geo.setAttribute('uv', new THREE.Float32BufferAttribute(outUv, 2));
    if (band) {
      geo.setAttribute(NG_EDGE_ATTRIBUTE, new THREE.Float32BufferAttribute(band.dist, 1));
    }
    geo.computeVertexNormals();
    geo.computeBoundingSphere();
    return geo;
  }

  async function rebuildAreas(): Promise<void> {
    const areas = payload?.areas ?? [];
    // Textures first, ALL of them: `surfaceFor` only hands out fully loaded
    // images (a clone of a loading texture stays blank), so the whole ground
    // is built once the library has what it needs.
    const kinds = new Set<string>([payload?.default_kind || '',
      ...areas.map((a) => a.kind)]);
    await Promise.all([...kinds].map((k) => preloadSurfaceTexture(k)));

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
    areas.forEach((area, index) => {
      const built = builtAreas[index];
      if (!built) return;   // a ring that encloses nothing has nothing to draw
      // WHO GETS A FRINGE is decided once, here, and reaches the geometry and
      // the material as the same answer — the class the material is built from
      // (`isWaterClass`, the very source `materialFor` reads). A lake keeps its
      // hard shore, and its drape is spared the refinement and the attribute.
      const softEdge = !isWaterClass(surfaceMaterialSpec(area.kind)?.class);
      // 1 m per UV unit: the shape geometry's UVs are the world coordinates,
      // so the texture runs seamlessly across area borders.
      const mesh = new THREE.Mesh(drapeArea(built.geometry, softEdge ? built.ring : null),
                                  materialFor(area.kind, 1, nextOwned, softEdge));
      mesh.receiveShadow = true;
      // LIST ORDER decides what covers what — the server sorted the areas
      // bottom to top (z_order, then paint order), so the index IS the layer.
      //
      // AND SINCE THE FRINGE, that order is also the BLEND order. The drapes
      // are transparent materials now (`applyNaturalGround`, stage 4), so
      // three draws them in the transparent pass, sorted by `renderOrder`
      // rather than by distance: area 1 is on the screen before area 2 blends
      // over it. The ladder starts at `AREA_RENDER_ORDER_BASE`, which is what
      // keeps the ground UNDER the overlays of the world (read it — a natural
      // 1, 2, 3 would paint the drapes over every selection ring and over the
      // fog). Nothing here changes about DEPTH: the drapes still write it,
      // still ride the `polygonOffset` ladder below and still sit on the
      // sub-millimetre y ladder, which together are what keeps coplanar ground
      // from z-fighting. A transparent material that stopped writing depth
      // would gain nothing (the pass is already ordered) and would lose the
      // ground its occlusion of what is drawn after it.
      mesh.renderOrder = AREA_RENDER_ORDER_BASE + index + 1;
      const mat = mesh.material as THREE.Material;
      const bias = -Math.min((index + 1) * AREA_POLYGON_OFFSET, AREA_OFFSET_MAX);
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = bias;
      mat.polygonOffsetUnits = bias;
      // The hairline lift rides ON TOP of the sampled height: the vertices
      // carry the relief, this adds the fraction of a millimetre that keeps a
      // driver with a weak depth bias from tearing two coplanar areas apart.
      mesh.position.y = Math.min((index + 1) * AREA_Y_STEP_M, AREA_Y_MAX_M);
      mesh.userData.terrainKind = area.kind;
      mesh.userData.terrainAreaId = area.id;

      // The CLEANED ring, the one the mesh was built from — see `ringBounds`.
      const [minX, minZ, maxX, maxZ] = ringBounds(built.ring);
      // Everything painted OVER this area hides the ground it grows on.
      const occluders = builtAreas.slice(index + 1)
        .filter((b): b is NonNullable<typeof b> => !!b)
        .map((b) => b.ring);
      // The area's centre, and it is no longer a LOD distance: every scatter
      // entry binds its own instances against their own distances (`binProp`,
      // called from `buildScatter`). What the centre still answers is WHERE
      // the props of this area stand, which is how the asset queue decides
      // which wood to fetch first.
      const centre = new THREE.Vector3((minX + maxX) / 2,
                                       heightAt((minX + maxX) / 2, (minZ + maxZ) / 2),
                                       (minZ + maxZ) / 2);
      const scatter = buildScatter(area, built.ring, built.areaM2, occluders,
                                   nextOwned, centre);
      next.push({ mesh, scatter, centre });
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
        ring: built.ring,
        bounds: [minX, minZ, maxX, maxZ],
        value: undergrowthFor(area.kind),
        color: kindColor(area.kind),
        swayM: swayFor(area.kind),
      });
    });

    // THE SWAP. Nothing above touched the scene, so the old ground stood until
    // this line and the new one is in place before the frame after it.
    clearAreas();
    for (const a of next) {
      group.add(a.mesh);
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
      relief.tileM = Number(payload.tile_m) || 0;
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
      // The tiles ray their ground from above the WORLD, so the relief moves
      // the start of that ray — see `setWorldRayStart`.
      setWorldRayStart(fieldRange.max);
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
        setWorldRayStart(fieldRange.max);
        cellM = cellFor(lastBounds);
        await rebuildAreas();
        rebuildBase(lastBounds);
      }
    } finally {
      tilesBusy = false;
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
    for (const a of payload?.areas ?? []) {
      if (pointInRing(x, z, a.polygon)) hit = a.kind || '';
    }
    const kind = hit || payload?.default_kind || '';
    const entry = catalog.get(kind.toLowerCase());
    if (!entry) {
      return { kind, passable: true, speed_factor: 1, move_anim: '',
        idle_anim: '', move_sink_m: 0, idle_sink_m: 0 };
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
      } catch {
        // Keep whatever stands. `loadedSig` is deliberately NOT advanced, so
        // the next poll with the same signature tries again.
        ok = false;
      }
    }
    cellM = cellFor(bounds);
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
      footprints = locations;
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
        cellM = cellFor(bounds);
        rebuildBase(bounds);
        if (!fpMoved) {
          // THE IDLE POLL IS THE TILE LOADER'S SECOND OCCASION (§ A16.3): the
          // anchor kicks it when it crosses a tile border, and this catches
          // everything that missed — a batch whose request failed, a want set
          // computed before the index arrived. It costs a set difference when
          // there is nothing to fetch.
          void refreshTiles();
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
    },
    heightAt,
    fieldHeightAt,
    groundPointAt(ray) {
      if (!baseMesh) return null;
      const hits = ray.intersectObject(baseMesh, false);
      return hits.length ? hits[0].point.clone() : null;
    },
    // BOTH GET `cellM`, and that is the whole of task 3's finding 1: the tiles
    // bring a 4 m lattice while the plate over a large world is cut at 8 m or
    // more, and over such a cell the drawn ground stands up to a quarter of the
    // cell's twist above every reading the fine grid takes. A veil hung on the
    // fine grid alone would hang inside the hill it covers.
    maxHeightIn: (x0, z0, x1, z1) => (
      hasRelief() ? maxCompositeHeightIn(relief, x0, z0, x1, z1, cellM) : GROUND_Y),
    heightRangeIn: (x0, z0, x1, z1) => (
      hasRelief() ? compositeHeightRangeIn(relief, x0, z0, x1, z1, cellM) : 0),
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
    dispose() {
      clearAreas();
      if (baseMesh) {
        group.remove(baseMesh);
        baseMesh.geometry.dispose();
        baseMesh = null;
      }
      drain(baseOwned);
      drain(areaOwned);
      // The height texture of the ground shader is module state, not a member
      // of this closure, so it outlives the group it was built for — hand it
      // back explicitly or a client that tears its world down keeps the whole
      // overview on the GPU.
      setNaturalGroundField(null);
      // …and the camera-local layer, for the same reason: its blade texture,
      // its one geometry and its material per kind outlive every rebuild and
      // are in no `*Owned` bag, so this is the only place they are freed.
      undergrowth.dispose();
    },
  };
}
