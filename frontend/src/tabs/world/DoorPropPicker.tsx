/**
 * WHICH prop fills a door — the two surfaces that decide it.
 *
 * `DoorPropSelect` is the picker itself: the prop LIBRARY (`/world/props`,
 * the same source the placement palette lists) narrowed to one dropdown,
 * because an opening panel is a row of small controls and has no room for a
 * thumbnail grid. Door props are the ones tagged `door` (or in that
 * category) and they come FIRST; everything else follows in a second group,
 * since a brand-new tagging convention must not hide a library that predates
 * it. A stored id the library no longer knows keeps its place, marked — a
 * deleted prop must not silently reset a field.
 *
 * `OpeningDoorProp` is the opening panel's control. The stored state is
 * THREE-VALUED and every value is a different sentence:
 *
 *   Location default — neither key set; the location's `default_door_prop_id`
 *                      fills the hole (`scene_recipe.door_prop_id`).
 *   None             — `door_prop: 'none'`; this hole stays an open passage
 *                      with the flat leaf, whatever the location says.
 *   Custom           — `prop_id`; this opening brings its own door.
 *
 * What the resolved prop SHOWS is not decided here: a picture belongs to the
 * prop, chosen where it is built (spec-picture-props.md, decision D3).
 *
 * Nothing here computes geometry: the editor writes fields, the server hangs
 * the mesh on the hinge (§ B2 `measure: "fit"`).
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import type { PropFull } from '../props/propTypes'
import type { RoomOpening } from './worldTypes'

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

type DoorPropMode = 'default' | 'none' | 'custom'

export function OpeningDoorProp({ opening, defaultPropId, onPatch }: {
  opening: RoomOpening
  /** The location's own default, so the first option can say WHICH door it
   *  is instead of leaving the reader to go and look. */
  defaultPropId?: string
  onPatch: (patch: Partial<RoomOpening>) => void
}) {
  const { t } = useI18n()
  const props = usePropLibrary()
  const stored: DoorPropMode = opening.prop_id
    ? 'custom' : opening.door_prop === 'none' ? 'none' : 'default'
  // "Custom" chosen but no prop picked yet: an empty `prop_id` is not stored,
  // so the stored state is still `default` and the select would snap back on
  // its own. This flag holds the picker open until something is picked. It is
  // per selected opening — the caller keys the component on the selection.
  const [pending, setPending] = useState(false)
  const mode: DoorPropMode = pending && stored === 'default' ? 'custom' : stored

  const setMode = (next: DoorPropMode) => {
    setPending(next === 'custom')
    if (next === 'custom') onPatch({ door_prop: undefined })
    else onPatch({ prop_id: undefined,
                   door_prop: next === 'none' ? 'none' : undefined })
  }

  return (
    <>
      <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Which prop fills this door. “Location default” takes the place’s own door, “None” leaves the hole open with the plain leaf, “Custom” hangs the prop picked beside it.')}>
        {t('Door prop')}
        <select
          className="ga-input"
          style={{ width: 130 }}
          value={mode}
          onChange={(e) => setMode(e.target.value as DoorPropMode)}
        >
          <option value="default">
            {defaultPropId
              ? `${t('Location default')} (${defaultPropId})`
              : t('Location default')}
          </option>
          <option value="none">{t('None')}</option>
          <option value="custom">{t('Custom')}</option>
        </select>
      </label>
      {mode === 'custom' ? (
        <DoorPropSelect
          value={opening.prop_id || ''}
          onChange={(id) => onPatch({ prop_id: id || undefined,
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
