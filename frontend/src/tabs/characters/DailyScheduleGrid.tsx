import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { LocationRef } from '../../lib/refs'

/**
 * Faithful React port of the legacy "Tagesablauf" drag-to-paint grid.
 * Rows = Sleep + each unique location + each role; columns = 24 hours.
 * Each hour holds at most one {location, role, sleep}; location and role are
 * independent, sleep is exclusive. Drag across a row to paint a range, click a
 * filled cell to clear it. Backed by /scheduler/daily-schedule.
 */

interface Slot {
  location: string
  role: string
  sleep: boolean
}
type SlotMap = Record<number, Slot>

interface KeyParts {
  kind: string
  loc: string
  role: string
}

function parseKey(key: string): KeyParts {
  const parts = key.split('|')
  return { kind: parts[0], loc: parts[1] || '', role: parts[2] || '' }
}

function slotMatchesKey(slot: Slot | undefined, key: string): boolean {
  if (!slot) return false
  const k = parseKey(key)
  if (k.kind === 'sleep') return !!slot.sleep
  if (slot.sleep) return false
  if (k.kind === 'loc') return slot.location === k.loc
  if (k.kind === 'role') return (slot.role || '') === k.role
  return false
}

// Mutates `map` (caller passes a fresh copy). clear=true empties only this key's axis.
function applyKeyToHour(map: SlotMap, key: string, hour: number, clear: boolean) {
  const k = parseKey(key)
  const slot: Slot = { ...(map[hour] || { location: '', role: '', sleep: false }) }
  if (k.kind === 'sleep') {
    if (clear) slot.sleep = false
    else {
      slot.sleep = true
      slot.location = ''
      slot.role = ''
    }
  } else if (k.kind === 'loc') {
    if (clear) slot.location = ''
    else {
      slot.location = k.loc
      slot.sleep = false
    }
  } else if (k.kind === 'role') {
    if (clear) slot.role = ''
    else {
      slot.role = k.role
      slot.sleep = false
    }
  }
  if (!slot.sleep && !slot.location && !slot.role) delete map[hour]
  else map[hour] = slot
}

interface Props {
  character: string
  locations: LocationRef[]
  roles: string[]
  initialEnabled: boolean
  initialSlots: Array<{ hour: number; location: string; role: string; sleep: boolean }>
  onSaved?: () => void
}

export function DailyScheduleGrid({
  character,
  locations,
  roles,
  initialEnabled,
  initialSlots,
  onSaved,
}: Props) {
  const { t } = useI18n()
  const { toast } = useToast()

  // Unique locations by name (+ id→canonical map for dedup), mirroring the legacy grid.
  const { uniqueLocs, idToCanonical } = useMemo(() => {
    const byName = new Map<string, { id: string; name: string }>()
    const canon: Record<string, string> = {}
    for (const loc of locations || []) {
      const name = (loc.name || loc.id || '').trim()
      if (!name) continue
      const id = loc.id || name
      if (!byName.has(name)) byName.set(name, { id, name })
      canon[id] = byName.get(name)!.id
    }
    return { uniqueLocs: Array.from(byName.values()), idToCanonical: canon }
  }, [locations])

  const [slots, setSlots] = useState<SlotMap>({})
  const [enabled, setEnabled] = useState(initialEnabled)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [drag, setDrag] = useState({ active: false, key: '', startH: -1, curH: -1 })

  // (Re)build the slot map whenever the loaded schedule changes.
  useEffect(() => {
    const map: SlotMap = {}
    for (const s of initialSlots || []) {
      const sleep = !!s.sleep
      const rawLoc = (s.location || '').trim()
      map[s.hour] = {
        location: sleep ? '' : idToCanonical[rawLoc] || rawLoc,
        role: sleep ? '' : (s.role || '').trim(),
        sleep,
      }
    }
    setSlots(map)
    setEnabled(initialEnabled)
    setDirty(false)
  }, [initialSlots, initialEnabled, idToCanonical])

  const slotsRef = useRef(slots)
  slotsRef.current = slots
  const dragRef = useRef(drag)
  dragRef.current = drag

  const commitDrag = useCallback(() => {
    const d = dragRef.current
    if (!d.active) return
    const minH = Math.min(d.startH, d.curH)
    const maxH = Math.max(d.startH, d.curH)
    setSlots((prev) => {
      const next: SlotMap = {}
      for (const [h, s] of Object.entries(prev)) next[Number(h)] = { ...s }
      // Single-cell toggle: clicking an already-matching cell clears that axis.
      if (minH === maxH && slotMatchesKey(next[minH], d.key)) {
        applyKeyToHour(next, d.key, minH, true)
      } else {
        for (let h = minH; h <= maxH; h++) applyKeyToHour(next, d.key, h, false)
      }
      return next
    })
    setDrag({ active: false, key: '', startH: -1, curH: -1 })
    setDirty(true)
  }, [])

  useEffect(() => {
    const up = () => commitDrag()
    document.addEventListener('mouseup', up)
    return () => document.removeEventListener('mouseup', up)
  }, [commitDrag])

  const save = useCallback(async () => {
    setSaving(true)
    const out: Array<{ hour: number; location: string; role: string; sleep: boolean }> = []
    for (const [hourStr, slot] of Object.entries(slotsRef.current)) {
      const h = Number(hourStr)
      if (slot.sleep) out.push({ hour: h, location: '', role: '', sleep: true })
      else if (slot.location || slot.role)
        out.push({ hour: h, location: slot.location || '', role: slot.role || '', sleep: false })
    }
    out.sort((a, b) => a.hour - b.hour)
    try {
      const res = await apiPost<{ jobs_created?: number }>('/scheduler/daily-schedule', {
        character,
        enabled,
        slots: out,
      })
      setDirty(false)
      toast(
        res.jobs_created !== undefined
          ? t('Schedule saved ({n} jobs)').replace('{n}', String(res.jobs_created))
          : t('Saved'),
      )
      onSaved?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [character, enabled, onSaved, t, toast])

  const clearAll = useCallback(async () => {
    if (!window.confirm(t('Delete the whole daily rhythm for {name}?').replace('{name}', character)))
      return
    setSaving(true)
    try {
      await apiDelete(`/scheduler/daily-schedule?character=${encodeURIComponent(character)}`)
      setSlots({})
      setEnabled(false)
      setDirty(false)
      toast(t('Deleted'))
      onSaved?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [character, onSaved, t, toast])

  // Build the list of rows (key + label) in legacy order: sleep, locations, roles.
  const rows: Array<{ key: string; label: string; header?: string }> = []
  rows.push({ key: '__h_sleep', label: '', header: t('Sleep') })
  rows.push({ key: 'sleep||', label: t('Sleep') })
  rows.push({ key: '__h_loc', label: '', header: t('Locations') })
  if (uniqueLocs.length === 0) rows.push({ key: '__empty_loc', label: t('No locations defined.') })
  else for (const l of uniqueLocs) rows.push({ key: `loc|${l.id}|`, label: l.name })
  rows.push({ key: '__h_role', label: '', header: t('Roles') })
  if (roles.length === 0) rows.push({ key: '__empty_role', label: t('No roles in the character profile.') })
  else for (const r of roles) rows.push({ key: `role||${r}`, label: r })

  const minH = Math.min(drag.startH, drag.curH)
  const maxH = Math.max(drag.startH, drag.curH)

  const cellClass = (key: string, h: number): string => {
    const filled = slotMatchesKey(slots[h], key)
    const isSleep = key.startsWith('sleep')
    const preview = drag.active && key === drag.key && h >= minH && h <= maxH && !filled
    let cls = 'tagesablauf-cell'
    if (filled) cls += ' tagesablauf-filled' + (isSleep ? ' tagesablauf-sleep' : '')
    if (preview) cls += ' tagesablauf-preview'
    return cls
  }

  return (
    <div className="tagesablauf">
      <label className="tagesablauf-enabled">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => {
            setEnabled(e.target.checked)
            setDirty(true)
          }}
        />
        {t('Schedule active')}
      </label>
      <p className="ga-sched-muted">
        {t('Drag across a row to paint hours; click a filled cell to clear it. Empty hours = the character chooses.')}
      </p>

      <div className="tagesablauf-grid">
        <table className="tagesablauf-table">
          <thead>
            <tr>
              <th className="tagesablauf-corner" />
              {Array.from({ length: 24 }, (_, h) => (
                <th key={h}>{String(h).padStart(2, '0')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              if (row.header !== undefined)
                return (
                  <tr key={row.key} className="tagesablauf-loc-header">
                    <td colSpan={25}>{row.header}</td>
                  </tr>
                )
              if (row.key.startsWith('__empty'))
                return (
                  <tr key={row.key}>
                    <td colSpan={25} className="ga-sched-muted" style={{ padding: '6px 8px' }}>
                      {row.label}
                    </td>
                  </tr>
                )
              return (
                <tr key={row.key}>
                  <td className="tagesablauf-row-label">{row.label}</td>
                  {Array.from({ length: 24 }, (_, h) => (
                    <td
                      key={h}
                      className={cellClass(row.key, h)}
                      onMouseDown={(e) => {
                        e.preventDefault()
                        setDrag({ active: true, key: row.key, startH: h, curH: h })
                      }}
                      onMouseEnter={() => {
                        if (dragRef.current.active && dragRef.current.key === row.key)
                          setDrag((d) => ({ ...d, curH: h }))
                      }}
                    />
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="ga-form-row" style={{ marginTop: 8, gap: 8 }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm ga-btn-primary"
          disabled={!dirty || saving}
          onClick={save}
        >
          {saving ? t('Saving…') : t('Save schedule')}
        </button>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={saving} onClick={clearAll}>
          {t('Delete schedule')}
        </button>
      </div>
    </div>
  )
}
