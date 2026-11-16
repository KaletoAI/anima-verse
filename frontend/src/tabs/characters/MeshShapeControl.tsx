/**
 * MeshShapeControl — Ruling A48d: the piece's mesh shape in the Mesh step: "Auto | As generated | Shell from the
 * body", what Auto resolves to and why, and what a change costs BEFORE the click (local on the CPU, 0 hub jobs; only
 * this piece's fit becomes due, and only when the shape it makes changes). A choice SAVES on its own (POST
 * …/garments/{item}/fit-settings `{mesh_shape}`) and runs nothing; the next run / Build makes the fit.
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MESH_SHAPE_CHOICES, MESH_SHAPE_HINTS, MESH_SHAPE_LABELS, meshShapeReason } from './fitSettingsModel'
import type { FitSettingsInfo, MeshShapeChoice } from './fitSettingsModel'

const BOX: CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 3, padding: '4px 8px', flexBasis: '100%',
  border: '1px solid var(--border, #30363d)', borderRadius: 6, fontSize: '0.85em', minWidth: 0,
}

export function MeshShapeControl({ character, itemId, info, busy, onSaved }: {
  character: string
  itemId: string
  info: FitSettingsInfo
  busy: boolean
  /** After a save: poll the dialog again. */
  onSaved: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [saving, setSaving] = useState<MeshShapeChoice | null>(null)
  const shape = info.mesh_shape
  if (!shape) return null
  const value = saving ?? shape.setting
  const resolvedOf = (c: MeshShapeChoice) => (c === 'auto' ? shape.auto.shape : c)
  // What a click on `c` would make due: the fit only when the shape it makes changes (and a fit exists).
  const costOf = (c: MeshShapeChoice) => (resolvedOf(c) === (shape.made ?? shape.resolved)
    ? t('nothing becomes due') : t('only this piece\'s fit becomes due — on the CPU, 0 hub jobs'))
  const reason = meshShapeReason(shape, t)
  const autoLine = `${t('Auto')} → ${t(MESH_SHAPE_LABELS[shape.auto.shape])}: ${reason}`

  const save = async (c: MeshShapeChoice) => {
    if (c === shape.setting) return
    setSaving(c)
    try {
      const d = await apiPost<{ fit_settings: FitSettingsInfo }>(
        `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/fit-settings`,
        { mesh_shape: c })
      toast(`${t('Saved')} · ${d.fit_settings.mesh_shape?.due || d.fit_settings.due
        ? t('Fit due — refits on the CPU, 0 hub jobs') : t('nothing becomes due')}`, 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(null)
      onSaved()
    }
  }

  const pct = (v: number | null | undefined) => (v != null ? `${(v * 100).toFixed(1)} %` : '–')
  return (
    <div style={BOX} role="group" aria-label={t('Mesh shape')} data-mesh-shape={shape.setting}
      data-mesh-shape-resolved={shape.resolved}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong>{t('Mesh shape')}</strong>
        {MESH_SHAPE_CHOICES.map((c) => (
          <button key={c} type="button" className={`ga-btn ga-btn-sm${value === c ? ' ga-btn-primary' : ''}`}
            aria-pressed={value === c} disabled={busy || saving !== null}
            title={[t(MESH_SHAPE_HINTS[c]), c === 'auto' ? autoLine : '', `${t('Cost')}: ${costOf(c)}`]
              .filter(Boolean).join('\n')}
            aria-label={`${t('Mesh shape')}: ${t(MESH_SHAPE_LABELS[c])} · ${costOf(c)}`}
            onClick={() => { void save(c) }}>
            {t(MESH_SHAPE_LABELS[c])}
            {c === 'auto' ? ` (→ ${t(MESH_SHAPE_LABELS[shape.auto.shape])})` : ''}
          </button>
        ))}
      </div>
      <span className="ga-hint" data-mesh-shape-auto="" style={{ overflowWrap: 'anywhere' }}>{autoLine}</span>
      <span className="ga-hint" data-mesh-shape-cost="">
        {t('A change runs locally on the CPU, 0 hub jobs; only this piece\'s fit becomes due, nothing runs until the next run or Build')}
      </span>
      {shape.due ? (
        <span className="ga-hint" data-mesh-shape-due="" style={{ color: 'var(--warning, #d29922)' }}>
          {`${t('The fit was made as {shape}').replace('{shape}', t(MESH_SHAPE_LABELS[shape.made ?? 'as_generated']))} · ${t('Fit due — refits on the CPU, 0 hub jobs')}`}
        </span>
      ) : null}
      {shape.made === 'shell' && shape.shell ? (
        <span className="ga-hint" data-mesh-shape-shell="">
          {`${t('Shell from the body')}: ${shape.shell.shell_faces?.toLocaleString() ?? '–'} △ · ${t('Share inside the body')} ${pct(shape.shell.inside_share)} · ${t('sides coloured from the views within 2 cm')} ${pct(shape.shell.side_colour_within_2cm)}`}
        </span>
      ) : null}
    </div>
  )
}
