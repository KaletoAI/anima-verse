/**
 * GiftPicker — composer action to give an inventory item to a present character
 * (feature #4). Loads the avatar's inventory, offers the transferable, not-worn
 * items in a grid, and gifts the chosen one to a selected recipient via
 * POST /inventory/characters/{avatar}/{item_id}/give → relationship boost.
 *
 * Portal-rendered: the composer lives inside react-grid-layout's transform
 * context, where a position:fixed modal would otherwise be clipped.
 */
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'

interface InventoryEntry {
  item_id: string
  item_name?: string
  item_image?: string | null
  item_rarity?: string
  item_transferable?: boolean
  equipped?: boolean
  quantity?: number
}

export interface GiftResult {
  item_name: string
  rarity: string
  boost: number
  to_character: string
}

const RARITY_COLOR: Record<string, string> = {
  common: '#8b949e',
  uncommon: '#3fa45a',
  rare: '#388bfd',
  epic: '#a371f7',
  legendary: '#d6b06a',
}

export function GiftPicker({
  avatar,
  recipients,
  defaultRecipient,
  onClose,
  onGifted,
}: {
  avatar: string
  recipients: string[]
  defaultRecipient?: string
  onClose: () => void
  onGifted: (r: GiftResult) => void
}) {
  const { t } = useI18n()
  const [items, setItems] = useState<InventoryEntry[] | null>(null)
  const [recipient, setRecipient] = useState(defaultRecipient || recipients[0] || '')
  const [giving, setGiving] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet<{ inventory?: InventoryEntry[] }>(`/inventory/characters/${encodeURIComponent(avatar)}`)
      .then((d) => setItems(d.inventory || []))
      .catch(() => setItems([]))
  }, [avatar])

  // Only transferable, not-currently-worn items can be gifted.
  const giftable = useMemo(
    () => (items || []).filter((it) => it.item_transferable !== false && !it.equipped),
    [items],
  )

  const give = async (it: InventoryEntry) => {
    if (!recipient || giving) return
    setGiving(it.item_id)
    setError('')
    try {
      const r = await apiPost<{ boost?: number; item_name?: string; rarity?: string }>(
        `/inventory/characters/${encodeURIComponent(avatar)}/${encodeURIComponent(it.item_id)}/give`,
        { to_character: recipient },
      )
      onGifted({
        item_name: r.item_name || it.item_name || it.item_id,
        rarity: r.rarity || it.item_rarity || 'common',
        boost: r.boost ?? 0,
        to_character: recipient,
      })
    } catch (e) {
      setError((e as Error).message)
      setGiving('')
    }
  }

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 680 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Give a gift')}</span>
          <button className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          <label className="ga-field" style={{ marginBottom: 10 }}>
            <span className="ga-field-caption">{t('Recipient')}</span>
            {recipients.length === 0 ? (
              <div className="ga-placeholder">{t('Nobody else is here.')}</div>
            ) : (
              <select
                className="ga-input"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
              >
                {recipients.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            )}
          </label>

          {error && <div className="ga-img-nomatch" style={{ marginBottom: 8 }}>{error}</div>}

          {items == null ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : giftable.length === 0 ? (
            <div className="ga-placeholder">{t('No giftable items.')}</div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                gap: 10,
              }}
            >
              {giftable.map((it) => {
                const rarity = (it.item_rarity || 'common').toLowerCase()
                const busy = giving === it.item_id
                return (
                  <button
                    key={it.item_id}
                    type="button"
                    disabled={!recipient || !!giving}
                    onClick={() => give(it)}
                    title={it.item_name || it.item_id}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                      padding: 6,
                      border: `1px solid ${RARITY_COLOR[rarity] || 'var(--border, #30363d)'}`,
                      borderRadius: 8,
                      background: 'var(--bg-alt, #0d1117)',
                      cursor: recipient && !giving ? 'pointer' : 'not-allowed',
                      opacity: busy ? 0.5 : 1,
                      textAlign: 'center',
                    }}
                  >
                    <div
                      style={{
                        width: '100%',
                        aspectRatio: '1 / 1',
                        borderRadius: 6,
                        overflow: 'hidden',
                        background: 'rgba(255,255,255,0.04)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      {it.item_image ? (
                        <img
                          src={`/inventory/items/${encodeURIComponent(it.item_id)}/image`}
                          alt={it.item_name || it.item_id}
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        />
                      ) : (
                        <span style={{ fontSize: 28, opacity: 0.5 }}>🎁</span>
                      )}
                    </div>
                    <span style={{ fontSize: '0.8em', fontWeight: 600, lineHeight: 1.2 }}>
                      {it.item_name || it.item_id}
                    </span>
                    <span
                      style={{ fontSize: '0.7em', color: RARITY_COLOR[rarity] || '#8b949e' }}
                    >
                      {t(rarity)}
                      {it.quantity && it.quantity > 1 ? ` ×${it.quantity}` : ''}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
