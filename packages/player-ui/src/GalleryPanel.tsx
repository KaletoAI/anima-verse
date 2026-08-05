/**
 * GalleryPanel — galleries in the player UI (tier 2, read-only).
 * By default the avatar's own gallery; if further galleries are released for
 * the avatar (gallery_allowed_viewers), a picker bar appears on top for
 * browsing those foreign galleries. Thumbnail grid (grouped by time); a click
 * opens a lightbox INSIDE the panel with the image plus its image info.
 * Sources: GET /play/galleries (list), GET /play/gallery[/{character}] (images).
 *
 * Moved into @anima/player-ui in stage 6 so the 3D client's HUD mounts the
 * same panel. Everything it needs came along, except the large
 * image-generation dialog of the regenerate flow, which belongs to the
 * game-admin UI — the host slots it in via the `regenDialog` prop.
 *
 * The panel keeps its OWN detail overlay (not the package Lightbox): it is not
 * just a big image but image plus info column, delete/regenerate actions and
 * paging through the grid order.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from './I18nProvider'
import { apiGet, apiPost, apiDelete } from './api'
import { usePoll } from './usePolling'
import { Icon } from './icons'
import { EmptyState } from './EmptyState'

interface ImgInfo {
  prompt: string; model: string; backend: string; from_character: string
  created_at: string; postprocessed_at: string; analysis: string; comment: string
}
interface Img { name: string; url: string; is_profile: boolean; video: string; postprocessed: boolean; info: ImgInfo }
interface Gallery { avatar: string; character?: string; images: Img[]; profile_image: string }
interface GalleryRef { character: string; is_self: boolean; profile_url: string }

/** What the regenerate dialog sends back. The subset of the host dialog's
 *  payload this panel forwards to `/characters/{c}/images/{n}/regenerate` —
 *  every field is optional but the prompt, and only what is set is posted. */
export interface GalleryRegenSubmit {
  prompt: string
  backend?: string
  loras?: unknown[] | null
  create_new?: boolean
  improvement_request?: string
  negative_prompt?: string
  character_names?: string[]
  use_room?: boolean
  use_source_as_reference?: boolean
}

/** What the host needs to render its image-generation dialog for the
 *  regenerate flow: the image's own prompt and thumbnail, the character
 *  detection of that image, plus the two callbacks that continue/abort it. */
export interface GalleryRegenControl {
  /** The image's stored prompt — the dialog's editable starting point. */
  prompt: string
  /** URL of the image being regenerated (shown as the source thumbnail). */
  sourceImageUrl: string
  /** Characters the server recognised in the image — pre-selected. */
  detected: string[]
  /** Everyone selectable as a subject. */
  available: string[]
  /** Generate: posts the regenerate route and closes the dialog. */
  onSubmit: (payload: GalleryRegenSubmit) => void | Promise<void>
  /** Dismiss without generating. */
  onClose: () => void
}

export interface GalleryPanelProps {
  /**
   * Renders the image-generation dialog of the regenerate flow. The dialog
   * itself lives in the game-admin UI (four admin tabs share it), so it is not
   * part of this package — the host slots it in. Left unset, the regenerate
   * button is not rendered at all and the flow is unreachable: that is the 3D
   * HUD's documented v1 state, not a defect.
   */
  regenDialog?: (ctl: GalleryRegenControl) => ReactNode
}

function fmt(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts.replace('T', ' ') : d.toLocaleString()
}

export function GalleryPanel({ regenDialog }: GalleryPanelProps = {}) {
  const { t, lang } = useI18n()
  const [self, setSelf] = useState<string>('')
  const [galleries, setGalleries] = useState<GalleryRef[] | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [data, setData] = useState<Gallery | null>(null)
  const [zoom, setZoom] = useState<Img | null>(null)
  const [confirmDel, setConfirmDel] = useState(false)  // inline confirmation inside the detail box
  const [deleting, setDeleting] = useState(false)

  // Deleting is offered ONLY for the own gallery (server enforces the same
  // rule with 403). Optimistically remove from the list and close the detail
  // box. confirmDel resets on image change.
  const deleteImage = async (img: Img) => {
    if (deleting || !selected) return
    setDeleting(true)
    try {
      await apiDelete(`/play/gallery/${encodeURIComponent(selected)}/image/${encodeURIComponent(img.name)}`)
      setData((d) => (d ? { ...d, images: d.images.filter((i) => i.name !== img.name) } : d))
      setZoom(null)
      setConfirmDel(false)
    } catch { /* ignore – the poll fetches the real state */ } finally { setDeleting(false) }
  }
  // Drop the confirmation as soon as another image is opened/closed.
  useEffect(() => { setConfirmDel(false) }, [zoom?.name])

  // Regenerate (own gallery only): detect characters, hand the prepared state
  // to the host's dialog through the `regenDialog` slot, post to the
  // character-image regenerate route. The 8s gallery poll picks up the
  // replaced/new image — no separate task polling needed.
  const [regenImg, setRegenImg] = useState<Img | null>(null)
  const [charOpts, setCharOpts] = useState<{ detected: string[]; available: string[] } | null>(null)

  const openRegen = useCallback(async (img: Img) => {
    if (!selected) return
    setZoom(null)  // close the detail/zoom box, otherwise it covers the dialog
    let opts = { detected: [] as string[], available: [] as string[] }
    try {
      const cd = await apiPost<{ detected?: string[]; available?: string[] }>(
        `/characters/${encodeURIComponent(selected)}/images/${encodeURIComponent(img.name)}/detect-characters`, {})
      opts = { detected: cd.detected || [], available: cd.available || [] }
    } catch { /* proceed without detection */ }
    setCharOpts(opts)
    setRegenImg(img)
  }, [selected])

  const submitRegen = useCallback(async (payload: GalleryRegenSubmit) => {
    const img = regenImg
    if (!img || !selected) return
    const body: Record<string, unknown> = {}
    if (payload.prompt) body.custom_prompt = payload.prompt
    if (payload.backend) body.backend = payload.backend
    if (payload.loras) body.loras = payload.loras
    if (payload.character_names) body.character_names = payload.character_names
    if (payload.improvement_request) body.improvement_request = payload.improvement_request
    if (payload.negative_prompt) body.negative_prompt = payload.negative_prompt
    if (payload.create_new) body.create_new = true
    if (payload.use_room === false) body.use_room = false
    if (payload.use_source_as_reference) body.use_source_as_reference = true
    try {
      await apiPost(`/characters/${encodeURIComponent(selected)}/images/${encodeURIComponent(img.name)}/regenerate`, body)
    } catch { /* gallery poll picks up the result */ }
    setRegenImg(null); setCharOpts(null); setZoom(null)
  }, [regenImg, selected])

  // Delete only the animation (video) of an image — the image stays.
  const deleteAnimation = useCallback(async (img: Img) => {
    if (!selected || !img.video) return
    try {
      await apiDelete(`/characters/${encodeURIComponent(selected)}/images/${encodeURIComponent(img.name)}/animation`)
    } catch { /* gallery poll picks up the result */ }
    setZoom(null)
  }, [selected])

  // Group images by creation time: fixed buckets first (Today → This month),
  // then month-year buckets newest-first, "Older" last. Mirrors the old UI.
  const groups = useMemo<{ label: string; images: Img[] }[]>(() => {
    const now = Date.now()
    const map = new Map<number, { label: string; images: Img[] }>()
    for (const img of data?.images || []) {
      const created = img.info?.created_at || ''
      const d = created ? new Date(created) : null
      let sortKey: number
      let label: string
      if (!d || isNaN(d.getTime())) {
        sortKey = Number.MAX_SAFE_INTEGER
        label = t('Older')
      } else {
        const diffDays = Math.floor((now - d.getTime()) / 86400000)
        if (diffDays <= 0) { sortKey = 0; label = t('Today') }
        else if (diffDays === 1) { sortKey = 1; label = t('Yesterday') }
        else if (diffDays < 7) { sortKey = 2; label = t('This week') }
        else if (diffDays < 30) { sortKey = 3; label = t('This month') }
        else {
          const ym = d.getFullYear() * 12 + d.getMonth()
          sortKey = 1000 + (3000000 - ym) // newer month → smaller key, always > fixed buckets
          label = d.toLocaleDateString(lang || undefined, { month: 'long', year: 'numeric' })
        }
      }
      let g = map.get(sortKey)
      if (!g) { g = { label, images: [] }; map.set(sortKey, g) }
      g.images.push(img)
    }
    return [...map.entries()].sort((a, b) => a[0] - b[0]).map(([, g]) => g)
  }, [data, t, lang])

  // Paging order of the detail view = display order of the grid.
  const flat = useMemo(() => groups.flatMap((g) => g.images), [groups])
  const zoomIdx = zoom ? flat.findIndex((i) => i.name === zoom.name) : -1
  const step = useCallback((dir: number) => {
    setZoom((cur) => {
      if (!cur) return cur
      const idx = flat.findIndex((i) => i.name === cur.name)
      return flat[idx + dir] ?? cur
    })
  }, [flat])

  // Arrow keys page, Escape closes — as long as the detail view is open.
  useEffect(() => {
    if (!zoom) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') step(1)
      else if (e.key === 'ArrowLeft') step(-1)
      else if (e.key === 'Escape') setZoom(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [zoom, step])

  // Load the set of galleries the avatar may browse (own + shared). Slow poll.
  const { data: galleriesData } = usePoll<{ avatar: string; galleries: GalleryRef[] }>(
    'play-galleries', () => apiGet('/play/galleries'), { intervalMs: 30000 })
  useEffect(() => {
    if (!galleriesData) return
    setSelf(galleriesData.avatar || '')
    setGalleries(galleriesData.galleries || [])
    setSelected((cur) => cur || galleriesData.avatar || '')
  }, [galleriesData])

  // Load + poll the currently selected gallery's images.
  const galleryUrl = selected
    ? (selected === self ? '/play/gallery' : `/play/gallery/${encodeURIComponent(selected)}`)
    : ''
  const { data: galleryData, error: galleryError } = usePoll<Gallery>(
    `play-gallery:${selected}`, () => apiGet<Gallery>(galleryUrl),
    { intervalMs: 8000, enabled: !!selected })
  useEffect(() => {
    if (!selected) setData(null)
    else if (galleryError) setData(null)
    else if (galleryData) setData(galleryData)
  }, [selected, galleryData, galleryError])

  if (!self) {
    return <EmptyState icon="self" title={t('No active avatar')} />
  }

  const hasPicker = (galleries?.length || 0) > 1
  const picker = hasPicker ? (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
      {galleries!.map((g) => {
        const active = g.character === selected
        return (
          <button key={g.character} onClick={() => setSelected(g.character)}
            style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 10,
              fontSize: '0.78em', cursor: 'pointer',
              border: active ? '1px solid var(--accent,#6aa9ff)' : '1px solid rgba(255,255,255,0.15)',
              background: active ? 'rgba(106,169,255,0.18)' : 'rgba(255,255,255,0.05)',
              color: 'inherit' }}>
            {g.is_self ? '★ ' : ''}{g.is_self ? t('My gallery') : g.character}
          </button>
        )
      })}
    </div>
  ) : null

  if (!data) {
    return <div>{picker}<div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('Loading…')}</div></div>
  }
  if (!data.images.length) {
    return <div>{picker}<EmptyState icon="gallery" title={t('No images yet')} /></div>
  }

  return (
    <div style={{ position: 'relative', height: '100%', minHeight: 0 }}>
      <div style={{ height: '100%', overflow: 'auto' }}>
        {picker}
        {groups.map((g) => (
          <div key={g.label} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: '0.72em', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', opacity: 0.55, margin: '6px 2px 4px' }}>{g.label}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(72px, 1fr))', gap: 6 }}>
              {g.images.map((img) => (
                <button key={img.name} onClick={() => setZoom(img)} title={img.name}
                  style={{ position: 'relative', padding: 0, borderRadius: 6, overflow: 'hidden', cursor: 'pointer',
                    border: img.is_profile ? '2px solid var(--accent,#6aa9ff)' : '1px solid rgba(255,255,255,0.15)',
                    background: 'rgba(255,255,255,0.05)', aspectRatio: '3/4' }}>
                  <img src={img.url} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                  {img.postprocessed && (
                    <span title={t('Edited externally')} style={{ position: 'absolute', top: 2, right: 2, fontSize: '0.65em',
                      background: 'rgba(160,90,210,0.9)', color: '#fff', borderRadius: 3, padding: '0 3px' }}>✎</span>
                  )}
                  {img.video && (
                    <span style={{ position: 'absolute', bottom: 2, right: 2, fontSize: '0.7em', background: 'rgba(0,0,0,0.6)', borderRadius: 3, padding: '0 3px' }}>▶</span>
                  )}
                  {img.is_profile && <span style={{ position: 'absolute', top: 2, left: 2, fontSize: '0.7em' }}>★</span>}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {zoom && createPortal(
        /* The class carries no styles (the look is inline, as it always was) —
           it is the MARKER a host outside React can test for: the 3D client's
           Esc chain hands the key to an overlay that owns it instead of also
           leaving the embodied mode with it (main.ts, "overlays own escape"). */
        <div className="player-gallery-overlay" onClick={() => setZoom(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 4000, background: 'rgba(0,0,0,0.82)',
            padding: 24, display: 'flex', gap: 12 }}>
          {/* Image — overlay buttons: close at the top of the image, paging on
              the sides. The former magnifier (a second full-screen stage) is
              gone: the detail view IS already the large presentation. */}
          <div style={{ position: 'relative', flex: 1, minWidth: 0, display: 'grid', placeItems: 'center' }} onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setZoom(null)} title={t('Close')} aria-label={t('Close')}
              style={{ position: 'absolute', top: 6, right: 6, zIndex: 1, display: 'inline-flex',
                alignItems: 'center', justifyContent: 'center', width: 32, height: 32, borderRadius: 8,
                border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)', color: '#fff', cursor: 'pointer' }}>
              <Icon name="close" size={16} />
            </button>
            {zoomIdx > 0 && (
              <button onClick={() => step(-1)} title={t('Previous image')} aria-label={t('Previous image')}
                style={{ position: 'absolute', left: 6, top: '50%', transform: 'translateY(-50%)', zIndex: 1,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 48,
                  borderRadius: 8, border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)',
                  color: '#fff', cursor: 'pointer' }}>
                <Icon name="chevronLeft" size={20} />
              </button>
            )}
            {zoomIdx >= 0 && zoomIdx < flat.length - 1 && (
              <button onClick={() => step(1)} title={t('Next image')} aria-label={t('Next image')}
                style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', zIndex: 1,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 48,
                  borderRadius: 8, border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)',
                  color: '#fff', cursor: 'pointer' }}>
                <Icon name="chevronRight" size={20} />
              </button>
            )}
            {zoom.video
              ? <video src={zoom.video} controls autoPlay style={{ maxWidth: '100%', maxHeight: 'calc(100vh - 48px)' }} />
              : <img src={zoom.url} alt={zoom.name}
                  style={{ maxWidth: '100%', maxHeight: 'calc(100vh - 48px)', objectFit: 'contain', borderRadius: 6 }} />}
          </div>
          {/* Image info */}
          <div onClick={(e) => e.stopPropagation()} style={{
            flex: '0 0 345px', maxWidth: '55%', overflow: 'auto', fontSize: '0.8em',
            background: 'rgba(20,22,28,0.92)', border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 8, padding: 10, display: 'flex', flexDirection: 'column', gap: 6,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <strong style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('Image info')}</strong>
              {regenDialog && selected === self && !zoom.video ? (
                <button onClick={() => openRegen(zoom)} title={t('Regenerate image')} aria-label={t('Regenerate image')}
                  style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer',
                    opacity: 0.7, display: 'inline-flex', alignItems: 'center', fontSize: '1em' }}>🔄</button>
              ) : null}
              {selected === self && zoom.video ? (
                <button onClick={() => deleteAnimation(zoom)} title={t('Delete animation')} aria-label={t('Delete animation')}
                  style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer',
                    opacity: 0.7, display: 'inline-flex', alignItems: 'center', fontSize: '1em' }}>
                  <span style={{ position: 'relative', display: 'inline-block', lineHeight: 1 }}>
                    🎬
                    <span style={{ position: 'absolute', left: -2, right: -2, top: '46%', height: 2,
                      background: '#e05656', borderRadius: 2, transform: 'rotate(-20deg)', pointerEvents: 'none' }} />
                  </span>
                </button>
              ) : null}
              {selected === self ? (
                <button onClick={() => setConfirmDel(true)} title={t('Delete image')} aria-label={t('Delete image')}
                  style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer',
                    opacity: 0.7, display: 'inline-flex', alignItems: 'center' }}>
                  <Icon name="trash" size={16} />
                </button>
              ) : null}
            </div>
            {confirmDel && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6,
                background: 'rgba(224,86,86,0.14)', border: '1px solid rgba(224,86,86,0.4)' }}>
                <span style={{ flex: 1 }}>{t('Delete this image permanently?')}</span>
                <button onClick={() => deleteImage(zoom)} disabled={deleting}
                  style={{ border: '1px solid #e05656', background: '#e05656', color: '#fff',
                    borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>
                  {deleting ? t('Deleting…') : t('Delete')}
                </button>
                <button onClick={() => setConfirmDel(false)}
                  style={{ border: '1px solid var(--border,#30363d)', background: 'transparent', color: 'inherit',
                    borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>
                  {t('Cancel')}
                </button>
              </div>
            )}
            {zoom.postprocessed && (
              <div style={{ color: '#c79af0' }}>✎ {t('Edited externally')}{zoom.info.postprocessed_at ? ` (${fmt(zoom.info.postprocessed_at)})` : ''}</div>
            )}
            <InfoRow label={t('Created')} value={fmt(zoom.info.created_at)} />
            <InfoRow label={t('Created by')} value={zoom.info.from_character} />
            <InfoRow label={t('Model')} value={zoom.info.model} />
            <InfoRow label={t('Backend')} value={zoom.info.backend} />
            {zoom.info.comment && (
              <div><div style={{ opacity: 0.55 }}>{t('Comment')}</div><div style={{ fontStyle: 'italic' }}>{zoom.info.comment}</div></div>
            )}
            {zoom.info.prompt && (
              <div><div style={{ opacity: 0.55 }}>{t('Prompt')}</div><div style={{ opacity: 0.8, wordBreak: 'break-word' }}>{zoom.info.prompt}</div></div>
            )}
            {zoom.info.analysis && (
              <div><div style={{ opacity: 0.55 }}>{t('Analysis')}</div><div style={{ opacity: 0.8 }}>{zoom.info.analysis}</div></div>
            )}
          </div>
        </div>,
        document.body,
      )}

      {regenImg && regenDialog?.({
        prompt: regenImg.info?.prompt || '',
        sourceImageUrl: regenImg.url,
        detected: charOpts?.detected || [],
        available: charOpts?.available || [],
        onSubmit: submitRegen,
        onClose: () => { setRegenImg(null); setCharOpts(null) },
      })}
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      <span style={{ flex: '0 0 76px', opacity: 0.55 }}>{label}</span>
      <span style={{ flex: 1, wordBreak: 'break-word' }}>{value}</span>
    </div>
  )
}
