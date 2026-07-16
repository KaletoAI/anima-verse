import { defineConfig } from 'vite';

const target = process.env.ANIMA_API ?? 'http://localhost:8000';
const proxied = ['/auth', '/play', '/world', '/characters', '/state', '/events', '/assets'];

export default defineConfig({
  build: {
    rollupOptions: {
      // Mehrseitig: Diagnose- und Vorschau-Seiten mit ausliefern
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
