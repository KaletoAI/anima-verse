import { worldToPx, type MinimapPlace, type MinimapLayout } from './minimap';

/** Pick in drawing coordinates so zoom never changes the clickable radius.
 * Strict improvement preserves list order when dots are equally close. */
export function pickPlaceAt(places: MinimapPlace[], layout: MinimapLayout,
  px: number, py: number, radiusPx = 10): string | null {
  let best: string | null = null;
  let distance = radiusPx;
  for (const place of places) {
    const point = worldToPx(place, layout);
    const d = Math.hypot(point.px - px, point.py - py);
    if (d <= radiusPx && (best === null || d < distance)) {
      best = place.id;
      distance = d;
    }
  }
  return best;
}

export interface TravelPick { id: string; name: string; distanceM: number | null }
