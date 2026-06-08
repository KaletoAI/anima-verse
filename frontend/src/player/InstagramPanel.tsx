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
  const [zoom, setZoom] = useState<string | null>(null)
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
              {p.video_url ? (
                <video src={p.video_url} autoPlay loop muted playsInline onClick={() => setZoom(p.video_url!)} />
              ) : (
                <>
                  <img
                    src={urls[idx]}
                    alt="post"
                    loading="lazy"
                    onClick={() => setZoom(urls[idx])}
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
              <button className="ig-act ig-del" title={t('Delete post')} onClick={() => remove(p)}>
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

      {zoom ? (
        <div className="ig-lightbox" onClick={() => setZoom(null)}>
          {zoom.endsWith('.mp4') || zoom.includes('/images/') && /\.(mp4|webm)$/.test(zoom) ? (
            <video src={zoom} autoPlay loop controls />
          ) : (
            <img src={zoom} alt="zoom" />
          )}
        </div>
      ) : null}
    </div>
  )
}
