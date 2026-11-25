#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/walk_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_walk_math.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { vectorChecks } from './embodyVectorDispatch.mjs';
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

// '../..' = the REPO root (this file lives in client3d/scripts/) — the same
// anchor smoke_enter_math.mjs and smoke_ground_math.mjs use.
const vectorCase = vectorChecks(check, ["walk_control","collide"]);

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC_DIR = join(ROOT, 'client3d/src/game');
/** The modules of MODULES that moved into the HUD workspace with the HUD page. */
const HUD_DIR = join(ROOT, 'hud/src/game');
const IN_HUD = new Set(['elevator', 'prefs', 'boot', 'soundtrack', 'voiceover', 'perfstats', 'minimap',
  'stairs', 'infoPanel']);
/** The pure modules under test. `walk.ts` and `proximity.ts` are import-free;
 *  `clickmove.ts` imports from `walk.ts` and nothing else — no `three`, no
 *  DOM. */
const MODULES = ['walk', 'clickmove', 'proximity', 'roomwalk', 'elevator', 'collide',
  'doors', 'prefs', 'boot', 'soundtrack', 'voiceover', 'polygon', 'enterLocation',
  'perfstats', 'bubble', 'minimap', 'locks', 'placement', 'ground', 'stairs', 'infoPanel'];

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
    // `scene/fogConstants.ts` is import-free too and is what `minimap.ts` reads
    // its view radius from (P4 A-T4); it lands in the same flat directory, so
    // its `../scene/` import is folded onto `./` like the sibling imports.
    const sources = [...MODULES.map((name) => [name, join(IN_HUD.has(name) ? HUD_DIR : SRC_DIR, `${name}.ts`)]),
      ['fogConstants', join(ROOT, 'hud/src/scene/fogConstants.ts')]];
    for (const [name, path] of sources) {
      const source = await readFile(path, 'utf8');
      const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
      await writeFile(join(dir, `${name}.mjs`),
        out.code.replace(/(from\s*["'])\.\.\/scene\/(fogConstants)(["'])/g, '$1./$2$3')
          .replace(/(from\s*["'])(\.\/[\w-]+)(["'])/g, '$1$2.mjs$3'), 'utf8');
    }
    const loaded = {};
    for (const name of MODULES) loaded[name] = await import(`file://${join(dir, `${name}.mjs`)}`);
    return loaded;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * ONE shared-package module, transpiled the same way. `storeyGround.ts`
 * (@anima/scene-render) is import-free arithmetic — the storey-0 ground lift
 * of § A16.9 — so the plain esbuild transpile above works for it too. It lives
 * outside `client3d/src/game`, hence its own tiny loader rather than a second
 * entry in MODULES (which would drag the whole package into that path rule).
 */
async function loadSharedModule(relPath) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'shared-'));
  try {
    const source = await readFile(join(ROOT, relPath), 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'mod.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
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
    bubble, minimap, locks, placement, ground, stairs, infoPanel } = await loadGameModules();
  const { walkDir, slideBlocked, slopeBlocks, gateStandY, groundStoreyFloors,
    terrainBlocks, terrainPace,
    moveClip, idleClip, movementOf, canRun, setMovementPoses, poseClip, publicClip, movementPoseOf, groundSink, sinkForState, floatRootY, groundWaterLevel,
    groundScope, wadeGate, swimFrom, SWIM_FROM_DEFAULT_M, MIN_PACE,
    submergedInWater, ghostCutY, ghostWaterLevel, WATER_GHOST_FROM_M,
    MOVE_EPS_M } = walk;
  const { planClickWalk, reachedGoal, goalDir, walkStalled,
    GOAL_ARRIVE_M, STALL_STEP_M } = clickmove;
  const { talkTargetNear, TALK_RANGE } = proximity;
  const { nearestRoomSwitch, idleRoomWalk, roomWalkCandidates } = roomwalk;
  const { elevatorAt, elevatorLevels, elevatorOptions, elevatorSoleOption,
    elevatorTargetRoom, ELEVATOR_RANGE } = elevator;
  const { wallSegments, clampAgainstWalls, bodyRadius, BODY_RADIUS_M,
    DOOR_EASE_M } = collide;
  const { doorMarkers, roomDoor, doorwayBetween } = doors;
  const { loadPrefs, savePrefs, DEFAULT_PREFS, PREFS_KEY, SHOW_ALL_KEY } = prefs;
  const { bootProgress, BOOT_STAGES, reportBootStage, getBootState, setBootNote,
    subscribeBoot, attributeLongTask } = boot;
  const { readManifest, emptyManifest, nightForMusic, pickMusic, pickAmbient,
    ambientTerrainFor, newTerrainSwitch, terrainSwitch, NIGHT_ON, NIGHT_OFF,
    AMBIENT_HOLD_MS } = soundtrack;
  const { sceneStampOf, newSceneLines, roomChanged, speakerOf, speakableLines,
    afterOwnLine, enqueueSpeech, createVoiceover, isNarratorLine,
    MAX_PENDING } = voiceover;
  const { minimapLayout, worldToPx, yawToCompassDeg, terrainColor,
    locationsSignature, footprintSignature, MINIMAP_PREF_KEY } = minimap;
  const { placementOf, figureTransition } = placement;
  const { stairChain, stairsAt, nearestRoomAt, stairY, stairLegTo, stairLegs,
    rideStep, STAIR_RANGE, RIDE_ARRIVE_M } = stairs;
  // The defaults are spelled out here BY HAND, never read from the module —
  // that is the whole point of pinning them (see the header).
  const DEFAULTS = {
    master: 0.8, music: 0.5, ambient: 0.6, tts: 1,
    musicOn: true, ambientOn: true, ttsOn: 'auto',
  };


  // Task 30: hand-derived ground, doorway and lift decisions moved intact.
  const decodeNpc = (v) => Array.isArray(v) ? v.map(decodeNpc)
    : v && typeof v === 'object' ? ('$number' in v ? Number(v.$number)
      : Object.fromEntries(Object.entries(v).map(([k, x]) => [k, decodeNpc(x)]))) : v;
  const npcFns = { ...walk, ...doors, ...elevator };
  const npcDispatch = { floatBodyY: (bed, level, sink) => floatRootY(bed, level, sink) - sink };
  for (const name of ['groundScope', 'terrainPace', 'sinkForState', 'groundSink',
    'floatRootY', 'wadeGate', 'ghostCutY', 'roomDoor', 'doorwayBetween',
    'elevatorLevels', 'elevatorTargetRoom']) {
    npcDispatch[name] = (...args) => npcFns[name](...decodeNpc(args));
    npcDispatch[name + 'Value'] = (args, fields) => fields.reduce(
      (v, key) => v[key], npcFns[name](...decodeNpc(args)));
  }
  const npcVectors = runVectors(loadVectors('npc_ground'), npcDispatch);
  passed += npcVectors.passed;
  failed += npcVectors.failed;

  // ---- the shared vectors (see "SHARED VECTORS" in the header): bubbles,
  // boot progress, the info panel and the scatter-pref typing. A stage list
  // becomes the Set the TS function takes, a roomOf object the Map.
  console.log('\n(vectors) shared/test-vectors/overview_hud.json');
  const hudVectors = runVectors(loadVectors('overview_hud'), {
    bubbleText: bubble.bubbleText,
    bubbleMs: bubble.bubbleMs,
    bootProgress: (stages) => bootProgress(new Set(stages)),
    infoPanelData: (loc, chars, events, roomOf, view, avatar) => infoPanel.infoPanelData(
      loc, chars, events, new Map(Object.entries(roomOf)), view ?? undefined, avatar ?? undefined),
    checkScatterPrefs: prefs.checkScatterPrefs,
    scatterLodCfgOf: prefs.scatterLodCfgOf,
  });
  passed += hudVectors.passed;
  failed += hudVectors.failed;

  // ---- figure_ground.json: [B2] [B5] [G1] [G2] [G3] (see "SHARED VECTORS").
  // A non-finite input travels as {"$number": "NaN" | "Infinity"}.
  console.log('\n(vectors) shared/test-vectors/figure_ground.json');
  const num = (v) => (v !== null && typeof v === 'object' && '$number' in v ? Number(v.$number) : v);
  const groundVectors = runVectors(loadVectors('figure_ground'), {
    placementOf: (hasTile, ...pos) => placementOf(hasTile, ...pos.map(
      (p) => (p && typeof p === 'object' ? { x: num(p.x), z: num(p.z) } : p))),
    figureTransition,
    gateStandY: (baked, declared, terrain) => gateStandY(num(baked), num(declared), num(terrain)),
    standY: (walkY, terrainY) => ground.standY(num(walkY), num(terrainY)),
    tileWalkLadder: ground.tileWalkLadder,
  });
  passed += groundVectors.passed;
  failed += groundVectors.failed;

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
  vectorCase("[1] " + ('yaw 0, w'));
  vectorCase("[1] " + ('yaw 0, s'));
  vectorCase("[1] " + ('yaw 0, d'));
  vectorCase("[1] " + ('yaw 0, a'));
  vectorCase("[1] " + ('yaw 0, w+d normalised'));
  vectorCase("[1] " + ('yaw pi/2, w'));
  vectorCase("[1] " + ('yaw pi/2, d'));
  vectorCase("[1] " + ('yaw pi/4, w'));
  vectorCase("[1] " + ('arrow keys walk like wasd'));
  vectorCase("[1] " + ('no key -> null'));
  vectorCase("[1] " + ('w+s cancel -> null'));
  vectorCase("[1] " + ('a+d cancel -> null'));
  vectorCase("[1] " + ('unrelated key -> null'));
  for (const yaw of [0, 0.3, 1.1, -2.4, Math.PI]) {
    const d = walkDir(keys('w', 'a'), yaw);
    vectorCase("[1] " + (`yaw ${yaw}: diagonal is unit length`));
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
    vectorCase("[2] " + ('a free step is unchanged'));
    vectorCase("[2] " + ('straight into the wall: the figure stands'));
    vectorCase("[2] " + ('diagonally into the wall: it slides along z'));
    const disc = (x, z) => Math.hypot(x, z) < 1;
    vectorCase("[2] " + ('a disc blocks the same way'));
    const quadrant = (x, z) => x > 0 && z > 0;
    vectorCase("[2] " + ('the tie goes to x, deterministically'));
  }

  // --- terrainBlocks (decision 2026-08-13) ---------------------------------
  // The client's half of the server's terrain gate, spelled out in the header:
  // painted ground stops the figure OUT IN THE WILDERNESS only. The two cases
  // that carry the decision are the same rock point with and without a tile
  // over it — the B1 case (a hall on a rock plateau) and the wilderness wall.
  console.log('terrainBlocks — painted ground judges the wilderness only');
  {
    vectorCase("[3] " + ('rock INSIDE a footprint is walkable (finding B1)'));
    vectorCase("[3] " + ('the same rock with no location over it blocks'));
    vectorCase("[3] " + ('walkable ground never blocks — outside'));
    vectorCase("[3] " + ('...nor inside'));
    // And the same pair once THROUGH slideBlocked, because that is how the
    // figure meets it: a rock strip 4 <= x <= 6 with a location standing on
    // its northern half (z >= 0). Walking east at z = 1 crosses it; walking
    // east at z = -1 (no tile) does not.
    const rock = (x) => x >= 4 && x <= 6;
    const tiled = (_x, z) => z >= 0;
    const blocked = (x, z) => terrainBlocks(!rock(x), tiled(x, z));
    vectorCase("[2] " + ('into the rock UNDER the location: the step goes through'));
    vectorCase("[2] " + ('into the same rock beside it: the figure stays put'));
  }

  // --- groundScope (reach decision, round 2 of 2026-08-13) -----------------
  // Most-specific-first: a room answers when there is one, otherwise the
  // footprint, otherwise the wilderness. Hand table in the header.
  console.log('groundScope — how far the terrain rule reaches');
  {
    // Migrated to npc_ground.json: [30] nothing over the point is the wilderness
    // Migrated to npc_ground.json: [30] an area location is open ground
    // Migrated to npc_ground.json: [30] a building footprint is built
    // Migrated to npc_ground.json: [30] an interior room beats the area location it stands in
    // Migrated to npc_ground.json: [30] an outdoor room beats the building it belongs to
    // Migrated to npc_ground.json: [30] a room without a footprint still answers
  }

  // --- terrainPace + moveClip (finding 3 + the round-2 reach) --------------
  // The pace and the animation of the TOPMOST terrain count in the wilderness
  // and in every OPEN place; a built place has a floor. Every number is
  // derived in the header.
  console.log('terrainPace — the ground sets the pace as far as the sky');
  {
    check('MIN_PACE is the documented 0.25', MIN_PACE, 0.25);
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
    vectorCase("[6] " + ('...which the stall detector does NOT call a stall'));
    // RED COUNTER-PROBE 1: without the clamp the same ground stalls the walk.
    const unclamped = (f, scope) => (scope === 'open' && f <= 0 ? 1 : f);
    check('RED: an unclamped 0.05 steps only 0.00283 m',
      stepFor(unclamped(0.05, 'wilderness'), leadFor()), 3.4 / 60 * 0.05);
    vectorCase("[6] " + ('...and that IS a stall — the click order would be dropped'));
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
    // Migrated to npc_ground.json: [30] ...while the rule in force wades it
    check('...and both agree out in the wilderness',
      oldRule(0.4, 'wilderness'), terrainPace(0.4, 'wilderness'));
  }

  // Spec §5.2: only walk_run selects running; swim/crawl override standing.
  console.log('movement types and fixed poses');
  for (const [movement, slow, fast, idle] of [
    ['walk_run', 'walk', 'run', ''], ['walk', 'walk', 'walk', ''],
    ['swim', 'breast-stroke', 'breast-stroke', 'treading-water'], ['crawl', 'crawl', 'crawl', 'crawl-rest'],
  ]) {
    check(`${movement} walking`, moveClip(movement, false), slow);
    check(`${movement} running`, moveClip(movement, true), fast);
    check(`${movement} idle`, idleClip(movement), idle);
    check(`${movement} can run`, canRun(movement), movement === 'walk_run');
    check(`${movement} built`, movementOf(movement, 'built'), 'walk_run');
  }
  check('invalid movement', movementOf('fly', 'open'), 'walk_run');
  check('object movement', movementOf({}, 'built'), 'walk_run');
  check('missing movement', movementOf(undefined, 'open'), 'walk_run');
  setMovementPoses({walking: {kind: 'mob1-walk', public_kind: 'walk'}});
  check('played pose', poseClip('walking'), 'mob1-walk');
  check('public pose', publicClip('walking'), 'walk');
  check('reverse played pose', movementPoseOf('mob1-walk'), 'walking');
  check('reverse public pose', movementPoseOf('walk'), 'walking');
  setMovementPoses(null);
  check('reset pose', poseClip('walking'), 'walk');
  // Junk fields independently reset to catalog defaults, never to an empty kind.
  setMovementPoses({walking: {kind: ' ', public_kind: 42}, standing: null});
  for (const [pose, kind] of [['standing', 'idle'], ['walking', 'walk'],
    ['running', 'run'], ['swimming', 'breast-stroke'], ['treading_water', 'treading-water'],
    ['crawling', 'crawl'], ['crawling_rest', 'crawl-rest']]) {
    check(`${pose} default played`, poseClip(pose), kind);
    check(`${pose} default public`, publicClip(pose), kind);
  }
  setMovementPoses({walking: {kind: ' LOCAL-WALK ', public_kind: 'shared'},
    running: {kind: 'shared', public_kind: 'run'}});
  check('pose kind normalized', poseClip('walking'), 'local-walk');
  check('played kind takes precedence over public collisions', movementPoseOf('shared'), 'running');
  check('unknown reverse kind', movementPoseOf('not-a-pose'), '');
  setMovementPoses(null);


  console.log('groundSink — how far the ground’s depth reaches');
  {
    // Migrated to npc_ground.json: [30] a lake takes 0.35 m of the moving body
    // Migrated to npc_ground.json: [30] ...an open place is the same water
    // Migrated to npc_ground.json: [30] THE REACH: a tiled hall over the lake is a floor
    // Migrated to npc_ground.json: [30] a ground without a depth sinks nobody
    // Migrated to npc_ground.json: [30] ...and neither does a negative one
    // Migrated to npc_ground.json: [30] ...nor a NaN one
    // Migrated to npc_ground.json: [30] the clamp of the catalog travels through untouched
    // RED COUNTER-PROBE, EXECUTED: the rule before the reach gate existed,
    // written out here — the depth with nothing but the "says something" test.
    const ungated = (sink) => (Number.isFinite(sink) && sink > 0 ? sink : 0);
    check('RED: the ungated rule wades the tiled hall', ungated(0.35), 0.35);
    // Migrated to npc_ground.json: [30] ...where the rule in force keeps the floor dry
    check('...and outside a built place the two agree',
      groundSink(0.35, 'wilderness'), ungated(0.35));
  }

  console.log('sinkForState — WHICH of the two depths is in force');
  {
    // The water seed of `shared/terrain/types.json`.
    const W = { move: 0.35, idle: 1.3 };
    // Migrated to npc_ground.json: [30] moving, the swimmer’s depth counts
    // Migrated to npc_ground.json: [30] ...even where the ground names no clip at all: a bog swallows ankles under a plain walk
    // Migrated to npc_ground.json: [30] waiting on a ground that names a standing clip, the treader’s does
    // Migrated to npc_ground.json: [30] THE STANDING GATE: without a ground idle clip nobody is sunk
    // Migrated to npc_ground.json: [30] a ground with no waiting depth sinks nobody while waiting
    // Migrated to npc_ground.json: [30] ...and one with no moving depth nobody while moving
    // RED COUNTER-PROBE, EXECUTED: the ONE-depth rule of finding 13, rebuilt.
    // It gives the treader whatever the swimmer got.
    const single = (moving, groundIdle, sink) =>
      (moving || groundIdle ? sink : 0);
    check('RED: with one depth the treader gets the swimmer’s 0.35',
      single(false, 'treading-water', W.move), 0.35);
    // Migrated to npc_ground.json: [30] ...where the rule in force gives it the body length it hangs
    check('...and the moving case is the one place the two agree',
      single(true, 'treading-water', W.move),
      sinkForState(true, 'treading-water', W));
  }

  console.log('floatRootY — the sink hangs under the MIRROR since E4');
  {
    const L = 3.0;
    const W = { move: 0.35, idle: 1.3 };
    // groundY at a given water depth, and what the two ends of the chain are:
    // the ROOT (what npcs.ts places) and the BODY reference (root − sink,
    // what `figures.Figure.play` drops the figure to).
    const root = (depth, sink) => floatRootY(L - depth, L, sink);
    const body = (depth, sink) => root(depth, sink) - sink;
    // The 16 root/body rows of the hand table now run from npc_ground.json.
    check('the swimmer crosses over at 0.35 m of water', root(W.move, W.move), L);
    check('...the treader only at 1.3 m — a body length before it floats',
      root(W.idle, W.idle), L);
    // Migrated to npc_ground.json: [30] OUT of the water nothing changed at all
    check('...the bog still swallows ankles from the terrain',
      floatRootY(7.25, null, 0.2) - 0.2, 7.05);
    // RED COUNTER-PROBE, EXECUTED: the pre-E4 rule, written out — the sink
    // measured from the BED. It is the user's screenshot.
    const fromBed = (depth, sink) => (L - depth) - sink;
    check('RED: measured from the bed, a 2 m lake puts the swimmer at',
      fromBed(2.0, W.move), 0.65);
    check('...i.e. 2.35 m under the water line', L - fromBed(2.0, W.move), 2.35);
    check('...where the rule in force keeps it 0.35 m under it',
      L - body(2.0, W.move), W.move);
    check('...and in water shallower than the sink the body IS the bed: '
      + 'one wades, feet on the ground', body(0.2, W.move), L - 0.2);
  }

  console.log('groundWaterLevel — the mirror reaches as far as the sink does');
  {
    check('wilderness: the lake counts', groundWaterLevel(3, 'wilderness'), 3);
    check('...an open place is the same water', groundWaterLevel(3, 'open'), 3);
    check('THE REACH: a tiled hall over the lake is a floor',
      groundWaterLevel(3, 'built'), null);
    check('a sea at world zero is still a level', groundWaterLevel(0, 'open'), 0);
    check('no lake, no level', groundWaterLevel(null, 'open'), null);
    check('a NaN is no level', groundWaterLevel(NaN, 'wilderness'), null);
  }

  console.log('wadeGate — swimming starts at a DEPTH, not at a kind (W4c)');
  {
    // The river seed of `shared/terrain/types.json`, and a mirror at L = 5.
    const L = 5.0;
    const RIVER = { movement: 'swim',
      sink: { move: 0.35, idle: 1.3 }, water: L };
    const WADED = { movement: 'walk_run', sink: { move: 0, idle: 0 },
      water: null };
    // The whole chain at one depth, exactly as npcs.ts runs it: gate the word,
    // then ask the unchanged rules what clip, what sink and what root come out.
    const at = (depth, swim, moving) => {
      const groundY = L - depth;
      const g = wadeGate({ ...RIVER }, groundY, swim);
      const groundIdle = idleClip(g.movement);
      const sink = groundSink(sinkForState(moving, groundIdle, g.sink),
        'wilderness');
      return {
        clip: moving ? moveClip(g.movement, false)
          : (groundIdle || 'idle'),
        sink,
        root: floatRootY(groundY, g.water, sink),
      };
    };
    // Migrated to npc_ground.json: [30] depth 0.4 m at a 1 m threshold: the gate hands back NOTHING
    check('...so a MOVING figure walks the ford, unsunk, on the bed',
      at(0.4, 1.0, true), { clip: 'walk', sink: 0, root: 4.6 });
    check('...and a WAITING one keeps its own standing clip on the bed',
      at(0.4, 1.0, false), { clip: 'idle', sink: 0, root: 4.6 });
    // Migrated to npc_ground.json: [30] depth 1.0 m IS the threshold — the word passes through
    // A water ground that does not swim (no `movement`, i.e. walk_run) is
    // gated the same way: shallow, its mirror goes, so the figure stands on
    // the bed instead of on the surface (floatRootY = max(bed, mirror)).
    // Migrated to npc_ground.json: [30] a walk_run water ground wades in the shallows too
    check('...moving: the swim clip, 0.35 under the mirror',
      at(1.0, 1.0, true), { clip: 'breast-stroke', sink: 0.35, root: 5.0 });
    check('...waiting: treading water, and a 1.3 m foot still finds the '
      + '1.0 m bed', at(1.0, 1.0, false),
    { clip: 'treading-water', sink: 1.3, root: 5.3 });
    check('depth 1.6 m: swimming, moving',
      at(1.6, 1.0, true), { clip: 'breast-stroke', sink: 0.35, root: 5.0 });
    check('...and treading water, feet off the bed at last',
      at(1.6, 1.0, false),
      { clip: 'treading-water', sink: 1.3, root: 5.0 });
    // A KIND WITHOUT THE FIELD reads the module default of one metre, so the
    // three rows above hold for it unchanged (`ground.typeAt` uses `swimFrom`).
    check('the default threshold is one metre', SWIM_FROM_DEFAULT_M, 1.0);
    check('a kind that names none answers it', swimFrom(undefined), 1.0);
    check('...and so does a junk one', swimFrom('deep'), 1.0);
    check('...and a negative one', swimFrom(-2), 1.0);
    check('...while an authored 0 is kept: swim from the very rim',
      swimFrom(0), 0);
    check('the unauthored kind wades the 0.4 m ford like the seed does',
      wadeGate({ ...RIVER }, L - 0.4, swimFrom(undefined)), WADED);
    check('...and swims its 1.6 m the same way',
      wadeGate({ ...RIVER }, L - 1.6, swimFrom(undefined)), RIVER);
    // Migrated to npc_ground.json: [30] a threshold of 0 swims the ankle-deep rim — the pre-W4c water
    // NOT WATER, NOT GATED — the case that keeps the rule out of every other
    // ground: with no mirror there is no depth to measure.
    const BOG = { movement: 'walk_run', sink: { move: 0.2, idle: 0.2 },
      water: null };
    // Migrated to npc_ground.json: [30] a bog carries no mirror, so nothing is taken from it
    check('...it still swallows ankles while walking',
      sinkForState(true, '', wadeGate({ ...BOG }, 4.6, 1.0).sink), 0.2);
    // Migrated to npc_ground.json: [30] a NaN bed decides nothing either — the word survives
    // RED COUNTER-PROBE, EXECUTED: the pre-W4c rule is no gate at all.
    const ungated = (word) => word;
    check('RED: ungated, the 0.4 m ford is swum',
      moveClip(ungated({ ...RIVER }).movement, false), 'breast-stroke');
    check('...where the rule in force walks it', at(0.4, 1.0, true).clip,
      'walk');
    check('...and in real water the two agree', at(1.6, 1.0, true).clip,
      moveClip(ungated({ ...RIVER }).movement, false));
  }

  // --- submergedInWater: the underwater ghost's gate (finding H3) -----------
  // WHAT IT IS FOR. Since Wasser v2 K-A the water surface IS the terrain, and
  // the terrain is opaque: a figure standing in a river is cut off at the
  // waterline and reads as buried. `figures.Figure.setSubmerged` draws it a
  // second time with depthFunc GreaterDepth — only where the normal pass LOST
  // the depth test, i.e. only the submerged part — and this predicate is the
  // whole decision about who gets that draw.
  //
  // IT IS DELIBERATELY NOT `wadeGate`'s ANSWER. That gate nulls the mirror
  // below the kind's swim depth, because a wader keeps its own clips and
  // stands on the bed — and a WADER is exactly the figure the opaque surface
  // cuts in half. So the ghost reads the UNGATED level: `groundWaterLevel`
  // (scope only), never `wadeGate`.
  //
  // THE THRESHOLD is 0.05 m, the depth from which the water LOOK stands at its
  // full rim ramp (`waterPlaneMath.WATER_EDGE_FADE_M`). Below it the surface is
  // still fading in and cuts nothing off, so a ghost there would be a second
  // body drawn for nothing — and one that flickers with every centimetre of
  // the walk. Hand table, bed at 12.00 m:
  //
  //     water null   -> false   (dry ground)
  //     water 11.90  -> false   (mirror UNDER the bed)
  //     water 12.00  -> false   (exactly the waterline: 0.00 < 0.05)
  //     water 12.04  -> false   (4 cm)
  //     water 12.05  -> true    (5 cm: the rim ramp is up)
  //     water 12.60  -> true    (a ford, knee deep — the wader)
  //     water 13.50  -> true    (a swimmer, cut at the chest)
  console.log('submergedInWater — who gets the underwater ghost (H3)');
  {
    const BED = 12.0;
    check('the threshold is the water look\'s own rim depth',
      WATER_GHOST_FROM_M, 0.05);
    check('dry ground carries no mirror at all',
      submergedInWater(BED, null), false);
    check('...nor does a scope-cut one (groundWaterLevel already said null)',
      submergedInWater(BED, groundWaterLevel(13.5, 'built')), false);
    check('a mirror UNDER the bed is not water over the figure',
      submergedInWater(BED, 11.9), false);
    check('exactly at the waterline: nothing is cut off yet',
      submergedInWater(BED, 12.0), false);
    check('...4 cm, still under the rim ramp', submergedInWater(BED, 12.04),
      false);
    check('5 cm: the surface stands at full and the ghost comes on',
      submergedInWater(BED, 12.05), true);
    check('a knee-deep ford — the WADER, and the whole point of the ghost',
      submergedInWater(BED, 12.6), true);
    check('...and a swimmer, cut at the chest', submergedInWater(BED, 13.5),
      true);
    check('a NaN bed decides nothing', submergedInWater(NaN, 13.5), false);
    check('...and neither does a NaN mirror', submergedInWater(BED, NaN),
      false);
    // RED: the WADE gate is the wrong question — it hands back null for the
    // very ford this ghost exists for, so a figure gated that way would be cut
    // in half exactly where the finding was reported.
    const L = 12.6;
    const FORD = { movement: 'swim',
      sink: { move: 0.35, idle: 1.3 }, water: L };
    // Migrated to npc_ground.json: [30] RED: the wade gate calls a 0.6 m ford no water at all
    check('RED: ...so gating the ghost on IT would leave the wader cut',
      submergedInWater(BED, wadeGate({ ...FORD }, BED, 1.0).water), false);
    check('...while the ungated level gives the wader its body back',
      submergedInWater(BED, groundWaterLevel(L, 'wilderness')), true);
    // …and the deep case agrees either way, which is what makes the difference
    // a WADING one and not a change of rule.
    check('a swimmer is submerged through both readings',
      submergedInWater(BED, wadeGate({ ...FORD, water: 13.5 }, BED, 1.0).water)
        && submergedInWater(BED, groundWaterLevel(13.5, 'wilderness')), true);
  }

  // --- ghostCutY: the same gate, and the LINE it answers --------------------
  // WHY IT EXISTS. Every ghost site needs the pair "is it submerged" AND "at
  // which world Y does the second draw stop" — the ghost discards everything
  // above `uGhostCutY`, so a boolean is not enough. That pair used to be
  // written out as `submergedInWater(b, l) ? l : null` at each site, and since
  // the user decision of 2026-08-25 there are four of them and not two: the two
  // figure sites in `scene/npcs.ts`, the world props (`scene/worldProps.ts`,
  // mount + redrape) and the scene placements (`scene/sceneRecipe.ts`, mount +
  // reliftScene + tier swap). One function, so none of them can hand in the
  // GATED level, a boolean, or the bed.
  //
  // The table is the one above, read as a cut line — no new threshold, no new
  // rule. `base` is what the thing STANDS ON: a figure's bed, a world prop's
  // `worldPropBottom`, a scene placement's `tile.center.y + bottom_y + lift`.
  //
  //     base 12.00, water null   -> null    (dry ground)
  //     base 12.00, water 11.90  -> null    (mirror UNDER the base)
  //     base 12.00, water 12.00  -> null    (exactly the waterline)
  //     base 12.00, water 12.04  -> null    (4 cm)
  //     base 12.00, water 12.05  -> 12.05   (5 cm: the rim ramp is up)
  //     base 12.00, water 12.60  -> 12.60   (a crate on a knee-deep ford's bed)
  //     base 12.00, water NaN    -> null    (a raster that knows nothing)
  console.log('ghostCutY — the gate and the waterline it cuts at');
  {
    const BASE = 12.0;
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
    check('RED: the cut is not the base', ghostCutY(BASE, 12.6) === BASE,
      false);
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
  }

  // --- ghostWaterLevel: the ghost asks what the WATER asks (2026-08-27) -----
  // THE BUG. At a shore location the placed diorama was drawn half transparent
  // although it stood on dry land, while the avatar beside it was solid. Both
  // gates were `submergedInWater(base, level)`, but they read different fields:
  // the figure gets its level through `ground.typeAt`, a polygon-inside test,
  // and the placement got the raster LEVEL — which the server DILATES 4 m past
  // every authored outline (`app/core/heightfield.py`, § A16.5). Since the bank
  // clamp was retired (K-A E6) the ground in that collar sits up to 0.772 m
  // under the dilated mirror, and the ghost trips at 0.05 m. So it fired on
  // ground the terrain draws as bank.
  //
  // THE FIELD THAT ANSWERS "INSIDE" is the signed distance, and the terrain
  // already uses it: `terrainLod.liftedHeight` scales the water lift by
  // `waterShade.waterInside(sd)` = smoothstep(0, 0.5, sd), i.e. with
  // t = clamp(sd/0.5, 0, 1), the value t²(3−2t):
  //
  //     sd = -1    -> t = 0    -> 0        (1 m outside: the dilation collar)
  //     sd =  0    -> t = 0    -> 0        (exactly ON the authored waterline)
  //     sd =  0.05 -> t = 0.1  -> 0.028
  //     sd =  0.25 -> t = 0.5  -> 0.5      (half the band in)
  //     sd =  2    -> t = 1    -> 1        (full water)
  //
  // (those five are re-derived in client3d/scripts/smoke_water_shade.mjs
  // against `waterInside` itself; here they are the INPUT, because `walk.ts`
  // must stay import-free and a second copy of the smoothstep in it is exactly
  // the twin rule that let the two gates drift apart in the first place.)
  //
  // `ghostWaterLevel(level, insideness)` therefore returns the level where the
  // picture draws water and `NaN` — the raster's own "nothing here" — where it
  // does not, and `ghostCutY` is left to judge the depth. BOTH must pass.
  //
  //     level 12.30, inside 0     -> NaN     -> ghostCutY(12.00, ·) = null
  //     level 12.30, inside 0.5   -> 12.30   -> ghostCutY(12.00, ·) = 12.30
  console.log('ghostWaterLevel — no ghost outside the authored outline');
  {
    const BASE = 12.0;
    const LEVEL = 12.3;            // 0.30 m over the base: six times the gate
    const inside = (sd) => {       // the hand-derived smoothstep, see above
      const t = Math.min(Math.max(sd / 0.5, 0), 1);
      return t * t * (3 - 2 * t);
    };
    check('sd = -1: the dilation collar is not water', inside(-1), 0);
    check('...so the level is withdrawn', Number.isNaN(
      ghostWaterLevel(LEVEL, inside(-1))), true);
    check('...and 0.30 m of "water" over a bank prop makes NO ghost',
      ghostCutY(BASE, ghostWaterLevel(LEVEL, inside(-1))), null);
    check('sd = 0: ON the waterline the ramp is still 0', inside(0), 0);
    check('...so the outline itself carries no ghost either',
      ghostCutY(BASE, ghostWaterLevel(LEVEL, inside(0))), null);
    check('sd = 0.25: half the band in, the ramp is 0.5', inside(0.25), 0.5);
    check('...the level passes through untouched',
      ghostWaterLevel(LEVEL, inside(0.25)), LEVEL);
    check('...and the cut is the usual waterline',
      ghostCutY(BASE, ghostWaterLevel(LEVEL, inside(0.25))), 12.3);
    check('sd = 2: full water', inside(2), 1);
    check('...and the cut is the same line',
      ghostCutY(BASE, ghostWaterLevel(LEVEL, inside(2))), 12.3);
    // The tiniest bit inside is already inside: the ramp only has to be > 0,
    // the DEPTH is `ghostCutY`'s question and nobody else's.
    check('sd = 0.05: a ramp of 0.028 is still inside', inside(0.05), 0.028);
    check('...so a shallow rim inside the outline does get its ghost',
      ghostCutY(BASE, ghostWaterLevel(LEVEL, inside(0.05))), 12.3);
    // …and the depth gate keeps its veto inside the outline.
    check('inside the outline, 2 cm of water is still no ghost',
      ghostCutY(BASE, ghostWaterLevel(12.02, inside(2))), null);
    check('a raster that knows no level is dry however far inside',
      ghostCutY(BASE, ghostWaterLevel(NaN, inside(2))), null);
    // THE RED PROBE — the bug itself, in numbers. The measured shore case:
    // the bank ground sits 0.772 m under the dilated mirror (§ K-A E6 addendum)
    // and lies 1 m OUTSIDE the outline. The old gate saw only the level.
    // Migrated to npc_ground.json: [30] RED: the old level-only gate ghosted the bank diorama
    check('...the gate that asks the outline too leaves it solid',
      ghostCutY(BASE, ghostWaterLevel(BASE + 0.772, inside(-1))), null);
  }

  // --- slopeBlocks (E8 task 1) ---------------------------------------------
  // The height gate as a pure predicate, mirroring `relief.slope_blocks`.
  // Every number is derived in the header; the limits are the world defaults.
  console.log('slopeBlocks — the slope always, the step on top below one metre');
  {
    const STEP = 0.4;
    const SLOPE = 40;
    vectorCase("[4] " + ('the steep shore: 1.2 m over 0.5 m is a wall'));
    vectorCase("[4] " + ('the flat beach: 0.3 m over 2 m (8.53 deg) is walked'));
    vectorCase("[4] " + ('a 0.3 m step under the cap passes'));
    vectorCase("[4] " + ('the cap itself passes (strictly greater blocks)'));
    vectorCase("[4] " + ('a DROP is never judged — only climbing is (rule 2026-08-28)'));
    vectorCase("[4] " + ('...nor a 0.9 m drop over 0.5 m'));
    vectorCase("[4] " + ('...nor three metres straight down over one'));
    vectorCase("[4] " + ('but the SAME 0.9 m upwards over 0.5 m is a step'));
    vectorCase("[4] " + ('45 deg over 2 m is refused'));
    vectorCase("[4] " + ('38.66 deg over the same 2 m is not'));
    vectorCase("[4] " + ('...and the very same rise a hair under the metre is a step'));
    vectorCase("[4] " + ('one metre exactly is already a slope (26.57 deg)'));
    vectorCase("[4] " + ('...0.999 m of it is a 0.5 m step and blocks'));
    vectorCase("[4] " + ('level ground never blocks, at any distance'));
    vectorCase("[4] " + ('a world with the limits wide open lets the cliff through'));
    // THE TWO REGIME CASES (findings F1/F2) — the step limit alone is blind
    // to both, and the client is where the first one bites: it walks in leads
    // of ~0.15 m while the server judges ~1.12 m report steps.
    vectorCase("[4] " + ('one 0.15 m lead up a 50.19° wall is blocked here too'));
    vectorCase("[4] " + ('...and crawling 0.4 m per 0.1 m does not climb 75.96° either'));
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

  // --- gateStandY: WHAT THE HEIGHT GATE MEASURES (plan-huette-dach task 2) --
  // The rungs the gate compares are derived in the header; the numbers here
  // are the Mondscheinhütte case, by hand.
  console.log('gateStandY — the gate stands on the lattice, like the server');
  {
    const STEP = 0.4;
    const SLOPE = 40;
    // Flat terrain at 0, a hut whose baked lattice answers its roof at 2.5 m.
    // [G1] The single-call cases (0 off the lattice, 2.5 on it, the
    // declaration rung, the terrain floor and the NaN fall-throughs) run from
    // figure_ground.json; the two heights are composed into the climb here.
    const outside = gateStandY(null, null, 0);         // no rung but the ground: 0
    const onRoof = gateStandY(2.5, null, 0);           // rung 0 answers 2.5
    // THE CLIMB the server refuses: 2.5 m up, over a 0.15 m walking lead
    // (step: 2.5 > 0.4) and over a 1.12 m report step (slope: 65.8676° > 40).
    vectorCase("[4] " + ('a 2.5 m lattice is a wall over a 0.15 m lead'));
    vectorCase("[4] " + ('...and over a 1.12 m report step as well'));
    // THE COUNTER-PROBE (409b4f3e): coming back down is never judged.
    vectorCase("[4] " + ('stepping off the same roof is free'));
    // RED: the terrain-only ladder the gate used until this task. Both points
    // read 0, the step is invisible here and the server refuses it — the
    // figure walks up and is snapped back three times a second.
    vectorCase("[4] " + ('RED: terrain only sees no step at all'));
    // [G1] RUNG 1, where no lattice answers: the room's own declared floor, a
    // podium 1.2 m over the flat ground (1.2; under a 2.5 lattice 2.5, ruling
    // R1). RUNG 2 is also the LOWER BOUND (Entscheid 5): a hollow in a
    // diorama never sinks the gate below the ground (−0.5 over terrain 0.3 ->
    // 0.3, lattice or declaration). A sampler with nothing to say is not a
    // height: NaN neither becomes a rung (NaN, 1.2, 0 -> 1.2; NaN, NaN, 0.3
    // -> 0.3) nor drags the answer to NaN (2.5, null, NaN -> 2.5). Those
    // seven cases run from figure_ground.json.

    // --- groundStoreyFloors: RUNG 1 IS STOREY 0 ONLY (review finding 1) ----
    // The server's declaration list is built from storey-0 rooms alone
    // (`model_surface._declarations`), while `tile.declaredFloors` is the
    // DRAWING list and carries every storey. A two-storey house on flat
    // ground, datum 0, terrain 0:
    //   hall,  level 0, walk_y 0.0, hull 12 x 12 m  (area 144)
    //   attic, level 1, walk_y 3.3, hull  6 x  6 m  (area  36, INSIDE the hall)
    // At (0, 0) both hulls contain the point and the SMALLER one wins the
    // most-specific tie-break — so unfiltered the gate stands the walker on
    // the attic floor: dh 3.3 against the ground outside, atan(3.3/1.12) =
    // 71.2531° over a report step, refused where the server (which never sees
    // the attic here) reads 0.0 and lets it through. That is the inverted
    // desync of this same bug, and the filter is what keeps both sides on one
    // number.
    const pickDeclared = ground.declaredFloorAt;
    const square = (h) => [[-h, -h], [h, -h], [h, h], [-h, h]];
    const HOUSE = [
      { roomId: 'hall', top: 0.0, outline: square(6) },
      { roomId: 'attic', top: 3.3, outline: square(3) },
    ];
    const levelOf = (id) => ({ hall: 0, attic: 1 })[id];
    vectorCase("[5] " + ('the upper storey drops out of the gate\'s list'));
    check('...so the gate stands on the ground floor',
      gateStandY(null, pickDeclared(groundStoreyFloors(HOUSE, levelOf), 0, 0), 0),
      0);
    vectorCase("[4] " + ('...and the step in from outside is free, as on the server'));
    check('RED: unfiltered, the attic hull wins the tie-break',
      pickDeclared(HOUSE, 0, 0), 3.3);
    vectorCase("[4] " + ('RED: ...and the gate refuses a step the server accepts'));
    // A BASEMENT is not storey 0 either — the server's test is `!= 0`.
    vectorCase("[5] " + ('a basement is dropped just like an upper floor'));
    // `int(level or 0)` reads a missing level as storey 0; a room the tile
    // knows no level for is read the same way, so a scene whose room list has
    // not landed yet does not silently lose its ground floor.
    vectorCase("[5] " + ('a room with no level known is on storey 0'));
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
    vectorCase("[6] " + ('GOAL_ARRIVE_M'));
    vectorCase("[6] " + ('STALL_STEP_M'));
    vectorCase("[6] " + ('a clear click gives the point itself'));
    vectorCase("[6] " + ('a blocked point plans nothing (the click falls through)'));
    vectorCase("[6] " + ('a click where one stands plans nothing either'));
    vectorCase("[6] " + ('arrived inside the threshold'));
    vectorCase("[6] " + ('...and not outside it'));
    vectorCase("[6] " + ('the direction and the distance left'));
    vectorCase("[6] " + ('no direction to a point one is on'));
    vectorCase("[6] " + ('half a frame of walking is a stall'));
    vectorCase("[6] " + ('a whole frame is not'));
  }

  console.log('talkTargetNear — who the avatar may address by walking up (task 5)');
  {
    /** avatar/other shorthands: outdoors in location L1 unless said otherwise */
    const me = (x, z, extra = {}) =>
      ({ name: 'Avatar', pos: { x, z }, locId: 'L1', room: null, ...extra });
    const npc = (name, x, z, extra = {}) =>
      ({ name, pos: { x, z }, locId: 'L1', room: null, scale: 1, ...extra });

    /** WHO the rule names — the offer itself is `{name, dist}` since the F
     *  key answers the NEAREST of the four standing offers (`game/offers.ts`)
     *  and needs the metres to compare. The distance is checked on its own
     *  below; every case here is about WHO, and reads better without it. */
    const talkName = (avatar, others) => talkTargetNear(avatar, others)?.name ?? null;

    vectorCase("[7] " + ('TALK_RANGE is the documented 2.5 m'));
    vectorCase("[7] " + ('2.0 m away -> in range'));
    vectorCase("[7] " + ('3.0 m away -> out of range'));
    vectorCase("[7] " + ('exactly 2.5 m still counts'));
    // 3-4-5: (1.5, 2.0) is exactly 2.5 m away, (1.8, 2.4) is 3.0 m.
    vectorCase("[7] " + ('diagonal 1.5/2.0 = 2.5 m -> in range'));
    vectorCase("[7] " + ('diagonal 1.8/2.4 = 3.0 m -> out of range'));
    vectorCase("[7] " + ('nobody around -> null'));

    vectorCase("[7] " + ('another location, same distance -> null'));
    vectorCase("[7] " + ('another shown room, 1 m away through the wall -> null'));
    vectorCase("[7] " + ('same shown room -> in range'));
    vectorCase("[7] " + ('avatar outdoors, NPC drawn inside a room -> null'));
    vectorCase("[7] " + ('avatar inside, NPC drawn outdoors -> null'));

    // Interior scale 0.3: the range shrinks with the figures, 2.5 * 0.3 = 0.75.
    vectorCase("[7] " + ('scale 0.3: 0.7 m -> in range (radius 0.75)'));
    vectorCase("[7] " + ('scale 0.3: 0.8 m -> out of range'));
    vectorCase("[7] " + ('scale 0.3: 2.0 m would be in range at scale 1, but is not here'));

    vectorCase("[7] " + ('the nearer of two wins'));
    vectorCase("[7] " + ('order of the list does not matter'));
    vectorCase("[7] " + ('the nearer one is out of range -> the other one is not taken either'));
    vectorCase("[7] " + ('equal distance -> the name decides (no 1 Hz flicker)'));

    vectorCase("[7] " + ('the avatar itself is never a candidate'));
    vectorCase("[7] " + ('alone with itself -> null'));

    // THE MEASURED DISTANCE, hand-derived: (1.5, 2.0) is 2.5 m by 3-4-5, and
    // the nearer of two is 1.2 m straight along z. It is what decides this
    // offer against the lift, the stairs and the location entry
    // (`scripts/smoke_offer_resolve.mjs`).
    vectorCase("[7] " + ('the offer carries the distance it was measured at'));
    vectorCase("[7] " + ('...of the NEAREST candidate, not of the first'));
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

    vectorCase("[8] " + ('idleRoomWalk is the empty clock'));
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

  console.log('roomWalkCandidates — the corridor is the fallback of its storey (§ A13b)');
  {
    const rooms = [{ id: 'k1', level: -1, center: { x: -2.5, z: -2.5 } },
                   { id: 'k2', level: -1, center: { x: 2.5, z: -2.5 } }];
    const base = { current: 'k1', ownLevel: -1, pos: { x: 0, z: 2 }, rooms,
      insideRect: () => false, insideLevelOutline: () => true, groundId: '__ground__',
      floorIdOf: (lv) => (lv === -1 ? '__floor__-1' : '') };
    // outside both rectangles on storey -1 -> the corridor, level -1, centre = pos
    check('cellar -> corridor', roomWalkCandidates(base).map((r) => r.id), ['__floor__-1']);
    check('corridor carries the storey', roomWalkCandidates(base)[0].level, -1);
    check('corridor stands where the figure does', roomWalkCandidates(base)[0].center,
      { x: 0, z: 2 });
    // inside k2's rectangle -> k2 alone, the corridor is no candidate
    check('inside k2', roomWalkCandidates({ ...base, insideRect: (id) => id === 'k2' }).map((r) => r.id), ['k2']);
    // storey 0 with a hallway: inside the plate outline -> hallway, outside -> ground
    const g = { ...base, ownLevel: 0, floorIdOf: (lv) => (lv === 0 ? '__floor__0' : '') };
    check('hallway inside outline', roomWalkCandidates(g).map((r) => r.id), ['__floor__0']);
    check('yard outside outline', roomWalkCandidates({ ...g, insideLevelOutline: () => false }).map((r) => r.id), ['__ground__']);
    // storey 0 without a hallway (no opt-in) -> the ground, as before
    check('no hallway -> ground', roomWalkCandidates({ ...g, floorIdOf: () => '' }).map((r) => r.id), ['__ground__']);
    // locked corridor -> falls through to the room list (the old behaviour), never the corridor
    check('locked corridor', roomWalkCandidates({ ...base, floorIdOf: () => '' }).map((r) => r.id), ['k1', 'k2']);
    // a LOCKED ground on storey 0 is no fallback either — the same fall-through
    check('locked ground', roomWalkCandidates({ ...g, floorIdOf: () => '', groundId: '' }).map((r) => r.id), ['k1', 'k2']);
    // no storey known yet (no room at all) reads as the ground storey, as it always has
    check('no storey -> ground rule', roomWalkCandidates({ ...base, ownLevel: undefined }).map((r) => r.id), ['__ground__']);
    // no scene yet -> nothing
    check('no rooms', roomWalkCandidates({ ...base, rooms: [] }), []);
  }
  console.log('nearestRoomAt / elevatorTargetRoom — the lift opens into the corridor');
  {
    const rooms = [{ id: 'k1', level: -1, center: { x: -2.5, z: -2.5 } },
                   { id: '__floor__-1', level: -1, center: { x: 3, z: -3 }, floor: true },
                   { id: 'eg', level: 0, center: { x: -2, z: -2.5 } }];
    const stops = [{ level: -1, pos: { x: 3, z: -3 } }, { level: 0, pos: { x: 3, z: -3 } }];
    // stop at (3,-3): k1 is hypot(5.5, 0.5) = 5.52 m away, the corridor 0 m —
    // and even from k1's own centre (where the corridor is 5.52 m off) the
    // corridor wins, because a storey's corridor beats every distance.
    // Migrated to npc_ground.json: [30] lift -> corridor
    // Migrated to stairs.json: [S6] corridor beats distance
    // Migrated to npc_ground.json: [30] storey without corridor -> nearest room
    // Migrated to npc_ground.json: [30] levels served count the corridor
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
  const RIDE_MS = 4000;        // main.ts VERTICAL_RIDE_MS
  const RIDE_ARRIVE = 0.2;     // main.ts VERTICAL_ARRIVE
  const ROOM_HOLD = 1.5;       // main.ts ROOM_HOLD_SECONDS
  /**
   * @param opts.rideOwnsFigure  finding 1: steering is ignored while the ride runs
   * @param opts.honourCooldown  finding 2: `roomRejectedUntil` gates the ride
   * @param opts.rejected        {roomId: untilMs}, judged at the press (t = 0)
   * @param opts.dir             key direction held for the whole run, or null
   * @param opts.pressAt         ms of ONE more F press during the run, or undefined
   * @param opts.interlock       task 4 review: a running ride makes no offer and
   *                             refuses a second ride (false = the old behaviour)
   * @param opts.stopY           height of each storey's holding point, by level
   * @param opts.staleStairs     {room, x, z, y} a stairs offer the 1 Hz tick has
   *                             not cleared yet — what the F chain reaches once
   *                             the lift chip is gone
   * @param opts.stairsGuard     `rideStairs` carries the same `verticalRide`
   *                             guard (false = the old behaviour)
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
    let pressed = false;
    let offerAtPress;
    let stairsPress;
    for (let i = 1; i <= opts.frames; i++) {
      const now = i * DT * 1000;
      // --- the F key, once, in the middle of the ride (task 4 review) ---
      // With the direct ride of a two-storey house, F is answered by whatever
      // offer stands. `updateElevator` therefore clears the offer for as long
      // as the ride owns the figure, and `rideElevator` refuses to start a
      // second one — without that pair the offer names the storey just LEFT
      // (the avatar's room is already the target one) and the press turns the
      // ride around in mid-flight.
      if (opts.pressAt !== undefined && !pressed && now >= opts.pressAt) {
        pressed = true;
        const lv = rooms.find((r) => r.id === current)?.level ?? 0;
        const riding = opts.interlock !== false && !!ride;
        offerAtPress = riding
          ? null : elevatorAt({ x: pos.x, z: pos.z }, lv, opts.stops, rooms, 1);
        const sole = offerAtPress ? elevatorSoleOption(offerAtPress) : null;
        if (sole !== null && !riding) {
          const back = elevatorTargetRoom(sole, opts.stops, rooms);
          const stopBack = opts.stops.find((s) => s.level === sole);
          if (back && stopBack) {
            requests.push({ at: now, room: back });
            current = back;
            goal.x = stopBack.pos.x; goal.z = stopBack.pos.z;
            goal.y = opts.stopY?.[sole] ?? 0;
            if (opts.rideOwnsFigure) ride = { until: now + RIDE_MS };
            roomWalk = idleRoomWalk();
          }
        } else if (!offerAtPress && opts.staleStairs) {
          // F is a priority CHAIN (talk → lift → stairs): with the lift chip
          // cleared for the ride, the press reaches a stairs offer that the
          // 1 Hz tick has not dropped yet. `rideStairs` carries the same
          // `verticalRide` guard, so a running ride refuses the climb too.
          const barredByRide = opts.stairsGuard !== false && !!ride;
          stairsPress = barredByRide ? 'refused' : 'ridden';
          if (!barredByRide) {
            requests.push({ at: now, room: opts.staleStairs.room });
            current = opts.staleStairs.room;
            goal.x = opts.staleStairs.x; goal.z = opts.staleStairs.z;
            goal.y = opts.staleStairs.y;
            if (opts.rideOwnsFigure) ride = { until: now + RIDE_MS };
            roomWalk = idleRoomWalk();
          }
        }
      }
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
    return { requests, pos, current, arrivedAt, offerAtPress, stairsPress };
  }

  // --- the elevator OFFER (E3) and its sole option (Treppen v2 task 4) -----
  // The header cases of this file, now measured instead of merely written
  // down. Layout: holding points at (2,0) on both storeys, rooms hall (0,0)
  // and store (8,0) on storey 0, attic (1,0) and loft (6,0) on storey 1.
  console.log('elevator offer — the holding point of one\'s OWN storey, scaled range');
  {
    const STOPS = [{ level: 0, pos: { x: 2, z: 0 } }, { level: 1, pos: { x: 2, z: 0 } }];
    const ROOMS = [
      { id: 'hall', level: 0, center: { x: 0, z: 0 } },
      { id: 'store', level: 0, center: { x: 8, z: 0 } },
      { id: 'attic', level: 1, center: { x: 1, z: 0 } },
      { id: 'loft', level: 1, center: { x: 6, z: 0 } },
    ];
    const at = (x, level, scale, stops = STOPS, rooms = ROOMS) =>
      elevatorAt({ x, z: 0 }, level, stops, rooms, scale);

    vectorCase("[10] " + ('range is 1.5 figure metres'));
    // Migrated to npc_ground.json: [30] both storeys have a stop AND a room
    check('0.9 m at scale 1 is inside the range', at(2.9, 0, 1),
      { levels: [0, 1], current: 0, dist: 0.9 });
    check('...1.5 m IS the range and is already out (strict)', at(3.5, 0, 1), null);
    check('...1.6 m is out', at(3.6, 0, 1), null);
    check('0.4 m at scale 0.3 is inside 0.45', at(2.4, 0, 0.3),
      { levels: [0, 1], current: 0, dist: 0.4 });
    check('...0.5 m is out', at(2.5, 0, 0.3), null);
    // Migrated to npc_ground.json: [30] a stop on a storey without a room does not count
    check('one storey left is no ride at all',
      at(2.9, 0, 1, STOPS, ROOMS.filter((r) => r.level === 0)), null);
    check('a storey with a room but no stop has no holding point to stand at',
      at(2.9, 3, 1, STOPS, [...ROOMS, { id: 'shed', level: 3, center: { x: 0, z: 0 } }]), null);
    vectorCase("[10] " + ('the own storey is never offered as a destination'));
    // Migrated to npc_ground.json: [30] the ride ends in the room nearest that storey's stop
    // Migrated to npc_ground.json: [30] ...and downwards likewise

    // Two storeys: one option, so F rides it instead of unfolding a picker
    // with a single button.
    vectorCase("[10] " + ('two storeys, standing below: the sole option is up'));
    vectorCase("[10] " + ('...standing above: the sole option is down'));
    vectorCase("[10] " + ('three storeys leave a choice, so there is no sole option'));
    vectorCase("[10] " + ('and the offer of a two-storey house carries exactly that one option'));
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
      honourCooldown: true, stopY: { 0: 0, 1: 3 }, ...extra,
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

    // --- a second F WHILE the lift runs (Treppen v2 task 4 review) ---------
    // Since two storeys are ridden by the F key itself, the standing offer is
    // what the key answers — and the offer of a running ride names the storey
    // just LEFT: the server has already put the avatar in the target room, so
    // `elevatorAt` reports `current` = 1 and its sole option is 0. Numbers of
    // the press at 300 ms = frame 18 (18 · 1000/60 = 300):
    //   the height blend has run 17 ticks by then:
    //     y = 3 · (1 − (14/15)^17) = 3 · 0.690516 = 2.0716
    //   turned around, the goal is storey 0 (y = 0) and y decays by 14/15 per
    //   tick; |0 − y| < 0.2 first holds after k ticks with
    //     2.0716 · (14/15)^k < 0.2  →  k = 34   (k = 33 gives 0.2126)
    //   so the reverse ride "arrives" at frame 18 + 34 = 52, i.e. 866.67 ms,
    //   at y = 2.0716 · (14/15)^34 = 0.1984 — back down where it started.
    console.log('elevator ride — a second F cannot turn the ride around (task 4 review)');
    const held = rideTo1({ rideOwnsFigure: true, pressAt: 300 });
    check('while the lift owns the figure there is no offer to press',
      held.offerAtPress ?? null, null);
    check('...so the press asks for no room of its own',
      held.requests.filter((r) => Math.abs(r.at - 300) < 1).length, 0);
    check('...and the ride stays the ONE room change until it lands (the key walks '
      + 'the figure into the attic afterwards, as it did before)',
      held.requests.filter((r) => r.at <= 683.33).length, 1);
    check('...and the ride still ends on the storey it was going to',
      held.arrivedAt?.y, 3, 0.2);
    check('...at the time it would have arrived anyway', held.arrivedAt?.at ?? null,
      683.33, 20);

    const turned = rideTo1({ rideOwnsFigure: true, pressAt: 300, interlock: false });
    check('without the interlock the standing offer names the storey just left',
      turned.offerAtPress, { levels: [0, 1], current: 1, dist: 0 });
    check('...and the press asks for a SECOND room', turned.requests.length, 2);
    check('...the one the ride started from', turned.requests[1], { at: 300, room: 'hall' }, 1);
    check('...so the figure sinks back to the storey it left', turned.arrivedAt?.y, 0.1984, 0.01);
    check('...arriving there instead, at 866.67 ms', turned.arrivedAt?.at ?? null, 866.67, 1);

    // --- and the press must not fall THROUGH to the stairs (re-review) -----
    // F is a priority chain: talk -> lift -> stairs. Clearing the lift chip
    // for the ride hands the next press to `state.stairs`, which is written
    // by its own 1 Hz tick and can stand for up to a second longer. So
    // `rideStairs` carries the SAME `verticalRide` guard, and each ride drops
    // the other's chip as well. The stale flight below leads back down into
    // the hall (a descent beside the shaft), so the numbers are the very same
    // ones as above: turned around at 300 ms, back at y = 0.1984 at 866.67.
    const STALE_DOWN = { room: 'hall', x: 0, z: 0, y: 0 };
    const fellThrough = rideTo1({ rideOwnsFigure: true, pressAt: 300,
      staleStairs: STALE_DOWN, stairsGuard: false });
    check('without its guard the stale flight is climbed mid-ride',
      fellThrough.stairsPress, 'ridden');
    check('...which is a second enter-room', fellThrough.requests.length, 2);
    check('...that takes the figure back down', fellThrough.arrivedAt?.y, 0.1984, 0.01);

    const chainGuarded = rideTo1({ rideOwnsFigure: true, pressAt: 300,
      staleStairs: STALE_DOWN });
    check('the climb refuses while the lift owns the figure',
      chainGuarded.stairsPress, 'refused');
    check('...so the press asks for no room of its own',
      chainGuarded.requests.filter((r) => Math.abs(r.at - 300) < 1).length, 0);
    check('...and the lift lands on the storey it was going to',
      chainGuarded.arrivedAt?.y, 3, 0.2);
  }

  const stairVectors = await runBridgeVectors('stairs');
  passed += stairVectors.passed; failed += stairVectors.failed;

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
  // leaf?, room_id?, outward_normal }]` — finished primitives in WORLD METRES,
  // and the server has ALREADY split every wall around its openings
  // (`app/core/scene_recipe.py::_room_walls`): a door or passage leaves a GAP
  // with only its LINTEL over it — one entry flagged `lintel`, because one
  // walks UNDER it — plus, for a door, the LEAF filling the hole, flagged
  // `leaf`, because one walks THROUGH it; while a window keeps a sill piece
  // below, a head piece above and a glass pane in between, three entries that
  // all span the opening. So "doors pass, windows block" needs no opening
  // lookup at all: whatever is left in `walls` blocks EXCEPT a `lintel` and a
  // `leaf`, and the gaps are the doors.
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
      // The wall ABOVE the door (height_m 2.1 -> 2.85): drawn, never a
      // barrier. Last of the level-0 entries so the indices above stand.
      { level: 0, from: [0, 2.5], to: [0, 1.5], base_y: 2.1, lintel: true },
      // …and the DOOR LEAF in the hole itself (0.00 -> 2.10, 0.042 thick):
      // drawn so the door reads as a door, and just as little of a barrier —
      // one walks THROUGH a door. Appended after the lintel for the same
      // reason: the indices above must not move.
      { level: 0, from: [0, 2.5], to: [0, 1.5], base_y: 0, leaf: true },
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
  vectorCase("[12] " + ('BODY_RADIUS_M is the figure-metre half width'));
  vectorCase("[12] " + ('DOOR_EASE_M'));
  vectorCase("[12] " + ('bodyRadius scales with k (small-scale k = 0.21)'));
  vectorCase("[12] " + ('bodyRadius(1) = BODY_RADIUS_M'));
  const segs0 = wallSegments(room, 0);
  check('the payload carries eleven level-0 pieces',
    room.walls.filter((w) => w.level === 0).length, 11);
  check('...nine of them block — neither lintel nor leaf is a barrier',
    segs0.length, 9);
  check('the skipped two are exactly the flagged lintel and leaf',
    segs0.filter((s) => s.ax === 0 && s.bx === 0
      && Math.min(s.az, s.bz) >= 1.5 && Math.max(s.az, s.bz) <= 2.5).length, 0);
  vectorCase("[12] " + ('upper storey is ONE segment'));
  // It stands ALONE on its storey, so BOTH of its ends count as free and both
  // are pulled back by the ease — the rule has no notion of "this end is a
  // corner", only "another wall ends here too". Harmless in a real payload
  // (every corner is shared) and visible here on purpose.
  vectorCase("[12] " + ('upper storey segment is the level-1 wall, both ends eased'));
  vectorCase("[12] " + ('a storey nobody built has no segments'));
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
  vectorCase("[13] " + ('head-on into a wall stands still'));
  //  oblique: delta = (-2,1); dot((-2,1),(0,1)) = 1 -> goal = (1,1) + (0,1)*1.
  //  The parallel component SURVIVES: the figure slides along the wall.
  vectorCase("[13] " + ('an oblique run slides along the wall'));
  //  the crossing test is bounded by the segment: past its end (z = 4) the
  //  same head-on move is free, only the push-out around the end cap applies.
  //  from (1,5) to (-1,5): closest point on the segment is (0,4),
  //  |(-1,5)-(0,4)| = sqrt(2) = 1.4142 >= 0.25 -> untouched.
  vectorCase("[13] " + ('beyond the end of the wall nothing blocks'));
  //  radius: from (1,1) to (0.1,3) never reaches x = 0, so nothing is crossed,
  //  but the goal lies 0.1 m from the wall. Push out along (1,0) to exactly r.
  vectorCase("[13] " + ('a grazing pass is pushed out to the body radius'));
  vectorCase("[13] " + ('and with a smaller radius it is left alone'));
  //  a door gap: the same wall split at z = 1.5 / 2.5. Walking through z = 2
  //  crosses neither piece, and the nearest end cap is
  //  |(-1,2)-(0,1.5)| = sqrt(1 + 0.25) = 1.118 >= 0.25 -> straight through.
  const gap = [{ ax: 0, az: 0, bx: 0, bz: 1.5 }, { ax: 0, az: 2.5, bx: 0, bz: 4 }];
  vectorCase("[13] " + ('through the door gap the goal survives untouched'));
  //  ... and the pieces beside it still block.
  vectorCase("[13] " + ('beside the door the wall still holds'));

  console.log('\nclampAgainstWalls — against the mini payload');
  //  Through the DOOR on edge 3 (gap z in [1.38, 2.62] after the ease):
  //  a walk west at z = 2 crosses nothing, nearest cheek end is
  //  |(-2,2)-(0,2.62)| = sqrt(4 + 0.3844) = 2.094 >= 0.25.
  vectorCase("[13] " + ('the avatar walks out through the door'));
  //  RED: the same payload with the flag dropped walls the door up — the
  //  lintel spans z in [1.5, 2.5], so the walk west at z = 2 crosses it and
  //  the move collapses onto the wall direction. That is the regression the
  //  flag exists for; without it the door is a picture, not a way through.
  const unflagged = { ...room,
    walls: room.walls.map((w) => (w.lintel ? { ...w, lintel: false } : w)) };
  vectorCase("[13] " + ('RED: an unflagged lintel would block the doorway'));
  //  RED, the same for the LEAF: the door leaf spans the very same z
  //  [1.5, 2.5]. A leaf that counted as a wall would brick up every door in
  //  the world — it is a picture of a door, not a door that shuts.
  const solidLeaf = { ...room,
    walls: room.walls.map((w) => (w.leaf ? { ...w, leaf: false } : w)) };
  vectorCase("[13] " + ('RED: a blocking leaf would brick up the doorway'));
  //  Through the WINDOW on edge 1 (same z, opposite side): the sill/head/glass
  //  entries span it, the move is projected onto their direction (0,1) and
  //  dot((4,0),(0,1)) = 0 -> stands still.
  vectorCase("[13] " + ('the window blocks like any wall'));
  //  Straight through the north wall (edge 0) — no opening there at all.
  vectorCase("[13] " + ('a wall without an opening blocks'));
  //  Diagonally at the door: delta = (-4,-1) still crosses nothing (it passes
  //  x = 0 at z = 2 - 1*(2/4) = 1.5, inside the eased gap [1.38, 2.62]) —
  //  BUT the cheek end (0,1.38) is 0.6 m away in z at x = -2, so no push
  //  either: |(-2,1)-(0,1.38)| = sqrt(4 + 0.1444) = 2.036 >= 0.25.
  vectorCase("[13] " + ('an oblique run through the door passes too'));
  //  Without the ease the same run would still pass; what the ease buys is the
  //  cheek CLEARANCE. Aiming at the untrimmed cheek corner (0,1.5): without
  //  the ease the goal (-0.1, 1.55) sits 0.1 m from the wall end and gets
  //  pushed; with the ease the cheek ends at (0,1.38) and
  //  |(-0.1,1.55)-(0,1.38)| = sqrt(0.01 + 0.0289) = 0.1972 -> still inside r,
  //  so it is pushed out, but from a point 0.12 m FARTHER from the doorway.
  //  The check that matters for the player: a walk hugging the eased cheek at
  //  z = 1.45 gets through instead of being stopped by the frame.
  vectorCase("[13] " + ('hugging the door cheek gets through'));
  //  Same run against the UNEASED gap: the cheek ends at (0,1.5), the goal
  //  passes 0.05 m from it -> pushed out along (-2-0, 1.45-1.5)/0.05... the
  //  point is only that it is NOT left alone. Compare the two.
  const tight = [{ ax: 0, az: 0, bx: 0, bz: 1.5 }, { ax: 0, az: 2.62, bx: 0, bz: 4 }];
  const hug = clampAgainstWalls({ x: 2, z: 1.45 }, { x: -2, z: 1.45 }, tight, R);
  check('without the ease the same run is clamped', hug.x > -2, true);
  //  Storey filter at the clamp: the upper storey wall runs (0,0)-(0,4) with
  //  NO door, so the same walk west is blocked there.
  vectorCase("[13] " + ('the storey above has no door and blocks'));
  vectorCase("[13] " + ('with no segments at all the goal is returned unchanged'));

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
  vectorCase("[13] " + ('offset segments block the world move'));
  vectorCase("[13] " + ('unoffset segments let it walk straight through (the bug)'));
  vectorCase("[13] " + ('and the door still works in world coordinates'));

  // I3 — the ORIGIN of the move may sit on the wall. Nothing walks a figure
  // there, but `snapPlayerTo` (the put-back after a refused step), a teleport
  // and a party pull all place it wall-blind. A point exactly on the line
  // makes EVERY from->goal a crossing, so the figure would be frozen in place
  // in all directions, for good. The origin is therefore pushed clear first;
  // when it is exactly ON the line, no side information exists and it takes
  // the side the player is heading for — the only sane pick, and unreachable
  // by walking (the goal never gets closer than the radius).
  console.log('\nclampAgainstWalls — an origin on the wall does not freeze (I3)');
  vectorCase("[13] " + ('standing on the wall, walking east: the move happens'));
  vectorCase("[13] " + ('standing on the wall, walking west: it works the other way too'));
  // Inside the capsule but off the line: the side IS known, so the figure is
  // pushed out to the radius while it walks along.
  vectorCase("[13] " + ('too close to the wall, walking along it: pushed out to r'));

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
  vectorCase("[13] " + ('down the middle of a too-narrow corridor: keeps walking'));
  check('and its clearance is not eaten by the push-out',
    minWallDistance(clampAgainstWalls(mid, { x: 0.15, z: 3 }, corridor, R), corridor),
    0.15, 1e-9);
  vectorCase("[13] " + ('out through the corridor wall: blocked, still in the middle'));
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
  vectorCase("[13] " + ('walking in: the figure is not shoved through the hull'));
  vectorCase("[13] " + ('walking out: it is not shoved through either'));
  check('and it never ends up past the hull wall',
    clampAgainstWalls(inNiche, { x: 2, z: 2 }, niche, NR).x <= 0.089, true);
  // The exemption that keeps this from freezing the on-the-wall case (I3):
  // contact AT the figure's own position is not a crossing — it is where it
  // stands. Only contact BEYOND it counts.
  vectorCase("[13] " + ('a figure standing on the wall still gets off it'));
  vectorCase("[13] " + ('and walking ALONG the wall line is still not free'));

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
  //   d5  HULL door of the hallway (§ A13c), mid (0,-3), along (1,0),
  //       width 1.2, base 0.10, rooms ['__floor__0'], outside, hull
  //
  // d5 is the case that has no room wall at all: a hallway is the complement
  // of its storey's rooms, so the door is cut out of the BUILDING OUTLINE and
  // `rooms[0]` is that wall-less corridor. For this module it is an outside
  // door like any other — which is the point of the checks below.
  // Its `outward_normal` [0,-1] is exactly `(along.z, -along.x)` of (1,0),
  // i.e. the room-door construction: the fixture does NOT exercise the
  // reversed-winding case, where the two come apart. Nothing is lost by that
  // here — the client never reads the field (the server pre-computes the
  // door-prop swing from it, § B1 "Woher `swing` kommt"), and the reversed
  // ring is hand-derived on the server side in `scripts/smoke_floor_rooms.py`
  // Part 8.
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
      { level: 0, at_world: [0, -3], along: [1, 0], width_m: 1.2, base_y: 0.1,
        rooms: ['__floor__0'], outside: true, hull: true,
        outward_normal: [0, -1] },
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
  check('the ground floor has exactly its five doorways', dm0.length, 5);
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
  // THE HULL DOOR (§ A13c): drawn on the building outline, opening into the
  // storey's hallway. Nothing here may filter it out for lacking a room wall
  // — the entry is read exactly like the room doors above, and the threshold
  // hangs on the tile's own group, not on a room's.
  check('the hull door of the hallway is a threshold like any other',
    { mid: dm0[4].mid, along: dm0[4].along, width: dm0[4].width,
      baseY: dm0[4].baseY, roomIds: dm0[4].roomIds, outside: dm0[4].outside },
    { mid: { x: 0, z: -3 }, along: { x: 1, z: 0 }, width: 1.2, baseY: 0.1,
      roomIds: ['__floor__0'], outside: true });

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

  // BETWEEN two rooms: the NPC walk (main.ts) routes a room change through the
  // door that joins them — the entry whose `rooms` holds both. That is what
  // the removed single exit point per room could never answer.
  console.log('\ndoorwayBetween — the door that joins two rooms');
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

  // Expected values are derived by hand in the docstring; the bootProgress
  // cases [P1..P3] run from overview_hud.json (see the top of main).
  const STAGES = ['world', 'scenes', 'tiles', 'visible', 'figures', 'arrival'];
  check('BOOT_STAGES order', [...BOOT_STAGES], STAGES);
  const intervals = [
    { phase: 'scene:fetch', start: 0, end: 100 },
    { phase: 'ground:fetch', start: 50, end: 300 },
  ];
  for (const [startTime, duration, expected] of [
    [60, 100, 'ground:fetch'], [0, 40, 'scene:fetch'],
    [400, 50, null], [50, 50, 'scene:fetch'],
  ]) check(`long task ${startTime}`, attributeLongTask(intervals, { startTime, duration }), expected);

  // Arrival overlaps all 60 ms, parse only 20 ms: CPU must win.
  check('CPU beats enclosing wait', attributeLongTask([
    { phase: 'arrival:mount', start: 0, end: 300 },
    { phase: 'clip:parse', start: 100, end: 120 },
  ], { startTime: 90, duration: 60 }), 'clip:parse');
  // Equal 20 ms CPU overlaps choose start 100 rather than 110.
  check('CPU ties choose earlier start', attributeLongTask([
    { phase: 'clip:fit', start: 110, end: 130 },
    { phase: 'clip:parse', start: 100, end: 120 },
  ], { startTime: 90, duration: 60 }), 'clip:parse');
  check('largest CPU overlap wins', attributeLongTask([
    { phase: 'arrival:mount', start: 0, end: 300 },
    { phase: 'clip:parse', start: 100, end: 120 },
    { phase: 'model:build', start: 110, end: 140 },
  ], { startTime: 90, duration: 60 }), 'model:build');
  // Wait-only cases above retain largest overlap and earlier-start ties.

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
    { percent: 17, label: 'scenes' });
  check('the subscriber was notified once', bootTicks, 1);
  reportBootStage('world');
  check('reporting the same stage twice does not count twice',
    getBootState().percent, 17);
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

  // Report timing uses a controlled monotonic clock: a 10..40 run is 30 ms;
  // a rejecting 40..55 run still adds 15, for a sum of 45 ms.
  const originalPerformance = globalThis.performance;
  const originalObserver = globalThis.PerformanceObserver;
  let bootNow = 10;
  globalThis.performance = { now: () => bootNow, mark: () => {} };
  globalThis.PerformanceObserver = undefined;
  try {
    boot.markBootStart();
    check('unsupported long tasks are null', boot.bootReport().longTasks, null);
    check('unsupported after-visible tasks are null', boot.bootReport().afterVisible, null);
    check('boot report is a stable snapshot', boot.bootReport() === boot.bootReport(), true);
    let reports = 0;
    const unsubscribe = boot.subscribeBootReport(() => { reports += 1; });
    const before = boot.bootReport();
    await boot.withPhase('scene:fetch', async () => { bootNow = 40; });
    check('phase run adds 30 ms', boot.bootReport().phases['scene:fetch'], 30);
    check('old snapshot stays unchanged', before.phases['scene:fetch'], 0);
    try {
      await boot.withPhase('scene:fetch', async () => { bootNow = 55; throw new Error('probe'); });
    } catch { /* Rejected operations are still measured. */ }
    check('rejection adds its 15 ms', boot.bootReport().phases['scene:fetch'], 45);
    boot.markPhase('clip:fit', 5);
    boot.reportBootStage('figures');
    boot.reportBootStage('world');
    check('finished stages use display order', boot.getBootState().stages, ['world', 'figures']);
    check('stage is relative to boot start', boot.bootReport().stages.world, 45);
    check('phase and stage changes notify', reports, 5);
    unsubscribe();
  } finally {
    globalThis.performance = originalPerformance;
    globalThis.PerformanceObserver = originalObserver;
  }

  /** Observer hand derivation: boot starts at 100, visible at 200, arrival
   * at 300. The window ends at 5200, so at arrival the delay is 4900.
   * Task starts 150/200/5200/5201: boot count 2, after-visible count 2.
   * Durations 60/70/80/90: boot total 130, after-visible total 150.
   * Final drain adds [300,400]: boot count 3, total 130 + 100 = 230.
   * [5100,5300] intersects the window [100,5200] for 100 ms.
   * Arrival 12000 exceeds visible 6100 + 5000 = 11100: delay 0.
   */
  const originalTimer = globalThis.setTimeout;
  const originalClearTimer = globalThis.clearTimeout;
  const originalInfo = console.info;
  let observerCallback;
  let observerOptions;
  let timerCallback;
  let timerDelay;
  let disconnected = false;
  let printed = 0;
  let printedLine = '';
  let drained = false;
  globalThis.performance = { now: () => bootNow, mark: () => {} };
  globalThis.setTimeout = (fn, ms) => { timerCallback = fn; timerDelay = ms; return 1; };
  globalThis.clearTimeout = () => {};
  console.info = (line) => { printed += 1; printedLine = line; check('console report follows final drain', drained || globalThis.PerformanceObserver === undefined, true); };
  globalThis.PerformanceObserver = class {
    static supportedEntryTypes = ['longtask'];
    constructor(fn) { observerCallback = fn; }
    observe(options) { observerOptions = options; }
    takeRecords() { drained = true; return [{ startTime: 300, duration: 100 }]; }
    disconnect() { disconnected = true; }
  };
  try {
    bootNow = 100;
    boot.markBootStart();
    check('long tasks request buffered entries', observerOptions, { type: 'longtask', buffered: true });
    bootNow = 200;
    boot.reportBootStage('visible');
    bootNow = 300;
    boot.reportBootStage('arrival');
    check('observer waits until visible plus five seconds', timerDelay, 4900);
    observerCallback({ getEntries: () => [
      { startTime: 99, duration: 100 },
      { startTime: 150, duration: 60 }, { startTime: 200, duration: 70 },
      { startTime: 5200, duration: 80 }, { startTime: 5201, duration: 90 },
    ] });
    check('boot task window excludes pre-boot and post-arrival', boot.bootReport().longTasks,
      { count: 2, totalMs: 130, maxMs: 70, maxPhase: null });
    check('after-visible window includes both endpoints', boot.bootReport().afterVisible,
      { count: 2, totalMs: 150, maxMs: 80, maxPhase: null });
    // Parse [150,300] overlaps the 60 and 70 ms tasks: maximum 70.
    // Fit [400,410] overlaps a new 80 ms task starting at 400.
    // The 90 ms task at 5201 is beyond the measurement window.
    boot.markPhase('clip:parse', 150);
    bootNow = 410;
    boot.markPhase('clip:fit', 10);
    observerCallback({ getEntries: () => [{ startTime: 400, duration: 80 }] });
    check('per-phase maxima use full attributed durations inside window',
      boot.bootReport().longTaskMaxByPhase, { 'clip:parse': 70, 'clip:fit': 80 });
    check('arrival does not print a provisional report', printed, 0);
    const emptySnapshot = boot.bootReport();
    observerCallback({ getEntries: () => [] });
    check('empty batch preserves snapshot', boot.bootReport() === emptySnapshot, true);
    bootNow = 5100;
    let finish;
    const crossing = boot.withPhase('model:build', () => new Promise((resolve) => { finish = resolve; }));
    bootNow = 5200;
    observerCallback({ getEntries: () => [{ startTime: 5190, duration: 80 }] });
    timerCallback();
    check('window end disconnects observer', disconnected, true);
    check('final drain prints one authoritative report', printed, 1);
    check('authoritative line includes drained task', printedLine.includes('longtasks 3 (230 ms'), true);
    // Build [5100,5200] overlaps the 80 ms task at 5190 for 10 ms.
    // The 90 ms task starting at 5201 is still outside the window.
    check('per-phase maxima reflect completed intervals',
      boot.bootReport().longTaskMaxByPhase, { 'clip:parse': 70, 'clip:fit': 80, 'model:build': 80 });
    check('console includes phase maxima',
      printedLine.includes('max by phase clip:parse 70 · clip:fit 80 · model:build 80'), true);
    check('crossing interval is clipped to 100 ms', boot.bootReport().phases['model:build'], 100);
    const frozen = boot.bootReport();
    bootNow = 5300;
    finish();
    await crossing;
    boot.markPhase('clip:fit', 200);
    check('gameplay operation still executes', await boot.withPhase('model:build', async () => 42), 42);
    check('final report stays frozen', boot.bootReport() === frozen, true);
    globalThis.PerformanceObserver = undefined;
    bootNow = 6000;
    boot.markBootStart();
    bootNow = 6100;
    boot.reportBootStage('visible');
    bootNow = 12000;
    boot.reportBootStage('arrival');
    check('late arrival ends the window', timerDelay, 0);
    check('unsupported browser waits for finalization', printed, 1);
    timerCallback();
    check('unsupported browser prints one report', printed, 2);
    check('unsupported summary remains n/a', boot.bootReport().longTasks, null);
    check('unsupported console line says n/a', printedLine.includes('longtasks n/a'), true);
  } finally {
    globalThis.performance = originalPerformance;
    globalThis.PerformanceObserver = originalObserver;
    globalThis.setTimeout = originalTimer;
    globalThis.clearTimeout = originalClearTimer;
    console.info = originalInfo;
  }

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

  console.log("voiceover — the server's narrator mark and who is read aloud");
  // The narrator is whoever the server MARKS (`meta.narrator`), never a name:
  // the speaker label is localised per world and would go silent-wrong in
  // every language nobody hardcoded.
  check('a line the server marks is the narrator, whatever its label',
    isNarratorLine(line({ speaker: 'Chronicler', meta: { narrator: true } })), true);
  check('a line without the mark is not, even when it is called Storyteller',
    isNarratorLine(line({ speaker: 'Storyteller' })), false);
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
  check('the marked narrator stays silent',
    speakableLines([line({ speaker: 'Storyteller', meta: { narrator: true } })], AVATAR), []);
  check('the marked narrator stays silent under a localised label too',
    speakableLines([line({ speaker: 'Erzähler', meta: { narrator: true } })], AVATAR), []);
  check('a marked narrator that only names itself in meta.speaker is caught as well',
    speakableLines([line({ speaker: '', meta: { speaker: 'Erzähler', narrator: true } })],
      AVATAR), []);
  check('an unmarked "Storyteller" is a character and is read',
    speakableLines([line({ speaker: 'Storyteller' })], AVATAR),
    [{ speaker: 'Storyteller', text: 'Good evening.' }]);
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

    vectorCase("[11] " + ('a listed room is locked'));
    vectorCase("[11] " + ('an unlisted room is not'));
    vectorCase("[11] " + ('a wordless entry is still a lock'));
    vectorCase("[11] " + ('no map at all locks nothing'));
    vectorCase("[11] " + ('the empty id is never locked'));
    vectorCase("[11] " + ('NO_LOCKS is empty'));
    // The sentence travels untranslated — it is the server's, already localized.
    vectorCase("[11] " + ('the reason is the server\'s own sentence'));
    vectorCase("[11] " + ('an open room has no reason'));
    vectorCase("[11] " + ('a wordless lock has none either'));
    // A map is a plain object: an inherited property must not pass for a lock.
    vectorCase("[11] " + ('a prototype property is no lock'));

    // null = open, a string (even the empty one) = locked. The two must not be
    // one answer: a wordless lock has to be drawn as a lock all the same.
    vectorCase("[11] " + ('a doorway into a locked room is locked'));
    vectorCase("[11] " + ('a doorway between two open rooms is not'));
    vectorCase("[11] " + ('the first locked room in payload order supplies the words'));
    vectorCase("[11] " + ('a wordless lock is a lock, not an open door'));
    vectorCase("[11] " + ('standing IN the locked room, its own door stays open'));
    vectorCase("[11] " + ('...but a second locked room behind it still shows'));
    vectorCase("[11] " + ('an outside door of a locked room, standing in it, is open'));
    vectorCase("[11] " + ('a doorway without rooms is open'));
    vectorCase("[11] " + ('and so is one with nothing locked'));

    const ROOMS = [{ id: 'hall' }, { id: 'kitchen' }, { id: 'study' }];
    vectorCase("[11] " + ('a locked room is no candidate'));
    vectorCase("[11] " + ('the room one is in survives its own lock'));
    vectorCase("[11] " + ('nothing locked leaves the list alone'));
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
  // NEU H1: absent on a241a8aa. Raw 516 - 16 = 500 ms, independent
  // of the engine's 100 ms cap; a fresh meter gives 1016 - 1000 = 16 ms.
  {
    let state = { lastFrameAt: null, worstFrameMs: 0 };
    for (const now of [0, 16, 516]) perfstats.pushWorstFrame(state, now);
    check('worst frame uses the raw clock', state.worstFrameMs, 500);
    state = { lastFrameAt: null, worstFrameMs: 0 };
    for (const now of [1000, 1016]) perfstats.pushWorstFrame(state, now);
    check('reset forgets the previous stall', state.worstFrameMs, 16);
  }

  console.log('perfstats — the fps window');
  const { newFpsMeter, pushFrame, fpsOf, visibleVertices, tierCounts,
    scatterCosts, emptyScatterCounts } = perfstats;

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

  // --- scatterCosts -------------------------------------------------------
  //
  // Rules, straight from the docstring and worked out by hand here:
  //   - a drawable that is invisible, or whose instance count is 0, costs
  //     nothing at all — not even a draw call;
  //   - triangles per instance = floor(verts / 3), verts read off the INDEX
  //     where there is one and off position.count otherwise;
  //   - the stage is the NAME: the impostor marker or the mesh half.
  // The indexed cube below has 36 index entries = 12 triangles per instance;
  // the unindexed billboard quad has 6 positions = 2 triangles per instance.
  console.log('perfstats — what the scatter submits');
  const IMP = 'scatter-impostor';
  const inst = (count, verts, opts = {}) => ({
    visible: opts.visible !== false,
    count,
    name: opts.name,
    geometry: opts.indexed === false
      ? { attributes: { position: { count: verts } } }
      : { index: { count: verts }, attributes: { position: { count: 999 } } },
  });

  check('nothing at all is an empty reading',
    scatterCosts(null, IMP), emptyScatterCounts());
  //   one prop entry, 100 instances of a 36-index cube:
  //   calls 1, instances 100, triangles 12 * 100 = 1200
  check('one mesh entry: 100 x 12 triangles = 1200',
    scatterCosts([inst(100, 36)], IMP),
    { mesh: { calls: 1, instances: 100, triangles: 1200 },
      impostor: { calls: 0, instances: 0, triangles: 0 } });
  //   the INDEX wins over the position count where both exist (999 above would
  //   read 333 triangles per instance and is not what the renderer draws)
  check('an indexed geometry counts by its index',
    scatterCosts([inst(1, 36)], IMP).mesh.triangles, 12);
  //   …and an unindexed quad by its positions: 6 / 3 = 2 per instance
  check('an unindexed quad is 2 triangles per instance',
    scatterCosts([inst(500, 6, { indexed: false, name: IMP })], IMP),
    { mesh: { calls: 0, instances: 0, triangles: 0 },
      impostor: { calls: 1, instances: 500, triangles: 1000 } });
  //   a parked entry (the binning leaves count 0 AND visible false) and an
  //   invisible one both cost nothing — neither a call nor an instance
  check('a parked entry costs nothing',
    scatterCosts([inst(0, 36, { visible: false })], IMP), emptyScatterCounts());
  check('a visible entry with 0 instances is not a draw call',
    scatterCosts([inst(0, 36)], IMP), emptyScatterCounts());
  check('an invisible entry with instances costs nothing',
    scatterCosts([inst(100, 36, { visible: false })], IMP), emptyScatterCounts());
  //   a plain (non-instanced) mesh draws itself once
  check('a mesh without a count draws once',
    scatterCosts([{ visible: true, geometry: { index: { count: 36 } } }], IMP).mesh,
    { calls: 1, instances: 1, triangles: 12 });
  //   the mixed reading a forest gives: two prop entries (100 x 12 and
  //   50 x 12 = 1200 + 600) against one billboard layer (800 x 2 = 1600)
  check('a wood adds up per stage', scatterCosts([
    inst(100, 36), inst(50, 36),
    inst(800, 6, { indexed: false, name: IMP }),
    inst(0, 36, { visible: false }),
  ], IMP), {
    mesh: { calls: 2, instances: 150, triangles: 1800 },
    impostor: { calls: 1, instances: 800, triangles: 1600 },
  });
  //   a prop whose own mesh IS two triangles still counts as a mesh: the stage
  //   is the marker, never the geometry
  check('a two-triangle prop is still a mesh',
    scatterCosts([inst(10, 6, { indexed: false })], IMP).impostor.calls, 0);

  // --- Speech bubbles (stage 6; client3d/src/game/bubble.ts) ---------------
  // Derived in the header ([B1..B15]); the cases run from overview_hud.json.
  // What stays here: the constants the derivation computes with, and the
  // rendered LENGTHS (a property of the result, not a second value).
  console.log('\nbubble — constants and lengths');
  const { bubbleText, BUBBLE_MAX_CHARS, BUBBLE_BASE_MS,
    BUBBLE_MS_PER_CHAR, BUBBLE_MAX_MS } = bubble;
  check('the constants are the ones this block computes with',
    [BUBBLE_MAX_CHARS, BUBBLE_BASE_MS, BUBBLE_MS_PER_CHAR, BUBBLE_MAX_MS],
    [140, 3500, 55, 12000]);
  check('[B5] ...and 140 characters really are 140', bubbleText('a'.repeat(140)).length, 140);
  check('[B6] the ellipsis counts towards the cap', bubbleText('a'.repeat(141)).length, 140);

  // The admin's "show all locations" switch lives beside the audio prefs since
  // the veil was struck (contract v6 Nr. 8) — it was never about the veil, only
  // about which places the worldmap answers with. Pinned by hand like
  // PREFS_KEY: a stored switch must keep working across versions of this
  // client.
  console.log('prefs — the show-all switch key');
  check('the show-all pref key is the documented one',
    SHOW_ALL_KEY, 'av3d.showAllLocations');

  // Info panel [I1..I12] and scatter-pref typing [J3]/[J4] run from
  // overview_hud.json; what JSON cannot carry stays here.
  console.log('info panel — the inline rest');
  check('infoPanelData is a function', typeof infoPanel.infoPanelData, 'function');
  const panel = infoPanel.infoPanelData(
    { id: 'loc1', name: 'Home', rooms: [{ id: 'r1', name: 'Kitchen' }, { id: 'r2', name: 'Hall' }] },
    [{ name: 'A', movement_target_name: 'Harbor', travel: { eta_hhmm: '14:30' } }, { name: 'B' }, { name: 'C' }],
    [{ category: 'danger', text: 'Fire' }, { category: 'other', text: 'News' }],
    new Map([['A', 'Kitchen'], ['B', 'r2']]));
  // `compare` counts keys, so a field that JSON would drop (undefined) fails.
  check('the panel data survives a JSON round trip unchanged',
    JSON.parse(JSON.stringify(panel)), panel);
  console.log('prefs — scatter typing, the inline rest');
  check('[J3] an empty number field (NaN) is refused as no number',
    prefs.checkScatterPrefs(NaN, 45, 120), { ok: false, error: 'number' });

  /**
   * --- Minimap (stage 5 task 3; on the METRE world since E4 task 2) ---------
   * `hud/src/game/minimap.ts`
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
  // [B2] — the cases run from figure_ground.json (see "SHARED VECTORS").
  console.log('\nplacement — [B2] runs from figure_ground.json');

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
  console.log('placement — [B5] runs from figure_ground.json; undefined stays here');
  check('…and undefined is the same "nothing drawn yet"',
    figureTransition(undefined, { room: null, interiorShown: false }), 'snap');

  console.log('\nground — the mesh rung is GONE (red counter-probes, E5b)');
  const { ROOF_CLEARANCE_M, plateCeiling, recipeFloorAt, WALK_CLEARANCE_M,
    declaredFloorAt, standY } = ground;
  check('`walkCeiling` no longer exists', ground.walkCeiling === undefined, true);
  check('…and neither does `acceptsWalkHit`',
    ground.acceptsWalkHit === undefined, true);
  check('…nor `groundLift`, the second height source of a scene',
    ground.groundLift === undefined, true);
  check('the clearance the STOREY question is still measured with', ROOF_CLEARANCE_M, 1.2);
  check('a building without a declared walk height keeps 1.2 m',
    plateCeiling({ display: 'shell' }), 1.2);
  check('…and so does a tile with no model info at all',
    plateCeiling(undefined), 1.2);
  check('a building measures from its own walk_y_world −0.30',
    plateCeiling({ display: 'shell', walkY: -0.30 }), 0.90, 1e-9);
  check('a building on a plinth carries the clearance up with it',
    plateCeiling({ display: 'shell', walkY: 3.2 }), 4.4);
  // THE AREA EXCEPTION IS GONE WITH THE HITS IT WAS FOR: an area location's
  // plates are storeys like anybody's, and the mesh it used to exempt is not
  // asked any more.
  check('an AREA model is judged by the same storey ceiling',
    plateCeiling({ display: 'ground', walkY: 0 }), 1.2);
  check('…the detail-mode area model just the same',
    plateCeiling({ display: 'shell_area' }), 1.2);

  console.log('\nground — ONE floor, and on storey 0 it is the terrain');
  // The payload of "Haus von Kai" (worlds/Anima Divide, GET /play/locations/
  // 20dc0cbd/scene) AFTER E5a: storey 0 ships no plate at all, so what is left
  // is the storey-1 pair — contour 1·2.8 + LEVEL_PLATE_TOP 0.08 = 2.88, bedroom
  // 1·2.8 + ROOM_PLATE_TOP 0.10 = 2.90. The hulls are the outlines it ships.
  const KAI_HOUSE = [[-4.5, -4.5], [6, -4.5], [6, 1.5], [-0.5, 1.5],
    [-0.5, 6], [-4.5, 6], [-4.5, -1], [-6.22, -1], [-6.25, -3.11],
    [-4.53, -3.13]];
  const KAI_BEDROOM = [[-6.25, -3.11], [-4.53, -3.13], [-4.5, -4.5],
    [6, -4.5], [6, 1.5], [-0.5, 1.5], [-4.5, 1.5], [-4.5, -1], [-6.22, -1]];
  const KAI_PLATES = [
    { top: 2.88, outline: KAI_HOUSE },
    { top: 2.90, outline: KAI_BEDROOM },
  ];
  // walk_y_world = 0 + offset_y (−0.30) since E5a — the 0.08 storey datum it
  // used to be measured from is gone with the storey-0 plate.
  const KAI_CEILING = plateCeiling({ display: 'shell', walkY: -0.30 });
  check('the storey ceiling of that building is 0.90', KAI_CEILING, 0.90, 1e-9);
  // THE RED PROBES. Every one of these points answered a plate before E5a —
  // 0.10 in a room, 0.08 in the house but in no room, 0.00 in the pool — and
  // every one of them has to answer "no plate here" now, because the floor is
  // the ground under it.
  check('living room: NO plate on storey 0 any more',
    recipeFloorAt(KAI_PLATES, 0.75, -1.5, KAI_CEILING), null);
  check('kitchen: the same',
    recipeFloorAt(KAI_PLATES, -2.5, 3.75, KAI_CEILING), null);
  check('the lift alcove: the same',
    recipeFloorAt(KAI_PLATES, -5.8, -2.0, KAI_CEILING), null);
  check('the pool (an outdoor room): the same',
    recipeFloorAt(KAI_PLATES, 3.7, 4.6, KAI_CEILING), null);
  check('on the plot, outside the house: unchanged, still null',
    recipeFloorAt(KAI_PLATES, 6.9, -6.5, KAI_CEILING), null);
  check('the storey above is out of reach from the ground floor (2.88 >= 0.90)',
    recipeFloorAt(KAI_PLATES, 0.75, -1.5, KAI_CEILING), null);
  // …and the rule itself is untouched where it still has work: standing ON the
  // first storey, the bedroom's 2.90 beats the contour's 2.88 under it.
  check('on storey 1 the ROOM plate still wins over the contour',
    recipeFloorAt(KAI_PLATES, 0.75, -1.5, 4.0), 2.90);
  check('…and in no room up there, the storey contour answers',
    recipeFloorAt(KAI_PLATES, -2, 4.0, 4.0), 2.88);
  check('no plates at all = no recipe floor', recipeFloorAt([], 0, 0, 1.2), null);
  check('...and neither does a tile that never got a list',
    recipeFloorAt(undefined, 0, 0, 1.2), null);

  console.log('\nground — THE STAIRWELL: a hole in a plate is not floor');
  // The opening a flight cuts into the floor it ARRIVES on (`plates[].holes`,
  // contract addendum "Treppen v2"). Drawn it is a hole in the ceiling; walked
  // it must not answer — otherwise a figure stands on the lid of the very
  // stairwell it is climbing through.
  //
  // The numbers are the contract example, derived by hand from the server's
  // constants (STAIR_TREAD_M 0.26, STAIR_RISE_M 0.20, STAIR_WIDTH_M 1.20,
  // STAIR_PAD_M 0.90, STAIR_PAD_GAP_M 0.05, LEVEL_PLATE_TOP 0.08,
  // ROOM_PLATE_TOP 0.10), storey 3.0 m, one flight at (2, −2) climbing +x:
  //
  //   climb = storey_floor_y(1) − storey_floor_y(0) = 3.08 − 0.00 = 3.08
  //   steps = round(3.08 / 0.20) = 15        run = 15 · 0.26 = 3.90
  //   hole  = run + STAIR_PAD_GAP_M + STAIR_PAD_M = 3.90 + 0.05 + 0.90 = 4.85
  //           long, max(1.20, 0.90) = 1.20 wide, from `at` along the climb:
  //           x 2 … 6.85, z −2.6 … −1.4
  //   plates of storey 1: the contour at 1·3 + 0.08 = 3.08, the room "hall"
  //           (x 1…5, z −4…0) at 1·3 + 0.10 = 3.10 — the flight's centre
  //           (4.425, −2) lies in "hall", so BOTH carry the ring.
  //
  // The contour is ±8 rather than the example's ±5 so that the whole ring
  // (out to x 6.85) and the ground beyond it lie ON the plate: what is being
  // measured is the hole, and a point outside the outline would answer `null`
  // for the wrong reason.
  const HOLE = [[2, -2.6], [6.85, -2.6], [6.85, -1.4], [2, -1.4]];
  const CONTOUR = [[-8, -8], [8, -8], [8, 8], [-8, 8]];
  const HALL = [[1, -4], [5, -4], [5, 0], [1, 0]];
  const CUT_PLATES = [
    { top: 3.08, outline: CONTOUR, holes: [HOLE] },
    { top: 3.10, outline: HALL, holes: [HOLE] },
  ];
  // High enough to have every plate of storey 1 in reach (the storey question
  // is settled elsewhere; what is measured here is the hole).
  const UP = 4.5;
  check('inside the opening, both plates cut: no floor at all',
    recipeFloorAt(CUT_PLATES, 3.0, -2.0, UP), null);
  check('red: the SAME point without the rings is the room plate',
    recipeFloorAt(CUT_PLATES.map((p) => ({ ...p, holes: [] })), 3.0, -2.0, UP),
    3.10);
  check('one step north of the opening (z −1.0) the room floor answers',
    recipeFloorAt(CUT_PLATES, 3.0, -1.0, UP), 3.10);
  check('...and one step south of it (z −3.0) as well',
    recipeFloorAt(CUT_PLATES, 3.0, -3.0, UP), 3.10);
  check('just short of the foot (x 1.9) there is floor',
    recipeFloorAt(CUT_PLATES, 1.9, -2.0, UP), 3.10);
  check('past the head pad (x 6.9), outside "hall", the contour answers',
    recipeFloorAt(CUT_PLATES, 6.9, -2.0, UP), 3.08);
  check('in the opening but past "hall" (x 6.0): the contour is cut too',
    recipeFloorAt(CUT_PLATES, 6.0, -2.0, UP), null);
  // THE FALL-THROUGH IS TO THE NEXT RUNG, not to null: only the room is cut
  // here (a hypothetical the server does not compose — it cuts the level plate
  // as well — but it is exactly the rule this loop implements, and it says
  // that the answer is the plate BELOW rather than "no plate here").
  check('a hole in the room plate alone falls through to the contour under it',
    recipeFloorAt([{ top: 3.08, outline: CONTOUR, holes: [] },
      { top: 3.10, outline: HALL, holes: [HOLE] }], 3.0, -2.0, UP), 3.08);
  check('an empty ring list is a plate like any other',
    recipeFloorAt([{ top: 3.08, outline: CONTOUR, holes: [] }], 3.0, -2.0, UP),
    3.08);
  check('...and so is a plate that carries no rings at all (a room\'s own '
    + 'declared floor)',
    recipeFloorAt([{ top: 3.08, outline: CONTOUR }], 3.0, -2.0, UP), 3.08);

  console.log('\nground — the HEADLINE: built and natural are ONE chain');
  // Hand-derived from § A16.9, both columns, storey 2.8 m, no dials:
  //   storey_floor_y(0, 2.8) = 0·2.8 + 0 = 0.00        (the terrain)
  //   _plate_top(level 0)    = 0.00                     for EVERY kind of room
  //   prop    bottom_y = 0.00 + 0.00 + PROP_CLEARANCE    0.01 = 0.01
  //   diorama bottom_y = 0.00 + 0.00 + DIORAMA_CLEARANCE 0.02 = 0.02
  //   figure           = the terrain itself                    = 0.00
  const PROP_CLEARANCE = 0.01;        // server, hand-quoted
  const DIORAMA_CLEARANCE = 0.02;     // server, hand-quoted
  const STOREY_M = 2.8;
  /** § A16.9 in one line, written out here rather than imported — the
   *  point of a derivation is that it is independent of the thing it checks. */
  const storeyFloorY = (level, storey) => level * storey + (level === 0 ? 0 : 0.08);
  const plateTop = (level, kind) => (level === 0 ? 0
    : kind === 'room' ? 0.10 : kind === 'zone' ? 0.09 : 0.08);
  // A ROOM's floor is its STOREY LEVEL plus what its own plate lays over it —
  // `level·storey + _plate_top`, NOT `storey_floor_y + _plate_top`: the level
  // plate's own 0.08 is the CONTOUR's datum (the yard and the storey slab
  // stand on it), while a room plate is drawn from the bare storey level. That
  // is why the storey-1 contour is 2.88 and the bedroom on it is 2.90 and not
  // 2.98. On storey 0 both readings are 0, which is the whole point.
  const chain = (level, kind) => {
    const floor = level * STOREY_M + plateTop(level, kind);
    return { floor, prop: floor + PROP_CLEARANCE,
             diorama: floor + DIORAMA_CLEARANCE };
  };
  const BUILT = chain(0, 'room');       // Haus von Kai, a closed room
  const NATURAL = chain(0, 'zone');     // Mondscheinsee, an open zone
  check('built: the floor is the terrain', BUILT.floor, 0.00, 1e-9);
  check('natural: the floor is the terrain', NATURAL.floor, 0.00, 1e-9);
  check('THE HEADLINE — the two chains are the same three numbers',
    [BUILT.floor, BUILT.prop, BUILT.diorama],
    [NATURAL.floor, NATURAL.prop, NATURAL.diorama], 1e-9);
  check('prop bottom_y is 0.01 on both', BUILT.prop, 0.01, 1e-9);
  check('diorama bottom_y is 0.02 on both', BUILT.diorama, 0.02, 1e-9);
  // RED PROBES on the three floor values the two chains used to have.
  check('the old BUILT room floor 0.10 is nowhere in the chain',
    BUILT.floor !== 0.10 && BUILT.prop !== 0.10 && BUILT.diorama !== 0.10, true);
  check('the old BUILT zone surface 0.09 likewise',
    NATURAL.floor !== 0.09 && NATURAL.prop !== 0.09, true);
  check('the old NATURAL zone surface 0.01 is no FLOOR any more',
    NATURAL.floor !== 0.01, true);
  check('…the 0.01 that is left is the PROP\'s hair over the ground',
    NATURAL.prop - NATURAL.floor, PROP_CLEARANCE, 1e-9);
  // A DECLARED storey did not move one millimetre — that is what makes this a
  // cull and not a redesign.
  check('storey 1, closed room: 2.90, exactly as before',
    chain(1, 'room').floor, 2.90, 1e-9);
  check('storey 1, open zone: 2.89 (0.08 + 0.01), exactly as before',
    chain(1, 'zone').floor, 2.89, 1e-9);
  check('a basement keeps its floor too: −2.8 + 0.10',
    chain(-1, 'room').floor, -2.70, 1e-9);
  check('…and the storey CONTOUR of that basement is −2.8 + 0.08',
    storeyFloorY(-1, STOREY_M), -2.72, 1e-9);
  check('the storey-1 contour is 2.88, the room plate on it 2.90',
    [storeyFloorY(1, STOREY_M), chain(1, 'room').floor], [2.88, 2.90], 1e-9);
  // THE DOORSTEP, the thing the old chain's socle line guarded in disguise:
  // stepping from the ground outside into a built room is now no step at all.
  const MAX_STEP_M = 0.4;             // world default, hand-quoted
  check('the doorstep terrain -> room floor is 0.00, under the step limit 0.4',
    [BUILT.floor - 0.00, BUILT.floor - 0.00 < MAX_STEP_M ? 1 : 0],
    [0.00, 1], 1e-9);
  check('the walk clearance IS the server\'s prop clearance',
    WALK_CLEARANCE_M, PROP_CLEARANCE);

  // ── The DECLARED floor (§ B6 no. 7, user finding 2026-08-20) ────────────
  //
  // MONDHÜTTE, a room with a diorama inside the AREA location Mondscheinsee
  // (worlds/Anima Divide, GET /play/locations/2e2f52e9/scene). Re-derived on
  // the E5a datum: the room's surface on storey 0 is the terrain (0.00), not
  // the 0.01 zone plate of the E3 era and not the 0.09 of the slab era.
  //
  //   diorama bottom_y = 0.00 + DIORAMA_CLEARANCE 0.02
  //                    + layout.model_offset_y (−0.30)          = −0.28
  //   walk_y_world     = bottom_y + walk_y (0.35)               =  0.07
  //   figure           = walk_y_world + WALK_CLEARANCE_M        =  0.08
  //
  // (The E3 datum said −0.27 / 0.08 / 0.09, the slab era −0.19 / 0.16 / 0.17 —
  // the whole chain has come down one plate at a time.) The clearance IS added
  // here and deliberately: a declared floor is a DRAWN surface, and a sole on
  // it would z-fight the very mesh it stands on.
  console.log('\nground — a DECLARED walk height beats the plates and the terrain');
  const HUT = [[-27.56, 10.43], [-19.8, 10.23], [-18.64, 15.37],
    [-24.15, 16.61], [-26.81, 13.67]];
  const HUT_BOTTOM = 0.00 + DIORAMA_CLEARANCE + (-0.30);
  check('the diorama hangs at bottom_y −0.28', HUT_BOTTOM, -0.28, 1e-9);
  const HUT_WALK = HUT_BOTTOM + 0.35;
  check('a dialled walk_y 0.35 is walk_y_world 0.07', HUT_WALK, 0.07, 1e-9);
  const LAKE_FLOORS = [{ roomId: 'd5535ee7', top: HUT_WALK, outline: HUT }];
  // The hut's anchor point (payload `anchor` [−21.28, 13.12]) is inside it.
  check('inside the hut the DECLARATION answers',
    declaredFloorAt(LAKE_FLOORS, -21.28, 13.12), 0.07, 1e-9);
  check('...and the figure stands one clearance above it: 0.08',
    declaredFloorAt(LAKE_FLOORS, -21.28, 13.12) + WALK_CLEARANCE_M, 0.08, 1e-9);
  check('...0.08 above the bare terrain the room would otherwise give',
    declaredFloorAt(LAKE_FLOORS, -21.28, 13.12) + WALK_CLEARANCE_M - 0.00,
    0.08, 1e-9);
  // THE WORLD STILL WINS where it is higher (§ A16). 0.18 is the MEASURED
  // world ground inside the hut's hull, over the pin; the declaration answers
  // 0.08, so the figure stands on the landscape. Both readings of the same
  // rule are pinned, so a future change to either cannot pass unnoticed.
  check('the world relief over the See out-tops the whole chain (0.18 > 0.08)',
    standY(declaredFloorAt(LAKE_FLOORS, -21.28, 13.12) + WALK_CLEARANCE_M,
      0.18), 0.18, 1e-9);
  check('...and on level ground the declaration is what answers',
    standY(declaredFloorAt(LAKE_FLOORS, -21.28, 13.12) + WALK_CLEARANCE_M,
      0.0), 0.08, 1e-9);
  check('outside the hut nothing is declared', declaredFloorAt(LAKE_FLOORS, 0, 0), null);
  check('no declarations at all', declaredFloorAt([], -21.28, 13.12), null);
  check('...nor a tile that never got a list',
    declaredFloorAt(undefined, -21.28, 13.12), null);
  // A declaration of 0 is a VALUE ("the lower edge is the floor"), never
  // "unset" — the same law the sidecar setter states.
  check('a declared 0 is an answer, not an absence',
    declaredFloorAt([{ roomId: 'a', top: 0, outline: HUT }], -21.28, 13.12), 0);
  // MOST SPECIFIC FIRST: "Seeufer" is an always-visible outdoor zone that
  // covers the shore the hut stands on. Were both to declare, the hut wins —
  // its hull is the smaller one. Derived on two squares so the areas are
  // checkable by hand: 20 × 20 = 400 m² against 2 × 2 = 4 m².
  const BIG = [[-10, -10], [10, -10], [10, 10], [-10, 10]];      // 400 m²
  const SMALL = [[-1, -1], [1, -1], [1, 1], [-1, 1]];            //   4 m²
  check('the SMALLER hull wins where two declarations overlap',
    declaredFloorAt([{ roomId: 'zone', top: 0.09, outline: BIG },
      { roomId: 'hut', top: 0.16, outline: SMALL }], 0, 0), 0.16);
  check('...in either list order',
    declaredFloorAt([{ roomId: 'hut', top: 0.16, outline: SMALL },
      { roomId: 'zone', top: 0.09, outline: BIG }], 0, 0), 0.16);
  check('...and outside the small one the big one still answers',
    declaredFloorAt([{ roomId: 'zone', top: 0.09, outline: BIG },
      { roomId: 'hut', top: 0.16, outline: SMALL }], 5, 5), 0.09);
  // A degenerate hull encloses nothing and may never claim a point.
  check('a two-point "hull" declares nothing',
    declaredFloorAt([{ roomId: 'x', top: 5, outline: [[0, 0], [1, 1]] }], 0.5, 0.5),
    null);

  // ── § S  THE STOREY-0 GROUND LIFT (§ A16.9, finding round 2026-08-21) ────
  //
  // THE DEFECT, in the numbers that were measured on the live world. Since
  // E5a the storey-0 floor is the TERRAIN, but the payload states every
  // placement against ONE datum: the ground under the location's anchor pin.
  // "Mondscheinsee" is pinned in its own lake bed —
  //
  //     h_final(pin  -1490, -770)                    = -2.000 m
  //     diorama "Nixenstrand"  anchor (19.71, -28.82), bottom_y -0.28
  //       drawn at   -2.000 + (-0.28)                = -2.280 m
  //       terrain at  h_final(-1470.29, -798.82)     = +0.277 m
  //       => buried   -2.280 - 0.277                 = -2.557 m
  //     diorama d5535ee7       anchor (-21.28, 13.12), bottom_y -0.28
  //       terrain at  h_final(-1511.28, -756.88)     = +0.335 m
  //       => buried   -2.280 - 0.335                 = -2.615 m
  //
  // The lift is `groundAt(x, z) - datum`, so it is +2.277 and +2.335 and the
  // two huts land on +0.277 - 0.28 and +0.335 - 0.28 — their own shore, with
  // `bottom_y` still meaning exactly what it meant.
  console.log('\nstorey-0 ground lift — a placement stands on ITS OWN ground');
  const { storeyGroundLift, flatGround } =
    await loadSharedModule('packages/scene-render/src/storeyGround.ts');
  const LAKE_DATUM = -2.0;
  const lake = (x, z) => (x === -1470.29 && z === -798.82 ? 0.277
    : x === -1511.28 && z === -756.88 ? 0.335 : LAKE_DATUM);
  check('Nixenstrand is lifted by +2.277',
    storeyGroundLift(0, -1470.29, -798.82, LAKE_DATUM, lake), 2.277, 1e-9);
  // WORLD y = datum + bottom_y + lift, the frame the terrain is measured in:
  //   -2.000 + (-0.28) + 2.277 = -0.003
  const worldYOf = (bottomY, x, z) =>
    LAKE_DATUM + bottomY + storeyGroundLift(0, x, z, LAKE_DATUM, lake);
  check('...which puts its bottom_y -0.28 on world -0.003, not on -2.280',
    worldYOf(-0.28, -1470.29, -798.82), -0.003, 1e-9);
  check('the second hut is lifted by +2.335',
    storeyGroundLift(0, -1511.28, -756.88, LAKE_DATUM, lake), 2.335, 1e-9);
  // RED: the flat-datum burial is what the rule must NOT reproduce. What is
  // LEFT under the terrain is the author's own dial and nothing else —
  //   bottom_y -0.28 = DIORAMA_CLEARANCE 0.02 + model_offset_y -0.30,
  // so the hut sits 0.28 m into its shore because someone asked it to, not
  // 2.557 m into the lake bed because the datum was the wrong one.
  check('RED: 2.557 m of burial becomes the dialled 0.28 m',
    Number((0.277 - worldYOf(-0.28, -1470.29, -798.82)).toFixed(3)), 0.28);
  check('RED: ...and the second hut the same 0.28, not 2.615',
    Number((0.335 - worldYOf(-0.28, -1511.28, -756.88)).toFixed(3)), 0.28);
  // At the pin itself the ground IS the datum, so the lift is 0 — which is
  // why a BUILT location (plateau stamped flat to that very height, § A16.4)
  // never moves by this rule at all.
  check('on the plateau of a built plot the lift is 0',
    storeyGroundLift(0, -1550, -760, 0.0, () => 0.0), 0, 1e-12);
  // THE THREE NON-LIFTERS.
  check('a DECLARED storey is not lifted', storeyGroundLift(1, 0, 0, 0, lake), 0);
  check('...nor a basement', storeyGroundLift(-1, 0, 0, 0, lake), 0);
  check('no sampler = no lift', storeyGroundLift(0, -1470.29, -798.82, LAKE_DATUM, null),
    0);
  check('...and an undefined sampler either',
    storeyGroundLift(0, -1470.29, -798.82, LAKE_DATUM, undefined), 0);
  // A height field that has not arrived must never drop a scene to zero.
  check('a NaN answer is "nothing to say", not a lift of -datum',
    storeyGroundLift(0, 0, 0, LAKE_DATUM, () => NaN), 0);
  check('...and so is a non-finite datum',
    storeyGroundLift(0, 0, 0, NaN, () => 5), 0);
  // A missing `level` reads as storey 0 — the payload omits it on a prop.
  check('an absent level means storey 0 and IS lifted',
    storeyGroundLift(undefined, -1470.29, -798.82, LAKE_DATUM, lake), 2.277, 1e-9);
  // THE ADMIN PREVIEW runs the very same formula on a FLAT stage, and that is
  // the whole reason its lift is 0: not an exemption, an answer.
  check('the flat admin stage answers 0 through the same formula',
    storeyGroundLift(0, 123.4, -56.7, 0, flatGround(0)), 0, 1e-12);
  check('...and a flat stage on a non-zero datum too',
    storeyGroundLift(0, 123.4, -56.7, -2, flatGround(-2)), 0, 1e-12);

  // ── § S2  THE FIELD ARRIVES LATE (user finding 2026-08-21) ───────────────
  //
  // THE DEFECT, and it is a RACE, not a number: the lift above was read ONCE,
  // when the scene mounted. On a fresh page load a scene mounts as soon as its
  // payload is there, which is BEFORE the 2 m height tiles under it — the
  // sampler then answers the coarse overview, which at the Mondscheinsee does
  // not even know the +2.8 m rise out of the lake bed and reports the pin's own
  // -2.000 m. So the Mondscheinhütte was lifted by 0, stayed at its composed
  // -2.280, and was buried. Re-saving the location changed the signature, the
  // scene remounted at a moment when the tiles WERE there, and the hut stood
  // correctly — until the next refresh. The world props never had this: they
  // re-drape whenever the relief moves (§ A9a).
  //
  // THE TWO PHASES, by hand, for the hut at (-1511.28, -756.88), bottom_y
  // -0.28, on the datum -2.000:
  //
  //   phase 1  overview only:  ground = -2.000 (the pin's own height)
  //            lift  = -2.000 - (-2.000)          =  0
  //            delta =  0 - 0                     =  0
  //            world = -2.000 + (-0.28) + 0       = -2.280   <- buried
  //   phase 2  the 2 m tile lands: ground = +0.335
  //            lift  =  0.335 - (-2.000)          = +2.335
  //            delta =  2.335 - 0                 = +2.335   <- the MOVE
  //            world = -2.280 + 2.335             = +0.055
  //
  // and the one-shot mount with the fine field present is -2.000 + (-0.28) +
  // 2.335 = +0.055 as well. THAT equality is the property: the drawn world may
  // not depend on which of two network answers won the race.
  //
  // What is checked here is the shared law (`storeyGroundRelift`); the caller
  // that owns the object is `sceneRecipe.reliftPlacement`, and it is the three
  // lines `mock` copies below — take the step, move by `delta`, keep `lift`.
  console.log('\nthe height field arrives LATE — mount and re-lift are one move');
  const { storeyGroundRelift } =
    await loadSharedModule('packages/scene-render/src/storeyGround.ts');
  /** One placement's bookkeeping: `y` is where it hangs, `lift` what of the
   *  terrain is already in it. `place` seats it on its composed bottom_y. */
  const place = (bottomY) => ({ y: LAKE_DATUM + bottomY, lift: 0 });
  const relift = (rec, x, z, sampler, level = 0) => {
    const step = storeyGroundRelift(rec.lift, level, x, z, LAKE_DATUM, sampler);
    rec.y += step.delta;
    rec.lift = step.lift;
    return step;
  };
  const HUT_X = -1511.28, HUT_Z = -756.88;
  // The COARSE field: the overview knows the pin and nothing else, so it
  // answers the datum everywhere — including under the hut.
  const coarse = () => LAKE_DATUM;
  const hut = place(-0.28);
  check('phase 1 — mounted before the tiles: no lift at all',
    relift(hut, HUT_X, HUT_Z, coarse).delta, 0, 1e-12);
  check('...so the hut hangs at its composed -2.280', hut.y, -2.28, 1e-9);
  const step2 = relift(hut, HUT_X, HUT_Z, lake);
  check('phase 2 — the 2 m tile lands: the move is +2.335', step2.delta, 2.335, 1e-9);
  check('...and the hut stands on +0.055', hut.y, 0.055, 1e-9);
  // ORDER INDEPENDENCE, the whole point.
  const oneShot = place(-0.28);
  relift(oneShot, HUT_X, HUT_Z, lake);
  check('a scene mounted WITH the field lands on the same y', oneShot.y, hut.y, 1e-12);
  check('...and carries the same lift', hut.lift, oneShot.lift, 1e-12);
  // RED: the pre-fix behaviour is phase 1 forever. The terrain under the hut
  // is +0.335 and the hut hangs at -2.280 -> 2.615 m of soil over its floor,
  // and the Nixenstrand hut the same arithmetic at +0.277 -> 2.557 m.
  check('RED: without the re-lift the hut stays 2.615 m under its own shore',
    Number((0.335 - place(-0.28).y).toFixed(3)), 2.615);
  check('RED: ...and the second hut 2.557 m',
    Number((0.277 - place(-0.28).y).toFixed(3)), 2.557);
  check('with it, what is left is the dialled 0.28 m',
    Number((0.335 - hut.y).toFixed(3)), 0.28);
  // NO DOUBLE LIFT: the tick runs on every height revision, and a revision
  // that does not move the ground under this hut may not move the hut.
  const again = relift(hut, HUT_X, HUT_Z, lake);
  check('a second re-lift on the same field is a no-op', again.delta, 0, 1e-12);
  check('...and the hut has not moved', hut.y, 0.055, 1e-9);
  // A FIELD THAT GOES AWAY (a tile evicted from the cache) says nothing, and
  // "nothing to say" is not "come back down": the hut keeps standing where the
  // last real answer put it. The MOUNT reads the same 0 as "not lifted yet",
  // which is why this is the one case the re-lift may not simply diff.
  check('a sampler that vanishes leaves the hut where it is',
    relift(hut, HUT_X, HUT_Z, null).delta, 0, 1e-12);
  check('...and it keeps its +2.335', hut.lift, 2.335, 1e-9);
  check('...and a NaN answer is the same "nothing to say"',
    relift(hut, HUT_X, HUT_Z, () => NaN).delta, 0, 1e-12);
  check('...the hut is still on +0.055', hut.y, 0.055, 1e-9);
  // A DECLARED STOREY is not carried by the terrain in either phase.
  const upper = place(2.9);
  check('an upper storey does not move when the tile lands',
    relift(upper, HUT_X, HUT_Z, lake, 1).delta, 0, 1e-12);
  check('...it stays on its plate', upper.y, LAKE_DATUM + 2.9, 1e-12);
  // WHAT STANDS IN THE HUT MOVES WITH IT. The room's declared floor is
  // `walk_y_world + lift` and its seat marks carry the same lift, so the
  // distance between hut, floor and seat is the same in both phases — a figure
  // may never be left standing on the height the payload composed while its
  // hut sits one relief further on.
  const WALK_Y = -0.26;                       // the hut's floor plank, dialled
  const declaredAt = (lift) => WALK_Y + lift;
  check('the declared floor moves by the very same 2.335',
    declaredAt(step2.lift) - declaredAt(0), 2.335, 1e-9);
  const seat = { y: -2.28 + 0.45, lift: 0 };  // a prop seat mark, composed
  relift(seat, HUT_X, HUT_Z, coarse);
  const seatCoarse = seat.y - place(-0.28).y;
  relift(seat, HUT_X, HUT_Z, lake);
  check('the seat mark keeps its 0.45 m over the hut base, before and after',
    [seatCoarse, seat.y - hut.y], [0.45, 0.45], 1e-9);

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
  console.log('\nthe tile DATUM arrives late too — the building hangs on it');
  const { tileDatumStep } =
    await loadSharedModule('packages/scene-render/src/storeyGround.ts');
  const PLATEAU_V8 = -0.4549, PLATEAU_V7 = -0.1269, COARSE = -0.2712;
  const PIN_X = 47, PIN_Z = 30;
  // A prop of the yard, 5 m off the pin on the ramp, where the v8 field
  // answers its own height — the terrain under a scene is not one number.
  const PROP_X = 52, PROP_Z = 30, PROP_G = -0.40;
  const fine = (x) => (x === PROP_X ? PROP_G : PLATEAU_V8);   // the 2 m tiles
  const overview = () => COARSE;          // the coarse field, before them
  /** One tile's bookkeeping, exactly the fields `redatumTile` + `reliftScene`
   *  move: the datum, the building hanging in the frame, a lifted yard prop,
   *  and a `fixed` prop marker that is composed in WORLD space and is
   *  therefore the one thing the frame does not carry by itself. */
  const BUILDING_BOTTOM = -0.05;          // the author's own sink dial
  const PROP_BOTTOM = 0.02;               // the prop's composed bottom_y
  const MARKER_OVER_PROP = 0.45;          // its seat mark
  const tileOn = (datum) => ({
    datum,
    // a group child: its world y is `datum + local`
    buildingLocal: BUILDING_BOTTOM,
    propLocal: PROP_BOTTOM, propLift: 0,
    // a world-space record that is NOT parented by the frame
    markerY: datum + PROP_BOTTOM + MARKER_OVER_PROP, markerLift: 0,
  });
  const buildingY = (t) => t.datum + t.buildingLocal;
  const propY = (t) => t.datum + t.propLocal;
  /** `redatumTile` + the `reliftScene(tile, datumDelta)` that follows it on the
   *  same beat — the second is handed the first's move, because the world-space
   *  records of a mounted scene (room doors, elevator stops, `fixed` markers)
   *  are not parented by the frame and have to be carried by hand. */
  const redatum = (t, sampler) => {
    const step = tileDatumStep(t.datum, PIN_X, PIN_Z, sampler);
    t.datum = step.datum;
    t.markerY += step.delta;              // reliftScene's `datumDelta` pass
    const back = storeyGroundRelift(t.propLift, 0, PROP_X, PROP_Z, t.datum,
                                    sampler);
    t.propLocal += back.delta;
    t.propLift = back.lift;
    const mark = storeyGroundRelift(t.markerLift, 0, PROP_X, PROP_Z, t.datum,
                                    sampler);
    t.markerY += mark.delta;
    t.markerLift = mark.lift;
    return step;
  };
  // PHASE 1 — the tile is built before the 2 m tiles are there.
  const kai = tileOn(COARSE);
  check('RED: on the coarse datum the house hangs 0.1837 m too high',
    Number((buildingY(kai) - (PLATEAU_V8 + BUILDING_BOTTOM)).toFixed(4)),
    0.1837);
  // PHASE 2 — the tiles land.
  check('the tiles land: the frame moves by -0.1837',
    redatum(kai, fine).delta, -0.1837, 1e-9);
  check('...the house stands on its plateau, minus its own dialled 0.05',
    Number((buildingY(kai) - PLATEAU_V8).toFixed(4)), BUILDING_BOTTOM);
  // ORDER INDEPENDENCE — the whole point, as in § S2.
  const oneShotTile = tileOn(PLATEAU_V8);
  check('a tile built WITH the field lands on the same house y',
    buildingY(oneShotTile), buildingY(kai), 1e-12);
  check('...and on the same datum', kai.datum, PLATEAU_V8, 1e-12);
  // THE RE-BAKE, the user's actual regression: the tile was built when the
  // ground under the plot was v7's, and the water rebuild moved it.
  const rebaked = tileOn(PLATEAU_V7);
  check('RED: after bake v8 the v7 tile leaves the house 0.3280 m in the air',
    Number((buildingY(rebaked) - (PLATEAU_V8 + BUILDING_BOTTOM)).toFixed(4)),
    0.3280);
  check('the new height revision moves the frame by -0.3280',
    redatum(rebaked, fine).delta, -0.3280, 1e-9);
  check('...and the house is back on the ground', buildingY(rebaked),
    PLATEAU_V8 + BUILDING_BOTTOM, 1e-9);
  // NO DOUBLE MOVE: a revision that does not move the ground under the pin
  // may not move the tile.
  check('a second re-datum on the same field is a no-op',
    redatum(kai, fine).delta, 0, 1e-12);
  // "NOTHING TO SAY" IS NOT "COME BACK DOWN" — the same rule the lift has: a
  // tile evicted from the cache keeps the datum it is standing on and must
  // never be dropped to the world zero.
  check('a sampler that vanishes leaves the tile where it is',
    redatum(kai, null).delta, 0, 1e-12);
  check('...and a NaN answer is the same "nothing to say"',
    redatum(kai, () => NaN).delta, 0, 1e-12);
  check('...the house is still on its plateau', buildingY(kai),
    PLATEAU_V8 + BUILDING_BOTTOM, 1e-9);
  // AND NOW THE PROPERTY THAT MAKES MOVING THE FRAME SAFE — NO DOUBLE MOVE.
  // A lifted placement is a CHILD of the frame, so the datum correction moves
  // it too; its re-lift on the same beat takes exactly that much back off. So
  // what the yard prop ends up moving by is the ground under ITS OWN anchor
  // and nothing else, by hand:
  //
  //   phase 1  coarse:  lift  = -0.2712 - (-0.2712)      =  0
  //                     world = -0.2712 + 0.02           = -0.2512
  //   phase 2  fine:    the frame moves -0.1837 with everything in it,
  //                     lift  = -0.400 - (-0.4549)       = +0.0549
  //                     world = -0.4549 + 0.02 + 0.0549  = -0.3800
  //   the prop moved -0.1288 = -0.400 - (-0.2712), the move of ITS ground —
  //   not the -0.1837 of the frame, and not the -0.3125 of both.
  const stable = tileOn(COARSE);
  redatum(stable, overview);              // mounted and lifted on the coarse
  check('phase 1 — the yard prop hangs on the coarse ground',
    propY(stable), -0.2512, 1e-9);
  const propBefore = propY(stable);
  const markerBefore = stable.markerY;
  check('the datum correction itself is -0.1837',
    redatum(stable, fine).delta, -0.1837, 1e-9);
  check('...and the prop stands on ITS OWN ground, not on the frame move',
    propY(stable), PROP_G + PROP_BOTTOM, 1e-9);
  check('RED: which is a move of -0.1288, never the -0.3125 of a double move',
    Number((propY(stable) - propBefore).toFixed(4)), -0.1288);
  check('...and the seat mark moved by exactly the same -0.1288',
    Number((stable.markerY - markerBefore).toFixed(4)), -0.1288);
  check('...so it still sits 0.45 m over the prop it belongs to',
    stable.markerY - propY(stable), MARKER_OVER_PROP, 1e-9);
  // ORDER INDEPENDENCE for the yard as well: a tile built and mounted with the
  // fine field in place lands the prop on the very same y.
  const oneShotYard = tileOn(PLATEAU_V8);
  oneShotYard.propLift = storeyGroundRelift(0, 0, PROP_X, PROP_Z,
                                            PLATEAU_V8, fine).lift;
  oneShotYard.propLocal += oneShotYard.propLift;
  check('a tile mounted WITH the field puts the prop on the same y',
    propY(oneShotYard), propY(stable), 1e-12);

  // --- CLIP TRANSITIONS -----------------------------------------------
  // The clip that has to play BETWEEN two clips. The precedence here MIRRORS
  // `animation_clips.resolve_transition` on the server, and the same cases are
  // checked there (scripts/smoke_locomotion_clips.py, group [transitions]) —
  // two implementations of one rule, so both are pinned to the same table.
  //
  // Derived by hand from the rule: both sides named beats the exit rule
  // (`from` named, `to` "*"), which beats the enter rule ("*" -> `to`). The
  // table is fed in the LEAST specific order on purpose, so an implementation
  // that simply takes the first match fails.
  const { setClipTransitions, clipTransition } = walk;
  // `clipTransition` hands back the WHOLE rule (the clip and how fast the
  // figure may get going belong together); these cases are about which rule
  // wins, so they read the clip off it.
  const via = (a, b) => clipTransition(a, b)?.kind ?? '';
  check('no table means no transition', via('sit', 'walk'), '');
  setClipTransitions([
    { from: '*', to: 'walk', kind: 'stroll' },
    { from: 'sit', to: '*', kind: 'idle' },
    { from: 'sit', to: 'walk', kind: 'run' },
  ]);
  check('both sides named wins over the exit rule', via('sit', 'walk'), 'run');
  check('the exit rule covers every other target', via('sit', 'jog'), 'idle');
  check('the enter rule covers every other origin', via('idle', 'walk'), 'stroll');
  check('an unruled pair stays empty', via('idle', 'jog'), '');
  check('the same kind twice is no transition', via('walk', 'walk'), '');
  check('case and padding do not matter', via('  SIT ', 'WALK'), 'run');
  check('an empty side is no transition', via('', 'walk'), '');
  check('junk entries are dropped, the good ones survive',
    setClipTransitions([{ from: 'sit', to: 'walk', kind: 'run' }, null, { from: 'sit' }, 7]).length, 1);
  check('a junk table leaves plain switching', setClipTransitions('nonsense').length, 0);
  check('…and then every lookup is empty again', via('sit', 'walk'), '');

  // Place-group entry rules are server-only: real pose keys never equal @seat.
  setClipTransitions([
    { from: 'walking', to: '@seat', kind: 'idle' },
    { from: 'walking', to: 'reading', kind: 'run' },
  ]);
  check('group target does not match a client pose', via('walking', 'sitting'), '');
  check('explicit pose transition still matches', via('walking', 'reading'), 'run');
  setClipTransitions([]);

  // --- how fast the figure gets going DURING the bridge ------------------
  // `accel` is the fraction of normal speed gained per second, and the client
  // normalises it exactly as the server does (scripts/smoke_locomotion_clips.py
  // [transitions]): missing, junk, negative and zero all mean 0 — the figure
  // stays on the spot, which is standing up out of a seat — and an absurd
  // value is capped at 8 rather than refused.
  const accelOf = (value) => setClipTransitions(
    [{ from: 'sit', to: 'walk', kind: 'run', ...(value === undefined ? {} : { accel: value }) }],
  )[0].accel;
  check('a rule without a value holds the figure', accelOf(undefined), 0);
  check('a value is kept', accelOf(1.5), 1.5);
  check('junk holds the figure', accelOf('nonsense'), 0);
  check('a negative number holds the figure', accelOf(-2), 0);
  check('an absurd value is capped', accelOf(99), 8);
  setClipTransitions([{ from: 'sit', to: 'walk', kind: 'run', accel: 2 }]);
  check('…and the lookup carries it', clipTransition('sit', 'walk').accel, 2);

  // --- WHAT THAT VALUE IS WORTH WHILE THE BRIDGE PLAYS -------------------
  // `bridgePace(accel, elapsed)` is the fraction of its speed a figure has
  // while a bridge clip runs, and the whole rule is
  //
  //     accel <= 0            ->  0            (held for the whole clip)
  //     otherwise             ->  min(1, max(0.02, accel · elapsed))
  //
  // Derived by hand: an `accel` of 1 reaches full speed after 1 s and is at
  // a quarter after 0.25 s; 0.5 takes two seconds; 4 is at 0.04 after 10 ms.
  // The floor of 0.02 is not cosmetic — 0 is the answer of a HELD bridge, and
  // the two must stay apart at every point of the ramp, including t = 0.
  //
  // The pair `Figure.paceLimit` builds from it — 1 while no bridge runs, this
  // number while one does — is what `npcs.tick` scales its step by, and it is
  // the ONLY brake on the step: a held figure neither walks nor turns, and
  // that is what makes a 7-second getting-up clip play out without the body
  // drifting towards the key (the bug of 2026-09-10).
  const { bridgePace } = walk;
  check('a rule without a speed-up holds the figure at t = 0', bridgePace(0, 0), 0);
  check('…and still holds it seven seconds in', bridgePace(0, 7), 0);
  check('junk and a negative value hold it too',
    [bridgePace('nonsense', 3), bridgePace(-1, 3), bridgePace(NaN, 3)].join(','), '0,0,0');
  check('a ramping rule is never exactly 0 at the start', bridgePace(1, 0), 0.02);
  check('…nor for a value below the floor', bridgePace(4, 0.001), 0.02);
  check('accel 4 after 10 ms', bridgePace(4, 0.01), 0.04);
  check('accel 1 after a quarter second', bridgePace(1, 0.25), 0.25);
  check('accel 1 reaches full speed after one second', bridgePace(1, 1), 1);
  check('accel 0.5 is half way after one second', bridgePace(0.5, 1), 0.5);
  check('…and full after two', bridgePace(0.5, 2), 1);
  check('full speed is the cap, not a stage', bridgePace(1, 30), 1);
  check('a clock that runs backwards is no speed', bridgePace(1, -5), 0.02);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(`\nsmoke_walk_math: ${e?.message || e}`);
  process.exit(1);
});
