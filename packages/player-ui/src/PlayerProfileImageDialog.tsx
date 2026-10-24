/** Profile portrait generation for player character forms, using automatic routing. */
import { useState } from 'react'
import { useI18n } from './I18nProvider'
import type { FieldImageDialogControl } from './character/CharacterFormHost'
import { profileImagePayload } from './playerDialogPayloads'
import { PlayerDialogFrame } from './PlayerDialogFrame'

export function PlayerProfileImageDialog({ ctl }: { ctl: FieldImageDialogControl }) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(ctl.prompt)
  const [useSource, setUseSource] = useState(false)
  const [negative, setNegative] = useState('')
  const payload = profileImagePayload({ prompt, useSource, negative })
  return <PlayerDialogFrame title={t('Generate profile image')} action={t('Generate')} disabled={!payload}
    onClose={ctl.onClose} onSubmit={() => { if (payload) return ctl.onSubmit(payload) }}>
    <label className="ga-field">
      <span className="ga-field-caption">{t('Prompt')}</span>
      <textarea className="ga-input" rows={5} autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} />
    </label>
    {!payload && <div className="player-photo-hint">{t('Enter a prompt.')}</div>}
    {ctl.sourceImageUrl && <label className="player-photo-check">
      <input type="checkbox" checked={useSource} onChange={(e) => setUseSource(e.target.checked)} />
      <span>{t('Use current portrait as reference')}</span>
    </label>}
    <label className="ga-field">
      <span className="ga-field-caption">{t('Negative prompt')}</span>
      <input className="ga-input" value={negative} onChange={(e) => setNegative(e.target.value)} />
    </label>
  </PlayerDialogFrame>
}
