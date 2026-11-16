/**
 * The one status lamp of the Poses tab (Ruling A110): a dot whose colour says the state and whose
 * mouse-over says the reason in plain words. Every sub-tab uses this, so green/yellow/red/grey
 * mean the same everywhere.
 */
export type LampColor = 'green' | 'yellow' | 'red' | 'grey'

const LAMP_COLOR: Record<LampColor, string> = {
  green: '#3fb950', yellow: '#d29922', red: '#f85149', grey: '#6e7681',
}

export function LampDot({ lamp, title }: { lamp: LampColor; title?: string }) {
  return <span title={title} aria-label={title} data-lamp={lamp} style={{ display: 'inline-block', width: 9, height: 9,
    borderRadius: 5, flex: '0 0 9px', background: LAMP_COLOR[lamp] }} />
}
