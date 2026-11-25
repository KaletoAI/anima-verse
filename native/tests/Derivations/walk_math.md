# walk_math

- Origin: `client3d/scripts/smoke_walk_math.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/CollideVectorTests.cs`, `native/tests/FigurePlacementVectorTests.cs`, `native/tests/NpcWalkVectorTests.cs`, `native/tests/OverviewHudVectorTests.cs`, `native/tests/BridgeVectorTests.cs`, `native/tests/WalkControlVectorTests.cs`
- Vectors: `shared/test-vectors/collide.json`, `shared/test-vectors/figure_ground.json`, `shared/test-vectors/npc_ground.json`, `shared/test-vectors/overview_hud.json`, `shared/test-vectors/stairs.json`, `shared/test-vectors/walk_control.json`

## Derivation

```text
/**
 * Smoke check for the pure walking maths of the 3D client (plan-3d-game
 * stage 3, tasks 3 and 4) — `client3d/src/game/walk.ts` and
 * `client3d/src/game/clickmove.ts`.
 *
 * --- ghostCutY: the same gate, and the LINE it answers --------------------
 * WHY IT EXISTS. Every ghost site needs the pair "is it submerged" AND "at
 * which world Y does the second draw stop" — the ghost discards everything
 * above `uGhostCutY`, so a boolean is not enough. That pair used to be
 * written out as `submergedInWater(b, l) ? l : null` at each site, and since
 * the user decision of 2026-08-25 there are four of them and not two: the two
 * figure sites in `scene/npcs.ts`, the world props (`scene/worldProps.ts`,
 * mount + redrape) and the scene placements (`scene/sceneRecipe.ts`, mount +
 * reliftScene + tier swap). One function, so none of them can hand in the
 * GATED level, a boolean, or the bed.
 *
 * The table is the one above, read as a cut line — no new threshold, no new
 * rule. `base` is what the thing STANDS ON: a figure's bed, a world prop's
 * `worldPropBottom`, a scene placement's `tile.center.y + bottom_y + lift`.
 *
 * base 12.00, water null   -> null    (dry ground)
 * base 12.00, water 11.90  -> null    (mirror UNDER the base)
 * base 12.00, water 12.00  -> null    (exactly the waterline)
 * base 12.00, water 12.04  -> null    (4 cm)
 * base 12.00, water 12.05  -> 12.05   (5 cm: the rim ramp is up)
 * base 12.00, water 12.60  -> 12.60   (a crate on a knee-deep ford's bed)
 * base 12.00, water NaN    -> null    (a raster that knows nothing)
 *
 * --- Doorways (E3 acceptance "you cannot see the doors", rehung in B3) ---
 *
 * The server renders a door as a GAP in the wall segments, and a gap alone
 * does not read as a door — so `client3d/src/game/doors.ts` says where the
 * walk-through gaps are and main.ts lays a threshold quad into each.
 *
 * Until B3 this module DERIVED them: it recomputed every room opening
 * (edge clamp, `width_m × k`) and measured the building entrance back out
 * of the contour pieces (two colinear stretches exactly 0.8 m apart), for
 * which it carried six constants of its own. It now READS `doorways[]`
 * (plan-betreten-und-tueren.md § 4.1), the finished primitive the server
 * already cut its walls and its hull from. The consumer rule of § 4.1 is
 * "recompute NOTHING", so every number below is simply the payload's:
 *
 * mid    = at_world + origin      (origin = tile centre; the payload is
 * tile-local, the scene is not)
 * along  = along                  (unit direction of the wall)
 * width  = width_m                (CLEAR width, already clamped)
 * baseY  = base_y                 (foot of the wall the gap belongs to)
 * roomIds= rooms                  (2 = party wall, 1 = door to outside)
 *
 * The fixture below carries rooms/openings and contour walls that CONTRADICT
 * its doorways (a window, a room opening nobody cut, two contour pieces
 * exactly 0.8 m apart). None of it may show up: if a single marker came from
 * there, the derivation is back.
 *
 * d0  party wall r1|r2, mid (2,0),  along (0,1),  width 1,   base 0.10
 * d1  r1 to the outside, mid (-1,-2), along (1,0), width 1,  base 0.10
 * d2  r2 to the outside, mid (3,-2),  along (1,0), width 0.6, base 0.10
 * d3  party wall r2|r3, mid (5,-1), along (1,0),  width 0.9, base 0.10
 * d4  storey 1, room up, mid (0,2), along (1,0),  width 1,   base 2.30
 * d5  HULL door of the hallway (§ A13c), mid (0,-3), along (1,0),
 * width 1.2, base 0.10, rooms ['__floor__0'], outside, hull
 *
 * d5 is the case that has no room wall at all: a hallway is the complement
 * of its storey's rooms, so the door is cut out of the BUILDING OUTLINE and
 * `rooms[0]` is that wall-less corridor. For this module it is an outside
 * door like any other — which is the point of the checks below.
 * Its `outward_normal` [0,-1] is exactly `(along.z, -along.x)` of (1,0),
 * i.e. the room-door construction: the fixture does NOT exercise the
 * reversed-winding case, where the two come apart. Nothing is lost by that
 * here — the client never reads the field (the server pre-computes the
 * door-prop swing from it, § B1 "Woher `swing` kommt"), and the reversed
 * ring is hand-derived on the server side in `scripts/smoke_floor_rooms.py`
 * Part 8.
 *
 * Task 30 doorway decisions: roomDoor prefers the first outside entry, else
 * the first entry naming the room: r1 -> (-1,-2), r2 -> (3,-2), r3 ->
 * (5,-1), width .9; the hallway -> (0,-3), width 1.2. doorwayBetween
 * finds the first entry naming BOTH distinct rooms: r1/r2 -> (2,0), ids
 * [r1,r2]; r2/r3 -> (5,-1). Unknown, identical or unjoined ids -> null.
 * Origin (40,-20) adds to these points: (5,-1) -> (45,-21).
 * ghostCutY also keeps a jetty base 12 under level 13.5: depth 1.5 >= .05,
 * cut 13.5. Non-finite bases/levels are dry. For the scene placement,
 * -2-.28+2.335=.055; .30-.055=.245 -> .30, .09-.055=.035 -> null.
 * floatBodyY(bed,level,sink) is floatRootY(bed,level,sink)-sink; the existing
 * floatRootY hand table below supplies all 16 migrated root/body assertions.
 *
 * Task 30 SHARED VECTORS: npc_ground.json labels [30] refer to the
 * hand tables in this header under groundScope, terrainPace, groundSink,
 * sinkForState, floatRootY, wadeGate, ghostCutY, doorways and the elevator.
 * Existing inline derivations remain beside each migrated call site. Only
 * static inputs and hand expectations moved; counter-probes remain local.
 * The Value adapters select a property path from the function result.
 * Non-finite inputs use {"$number":"NaN"}; expectations stay finite.
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
 * --- fixed movement poses (design §5.1–5.3) -------------------------------
 * walk_run chooses walking/running by distance; walk always walks; swim uses
 * swimming/treading_water; crawl uses crawling/crawling_rest. Terrain values
 * are types, never clip names. Built scopes and invalid types become walk_run.
 * Only walk_run permits running. Missing pose fields use the seven public
 * defaults. Played kinds are matched before public kinds in reverse lookup.
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
 * --- floatRootY: the sink is measured from the MIRROR, not the bed (E4) ----
 * "Ein Boden" E4 (§ G4). Both depths above are still exactly what they were;
 * what changed is the surface they hang under. Until E4 that was the TERRAIN,
 * and since E1 a lake's bed is CARVED — `water_depth_m` defaults to 2 m — so a
 * swimmer over a 2 m bed hung 2.6 m under the water line and came out half
 * inside the grass plate of the bank (the user's screenshot, 2026-08-21).
 *
 *   floatRootY(groundY, waterLevel, sink) =
 *     waterLevel === null ? groundY : max(groundY + sink, waterLevel)
 *
 * and because the body reference is always `root − sink`, that reads
 * `body = max(groundY, waterLevel − sink)`: out of the water NOTHING changes,
 * in it the body hangs `sink` under the mirror and never below the bed it
 * would otherwise stand on. The crossover falls out of the `max` and is not a
 * second rule — the branches are equal where `groundY + sink = waterLevel`,
 * i.e. at a water DEPTH of exactly `sink`.
 *
 * With the world's own water seed and a mirror at L = 3.0, the MOVE depth
 * 0.35 (a swimmer's knee) and the IDLE depth 1.3 (a treader's foot):
 *
 *   depth  groundY  root(move)          root(idle)         body(move) body(idle)
 *   0.00   3.00     max(3.35, 3) = 3.35 max(4.3, 3) = 4.3  3.00       3.00
 *   0.35   2.65     max(3.00, 3) = 3.00 max(3.95,3) = 3.95 2.65       2.65
 *   1.30   1.70     max(2.05, 3) = 3.00 max(3.00,3) = 3.00 2.65       1.70
 *   2.00   1.00     max(1.35, 3) = 3.00 max(2.30,3) = 3.00 2.65       1.70
 *
 * — the swimmer crosses over at 0.35 m of water, the treader only at 1.30 m,
 * which is the whole point of two depths: a figure that is upright needs a
 * body length of water before it stops touching the bottom.
 *
 * `groundWaterLevel(level, scope)` is the exact twin of `groundSink`'s reach:
 * a tiled hall standing in a painted lake is a floor, so `'built'` answers
 * `null` and nobody floats inside it. The full shore/plane arithmetic is
 * `client3d/scripts/smoke_water_plane.mjs`.
 *
 * --- wadeGate: SWIMMING IS A DEPTH, NOT A KIND (W4c, 2026-08-23) ----------
 * The SECOND reach rule of the ground contract. Until now `meta.move_anim:
 * swim` played on every pixel of a water area — ankle-deep on the shore ramp
 * included — so a figure crossing a ford crawled through water at its shins.
 * The kind now says FROM WHICH DEPTH that word counts (`meta.swim_from_m`,
 * default 1 m), and the client measures the depth it already has:
 *
 *   depth = waterLevel − groundY
 *   depth ≥ swim_from_m -> SWIM: the word passes through unchanged
 *   depth <  swim_from_m -> WADE: `{anim:'', idle:'', sink:{0,0}, water:null}`
 *
 * All four fields are gated TOGETHER, and the mirror is the one that proves
 * why: zeroing the sink while leaving the level in would hand `floatRootY` a
 * `max(groundY, level)` and put the wader ON the water surface — the opposite
 * of standing in it.
 *
 * Derived with the river seed of `shared/terrain/types.json` (`swim_from_m`
 * 1.0, `move_sink_m` 0.35, `idle_sink_m` 1.3) and a mirror at L = 5.0. The
 * three depths asked for, moving and waiting, with the root that comes out of
 * `floatRootY(groundY, gated.water, sink)`:
 *
 *   depth  groundY  gate  moving: clip/sink/root      waiting: clip/sink/root
 *   0.4    4.6      wade  walk  / 0    / 4.60         (own idle) / 0    / 4.60
 *   1.0    4.0      swim  swim  / 0.35 / max(4.35,5)=5  treading / 1.3  / max(5.3,5)=5.3
 *   1.6    3.4      swim  swim  / 0.35 / max(3.75,5)=5  treading / 1.3  / max(4.7,5)=5
 *
 * — 1.0 is the threshold and is INCLUDED (`>=`), which is what makes the rule
 * a single line instead of a band; the waiting root at depth 1.0 sits ABOVE
 * the mirror because a treader whose foot hangs 1.3 m down still stands on a
 * 1.0 m bed, exactly as `floatRootY`'s own crossover table says.
 *
 * A kind that names NO threshold answers `SWIM_FROM_DEFAULT_M` = 1.0 through
 * `swimFrom`, so it reads the very same three rows; an authored 0 is kept and
 * means "swim from the very rim" — the behaviour every water kind had before
 * this round. A NON-WATER ground is untouched, and that is the case that keeps
 * the rule out of the rest of the world: with `water: null` there is no depth
 * to measure, so a bog's `move_sink_m` still swallows ankles.
 * RED COUNTER-PROBE, implemented below: the pre-W4c rule is "no gate at all",
 * i.e. the word passing through whatever the depth — it swims the 0.4 m ford.
 *
 * --- slopeBlocks: THE HEIGHT GATE (E8 task 1) -----------------------------
 * The client's half of the server rule of `POST /play/pos` § A15 Nr. 8, the
 * exact mirror of `relief.slope_blocks`. The SLOPE limit holds at every
 * distance, and below one metre the STEP limit holds ON TOP of it:
 *
 *   slopeBlocks(dh, dist, maxStep, maxSlope) =
 *     dh <= 0     -> false          (a DESCENT is never judged)
 *     otherwise   -> (dist < 1 && dh > maxStep)
 *                    || atan(dh / dist) * 180/pi > maxSlope
 *
 * ONLY A CLIMB IS JUDGED (user rule, 2026-08-28): `dh` is signed (target minus
 * the point one stands on) and every descent passes, however deep — walking
 * downhill is what a body does without asking. The accepted price: a figure
 * can drop somewhere it cannot climb back out of and be stranded there.
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
 *   dh -1.2, dist 0.5  -> a DROP is not judged                   -> free
 *   dh -0.9, dist 0.5  -> nor this one, though +0.9 over the same
 *                         0.5 m is a step twice the cap          -> free
 *   dh -3,   dist 1    -> three metres down, atan(3) = 71.5651 deg
 *                         as a climb, is walked down all the same -> free
 *   dh 0.9,  dist 0.5  -> the SAME rise UPWARDS: 0.9 > 0.4       -> blocked
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
 * The OPENING EXEMPTION (a point within 1.5 m of an authored opening is never
 * refused for its height — an opening is the ramp onto a plateau) stays in
 * `main.ts` `slopeBlockedBetween`. The server half is hand-derived in
 * `scripts/smoke_slope_gate.py`.
 *
 * --- [G1] gateStandY: THE HEIGHT THE GATE COMPARES (plan-huette-dach task 2)
 * `slopeBlocks` judges a DIFFERENCE, and until 2026-08-28 the client looked
 * that difference up on the terrain alone while the server looked it up on
 * the whole standing ladder (`model_surface.stand_height_at`, in the gate of
 * `POST /play/pos` since 165ccf61). The figure is DRAWN on the ladder, so it
 * walked up onto a hut's baked roof and the server refused every report.
 * `gateStandY` is that ladder as a rule, one point at a time — the three
 * rungs the server composes, in the server's order:
 *
 *   gateStandY(baked, declared, terrain) =
 *     baked    finite -> max(baked,    terrain)   rung 0, the baked lattice
 *     declared finite -> max(declared, terrain)   rung 1, a room's walk_y
 *     otherwise       -> terrain                  rung 2, the world ground
 *
 * All three are WORLD metres; the terrain is the lower bound of the upper two
 * (Entscheid 5: a hollow in a diorama never sinks a figure below the ground).
 * A non-finite rung is not a height and falls through to the next one, and a
 * terrain sampler with nothing to say leaves the upper rung standing.
 * THE STOREY PLATES ARE NOT A RUNG — the server's ladder has none (storey 0
 * draws no plate since E5a), so the gate's has none either; mirroring, not
 * extending. The three LOOKUPS stay in main.ts (`gateStandAt`: `bakedFloorAt`
 * with the storey-0 filter, `declaredFloorAt`, `terrainGround.heightAt`).
 *
 * BOTH UPPER RUNGS ARE STOREY-0 ONLY, and rung 1 needs a filter of its own:
 * `tile.declaredFloors` is the DRAWING list and carries every storey, while
 * the server's list is built from storey-0 rooms alone
 * (`model_surface._declarations`). `groundStoreyFloors(floors, levelOf)` is
 * that filter as a rule — a room whose level is unknown counts as storey 0,
 * the mirror of the server's `int(level or 0)` — and the two-storey house
 * below shows what it prevents.
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
 *  5. TWO storeys leave nothing to choose (Treppen v2 task 4): `elevatorOptions`
 *     returns exactly ONE storey, so the picker would be a single button.
 *     `elevatorSoleOption` names that storey and F rides it straight away;
 *     from the third storey on there is a choice again and the answer is null.
 *   sole option of {levels:[0,1], current:0}           -> 1 (up)
 *   sole option of {levels:[0,1], current:1}           -> 0 (down)
 *   sole option of {levels:[0,1,2], current:1}         -> null (two to choose)
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
 * Six stages: world, scenes, tiles, visible, figures, arrival. Step = 100/6.
 * [P1] In order: 0 -> 0/world, 1 -> 17/scenes (16.67 rounds up), 2 -> 33/tiles,
 * 3 -> 50/visible, 4 -> 67/figures, 5 -> 83/arrival, 6 -> 100/ready.
 * [P2] Out of order: figures alone -> 17/world; world+figures+tiles ->
 * 50/scenes; world+figures+scenes+arrival -> 67/tiles; all six reversed ->
 * 100/ready. [P3] Unknowns count zero: world+bogus -> 17/scenes,
 * bogus+other -> 0/world.
 * Attribution: A=[0,100], B=[50,300]; [60,160] -> B (40 vs 100);
 * [0,40] -> A (40 vs 0); [400,450] -> null. Tie [50,100] -> A:
 * both overlap by 50, but A started earlier.
 * The label is a STAGE NAME, not a sentence: the React side maps it to a
 * translated string via t(), so the pure module stays language-free. The store
 * on top of it (`reportBootStage` / `setBootNote` / `getBootState` /
 * `subscribeBoot`) publishes only on a REAL change — a stage reported twice
 * and an unchanged note must not wake the subscribers, or the retry loop
 * re-renders the screen once per attempt for nothing. The note is a value
 * (`{kind:'retry',seconds}` / `{kind:'failed'}`) for the same reason as the
 * label: the vanilla side has no t().
 *
 * --- Speech bubbles (stage 6; `client3d/src/game/bubble.ts`) ---------------
 * From the module's constants: BUBBLE_MAX_CHARS = 140, BUBBLE_BASE_MS = 3500,
 * BUBBLE_MS_PER_CHAR = 55, BUBBLE_MAX_MS = 12000, so
 *     bubbleMs(n chars) = clamp(3500 + 55n, 3500, 12000),
 * which reaches the ceiling at 55n = 8500 -> n = 154.5454..., i.e. the FIRST
 * length that clamps is 155 characters. What is shown:
 * [B1] 'Yes.' passes through unchanged.  [B2] surrounding whitespace goes.
 * [B3] inner whitespace collapses to single spaces: 'one\n\ntwo   three\tfour'
 *      -> 'one two three four' (a pasted line break must not make the bubble
 *      three lines tall).  [B4] whitespace only -> '' (the caller shows nothing).
 * [B5] exactly at the cap: 140 'a' -> untouched, no ellipsis.
 * [B6] one over: 141 'a' -> 139 'a' + '…' = 140 rendered characters.
 * [B7] the cut must not leave a dangling space in front of the ellipsis:
 *      138 'b' + ' ' + 20 'c' -> the first 139 characters end in the space ->
 *      trimEnd -> 138 'b' + '…'.
 * How long it hangs:
 * [B8] 'Yes.': 3500 + 55·4 = 3720.  [B9] '' -> the base 3500.
 * [B10] 100 chars: 3500 + 5500 = 9000.  [B11] 154: 3500 + 8470 = 11970, the
 *       last value BELOW the ceiling.  [B12] 155: 3500 + 8525 = 12025 -> 12000.
 * [B13] 4000 chars -> 12000.  [B14] the duration is measured on the UNCUT
 *       line: 200 chars are shown as 140 but took 200 characters to say -> 12000.
 * [B15] it measures the COLLAPSED length, like bubbleText: ' a \n b ' -> 'a b'
 *       = 3 characters -> 3500 + 165 = 3665.
 *
 * --- Location info panel (`client3d/src/game/infoPanel.ts`) ----------------
 * `infoPanelData(loc, chars, events, roomOf, view?, avatar?)` is a plain copy
 * of what the HUD shows; the fixture is the location Home with the rooms
 * r1 'Kitchen' and r2 'Hall', the characters A (travelling to Harbor, eta
 * 14:30), B and C, and roomOf A -> 'Kitchen' (a room NAME), B -> 'r2' (a room ID).
 * [I1] terrain 'forest' is an area: its rooms are generic zones -> rooms [].
 * [I2] map3d.area_model set -> rooms [] as well.
 * [I3] otherwise every room in the location's order with who matches its name
 *      OR its id: Kitchen [A] (by name), Hall [B] (by id); C is in no room.
 * [I4] present: every character in the given order, absent fields as '':
 *      A {travelTo 'Harbor', eta '14:30'}, B and C all ''.
 * [I5] events: danger iff category === 'danger' -> Fire true, News false.
 * [I6] no view given -> null.  [I7] no description -> ''.
 * [I8] a view is copied: {openable true, open false}.
 * [I9] the avatar elsewhere: L1 at (0, 0), avatar in L2 at (3, 4) -> distance
 *      hypot(3, 4) = 5.  [I10] the avatar IN this location -> travel null.
 *      [I11] no avatar -> travel null.  [I12] a location without pos_x/pos_z
 *      -> travel {distanceM: null} (the button stays, the number goes).
 *
 * --- Scatter detail distances: typing (`client3d/src/game/prefs.ts`) -------
 * The stored side of these prefs (defaults, reading) is pinned in
 * `smoke_scatter_math.mjs` section (J); what the menu asks before it stores
 * anything is here, beside the other prefs:
 * [J3] `checkScatterPrefs(near, far, cull)` — a value must be a finite NUMBER,
 *      it is clamped to 5..2000 m, and the triple must climb strictly:
 *        (20, 40, 300)      -> ok, taken as typed
 *        (3, 10, 50)        -> ok, the 3 clamped up to 5
 *        (40, 20, 300)      -> refused, 'order' — near is not under far
 *        (20, 40, 40)       -> refused, 'order' — equal is not ordered either
 *        (NaN, 45, 120)     -> refused, 'number' (an empty number field)
 *        ('30', 45, 120)    -> refused, 'number' (a string is not a number)
 *        (2500, 3000, 4000) -> refused, 'order': all three clamp to 2000 and
 *                              collide there, which is better told to the
 *                              player than silently drawn.
 * [J4] `scatterLodCfgOf` renames the stored fields into the cfg the LOD maths
 *      takes: {scatterNearM 20, scatterFarM 40, scatterCullM 300} ->
 *      {nearM 20, farM 40, cullM 300} (what that cfg then does is (J4) of
 *      `smoke_scatter_math.mjs`).
 *
 * --- SHARED VECTORS — `shared/test-vectors/figure_ground.json` -------------
 * The input -> value cases of [B2] `placementOf` and [B5] `figureTransition`
 * (derived in the PLACEMENT block of the body), [G1] `gateStandY`, [G2]
 * `standY` and [G3] `tileWalkLadder` (in this header) run from that file, which the
 * native client's C# tests read too (plan Task 29). A non-finite INPUT is
 * written `{"$number": "NaN" | "Infinity"}` and decoded by the dispatch; an
 * absent `placementOf` point is an omitted argument. WHAT STAYS INLINE: the
 * `undefined` previous placement of [B5] (JSON has no undefined; `null` is
 * the vector case) and every check that composes the rules with
 * `declaredFloorAt` / `groundStoreyFloors` / `slopeBlocks`.
 *
 * --- SHARED VECTORS — `shared/test-vectors/overview_hud.json` --------------
 * The input -> value cases of the four sections above run from that file,
 * which the native client's C# tests read too; each label starts with the
 * tag of its derivation. The `fn` names are the TypeScript ones. Two
 * conventions: `bootProgress` takes the finished stages as a LIST (the TS
 * function takes a Set), and `infoPanelData` takes `roomOf` as an OBJECT
 * name -> room (a Map in TS) and `null` for an absent view / avatar.
 * WHAT STAYS INLINE: the constants and BOOT_STAGES pins, string lengths,
 * the JSON round trip of the panel data, the NaN input of (J3), the boot
 * STORE (state across calls) and `attributeLongTask` (no C# consumer yet).
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
 * --- THE HEIGHT LADDER IS DATA-ONLY ("Ein Boden" E5b) ---------------------
 * `tileWalkY` used to have three rungs and a raycast at the bottom of them.
 * E5a took the storey-0 plates out of the payload and E5b takes the ray out of
 * the client, so what is left is two data rungs and the terrain:
 *
 *   1. a ROOM's declared `walk_y_world`  (`declaredFloorAt`)
 *   2. a DECLARED STOREY's plate         (`recipeFloorAt`, capped by
 *                                         `plateCeiling`)
 *   3. the TERRAIN                       (`heightAt`, via `standY`)
 *
 * `walkCeiling` and `acceptsWalkHit` are DELETED with the ray they judged.
 * They existed to tell a location model's ground skin from its roof (the
 * finding-B8 1.2 m mark, Infinity for an area model). An area model's walkable
 * surface is the number its spec declares, and where it declares none the
 * ground it was drawn over answers — there is no second surface left to sort
 * out. `plateCeiling` STAYS and now applies to every display alike: it is the
 * storey question, and an uncapped plate pick would hoist a ground-floor
 * figure onto the slab above it.
 *
 * --- [G3] tileWalkLadder: THE RUNG ORDER AS A RULE (Task 29) ---------------
 * `tiles.tileWalkY` asks its lookups (the storey-0 lattice, the declarations,
 * the plates) and hands the answers to `ground.tileWalkLadder(datumY, baked,
 * declared, plate)`, the first rung that answers winning. `baked` is already
 * WORLD metres; `declared` and `plate` are tile-local over the datum; the
 * clearance 0.01 goes on every drawn rung and never on the datum:
 *   (0.5, 1.2, 0.3, 2.9)       -> 1.2 + 0.01         = 1.21   rung 0 wins
 *   (0.5, null, 0.3, 2.9)      -> 0.5 + 0.3 + 0.01   = 0.81   rung 1 wins
 *   (0.5, null, 0, 2.9)        -> 0.5 + 0 + 0.01     = 0.51   0 is a VALUE
 *   (0.5, null, null, 2.9)     -> 0.5 + 2.9 + 0.01   = 3.41   rung 2
 *   (−0.3, null, null, −2.5)   -> −0.3 − 2.5 + 0.01  = −2.79  a basement
 *   (0.5, null, null, null)    -> 0.5                          the datum
 *
 * --- [G2] standY: THE TILE AND THE WORLD, THE HIGHER WINS -------------------
 * `standY(walkY, terrainY)` (ground.ts, user decision 2026-08-13) reconciles
 * the tile's answer above with the world ground. A non-finite tile answer
 * reads as 0; a non-finite world answer leaves the tile answer alone:
 *   (0.08, 0.18)  -> 0.18   the relief out-tops the hut's declaration
 *   (0.08, 0)     -> 0.08   on level ground the tile answers
 *   (−0.3, −0.8)  -> −0.3   max, whatever the sign
 *   (NaN, 1.4)    -> max(0, 1.4) = 1.4
 *   (NaN, −0.8)   -> max(0, −0.8) = 0    the docstring's own example
 *   (1.2, NaN)    -> max(1.2, 1.2) = 1.2
 *   (NaN, NaN)    -> 0
 *   (Infinity, 2) -> max(0, 2) = 2       Infinity is no height either
 *
 * --- THE HEADLINE OF E5: built and natural are ONE chain -------------------
 * § A16.9 of docs/schnittstellen-3d.md states the ladder in one line:
 *
 *     storey_floor_y(level, storey) = level·storey + (0 if level == 0 else 0.08)
 *
 * — that is the datum of the storey CONTOUR plate and of the yard on it. A
 * ROOM's own floor is drawn from the bare storey level plus what its plate
 * lays over it (`_plate_top`): 0 on storey 0, and on a DECLARED storey 0.10
 * (closed room) / 0.09 (zone) / 0.08 (yard). Storey 0 is the terrain, so both
 * columns of the old table collapse into one — derived by hand for "Haus von
 * Kai" (built) and "Mondscheinsee" (natural), storey 2.8 m:
 *
 *   quantity                      built, OLD    natural, OLD    BOTH, NEW
 *   floor stood on                0.10          0.01            0.00
 *   wall foot (room / contour)    0.10 / 0.08   —               0.00
 *   prop bottom_y                 0.11          0.02            0.01
 *   diorama bottom_y (no dial)    0.12          0.03            0.02
 *   doorstep without a declaration 0.10         —               0.00
 *   building walk_y_world         0.08 + off_y  0.00 + off_y    off_y
 *
 * The three old FLOOR numbers — 0.10, 0.09, 0.01 — are the red probes of this
 * file: on storey 0 not one of them may come out of the ladder any more. The
 * prop clearance 0.01 survives as a number, but as the PROP's anti-z-fight
 * hair over the ground, never as a floor.
 *
 * WHERE THE FIGURE STANDS ON STOREY 0 there is no `WALK_CLEARANCE_M` either,
 * and that is the same statement seen from the other side: outside a location
 * a figure walks at exactly `heightAt`, and inside one it now walks on that
 * very ground. So the sole is on the terrain and the chair's bottom face is
 * 1 cm over it — which is what `PROP_CLEARANCE` is for. The clearance is added
 * on the two DECLARED rungs only, where the floor is a drawn surface a sole
 * would otherwise sink into.
 *
 * --- THE PLATES THAT ARE LEFT ---------------------------------------------
 * `recipeFloorAt(plates, lx, lz, ceiling)` is unchanged and its list is not:
 * "Haus von Kai" ships exactly two plates now, both on storey 1 — the storey
 * contour at `1·2.8 + 0.08 = 2.88` and the bedroom at `1·2.8 + 0.10 = 2.90`.
 * Its building spec declares `walk_y_world = offset_y = −0.30`, so the storey
 * ceiling is `−0.30 + 1.2 = 0.90` and neither plate is in reach from the
 * ground floor: the answer there is `null`, and `null` means the terrain.
 *
 * --- AND ONE OF THEM CAN HAVE A HOLE (addendum "Treppen v2") --------------
 * A flight of stairs opens the floor it ARRIVES on: the plate carries the
 * ring in `holes`, the renderer takes it out of the shape, and the walk rule
 * has to make the same statement — a point inside a ring is not on that plate,
 * so the height falls through to the rung below it. Derived by hand from the
 * contract example further down ("THE STAIRWELL").
 *
 * --- THE STOREY CORRIDOR (§ A13b, 2026-09-09) -----------------------------
 * Every used storey owns a reserved corridor room, the complement of its
 * rooms — so stepping out of a room no longer means "no candidate at all".
 * `roomWalkCandidates` states the whole rule: a rectangle that holds the
 * figure wins; otherwise the figure is in its OWN storey's corridor, and only
 * on storey 0 does the outline decide between the hallway (inside the
 * building) and the ground (outside it). A corridor that is locked or absent
 * changes nothing — the old fall-through stands, and the cellar has no ground
 * to fall onto.
 * The same room is where the lift and the stairs open: `nearestRoomAt` gives
 * a storey's corridor precedence over every distance, because that is the
 * room you stand in when you step off a landing, whatever room centre happens
 * to be nearer.
 * WHICH CORRIDORS EXIST IS THE CALLER'S QUESTION (review 2026-09-09), not
 * this module's: `main.ts` answers `floorIdOf` only for a corridor the
 * mounted tile knows (`tile.roomLevels.has(id)`, i.e. one the payload's
 * `corridors[]` brought), because a storey without a resolvable footprint has
 * a STORED corridor and no entry. The pure rule is unchanged — an absent
 * corridor is the `floorIdOf: () => ''` case already checked below, and both
 * probes ("locked corridor", "no hallway -> ground") cover it.
 *
 * Task 31 stairs.json hand derivations (moved from the former inline checks):
 * [S1] chains; [S2] offers; [S3] height; [S4] leg selection;
 * [S5] ride sequence and radius; [S6] nearest room; [S7] the ride at any
 * frame rate (Task 35c).
 * --- stairs: the chain routes per storey (stairs task 4) -----------------
 * A staircase spans exactly ONE storey (`foot.level + 1 === head.level`), so
 * a storey change over stairs is a CHAIN: one flight per step of the storey
 * difference, and each flight contributes its NEAR end first, then its FAR
 * end. Missing a single link means there is no stair route at all — the
 * caller falls back to the lift, which is why the answer is `null` and not a
 * short chain that ends in mid-air.
 *
 * The two flights below are the § 0 hand calculation of the spec, house
 * storey 3.0, `dir_deg` 90 (climb along +X), and their endpoints are the
 * PAD TOP FACES + the 1 cm walk clearance that `tile.stairs` carries:
 *
 * A: at = [2, −2], from_level 0 → base = 0.0, target = 1·3.0 + 0.08 = 3.08
 * foot pad centre [2 − (0.9/2 + 0.05), −0.025, −2] = [1.5, −0.025, −2]
 * → top face −0.025 + 0.05/2 = 0.0, walk Y = 0.0 + 0.01 = 0.01
 * run = 15 · 0.26 = 3.9, head pad centre [2 + 3.9 + 0.5, 3.055, −2]
 * = [6.4, 3.055, −2] → top 3.055 + 0.025 = 3.08, walk Y = 3.09
 * B: at = [2, +2], from_level 1 → base = 3.08, target = 2·3.0 + 0.08 = 6.08
 * foot [1.5, 3.09, 2] (top 3.08), head [6.4, 6.09, 2] (top 6.08)
 * (a) one flight, upwards: the foot is where you get on, the head where
 * you get off.
 * (b) the same flight downwards is the same two points, mirrored.
 * (c) two flights, 0 → 1 → 2: four points, and the middle pair is the
 * landing — head of A at [6.4, 3.09, −2], foot of B at [1.5, 3.09, 2],
 * both on the storey-1 floor 3.08 + 0.01.
 * The list is UNORDERED — the payload order must not decide the route.
 * Two flights between the SAME storeys: the FIRST match wins, always.
 * (d) a gap: only 0 → 1 exists, so 0 → 2 has no stair route at all.
 * (e) no storey change = no waypoints, and that is NOT "no route".
 * A basement counts like any other storey.
 * --- stairs: the avatar's trigger and its target room (stairs task 5) -----
 * The player's way onto a flight is the same shape as the lift's
 * (`elevatorAt`): standing within reach of a landing OF ONE'S OWN STOREY
 * offers the ride, and the reach is FIGURE metres — `STAIR_RANGE * scale`,
 * because indoors a world metre is not a figure metre (at scale 0.3 the
 * 1.5 m reach is 0.45 world metres, and unscaled the offer would cover half
 * the room). The comparison is `dist < range`, exactly as `elevatorAt` has
 * it, so a figure standing ON the range circle is not yet at the stairs.
 *
 * The flight below is the § 0 hand calculation again (house storey 3.0,
 * `at = [2, −2]`, `dir_deg` 90): foot landing [1.5, 0.01, −2] on storey 0,
 * head landing [6.4, 3.09, −2] on storey 1.
 * The offer CARRIES the distance it was measured at (bug round 2026-08-30):
 * the F key answers the nearest of the four standing offers, and the reaches
 * differ in size (2.5 m to talk against 1.5 m here). The `dist` in every
 * expectation below is the plain distance to the landing STOOD AT, in world
 * metres — never to `dest`.
 * (a) 1.0 m from the foot landing, scale 1 → reach 1.5, and 1.0 < 1.5.
 * Standing at a FOOT means going UP, and the destination is the other
 * end of that flight — the head.
 * (b) 3.1 − 1.5 = 1.6 m away, still scale 1: 1.6 ≥ 1.5, no offer.
 * (c) scale 0.3 → reach 1.5 · 0.3 = 0.45 world metres. 2.0 − 1.5 = 0.5 m
 * is outside it, 1.9 − 1.5 = 0.4 m inside — the same half metre that
 * would be well within reach at scale 1.
 * (d) standing ON the head landing, on storey 1: the same flight read from
 * the other end — the way DOWN, destination the foot.
 * Only landings of ONE'S OWN storey count: standing on the foot landing
 * while the server has the avatar upstairs is not a stair offer (the head
 * is 4.9 m away, far outside the reach).
 * Several flights: the NEAREST landing wins. D's foot sits at x = 3.5, so
 * from x = 2.6 it is 0.9 m away and A's foot 1.1 m — both in reach, D is
 * closer, and its head is the destination.
 * A tie (x = 2.5 is 1.0 m from either foot) falls to the FIRST listed —
 * the payload order is arbitrary, but the pick must not flicker.
 * --- stairY: the height ON the run (plan-treppen-v2 task 3) --------------
 * The climb is no longer a blend towards the far landing but a RAMP along
 * the run: `y = foot.y + t · (head.y − foot.y)` with `t` the clamped
 * projection of the figure onto the run axis. The flight is the § 0 hand
 * calculation again, now with the run the payload ships (§ B1 `stairs`):
 *
 * at = [2, −2], dir = +x, run = 15 · 0.26 = 3.9, width = 1.2
 * foot = [1.5, 0.01, −2] on storey 0, head = [6.4, 3.09, −2] on storey 1
 * climb = 3.09 − 0.01 = 3.08
 *
 * so `t` is `(x − 2) / 3.9` and the height is `0.01 + t · 3.08`:
 * x = 2     → t = 0            → 0.01
 * x = 3.3   → t = 1.3/3.9 = ⅓  → 0.01 + 1.026666… = 1.036666…
 * x = 3.95  → t = 1.95/3.9 = ½ → 0.01 + 1.54 = 1.55
 * x = 5.9   → t = 3.9/3.9 = 1  → 3.09
 * x = 6.4   → t clamped to 1   → 3.09  (the head LANDING, 0.5 m past the run)
 * x = 1.0   → t clamped to 0   → 0.01  (a metre in front of the first tread)
 * ACROSS the axis the gate is half a step width, 1.2/2 = 0.6: the axis is
 * z = −2, so `across = z + 2` and −2.6 … −1.4 is on the flight, ±0.61 off it.
 * The gate across is `|across| > width/2`. The EDGE itself, `across` =
 * 0.6, is deliberately not pinned: `−1.4 + 2` is 0.6000000000000001 in
 * doubles, so which side of the gate the exact rim falls on is a float
 * coin-flip and no rule anybody could rely on. Half a tread inside and a
 * quarter of one outside are the statement.
 * Flight B of the § 0 calculation, but turned: `at` [2, 2] climbing along
 * +z from storey 1 to 2 — the projection has to work on either axis.
 * Its climb is 6.09 − 3.09 = 3.0, so half way up is 3.09 + 1.5 = 4.59.
 * The direction is normalised inside, so a payload vector of any length
 * answers the same — and a degenerate flight answers nothing.
 * --- the RIDE: which flight, and from when on (review round 1) -----------
 * A stairwell may stack two flights over the SAME footprint — same `at`,
 * same direction, one storey apart — and the server builds exactly that.
 * Then xz alone says nothing at all: the two head landings are the same
 * point but for their height, and the walk from the first head landing back
 * to the second flight's foot runs the WHOLE length of the second run. So
 * the ride is a sequence of legs, and a leg only answers once its own start
 * landing has been reached.
 *
 * The stack below is the § 0 flight and a copy of it one storey up:
 * S0: foot [1.5, 0.01, −2] level 0 → head [6.4, 3.09, −2] level 1
 * S1: foot [1.5, 3.09, −2] level 1 → head [6.4, 6.09, −2] level 2
 * Same run [at 2/−2, +x, 3.9 × 1.2] for both. S0.head and S1.head are the
 * same xz and 3.0 m apart in height; S0's climb is 3.08, S1's 3.0.
 * (a) The avatar's climb: the offer names the landing it ends on.
 * (b) THE STACK: S1.head has the same xz as S0.head and differs only in
 * storey and height — matching on xz alone would ride the wrong ramp.
 * (c) Going DOWN the flight is the same one, read from the other end.
 * (d) The NPC chain: `stairChain` lays the flights end to end, `stairLegs`
 * names the flight of each PAIR. Over the stack the second pair is
 * [S1.foot, S1.head] and must be S1 — the bug this replaces matched on
 * xz and got S0 twice.
 * (e) Downwards the pairs arrive head-first — the match has to take a
 * pair in EITHER order, or a descent has no legs at all.
 * (f) A pair no flight owns is skipped, never guessed at.
 * --- rideStep: arm at the start landing, hand over at the end ------------
 * The arrival radius is 0.4 m, and that number is not free: the server puts
 * a landing `STAIR_PAD_M/2 + STAIR_PAD_GAP_M` = 0.9/2 + 0.05 = 0.5 m from
 * the end of the run (which is why the § 0 foot landing is at x = 1.5 and
 * the run starts at x = 2). A radius under 0.5 m therefore cannot reach into
 * the run itself: a figure "at the landing" is never on a tread.
 * The NPC chain of the stack, as the routing hands it over: unarmed,
 * because the figure is still a room away from the first flight.
 * (a) In the room, 1.5 m short of the foot landing: nothing armed, the
 * floor answers. hypot(1.5, 0, 0) = 1.5 > 0.4.
 * (b) ON the foot landing: armed, and the ramp answers the landing height
 * itself (t clamped to 0).
 * (c) Half way up the first flight.
 * (d) ON the head landing: the leg is done, the NEXT one takes over —
 * unarmed, because its foot is 4.9 m back at x = 1.5.
 * (e) THE WALK BACK, the case that killed the nearest-height rule: the
 * figure crosses the whole footprint of the second flight on the
 * storey-1 floor. Its ramp would say 1.55 + 3.08 = 4.59 here; unarmed
 * it says nothing and the floor keeps the figure at 3.09.
 * (f) On the second foot landing the second leg arms — same xz as the
 * first one, 3.08 m higher, which only the 3D radius tells apart.
 * (g) The last landing ends the ride altogether.
 * (h) The AVATAR's ride starts armed: it accepted the offer standing at
 * the landing, so there is no walk up to the flight to wait for.
 * …and a figure standing a metre beside the run is on no flight at all,
 * armed or not: across = −1.0 + 2 = 1.0 > 0.6.
 * --- [S7] the ride ends at its landing at ANY frame rate (Task 35c) -----
 * The walk (`npcGoal`) retires a landing at the START of a frame, measured
 * with the height the ride wrote the frame before, and steps towards the
 * next station in the same frame. The ride used to test only the point the
 * frame ENDS on, with the root height from BEFORE this frame's ramp answer.
 * On a long frame both miss: the end point is already past the landing, the
 * old height lags the ramp, and the leg never ends. Rule now: a landing is
 * reached when the frame's SWEPT xz segment (from = where the frame began)
 * comes within 0.4 m of it; the height measured is the floor's `y` while the
 * leg waits to arm and the leg's own ramp once it is armed.
 * On 1518fdf7 (point test; stairs.ts last changed in 3af42697) the cases
 * (a), (b) swept, (c) swept and the dt 0.1 rows of (e)/(f) fail.
 * Numbers: a running step is 3.4 · 1.8 · dt = 6.12 · dt — while a station
 * remains the walk measures d + 10 > 6, so every frame of the approach runs:
 * dt 1/60 → 0.102, 1/30 → 0.204, 0.1 → 0.612, 0.25 → 1.53 m. S0's ramp
 * climbs 3.08 / 3.9 per metre of x and is clamped to the landing heights
 * for x ≤ 2 (run start, 0.01) and x ≥ 5.9 (run end, 3.09).
 * (a) ride_13 (S0 up, armed) at [6.096, −2] with the STALE root y 2.79:
 * x ≥ 5.9, so the ramp says 3.09 and the head is hypot(0.304, 0) = 0.304
 * < 0.4 away → the leg ends, the ride is over (leg 1, done). Measured with
 * the stale y it is hypot(0.304, 0.3) = 0.427 > 0.4 — the old answer.
 * (b) ride_13, a frame from [6.0, −2.3] to [6.8, −2.3]. Each end point is
 * hypot(0.4, 0.3) = 0.5 > 0.4 from the head, so the point test keeps the
 * leg armed with the ramp height there (across 0.3 ≤ 0.6, x ≥ 5.9) 3.09.
 * Swept, the nearest point is [6.4, −2.3]: ramp 3.09, distance 0.3 → done.
 * (c) ride_10 unarmed, a frame from [1.2, −2] to [2.112, −2] at floor y
 * 0.01. The end point is 0.612 from the foot landing → unarmed, null. Swept,
 * the segment passes x = 1.5 → distance 0 → armed, and the ramp at 2.112 is
 * 0.01 + 0.112 · 3.08 / 3.9 = 0.01 + 0.34496 / 3.9 = 0.0984512820512…
 * (d) The stack still holds: ride_10 on leg 1 (S1, start = foot [1.5, 3.09,
 * −2] on storey 1); a storey-0 frame from [1.0, −2] to [2.0, −2] at y 0.01
 * passes that xz at |0.01 − 3.09| = 3.08 > 0.4 → stays unarmed.
 * (e) THE WALK, fixture walk_16: S0 walked DOWN (start = head, end = foot),
 * unarmed, from [9.76, 3.09, −2] on storey 1; stations head [6.4, 3.09, −2]
 * and foot [1.5, 0.01, −2], target [3.95, 0.01, −12]; 6 s of frames. Both
 * stations lie ahead on z = −2, so the frame ends are x_k = 9.76 − s·k as
 * long as no step is clamped onto a station (it is when the frame starts
 * nearer than s).
 *   dt 0.1 (s 0.612): k = 4 → 7.312 (0.912 from the head), k = 5 → 6.70
 *   (0.3, frame start 0.912 > s: not clamped) → arms. Frame 6 starts 0.3
 *   from the head at its ramp height 3.09 → the walk retires it and goes on
 *   towards the foot, still in −x. k = 12 → 2.416 (0.916 from the foot),
 *   k = 13 → 1.804 (0.304; not clamped). Frame 13 sweeps [2.416, 1.804]:
 *   nearest 1.804, ramp 0.01 → 0.304 < 0.4 → done on frame 13, t = 1.3 s,
 *   at [1.804, −2].
 *   The OLD rule on frame 13: root y = ramp(2.416) = 0.01 + 0.416 · 3.08 /
 *   3.9 = 0.3385333…, hypot(0.304, 0.3285333…) = 0.4476 > 0.4 → not done.
 *   Frame 14 starts 0.304 from the foot → the walk retires it and turns to
 *   the target: delta (2.146, −10), 10.2277 m, so z drops 10 · 0.612 /
 *   10.2277 = 0.598 > 0.4 in that step and keeps falling — the foot is never
 *   within 0.4 again and the ride stays armed for good.
 *   dt 1/60 (s 0.102): k = 29 → 6.802 (0.402, not yet), k = 30 → 6.70 arms;
 *   k = 77 → 1.906 (ramp 0.01, 0.406, not yet), k = 78 → 1.804 → done,
 *   t = 78 / 60 = 1.3 s, at [1.804, −2].
 *   dt 1/30 (s 0.204): k = 14 → 6.904 (0.504), k = 15 → 6.70 arms; k = 38
 *   → 2.008 (0.508), k = 39 → 1.804 → done, t = 1.3 s, at [1.804, −2].
 *   dt 0.25 (s 1.53): k = 1 → 8.23, k = 2 → 6.70 (0.3; start 1.83 > s)
 *   arms; frame 3 retires the head; k = 3 → 5.17, 4 → 3.64, 5 → 2.11 (0.61
 *   from the foot, < s): frame 6 is clamped onto the foot, [1.5, −2],
 *   distance 0 → done on frame 6, t = 1.5 s.
 *   So the ride ends within 0.4 m of its foot landing at every rate: on the
 *   same point [1.804, −2] at t = 1.3 s for the three rates whose frame
 *   grids meet there, on the landing itself where a 1.53 m step lands on it.
 *   No ride is left afterwards. Heights: until it arms the figure eases
 *   towards the head's 3.09 from 3.09, so the order's peak is 3.09; it ends
 *   on the target's floor, 0.01 (eased at min(1, 4·dt) per frame for over
 *   2.6 s after the ride: residual ≤ 0.33 · 0.6^47 at dt 0.1, eps 1e-6).
 * (f) A LATER plain order — no route, which keeps whatever ride there is:
 * from the target to [3.95, 0.01, −2], under the middle of the flight on
 * storey 0, 6 s. With the ride over only the floor answers: peak and end
 * height 0.01. The ride the old rule left armed at dt 0.1 answers the ramp
 * there, 0.01 + 1.95 · 3.08 / 3.9 = 1.55 — 1.54 m into the air.
 * --- nearestRoomAt: where the climb ends up ------------------------------
 * The ride needs a ROOM to ask the server for, and stepping off a flight
 * puts you in the room the landing lies in — or, failing a hit, the nearest
 * one on that storey. The rule is `elevatorTargetRoom`'s, only measured from
 * the landing instead of a lift stop: smallest centre distance on the
 * storey, ties to the LOWER id so a symmetric floor cannot flicker.
 * The head landing of the § 0 flight, [6.4, −2]: on storey 1 that is
 * hypot(1.4, 2) = 2.44… to `landing` and hypot(11.4, 2) = 11.57… to
 * `bedroom`.
 * The same point judged on storey 0: hypot(6.4, 2) = 6.70… to `hall`,
 * hypot(0.4, 2) = 2.03… to `kitchen`.
 * (e) The tie: x = 3 is 3 m from `hall` (0) and 3 m from `kitchen` (6).
 * 'hall' < 'kitchen', so the lower id wins — in EITHER list order.
 * [S6] Corridor companion: on level -1, k1 at (-2.5,-2.5) is exactly
 * at the query; floor corridor __floor__-1 at (3,-3) is sqrt(30.5) away.
 * A floor corridor on the requested level wins before the distance rule,
 * so __floor__-1 wins despite k1's zero distance. Room eg is on level 0.
 *
 * Task 46 shared-vector index (existing hand tables above apply verbatim):
 * [1] walkDir and its unit norm; [2] slideBlocked; [3] terrainBlocks;
 * [4] slopeBlocks and STEP_DISTANCE_M=1; [5] groundStoreyFloors (unknown=0);
 * [6] clickmove; [7] talkTargetNear; [8] roomSwitchSequence; [9] candidates;
 * [10] elevator offers/options; [11] locks; [12] wall segments; [13] clamp.
 * Stateful adapters start fresh and preserve current until an external room
 * answer; [8] returns every next plus the final clock, so a 1600 ms switch
 * re-arms at 1600 and a 2000 ms sample still returns current.
 * [9] Candidate table: k1/k2 on -1 at (+/-2.5,-2.5), pos (0,2).
 * No rect contains it -> __floor__-1, same level and pos. Inside k2 -> k2.
 * Level 0 inside outline with a corridor -> __floor__0; outside -> ground;
 * no corridor -> ground. Locked/missing cellar corridor or locked ground
 * falls through to [k1,k2]. Unknown storey means 0. No rooms means [].
 * [11] Own keys only: kitchen='The door is locked.', vault='' both lock;
 * hall, empty id and inherited toString do not. Doorway order supplies the
 * first reason, including ''; current room is exempt. unlockedRooms removes
 * kitchen except while current=kitchen, preserving payload order.
 * [12] Mini room: square (0,0)..(4,4). Window x=4 spans z=1.5..2.5:
 * sill, head and glass block. Door x=0 has the same span: lintel and leaf
 * do not block. Of 11 level-0 pieces, 9 remain. Free cheeks retract .12:
 * (0,4)->(0,2.62), (0,1.38)->(0,0). Joined corners/window unchanged.
 * Level-1 lone segment (0,0)->(0,4) retracts both ends to .12 and 3.88.
 * Body radius=.25*k; k=.21 gives .0525. Origin (40,20) adds to endpoints.
 * [13] Bare wall x=0, z=0..4, radius .25: (1,1)->(-1,1) stands (1,1),
 * oblique to (-1,2) slides to (1,2); past z=4 is free. Goal (.1,3) pushes
 * to (.25,3), unless radius=.05. Gap z=1.5..2.5 passes at z=2; z=1 blocks.
 * Mini-room door passes (2,2)->(-2,2), window blocks (2,2)->(6,2), north
 * wall blocks (2,2)->(2,-2). Unflagged lintel/leaf bricks up the door.
 * Eased cheek allows z=1.45. Level 1 blocks. Empty segments preserve goal.
 * On-wall starts (0,2) can leave either way; (.05,2)->(.05,3) pushes to
 * (.25,3). Corridor walls x=0,.3, radius .25, middle x=.15: along z keeps
 * .15 clearance; an outward goal stands. Niche x=0,.089, radius .109,
 * start (.0445,2) cannot move to either +/-2 through a wall and stands.
 * The independent minWallDistance invariant and counter-probes stay inline.
 * Callback data is explicit rectangles/discs and floor-level maps; no table
 * or expected value comes from production output.
 */
```

## Inline derivations

Comment blocks of `client3d/scripts/smoke_walk_math.mjs` after its opening docstring that contain a mark a case label
cites, in file order; line numbers refer to the smoke at 87b34ea4dddc.

Line 1482 (cites [B2], [B5], [G1], [G2], [G3]):

```text
  // ---- figure_ground.json: [B2] [B5] [G1] [G2] [G3] (see "SHARED VECTORS").
  // A non-finite input travels as {"$number": "NaN" | "Infinity"}.
```

Line 1588 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] nothing over the point is the wilderness
    // Migrated to npc_ground.json: [30] an area location is open ground
    // Migrated to npc_ground.json: [30] a building footprint is built
    // Migrated to npc_ground.json: [30] an interior room beats the area location it stands in
    // Migrated to npc_ground.json: [30] an outdoor room beats the building it belongs to
    // Migrated to npc_ground.json: [30] a room without a footprint still answers
```

Line 1603 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] grass out in the wilderness
    // Migrated to npc_ground.json: [30] ...and inside an open place
    // Migrated to npc_ground.json: [30] water in the wilderness
    // Migrated to npc_ground.json: [30] THE FINDING: the same water in an open place still slows
    // Migrated to npc_ground.json: [30] ROUND 2: under a roof it does not — the place has a floor
    // Migrated to npc_ground.json: [30] ...not even a FAST ground reaches inside
    // Migrated to npc_ground.json: [30] a factor-0 ground in an open place is neutral (never meant to be walked)
    // Migrated to npc_ground.json: [30] ...and out in the open it is clamped, not neutralised
    // Migrated to npc_ground.json: [30] a crawling 0.1 is clamped in an open place as well
    // Migrated to npc_ground.json: [30] ...and 0.2 outside
    // Migrated to npc_ground.json: [30] the catalog maximum passes through
    // Migrated to npc_ground.json: [30] a NaN factor walks at the normal pace
    // Migrated to npc_ground.json: [30] a negative factor in an open place is the 0 case
    // Migrated to npc_ground.json: [30] ...and outside it the clamp
```

Line 1656 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] ...while the rule in force wades it
```

Line 1701 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] a lake takes 0.35 m of the moving body
    // Migrated to npc_ground.json: [30] ...an open place is the same water
    // Migrated to npc_ground.json: [30] THE REACH: a tiled hall over the lake is a floor
    // Migrated to npc_ground.json: [30] a ground without a depth sinks nobody
    // Migrated to npc_ground.json: [30] ...and neither does a negative one
    // Migrated to npc_ground.json: [30] ...nor a NaN one
    // Migrated to npc_ground.json: [30] the clamp of the catalog travels through untouched
    // RED COUNTER-PROBE, EXECUTED: the rule before the reach gate existed,
    // written out here — the depth with nothing but the "says something" test.
```

Line 1712 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] ...where the rule in force keeps the floor dry
```

Line 1721 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] moving, the swimmer’s depth counts
    // Migrated to npc_ground.json: [30] ...even where the ground names no clip at all: a bog swallows ankles under a plain walk
    // Migrated to npc_ground.json: [30] waiting on a ground that names a standing clip, the treader’s does
    // Migrated to npc_ground.json: [30] THE STANDING GATE: without a ground idle clip nobody is sunk
    // Migrated to npc_ground.json: [30] a ground with no waiting depth sinks nobody while waiting
    // Migrated to npc_ground.json: [30] ...and one with no moving depth nobody while moving
    // RED COUNTER-PROBE, EXECUTED: the ONE-depth rule of finding 13, rebuilt.
    // It gives the treader whatever the swimmer got.
```

Line 1733 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] ...where the rule in force gives it the body length it hangs
```

Line 1752 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] OUT of the water nothing changed at all
```

Line 1801 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] depth 0.4 m at a 1 m threshold: the gate hands back NOTHING
```

Line 1806 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] depth 1.0 m IS the threshold — the word passes through
    // A water ground that does not swim (no `movement`, i.e. walk_run) is
    // gated the same way: shallow, its mirror goes, so the figure stands on
    // the bed instead of on the surface (floatRootY = max(bed, mirror)).
    // Migrated to npc_ground.json: [30] a walk_run water ground wades in the shallows too
```

Line 1833 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] a threshold of 0 swims the ankle-deep rim — the pre-W4c water
    // NOT WATER, NOT GATED — the case that keeps the rule out of every other
    // ground: with no mirror there is no depth to measure.
```

Line 1838 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] a bog carries no mirror, so nothing is taken from it
```

Line 1841 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] a NaN bed decides nothing either — the word survives
    // RED COUNTER-PROBE, EXECUTED: the pre-W4c rule is no gate at all.
```

Line 1909 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] RED: the wade gate calls a 0.6 m ford no water at all
```

Line 1946 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] dry ground: no cut and no ghost
    // Migrated to npc_ground.json: [30] a mirror UNDER the base is not water over the object
    // Migrated to npc_ground.json: [30] exactly at the waterline: nothing is cut off yet
    // Migrated to npc_ground.json: [30] 4 cm, still under the rim ramp
    // Migrated to npc_ground.json: [30] 5 cm: the cut is the water level itself
    // Migrated to npc_ground.json: [30] a crate on the bed of a 0.6 m ford cuts at 12.60
    // Migrated to npc_ground.json: [30] a jetty post whose base lies 1.5 m down cuts at 13.50
    // Migrated to npc_ground.json: [30] a raster with nothing to say is dry
    // Migrated to npc_ground.json: [30] ...and so is a base nobody could measure
    // The cut is the LEVEL and never the base: a ghost cut at its own base
    // would discard the whole submerged half — i.e. exactly the half it exists
    // to draw — and show only the dry part it must not touch.
```

Line 1960 (cites [30]):

```text
    // A PROP is gated on the very same numbers a figure is. Hand case, § A9a:
    // ground 2.50 m, offset_y 0.5 -> bottom 3.00; a lake standing at 3.40 m
    // over it is 0.40 m of water, so the cut is 3.40. Lower the lake to 3.02
    // and the 2 cm left are under the rim ramp: no ghost.
    // Migrated to npc_ground.json: [30] a world prop on a 2.5 m bed, lake at 3.40 -> cut 3.40
    // Migrated to npc_ground.json: [30] ...the same prop with 2 cm of water over it -> none
    // A SCENE placement's base is `tile.center.y + bottom_y + lift` (§ A16.9):
    // datum -2.00, bottom_y -0.28, lift +2.335 -> 0.055. A lake at 0.30 stands
    // 0.245 m over it, so the cut is 0.30; at 0.09 it is 0.035 m and dry.
    // Migrated to npc_ground.json: [30] a scene placement at 0.055 under a lake at 0.30 -> cut 0.30
    // Migrated to npc_ground.json: [30] ...and 3.5 cm of water over the same placement -> none
```

Line 2040 (cites [30]):

```text
    // THE RED PROBE — the bug itself, in numbers. The measured shore case:
    // the bank ground sits 0.772 m under the dilated mirror (§ K-A E6 addendum)
    // and lies 1 m OUTSIDE the outline. The old gate saw only the level.
    // Migrated to npc_ground.json: [30] RED: the old level-only gate ghosted the bank diorama
```

Line 2096 (cites [G1]):

```text
    // Flat terrain at 0, a hut whose baked lattice answers its roof at 2.5 m.
    // [G1] The single-call cases (0 off the lattice, 2.5 on it, the
    // declaration rung, the terrain floor and the NaN fall-throughs) run from
    // figure_ground.json; the two heights are composed into the climb here.
```

Line 2112 (cites [G1]):

```text
    // [G1] RUNG 1, where no lattice answers: the room's own declared floor, a
    // podium 1.2 m over the flat ground (1.2; under a 2.5 lattice 2.5, ruling
    // R1). RUNG 2 is also the LOWER BOUND (Entscheid 5): a hollow in a
    // diorama never sinks the gate below the ground (−0.5 over terrain 0.3 ->
    // 0.3, lattice or declaration). A sampler with nothing to say is not a
    // height: NaN neither becomes a rung (NaN, 1.2, 0 -> 1.2; NaN, NaN, 0.3
    // -> 0.3) nor drags the answer to NaN (2.5, null, NaN -> 2.5). Those
    // seven cases run from figure_ground.json.
```

Line 2364 (cites [30], [S6]):

```text
    // stop at (3,-3): k1 is hypot(5.5, 0.5) = 5.52 m away, the corridor 0 m —
    // and even from k1's own centre (where the corridor is 5.52 m off) the
    // corridor wins, because a storey's corridor beats every distance.
    // Migrated to npc_ground.json: [30] lift -> corridor
    // Migrated to stairs.json: [S6] corridor beats distance
    // Migrated to npc_ground.json: [30] storey without corridor -> nearest room
    // Migrated to npc_ground.json: [30] levels served count the corridor
```

Line 2707 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] both storeys have a stop AND a room
```

Line 2715 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] a stop on a storey without a room does not count
```

Line 2721 (cites [30]):

```text
    // Migrated to npc_ground.json: [30] the ride ends in the room nearest that storey's stop
    // Migrated to npc_ground.json: [30] ...and downwards likewise
```

Line 3398 (cites [30]):

```text
  // Migrated to npc_ground.json: [30] r1 prefers its outside door over the party wall it is listed after
  // Migrated to npc_ground.json: [30] r2 takes its outside door over both party walls
  // Migrated to npc_ground.json: [30] r3 has no outside door, so its party wall answers
  // Migrated to npc_ground.json: [30] the tile centre applies here too
  // The hallway is where a figure leaving the building stands when no
  // rectangle holds it (§ A13b), and its way out is the HULL door: a figure
  // routed from `__floor__0` to the yard walks through this one.
  // Migrated to npc_ground.json: [30] the hallway takes its hull door as the way out
  // Migrated to npc_ground.json: [30] a room without any doorway has none
  // Migrated to npc_ground.json: [30] and neither has no room at all
  // Migrated to npc_ground.json: [30] no payload, no door
```

Line 3414 (cites [30]):

```text
  // Migrated to npc_ground.json: [30] r1 and r2 are joined by the party wall
  // Migrated to npc_ground.json: [30] the order of the two rooms does not matter
  // Migrated to npc_ground.json: [30] r1 and r3 share no wall
  // Migrated to npc_ground.json: [30] a room is not joined to itself
  // Migrated to npc_ground.json: [30] an unknown room joins nothing
  // A hull door names ONE room, so it joins the hallway to nothing indoors —
  // a figure going from a room into the hallway leaves through the room's own
  // door and walks in, exactly as it does towards the ground.
  // Migrated to npc_ground.json: [30] the hull door joins the hallway to no room
  // Migrated to npc_ground.json: [30] the tile centre applies here too (72)
```

Line 4390 (cites [J3], [J4]):

```text
  // Info panel [I1..I12] and scatter-pref typing [J3]/[J4] run from
  // overview_hud.json; what JSON cannot carry stays here.
```

Line 4696 (cites [B2]):

```text
  /**
   * --- PLACEMENT: where a figure is drawn, and whether it walks there -------
   * (`client3d/src/game/placement.ts`, acceptance findings B2 + B5)
   *
   * [B2] `placementOf(hasTile, pos)`: a tile places the figure; without one the
   * free metre point does; without either there is nothing to draw. THE POINT
   * OF IT is the wilderness — `location_id: ""` has been a legal state since
   * E1, and the figure list used to drop those characters, which took the
   * player's own figure off the map mid-walk.
   *   (true, (12, 34)) / (true, null)  -> tile   the tile decides
   *   (false, (12.5, −3.25))           -> free at (12.5, −3.25)
   *   (false, (0, 0))                  -> free at (0, 0): 0 is not "missing"
   *   (false, null) / (false, absent)  -> offmap
   *   (false, (NaN, 0)) / (false, (0, Infinity)) -> offmap: not finite
   */
```

Line 4711 (cites [B2]):

```text
  // [B2] — the cases run from figure_ground.json (see "SHARED VECTORS").
```

Line 4714 (cites [B5]):

```text
  /**
   * [B5] `figureTransition(prev, next)`: SNAP on a visibility change, ROUTE on a
   * room change, STAY otherwise. The finding (B5) is the first line of the
   * table: opening the detail view flipped the drawn room from null to the
   * room the character had been standing in all along, and the door routing
   * read that as "it just walked in" — from the outdoor huddle spot, through
   * the front door, into the room it never left.
   *   prev none                      -> snap    (the first placement)
   *   {null, closed} -> {hall, open} -> snap    VIEW OPENS
   *   {hall, open} -> {null, closed} -> snap    VIEW CLOSES
   *   {hall, open} -> {kitchen, open} -> route  a real room change
   *   {hall, open} -> {null, open}   -> route   room -> ground (outside door)
   *   {null, open} -> {hall, open}   -> route   …and back
   *   {hall, open} -> {hall, open}   -> stay
   *   {null, closed} -> {null, closed} -> stay
   *   {null, closed} <-> {null, open} -> stay   a GROUND figure is not
   *                                             teleported when the view opens
   *                                             over it (review, fix round 2)
   *   {hall, closed} -> {hall, open} -> stay    the same room, the same spot
   *   {hall, closed} -> {kitchen, open} -> snap the visibility change wins
   * The cases run from figure_ground.json; JSON has no `undefined`, so that
   * reading of "nothing drawn yet" stays here.
   */
```

Line 5184 (cites [11]):

```text
  // ── § S3  THE DATUM ITSELF IS A LATE SAMPLE (user finding 2026-08-24) ────
  //
  // THE DEFECT, and it is the OTHER HALF of § S2: everything above lifts a
  // placement OVER the datum, and the datum — the ground under the location's
  // anchor pin, `tile.center.y` — is read from the very same field, ONCE, when
  // `buildTile` runs. § S2 made every lifted placement immune to that, because
  // `lift = ground − datum` cancels the datum out of `datum + bottom_y + lift`.
  // The BUILDING model is not lifted (§ A16.9: it IS the plot, not something
  // standing on it), so for it the datum is the entire answer — and a stale
  // datum is exactly how far the house hangs in the air. `main.relevelTiles`
  // used to re-read it every frame; it was deleted with the ground plate whose
  // drape its second clause watched ("Ein Boden" E3, 9062dbf9).
  //
  // THE FIXTURE, measured on the server's own shore-plot fixture (the lake +
  // meadow of `scripts/smoke_height_bake.py` [11], relief amplitude 1.0 m /
  // wave 16 m, with a 10 × 10 m plot pinned 7 m off the east bank):
  //
  //   PLATEAU_V8  -0.4549   what the bake stamps under the plot TODAY, i.e.
  //                         `final()` at the pin (a plateau is flat, so the
  //                         pin's ground IS the plot's height)
  //   PLATEAU_V7  -0.1269   what bake v7 stamped there — the median of the
  //                         SAME noise faded to nothing at the waterline, the
  //                         guard K-A E6 retired. The ground under the plot
  //                         legitimately MOVED by -0.3280 m.
  //   COARSE      -0.2712   what the coarse overview answers at that pin on a
  //                         16 m lattice: the 10 m plateau is invisible to it.
  //
  // THE TWO WAYS THE TILE ENDS UP STALE, and both are one move:
  //
  //   fresh load   built on COARSE, tiles land   -> delta = -0.4549 + 0.2712
  //                                                       = -0.1837
  //   re-bake      built on PLATEAU_V7, v8 lands -> delta = -0.4549 + 0.1269
  //                                                       = -0.3280
  //
  // and in both the building was standing that far ABOVE its own plateau.
```
