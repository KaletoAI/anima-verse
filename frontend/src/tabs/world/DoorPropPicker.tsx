/**
 * WHICH door fills an opening — the surfaces that decide it.
 *
 * `DoorPropSelect` is the prop picker: the prop LIBRARY (`/world/props`)
 * narrowed to one dropdown, door-tagged props FIRST, everything else after,
 * since a tagging convention must not hide a library that predates it. A
 * stored id the library no longer knows keeps its place, marked.
 *
 * `DoorStyleSelect` picks one of the shipped Blender door styles
 * (`/world/door-styles`, with a thumbnail), fetched once per page.
 *
 * `OpeningDoorProp` is the opening panel's control. The stored state is
 * FOUR-VALUED and every value is a different sentence (spec
 * 2026-10-19-blender-doors § 3.1, `scene_recipe.door_choice`):
 *
 *   Location default — no key set; the location's default prop or door style
 *                      fills the hole, else the active hull style's door, else
 *                      the shipped `panel` (outside) / `interior` (inside).
 *   None             — `door_prop: 'none'`; NOTHING hangs here, an open gap,
 *                      whatever the location says.
 *   Door style       — `door_style`; a Blender door built for this hole.
 *   Door prop        — `prop_id`; an image-made prop, the special case.
 *
 * `LocationDoorDefault` is the same choice for the whole location, without
 * "None" (the backend has no location-wide gap).
 *
 * Nothing here computes geometry: the editor writes fields, the server builds
 * and hangs the door (§ B2 `measure: "fit"`).
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import type { PropFull } from '../props/propTypes'

/** THE convention (plan-door-props-texture-slots.md): a door prop is tagged
 *  `door` or filed under that category. Free strings on both sides — there is
 *  no enum to check against, so the comparison is the whole rule. */
function isDoorProp(p: PropFull): boolean {
  if ((p.category || '').trim().toLowerCase() === 'door') return true
  return (p.tags || []).some((tag) => tag.trim().toLowerCase() === 'door')
}

/** The prop library, once per mounted picker. Props change in the Props tab,
 *  not while a floor plan is being edited — the palette next to this one
 *  fetches on the same terms.
 *
 *  `enabled` is how a caller that ALREADY holds the list keeps this from
 *  fetching it a second time (the opening panel needs it for the slot
 *  controls and hands it to the select below it). */
function usePropLibrary(enabled = true): PropFull[] {
  const [props, setProps] = useState<PropFull[]>([])
  useEffect(() => {
    if (!enabled) return
    let stale = false
    apiGet<{ props?: PropFull[] }>('/world/props')
      .then((d) => { if (!stale) setProps(d.props || []) })
      .catch(() => { if (!stale) setProps([]) })
    return () => { stale = true }
  }, [enabled])
  return props
}

export function DoorPropSelect({ value, onChange, emptyLabel, title, width,
                                 library }: {
  /** The chosen prop id ('' = nothing chosen — what `emptyLabel` names). */
  value: string
  onChange: (propId: string) => void
  /** What an empty value MEANS here — the location field and the opening
   *  panel mean two different things by it. */
  emptyLabel: string
  title?: string
  width?: number
  /** The library, where the caller already has it — otherwise it is fetched. */
  library?: PropFull[]
}) {
  const { t } = useI18n()
  const fetched = usePropLibrary(!library)
  const props = library || fetched
  const [doors, others] = useMemo(() => {
    const sorted = [...props].sort((a, b) => a.name.localeCompare(b.name))
    return [sorted.filter(isDoorProp), sorted.filter((p) => !isDoorProp(p))]
  }, [props])
  const dangling = !!value && !props.some((p) => p.id === value)
  const opt = (p: PropFull) => (
    <option key={p.id} value={p.id}>{p.name || p.id}</option>
  )
  return (
    <select
      className="ga-input"
      style={{ width: width || 150 }}
      value={value}
      title={title}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{emptyLabel}</option>
      {dangling ? (
        <option value={value}>{`${value} ${t('(missing)')}`}</option>
      ) : null}
      {doors.length && others.length ? (
        <>
          <optgroup label={t('Doors')}>{doors.map(opt)}</optgroup>
          <optgroup label={t('Other props')}>{others.map(opt)}</optgroup>
        </>
      ) : (
        [...doors, ...others].map(opt)
      )}
    </select>
  )
}

type DoorPropMode = 'default' | 'none' | 'style' | 'custom'

/** The fields this control owns — the ONLY thing it needs to know about
 *  the opening it hangs a door in. Stated structurally so the hull door
 *  (`HullOpening`, which has no `to` and no letter edge) uses the very same
 *  control as a room opening instead of a copy of it. */
export interface DoorPropFields {
  door_style?: string
  prop_id?: string
  door_prop?: 'none'
  hinge?: 'left' | 'right'
}

export function OpeningDoorProp({ opening, defaultPropId, defaultStyle, onPatch }: {
  opening: DoorPropFields
  /** The location's own default, so the first option can say WHICH door it
   *  is instead of leaving the reader to go and look. */
  defaultPropId?: string
  defaultStyle?: string
  onPatch: (patch: DoorPropFields) => void
}) {
  const { t } = useI18n()
  const props = usePropLibrary()
  const styles = useDoorStyles()
  const stored: DoorPropMode = opening.prop_id ? 'custom'
    : opening.door_style ? 'style' : opening.door_prop === 'none' ? 'none' : 'default'
  const [pending, setPending] = useState<DoorPropMode>('default')
  const mode = stored === 'default' ? pending : stored
  const defaultName = defaultPropId
    ? props.find((p) => p.id === defaultPropId)?.name || defaultPropId
    : styles.find((s) => s.id === defaultStyle)?.name || defaultStyle
  const setMode = (next: DoorPropMode) => {
    setPending(next === 'custom' || next === 'style' ? next : 'default')
    onPatch({ prop_id: undefined, door_style: undefined,
      door_prop: next === 'none' ? 'none' : undefined })
  }

  return (
    <>
      <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Choose the location default, an open gap, a door style or a door prop.')}>
        {t('Door')}
        <select
          className="ga-input"
          style={{ width: 130 }}
          value={mode}
          onChange={(e) => setMode(e.target.value as DoorPropMode)}
        >
          <option value="default">
            {defaultName
              ? `${t('Location default')} (${defaultName})`
              : t('Location default')}
          </option>
          <option value="none">{t('None')}</option>
          <option value="style">{t('Door style')}</option>
          <option value="custom">{t('Door prop')}</option>
        </select>
      </label>
      {mode === 'style' ? <DoorStyleSelect value={opening.door_style || ''}
        onChange={(id) => onPatch({ door_style: id || undefined, prop_id: undefined, door_prop: undefined })} /> : null}
      {mode === 'custom' ? (
        <DoorPropSelect
          value={opening.prop_id || ''}
          onChange={(id) => onPatch({ prop_id: id || undefined, door_style: undefined,
                                      door_prop: undefined })}
          emptyLabel={t('— pick a prop —')}
          title={t('The prop hung in THIS opening — it overrides the location default.')}
          library={props}
        />
      ) : null}
      {/* The one thing that only means something where a leaf actually HANGS:
          which jamb it turns about. */}
      {mode !== 'none' ? (
        <>
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Left or right as seen from inside this room, facing the door.')}>
            {t('Hinge')}
            <select
              className="ga-input"
              style={{ width: 90 }}
              value={opening.hinge || 'left'}
              onChange={(e) => onPatch({ hinge: e.target.value as 'left' | 'right' })}
            >
              <option value="left">{t('Left')}</option>
              <option value="right">{t('Right')}</option>
            </select>
          </label>
        </>
      ) : null}
    </>
  )
}

interface DoorStyle {
  id: string
  name: string
  description: string
  thumbnail_url?: string
}

// Shipped styles do not change while the admin page is open. Share even an
// in-flight request across the location and opening pickers.
let styleLibrary: Promise<DoorStyle[]> | undefined
function useDoorStyles(): DoorStyle[] {
  const [styles, setStyles] = useState<DoorStyle[]>([])
  useEffect(() => {
    let stale = false
    styleLibrary ??= apiGet<{ styles: DoorStyle[] }>('/world/door-styles')
      .then((data) => data.styles).catch(() => [])
    void styleLibrary.then((data) => { if (!stale) setStyles(data) })
    return () => { stale = true }
  }, [])
  return styles
}

function DoorStyleSelect({ value, onChange }: {
  value: string
  onChange: (id: string) => void
}) {
  const { t } = useI18n()
  const styles = useDoorStyles()
  const chosen = styles.find((s) => s.id === value)
  return <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
    <select className="ga-input" value={value} aria-label={t('Door style')}
      title={chosen?.description} onChange={(e) => onChange(e.target.value)}>
      <option value="">{t('— pick a door style —')}</option>
      {value && !chosen ? <option value={value}>{value} {t('(missing)')}</option> : null}
      {styles.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}
    </select>
    {chosen?.thumbnail_url ? <img src={chosen.thumbnail_url} alt={chosen.name}
      loading="lazy" width={48} height={48} style={{ objectFit: 'contain' }} /> : null}
  </span>
}

export function LocationDoorDefault({ propId, styleId, onChange }: {
  propId: string
  styleId: string
  onChange: (propId: string, styleId: string) => void
}) {
  const { t } = useI18n()
  const stored = propId ? 'custom' : styleId ? 'style' : 'default'
  const [pending, setPending] = useState('default')
  const mode = stored === 'default' ? pending : stored
  return <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center', fontSize: '0.82em' }}>
    <label>{t('Door')}
      <select className="ga-input" value={mode} onChange={(e) => {
        setPending(e.target.value)
        onChange('', '')
      }}>
        <option value="default">{t('Building default (from the hull style)')}</option>
        <option value="style">{t('Door style')}</option>
        <option value="custom">{t('Door prop')}</option>
      </select>
    </label>
    {mode === 'style' ? <DoorStyleSelect value={styleId} onChange={(id) => onChange('', id)} /> : null}
    {mode === 'custom' ? <DoorPropSelect value={propId} onChange={(id) => onChange(id, '')}
      emptyLabel={t('— pick a prop —')} /> : null}
  </div>
}
