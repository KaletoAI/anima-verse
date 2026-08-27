/**
 * PICKING A PICTURE OUT OF THIS WORLD'S GALLERIES — the shared plumbing.
 *
 * A slot IS a material of the mesh, and what fills it is chosen where the
 * prop is BUILT (spec-picture-props.md, decision D3), never per placement.
 * This module holds what any such picker needs: the two gallery routes the
 * server accepts as a value, the reading-back of a stored URL, and the three
 * listings behind the dropdowns. No geometry, no fields — only addresses and
 * lists.
 */
import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'

/** The two URL forms the server accepts — building them here is the only
 *  place a picker knows them. */
export const locUrl = (locationId: string, file: string) =>
  `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(file)}`
export const charUrl = (character: string, file: string) =>
  `/characters/${encodeURIComponent(character)}/images/${encodeURIComponent(file)}`

/** WHERE a stored image comes from, read back off the URL — `''` = nothing
 *  chosen, `'loc'` = this location's gallery, `'c:<name>'` = a character. */
export function sourceOf(url: string | undefined): string {
  const m = /^\/characters\/([^/]+)\/images\//.exec(url || '')
  if (m) return `c:${decodeURIComponent(m[1])}`
  return url ? 'loc' : ''
}

/** The file name at the end of either URL form. */
export function fileOf(url: string | undefined): string {
  const tail = (url || '').split('/').pop() || ''
  try { return decodeURIComponent(tail) } catch { return tail }
}

/** The location's gallery, once per mounted editor. */
export function useLocationImages(locationId: string): string[] {
  const [images, setImages] = useState<string[]>([])
  useEffect(() => {
    if (!locationId) { setImages([]); return }
    let stale = false
    apiGet<{ images?: string[] }>(
      `/world/locations/${encodeURIComponent(locationId)}/gallery`)
      .then((d) => { if (!stale) setImages(d.images || []) })
      .catch(() => { if (!stale) setImages([]) })
    return () => { stale = true }
  }, [locationId])
  return images
}

/** The character roster. Only ever called from an IMAGE slot, so a prop
 *  without one costs no request. */
export function useCharacterNames(): string[] {
  const [names, setNames] = useState<string[]>([])
  useEffect(() => {
    let stale = false
    loadCharacters()
      .then((cs) => {
        if (stale) return
        setNames(cs.map((c) => c.name).filter(Boolean)
          .sort((a, b) => a.localeCompare(b)))
      })
      .catch(() => { if (!stale) setNames([]) })
    return () => { stale = true }
  }, [])
  return names
}

/** One character's images (file names — `GET /characters/{name}/images`),
 *  fetched only while that character is the picked source. */
export function useCharacterImages(character: string): string[] {
  const [files, setFiles] = useState<string[]>([])
  useEffect(() => {
    if (!character) { setFiles([]); return }
    let stale = false
    apiGet<{ images?: string[] }>(
      `/characters/${encodeURIComponent(character)}/images`)
      .then((d) => { if (!stale) setFiles(d.images || []) })
      .catch(() => { if (!stale) setFiles([]) })
    return () => { stale = true }
  }, [character])
  return files
}
