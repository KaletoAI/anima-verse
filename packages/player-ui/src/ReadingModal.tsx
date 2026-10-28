import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'
import { useToast } from './Toast'
import { PlayerPhotoDialog, type BackendOptions } from './PlayerPhotoDialog'
import type { ScenePhotoSubmit } from './ScenePanel'
import { useEnlarge } from './ZoomButton'

interface Reading {
  item_name: string
  index: number
  total: number
  page: {
    heading: string
    date_label?: string
    text: string
    image?: string
    image_regenerable?: boolean
    image_ref?: string
  } | null
}

type SessionResult = { caught_by?: string; error?: string }

interface PreparedImage {
  prompt: string
  subjects: string[]
  available: string[]
  avatar: string
  page_ref: string
  backend_options: BackendOptions
  index: number
}

/** Shared by the 2D inventory and 3D HUD; escape transformed panel bounds. */
export function ReadingModal({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const lightboxClose = useRef<(() => void) | null>(null)
  const enlarge = useEnlarge((dispose) => {
    lightboxClose.current?.()
    lightboxClose.current = dispose
  })
  const [request, setRequest] = useState({ index: 0, opening: true })
  const [reading, setReading] = useState<Reading | null>(null)
  const [busy, setBusy] = useState(true)
  const [imagePreparing, setImagePreparing] = useState(false)
  const [preparedImage, setPreparedImage] = useState<PreparedImage | null>(null)
  const [imageError, setImageError] = useState('')
  const regenerateButton = useRef<HTMLButtonElement>(null)
  const pageLocked = busy || imagePreparing || preparedImage !== null
  const dialog = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
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
    lightboxClose.current?.()
    lightboxClose.current = null
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
    if (content.current) content.current.scrollTop = 0
  }, [reading?.index])

  useEffect(() => {
    const previous = document.activeElement
    dialog.current?.focus()
    return () => { if (previous instanceof HTMLElement) previous.focus() }
  }, [])

  function closeImageDialog() {
    setPreparedImage(null)
    requestAnimationFrame(() => regenerateButton.current?.focus())
  }

  async function prepareImage() {
    if (closed.current || pageLocked || !reading?.page?.image_regenerable || !reading.page.image_ref) return
    const index = reading.index
    setImagePreparing(true)
    setImageError('')
    const call = apiPost<Omit<PreparedImage, 'index'> | SessionResult>(
      '/play/read/image-prepare', { item_id: itemId, index, page_ref: reading.page.image_ref },
    )
    pending.current.add(call)
    try {
      const result = await call
      if (!mounted.current || closed.current) return
      if (('caught_by' in result || 'error' in result) && notify(result)) {
        close()
        return
      }
      if ('page_ref' in result) setPreparedImage({ ...result, index })
    } catch (error) {
      if (mounted.current && !closed.current) {
        toast(error instanceof Error ? error.message : String(error), 'error')
      }
    } finally {
      pending.current.delete(call)
      if (mounted.current && !closed.current) setImagePreparing(false)
    }
  }

  async function regenerateImage(payload: ScenePhotoSubmit) {
    if (closed.current || !preparedImage) return
    setImageError('')
    const call = apiPost<Reading | SessionResult>('/play/read/image-regenerate', {
      item_id: itemId,
      index: preparedImage.index,
      page_ref: preparedImage.page_ref,
      prompt: payload.prompt,
      backend: payload.backend || undefined,
      loras: payload.loras,
      negative_prompt: payload.negative_prompt,
    })
    // Rendering cannot reopen a session; closing must not wait for the GPU.
    try {
      const result = await call
      if (!mounted.current || closed.current) return
      if (('caught_by' in result || 'error' in result) && notify(result)) {
        close()
        return
      }
      if ('page' in result) {
        setReading(result)
        closeImageDialog()
      }
    } catch (error) {
      if (mounted.current && !closed.current) {
        setImageError(error instanceof Error ? error.message : String(error))
      }
    }
  }

  function flip(index: number) {
    if (closed.current || pageLocked || !reading || index < 0 || index >= reading.total) return
    setBusy(true)
    setRequest({ index, opening: false })
  }

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      // The book's capture handler must not steal keys or focus from overlays.
      if (preparedImage || document.querySelector('.lb-overlay')?.contains(document.activeElement)) return
      if (['Escape', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
        event.preventDefault()
        event.stopImmediatePropagation()
        if (event.key === 'Escape') close()
        else if (!closed.current && !pageLocked && reading) {
          const index = reading.index + (event.key === 'ArrowLeft' ? -1 : 1)
          if (index >= 0 && index < reading.total) {
            setBusy(true)
            setRequest({ index, opening: false })
          }
        }
      }
      if (event.key === 'Tab') {
        const buttons = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [role="button"][tabindex="0"]')
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
  }, [pageLocked, preparedImage, reading, close])

  return createPortal(
    <>
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
        style={{ maxWidth: 620, maxHeight: 'calc(100dvh - 48px)', minWidth: 0, minHeight: 0, overflow: 'hidden' }}
        onMouseDown={(event) => event.stopPropagation()}>
        <div className="ga-modal-header" style={{ flexShrink: 0, minWidth: 0, gap: 8 }}>
          <span title={reading?.item_name}
            style={{ minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {reading?.item_name || t('Loading…')}
          </span>
          <button className="ga-modal-close" style={{ flexShrink: 0 }} aria-label={t('Close')} onClick={close}>×</button>
        </div>
        <div className="ga-modal-body" aria-busy={busy}
          style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto', minHeight: 0, minWidth: 0, overflow: 'hidden', gap: 16 }}>
          {reading ? <>
            {reading.page && reading.total > 0 && <div style={{ flexShrink: 0, minWidth: 0 }}>
              <h3 title={reading.page.heading}
                style={{ margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {reading.page.heading}
              </h3>
              {reading.page.date_label && <div style={{ marginTop: 4, color: 'var(--text-muted, #8b949e)', overflowWrap: 'anywhere' }}>
                {reading.page.date_label}
              </div>}
            </div>}
            <div ref={content} key={reading.index} className="reading-page"
              style={{ flex: '1 1 auto', minHeight: 0, minWidth: 0, overflowY: 'auto', overflowX: 'hidden', lineHeight: 1.6 }}>
              {reading.total === 0 ? <p>{t('The pages are empty.')}</p> : reading.page && <>
                {reading.page.image && <img src={reading.page.image} alt={reading.page.heading}
                  {...enlarge({ src: reading.page.image, alt: reading.page.heading }, {
                    display: 'block', width: '100%', maxWidth: '100%', height: 'auto', marginBottom: 16,
                  })} />}
                {reading.page.image_regenerable && <div style={{ marginBottom: 16 }}>
                  <button ref={regenerateButton} className="ga-btn" disabled={pageLocked}
                    onClick={() => { void prepareImage() }}>
                    {imagePreparing ? t('Loading…') : t('Regenerate image')}
                  </button>
                </div>}
                <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{reading.page.text}</div>
              </>}
            </div>
            <div style={{ display: 'flex', flexShrink: 0, alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <button className="ga-btn" disabled={pageLocked || reading.index <= 0 || reading.total === 0}
                onClick={() => flip(reading.index - 1)}>{t('‹ Previous')}</button>
              <span aria-live="polite" style={{ flexShrink: 0 }}>{reading.total ? reading.index + 1 : 0} / {reading.total}</span>
              <button className="ga-btn" disabled={pageLocked || reading.index >= reading.total - 1}
                onClick={() => flip(reading.index + 1)}>{t('Next ›')}</button>
            </div>
          </> : <div>{t('Loading…')}</div>}
        </div>
      </div>
    </div>
    {preparedImage && <PlayerPhotoDialog {...preparedImage}
      title="Regenerate image" occasion="scene_view" hideSceneControls error={imageError}
      backendOptions={preparedImage.backend_options}
      onSubmit={regenerateImage} onClose={closeImageDialog} />}
    </>, document.body,
  )
}
