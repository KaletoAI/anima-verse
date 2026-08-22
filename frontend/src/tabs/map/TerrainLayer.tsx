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
 * The SCATTER PREVIEW has two modes and the zoom decides between them: close
 * enough that one screen's true instance count fits the frame budget, it draws
 * the very props the 3D client plants (the shared 64 m cell sampler, same
 * seeds); wider than that, the thinned whole-world sample of before — which
 * now says so on the picture. The maths of both, and the hysteresis between
 * them, is `mapMath` (see the scatter-preview section there).
 *
 * Inside the paint part the order never changes: fills, then the flow arrows
 * of the water areas, then the scatter preview, then the selection outline /
 * centre line / handles / draft. The
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
import { useEffect, useMemo, useState } from 'react'
import type { ScatterFootprint } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { useMapView } from './MapCanvas'
import {
  decorateStroke, flowArrow, flowArrowsAlong, flowAxisPoints, scatterAreaCosts,
  scatterAreaPlan, scatterPreviewJobs, scatterThinnedByArea,
  scatterThinnedPercentText, scatterWindowDots, strokeToPolygon,
  visibleWorldRect, worldPolyToPath, worldToScreen,
  type FlowArrow, type ScatterDot, type ScatterPreviewJob,
  type ScatterThinnedDraw, type StrokeDeco,
} from './mapMath'
import { PolygonHandles } from './PolygonHandles'
import { isWaterKind, readStrokePoints, readWater } from './mapTypes'
import type { TerrainArea, TerrainType } from './mapTypes'

/** One opacity for every fill — see the module docstring. */
const FILL_OPACITY = 0.45
/** A kind the catalog does not know: grey, and marked as unknown. The SAME
 *  grey the server (`app/core/terrain_types.py: DEFAULT_COLOR`) and the 3D
 *  minimap (`terrainColor`) fall back to — one unknown, one colour. THE one
 *  fallback colour of this app: the type editor (the Terrain tab's
 *  `TerrainDetail`) takes its new-kind default from here instead of keeping a
 *  second literal. */
export const UNKNOWN_COLOR = '#888888'
const COL_SELECTED = '#58a6ff'
const COL_DRAFT = '#3fb950'
const COL_WARN = '#d29922'
/** The flow arrow of a water area: near-white with a dark halo, so it reads on
 *  a light shallow and on a deep blue alike. It is an ANNOTATION, not paint —
 *  it never changes with the kind's own colour. */
const COL_FLOW = '#e6f2ff'
const COL_FLOW_HALO = '#0d2233'

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

/** Radius of a preview dot in pixels. */
const SCATTER_DOT_R = 1.8

/** The canvas' own background (`MapCanvas.BG_COLOR`) — the thinning label is
 *  written over painted ground, so it carries this as a stroke behind its
 *  glyphs (`paint-order: stroke`) and stays readable on any fill. */
const LABEL_BG = '#0d1117'

/** Nothing to draw, as ONE object each: an empty array literal per render
 *  would be a new identity every time and defeat the memos that exist to keep
 *  the inactive mode from doing any work at all. */
const NO_JOBS: ScatterPreviewJob[] = []
const NO_DOTS: ScatterDot[] = []
const NO_THINNED: ScatterThinnedDraw = { dots: NO_DOTS, badges: [] }

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
  /** …and with the stored recipe's decoration, so a dragged wavy line follows
   *  the pointer as the wavy line it is. */
  centerlineDeco: StrokeDeco
  /** The polygon being painted (world metres) and the cursor it follows. */
  draft: Array<[number, number]>
  draftCursor: { x: number; z: number } | null
  /** The running draft is a centre LINE, not an outline: it is drawn open and
   *  the ribbon it would become is previewed underneath it. */
  draftLine: boolean
  /** Width the line draft would get, in metres. */
  draftWidthM: number
  /** …and how the toolbar would bend it. The preview draws the ribbon the
   *  save will produce, deflections included — a straight preview under a
   *  jagged setting would be the one thing nobody could check by eye. */
  draftDeco: StrokeDeco
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
  /** The placed locations, as the DRAWN outlines they cover in WORLD metres
   *  (contract v6 "Gebiete"). Their footprints are kept CLEAR of scatter
   *  (finding B18). The caller turns `map3d.boundary` out of the location's
   *  local frame once per location (§ A1.1) — the shared sampler knows nothing
   *  about pins, and a location without a boundary has no area and simply does
   *  not appear in this list. */
  footprints: readonly ScatterFootprint[]
}

export function TerrainLayer({
  part = 'all', areas, types, groundColor, editing, editable, selectedId,
  centerline, centerlineWidthM, centerlineDeco, draft, draftCursor, draftLine,
  draftWidthM, draftDeco,
  draftColor, draftWillClose, onVertexMove, onVertexDelete, onEdgeInsert,
  scatterPreview, footprints,
}: TerrainLayerProps) {
  const { view, w, h } = useMapView()
  const { t } = useI18n()

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
    draftLine && draftPts.length >= 2
      ? strokeToPolygon(decorateStroke(draftPts, draftDeco.style,
        draftDeco.spacingM, draftDeco.amplitudeM).points, draftWidthM)
      : null
  ), [draftDeco, draftLine, draftPts, draftWidthM])

  /**
   * WHAT GROWS ON THE GROUND, in the two modes of `mapMath`'s preview — and
   * PER AREA, so one big wood cannot decide the picture of the small one
   * beside it.
   *
   * The rows are collected once per data change (`scatterPreviewJobs` —
   * cleaned rings, occluders, true counts); which of the two ways EACH AREA is
   * drawn hangs on what that area alone would cost (`scatterAreaCosts` →
   * `scatterAreaPlan`):
   *
   *  · an area whose own bound fits `SCATTER_AREA_TRUE_MAX`: the covered 64 m
   *    CELLS are enumerated and every instance the 3D client plants is drawn —
   *    the preview and the world are then the same picture, cell for cell
   *    (`scatterWindowDots`);
   *  · an area over it: the whole-area sample thinned to its share of the dot
   *    budget, with a badge on its own centroid saying what fraction of the
   *    authored density that is (`scatterThinnedByArea`).
   *
   * TWO MEMOS, NOT ONE, and each answers the SAME empty object when its half
   * is empty: the true window has to be re-sampled on every pan (that is what
   * makes it true), while the thinned sample must NOT be — it depends on the
   * data and on WHICH areas are thinned, never on where the viewport sits, and
   * re-sampling a world's worth of props for a wheel notch is exactly the cost
   * the overview exists to avoid.
   */
  const rect = useMemo(() => visibleWorldRect(view, w, h), [view, w, h])
  // The ground part draws no dots, and collecting for it would mean paying the
  // whole scatter twice per render once the layer is split in two.
  const jobs = useMemo(() => (scatterPreview && part !== 'ground'
    ? scatterPreviewJobs(areas) : NO_JOBS), [areas, part, scatterPreview])
  const costs = useMemo(() => scatterAreaCosts(jobs, rect), [jobs, rect])
  // The plan, with per-area hysteresis: a pan or a wheel notch at the boundary
  // must not flap an area between its two pictures.
  //
  // THE RULE IS APPLIED IN THE RENDER, and the state only REMEMBERS which
  // areas the last frame drew truly. Reading a stored plan instead would let
  // one frame sample the new costs against the old plan — the frame that
  // switches the preview on while zoomed out would enumerate a world's worth
  // of cells before the correcting effect ever ran, which is the one thing a
  // windowed sampler must never do.
  const [lastTrue, setLastTrue] = useState('')
  const plan = useMemo(
    () => scatterAreaPlan(costs, new Set(lastTrue ? lastTrue.split('\n') : [])),
    [costs, lastTrue],
  )
  // ONE STRING, not a Set: the memos below must not re-run because a new Set
  // of the same ids was built, and a joined key compares by value for free.
  const trueKey = plan.trueIds.join('\n')
  useEffect(() => { setLastTrue(trueKey) }, [trueKey])
  const trueJobs = useMemo(() => {
    const ids = new Set(trueKey ? trueKey.split('\n') : [])
    return ids.size ? jobs.filter((j) => ids.has(j.areaId)) : NO_JOBS
  }, [jobs, trueKey])
  const thinJobs = useMemo(() => {
    const ids = new Set(trueKey ? trueKey.split('\n') : [])
    return jobs.filter((j) => !ids.has(j.areaId))
  }, [jobs, trueKey])
  const windowDots = useMemo(() => (trueJobs.length
    ? scatterWindowDots(trueJobs, rect, footprints) : NO_DOTS),
  [footprints, rect, trueJobs])
  const thinned = useMemo(() => (thinJobs.length
    ? scatterThinnedByArea(thinJobs, footprints) : NO_THINNED),
  [footprints, thinJobs])
  const scatterDots = useMemo(
    () => (thinned.dots.length ? [...windowDots, ...thinned.dots] : windowDots),
    [thinned, windowDots],
  )
  /** …and, for every APPROXIMATED area, how much of it the dots on it are —
   *  the honest half of a sample that cannot show it all. An area drawn
   *  exactly gets none, and neither does one whose share rounded to nothing:
   *  a badge over ground with no dots under it would name a density the
   *  picture does not carry. */
  const badges = useMemo(() => thinned.badges
    .filter((b) => b.drawn > 0 && b.wanted > 0), [thinned])

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
      strokeToPolygon(decorateStroke(pts, centerlineDeco.style,
        centerlineDeco.spacingM, centerlineDeco.amplitudeM).points,
      centerlineWidthM) || selected?.polygon || [])
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

      {/* WHICH WAY THE WATER GOES (§ A16.3, W1/W4a). A flowing area's mirror
          falls downhill, and the one thing an author cannot see in a blue
          polygon is which end of it is the low one.
          TWO KINDS OF AREA, TWO ARROW SHAPES, and the area decides which:
          * DRAWN AS A LINE (W4a) → one arrow per segment of that very line,
            pointing the way `meta.flow_along` reads it. A single arrow through
            the centroid would lie on a meander — on a hairpin it points
            straight across both legs — and the whole point of W4a is that the
            water follows the bends.
          * an ordinary POLYGON → the one arrow on the straight axis of W1,
            through the AREA centroid along `flow_dir_deg`, which is the very
            axis the server builds that profile around.
          The line wins where both are set, exactly as the bake lets it win
          (`heightfield.is_flowing`). Still water gets no arrow at all: a lake
          has no downstream, and an arrow of some default bearing would be an
          invention. Inert to the pointer, like every other overlay here. */}
      <g pointerEvents="none">
        {areas.map((a) => {
          if (!isWaterKind(types[a.kind])) return null
          const water = readWater(a.meta)
          const axis = flowAxisPoints(readStrokePoints(a.meta), water.flow_along)
          const arrows: FlowArrow[] = axis ? flowArrowsAlong(axis) : []
          if (!axis) {
            const one = flowArrow(a.polygon, water.flow_dir_deg)
            if (one) arrows.push(one)
          }
          if (!arrows.length) return null
          const parts: string[] = []
          for (const arrow of arrows) {
            const p0 = worldToScreen(arrow.from[0], arrow.from[1], view, w, h)
            const p1 = worldToScreen(arrow.to[0], arrow.to[1], view, w, h)
            const b0 = worldToScreen(arrow.barbs[0][0], arrow.barbs[0][1],
              view, w, h)
            const b1 = worldToScreen(arrow.barbs[1][0], arrow.barbs[1][1],
              view, w, h)
            // Under six screen pixels of shaft there is nothing left to read —
            // a zoomed-out world would only get a smear of dots. Per arrow, so
            // a long reach of a river keeps its arrow while a short kink beside
            // it drops out instead of taking the whole line down with it.
            if (Math.hypot(p1.x - p0.x, p1.y - p0.y) < 6) continue
            parts.push(`M${p0.x.toFixed(2)} ${p0.y.toFixed(2)}`
              + `L${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`
              + `M${b0.x.toFixed(2)} ${b0.y.toFixed(2)}`
              + `L${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`
              + `L${b1.x.toFixed(2)} ${b1.y.toFixed(2)}`)
          }
          if (!parts.length) return null
          const d = parts.join('')
          return (
            <g key={`flow-${a.id}`}>
              <path d={d} fill="none" stroke={COL_FLOW_HALO} strokeWidth={4}
                strokeLinecap="round" strokeLinejoin="round"
                strokeOpacity={0.55} />
              <path d={d} fill="none" stroke={COL_FLOW} strokeWidth={1.6}
                strokeLinecap="round" strokeLinejoin="round" />
            </g>
          )
        })}
      </g>

      {/* What the areas grow, seen from above — in the true-density mode the
          SAME instances the 3D world plants, cell for cell. Inert to the
          pointer: this is a view, and a click on it has to reach the canvas
          underneath, which is where the area hit test lives. */}
      {scatterDots.length ? (
        <g pointerEvents="none">
          {scatterDots.map((d, i) => {
            const s = worldToScreen(d.x, d.z, view, w, h)
            return (
              <circle key={`s${i}`} cx={s.x} cy={s.y} r={SCATTER_DOT_R}
                fill={scatterColor(d.entry)} fillOpacity={0.9} />
            )
          })}
        </g>
      ) : null}

      {/* …and, for every area too thick to draw whole, what fraction of the
          authored density its dots ARE — ON THAT AREA, at its centroid.
          A preview that shows a hundredth of what grows and says nothing is
          the defect this closes, and since the mode is now an area's own the
          picture is routinely MIXED: one label in a corner would be wrong
          about the exact wood and unattributable for the thinned one. An area
          without a badge is an area drawn exactly. */}
      {badges.map((b) => {
        const s = worldToScreen(b.x, b.z, view, w, h)
        if (s.x < -80 || s.y < -20 || s.x > w + 80 || s.y > h + 20) return null
        return (
          <text key={`b${b.areaId}`} x={s.x} y={s.y} textAnchor="middle"
            fontSize={11} fill={COL_WARN} stroke={LABEL_BG} strokeWidth={3}
            paintOrder="stroke" pointerEvents="none">
            {t('~{p}% of {n} — zoom in for true density')
              .replace('{p}', scatterThinnedPercentText(b.drawn, b.wanted))
              .replace('{n}', String(b.wanted))}
          </text>
        )
      })}

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
