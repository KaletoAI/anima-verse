/**
 * Which surface a figure stands on inside a location, and where the room's own
 * stands are — pure arithmetic, so every rule here can be derived by hand in
 * `client3d/scripts/smoke_walk_math.mjs` and `smoke_room_spots.mjs`. The
 * lookups (the tile's plate list, the height sampler) stay in `scene/tiles.ts`
 * (`tileGroundY`, `deriveRoomSpots`); only the RULES live here.
 *
 * THE LADDER IS DATA-ONLY SINCE "Ein Boden" E5b. Three rungs here, under the
 * baked rung 0 that `tileWalkY` asks first (see the note at the end):
 *
 *  1. a ROOM's own declaration (`declaredFloorAt`) — where a diorama spec
 *     carries a `walk_y_world`, that is the floor of that room, in every
 *     display mode. It is a statement, never a measurement (§ B6 no. 7).
 *  2. the plates of the recipe (`recipeFloorAt`) — which since E5a are the
 *     DECLARED STOREYS only: an upper floor, a basement. Storey 0 draws none.
 *  3. the TERRAIN. Nothing else is left: a built location stands on the
 *     plateau the bake stamps under it (§ G5), a natural one on the landscape,
 *     and both are the same one height function (`heightAt`, § A16).
 *
 * WHAT WENT WITH E5b: the mesh-raycast rung and the roof guard that judged it
 * (`walkCeiling` / `acceptsWalkHit` / the 1.2 m mark of finding B8). An area
 * model's walkable surface is its DECLARED `walk_y_world`; where it declares
 * none the answer is the terrain, which is the ground that model is drawn over
 * anyway. Asking the triangles was only ever a way of finding out which of two
 * grounds was in front — there is one now.
 *
 * Since v6 a baked lattice (`tile.surfaces`, scene-render `surfaceHeightAt`)
 * stands where the ray stood — data from the payload, not a measurement.
 */

import { pointInPolygon, polygonArea, type Polygon } from './polygon';

/** Clearance over a location's declared standing height above which a drawn
 *  plate belongs to the NEXT storey, in metres. */
export const ROOF_CLEARANCE_M = 1.2;

/** How far a figure's feet stand ABOVE the surface they were measured on, in
 *  metres — the hair that keeps a sole out of the floor it stands on.
 *
 *  It is the server's own `PROP_CLEARANCE` (`app/core/scene_recipe.py`): a
 *  prop's `bottom_y` is `plate top + 0.01`, so a figure standing on the same
 *  plate and a chair standing on it are at the SAME height by construction.
 *  Both the recipe-floor answer and the mesh-ray answer of `tileWalkY` add it,
 *  which is what makes the two paths comparable at all. */
export const WALK_CLEARANCE_M = 0.01;

/** One floor plate of the scene recipe, as the walk rule reads it: its
 *  outline in TILE-LOCAL metres and its `top_y`. Since E5a that is a DECLARED
 *  storey — an upper floor or a basement; storey 0 draws no plate at all. */
export interface WalkPlate {
  top: number;
  outline: readonly (readonly [number, number])[];
  /** THE OPENINGS CUT INTO IT (`plates[].holes`, contract addendum "Treppen
   *  v2") — a stairwell today. A point inside a ring is NOT on this plate:
   *  the floor is open there, so the answer falls through to the rung below
   *  (the storey under it, in the end the terrain). Absent where the source
   *  is not a drawn plate — a room's declared floor is a statement about a
   *  surface, and nothing cuts a hole into a statement. */
  holes?: readonly (readonly (readonly [number, number])[])[];
}

/**
 * THE FLOOR OF THE RECIPE under a tile-local point, or `null` where the
 * payload draws none (decision 2026-08-20, § B1/B2 addendum).
 *
 * The highest plate whose hull contains the point and whose top is still
 * BELOW the storey ceiling (`plateCeiling`): the highest surface that is not
 * already the next storey. Since E5a every plate in the list IS a declared
 * storey, so on the ground floor this answers `null` and the terrain has the
 * floor — while a figure standing on the first storey's 2.90 m slab keeps
 * standing on it, and the basement below keeps its own.
 *
 * The rule survives the plate cull unchanged on purpose: it is what stops an
 * uncapped pick from hoisting a ground-floor figure onto the storey above it.
 *
 * A HOLE IS NOT FLOOR (addendum "Treppen v2"): where a plate carries rings,
 * a point inside one is not on that plate at all — the plate simply does not
 * answer, and the next rung under it does. That is what lets a figure climb
 * through a stairwell instead of standing on its lid, and it is the same
 * statement the renderer makes by taking the ring out of the shape.
 */
export function recipeFloorAt(plates: readonly WalkPlate[] | null | undefined,
                              lx: number, lz: number,
                              ceiling: number): number | null {
  let best: number | null = null;
  for (const plate of plates ?? []) {
    if (!(plate.top < ceiling)) continue;
    if (best !== null && plate.top <= best) continue;
    if (!pointInPolygon(lx, lz, plate.outline as Polygon)) continue;
    if (plate.holes?.some((ring) => pointInPolygon(lx, lz, ring as Polygon))) continue;
    best = plate.top;
  }
  return best;
}

/**
 * A room's DECLARED walking floor: the `walk_y_world` of its diorama spec
 * plus the hull it is declared inside, both in TILE-LOCAL metres.
 *
 * The same shape as a plate on purpose — it answers the same question — but
 * it is a different KIND of answer and therefore a different list: a plate is
 * DRAWN geometry the rule may outrank, a declaration is the admin's word and
 * outranks everything (§ B6 no. 7, "walk_y is a statement, never a
 * measurement").
 */
export interface DeclaredFloor extends WalkPlate {
  /** The room that declared it — the key a tier swap replaces its entry by. */
  roomId: string;
}

/**
 * THE DECLARED floor under a tile-local point, or `null` when no room
 * declares one there (user finding 2026-08-20: Mondhütte).
 *
 * A declared `walk_y` has beaten every other rung since the dial exists — but
 * the WALKING figure never asked it: `tileWalkY` knew the drawn plates and the
 * mesh ray and nothing else, so the dial moved the NPC spots and the room
 * centre while the figure kept standing on the plate (or, in an area location
 * without a mesh, on the bare tile floor).
 * Two floors in one room, which is exactly what the one-datum law of
 * 2026-08-20 forbids. This is the missing half of that law: ONE lookup, asked
 * FIRST, by every consumer of the walking height.
 *
 * It applies whatever the location's `display` is. A declaration is not a
 * property of the surrounding mesh — it is a statement about the room's own
 * modelled floor (a podium, a sunken lounge, a hut standing in a lake), and a
 * hut does not stop having a floor because the place around it is an area.
 *
 * WHERE SEVERAL DECLARATIONS COVER THE POINT the smallest hull wins — the
 * innermost answer, the same most-specific-first tie-break the footprints use
 * (v6 no. 6, `polygonArea`). Rooms are not supposed to overlap, but an always-visible outdoor zone spanning
 * half the location legally contains a hut standing in it.
 */
export function declaredFloorAt(floors: readonly WalkPlate[] | null | undefined,
                                lx: number, lz: number): number | null {
  let best: WalkPlate | null = null;
  let bestArea = -1;                       // < 0 = not measured yet
  for (const floor of floors ?? []) {
    if (!Number.isFinite(floor.top)) continue;
    // Containment FIRST, and the area only for the hulls that answer at all:
    // this runs per figure per frame, overlapping declarations are the rare
    // case, and the tie-break must not cost a shoelace pass over every room
    // hull of the location on every one of them. A hull of fewer than three
    // points contains nothing (`pointInPolygon`), so it never declares.
    if (!pointInPolygon(lx, lz, floor.outline as Polygon)) continue;
    if (!best) { best = floor; continue; }
    if (bestArea < 0) bestArea = polygonArea(best.outline as Polygon);
    const area = polygonArea(floor.outline as Polygon);
    if (area > 0 && (bestArea <= 0 || area < bestArea)) {
      best = floor;
      bestArea = area;
    }
  }
  return best ? best.top : null;
}

/** What the scene payload says about the location's own model. `display` is
 *  the spec word of § B6 no. 10, `walkY` its `walk_y_world`. */
export interface GroundModelInfo {
  display?: 'shell' | 'ground' | 'shell_area';
  /** Declared walkable height of the model in WORLD metres, if the spec
   *  carries one. */
  walkY?: number;
}

/**
 * The ceiling that judges DRAWN PLATES — the storey question.
 *
 * One clearance over the location model's declared standing height, so the
 * storey above is out of reach of a figure on the one below. It applies to
 * every display alike since E5b: `walkCeiling`'s `Infinity` exception existed
 * for MESH HITS (a shore, a slope, a lake bed are all ground, finding B8), and
 * there are no mesh hits in the ladder any more — an area model's walkable
 * surface is the number it declares, and where it declares none the terrain
 * answers.
 */
export function plateCeiling(info: GroundModelInfo | null | undefined): number {
  const walk = info?.walkY;
  const base = typeof walk === 'number' && Number.isFinite(walk) ? walk : 0;
  return base + ROOF_CLEARANCE_M;
}

/**
 * WHERE A FIGURE STANDS when the tile and the world disagree — THE HIGHER ONE
 * WINS (user decision 2026-08-13, acceptance finding 4).
 *
 * A tile's walking height is a TILE answer: the declared floor of a room, or a
 * DECLARED storey's plate — measured from the location's own centre. The WORLD
 * ground (§ A16) runs on underneath a NATURAL footprint (one that
 * `draws_built_floor` says nothing about), and until this rule the client
 * never asked it inside a footprint: the figure walked at plate height while
 * the landscape rose through the plate around it, and crossing the footprint
 * border it JUMPED, because a traveller outside was already sampled off the
 * world field.
 *
 * Under a BUILT footprint this is inert by construction: the bake stamps the
 * field there to exactly the plateau the tile stands on, so both answers are
 * the same number and the maximum is that number.
 *
 * The price is named in the spec (§ A16): a model that dips BELOW the world
 * ground — the lake bed of an area model, a sunken courtyard — is undercut by
 * the landscape, and that is an authoring matter, not a case for the renderer.
 *
 * NaN is not a height. A sampler that answers nonsense (no field yet, a broken
 * payload) must not put a figure at NaN, from which no frame ever recovers:
 * a non-finite TILE answer reads as the tile floor 0 (and the world may still
 * win over it — `standY(NaN, −0.8)` is 0, not −0.8), a non-finite WORLD answer
 * leaves the tile answer alone, and with both gone the figure stands on 0.
 */
export function standY(walkY: number, terrainY: number): number {
  const walk = Number.isFinite(walkY) ? walkY : 0;
  const terrain = Number.isFinite(terrainY) ? terrainY : walk;
  return Math.max(walk, terrain);
}

// `plateLift` stood here until 2026-08-21 ("Ein Boden" E3, plan § 3.1): the
// drawn mirror of `standY` that lifted every vertex of a tile's own footprint
// plate onto the world ground, clamped so the plate never sank below the floor
// the figure walked on. The tile draws no plate any more — the terrain IS the
// ground under a location — so the rule has nothing left to lift. `standY`
// itself stays: the figure still has to reconcile a tile answer (a declared
// floor, a storey plate) with the terrain under it.
//
// `groundLift`/`ScenePatch` followed it in E5b, for the same reason one rung
// further in: they added a LOCATION's own relief on top of the world one, and
// the scene's 17 x 17 field is deleted (§ A19 no. 6, decision 1). "The ground
// at a world point" is `heightAt` and nothing plus it.

// ── The stands of a room, derived from its POLYGON (E5b) ─────────────────
//
// Until E5b a room's centre, its NPC stands and its sit/lie targets came out
// of 6 x 6 rays shot down at the room's plate mesh: the dominant height bin
// was the floor, a reference ray at the door repaired it where the mesh had
// holes, and everything within 12 cm of it was a stand. Storey 0 has no plate
// to ray any more, so the shape travels as data (`floor_plan`, § A19 no. 3)
// and the height comes from the ONE height function at the point being asked
// about. The two rules that survive that move are here, pure.

/** The AREA CENTROID of a polygon in any one frame, or `null` for a ring that
 *  encloses nothing (fewer than three points, or zero area — a degenerate hull
 *  has no centre and must not answer 0/0 as one).
 *
 *  The shoelace centroid, i.e. the centre of MASS of the enclosed surface and
 *  not the average of the corners: a wall drawn with ten points and the
 *  opposite one with two would pull a corner average against the ten-point
 *  wall, which is how a room's label and its NPC huddle end up in a corner. */
export function polygonCentroid(poly: Polygon | null | undefined
): { x: number; z: number } | null {
  if (!poly || poly.length < 3) return null;
  let twiceArea = 0;
  let cx = 0;
  let cz = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x0, z0] = poly[i];
    const [x1, z1] = poly[(i + 1) % poly.length];
    const cross = x0 * z1 - x1 * z0;
    twiceArea += cross;
    cx += (x0 + x1) * cross;
    cz += (z0 + z1) * cross;
  }
  if (Math.abs(twiceArea) < 1e-9) return null;
  return { x: cx / (3 * twiceArea), z: cz / (3 * twiceArea) };
}

/** How much of a room's bounding box the stand raster spans, as a fraction —
 *  the 0.78 the ray raster used, kept so the stands sit where they always sat
 *  (inside the walls, not against them). */
export const SPOT_SPREAD = 0.78;

/** Rows and columns of the stand raster — the 6 x 6 of the ray raster. */
export const SPOT_GRID = 6;

/**
 * THE STANDS OF A ROOM, in the frame its hull is given in.
 *
 * The very raster the rays were shot on — `SPOT_GRID` x `SPOT_GRID` points over
 * `SPOT_SPREAD` of the room's bounding box, around its centre — with the RAY
 * replaced by the polygon: a point the hull does not contain is not a stand.
 * That test is what the rays did implicitly (a ray beside the plate hit
 * nothing), and it is stricter and cheaper on a drawn L-shaped room, where the
 * bounding box reaches into the neighbour.
 *
 * Ordered by distance from the centre, nearest first — the order the ray
 * version handed its spots out in, and the reason a lone character stands in
 * the middle of its room rather than in a corner.
 */
export function roomSpotGrid(hull: Polygon | null | undefined,
                             cx: number, cz: number,
                             w: number, d: number): { x: number; z: number }[] {
  const out: { x: number; z: number }[] = [];
  const n = SPOT_GRID;
  for (let ix = 0; ix < n; ix++) {
    for (let iz = 0; iz < n; iz++) {
      const x = cx + (ix / (n - 1) - 0.5) * w * SPOT_SPREAD;
      const z = cz + (iz / (n - 1) - 0.5) * d * SPOT_SPREAD;
      if (hull && hull.length >= 3 && !pointInPolygon(x, z, hull)) continue;
      out.push({ x, z });
    }
  }
  out.sort((a, b) => ((a.x - cx) ** 2 + (a.z - cz) ** 2)
    - ((b.x - cx) ** 2 + (b.z - cz) ** 2));
  return out;
}

/** How far a stand's own ground may deviate from the room's floor and still be
 *  part of that floor, in metres — the 12 cm the ray raster judged its hits by,
 *  now measured against the HEIGHT DATA instead of against triangles.
 *
 *  Under a built room it is inert by construction: the plateau stamp makes the
 *  plot flat (§ G5), so every stand reads the room's own floor to the
 *  millimetre. Under an OPEN ZONE on natural ground it is the rule that keeps
 *  a huddle off a hillside the zone happens to run up — exactly what the
 *  dominant-bin heuristic did, minus the guessing. */
export const SPOT_FLAT_M = 0.12;

/** Is a surface at `surfaceY` a SEAT for a figure standing on `floorY`?
 *  Between a footstool and a bar stool, in metres over the floor: a 1.70 m
 *  figure's knee is at ~0.45 m, and the window has to hold a 0.25 m step as
 *  well as a 0.70 m stool. A worktop or a table (0.72 m and up) is out — you
 *  do not sit ON the table.
 *
 *  The pre-E5b window was 0.08 … 0.32 m, which was a REAL-metre window from the
 *  era when a room figure was 0.60 m tall (`k` was a scale then, § B E4 made it
 *  1). It has caught nothing at all since; the numbers above are the same
 *  statement re-derived for a 1.70 m figure. */
export const SEAT_MIN_M = 0.25;
export const SEAT_MAX_M = 0.70;

/** A surface a figure can LIE on has to take a body: at least 1.60 m long and
 *  0.70 m wide (a 1.70 m figure with its knees drawn up on a 0.70 m mattress).
 *  Anything shorter or narrower inside the seat window is a seat. */
export const LIE_LENGTH_M = 1.6;
export const LIE_WIDTH_M = 0.7;

/** What a placed prop offers a figure: nothing, a seat, or a place to lie.
 *  `surfaceY` is the TOP of its bounding box, `w`/`d` its footprint in metres
 *  — an OBJECT property, measured on the object, never on the ground. */
export function furnitureUse(floorY: number, surfaceY: number,
                             w: number, d: number): 'sit' | 'lie' | null {
  const over = surfaceY - floorY;
  if (!(over >= SEAT_MIN_M) || !(over <= SEAT_MAX_M)) return null;
  const long = Math.max(w, d);
  const short = Math.min(w, d);
  return long >= LIE_LENGTH_M && short >= LIE_WIDTH_M ? 'lie' : 'sit';
}
