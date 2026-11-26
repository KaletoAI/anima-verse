# animal_vectors

- Origin: the browser scene's deleted `smoke_animal_vectors.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/AnimalVectorTests.cs`
- Vectors: `shared/test-vectors/animal_gait.json`, `shared/test-vectors/animal_legs.json`

## Derivation

```text
/** Task 34 hand derivations from e5-inventory.md section 2.10 and the
 * existing browser heuristic (no model files or live config).
 * Ordered bones: {name,parent,position:{x,y,z}}; parent is a bone index or
 * null (non-bone parent). Positions and box share world space. Outputs use
 * indices, preserving identity even with duplicate names.
 * [1] Empty, singleton, horizontal tail and high leaf yield no chains:
 * need multiple links, rise >= .12*h and foot y <= minY+.25*h.
 * [2] Box (-1,0,-2)..(1,4,2): h=4, cutoff=1, rise=.48.
 * Hip y=2 -> foot y=0 qualifies; Z is long, axis=(1,0,0).
 * Foot x=-1 < centre 0 gives both phases pi=3.141592653589793;
 * foot x=0 gives both phases 0. Names have no effect.
 * [2c,d] Two and three branches use the same side rule: feet X=-1,1
 * give [pi,0], adding centre X=0 gives [pi,0,0].
 * [2e] Translating box X to [9,11] gives centre 10: foot X=9 is
 * negative-side despite positive world X, so both phases pi.
 * [3] Foot y=1 and hip y=1.48 meet both inclusive thresholds.
 * Foot y=1.0001 fails ground; hip y=1.4799 fails minimum rise.
 * [4] Four branches, feet (-1,0,-1),(1,0,-1),(-1,0,1),(1,0,1).
 * Stable equal-height order gives hips [1,3,5,7], feet [2,4,6,8].
 * Walk [0,pi,pi/2,3*pi/2] is [0,3.141592653589793,
 * 1.5707963267948966,4.71238898038469]; trot [0,pi,pi,0].
 * Swap X/Z and widen X: same phases, axis=(0,0,1).
 * Square footprint ties choose Z, axis=(1,0,0).
 * [5] Five branches with feet y=[.8,.6,.4,.2,0] sort ascending;
 * take four: hips [9,7,5,3], feet [10,8,6,4]. All X/Z=0, so stable
 * ties give walks [0,pi,pi/2,3*pi/2], trot [0,pi,pi,0].
 * [6] Flat box uses h=max(0,.001)=.001: rise .00012 qualifies,
 * .000119 fails; centre-side foot phases 0.
 * [7] Two leaves branching directly off a hip are single links: none.
 * Three unbranched links select the first link as top, last as foot.
 * [8] swing=sin(phase+legPhase)*.45, bob=abs(sin(phase))*height*.02.
 * Zero -> (0,0). pi/2,height 2 -> (.45,.04); offset pi -> (-.45,.04).
 * -pi/2,height 3 -> (-.45,.06). pi,offset pi/2,height 2 -> (-.45,0).
 * [9] Idle bob=sin(phase)*.012, scale=1+sin(phase*.5)*.006:
 * 0 -> (0,1); pi -> (0,1.006); -pi -> (0,.994); 2*pi -> (0,1).
 * pi/2 -> (.012,1.0042426406871193), since sqrt(2)/2*.006
 * =.004242640687119285. All trigonometric checks use tolerance 1e-9.
 * [11] Browser integration uses [4a]'s box/bones and scale 1,height 4.
 * At walk phase pi/2, dt=0: angle from bind=.45, bob=1*4*.02=.08,
 * scale=1. Run from phase 1,dt=.5 -> 6.5. Idle from phase 0,dt=0
 * restores all bind rotations, bob=0 and scale=1. Without legs even a walk
 * uses idle: from phase 0,dt=.5 -> .8, walk phase remains 1.
 * A parent rotated pi/2 about Y converts world X into local +Z;
 * undoing that rotation returns world (1,0,0).
 * [10] Advance phase+dt*rate, rates walk=7, run=11, idle=1.6.
 * From 1,dt=.5: 4.5,6.5,1.8; dt=0 preserves 2;
 * walk from 1,dt=-.5 gives -2.5 (no new clamping).
 */
```
