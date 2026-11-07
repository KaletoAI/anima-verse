/**
 * PairActions — the two-person picker for a menu with SEVERAL possible
 * partners (the chat window: everyone the avatar can address). One
 * "🤝 <name> ▸ n" chip per person opens that person's row of pose chips;
 * the chips, the options feed and the proposing are the shared pieces of
 * `pairActions.tsx` that the Others card renders inline, so both places
 * always offer the same actions.
 */
import { useState } from 'react'
import { HoverHint } from './HoverHint'
import { useI18n } from './I18nProvider'
import { pairActionChips, usePairPropose, type PairOptions, type PairTarget } from './pairActions'

export function PairActions({ targets, options, onChanged, onNote }: {
  targets: PairTarget[]
  options: PairOptions
  /** After a proposal (refresh the host's data). */
  onChanged: () => void | Promise<void>
  /** The engine's refusal, "" when a new proposal starts. */
  onNote: (message: string) => void
}) {
  const { t } = useI18n()
  const actions = usePairPropose(onChanged, onNote)
  const [open, setOpen] = useState('')
  if (!options.poses.length) return null
  const shown = targets.find((target) => target.name === open)
  return <>
    {targets.map((target) => (
      <HoverHint key={`pair:${target.name}`} text={t('Together with {name}').replace('{name}', target.name)}>
        <button type="button" className={`player-chip${shown === target ? ' on' : ''}`}
          aria-expanded={shown === target}
          onClick={() => setOpen(shown === target ? '' : target.name)}>
          🤝 {target.name} ▸ {options.poses.length}
        </button>
      </HoverHint>
    ))}
    {/* `order: 1` + full width: the open row drops below every chip of the
        surrounding chip line instead of splitting it. */}
    {shown && <div className="player-prop-offers-row"
      style={{ order: 1, flex: '1 1 100%', display: 'flex', flexWrap: 'wrap', gap: 5, alignItems: 'center' }}>
      <span style={{ opacity: 0.7 }}>🤝 {shown.name}:</span>
      {pairActionChips({ target: shown, options, actions, t })}
      <button type="button" className="player-chip" aria-label={t('Close')} onClick={() => setOpen('')}>✕</button>
    </div>}
  </>
}
