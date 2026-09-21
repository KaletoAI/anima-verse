import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteDevTarget } from './dev-proxy-rule.js'

// Built assets are served by the FastAPI server out of static/game_admin/.
// Two pages share this output (same frontend/ project, separate pages/routes):
//   index.html -> Game-Admin SPA   (served at /game-admin)
//   play.html  -> Player UI        (served at /play)
// The matching base path makes the hashed asset URLs resolve under
// /static/game_admin/ for both.
//
// In DEV the base is `/` instead. The dev server has to forward `/static/…`
// to the backend (both HTML entries link the theme CSS and the favicon from
// there), and it cannot do that while it serves its own files under the same
// prefix. `/` is also what the dev pages are documented as: the Game-Admin at
// http://localhost:5173/, the player at http://localhost:5173/play.
const PROD_BASE = '/static/game_admin/'

// Where the dev server sends everything it does not serve itself. Same
// environment variable as client3d's config, so one name covers both clients.
const backend = process.env.ANIMA_API ?? 'http://localhost:8000'

export default defineConfig(({ command, isPreview }) => ({
  plugins: [react()],
  base: command === 'serve' && !isPreview ? '/' : PROD_BASE,
  build: {
    outDir: '../static/game_admin',
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      // Relative paths resolve from the Vite root (this frontend/ dir).
      input: {
        index: 'index.html',
        play: 'play.html',
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // ONE catch-all context (a `^`-prefixed key is matched as a regexp, and
      // every request path starts with `/`). There is deliberately no list of
      // backend prefixes any more — `dev-proxy-rule.js` names the few paths
      // VITE owns, and everything else is the backend's. A new route can
      // therefore never again be answered by the dev server's own HTML.
      '^/': {
        target: backend,
        changeOrigin: true,
        // No `ws`: the HMR websocket upgrade must stay with Vite. Nothing in
        // the SPA opens a websocket to the backend (chat and the event
        // streams are plain HTTP/SSE), and those stream through untouched —
        // the proxy pipes the response, it does not buffer it.
        ws: false,
        // No `cookieDomainRewrite`: the session cookie is set without a
        // Domain and without `secure` over http, so the browser scopes it to
        // localhost:5173 by itself. Rewriting would only break it.
        bypass: (req) => viteDevTarget(req.url ?? '/'),
      },
    },
  },
}))
