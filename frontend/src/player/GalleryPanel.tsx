/**
 * GalleryPanel — Galerien im Player-UI (Tier 2, read-only).
 * Standardmäßig die eigene Avatar-Galerie; sind weitere Galerien für den Avatar
 * freigegeben (gallery_allowed_viewers), erscheint oben eine Auswahlleiste zum
 * Durchstöbern dieser fremden Galerien. Thumbnail-Grid (nach Zeit gruppiert);
 * Klick öffnet eine Lightbox INNERHALB des Panels mit Bild + Bild-Informationen.
 * Quellen: GET /play/galleries (Liste), GET /play/gallery[/{character}] (Bilder).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost, apiDelete } from '../lib/api'
import { useLightbox } from './Lightbox'
import { ImageGenDialog, type ImageGenSubmit } from '../components/ImageGenDialog'
import { Icon } from './icons'
import { EmptyState } from './EmptyState'

interface ImgInfo {
  prompt: string; model: string; backend: string; from_character: string
  created_at: string; postprocessed_at: string; analysis: string; comment: string
}
interface Img { name: string; url: string; is_profile: boolean; video: string; postprocessed: boolean; info: ImgInfo }
interface Gallery { avatar: string; character?: string; images: Img[]; profile_image: string }
interface GalleryRef { character: string; is_self: boolean; profile_url: string }

function fmt(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts.replace('T', ' ') : d.toLocaleString()
}

export function GalleryPanel() {
  const { t, lang } = useI18n()
  const lightbox = useLightbox()
  const [self, setSelf] = useState<string>('')
  const [galleries, setGalleries] = useState<GalleryRef[] | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [data, setData] = useState<Gallery | null>(null)
  const [zoom, setZoom] = useState<Img | null>(null)
  const [confirmDel, setConfirmDel] = useState(false)  // Inline-Bestätigung in der Detail-Box
  const [deleting, setDeleting] = useState(false)

  // Löschen aus der AKTUELL gewählten Galerie (vorerst für alle Bilder; eine
  // Berechtigungsprüfung wird später nachgezogen). Optimistisch aus der Liste
  // entfernen und die Detail-Box schließen. confirmDel zurücksetzen bei Bildwechsel.
  const deleteImage = async (img: Img) => {
    if (deleting || !selected) return
    setDeleting(true)
    try {
      await apiDelete(`/play/gallery/${encodeURIComponent(selected)}/image/${encodeURIComponent(img.name)}`)
      setData((d) => (d ? { ...d, images: d.images.filter((i) => i.name !== img.name) } : d))
      setZoom(null)
      setConfirmDel(false)
    } catch { /* ignore – Poll holt den echten Stand nach */ } finally { setDeleting(false) }
  }
  // Bestätigung verwerfen, sobald ein anderes Bild geöffnet/geschlossen wird.
  useEffect(() => { setConfirmDel(false) }, [zoom?.name])

  // Regenerate (nur für die EIGENE Galerie): detect characters, open the shared
  // ImageGenDialog, post to the character-image regenerate route. The 8s gallery
  // poll picks up the replaced/new image — no separate task polling needed.
  const [regenImg, setRegenImg] = useState<Img | null>(null)
  const [charOpts, setCharOpts] = useState<{ detected: string[]; available: string[] } | null>(null)

  const openRegen = useCallback(async (img: Img) => {
    if (!selected) return
    let opts = { detected: [] as string[], available: [] as string[] }
    try {
      const cd = await apiPost<{ detected?: string[]; available?: string[] }>(
        `/characters/${encodeURIComponent(selected)}/images/${encodeURIComponent(img.name)}/detect-characters`, {})
      opts = { detected: cd.detected || [], available: cd.available || [] }
    } catch { /* proceed without detection */ }
    setCharOpts(opts)
    setRegenImg(img)
  }, [selected])

  const submitRegen = useCallback(async (payload: ImageGenSubmit) => {
    const img = regenImg
    if (!img || !selected) return
    const body: Record<string, unknown> = {}
    if (payload.prompt) body.custom_prompt = payload.prompt
    if (payload.workflow) body.workflow = payload.workflow
    if (payload.backend) body.backend = payload.backend
    if (payload.model_override) body.model_override = payload.model_override
    if (payload.loras) body.loras = payload.loras
    if (payload.character_names) body.character_names = payload.character_names
    if (payload.improvement_request) body.improvement_request = payload.improvement_request
    if (payload.negative_prompt) body.negative_prompt = payload.negative_prompt
    if (payload.create_new) body.create_new = true
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

  // Load the set of galleries the avatar may browse (own + shared). Slow poll.
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await apiGet<{ avatar: string; galleries: GalleryRef[] }>('/play/galleries')
        if (!alive) return
        setSelf(d.avatar || '')
        setGalleries(d.galleries || [])
        setSelected((cur) => cur || d.avatar || '')
      } catch { /* auth handled */ }
    }
    tick()
    const id = setInterval(tick, 30000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // Load + poll the currently selected gallery's images.
  useEffect(() => {
    if (!selected) { setData(null); return }
    let alive = true
    const url = selected === self ? '/play/gallery' : `/play/gallery/${encodeURIComponent(selected)}`
    const tick = async () => {
      try { const d = await apiGet<Gallery>(url); if (alive) setData(d) } catch { if (alive) setData(null) }
    }
    tick()
    const id = setInterval(tick, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [selected, self])

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
        <div onClick={() => setZoom(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 4000, background: 'rgba(0,0,0,0.82)',
            padding: 24, display: 'flex', gap: 12 }}>
          {/* Bild */}
          <div style={{ position: 'relative', flex: 1, minWidth: 0, display: 'grid', placeItems: 'center' }} onClick={(e) => e.stopPropagation()}>
            <button onClick={() => lightbox.open(zoom.video ? { video: zoom.video, alt: zoom.name } : { src: zoom.url, alt: zoom.name })}
              title={t('Open fullscreen')} aria-label={t('Open fullscreen')}
              style={{ position: 'absolute', top: 6, right: 6, zIndex: 1, display: 'inline-flex',
                alignItems: 'center', justifyContent: 'center', width: 32, height: 32, borderRadius: 8,
                border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)', color: '#fff', cursor: 'pointer' }}>
              <Icon name="maximize" size={16} />
            </button>
            {zoom.video
              ? <video src={zoom.video} controls autoPlay style={{ maxWidth: '100%', maxHeight: '100%' }} />
              : <img src={zoom.url} alt={zoom.name} onClick={() => lightbox.open({ src: zoom.url, alt: zoom.name })}
                  style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', borderRadius: 6, cursor: 'zoom-in' }} />}
          </div>
          {/* Bild-Informationen */}
          <div onClick={(e) => e.stopPropagation()} style={{
            flex: '0 0 345px', maxWidth: '55%', overflow: 'auto', fontSize: '0.8em',
            background: 'rgba(20,22,28,0.92)', border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 8, padding: 10, display: 'flex', flexDirection: 'column', gap: 6,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <strong style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('Image info')}</strong>
              {selected === self && !zoom.video ? (
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
              <button onClick={() => setConfirmDel(true)} title={t('Delete image')} aria-label={t('Delete image')}
                style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer',
                  opacity: 0.7, display: 'inline-flex', alignItems: 'center' }}>
                <Icon name="trash" size={16} />
              </button>
              <button onClick={() => setZoom(null)} title={t('Close')}
                style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: '1.2em', lineHeight: 1, opacity: 0.7 }}>×</button>
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

      {regenImg ? (
        <ImageGenDialog
          open
          title={t('Regenerate image')}
          defaultPrompt={regenImg.info?.prompt || ''}
          mode="regenerate"
          characterOptions={charOpts || { detected: [], available: [] }}
          onSubmit={submitRegen}
          onClose={() => { setRegenImg(null); setCharOpts(null) }}
        />
      ) : null}
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
