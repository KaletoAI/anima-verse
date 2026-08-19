/**
 * MapDraftPreview — the map draft an LLM produced, drawn on the very canvas
 * the map editor draws with.
 *
 * READ-ONLY, and structurally so: every layer sits inside a
 * `pointerEvents="none"` group, so nothing here can be picked, dragged or
 * reshaped. The draft is not persisted either — it lives in the World-Dev
 * session until "Apply" writes it through the editor endpoints.
 *
 * THE GEOMETRY IS THE SERVER'S. `POST /world-dev/preview-map` normalises the
 * raw model JSON (line recipes already widened into polygons, unknown kinds
 * dropped, coordinates clamped) and this component only projects what came
 * back. Nothing is recomputed here: a preview that derived its own polygons
 * would show a map the apply would not produce.
 *
 * Three layers in the editor's order — painted ground, relief, placements —
 * and the placements are drawn TWICE: the world's current ones dimmed
 * underneath, the draft's on top. The question a placement draft answers is
 * "what moves where", and that needs both ends of the move on screen.
 *
 * The scale aids come from `MapCanvas` itself (metre grid, scale bar, the
 * 1.70 m figure seen from above), so a draft is read against the same anchors
 * as the editor's map — "kein Maß ohne Maßstab" holds for a preview too.
 *
 * A warning is a POINTER, not a verdict: clicking one centres the view on the
 * shape it names and rings it. The server's `ref` is free-form, so it is
 * resolved through a tolerant reader (`resolveWarningRef`) that falls back to
 * the warning CODE to decide which list a bare index counts in — an
 * unresolvable ref simply highlights nothing instead of pointing at the wrong
 * shape.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { MapCanvas, useMapView } from '../map/MapCanvas'
import {
  boundaryScreenPoints, fitBounds, worldPolyToPath, worldToScreen,
  type MapBounds, type StrokeDeco, type View,
} from '../map/mapMath'
import { TerrainLayer } from '../map/TerrainLayer'
import { HeightLayer } from '../map/HeightLayer'
import { PlacementLayer, boundaryLocal, isPlaced } from '../map/PlacementLayer'
import { DEFAULT_MAX_SLOPE_DEG, DEFAULT_MAX_STEP_M } from '../map/heightMath'
import type {
  EditorLocation, HeightArea, TerrainArea, TerrainMeta, TerrainStroke,
  TerrainType, TerrainTypesResp,
} from '../map/mapTypes'

/* ------------------------------------------------------------------ types */

/** One finding of `POST /world-dev/preview-map`. Never an error — the apply
 *  runs regardless; this is what the author is asked to look at. */
export interface MapDraftWarning {
  code: string
  message: string
  /** Which shape it is about. Free-form by contract — see `resolveWarningRef`. */
  ref?: string | number | null
}

/** A normalised terrain area of the draft. It carries no id (nothing is
 *  persisted yet) and its `meta` is passed through verbatim, the line recipe
 *  (`meta.stroke`) included — the polygon is already the widened ribbon, the
 *  recipe only says how it came about. */
export interface MapDraftArea {
  kind: string
  polygon: Array<[number, number]>
  z_order?: number
  meta?: { label?: string; stroke?: TerrainStroke; source?: string }
    & Record<string, unknown>
}

export interface MapDraftHeightArea {
  polygon: Array<[number, number]>
  height_m: number
  falloff_m: number
  meta?: { label?: string } & Record<string, unknown>
}

/** A position the draft proposes for an EXISTING location (v1 places no new
 *  places — the `location` schema does that). */
export interface MapDraftLocation {
  id: string
  pos_x: number
  pos_z: number
  yaw_deg?: number
}

export interface MapDraftNormalized {
  summary?: string
  bounds?: MapBounds | null
  terrain_areas?: MapDraftArea[]
  height_areas?: MapDraftHeightArea[]
  locations?: MapDraftLocation[]
}

export interface MapDraftCounts {
  areas: number
  heights: number
  positions: number
}

/** `POST /world-dev/preview-map`. */
export interface MapPreviewResponse {
  normalized: MapDraftNormalized
  warnings?: MapDraftWarning[]
  counts?: MapDraftCounts
}

/* -------------------------------------------------------------- constants */

/** Nothing is being drawn here, so the paint tool's settings are inert. */
const NO_DECO: StrokeDeco = { style: 'straight', spacingM: 0, amplitudeM: 0 }
const NO_POINTS: Array<[number, number]> = []
const NO_FOOTPRINTS: readonly [] = []
const NOOP = () => { /* read-only preview */ }

/** The draft's own colours: green for what would be ADDED, amber for the shape
 *  a clicked warning is about. The editor's palette, same meanings. */
const COL_DRAFT = '#3fb950'
const COL_HIGHLIGHT = '#d29922'

/** Height of the map pane, unless the caller says otherwise. Tall enough for a
 *  village to be legible next to the chat it came out of. */
const DEFAULT_PANE_PX = 420

/** Air around the fitted draft, in metres — a layout that ends exactly at the
 *  canvas edge reads as if it continued. */
const FIT_PAD_M = 20

/* ----------------------------------------------------------- ref resolving */

type HighlightKind = 'area' | 'height' | 'location'

export interface DraftHighlight {
  kind: HighlightKind
  index: number
}

/**
 * Which list an explicit `ref` counts in. HEIGHT FIRST, deliberately: the
 * terrain pattern's `areas?` also matches inside `height_areas`, so testing it
 * first would send every relief warning to the painted ground.
 */
const REF_PATTERNS: Array<[RegExp, HighlightKind]> = [
  [/(?:height_areas?|heights?)\D{0,3}(\d+)/i, 'height'],
  [/(?:terrain_areas?|areas?)\D{0,3}(\d+)/i, 'area'],
  [/(?:locations?|positions?)\D{0,3}(\d+)/i, 'location'],
]

/** Codes that are ALWAYS about a placement — what a bare index means when the
 *  ref carries no list name. Everything else counts in the terrain list, which
 *  is where the geometric complaints live. */
const LOCATION_CODES: ReadonlySet<string> = new Set([
  'footprint_overlap', 'on_impassable', 'unknown_location',
])

/**
 * Point a warning at a shape — or at nothing.
 *
 * The `ref` is free-form by contract, so it is read through four steps, in
 * this order: an explicit "list + index" spelling, an exact location id, an
 * exact `meta.label`, and finally a bare number, which is disambiguated by the
 * warning CODE. Anything else resolves to `null`: highlighting the wrong shape
 * is worse than highlighting none.
 */
export function resolveWarningRef(
  warning: MapDraftWarning, draft: MapDraftNormalized,
): DraftHighlight | null {
  const areas = draft.terrain_areas || []
  const heights = draft.height_areas || []
  const locs = draft.locations || []
  const raw = warning.ref
  if (raw === null || raw === undefined || raw === '') return null

  const inRange = (kind: HighlightKind, index: number): DraftHighlight | null => {
    const len = kind === 'area' ? areas.length
      : kind === 'height' ? heights.length : locs.length
    return index >= 0 && index < len ? { kind, index } : null
  }

  if (typeof raw === 'number') {
    return inRange(LOCATION_CODES.has(warning.code) ? 'location' : 'area', raw)
  }

  const ref = String(raw).trim()
  for (const [re, kind] of REF_PATTERNS) {
    const m = re.exec(ref)
    if (m) return inRange(kind, Number(m[1]))
  }

  const byId = locs.findIndex((l) => l.id === ref)
  if (byId >= 0) return { kind: 'location', index: byId }

  const byAreaLabel = areas.findIndex((a) => a.meta?.label === ref)
  if (byAreaLabel >= 0) return { kind: 'area', index: byAreaLabel }

  const byHeightLabel = heights.findIndex((a) => a.meta?.label === ref)
  if (byHeightLabel >= 0) return { kind: 'height', index: byHeightLabel }

  if (/^-?\d+$/.test(ref)) {
    return inRange(LOCATION_CODES.has(warning.code) ? 'location' : 'area',
      Number(ref))
  }
  return null
}

/* ------------------------------------------------------------------ bounds */

/** Arithmetic mean of a ring's vertices — good enough to centre a view on. */
function centroid(poly: Array<[number, number]>): [number, number] | null {
  if (!poly.length) return null
  let x = 0
  let z = 0
  for (const [px, pz] of poly) { x += px; z += pz }
  return [x / poly.length, z / poly.length]
}

/** The box every part of the draft fits into, plus the placed locations it is
 *  compared against. `null` when there is nothing with coordinates at all. */
function draftBounds(draft: MapDraftNormalized,
  placed: EditorLocation[]): MapBounds | null {
  let minX = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxZ = -Infinity
  const eat = (x: number, z: number) => {
    if (!Number.isFinite(x) || !Number.isFinite(z)) return
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (z < minZ) minZ = z
    if (z > maxZ) maxZ = z
  }
  for (const a of draft.terrain_areas || []) for (const p of a.polygon || []) eat(p[0], p[1])
  for (const a of draft.height_areas || []) for (const p of a.polygon || []) eat(p[0], p[1])
  for (const l of draft.locations || []) eat(l.pos_x, l.pos_z)
  for (const l of placed) eat(l.pos_x as number, l.pos_z as number)
  if (!Number.isFinite(minX) || !Number.isFinite(minZ)) return null
  return {
    min_x: minX - FIT_PAD_M, min_z: minZ - FIT_PAD_M,
    max_x: maxX + FIT_PAD_M, max_z: maxZ + FIT_PAD_M,
  }
}

/* ----------------------------------------------------------------- overlay */

interface DraftOverlayProps {
  areas: MapDraftArea[]
  heights: MapDraftHeightArea[]
  /** The draft footprints, already resolved against the world's records. */
  locs: EditorLocation[]
  highlight: DraftHighlight | null
}

/**
 * What the editor's layers cannot say about a DRAFT: which footprints are
 * proposed (green dashed ghosts over the ordinary squares), where a line
 * recipe ran (dashed centre line — the polygon is the ribbon, the line is how
 * it was drawn) and which shape a clicked warning is about (amber ring).
 *
 * The outline comes from `boundaryScreenPoints`, the same verified § A1.1
 * projection the placement layer draws with — a ghost drawn from its own
 * arithmetic would be a second opinion about where a location stands.
 */
function DraftOverlay({ areas, heights, locs, highlight }: DraftOverlayProps) {
  const { view, w, h } = useMapView()
  if (!w || !h) return null

  const ghostRing = (loc: EditorLocation, color: string, width: number) => {
    const corners = boundaryScreenPoints({
      pos_x: loc.pos_x, pos_z: loc.pos_z, yaw_deg: loc.yaw_deg,
      boundary: boundaryLocal(loc),
    }, view, w, h)
    if (!corners) {
      // No drawn boundary: the location has no area at all (contract v6), so
      // the ghost is a marker on its point instead of a shape claiming ground.
      const p = worldToScreen(loc.pos_x as number, loc.pos_z as number, view, w, h)
      return (
        <circle cx={p.x} cy={p.y} r={9} fill="none" stroke={color}
          strokeWidth={width} strokeDasharray="5 4" />
      )
    }
    return (
      <path d={`M${corners.map((c) => `${c.x.toFixed(2)} ${c.y.toFixed(2)}`).join(' L')} Z`}
        fill="none" stroke={color} strokeWidth={width} strokeDasharray="6 4" />
    )
  }

  const hiArea = highlight?.kind === 'area' ? areas[highlight.index] : null
  const hiHeight = highlight?.kind === 'height' ? heights[highlight.index] : null
  const hiLoc = highlight?.kind === 'location' ? locs[highlight.index] : null

  return (
    <g pointerEvents="none">
      {/* The centre line of every area that came from a line recipe. */}
      {areas.map((a, i) => {
        const pts = a.meta?.stroke?.points
        if (!Array.isArray(pts) || pts.length < 2) return null
        return (
          <path key={`sl${i}`} d={worldPolyToPath(pts, view, w, h, false)}
            fill="none" stroke={COL_DRAFT} strokeWidth={1.2}
            strokeDasharray="7 4" strokeOpacity={0.75} />
        )
      })}

      {/* Every proposed footprint, marked as proposed. */}
      {locs.map((loc, i) => (
        <g key={`g${loc.id}-${i}`}>{ghostRing(loc, COL_DRAFT, 2)}</g>
      ))}

      {/* The shape a clicked warning is about. */}
      {hiArea && hiArea.polygon.length >= 3 ? (
        <path d={worldPolyToPath(hiArea.polygon, view, w, h)} fill="none"
          stroke={COL_HIGHLIGHT} strokeWidth={3} />
      ) : null}
      {hiHeight && hiHeight.polygon.length >= 3 ? (
        <path d={worldPolyToPath(hiHeight.polygon, view, w, h)} fill="none"
          stroke={COL_HIGHLIGHT} strokeWidth={3} />
      ) : null}
      {hiLoc ? ghostRing(hiLoc, COL_HIGHLIGHT, 3) : null}
    </g>
  )
}

/* --------------------------------------------------------------- component */

export interface MapDraftPreviewProps {
  normalized: MapDraftNormalized
  warnings: MapDraftWarning[]
  counts?: MapDraftCounts
  /** Height of the map pane in CSS pixels. */
  heightPx?: number
}

export function MapDraftPreview({
  normalized, warnings, counts, heightPx = DEFAULT_PANE_PX,
}: MapDraftPreviewProps) {
  const { t } = useI18n()
  const [worldLocations, setWorldLocations] = useState<EditorLocation[]>([])
  const [types, setTypes] = useState<Record<string, TerrainType>>({})
  const [highlight, setHighlight] = useState<DraftHighlight | null>(null)
  const [view, setView] = useState<View>({ cx: 0, cz: 0, pxPerM: 4 })

  // Read side, once per mount: the full location records (names and the scale
  // anchor of UNPLACED places, which only these dicts carry) and the effective
  // terrain catalog, which is the only source of a kind's colour. A failed
  // fetch stays silent — a preview without names is still a preview, and the
  // chat above already has the user's attention.
  useEffect(() => {
    apiGet<{ locations?: EditorLocation[] }>('/world/locations')
      .then((d) => setWorldLocations(d.locations || []))
      .catch(() => setWorldLocations([]))
    apiGet<TerrainTypesResp>('/world/terrain-types')
      .then((r) => {
        const m: Record<string, TerrainType> = {}
        for (const ty of r.types || []) m[ty.kind] = ty
        setTypes(m)
      })
      .catch(() => setTypes({}))
  }, [])

  const draftAreas = useMemo(() => normalized.terrain_areas || [], [normalized])
  const draftHeights = useMemo(() => normalized.height_areas || [], [normalized])

  /** The draft's areas in the shape the editor's layer reads. Synthetic ids —
   *  nothing is persisted yet, and the layer needs a stable React key. */
  const terrainAreas: TerrainArea[] = useMemo(() => draftAreas.map((a, i) => ({
    id: `draft-area-${i}`,
    kind: a.kind,
    polygon: a.polygon || [],
    z_order: typeof a.z_order === 'number' ? a.z_order : 0,
    meta: a.meta as TerrainMeta | undefined,
  })), [draftAreas])

  const heightAreas: HeightArea[] = useMemo(() => draftHeights.map((a, i) => ({
    id: `draft-height-${i}`,
    polygon: a.polygon || [],
    height_m: a.height_m,
    falloff_m: a.falloff_m,
    meta: a.meta,
  })), [draftHeights])

  const byId = useMemo(() => {
    const m: Record<string, EditorLocation> = {}
    for (const loc of worldLocations) m[loc.id] = loc
    return m
  }, [worldLocations])

  /** The proposed placements as location records: the draft's position and
   *  yaw on the world's own name, icon and scale anchor. */
  const draftLocs: EditorLocation[] = useMemo(
    () => (normalized.locations || []).map((l) => {
      const src = byId[l.id]
      return {
        id: l.id,
        name: src?.name || l.id,
        pos_x: l.pos_x,
        pos_z: l.pos_z,
        yaw_deg: typeof l.yaw_deg === 'number' ? l.yaw_deg : 0,
        map3d: src?.map3d,
        map_rotation_2d: src?.map_rotation_2d,
      }
    }),
    [byId, normalized],
  )

  /** Where those places stand TODAY — the other end of every move. */
  const placedToday = useMemo(
    () => worldLocations.filter(isPlaced), [worldLocations],
  )

  const bounds = useMemo(() => {
    const b = normalized.bounds
    if (b && Number.isFinite(b.min_x) && Number.isFinite(b.max_x)
      && Number.isFinite(b.min_z) && Number.isFinite(b.max_z)) return b
    return draftBounds(normalized, placedToday)
  }, [normalized, placedToday])

  // The pane is measured here because `fitBounds` needs pixels BEFORE the
  // first view exists, and the size the canvas measures lives in its own
  // context. A callback ref, like the map editor's — the pane may enter the
  // DOM later than any mount effect would run.
  const [pane, setPane] = useState({ w: 0, h: 0 })
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

  const fitView = useCallback(() => {
    if (!bounds || !pane.w || !pane.h) return
    setView(fitBounds(bounds, pane.w, pane.h))
  }, [bounds, pane])

  // Every NEW draft frames itself once. Unlike the editor this refits on a
  // data change: a draft is replaced wholesale by the next turn of the chat,
  // and keeping the old view would leave the new layout off screen.
  const fittedKeyRef = useRef('')
  useEffect(() => {
    if (!bounds || !pane.w || !pane.h) return
    const key = `${bounds.min_x},${bounds.min_z},${bounds.max_x},${bounds.max_z}`
      + `|${pane.w}x${pane.h}`
    if (fittedKeyRef.current === key) return
    fittedKeyRef.current = key
    setView(fitBounds(bounds, pane.w, pane.h))
  }, [bounds, pane])

  // A draft that is replaced must not keep pointing at a shape of the old one.
  useEffect(() => { setHighlight(null) }, [normalized])

  /** Centre the view on what a warning names, and ring it. */
  const focusWarning = useCallback((warning: MapDraftWarning) => {
    const target = resolveWarningRef(warning, normalized)
    setHighlight(target)
    if (!target) return
    let centre: [number, number] | null = null
    if (target.kind === 'area') centre = centroid(draftAreas[target.index]?.polygon || [])
    else if (target.kind === 'height') centre = centroid(draftHeights[target.index]?.polygon || [])
    else {
      const l = normalized.locations?.[target.index]
      if (l) centre = [l.pos_x, l.pos_z]
    }
    if (!centre) return
    const [cx, cz] = centre
    setView((v) => ({ ...v, cx, cz }))
  }, [draftAreas, draftHeights, normalized])

  const shown: MapDraftCounts = counts || {
    areas: terrainAreas.length,
    heights: heightAreas.length,
    positions: draftLocs.length,
  }

  return (
    <div className="ga-wd-mapdraft"
      style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div
          ref={setPaneEl}
          style={{
            height: heightPx, border: '1px solid var(--border, #30363d)',
            borderRadius: 6, overflow: 'hidden',
          }}
        >
          <MapCanvas view={view} onViewChange={setView}>
            {/* Every layer is inert: this is a view of a draft, not an editor.
                The canvas keeps its own gestures (wheel zoom, drag to pan), so
                a big layout can still be looked at closely. */}
            <g pointerEvents="none">
              <TerrainLayer
                part="all"
                areas={terrainAreas}
                types={types}
                groundColor=""
                editing={false}
                editable={false}
                selectedId=""
                centerline={null}
                centerlineWidthM={0}
                centerlineDeco={NO_DECO}
                draft={NO_POINTS}
                draftCursor={null}
                draftLine={false}
                draftWidthM={0}
                draftDeco={NO_DECO}
                draftColor={COL_DRAFT}
                draftWillClose={false}
                onVertexMove={NOOP}
                onVertexDelete={NOOP}
                onEdgeInsert={NOOP}
                scatterPreview={false}
                footprints={NO_FOOTPRINTS}
              />
              {heightAreas.length ? (
                <HeightLayer
                  areas={heightAreas}
                  selectedId=""
                  editing={false}
                  maxSlopeDeg={DEFAULT_MAX_SLOPE_DEG}
                  maxStepM={DEFAULT_MAX_STEP_M}
                  draft={NO_POINTS}
                  draftCursor={null}
                  draftWillClose={false}
                  onVertexMove={NOOP}
                  onVertexDelete={NOOP}
                  onEdgeInsert={NOOP}
                />
              ) : null}
              {/* Where those places stand today — dimmed, so the draft on top
                  reads as the proposal it is. */}
              <g opacity={0.3}>
                <PlacementLayer
                  locations={placedToday}
                  selectedId=""
                  onSelect={NOOP}
                  onMove={NOOP}
                  snapM={0}
                  iconVer={{}}
                  ghost={null}
                  ghostPt={null}
                />
              </g>
              <PlacementLayer
                locations={draftLocs}
                selectedId=""
                onSelect={NOOP}
                onMove={NOOP}
                snapM={0}
                iconVer={{}}
                ghost={null}
                ghostPt={null}
              />
              <DraftOverlay areas={draftAreas} heights={draftHeights}
                locs={draftLocs} highlight={highlight} />
            </g>
          </MapCanvas>
        </div>
        <div className="ga-form-hint"
          style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 4 }}>
          <span>
            {t('{a} areas · {h} height areas · {p} positions')
              .replace('{a}', String(shown.areas))
              .replace('{h}', String(shown.heights))
              .replace('{p}', String(shown.positions))}
          </span>
          <button type="button" className="ga-btn ga-btn-sm" onClick={fitView}>
            {t('Fit view')}
          </button>
          <span style={{ opacity: 0.75 }}>
            {t('Preview only — nothing is written until you apply.')}
          </span>
        </div>
      </div>

      <div style={{
        flex: '0 0 280px', display: 'flex', flexDirection: 'column', gap: 6,
        maxHeight: heightPx + 24, overflowY: 'auto',
      }}>
        {normalized.summary ? (
          <div className="ga-form-hint" style={{ whiteSpace: 'pre-wrap' }}>
            {normalized.summary}
          </div>
        ) : null}
        <div className="ga-form-section-label">
          {t('Warnings')} ({warnings.length})
        </div>
        {warnings.length === 0 ? (
          <div className="ga-form-hint">{t('No warnings — the draft is clean.')}</div>
        ) : null}
        {warnings.map((warning, i) => {
          const target = resolveWarningRef(warning, normalized)
          const active = !!target && !!highlight
            && highlight.kind === target.kind && highlight.index === target.index
          return (
            <button
              key={i}
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={() => focusWarning(warning)}
              disabled={!target}
              title={target ? t('Show on the map') : t('No shape to point at')}
              style={{
                textAlign: 'left', display: 'block', width: '100%',
                whiteSpace: 'normal',
                borderColor: active ? COL_HIGHLIGHT : undefined,
              }}
            >
              <span style={{ opacity: 0.7, fontSize: 10, letterSpacing: 0.4 }}>
                {warning.code}
              </span>
              <br />
              {warning.message}
            </button>
          )
        })}
      </div>
    </div>
  )
}
