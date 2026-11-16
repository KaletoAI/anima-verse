/**
 * The place preview's figure path without React (Ruling A110 phase 3) — what `PlacePreview` runs per figure and per
 * frame, kept here so `scripts/smoke_place_preview_partners.mjs` drives the SAME code the preview does and compares it
 * with client3d's `Figure` + `NpcManager` path.
 *
 *  - `mountPlaceFigure`: the template cloned under root → pivot → instance, the pivot scaled to the figure height with
 *    the feet on y 0 (`anchorFigureBind`), and the shared `FigureRuntime` on the root;
 *  - `placeInteraction`: the running pair interaction a pair/group place stands for (members = the figures on the same
 *    marker) — a partner's channel engages only within it, as in the game;
 *  - `placePhaseB`: phase B over every figure (`runFigureFrame`), then, when asked, the cross-person readout
 *    (`inspectFrame` over each runtime's `inspect()`).
 */
import type { Object3D } from 'three'
import {
  FIGURE_HEIGHT_M, anchorFigureBind, createFigureRuntime, inspectFrame, runFigureFrame,
  type CollisionPayload, type FigureInspection, type FigureRuntime, type FrameInspection, type FrameLoopState, type SecondaryMotionPayload,
} from '@anima/scene-render'

type Three = typeof import('three')

export interface PlaceFigure { root: Object3D; pivot: Object3D; inst: Object3D; runtime: FigureRuntime }

/** One figure for a place: `skclone` = SkeletonUtils.clone (passed in so three's addons stay lazily loaded). */
export function mountPlaceFigure(THREE: Three, skclone: (o: Object3D) => Object3D, template: Object3D,
  opts: { collision: CollisionPayload | null | undefined; motion: () => SecondaryMotionPayload | undefined;
    figureHeight?: number }): PlaceFigure {
  const height = opts.figureHeight ?? FIGURE_HEIGHT_M
  const inst = skclone(template)
  inst.traverse((o) => { o.frustumCulled = false })
  const pivot = new THREE.Group()
  pivot.add(inst)
  anchorFigureBind(THREE, pivot, height)
  const root = new THREE.Group()
  root.add(pivot)
  root.updateMatrixWorld(true)
  const size = new THREE.Box3().setFromObject(inst).getSize(new THREE.Vector3())
  const runtime = createFigureRuntime(THREE, {
    root, template, motion: opts.motion, collision: opts.collision ?? null,
    tier: 'full', bindRadius: Math.max(height, Math.hypot(size.x / 2, size.y, size.z / 2)),
  })
  return { root, pivot, inst, runtime }
}

/** The pair interaction of a pair/group place: id = the marker, kind = the clip kind, members = its figures. */
export function placeInteraction(kind: string, markerId: string, members: readonly string[]) {
  return { id: markerId, kind, members: [...members] }
}

/** Phase B for the frame's figures, then, when `inspect`, every figure's inspection (entry order) and the frame's
 *  readout (null otherwise). */
export function placePhaseB(entries: readonly { name: string; interaction: ReturnType<typeof placeInteraction> | null;
  figure: FigureRuntime }[], state: FrameLoopState, inspect: boolean):
  { figures: { name: string; inspection: FigureInspection | null }[]; frame: FrameInspection } | null {
  runFigureFrame(entries, state)
  if (!inspect) return null
  const figures = entries.map((e) => ({ name: e.name, inspection: e.figure.inspect() }))
  return { figures, frame: inspectFrame(figures) }
}
