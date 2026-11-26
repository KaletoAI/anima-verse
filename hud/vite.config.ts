import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteDevTarget } from './dev-proxy-rule.js';

// Where the dev server sends everything it does not serve itself. Same
// environment variable as the other apps' configs, so one name covers all.
const target = process.env.ANIMA_API ?? 'http://localhost:8000';

export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/hud/' : '/',
  plugins: [react()],
  build: {
    outDir: '../static/hud',
    emptyOutDir: true,
    rollupOptions: {
      // One page: the HUD. `dev-proxy-rule.js` keeps the same entry — it is
      // the page Vite answers in dev.
      input: {
        hud: 'hud.html',
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5184,
    proxy: {
      // ONE catch-all context, the same rule as the browser 3D scene: `dev-proxy-rule.js`
      // names the few paths VITE owns (its namespaces, the source tree, the
      // HTML entry, `public/`), and everything else is the backend's — a
      // missing prefix would not 404 but answer the API call with Vite's HTML.
      '^/': {
        target,
        changeOrigin: true,
        // No `ws`: the HMR websocket upgrade must stay with Vite.
        ws: false,
        bypass: (req) => viteDevTarget(req.url ?? '/'),
      },
    },
  },
}));
