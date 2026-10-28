/** Test adapters only: production arithmetic, explicit callback data and fresh state per case. */
import { build } from 'esbuild';
import { loadVectors, near, resolveArgs } from '../../shared/test-vectors/vectors.mjs';

const game = ['stairs', 'walk', 'clickmove', 'proximity', 'roomwalk', 'elevator', 'collide',
  'locks', 'ground', 'polygon', 'enterLocation', 'placement', 'offers', 'posEcho', 'readiness'];
const entry = game.map(n => `export * as ${n} from ${JSON.stringify(new URL(`../src/game/${n}.ts`, import.meta.url).pathname)};`);
entry.push(...['cameraMath', 'cameraFraming'].map(n =>
  `export * as ${n} from ${JSON.stringify(new URL(`../src/scene/${n}.ts`, import.meta.url).pathname)};`));
entry.push(`export * as bus from ${JSON.stringify(new URL('../src/hud/bus.ts', import.meta.url).pathname)};`);
const built = await build({ stdin: { contents: entry.join('\n'), resolveDir: new URL('../../', import.meta.url).pathname, loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', write: false });
const modules = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const m = Object.assign({}, ...Object.values(modules));
const field = (value, path) => path.reduce((v, k) => k === '$ids' ? v.map(r => r.id)
  : k === '$roomIds' ? v.map(r => r.roomId) : k === '$length' ? Math.hypot(v.x, v.z)
  : v?.[k], value);
export const blockedFrom = (data = {}) => (x, z) => {
  const inRect = ([a, b, c, d]) => data.inclusive
    ? x >= a && z >= b && x <= c && z <= d : x > a && z > b && x < c && z < d;
  const rock = (data.rects ?? []).some(inRect) || (data.discs ?? []).some(([a,b,r]) => Math.hypot(x-a,z-b) < r);
  if (!data.footprints) return rock;
  const inside = data.footprints.some(([a,b,c,d]) => x >= a && z >= b && x <= c && z <= d);
  return m.terrainBlocks(!rock, inside);
};
const cancelIn = v => v === '$NO_CANCEL' ? m.NO_CANCEL : v;
const cancelOut = v => v === m.NO_CANCEL ? '$NO_CANCEL' : v;
export const embodyDispatch = { ...m,
  polygonDistanceInfinite: (...args) => m.polygonDistance(...args) === Infinity,
  constant: name => {
    if (!(name in m) || typeof m[name] === 'function') throw new Error(`unknown constant ${name}`);
    return m[name];
  },
  walkDir: (keys, yaw) => m.walkDir(new Set(keys), yaw),
  slideBlocked: (from, to, blocked) => m.slideBlocked(from, to, blockedFrom(blocked)),
  planClickWalk: (from, to, blocked) => m.planClickWalk(from, to, blockedFrom(blocked)),
  talkName: (avatar, others) => m.talkTargetNear(avatar, others)?.name ?? null,
  groundStoreyFloors: (floors, levels) => m.groundStoreyFloors(floors, id => levels[id]),
  roomWalkCandidatesValue: (data) => m.roomWalkCandidates({ ...data,
    insideRect: id => data.insideRooms.includes(id),
    insideLevelOutline: lv => data.insideLevels.includes(lv),
    floorIdOf: lv => data.floorIds[lv] ?? '',
  }),
  roomSwitchSequence: (current, rooms, level, steps, holdS = 1.5, locks = null) => {
    let state = m.idleRoomWalk();
    const results = steps.map(([pos, nowMs]) => {
      const r = m.nearestRoomSwitch(current, pos, m.unlockedRooms(rooms, locks, current), level, state, nowMs, holdS);
      state = r.state;
      return r.next;
    });
    return { next: results, state };
  },
  avatarDriver: (state, event, cancelled) => {
    const r = m.avatarDriver(state, event, cancelIn(cancelled));
    return { ...r, cancelled: cancelOut(r.cancelled) };
  },
  suppressedJourney: (state, cancelled, journey) => m.suppressedJourney(state, cancelIn(cancelled), journey),
  echoSequence: (sent, session, origins, cap = m.ECHO_RING_CAP) => {
    const ring = [];
    for (const seq of sent) m.pushSeq(ring, seq, cap);
    return { ring, own: origins.map(origin => m.isOwnEcho(ring, session, origin)) };
  },
  holdForSequence: steps => {
    const state = { approachPin: null, pendingSnap: null }, calls = [];
    const frames = steps.map(({ id, ready, x = 0, z = 0, clear = false }) => {
      const deps = { placeAt: () => id, isReady: () => ready,
        pin: (key, owner) => calls.push(['pin', key, owner]),
        release: (key, owner) => calls.push(['release', key, owner]) };
      const held = clear ? (m.clearApproach(deps, state), false) : m.holdFor(deps, state, x, z);
      return { held, state: structuredClone(state) };
    });
    return { frames, calls };
  },
  firstPersonZoomSequence: steps => {
    const zoom = new m.FirstPersonZoom();
    return steps.map(([distance, enabled, dt]) => zoom.update(distance, enabled, dt));
  },
};
// Projection is explicit test data; it never changes the production result.
for (const [name, fn] of Object.entries({ ...embodyDispatch })) {
  if (typeof fn === 'function' && !Object.hasOwn(embodyDispatch, `${name}Value`)) embodyDispatch[`${name}Value`] = (args, path) => field(fn(...args), path);
}

/** Preserve each source smoke's check accounting while reading its migrated cases. */
export function vectorChecks(check, names) {
  const cases = names.flatMap(name => {
    const file = loadVectors(name);
    return file.cases.map(c => ({ ...c, fixtures: file.fixtures }));
  });
  return label => {
    const c = cases.find(c => c.label === label);
    if (!c) throw new Error(`missing migrated case ${label}`);
    const fn = embodyDispatch[c.fn];
    if (typeof fn !== 'function') throw new Error(`unknown vector function ${c.fn}`);
    const args = resolveArgs(c.args, c.fixtures);
    if (c.expect?.$throws === true) {
      let threw = false;
      try { fn(...args); } catch { threw = true; }
      check(label, threw, true);
    } else {
      const result = near(c.expect, fn(...args), c.eps);
      if (!result.ok) console.error(result.diff);
      check(label, result.ok, true);
    }
  };
}
