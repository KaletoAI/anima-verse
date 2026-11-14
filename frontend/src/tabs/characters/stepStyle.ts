/** The colours of the step lights and the frame of a tab's right-hand panel (StepRows.tsx). */
import type { CSSProperties } from 'react'
import type { Light } from './hairstylesModel'

export const LIGHT_COLOR: Record<Light, string> = {
  green: 'var(--success, #3fb950)',
  yellow: 'var(--warning, #d29922)',
  red: 'var(--danger, #f85149)',
  grey: 'var(--text-muted, #6e7681)',
  blue: 'var(--accent, #58a6ff)',
}

/** The frame of a tab's right-hand panel (the sub-tabs and their content). */
export const PANEL: CSSProperties = {
  border: '1px solid var(--border, #30363d)', borderRadius: 8, padding: 10, display: 'flex',
  flexDirection: 'column', gap: 8, minWidth: 0,
}
