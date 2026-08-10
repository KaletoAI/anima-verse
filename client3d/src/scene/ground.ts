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
 * GROUND_Y DISCIPLINE. Every vertex sits at y = 0 and stays there. Stacked
 * areas are separated by `renderOrder` + a depth bias, not by a height ladder
 * — a metre world whose meadow floats above its path would show a step at
 * every edge the moment relief arrives. The only exception is a sub-millimetre
 * lift, capped at one centimetre in total (`AREA_Y_MAX_M`), which is there for
 * the drivers whose depth bias is too weak to separate coplanar faces.
 *
 * REFETCH. The terrain is never fogged, so it is fetched ONCE and again only
 * when the worldmap poll reports a different `terrain_sig` — `sync()` takes
 * that signature and does nothing while it is unchanged.
 */
import * as THREE from 'three';
import { AREA_POLYGON_OFFSET, buildAreaGeometry, surfaceMaterial } from '@anima/scene-render';
import type { Point2, SurfaceMaterialSpec } from '@anima/scene-render';
import { fetchTerrain } from '../api';
import type { TerrainArea, TerrainPayload, TerrainScatterMeta, TerrainType, WorldBounds } from '../types';
import { preloadSurfaceTexture, surfaceFor, surfaceMaterialSpec } from './tiles';
import { seededRandom } from './textures';
import { loadGlb } from './propAssets';

/** The world's ground height. v1 of the seamless world is flat, and this
 *  constant is the single place that says so — nothing computes a ground y of
 *  its own (plan § D: `ground_y(x, z)` is the ground truth). */
export const GROUND_Y = 0;

/** How far the base plane reaches beyond `world_bounds`, in metres. The bounds
 *  end at the outermost footprint; a player walking out there must not fall off
 *  the visible world. */
const BASE_MARGIN_M = 60;
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

/** Scatter instances are never more than this per area, whatever the density
 *  says. A hand-typed `density_per_100m2` on a lake-sized meadow would
 *  otherwise build a hundred thousand instances in one frame. */
const SCATTER_MAX_PER_AREA = 2000;
/** Rejection sampling gives up after this many misses per wanted instance —
 *  a very thin or very concave ring can reject most of its bounding box. */
const SCATTER_TRIES_PER_POINT = 12;
/** Fallback tuft size when `meta.scatter` names no model. */
const TUFT_RADIUS_M = 0.16;
const TUFT_HEIGHT_M = 0.55;

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

/** One built area: what stands in the scene, plus what the scatter LOD needs. */
interface AreaMesh {
  mesh: THREE.Mesh;
  /** instanced scatter of this area, or null when the kind scatters nothing */
  scatter: THREE.InstancedMesh | null;
  /** centre of the area's bounding box — the distance the LOD measures */
  centre: THREE.Vector3;
  /** half the diagonal of the bounding box, so a big area is not hidden
   *  because its CENTRE is far while its edge is under the camera */
  radius: number;
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
   * Resolves to `true` when something was rebuilt. Never throws: a ground that
   * could not be fetched leaves the previous one standing (and the very first
   * failure leaves the base plane in the default look), because a client that
   * tears its world down over one failed poll is worse than a stale one.
   */
  sync(sig: string, bounds: WorldBounds | null): Promise<boolean>;
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

/** Even-odd ray crossing: is `(x, z)` inside the ring? Used for the scatter
 *  rejection sampling only — a point on the edge may fall either way, which
 *  moves at most one tuft by a hair. */
function pointInRing(x: number, z: number, polygon: Point2[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [xi, zi] = polygon[i];
    const [xj, zj] = polygon[j];
    if ((zi > z) !== (zj > z)
        && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

export function createGround(): Ground {
  const group = new THREE.Group();
  group.name = 'terrain-ground';

  let payload: TerrainPayload | null = null;
  let loadedSig: string | null = null;
  let inFlight: Promise<boolean> | null = null;
  let rev = 0;

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
   *  server itself uses for a kind without one. NEVER a palette of our own —
   *  the ground is data. */
  function kindColor(kind: string): string {
    return catalog.get((kind || '').toLowerCase())?.color || '#888888';
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

  /** The plane under everything, in the look of the unpainted ground. */
  function rebuildBase(bounds: WorldBounds | null): void {
    const minX = bounds ? bounds.min_x - BASE_MARGIN_M : -BASE_FALLBACK_M / 2;
    const maxX = bounds ? bounds.max_x + BASE_MARGIN_M : BASE_FALLBACK_M / 2;
    const minZ = bounds ? bounds.min_z - BASE_MARGIN_M : -BASE_FALLBACK_M / 2;
    const maxZ = bounds ? bounds.max_z + BASE_MARGIN_M : BASE_FALLBACK_M / 2;
    const w = Math.max(maxX - minX, 1);
    const d = Math.max(maxZ - minZ, 1);
    const kind = payload?.default_kind || '';
    const key = `${kind}|${minX}|${minZ}|${w}|${d}`;
    if (baseMesh && key === baseKey) return;
    if (baseMesh) {
      group.remove(baseMesh);
      baseMesh.geometry.dispose();
      baseMesh = null;
      drain(baseOwned);
    }
    baseKey = key;
    const geo = new THREE.PlaneGeometry(w, d);
    geo.rotateX(-Math.PI / 2);
    // The base tiles over its WHOLE edge, so one UV unit is `w` metres wide
    // and `d` deep. Non-square worlds would stretch the texture; the shorter
    // edge decides, which repeats a little more often than it stretches.
    const mesh = new THREE.Mesh(geo, materialFor(kind, Math.min(w, d), baseOwned));
    mesh.position.set((minX + maxX) / 2, GROUND_Y, (minZ + maxZ) / 2);
    mesh.receiveShadow = true;
    mesh.renderOrder = 0;
    baseMesh = mesh;
    group.add(mesh);
  }

  /**
   * Deterministic prop scatter of one area (v1).
   *
   * Only kinds whose catalog entry carries `meta.scatter` scatter anything —
   * there is no default, and a world that wants tufts says so in the catalog.
   * The instance count follows the AREA: `density_per_100m2` per 100 m2 of
   * ground, so the same meadow always carries the same number however it was
   * drawn.
   *
   * SEED = the area id. The generator is `seededRandom` from `textures.ts`
   * (FNV-1a over the seed string, then an xorshift-multiply step — the same
   * hash the procedural textures use), so the tufts of an area land in the
   * very same places on every client and after every reload. Positions come
   * from rejection sampling inside the ring's bounding box; a concave area
   * simply misses more often, which the try budget caps.
   */
  function buildScatter(area: TerrainArea, ring: Point2[], areaM2: number
  ): THREE.InstancedMesh | null {
    const type = catalog.get((area.kind || '').toLowerCase());
    const scatter: TerrainScatterMeta | undefined = type?.meta?.scatter;
    const density = Number(scatter?.density_per_100m2 ?? 0);
    if (!scatter || !Number.isFinite(density) || density <= 0) return null;
    const wanted = Math.min(Math.round((areaM2 / 100) * density), SCATTER_MAX_PER_AREA);
    if (wanted < 1) return null;

    const [minX, minZ, maxX, maxZ] = ringBounds(ring);
    const rnd = seededRandom(`terrain:scatter:${area.id}`);
    const points: [number, number, number][] = [];   // x, z, yaw
    let tries = wanted * SCATTER_TRIES_PER_POINT;
    while (points.length < wanted && tries > 0) {
      tries -= 1;
      const x = minX + rnd() * (maxX - minX);
      const z = minZ + rnd() * (maxZ - minZ);
      if (!pointInRing(x, z, ring)) continue;
      points.push([x, z, rnd() * Math.PI * 2]);
    }
    if (!points.length) return null;

    const h = Number(scatter.height_m) > 0 ? Number(scatter.height_m) : TUFT_HEIGHT_M;
    // v1 prop: a low cone in the kind's own colour. A `model` URL is honoured
    // asynchronously below — the tufts stand immediately and are replaced by
    // the mesh when it arrives, so a slow asset never delays the ground.
    const geo = new THREE.ConeGeometry(TUFT_RADIUS_M, h, 5);
    geo.translate(0, h / 2, 0);
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(kindColor(area.kind)).multiplyScalar(0.75),
      roughness: 0.95,
    });
    areaOwned.push(geo, mat);
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
    points.forEach(([x, z, yaw], i) => {
      q.setFromAxisAngle(up, yaw);
      m.compose(at.set(x, GROUND_Y, z), q, s);
      inst.setMatrixAt(i, m);
    });
    inst.instanceMatrix.needsUpdate = true;
    inst.castShadow = false;
    inst.frustumCulled = true;

    if (scatter.model) {
      // The declared model REPLACES the tuft geometry in place: same instance
      // matrices, same count. Only the first mesh of the file is used — a prop
      // that is really several meshes is a v2 problem, and a silently missing
      // prop would be worse than a simplified one.
      void loadGlb(scatter.model).then((obj) => {
        // A terrain refetch between request and answer took this instance out
        // of the scene and disposed it — writing into it would resurrect
        // nothing and hold the loaded mesh alive.
        if (!obj || !inst.parent) return;
        let src: THREE.Mesh | null = null;
        obj.traverse((o) => { if (!src && (o as THREE.Mesh).isMesh) src = o as THREE.Mesh; });
        if (!src) return;
        const mesh = src as THREE.Mesh;
        inst.geometry = mesh.geometry;
        inst.material = mesh.material as THREE.Material;
      }).catch(() => { /* the tuft stands; a missing prop is not a broken world */ });
    }
    return inst;
  }

  function clearAreas(): void {
    for (const a of areaMeshes) {
      group.remove(a.mesh);
      a.mesh.geometry.dispose();
      if (a.scatter) {
        group.remove(a.scatter);
        a.scatter.dispose();
      }
    }
    areaMeshes.length = 0;
    drain(areaOwned);
  }

  async function rebuildAreas(): Promise<void> {
    clearAreas();
    const areas = payload?.areas ?? [];
    // Textures first, ALL of them: `surfaceFor` only hands out fully loaded
    // images (a clone of a loading texture stays blank), so the whole ground
    // is built once the library has what it needs.
    const kinds = new Set<string>([payload?.default_kind || '',
      ...areas.map((a) => a.kind)]);
    await Promise.all([...kinds].map((k) => preloadSurfaceTexture(k)));

    areas.forEach((area, index) => {
      const built = buildAreaGeometry(THREE, area.polygon);
      if (!built) return;   // a ring that encloses nothing has nothing to draw
      // 1 m per UV unit: the shape geometry's UVs are the world coordinates,
      // so the texture runs seamlessly across area borders.
      const mesh = new THREE.Mesh(built.geometry, materialFor(area.kind, 1, areaOwned));
      mesh.receiveShadow = true;
      // LIST ORDER decides what covers what — the server sorted the areas
      // bottom to top (z_order, then paint order), so the index IS the layer.
      mesh.renderOrder = index + 1;
      const mat = mesh.material as THREE.Material;
      const bias = -Math.min((index + 1) * AREA_POLYGON_OFFSET, AREA_OFFSET_MAX);
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = bias;
      mat.polygonOffsetUnits = bias;
      mesh.position.y = GROUND_Y
        + Math.min((index + 1) * AREA_Y_STEP_M, AREA_Y_MAX_M);
      mesh.userData.terrainKind = area.kind;
      mesh.userData.terrainAreaId = area.id;
      group.add(mesh);

      // The CLEANED ring, the one the mesh was built from — see `ringBounds`.
      const [minX, minZ, maxX, maxZ] = ringBounds(built.ring);
      const scatter = buildScatter(area, built.ring, built.areaM2);
      if (scatter) group.add(scatter);
      areaMeshes.push({
        mesh,
        scatter,
        centre: new THREE.Vector3((minX + maxX) / 2, GROUND_Y, (minZ + maxZ) / 2),
        radius: Math.hypot(maxX - minX, maxZ - minZ) / 2,
      });
    });
    rev += 1;
  }

  async function reload(sig: string, bounds: WorldBounds | null): Promise<boolean> {
    try {
      payload = await fetchTerrain();
      loadedSig = payload.sig || sig;
    } catch {
      // Keep whatever stands. `loadedSig` is deliberately NOT advanced, so the
      // next poll with the same signature tries again.
      if (!payload) rebuildBase(bounds);
      return false;
    }
    rebuildCatalog();
    // Areas FIRST: `rebuildAreas` preloads the surface textures of every kind
    // in play, the default kind included. Building the base plane before that
    // would give it the flat catalog colour and never rebuild it — the key
    // below has not changed, so nothing would ever put its texture on.
    await rebuildAreas();
    rebuildBase(bounds);
    return true;
  }

  return {
    group,
    sync(sig, bounds) {
      if (inFlight) return inFlight;
      if (loadedSig !== null && loadedSig === sig) {
        // Same terrain — only the frame may have moved.
        rebuildBase(bounds);
        return Promise.resolve(false);
      }
      inFlight = reload(sig, bounds).finally(() => { inFlight = null; });
      return inFlight;
    },
    setHole(rect) {
      holeOn.value = rect ? 1 : 0;
      if (rect) holeRect.value.set(rect[0], rect[1], rect[2], rect[3]);
    },
    tickScatterLod(cameraPos, farM) {
      for (const a of areaMeshes) {
        if (!a.scatter) continue;
        // Distance to the area's bounding SPHERE, not to its centre: a large
        // meadow is under the camera long before its centre is.
        const d = cameraPos.distanceTo(a.centre) - a.radius;
        a.scatter.visible = d <= farM;
      }
    },
    payload: () => payload,
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
