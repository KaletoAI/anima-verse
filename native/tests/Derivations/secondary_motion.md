# secondary_motion

- Origin: the browser scene's deleted `smoke_secondary_motion.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/SecondaryVectorTests.cs`
- Vectors: `shared/test-vectors/secondary_angle.json`, `shared/test-vectors/secondary_chain.json`, `shared/test-vectors/secondary_params.json`, `shared/test-vectors/secondary_particle.json`

## Derivation

```text
/**
 * Usage: node smoke_secondary_motion.mjs   (historical; the runner was deleted with the browser scene in E3)
 * Hand derivation, metres/seconds, Y-up gravity (0,-9.81,0):
 * omega²=(4*pi)²=157.9136704. With m=2 upright a_g=(0,-9.81,0)
 * gives e_y=-9.81/omega²=-0.06212255072; m=1 gives 0 and m=.5 gives
 * +0.03106127536. Group gravity scales both baked and current gravity.
 * Direct targets replace the old force-based flatten/spill expectations:
 * f_in=clamp(-g_hat.dot(u)-max(0,-g_hat.dot(u_bind)),0,1),
 * s=1-flatten*(1-flatten_floor)*f_in; omitted floor inherits squash_min.
 * f_in=1, flatten=1, min=.5 gives s=.5 at 1.5 and 4 Hz;
 * f_in=.5 gives .75. Spill=.5 and spill_max=30 (sag=5) gives 15 degrees
 * outward with opposite X signs. Paired width is min(1.6,1+spread*(1/s-1)), spread default .5.
 * Remaining inward axial force is removed, transverse e=force/omega²
 * rotates the lever while preserving the direct target length.
 * Translate=1 moves the head by sin(atan(d))*lever_length for a unit
 * horizontal lever and d=9.81/(4*pi)^2; translate=0 keeps its head fixed.
 * Static T' uses the bounded sag direction and direct length target,
 * independently of gain and dynamic max_deg. Resets, far
 * LOD and gain zero retain T'. Rest rotation blends over 1.5 real seconds.
 * Straightening: three unit links have bind directions 0,20,40 degrees.
 * At rest 90/threshold60, smoothstep(1)=1 leaves joint bends0 and root90.
 * At rest30/threshold60, smoothstep(.5)=.5 leaves both joints10 degrees.
 * Threshold0 or rest0 retains20 degrees; signed rest uses its absolute value.
 * Rest 0→60 at .75s is30, hence joints10; after1.5s joints0. Fixed rest90
 * threshold off→60 at .75s also leaves10; interrupted disable halfway leaves
 * 15 at its midpoint, then20. Simultaneous rest+90→-90 crosses0 at .75s,
 * where threshold60→0 must leave both joints20 (zero-rest invariant).
 * Static sag_max_deg and squash bound T'; max_deg is a whole-chain swing
 * budget. Bind spans l_j give R_j=sum of remaining spans and weights R_j²*l_j.
 * Equal spans: three links give 9:4:1 /14; five give 25:16:9:4:1 /55.
 * Spans [2,1] give R=[3,1], weights=[3²*2,1²*1]=[18,1] /19.
 * One link has share 1. With L=max_deg*share, dynamic angles are linear up to
 * L/2, then L/2*(1+tanh((angle-L/2)/(L/2))).
 * This C1 function is strictly monotonic and bounded by L. Gain is
 * applied AFTER saturation. A critical spring with body velocity V has
 * d=-V*t*exp(-omega*t), independent of gravity: at V=3,t=1/30,
 * d_x=-0.065778376882. Bent-forward gravity 0/3 share this raw dynamic
 * response; the rendered transverse swing preserves each static length.
 * Weighted centroid (.25*z1+.75*z3)=2.5; after -90 X direction=(0,2.5,-d), length=2.5.
 * f=20 has 1/100 of the f=2 offset; damping does not change equilibrium.
 * Client centering subtracts 1 from Y after -90 X.
 * P4: numeric fields use smoothstep(t/1.5), so at .75 s gravity 1→.4
 * becomes .7, gain 1→0 becomes .5, frequency 2→0 becomes 1.
 * At zero frequency there is no static spring equilibrium: e=0; propagation
 * is ballistic p(t)=p(0)+v*t, including overdamped parameter values.
 * Both renderers share the solver; matrices use bounded transverse scales, inverse-transpose
 * normals, immutable bind transforms, chain FK, and instance ownership.
 *
 * Shared Task 33 oracle derivations (JSON labels below; no solver recordings):
 * [S1] omega=0 => p'=p+v*h, v'=v. (1,0,0)+(2,0,0)*.25
 * = (1.5,0,0), v'=(2,0,0). With p=(1,2,3), v=(2,-4,6),
 * p'=(1.5,1,4.5), v'=(2,-4,6); arbitrary target and its velocity cancel.
 * [S2] h=0 gives identity propagation: p=(1,2,3), v=(4,5,6).
 * [S3] critical omega=4*pi, x=0, relative velocity w=(-3,0,0).
 * h=1/30, u=omega*h=.4188790204786391, exp(-u)=.6577837688198456.
 * Absolute p_x=3*h-3*h*exp(-u)=.03422162311801544;
 * v_x=3-3*exp(-u)*(1-u)=1.8532441558504768; Y,Z remain zero.
 * The relative displacement is -.06577837688198456 (the original impulse).
 * [S4] zeta=0, f=.25 => omega=pi/2: at h=1, cos(pi/2)=0,
 * sin(pi/2)=1; x0=1,v0=0 gives p=(0,0,0), v=(-pi/2,0,0),
 * -pi/2=-1.5707963267948966.
 * [S5] x=w=0 eliminates both damped modes at any damping. Hence target
 * (1,2,3)+(4,5,6)*.25=(2,3.25,4.5), v=(4,5,6).
 * [S6] f=1/(2*pi)=.15915494309189535, zeta=1.25 gives omega=1,
 * roots -1.25 +/- sqrt(1.25^2-1)=-.5,-2. Starting x=1,w=-.5
 * selects the slow root alone: h=2 => p_x=exp(-1)=.36787944117144233,
 * v_x=-.5*exp(-1)=-.18393972058572117; Y,Z remain zero.
 * [A1] limit2 has knee1: angles0,.5,1 return0,.5,1.
 * [A2] angle2,limit2 => 1+tanh(1)=1.7615941559557649,
 * using tanh(1)=(exp(2)-1)/(exp(2)+1). [A3] limits0,-1 return0.
 * [B1] smoothstep(.75/1.5)=.5. Arithmetic means: gravity1->.4=.7,
 * gain1->0=.5, freq2->0=1, flatten0->.2=.1, spill0->.8=.4,
 * zeta1->0=.5. [B2] t=1 at1.5s gives gain0.
 * [B3] elapsed -1 clamps to0: gravity1,gain1,freq2; elapsed3 clamps
 * to1: gravity.4,gain0,freq0. [B4] means length1.5->.5=1,
 * girth.8->2=1.4. Missing spread=.5, head_sag=1 and flatten_floor
 * inherits target squash_min=.1, so each constant remains .5,1,.1.
 * [B5] The server applies clothing (docs/plugins.md, Extension motion
 * layers); the renderer only blends. Unclothed from: translate.8, spill.4,
 * gain1, freq2, zeta1, gravity1, max180, sag180, rest0 (rest_max90).
 * Clothing product c=.25: gain.25, max_deg180*.25=45, translate.8*.25=.2,
 * spill.4*.25=.1, freq2/sqrt(.25)=4, zeta1/sqrt(.25)=2. Lift .25:
 * gravity1*.75=.75, sag180*.75=135, rest0+.25*90=22.5. At .75s weight.5:
 * gain.625, translate.5, spill.25, freq3, zeta1.5, gravity.875; max_deg,
 * sag_max_deg, rest_deg and rest_max_deg are not blended fields, so they
 * are the target's 45, 135, 22.5, 90 (the rest angle eases separately).
 * [C1-C4] Numeric column-major bind matrices: anchor and c1 identity;
 * c2 translates (0,-1,0). Rings at y=-.5,-1.5 have radius .1 and
 * unit weights on c1,c2 respectively. Gravity/gain/flatten/stretch are0.
 * Each link scales once: half-width=.1*girth, centre distance=.5*length
 * or1.5*length. Thus (girth,length)=(2,1): (.2,.5),(.2,1.5);
 * (1,1.5): (.1,.75),(.1,2.25); (2,1.5): (.2,.75),(.2,2.25).
 * For C1-C3 the anchor world matrix is identity; c1 has diagonal
 * (girth,length,girth,1), translation0; c2 has the SAME diagonal and
 * translation (0,-length,0). All off-diagonal entries are0.
 * Rest60 rotates about the root without changing these distances, so C4
 * equals C3. Four vertices per ring keep the centroid on its chain axis.
 * Float32 geometry requires1e-6 tolerance; matrices themselves are doubles.
 *
 * Admin harness repair: the current viewer JSX receives statusPanel, supplied
 * as null here because only its motion prop is under test. Advanced validation
 * requires length/girth defaults1; the remount key now lives in side panels.
 */
```
