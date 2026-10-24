# `frontend/` — the Game-Admin React SPA

One Vite project builds `index.html` → `src/main.tsx` into
`static/game_admin/index.html`, served by FastAPI at `/game-admin`.
The player is the separate `client3d/` workspace, served at `/play`.

`vite.config.ts` uses `base: '/static/game_admin/'` in builds and `/` in dev.
The Python route (`app/routes/game_admin.py`) serves the built shell with a
`no-cache` header. A UI change needs a rebuild and a browser reload.
**Built output is committed** so a source checkout runs without Node.

## Workspace

The repository root is the npm workspace root (`frontend`, `client3d`, `packages/*`) — **one**
`npm install` at the root covers everything. Do not run `npm install` inside `frontend/`.

```bash
npm install                  # once, at the repository ROOT

npm run dev:admin            # = npm run dev -w frontend — Vite on http://localhost:5173/
npm run build:admin          # = tsc -b && vite build → ../static/game_admin/
npm run lint -w frontend     # the ONLY lint script; runs from the root and covers
                             # frontend/ + packages/player-ui/src + packages/scene-render/src
```

**The dev server forwards everything it does not serve itself** to the Python server on
`:8000` (`ANIMA_API` overrides the address) — there is no list of API prefixes any more, because a
list can only rot and a missing entry does not 404: Vite would answer the call with its own HTML and
a `200`, `res.json()` would fail and the component would blow up far from the cause. The rule is the
shared one of [`packages/dev-proxy-rule/`](../packages/README.md) (client3d's dev server uses it
too), bound to this app's pages in `frontend/dev-proxy-rule.js`. The few paths
Vite keeps: its own namespaces (`/@…`, `/__…`), `/src/…`,
`/node_modules/…`, the `public/` files, `index.html`, `/` and `/game-admin`.
`/play` and every `/play/…` API request go to the backend.
`scripts/smoke_vite_proxy.py` guards every backend route and the single catch-all proxy rule.

> `/static/…` stays a backend path in dev, including the theme CSS and favicon.

## Layout

```
src/
  main.tsx, App.tsx      # Game-Admin shell (tab bar, header, freeze/sleep toggles, game clock)
  tabs/                  # one directory per Game-Admin tab; the list is tabs/registry.ts
  components/            # shared admin widgets (Field, ListPane, dialogs, pickers, …)
  help/                  # the right-hand side-panel dock: help, prompt help, translate
  lib/                   # AuthGate, api (re-export), toast, formatting and hooks
  i18n/                  # a re-export of the shared provider
  styles/game-admin.css  # admin-only styles
```

**Adding a tab** means one entry in `src/tabs/registry.ts` (`id`, English `label`, `Component`) —
nothing else registers it. Player panels belong in `@anima/player-ui`; their HUD
registration is in `client3d/src/hud/Hud.tsx`, including skill requirements.

Character forms and shared UI come from [`@anima/player-ui`](../packages/README.md),
and geometry from `@anima/scene-render`. `src/lib/api.ts` and
`src/i18n/I18nProvider.tsx` re-export the shared API client and provider.

## Conventions

- **Render HUD modals with `createPortal` to `document.body`** so they escape panel layout constraints.
- **No `window.prompt` / `alert` / `confirm`** — build real in-app UI (`ConfirmDialog`,
  `PromptDialog`).
- **Strings are English at the source** and looked up with `useI18n().t('English source')`. A
  missing translation logs `[i18n] missing [<lang>]: <source>` once per (lang, source) pair at
  `console.debug`; translation maps live in `shared/languages/<lang>.json` (currently `de.json`) and
  are reloaded by the server on restart. React and server strings forwarded through `t(en, lang)`
  are the only translatable surfaces — the Python-rendered admin pages and the config schema are
  English-only, and `scripts/smoke_i18n_orphans.py` fails on a `de.json` key without a live source.
- **Character settings render generically from templates** (`shared/templates/character/*.json` via
  `TemplateTab` / `TemplateField`) — never hardcode a field list or a per-feature form.
- Theme variables come from `static/themes/base.css` and `dark.css`, loaded as `<link>` tags in the
  HTML entry.

## Stack

- Vite 8 + `@vitejs/plugin-react` 6, TypeScript 5.6, ESLint 10 (flat config in
  `eslint.config.js`).
- React 18, `three` for the admin's floor-plan preview
  (lazy-loaded, and only ever passed into `@anima/scene-render`, never imported by it).
- No state-management framework — `useState` / `useReducer` only. No UI framework.
- `tsc -b` type-checks `src` through the project references in `tsconfig.json`; the imported package
  sources are checked along with it.
