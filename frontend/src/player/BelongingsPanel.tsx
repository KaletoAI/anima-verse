/**
 * BelongingsPanel — Inventar + Outfit als klassisches RPG-Paper-Doll (B Tier 1).
 *
 * Links: filterbare Item-Liste (Kategorie + bei Outfit zusätzlich Slot-Filter).
 * Rechts: die Figur des Avatars mit Slot-Spalte (head→feet); getragene Pieces
 * zeigen ihr Icon und sind per Klick ablegbar. Anziehen/Use/Set-Wechsel über die
 * Liste. Quelle: GET /play/belongings; Setter: /play/{equip,unequip,use-item},
 * /play/self/outfit.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { usePoll } from './usePolling'
import { EmptyState } from './EmptyState'

// Anker-Positionen (x%, y%) im KOORDINATENSYSTEM DES BILDES (silhouette.svg ist
// 896×1216, die Figur liegt zentral). Hier werden die Symbole der getragenen
// Outfitteile projiziert. Nur Figur + Symbole, KEINE farbigen Slot-Flächen.
const SLOT_ANCHOR: Record<string, [number, number]> = {
  head: [50, 6], neck: [50, 19], outer: [33, 40], top: [50, 33],
  underwear_top: [66, 33], bottom: [50, 55], underwear_bottom: [66, 55],
  legs: [50, 73], feet: [50, 92],
}

/** Item-Icon mit Emoji-Fallback: zentriert, und bei fehlendem/kaputtem Bild
 *  (z.B. manche Spell-Items) wird sauber das Kategorie-Emoji gezeigt. */
function ItemIcon({ itemId, hasImage, emoji, size }: { itemId: string; hasImage: boolean; emoji: string; size: number }) {
  const [failed, setFailed] = useState(false)
  return (
    <span style={{
      width: size, height: size, flex: '0 0 auto', borderRadius: 4, overflow: 'hidden',
      background: 'rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center',
      justifyContent: 'center', fontSize: Math.round(size * 0.6), lineHeight: 1,
    }}>
      {hasImage && !failed
        ? <img src={`/inventory/items/${encodeURIComponent(itemId)}/image`} alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            onError={() => setFailed(true)} />
        : emoji}
    </span>
  )
}

interface Item {
  item_id: string; name: string; description: string; quantity: number; category: string
  consumable: boolean; equipped: boolean; is_outfit: boolean; slots: string[]
  outfit_types: string[]; is_spell: boolean; incantation: string
  image: boolean; rarity: string
}

// Rarität → Rand-Farbe (common dezent, rare blau, unique gold).
const RARITY_COLOR: Record<string, string> = {
  common: 'rgba(255,255,255,0.18)', rare: '#5b9cff', unique: '#e0a106',
}
interface Equipped { item_id: string; name: string; image: boolean }
interface Belongings {
  avatar: string; slot_order: string[]; slot_labels: Record<string, string>
  silhouette_url?: string
  slot_anchors?: Record<string, [number, number]>
  equipped: Record<string, Equipped>; items: Item[]
  outfit_sets: Array<{ id: string; name: string }>; max_slots: number
}

const EMPTY: Belongings = {
  avatar: '', slot_order: [], slot_labels: {}, equipped: {}, items: [],
  outfit_sets: [], max_slots: 0,
}

type Cat = 'all' | 'outfit' | 'consumable' | 'spell' | 'other'

function catOf(it: Item): Cat {
  if (it.is_spell) return 'spell'
  if (it.is_outfit) return 'outfit'
  if (it.consumable) return 'consumable'
  return 'other'
}
const CAT_EMOJI: Record<Cat, string> = { all: '🎒', outfit: '👕', consumable: '🧪', spell: '✨', other: '📦' }

export function BelongingsPanel({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useI18n()
  const [data, setData] = useState<Belongings>(EMPTY)
  const [cat, setCat] = useState<Cat>('all')
  const [slotFilter, setSlotFilter] = useState('')
  const [busy, setBusy] = useState(false)
  // Figurhöhe messen → Slot-Marker skalieren mit der Figur.
  const figRef = useRef<HTMLDivElement>(null)
  const [figH, setFigH] = useState(0)
  // avatar in den Deps: die Figur (und damit figRef) wird erst gerendert, wenn
  // ein Avatar geladen ist — sonst hinge der Observer am noch nicht existenten
  // Element und figH bliebe 0 (Marker zu klein, skalieren nicht).
  const avatarReady = data.avatar
  useEffect(() => {
    const el = figRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => setFigH(entries[0].contentRect.height))
    ro.observe(el)
    setFigH(el.getBoundingClientRect().height)
    return () => ro.disconnect()
  }, [avatarReady])

  const { data: polled, refresh } = usePoll<Belongings>(
    'play-belongings', () => apiGet<Belongings>('/play/belongings'), { intervalMs: 5000 })
  useEffect(() => { if (polled) setData(polled) }, [polled])

  const act = useCallback(async (url: string, body: Record<string, unknown>, closeAfter = false) => {
    if (busy) return
    setBusy(true)
    try {
      await apiPost(url, body)
      await refresh()
      if (closeAfter) onClose?.()  // e.g. close inventory after self-cast (like the old UI)
    } catch { /* ignore */ } finally { setBusy(false) }
  }, [busy, refresh, onClose])

  const filtered = useMemo(() => {
    let list = data.items
    if (cat !== 'all') list = list.filter((it) => catOf(it) === cat)
    if (cat === 'outfit' && slotFilter) list = list.filter((it) => it.slots.includes(slotFilter))
    return list
  }, [data.items, cat, slotFilter])

  // Slot-Filter-Optionen aus den vorhandenen Outfit-Pieces ableiten
  const slotOptions = useMemo(() => {
    const s = new Set<string>()
    data.items.forEach((it) => { if (it.is_outfit) it.slots.forEach((x) => s.add(x)) })
    return data.slot_order.filter((x) => s.has(x))
  }, [data.items, data.slot_order])

  if (!data.avatar) {
    return <EmptyState icon="inventory" title={t('No active avatar')} />
  }

  const cats: Cat[] = ['all', 'outfit', 'consumable', 'spell', 'other']
  // Marker-Größe skaliert mit der Figurhöhe (geclamped).
  const markerSize = Math.round(Math.max(22, Math.min(80, figH * 0.11)))
  // Alle Slots mit Anker (in Anzeige-Reihenfolge) — leer ODER belegt darstellen.
  // Anchor positions: species package (slot_anchors) wins, core map is the default.
  const anchorOf = (s: string): [number, number] | undefined =>
    data.slot_anchors?.[s] || SLOT_ANCHOR[s]
  const figureSlots = data.slot_order.filter((s) => anchorOf(s))

  return (
    <div style={{ display: 'flex', gap: 10, height: '100%', minHeight: 0, fontSize: '0.88em' }}>
      {/* ── Links: Filter + Liste ──────────────────────────────── */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {cats.map((c) => (
            <button key={c} onClick={() => { setCat(c); if (c !== 'outfit') setSlotFilter('') }}
              style={chip(cat === c)}>
              {CAT_EMOJI[c]} {t(c === 'all' ? 'All' : c === 'outfit' ? 'Outfit' : c === 'consumable' ? 'Consumable' : c === 'spell' ? 'Spell' : 'Other')}
            </button>
          ))}
        </div>
        {cat === 'outfit' && slotOptions.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            <button onClick={() => setSlotFilter('')} style={chip(!slotFilter, true)}>{t('All slots')}</button>
            {slotOptions.map((s) => (
              <button key={s} onClick={() => setSlotFilter(s)} style={chip(slotFilter === s, true)}>
                {t(data.slot_labels[s] || s)}
              </button>
            ))}
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
          {filtered.length === 0 && <EmptyState small icon="inventory" title={t('Nothing here')} />}
          {filtered.map((it) => {
            // Zweite Zeile: bevorzugt die Beschreibung; sonst Slot/Spruch/Kategorie.
            const fallback = it.is_spell
              ? (it.incantation ? `„${it.incantation}"` : t('Spell'))
              : it.is_outfit
                ? it.slots.map((s) => data.slot_labels[s] || s).join(', ')
                : it.consumable ? t('Consumable') : (it.category || t('Other'))
            const sub = it.description || fallback
            const rarityColor = RARITY_COLOR[it.rarity] || RARITY_COLOR.common
            return (
              <div key={it.item_id} title={it.rarity || 'common'} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px',
                borderRadius: 6, borderLeft: `3px solid ${rarityColor}`,
                background: it.equipped ? 'rgba(120,170,255,0.14)' : 'rgba(255,255,255,0.04)',
              }}>
                <ItemIcon itemId={it.item_id} hasImage={it.image} emoji={CAT_EMOJI[catOf(it)]} size={40} />
                <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.name}{it.quantity > 1 ? <span style={{ opacity: 0.6 }}> ×{it.quantity}</span> : null}
                  </span>
                  {sub && (
                    <span style={{ fontSize: '0.72em', opacity: 0.5, fontStyle: (!it.description && it.is_spell) ? 'italic' : 'normal',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</span>
                  )}
                </div>
                {it.is_outfit && (
                  it.equipped
                    ? <span style={{ fontSize: '0.72em', opacity: 0.6 }}>{t('worn')}</span>
                    : <button disabled={busy} style={btn()} onClick={() => act('/play/equip', { item_id: it.item_id })}>{t('Wear')}</button>
                )}
                {/* Spell: casten (execute_cast, respektiert copy_on_give) — NICHT consume. */}
                {it.is_spell && (
                  <button disabled={busy} style={btn()} onClick={() => act('/play/cast-self', { item_id: it.item_id }, true)}>{t('Cast')}</button>
                )}
                {!it.is_spell && it.consumable && (
                  <button disabled={busy} style={btn()} onClick={() => act('/play/use-item', { item_id: it.item_id })}>{t('Use')}</button>
                )}
              </div>
            )
          })}
        </div>
        {data.outfit_sets.length > 0 && (
          <select className="ga-input" value="" disabled={busy} style={{ width: '100%' }}
            onChange={(e) => e.target.value && act('/play/self/outfit', { outfit_id: e.target.value })}>
            <option value="">{t('Wear a saved outfit…')}</option>
            {data.outfit_sets.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}
      </div>

      {/* ── Rechts: Figur + Outfit-Symbole — Spaltenbreite folgt der Bildhöhe,
              so skaliert die Figur mit der Fensterhöhe ─ */}
      <div style={{ flex: '0 0 auto', maxWidth: '55%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0, overflow: 'hidden' }}>
        <div style={{ flex: 1, minHeight: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', overflow: 'hidden' }}>
          <div ref={figRef} style={{ position: 'relative', height: '100%', display: 'inline-flex' }}>
            <img src={data.silhouette_url || '/static/game_admin/silhouette.svg'} alt={data.avatar}
              style={{ height: '100%', width: 'auto', display: 'block', opacity: 0.45 }} />
            {figureSlots.map((slot) => {
              const a = anchorOf(slot)!
              const eq = data.equipped[slot]
              const common = {
                position: 'absolute' as const, left: `${a[0]}%`, top: `${a[1]}%`,
                transform: 'translate(-50%,-50%)', width: markerSize, height: markerSize,
                borderRadius: 5, boxSizing: 'border-box' as const,
              }
              if (eq) {
                // belegt: Item-Symbol (eckig) mit kräftigem, vollem Rand
                return (
                  <button key={slot} title={`${eq.name} — ${t('take off')}`}
                    onClick={() => act('/play/unequip', { slot })}
                    style={{
                      ...common, padding: 0, cursor: 'pointer', overflow: 'hidden',
                      border: '2px solid var(--accent,#6aa9ff)',
                      boxShadow: '0 0 0 2px rgba(0,0,0,0.5), 0 1px 4px rgba(0,0,0,0.6)',
                      background: 'rgba(20,25,35,0.85)',
                    }}>
                    <ItemIcon itemId={eq.item_id} hasImage={eq.image} emoji="👕" size={markerSize} />
                  </button>
                )
              }
              // leer: gestrichelter, dezenter eckiger Umriss als Slot-Markierung
              return (
                <div key={slot} title={`${t(data.slot_labels[slot] || slot)} (${t('empty')})`}
                  style={{
                    ...common, border: '2px dashed rgba(255,255,255,0.4)',
                    background: 'rgba(0,0,0,0.25)',
                  }} />
              )
            })}
          </div>
        </div>
        <div style={{ opacity: 0.5, fontSize: '0.72em', textAlign: 'center' }}>
          {data.items.length}/{data.max_slots || '∞'} {t('items')}
        </div>
      </div>
    </div>
  )
}

function chip(active: boolean, small = false): CSSProperties {
  return {
    padding: small ? '1px 7px' : '2px 9px', borderRadius: 11, cursor: 'pointer',
    fontSize: small ? '0.72em' : '0.78em',
    border: '1px solid ' + (active ? 'var(--accent,#6aa9ff)' : 'rgba(255,255,255,0.2)'),
    background: active ? 'rgba(120,170,255,0.25)' : 'transparent', color: 'inherit',
  }
}
function btn(): CSSProperties {
  return {
    fontSize: '0.72em', padding: '2px 8px', borderRadius: 6, cursor: 'pointer',
    border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(255,255,255,0.06)', color: 'inherit',
  }
}
