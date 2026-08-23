/**
 * HeightLayer — the authored world relief on the map, drawn INSIDE the
 * `MapCanvas` SVG (§ A16).
 *
 * A height area is a polygon in world metres plus a height and a ramp width;
 * the server rasters those into the grid every client samples. This layer
 * shows exactly what was AUTHORED, never the raster: outline, fill by sign,
 * and the two numbers written into the shape. That is the whole design
 * decision of v1 — NO HILLSHADE, no contour lines, no rendering of the
 * interpolated field. A shaded picture would be a second, prettier answer to
 * "how high is it here" that nobody could compare with the one the rules use,
 * and the numbers are what an author actually edits.
 *
 * In its own mode it is drawn FULL: filled by sign, labelled, editable.
 * Outside it the layer stays on the canvas as SUBDUED contours (the "Contours"
 * view switch, on by default) — outlines only, no fill, everything at
 * `SUBDUED_OPACITY`, and inert. That keeps the old objection answered: two
 * half-transparent polygon STACKS on top of each other stop being readable as
 * either, so the background copy is line work, not a second stack, and it says
 * where the ground rises while somebody paints terrain or places props.
 *
 * The handles are the SHARED gesture (`PolygonHandles`), the same one the
 * painted terrain is reshaped with.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { useMapView } from './MapCanvas'
import { worldPolyToPath, worldToScreen } from './mapMath'
import { PolygonHandles } from './PolygonHandles'
import { tooSteep } from './heightMath'
import type { HeightArea } from './mapTypes'

/** Ground that rises, ground that sinks, and the selection. Two colours
 *  because the sign is the first thing to read off a relief — a hollow drawn
 *  like a hill is a map that lies at a glance. */
const COL_HILL = '#e3b341'
const COL_HOLLOW = '#a371f7'
const COL_SELECTED = '#58a6ff'
const COL_DRAFT = '#3fb950'
const COL_WARN = '#d29922'

/** Which way the ground goes, as a colour. Exported because the tray list says
 *  the same thing about the same area, and two tables of colours for one
 *  meaning drift apart. */
export function heightColor(m: number): string {
  return m < 0 ? COL_HOLLOW : COL_HILL
}

/** Light enough that the painted ground and the metre grid read through it —
 *  a height area says something ABOUT ground that stays visible. */
const FILL_OPACITY = 0.22

/** How strong the layer reads OUTSIDE the heights mode. Low enough that the
 *  active tool's own colours stay the foreground, high enough that a hill's
 *  outline and its metre number are still readable over painted ground. */
const SUBDUED_OPACITY = 0.45

/** Radius of a draft vertex marker, in pixels (the handle radius). */
const HANDLE_R = 5

/** Arithmetic mean of the vertices — good enough to hang a label on. */
function centroid(poly: Array<[number, number]>): [number, number] {
  let x = 0
  let z = 0
  for (const [px, pz] of poly) { x += px; z += pz }
  return [x / poly.length, z / poly.length]
}

/** The height with its sign spelled out: a relief is a difference, so "5 m"
 *  alone would leave the reader to guess which way. */
export function fmtHeight(m: number): string {
  const r = Math.round(m * 100) / 100
  return (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r) + ' m'
}

export interface HeightLayerProps {
  areas: HeightArea[]
  selectedId: string
  /** Handles are live only while an area is selected for editing. */
  editing: boolean
  /** Drawn as background contours instead of the editable relief: no fill, no
   *  handles, no draft, no pointer events, and the whole group dimmed. True in
   *  every mode BUT heights. */
  subdued: boolean
  /** The two walk limits (worldmap payload) — an area whose ramp is steeper
   *  than they allow is marked here and explained in its chip. */
  maxSlopeDeg: number
  maxStepM: number
  /** The polygon being drawn (world metres) and the cursor it follows. */
  draft: Array<[number, number]>
  draftCursor: { x: number; z: number } | null
  /** The cursor sits inside the close tolerance of the first vertex. */
  draftWillClose: boolean
  onVertexMove: (index: number, x: number, z: number) => void
  onVertexDelete: (index: number) => void
  onEdgeInsert: (index: number, x: number, z: number) => void
}

export function HeightLayer({
  areas, selectedId, editing, subdued, maxSlopeDeg, maxStepM, draft, draftCursor,
  draftWillClose,
  onVertexMove, onVertexDelete, onEdgeInsert,
}: HeightLayerProps) {
  const { t } = useI18n()
  const { view, w, h } = useMapView()
  if (!w || !h) return null

  const selected = areas.find((a) => a.id === selectedId) || null
  const draftPts = draftCursor
    ? [...draft, [draftCursor.x, draftCursor.z] as [number, number]]
    : draft

  return (
    // Subdued the WHOLE group is inert, not just its parts: the active tool
    // owns every click on this canvas, and a background picture that swallowed
    // one would be a defect nobody could see the cause of.
    <g opacity={subdued ? SUBDUED_OPACITY : undefined}
      pointerEvents={subdued ? 'none' : undefined}>
      <g pointerEvents="none">
        {areas.map((a) => {
          if (a.polygon.length < 3) return null
          const color = heightColor(a.height_m)
          // Nothing is SELECTED outside the heights mode — the selection is a
          // state of that editor, and drawing it elsewhere would promise an
          // edit the mode cannot do.
          const isSel = !subdued && a.id === selectedId
          const c = centroid(a.polygon)
          const cp = worldToScreen(c[0], c[1], view, w, h)
          const steep = tooSteep(a.height_m, a.falloff_m, maxSlopeDeg, maxStepM)
          return (
            <g key={a.id}>
              {/* evenodd like every other polygon here: the engine answers
                  point queries by ray casting, which IS the even-odd rule. */}
              <path d={worldPolyToPath(a.polygon, view, w, h)}
                fill={subdued ? 'none' : color}
                fillOpacity={subdued ? 0 : FILL_OPACITY} fillRule="evenodd"
                stroke={isSel ? COL_SELECTED : color}
                strokeWidth={isSel ? 2 : 1.5}
                strokeOpacity={isSel ? 1 : 0.85} />
              <text x={cp.x} y={cp.y} fontSize={13} textAnchor="middle"
                fill={color} stroke="#0d1117" strokeWidth={3}
                paintOrder="stroke" fontWeight={600}>
                {fmtHeight(a.height_m)}
              </text>
              {/* The ramp belongs to EDITING the relief — outside the heights
                  mode a contour answers "how high", nothing more. */}
              {subdued ? null : (
                <text x={cp.x} y={cp.y + 14} fontSize={11} textAnchor="middle"
                  fill={steep ? COL_WARN : color} stroke="#0d1117"
                  strokeWidth={3} paintOrder="stroke">
                  {(steep ? '⚠ ' : '')
                    + t('ramp {n} m').replace('{n}', String(a.falloff_m))}
                </text>
              )}
            </g>
          )
        })}
      </g>

      {!subdued && editing && selected && selected.polygon.length >= 3 ? (
        <PolygonHandles
          points={selected.polygon}
          closed
          color={COL_SELECTED}
          minPoints={3}
          onMove={onVertexMove}
          onDelete={onVertexDelete}
          onInsert={onEdgeInsert}
        />
      ) : null}

      {/* The ring being drawn: open to the cursor, closed only when the click
          actually closes it — the terrain draft's rules, because it is the
          same gesture on the same canvas. */}
      {!subdued && draft.length ? (
        <g pointerEvents="none">
          <path d={worldPolyToPath(draftPts, view, w, h, draft.length >= 3)}
            fill={draft.length >= 3 ? COL_HILL : 'none'}
            fillOpacity={draft.length >= 3 ? FILL_OPACITY : 0}
            fillRule="evenodd"
            stroke={COL_DRAFT} strokeWidth={2} strokeDasharray="6 3" />
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
