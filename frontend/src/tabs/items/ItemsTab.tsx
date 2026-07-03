import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { loadCharacters, type CharacterRef } from '../../lib/refs'
import { STYLE_HINT_OPTIONS } from '../../lib/styleHints'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ListHeader } from '../../components/ListHeader'
import { ExportButton, ImportButton, PublishButton } from '../../components/ImportExport'
import { Silhouette } from '../../components/Silhouette'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'
import { ItemForm } from './ItemForm'
import {
  CATEGORIES,
  EMPTY_DRAFT,
  RARITIES,
  VALID_PIECE_SLOTS,
  draftToBody,
  itemToDraft,
  type Category,
  type ConditionOption,
  type DraftItem,
  type Item,
  type Owner,
  type Rarity,
} from './itemsModel'

interface ItemRowProps {
  item: Item
  isActive: boolean
  onSelect: (item: Item) => void
}

const ItemRow = memo(function ItemRow({ item, isActive, onSelect }: ItemRowProps) {
  return (
    <li>
      <button
        type="button"
        className={`ga-list-row ga-cat-${item.category || 'tool'}${isActive ? ' is-active' : ''}`}
        onClick={() => onSelect(item)}
      >
        <span className="ga-list-row-main">
          <strong>{item.name || item.id}</strong>
          <span className="ga-list-row-sub">— {item.category || 'tool'}</span>
        </span>
        <span className="ga-source ga-source-shared" style={{ visibility: item._shared ? 'visible' : 'hidden' }}>
          shared
        </span>
      </button>
    </li>
  )
})

export function ItemsTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [items, setItems] = useState<Item[] | null>(null)
  const [draft, setDraft] = useState<DraftItem | null>(null)
  const [search, setSearch] = useState('')
  const [filterCategory, setFilterCategory] = useState<Category | ''>('')
  const [filterRarity, setFilterRarity] = useState<Rarity | ''>('')
  const [filterScope, setFilterScope] = useState<'' | 'world' | 'shared'>('')
  // Slot filter, only relevant when filterCategory === 'outfit_piece'.
  const [filterSlot, setFilterSlot] = useState('')
  // '' = all, '__none__' = owned by nobody, otherwise a character name.
  const [filterOwner, setFilterOwner] = useState('')
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [owners, setOwners] = useState<Owner[]>([])
  const [ownership, setOwnership] = useState<Record<string, string[]>>({})
  const [outfitTypeOptions, setOutfitTypeOptions] = useState<string[]>([])
  const [conditionOptions, setConditionOptions] = useState<ConditionOption[]>([])
  const [genDialogOpen, setGenDialogOpen] = useState(false)

  const loadOwnership = useCallback(async () => {
    try {
      const d = await apiGet<{ ownership?: Record<string, string[]> }>('/inventory/ownership')
      setOwnership(d.ownership || {})
    } catch {
      setOwnership({})
    }
  }, [])

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ items?: Item[] }>('/inventory/items?include_shared=1')
      setItems(data.items || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => {
    reload()
    loadOwnership()
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
    // Step 7 (May 2026, plan-outfit-system-rethink.md §1): outfit types
    // reduced to the short style_hint vocabulary. Items keep the tags so the
    // ChangeOutfit skill can still match "show me a business piece".
    setOutfitTypeOptions([...STYLE_HINT_OPTIONS])
    apiGet<{ conditions?: ConditionOption[] }>('/world/conditions/list')
      .then((d) => setConditionOptions(d.conditions || []))
      .catch(() => setConditionOptions([]))
  }, [reload, loadOwnership])

  const loadOwners = useCallback(async (id: string) => {
    if (!id) {
      setOwners([])
      return
    }
    try {
      const d = await apiGet<{ owners?: Owner[] }>(`/inventory/items/${encodeURIComponent(id)}/owners`)
      setOwners(d.owners || [])
    } catch {
      setOwners([])
    }
  }, [])

  const filtered = useMemo(() => {
    if (!items) return []
    const q = search.trim().toLowerCase()
    return items
      .filter((it) => {
        if (filterCategory && it.category !== filterCategory) return false
        if (filterRarity && it.rarity !== filterRarity) return false
        if (filterScope === 'shared' && !it._shared) return false
        if (filterScope === 'world' && it._shared) return false
        if (filterCategory === 'outfit_piece' && filterSlot && !(it.outfit_piece?.slots || []).includes(filterSlot)) return false
        if (filterOwner) {
          const ownedBy = ownership[it.id] || []
          if (filterOwner === '__none__') {
            if (ownedBy.length > 0) return false
          } else if (!ownedBy.includes(filterOwner)) {
            return false
          }
        }
        if (q && !((it.name || '').toLowerCase().includes(q) || (it.description || '').toLowerCase().includes(q))) {
          return false
        }
        return true
      })
      .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
  }, [items, search, filterCategory, filterRarity, filterScope, filterSlot, filterOwner, ownership])

  // Derive the used slots from the existing outfit pieces, in canonical
  // order (head→feet) — like the slot filter in the player inventory.
  const slotOptions = useMemo(() => {
    if (!items) return []
    const used = new Set<string>()
    items.forEach((it) => {
      if (it.category === 'outfit_piece') (it.outfit_piece?.slots || []).forEach((s) => used.add(s))
    })
    return VALID_PIECE_SLOTS.filter((s) => used.has(s))
  }, [items])

  const newItem = useCallback(() => {
    setDraft({ ...EMPTY_DRAFT })
    setOwners([])
  }, [])

  const editItem = useCallback(
    (it: Item) => {
      setDraft(itemToDraft(it))
      loadOwners(it.id)
    },
    [loadOwners],
  )

  const copyItem = useCallback(() => {
    setDraft((prev) =>
      prev ? { ...prev, id: '', name: `${prev.name} (copy)`.trim(), isNew: true } : prev,
    )
    setOwners([])
  }, [])

  const update = useCallback(<K extends keyof DraftItem>(key: K, value: DraftItem[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }, [])

  // Writes a value into the extras dict (spell/tracker/evidence fields).
  // Empty values are deleted so draftToBody doesn't post the key along.
  const updateExtra = useCallback((key: string, value: unknown) => {
    setDraft((prev) => {
      if (!prev) return prev
      const extras = { ...prev.extras }
      if (value === '' || value === null || value === undefined) delete extras[key]
      else extras[key] = value
      return { ...prev, extras }
    })
  }, [])

  const toggleListItem = useCallback(
    (key: 'outfit_types' | 'slots' | 'covers' | 'partially_covers', value: string) => {
      if (!value) return
      setDraft((prev) => {
        if (!prev) return prev
        const set = new Set(prev[key])
        if (set.has(value)) set.delete(value)
        else set.add(value)
        return { ...prev, [key]: Array.from(set) }
      })
    },
    [],
  )

  // Click-to-cycle on the silhouette: empty → slot → cover → partial → empty.
  // Each click moves the slot one step around the loop, so the user can
  // mark all four states without juggling the three tag pickers.
  const cycleSlot = useCallback((slot: string) => {
    setDraft((prev) => {
      if (!prev) return prev
      const inSlots = prev.slots.includes(slot)
      const inCovers = prev.covers.includes(slot)
      const inPartial = prev.partially_covers.includes(slot)
      const dropFrom = (list: string[]) => list.filter((s) => s !== slot)
      if (!inSlots && !inCovers && !inPartial) {
        return { ...prev, slots: [...prev.slots, slot] }
      }
      if (inSlots) {
        return { ...prev, slots: dropFrom(prev.slots), covers: [...prev.covers, slot] }
      }
      if (inCovers) {
        return { ...prev, covers: dropFrom(prev.covers), partially_covers: [...prev.partially_covers, slot] }
      }
      // inPartial → empty
      return { ...prev, partially_covers: dropFrom(prev.partially_covers) }
    })
  }, [])

  const save = useCallback(async () => {
    if (!draft) return
    if (!draft.name.trim()) {
      toast(t('Name required'), 'error')
      return
    }
    try {
      const body = draftToBody(draft)
      let saved: Item | undefined
      if (draft.isNew) {
        const r = await apiPost<{ item?: Item }>('/inventory/items', body)
        saved = r.item
        toast(t('Item created'))
      } else {
        const r = await apiPut<{ item?: Item }>(`/inventory/items/${encodeURIComponent(draft.id)}`, body)
        saved = r.item
        toast(t('Item saved'))
      }
      await reload()
      // Keep the detail panel open on the just-saved item. The server
      // returns the persisted record; if for any reason it doesn't, fall
      // back to flipping the draft to non-new state instead of closing.
      if (saved) {
        setDraft(itemToDraft(saved))
        if (draft.isNew) loadOwners(saved.id)
      } else {
        setDraft((prev) => (prev ? { ...prev, isNew: false } : prev))
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [draft, loadOwners, reload, t, toast])

  const remove = useCallback(async () => {
    if (!draft || draft.isNew) return
    if (!window.confirm(t('Delete item "{name}"?').replace('{name}', draft.name || draft.id))) return
    try {
      await apiDelete(`/inventory/items/${encodeURIComponent(draft.id)}`)
      toast(t('Deleted'))
      await reload()
      setDraft(null)
      setOwners([])
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [draft, reload, t, toast])

  const move = useCallback(
    async (target: 'world' | 'shared') => {
      if (!draft || draft.isNew) return
      const path =
        target === 'shared'
          ? `/inventory/items/${encodeURIComponent(draft.id)}/move-to-shared`
          : `/inventory/items/${encodeURIComponent(draft.id)}/move-to-world`
      try {
        await apiPost(path, {})
        toast(target === 'shared' ? t('Moved to shared') : t('Moved to world'))
        await reload()
        setDraft(null)
        setOwners([])
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [draft, reload, t, toast],
  )

  // Build the dialog's default prompt — mirrors the server fallback chain
  // in generate_item_image_sync: image_prompt > prompt_fragment > name,
  // with the same product-photography suffix the server appends.
  const buildItemPrompt = useCallback((d: DraftItem): string => {
    const base =
      (d.image_prompt || '').trim() ||
      (d.prompt_fragment || '').trim() ||
      (d.name || '').trim() ||
      d.id
    return `${base}, isolated object on green background, product photography, sharp focus, realistic`
  }, [])

  // Submit handler the ImageGenDialog calls on Generate. The dialog
  // payload uses LoRA name+strength; the items endpoint expects
  // {file, strength}, so map across.
  const submitGenerateImage = useCallback(
    async (payload: ImageGenSubmit) => {
      if (!draft || draft.isNew) return
      const body: Record<string, unknown> = { prompt: payload.prompt }
      if (payload.backend) body.backend = payload.backend
      if (payload.loras && payload.loras.length) {
        body.loras = payload.loras.map((l) => ({ file: l.name, strength: l.strength }))
      }
      if (payload.negative_prompt) body.negative_prompt = payload.negative_prompt
      try {
        await apiPost(`/inventory/items/${encodeURIComponent(draft.id)}/generate-image`, body)
        toast(t('Image queued'))
        // The endpoint enqueues in a background thread; refresh shortly so
        // the new image + caption meta have a chance to land.
        window.setTimeout(reload, 1500)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        throw e
      }
    },
    [draft, reload, t, toast],
  )

  const addOwner = useCallback(
    async (characterName: string, qty: number) => {
      if (!draft || draft.isNew || !characterName) return
      try {
        await apiPost(`/inventory/characters/${encodeURIComponent(characterName)}`, {
          item_id: draft.id,
          quantity: qty,
          obtained_method: 'manual',
        })
        toast(t('Given'))
        loadOwners(draft.id)
        loadOwnership()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [draft, loadOwners, loadOwnership, t, toast],
  )

  const removeOwner = useCallback(
    async (characterName: string) => {
      if (!draft || draft.isNew) return
      try {
        await apiDelete(`/inventory/characters/${encodeURIComponent(characterName)}/${encodeURIComponent(draft.id)}`)
        toast(t('Removed'))
        loadOwners(draft.id)
        loadOwnership()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [draft, loadOwners, loadOwnership, t, toast],
  )

  if (items === null) return <div className="ga-loading">{t('Loading…')}</div>

  const isOutfit = draft?.category === 'outfit_piece'

  return (
    <div className={`ga-items-grid${isOutfit ? ' has-silhouette' : ''}`}>
      <aside className="ga-items-list-col">
        <ListHeader
          title={t('Item library')}
          onNew={newItem}
          onCopy={copyItem}
          copyDisabled={!draft || draft.isNew}
          extra={
            <ImportButton
              endpoint="/inventory/items/import"
              overwriteSupported
              onImported={() => reload()}
            />
          }
        />
        <input
          className="ga-input"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('Search…')}
        />
        <div className="ga-form-row" style={{ marginTop: 4 }}>
          <select
            className="ga-input"
            style={{ flex: 1 }}
            value={filterCategory}
            onChange={(e) => {
              const v = e.target.value as Category | ''
              setFilterCategory(v)
              if (v !== 'outfit_piece') setFilterSlot('')
            }}
          >
            <option value="">{t('All categories')}</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            className="ga-input"
            style={{ flex: 1 }}
            value={filterScope}
            onChange={(e) => setFilterScope(e.target.value as '' | 'world' | 'shared')}
            title={t('Filter by source')}
          >
            <option value="">{t('All sources')}</option>
            <option value="world">{t('World only')}</option>
            <option value="shared">{t('Shared only')}</option>
          </select>
          <select
            className="ga-input"
            style={{ flex: 1 }}
            value={filterRarity}
            onChange={(e) => setFilterRarity(e.target.value as Rarity | '')}
          >
            <option value="">{t('All rarities')}</option>
            {RARITIES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select
            className="ga-input"
            style={{ flex: 1 }}
            value={filterOwner}
            onChange={(e) => setFilterOwner(e.target.value)}
            title={t('Filter by owner')}
          >
            <option value="">{t('All owners')}</option>
            <option value="__none__">{t('Owned by nobody')}</option>
            {characters.map((c) => (
              <option key={c.name} value={c.name}>
                {c.display_name || c.name}
              </option>
            ))}
          </select>
        </div>
        {filterCategory === 'outfit_piece' && (
          <div className="ga-form-row" style={{ marginTop: 4 }}>
            <select
              className="ga-input"
              style={{ flex: 1 }}
              value={filterSlot}
              onChange={(e) => setFilterSlot(e.target.value)}
              title={t('Filter by slot')}
            >
              <option value="">{t('All slots')}</option>
              {slotOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        )}
        <ul className="ga-list" style={{ marginTop: 6 }}>
          {filtered.length === 0 ? (
            <li className="ga-list-empty">{t('No items')}</li>
          ) : (
            filtered.map((it) => (
              <ItemRow
                key={it.id}
                item={it}
                isActive={!!(draft && !draft.isNew && draft.id === it.id)}
                onSelect={editItem}
              />
            ))
          )}
        </ul>
      </aside>

      {draft ? (
        <div className="ga-items-toolbar-row">
          <DetailToolbar
            title={draft.name || draft.id || t('New item')}
            onSave={save}
            onCancel={() => {
              setDraft(null)
              setOwners([])
            }}
            onDelete={draft.isNew ? undefined : remove}
            onMove={draft.isNew ? undefined : move}
            storage={draft.shared ? 'shared' : 'world'}
            extra={
              draft.isNew || !draft.id || draft.shared ? null : (
                <>
                  <ExportButton
                    endpoint={`/inventory/items/${encodeURIComponent(draft.id)}/export`}
                    filename={`${draft.id}.zip`}
                  />
                  <PublishButton
                    packType="item"
                    entityId={draft.id}
                    defaultName={draft.name || draft.id}
                  />
                </>
              )
            }
          />
        </div>
      ) : null}

      <section className="ga-items-form-col">
        {draft ? (
          <ItemForm
            draft={draft}
            items={items || []}
            outfitTypeOptions={outfitTypeOptions}
            conditionOptions={conditionOptions}
            onUpdate={update}
            onUpdateExtra={updateExtra}
            onToggleListItem={toggleListItem}
          />
        ) : (
          <div className="ga-placeholder">{t('Click an item or create a new one.')}</div>
        )}
      </section>

      {isOutfit && draft ? (
        <aside className="ga-items-silhouette-col">
          <Silhouette
            slots={draft.slots}
            covers={draft.covers}
            partially_covers={draft.partially_covers}
            onCycleSlot={cycleSlot}
          />
        </aside>
      ) : null}

      <aside className="ga-items-side-col">
        {draft && !draft.isNew ? (
          <>
            <div className="ga-items-image-panel">
              <div className="ga-form-section-label">{t('Image')}</div>
              <div className="ga-items-image-preview">
                <img src={`/inventory/items/${encodeURIComponent(draft.id)}/image?t=${Date.now()}`} alt="" />
              </div>
              {(() => {
                const meta = items?.find((it) => it.id === draft.id)?.image_meta
                if (!meta || (!meta.model && !meta.backend)) return null
                return (
                  <div className="ga-gallery-meta" style={{ marginTop: 6 }}>
                    {meta.model ? (
                      <div>
                        <strong>{t('Model')}</strong> {meta.model}
                      </div>
                    ) : null}
                    {meta.backend ? (
                      <div>
                        <strong>{t('Provider')}</strong> {meta.backend}
                      </div>
                    ) : null}
                  </div>
                )
              })()}
              <button className="ga-btn ga-btn-sm" onClick={() => setGenDialogOpen(true)}>
                {t('Generate image')}
              </button>
            </div>
            {genDialogOpen ? (
              <ImageGenDialog
                open
                title={t('Generate item image — {name}').replace('{name}', draft.name || draft.id)}
                defaultPrompt={buildItemPrompt(draft)}
                onSubmit={submitGenerateImage}
                onClose={() => setGenDialogOpen(false)}
              />
            ) : null}
            <div className="ga-items-owners-panel">
              <div className="ga-form-section-label">{t('Owners of this item')}</div>
              <OwnerAdder characters={characters} onAdd={addOwner} />
              {owners.length === 0 ? (
                <div className="ga-form-hint">{t('Nobody')}</div>
              ) : (
                <ul className="ga-items-owners-list">
                  {owners.map((o) => (
                    <li key={o.character}>
                      <span>
                        {o.character} <span className="ga-form-hint">×{o.quantity}</span>
                        {o.equipped ? <span className="ga-form-hint"> · {t('equipped')}</span> : null}
                        {o.obtained_from ? <span className="ga-form-hint"> · {t('from')} {o.obtained_from}</span> : null}
                      </span>
                      <button
                        className="ga-btn ga-btn-sm ga-btn-danger"
                        onClick={() => removeOwner(o.character)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        ) : (
          <div className="ga-placeholder">{t('Select an item to manage image and owners.')}</div>
        )}
      </aside>
    </div>
  )
}

interface OwnerAdderProps {
  characters: CharacterRef[]
  onAdd: (name: string, qty: number) => void
}

function OwnerAdder({ characters, onAdd }: OwnerAdderProps) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [qty, setQty] = useState(1)
  return (
    <div className="ga-form-row" style={{ marginTop: 6 }}>
      <select className="ga-input" style={{ flex: 1, fontSize: 11 }} value={name} onChange={(e) => setName(e.target.value)}>
        <option value="">— {t('character')} —</option>
        {characters.map((c) => (
          <option key={c.name} value={c.name}>
            {c.display_name || c.name}
          </option>
        ))}
      </select>
      <input
        type="number"
        className="ga-input"
        style={{ width: 60, fontSize: 11 }}
        min={1}
        value={qty}
        onChange={(e) => setQty(parseInt(e.target.value, 10) || 1)}
      />
      <button
        className="ga-btn ga-btn-sm ga-btn-primary"
        onClick={() => {
          if (name) {
            onAdd(name, qty)
            setName('')
            setQty(1)
          }
        }}
      >
        + {t('Give')}
      </button>
    </div>
  )
}
