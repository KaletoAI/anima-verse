import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { usePersistentState } from '../../lib/usePersistentState'
import { ModelPicker, type PickerOption } from '../../components/ModelPicker'
import type { LocationRef } from '../../lib/refs'

/**
 * "+ New NPC" — runs the temporary-NPC pipeline and shows its four stages
 * live. The endpoint answers with an SSE stream (one frame per stage
 * transition), so the admin sees which turn is running instead of a spinner
 * over a multi-turn LLM run.
 *
 * Model + validator model are per-browser state, exactly like the World Dev
 * header: there is no server-side default to fall back on.
 */

type StageId = 'generate' | 'validate' | 'repair' | 'apply'

const STAGES: StageId[] = ['generate', 'validate', 'repair', 'apply']

interface ModelEntry {
  name: string
  provider?: string
  pricing?: { input?: number; output?: number }
}

interface StageFrame {
  stage?: StageId
  status?: 'running' | 'done' | 'skipped'
  error?: string
  gaps?: string[]
  applied?: { character?: string }
  done?: boolean
}

export function NewNpcDialog({
  locations,
  defaultLocationId,
  onClose,
  onCreated,
}: {
  locations: LocationRef[]
  defaultLocationId?: string
  onClose: () => void
  onCreated: (name: string) => void
}) {
  const { t } = useI18n()
  const [briefing, setBriefing] = useState('')
  const [locationId, setLocationId] = useState(defaultLocationId || '')
  const [roomId, setRoomId] = useState('')
  const [ttlHours, setTtlHours] = useState('')
  const [model, setModel] = usePersistentState('npc.model', '')
  const [provider, setProvider] = usePersistentState('npc.provider', '')
  const [validateModel, setValidateModel] = usePersistentState('npc.validateModel', '')
  const [validateProvider, setValidateProvider] = usePersistentState('npc.validateProvider', '')
  const [models, setModels] = useState<ModelEntry[]>([])
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState<Record<string, StageFrame>>({})
  const [gaps, setGaps] = useState<string[]>([])
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    apiGet<{ providers?: Record<string, { models?: ModelEntry[] }> }>('/characters/available-models')
      .then((d) => {
        const flat: ModelEntry[] = []
        for (const [provName, prov] of Object.entries(d.providers || {})) {
          for (const m of prov.models || []) {
            flat.push({ name: m.name, provider: provName, pricing: m.pricing })
          }
        }
        setModels(flat)
      })
      .catch(() => setModels([]))
  }, [])

  // Cancel an in-flight stream when the dialog goes away.
  useEffect(() => () => abortRef.current?.abort(), [])

  const modelOptions: PickerOption[] = useMemo(
    () =>
      [...models]
        .sort(
          (a, b) =>
            (a.provider || '').localeCompare(b.provider || '') || a.name.localeCompare(b.name),
        )
        .map((m) => ({
          value: `${m.provider || ''}|${m.name}`,
          label: m.name,
          group: m.provider || '',
        })),
    [models],
  )

  const rooms = useMemo(
    () => locations.find((l) => l.id === locationId)?.rooms || [],
    [locations, locationId],
  )

  const canSubmit = !!briefing.trim() && !!locationId && !!model && !running

  const submit = async () => {
    if (!canSubmit) return
    setRunning(true)
    setStages({})
    setGaps([])
    setError('')
    const controller = new AbortController()
    abortRef.current = controller
    let createdName = ''
    try {
      const res = await fetch('/npc/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        signal: controller.signal,
        body: JSON.stringify({
          briefing: briefing.trim(),
          location_id: locationId,
          room_id: roomId,
          ttl_hours: ttlHours.trim() === '' ? null : Number(ttlHours),
          model,
          provider,
          validator_model: validateModel,
          validator_provider: validateProvider,
        }),
      })
      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => '')
        setError(text || `HTTP ${res.status}`)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let idx: number
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, idx).trim()
          buffer = buffer.slice(idx + 2)
          if (!chunk.startsWith('data:')) continue
          const json = chunk.slice(5).trim()
          if (!json) continue
          let evt: StageFrame
          try {
            evt = JSON.parse(json) as StageFrame
          } catch {
            continue // drop malformed chunks
          }
          if (evt.stage) {
            const stage = evt.stage
            setStages((prev) => ({ ...prev, [stage]: evt }))
            if (evt.gaps) setGaps(evt.gaps)
            if (evt.error) setError(evt.error)
            if (evt.applied?.character) createdName = evt.applied.character
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    } finally {
      setRunning(false)
      abortRef.current = null
      if (createdName) onCreated(createdName)
    }
  }

  const stageLabel = (id: StageId): string =>
    ({
      generate: t('Generate'),
      validate: t('Validate'),
      repair: t('Repair'),
      apply: t('Apply'),
    })[id]

  const stageMark = (frame?: StageFrame): string => {
    if (!frame) return '·'
    if (frame.error) return '✗'
    if (frame.status === 'running') return '…'
    if (frame.status === 'skipped') return '–'
    return '✓'
  }

  return createPortal(
    <div
      className="ga-modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !running) onClose()
      }}
    >
      <div className="ga-modal" role="dialog" aria-label={t('New temporary NPC')} style={{ maxWidth: 620 }}>
        <div className="ga-modal-header">
          <span>✦ {t('New temporary NPC')}</span>
          <button
            className="ga-modal-close"
            onClick={onClose}
            disabled={running}
            aria-label={t('Close')}
          >
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          <p style={{ marginTop: 0, opacity: 0.7, fontSize: '0.86em' }}>
            {t('A temporary NPC has no memory, no relationships and no autonomous thoughts. It stands where you put it, does its one standing task and answers when spoken to.')}
          </p>

          <label className="ga-field">
            <span className="ga-field-caption">{t('Briefing')}</span>
            <textarea
              className="ga-input"
              rows={4}
              value={briefing}
              disabled={running}
              placeholder={t('e.g. a weary barkeeper who has run this place for thirty years')}
              onChange={(e) => setBriefing(e.target.value)}
            />
          </label>

          <div style={{ display: 'flex', gap: 10 }}>
            <label className="ga-field" style={{ flex: 1 }}>
              <span className="ga-field-caption">{t('Location')}</span>
              <select
                className="ga-input"
                value={locationId}
                disabled={running}
                onChange={(e) => {
                  setLocationId(e.target.value)
                  setRoomId('')
                }}
              >
                <option value="">{t('Pick a location')}</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name || l.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="ga-field" style={{ flex: 1 }}>
              <span className="ga-field-caption">{t('Room')}</span>
              <select
                className="ga-input"
                value={roomId}
                disabled={running || rooms.length === 0}
                onChange={(e) => setRoomId(e.target.value)}
              >
                <option value="">{t('(any room)')}</option>
                {rooms.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name || r.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="ga-field" style={{ width: 130 }}>
              <span className="ga-field-caption">{t('TTL (game hours)')}</span>
              <input
                className="ga-input"
                type="number"
                min={0}
                value={ttlHours}
                disabled={running}
                placeholder="∞"
                onChange={(e) => setTtlHours(e.target.value)}
              />
            </label>
          </div>

          <div style={{ display: 'flex', gap: 10 }}>
            <label className="ga-field" style={{ flex: 1 }}>
              <span className="ga-field-caption">{t('Model')}</span>
              <ModelPicker
                options={modelOptions}
                value={provider || model ? `${provider}|${model}` : ''}
                onChange={(v) => {
                  const [p, m] = v.split('|')
                  setProvider(p || '')
                  setModel(m || '')
                }}
              />
            </label>
            <label className="ga-field" style={{ flex: 1 }}>
              <span className="ga-field-caption">{t('Validator model')}</span>
              <ModelPicker
                options={modelOptions}
                value={validateProvider || validateModel ? `${validateProvider}|${validateModel}` : ''}
                emptyLabel={t('same as model')}
                onChange={(v) => {
                  const [p, m] = v.split('|')
                  setValidateProvider(p || '')
                  setValidateModel(m || '')
                }}
              />
            </label>
          </div>

          <div style={{ display: 'flex', gap: 14, margin: '12px 0', fontSize: '0.9em' }}>
            {STAGES.map((id) => {
              const frame = stages[id]
              return (
                <span key={id} style={{ opacity: frame ? 1 : 0.45 }}>
                  {stageMark(frame)} {stageLabel(id)}
                </span>
              )
            })}
          </div>

          {gaps.length > 0 && (
            <details style={{ fontSize: '0.85em', opacity: 0.8 }}>
              <summary>{t('Validator findings ({n})').replace('{n}', String(gaps.length))}</summary>
              <ul style={{ margin: '6px 0 0 0', paddingLeft: 18 }}>
                {gaps.map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            </details>
          )}

          {error && (
            <p style={{ color: '#e0a356', fontSize: '0.86em' }}>{error}</p>
          )}
        </div>
        <div className="ga-modal-footer">
          <button className="ga-btn" onClick={onClose} disabled={running}>
            {t('Cancel')}
          </button>
          <button
            className="ga-btn ga-btn-primary"
            onClick={() => { void submit() }}
            disabled={!canSubmit}
          >
            {running ? t('Generating…') : t('Create NPC')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
