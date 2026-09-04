/**
 * InstagramPanel — the Instagram feed in the player UI (/play), ported from
 * the legacy UI. Phase 1: feed display (avatar, image/carousel/video, caption +
 * hashtags, likes/liked_by, comments with reactions/@mentions/creator reply)
 * plus the direct actions like, comment, delete and carousel navigation
 * (including removing a single image). Regenerate + animate (large shared
 * dialogs) were added as separate steps.
 * Source: /instagram/feed (+ /post/{id}/like|comment, DELETE /post/{id}).
 *
 * Moved into @anima/player-ui in stage 6 so the 3D client's HUD mounts the
 * same panel. Everything it needs came along, except the TWO large dialogs of
 * the regenerate and animate flows — both belong to the game-admin UI, so the
 * host slots them in via `imageGenDialog` and `animateDialog`. Zooming a post
 * uses the package Lightbox, so it needs no overlay of its own.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useI18n } from './I18nProvider'
import { apiGet, apiPost, apiDelete } from './api'
import { usePoll } from './usePolling'
import { useToast } from './Toast'
import { useLightbox } from './Lightbox'
import { useEnlarge } from './ZoomButton'
import { Icon } from './icons'

interface Reaction {
  emoji?: string
}
interface Comment {
  author: string
  text: string
  timestamp?: string
  reactions?: Reaction[]
}
interface ImageMeta {
  model?: string
  backend?: string
  backend_type?: string
  postprocessed?: boolean
  duration_s?: number
  image_analysis?: string
  prompt?: string
}
interface Post {
  id: string
  image_url?: string
  image_filename: string
  image_urls?: string[]
  image_filenames?: string[]
  video_url?: string
  caption?: string
  timestamp?: string
  agent_name?: string
  likes?: number
  liked_by?: string[]
  comments?: Comment[]
  image_meta?: ImageMeta
}

/** What the image-generation dialog sends back. The subset of the host
 *  dialog's payload this panel forwards to `/instagram/post/{id}/regenerate` —
 *  every field is optional but the prompt, and only what is set is posted. */
export interface InstagramImageGenSubmit {
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
 *  regenerate flow: the post's own prompt and image, the character detection
 *  of that image, plus the two callbacks that continue/abort it. */
export interface InstagramImageGenControl {
  /** The post's stored image prompt — the dialog's editable starting point. */
  prompt: string
  /** URL of the image being regenerated (shown as the source thumbnail). */
  sourceImageUrl: string
  /** Characters the server recognised in the image — pre-selected. */
  detected: string[]
  /** Everyone selectable as a subject. */
  available: string[]
  /** Generate: posts the regenerate route and closes the dialog. */
  onSubmit: (payload: InstagramImageGenSubmit) => void | Promise<void>
  /** Dismiss without generating. */
  onClose: () => void
}

/** What the animate dialog sends back — posted verbatim to
 *  `/instagram/post/{id}/animate`. */
export interface InstagramAnimateSubmit {
  prompt: string
  service: string
  /** Optional LoRAs for gateway video aliases. */
  loras?: Array<{ name: string; strength: number }>
  /** Optional video length in seconds (empty = backend default). */
  seconds?: number
}

/** What the host needs to render its animate dialog: the still it animates,
 *  the motion prompt to start from, whether the post ALREADY carries a video
 *  (the host titles the dialog "Re-animate" then), the prompt suggestion round
 *  trip and the two callbacks that continue/abort it. */
export interface InstagramAnimateControl {
  /** The image analysis of the post — the dialog's motion-prompt starting point. */
  prompt: string
  /** URL of the still being animated (shown as the source thumbnail). */
  sourceImageUrl: string
  /** The post already has an animation — this run replaces it. */
  hasVideo: boolean
  /** Ask the backend to suggest a motion prompt; returns the suggestion. */
  onSuggest: (opts: { system_prompt: string; llm_override: string }) => Promise<string>
  /** Animate: posts the animate route and closes the dialog. */
  onSubmit: (payload: InstagramAnimateSubmit) => void | Promise<void>
  /** Dismiss without animating. */
  onClose: () => void
}

export interface InstagramPanelProps {
  /**
   * Renders the image-generation dialog of the regenerate flow. The dialog
   * itself lives in the game-admin UI (four admin tabs share it), so it is not
   * part of this package — the host slots it in. Left unset, the regenerate
   * button is not rendered at all and the flow is unreachable: that is the 3D
   * HUD's documented v1 state, not a defect.
   */
  imageGenDialog?: (ctl: InstagramImageGenControl) => ReactNode
  /**
   * Renders the animate dialog (image → video). Game-admin UI as well, same
   * rule: without the slot the animate button is not rendered. Deleting an
   * existing animation stays available either way — that is a plain DELETE,
   * not a generation dialog.
   */
  animateDialog?: (ctl: InstagramAnimateControl) => ReactNode
}

function fmt(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts.replace('T', ' ') : d.toLocaleString()
}

// Caption with #hashtag / @mention highlighting (escaped via React text nodes).
function renderRich(text: string) {
  return text.split(/(#\w+|@\w+)/g).map((part, i) => {
    if (part.startsWith('#')) return <span key={i} className="ig-hashtag">{part}</span>
    if (part.startsWith('@')) return <span key={i} className="ig-mention">{part}</span>
    return <span key={i}>{part}</span>
  })
}

function metaTitle(m?: ImageMeta): string {
  if (!m) return ''
  const parts: string[] = []
  if (m.model) parts.push(`Model: ${m.model}`)
  if (m.backend) parts.push(`Skill: ${m.backend}`)
  if (m.backend_type) parts.push(`Type: ${m.backend_type}`)
  if (m.postprocessed) parts.push('Post-processing: external')
  if (m.duration_s) parts.push(`Duration: ${m.duration_s}s`)
  if (m.image_analysis) parts.push(`Analysis: ${m.image_analysis}`)
  return parts.join('\n')
}

export function InstagramPanel({ imageGenDialog, animateDialog }: InstagramPanelProps = {}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [carousel, setCarousel] = useState<Record<string, number>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [avatarFail, setAvatarFail] = useState<Record<string, boolean>>({})
  const [liked, setLiked] = useState<Record<string, boolean>>({})
  const lightbox = useLightbox()
  const enlarge = useEnlarge()
  // Open an image/video from the feed in the shared lightbox (video detected
  // by file extension → the lightbox shows video controls instead of zoom).
  const openMedia = useCallback((url: string) => {
    lightbox.open(/\.(mp4|webm)$/i.test(url) ? { video: url } : { src: url })
  }, [lightbox])
  // Regenerate: the post whose image-gen dialog is open, the detected/available
  // characters for it, and the set of posts currently regenerating.
  const [regenPost, setRegenPost] = useState<Post | null>(null)
  const [charOpts, setCharOpts] = useState<{ detected: string[]; available: string[] } | null>(null)
  const [regenerating, setRegenerating] = useState<Record<string, boolean>>({})
  // Animate: the post whose animate dialog is open, and posts currently animating.
  const [animatePost, setAnimatePost] = useState<Post | null>(null)
  const [animating, setAnimating] = useState<Record<string, boolean>>({})

  // Steady feed poll via the shared hub (visibility pause + error backoff).
  // The fetcher RETURNS the payload (instead of setting state itself) so the
  // hub can replay the last result into a freshly remounted panel — the grid
  // remounts all panels whenever the open-panel set changes.
  const { data: feed, refresh: reload } = usePoll<{ posts?: Post[] }>(
    'instagram-feed',
    () => apiGet<{ posts?: Post[] }>('/instagram/feed?limit=50'),
    { intervalMs: 12000 },
  )
  // Local copy so actions (e.g. like) can update optimistically between polls.
  useEffect(() => {
    if (feed) setPosts(feed.posts || [])
  }, [feed])

  const like = useCallback(
    async (p: Post) => {
      try {
        const r = await apiPost<{ likes?: number }>(`/instagram/post/${encodeURIComponent(p.id)}/like`, {})
        setPosts((prev) =>
          (prev || []).map((x) => (x.id === p.id ? { ...x, likes: r.likes ?? x.likes } : x)),
        )
        setLiked((m) => ({ ...m, [p.id]: true }))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [t, toast],
  )

  const comment = useCallback(
    async (p: Post) => {
      const text = (drafts[p.id] || '').trim()
      if (!text) return
      try {
        await apiPost(`/instagram/post/${encodeURIComponent(p.id)}/comment`, { text })
        setDrafts((d) => ({ ...d, [p.id]: '' }))
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [drafts, reload, t, toast],
  )

  const remove = useCallback(
    async (p: Post) => {
      if (!window.confirm(t('Delete this post?'))) return
      try {
        await apiDelete(`/instagram/post/${encodeURIComponent(p.id)}`)
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  const removeCarouselImage = useCallback(
    async (p: Post, filename: string) => {
      if (!filename || !window.confirm(t('Remove this image from the post?'))) return
      try {
        await apiDelete(
          `/instagram/post/${encodeURIComponent(p.id)}/image/${encodeURIComponent(filename)}`,
        )
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  const deleteAnimation = useCallback(
    async (p: Post) => {
      if (!window.confirm(t('Delete this animation? The image stays.'))) return
      try {
        await apiDelete(`/instagram/post/${encodeURIComponent(p.id)}/animation`)
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  // Poll the queue for the regenerate task; reload the feed each tick so the
  // new/replaced image lands, and stop once the task was seen and is gone.
  const pollTrack = useCallback(
    (postId: string, trackId: string, clear: (id: string) => void, maxTicks = 40) => {
      let n = 0
      let seen = false
      const iv = window.setInterval(async () => {
        n++
        let active = false
        try {
          const q = await apiGet<{ active_tasks?: { task_id?: string }[] }>('/queue/status')
          active = (q.active_tasks || []).some((tk) => tk.task_id === trackId)
        } catch { /* keep polling */ }
        if (active) seen = true
        await reload()
        if ((trackId && seen && !active) || n >= maxTicks) {
          window.clearInterval(iv)
          clear(postId)
        }
      }, 3000)
    },
    [reload],
  )
  const clearRegen = useCallback((id: string) => setRegenerating((p) => { const x = { ...p }; delete x[id]; return x }), [])
  const clearAnimate = useCallback((id: string) => setAnimating((p) => { const x = { ...p }; delete x[id]; return x }), [])

  // Open the regenerate dialog: detect characters first, prefill from the post.
  const openRegen = useCallback(async (p: Post) => {
    let opts = { detected: [] as string[], available: [] as string[] }
    try {
      const cd = await apiPost<{ detected?: string[]; available?: string[] }>(
        `/instagram/post/${encodeURIComponent(p.id)}/detect-characters`, {},
      )
      opts = { detected: cd.detected || [], available: cd.available || [] }
    } catch { /* proceed without character detection */ }
    setCharOpts(opts)
    setRegenPost(p)
  }, [])

  const submitRegen = useCallback(
    async (payload: InstagramImageGenSubmit) => {
      const p = regenPost
      if (!p) return
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
        const r = await apiPost<{ track_id?: string }>(
          `/instagram/post/${encodeURIComponent(p.id)}/regenerate`, body,
        )
        toast(t('Regenerating…'))
        setRegenerating((prev) => ({ ...prev, [p.id]: true }))
        pollTrack(p.id, r.track_id || '', clearRegen)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [regenPost, pollTrack, clearRegen, t, toast],
  )

  // Animate: suggest the motion prompt for the open post, then fire the video job.
  const suggestAnimate = useCallback(
    async (opts: { system_prompt: string; llm_override: string }): Promise<string> => {
      const p = animatePost
      if (!p) return ''
      try {
        const r = await apiPost<{ prompt?: string }>(
          `/instagram/post/${encodeURIComponent(p.id)}/suggest-animate-prompt`, opts,
        )
        return r.prompt || ''
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        return ''
      }
    },
    [animatePost, t, toast],
  )

  const submitAnimate = useCallback(
    async (payload: InstagramAnimateSubmit) => {
      const p = animatePost
      if (!p) return
      try {
        const r = await apiPost<{ track_id?: string }>(
          `/instagram/post/${encodeURIComponent(p.id)}/animate`, payload,
        )
        toast(t('Animating…'))
        setAnimating((prev) => ({ ...prev, [p.id]: true }))
        // Video generation takes longer than image regen — allow ~10 min.
        pollTrack(p.id, r.track_id || '', clearAnimate, 200)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [animatePost, pollTrack, clearAnimate, t, toast],
  )

  if (posts === null) return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('Loading…')}</div>
  if (posts.length === 0)
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No posts yet.')}</div>

  return (
    <div className="ig-feed">
      {posts.map((p) => {
        const agent = p.agent_name || 'Unknown'
        const urls = p.image_urls && p.image_urls.length ? p.image_urls : [p.image_url || `/instagram/images/${p.image_filename}`]
        const filenames = p.image_filenames && p.image_filenames.length ? p.image_filenames : [p.image_filename]
        const hasCarousel = urls.length > 1
        const idx = carousel[p.id] || 0
        const comments = p.comments || []
        const showAll = expanded[p.id]
        const visibleComments = showAll ? comments : comments.slice(Math.max(0, comments.length - 2))
        return (
          <div className="ig-post" key={p.id}>
            <div className="ig-post-head">
              {avatarFail[agent] ? (
                <div className="ig-avatar ig-avatar-ph">{agent.charAt(0).toUpperCase()}</div>
              ) : (
                <img
                  className="ig-avatar"
                  src={`/characters/${encodeURIComponent(agent)}/images/profile`}
                  alt={agent}
                  {...enlarge({ src: `/characters/${encodeURIComponent(agent)}/images/profile`, alt: agent })}
                  onError={() => setAvatarFail((m) => ({ ...m, [agent]: true }))}
                />
              )}
              <span className="ig-author">{agent}</span>
              <span className="ig-time">{fmt(p.timestamp)}</span>
              {metaTitle(p.image_meta) ? (
                <span className="ig-info" title={metaTitle(p.image_meta)}>
                  i
                </span>
              ) : null}
            </div>

            <div className="ig-image">
              <button className="ig-zoom-btn" title={t('Open fullscreen')} aria-label={t('Open fullscreen')}
                onClick={() => openMedia(p.video_url || urls[idx])}>
                <Icon name="maximize" size={16} />
              </button>
              {p.video_url ? (
                <video src={p.video_url} autoPlay loop muted playsInline onClick={() => openMedia(p.video_url!)} />
              ) : (
                <>
                  <img
                    src={urls[idx]}
                    alt="post"
                    loading="lazy"
                    onClick={() => openMedia(urls[idx])}
                  />
                  {hasCarousel ? (
                    <>
                      {idx > 0 ? (
                        <button
                          className="ig-arrow ig-arrow-l"
                          onClick={() => setCarousel((c) => ({ ...c, [p.id]: idx - 1 }))}
                        >
                          ‹
                        </button>
                      ) : null}
                      {idx < urls.length - 1 ? (
                        <button
                          className="ig-arrow ig-arrow-r"
                          onClick={() => setCarousel((c) => ({ ...c, [p.id]: idx + 1 }))}
                        >
                          ›
                        </button>
                      ) : null}
                      <button
                        className="ig-carousel-del"
                        title={t('Remove this image')}
                        onClick={() => removeCarouselImage(p, filenames[idx] || '')}
                      >
                        🗑
                      </button>
                      <div className="ig-dots">
                        {urls.map((_, i) => (
                          <span key={i} className={`ig-dot${i === idx ? ' active' : ''}`} />
                        ))}
                      </div>
                    </>
                  ) : null}
                </>
              )}
            </div>

            <div className="ig-actions">
              <button
                className={`ig-act ig-like${liked[p.id] ? ' ig-liked' : ''}`}
                onClick={() => like(p)}
              >
                ♥ <span>{p.likes || 0}</span>
              </button>
              <button className="ig-act">💬 {comments.length}</button>
              {/* Regenerate + animate need the host's game-admin dialogs. No
                  slot, no button — the flow is simply not offered there. */}
              {imageGenDialog ? (
                <button
                  className="ig-act"
                  title={t('Regenerate image')}
                  disabled={!!regenerating[p.id]}
                  onClick={() => openRegen(p)}
                >
                  {regenerating[p.id] ? '⏳' : '🔄'}
                </button>
              ) : null}
              {animateDialog ? (
                <button
                  className="ig-act"
                  title={p.video_url ? t('Re-animate') : t('Animate image')}
                  disabled={!!animating[p.id]}
                  onClick={() => setAnimatePost(p)}
                >
                  {animating[p.id] ? '⏳' : '🎬'}
                </button>
              ) : null}
              {p.video_url ? (
                <button className="ig-act" title={t('Delete animation')} onClick={() => deleteAnimation(p)}>
                  <span style={{ position: 'relative', display: 'inline-block', lineHeight: 1 }}>
                    🎬
                    <span style={{ position: 'absolute', left: -2, right: -2, top: '46%', height: 2,
                      background: '#e05656', borderRadius: 2, transform: 'rotate(-20deg)', pointerEvents: 'none' }} />
                  </span>
                </button>
              ) : null}
              <button className="ig-act ig-del"
                title={hasCarousel ? t('Delete current image') : t('Delete post')}
                onClick={() => (hasCarousel ? removeCarouselImage(p, filenames[idx] || '') : remove(p))}>
                🗑️
              </button>
            </div>

            {p.liked_by && p.liked_by.length > 0 ? (
              <div className="ig-likedby" title={p.liked_by.join(', ')}>
                {t('Liked by')} {p.liked_by.slice(0, 2).join(', ')}
                {p.liked_by.length > 2 ? ` ${t('and')} ${p.liked_by.length - 2} ${t('more')}` : ''}
              </div>
            ) : null}

            {p.caption ? <div className="ig-caption">{renderRich(p.caption)}</div> : null}

            {comments.length > 0 ? (
              <div className="ig-comments">
                {!showAll && comments.length > 2 ? (
                  <button
                    className="ig-more"
                    onClick={() => setExpanded((x) => ({ ...x, [p.id]: true }))}
                  >
                    {t('Show all {n} comments').replace('{n}', String(comments.length))}
                  </button>
                ) : null}
                {visibleComments.map((c, i) => {
                  const creatorReply = c.author === agent && c.text.startsWith('@')
                  return (
                    <div key={i} className={`ig-comment${creatorReply ? ' ig-creator' : ''}`}>
                      <span className="ig-comment-author">{c.author}</span>{' '}
                      <span>{renderRich(c.text)}</span>
                      {c.reactions && c.reactions.length > 0 ? (
                        <span className="ig-reactions">
                          {Object.entries(
                            c.reactions.reduce<Record<string, number>>((acc, r) => {
                              const k = r.emoji || '❤️'
                              acc[k] = (acc[k] || 0) + 1
                              return acc
                            }, {}),
                          ).map(([emoji, n]) => (
                            <span key={emoji} className="ig-reaction">
                              {emoji}
                              {n > 1 ? ' ' + n : ''}
                            </span>
                          ))}
                        </span>
                      ) : null}
                      {c.timestamp ? <span className="ig-comment-time">{fmt(c.timestamp)}</span> : null}
                    </div>
                  )
                })}
              </div>
            ) : null}

            <div className="ig-comment-form">
              <input
                type="text"
                maxLength={500}
                placeholder={t('Comment…')}
                value={drafts[p.id] || ''}
                onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') comment(p)
                }}
              />
              <button onClick={() => comment(p)}>{t('Send')}</button>
            </div>
          </div>
        )
      })}

      {regenPost && imageGenDialog?.({
        prompt: regenPost.image_meta?.prompt || '',
        sourceImageUrl: regenPost.image_urls?.[0] || regenPost.image_url || (regenPost.image_filename ? `/instagram/images/${regenPost.image_filename}` : ''),
        detected: charOpts?.detected || [],
        available: charOpts?.available || [],
        onSubmit: submitRegen,
        onClose: () => { setRegenPost(null); setCharOpts(null) },
      })}

      {animatePost && animateDialog?.({
        prompt: animatePost.image_meta?.image_analysis || '',
        sourceImageUrl: animatePost.image_url || `/instagram/images/${animatePost.image_filename}`,
        hasVideo: !!animatePost.video_url,
        onSuggest: suggestAnimate,
        onSubmit: submitAnimate,
        onClose: () => setAnimatePost(null),
      })}
    </div>
  )
}
