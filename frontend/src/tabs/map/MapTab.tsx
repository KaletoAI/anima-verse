import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ExportButton, ImportButton } from '../../components/ImportExport'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'
import { FitDialog } from './FitDialog'
import { EdgeDialog } from './EdgeDialog'
import { SurfaceTexturesDialog } from './SurfaceTexturesDialog'

/**
 * Map tab — replaces the placement UI that used to live on the main
 * worldmap. The list-detail layout matches the other tabs: a tray on
 * the left with unplaced + passable templates, a 2D grid on the right
 * where locations are dropped onto cells.
 *
 * Drag payloads:
 *   "tmpl:<id>"  – passable template, drop on grid → POST clone at (x,y)
 *   "loc:<id>"   – existing location, drop on grid → PATCH position
 *                  (drop on tray → PATCH to (-1,-1) or DELETE if clone)
 */

interface Location {
  id: string
  name: string
  passable?: boolean
  is_template?: boolean
  template_location_id?: string
  grid_x?: number | null
  grid_y?: number | null
  map_image_2d?: string
  map_rotation_2d?: number
  /** Multi-tile ground patch anchored (centred) on this cell — a gallery
   *  file of type map_3x3, drawn UNDER the per-cell tiles. */
  map_patch_2d?: string
  map_patch_span?: number
  /** The cell's own tile is switched off (no first-image fallback either). */
  map_image_off?: boolean
  description?: string
  image_prompt_map_2d?: string
}

interface GalleryResp {
  images?: string[]
  image_types?: Record<string, string>
}

const COLS = 10
const ROWS = 10
const CELL = 88

// Flat 2D map tile, hidden if none exists. The Map tab is a flat grid, so the 2D
// tiles are the natural fit. `cacheKey` lets a caller force a reload after the
// per-cell image was changed. Rotation is a display-only transform.
function MapIcon({ locId, className, cacheKey, rotation }: { locId: string; className: string; cacheKey?: string; rotation?: number }) {
  const [hidden, setHidden] = useState(false)
  useEffect(() => { setHidden(false) }, [cacheKey, locId])
  if (hidden) return null
  const base = `/world/locations/${encodeURIComponent(locId)}/map-icon-2d`
  const src = cacheKey ? `${base}?v=${encodeURIComponent(cacheKey)}` : base
  const style = rotation ? { transform: `rotate(${rotation}deg)` } : undefined
  return <img className={className} src={src} alt="" style={style} onError={() => setHidden(true)} />
}

// Multi-tile ground patch (gallery type map_3x3), drawn UNDER the cell grid.
// Hidden on 404; never intercepts the drag&drop pointers.
function MapPatchImg({ locId, left, top, size, cacheKey }: {
  locId: string; left: number; top: number; size: number; cacheKey?: string
}) {
  const [hidden, setHidden] = useState(false)
  useEffect(() => { setHidden(false) }, [cacheKey, locId])
  if (hidden) return null
  const base = `/world/locations/${encodeURIComponent(locId)}/map-patch-2d`
  const src = cacheKey ? `${base}?v=${encodeURIComponent(cacheKey)}` : base
  return (
    <img src={src} alt="" onError={() => setHidden(true)}
      style={{ position: 'absolute', left, top, width: size, height: size,
        objectFit: 'cover', borderRadius: 4, pointerEvents: 'none' }} />
  )
}

export function MapTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [locations, setLocations] = useState<Location[] | null>(null)
  const [dragPayload, setDragPayload] = useState<string | null>(null)
  const [dragOverCell, setDragOverCell] = useState<string | null>(null)
  const [trayDragOver, setTrayDragOver] = useState(false)
  const gridRef = useRef<HTMLDivElement | null>(null)

  // Per-cell image picker: which placed location's picker is open, its gallery,
  // and a per-location cache-buster so the icon reloads after a change.
  const [picker, setPicker] = useState<Location | null>(null)
  const [pickerGallery, setPickerGallery] = useState<GalleryResp | null>(null)
  const [iconVer, setIconVer] = useState<Record<string, number>>({})
  // Globaler Refresh-Tick: erzwingt EINMAL ein Neuladen ALLER Tiles (z.B. nach
  // Edge-Match, das auch den Nachbarn aendert). Pro Loc bleibt iconVer fuer
  // gezielte Refreshes (normale Gen / Fit).
  const [refreshTick, setRefreshTick] = useState(0)
  // Welche Galerie-Datei steht gerade zum Loeschen an (Inline-Bestaetigung, kein confirm()).
  const [delConfirm, setDelConfirm] = useState<string | null>(null)

  // Image generation from the cell-image dialog: ✨ = normal ImageGenDialog,
  // ⊞ = hardwired FitDialog (backend comes from the config).
  const [gen, setGen] = useState<{ loc: Location; type: 'map_2d' | 'map_3x3' } | null>(null)
  const [fit, setFit] = useState<{ loc: Location } | null>(null)
  const [edge, setEdge] = useState<{ loc: Location; available: Record<string, string> } | null>(null)
  const [showTextures, setShowTextures] = useState(false)
  // Inpaint backends (category=="inpaint") for the Fit/Edge selection + the
  // mapfit default prompts per family (prefill the prompt field).
  const [inpaintBackends, setInpaintBackends] = useState<{ name: string; family: string; prompt: string; terrainHint: boolean }[]>([])
  const [mapfitPrompts, setMapfitPrompts] = useState<Record<string, string>>({})
  const [mapfitDefault, setMapfitDefault] = useState('')
  useEffect(() => {
    apiGet<{
      mapfit_prompts?: Record<string, string>
      mapfit_imagegen_default?: string
      options?: Array<{ name?: string; category?: string; image_family?: string; prompt?: string; terrain_hint?: boolean }>
    }>('/world/imagegen-options')
      .then((d) => {
        setMapfitPrompts(d.mapfit_prompts || {})
        setMapfitDefault(d.mapfit_imagegen_default || '')
        // Inpaint targets: backends with category=="inpaint". terrain_hint decides
        // whether the dialog appends the dynamic terrain hint to the prompt.
        const inp = (d.options || [])
          .filter((o) => o.category === 'inpaint' && o.name)
          .map((o) => ({
            name: o.name as string,
            family: o.image_family || '', prompt: o.prompt || '',
            terrainHint: !!o.terrain_hint,
          }))
        setInpaintBackends(inp)
      })
      .catch(() => { /* ignore */ })
  }, [])

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ locations?: Location[] }>('/world/locations')
      setLocations(data.locations || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => {
    reload()
  }, [reload])

  // Clones share their template's gallery — load images from the owner
  // (template_location_id when a clone, else the location itself). The chosen
  // image is stored on the placed location/clone (loc.id) so each cell differs.
  const ownerOf = (loc: Location) => (loc.template_location_id || '').trim() || loc.id

  const openPicker = useCallback(async (loc: Location) => {
    setPicker(loc)
    setPickerGallery(null)
    setDelConfirm(null)
    try {
      const g = await apiGet<GalleryResp>(`/world/locations/${encodeURIComponent(ownerOf(loc))}/gallery`)
      setPickerGallery(g)
      // Kein „Auto"-Modus: hat die Zelle noch kein festes Map-Bild, sofort das
      // erste verfuegbare zuordnen — so ist die Auswahl immer konkret (Zaehlung).
      if (!(loc.map_image_2d || '').trim()) {
        const firstMap = (g.images || []).find((f) => (g.image_types || {})[f] === 'map_2d')
        if (firstMap) {
          await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-image`, { type: 'map_2d', file: firstMap })
          setIconVer((v) => ({ ...v, [loc.id]: (v[loc.id] || 0) + 1 }))
          setPicker((p) => (p && p.id === loc.id ? { ...p, map_image_2d: firstMap } : p))
          void reload()
        }
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setPickerGallery({ images: [], image_types: {} })
    }
  }, [reload, t, toast])

  const chooseImage = useCallback(
    async (loc: Location, type: 'map_2d', file: string) => {
      try {
        await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-image`, { type, file })
        setIconVer((v) => ({ ...v, [loc.id]: (v[loc.id] || 0) + 1 }))
        await reload()
        setPicker(null)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  // Set/clear the 3x3 patch anchored at this cell. The backend toggles the
  // own tile of every covered same-template cell (off on set, back on when
  // cleared) — refresh everything, several tiles change at once.
  const choosePatch = useCallback(
    async (loc: Location, file: string) => {
      try {
        const r = await apiPatch<{ affected?: string[] }>(
          `/world/locations/${encodeURIComponent(loc.id)}/map-patch`, { file, span: 3 })
        const n = (r.affected || []).length
        toast(file
          ? t('Patch set — {n} covered tiles hidden').replace('{n}', String(n))
          : t('Patch removed — {n} tiles restored').replace('{n}', String(n)))
        setRefreshTick((k) => k + 1)
        await reload()
        setPicker(null)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  // Per-cell switch: hide/show the cell's own tile (map_image_off).
  const toggleImageOff = useCallback(
    async (loc: Location, off: boolean) => {
      try {
        await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-image-off`, { off })
        setIconVer((v) => ({ ...v, [loc.id]: (v[loc.id] || 0) + 1 }))
        await reload()
        setPicker((p) => (p && p.id === loc.id ? { ...p, map_image_off: off } : p))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  // Galerie-Bild loeschen (Backend raeumt haengende map_image_2d-Referenzen selbst
  // auf). Danach Galerie + Locations neu laden und den offenen Picker auffrischen,
  // damit die Auswahl-Markierung stimmt, falls das geloeschte Bild gewaehlt war.
  const deleteImage = useCallback(
    async (owner: string, file: string) => {
      try {
        await apiDelete(`/world/locations/${encodeURIComponent(owner)}/gallery/${encodeURIComponent(file)}`)
        const g = await apiGet<GalleryResp>(`/world/locations/${encodeURIComponent(owner)}/gallery`)
        setPickerGallery(g)
        const data = await apiGet<{ locations?: Location[] }>('/world/locations')
        const locs = data.locations || []
        setLocations(locs)
        setPicker((p) => (p ? locs.find((l) => l.id === p.id) || p : p))
        toast(t('Image deleted'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [t, toast],
  )

  // Default-Prompt fuer Map-Icons: nur der Subjekt-Teil (Stil-Suffix haengt der
  // Dialog/Server an). Subjekt aus image_prompt_map_2d, sonst Beschreibung/Name.
  const buildDefaultPrompt = useCallback((loc: Location): string => {
    return (loc.image_prompt_map_2d || '').trim() || (loc.description || loc.name || '').trim()
  }, [])

  // Kein PERIODISCHER Auto-Refresh (stört das Editieren). Stattdessen: nach einer
  // erfolgreichen Generierung EINMAL gezielt das/die betroffene(n) Tile(s) neu
  // laden. Die Gen ist fire-and-forget (POST liefert track_id, Bild kommt async)
  // → den Track via /queue/status bis Endzustand pollen, dann Cache-Buster bumpen.
  const bumpIcons = useCallback((ids: string[]) => {
    setIconVer((v) => {
      const next = { ...v }
      for (const id of ids) next[id] = (next[id] || 0) + 1
      return next
    })
  }, [])

  const watchAndRefresh = useCallback(async (trackId: string, locIds: string[], all = false) => {
    if (!trackId) return
    const deadline = Date.now() + 4 * 60 * 1000  // Map-Gens koennen dauern
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2500))
      let status: string | null = null
      try {
        const s = await apiGet<{
          recent?: Array<{ task_id: string; status: string }>
          recent_tasks?: Array<{ task_id: string; status: string }>
        }>('/queue/status')
        const hit = [...(s.recent || []), ...(s.recent_tasks || [])].find((x) => x.task_id === trackId)
        if (hit) status = hit.status
      } catch { /* weiter pollen */ }
      if (status) {  // Endzustand erreicht
        if (status === 'completed') {
          if (all) setRefreshTick((n) => n + 1)
          else bumpIcons(locIds)
        }
        return
      }
    }
  }, [bumpIcons])

  // ✨ Normale Generierung aus dem Cell-image-Dialog. POST an die ZELLE (loc.id),
  // Klone speichern ins geteilte Template, die Auswahl bleibt pro Zelle.
  const submitGen = useCallback(
    async (payload: ImageGenSubmit, target: { loc: Location; type: 'map_2d' | 'map_3x3' }) => {
      const body: Record<string, unknown> = { prompt_type: target.type, prompt: payload.prompt }
      if (payload.backend) body.backend = payload.backend
      if (payload.loras) body.loras = payload.loras
      if (payload.prompt_settings_applied) body.settings_applied = true
      try {
        const r = await apiPost<{ track_id?: string }>(
          `/world/locations/${encodeURIComponent(target.loc.id)}/gallery`, body)
        toast(t('Image queued'))
        void watchAndRefresh(r?.track_id || '', [target.loc.id])
      } catch (e) { toast(t('Error') + ': ' + (e as Error).message, 'error') }
    },
    [t, toast, watchAndRefresh],
  )

  // ⊞ Fit to neighbors — prompt_type/fit + the edited directional prompt.
  // settings_applied=true: the server appends neither style suffix nor hint again.
  const submitFit = useCallback(
    async (prompt: string, backend: string, loc: Location) => {
      const body: Record<string, unknown> = { prompt_type: 'map_2d', prompt, fit_neighbors: true, settings_applied: true }
      // Chosen inpaint backend (category=="inpaint"); empty = server default.
      if (backend) body.backend = backend
      try {
        const r = await apiPost<{ track_id?: string }>(
          `/world/locations/${encodeURIComponent(loc.id)}/gallery`, body)
        toast(t('Image queued'))
        void watchAndRefresh(r?.track_id || '', [loc.id])
      } catch (e) { toast(t('Error') + ': ' + (e as Error).message, 'error') }
    },
    [t, toast, watchAndRefresh],
  )

  // ⧉ Match edges — same mapfit inpaint backend, but frame mask + transition
  // prompt only for the selected sides. Center = existing tile.
  const submitEdge = useCallback(
    async (sides: string[], prompt: string, backend: string, loc: Location) => {
      const body: Record<string, unknown> = {
        prompt_type: 'map_2d', prompt, edge_match: true, edge_sides: sides, settings_applied: true,
      }
      if (backend) body.backend = backend
      try {
        const r = await apiPost<{ track_id?: string }>(
          `/world/locations/${encodeURIComponent(loc.id)}/gallery`, body)
        toast(t('Image queued'))
        // Edge betrifft auch den Nachbarn → alle Tiles einmal refreshen.
        void watchAndRefresh(r?.track_id || '', [loc.id], true)
      } catch (e) { toast(t('Error') + ': ' + (e as Error).message, 'error') }
    },
    [t, toast, watchAndRefresh],
  )

  // Rotate the cell's 2D icon by +90° (0→90→180→270→0). Display-only.
  const rotateCell = useCallback(
    async (loc: Location) => {
      const next = ((loc.map_rotation_2d || 0) + 90) % 360
      try {
        await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-rotation`, { rotation: next })
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  const { placedByCell, unplaced, passableTemplates, patchAnchors, coveredCells } = useMemo(() => {
    const byCell = new Map<string, Location>()
    const unp: Location[] = []
    const tmpls: Location[] = []
    for (const loc of locations || []) {
      const isClone = !!(loc.template_location_id || '').trim()
      const isPassableTemplate = !!loc.passable && !isClone
      if (isPassableTemplate) {
        tmpls.push(loc)
        continue
      }
      if (
        loc.grid_x != null &&
        loc.grid_y != null &&
        loc.grid_x >= 0 &&
        loc.grid_y >= 0
      ) {
        byCell.set(`${loc.grid_x},${loc.grid_y}`, loc)
      } else {
        unp.push(loc)
      }
    }
    // 3x3 patches: anchors sorted stably (y, then x) so overlapping patches
    // paint deterministically; covered cells render transparent so the patch
    // below shows through.
    const anchors = Array.from(byCell.values())
      .filter((l) => (l.map_patch_2d || '').trim())
      .sort((a, b) => ((a.grid_y as number) - (b.grid_y as number))
        || ((a.grid_x as number) - (b.grid_x as number)))
    const covered = new Set<string>()
    for (const l of anchors) {
      const r = Math.floor(Math.max(1, l.map_patch_span || 3) / 2)
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          covered.add(`${(l.grid_x as number) + dx},${(l.grid_y as number) + dy}`)
        }
      }
    }
    return { placedByCell: byCell, unplaced: unp, passableTemplates: tmpls,
      patchAnchors: anchors, coveredCells: covered }
  }, [locations])

  const onDropOnCell = useCallback(
    async (gridX: number, gridY: number) => {
      const payload = dragPayload
      setDragPayload(null)
      setDragOverCell(null)
      if (!payload) return
      const cellKey = `${gridX},${gridY}`
      const occupant = placedByCell.get(cellKey)
      try {
        if (payload.startsWith('tmpl:')) {
          if (occupant) return
          const templateId = payload.slice(5)
          await apiPost(
            `/world/locations/${encodeURIComponent(templateId)}/clone`,
            { grid_x: gridX, grid_y: gridY },
          )
        } else if (payload.startsWith('loc:')) {
          const locId = payload.slice(4)
          if (occupant && occupant.id !== locId) return
          await apiPatch(
            `/world/locations/${encodeURIComponent(locId)}/position`,
            { grid_x: gridX, grid_y: gridY },
          )
        }
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [dragPayload, placedByCell, reload, t, toast],
  )

  const onDropOnTray = useCallback(async () => {
    const payload = dragPayload
    setDragPayload(null)
    setTrayDragOver(false)
    if (!payload || !payload.startsWith('loc:')) return
    const locId = payload.slice(4)
    const loc = (locations || []).find((l) => l.id === locId)
    if (!loc) return
    const isClone = !!(loc.template_location_id || '').trim()
    try {
      if (isClone) {
        await apiDelete(`/world/locations/${encodeURIComponent(locId)}`)
      } else {
        await apiPatch(
          `/world/locations/${encodeURIComponent(locId)}/position`,
          { grid_x: -1, grid_y: -1 },
        )
      }
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [dragPayload, locations, reload, t, toast])

  const onCellDragOver = useCallback(
    (e: React.DragEvent, gridX: number, gridY: number) => {
      if (!dragPayload) return
      const cellKey = `${gridX},${gridY}`
      const occupant = placedByCell.get(cellKey)
      // Block drop if cell occupied by someone else (template clone target)
      if (dragPayload.startsWith('tmpl:') && occupant) return
      if (dragPayload.startsWith('loc:')) {
        const draggedId = dragPayload.slice(4)
        if (occupant && occupant.id !== draggedId) return
      }
      e.preventDefault()
      e.dataTransfer.dropEffect = dragPayload.startsWith('tmpl:') ? 'copy' : 'move'
      setDragOverCell(cellKey)
    },
    [dragPayload, placedByCell],
  )

  const startDragLoc = useCallback((e: React.DragEvent, loc: Location) => {
    const payload = `loc:${loc.id}`
    e.dataTransfer.setData('text/plain', payload)
    e.dataTransfer.effectAllowed = 'move'
    setDragPayload(payload)
  }, [])

  const startDragTmpl = useCallback((e: React.DragEvent, loc: Location) => {
    const payload = `tmpl:${loc.id}`
    e.dataTransfer.setData('text/plain', payload)
    e.dataTransfer.effectAllowed = 'copy'
    setDragPayload(payload)
  }, [])

  const onTrayDragOver = useCallback(
    (e: React.DragEvent) => {
      if (!dragPayload || !dragPayload.startsWith('loc:')) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      setTrayDragOver(true)
    },
    [dragPayload],
  )

  if (locations == null) {
    return <div className="ga-empty">{t('Loading…')}</div>
  }

  return (
    <div className="ga-map-layout">
      <aside
        className={'ga-map-tray' + (trayDragOver ? ' drag-over' : '')}
        onDragOver={onTrayDragOver}
        onDragLeave={() => setTrayDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          onDropOnTray()
        }}
      >
        <div className="ga-map-tray-section">
          <div
            className="ga-map-tray-title"
            style={{ display: 'flex', alignItems: 'center', gap: 4, justifyContent: 'space-between' }}
          >
            <span>{t('Layout')}</span>
            <span style={{ display: 'flex', gap: 4 }}>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => setShowTextures(true)}
                title={t('Global ground textures for terrain tiles in the 3D client (AV3D-13)')}
              >
                🧱
              </button>
              <ExportButton
                endpoint="/world/map/export"
                filename="map_layout.zip"
                title={t('Download grid positions as a ZIP')}
              />
              <ImportButton
                endpoint="/world/map/import"
                onImported={() => reload()}
                title={t('Apply a saved layout to the current world')}
              />
            </span>
          </div>
        </div>
        <div className="ga-map-tray-section">
          <div className="ga-map-tray-title">{t('Unplaced')}</div>
          {unplaced.length === 0 ? (
            <div className="ga-map-tray-empty">{t('None')}</div>
          ) : (
            <div className="ga-map-tray-items">
              {unplaced.map((loc) => (
                <div
                  key={loc.id}
                  className="ga-map-tray-item"
                  draggable
                  onDragStart={(e) => startDragLoc(e, loc)}
                  onDragEnd={() => setDragPayload(null)}
                  title={loc.name}
                >
                  <MapIcon locId={loc.id} className="ga-map-tray-icon" />
                  <span className="ga-map-tray-name">{loc.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ga-map-tray-section">
          <div className="ga-map-tray-title">{t('Passable templates')}</div>
          {passableTemplates.length === 0 ? (
            <div className="ga-map-tray-empty">{t('None')}</div>
          ) : (
            <div className="ga-map-tray-items">
              {passableTemplates.map((loc) => (
                <div
                  key={loc.id}
                  className="ga-map-tray-item ga-map-tray-template"
                  draggable
                  onDragStart={(e) => startDragTmpl(e, loc)}
                  onDragEnd={() => setDragPayload(null)}
                  title={t('Drag onto map to place a copy')}
                >
                  <MapIcon locId={loc.id} className="ga-map-tray-icon" />
                  <span className="ga-map-tray-name">{loc.name}</span>
                  <span className="ga-map-tray-stamp">∞</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ga-map-tray-hint">
          {t('Drop a placed location here to remove it from the grid.')}
        </div>
      </aside>

      <div className="ga-map-grid-wrap" ref={gridRef}>
        {/* Relative wrapper: the 3x3 patches sit absolutely BELOW the grid
            (DOM order) and span cell+gap strides; covered cells go
            transparent so the patch shows through. */}
        <div style={{ position: 'relative', width: 'max-content' }}>
          {patchAnchors.map((l) => {
            const span = Math.max(1, l.map_patch_span || 3)
            const r = Math.floor(span / 2)
            return (
              <MapPatchImg
                key={`patch-${l.id}`}
                locId={l.id}
                left={((l.grid_x as number) - r) * (CELL + 2)}
                top={((l.grid_y as number) - r) * (CELL + 2)}
                size={span * CELL + (span - 1) * 2}
                cacheKey={`${iconVer[l.id] || 0}.${refreshTick}`}
              />
            )
          })}
        <div
          className="ga-map-grid"
          style={{
            gridTemplateColumns: `repeat(${COLS}, ${CELL}px)`,
            gridTemplateRows: `repeat(${ROWS}, ${CELL}px)`,
          }}
        >
          {Array.from({ length: ROWS }).map((_, y) =>
            Array.from({ length: COLS }).map((__, x) => {
              const cellKey = `${x},${y}`
              const loc = placedByCell.get(cellKey)
              const isClone = !!(loc && (loc.template_location_id || '').trim())
              const dragOver = dragOverCell === cellKey
              const covered = coveredCells.has(cellKey)
              const cls = [
                'ga-map-cell',
                loc ? 'occupied' : '',
                loc?.passable ? 'passable' : '',
                isClone ? 'clone' : '',
                dragOver ? 'drag-over' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <div
                  key={cellKey}
                  className={cls}
                  style={covered ? { background: 'transparent' } : undefined}
                  onDragOver={(e) => onCellDragOver(e, x, y)}
                  onDragLeave={() => {
                    if (dragOverCell === cellKey) setDragOverCell(null)
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    onDropOnCell(x, y)
                  }}
                >
                  {loc ? (
                    <div
                      className="ga-map-tile"
                      draggable
                      onDragStart={(e) => startDragLoc(e, loc)}
                      onDragEnd={() => setDragPayload(null)}
                      title={loc.name + (isClone ? ' (' + t('copy') + ')' : '')}
                    >
                      {loc.map_image_off ? null : (
                        <MapIcon locId={loc.id} className="ga-map-tile-bg" cacheKey={`${iconVer[loc.id] || 0}.${refreshTick}`} rotation={loc.map_rotation_2d || 0} />
                      )}
                      <span className="ga-map-tile-name">{loc.name}</span>
                      <button
                        type="button"
                        className="ga-map-tile-rotbtn"
                        title={t('Rotate the 2D icon 90°')}
                        draggable={false}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          rotateCell(loc)
                        }}
                      >
                        ↻
                      </button>
                      <button
                        type="button"
                        className="ga-map-tile-imgbtn"
                        title={t('Choose which image this cell shows')}
                        draggable={false}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          openPicker(loc)
                        }}
                      >
                        🖼
                      </button>
                    </div>
                  ) : (
                    <span className="ga-map-cell-coord">
                      {x},{y}
                    </span>
                  )}
                </div>
              )
            }),
          )}
        </div>
        </div>
      </div>

      {picker ? (
        <div className="ga-modal-backdrop" onMouseDown={() => setPicker(null)}>
          <div className="ga-modal ga-map-imgpicker" onMouseDown={(e) => e.stopPropagation()}>
            <div className="ga-modal-header">
              <span>{t('Cell image')} — {picker.name}</span>
              <button className="ga-modal-close" onClick={() => setPicker(null)}>×</button>
            </div>
            <div className="ga-modal-body">
              {pickerGallery == null ? (
                <div className="ga-empty">{t('Loading…')}</div>
              ) : (
                ([
                  { type: 'map_2d' as const, label: t('2D icon'), chosen: picker.map_image_2d || '' },
                  { type: 'map_3x3' as const, label: t('3×3 patch'), chosen: picker.map_patch_2d || '' },
                ]).map(({ type, label, chosen }) => {
                  const imgs = (pickerGallery.images || []).filter(
                    (f) => (pickerGallery.image_types || {})[f] === type,
                  )
                  // Own tile picks the cell image; the 3x3 group anchors/clears
                  // the patch centred on this cell.
                  const pick = (f: string) =>
                    type === 'map_3x3' ? choosePatch(picker, f) : chooseImage(picker, type, f)
                  return (
                    <div key={type} className="ga-map-imgpicker-group">
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                        <div className="ga-map-imgpicker-label" style={{ marginBottom: 0 }}>{label}</div>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          {type === 'map_2d' ? (
                            <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.8em' }}
                              title={t('Off: the cell shows no own tile (an underlying 3×3 patch shows instead).')}>
                              <input
                                type="checkbox"
                                checked={!picker.map_image_off}
                                onChange={(e) => { void toggleImageOff(picker, !e.target.checked) }}
                              />
                              {t('Own tile')}
                            </label>
                          ) : null}
                          {type === 'map_3x3' && chosen ? (
                            <button
                              type="button"
                              className="ga-btn ga-btn-sm"
                              onClick={() => { void choosePatch(picker, '') }}
                              title={t('Remove the patch — covered tiles of this template are shown again.')}
                            >
                              ✕ {t('Remove patch')}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="ga-btn ga-btn-sm"
                            onClick={() => setGen({ loc: picker, type })}
                            title={t('Generate a new image for this cell')}
                          >
                            ✨ {t('Generate')}
                          </button>
                          {type === 'map_2d' ? (
                            <button
                              type="button"
                              className="ga-btn ga-btn-sm"
                              onClick={() => {
                                // Dialog SOFORT oeffnen — der (langsame, vision-
                                // basierte) Terrain-Hint wird im Dialog asynchron
                                // nachgeladen, sonst wirkt es, als ginge er nicht auf.
                                setFit({ loc: picker })
                              }}
                              title={t('Fit to neighbors: inpaint the tile so its edges continue the adjacent map cells')}
                            >
                              ⊞ {t('Fit to neighbors')}
                            </button>
                          ) : null}
                          {type === 'map_2d' ? (
                            <button
                              type="button"
                              className="ga-btn ga-btn-sm"
                              onClick={async () => {
                                // Verfügbare Nachbar-Seiten holen → Edge-Dialog (Seiten klickbar).
                                try {
                                  const r = await apiGet<{ sides?: Record<string, string> }>(
                                    `/world/locations/${encodeURIComponent(picker.id)}/edges`)
                                  const sides = r.sides || {}
                                  if (!Object.keys(sides).length) {
                                    toast(t('No neighbors with a tile.'), 'error')
                                    return
                                  }
                                  setEdge({ loc: picker, available: sides })
                                } catch (e) {
                                  toast(t('Error') + ': ' + (e as Error).message, 'error')
                                }
                              }}
                              title={t('Match edges: blend the tile edges into selected neighbors')}
                            >
                              ⧉ {t('Match edges')}
                            </button>
                          ) : null}
                        </div>
                      </div>
                      {imgs.length === 0 ? (
                        <div className="ga-map-tray-empty">{t('No images of this type.')}</div>
                      ) : (
                        <div className="ga-map-imgpicker-grid">
                          {imgs.map((f) => {
                            const owner = ownerOf(picker)
                            return (
                              <div key={f} className="ga-map-imgpicker-cell">
                                <button
                                  type="button"
                                  className={'ga-map-imgpicker-item' + (chosen === f ? ' selected' : '')}
                                  onClick={() => { void pick(f) }}
                                  title={f}
                                >
                                  <img
                                    src={`/world/locations/${encodeURIComponent(owner)}/gallery/${encodeURIComponent(f)}`}
                                    alt=""
                                  />
                                </button>
                                {delConfirm === f ? (
                                  <div className="ga-map-imgpicker-confirm">
                                    <span>{t('Delete?')}</span>
                                    <div className="ga-map-imgpicker-confirm-row">
                                      <button
                                        type="button"
                                        className="ga-btn ga-btn-sm ga-btn-danger"
                                        onClick={() => { setDelConfirm(null); deleteImage(owner, f) }}
                                      >
                                        {t('Delete')}
                                      </button>
                                      <button
                                        type="button"
                                        className="ga-btn ga-btn-sm"
                                        onClick={() => setDelConfirm(null)}
                                      >
                                        {t('Cancel')}
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <button
                                    type="button"
                                    className="ga-map-imgpicker-del"
                                    title={t('Delete image')}
                                    onClick={() => setDelConfirm(f)}
                                  >
                                    ×
                                  </button>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      ) : null}

      {gen ? (
        <ImageGenDialog
          open
          title={(gen.type === 'map_3x3'
            ? t('Generate 3×3 map tile — {name}')
            : t('Generate 2D icon — {name}')).replace('{name}', gen.loc.name)}
          defaultPrompt={buildDefaultPrompt(gen.loc)}
          styleUseCase="map"
          hideNegative
          onSubmit={(payload) => submitGen(payload, gen)}
          onClose={() => setGen(null)}
        />
      ) : null}

      {fit ? (
        <FitDialog
          title={t('Fit to neighbors — {name}').replace('{name}', fit.loc.name)}
          locId={fit.loc.id}
          canvasUrl={`/world/locations/${encodeURIComponent(fit.loc.id)}/fit-canvas`}
          backends={inpaintBackends}
          defaultBackend={mapfitDefault}
          mapfitPrompts={mapfitPrompts}
          onSubmit={(prompt, backend) => submitFit(prompt, backend, fit.loc)}
          onClose={() => setFit(null)}
        />
      ) : null}

      {edge ? (
        <EdgeDialog
          locId={edge.loc.id}
          locName={edge.loc.name}
          available={edge.available}
          rotation={edge.loc.map_rotation_2d || 0}
          backends={inpaintBackends}
          defaultBackend={mapfitDefault}
          mapfitPrompts={mapfitPrompts}
          onSubmit={(sides, prompt, backend) => submitEdge(sides, prompt, backend, edge.loc)}
          onClose={() => setEdge(null)}
        />
      ) : null}

      {showTextures ? (
        <SurfaceTexturesDialog onClose={() => setShowTextures(false)} />
      ) : null}
    </div>
  )
}
