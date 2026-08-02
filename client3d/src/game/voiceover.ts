/**
 * WHICH lines are read aloud, and in what order — the spoken half of the
 * client's audio (stage 4, task 6).
 *
 * `game/audio.ts` plays URLs and has no opinion about them, `api.ts` talks to
 * `/tts/speak`; this module is the opinion and the queue between the two. The
 * choosing part is pure (no DOM, no imports beyond a type), so every rule below
 * is checked with hand-written cases in `scripts/smoke_walk_math.mjs` — the
 * only reason a "the narrator is read aloud" bug can be found without listening
 * to a whole conversation. The driver takes its three side effects as
 * parameters for the same reason: it is the queue that is worth checking, not
 * how a fetch is spelled.
 *
 * WHAT IS SPOKEN. Only what a voice in the room actually said:
 * - kind `in_room` or `spoken_self` — `whisper_meta` carries no content (a
 *   third party only hears THAT something was whispered), `distant_shout`
 *   comes from another room, and `utterance` is the objective god view that
 *   never reaches a player payload;
 * - not the avatar itself: reading one's own message back is uncanny and takes
 *   the seconds in which the answer arrives;
 * - not the narrator (see `NARRATOR_SPEAKERS`) — narration is written, not
 *   said, and scene photos and movement traces are narrator lines too;
 * - nothing empty, and none of the display-only meta rows the scene view
 *   renders as notes (relationship changes, event verdicts).
 *
 * WHY A QUEUE WITH A CAP. Every line costs a TTS render (seconds) plus its own
 * playing time, and a room with four characters produces lines faster than
 * that. Without a cap the client would fall minutes behind the world and read
 * out a conversation the player has long since answered. So at most
 * `MAX_PENDING` lines wait, and it is the OLDEST that are dropped — the newest
 * line is the one that still matches what is on screen.
 *
 * The player's own message is the hard interruption: it clears the queue and
 * silences what is sounding (`clear()`), because everything waiting was said
 * BEFORE that message.
 */
import type { SceneLine } from '@anima/player-ui';

/**
 * Speaker values that mean "the narrator", never a voice in the room.
 *
 * The canonical, persisted one is `STORYTELLER_SPEAKER` in
 * `app/core/perception.py:41`. `/play/scene` substitutes the LOCALISED label
 * for display before it sends the payload (`app/routes/play.py:239`), so the
 * client sees the translated name in a German world — which is why this is a
 * list and not one constant. The translations live in
 * `shared/languages/<lang>.json` under the key "Storyteller" (today only
 * `de.json`: "Erzähler").
 */
export const NARRATOR_SPEAKERS: readonly string[] = ['Storyteller', 'Erzähler'];

/** One line ready to be spoken: who said it (the server picks the voice by
 *  character) and the words. */
export interface SpokenLine {
  speaker: string;
  text: string;
}

/** The transcript of one room as the HUD last saw it. */
export interface SceneSnapshot {
  room: string;
  lines: readonly SceneLine[];
}

/** The name the player sees, read exactly as `SceneView` reads it: the
 *  top-level speaker first, then the one in `meta`. */
export function speakerOf(line: SceneLine): string {
  return line.speaker || (line.meta?.speaker as string) || '';
}

/**
 * Identity of ONE line, as strong as the payload gets: the timestamp plus who
 * said what. The timestamp alone is NOT an identity — the server stamps with
 * `utc_now_iso()`, whose default is `timespec="seconds"`
 * (`app/core/timeutils.py:33`), so a whole second's worth of lines can share
 * one `ts` (`2026-06-24T22:46:09+00:00`).
 */
function identityOf(line: SceneLine): string {
  return `${line.ts || ''}|${speakerOf(line)}|${line.content || ''}`;
}

/**
 * Fingerprint of a transcript: how many lines, and the identity of the newest
 * one. Cheap, a plain string, and exactly what a React effect can depend on —
 * the poll hands out a fresh array every 5 seconds, and its identity says
 * nothing.
 *
 * The last line's SPEAKER AND CONTENT are part of it, not just its `ts`: at a
 * one-second resolution the pair (count, ts) does not change when the rolling
 * window drops a line at the front while a new one arrives in the same second,
 * and a transcript that changed but does not move this string is a line the
 * HUD never sees at all.
 */
export function sceneStampOf(lines: readonly SceneLine[] | undefined): string {
  const list = lines || [];
  return `${list.length}|${list.length ? identityOf(list[list.length - 1]) : ''}`;
}

/**
 * The lines that are NEW compared to `prev` — the ONE new-lines detection of
 * the HUD. The chat auto-show and the speech driver must never disagree about
 * what "somebody said something" means, so they read the same function.
 *
 * ANCHORED, NOT COMPARED BY TIME. The last line already seen is looked up in
 * the new transcript and everything after it is new. A `ts` comparison cannot
 * do this job: timestamps have SECOND resolution (see `identityOf`), so a
 * second character answering within the same second as the last line of the
 * previous poll — the parallel respond lane does exactly that — would never be
 * greater than what was seen and would be dropped in silence. Anchoring also
 * survives the rolling window of `/play/scene` (100 lines): the anchor moves
 * to the front instead of the count telling a story.
 *
 * DUPLICATES. Two lines with the same identity are two characters saying the
 * same words in the same second — rare, but it decides where to cut. So the
 * anchor is counted: if the previous transcript held it twice, the SECOND
 * occurrence in the new one is the anchor, and a third one is new. Fewer
 * occurrences than before means the older ones rolled out of the window, and
 * the last one is the anchor.
 *
 * FALLBACK. If the anchor is gone from the window entirely (more than a
 * hundred lines since the last poll, or a consolidated scene), there is
 * nothing to anchor to and the `ts` comparison is the last resort — with its
 * known blind spot for the same second, which at that point costs at most one
 * line out of a hundred that were missed anyway.
 *
 * Two cases are deliberately NOT new and only set the baseline: the first
 * payload after mount (`prev` = null — otherwise the chat pops open on every
 * page load and the room's last hour is read aloud at once) and a room change
 * (walking into a room with an older transcript is not somebody speaking).
 */
export function newSceneLines(prev: SceneSnapshot | null,
                              cur: SceneSnapshot): SceneLine[] {
  if (!prev) return [];
  if (prev.room !== cur.room) return [];
  if (!prev.lines.length) return cur.lines.slice();
  const anchor = identityOf(prev.lines[prev.lines.length - 1]);
  let seenTimes = 0;
  for (const l of prev.lines) if (identityOf(l) === anchor) seenTimes += 1;
  const hits: number[] = [];
  for (let i = 0; i < cur.lines.length; i++) {
    if (identityOf(cur.lines[i]) === anchor) hits.push(i);
  }
  if (hits.length) return cur.lines.slice(hits[Math.min(seenTimes, hits.length) - 1] + 1);
  const seenTs = prev.lines[prev.lines.length - 1].ts || '';
  return cur.lines.filter((l) => (l.ts || '') > seenTs);
}

/** Perception kinds that are a voice speaking IN this room. */
const SPOKEN_KINDS = new Set(['in_room', 'spoken_self']);
/** `meta` keys that mark a row as a UI note rather than speech (`SceneView`
 *  renders each of them as its own kind of block). */
const NOTE_KEYS = ['display_only', 'relationship', 'event_verdict'];

/**
 * The lines of `lines` that a voice should read, in order. Pure filter — see
 * the module docstring for WHAT is dropped and why.
 *
 * `spoken_self` is in the accepted kinds although the avatar rule removes
 * every one of them in practice (the stream is the avatar's own perception, so
 * `spoken_self` means the avatar spoke): the kind list is the contract with
 * `app/core/perception.py`, and a stream fetched for anyone else would carry
 * that kind meaningfully.
 */
export function speakableLines(lines: readonly SceneLine[], avatar: string,
                               narrators: readonly string[] = NARRATOR_SPEAKERS
): SpokenLine[] {
  const out: SpokenLine[] = [];
  for (const line of lines) {
    if (!line.kind || !SPOKEN_KINDS.has(line.kind)) continue;
    const meta = line.meta;
    if (meta && NOTE_KEYS.some((k) => meta[k])) continue;
    const speaker = speakerOf(line);
    if (!speaker || speaker === avatar || narrators.includes(speaker)) continue;
    const text = (line.content || '').trim();
    if (!text) continue;
    out.push({ speaker, text });
  }
  return out;
}

/**
 * Everything after the player's own LAST line in this batch. One's own message
 * ends the backlog: what was said before it is what the player just answered,
 * and hearing it read out afterwards is the wrong conversation.
 */
export function afterOwnLine(lines: readonly SceneLine[], avatar: string): SceneLine[] {
  let cut = -1;
  for (let i = 0; i < lines.length; i++) {
    if (speakerOf(lines[i]) === avatar) cut = i;
  }
  return lines.slice(cut + 1);
}

/** How many lines may wait to be spoken. Three is roughly the exchange still
 *  on screen; a fourth would be answered before it is heard. */
export const MAX_PENDING = 3;

/** The waiting queue after `incoming` arrived — at most `max` lines, the
 *  OLDEST dropped. Pure; the driver below is the only caller that keeps
 *  the result. */
export function enqueueSpeech(queue: readonly SpokenLine[],
                              incoming: readonly SpokenLine[],
                              max: number = MAX_PENDING): SpokenLine[] {
  const all = [...queue, ...incoming];
  return all.length > max ? all.slice(all.length - max) : all;
}

/**
 * The three side effects the driver needs. Passed in, never imported: that
 * keeps this module free of `api.ts` and `audio.ts` (and therefore loadable in
 * the smoke check), and it puts the wiring where the HUD's own state lives.
 */
export interface VoiceoverDeps {
  /** Render one line to an audio URL (`POST /tts/speak`). An empty string
   *  means "nothing to play" — TTS off, no speakable text left after the
   *  server's cleanup, a failed render. Must not reject; if it does, the line
   *  is skipped. */
  synth: (line: SpokenLine) => Promise<string>;
  /** Play one URL, resolving when it has finished (`AudioEngine.speak`). */
  play: (url: string) => Promise<void>;
  /** Silence what is sounding right now — SPEECH ONLY
   *  (`AudioEngine.stopSpeech`; `stopAll` would take the music with it). */
  stop: () => void;
}

export interface Voiceover {
  /** Queue these lines (capped, see `enqueueSpeech`) and keep the chain
   *  running. Returns immediately — speaking is a background chain. */
  push(lines: readonly SpokenLine[]): void;
  /** Drop everything waiting and silence the current line. Used by the
   *  player's own message and by switching the voices off. */
  clear(): void;
  /** What is waiting (a copy) — for the smoke check and for a caller that
   *  wants to show a backlog. */
  readonly pending: SpokenLine[];
}

/**
 * The serial driver: one line at a time, render then play then the next. Serial
 * on purpose — two voices at once are not a conversation, and the TTS backend
 * is one queue anyway.
 *
 * Every step checks its GENERATION, the same pattern `audio.ts` uses: `clear()`
 * cannot cancel a promise chain that is already built, so each link has to
 * notice that it belongs to a cleared queue and fall through. Errors are
 * console warnings and nothing else — a room whose speech backend is down must
 * still be a playable room.
 */
export function createVoiceover(deps: VoiceoverDeps): Voiceover {
  let queue: SpokenLine[] = [];
  let running = false;
  let generation = 0;

  async function run(): Promise<void> {
    running = true;
    const gen = generation;
    try {
      while (queue.length) {
        if (gen !== generation) return;
        const line = queue.shift() as SpokenLine;
        let url = '';
        try {
          url = await deps.synth(line);
        } catch (e) {
          console.warn(`[voiceover] could not render a line of ${line.speaker}`, e);
        }
        if (gen !== generation) return;
        if (!url) continue;
        try {
          await deps.play(url);
        } catch (e) {
          console.warn(`[voiceover] could not play ${url}`, e);
        }
      }
    } finally {
      // Only the generation that is still current hands the chain back; a
      // cleared one must not report the fresh chain as idle.
      if (gen === generation) running = false;
    }
  }

  return {
    push(lines: readonly SpokenLine[]): void {
      if (!lines.length) return;
      queue = enqueueSpeech(queue, lines);
      if (!running) void run();
    },
    clear(): void {
      generation += 1;
      queue = [];
      running = false;
      deps.stop();
    },
    get pending(): SpokenLine[] {
      return queue.slice();
    },
  };
}
