/**
 * GalleryTab — a character's image gallery in the Game-Admin.
 * Thumbnail grid · select profile image · delete with inline confirmation ·
 * regenerate (ImageGenDialog, incl. the LLM "Improve prompt") · view enlarged
 * in the lightbox.
 *
 * Source: GET /characters/{name}/images · delete: DELETE …/images/{file}
 * · select portrait: POST …/profile-image/{file} · regenerate:
 * POST …/images/{file}/detect-characters, then …/images/{file}/regenerate
 * (the same routes as the player gallery; the render runs in the background,
 * so the tab polls until the image changed).
 * The lightbox is the shared singleton; its ONE host is mounted in main.tsx.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiDelete, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { openLightbox } from '../../components/Lightbox'
import { GalleryAccess } from './GalleryAccess'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'
import { thumbUrl, thumbWidth } from '@anima/player-ui'

/** Grid tile: `minmax(120px, 1fr)`. The lightbox keeps the ORIGINAL. */
const TILE_W = thumbWidth(120)

interface ImagesResp {
  character: string
  images: string[]
  profile_image: string | null
  urls: string[]
  image_videos: Record<string, string>
  image_prompts?: Record<string, string>
  image_metadata?: Record<string, { created_at?: string }>
}

/** The open regenerate dialog: which file + who the server saw in it. */
interface RegenTarget { file: string; detected: string[]; available: string[] }

/** How long the tab waits for a background regenerate to land. */
const REGEN_POLL_MS = 4000
const REGEN_POLL_MAX = 45  // × 4 s = 3 min

export function GalleryTab({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [data, setData] = useState<ImagesResp | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [regen, setRegen] = useState<RegenTarget | null>(null)
  // A replaced image keeps its file name — `rev` busts the browser cache of
  // the tiles and the lightbox once a regenerate landed.
  const [rev, setRev] = useState(0)
  const pollTimer = useRef<number | null>(null)

  const fetchImages = useCallback(
    () => apiGet<ImagesResp>(`/characters/${encodeURIComponent(character)}/images`), [character])
  const load = useCallback(async () => {
    if (!character) { setData(null); return }
    try { setData(await fetchImages()) }
    catch { setData(null) }
  }, [character, fetchImages])
  const stopPoll = () => {
    if (pollTimer.current !== null) window.clearTimeout(pollTimer.current)
    pollTimer.current = null
  }
  useEffect(() => { load(); setConfirmDel(null); setRegen(null); stopPoll() }, [load])
  useEffect(() => stopPoll, [])

  const imgUrl = (f: string) => `/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(f)}`
  const withRev = (url: string) => (rev ? `${url}${url.includes('?') ? '&' : '?'}r=${rev}` : url)
  const videoOf = (f: string): string => {
    const stem = f.replace(/\.[^.]+$/, '')
    const v = data?.image_videos?.[stem]
    return v ? `/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(v)}` : ''
  }
  const openOne = (f: string) => {
    const v = videoOf(f)
    openLightbox(v ? { video: v, alt: f } : { src: withRev(imgUrl(f)), alt: f })
  }

  const openRegen = async (f: string) => {
    if (busy) return
    let detected: string[] = []
    let available: string[] = []
    try {
      const cd = await apiPost<{ detected?: string[]; available?: { name: string }[] }>(
        `${imgUrl(f)}/detect-characters`, {})
      detected = cd.detected || []
      available = (cd.available || []).map((c) => c.name)
    } catch { /* proceed without detection */ }
    setRegen({ file: f, detected, available })
  }

  // Poll until the file list or the regenerated file's stamp changed.
  const waitForRegen = (f: string, before: ImagesResp | null) => {
    stopPoll()
    const stamp = (d: ImagesResp | null) =>
      `${d?.images.length ?? 0}|${d?.image_metadata?.[f]?.created_at ?? ''}`
    const was = stamp(before)
    let round = 0
    const tick = async () => {
      pollTimer.current = null
      round += 1
      try {
        const d = await fetchImages()
        if (stamp(d) !== was) { setData(d); setRev((r) => r + 1); return }
      } catch { /* try again */ }
      if (round < REGEN_POLL_MAX) pollTimer.current = window.setTimeout(() => { void tick() }, REGEN_POLL_MS)
    }
    pollTimer.current = window.setTimeout(() => { void tick() }, REGEN_POLL_MS)
  }

  const submitRegen = async (payload: ImageGenSubmit) => {
    const target = regen
    if (!target) return
    const body: Record<string, unknown> = { custom_prompt: payload.prompt }
    if (payload.backend) body.backend = payload.backend
    if (payload.loras) body.loras = payload.loras
    if (payload.character_names) body.character_names = payload.character_names
    if (payload.improvement_request) body.improvement_request = payload.improvement_request
    if (payload.negative_prompt) body.negative_prompt = payload.negative_prompt
    if (payload.create_new) body.create_new = true
    if (payload.use_room === false) body.use_room = false
    if (payload.use_source_as_reference) body.use_source_as_reference = true
    if (typeof payload.pose_check === 'boolean') body.pose_check = payload.pose_check
    try {
      await apiPost(`${imgUrl(target.file)}/regenerate`, body)
      toast(t('Regeneration started'))
      waitForRegen(target.file, data)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }

  const setProfile = async (f: string) => {
    if (busy) return
    setBusy(true)
    try {
      const result = await apiPost<{ profile_image: string }>(
        `/characters/${encodeURIComponent(character)}/profile-image/${encodeURIComponent(f)}`, {},
      )
      setData((d) => d?.character === character ? { ...d, profile_image: result.profile_image } : d)
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
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
    <>
      <div style={{ marginBottom: 12 }}>
        <GalleryAccess character={character} />
      </div>
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
                  <img src={withRev(thumbUrl(imgUrl(f), TILE_W))} alt={f} loading="lazy" decoding="async" title={f} onClick={() => openOne(f)}
                    style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', cursor: 'zoom-in' }} />

                  {isProfile && (
                    <span title={t('Profile image')} style={{
                      position: 'absolute', top: 4, left: 4, fontSize: '0.85em',
                      background: 'rgba(0,0,0,0.5)', borderRadius: 4, padding: '0 4px', color: '#fff',
                    }}>★</span>
                  )}
                  {!isProfile && !confirming && (
                    <button type="button" title={t('Set as profile image')} aria-label={t('Set as profile image')}
                      disabled={busy} onClick={() => setProfile(f)}
                      style={{
                        position: 'absolute', top: 4, left: 4, width: 26, height: 26, borderRadius: 6,
                        border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)',
                        color: '#fff', cursor: 'pointer', lineHeight: 1, fontSize: '0.9em',
                      }}>☆</button>
                  )}
                  {/* Regenerate needs the stored prompt; an animated image
                      stays as it is (same rule as the player gallery). */}
                  {!hasVideo && !confirming && data?.image_prompts?.[f] && (
                    <button type="button" title={t('Regenerate image')} aria-label={t('Regenerate image')}
                      disabled={busy} onClick={() => { void openRegen(f) }}
                      style={{
                        position: 'absolute', bottom: 4, left: 4, width: 26, height: 26, borderRadius: 6,
                        border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)',
                        color: '#fff', cursor: 'pointer', lineHeight: 1, fontSize: '0.9em',
                      }}>↻</button>
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
                      disabled={busy}
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
      {regen && (
        <ImageGenDialog
          open
          title={`${t('Regenerate image')} — ${character}`}
          mode="regenerate"
          defaultPrompt={data?.image_prompts?.[regen.file] || ''}
          sourceImageUrl={withRev(imgUrl(regen.file))}
          showRoomReference
          characterOptions={{ detected: regen.detected, available: regen.available }}
          occasion="regenerate"
          occasionCharacter={character}
          onSubmit={submitRegen}
          onClose={() => setRegen(null)}
        />
      )}
    </>
  )
}
