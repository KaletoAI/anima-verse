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
 *    prop scatter and its distance cut-off.
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
 */
import * as THREE from 'three';
import { AREA_POLYGON_OFFSET, buildAreaGeometry, gridPlate, gridStepFor,
  maxWorldHeightIn, pointInRing, propGroundFit, sampleGroundHeight,
  sampleWorldHeight, scatterInstances, scatterSeed, subdivideOnGrid,
  surfaceMaterial, worldHeightRange, worldHeightRangeIn } from '@anima/scene-render';
import type { GridBox, Point2, ScatterEntry, ScatterFootprint,
  SurfaceMaterialSpec, WorldHeightField } from '@anima/scene-render';
import { fetchHeightfield, fetchTerrain } from '../api';
import { footprintSignature, TERRAIN_FALLBACK_COLOR } from '../game/minimap';
import type { MapLocation, TerrainArea, TerrainPayload, TerrainType, WorldBounds } from '../types';
import { preloadSurfaceTexture, setWorldGround, setWorldRayStart, surfaceFor,
  surfaceMaterialSpec } from './tiles';
import { loadGlb } from './propAssets';

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

/** Fallback tuft size when a scatter entry names no model — HIP-HIGH next to a
 *  1.70 m figure, not knee-high (finding 2 of the E8 acceptance round: the old
 *  0.55 m / 0.16 m tuft read as moss from eye level). ONE place for the two
 *  numbers. */
const TUFT_RADIUS_M = 0.22;
const TUFT_HEIGHT_M = 0.8;
/** Target height of a scattered GLB that declares no `height_m` (metres).
 *
 *  A prop file carries whatever size its author chose, and "whatever the file
 *  says" is not a size in a world measured in metres — a tree exported in
 *  centimetres stood 2 cm tall next to the figure. So an undeclared model is
 *  normalised to a shrub/small-tree height instead of being trusted; an author
 *  who wants another size says so in `height_m` (the editor now pre-fills it). */
const SCATTER_MODEL_HEIGHT_M = 2.0;

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

/** Give a ground material the hole test. Idempotent per material — each one is
 *  created once per rebuild and patched right here. */
function patchHole(mat: THREE.Material): void {
  mat.onBeforeCompile = (shader) => {
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
  // One cache key for every ground material: they differ in maps and colours,
  // not in the patch, and three.js keys the compiled program on this string
  // PLUS the material's own defines.
  mat.customProgramCacheKey = () => 'ground-hole';
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
  /** one instanced scatter per authored entry — empty when nothing grows here
   *  (finding B17: the list hangs on the AREA, not on the terrain type) */
  scatter: THREE.InstancedMesh[];
  /** centre of the area's bounding box — the distance the LOD measures */
  centre: THREE.Vector3;
  /** half the diagonal of the bounding box, so a big area is not hidden
   *  because its CENTRE is far while its edge is under the camera */
  radius: number;
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
  /** Hide the prop scatter beyond `farM` metres from the camera. Called by the
   *  1 Hz LOD tick of `main.ts` — the hysteresis of the model tiers lives
   *  there, this is a plain visibility switch on top of it. */
  tickScatterLod(cameraPos: THREE.Vector3, farM: number): void;
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
   * WILDERNESS only (footprint wins, § A15), `speed_factor` and `move_anim`
   * count everywhere (finding 3). The rules that combine each with the
   * footprint live in `game/walk.ts` (`terrainBlocks`, `terrainPace`,
   * `moveClip`) and every caller goes through them — never through this
   * answer alone.
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

/**
 * The scatter list an area declares, read through a check.
 *
 * `meta` is free-form JSON the server passes through, so nothing in the type
 * system guarantees a stored `scatter` has the declared shape — an old area
 * still carries none at all. The server whitelists what it stores
 * (`app/models/terrain._sanitize_scatter_list`); this is the reader's half of
 * the same contract, and anything that is not a list of objects grows nothing.
 */
function readScatterList(area: TerrainArea): ScatterEntry[] {
  const raw = (area.meta as { scatter?: unknown } | undefined)?.scatter;
  if (!Array.isArray(raw)) return [];
  return raw.filter((e): e is ScatterEntry => !!e && typeof e === 'object');
}

export function createGround(): Ground {
  const group = new THREE.Group();
  group.name = 'terrain-ground';

  let payload: TerrainPayload | null = null;
  let loadedSig: string | null = null;
  let inFlight: Promise<boolean> | null = null;
  let rev = 0;

  /** The world relief (§ A16) and the signature it was fetched for. `null`
   *  means "not yet arrived", which answers a flat world — the same answer a
   *  world without a single authored hill gives, and deliberately so: nothing
   *  waits for the field, the ground is simply draped again when it lands. */
  let field: WorldHeightField | null = null;
  let loadedHeightSig: string | null = null;
  let heightRev = 0;
  /** `worldHeightRange(field)`, taken ONCE when the field arrives. It walks
   *  every support point (up to 120 000 of them, § A16) and both readers ask
   *  on the poll path — the ray start when the field lands, the cell size on
   *  every single sync. */
  let fieldRange = { min: 0, max: 0 };
  /** The cell size plate and areas are cut at — ONE for the whole ground, so
   *  the two always meet on the same lines (`gridStepFor`, gridMesh.ts). 0
   *  while there is no relief at all: then nothing is subdivided. */
  let cellM = 0;

  /**
   * The ground under a point — the DRAWN one (`sampleGroundHeight`), not the
   * bilinear field.
   *
   * The mesh is triangles: within a cell the plate is two planes, and a vertex
   * or a figure placed at the field's bilinear reading sits off that surface by
   * up to a quarter of the cell's twist — a measured metre on a 5 m hill with a
   * 10 m falloff. ONE sampler for the plate, the areas, the props and every
   * figure is what makes them describe one surface (§ A16).
   */
  const heightAt = (x: number, z: number): number =>
    (field ? sampleGroundHeight(field, x, z, cellM) : GROUND_Y);

  /** The BILINEAR reading of the field — the server's own (see the interface).
   *  Used by the walk-rule mirror, never by anything that is drawn. */
  const fieldHeightAt = (x: number, z: number): number =>
    (field ? sampleWorldHeight(field, x, z) : GROUND_Y);

  // THE GROUND HOOK (E8 task 4): a location's tile stands on the ground under
  // its centre, and this is where `scene/tiles.ts` gets that height from. The
  // sampler is a closure over `field`/`cellM`, so it stays correct across every
  // refetch without anyone re-registering it — and it is the DRAWN ground on
  // purpose: the tile has to sit on the surface the player sees. Under a
  // footprint that levels its ground (`level_ground`, § A16.1, opt-in) the two
  // readings agree anyway, because the server flattens the field there.
  setWorldGround(heightAt);

  /** Lift a flat vertex list onto the ground, in place. `pos` is `[x, y, z, …]`
   *  in WORLD metres (both the plate and the subdivided areas are), so the
   *  sample point is the vertex itself. */
  function liftToField(pos: number[]): void {
    if (!field) return;
    for (let i = 0; i < pos.length; i += 3) {
      pos[i + 1] += sampleGroundHeight(field, pos[i], pos[i + 2], cellM);
    }
  }

  /** The box the FIELD describes (§ A16): `origin + (cols−1) · step`. Outside
   *  it the ground is the field's border value, which the server pins to 0 —
   *  flat, and the plate covers it with plain quads. `null` = no relief. */
  function reliefBox(): GridBox | null {
    const rows = field?.heights?.length ?? 0;
    const cols = field?.heights?.[0]?.length ?? 0;
    const step = field?.step_m ?? 0;
    if (!field || rows < 2 || cols < 2 || !(step > 0)) return null;
    return {
      x0: field.origin_x,
      z0: field.origin_z,
      x1: field.origin_x + (cols - 1) * step,
      z1: field.origin_z + (rows - 1) * step,
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
   */
  function materialFor(kind: string, uvScaleM: number,
                       sink: { dispose(): void }[]): THREE.Material {
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
   * A field of nothing but zeroes is FLAT and says so: today's worlds have no
   * relief at all, and giving them forty thousand cells for a surface that is
   * level would be paid every rebuild for nothing.
   */
  function cellFor(bounds: WorldBounds | null): number {
    const step = field?.step_m ?? 0;
    const relief = reliefBox();
    if (!(step > 0) || !relief) return 0;
    if (fieldRange.min === 0 && fieldRange.max === 0) return 0;
    const [px0, pz0, px1, pz1] = plateExtent(bounds);
    // The budget is spent where there IS relief: the field's box, clipped to
    // what the plate shows of it. A hill in the corner of a huge world keeps
    // the native cell size instead of paying for the plain around it.
    const x0 = Math.max(px0, relief.x0);
    const z0 = Math.max(pz0, relief.z0);
    const x1 = Math.min(px1, relief.x1);
    const z1 = Math.min(pz1, relief.z1);
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
                            Math.max(wantZ1, wantZ0 + 1),
                            cellM, field?.origin_x ?? 0, field?.origin_z ?? 0,
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
   * Deterministic prop scatter of one area — ONE InstancedMesh per entry.
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
   */
  function buildScatter(area: TerrainArea, ring: Point2[], areaM2: number,
                        occluders: Point2[][], sink: { dispose(): void }[]
  ): THREE.InstancedMesh[] {
    const out: THREE.InstancedMesh[] = [];
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

      const h = Number(entry.height_m) > 0 ? Number(entry.height_m) : TUFT_HEIGHT_M;
      // v1 prop: a low cone in the kind's own colour. A `model` URL is honoured
      // asynchronously below — the tufts stand immediately and are replaced by
      // the mesh when it arrives, so a slow asset never delays the ground.
      const geo = new THREE.ConeGeometry(TUFT_RADIUS_M, h, 5);
      geo.translate(0, h / 2, 0);
      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(kindColor(area.kind)).multiplyScalar(0.75),
        roughness: 0.95,
      });
      sink.push(geo, mat);
      // Typed on the BASE classes: the `model` branch below swaps geometry and
      // material for the loaded ones, which are not a cone and not this material.
      const inst: THREE.InstancedMesh<THREE.BufferGeometry, THREE.Material>
        = new THREE.InstancedMesh(geo, mat, points.length);
      // One of each, reused: a big meadow places thousands of instances, and a
      // fresh Vector3 per instance is garbage for nothing.
      const m = new THREE.Matrix4();
      const q = new THREE.Quaternion();
      const up = new THREE.Vector3(0, 1, 0);
      const at = new THREE.Vector3();
      const s = new THREE.Vector3(1, 1, 1);
      points.forEach((p, i) => {
        q.setFromAxisAngle(up, p.yaw);
        // EVERY instance samples its own ground (§ A16): the sampler decides
        // where the tuft stands, the scatter only where it stands in XZ. A
        // shared height would float half a wood over the slope it grows on.
        // The props stay UPRIGHT on a slope — a tree grows towards the sky,
        // and tilting one into the surface normal is a look, not a fix.
        m.compose(at.set(p.x, heightAt(p.x, p.z), p.z), q, s);
        inst.setMatrixAt(i, m);
      });
      inst.instanceMatrix.needsUpdate = true;
      inst.castShadow = false;
      inst.frustumCulled = true;

      if (entry.model) {
        // The declared model REPLACES the tuft geometry in place: same instance
        // matrices, same count. Only the first mesh of the file is used — a prop
        // that is really several meshes is a v2 problem, and a silently missing
        // prop would be worse than a simplified one.
        void loadGlb(entry.model).then((obj) => {
          // A terrain refetch between request and answer took this instance out
          // of the scene and disposed it — writing into it would resurrect
          // nothing and hold the loaded mesh alive. The test is the DISPOSED
          // mark `clearAreas` leaves, not the parent: since the build-then-swap
          // an instance is legitimately parentless for as long as its rebuild
          // takes, and reading that as "gone" would drop the model of every
          // prop whose file arrives before the swap.
          if (!obj || inst.userData.disposed) return;
          let src: THREE.Mesh | null = null;
          obj.traverse((o) => { if (!src && (o as THREE.Mesh).isMesh) src = o as THREE.Mesh; });
          if (!src) return;
          const mesh = src as THREE.Mesh;
          // `height_m` is the TARGET height since B17: the prop is scaled until
          // its bounding box is that tall, and grounded either way (B16).
          // Without one the model is NOT instanced at its authored size — it is
          // normalised to `SCATTER_MODEL_HEIGHT_M`, see there.
          const geometry = groundedGeometry(
            mesh, Number(entry.height_m) > 0
              ? Number(entry.height_m) : SCATTER_MODEL_HEIGHT_M);
          // The clone is OURS and nothing else disposes it — the owned bag of
          // this rebuild was drained into `areaOwned` long before this answer
          // arrived (the load is asynchronous, the swap is not). So it rides on
          // the instance and `clearAreas` frees it with the instance.
          inst.userData.ownedGeometry = geometry;
          inst.geometry = geometry;
          inst.material = mesh.material as THREE.Material;
        }).catch(() => { /* the tuft stands; a missing prop is not a broken world */ });
      }
      out.push(inst);
    });
    return out;
  }

  function clearAreas(): void {
    for (const a of areaMeshes) {
      group.remove(a.mesh);
      a.mesh.geometry.dispose();
      for (const inst of a.scatter) {
        group.remove(inst);
        // The mark a pending `loadGlb` reads — see `buildScatter`.
        inst.userData.disposed = true;
        // The grounded CLONE of a loaded prop, if one arrived (see there).
        // `InstancedMesh.dispose` frees the instance buffers, never the
        // geometry, and this one belongs to nobody else.
        const owned = inst.userData.ownedGeometry as THREE.BufferGeometry | undefined;
        if (owned) owned.dispose();
        inst.dispose();
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
   * The input geometry is consumed: it is either handed back untouched (a flat
   * world subdivides nothing) or disposed here, because from that moment on
   * nothing else knows about it.
   */
  function drapeArea(flat: THREE.BufferGeometry): THREE.BufferGeometry {
    if (!(cellM > 0) || !field) return flat;
    const src = flat.index ? flat.toNonIndexed() : flat;
    const pos = Array.from(src.getAttribute('position').array as ArrayLike<number>);
    const uvAttr = src.getAttribute('uv');
    const uv = uvAttr ? Array.from(uvAttr.array as ArrayLike<number>) : null;
    if (src !== flat) src.dispose();
    flat.dispose();
    const cut = subdivideOnGrid(pos, uv, cellM, field.origin_x, field.origin_z);
    liftToField(cut.pos);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(cut.pos, 3));
    if (uv) geo.setAttribute('uv', new THREE.Float32BufferAttribute(cut.uv, 2));
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
    // ALL geometries first, in list order — the scatter of an area needs the
    // rings of the areas ABOVE it (see `buildScatter`), and the list order is
    // the stacking order the server sorted (z_order ASC, created_at ASC).
    // `null` = a ring that encloses nothing: it draws nothing and covers
    // nothing. Each area is still built exactly once.
    const builtAreas = areas.map((area) => buildAreaGeometry(THREE, area.polygon));
    areas.forEach((area, index) => {
      const built = builtAreas[index];
      if (!built) return;   // a ring that encloses nothing has nothing to draw
      // 1 m per UV unit: the shape geometry's UVs are the world coordinates,
      // so the texture runs seamlessly across area borders.
      const mesh = new THREE.Mesh(drapeArea(built.geometry),
                                  materialFor(area.kind, 1, nextOwned));
      mesh.receiveShadow = true;
      // LIST ORDER decides what covers what — the server sorted the areas
      // bottom to top (z_order, then paint order), so the index IS the layer.
      mesh.renderOrder = index + 1;
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
      const scatter = buildScatter(area, built.ring, built.areaM2, occluders,
                                   nextOwned);
      next.push({
        mesh,
        scatter,
        centre: new THREE.Vector3((minX + maxX) / 2,
                                  heightAt((minX + maxX) / 2, (minZ + maxZ) / 2),
                                  (minZ + maxZ) / 2),
        radius: Math.hypot(maxX - minX, maxZ - minZ) / 2,
      });
    });

    // THE SWAP. Nothing above touched the scene, so the old ground stood until
    // this line and the new one is in place before the frame after it.
    clearAreas();
    for (const a of next) {
      group.add(a.mesh);
      for (const inst of a.scatter) group.add(inst);
      areaMeshes.push(a);
    }
    areaOwned.push(...nextOwned);
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
      field = await fetchHeightfield();
      loadedHeightSig = field.sig || heightSig;
      heightRev += 1;
      fieldRange = worldHeightRange(field);
      // The tiles ray their ground from above the WORLD, so the relief moves
      // the start of that ray — see `setWorldRayStart`.
      setWorldRayStart(fieldRange.max);
      return true;
    } catch {
      return false;
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
    if (!entry) return { kind, passable: true, speed_factor: 1, move_anim: '' };
    return {
      kind,
      passable: entry.passable !== false,
      speed_factor: Number.isFinite(entry.speed_factor) ? entry.speed_factor : 1,
      move_anim: String(entry.meta?.move_anim ?? '').trim(),
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
      if (inFlight) return inFlight;
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
        if (!fpMoved) return Promise.resolve(false);
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
    heightAt,
    fieldHeightAt,
    groundPointAt(ray) {
      if (!baseMesh) return null;
      const hits = ray.intersectObject(baseMesh, false);
      return hits.length ? hits[0].point.clone() : null;
    },
    maxHeightIn: (x0, z0, x1, z1) => (
      field ? maxWorldHeightIn(field, x0, z0, x1, z1, cellM) : GROUND_Y),
    heightRangeIn: (x0, z0, x1, z1) => (
      field ? worldHeightRangeIn(field, x0, z0, x1, z1, cellM) : 0),
    heightRevision: () => heightRev,
    setHole(rect) {
      holeOn.value = rect ? 1 : 0;
      if (rect) holeRect.value.set(rect[0], rect[1], rect[2], rect[3]);
    },
    tickScatterLod(cameraPos, farM) {
      for (const a of areaMeshes) {
        if (!a.scatter.length) continue;
        // Distance to the area's bounding SPHERE, not to its centre: a large
        // meadow is under the camera long before its centre is.
        const d = cameraPos.distanceTo(a.centre) - a.radius;
        const on = d <= farM;
        for (const inst of a.scatter) inst.visible = on;
      }
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
    },
  };
}
