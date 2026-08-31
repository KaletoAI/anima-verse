import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

/**
 * Per-character image-generation overrides (Characters → Image):
 *  - Backend match: a glob over image-backend names (e.g. "Flux*"). The server
 *    resolves it to a concrete backend at render time, picking among matches by
 *    availability — independent of the global fallback. A model picker is
 *    intentionally absent (the model comes from the backend).
 *  - T-pose backend match: a second glob used ONLY for the T-pose reference
 *    renders (the image->3D input), e.g. a pose-controlled backend alias.
 *  - LoRA override: LoRAs always applied for this character.
 *  - T-pose LoRAs: replace the LoRA override for the T-pose reference renders
 *    (different backend, different LoRA ecosystem — no merge).
 * Backed by /characters/{name}/outfit-imagegen (GET/PUT) plus the backend
 * list (/world/imagegen-options) and available LoRAs (/outfit-lora-options).
 *
 * THIS PANEL DOES NOT WRITE. Every edit goes into the character sheet's change
 * buffer (`queueImagegen`) and leaves with the toolbar's one Save.
 *
 * WHY EVERY EDIT QUEUES ALL FOUR KEYS: the store behind this panel is
 * `PUT /characters/{name}/outfit-imagegen`, and that route takes the WHOLE
 * record — a body carrying only `loras` would blank the two match patterns.
 * The buffer hands its patch to that route unchanged, so the patch has to BE
 * the whole record: `{workflow, tpose_workflow, loras, tpose_loras}`, every
 * time, with the edited value taken from the event (the state behind it is one
 * render old) and the other three from the current render. The visible cost is
 * that one keystroke here counts as four pending fields in "Save (n)".
 *
 * The "Add LoRA" choices are the one thing the SAVED values decide: the server
 * resolves them from the stored backend match, so a match still sitting in the
 * buffer suggests LoRAs for the previous backend. They are refetched when the
 * container reports a successful Save (`savedSignal`) — the hint under the
 * match field says so. The "Currently matches" previews are computed here and
 * follow the typed pattern immediately.
 */

interface Lora {
  name: string
  strength: number
}

/** The override record as this panel holds it. */
interface Override {
  pattern: string
  tposePattern: string
  loras: Lora[]
  tposeLoras: Lora[]
}

const EMPTY_OVERRIDE: Override = { pattern: '', tposePattern: '', loras: [], tposeLoras: [] }

// Convert a shell-style glob (only '*' wildcard) to a case-insensitive regex.
function globToRegex(glob: string): RegExp {
  const escaped = glob.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')
  return new RegExp('^' + escaped + '$', 'i')
}

// Make a match spec readable: "backend:LocalAI-Flux" -> "LocalAI-Flux".
function formatMatchSpec(spec: string): string {
  const s = (spec || '').trim()
  if (s.startsWith('backend:')) return s.slice(8)
  return s
}

/** The buffered record laid OVER the stored one, key by key — what the panel
 *  shows when it is re-opened while the sheet still holds unsaved edits. */
function withDraft(stored: Override, draft: Record<string, unknown>): Override {
  return {
    pattern: typeof draft.workflow === 'string' ? draft.workflow : stored.pattern,
    tposePattern: typeof draft.tpose_workflow === 'string' ? draft.tpose_workflow : stored.tposePattern,
    loras: Array.isArray(draft.loras) ? (draft.loras as Lora[]) : stored.loras,
    tposeLoras: Array.isArray(draft.tpose_loras) ? (draft.tpose_loras as Lora[]) : stored.tposeLoras,
  }
}

export function ImageOverrides({
  character,
  queueImagegen,
  draft,
  discardSignal,
  savedSignal,
}: {
  character: string
  /** Remember the whole override record — see the module note on why all four
   *  keys travel together. */
  queueImagegen: (patch: Record<string, unknown>) => void
  /** The container's buffered record, laid over what the GET returned. */
  draft: Record<string, unknown>
  /** Bumped by the container's Discard — back to the stored values. */
  discardSignal: number
  /** Bumped by a successful Save — the LoRA suggestions are re-resolved. */
  savedSignal: number
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [pattern, setPattern] = useState('')
  const [tposePattern, setTposePattern] = useState('')
  const [loras, setLoras] = useState<Lora[]>([])
  const [tposeLoras, setTposeLoras] = useState<Lora[]>([])
  const [backends, setBackends] = useState<string[]>([])  // image-backend names (match target)
  const [outfitDefault, setOutfitDefault] = useState('')  // global outfit default (match spec)
  const [availableLoras, setAvailableLoras] = useState<Array<{ name: string; missing?: boolean }>>([])
  const [tposeLoraOptions, setTposeLoraOptions] = useState<Array<{ name: string; missing?: boolean }>>([])
  const [loading, setLoading] = useState(false)
  const [addName, setAddName] = useState('')
  const [addTposeName, setAddTposeName] = useState('')

  /** What the server last handed us — where a Discard goes back to. */
  const storedRef = useRef<Override>(EMPTY_OVERRIDE)
  /** Read inside the loaders without making them depend on the draft. */
  const draftRef = useRef(draft)
  draftRef.current = draft

  const show = useCallback((rec: Override) => {
    setPattern(rec.pattern)
    setTposePattern(rec.tposePattern)
    setLoras(rec.loras)
    setTposeLoras(rec.tposeLoras)
  }, [])

  // The server resolves the LoRA list from the SAVED match pattern (backend
  // lora_filter + library, endpoint-filtered) — so the "Add LoRA" choices
  // must be refetched after every Save, not loaded just once.
  const refreshLoraOptions = useCallback(async () => {
    try {
      const loraOpts = await apiGet<{ loras?: Array<{ name: string; missing?: boolean }> }>(
        `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}`,
      )
      setAvailableLoras((loraOpts.loras || []).filter((l) => l.name && l.name !== 'None'))
    } catch { /* keep the previous list */ }
    try {
      // The T-pose list is scoped to the T-pose match backend (which falls
      // back to the render match when its glob is empty).
      const tposeOpts = await apiGet<{ loras?: Array<{ name: string; missing?: boolean }> }>(
        `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}&target=tpose`,
      )
      setTposeLoraOptions((tposeOpts.loras || []).filter((l) => l.name && l.name !== 'None'))
    } catch { /* keep the previous list */ }
  }, [character])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [ovr, opts, loraOpts, tposeOpts] = await Promise.all([
          apiGet<{ workflow?: string; tpose_workflow?: string; loras?: Lora[]; tpose_loras?: Lora[] }>(
            `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
          ),
          apiGet<{ options?: Array<{ name?: string; category?: string }>; outfit_imagegen_default?: string }>('/world/imagegen-options'),
          apiGet<{ loras?: Array<{ name: string; missing?: boolean }> }>(
            `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}`,
          ),
          apiGet<{ loras?: Array<{ name: string; missing?: boolean }> }>(
            `/characters/outfit-lora-options?character_name=${encodeURIComponent(character)}&target=tpose`,
          )
        ])
        if (cancelled) return
        const stored: Override = {
          pattern: ovr.workflow || '',
          tposePattern: ovr.tpose_workflow || '',
          loras: Array.isArray(ovr.loras) ? ovr.loras : [],
          tposeLoras: Array.isArray(ovr.tpose_loras) ? ovr.tpose_loras : [],
        }
        storedRef.current = stored
        // Unsaved edits survive a trip to another sub-tab and back.
        show(withDraft(stored, draftRef.current))
        // Inpaint targets (category=inpaint) are only for Map-Fit/Match-Edges,
        // not for a character's normal render matching.
        setBackends(
          (opts.options || [])
            .filter((o) => o.name && o.category !== 'inpaint')
            .map((o) => o.name as string),
        )
        setOutfitDefault(opts.outfit_imagegen_default || '')
        setAvailableLoras((loraOpts.loras || []).filter((l) => l.name && l.name !== 'None'))
        setTposeLoraOptions((tposeOpts.loras || []).filter((l) => l.name && l.name !== 'None'))
      } catch (e) {
        if (!cancelled) toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [character, show, t, toast])

  // A Discard empties the buffer — the fields go back to what is stored.
  // The last seen value, not a "first run" flag: StrictMode runs an effect
  // twice on mount, and a flag would let the second run wipe the fields.
  const seenDiscard = useRef(discardSignal)
  useEffect(() => {
    if (seenDiscard.current === discardSignal) return
    seenDiscard.current = discardSignal
    show(storedRef.current)
  }, [discardSignal, show])

  // A Save made the buffered record the stored one: re-read it (the server may
  // normalise) and re-resolve the LoRA suggestions for the now-saved match.
  const seenSaved = useRef(savedSignal)
  useEffect(() => {
    if (seenSaved.current === savedSignal) return
    seenSaved.current = savedSignal
    let cancelled = false
    ;(async () => {
      try {
        const ovr = await apiGet<{ workflow?: string; tpose_workflow?: string; loras?: Lora[]; tpose_loras?: Lora[] }>(
          `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
        )
        if (cancelled) return
        const stored: Override = {
          pattern: ovr.workflow || '',
          tposePattern: ovr.tpose_workflow || '',
          loras: Array.isArray(ovr.loras) ? ovr.loras : [],
          tposeLoras: Array.isArray(ovr.tpose_loras) ? ovr.tpose_loras : [],
        }
        storedRef.current = stored
        show(stored)
      } catch { /* keep what is on screen */ }
    })()
    void refreshLoraOptions()
    return () => { cancelled = true }
  }, [savedSignal, character, refreshLoraOptions, show])

  /** Put the WHOLE record into the buffer. Callers pass the value they just
   *  changed explicitly, because their state is still one render behind. */
  const queueRecord = useCallback(
    (next: Partial<Override>) => {
      queueImagegen({
        workflow: (next.pattern ?? pattern).trim(),
        tpose_workflow: (next.tposePattern ?? tposePattern).trim(),
        loras: next.loras ?? loras,
        tpose_loras: next.tposeLoras ?? tposeLoras,
      })
    },
    [queueImagegen, pattern, tposePattern, loras, tposeLoras],
  )

  const matching = useMemo(() => {
    const p = pattern.trim()
    if (!p) return []
    // Glob over image-backend names (an optional "backend:" prefix is allowed) —
    // same resolution as resolve_imagegen_target on the server.
    const re = globToRegex(p.replace(/^backend:/i, '').trim())
    return backends.filter((b) => re.test(b))
  }, [pattern, backends])

  // Same glob resolution for the T-pose-only match.
  const tposeMatching = useMemo(() => {
    const p = tposePattern.trim()
    if (!p) return []
    const re = globToRegex(p.replace(/^backend:/i, '').trim())
    return backends.filter((b) => re.test(b))
  }, [tposePattern, backends])

  /** A LoRA list edit: on screen and in the buffer in the same breath, so a
   *  picked-and-added LoRA is part of the sheet without a second click. */
  const editLoras = useCallback(
    (next: Lora[]) => {
      setLoras(next)
      queueRecord({ loras: next })
    },
    [queueRecord],
  )

  const editTposeLoras = useCallback(
    (next: Lora[]) => {
      setTposeLoras(next)
      queueRecord({ tposeLoras: next })
    },
    [queueRecord],
  )

  const savedHint = t('LoRA suggestions follow the SAVED match — they are re-read after Save.')

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div className="ga-form">
      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('Render match')}</div>
        <div className="ga-form-row">
          <Field
            label={t('Backend match (glob)')}
            help="imagegen_target"
            hint={t('e.g. "Flux*" or an exact backend name. Matched against image-backend names; the server picks an available match at render time. Empty = global default.') + ' ' + savedHint}
          >
            <input
              className="ga-input"
              value={pattern}
              placeholder="Flux*"
              onChange={(e) => {
                setPattern(e.target.value)
                queueRecord({ pattern: e.target.value })
              }}
            />
          </Field>
          <Field label={t('Currently matches')} hint={t('Backends matching the pattern right now.')}>
            <div className="ga-img-matches">
              {pattern.trim() === '' ? (
                <span className="ga-sched-muted">
                  {t('— global default —')}
                  {outfitDefault ? (
                    <span className="ga-img-match-chip" style={{ marginLeft: 6 }}>{formatMatchSpec(outfitDefault)}</span>
                  ) : null}
                </span>
              ) : matching.length === 0 ? (
                <span className="ga-img-nomatch">{t('no match')}</span>
              ) : (
                matching.map((w) => (
                  <span key={w} className="ga-img-match-chip">
                    {w}
                  </span>
                ))
              )}
            </div>
          </Field>
        </div>
        <div className="ga-form-row">
          <Field
            label={t('T-pose backend match (glob)')}
            hint={t('Backend for the T-pose reference renders only (front and the extra 3D views) — e.g. a pose-controlled alias. Empty = the render match above / global default.') + ' ' + savedHint}
          >
            <input
              className="ga-input"
              value={tposePattern}
              placeholder="TPose*"
              onChange={(e) => {
                setTposePattern(e.target.value)
                queueRecord({ tposePattern: e.target.value })
              }}
            />
          </Field>
          <Field label={t('Currently matches')} hint={t('Backends matching the T-pose pattern right now.')}>
            <div className="ga-img-matches">
              {tposePattern.trim() === '' ? (
                <span className="ga-sched-muted">{t('— render match above —')}</span>
              ) : tposeMatching.length === 0 ? (
                <span className="ga-img-nomatch">{t('no match')}</span>
              ) : (
                tposeMatching.map((w) => (
                  <span key={w} className="ga-img-match-chip">
                    {w}
                  </span>
                ))
              )}
            </div>
          </Field>
        </div>
        {backends.length > 0 ? (
          <p className="ga-sched-muted" style={{ margin: '2px 0 0' }}>
            {t('Available targets:')} {backends.join(', ')}
          </p>
        ) : null}
      </div>

      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('LoRA override')}</div>
        {loras.length === 0 ? (
          <div className="ga-placeholder">{t('No LoRAs forced for this character.')}</div>
        ) : (
          loras.map((l, i) => (
            <div className="ga-form-row" key={i}>
              <Field label={i === 0 ? t('LoRA') : ''}>
                <input className="ga-input" value={l.name} disabled readOnly />
              </Field>
              <Field label={i === 0 ? t('Strength') : ''} compact>
                <input
                  className="ga-input"
                  type="number"
                  step="0.05"
                  style={{ width: 90 }}
                  value={l.strength}
                  onChange={(e) => {
                    const strength = parseFloat(e.target.value)
                    editLoras(
                      loras.map((x, j) => (j === i ? { ...x, strength: isNaN(strength) ? 1 : strength } : x)),
                    )
                  }}
                />
              </Field>
              <Field label={i === 0 ? '' : ''} compact>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  onClick={() => editLoras(loras.filter((_, j) => j !== i))}
                >
                  {t('Remove')}
                </button>
              </Field>
            </div>
          ))
        )}
        <div className="ga-form-row" style={{ marginTop: 6, gap: 8 }}>
          <Field label={t('Add LoRA')}>
            <select className="ga-input" value={addName} onChange={(e) => setAddName(e.target.value)}>
              <option value="">— {t('pick a LoRA')} —</option>
              {availableLoras
                .filter((l) => !loras.some((x) => x.name === l.name))
                .map((l) => (
                  <option key={l.name} value={l.name}>
                    {l.name}{l.missing ? ` ${t('(missing)')}` : ''}
                  </option>
                ))}
            </select>
          </Field>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={!addName}
              onClick={() => {
                if (!addName) return
                editLoras([...loras, { name: addName, strength: 1 }])
                setAddName('')
              }}
            >
              {t('Add')}
            </button>
          </div>
        </div>
      </div>

      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('T-pose LoRAs')}</div>
        <p className="ga-sched-muted" style={{ margin: '0 0 6px' }}>
          {t('Used INSTEAD of the LoRAs above for the T-pose reference renders; suggestions come from the T-pose match backend. Empty = the LoRAs above apply.')}
        </p>
        {tposeLoras.length === 0 ? (
          <div className="ga-placeholder">{t('No separate LoRAs for the T-pose renders.')}</div>
        ) : (
          tposeLoras.map((l, i) => (
            <div className="ga-form-row" key={i}>
              <Field label={i === 0 ? t('LoRA') : ''}>
                <input className="ga-input" value={l.name} disabled readOnly />
              </Field>
              <Field label={i === 0 ? t('Strength') : ''} compact>
                <input
                  className="ga-input"
                  type="number"
                  step="0.05"
                  style={{ width: 90 }}
                  value={l.strength}
                  onChange={(e) => {
                    const strength = parseFloat(e.target.value)
                    editTposeLoras(
                      tposeLoras.map((x, j) => (j === i ? { ...x, strength: isNaN(strength) ? 1 : strength } : x)),
                    )
                  }}
                />
              </Field>
              <Field label={i === 0 ? '' : ''} compact>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  onClick={() => editTposeLoras(tposeLoras.filter((_, j) => j !== i))}
                >
                  {t('Remove')}
                </button>
              </Field>
            </div>
          ))
        )}
        <div className="ga-form-row" style={{ marginTop: 6, gap: 8 }}>
          <Field label={t('Add LoRA')}>
            <select className="ga-input" value={addTposeName} onChange={(e) => setAddTposeName(e.target.value)}>
              <option value="">— {t('pick a LoRA')} —</option>
              {tposeLoraOptions
                .filter((l) => !tposeLoras.some((x) => x.name === l.name))
                .map((l) => (
                  <option key={l.name} value={l.name}>
                    {l.name}{l.missing ? ` ${t('(missing)')}` : ''}
                  </option>
                ))}
            </select>
          </Field>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={!addTposeName}
              onClick={() => {
                if (!addTposeName) return
                editTposeLoras([...tposeLoras, { name: addTposeName, strength: 1 }])
                setAddTposeName('')
              }}
            >
              {t('Add')}
            </button>
          </div>
        </div>
      </div>

    </div>
  )
}
