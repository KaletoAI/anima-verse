import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'
import { CLOSE_TOL_PX, fmtM } from '../world/planGeometry'
import { MapCanvas } from './MapCanvas'
import {
  FIT_FALLBACK_PX_PER_M, fitBounds, pointInPolygon, type MapBounds, type View,
} from './mapMath'
import {
  NO_ANCHOR_WIDTH_M, PlacementLayer, anchorWidthM, isPlaced, type GhostSpec,
} from './PlacementLayer'
import { TerrainLayer, typeColor } from './TerrainLayer'
import {
  MAX_COORD, MAX_POINTS, MAX_Z_ORDER, MIN_POINTS, TerrainAreaChip,
  TerrainToolbar, type TerrainMode,
} from './TerrainTools'
import { TerrainTypesDialog } from './TerrainTypesDialog'
import type {
  EditorLocation, TerrainArea, TerrainPayload, TerrainType, TerrainTypesResp,
  WorldmapPayload,
} from './mapTypes'

/**
 * Map tab — the editor of the free metre world.
 *
 * The grid is gone (Seamless World, E1/E2): a location is a square of edge
 * `map3d.plan_width_m` standing on a continuous plane at (`pos_x`, `pos_z`),
 * turned by `yaw_deg`. Placing means naming a point in METRES, not choosing a
 * cell, so nothing here counts columns and nothing drops onto a tile.
 *
 * Two reads, both one-shot (an editor that polls fights the hand that edits):
 *   - `GET /world/locations` — the full dicts. The tray lives off them: an
 *     unplaced location still carries its scale anchor in `map3d`, which the
 *     worldmap payload would report as `null`, and only these dicts know
 *     about templates and clones.
 *   - `GET /play/worldmap?all=1` — for `world_bounds` alone, to frame the
 *     first view. The reload button refetches both.
 *
 * Writing goes through three routes only: `PATCH .../position` (place, move,
 * turn, and — with null coordinates — unplace), `POST .../clone` (a template
 * instance at a point) and `DELETE /world/locations/{id}` (clones only, as
 * before). Re-placing shifts the occupants server-side, so the editor moves a
 * location without thinking about who stands inside it.
 *
 * Placing is click-arm-click, never HTML5 drag&drop: a tray entry arms a
 * ghost footprint that follows the cursor, the next click on the map commits
 * it, Escape cancels. The gesture works at any zoom and needs no drop target.
 *
 * The ground is edited on the same canvas, in three exclusive MODES: `select`
 * is everything above, `paint` collects vertices into a new terrain area and
 * `edit-area` works on the polygon of one existing area. A click on the map
 * means something different in each — which is precisely why the mode is a
 * visible switch and not something guessed from what happens to sit under the
 * cursor. Switching modes drops whatever the previous one had armed (ghost,
 * draft, selection), so no mode can act on the other's leftovers.
 *
 * Terrain reads from two endpoints and writes to one:
 *   - `GET /world/terrain-types` — the effective catalog, fetched ONCE. It is
 *     the single source of every colour and every palette entry here; the
 *     `types` block of `/play/terrain` carries the same catalog and stays
 *     unused, because two copies of one truth drift.
 *   - `GET /play/terrain` — `areas` (bottom-to-top) plus `default_kind`. Its
 *     `sig` is carried along and logged into the state, never polled: it is
 *     the signal a WATCHING client uses, and the hand that paints already
 *     knows when it changed something.
 *   - `POST/PUT/DELETE /world/terrain-areas` — one refetch after each write.
 */

interface GalleryResp {
  images?: string[]
  image_types?: Record<string, string>
}

/** Yaw controls: the fine step and the quarter turn. */
const YAW_FINE = 15
const YAW_QUARTER = 90

/** Snap step of the placement grid when the toggle is on (§ E2 brief). */
const SNAP_M = 10

const normYaw = (deg: number): number => ((deg % 360) + 360) % 360

/** The metre grid the server stores terrain vertices on (2 decimals). */
const r2 = (v: number): number => Math.round(v * 100) / 100

/** Mirror of the server's coordinate range — a point outside it is refused
 *  here so the user hears why instead of losing a click to a 400. */
const inRange = (x: number, z: number): boolean =>
  Math.abs(x) <= MAX_COORD && Math.abs(z) <= MAX_COORD

/** A world coordinate for the chip. `fmtM` decides its precision by
 *  magnitude, which a negative metre would defeat (−50 would print with two
 *  decimals, +50 with none) — the sign is therefore split off first. */
const fmtPos = (v: number): string => (v < 0 ? '-' : '') + fmtM(Math.abs(v))

/** Flat 2D map icon as an HTML thumbnail (tray). Hidden when the location has
 *  none — a broken image would claim the entry is misconfigured. The map
 *  itself draws the same URL as an SVG `<image>`, which needs no such guard. */
function MapIcon({ locId, className, cacheKey }: {
  locId: string; className: string; cacheKey?: string
}) {
  const [hidden, setHidden] = useState(false)
  useEffect(() => { setHidden(false) }, [cacheKey, locId])
  if (hidden) return null
  const base = `/world/locations/${encodeURIComponent(locId)}/map-icon-2d`
  const src = cacheKey ? `${base}?v=${encodeURIComponent(cacheKey)}` : base
  return <img className={className} src={src} alt="" onError={() => setHidden(true)} />
}

export function MapTab() {
  const { t } = useI18n()
  const { toast } = useToast()

  const [locations, setLocations] = useState<EditorLocation[] | null>(null)
  const [bounds, setBounds] = useState<MapBounds | null>(null)
  const [view, setView] = useState<View>({ cx: 0, cz: 0, pxPerM: FIT_FALLBACK_PX_PER_M })
  const [selId, setSelId] = useState('')
  const [snapOn, setSnapOn] = useState(true)
  const [ghost, setGhost] = useState<GhostSpec | null>(null)
  const [ghostPt, setGhostPt] = useState<{ x: number; z: number } | null>(null)
  const [yawDraft, setYawDraft] = useState('')
  const [delArmed, setDelArmed] = useState('')

  // Terrain: the mode of the canvas, the catalog, the painted areas, the
  // running draft and the selected area.
  const [mode, setMode] = useState<TerrainMode>('select')
  const [terrainTypes, setTerrainTypes] = useState<TerrainType[]>([])
  // Where each effective kind comes from — only the type manager needs it, and
  // it arrives in the same answer as the catalog, so it is kept here too.
  const [typeSources, setTypeSources] = useState<Record<string, 'shared' | 'world'>>({})
  // Did the catalog FAIL to load? Without this an empty `typeMap` is
  // indistinguishable from "you have not picked a type yet", and every write
  // gets refused with a hint the user cannot act on — the fix is Reload, not
  // a different click.
  const [typesError, setTypesError] = useState(false)
  const [typesOpen, setTypesOpen] = useState(false)
  const [terrain, setTerrain] = useState<TerrainPayload | null>(null)
  const [paintKind, setPaintKind] = useState('')
  const [draft, setDraft] = useState<Array<[number, number]>>([])
  const [draftCursor, setDraftCursor] = useState<{ x: number; z: number } | null>(null)
  const [selArea, setSelArea] = useState('')

  // Per-location cache-buster for the map icon (bumped after a change).
  const [iconVer, setIconVer] = useState<Record<string, number>>({})
  // Image picker: which location's picker is open plus its gallery, and which
  // gallery file is armed for deletion (inline confirmation, no confirm()).
  const [picker, setPicker] = useState<EditorLocation | null>(null)
  const [pickerGallery, setPickerGallery] = useState<GalleryResp | null>(null)
  const [delConfirm, setDelConfirm] = useState<string | null>(null)
  const [gen, setGen] = useState<EditorLocation | null>(null)

  // The canvas pane is measured here as well: `fitBounds` needs the pixel size
  // BEFORE the first view exists, and the size the canvas measures for itself
  // lives inside its own context.
  //
  // A CALLBACK REF, not a mount effect — and that is the whole point of it:
  // this tab renders a "Loading…" placeholder while `locations` is null, which
  // it ALWAYS is on the first commit, so the pane div does not exist yet when a
  // `useEffect(…, [])` would run. That effect read `null`, never attached the
  // observer and never ran again — `pane` stayed {0,0} forever, which killed
  // BOTH the initial auto-fit and the "Fit view" button (an enabled no-op).
  // A callback ref fires when the element actually enters the DOM, whenever
  // that is, and again with `null` on unmount.
  const [pane, setPane] = useState({ w: 0, h: 0 })
  const fittedRef = useRef(false)
  const paneObsRef = useRef<ResizeObserver | null>(null)

  const setPaneEl = useCallback((el: HTMLDivElement | null) => {
    paneObsRef.current?.disconnect()
    paneObsRef.current = null
    if (!el) return
    const read = () => {
      const r = el.getBoundingClientRect()
      setPane({ w: Math.round(r.width), h: Math.round(r.height) })
    }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    paneObsRef.current = ro
  }, [])

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ locations?: EditorLocation[] }>('/world/locations')
      setLocations(data.locations || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      return
    }
    // The frame is a nicety — a world without bounds still edits fine.
    try {
      const wm = await apiGet<WorldmapPayload>('/play/worldmap?all=1')
      setBounds(wm.world_bounds || null)
    } catch { /* keep the current frame */ }
  }, [t, toast])

  /** The painted ground. Called on mount, by the reload button and after every
   *  terrain write — never on a timer. */
  const reloadTerrain = useCallback(async () => {
    try {
      setTerrain(await apiGet<TerrainPayload>('/play/terrain'))
    } catch (e) {
      toast(t('Failed to load terrain') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => { void reload() }, [reload])
  useEffect(() => { void reloadTerrain() }, [reloadTerrain])

  /** The catalog. Read on mount and after every write of the type manager —
   *  never on a timer: it changes only when someone edits the types, and the
   *  palette plus every area colour follow from this one state. */
  const reloadTypes = useCallback(async () => {
    try {
      const r = await apiGet<TerrainTypesResp>('/world/terrain-types')
      setTerrainTypes(r.types || [])
      setTypeSources(r.sources || {})
      setTypesError(false)
    } catch (e) {
      toast(t('Failed to load terrain types') + ': ' + (e as Error).message, 'error')
      setTypesError(true)
    }
  }, [t, toast])

  useEffect(() => { void reloadTypes() }, [reloadTypes])

  /** Why a write has no usable kind. A catalog that never arrived is not the
   *  user picking the wrong thing, and "pick a type first" is unactionable
   *  when there is no palette to pick from — say what actually helps. */
  const noKindMsg = useCallback(() => (typesError
    ? t('Terrain types could not be loaded — retry via Reload')
    : t('Pick a terrain type first')), [t, typesError])

  /** The catalog by kind — what every colour lookup goes through. */
  const typeMap = useMemo(() => {
    const m: Record<string, TerrainType> = {}
    for (const ty of terrainTypes) m[ty.kind] = ty
    return m
  }, [terrainTypes])

  // A kind the type manager just removed must not stay armed — the next
  // painted ring would be posted with a kind the server no longer knows.
  useEffect(() => {
    if (paintKind && !typeMap[paintKind]) setPaintKind('')
  }, [paintKind, typeMap])

  // First frame: as soon as bounds AND a measured pane exist. Later reloads
  // keep the user's view — refitting under an edit would move the world away.
  useEffect(() => {
    if (fittedRef.current || !bounds || !pane.w || !pane.h) return
    fittedRef.current = true
    setView(fitBounds(bounds, pane.w, pane.h))
  }, [bounds, pane])

  const fitView = useCallback(() => {
    if (!bounds || !pane.w || !pane.h) return
    setView(fitBounds(bounds, pane.w, pane.h))
  }, [bounds, pane])

  // Escape cancels the armed ghost, then the running draft, then the selection.
  const ghostRef = useRef<GhostSpec | null>(null)
  ghostRef.current = ghost
  const draftRef = useRef<Array<[number, number]>>([])
  draftRef.current = draft
  // The loaded list as the write handlers see it — they run long after the
  // render that armed them, so they must not read a captured copy.
  const locationsRef = useRef<EditorLocation[]>([])
  locationsRef.current = locations || []
  const modeRef = useRef<TerrainMode>(mode)
  modeRef.current = mode
  const areasRef = useRef<TerrainArea[]>([])
  areasRef.current = terrain?.areas || []
  // Is a modal covering the canvas? The handler is bound once, so this cannot
  // be read from the state directly.
  const modalRef = useRef(false)
  modalRef.current = typesOpen || !!picker || !!gen
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // While a dialog is open, Escape is the reflex for CLOSING IT — and the
      // type manager is only reachable from paint mode, so acting on the
      // canvas here would silently throw away a half-drawn polygon behind a
      // window that stays open regardless. Not this handler's key.
      if (modalRef.current) return
      if (ghostRef.current) { setGhost(null); setGhostPt(null) } else if (draftRef.current.length) {
        setDraft([])
        setDraftCursor(null)
      } else { setSelId(''); setSelArea('') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /** Switching modes drops everything the previous mode had armed — an
   *  abandoned draft or a selection whose chip is no longer reachable would
   *  keep acting on clicks that now mean something else. */
  const switchMode = useCallback((m: TerrainMode) => {
    setMode(m)
    setGhost(null)
    setGhostPt(null)
    setDraft([])
    setDraftCursor(null)
    if (m !== 'select') setSelId('')
    if (m !== 'edit-area') setSelArea('')
  }, [])

  const snapV = useCallback((v: number) => (
    snapOn ? Math.round(v / SNAP_M) * SNAP_M : Math.round(v * 100) / 100
  ), [snapOn])

  // Only an armed ghost cares where the cursor is; without one this must not
  // re-render the tab on every mouse move. The point is SNAPPED here, not only
  // on the click: a preview that shows a spot the placement will not use is
  // worse than none (with the 10 m grid it can be off by up to 7.07 m).
  const onWorldMove = useCallback((x: number, z: number) => {
    if (ghostRef.current) setGhostPt({ x: snapV(x), z: snapV(z) })
    // Only a running draft needs the rubber band; without one this must not
    // re-render the tab on every mouse move.
    else if (draftRef.current.length) setDraftCursor({ x, z })
  }, [snapV])

  const { placed, unplaced, templates } = useMemo(() => {
    const pl: EditorLocation[] = []
    const un: EditorLocation[] = []
    const tm: EditorLocation[] = []
    for (const loc of locations || []) {
      const isClone = !!(loc.template_location_id || '').trim()
      // A template is a stamp, never a place on the map: a passable location
      // that is not itself a clone — its clones are what gets placed.
      if (!!loc.passable && !isClone) { tm.push(loc); continue }
      if (isPlaced(loc)) pl.push(loc)
      else un.push(loc)
    }
    return { placed: pl, unplaced: un, templates: tm }
  }, [locations])

  const selected = useMemo(
    () => (locations || []).find((l) => l.id === selId) || null,
    [locations, selId],
  )
  useEffect(() => {
    setYawDraft(selected ? String(normYaw(selected.yaw_deg || 0)) : '')
    setDelArmed('')
  }, [selected])

  // ── Writes ───────────────────────────────────────────────────────────────

  /** Optimistic patch of one location in the loaded list. */
  const patchLocal = useCallback((id: string, fields: Partial<EditorLocation>) => {
    setLocations((ls) => (ls || []).map((l) => (l.id === id ? { ...l, ...fields } : l)))
  }, [])

  const commitMove = useCallback(async (id: string, x: number, z: number) => {
    patchLocal(id, { pos_x: x, pos_z: z })
    try {
      await apiPatch(`/world/locations/${encodeURIComponent(id)}/position`,
        { pos_x: x, pos_z: z })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      void reload()
    }
  }, [patchLocal, reload, t, toast])

  /** Turning re-sends the position: the route reads a missing coordinate as
   *  "unplace", so a yaw-only body would take the location off the map. */
  const commitYaw = useCallback(async (loc: EditorLocation, deg: number) => {
    const yaw = normYaw(deg)
    if (!isPlaced(loc)) return
    patchLocal(loc.id, { yaw_deg: yaw })
    setYawDraft(String(yaw))
    try {
      await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/position`,
        { pos_x: loc.pos_x, pos_z: loc.pos_z, yaw_deg: yaw })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      void reload()
    }
  }, [patchLocal, reload, t, toast])

  const unplace = useCallback(async (loc: EditorLocation) => {
    try {
      await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/position`,
        { pos_x: null, pos_z: null })
      setSelId('')
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [reload, t, toast])

  const removeClone = useCallback(async (loc: EditorLocation) => {
    try {
      await apiDelete(`/world/locations/${encodeURIComponent(loc.id)}`)
      setSelId('')
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [reload, t, toast])

  /** The armed tray entry lands here: place the location itself, or stamp a
   *  clone of the template at the clicked point. */
  const placeGhost = useCallback(async (wx: number, wz: number) => {
    const g = ghostRef.current
    if (!g) return
    setGhost(null)
    setGhostPt(null)
    const x = snapV(wx)
    const z = snapV(wz)
    try {
      if (g.kind === 'clone') {
        // The server refuses a second clone of the same template on the very
        // same point and answers 200 with the EXISTING one — with the 10 m
        // snap two clicks land there easily, and without this the placement
        // would look like it simply did nothing. An id we already knew means
        // no new copy was made; say so and show which one is in the way.
        const knownBefore = new Set(locationsRef.current.map((l) => l.id))
        const r = await apiPost<{ location?: EditorLocation }>(
          `/world/locations/${encodeURIComponent(g.id)}/clone`, { pos_x: x, pos_z: z })
        const newId = r?.location?.id || ''
        await reload()
        setSelId(newId)
        if (newId && knownBefore.has(newId)) {
          toast(t('A copy already stands here'), 'error')
        }
      } else {
        await apiPatch(`/world/locations/${encodeURIComponent(g.id)}/position`,
          { pos_x: x, pos_z: z })
        await reload()
        setSelId(g.id)
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [reload, snapV, t, toast])

  // ── Terrain writes ───────────────────────────────────────────────────────

  const selectedArea = useMemo(
    () => (terrain?.areas || []).find((a) => a.id === selArea) || null,
    [terrain, selArea],
  )

  /** Optimistic patch of one area, so an edited outline does not snap back to
   *  its old shape for the length of the round trip. */
  const patchAreaLocal = useCallback((id: string, fields: Partial<TerrainArea>) => {
    setTerrain((tp) => (tp
      ? { ...tp, areas: tp.areas.map((a) => (a.id === id ? { ...a, ...fields } : a)) }
      : tp))
  }, [])

  /** Replace one existing area. The route is a FULL replace (kind, polygon,
   *  z_order, meta), so every field travels along — a body carrying only the
   *  changed one would blank the rest. The refetch afterwards runs whether the
   *  write worked or not: on 404 (someone else erased it) it is the repair.
   *
   *  That full body is why an area whose kind the catalog no longer knows
   *  cannot be reshaped: the server sanitizer checks `kind` FIRST and rejects
   *  the whole body before it ever looks at the polygon
   *  (`terrain.sanitize_area`). Every write therefore carries a KNOWN kind or
   *  does not leave. The surfaces disable themselves as well — this is the net
   *  under them, not the only guard, and it says what to do instead of
   *  letting a 400 come back as a stack trace. Changing the kind is exactly
   *  the write that rescues such an area, so the patch's kind wins. */
  const putArea = useCallback(async (area: TerrainArea, patch: Partial<TerrainArea>) => {
    const body = {
      kind: area.kind, polygon: area.polygon, z_order: area.z_order,
      meta: area.meta || {}, ...patch,
    }
    if (!typeMap[body.kind]) {
      toast(noKindMsg(), 'error')
      await reloadTerrain()
      return
    }
    try {
      await apiPut(`/world/terrain-areas/${encodeURIComponent(area.id)}`, body)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    await reloadTerrain()
  }, [noKindMsg, reloadTerrain, t, toast, typeMap])

  /**
   * Close the running ring into a new area.
   *
   * The draft is dropped only once the server has it. A polygon is a dozen
   * deliberate clicks; a connection blip or an expired session must not cost
   * them, so on failure the ring stays standing and `Close` can simply be
   * pressed again. The in-flight flag is what makes that safe: with the draft
   * still on screen a second close-click would otherwise post the same area
   * twice.
   */
  const draftBusyRef = useRef(false)
  const commitDraft = useCallback(async (pts: Array<[number, number]>) => {
    if (draftBusyRef.current) return
    if (pts.length < MIN_POINTS) {
      toast(t('An area needs at least {n} points').replace('{n}', String(MIN_POINTS)), 'error')
      return
    }
    draftBusyRef.current = true
    try {
      await apiPost('/world/terrain-areas', { kind: paintKind, polygon: pts })
      setDraft([])
      setDraftCursor(null)
      await reloadTerrain()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      draftBusyRef.current = false
    }
  }, [paintKind, reloadTerrain, t, toast])

  /** One click while painting: close the ring, or drop another vertex. */
  const addDraftPoint = useCallback((wx: number, wz: number) => {
    // While the ring is being saved the draft still stands (it is only dropped
    // once the server has it) — a vertex added now would be dropped with it.
    if (draftBusyRef.current) return
    if (!paintKind) { toast(noKindMsg(), 'error'); return }
    const x = r2(wx)
    const z = r2(wz)
    if (!inRange(x, z)) {
      toast(t('That point lies outside the world (±{n} m)')
        .replace('{n}', String(MAX_COORD)), 'error')
      return
    }
    const cur = draftRef.current
    // Closing is a click ON the first vertex, measured in PIXELS: the ring must
    // be equally easy to close at every zoom, and a metre tolerance would be
    // unreachable when zoomed out and hair-trigger when zoomed in.
    if (cur.length >= MIN_POINTS) {
      const tolM = CLOSE_TOL_PX / view.pxPerM
      if (Math.hypot(x - cur[0][0], z - cur[0][1]) <= tolM) {
        void commitDraft(cur)
        return
      }
    }
    if (cur.length >= MAX_POINTS) {
      toast(t('An area holds at most {n} points').replace('{n}', String(MAX_POINTS)), 'error')
      return
    }
    setDraft([...cur, [x, z]])
  }, [commitDraft, noKindMsg, paintKind, t, toast, view.pxPerM])

  const moveVertex = useCallback((i: number, x: number, z: number) => {
    const a = selectedArea
    if (!a || i < 0 || i >= a.polygon.length) return
    if (!inRange(x, z)) {
      // Nothing was patched locally yet, so refusing is the whole undo — the
      // layer's drag preview ended with the pointer that raised this.
      toast(t('That point lies outside the world (±{n} m)')
        .replace('{n}', String(MAX_COORD)), 'error')
      return
    }
    const poly = a.polygon.map((p, k) => (k === i ? [x, z] as [number, number] : p))
    patchAreaLocal(a.id, { polygon: poly })
    void putArea(a, { polygon: poly })
  }, [patchAreaLocal, putArea, selectedArea, t, toast])

  const deleteVertex = useCallback((i: number) => {
    const a = selectedArea
    if (!a || i < 0 || i >= a.polygon.length) return
    if (a.polygon.length <= MIN_POINTS) {
      toast(t('An area needs at least {n} points').replace('{n}', String(MIN_POINTS)), 'error')
      return
    }
    const poly = a.polygon.filter((_, k) => k !== i)
    patchAreaLocal(a.id, { polygon: poly })
    void putArea(a, { polygon: poly })
  }, [patchAreaLocal, putArea, selectedArea, t, toast])

  const insertVertex = useCallback((i: number, x: number, z: number) => {
    const a = selectedArea
    if (!a) return
    if (a.polygon.length >= MAX_POINTS) {
      toast(t('An area holds at most {n} points').replace('{n}', String(MAX_POINTS)), 'error')
      return
    }
    const poly = [...a.polygon]
    poly.splice(i, 0, [x, z])
    patchAreaLocal(a.id, { polygon: poly })
    void putArea(a, { polygon: poly })
  }, [patchAreaLocal, putArea, selectedArea, t, toast])

  const setAreaKind = useCallback((kind: string) => {
    const a = selectedArea
    if (!a || a.kind === kind) return
    patchAreaLocal(a.id, { kind })
    void putArea(a, { kind })
  }, [patchAreaLocal, putArea, selectedArea])

  /** "Bring forward" / "send back" is one layer, not a jump to the top: the
   *  areas around it keep their order relative to each other. */
  const bumpAreaZ = useCallback((delta: number) => {
    const a = selectedArea
    if (!a) return
    const z = Math.min(MAX_Z_ORDER, Math.max(-MAX_Z_ORDER, (a.z_order || 0) + delta))
    if (z === a.z_order) return
    void putArea(a, { z_order: z })
  }, [putArea, selectedArea])

  const deleteArea = useCallback(async () => {
    const a = selectedArea
    if (!a) return
    setSelArea('')
    try {
      await apiDelete(`/world/terrain-areas/${encodeURIComponent(a.id)}`)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    await reloadTerrain()
  }, [reloadTerrain, selectedArea, t, toast])

  const onBackgroundClick = useCallback((wx: number, wz: number) => {
    if (ghostRef.current) { void placeGhost(wx, wz); return }
    const m = modeRef.current
    if (m === 'paint') { addDraftPoint(wx, wz); return }
    if (m === 'edit-area') {
      // The list arrives bottom-to-top, so the TOPMOST area under the cursor
      // is the last one that contains the point — walk it from the end.
      const areas = areasRef.current
      for (let i = areas.length - 1; i >= 0; i--) {
        if (pointInPolygon(wx, wz, areas[i].polygon)) { setSelArea(areas[i].id); return }
      }
      setSelArea('')
      return
    }
    setSelId('')
  }, [addDraftPoint, placeGhost])

  /** Arming a tray entry is a location gesture — it takes the canvas back to
   *  the location mode instead of leaving a ghost that the next click, meant
   *  for the ground, would place by accident. */
  const armGhost = useCallback((loc: EditorLocation, kind: 'place' | 'clone') => {
    switchMode('select')
    const anchor = anchorWidthM(loc)
    setGhost({
      kind, id: loc.id, name: loc.name,
      widthM: anchor ?? NO_ANCHOR_WIDTH_M, anchored: anchor != null,
    })
    setGhostPt(null)
  }, [switchMode])

  /** Open the location in the World tab. A clone has no editable data of its
   *  own — everything lives on its template, so that is what gets opened. */
  const editLocation = useCallback((loc: EditorLocation) => {
    const target = (loc.template_location_id || '').trim() || loc.id
    sessionStorage.setItem('ga:world:select',
      JSON.stringify({ kind: 'location', locationId: target }))
    window.location.hash = '#/world'
  }, [])

  /** 90° step of the ICON inside the footprint (display transform), not the
   *  location's rotation in the world. */
  const rotateIcon = useCallback(async (loc: EditorLocation) => {
    const next = ((loc.map_rotation_2d || 0) + 90) % 360
    patchLocal(loc.id, { map_rotation_2d: next })
    try {
      await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-rotation`,
        { rotation: next })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      void reload()
    }
  }, [patchLocal, reload, t, toast])

  // ── Image picker (kept from the grid tab, cell mechanics removed) ─────────

  // Clones share their template's gallery — images are read from the owner,
  // the CHOICE is stored on the clone, so two copies can show two pictures.
  const ownerOf = (loc: EditorLocation) => (loc.template_location_id || '').trim() || loc.id

  const bumpIcon = useCallback((id: string) => {
    setIconVer((v) => ({ ...v, [id]: (v[id] || 0) + 1 }))
  }, [])

  const openPicker = useCallback(async (loc: EditorLocation) => {
    setPicker(loc)
    setPickerGallery(null)
    setDelConfirm(null)
    try {
      const g = await apiGet<GalleryResp>(
        `/world/locations/${encodeURIComponent(ownerOf(loc))}/gallery`)
      setPickerGallery(g)
      // No "auto" mode: without an explicit choice the first map image is
      // assigned right away, so what the map shows is always a named file.
      if (!(loc.map_image_2d || '').trim()) {
        const firstMap = (g.images || []).find((f) => (g.image_types || {})[f] === 'map_2d')
        if (firstMap) {
          await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-image`,
            { type: 'map_2d', file: firstMap })
          bumpIcon(loc.id)
          setPicker((p) => (p && p.id === loc.id ? { ...p, map_image_2d: firstMap } : p))
          void reload()
        }
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setPickerGallery({ images: [], image_types: {} })
    }
  }, [bumpIcon, reload, t, toast])

  const chooseImage = useCallback(async (loc: EditorLocation, file: string) => {
    try {
      await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-image`,
        { type: 'map_2d', file })
      bumpIcon(loc.id)
      await reload()
      setPicker(null)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [bumpIcon, reload, t, toast])

  // The backend clears dangling map_image_2d references itself; the gallery
  // and the locations are re-read so the selection marker stays honest.
  const deleteImage = useCallback(async (owner: string, file: string) => {
    try {
      await apiDelete(
        `/world/locations/${encodeURIComponent(owner)}/gallery/${encodeURIComponent(file)}`)
      const g = await apiGet<GalleryResp>(
        `/world/locations/${encodeURIComponent(owner)}/gallery`)
      setPickerGallery(g)
      const data = await apiGet<{ locations?: EditorLocation[] }>('/world/locations')
      const locs = data.locations || []
      setLocations(locs)
      setPicker((p) => (p ? locs.find((l) => l.id === p.id) || p : p))
      toast(t('Image deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  // Generation is fire-and-forget (the POST returns a track id, the image
  // arrives asynchronously) — poll the track until it reaches a terminal
  // state, then bust the icon cache ONCE. No periodic refresh: it would fight
  // the editing hand.
  const watchAndRefresh = useCallback(async (trackId: string, locId: string) => {
    if (!trackId) return
    const deadline = Date.now() + 4 * 60 * 1000  // map generations can take a while
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2500))
      let status: string | null = null
      try {
        const s = await apiGet<{
          recent?: Array<{ task_id: string; status: string }>
          recent_tasks?: Array<{ task_id: string; status: string }>
        }>('/queue/status')
        const hit = [...(s.recent || []), ...(s.recent_tasks || [])]
          .find((x) => x.task_id === trackId)
        if (hit) status = hit.status
      } catch { /* keep polling */ }
      if (status) {  // terminal state reached
        if (status === 'completed') bumpIcon(locId)
        return
      }
    }
  }, [bumpIcon])

  const submitGen = useCallback(async (payload: ImageGenSubmit, loc: EditorLocation) => {
    const body: Record<string, unknown> = { prompt_type: 'map_2d', prompt: payload.prompt }
    if (payload.backend) body.backend = payload.backend
    if (payload.loras) body.loras = payload.loras
    if (payload.prompt_settings_applied) body.settings_applied = true
    // Composed negative (carries what the guard moved out of the subject).
    if (payload.negative_prompt) body.negative_prompt = payload.negative_prompt
    if (payload.llm_composed) {
      body.llm_composed = true
      body.cache_hit = !!payload.cache_hit
    }
    try {
      const r = await apiPost<{ track_id?: string }>(
        `/world/locations/${encodeURIComponent(loc.id)}/gallery`, body)
      toast(t('Image queued'))
      void watchAndRefresh(r?.track_id || '', loc.id)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast, watchAndRefresh])

  // ── Render ───────────────────────────────────────────────────────────────

  if (locations == null) {
    return <div className="ga-empty">{t('Loading…')}</div>
  }

  const selAnchor = selected ? anchorWidthM(selected) : null
  const selIsClone = !!(selected && (selected.template_location_id || '').trim())

  // The unpainted ground: the default kind's colour, and nothing at all until
  // both the payload and the catalog have answered.
  const groundColor = typeMap[terrain?.default_kind || '']?.color || ''
  // An area the catalog cannot name is selectable but not reshapeable — see
  // `putArea`. The chip says so; here the handles simply stay away.
  const selAreaEditable = !!(selectedArea && typeMap[selectedArea.kind])
  // Will the next click close the ring? The same pixel tolerance the click
  // handler uses — the highlight must not promise a close that will not happen.
  const draftWillClose = !!(draftCursor && draft.length >= MIN_POINTS
    && Math.hypot(draftCursor.x - draft[0][0], draftCursor.z - draft[0][1])
      <= CLOSE_TOL_PX / view.pxPerM)

  const trayEntry = (loc: EditorLocation, kind: 'place' | 'clone') => {
    const anchor = anchorWidthM(loc)
    return (
      <button
        key={loc.id}
        type="button"
        className={'ga-map-tray-item' + (ghost && ghost.id === loc.id ? ' armed' : '')
          + (kind === 'clone' ? ' ga-map-tray-template' : '')}
        onClick={() => armGhost(loc, kind)}
        title={kind === 'clone'
          ? t('Click, then click the map to place a copy')
          : t('Click, then click the map to place it')}
      >
        <MapIcon locId={loc.id} className="ga-map-tray-icon"
          cacheKey={String(iconVer[loc.id] || 0)} />
        <span className="ga-map-tray-name">{loc.name}</span>
        <span className="ga-map-tray-stamp">
          {anchor ? fmtM(anchor) + ' m' : '?'}
        </span>
      </button>
    )
  }

  return (
    <div className="ga-map-layout">
      <aside className="ga-map-tray">
        <div className="ga-map-tray-section">
          <div className="ga-map-tray-title">{t('Unplaced')}</div>
          {unplaced.length === 0 ? (
            <div className="ga-map-tray-empty">{t('None')}</div>
          ) : (
            <div className="ga-map-tray-items">
              {unplaced.map((loc) => trayEntry(loc, 'place'))}
            </div>
          )}
        </div>
        <div className="ga-map-tray-section">
          <div className="ga-map-tray-title">{t('Templates')}</div>
          {templates.length === 0 ? (
            <div className="ga-map-tray-empty">{t('None')}</div>
          ) : (
            <div className="ga-map-tray-items">
              {templates.map((loc) => trayEntry(loc, 'clone'))}
            </div>
          )}
        </div>
        <div className="ga-map-tray-hint">
          {t('Click an entry, then click the map to place it. Escape cancels.')}
        </div>
      </aside>

      <div className="ga-map-main">
        <div className="ga-map-toolbar">
          {/* Reload re-reads the CATALOG too — it is the only way back from a
              failed type fetch, and everything the ground editor can do hangs
              off that one answer. */}
          <button type="button" className="ga-btn ga-btn-sm"
            onClick={() => { void reload(); void reloadTerrain(); void reloadTypes() }}>
            ↻ {t('Reload')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm" onClick={fitView}
            disabled={!bounds}>
            {t('Fit view')}
          </button>
          <TerrainToolbar
            mode={mode}
            onMode={switchMode}
            types={terrainTypes}
            paintKind={paintKind}
            onPaintKind={setPaintKind}
            draftLen={draft.length}
            onCloseDraft={() => { void commitDraft(draft) }}
            onDiscardDraft={() => { setDraft([]); setDraftCursor(null) }}
            areaCount={terrain?.areas.length || 0}
            onManageTypes={() => setTypesOpen(true)}
            typesError={typesError}
          />
          {mode === 'select' ? (
            <label className="ga-map-toolbar-check"
              title={t('Placing and moving snap the centre onto a {n} m grid')
                .replace('{n}', String(SNAP_M))}>
              <input type="checkbox" checked={snapOn}
                onChange={(e) => setSnapOn(e.target.checked)} />
              {t('Snap {n} m').replace('{n}', String(SNAP_M))}
            </label>
          ) : null}
          <span className="ga-map-toolbar-info">
            {t('{n} placed').replace('{n}', String(placed.length))}
          </span>
          {ghost ? (
            <span className={'ga-map-arm' + (ghost.anchored ? '' : ' warn')}>
              {(ghost.kind === 'clone'
                ? t('Placing a copy of “{name}” — click the map')
                : t('Placing “{name}” — click the map')).replace('{name}', ghost.name)}
              {ghost.anchored
                ? ' · ' + fmtM(ghost.widthM) + ' m'
                : ' · ' + t('no scale anchor, {n} m placeholder')
                  .replace('{n}', String(NO_ANCHOR_WIDTH_M))}
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={() => { setGhost(null); setGhostPt(null) }}>
                {t('Cancel')}
              </button>
            </span>
          ) : null}
        </div>

        <div className="ga-map-canvas-pane" ref={setPaneEl}>
          <MapCanvas
            view={view}
            onViewChange={setView}
            onBackgroundClick={onBackgroundClick}
            onPointerWorldMove={onWorldMove}
            cursor={ghost || mode !== 'select' ? 'crosshair' : undefined}
          >
            <TerrainLayer
              areas={terrain?.areas || []}
              types={typeMap}
              groundColor={groundColor}
              editing={mode === 'edit-area'}
              editable={selAreaEditable}
              selectedId={selArea}
              draft={draft}
              draftCursor={draftCursor}
              draftColor={typeColor(typeMap, paintKind)}
              draftWillClose={draftWillClose}
              onVertexMove={moveVertex}
              onVertexDelete={deleteVertex}
              onEdgeInsert={insertVertex}
            />
            {/* Outside the location mode the footprints must let clicks
                through: a terrain click has to reach the canvas, which is
                where the point-in-polygon test lives. The layer's own root
                sets no pointer-events when nothing is armed, so it inherits
                this. */}
            <g pointerEvents={mode === 'select' ? undefined : 'none'}>
              <PlacementLayer
                locations={placed}
                selectedId={selId}
                onSelect={setSelId}
                onMove={(id, x, z) => { void commitMove(id, x, z) }}
                snapM={snapOn ? SNAP_M : 0}
                iconVer={iconVer}
                ghost={ghost}
                ghostPt={ghostPt}
              />
            </g>
          </MapCanvas>

          {selectedArea ? (
            <TerrainAreaChip
              key={selectedArea.id}
              area={selectedArea}
              types={typeMap}
              typeList={terrainTypes}
              typesError={typesError}
              onKind={setAreaKind}
              onZOrder={bumpAreaZ}
              onDelete={() => { void deleteArea() }}
              onClose={() => setSelArea('')}
            />
          ) : null}

          {selected ? (
            <div className="ga-map-chip">
              <div className="ga-map-chip-head">
                <strong>{selected.name}</strong>
                {selIsClone ? <span className="ga-map-chip-tag">{t('copy')}</span> : null}
                <button type="button" className="ga-modal-close"
                  title={t('Clear selection')} onClick={() => setSelId('')}>×</button>
              </div>
              <div className="ga-map-chip-row">
                <span className={selAnchor ? '' : 'ga-map-chip-warn'}>
                  {selAnchor
                    ? fmtM(selAnchor) + ' × ' + fmtM(selAnchor) + ' m'
                    : t('No scale anchor — drawn as a {n} m placeholder')
                      .replace('{n}', String(NO_ANCHOR_WIDTH_M))}
                </span>
                <span className="ga-map-chip-pos">
                  x {fmtPos(selected.pos_x || 0)} · z {fmtPos(selected.pos_z || 0)}
                </span>
              </div>
              <div className="ga-map-chip-row">
                <span className="ga-map-chip-label">{t('Rotation')}</span>
                <button type="button" className="ga-btn ga-btn-sm"
                  title={t('Turn left {n}°').replace('{n}', String(YAW_FINE))}
                  onClick={() => { void commitYaw(selected, (selected.yaw_deg || 0) - YAW_FINE) }}>
                  ⟲{YAW_FINE}°
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  title={t('Turn right {n}°').replace('{n}', String(YAW_FINE))}
                  onClick={() => { void commitYaw(selected, (selected.yaw_deg || 0) + YAW_FINE) }}>
                  ⟳{YAW_FINE}°
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => { void commitYaw(selected, (selected.yaw_deg || 0) - YAW_QUARTER) }}>
                  −{YAW_QUARTER}°
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => { void commitYaw(selected, (selected.yaw_deg || 0) + YAW_QUARTER) }}>
                  +{YAW_QUARTER}°
                </button>
                <input
                  className="ga-input ga-map-chip-yaw"
                  type="number" step={1} value={yawDraft}
                  onChange={(e) => setYawDraft(e.target.value)}
                  onBlur={() => {
                    const v = parseFloat(yawDraft)
                    if (Number.isFinite(v)) void commitYaw(selected, v)
                    else setYawDraft(String(normYaw(selected.yaw_deg || 0)))
                  }}
                  onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
                />
                <span className="ga-map-chip-label">°</span>
              </div>
              <div className="ga-map-chip-actions">
                <button type="button" className="ga-btn ga-btn-sm"
                  title={t('Choose which image this location shows on the map')}
                  onClick={() => { void openPicker(selected) }}>
                  🖼 {t('Image')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  title={t('Rotate the map icon 90° inside the footprint')}
                  onClick={() => { void rotateIcon(selected) }}>
                  ↻ {t('Icon')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => editLocation(selected)}>
                  {t('Edit location')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  title={t('Take it off the map — it keeps all its data')}
                  onClick={() => { void unplace(selected) }}>
                  {t('Unplace')}
                </button>
                {selIsClone ? (
                  delArmed === selected.id ? (
                    <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                      onClick={() => { void removeClone(selected) }}>
                      {t('Really delete')}
                    </button>
                  ) : (
                    <button type="button" className="ga-btn ga-btn-sm"
                      title={t('Delete this copy')}
                      onClick={() => setDelArmed(selected.id)}>
                      {t('Delete copy')}
                    </button>
                  )
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {typesOpen ? (
        <TerrainTypesDialog
          types={terrainTypes}
          sources={typeSources}
          onChanged={reloadTypes}
          onClose={() => setTypesOpen(false)}
        />
      ) : null}

      {picker ? (
        <div className="ga-modal-backdrop" onMouseDown={() => setPicker(null)}>
          <div className="ga-modal ga-map-imgpicker" onMouseDown={(e) => e.stopPropagation()}>
            <div className="ga-modal-header">
              <span>{t('Map image')} — {picker.name}</span>
              <button className="ga-modal-close" onClick={() => setPicker(null)}>×</button>
            </div>
            <div className="ga-modal-body">
              {pickerGallery == null ? (
                <div className="ga-empty">{t('Loading…')}</div>
              ) : (
                <div className="ga-map-imgpicker-group">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                    <div className="ga-map-imgpicker-label" style={{ marginBottom: 0 }}>
                      {t('2D icon')}
                    </div>
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => setGen(picker)}
                      title={t('Generate a new map image for this location')}>
                      ✨ {t('Generate')}
                    </button>
                  </div>
                  {(() => {
                    const imgs = (pickerGallery.images || []).filter(
                      (f) => (pickerGallery.image_types || {})[f] === 'map_2d')
                    if (imgs.length === 0) {
                      return <div className="ga-map-tray-empty">{t('No images of this type.')}</div>
                    }
                    const owner = ownerOf(picker)
                    const chosen = picker.map_image_2d || ''
                    return (
                      <div className="ga-map-imgpicker-grid">
                        {imgs.map((f) => (
                          <div key={f} className="ga-map-imgpicker-cell">
                            <button
                              type="button"
                              className={'ga-map-imgpicker-item' + (chosen === f ? ' selected' : '')}
                              onClick={() => { void chooseImage(picker, f) }}
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
                                  <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                                    onClick={() => { setDelConfirm(null); void deleteImage(owner, f) }}>
                                    {t('Delete')}
                                  </button>
                                  <button type="button" className="ga-btn ga-btn-sm"
                                    onClick={() => setDelConfirm(null)}>
                                    {t('Cancel')}
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <button type="button" className="ga-map-imgpicker-del"
                                title={t('Delete image')} onClick={() => setDelConfirm(f)}>
                                ×
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {gen ? (
        <ImageGenDialog
          open
          title={t('Generate map image — {name}').replace('{name}', gen.name)}
          defaultPrompt=""
          // The server composes style + subject + guard (the same composer the
          // batch path uses) and decides the use case itself.
          composeRequest={{ location_id: gen.id, prompt_type: 'map_2d' }}
          onSubmit={(payload) => submitGen(payload, gen)}
          onClose={() => setGen(null)}
        />
      ) : null}
    </div>
  )
}
