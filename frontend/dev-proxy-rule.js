/**
 * This app's dev-proxy rule: the shared rule of
 * `packages/dev-proxy-rule/index.js` bound to the Game-Admin page.
 *
 * Why a file of its own instead of the parameters sitting in
 * `vite.config.ts`: `scripts/smoke_vite_proxy.py` imports THIS module with
 * `node` and checks the exported function. A parameterisation that only
 * existed inside the config could drift away from the one the guard tests.
 *
 * `import.meta.url` points at this directory — also when Vite bundles the
 * config, because it inlines this file into a temporary module next to
 * `vite.config.ts` and defines `import.meta.url` to that path. Both ways
 * `./public/` is `frontend/public/`.
 *
 * The single entry is `index.html`, the Game-Admin (also at `/`).
 * `/game-admin` is its production path and is an explicit alias.
 * `/play` and `/play/…` are served by the backend.
 */
import { createDevTarget } from '../packages/dev-proxy-rule/index.js'

export const ENTRIES = ['index.html']

export const ALIASES = {
  '/game-admin': '/index.html',
  '/game-admin/': '/index.html',
}

/** The path Vite serves for a request, or `null` when it is the backend's. */
export const viteDevTarget = createDevTarget({
  publicDir: new URL('./public/', import.meta.url),
  entries: ENTRIES,
  aliases: ALIASES,
})
