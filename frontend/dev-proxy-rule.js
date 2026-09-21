/**
 * The ONE rule of the dev server: what Vite answers itself, everything else
 * goes to the backend.
 *
 * Plain JavaScript on purpose — `vite.config.ts` imports it, and
 * `scripts/smoke_vite_proxy.py` runs it through `node` without a build step,
 * so the guard checks the very function the dev server uses. It must stay
 * dependency-free (node builtins only).
 *
 * WHY INVERTED. The dev server used to forward an explicit LIST of backend
 * prefixes. A prefix missing from that list does not 404: Vite answers the
 * API call with its own HTML and a 200, `res.json()` fails and the component
 * blows up far from the cause. The list was ten entries against ~38 route
 * prefixes the two pages call, and two of its entries (`/activities`,
 * `/scheduler`) had no route behind them any more. A list of API paths can
 * only rot; the set of paths VITE owns is small, fixed and known here.
 *
 * WHAT VITE OWNS
 *   /@…            its dev namespaces: /@vite/client, /@react-refresh,
 *                  /@id/…, /@fs/… (this is how the workspace packages
 *                  @anima/player-ui and @anima/scene-render are served)
 *   /__…           /__open-in-editor, /__vite_ping and friends
 *   /src/…         the source tree
 *   /node_modules/…  dependencies and the optimizer cache (/node_modules/.vite)
 *   the HTML entries and the public/ files (see below)
 * The HMR websocket is not a path question: the proxy entry sets no `ws`, so
 * the upgrade never reaches it.
 *
 * THE PAGE/API COLLISION. In production the player PAGE is `/play` and the
 * player API lives under `/play/…` (`/play/say`, `/play/locations/…/scene`).
 * In dev the page is the Vite entry `play.html`. So `/play` and `/play/`
 * (exactly — nothing after the slash) are served as `play.html` and every
 * deeper `/play/…` goes to the backend. Same for `/game-admin` → `index.html`.
 * That also makes the backend's login redirect work in dev: the auth gate
 * answers a navigation with `302 /play?return=…`, the browser follows it on
 * :5173 and lands on the dev page instead of the built bundle.
 *
 * Note that `/static/…` is a BACKEND path here (the theme CSS and the favicon
 * both HTML entries link). Nothing of Vite lives under it in dev, because
 * `base` is `/` while the dev server runs and only the build uses
 * `/static/game_admin/`. The one public file, `silhouette.svg`, is addressed
 * by the components as `/static/game_admin/silhouette.svg` and therefore comes
 * from the backend's committed build in dev; Vite serves it at
 * `/silhouette.svg`, which is why `public/` is part of the rule at all.
 */
import { readdirSync } from 'node:fs'

/** Path prefixes that belong to Vite's dev server, never to the backend. */
export const VITE_PREFIXES = ['/@', '/__', '/src/', '/node_modules/']

/** Request path (without query) -> the HTML entry Vite serves for it. */
export const HTML_ENTRIES = {
  '/': '/index.html',
  '/index.html': '/index.html',
  '/game-admin': '/index.html',
  '/game-admin/': '/index.html',
  '/play.html': '/play.html',
  '/play': '/play.html',
  '/play/': '/play.html',
}

let _publicPaths = null

/** The files under `frontend/public/`, as the URL paths Vite serves them at. */
export function publicPaths() {
  if (_publicPaths) return _publicPaths
  const walk = (dir, base) => {
    const out = []
    let entries
    try {
      entries = readdirSync(dir, { withFileTypes: true })
    } catch {
      return out // no public/ directory — nothing to keep
    }
    for (const e of entries) {
      if (e.isDirectory()) out.push(...walk(new URL(e.name + '/', dir), base + e.name + '/'))
      else out.push('/' + base + e.name)
    }
    return out
  }
  _publicPaths = new Set(walk(new URL('./public/', import.meta.url), ''))
  return _publicPaths
}

/**
 * The rule. Returns the path Vite should serve, or `null` when the request
 * belongs to the backend.
 *
 * `null` is what the Vite `bypass` hook wants for "proxy this": only a string
 * (serve it) and `false` (404) are special to it.
 */
export function viteDevTarget(url) {
  const q = url.indexOf('?')
  const pathname = q === -1 ? url : url.slice(0, q)
  const search = q === -1 ? '' : url.slice(q)
  const entry = HTML_ENTRIES[pathname]
  if (entry) return entry + search
  if (VITE_PREFIXES.some((p) => pathname.startsWith(p))) return url
  if (publicPaths().has(pathname)) return url
  return null
}
