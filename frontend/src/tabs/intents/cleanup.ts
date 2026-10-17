type CleanupAction = 'duplicate' | 'deadline' | 'cleanup' | 'cap'

export interface CleanupResult {
  dry_run: boolean
  counts: Partial<Record<CleanupAction, number>>
  items: Array<{ id: string; owner: string; title: string; action: CleanupAction; expires_at?: string }>
}

export const ACTION_LABELS: Record<CleanupAction, string> = {
  duplicate: 'duplicate merged',
  deadline: 'deadline added',
  cleanup: 'ended by clean-up',
  cap: 'limit reached',
}

export function cleanupCounts(result: CleanupResult, t: (text: string) => string): string {
  return Object.entries(ACTION_LABELS)
    .map(([action, label]) => `${t(label)}: ${result.counts[action as CleanupAction] || 0}`)
    .join(' · ')
}

