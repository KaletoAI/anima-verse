/**
 * GalleryAccess — welche anderen Charaktere die Galerie dieses Characters im
 * Player-UI durchsehen dürfen. Liste von Checkboxen; gespeichert im Config-Feld
 * `gallery_allowed_viewers`. Wird oben im Gallerie-Tab gezeigt.
 *
 * Quelle: GET /characters/{name}/config (gallery_allowed_viewers) + Character-
 * Roster. Speichern: POST /characters/{name}/config.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { loadCharacters } from '../../lib/refs'

export function GalleryAccess({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [viewers, setViewers] = useState<string[]>([])
  const [roster, setRoster] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (!character) return
    ;(async () => {
      try {
        const [cfgResp, rosterData] = await Promise.all([
          apiGet<{ config?: Record<string, unknown> }>(`/characters/${encodeURIComponent(character)}/config`),
          loadCharacters(),
        ])
        if (cancelled) return
        const gv = (cfgResp.config || {}).gallery_allowed_viewers
        setViewers(Array.isArray(gv) ? gv.map((x) => String(x)).filter(Boolean) : [])
        setRoster(rosterData.map((c) => c.name).filter((n) => n && n !== character))
      } catch {
        /* ignore — leere Liste */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [character])

  const setViewersAndSave = useCallback(
    async (next: string[]) => {
      setViewers(next)
      setSaving(true)
      try {
        await apiPost(`/characters/${encodeURIComponent(character)}/config`, {
          fields: { gallery_allowed_viewers: next },
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSaving(false)
      }
    },
    [character, t, toast],
  )

  return (
    <div className="ga-fieldset">
      <div className="ga-fieldset-title">{t('Gallery access')}</div>
      <p className="ga-sched-muted" style={{ margin: '0 0 8px' }}>
        {t('Other characters allowed to browse this character’s gallery in the player UI. None checked = only the character itself.')}
      </p>
      <div className="ga-gallery-access">
        {roster.length === 0 ? (
          <span className="ga-sched-muted">{t('No other characters.')}</span>
        ) : (
          roster.map((name) => {
            const on = viewers.includes(name)
            return (
              <label key={name} className="ga-check-row">
                <input
                  type="checkbox"
                  checked={on}
                  disabled={saving}
                  onChange={() =>
                    setViewersAndSave(on ? viewers.filter((x) => x !== name) : [...viewers, name])
                  }
                />
                <span>{name}</span>
              </label>
            )
          })
        )}
        {/* Gespeicherte Namen, die nicht (mehr) im Roster sind — sichtbar lassen,
            damit man sie abwählen kann statt sie still zu verlieren. */}
        {viewers
          .filter((v) => !roster.includes(v))
          .map((v) => (
            <label key={v} className="ga-check-row">
              <input
                type="checkbox"
                checked
                disabled={saving}
                onChange={() => setViewersAndSave(viewers.filter((x) => x !== v))}
              />
              <span>
                {v} <span className="ga-sched-muted">({t('not in roster')})</span>
              </span>
            </label>
          ))}
      </div>
    </div>
  )
}
