/**
 * useScenePreview — ONE scene recipe for the whole floor-plan tab.
 *
 * The server composes the entire scene of a location (contract
 * shared/schnittstellen-3d.md part B); the editor draft — including
 * everything unsaved — goes to POST /play/scene-preview and both consumers
 * read the SAME response: the 3D preview renders its primitives and model
 * specs, the 2D plan editor draws its neighbour-ghost openings and the
 * derived exit from the per-room block. Nothing on this side re-derives
 * geometry.
 *
 * Debounced (~300 ms): dragging a room fires per pointermove, one POST per
 * burst is plenty. A model edit (orientation fix, width_m, walk_y, a new
 * mesh) changes the payload without touching the draft — the shared
 * 'anima-model3d-changed' event refetches for that.
 */
import { useEffect, useState } from 'react'
import { postScenePreview } from '../../lib/api'
import type { Map3D, Room, ScenePayload } from './worldTypes'

const DEBOUNCE_MS = 300

export function useScenePreview(locationId: string, rooms: Room[],
                                map3d: Map3D | undefined,
                                fallbackYawDeg: number,
                                terrain: string) {
  const [scene, setScene] = useState<ScenePayload | null>(null)
  const [error, setError] = useState('')
  const [modelVer, setModelVer] = useState(0)

  useEffect(() => {
    const onChanged = () => setModelVer((v) => v + 1)
    window.addEventListener('anima-model3d-changed', onChanged)
    return () => window.removeEventListener('anima-model3d-changed', onChanged)
  }, [])

  useEffect(() => {
    let stale = false
    const timer = window.setTimeout(() => {
      postScenePreview<ScenePayload>({
        id: locationId,
        map_rotation_2d: fallbackYawDeg,
        // The ground outside is the server's call too (plan-grundflaeche.md
        // § 5) — the draft terrain travels along so an edited ground shows
        // up here exactly as the 3D client will render it.
        terrain,
        map3d: map3d || {},
        rooms: rooms.map((r) => ({ id: r.id || '', name: r.name || '',
                                   layout: r.layout })),
      })
        .then((payload) => {
          if (stale) return
          setError('')
          setScene(payload)
        })
        .catch((e) => {
          if (stale) return
          // No silent fallback to a local computation — the consumers say so
          // instead of showing a second, differently-computed picture.
          setError((e as Error).message)
          setScene(null)
        })
    }, DEBOUNCE_MS)
    return () => { stale = true; window.clearTimeout(timer) }
  }, [locationId, rooms, map3d, fallbackYawDeg, terrain, modelVer])

  return { scene, error }
}
