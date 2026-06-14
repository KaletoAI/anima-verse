/**
 * ExpressionsTab — alle gecachten Expression-Variants eines Characters im
 * Game-Admin, mit ihren Generierungs-Parametern. Pro Bild: Löschen (Inline-
 * Bestätigung) · vergrößern in der Lightbox. Oben: „Clear expression cache".
 *
 * Quelle:  GET    /characters/{name}/expressions
 * Bild:    GET    /characters/{name}/expressions/{file}
 * Löschen: DELETE /characters/{name}/expressions/{file}
 * Cache:   POST   /characters/{name}/clear-expression-cache
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
  workflow: string
  prompt: string
  created_at: string
  use_count: number
  last_used_at: number
}

interface ExpressionsResp {
  character: string
  expressions: Expression[]
}

export function ExpressionsTab({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [items, setItems] = useState<Expression[] | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!character) { setItems(null); return }
    try { setItems((await apiGet<ExpressionsResp>(`/characters/${encodeURIComponent(character)}/expressions`)).expressions) }
    catch { setItems([]) }
  }, [character])
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
                pieces && `outfit: ${pieces}`, e.workflow && `workflow: ${e.workflow}`,
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
                    {(e.workflow || e.service) && (
                      <div style={{ fontSize: '0.7em', opacity: 0.55 }} title={`${e.workflow} · ${e.service}`}>
                        ⚙ {[e.workflow, e.service].filter(Boolean).join(' · ')}
                      </div>
                    )}
                    {(e.model || e.seed != null) && (
                      <div style={{ fontSize: '0.7em', opacity: 0.55 }} title={`${e.model} · seed ${e.seed}`}>
                        {[e.model, e.seed != null ? `#${e.seed}` : ''].filter(Boolean).join(' · ')}
                      </div>
                    )}
                    {e.created_at && <div style={{ fontSize: '0.68em', opacity: 0.45 }}>{fmtDate(e.created_at)}</div>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </LightboxProvider>
  )
}
