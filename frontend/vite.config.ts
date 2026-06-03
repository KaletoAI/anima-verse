import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built assets are served by the FastAPI server out of static/game_admin/.
// Two pages share this output (same frontend/ project, separate pages/routes):
//   index.html -> Game-Admin SPA   (served at /game-admin)
//   play.html  -> Player UI        (served at /play)
// The matching base path makes the hashed asset URLs resolve under
// /static/game_admin/ for both.
export default defineConfig({
  plugins: [react()],
  base: '/static/game_admin/',
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
      // Backend endpoints — Vite dev server forwards them to FastAPI on :8000.
      // The dev page is opened directly via Vite at http://localhost:5173/.
      // In production the page is served at /game-admin by FastAPI.
      '/i18n': 'http://localhost:8000',
      '/activities': 'http://localhost:8000',
      '/rules': 'http://localhost:8000',
      '/inventory': 'http://localhost:8000',
      '/world': 'http://localhost:8000',
      '/world-dev': 'http://localhost:8000',
      '/scheduler': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/account': 'http://localhost:8000',
    },
  },
})
