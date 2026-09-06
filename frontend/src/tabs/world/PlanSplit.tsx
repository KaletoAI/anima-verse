/**
 * PlanSplit — the floor-plan tab's outer split: the 2D workbench on the left,
 * the 3D preview as a DOCK on the right, and a draggable grip between them.
 *
 * WHY IT EXISTS. The tab used to be a hard `ga-loc-twocol--5050` grid, so the
 * plan could never be wider than half the page however much screen there was —
 * and inside that half sat a 420 px canvas, a tool rail and a settings column.
 * The plan ended up with roughly a third of the width it was drawing metres
 * on. Here the dock's width belongs to the author: drag the grip, or fold the
 * dock away entirely and let the plan have the row.
 *
 * The width is a PERCENTAGE of the split, kept in localStorage, so it survives
 * a reload and a different window size alike. Under 900 px the CSS stops
 * splitting and the two stack, like every other split on this page.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'

/** Narrowest and widest the dock may be dragged, in percent of the split. */
const MIN_PCT = 18
const MAX_PCT = 60
const DEFAULT_PCT = 34
const STORE_KEY = 'av.floorplan.previewPct'
const STORE_OPEN = 'av.floorplan.previewOpen'

function readStored(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(key)
    const n = raw === null ? NaN : Number(raw)
    return Number.isFinite(n) ? n : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* private mode / storage off — the split simply starts at its default. */
  }
}

interface Props {
  /** The 2D workbench. Gets everything the dock does not take. */
  main: ReactNode
  /** The 3D preview. Not rendered at all while the dock is folded away, so a
   *  folded preview costs no WebGL context either. */
  side: ReactNode
  /** Label of the fold button, e.g. "3D preview". */
  sideLabel: string
}

export function PlanSplit({ main, side, sideLabel }: Props) {
  const { t } = useI18n()
  const [pct, setPct] = useState(() => readStored(STORE_KEY, DEFAULT_PCT))
  const [open, setOpen] = useState(() => readStored(STORE_OPEN, 1) !== 0)
  const rootRef = useRef<HTMLDivElement>(null)
  const sideRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef(false)

  const apply = useCallback((next: number) => {
    const clamped = Math.round(Math.min(MAX_PCT, Math.max(MIN_PCT, next)))
    setPct(clamped)
    write(STORE_KEY, String(clamped))
  }, [])

  // Dragging is tracked on the WINDOW, not on the grip: the pointer leaves the
  // 12 px strip on the first move, and a grip that only hears its own element
  // would drop the drag immediately.
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragRef.current) return
      const el = rootRef.current
      const side = sideRef.current
      if (!el || !side) return
      const rect = el.getBoundingClientRect()
      if (rect.width <= 0) return
      e.preventDefault()
      // Measured from the DOCK's own right edge, not the split's: the fold
      // button sits to the right of the dock and is part of the split, so
      // using the split's edge would offset every drag by a button width.
      const right = side.getBoundingClientRect().right
      apply(((right - e.clientX) / rect.width) * 100)
    }
    const onUp = () => { dragRef.current = false }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [apply])

  return (
    <div className="ga-plan-split" ref={rootRef}>
      <div className="ga-plan-split-main">
        {main}
      </div>
      {open ? (
        <>
          <div
            className="ga-plan-split-grip"
            role="separator"
            aria-orientation="vertical"
            aria-label={t('Drag to resize the 3D preview')}
            title={t('Drag to resize the 3D preview — double-click restores the default width.')}
            onPointerDown={(e) => { e.preventDefault(); dragRef.current = true }}
            onDoubleClick={() => apply(DEFAULT_PCT)}
          />
          <div ref={sideRef} className="ga-plan-split-side"
            style={{ width: `${pct}%` }}>
            {side}
          </div>
        </>
      ) : null}
      <button
        type="button"
        className={`ga-btn ga-btn-sm${open ? '' : ' ga-btn-primary'}`}
        style={{ flex: '0 0 auto', marginLeft: 4, alignSelf: 'flex-start' }}
        title={open
          ? t('Fold the 3D preview away — the plan takes the whole row.')
          : t('Show the 3D preview beside the plan again.')}
        onClick={() => {
          setOpen((v) => {
            write(STORE_OPEN, v ? '0' : '1')
            return !v
          })
        }}
      >
        {open ? '◨' : '◧'} {sideLabel}
      </button>
    </div>
  )
}
