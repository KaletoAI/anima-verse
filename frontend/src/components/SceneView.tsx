/**
 * SceneView — hybrid renderer for a list of scene lines (dialogue + narrated
 * ambient). Shared on purpose: the Observer tab uses it now, the player room UI
 * (Phase 2) reuses the same component. plan-room-conversation.
 *
 * It renders whatever it is handed — it does NOT filter. Confidentiality is
 * enforced upstream (the subjective stream never carries whispered content).
 */
import type { ReactNode } from 'react'
import { useI18n } from '../i18n/I18nProvider'

export interface SceneLine {
  ts: string
  speaker?: string
  content?: string
  /** perception kind (spoken_self|in_room|whisper_meta|distant_shout) or 'utterance' for objective rows */
  kind?: string
  addressees?: string[]
  /** objective view only: whisper|normal|shout */
  volume?: string
  meta?: Record<string, unknown>
}

function clockOf(ts: string): string {
  // ISO -> HH:MM:SS, best-effort.
  const d = new Date(ts)
  return isNaN(d.getTime()) ? ts : d.toLocaleTimeString()
}

function addresseesOf(line: SceneLine): string[] {
  if (line.addressees && line.addressees.length) return line.addressees
  const m = line.meta?.addressees
  return Array.isArray(m) ? (m as string[]) : []
}

function speakerOf(line: SceneLine): string {
  return line.speaker || (line.meta?.speaker as string) || '?'
}

export interface ThinkingInfo {
  name: string
  /** true = antwortet (sichtbarer Chat-Turn), false = denkt (Hintergrund). */
  responding?: boolean
}

export function SceneView({ lines, emptyHint, thinking }: { lines: SceneLine[]; emptyHint?: string; thinking?: ThinkingInfo[] }) {
  const { t } = useI18n()
  const thinkers = thinking || []
  if (!lines.length && !thinkers.length) {
    return <div className="ga-list-empty">{emptyHint || t('No lines')}</div>
  }
  return (
    <div className="ga-list" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {lines.map((line, i) => (
        <SceneRow key={i} line={line} />
      ))}
      {thinkers.map((info) => (
        <div key={`thinking-${info.name}`} className="ga-list-row" style={{ display: 'flex', gap: 8, alignItems: 'baseline', opacity: 0.75 }}>
          <span className="ga-list-row-sub" style={{ fontVariantNumeric: 'tabular-nums', opacity: 0.5, fontSize: '0.75em' }} />
          <span className="ga-list-row-main" style={{ flex: 1 }}>
            <strong>{info.name}</strong>{' '}
            <span style={{ opacity: 0.7, fontStyle: 'italic' }}>
              {info.responding ? t('is responding') : t('is thinking')}
            </span>{' '}
            <span className="player-thinking-dots" aria-hidden="true">
              <span className="player-thinking-dot" />
              <span className="player-thinking-dot" />
              <span className="player-thinking-dot" />
            </span>
          </span>
        </div>
      ))}
    </div>
  )
}

function SceneRow({ line }: { line: SceneLine }) {
  const { t } = useI18n()
  const speaker = speakerOf(line)
  const addr = addresseesOf(line)
  const time = clockOf(line.ts)

  // Event-Verdikt (gelöst/ungelöst) — eigener farbiger Block unter dem Erzähler.
  const verdict = line.meta?.event_verdict as string | undefined
  if (verdict === 'resolved' || verdict === 'unresolved') {
    const resolved = verdict === 'resolved'
    return (
      <div className="ga-list-row" style={{
        display: 'flex', gap: 8, alignItems: 'baseline', padding: '4px 8px',
        margin: '2px 0', borderRadius: 6,
        borderLeft: `4px solid ${resolved ? '#3fa45a' : '#e0843c'}`,
        background: resolved ? 'rgba(63,164,90,0.16)' : 'rgba(224,132,60,0.16)',
      }}>
        <span style={{ flex: '0 0 auto', fontSize: '0.75em', fontWeight: 700,
          color: resolved ? '#7ed79a' : '#f0a868' }}>
          {resolved ? `✓ ${t('Event resolved')}` : `⚠ ${t('Event unresolved')}`}
        </span>
        <span style={{ flex: 1, opacity: 0.85, fontStyle: 'italic' }}>{line.content}</span>
      </div>
    )
  }

  let body: ReactNode
  let marker = ''

  if (speaker === 'Erzähler') {
    // Erzähler-Narration (Act/Storyteller): farblich abgesetzt — gold + kursiv,
    // damit es sich klar vom Charakter-Dialog unterscheidet.
    body = (
      <span style={{ fontStyle: 'italic', color: '#d6b06a' }}>
        <strong style={{ opacity: 0.85 }}>{speaker}</strong>: {line.content}
      </span>
    )
  } else if (line.kind === 'whisper_meta') {
    // third party: knows the fact, never the content
    const to = addr.length ? addr.join(', ') : t('someone')
    body = <em style={{ opacity: 0.65 }}>🤫 {speaker} {t('whispers something to')} {to}</em>
  } else if (line.kind === 'distant_shout') {
    body = (
      <span style={{ opacity: 0.8 }}>
        ‹ {t('from afar')} — <strong>{speaker}</strong>: {line.content} ›
      </span>
    )
  } else {
    // spoken_self | in_room | objective utterance
    if (line.volume === 'whisper') marker = addr.length ? `(${t('whisper to')} ${addr.join(', ')})` : `(${t('whisper')})`
    else if (line.volume === 'shout') marker = `(${t('shout')})`
    else if (addr.length) marker = `→ ${addr.join(', ')}`
    body = (
      <span>
        <strong>{speaker}</strong>
        {marker ? <span style={{ opacity: 0.6 }}> {marker}</span> : null}: {line.content}
      </span>
    )
  }

  return (
    <div className="ga-list-row" style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
      <span className="ga-list-row-sub" style={{ fontVariantNumeric: 'tabular-nums', opacity: 0.5, fontSize: '0.75em' }}>
        {time}
      </span>
      <span className="ga-list-row-main" style={{ flex: 1 }}>{body}</span>
      <span className="ga-list-row-sub" style={{ opacity: 0.35, fontSize: '0.7em' }}>{line.kind}</span>
    </div>
  )
}
