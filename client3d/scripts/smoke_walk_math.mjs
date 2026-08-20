#!/usr/bin/env node
/**
 * Smoke check for the pure walking maths of the 3D client (plan-3d-game
 * stage 3, tasks 3 and 4) — `client3d/src/game/walk.ts` and
 * `client3d/src/game/clickmove.ts`.
 *
 * Usage:  node client3d/scripts/smoke_walk_math.mjs
 *
 * Like `scripts/smoke_scene_recipe.py`, every expected number below is derived
 * BY HAND from the contract, never recorded from the current output.
 *
 * --- WHAT THE METRE WORLD TOOK AWAY (E4 task 5) ---------------------------
 * The grid anchoring, `cellOf`, `stepDirection`, `clampToCell`, `keepAhead`,
 * `splitDiagonal` and the `planRoute` A* are DELETED, and with them the ten
 * frame-loop cases that simulated the step machine against
 * `/world/avatar/step` (a route E3 already removed). The client walks freely
 * on the metre plane now and REPORTS its position (`POST /play/pos`); what
 * stops the figure is geometry, and what decides a location change is the
 * server. The successors are derived by hand further down (`slideBlocked`,
 * the click-walk helpers) and in two other files:
 *   - the SERVER gates: scripts/smoke_play_pos.py
 *   - the ENTRY OFFER in metres: client3d/scripts/smoke_enter_math.mjs
 *

 * --- walkDir --------------------------------------------------------------
 * The engine's camera forward is `(-sin yaw, 0, -cos yaw)` and its right is
 * `(-fwd.z, 0, fwd.x)` (client3d/src/scene/engine.ts, pan block). The avatar
 * has to walk along the SAME vectors, otherwise "forward" means two things.
 *   yaw = 0:      fwd = (-sin 0, -cos 0)      = (0, -1)
 *                 right = (-fwd.z, fwd.x)     = (1, 0)
 *     w      -> (0, -1)
 *     d      -> (1, 0)
 *     s      -> (0, 1)
 *     a      -> (-1, 0)
 *     w+d    -> (1, -1) normalised = (0.7071067811865475, -0.7071067811865475)
 *   yaw = pi/2:   fwd = (-1, 0), right = (0, -1)
 *     w      -> (-1, 0)
 *     d      -> (0, -1)
 *   yaw = pi/4:   fwd = (-0.7071067811865475, -0.7071067811865476)
 *     w      -> that, already unit length
 *   no key, or w+s (they cancel) -> null (never a NaN from normalising 0).
 *
 * --- terrainBlocks: FOOTPRINT WINS (decision 2026-08-13) ------------------
 * `slideBlocked` takes the predicate as a parameter and never asks what a
 * blocker is — main.ts `blockedFor` decides that. Its TERRAIN half is a rule,
 * not a lookup, so it lives in `walk.ts` next to `slideBlocked` and is
 * derived here: painted ground judges the WILDERNESS only, mirroring the
 * server gate of `POST /play/pos` (§ A15 — the location of the point is
 * derived first, `passability_at` runs only for `location_id == ""`).
 *   terrainBlocks(passable, insideFootprint) = !insideFootprint && !passable
 *   rock (passable false) INSIDE a footprint  -> false, one walks on it;
 *   the same rock with no tile over it        -> true, the wilderness wall;
 *   grass, inside or outside                  -> false either way.
 * The lookups stay in main.ts (`terrainGround.passableAt`, `tileAt`), and the
 * server side of the same rule is hand-derived in `scripts/smoke_play_pos.py`
 * [20] and, for NPC routing, `scripts/smoke_nav_grid.py` [12].
 *
 * --- groundScope: HOW FAR THE TERRAIN RULE REACHES (round 2, 2026-08-13) ---
 * The user's decision of 2026-08-13, read MOST-SPECIFIC-FIRST. Both arguments
 * are three-valued: `null` means "there is no such thing over this point".
 * The mirror is `terrain_query.ground_scope` (`scripts/smoke_nav_grid.py`
 * [16]).
 *
 *   groundScope(placeIsArea, roomIsOutdoor) =
 *     roomIsOutdoor !== null  -> roomIsOutdoor ? 'open' : 'built'
 *     placeIsArea  !== null   -> placeIsArea  ? 'open' : 'built'
 *     otherwise               -> 'wilderness'
 *
 *   (null,  null)  -> 'wilderness'   out between the places
 *   (true,  null)  -> 'open'         an area location's footprint
 *   (false, null)  -> 'built'        a building footprint
 *   (true,  false) -> 'built'        an interior room inside an area location
 *   (false, true)  -> 'open'         the terrace of a house
 *   (null,  true)  -> 'open'         (a room outside every footprint cannot
 *                                     happen; the rule still answers)
 *
 * --- terrainPace: THE PACE REACHES AS FAR AS THE SKY (finding 3 + round 2) --
 * The pace is NOT the passability. Where `terrainBlocks` asks only about the
 * wilderness, the ground's `speed_factor` applies inside an OPEN place as
 * well — a village painted onto a lake is waded through, and painting the
 * ground of a place is how one says so. A BUILT place brings its own floor.
 * The mirror is `terrain_query.effective_speed_factor`.
 *
 *   terrainPace(f, scope) =
 *     f not finite               -> 1            (a NaN step never moves again)
 *     scope 'built'              -> 1            (the place has a floor)
 *     scope 'open' && f <= 0     -> 1            (a 0 is not a pace: that
 *                                                 ground was never meant to be
 *                                                 walked, the place declares
 *                                                 it walkable)
 *     otherwise                  -> max(f, MIN_PACE = 0.25)
 *
 * Hand table (catalog: grass 1.0 · forest 0.7 · water 0.4 · rock 0.0, max 2):
 *   (1.0,  wilderness) -> 1        (1.0,  open)  -> 1
 *   (0.4,  wilderness) -> 0.4      (0.4,  open)  -> 0.4   <- THE finding
 *   (0.0,  open)       -> 1        (0.0,  wilderness)-> 0.25  (clamp)
 *   (0.1,  open)       -> 0.25     (0.2,  wilderness)-> 0.25  (clamp)
 *   (2.0,  wilderness) -> 2        (NaN,  open)  -> 1
 *   (-1,   open)       -> 1        (-1,   wilderness)-> 0.25
 *   (0.4,  built)      -> 1        (2.0,  built) -> 1      <- round 2
 *
 * WHY THE CLAMP IS 0.25 HERE and 0.1 on the server: the server clamps a COST
 * against infinity, the client clamps a STEP against the stall detector. At
 * 60 fps a step is `WALK_SPEED · dt · pace = 3.4/60 · pace`; at 0.25 that is
 * 0.014166 m, over `STALL_STEP_M = 0.01` — so a click route survives the
 * slowest legal ground. Without the clamp a factor of 0.05 would give
 * 0.002833 m per frame, `walkStalled` would report a stall and the click
 * order would be dropped after a few frames: a ground one cannot walk a route
 * over is a wall pretending to be mud. Both numbers are checked below.
 *
 * --- WHERE THE PACE IS APPLIED (the freeze finding, round 2) ---------------
 * The avatar's goal is set a LEAD ahead of its CURRENT position every frame
 * (`main.ts`), and `npcs.tick` walks the figure toward that goal:
 *
 *   lead = min(max(WALK_SPEED · dt, MIN_LEAD = 0.15), reach)   <- NOT paced
 *   step = min(distToGoal, WALK_SPEED · dt · pace)             <- paced
 *   the figure counts as MOVING only while distToGoal > MOVE_EPS_M = 0.05
 *
 * At 60 fps the lead is max(0.0567, 0.15) = 0.15 m — three times the movement
 * threshold, whatever the ground. RED COUNTER-PROBE: the old formula multiplied
 * the LEAD (`max(WALK_SPEED·dt, MIN_LEAD) · pace`), which on a 0.25 ground is
 * 0.15 · 0.25 = 0.0375 m — UNDER 0.05, so the figure never moved and played
 * idle instead of swimming. That is the reported "swim animation does not
 * work" in its second half.
 *
 * RED COUNTER-PROBE (the rule itself): the pre-finding-3 rule, which
 * neutralised every ground under a footprint (`inside ? 1 : max(f, MIN)`). It
 * walks the lake dry — 0.4 in a footprint becomes 1 — which is exactly
 * finding 3.
 *
 * --- moveClip: the ground names the clip ----------------------------------
 * A type may carry `meta.move_anim` (§ A9, `swim` on water). It replaces walk
 * AND run — there is no sprinting through a lake — and an absent one leaves
 * the old pair alone. It has the SAME reach as the pace: inside a BUILT place
 * the ground names nothing, one does not swim through a tiled hall. Standing
 * is not this function's business at all.
 *   moveClip('swim', running false, 'wilderness')  -> 'swim'
 *   moveClip('swim', running true,  'wilderness')  -> 'swim'   (no run over it)
 *   moveClip(' swim ', false, 'open')              -> 'swim'   (trimmed)
 *   moveClip('swim', false, 'built')               -> 'walk'   <- round 2
 *   moveClip('swim', true,  'built')               -> 'run'
 *   moveClip('', false, 'wilderness')              -> 'walk'
 *   moveClip('', true,  'wilderness')              -> 'run'
 *   moveClip('   ', true, 'open')                  -> 'run'
 * A kind no model carries is not this file's problem: `figures.CLIP_FALLBACK`
 * maps swim -> walk and everything unknown ends at idle.
 *
 * --- idleClip: the ground names the STANDING clip too (water round) --------
 * The acceptance finding of 2026-08-13: a figure standing still in a lake
 * played its standing clip and stood ON the water. A type may therefore carry
 * a second clip, `meta.idle_anim` (§ A9, `treading-water` on water), and it is
 * the same contract as `move_anim` with the same reach — literally the same
 * helper inside `walk.ts`, so the two can never start reaching differently.
 * `''` is the answer "the ground says nothing", and only then does the
 * caller's own standing clip stand (`npc.animation` or the activity heuristic,
 * § A8) — this function never invents `idle` itself, which is what keeps
 * "no terrain idle" distinguishable from "the terrain wants idle".
 *   idleClip('treading-water', 'wilderness')  -> 'treading-water'
 *   idleClip('treading-water', 'open')        -> 'treading-water'
 *   idleClip('  treading-water  ', 'open')    -> 'treading-water'  (trimmed)
 *   idleClip('treading-water', 'built')       -> ''   <- the reach, see below
 *   idleClip('', 'wilderness')                -> ''
 *   idleClip('   ', 'wilderness')             -> ''
 * RED COUNTER-PROBE, the one that matters: a rule WITHOUT the built-scope
 * gate (`(a || '').trim()` alone) answers 'treading-water' inside a tiled hall
 * standing in that lake — a figure treading water on a floor. The reach is
 * not decoration, it is the difference between the two answers.
 * The npcs.ts side of it, derived by hand and checked below as a table: the
 * standing branch plays `idleClip(...) || standingClip`, so the ground wins
 * where it speaks and nothing changes where it does not, and the SECOND
 * argument of `Figure.play` (the clip-ground drop gate) is
 * `moving || !!groundIdle` — `treading-water` is authored on the water line
 * exactly like `swim` and has to be dropped onto the ground the same way.
 *
 * --- groundSink: how far the ground's DEPTH reaches ------------------------
 * The third field of the same contract (§ A9, world metres): the clip
 * normalisation puts the LOWEST body point on the surface, which for a swimmer
 * is a bent knee, so the body lies on the lake instead of in it.
 * Same reach as the two clips, and a depth that says nothing is 0:
 *   groundSink(0.35, 'wilderness') -> 0.35
 *   groundSink(0.35, 'open')       -> 0.35
 *   groundSink(0.35, 'built')      -> 0     the reach: a tiled hall over the
 *                                           lake is a floor, nobody wades it
 *   groundSink(1.5, 'wilderness')  -> 1.5   the catalog clamp passes through
 *   groundSink(0 / −1 / NaN, …)    -> 0
 * RED COUNTER-PROBE, implemented rather than asserted: the rule this replaced
 * is `sink > 0 ? sink : 0` without the scope, written out below as `ungated`.
 * It answers 0.35 in the tiled hall where the rule in force answers 0, and
 * agrees with it everywhere else — that difference IS the reach.
 *
 * --- sinkForState: WHICH of the two depths is in force (finding 13) --------
 * One depth could not serve both poses: a moving swimmer lies HORIZONTAL and
 * its lowest point is a knee a hand's width under the body, a waiting one
 * treads water UPRIGHT and its lowest point is a foot a body length down. So
 * the catalog carries two (`meta.move_sink_m` / `meta.idle_sink_m`) and the
 * STATE picks, with the water seed 0.35 / 1.3:
 *   sinkForState(true,  'treading-water', W) -> 0.35   moving: the move depth
 *   sinkForState(true,  '',               W) -> 0.35   ...even where the
 *                             ground names no clip: walk stands on its ground,
 *                             so a bog may swallow ankles without a clip
 *   sinkForState(false, 'treading-water', W) -> 1.3    waiting, and the ground
 *                                                      names a standing clip
 *   sinkForState(false, '',               W) -> 0      THE STANDING GATE: the
 *                             figure keeps its OWN clip, which brings its own
 *                             reference height (`sleep` is animated on a bed)
 *   sinkForState(false, 'treading-water', {move: .35, idle: 0}) -> 0
 *                             a ground that names no waiting depth sinks
 *                             nobody while waiting
 * RED COUNTER-PROBE, implemented: the ONE-depth rule this replaced
 * (`single(sink) = moving || groundIdle ? sink : 0`, the state of finding 13)
 * hands the treader the swimmer's 0.35 where the rule in force gives 1.3 —
 * the treader standing on the lake, which is what was reported.
 *
 * --- slopeBlocks: THE HEIGHT GATE (E8 task 1) -----------------------------
 * The client's half of the server rule of `POST /play/pos` § A15 Nr. 8, the
 * exact mirror of `relief.slope_blocks`. The SLOPE limit holds at every
 * distance, and below one metre the STEP limit holds ON TOP of it:
 *
 *   slopeBlocks(dh, dist, maxStep, maxSlope) =
 *     |dh| === 0  -> false
 *     otherwise   -> (dist < 1 && |dh| > maxStep)
 *                    || atan(|dh| / dist) * 180/pi > maxSlope
 *
 * The two hold TOGETHER and not either/or, and this file is where that shows
 * (review finding F1/F2): the walk loop tests a LEAD of ~0.15 m while the
 * server tests a REPORT step of ~1.12 m, so an either/or made the client blind
 * to the whole band the server refuses between 40° and 69° — the figure walked
 * on while the server snapped it back three times a second. The same form also
 * let one climb any wall by crawling: 0.4 m per 0.1 m report is exactly the
 * step limit and passed.
 *
 * At the world defaults (maxStep 0.4 m, maxSlope 40 deg), all derived by hand
 * and the first two straight off the plan (the Mondscheinsee shore and the
 * flat beach):
 *   dh 1.2,  dist 0.5  -> STEP,  1.2 > 0.4                       -> blocked
 *   dh 0.3,  dist 2    -> SLOPE, atan(0.15)  =  8.5308 deg  < 40 -> free
 *   dh 0.3,  dist 0.5  -> STEP,  0.3 <= 0.4                      -> free
 *   dh 0.4,  dist 0.5  -> STEP,  the limit itself passes (`>`)   -> free
 *   dh -1.2, dist 0.5  -> STEP,  the drop is the climb           -> blocked
 *   dh 2,    dist 2    -> SLOPE, atan(1)     = 45      deg  > 40 -> blocked
 *   dh 1.6,  dist 2    -> SLOPE, atan(0.8)   = 38.6598 deg  < 40 -> free
 *   dh 1.6,  dist 0.99 -> the SAME rise a hair under the metre is a step
 *                         as well: 1.6 > 0.4                     -> blocked
 *   dh 0,    dist 0    -> flat ground never blocks (and no atan(0/0))
 * and the two REGIME cases the either/or form waved through:
 *   dh 0.18, dist 0.15 -> ONE walking lead. No step (0.18 <= 0.4), but
 *                         atan(1.2) = 50.1944 deg                -> blocked
 *   dh 0.4,  dist 0.1  -> THE CRAWL: exactly the step limit, so the old form
 *                         said free; atan(4) = 75.9638 deg       -> blocked
 * The metre line itself: at dist exactly 1 the step regime is over (`<` is
 * strict), so dh 0.5 / dist 1 -> atan(0.5) = 26.5651 deg < 40 -> free, while
 * the same 0.5 m at dist 0.999 is a step of 0.5 > 0.4 -> blocked. That jump is
 * the rule, not a defect: a 0.5 m rise one takes in a single stride IS a wall,
 * and the same rise spread over a metre is a ramp.
 * The two LOOKUPS stay in main.ts, deliberately: the heights come from
 * `reliefLiftAt` — the innermost enclosing tile that HAS a relief field, via
 * `scene/tiles.terrainLiftAt` (the payload's field, the server's own source —
 * never the model raycast of `tileGroundY`); a hut without a field of its own
 * stands ON the ground under it rather than flattening it (finding F3). The
 * OPENING EXEMPTION (a point within 1.5 m of an authored opening is never
 * refused for its height — an opening is the ramp onto a plateau) is
 * `slopeBlockedBetween` there. The server half is hand-derived in
 * `scripts/smoke_slope_gate.py`.
 *
 * --- slideBlocked (E4 task 5) ---------------------------------------------
 * The step that would end in blocked ground keeps the component that runs
 * ALONG the boundary: full step if free, else the larger axis alone (ties to
 * x), else the smaller, else stand. Wall at x = 5 (blocked x > 5):
 *   (4,0) -> (6,0)      target blocked, dz = 0            -> (4,0)
 *   (4,0) -> (6,2)      tie -> x tried, blocked; z slides -> (4,2)
 *   (4,0) -> (4.5,0.5)  free                              -> unchanged
 * Disc of radius 1 at the origin: (2,0) -> (0.5,0)        -> (2,0)
 * Quadrant x>0 && z>0:  (-1,-1) -> (1,1)                  -> (1,-1)
 *
 * --- clickmove (E4 task 5) -------------------------------------------------
 * A click plans one POINT, never a route. `planClickWalk` answers null for a
 * blocked point (the click falls through to the info panel) and for a point
 * one already stands on (< GOAL_ARRIVE_M = 0.2 m). `goalDir` on the 3-4-5
 * triangle is (0.6, 0.8) with dist 5; `walkStalled` trips under
 * STALL_STEP_M = 0.01 m, which is a fifth of one 60 fps step (3.4/60).
 *

 * --- talkTargetNear (task 5) ----------------------------------------------
 * Who the avatar may address by walking up to them. The rule has three parts
 * and all three are hand-derived below:
 *  1. Same LOCATION (the map cell) — a neighbouring tile is a different place.
 *  2. Same SHOWN room. Not the room the worldmap reports, the room the 3D view
 *     is currently DRAWING (main.ts `shownRoom`): with an interior open you
 *     stand a metre from someone through a wall you can see, and the prompt
 *     must not fire through it. Outside, both sides are `null` and match.
 *  3. Within TALK_RANGE = 2.5 m, MULTIPLIED BY THE FIGURE SCALE. Interiors
 *     draw their figures at the room scale (`computeNpcStates`, roomScale),
 *     so world metres there are not human metres: at scale 0.3 a 2.5 m reach
 *     is 2.5 * 0.3 = 0.75 world metres. Without that factor an indoor prompt
 *     would cover a third of the room.
 * Distance is the plain XZ distance (heights do not gate a conversation), the
 * comparison is <= so the range itself still counts, and of several
 * candidates the NEAREST wins — ties by name, so a 1 Hz poll cannot flicker
 * between two figures standing at the same distance.
 *   avatar (0,0), other at (2,0), scale 1      -> 2.0  <= 2.5   -> in range
 *   other at (3,0)                             -> 3.0  >  2.5   -> null
 *   other at (2.5,0)                           -> exactly on it -> in range
 *   other at (0.7,0), scale 0.3                -> 0.7  <= 0.75  -> in range
 *   other at (0.8,0), scale 0.3                -> 0.8  >  0.75  -> null
 *   (2,0) and (0,1.2) both in range            -> 1.2 < 2.0 -> the second
 * The avatar is never its own target: it stands in the same list at distance
 * 0 and would beat everyone, so the function is given its own name and skips
 * it (that is why the avatar argument carries a `name` the brief's sketch did
 * not have — the guard belongs to the tested function, not to the glue).
 *
 * --- nearestRoomSwitch (task 6) -------------------------------------------
 * Walking from room to room inside an open interior has to move the room the
 * SERVER keeps for the avatar — that room is what the chat context hangs off.
 * The rule is "the room whose centre is closest", and its whole difficulty is
 * that a centre distance flips the moment one crosses the halfway line: a
 * player standing on that line would fire one /play/enter-room per frame. So
 * a new nearest room has to HOLD for `holdSeconds` before it counts, and a
 * tie never moves anybody.
 *  1. Only rooms of the CURRENT storey are candidates — the room one floor up
 *     is nearer in XZ than the one across the hall, and walking cannot reach
 *     it (there is no vertical movement on foot).
 *  2. Nearest by plain XZ distance to the room centre. A tie keeps `current`;
 *     without a current room the lower id decides, so a figure parked exactly
 *     between two rooms cannot flicker between them.
 *  3. The switch fires only once that room has been the nearest one for
 *     `holdSeconds`; every candidate change restarts the clock. `next` is the
 *     room the avatar should be in — equal to `current` while nothing is due.
 * Layout of the numbers below: hall (0,0), kitchen (10,0), study (20,0) on
 * level 0, attic (0,0) on level 1; holdSeconds = 1.5 as in main.ts. The times
 * are the `nowMs` handed in — the module never reads a clock itself.
 *   current hall, pos (9,0): kitchen 1 m away, hall 9 m -> kitchen leads
 *     t = 0     -> candidate kitchen, sinceMs 0,  next hall
 *     t = 1400  -> 1.4 s held                     next hall
 *     t = 1500  -> exactly the hold               next kitchen
 *     t = 1600  -> 1.6 s                          next kitchen
 *   and the fire re-arms the clock (sinceMs = nowMs), so an unconfirmed
 *   switch cannot repeat before another full hold.
 *   candidate change: t = 0 at (9,0) -> kitchen; t = 1000 at (19,0) -> study
 *     (clock restarts at 1000) -> t = 2000 still hall, t = 2500 study.
 *   storey: same pos (9,0) but currentLevel 1 -> the only candidate is the
 *     attic at (0,0), 9 m away -> after the hold the switch is to the attic.
 *   currentLevel 2 -> no candidate at all -> current stays, no clock.
 *   tie: pos (5,0) is 5 m from hall AND from kitchen
 *     current hall  -> hall  (a tie never moves anybody)
 *     current study -> hall  (lower id, deterministic)
 *     current null  -> hall
 *   pos (1,0), current hall -> already the nearest room, no clock at all.
 *
 * --- the room-walk hook (task 6, fix round) -------------------------------
 * `nearestRoomSwitch` is pure; WHICH storey it is asked about and WHEN a
 * request may leave is the glue in main.ts. Two review findings live exactly
 * there, so the loop below mirrors the hook's order the same way the frame
 * loop further down mirrors the walking hook (a copy, not an import —
 * main.ts drags in Three and the whole app).
 *  1. The storey handed in is the FIGURE'S OWN (`roomLevels[current]`), never
 *     the displayed one (`levelFilter`). The storey button is a view state:
 *     glancing at the first floor from the hall must not post the avatar up
 *     there, and a room set by the HUD chip must not be silently pulled back
 *     down because the view shows the ground floor.
 *  2. A frame without a figure resets the clock. Otherwise a figure that
 *     vanishes (model reload) and returns keeps a candidate whose `sinceMs`
 *     lies in the past, and the very first frame after its return fires —
 *     the hold guarantee gone.
 *  3. A due switch that cannot be sent (a step in flight, a room request in
 *     flight, the same room already asked for, a refused room) keeps the OLD
 *     clock instead of the re-armed one: it goes out the moment the line is
 *     free and does not cost a second full hold.
 *  4. `current` is `roomOf` RESOLVED against the rooms of the tile the figure
 *     stands on, and two things feed `roomOf`: the worldmap poll (every 3 s)
 *     and — since walking into a building became possible (E3) — the answer of
 *     `/world/avatar/step`, which carries the entry room the server has just
 *     put the avatar in. Without that answer the client is blind for up to one
 *     poll, and a blind hook adopts the nearest room centre out of nothing.
 *  5. So while `roomOf` names a room the current tile does NOT have (the
 *     location just changed, the truth is still on its way) the hook does
 *     nothing at all and keeps its clock reset. Is `roomOf` genuinely empty
 *     (outdoors, a location without rooms), the old behaviour stands.
 * Numbers (hall (0,0) L0, kitchen (10,0) L0, attic (0,0) L1; frames every
 * 100 ms; hold 1.5 s):
 *   in the hall, standing still, view switched to storey 1 for 3 s
 *                                       -> 0 requests (own storey is 0)
 *   in the attic, standing still, view on storey 0 for 3 s
 *                                       -> 0 requests (own storey is 1)
 *   in the hall, standing at (9,0)      -> 1 request, at t = 1500
 *   figure gone at 1000, back at 1200   -> clock restarts at 1200,
 *                                          the request goes out at 2700
 *   step in flight 1400…1700            -> the request goes out at 1800,
 *                                          the next free frame — NOT at
 *                                          1500 + 1500 = 3000
 *
 * --- entering a building: MOVED (E4 task 5) -------------------------------
 * `entryOfferNear` speaks metres now and the edge/adjacency rules went with
 * the step. Its derivations live in client3d/scripts/smoke_enter_math.mjs.
 *

 * --- the elevator (E3, floors on foot) ------------------------------------
 * Stage 3 left storey changes out, and the 3D HUD has no room chips — so the
 * upper floors of a building were unreachable in the embodied mode. The
 * building already carries everything needed: `tile.elevatorStops` (one
 * holding point per storey, the NPC storey routing rides them, AV3D-12) and
 * `tile.roomLevels` / `tile.roomCenters`.
 *  1. The elevator is OFFERED when the avatar stands at the holding point of
 *     ITS OWN storey, closer than ELEVATOR_RANGE = 1.5 m — SCALED by the
 *     figure scale, exactly like the talk range (proximity.ts): indoors a
 *     world metre is not a figure metre, so at scale 0.3 the reach is 0.45 m.
 *     The comparison is strict, so the range itself is already out.
 *  2. A storey counts only if it has a stop AND at least one room: a stop on
 *     a storey with no room leads nowhere, and the rooms are what
 *     `/play/enter-room` moves the avatar between.
 *  3. Fewer than two such storeys = no elevator at all (nothing to choose).
 *     Likewise if the avatar's own storey is not one of them — there is no
 *     holding point to stand at.
 *  4. The ride's destination is the room of the target storey whose centre
 *     lies NEAREST that storey's holding point: stepping out of the lift puts
 *     you in the room the lift opens into. Ties fall to the lower id so the
 *     choice cannot flicker.
 * Layout of the numbers below — holding points at (2,0) on every storey,
 * rooms hall (0,0) and store (8,0) on storey 0, attic (1,0) and loft (6,0) on
 * storey 1:
 *   avatar at (2.9,0), scale 1:   0.9 m  <  1.5        -> {levels:[0,1], current:0}
 *   avatar at (3.5,0), scale 1:   1.5 m  =  1.5        -> null (strict)
 *   avatar at (3.6,0), scale 1:   1.6 m  >  1.5        -> null
 *   avatar at (2.4,0), scale 0.3: 0.4 m  <  0.45       -> offered
 *   avatar at (2.5,0), scale 0.3: 0.5 m  >  0.45       -> null
 *   a stop on storey 2 without a room                  -> levels stay [0,1]
 *   rooms only on storey 0                             -> null
 *   avatar on storey 3 (a room, no stop)               -> null
 *   options of {levels:[0,1,2], current:1}             -> [0,2]
 *   target room storey 1: attic |1-2| = 1, loft |6-2| = 4  -> attic
 *   target room storey 0: hall  |0-2| = 2, store |8-2| = 6 -> hall
 *
 * --- the elevator RIDE (E3 review, two findings) --------------------------
 * `elevatorAt`/`elevatorTargetRoom` decide WHETHER and WHERE; the ride itself
 * is glue in main.ts, and two things were missing from it. The sim below
 * mirrors that glue the same way `frameLoop` mirrors the walking hook (a copy
 * of the ORDER: ride start -> walk hook -> tick() -> room walk), with a knob
 * per finding so the old behaviour stays pinned as a number.
 *  1. The ride has to OWN the figure until it arrives. `setPlayerTarget` alone
 *     is overwritten by the very next steering frame, so a held W walks the
 *     figure out of the shaft while the height keeps blending to the target
 *     storey — through the ceiling, into a room nobody chose, and the room
 *     walk then fires a SECOND `/play/enter-room` 1.5 s later. Semantics
 *     chosen: the ride is short, so steering is IGNORED while it runs; it ends
 *     on arrival (or after RIDE_MS = 4 s if something stopped the figure).
 *  2. The ride has to honour `roomRejectedUntil` like the room walk does. A
 *     refused room could otherwise be asked for again immediately, once per
 *     press.
 * Numbers — hall (0,0) on storey 0, landing (0,0) and attic (3,0) on storey 1,
 * holding points at (0,0), the target storey's at height 3; the avatar stands
 * on the holding point of storey 0 and holds W (east) the whole time.
 * RE-DERIVED for E4 task 3: the interior figure scale (0.3) is gone with the
 * double scale, so the pace is the full WALK_SPEED * DT = 3.4/60 = 0.0566667 m
 * per frame — the goal sits MIN_LEAD = 0.15 m ahead, which is more than one
 * frame of catch-up, so every frame moves a whole step.
 *   The height blend of `tick()` is y += (goal.y - y) * min(1, dt*4) = 1/15
 *   per frame, so 3 - y_n = 3 * (14/15)^n; the arrival test (|dy| < 0.2)
 *   passes at n = 40 (3 * 0.0633 = 0.19; at n = 39 it is 0.203). The hook
 *   sees it one frame later -> the ride ends at frame 41 = 683 ms. This one is
 *   HEIGHT-driven and therefore untouched by the pace change.
 *   ride owns the figure: arrival at ~683 ms, standing ON the holding point
 *                         (x = 0 AT THAT MOMENT — afterwards the key steers
 *                         again and walking on is right), and exactly ONE
 *                         enter-room until then, for `landing`
 *   ride does not own it: never arrives at all, x after 240 frames =
 *                         240 * 0.0566667 = 13.6 m (it was 240 * 3.4 * 0.3/60
 *                         = 4.08 m at the room scale), and the room walk
 *                         switches to `attic`: the attic becomes the nearest
 *                         room past the midpoint x = 1.5, i.e. in the first
 *                         frame with i * 0.0566667 > 1.5 -> i = 27 (x = 1.53)
 *                         at 27 * 1000/60 = 450 ms; `nearestRoomSwitch` holds
 *                         it for ROOM_HOLD = 1.5 s and fires at the first
 *                         frame with now >= 1950 ms, which is i = 117 exactly
 *                         -> a second request at 1950 ms (it was 1483 + 1500
 *                         = 2983 ms)
 *   cooldown honoured:    a `landing` refused 4 s ago -> NO request at all
 *   cooldown ignored:     one request, straight back into the refusal
 *
 * --- frame loop: REMOVED (E4 task 5) --------------------------------------
 * The mirrored hook proved the STEP MACHINE (permission per cell boundary,
 * one request per edge, the entry-room detour). None of that exists any more;
 * see the note at the top. The one pace it also pinned — WALK_SPEED 3.4 m/s,
 * one metre everywhere since k = 1 — is now a property of the walk itself and
 * needs no loop to show it.
 *

 * --- Audio prefs (stage 4, task 2; `client3d/src/game/prefs.ts`) -----------
 * The volume prefs are the one part of the audio layer that is pure maths on a
 * string, so they are checked here. Source of the defaults: the task brief —
 *   master 0.8, music 0.5, ambient 0.6, tts 1.0,
 *   musicOn true, ambientOn true, ttsOn 'auto'
 * `loadPrefs(raw)` takes exactly what `localStorage.getItem('av3d.audio.v1')`
 * returns, i.e. a string or null, and must NEVER throw: the store is user-
 * writable and survives every version of this client, so anything that is not
 * a recognised value falls back to its default FIELD BY FIELD (a single bad
 * slider must not reset the rest).
 * The rules, each pinned below:
 *   - null / unparsable / a JSON non-object (`null`, `[]`, `"x"`, `3`) -> all defaults
 *   - a volume is taken only if it is a finite NUMBER; a numeric STRING is not
 *     a number ("0.3" -> default), NaN/Infinity are not finite -> default
 *   - a taken volume is clamped to [0,1]:  2 -> 1,  -1 -> 0,  0 stays 0
 *     (0 must survive: muting a bus is a legal setting, not a missing value)
 *   - musicOn/ambientOn are taken only if they are real booleans ("yes" -> default)
 *   - ttsOn is taken only from {'auto','on','off'}; anything else -> 'auto'
 *   - `savePrefs` is JSON, so `loadPrefs(savePrefs(p))` returns `p` unchanged
 *     for any already-valid `p` (the round trip the settings UI of task 4 does).
 *
 * --- Boot progress (stage 4, task 3; `client3d/src/game/boot.ts`) ----------
 * The loading screen shows how far the start has come. `startApp` reports four
 * stages, in the order it actually reaches them:
 *
 *     world   world data fetched (locations + worldmap + surface textures)
 *     figures the figure library finished loading
 *     scenes  the scene recipes are primed
 *     tiles   every tile is built and pickable
 *
 * `bootProgress(done)` turns the set of finished stages into what the screen
 * draws. Two rules, and they are deliberately independent of each other:
 *   - percent counts stages, four of them, 25 % each:
 *         percent = 25 * |done ∩ {world, figures, scenes, tiles}|
 *     Anything else in the set is not a stage and contributes nothing — the
 *     bar can never read more than 100 % because a caller mistyped.
 *   - the label names the FIRST stage of the order above that is still
 *     missing, i.e. what the client is working on right now; with all four
 *     done it is 'ready'.
 * So percent and label can disagree about "how far": a set {figures} is 25 %
 * done and still waiting for 'world'. That is correct — the stages complete in
 * their own time and only the first hole says what is being waited FOR.
 * Hand-computed:
 *   {}                          -> 25*0 = 0,   first hole = world    -> 'world'
 *   {world}                     -> 25*1 = 25,  first hole = figures  -> 'figures'
 *   {world,figures}             -> 25*2 = 50,  first hole = scenes   -> 'scenes'
 *   {world,figures,scenes}      -> 25*3 = 75,  first hole = tiles    -> 'tiles'
 *   {world,figures,scenes,tiles}-> 25*4 = 100, no hole               -> 'ready'
 *   {figures}                   -> 25*1 = 25,  first hole = world    -> 'world'
 *   {world,figures,tiles}       -> 25*3 = 75,  first hole = scenes   -> 'scenes'
 *   {world,'bogus'}             -> 25*1 = 25   ('bogus' is not a stage)
 * The label is a STAGE NAME, not a sentence: the React side maps it to a
 * translated string via t(), so the pure module stays language-free. The store
 * on top of it (`reportBootStage` / `setBootNote` / `getBootState` /
 * `subscribeBoot`) publishes only on a REAL change — a stage reported twice
 * and an unchanged note must not wake the subscribers, or the retry loop
 * re-renders the screen once per attempt for nothing. The note is a value
 * (`{kind:'retry',seconds}` / `{kind:'failed'}`) for the same reason as the
 * label: the vanilla side has no t().
 *
 * --- Soundtrack (stage 4, task 5; `client3d/src/game/soundtrack.ts`) -------
 * WHICH music and WHICH ambience play. All four rules are pure lookups or a
 * state function, so they belong here and not in a listening session.
 *
 * `readManifest(raw)` is the door for `GET /assets/audio`
 * ({"music":{"day":[…],"night":[…]},"ambient":{"<terrain>":[…]}}). Same job as
 * `loadPrefs`: whatever arrives, a complete manifest comes out — a missing or
 * wrongly-typed list is an empty list, a non-string entry is dropped, an
 * ambient key with no playable file does not appear at all.
 *
 * `nightForMusic(wasNight, factor)` — the hysteresis on `engine.nightFactor`
 * (0 = full day … 1 = full night; engine.ts: clamp(1 - day*3, 0, 1)). A single
 * threshold would be crossed back and forth at dusk, each crossing costing a
 * 4 s crossfade. So: night above 0.8, day below 0.2, the last decision holds
 * in between, comparisons STRICT. Hand-run as an evening and a morning:
 *   day  , 0.00 -> day    (0 < 0.2)
 *   day  , 0.20 -> day    (exactly the threshold is not "below")
 *   day  , 0.50 -> day    (dead band, keeps)
 *   day  , 0.80 -> day    (exactly the threshold is not "above")
 *   day  , 0.81 -> NIGHT
 *   night, 0.50 -> night  (dead band, keeps)
 *   night, 0.21 -> night
 *   night, 0.19 -> day
 * A ramp 0.19 -> 0.21 -> 0.19 therefore switches ONCE, not three times.
 *
 * `pickMusic` / `pickAmbient` — no substitutions: an empty night bucket is
 * silence at night and never the day list, an unknown terrain is silence and
 * never "the nearest terrain". `pickAmbient` matches the directory name
 * case-insensitively on top of the exact hit (audio/ambient/Forest/ is meant
 * for terrain "forest").
 *
 * `ambientTerrainFor(mode, avatarCell, cameraCell, terrainAt)` — embodied one
 * hears the ground the AVATAR stands on, in the overview the cell the CAMERA
 * looks at. A missing cell is silence, not the other one's terrain. The result
 * is trimmed and lower-cased.
 *
 * `terrainSwitch(state, candidate, now, holdMs)` — the debounce. Walking a
 * corner cell or panning across one must not restart the bed, so a new terrain
 * has to hold AMBIENT_HOLD_MS = 5000 ms; the first terrain of a session is
 * taken at once (a debounce stops flapping, it does not open with silence).
 * Hand-run at holdMs = 5000, starting from {'', '', 0, started:false}:
 *   t=1000 'grass'  -> applied 'grass'      (first one, no hold)
 *   t=2000 'grass'  -> applied 'grass', pending 'grass'
 *   t=3000 'water'  -> applied 'grass', pending 'water', since 3000
 *   t=5000 'water'  -> unchanged (5000-3000 = 2000 < 5000)
 *   t=7999 'water'  -> unchanged (4999 < 5000)
 *   t=8000 'water'  -> applied 'water'      (exactly 5000 counts)
 * and the flap that the hold exists for — grass, one second of water, grass:
 *   t=1000 'grass'  -> applied 'grass'
 *   t=2000 'water'  -> pending 'water', since 2000
 *   t=3000 'grass'  -> candidate == applied: the hold is cancelled
 *   t=9000 'grass'  -> still 'grass' (the water pending never matured)
 * ONLY the very first terrain skips the hold. Once something plays, EVERY
 * change goes through the full 5 s — silence included, and the next terrain
 * after silence is a change like any other:
 *   t=1000 'grass'  -> applied 'grass'         (first, no hold)
 *   t=2000 ''       -> pending '', since 2000  (walking off the map)
 *   t=6999 ''       -> still 'grass'           (4999 < 5000)
 *   t=7000 ''       -> applied ''              (silence took 5 s)
 *   t=8000 'water'  -> pending 'water', since 8000
 *   t=12999 'water' -> still ''                (4999 < 5000)
 *   t=13000 'water' -> applied 'water'         (the next one holds too)
 *
 * --- Voiceover (stage 4, task 6; `client3d/src/game/voiceover.ts`) ---------
 * WHICH lines are read aloud and HOW MANY may wait. Both are pure, so the
 * rules are checkable without a voice.
 *
 * `newSceneLines(prev, cur)` is the ONE new-lines detection of the HUD — the
 * chat auto-show (74a795c) and the speech driver must never disagree about
 * what "somebody said something" means.
 *
 * THE TIMESTAMPS HAVE SECOND RESOLUTION. `record_utterance` stamps with
 * `utc_now_iso()`, whose default is `timespec="seconds"`
 * (app/core/timeutils.py:33) — the demo world shows exactly that
 * ("2026-06-24T22:46:09+00:00"), and the fixtures below use that same shape,
 * never microseconds the server does not send. So "newer than the last ts"
 * cannot be the rule: two characters answering within the same second (the
 * agent loop has a parallel respond lane) would lose the second line — unheard
 * AND without the chat panel coming up for it.
 *
 * The rule is therefore an ANCHOR: the last line already seen is looked up in
 * the new transcript by (ts, speaker, content), and everything after it is
 * new. That survives the rolling window of `/play/scene` too (100 lines: the
 * anchor moves towards the front instead of the count telling a story).
 * Duplicates — the same words from the same speaker in the same second — are
 * counted: seen twice before means the SECOND occurrence is the anchor. Only
 * when the anchor has left the window entirely does the ts comparison stand in.
 *
 * Two cases are deliberately not new and only set the baseline: the first
 * payload after mount (prev = null) and a room change — walking into a room
 * with an older transcript is not somebody speaking.
 *
 * `speakableLines(lines, avatar, narrators)` — what a VOICE may say:
 *   kind          in_room | spoken_self  (whisper_meta carries no content,
 *                 distant_shout is not in the room, 'utterance' is the
 *                 objective god view and never reaches a player payload)
 *   speaker       not the avatar (one's own words are not read back) and not
 *                 the narrator sentinel — 'Storyteller' (the canonical value,
 *                 app/core/perception.py:41) or its localised label, which
 *                 /play/scene substitutes for display (app/routes/play.py:239)
 *   content       non-empty after trimming
 *   meta          display_only / relationship / event_verdict are UI notes,
 *                 not speech
 * The speaker is read exactly as SceneView reads it (`speaker` first, then
 * `meta.speaker`), because that is the name the player sees.
 *
 * `afterOwnLine(lines, avatar)` — the player's own message ends the backlog:
 * everything up to and including the LAST own line in a batch is stale (it was
 * said before the player answered), only what comes after it is still worth
 * hearing.
 *
 * `enqueueSpeech(queue, incoming, max)` — at most MAX_PENDING = 3 lines wait,
 * and it is the OLDEST that go: every waiting line costs a TTS render plus its
 * playing time, so a busy room would otherwise put the client minutes behind
 * the world. 5 lines at once therefore leave [3rd, 4th, 5th].
 *
 * --- Walk height on a location model (finding B8; `game/ground.ts`) --------
 * `tileGroundY` shoots a ray from y = 20 down onto the location's server model
 * and takes the first hit that counts as GROUND. Which one that is used to be
 * a flat `y < 1.2` — the roof filter — and that cap is wrong for area models:
 * the Mondscheinsee mesh spans y −0.80 … +2.69 m, so every hit on the raised
 * shore was rejected and the figure dropped to the tile floor at 0.
 *
 * The accept rule now reads the PAYLOAD (§ B `_building_model`,
 * `app/core/scene_recipe.py`):
 *   display "ground" / "shell_area"  (= map3d.area_model) — the model IS the
 *       ground of the location, relief included. No ceiling at all:
 *       walkCeiling = Infinity.
 *   display "shell" (a building) — keeps the roof protection, but measured
 *       from the model's own declared walkable height:
 *       walkCeiling = walk_y_world + ROOF_CLEARANCE_M (1.2).
 *       A building spec without a walk height falls back to 0 + 1.2 = 1.2,
 *       exactly the old constant.
 * Derived by hand from those two lines:
 *   shell, no walk_y_world:   ceiling 1.2      (0 + 1.2)
 *   shell, walk_y_world 0.06: ceiling 1.26     (BUILDING_BOTTOM_Y 0.06, the
 *                                               offset-free normal case)
 *   shell, walk_y_world 3.2:  ceiling 4.4      (a building on a plinth)
 *   ground / shell_area:      ceiling Infinity
 * The comparison is STRICT (`y < ceiling`), so 1.2 on a plain building is
 * already roof — the unchanged old behaviour.
 *
 * --- ONE FLOOR: the recipe's plate, not the mesh (decision 2026-08-20) -----
 * `recipeFloorAt(plates, lx, lz, ceiling)` — where a figure stands INSIDE a
 * building. The chain everything in a room has to meet (tile metres, § B1/B2
 * addendum of docs/schnittstellen-3d.md):
 *
 *   socle plate 0.045 < level plate 0.08 <= room plate 0.10
 *   prop bottom_y = room plate + PROP_CLEARANCE  = 0.11   (server)
 *   walk height   = room plate + WALK_CLEARANCE_M = 0.11   (here)
 *
 * The rule: the HIGHEST plate whose hull contains the point and whose top is
 * still below the walk ceiling — the same ceiling the ray hits are judged by,
 * because it answers the same question (the highest surface that is not
 * already the next storey). Derived by hand on the Haus-von-Kai payload
 * (living room 8-point hull, kitchen 4-point hull, storey 2.8 m):
 *
 *   plates: level0 top 0.08 (house contour), living room 0.10, kitchen 0.10,
 *           pool 0.00 (outdoor, thickness 0), level1 2.88, bedroom 2.90
 *   ceiling for that building = walk_y_world (−0.22) + 1.2 = 0.98
 *
 *   (0.75, −1.5)  in the living room   -> 0.10   (room beats level plate)
 *   (−2.5, 3.75)  in the kitchen       -> 0.10
 *   (−5.8, −2.0)  the lift alcove — DRAWN INTO the living room -> 0.10
 *                 (that house's contour is exactly its two rooms, so the
 *                  "in the house, in no room -> level plate" case is derived
 *                  on a synthetic 10 m square with one 4 × 3 m room instead:
 *                  (−2, −2) -> 0.10, (2, 2) -> 0.08)
 *   (3.7, 4.6)    in the pool          -> 0.00   (an outdoor room IS a floor)
 *   (6.9, −6.5)   on the plot, outside the house -> null (the mesh answers)
 *   the bedroom's 2.90 is never returned: 2.90 >= 0.98, the next storey.
 *
 * WHAT THIS REPLACED, the regression pin: the same point in the living room
 * used to be the first accepted ray hit on the shell mesh. That mesh carries
 * a 0.240 m terrain pad under its walls and was dialled offset_y −0.30, so
 * its floor sat at 0.06 − 0.30 + 0.240 = 0.000 and the figure stood at
 * 0.000 + 0.01 = 0.010 — 0.090 below the room plate its own props stood on
 * and 0.035 below the tile's grass socle (0.045), which is exactly what the
 * user saw. The plate answer is 0.10 + 0.01 = 0.11 = the props' bottom_y.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/) — the same
// anchor smoke_enter_math.mjs and smoke_ground_math.mjs use.
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC_DIR = join(ROOT, 'client3d/src/game');
/** The pure modules under test. `walk.ts` and `proximity.ts` are import-free;
 *  `clickmove.ts` imports from `walk.ts` and nothing else — no `three`, no
 *  DOM. */
const MODULES = ['walk', 'clickmove', 'proximity', 'roomwalk', 'elevator', 'collide',
  'doors', 'prefs', 'boot', 'soundtrack', 'voiceover', 'polygon', 'enterLocation',
  'perfstats', 'bubble', 'minimap', 'locks', 'placement', 'ground'];

/**
 * Both files are TypeScript and deliberately free of any runtime dependency
 * (that is the point of the "pure" in their docstrings), so a plain transpile
 * is enough — no bundler. `tsx` is not installed; esbuild is, as a Vite
 * dependency. The only fix-up needed is the file extension: the TS sources
 * import `'./walk'`, Node's ESM loader wants `'./walk.mjs'`.
 */
async function loadGameModules() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'walkmath-'));
  try {
    for (const name of MODULES) {
      const source = await readFile(join(SRC_DIR, `${name}.ts`), 'utf8');
      const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
      await writeFile(join(dir, `${name}.mjs`),
        out.code.replace(/(from\s*["'])(\.\/[\w-]+)(["'])/g, '$1$2.mjs$3'), 'utf8');
    }
    const loaded = {};
    for (const name of MODULES) loaded[name] = await import(`file://${join(dir, `${name}.mjs`)}`);
    return loaded;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
function compare(a, b, eps) {
  if (a === null || b === null) return a === b;
  if (typeof b === 'number') return typeof a === 'number' && Math.abs(a - b) <= eps;
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

/** Distance of a point to the nearest wall line — written out here on purpose
 *  instead of importing the module's own helper, so the clearance invariant of
 *  finding I2 is checked against an INDEPENDENT calculation. */
function minWallDistance(p, segments) {
  let best = Infinity;
  for (const s of segments) {
    const dx = s.bx - s.ax;
    const dz = s.bz - s.az;
    const len2 = dx * dx + dz * dz;
    let t = len2 < 1e-12 ? 0 : ((p.x - s.ax) * dx + (p.z - s.az) * dz) / len2;
    t = Math.min(1, Math.max(0, t));
    best = Math.min(best, Math.hypot(p.x - (s.ax + dx * t), p.z - (s.az + dz * t)));
  }
  return best;
}

const CELL = 10;              // must match tiles.ts — see the header
const SQRT_HALF = Math.SQRT1_2;   // 0.7071067811865476

async function main() {
  const { walk, clickmove, proximity, roomwalk, elevator, collide, doors,
    prefs, boot, soundtrack, voiceover, enterLocation, perfstats,
    bubble, minimap, locks, placement, ground } = await loadGameModules();
  const { walkDir, slideBlocked, slopeBlocks, terrainBlocks, terrainPace,
    moveClip, idleClip, groundSink, sinkForState, groundScope, MIN_PACE,
    MOVE_EPS_M } = walk;
  const { planClickWalk, reachedGoal, goalDir, walkStalled,
    GOAL_ARRIVE_M, STALL_STEP_M } = clickmove;
  const { talkTargetNear, TALK_RANGE } = proximity;
  const { nearestRoomSwitch, idleRoomWalk } = roomwalk;
  const { elevatorAt, elevatorLevels, elevatorOptions, elevatorTargetRoom,
    ELEVATOR_RANGE } = elevator;
  const { wallSegments, clampAgainstWalls, bodyRadius, BODY_RADIUS_M,
    DOOR_EASE_M } = collide;
  const { doorMarkers, roomDoor, doorwayBetween } = doors;
  const { loadPrefs, savePrefs, DEFAULT_PREFS, PREFS_KEY, SHOW_ALL_KEY } = prefs;
  const { bootProgress, BOOT_STAGES, reportBootStage, getBootState, setBootNote,
    subscribeBoot } = boot;
  const { readManifest, emptyManifest, nightForMusic, pickMusic, pickAmbient,
    ambientTerrainFor, newTerrainSwitch, terrainSwitch, NIGHT_ON, NIGHT_OFF,
    AMBIENT_HOLD_MS } = soundtrack;
  const { sceneStampOf, newSceneLines, roomChanged, speakerOf, speakableLines,
    afterOwnLine, enqueueSpeech, createVoiceover, NARRATOR_SPEAKERS,
    MAX_PENDING } = voiceover;
  const { minimapLayout, worldToPx, yawToCompassDeg, terrainColor,
    locationsSignature, footprintSignature, MINIMAP_PREF_KEY } = minimap;
  const { placementOf, figureTransition } = placement;
  // The defaults are spelled out here BY HAND, never read from the module —
  // that is the whole point of pinning them (see the header).
  const DEFAULTS = {
    master: 0.8, music: 0.5, ambient: 0.6, tts: 1,
    musicOn: true, ambientOn: true, ttsOn: 'auto',
  };

  // --- the CELL maths: GONE (E4 task 5) ------------------------------------
  // `cellOf`, `stepDirection`, `clampToCell`, `keepAhead`, `splitDiagonal` and
  // `EDGE_MARGIN` were the grid world's step machine, and `planRoute` was the
  // A* click route over the same cells. Both are deleted: the metre world has
  // no cells to round into, no compass step to name and no client A*
  // (plan task 5, "Luftlinie + Wand-Gleiten, KEIN Client-A* in E4"). Their
  // successors are checked below from hand-derived numbers — `slideBlocked`
  // and the click-walk helpers — and the geometry the click route used to
  // approximate is the server's business now (`scripts/smoke_play_pos.py`).

  console.log('walkDir — the engine forward (-sin yaw, 0, -cos yaw)');

  const keys = (...k) => new Set(k);
  check('yaw 0, w', walkDir(keys('w'), 0), { x: 0, z: -1 });
  check('yaw 0, s', walkDir(keys('s'), 0), { x: 0, z: 1 });
  check('yaw 0, d', walkDir(keys('d'), 0), { x: 1, z: 0 });
  check('yaw 0, a', walkDir(keys('a'), 0), { x: -1, z: 0 });
  check('yaw 0, w+d normalised', walkDir(keys('w', 'd'), 0),
    { x: SQRT_HALF, z: -SQRT_HALF });
  check('yaw pi/2, w', walkDir(keys('w'), Math.PI / 2), { x: -1, z: 0 });
  check('yaw pi/2, d', walkDir(keys('d'), Math.PI / 2), { x: 0, z: -1 });
  check('yaw pi/4, w', walkDir(keys('w'), Math.PI / 4), { x: -SQRT_HALF, z: -SQRT_HALF });
  check('arrow keys walk like wasd', walkDir(keys('arrowup'), 0), { x: 0, z: -1 });
  check('no key -> null', walkDir(keys(), 0), null);
  check('w+s cancel -> null', walkDir(keys('w', 's'), 0), null);
  check('a+d cancel -> null', walkDir(keys('a', 'd'), Math.PI / 3), null);
  check('unrelated key -> null', walkDir(keys('q'), 0), null);
  for (const yaw of [0, 0.3, 1.1, -2.4, Math.PI]) {
    const d = walkDir(keys('w', 'a'), yaw);
    check(`yaw ${yaw}: diagonal is unit length`, Math.hypot(d.x, d.z), 1);
  }

  // --- slideBlocked (E4 task 5) --------------------------------------------
  // The successor of the cell clamp. Blocked ground is an AREA now (impassable
  // terrain, a foreign footprint), and a step that would end inside it keeps
  // the part of itself that runs ALONG the boundary:
  //   1. the full step if its target is free;
  //   2. else the LARGER axis component alone (ties go to x);
  //   3. else the smaller one alone;
  //   4. else stand still.
  // Hand-derived against a wall running north-south at x = 5 (blocked: x > 5):
  //   (4,0) -> (6,0):  target blocked. dx = 2, dz = 0 -> x first, still
  //                    blocked; the z fallback has dz = 0 and is skipped
  //                    -> (4,0), the figure stands.
  //   (4,0) -> (6,2):  |dx| = |dz| = 2, the tie goes to x: (6,0) is blocked,
  //                    so the z slide (4,2) stands -> it walks ALONG the wall.
  //   (4,0) -> (4.5,0.5): free, returned unchanged.
  // And against a disc of radius 1 around the origin:
  //   (2,0) -> (0.5,0): |0.5| < 1 -> blocked; dz = 0, so nothing slides
  //                    -> (2,0).
  // The tie rule made visible — blocked is the QUADRANT x > 0 && z > 0:
  //   (-1,-1) -> (1,1): the diagonal target is blocked, x wins the tie and
  //                    (1,-1) is free -> (1,-1).
  console.log('slideBlocked — a blocked step slides along the boundary');
  {
    const wall = (x) => x > 5;
    check('a free step is unchanged',
      slideBlocked({ x: 4, z: 0 }, { x: 4.5, z: 0.5 }, wall), { x: 4.5, z: 0.5 });
    check('straight into the wall: the figure stands',
      slideBlocked({ x: 4, z: 0 }, { x: 6, z: 0 }, wall), { x: 4, z: 0 });
    check('diagonally into the wall: it slides along z',
      slideBlocked({ x: 4, z: 0 }, { x: 6, z: 2 }, wall), { x: 4, z: 2 });
    const disc = (x, z) => Math.hypot(x, z) < 1;
    check('a disc blocks the same way',
      slideBlocked({ x: 2, z: 0 }, { x: 0.5, z: 0 }, disc), { x: 2, z: 0 });
    const quadrant = (x, z) => x > 0 && z > 0;
    check('the tie goes to x, deterministically',
      slideBlocked({ x: -1, z: -1 }, { x: 1, z: 1 }, quadrant), { x: 1, z: -1 });
  }

  // --- terrainBlocks (decision 2026-08-13) ---------------------------------
  // The client's half of the server's terrain gate, spelled out in the header:
  // painted ground stops the figure OUT IN THE WILDERNESS only. The two cases
  // that carry the decision are the same rock point with and without a tile
  // over it — the B1 case (a hall on a rock plateau) and the wilderness wall.
  console.log('terrainBlocks — painted ground judges the wilderness only');
  {
    check('rock INSIDE a footprint is walkable (finding B1)',
      terrainBlocks(false, true), false);
    check('the same rock with no location over it blocks',
      terrainBlocks(false, false), true);
    check('walkable ground never blocks — outside',
      terrainBlocks(true, false), false);
    check('...nor inside', terrainBlocks(true, true), false);
    // And the same pair once THROUGH slideBlocked, because that is how the
    // figure meets it: a rock strip 4 <= x <= 6 with a location standing on
    // its northern half (z >= 0). Walking east at z = 1 crosses it; walking
    // east at z = -1 (no tile) does not.
    const rock = (x) => x >= 4 && x <= 6;
    const tiled = (_x, z) => z >= 0;
    const blocked = (x, z) => terrainBlocks(!rock(x), tiled(x, z));
    check('into the rock UNDER the location: the step goes through',
      slideBlocked({ x: 3, z: 1 }, { x: 5, z: 1 }, blocked), { x: 5, z: 1 });
    check('into the same rock beside it: the figure stays put',
      slideBlocked({ x: 3, z: -1 }, { x: 5, z: -1 }, blocked), { x: 3, z: -1 });
  }

  // --- groundScope (reach decision, round 2 of 2026-08-13) -----------------
  // Most-specific-first: a room answers when there is one, otherwise the
  // footprint, otherwise the wilderness. Hand table in the header.
  console.log('groundScope — how far the terrain rule reaches');
  {
    check('nothing over the point is the wilderness',
      groundScope(null, null), 'wilderness');
    check('an area location is open ground', groundScope(true, null), 'open');
    check('a building footprint is built', groundScope(false, null), 'built');
    check('an interior room beats the area location it stands in',
      groundScope(true, false), 'built');
    check('an outdoor room beats the building it belongs to',
      groundScope(false, true), 'open');
    check('a room without a footprint still answers',
      groundScope(null, true), 'open');
  }

  // --- terrainPace + moveClip (finding 3 + the round-2 reach) --------------
  // The pace and the animation of the TOPMOST terrain count in the wilderness
  // and in every OPEN place; a built place has a floor. Every number is
  // derived in the header.
  console.log('terrainPace — the ground sets the pace as far as the sky');
  {
    check('MIN_PACE is the documented 0.25', MIN_PACE, 0.25);
    check('grass out in the wilderness', terrainPace(1, 'wilderness'), 1);
    check('...and inside an open place', terrainPace(1, 'open'), 1);
    check('water in the wilderness', terrainPace(0.4, 'wilderness'), 0.4);
    check('THE FINDING: the same water in an open place still slows',
      terrainPace(0.4, 'open'), 0.4);
    check('ROUND 2: under a roof it does not — the place has a floor',
      terrainPace(0.4, 'built'), 1);
    check('...not even a FAST ground reaches inside', terrainPace(2, 'built'), 1);
    check('a factor-0 ground in an open place is neutral (never meant to be walked)',
      terrainPace(0, 'open'), 1);
    check('...and out in the open it is clamped, not neutralised',
      terrainPace(0, 'wilderness'), MIN_PACE);
    check('a crawling 0.1 is clamped in an open place as well',
      terrainPace(0.1, 'open'), MIN_PACE);
    check('...and 0.2 outside', terrainPace(0.2, 'wilderness'), MIN_PACE);
    check('the catalog maximum passes through', terrainPace(2, 'wilderness'), 2);
    check('a NaN factor walks at the normal pace', terrainPace(NaN, 'open'), 1);
    check('a negative factor in an open place is the 0 case',
      terrainPace(-1, 'open'), 1);
    check('...and outside it the clamp', terrainPace(-1, 'wilderness'), MIN_PACE);

    // WHERE the pace is applied. The lead keeps the figure over the movement
    // threshold, the STEP carries the pace — hand-derived in the header.
    // WALK_SPEED/MIN_LEAD are pinned here by hand (npcs.ts, main.ts); they
    // are not importable, three.js hangs off both modules.
    const WALK_SPEED = 3.4;
    const MIN_LEAD = 0.15;
    const DT = 1 / 60;
    const leadFor = (reach = Infinity) =>
      Math.min(Math.max(WALK_SPEED * DT, MIN_LEAD), reach);
    const stepFor = (pace, dist) => Math.min(dist, WALK_SPEED * DT * pace);
    check('MOVE_EPS_M is the documented 0.05', MOVE_EPS_M, 0.05);
    check('one frame of walking leads 0.15 m, whatever the ground',
      leadFor(), 0.15);
    check('...which is three times the movement threshold',
      leadFor() > MOVE_EPS_M, true);
    check('the slowest legal ground still steps 0.0141666 m',
      stepFor(terrainPace(0.05, 'wilderness'), leadFor()), 3.4 / 60 * 0.25);
    check('...which the stall detector does NOT call a stall',
      walkStalled({ x: 0, z: 0 },
        { x: stepFor(terrainPace(0.05, 'wilderness'), leadFor()), z: 0 }),
      false);
    // RED COUNTER-PROBE 1: without the clamp the same ground stalls the walk.
    const unclamped = (f, scope) => (scope === 'open' && f <= 0 ? 1 : f);
    check('RED: an unclamped 0.05 steps only 0.00283 m',
      stepFor(unclamped(0.05, 'wilderness'), leadFor()), 3.4 / 60 * 0.05);
    check('...and that IS a stall — the click order would be dropped',
      walkStalled({ x: 0, z: 0 },
        { x: stepFor(unclamped(0.05, 'wilderness'), leadFor()), z: 0 }),
      true);
    // RED COUNTER-PROBE 2: the OLD placement of the pace — on the LEAD. On a
    // 0.25 ground the goal lands 0.0375 m ahead, under MOVE_EPS_M, and the
    // figure stands still with an idle clip instead of swimming.
    const oldLead = (pace) => Math.max(WALK_SPEED * DT, MIN_LEAD) * pace;
    check('RED: a paced LEAD on the slowest ground is 0.0375 m',
      oldLead(terrainPace(0.05, 'wilderness')), 0.0375);
    check('...which npcs.tick does NOT call moving — the figure froze',
      oldLead(terrainPace(0.05, 'wilderness')) > MOVE_EPS_M, false);
    check('...while the lead in force keeps it moving',
      leadFor() > MOVE_EPS_M, true);
    // RED COUNTER-PROBE 3: the pre-finding-3 rule — a footprint neutralised
    // EVERY ground, which is the defect finding 3 names.
    const oldRule = (f, scope) =>
      (scope === 'wilderness' ? Math.max(f, MIN_PACE) : 1);
    check('RED: the old rule walks the lake dry', oldRule(0.4, 'open'), 1);
    check('...while the rule in force wades it', terrainPace(0.4, 'open'), 0.4);
    check('...and both agree out in the wilderness',
      oldRule(0.4, 'wilderness'), terrainPace(0.4, 'wilderness'));
  }

  console.log('moveClip — a ground may name the clip one moves over it with');
  {
    check('water swims', moveClip('swim', false, 'wilderness'), 'swim');
    check('...and there is no sprinting through it',
      moveClip('swim', true, 'wilderness'), 'swim');
    check('...an open place swims too', moveClip('swim', false, 'open'), 'swim');
    check('ROUND 2: a built place names no clip at all',
      moveClip('swim', false, 'built'), 'walk');
    check('...and runs when it is far enough', moveClip('swim', true, 'built'), 'run');
    check('the kind is trimmed', moveClip('  swim  ', false, 'open'), 'swim');
    check('without one, walking is walking', moveClip('', false, 'wilderness'), 'walk');
    check('...and running is running', moveClip('', true, 'wilderness'), 'run');
    check('a blank one is no one', moveClip('   ', true, 'open'), 'run');
  }

  console.log('idleClip — and it may name the standing one as well');
  {
    check('water is trodden, not stood on',
      idleClip('treading-water', 'wilderness'), 'treading-water');
    check('...in an open place too', idleClip('treading-water', 'open'),
      'treading-water');
    check('the kind is trimmed', idleClip('  treading-water  ', 'open'),
      'treading-water');
    check('THE REACH: a built place names no clip at all',
      idleClip('treading-water', 'built'), '');
    check('without one the ground says NOTHING — never an idle of its own',
      idleClip('', 'wilderness'), '');
    check('...and a blank one is no one either',
      idleClip('   ', 'open'), '');
    // RED COUNTER-PROBE: the same rule without the scope gate. It treads
    // water on the tiled floor of a hall standing in the lake.
    const ungated = (a) => (a || '').trim();
    check('RED: without the built gate the hall is trodden too',
      ungated('treading-water'), 'treading-water');
    check('...while the rule in force leaves it alone',
      idleClip('treading-water', 'built'), '');
    check('...and both agree out in the wilderness',
      ungated('treading-water'), idleClip('treading-water', 'wilderness'));

    // The npcs.ts standing branch as a TABLE — the ground wins where it
    // speaks, the standing clip stands where it does not, and the drop gate
    // follows the ground and nothing else.
    const standing = (idleAnim, scope, standingClip) => {
      const groundIdle = idleClip(idleAnim, scope);
      return { kind: groundIdle || standingClip, drop: !!groundIdle };
    };
    check('standing in the lake: the ground wins, and the drop is gated on',
      standing('treading-water', 'wilderness', 'sit'),
      { kind: 'treading-water', drop: true });
    check('...the same lake under a roof: the activity clip stands, no drop',
      standing('treading-water', 'built', 'sit'),
      { kind: 'sit', drop: false });
    check('a ground that names nothing changes nothing',
      standing('', 'wilderness', 'sit'), { kind: 'sit', drop: false });
    check('...not even the plain idle of a figure without an activity',
      standing('', 'open', 'idle'), { kind: 'idle', drop: false });
  }

  console.log('groundSink — how far the ground’s depth reaches');
  {
    check('a lake takes 0.35 m of the moving body',
      groundSink(0.35, 'wilderness'), 0.35);
    check('...an open place is the same water', groundSink(0.35, 'open'), 0.35);
    check('THE REACH: a tiled hall over the lake is a floor',
      groundSink(0.35, 'built'), 0);
    check('a ground without a depth sinks nobody', groundSink(0, 'wilderness'), 0);
    check('...and neither does a negative one', groundSink(-1, 'open'), 0);
    check('...nor a NaN one', groundSink(NaN, 'wilderness'), 0);
    check('the clamp of the catalog travels through untouched',
      groundSink(1.5, 'wilderness'), 1.5);
    // RED COUNTER-PROBE, EXECUTED: the rule before the reach gate existed,
    // written out here — the depth with nothing but the "says something" test.
    const ungated = (sink) => (Number.isFinite(sink) && sink > 0 ? sink : 0);
    check('RED: the ungated rule wades the tiled hall', ungated(0.35), 0.35);
    check('...where the rule in force keeps the floor dry',
      groundSink(0.35, 'built'), 0);
    check('...and outside a built place the two agree',
      groundSink(0.35, 'wilderness'), ungated(0.35));
  }

  console.log('sinkForState — WHICH of the two depths is in force');
  {
    // The water seed of `shared/terrain/types.json`.
    const W = { move: 0.35, idle: 1.3 };
    check('moving, the swimmer’s depth counts',
      sinkForState(true, 'treading-water', W), 0.35);
    check('...even where the ground names no clip at all: a bog swallows '
      + 'ankles under a plain walk', sinkForState(true, '', W), 0.35);
    check('waiting on a ground that names a standing clip, the treader’s does',
      sinkForState(false, 'treading-water', W), 1.3);
    check('THE STANDING GATE: without a ground idle clip nobody is sunk',
      sinkForState(false, '', W), 0);
    check('a ground with no waiting depth sinks nobody while waiting',
      sinkForState(false, 'treading-water', { move: 0.35, idle: 0 }), 0);
    check('...and one with no moving depth nobody while moving',
      sinkForState(true, '', { move: 0, idle: 1.3 }), 0);
    // RED COUNTER-PROBE, EXECUTED: the ONE-depth rule of finding 13, rebuilt.
    // It gives the treader whatever the swimmer got.
    const single = (moving, groundIdle, sink) =>
      (moving || groundIdle ? sink : 0);
    check('RED: with one depth the treader gets the swimmer’s 0.35',
      single(false, 'treading-water', W.move), 0.35);
    check('...where the rule in force gives it the body length it hangs',
      sinkForState(false, 'treading-water', W), 1.3);
    check('...and the moving case is the one place the two agree',
      single(true, 'treading-water', W.move),
      sinkForState(true, 'treading-water', W));
  }

  // --- slopeBlocks (E8 task 1) ---------------------------------------------
  // The height gate as a pure predicate, mirroring `relief.slope_blocks`.
  // Every number is derived in the header; the limits are the world defaults.
  console.log('slopeBlocks — the slope always, the step on top below one metre');
  {
    const STEP = 0.4;
    const SLOPE = 40;
    check('the Mondscheinsee shore: 1.2 m over 0.5 m is a wall',
      slopeBlocks(1.2, 0.5, STEP, SLOPE), true);
    check('the flat beach: 0.3 m over 2 m (8.53 deg) is walked',
      slopeBlocks(0.3, 2, STEP, SLOPE), false);
    check('a 0.3 m step under the cap passes',
      slopeBlocks(0.3, 0.5, STEP, SLOPE), false);
    check('the cap itself passes (strictly greater blocks)',
      slopeBlocks(0.4, 0.5, STEP, SLOPE), false);
    check('a DROP is the same obstacle as a climb',
      slopeBlocks(-1.2, 0.5, STEP, SLOPE), true);
    check('45 deg over 2 m is refused',
      slopeBlocks(2, 2, STEP, SLOPE), true);
    check('38.66 deg over the same 2 m is not',
      slopeBlocks(1.6, 2, STEP, SLOPE), false);
    check('...and the very same rise a hair under the metre is a step',
      slopeBlocks(1.6, 0.99, STEP, SLOPE), true);
    check('one metre exactly is already a slope (26.57 deg)',
      slopeBlocks(0.5, 1, STEP, SLOPE), false);
    check('...0.999 m of it is a 0.5 m step and blocks',
      slopeBlocks(0.5, 0.999, STEP, SLOPE), true);
    check('level ground never blocks, at any distance',
      slopeBlocks(0, 0, STEP, SLOPE), false);
    check('a world with the limits wide open lets the cliff through',
      slopeBlocks(1.2, 0.5, 5, 89), false);
    // THE TWO REGIME CASES (findings F1/F2) — the step limit alone is blind
    // to both, and the client is where the first one bites: it walks in leads
    // of ~0.15 m while the server judges ~1.12 m report steps.
    check('one 0.15 m lead up a 50.19° wall is blocked here too',
      slopeBlocks(0.18, 0.15, STEP, SLOPE), true);
    check('...and crawling 0.4 m per 0.1 m does not climb 75.96° either',
      slopeBlocks(0.4, 0.1, STEP, SLOPE), true);
    // RED COUNTER-PROBE: the either/or form this rule started as. Both cases
    // pass under it, which is exactly why the two limits now hold together.
    const eitherOr = (dh, dist, maxStep, maxSlope) => {
      const rise = Math.abs(dh);
      if (!rise) return false;
      if (dist < 1) return rise > maxStep;
      return Math.atan2(rise, dist) * 180 / Math.PI > maxSlope;
    };
    check('the old form let the 50° lead through',
      eitherOr(0.18, 0.15, STEP, SLOPE), false);
    check('...and the crawl as well',
      eitherOr(0.4, 0.1, STEP, SLOPE), false);
  }

  // --- clickmove (E4 task 5) -----------------------------------------------
  // A click plans ONE point; the walk is the same straight line + slide WASD
  // produces. NO client A* in E4, so there is no route to check any more —
  // what is left is the three answers of `planClickWalk` and the arithmetic
  // the frame hook steers with.
  //   GOAL_ARRIVE_M = 0.2  (above the 0.05 `tick()` needs to see movement)
  //   STALL_STEP_M  = 0.01 (a 60 fps frame walks 3.4/60 = 0.0567 m)
  //   goalDir((0,0) -> (3,4)) = the 3-4-5 triangle: dist 5, unit (0.6, 0.8)
  console.log('clickmove — one goal, no route');
  {
    const free = () => false;
    check('GOAL_ARRIVE_M', GOAL_ARRIVE_M, 0.2);
    check('STALL_STEP_M', STALL_STEP_M, 0.01);
    check('a clear click gives the point itself',
      planClickWalk({ x: 0, z: 0 }, { x: 10, z: 0 }, free), { x: 10, z: 0 });
    check('a blocked point plans nothing (the click falls through)',
      planClickWalk({ x: 0, z: 0 }, { x: 10, z: 0 }, (x) => x > 5), null);
    check('a click where one stands plans nothing either',
      planClickWalk({ x: 0, z: 0 }, { x: 0.1, z: 0 }, free), null);
    check('arrived inside the threshold',
      reachedGoal({ x: 0, z: 0 }, { x: 0.1, z: 0 }), true);
    check('...and not outside it',
      reachedGoal({ x: 0, z: 0 }, { x: 0.3, z: 0 }), false);
    check('the direction and the distance left',
      goalDir({ x: 0, z: 0 }, { x: 3, z: 4 }), { x: 0.6, z: 0.8, dist: 5 });
    check('no direction to a point one is on',
      goalDir({ x: 2, z: 2 }, { x: 2, z: 2 }), null);
    check('half a frame of walking is a stall',
      walkStalled({ x: 0, z: 0 }, { x: 0.005, z: 0 }), true);
    check('a whole frame is not',
      walkStalled({ x: 0, z: 0 }, { x: 0.02, z: 0 }), false);
  }

  console.log('talkTargetNear — who the avatar may address by walking up (task 5)');
  {
    /** avatar/other shorthands: outdoors in location L1 unless said otherwise */
    const me = (x, z, extra = {}) =>
      ({ name: 'Avatar', pos: { x, z }, locId: 'L1', room: null, ...extra });
    const npc = (name, x, z, extra = {}) =>
      ({ name, pos: { x, z }, locId: 'L1', room: null, scale: 1, ...extra });

    check('TALK_RANGE is the documented 2.5 m', TALK_RANGE, 2.5);
    check('2.0 m away -> in range', talkTargetNear(me(0, 0), [npc('Ayla', 2, 0)]), 'Ayla');
    check('3.0 m away -> out of range', talkTargetNear(me(0, 0), [npc('Ayla', 3, 0)]), null);
    check('exactly 2.5 m still counts', talkTargetNear(me(0, 0), [npc('Ayla', 2.5, 0)]), 'Ayla');
    // 3-4-5: (1.5, 2.0) is exactly 2.5 m away, (1.8, 2.4) is 3.0 m.
    check('diagonal 1.5/2.0 = 2.5 m -> in range',
      talkTargetNear(me(0, 0), [npc('Ayla', 1.5, 2)]), 'Ayla');
    check('diagonal 1.8/2.4 = 3.0 m -> out of range',
      talkTargetNear(me(0, 0), [npc('Ayla', 1.8, 2.4)]), null);
    check('nobody around -> null', talkTargetNear(me(0, 0), []), null);

    check('another location, same distance -> null',
      talkTargetNear(me(0, 0), [npc('Ayla', 2, 0, { locId: 'L2' })]), null);
    check('another shown room, 1 m away through the wall -> null',
      talkTargetNear(me(0, 0, { room: 'hall' }),
        [npc('Ayla', 1, 0, { room: 'kitchen' })]), null);
    check('same shown room -> in range',
      talkTargetNear(me(0, 0, { room: 'hall' }),
        [npc('Ayla', 1, 0, { room: 'hall' })]), 'Ayla');
    check('avatar outdoors, NPC drawn inside a room -> null',
      talkTargetNear(me(0, 0), [npc('Ayla', 1, 0, { room: 'hall' })]), null);
    check('avatar inside, NPC drawn outdoors -> null',
      talkTargetNear(me(0, 0, { room: 'hall' }), [npc('Ayla', 1, 0)]), null);

    // Interior scale 0.3: the range shrinks with the figures, 2.5 * 0.3 = 0.75.
    check('scale 0.3: 0.7 m -> in range (radius 0.75)',
      talkTargetNear(me(0, 0, { room: 'hall' }),
        [npc('Ayla', 0.7, 0, { room: 'hall', scale: 0.3 })]), 'Ayla');
    check('scale 0.3: 0.8 m -> out of range',
      talkTargetNear(me(0, 0, { room: 'hall' }),
        [npc('Ayla', 0.8, 0, { room: 'hall', scale: 0.3 })]), null);
    check('scale 0.3: 2.0 m would be in range at scale 1, but is not here',
      talkTargetNear(me(0, 0, { room: 'hall' }),
        [npc('Ayla', 2, 0, { room: 'hall', scale: 0.3 })]), null);

    check('the nearer of two wins',
      talkTargetNear(me(0, 0), [npc('Ayla', 2, 0), npc('Bea', 0, 1.2)]), 'Bea');
    check('order of the list does not matter',
      talkTargetNear(me(0, 0), [npc('Bea', 0, 1.2), npc('Ayla', 2, 0)]), 'Bea');
    check('the nearer one is out of range -> the other one is not taken either',
      talkTargetNear(me(0, 0), [npc('Ayla', 3, 0), npc('Bea', 4, 0)]), null);
    check('equal distance -> the name decides (no 1 Hz flicker)',
      talkTargetNear(me(0, 0), [npc('Bea', 2, 0), npc('Ayla', 0, 2)]), 'Ayla');

    check('the avatar itself is never a candidate',
      talkTargetNear(me(0, 0), [npc('Avatar', 0, 0), npc('Ayla', 2, 0)]), 'Ayla');
    check('alone with itself -> null',
      talkTargetNear(me(0, 0), [npc('Avatar', 0, 0)]), null);
  }

  console.log('nearestRoomSwitch — walking from room to room (task 6)');
  {
    /** hall/kitchen/study on the ground floor, attic one storey up */
    const ROOMS = [
      { id: 'hall', level: 0, center: { x: 0, z: 0 } },
      { id: 'kitchen', level: 0, center: { x: 10, z: 0 } },
      { id: 'study', level: 0, center: { x: 20, z: 0 } },
      { id: 'attic', level: 1, center: { x: 0, z: 0 } },
    ];
    const HOLD = 1.5;   // seconds — the value main.ts hands in

    check('idleRoomWalk is the empty clock', idleRoomWalk(), { candidate: null, sinceMs: 0 });
    check('...and a fresh object each time', idleRoomWalk() !== idleRoomWalk(), true);

    // 1. the hold itself
    {
      let r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('1 m from the kitchen: no switch yet', r.next, 'hall');
      check('...the kitchen is the candidate', r.state.candidate, 'kitchen');
      check('...and the clock started at nowMs', r.state.sinceMs, 0);
      r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0, r.state, 1400, HOLD);
      check('1.4 s held -> still the hall', r.next, 'hall');
      check('...clock keeps running from 0', r.state.sinceMs, 0);
      r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0, r.state, 1600, HOLD);
      check('1.6 s held -> switch to the kitchen', r.next, 'kitchen');
      check('...and the clock re-arms (no repeat before another hold)',
        r.state, { candidate: 'kitchen', sinceMs: 1600 });
      r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0, r.state, 2000, HOLD);
      check('0.4 s after the fire: no second request', r.next, 'hall');
    }
    // exactly the hold counts
    {
      const started = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0,
        idleRoomWalk(), 0, HOLD);
      const r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0, started.state, 1500, HOLD);
      check('exactly 1.5 s switches', r.next, 'kitchen');
    }
    // 2. a changed candidate restarts the clock
    {
      let r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('candidate kitchen at t=0', r.state.candidate, 'kitchen');
      r = nearestRoomSwitch('hall', { x: 19, z: 0 }, ROOMS, 0, r.state, 1000, HOLD);
      check('walked on to the study: new candidate', r.state.candidate, 'study');
      check('...clock restarted', r.state.sinceMs, 1000);
      r = nearestRoomSwitch('hall', { x: 19, z: 0 }, ROOMS, 0, r.state, 2000, HOLD);
      check('2 s since the FIRST candidate is not enough', r.next, 'hall');
      r = nearestRoomSwitch('hall', { x: 19, z: 0 }, ROOMS, 0, r.state, 2500, HOLD);
      check('1.5 s since the second one switches', r.next, 'study');
    }
    // 3. only the current storey is a candidate
    {
      let r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 1, idleRoomWalk(), 0, HOLD);
      check('storey 1: the kitchen 1 m away is not a candidate', r.state.candidate, 'attic');
      r = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 1, r.state, 1600, HOLD);
      check('storey 1: the switch goes to the attic', r.next, 'attic');
      const empty = nearestRoomSwitch('hall', { x: 9, z: 0 }, ROOMS, 2, idleRoomWalk(), 0, HOLD);
      check('storey 2 has no room: current stays', empty.next, 'hall');
      check('...and no clock runs', empty.state, { candidate: null, sinceMs: 0 });
    }
    // 4. a tie never moves anybody
    {
      const a = nearestRoomSwitch('hall', { x: 5, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('exactly between hall and kitchen: current stays', a.next, 'hall');
      check('...and no clock runs', a.state, { candidate: null, sinceMs: 0 });
      const b = nearestRoomSwitch('kitchen', { x: 5, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('same spot, coming from the kitchen: kitchen stays', b.next, 'kitchen');
      const c = nearestRoomSwitch('study', { x: 5, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('tie without the current room: the lower id decides', c.state.candidate, 'hall');
      const d = nearestRoomSwitch(null, { x: 5, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('no current room at all: the lower id decides', d.state.candidate, 'hall');
    }
    // 5. standing in the nearest room: nothing to do, ever
    {
      const r = nearestRoomSwitch('hall', { x: 1, z: 0 }, ROOMS, 0,
        { candidate: 'kitchen', sinceMs: 0 }, 9000, HOLD);
      check('already in the nearest room: no switch', r.next, 'hall');
      check('...and a stale candidate is dropped', r.state, { candidate: null, sinceMs: 0 });
    }
    // 6. coming from outside (the server has not assigned a room yet)
    {
      let r = nearestRoomSwitch(null, { x: 9, z: 0 }, ROOMS, 0, idleRoomWalk(), 0, HOLD);
      check('no room yet: nothing to report before the hold', r.next, null);
      r = nearestRoomSwitch(null, { x: 9, z: 0 }, ROOMS, 0, r.state, 1600, HOLD);
      check('no room yet: the hold still applies', r.next, 'kitchen');
    }
    // 7. the distance is the plain XZ one (3-4-5 against a room off the axis)
    {
      const rooms = [
        { id: 'a', level: 0, center: { x: 0, z: 0 } },
        { id: 'b', level: 0, center: { x: 3, z: 4 } },   // 5 m from the origin
      ];
      const near = nearestRoomSwitch('a', { x: 2, z: 3 }, rooms, 0, idleRoomWalk(), 0, HOLD);
      // (2,3): to a = sqrt(13) = 3.606, to b = sqrt(1+1) = 1.414 -> b
      check('nearest by XZ distance, not by axis', near.state.candidate, 'b');
    }
  }

  console.log('room-walk hook — storey source, lost figure, gated request (task 6)');
  {
    const ROOMS = [
      { id: 'hall', level: 0, center: { x: 0, z: 0 } },
      { id: 'kitchen', level: 0, center: { x: 10, z: 0 } },
      { id: 'attic', level: 1, center: { x: 0, z: 0 } },
    ];
    const HOLD = 1.5;
    /** Frames every 100 ms; `fn(t)` describes the frame at time t. */
    const frames = (untilMs, fn) => {
      const out = [];
      for (let t = 0; t <= untilMs; t += 100) out.push({ nowMs: t, ...fn(t) });
      return out;
    };
    /**
     * The E3-T6 hook of main.ts, mirrored in the same ORDER — deliberately a
     * copy, not an import. `f.stepInFlight` stands for BOTH in-flight gates:
     * `roomRequestInFlight` sits in the very same boolean in main.ts. Scale and
     * fade are not modelled: they are view state and do not reach the switch.
     *
     * `f.roomOf` is what the map `roomOf` holds for the avatar at that frame
     * (the worldmap poll writes it); `f.stepAnswerRoom` is the entry room the
     * answer of `/world/avatar/step` carries. `current` is that value RESOLVED
     * against the rooms of the tile the figure stands on — a room of the
     * location just left does not resolve here.
     */
    function roomWalkSim(list, rooms) {
      let state = idleRoomWalk();
      let requested = null;
      const requests = [];
      let raw = null;                 // roomOf value for the avatar
      for (const f of list) {
        if (f.roomOf !== undefined) raw = f.roomOf;
        // The step answer names the room the server has just put the avatar in
        // — the same truth the next poll repeats, only three seconds earlier.
        if (f.stepAnswerRoom) raw = f.stepAnswerRoom;
        // no figure on the map -> the clock is reset, never carried over
        if (!f.pos) { state = idleRoomWalk(); continue; }
        const current = rooms.some((r) => r.id === raw) ? raw : null;
        // roomOf names a room this tile does not have: the location changed
        // and the truth is still on its way. Adopting the nearest centre now
        // is exactly how the avatar drifts out of its entry room.
        if (!current && raw) { state = idleRoomWalk(); continue; }
        // the storey of the room the FIGURE is in, not the displayed one
        const own = current ? rooms.find((r) => r.id === current)?.level : undefined;
        const level = own ?? f.levelFilter;
        const before = state;
        const out = nearestRoomSwitch(current, f.pos, rooms, level, before, f.nowMs, HOLD);
        const next = out.next;
        if (!next || next === current) { state = out.state; continue; }
        // a due switch that cannot leave keeps the OLD clock
        const gated = !!f.stepInFlight || next === requested;
        state = gated ? before : out.state;
        if (gated) continue;
        requested = next;
        requests.push({ at: f.nowMs, room: next });
      }
      return { requests, state };
    }

    // 1. the storey button is a view state and must not move the avatar
    {
      const run = roomWalkSim(frames(3000, () =>
        ({ pos: { x: 0, z: 0 }, roomOf: 'hall', levelFilter: 1 })), ROOMS);
      check('looking at storey 1 from the hall: no request', run.requests.length, 0);
      // why the source matters: fed the VIEW storey, the same situation switches
      check('...the view storey would have moved the avatar',
        nearestRoomSwitch('hall', { x: 0, z: 0 }, ROOMS, 1,
          { candidate: 'attic', sinceMs: 0 }, 1600, HOLD).next, 'attic');
    }
    // 2. and it must not pull a room set by the HUD chip back down either
    {
      const run = roomWalkSim(frames(3000, () =>
        ({ pos: { x: 0, z: 0 }, roomOf: 'attic', levelFilter: 0 })), ROOMS);
      check('in the attic, view on storey 0: no request', run.requests.length, 0);
    }
    // 3. the ordinary switch still happens, and exactly once
    {
      const run = roomWalkSim(frames(3000, () =>
        ({ pos: { x: 9, z: 0 }, roomOf: 'hall', levelFilter: 0 })), ROOMS);
      check('standing at the kitchen: one request', run.requests.length, 1);
      check('...at 1.5 s', run.requests[0], { at: 1500, room: 'kitchen' });
    }
    // 4. a figure that vanishes and returns starts the hold afresh
    {
      const run = roomWalkSim(frames(3000, (t) => ({
        pos: (t >= 1000 && t < 1200) ? null : { x: 9, z: 0 },
        roomOf: 'hall', levelFilter: 0,
      })), ROOMS);
      check('figure gone and back: still exactly one request', run.requests.length, 1);
      check('...and the hold restarted on its return (1200 + 1500)',
        run.requests[0].at, 2700);
    }
    // 5. a step in flight defers the request without costing a second hold
    {
      const run = roomWalkSim(frames(3000, (t) => ({
        pos: { x: 9, z: 0 }, roomOf: 'hall', levelFilter: 0,
        stepInFlight: t >= 1400 && t <= 1700,
      })), ROOMS);
      check('step in flight: one request, deferred', run.requests.length, 1);
      check('...the first free frame after the line clears', run.requests[0].at, 1800);
    }
    // 6. Just walked into a building (E3): the step answer carries the entry
    // room the server has set. Standing exactly between the two rooms, that
    // knowledge is the whole difference — a tie keeps the room the avatar is
    // in, while a blind hook falls to the lower id and asks the avatar OUT of
    // the entry room it was just placed in (the step back out then earns a
    // `not_at_entry_room` 403 plus the 4 s edge block).
    {
      const HOUSE = [
        { id: 'back', level: 0, center: { x: 10, z: 0 } },
        { id: 'entry', level: 0, center: { x: 0, z: 0 } },
      ];
      const run = roomWalkSim(frames(3000, (t) => ({
        pos: { x: 5, z: 0 }, levelFilter: 0,
        roomOf: t === 0 ? 'porch' : undefined,            // the room just left
        stepAnswerRoom: t === 300 ? 'entry' : undefined,  // the server's answer
      })), HOUSE);
      check('entry room known from the step answer: no request at all',
        run.requests.length, 0);
    }
    // 7. The step answer is slow or lost: until the poll brings the truth,
    // `roomOf` names a room this house does not have — the hook keeps still
    // instead of adopting the nearest centre. Afterwards the ordinary hold
    // runs, and the switch to `back` is right: the figure stands 1 m from it.
    {
      const HOUSE = [
        { id: 'back', level: 0, center: { x: 10, z: 0 } },
        { id: 'entry', level: 0, center: { x: 0, z: 0 } },
      ];
      const run = roomWalkSim(frames(5000, (t) => ({
        pos: { x: 9, z: 0 }, levelFilter: 0,
        roomOf: t === 0 ? 'porch' : t === 3000 ? 'entry' : undefined,
      })), HOUSE);
      check('room of another location: nothing before the poll',
        run.requests.filter((r) => r.at < 3000).length, 0);
      check('after the poll the ordinary hold runs', run.requests.length, 1);
      check('...and it switches to the room walked into', run.requests[0],
        { at: 4500, room: 'back' });
    }
    // 8. Outdoors / a location without a known room: `roomOf` is genuinely
    // empty, and there the old behaviour stands — the guard is limited to
    // "roomOf says a room, this tile does not have it".
    {
      const HOUSE = [
        { id: 'back', level: 0, center: { x: 10, z: 0 } },
        { id: 'entry', level: 0, center: { x: 0, z: 0 } },
      ];
      const run = roomWalkSim(frames(3000, () =>
        ({ pos: { x: 9, z: 0 }, levelFilter: 0 })), HOUSE);
      check('no room known at all: adopts the nearest as before',
        run.requests, [{ at: 1500, room: 'back' }]);
    }
  }

  // --- the frame loop of the STEP MACHINE: GONE (E4 task 5) ---------------
  //
  // Ten cases lived here and every one of them was about a permission the
  // metre world does not ask for: the barred east edge, the exact diagonal
  // into a free corner, "one step request per cell edge" for route and WASD,
  // the impassable-but-known neighbour, the cell without a location, and the
  // entry-room gate the client used to walk before it dared step out. They
  // simulated `main.ts`'s hook against `/world/avatar/step`, which E3 deleted
  // and E4 task 5 replaced with free walking (`POST /play/pos`): the figure
  // walks, reports, and is corrected when the server refuses.
  //
  // What replaced them, and where the numbers now live:
  //  - the WALK itself is geometry, not permission: `slideBlocked` (checked
  //    below, hand-derived) plus `clampAgainstWalls` (unchanged, further
  //    down);
  //  - the GATES are the server's and are checked where they are decided,
  //    with hand-derived metres: `scripts/smoke_play_pos.py`;
  //  - the ENTRY OFFER moved to `client3d/scripts/smoke_enter_math.mjs`
  //    (metre openings, § A1.1, yaw included).
  // Re-deriving them here would mean maintaining a mock of a protocol that
  // does not exist any more.


  // Constants the mirrored loops below share with `main.ts`/`npcs.ts`. They
  // used to be declared by the step-machine block that is gone now.
  const WALK_SPEED = 3.4;      // npcs.ts
  const MIN_LEAD = 0.15;       // main.ts
  const DT = 1 / 60;

  // --- the elevator ride, mirrored (E3 review) ----------------------------
  // A copy of the ORDER in main.ts (ride start -> walk hook -> tick() -> room
  // walk), never an import. Cell boundaries play no part: a ride happens
  // inside ONE interior, which is one cell.
  const RIDE_MS = 4000;        // main.ts ELEVATOR_RIDE_MS
  const RIDE_ARRIVE = 0.2;     // main.ts ELEVATOR_ARRIVE
  const ROOM_HOLD = 1.5;       // main.ts ROOM_HOLD_SECONDS
  /**
   * @param opts.rideOwnsFigure  finding 1: steering is ignored while the ride runs
   * @param opts.honourCooldown  finding 2: `roomRejectedUntil` gates the ride
   * @param opts.rejected        {roomId: untilMs}, judged at the press (t = 0)
   * @param opts.dir             key direction held for the whole run, or null
   */
  function elevatorRideSim(opts) {
    const speed = WALK_SPEED * DT;
    const { rooms, stop } = opts;
    const pos = { x: 0, z: 0, y: 0 };
    const goal = { x: 0, z: 0, y: 0 };          // npc.target
    const requests = [];
    const rejectedUntil = new Map(Object.entries(opts.rejected ?? {}));
    let ride = null;
    let arrivedAt = null;
    let roomWalk = idleRoomWalk();
    let current = opts.current;

    // t = 0: a storey button was pressed (rideElevator).
    const target = elevatorTargetRoom(opts.level, opts.stops, rooms);
    const barred = opts.honourCooldown && (rejectedUntil.get(target) ?? 0) > 0;
    if (target && !barred) {
      requests.push({ at: 0, room: target });
      current = target;                          // the server's own word
      goal.x = stop.x; goal.z = stop.z; goal.y = stop.y;
      if (opts.rideOwnsFigure) ride = { until: RIDE_MS };
      roomWalk = idleRoomWalk();
    }
    for (let i = 1; i <= opts.frames; i++) {
      const now = i * DT * 1000;
      // --- walk hook ---
      if (ride) {
        const arrived = Math.hypot(goal.x - pos.x, goal.z - pos.z) < RIDE_ARRIVE
          && Math.abs(goal.y - pos.y) < RIDE_ARRIVE;
        if (arrived || now > ride.until) {
          // Where the figure stood when the lift handed it back. After that
          // the player steers again, so the END position says nothing about
          // the ride — walking on out of the lift is exactly right.
          if (arrived) arrivedAt = { at: now, x: pos.x, z: pos.z, y: pos.y };
          ride = null;
        }
      }
      if (!ride && opts.dir) {
        // The lead of the walking hook, and its height: the avatar's room is
        // already the target storey, so `storeyY` answers that storey's floor.
        const lead = Math.max(speed, MIN_LEAD);
        goal.x = pos.x + opts.dir.x * lead;
        goal.z = pos.z + opts.dir.z * lead;
        goal.y = opts.steerY ?? 0;
      }
      // --- tick() ---
      const dx = goal.x - pos.x, dz = goal.z - pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist > 0.05) {
        const s = Math.min(dist, speed);
        pos.x += (dx / dist) * s;
        pos.z += (dz / dist) * s;
      }
      pos.y += (goal.y - pos.y) * Math.min(1, DT * 4);
      // --- room walk (T6 hook) ---
      const level = rooms.find((r) => r.id === current)?.level ?? 0;
      const out = nearestRoomSwitch(current, { x: pos.x, z: pos.z }, rooms, level,
        roomWalk, now, ROOM_HOLD);
      roomWalk = out.state;
      if (out.next && out.next !== current) {
        requests.push({ at: now, room: out.next });
        current = out.next;
      }
    }
    return { requests, pos, current, arrivedAt };
  }

  console.log('elevator ride — the ride owns the figure until it arrives (E3 review)');
  {
    const HOUSE = [
      { id: 'hall', level: 0, center: { x: 0, z: 0 } },
      { id: 'landing', level: 1, center: { x: 0, z: 0 } },
      { id: 'attic', level: 1, center: { x: 3, z: 0 } },
    ];
    const STOPS = [{ level: 0, pos: { x: 0, z: 0 } }, { level: 1, pos: { x: 0, z: 0 } }];
    const rideTo1 = (extra) => elevatorRideSim({
      level: 1, stops: STOPS, rooms: HOUSE, stop: { x: 0, z: 0, y: 3 },
      current: 'hall', frames: 240, dir: { x: 1, z: 0 }, steerY: 3,
      honourCooldown: true, ...extra,
    });

    const owned = rideTo1({ rideOwnsFigure: true });
    check('the ride reaches the holding point of the target storey',
      owned.arrivedAt?.at ?? null, 683.33, 20);
    check('...standing ON it, the held key never moved it', owned.arrivedAt?.x, 0, 1e-9);
    check('...at the height of that storey', owned.arrivedAt?.y, 3, 0.2);
    check('...and it was the only room change while it ran',
      owned.requests.filter((r) => r.at <= 683.33).length, 1);
    check('only AFTER the arrival does the key walk the figure on',
      owned.pos.x > 3, true);
    check('...to the room the lift opens into', owned.requests[0], { at: 0, room: 'landing' });

    // RE-DERIVED for E4 task 3 (the interior pace factor is gone, k = 1):
    // every frame the goal sits MIN_LEAD = 0.15 m ahead, which is more than
    // one frame of catch-up, so the figure advances by the full
    // WALK_SPEED·DT = 3.4/60 = 0.0566667 m each of the 240 frames:
    //     240 · 0.0566667 = 13.6 m
    // (it used to be 240 · 3.4 · 0.3/60 = 4.08 m at the room scale 0.3).
    const loose = rideTo1({ rideOwnsFigure: false });
    check('unowned: the held key steers the figure out of the shaft',
      loose.pos.x, 13.6, 0.02);
    check('...so it never arrives at the holding point', loose.arrivedAt ?? null, null);
    check('...and the room walk fires a SECOND enter-room', loose.requests.length, 2);
    check('...into a room nobody chose', loose.requests[1].room, 'attic');
    // The attic (centre x = 3) becomes the nearest room past the halfway line
    // x = 1.5, i.e. in the first frame with i · 0.0566667 > 1.5 → i = 27
    // (x = 1.53), at 27 · 1000/60 = 450 ms. `nearestRoomSwitch` then holds it
    // for ROOM_HOLD = 1.5 s and fires at the first frame with now ≥ 1950 ms,
    // which is i = 117 exactly (117 · 1000/60 = 1950).
    check('...at 450 + 1500 ms', loose.requests[1].at, 1950, 20);

    console.log('elevator ride — a refused room stays refused (E3 review)');
    const cooled = rideTo1({ rideOwnsFigure: true, rejected: { landing: 4000 }, frames: 60 });
    check('the ride does not ask again inside the cooldown', cooled.requests.length, 0);
    check('...and the avatar stays where it was', cooled.current, 'hall');
    const hammered = rideTo1({ rideOwnsFigure: true, rejected: { landing: 4000 },
      honourCooldown: false, frames: 60 });
    check('without the gate every press runs into the same refusal',
      hammered.requests.length, 1);
  }

  // --- walking indoors: the floor, not the shell (E3 acceptance) -----------
  // Finding "Zur Rosinante: you walk on the ROOF". The walk goal took its
  // height from `tileGroundY` (client3d/src/scene/tiles.ts), which raycasts the
  // building/area MESH from above and accepts the first hit below 1.2 WORLD
  // metres. That 1.2 is an assumption about scale, and an area location breaks
  // it. Numbers read off the live payload of Willowbrook, the location "Zur
  // Rosinante" is a room of (GET /play/locations/2b0b384d/scene, world
  // anima-dome): k = 0.21, storey_m = 0.63, and the room's floor plate has
  // top_y = 0.037.
  console.log('walk height — why the shell cannot answer indoors (E3 acceptance)');
  {
    const PLAN_WIDTH_M = 50;      // map3d.plan_width_m of the location
    const EXTENT_M = 10.5;        // map3d.extent_m — its size in world metres
    const STOREY_REAL_M = 3.0;    // map3d.storey_height_m
    const GROUND_SKIN_MAX = 1.2;  // tiles.ts tileGroundY: `h.point.y < 1.2`
    const FLOOR_Y = 0.037;        // plate top_y of the room "Zur Rosinante"
    const k = EXTENT_M / PLAN_WIDTH_M;
    check('world metres per real metre', k, 0.21);
    check('...so one storey is 0.63 world metres', STOREY_REAL_M * k, 0.63);
    // A one-storey house of the village: floor 0.037 + 0.63 = 0.667 m ridge.
    const roofY = FLOOR_Y + STOREY_REAL_M * k;
    check('a village roof stands at 0.667 m', roofY, 0.667, 1e-9);
    check('...which is INSIDE the window the ground skin accepts',
      roofY < GROUND_SKIN_MAX, true);
    check('...and 0.63 m — a full storey — above the floor of the room',
      roofY - FLOOR_Y, 0.63, 1e-9);
    // The only scale at which the skin would have answered correctly here is
    // one where a storey does not fit under 1.2 m, i.e. k > 0.4.
    check('the skin only works while a storey does not fit under it',
      STOREY_REAL_M * 0.4 < GROUND_SKIN_MAX, false);
  }

  // --- which height source the walking hook asks (E3 review, I3) -----------
  // `roomFloorY` (main.ts) replaced the ground skin for the room the avatar is
  // in. That is right INSIDE a building — the skin guesses at scale (see the
  // block above) — and wrong for an always-visible outdoor zone: the payload
  // gives such a zone ONE height (its `overlay.y`), while the skin samples the
  // model under the figure's feet and follows the ground. Willowbrook runs at
  // k = 0.21, so its whole terrain sits inside the skin's 1.2 m window and the
  // skin does work there; a village square on a slope would otherwise be flat
  // and the figure would float downhill and sink uphill.
  //
  // Mirror of the rule, the two variants side by side: 'room-always' is what
  // 0f3b540 shipped, 'building-only' the corrected one.
  const heightSource = (tile, variant) => {
    if (variant === 'building-only') {
      if (!tile.isBuilding) return 'skin';
      if (!tile.room || tile.alwaysVisible) return 'skin';
      return 'room';
    }
    return tile.room ? 'room' : 'skin';   // 0f3b540
  };
  console.log('walk height — the skin keeps the outdoor slope (E3 review)');
  {
    // Willowbrook: an area location, so `passable: false` -> isBuilding, with
    // the indoor room "Zur Rosinante" (floor plate 0.037) and the always-
    // visible zone "Der Dorfplatz". Skin values are two points of the model
    // surface on a slope.
    const inn = { isBuilding: true, room: 'e59ab388', alwaysVisible: false };
    const square = { isBuilding: true, room: 'a97a55f0', alwaysVisible: true };
    const street = { isBuilding: false, room: 'zone', alwaysVisible: false };
    const outdoors = { isBuilding: true, room: null, alwaysVisible: false };

    check('inside a building room: the room floor', heightSource(inn, 'building-only'), 'room');
    check('always-visible outdoor zone: the ground skin',
      heightSource(square, 'building-only'), 'skin');
    check('...which 0f3b540 flattened to one height',
      heightSource(square, 'room-always'), 'room');
    check('passable ground with zones: the ground skin',
      heightSource(street, 'building-only'), 'skin');
    check('no room resolved: the ground skin unchanged',
      heightSource(outdoors, 'building-only'), 'skin');
    // The size of the error the flattening causes: the zone's one height
    // against the sampled surface. At k = 0.21 a 3 m rise of the plan is
    // 0.63 m of world height — half a village square.
    const zoneY = 0.0;
    const skinUphill = 3.0 * (10.5 / 50);
    check('a 3 m rise of the plan is 0.63 m the figure would sink into',
      skinUphill - zoneY, 0.63, 1e-9);
  }

  // --- the storey following is edge-triggered (E3 review, I2) --------------
  // `followAvatarStorey` applies the avatar's storey when THAT changes, so a
  // storey picked by hand survives while the avatar stays put. The memory must
  // not outlive the mode, though: in the overview the in-world switch is the
  // only authority, and a pick there meets a memory that already holds the
  // avatar's storey — the edge never fires again and the view stays on the
  // wrong floor.
  /** @param resetOnExit the fix: leaving the mode clears the memory */
  function storeyFollowSim(steps, resetOnExit) {
    const memory = new Map();
    let filter = 0;
    for (const s of steps) {
      if (s.mode === 'overview') {
        if (resetOnExit) memory.clear();
        if (s.pick !== undefined) filter = s.pick;   // the in-world switch
        continue;
      }
      if (s.pick !== undefined) filter = s.pick;
      if (s.level === undefined) continue;
      if (memory.get('tile') === s.level) continue;  // edge only
      memory.set('tile', s.level);
      filter = s.level;
    }
    return filter;
  }
  console.log('storey follow — the edge memory does not outlive the mode (E3 review)');
  {
    // Embodied on storey 1 -> leave -> pick the ground floor by hand -> come
    // back with the avatar still upstairs.
    const trip = [
      { mode: 'embodied', level: 1 },
      { mode: 'overview', pick: 0 },
      { mode: 'embodied', level: 1 },
    ];
    check('with the reset the view returns to the avatar', storeyFollowSim(trip, true), 1);
    check('without it the view stays on the storey nobody is on',
      storeyFollowSim(trip, false), 0);
    // What the edge is FOR stays intact: a manual pick inside the mode holds
    // while the avatar does not change storey.
    const look = [
      { mode: 'embodied', level: 0 },
      { mode: 'embodied', pick: 1 },
      { mode: 'embodied', level: 0 },
    ];
    check('a manual pick survives while the avatar stays put',
      storeyFollowSim(look, true), 1);
    // …and the avatar wins again the moment it moves.
    check('and the avatar wins again as soon as it changes storey',
      storeyFollowSim([...look, { mode: 'embodied', level: 1 },
        { mode: 'embodied', level: 0 }], true), 0);
  }

  // --- Wall collision indoors (E3 acceptance: "walks through walls") -------
  //
  // Source of the geometry: the SCENE PAYLOAD, docs/schnittstellen-3d.md § B1.
  // `walls: [{ level, from:[x,z], to:[x,z], base_y, height, thickness, glass?,
  // room_id?, outward_normal }]` — finished primitives in WORLD METRES, and
  // the server has ALREADY split every wall around its openings
  // (`app/core/scene_recipe.py::_room_walls`): a door or passage leaves a
  // full-height GAP (no entry at all), a window keeps a sill piece below, a
  // head piece above and a glass pane in between — three entries that all
  // span the opening. So "doors pass, windows block" needs no opening lookup
  // at all: whatever is left in `walls` blocks, the gaps are the doors.
  //
  // Hand-derived mini payload — a 4x4 m square room, k = 1, clockwise hull
  //   (0,0) -> (4,0) -> (4,4) -> (0,4) -> close
  // edge 1 = (4,0)->(4,4) carries a WINDOW  at = 0.5, width_m = 1.0
  // edge 3 = (0,4)->(0,0) carries a DOOR    at = 0.5, width_m = 1.0
  // The server maths for both (scene_recipe `_room_walls`):
  //   length = 4, half = width_m * k / 2 = 0.5, centre = at * length = 2
  //   -> opening span along the edge = [1.5, 2.5]
  //   -> solid pieces = _subtract([(0,4)], [(1.5,2.5)]) = [(0,1.5), (2.5,4)]
  // Edge 1 runs +z from (4,0), so its span is z in [1.5,2.5]; edge 3 runs -z
  // from (0,4), so ITS span is z in [4-2.5, 4-1.5] = [1.5,2.5] as well.
  // The window additionally emits sill/head/glass over exactly that span.
  const room = {
    k: 1,
    walls: [
      { level: 0, from: [0, 0], to: [4, 0] },                     // edge 0
      { level: 0, from: [4, 0], to: [4, 1.5] },                   // edge 1 solid
      { level: 0, from: [4, 2.5], to: [4, 4] },                   // edge 1 solid
      { level: 0, from: [4, 1.5], to: [4, 2.5], base_y: 0 },      // window sill
      { level: 0, from: [4, 1.5], to: [4, 2.5], base_y: 2.1 },    // window head
      { level: 0, from: [4, 1.5], to: [4, 2.5], glass: true },    // window glass
      { level: 0, from: [4, 4], to: [0, 4] },                     // edge 2
      { level: 0, from: [0, 4], to: [0, 2.5] },                   // edge 3 solid
      { level: 0, from: [0, 1.5], to: [0, 0] },                   // edge 3 solid
      { level: 1, from: [0, 0], to: [0, 4] },                     // upper storey
    ],
  };
  //
  // DOOR EASE. The gap in `walls` is exactly as wide as the drawn door, and a
  // figure of radius r would have to thread r of clearance on each side of it
  // — one brushed frame and it sticks. So every wall end that is NOT joined to
  // another wall end (tolerance 0.01 m, the payload rounds to 4 decimals) is
  // pulled back by DOOR_EASE_M * k = 0.12 m. Corners and the window's own
  // sill/head/glass joints share their endpoints exactly, so ONLY the two door
  // cheeks move:
  //   (0,4)->(0,2.5)  free end (0,2.5)  ->  (0,4)   -> (0,2.62)
  //   (0,1.5)->(0,0)  free end (0,1.5)  ->  (0,1.38)-> (0,0)
  // The 1.00 m door therefore collides as a 1.24 m gap.
  console.log('\nwallSegments — level filter, door gaps, window still blocks');
  check('BODY_RADIUS_M is the figure-metre half width', BODY_RADIUS_M, 0.25);
  check('DOOR_EASE_M', DOOR_EASE_M, 0.12);
  check('bodyRadius scales with k (Willowbrook k = 0.21)', bodyRadius(0.21), 0.0525);
  check('bodyRadius(1) = BODY_RADIUS_M', bodyRadius(1), 0.25);
  const segs0 = wallSegments(room, 0);
  check('ground floor keeps all nine level-0 entries', segs0.length, 9);
  check('upper storey is ONE segment', wallSegments(room, 1).length, 1);
  // It stands ALONE on its storey, so BOTH of its ends count as free and both
  // are pulled back by the ease — the rule has no notion of "this end is a
  // corner", only "another wall ends here too". Harmless in a real payload
  // (every corner is shared) and visible here on purpose.
  check('upper storey segment is the level-1 wall, both ends eased',
    wallSegments(room, 1)[0], { ax: 0, az: 0.12, bx: 0, bz: 3.88 }, 1e-9);
  check('a storey nobody built has no segments', wallSegments(room, 2).length, 0);
  // The two door cheeks, pulled back by the ease; everything else untouched.
  check('door cheek from the north corner ends 0.12 short', segs0[7],
    { ax: 0, az: 4, bx: 0, bz: 2.62 }, 1e-9);
  check('door cheek from the south corner starts 0.12 later', segs0[8],
    { ax: 0, az: 1.38, bx: 0, bz: 0 }, 1e-9);
  check('a corner-joined wall keeps its full length', segs0[0],
    { ax: 0, az: 0, bx: 4, bz: 0 });
  check('the window sill keeps its full length (joined to both solids)',
    segs0[3], { ax: 4, az: 1.5, bx: 4, bz: 2.5 });

  console.log('\nclampAgainstWalls — a wall blocks, a door does not');
  const R = 0.25;
  // Bare segments (no payload, no ease) so the maths stays hand-checkable:
  // ONE wall on the z axis, x = 0, from z = 0 to z = 4.
  const wall = [{ ax: 0, az: 0, bx: 0, bz: 4 }];
  //  head-on: from (1,1) to (-1,1) crosses the wall at (0,1), 1 in [0,4].
  //  The move is projected onto the wall direction (0,1): dot((-2,0),(0,1)) = 0
  //  -> the goal collapses onto the position. Nothing is pushed out afterwards
  //  (distance from (1,1) to the wall is 1 >= 0.25).
  check('head-on into a wall stands still',
    clampAgainstWalls({ x: 1, z: 1 }, { x: -1, z: 1 }, wall, R), { x: 1, z: 1 });
  //  oblique: delta = (-2,1); dot((-2,1),(0,1)) = 1 -> goal = (1,1) + (0,1)*1.
  //  The parallel component SURVIVES: the figure slides along the wall.
  check('an oblique run slides along the wall',
    clampAgainstWalls({ x: 1, z: 1 }, { x: -1, z: 2 }, wall, R), { x: 1, z: 2 });
  //  the crossing test is bounded by the segment: past its end (z = 4) the
  //  same head-on move is free, only the push-out around the end cap applies.
  //  from (1,5) to (-1,5): closest point on the segment is (0,4),
  //  |(-1,5)-(0,4)| = sqrt(2) = 1.4142 >= 0.25 -> untouched.
  check('beyond the end of the wall nothing blocks',
    clampAgainstWalls({ x: 1, z: 5 }, { x: -1, z: 5 }, wall, R), { x: -1, z: 5 });
  //  radius: from (1,1) to (0.1,3) never reaches x = 0, so nothing is crossed,
  //  but the goal lies 0.1 m from the wall. Push out along (1,0) to exactly r.
  check('a grazing pass is pushed out to the body radius',
    clampAgainstWalls({ x: 1, z: 1 }, { x: 0.1, z: 3 }, wall, R), { x: 0.25, z: 3 });
  check('and with a smaller radius it is left alone',
    clampAgainstWalls({ x: 1, z: 1 }, { x: 0.1, z: 3 }, wall, 0.05),
    { x: 0.1, z: 3 });
  //  a door gap: the same wall split at z = 1.5 / 2.5. Walking through z = 2
  //  crosses neither piece, and the nearest end cap is
  //  |(-1,2)-(0,1.5)| = sqrt(1 + 0.25) = 1.118 >= 0.25 -> straight through.
  const gap = [{ ax: 0, az: 0, bx: 0, bz: 1.5 }, { ax: 0, az: 2.5, bx: 0, bz: 4 }];
  check('through the door gap the goal survives untouched',
    clampAgainstWalls({ x: 1, z: 2 }, { x: -1, z: 2 }, gap, R), { x: -1, z: 2 });
  //  ... and the pieces beside it still block.
  check('beside the door the wall still holds',
    clampAgainstWalls({ x: 1, z: 1 }, { x: -1, z: 1 }, gap, R), { x: 1, z: 1 });

  console.log('\nclampAgainstWalls — against the mini payload');
  //  Through the DOOR on edge 3 (gap z in [1.38, 2.62] after the ease):
  //  a walk west at z = 2 crosses nothing, nearest cheek end is
  //  |(-2,2)-(0,2.62)| = sqrt(4 + 0.3844) = 2.094 >= 0.25.
  check('the avatar walks out through the door',
    clampAgainstWalls({ x: 2, z: 2 }, { x: -2, z: 2 }, segs0, R), { x: -2, z: 2 });
  //  Through the WINDOW on edge 1 (same z, opposite side): the sill/head/glass
  //  entries span it, the move is projected onto their direction (0,1) and
  //  dot((4,0),(0,1)) = 0 -> stands still.
  check('the window blocks like any wall',
    clampAgainstWalls({ x: 2, z: 2 }, { x: 6, z: 2 }, segs0, R), { x: 2, z: 2 });
  //  Straight through the north wall (edge 0) — no opening there at all.
  check('a wall without an opening blocks',
    clampAgainstWalls({ x: 2, z: 2 }, { x: 2, z: -2 }, segs0, R), { x: 2, z: 2 });
  //  Diagonally at the door: delta = (-4,-1) still crosses nothing (it passes
  //  x = 0 at z = 2 - 1*(2/4) = 1.5, inside the eased gap [1.38, 2.62]) —
  //  BUT the cheek end (0,1.38) is 0.6 m away in z at x = -2, so no push
  //  either: |(-2,1)-(0,1.38)| = sqrt(4 + 0.1444) = 2.036 >= 0.25.
  check('an oblique run through the door passes too',
    clampAgainstWalls({ x: 2, z: 2 }, { x: -2, z: 1 }, segs0, R), { x: -2, z: 1 });
  //  Without the ease the same run would still pass; what the ease buys is the
  //  cheek CLEARANCE. Aiming at the untrimmed cheek corner (0,1.5): without
  //  the ease the goal (-0.1, 1.55) sits 0.1 m from the wall end and gets
  //  pushed; with the ease the cheek ends at (0,1.38) and
  //  |(-0.1,1.55)-(0,1.38)| = sqrt(0.01 + 0.0289) = 0.1972 -> still inside r,
  //  so it is pushed out, but from a point 0.12 m FARTHER from the doorway.
  //  The check that matters for the player: a walk hugging the eased cheek at
  //  z = 1.45 gets through instead of being stopped by the frame.
  check('hugging the door cheek gets through',
    clampAgainstWalls({ x: 2, z: 1.45 }, { x: -2, z: 1.45 }, segs0, R),
    { x: -2, z: 1.45 });
  //  Same run against the UNEASED gap: the cheek ends at (0,1.5), the goal
  //  passes 0.05 m from it -> pushed out along (-2-0, 1.45-1.5)/0.05... the
  //  point is only that it is NOT left alone. Compare the two.
  const tight = [{ ax: 0, az: 0, bx: 0, bz: 1.5 }, { ax: 0, az: 2.62, bx: 0, bz: 4 }];
  const hug = clampAgainstWalls({ x: 2, z: 1.45 }, { x: -2, z: 1.45 }, tight, R);
  check('without the ease the same run is clamped', hug.x > -2, true);
  //  Storey filter at the clamp: the upper storey wall runs (0,0)-(0,4) with
  //  NO door, so the same walk west is blocked there.
  check('the storey above has no door and blocks',
    clampAgainstWalls({ x: 2, z: 2 }, { x: -2, z: 2 }, wallSegments(room, 1), R),
    { x: 2, z: 2 });
  check('with no segments at all the goal is returned unchanged',
    clampAgainstWalls({ x: 2, z: 2 }, { x: -2, z: 2 }, [], R), { x: -2, z: 2 });

  // --- Review findings C1 / I2 / I3 ----------------------------------------
  //
  // C1 — THE PAYLOAD IS TILE-LOCAL. `_w(frac, extent)` in scene_recipe.py
  // yields world METRES around the TILE CENTRE, not absolute world position:
  // every other consumer adds `tile.center` (sceneRecipe.ts does it for room
  // rects, room centres, overlay zones, `outlineWalls` mids, elevator stops,
  // doorways and markers). The figure position the clamp is fed comes from
  // `npcs.positionOf()` and IS absolute. Measured on "Haus von Kai": the
  // nearest segment sat 53.41 m away, so the clamp did nothing in 9 of 9
  // buildings — only a location on grid (0,0) would ever have blocked. The
  // mini payload above hid it because it sits at the origin.
  //
  // Tile (4,2) -> centre (4*CELL, 2*CELL) = (40, 20). Every hand-derived
  // number of the mini payload simply shifts by it.
  console.log('\nwallSegments — the payload is tile-local, the figure is not (C1)');
  const at40 = wallSegments(room, 0, { x: 40, z: 20 });
  check('the north wall lands on the tile', at40[0],
    { ax: 40, az: 20, bx: 44, bz: 20 });
  check('the eased door cheek lands with it', at40[7],
    { ax: 40, az: 24, bx: 40, bz: 22.62 }, 1e-9);
  check('and the other cheek too', at40[8],
    { ax: 40, az: 21.38, bx: 40, bz: 20 }, 1e-9);
  check('the raw payload really is NOT world-absolute', segs0[0],
    { ax: 0, az: 0, bx: 4, bz: 0 });
  // The proof that the offset is what makes it work: the same world move.
  check('offset segments block the world move',
    clampAgainstWalls({ x: 42, z: 22 }, { x: 42, z: 18 }, at40, R),
    { x: 42, z: 22 });
  check('unoffset segments let it walk straight through (the bug)',
    clampAgainstWalls({ x: 42, z: 22 }, { x: 42, z: 18 }, segs0, R),
    { x: 42, z: 18 });
  check('and the door still works in world coordinates',
    clampAgainstWalls({ x: 42, z: 22 }, { x: 38, z: 22 }, at40, R),
    { x: 38, z: 22 });

  // I3 — the ORIGIN of the move may sit on the wall. Nothing walks a figure
  // there, but `snapPlayerTo` (the put-back after a refused step), a teleport
  // and a party pull all place it wall-blind. A point exactly on the line
  // makes EVERY from->goal a crossing, so the figure would be frozen in place
  // in all directions, for good. The origin is therefore pushed clear first;
  // when it is exactly ON the line, no side information exists and it takes
  // the side the player is heading for — the only sane pick, and unreachable
  // by walking (the goal never gets closer than the radius).
  console.log('\nclampAgainstWalls — an origin on the wall does not freeze (I3)');
  check('standing on the wall, walking east: the move happens',
    clampAgainstWalls({ x: 0, z: 2 }, { x: 1, z: 2 }, wall, R), { x: 1, z: 2 });
  check('standing on the wall, walking west: it works the other way too',
    clampAgainstWalls({ x: 0, z: 2 }, { x: -1, z: 2 }, wall, R), { x: -1, z: 2 });
  // Inside the capsule but off the line: the side IS known, so the figure is
  // pushed out to the radius while it walks along.
  check('too close to the wall, walking along it: pushed out to r',
    clampAgainstWalls({ x: 0.05, z: 2 }, { x: 0.05, z: 3 }, wall, R),
    { x: 0.25, z: 3 });

  // I2 — the push-out is an iteration, and between two walls closer together
  // than 2r it cannot converge: it ping-pongs and the loop simply ends
  // somewhere, measured as low as 0.002 m at r = 0.109 — the figure ends up
  // standing IN the wall. The guarantee that can actually be kept is
  // relative: the result is never closer to a wall than the figure already
  // was (capped at r). Anything that fails it is dropped in favour of the
  // slide, and that in turn in favour of standing still — so a corridor
  // narrower than the body stays walkable instead of freezing.
  //   corridor: walls at x = 0 and x = 0.3, r = 0.25, so 2r = 0.5 > 0.3.
  console.log('\nclampAgainstWalls — never worse off than before (I2)');
  const corridor = [{ ax: 0, az: 0, bx: 0, bz: 4 }, { ax: 0.3, az: 0, bx: 0.3, bz: 4 }];
  const mid = { x: 0.15, z: 2 };
  check('down the middle of a too-narrow corridor: keeps walking',
    clampAgainstWalls(mid, { x: 0.15, z: 3 }, corridor, R), { x: 0.15, z: 3 });
  check('and its clearance is not eaten by the push-out',
    minWallDistance(clampAgainstWalls(mid, { x: 0.15, z: 3 }, corridor, R), corridor),
    0.15, 1e-9);
  check('out through the corridor wall: blocked, still in the middle',
    clampAgainstWalls(mid, { x: 0.5, z: 2 }, corridor, R), { x: 0.15, z: 2 });
  // The invariant itself, over every case of this section.
  const invariant = [
    [{ x: 1, z: 1 }, { x: -1, z: 1 }, wall],
    [{ x: 1, z: 1 }, { x: 0.1, z: 3 }, wall],
    [{ x: 0, z: 2 }, { x: 1, z: 2 }, wall],
    [{ x: 0.05, z: 2 }, { x: 0.05, z: 3 }, wall],
    [mid, { x: 0.15, z: 3 }, corridor],
    [mid, { x: 0.5, z: 2 }, corridor],
    [{ x: 42, z: 22 }, { x: 38, z: 22 }, at40],
    [{ x: 42, z: 22 }, { x: 42, z: 18 }, at40],
  ];
  const violations = invariant.filter(([f, t, segs]) => {
    const need = Math.min(R, minWallDistance(f, segs));
    return minWallDistance(clampAgainstWalls(f, t, segs, R), segs) < need - 1e-6;
  });
  check('no case ends closer to a wall than it started', violations.length, 0);

  // --- Review finding: the push-out must not cross to the far side ---------
  //
  // The crossing tests run from `base` (the pushed-clear origin), but the
  // FIGURE stands at `from` — and the step from `from` to `base` was only ever
  // checked by distance. In a niche that the push-out cannot resolve, `base`
  // therefore lands on the far side of a wall and the figure is teleported
  // through it. Measured at the Bernstein Academy: a room hull and the
  // building contour 0.089 m apart at 2r = 0.218 m, 2427 of 286950 capsule
  // starts (0.85 %) came out on the wrong side — the figure walking IN gets
  // thrown out of the building. Unreachable by walking (0 of 188050 legal
  // starts), reachable after a server-side put-back into the niche
  // (authority snap to tile.center, the 403 put-back).
  //
  //   walls at x = 0 (contour) and x = 0.089 (room hull), r = 0.109, the room
  //   is x > 0.089. The figure sits in the niche at x = 0.0445 (dead centre,
  //   0.0445 from either wall). The push-out cannot settle: wall 1 shoves it
  //   to x = 0.109, which is now 0.02 INSIDE wall 2's capsule, so wall 2
  //   shoves it on to x = 0.089 + 0.109 = 0.198 — past the hull, in the room.
  console.log('\nclampAgainstWalls — the push-out stays on the figure\'s side');
  const niche = [{ ax: 0, az: 0, bx: 0, bz: 4 }, { ax: 0.089, az: 0, bx: 0.089, bz: 4 }];
  const NR = 0.109;
  const inNiche = { x: 0.0445, z: 2 };
  check('walking in: the figure is not shoved through the hull',
    clampAgainstWalls(inNiche, { x: 2, z: 2 }, niche, NR), { x: 0.0445, z: 2 });
  check('walking out: it is not shoved through either',
    clampAgainstWalls(inNiche, { x: -2, z: 2 }, niche, NR), { x: 0.0445, z: 2 });
  check('and it never ends up past the hull wall',
    clampAgainstWalls(inNiche, { x: 2, z: 2 }, niche, NR).x <= 0.089, true);
  // The exemption that keeps this from freezing the on-the-wall case (I3):
  // contact AT the figure's own position is not a crossing — it is where it
  // stands. Only contact BEYOND it counts.
  check('a figure standing on the wall still gets off it',
    clampAgainstWalls({ x: 0, z: 2 }, { x: 1, z: 2 }, wall, R), { x: 1, z: 2 });
  check('and walking ALONG the wall line is still not free',
    clampAgainstWalls({ x: 1, z: 1 }, { x: -1, z: 1 }, wall, R), { x: 1, z: 1 });

  // --- Doorways (E3 acceptance "you cannot see the doors", rehung in B3) ---
  //
  // The server renders a door as a GAP in the wall segments, and a gap alone
  // does not read as a door — so `client3d/src/game/doors.ts` says where the
  // walk-through gaps are and main.ts lays a threshold quad into each.
  //
  // Until B3 this module DERIVED them: it recomputed every room opening
  // (edge clamp, `width_m × k`) and measured the building entrance back out
  // of the contour pieces (two colinear stretches exactly 0.8 m apart), for
  // which it carried six constants of its own. It now READS `doorways[]`
  // (plan-betreten-und-tueren.md § 4.1), the finished primitive the server
  // already cut its walls and its hull from. The consumer rule of § 4.1 is
  // "recompute NOTHING", so every number below is simply the payload's:
  //
  //   mid    = at_world + origin      (origin = tile centre; the payload is
  //                                    tile-local, the scene is not)
  //   along  = along                  (unit direction of the wall)
  //   width  = width_m                (CLEAR width, already clamped)
  //   baseY  = base_y                 (foot of the wall the gap belongs to)
  //   roomIds= rooms                  (2 = party wall, 1 = door to outside)
  //
  // The fixture below carries rooms/openings and contour walls that CONTRADICT
  // its doorways (a window, a room opening nobody cut, two contour pieces
  // exactly 0.8 m apart). None of it may show up: if a single marker came from
  // there, the derivation is back.
  //
  //   d0  party wall r1|r2, mid (2,0),  along (0,1),  width 1,   base 0.10
  //   d1  r1 to the outside, mid (-1,-2), along (1,0), width 1,  base 0.10
  //   d2  r2 to the outside, mid (3,-2),  along (1,0), width 0.6, base 0.10
  //   d3  party wall r2|r3, mid (5,-1), along (1,0),  width 0.9, base 0.10
  //   d4  storey 1, room up, mid (0,2), along (1,0),  width 1,   base 2.30
  console.log('\ndoorMarkers — the payload IS the doorway, nothing is derived');
  const doorScene = {
    extent_m: 10,
    k: 1,
    levels: [{ level: 0, floor_y: 0 }, { level: 1, floor_y: 2.2 }],
    doorways: [
      { level: 0, at_world: [2, 0], along: [0, 1], width_m: 1, base_y: 0.1,
        rooms: ['r1', 'r2'], outside: false },
      { level: 0, at_world: [-1, -2], along: [1, 0], width_m: 1, base_y: 0.1,
        rooms: ['r1'], outside: true },
      { level: 0, at_world: [3, -2], along: [1, 0], width_m: 0.6, base_y: 0.1,
        rooms: ['r2'], outside: true },
      { level: 0, at_world: [5, -1], along: [1, 0], width_m: 0.9, base_y: 0.1,
        rooms: ['r2', 'r3'], outside: false },
      { level: 1, at_world: [0, 2], along: [1, 0], width_m: 1, base_y: 2.3,
        rooms: ['up'], outside: true },
    ],
    // Everything below is the material the module used to derive from. It is
    // still in the payload (other consumers need it) and must stay unread.
    rooms: [
      { room_id: 'r1', level: 0,
        outline: [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]],
        openings: [
          { edge: 2, at: 0.5, width_m: 1.2, height_m: 1.2, sill_m: 0.9, type: 'window' },
          { edge: 3, at: 0.5, width_m: 1, type: 'door', to: 'outside' },
        ] },
    ],
    walls: [
      { level: 0, room_id: 'r1', from: [-2, -2], to: [-1.5, -2], base_y: 0.1 },
      { level: 0, from: [-2, 3], to: [0.6, 3], base_y: 0.08 },
      { level: 0, from: [1.4, 3], to: [4, 3], base_y: 0.08 },
    ],
  };
  const dm0 = doorMarkers(doorScene, 0);
  check('the ground floor has exactly its four doorways', dm0.length, 4);
  check('the party wall arrives unchanged',
    { mid: dm0[0].mid, along: dm0[0].along, width: dm0[0].width,
      baseY: dm0[0].baseY, roomIds: dm0[0].roomIds, outside: dm0[0].outside },
    { mid: { x: 2, z: 0 }, along: { x: 0, z: 1 }, width: 1, baseY: 0.1,
      roomIds: ['r1', 'r2'], outside: false });
  check('an outside door names its ONE room',
    { mid: dm0[1].mid, width: dm0[1].width, roomIds: dm0[1].roomIds,
      outside: dm0[1].outside },
    { mid: { x: -1, z: -2 }, width: 1, roomIds: ['r1'], outside: true });
  check('the width is the CLEAR one, not width_m x k', dm0[2].width, 0.6);
  check('the storey filter is the level field', doorMarkers(doorScene, 1).length, 1);
  check('and the upper doorway stands on the upper wall foot',
    { mid: doorMarkers(doorScene, 1)[0].mid, baseY: doorMarkers(doorScene, 1)[0].baseY },
    { mid: { x: 0, z: 2 }, baseY: 2.3 });
  check('a storey nobody built has no doorways', doorMarkers(doorScene, 2).length, 0);
  check('no payload, no doorways', doorMarkers(null, 0).length, 0);
  check('a payload without the block has none either',
    doorMarkers({ extent_m: 10, k: 1 }, 0).length, 0);
  // The two contour pieces of the fixture lie 0.8 m apart (0.6 -> 1.4 at
  // z = 3) — the exact signature the old code called "the entrance". A marker
  // at (1,3) would mean the back-measuring is still there.
  check('no marker is measured out of the contour gap',
    dm0.filter((m) => Math.abs(m.mid.z - 3) < 1e-9).length, 0);
  // r1's own openings list carries a door on edge 3 the doorways do not know.
  // Deriving it would put a marker at (-2,0); reading cannot.
  check('no marker is recomputed from rooms[].openings',
    dm0.filter((m) => Math.abs(m.mid.x + 2) < 1e-9).length, 0);

  // THE WORLD OFFSET (the C1 lesson of the collision round): the payload is
  // TILE-LOCAL — world metres around the tile CENTRE — while the scene the
  // markers are added to is absolute. A tile on grid (4,-2) sits at world
  // (40,-20), so every mid has to move with it and nothing else may.
  console.log('\ndoorMarkers — the payload is tile-local, the scene is not (C1)');
  const off = doorMarkers(doorScene, 0, { x: 40, z: -20 });
  check('the party wall moves with the tile', off[0].mid, { x: 42, z: -20 });
  check('the outside door too', off[1].mid, { x: 39, z: -22 });
  check('the direction does NOT move', off[1].along, { x: 1, z: 0 });
  check('the width does not either', off[1].width, 1);
  check('and neither does the base height', off[1].baseY, 0.1);

  // ONE room, WHICH door: the floor probe (tiles.ts) shoots its reference ray
  // at the room's door, and a figure leaving a building walks through it. The
  // rule is "the outside door, else the first" — r1 has a party wall FIRST in
  // the list and an outside door second, so preference beats order.
  console.log('\nroomDoor — the outside door of a room, else its first');
  check('r1 prefers its outside door over the party wall it is listed after',
    roomDoor(doorScene, 'r1').mid, { x: -1, z: -2 });
  check('r2 takes its outside door over both party walls', roomDoor(doorScene, 'r2').mid,
    { x: 3, z: -2 });
  check('r3 has no outside door, so its party wall answers',
    { mid: roomDoor(doorScene, 'r3').mid, width: roomDoor(doorScene, 'r3').width },
    { mid: { x: 5, z: -1 }, width: 0.9 });
  check('the tile centre applies here too',
    roomDoor(doorScene, 'r3', { x: 40, z: -20 }).mid, { x: 45, z: -21 });
  check('a room without any doorway has none', roomDoor(doorScene, 'nope'), null);
  check('and neither has no room at all', roomDoor(doorScene, ''), null);
  check('no payload, no door', roomDoor(null, 'r1'), null);

  // BETWEEN two rooms: the NPC walk (main.ts) routes a room change through the
  // door that joins them — the entry whose `rooms` holds both. That is what
  // the removed single exit point per room could never answer.
  console.log('\ndoorwayBetween — the door that joins two rooms');
  check('r1 and r2 are joined by the party wall',
    { mid: doorwayBetween(doorScene, 'r1', 'r2').mid,
      roomIds: doorwayBetween(doorScene, 'r1', 'r2').roomIds },
    { mid: { x: 2, z: 0 }, roomIds: ['r1', 'r2'] });
  check('the order of the two rooms does not matter',
    doorwayBetween(doorScene, 'r2', 'r1').mid, { x: 2, z: 0 });
  check('r1 and r3 share no wall', doorwayBetween(doorScene, 'r1', 'r3'), null);
  check('a room is not joined to itself', doorwayBetween(doorScene, 'r1', 'r1'), null);
  check('an unknown room joins nothing', doorwayBetween(doorScene, 'r1', 'nope'), null);
  check('the tile centre applies here too',
    doorwayBetween(doorScene, 'r2', 'r3', { x: 40, z: -20 }).mid, { x: 45, z: -21 });

  // ── Audio prefs (stage 4, task 2) ────────────────────────────────────────
  console.log('\nprefs — the localStorage key and the shipped defaults');
  check('the store key is the versioned one', PREFS_KEY, 'av3d.audio.v1');
  check('DEFAULT_PREFS is exactly the brief', DEFAULT_PREFS, DEFAULTS);
  check('nothing stored yet -> defaults', loadPrefs(null), DEFAULTS);

  console.log('prefs — junk falls back, field by field');
  check('unparsable text -> defaults', loadPrefs('not json at all'), DEFAULTS);
  check('JSON null -> defaults', loadPrefs('null'), DEFAULTS);
  check('a JSON array is not a prefs object', loadPrefs('[0.5, 0.5]'), DEFAULTS);
  check('a bare number is not a prefs object', loadPrefs('3'), DEFAULTS);
  check('an empty object -> defaults', loadPrefs('{}'), DEFAULTS);
  check('one bad field does not reset the others',
    loadPrefs('{"master":"loud","music":0.25}'),
    { ...DEFAULTS, music: 0.25 });
  check('a numeric string is not a number',
    loadPrefs('{"music":"0.3"}'), DEFAULTS);
  check('NaN is not finite -> default', loadPrefs('{"music":null}'), DEFAULTS);
  check('a non-boolean switch -> default',
    loadPrefs('{"musicOn":"yes"}'), DEFAULTS);
  check('musicOn false is honoured',
    loadPrefs('{"musicOn":false}'), { ...DEFAULTS, musicOn: false });
  check('ambientOn false is honoured',
    loadPrefs('{"ambientOn":false}'), { ...DEFAULTS, ambientOn: false });

  console.log('prefs — volumes are clamped to [0,1], 0 survives');
  check('2 clamps down to 1', loadPrefs('{"master":2}'), { ...DEFAULTS, master: 1 });
  check('-1 clamps up to 0', loadPrefs('{"ambient":-1}'), { ...DEFAULTS, ambient: 0 });
  check('0 is a setting, not a missing value',
    loadPrefs('{"tts":0}'), { ...DEFAULTS, tts: 0 });
  check('Infinity is not finite -> default',
    loadPrefs('{"master":1e999}'), DEFAULTS);
  check('all four buses at once',
    loadPrefs('{"master":0.1,"music":0.2,"ambient":0.3,"tts":0.4}'),
    { ...DEFAULTS, master: 0.1, music: 0.2, ambient: 0.3, tts: 0.4 });

  console.log("prefs — ttsOn is 'auto' | 'on' | 'off'");
  check("'on' is taken", loadPrefs('{"ttsOn":"on"}'), { ...DEFAULTS, ttsOn: 'on' });
  check("'off' is taken", loadPrefs('{"ttsOn":"off"}'), { ...DEFAULTS, ttsOn: 'off' });
  check("'auto' is taken", loadPrefs('{"ttsOn":"auto"}'), DEFAULTS);
  check('an unknown mode falls back to auto',
    loadPrefs('{"ttsOn":"loud"}'), DEFAULTS);
  check('a boolean is not a mode', loadPrefs('{"ttsOn":true}'), DEFAULTS);

  console.log('prefs — the round trip the settings UI does');
  const edited = { master: 0.4, music: 0, ambient: 0.75, tts: 1,
    musicOn: false, ambientOn: true, ttsOn: 'off' };
  check('savePrefs -> loadPrefs returns the same prefs',
    loadPrefs(savePrefs(edited)), edited);
  check('defaults survive the round trip too',
    loadPrefs(savePrefs(DEFAULT_PREFS)), DEFAULTS);
  check('a clamped load round-trips unchanged',
    loadPrefs(savePrefs(loadPrefs('{"master":2,"music":-1}'))),
    { ...DEFAULTS, master: 1, music: 0 });

  // ── Boot progress (stage 4, task 3) ──────────────────────────────────────
  // The four stages are spelled out here BY HAND, in the order the loading
  // screen walks them — the module must not be the source of its own test.
  const STAGES = ['world', 'figures', 'scenes', 'tiles'];
  console.log('\nboot — the four stages and their order');
  check('BOOT_STAGES is exactly the brief, in order',
    [...BOOT_STAGES], STAGES);

  console.log('boot — 25 % per stage, label = first missing stage');
  check('nothing done yet', bootProgress(new Set()),
    { percent: 0, label: 'world' });
  check('world done', bootProgress(new Set(['world'])),
    { percent: 25, label: 'figures' });
  check('world + figures done', bootProgress(new Set(['world', 'figures'])),
    { percent: 50, label: 'scenes' });
  check('three of four done',
    bootProgress(new Set(['world', 'figures', 'scenes'])),
    { percent: 75, label: 'tiles' });
  check('all four done -> 100 % and ready',
    bootProgress(new Set(STAGES)), { percent: 100, label: 'ready' });

  console.log('boot — out-of-order and unknown stages');
  check('a later stage alone still counts, label names the first hole',
    bootProgress(new Set(['figures'])), { percent: 25, label: 'world' });
  check('a hole in the middle is what is waited for',
    bootProgress(new Set(['world', 'figures', 'tiles'])),
    { percent: 75, label: 'scenes' });
  check('an unknown entry is not a stage',
    bootProgress(new Set(['world', 'bogus'])), { percent: 25, label: 'figures' });
  check('only unknown entries -> nothing done',
    bootProgress(new Set(['bogus', 'other'])), { percent: 0, label: 'world' });
  check('insertion order of the set does not matter',
    bootProgress(new Set(['tiles', 'scenes', 'figures', 'world'])),
    { percent: 100, label: 'ready' });

  console.log('boot — the store the title screen subscribes to');
  check('a fresh store is at zero',
    { percent: getBootState().percent, label: getBootState().label,
      note: getBootState().note },
    { percent: 0, label: 'world', note: null });
  let bootTicks = 0;
  const unsubBoot = subscribeBoot(() => { bootTicks += 1; });
  reportBootStage('world');
  check('reporting a stage moves the store',
    { percent: getBootState().percent, label: getBootState().label },
    { percent: 25, label: 'figures' });
  check('the subscriber was notified once', bootTicks, 1);
  reportBootStage('world');
  check('reporting the same stage twice does not count twice',
    getBootState().percent, 25);
  check('reporting it twice does not notify twice', bootTicks, 1);
  setBootNote({ kind: 'retry', seconds: 4 });
  check('the note rides along', getBootState().note, { kind: 'retry', seconds: 4 });
  check('the note notified', bootTicks, 2);
  setBootNote({ kind: 'retry', seconds: 4 });
  check('the same note again is not a change', bootTicks, 2);
  setBootNote({ kind: 'retry', seconds: 8 });
  check('a longer wait IS a change', bootTicks, 3);
  setBootNote(null);
  check('null clears the note', getBootState().note, null);
  for (const s of STAGES) reportBootStage(s);
  check('all stages reported -> 100 % and ready',
    { percent: getBootState().percent, label: getBootState().label },
    { percent: 100, label: 'ready' });
  unsubBoot();
  const ticksAfter = bootTicks;
  setBootNote({ kind: 'failed' });
  check('an unsubscribed listener stops hearing', bootTicks, ticksAfter);

  // ── Soundtrack (stage 4, task 5) ─────────────────────────────────────────
  console.log('\nsoundtrack — the manifest door');
  const EMPTY = { music: { day: [], night: [] }, ambient: {} };
  check('an empty manifest is two empty buckets and no terrain',
    emptyManifest(), EMPTY);
  check('null is not a manifest', readManifest(null), EMPTY);
  check('a string is not a manifest', readManifest('audio'), EMPTY);
  check('an array is not an ambient map',
    readManifest({ ambient: ['grass'] }), EMPTY);
  check('a music bucket that is not a list becomes empty',
    readManifest({ music: { day: 'a.mp3', night: null } }), EMPTY);
  check('non-string entries are dropped',
    readManifest({ music: { day: ['a.mp3', 3, null, ''], night: [] } }),
    { music: { day: ['a.mp3'], night: [] }, ambient: {} });
  check('an ambient key without playable files does not appear',
    readManifest({ ambient: { grass: [], forest: ['f.ogg'] } }),
    { music: { day: [], night: [] }, ambient: { forest: ['f.ogg'] } });
  check('the shape the server actually sends survives unchanged',
    readManifest({ music: { day: ['/assets/audio/music/day/a.mp3'], night: ['/n.mp3'] },
      ambient: { grass: ['/g.mp3', '/g2.mp3'] } }),
    { music: { day: ['/assets/audio/music/day/a.mp3'], night: ['/n.mp3'] },
      ambient: { grass: ['/g.mp3', '/g2.mp3'] } });

  console.log('soundtrack — the day/night hysteresis (0.2 / 0.8, strict)');
  check('the thresholds are the documented ones', [NIGHT_OFF, NIGHT_ON], [0.2, 0.8]);
  check('full day stays day', nightForMusic(false, 0), false);
  check('exactly 0.2 is not "below" — day stays day', nightForMusic(false, 0.2), false);
  check('the dead band keeps day', nightForMusic(false, 0.5), false);
  check('exactly 0.8 is not "above" — day stays day', nightForMusic(false, 0.8), false);
  check('past 0.8 it becomes night', nightForMusic(false, 0.81), true);
  check('the dead band keeps night', nightForMusic(true, 0.5), true);
  check('0.21 still keeps night', nightForMusic(true, 0.21), true);
  check('below 0.2 it becomes day again', nightForMusic(true, 0.19), false);
  // The whole point: a factor wobbling around the lower threshold switches ONCE.
  let musicNight = true;
  let musicFlips = 0;
  for (const f of [0.19, 0.21, 0.19, 0.21, 0.19]) {
    const next = nightForMusic(musicNight, f);
    if (next !== musicNight) musicFlips += 1;
    musicNight = next;
  }
  check('a wobble around 0.2 flips exactly once', musicFlips, 1);
  check('and it ends on day', musicNight, false);

  console.log('soundtrack — the playlists, with no substitutions');
  const MAN = readManifest({
    music: { day: ['/d1.mp3', '/d2.mp3'], night: ['/n1.mp3'] },
    ambient: { grass: ['/a-grass.mp3'], Forest: ['/a-forest.mp3'] },
  });
  check('day plays the day bucket', pickMusic(MAN, false), ['/d1.mp3', '/d2.mp3']);
  check('night plays the night bucket', pickMusic(MAN, true), ['/n1.mp3']);
  check('an empty night bucket is silence, not the day list',
    pickMusic(readManifest({ music: { day: ['/d.mp3'], night: [] } }), true), []);
  check('the terrain hits its folder', pickAmbient(MAN, 'grass'), ['/a-grass.mp3']);
  check('the folder name matches case-insensitively',
    pickAmbient(MAN, 'forest'), ['/a-forest.mp3']);
  check('an unknown terrain is silence', pickAmbient(MAN, 'lava'), []);
  check('no terrain is silence', pickAmbient(MAN, ''), []);

  console.log('soundtrack — whose surroundings one hears');
  // METRE POINTS since E4 task 5 — `main.ts` looks the terrain up on the
  // footprint under the point, not on a cell.
  const TERRAIN = new Map([['0,0', 'grass'], ['10,0', ' Water '], ['20,0', '']]);
  const terrainAt = (at) => TERRAIN.get(`${at.x},${at.z}`) ?? '';
  check('embodied: the ground the avatar stands on',
    ambientTerrainFor('embodied', { x: 0, z: 0 }, { x: 10, z: 0 }, terrainAt), 'grass');
  check('overview: the point the camera looks at',
    ambientTerrainFor('overview', { x: 0, z: 0 }, { x: 10, z: 0 }, terrainAt), 'water');
  check('the terrain is trimmed and lower-cased',
    ambientTerrainFor('embodied', { x: 10, z: 0 }, null, terrainAt), 'water');
  check('a point without a location is silence',
    ambientTerrainFor('overview', { x: 0, z: 0 }, { x: 90, z: 90 }, terrainAt), '');
  check('a location without a terrain is silence',
    ambientTerrainFor('overview', { x: 0, z: 0 }, { x: 20, z: 0 }, terrainAt), '');
  check('no avatar yet: embodied hears nothing, NOT the camera point',
    ambientTerrainFor('embodied', null, { x: 0, z: 0 }, terrainAt), '');

  console.log('soundtrack — the 5 s terrain debounce');
  check('the hold is the documented one', AMBIENT_HOLD_MS, 5000);
  check('a fresh state has nothing playing and has not started',
    newTerrainSwitch(), { applied: '', pending: '', since: 0, started: false });
  check('nothing to play keeps the state unstarted',
    terrainSwitch(newTerrainSwitch(), '', 500), { applied: '', pending: '', since: 0, started: false });
  let ts = terrainSwitch(newTerrainSwitch(), 'grass', 1000);
  check('the FIRST terrain is taken at once',
    ts, { applied: 'grass', pending: 'grass', since: 1000, started: true });
  ts = terrainSwitch(ts, 'grass', 2000);
  check('the same terrain again changes nothing that plays', ts.applied, 'grass');
  ts = terrainSwitch(ts, 'water', 3000);
  check('a new terrain only becomes pending',
    ts, { applied: 'grass', pending: 'water', since: 3000, started: true });
  ts = terrainSwitch(ts, 'water', 5000);
  check('2000 ms of holding is not enough', ts.applied, 'grass');
  ts = terrainSwitch(ts, 'water', 7999);
  check('4999 ms is not enough either', ts.applied, 'grass');
  ts = terrainSwitch(ts, 'water', 8000);
  check('exactly 5000 ms takes over',
    ts, { applied: 'water', pending: 'water', since: 8000, started: true });
  // The flap the hold exists for: one second of water while walking a corner.
  let flap = terrainSwitch(newTerrainSwitch(), 'grass', 1000);
  flap = terrainSwitch(flap, 'water', 2000);
  flap = terrainSwitch(flap, 'grass', 3000);
  check('coming back cancels the pending switch',
    flap, { applied: 'grass', pending: 'grass', since: 3000, started: true });
  flap = terrainSwitch(flap, 'grass', 9000);
  check('and the passed-through terrain never matures', flap.applied, 'grass');

  // ONLY the first terrain skips the hold. Silence is a candidate like any
  // other, and the terrain that follows silence holds its own 5 s — "started"
  // means "something has played", not "we are past the hold once and for all".
  let quiet = terrainSwitch(newTerrainSwitch(), 'grass', 1000);
  quiet = terrainSwitch(quiet, '', 2000);
  check('walking off the map only makes silence pending',
    quiet, { applied: 'grass', pending: '', since: 2000, started: true });
  quiet = terrainSwitch(quiet, '', 6999);
  check('4999 ms of nothing is not enough for silence', quiet.applied, 'grass');
  quiet = terrainSwitch(quiet, '', 7000);
  check('exactly 5000 ms turns the bed off',
    quiet, { applied: '', pending: '', since: 7000, started: true });
  quiet = terrainSwitch(quiet, 'water', 8000);
  check('the terrain after silence is pending, NOT taken at once',
    quiet, { applied: '', pending: 'water', since: 8000, started: true });
  quiet = terrainSwitch(quiet, 'water', 12999);
  check('and it holds its own 4999 ms in vain', quiet.applied, '');
  quiet = terrainSwitch(quiet, 'water', 13000);
  check('only its full 5000 ms take over',
    quiet, { applied: 'water', pending: 'water', since: 13000, started: true });

  // ── Voiceover (stage 4, task 6) ──────────────────────────────────────────
  //
  // One scene line, with everything that matters overridable. `ts` counts up in
  // the tests, because "new" is defined by it.
  const AVATAR = 'Alva';
  // The ts shape is the one the server really sends: SECONDS, no microseconds
  // (utc_now_iso(timespec="seconds"), app/core/timeutils.py:33).
  const line = (over = {}) => ({
    ts: '2026-08-01T10:00:00+00:00',
    kind: 'in_room', speaker: 'Mira', content: 'Good evening.', ...over,
  });

  console.log('\nvoiceover — the ONE new-lines detection (chat auto-show + speech)');
  const l1 = line({ ts: '2026-08-01T10:00:01+00:00' });
  const l2 = line({ ts: '2026-08-01T10:00:02+00:00', content: 'And you?' });
  const l3 = line({ ts: '2026-08-01T10:00:03+00:00', content: 'Well.' });
  check('the stamp is count + the identity of the last line',
    sceneStampOf([l1, l2]), '2|2026-08-01T10:00:02+00:00|Mira|And you?');
  check('an empty transcript has a stamp too', sceneStampOf([]), '0|');
  check('a missing transcript is the same as an empty one',
    sceneStampOf(undefined), '0|');
  // The stamp is what the HUD's effect depends on, so it has to MOVE when the
  // window rolls a line out at the front and a new one arrives in the same
  // second — count and ts are both unchanged there, only the words differ.
  check('a rolled window in the same second still moves the stamp',
    sceneStampOf([l1, l2]) === sceneStampOf([l2, line({ ts: l2.ts, content: 'Or not.' })]),
    false);
  check('the FIRST payload only sets the baseline',
    newSceneLines(null, { room: 'hall', lines: [l1, l2] }), []);
  check('a room change is not somebody speaking',
    newSceneLines({ room: 'hall', lines: [l1] },
      { room: 'yard', lines: [l1, l2] }), []);
  check('the same transcript is silence',
    newSceneLines({ room: 'hall', lines: [l1, l2] },
      { room: 'hall', lines: [l1, l2] }), []);
  check('one appended line is one new line',
    newSceneLines({ room: 'hall', lines: [l1, l2] },
      { room: 'hall', lines: [l1, l2, l3] }), [l3]);
  check('two appended lines are two new lines',
    newSceneLines({ room: 'hall', lines: [l1] },
      { room: 'hall', lines: [l1, l2, l3] }), [l2, l3]);
  // The rolling window of /play/scene: the count stays equal, the content moves.
  check('a rolled window still finds the new line',
    newSceneLines({ room: 'hall', lines: [l1, l2] },
      { room: 'hall', lines: [l2, l3] }), [l3]);
  check('an empty room that gets its first line hears all of it',
    newSceneLines({ room: 'hall', lines: [] },
      { room: 'hall', lines: [l1, l2] }), [l1, l2]);
  check('lines pruned from the front alone are not new',
    newSceneLines({ room: 'hall', lines: [l1, l2, l3] },
      { room: 'hall', lines: [l3] }), []);

  console.log('voiceover — leaving the room ends its conversation');
  // `newSceneLines` answers a room change with [] — exactly like silence — so
  // the caller cannot tell them apart, and they need opposite things: silence
  // lets the queue run on, a room change drops it (the waiting lines were said
  // where one no longer is). Hence a predicate of its own.
  check('the first payload is not a change',
    roomChanged(null, { room: 'hall', lines: [l1] }), false);
  check('the same room is not a change',
    roomChanged({ room: 'hall', lines: [l1] }, { room: 'hall', lines: [l1, l2] }), false);
  check('another room IS a change',
    roomChanged({ room: 'hall', lines: [l1] }, { room: 'yard', lines: [] }), true);
  check('and it is a change even when the new room is silent',
    roomChanged({ room: 'hall', lines: [l1, l2] }, { room: 'yard', lines: [l3] }), true);
  check('arriving from nowhere counts as a change too',
    roomChanged({ room: '', lines: [] }, { room: 'hall', lines: [l1] }), true);
  // What the caller does with it is checked against the driver further down
  // ("a room change leaves nothing waiting").

  console.log('voiceover — a second character answering in the SAME second');
  // The failure this rule exists for: the poll ends with a line stamped …:01,
  // the parallel respond lane writes another one in the same clock second, and
  // "newer than the last ts" would never see it — not read aloud, and the chat
  // panel would not come up for it either.
  const same = line({ ts: l1.ts, speaker: 'Toran', content: 'Evening.' });
  check('a line stamped in the same second as the last seen one IS new',
    newSceneLines({ room: 'hall', lines: [l1] },
      { room: 'hall', lines: [l1, same] }), [same]);
  // Count AND ts unchanged (2 lines, last one stamped …:02) — only the anchor
  // shows that the window moved on.
  const same2 = line({ ts: l2.ts, speaker: 'Toran', content: 'Quite.' });
  check('a window that rolls within one second is still read correctly',
    newSceneLines({ room: 'hall', lines: [l1, l2] },
      { room: 'hall', lines: [l2, same2] }), [same2]);
  check('two more in the same second are both new',
    newSceneLines({ room: 'hall', lines: [l1] },
      { room: 'hall', lines: [l1, same, line({ ts: l1.ts, speaker: 'Nira', content: 'Hm.' })] })
      .length, 2);
  check('the same-second line is not found twice',
    newSceneLines({ room: 'hall', lines: [l1, same] },
      { room: 'hall', lines: [l1, same] }), []);
  check('a rolled window in the same second finds only what is new',
    newSceneLines({ room: 'hall', lines: [l1, same] },
      { room: 'hall', lines: [same, l2] }), [l2]);
  // The anchor is gone from the window (more than a window's worth of lines
  // since the last poll): the ts comparison stands in.
  check('an anchor that left the window falls back to the timestamps',
    newSceneLines({ room: 'hall', lines: [l1] },
      { room: 'hall', lines: [l2, l3] }), [l2, l3]);

  console.log('voiceover — the same words twice in the same second');
  // Two characters CAN say the same thing in the same second; then the
  // identity is not unique and the count decides where to cut.
  const dup = line({ ts: l2.ts, speaker: 'Mira', content: 'Yes.' });
  check('a duplicate of the anchor line is new the first time',
    newSceneLines({ room: 'hall', lines: [l1, dup] },
      { room: 'hall', lines: [l1, dup, dup] }), [dup]);
  check('but only once — seen twice, cut after the second',
    newSceneLines({ room: 'hall', lines: [l1, dup, dup] },
      { room: 'hall', lines: [l1, dup, dup] }), []);
  check('what follows a repeated anchor is still found',
    newSceneLines({ room: 'hall', lines: [l1, dup, dup] },
      { room: 'hall', lines: [l1, dup, dup, l3] }), [l3]);
  check('fewer copies than before means the older ones rolled out',
    newSceneLines({ room: 'hall', lines: [l1, dup, dup] },
      { room: 'hall', lines: [dup, l3] }), [l3]);

  console.log('voiceover — the sentinel and who is read aloud');
  check('the canonical narrator value is the first sentinel',
    NARRATOR_SPEAKERS[0], 'Storyteller');
  check('the localised label is one too', NARRATOR_SPEAKERS.includes('Erzähler'), true);
  check('the speaker is read like SceneView reads it',
    speakerOf(line({ speaker: '', meta: { speaker: 'Toran' } })), 'Toran');
  check('a top-level speaker wins over the meta one',
    speakerOf(line({ speaker: 'Mira', meta: { speaker: 'Toran' } })), 'Mira');
  check('a room line is spoken', speakableLines([line()], AVATAR),
    [{ speaker: 'Mira', text: 'Good evening.' }]);
  check('the order is kept',
    speakableLines([line({ content: 'one' }), line({ speaker: 'Toran', content: 'two' })],
      AVATAR),
    [{ speaker: 'Mira', text: 'one' }, { speaker: 'Toran', text: 'two' }]);
  check('the avatar is never read back to itself',
    speakableLines([line({ speaker: AVATAR })], AVATAR), []);
  check("one's own line is spoken_self, and that is not read back either",
    speakableLines([line({ kind: 'spoken_self', speaker: AVATAR })], AVATAR), []);
  check('the canonical narrator stays silent',
    speakableLines([line({ speaker: 'Storyteller' })], AVATAR), []);
  check('the localised narrator stays silent too',
    speakableLines([line({ speaker: 'Erzähler' })], AVATAR), []);
  check('a narrator in meta.speaker is caught as well',
    speakableLines([line({ speaker: '', meta: { speaker: 'Erzähler' } })], AVATAR), []);
  check('a whisper THIRD PARTIES only hear about has nothing to say',
    speakableLines([line({ kind: 'whisper_meta', content: '' })], AVATAR), []);
  check('a shout from another room is not in the room',
    speakableLines([line({ kind: 'distant_shout' })], AVATAR), []);
  check('the objective god view is not a player line',
    speakableLines([line({ kind: 'utterance' })], AVATAR), []);
  check('a line without a kind is not spoken',
    speakableLines([line({ kind: undefined })], AVATAR), []);
  check('an empty line has nothing to say',
    speakableLines([line({ content: '' })], AVATAR), []);
  check('whitespace is nothing to say either',
    speakableLines([line({ content: '   ' })], AVATAR), []);
  check('the text is trimmed',
    speakableLines([line({ content: '  Hello.  ' })], AVATAR),
    [{ speaker: 'Mira', text: 'Hello.' }]);
  check('a line without any speaker is dropped',
    speakableLines([line({ speaker: '' })], AVATAR), []);
  check('a display-only note is not speech',
    speakableLines([line({ meta: { display_only: true } })], AVATAR), []);
  check('a relationship note is not speech',
    speakableLines([line({ meta: { relationship: true } })], AVATAR), []);
  check('an event verdict is not speech',
    speakableLines([line({ meta: { event_verdict: 'resolved' } })], AVATAR), []);
  // A whisper the avatar IS an addressee of arrives as a normal in_room line
  // with content — it is meant for the player and is read like any other.
  check('a whisper meant for the avatar is read',
    speakableLines([line({ volume: 'whisper', content: 'Psst.' })], AVATAR),
    [{ speaker: 'Mira', text: 'Psst.' }]);
  check('a different narrator list is respected',
    speakableLines([line({ speaker: 'Chronicler' })], AVATAR, ['Chronicler']), []);

  console.log("voiceover — one's own message ends the backlog");
  const own = line({ ts: '2026-08-01T10:00:04.000000+00:00', speaker: AVATAR,
    kind: 'spoken_self', content: 'Wait.' });
  check('without an own line everything counts',
    afterOwnLine([l1, l2], AVATAR), [l1, l2]);
  check('an own line at the end drops the whole batch',
    afterOwnLine([l1, l2, own], AVATAR), []);
  check('only what came after the own line survives',
    afterOwnLine([l1, own, l3], AVATAR), [l3]);
  check('the LAST own line decides',
    afterOwnLine([l1, own, l2, line({ speaker: AVATAR, content: 'No.' }), l3], AVATAR),
    [l3]);
  check('an empty batch stays empty', afterOwnLine([], AVATAR), []);

  console.log('voiceover — at most three lines wait');
  const q = (n) => ({ speaker: 'Mira', text: `line ${n}` });
  check('the cap is the documented one', MAX_PENDING, 3);
  check('nothing waiting plus nothing new is nothing',
    enqueueSpeech([], []), []);
  check('two lines simply queue', enqueueSpeech([], [q(1), q(2)]), [q(1), q(2)]);
  check('three lines are still all of them',
    enqueueSpeech([q(1)], [q(2), q(3)]), [q(1), q(2), q(3)]);
  check('the fourth pushes the oldest out',
    enqueueSpeech([q(1), q(2), q(3)], [q(4)]), [q(2), q(3), q(4)]);
  check('five at once leave the last three',
    enqueueSpeech([], [q(1), q(2), q(3), q(4), q(5)]), [q(3), q(4), q(5)]);
  check('a full queue with nothing new is unchanged',
    enqueueSpeech([q(1), q(2), q(3)], []), [q(1), q(2), q(3)]);
  check('the cap is a parameter',
    enqueueSpeech([q(1), q(2)], [q(3)], 2), [q(2), q(3)]);

  console.log('voiceover — the serial driver');
  // Fake deps: `synth` answers with a URL derived from the text (or '' where
  // the test wants a failure), `play` records what sounded. A macrotask turn
  // (`flush`) is enough to let the whole chain settle, because every promise
  // here resolves immediately.
  const flush = () => new Promise((r) => setTimeout(r, 0));
  function fakeVoice(opts = {}) {
    const spoken = [];
    const asked = [];
    let stops = 0;
    const vo = createVoiceover({
      synth: async (l) => { asked.push(l.text); return opts.synth ? opts.synth(l) : `/tts/${l.text}`; },
      play: async (url) => { spoken.push(url); },
      stop: () => { stops += 1; },
    });
    return { vo, spoken, asked, stops: () => stops };
  }
  let fv = fakeVoice();
  fv.vo.push([q(1), q(2)]);
  await flush();
  check('both lines were rendered, in order', fv.asked, ['line 1', 'line 2']);
  check('and both sounded, in order', fv.spoken, ['/tts/line 1', '/tts/line 2']);
  check('nothing waits afterwards', fv.vo.pending, []);
  fv = fakeVoice();
  fv.vo.push([q(1), q(2), q(3), q(4), q(5)]);
  check('the cap holds at the moment of pushing: 3 kept, the head taken',
    fv.vo.pending, [q(4), q(5)]);
  await flush();
  check('so the two oldest of five are never even rendered',
    fv.asked, ['line 3', 'line 4', 'line 5']);
  fv = fakeVoice({ synth: (l) => (l.text === 'line 2' ? '' : `/tts/${l.text}`) });
  fv.vo.push([q(1), q(2), q(3)]);
  await flush();
  check('a line without audio is skipped, the queue goes on',
    fv.spoken, ['/tts/line 1', '/tts/line 3']);
  // The interruption: the player says something while the room is talking.
  fv = fakeVoice();
  fv.vo.push([q(1), q(2), q(3)]);
  fv.vo.clear();
  check('clearing empties what waits', fv.vo.pending, []);
  check('and silences what sounds', fv.stops(), 1);
  await flush();
  check('at most the line already in flight is heard', fv.spoken.length <= 1, true);
  check('nothing was queued behind it', fv.vo.pending, []);
  // …and the driver still works afterwards.
  fv.vo.push([q(9)]);
  await flush();
  check('a cleared driver takes new lines again',
    fv.spoken[fv.spoken.length - 1], '/tts/line 9');
  // Walking out of the room is the same interruption as one's own message —
  // the caller asks `roomChanged` and clears (Hud.tsx).
  fv = fakeVoice();
  fv.vo.push([q(1), q(2), q(3)]);
  if (roomChanged({ room: 'hall', lines: [l1] }, { room: 'yard', lines: [] })) fv.vo.clear();
  check('a room change leaves nothing waiting', fv.vo.pending, []);
  check('and silences the line in flight', fv.stops(), 1);
  await flush();
  check('nothing of the old room is heard afterwards', fv.spoken.length <= 1, true);

  // --- the ENTRY OFFER moved out (E4 task 5) ------------------------------
  // `entryOfferNear` speaks METRES now (opening world points, no adjacency and
  // no crossed edge), and `entryEdgeBetween`/`EXIT_EDGE_OF`/`mayLeaveAcross`
  // are gone with the step they served. Its hand-derived cases — § A1.1
  // local→world including yaw 90, the offer radius, open-beats-locked — live
  // in `client3d/scripts/smoke_enter_math.mjs`, which is TRACKED (this file is
  // not) and runs the same way.


  // ==== locks.ts — what is barred, and what that leaves (task C2) ==========
  //
  // Source of the rules: client3d/src/game/locks.ts and § 3 decision 2 of
  // plan-betreten-und-tueren.md ("a ban is visible"). The lock map comes from
  // the server (`/play/scene`) and holds a key EXACTLY for what is locked, so
  // presence is the whole test — a locked thing the rule gave no words to is
  // still locked.
  //
  //   isLocked({kitchen:'…'}, 'kitchen') → true   (key present)
  //   isLocked({kitchen:'…'}, 'hall')    → false  (no key)
  //   isLocked({vault:''},    'vault')   → true   (present, wordless)
  //   lockReason of an open id            → ''    (nothing to show)
  //
  // A DOORWAY is locked by the room BEHIND it, never by the room one stands
  // in — otherwise every door of a room one may not re-enter reads as a cage.
  // The first locked room in payload order supplies the words (`rooms[0]` owns
  // the wall the gap was cut from).
  //
  // The room walk drops locked rooms from its candidates, but keeps the room
  // the avatar is ALREADY in: without that exception the nearest OTHER room
  // becomes the best candidate while the figure stands still, and the
  // hysteresis walks it out of a room it legitimately occupies.
  console.log('locks — the server says what is barred (task C2)');
  {
    const { isLocked, lockReason, doorwayLock, unlockedRooms, NO_LOCKS } = locks;
    const LOCKS = { kitchen: 'The door is locked.', vault: '' };

    check('a listed room is locked', isLocked(LOCKS, 'kitchen'), true);
    check('an unlisted room is not', isLocked(LOCKS, 'hall'), false);
    check('a wordless entry is still a lock', isLocked(LOCKS, 'vault'), true);
    check('no map at all locks nothing', isLocked(null, 'kitchen'), false);
    check('the empty id is never locked', isLocked(LOCKS, ''), false);
    check('NO_LOCKS is empty', isLocked(NO_LOCKS, 'kitchen'), false);
    // The sentence travels untranslated — it is the server's, already localized.
    check('the reason is the server\'s own sentence',
      lockReason(LOCKS, 'kitchen'), 'The door is locked.');
    check('an open room has no reason', lockReason(LOCKS, 'hall'), '');
    check('a wordless lock has none either', lockReason(LOCKS, 'vault'), '');
    // A map is a plain object: an inherited property must not pass for a lock.
    check('a prototype property is no lock', isLocked(LOCKS, 'toString'), false);

    // null = open, a string (even the empty one) = locked. The two must not be
    // one answer: a wordless lock has to be drawn as a lock all the same.
    check('a doorway into a locked room is locked',
      doorwayLock(['hall', 'kitchen'], LOCKS), 'The door is locked.');
    check('a doorway between two open rooms is not',
      doorwayLock(['hall', 'study'], LOCKS), null);
    check('the first locked room in payload order supplies the words',
      doorwayLock(['kitchen', 'vault'], LOCKS), 'The door is locked.');
    check('a wordless lock is a lock, not an open door',
      doorwayLock(['vault', 'kitchen'], LOCKS), '');
    check('standing IN the locked room, its own door stays open',
      doorwayLock(['kitchen', 'hall'], LOCKS, 'kitchen'), null);
    check('...but a second locked room behind it still shows',
      doorwayLock(['kitchen', 'vault'], LOCKS, 'kitchen'), '');
    check('an outside door of a locked room, standing in it, is open',
      doorwayLock(['kitchen'], LOCKS, 'kitchen'), null);
    check('a doorway without rooms is open', doorwayLock([], LOCKS), null);
    check('and so is one with nothing locked', doorwayLock(['hall'], NO_LOCKS), null);

    const ROOMS = [{ id: 'hall' }, { id: 'kitchen' }, { id: 'study' }];
    check('a locked room is no candidate',
      unlockedRooms(ROOMS, LOCKS).map((r) => r.id), ['hall', 'study']);
    check('the room one is in survives its own lock',
      unlockedRooms(ROOMS, LOCKS, 'kitchen').map((r) => r.id),
      ['hall', 'kitchen', 'study']);
    check('nothing locked leaves the list alone',
      unlockedRooms(ROOMS, NO_LOCKS).map((r) => r.id), ['hall', 'kitchen', 'study']);
  }

  console.log('locks + nearestRoomSwitch — a locked room is never walked into');
  {
    const { unlockedRooms, NO_LOCKS } = locks;
    // Fixture as in the room-walk block above: hall at x=0, kitchen at x=10,
    // both on storey 0, HOLD = 1.5 s. The avatar stands at x = 9, i.e. 1 m
    // from the kitchen centre and 9 m from the hall's — the kitchen is the
    // nearest room and a switch is due once the hold has run out.
    const ROOMS = [
      { id: 'hall', level: 0, center: { x: 0, z: 0 } },
      { id: 'kitchen', level: 0, center: { x: 10, z: 0 } },
    ];
    const HOLD = 1.5;
    const AT = { x: 9, z: 0 };
    const LOCKED = { kitchen: 'The kitchen is closed.' };

    // Unlocked, for the contrast: candidate at 0 ms, switch at 1600 ms.
    let open = nearestRoomSwitch('hall', AT, unlockedRooms(ROOMS, NO_LOCKS),
      0, idleRoomWalk(), 0, HOLD);
    check('open: the kitchen becomes the candidate', open.state.candidate, 'kitchen');
    open = nearestRoomSwitch('hall', AT, unlockedRooms(ROOMS, NO_LOCKS),
      0, open.state, 1600, HOLD);
    check('open: after 1.6 s the switch is due', open.next, 'kitchen');

    // Locked: the kitchen is not in the candidate list at all, so the only
    // room left is the hall the avatar is already in — no candidate, no clock,
    // no switch, however long one stands there.
    const left = unlockedRooms(ROOMS, LOCKED);
    check('the locked kitchen is gone from the candidates',
      left.map((r) => r.id), ['hall']);
    let shut = nearestRoomSwitch('hall', AT, left, 0, idleRoomWalk(), 0, HOLD);
    check('locked: no candidate starts', shut.state.candidate, null);
    check('locked: the avatar stays in the hall', shut.next, 'hall');
    shut = nearestRoomSwitch('hall', AT, left, 0, shut.state, 1600, HOLD);
    check('locked: and still does after the hold', shut.next, 'hall');
    // Standing INSIDE the locked room: it stays a candidate for itself, so the
    // avatar is not pushed back out to the hall 9 m away.
    const inside = unlockedRooms(ROOMS, LOCKED, 'kitchen');
    check('inside the locked room it is still listed',
      inside.map((r) => r.id), ['hall', 'kitchen']);
    const stay = nearestRoomSwitch('kitchen', AT, inside, 0, idleRoomWalk(), 0, HOLD);
    check('inside: nothing moves the avatar out', stay.next, 'kitchen');
    check('inside: and no clock runs', stay.state.candidate, null);
  }

  // ==== perfstats.ts — the performance readout (Etappe 5) ==================
  //
  // Source of every expected number below: the RULES in the module docstring,
  // worked out by hand — never a recorded output.
  //
  // --- FPS window ---------------------------------------------------------
  // pushFrame appends dt, then drops from the FRONT while
  //   sum > FPS_WINDOW_S (= 1) AND more than one sample is left,
  // and returns samples.length / sum.
  // All frame times below are exact binary fractions (1/16 = 0.0625), so the
  // sums are exact and the expected values are plain division.
  console.log('perfstats — the fps window');
  const { newFpsMeter, pushFrame, fpsOf, visibleVertices, tierCounts } = perfstats;

  const m0 = newFpsMeter();
  check('an empty meter reads 0', fpsOf(m0), 0);
  //   one frame of 0.02 s -> 1 / 0.02 = 50
  check('one frame: 1 / 0.02 = 50', pushFrame(m0, 0.02), 50);
  //   five frames of 0.02 -> sum 0.10 (< 1, nothing drops) -> 5 / 0.10 = 50
  for (let i = 0; i < 4; i += 1) pushFrame(m0, 0.02);
  check('five frames of 0.02 s stay 50 fps', fpsOf(m0), 50, 1e-12);
  check('  and the window still holds all five', m0.samples.length, 5);

  //   16 frames of 1/16 s -> sum EXACTLY 1.0 -> "sum > 1" is false, none drop
  const m1 = newFpsMeter();
  for (let i = 0; i < 16; i += 1) pushFrame(m1, 0.0625);
  check('16 x 1/16 s fills the window exactly', m1.sum, 1);
  check('  16 samples over 1 s = 16 fps', fpsOf(m1), 16);
  //   the 17th pushes the sum to 1.0625 > 1 -> exactly one sample drops,
  //   leaving 16 over 1.0 s again: a steady rate stays steady
  check('the 17th frame drops the oldest, reading stays 16', pushFrame(m1, 0.0625), 16);
  check('  and the window is 16 samples again', m1.samples.length, 16);
  //   a 0.5 s stall on top: sum 1.5 with 17 samples. Dropping 1/16 at a time
  //   needs 8 drops to reach sum 1.0 (1.5 - 8*0.0625 = 1.0), leaving 9
  //   samples -> 9 / 1.0 = 9 fps. The stall is VISIBLE, not averaged away.
  check('a 0.5 s stall drops the rate to 9', pushFrame(m1, 0.5), 9);
  check('  9 samples left in the window', m1.samples.length, 9);

  //   a single frame longer than the window survives as itself: the drop loop
  //   never empties the list, so 2 s reads 1 / 2 = 0.5 fps
  const m2 = newFpsMeter();
  check('one 2 s frame reads 0.5 fps', pushFrame(m2, 2), 0.5);
  check('  and is not dropped', m2.samples.length, 1);
  //   junk is ignored, the reading is kept
  check('NaN is ignored', pushFrame(m2, NaN), 0.5);
  check('0 is ignored (THREE.Clock hands one out on frame 1)', pushFrame(m2, 0), 0.5);
  check('a negative dt is ignored', pushFrame(m2, -0.5), 0.5);
  check('  none of the three changed the window', m2.samples.length, 1);

  // --- visibleVertices ----------------------------------------------------
  // Rule: an invisible node contributes nothing AND takes its whole subtree
  // with it; a visible node contributes geometry.attributes.position.count.
  console.log('perfstats — vertices of the visible graph');
  const mesh = (count, visible = true, children = []) =>
    ({ visible, children, geometry: { attributes: { position: { count } } } });
  const group = (visible, children) => ({ visible, children });

  check('nothing at all is 0', visibleVertices(null), 0);
  check('a lone visible mesh is its own count', visibleVertices(mesh(100)), 100);
  check('an invisible mesh is 0', visibleVertices(mesh(100, false)), 0);
  //   100 + 250 visible, the 999 hangs under an invisible group (the closed
  //   location) and must not count -> 350
  const scene = group(true, [
    mesh(100), mesh(250), group(false, [mesh(999)]), { visible: true },
  ]);
  check('an invisible group takes its subtree with it', visibleVertices(scene), 350);
  //   shared geometry counts ONCE PER NODE: ten clones cost ten draws
  const forestOfClones = group(true, Array.from({ length: 10 }, () => mesh(40)));
  check('ten clones of one geometry count ten times', visibleVertices(forestOfClones), 400);
  //   a node whose geometry has no position attribute contributes 0
  check('geometry without a position attribute is 0',
    visibleVertices({ visible: true, geometry: { attributes: {} } }), 0);

  // --- tierCounts ---------------------------------------------------------
  // Rule: read the STANDING url. It counts as `low` only when it is the low
  // variant AND that url differs from the full one; no mesh counts for
  // neither tier.
  console.log('perfstats — which tier is standing');
  const both = { full: 'a.glb', low: 'b.glb' };
  check('the low url counts as low',
    tierCounts([{ variants: both, url: 'b.glb' }]), { full: 0, low: 1 });
  check('the full url counts as full',
    tierCounts([{ variants: both, url: 'a.glb' }]), { full: 1, low: 0 });
  check('a model without a low variant counts as full',
    tierCounts([{ variants: { full: 'a.glb' }, url: 'a.glb' }]), { full: 1, low: 0 });
  //   a "low" that resolves to the same file never got cheaper — it must not
  //   pad the low column, or the display would hide the meshes still to shrink
  check('a low variant identical to full counts as full',
    tierCounts([{ variants: { full: 'a.glb', low: 'a.glb' }, url: 'a.glb' }]),
    { full: 1, low: 0 });
  check('only a low variant authored counts as low',
    tierCounts([{ variants: { low: 'b.glb' }, url: 'b.glb' }]), { full: 0, low: 1 });
  check('a placeholder without a mesh counts for neither',
    tierCounts([{ variants: both, url: '' }]), { full: 0, low: 0 });
  check('a mixed scene adds up', tierCounts([
    { variants: both, url: 'b.glb' }, { variants: both, url: 'b.glb' },
    { variants: both, url: 'a.glb' }, { variants: { full: 'c.glb' }, url: 'c.glb' },
    { variants: both, url: '' },
  ]), { full: 2, low: 2 });

  // --- Speech bubbles (stage 6; client3d/src/game/bubble.ts) ---------------
  //
  // Every number here is derived BY HAND from the constants in that module:
  //   BUBBLE_MAX_CHARS = 140, BUBBLE_BASE_MS = 3500,
  //   BUBBLE_MS_PER_CHAR = 55, BUBBLE_MAX_MS = 12000
  // so   bubbleMs(n chars) = clamp(3500 + 55n, 3500, 12000),
  // which reaches the ceiling at  55n = 8500  ->  n = 154.5454...,
  // i.e. the FIRST length that clamps is 155 characters.
  console.log('\nbubble — what is shown');
  const { bubbleText, bubbleMs, BUBBLE_MAX_CHARS, BUBBLE_BASE_MS,
    BUBBLE_MS_PER_CHAR, BUBBLE_MAX_MS } = bubble;
  check('the constants are the ones this block computes with',
    [BUBBLE_MAX_CHARS, BUBBLE_BASE_MS, BUBBLE_MS_PER_CHAR, BUBBLE_MAX_MS],
    [140, 3500, 55, 12000]);
  check('a short line passes through unchanged', bubbleText('Yes.'), 'Yes.');
  check('surrounding whitespace goes', bubbleText('  Yes.  '), 'Yes.');
  //   a pasted line break must not make the bubble three lines tall
  check('inner whitespace collapses to single spaces',
    bubbleText('one\n\ntwo   three\tfour'), 'one two three four');
  check('whitespace only yields the empty string (caller shows nothing)',
    bubbleText('   \n  '), '');
  //   exactly at the cap: 140 'a' -> untouched, no ellipsis
  const a140 = 'a'.repeat(140);
  check('140 characters are still shown in full', bubbleText(a140), a140);
  check('...and that really is 140 characters', bubbleText(a140).length, 140);
  //   one over the cap: cut to 139 + the ellipsis = 140 rendered characters
  const a141 = 'a'.repeat(141);
  check('141 characters are cut', bubbleText(a141), `${'a'.repeat(139)}…`);
  check('the ellipsis counts towards the cap', bubbleText(a141).length, 140);
  //   the cut must not leave a dangling space in front of the ellipsis:
  //   139 chars of "b"*138 + " " -> trimEnd -> 138 + ellipsis = 139 long
  const spaceAt139 = `${'b'.repeat(138)} ${'c'.repeat(20)}`;
  check('a cut on a space does not leave one hanging',
    bubbleText(spaceAt139), `${'b'.repeat(138)}…`);

  console.log('\nbubble — how long it hangs');
  //   3500 + 55*4 = 3720
  check('short line: 3500 + 55*4', bubbleMs('Yes.'), 3720);
  //   the empty line never reaches the scene, but the floor must still hold
  check('nothing to say is still the base', bubbleMs(''), 3500);
  //   100 chars: 3500 + 5500 = 9000
  check('100 characters: 3500 + 5500', bubbleMs('x'.repeat(100)), 9000);
  //   154 chars: 3500 + 8470 = 11970 — the last value BELOW the ceiling
  check('154 characters stay just under the ceiling',
    bubbleMs('x'.repeat(154)), 11970);
  //   155 chars: 3500 + 8525 = 12025 -> clamped to 12000
  check('155 characters are the first to clamp',
    bubbleMs('x'.repeat(155)), 12000);
  check('a very long line clamps too', bubbleMs('x'.repeat(4000)), 12000);
  //   the duration is measured on the UNCUT line: 200 chars are shown as 140,
  //   but they took 200 characters' worth of time to say -> ceiling
  check('the duration counts what was SAID, not what is shown',
    bubbleMs('x'.repeat(200)), 12000);
  //   and it measures the COLLAPSED length, like bubbleText does:
  //   'a b' is 3 characters -> 3500 + 165 = 3665
  check('duration uses the collapsed length', bubbleMs(' a \n b '), 3665);

  // The admin's "show all locations" switch lives beside the audio prefs since
  // the veil was struck (contract v6 Nr. 8) — it was never about the veil, only
  // about which places the worldmap answers with. Pinned by hand like
  // PREFS_KEY: a stored switch must keep working across versions of this
  // client.
  console.log('prefs — the show-all switch key');
  check('the show-all pref key is the documented one',
    SHOW_ALL_KEY, 'av3d.showAllLocations');

  /**
   * --- Minimap (stage 5 task 3; on the METRE world since E4 task 2) ---------
   * `client3d/src/game/minimap.ts`
   *
   * `minimapLayout(bounds, sizePx)` — the WHOLE world frame (`world_bounds`,
   * § A12, in METRES) fitted into a square canvas, north up, no scrolling and
   * no zoom. "Contain" fit, so the longer axis decides the scale and the
   * shorter one is centred; unlike the old grid frame the extent is CONTINUOUS
   * (no `+1` — a frame from 0 to 200 is 200 m wide, not 201):
   *     cx = (min_x + max_x) / 2,   cz = (min_z + max_z) / 2
   *     w  = max(max_x - min_x, 10),  d = max(max_z - min_z, 10)   [MIN_SPAN]
   *     scale = min(sizePx / w, sizePx / d)              [px per METRE]
   *     offX  = sizePx / 2 - cx * scale
   *     offY  = sizePx / 2 - cz * scale
   * The offsets place the WORLD ORIGIN, so `worldToPx` takes the layout alone.
   * The 10 m floor exists because a world with one placed location has a
   * zero-wide extent, and dividing the canvas by it would give an infinite
   * scale; clamping the SPAN while centring on the MIDPOINT opens that window
   * symmetrically around the one thing that is placed.
   *   0..200 x 0..100 m, 160 px:  w 200, d 100
   *                        scale = min(0.8, 1.6) = 0.8
   *                        offX = 80 - 100*0.8 = 0
   *                        offY = 80 -  50*0.8 = 40
   *   0..100 x 0..200 m:   the transpose -> scale 0.8, offX 40, offY 0
   *  -40..160 x 0..100 m:  the same 200x100 frame, shifted; cx = 60
   *                        -> offX = 80 - 60*0.8 = 32, offY = 40
   *   5..5 x 5..5 m:       one point; w = d = 10 -> scale 16,
   *                        offX = 80 - 5*16 = 0, offY = 0
   *   0..4 x 0..100 m:     only x is under the floor; w = 10, d = 100
   *                        -> scale = min(16, 1.6) = 1.6
   *                        offX = 80 - 2*1.6 = 76.8, offY = 80 - 50*1.6 = 0
   *   bounds null:         nothing placed at all -> scale 0 and the canvas
   *                        centre as the offset, so nothing is drawn.
   *
   * `worldToPx(p, layout)` — a world point in canvas pixels:
   *     px = offX + x * scale,   py = offY + z * scale
   * py grows with the world's z, and north is -z, so north is UP on the canvas
   * without any extra flip.
   *   0..200 x 0..100: (0,0)     -> (0 + 0,      40 + 0)      = (0, 40)
   *                    (200,100) -> (0 + 160,    40 + 80)     = (160, 120)
   *                    (100,50)  -> (0 + 80,     40 + 40)     = (80, 80)
   *  -40..160 x 0..100: (-40,0)  -> (32 - 32,    40 + 0)      = (0, 40)
   *                    — the left edge of a shifted frame lands on the very
   *                      same pixel as the unshifted one.
   *   5..5 x 5..5:     (5,5)     -> (0 + 80,     0 + 80)      = (80, 80)
   *                    — the lone point sits in the middle of the canvas.
   *
   * `yawToCompassDeg(yaw)` — THE SIGN, read off the code and not guessed:
   *   - `client3d/src/scene/engine.ts` puts the camera at
   *     `target + (sin yaw * cos pitch, ..., cos yaw * cos pitch) * dist`, so
   *     it LOOKS along `(-sin yaw, -cos yaw)` in XZ — the same forward vector
   *     `walkDir` uses (walk.ts: `fx = -sin yaw`, `fz = -cos yaw`).
   *   - north is -z and east is +x.
   *   A compass bearing (0 = north, clockwise) of a direction (dx, dz) is
   *   therefore `atan2(dx, -dz)`; substituting the forward vector gives
   *     atan2(-sin yaw, cos yaw) = -yaw.
   *   So the yaw runs COUNTER-clockwise on the compass:
   *     yawToCompassDeg(yaw) = (-yaw in degrees) normalised into [0, 360).
   *     yaw 0      -> 0   north   (fwd (0,-1) = -z)
   *     yaw pi/2   -> 270 west    (fwd (-1,0) = -x)
   *     yaw pi     -> 180 south   (fwd (0,+1) = +z)
   *     yaw 3pi/2  -> 90  east    (fwd (+1,0) = +x)
   *     yaw pi/4   -> 315 north-west — the camera's DEFAULT heading
   *     yaw -pi/2  -> 90, yaw 2pi -> 0, yaw 5pi/2 -> 270 (wraps like pi/2)
   *
   * `terrainColor(kind, colors)` — a LOOKUP in the world's own terrain catalog
   * (`/play/terrain -> types[].color`), no palette of the client's own. The
   * regular-expression table this replaced was a second source of truth for
   * something the world already declares per kind, and it could not know a
   * kind invented an hour ago. The map is keyed by the LOWER-CASED kind, the
   * input is lower-cased and trimmed before the lookup, and anything the
   * catalog does not carry — an unknown kind, the empty string, an entry with
   * an empty colour — is the ONE neutral grey `#888888`, the same fallback the
   * server writes for a type without a colour (`terrain_types.DEFAULT_COLOR`).
   * A `Map` and a plain object are both accepted; `main.ts` builds a `Map`.
   *
   * `locationsSignature(locations)` — the REDRAW key of the dots (E5 task 2).
   * The publisher in `main.ts` redraws only when its signature changes, and
   * the places entered that signature by their COUNT alone. A count answers
   * "has one been discovered" and never "has one moved" — since the seamless
   * world a location can be dragged to another metre without the list growing,
   * and the dot then stayed at the old spot until a step or an orbit happened
   * to move the signature. Id AND point, `id:x,z` joined with ';':
   *
   *   [ {mill, 10, 20}, {barn, 30, 40} ]  -> "mill:10,20;barn:30,40"
   *   the SAME two with the mill at 11    -> "mill:11,20;barn:30,40"   differs
   *   the same two in the other order     -> "barn:30,40;mill:10,20"   differs
   *     (order is the payload's; a reordered list redraws once, which is
   *      cheaper than sorting every poll)
   *   one place renamed to another id at the very same metre -> differs, and
   *     must: the dot means a different place, with a different tooltip
   *   an UNPLACED one (pos null) -> "ghost:null,null", its own state — no dot
   *     is drawn, and a place that gets a position has to bring one back
   *
   * `footprintSignature(loc)` — the same lesson for the TILE (finding B13).
   * A tile is built from the location ROW (§ A1.1): centre `pos_x`/`pos_z`,
   * rotation `yaw_deg`, the derived bounding-box width `plan_width_m` and —
   * since contract v6 — THE DRAWN OUTLINE `boundary`. None of them is in
   * `map3d` on that row, so the layout signature that watches `map3d` and the
   * room layouts is blind to all of them, and a place moved, turned or
   * RESHAPED in the world editor kept its tile at the old metres in a running
   * client while the server judged walking and entering against the new
   * footprint. Joined as `x,z,yaw,width,outline` with the outline written as
   * `x z` pairs separated by spaces:
   *
   *   {10, 20, yaw 0, width 8, no outline} -> "10,20,0,8,undefined"
   *   the same place at x = 11             -> "11,20,0,8,undefined"  (a drag)
   *   the same place at yaw 90             -> "10,20,90,8,undefined" (a turn)
   *   the same place at width 12           -> "10,20,0,12,undefined" (a resize)
   *   with the square outline drawn        -> "10,20,0,8,-4 -4 4 -4 4 4 -4 4"
   *   THE RESHAPE THE OLD SIGNATURE MISSED: pulling the corner (4, 4) in to
   *     (2, 2) keeps the bounding box — and therefore `plan_width_m` — at
   *     exactly 8, so the four numbers alone read as "nothing changed"; with
   *     the points in it is "10,20,0,8,-4 -4 4 -4 2 2 -4 4" and differs
   *   nothing changed            -> the same string (no rebuild per poll)
   *   an UNPLACED one            -> "null,null,undefined,null,undefined" — its
   *     own state, and never a tile at the origin
   *   []                                  -> ""
   */
  console.log('\nminimap — the whole METRE frame, contain-fitted, north up');
  const MM_BOUNDS = { min_x: 0, min_z: 0, max_x: 200, max_z: 100 };
  const mmWide = minimapLayout(MM_BOUNDS, 160);
  check('a 200x100 m frame in 160 px scales by 0.8 and centres 80 px of depth',
    mmWide, { scale: 0.8, offX: 0, offY: 40 });
  check('the transposed 100x200 m frame centres in x instead',
    minimapLayout({ min_x: 0, min_z: 0, max_x: 100, max_z: 200 }, 160),
    { scale: 0.8, offX: 40, offY: 0 });
  const mmNeg = minimapLayout({ min_x: -40, min_z: 0, max_x: 160, max_z: 100 }, 160);
  check('a frame starting at -40 m absorbs its origin into offX',
    mmNeg, { scale: 0.8, offX: 32, offY: 40 });
  const mmDot = minimapLayout({ min_x: 5, min_z: 5, max_x: 5, max_z: 5 }, 160);
  check('a single placed point opens the 10 m minimum window around itself',
    mmDot, { scale: 16, offX: 0, offY: 0 });
  check('the floor applies per axis, the longer one still decides the scale',
    minimapLayout({ min_x: 0, min_z: 0, max_x: 4, max_z: 100 }, 160),
    { scale: 1.6, offX: 76.8, offY: 0 }, 1e-12);
  check('nothing placed -> nothing to draw',
    minimapLayout(null, 160), { scale: 0, offX: 80, offY: 80 });

  console.log('minimap — world metres in canvas pixels');
  check('the frame corner sits on the canvas edge',
    worldToPx({ x: 0, z: 0 }, mmWide), { px: 0, py: 40 });
  check('the far corner of the frame',
    worldToPx({ x: 200, z: 100 }, mmWide), { px: 160, py: 120 });
  check('the middle of the world is the middle of the canvas',
    worldToPx({ x: 100, z: 50 }, mmWide), { px: 80, py: 80 });
  check('a shifted frame puts its left edge on the same pixel',
    worldToPx({ x: -40, z: 0 }, mmNeg), { px: 0, py: 40 });
  check('the lone point of a degenerate frame lands in the centre',
    worldToPx({ x: 5, z: 5 }, mmDot), { px: 80, py: 80 });

  console.log('minimap — yaw to compass bearing (0 = north, clockwise)');
  check('yaw 0 looks north', yawToCompassDeg(0), 0);
  check('yaw pi/2 looks west', yawToCompassDeg(Math.PI / 2), 270);
  check('yaw pi looks south', yawToCompassDeg(Math.PI), 180);
  check('yaw 3pi/2 looks east', yawToCompassDeg(3 * Math.PI / 2), 90);
  check('the camera default pi/4 looks north-west',
    yawToCompassDeg(Math.PI / 4), 315);
  check('a negative yaw wraps into [0,360)', yawToCompassDeg(-Math.PI / 2), 90);
  check('a full turn is north again', yawToCompassDeg(2 * Math.PI), 0);
  check('more than a full turn wraps like the first',
    yawToCompassDeg(5 * Math.PI / 2), 270);

  console.log('minimap — terrain colours come from the world catalog');
  // A catalog as `/play/terrain` delivers it, lower-cased keys. The values are
  // deliberately NOT the shared seed's: what is checked is the LOOKUP, and a
  // check that repeated the seed file would pass even if the lookup were gone.
  const MM_COLORS = new Map([['grass', '#123456'], ['water', '#abcdef'],
    ['blank', '']]);
  check('a known kind gets its catalog colour',
    terrainColor('grass', MM_COLORS), '#123456');
  check('another one', terrainColor('water', MM_COLORS), '#abcdef');
  check('the input is lower-cased before the lookup',
    terrainColor('Grass', MM_COLORS), '#123456');
  check('…and trimmed', terrainColor('  water  ', MM_COLORS), '#abcdef');
  check('a plain object works as well as a Map',
    terrainColor('grass', { grass: '#123456' }), '#123456');
  check('a kind the catalog does not carry is the neutral grey',
    terrainColor('marzipan', MM_COLORS), '#888888');
  check('an entry with an empty colour falls back too',
    terrainColor('blank', MM_COLORS), '#888888');
  check('the empty string is the fallback', terrainColor('', MM_COLORS), '#888888');
  check('undefined is the fallback', terrainColor(undefined, MM_COLORS), '#888888');
  check('an empty catalog paints everything grey',
    terrainColor('grass', new Map()), '#888888');
  //   pinned by hand like PREFS_KEY and SHOW_ALL_KEY above: a stored switch
  //   must keep working across versions of this client
  check('the minimap pref key is the documented one',
    MINIMAP_PREF_KEY, 'av3d.minimap');

  console.log('minimap — the dots\' redraw signature (id AND point)');
  const MM_PLACES = [{ id: 'mill', pos_x: 10, pos_z: 20 },
    { id: 'barn', pos_x: 30, pos_z: 40 }];
  check('id and point, joined',
    locationsSignature(MM_PLACES), 'mill:10,20;barn:30,40');
  // THE REGRESSION: same length, one place moved — a count could not tell.
  check('a place that MOVED changes it at the same length',
    locationsSignature([{ id: 'mill', pos_x: 11, pos_z: 20 }, MM_PLACES[1]]),
    'mill:11,20;barn:30,40');
  check('...and so does a move in z',
    locationsSignature([{ id: 'mill', pos_x: 10, pos_z: 21 }, MM_PLACES[1]]),
    'mill:10,21;barn:30,40');
  check('another place at the same metre is another dot',
    locationsSignature([{ id: 'forge', pos_x: 10, pos_z: 20 }, MM_PLACES[1]]),
    'forge:10,20;barn:30,40');
  check('the payload order is the signature order',
    locationsSignature([MM_PLACES[1], MM_PLACES[0]]), 'barn:30,40;mill:10,20');
  check('an unplaced location is its own state',
    locationsSignature([{ id: 'ghost', pos_x: null, pos_z: null }]),
    'ghost:null,null');
  check('a discovery still changes it, as the count did',
    locationsSignature([...MM_PLACES, { id: 'well', pos_x: 0, pos_z: 0 }]),
    'mill:10,20;barn:30,40;well:0,0');
  check('nothing known, nothing to draw', locationsSignature([]), '');

  console.log('minimap — the tile\'s rebuild signature (finding B13)');
  const FP = { id: 'mill', pos_x: 10, pos_z: 20, yaw_deg: 0, plan_width_m: 8 };
  check('centre, rotation and footprint width, joined',
    footprintSignature(FP), '10,20,0,8,undefined');
  check('an unchanged row is the same string (no rebuild per poll)',
    footprintSignature({ ...FP }), '10,20,0,8,undefined');
  check('a DRAG changes it',
    footprintSignature({ ...FP, pos_x: 11 }), '11,20,0,8,undefined');
  check('...and so does a drag in z',
    footprintSignature({ ...FP, pos_z: 21 }), '10,21,0,8,undefined');
  check('a TURN changes it',
    footprintSignature({ ...FP, yaw_deg: 90 }), '10,20,90,8,undefined');
  check('a RESIZE changes it',
    footprintSignature({ ...FP, plan_width_m: 12 }), '10,20,0,12,undefined');
  // The OUTLINE is in it since contract v6 (v6 Nr. 1): a place can be redrawn
  // without its bounding box moving at all, and the four numbers alone would
  // never notice.
  const SQUARE = [[-4, -4], [4, -4], [4, 4], [-4, 4]];
  check('the drawn outline goes in as its points',
    footprintSignature({ ...FP, boundary: SQUARE }),
    '10,20,0,8,-4 -4 4 -4 4 4 -4 4');
  check('a RESHAPE that keeps the bounding box still changes it',
    footprintSignature({ ...FP, boundary: [[-4, -4], [4, -4], [2, 2], [-4, 4]] }),
    '10,20,0,8,-4 -4 4 -4 2 2 -4 4');
  // The name is not geometry: renaming a place must not tear its tile down.
  check('a rename does NOT change it',
    footprintSignature({ ...FP, name: 'Mill of the North' }), '10,20,0,8,undefined');
  check('an unplaced location is its own state',
    footprintSignature({ id: 'ghost', pos_x: null, pos_z: null, plan_width_m: null }),
    'null,null,undefined,null,undefined');

  /**
   * --- WHAT A SEEDED SLICE WOULD DRAW (acceptance finding B6, "shows
   * nothing") -------------------------------------------------------------
   *
   * The finding could not say whether the map was BROKEN or merely covered, so
   * the picture of a small painted world is derived here by hand — pixel by
   * pixel, out of the same two functions `Minimap.tsx` strokes with.
   *
   * The world: two placed locations, (0, 0) and (160, 60), and a 40 x 40 m
   * rock square painted around the first one. `world_bounds` over both
   * footprints (10 m edges, so ±5 m) is x ∈ [-5, 165], z ∈ [-5, 65].
   *
   *   w = 170, d = 70  ->  scale = min(160/170, 160/70) = 0.9411764705882353
   *   cx = 80, cz = 30 ->  offX = 80 - 80·scale = 4.705882352941174
   *                        offY = 80 - 30·scale = 51.76470588235294
   *
   * Every number below follows from those three.
   */
  console.log('minimap — what a two-location painted world actually draws');
  const B6_BOUNDS = { min_x: -5, min_z: -5, max_x: 165, max_z: 65 };
  const b6 = minimapLayout(B6_BOUNDS, 160);
  check('the frame of the seeded world', b6,
    { scale: 160 / 170, offX: 80 - 80 * (160 / 170), offY: 80 - 30 * (160 / 170) }, 1e-12);
  //   the two location dots (radius 2.5 px each)
  check('the first place lands well inside the canvas',
    worldToPx({ x: 0, z: 0 }, b6), { px: 4.705882352941174, py: 51.76470588235294 }, 1e-9);
  check('the second one 150.6 px to the right of it',
    worldToPx({ x: 160, z: 60 }, b6), { px: 155.29411764705884, py: 108.23529411764706 }, 1e-9);
  //   the painted square: corners (-20,-20) and (20,20)
  const b6a = worldToPx({ x: -20, z: -20 }, b6);
  const b6b = worldToPx({ x: 20, z: 20 }, b6);
  check('the painted square starts off the left edge',
    b6a, { px: -14.117647058823529, py: 32.94117647058823 }, 1e-9);
  check('…and ends 37.6 px further in both axes',
    b6b, { px: 23.529411764705884, py: 70.58823529411765 }, 1e-9);
  check('so the fill covers 37.6 px of the 160 px canvas',
    b6b.px - b6a.px, 40 * (160 / 170), 1e-12);
  // VERDICT: two dots 150 px apart and a 37.6 x 37.6 px filled square — the
  // projection is sound and a painted world is NOT drawn empty. What the
  // finding saw is the overlap: `.info-panel` (z 10) and the minimap (inside
  // #hud, z 20) share the top-right corner, so the map's own dark backdrop sat
  // on the panel and each hid the other's content. The CSS dodge in hud.css
  // separates them; nothing in these functions needed fixing.

  /**
   * --- PLACEMENT: where a figure is drawn, and whether it walks there -------
   * (`client3d/src/game/placement.ts`, acceptance findings B2 + B5)
   *
   * `placementOf(hasTile, pos)`: a tile places the figure; without one the
   * free metre point does; without either there is nothing to draw. THE POINT
   * OF IT is the wilderness — `location_id: ""` has been a legal state since
   * E1, and the figure list used to drop those characters, which took the
   * player's own figure off the map mid-walk.
   */
  console.log('\nplacement — tile, free point or nothing at all');
  check('a character on a built tile is placed by the tile',
    placementOf(true, { x: 12, z: 34 }), { kind: 'tile' });
  check('…even without a point of its own',
    placementOf(true, null), { kind: 'tile' });
  check('WILDERNESS: no tile but a point = a standing figure there',
    placementOf(false, { x: 12.5, z: -3.25 }),
    { kind: 'free', pos: { x: 12.5, z: -3.25 } });
  check('the origin is a point like any other (0 is not "missing")',
    placementOf(false, { x: 0, z: 0 }), { kind: 'free', pos: { x: 0, z: 0 } });
  check('no tile and no point: nothing to draw',
    placementOf(false, null), { kind: 'offmap' });
  check('an absent point is the same answer',
    placementOf(false, undefined), { kind: 'offmap' });
  check('a non-finite coordinate is not a place',
    placementOf(false, { x: NaN, z: 0 }), { kind: 'offmap' });
  check('…nor is an infinite one',
    placementOf(false, { x: 0, z: Infinity }), { kind: 'offmap' });

  /**
   * `figureTransition(prev, next)`: SNAP on a visibility change, ROUTE on a
   * room change, STAY otherwise. The finding (B5) is the first line of the
   * table: opening the detail view flipped the drawn room from null to the
   * room the character had been standing in all along, and the door routing
   * read that as "it just walked in" — from the outdoor huddle spot, through
   * the front door, into the room it never left.
   */
  console.log('placement — snap on a view change, route on a room change');
  const SHOWN = (room, interiorShown) => ({ room, interiorShown });
  check('the FIRST placement of a figure never walks',
    figureTransition(null, SHOWN('hall', true)), 'snap');
  check('…and undefined is the same "nothing drawn yet"',
    figureTransition(undefined, SHOWN(null, false)), 'snap');
  check('VIEW OPENS: outside/closed -> in its room = snap, not a walk',
    figureTransition(SHOWN(null, false), SHOWN('hall', true)), 'snap');
  check('VIEW CLOSES: in its room -> the outdoor spot = snap as well',
    figureTransition(SHOWN('hall', true), SHOWN(null, false)), 'snap');
  check('a real room change inside the open view routes through the door',
    figureTransition(SHOWN('hall', true), SHOWN('kitchen', true)), 'route');
  check('room -> ground inside the open view routes too (the outside door)',
    figureTransition(SHOWN('hall', true), SHOWN(null, true)), 'route');
  check('…and ground -> room the same way back',
    figureTransition(SHOWN(null, true), SHOWN('hall', true)), 'route');
  check('nothing changed: whatever the figure is doing keeps running',
    figureTransition(SHOWN('hall', true), SHOWN('hall', true)), 'stay');
  check('standing outside a closed interior is just as quiet',
    figureTransition(SHOWN(null, false), SHOWN(null, false)), 'stay');
  // The same room means the same placement, whatever the view does — a figure
  // crossing the open GROUND of a tile must not be teleported onto its spot
  // because somebody opened the detail view (review finding, fix round 2).
  check('a GROUND figure is not snapped when the view opens over it',
    figureTransition(SHOWN(null, false), SHOWN(null, true)), 'stay');
  check('…nor when it closes again',
    figureTransition(SHOWN(null, true), SHOWN(null, false)), 'stay');
  check('a figure inside a room the view keeps showing stays put too',
    figureTransition(SHOWN('hall', false), SHOWN('hall', true)), 'stay');
  check('a visibility change wins even when the room changes with it',
    figureTransition(SHOWN('hall', false), SHOWN('kitchen', true)), 'snap');

  console.log('\nground — which ray hit counts as walkable (finding B8)');
  const { walkCeiling, acceptsWalkHit, ROOF_CLEARANCE_M } = ground;
  check('the clearance is the old constant', ROOF_CLEARANCE_M, 1.2);
  check('a building without a declared walk height keeps 1.2 m',
    walkCeiling({ display: 'shell' }), 1.2);
  check('…and so does a tile with no model info at all',
    walkCeiling(undefined), 1.2);
  check('a normal building measures from its walk_y_world 0.06',
    walkCeiling({ display: 'shell', walkY: 0.06 }), 1.26);
  check('a building on a plinth carries the clearance up with it',
    walkCeiling({ display: 'shell', walkY: 3.2 }), 4.4);
  // `check` compares numbers with a tolerance, and Infinity − Infinity is
  // NaN — so the unbounded ceiling is asserted as the identity it is.
  check('an AREA model is not capped at all',
    walkCeiling({ display: 'ground', walkY: 0 }) === Infinity, true);
  check('…the detail-mode area model just the same',
    walkCeiling({ display: 'shell_area' }) === Infinity, true);
  const SHELL = { display: 'shell', walkY: 0.06 };
  const LAKE = { display: 'ground', walkY: 0 };
  check('building: the ground skin at the entrance is walkable',
    acceptsWalkHit(SHELL, 0.2), true);
  check('building: a roof hit at 3 m is rejected',
    acceptsWalkHit(SHELL, 3), false);
  check('building: the ceiling itself is already roof (strict <)',
    acceptsWalkHit(SHELL, 1.26), false);
  check('building: a hand below it still counts',
    acceptsWalkHit(SHELL, 1.25), true);
  check('area: the raised shore at 3 m is walkable',
    acceptsWalkHit(LAKE, 3), true);
  check('area: the water surface at 0.2 m as well',
    acceptsWalkHit(LAKE, 0.2), true);
  check('area: the Mondscheinsee upper edge (2.69 m) too',
    acceptsWalkHit(LAKE, 2.69), true);
  check('area: and the lake bed below zero (−0.8 m)',
    acceptsWalkHit(LAKE, -0.8), true);

  console.log('\nground — ONE floor: the recipe plate the props stand on');
  const { recipeFloorAt, WALK_CLEARANCE_M } = ground;
  // The payload of "Haus von Kai" (worlds/Anima Divide, GET /play/locations/
  // 20dc0cbd/scene), plates verbatim — the hulls are the outlines it ships.
  const KAI_PLATES = [
    { top: 0.08, outline: [[-4.5, -4.5], [6, -4.5], [6, 1.5], [-0.5, 1.5],
      [-0.5, 6], [-4.5, 6], [-4.5, -1], [-6.22, -1], [-6.25, -3.11],
      [-4.53, -3.13]] },
    { top: 2.88, outline: [[-4.5, -4.5], [6, -4.5], [6, 1.5], [-0.5, 1.5],
      [-0.5, 6], [-4.5, 6], [-4.5, -1], [-6.22, -1], [-6.25, -3.11],
      [-4.53, -3.13]] },
    { top: 0.10, outline: [[6, -4.5], [6, 1.5], [-4.5, 1.5], [-4.5, -1],
      [-6.22, -1], [-6.25, -3.11], [-4.53, -3.13], [-4.5, -4.5]] },
    { top: 2.90, outline: [[-6.25, -3.11], [-4.53, -3.13], [-4.5, -4.5],
      [6, -4.5], [6, 1.5], [-0.5, 1.5], [-4.5, 1.5], [-4.5, -1],
      [-6.22, -1]] },
    { top: 0.00, outline: [[1.22, 3.12], [6.22, 3.12], [6.22, 6.12],
      [1.22, 6.12]] },
    { top: 0.10, outline: [[-0.5, 6], [-4.5, 6], [-4.5, 1.5], [-0.5, 1.5]] },
  ];
  // walk_y_world −0.22 (0.08 + offset_y −0.30) + ROOF_CLEARANCE 1.2.
  const KAI_CEILING = walkCeiling({ display: 'shell', walkY: -0.22 });
  check('the ceiling of that building is 0.98', KAI_CEILING, 0.98, 1e-9);
  check('living room: the ROOM plate wins over the level plate under it',
    recipeFloorAt(KAI_PLATES, 0.75, -1.5, KAI_CEILING), 0.10);
  check('kitchen: its own plate, same height',
    recipeFloorAt(KAI_PLATES, -2.5, 3.75, KAI_CEILING), 0.10);
  // The lift alcove (x −6.25…−4.5, z −3.11…−1) is DRAWN INTO the living
  // room's hull, so it is that room's floor — and with it the house contour
  // is exactly living room + kitchen, with no gap between them. Hence the
  // level plate is proven on a synthetic pair below rather than here.
  check('the lift alcove belongs to the living room hull, so 0.10',
    recipeFloorAt(KAI_PLATES, -5.8, -2.0, KAI_CEILING), 0.10);
  const GAP_PLATES = [
    { top: 0.08, outline: [[-5, -5], [5, -5], [5, 5], [-5, 5]] },
    { top: 0.10, outline: [[-4, -4], [0, -4], [0, -1], [-4, -1]] },
  ];
  check('inside the room: its plate (0.10)',
    recipeFloorAt(GAP_PLATES, -2, -2, 1.2), 0.10);
  check('inside the house but in no room: the storey contour (0.08)',
    recipeFloorAt(GAP_PLATES, 2, 2, 1.2), 0.08);
  check('the pool is an outdoor room and IS a floor at 0.00',
    recipeFloorAt(KAI_PLATES, 3.7, 4.6, KAI_CEILING), 0.00);
  check('on the plot but outside the house: no plate, the mesh answers',
    recipeFloorAt(KAI_PLATES, 6.9, -6.5, KAI_CEILING), null);
  check('the storey above is out of reach (2.90 >= 0.98)',
    recipeFloorAt(KAI_PLATES, 0.75, -1.5, KAI_CEILING) < 2.88, true);
  check('...and with a ceiling above it, it IS the floor (upper storey)',
    recipeFloorAt(KAI_PLATES, 0.75, -1.5, 4.0), 2.90);
  check('no plates at all = no recipe floor', recipeFloorAt([], 0, 0, 1.2), null);
  check('...and neither does a tile that never got a list',
    recipeFloorAt(undefined, 0, 0, 1.2), null);
  // THE CHAIN, hand-derived (§ B1/B2 addendum): socle < level <= room plate,
  // and a figure stands exactly where the room's props stand.
  const SOCLE_Y_M = 0.045;          // client `scene/tiles.SOCLE_Y_M`
  const PROP_BOTTOM = 0.11;         // server: room plate 0.10 + PROP_CLEARANCE
  const roomFloor = recipeFloorAt(KAI_PLATES, 0.75, -1.5, KAI_CEILING);
  check('the walk clearance IS the server\'s prop clearance', WALK_CLEARANCE_M, 0.01);
  check('socle 0.045 < level plate 0.08 <= room plate 0.10',
    SOCLE_Y_M < 0.08 && 0.08 <= roomFloor, true);
  check('figure and chair stand at ONE height: plate + 0.01 = 0.11',
    roomFloor + WALK_CLEARANCE_M, PROP_BOTTOM, 1e-9);
  // The regression pin: the mesh answer the same point used to give.
  const MESH_FLOOR = 0.06 + (-0.30) + 0.240;    // old pin + pad = 0.000
  check('the OLD mesh answer was 0.010 — 0.090 under the plate, 0.035 under '
    + 'the grass',
    [MESH_FLOOR + WALK_CLEARANCE_M,
      roomFloor + WALK_CLEARANCE_M - (MESH_FLOOR + WALK_CLEARANCE_M),
      SOCLE_Y_M - (MESH_FLOOR + WALK_CLEARANCE_M)],
    [0.010, 0.100, 0.035], 1e-9);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(`\nsmoke_walk_math: ${e?.message || e}`);
  process.exit(1);
});
