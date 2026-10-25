/**
 * Event pins over the world map (overview): which glyph a location's pin shows
 * and how high it floats. Pure, so the browser and the native client share the
 * cases in shared/test-vectors/event_pins.json (derivations:
 * client3d/scripts/smoke_event_pins.mjs).
 */

/** Metres the pin floats above the top of its place. */
export const PIN_LIFT_M = 3.5;

/** 🔥 when any event of the location is a danger, ❗ for any other event, null without events. */
export function pinGlyph(events: readonly { category?: string | null }[] | null | undefined): string | null {
  if (!events || events.length === 0) return null;
  return events.some((e) => e.category === 'danger') ? '🔥' : '❗';
}

/**
 * World height of a pin: the place's ground datum (`tile.center.y`) plus the
 * place's own height plus the lift — measured from the ground the place stands
 * on, so a pin over a hilltop village is not buried in the hill.
 */
export function pinY(groundY: number, placeHeight: number): number {
  return groundY + placeHeight + PIN_LIFT_M;
}
