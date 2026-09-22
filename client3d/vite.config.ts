import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteDevTarget } from './dev-proxy-rule.js';

// Where the dev server sends everything it does not serve itself. Same
// environment variable as frontend's config, so one name covers both clients.
const target = process.env.ANIMA_API ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // Multi-page: ship the diagnostic and preview pages as well.
      // `dev-proxy-rule.js` keeps the same three entries — they are the pages
      // Vite answers in dev.
      input: {
        main: 'index.html',
        figureTest: 'figure-test.html',
        floorplan: 'floorplan.html',
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5183,
    proxy: {
      // ONE catch-all context (a `^`-prefixed key is matched as a regexp, and
      // every request path starts with `/`). There is deliberately no list of
      // backend prefixes any more — `dev-proxy-rule.js` names the few paths
      // VITE owns (its namespaces, the source tree, the three HTML entries,
      // `public/`), and everything else is the backend's. The old list was
      // sixteen prefixes against ~38 the client and the shared panels call,
      // and a missing prefix does not 404: Vite answers the API call with its
      // own HTML and a 200, `res.json()` fails and the error surfaces far
      // from the cause.
      '^/': {
        target,
        changeOrigin: true,
        // No `ws`: the HMR websocket upgrade must stay with Vite. Nothing in
        // the client opens a websocket to the backend (chat and the event
        // streams are plain HTTP/SSE), and those stream through untouched —
        // the proxy pipes the response, it does not buffer it.
        ws: false,
        bypass: (req) => viteDevTarget(req.url ?? '/'),
      },
    },
  },
});
