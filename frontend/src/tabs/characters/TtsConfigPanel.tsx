/**
 * TtsConfigPanel — compact, generic per-character TTS settings rendered via
 * the template special slot `tts_config`.
 *
 * Unifies AI-Hub TTS aliases (e.g. `hub:ZONOS3-Mini`, `hub:ming-3.0-tts-0.5b`)
 * and legacy backends (`xtts`, `magpie`, `f5`) into at most 5 fields:
 *   1. `tts_enabled`  (Yes / No)
 *   2. `tts_auto`     (Yes / No)
 *   3. `tts_model`    (Global default, AI-Hub alias, or legacy backend)
 *   4. `tts_voice`    (ONE generic select: model presets + cloned `voices/` files)
 *   5. `tts_param`    (ONE context-aware extra parameter — style or speaking rate —
 *                      hidden when the selected model declares none)
 *
 * Reads live capabilities from `GET /tts/capabilities` and queues every edit
 * into the Character tab's shared draft buffer (`queueField('config', ...)`).
 * Legacy `tts_speaker_wav` values are transparently surfaced as `clone:<path>`.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface VoiceOption {
  value: string
  label: string
  path?: string
}

interface ExtraParamMeta {
  kind: 'style' | 'speed'
  param: string
  label: string
  label_de?: string
  placeholder?: string
  placeholder_de?: string
  hint?: string
  hint_de?: string
  min?: number | null
  max?: number | null
  neutral?: number | null
}

interface TtsModelCap {
  id: string
  alias?: string
  label: string
  source: 'ai_hub_local' | 'ai_hub_cloud' | 'legacy'
  available: boolean
  voices: VoiceOption[]
  default_voice?: string
  supports_clone: boolean
  clone_required?: boolean
  extra_param?: ExtraParamMeta | null
}

interface TtsCapabilities {
  enabled: boolean
  default_model: string
  models: TtsModelCap[]
  cloned_voices: VoiceOption[]
}

function asBoolStr(val: unknown, fallback: boolean): 'true' | 'false' {
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  if (typeof val === 'string') {
    const low = val.trim().toLowerCase()
    if (low === 'true' || low === '1' || low === 'yes') return 'true'
    if (low === 'false' || low === '0' || low === 'no') return 'false'
  }
  return fallback ? 'true' : 'false'
}

export function TtsConfigPanel({
  character,
  queueField,
  draftConfig,
  discardSignal,
  savedSignal,
}: {
  character: string
  queueField?: (scope: 'profile' | 'config', key: string, value: unknown) => void
  draftConfig?: Record<string, unknown>
  discardSignal?: number
  savedSignal?: number
}) {
  const { lang } = useI18n()
  const { toast } = useToast()
  const isDe = lang === 'de'

  const [serverCfg, setServerCfg] = useState<Record<string, unknown>>({})
  const [caps, setCaps] = useState<TtsCapabilities | null>(null)
  const [testing, setTesting] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    let alive = true
    apiGet<TtsCapabilities>('/tts/capabilities')
      .then((d) => { if (alive) setCaps(d) })
      .catch(() => { if (alive) setCaps(null) })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    let alive = true
    apiGet<{ config?: Record<string, unknown> }>(
      `/characters/${encodeURIComponent(character)}/config`,
    )
      .then((d) => { if (alive) setServerCfg(d.config || {}) })
      .catch(() => { if (alive) setServerCfg({}) })
    return () => { alive = false }
  }, [character, discardSignal, savedSignal])

  const eff = useMemo(
    () => ({ ...serverCfg, ...(draftConfig || {}) }),
    [serverCfg, draftConfig],
  )

  const enabledStr = asBoolStr(eff.tts_enabled, true)
  const autoStr = asBoolStr(eff.tts_auto, false)
  const rawModel = typeof eff.tts_model === 'string' ? eff.tts_model : ''
  const rawVoice = typeof eff.tts_voice === 'string' ? eff.tts_voice : ''
  const legacySpeaker = typeof eff.tts_speaker_wav === 'string' ? eff.tts_speaker_wav : ''
  const rawParam = eff.tts_param != null ? String(eff.tts_param) : ''

  // Backward-compatible canonical voice value: legacy tts_speaker_wav -> clone:<path>
  const effectiveVoice = rawVoice || (legacySpeaker ? `clone:${legacySpeaker}` : '')

  const models = useMemo(() => caps?.models || [], [caps])
  const defaultModelId = caps?.default_model || ''
  const activeModelId = rawModel || defaultModelId
  const activeModel = useMemo(
    () => models.find((m) => m.id === activeModelId) || null,
    [models, activeModelId],
  )
  const defaultModelLabel = useMemo(() => {
    const found = models.find((m) => m.id === defaultModelId)
    return found ? found.label : (defaultModelId || 'Default')
  }, [models, defaultModelId])

  const hubModels = useMemo(
    () => models.filter((m) => m.source === 'ai_hub_local' || m.source === 'ai_hub_cloud'),
    [models],
  )
  const legacyModels = useMemo(
    () => models.filter((m) => m.source === 'legacy'),
    [models],
  )

  const presetVoices = activeModel?.voices || []
  const clonedVoices = activeModel ? (activeModel.supports_clone ? (caps?.cloned_voices || []) : []) : (caps?.cloned_voices || [])

  // Preserve an unknown saved value so switching models never silently blanks it
  const voiceKnown = !effectiveVoice
    || presetVoices.some((v) => v.value === effectiveVoice)
    || clonedVoices.some((v) => v.value === effectiveVoice)

  const modelKnown = !rawModel || models.some((m) => m.id === rawModel)
  const extraMeta = activeModel?.extra_param || null

  const updateField = (key: string, value: unknown) => {
    if (queueField) {
      queueField('config', key, value)
    } else {
      void apiPost(`/characters/${encodeURIComponent(character)}/config`, { fields: { [key]: value } })
        .then(() => setServerCfg((prev) => ({ ...prev, [key]: value })))
        .catch((e) => toast((e as Error).message, 'error'))
    }
  }

  const onVoiceChange = (val: string) => {
    updateField('tts_voice', val)
    if (legacySpeaker) {
      // Clear legacy speaker field once migrated into generic tts_voice
      updateField('tts_speaker_wav', '')
    }
  }

  const onTestVoice = async () => {
    setTesting(true)
    try {
      const sample = isDe
        ? `Hallo, ich bin ${character}. So klingt meine Stimme.`
        : `Hello, I am ${character}. This is how my voice sounds.`
      const res = await apiPost<{ audio_url?: string; error?: string }>('/tts/speak', {
        text: sample,
        character_name: character,
        model: rawModel,
        voice: effectiveVoice,
        param: rawParam,
      })
      if (res.audio_url) {
        if (audioRef.current) {
          audioRef.current.pause()
        }
        const audio = new Audio(res.audio_url)
        audioRef.current = audio
        await audio.play()
      } else {
        toast(res.error || (isDe ? 'TTS-Test fehlgeschlagen' : 'TTS test failed'), 'error')
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setTesting(false)
    }
  }

  const voiceHint = (() => {
    if (!activeModel) {
      return isDe
        ? 'Modell-Stimme oder geklonte Referenz-Stimme (voices/)'
        : 'Model preset voice or cloned reference voice (voices/)'
    }
    if (activeModel.clone_required) {
      return isDe
        ? 'Benötigt eine geklonte Referenz-Stimme aus voices/ (leer = Modell-Standard)'
        : 'Uses a cloned reference voice from voices/ (empty = model default)'
    }
    if (activeModel.supports_clone && presetVoices.length > 0) {
      return isDe
        ? 'Modell-Stimme oder geklonte Referenz-Stimme (Geklont überschreibt Preset)'
        : 'Model preset voice or cloned reference voice (clone overrides preset)'
    }
    if (activeModel.supports_clone) {
      return isDe
        ? 'Geklonte Referenz-Stimme aus voices/ (leer = Modell-Standard)'
        : 'Cloned reference voice from voices/ (empty = model default)'
    }
    return isDe
      ? 'Vordefinierte Stimme des gewählten Modells (leer = Standard)'
      : 'Preset voice of the selected model (empty = default)'
  })()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Field label={isDe ? 'TTS aktiviert' : 'TTS enabled'}>
        <select
          className="ga-input"
          value={enabledStr}
          onChange={(e) => updateField('tts_enabled', e.target.value === 'true')}
        >
          <option value="true">{isDe ? 'Ja' : 'Yes'}</option>
          <option value="false">{isDe ? 'Nein' : 'No'}</option>
        </select>
      </Field>

      <Field label="Auto-Play">
        <select
          className="ga-input"
          value={autoStr}
          onChange={(e) => updateField('tts_auto', e.target.value === 'true')}
        >
          <option value="true">{isDe ? 'Ja' : 'Yes'}</option>
          <option value="false">{isDe ? 'Nein' : 'No'}</option>
        </select>
      </Field>

      <Field
        label={isDe ? 'Modell / Backend' : 'Model / Backend'}
        hint={isDe ? 'Leer = globaler Standard aus den Einstellungen' : 'Empty = global default from settings'}
      >
        <select
          className="ga-input"
          value={rawModel}
          onChange={(e) => updateField('tts_model', e.target.value)}
        >
          <option value="">
            {isDe ? `Globaler Standard (${defaultModelLabel})` : `Global default (${defaultModelLabel})`}
          </option>
          {!modelKnown && (
            <option value={rawModel}>{rawModel}</option>
          )}
          {hubModels.length > 0 && (
            <optgroup label="AI-Hub">
              {hubModels.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </optgroup>
          )}
          {legacyModels.length > 0 && (
            <optgroup label={isDe ? 'Lokale Backends' : 'Local backends'}>
              {legacyModels.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </optgroup>
          )}
        </select>
      </Field>

      <Field label={isDe ? 'Stimme' : 'Voice'} hint={voiceHint}>
        <select
          className="ga-input"
          value={effectiveVoice}
          onChange={(e) => onVoiceChange(e.target.value)}
        >
          <option value="">
            {activeModel?.default_voice
              ? (isDe ? `Standard (${activeModel.default_voice})` : `Default (${activeModel.default_voice})`)
              : (isDe ? 'Standard' : 'Default')}
          </option>
          {!voiceKnown && (
            <option value={effectiveVoice}>
              {effectiveVoice.startsWith('clone:') ? `${effectiveVoice.slice(6)} (clone)` : effectiveVoice}
            </option>
          )}
          {presetVoices.length > 0 && (
            <optgroup label={isDe ? 'Modell-Stimmen' : 'Model voices'}>
              {presetVoices.map((v) => (
                <option key={v.value} value={v.value}>{v.label}</option>
              ))}
            </optgroup>
          )}
          {clonedVoices.length > 0 && (
            <optgroup label={isDe ? 'Geklonte Stimmen (voices/)' : 'Cloned voices (voices/)'}>
              {clonedVoices.map((v) => (
                <option key={v.value} value={v.value}>{v.label}</option>
              ))}
            </optgroup>
          )}
        </select>
      </Field>

      {extraMeta && (
        <Field
          label={isDe ? (extraMeta.label_de || extraMeta.label) : extraMeta.label}
          hint={isDe ? (extraMeta.hint_de || extraMeta.hint) : extraMeta.hint}
        >
          <input
            className="ga-input"
            type={extraMeta.kind === 'speed' ? 'number' : 'text'}
            step={extraMeta.kind === 'speed' ? '0.05' : undefined}
            min={extraMeta.kind === 'speed' && extraMeta.min != null ? extraMeta.min : undefined}
            max={extraMeta.kind === 'speed' && extraMeta.max != null ? extraMeta.max : undefined}
            placeholder={isDe ? (extraMeta.placeholder_de || extraMeta.placeholder || '') : (extraMeta.placeholder || '')}
            value={rawParam}
            onChange={(e) => updateField('tts_param', e.target.value)}
          />
        </Field>
      )}

      {caps?.enabled && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 2 }}>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={testing}
            onClick={() => { void onTestVoice() }}
          >
            {testing
              ? (isDe ? 'Generiere…' : 'Generating…')
              : (isDe ? 'Stimme testen' : 'Test voice')}
          </button>
        </div>
      )}
    </div>
  )
}
