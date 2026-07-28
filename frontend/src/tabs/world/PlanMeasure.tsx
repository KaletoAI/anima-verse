/**
 * PlanMeasure — the reference sizes of the 2D floor plan.
 *
 * Same rule as measureKit.ts for the 3D surfaces (user directive 2026-07-28):
 * "Kein Maß ohne Maßstab." The plan draws in FRACTIONS of the reference
 * square, so a rectangle on it says nothing about real size until something
 * human stands next to it. Three aids, all fed by the one scale anchor
 * (`map3d.plan_width_m`) — without it they stay away, and their absence is
 * the honest answer:
 *
 *   1. a scale bar that names the length it draws,
 *   2. a grid in whole metres, adapting its step to the zoom,
 *   3. the 1.70 m figure — from above, at true scale, draggable to whatever
 *      you are judging right now.
 *
 * Pure view state: nothing here is persisted, nothing here is geometry.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { fmtM, niceDown, niceUp } from './planGeometry'
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
  /** Real width the plan square represents (0 = no anchor → no aids). */
  planWidthM: number
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
export function PlanScaleBar({ planWidthM, canvasPx }: ScaleProps) {
  if (!(planWidthM > 0)) return null
  const pxPerM = canvasPx / planWidthM
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
 * Grid in whole metres over the plan square. The step follows the zoom (lines
 * never crowd closer than ~14 px), every fifth line is stronger.
 */
export function PlanMetreGrid({ planWidthM, canvasPx }: ScaleProps) {
  if (!(planWidthM > 0)) return null
  const pxPerM = canvasPx / planWidthM
  const step = niceUp(14 / pxPerM)
  // Multiples of the step, not an accumulating sum — 0.25 m steps would
  // otherwise drift into 0.7500000000000001 after a few rounds.
  const count = Math.max(0, Math.floor((planWidthM - 1e-6) / step))
  const lines = Array.from({ length: count }, (_, i) => (i + 1) * step)
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{
      position: 'absolute', inset: 0, width: '100%', height: '100%',
      pointerEvents: 'none',
    }}>
      {lines.map((m, i) => {
        const p = (m / planWidthM) * 100
        const o = (i + 1) % 5 === 0 ? 0.4 : 0.17
        return (
          <g key={m} stroke={GRID_COLOR} strokeWidth={1} opacity={o}
            vectorEffect="non-scaling-stroke">
            <line x1={p} y1={0} x2={p} y2={100} vectorEffect="non-scaling-stroke" />
            <line x1={0} y1={p} x2={100} y2={p} vectorEffect="non-scaling-stroke" />
          </g>
        )
      })}
    </svg>
  )
}

/**
 * The 1.70 m person from above, at the plan's true scale: the 0.60 m circle
 * of occupied space, shoulders and head. Drag it onto whatever is being
 * judged — a door width, a corridor, a bed.
 *
 * It never scales with anything but the plan width; that is the whole point.
 */
export function PlanFigure({ planWidthM, pos, onPos, canvasRef, interactive }: {
  planWidthM: number
  pos: [number, number]
  onPos: (p: [number, number]) => void
  canvasRef: RefObject<HTMLDivElement | null>
  /** Off while a click tool is armed — the plan gets the click, not us. */
  interactive: boolean
}) {
  const { t } = useI18n()
  if (!(planWidthM > 0)) return null
  const frac = FIG.spaceM / planWidthM

  const startDrag = (e: ReactPointerEvent) => {
    if (!interactive) return
    e.stopPropagation()
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const move = (ev: PointerEvent) => {
      const r = canvas.getBoundingClientRect()
      const cl = (v: number) => Math.min(1, Math.max(0, v))
      onPos([cl((ev.clientX - r.left) / r.width),
             cl((ev.clientY - r.top) / r.height)])
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
        left: `${pos[0] * 100}%`, top: `${pos[1] * 100}%`,
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
        1.70 m
      </span>
    </div>
  )
}
