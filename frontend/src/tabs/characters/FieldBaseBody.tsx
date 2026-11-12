/**
 * FieldBaseBody — the Base body tab (template tab `base_body_tab`, before
 * Pose; spec
 * docs/superpowers/specs/2026-11-08-base-body-outfits-design.md): the
 * per-character switch onto the base-body pipeline, then the plain body's
 * views and rigged model (FigureBodyDetails — moved into the Figure tab's
 * Body details by plan 2026-11-12-unified-worn-pieces Task 10; this tab goes
 * with Task 11).
 *
 * Backend: GET /characters/{n}/base-body (useBaseBody), POST
 * .../base-body/pipeline {enabled} (400 for a non-humanoid).
 *
 * The section is humanoid-only in the template (`visible_when`); should a
 * non-humanoid still reach it, it shows only a hint.
 */
import { useCallback, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useBaseBody } from './useBaseBody'
import { FigureBodyDetails } from './FigureBodyDetails'

export function FieldBaseBody({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, setInfo, startPoll } = useBaseBody(character)
  const [posting, setPosting] = useState(false)
  // Bumped by a pipeline switch: the details remount and read the new state.
  const [version, setVersion] = useState(0)

  const setPipeline = useCallback(
    async (enabled: boolean) => {
      if (posting) return
      setPosting(true)
      try {
        const d = await apiPost<{ pipeline: boolean }>(
          `/characters/${enc}/base-body/pipeline`, { enabled })
        setInfo((prev) => (prev ? { ...prev, pipeline: d.pipeline } : prev))
        startPoll()
        setVersion((v) => v + 1)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setPosting(false)
      }
    },
    [enc, posting, setInfo, startPoll, t, toast],
  )

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) {
    return <div className="ga-hint">{t('The base body is for humanoid characters only.')}</div>
  }
  const hint = t('A bald, neutral A-pose base body built from the profile picture. Outfits are rendered as edits of its views and painted onto its rigged model.')
  return (
    <div className="ga-form">
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }} title={hint}>
        <input type="checkbox" checked={info.pipeline} disabled={posting}
          onChange={(e) => setPipeline(e.target.checked)} />
        <span>{t('Use base body pipeline')}</span>
      </label>
      {info.pipeline ? <FigureBodyDetails key={version} character={character} />
        : <div className="ga-hint">{hint}</div>}
    </div>
  )
}
