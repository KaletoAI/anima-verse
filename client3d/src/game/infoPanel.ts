import type { MapCharacter, MapEvent, WorldLocation } from '../types';

/** Plain location information, computed by the scene and rendered by the HUD. */
export interface InfoPanelData {
  id: string; name: string; description: string;
  rooms: Array<{ name: string; who: string[] }>;
  present: Array<{ name: string; activity: string; mood: string; travelTo: string; eta: string }>;
  events: Array<{ danger: boolean; text: string }>;
  travel: { distanceM: number | null } | null;
  view: { openable: boolean; open: boolean } | null;
}

export function infoPanelData(loc: WorldLocation, chars: MapCharacter[], events: MapEvent[],
  roomOf: Map<string, string>, view?: { openable: boolean; open: boolean },
  avatar?: { locationId: string; pos: { x: number; z: number } | null }): InfoPanelData {
  // Area rooms are generic zones, so their names add no useful information.
  const area = !!loc.map3d?.area_model
    || ['water', 'forest', 'grass', 'road', 'sand', 'rock'].includes((loc.terrain || '').toLowerCase());
  return {
    id: loc.id, name: loc.name || '', description: loc.description || '',
    rooms: area ? [] : loc.rooms.map(r => ({ name: r.name || '',
      who: chars.filter(c => roomOf.get(c.name) === r.name || roomOf.get(c.name) === r.id).map(c => c.name || '') })),
    present: chars.map(c => ({ name: c.name || '', activity: c.activity || '', mood: c.mood || '',
      travelTo: c.movement_target_name || '', eta: c.travel?.eta_hhmm || '' })),
    events: events.map(e => ({ danger: e.category === 'danger', text: e.text || '' })),
    travel: avatar && avatar.locationId !== loc.id ? {
      distanceM: avatar.pos && loc.pos_x != null && loc.pos_z != null
        ? Math.hypot(loc.pos_x - avatar.pos.x, loc.pos_z - avatar.pos.z) : null,
    } : null,
    view: view ? { ...view } : null,
  };
}
