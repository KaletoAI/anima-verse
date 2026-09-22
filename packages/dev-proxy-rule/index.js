/**
 * The ONE rule of a Vite dev server in this repository: what Vite answers
 * itself, everything else goes to the backend.
 *
 * Both browser apps run their own dev server (`frontend` on :5173, `client3d`
 * on :5183) against the same FastAPI backend, so both need the same rule.
 * It lives here for the reason every other package under `packages/` exists:
 * it was written twice and the two copies drifted — `client3d` still forwarded
 * a hand-kept list of sixteen prefixes, one of which (`/state`) had no route
 * behind it any more while ~14 prefixes its own code calls were missing.
 *
 * Plain JavaScript on purpose — a `vite.config.ts` imports it by RELATIVE path
 * (so no workspace link and no build step is needed; esbuild inlines it into
 * the bundled config), and `scripts/smoke_vite_proxy.py` runs it through
 * `node`, so the guard checks the very function the dev servers use. It must
 * stay dependency-free (node builtins only).
 *
 * WHY INVERTED. A dev server used to forward an explicit LIST of backend
 * prefixes. A prefix missing from that list does not 404: Vite answers the
 * API call with its own HTML and a 200, `res.json()` fails and the component
 * blows up far from the cause. Such a list stood at ten (frontend) and sixteen
 * (client3d) entries against the ~38 route prefixes the pages call, and single
 * entries had long gone dead. A list of API paths can only rot; the set of
 * paths VITE owns is small, fixed and known per app.
 *
 * WHAT VITE OWNS
 *   /@…            its dev namespaces: /@vite/client, /@react-refresh,
 *                  /@id/…, /@fs/… (this is how the workspace packages
 *                  @anima/player-ui and @anima/scene-render are served)
 *   /__…           /__open-in-editor, /__vite_ping and friends
 *   /src/…         the source tree
 *   /node_modules/…  dependencies and the optimizer cache (/node_modules/.vite)
 *   the HTML entries and the public/ files — those two differ per app and are
 *   therefore PARAMETERS (`entries`, `publicDir`), not constants.
 * The HMR websocket is not a path question: the proxy entry sets no `ws`, so
 * the upgrade never reaches it.
 *
 * THE PAGE/API COLLISION. In production the player PAGE is `/play` and the
 * player API lives under `/play/…` (`/play/say`, `/play/locations/…/scene`).
 * In dev the page is the Vite entry `play.html`. So an entry `x.html` is
 * served at `/x.html`, `/x` and `/x/` (exactly — nothing after the slash) and
 * every deeper `/x/…` goes to the backend. `index.html` additionally answers
 * `/`. Aliases cover what does not follow from a file name, e.g. the
 * Game-Admin page `/game-admin` → `index.html`. That also makes the backend's
 * login redirect work in dev: the auth gate answers a navigation with
 * `302 /play?return=…`, the browser follows it on :5173 and lands on the dev
 * page instead of the built bundle.
 *
 * Note that `/static/…` is a BACKEND path in both apps (the frontend's HTML
 * entries link the theme CSS and the favicon from there, and the shared
 * `BelongingsPanel` falls back to `/static/game_admin/silhouette.svg`).
 * Nothing of Vite lives under it in dev, because `base` is `/` while a dev
 * server runs. `frontend/public/silhouette.svg` is addressed by the
 * components as `/static/game_admin/silhouette.svg` and therefore comes from
 * the backend's committed build in dev; Vite serves it at `/silhouette.svg`,
 * which is why `public/` is part of the rule at all.
 */
import { readdirSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

/** Path prefixes that belong to Vite's dev server, never to the backend. */
export const VITE_PREFIXES = ['/@', '/__', '/src/', '/node_modules/']

/** A directory given as URL, file: URL string or path -> a URL ending in `/`. */
function asDirUrl(dir) {
  const url = dir instanceof URL
    ? dir
    : String(dir).startsWith('file:') ? new URL(String(dir)) : pathToFileURL(String(dir))
  return url.href.endsWith('/') ? url : new URL(url.href + '/')
}

/**
 * Request path (without query) -> the HTML entry Vite serves for it.
 *
 * `entries` are the file names of the app's Vite entries (the same list as
 * `build.rollupOptions.input`), `aliases` the extra request paths that do not
 * follow from a file name.
 */
export function htmlEntryMap(entries, aliases = {}) {
  const map = {}
  for (const file of entries) {
    const path = '/' + file
    map[path] = path
    if (file === 'index.html') {
      map['/'] = path
    } else {
      const stem = '/' + file.slice(0, -'.html'.length)
      map[stem] = path
      map[stem + '/'] = path
    }
  }
  return { ...map, ...aliases }
}

const _publicCache = new Map()

/** The files under `publicDir`, as the URL paths Vite serves them at. */
export function publicPaths(publicDir) {
  const dir = asDirUrl(publicDir)
  const hit = _publicCache.get(dir.href)
  if (hit) return hit
  const walk = (at, base) => {
    const out = []
    let entries
    try {
      entries = readdirSync(at, { withFileTypes: true })
    } catch {
      return out // no public/ directory — nothing to keep
    }
    for (const e of entries) {
      if (e.isDirectory()) out.push(...walk(new URL(e.name + '/', at), base + e.name + '/'))
      else out.push('/' + base + e.name)
    }
    return out
  }
  const paths = new Set(walk(dir, ''))
  _publicCache.set(dir.href, paths)
  return paths
}

/**
 * The rule, bound to one app.
 *
 * Returns a function of the request URL that answers with the path Vite
 * should serve, or `null` when the request belongs to the backend. `null` is
 * what the Vite `bypass` hook wants for "proxy this": only a string (serve it)
 * and `false` (404) are special to it.
 */
export function createDevTarget({ publicDir, entries, aliases = {} }) {
  const htmlEntries = htmlEntryMap(entries, aliases)
  return function viteDevTarget(url) {
    const q = url.indexOf('?')
    const pathname = q === -1 ? url : url.slice(0, q)
    const search = q === -1 ? '' : url.slice(q)
    const entry = htmlEntries[pathname]
    if (entry) return entry + search
    if (VITE_PREFIXES.some((p) => pathname.startsWith(p))) return url
    if (publicPaths(publicDir).has(pathname)) return url
    return null
  }
}
