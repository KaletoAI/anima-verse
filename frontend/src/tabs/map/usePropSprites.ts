/**
 * usePropSprites — the top-down pictures of a set of prop meshes, for the
 * map's "Props from above" layer (`PropSpriteLayer`): asked for once each,
 * rendered one at a time in the module chain of `renderPropTopDown`, and
 * handed back as they land. A hook of its own file so the layer file stays
 * components-only (fast refresh).
 */
import { useEffect, useMemo, useReducer } from 'react'
import { propSpriteSync, renderPropTopDown } from '../world/topDownSnapshot'
import type { PropSprite } from '../world/topDownSnapshot'

/** The finished pictures, by URL: a `PropSprite`, or `null` for a mesh that
 *  could not be rendered. A URL not in the map has not landed yet. */
export type PropSpriteMap = ReadonlyMap<string, PropSprite | null>

const NO_SPRITES: PropSpriteMap = new Map()

/**
 * The pictures for a set of mesh URLs — asked for once each, rendered one at
 * a time in the module's chain, and handed back as they land (the hook
 * re-renders its caller per finished picture). `enabled` false asks for
 * nothing and answers nothing: below the zoom gate no picture is rendered,
 * whatever is on screen.
 *
 * The map's identity changes only when a picture lands or the URL set
 * changes, so a consumer may hang memos on it.
 */
export function usePropSprites(urls: readonly string[], enabled: boolean): PropSpriteMap {
  const [version, landed] = useReducer((n: number) => n + 1, 0)
  // ONE string, not the array: the effect and the memo must not re-run
  // because a new array of the same URLs was built.
  const key = useMemo(() => [...new Set(urls)].sort().join('\n'), [urls])
  useEffect(() => {
    if (!enabled || !key) return undefined
    let alive = true
    for (const url of key.split('\n')) {
      if (propSpriteSync(url) !== undefined) continue
      void renderPropTopDown(url).then(() => { if (alive) landed() })
    }
    return () => { alive = false }
  }, [enabled, key])
  return useMemo(() => {
    if (!enabled || !key) return NO_SPRITES
    const out = new Map<string, PropSprite | null>()
    for (const url of key.split('\n')) {
      const s = propSpriteSync(url)
      if (s !== undefined) out.set(url, s)
    }
    return out
    // `version` is the "a picture landed" tick — it is not read, it is what
    // makes the map rebuild so a consumer sees the new picture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key, version])
}
