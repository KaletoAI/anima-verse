/**
 * WHAT GOES INTO A PROP'S TEXTURE SLOTS — one control per slot the prop
 * declares (v5, plan-door-props-texture-slots.md).
 *
 * A slot IS a material of the mesh: the prop editor lists them (`slots`,
 * `{name, kind}`), and this is where a PLACEMENT says what fills them. The
 * component is generic over that list — it renders whatever the prop declares
 * and nothing else, so a new slot on a new prop needs no code here. It writes
 * fields only: no geometry, no URL building beyond the two gallery routes the
 * server accepts.
 *
 *   kind `image`     → a picture out of a gallery. Source first (this
 *                      location, or a character), then the file. The stored
 *                      value IS the URL, so the source is read back off it and
 *                      needs no state of its own.
 *   kind `material`  → a look. One preset today (`glass`), the list mirrors
 *                      `MATERIAL_PRESETS` of @anima/scene-render — a preset no
 *                      renderer draws must not be offerable.
 *
 * Both offer "None", which REMOVES the key: an empty value is not a value.
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import { MATERIAL_PRESETS } from '@anima/scene-render'
import type { PropSlot } from '../props/propTypes'
import type { SlotValue } from './worldTypes'

/** The two URL forms the server accepts (`props.sanitize_slot_values`) —
 *  building them here is the only place the editor knows them. */
const locUrl = (locationId: string, file: string) =>
  `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(file)}`
const charUrl = (character: string, file: string) =>
  `/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(file)}`

/** WHERE a stored image comes from, read back off the URL — `''` = nothing
 *  chosen, `'loc'` = this location's gallery, `'c:<name>'` = a character. */
function sourceOf(url: string | undefined): string {
  const m = /^\/characters\/([^/]+)\/images\//.exec(url || '')
  if (m) return `c:${decodeURIComponent(m[1])}`
  return url ? 'loc' : ''
}

/** The file name at the end of either URL form. */
function fileOf(url: string | undefined): string {
  const tail = (url || '').split('/').pop() || ''
  try { return decodeURIComponent(tail) } catch { return tail }
}

/** The location's gallery, once per mounted editor. */
function useLocationImages(locationId: string): string[] {
  const [images, setImages] = useState<string[]>([])
  useEffect(() => {
    if (!locationId) { setImages([]); return }
    let stale = false
    apiGet<{ images?: string[] }>(
      `/world/locations/${encodeURIComponent(locationId)}/gallery`)
      .then((d) => { if (!stale) setImages(d.images || []) })
      .catch(() => { if (!stale) setImages([]) })
    return () => { stale = true }
  }, [locationId])
  return images
}

/** The character roster. Only ever called from an IMAGE slot, so a prop
 *  without one costs no request. */
function useCharacterNames(): string[] {
  const [names, setNames] = useState<string[]>([])
  useEffect(() => {
    let stale = false
    loadCharacters()
      .then((cs) => {
        if (stale) return
        setNames(cs.map((c) => c.name).filter(Boolean)
          .sort((a, b) => a.localeCompare(b)))
      })
      .catch(() => { if (!stale) setNames([]) })
    return () => { stale = true }
  }, [])
  return names
}

/** One character's images (file names — `GET /characters/{name}/images`),
 *  fetched only while that character is the picked source. */
function useCharacterImages(character: string): string[] {
  const [files, setFiles] = useState<string[]>([])
  useEffect(() => {
    if (!character) { setFiles([]); return }
    let stale = false
    apiGet<{ images?: string[] }>(
      `/characters/${encodeURIComponent(character)}/images`)
      .then((d) => { if (!stale) setFiles(d.images || []) })
      .catch(() => { if (!stale) setFiles([]) })
    return () => { stale = true }
  }, [character])
  return files
}

function ImageSlot({ slot, value, locationId, onValue }: {
  slot: PropSlot
  value: SlotValue | undefined
  locationId: string
  onValue: (next: SlotValue | undefined) => void
}) {
  const { t } = useI18n()
  const stored = value?.image || ''
  const locImages = useLocationImages(locationId)
  const names = useCharacterNames()
  // "Source picked, no picture yet" is not a storable state — an empty value
  // is no value, so the stored URL would read back as "None" and the select
  // would snap shut the moment it was opened. The same problem the door-prop
  // picker has, and the same answer: a local flag, consulted only while
  // nothing is stored.
  const [pendingSource, setPendingSource] = useState('')
  const source = stored ? sourceOf(stored) : pendingSource
  const character = source.startsWith('c:') ? source.slice(2) : ''
  const charImages = useCharacterImages(character)
  const files = character ? charImages : locImages
  const picked = fileOf(stored)
  // A stored file the gallery does not list keeps its place — a deleted
  // picture must not silently empty the frame on the next save. It is only
  // CALLED missing once the list has actually arrived; before that it is
  // simply the current pick.
  const ownOption = !!picked && !files.includes(picked)
  const missing = ownOption && files.length > 0

  const setSource = (next: string) => {
    setPendingSource(next)
    // Changing the source cannot keep the file: it names a picture in the
    // other gallery. Staying on the same source keeps it.
    if (next !== sourceOf(stored)) onValue(undefined)
  }
  const setFile = (file: string) => {
    if (!file) { onValue(undefined); return }
    onValue({ image: character ? charUrl(character, file) : locUrl(locationId, file) })
  }

  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      <select
        className="ga-input"
        style={{ width: 110 }}
        value={source}
        title={t('Where the picture for this slot comes from.')}
        onChange={(e) => setSource(e.target.value)}
      >
        <option value="">{t('None')}</option>
        <option value="loc">{t('This place')}</option>
        {names.map((n) => (
          <option key={n} value={`c:${n}`}>{n}</option>
        ))}
      </select>
      {source ? (
        <select
          className="ga-input"
          style={{ width: 150 }}
          value={picked}
          title={t('Which picture fills the “{slot}” surface of this prop.')
            .replace('{slot}', slot.name)}
          onChange={(e) => setFile(e.target.value)}
        >
          <option value="">{t('— pick a picture —')}</option>
          {ownOption ? (
            <option value={picked}>
              {missing ? `${picked} ${t('(missing)')}` : picked}
            </option>
          ) : null}
          {files.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      ) : null}
    </span>
  )
}

function MaterialSlot({ slot, value, onValue }: {
  slot: PropSlot
  value: SlotValue | undefined
  onValue: (next: SlotValue | undefined) => void
}) {
  const { t } = useI18n()
  return (
    <select
      className="ga-input"
      style={{ width: 110 }}
      value={value?.preset || ''}
      title={t('Which look the “{slot}” surface of this prop gets.')
        .replace('{slot}', slot.name)}
      onChange={(e) => onValue(e.target.value ? { preset: e.target.value } : undefined)}
    >
      <option value="">{t('None')}</option>
      {MATERIAL_PRESETS.map((p) => (
        <option key={p} value={p}>{p === 'glass' ? t('Glass') : p}</option>
      ))}
    </select>
  )
}

export function SlotValuesEditor({ slots, values, locationId, onChange }: {
  /** What the PROP declares — the whole list, in the prop's own order. */
  slots: PropSlot[] | undefined
  values: Record<string, SlotValue> | undefined
  /** The place whose gallery the image picker offers first. */
  locationId: string
  /** The complete new map, or `undefined` once nothing is filled any more. */
  onChange: (next: Record<string, SlotValue> | undefined) => void
}) {
  const { t } = useI18n()
  const list = useMemo(() => (slots || []).filter((s) => s?.name), [slots])
  if (!list.length) return null
  const set = (name: string, next: SlotValue | undefined) => {
    const merged: Record<string, SlotValue> = { ...(values || {}) }
    if (next) merged[name] = next
    else delete merged[name]
    onChange(Object.keys(merged).length ? merged : undefined)
  }
  return (
    <>
      {list.map((slot) => (
        <label
          key={slot.name}
          style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
          title={slot.kind === 'image'
            ? t('This prop has a fillable picture surface. The picture is shown on it in the 3D client and in the preview.')
            : t('This prop has a fillable material surface — give it a look instead of a picture.')}
        >
          {slot.kind === 'image' ? '🖼' : '◇'} {slot.name}
          {slot.kind === 'image' ? (
            <ImageSlot slot={slot} locationId={locationId}
              value={values?.[slot.name]}
              onValue={(next) => set(slot.name, next)} />
          ) : (
            <MaterialSlot slot={slot} value={values?.[slot.name]}
              onValue={(next) => set(slot.name, next)} />
          )}
        </label>
      ))}
    </>
  )
}
