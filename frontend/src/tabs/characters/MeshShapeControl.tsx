/**
 * MeshShapeControl — Ruling A48d: what the piece's mesh is in the Mesh step. Since A168 "Shell from the body" is its
 * own mode on the item (Wardrobe → Mode), so the shape is only SHOWN here: the shape the mode makes, a fit made as the
 * other shape (due — refits on the CPU, 0 hub jobs) and the shell's numbers. For a shell-mode piece the box keeps the
 * shell's offset from the skin (A166) — it SAVES on its own (POST …/garments/{item}/fit-settings `{shell_offset}`)
 * and runs nothing; only this piece's fit becomes due. "Take from the body" and "Fill holes up to" (A184) live in the
 * Fit settings box (`FitSettings`).
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MESH_SHAPE_LABELS, SHELL_OFFSET_HINT, shellChoiceLabel } from './fitSettingsModel'
import type { FitSettingsInfo, ShellChoice } from './fitSettingsModel'

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
  const [saving, setSaving] = useState<{ key: string; value: number } | null>(null)
  const shape = info.mesh_shape
  if (!shape) return null

  /** A166: the shell's offset saves on its own (POST …/fit-settings `{shell_offset}`). */
  const save = async (key: string, value: number) => {
    setSaving({ key, value })
    try {
      const d = await apiPost<{ fit_settings: FitSettingsInfo }>(
        `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/fit-settings`,
        { [key]: value })
      toast(`${t('Saved')} · ${d.fit_settings.mesh_shape?.due || d.fit_settings.due
        ? t('Fit due — refits on the CPU, 0 hub jobs') : t('nothing becomes due')}`, 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(null)
      onSaved()
    }
  }
  const rows: { key: string; label: string; hint: string; unit: string; choice?: ShellChoice }[] = [
    { key: 'shell_offset', label: 'Shell offset from the skin', hint: SHELL_OFFSET_HINT, unit: 'mm', choice: shape.offset },
  ]

  const pct = (v: number | null | undefined) => (v != null ? `${(v * 100).toFixed(1)} %` : '–')
  return (
    <div style={BOX} role="group" aria-label={t('Mesh shape')} data-mesh-shape-resolved={shape.resolved}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong>{t('Mesh shape')}</strong>
        <span>{t(MESH_SHAPE_LABELS[shape.resolved])}</span>
        <span className="ga-hint">{t('set by the mode in the Wardrobe')}</span>
      </div>
      {shape.resolved === 'shell' ? rows.map(({ key, label, hint, unit, choice }) => choice ? (
        <div key={key} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }} title={t(hint)}
          data-shell-setting={key}>
          <label htmlFor={`${key}-${itemId}`}>{t(label)}</label>
          <select id={`${key}-${itemId}`} className="ga-input" style={{ padding: '1px 4px' }}
            value={String(saving?.key === key ? saving.value : choice.setting)} disabled={busy || saving !== null}
            onChange={(e) => { void save(key, Number(e.target.value)) }}>
            {choice.choices.map((v) => (
              <option key={v} value={String(v)}>{shellChoiceLabel(v, choice.default, unit, t)}</option>
            ))}
          </select>
          <span className="ga-hint">
            {choice.made != null && choice.made !== choice.setting
              ? t('the shown shell was made at {value}').replace('{value}', `${choice.made} ${unit}`)
              : t('CPU, 0 hub jobs')}
          </span>
        </div>
      ) : null) : null}
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
