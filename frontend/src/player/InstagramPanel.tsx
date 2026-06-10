/**
 * InstagramPanel — der Instagram-Feed im Player-UI (/play), portiert aus der
 * alten UI. Phase 1: Feed-Anzeige (Avatar, Bild/Carousel/Video, Caption +
 * Hashtags, Likes/liked_by, Kommentare mit Reaktionen/@Mentions/Creator-Reply)
 * plus die direkten Aktionen Like, Comment, Delete und Carousel-Navigation
 * (inkl. einzelnes Bild entfernen). Regenerate + Animate (große geteilte
 * Dialoge) folgen als eigene Schritte.
 * Quelle: /instagram/feed (+ /post/{id}/like|comment, DELETE /post/{id}).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost, apiDelete } from '../lib/api'
import { useToast } from '../lib/Toast'
import { ImageGenDialog, type ImageGenSubmit } from '../components/ImageGenDialog'
import { AnimateDialog, type AnimateSubmit } from '../components/AnimateDialog'
import { useLightbox } from './Lightbox'
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
  workflow?: string
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
  if (m.workflow) parts.push(`Workflow: ${m.workflow}`)
  if (m.postprocessed) parts.push('Post-processing: external')
  if (m.duration_s) parts.push(`Duration: ${m.duration_s}s`)
  if (m.image_analysis) parts.push(`Analysis: ${m.image_analysis}`)
  return parts.join('\n')
}

export function InstagramPanel() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [posts, setPosts] = useState<Post[] | null>(null)
  const [carousel, setCarousel] = useState<Record<string, number>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [avatarFail, setAvatarFail] = useState<Record<string, boolean>>({})
  const [liked, setLiked] = useState<Record<string, boolean>>({})
  const lightbox = useLightbox()
  // Bild/Video aus dem Feed in der gemeinsamen Lightbox öffnen (Video an der
  // Endung erkennen → Lightbox zeigt Video mit Steuerung statt Zoom).
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
  const alive = useRef(true)

  const reload = useCallback(async () => {
    try {
      const d = await apiGet<{ posts?: Post[] }>('/instagram/feed?limit=50')
      if (alive.current) setPosts(d.posts || [])
    } catch {
      /* auth handled globally */
    }
  }, [])

  useEffect(() => {
    alive.current = true
    reload()
    const id = setInterval(reload, 12000)
    return () => {
      alive.current = false
      clearInterval(id)
    }
  }, [reload])

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
    async (payload: ImageGenSubmit) => {
      const p = regenPost
      if (!p) return
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
    async (payload: AnimateSubmit) => {
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
              <button
                className="ig-act"
                title={t('Regenerate image')}
                disabled={!!regenerating[p.id]}
                onClick={() => openRegen(p)}
              >
                {regenerating[p.id] ? '⏳' : '🔄'}
              </button>
              <button
                className="ig-act"
                title={p.video_url ? t('Re-animate') : t('Animate image')}
                disabled={!!animating[p.id]}
                onClick={() => setAnimatePost(p)}
              >
                {animating[p.id] ? '⏳' : '🎬'}
              </button>
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

      {regenPost ? (
        <ImageGenDialog
          open
          title={t('Regenerate image')}
          defaultPrompt={regenPost.image_meta?.prompt || ''}
          showCreateNew
          showImprovement
          showNegative
          characterOptions={charOpts || { detected: [], available: [] }}
          onSubmit={submitRegen}
          onClose={() => { setRegenPost(null); setCharOpts(null) }}
        />
      ) : null}

      {animatePost ? (
        <AnimateDialog
          open
          title={animatePost.video_url ? t('Re-animate') : t('Animate image')}
          sourceImageUrl={animatePost.image_url || `/instagram/images/${animatePost.image_filename}`}
          defaultPrompt={animatePost.image_meta?.image_analysis || ''}
          characterName={animatePost.agent_name || ''}
          onSuggest={suggestAnimate}
          onSubmit={submitAnimate}
          onClose={() => setAnimatePost(null)}
        />
      ) : null}
    </div>
  )
}
