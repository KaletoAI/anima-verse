/** Ordinary image generators exclude operations that require special inputs. */
export function isGeneratorBackend(backend: { category?: string; media?: string }): boolean {
  return (backend.media || 'image') === 'image' && !['inpaint', 'upscale'].includes(backend.category || '')
}
