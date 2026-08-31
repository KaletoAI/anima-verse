/**
 * The DECIDABLE rules of the HUD chat window: how big it may be, which
 * portraits the picture column shows, and which transcript row governs that
 * column (plan-hud-chat-portraits.md, task 2).
 *
 * Pure like `game/walk.ts`, `game/offers.ts` and `game/prefs.ts`: plain values,
 * no DOM, no React, no module state and no import at all. That is what lets
 * `scripts/smoke_chat_portraits.mjs` check the whole behaviour against numbers
 * derived by hand. The DOM side stays in `Hud.tsx` — it measures and calls in
 * here, it never re-decides anything.
 *
 * The `localStorage` contract is the one every other HUD setting follows
 * (`Hud.tsx`, `game/prefs.ts`): the store is user-writable and survives every
 * version of this client, so a reader NEVER throws and treats anything it does
 * not recognise as "nothing stored" rather than as a value to repair.
 */

/** Size the user dragged for the chat window, `{w,h}` as JSON. Absent = the
 *  stylesheet's own `width`/`height` decide, which is what a fresh browser and
 *  a double-clicked reset both give. */
export const CHAT_SIZE_KEY = 'av3d.chatSize';
/** How solid the chat window is drawn over the world (0..1). */
export const CHAT_ALPHA_KEY = 'av3d.chat.alpha';
/** How many portraits the picture column shows (1..3). */
export const CHAT_PORTRAITS_KEY = 'av3d.chat.portraits';

/**
 * THE SIZE BOUNDS, and what each end is for.
 *
 * The real ceiling is the VIEWPORT, and since the drag lifts the stylesheet's
 * default width cap (see `CHAT_VIEWPORT_MARGIN_W`) the clamp has to keep that
 * ceiling itself — it is handed in, never read here, so this stays a pure
 * function. The two numbers below are the FLOOR and a garbage filter:
 *
 * - `CHAT_MIN_W` is the chat column's own width (`CHAT_COL_W` below): at the
 *   minimum the picture column is squeezed to nothing and the transcript is
 *   all that is left, which is the panel as it was before this feature. Below
 *   it the composer's address chips, volume switch and buttons wrap into a
 *   stack nobody can operate.
 * - `CHAT_MIN_H` leaves the transcript about five lines: panel head ~31px,
 *   composer ~130px (address row + input + button row) and 100px of history.
 *   Under that the window is a text field with a title, and the transcript —
 *   the reason the panel exists — says nothing.
 *
 * The MAXIMA are garbage filters, not layout: 2400 x 2000 needs a window of
 * 2490 x 2070 px to be reachable at all. Anything beyond them in the store was
 * hand-edited or belongs to another client, and is dropped.
 */
export const CHAT_MIN_W = 520;
export const CHAT_MAX_W = 2400;
export const CHAT_MIN_H = 260;
export const CHAT_MAX_H = 2000;

/**
 * How much of the window the panel leaves standing — the same margins the
 * stylesheet keeps (`hud.css`, `.hud-chat`): the rail and the panel's own
 * offset on the width, the header band on the height.
 *
 * The width is the one that matters here. Its DEFAULT cap in the stylesheet is
 * tighter still (`max(420px, 50vw - 232px)`), because the bottom-centre stack
 * — talk prompt, character plaque, storey choice — reaches 220px to the left
 * of the viewport's middle and an untouched panel must not sit on it. A size
 * the user DRAGGED is not capped that way: pulling the edge is a decision, the
 * overlap is visible while it happens, and `Hud.tsx` therefore writes an inline
 * `max-width` of this margin alone whenever a dragged size exists.
 */
export const CHAT_VIEWPORT_MARGIN_W = 90;
export const CHAT_VIEWPORT_MARGIN_H = 70;

/** The window the panel has to fit into, in CSS pixels. Handed to the clamp
 *  instead of read inside it — that is what keeps the rule checkable. */
export interface ChatViewport {
  w: number;
  h: number;
}

/** Width of the chat column inside the split (E2): the chat keeps this and
 *  every extra pixel of the window goes LEFT, to the pictures. Same number as
 *  `CHAT_MIN_W` on purpose — the narrowest window is exactly "chat only". */
export const CHAT_COL_W = 520;

/** How solid the window is drawn. 1 = the opaque panel of before (the
 *  delivered state — this feature changes no look until it is used); below
 *  `CHAT_ALPHA_MIN` the transcript over a bright scene is unreadable, so the
 *  slider stops there rather than offering an invisible window. */
export const CHAT_ALPHA_MIN = 0.2;
export const CHAT_ALPHA_MAX = 1;
export const CHAT_ALPHA_DEFAULT = 1;

/** How many portraits the picture column shows. The upper end is a MEASURED
 *  one: over 37 logged turns a room history carried a median of 2 and at most
 *  4 distinct speakers, one of them the narrator, who is never drawn. */
export const PORTRAITS_MIN = 1;
export const PORTRAITS_MAX = 3;
export const PORTRAITS_DEFAULT = 1;

export interface ChatSize {
  w: number;
  h: number;
}

function clampNumber(v: number, min: number, max: number): number {
  // A non-number can only reach this from a broken caller, never from a drag;
  // the floor is the safe answer, and it is what an empty store gives too.
  if (!Number.isFinite(v)) return min;
  return Math.round(Math.min(max, Math.max(min, v)));
}

/** The ceiling of one axis: the garbage filter, or the window if that is the
 *  narrower of the two. A window measure that is not a number (no caller in
 *  this client produces one) leaves the fixed maximum standing. */
function ceilingFor(max: number, view: number, margin: number): number {
  if (!Number.isFinite(view)) return max;
  return Math.min(max, view - margin);
}

/**
 * The size a drag may actually set. Both axes are clamped independently —
 * pulling the top edge does not touch the width and vice versa.
 *
 * On a window smaller than the FLOOR the ceiling wins and the panel is made
 * narrower than `CHAT_MIN_W`: the stylesheet's viewport caps could always do
 * that, and a floor that pushed the panel off-screen would be the worse of the
 * two answers.
 */
export function clampChatSize(w: number, h: number, view: ChatViewport): ChatSize {
  return {
    w: clampNumber(w, CHAT_MIN_W, ceilingFor(CHAT_MAX_W, view.w, CHAT_VIEWPORT_MARGIN_W)),
    h: clampNumber(h, CHAT_MIN_H, ceilingFor(CHAT_MAX_H, view.h, CHAT_VIEWPORT_MARGIN_H)),
  };
}

/**
 * The stored size, or `null` for "nothing stored". Anything that is not a pair
 * of numbers INSIDE the range counts as absent: a size out of range is not
 * clamped back in but dropped, because a value nobody in this client could
 * have written is not a preference — it is noise, and clamping would silently
 * turn it into one.
 */
export function readChatSize(raw: string | null): ChatSize | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const { w, h } = parsed as { w?: unknown; h?: unknown };
  if (typeof w !== 'number' || typeof h !== 'number') return null;
  if (!Number.isFinite(w) || !Number.isFinite(h)) return null;
  if (w < CHAT_MIN_W || w > CHAT_MAX_W) return null;
  if (h < CHAT_MIN_H || h > CHAT_MAX_H) return null;
  return { w: Math.round(w), h: Math.round(h) };
}

/** The size to write back. One place, so reader and writer cannot drift. */
export function writeChatSize(size: ChatSize): string {
  return JSON.stringify({ w: size.w, h: size.h });
}

/** The stored opacity, or `null` for "nothing stored" (the default applies).
 *  Same rule as the size: out of range is noise, not a preference. */
export function readChatAlpha(raw: string | null): number | null {
  if (raw === null || raw.trim() === '') return null;
  const v = Number(raw);
  if (!Number.isFinite(v)) return null;
  if (v < CHAT_ALPHA_MIN || v > CHAT_ALPHA_MAX) return null;
  return v;
}

/** The stored portrait count, or `null` for "nothing stored". Whole numbers
 *  only — there is no half a portrait. */
export function readPortraitCount(raw: string | null): number | null {
  if (raw === null || raw.trim() === '') return null;
  const v = Number(raw);
  if (!Number.isInteger(v)) return null;
  if (v < PORTRAITS_MIN || v > PORTRAITS_MAX) return null;
  return v;
}

/** What this module needs of a transcript row. Structurally a subtype of the
 *  payload's `scene[]` entries, so the caller hands them over unchanged. */
export interface PortraitLine {
  id?: number;
  speaker?: string;
  meta?: Record<string, unknown>;
}

/** Same derivation `SceneView` uses, and for the same reason: the `/play/scene`
 *  payload carries the name in `meta.speaker`, the objective observer rows in
 *  `speaker`. Never the LOCALIZED display string — that is a rendering. */
function speakerOf(line: PortraitLine): string {
  return line.speaker || (line.meta?.speaker as string) || '';
}

/**
 * WHICH FACES THE PICTURE COLUMN SHOWS: the last `count` DISTINCT renderable
 * speakers of the history, in the order they spoke, the youngest LAST — that
 * is, right next to the chat column (E3).
 *
 * "Renderable" is not decided here and is deliberately not re-derived: the
 * server says so by listing a name in `speaker_expr_versions`, which it fills
 * for every speaker of the returned history except the narrator, the
 * display-only rows and the event verdicts. Testing for the narrator in the
 * client would mean testing a localized display string, which is exactly the
 * bug `SceneView` still carries.
 *
 * `focusId` cuts the history short: the column then describes the transcript
 * UP TO AND INCLUDING that row, which is what makes hovering a line answer
 * with the face that said it. `null` (the resting state) means the whole
 * history, so the youngest portrait is the one who spoke last. An id that is
 * not in this history at all — a row that has since fallen out of the payload
 * — cuts nothing; the resting state is the only sensible answer left.
 */
export function pickPortraitSpeakers(
  lines: readonly PortraitLine[],
  versions: Readonly<Record<string, string>>,
  count: number,
  focusId: number | null = null,
): string[] {
  const k = Number.isFinite(count) ? Math.floor(count) : 0;
  if (k <= 0) return [];
  let end = lines.length;
  if (focusId != null) {
    const at = lines.findIndex((l) => l.id === focusId);
    if (at >= 0) end = at + 1;
  }
  const newestFirst: string[] = [];
  for (let i = end - 1; i >= 0 && newestFirst.length < k; i--) {
    const name = speakerOf(lines[i]);
    if (!name) continue;
    if (!Object.prototype.hasOwnProperty.call(versions, name)) continue;
    if (newestFirst.includes(name)) continue;
    newestFirst.push(name);
  }
  return newestFirst.reverse();
}

/** One box of the picture column. A slot without a `name` has no face to
 *  show and is drawn as a silhouette. */
export interface PortraitSlot {
  /** the speaker whose portrait fills the slot; `''` = nobody */
  name: string;
  /** cache-buster out of `speaker_expr_versions`; `''` when there is none */
  version: string;
}

/**
 * WHAT THE COLUMN DRAWS: one slot per picked name, in that order, plus the one
 * rule that keeps the panel still — AN EMPTY SELECTION IS STILL ONE SLOT.
 *
 * The column takes all the width the chat column leaves (`hud.css`,
 * `.hud-chat-portraits` is `flex: 1 1 0`), so how many slots it holds never
 * moves the transcript. Whether it EXISTS does: without a column the flex row
 * has a single child and the transcript widens to the whole window, which is
 * the jump the user sees the moment the narrator is all that has been said.
 * So the column is always handed over and always has something to draw — a
 * face where there is one, the silhouette where there is not.
 */
export function portraitSlots(
  names: readonly string[],
  versions: Readonly<Record<string, string>>,
): PortraitSlot[] {
  if (!names.length) return [{ name: '', version: '' }];
  return names.map((name) => ({ name, version: versions[name] || '' }));
}

/** Where the transcript stands and what the pointer is on — everything the
 *  focus rule below needs, and nothing else. */
export interface ChatFocusInput {
  /** the row the pointer is over, `null` = nowhere */
  hoveredId: number | null;
  /** the row across the vertical middle of the scroll window, `null` = none */
  centeredId: number | null;
  /** the transcript is at its end (the "stick to bottom" state) */
  stuck: boolean;
}

/**
 * THE STATE RULE (E4), in three lines:
 *
 * - the POINTER wins whenever it is on a row. It is a deliberate act and
 *   beats "whatever happens to be in the middle";
 * - otherwise, a transcript that STICKS TO THE END is the resting state and
 *   answers `null` — the column then shows the last speakers, which is what
 *   somebody who is simply following the conversation wants;
 * - only a transcript that was scrolled UP hands the decision to the row in
 *   the middle. Scrolling back to the end returns to the resting state by
 *   itself, because `stuck` is true again.
 *
 * `null` therefore means "the end of the history", never "nothing".
 */
export function chatFocusId({ hoveredId, centeredId, stuck }: ChatFocusInput): number | null {
  if (hoveredId != null) return hoveredId;
  if (stuck) return null;
  return centeredId;
}

/** One measured row: its id and its vertical extent in viewport pixels. */
export interface RowExtent {
  id: number;
  top: number;
  bottom: number;
}

/**
 * The row that crosses `centerY`. The interval is HALF-OPEN (`top <= y <
 * bottom`), so two rows that touch — and in a gapped list they nearly do —
 * can never both answer: the lower one owns the shared edge. `null` when the
 * middle falls in a gap or the list is empty.
 */
export function rowAtCenter(rows: readonly RowExtent[], centerY: number): number | null {
  for (const r of rows) {
    if (r.top <= centerY && centerY < r.bottom) return r.id;
  }
  return null;
}
