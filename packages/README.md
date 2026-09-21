# `packages/` — the shared workspaces

Two private npm workspaces that both browser apps of this repository depend on. They exist for one
reason: everything in here used to exist **twice**, once in `frontend/` and once in `client3d/`, and
the two copies drifted. What both apps need lives here; what is a matter of view state stays in each
app.

Neither package is published, bundled or built on its own. They are TypeScript sources consumed
through the workspace link (`"@anima/player-ui": "*"` in the consumer's `package.json`), so the
consuming app's Vite build compiles them and the consuming app's `tsc` type-checks them.

| Package | Directory | Consumed by |
|---|---|---|
| `@anima/player-ui` | `packages/player-ui/` | `frontend/` (the `/play` Player UI) and `client3d/` (the 3D HUD) |
| `@anima/scene-render` | `packages/scene-render/` | `frontend/` (the admin floor-plan preview) and `client3d/` (the 3D world) |

---

## `@anima/player-ui`

The player-facing React panels plus the plumbing they need: the API client, the i18n provider, the
toast, the polling hook and the queue hook.

Both player surfaces show the **same** panels. `/play` arranges them as tiles in a
react-grid-layout; the 3D client docks one column of them beside the world. Neither owns the panel —
this package does, so a fix lands in both at once.

Exports (`packages/player-ui/src/index.ts`):

- **Panels** — `ScenePanel` (chat), `SelfPanel`, `OthersPanel`, `BelongingsPanel` (inventory),
  `MindPanel` (+ `MindThoughtsSection`), `PhonePanel`, `NewsPanel`, `QuestsPanel`, `TaskPanel`,
  `GalleryPanel`, `InstagramPanel`, `PartyStrip`, `SceneView`, `ScenesRecap`.
- **Dialogs and pickers** — `ChatGalleryPicker`, `GiftPicker`, `PlayerPhotoDialog`, `Lightbox`,
  `ZoomButton`, `EmptyState`, `ErrorBoundary`, `Toast`.
- **Plumbing** — `api` (`apiGet`/`apiPost`/`apiDelete`, also available as the `./api` subpath),
  `I18nProvider` + `useI18n`, `usePolling`, `useQueue`, `thumbs`, `clockFormat`/`clockSettings`,
  `icons`.
- **Styles** — `@anima/player-ui/panels.css`. It is themeable: every colour is a CSS custom
  property, and each app brings its own theme (`frontend/src/player/player.css`,
  `client3d/src/hud/hud.css` + `theme-fantasy.css`, loaded after it).

Two conventions matter when touching a panel:

- **A panel bound to a skill declares it.** `PANEL_META` in `frontend/src/player/panelRegistry.ts`
  and `PANELS` in `client3d/src/hud/Hud.tsx` carry a `requires` field with a skill id (e.g.
  `instagram`, `send_message`). `GET /play/scene` reports the world's capabilities, and a panel
  whose skill package is not installed disappears from the launcher in **both** apps. That is what
  makes a package's deletion test hold all the way into the UI.
- **The package never imports an app.** It receives everything through props and the shared API
  client; `react` and `react-dom` are peer dependencies supplied by the consumer.

## `@anima/scene-render`

The geometric half of the 3D scene contract (`docs/schnittstellen-3d.md`, part B) — the code that
turns a scene payload into meshes. The server computes, the clients render, and "render" must mean
the same thing in the admin's floor-plan preview and in the 3D world, so there is exactly one
implementation of it:

- `place.ts` / `placeGeometry.ts` — the one `place()` routine of § B2.
- `clip.ts`, `layerCut.ts`, `depthCut.ts`, `cutouts.ts` — the room clip of § B1 (this is the piece
  that had demonstrably been written twice and had already drifted).
- `verify.ts` — the numeric diff of § B5a, which is how a 3D finding is argued here.
- `types.ts` — the payload types both renderers read.
- The rest is the shared vocabulary of the scene: `primitives`, `materials`, `slotMaterials`,
  `surface`, `storeyGround`, `groundAreas`, `stroke`, `scatter`/`scatterAxis`, `occupancy`,
  `figure`, `clipRetarget`, `leafPivot`, `mirrorSurface`, `hillshade`, `worldHeight`, `waterfall`.

`three` is a **peer dependency and is never imported by the package** — it is passed in as a
parameter. That keeps the admin's lazy loading of Three.js intact: the preview only pulls the
library when a user opens a floor plan.

**Deliberately not shared:** camera and LOD handling, fades, culling, labels, pathfinding, NPC
logic and editor overlays. View state belongs to each app. If a rendering bug is fixed in only one
renderer, the fix is in the wrong place — it belongs in the payload spec, in this package, or it is
genuinely view state.

---

## Working on them

```bash
npm install                  # once, at the repository ROOT (workspace root)

npm run lint -w frontend     # eslint over frontend/ + packages/player-ui/src + packages/scene-render/src
npm run build:admin          # tsc -b && vite build — type-checks player-ui through its imports
npm run build:client3d       # tsc --noEmit && vite build — the same for both packages
```

There is no `build` or `test` script inside either package, and none is wanted: a build step would
reintroduce a stale artefact between the source and its two consumers. Type errors surface in
whichever app imports the changed file, so **build both** after a change here — `npm run build` at
the root does exactly that.
