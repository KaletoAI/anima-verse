/** HUD boundary: forbidden runtime imports, JSON snapshots and keyboard priority. */
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { transformSync } from 'esbuild';
const violations = [];
async function scan(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = `${dir}/${entry.name}`;
    if (entry.isDirectory()) { await scan(file); continue; }
    if (!/\.[cm]?[jt]sx?$/.test(file)) continue;
    const source = await readFile(file, 'utf8');
    for (const match of source.matchAll(/^import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]/gm)) {
      const [, clause, path] = match;
      if (/^type\b/.test(clause.trim()) || /^\{\s*type\s+[^}]+\}$/.test(clause.trim()) && !clause.includes(',')) continue;
      if (/^\.\.\/(?:main$|scene\/|game\/(?:audio|boot|embody)$)/.test(path)) {
        violations.push(`${file}:${source.slice(0, match.index).split('\n').length}: ${path}`);
      }
    }
  }
}
await scan('client3d/src/hud');
assert.deepEqual(violations, [], `Forbidden HUD imports:\n${violations.join('\n')}`);
const code = transformSync(await readFile('client3d/src/hud/bus.ts', 'utf8'), { loader: 'ts', format: 'esm' }).code;
const bus = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const game = { ...bus.getGameState(), mode: 'embodied', selected: { char: { name: 'Ada', location_id: 'home', pos: { x: 1, z: 2 }, pos_origin: { session: 'test', seq: 1 } }, isAvatar: true },
  talkTarget: { name: 'Bob', dist: 1 }, movementLocked: true, partyLeader: 'Bob', groundRoomId: 'ground',
  floorRoomIds: { 0: 'hall' }, lockedRooms: { vault: 'Locked' }, lockedLoc: 'home', lockedLocations: { away: 'Locked' },
  elevator: { dist: 1, levels: [0, 1], current: 0 }, elevatorOpen: true,
  stairs: { dist: 1, dir: 'up', dest: { level: 1, x: 1, y: 3, z: 2 } }, enterOffer: { name: 'away', dist: 2 } };
const ui = { menuOpen: true, typing: false, overlayOpen: false, hitRects: [{ x: 1, y: 2, w: 3, h: 4 }, { x: 5, y: 6, w: 7, h: 8 }] };
const boot = { state: { percent: 0, label: 'world', note: null, stages: [] }, report: { stages: { world: 1, scenes: 2, tiles: 3, visible: 4, figures: 5, arrival: 6 }, phases: { 'clip:download': 1, 'clip:parse': 2, 'clip:fit': 3, 'model:download': 4, 'model:build': 5, 'scene:fetch': 6, 'arrival:mount': 7, 'ground:fetch': 8, 'ground:build': 9 }, longTasks: null, longTaskMaxByPhase: {}, afterVisible: null } };
for (const [set, get, value] of [[bus.setGameState, bus.getGameState, game], [bus.setHudUiState, bus.getHudUiState, ui], [bus.setBoot, bus.getBoot, boot]]) {
  set(value);
  assert.deepEqual(get(), value);
  assert.deepEqual(JSON.parse(JSON.stringify(get())), get());
}
for (const [patch, elevator, expected] of [
  [{ typing: true }, true, 'ignore'], [{ overlayOpen: true }, false, 'ignore'],
  [{}, true, 'elevator'], [{}, false, 'menu'], [{ menuOpen: false }, false, 'mode'],
]) assert.equal(bus.escTarget({ ...ui, ...patch }, elevator), expected);
for (const typing of [false, true]) for (const overlayOpen of [false, true]) {
  assert.equal(bus.keyForScene({ ...ui, typing, overlayOpen }), !typing && !overlayOpen);
}
for (const [subscribe, set, get] of [[bus.subscribeBoot, bus.setBoot, bus.getBoot], [bus.subscribeHudUiState, bus.setHudUiState, bus.getHudUiState]]) {
  let calls = 0;
  const off = subscribe(() => calls++);
  const previous = get();
  set({ ...previous });
  assert.equal(calls, 1);
  assert.notEqual(get(), previous);
  off(); set({ ...previous }); assert.equal(calls, 1);
}
console.log('hud boundary: PASS (imports, JSON snapshots, subscriptions, Esc priority, keyboard guards)');
