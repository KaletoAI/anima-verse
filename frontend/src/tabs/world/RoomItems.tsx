import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { type ItemRef } from '../../lib/refs'

// ── Room items panel ───────────────────────────────────────────────────────

interface RoomItem {
  item_id: string
  item_name?: string
  item_description?: string
  quantity?: number
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

  const removeItem = useCallback(
    async (itemId: string) => {
      if (!window.confirm(t('Remove item from room?'))) return
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
    [locationId, roomId, reload, t, toast],
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
            <li key={it.item_id}>
              <strong>{it.item_name || it.item_id}</strong>
              {it.quantity && it.quantity > 1 ? ` ×${it.quantity}` : ''}
              {it.hidden ? <span className="ga-form-hint"> · {t('hidden')}</span> : null}
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
    </div>
  )
}
