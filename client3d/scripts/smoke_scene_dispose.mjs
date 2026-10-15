#!/usr/bin/env node
/**
 * Smoke check for the GPU-RESOURCE LIFETIME of a mounted LOCATION SCENE in the
 * 3D client (review finding UI-2): what `mountShell` / `mountDetail` build itself, what it
 * only borrows, and what `unmountShell` has to hand back when the scene is
 * replaced (remount on a changed signature), rebuilt or dropped.
 *
 * Usage:  node client3d/scripts/smoke_scene_dispose.mjs
 *         (needs three + esbuild; no server, no world DB, no WebGL — three.js
 *          dispatches a 'dispose' event on geometries, materials and textures,
 *          and that event IS the measurement here)
 *
 * The fixture is a hand-built scene payload, so the expected counts are
 * counted off it rather than read out of the code:
 *
 *   2 plates   (storey plate + room plate, texture_kind "floor")
 *                → 2 ExtrudeGeometry/ShapeGeometry + 2 materials + 2 texture
 *                  CLONES of the ONE library image (`tiledTexture` clones per
 *                  primitive — the library original must survive)
 *   2 walls    (one plastered, one glass)
 *                → 2 BoxGeometry + 2 materials + 1 texture clone
 *                  (glass takes its colour from `style`, no map)
 *   1 extra    (elevator pad, untextured) → 1 BoxGeometry + 1 material
 *   1 prop without a mesh (`placeholder_dims`)
 *                → 1 BoxGeometry + 1 material (`buildPlaceholder`)
 *   1 prop WITH a mesh, cut by `cut_plane`
 *                → geometry + base material are the LOADER CACHE's (shared by
 *                  every other placement of the same URL) and must NOT be
 *                  freed; the cut CLONE hung on the mesh is this mount's
 *   1 building model
 *                → geometry/base material shared again; the shell material
 *                  clones `applySceneBuilding` pushes into `roofMats` are this
 *                  mount's, and the model group hangs straight off the TILE,
 *                  so the unmount has to unhook it by hand
 *
 * Owned vs. borrowed is decided WITHOUT looking at the fix's own bookkeeping:
 * everything reachable from the tile after the mount is collected, and what
 * belongs to one of the two shared templates (their geometries, materials and
 * textures, plus the surface library's image) is subtracted. What is left is
 * what this mount produced, and each of those must see EXACTLY ONE dispose
 * event — never two, which would mean two owners for one buffer.
 *
 * REGRESSION: cases 1–5 keep the original d6bc7673^ leak baseline.
 * [1] unmount → every owned resource 1, every shared resource 0, and the
 *     building model no longer hangs on the tile.
 * [2] remount with a changed signature (`mountShell` unmounts first) → the
 *     first mount's resources 1, the second mount's still 0 while it stands.
 * [3] the DROP path, in the order `main.ts` uses it: `unmountShell` first, then
 *     the disposing traversal over `tile.group`. Neither may the traversal miss
 *     the scene (the pre-fix bug: the unmount had already unhooked the scene
 *     group, so the traversal never reached it) nor may the two together free
 *     one buffer twice — so again exactly 1 per owned resource.
 * [4] a location WITHOUT a building model wears the far-view shell, which
 *     COPIES the plates and walls: the copies share their geometry with the
 *     originals and own only their material clone. So the same "exactly 1"
 *     holds — a teardown that simply traversed and disposed would free every
 *     copied geometry twice.
 * [5] RED counter-probe: the SAME checks against the pre-fix `sceneRecipe.ts`
 *     out of `git show d6bc7673^:…` (the pre-fix revision), bundled through an esbuild onLoad plugin.
 *     There the owned resources must come out at 0 — that is the leak.
 */
import { execFileSync } from 'node:child_process';
// The counter-probe bundles the PRE-FIX sceneRecipe.ts. Pinned to the parent of the
// commit that introduced the ownership ledger (d6bc7673) — 'HEAD' would compare the
// file with itself as soon as that commit is HEAD.
const PRE_FIX_REV = 'd6bc7673^';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const RECIPE = 'client3d/src/scene/sceneRecipe.ts';

// ── the DOM this module touches (labels, the texture loader's <img>) ────────
globalThis.self = globalThis;
if (!globalThis.window) globalThis.window = globalThis;
function fakeElement(tag) {
  const listeners = new Map();
  const el = {
    tagName: tag,
    style: {},
    dataset: {},
    children: [],
    classList: { toggle() {}, add() {}, remove() {} },
    addEventListener(type, cb) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(cb);
    },
    removeEventListener() {},
    setAttribute() {},
    appendChild(child) { el.children.push(child); return child; },
    querySelectorAll() { return []; },
    remove() { el.removed = true; },
  };
  if (tag === 'img') {
    Object.defineProperty(el, 'src', {
      get() { return el._src; },
      set(v) {
        el._src = v;
        // What a browser does once the bytes are in: the loader waits for it.
        setTimeout(() => (listeners.get('load') ?? []).forEach((cb) => cb()), 0);
      },
    });
  }
  return el;
}
if (!globalThis.document) {
  globalThis.document = {
    createElement: fakeElement,
    createElementNS: (_ns, tag) => fakeElement(tag),
    querySelectorAll: () => [],
    body: fakeElement('body'),
  };
}
if (!globalThis.location) globalThis.location = { search: '' };

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const eq = (label, actual, expected) =>
  check(label, actual === expected, `${actual} (expected ${expected})`);

const THREE = await import('three');

/** Bundle the client modules under test. `ref` = a git revision whose version
 *  of sceneRecipe.ts is used instead of the working tree's (the RED probe). */
async function loadClient(ref) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  const oldSource = ref
    ? execFileSync('git', ['show', `${ref}:${RECIPE}`], { cwd: ROOT, encoding: 'utf8' })
    : null;
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = [
      ref ? `export { mountScene as mountShell, unmountScene as unmountShell } from '${src}/sceneRecipe'; export async function mountDetail() { return true; }` : `export { mountShell, mountDetail, unmountDetail, unmountShell, reliftScene, setSceneModelTier, detailVerifyReport } from '${src}/sceneRecipe';`,
      `export { buildTile, setSurfaceTextures, preloadSurfaceTexture, setWorldGround, tileGroundY } from '${src}/tiles';`,
      `export { buildPlace } from '${src}/places';`,
    ].join('\n');
    const stubs = {
      name: 'smoke-stubs',
      setup(build) {
        // Lease stubs count consumer ownership without disposing shared resources.
        build.onLoad({ filter: /scene[/\\]propAssets\.ts$/ }, () => ({
          contents: `export function setPropLoadFocus() {}
            async function load(url) {
              globalThis.__smokeUrls?.push(url);
              return globalThis.__smokeLoad ? globalThis.__smokeLoad(url) : globalThis.__smokeTemplates?.get(url) ?? null;
            }
            ${ref ? 'export { load as loadGlb };' : ''}
            export async function leaseGlb(url) {
              const template = await load(url); if (!template) return null;
              const counts = globalThis.__leaseCounts ??= new Map();
              counts.set(url, (counts.get(url) ?? 0) + 1);
              let released = false;
              return { template, release() {
                if (released) throw new Error('lease released twice: ' + url);
                globalThis.__beforeLeaseRelease?.(url);
                released = true; counts.set(url, counts.get(url) - 1);
              } };
            }`,
          loader: 'ts',
        }));
        if (oldSource) {
          build.onLoad({ filter: /scene[/\\]sceneRecipe\.ts$/ },
                       () => ({ contents: oldSource, loader: 'ts' }));
        }
      },
    };
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'client.mjs'), external: ['three', 'three/*'],
      plugins: [stubs],
      tsconfig: join(ROOT, 'client3d/tsconfig.json'),
    });
    const file = join(dir, `client${ref ? '-ref' : ''}.mjs`);
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

// ── the fixture ────────────────────────────────────────────────────────────

const STYLE = {
  wall_color: '#cfc7ba', floor_color: '#b9ad9a', glass_color: '#bcd8e6',
  glass_opacity: 0.25, upper_wall_opacity: 0.35, upper_floor_opacity: 0.35,
  room_palette: ['#ccc'], elevator_pad_color: '#888',
};

const square = (x, z, r) => [[x - r, z - r], [x + r, z - r], [x + r, z + r], [x - r, z + r]];

/** One payload; `signature` is what makes a remount a remount. */
function payload(signature) {
  return {
    signature,
    rooms: [{ room_id: 'r1', level: 1, always_visible: false, outline: square(0, 0, 3) }],
    extent_m: 12, k: 1, storey_m: 3,
    levels: [{ level: 1, floor_y: 3 }],
    style: STYLE,
    plates: [
      { level: 1, outline: square(0, 0, 6), holes: [], top_y: 3, thickness: 0.2,
        texture_kind: 'floor', opacity_role: 'upper' },
      { level: 1, outline: square(0, 0, 3), holes: [], top_y: 3.05, thickness: 0,
        texture_kind: 'floor', opacity_role: 'upper', room_id: 'r1' },
    ],
    floor_plan: [],
    walls: [
      { level: 1, from: [-3, -3], to: [3, -3], base_y: 3, height: 2.4, thickness: 0.2,
        texture_kind: 'plaster', opacity_role: 'upper', room_id: 'r1',
        outward_normal: [0, -1] },
      { level: 1, from: [3, -3], to: [3, 3], base_y: 3, height: 2.4, thickness: 0.1,
        glass: true, opacity_role: 'upper', room_id: 'r1', outward_normal: [1, 0] },
    ],
    extras: [
      { kind: 'elevator_pad', center: [2, 3.1, 2], size: [1, 0.1, 1], level: 1 },
    ],
    stairs: [],
    models: [
      { role: 'building', id: 'b1', variants: { full: '/building.glb' }, level: 0,
        fix_euler: { x: 0, y: 0, z: 0 }, yaw_deg: 0, measure: 'xz', max_m: 10,
        anchor: [0, 0], bottom_y: 0, display: 'shell' },
      { role: 'prop', id: 'p1', room_id: 'r1', variants: { full: '/prop.glb' }, level: 1,
        fix_euler: { x: 0, y: 0, z: 0 }, yaw_deg: 0, measure: 'xz', max_m: 1,
        anchor: [1, 1], bottom_y: 3.05,
        cut_plane: { normal: [1, 0, 0], constant: 0 } },
      { role: 'prop', id: 'p2', room_id: 'r1', variants: {}, level: 1,
        fix_euler: { x: 0, y: 0, z: 0 }, yaw_deg: 0, measure: 'xz',
        anchor: [-1, -1], bottom_y: 3.05,
        placeholder_dims: { w: 0.6, d: 0.6, h: 0.8 } },
    ],
    figures: { base_height_m_world: 1.7, stand_clearance: 0.02 },
    markers: [], doorways: [], problems: [], outdoor_rooms: [], corridors: [],
  };
}

/** The same place with no model at all — `wantsRecipeShell` then stands the
 *  recipe's own primitives outside as the far-view shell. */
function shellPayload(signature) {
  const p = payload(signature);
  p.models = [];
  return p;
}

const LOCATION = {
  id: 'demo-house', name: 'Demo House', pos_x: 0, pos_z: 0, yaw_deg: 0,
  boundary: square(0, 0, 6), plan_width_m: 12,
  rooms: [{ id: 'r1', name: '', layout: null }],
  map3d: { style: 'building' },
};

/** One shared GLB template, retained by the lease pool. */
function template(tag, store) {
  const group = new THREE.Group();
  const geo = new THREE.BoxGeometry(1, 1, 1);
  const mat = new THREE.MeshStandardMaterial();
  mat.map = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
  group.add(new THREE.Mesh(geo, mat));
  store.geometries.add(geo);
  store.materials.add(mat);
  store.textures.add(mat.map);
  group.name = tag;
  return group;
}

/** Every geometry/material/texture reachable from an object. */
function reachable(root) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  root.traverse((o) => {
    const mesh = o;
    if (!mesh.isMesh) return;
    if (mesh.geometry) geometries.add(mesh.geometry);
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      if (!m) continue;
      materials.add(m);
      if (m.map) textures.add(m.map);
    }
  });
  return { geometries, materials, textures };
}

/** Count dispose events per resource. */
function watcher() {
  const counts = new Map();
  return {
    watch(res) {
      if (counts.has(res)) return;
      counts.set(res, 0);
      res.addEventListener('dispose', () => counts.set(res, counts.get(res) + 1));
    },
    hits(res) { return counts.get(res) ?? -1; },
    /** [min, max] over a set — one number per category is enough to read. */
    range(set) {
      let lo = Infinity;
      let hi = -Infinity;
      for (const res of set) {
        const n = counts.get(res) ?? -1;
        lo = Math.min(lo, n);
        hi = Math.max(hi, n);
      }
      return set.size ? [lo, hi] : [0, 0];
    },
  };
}

/** What ONE mount produced: reachable minus the shared templates' own. */
function ownedOf(tile, shared) {
  const all = reachable(tile.group);
  const owned = { geometries: new Set(), materials: new Set(), textures: new Set() };
  for (const kind of ['geometries', 'materials', 'textures']) {
    for (const res of all[kind]) if (!shared[kind].has(res)) owned[kind].add(res);
  }
  return owned;
}

const countOwned = (o) => o.geometries.size + o.materials.size + o.textures.size;

/** The teardown of the DROP path, copied from `main.ts:dropTile` INCLUDING its
 *  order: the scene's own unmount first, then the traversal that frees what
 *  `buildTile` made. The check is that the two together free every owned
 *  buffer exactly once. */
function dropPath(tile, unmountShell) {
  unmountShell(tile);
  const free = (o) => {
    const mesh = o;
    if (mesh.isMesh) {
      mesh.geometry.dispose();
      for (const m of (Array.isArray(mesh.material) ? mesh.material : [mesh.material])) {
        m?.dispose();
      }
    }
    for (const child of [...o.children]) free(child);
  };
  free(tile.group);
}

/**
 * Mount the fixture on a fresh tile and return everything the checks need.
 * `teardown` decides how the scene goes: the plain unmount, a remount with a
 * changed signature, or the drop path.
 */
async function run(client, label, teardown, make = payload) {
  const { mountShell, mountDetail, unmountShell, buildTile, buildPlace, setSurfaceTextures,
          preloadSurfaceTexture } = client;
  console.log(`\n${label}`);

  // The shared surface library: ONE image per kind, loaded once — every plate
  // and wall gets a CLONE of it.
  setSurfaceTextures([
    { kind: 'floor', url: '/surfaces/floor.png', size_m: 3 },
    { kind: 'plaster', url: '/surfaces/plaster.png', size_m: 2 },
  ]);
  await preloadSurfaceTexture('floor');
  await preloadSurfaceTexture('plaster');

  const w = watcher();
  const shared = { geometries: new Set(), materials: new Set(), textures: new Set() };
  globalThis.__smokeTemplates = new Map([
    ['/building.glb', template('building', shared)],
    ['/prop.glb', template('prop', shared)],
  ]);
  for (const set of Object.values(shared)) for (const res of set) w.watch(res);

  const scene = new THREE.Scene();
  const place = buildPlace(LOCATION);
  const tile = buildTile(place);
  scene.add(place.anchor);
  scene.add(tile.group);                    // a tile without a parent is "stale"

  const recipe = make('sig-a');
  await mountShell(tile, recipe);
  await mountDetail(tile, recipe);
  const owned = ownedOf(tile, shared);
  for (const set of Object.values(owned)) for (const res of set) w.watch(res);
  // The library IMAGE itself is not reachable from the tile — only clones of
  // it are — and a `Texture.source` carries no dispose event of its own. It is
  // therefore identified by that source object, and check [2] shows it is
  // still there after every clone made from it has been freed.
  const sources = new Set([...owned.textures].map((t) => t.source));

  check('the scene stands', countOwned(owned) >= 10,
        `${owned.geometries.size} geometries, ${owned.materials.size} materials, `
        + `${owned.textures.size} textures`);
  if (make === payload) {
    check('the building model hangs on the tile',
          tile.group.children.some((c) => c.name === 'building'
            || c.children.some((g) => g.name === 'building')) || !!tile.serverModel);
  } else {
    check('the far-view shell stands instead of a model', !!tile.shell,
          `${tile.shell?.children.length ?? 0} copies`);
  }

  const second = await teardown({ tile, mountShell, mountDetail, unmountShell });

  return { w, owned, shared, tile, second, sources };
}

function report(prefix, res, expected) {
  const { w, owned, shared } = res;
  for (const kind of ['geometries', 'materials', 'textures']) {
    const [lo, hi] = w.range(owned[kind]);
    check(`${prefix}: owned ${kind} disposed exactly ${expected}× `
          + `(${owned[kind].size} of them)`,
          lo === expected && hi === expected, `min ${lo}, max ${hi}`);
  }
  for (const kind of ['geometries', 'materials', 'textures']) {
    const [lo, hi] = w.range(shared[kind]);
    check(`${prefix}: shared template ${kind} untouched`,
          lo === 0 && hi === 0, `min ${lo}, max ${hi}`);
  }
}

/**
 * NEU (red on a241a8aa: layer API absent), hand-derived oracles:
 * detail_keeps_shell/shell_after_detail: subtraction of reachable shell resources
 * from the full mount gives detail ownership; 0/1 disposals before/after teardown.
 * shell_only/unmount_twice: one creation means exactly one disposal, even twice.
 * outdoor_stays: O's prop and diorama survive, I's prop leaves the graph.
 * surfaces_layer: two surface entries become precisely the outdoor entry.
 * declared_restore: I's plate 2 is overridden by diorama 5, then restored to 2;
 * centre = 2 + clearance .01; room marker = 2 + offset .25. No indoor seats remain.
 * declared_relift: datum +.5 carries the shell declaration 2 to 2.5.
 * declared_tier: new ground lift .3 makes O's 2 become 2.3, including walking
 * height centre.y + 2.3 + .01. I returns to 2 after details are removed.
 * labels_after_spots: square centred at (2,1) puts its label at x=2,z=1.
 * far_low_urls: building and outdoor specs request /low URLs, no interior URL.
 * detail_stale/swap_after_detail: removing the layer before resolution means
 * no attachment or changed floor/seat state; mountDetail returns false.
 * swap_mixed: outdoor response before teardown survives and finishes its height
 * update; indoor response after teardown cannot reintroduce geometry or seats.
 * free_after_detail: each owned resource gets one disposal, shared templates zero.
 * verify_layers: six specs split into three shell and three detail specs,
 * each report counts only its own three loaded placements.
 * NEU outdoor_doors: one outdoor and one indoor door give 2 registrations after
 * shell+detail mount; detail teardown leaves exactly the outdoor registration.
 * Its low-tier replacement must be a new live object, retain the registration
 * and swing angle .4; shell teardown leaves no registrations.
 * NEU detail_objects: every captured detail object has parent null and is
 * unreachable from tile.group after teardown, even though its room survives.
 * buildDoorMarks guard: door rebuilding cannot remove the shell's boundary marks.
 */
async function layerCases(c) {
  const { mountShell, mountDetail, unmountDetail, unmountShell } = c;
  const shared = { geometries: new Set(), materials: new Set(), textures: new Set() };
  const raw = template('model', shared);
  globalThis.__smokeTemplates = new Map(['/building.glb', '/prop.glb', '/low.glb', '/full.glb'].map((url) => [url, raw]));
  const mkTile = () => {
    c.setWorldGround(() => 0);
    const tile = c.buildTile(c.buildPlace({ ...LOCATION, rooms: [{ id: 'r1', name: 'Inside' }, { id: 'o', name: 'Outside' }] }));
    new THREE.Scene().add(tile.group);
    return tile;
  };
  const fixture = () => {
    const p = payload('layers');
    p.rooms[0].outline = square(2, 1, 3);
    p.plates[1].top_y = 2;
    p.plates[1].outline = square(2, 1, 3);
    p.rooms.push({ room_id: 'o', level: 0, outline: square(10, 0, 2) });
    p.floor_plan = [{ room_id: 'o', polygon_world: square(10, 0, 2) }];
    p.outdoor_rooms = ['o'];
    const dio = { ...p.models[1], role: 'room', cut_plane: undefined, level: 0, walk_y_world: 2, variants: { full: '/full.glb', low: '/low.glb' }, anchor: [10, 0] };
    p.models.push({ ...dio, id: 'outside', room_id: 'o' }, { ...dio, id: 'inside', room_id: 'r1', level: 1, walk_y_world: 5 }, { ...p.models[1], id: 'outprop', room_id: 'o' });
    p.models.find((m) => m.id === 'outprop').variants = { full: '/full.glb', low: '/low.glb' };
    p.models[0].variants = { full: '/full.glb', low: '/low.glb' };
    p.models[1].bottom_y = 5;
    p.models[1].max_m = .5;
    p.models[1].variants = { full: '/full.glb', low: '/low.glb' };
    p.markers = [{ room_id: 'r1', id: 'mark', source: 'room', at_world: [2, 1], slots: [[2, 1]], y_world: 3.25 }];
    return p;
  };
  const track = (resources) => {
    const w = watcher();
    for (const set of Object.values(resources)) for (const r of set) w.watch(r);
    return w;
  };
  const expectResources = (name, resources, w, n) => {
    for (const [kind, set] of Object.entries(resources)) for (const r of set) eq(`${name} ${kind}`, w.hits(r), n);
  };
  {
    const tile = mkTile(), p = fixture();
    p.models = p.models.filter((m) => m.role !== 'building');
    await mountShell(tile, p);
    const shell = ownedOf(tile, shared), sw = track(shell);
    eq('labels_after_spots x', tile.interiorLabels[0].position.x, 2);
    eq('labels_after_spots z', tile.interiorLabels[0].position.z, 1);
    const outside = tile.placedModels.filter((r) => r.spec.room_id === 'o').map((r) => r.object);
    await mountDetail(tile, p);
    const all = ownedOf(tile, shared), aw = track(all);
    eq('declared_restore mounted', tile.roomFloors.get('r1').declared, 5);
    check('declared_restore has indoor seat before removal', (tile.roomSitSpots.get('r1')?.length ?? 0) > 0);
    const detailObjects = tile.placedModels.filter((r) => r.layer === 'detail').map((r) => r.object).filter(Boolean);
    unmountDetail(tile);
    for (const object of detailObjects) {
      eq('NEU detail_objects parent', object.parent, null);
      check('NEU detail_objects unreachable', !tile.group.getObjectById(object.id));
    }
    expectResources('detail_keeps_shell', shell, sw, 0);
    for (const kind of Object.keys(all)) for (const r of all[kind]) if (!shell[kind].has(r)) eq('detail owned freed', aw.hits(r), 1);
    eq('declared_restore plate', tile.roomFloors.get('r1').declared, 2);
    eq('declared_restore centre', tile.roomCenters.get('r1').y, tile.center.y + 2.01);
    eq('declared_restore marker', tile.roomMarkers.get('r1').get('mark').slots[0].y, tile.center.y + 2.25);
    eq('declared_restore seats', tile.roomSitSpots.get('r1')?.length ?? 0, 0);
    check('outdoor_stays', outside.every((o) => o?.parent && tile.group.getObjectById(o.id)));
    check('indoor props detached', !tile.placedModels.some((r) => r.layer === 'detail'));
    unmountShell(tile); unmountShell(tile);
    expectResources('shell_after_detail / unmount_twice', shell, sw, 1);
    expectResources('combined ownership', all, aw, 1);
  }
  {
    const tile = mkTile(); await mountShell(tile, fixture());
    const owned = ownedOf(tile, shared), w = track(owned);
    unmountShell(tile); expectResources('shell_only', owned, w, 1);
  }
  {
    const tile = mkTile(), p = fixture(); await mountShell(tile, p); await mountDetail(tile, p);
    c.reliftScene(tile, .5); unmountDetail(tile);
    eq('declared_relift', tile.roomFloors.get('r1').declared, 2.5); unmountShell(tile);
  }
  {
    const tile = mkTile(), p = fixture();
    // The mount copies these surface entries synchronously; no lattice sample
    // is needed for this ownership assertion.
    p.models.find((m) => m.id === 'outside').surface = { extent_snapped: [2, 1, 2], box_min: [-1, 0, -1], box_max: [1, 1, 1], origin: [-1, -1], step: 1, cols: 3, rows: 3, values: Array(9).fill(null) };
    p.models.find((m) => m.id === 'inside').surface = p.models.find((m) => m.id === 'outside').surface;
    // Keep missing meshes away from verification of the synthetic lattice.
    const keep = globalThis.__smokeTemplates; globalThis.__smokeTemplates = new Map();
    await mountShell(tile, p); const outer = [...tile.surfaces];
    await mountDetail(tile, p); eq('surfaces_layer mounted', tile.surfaces.length, 2);
    unmountDetail(tile); check('surfaces_layer retains outdoor identity', tile.surfaces.length === 1 && tile.surfaces[0] === outer[0]);
    unmountShell(tile); globalThis.__smokeTemplates = keep;
  }
  {
    const tile = mkTile(), p = fixture(); globalThis.__smokeUrls = [];
    await mountShell(tile, p, 'low', 'low');
    // Give the outdoor prop variants too: all shell URLs must be low.
    check('far_low_urls', globalThis.__smokeUrls.length === 3 && globalThis.__smokeUrls.every((u) => u === '/low.glb'));
    unmountShell(tile); globalThis.__smokeUrls = undefined;
  }
  {
    const tile = mkTile(), p = fixture(); await mountShell(tile, p);
    await c.setSceneModelTier(tile, 'interior', 'low');
    c.setWorldGround(() => .3);
    await c.setSceneModelTier(tile, 'interior', 'full');
    eq('declared_tier O', tile.roomFloors.get('o').declared, 2.3);
    eq('declared_tier walking', c.tileGroundY(tile, new THREE.Vector3(10, 0, 0)), tile.center.y + 2.3 + .01);
    await mountDetail(tile, p); unmountDetail(tile);
    eq('declared_tier O restored', tile.roomFloors.get('o').declared, 2.3);
    eq('declared_tier I restored', tile.roomFloors.get('r1').declared, 2); unmountShell(tile);
  }
  for (const name of ['detail_stale', 'swap_after_detail', 'swap_mixed']) {
    const tile = mkTile(), p = fixture(); await mountShell(tile, p);
    if (name !== 'detail_stale') await mountDetail(tile, p);
    const waiting = [];
    globalThis.__smokeLoad = (url) => new Promise((resolve) => waiting.push(() => resolve(raw)));
    c.setWorldGround(() => .3);
    const pending = name === 'detail_stale' ? mountDetail(tile, p) : c.setSceneModelTier(tile, 'interior', 'low');
    if (name === 'swap_mixed') { waiting.shift()(); await Promise.resolve(); await Promise.resolve(); }
    if (name === 'detail_stale') unmountShell(tile); else unmountDetail(tile);
    const before = tile.roomFloors.get('r1')?.declared;
    const children = [...(tile.roomGroups.get('r1')?.children ?? [])];
    for (const done of waiting) done();
    const result = await pending;
    if (name === 'detail_stale') eq(name, result, false);
    check(`${name} no late attachment`, (tile.roomGroups.get('r1')?.children ?? []).every((child) => children.includes(child)));
    eq(`${name} indoor height unchanged`, tile.roomFloors.get('r1')?.declared, before);
    eq(`${name} no indoor seats`, tile.roomSitSpots.get('r1')?.length ?? 0, 0);
    check(`${name} no detail record`, !tile.placedModels?.some((r) => r.layer === 'detail'));
    if (name === 'swap_mixed') eq('swap_mixed outdoor height', tile.roomFloors.get('o').declared, 2.3);
    globalThis.__smokeLoad = undefined; unmountShell(tile);
  }
  {
    const tile = mkTile(), p = fixture(); await mountShell(tile, p); await mountDetail(tile, p);
    const owned = ownedOf(tile, shared), w = track(owned), borrowed = track(shared);
    unmountDetail(tile); dropPath(tile, unmountShell);
    expectResources('free_after_detail owned', owned, w, 1);
    expectResources('free_after_detail shared', shared, borrowed, 0);
  }
  {
    const tile = mkTile(), p = fixture();
    globalThis.__verify3d = true;
    const report = await mountShell(tile, p);
    eq('verify_layers shell total', report.models.total, 3);
    eq('verify_layers shell placed', report.models.placed, 3);
    eq('verify_layers detail current', await mountDetail(tile, p), true);
    check('verify_layers detail report exposed', c.detailVerifyReport(tile) === globalThis.__sceneVerify[tile.loc.id]);
    eq('verify_layers detail total', globalThis.__sceneVerify[tile.loc.id].models.total, 3);
    eq('verify_layers detail placed', globalThis.__sceneVerify[tile.loc.id].models.placed, 3);
    globalThis.__verify3d = false; unmountShell(tile);
  }
  {
    const tile = mkTile(), p = fixture();
    p.doorways = [{ at_world: [10, 0], level: 0, rooms: ['o'] },
                  { at_world: [1, 1], level: 1, rooms: ['r1'] }];
    p.models.find((m) => m.id === 'outprop').door = { opening: 0, swing: 1, hinge: 'left' };
    p.models.find((m) => m.id === 'p1').door = { opening: 1, swing: -1, hinge: 'right' };
    await mountShell(tile, p);
    const outdoor = tile.placedModels.find((r) => r.spec.id === 'outprop');
    const old = outdoor.object;
    await mountDetail(tile, p);
    eq('NEU outdoor_doors mounted count', tile.doorProps.length, 2);
    check('NEU outdoor_doors mounted live outdoor', tile.doorProps.some((d) => d.group === old));
    unmountDetail(tile);
    eq('NEU outdoor_doors detail removed count', tile.doorProps.length, 1);
    check('NEU outdoor_doors outdoor retained', tile.doorProps[0]?.group === old && !!old.parent);
    const registration = tile.doorProps.find((d) => d.group === old);
    if (registration) registration.angle = .4;
    await c.setSceneModelTier(tile, 'interior', 'low');
    check('NEU outdoor_doors replacement live', outdoor.object !== old && !!outdoor.object.parent && !!tile.group.getObjectById(outdoor.object.id));
    eq('NEU outdoor_doors old detached', old.parent, null);
    eq('NEU outdoor_doors swap count', tile.doorProps.length, 1);
    check('NEU outdoor_doors registration follows mesh', tile.doorProps[0]?.group === outdoor.object);
    eq('NEU outdoor_doors swing survives', outdoor.object.rotation.y, .4);
    unmountShell(tile);
    eq('NEU outdoor_doors shell removed count', tile.doorProps?.length ?? 0, 0);
  }
  /** NEU on a241a8aa: no lease API. Hand counts: building + outdoor diorama
   * + outdoor prop = 3 shell leases; indoor prop + diorama = 2 detail leases;
   * placeholder = 0. Total 5: /full=5. Interior swap changes four
   * /full URLs to /low: /full=1, /low=4. Rejection returns all new
   * leases. Repeated detail teardown leaves 3; shell teardown leaves 0.
   * Building material clones must be disposed before their lease is released.
   */
  for (const name of ['swap_releases_old', 'swap_rejected_releases', 'swap_then_unmount', 'layer_leases']) {
    globalThis.__leaseCounts = new Map();
    const tile = mkTile(), p = fixture();
    await mountShell(tile, p); await mountDetail(tile, p);
    const counts = globalThis.__leaseCounts;
    const initial = [...counts.values()].reduce((a, b) => a + b, 0);
    eq(`NEU ${name} one lease per loaded rec`, initial, 5);
    if (name === 'layer_leases') {
      unmountDetail(tile); unmountDetail(tile);
      eq('NEU unmountDetail releases every detail lease exactly once', [...counts.values()].reduce((a,b) => a+b,0), 3);
    } else if (name === 'swap_rejected_releases') {
      const waiting = []; globalThis.__smokeLoad = () => new Promise(resolve => waiting.push(() => resolve(raw)));
      const pending = c.setSceneModelTier(tile, 'interior', 'low');
      unmountShell(tile); waiting.forEach(done => done()); await pending;
      globalThis.__smokeLoad = undefined;
      eq('NEU swap_rejected_releases', counts.get('/low.glb'), 0);
    } else {
      await c.setSceneModelTier(tile, 'interior', 'low');
      eq(`NEU ${name} old freed`, counts.get('/full.glb'), 1);
      eq(`NEU ${name} new held`, counts.get('/low.glb'), 4);
      check(`NEU ${name} new lease attached`, tile.placedModels.filter(r => r.url === '/low.glb').every(r => r.lease?.template === raw));
    }
    const roofCounts = new Map(tile.roofMats.map(mat => [mat, 0]));
    for (const mat of roofCounts.keys()) mat.addEventListener('dispose', () => roofCounts.set(mat, roofCounts.get(mat) + 1));
    globalThis.__beforeLeaseRelease = () => {
      if (name === 'layer_leases') check('NEU building clones disposed before lease release', [...roofCounts.values()].every(n => n === 1));
    };
    unmountShell(tile); unmountShell(tile);
    globalThis.__beforeLeaseRelease = undefined;
    check(`NEU ${name} unmountShell releases building and all other leases`, [...counts.values()].every(n => n === 0));
  }
  // NEU hand-derived: failed mount => 0; failed swap => full=1, low=0,
  // old object still attached. A reversal likewise retains full=1, low=0.
  for (const phase of ['mount', 'mount_place', 'swap', 'swap_place', 'swap_attach', 'tier_reversal']) {
    globalThis.__leaseCounts = new Map();
    const tile = mkTile(), p = fixture();
    p.models = [p.models.find(m => m.id === 'outprop')];
    if (!phase.startsWith('mount')) await mountShell(tile, p);
    const rec = tile.placedModels?.[0], old = rec?.object;
    if (phase === 'tier_reversal') {
      const waiting = [];
      globalThis.__smokeLoad = () => new Promise(resolve => waiting.push(() => resolve(raw)));
      const pending = c.setSceneModelTier(tile, 'interior', 'low');
      let done = false;
      const duplicate = c.setSceneModelTier(tile, 'interior', 'low').then(() => { done = true; });
      for (let i = 0; i < 10; i++) await Promise.resolve();
      eq('NEU pending wish waits', done, false);
      await c.setSceneModelTier(tile, 'interior', 'full');
      waiting.forEach(resolve => resolve()); await pending; await duplicate;
      globalThis.__smokeLoad = undefined;
    } else {
      const clone = raw.clone;
      raw.clone = function () {
        if (phase.endsWith('_place')) {
          const obj = clone.call(this, true);
          obj.updateMatrixWorld = () => { throw new Error('NEU injected placement failure'); };
          return obj;
        }
        if (phase === 'swap_attach') return clone.call(this, true);
        throw new Error('NEU injected clone failure');
      };
      const parent = rec?.parent, add = parent?.add;
      if (phase === 'swap_attach') parent.add = function (obj) {
        add.call(this, obj); throw new Error('NEU injected attach failure');
      };
      let failed = false;
      try { await (phase.startsWith('mount') ? mountShell(tile, p) : c.setSceneModelTier(tile, 'interior', 'low')); }
      catch (error) { failed = error.message.includes('NEU injected'); }
      finally { raw.clone = clone; if (parent) parent.add = add; }
      check(`NEU ${phase}_throws rejects`, failed);
    }
    eq(`NEU ${phase} new lease released`, globalThis.__leaseCounts.get(phase.startsWith('mount') ? '/full.glb' : '/low.glb'), 0);
    if (old) {
      check(`NEU ${phase} old attached`, rec.object === old && !!old.parent);
      eq(`NEU ${phase} old lease held`, globalThis.__leaseCounts.get('/full.glb'), 1);
    }
    unmountShell(tile);
  }
  // NEU hand-derived: A waits for its building; B replaces A and installs
  // its building. A's stale completion owes only its lease, never B's clones.
  {
    globalThis.__leaseCounts = new Map();
    const tile = mkTile(), a = fixture(), b = fixture();
    a.models = [{ ...a.models[0], variants: { full: '/building-a.glb' } }];
    b.models = [{ ...b.models[0], variants: { full: '/building-b.glb' } }];
    let resolveA;
    const started = new Promise(resolve => {
      globalThis.__smokeLoad = url => url === '/building-a.glb'
        ? new Promise(done => { resolveA = done; resolve(); }) : raw;
    });
    try {
      const pendingA = mountShell(tile, a);
      await started;
      await mountShell(tile, b);
      const buildingB = tile.serverModel, matsB = [...tile.roofMats];
      const w = watcher();
      for (const mat of matsB) w.watch(mat);
      check('NEU stale_building B has roof materials', matsB.length > 0);
      resolveA(raw);
      await pendingA;
      check('NEU stale_building B remains attached', tile.serverModel === buildingB && buildingB.parent === tile.group);
      check('NEU stale_building B roof ledger retained', matsB.every(mat => tile.roofMats.includes(mat)));
      for (const mat of matsB) eq('NEU stale_building B material not disposed', w.hits(mat), 0);
      eq('NEU stale_building A lease released', globalThis.__leaseCounts.get('/building-a.glb'), 0);
      eq('NEU stale_building B lease held', globalThis.__leaseCounts.get('/building-b.glb'), 1);
    } finally {
      globalThis.__smokeLoad = undefined;
      unmountShell(tile);
    }
  }
  const mainSource = await readFile(join(ROOT, 'client3d/src/main.ts'), 'utf8');
  const body = mainSource.slice(mainSource.indexOf('function buildDoorMarks'), mainSource.indexOf('function buildBoundaryMarks'));
  check('buildDoorMarks preserves boundary marks', !body.includes('dropBoundaryMarks('));
}

async function main() {
  const fresh = await loadClient();
  await layerCases(fresh);

  // ── [1] the plain unmount ────────────────────────────────────────────────
  const one = await run(fresh, '[1] unmount frees what the mount built',
                        ({ tile, unmountShell }) => { unmountShell(tile); });
  report('unmount', one, 1);
  check('the building model is unhooked from the tile',
        !one.tile.serverModel
          && !one.tile.group.children.some((c) => c.name === 'building'),
        String(one.tile.group.children.map((c) => c.name)));
  eq('the placement ledger is gone', one.tile.placedModels, undefined);

  // ── [2] remount on a changed signature ───────────────────────────────────
  const two = await run(fresh, '[2] a remount frees the mount it replaces',
                        async ({ tile, mountShell, mountDetail }) => {
                          await mountShell(tile, payload('sig-b'));
                          await mountDetail(tile, payload('sig-b'));
                          return true;
                        });
  report('remount', two, 1);
  const standing = ownedOf(two.tile, two.shared);
  check('the new mount stands', countOwned(standing) >= 10,
        `${countOwned(standing)} resources`);
  const overlap = [...standing.geometries].filter((g) => two.owned.geometries.has(g));
  eq('and shares no geometry with the mount it replaced', overlap.length, 0);
  // Every texture of a mount is a CLONE of a library image. Freeing all the
  // clones of the first mount must not take the image with them: the second
  // mount's clones come out of the very same `Texture.source` objects.
  const freshSources = new Set([...standing.textures].map((t) => t.source));
  check('the shared surface library survives its clones',
        freshSources.size > 0 && [...freshSources].every((s) => two.sources.has(s)),
        `${freshSources.size} source(s), ${two.sources.size} before`);

  // ── [3] the drop path, in main.ts' order ─────────────────────────────────
  const three = await run(fresh, '[3] the drop path frees each buffer once',
                          ({ tile, unmountShell }) => dropPath(tile, unmountShell));
  report('drop', three, 1);

  // ── [4] the far-view shell shares its geometry with the plates ───────────
  const shell = await run(fresh, '[4] the far shell shares geometry, owns its materials',
                          ({ tile, unmountShell }) => { unmountShell(tile); },
                          shellPayload);
  report('shell unmount', shell, 1);
  check('the shell is gone with the scene', !shell.tile.shell,
        String(shell.tile.shell));

  // ── [5] RED counter-probe against the pre-fix source ─────────────────────
  const old = await loadClient(PRE_FIX_REV);
  const red = await run(old, '[5] RED: the pre-fix unmount frees nothing of it',
                        ({ tile, unmountShell }) => { unmountShell(tile); });
  report('pre-fix unmount', red, 0);

  console.log(`\n${failed ? 'FAILED' : 'PASSED'}: ${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

await main();
