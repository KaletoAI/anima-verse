import { useI18n } from '../../i18n/I18nProvider'
import { Field } from '../../components/Field'
import { EVENT_CATEGORIES, type EventSettings } from './worldTypes'

// ── Per-location random-events overrides ──────────────────────────────────
// Mirrors the global "Random events" config block but lets a location set
// its own probability / cooldown / categories. Hint text matches the global
// admin's "Pro Location ueberschreibbar" promise — without this section the
// override claim was dead since the React migration.
interface RandomEventsEditorProps {
  value: EventSettings | undefined
  onChange: (next: EventSettings) => void
}

export function RandomEventsEditor({ value, onChange }: RandomEventsEditorProps) {
  const { t } = useI18n()
  const settings: EventSettings = value || {}
  const probabilityPct = Math.round(((settings.event_probability ?? 0.1) as number) * 100)
  const allowed = settings.allowed_categories || [...EVENT_CATEGORIES]
  const blacklistText = (settings.event_blacklist || []).join(', ')

  const update = (patch: Partial<EventSettings>) => {
    onChange({ ...settings, ...patch })
  }

  return (
    <div className="ga-form">
      <div className="ga-form-row">
        <Field
          label={t('Probability %')}
          hint={t('Per hour. Overrides the global default.')}
        >
          <input
            type="number"
            className="ga-input"
            min={0}
            max={50}
            step={1}
            value={probabilityPct}
            onChange={(e) =>
              update({ event_probability: (parseInt(e.target.value, 10) || 0) / 100 })
            }
          />
        </Field>
        <Field label={t('Max')}>
          <input
            type="number"
            className="ga-input"
            min={1}
            max={10}
            value={settings.max_concurrent_events ?? 1}
            onChange={(e) =>
              update({ max_concurrent_events: parseInt(e.target.value, 10) || 1 })
            }
          />
        </Field>
        <Field label={t('Cooldown h')}>
          <input
            type="number"
            className="ga-input"
            min={0}
            max={48}
            value={settings.event_cooldown_hours ?? 2}
            onChange={(e) =>
              update({ event_cooldown_hours: parseInt(e.target.value, 10) || 0 })
            }
          />
        </Field>
      </div>
      <Field label={t('Allowed categories')}>
        <div className="ga-form-row" style={{ gap: 10, flexWrap: 'wrap' }}>
          {EVENT_CATEGORIES.map((cat) => {
            const checked = allowed.includes(cat)
            return (
              <label key={cat} className="ga-form-check">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...allowed.filter((c) => c !== cat), cat]
                      : allowed.filter((c) => c !== cat)
                    update({ allowed_categories: next })
                  }}
                />
                {cat}
              </label>
            )
          })}
        </div>
      </Field>
      <Field label={t('Blacklist')} hint={t('Comma-separated event names that must never fire here.')}>
        <input
          className="ga-input"
          value={blacklistText}
          placeholder="z.B. Feuer, Erdbeben"
          onChange={(e) =>
            update({
              event_blacklist: e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      </Field>
    </div>
  )
}
