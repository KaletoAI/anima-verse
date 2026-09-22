/**
 * This app's dev-proxy rule: the shared rule of
 * `packages/dev-proxy-rule/index.js` bound to the 3D client's pages.
 *
 * Why a file of its own instead of the parameters sitting in
 * `vite.config.ts`: `scripts/smoke_vite_proxy.py` imports THIS module with
 * `node` and checks the exported function. A parameterisation that only
 * existed inside the config could drift away from the one the guard tests.
 *
 * `import.meta.url` points at this directory — also when Vite bundles the
 * config, because it inlines this file into a temporary module next to
 * `vite.config.ts` and defines `import.meta.url` to that path. Both ways
 * `./public/` is `client3d/public/`, which holds `/models/manifest.json` and
 * the test meshes: those must stay Vite's, they have no backend route.
 *
 * The entries are the three of `build.rollupOptions.input`. This client has
 * no `play.html`, so `/play` and `/play/…` are backend API here, as are
 * `/game-admin` and `/static/…` (the shared `BelongingsPanel` falls back to
 * `/static/game_admin/silhouette.svg`).
 */
import { createDevTarget } from '../packages/dev-proxy-rule/index.js'

export const ENTRIES = ['index.html', 'figure-test.html', 'floorplan.html']

/** The path Vite serves for a request, or `null` when it is the backend's. */
export const viteDevTarget = createDevTarget({
  publicDir: new URL('./public/', import.meta.url),
  entries: ENTRIES,
})
