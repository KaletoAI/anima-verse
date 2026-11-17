/**
 * MeshShapeControl — Ruling A48d: what the piece's mesh is in the Mesh step. Since A168 "Shell from the body" is its
 * own mode on the item (Wardrobe → Mode), so the shape is only SHOWN here: the shape the mode makes, a fit made as the
 * other shape (due — refits on the CPU, 0 hub jobs) and the shell's numbers. For a shell-mode piece the box keeps the
 * shell's offset from the skin (A166) — it SAVES on its own (POST …/garments/{item}/fit-settings `{shell_offset}`)
 * and runs nothing; only this piece's fit becomes due.
 */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MESH_SHAPE_LABELS, SHELL_OFFSET_HINT, shellOffsetLabel } from './fitSettingsModel'
import type { FitSettingsInfo } from './fitSettingsModel'

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
  const [savingOffset, setSavingOffset] = useState<number | null>(null)
  const shape = info.mesh_shape
  if (!shape) return null

  /** A166: the shell's offset saves on its own (POST …/fit-settings `{shell_offset}`). */
  const saveOffset = async (mm: number) => {
    setSavingOffset(mm)
    try {
      const d = await apiPost<{ fit_settings: FitSettingsInfo }>(
        `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}/fit-settings`,
        { shell_offset: mm })
      toast(`${t('Saved')} · ${d.fit_settings.mesh_shape?.due || d.fit_settings.due
        ? t('Fit due — refits on the CPU, 0 hub jobs') : t('nothing becomes due')}`, 'success')
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSavingOffset(null)
      onSaved()
    }
  }
  const offset = shape.offset

  const pct = (v: number | null | undefined) => (v != null ? `${(v * 100).toFixed(1)} %` : '–')
  return (
    <div style={BOX} role="group" aria-label={t('Mesh shape')} data-mesh-shape-resolved={shape.resolved}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong>{t('Mesh shape')}</strong>
        <span>{t(MESH_SHAPE_LABELS[shape.resolved])}</span>
        <span className="ga-hint">{t('set by the mode in the Wardrobe')}</span>
      </div>
      {shape.resolved === 'shell' && offset ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }} title={t(SHELL_OFFSET_HINT)}>
          <label htmlFor={`shell-offset-${itemId}`}>{t('Shell offset from the skin')}</label>
          <select id={`shell-offset-${itemId}`} className="ga-input" style={{ padding: '1px 4px' }}
            value={String(savingOffset ?? offset.setting)} disabled={busy || savingOffset !== null}
            onChange={(e) => { void saveOffset(Number(e.target.value)) }}>
            {offset.choices.map((mm) => (
              <option key={mm} value={String(mm)}>{shellOffsetLabel(mm, offset.default, t)}</option>
            ))}
          </select>
          <span className="ga-hint">
            {offset.made != null && offset.made !== offset.setting
              ? t('the shown shell was made at {mm} mm').replace('{mm}', String(offset.made))
              : t('CPU, 0 hub jobs')}
          </span>
        </div>
      ) : null}
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
