// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing '../lib/api'; the implementation lives in
// @anima/player-ui so client3d's HUD uses the identical client.
import { apiGet, apiPost } from '@anima/player-ui/api';

export * from '@anima/player-ui/api';

/** The boot hem of the worn outfit (`outfit_options.hem_applicable`, boots spec § 8): whether the control
 *  applies (a worn boot + worn own-mesh trousers that are no skirt), the stored mode, and — in the Wardrobe
 *  payload — `fallback` `too_wide` when a tucked pair is worn over the boot. */
export type BootHemMode = 'tucked' | 'over'
export interface BootHemState {
  applicable: boolean
  boot_item: string | null
  trousers_item: string | null
  reason: string
  /** The mode in effect (a stored null reads as `over`). */
  mode: BootHemMode
  fallback?: 'too_wide' | null
}
export interface OutfitOptions {
  /** The stored choice: null = the default (over). */
  boot_hem: BootHemMode | null
  applicable: BootHemState
}

/** GET /characters/{name}/outfit-options. */
export const getOutfitOptions = (character: string) =>
  apiGet<OutfitOptions>(`/characters/${encodeURIComponent(character)}/outfit-options`)

/** POST /characters/{name}/outfit-options — `null` stores the default (over); the served model re-assembles. */
export const setOutfitOptions = (character: string, bootHem: BootHemMode | null) =>
  apiPost<OutfitOptions>(`/characters/${encodeURIComponent(character)}/outfit-options`, { boot_hem: bootHem })
