/**
 * BaseBodyOutfitStatus — under the Pose tab's outfit-model preview: how the CURRENT
 * outfit's model on the base-body pipeline stands (`base_info.outfit`).
 * Renders nothing off the pipeline (a non-humanoid; every humanoid is on it).
 *
 * The outfit model is the rigged base body with the outfit painted on by the
 * local retexture worker. Shown: its status, the worker's error when the last
 * run failed (e.g. a refused view alignment), else two numbers of the
 * worker's proof — how much of the visible surface the garment covers and
 * how much of that garment was filled in without any view seeing it.
 *
 * Dressed views the view guard left out (the edit turned the figure around)
 * are listed as warnings under the status.
 *
 * A changed base body does NOT rebuild outfit models by itself; such a model
 * reports `stale` (or was made without the base body — every humanoid's old model until its first Build,
 * Ruling A13). The button next to the status is the Figure tab's Build (FigureBuildButton, Ruling A13b:
 * POST …/figure/build, "Build (N jobs)" — no cascade of its own). "Open Figure tab" leads to the character's
 * Build and its plain body.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { useBaseBody } from './useBaseBody'
import { staleModelText } from './figureModel'
import { FigureBuildButton } from './FigureBuildButton'

/** A share (0..1) from the proof's `texels` block, or null when absent. */
function texelShare(proof: Record<string, unknown> | null, key: string): number | null {
  const texels = proof?.texels
  if (!texels || typeof texels !== 'object') return null
  const v = (texels as Record<string, unknown>)[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

const pct = (v: number) => `${(v * 100).toFixed(1)} %`

export function BaseBodyOutfitStatus({ character, onStarted, onOpenFigure }: {
  character: string
  /** A Build was started (the caller re-reads its model preview). */
  onStarted?: () => void
  /** Switches to the Figure tab. */
  onOpenFigure?: () => void
}) {
  const { t } = useI18n()
  const { info, startPoll } = useBaseBody(character)

  const outfit = info?.outfit
  if (!info?.pipeline || !outfit) return null

  const coverage = texelShare(outfit.proof, 'garment_share_of_exposed')
  const filled = texelShare(outfit.proof, 'unseen_filled_share_of_exposed_garment')
  const statusText = outfit.status === 'running' ? t('Generating…')
    : outfit.status === 'failed' ? t('Failed')
    : outfit.status === 'stale'
      ? staleModelText(outfit.stale_reason, t)
    : outfit.status === 'missing' ? t('Not built yet')
    : t('Ready')

  return (
    <div className="ga-form" style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>{t('Outfit model (base body)')}: <span className="ga-hint">{statusText}</span></span>
        <FigureBuildButton character={character} onStarted={() => { startPoll(500); onStarted?.() }} />
        {onOpenFigure ? (
          <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenFigure}>{t('Open Figure tab')}</button>
        ) : null}
      </div>
      {outfit.status === 'failed' && outfit.error ? (
        <div className="ga-hint" style={{ color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }}>
          {outfit.error}
        </div>
      ) : outfit.status !== 'running' && (coverage !== null || filled !== null) ? (
        <div className="ga-hint">
          {[
            coverage !== null ? `${t('Garment coverage of the visible surface')}: ${pct(coverage)}` : '',
            filled !== null ? `${t('Garment filled in without a view')}: ${pct(filled)}` : '',
          ].filter(Boolean).join(' · ')}
        </div>
      ) : null}
      {outfit.status !== 'running' && (outfit.warnings ?? []).map((warning) => (
        <div key={warning} className="ga-hint" style={{ color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }}>
          {warning}
        </div>
      ))}
    </div>
  )
}
