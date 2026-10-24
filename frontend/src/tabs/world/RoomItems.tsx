import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPatch } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '@anima/player-ui'
import { ConfirmDialog } from '@anima/player-ui'
import { type ItemRef } from '../../lib/refs'

// ── Room items panel ───────────────────────────────────────────────────────

interface RoomItem {
  item_id: string
  item_name?: string
  item_description?: string
  quantity?: number
  discovery_difficulty?: number
  found_by?: string[]
  note?: string
  hidden?: boolean
}

export function RoomItems({
  locationId,
  roomId,
  items,
}: {
  locationId: string
  roomId: string
  items: ItemRef[]
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [roomItems, setRoomItems] = useState<RoomItem[] | null>(null)
  const [addId, setAddId] = useState('')
  const [addQty, setAddQty] = useState(1)
  const [addHidden, setAddHidden] = useState(false)

  const reload = useCallback(async () => {
    if (!locationId || !roomId) return
    try {
      const d = await apiGet<{ items?: RoomItem[] }>(
        `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}`,
      )
      setRoomItems(d.items || [])
    } catch {
      setRoomItems([])
    }
  }, [locationId, roomId])

  useEffect(() => {
    reload()
  }, [reload])

  // The click arms the in-app question, the dialog at the end removes.
  const [pendingRemove, setPendingRemove] = useState('')
  const removeItem = useCallback((itemId: string) => { setPendingRemove(itemId) }, [])
  const doRemoveItem = useCallback(
    async () => {
      const itemId = pendingRemove
      setPendingRemove('')
      if (!itemId) return
      try {
        await apiDelete(
          `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}/${encodeURIComponent(itemId)}`,
        )
        toast(t('Removed'))
        reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [pendingRemove, locationId, roomId, reload, t, toast],
  )

  const addItem = useCallback(async () => {
    if (!addId) return
    try {
      await apiPost(
        `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}`,
        { item_id: addId, quantity: addQty, hidden: addHidden },
      )
      toast(t('Added'))
      setAddId('')
      setAddQty(1)
      setAddHidden(false)
      reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [addId, addQty, addHidden, locationId, roomId, reload, t, toast])

  const editItem = async (itemId: string, updates: Partial<RoomItem>) => {
    try {
      await apiPatch(
        `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}/${encodeURIComponent(itemId)}`,
        updates,
      )
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      await reload()
    }
  }

  return (
    <div className="ga-section">
      <div className="ga-form-section-label">{t('Items in this room')}</div>
      {roomItems === null ? (
        <div className="ga-form-hint">{t('Loading…')}</div>
      ) : roomItems.length === 0 ? (
        <div className="ga-form-hint">{t('Empty')}</div>
      ) : (
        <ul className="ga-room-mini-list">
          {roomItems.map((it) => (
            <li key={it.item_id} style={{ flexWrap: 'wrap' }}>
              <strong>{it.item_name || it.item_id}</strong>
              {it.quantity && it.quantity > 1 ? ` ×${it.quantity}` : ''}
              <Field label={t('Hidden')} inline compact>
                <input type="checkbox" checked={!!it.hidden}
                  onChange={(e) => { void editItem(it.item_id, { hidden: e.target.checked }) }} />
              </Field>
              {it.hidden && (
                <div style={{ flexBasis: '100%', order: 1 }}>
                  <Field label={t('Discovery difficulty')}
                    hint={t('Compared with the discovery stat (Setup). Above 100 stays hidden unless a state boosts the stat.')}>
                    <input type="number" className="ga-input" min={0} max={999} step={1}
                      value={it.discovery_difficulty ?? 0}
                      onChange={(e) => {
                        const value = e.target.valueAsNumber
                        setRoomItems((current) => current?.map((row) => row.item_id === it.item_id
                          ? { ...row, discovery_difficulty: Number.isFinite(value) ? value : 0 } : row) ?? null)
                      }}
                      onBlur={(e) => { void editItem(it.item_id, {
                        discovery_difficulty: Math.max(0, Math.min(999, Math.trunc(e.target.valueAsNumber || 0))),
                      }) }} />
                  </Field>
                  <div className="ga-form-hint">{t('Found by')}: {(it.found_by || []).join(', ') || '—'}</div>
                </div>
              )}
              <button className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => removeItem(it.item_id)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="ga-form-row" style={{ marginTop: 6 }}>
        <Field label={t('Add item')}>
          <select className="ga-input" value={addId} onChange={(e) => setAddId(e.target.value)}>
            <option value="">— {t('select')} —</option>
            {items.map((it) => (
              <option key={it.id} value={it.id}>
                {it.name || it.id}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('Quantity')}>
          <input
            type="number"
            className="ga-input"
            min={1}
            max={99}
            value={addQty}
            onChange={(e) => setAddQty(parseInt(e.target.value, 10) || 1)}
          />
        </Field>
      </div>
      <div className="ga-form-row">
        <Field label={t('Hidden')} inline compact hint={t('Items hidden in the room are not visible to characters until discovered.')}>
          <input type="checkbox" checked={addHidden} onChange={(e) => setAddHidden(e.target.checked)} />
        </Field>
        <button
          className="ga-btn ga-btn-sm ga-btn-primary"
          onClick={addItem}
          disabled={!addId}
          style={{ marginLeft: 'auto', alignSelf: 'flex-end' }}
        >
          + {t('Add')}
        </button>
      </div>

      <ConfirmDialog
        open={!!pendingRemove}
        title={t('Remove item from room')}
        message={t('The item is taken out of this room. The item itself stays in the world.')}
        confirmLabel={t('Remove')}
        danger
        onConfirm={() => { void doRemoveItem() }}
        onClose={() => setPendingRemove('')}
      />
    </div>
  )
}
