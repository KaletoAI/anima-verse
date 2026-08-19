/**
 * PlanMeasure — the reference sizes of the 2D floor plan.
 *
 * Same rule as measureKit.ts for the 3D surfaces (user directive 2026-07-28):
 * "Kein Maß ohne Maßstab." Since the metric wave (contract v6 Nr. 2) the plan
 * draws in LOCAL METRES, but a rectangle on a screen still says nothing about
 * real size until something human stands next to it. Three aids, all fed by
 * the drawing VIEWPORT (`PlanView` — how many metres the canvas spans and
 * where its min corner sits):
 *
 *   1. a scale bar that names the length it draws,
 *   2. a grid in whole metres of the LOCATION frame, adapting its step to the
 *      zoom and labelling its coordinates, so a line is not just spacing but a
 *      readable position (the "Maße brauchen Bezug" readback),
 *   3. the 1.70 m figure — from above, at true scale, draggable to whatever
 *      you are judging right now.
 *
 * Pure view state: nothing here is persisted, nothing here is geometry.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { fmtM, niceDown, niceUp, viewFx, viewFz } from './planGeometry'
import type { PlanView } from './planGeometry'
import type { PointerEvent as ReactPointerEvent, RefObject } from 'react'

/** How the figure is built (metres, seen from above). */
const FIG = {
  /** The space a standing person occupies — the dashed circle. */
  spaceM: 0.6,
  /** Shoulder width / body depth as a share of that circle. */
  shoulderR: 0.375,
  bodyR: 0.25,
  headR: 0.16,
  headY: -0.09,
}

const AID_COLOR = '#f0f6fc'
const GRID_COLOR = '#8b949e'

interface ScaleProps {
  /** The metre window the square canvas shows. */
  view: PlanView
  /**
   * The canvas edge as it really is on screen, MEASURED — zoom included, and
   * the shrink a narrow pane forces on it too. An aid that computes pixels
   * from an assumed 420 would lie about exactly the thing it is here to say.
   */
  canvasPx: number
}

/**
 * The classic four-segment map scale, over the plan's bottom-left corner.
 * Lives OUTSIDE the scrolling canvas so a zoomed-in plan cannot scroll its
 * own scale out of view.
 */
export function PlanScaleBar({ view, canvasPx }: ScaleProps) {
  if (!(view.size > 0)) return null
  const pxPerM = canvasPx / view.size
  // A bar wants about a third of the visible width; the nice step decides
  // the rest, so the number stays round while the zoom changes.
  const barM = niceDown(140 / pxPerM)
  const segPx = (barM * pxPerM) / 4
  return (
    <div style={{
      position: 'absolute', left: 8, bottom: 8, pointerEvents: 'none',
      display: 'flex', alignItems: 'flex-end', gap: 5,
    }}>
      <div style={{ display: 'flex', height: 6, boxShadow: '0 0 0 1px #0d1117' }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} style={{
            width: segPx, background: i % 2 ? AID_COLOR : '#0d1117',
            borderTop: `1px solid ${AID_COLOR}`,
            borderBottom: `1px solid ${AID_COLOR}`,
          }} />
        ))}
      </div>
      <span style={{
        fontSize: 10, lineHeight: '10px', color: AID_COLOR,
        textShadow: '0 0 3px #0d1117, 0 0 3px #0d1117',
      }}>
        {fmtM(barM)} m
      </span>
    </div>
  )
}

/**
 * Grid in whole metres of the LOCATION-LOCAL frame. The step follows the zoom
 * (lines never crowd closer than ~14 px), every fifth line is stronger and
 * carries its coordinate — the pin is where x = 0 meets z = 0, and that pair
 * of zero lines is drawn in the accent colour so the origin is never guessed.
 */
export function PlanMetreGrid({ view, canvasPx }: ScaleProps) {
  if (!(view.size > 0)) return null
  const pxPerM = canvasPx / view.size
  const step = niceUp(14 / pxPerM)
  // Multiples of the step ANCHORED ON THE FRAME ORIGIN, not on the viewport
  // corner: a grid line has to mean "x = 12 m from the pin", otherwise it is
  // decoration. Computed as index × step (never an accumulating sum — 0.25 m
  // steps would drift into 0.7500000000000001 after a few rounds).
  const first = Math.ceil(view.x0 / step)
  const last = Math.floor((view.x0 + view.size) / step)
  const firstZ = Math.ceil(view.z0 / step)
  const lastZ = Math.floor((view.z0 + view.size) / step)
  const xs = Array.from({ length: Math.max(0, last - first + 1) },
    (_, i) => (first + i) * step)
  const zs = Array.from({ length: Math.max(0, lastZ - firstZ + 1) },
    (_, i) => (firstZ + i) * step)
  // A label on every fifth line only — a labelled line every 14 px is noise.
  const labelled = (m: number) => Math.abs(Math.round(m / step) % 5) === 0
  const line = (m: number) => (Math.abs(m) < 1e-9 ? 0.75 : labelled(m) ? 0.4 : 0.17)
  const col = (m: number) => (Math.abs(m) < 1e-9 ? '#58a6ff' : GRID_COLOR)
  return (
    <>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{
        position: 'absolute', inset: 0, width: '100%', height: '100%',
        pointerEvents: 'none',
      }}>
        {xs.map((m) => (
          <line key={`x${m}`} x1={viewFx(view, m) * 100} y1={0}
            x2={viewFx(view, m) * 100} y2={100} stroke={col(m)} strokeWidth={1}
            opacity={line(m)} vectorEffect="non-scaling-stroke" />
        ))}
        {zs.map((m) => (
          <line key={`z${m}`} x1={0} y1={viewFz(view, m) * 100}
            x2={100} y2={viewFz(view, m) * 100} stroke={col(m)} strokeWidth={1}
            opacity={line(m)} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      {/* Readback: the coordinate of every fifth line, in metres from the pin
          — top edge for x, left edge for z. Pixel-sized text, so it stays
          legible at any zoom. */}
      {xs.filter(labelled).map((m) => (
        <span key={`lx${m}`} style={{
          position: 'absolute', left: `${viewFx(view, m) * 100}%`, top: 1,
          transform: 'translateX(2px)', fontSize: 9, lineHeight: '10px',
          color: Math.abs(m) < 1e-9 ? '#58a6ff' : GRID_COLOR, opacity: 0.9,
          pointerEvents: 'none', whiteSpace: 'nowrap',
          textShadow: '0 0 3px #0d1117, 0 0 3px #0d1117',
        }}>{fmtM(m)}</span>
      ))}
      {zs.filter(labelled).map((m) => (
        <span key={`lz${m}`} style={{
          position: 'absolute', top: `${viewFz(view, m) * 100}%`, left: 2,
          transform: 'translateY(1px)', fontSize: 9, lineHeight: '10px',
          color: Math.abs(m) < 1e-9 ? '#58a6ff' : GRID_COLOR, opacity: 0.9,
          pointerEvents: 'none', whiteSpace: 'nowrap',
          textShadow: '0 0 3px #0d1117, 0 0 3px #0d1117',
        }}>{fmtM(m)}</span>
      ))}
    </>
  )
}

/**
 * The 1.70 m person from above, at the plan's true scale: the 0.60 m circle
 * of occupied space, shoulders and head. Drag it onto whatever is being
 * judged — a door width, a corridor, a bed. Its position is LOCAL METRES, and
 * the label says where it stands, so the figure doubles as a coordinate probe.
 *
 * It never scales with anything but the viewport; that is the whole point.
 */
export function PlanFigure({ view, pos, onPos, canvasRef, interactive }: {
  view: PlanView
  /** Position in LOCATION-LOCAL metres. */
  pos: [number, number]
  onPos: (p: [number, number]) => void
  canvasRef: RefObject<HTMLDivElement | null>
  /** Off while a click tool is armed — the plan gets the click, not us. */
  interactive: boolean
}) {
  const { t } = useI18n()
  if (!(view.size > 0)) return null
  const frac = FIG.spaceM / view.size

  const startDrag = (e: ReactPointerEvent) => {
    if (!interactive) return
    e.stopPropagation()
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const move = (ev: PointerEvent) => {
      const r = canvas.getBoundingClientRect()
      onPos([view.x0 + ((ev.clientX - r.left) / r.width) * view.size,
             view.z0 + ((ev.clientY - r.top) / r.height) * view.size])
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: `${viewFx(view, pos[0]) * 100}%`,
        top: `${viewFz(view, pos[1]) * 100}%`,
        width: `${frac * 100}%`, height: `${frac * 100}%`,
        transform: 'translate(-50%, -50%)',
        pointerEvents: interactive ? 'auto' : 'none',
      }}
    >
      {/* Hit area — the figure itself is only a few pixels on a wide plan. */}
      <div
        title={t('Reference: a 1.70 m person from above (0.60 m of occupied space, 0.45 m shoulders). Drag it to whatever you are sizing up.')}
        onPointerDown={startDrag}
        onClick={(e) => e.stopPropagation()}
        style={{ position: 'absolute', inset: -9, cursor: 'grab' }}
      />
      <svg viewBox="-0.5 -0.5 1 1" preserveAspectRatio="none" style={{
        position: 'absolute', inset: 0, width: '100%', height: '100%',
        overflow: 'visible', pointerEvents: 'none',
      }}>
        <circle cx={0} cy={0} r={0.5} fill="rgba(240,246,252,0.10)"
          stroke={AID_COLOR} strokeWidth={1} vectorEffect="non-scaling-stroke"
          strokeDasharray="3 2" opacity={0.6} />
        <ellipse cx={0} cy={0.02} rx={FIG.shoulderR} ry={FIG.bodyR}
          fill="rgba(240,246,252,0.85)" stroke="#0d1117" strokeWidth={1}
          vectorEffect="non-scaling-stroke" />
        <circle cx={0} cy={FIG.headY} r={FIG.headR} fill={AID_COLOR}
          stroke="#0d1117" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      </svg>
      <span style={{
        position: 'absolute', left: '50%', top: '50%',
        marginLeft: 10, marginTop: -6,
        fontSize: 10, lineHeight: '12px', whiteSpace: 'nowrap',
        color: AID_COLOR, textShadow: '0 0 3px #0d1117, 0 0 3px #0d1117',
        pointerEvents: 'none',
      }}>
        1.70 m · {fmtM(pos[0])} / {fmtM(pos[1])} m
      </span>
    </div>
  )
}
