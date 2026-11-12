// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing '../lib/api'; the implementation lives in
// @anima/player-ui so client3d's HUD uses the identical client.
import { apiGet, apiPost } from '@anima/player-ui/api';

export * from '@anima/player-ui/api';

/** The boot hem of the worn outfit (`outfit_options.hem_applicable`, boots spec § 8): whether the control
 *  applies (a worn boot + worn own-mesh trousers that are no skirt), the stored mode, and — in the Wardrobe
 *  payload — `fallback` when a tucked pair is worn over the boot: `too_wide` (the trousers do not fit into the
 *  shaft) or `shaft_too_low` (the shaft ends too close to the ankle to tuck into). */
export type BootHemMode = 'tucked' | 'over'
export interface BootHemState {
  applicable: boolean
  boot_item: string | null
  trousers_item: string | null
  reason: string
  /** The mode in effect (a stored null reads as `over`). */
  mode: BootHemMode
  fallback?: 'too_wide' | 'shaft_too_low' | null
}
export interface OutfitOptions {
  /** The stored choice: null = the default (over). */
  boot_hem: BootHemMode | null
  applicable: BootHemState
}

/** GET /characters/{name}/outfit-options. */
export const getOutfitOptions = (character: string) =>
  apiGet<OutfitOptions>(`/characters/${encodeURIComponent(character)}/outfit-options`)

/** POST /characters/{name}/outfit-options/piece-state — wear a closable piece open or closed (unified-worn-pieces
 *  Addendum A): saved at once like an equip (history, the automatic Build when it is on); 400 with the reason for
 *  a piece that is not closable or not worn. */
export const setPieceState = (character: string, itemId: string, state: 'open' | 'closed') =>
  apiPost<{ piece_state: Record<string, 'open'> }>(
    `/characters/${encodeURIComponent(character)}/outfit-options/piece-state`, { item_id: itemId, state })

/** POST /characters/{name}/outfit-options — `null` stores the default (over); the served model re-assembles. */
export const setOutfitOptions = (character: string, bootHem: BootHemMode | null) =>
  apiPost<OutfitOptions>(`/characters/${encodeURIComponent(character)}/outfit-options`, { boot_hem: bootHem })
