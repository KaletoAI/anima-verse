#!/usr/bin/env node
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
 * position lies within a metre of the segment camera→avatar-chest are thinned
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
 * The radius is 1.0 m throughout — a shoulder's worth either side of the line
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
 * ---------------------------------------------------------------------------
 * [6] THE WIRING, pinned by reading the source
 * ---------------------------------------------------------------------------
 * The patch is worth nothing where nobody applies it, and worse than nothing
 * where it is applied to a SHARED material: `loadGlb` caches the loaded file,
 * so patching `mesh.material` would dissolve a placed tree in a room the moment
 * the player walks past a wood. So the scatter path clones per entry (and
 * therefore disposes every clone), the tile shell is patched per tile, the
 * server model on the clones `applySceneBuilding` makes, and `main.ts` writes
 * the uniforms once per frame. None of that can be called from here — it lives
 * inside closures over fetched payloads — so it is pinned against the source
 * text.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const OCC_SRC = join(ROOT, 'client3d/src/scene/occlusion.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');
const TILES_SRC = join(ROOT, 'client3d/src/scene/tiles.ts');
const RECIPE_SRC = join(ROOT, 'client3d/src/scene/sceneRecipe.ts');
const MAIN_SRC = join(ROOT, 'client3d/src/main.ts');

/**
 * Bundle the client's occlusion module TOGETHER with the ground module and
 * import the pair. One bundle on purpose: the double chain of section [2] needs
 * the very `applySway` that runs in the app, and `external: ['three']` keeps
 * node's own three the only one in play (same trick as
 * `smoke_surface_patch.mjs`). `ground.ts` reaches the DOM and the network only
 * inside functions, so it loads here.
 *
 * `mutate` rewrites the BUILT text before the import — that is how section [5]
 * gets its two mutants without a second copy of the patch lying around to rot.
 */
async function loadClient(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const entry = "export { applyOcclusionFade, occlusionUniforms, updateOcclusion,\n"
      + "  occA, occB, occRadius, occStrength, OCC_CACHE_KEY, OCC_RADIUS_M }\n"
      + `  from '${OCC_SRC}';\n`
      + `export { applySway } from '${GROUND_SRC}';\n`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'occlusion.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    const file = join(dir, 'occlusion.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section [5a]'s mutant: `applyOcclusionFade` ASSIGNS instead of chaining, so
 *  the predecessor patch in the slot is never called. Anchored on the
 *  corridor's own first uniform — there are several chained patches in this
 *  bundle and a bare `prev.call(…)` would hit whichever esbuild printed
 *  first. */
function assignInsteadOfChain(text) {
  const chained = /prev\.call\(mat, shader, renderer\);(\s*)shader\.uniforms\.uOccA =/;
  if (!chained.test(text)) throw new Error('the corridor patch no longer chains here');
  return text.replace(chained, 'shader.uniforms.uOccA =');
}

/** Section [5b]'s mutant: the embodiment gate drops out of the arithmetic, so
 *  an overview client would get a real corridor cut through its map. */
function ignoreEmbodied(text) {
  const gate = 'if (!embodied || !avatar) {';
  if (!text.includes(gate)) throw new Error('the embodiment gate is no longer where the probe looks');
  return text.replace(gate, 'if (!avatar) {');
}

/** The stub shader: three's own anchor lines, in three's own order, and
 *  nothing else. What the patches do to these strings is the whole subject. */
function stubShader() {
  return {
    uniforms: {},
    vertexShader: [
      'void main() {',
      '\t#include <begin_vertex>',
      '\t#include <project_vertex>',
      '}',
    ].join('\n'),
    fragmentShader: [
      'void main() {',
      '\t#include <clipping_planes_fragment>',
      '\t#include <map_fragment>',
      '\t#include <opaque_fragment>',
      '}',
    ].join('\n'),
  };
}

/** The lines the corridor patch writes — one list, used for "present" in [1]
 *  and [2] and for "absent" nowhere yet, so the two sides cannot drift. */
const OCC_MARKS = [
  ['vert', 'varying vec3 vOccWorld;'],
  ['vert', 'vOccWorld = ( modelMatrix * instanceMatrix * vec4( transformed, 1.0 ) ).xyz;'],
  ['vert', 'vOccWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;'],
  ['frag', 'uniform vec3 uOccA;'],
  ['frag', 'uniform float uOccStrength;'],
  ['frag', 'if ( uOccStrength > 0.0 ) {'],
  // point-to-SEGMENT, not point-to-line: the clamp is the whole difference
  ['frag', 'float occT = clamp( dot( vOccWorld - uOccA, occAB ) / occLen2, 0.0, 1.0 );'],
  ['frag', 'float occDist = distance( vOccWorld, uOccA + occAB * occT );'],
  // the soft rim over the radius, and the ordered 4x4 Bayer threshold
  ['frag', 'smoothstep( uOccRadius * 0.5, uOccRadius, occDist )'],
  ['frag', 'float occThreshold = ( abs( occY0 - occX0 ) * 8.0 + occY0 * 4.0'],
  ['frag', 'if ( occHide > occThreshold ) discard;'],
];
const OCC_UNIFORMS = ['uOccA', 'uOccB', 'uOccRadius', 'uOccStrength'];
/** What `applySway` writes, at the amplitude used below — the predecessor the
 *  chain has to keep (copied from `smoke_surface_patch.mjs` section [8], which
 *  is where these lines are the subject). */
const SWAY_MARKS = [
  ['vert', 'uniform float uSwayRef;'],
  ['vert', 'float swayUp = pow( max( transformed.y, 0.0 ) / uSwayRef, 2.0 );'],
  ['vert', 'transformed.xz += 0.06 * swayUp * sin( uTime * 1.70 + swayPhase ) * swayDir.xz;'],
];
const SWAY_UNIFORMS = ['uTime', 'uSwayRef'];

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

function marksIn(shader, marks) {
  return marks.filter(([where, text]) => (where === 'vert'
    ? shader.vertexShader : shader.fragmentShader).includes(text))
    .map(([, text]) => text);
}
const allOf = (marks) => marks.map(([, text]) => text);
/** Metres to the millimetre — the corridor is a view effect, and comparing
 *  raw doubles would only measure the square root. */
const mm = (v) => Math.round(v * 1000) / 1000;
const mm3 = (v) => v.map(mm);

async function main() {
  const THREE = await import('three');
  const { applyOcclusionFade, occlusionUniforms, updateOcclusion,
    occA, occB, occRadius, occStrength, OCC_CACHE_KEY, OCC_RADIUS_M,
    applySway } = await loadClient();

  /** One material through the patch, with its composed shader. */
  function patched(patch = applyOcclusionFade, before = null) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
    if (before) before(mat);
    patch(mat);
    const shader = stubShader();
    mat.onBeforeCompile(shader, null);
    return { mat, shader };
  }

  console.log('\n[1] the corridor patch alone — both replacements after the chain');
  const bush = patched();
  check('every corridor line is written', marksIn(bush.shader, OCC_MARKS),
    allOf(OCC_MARKS));
  check('…the four uniforms are bound',
    OCC_UNIFORMS.filter((u) => bush.shader.uniforms[u] !== undefined), OCC_UNIFORMS);
  check('the vertex anchor is APPENDED to, not replaced',
    bush.shader.vertexShader.includes('#include <project_vertex>'), true);
  check('…and the world position stands after it',
    bush.shader.vertexShader.indexOf('#include <project_vertex>')
      < bush.shader.vertexShader.indexOf('vOccWorld ='), true);
  check('the discard stands before the clipping include',
    bush.shader.fragmentShader.indexOf('discard;')
      < bush.shader.fragmentShader.indexOf('#include <clipping_planes_fragment>'), true);
  check('…and inside the strength guard (0 discards nothing)',
    bush.shader.fragmentShader.indexOf('if ( uOccStrength > 0.0 ) {')
      < bush.shader.fragmentShader.indexOf('discard;'), true);
  check('nothing of the test lands in the vertex shader',
    bush.shader.vertexShader.includes('discard'), false);
  check('the cache key is the corridor\'s own', bush.mat.customProgramCacheKey(),
    OCC_CACHE_KEY);
  check('…which is the constant, not a value of the frame',
    OCC_CACHE_KEY, 'occlusion-corridor');
  check('…and it is stable across calls', bush.mat.customProgramCacheKey(),
    bush.mat.customProgramCacheKey());
  const second = patched();
  check('a second material answers the SAME key (one program for all of them)',
    second.mat.customProgramCacheKey(), bush.mat.customProgramCacheKey());

  console.log('\n[2] the double chain — wind and corridor on one material');
  const grass = patched(applyOcclusionFade, (m) => applySway(m, 0.06, 0.8));
  check('the sway lines survive the corridor patch',
    marksIn(grass.shader, SWAY_MARKS), allOf(SWAY_MARKS));
  check('…and every corridor line is there as well',
    marksIn(grass.shader, OCC_MARKS), allOf(OCC_MARKS));
  check('the sway uniforms are bound',
    SWAY_UNIFORMS.filter((u) => grass.shader.uniforms[u] !== undefined), SWAY_UNIFORMS);
  check('…and the corridor uniforms too',
    OCC_UNIFORMS.filter((u) => grass.shader.uniforms[u] !== undefined), OCC_UNIFORMS);
  check('the key is both, in the order they were applied',
    grass.mat.customProgramCacheKey(), `ground-sway@0.06+${OCC_CACHE_KEY}`);
  check('…which is neither of the two singles',
    ['ground-sway@0.06', OCC_CACHE_KEY].includes(grass.mat.customProgramCacheKey()), false);
  applyOcclusionFade(grass.mat);
  const twice = stubShader();
  grass.mat.onBeforeCompile(twice, null);
  check('patching twice is still one patch',
    twice.vertexShader.split('varying vec3 vOccWorld;').length - 1, 1);
  check('…and the key did not grow a second corridor',
    grass.mat.customProgramCacheKey(), `ground-sway@0.06+${OCC_CACHE_KEY}`);

  console.log('\n[3] the shared uniforms — one write per frame reaches everything');
  check('two materials share ONE corridor start',
    bush.shader.uniforms.uOccA === grass.shader.uniforms.uOccA, true);
  check('…one corridor end', bush.shader.uniforms.uOccB === grass.shader.uniforms.uOccB, true);
  check('…one radius', bush.shader.uniforms.uOccRadius === grass.shader.uniforms.uOccRadius, true);
  check('…and one strength',
    bush.shader.uniforms.uOccStrength === grass.shader.uniforms.uOccStrength, true);
  check('…and they are the module\'s own objects',
    [bush.shader.uniforms.uOccA === occA, bush.shader.uniforms.uOccB === occB,
      bush.shader.uniforms.uOccRadius === occRadius,
      bush.shader.uniforms.uOccStrength === occStrength], [true, true, true, true]);
  updateOcclusion({ x: 0, y: 1.2, z: 10 }, { x: 0, y: 0, z: 0 }, true);
  check('one frame\'s write reaches the composed shader',
    [mm(bush.shader.uniforms.uOccA.value.z), mm(bush.shader.uniforms.uOccB.value.z),
      mm(bush.shader.uniforms.uOccStrength.value)], [9.5, 0, 1]);
  check('…and the second material sees the very same numbers',
    [mm(grass.shader.uniforms.uOccA.value.z), mm(grass.shader.uniforms.uOccStrength.value)],
    [9.5, 1]);
  updateOcclusion({ x: 0, y: 1.2, z: 10 }, { x: 0, y: 0, z: 0 }, false);
  check('leaving the mode neutralises both at once',
    [bush.shader.uniforms.uOccStrength.value, grass.shader.uniforms.uOccStrength.value],
    [0, 0]);

  console.log('\n[4] the arithmetic — occlusionUniforms, by hand');
  const feet = { x: 0, y: 0, z: 0 };
  const gate = occlusionUniforms({ x: 0, y: 1.2, z: 25 }, feet, true);
  check('the corridor ends at the avatar\'s chest, 1.2 m up', mm3(gate.b), [0, 1.2, 0]);
  check('the radius is one metre', gate.radius, OCC_RADIUS_M);
  check('…and that is 1.0', OCC_RADIUS_M, 1);
  check('at exactly 25 m the gate is shut', mm(gate.strength), 0);
  check('…and the corridor still starts 0.5 m in front of the lens',
    mm3(gate.a), [0, 1.2, 24.5]);
  check('halfway through the 20..25 m blend the strength is halved',
    mm(occlusionUniforms({ x: 0, y: 1.2, z: 22.5 }, feet, true).strength), 0.5);
  check('at 20 m it is fully open',
    mm(occlusionUniforms({ x: 0, y: 1.2, z: 20 }, feet, true).strength), 1);
  check('…and stays open closer in',
    mm(occlusionUniforms({ x: 0, y: 1.2, z: 5 }, feet, true).strength), 1);
  check('beyond the gate nothing is thinned at all',
    mm(occlusionUniforms({ x: 0, y: 1.2, z: 30 }, feet, true).strength), 0);
  const above = occlusionUniforms({ x: 0, y: 11.2, z: 0 }, feet, true);
  check('the 0.5 m clearance follows the line of sight, not an axis',
    [mm3(above.a), mm(above.strength)], [[0, 10.7, 0], 1]);
  const overview = occlusionUniforms({ x: 0, y: 1.2, z: 5 }, feet, false);
  check('an unembodied client is neutral', overview.strength, 0);
  check('…and so is one whose figure is not on the map yet',
    occlusionUniforms({ x: 0, y: 1.2, z: 5 }, null, true).strength, 0);
  check('…while the corridor collapses to a point instead of turning round',
    mm3(overview.a), mm3(overview.b));

  console.log('\n[5] the RED counter-checks — the chain, and the neutrality');
  const flat = await loadClient(assignInsteadOfChain);
  const redMat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  flat.applySway(redMat, 0.06, 0.8);
  flat.applyOcclusionFade(redMat);
  const redShader = stubShader();
  redMat.onBeforeCompile(redShader, null);
  check('the assignment mutant loses EVERY sway line',
    marksIn(redShader, SWAY_MARKS), []);
  check('…and the sway uniforms with them',
    SWAY_UNIFORMS.filter((u) => redShader.uniforms[u] !== undefined), []);
  check('…while its own corridor is fully intact (the probe measures the chain)',
    marksIn(redShader, OCC_MARKS), allOf(OCC_MARKS));
  check('the truth, from the other side, KEEPS the wind',
    marksIn(grass.shader, SWAY_MARKS).length, SWAY_MARKS.length);

  const loud = await loadClient(ignoreEmbodied);
  check('without the embodiment gate an overview client WOULD be cut open',
    mm(loud.occlusionUniforms({ x: 0, y: 1.2, z: 5 }, feet, false).strength), 1);
  check('…while the truth answers 0 for the very same frame',
    mm(occlusionUniforms({ x: 0, y: 1.2, z: 5 }, feet, false).strength), 0);

  console.log('\n[6] the wiring, pinned by reading the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  const tilesSrc = await readFile(TILES_SRC, 'utf8');
  const recipeSrc = await readFile(RECIPE_SRC, 'utf8');
  const mainSrc = await readFile(MAIN_SRC, 'utf8');
  check('the tuft material of every scatter entry is patched',
    /applySway\(mat, entrySway, h\);\n(\s*\/\/[^\n]*\n)*\s*applyOcclusionFade\(mat\);/.test(groundSrc),
    true);
  check('…a loaded tier draws through a CLONE of the cached GLB material',
    /const material = prop\.mats\.get\(url\) \?\? \(mesh\.material as THREE\.Material\)\.clone\(\);/
      .test(groundSrc), true);
  check('…and the patch is applied where a tier is MOUNTED (mountUrl)',
    /applySway\(material, prop\.sway, prop\.targetH\);\s*applyOcclusionFade\(material\);/
      .test(groundSrc), true);
  // Every clone is ours now, so every clone has to be freed — the wind used to
  // be the condition, and a clone nobody frees is a leak per terrain rebuild.
  check('…every tier material is disposed with the area',
    /\n\s*for \(const m of prop\.mats\.values\(\)\) m\.dispose\(\);/.test(groundSrc), true);
  check('…without the old sway condition in front of it',
    /if \(prop\.sway > 0\) for \(const m of prop\.mats/.test(groundSrc), false);
  check('the procedural building shell is patched per tile',
    /shell\.traverse\(\(o\) => \{[\s\S]{0,400}?applyOcclusionFade\(m\);/.test(tilesSrc), true);
  // Twice = the import and the ONE call: the socle plate under a building is
  // ground and must keep its fragments (it is added before the shell capture).
  check('…and nowhere else in that file (the socle plate stays whole)',
    tilesSrc.split('applyOcclusionFade').length - 1, 2);
  check('the server building model is patched on the clone, not on the cache',
    /const c = m\.clone\(\);[\s\S]{0,700}?applyOcclusionFade\(c\);/.test(recipeSrc), true);
  check('main.ts evaluates the corridor in a FRAME hook',
    /addFrameHook\(\(\) => \{[\s\S]{0,400}?updateOcclusion\(engine\.camera\.position,/
      .test(mainSrc), true);
  check('…with the avatar only while embodied',
    /embodied \? npcs\.positionOf\(avatarName\) : null, embodied\);/.test(mainSrc), true);
  check('…and writes the uniforms exactly once per frame',
    mainSrc.split('updateOcclusion(').length - 1, 1);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
