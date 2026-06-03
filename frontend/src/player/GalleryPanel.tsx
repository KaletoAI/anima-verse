/**
 * GalleryPanel — Bilder des Avatars (Tier 2, read-only).
 * Thumbnail-Grid; Klick öffnet eine Lightbox INNERHALB des Panels (unter dem
 * Header, mit Rand-Abstand) mit Bild + Bild-Informationen daneben.
 * Extern (post-)bearbeitete Bilder sind markiert. Quelle: GET /play/gallery.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

interface ImgInfo {
  prompt: string; model: string; backend: string; from_character: string
  created_at: string; postprocessed_at: string; analysis: string; comment: string
}
interface Img { name: string; url: string; is_profile: boolean; video: string; postprocessed: boolean; info: ImgInfo }
interface Gallery { avatar: string; images: Img[]; profile_image: string }

function fmt(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts.replace('T', ' ') : d.toLocaleString()
}

export function GalleryPanel() {
  const { t } = useI18n()
  const [data, setData] = useState<Gallery | null>(null)
  const [zoom, setZoom] = useState<Img | null>(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try { const d = await apiGet<Gallery>('/play/gallery'); if (alive) setData(d) } catch { /* auth handled */ }
    }
    tick()
    const id = setInterval(tick, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (!data || !data.avatar) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No active avatar')}</div>
  }
  if (!data.images.length) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No images yet')}</div>
  }

  return (
    <div style={{ position: 'relative', height: '100%', minHeight: 0 }}>
      <div style={{ height: '100%', overflow: 'auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(72px, 1fr))', gap: 6 }}>
          {data.images.map((img) => (
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

      {zoom && (
        <div onClick={() => setZoom(null)}
          style={{ position: 'absolute', inset: 0, zIndex: 5, background: 'rgba(0,0,0,0.78)',
            padding: 10, display: 'flex', gap: 10, borderRadius: 8 }}>
          {/* Bild */}
          <div style={{ flex: 1, minWidth: 0, display: 'grid', placeItems: 'center' }} onClick={(e) => e.stopPropagation()}>
            {zoom.video
              ? <video src={zoom.video} controls autoPlay style={{ maxWidth: '100%', maxHeight: '100%' }} />
              : <img src={zoom.url} alt={zoom.name} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', borderRadius: 6 }} />}
          </div>
          {/* Bild-Informationen */}
          <div onClick={(e) => e.stopPropagation()} style={{
            flex: '0 0 345px', maxWidth: '55%', overflow: 'auto', fontSize: '0.8em',
            background: 'rgba(20,22,28,0.92)', border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 8, padding: 10, display: 'flex', flexDirection: 'column', gap: 6,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <strong style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t('Image info')}</strong>
              <button onClick={() => setZoom(null)} title={t('Close')}
                style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: '1.2em', lineHeight: 1, opacity: 0.7 }}>×</button>
            </div>
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
        </div>
      )}
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
