/**
 * Does the Map tab's initial auto-fit actually fire?  (E2 final review,
 * finding 1 — the pane measurement never ran, so `pane` stayed {0,0} and both
 * the auto-fit and the "Fit view" button were dead.)
 *
 * Renders the REAL MapTab (bundled from source) into jsdom with a stubbed
 * API, a 800x600 pane and a ResizeObserver that reports once, then reads the
 * scale legend the canvas draws — its label is a pure function of the view's
 * pxPerM, so it says which view the tab settled on.
 *
 * Hand-derived expectations (frontend/src/tabs/map/mapMath.ts + MapCanvas.tsx):
 *   world_bounds {min_x 0, min_z 0, max_x 100, max_z 50}, pane 800x600,
 *   fitBounds margin 40 px:
 *     usableW = 800 - 80 = 720 ; usableH = 600 - 80 = 520
 *     spanX = 100 -> 7.2 px/m ; spanZ = 50 -> 10.4 px/m ; min -> 7.2 px/m
 *     clampZoom(0.05 .. 40) leaves 7.2
 *   legend: barM = niceDown(140 / 7.2 = 19.44) -> 10  =>  label "10 m"
 *   NOT fitted (FIT_FALLBACK_PX_PER_M = 4): niceDown(140 / 4 = 35) -> 20
 *                                                          =>  label "20 m"
 * So "10 m" proves the fit ran, "20 m" is exactly the broken state.
 *
 * jsdom is NOT a repo dependency — install it into a scratch directory and
 * point JSDOM_MODULE at it (default: the bare specifier, i.e. whatever node
 * resolves from the working directory / NODE_PATH).
 *
 * Usage:  JSDOM_MODULE=<scratch>/node_modules/jsdom/lib/api.js \
 *           node scripts/check_maptab_fit.mjs <bundle.mjs>
 */
const { JSDOM } = await import(process.env.JSDOM_MODULE || 'jsdom')

const bundle = process.argv[2]

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',
  { url: 'http://localhost/game-admin', pretendToBeVisual: true })
const { window } = dom

const FIXTURES = {
  '/world/locations': {
    locations: [{
      id: 'inn', name: 'Inn', pos_x: 10, pos_z: 10, yaw_deg: 0,
      map3d: { plan_width_m: 10 },
    }],
  },
  '/play/worldmap?all=1': {
    world_bounds: { min_x: 0, min_z: 0, max_x: 100, max_z: 50 },
  },
  '/play/terrain': { areas: [], default_kind: 'grass', sig: 'sig1' },
  '/world/terrain-types': {
    types: [{ kind: 'grass', name: 'Grass', color: '#448844' }], sources: {},
  },
}

const seen = []
window.fetch = async (path) => {
  seen.push(String(path))
  const body = FIXTURES[String(path)]
  return {
    ok: body !== undefined, status: body === undefined ? 404 : 200,
    url: String(path), headers: { get: () => 'application/json' },
    json: async () => (body === undefined ? { detail: 'not found' } : body),
  }
}

// Layout: jsdom has none, so every element reports the pane size.
window.Element.prototype.getBoundingClientRect = () => ({
  width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0,
  toJSON() { return this },
})
// A ResizeObserver that reports ONCE on observe — the real one does the same
// on the first frame after the element is attached.
window.ResizeObserver = class {
  constructor(cb) { this.cb = cb }
  observe() { this.cb([], this) }
  unobserve() {}
  disconnect() {}
}

for (const k of ['window', 'document', 'navigator', 'Element', 'HTMLElement',
  'SVGElement', 'Node', 'CustomEvent', 'Event', 'ResizeObserver', 'fetch',
  'requestAnimationFrame', 'cancelAnimationFrame', 'getComputedStyle',
  'sessionStorage', 'localStorage', 'MutationObserver']) {
  try {
    globalThis[k] = window[k]
  } catch {
    Object.defineProperty(globalThis, k, { value: window[k], configurable: true })
  }
}
globalThis.IS_REACT_ACT_ENVIRONMENT = false

await import(bundle)
globalThis.__mountMapTab(window.document.getElementById('root'))

// Let the mount effects, the four fetches and their state updates settle.
for (let i = 0; i < 40; i++) await new Promise((r) => setTimeout(r, 5))

const texts = [...window.document.querySelectorAll('svg text')]
  .map((n) => n.textContent.trim())
const legend = texts.find((s) => /^\d+(\.\d+)? m$/.test(s)) || '(none)'

const bodyText = window.document.body.textContent || ''
let fails = 0
const check = (label, actual, expected) => {
  const ok = actual === expected
  if (!ok) fails++
  console.log(`  ${ok ? '✓' : '✗'} ${label}: ${JSON.stringify(actual)}`
    + (ok ? '' : ` — expected ${JSON.stringify(expected)}`))
}

console.log('[0] the tab loaded and rendered its canvas')
// The four one-shot reads. They can run more than once — the callbacks depend
// on the i18n `t`, whose identity changes when the provider settles; that is
// pre-existing and not what this check is about.
check('all four endpoints read', new Set(seen).size, 4)
check('past the Loading placeholder', /Fit view/.test(bodyText), true)
check('canvas svg present', window.document.querySelectorAll('svg').length > 0, true)

console.log('[1] the initial auto-fit ran (pane was measured)')
check('scale legend', legend, '10 m')
check('not the unfitted fallback view', legend === '20 m', false)

console.log()
if (fails) { console.log(`FAILED ${fails}`); process.exit(1) }
console.log('OK — auto-fit fired on the first render')
