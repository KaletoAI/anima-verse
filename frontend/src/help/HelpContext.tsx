import { createContext, useContext, useState, type ReactNode } from 'react'

/** One help item: static hint (from the server) or dynamic insert token. */
export interface HelpItem { code?: string; text: string; copy?: boolean; insert?: string }

interface HelpOpts {
  /** Dynamic items (e.g. {token} placeholders of a prompt field). */
  items?: HelpItem[]
  /** Inserts text at the cursor position of the focused field. */
  insert?: (text: string) => void
}

/** The side panels docked to the right edge — at most one is open at a time. */
export type SidePanelId = 'help' | 'translate' | 'prompt'

/**
 * Context-sensitive editor help + side-panel state. Fields report their topic
 * on focus (setTopic) or a topic plus dynamic items/insert function (setHelp).
 * `panel` holds which side panel (Help / Translate / Prompt Help) is open.
 */
interface HelpCtx {
  topic: string | null
  items: HelpItem[]
  insert: ((text: string) => void) | null
  panel: SidePanelId | null
  setPanel: (p: SidePanelId | null) => void
  setTopic: (t: string | null) => void
  setHelp: (t: string | null, opts?: HelpOpts) => void
}

const Ctx = createContext<HelpCtx>({
  topic: null, items: [], insert: null, panel: null,
  setPanel: () => {}, setTopic: () => {}, setHelp: () => {},
})

export function HelpProvider({ children }: { children: ReactNode }) {
  const [topic, setTopicState] = useState<string | null>(null)
  const [items, setItems] = useState<HelpItem[]>([])
  const [insert, setInsert] = useState<((text: string) => void) | null>(null)
  const [panel, setPanel] = useState<SidePanelId | null>(null)

  // setTopic: plain topic without dynamic items (clears them).
  const setTopic = (t: string | null) => { setTopicState(t); setItems([]); setInsert(() => null) }
  // setHelp: topic + dynamic items + insert function.
  const setHelp = (t: string | null, opts?: HelpOpts) => {
    setTopicState(t)
    setItems(opts?.items || [])
    setInsert(() => opts?.insert || null)
  }

  return (
    <Ctx.Provider value={{ topic, items, insert, panel, setPanel, setTopic, setHelp }}>
      {children}
    </Ctx.Provider>
  )
}

export const useHelp = () => useContext(Ctx)
