/**
 * AvatarSettingsPanel — the user's own avatar in /play: edit appearance, soul
 * and preferences. Uses the same template-driven column renderer as the
 * Game-Admin (`TemplateTab`) — same layout, filtered down to the columns and
 * fields a user may touch.
 *
 * Sub-tabs:
 *  - Appearance  = template columns 1,6 (identity + face incl. profile picture)
 *  - Physique    = template columns 4,5 (physical values + appearance prompt incl. image)
 *  - Soul        = SoulEditor (respects locked sections)
 *  - Preferences = columns 2,10 without the social numbers → dressing preference + TTS,
 *                  plus the ACCOUNT language section (see LanguageSettings below)
 *
 * Social numbers, feature flags, stats and placement stay admin-only
 * (not in these columns / via excludeKeys). The user's own avatar is in
 * `allowed_characters`, so /characters/{avatar}/* is allowed.
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { TemplateTab } from '../tabs/characters/TemplateTab'
import { BodyEditor } from '../tabs/characters/BodyEditor'
import { type DynamicData } from '../tabs/characters/TemplateField'
import { type TmplSection } from '../tabs/characters/TemplateSectionForm'
import { SoulEditor } from '../tabs/characters/SoulEditor'

interface TmplSectionRaw extends TmplSection {
  special?: unknown
  column?: number
  row?: number
}

// The social numbers stay admin-only (even where they sit in an allowed column).
const HIDE_KEYS = ['popularity', 'trustworthiness', 'social_dialog_probability', 'roles', 'romantic_interests']
const AUSSEHEN_COLS = [1, 6] // identity + face (+ profile picture)
const KOERPER_COLS = [4, 5] // body editor (species slots) + appearance prompt
const PREF_COLS = [2, 10] // traits (→ dressing preference only) + TTS

type Sub = 'look' | 'body' | 'soul' | 'prefs'

interface LanguagePayload {
  system_language: string
  translation_mode: string
  languages: Array<{ value: string; label: string }>
  translation_modes: string[]
}

// How the two translation modes read in the UI. The server owns the VALUES
// (app/models/account.TRANSLATION_MODES); only the wording lives here.
const MODE_LABELS: Record<string, string> = {
  native: 'Characters answer in this language',
  translate: 'Characters keep their own language',
}

/**
 * Account language — NOT a character setting.
 *
 * The account profile is stored once per world (table `account`, id=1), so
 * this pair is shared by everyone playing that world; the rest of this panel
 * edits the avatar's own character profile. That is why it does not come from
 * the character template but from GET/POST /account/language, and why it sits
 * in its own section.
 */
function LanguageSettings() {
  const { t } = useI18n()
  const [data, setData] = useState<LanguagePayload | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    apiGet<LanguagePayload>('/account/language')
      .then((d) => {
        if (alive) setData(d)
      })
      .catch(() => {
        if (alive) setError('Could not load the language settings')
      })
    return () => {
      alive = false
    }
  }, [])

  if (!data) {
    return (
      <div className="ga-section">
        <h4>{t('Language')}</h4>
        <div className="ga-field-hint">{error ? t(error) : t('Loading…')}</div>
      </div>
    )
  }

  const save = async (patch: Partial<Pick<LanguagePayload, 'system_language' | 'translation_mode'>>) => {
    const next = { ...data, ...patch }
    setData(next)
    setSaving(true)
    setError('')
    try {
      await apiPost('/account/language', {
        system_language: next.system_language,
        translation_mode: next.translation_mode,
      })
    } catch {
      setError('Could not save the language settings')
      setData(data)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="ga-section" style={{ marginTop: 12 }}>
      <h4>{t('Language')}</h4>
      <div className="ga-field-hint">
        {t('Applies to the whole world, not just this character.')}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8, maxWidth: 420 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span>{t('Account language')}</span>
          <select
            className="ga-input"
            value={data.system_language}
            disabled={saving}
            onChange={(e) => void save({ system_language: e.target.value })}
          >
            {data.languages.map((l) => (
              <option key={l.value} value={l.value}>
                {t(l.label)}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span>{t('Translation mode')}</span>
          <select
            className="ga-input"
            value={data.translation_mode}
            disabled={saving}
            onChange={(e) => void save({ translation_mode: e.target.value })}
          >
            {data.translation_modes.map((m) => (
              <option key={m} value={m}>
                {t(MODE_LABELS[m] || m)}
              </option>
            ))}
          </select>
        </label>
        {error ? <div className="ga-field-hint ga-field-warn">{t(error)}</div> : null}
      </div>
    </div>
  )
}

export function AvatarSettingsPanel({ avatar }: { avatar: string }) {
  const { t, lang } = useI18n()
  const [sections, setSections] = useState<TmplSectionRaw[]>([])
  const [loaded, setLoaded] = useState(false)
  const [sub, setSub] = useState<Sub>('look')
  const [seasons, setSeasons] = useState<Array<{ value: string; label: string; days: number }>>([])

  useEffect(() => {
    let alive = true
    ;(async () => {
      if (!avatar) {
        setLoaded(true)
        return
      }
      try {
        const pr = await apiGet<{ profile?: Record<string, unknown> }>(
          `/characters/${encodeURIComponent(avatar)}/profile`,
        )
        const tmplId = String(pr.profile?.template || '')
        if (tmplId) {
          const tmpl = await apiGet<{ sections?: TmplSectionRaw[] }>(`/templates/${encodeURIComponent(tmplId)}`)
          if (alive) setSections(tmpl.sections || [])
        }
      } catch {
        /* api handles auth redirect */
      } finally {
        if (alive) setLoaded(true)
      }
    })()
    return () => {
      alive = false
    }
  }, [avatar])

  // Seasons of the world calendar, names localized for the UI language — the
  // option source of every `season_day` field.
  useEffect(() => {
    let alive = true
    apiGet<{ calendar?: { seasons?: Array<{ key: string; name: string; days: number }> } }>(
      `/world/game-time?lang=${encodeURIComponent(lang)}`,
    )
      .then((d) => {
        if (!alive) return
        setSeasons(
          (d.calendar?.seasons || []).map((s) => ({
            value: s.key,
            label: s.name || s.key,
            days: s.days,
          })),
        )
      })
      .catch(() => {
        if (alive) setSeasons([])
      })
    return () => {
      alive = false
    }
  }, [lang])

  // The appearance selects use no dynamic sources; TTS voices/speakers cannot be
  // loaded in /play → the current value stays, the choice is limited.
  // The world calendar is the exception: `season_day` fields (the identity
  // column carries one) are an empty dropdown without it, so the same list the
  // game clock ships is loaded here too.
  const dynamicData: DynamicData = useMemo(
    () => ({ tts_voices: [], tts_speakers: [], characters: [], seasons }),
    [seasons],
  )

  if (!avatar) return <div className="ga-placeholder">{t('No active avatar')}</div>
  if (!loaded) return <div className="ga-loading">{t('Loading…')}</div>

  const tabs: Array<{ id: Sub; label: string }> = [
    { id: 'look', label: 'Appearance' },
    { id: 'body', label: 'Physique' },
    { id: 'soul', label: 'Soul' },
    { id: 'prefs', label: 'Preferences' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <nav className="ga-subtabs" style={{ flex: '0 0 auto' }}>
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={`ga-btn ga-btn-sm${sub === tb.id ? ' ga-btn-primary' : ''}`}
            onClick={() => setSub(tb.id)}
          >
            {t(tb.label)}
          </button>
        ))}
      </nav>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', paddingTop: 8 }}>
        {sub === 'look' && (
          <div className="avatar-aussehen-tab">
            <TemplateTab
              character={avatar}
              tab={{ id: 'look', columns: AUSSEHEN_COLS }}
              sections={sections}
              dynamicData={dynamicData}
            />
          </div>
        )}
        {sub === 'body' && (
          <div className="avatar-body-tab">
            <TemplateTab
              character={avatar}
              tab={{ id: 'body', columns: KOERPER_COLS }}
              sections={sections}
              dynamicData={dynamicData}
              specialSlots={{ body_editor: <BodyEditor character={avatar} /> }}
            />
          </div>
        )}
        {sub === 'prefs' && (
          <>
            <TemplateTab
              character={avatar}
              tab={{ id: 'prefs', columns: PREF_COLS }}
              sections={sections}
              dynamicData={dynamicData}
              excludeKeys={HIDE_KEYS}
            />
            <LanguageSettings />
          </>
        )}
        {sub === 'soul' && <SoulEditor character={avatar} />}
      </div>
    </div>
  )
}
