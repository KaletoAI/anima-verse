#!/usr/bin/env node
/**
 * Smoke check for the GPU-RESOURCE LIFETIME of a mounted LOCATION SCENE in the
 * 3D client (review finding UI-2): what `mountScene` builds itself, what it
 * only borrows, and what `unmountScene` has to hand back when the scene is
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
 * [1] unmount → every owned resource 1, every shared resource 0, and the
 *     building model no longer hangs on the tile.
 * [2] remount with a changed signature (`mountScene` unmounts first) → the
 *     first mount's resources 1, the second mount's still 0 while it stands.
 * [3] the DROP path, in the order `main.ts` uses it: `unmountScene` first, then
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
 *     out of `git show HEAD:…`, bundled through an esbuild onLoad plugin.
 *     There the owned resources must come out at 0 — that is the leak.
 */
import { execFileSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
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
      `export { mountScene, unmountScene } from '${src}/sceneRecipe';`,
      `export { buildTile, setSurfaceTextures, preloadSurfaceTexture } from '${src}/tiles';`,
    ].join('\n');
    const stubs = {
      name: 'smoke-stubs',
      setup(build) {
        // The GLB loader is the ONE thing this check must own: `loadGlb`
        // caches its templates, and a template is what must survive an unmount.
        build.onLoad({ filter: /scene[/\\]propAssets\.ts$/ }, () => ({
          contents: 'export function setPropLoadFocus() {}\n'
            + 'export function loadGlb(url) {\n'
            + '  return Promise.resolve(globalThis.__smokeTemplates?.get(url) ?? null);\n'
            + '}\n',
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

/** One shared GLB template, exactly as `loadGlb` caches it. */
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
function dropPath(tile, unmountScene) {
  const cached = new Set();
  for (const rec of tile.placedModels ?? []) if (rec.object) cached.add(rec.object);
  unmountScene(tile);
  const free = (o) => {
    if (cached.has(o)) return;
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
  const { mountScene, unmountScene, buildTile, setSurfaceTextures,
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
  const tile = buildTile(LOCATION);
  scene.add(tile.group);                    // a tile without a parent is "stale"

  await mountScene(tile, make('sig-a'));
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

  const second = await teardown({ tile, mountScene, unmountScene });

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

async function main() {
  const fresh = await loadClient();

  // ── [1] the plain unmount ────────────────────────────────────────────────
  const one = await run(fresh, '[1] unmount frees what the mount built',
                        ({ tile, unmountScene }) => { unmountScene(tile); });
  report('unmount', one, 1);
  check('the building model is unhooked from the tile',
        !one.tile.serverModel
          && !one.tile.group.children.some((c) => c.name === 'building'),
        String(one.tile.group.children.map((c) => c.name)));
  eq('the placement ledger is gone', one.tile.placedModels, undefined);

  // ── [2] remount on a changed signature ───────────────────────────────────
  const two = await run(fresh, '[2] a remount frees the mount it replaces',
                        async ({ tile, mountScene }) => {
                          await mountScene(tile, payload('sig-b'));
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
                          ({ tile, unmountScene }) => dropPath(tile, unmountScene));
  report('drop', three, 1);

  // ── [4] the far-view shell shares its geometry with the plates ───────────
  const shell = await run(fresh, '[4] the far shell shares geometry, owns its materials',
                          ({ tile, unmountScene }) => { unmountScene(tile); },
                          shellPayload);
  report('shell unmount', shell, 1);
  check('the shell is gone with the scene', !shell.tile.shell,
        String(shell.tile.shell));

  // ── [5] RED counter-probe against the pre-fix source ─────────────────────
  const old = await loadClient('HEAD');
  const red = await run(old, '[5] RED: the pre-fix unmount frees nothing of it',
                        ({ tile, unmountScene }) => { unmountScene(tile); });
  report('pre-fix unmount', red, 0);

  console.log(`\n${failed ? 'FAILED' : 'PASSED'}: ${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

await main();
