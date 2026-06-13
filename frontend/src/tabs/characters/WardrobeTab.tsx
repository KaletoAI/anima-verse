import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Wardrobe / outfit editor for any character (Characters → Wardrobe).
 * Read-staged-then-bulk-apply: edit a draft of slot→piece, then apply the
 * full soll-state in one call. Backend:
 *   GET  /inventory/characters/{c}              (inventory, outfit_piece items)
 *   GET  /inventory/characters/{c}/equipped     (equipped_pieces {slot:item_id})
 *   POST /inventory/characters/{c}/apply-equipped ({pieces:{slot:item_id}})
 *   GET  /characters/{c}/outfit-expression?override=1&pieces=…  (cached-only preview)
 */

// Canonical slot order — mirrors VALID_PIECE_SLOTS (app/models/inventory.py).
const SLOTS: Array<{ id: string; label: string }> = [
  { id: 'underwear_top', label: 'Underwear (top)' },
  { id: 'underwear_bottom', label: 'Underwear (bottom)' },
  { id: 'legs', label: 'Legs' },
  { id: 'top', label: 'Top' },
  { id: 'bottom', label: 'Bottom' },
  { id: 'outer', label: 'Outer' },
  { id: 'feet', label: 'Feet' },
  { id: 'neck', label: 'Neck' },
  { id: 'head', label: 'Head' },
]

interface OutfitPiece { slots?: string[]; covers?: string[]; partially_covers?: string[] }
interface InvItem {
  item_id: string
  item_name: string
  item_category: string
  item_image?: string | null
  item_prompt_fragment?: string
  outfit_piece?: OutfitPiece
  equipped?: boolean
}
interface EquippedResp { equipped_pieces: Record<string, string>; equipped_items: string[] }

type Draft = Record<string, string>  // slot -> item_id

function normalize(d: Draft): string {
  return Object.keys(d).filter((k) => d[k]).sort().map((k) => `${k}:${d[k]}`).join(',')
}
function slotsOf(p: InvItem): string[] {
  const s = p.outfit_piece?.slots
  return Array.isArray(s) && s.length ? s : []
}
/** Setzt ein (ggf. Multi-Slot-)Piece in den Draft und verdrängt Pieces, die
 *  einen der Ziel-Slots belegen, vollständig aus allen ihren Slots. */
function withPiece(draft: Draft, piece: InvItem): Draft {
  const target = slotsOf(piece)
  const next: Draft = { ...draft }
  const displaced = new Set(target.map((s) => next[s]).filter(Boolean))
  for (const s of Object.keys(next)) if (displaced.has(next[s])) delete next[s]
  for (const s of target) next[s] = piece.item_id
  return next
}
function withoutItem(draft: Draft, itemId: string): Draft {
  const next: Draft = { ...draft }
  for (const s of Object.keys(next)) if (next[s] === itemId) delete next[s]
  return next
}

export function WardrobeTab({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)

  const [items, setItems] = useState<InvItem[]>([])
  const [equipped, setEquipped] = useState<Draft>({})
  const [draft, setDraft] = useState<Draft>({})
  const [openSlot, setOpenSlot] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [previewFailed, setPreviewFailed] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [inv, eq] = await Promise.all([
        apiGet<{ inventory: InvItem[] }>(`/inventory/characters/${enc}`),
        apiGet<EquippedResp>(`/inventory/characters/${enc}/equipped`),
      ])
      const pieces = (inv.inventory || []).filter((it) => it.item_category === 'outfit_piece')
      setItems(pieces)
      const eqp = eq.equipped_pieces || {}
      setEquipped(eqp)
      setDraft({ ...eqp })
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [enc, t, toast])

  useEffect(() => { setOpenSlot(''); setPreviewFailed(false); load() }, [load])
  useEffect(() => { setPreviewFailed(false) }, [normalize(draft)]) // eslint-disable-line react-hooks/exhaustive-deps

  const byId = useMemo(() => {
    const m: Record<string, InvItem> = {}
    for (const it of items) m[it.item_id] = it
    return m
  }, [items])

  const candidatesFor = useCallback(
    (slot: string) => items.filter((it) => slotsOf(it).includes(slot)),
    [items],
  )

  const dirty = normalize(draft) !== normalize(equipped)

  const apply = async () => {
    setBusy(true)
    try {
      const pieces: Draft = {}
      for (const k of Object.keys(draft)) if (draft[k]) pieces[k] = draft[k]
      await apiPost(`/inventory/characters/${enc}/apply-equipped`, { user_id: '', pieces })
      toast(t('Outfit applied'), 'success')
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="ga-placeholder">{t('Loading…')}</div>

  // Belegte Slots ohne Multi-Slot-Duplikate → Paper-Doll-Vorschau.
  const occupiedItemIds = Array.from(new Set(Object.values(draft).filter(Boolean)))
  const previewPieces = Object.keys(draft).filter((s) => draft[s]).sort()
    .map((s) => `${s}:${draft[s]}`).join(',')
  const previewSrc = `/characters/${enc}/outfit-expression?override=1&items=&pieces=`
    + encodeURIComponent(previewPieces)

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      {/* Linke Spalte: Slot-Akkordeon */}
      <div style={{ flex: '1 1 360px', minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center' }}>
          <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={!dirty || busy} onClick={apply}>
            {busy ? t('Applying…') : t('Apply outfit')}
          </button>
          <button className="ga-btn ga-btn-sm" disabled={!dirty || busy} onClick={() => setDraft({ ...equipped })}>
            {t('Reset')}
          </button>
          {dirty ? <span style={{ fontSize: '0.8em', opacity: 0.6 }}>{t('Unsaved changes')}</span> : null}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {SLOTS.map((slot) => {
            const curId = draft[slot.id]
            const cur = curId ? byId[curId] : undefined
            const cands = candidatesFor(slot.id)
            const open = openSlot === slot.id
            const multi = cur ? slotsOf(cur).filter((s) => s !== slot.id) : []
            return (
              <div key={slot.id} style={{ border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
                <button
                  type="button"
                  onClick={() => setOpenSlot(open ? '' : slot.id)}
                  disabled={cands.length === 0 && !cur}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                    background: 'none', border: 0, color: 'inherit', cursor: 'pointer',
                    padding: '7px 10px', textAlign: 'left',
                    opacity: cands.length === 0 && !cur ? 0.4 : 1,
                  }}
                >
                  <span style={{ flex: '0 0 110px', fontSize: '0.82em', opacity: 0.7 }}>{t(slot.label)}</span>
                  {cur ? <ItemThumb item={cur} size={26} /> : null}
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {cur ? cur.item_name : <span style={{ opacity: 0.4 }}>{t('empty')}</span>}
                    {multi.length > 0 && (
                      <span style={{ opacity: 0.45, fontSize: '0.78em' }}>
                        {' '}({multi.map((s) => t(SLOTS.find((x) => x.id === s)?.label || s)).join(', ')})
                      </span>
                    )}
                  </span>
                  <span style={{ flex: '0 0 auto', opacity: 0.5 }}>{open ? '▾' : '▸'}</span>
                </button>

                {open && (
                  <div style={{ borderTop: '1px solid var(--border, #30363d)', padding: 6,
                                display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {/* Slot leeren */}
                    <button
                      type="button"
                      onClick={() => { if (curId) setDraft(withoutItem(draft, curId)) }}
                      disabled={!curId}
                      style={rowBtn(!curId)}>
                      <span style={{ flex: '0 0 26px', textAlign: 'center', opacity: 0.6 }}>∅</span>
                      <span style={{ opacity: 0.6 }}>{t('Remove / leave empty')}</span>
                    </button>
                    {cands.length === 0 ? (
                      <div style={{ fontSize: '0.8em', opacity: 0.5, padding: '4px 8px' }}>
                        {t('No pieces in inventory for this slot.')}
                      </div>
                    ) : cands.map((p) => {
                      const active = curId === p.item_id
                      const extra = slotsOf(p).filter((s) => s !== slot.id)
                      return (
                        <button key={p.item_id} type="button"
                          onClick={() => setDraft(withPiece(draft, p))}
                          style={rowBtn(false, active)}>
                          <ItemThumb item={p} size={26} />
                          <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {p.item_name}
                            {extra.length > 0 && (
                              <span style={{ opacity: 0.45, fontSize: '0.78em' }}>
                                {' '}(+{extra.map((s) => t(SLOTS.find((x) => x.id === s)?.label || s)).join(', ')})
                              </span>
                            )}
                          </span>
                          {active ? <span style={{ flex: '0 0 auto', color: 'var(--accent, #6aa9ff)' }}>✓</span> : null}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Rechte Spalte: Vorschau */}
      <div style={{ flex: '0 1 280px', minWidth: 200 }}>
        <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 6 }}>{t('Preview')}</div>
        {!previewFailed && previewPieces ? (
          <img
            src={previewSrc}
            alt={t('Preview')}
            onError={() => setPreviewFailed(true)}
            style={{ width: '100%', borderRadius: 8, border: '1px solid var(--border, #30363d)', display: 'block' }}
          />
        ) : null}
        {(previewFailed || !previewPieces) && (
          <div style={{ fontSize: '0.76em', opacity: 0.45, marginBottom: 8 }}>
            {previewPieces
              ? t('No rendered preview cached for this combination.')
              : t('No pieces equipped.')}
          </div>
        )}
        {/* Paper-Doll-Liste der belegten Pieces (immer verfügbar) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
          {occupiedItemIds.map((id) => {
            const it = byId[id]
            if (!it) return null
            return (
              <div key={id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ItemThumb item={it} size={30} />
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                               whiteSpace: 'nowrap', fontSize: '0.85em' }}>{it.item_name}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function rowBtn(disabled: boolean, active = false): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
    padding: '4px 8px', borderRadius: 5, cursor: disabled ? 'default' : 'pointer',
    border: '1px solid ' + (active ? 'var(--accent, #6aa9ff)' : 'transparent'),
    background: active ? 'rgba(120,170,255,0.16)' : 'transparent',
    color: 'inherit', opacity: disabled ? 0.4 : 1, fontSize: '0.88em',
  }
}

function ItemThumb({ item, size }: { item: InvItem; size: number }) {
  const common: React.CSSProperties = {
    width: size, height: size, flex: '0 0 auto', borderRadius: 5,
    background: 'rgba(255,255,255,0.06)', objectFit: 'cover',
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  }
  if (item.item_image) {
    return <img src={`/inventory/items/${encodeURIComponent(item.item_id)}/image`} alt="" style={common} />
  }
  return <span style={{ ...common, fontSize: size * 0.5, opacity: 0.5 }}>👕</span>
}
