/**
 * WHERE A STOREY-0 PLACEMENT STANDS — one law, both renderers
 * (docs/schnittstellen-3d.md § A16.9, finding round 2026-08-21).
 *
 * THE DEFECT THIS CLOSES. Since "Ein Boden" E5a the floor of storey 0 is the
 * TERRAIN, and terrain has relief. The scene payload, however, states every
 * placement against the scene frame's own datum — `y = 0` is the ground under
 * the location's ANCHOR PIN, one single height for the whole location. On a
 * built plot that is exact, because the bake stamps the plot flat to precisely
 * that height (§ A16.4). On a NATURAL location it is exact at one point and
 * wrong everywhere else. Measured on "Mondscheinsee" (pin ground −2.00 m, the
 * lake bed): its two shore dioramas are composed at `bottom_y` −0.28, i.e.
 * drawn at −2.28, while the terrain under their own anchors stands at +0.277
 * and +0.335 — they are buried 2.56 m and 2.62 m deep. The location's relief
 * spans 5.08 m.
 *
 * THE RULE, and it is the WORLD-PROPS rule (§ A9a) applied to the scene: a
 * placement on storey 0 stands on the ground AT ITS OWN (x, z), so it is
 * lifted by
 *
 *     lift = groundAt(x, z) − datum
 *
 * where `datum` is the height the payload's `y = 0` was composed against (the
 * pin's ground — `tile.center.y` in the 3D client). Every number in the spec
 * keeps its meaning: `bottom_y`, `offset_y`, `ground_offset_m` and
 * `model_offset_y` all still measure from the storey-0 floor, that floor is
 * simply the one under the object rather than the one under the pin.
 *
 * A DECLARED STOREY IS NOT LIFTED. `level != 0` stands on a PLATE, and a plate
 * is a drawn horizontal surface at a stated height — the terrain does not
 * reach it and must not move it. That is the same split § A16.9 already draws
 * for `plates[]`, `storey_floor_y` and the figure ladder.
 *
 * NOR IS THE BUILDING / GROUND MODEL. `role: 'building'` is not an object
 * standing on the plot, it IS the plot: it spans the whole footprint and § A16.9
 * gives it its own anchoring law (`walk_y_world`, `offset_y`) which the figure
 * ladder reads back. Lifting the mesh by the terrain under its bbox centre
 * would move it away from the very number that says where one walks on it.
 *
 * THE ADMIN PREVIEW CALLS THE SAME FUNCTION. Its stage is a flat plane, so it
 * passes `flatGround(datum)` and the formula returns 0 — the preview inherits
 * the rule instead of being exempted from it, which is what keeps the two
 * renderers from drifting apart again.
 *
 * Pure arithmetic, no `three`: `client3d/scripts/smoke_walk_math.mjs` derives
 * the cases by hand (§ B5a).
 */

/** A world-height answer in WORLD metres at a world (x, z). Returning a
 *  non-finite value means "nothing to say" and is treated as no lift — a
 *  height field that has not arrived must never drop a scene to zero. */
export type GroundSampler = (worldX: number, worldZ: number) => number

/** The sampler of a FLAT stage: everything stands on the datum, so the lift
 *  below is 0 for every point. The admin floor-plan preview uses this — not
 *  as an exemption but as its actual ground truth. */
export function flatGround(datumY: number): GroundSampler {
  return () => datumY
}

/**
 * The lift a placement gets over the height its spec was composed against.
 *
 * @param level    the spec's storey — only 0 is carried by the terrain
 * @param worldX   the placement's anchor in WORLD metres (the caller turns the
 *                 tile-local anchor by the footprint yaw first — § A1.1)
 * @param worldZ   likewise
 * @param datumY   the world height the payload's `y = 0` means
 * @param sampler  the world height function; absent = no lift
 */
export function storeyGroundLift(level: number | undefined,
                                 worldX: number, worldZ: number,
                                 datumY: number,
                                 sampler?: GroundSampler | null): number {
  if ((level ?? 0) !== 0) return 0
  if (!sampler) return 0
  if (!Number.isFinite(datumY)) return 0
  const y = sampler(worldX, worldZ)
  if (!Number.isFinite(y)) return 0
  return y - datumY
}

/** What `storeyGroundRelift` answers: the lift that is now applied, and the
 *  y-DISTANCE the caller has to move its object by to get there from the lift
 *  it was carrying. */
export interface StoreyGroundStep {
  /** the lift belonging to the height field as it stands NOW */
  lift: number
  /** `lift − applied` — the move, 0 when nothing changed */
  delta: number
}

/**
 * MOUNTING AND RE-DRAPING ARE THE SAME MOVE (user finding 2026-08-21).
 *
 * THE DEFECT THIS CLOSES. The lift above is read ONCE, when a scene is
 * mounted — and on a fresh page load a scene mounts BEFORE the fine height
 * tiles under it have arrived. The sampler then answers the coarse overview,
 * or nothing at all, and every placement of that scene keeps that answer for
 * as long as it stands: the Mondscheinhütte was buried 2.5 m deep after every
 * refresh and stood correctly only after a re-save, because a re-save remounts
 * the scene at a moment when the tiles happen to be there. That is an ORDER
 * DEPENDENCE — the drawn world depended on which of two network answers won a
 * race — and it is exactly the defect the world props (§ A9a `redrape`) do not
 * have, because they re-ask the field whenever the relief moves.
 *
 * THE RULE: a lifted placement carries the lift it is standing on, and every
 * time the height field moves it is moved by the DIFFERENCE to the lift the
 * field now says. Passing `applied = 0` makes this the MOUNT — one function,
 * so a scene that mounted coarse and was re-lifted fine ends at the very
 * number a scene mounted once with the fine field lands on, and no placement
 * can ever be lifted twice.
 *
 * "NOTHING TO SAY" IS NOT "COME BACK DOWN", and that is the one place this
 * function may NOT simply diff the lift above. There, a field that has not
 * arrived answers 0 — which is right for a MOUNT (nothing has lifted the
 * object yet) and would be a fall for a re-lift: a tile evicted from the cache
 * would drop a hut that is already standing correctly back into the lake. So a
 * missing sampler, a non-finite sample and a non-finite datum all keep the lift
 * the object carries and move it by nothing.
 *
 * Hand-derived in `client3d/scripts/smoke_walk_math.mjs` § S2 (§ B5a).
 *
 * @param applied the lift the object already carries (0 = it carries none yet)
 */
export function storeyGroundRelift(applied: number,
                                   level: number | undefined,
                                   worldX: number, worldZ: number,
                                   datumY: number,
                                   sampler?: GroundSampler | null): StoreyGroundStep {
  const have = Number.isFinite(applied) ? applied : 0
  // A declared storey stands on a plate: its lift is 0 as a STATEMENT, not as
  // a missing answer, so anything applied comes back off.
  if ((level ?? 0) !== 0) return { lift: 0, delta: -have }
  if (!sampler || !Number.isFinite(datumY)) return { lift: have, delta: 0 }
  const y = sampler(worldX, worldZ)
  if (!Number.isFinite(y)) return { lift: have, delta: 0 }
  const lift = y - datumY
  return { lift, delta: lift - have }
}
