/**
 * Smoke: the decidable rules of the HUD chat window — `hud/chatPanel.ts`.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *     node scripts/smoke_chat_portraits.mjs
 *
 * WHY THIS CHECK EXISTS. Three rules of the chat window are decisions, not
 * drawing, and each of them is a place where the panel can quietly become
 * useless: which faces the picture column shows, how small the window may be
 * dragged, and which transcript row governs the column. All three are pure
 * functions for exactly that reason; the DOM side in `Hud.tsx` only measures
 * and calls in.
 *
 * EVERY EXPECTED VALUE BELOW IS DERIVED BY HAND from the rule, never from the
 * function's output.
 *
 * ── THE HISTORY, once ───────────────────────────────────────────────────
 * Eight rows, in the order the room heard them. `speaker_expr_versions` is the
 * server's list of who can be DRAWN; the narrator is not in it, and neither is
 * "Ghost" (a speaker the server did not version — the same case as a row the
 * selection must skip):
 *
 *     id 10  Storyteller   not versioned  → skipped
 *     id 11  Ayla          versioned
 *     id 12  Bea           versioned
 *     id 13  Ayla          versioned
 *     id 14  Storyteller   not versioned  → skipped
 *     id 15  Cara          versioned
 *     id 16  Bea           versioned
 *     id 17  Ghost         not versioned  → skipped
 *
 * The renderable sequence is therefore 11 Ayla · 12 Bea · 13 Ayla · 15 Cara ·
 * 16 Bea. Walking it BACKWARDS and keeping the first sighting of each name
 * gives Bea (16), Cara (15), Ayla (13); the column shows them in history
 * order, youngest last, i.e. reversed:
 *
 *     K = 1  → [Bea]                 (Ghost at 17 is not drawable)
 *     K = 2  → [Cara, Bea]
 *     K = 3  → [Ayla, Cara, Bea]
 *     K = 4  → [Ayla, Cara, Bea]     only three distinct faces exist
 *
 * With the focus on row 13 the history is cut after it — 10..13, renderable
 * 11 Ayla · 12 Bea · 13 Ayla — so backwards: Ayla (13), Bea (12), and 11 is
 * Ayla again:
 *
 *     K = 1  → [Ayla]
 *     K = 2  → [Bea, Ayla]
 *     K = 3  → [Bea, Ayla]           only two distinct faces up to there
 *
 * ── THE NARRATOR HAS A PLACE OF ITS OWN ─────────────────────────────────
 * The rows above are named "Storyteller" but carry NO mark, and that is the
 * point: a name never decides. The server marks its narrator rows with
 * `meta.narrator === true` (`app/routes/play.py`), because the name it puts on
 * them is a LOCALIZED label — in an English world it is the canonical value
 * itself, in a German one it is "Erzähler", and neither is a speaker kind.
 *
 * A marked row is a picture slot like any other, with one difference: it is
 * PICTURELESS. There is no narrator portrait to fetch, so the slot carries no
 * name and no version and the column draws the silhouette for it directly —
 * never an <img> that has to fail first.
 *
 * A second history, marked the way the server now marks:
 *
 *     id 20  Ayla        versioned
 *     id 21  narrator    marked
 *     id 22  narrator    marked
 *     id 23  Bea         versioned
 *     id 24  Ghost       not versioned  → skipped
 *
 * Walking BACKWARDS and keeping the first sighting of each: Ghost (24) is not
 * drawable, Bea (23), then the narrator (22) — and 21 is the narrator again,
 * so it adds nothing, exactly as a speaker who says two things in a row adds
 * one face — then Ayla (20). Reversed for the column, youngest last:
 *
 *     K = 1  → [Bea]                  the youngest drawable row is 23
 *     K = 2  → [narrator, Bea]
 *     K = 3  → [Ayla, narrator, Bea]  the narrator keeps its place in between
 *     K = 4  → [Ayla, narrator, Bea]  three distinct places exist
 *
 * The narrator COUNTS: at K = 2 it takes the place Ayla would have had.
 *
 * With the focus on row 22 the history is cut after it — 20 Ayla, 21 and 22
 * narrator — so backwards: narrator (22), 21 is the same place again, Ayla
 * (20), i.e. `[Ayla, narrator]`.
 *
 * ── THE SLOTS THE COLUMN DRAWS ──────────────────────────────────────────
 * One slot per picked name, in that order, each carrying the version the
 * server sent for it. The narrator's place becomes a slot with neither: it is
 * `{ name: '', version: '', narrator: true }`. The one rule on top: an EMPTY
 * selection is still one slot — a nameless one, drawn as a silhouette. That is
 * what keeps the column's width constant, and the transcript's with it: a
 * history in which nothing drawable has been said used to hand over no column
 * at all, and the chat jumped wider the moment it did.
 *
 * ── THE SIZE BOUNDS ─────────────────────────────────────────────────────
 * 520 x 260 minimum, 2400 x 2000 maximum (`chatPanel.ts` explains both ends).
 * Clamping is per axis; a stored value OUTSIDE the range is dropped, not
 * clamped — "nothing stored" is the only honest reading of noise.
 *
 * The VIEWPORT is the second ceiling, and it is handed in rather than read, so
 * the rule stays a pure function. It is the same margin the stylesheet keeps:
 * 90px of window width and 70px of window height. Derived by hand for a
 * 1920 x 1080 window:
 *
 *     width  ceiling  min(2400, 1920 - 90)  = 1830
 *     height ceiling  min(2000, 1080 - 70)  = 1010
 *
 * That ceiling is DELIBERATELY wider than the stylesheet's DEFAULT cap. Until
 * a handle is touched the panel also stops short of the bottom-centre plaque
 * (`max(420px, 50vw - 232px)`, i.e. 728px on a 1920 window); a size the user
 * dragged is only capped by the window, because whoever pulls the edge has
 * decided and sees the overlap. So a dragged 900 survives at 1920 — 900 is
 * past 728 and well inside 1830 — and `Hud.tsx` lifts the stylesheet cap for
 * exactly the case where a stored size exists.
 *
 * On a window too small for the FLOOR the window still wins (500px wide →
 * 410px of ceiling, under the 520 floor): the stylesheet has always been able
 * to squeeze the panel below it, and a floor that pushed the panel off-screen
 * would be the worse answer.
 *
 * ── THE FOCUS RULE (E4) ─────────────────────────────────────────────────
 * pointer → that row; else stuck to the end → null (the resting state, i.e.
 * the whole history); else the row in the middle. So the mouse beats "middle",
 * and scrolling back to the end returns to the resting state on its own.
 */
import { spawnSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  if (!process.env.SMOKE_BUNDLED) {
    const bundlePath = '/tmp/smoke_chat_portraits_bundled.mjs'
    const root = path.join(__dirname, '../')
    const bin = ['client3d/node_modules/.bin/esbuild',
                 'node_modules/.bin/esbuild']
      .map((rel) => path.join(root, rel)).find((p) => fs.existsSync(p))
    if (!bin) {
      console.error('esbuild not found (npm install) — nothing was checked')
      process.exit(1)
    }
    const built = spawnSync(bin, [
      __filename, '--bundle', '--platform=node', '--format=esm',
      `--outfile=${bundlePath}`,
    ], { cwd: root, stdio: 'inherit' })
    if (built.status !== 0) process.exit(built.status ?? 1)
    const run = spawnSync('node', [bundlePath], {
      stdio: 'inherit', env: { ...process.env, SMOKE_BUNDLED: '1' },
    })
    process.exit(run.status ?? 1)
  }

  const {
    pickPortraitSpeakers, portraitSlots, NARRATOR_SLOT,
    clampChatSize, readChatSize, writeChatSize,
    readChatAlpha, readPortraitCount, chatFocusId, rowAtCenter,
    CHAT_MIN_W, CHAT_MAX_W, CHAT_MIN_H, CHAT_MAX_H, CHAT_COL_W,
    CHAT_ALPHA_MIN, CHAT_ALPHA_MAX, PORTRAITS_MIN, PORTRAITS_MAX,
  } = await import('../client3d/src/hud/chatPanel.ts')

  const failures = []
  const check = (label, actual, expected) => {
    const a = JSON.stringify(actual)
    const e = JSON.stringify(expected)
    const ok = a === e
    console.log(`  ${ok ? '✓' : '✗'} ${label} — ${a}`)
    if (!ok) {
      failures.push(label)
      console.log(`      expected ${e}`)
    }
  }

  // ── The history, exactly as documented above ─────────────────────────
  const say = (id, speaker) => ({ id, ts: '', content: '', kind: 'in_room',
                                  meta: { speaker } })
  const HISTORY = [
    say(10, 'Storyteller'), say(11, 'Ayla'), say(12, 'Bea'), say(13, 'Ayla'),
    say(14, 'Storyteller'), say(15, 'Cara'), say(16, 'Bea'), say(17, 'Ghost'),
  ]
  const VERSIONS = { Ayla: 'a1', Bea: 'b1', Cara: 'c1' }

  // The second history: the narrator rows the server MARKED. The label on them
  // is the German one on purpose — the mark decides, the name never does.
  const nar = (id) => ({ id, ts: '', content: '', kind: 'in_room',
                         meta: { speaker: 'Erzähler', narrator: true } })
  const NARRATED = [
    say(20, 'Ayla'), nar(21), nar(22), say(23, 'Bea'), say(24, 'Ghost'),
  ]
  const N = NARRATOR_SLOT

  console.log('\n[0] the bounds the cases below are derived from')
  check('the window floor is 520 x 260', [CHAT_MIN_W, CHAT_MIN_H], [520, 260])
  check('the window ceiling is 2400 x 2000', [CHAT_MAX_W, CHAT_MAX_H], [2400, 2000])
  check('the chat column is as wide as the narrowest window', CHAT_COL_W, CHAT_MIN_W)
  check('the opacity range is 0.2 .. 1', [CHAT_ALPHA_MIN, CHAT_ALPHA_MAX], [0.2, 1])
  check('the portrait count runs 1 .. 3', [PORTRAITS_MIN, PORTRAITS_MAX], [1, 3])

  console.log('\n[1] speaker selection: only what the server versioned, once each,'
    + ' history order, youngest last')
  check('K=1 → the last drawable speaker (Ghost at 17 is not one)',
        pickPortraitSpeakers(HISTORY, VERSIONS, 1), ['Bea'])
  check('K=2 → Cara then Bea', pickPortraitSpeakers(HISTORY, VERSIONS, 2),
        ['Cara', 'Bea'])
  check('K=3 → Ayla, Cara, Bea (Ayla from row 13, her younger sighting)',
        pickPortraitSpeakers(HISTORY, VERSIONS, 3), ['Ayla', 'Cara', 'Bea'])
  check('K=4 → still three: only three distinct faces exist',
        pickPortraitSpeakers(HISTORY, VERSIONS, 4), ['Ayla', 'Cara', 'Bea'])
  check('K=0 → nothing', pickPortraitSpeakers(HISTORY, VERSIONS, 0), [])
  check('an empty history shows nothing', pickPortraitSpeakers([], VERSIONS, 3), [])
  check('an empty version map shows nothing — not even Ayla',
        pickPortraitSpeakers(HISTORY, {}, 3), [])
  // Walking back from 17 with the narrator versioned: Ghost (17) is still not,
  // then Bea (16), Cara (15), Storyteller (14) — reversed for the column.
  check('a row merely NAMED "Storyteller" is an ordinary speaker — version him '
    + 'and he is drawn like anybody else',
        pickPortraitSpeakers(HISTORY, { ...VERSIONS, Storyteller: 's1' }, 3),
        ['Storyteller', 'Cara', 'Bea'])
  check('an objective row carries the name in `speaker`, not in `meta`',
        pickPortraitSpeakers([{ id: 1, speaker: 'Ayla' }], VERSIONS, 2), ['Ayla'])
  check('a row without any speaker is skipped',
        pickPortraitSpeakers([{ id: 1 }, { id: 2, meta: { speaker: 'Bea' } }],
                             VERSIONS, 2), ['Bea'])

  console.log('\n[1b] the narrator gets a place of its own — by the MARK, and'
    + ' pictureless')
  check('K=1 → Bea: the youngest drawable row is hers, Ghost has no version',
        pickPortraitSpeakers(NARRATED, VERSIONS, 1), ['Bea'])
  check('K=2 → THE NARRATOR COUNTS: it takes the place Ayla would have had',
        pickPortraitSpeakers(NARRATED, VERSIONS, 2), [N, 'Bea'])
  check('K=3 → the narrator keeps its place in the middle, history order',
        pickPortraitSpeakers(NARRATED, VERSIONS, 3), ['Ayla', N, 'Bea'])
  check('K=4 → still three: rows 21 and 22 are ONE place, like one speaker '
    + 'saying two things in a row',
        pickPortraitSpeakers(NARRATED, VERSIONS, 4), ['Ayla', N, 'Bea'])
  check('a narrator-only history is a narrator place, not an empty column',
        pickPortraitSpeakers([nar(1), nar(2)], VERSIONS, 3), [N])
  check('THE MARK DECIDES, NOT THE VERSION MAP: versioning the label changes '
    + 'nothing', pickPortraitSpeakers(NARRATED, { ...VERSIONS, 'Erzähler': 'e1' }, 3),
        ['Ayla', N, 'Bea'])
  check('an unversioned REAL speaker still stays out (Ghost at 24)',
        pickPortraitSpeakers(NARRATED, VERSIONS, 4).includes('Ghost'), false)
  check('focus 22 cuts after the second narrator row → [Ayla, narrator]',
        pickPortraitSpeakers(NARRATED, VERSIONS, 3, 22), ['Ayla', N])

  console.log('\n[1a] the column ALWAYS has a slot — a face, or the silhouette')
  check('the drawn slots carry the version the server sent',
        portraitSlots(['Cara', 'Bea'], VERSIONS),
        [{ name: 'Cara', version: 'c1', narrator: false },
         { name: 'Bea', version: 'b1', narrator: false }])
  check('NOBODY TO SHOW IS STILL ONE SLOT — the silhouette, so the column '
    + 'keeps its width and the transcript never widens',
        portraitSlots([], VERSIONS), [{ name: '', version: '', narrator: false }])
  check('a history with nothing drawable in it therefore draws the silhouette',
        portraitSlots(pickPortraitSpeakers(HISTORY, VERSIONS, 3, 10), VERSIONS),
        [{ name: '', version: '', narrator: false }])
  check('THE NARRATOR PLACE IS PICTURELESS: no name to fetch, no version',
        portraitSlots(pickPortraitSpeakers(NARRATED, VERSIONS, 3), VERSIONS),
        [{ name: 'Ayla', version: 'a1', narrator: false },
         { name: '', version: '', narrator: true },
         { name: 'Bea', version: 'b1', narrator: false }])
  check('…even when the version map does carry the narrator label',
        portraitSlots(pickPortraitSpeakers([nar(1)], { ...VERSIONS, 'Erzähler': 'e1' }, 1),
                      { ...VERSIONS, 'Erzähler': 'e1' }),
        [{ name: '', version: '', narrator: true }])
  check('a name the version map does not carry keeps its slot, versionless',
        portraitSlots(['Ghost'], VERSIONS),
        [{ name: 'Ghost', version: '', narrator: false }])
  check('the slot count follows the names, not K: one speaker, one slot',
        portraitSlots(pickPortraitSpeakers(HISTORY, VERSIONS, 3, 12), VERSIONS)
          .length, 2)

  console.log('\n[2] the focus cuts the history short (hovering a line answers'
    + ' with the faces up to it)')
  check('focus 13, K=1 → Ayla', pickPortraitSpeakers(HISTORY, VERSIONS, 1, 13),
        ['Ayla'])
  check('focus 13, K=2 → Bea, Ayla',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, 13), ['Bea', 'Ayla'])
  check('focus 13, K=3 → still two: only Ayla and Bea have spoken by then',
        pickPortraitSpeakers(HISTORY, VERSIONS, 3, 13), ['Bea', 'Ayla'])
  check('focus 14 (an unmarked "Storyteller" row) answers with the faces behind it',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, 14), ['Bea', 'Ayla'])
  check('focus 10 (the first row, unversioned) → nothing drawable yet',
        pickPortraitSpeakers(HISTORY, VERSIONS, 3, 10), [])
  check('a focus id no longer in the history cuts nothing (= the resting state)',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, 999), ['Cara', 'Bea'])

  console.log('\n[3] size clamping: the drag stops at the bounds, per axis')
  // A window big enough that only the fixed bounds can speak: 2400 + 90 wide,
  // 2000 + 70 tall, so both viewport ceilings land exactly on the maxima.
  const HUGE = { w: 2490, h: 2070 }
  check('dragged below the floor → the floor', clampChatSize(300, 100, HUGE),
        { w: 520, h: 260 })
  check('dragged past the ceiling → the ceiling', clampChatSize(9999, 9999, HUGE),
        { w: 2400, h: 2000 })
  check('inside the range it is kept, rounded to whole pixels',
        clampChatSize(700.4, 400.6, HUGE), { w: 700, h: 401 })
  check('the axes are independent: narrow AND far too tall',
        clampChatSize(10, 5000, HUGE), { w: 520, h: 2000 })
  check('exactly on the bounds is inside them',
        [clampChatSize(520, 260, HUGE), clampChatSize(2400, 2000, HUGE)],
        [{ w: 520, h: 260 }, { w: 2400, h: 2000 }])
  check('a drag that produced no number falls to the floor',
        clampChatSize(NaN, NaN, HUGE), { w: 520, h: 260 })

  console.log('\n[3a] …and the window is the other ceiling, handed in, not read')
  const FHD = { w: 1920, h: 1080 }
  check('a 1920 x 1080 window caps at 1830 x 1010, not at 2400 x 2000',
        clampChatSize(9999, 9999, FHD), { w: 1830, h: 1010 })
  check('A DRAGGED WIDTH MAY PASS THE PLAQUE CAP: 900 > 728 and stays 900',
        clampChatSize(900, 600, FHD), { w: 900, h: 600 })
  check('one pixel short of the window ceiling is kept',
        clampChatSize(1829, 1009, FHD), { w: 1829, h: 1009 })
  check('one pixel past it is the ceiling',
        clampChatSize(1831, 1011, FHD), { w: 1830, h: 1010 })
  check('the floor still holds on a roomy window',
        clampChatSize(300, 100, FHD), { w: 520, h: 260 })
  check('a window too small for the floor wins anyway (500 - 90, 300 - 70)',
        clampChatSize(800, 600, { w: 500, h: 300 }), { w: 410, h: 230 })
  check('a window measure that is no number falls back to the fixed maxima',
        clampChatSize(9999, 9999, { w: NaN, h: NaN }), { w: 2400, h: 2000 })

  console.log('\n[4] a stored size that is nonsense counts as NOTHING stored')
  check('nothing in the store', readChatSize(null), null)
  check('an empty entry', readChatSize(''), null)
  check('not JSON at all', readChatSize('840x680'), null)
  check('JSON, but not an object', readChatSize('null'), null)
  check('only one axis', readChatSize('{"w":700}'), null)
  check('a string where a number belongs', readChatSize('{"w":"700","h":400}'), null)
  check('NaN cannot even be written as JSON', readChatSize('{"w":NaN,"h":400}'), null)
  check('a negative width', readChatSize('{"w":-700,"h":400}'), null)
  check('one pixel under the width floor is DROPPED, not clamped',
        readChatSize('{"w":519,"h":400}'), null)
  check('one pixel over the width ceiling', readChatSize('{"w":2401,"h":400}'), null)
  check('one pixel under the height floor', readChatSize('{"w":700,"h":259}'), null)
  check('one pixel over the height ceiling', readChatSize('{"w":700,"h":2001}'), null)
  check('a sane pair survives, rounded', readChatSize('{"w":700.6,"h":400.2}'),
        { w: 701, h: 400 })
  check('reader and writer agree', readChatSize(writeChatSize({ w: 733, h: 512 })),
        { w: 733, h: 512 })

  console.log('\n[5] the other two stored settings, same rule')
  check('no opacity stored', readChatAlpha(null), null)
  check('not a number', readChatAlpha('half'), null)
  check('fully see-through is below the floor', readChatAlpha('0'), null)
  check('over 1 is not an opacity', readChatAlpha('1.0001'), null)
  check('the floor itself is allowed', readChatAlpha('0.2'), 0.2)
  check('and so is opaque', readChatAlpha('1'), 1)
  check('a value in between', readChatAlpha('0.55'), 0.55)
  check('no count stored', readPortraitCount(null), null)
  check('zero portraits is not an option', readPortraitCount('0'), null)
  check('four is past the measured maximum', readPortraitCount('4'), null)
  check('there is no half a portrait', readPortraitCount('2.5'), null)
  check('two is', readPortraitCount('2'), 2)

  console.log('\n[6] the state rule E4: resting ↔ hover ↔ middle ↔ back to the end')
  const F = (hoveredId, centeredId, stuck) =>
    chatFocusId({ hoveredId, centeredId, stuck })
  check('at the end, pointer away → the resting state', F(null, 42, true), null)
  check('scrolled up → the row in the middle', F(null, 42, false), 42)
  check('THE MOUSE BEATS THE MIDDLE', F(7, 42, false), 7)
  check('…and it beats the resting state too', F(7, null, true), 7)
  // Both other inputs are set AND favourable at once — the transcript sticks
  // to its end (resting → null) and row 42 crosses the middle. The rule reads
  // the pointer FIRST and returns before either can speak, so 7 it is. This is
  // the case a hovering user is actually in: the chat follows the conversation
  // while the mouse rests on an older line.
  check('the pointer wins even when the end AND the middle would both answer',
        F(7, 42, true), 7)
  check('the pointer leaves while scrolled up → the middle again',
        F(null, 42, false), 42)
  check('scrolled back to the end → the resting state returns',
        F(null, 42, true), null)
  check('scrolled up with nothing across the middle → resting anyway',
        F(null, null, false), null)
  check('row id 0 is a row, not "nothing"', F(0, 42, false), 0)

  console.log('\n[7] …and the same cycle as the faces the column then shows')
  check('resting: the last drawable speakers',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, F(null, 15, true)),
        ['Cara', 'Bea'])
  check('pointer on row 13: the faces up to Ayla',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, F(13, 15, true)),
        ['Bea', 'Ayla'])
  check('scrolled up, pointer away, row 12 in the middle',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, F(null, 12, false)),
        ['Ayla', 'Bea'])
  check('back at the end: the resting set again',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, F(null, 12, true)),
        ['Cara', 'Bea'])

  console.log('\n[8] which row is "in the middle" — a half-open interval, so no'
    + ' two rows ever answer at once')
  const ROWS = [
    { id: 11, top: 0, bottom: 20 },
    { id: 12, top: 20, bottom: 44 },
    { id: 13, top: 60, bottom: 80 },
  ]
  check('the very top belongs to the first row', rowAtCenter(ROWS, 0), 11)
  check('one pixel short of the shared edge', rowAtCenter(ROWS, 19.9), 11)
  check('ON the shared edge the LOWER row owns it', rowAtCenter(ROWS, 20), 12)
  check('inside the second row', rowAtCenter(ROWS, 43.9), 12)
  check('a gap between rows answers nothing', rowAtCenter(ROWS, 44), null)
  check('…and so does the middle of that gap', rowAtCenter(ROWS, 50), null)
  check('the row after the gap', rowAtCenter(ROWS, 60), 13)
  check('the bottom edge of the last row is past it', rowAtCenter(ROWS, 80), null)
  check('above the list', rowAtCenter(ROWS, -5), null)
  check('an empty list', rowAtCenter([], 10), null)

  console.log(`\n${failures.length
    ? 'FAILED: ' + failures.join(', ') : 'all checks passed'}`)
  process.exit(failures.length ? 1 : 0)
}

void main()
