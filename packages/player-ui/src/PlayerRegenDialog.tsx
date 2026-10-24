/** Player regeneration uses automatic routing, with no backend or LoRA overrides. */
import { useState } from 'react'
import { useI18n } from './I18nProvider'
import type { GalleryRegenControl } from './GalleryPanel'
import type { InstagramImageGenControl } from './InstagramPanel'
import { regenPayload } from './playerDialogPayloads'
import { PlayerDialogFrame } from './PlayerDialogFrame'

export function PlayerRegenDialog({ ctl }: { ctl: GalleryRegenControl | InstagramImageGenControl }) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(ctl.prompt)
  const [names, setNames] = useState(ctl.detected)
  const [useRoom, setUseRoom] = useState(true)
  const [useSource, setUseSource] = useState(true)
  const [negative, setNegative] = useState('')
  const available = Array.from(new Set([...ctl.available, ...ctl.detected]))
  const payload = regenPayload({ prompt, names, useRoom, useSource, negative })
  return <PlayerDialogFrame title={t('Regenerate image')} action={t('Generate')} disabled={!payload}
    onClose={ctl.onClose} onSubmit={() => { if (payload) return ctl.onSubmit(payload) }}>
    <label className="ga-field">
      <span className="ga-field-caption">{t('Prompt')}</span>
      <textarea className="ga-input" rows={5} autoFocus value={prompt} onChange={(e) => setPrompt(e.target.value)} />
    </label>
    {!prompt.trim() && <div className="player-photo-hint">{t('Enter a prompt.')}</div>}
    <div className="ga-field">
      <span className="ga-field-caption">{t('Who is in the picture')}</span>
      <div className="player-photo-chips">
        {available.map((name) => <button key={name} type="button" aria-pressed={names.includes(name)}
          className={`player-photo-chip${names.includes(name) ? ' on' : ''}`}
          onClick={() => setNames((prev) => prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name])}>{name}</button>)}
      </div>
      {!names.length && <div className="player-photo-hint">{t('Select at least one character.')}</div>}
    </div>
    <label className="player-photo-check">
      <input type="checkbox" checked={useRoom} onChange={(e) => setUseRoom(e.target.checked)} />
      <span>{t('Show the room around it')}</span>
    </label>
    <label className="player-photo-check">
      <input type="checkbox" checked={useSource} onChange={(e) => setUseSource(e.target.checked)} />
      <span>{t('Use source image as reference')}</span>
    </label>
    <label className="ga-field">
      <span className="ga-field-caption">{t('Negative prompt')}</span>
      <input className="ga-input" value={negative} onChange={(e) => setNegative(e.target.value)} />
    </label>
  </PlayerDialogFrame>
}
