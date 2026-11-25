/**
 * Derivation moved to native/tests/Derivations/audio_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_audio_math.mjs   (no browser/server/audio device)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { transformSync } from 'esbuild';
import { loadVectors, resolveArgs, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../..');
const read = path => readFileSync(join(ROOT, path), 'utf8');
function moduleOf(source, globals = {}) {
  const module = { exports: {} };
  vm.runInNewContext(transformSync(source, { loader: 'ts', format: 'cjs' }).code,
    { module, exports: module.exports, console, ...globals }, { timeout: 5000 });
  return module.exports;
}
function extractFunction(source, name) {
  const start = source.indexOf(`export function ${name}(`);
  assert(start >= 0, `missing production function ${name}`);
  const end = source.indexOf('\n}', start);
  assert(end > start, `missing end of production function ${name}`);
  return source.slice(start, end + 2);
}
const scatter = read('packages/scene-render/src/scatter.ts');
const { seededRandom } = moduleOf(extractFunction(scatter, 'scatterSeedHash')
  + '\n' + extractFunction(scatter, 'seededRandom'));
const P = moduleOf(read('hud/src/game/prefs.ts'));
const S = moduleOf(read('hud/src/game/soundtrack.ts'));
const V = moduleOf(read('hud/src/game/voiceover.ts'));

// AudioParam records Web Audio's set/ramp/cancel boundary. Sampling interprets
// those events linearly; it contains no audio production formula or constants.
class Param {
  constructor(value = 1) { this.value = value; this.events = []; this.cancelled = []; }
  setValueAtTime(value, time) { this.events.push({ kind: 'set', value, time }); }
  linearRampToValueAtTime(value, time) { this.events.push({ kind: 'ramp', value, time }); }
  cancelScheduledValues(time) {
    this.cancelled.push(time);
    this.events = this.events.filter(e => e.time < time);
  }
  at(time) {
    let prev = this.events[0];
    if (!prev || time <= prev.time) return prev?.value ?? this.value;
    for (const event of this.events.slice(1)) {
      if (time < event.time) return event.kind === 'ramp'
        ? prev.value + (event.value - prev.value) * (time - prev.time) / (event.time - prev.time)
        : prev.value;
      prev = event;
    }
    return prev.value;
  }
}
class Context {
  currentTime = 0;
  gains = [];
  sources = [];
  createGain() {
    const node = { gain: new Param(), connect() {}, disconnect() {} };
    this.gains.push(node);
    return node;
  }
  createBufferSource() {
    const node = { connect() {}, start(time) { this.begin = time; }, stop(time) { this.end = time; } };
    this.sources.push(node);
    return node;
  }
}
const timers = [];
const A = moduleOf(read('client3d/src/game/audio.ts')
  .replace(/^import \{ seededRandom \} from '..\/scene\/textures';$/m, '')
  // Observe locals AFTER their production expressions. In particular the
  // zero-fade path has no gain events from which to recover fade/seam.
  .replace(/(const seam = [^\n]+;)/, '$1\n this.ctx.schedule = { begin, fade, seam };')
  + '\nexport { Playlist, equalPowerFade, shuffle };', {
  seededRandom, window: { AudioContext: Context },
  setTimeout(callback, ms) { timers.push({ callback, ms }); return timers.length; },
  clearTimeout() {},
});

const dispatch = {
  audioPrefsConstants: () => ({ key: P.PREFS_KEY, defaults: P.DEFAULT_PREFS }),
  loadAudioPrefs: P.loadPrefs,
  saveAudioPrefs: P.savePrefs,
  audioPrefsRoundTrip: p => P.loadPrefs(P.savePrefs(p)),
  soundtrackConstants: () => ({ nightOn: S.NIGHT_ON, nightOff: S.NIGHT_OFF, holdMs: S.AMBIENT_HOLD_MS }),
  readManifest: S.readManifest,
  nightForMusic: S.nightForMusic,
  nightForMusicSeq: (start, factors) => factors.map(factor => (start = S.nightForMusic(start, factor))),
  pickMusic: S.pickMusic,
  pickAmbient: S.pickAmbient,
  ambientTerrainFor: (mode, avatar, camera, rows) => S.ambientTerrainFor(mode, avatar, camera,
    at => rows.find(([x, z]) => x === at.x && z === at.z)?.[2] ?? ''),
  terrainSwitchSeq: (steps, holdMs) => {
    let state = S.newTerrainSwitch();
    return steps.map(([candidate, nowMs]) => (state = S.terrainSwitch(state, candidate, nowMs, holdMs)));
  },
  equalPowerGainAt: (t0, dur, up, time) => {
    const param = new Param();
    A.equalPowerFade(param, t0, dur, up);
    assert.equal(param.events.length, 9, 'initial set plus eight linear ramps');
    return param.at(time);
  },
  playlistSchedule: async (requested, now, duration, crossfadeS) => {
    const ctx = new Context();
    ctx.currentTime = now;
    const playlist = new A.Playlist(ctx, {}, async () => ({ duration }));
    playlist.play(['fixture-track'], { crossfadeS });
    // Let play configure the real defaults/clamping. Its initial track awaits
    // a cross-realm Promise; one local microtask is not a completion barrier.
    await new Promise(setImmediate);
    ctx.gains = [];
    ctx.sources = [];
    const timerCount = timers.length;
    // Probe the real private method at an explicit requested audio-clock time.
    await playlist.startTrack(requested, playlist.generation);
    assert.equal(ctx.sources[0].begin, ctx.schedule.begin);
    assert.equal(timers.length, timerCount + 1);
    return { ...ctx.schedule, wakeInS: timers.at(-1).ms / 1000 };
  },
  stopRamp: (g0, now, fadeS, time) => {
    const ctx = new Context();
    ctx.currentTime = now;
    const gain = ctx.createGain();
    gain.gain.value = g0;
    const src = ctx.createBufferSource();
    const playlist = new A.Playlist(ctx, {}, async () => { throw Error('unused decoder'); });
    playlist.live = [{ src, gain }];
    playlist.stop(fadeS);
    assert.deepEqual(gain.gain.cancelled, [now]);
    return { gain: gain.gain.at(time), end: src.end };
  },
  volumeRamp: (g0, target, now, time, bus = 'master') => {
    const engine = new A.AudioEngine();
    engine.ctx.currentTime = now;
    const node = bus === 'master' ? engine.master : engine.buses[bus];
    node.gain.value = g0;
    engine.setVolume(bus, target);
    assert.deepEqual(node.gain.cancelled, [now]);
    for (const other of engine.ctx.gains.filter(n => n !== node)) assert.equal(other.gain.events.length, 0);
    return node.gain.at(time);
  },
  shuffle: A.shuffle,
  enqueueSpeech: V.enqueueSpeech,
};

let passed = 0;
let failed = 0;
const file = loadVectors('audio');
for (const c of file.cases) {
  assert.equal(typeof dispatch[c.fn], 'function', `unknown fn ${c.fn}`);
}
// The common runner is synchronous. Await real production operations first,
// then use its unchanged fixture/sentinel/comparison/failure semantics.
for (const c of file.cases) {
  let result;
  let error;
  try { result = await dispatch[c.fn](...resolveArgs(c.args, file.fixtures)); }
  catch (e) { error = e; }
  const run = runVectors({ ...file, cases: [c] }, { [c.fn]: () => {
    if (error) throw error;
    return result;
  } });
  passed += run.passed;
  failed += run.failed;
}

// Fixture contract is checked here as well: no extra canonical source smoke.
const fixture = join(ROOT, 'native/fixtures/audio');
const manifest = JSON.parse(readFileSync(join(fixture, 'audio_manifest.json'), 'utf8'));
const urls = JSON.parse(readFileSync(join(fixture, 'urls.json'), 'utf8'));
assert.equal(JSON.stringify(S.readManifest(manifest)), JSON.stringify(manifest));
// Native FootprintAt reads slot.Loc.Terrain from the WORLD MAP row, not from
// the separately fetched location details. Both must carry the terrain.
const world = JSON.parse(readFileSync(join(fixture, 'worldmap.json'), 'utf8'));
const details = JSON.parse(readFileSync(join(fixture, 'locations.json'), 'utf8'));
for (const loc of world.locations) {
  assert.equal(loc.terrain, details.locations.find(d => d.id === loc.id)?.terrain,
    `worldmap terrain must match location details: ${loc.id}`);
}
const terrainRows = world.locations.map(loc => [loc.pos_x, loc.pos_z, loc.terrain]);
const avatar = world.characters.find(c => c.name === world.avatar).pos;
assert.equal(dispatch.ambientTerrainFor('overview', avatar, { x: 0, z: 0 }, terrainRows), 'grass');
assert.equal(dispatch.ambientTerrainFor('embodied', avatar, { x: 0, z: 0 }, terrainRows), 'forest');
for (const url of [...manifest.music.day, ...manifest.music.night, ...Object.values(manifest.ambient).flat(),
  '/tts/tmp/fixture.wav']) {
  assert(Object.hasOwn(urls, url), `unmapped fixture URL ${url}`);
  const path = join(fixture, urls[url]);
  assert(statSync(path).size < 50000, `oversized fixture ${url}`);
  const bytes = readFileSync(path);
  if (url.endsWith('broken.mp3')) assert.equal(bytes.toString(), 'deliberately invalid audio\n');
  else if (url.endsWith('.wav')) {
    assert.equal(bytes.toString('ascii', 0, 4), 'RIFF');
    assert.equal(bytes.toString('ascii', 8, 12), 'WAVE');
  } else if (url.endsWith('.ogg')) assert.equal(bytes.toString('ascii', 0, 4), 'OggS');
  else assert.equal(bytes.toString('ascii', 0, 3), 'ID3');
}
console.log(`\n${passed} audio vectors passed, ${failed} failed; fixture manifest/terrain/URL/size/signature checks passed`);
process.exitCode = failed ? 1 : 0;
