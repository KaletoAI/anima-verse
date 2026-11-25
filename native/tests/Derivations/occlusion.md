# occlusion

- Origin: `client3d/scripts/smoke_occlusion.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/OcclusionVectorTests.cs`
- Vectors: `shared/test-vectors/occlusion.json`

## Derivation

```text
/**
 * Smoke check for the VIEW CORRIDOR between camera and avatar — the shader
 * patch and the arithmetic that steers it (§ B5a: strings and numbers, no
 * screenshots).
 *
 * Usage:  node client3d/scripts/smoke_occlusion.mjs
 *         (bundles the client's occlusion + ground modules; needs three)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Standing in a wood, the embodied player looks at leaves. The offending trees
 * are INSTANCED, so there is no per-instance opacity to turn down and no honest
 * way to pick them by raycast without a ledger and a hysteresis per instance.
 * Instead every affected material carries a patch: fragments whose WORLD
 * position lies within 1.5 metres of the segment camera→avatar-chest are thinned
 * out by an ordered dither and discarded (`client3d/src/scene/occlusion.ts`).
 *
 * Two things can silently break, and both are checked here without a GPU:
 *  - the patch is the SECOND writer of `onBeforeCompile` on the scatter
 *    materials (`applySway` is already in the slot). An ASSIGNMENT would throw
 *    the wind away — the rule this repo learned the hard way with the water
 *    shader (`smoke_surface_patch.mjs`), and the mutant of section [5] measures
 *    exactly that loss.
 *  - the corridor is steered by SHARED UNIFORMS and its cache key is a
 *    CONSTANT. A key that carried the corridor would recompile every patched
 *    program on every frame — cheap to write, ruinous to run.
 *
 * The patches are handed a STUB SHADER whose vertex/fragment strings carry the
 * real `#include` anchors of three's `meshphysical` shader, and the resulting
 * strings are read.
 *
 * THE ANCHORS (both `#include` LINES, because `onBeforeCompile` sees the shader
 * BEFORE three resolves its includes):
 *   vertex   `#include <project_vertex>`          the fragment's world position
 *   fragment `#include <clipping_planes_fragment>` the discard, before anything
 *                                                  else is computed
 * The world position is taken AFTER `project_vertex` on purpose: the sway patch
 * displaces `transformed` at `begin_vertex`, and a corridor measured before it
 * would test the unbent blade.
 *
 * ---------------------------------------------------------------------------
 * [1] THE PATCH ALONE — both replacements present after the chain
 * ---------------------------------------------------------------------------
 * Hand expectations, each one a line the patch writes:
 *   vertex   `varying vec3 vOccWorld;` plus BOTH world-position branches. The
 *            instanced one is not cosmetic: at `project_vertex` the chunk
 *            itself applies `instanceMatrix`, so without the branch every blade
 *            of a meadow would report the position of the mesh's origin and the
 *            whole entry would blink as one.
 *   fragment the four uniforms declared, the point-to-SEGMENT distance (the
 *            `clamp( … , 0.0, 1.0 )` on the projection IS the difference to a
 *            line — a line would keep thinning props behind the avatar and
 *            behind the camera), the ordered 4×4 Bayer threshold, and the
 *            `discard` guarded by `uOccStrength > 0.0`.
 *   uniforms uOccA, uOccB, uOccRadius, uOccStrength
 *   key      'occlusion-corridor', constant and stable across calls.
 * The vertex anchor is APPENDED to (the world position needs `transformed`),
 * the discard stands BEFORE the clipping include.
 *
 * ---------------------------------------------------------------------------
 * [2] THE DOUBLE CHAIN — wind and corridor on ONE material
 * ---------------------------------------------------------------------------
 * The scatter materials carry both. All sway lines AND all corridor lines must
 * be in the composed shader, both uniform families bound, and the key must be
 * 'ground-sway@0.06+occlusion-corridor' — the two of them in the order they
 * were applied. Patching twice is still one patch (the WeakSet guard), or the
 * shader would declare `vOccWorld` twice and not compile.
 *
 * ---------------------------------------------------------------------------
 * [3] THE SHARED UNIFORMS — one write per frame reaches every material
 * ---------------------------------------------------------------------------
 * The `surfaceTimeUniform` pattern: two materials must hand the SAME four
 * objects into their shaders, and one call to `updateOcclusion` must show up in
 * both. Without this a wood would cost one uniform update per bush, or worse,
 * half the bushes would read a corridor from the frame before.
 *
 * ---------------------------------------------------------------------------
 * [4] THE ARITHMETIC — `occlusionUniforms`, by hand
 * ---------------------------------------------------------------------------
 * Avatar at the origin, so its chest is (0, 1.2, 0) — the 1.70 m reference
 * figure's chest, and the end of the corridor: the figure itself and the ground
 * behind it stay whole.
 *   camera (0, 1.2, 25)   d = 25 exactly  -> strength 0     (the gate)
 *   camera (0, 1.2, 22.5) d = 22.5        -> strength 0.5   ((25−22.5)/5)
 *   camera (0, 1.2, 20)   d = 20          -> strength 1     (fully open)
 *   camera (0, 1.2, 30)                   -> strength 0     (beyond the gate)
 *   camera (0, 11.2, 0)   straight above  -> a = (0, 10.7, 0): the corridor
 *                                            starts 0.5 m in front of the lens,
 *                                            or a wall the camera is pressed
 *                                            against would dissolve into a
 *                                            dither pattern filling the screen.
 *   not embodied, or no figure on the map -> strength 0, and the shader's own
 *                                            guard then discards nothing: an
 *                                            overview client draws exactly the
 *                                            picture it drew before.
 * The radius is 1.5 m throughout — a shoulder's worth either side of the line
 * of sight.
 *
 * ---------------------------------------------------------------------------
 * [5] THE RED COUNTER-CHECKS — two mutants, two losses
 * ---------------------------------------------------------------------------
 * (a) ASSIGNMENT INSTEAD OF CHAIN. The module is bundled a second time with the
 *     line that calls the previous callback deleted — that is the mistake the
 *     rule forbids, expressed as a mutation. Fed a material that already sways,
 *     the mutant's composed shader contains NOT ONE sway line while every
 *     corridor line is still there (so the probe measures the loss of the
 *     chain, not a broken module). Pinned from both sides: what the mutant
 *     loses, the truth of section [2] has.
 * (b) NEUTRALITY WITHOUT AN AVATAR. `strength 0 while not embodied` is the
 *     promise that an overview client is untouched by all of this, and a check
 *     that only reads 0 would pass just as well if the function always returned
 *     0. The mutant drops `embodied` from the gate: it then answers a real
 *     strength for an unembodied client, while the truth answers 0.
 *
 * [4] Additional segment derivations (Task 53 / E7-T8): d <= .5 collapses
 * a onto b. Camera (3,5.2,0) minus chest (0,1.2,0) is the 3/4/5 triangle:
 * clearance .5 moves a by (-.3,-.4,0) to (2.7,4.8,0). Translating feet to
 * (10,2,20) translates chest to (10,3.2,20) and start to (10,3.2,29.5).
 * [6] Shader CPU probe: distance to the CLAMPED segment; radius 1.5,
 * smoothstep from .75 to 1.5. At .75 hide=1, at 1.125 t=.5 so 1-t*t*(3-2*t)
 * = .5, at 1.5 hide=0. A 2 m point beyond either end is outside; 1.125 m
 * beyond the chest is the round cap's half rim. Gate 0 and strength 0
 * hide nothing; strength .5 times rim .5 = .25. Collapsed segments use the
 * same max(length squared,1e-6) denominator and become point distance.
 * [7] The shader Bayer formula gives rows [0,8,2,10], [12,4,14,6],
 * [3,11,1,9], [15,7,13,5], divided by 16. Discard is STRICT hide > threshold:
 * zero never discards, .5 equals pixel (1,0), exceeds (1,1)=.25,
 * 1 exceeds the maximum .9375; (5,4) repeats (1,0).
 */
```
