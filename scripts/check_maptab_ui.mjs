/**
 * The three remaining UI findings of the E2 final review, checked against the
 * REAL MapTab rendered into jsdom (same rig as check_maptab_fit.mjs).
 *
 *   middle   — finding 3: a MIDDLE-button press on the canvas must not count
 *              as a background click. In paint mode that click would drop a
 *              terrain vertex; the toolbar hint says how many the draft has,
 *              so it is the readout. Left button afterwards must still work.
 *   comment  — finding 4: the four `//` lines inside <g> in TerrainLayer were
 *              JSX TEXT, i.e. rendered into the SVG. With one area painted the
 *              document must not contain that comment text anywhere.
 *   typesfail— finding 5: when /world/terrain-types fails, the tab must say
 *              the CATALOG did not load (and that Reload is the way out)
 *              instead of "Pick a terrain type first", and the Reload button
 *              must clear the state once the endpoint answers again.
 *
 * jsdom is NOT a repo dependency — install it into a scratch directory and
 * point JSDOM_MODULE at it (default: the bare specifier, i.e. whatever node
 * resolves from the working directory / NODE_PATH).
 *
 * Usage:  JSDOM_MODULE=<scratch>/node_modules/jsdom/lib/api.js \
 *           node scripts/check_maptab_ui.mjs <bundle.mjs> middle|comment|typesfail
 */
const { JSDOM } = await import(process.env.JSDOM_MODULE || 'jsdom')

const bundle = process.argv[2]
const CASE = process.argv[3]

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',
  { url: 'http://localhost/game-admin', pretendToBeVisual: true })
const { window } = dom

const AREA = {
  id: 'a1', kind: 'grass', z_order: 0, meta: {},
  polygon: [[0, 0], [20, 0], [20, 20], [0, 20]],
}
const TYPES = {
  types: [{ kind: 'grass', name: 'Grass', color: '#448844' }], sources: {},
}
let typesFail = CASE === 'typesfail'

const fixtures = () => ({
  '/world/locations': { locations: [] },
  '/play/worldmap?all=1': {
    world_bounds: { min_x: 0, min_z: 0, max_x: 100, max_z: 50 },
  },
  '/play/terrain': {
    areas: CASE === 'comment' ? [AREA] : [], default_kind: 'grass', sig: 's',
  },
  '/world/terrain-types': typesFail ? undefined : TYPES,
})

const posted = []
window.fetch = async (path, init) => {
  if ((init?.method || 'GET') !== 'GET') { posted.push(String(path)); return {
    ok: true, status: 200, url: String(path),
    headers: { get: () => 'application/json' }, json: async () => ({}),
  } }
  const body = fixtures()[String(path)]
  return {
    ok: body !== undefined, status: body === undefined ? 500 : 200,
    url: String(path), headers: { get: () => 'application/json' },
    json: async () => (body === undefined ? { detail: 'boom' } : body),
  }
}

window.Element.prototype.getBoundingClientRect = () => ({
  width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0,
  toJSON() { return this },
})
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
  try { globalThis[k] = window[k] } catch {
    Object.defineProperty(globalThis, k, { value: window[k], configurable: true })
  }
}
globalThis.IS_REACT_ACT_ENVIRONMENT = false

const settle = async (n = 20) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 5))
}
const body = () => window.document.body.textContent || ''
const btn = (re) => [...window.document.querySelectorAll('button')]
  .find((b) => re.test(b.textContent || ''))
const click = async (el) => {
  el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, button: 0 }))
  await settle(6)
}
/** A press-and-release on the canvas with the given mouse button. */
const press = async (button) => {
  const box = window.document.querySelector('.ga-map-canvas-pane > div')
  const ev = (type, target) => target.dispatchEvent(new window.MouseEvent(type, {
    bubbles: true, button, clientX: 400, clientY: 300,
  }))
  ev('pointerdown', box)
  ev('pointerup', window)
  await settle(6)
}

let fails = 0
const check = (label, actual, expected) => {
  const ok = actual === expected
  if (!ok) fails++
  console.log(`  ${ok ? '✓' : '✗'} ${label}: ${JSON.stringify(actual)}`
    + (ok ? '' : ` — expected ${JSON.stringify(expected)}`))
}

await import(bundle)
globalThis.__mountMapTab(window.document.getElementById('root'))
await settle(40)

if (CASE === 'middle') {
  console.log('[3] the middle button pans, it never clicks')
  await click(btn(/Paint/))
  await click(btn(/Grass/))
  check('paint mode armed, draft empty',
    /Click the map to set the first point/.test(body()), true)
  await press(1)
  check('middle press left the draft alone',
    /Click the map to set the first point/.test(body()), true)
  check('no point from the middle button', /1 of \d+ points/.test(body()), false)
  await press(0)
  check('left press adds the vertex', /1 of \d+ points/.test(body()), true)
} else if (CASE === 'comment') {
  console.log('[4] the layer comment is a JSX comment, not rendered text')
  check('the area is drawn',
    window.document.querySelectorAll('svg path').length > 0, true)
  check('no leaked comment text', /evenodd, not SVG/.test(body()), false)
  check('no stray // in the svg',
    /\/\/ /.test(window.document.querySelector('svg').textContent || ''), false)
} else if (CASE === 'typesfail') {
  console.log('[5] a failed catalog says so — and Reload is the way out')
  await click(btn(/Paint/))
  check('says the catalog did not load',
    /Terrain types could not be loaded/.test(body()), true)
  check('does not blame the user',
    /Pick a terrain type first/.test(body()), false)
  typesFail = false
  await click(btn(/Reload/))
  await settle(20)
  check('after Reload the palette is back', /Grass/.test(body()), true)
  check('the error message is gone',
    /Terrain types could not be loaded/.test(body()), false)
} else {
  console.log('unknown case'); process.exit(2)
}

console.log()
if (fails) { console.log(`FAILED ${fails}`); process.exit(1) }
console.log(`OK — ${CASE}`)
