/** Display names for generated pose clips: which motion model made a clip
 *  (`source.generator` in its sidecar) and a short form of its licence. Names
 *  of models and licences are not translated. */
const GENERATOR_NAMES: Record<string, string> = { unimate: 'UniMate', kimodo: 'Kimodo' }
const LICENSE_SHORT: Record<string, string> = {
  'CC-BY-NC-4.0': 'NC',
  'NVIDIA-Open-Model-License': 'NVIDIA OML',
}

export function generatorName(generator: string | undefined | null): string {
  const g = (generator || '').trim()
  return GENERATOR_NAMES[g] || g
}

export function licenseShort(license: string | undefined | null): string {
  const l = (license || '').trim()
  return LICENSE_SHORT[l] || l
}

/** Badge text for a clip generated for a pose ("Kimodo · NVIDIA OML"), or ''
 *  for every other clip. The server reports a generated clip's origin as its
 *  generator, so both must agree. */
export function generatedBadge(clip: { generator?: string; origin?: string; license?: string }): string {
  if (!clip.generator || clip.origin !== clip.generator) return ''
  const short = licenseShort(clip.license)
  return short ? `${generatorName(clip.generator)} · ${short}` : generatorName(clip.generator)
}
