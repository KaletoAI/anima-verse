import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'
import { useToast } from './Toast'

interface Reading {
  item_name: string
  index: number
  total: number
  page: { heading: string; text: string } | null
}

type SessionResult = { caught_by?: string; error?: string }

/** Shared by the 2D inventory and 3D HUD; escape transformed panel bounds. */
export function ReadingModal({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [request, setRequest] = useState({ index: 0, opening: true })
  const [reading, setReading] = useState<Reading | null>(null)
  const [busy, setBusy] = useState(true)
  const dialog = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const mounted = useRef(false)
  const closed = useRef(false)
  const pending = useRef(new Set<Promise<unknown>>())
  const translateRef = useRef(t)
  translateRef.current = t

  const notify = useCallback((result: SessionResult) => {
    if (result.caught_by) {
      toast(translateRef.current('{name} caught you reading.').replace('{name}', result.caught_by))
      return true
    }
    if (result.error) {
      toast(result.error, 'error')
      return true
    }
    return false
  }, [toast])

  const endSession = useCallback(() => {
    if (closed.current) return
    closed.current = true
    // Wait for pending reads so an opening cannot recreate a closed session.
    void Promise.allSettled([...pending.current])
      .then(() => apiPost<SessionResult>('/play/read/close', { item_id: itemId }))
      .then(notify)
      .catch((error: Error) => toast(error.message, 'error'))
  }, [itemId, notify, toast])

  const close = useCallback(() => {
    if (closed.current) return
    endSession()
    closeRef.current()
  }, [endSession])

  useEffect(() => {
    mounted.current = true
    const heartbeat = window.setInterval(() => {
      if (closed.current) return
      const call = apiPost<SessionResult>('/play/read/heartbeat', { item_id: itemId })
      pending.current.add(call)
      void call.then((result) => {
        if (mounted.current && !closed.current && notify(result)) close()
      }).catch((error: Error) => {
        if (!mounted.current || closed.current) return
        toast(error.message, 'error')
        close()
      }).finally(() => pending.current.delete(call))
    }, 5000)
    return () => {
      mounted.current = false
      window.clearInterval(heartbeat)
      // StrictMode replays setup immediately; only a real unmount ends the session.
      queueMicrotask(() => { if (!mounted.current) endSession() })
    }
  }, [itemId, close, endSession, notify, toast])

  useEffect(() => {
    let active = true
    if (closed.current) return
    const call = apiPost<Reading | SessionResult>('/play/read', { item_id: itemId, ...request })
    pending.current.add(call)
    void call
      .then((result) => {
        if (!mounted.current || closed.current) return
        if (('caught_by' in result || 'error' in result) && notify(result)) {
          close()
          return
        }
        if (!active || !('page' in result)) return
        setReading(result)
        setBusy(false)
      })
      .catch((error: Error) => {
        if (!mounted.current || closed.current) return
        toast(error.message, 'error')
        close()
      })
      .finally(() => pending.current.delete(call))
    return () => { active = false }
  }, [itemId, request, toast, close, notify])

  useEffect(() => {
    const previous = document.activeElement
    dialog.current?.focus()
    return () => { if (previous instanceof HTMLElement) previous.focus() }
  }, [])

  function flip(index: number) {
    if (closed.current || busy || !reading || index < 0 || index >= reading.total) return
    setBusy(true)
    setRequest({ index, opening: false })
  }

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (['Escape', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
        event.preventDefault()
        event.stopImmediatePropagation()
        if (event.key === 'Escape') close()
        else if (!closed.current && !busy && reading) {
          const index = reading.index + (event.key === 'ArrowLeft' ? -1 : 1)
          if (index >= 0 && index < reading.total) {
            setBusy(true)
            setRequest({ index, opening: false })
          }
        }
      }
      if (event.key === 'Tab') {
        const buttons = dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
        if (!buttons?.length) return
        const first = buttons[0]
        const last = buttons[buttons.length - 1]
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', keydown, true)
    return () => window.removeEventListener('keydown', keydown, true)
  }, [busy, reading, close])

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={close}>
      <style>{`
        @keyframes reading-page-turn {
          from { opacity: 0.4; transform: perspective(800px) rotateY(-5deg); }
          to { opacity: 1; transform: perspective(800px) rotateY(0); }
        }
        .reading-page { animation: reading-page-turn 160ms ease-out; transform-origin: left center; }
        @media (prefers-reduced-motion: reduce) { .reading-page { animation: none; } }
      `}</style>
      <div ref={dialog} className="ga-modal" role="dialog" aria-modal="true"
        aria-label={reading?.item_name || t('Read')} tabIndex={-1}
        style={{ maxWidth: 620 }} onMouseDown={(event) => event.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{reading?.item_name || t('Loading…')}</span>
          <button className="ga-modal-close" aria-label={t('Close')} onClick={close}>×</button>
        </div>
        <div className="ga-modal-body" aria-busy={busy}
          style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {reading ? <>
            <div key={reading.index} className="reading-page" style={{ minHeight: 160, lineHeight: 1.6 }}>
              {reading.total === 0 ? <p>{t('The pages are empty.')}</p> : reading.page && <>
                <h3 style={{ marginTop: 0 }}>{reading.page.heading}</h3>
                <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{reading.page.text}</div>
              </>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <button className="ga-btn" disabled={busy || reading.index <= 0 || reading.total === 0}
                onClick={() => flip(reading.index - 1)}>{t('‹ Previous')}</button>
              <span aria-live="polite">{reading.total ? reading.index + 1 : 0} / {reading.total}</span>
              <button className="ga-btn" disabled={busy || reading.index >= reading.total - 1}
                onClick={() => flip(reading.index + 1)}>{t('Next ›')}</button>
            </div>
          </> : <div>{t('Loading…')}</div>}
        </div>
      </div>
    </div>, document.body,
  )
}
