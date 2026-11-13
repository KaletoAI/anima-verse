/**
 * HairstyleParts — small parts of the Hairstyles tab (FieldHairstyles; plan
 * docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 14, rebuilt in Task UI4):
 *
 * - Swatch: a colour square (the hair colour in use).
 * - FigureBuildLine: the character's pending changes and ONE "Build (cost)" button (POST
 *   /characters/{n}/figure/build) — shown after a Wear or a mode change.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { WARN_STYLE } from './garmentStyle'
import { BuildSteps } from './WardrobeGarment'
import { BUILD_STATUS, figureBuildLine } from './figureModel'

export function Swatch({ hex }: { hex: string }) {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block', width: 18, height: 18, borderRadius: 4, background: hex,
        border: '1px solid var(--border, #30363d)', verticalAlign: 'middle',
      }}
    />
  )
}

/** GET /characters/{n}/figure — the parts the hair row reads. */
interface FigureCost {
  pipeline: boolean
  changes: Array<{ key: string; name: string }>
  cost: { hub_jobs: number | null; note: string; steps: Array<{ label: string }> }
}

/** The line after a Wear or a hair mode change: the character's pending changes and
 *  ONE "Build (cost)" button (POST /characters/{n}/figure/build — a manual
 *  Build); its reason under it when there is nothing to build. */
export function FigureBuildLine({ character, version }: { character: string; version: number }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [data, setData] = useState<FigureCost | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    try {
      setData(await apiGet<FigureCost>(`/characters/${enc}/figure`))
      setError('')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [enc])
  useEffect(() => { void load() }, [load, version])
  if (error) return <div className="ga-hint" style={WARN_STYLE}>{error}</div>
  if (!data) return <div className="ga-hint">{t('Loading…')}</div>
  const changes = data.changes.length
  const line = figureBuildLine(changes, data.cost.hub_jobs)
  const jobs = data.cost.hub_jobs === null ? t('cost unknown')
    : data.cost.hub_jobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(data.cost.hub_jobs))
  const build = async () => {
    setBusy(true)
    try {
      const d = await apiPost<{ status: string }>(`/characters/${enc}/figure/build`, {})
      toast(t(BUILD_STATUS[d.status] || d.status), 'success')
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: '0.75em' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span>
          {changes === 0 ? t('No changes') : changes === 1 ? t('1 change')
            : t('{n} changes').replace('{n}', String(changes))}
          {changes ? `: ${data.changes.map((c) => t(c.name)).join(', ')}` : ''}
        </span>
        {line.button ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} title={t(data.cost.note)}
            onClick={() => { void build() }}>
            {t('Build ({cost})').replace('{cost}', jobs)}
          </button>
        ) : null}
      </div>
      {line.reason ? <span className="ga-hint">{t(line.reason)}</span> : null}
      <BuildSteps steps={data.cost.steps.map((s) => s.label)}
        summary={t('What the Build runs ({cost})').replace('{cost}', jobs)} />
    </div>
  )
}
