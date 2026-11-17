/**
 * useGarment's poll answer (review 12#4, frontend/src/tabs/characters/useGarment.ts → garmentPollAnswer), pinned by hand:
 *
 *   The hook polls one garment/hair info route while a step runs (`garment.running_step`) or accepted images are
 *   re-gated (`garment.regate_checking` non-empty). The rule per answer:
 *     answer {data: running}                 → info = that data, error '', again true
 *     answer {data: re-gating, nothing runs} → info = that data, error '', again true
 *     answer {data: idle}                    → info = that data, error '', again false (the chain stops)
 *     answer {data: null} (no URL)           → info null, error '', again false
 *     answer {error: 'HTTP 502'}             → info UNDEFINED (= keep the last good answer), error 'HTTP 502',
 *                                              again true (the run may still go; the next answer decides)
 *     answer {error: ''}                     → error 'request failed' (a failure is never shown as "no error")
 *   The old tick turned a failed GET into `setInfo(null)` and, since null is neither running nor re-gating,
 *   ended the chain: the dialog fell back to "Loading…" (unmounting its viewer and live drafts) and never polled
 *   again — i.e. old behaviour on {error} = {info: null, again: false}, which the two error rows reject.
 *
 * Usage: node scripts/smoke_garment_poll_answer.mjs   (no server, no world; bundles the module with esbuild,
 *        React / @anima/player-ui / the API client stubbed — only the pure function runs)
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
let failures = 0
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${ok ? '' : ` — got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`}`)
  if (!ok) failures++
}

const STUBS = {
  react: 'export const useCallback = () => {}, useEffect = () => {}, useRef = () => ({}), useState = () => [];',
  '@anima/player-ui': 'export const syncHub = () => ({ onTopics: () => () => {} });',
  '../../lib/api': 'export const apiGet = async () => null, apiPost = async () => null;',
}
const stubPlugin = {
  name: 'stubs',
  setup(build) {
    build.onResolve({ filter: /^(react|@anima\/player-ui|\.\.\/\.\.\/lib\/api)$/ }, (a) => ({ path: a.path, namespace: 'stub' }))
    build.onLoad({ filter: /.*/, namespace: 'stub' }, (a) => ({ contents: STUBS[a.path], loader: 'js' }))
  },
}

const dir = await mkdtemp(join(tmpdir(), 'garment-poll-'))
try {
  const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
  const built = await esbuild.build({
    entryPoints: [join(ROOT, 'frontend/src/tabs/characters/useGarment.ts')],
    bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error', plugins: [stubPlugin],
  })
  const file = join(dir, 'garment.mjs')
  await writeFile(file, built.outputFiles[0].text, 'utf8')
  const G = await import(`file://${file}`)
  const shape = (r) => ({ kept: r.info === undefined, info: r.info ?? null, error: r.error, again: r.again })

  const running = { garment: { running_step: 'mesh' } }
  const regating = { garment: { running_step: null, regate_checking: ['front'] } }
  const idle = { garment: { running_step: null, regate_checking: [] } }

  console.log('[1] answers')
  check('running → shown, polls on', shape(G.garmentPollAnswer({ data: running })),
    { kept: false, info: running, error: '', again: true })
  check('re-gating → shown, polls on', shape(G.garmentPollAnswer({ data: regating })),
    { kept: false, info: regating, error: '', again: true })
  check('idle → shown, stops', shape(G.garmentPollAnswer({ data: idle })),
    { kept: false, info: idle, error: '', again: false })
  check('no URL → null, stops', shape(G.garmentPollAnswer({ data: null })),
    { kept: false, info: null, error: '', again: false })

  console.log('[2] a failed GET')
  check('HTTP 502 → last answer kept, error shown, polls on', shape(G.garmentPollAnswer({ error: 'HTTP 502' })),
    { kept: true, info: null, error: 'HTTP 502', again: true })
  check('empty message → still an error', G.garmentPollAnswer({ error: '' }).error, 'request failed')
} finally {
  await rm(dir, { recursive: true, force: true })
}
console.log(failures ? `FAILED: ${failures}` : 'all OK')
process.exit(failures ? 1 : 0)
