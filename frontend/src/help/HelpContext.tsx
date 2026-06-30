import { createContext, useContext, useState, type ReactNode } from 'react'

/**
 * Kontextsensitive Editor-Hilfe. Felder melden beim Fokus ihr Hilfe-Thema
 * (z.B. "condition", "prompt_modifier"); das ausklappbare HelpPanel zeigt die
 * passenden Optionen. Topic bleibt bestehen bis ein anderes Feld fokussiert wird
 * (so kann man ins Panel klicken/scrollen, ohne dass es leer wird).
 */
interface HelpCtx {
  topic: string | null
  setTopic: (t: string | null) => void
  open: boolean
  setOpen: (b: boolean) => void
}

const Ctx = createContext<HelpCtx>({
  topic: null, setTopic: () => {}, open: false, setOpen: () => {},
})

export function HelpProvider({ children }: { children: ReactNode }) {
  const [topic, setTopic] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  return <Ctx.Provider value={{ topic, setTopic, open, setOpen }}>{children}</Ctx.Provider>
}

export const useHelp = () => useContext(Ctx)
