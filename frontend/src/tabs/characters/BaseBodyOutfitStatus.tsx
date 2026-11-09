/**
 * BaseBodyOutfitStatus — under the Pose tab's pose tiles: how the CURRENT
 * outfit's model on the base-body pipeline stands (`base_info.outfit`).
 * Renders nothing off the pipeline.
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
 * reports `stale` (or was built before the character joined the pipeline), and "Rebuild outfit model" starts the regular generation
 * of the current outfit (POST /characters/{n}/model3d/generate?force=1 — the
 * route FieldModel3D uses; on the pipeline it builds via the base body).
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { modelRunning, useBaseBody } from './useBaseBody'

/** A share (0..1) from the proof's `texels` block, or null when absent. */
function texelShare(proof: Record<string, unknown> | null, key: string): number | null {
  const texels = proof?.texels
  if (!texels || typeof texels !== 'object') return null
  const v = (texels as Record<string, unknown>)[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

const pct = (v: number) => `${(v * 100).toFixed(1)} %`

export function BaseBodyOutfitStatus({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, startPoll } = useBaseBody(character)
  const [posting, setPosting] = useState(false)

  const rebuild = useCallback(async () => {
    if (posting) return
    setPosting(true)
    try {
      const d = await apiPost<{ status?: string }>(`/characters/${enc}/model3d/generate?force=1`, {})
      if (d?.status === 'already_running') {
        toast(t('A 3D model generation is already running for this character'))
      } else {
        toast(t('Generating…'))
      }
      startPoll(500)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }, [enc, posting, startPoll, t, toast])

  const outfit = info?.outfit
  if (!info?.pipeline || !outfit) return null

  const coverage = texelShare(outfit.proof, 'garment_share_of_exposed')
  const filled = texelShare(outfit.proof, 'unseen_filled_share_of_exposed_garment')
  const statusText = outfit.status === 'running' ? t('Generating…')
    : outfit.status === 'failed' ? t('Failed')
    : outfit.status === 'stale'
      ? (outfit.stale_reason === 'before_pipeline'
        ? t('Built before the base body pipeline — rebuild it')
        : outfit.stale_reason === 'detail_changed'
          ? t('Built for another body detail under the clothing — rebuild it')
          : outfit.stale_reason === 'mesh_item_ready'
            ? t('An own-mesh piece painted on here has its garment mesh now — rebuild it')
            : t('Built on an older base body — rebuild it'))
    : outfit.status === 'missing' ? t('Not built yet')
    : t('Ready')

  return (
    <div className="ga-form" style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>{t('Outfit model (base body)')}: <span className="ga-hint">{statusText}</span></span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={posting || modelRunning(info) || !info.model}
          title={!info.model ? t('Generate the base model first') : undefined}
          onClick={rebuild}
        >
          {t('Rebuild outfit model')}
        </button>
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
