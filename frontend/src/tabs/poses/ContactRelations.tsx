/**
 * Ruling A139: the CONTACT RELATIONS of a pair/group clip in the Alignment panel — which place's attached part aims at
 * which target (channel, a hand, the head front point) of which other place. The list is a draft the place preview
 * reads live (Auto-align, the fine fit, the role check); "Save contacts" stores it in the clip's `<kind>.json`
 * (PATCH `contact_target`), "Use inherited" drops the clip's own list so the package default (or the automatic
 * channel detection) applies again. Saving runs nothing.
 */
import { CONTACT_TARGETS, PROVISIONAL_TARGETS, type ContactRelation, type ContactTarget } from '@anima/scene-render'
import { useI18n } from '../../i18n/I18nProvider'
import { targetWordOf } from './contactWords'

export interface ContactSetting { relations: ContactRelation[]; source: 'clip' | 'package' | 'default' }

export function ContactRelations({ roles, saved, draft, onDraft, onSave, busy }: {
  /** the clip's place roles, e.g. ['a', 'b', 'c', 'd'] */
  roles: readonly string[]
  saved: ContactSetting | null | undefined
  draft: ContactRelation[]
  onDraft: (next: ContactRelation[]) => void
  /** null = drop the clip's own list (inherit) */
  onSave: (next: ContactRelation[] | null) => void
  busy: boolean
}) {
  const { t } = useI18n()
  const savedRels = saved?.relations ?? []
  const dirty = JSON.stringify(draft) !== JSON.stringify(savedRels)
  const sourceText = saved?.source === 'clip' ? t('set for this clip')
    : saved?.source === 'package' ? t('package default') : t('automatic (the channel the part fits, B moves)')
  const set = (i: number, patch: Partial<ContactRelation>) => onDraft(draft.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  const free = roles.filter((r) => !draft.some((x) => x.part === r))
  const sel = { className: 'ga-input', style: { fontSize: 12, padding: '0 2px' } }
  return (
    <div data-testid="contact-relations" style={{ fontSize: 12, display: 'grid', gap: 3 }}>
      <div title={t('Which place’s attached part aims at which target of which other place. Auto-align, the fine fit and the follow solve every row; the place preview checks that each person has what the row needs.')}>
        <strong>{t('Contacts')}</strong> <span style={{ opacity: 0.7 }}>· {sourceText}</span>
      </div>
      {draft.length === 0 ? <div className="ga-form-hint" style={{ margin: 0 }}>{t('No rows: the channel the attached part fits is found automatically.')}</div> : null}
      {draft.map((r, i) => (
        <div key={i} style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          <select {...sel} aria-label={t('Place with the attached part')} value={r.part} disabled={busy}
            onChange={(e) => set(i, { part: e.target.value })}>
            {roles.map((x) => <option key={x} value={x} disabled={x !== r.part && draft.some((y) => y.part === x)}>{x.toUpperCase()}</option>)}
          </select>
          <span>{t('tip →')}</span>
          <select {...sel} aria-label={t('Anchor place')} value={r.at} disabled={busy} onChange={(e) => set(i, { at: e.target.value })}>
            {roles.filter((x) => x !== r.part).map((x) => <option key={x} value={x}>{x.toUpperCase()}</option>)}
          </select>
          <select {...sel} data-testid={`contact-target-${i}`} aria-label={t('Contact target')} value={r.target} disabled={busy}
            onChange={(e) => set(i, { target: e.target.value as ContactTarget })}>
            {CONTACT_TARGETS.map((x) => <option key={x} value={x}>{targetWordOf(t, x)}{PROVISIONAL_TARGETS.includes(x) ? ` (${t('provisional')})` : ''}</option>)}
          </select>
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} title={t('Remove this contact')}
            onClick={() => onDraft(draft.filter((_, k) => k !== i))}>×</button>
        </div>
      ))}
      {draft.some((r) => PROVISIONAL_TARGETS.includes(r.target)) ? (
        <div className="ga-form-hint" style={{ margin: 0 }}>
          {t('Head front point is provisional: a point in front of the head at mouth height, from the head bone and the face direction. A mouth opening (region, opening, widening like a channel) is not built yet.')}
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !free.length || roles.length < 2}
          onClick={() => { const part = free.includes('b') ? 'b' : free[0]; onDraft([...draft, { part, at: roles.find((x) => x !== part) ?? 'a', target: 'channel' }]) }}>
          {t('Add contact')}</button>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" data-testid="contact-save" disabled={busy || !dirty || !draft.length}
          title={t('Stores the contacts with the clip (all its sets and halves). Runs nothing; Auto-align uses them at once.')}
          onClick={() => onSave(draft)}>{t('Save contacts')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || saved?.source !== 'clip'}
          title={t('Drops this clip’s own contacts: the package default, or the automatic channel detection, applies again.')}
          onClick={() => onSave(null)}>{t('Use inherited')}</button>
        {dirty ? <span style={{ color: 'var(--warning, #d29922)' }}>{t('unsaved — the preview already uses it')}</span> : null}
      </div>
    </div>
  )
}
