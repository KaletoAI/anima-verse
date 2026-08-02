/**
 * The client's audio output — music, ambience and spoken lines (stage 4,
 * task 2).
 *
 * ONE `AudioContext` for the whole client, and one gain node per bus:
 *
 *     music  ──┐
 *     ambient ─┼─> master ──> destination
 *     tts    ──┘
 *
 * So "master" is a real node and not a number the callers have to multiply in:
 * a bus volume and the master volume compose in the graph, and a track that is
 * already playing follows a slider immediately. Every gain change is a short
 * ramp (`RAMP_S`) instead of an assignment — stepping a gain mid-sample is an
 * audible click.
 *
 * WHY WEB AUDIO AND NOT `<audio>` ELEMENTS: the crossfade. Two elements cannot
 * be faded against each other with any accuracy, because their volume can only
 * be stepped from a JS timer. Here both tracks hang on gain ramps on the AUDIO
 * clock, and the next track is even STARTED on that clock (`source.start(at)`),
 * so the seam is sample-accurate and independent of frame drops. A JS timer is
 * used for one thing only: waking up early enough to fetch and decode the next
 * track (`PRELOAD_S` before the seam) — the scheduling itself never depends on
 * when that timer actually fires.
 *
 * AUTOPLAY: a context created before the first user gesture starts
 * `suspended`, and everything scheduled into it simply waits. `unlock()` is
 * what resumes it, is idempotent and belongs on the first guaranteed click
 * (the login / "enter world" button).
 *
 * The engine has no opinion about WHICH tracks to play — it takes URL lists
 * (from `/assets/audio`) and volumes (from `game/prefs.ts`). Choosing by
 * daylight or terrain is the caller's job.
 */
import { seededRandom } from '../scene/textures';

export type Bus = 'music' | 'ambient' | 'tts';
export type VolumeBus = Bus | 'master';

/** Ramp length for a volume change — long enough to not click, short enough
 *  to feel immediate on a slider. */
const RAMP_S = 0.05;
/** Default crossfade between two tracks of a playlist. */
const DEFAULT_CROSSFADE_S = 3;
/** How long before the seam the next track is fetched and decoded. Generous:
 *  a decode of a few MB plus a slow request must still land in time, and
 *  arriving early costs nothing (the start time is fixed on the audio clock). */
const PRELOAD_S = 6;
/** A track shorter than two crossfades cannot be faded at full length —
 *  the fade is capped at a third of it so a jingle still gets a seam. */
const MIN_FADE_SHARE = 3;
/** Segments per crossfade. The fade follows an EQUAL-POWER curve, and this is
 *  how finely it is approximated — see `equalPowerFade`. */
const FADE_STEPS = 8;

/**
 * Schedules one half of an equal-power crossfade on `param`: `up` fades in
 * along sin(t·π/2), `down` fades out along cos(t·π/2).
 *
 * WHY NOT A STRAIGHT LINE: with two linear ramps both sides sit at half
 * amplitude in the middle of the seam, so the combined POWER of two unrelated
 * tracks is 0.5² + 0.5² = 0.5 — a 3 dB dip, audible as a "hole" in the middle
 * of every track change. sin² + cos² = 1 keeps the power constant instead
 * (measured residue −0.042 dB with the eight segments below), so the seam
 * sounds like one continuous piece of music.
 *
 * The curve is approximated with `FADE_STEPS` linear ramps rather than
 * `setValueCurveAtTime`, deliberately: a scheduled value curve makes the
 * `cancelScheduledValues` + `setValueAtTime` that `stop()` needs illegal while
 * it runs, and eight segments are already inaudibly close to the curve
 * (worst-case error < 1 %).
 */
function equalPowerFade(param: AudioParam, t0: number, dur: number,
                        up: boolean): void {
  param.setValueAtTime(up ? 0 : 1, t0);
  for (let i = 1; i <= FADE_STEPS; i++) {
    const t = i / FADE_STEPS;
    const v = up ? Math.sin((t * Math.PI) / 2) : Math.cos((t * Math.PI) / 2);
    param.linearRampToValueAtTime(v, t0 + dur * t);
  }
}

interface PlayOpts {
  /** Seconds of overlap between two tracks. */
  crossfadeS?: number;
  /** Shuffle seed. Defaults to the playlist itself — see `shuffle()`. */
  seed?: string;
}

/**
 * Deterministic shuffle, `seededRandom` from the tile textures (the client's
 * one PRNG — nothing here needs `Math.random`, and a reproducible order makes
 * a report about "the music order" checkable at all).
 *
 * The default seed is the PLAYLIST, which for music is exactly the time-of-day
 * bucket: the day list and the night list are different lists, so they shuffle
 * differently, while re-entering the same bucket in the same session keeps the
 * order it already had. Fisher-Yates, back to front.
 */
function shuffle(urls: string[], seed: string): string[] {
  const rnd = seededRandom(seed);
  const out = urls.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * One endless, crossfading playlist on one bus. Music and ambience differ
 * only in which bus they hang on and which URLs they get, so they are the
 * same machine twice.
 */
class Playlist {
  private urls: string[] = [];
  private at = 0;
  private crossfadeS = DEFAULT_CROSSFADE_S;
  /** The playlist currently running, as the caller passed it — an identical
   *  list is a no-op, so a poll that re-reports the same tracks does not
   *  restart the music every few seconds. */
  private key = '';
  private timer: ReturnType<typeof setTimeout> | null = null;
  /** The tracks currently sounding — up to two while a crossfade runs. Each
   *  keeps its OWN gain node, which is what makes a crossfade possible: the
   *  outgoing track fades on its node while the incoming one rises on its. */
  private live: { src: AudioBufferSourceNode; gain: GainNode }[] = [];
  /** Guards against a slow decode landing after `stop()` or after a switch. */
  private generation = 0;

  constructor(
    private ctx: AudioContext,
    private bus: GainNode,
    private decode: (url: string) => Promise<AudioBuffer>,
  ) {}

  play(urls: string[], opts: PlayOpts = {}): void {
    const key = urls.join('|');
    if (key === this.key) return;
    this.stop(opts.crossfadeS ?? DEFAULT_CROSSFADE_S);
    this.key = key;
    if (!urls.length) return;
    this.crossfadeS = Math.max(0, opts.crossfadeS ?? DEFAULT_CROSSFADE_S);
    this.urls = shuffle(urls, opts.seed ?? key);
    this.at = 0;
    const gen = this.generation;
    void this.startTrack(this.ctx.currentTime, gen);
  }

  /** Fades the running tracks out and drops the schedule. */
  stop(fadeS = RAMP_S): void {
    this.generation += 1;
    this.key = '';
    this.urls = [];
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const now = this.ctx.currentTime;
    const end = now + Math.max(RAMP_S, fadeS);
    for (const { src, gain } of this.live) {
      gain.gain.cancelScheduledValues(now);
      gain.gain.setValueAtTime(gain.gain.value, now);
      gain.gain.linearRampToValueAtTime(0, end);
      try {
        src.stop(end);
      } catch {
        /* already stopped */
      }
    }
    this.live = [];
  }

  /**
   * Decodes track `this.at`, starts it AT `startAt` on the audio clock, fades
   * it in, and arranges for the next one to overlap its tail.
   */
  private async startTrack(startAt: number, gen: number): Promise<void> {
    // Every URL gets one try; a broken file skips to the next instead of
    // ending the music (the folder is user data — a truncated mp3 happens).
    for (let tries = 0; tries < this.urls.length; tries++) {
      const url = this.urls[this.at];
      this.at = (this.at + 1) % this.urls.length;
      let buffer: AudioBuffer;
      try {
        buffer = await this.decode(url);
      } catch (e) {
        console.warn(`[audio] could not load ${url}`, e);
        continue;
      }
      if (gen !== this.generation) return;   // stopped or switched meanwhile
      const fade = Math.min(this.crossfadeS, buffer.duration / MIN_FADE_SHARE);
      const begin = Math.max(startAt, this.ctx.currentTime);
      const gain = this.ctx.createGain();
      gain.connect(this.bus);
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(gain);
      const seam = begin + buffer.duration - fade;
      if (fade > 0) {
        equalPowerFade(gain.gain, begin, fade, true);
        equalPowerFade(gain.gain, seam, fade, false);   // holds 1 until `seam`
      } else {
        gain.gain.setValueAtTime(1, begin);
      }
      src.start(begin);
      this.live.push({ src, gain });
      src.onended = () => {
        this.live = this.live.filter((e) => e.src !== src);
        gain.disconnect();
      };
      // Wake up early enough to have the next track decoded BEFORE the seam;
      // the seam itself is already fixed on the audio clock above.
      const wakeIn = Math.max(0, seam - PRELOAD_S - this.ctx.currentTime);
      this.timer = setTimeout(() => {
        this.timer = null;
        if (gen === this.generation) void this.startTrack(seam, gen);
      }, wakeIn * 1000);
      return;
    }
    console.warn('[audio] no playable file in the playlist');
  }
}

let engine: AudioEngine | null = null;

/**
 * The client's ONE audio engine. Created on first use, not at import time: an
 * `AudioContext` built during module evaluation is a context built before any
 * gesture, which some browsers log about and none of them let sound.
 */
export function getAudio(): AudioEngine {
  if (!engine) engine = new AudioEngine();
  return engine;
}

export class AudioEngine {
  private ctx: AudioContext;
  private master: GainNode;
  private buses: Record<Bus, GainNode>;
  private music: Playlist;
  private ambient: Playlist;
  /** Decoded buffers by URL — MUSIC AND AMBIENCE ONLY. The same few tracks
   *  loop for a whole session, so decoding one twice would be pure waste. */
  private buffers = new Map<string, Promise<AudioBuffer>>();
  /** Spoken lines are strictly serial: the tail of this chain is the point
   *  where the next `speak()` hangs itself. */
  private speech: Promise<void> = Promise.resolve();
  /** Bumped by `stopSpeech` — a queued line whose
   *  generation is stale drops out instead of playing (see `playSpeech`). */
  private speechGen = 0;
  private speaking: AudioBufferSourceNode | null = null;
  private unlocked = false;

  constructor() {
    const Ctor = window.AudioContext
      || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctor();
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.buses = {
      music: this.ctx.createGain(),
      ambient: this.ctx.createGain(),
      tts: this.ctx.createGain(),
    };
    for (const bus of Object.values(this.buses)) bus.connect(this.master);
    const decode = (url: string) => this.buffer(url);
    this.music = new Playlist(this.ctx, this.buses.music, decode);
    this.ambient = new Playlist(this.ctx, this.buses.ambient, decode);
  }

  /**
   * Resumes the context. Idempotent — call it on every gesture that might be
   * the first one; a running context makes this a no-op. Browsers only honour
   * it inside a user gesture, which is why it hangs on the login button.
   */
  async unlock(): Promise<void> {
    if (this.unlocked && this.ctx.state === 'running') return;
    try {
      await this.ctx.resume();
      this.unlocked = this.ctx.state === 'running';
    } catch (e) {
      console.warn('[audio] the AudioContext could not be resumed', e);
    }
  }

  /** True once the context actually runs — the UI can show "click to enable". */
  get running(): boolean {
    return this.ctx.state === 'running';
  }

  /** Sets a bus (or the master) to `v` in [0,1], ramped so it does not click. */
  setVolume(bus: VolumeBus, v: number): void {
    const node = bus === 'master' ? this.master : this.buses[bus];
    const value = Math.min(1, Math.max(0, v));
    const now = this.ctx.currentTime;
    node.gain.cancelScheduledValues(now);
    node.gain.setValueAtTime(node.gain.value, now);
    node.gain.linearRampToValueAtTime(value, now + RAMP_S);
  }

  /** Starts (or switches to) a music playlist. The same list twice keeps
   *  playing; an empty list stops the music. */
  playMusic(urls: string[], opts: PlayOpts = {}): void {
    this.music.play(urls, opts);
  }

  /** Same for the ambience bed. */
  playAmbient(urls: string[], opts: PlayOpts = {}): void {
    this.ambient.play(urls, opts);
  }

  /**
   * Plays one spoken line and resolves when it has finished. Lines queue:
   * every call waits for the one before it, so two characters talking at once
   * are heard one after the other instead of on top of each other.
   *
   * Never rejects, and always resolves: a line that fails to load, arrives
   * after `stopSpeech()` or is spoken into a still-locked context is a line not
   * heard — not a broken chat and not a promise the caller waits on forever.
   */
  speak(url: string): Promise<void> {
    const gen = this.speechGen;
    const done = this.speech.then(() => this.playSpeech(url, gen));
    this.speech = done.catch(() => undefined);
    return this.speech;
  }

  private async playSpeech(url: string, gen: number): Promise<void> {
    // The generation is checked before every step, exactly like `Playlist`
    // does it: `stopSpeech` cannot cancel the promise chain that is already
    // built, so each link has to notice that it belongs to a stopped queue and
    // fall through — otherwise the line AFTER the stopped one still plays, and
    // the next `speak()` (hanging on the fresh chain) plays on top of it.
    if (gen !== this.speechGen) return;
    // A suspended context never fires `onended`, so starting here would stall
    // the whole queue on a promise that cannot resolve. Silence is the correct
    // behaviour before the unlock gesture.
    if (!this.running) return;
    let buffer: AudioBuffer;
    try {
      buffer = await this.buffer(url, false);
    } catch (e) {
      console.warn(`[audio] could not load the speech file ${url}`, e);
      return;
    }
    if (gen !== this.speechGen) return;
    await new Promise<void>((resolve) => {
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.buses.tts);
      src.onended = () => {
        if (this.speaking === src) this.speaking = null;
        resolve();
      };
      this.speaking = src;
      src.start();
    });
  }

  /**
   * Stops the SPOKEN lines only — the line sounding right now and every one
   * already hanging on the chain behind it. Music and ambience keep playing.
   *
   * That separation is the whole point (E4-T6): the player's own message
   * interrupts what the room is saying, and a chat message that also killed the
   * soundtrack would be a bug nobody would look for here. There is deliberately
   * no "stop everything" hammer: the two playlists stop by being handed an
   * empty list, which is what the menu switches already do.
   */
  stopSpeech(): void {
    this.speechGen += 1;
    if (this.speaking) {
      try {
        this.speaking.stop();
      } catch {
        /* already stopped */
      }
      this.speaking = null;
    }
    this.speech = Promise.resolve();
  }

  /**
   * Fetch + decode. With `cache` (the playlists) the buffer is kept per URL,
   * because the same handful of tracks loops for a whole session.
   *
   * Spoken lines pass `cache = false`, and that is not a nicety: a cache entry
   * is not "a map entry", it is the DECODED PCM — a minute of stereo at 48 kHz
   * is around 11 MB of heap. TTS lines are unique and never repeat, so caching
   * them would grow without bound over a long session, with no eviction rule
   * that could sensibly decide what to drop.
   */
  private buffer(url: string, cache = true): Promise<AudioBuffer> {
    const known = cache ? this.buffers.get(url) : undefined;
    if (known) return known;
    const pending = (async () => {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`${resp.status} ${url}`);
      return this.ctx.decodeAudioData(await resp.arrayBuffer());
    })();
    if (cache) {
      // A failed load must not stay cached as a failure forever.
      pending.catch(() => this.buffers.delete(url));
      this.buffers.set(url, pending);
    }
    return pending;
  }
}
