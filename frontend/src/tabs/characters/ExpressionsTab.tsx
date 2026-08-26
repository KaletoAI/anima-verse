/**
 * ExpressionsTab — every cached expression variant of a character in the
 * Game-Admin, with its generation parameters. Per image: delete (inline
 * confirmation) · enlarge in the lightbox. On top: "Clear expression cache".
 *
 * Source:  GET    /characters/{name}/expressions
 * Image:   GET    /characters/{name}/expressions/{file}
 * Delete:  DELETE /characters/{name}/expressions/{file}
 * Cache:   POST   /characters/{name}/clear-expression-cache
 *
 * `readOnly` is the temporary-NPC mode (see DefaultExpressionOnly): that
 * character kind has no variants at all, only the ONE default one it is
 * shown by, so the grid would be the wrong picture of the subject.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiDelete } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { LightboxProvider, openLightbox } from '../../player/Lightbox'

interface Expression {
  file: string
  mood: string
  activity: string
  equipped_pieces: Record<string, string>
  equipped_items: string[]
  model: string
  seed: number | null
  provider: string
  service: string
  prompt: string
  created_at: string
  use_count: number
  last_used_at: number
}

interface ExpressionsResp {
  character: string
  expressions: Expression[]
}

/** How long the re-render is polled for before the view gives up (4 s steps). */
const POLL_LIMIT = 45

/**
 * The read-only Expressions tab of a temporary NPC: its ONE default variant
 * and a button that renders it again.
 *
 * WHY `override=1`: without it the route fills an empty `mood` from the
 * character's current feeling and an empty `pose_key` from its effective pose
 * key, i.e. it asks for the variant of the current MOMENT. A temporary NPC has
 * exactly one variant — mood "" and pose "" (`npc_assets._render_default_
 * expression`) — and asking for any other one would answer 404 forever,
 * because its template's `expression_variants_enabled` gate refuses to
 * generate. `override=1` pins both axes to empty; the equipped state it
 * implies (no pieces, no items) is this NPC's real one, since its template has
 * no outfit system, so the key resolves to the very file the finishing job
 * wrote.
 *
 * WHY NO `fallback=default`: it would make this view LIE. While a render runs,
 * the route answers the fallback chain instead of 202
 * (`routes/characters.py:1022-1024`), and step 1 of that chain is
 * `find_nearest_expression` — which scores sidecars by outfit similarity, and
 * "empty vs empty is 1.0" (`outfit_match.outfit_similarity`). A temporary NPC
 * has an EMPTY equipped state in every sidecar it ever wrote, so every
 * leftover variant ties at the top and the newest one is served with 200. That
 * is exactly the picture of the OLD outfit, orphaned by the very edit that
 * queued this render and still on disk until `outfit_cache_gc` reaps it — and
 * a 200 fires `onLoad`, which stops the polling and presents it as the result.
 * Without the parameter a cache miss is 202 or 404, both of which keep the
 * "Rendering…" overlay up and the poll running until the real file lands.
 *
 * The button adds `trigger=1&force=1`: `force` deletes the cached file, and
 * `trigger` is what makes the route pass `ignore_feature_gate=True` — the one
 * documented way past the closed variant gate, the same one the finishing job
 * takes. The answer is 202 ("generating"), so the image is polled afterwards.
 */
function DefaultExpressionOnly({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [nonce, setNonce] = useState(1)
  const [polls, setPolls] = useState(0)
  const [rendering, setRendering] = useState(false)
  const [ready, setReady] = useState<boolean | null>(null)

  const base = `/characters/${encodeURIComponent(character)}/outfit-expression`
  const src = `${base}?override=1&_=${nonce}`

  useEffect(() => {
    setRendering(false)
    setPolls(0)
    setReady(null)
    setNonce((n) => n + 1)
  }, [character])

  // Poll while a render is running — the generator is a background thread, so
  // nothing tells this view when the file lands.
  useEffect(() => {
    if (!rendering) return
    if (polls >= POLL_LIMIT) {
      setRendering(false)
      return
    }
    const id = window.setTimeout(() => {
      setPolls((p) => p + 1)
      setNonce((n) => n + 1)
    }, 4000)
    return () => window.clearTimeout(id)
  }, [rendering, polls])

  const rerender = async () => {
    if (rendering) return
    setRendering(true)
    setPolls(0)
    try {
      await apiGet(`${base}?override=1&trigger=1&force=1`)
      toast(t('Rendering the default expression — this takes a moment.'))
      setReady(null)
      setNonce((n) => n + 1)
    } catch (e) {
      setRendering(false)
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }

  return (
    <LightboxProvider>
      <div className="ga-form" style={{ padding: 0 }}>
        <div style={{ fontSize: '0.82em', opacity: 0.7, marginBottom: 12 }}>
          {t('This character kind has no mood or pose variants — it is shown by this one default expression.')}
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {/* The image stays MOUNTED even while it 404s: the poll works by
              changing its src, and an unmounted img would never re-fetch. */}
          <div style={{
            position: 'relative', width: 220, aspectRatio: '3 / 4', borderRadius: 8,
            overflow: 'hidden', border: '1px solid var(--border, #30363d)',
            background: 'var(--bg, #0d1117)',
          }}>
            <img src={src} alt={t('Default expression')}
              onLoad={() => { setReady(true); setRendering(false) }}
              onError={() => setReady(false)}
              onClick={() => { if (ready === true) openLightbox({ src, alt: t('Default expression') }) }}
              style={{
                width: '100%', height: '100%', objectFit: 'cover',
                display: ready === true ? 'block' : 'none', cursor: 'zoom-in',
              }} />
            {ready !== true && (
              <div style={{
                position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
                justifyContent: 'center', padding: 10, textAlign: 'center',
                fontSize: '0.8em', opacity: 0.6,
              }}>
                {/* `null` = the first load has not answered yet: say nothing
                    rather than claim there is no picture. */}
                {rendering ? t('Rendering…') : ready === false ? t('No default expression yet') : ''}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button type="button" className="ga-btn ga-btn-sm" disabled={rendering} onClick={rerender}>
              {rendering ? t('Rendering…') : t('Re-render default expression')}
            </button>
            {rendering && (
              <span style={{ fontSize: '0.76em', opacity: 0.6 }}>
                {t('The picture appears here as soon as the backend delivers it.')}
              </span>
            )}
          </div>
        </div>
      </div>
    </LightboxProvider>
  )
}

export function ExpressionsTab({ character, readOnly = false }: { character: string; readOnly?: boolean }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [items, setItems] = useState<Expression[] | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [promptOf, setPromptOf] = useState<Expression | null>(null)
  const [busy, setBusy] = useState(false)

  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast(t('Prompt copied'))
    } catch {
      toast(t('Copy failed — select the text manually'), 'error')
    }
  }

  const load = useCallback(async () => {
    if (!character || readOnly) { setItems(null); return }
    try { setItems((await apiGet<ExpressionsResp>(`/characters/${encodeURIComponent(character)}/expressions`)).expressions) }
    catch { setItems([]) }
  }, [character, readOnly])
  useEffect(() => { load(); setConfirmDel(null); setConfirmClear(false) }, [load])

  const imgUrl = (f: string) => `/characters/${encodeURIComponent(character)}/expressions/${encodeURIComponent(f)}`

  const del = async (f: string) => {
    if (busy) return
    setBusy(true)
    try {
      await apiDelete(`/characters/${encodeURIComponent(character)}/expressions/${encodeURIComponent(f)}`)
      setItems((d) => (d ? d.filter((e) => e.file !== f) : d))
      setConfirmDel(null)
    } catch (e) { toast(t('Error') + ': ' + (e as Error).message, 'error') } finally { setBusy(false) }
  }

  const clearCache = async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await apiPost<{ deleted?: number }>(
        `/characters/${encodeURIComponent(character)}/clear-expression-cache`, {})
      const n = typeof r?.deleted === 'number' ? r.deleted : 0
      toast(t('Expression cache cleared') + ` (${n})`)
      setConfirmClear(false)
      await load()
    } catch (e) { toast(t('Error') + ': ' + (e as Error).message, 'error') } finally { setBusy(false) }
  }

  if (!character) return <div className="ga-form"><div className="ga-placeholder">{t('No character selected')}</div></div>
  // A temporary NPC: the grid would render a cache that structurally holds a
  // single entry, next to a delete button for the only picture the NPC has.
  if (readOnly) return <DefaultExpressionOnly character={character} />

  const files = items || []
  const fmtDate = (iso: string) => (iso ? iso.replace('T', ' ').replace(/(\+\d\d:\d\d|Z)$/, '').slice(0, 16) : '')
  const piecesText = (p: Record<string, string>) => Object.values(p || {}).filter(Boolean).join(', ')

  return (
    <LightboxProvider>
      <div className="ga-form" style={{ padding: 0 }}>
        {/* Header: Clear expression cache */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 10, marginBottom: 12, flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: '0.85em', opacity: 0.7 }}>
            {files.length} {files.length === 1 ? t('expression') : t('expressions')}
          </span>
          {confirmClear ? (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: '0.82em' }}>{t('Clear ALL cached expressions?')}</span>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy} onClick={clearCache}>
                {busy ? t('Clearing…') : t('Clear')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm" onClick={() => setConfirmClear(false)}>{t('Cancel')}</button>
            </div>
          ) : (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
              disabled={!files.length && items !== null} onClick={() => setConfirmClear(true)}>
              {t('Clear expression cache')}
            </button>
          )}
        </div>

        {files.length === 0 ? (
          <div className="ga-placeholder">{t('No cached expressions yet')}</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
            {files.map((e) => {
              const confirming = confirmDel === e.file
              const pieces = piecesText(e.equipped_pieces)
              const tip = [
                `mood: ${e.mood || '—'}`, `activity: ${e.activity || '—'}`,
                pieces && `outfit: ${pieces}`,
                e.service && `backend: ${e.service}`, e.model && `model: ${e.model}`,
                e.seed != null && `seed: ${e.seed}`, e.created_at && `created: ${fmtDate(e.created_at)}`,
                e.use_count != null && `used: ${e.use_count}×`,
              ].filter(Boolean).join('\n')
              return (
                <div key={e.file} style={{
                  borderRadius: 8, overflow: 'hidden', background: 'var(--bg, #0d1117)',
                  border: '1px solid var(--border, #30363d)', display: 'flex', flexDirection: 'column',
                }}>
                  <div style={{ position: 'relative', aspectRatio: '3 / 4' }}>
                    <img src={imgUrl(e.file)} alt={e.file} loading="lazy" title={tip}
                      onClick={() => openLightbox({ src: imgUrl(e.file), alt: e.file })}
                      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block', cursor: 'zoom-in' }} />
                    {confirming ? (
                      <div style={{
                        position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                        alignItems: 'center', justifyContent: 'center', gap: 8, padding: 8,
                        background: 'rgba(10,12,16,0.86)', textAlign: 'center',
                      }}>
                        <span style={{ fontSize: '0.82em' }}>{t('Delete this expression?')}</span>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy} onClick={() => del(e.file)}>
                            {busy ? t('Deleting…') : t('Delete')}
                          </button>
                          <button type="button" className="ga-btn ga-btn-sm" onClick={() => setConfirmDel(null)}>{t('Cancel')}</button>
                        </div>
                      </div>
                    ) : (
                      <button type="button" title={t('Delete expression')} aria-label={t('Delete expression')}
                        onClick={() => setConfirmDel(e.file)}
                        style={{
                          position: 'absolute', top: 4, right: 4, width: 26, height: 26, borderRadius: 6,
                          border: '1px solid rgba(255,255,255,0.18)', background: 'rgba(20,22,28,0.7)',
                          color: '#fff', cursor: 'pointer', lineHeight: 1, fontSize: '0.9em',
                        }}>🗑</button>
                    )}
                  </div>
                  {/* Parameter-Caption */}
                  <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <div style={{ fontSize: '0.82em', fontWeight: 600 }} title={e.mood}>
                      😊 {e.mood || <span style={{ opacity: 0.5 }}>{t('neutral')}</span>}
                    </div>
                    <div style={{ fontSize: '0.78em', opacity: 0.85 }} title={e.activity}>
                      {e.activity ? `🚶 ${e.activity}` : <span style={{ opacity: 0.5 }}>🚶 —</span>}
                    </div>
                    {pieces && <div style={{ fontSize: '0.72em', opacity: 0.6 }} title={pieces}>👕 {pieces}</div>}
                    {e.service && (
                      <div style={{ fontSize: '0.7em', opacity: 0.55 }} title={e.service}>
                        ⚙ {e.service}
                      </div>
                    )}
                    {(e.model || e.seed != null) && (
                      <div style={{ fontSize: '0.7em', opacity: 0.55 }} title={`${e.model} · seed ${e.seed}`}>
                        {[e.model, e.seed != null ? `#${e.seed}` : ''].filter(Boolean).join(' · ')}
                      </div>
                    )}
                    {e.created_at && <div style={{ fontSize: '0.68em', opacity: 0.45 }}>{fmtDate(e.created_at)}</div>}
                    {/* Final prompt: ansehen + kopieren */}
                    <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                      <button type="button" className="ga-btn ga-btn-sm" style={{ fontSize: '0.7em', padding: '2px 6px' }}
                        disabled={!e.prompt} onClick={() => setPromptOf(e)}>
                        📄 {t('Prompt')}
                      </button>
                      <button type="button" className="ga-btn ga-btn-sm" style={{ fontSize: '0.7em', padding: '2px 6px' }}
                        disabled={!e.prompt} title={t('Copy prompt')} onClick={() => copyPrompt(e.prompt)}>
                        📋
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Prompt-Viewer (ansehbar + kopierbar) */}
        {promptOf && (
          <div onClick={() => setPromptOf(null)}
            style={{
              position: 'fixed', inset: 0, zIndex: 1000, display: 'flex',
              alignItems: 'center', justifyContent: 'center', padding: 24,
              background: 'rgba(8,10,14,0.7)',
            }}>
            <div onClick={(ev) => ev.stopPropagation()}
              style={{
                width: 'min(720px, 100%)', maxHeight: '80vh', display: 'flex', flexDirection: 'column',
                gap: 10, padding: 16, borderRadius: 10, background: 'var(--bg, #0d1117)',
                border: '1px solid var(--border, #30363d)',
              }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10 }}>
                <strong style={{ fontSize: '0.9em' }}>
                  {t('Final prompt')} — 😊 {promptOf.mood || t('neutral')}
                  {promptOf.activity ? ` · 🚶 ${promptOf.activity}` : ''}
                </strong>
                <button type="button" className="ga-btn ga-btn-sm" onClick={() => setPromptOf(null)}>{t('Close')}</button>
              </div>
              <textarea readOnly value={promptOf.prompt} onFocus={(ev) => ev.currentTarget.select()}
                style={{
                  flex: 1, minHeight: 200, resize: 'vertical', width: '100%', boxSizing: 'border-box',
                  fontFamily: 'monospace', fontSize: '0.82em', lineHeight: 1.4, padding: 10, borderRadius: 8,
                  background: 'var(--bg-elev, #161b22)', color: 'inherit', border: '1px solid var(--border, #30363d)',
                }} />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" onClick={() => copyPrompt(promptOf.prompt)}>
                  📋 {t('Copy prompt')}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </LightboxProvider>
  )
}
