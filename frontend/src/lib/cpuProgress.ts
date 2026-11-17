/** A194: the live line of a CPU job in flight (`app/core/cpu_progress.py` `snapshot`) — the same shape wherever a
 *  running step is shown (Figure tab Build step, piece dialog, Wardrobe chip, Base body Run all). */
export interface CpuProgressPart {
  /** A translatable English label (a de.json key). */
  label: string
  i: number | null
  n: number | null
  /** A second counter of the part, e.g. "frame 7/12"; "" when none. */
  extra: string
}

export interface CpuProgress {
  parts: CpuProgressPart[]
  /** Seconds since the innermost running part started. */
  elapsed_s: number
  /** Linear estimate of what is left, null without an i/n to go by. */
  eta_s: number | null
  /** The same line in English (the task-queue row shows it). */
  line: string
}

type Tr = (s: string) => string

/** "Stage · Sub i/n · 42 s · ~30 s left" — every label through `t`. */
export function cpuProgressText(p: CpuProgress, t: Tr): string {
  const out: string[] = []
  for (const part of p.parts) {
    let text = t(part.label)
    if (part.i !== null && part.n) text = `${text} ${part.i}/${part.n}`
    if (text) out.push(text)
    const frame = /^frame (\d+)\/(\d+)$/.exec(part.extra || '')
    if (frame) out.push(t('frame {n}/{m}').replace('{n}', frame[1]).replace('{m}', frame[2]))
    else if (part.extra) out.push(part.extra)
  }
  out.push(`${Math.round(p.elapsed_s)} s`)
  if (p.eta_s !== null && p.eta_s !== undefined) out.push(t('~{n} s left').replace('{n}', String(Math.round(p.eta_s))))
  return out.join(' · ')
}
