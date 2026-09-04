/**
 * Lightbox — the full-screen overlay all player panels share.
 *
 * Deliberately CONTEXT-INDEPENDENT: a module singleton instead of a React
 * context. That way `open()` is guaranteed to reach the one mounted host
 * (rendered by `LightboxProvider`) regardless of its position in the tree, and
 * immune to context-resolution problems (e.g. a duplicate module instance from
 * code splitting). Any panel opens it via `useLightbox().open({ src | video })`
 * or directly with `openLightbox(...)`. Images zoom towards the cursor with the
 * mouse wheel and can be dragged around while zoomed; a double click toggles
 * between fit and 2.5×. Videos are shown large with controls. Closes on ×, Esc
 * or a click on the dark margin.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './icons'
import { useI18n } from './I18nProvider'
import './Lightbox.css'

export interface LightboxItem {
  src?: string
  video?: string
  alt?: string
  /** Optional one-line note under the media (e.g. provenance of a texture). */
  caption?: string
}

// Module singleton: the mounted host registers its setter here.
let _setItem: ((it: LightboxItem | null) => void) | null = null
export function openLightbox(item: LightboxItem) { _setItem?.(item) }
const _api = { open: openLightbox }
export const useLightbox = () => _api

export function LightboxProvider({ children }: { children: ReactNode }) {
  return (<>{children}<LightboxHost /></>)
}

function LightboxHost() {
  const [item, setItem] = useState<LightboxItem | null>(null)
  useEffect(() => {
    _setItem = setItem
    return () => { if (_setItem === setItem) _setItem = null }
  }, [])
  if (!item) return null
  // Portal to document.body: that way the overlay (position:fixed) escapes any
  // transformed ancestor (react-grid-layout panels use CSS transform).
  return createPortal(<LightboxOverlay item={item} onClose={() => setItem(null)} />, document.body)
}

const SCALE_MIN = 1
const SCALE_MAX = 8
const clampScale = (s: number) => Math.max(SCALE_MIN, Math.min(SCALE_MAX, s))

function LightboxOverlay({ item, onClose }: { item: LightboxItem; onClose: () => void }) {
  const { t } = useI18n()
  const overlayRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [tx, setTx] = useState(0)
  const [ty, setTy] = useState(0)
  const stateRef = useRef({ scale: 1, tx: 0, ty: 0 })
  stateRef.current = { scale, tx, ty }
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null)
  const isVideo = !!item.video
  const [interacted, setInteracted] = useState(false)  // zoom hint until the first action

  const reset = useCallback(() => { setScale(1); setTx(0); setTy(0) }, [])

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Zoom towards the point (mx,my): the pixel under the cursor stays put.
  // Mapping for transform-origin center + `translate(t) scale(s)`:
  //   screenOffsetFromCenter = t + s * localOffset.
  const zoomAt = useCallback((mx: number, my: number, factor: number) => {
    const el = overlayRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const cx = r.left + r.width / 2
    const cy = r.top + r.height / 2
    const { scale: s0, tx: tx0, ty: ty0 } = stateRef.current
    const s1 = clampScale(s0 * factor)
    if (s1 === s0) return
    const px = (mx - cx - tx0) / s0
    const py = (my - cy - ty0) / s0
    if (s1 === 1) { setScale(1); setTx(0); setTy(0); return }
    setScale(s1)
    setTx((mx - cx) - s1 * px)
    setTy((my - cy) - s1 * py)
  }, [])

  // Mouse-wheel zoom (non-passive so preventDefault stops the page scroll).
  useEffect(() => {
    if (isVideo) return
    const el = overlayRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setInteracted(true)
      zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, isVideo])

  const onPointerDown = (e: React.PointerEvent) => {
    if (isVideo) return
    e.stopPropagation()
    setInteracted(true)
    dragRef.current = { x: e.clientX, y: e.clientY, tx: stateRef.current.tx, ty: stateRef.current.ty, moved: false }
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true
    setTx(d.tx + dx)
    setTy(d.ty + dy)
  }
  const onPointerUp = (e: React.PointerEvent) => {
    if (dragRef.current) { e.stopPropagation(); dragRef.current = null }
  }
  const onDoubleClick = (e: React.MouseEvent) => {
    if (isVideo) return
    e.stopPropagation()
    if (stateRef.current.scale > 1.01) reset()
    else zoomAt(e.clientX, e.clientY, 2.5)
  }

  const zoomed = scale > 1.01

  return (
    <div className="lb-overlay" ref={overlayRef}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <button className="lb-close" onClick={onClose} title={t('Close')} aria-label={t('Close')}>
        <Icon name="close" size={20} />
      </button>

      {!isVideo && !interacted && (
        <span className="player-hint-pill" style={{ top: 16, left: 16 }}>
          {t('Scroll to zoom · double-click to fit')}
        </span>
      )}

      {isVideo ? (
        <video className="lb-media" src={item.video} controls autoPlay
          onClick={(e) => e.stopPropagation()} />
      ) : (
        <img className="lb-media" src={item.src} alt={item.alt || ''} draggable={false}
          style={{
            transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
            cursor: zoomed ? 'grab' : 'zoom-in',
          }}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove}
          onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
          onDoubleClick={onDoubleClick} />
      )}

      {item.caption ? (
        <span className="player-hint-pill lb-caption" title={item.caption}>{item.caption}</span>
      ) : null}

      {!isVideo && (
        <div className="lb-zoombar" onClick={(e) => e.stopPropagation()}>
          <button className="lb-zoom-btn" onClick={() => zoomAt(window.innerWidth / 2, window.innerHeight / 2, 1 / 1.3)}
            title={t('Zoom out')} aria-label={t('Zoom out')}><Icon name="zoomOut" size={16} /></button>
          <button className="lb-zoom-btn lb-zoom-reset" onClick={reset}
            title={t('Reset zoom')} aria-label={t('Reset zoom')}>{Math.round(scale * 100)}%</button>
          <button className="lb-zoom-btn" onClick={() => zoomAt(window.innerWidth / 2, window.innerHeight / 2, 1.3)}
            title={t('Zoom in')} aria-label={t('Zoom in')}><Icon name="zoomIn" size={16} /></button>
        </div>
      )}
    </div>
  )
}
