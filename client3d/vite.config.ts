import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.ANIMA_API ?? 'http://localhost:8000';
// Backend prefixes the dev server forwards. Besides the client's own calls
// (/auth /play /world /characters /state /events /assets) this covers every
// prefix the @anima/player-ui panels touch: /play (scene/say/self/others/…),
// /characters (also portrait/library image URLs, memory + knowledge), /chat
// (image upload + library), /inventory (gift picker), /queue (queue status
// feed), /i18n (translations), /diary (MindPanel's diary section), /instagram
// (the feed panel and its post images) and /static (the silhouette fallback in
// BelongingsPanel).
//
// A MISSING prefix does not 404 — Vite answers with its SPA index.html, so the
// caller gets 200 + HTML, `res.json()` fails and `apiGet` resolves to null,
// which then explodes somewhere deep in a component (that is exactly how
// /diary was found: "Cannot read properties of null (reading 'entries')").
// `api.ts` now names that case, but the list still has to be complete. When a
// panel moves into the package, sweep it:
//   grep -ohE "[\`'\"]/[a-zA-Z0-9_-]+" packages/player-ui/src/*.tsx | sort -u
const proxied = [
  '/auth', '/play', '/world', '/characters', '/state', '/events', '/assets',
  '/chat', '/inventory', '/queue', '/i18n', '/diary', '/instagram', '/static',
];

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // Multi-page: ship the diagnostic and preview pages as well
      input: {
        main: 'index.html',
        figureTest: 'figure-test.html',
        floorplan: 'floorplan.html',
        webgpuSmoke: 'webgpu-smoke.html',
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5183,
    proxy: Object.fromEntries(
      proxied.map((p) => [p, { target, changeOrigin: true }])
    ),
  },
});
