import { isGeneratorBackend } from '../../lib/imageBackends'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

/**
 * Per-character image-generation overrides (Characters → Image):
 *  - Backend match: a glob over image-backend names (e.g. "Flux*"). It is
 *    position 0 before the occasion chain of the image routing (Admin → Media
 *    Generation → Routing): every render of this character that names no
 *    backend of its own (outfit and variant previews, chat photos, TakePhoto
 *    turns) tries this match first, then the chain. A model picker
 *    is intentionally absent (the model comes from the backend).
 *  - T-pose backend match: a second glob used ONLY for the T-pose reference
 *    renders (the image->3D input) — position 0 of the T-pose chain.
 *  - Portrait backend match: a separate glob for portraits; empty uses
 *    the server's portrait occasion chain without inheriting the render match.
 *  - LoRA override: LoRAs always applied for this character.
 *  - T-pose LoRAs: replace the LoRA override for the T-pose reference renders
 *    (different backend, different LoRA ecosystem — no merge).
 * Backed by /characters/{name}/outfit-imagegen (GET/PUT) plus the backend
 * list (/world/imagegen-options) and available LoRAs (/outfit-lora-options).
 *
 * THIS PANEL DOES NOT WRITE. Every edit goes into the character sheet's change
 * buffer (`queueImagegen`) and leaves with the toolbar's one Save.
 *
 * WHY EVERY EDIT QUEUES THE WHOLE RECORD: the store behind this panel is
 * `PUT /characters/{name}/outfit-imagegen`, and that route takes the WHOLE
 * record — a body carrying only `loras` would blank the match patterns.
 * The buffer hands its patch to that route unchanged, so the patch has to BE
 * `{workflow, profile_workflow, tpose_workflow, tpose_view_workflow, loras, tpose_loras}`, every
 * time, with the edited value taken from the event (the state behind it is one
 * render old) and the other fields from the current render. One keystroke here
 * therefore counts as six pending fields in "Save (n)".
 *
 * The "Add LoRA" choices are the one thing the SAVED values decide: the server
 * resolves them from the stored backend match, so a match still sitting in the
 * buffer suggests LoRAs for the previous backend. They are refetched when the
 * container reports a successful Save (`savedSignal`). Matching previews are
 * computed here and follow the typed pattern immediately.
 */

interface Lora {
  name: string
  strength: number
}

/** The override record as this panel holds it. */
interface Override {
  pattern: string
  tposePattern: string
  tposeViewPattern: string
  profilePattern: string
  loras: Lora[]
  tposeLoras: Lora[]
}

const EMPTY_OVERRIDE: Override = { pattern: '', tposePattern: '', tposeViewPattern: '', profilePattern: '', loras: [], tposeLoras: [] }

// Convert a shell-style glob (only '*' wildcard) to a case-insensitive regex.
function globToRegex(glob: string): RegExp {
  const escaped = glob.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')
  return new RegExp('^' + escaped + '$', 'i')
}

/** The buffered record laid OVER the stored one, key by key — what the panel
 *  shows when it is re-opened while the sheet still holds unsaved edits. */
function withDraft(stored: Override, draft: Record<string, unknown>): Override {
  return {
    pattern: typeof draft.workflow === 'string' ? draft.workflow : stored.pattern,
    tposePattern: typeof draft.tpose_workflow === 'string' ? draft.tpose_workflow : stored.tposePattern,
    tposeViewPattern: typeof draft.tpose_view_workflow === 'string' ? draft.tpose_view_workflow : stored.tposeViewPattern,
    profilePattern: typeof draft.profile_workflow === 'string' ? draft.profile_workflow : stored.profilePattern,
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
  /** Remember the whole override record — see the module note on why all six
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
  const [tposeViewPattern, setTposeViewPattern] = useState('')
  const [profilePattern, setProfilePattern] = useState('')
  const [loras, setLoras] = useState<Lora[]>([])
  const [tposeLoras, setTposeLoras] = useState<Lora[]>([])
  const [backends, setBackends] = useState<string[]>([])  // image-backend names (match target)
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
    setTposeViewPattern(rec.tposeViewPattern)
    setProfilePattern(rec.profilePattern)
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
          apiGet<{ workflow?: string; profile_workflow?: string; tpose_workflow?: string; tpose_view_workflow?: string; loras?: Lora[]; tpose_loras?: Lora[] }>(
            `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
          ),
          apiGet<{ options?: Array<{ name?: string; category?: string }> }>('/world/imagegen-options'),
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
          tposeViewPattern: ovr.tpose_view_workflow || '',
          profilePattern: ovr.profile_workflow || '',
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
            .filter((o) => o.name && isGeneratorBackend(o))
            .map((o) => o.name as string),
        )
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
        const ovr = await apiGet<{ workflow?: string; profile_workflow?: string; tpose_workflow?: string; tpose_view_workflow?: string; loras?: Lora[]; tpose_loras?: Lora[] }>(
          `/characters/${encodeURIComponent(character)}/outfit-imagegen`,
        )
        if (cancelled) return
        const stored: Override = {
          pattern: ovr.workflow || '',
          tposePattern: ovr.tpose_workflow || '',
          tposeViewPattern: ovr.tpose_view_workflow || '',
          profilePattern: ovr.profile_workflow || '',
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
        tpose_view_workflow: (next.tposeViewPattern ?? tposeViewPattern).trim(),
        profile_workflow: (next.profilePattern ?? profilePattern).trim(),
        loras: next.loras ?? loras,
        tpose_loras: next.tposeLoras ?? tposeLoras,
      })
    },
    [queueImagegen, pattern, tposePattern, tposeViewPattern, profilePattern, loras, tposeLoras],
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

  const tposeViewMatching = useMemo(() => {
    const p = tposeViewPattern.trim()
    if (!p) return []
    const re = globToRegex(p.replace(/^backend:/i, '').trim())
    return backends.filter((b) => re.test(b))
  }, [tposeViewPattern, backends])

  const profileMatching = useMemo(() => {
    const p = profilePattern.trim()
    if (!p) return []
    const re = globToRegex(p.replace(/^backend:/i, '').trim())
    return backends.filter((b) => re.test(b))
  }, [profilePattern, backends])

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

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div className="ga-form">
      <div className="ga-fieldset">
        <div className="ga-fieldset-title">{t('Render match')}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 240px), 1fr))', gap: 16 }}>
          {[
            { label: t('Backend match (glob)'), value: pattern, set: setPattern, key: 'pattern', matches: matching, placeholder: 'Flux*', empty: t('Empty: occasion chain') },
            { label: t('Portrait backend match (glob)'), value: profilePattern, set: setProfilePattern, key: 'profilePattern', matches: profileMatching, placeholder: 'Portrait*', empty: t('Empty: portrait chain') },
            { label: t('T-pose backend match (glob)'), value: tposePattern, set: setTposePattern, key: 'tposePattern', matches: tposeMatching, placeholder: 'TPose*', empty: t('Empty: render match, then T-pose chain') },
            { label: t('T-pose views backend match (glob)'), value: tposeViewPattern, set: setTposeViewPattern, key: 'tposeViewPattern', matches: tposeViewMatching, placeholder: 'Flux*', empty: t('Empty: T-pose views chain') },
          ].map((match) => (
            <Field key={match.key} label={match.label}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', minWidth: 0 }}>
              <input
                className="ga-input"
                value={match.value}
                placeholder={match.placeholder}
                onChange={(e) => {
                  match.set(e.target.value)
                  queueRecord({ [match.key]: e.target.value })
                }}
              />
              <div className="ga-img-matches">
                {!match.value.trim() ? (
                  <span className="ga-sched-muted">{match.empty}</span>
                ) : match.matches.length === 0 ? (
                  <span className="ga-img-nomatch">{t('no match')}</span>
                ) : (
                  match.matches.map((name) => (
                    <span key={name} className="ga-img-match-chip">{name}</span>
                  ))
                )}
              </div>
              </div>
            </Field>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 16 }}>
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
        {tposeLoras.length === 0 ? (
          <div className="ga-placeholder">{t('Empty: use the normal LoRAs')}</div>
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

    </div>
  )
}
