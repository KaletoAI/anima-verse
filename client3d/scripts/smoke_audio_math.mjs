/**
 * Task 58 / E8-T1. Canonical hand derivations for audio.json.
 * Run: node client3d/scripts/smoke_audio_math.mjs (no browser/server/audio device).
 * P3-R31: transform the ORIGINAL prefs, soundtrack, voiceover and audio code;
 * never copy their algorithms or edit client3d/src or packages.
 *
 * [1] Prefs: key av3d.audio.v1; defaults master=.8, music=.5, ambient=.6,
 * tts=1, musicOn=ambientOn=true, ttsOn=auto. Missing/invalid/non-object JSON
 * gives all defaults. Only finite NUMBERS are volumes: strings, null, bools,
 * objects and 1e400 fall back independently; negative -> 0, >1 -> 1, 0 stays.
 * Switches require booleans; ttsOn accepts exactly auto/on/off. Save emits the
 * seven fields in that order without spaces; round trip preserves each field.
 *
 * [2] Manifest: null/scalars/missing fields -> empty lists/object. Filter lists
 * to nonempty strings; preserve whitespace strings, duplicates and key case.
 * Drop ambient keys with no remaining files; an ambient array is not a map.
 * [3] Night hysteresis: >.8 -> night; <.2 -> day; EXACT .2/.8 and NaN hold.
 * Dusk [0,.2,.5,.8,.81,.5] from day -> [F,F,F,F,T,T]. Dawn
 * [.8,.21,.2,.19,.21,.19] from night -> [T,T,T,F,F,F]. Infinity goes night,
 * -Infinity day. [4] Pick only the requested music bucket; no fallback.
 * Ambient exact key wins before case-insensitive lookup; unknown/empty -> [].
 * [5] Terrain uses avatar in embodied, camera in overview. Missing chosen
 * point means silence, never the other point. Trim/lowercase the lookup.
 * [6] Hold starts {applied:'',pending:'',since:0,started:false}. Initial empty
 * stays there; first grass at 1000 applies immediately. Grass at 2000 resets
 * since=2000. Water at 3000 starts pending; at 7999 elapsed=4999, still grass;
 * at 8000 elapsed=5000 -> water. A return to applied cancels the pending hold.
 * Silence after grass starts at 2000, applies at 7000. Water after silence at
 * 8000 must wait to 13000 (started stays true). A different pending candidate
 * resets since. Custom hold=100 applies at 200 after candidate at 100.
 *
 * [7] Equal-power targets at fractions i/8: sin(i*pi/16) ascending =
 * 0, .19509032201612825, .3826834323650898, .5555702330196022,
 * .7071067811865476, .8314696123025452, .9238795325112867,
 * .9807852804032304, 1. Descending cos is the reverse sequence (last ~0).
 * With t0=10,dur=8 the knots are at 10..18. At 10.5 the LINEAR segment gives
 * .5*sin(pi/16)=.09754516100806413, NOT sin(pi/32)=.0980171403295606.
 * At 13.5: (.5555702330196022+.7071067811865476)/2=.6313385071030749;
 * descending (.8314696123025452+.7071067811865476)/2=.7692881967445464.
 * Outside the scheduled interval the endpoint holds. Shift/scale: t0=2,dur=4,
 * t=2.25 is again halfway along segment 1, and t=4 is sqrt(1/2).
 *
 * [8] Playlist: fade=min(crossfade,duration/3), begin=max(requested,now),
 * seam=begin+duration-fade; wake=max(0,seam-6-now). All values seconds.
 * duration 9/crossfade 4/begin 10 -> fade 3,seam 16,wake 0 at now=10.
 * 12/4 -> 4,18,2; 18/4 -> 4,24,8; 9/3 -> 3,16,0.
 * Requested 20,now 10,9/4 -> begin20,fade3,seam26,wake10.
 * Requested 5,now10,9/4 -> begin10,fade3,seam16,wake0.
 * 3/4 -> fade1,seam12,wake0; 0/4 -> fade0,seam10,wake0.
 * 9/0 and 9/-2 (play clamps negative crossfade) -> fade0,seam19,wake3.
 * Default 18/3 -> fade3,seam25,wake9.
 *
 * [9] Stop is LINEAR, end=now+max(.05,fadeS). For gain .8,now10,fade4:
 * before/at10=.8, at12=.4, at14/after=0, end14. Fade0/-1 floors at .05:
 * gain1,now2,t2.025 -> .5,end2.05. Gain0 stays0 even on a long stop.
 * [10] Volume is a LINEAR .05-s ramp from current gain to clamp(target,0,1).
 * .8 -> .2 at now2: t<=2=.8, t2.0125=.65, t2.025=.5, t>=2.05=.2.
 * 0->2 clamps to1, halfway=.5; 1->-2 clamps to0, halfway=.5.
 * Each of master/music/ambient/tts follows the same ramp; other buses hold.
 *
 * [11] Shuffle: FNV-1a hashes ''=2166136261, 'a'=3826002220. For each draw,
 * h=imul(h^(h>>>15),2246822519); h=imul(h^(h>>>13),3266489917);
 * h=(h^(h>>>16))>>>0. Independently worked uint32 draws (not engine output):
 * '' -> 2019044825,2827497437,2156573836;
 * 'a' -> 2713139746,2529889813,2918604097.
 * First two multiply intermediates for '' are 760624676,2019054977,
 * then 3697722831,2827519829, then 3173430091,2156540934.
 * For 'a': 3034756908,2713164693; 4232862292,2529925342;
 * 1077731301,2918641847 (all arithmetic modulo 2^32 before final xor).
 * Divide by 2^32; floor(draw*(i+1)/2^32) at i=3,2,1:
 * '' -> j=1,1,1: ABCD -> ADCB -> ACDB -> ACDB.
 * 'a' -> j=2,1,1: ABCD -> ABDC -> ADBC -> ADBC.
 * With ABC and seed 'a': j=1,1 -> ACB -> ACB. AB stays AB (j=1);
 * with empty seed AB -> BA (j=0). Duplicates aabc/empty seed:
 * aabc -> acba -> abca -> abca (indices 0,2,3,1 of the original).
 * Empty/single lists stay unchanged; duplicates remain distinct entries.
 *
 * [12] Browser queue: voiceover.ts MAX_PENDING=3, enqueueSpeech appends then
 * keeps the LAST three. [a,b,c]+[d] -> [b,c,d]; [a]+[b,c,d,e] -> [c,d,e].
 * FIFO survives below cap; empty incoming still trims an oversized queue.
 * This is the WAITING queue (not the active line). AudioEngine.speak itself
 * has an unbounded promise chain: P3-R30 applies the HUD's rule natively.
 * Adapters use strings as opaque queue entries; no selection/VO port here.
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
const P = moduleOf(read('client3d/src/game/prefs.ts'));
const S = moduleOf(read('client3d/src/game/soundtrack.ts'));
const V = moduleOf(read('client3d/src/game/voiceover.ts'));

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
