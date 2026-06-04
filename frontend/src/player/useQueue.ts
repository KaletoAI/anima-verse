/**
 * useQueue — pollt GET /queue/status und destilliert daraus die zwei Dinge, die
 * die Player-UI braucht:
 *   • llmTasks    — laufende LLM-Calls (Chat/Thought/Respond) aus
 *                   providers[*].chat_active. Das sind die "X denkt …"-Einträge
 *                   mit Modell, GPU, Iteration und Dauer-Schätzung.
 *   • trackedTasks — getrackte Bild-/Video-/TTS-/GPU-Tasks (active_tasks).
 *   • thinkingAgents — Set der agent_names mit aktivem LLM-Call (für den
 *                      "denkt …"-Indikator in der Szene / am Figuren-Avatar).
 *
 * plan-room-conversation Phase 3 (Feedback-Schleife sichtbar machen).
 */
import { useEffect, useState } from 'react'
import { apiGet } from '../lib/api'

export interface LLMTaskInfo {
  task_id?: string
  label?: string
  task_type?: string
  agent_name?: string
  model?: string
  provider_name?: string
  started_at?: string
  created_at?: string
  estimated_duration_s?: number
  iteration?: number
  max_iterations?: number
  status?: string
}

export interface TrackedTaskInfo {
  task_id?: string
  label?: string
  task_type?: string
  agent_name?: string
  status?: string
  started_at?: string
  created_at?: string
  provider?: string
  queue_name?: string
}

interface ProviderChannel {
  provider?: string
  type?: string
  healthy?: boolean
  chat_active?: LLMTaskInfo | LLMTaskInfo[] | null
  current_tasks?: LLMTaskInfo[]
}

/** Verfügbarkeit eines Backends (Channel) für die Status-Anzeige.
 *  kind unterscheidet LLM-Provider von Image-Generation-Backends (ComfyUI). */
export interface ChannelStatus {
  key: string
  name: string
  healthy: boolean
  busy: boolean
  kind: 'llm' | 'image'
}

// Nicht-LLM-Tasks, die ebenfalls über Provider-Channels laufen (ComfyUI/TTS) —
// sie gehören ins getrackte active_tasks-Panel, NICHT zu den Chat-LLM-Calls.
const NON_LLM_TYPES = new Set([
  'image_generation', 'tts', 'video_generation', 'animate', 'variant_generation',
])

interface QueueStatus {
  providers?: Record<string, ProviderChannel>
  active_tasks?: TrackedTaskInfo[]
}

/** Pro-Agent: läuft gerade ein LLM-Call, und ist es eine *Antwort* (vs. Gedanke)? */
export interface AgentActivity {
  responding: boolean
  label?: string
}

export interface QueueSnapshot {
  llmTasks: LLMTaskInfo[]
  trackedTasks: TrackedTaskInfo[]
  /** agent_name → Aktivität (für "antwortet …" / "denkt …"-Indikator). */
  agentActivity: Record<string, AgentActivity>
  /** LLM-Backends (Channels) mit Verfügbarkeit + busy-Flag. */
  channels: ChannelStatus[]
}

const EMPTY: QueueSnapshot = { llmTasks: [], trackedTasks: [], agentActivity: {}, channels: [] }

// task_types, bei denen der Character auf jemanden *antwortet* (sichtbarer Chat),
// im Gegensatz zu Hintergrund-Gedanken.
const RESPONDING_TYPES = new Set(['character_talk', 'talk_to', 'send_message', 'chat_stream'])

function collectLLM(providers: Record<string, ProviderChannel> | undefined): LLMTaskInfo[] {
  const out: LLMTaskInfo[] = []
  const seen = new Set<string>()
  for (const ch of Object.values(providers || {})) {
    // ComfyUI/Bild-Backends überspringen — deren Tasks sind keine Chat-LLM-Calls
    // (sie erscheinen separat im getrackten active_tasks-Block).
    if ((ch?.type || '') === 'comfyui') continue
    // chat_active (Streaming/registrierte Chats) + current_tasks (submit-Calls,
    // u.a. der Loop-Respond via run_chat_turn) — beide sind laufende LLM-Calls.
    const ca = ch?.chat_active
    const fromChat = Array.isArray(ca) ? ca : ca ? [ca] : []
    const fromCurrent = ch?.current_tasks || []
    for (const tk of [...fromChat, ...fromCurrent]) {
      if (NON_LLM_TYPES.has(tk.task_type || '')) continue
      const key = tk.task_id || `${tk.agent_name}:${tk.label}`
      if (seen.has(key)) continue
      seen.add(key)
      // provider_name fehlt manchmal am Task → vom Channel ziehen
      out.push({ ...tk, provider_name: tk.provider_name || ch?.provider })
    }
  }
  return out
}

/** Alle Backends (Channels) aus dem providers-Payload: LLM-Provider UND
 * Image-Generation-Backends (ComfyUI), per `kind` unterscheidbar. healthy/busy
 * kommen vom Server (get_combined_status; ComfyUI inkl. Backend-Ping). */
function collectChannels(providers: Record<string, ProviderChannel> | undefined): ChannelStatus[] {
  const out: ChannelStatus[] = []
  for (const [key, ch] of Object.entries(providers || {})) {
    const isImage = (ch?.type || '') === 'comfyui'
    const ca = ch?.chat_active
    const nChat = Array.isArray(ca) ? ca.length : ca ? 1 : 0
    const busy = nChat > 0 || (ch?.current_tasks?.length || 0) > 0
    out.push({ key, name: ch?.provider || key, healthy: !!ch?.healthy, busy,
               kind: isImage ? 'image' : 'llm' })
  }
  // LLM-Provider zuerst, dann Image-Backends; innerhalb der Gruppe alphabetisch.
  out.sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name)
                                        : a.kind === 'llm' ? -1 : 1))
  return out
}

export function useQueue(intervalMs = 2000): QueueSnapshot {
  const [snap, setSnap] = useState<QueueSnapshot>(EMPTY)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await apiGet<QueueStatus>('/queue/status')
        if (!alive) return
        const llmTasks = collectLLM(d.providers)
        const agentActivity: Record<string, AgentActivity> = {}
        for (const tk of llmTasks) {
          const name = (tk.agent_name || '').trim()
          if (!name) continue
          const responding = RESPONDING_TYPES.has(tk.task_type || '')
          // "antwortet" gewinnt gegen "denkt", falls beides für denselben Agent läuft
          if (!agentActivity[name] || responding) {
            agentActivity[name] = { responding, label: tk.label }
          }
        }
        setSnap({ llmTasks, trackedTasks: d.active_tasks || [], agentActivity,
                  channels: collectChannels(d.providers) })
      } catch {
        /* ignore poll errors (api.ts handles auth redirect) */
      }
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [intervalMs])

  return snap
}

/** Sekunden seit started_at (UTC-ISO), oder null wenn unbekannt. */
export function elapsedSeconds(startedAt: string | undefined, nowMs: number): number | null {
  if (!startedAt) return null
  const t = Date.parse(startedAt)
  if (isNaN(t)) return null
  return Math.max(0, Math.round((nowMs - t) / 1000))
}
