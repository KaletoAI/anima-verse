export type Category =
  | 'outfit_piece'
  | 'key'
  | 'tool'
  | 'consumable'
  | 'evidence'
  | 'gift'
  | 'spell'
  | 'quest'
  | 'decoration'
export type Rarity = 'common' | 'rare' | 'unique'

export interface OutfitPieceMeta {
  outfit_types?: string[]
  slots?: string[]
  covers?: string[]
  partially_covers?: string[]
}

export interface Item {
  id: string
  name?: string
  description?: string
  category?: Category
  rarity?: Rarity
  stackable?: boolean
  transferable?: boolean
  consumable?: boolean
  image_prompt?: string
  prompt_fragment?: string
  outfit_piece?: OutfitPieceMeta
  // Effects stored as a dict on the server (same as activities). The form
  // edits a "key: value" text representation; we (de)serialize on edit.
  effects?: Record<string, number | string> | string
  apply_condition?: string
  condition_duration?: number
  has_image?: boolean
  image?: string
  image_meta?: { backend?: string; backend_type?: string; model?: string }
  _shared?: boolean
  // Spell / magic / tracker / evidence fields. The spell-section editor
  // (rendered for category=spell) reads/writes them via `extras`; for
  // other categories they are passed through untouched on save.
  incantation?: string
  spell_mode?: string
  clone_item_id?: string
  success_chance?: number
  copy_on_give?: boolean
  success_text?: string
  fail_text?: string
  cast_activity?: string
  anchor_item_id?: string
  teleport_subject?: string
  tracks_character?: string
  reveals_secret?: string
}

export interface Owner {
  character: string
  quantity: number
  equipped: boolean
  obtained_from?: string
}

export interface DraftItem {
  id: string
  name: string
  description: string
  category: Category
  rarity: Rarity
  stackable: boolean
  transferable: boolean
  consumable: boolean
  image_prompt: string
  prompt_fragment: string
  outfit_types: string[]
  slots: string[]
  covers: string[]
  partially_covers: string[]
  effects: string
  apply_condition: string
  condition_duration: number
  // Round-trip storage for the magic / tracker / evidence fields. We
  // don't show editors for them yet but preserve whatever the server
  // returns so saving doesn't strip them.
  extras: Record<string, unknown>
  isNew: boolean
  // Where this item currently lives — drives the Move-button label.
  // Carried on the draft (not looked up against the list) so it stays
  // correct after save reloads & matches what the server just returned.
  shared: boolean
}

export interface ConditionOption {
  name: string
  label?: string
  icon?: string
}

// apply_condition + condition_duration_hours live INSIDE the effects
// dict on the server (see app/models/inventory.py:1303). We pull them
// out so the form can render them as discrete fields, and re-embed on
// save. Without this round-trip neither value persists across reloads.
const CONDITION_KEYS = new Set(['apply_condition', 'condition_duration_hours'])

export function effectsToText(eff: Item['effects']): string {
  if (!eff) return ''
  if (typeof eff === 'string') return eff
  return Object.entries(eff)
    .filter(([k]) => !CONDITION_KEYS.has(k))
    .map(([k, v]) => `${k}: ${v}`)
    .join('\n')
}

export function textToEffects(text: string): Record<string, number | string> {
  const out: Record<string, number | string> = {}
  for (const line of text.split('\n')) {
    const m = line.match(/^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+?)\s*$/)
    if (!m) continue
    const raw = m[2]
    const num = Number(raw)
    out[m[1]] = Number.isFinite(num) && /^[+-]?\d+(?:\.\d+)?$/.test(raw) ? num : raw
  }
  return out
}

export function extractConditionFromEffects(eff: Item['effects']): {
  apply_condition: string
  condition_duration: number
} {
  if (!eff || typeof eff === 'string') {
    return { apply_condition: '', condition_duration: 2 }
  }
  const cond = String(eff.apply_condition ?? '').trim()
  const durRaw = eff.condition_duration_hours
  const dur = Number(durRaw)
  return {
    apply_condition: cond,
    condition_duration: Number.isFinite(dur) && dur > 0 ? Math.floor(dur) : 2,
  }
}

export const EXTRA_KEYS = [
  'incantation',
  'spell_mode',
  'clone_item_id',
  'success_chance',
  'copy_on_give',
  'success_text',
  'fail_text',
  'cast_activity',
  'anchor_item_id',
  'teleport_subject',
  'tracks_character',
  'reveals_secret',
] as const

export const CATEGORIES: Category[] = [
  'outfit_piece',
  'key',
  'tool',
  'consumable',
  'evidence',
  'gift',
  'spell',
  'quest',
  'decoration',
]

export const RARITIES: Rarity[] = ['common', 'rare', 'unique']

export const VALID_PIECE_SLOTS = [
  'head',
  'neck',
  'outer',
  'top',
  'underwear_top',
  'bottom',
  'underwear_bottom',
  'legs',
  'feet',
]

export const EMPTY_DRAFT: DraftItem = {
  id: '',
  name: '',
  description: '',
  category: 'tool',
  rarity: 'common',
  stackable: false,
  transferable: true,
  consumable: false,
  image_prompt: '',
  prompt_fragment: '',
  outfit_types: [],
  slots: [],
  covers: [],
  partially_covers: [],
  effects: '',
  apply_condition: '',
  condition_duration: 2,
  extras: {},
  isNew: true,
  shared: false,
}

export function itemToDraft(it: Item): DraftItem {
  const op = it.outfit_piece || {}
  const extras: Record<string, unknown> = {}
  const itAny = it as unknown as Record<string, unknown>
  for (const k of EXTRA_KEYS) {
    const v = itAny[k]
    if (v !== undefined && v !== null && v !== '') extras[k] = v
  }
  return {
    id: it.id,
    name: it.name || '',
    description: it.description || '',
    category: (it.category || 'tool') as Category,
    rarity: (it.rarity || 'common') as Rarity,
    stackable: !!it.stackable,
    transferable: it.transferable !== false,
    consumable: !!it.consumable,
    image_prompt: it.image_prompt || '',
    prompt_fragment: it.prompt_fragment || '',
    outfit_types: [...(op.outfit_types || [])],
    slots: [...(op.slots || [])],
    covers: [...(op.covers || [])],
    partially_covers: [...(op.partially_covers || [])],
    effects: effectsToText(it.effects),
    ...extractConditionFromEffects(it.effects),
    extras,
    isNew: false,
    shared: !!it._shared,
  }
}

export function draftToBody(d: DraftItem): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: d.name.trim(),
    description: d.description,
    category: d.category,
    rarity: d.rarity,
    stackable: d.stackable,
    transferable: d.transferable,
    consumable: d.consumable,
    image_prompt: d.image_prompt,
    prompt_fragment: d.prompt_fragment,
  }
  // Only send the ID on create — the backend rejects ID updates.
  if (d.isNew && d.id.trim()) {
    body.id = d.id.trim()
  }
  if (d.category === 'outfit_piece') {
    body.outfit_piece = {
      outfit_types: d.outfit_types,
      slots: d.slots,
      covers: d.covers,
      partially_covers: d.partially_covers,
    }
  }
  // "Effect on consume / cast" section: consumables AND spells write
  // effects. apply_condition + condition_duration_hours live INSIDE the
  // effects dict (server reads them from there in inventory.py:1303),
  // so we embed them rather than sending them at the top level.
  if (d.consumable || d.category === 'spell') {
    const eff = textToEffects(d.effects)
    if (d.apply_condition) {
      eff.apply_condition = d.apply_condition
      if (d.condition_duration > 0) {
        eff.condition_duration_hours = d.condition_duration
      }
    }
    body.effects = eff
  }
  // Pass-through magic / tracker / evidence fields so editing a spell
  // item doesn't strip its incantation / spell_mode / etc.
  for (const k of EXTRA_KEYS) {
    if (d.extras[k] !== undefined && d.extras[k] !== null && d.extras[k] !== '') {
      body[k] = d.extras[k]
    }
  }
  return body
}
