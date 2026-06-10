/**
 * GalleryTab — Bilder-Galerie eines Characters im Game-Admin.
 * Bewusst minimal: Thumbnail-Grid · Bild löschen (mit Inline-Bestätigung) ·
 * vergrößert in der Lightbox ansehen. Keine weiteren Features.
 *
 * Quelle: GET /characters/{name}/images · Löschen: DELETE …/images/{file}.
 * Lightbox ist der geteilte Singleton aus dem Player-UI (eigener Host hier via
 * LightboxProvider, damit er auch im Game-Admin gemountet ist).
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiDelete } from '../../lib/api'
import { LightboxProvider, openLightbox } from '../../player/Lightbox'

interface ImagesResp {
  character: string
  images: string[]
  profile_image: string | null
  urls: string[]
  image_videos: Record<string, string>
}

export function GalleryTab({ character }: { character: string }) {
  const { t } = useI18n()
  const [data, setData] = useState<ImagesResp | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!character) { setData(null); return }
    try { setData(await apiGet<ImagesResp>(`/characters/${encodeURIComponent(character)}/images`)) }
    catch { setData(null) }
  }, [character])
  useEffect(() => { load(); setConfirmDel(null) }, [load])

  const imgUrl = (f: string) => `/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(f)}`
  const videoOf = (f: string): string => {
    const stem = f.replace(/\.[^.]+$/, '')
    const v = data?.image_videos?.[stem]
    return v ? `/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(v)}` : ''
  }
  const openOne = (f: string) => {
    const v = videoOf(f)
    openLightbox(v ? { video: v, alt: f } : { src: imgUrl(f), alt: f })
  }

  const del = async (f: string) => {
    if (busy) return
    setBusy(true)
    try {
      await apiDelete(`/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(f)}`)
      setData((d) => (d ? {
        ...d,
        images: d.images.filter((n) => n !== f),
        profile_image: d.profile_image === f ? null : d.profile_image,
      } : d))
      setConfirmDel(null)
    } catch { /* ignore */ } finally { setBusy(false) }
  }

  if (!character) return <div className="ga-form"><div className="ga-placeholder">{t('No character selected')}</div></div>

  const files = data?.images || []

  return (
    <LightboxProvider>
      <div className="ga-form" style={{ padding: 0 }}>
        {files.length === 0 ? (
          <div className="ga-placeholder">{t('No images yet')}</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10 }}>
            {files.map((f) => {
              const isProfile = f === data?.profile_image
              const hasVideo = !!videoOf(f)
              const confirming = confirmDel === f
              return (
                <div key={f} style={{
                  position: 'relative', aspectRatio: '3 / 4', borderRadius: 8, overflow: 'hidden',
                  background: 'var(--bg, #0d1117)',
                  border: isProfile ? '2px solid var(--accent, #6aa9ff)' : '1px solid var(--border, #30363d)',
                }}>
                  <img src={imgUrl(f)} alt={f} loading="lazy" title={f} onClick={() => openOne(f)}
                    style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', cursor: 'zoom-in' }} />

                  {isProfile && (
                    <span title={t('Profile image')} style={{
                      position: 'absolute', top: 4, left: 4, fontSize: '0.85em',
                      background: 'rgba(0,0,0,0.5)', borderRadius: 4, padding: '0 4px', color: '#fff',
                    }}>★</span>
                  )}
                  {hasVideo && (
                    <span style={{
                      position: 'absolute', bottom: 4, right: 4, fontSize: '0.8em',
                      background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '0 4px', color: '#fff',
                    }}>▶</span>
                  )}

                  {confirming ? (
                    <div style={{
                      position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                      alignItems: 'center', justifyContent: 'center', gap: 8, padding: 8,
                      background: 'rgba(10,12,16,0.86)', textAlign: 'center',
                    }}>
                      <span style={{ fontSize: '0.82em' }}>{t('Delete this image?')}</span>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                          onClick={() => del(f)}
                          style={{ background: '#e0443e', borderColor: '#e0443e', color: '#fff' }}>
                          {busy ? t('Deleting…') : t('Delete')}
                        </button>
                        <button type="button" className="ga-btn ga-btn-sm" onClick={() => setConfirmDel(null)}>
                          {t('Cancel')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button type="button" title={t('Delete image')} aria-label={t('Delete image')}
                      onClick={() => setConfirmDel(f)}
                      style={{
                        position: 'absolute', top: 4, right: 4, width: 26, height: 26, borderRadius: 6,
                        border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)',
                        color: '#fff', cursor: 'pointer', lineHeight: 1, fontSize: '0.9em',
                      }}>🗑</button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </LightboxProvider>
  )
}
