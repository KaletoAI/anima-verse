/**
 * This app's dev-proxy rule: the shared rule of
 * `packages/dev-proxy-rule/index.js` bound to the HUD page.
 *
 * A file of its own (not parameters inside `vite.config.ts`) because
 * `scripts/smoke_vite_proxy.py` imports THIS module with `node` and checks the
 * exported function — a parameterisation only inside the config could drift
 * away from the one the guard tests.
 *
 * `./public/` is `hud/public/` (it must exist: `createDevTarget` refuses a
 * missing directory; it holds only `.gitkeep`). The entry matches
 * `build.rollupOptions.input`: `/hud.html` is Vite's, everything else —
 * `/play/…`, `/static/…`, the API — goes to the backend.
 */
import { createDevTarget } from '../packages/dev-proxy-rule/index.js'

export const ENTRIES = ['hud.html']

/** The path Vite serves for a request, or `null` when it is the backend's. */
export const viteDevTarget = createDevTarget({
  publicDir: new URL('./public/', import.meta.url),
  entries: ENTRIES,
})
