import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { isGeneratorBackend } from '../../lib/imageBackends'
import { Field } from '@anima/player-ui'
import './imagegenOverride.css'

/**
 * The per-character image-generation overrides (`profile.outfit_imagegen`:
 * backend globs + LoRA lists), rendered as the template special slot
 * `imagegen_override`. The section names WHICH keys it shows (`slot_keys`),
 * so every key sits on the tab whose step it steers — render and portrait
 * globs + character LoRAs on Image, the T-pose and outfit-view globs on Pose,
 * the base-body globs on Base body, the HairDeck glob on Hair, the mesh glob
 * on 3D — and moving one is a template edit (base-character.json).
 *
 * A glob is position 0 in front of its occasion chain of the image routing
 * (Admin → Media Generation → Routing; app/imagegen/occasions.py names the
 * occasion of each key). Empty = the key's fallback key(s), then the chain.
 *
 * THIS SLOT DOES NOT WRITE. Every edit is queued into the character sheet's
 * change buffer (`queue`, one key at a time) and leaves with the toolbar's one
 * Save as `PUT /characters/{n}/outfit-imagegen` — a PARTIAL update, so the
 * sections on different tabs never overwrite each other's keys. What is shown
 * is the buffered value over the stored one; a Discard empties the buffer and
 * the stored value shows again.
 *
 * Backed by GET /characters/{n}/outfit-imagegen (record + chains + mesh/hair
 * backends), GET /world/imagegen-options (the enabled image generators, the
 * match preview) and GET /characters/outfit-lora-options (the LoRA choices,
 * scoped to the backend the render resolves to WITH the unsaved globs of the
 * draft — the list follows what is typed, not what was saved).
 */

interface Lora {
  name: string
  strength: number
}

interface MatchChain {
  occasion: string
  label: string
  chain: string[]
}

/** GET /characters/{name}/outfit-imagegen. */
interface StoredOverride {
  [key: string]: unknown
  loras?: Lora[]
  tpose_loras?: Lora[]
  mesh_occasion?: string
  mesh_world_chain?: string[]
  mesh_backends?: string[]
  hair_world_chain?: string[]
  hair_backends?: string[]
  match_chains?: Record<string, MatchChain[]>
}

type GlobKind = 'image' | 'mesh' | 'hair'

interface GlobDef {
  kind: GlobKind
  label: string
  /** Hover text: what the glob steers. */
  tip: string
  placeholder: string
  /** Keys read when this one is empty, in order (occasions.py
   *  char_spec_fallback); then the occasion chain. */
  fallback?: string[]
}

interface LoraDef {
  kind: 'loras'
  label: string
  tip: string
  /** outfit-lora-options target: whose backend the list is scoped to. */
  target: 'render' | 'tpose'
  empty: string
}

/** Every key of the record this slot can show. Labels stay short; the hover
 *  text carries the details. */
const DEFS: Record<string, GlobDef | LoraDef> = {
  workflow: {
    kind: 'image', label: 'Renders', placeholder: 'Flux*',
    tip: 'Tried first for every render of this character that names no backend: photos, Instagram posts, expression and outfit variants, gallery regenerate. Also the fallback of the T-pose and the base-body front.',
  },
  profile_workflow: {
    kind: 'image', label: 'Portrait', placeholder: 'Portrait*',
    tip: 'Tried first for the profile portrait only. Empty = the portrait chain (the Renders glob is NOT used).',
  },
  tpose_workflow: {
    kind: 'image', label: 'T-pose', placeholder: 'TPose*', fallback: ['workflow'],
    tip: 'The T-pose main reference (main mesh input). Empty = the Renders glob (Image tab), then the T-pose chain.',
  },
  tpose_view_workflow: {
    kind: 'image', label: 'T-pose views', placeholder: 'Flux*',
    tip: 'The extra reference views (back, side, face) and the Hair tab\'s haired and hair-only edits. The base-body and outfit view steps fall back to it.',
  },
  base_front_workflow: {
    kind: 'image', label: 'Front', placeholder: 'Qwen*', fallback: ['tpose_workflow', 'workflow'],
    tip: 'The bald A-pose front. Identity comes from the profile picture; an accurate (non-turbo) model is recommended. Empty = the T-pose glob, then the Renders glob, then this step\'s chain.',
  },
  base_view_workflow: {
    kind: 'image', label: 'Back/side views', placeholder: 'Qwen*', fallback: ['tpose_view_workflow'],
    tip: 'The back, left and right views (edits of the front). Empty = the T-pose views glob (Pose tab), then this step\'s chain.',
  },
  outfit_front_workflow: {
    kind: 'image', label: 'Front edit', placeholder: 'Qwen*', fallback: ['tpose_view_workflow'],
    tip: 'The dressed front, an edit of the base front. Empty = the T-pose views glob, then this step\'s chain.',
  },
  outfit_back_draft_workflow: {
    kind: 'image', label: 'Back draft', placeholder: 'Qwen*', fallback: ['tpose_view_workflow'],
    tip: 'Rendered fresh from the dressed front; only its clothing is used. Empty = the T-pose views glob, then this step\'s chain.',
  },
  outfit_back_workflow: {
    kind: 'image', label: 'Back fit', placeholder: 'Qwen*', fallback: ['tpose_view_workflow'],
    tip: 'Edit of the base back view with the draft as second reference; grainy results are caught by a noise check and re-rendered. Empty = the T-pose views glob, then this step\'s chain.',
  },
  outfit_side_draft_workflow: {
    kind: 'image', label: 'Side draft', placeholder: 'Qwen*',
    fallback: ['outfit_back_draft_workflow', 'tpose_view_workflow'],
    tip: 'Rendered fresh from the dressed front in profile; only its clothing is used. Runs only with the world setting Dressed side views. Empty = the Back draft glob, then the T-pose views glob, then this step\'s chain.',
  },
  outfit_side_workflow: {
    kind: 'image', label: 'Side fit', placeholder: 'Qwen*',
    fallback: ['outfit_back_workflow', 'tpose_view_workflow'],
    tip: 'Edit of the base side view with the draft as second reference; grainy or turned results are re-rendered. Runs only with the world setting Dressed side views. Empty = the Back fit glob, then the T-pose views glob, then this step\'s chain.',
  },
  mesh_workflow: {
    kind: 'mesh', label: 'Mesh', placeholder: 'Trellis*',
    tip: 'Tried first for this character\'s 3D mesh (the humanoid or creature mesh chain, whichever its rig selects). Empty = that chain.',
  },
  hair_mesh_workflow: {
    kind: 'hair', label: 'HairDeck cards', placeholder: 'HairDeck*',
    tip: 'Tried first for the hair cards made from one image of the character (Hair method HairDeck). Empty = the hair-cards chain.',
  },
  loras: {
    kind: 'loras', label: 'Character LoRAs', target: 'render', empty: 'None',
    tip: 'Added to this character\'s variant, outfit, T-pose and base-body renders. The choices are the LoRAs of the backend its variant renders resolve to (with the Renders glob as typed).',
  },
  tpose_loras: {
    kind: 'loras', label: 'T-pose LoRAs', target: 'tpose', empty: 'Empty: the character LoRAs apply',
    tip: 'Used INSTEAD of the character LoRAs on every mesh-input render (T-pose, its views, base body, outfit views) — a different backend has its own LoRAs. The choices are the LoRAs of the backend the T-pose resolves to.',
  },
}

// ── shared loads: several sections of one tab read the same record once ──

const recordLoads = new Map<string, Promise<StoredOverride>>()
const backendLoads = new Map<string, Promise<string[]>>()

function cached<T>(cache: Map<string, Promise<T>>, key: string, load: () => Promise<T>): Promise<T> {
  let p = cache.get(key)
  if (!p) {
    p = load()
    // A failed load is not remembered — the next mount asks again.
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return p
}

function loadRecord(character: string, rev: number): Promise<StoredOverride> {
  return cached(recordLoads, `${character}\u0000${rev}`, () =>
    apiGet<StoredOverride>(`/characters/${encodeURIComponent(character)}/outfit-imagegen`))
}

function loadImageBackends(rev: number): Promise<string[]> {
  return cached(backendLoads, String(rev), async () => {
    const opts = await apiGet<{ options?: Array<{ name?: string; category?: string; media?: string }> }>(
      '/world/imagegen-options')
    // Inpaint/upscale targets never take a character's ordinary renders.
    return (opts.options || []).filter((o) => o.name && isGeneratorBackend(o)).map((o) => o.name as string)
  })
}

/** fnmatch-style glob (`*`, `?`, `[set]`, `[!set]`), case-insensitive — the
 *  same matching as the server's routing (fnmatch on lowercased names). */
function globToRegex(glob: string): RegExp {
  let re = ''
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i]
    if (c === '*') re += '.*'
    else if (c === '?') re += '.'
    else if (c === '[') {
      const close = glob.indexOf(']', i + 2)
      if (close < 0) { re += '\\['; continue }
      let set = glob.slice(i + 1, close)
      if (set.startsWith('!')) set = '^' + set.slice(1)
      re += '[' + set.replace(/\\/g, '\\\\') + ']'
      i = close
    } else re += c.replace(/[.+^${}()|\\]/g, '\\$&')
  }
  return new RegExp('^' + re + '$', 'i')
}

function matchNames(glob: string, names: string[]): string[] {
  const p = glob.trim().replace(/^backend:/i, '').trim()
  if (!p) return []
  try {
    const re = globToRegex(p)
    return names.filter((n) => re.test(n))
  } catch {
    return []
  }
}

export function ImagegenOverrideFields({
  character,
  keys,
  draft,
  queue,
  savedSignal,
}: {
  character: string
  /** The record keys this section shows (template `slot_keys`). */
  keys: string[]
  /** The sheet's buffered values of the record, over the stored ones. */
  draft: Record<string, unknown>
  /** Queue ONE key's new value into the sheet's change buffer. */
  queue: (patch: Record<string, unknown>) => void
  /** Bumped by a successful Save — the stored record is read again. */
  savedSignal: number
}) {
  const { t } = useI18n()
  const [stored, setStored] = useState<StoredOverride | null>(null)
  const [backends, setBackends] = useState<string[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setError('')
    Promise.all([loadRecord(character, savedSignal), loadImageBackends(savedSignal)])
      .then(([rec, names]) => {
        if (cancelled) return
        setStored(rec)
        setBackends(names)
      })
      .catch((e) => { if (!cancelled) setError((e as Error).message) })
    return () => { cancelled = true }
  }, [character, savedSignal])

  if (error) return <div className="ga-hint">{t('Failed to load')}: {error}</div>
  if (!stored) return <div className="ga-hint">{t('Loading…')}</div>

  const globValue = (key: string): string =>
    typeof draft[key] === 'string' ? (draft[key] as string) : String(stored[key] ?? '')

  const globKeys = keys.filter((k) => DEFS[k] && DEFS[k].kind !== 'loras')
  const loraKeys = keys.filter((k) => DEFS[k]?.kind === 'loras')

  return (
    <div className="ga-igo">
      {globKeys.map((key) => (
        <GlobRow key={key} fieldKey={key} def={DEFS[key] as GlobDef} value={globValue(key)}
          globValue={globValue} stored={stored} backends={backends}
          onChange={(v) => queue({ [key]: v })} />
      ))}
      {loraKeys.map((key) => (
        <LoraList key={key} character={character} def={DEFS[key] as LoraDef}
          list={Array.isArray(draft[key]) ? (draft[key] as Lora[])
            : Array.isArray(stored[key]) ? (stored[key] as Lora[]) : []}
          draft={draft} savedSignal={savedSignal}
          onChange={(next) => queue({ [key]: next })} />
      ))}
    </div>
  )
}

function GlobRow({ fieldKey, def, value, globValue, stored, backends, onChange }: {
  fieldKey: string
  def: GlobDef
  value: string
  globValue: (key: string) => string
  stored: StoredOverride
  backends: string[]
  onChange: (v: string) => void
}) {
  const { t } = useI18n()
  const label = fieldKey === 'mesh_workflow'
    ? (stored.mesh_occasion === 'mesh_creature' ? t('Mesh (creature)') : t('Mesh (humanoid)'))
    : t(def.label)
  const names = def.kind === 'mesh' ? stored.mesh_backends || []
    : def.kind === 'hair' ? stored.hair_backends || [] : backends

  // One line under the input: what this glob hits, or — empty — what runs
  // instead (the first non-empty fallback glob, else the chain). The full
  // text is the line's hover.
  const chainText = (chain: string[]) =>
    chain.length ? chain.join(' → ') : t('cheapest backend of this kind')
  let status: string
  let tone: 'ok' | 'bad' | 'muted'
  if (value.trim()) {
    const hits = matchNames(value, names)
    status = hits.length ? hits.join(', ') : t('no match')
    tone = hits.length ? 'ok' : 'bad'
  } else {
    tone = 'muted'
    const via = (def.fallback || []).find((k) => globValue(k).trim())
    if (via) {
      status = t('uses {field}: {glob}')
        .replace('{field}', t((DEFS[via] as GlobDef).label)).replace('{glob}', globValue(via).trim())
    } else if (def.kind === 'mesh') {
      status = t('chain') + ': ' + chainText(stored.mesh_world_chain || [])
    } else if (def.kind === 'hair') {
      status = t('chain') + ': ' + chainText(stored.hair_world_chain || [])
    } else {
      const rows = stored.match_chains?.[fieldKey] || []
      const distinct = new Set(rows.map((r) => r.chain.join('\u0000')))
      status = t('chain') + ': ' + (rows.length === 0 ? chainText([])
        : distinct.size === 1 ? chainText(rows[0].chain)
          : rows.map((r) => r.label + ': ' + chainText(r.chain)).join(' · '))
    }
  }

  return (
    <div className="ga-igo-cell">
      <Field label={label} tip={t(def.tip)} compact>
        <div className="ga-igo-control">
          <input className="ga-input" value={value} placeholder={def.placeholder}
            spellCheck={false} onChange={(e) => onChange(e.target.value)} />
          <div className={`ga-igo-status ga-igo-status--${tone}`} title={status}>{status}</div>
        </div>
      </Field>
    </div>
  )
}

function LoraList({ character, def, list, draft, savedSignal, onChange }: {
  character: string
  def: LoraDef
  list: Lora[]
  draft: Record<string, unknown>
  savedSignal: number
  onChange: (next: Lora[]) => void
}) {
  const { t } = useI18n()
  const [options, setOptions] = useState<Array<{ name: string; missing?: boolean }>>([])
  const [addName, setAddName] = useState('')

  // The choices follow the backend the render resolves to WITH the unsaved
  // globs (render: workflow; T-pose: tpose_workflow, falling back to
  // workflow) — debounced, typing a glob is many edits.
  const draftWorkflow = typeof draft.workflow === 'string' ? draft.workflow : undefined
  const draftTpose = typeof draft.tpose_workflow === 'string' ? draft.tpose_workflow : undefined
  const query = useMemo(() => {
    const q = new URLSearchParams({ character_name: character })
    if (def.target === 'tpose') q.set('target', 'tpose')
    if (draftWorkflow !== undefined) q.set('workflow', draftWorkflow.trim())
    if (def.target === 'tpose' && draftTpose !== undefined) q.set('tpose_workflow', draftTpose.trim())
    return q.toString()
  }, [character, def.target, draftWorkflow, draftTpose])

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(() => {
      apiGet<{ loras?: Array<{ name: string; missing?: boolean }> }>(`/characters/outfit-lora-options?${query}`)
        .then((r) => {
          if (!cancelled) setOptions((r.loras || []).filter((l) => l.name && l.name !== 'None'))
        })
        .catch(() => { /* keep the previous list */ })
    }, 350)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [query, savedSignal])

  const offered = options.filter((l) => !list.some((x) => x.name === l.name))

  return (
    <div className="ga-igo-loras">
      <Field label={t(def.label)} tip={t(def.tip)} compact>
        <div className="ga-igo-lora-body">
          {list.length === 0 ? <div className="ga-igo-status ga-igo-status--muted">{t(def.empty)}</div> : (
            list.map((l, i) => (
              <div className="ga-igo-lora-row" key={l.name}>
                <span className="ga-igo-lora-name" title={l.name}>{l.name}</span>
                <input className="ga-input ga-igo-lora-strength" type="number" step="0.05"
                  title={t('Strength')} value={l.strength}
                  onChange={(e) => {
                    const strength = parseFloat(e.target.value)
                    onChange(list.map((x, j) => (j === i ? { ...x, strength: isNaN(strength) ? 1 : strength } : x)))
                  }} />
                <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" title={t('Remove')}
                  aria-label={t('Remove')} onClick={() => onChange(list.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))
          )}
          <div className="ga-igo-lora-row">
            <select className="ga-input ga-igo-lora-pick" value={addName} onChange={(e) => setAddName(e.target.value)}>
              <option value="">{offered.length ? `— ${t('pick a LoRA')} —` : `— ${t('no LoRAs for this backend')} —`}</option>
              {offered.map((l) => (
                <option key={l.name} value={l.name}>
                  {l.name}{l.missing ? ` ${t('(missing)')}` : ''}
                </option>
              ))}
            </select>
            <button type="button" className="ga-btn ga-btn-sm" disabled={!addName}
              onClick={() => {
                if (!addName) return
                onChange([...list, { name: addName, strength: 1 }])
                setAddName('')
              }}>
              {t('Add')}
            </button>
          </div>
        </div>
      </Field>
    </div>
  )
}
