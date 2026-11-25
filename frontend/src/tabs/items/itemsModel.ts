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
  | 'document'
  // Mesh-only item worn through equipped_mesh_pieces (hair as its own mesh).
  | 'garment'
export type Rarity = 'common' | 'rare' | 'unique'

export interface OutfitPieceMeta {
  outfit_types?: string[]
  slots?: string[]
  covers?: string[]
  motion_damping?: number
  partially_covers?: string[]
  // How the piece reaches the 3D figure: own_mesh / shell / template / accessory / in_body (absent = the default, in the body).
  mesh_mode?: string
  // Can be worn open (spec 2026-11-12 Addendum A): its wearers get a Closed / Open toggle.
  closable?: boolean
  exposed_detail?: boolean
  // Leaves the body free below (skirt, dress, kilt): never blocks a contact clip (contact_clothing).
  open_below?: boolean
  // How much the piece carries the body under it in 3D (0..1); absent = the
  // slot default a package declares.
  lift?: number
  /** Accessory description (`accessory_spec`); design G: `kind: 'charm'` is a part item, a necklace / belt links
   *  parts (`pendant` / `buckle` / `charms`). */
  jewellery?: Jewellery | null
}

/** The stored accessory description, as far as the Items tab reads it. */
export interface Jewellery {
  kind?: string
  pendant?: PartLink | null
  buckle?: PartLink | null
  charms?: CharmLink[]
  charm?: { size_mm?: number; mount?: string; flip?: boolean }
  [key: string]: unknown
}

export interface PartLink { item: string; size_mm?: number; gem_color?: string }

export type CharmAt = 'front' | 'left_hip' | 'right_hip' | number

export interface CharmLink { item: string; at: CharmAt; mount?: 'flat' | 'hang'; drop_cm: number; size_mm?: number }

/** One link of a host, in the server's order (`accessory_spec.links`): the buckle / pendant first, then the charms.
 *  `size_mm` / `mount` null = the part's own. */
export interface PartLinkRow {
  role: 'buckle' | 'pendant' | 'charm'
  index: number
  item: string
  size_mm: number | null
  at_deg: number
  mount: string | null
  drop_cm: number
}

export interface ItemProperties {
  stat_bonuses?: Record<string, number>
  bonus_when?: 'equipped' | 'carried'
  [key: string]: unknown
}

export interface Item {
  properties?: ItemProperties
  id: string
  owner?: string
  pages_source?: string
  portable?: boolean
  name?: string
  description?: string
  category?: Category
  rarity?: Rarity
  stackable?: boolean
  transferable?: boolean
  consumable?: boolean
  image_prompt?: string
  prompt_fragment?: string
  /** Outfit pieces only: the optional back description (back and side renders); absent = the front text. */
  prompt_fragment_back?: string
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
  properties: ItemProperties
  bonus_rows: { stat: string; amount: number }[]
  bonus_when: 'equipped' | 'carried'
  id: string
  owner: string
  pages_source: string
  portable: boolean
  name: string
  description: string
  category: Category
  rarity: Rarity
  stackable: boolean
  transferable: boolean
  consumable: boolean
  image_prompt: string
  prompt_fragment: string
  /** '' = none: back and side renders quote the front text (`prompt_fragment`). */
  prompt_fragment_back: string
  outfit_types: string[]
  slots: string[]
  covers: string[]
  motion_damping: number
  partially_covers: string[]
  /** '' = not stored (the piece follows the default, in the body). Shown read-only: the mode is set in a
   *  wearer's Wardrobe, and draftToBody never sends it (`inventory.update_item` keeps the stored one), so a
   *  form opened before a Wardrobe change cannot overwrite it. */
  mesh_mode: string
  /** "Can be worn open" — shown read-only like `mesh_mode` and for the same reason never sent by draftToBody
   *  (`inventory.update_item` keeps the stored flag when the update does not name it): set in a wearer's
   *  Wardrobe, a form opened before that change cannot overwrite it. */
  closable: boolean
  exposed_detail: boolean
  /** "Open below": a skirt, a dress or a kilt — never blocks a contact clip (`outfit_piece.open_below`). */
  open_below: boolean
  lift: number | null
  /** The stored `outfit_piece.jewellery` (null: none). Sent back only for a part (`is_part`) or after its links were
   *  edited here (`jewellery_dirty`) — an untouched form never overwrites a change made in a wearer's Wardrobe. */
  jewellery: Jewellery | null
  jewellery_dirty: boolean
  /** A part item (design G): a buckle, pendant or charm worn through its chain or belt — no slot. */
  is_part: boolean
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

// Spell-only extras: only meaningful (and only persisted by the server) on
// category "spell". Sending them for other categories turned a copied spell
// into a consumable that still cast/displayed as a spell.
export const SPELL_EXTRA_KEYS = [
  'cost',
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
] as const

export const EXTRA_KEYS = [
  ...SPELL_EXTRA_KEYS,
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
  'document',
  'garment',
]

export const RARITIES: Rarity[] = ['common', 'rare', 'unique']

export const VALID_PIECE_SLOTS = [
  'head',
  'face',
  'neck',
  'outer',
  'top',
  'underwear_top',
  'bottom',
  'underwear_bottom',
  'legs',
  'feet',
  'hands',
]

export const EMPTY_DRAFT: DraftItem = {
  properties: {},
  bonus_rows: [],
  bonus_when: 'equipped',
  id: '',
  owner: '',
  pages_source: '',
  portable: true,
  name: '',
  description: '',
  category: 'tool',
  rarity: 'common',
  stackable: false,
  transferable: true,
  consumable: false,
  image_prompt: '',
  prompt_fragment: '',
  prompt_fragment_back: '',
  outfit_types: [],
  slots: [],
  covers: [],
  motion_damping: 1,
  partially_covers: [],
  mesh_mode: '',
  closable: false,
  exposed_detail: false,
  open_below: false,
  lift: null,
  jewellery: null,
  jewellery_dirty: false,
  is_part: false,
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
    properties: { ...it.properties },
    bonus_rows: Object.entries(it.properties?.stat_bonuses || {}).map(([stat, amount]) => ({ stat, amount })),
    bonus_when: it.properties?.bonus_when || 'equipped',
    id: it.id,
    owner: it.owner || '',
    pages_source: it.pages_source || '',
    portable: it.portable !== false,
    name: it.name || '',
    description: it.description || '',
    category: (it.category || 'tool') as Category,
    rarity: (it.rarity || 'common') as Rarity,
    stackable: !!it.stackable,
    transferable: it.transferable !== false,
    consumable: !!it.consumable,
    image_prompt: it.image_prompt || '',
    prompt_fragment: it.prompt_fragment || '',
    prompt_fragment_back: it.prompt_fragment_back || '',
    outfit_types: [...(op.outfit_types || [])],
    slots: [...(op.slots || [])],
    covers: [...(op.covers || [])],
    motion_damping: op.motion_damping ?? 1,
    partially_covers: [...(op.partially_covers || [])],
    mesh_mode: typeof op.mesh_mode === 'string' ? op.mesh_mode : '',
    closable: op.closable === true,
    exposed_detail: op.exposed_detail === true,
    open_below: op.open_below === true,
    lift: typeof op.lift === 'number' ? op.lift : null,
    jewellery: op.jewellery && typeof op.jewellery === 'object' ? { ...op.jewellery } : null,
    jewellery_dirty: false,
    is_part: op.jewellery?.kind === 'charm',
    effects: effectsToText(it.effects),
    ...extractConditionFromEffects(it.effects),
    extras,
    isNew: false,
    shared: !!it._shared,
  }
}

export function draftToBody(d: DraftItem): Record<string, unknown> {
  const body: Record<string, unknown> = {
    properties: {
      ...d.properties,
      stat_bonuses: Object.fromEntries(d.bonus_rows.filter(row => row.stat).map(row => [row.stat, row.amount])),
      bonus_when: d.bonus_when,
    },
    owner: d.owner.trim(),
    pages_source: d.pages_source.trim(),
    portable: d.portable,
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
    // '' clears it (the server drops an empty back text).
    body.prompt_fragment_back = d.prompt_fragment_back.trim()
    body.outfit_piece = {
      outfit_types: d.outfit_types,
      slots: d.slots,
      covers: d.covers,
      motion_damping: d.motion_damping,
      partially_covers: d.partially_covers,
      exposed_detail: d.exposed_detail,
      open_below: d.open_below,
      // null resets the piece to the slot default.
      lift: d.lift,
    }
    const piece = body.outfit_piece as Record<string, unknown>
    if (d.is_part) {
      // A part has no slot; its kind stays 'charm' (the server forces both too).
      piece.slots = []
      piece.covers = []
      piece.partially_covers = []
      piece.jewellery = { ...(d.jewellery || {}), kind: 'charm' }
    } else if (d.jewellery_dirty && d.jewellery) {
      piece.jewellery = d.jewellery
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
  // item doesn't strip its incantation / spell_mode / etc. Spell-only
  // keys stay home unless the item IS a spell — a draft copied from a
  // spell (or re-categorized away from spell) must not carry them.
  const spellOnly = new Set<string>(SPELL_EXTRA_KEYS)
  for (const k of EXTRA_KEYS) {
    if (spellOnly.has(k) && d.category !== 'spell') continue
    if (d.extras[k] !== undefined && d.extras[k] !== null && d.extras[k] !== '') {
      body[k] = d.extras[k]
    }
  }
  return body
}

// ---------------------------------------------------------------------------------------------------------------------
// Part links (design G) — the same rules as the server's `accessory_spec` (links, `_at`, MAX_CHARMS)
// ---------------------------------------------------------------------------------------------------------------------

export const MAX_CHARMS = 6

const AT_DEG: Record<string, number> = { front: 0, left_hip: 90, right_hip: -90 }

/** A charm's place in degrees (+90 = the body's left); a number is wrapped to [−180, 180). */
export function atDeg(at: CharmAt): number {
  if (typeof at === 'string') return AT_DEG[at] ?? 0
  return ((((at + 180) % 360) + 360) % 360) - 180
}

/** Whether an item is a part item (`outfit_piece.jewellery.kind === 'charm'`). */
export function isPartItem(it: Pick<Item, 'outfit_piece'>): boolean {
  return it.outfit_piece?.jewellery?.kind === 'charm'
}

/** The links of a host draft, as the server lists them (`accessory_spec.links`). */
export function partLinksOf(d: Pick<DraftItem, 'jewellery'>): PartLinkRow[] {
  const j = d.jewellery
  if (!j) return []
  const out: PartLinkRow[] = []
  const head = j.kind === 'belt' ? 'buckle' : j.kind === 'necklace' ? 'pendant' : null
  const link = head ? j[head] : null
  if (head && link && link.item) {
    out.push({ role: head, index: 0, item: link.item, size_mm: link.size_mm ?? null, at_deg: 0, mount: null, drop_cm: 0 })
  }
  if (j.kind === 'belt') {
    (j.charms || []).forEach((c, i) => out.push({
      role: 'charm', index: i, item: c.item, size_mm: c.size_mm ?? null, at_deg: atDeg(c.at ?? 'front'),
      mount: c.mount ?? null, drop_cm: Number(c.drop_cm) || 0,
    }))
  }
  return out
}

function withJewellery<D extends Pick<DraftItem, 'jewellery' | 'jewellery_dirty'>>(d: D, j: Jewellery): D {
  return { ...d, jewellery: j, jewellery_dirty: true }
}

/** The buckle / pendant link set to `item` (a new part brings its own size) or removed (`null`). */
export function withLink<D extends Pick<DraftItem, 'jewellery' | 'jewellery_dirty'>>(
  d: D, role: 'buckle' | 'pendant', item: string | null): D {
  return withJewellery(d, { ...(d.jewellery || {}), [role]: item ? { item } : null })
}

/** The size override of the buckle / pendant link (null: the part's own). */
export function withLinkSize<D extends Pick<DraftItem, 'jewellery' | 'jewellery_dirty'>>(
  d: D, role: 'buckle' | 'pendant', sizeMm: number | null): D {
  const link = d.jewellery?.[role]
  if (!link) return d
  const next: PartLink = { ...link }
  if (sizeMm == null) delete next.size_mm
  else next.size_mm = sizeMm
  return withJewellery(d, { ...(d.jewellery || {}), [role]: next })
}

/** A belt's charm appended (default: at the front, flat on the band); null when the host is no belt or carries
 *  MAX_CHARMS already. */
export function withCharm<D extends Pick<DraftItem, 'jewellery' | 'jewellery_dirty'>>(
  d: D, link: Partial<CharmLink> & { item: string }): D | null {
  const j = d.jewellery
  if (!j || j.kind !== 'belt') return null
  const charms = j.charms || []
  if (charms.length >= MAX_CHARMS) return null
  const { item, ...rest } = link
  return withJewellery(d, { ...j, charms: [...charms, { item, at: 'front', drop_cm: 0, ...rest }] })
}

export function withoutCharm<D extends Pick<DraftItem, 'jewellery' | 'jewellery_dirty'>>(d: D, index: number): D {
  const charms = (d.jewellery?.charms || []).filter((_, i) => i !== index)
  return withJewellery(d, { ...(d.jewellery || {}), charms })
}

export function updateCharm<D extends Pick<DraftItem, 'jewellery' | 'jewellery_dirty'>>(
  d: D, index: number, patch: Partial<CharmLink>): D {
  const charms = (d.jewellery?.charms || []).map((c, i) => (i === index ? { ...c, ...patch } : c))
  return withJewellery(d, { ...(d.jewellery || {}), charms })
}

/** One part the pickers offer (`part_options` of the figure route, or the item list). */
export interface PartOption { id: string; name: string; image_url: string; state: string }

/** A link's line from the Wardrobe (`accessory_build.part_rows` + `host_mentions`). */
export interface PartRowInfo {
  role: string
  index: number
  item: string
  state: string
  reason: string
  on_figure?: boolean
  host_mentions?: boolean
  metrics?: { size_mm?: number; depth_mm?: number } | null
}

export const PART_STATE_LABELS: Record<string, string> = {
  ready: 'Mesh built', running: 'Mesh building', missing: 'Mesh not built', refused: 'Mesh refused',
  failed: 'Mesh failed', no_image: 'No item image', gone: 'Part item gone',
}
export const PART_STATE_COLOR: Record<string, string> = {
  ready: '#3fb950', running: '#58a6ff', missing: '#d29922', refused: '#f85149', failed: '#f85149',
  no_image: '#8b949e', gone: '#f85149',
}
const ITEMS_SELECT_KEY = 'ga:items:select'

/** Opens the Items tab with ``itemId`` selected (the tab reads the key once on load). */
export function openInItems(itemId: string) {
  try { window.sessionStorage.setItem(ITEMS_SELECT_KEY, itemId) } catch { /* private mode: the tab opens unselected */ }
  window.location.hash = '#/items'
}

/** The item id the Items tab should select on load (read once). */
export function takeItemsSelection(): string {
  try {
    const id = window.sessionStorage.getItem(ITEMS_SELECT_KEY) || ''
    window.sessionStorage.removeItem(ITEMS_SELECT_KEY)
    return id
  } catch {
    return ''
  }
}
