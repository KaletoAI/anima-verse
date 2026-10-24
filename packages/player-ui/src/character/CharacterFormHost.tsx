import { createContext, useContext, type ReactNode } from 'react'

/** One help item: static hint (from the server) or dynamic insert token. */
export interface HelpItem { code?: string; text: string; copy?: boolean; insert?: string }

export interface HelpOpts {
  /** Dynamic items (e.g. {token} placeholders of a prompt field). */
  items?: HelpItem[]
  /** Inserts text at the cursor position of the focused field. */
  insert?: (text: string) => void
}

/** Optional app-owned services; player HUDs can render forms without admin help. */
export interface CharacterFormHost {
  setTopic?: (t: string | null) => void
  setHelp?: (t: string | null, opts?: HelpOpts) => void
  renderImageDialog?: (ctl: FieldImageDialogControl) => ReactNode
}

export interface FieldImageSubmit {
  prompt: string
  backend?: string
  loras?: Array<{ name: string; strength: number }> | null
  use_source_as_reference?: boolean
  negative_prompt?: string
}

export interface FieldImageDialogControl {
  prompt: string
  // The admin dialog needs the character and current portrait for its reference controls.
  character: string
  sourceImageUrl?: string
  onSubmit: (payload: FieldImageSubmit) => void | Promise<void>
  onClose: () => void
}

export const CharacterFormHostContext = createContext<CharacterFormHost>({})
export function useCharacterFormHost(): CharacterFormHost {
  return useContext(CharacterFormHostContext)
}
