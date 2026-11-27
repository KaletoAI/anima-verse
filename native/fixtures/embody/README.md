# Embodiment fixture (Task 46 / E7-T1)

Ruling: use a separate `embody/` world so the E5 walk and E6 travel checks keep
stable inputs. All names and content are synthetic. Coordinates are metres,
XZ is east/south, Y is up, yaw is zero. Scene coordinates are tile-local;
worldmap openings are already world coordinates.

Load this directory through `FixtureSource(dir, native/fixtures)` when the E7
consumer arrives. `urls.json` reuses the synthetic box from `fidelity/` for
the room diorama and the normal shared rig/clip mappings. `model3d.json` gives
both characters null models, so the normal placeholder figure path applies.
No prop actions are offered or called. The data/geometry checks ran in the browser scene's
`smoke_embody_fixture.mjs`, deleted with that scene in plan E3.
Task 46 does not add a C# write consumer or a `--check embody` mode.

| Element | Authored layout |
|---|---|
| Ground | Height grid origin (-16,-16), 1 m samples, 65 columns × 33 rows; zero except the step below |
| Hall | Pin (0,0), boundary (-6,-4)..(6,4), scale 1, storeys 0 and 1 at Y 0 and 3 |
| Two rooms | r-a: X -6..0, Z -4..4; r-b: X 0..6, Z -4..4 |
| Party-wall door | X 0, Z 1.5..2.5, centre (0,2), clear width 1; leaf/lintel are excluded from collision |
| Outside door | Z 4, X 2.4..3.6, centre (3,4), out (0,1), clear width 1.2, room r-b, level 0; fenced hall also has gate edge 2 at (3,4), inward (0,-1) |
| Lift | Pads at XZ (4,2), levels 0/1; centre Y -.04/2.96 + half thickness .05 = stop Y .01/3.01; r-b/r-up serve the levels |
| Stair flight | Foot (0,.01,-2), run starts (.5,-2), head (3.5,3.01,-2); run 2.5, rise 3, width 1, 10 authored ascending treads of .25 with top heights .3,.6,...,3; upper plates have its footprint hole |
| Room place | room-seat in r-a, centre (-3,0), slots (-3.3,0), (-2.7,0), capacity 2; source room, diorama true; surface Y .45 minus root offset .4 = root Y .05 |
| Room poses | sitting / reading, both free slots [0,1] in `/play/places` |
| Diorama | role room, r-a, anchor (-3,0), full variant `/fixture/embody/diorama.glb`; clipped to r-a |
| Free boundary | loc-free pin (24,0), square +/-4, unfenced, empty openings and doors |
| Locked location | loc-locked pin (40,0), square +/-4; fenced, gate (40,4), empty doors; `hud_scene.json` carries the HUD bus lock sentence |
| Characters | fixture-avatar (-3,1) and fixture-npc (-3,3), both r-a; separation exactly 2 |
| Impassable patch | Rock square X 8..12, Z 8..12; no footprint covers it |
| One-metre step | Lattice plateau Y 1 at X 10..14, Z -2..2; surrounding lattice Y 0; linear interpolation rises from X 9 to 10 on Z 0 |

The step is a one-metre rise with a one-cell interpolation ramp, rather than
a discontinuity between identical grid coordinates. (9,0) has Y 0, (10,0)
Y 1; rise/distance = 1 gives 45°, over the default 40° maximum. A lead from
9 to 9.5 rises .5 m over .5 m, violating both the .4 m step limit and 40°
slope limit. A drop is permitted by the browser rule. All ordinary walking
and offer probes below are on the flat part of the grid.

## Hand numbers for the later native check

At speed 3.4 and dt=1/60, each unblocked frame travels 17/300 m. Starting
(-3,1), W at yaw 0 has direction (0,-1). After n frames the point is
(-3, 1-17n/300): frame 15 -> Z .15, frame 30 -> -.7, frame 60 -> -2.4.
The .15 m target lead is longer than the frame step and does not change it.
For a click at (-3,-2.4), the .2 m arrival radius is first reached after
57 steps: Z -2.23, remainder .17; the next steering evaluation stops. After
56 steps Z -2.1733333333333333, remainder .2266666666666667, still walking.

Against the rock patch, (7,9)->(9,10) has blocked target and |dx|=2>|dz|=1.
The X-only attempt (9,9) is blocked; the Z-only attempt (7,10) is free, so
slideBlocked returns (7,10). Against the party wall away from its door,
(-.3,0)->(.3,.2) projects onto Z and ends (-.3,.2). Through the door at
Z 2 the same eastward crossing survives. Door cheeks ease .12 m each, so
the 1 m door collides as a 1.24 m opening (Z 1.38..2.62).

`refusal-walk` attempts (1,2), answer (-3,2): distance 4 <=8, so correction
walks. `refusal-snap` attempts (10,2), answer (-3,2): distance 13 >8, so it
snaps to (-3,2). At speed 3.4, 4 m would take 20/17 seconds before the .2 m
arrival radius; 8 m takes 40/17 seconds, below the 3 s correction deadline.
The refused point is a radius .8 disc for 4 s; it is not the accepted point.

| Probe (XZ; room/level where needed) | Hand offer |
|---|---|
| (-3,1), r-a/0 | NPC dist 2 <=2.5 -> talk; stair sqrt(18)>1.5, lift sqrt(50)>1.5; own location entry suppressed |
| (0,-2), r-b/0 | Stair foot dist 0 -> stairs; lift sqrt(32)>1.5 |
| (3,2), r-b/0 | Lift dist 1 <1.5 -> elevator, levels [0,1], sole destination 1 |
| (5.5,2), r-b/0 | Lift dist 1.5 equals the strict range -> no elevator |
| (3,6), wilderness | Fenced hall gate (3,4), dist 2 -> enter, inward (0,-1) |
| (30,0), wilderness | Unfenced meadow without doors -> no enter offer |
| (40,6), wilderness | Locked fenced gate (40,4), dist 2 -> locked entry offer, caller displays lock reason |
| (-3.3,.6), diorama hit | Nearest free slot (-3.3,0), dist .6 -> room-seat |
| (-3.3,.7), diorama hit | dist .7 >.6 -> no place pick |

## Scripted answers

`pos_answers.json` is data for the later FixtureSource write adapter. Format
`anima-pos-answers/1`: select a named scenario, consume its steps in order,
match `method`, `path` and exact `request` JSON (GET has null request), return
`status` and `body`. Unknown/exhausted scenarios fail. Queues are independent;
there is no implicit server mutation, replay, timer or network access.

The table includes accepted, throttled then retry, stale, 409 walk correction,
409 snap, 403 party_follower, room entry accepted/refused, taking either room
pose, standing up, GET places, and a room-place-full refusal. Position seq 1/2
uses t_ms 330/660 and fixed session `fixture-session-46`. The activity and
entry request bodies are the browser wire shapes. Seating is verified later
from an explicit worldmap row carrying its `place`; a successful activity
answer alone does not synthesize a row. `hud_scene.json` is an explicit HUD bus snapshot (`lockedRooms`,
`lockedLocations`, `lockedLoc`, `movementLocked`, `partyLeader`), ready for
the later check to inject. It is not an API response or a new worldmap protocol.

## Corridor check (Task 53 / E7-T8)

`--check=embody` also builds these unchanged fixtures for `OcclusionCheck`.
Feet (-3,.01,1) give chest (-3,1.21,1). A camera at (-3,1.21,8)
starts its corridor at Z=7.5; distance 7 gives strength 1. The south wall
from (2.4,4) to (-6,4), Y=0..3, contains (-3,1.21,4), so that fragment
has segment distance 0 and hide 1. The fragment at (0,1.21,4) is 3 m
away, beyond radius 1.5, and stays whole. Moving the camera to
(-3,1.21,-6) puts the original wall fragment 3 m beyond the chest;
its hide returns to 0. First person, overview and absent avatars always
have strength 0. These are shader-binding and CPU discard probes; the
headless renderer does not verify pixels.

The check also proves shell clones leave interior materials alone, wind and
instance color survive on scatter/undergrowth, impostors carry the corridor
while their bake does not, and plan-hull cut clones toggle their corridor gate
1 → 0 → 1 as cutouts open/close while sharing their shader program.

## Entry semantics hand derivations (fence, outside walls, no-trap, offers, rooms)

Fixture geometry: `loc-hall` at `(0, 0)`, yaw `0`, boundary `x -6..6`, `z -4..4`, `k = 1`, `BodyRadiusM = 0.25`, `DoorEaseM = 0.12`; gate `edge 2`, `at_world = (3, 4)`, `inward = (0, -1)`; outside door `x = 3`, `z = 4`, `out = (0, 1)`, `width_m = 1.2`, `room = "r-b"`, `level = 0`; tolerances `door_tolerance = {along_pad_m: 0.3, across_m: 1.5}`, `gate_tolerance_m = 1.5`. Walk speed is `3.4 m/s` at `dt = 1/60 s`, so each unblocked frame advances `3.4 / 60 = 17/300 ≈ 0.056667 m`.

- **`EmbodyWalkCheck` fenced hall (`PlayerBlocked`)**:
  - `(0, 0)` from outside (`mine = null`, `from = null`): lies inside the foreign fenced plot `loc-hall`; distance to gate `(3, 4)` is `hypot(0 - 3, 0 - 4) = hypot(-3, -4) = 5 > 1.5` → blocked (`true`).
  - `(3, 3.6)` from `(3, 4.5)` (`mine = null`): distance to gate `(3, 4)` is `hypot(0, -0.4) = 0.4 <= 1.5` → allowed (`false`).
  - Own place click target `(-3, -8)` (`mine = hall`, `from = null`): `from` is `null` (target check), so rule (b) does not refuse it (`false`).
  - Leaving `hall` from `(0, 3.6)` to `(0, 4.5)`: `from` lies on `hall`, target is outside `hall`, distance to gate `(3, 4)` is `hypot(0 - 3, 4.5 - 4) = hypot(-3, 0.5) = sqrt(9.25) ≈ 3.04138 > 1.5` → blocked (`true`).
  - Leaving `hall` from `(3, 3.6)` to `(3, 4.5)`: distance to gate `(3, 4)` is `hypot(0, 0.5) = 0.5 <= 1.5` → allowed (`false`).
- **`EmbodyWalkCheck` unfenced hall with door (`fenced: false`, `openings: []`, same `doors`)**:
  - `(0, 0)` from outside (`mine = null`, `from = null`): unfenced plot does not block (`PlayerBlocked == false`).
  - East outside wall at `x = 6`: starting at `(7, 0)` with key `a` (west, `(-1, 0)` at yaw `0`), `60` frames cover `60 * 17/300 = 3.4 m`, reaching the clamped wall line `x = 6 + 0.25 = 6.25` after `0.75 / (17/300) = 225/17 ≈ 13.24` frames; `OutsideWalls` holds `x >= 6.25` on every frame and the avatar settles at `x = 6.25 < 6.4`.
  - South outside door gap at `z = 4`, `x = 2.4..3.6` (width `1.2 m`, eased `0.12 m` per cheek → clear collision gap `x = 2.28..3.72`, `0.72 m > 0.25 m` clearance on each side of `x = 3`): starting at `(3, 5)` with key `w` (north, `(0, -1)` at yaw `0`), `40` frames cover `40 * 17/300 = 68/30 ≈ 2.2667 m`, reaching `z = 5 - 2.2667 = 2.7333 < 3.6`.
  - Upstairs skip: `r-up` is on level `1 != 0`, so `OutsideWalls(hall, "r-up", -3, 1, entry)` skips `hall`'s level-0 walls and returns `null`.
- **`EmbodyWalkCheck` no-trap unfenced hall (`fenced: false`, `openings: []`, `doors: []`)**:
  - `OutsideWalls(null, "", 7, 0, noTrapEntry)` skips `loc-hall` (unfenced with no outside doors) and returns `null`.
  - Starting at `(7, 0)` with key `a` (west), crossing `x = 6` takes `1.0 / (17/300) = 300/17 ≈ 17.65` frames; in `30` frames the figure travels `30 * 17/300 = 1.7 m` to `x = 7 - 1.7 = 5.3 < 6`, passing the wall line that held it at `6.25` in the door variant.
  - With the interior visible and room `r-a`, `scene_loc-hall.json` has `7` non-leaf/non-lintel level-0 walls: `5` hull segments on the boundary (`z = -4`, `x = 6`, `z = 4` east/west of the door, `x = -6`; endpoints and midpoints all have rim distance `0 <= 0.3 * 1`) and `2` party-wall segments at `x = 0` (`(0, -4)-(0, 1.38)` with midpoint `(0, -1.31)` at rim distance `2.69 > 0.3`, and `(0, 2.62)-(0, 4)` with midpoint `(0, 3.31)` at rim distance `0.69 > 0.3`). `PlayerWalls(hall, "r-a", noTrapEntry)` keeps the `2` party-wall segments (`2 < 7` of `doorEntry`) and drops all `5` hull segments.
- **`EmbodyOffersCheck` O3b (unfenced hall with door)**:
  - At `(3, 5)`: distance to door `(3, 4)` is `hypot(0, -1) = 1.0 <= 3` (`EnterRadius = 3`; along `out = (0, 1)`: `across = 1.0 <= 1.5`, `along = 0 <= 0.6 + 0.3 = 0.9`) → enter offer with `point = (3, 4)`, `inward = -out = (0, -1)`. `EnterAsync` sets walk-in goal `point + inward * 0.5 = (3, 4) + (0, -0.5) = (3, 3.5)`.
  - At `(-3, 5)`: distance to door `(3, 4)` is `hypot(6, -1) = sqrt(37) ≈ 6.0828 > 3` (`along = -6`, `|-6| = 6 > 0.9`), and `openings` is empty → no offer (`enterOffer` is `null`).
- **`EmbodyRoomsCheck` R11 / R12**:
  - `R11`: avatar at `(3, 2)` (in `r-b`, `RoomId = "r-a"`) with `confirmedLoc = ""` != `"loc-hall"` → `AvatarRoomsController.Tick` calls `Channel.Idle()` instead of `Channel.Walk`, so after `1600 ms > 1500 ms` hold, `RoomRequests.Count == 0`.
  - `R12`: with `confirmedLoc = "loc-hall"` and scenario `enter-room-not-in-location` (step 0: `409 {"detail":{"reason":"not_in_location","location_id":""}}`, step 1: `200`), the first send happens at `1500 ms` (`RoomRequests.Count == 1`); advancing `5000 ms` (`> 4000 ms` `RejectMs`) sends nothing while `confirmedLoc` stays `"loc-hall"`; changing `confirmedLoc` to `"loc-other"` clears the block via `SetLocation`, and returning to `"loc-hall"` for `1500 ms` sends the retry (`RoomRequests.Count == 2`).
