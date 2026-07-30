import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.ANIMA_API ?? 'http://localhost:8000';
// Backend prefixes the dev server forwards. Besides the client's own calls
// (/auth /play /world /characters /state /events /assets) this covers every
// prefix the @anima/player-ui panels touch (endpoint sweep, E2-T5):
// /play (scene/say/self/others/…), /characters (also portrait/library image
// URLs), /chat (image upload + library), /inventory (gift picker), /queue
// (queue status feed), /i18n (translations).
const proxied = [
  '/auth', '/play', '/world', '/characters', '/state', '/events', '/assets',
  '/chat', '/inventory', '/queue', '/i18n',
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
