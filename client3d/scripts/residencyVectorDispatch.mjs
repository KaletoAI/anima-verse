/** Test-only op interpreter; decisions come from the production driver/library. */
import { readFile } from 'node:fs/promises';
import { build, transformSync } from 'esbuild';
export async function load(path) {
  const r = await build({ entryPoints: [path], bundle: true, write: false, format: 'esm', platform: 'node' });
  return import(`data:text/javascript;base64,${Buffer.from(r.outputFiles[0].text).toString('base64')}`);
}
export const { createResidencyDriver } = await load('client3d/src/game/residency.ts');
export const { createFocusQueue } = await load('client3d/src/game/focusQueue.ts');
export const flush = async () => { for (let i = 0; i < 100; i++) await Promise.resolve(); };
export const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
};
const recipe = await readFile('client3d/src/scene/sceneRecipe.ts', 'utf8');
const librarySource = recipe.slice(recipe.indexOf('export class SceneLibrary'), recipe.indexOf('// ── Verify'));
export const makeLibrary = fetch => new Function('getLocationScene', 'createFocusQueue',
  transformSync(librarySource.replace('export class', 'class') + '\nreturn SceneLibrary;',
    { loader: 'ts', format: 'cjs' }).code)(fetch, createFocusQueue);

// Bound waits make a broken lifecycle fail with a diagnostic instead of hanging.
async function bounded(promise) {
  let timer;
  try {
    await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('scenario did not settle')), 1000);
    })]);
  } finally { clearTimeout(timer); }
}

export async function residencyScenario(kind, steps) {
  const ids = new Set(), gates = new Map(), results = {}, handles = new Map();
  const calls = [], live = new Map(), wait = [], timers = [], events = [], pending = [];
  let active = 0, max = 0, rollback = 0, fail = false, resolved = 0;
  const driver = createResidencyDriver({
    async up(id, version, from, alive) {
      calls.push(['up', id, version, from]);
      active++; max = Math.max(max, active);
      const gate = wait.shift();
      if (gate) await gate.promise;
      active--;
      if (!alive()) { rollback++; return 'aborted'; }
      if (fail) { fail = false; return 'failed'; }
      live.set(id, version);
      return 'ok';
    },
    down(id, version, from) {
      calls.push(['down', id, version, from]);
      if (from === 'far') live.delete(id);
    },
  }, createFocusQueue({ max: 2 }), {
    setTimeout(fn, ms) { const timer = { fn, ms }; timers.push(timer); return timer; },
    clearTimeout(timer) { const i = timers.indexOf(timer); if (i >= 0) timers.splice(i, 1); },
  });
  const Library = makeLibrary(id => {
    const gate = deferred(); pending.push({ id, ...gate }); return gate.promise;
  });
  const lib = new Library(); lib.onScene = id => events.push(id);
  const snapshots = [];
  for (const ops of steps) {
    for (const [op, ...a] of ops) {
      switch (op) {
        case 'gate': { const gate = deferred(); gates.set(a[0], gate); wait.push(gate); break; }
        case 'release': gates.get(a[0]).resolve(); break;
        case 'want': ids.add(a[0]); driver.want(a[0], a[1], a[2], () => a[3] ?? 0); break;
        case 'rebuild': driver.rebuild(...a); break;
        case 'drop': driver.drop(...a); break;
        case 'fail': fail = true; break;
        case 'flush': await flush(); break;
        case 'settled': await bounded(driver.settled(a[0])); break;
        case 'watch': driver.settled(a[0]).then(() => resolved++); break;
        case 'retry': {
          const timer = timers.shift();
          if (!timer) throw Error('no retry timer');
          timer.fn(); break;
        }
        case 'sweep': {
          a[1].forEach(id => ids.add(id));
          handles.set(a[0], lib.sweep(a[1])); break;
        }
        case 'request': {
          ids.add(a[1]); const p = lib.request(a[1]); handles.set(a[0], p);
          p.then(scene => { results[a[0]] = scene?.signature ?? null; }); break;
        }
        case 'forget': lib.forget(a[0]); break;
        case 'reply': pending[a[0]].resolve({ signature: a[1] }); break;
        case 'await': await bounded(handles.get(a[0])); break;
        case 'samePromise': results.samePromise = handles.get(a[0]) === handles.get(a[1]); break;
        default: throw Error(`unknown residency operation ${op}`);
      }
    }
    // No implicit flush: a snapshot can test synchronous invalidation/hasJob.
    if (kind === 'driver') snapshots.push({
      rings: Object.fromEntries([...ids].map(id => [id, driver.ring(id)])),
      targets: Object.fromEntries([...ids].map(id => [id, driver.target(id)])),
      jobs: Object.fromEntries([...ids].map(id => [id, driver.hasJob(id)])),
      calls: calls.splice(0), live: [...live], max, rollback, timers: timers.map(t => t.ms), resolved,
    });
    else if (kind === 'library') snapshots.push({
      pending: pending.map(p => p.id), events: [...events], results: { ...results },
      cache: Object.fromEntries([...ids].map(id => [id, lib.get(id)?.signature ?? null])),
    });
    else throw Error(`unknown scenario kind ${kind}`);
  }
  return snapshots;
}
