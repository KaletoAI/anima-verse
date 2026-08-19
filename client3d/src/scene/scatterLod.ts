/**
 * Pure display maths of the ground scatter: how tall its props stand, how far
 * they bend in the wind, and its level of detail.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM — the same discipline as `game/walk.ts`, and what lets
 * `client3d/scripts/smoke_scatter_math.mjs` transpile this file and check it
 * with hand-derived numbers. It must stay IMPORT-FREE.
 *
 * WHY ITS OWN THRESHOLDS. The scatter used to borrow `BUILDING_TIER_FAR`
 * (60 m) for a binary on/off per area: everything nearer stood at the FULL
 * tier, everything farther was simply gone. That is the wrong shape twice
 * over — a wood does not stop existing 60 m away, and the trees that ARE
 * shown do not all have to be the expensive mesh. So the distance decides
 * three things separately, and none of them is the building rule:
 *
 *   0 … 35 m   full mesh
 *  35 … 45 m   the hysteresis band — whatever mesh the instance already shows
 *  45 …120 m   low mesh, and the share still drawn sinks linearly to a quarter
 *   > 120 m    nothing
 *
 * THE DISTANCE IS THE INSTANCE'S OWN. Every function here is fed the distance
 * from the camera to ONE scattered prop, and the numbers above are only the
 * DEFAULTS: they arrive as a `ScatterLodCfg` argument, because the player sets
 * them in the game menu (`game/prefs.ts`, localStorage).
 *
 * PER INSTANCE, AND THAT IS THE POINT (2026-08-15). The rules used to be asked
 * once per painted AREA, and an area is a wood, not a point: with one answer
 * for all of it the trees at the player's feet dropped to the cheap mesh
 * because the far edge of the same wood was 100 m away, and a 300 m meadow was
 * either wholly drawn or wholly gone. The three questions are now asked of ONE
 * prop at ITS OWN distance; `scene/ground.ts` sorts the answers into two
 * instance buffers per entry.
 *
 * WHAT IS NOT DECIDED HERE: where the instances stand. That is the shared
 * sampler (`@anima/scene-render/scatter.ts`), it is seed-stable, and this
 * module never reorders it — the thinning picks by a hash of the instance
 * INDEX, so walking towards a wood regrows the same trees and never moves one.
 *
 * AND SINCE 2026-08-15 A THIRD DISTANCE CLASS: beyond the cull line the props
 * do not simply stop — the entries that HAVE a model are drawn as upright
 * billboards out to `IMPOSTOR_FAR_M` (`IMPOSTOR_*` below, the render side in
 * `scene/impostors.ts`). The window, the thinning over it and the whole
 * geometry of one billboard are arithmetic and therefore live here.
 *
 * SINCE 2026-08-15 THE SECOND LAYER'S NUMBERS LIVE HERE TOO: the automatic
 * undergrowth (`UNDERGROWTH_*` at the bottom of the file). It is the same
 * three questions with its own numbers — how dense the carpet is, how tall
 * its tufts are and how far it is drawn — and they sit beside the props'
 * because both are read on the same LOD tick and both have to stay
 * import-free for the smoke. Everything of that layer which is NOT a plain
 * number (the camera-local cell raster, the blade texture, the meshes) is
 * `scene/undergrowth.ts`.
 */

/** Nearer than this, a scattered prop stands on the full mesh (metres). */
export const SCATTER_TIER_NEAR = 35;
/** Farther than this, it stands on the low one. Between NEAR and FAR the mesh
 *  in place stays — a camera hovering at the line would otherwise re-download
 *  and re-swap a mesh every second, which costs far more than the detail it
 *  saves. Same shape as `wantedBuildingTier` in `main.ts`, own numbers. */
export const SCATTER_TIER_FAR = 45;
/** Beyond this a scattered prop is not drawn at all (metres). Twice the old
 *  borrowed 60 m: props stay visible far longer than before, but on the cheap
 *  mesh and in thinning numbers instead of all-or-nothing. */
export const SCATTER_CULL_FAR = 120;
/** The share of instances still drawn immediately before the cull distance.
 *  Not 0: a wood that fades to nothing pops when it crosses the line, and a
 *  quarter of it still reads as a wood on the horizon. */
export const SCATTER_MIN_SHARE = 0.25;

/** Target height of a scattered GLB when NOBODY knows how tall it should be
 *  (metres) — no authored `height_m`, no prop record behind the URL.
 *
 *  A prop file carries whatever size its author chose, and "whatever the file
 *  says" is not a size in a world measured in metres — a tree exported in
 *  centimetres stood 2 cm tall next to the figure. So an unknown model is
 *  normalised to a shrub/small-tree height instead of being trusted. It is the
 *  LAST resort, not the default: a prop of this world brings its real height
 *  along (`prop_height_m`), and this number is what is left for the built-in
 *  tuft's model-less siblings and foreign URLs. */
export const SCATTER_MODEL_HEIGHT_M = 2.0;

/**
 * How tall ONE scattered prop is drawn, in metres (§ A9).
 *
 * The precedence, and the whole point of it: the height AUTHORED on the
 * scatter row wins, because someone typed it for this ground. Otherwise the
 * prop's own library height governs — a tree is 8 m tall because the Props tab
 * says so, and every area that scatters it gets a tree instead of a shrub.
 * Only when neither exists (a foreign URL, a prop this world has no record
 * for) does the flat fallback apply. Before finding 12 the fallback WAS the
 * default and every wood stood at avatar height.
 *
 * Both inputs are "> 0 or nothing": undefined, null, NaN, 0 and negatives all
 * read as "not given", written as `> 0` so NaN falls through instead of
 * scaling a mesh into a NaN matrix.
 */
export function scatterTargetH(entryH?: number, propH?: number): number {
  if (Number(entryH) > 0) return Number(entryH);
  if (Number(propH) > 0) return Number(propH);
  return SCATTER_MODEL_HEIGHT_M;
}

/** What a scatter entry bends by when it says nothing: the ground's FULL
 *  deflection. The server stores and ships the factor only when it differs
 *  (`props.SWAY_FACTOR_DEFAULT`), so an absent field is this. */
export const SCATTER_SWAY_FACTOR_DEFAULT = 1;

/**
 * How far ONE scatter entry really bends, in metres (§ A9).
 *
 * TWO AUTHORS, ONE NUMBER. The terrain KIND says how hard it blows over this
 * ground (`meta.sway_m`, already clamped by the caller); the PROP says how
 * much of that it takes part in (`sway_factor` on the entry, 0..1, from its
 * library record). A boulder scattered over a waving meadow gets 0 and stands
 * still while the ferns beside it bend fully — which is the whole point of the
 * factor, and it cannot be expressed on the kind, where the wind lives.
 *
 * The factor is "a finite NUMBER in 0..1, or nothing": absent, null, NaN and
 * non-numbers read as "not given" and leave the ground's own amplitude alone,
 * values outside the range are clamped exactly as the server clamps them.
 *
 * WHICH IS WHY `Number()` IS NOT ENOUGH HERE, unlike everywhere else in this
 * file: `Number(null)` is 0, and 0 is a legal factor in this one field — a
 * `null` on the wire would silently stop a whole meadow instead of falling
 * back to the default. The type is tested, not just the value.
 *
 * ROUNDED TO TWO DECIMALS, and that is not cosmetic: `applySway` bakes the
 * amplitude into the shader at that precision and refuses anything under
 * `SWAY_MIN_M`, while `ground.ts` clones a material for every entry whose
 * value is `> 0`. Rounding here is what keeps those two tests agreeing — a
 * product of 0.004 would otherwise buy a material clone that never moves.
 */
export function scatterSway(swayM: number, factor?: number): number {
  const base = Number(swayM);
  if (!(base > 0)) return 0;
  const clamped = typeof factor === 'number' && Number.isFinite(factor)
    ? Math.min(Math.max(factor, 0), 1)
    : SCATTER_SWAY_FACTOR_DEFAULT;
  return Math.round(base * clamped * 100) / 100;
}

/* ==========================================================================
 * PER-INSTANCE LOD — the three questions, asked of ONE prop
 *
 * There used to be an AREA-WIDE half above this line (`scatterTierFor`,
 * `scatterCountShare`, `scatterVisibleCount`, and a `ScatterTier` string type
 * for the two mesh tiers). It went with the caller that binned whole areas:
 * the tier is per instance now, the "visible count" is a per-instance hash
 * rather than the tail of a list, and a rule nothing asks is a rule that rots.
 * ========================================================================== */

/**
 * The three distances as ONE value.
 *
 * They are an ARGUMENT and no longer a constant read from module scope,
 * because two callers need different numbers: the smoke check feeds hand-
 * derived thresholds to derive its expectations from, and the running client
 * feeds whatever the player set in the menu. A module-level `let` that the
 * menu writes would work exactly once — it would also make every function
 * here impure, which is the one thing this file is not allowed to be.
 */
export interface ScatterLodCfg {
  /** Nearer than this an instance stands at the full mesh (metres). */
  nearM: number;
  /** Farther than this at the low mesh. In between it keeps what it has. */
  farM: number;
  /** Beyond this it is not drawn at all (metres). */
  cullM: number;
}

/** What the constants above are: the DEFAULT distances, the ones a player who
 *  never opens the menu plays with. `prefs.ts` holds the same three numbers as
 *  its stored defaults (it must stay import-free, so it cannot read them from
 *  here) and the smoke check pins the two against each other. */
export const SCATTER_LOD_DEFAULTS: ScatterLodCfg = {
  nearM: SCATTER_TIER_NEAR,
  farM: SCATTER_TIER_FAR,
  cullM: SCATTER_CULL_FAR,
};

/** What ONE instance is drawn as: 0 = the full mesh, 1 = the low mesh,
 *  2 = not at all.
 *
 *  Numbers and not the payload's tier tokens (`'full'`/`'low'`), because this
 *  is what a `Uint8Array` per scatter entry holds — one byte per instance,
 *  read and
 *  written for every instance of every entry on every LOD tick. A string per
 *  instance would allocate on a path whose whole point is not to. */
export type InstanceTier = 0 | 1 | 2;

/** How far back inside the cull distance a hidden instance has to come before
 *  it is drawn again — 0.92 of it, i.e. 110.4 m at the default 120 m.
 *
 *  The cull edge needs the same treatment the 35…45 m band gives the mesh
 *  swap, and for a harsher reason: a tree that pops in and out with every
 *  centimetre of camera drift is far more visible than one that swaps mesh.
 *  A FACTOR rather than a second distance, so a player who sets the cull to
 *  400 m gets a band that scales with it instead of a 0.4 % sliver. */
export const SCATTER_UNHIDE_FACTOR = 0.92;

/**
 * Which of the three classes ONE instance belongs in, given how far away IT is
 * and what it was drawn as last tick.
 *
 * Two hystereses, both of them "the answer inside the band is whatever is
 * already there":
 *
 *   - `nearM`…`farM` between full and low, exclusive on BOTH ends — at exactly
 *     35 m nothing is promoted and at exactly 45 m nothing is demoted, so a
 *     camera parked on the number keeps what it has.
 *   - `SCATTER_UNHIDE_FACTOR`·`cullM`…`cullM` between drawn and hidden. Note
 *     the asymmetry: hiding happens BEYOND the cull distance, showing again
 *     only well inside it, so the two thresholds cannot chase each other.
 *
 * A previously hidden instance that comes back re-enters as `low` and is then
 * judged by the band like everything else — it kept no memory of the tier it
 * had before it was culled, and at 0.92·cull it is in low territory anyway.
 * The one case where that matters is a hand-set cfg whose bands overlap; the
 * answer there is still a tier and not a crash.
 *
 * A NON-FINITE DISTANCE HIDES the instance. One function answers both the
 * mesh and the cull question here, so it has to give the answer that draws
 * nothing rather than the one that draws a NaN matrix.
 */
export function instanceTier(
  distM: number, prev: InstanceTier, cfg: ScatterLodCfg,
): InstanceTier {
  // Negated, so a NaN distance lands here instead of in the comparisons below.
  if (!(distM <= cfg.cullM)) return 2;
  let held: InstanceTier = prev;
  if (prev === 2) {
    if (!(distM < SCATTER_UNHIDE_FACTOR * cfg.cullM)) return 2;
    held = 1;
  }
  if (distM < cfg.nearM) return 0;
  if (distM > cfg.farM) return 1;
  return held;
}

/**
 * What share of the instances at that distance is drawn, measured at the
 * instance's own distance and against a given cfg.
 *
 * The line: flat 1 up to `farM`, straight down to
 * `SCATTER_MIN_SHARE` at `cullM`, nothing beyond. `cullM > farM` need not be
 * checked before the division: the only branch that divides is the one where
 * `distM` is above `farM` and at most `cullM`, which cannot be reached unless
 * the two differ.
 */
export function instanceShare(distM: number, cfg: ScatterLodCfg): number {
  if (!(distM <= cfg.cullM)) return 0;
  if (distM <= cfg.farM) return 1;
  const t = (distM - cfg.farM) / (cfg.cullM - cfg.farM);
  return 1 - t * (1 - SCATTER_MIN_SHARE);
}

/**
 * A number in [0,1) that belongs to an instance INDEX and to nothing else.
 *
 * This is what makes thinning stable. The area-wide budget this replaces could
 * cap the tail of the list because one distance governed the whole area; per
 * instance there is no tail — every instance has its own share, and "the first
 * n of them"
 * would mean a different n per tick and a different SET per tick, i.e. trees
 * blinking in and out while the player stands still. A hash of the index gives
 * each instance a fixed place in the queue, so walking towards a wood always
 * regrows the same trees in the same order.
 *
 * The mix is the murmur3 finaliser over the index times the golden-ratio
 * constant. The textbook `fract(sin(i·12.9898)·43758.5453)` was measured
 * first and is visibly biased in the low quarter — it drew 14 % too few at a
 * share of 0.25, exactly where the thinning is supposed to work — while this
 * one stays inside 3.5 % over the same 1000 indices.
 *
 * `hash(0) === 0` falls out of the multiplication and is kept deliberately:
 * instance 0 survives as long as anything of the entry is drawn at all. That
 * is the floor the area-wide budget had to spell out ("at least ONE as long as
 * anything is drawn"), and here it costs no rule at all — a lone landmark tree
 * is instance 0 of a one-instance entry.
 *
 * EXPORTED because the undergrowth's per-tuft shade uses the same mixer over
 * a different key (`undergrowthShade` in `scene/undergrowth.ts` folds the
 * tuft's POSITION into it). One mixer, measured once — and read the note
 * there for why the shade must not be keyed on the index this function is
 * usually called with.
 */
export function instanceHash(index: number): number {
  let h = Math.imul(index | 0, 2654435761) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/**
 * Whether instance `index` is part of the thinned-out set at its distance.
 *
 * Pure and stateless on purpose: the set is not remembered anywhere, it is
 * recomputed from index and distance every tick and comes out the same. Which
 * also means the answer is MONOTONE in the distance — an instance that is
 * drawn 100 m away is drawn at 60 m too, because its hash did not move and
 * the share only grew. Nothing pops out while the player walks closer.
 *
 * Hiding by distance is `instanceTier`'s answer, not this one's; an instance
 * is drawn when its tier is not 2 AND it is visible here.
 */
export function instanceVisible(
  index: number, distM: number, cfg: ScatterLodCfg,
): boolean {
  const share = instanceShare(distM, cfg);
  if (share >= 1) return true;
  if (share <= 0) return false;
  return instanceHash(index) < share;
}

/* ==========================================================================
 * THE FAR IMPOSTORS (2026-08-15) — what stands BEYOND the cull line
 *
 * The cull distance ends the MESHES, and it used to end the wood with them: a
 * forest 130 m away was bare ground, and the player walked into a world that
 * grew itself out of nothing. An impostor is not a second asset and not a
 * second authoring step — it is a RENDER stage: one billboard quad per
 * instance, its texture baked from the entry's own low mesh at runtime
 * (`scene/impostors.ts`), standing at the very positions the meshes would
 * stand at.
 *
 * WHAT IS ARITHMETIC AND THEREFORE LIVES HERE: the distance window, the
 * thinning over it, the yaw of one billboard and the size and height of its
 * quad. The GPU half — baking the texture, filling the instance buffer — is
 * the other file's, and none of it decides geometry.
 *
 * THE POSITIONS ARE THE MESHES' OWN. That is the whole promise of the stage:
 * the same seed-stable sampler output, the same array, only a different
 * distance window — so a tree crossing the cull line swaps its billboard for
 * its mesh WHERE IT STOOD and never jumps a metre.
 * ========================================================================== */

/** Beyond this nothing of the scatter is drawn at all, in metres — the end of
 *  the impostor window and the end of the wood.
 *
 *  400 m sits inside the distance-haze band (it closes the view at 520 m,
 *  `scene/engine.ts`), which is what makes the stage affordable to end: a
 *  billboard that vanishes at 400 m does so behind enough haze that nobody
 *  sees it go. A CONSTANT and not a preference: the object-LOD menu sets the
 *  three MESH distances, and a fourth number for a stage that costs one draw
 *  call per entry would be a setting for the sake of having one. */
export const IMPOSTOR_FAR_M = 400;

/** The share of billboards still drawn immediately before that edge — the
 *  props' own `SCATTER_MIN_SHARE`, over its own span. A quarter of a wood
 *  still reads as a wood on the horizon, which is the very reason the meshes
 *  keep a floor rather than fading to nothing. */
export const IMPOSTOR_MIN_SHARE = 0.25;

/**
 * How far the bake camera is raised above the horizon, in radians (10°).
 *
 * NOT frontal-flat, and not a look: the player's camera hangs above the world
 * (18° close up, 62° far out, `scene/engine.ts`), so a billboard baked dead
 * level shows a tree from an angle nobody ever looks from — the crown reads
 * flat and the ground contact reads wrong. Ten degrees is the compromise that
 * still lets the same texture serve the near end of the window, where the
 * player's own angle is shallow.
 *
 * It is a CONSTANT of the geometry, not of the renderer: `impostorQuad` needs
 * the very angle the bake used to put the tree's foot on the ground, so both
 * sides read this one number.
 */
export const IMPOSTOR_ELEV_RAD = (10 * Math.PI) / 180;

/** How much air the baked image keeps around the prop (2.5 % per side). The
 *  quad is drawn with `alphaTest`, so a silhouette touching the texture border
 *  would be cut off by the clamp rather than fading — and the rim costs
 *  nothing but a few transparent texels. */
export const IMPOSTOR_BAKE_PAD = 1.05;

/**
 * Whether ONE instance at that distance belongs to the impostor stage at all.
 *
 * The window is `(cullM, IMPOSTOR_FAR_M]` — open at the near end and closed at
 * the far one, which is exactly the complement of what the meshes draw
 * (`instanceTier` hides at `distM > cullM`). One line, two representations,
 * and never both: at 120.0 m the mesh has it, at 120.1 m the billboard does.
 *
 * A cull distance a player pushed past `IMPOSTOR_FAR_M` empties the window
 * rather than inverting it — the meshes then reach further than the stage
 * that exists to replace them, which is a legitimate setting and not a case
 * to correct. A non-finite distance draws nothing (negated comparison).
 */
export function impostorInWindow(distM: number, cfg: ScatterLodCfg): boolean {
  return distM > cfg.cullM && distM <= IMPOSTOR_FAR_M;
}

/**
 * What share of the billboards is drawn at that distance: flat 1 at the cull
 * line, straight down to `IMPOSTOR_MIN_SHARE` at `IMPOSTOR_FAR_M`.
 *
 * ITS OWN SPAN, not a continuation of `instanceShare`. The mesh line ends at a
 * quarter because drawing a mesh is expensive; a billboard is two triangles,
 * so the stage starts full and spends its own 280 m getting thin. The visible
 * consequence is honest and worth naming: crossing the cull line OUTWARD the
 * wood gets fuller, because trees the mesh thinning had taken away come back
 * as billboards. Nothing MOVES while that happens — the two thinnings share
 * `instanceHash`, so the meshes drawn inside the line are a subset of the
 * billboards drawn outside it.
 */
export function impostorShare(distM: number, cfg: ScatterLodCfg): number {
  if (!impostorInWindow(distM, cfg)) return 0;
  const span = IMPOSTOR_FAR_M - cfg.cullM;
  if (!(span > 0)) return 0;
  const t = (distM - cfg.cullM) / span;
  return 1 - t * (1 - IMPOSTOR_MIN_SHARE);
}

/**
 * Whether billboard `index` is part of the thinned-out stage at its distance.
 *
 * The rule of `instanceVisible`, down to the shared `instanceHash`: stable
 * while nothing moves, monotone as the player walks closer, and instance 0
 * survives as long as anything of the entry is drawn.
 */
export function impostorVisible(
  index: number, distM: number, cfg: ScatterLodCfg,
): boolean {
  const share = impostorShare(distM, cfg);
  if (share >= 1) return true;
  if (share <= 0) return false;
  return instanceHash(index) < share;
}

/**
 * Which way ONE billboard turns: the yaw, in radians, that faces its quad at
 * the camera — AROUND THE Y AXIS AND NOTHING ELSE.
 *
 * That is the whole difference to the usual "full" billboard, and the reason
 * the camera's HEIGHT is not an argument here: a tree stands upright. A quad
 * that also tilts back towards a camera looking down from 60° would lay the
 * trunk over the ground and the wood would tip as the player zooms out.
 *
 * The angle is `atan2(dx, dz)` and not `atan2(dz, dx)`: a rotation by θ about
 * +Y takes the quad's own normal (0, 0, 1) to (sin θ, 0, cos θ), so the sine
 * belongs to x. An instance the camera stands exactly on gives 0 — atan2(0, 0)
 * is 0 in JS, and a quad seen edge-on from directly above is invisible either
 * way.
 */
export function impostorYaw(px: number, pz: number,
                            camX: number, camZ: number): number {
  return Math.atan2(camX - px, camZ - pz);
}

/** What the bake framed, as ratios of the prop's own model — everything
 *  `impostorQuad` needs to turn a target height into a quad, and nothing about
 *  pixels. */
export interface ImpostorFrame {
  /** how many MODEL heights the image spans vertically (> 1: the padding and
   *  the raised camera both add air) */
  spanH: number;
  /** the image's width divided by its height — the quad's aspect */
  aspect: number;
}

/**
 * The orthographic frame the bake renders in, from the prop's own box.
 *
 * `heightM` is the model's bounding-box height, `radiusM` its horizontal reach
 * measured FROM THE MODEL ORIGIN (the largest of |min.x|, |max.x|, |min.z|,
 * |max.z|) — from the origin and not from the box centre, because the instance
 * matrix puts the model's ORIGIN on the scattered point. A frame centred on
 * the box would draw a lopsided tree half a metre beside its own position, and
 * the mesh it swaps with does not move either (`groundedGeometry` lifts the
 * box but never recentres it).
 *
 * Vertically the frame is centred on the box, and it has to allow for the
 * raised camera: the image's up axis is (0, cos e, −sin e), so a point at the
 * box's rim contributes `(height/2)·cos e` and its DEPTH another
 * `radius·sin e`. Both padded by `IMPOSTOR_BAKE_PAD`.
 *
 * `null` for a degenerate model (no height, no width, junk numbers) — such a
 * prop gets no billboard at all rather than a quad scaled by an infinity.
 */
export function impostorFrame(heightM: number, radiusM: number): ImpostorFrame | null {
  if (!(heightM > 0) || !(radiusM > 0)) return null;
  const halfW = radiusM * IMPOSTOR_BAKE_PAD;
  const halfH = ((heightM / 2) * Math.cos(IMPOSTOR_ELEV_RAD)
    + radiusM * Math.sin(IMPOSTOR_ELEV_RAD)) * IMPOSTOR_BAKE_PAD;
  if (!(halfH > 0)) return null;
  return { spanH: (2 * halfH) / heightM, aspect: halfW / halfH };
}

/** One billboard's quad in world metres: its size, and how far its CENTRE
 *  stands above the point the instance sits on. */
export interface ImpostorQuad {
  w: number;
  h: number;
  centreY: number;
}

/**
 * The quad ONE instance of an entry is drawn on.
 *
 * `targetH` is the entry's own drawn height (`scatterTargetH`) — the same
 * number the mesh is scaled to, which is what makes the swap at the cull line
 * a swap and not a jump in size. The image spans `spanH` model heights, so the
 * quad spans `targetH · spanH`, and its width follows the frame's aspect.
 *
 * THE CENTRE OFFSET IS WHERE THE FOOT GOES. In the baked image the model's
 * base sits `(height/2)·cos e` BELOW the image centre (the frame is centred on
 * the box, the camera looks down by `e`). Scaled into the world that is
 * `targetH·cos e / 2`, so lifting the quad centre by exactly that puts the
 * tree's foot on the ground the instance stands on — independently of how much
 * air the padding added, which grows the quad symmetrically about its centre.
 */
export function impostorQuad(targetH: number, frame: ImpostorFrame): ImpostorQuad {
  const h = targetH * frame.spanH;
  return {
    w: h * frame.aspect,
    h,
    centreY: (targetH * Math.cos(IMPOSTOR_ELEV_RAD)) / 2,
  };
}

/**
 * The four world corners of one billboard, in the order
 * bottom-left, bottom-right, top-right, top-left as seen from the camera.
 *
 * Nothing draws through this — the renderer composes an instance matrix from
 * `impostorYaw` and `impostorQuad` and lets the GPU transform the quad. It
 * exists so the SHAPE is checkable without a GPU (§ B5a): the four corners are
 * what a billboard IS, and the one property that must never be lost is
 * visible in them — every corner keeps the y of its own edge, whatever the
 * camera does. A full billboard tilts, and its corners say so.
 *
 * `cx, cy, cz` is the quad's centre (the instance's ground point lifted by
 * `ImpostorQuad.centreY`).
 */
export function impostorCorners(cx: number, cy: number, cz: number,
                                w: number, h: number,
                                camX: number, camZ: number): number[][] {
  const yaw = impostorYaw(cx, cz, camX, camZ);
  // The quad's own +X axis under a rotation of `yaw` about +Y. The vertical
  // axis is (0, 1, 0) and stays it — see the doc comment.
  const rx = Math.cos(yaw) * (w / 2);
  const rz = -Math.sin(yaw) * (w / 2);
  const top = cy + h / 2;
  const bottom = cy - h / 2;
  return [
    [cx - rx, bottom, cz - rz],
    [cx + rx, bottom, cz + rz],
    [cx + rx, top, cz + rz],
    [cx - rx, top, cz - rz],
  ];
}

/**
 * How ONE bake attempt of `scene/impostors.ts` ended.
 *
 *  - `baked` — there is a texture.
 *  - `unbakeable` — the file ARRIVED and there is still nothing to render: no
 *    mesh in it, an empty box, a degenerate frame (`impostorFrame` → null).
 *  - `load-failed` — the GLB did not arrive. `loadGlb` already retried it three
 *    times with backoff before it answered null, so this is a backend that went
 *    away, not a broken prop.
 *  - `no-renderer` — the tick ran before `setImpostorRenderer`. Nothing was
 *    even tried, and nothing was learnt about the prop.
 */
export type ImpostorBakeAttempt =
  'baked' | 'unbakeable' | 'load-failed' | 'no-renderer';

/**
 * What the bake cache is allowed to REMEMBER of such an attempt — `store` the
 * texture, `refuse` the prop for the session, or `retry` on the next contact.
 *
 * NOT ARITHMETIC, and it sits in this import-free module for one reason: it is
 * the only part of the bake that can be checked without a GPU
 * (`smoke_impostors.mjs` section (G)), and the decision it makes is invisible
 * until an hour later, when a wood that a single dropped request touched is
 * still bare.
 *
 * ONLY A PROP THAT CANNOT BE BAKED IS REFUSED. The refusal exists so the tick
 * does not queue the same hopeless job every second — it is a statement about
 * the MODEL, and the two failures above that say nothing about the model must
 * not produce one: a backend restarting for ten seconds would otherwise cost
 * every prop it was asked for its billboards for the whole session, and only a
 * reload would bring them back.
 */
export function impostorBakeVerdict(
  attempt: ImpostorBakeAttempt,
): 'store' | 'refuse' | 'retry' {
  if (attempt === 'baked') return 'store';
  if (attempt === 'unbakeable') return 'refuse';
  return 'retry';
}

/* ==========================================================================
 * THE UNDERGROWTH (2026-08-15, rebuilt 2026-08-16) — the layer NOBODY authored
 *
 * A wood reads as a wood when something stands BETWEEN the trunks, and until
 * now that something was a second scatter row somebody had to paint onto every
 * single wood. The terrain KIND already knows the answer — forest is
 * undergrown, a path is not — so it says it in one number
 * (`meta.undergrowth`, 0..1, § A9) and the client grows the layer itself.
 *
 * WHAT LIVES HERE is only the arithmetic of it: how many tufts one CELL of the
 * camera-local raster carries, how tall each one stands, how far the layer is
 * drawn and which of its instances survive at a distance. The cell raster
 * itself — which cells are wanted, and under which seed each of them samples —
 * is `scene/undergrowth.ts`, together with the blade texture and the meshes.
 *
 * IT IS NO LONGER GROWN PER PAINTED AREA, and that is the whole of the
 * 2026-08-16 rescue. A rate over a lake-sized shape is a number nobody typed,
 * so the old build capped each area at 20 000 instances — which on a square
 * kilometre of deep forest thinned the layer to 0.02/m2 and made it
 * effectively invisible, exactly the acceptance finding. The layer is only
 * ever seen out to `UNDERGROWTH_CULL_M`, so it is now grown where it is seen:
 * per 64 m CELL around the anchor, which makes a 10 km2 wood locally exactly
 * as dense as a small meadow and costs a constant amount whatever the world
 * looks like.
 * ========================================================================== */

/** The full base density of the layer, in instances per SQUARE METRE — what a
 *  kind with `undergrowth: 1` gets. Everything else is this times the kind's
 *  own number, so the catalog value is a share and never a count.
 *
 *  0.80/m2 (0.40 before the acceptance of 2026-08-16, 0.15 before the
 *  camera-local rebuild) puts a tuft every 1.1 m of edge at full value; a
 *  forest at the seeded 0.6 carries one about every 1.4 m. That is the
 *  difference the first finding named: at 0.40 the layer read as SEPARATE
 *  tufts one walks past.
 *
 *  THE DENSITY STAYED WHERE IT IS WHEN THE TUFT SHRANK to 60 % (the sight
 *  round of 2026-08-16: "the blades could be a little smaller, and they lack
 *  volume"), and the spacing has to be read together with that. A tuft is
 *  drawn `UNDERGROWTH_W_RATIO` times its own height wide
 *  (`scene/undergrowth.ts`), i.e. 0.41 m at the new reference height against
 *  0.69 m before — so at ~1.1 m spacing the silhouettes no longer touch, and
 *  the closed floor of the earlier round is now carried by the THIRD quad
 *  (three planes in a star instead of two crossed cards) rather than by the
 *  width of a single tuft. Turning this number up is the lever if the next
 *  sight round finds the ground bare again; it is not a lever for the SIZE of
 *  a blade, which is what the finding was about.
 *
 *  WHAT IT COSTS, and why the number can be this high: the cells are
 *  camera-local, so the world's size never enters. A cell of 64 m at full
 *  value wants round(64²/100 · 80) = 3277 tufts, and the 5-9 cells that carry
 *  anything drawable inside `UNDERGROWTH_CULL_M` therefore put roughly
 *  15 000-30 000 tufts of three quads each into the frame — instanced, so a handful of
 *  draw calls, and the per-cell ceiling of 8000 is still more than twice what
 *  the densest legal ground asks for.
 *
 *  THE OVERDRAW GUARD, because that is the cost this layer really pays:
 *  alpha-tested quads cost FILL RATE, not draw calls, and a carpet seen at a
 *  grazing angle overdraws the same pixels many times over. If the sight
 *  acceptance stutters, the first lever is THIS constant (halving it halves
 *  the fill) and the second is the near end of the LOD ladder,
 *  `UNDERGROWTH_FADE_M` (30 m) — beyond it the layer is already thinned
 *  linearly to nothing at `UNDERGROWTH_CULL_M`. Neither is a per-world dial:
 *  they are the two numbers to turn here. */
export const UNDERGROWTH_DENSITY_PER_M2 = 0.80;

/** Edge of ONE cell of the layer's raster, in metres — ORIGIN-ANCHORED, so a
 *  cell is a fixed square of the world and not a square around the player.
 *  That is what makes a cell's content re-derivable: the same ground gives the
 *  same tufts whichever direction it was walked into from.
 *
 *  64 m is the compromise between the two costs a cell has. Smaller cells
 *  cross more borders per metre walked (a rebuild each time) and cost a draw
 *  call each; bigger ones make every single crossing expensive and force the
 *  radius out. At 64 m one crossing rebuilds about five cells of ~2000
 *  instances — a few milliseconds, once every 64 m. */
export const UNDERGROWTH_CELL_M = 64;

/** How far around the anchor cells are held, in metres.
 *
 *  TWO CELL WIDTHS, i.e. more than twice the cull distance, and the margin is
 *  the point: nothing beyond `UNDERGROWTH_CULL_M` (60 m) is DRAWN, so a radius
 *  of exactly that would build a cell the very moment something in it became
 *  visible — a hitch at the edge of the picture every time. At 128 m a cell is
 *  built a whole cell-width before the player can see anything in it, and the
 *  LOD keeps it at zero instances until then, which costs nothing per tick. */
export const UNDERGROWTH_CELL_RADIUS_M = 128;

/** Hard ceiling of the layer PER CELL — a guard, not a budget.
 *
 *  A cell of 64 m at the full base density wants round(4096/100 · 80) = 3277
 *  tufts, so 8000 is nearly two and a half times what the densest legal ground
 *  asks and CANNOT be reached through `undergrowthDensityPer100m2` (the catalog
 *  value is clamped to 1). It exists for the same reason the sampler has a
 *  ceiling at all: a hand-edited density that crosses the JSON boundary must
 *  cost a thicker cell, never a hundred thousand instances built in one frame.
 *
 *  There is deliberately NO "capped" report beside it any more. The old
 *  per-area ceiling was reached by ordinary worlds and silently thinned them,
 *  which is what the console line existed to explain; a ceiling nothing can
 *  reach has nothing to explain. */
export const UNDERGROWTH_MAX_PER_CELL = 8000;

/** Up to here every tuft of the layer is drawn (metres). */
export const UNDERGROWTH_FADE_M = 30;
/**
 * Beyond this NOTHING of the layer is drawn (metres) — half the scatter's own
 * default cull distance, and that is the point of a second set of numbers.
 *
 * A tuft is knee-high: at 60 m it is a few pixels tall, and the thousands of
 * them a wood carries cost the same per-instance work as the trees do. The
 * trees keep their 120 m because a tree at 120 m is still a tree in the
 * picture; the undergrowth is gone long before it stops being drawn.
 */
export const UNDERGROWTH_CULL_M = 60;

/** The share still drawn at the very cull edge — ZERO, and unlike the
 *  scatter's `SCATTER_MIN_SHARE` (a quarter) that is on purpose. The scatter
 *  keeps a floor because a wood that fades to nothing POPS when it crosses the
 *  line, and a quarter of a wood still reads as a wood on the horizon. Neither
 *  holds for the undergrowth: the last blade of it is invisible long before
 *  60 m, so there is nothing to pop, and a floor would keep a quarter of every
 *  meadow's tufts alive out to the edge for a picture nobody can see. Fading
 *  to 0 also removes the need for the cull hysteresis the props have — the set
 *  is already empty when the line is reached. */
export const UNDERGROWTH_MIN_SHARE = 0;

/** How tall ONE tuft of the layer stands, in metres — a span, not a number:
 *  a floor of blades all exactly the same height reads as a texture, not as
 *  growth.
 *
 *  SIXTY PER CENT OF THE 0.4 … 0.7 m IT WAS (sight round of 2026-08-16, "the
 *  blades could be a little smaller"): 0.24 … 0.42 m, i.e. ankle- to
 *  shin-high on the 1.70 m reference figure instead of knee-high. The width
 *  goes with it — `UNDERGROWTH_W_RATIO` is a ratio of the height, so the
 *  absolute width falls by the same factor and a tuft keeps its proportions.
 *
 *  What it costs is stated where it is paid: the spacing argument in
 *  `UNDERGROWTH_DENSITY_PER_M2` above (the silhouettes of two neighbours no
 *  longer meet) and the fill rate in `scene/undergrowth.ts` (three quads at
 *  36 % of their old area each = 54 % of the pixels the old two covered). */
export const UNDERGROWTH_H_MIN = 0.24;
export const UNDERGROWTH_H_MAX = 0.42;

/**
 * The catalog's share as the density the shared sampler takes (per 100 m2).
 *
 * The value crosses a JSON boundary, so "not given" is every non-number and
 * every non-positive one, and anything above 1 is CLAMPED exactly as the
 * server clamps it — a hand-edited row must cost a thicker meadow, never a
 * hundred thousand tufts.
 */
export function undergrowthDensityPer100m2(value: number): number {
  const v = Number(value);
  if (!Number.isFinite(v) || v <= 0) return 0;
  return UNDERGROWTH_DENSITY_PER_M2 * 100 * Math.min(v, 1);
}

/**
 * How many tufts ONE cell of the raster samples — the sampler's own count rule
 * (`round(areaM2 / 100 * density)`) over a cell's 4096 m2, capped.
 *
 * Written with the SAME expression the sampler evaluates, so the number this
 * answers and the number `scatterInstances` draws cannot drift apart in the
 * last bit of a float.
 *
 * IT IS A NUMBER OF CANDIDATES, not a promise of instances, and the difference
 * is what makes the density right at a border: the cell always draws this many
 * points over its whole 4096 m2 and then DROPS the ones that do not belong to
 * the shape being sampled, that stand on a building's footprint or that lie
 * under ground painted over it. A cell that is half wood and half meadow
 * therefore carries half of this from each — which is the same tufts per
 * square metre as a cell that is all wood, wherever the painted borders
 * happen to run.
 *
 * The area-wide `undergrowthCount`/`undergrowthCapped` pair this replaces went
 * with the per-area build: there is no "the shape wanted more than it got" to
 * report when the shape is not the unit any more (see
 * `UNDERGROWTH_MAX_PER_CELL`).
 */
export function undergrowthCellCount(value: number): number {
  const density = undergrowthDensityPer100m2(value);
  if (!(density > 0)) return 0;
  const cellM2 = UNDERGROWTH_CELL_M * UNDERGROWTH_CELL_M;
  return Math.min(Math.round((cellM2 / 100) * density), UNDERGROWTH_MAX_PER_CELL);
}

/**
 * How tall the tuft at `yaw` stands, in metres.
 *
 * THE HEIGHT COMES OUT OF THE YAW, and that is not a trick to save work: the
 * sampler already draws a uniform number in [0, 2pi) for every instance, and
 * an extra stream would either shift the existing one (moving every tuft) or
 * need a second PRNG per area. The yaw is uniform, so the height is uniform
 * over the span, and the correlation between "which way a blade faces" and
 * "how tall it is" is invisible in a field of them.
 *
 * A junk yaw gives the shortest tuft rather than a NaN scale — a NaN matrix
 * removes an instance from the screen instead of shrinking it.
 */
export function undergrowthHeight(yaw: number): number {
  const t = Number(yaw) / (Math.PI * 2);
  const frac = Number.isFinite(t) ? t - Math.floor(t) : 0;
  return UNDERGROWTH_H_MIN + (UNDERGROWTH_H_MAX - UNDERGROWTH_H_MIN) * frac;
}

/**
 * What share of the layer is drawn at that distance — flat 1 up to
 * `UNDERGROWTH_FADE_M`, straight down to `UNDERGROWTH_MIN_SHARE` (0) at
 * `UNDERGROWTH_CULL_M`, nothing beyond.
 *
 * The same line `instanceShare` draws for the props, with its own two
 * distances and its own floor — and no `cfg`: the player's LOD menu sets the
 * distances of the OBJECT scatter, which is a picture they can judge (trees
 * appearing and disappearing). The undergrowth is a carpet that is gone from
 * the picture at 60 m whatever anyone sets, so it is a constant here and not a
 * fourth field in a settings dialog.
 *
 * A non-finite distance draws nothing, written as a negated comparison for
 * exactly that reason.
 */
export function undergrowthShare(distM: number): number {
  if (!(distM <= UNDERGROWTH_CULL_M)) return 0;
  if (distM <= UNDERGROWTH_FADE_M) return 1;
  const t = (distM - UNDERGROWTH_FADE_M)
    / (UNDERGROWTH_CULL_M - UNDERGROWTH_FADE_M);
  return 1 - t * (1 - UNDERGROWTH_MIN_SHARE);
}

/**
 * Whether tuft `index` is part of the thinned-out layer at its own distance.
 *
 * The very rule `instanceVisible` follows, down to the shared `instanceHash`:
 * stable (the set does not change while nothing moves) and monotone (walking
 * closer only ever adds blades). Instance 0 has hash 0 and is therefore drawn
 * as long as ANY of the layer is — but here that ends at the cull distance
 * itself, because the share reaches exactly 0 there.
 */
export function undergrowthVisible(index: number, distM: number): boolean {
  const share = undergrowthShare(distM);
  if (share >= 1) return true;
  if (share <= 0) return false;
  return instanceHash(index) < share;
}
