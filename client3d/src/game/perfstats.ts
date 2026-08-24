/**
 * The numbers behind the performance readout (Etappe 5,
 * `development_instructions/plan-3d-lod-und-betreten.md`).
 *
 * The LOD rebuild added resolution tiers to every mesh, and until now nothing
 * in the picture said whether a tier does anything at all. These are the four
 * figures that answer that, and this module is the arithmetic behind them —
 * pure like `walk.ts` and `prefs.ts`: no DOM, no `three`, no module state, so
 * `client3d/scripts/smoke_walk_math.mjs` can hand-check every case.
 *
 * WHAT COMES FROM WHERE, and why two of the figures cannot come from
 * `renderer.info`:
 * - `renderer.info.render` gives TRIANGLES and DRAW CALLS of the last rendered
 *   frame — drawn geometry, so frustum culling is already in those numbers.
 *   Nothing to compute, the caller reads them straight off.
 * - It does NOT give a vertex count, so `visibleVertices` sums
 *   `geometry.attributes.position.count` over the visible graph itself.
 *   Mind the difference in meaning: this counts what is VISIBLE (the
 *   `visible` flag, the fade of a closed location), not what is DRAWN — a
 *   mesh behind the camera still counts here. That is the wanted reading for
 *   a LOD display: it says what the tier choice put into the scene, not where
 *   the camera happens to point.
 * - The tier split has no renderer source at all: it is the client's own
 *   placement ledger (`tile.placedModels`), one record per mounted model with
 *   the URL it currently stands on.
 *
 * None of this runs per frame except `pushFrame`. A traversal of the whole
 * graph on every frame would distort exactly the figure it measures — the
 * caller runs the heavy part on the ~1 Hz LOD tick.
 */
import type { ModelTier } from '@anima/scene-render';

/** One complete readout — what the overlay shows, filled by the caller from
 *  the three sources above. */
export interface PerfStats {
  /** frames per second, smoothed over the last second (`pushFrame`) */
  fps: number;
  /** triangles DRAWN in the last frame (`renderer.info.render.triangles`) */
  triangles: number;
  /** draw calls of the last frame — the cost centre of scattered props, where
   *  every copy is its own call until instancing lands */
  calls: number;
  /** vertices VISIBLE in the scene graph (`visibleVertices`) */
  vertices: number;
  /** geometries/textures held on the GPU (`renderer.info.memory`) */
  geometries: number;
  textures: number;
  /** how many mounted models stand on which resolution tier */
  tiers: TierCounts;
  /** what the ground scatter submits per frame, split into its two render
   *  stages (`scatterCosts`) — the figure that says WHICH half of the scatter
   *  a frame is spent in */
  scatter: ScatterCounts;
  /** how long the last 1 Hz scatter/undergrowth LOD pass took, in
   *  milliseconds — the CPU half of the same question (0 while nothing has
   *  been measured yet) */
  scatterLodMs: number;
}

// --- FPS ------------------------------------------------------------------

/** Length of the averaging window in seconds. One second is what the eye
 *  needs: shorter and the number flickers with every hitch, longer and a
 *  stutter you can feel does not show up. */
export const FPS_WINDOW_S = 1;
/** Hard cap on the sample list, so a machine drawing far above 240 fps (or a
 *  runaway caller) cannot grow it without bound. Above the cap the window is
 *  shorter than a second — at those rates nobody is reading the number to
 *  diagnose anything. */
export const FPS_MAX_SAMPLES = 240;

/** Sliding window of frame times. Hand it to `pushFrame` once per frame. */
export interface FpsMeter {
  /** frame durations in seconds, oldest first */
  samples: number[];
  /** sum of `samples` — kept alongside so no frame re-adds the whole list */
  sum: number;
}

export function newFpsMeter(): FpsMeter {
  return { samples: [], sum: 0 };
}

/**
 * Add one frame time (seconds) and return the smoothed rate.
 *
 * Mutates the meter on purpose: this is the one thing here that runs 60 times
 * a second, and a fresh object per frame would be litter for the collector.
 * The result stays a pure function of the frames pushed so far.
 *
 * A `dt` that is not a positive finite number is IGNORED (the reading is kept
 * as it was): `THREE.Clock` hands out a 0 on the very first frame, and a
 * paused tab can produce values no rate should be derived from.
 *
 * The window drops from the front while the sum EXCEEDS `FPS_WINDOW_S`, never
 * emptying it — so a single huge frame time survives as itself (a 2 s freeze
 * reads 0.5 fps) instead of vanishing and showing a stale rate.
 */
export function pushFrame(meter: FpsMeter, dt: number): number {
  if (!Number.isFinite(dt) || dt <= 0) return fpsOf(meter);
  meter.samples.push(dt);
  meter.sum += dt;
  while (meter.samples.length > 1
         && (meter.sum > FPS_WINDOW_S || meter.samples.length > FPS_MAX_SAMPLES)) {
    meter.sum -= meter.samples.shift() as number;
  }
  return fpsOf(meter);
}

/** Current reading without adding a frame (0 while nothing was pushed). */
export function fpsOf(meter: FpsMeter): number {
  return meter.sum > 0 ? meter.samples.length / meter.sum : 0;
}

// --- Vertices -------------------------------------------------------------

/**
 * The bit of `THREE.Object3D` this module needs — structural, so the smoke
 * check can build a graph out of plain objects and no `three` import appears
 * here. A real `Scene`/`Mesh` satisfies it as it is.
 */
export interface CountableNode {
  visible: boolean;
  children?: readonly CountableNode[];
  geometry?: { attributes?: { position?: { count?: number } | null } | null } | null;
}

/**
 * Vertices of every visible mesh under `root`, `root` included.
 *
 * An invisible node takes its whole subtree with it — that is what makes the
 * number react to opening and closing a location, where the fade sets
 * `visible` on the group and not on each mesh.
 *
 * Shared geometry is counted once PER NODE, not once per geometry: ten clones
 * of one tree are ten times the vertices, because ten clones cost ten draws.
 * That is the reading the draw-call figure next to it needs to make sense.
 */
export function visibleVertices(root: CountableNode | null | undefined): number {
  if (!root || !root.visible) return 0;
  let total = root.geometry?.attributes?.position?.count ?? 0;
  for (const child of root.children ?? []) total += visibleVertices(child);
  return total;
}

// --- Tier split -----------------------------------------------------------

export type TierCounts = Record<ModelTier, number>;

/** One mounted model as the tier count sees it — the two fields of
 *  `PlacedSceneModel` that say which tier is standing. */
export interface TierSample {
  /** the model's variants per tier (§ B1), as the payload delivered them */
  variants: Record<string, string>;
  /** URL the mounted object was loaded from ('' = placeholder / no mesh) */
  url: string;
}

/**
 * How many mounted models currently stand on `full` and how many on `low`.
 *
 * Read off the URL rather than off a remembered wish: the wish is what the
 * view WANTED, and a swap that is still loading, was superseded or found no
 * low variant would make the display lie. The URL is what is in the scene.
 *
 * A model with no low variant resolves to the same URL for both tiers and
 * counts as `full` — it never got cheaper, and pretending otherwise would
 * hide exactly the meshes that still need a low stage. Models without a mesh
 * at all (placeholder box) count for neither.
 */
export function tierCounts(items: Iterable<TierSample>): TierCounts {
  const counts: TierCounts = { full: 0, low: 0 };
  for (const it of items) {
    if (!it.url) continue;
    const low = it.variants?.low;
    if (low && it.url === low && low !== it.variants?.full) counts.low += 1;
    else counts.full += 1;
  }
  return counts;
}

// --- What the ground scatter submits --------------------------------------
//
// WHY A SPLIT AND NOT ONE NUMBER (perf finding 2026-08-24). Measured on an
// Intel iGPU, hiding the scatter alone (isolation switch 13) moved the picture
// from 34 fps to 46-64 — the scatter is ~11 ms of a 29 ms frame and the single
// dominant cost, while the whole terrain is 6 ms and the shadows 1.6. That
// number says nothing about WHICH of the scatter's two stages spends it: the
// near half draws real prop meshes (thousands of triangles per instance, cheap
// per pixel), the far half draws one alpha-tested billboard per instance (two
// triangles, expensive per pixel). The two are fixed in opposite directions,
// so a readout that adds them up cannot drive a fix.

/** One drawable of the scatter as the counter reads it — structural, so the
 *  smoke check can build one out of a plain object and no `three` import
 *  appears in this module. A real `InstancedMesh` satisfies it as it is. */
export interface DrawableNode {
  visible: boolean;
  /** `InstancedMesh.count` — how many instances the last binning left in the
   *  buffer. Absent on a plain mesh, which draws itself once. */
  count?: number;
  /** `Object3D.name`; the impostor stage marks its meshes with
   *  `IMPOSTOR_MESH_NAME` (`scene/impostors.ts`) and nothing else does. */
  name?: string;
  geometry?: {
    index?: { count?: number } | null;
    attributes?: { position?: { count?: number } | null } | null;
  } | null;
}

/** What ONE render stage costs a frame. */
export interface ScatterCost {
  /** draw calls — one per drawable that really submits something */
  calls: number;
  /** instances submitted, summed over those drawables */
  instances: number;
  /** triangles submitted: per-instance triangles times the instance count */
  triangles: number;
}

/** The scatter's two stages side by side — near meshes against far billboards. */
export interface ScatterCounts {
  mesh: ScatterCost;
  impostor: ScatterCost;
}

/** An empty reading — what the display shows before the first measurement. */
export function emptyScatterCounts(): ScatterCounts {
  return {
    mesh: { calls: 0, instances: 0, triangles: 0 },
    impostor: { calls: 0, instances: 0, triangles: 0 },
  };
}

/**
 * What the ground scatter submits this frame, per stage.
 *
 * THE RULES, all three of them readable off a drawable and nothing else:
 *  - a drawable that is invisible or holds no instance costs NOTHING, not even
 *    a draw call. That is the honest reading: the binning parks an empty entry
 *    at `count = 0, visible = false`, and a stage whose entries are all parked
 *    has to read zero or the display would blame it for a frame it sat out.
 *  - triangles per instance come from the INDEX where there is one and from
 *    the position count otherwise — the same rule the renderer draws by
 *    (`drawElements` vs `drawArrays`), so this counts what is really submitted
 *    and not what the file happens to hold.
 *  - the stage is the NAME: `impostorName` (the billboards mark themselves,
 *    see `DrawableNode.name`), everything else is the mesh half. A marker
 *    rather than a geometry test, because a prop whose mesh happens to be two
 *    triangles is still a mesh.
 *
 * WHAT IT DELIBERATELY DOES NOT KNOW is the frustum: it counts what the scene
 * offers, not what survives culling. For this layer the two are the same
 * number — every scatter mesh carries the bounding sphere of its whole entry
 * (`ScatterProp.sphere`), which spans the entire camera window, so the frustum
 * test never rejects one. Reading it as "what is offered" is also what makes
 * the figure comparable between two camera positions.
 */
export function scatterCosts(nodes: Iterable<DrawableNode> | null | undefined,
                             impostorName: string): ScatterCounts {
  const out = emptyScatterCounts();
  for (const node of nodes ?? []) {
    if (!node || !node.visible) continue;
    // `count` is absent on a plain mesh, which draws itself once; an explicit
    // 0 is an entry the binning parked and is not a draw call.
    const instances = node.count === undefined ? 1 : node.count;
    if (!(instances > 0)) continue;
    const verts = node.geometry?.index?.count
      ?? node.geometry?.attributes?.position?.count ?? 0;
    const bucket = node.name === impostorName ? out.impostor : out.mesh;
    bucket.calls += 1;
    bucket.instances += instances;
    bucket.triangles += Math.floor(verts / 3) * instances;
  }
  return out;
}
