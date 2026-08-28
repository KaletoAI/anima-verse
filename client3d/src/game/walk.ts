/**
 * Pure walking maths of the embodied mode — FREE WALKING since E4 task 5.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM. That is what makes `client3d/scripts/smoke_walk_math.mjs` able to
 * check it with hand-derived numbers — the file is transpiled and imported as
 * plain ESM, so it must stay IMPORT-FREE as well.
 *
 * THE CELL FUNCTIONS ARE GONE (E4 task 5). `cellOf`, `clampToCell`,
 * `splitDiagonal`, `stepDirection`, `keepAhead` and `EDGE_MARGIN` were the
 * step machine of the grid world: the figure was held inside its cell until
 * the server granted the crossing. The metre world has no cells and no
 * per-boundary permission — the client walks freely and REPORTS where it
 * stands (`POST /play/pos`), and what stops the figure is geometry:
 * `game/collide.ts` for walls inside an open interior, `slideBlocked` below
 * for impassable terrain and foreign footprints outdoors.
 */

/** A point on the world plane, in METRES. The one shape every walking
 *  function here speaks; `THREE.Vector3` is the renderer's business. */
export interface Point { x: number; z: number }

/** Is that world point off limits for the walking figure? Supplied by
 *  `main.ts`, which knows the terrain areas (impassable kinds) and the
 *  footprints of the locations the avatar is not in. */
export type BlockedFn = (x: number, z: number) => boolean;

/**
 * Camera-relative walk direction (unit length) from the held keys, or null
 * when nothing is pressed or opposite keys cancel out.
 *
 * Uses the SAME basis as the engine's camera pan: forward
 * `(-sin yaw, 0, -cos yaw)`, right `(-fwd.z, 0, fwd.x)`. If these ever
 * disagree, "forward" means two different things on one screen.
 */
export function walkDir(keys: ReadonlySet<string>, yaw: number
): { x: number; z: number } | null {
  const fx = -Math.sin(yaw);
  const fz = -Math.cos(yaw);
  const rx = -fz;
  const rz = fx;
  let x = 0;
  let z = 0;
  if (keys.has('w') || keys.has('arrowup')) { x += fx; z += fz; }
  if (keys.has('s') || keys.has('arrowdown')) { x -= fx; z -= fz; }
  if (keys.has('d') || keys.has('arrowright')) { x += rx; z += rz; }
  if (keys.has('a') || keys.has('arrowleft')) { x -= rx; z -= rz; }
  const len = Math.hypot(x, z);
  if (len < 1e-6) return null;
  return { x: x / len, z: z / len };
}

/**
 * Hold a step out of blocked ground, sliding ALONG the boundary instead of
 * stopping dead.
 *
 * The ideal is the tangent projection: the part of the movement that runs
 * along the boundary survives, the part that runs into it is dropped. What
 * this does is the documented simplification of that (plan task 5, "simple
 * per-axis fallback is acceptable"): the two axes are the two tangents an
 * axis-aligned obstacle can offer, and the boundaries out here are exactly
 * that kind — the edges of terrain polygons and of footprint squares.
 *
 *  1. the full step, if its target is free;
 *  2. otherwise the LARGER of the two axis components alone (deterministic:
 *     ties go to x) — a figure walking mostly north into a wall on its east
 *     keeps going north;
 *  3. otherwise the smaller one alone;
 *  4. otherwise stand still.
 *
 * Only the TARGET point is asked about, never the way there. A step is at
 * most `WALK_SPEED × dt` long (a few centimetres at any sane frame rate),
 * and both blockers are areas metres across — a step cannot jump one.
 */
/**
 * Does PAINTED GROUND stop the figure at that point? The client's half of
 * the server rule of `POST /play/pos` (§ A15), pulled out of `main.ts` so it
 * can be checked by hand instead of only being read.
 *
 * FOOTPRINT WINS (decision 2026-08-13). Terrain judges the WILDERNESS, never
 * the inside of a placed location: the server derives the location of the
 * reported point FIRST and asks `passability_at` only for
 * `location_id == ""`. A place is put ON the world and does not inherit the
 * ground somebody painted under it — a hall on a rock plateau is a place one
 * can stand in. Who may go IN is decided elsewhere (openings, rules — the
 * foreign-footprint half of `main.ts` `blockedFor`); this predicate never
 * had anything to say about it.
 *
 * `passable` is the terrain answer at the point (`ground.passableAt`),
 * `insideFootprint` whether ANY placed footprint covers it (`main.ts`
 * `tileAt(x, z) !== null`) — the avatar's own as much as a foreign one.
 * Both are lookups, which is why they are the caller's job and not this
 * file's: what is derivable is the RULE, and the rule is that a footprint
 * point is never refused for its ground.
 *
 * ONLY THE REFUSAL is a wilderness question. How FAST that ground is walked
 * and WITH WHICH CLIP reaches further — into every OPEN place as well; see
 * `groundScope`, `terrainPace` and `moveClip` below (finding 3).
 */
export function terrainBlocks(passable: boolean, insideFootprint: boolean
): boolean {
  return !insideFootprint && !passable;
}

/** HOW FAR THE TERRAIN RULE REACHES at a point — the three places a walking
 *  figure can be (user decision 2026-08-13, round 2 of the E8 acceptance).
 *  The words are the contract, shared with the server
 *  (`terrain_query.SCOPE_*`):
 *
 *   - `wilderness` — out between the places, no footprint over the point;
 *   - `open` — inside an OPEN place: the footprint of an AREA location, or an
 *     outdoor room (`always_visible`, § A5). Sky above, painted ground below;
 *   - `built` — a building footprint or a normal interior room. The place
 *     brings its own floor and the painted ground has nothing to say. */
export type GroundScope = 'wilderness' | 'open' | 'built';

/**
 * Which of the three a point is in — the client twin of
 * `terrain_query.ground_scope`, read MOST-SPECIFIC-FIRST.
 *
 * @param placeIsArea    `null` when no footprint covers the point (the
 *   wilderness); otherwise whether that place is open ground
 *   (`tiles.isAreaLocation`, the twin of `world_geometry.is_area_location`).
 * @param roomIsOutdoor  `null` when the point lies in no room rectangle;
 *   otherwise whether that room is an outdoor one (`tile.alwaysVisibleRooms`).
 *
 * A room ANSWERS for the point when there is one, so the terrace of a house
 * wades through painted water while the house itself does not, and a hut
 * inside a village square is dry while the square around it is not. Both
 * arguments are the caller's lookup (`main.ts` `groundScopeAt`) — what is
 * derivable is the RULE, and only the rule lives in this import-free file.
 */
export function groundScope(placeIsArea: boolean | null,
                            roomIsOutdoor: boolean | null): GroundScope {
  if (roomIsOutdoor !== null) return roomIsOutdoor ? 'open' : 'built';
  if (placeIsArea !== null) return placeIsArea ? 'open' : 'built';
  return 'wilderness';
}

/** Lowest pace a ground may actually impose on the walking figure.
 *
 *  A pace scales the walking STEP (`npcs.tick`, `WALK_SPEED * dt * pace`),
 *  and the step is what the stall detection of `game/clickmove.walkStalled`
 *  measures: below `STALL_STEP_M` = 0.01 m a frame counts as "got nowhere"
 *  and a click order is dropped after a few of them. A 60 fps frame walks
 *  3.4/60 = 0.0567 m, so a quarter of it is 0.0142 m — still a real step.
 *  Anything slower would be a ground one cannot walk a click route over,
 *  which is a wall pretending to be mud; the server's own clamp sits lower
 *  (0.1, `terrain_query.MIN_SPEED_FACTOR`) because it guards a COST against
 *  infinity, not a frame against a threshold. */
export const MIN_PACE = 0.25;

/** From this distance to its goal a figure counts as MOVING (metres,
 *  `npcs.tick`) — under it there is no step and no walk animation, the figure
 *  stands.
 *
 *  It lives here because the walking LEAD has to clear it: the avatar's goal
 *  is set a lead ahead of the figure every frame, so a lead below this
 *  threshold is a figure frozen in place with an idle clip (the swim finding
 *  of 2026-08-13 — a paced lead of 0.0375 m on `deep_forest` never moved).
 *  That is why the pace scales the STEP and never the lead. */
export const MOVE_EPS_M = 0.05;

/**
 * How fast the figure walks on that ground — the client's half of the pace
 * rule of `terrain_query.effective_speed_factor` (finding 3 of the E8
 * acceptance, 2026-08-13; reach decided in round 2).
 *
 * THE TOPMOST TERRAIN'S FACTOR COUNTS WHEREVER THE SKY IS: out in the
 * wilderness and inside an OPEN place — painted water slows a walker down in
 * a village on a lake exactly as it does outside it, and painting the ground
 * of a place is how one says so. Only the PASSABILITY is a wilderness
 * question (`terrainBlocks`).
 *
 * Two neutral cases, both at the plain 1:
 *  - a BUILT place (building footprint, normal interior room) replaces the
 *    ground with its own floor, whatever the catalog holds there;
 *  - a factor of 0 inside an OPEN place: that is not a pace but a "this
 *    ground was never meant to be walked" (rock), and a place put down on it
 *    declares it walkable.
 * Everything else is clamped up to `MIN_PACE`.
 *
 * `speedFactor` is the caller's lookup (`ground.typeAt(x, z).speed_factor`),
 * `scope` is `groundScope` read at the point — what is derivable is the RULE,
 * and only the rule lives in this import-free file.
 */
export function terrainPace(speedFactor: number, scope: GroundScope): number {
  // A world whose catalog hands out nonsense walks at the normal pace rather
  // than at NaN — one NaN in the step and the figure never moves again.
  if (!Number.isFinite(speedFactor)) return 1;
  if (scope === 'built') return 1;
  if (scope === 'open' && speedFactor <= 0) return 1;
  return Math.max(speedFactor, MIN_PACE);
}

/**
 * WHICH CLIP a moving figure plays — the animation half of the same rule,
 * with the same reach.
 *
 * A ground may name the clip one moves over it with (`meta.move_anim`, § A9 —
 * `swim` on water). It replaces walk AND run: a figure crossing a lake does
 * not sprint through it, and there is no second speed of swimming to choose
 * from. Without one the old pair stands, run past `RUN_DISTANCE` and walk
 * below it. INSIDE A BUILT PLACE the ground names nothing at all: one does
 * not swim across a tiled hall standing in a lake.
 *
 * The clip kind goes into the open vocabulary of `Figure.play` unchecked —
 * a kind no model carries falls back through `clipCoverage.resolveClipKind` —
 * same FAMILY first (`walk` ↔ `walk-cmu`), then `CLIP_FALLBACK` (swim → walk),
 * finally idle, which is the same road every other kind takes.
 * STANDING is `idleClip`'s business, not this one's.
 */
export function moveClip(moveAnim: string, running: boolean,
                         scope: GroundScope): string {
  const kind = groundClip(moveAnim, scope);
  if (kind) return kind;
  return running ? 'run' : 'walk';
}

/**
 * WHICH CLIP a STANDING figure plays because of the ground — the second half
 * of the same contract (`meta.idle_anim`, § A9; the water round of
 * 2026-08-13: standing still in a lake played the standing clip, and the
 * figure stood on the water like a floor).
 *
 * `''` means "the ground says nothing", and then the caller's own standing
 * clip stands — the server's `animation` or the activity heuristic (§ A8),
 * unchanged. THE REACH IS THE ONE OF `moveClip`, literally the same helper:
 * inside a built place the ground names nothing, one does not tread water in
 * a tiled hall standing in a lake.
 */
export function idleClip(idleAnim: string, scope: GroundScope): string {
  return groundClip(idleAnim, scope);
}

/**
 * WHICH CLIP A STANDING FIGURE ACTUALLY PLAYS — the one decision of every
 * figure, the player's avatar included (`npcs.tick`).
 *
 * Three words in one order: the GROUND first (`idleClip` above, `''` where it
 * says nothing), then the server's activity clip (§ A8/AV3D-6, the worldmap's
 * `activity_animation`), and where neither names one the figure simply
 * stands. There is no keyword guessing over the activity text any more — a
 * pose comes from the catalog or not at all (plan-posen-plaetze.md, Task 13).
 *
 * @param animation the figure's server clip, `undefined` for none.
 * @param groundIdle what the ground named, `''` for nothing.
 *
 * The avatar's stand-up clears `animation` locally the moment the key is
 * pressed (`NpcManager.setPlayerAnimation`), because otherwise this rule keeps
 * answering the seat's `sit` until the next poll (plan-aufstehen.md).
 *
 * PURE, and hand-derived in `client3d/scripts/smoke_places_client.mjs` [10].
 */
export function standingClipFor(animation: string | undefined,
                                groundIdle: string | undefined): string {
  return groundIdle || animation || 'idle';
}

/**
 * HOW DEEP the ground swallows the figure standing or moving on it (§ A9,
 * world metres) — the third field of the same contract, with the SAME reach.
 *
 * The clip normalisation puts the lowest body point on the surface, and for a
 * swimmer that point is a bent knee: the body lies on the lake instead of in
 * it. This is what belongs underneath. Inside a BUILT place the ground says
 * nothing here either — a tiled hall over painted water is a floor, and one
 * does not stand knee-deep in it. Junk and non-positive numbers are no depth.
 *
 * WHICH of the ground's two depths is handed in is `sinkForState`'s business;
 * this function only says how far the ground's word reaches.
 */
export function groundSink(sink: number, scope: GroundScope): number {
  if (!Number.isFinite(sink) || sink <= 0) return 0;
  return scope === 'built' ? 0 : sink;
}

/** The two depths a ground carries (`meta.move_sink_m` / `meta.idle_sink_m`,
 *  § A9), as `ground.typeAt` reads them — 0 where the catalog says nothing. */
export interface GroundSink { move: number; idle: number }

/**
 * WHICH of the two depths is in force right now (finding 13, 2026-08-13).
 *
 * One number could not serve both poses: a moving swimmer lies HORIZONTAL and
 * its lowest point is an angled knee a hand's width under the body, a waiting
 * one treads water UPRIGHT and its lowest point is a foot a whole body length
 * down. Normalised onto the same surface, one depth puts one of them right and
 * the other in the wrong world.
 *
 * So the state picks: moving → the move depth, waiting → the idle one. AND
 * WAITING HAS A GATE the moving case does not have: the idle depth only counts
 * where the ground also NAMES a standing clip (`groundIdle`, i.e.
 * `idleClip(meta.idle_anim, scope)` — already reach-filtered by the caller).
 * Without one the figure keeps its OWN standing clip, and that clip brings its
 * own reference height with it (`sleep` is animated on a bed) — sinking it
 * would push a sleeper through the mattress. Moving needs no such gate: walk
 * and run stand on the ground they are played on, so a bog may swallow ankles
 * without naming a clip at all.
 */
export function sinkForState(moving: boolean, groundIdle: string,
                             sink: GroundSink): number {
  if (moving) return sink.move;
  return groundIdle ? sink.idle : 0;
}

/**
 * HOW FAR THE MIRROR'S WORD REACHES — the exact twin of `groundSink` above,
 * and for the same reason (E4).
 *
 * A tiled hall standing in a painted lake is a FLOOR: one does not stand
 * knee-deep in it (`groundSink`), and one does not float on the lake's water
 * line inside it either. The painted areas do not know about rooms — `typeAt`
 * reads the topmost polygon and nothing else — so the reach rule has to be
 * applied by whoever knows the scope, exactly as it already is for the sink and
 * the two ground clips. Without it a room built over a lake would lift every
 * figure in it up to the water surface.
 */
export function groundWaterLevel(level: number | null,
                                 scope: GroundScope): number | null {
  if (level === null || !Number.isFinite(level)) return null;
  return scope === 'built' ? null : level;
}

/** From which water DEPTH a figure swims instead of wading, in metres, where
 *  the kind names no `meta.swim_from_m` — the mirror of
 *  `terrain_types.SWIM_FROM_DEFAULT_M`. Roughly where an adult's feet stop
 *  carrying it. */
export const SWIM_FROM_DEFAULT_M = 1.0;

/** What the GROUND imposes on a figure at one point, as `wadeGate` reads and
 *  returns it: the two clips it names, its two depths and the mirror over the
 *  point (already cut to its scope by `groundWaterLevel`). It is the water
 *  half of `npcs.GroundMove`, which is why the scope itself is not in it —
 *  that reach was applied before this one. */
export interface GroundWater {
  /** `meta.move_anim`, or `''` — what a MOVING figure plays here */
  anim: string;
  /** `meta.idle_anim`, or `''` — what a WAITING figure plays here */
  idle: string;
  /** `meta.move_sink_m` / `meta.idle_sink_m` */
  sink: GroundSink;
  /** the mirror over the point in world metres, or `null` where none applies */
  water: number | null;
}

/**
 * SWIMMING IS A DEPTH, NOT A KIND (W4c, 2026-08-23) — the SECOND reach rule of
 * the ground contract, next to the scope one above.
 *
 * THE BUG IT ENDS. Until now `meta.move_anim: swim` played on every pixel of a
 * water area, ankle-deep on the shore ramp included: a figure crossing a ford,
 * or standing on the rim of a river whose ramp is a metre wide, crawled through
 * water that reached its shins. The client has both numbers it needs to know
 * better — the mirror over the point (`groundWaterLevel`) and the bed under the
 * figure — so the ground's water word is gated by what they say:
 *
 *     depth = waterLevel − groundY
 *     depth ≥ swimFromM  ->  SWIM: the ground's clips and sinks as before, the
 *                            body hangs `move_sink_m` under the mirror
 *     depth <  swimFromM  ->  WADE: the ground says NOTHING — the figure keeps
 *                            its own walk/run and standing clips, sinks by
 *                            nothing and stands on the BED (`water: null`, so
 *                            `floatRootY` leaves the terrain height alone)
 *
 * The mirror has to go with the clips: leaving it in while zeroing the sink
 * would put the wader ON the water surface (`floatRootY` = max(groundY, level)),
 * which is the opposite of standing in the water. All four fields answer one
 * question, so they are gated in one place and not four.
 *
 * WHY THE SINK GOES TO ZERO AND NOT TO SOMETHING SMALL: a wader plays a walk
 * clip, and a walk clip is authored standing on the ground it is played on.
 * The water reaching the hips is drawn by the water surface passing through the
 * figure, not by dropping the figure into the bed.
 *
 * NO WATER, NO GATE. Where the point carries no mirror (`water === null` — the
 * whole dry world, and every built place, which `groundWaterLevel` already cut)
 * the word passes through untouched: a bog with a `move_sink_m` still swallows
 * ankles, and a kind with a `move_anim` of its own still names it. This is what
 * keeps the rule to WATER and out of every other ground.
 *
 * Worked through with the river seed (`swim_from_m` 1.0, mirror at L = 5.0):
 *
 *     depth 0.4 -> groundY 4.6, wades: walk/idle clip, sink 0, root 4.6
 *     depth 1.0 -> groundY 4.0, THE THRESHOLD, swims: swim/treading-water,
 *                  root = max(4.0 + 0.35, 5.0) = 5.0
 *     depth 1.6 -> groundY 3.4, swims: root = max(3.75, 5.0) = 5.0
 *
 * `swimFromM` is the kind's number as `ground.typeAt` read it; junk and a
 * negative one fall back to `SWIM_FROM_DEFAULT_M`, and a 0 is kept — it means
 * "swim from the very rim", which is exactly what every water kind did before
 * this round.
 */
export function wadeGate(word: GroundWater, groundY: number,
                         swimFromM: number): GroundWater {
  const level = word.water;
  // No mirror over the point, or no ground under the figure to measure against:
  // nothing to decide, and inventing a depth out of a NaN would silently
  // undress every ground the sampler has not answered for yet.
  if (level === null || !Number.isFinite(level) || !Number.isFinite(groundY)) {
    return word;
  }
  if (level - groundY >= swimFrom(swimFromM)) return word;
  return { anim: '', idle: '', sink: { move: 0, idle: 0 }, water: null };
}

/** The kind's swim threshold, made a number — junk and a negative one are the
 *  default, a 0 is a value. One place, so the gate and every caller that wants
 *  to show the number agree on what an unauthored kind means. */
export function swimFrom(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value : SWIM_FROM_DEFAULT_M;
}

/**
 * WHERE A FIGURE'S ROOT STANDS over water — "Ein Boden" E4 (§ G4), and the end
 * of the swimmer who hung in the lake bed.
 *
 * THE BUG IT ENDS. Until E4 the sink was measured from the TERRAIN: the root
 * sat on `h(x, z)` and `figures.Figure.play` dropped the body by
 * `sinkForState(...)` under it. That is right for a bog and wrong for a lake,
 * because since E1 a lake's bed is CARVED — `water_depth_m` defaults to two
 * metres — so a swimmer on a two-metre bed hung 2.35 m below the water line
 * (2.0 of bed plus its own 0.35) and came out half inside the grass plate of
 * the bank (the user's screenshot, 2026-08-21). The deeper the lake, the deeper
 * the swimmer.
 *
 * THE NEW RULE, in the one place both the avatar and the NPCs read it. The
 * mirror comes out of the payload now — since W2 as the LOCAL level of the
 * area's own profile (`waterLevelAt(meta.water_profile, x, z)`, handed in as
 * `waterLevel`), so:
 *
 *     root = waterLevel === null ? groundY : max( groundY + sink, waterLevel )
 *
 * and since the body reference is always `root − sink`, that is
 *
 *     body = waterLevel === null ? groundY − sink : max( groundY, waterLevel − sink )
 *
 * — read it as: OUT of the water nothing changes at all; IN the water the body
 * hangs `sink` under the MIRROR, and never below the bed it would otherwise
 * stand on.
 *
 * THE CROSSOVER FALLS OUT OF THE `max`, it is not a second rule: the two
 * branches are equal where `groundY + sink = waterLevel`, i.e. at a water
 * DEPTH of exactly `sink`. Shallower than that the figure WADES (feet on the
 * bed, `root = groundY + sink`, body on `groundY`), deeper it SWIMS (`root =
 * waterLevel`, body `sink` under the water line, whatever the bed does). The
 * maximum of two continuous functions is continuous, so walking into a lake is
 * one smooth descent and out again one smooth rise — no step at the waterline,
 * and none at the crossover either.
 *
 * Worked through with the world's own swim depth `sink = 0.35` and a mirror at
 * `L` (`smoke_walk_math.mjs` pins this table, `smoke_water_plane.mjs` § 4 the
 * same shape with a 0.6 seed):
 *
 *     depth 0.00 -> root L+0.35  body L         wading, at the very rim
 *     depth 0.20 -> root L+0.15  body L−0.20    wading, feet on the bed
 *     depth 0.35 -> root L       body L−0.35    THE CROSSOVER (both agree)
 *     depth 1.20 -> root L       body L−0.35    swimming
 *     depth 2.00 -> root L       body L−0.35    swimming (was L−2.35 before E4)
 *
 * The treader's own depth (`idle_sink_m`, 1.3 — a whole body length) puts its
 * crossover at 1.3 m of water, which is the point of having two: an upright
 * figure needs a body length before its feet leave the bottom.
 *
 * NO EXTRA CLEARANCE over the bed. The brief asked for "terrain + a small
 * clearance"; a positive one would lift a wader off the ground it is standing
 * on and buy nothing — continuity is already the `max`'s doing, not the
 * clearance's, and the bed is drawn by the same height function this reads.
 *
 * `sink` is what `groundSink(sinkForState(...), scope)` already answered, so
 * everything that rule says still holds: a built place has no sink and no
 * mirror either, and junk is no depth.
 *
 * SINCE W4c THE SHALLOW END RARELY GETS HERE AT ALL: `wadeGate` hands this a
 * `waterLevel` of `null` below the kind's `swim_from_m`, so the wading rows of
 * the table above are what the gate itself produces (`root = groundY`, feet on
 * the bed, sink 0) and the `max` only decides for a figure that IS swimming.
 * The arithmetic is unchanged — a kind with `swim_from_m: 0` still walks the
 * whole table, and the crossover still falls out of the `max`.
 */
export function floatRootY(groundY: number, waterLevel: number | null,
                           sink: number): number {
  const s = Number.isFinite(sink) && sink > 0 ? sink : 0;
  if (waterLevel === null || !Number.isFinite(waterLevel)) return groundY;
  return Math.max(groundY + s, waterLevel);
}

/**
 * FROM HOW MUCH WATER a figure gets its underwater ghost, in metres — the
 * depth at which the water look itself stands at its full rim ramp
 * (`scene/waterPlaneMath.WATER_EDGE_FADE_M`, 0.05 m).
 *
 * The two numbers are the same one on purpose: below it the water surface is
 * still fading in and cuts nothing off a figure, so a ghost there would be a
 * second body drawn for no visible reason — and, right at the waterline, one
 * that flickers on and off with every centimetre of the walk.
 */
export const WATER_GHOST_FROM_M = 0.05;

/**
 * IS THIS FIGURE STANDING IN WATER — the gate of the underwater ghost
 * (`figures.Figure.setSubmerged`, finding H3, 2026-08-25).
 *
 * `bedY` is the terrain height UNDER the figure and `waterLevel` the mirror
 * over the same point, already cut to its scope by {@link groundWaterLevel} —
 * i.e. the very two numbers the walk loop asks for every frame anyway. It is
 * deliberately NOT {@link wadeGate}'s answer: that gate nulls the water below
 * the kind's `swim_from_m` because a wader keeps its own clips and stands on
 * the bed — and a WADER is exactly the figure this ghost exists for. A
 * swimmer's body is at the surface; a wader's legs are the part the opaque
 * water surface cuts away.
 *
 * Hand values, threshold 0.05 m:
 *
 *     bed 12.00, water null   -> false   (dry ground: no water at all)
 *     bed 12.00, water 11.90  -> false   (the mirror is UNDER the bed)
 *     bed 12.00, water 12.00  -> false   (exactly at the waterline)
 *     bed 12.00, water 12.04  -> false   (4 cm: the look has not faded in)
 *     bed 12.00, water 12.05  -> true    (5 cm: the rim ramp is up)
 *     bed 12.00, water 12.60  -> true    (a ford, knee deep — the wader)
 *     bed 12.00, water 13.50  -> true    (a swimmer, cut at the chest)
 */
export function submergedInWater(bedY: number,
                                 waterLevel: number | null): boolean {
  if (waterLevel === null || !Number.isFinite(waterLevel)
      || !Number.isFinite(bedY)) {
    return false;
  }
  return waterLevel - bedY >= WATER_GHOST_FROM_M;
}

/**
 * THE GATE AND ITS ANSWER IN ONE — the whole decision behind every underwater
 * ghost there is (`scene/submergedGhost.ts`).
 *
 * `baseY` is the world Y the thing STANDS ON — a figure's bed
 * (`scene/npcs.ts`), a world prop's `worldPropBottom`, a scene placement's
 * `tile.center.y + bottom_y + lift` — and `waterLevel` the mirror over the very
 * same point, `null` where the point is dry. The answer is what the ghost cuts
 * itself off at: the LEVEL where there is water over the base, `null` where
 * there is not.
 *
 * It exists because the pair "is it submerged" + "at which line" was written
 * out at every gate site, and a second copy of `x ? level : null` is how one of
 * them ends up handing in the gated level, or a boolean, or the bed.
 *
 * Hand values (threshold {@link WATER_GHOST_FROM_M} = 0.05 m):
 *
 *     base 12.00, water null   -> null    (dry ground: no water at all)
 *     base 12.00, water 11.90  -> null    (the mirror is UNDER the base)
 *     base 12.00, water 12.04  -> null    (4 cm: the look has not faded in)
 *     base 12.00, water 12.05  -> 12.05   (5 cm: the rim ramp is up)
 *     base 12.00, water 12.60  -> 12.60   (a crate on a knee-deep ford's bed)
 *     base 12.00, water NaN    -> null    (a raster that knows nothing is dry)
 */
export function ghostCutY(baseY: number,
                          waterLevel: number | null): number | null {
  return submergedInWater(baseY, waterLevel) ? waterLevel : null;
}

/**
 * THE LEVEL A GHOST MAY BE CUT AT, ONCE THE PICTURE AGREES THERE IS WATER —
 * the second half of the gate, and the fix for the ghosting diorama on the
 * shore (user finding 2026-08-27, "Klippen").
 *
 * `waterLevel` is the raster's DILATED level: the server defines it 4 m past
 * every authored outline (`app/core/heightfield.py`, § A16.5), so on a bank it
 * still answers a mirror that is drawn nowhere — and since the bank clamp was
 * retired (K-A E6) the ground there sits up to 0.77 m under it, far over the
 * 5 cm of {@link submergedInWater}. Read alone it floods the collar and every
 * prop standing in it turns into a half-transparent ghost on dry land.
 *
 * `insideness` is what the TERRAIN asks instead: `waterShade.waterInside(sd)`
 * over the very same point, the ramp that scales the water lift in
 * `terrainLod.liftedHeight`. It is 0 outside the authored outline and ON it,
 * and rises to 1 half a metre in. Passing the ramp's VALUE rather than `sd`
 * keeps this file import-free and leaves the ramp itself in exactly one place;
 * a second copy of the smoothstep here is how the ghost and the drawn water
 * start disagreeing again.
 *
 * The answer is the level to hand {@link ghostCutY}, or `NaN` — the raster's
 * own "nothing knows of water here", which that gate already reads as dry.
 *
 * Hand values:
 *
 *     level 12.6, inside 0     -> NaN    (1 m outside: the dilation collar)
 *     level 12.6, inside 0     -> NaN    (sd = 0, exactly on the waterline)
 *     level 12.6, inside 0.5   -> 12.6   (sd = 0.25, half a band in)
 *     level 12.6, inside 1     -> 12.6   (sd >= 0.5, full water)
 */
export function ghostWaterLevel(waterLevel: number,
                                insideness: number): number {
  return insideness > 0 ? waterLevel : NaN;
}

/** The reach rule BOTH ground clips share, in one place: outside a built
 *  place the ground may name a clip, inside it never does, and a blank name
 *  is no name. Two copies of this is how one of them starts reaching further
 *  than the other. */
function groundClip(anim: string, scope: GroundScope): string {
  return scope === 'built' ? '' : (anim || '').trim();
}

/** Below this horizontal distance a height change counts as a STEP, above it
 *  as a SLOPE (metres) — the mirror of `STEP_DISTANCE_M` in
 *  `app/core/relief.py`. One metre is the scale of a position report itself,
 *  which is what makes it the line between "one has to climb that" and "one
 *  walks up that". */
export const STEP_DISTANCE_M = 1;

/**
 * Does a height change of `dh` over `dist` metres stop the figure? The
 * client's half of the E8 height gate of `POST /play/pos` (§ A15): the exact
 * mirror of `relief.slope_blocks` on the server, applied to the exact
 * difference the server applies it to — `stand_height_at` at both points,
 * which is {@link gateStandY} here (`main.ts` `gateStandAt` looks the rungs
 * up). Both halves of the mirror matter: the RULE below refuses the same
 * numbers the server refuses only as long as the NUMBERS are the same
 * heights, and for a while they were not (plan-huette-dach task 2).
 *
 * THE TWO LIMITS APPLY TOGETHER, and the step is the ADDITIONAL one:
 *
 *   - the SLOPE limit holds at EVERY distance: blocked when
 *     `atan(dh / dist) > maxSlope` degrees;
 *   - BELOW `STEP_DISTANCE_M` the step limit holds on top: blocked when
 *     `dh > maxStep`, however gentle the angle would call it.
 *
 * It was an either/or once, and that broke this mirror in particular (review
 * 2026-08-13): the client tests a walking LEAD of ~0.15 m while the server
 * tests a REPORT step of ~1.12 m, so with an either/or the whole band from
 * `maxSlope` up to the angle the same rise makes over a lead — 40° to 69° at
 * the defaults — was invisible here and refused there. The figure walked on
 * while the server snapped it back three times a second. (It also made every
 * slope climbable by crawling: 0.1 m per report turns a 76° wall into a legal
 * "step".)
 *
 * DIRECTION DOES MATTER (user rule, 2026-08-28): `dh` is SIGNED — the ground
 * under the target minus the ground under the point the figure stands on — and
 * ONLY A CLIMB is judged. A descent (`dh <= 0`) always passes, however deep:
 * walking downhill is what a body does without asking, and refusing it reads
 * as the world holding the figure back for nothing. The price is accepted: a
 * walker can go down where it cannot come back up and be stranded there.
 * Level ground never blocks either, which is what keeps the whole gate inert
 * in a world without relief.
 *
 * `dh` is the caller's lookup ({@link gateStandY} at both points, through
 * `main.ts` `gateStandAt`), `maxStep`/`maxSlope` the world settings off the
 * worldmap payload — what is derivable is the RULE, and only the rule lives
 * in this import-free file.
 */
export function slopeBlocks(dh: number, dist: number, maxStep: number,
                            maxSlope: number): boolean {
  const rise = dh;
  if (!(rise > 0)) return false;
  return (dist < STEP_DISTANCE_M && rise > maxStep)
    || Math.atan2(rise, dist) * 180 / Math.PI > maxSlope;
}

/**
 * WHERE A FIGURE STANDS at one point, as the HEIGHT GATE reads it — the
 * client's copy of `app/core/model_surface.stand_height_at`, which is what
 * `POST /play/pos` measures its step with (`app/routes/play.py`, since
 * 165ccf61).
 *
 * THE SAME THREE RUNGS AS THE SERVER, in the server's order, all in WORLD
 * metres:
 *
 *  0. THE BAKED LATTICE (`baked`) — the storey-0 surfaces of the tile
 *     (`tiles.bakedFloorAt`, `highest_surface_at` there), which is what a hut
 *     puts over the ground it stands on.
 *  1. THE DECLARATION (`declared`) — where no lattice answers, the
 *     `walk_y_world` a storey-0 room states (`ground.declaredFloorAt`,
 *     `declared_floor_of` there): a podium, a sunken lounge, a hut in a lake.
 *  2. THE TERRAIN (`terrain`) — the world ground, and it is the LOWER BOUND
 *     of the two rungs above as well (Entscheid 5): a hollow in a diorama
 *     never sinks a figure below the ground it stands on.
 *
 * THE STOREY PLATES ARE DELIBERATELY ABSENT, exactly as they are on the
 * server: since E5a the recipe draws a plate for DECLARED storeys only, this
 * gate is storey-0 only, and a walker on the ground plane must not be
 * measured against the slab of the floor above them. The drawing ladder
 * (`tiles.tileWalkY`) does read that rung, and it also adds
 * `WALK_CLEARANCE_M` — the hair that keeps a sole out of its floor. Neither
 * belongs here: this is a MIRROR of the server's ladder, not the drawing one.
 *
 * A NON-FINITE RUNG IS NOT A HEIGHT (`ground.standY`'s rule): a sampler with
 * nothing to say — no field loaded yet, a malformed sidecar — falls through
 * to the next rung instead of putting the gate at NaN, and with the terrain
 * gone the upper rung stands alone. A gate that answers NaN judges nothing,
 * which would silently unblock the world.
 */
export function gateStandY(baked: number | null, declared: number | null,
                           terrain: number): number {
  const lattice = Number.isFinite(baked) ? (baked as number)
    : Number.isFinite(declared) ? (declared as number) : NaN;
  if (!Number.isFinite(lattice)) return terrain;
  return Number.isFinite(terrain) ? Math.max(lattice, terrain) : lattice;
}

export function slideBlocked(from: Point, to: Point, blocked: BlockedFn): Point {
  if (!blocked(to.x, to.z)) return to;
  const dx = to.x - from.x;
  const dz = to.z - from.z;
  const alongX = { x: to.x, z: from.z };
  const alongZ = { x: from.x, z: to.z };
  const first = Math.abs(dx) >= Math.abs(dz) ? alongX : alongZ;
  const second = first === alongX ? alongZ : alongX;
  if ((first === alongX ? dx : dz) !== 0 && !blocked(first.x, first.z)) return first;
  if ((second === alongX ? dx : dz) !== 0 && !blocked(second.x, second.z)) return second;
  return { x: from.x, z: from.z };
}
