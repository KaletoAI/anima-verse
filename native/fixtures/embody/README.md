# Embodiment fixture (Task 46 / E7-T1)

Ruling: use a separate `embody/` world so the E5 walk and E6 travel checks keep
stable inputs. All names and content are synthetic. Coordinates are metres,
XZ is east/south, Y is up, yaw is zero. Scene coordinates are tile-local;
worldmap openings are already world coordinates.

Load this directory through `FixtureSource(dir, native/fixtures)` when the E7
consumer arrives. `urls.json` reuses the synthetic box from `fidelity/` for
the room diorama and the normal shared rig/clip mappings. `model3d.json` gives
both characters null models, so the normal placeholder figure path applies.
No prop actions are offered or called. Run
`node client3d/scripts/smoke_embody_fixture.mjs` for the data/geometry checks.
Task 46 does not add a C# write consumer or a `--check embody` mode.

| Element | Authored layout |
|---|---|
| Ground | Height grid origin (-16,-16), 1 m samples, 65 columns × 33 rows; zero except the step below |
| Hall | Pin (0,0), boundary (-6,-4)..(6,4), scale 1, storeys 0 and 1 at Y 0 and 3 |
| Two rooms | r-a: X -6..0, Z -4..4; r-b: X 0..6, Z -4..4 |
| Party-wall door | X 0, Z 1.5..2.5, centre (0,2), clear width 1; leaf/lintel are excluded from collision |
| Outside door | Z 4, X 2.4..3.6, centre (3,4), clear width 1.2; authored opening edge 2, inward (0,-1), r-b |
| Lift | Pads at XZ (4,2), levels 0/1; centre Y -.04/2.96 + half thickness .05 = stop Y .01/3.01; r-b/r-up serve the levels |
| Stair flight | Foot (0,.01,-2), run starts (.5,-2), head (3.5,3.01,-2); run 2.5, rise 3, width 1, 10 authored ascending treads of .25 with top heights .3,.6,...,3; upper plates have its footprint hole |
| Room place | room-seat in r-a, centre (-3,0), slots (-3.3,0), (-2.7,0), capacity 2; source room, diorama true; surface Y .45 minus root offset .4 = root Y .05 |
| Room poses | sitting / reading, both free slots [0,1] in `/play/places` |
| Diorama | role room, r-a, anchor (-3,0), full variant `/fixture/embody/diorama.glb`; clipped to r-a |
| Free boundary | loc-free pin (24,0), square +/-4, empty openings, world rim X 20..28, Z -4..4 |
| Locked location | loc-locked pin (40,0), square +/-4; opening (40,4), room locked-room; `hud_scene.json` carries the HUD bus lock sentence |
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
| (3,6), wilderness | Authored hall opening (3,4), dist 2 -> enter, inward (0,-1) |
| (30,0), wilderness | Free rim point (28,0), dist 2 -> enter, inward (-1,0) |
| (40,6), wilderness | Locked opening (40,4), dist 2 -> locked entry offer, caller displays lock reason |
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
