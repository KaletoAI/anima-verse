/**
 * measureKit — the reference sizes behind every metre dial of the world
 * editor, built ONCE for both 3D surfaces (the floor-plan preview and the
 * model panel).
 *
 * Rule (user directive 2026-07-28): "Kein Maß ohne Maßstab." A number field
 * in REAL metres is unusable without something human next to it — a person
 * cannot judge "3.79 m above the model's lower edge" in the abstract. So
 * every such dial comes with
 *
 *   1. the 1.70 m figure, which never scales with anything,
 *   2. a grid/ruler in the unit the dial uses, and
 *   3. the value ON the stretch it means.
 *
 * Because too many rulers at once are their own kind of blind, only the base
 * kit (figure + frame) stays visible; the rest appears while the cursor is IN
 * the field — one measure at a time, with a short linger so the result is
 * still readable after tabbing away (``useActiveMeasure``).
 *
 * three is a PARAMETER, never an import: the world tab loads three lazily and
 * a static import would drag it into the main bundle.
 */
import { useCallback, useRef, useState } from 'react'
import type { Group, Object3D } from 'three'

/** Which dial is being edited — decides WHICH ruler shows. */
export type MeasureKey =
  | 'plan_width' | 'storey' | 'size'
  | 'offset_y' | 'walk_y' | null

/** Colours of the aids. Deliberately not the scene style: these are editor
 *  overlays, not contract geometry. */
const AID = {
  figure: 0xf0f6fc,
  frame: 0x58a6ff,
  grid: 0x8b949e,
  active: 0xe0a356,
  ground: 0x3fb950,
}

/** ~1.5 s of linger, so a value stays readable after leaving the field. */
const LINGER_MS = 1500

/**
 * Focus state for a group of metre dials. `bind(key)` returns the handlers a
 * field needs; the active key drives the 3D aids.
 */
export function useActiveMeasure() {
  const [measure, setMeasure] = useState<MeasureKey>(null)
  const timer = useRef<number | null>(null)
  const bind = useCallback((key: Exclude<MeasureKey, null>) => ({
    onFocus: () => {
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = null
      setMeasure(key)
    },
    onBlur: () => {
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setMeasure(null), LINGER_MS)
    },
  }), [])
  return { measure, bind }
}

type THREE = typeof import('three')

function labelSprite(T: THREE, text: string, color = AID.active) {
  const c = document.createElement('canvas')
  c.width = 256
  c.height = 64
  const ctx = c.getContext('2d')
  if (ctx) {
    ctx.font = '600 34px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.shadowColor = 'rgba(0,0,0,0.95)'
    ctx.shadowBlur = 6
    ctx.fillStyle = `#${color.toString(16).padStart(6, '0')}`
    ctx.fillText(text, 128, 32)
  }
  const sprite = new T.Sprite(new T.SpriteMaterial({
    map: new T.CanvasTexture(c), transparent: true, depthTest: false,
  }))
  sprite.renderOrder = 999
  return sprite
}

function line(T: THREE, pts: [number, number, number][], color: number,
              dashed = false) {
  const geo = new T.BufferGeometry().setFromPoints(
    pts.map(([x, y, z]) => new T.Vector3(x, y, z)))
  const mat = dashed
    ? new T.LineDashedMaterial({ color, dashSize: 0.25, gapSize: 0.18,
      depthTest: false, transparent: true })
    : new T.LineBasicMaterial({ color, depthTest: false, transparent: true })
  const l = new T.Line(geo, mat)
  if (dashed) l.computeLineDistances()
  l.renderOrder = 998
  return l
}

/** A square outline in the XZ plane at height y. */
function square(T: THREE, size: number, y: number, color: number,
                dashed = false) {
  const h = size / 2
  return line(T, [[-h, y, -h], [h, y, -h], [h, y, h], [-h, y, h], [-h, y, -h]],
              color, dashed)
}

/**
 * The 1.70 m reference — a neutral mannequin, NOT a character: it exists to
 * be compared against, so it stays the same shape everywhere and never
 * scales with the model. `heightWorld` is the payload's
 * ``figures.base_height_m_world``.
 */
export function referenceFigure(T: THREE, heightWorld: number): Group {
  const g = new T.Group()
  const h = Math.max(heightWorld, 1e-4)
  const mat = new T.MeshStandardMaterial({
    color: AID.figure, roughness: 0.9, transparent: true, opacity: 0.9,
  })
  const body = new T.Mesh(new T.CapsuleGeometry(0.055 * h, 0.62 * h, 4, 10), mat)
  body.position.y = 0.42 * h
  const head = new T.Mesh(new T.SphereGeometry(0.09 * h, 12, 12), mat)
  head.position.y = 0.9 * h
  g.add(body, head)
  return g
}

export interface MeasureContext {
  /** Which dial is being edited (null = only the base kit). */
  measure: MeasureKey
  /** Reference square in WORLD metres (payload `extent_m` — the footprint
   *  edge, so since E4 the same number as `plan_width_m`). */
  extentM: number
  /** World metres per REAL metre (payload k; 1 since E4). */
  k: number
  /** Real width the square represents (map3d.plan_width_m, 0 = unanchored). */
  planWidthM: number
  /** Storey height in world metres and in real metres. */
  storeyWorld: number
  storeyRealM: number
  /** 1.70 m in world metres (payload figures.base_height_m_world). */
  figureHeightWorld: number
  /** Placed model: footprint width, lower edge and walkable height (world). */
  modelWidthM?: number
  modelBottomY?: number
  walkYWorld?: number
  /** Levels in play — the storey ruler draws a line per level. */
  levels?: number[]
  /** Localized words the labels need (the module has no i18n of its own). */
  words?: { ground?: string; walk?: string; of?: string }
}

/**
 * Build the aids for one context. The caller adds the returned group to its
 * scene and disposes it on the next rebuild (``disposeAids``).
 *
 * The base kit — reference figure at the south-west corner plus the frame —
 * is always in; everything else answers exactly one dial.
 */
export function buildMeasureAids(T: THREE, ctx: MeasureContext): Group {
  const g = new T.Group()
  g.name = 'measure-aids'
  const half = ctx.extentM / 2
  const w = ctx.words || {}

  // ── Base kit ────────────────────────────────────────────────────────
  const fig = referenceFigure(T, ctx.figureHeightWorld)
  fig.position.set(-half - ctx.figureHeightWorld * 0.9, 0,
                   half + ctx.figureHeightWorld * 0.9)
  g.add(fig)
  const figLabel = labelSprite(T, '1,70 m', AID.figure)
  figLabel.scale.set(ctx.figureHeightWorld * 1.6, ctx.figureHeightWorld * 0.4, 1)
  figLabel.position.set(fig.position.x, ctx.figureHeightWorld * 1.15, fig.position.z)
  g.add(figLabel)

  const labelAt = (text: string, x: number, y: number, z: number,
                   color = AID.active) => {
    const s = labelSprite(T, text, color)
    const scale = Math.max(ctx.extentM * 0.16, ctx.figureHeightWorld * 1.4)
    s.scale.set(scale, scale * 0.25, 1)
    s.position.set(x, y, z)
    g.add(s)
  }

  switch (ctx.measure) {
    case 'plan_width': {
      // The anchor edge itself, over a grid of one REAL metre (k = 1 since
      // E4, so one grid step is one world metre too).
      if (ctx.k > 0) {
        const step = ctx.k
        const pts: [number, number, number][] = []
        for (let x = -half; x <= half + 1e-6; x += step) {
          pts.push([x, 0.01, -half], [x, 0.01, half])
        }
        for (let z = -half; z <= half + 1e-6; z += step) {
          pts.push([-half, 0.01, z], [half, 0.01, z])
        }
        const geo = new T.BufferGeometry().setFromPoints(
          pts.map(([x, y, z]) => new T.Vector3(x, y, z)))
        const grid = new T.LineSegments(geo, new T.LineBasicMaterial({
          color: AID.grid, transparent: true, opacity: 0.45, depthTest: false,
        }))
        grid.renderOrder = 997
        g.add(grid)
      }
      g.add(square(T, ctx.extentM, 0.02, AID.active))
      labelAt(ctx.planWidthM > 0
        ? `${ctx.planWidthM.toFixed(1).replace('.', ',')} m`
        : '—', 0, 0.05, half + 0.25)
      break
    }
    case 'storey': {
      const levels = ctx.levels?.length ? ctx.levels : [0]
      const lo = Math.min(...levels, 0)
      const hi = Math.max(...levels, 0)
      for (let lv = lo; lv <= hi + 1; lv++) {
        const y = lv * ctx.storeyWorld
        g.add(square(T, ctx.extentM, y, lv === 0 ? AID.ground : AID.active,
                     lv !== 0))
      }
      labelAt(`${ctx.storeyRealM.toFixed(2).replace('.', ',')} m`,
              -half - 0.3, ctx.storeyWorld / 2, half)
      // The figure moves between two storey lines: is there head room?
      fig.position.set(-half + ctx.figureHeightWorld, 0, half - ctx.figureHeightWorld)
      figLabel.position.set(fig.position.x, ctx.figureHeightWorld * 1.15, fig.position.z)
      break
    }
    case 'size': {
      if (ctx.modelWidthM) {
        g.add(square(T, ctx.modelWidthM, 0.03, AID.active))
        labelAt(`${ctx.modelWidthM.toFixed(2).replace('.', ',')} m ${w.of || 'von'} `
                + `${ctx.extentM.toFixed(2).replace('.', ',')} m`,
                0, 0.06, -half - 0.25)
      }
      g.add(square(T, ctx.extentM, 0.02, AID.frame))
      break
    }
    case 'offset_y': {
      g.add(square(T, ctx.extentM, 0, AID.ground))
      labelAt(w.ground || 'Etage 0', -half - 0.3, 0.04, -half)
      if (ctx.modelBottomY !== undefined) {
        g.add(square(T, ctx.extentM * 0.98, ctx.modelBottomY, AID.active, true))
        labelAt(`${ctx.modelBottomY.toFixed(2).replace('.', ',')} m`,
                half + 0.3, ctx.modelBottomY, -half)
      }
      break
    }
    case 'walk_y': {
      const y = ctx.walkYWorld ?? 0
      g.add(square(T, ctx.extentM, y, AID.ground))
      labelAt(w.walk || 'Boden', -half - 0.3, y + 0.04, -half)
      // The figure STANDS on the dialled ground — that is the acceptance test.
      fig.position.setY(y)
      figLabel.position.setY(y + ctx.figureHeightWorld * 1.15)
      if (ctx.modelBottomY !== undefined) {
        g.add(square(T, ctx.extentM * 0.98, ctx.modelBottomY, AID.grid, true))
      }
      break
    }
    default:
      break
  }
  return g
}

/** Free an aids group's geometries/materials/textures and unhook it. */
export function disposeAids(group: Object3D | null | undefined) {
  if (!group) return
  group.parent?.remove(group)
  group.traverse((o) => {
    const any = o as unknown as {
      geometry?: { dispose?: () => void }
      material?: { dispose?: () => void; map?: { dispose?: () => void } }
    }
    any.geometry?.dispose?.()
    any.material?.map?.dispose?.()
    any.material?.dispose?.()
  })
}
