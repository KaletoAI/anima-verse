# `frontend/` — the React SPA (Game-Admin + Player UI)

One Vite project that builds **two pages** into `../static/game_admin/`, which FastAPI serves
directly:

| Entry | Built file | Served at | What it is |
|---|---|---|---|
| `index.html` → `src/main.tsx` | `static/game_admin/index.html` | `/game-admin` | **Game-Admin** — world building in 20 tabs |
| `play.html` → `src/player/main.tsx` | `static/game_admin/play.html` | `/play` | **Player UI** — the game itself |

`vite.config.ts` sets `base: '/static/game_admin/'`, so the hashed asset URLs resolve for both
pages. The Python routes (`app/routes/game_admin.py`, `app/routes/play.py`) only hand out the built
shell with a `no-cache` header — they contain no markup, so a UI change needs no server restart,
only a rebuild.

**The built output is committed.** A source checkout runs without Node at all; a change here is only
finished once `npm run build` has been run and `static/game_admin/` is part of the commit. If both
admin views look wrong while the 3D client looks right, the bundle is stale.

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

The dev server proxies API calls to the Python server on `:8000` (list in `vite.config.ts`). The
Game-Admin page is opened directly at `http://localhost:5173/`, the player page at
`http://localhost:5173/play.html`.

> **A missing proxy prefix does not 404.** Vite answers with its own `index.html`, so the caller
> gets `200` + HTML, `res.json()` fails and `apiGet` resolves to `null` — which then explodes deep
> inside a component. The forwarded list in `vite.config.ts` is shorter than the set of prefixes
> the two pages actually call, so parts of the app only work when served by FastAPI on `:8000`.
> Sweep both sides before relying on the dev server:
>
> ```bash
> grep -rohE "api(Get|Post|Put|Delete)\(\s*[\`'\"]/[a-zA-Z0-9_-]+" frontend/src | sed -E "s/.*[\`'\"]//" | sort -u
> grep -rohE "[\`'\"]/[a-zA-Z0-9_-]+" packages/player-ui/src/*.tsx | sort -u
> ```

## Layout

```
src/
  main.tsx, App.tsx      # Game-Admin shell (tab bar, header, freeze/sleep toggles, game clock)
  tabs/                  # one directory per Game-Admin tab; the list is tabs/registry.ts
  player/                # the /play surface: main.tsx, PlayerApp.tsx, panelRegistry.ts,
                         # the panels that are specific to the tiled layout, player.css
  components/            # shared admin widgets (Field, ListPane, dialogs, pickers, …)
  help/                  # the right-hand side-panel dock: help, prompt help, translate
  lib/                   # AuthGate, api (re-export), toast, formatting and hooks
  i18n/                  # a re-export of the shared provider
  styles/game-admin.css  # admin-only styles
```

**Adding a tab** means one entry in `src/tabs/registry.ts` (`id`, English `label`, `Component`) —
nothing else registers it. **Adding a player panel** means one entry in
`src/player/panelRegistry.ts` (`PANEL_META` for the launcher, `DEFAULT_LAYOUT` for its box); a panel
bound to a skill package carries `requires: '<skill id>'` and disappears together with the package.

Shared with the 3D client: the player panels and their plumbing come from
[`@anima/player-ui`](../packages/README.md), and everything geometric from `@anima/scene-render`.
`src/lib/api.ts` and `src/i18n/I18nProvider.tsx` are thin re-exports of the package, so both
surfaces use the identical client and provider. New player-facing UI belongs in the package unless
it is specific to the tiled layout.

## Conventions

- **Modals inside the `/play` react-grid-layout must be rendered with `createPortal` to
  `document.body`**, or they come up as an empty floating window.
- **No `window.prompt` / `alert` / `confirm`** — build real in-app UI (`ConfirmDialog`,
  `PromptDialog`).
- **Strings are English at the source** and looked up with `useI18n().t('English source')`. A
  missing translation logs `[i18n] missing [<lang>]: <source>` once per (lang, source) pair at
  `console.debug`; translation maps live in `shared/languages/<lang>.json` (currently `de.json`) and
  are reloaded by the server on restart.
- **Character settings render generically from templates** (`shared/templates/character/*.json` via
  `TemplateTab` / `TemplateField`) — never hardcode a field list or a per-feature form.
- Theme variables come from `static/themes/base.css` and `dark.css`, loaded as `<link>` tags in both
  HTML entries.

## Stack

- Vite 8 + `@vitejs/plugin-react` 6, TypeScript 5.6, ESLint 10 (flat config in
  `eslint.config.js`).
- React 18 + `react-grid-layout` for the player tiles, `three` for the admin's floor-plan preview
  (lazy-loaded, and only ever passed into `@anima/scene-render`, never imported by it).
- No state-management framework — `useState` / `useReducer` only. No UI framework.
- `tsc -b` type-checks `src` through the project references in `tsconfig.json`; the imported package
  sources are checked along with it.
