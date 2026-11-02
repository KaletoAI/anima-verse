import type { GalleryRegenSubmit } from './GalleryPanel'
import type { InstagramAnimateSubmit } from './InstagramPanel'
import type { FieldImageSubmit } from './character/CharacterFormHost'

export function regenPayload(f: {
  prompt: string; names: string[]; useRoom: boolean; useSource: boolean; negative: string
  /** Pose-check override; undefined = the occasion's routing switch decides. */
  poseCheck?: boolean
  backend?: string
  loras?: Array<{ name: string; strength: number }>
}): GalleryRegenSubmit | null {
  const prompt = f.prompt.trim()
  // An empty selection restores detected subjects on the server; it cannot mean nobody.
  if (!prompt || !f.names.length) return null
  return {
    prompt, character_names: f.names, use_room: f.useRoom,
    // Like the photo dialog: Auto sends no backend, but LoRAs picked from the
    // auto-resolved backend's list still go along.
    ...(f.backend ? { backend: f.backend } : {}),
    ...(f.loras?.length ? { loras: f.loras } : {}),
    use_source_as_reference: f.useSource,
    ...(f.negative.trim() ? { negative_prompt: f.negative.trim() } : {}),
    ...(typeof f.poseCheck === 'boolean' ? { pose_check: f.poseCheck } : {}),
  }
}

export function animatePayload(f: { prompt: string; seconds: string }): InstagramAnimateSubmit | null {
  const prompt = f.prompt.trim()
  if (!prompt) return null
  const seconds = parseInt(f.seconds, 10)
  return { prompt, ...(Number.isFinite(seconds) && seconds > 0 ? { seconds } : {}) }
}

export function profileImagePayload(f: {
  prompt: string; useSource: boolean; negative: string
}): FieldImageSubmit | null {
  const prompt = f.prompt.trim()
  if (!prompt) return null
  return {
    prompt, use_source_as_reference: f.useSource,
    ...(f.negative.trim() ? { negative_prompt: f.negative.trim() } : {}),
  }
}
