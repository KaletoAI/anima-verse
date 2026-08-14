/**
 * WHICH FINE HEIGHT TILES THE CLIENT WANTS — the loading policy of § A16.3,
 * as pure arithmetic.
 *
 * Since v2 the world's relief arrives twice: a coarsenable OVERVIEW for the
 * distance, and 256 m tiles at an always-fine step (the server's, 2 m
 * today) for everything the
 * ground decides (`@anima/scene-render` `WorldHeightTiles`). The overview is
 * one fetch and then it stands; the tiles are a moving window, and this file
 * is the whole of the question "which ones, right now".
 *
 * NO FETCHING, NO STATE, NO THREE. It answers with keys and leaves the
 * requesting, the caching and the drawing to `ground.ts` — which is what lets
 * the numbers below be derived by hand in `client3d/scripts/smoke_height_tiles.mjs`
 * instead of being observed from a running client.
 *
 * THE RADIUS IS THE FOG'S, plus a tile's worth of margin: the veil closes at
 * 520 m (`engine.ts`, `THREE.Fog`), so a ground draped from the overview
 * beyond 560 m is behind the veil when it appears. The seam between the two
 * rasters is real and stays deliberately uncovered (plan, § A16.3) — it just
 * never happens where anyone can see it.
 */
import { tileKeyAt } from '@anima/scene-render';

/** How far around the anchor fine tiles are held, in metres. 560 = the fog end
 *  of 520 m plus one tile's diagonal of slack, so the seam sits inside the
 *  veil rather than at its edge. */
export const HEIGHT_TILE_RADIUS_M = 560;

/** How many tiles the client keeps at most. A full want set is ~25 tiles
 *  (a 560 m disc over a 256 m raster), so 96 is roughly three anchor positions
 *  of history — enough that walking back and forth across a tile border costs
 *  no refetch, and about 2.4 MB of heights at ~25 KB each. */
export const HEIGHT_TILE_CACHE_MAX = 96;

/** Keys per request — the server's own cap (`heightfield.TILE_BATCH_MAX`).
 *  Anything past it is dropped there with a one-shot warning, so the client
 *  splits instead of finding out by missing ground. */
export const HEIGHT_TILE_BATCH_MAX = 64;

/** Hard ceiling on tiles per axis inside the radius — a guard, not a working
 *  limit. The working case is 560 m over 256 m tiles, i.e. 6 columns; a
 *  payload whose `tile_m` made thousands of tiles fall inside the radius would
 *  blow the LRU anyway, and this stops the loop before it walks a million
 *  candidates first. */
const MAX_TILES_PER_AXIS = 64;

/**
 * The tiles worth holding around (x, z): every INDEXED tile whose square comes
 * within `radiusM` of the point, nearest first.
 *
 * `index` is the tile index of `GET /play/heightfield` — the tiles the world
 * actually has a ground in. Intersecting with it is what keeps the client from
 * asking for the empty half of the map: the server would answer those with
 * nothing at all (an unindexed tile IS flat ground), so a request for them is
 * a round trip for a guaranteed absence.
 *
 * THE TEST IS SQUARE-TO-POINT, not centre-to-point: a tile is 256 m across, so
 * measuring from its centre would drop tiles whose near edge is right under the
 * camera. `dx`/`dz` are the distance from the point to the tile's box, 0 on the
 * axes where the point is inside it — the standard box distance, and the reason
 * the anchor's own tile always comes out first.
 *
 * NEAREST FIRST matters only when the set is bigger than one batch, and then it
 * matters a lot: the ground under the player arrives in the first request and
 * the far edge of the radius in the last. Ties are broken by the key, so the
 * order is stable and a smoke can name it.
 */
export function wantedTiles(index: ReadonlySet<string>, tileM: number,
                            x: number, z: number,
                            radiusM: number = HEIGHT_TILE_RADIUS_M): string[] {
  if (!(tileM > 0) || !(radiusM >= 0) || !index.size) return [];
  if (!Number.isFinite(x) || !Number.isFinite(z)) return [];
  const firstX = Math.floor((x - radiusM) / tileM);
  const lastX = Math.floor((x + radiusM) / tileM);
  const firstZ = Math.floor((z - radiusM) / tileM);
  const lastZ = Math.floor((z + radiusM) / tileM);
  if (lastX - firstX > MAX_TILES_PER_AXIS || lastZ - firstZ > MAX_TILES_PER_AXIS) {
    return [];
  }
  const reach = radiusM * radiusM;
  const hits: { key: string; d2: number }[] = [];
  for (let tz = firstZ; tz <= lastZ; tz += 1) {
    const dz = Math.max(tz * tileM - z, 0, z - (tz + 1) * tileM);
    for (let tx = firstX; tx <= lastX; tx += 1) {
      const dx = Math.max(tx * tileM - x, 0, x - (tx + 1) * tileM);
      const d2 = dx * dx + dz * dz;
      if (d2 > reach) continue;
      // The key comes from `tileKeyAt` and never from a template written here:
      // there is ONE mapping between a place and a tile name (§ A16.3), and the
      // centre of the square is a place like any other. A second `Math.floor`
      // in this file would be a second answer to "which tile", and the two
      // would part company on the seams — exactly where a wrong key is a step
      // in the ground.
      const key = tileKeyAt(tileM, (tx + 0.5) * tileM, (tz + 0.5) * tileM);
      if (!index.has(key)) continue;
      hits.push({ key, d2 });
    }
  }
  hits.sort((a, b) => (a.d2 - b.d2) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return hits.map((h) => h.key);
}

/** The keys split into requests of at most `max`, in the order given — so the
 *  nearest tiles of `wantedTiles` are in the first batch. An empty list is no
 *  request at all, and a non-positive `max` is one request per key rather than
 *  an endless loop. */
export function tileBatches(keys: readonly string[],
                            max: number = HEIGHT_TILE_BATCH_MAX): string[][] {
  const size = max > 0 ? Math.floor(max) : 1;
  const out: string[][] = [];
  for (let i = 0; i < keys.length; i += size) out.push(keys.slice(i, i + size));
  return out;
}
