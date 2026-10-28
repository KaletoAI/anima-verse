import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'
import { useToast } from './Toast'
import { PlayerPhotoDialog, type BackendOptions } from './PlayerPhotoDialog'
import type { ScenePhotoSubmit } from './ScenePanel'
import { useEnlarge } from './ZoomButton'

interface Reading {
  avatar: string
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

interface QueuedImage {
  task_id: string
  page_ref: string
  status: 'queued'
}

interface ImageStatus {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  detail?: string
  reading?: Reading
}

// Retain only job IDs while the book is closed; never poll outside its read session.
const admittedImageJobs = new Map<string, QueuedImage>()
const imageJobKey = (avatar: string, itemId: string, pageRef: string) =>
  JSON.stringify([avatar, itemId, pageRef])

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
  const [imageJob, setImageJob] = useState<QueuedImage | null>(null)
  const imageStatusPoll = useRef<number | null>(null)
  const pageRequestVersion = useRef(0)
  const pageRef = reading?.page?.image_ref
  const pageIndex = reading?.index
  const avatar = reading?.avatar
  const imagePending = imageJob !== null && imageJob.page_ref === pageRef
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
    if (imageStatusPoll.current !== null) window.clearTimeout(imageStatusPoll.current)
    imageStatusPoll.current = null
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
        setImageJob(result.page?.image_ref
          ? admittedImageJobs.get(imageJobKey(result.avatar, itemId, result.page.image_ref)) ?? null
          : null)
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
    if (busy || !imageJob || !pageRef || pageIndex === undefined || !avatar
      || imageJob.page_ref !== pageRef || closed.current) return
    const job = imageJob
    let active = true
    let errorReported = false
    const version = pageRequestVersion.current
    const key = imageJobKey(avatar, itemId, pageRef)
    const current = () => active && mounted.current && !closed.current
      && pageRequestVersion.current === version
    async function poll() {
      imageStatusPoll.current = null
      if (!current()) return
      try {
        const result = await apiPost<ImageStatus | SessionResult>('/play/read/image-status', {
          item_id: itemId, index: pageIndex, page_ref: pageRef, task_id: job.task_id,
        })
        if (!current()) return
        if (('caught_by' in result || 'error' in result) && notify(result)) {
          close()
          return
        }
        if (!('status' in result)) return
        errorReported = false
        if (result.status === 'completed' || result.status === 'failed' || result.status === 'cancelled') {
          admittedImageJobs.delete(key)
          setImageJob((currentJob) => currentJob?.task_id === job.task_id ? null : currentJob)
          if (result.status === 'completed') {
            const refreshed = result.reading
            if (refreshed && refreshed.avatar === avatar && refreshed.index === pageIndex
              && refreshed.page?.image_ref === pageRef) {
              setReading((page) => page && page.avatar === avatar && page.index === pageIndex
                && page.page?.image_ref === pageRef ? refreshed : page)
            }
          } else {
            toast(result.detail || translateRef.current(
              result.status === 'cancelled' ? 'Cancelled' : 'Generation failed.',
            ), 'error')
          }
          return
        }
      } catch (error) {
        if (!current()) return
        if (!errorReported) {
          toast(error instanceof Error ? error.message : String(error), 'error')
          errorReported = true
        }
      }
      if (current()) imageStatusPoll.current = window.setTimeout(() => { void poll() }, 2000)
    }
    imageStatusPoll.current = window.setTimeout(() => { void poll() }, 0)
    return () => {
      active = false
      if (imageStatusPoll.current !== null) window.clearTimeout(imageStatusPoll.current)
      imageStatusPoll.current = null
    }
  }, [avatar, busy, close, imageJob, itemId, notify, pageIndex, pageRef, toast])

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
    requestAnimationFrame(() => {
      if (regenerateButton.current && !regenerateButton.current.disabled) regenerateButton.current.focus()
      else dialog.current?.focus()
    })
  }

  async function prepareImage() {
    if (closed.current || pageLocked || imagePending || !reading?.page?.image_regenerable || !reading.page.image_ref) return
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
    const call = apiPost<QueuedImage | SessionResult>('/play/read/image-regenerate', {
      item_id: itemId,
      index: preparedImage.index,
      page_ref: preparedImage.page_ref,
      prompt: payload.prompt,
      backend: payload.backend || undefined,
      loras: payload.loras,
      negative_prompt: payload.negative_prompt,
    })
    // Await only admission; the render outlives this dialog and read session.
    try {
      const result = await call
      if ('task_id' in result && result.page_ref === preparedImage.page_ref) {
        admittedImageJobs.set(imageJobKey(preparedImage.avatar, itemId, result.page_ref), result)
      }
      if (!mounted.current || closed.current) return
      if (('caught_by' in result || 'error' in result) && notify(result)) {
        close()
        return
      }
      if ('task_id' in result && result.page_ref === preparedImage.page_ref) {
        setImageJob(result)
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
    pageRequestVersion.current += 1
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
            pageRequestVersion.current += 1
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
                {(reading.page.image || reading.page.image_regenerable) && <div style={{ position: 'relative', marginBottom: 16 }}>
                  {reading.page.image ? <img src={reading.page.image} alt={reading.page.heading}
                    {...enlarge({ src: reading.page.image, alt: reading.page.heading }, {
                      display: 'block', width: '100%', maxWidth: '100%', height: 'auto',
                    })} /> : <div aria-hidden="true" style={{ minHeight: 160, display: 'grid',
                      placeItems: 'center', border: '1px dashed var(--border, #30363d)',
                      borderRadius: 4, color: 'var(--text-muted, #8b949e)', fontSize: 32 }}>🖼</div>}
                  {reading.page.image_regenerable && <button ref={regenerateButton} type="button"
                    title={t('Regenerate image')} aria-label={t('Regenerate image')}
                    aria-busy={imagePreparing || imagePending} disabled={pageLocked || imagePending}
                    style={{ position: 'absolute', right: 8, bottom: 8, display: 'inline-flex',
                      alignItems: 'center', justifyContent: 'center', border: 'none', borderRadius: 4,
                      background: 'rgba(20,22,28,0.7)', color: '#fff', padding: 6, fontSize: '1em',
                      lineHeight: 1, cursor: pageLocked || imagePending ? 'default' : 'pointer' }}
                    onClick={(event) => { event.stopPropagation(); void prepareImage() }}>
                    {imagePreparing || imagePending ? '⏳' : '🔄'}
                  </button>}
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
