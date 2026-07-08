/**
 * AvatarSettingsPanel — der eigene Avatar im /play: Aussehen, Soul und
 * Präferenzen bearbeiten. Nutzt denselben template-getriebenen Spalten-Renderer
 * wie der Game-Admin (`TemplateTab`) — gleiche Aufteilung, gefiltert auf
 * user-taugliche Spalten/Felder.
 *
 * Sub-Tabs:
 *  - Aussehen   = Template-Spalten 1,6 (Identität + Gesicht inkl. Profilbild)
 *  - Körper     = Template-Spalten 4,5 (physische Werte + Aussehen-Prompt inkl. Bild)
 *  - Soul       = SoulEditor (Lock-Sektionen respektiert)
 *  - Präferenzen= Spalten 2,10 ohne Social-Zahlen → Dressing-Preference + TTS
 *
 * Social-Zahlen, Feature-Flags, Telegram, Stats, Placement bleiben Admin-only
 * (nicht in diesen Spalten / via excludeKeys). Der eigene Avatar liegt in
 * `allowed_characters`, daher sind /characters/{avatar}/* erlaubt.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'
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

// Social-Zahlen bleiben Admin-only (auch wenn sie in einer erlaubten Spalte liegen).
const HIDE_KEYS = ['popularity', 'trustworthiness', 'social_dialog_probability', 'roles', 'romantic_interests']
const AUSSEHEN_COLS = [1, 6] // Identität + Gesicht(+Profilbild)
const KOERPER_COLS = [4, 5] // Body editor (species slots) + Aussehen-Prompt
const PREF_COLS = [2, 10] // Eigenschaften (→ nur Dressing-Preference) + TTS

type Sub = 'look' | 'body' | 'soul' | 'prefs'

export function AvatarSettingsPanel({ avatar }: { avatar: string }) {
  const { t } = useI18n()
  const [sections, setSections] = useState<TmplSectionRaw[]>([])
  const [loaded, setLoaded] = useState(false)
  const [sub, setSub] = useState<Sub>('look')

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

  // Appearance-Selects nutzen keine dynamischen Quellen; TTS-Voices/Speaker sind
  // im /play nicht ladbar → aktueller Wert bleibt, Auswahl eingeschränkt.
  const dynamicData: DynamicData = { tts_voices: [], tts_speakers: [], characters: [] }

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
          <div className="avatar-aussehen-tab">
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
          <TemplateTab
            character={avatar}
            tab={{ id: 'prefs', columns: PREF_COLS }}
            sections={sections}
            dynamicData={dynamicData}
            excludeKeys={HIDE_KEYS}
          />
        )}
        {sub === 'soul' && <SoulEditor character={avatar} />}
      </div>
    </div>
  )
}
