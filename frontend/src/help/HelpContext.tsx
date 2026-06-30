import { createContext, useContext, useState, type ReactNode } from 'react'

/** Ein Hilfe-Item: statischer Hinweis (vom Server) oder dynamisches Insert-Token. */
export interface HelpItem { code?: string; text: string; copy?: boolean; insert?: string }

interface HelpOpts {
  /** Dynamische Items (z.B. {token}-Platzhalter eines Prompt-Felds). */
  items?: HelpItem[]
  /** Fügt Text an der Cursor-Position des fokussierten Felds ein. */
  insert?: (text: string) => void
}

/**
 * Kontextsensitive Editor-Hilfe. Felder melden beim Fokus ihr Thema (setTopic)
 * oder ein Thema + dynamische Items/Insert-Funktion (setHelp). Das ausklappbare
 * HelpPanel zeigt das passende Topic vom Server plus die dynamischen Items.
 */
interface HelpCtx {
  topic: string | null
  items: HelpItem[]
  insert: ((text: string) => void) | null
  open: boolean
  setOpen: (b: boolean) => void
  setTopic: (t: string | null) => void
  setHelp: (t: string | null, opts?: HelpOpts) => void
}

const Ctx = createContext<HelpCtx>({
  topic: null, items: [], insert: null, open: false,
  setOpen: () => {}, setTopic: () => {}, setHelp: () => {},
})

export function HelpProvider({ children }: { children: ReactNode }) {
  const [topic, setTopicState] = useState<string | null>(null)
  const [items, setItems] = useState<HelpItem[]>([])
  const [insert, setInsert] = useState<((text: string) => void) | null>(null)
  const [open, setOpen] = useState(false)

  // setTopic: einfaches Thema ohne dynamische Items (leert sie).
  const setTopic = (t: string | null) => { setTopicState(t); setItems([]); setInsert(() => null) }
  // setHelp: Thema + dynamische Items + Insert-Funktion.
  const setHelp = (t: string | null, opts?: HelpOpts) => {
    setTopicState(t)
    setItems(opts?.items || [])
    setInsert(() => opts?.insert || null)
  }

  return (
    <Ctx.Provider value={{ topic, items, insert, open, setOpen, setTopic, setHelp }}>
      {children}
    </Ctx.Provider>
  )
}

export const useHelp = () => useContext(Ctx)
