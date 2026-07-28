import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

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

/** Snapshot of the last focused Game-Admin text field (for the assist panels). */
export interface FieldCapture {
  text: string
  isPrompt: boolean
  /** What KIND of prompt this is (Field `promptContext`), '' = unspecified.
   *  Travels to the Prompt Help so its improvement fits the target. */
  promptContext: string
  seq: number
}

/**
 * Context-sensitive editor help + side-panel state. Fields report their topic
 * on focus (setTopic) or a topic plus dynamic items/insert function (setHelp).
 * `panel` holds which side panel (Help / Translate / Prompt Help) is open.
 *
 * The provider additionally captures every focused admin text field (value +
 * prompt classification) so the Translate / Prompt Help panels can take the
 * text over automatically and write an improved prompt back into its field.
 */
interface HelpCtx {
  topic: string | null
  items: HelpItem[]
  insert: ((text: string) => void) | null
  panel: SidePanelId | null
  setPanel: (p: SidePanelId | null) => void
  setTopic: (t: string | null) => void
  setHelp: (t: string | null, opts?: HelpOpts) => void
  /** Latest captured admin text field. Ref-read — pair with `captureTick`. */
  getCapture: () => FieldCapture | null
  /** Bumps whenever a capture happens while a side panel is open. */
  captureTick: number
  /** Write text back into the last captured PROMPT field. False = field gone. */
  writeBack: (text: string) => boolean
}

const Ctx = createContext<HelpCtx>({
  topic: null, items: [], insert: null, panel: null,
  setPanel: () => {}, setTopic: () => {}, setHelp: () => {},
  getCapture: () => null, captureTick: 0, writeBack: () => false,
})

export function HelpProvider({ children }: { children: ReactNode }) {
  const [topic, setTopicState] = useState<string | null>(null)
  const [items, setItems] = useState<HelpItem[]>([])
  const [insert, setInsert] = useState<((text: string) => void) | null>(null)
  const [panel, setPanel] = useState<SidePanelId | null>(null)
  const [captureTick, setCaptureTick] = useState(0)

  // Refs mirror the reactive state for the document-level listeners: captures
  // happen on every focus/keystroke and must not re-render the whole app —
  // `captureTick` only bumps while a panel is actually open to consume it.
  const captureRef = useRef<FieldCapture | null>(null)
  const promptElRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
  const panelRef = useRef<SidePanelId | null>(null)
  const topicRef = useRef<string | null>(null)
  panelRef.current = panel
  topicRef.current = topic

  // setTopic: plain topic without dynamic items (clears them).
  const setTopic = (t: string | null) => { setTopicState(t); setItems([]); setInsert(() => null) }
  // setHelp: topic + dynamic items + insert function.
  const setHelp = (t: string | null, opts?: HelpOpts) => {
    setTopicState(t)
    setItems(opts?.items || [])
    setInsert(() => opts?.insert || null)
  }

  useEffect(() => {
    // Capture focus AND typing of admin text fields. Both events bubble past
    // the React root first, so `topicRef` already reflects the field's help
    // topic (e.g. ImageGenDialog's prompt sets 'image_prompt' on focus).
    const handler = (e: Event) => {
      const el = e.target
      if (!(el instanceof HTMLTextAreaElement) && !(el instanceof HTMLInputElement)) return
      if (el instanceof HTMLInputElement && el.type !== 'text' && el.type !== 'search') return
      if (el.closest('[data-side-panel]')) return
      const helpKey = el.closest('[data-help]')?.getAttribute('data-help') || ''
      const promptContext = el.closest('[data-prompt-context]')
        ?.getAttribute('data-prompt-context') || ''
      const hint = [helpKey, el.name || '', el.id || '', el.placeholder || '',
        el.getAttribute('aria-label') || ''].join(' ').toLowerCase()
      // A declared context IS the statement "this is a prompt field" — the
      // other two are guesses from a class and from the word "prompt".
      const isPrompt = !!promptContext
        || !!el.closest('.ga-prompt-field')
        || hint.includes('prompt')
        || (topicRef.current || '').includes('prompt')
      if (isPrompt) promptElRef.current = el
      captureRef.current = {
        text: el.value, isPrompt, promptContext,
        seq: (captureRef.current?.seq || 0) + 1,
      }
      if (panelRef.current) setCaptureTick((n) => n + 1)
    }
    document.addEventListener('focusin', handler)
    document.addEventListener('input', handler)
    return () => {
      document.removeEventListener('focusin', handler)
      document.removeEventListener('input', handler)
    }
  }, [])

  const getCapture = useCallback(() => captureRef.current, [])

  // Write into the last captured prompt field through the native value setter,
  // then dispatch input + focusout so controlled components AND commit-on-blur
  // fields (TemplateTab prompt fields) pick the new value up.
  const writeBack = useCallback((text: string): boolean => {
    const el = promptElRef.current
    if (!el || !el.isConnected) return false
    const proto = el instanceof HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    if (!setter) return false
    setter.call(el, text)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    return true
  }, [])

  return (
    <Ctx.Provider value={{
      topic, items, insert, panel, setPanel, setTopic, setHelp,
      getCapture, captureTick, writeBack,
    }}>
      {children}
    </Ctx.Provider>
  )
}

export const useHelp = () => useContext(Ctx)
