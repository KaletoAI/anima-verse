/**
 * TemplateParamsDialog — the parameter dialog of an outfit piece in mode "template" (Ruling A138): the sewing-pattern
 * parameters the drape is made from (kind, length, flare, waistband, slit, sleeves, fabric), with a 1.70 m reference
 * figure that draws the piece at its length and flare (checklist 7). "Suggest from picture" asks the vision task
 * ONCE (1 LLM call, nothing saved) and fills the fields; Save stores them on the ITEM (every wearer) and spends
 * nothing — the next Build re-drapes (CPU, 0 hub jobs). Rendered through a portal; no native dialogs.
 */
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { TEMPLATE_CHOICE_LABELS, TEMPLATE_FIELD_LABELS, cm, templateCost } from './figureModel'
import type { TemplateFieldSpec, TemplateInfo, TemplateParams } from './figureModel'

interface TemplatePayload {
  item_id: string
  name: string
  params: TemplateParams | null
  source: string
  updated_at: string
  spec: Record<keyof TemplateParams, TemplateFieldSpec>
  built: string[]
  cost: TemplateInfo['cost']
}

const GRID: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '6px 12px' }
const WARN: CSSProperties = { color: 'var(--warning, #d29922)' }
const ORDER: (keyof TemplateParams)[] = ['kind', 'fabric', 'length_m', 'flare', 'waist_height', 'sleeves', 'slit',
  'slit_m']

function defaults(spec: TemplatePayload['spec']): TemplateParams {
  const out: Record<string, string | number> = {}
  for (const key of ORDER) out[key] = spec[key].default
  return out as unknown as TemplateParams
}

/** The 1.70 m reference figure with the piece drawn at its length and flare (checklist 7: a metre value has a
 *  reference). Scale: 1 m = 100 px; waist at 1.05 m (the reference body), chest band at 1.275 m. */
function ReferenceFigure({ p }: { p: TemplateParams }) {
  const { t } = useI18n()
  const H = 170
  const y = (m: number) => H + 10 - m * 100
  const waist = p.waist_height === 'high' ? 1.08 : p.waist_height === 'low' ? 0.98 : 1.05
  const top = p.kind === 'dress' ? 1.275 : waist
  const hem = Math.max(0.05, waist - p.length_m)
  const halfTop = p.kind === 'dress' ? 14 : 12
  const halfHem = 16 * (1 + 1.5 * p.flare)
  const cx = 60
  return (
    <svg width={120} height={H + 20} role="img" aria-label={t('1.70 m reference figure')}
      style={{ border: '1px solid var(--border, #30363d)', borderRadius: 4, flex: '0 0 auto' }}>
      {[0, 0.5, 1.0, 1.5].map((m) => (
        <g key={m}>
          <line x1={0} x2={8} y1={y(m)} y2={y(m)} stroke="currentColor" opacity={0.5} />
          <text x={10} y={y(m) + 3} fontSize={8} fill="currentColor" opacity={0.7}>{m.toFixed(1)} m</text>
        </g>
      ))}
      <circle cx={cx} cy={y(1.58)} r={9} fill="none" stroke="currentColor" opacity={0.6} />
      <line x1={cx} x2={cx} y1={y(1.49)} y2={y(0.9)} stroke="currentColor" opacity={0.6} />
      <line x1={cx - 30} x2={cx + 30} y1={y(1.42)} y2={y(1.42)} stroke="currentColor" opacity={0.6} />
      <line x1={cx} x2={cx - 10} y1={y(0.9)} y2={y(0.02)} stroke="currentColor" opacity={0.6} />
      <line x1={cx} x2={cx + 10} y1={y(0.9)} y2={y(0.02)} stroke="currentColor" opacity={0.6} />
      <polygon fill="var(--accent, #6aa9ff)" opacity={0.55}
        points={[[cx - halfTop, y(top)], [cx + halfTop, y(top)], [cx + 11, y(waist)], [cx + halfHem, y(hem)],
          [cx - halfHem, y(hem)], [cx - 11, y(waist)]].map((q) => q.join(',')).join(' ')} />
      {p.slit !== 'none' && p.slit_m > 0 ? (
        <line x1={p.slit === 'left' ? cx + halfHem - 3 : p.slit === 'right' ? cx - halfHem + 3 : cx}
          x2={p.slit === 'left' ? cx + halfHem - 3 : p.slit === 'right' ? cx - halfHem + 3 : cx}
          y1={y(hem)} y2={y(hem + p.slit_m)} stroke="var(--bg, #0d1117)" strokeWidth={2} />
      ) : null}
      <text x={cx + halfHem + 2} y={y(hem) + 3} fontSize={8} fill="currentColor">{cm(hem)}</text>
    </svg>
  )
}

export function TemplateParamsDialog({ character, itemId, onClose, onSaved }: {
  character: string
  itemId: string
  onClose: () => void
  /** Saved on the item: the caller reloads its rows (the drape is due for the next Build). */
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const path = `/characters/${encodeURIComponent(character)}/figure/template/${encodeURIComponent(itemId)}`
  const [data, setData] = useState<TemplatePayload | null>(null)
  const [draft, setDraft] = useState<TemplateParams | null>(null)
  const [source, setSource] = useState<'llm' | 'user'>('user')
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [busy, setBusy] = useState<'' | 'suggest' | 'save'>('')
  const [saved, setSaved] = useState('')
  useEffect(() => {
    let gone = false
    apiGet<TemplatePayload>(path)
      .then((p) => {
        if (gone) return
        setData(p)
        setDraft(p.params || defaults(p.spec))
        setSource(p.source === 'llm' ? 'llm' : 'user')
      })
      .catch((e) => { if (!gone) setError((e as Error).message) })
    return () => { gone = true }
  }, [path])
  const set = (key: keyof TemplateParams, value: string | number) => {
    if (!draft) return
    setDraft({ ...draft, [key]: value })
    setSource('user')
    setSaved('')
  }
  const suggest = async () => {
    setBusy('suggest')
    setError('')
    try {
      const r = await apiPost<{ params: TemplateParams; errors: string[] }>(`${path}/suggest`, {})
      setDraft(r.params)
      setWarnings(r.errors || [])
      setSource('llm')
      setSaved('')
      toast(t('Suggested from the picture — check and save'), 'success')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }
  const save = async () => {
    if (!draft) return
    setBusy('save')
    setError('')
    try {
      await apiPut(path, { params: draft, source })
      setSaved(t('Saved — the next Build drapes it (CPU, 0 hub jobs)'))
      toast(t('Template parameters saved'), 'success')
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }
  const title = t('Template parameters — {name}').replace('{name}', data?.name || itemId)
  const kindBuilt = !draft || !data || data.built.includes(draft.kind)
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={title} style={{ maxWidth: 720 }}>
        <div className="ga-modal-header"><h3>{title}</h3></div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
          {!data && !error ? <div className="ga-hint">{t('Loading…')}</div> : null}
          {data && draft ? (
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <ReferenceFigure p={draft} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 0 }}>
                <div style={GRID}>
                  {ORDER.map((key) => {
                    const f = data.spec[key]
                    if (key === 'slit_m' && draft.slit === 'none') return <span key={key} />
                    return (
                      <label key={key} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span className="ga-form-hint">{t(TEMPLATE_FIELD_LABELS[key])}</span>
                        {f.type === 'choice' ? (
                          <select className="ga-input" value={String(draft[key])}
                            onChange={(e) => set(key, e.target.value)}>
                            {f.choices.map((c) => (
                              <option key={c} value={c}>
                                {t(TEMPLATE_CHOICE_LABELS[c] || c)}
                                {key === 'kind' && !data.built.includes(c) ? ` (${t('not built yet')})` : ''}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input type="range" min={f.min} max={f.max} step={0.01} style={{ flex: 1 }}
                              value={Number(draft[key])} onChange={(e) => set(key, Number(e.target.value))} />
                            <span style={{ width: 52, textAlign: 'right' }}>
                              {key === 'flare' ? Number(draft[key]).toFixed(2) : cm(Number(draft[key]))}
                            </span>
                          </span>
                        )}
                      </label>
                    )
                  })}
                </div>
                {!kindBuilt ? (
                  <div className="ga-hint" style={WARN}>
                    {t('This kind is not draped yet — the piece stays left off until skirts and dresses are joined by it.')}
                  </div>
                ) : null}
                {draft.sleeves !== 'none' ? (
                  <div className="ga-hint">{t('Sleeves are recorded; pieces are draped sleeveless for now.')}</div>
                ) : null}
                {warnings.length ? (
                  <div className="ga-hint" style={WARN} title={warnings.join('\n')}>
                    {t('The suggestion had {n} value(s) out of range — corrected').replace('{n}', String(warnings.length))}
                  </div>
                ) : null}
                <div className="ga-hint">
                  {source === 'llm' ? t('Values from the picture suggestion') : t('Values set by hand')}
                  {data.updated_at ? ` · ${t('saved {at}').replace('{at}', data.updated_at.replace('T', ' ').slice(0, 16))}` : ''}
                </div>
                <div className="ga-hint">{templateCost(data.cost, t)}</div>
                {saved ? <div className="ga-hint" style={{ color: 'var(--success, #3fb950)' }}>{saved}</div> : null}
              </div>
            </div>
          ) : null}
          {error ? <div className="ga-hint" style={WARN}>{error}</div> : null}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
          <button type="button" className="ga-btn" disabled={!data || !!busy} onClick={() => { void suggest() }}
            title={t('Reads the item picture and text with the vision model; fills the fields, saves nothing')}>
            {busy === 'suggest' ? t('Asking the LLM…') : t('Suggest from picture (1 LLM call)')}
          </button>
          <span style={{ display: 'flex', gap: 6 }}>
            <button type="button" className="ga-btn" disabled={!!busy} onClick={onClose}>{t('Close')}</button>
            <button type="button" className="ga-btn ga-btn-primary" disabled={!draft || !!busy}
              onClick={() => { void save() }}>{busy === 'save' ? t('Saving…') : t('Save')}</button>
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
