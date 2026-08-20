/**
 * LocationViewSwitch — WHAT a placed location shows inside its outline.
 *
 * Three states, one control, because they are three answers to one question
 * and never combine: the flat 2D map ICON (what the map has always drawn), the
 * rendered ROOFS (the building model from straight above) or the ROOMS (the
 * floor plan's own hulls, as flat colour over the painted ground).
 *
 * THE ROOMS STATE EXISTS FOR THE CASE A PICTURE CANNOT SERVE. A lake is
 * positioned by lining its water and shore rooms up with the terrain painting
 * underneath — the roof of a lake is nothing at all, and a flat icon says
 * nothing about where the water room ends. So the rooms are drawn
 * semi-transparently and the icon is dropped with them: the ground under the
 * shapes is the reference being aligned against.
 *
 * The two gates are not the same kind of gate, and the control says so:
 *   * ROOFS are RENDERED — one scene request plus one WebGL context each — so
 *     under `roofMinPxPerM` they are not fetched at all (`MapTab`), and the
 *     switch says "zoom in" instead of showing empty outlines that read as
 *     "there are no models".
 *   * ROOMS are VECTOR and cost nothing to draw. Their floor is only that at
 *     world zoom a whole location is a few pixels, so its rooms are dots that
 *     clutter exactly the ground somebody is painting. Below it the map falls
 *     back to the icons, which is what it looked like before.
 *
 * It is a VIEW, like the switches in the Display panel above it: nothing here
 * changes the world, and it lives in the tray rather than in the toolbar,
 * where every control arms a gesture (user finding 2026-08-13).
 */
import { useI18n } from '../../i18n/I18nProvider'
import type { LocationView } from './PlacementLayer'

export interface LocationViewSwitchProps {
  value: LocationView
  onChange: (view: LocationView) => void
  /** The locations are switched off entirely — there is nothing to draw a
   *  view into, so the buttons say so instead of doing nothing. */
  locationsOn: boolean
  /** The zoom is under the roofs' budget gate / under the rooms' clutter
   *  floor. Each is only mentioned on its own button. */
  roofsZoomedOut: boolean
  roomsZoomedOut: boolean
  roofMinPxPerM: number
  roomsMinPxPerM: number
}

export function LocationViewSwitch({
  value, onChange, locationsOn, roofsZoomedOut, roomsZoomedOut,
  roofMinPxPerM, roomsMinPxPerM,
}: LocationViewSwitchProps) {
  const { t } = useI18n()
  const zoomHint = (n: number) => t('Zoom in to at least {n} px per metre')
    .replace('{n}', String(n))
  const btn = (v: LocationView, icon: string, label: string, title: string) => (
    <button
      type="button"
      className={'ga-btn ga-btn-sm' + (value === v ? ' ga-btn-primary' : '')}
      title={locationsOn ? title : t('Switch the locations back on to see this')}
      disabled={!locationsOn}
      onClick={() => onChange(v)}
    >
      {icon} {label}
    </button>
  )
  return (
    <div className="ga-map-tray-section">
      <span className="ga-map-tray-title">{t('Location view')}</span>
      <div className="ga-map-view-switch">
        {btn('icons', '🗺', t('Icons'),
          t('The flat 2D map icon of each location, as before.'))}
        {btn('roofs', '🏢', t('Roofs') + (roofsZoomedOut ? ' ' + t('(zoom in)') : ''),
          roofsZoomedOut
            ? zoomHint(roofMinPxPerM)
            : t('Show each building model from above inside its outline. Switch away and back to refresh the pictures.'))}
        {btn('rooms', '🧩', t('Rooms') + (roomsZoomedOut ? ' ' + t('(zoom in)') : ''),
          roomsZoomedOut
            ? zoomHint(roomsMinPxPerM)
            : t('Draw the floor plan’s ground-floor rooms over the terrain, coloured by their floor material and see-through. This is how a place is lined up with the painted ground — a lake against its water, a yard against its path.'))}
      </div>
    </div>
  )
}
