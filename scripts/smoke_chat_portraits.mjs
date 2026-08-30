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
 * ── THE SIZE BOUNDS ─────────────────────────────────────────────────────
 * 520 x 260 minimum, 2400 x 2000 maximum (`chatPanel.ts` explains both ends).
 * Clamping is per axis; a stored value OUTSIDE the range is dropped, not
 * clamped — "nothing stored" is the only honest reading of noise.
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
    pickPortraitSpeakers, clampChatSize, readChatSize, writeChatSize,
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
  check('the narrator is skipped by the VERSION LIST, not by his name: '
    + 'version him and he is drawn',
        pickPortraitSpeakers(HISTORY, { ...VERSIONS, Storyteller: 's1' }, 3),
        ['Storyteller', 'Cara', 'Bea'])
  check('an objective row carries the name in `speaker`, not in `meta`',
        pickPortraitSpeakers([{ id: 1, speaker: 'Ayla' }], VERSIONS, 2), ['Ayla'])
  check('a row without any speaker is skipped',
        pickPortraitSpeakers([{ id: 1 }, { id: 2, meta: { speaker: 'Bea' } }],
                             VERSIONS, 2), ['Bea'])

  console.log('\n[2] the focus cuts the history short (hovering a line answers'
    + ' with the faces up to it)')
  check('focus 13, K=1 → Ayla', pickPortraitSpeakers(HISTORY, VERSIONS, 1, 13),
        ['Ayla'])
  check('focus 13, K=2 → Bea, Ayla',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, 13), ['Bea', 'Ayla'])
  check('focus 13, K=3 → still two: only Ayla and Bea have spoken by then',
        pickPortraitSpeakers(HISTORY, VERSIONS, 3, 13), ['Bea', 'Ayla'])
  check('focus 14 (a narrator row) answers with the faces behind it',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, 14), ['Bea', 'Ayla'])
  check('focus 10 (the first row, a narrator) → nothing has been said yet',
        pickPortraitSpeakers(HISTORY, VERSIONS, 3, 10), [])
  check('a focus id no longer in the history cuts nothing (= the resting state)',
        pickPortraitSpeakers(HISTORY, VERSIONS, 2, 999), ['Cara', 'Bea'])

  console.log('\n[3] size clamping: the drag stops at the bounds, per axis')
  check('dragged below the floor → the floor', clampChatSize(300, 100),
        { w: 520, h: 260 })
  check('dragged past the ceiling → the ceiling', clampChatSize(9999, 9999),
        { w: 2400, h: 2000 })
  check('inside the range it is kept, rounded to whole pixels',
        clampChatSize(700.4, 400.6), { w: 700, h: 401 })
  check('the axes are independent: narrow AND far too tall',
        clampChatSize(10, 5000), { w: 520, h: 2000 })
  check('exactly on the bounds is inside them',
        [clampChatSize(520, 260), clampChatSize(2400, 2000)],
        [{ w: 520, h: 260 }, { w: 2400, h: 2000 }])
  check('a drag that produced no number falls to the floor',
        clampChatSize(NaN, NaN), { w: 520, h: 260 })

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
