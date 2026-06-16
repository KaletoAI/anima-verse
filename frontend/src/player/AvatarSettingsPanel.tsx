/**
 * AvatarSettingsPanel — der eigene Avatar im /play: Aussehen, Soul und Bild/TTS-
 * Präferenzen bearbeiten. Nutzt denselben generischen, template-getriebenen
 * Renderer wie der Game-Admin (`TemplateSectionForm`) — keine eigenen Feldlisten.
 *
 * Sichtbar sind nur user-taugliche Sektionen (Aussehen + TTS). Social-Zahlen,
 * Feature-Flags, Telegram, Stats bleiben Admin-only (siehe `HIDE_KEYS` +
 * Sektions-Allowlist). Der eigene Avatar liegt in `allowed_characters`, daher
 * sind /characters/{avatar}/profile|config|status-effects|soul erlaubt.
 *
 * Quelle Template-id:  GET /characters/{avatar}/profile  → profile.template
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { useToast } from '../lib/Toast'
import { TemplateSectionForm, type TmplSection } from '../tabs/characters/TemplateSectionForm'
import { tmplText, type DynamicData, type TmplFieldDef } from '../tabs/characters/TemplateField'
import { SoulEditor } from '../tabs/characters/SoulEditor'

// Aussehens-/Präferenz-Sektionen, die der User am eigenen Avatar ändern darf.
const APPEARANCE_IDS = new Set(['identity', 'appearance', 'characteristics', 'face', 'others'])
const TTS_IDS = new Set(['tts_config'])
// Social-Zahlen bleiben Admin-only (privacy/policy) — auch wenn sie in einer
// erlaubten Sektion (human `characteristics`) liegen.
const HIDE_KEYS = ['popularity', 'trustworthiness', 'social_dialog_probability', 'roles', 'romantic_interests']

interface TmplSectionRaw extends TmplSection {
  special?: unknown
  column?: number
  row?: number
}

// Hat die Sektion nach Soul-/Policy-Filter noch ein editierbares Feld?
function hasRenderableField(s: TmplSectionRaw, hide: Set<string>): boolean {
  if (s.special) return false
  return (s.fields || []).some(
    (f: TmplFieldDef) =>
      f.editor_visible !== false && !f.source_file && !f.readonly && !hide.has(f.key),
  )
}

export function AvatarSettingsPanel({ avatar }: { avatar: string }) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [template, setTemplate] = useState<{ sections?: TmplSectionRaw[] } | null>(null)
  const [decency, setDecency] = useState('')
  const [savingDecency, setSavingDecency] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    if (!avatar) return
    setLoaded(false)
    try {
      const pr = await apiGet<{ profile: Record<string, unknown> }>(
        `/characters/${encodeURIComponent(avatar)}/profile`,
      )
      setDecency(String(pr.profile?.decency_preference || ''))
      const tmplId = String(pr.profile?.template || '')
      if (tmplId) {
        const tmpl = await apiGet<{ sections?: TmplSectionRaw[] }>(`/templates/${encodeURIComponent(tmplId)}`)
        setTemplate(tmpl)
      }
    } catch {
      /* api handles auth redirect */
    } finally {
      setLoaded(true)
    }
  }, [avatar])

  useEffect(() => {
    load()
  }, [load])

  const saveDecency = useCallback(
    async (value: string) => {
      setSavingDecency(true)
      try {
        await apiPost(`/characters/${encodeURIComponent(avatar)}/profile`, {
          fields: { decency_preference: value },
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSavingDecency(false)
      }
    },
    [avatar, t, toast],
  )

  if (!avatar) return <div className="ga-placeholder">{t('No active avatar')}</div>
  if (!loaded) return <div className="ga-loading">{t('Loading…')}</div>

  const hide = new Set(HIDE_KEYS)
  const secs = (template?.sections || [])
    .slice()
    .sort((a, b) => (a.column || 1) - (b.column || 1) || (a.row ?? 1) - (b.row ?? 1))
  const appearanceSecs = secs.filter((s) => APPEARANCE_IDS.has(s.id) && hasRenderableField(s, hide))
  const ttsSecs = secs.filter((s) => TTS_IDS.has(s.id) && hasRenderableField(s, new Set()))

  // Appearance-Selects nutzen keine dynamischen Quellen; TTS-Voices/Speaker sind
  // im /play nicht ladbar → aktueller Wert bleibt erhalten, Auswahl eingeschränkt.
  const dynamicData: DynamicData = { tts_voices: [], tts_speakers: [], characters: [] }

  const sectionBlock = (s: TmplSectionRaw, hideKeys?: string[]) => (
    <section key={s.id} style={{ marginBottom: 14 }}>
      <div className="ga-fieldset-title" style={{ marginBottom: 8 }}>
        {tmplText(s, 'label', lang) || s.id}
      </div>
      <TemplateSectionForm character={avatar} section={s} dynamicData={dynamicData} excludeKeys={hideKeys} />
    </section>
  )

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: 4 }}>
      <div className="ga-form-section-label">{t('Appearance')}</div>
      {appearanceSecs.length === 0 ? (
        <div className="ga-placeholder">{t('No appearance fields.')}</div>
      ) : (
        appearanceSecs.map((s) => sectionBlock(s, HIDE_KEYS))
      )}

      <div className="ga-form-section-label" style={{ marginTop: 10 }}>
        {t('Soul')}
      </div>
      <section style={{ marginBottom: 14 }}>
        <SoulEditor character={avatar} />
      </section>

      <div className="ga-form-section-label" style={{ marginTop: 10 }}>
        {t('Preferences')}
      </div>
      <section style={{ marginBottom: 14 }}>
        <div className="ga-field">
          <label className="ga-field-caption">{t('Dressing preference')}</label>
          <div className="ga-field-control">
            <textarea
              className="ga-input"
              rows={2}
              value={decency}
              disabled={savingDecency}
              onChange={(e) => setDecency(e.target.value)}
              onBlur={(e) => saveDecency(e.target.value)}
            />
          </div>
          <div className="ga-field-hint">
            {t('Free-text style hint for outfit generation. Room decency still applies.')}
          </div>
        </div>
      </section>
      {ttsSecs.map((s) => sectionBlock(s))}
    </div>
  )
}
