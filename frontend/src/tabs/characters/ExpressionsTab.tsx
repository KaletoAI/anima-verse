/**
 * ExpressionsTab — every cached expression variant of a character in the
 * Game-Admin, with its generation parameters. Per image: delete (inline
 * confirmation) · enlarge in the lightbox. On top, in one row: the
 * template's own settings of this tab (the expression set picker, handed in as
 * `settings`), "Generate default expression", "Clear expression cache" and
 * "Preview expression cleanup".
 *
 * Source:  GET    /characters/{name}/expressions
 * Image:   GET    /characters/{name}/expressions/{file}
 * Delete:  DELETE /characters/{name}/expressions/{file}
 * Cache:   POST   /characters/{name}/clear-expression-cache
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiDelete } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { openLightbox } from '../../components/Lightbox'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { ExpressionCleanupButton, ExpressionCleanupPreview } from './ExpressionCleanupPreview'
import { useExpressionCleanup } from './useExpressionCleanup'
import { useExpressionAttempt } from '@anima/player-ui'

interface Expression {
  file: string
  mood: string
  activity: string
  expression_set: string
  expression_key: string
  expression_label?: string
  outfit_raw: string
  contract: string
  status: 'current' | 'historical' | 'unverified'
  reason: string
  version: string
  equipped_pieces: Record<string, string>
  equipped_items: string[]
  model: string
  seed: number | null
  provider: string
  service: string
  prompt: string
  // Every LoRA the render sent (set LoRA, slot LoRAs, character LoRAs),
  // straight from the image sidecar.
  loras?: { name: string; strength?: number }[]
  // The set's default member: the outfit's base image every other
  // expression of the outfit is edited from.
  is_base?: boolean
  created_at: string
  use_count: number
  last_used_at: number
}

function loraLabel(e: Expression): string {
  return (e.loras || [])
    .filter((l) => l && l.name)
    .map((l) => (l.strength != null ? `${l.name} (${l.strength})` : l.name))
    .join(', ')
}

// One row per outfit (set + outfit identity): the base expression first, the
// rest newest first; rows keep the order of their newest image (the server
// sorts newest first).
function groupByOutfit(files: Expression[]): { key: string; items: Expression[] }[] {
  const groups = new Map<string, Expression[]>()
  for (const e of files) {
    const key = `${e.expression_set}\u0000${e.outfit_raw}`
    const list = groups.get(key)
    if (list) list.push(e)
    else groups.set(key, [e])
  }
  return [...groups.entries()].map(([key, items]) => ({
    key,
    items: [...items.filter((e) => e.is_base), ...items.filter((e) => !e.is_base)],
  }))
}

interface ExpressionsResp {
  character: string
  expressions: Expression[]
}

export function ExpressionsTab({ character, settings }: {
  character: string
  /** The template's fields of this tab (rendered by the caller's TemplateTab);
   *  they lead the header row, the action buttons follow. */
  settings?: ReactNode
}) {
  // Subscribe to the shared clock settings so the stamps above re-render
  // once the server-configured format and timezone arrive.
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const [items, setItems] = useState<Expression[] | null>(null)
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [promptOf, setPromptOf] = useState<Expression | null>(null)
  const [busy, setBusy] = useState(false)
  // Same render path as the default-expression field on the Appearance tab:
  // the one default variant, forced, for every character and temporary NPC.
  const generation = useExpressionAttempt(character)

  const copyPrompt = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast(t('Prompt copied'))
    } catch {
      toast(t('Copy failed — select the text manually'), 'error')
    }
  }

  const load = useCallback(async () => {
    if (!character) { setItems(null); return }
    try { setItems((await apiGet<ExpressionsResp>(`/characters/${encodeURIComponent(character)}/expressions`)).expressions) }
    catch { setItems([]) }
  }, [character])
  useEffect(() => { load(); setConfirmDel(null); setConfirmClear(false) }, [load])
  const cleanup = useExpressionCleanup(character, load)

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
  const fmtDate = (iso: string) => formatDateTime(iso, clockSettings())
  const piecesText = (p: Record<string, string>) => Object.values(p || {}).filter(Boolean).join(', ')

  return (
    <>
      <div className="ga-form" style={{ padding: 0 }}>
        {/* Header row: the template settings (expression set), then the actions */}
        <div className="ga-expr-header" style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap',
        }}>
          {settings ? <div className="ga-expr-settings" style={{ flex: '0 1 440px', minWidth: 0 }}>{settings}</div> : null}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <button type="button" className="ga-btn ga-btn-sm" disabled={generation.busy}
              onClick={() => void generation.start({ default_expression: true, force: true })}>
              {generation.busy ? t('Rendering…') : t('Generate default expression')}
            </button>
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
            <ExpressionCleanupButton cleanup={cleanup} />
          </div>
        </div>
        {generation.error && <div role="alert" style={{ color: 'var(--error)', fontSize: '0.85em', marginBottom: 8 }}>{generation.error}</div>}
        <div style={{ fontSize: '0.85em', opacity: 0.7, marginBottom: 8 }}>
          {files.length} {files.length === 1 ? t('expression') : t('expressions')}
          {' · '}{files.filter(e => e.status === 'current').length} {t('Current')}
          {' · '}{files.filter(e => e.status !== 'current').length} {t('Historical or unverified')}
        </div>
        <ExpressionCleanupPreview cleanup={cleanup} />

        {files.length === 0 ? (
          <div className="ga-placeholder">{t('No cached expressions yet')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {groupByOutfit(files).map((g) => (
              <div key={g.key}>
                {/* One row per outfit: its base expression first, then the expressions edited from it */}
                <div style={{ fontSize: '0.82em', marginBottom: 6, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
                  <strong title={g.items[0].outfit_raw}>{piecesText(g.items[0].equipped_pieces) || t('No equipped pieces')}</strong>
                  <span style={{ opacity: 0.6 }}>{g.items[0].expression_set || t('Legacy')} · {g.items.length} {g.items.length === 1 ? t('expression') : t('expressions')}</span>
                  {!g.items[0].is_base && <span style={{ opacity: 0.6 }}>· {t('No base expression')}</span>}
                </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
            {g.items.map((e) => {
              const confirming = confirmDel === e.file
              const pieces = piecesText(e.equipped_pieces)
              const tip = [
                `expression: ${e.expression_key || '—'}`, `set: ${e.expression_set || '—'}`, `mood: ${e.mood || '—'}`,
                `status: ${e.status}`, `reason: ${e.reason}`, `outfit identity: ${e.outfit_raw}`,
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
                  {/* Parameter caption */}
                  <div style={{ padding: '6px 8px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <div style={{ fontSize: '0.82em', fontWeight: 600 }} title={e.mood}>
                      {e.expression_label || e.expression_key || t('Unverified')}
                      {e.is_base && <span style={{ marginLeft: 6, fontSize: '0.85em', fontWeight: 400, opacity: 0.75 }}
                        title={t('The base expression of this outfit: rendered without the set LoRA, the reference of every other expression')}>
                        ★ {t('Base')}
                      </span>}
                    </div>
                    <div style={{ fontSize: '0.78em', opacity: 0.85 }}>
                      {e.expression_set || t('Legacy')} · {e.status === 'current' ? t('Current') : e.status === 'historical' ? t('Historical') : t('Unverified')}
                    </div>
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
                    {loraLabel(e) && (
                      <div style={{ fontSize: '0.7em', opacity: 0.7 }} title={loraLabel(e)}>
                        🎛 {loraLabel(e)}
                      </div>
                    )}
                    {e.created_at && <div style={{ fontSize: '0.68em', opacity: 0.45 }}>{fmtDate(e.created_at)}</div>}
                    {/* Final prompt: view + copy */}
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
              </div>
            ))}
          </div>
        )}

        {/* Prompt viewer (viewable + copyable) */}
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
                  {t('Final prompt')} — {promptOf.expression_label || promptOf.expression_key || t('Unverified')}
                  {promptOf.expression_set ? ` · ${promptOf.expression_set}` : ''}
                </strong>
                <button type="button" className="ga-btn ga-btn-sm" onClick={() => setPromptOf(null)}>{t('Close')}</button>
              </div>
              <div style={{ fontSize: '0.8em', opacity: 0.8 }}>
                {t('LoRAs')}: {loraLabel(promptOf) || '—'}
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
    </>
  )
}
