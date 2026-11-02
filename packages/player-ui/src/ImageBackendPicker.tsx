/** Shared backend/LoRA controls for photo and regenerate dialogs. */
import { useI18n } from './I18nProvider'
import type { useImageBackendPicker } from './useImageBackendPicker'

export function ImageBackendPicker({ picker, busy = false }: {
  picker: ReturnType<typeof useImageBackendPicker>; busy?: boolean
}) {
  const { t } = useI18n()
  const { backend, setBackend, backends, backendList, mediaOff, loraOptions, loraSlots, setSlot } = picker
  return <>
    <label className="ga-field" style={{ marginBottom: 10 }}>
      <span className="ga-field-caption">{t('Backend')}</span>
      <select className="ga-input" value={backend} disabled={busy || !backends}
        onChange={(e) => setBackend(e.target.value)}>
        <option value="">
          {!backends ? t('Loading…')
            : backends.resolved ? `${t('Auto (routing)')} → ${backends.resolved}`
              : t('Auto (routing) — no backend available')}
        </option>
        {backendList.map((o) => (
          <option key={o.name} value={o.name}>{o.label || o.name}</option>
        ))}
      </select>
      {mediaOff && (
        <div className="player-photo-hint">
          {t('Media generation is disabled for this world (Admin → Settings → Media Generation)')}
        </div>
      )}
    </label>

    {loraOptions.length > 0 && (
      <div className="ga-field" style={{ marginBottom: 10 }}>
        <span className="ga-field-caption">{t('LoRAs')}</span>
        <div className="player-photo-loras">
          {loraSlots.map((slot, i) => (
            <div key={i} className="player-photo-lora-row">
              <select className="ga-input" value={slot.name} disabled={busy}
                onChange={(e) => setSlot(i, { name: e.target.value })}>
                <option value="">{t('None')}</option>
                {loraOptions.map((l) => (
                  <option key={l.name} value={l.name}>
                    {l.name}{l.missing ? ` ${t('(missing)')}` : ''}
                  </option>
                ))}
              </select>
              <input type="number" className="ga-input player-photo-lora-strength"
                min={-2} max={2} step={0.05} title={t('Strength')}
                disabled={busy || !slot.name} value={slot.strength}
                onChange={(e) => setSlot(i, { strength: parseFloat(e.target.value) || 0 })} />
            </div>
          ))}
        </div>
      </div>
    )}
  </>
}
