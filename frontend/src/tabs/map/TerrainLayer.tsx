/**
 * TerrainLayer — the painted ground of the free world map, drawn INSIDE the
 * `MapCanvas` SVG.
 *
 * It draws in TWO parts, and which of them a caller asks for decides what
 * covers what (`part`). The unpainted GROUND is a full-canvas wash and belongs
 * at the very bottom; the painted areas and every overlay above them are the
 * PAINT part. In the ground-editing modes `MapTab` puts that second part above
 * the location footprints, because a footprint is drawn opaque (map picture or
 * roof snapshot) and would otherwise swallow the 45 % fills — and with them the
 * running draft. Everywhere else both parts stay in one piece, underneath the
 * placements, which is where ground belongs while locations are being moved.
 *
 * Inside the paint part the order never changes: fills, then the scatter
 * preview, then the selection outline / centre line / handles / draft. The
 * overlays are how the user sees WHAT they are editing, so nothing this layer
 * draws may cover them — which is why the selection outline is one of those
 * overlays and NOT the stroke of the selected area's own fill: an area painted
 * on top of it is drawn later and would swallow it.
 *
 * A terrain area is a polygon in WORLD METRES (contract § A1.5) — not a
 * location, so it carries no `yaw_deg` and gets NO rotation transform. The
 * footprint squares next door need `rotate(−yaw)` because they are drawn from
 * a centre plus a local frame; a terrain polygon already IS its world
 * coordinates, and turning it would move ground that nobody turned.
 *
 * Paint order is the server's: `areas` arrives bottom-to-top (`z_order` ASC,
 * then insert order) and is rendered in exactly that order, so the last entry
 * covers the ones before it — the same rule `terrain_query` uses to answer
 * "which kind is at this point". The layer never re-sorts.
 *
 * Colours come from the type catalog and from nowhere else. A kind the catalog
 * does not know is drawn grey with a warning glyph instead of being hidden: an
 * area painted with a since-deleted type still exists on the server and still
 * answers point queries, and an editor that draws nothing there would invite
 * painting a second area on top of a problem the user cannot see.
 *
 * An area drawn as a LINE is not a second kind of thing: it is an ordinary
 * polygon that happens to carry its recipe (`meta.stroke`) along. It is filled
 * and outlined like every other area; only when it is SELECTED does the centre
 * line appear, dashed, and the handles move onto it — because a ribbon is
 * reshaped by its line and its width, never by its own outline.
 *
 * All fills — the painted areas AND the default ground — share ONE opacity.
 * The metre grid is drawn by the canvas BEFORE its children, so an opaque
 * ground rectangle would swallow the scale aids ("kein Maß ohne Maßstab");
 * at 45 % the grid reads through, and painted vs. unpainted ground stay
 * directly comparable in colour because both got the same treatment.
 *
 * The polygons themselves take no pointer events. Selecting an area is a
 * point-in-polygon test on the canvas' background click (`mapMath`, the
 * server's algorithm), which is the only way to reach the TOPMOST area under
 * the cursor when several overlap. Only the vertex handles and edges of the
 * area already selected are interactive, and only while editing — and those
 * handles are the SHARED gesture (`PolygonHandles`), the same one the height
 * areas of the world relief are edited with.
 */
import { useMemo } from 'react'
import { cleanRing, polygonArea, scatterInstances, scatterSeed } from '@anima/scene-render'
import type { ScatterFootprint } from '@anima/scene-render'
import { useMapView } from './MapCanvas'
import { strokeToPolygon, worldPolyToPath, worldToScreen } from './mapMath'
import { PolygonHandles } from './PolygonHandles'
import { readScatter } from './mapTypes'
import type { TerrainArea, TerrainType } from './mapTypes'

/** One opacity for every fill — see the module docstring. */
const FILL_OPACITY = 0.45
/** A kind the catalog does not know: grey, and marked as unknown. The SAME
 *  grey the server (`app/core/terrain_types.py: DEFAULT_COLOR`) and the 3D
 *  minimap (`terrainColor`) fall back to — one unknown, one colour. THE one
 *  fallback colour of this app: the type editor (`TerrainTypesDialog`) takes
 *  its new-row default from here instead of keeping a second literal. */
export const UNKNOWN_COLOR = '#888888'
const COL_SELECTED = '#58a6ff'
const COL_DRAFT = '#3fb950'
const COL_WARN = '#d29922'

/** Radius of a draft vertex marker, in pixels — the handle radius of
 *  `PolygonHandles`, so the ring being drawn and the ring being edited read as
 *  the same kind of point. */
const HANDLE_R = 5

/**
 * Colours of the scatter preview, by list index.
 *
 * Not the terrain colour: the dots have to stand out FROM the ground they
 * grow on, and two entries on one area have to be told apart. Six is well
 * past the eight entries an area may carry in practice; beyond that the
 * palette repeats, which is a legibility limit and not a wrong drawing.
 */
const SCATTER_COLORS = ['#2ecc71', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c', '#f1c40f']

/** The preview colour of the n-th scatter entry — shared with its row in the
 *  area chip, so a dot and the line that made it match by eye. */
export function scatterColor(index: number): string {
  return SCATTER_COLORS[((index % SCATTER_COLORS.length) + SCATTER_COLORS.length)
    % SCATTER_COLORS.length]
}

/** Dots the preview draws at most, over ALL areas together.
 *
 *  The POINTS are always the world's own — the shared sampler answers them
 *  whatever this says. This caps how many of them become SVG circles: a world
 *  of dense meadows samples tens of thousands, and a browser asked for that
 *  many nodes stops being an editor. What is drawn is the first n, so the
 *  preview stays a faithful sample of the real placement. */
const SCATTER_PREVIEW_MAX = 4000

/** Radius of a preview dot in pixels. */
const SCATTER_DOT_R = 1.8

/** The colour a kind is drawn in — catalog first, grey when unknown. */
export function typeColor(types: Record<string, TerrainType>, kind: string): string {
  const c = types[kind]?.color
  return typeof c === 'string' && c ? c : UNKNOWN_COLOR
}

/** Arithmetic mean of the vertices — good enough to hang a glyph on. */
function centroid(poly: Array<[number, number]>): [number, number] {
  let x = 0
  let z = 0
  for (const [px, pz] of poly) { x += px; z += pz }
  return [x / poly.length, z / poly.length]
}

/**
 * Which half of the layer to draw — see the module docstring.
 *
 * `ground` is the unpainted default kind alone, `paint` everything that is
 * drawn on top of it, `all` both in one group (the order inside is identical
 * either way). The split exists so a caller can slot ANOTHER layer between the
 * two; it is not a second opinion about paint order.
 */
export type TerrainPart = 'ground' | 'paint' | 'all'

export interface TerrainLayerProps {
  /** Which half to draw. Default `all` — both, as one group. */
  part?: TerrainPart
  /** Bottom-to-top, as the server sent them. Never re-sorted here. */
  areas: TerrainArea[]
  /** The effective catalog by kind — the ONLY source of colours. */
  types: Record<string, TerrainType>
  /** Colour of the unpainted ground (the `default_kind`), empty while the
   *  catalog has not answered yet. */
  groundColor: string
  /** Vertex handles are live only while the edit-area mode is on. */
  editing: boolean
  /** The selected area may be RESHAPED. False for an area whose kind the
   *  catalog no longer knows: every write is a full replace and the server
   *  rejects the unknown kind before it reads the polygon, so offering
   *  handles would only produce a 400 per drag. The selection outline still
   *  shows — the area is selectable, just not editable until its kind is. */
  editable: boolean
  selectedId: string
  /** The CENTRE LINE of the selected area, when it was drawn as a line
   *  (`meta.stroke`, already checked by the caller) — null for an ordinary
   *  painted area. It is what the handles edit, and it is drawn dashed
   *  whenever the area is selected: the polygon is the truth, the line is the
   *  recipe, and only the recipe can be dragged back into shape. */
  centerline: Array<[number, number]> | null
  /** Width of that stroke in metres — the outline preview is regenerated from
   *  it while a line point is being dragged. */
  centerlineWidthM: number
  /** The polygon being painted (world metres) and the cursor it follows. */
  draft: Array<[number, number]>
  draftCursor: { x: number; z: number } | null
  /** The running draft is a centre LINE, not an outline: it is drawn open and
   *  the ribbon it would become is previewed underneath it. */
  draftLine: boolean
  /** Width the line draft would get, in metres. */
  draftWidthM: number
  /** Colour of the armed paint kind. */
  draftColor: string
  /** The cursor sits inside the close tolerance of the first vertex — the
   *  next click will close the ring. Always false for a line draft, which has
   *  no first point to come back to. */
  draftWillClose: boolean
  /** A finished vertex drag, in world metres. Indices are into whatever the
   *  handles sit on — the centre line when there is one, the polygon
   *  otherwise. */
  onVertexMove: (index: number, x: number, z: number) => void
  onVertexDelete: (index: number) => void
  /** Insert a vertex AT `index` (the position it takes in that list). */
  onEdgeInsert: (index: number, x: number, z: number) => void
  /** Draw what the areas GROW, as top-down dots (finding B17). */
  scatterPreview: boolean
  /** The placed locations. Their footprints are kept CLEAR of scatter
   *  (finding B18) — the rows go in as they are, the shared sampler reads
   *  `pos_x`/`pos_z`/`yaw_deg`/`plan_width_m` off them itself. */
  footprints: readonly ScatterFootprint[]
}

export function TerrainLayer({
  part = 'all', areas, types, groundColor, editing, editable, selectedId,
  centerline, centerlineWidthM, draft, draftCursor, draftLine, draftWidthM,
  draftColor, draftWillClose, onVertexMove, onVertexDelete, onEdgeInsert,
  scatterPreview, footprints,
}: TerrainLayerProps) {
  const { view, w, h } = useMapView()

  const selected = useMemo(
    () => areas.find((a) => a.id === selectedId) || null,
    [areas, selectedId],
  )

  /** The draft as it is drawn: the clicked points plus, while the cursor is
   *  over the canvas, the point the next click would add. */
  const draftPts = useMemo(() => (draftCursor
    ? [...draft, [draftCursor.x, draftCursor.z] as [number, number]]
    : draft), [draft, draftCursor])

  /** The ribbon a LINE draft would become — regenerated on every click and on
   *  every cursor move. The centre line alone is not a preview: the width is
   *  what actually gets painted, and only the generated outline shows it. */
  const draftRibbon = useMemo(() => (
    draftLine && draftPts.length >= 2 ? strokeToPolygon(draftPts, draftWidthM) : null
  ), [draftLine, draftPts, draftWidthM])

  /**
   * The scatter of every area, sampled ONCE per data change — in WORLD
   * metres, so panning and zooming only re-project it.
   *
   * The points come from `scatterInstances` (@anima/scene-render), the very
   * call `client3d/src/scene/ground.ts` makes with the very same seed
   * (`scatterSeed(area.id, index)`), the same cleaned ring and the same
   * footprints. Preview and world are therefore identical by construction and
   * not by two files being kept in step — that is why the sampler is shared at
   * all.
   *
   * The rings are cleaned ONCE up front, because an area also has to know the
   * rings of the areas ABOVE it: only the topmost area of a spot scatters
   * there. `areas` arrives bottom to top, so those are the rings after its own
   * index.
   */
  const scatterDots = useMemo(() => {
    // The ground part draws no dots, and sampling for it would mean paying the
    // whole scatter twice per render once the layer is split in two.
    if (!scatterPreview || part === 'ground') return []
    const out: { x: number; z: number; color: string }[] = []
    const rings = areas.map((a) => cleanRing(a.polygon))
    areas.forEach((a, ai) => {
      const entries = readScatter(a.meta)
      if (!entries.length) return
      const ring = rings[ai]
      if (ring.length < 3) return
      const areaM2 = polygonArea(ring)
      const occluders = rings.slice(ai + 1).filter((r) => r.length >= 3)
      entries.forEach((e, i) => {
        if (out.length >= SCATTER_PREVIEW_MAX) return
        const color = scatterColor(i)
        for (const p of scatterInstances({
          ring, areaM2, densityPer100m2: e.density_per_100m2,
          seed: scatterSeed(a.id, i), footprints, occluders,
        })) {
          if (out.length >= SCATTER_PREVIEW_MAX) break
          out.push({ x: p.x, z: p.z, color })
        }
      })
    })
    return out
  }, [areas, footprints, part, scatterPreview])

  if (!w || !h) return null

  // Unpainted ground: the default kind, same treatment as a painted area so
  // the two can be compared by eye. Empty until the catalog has answered —
  // colouring the whole world grey to mean "not loaded yet" would be a
  // statement about the ground, not about the load.
  const ground = groundColor ? (
    <rect x={0} y={0} width={w} height={h} fill={groundColor}
      fillOpacity={FILL_OPACITY} pointerEvents="none" />
  ) : null
  // The ground part is the wash and NOTHING else — returned here so the paint
  // part below stays one unbroken order to read.
  if (part === 'ground') return <g>{ground}</g>

  // What the handles sit on as it is being edited: the CENTRE LINE of a stroke
  // area, the polygon of an ordinary one. A centre line is OPEN (no wrap-around
  // edge, and two points already make one); a polygon closes and needs three.
  const editPts: Array<[number, number]> = selected
    ? (centerline || selected.polygon)
    : []
  const editClosed = !centerline
  const editMin = centerline ? 2 : 3
  // While a line point is dragged the RIBBON follows it live (the shared
  // handles call this with the dragged points); the filled area underneath
  // only catches up once the write comes back. Should the dragged line
  // degenerate on the way, the stored polygon is shown instead of nothing.
  const outlineOf = centerline
    ? (pts: Array<[number, number]>) => (
      strokeToPolygon(pts, centerlineWidthM) || selected?.polygon || [])
    : undefined
  // Are the handles on screen? Only then do they draw the outline themselves,
  // and only then does the static selection outline step aside.
  const handlesLive = !!selected && editing && editable
    && editPts.length >= editMin

  return (
    <g>
      {part === 'all' ? ground : null}
      <g pointerEvents="none">
        {areas.map((a) => {
          if (a.polygon.length < 3) return null
          const known = !!types[a.kind]
          const color = typeColor(types, a.kind)
          const c = centroid(a.polygon)
          const cp = worldToScreen(c[0], c[1], view, w, h)
          return (
            <g key={a.id}>
              {/* evenodd, not SVG's nonzero default: the engine answers point
                  queries by ray casting (`world_geometry.point_in_polygon`),
                  which IS the even-odd rule. On a bow tie the two disagree —
                  nonzero would paint a centre the engine calls OUTSIDE. */}
              <path d={worldPolyToPath(a.polygon, view, w, h)}
                fill={color} fillOpacity={FILL_OPACITY} fillRule="evenodd"
                stroke={color} strokeWidth={1} strokeOpacity={0.75}
                strokeDasharray={known ? undefined : '5 4'} />
              {known ? null : (
                <text x={cp.x} y={cp.y + 5} fontSize={15} textAnchor="middle"
                  fill={COL_WARN}>⚠</text>
              )}
            </g>
          )
        })}
      </g>

      {/* What the areas grow, seen from above — the SAME points the 3D world
          plants. Inert to the pointer: this is a view, and a click on it has
          to reach the canvas underneath, which is where the area hit test
          lives. */}
      {scatterDots.length ? (
        <g pointerEvents="none">
          {scatterDots.map((d, i) => {
            const s = worldToScreen(d.x, d.z, view, w, h)
            return (
              <circle key={`s${i}`} cx={s.x} cy={s.y} r={SCATTER_DOT_R}
                fill={d.color} fillOpacity={0.9} />
            )
          })}
        </g>
      ) : null}

      {/* The outline of the SELECTED area — an overlay, not the stroke of its
          own fill: an area painted on top of it would otherwise cover the very
          outline that says what is selected. While the handles are live they
          draw their own (drag-following) outline, so this one steps aside
          instead of leaving a stale ring behind. An area whose kind the
          catalog no longer knows has nothing to grab (every write would be
          refused on the kind) and keeps this outline. */}
      {selected && selected.polygon.length >= 3 && !handlesLive ? (
        <path d={worldPolyToPath(selected.polygon, view, w, h)} fill="none"
          stroke={COL_SELECTED} strokeWidth={2} pointerEvents="none" />
      ) : null}

      {/* The centre line of the selected stroke area, dashed — the recipe is
          not the shape, so it is drawn as a hint over it. While the handles
          are live they draw their own (drag-following) copy of it, so this one
          steps aside instead of leaving a second, stale line behind. */}
      {selected && centerline && centerline.length >= 2
        && !(editing && editable) ? (
          <path d={worldPolyToPath(centerline, view, w, h, false)} fill="none"
            stroke={COL_SELECTED} strokeWidth={1.5} strokeDasharray="7 4"
            strokeOpacity={0.9} pointerEvents="none" />
        ) : null}

      {/* Handles of the selected area — the only interactive part, and the
          SHARED gesture (`PolygonHandles`). An area whose kind the catalog no
          longer knows gets no handles: every write would be refused on the
          kind before the polygon is even read. Its outline is the overlay
          above, which is drawn for every selection. */}
      {handlesLive ? (
        <PolygonHandles
          points={editPts}
          closed={editClosed}
          color={COL_SELECTED}
          outlineOf={outlineOf}
          dashed={!!centerline}
          minPoints={editMin}
          onMove={onVertexMove}
          onDelete={onVertexDelete}
          onInsert={onEdgeInsert}
        />
      ) : null}

      {/* The polygon being painted: an OPEN line to the cursor, closed only
          when the click actually closes it. A LINE draft never closes — what
          it fills is the generated ribbon under the centre line. */}
      {draft.length ? (
        <g pointerEvents="none">
          {/* Same even-odd rule as a saved area: the preview must show the
              shape the engine will read back, self-crossings included. */}
          {draftLine ? (
            <>
              {draftRibbon ? (
                <path d={worldPolyToPath(draftRibbon, view, w, h)}
                  fill={draftColor} fillOpacity={FILL_OPACITY * 0.6}
                  fillRule="evenodd"
                  stroke={draftColor} strokeWidth={1} strokeOpacity={0.8} />
              ) : null}
              <path d={worldPolyToPath(draftPts, view, w, h, false)} fill="none"
                stroke={COL_DRAFT} strokeWidth={2} strokeDasharray="6 3" />
            </>
          ) : (
            <path d={worldPolyToPath(draftPts, view, w, h, draft.length >= 3)}
              fill={draft.length >= 3 ? draftColor : 'none'}
              fillOpacity={draft.length >= 3 ? FILL_OPACITY * 0.6 : 0}
              fillRule="evenodd"
              stroke={COL_DRAFT} strokeWidth={2} strokeDasharray="6 3" />
          )}
          {draft.map((p, i) => {
            const s = worldToScreen(p[0], p[1], view, w, h)
            const first = i === 0
            return (
              <circle key={`d${i}`} cx={s.x} cy={s.y}
                r={first && draftWillClose ? HANDLE_R + 3 : 3}
                fill={first && draftWillClose ? COL_DRAFT : '#0d1117'}
                stroke={COL_DRAFT} strokeWidth={2} />
            )
          })}
        </g>
      ) : null}
    </g>
  )
}
