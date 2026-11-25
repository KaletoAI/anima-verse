import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { loadCharacters, loadItems, loadLocations } from '../../lib/refs'
import type { CharacterRef, ItemRef, LocationRef } from '../../lib/refs'
import { roomLabel } from '../world/worldTypes'
import { questError, startRun } from './api'
import { bindingFor, bindingsComplete, filterOptions, questErrorText } from './questsModel'
import type { Issue, Role, RolePick } from './questsModel'

/**
 * The Start-run dialog: one picker per role of the template, matching the role's kind (D6) — a character
 * standing in the world (no dormant or pooled family member, no temporary NPC), a location, a location plus one of
 * its rooms, or an item. Start stays disabled until every role is bound; a refusal (422 `refused`) lists its
 * issues here and keeps the dialog open. `onStarted` runs after the server accepted the run. A character or item
 * picker has a filter field above it (the item library is long).
 */
export function StartRunDialog({
  open, templateId, title, roles, onClose, onStarted,
}: {
  open: boolean
  templateId: string
  title: string
  roles: Role[]
  onClose: () => void
  onStarted: () => void
}) {
  const { t } = useI18n()
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [locations, setLocations] = useState<LocationRef[]>([])
  const [items, setItems] = useState<ItemRef[]>([])
  const [picks, setPicks] = useState<Record<string, RolePick>>({})
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [issues, setIssues] = useState<Issue[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Every opening starts empty and reloads the world lists (they may have changed since the last start).
  useEffect(() => {
    if (!open) return
    setPicks({})
    setFilters({})
    setIssues([])
    setError('')
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
    loadLocations().then(setLocations).catch(() => setLocations([]))
    loadItems().then(setItems).catch(() => setItems([]))
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const inWorld = useMemo(
    () => characters.filter((c) => !c.temporary && c.status !== 'dormant' && c.status !== 'pooled'),
    [characters],
  )

  if (!open) return null

  const pick = (key: string, patch: RolePick) =>
    setPicks((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }))
  const complete = bindingsComplete(roles, picks)

  const start = async () => {
    if (!complete || busy) return
    const bindings: Record<string, Record<string, string>> = {}
    for (const r of roles) {
      const b = bindingFor(r.kind, picks[r.key] || {})
      if (b) bindings[r.key] = b
    }
    setBusy(true)
    setIssues([])
    setError('')
    try {
      await startRun(templateId, bindings)
      onStarted()
    } catch (e) {
      const err = questError(e)
      if (err.code === 'refused') {
        setIssues(err.issues)
        setError(t('The run was refused:'))
      } else {
        setError(questErrorText(err, t))
      }
    } finally {
      setBusy(false)
    }
  }

  const filterInput = (role: Role) => (
    <input className="ga-input ga-quest-filter" type="search" value={filters[role.key] || ''}
      placeholder={t('Filter…')} aria-label={t('Filter…')}
      onChange={(e) => setFilters((prev) => ({ ...prev, [role.key]: e.target.value }))} />
  )

  const picker = (role: Role) => {
    const p = picks[role.key] || {}
    const query = filters[role.key] || ''
    if (role.kind === 'character') {
      const shown = filterOptions(inWorld, query, (c) => c.display_name || c.name, (c) => c.name, p.name || '')
      return (
        <div className="ga-quest-picker">
          {filterInput(role)}
          <select className="ga-input" value={p.name || ''} onChange={(e) => pick(role.key, { name: e.target.value })}>
            <option value="">{t('— pick a character —')}</option>
            {shown.map((c) => <option key={c.name} value={c.name}>{c.display_name || c.name}</option>)}
          </select>
        </div>
      )
    }
    if (role.kind === 'location' || role.kind === 'room') {
      const rooms = locations.find((l) => l.id === p.location_id)?.rooms || []
      return (
        <div className="ga-form-row">
          <select className="ga-input" value={p.location_id || ''}
            onChange={(e) => pick(role.key, { location_id: e.target.value, room_id: '' })}>
            <option value="">{t('— pick a location —')}</option>
            {locations.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}
          </select>
          {role.kind === 'room' ? (
            <select className="ga-input" value={p.room_id || ''} disabled={!p.location_id}
              onChange={(e) => pick(role.key, { room_id: e.target.value })}>
              <option value="">{t('— pick a room —')}</option>
              {rooms.map((r) => <option key={r.id} value={r.id}>{roomLabel(r, t)}</option>)}
            </select>
          ) : null}
        </div>
      )
    }
    if (role.kind === 'item') {
      const shown = filterOptions(items, query, (i) => i.name || i.id, (i) => i.id, p.item_id || '')
      return (
        <div className="ga-quest-picker">
          {filterInput(role)}
          <select className="ga-input" value={p.item_id || ''} onChange={(e) => pick(role.key, { item_id: e.target.value })}>
            <option value="">{t('— pick an item —')}</option>
            {shown.map((i) => <option key={i.id} value={i.id}>{i.name || i.id}</option>)}
          </select>
        </div>
      )
    }
    return <p className="ga-quest-error">{t('Unknown role kind')}: {role.kind}</p>
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div className="ga-modal ga-quest-start" role="dialog" aria-label={t('Start run')}
        onClick={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Start run')}: {title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body ga-form">
          {roles.length === 0 ? <p className="ga-form-hint">{t('This quest has no roles to bind.')}</p> : null}
          {roles.map((role) => (
            <Field key={role.key} label={role.key} hint={role.description || undefined}>
              {picker(role)}
            </Field>
          ))}
          {error ? (
            <div className="ga-quest-error" role="alert">
              <p>{error}</p>
              {issues.length ? (
                <ul>{issues.map((i, n) => <li key={n}><code>{i.path || '—'}</code> {i.message}</li>)}</ul>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>{t('Cancel')}</button>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={!complete || busy}
            onClick={() => { void start() }}>
            {busy ? t('Starting…') : t('Start')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
