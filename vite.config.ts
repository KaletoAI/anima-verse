import { defineConfig } from 'vite';

const target = process.env.ANIMA_API ?? 'http://localhost:8000';
const proxied = ['/auth', '/play', '/world', '/characters', '/state', '/events', '/assets'];

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 5183,
    proxy: Object.fromEntries(
      proxied.map((p) => [p, { target, changeOrigin: true }])
    ),
  },
});
