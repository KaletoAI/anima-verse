/**
 * PlacementLayer — the placed locations of the free world map, drawn INSIDE
 * the `MapCanvas` SVG.
 *
 * SINCE CONTRACT v6 ("Gebiete") A LOCATION IS A DRAWN POLYGON: `map3d.boundary`
 * is a closed point sequence in LOCAL metres around the pin, and the square is
 * only its special case. The polygon is transformed point by point with the ONE
 * § A1.1 mapping (`mapMath.localToWorld`) and then drawn in world metres — no
 * SVG rotation is involved at all, which is why the sign question below does
 * NOT apply to it. The hand-checked case is the same one `footprintScreenCorners`
 * is pinned to (§ B5a): location (pos 10/20, yaw 90), view {cx:10, cz:20,
 * pxPerM:1} on 200×200, boundary point (+5,+5) -> world (15, 15) -> screen
 * (105, 95) — identical to the square's corner, because a square boundary IS
 * that square.
 *
 * A location WITHOUT a boundary keeps the square rendering (transition state,
 * v6 says a location without a boundary has no area at all — the square dies in
 * a later wave, not here).
 *
 * The square: edge `map3d.plan_width_m` centred on its metre
 * position and turned by `yaw_deg` (contract § A1.1). The turn happens in SVG,
 * around exactly the point `worldToScreen` returns for the centre — but with
 * the OPPOSITE sign: `rotate(−yaw)`. SVG's `rotate(+deg)` turns clockwise on a
 * screen whose y grows downwards, which is the TRANSPOSE of the § A1.1 matrix,
 * not the same rotation. The two are a mirror image of each other, so the sign
 * is derived here and not guessed (mapMath's § B5a case, hand-checked):
 *
 *   loc (pos 10/20, width 10, yaw 90), view {cx:10, cz:20, pxPerM:1}, 200×200.
 *   Local corner (+5,+5) -> § A1.1 -> world (15, 15) -> screen (105, 95).
 *   Unrotated that corner is drawn at (105, 105); around the centre (100, 100)
 *     SVG rotate(+90) gives (95, 105)  — mirrored, WRONG
 *     SVG rotate(−90) gives (105, 95)  — the contract's corner
 *   Sanity check without arithmetic: at yaw 90 the local +x axis points to
 *   world −z (north), so the local north edge must sit WEST of the centre.
 *
 * `yaw_deg` itself is stored and written through unchanged — the sign lives in
 * the RENDERING only, never in the data (decision 2026-08-07). This layer does
 * not re-derive the corner arithmetic of `footprintScreenCorners`; both are
 * pinned to the same verified case, and a change to one is a lie about the
 * other until it is re-run.
 *
 * Without a scale anchor a location has NO area (§ A1.3). It is still drawn —
 * as a dashed NO_ANCHOR_WIDTH_M placeholder — because an editor that hides a
 * half-configured location leaves the user nothing to click; every surface
 * showing one says so (dashes here, a warning on the selection chip).
 *
 * Moving is the canvas gesture, never HTML5 drag&drop: `pointerdown` on a
 * footprint stops propagation (so `MapCanvas` does not pan), the move runs on
 * window listeners so it survives leaving the canvas, and the commit fires
 * ONCE on `pointerup`. Below CLICK_SLOP_PX the press stays a selection click —
 * the same threshold the canvas uses to tell a pan from a click.
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { useMapView } from './MapCanvas'
import {
  localToWorld, worldPolyToPath, worldToLocal, worldToScreen, type ScreenPt,
} from './mapMath'
import { PolygonHandles } from './PolygonHandles'
import type { EditorLocation } from './mapTypes'

/** Edge a footprint falls back to when the location carries no scale anchor.
 *  A placeholder, and marked as one wherever it is drawn. */
export const NO_ANCHOR_WIDTH_M = 10

/** Below this travel the press is a click, not a move (MapCanvas' value). */
const CLICK_SLOP_PX = 4
/** Under this drawn edge the name would be wider than the place it names. */
const LABEL_MIN_PX = 28
/** A footprint never drops below this on screen — at world zoom a 3 m hut
 *  would otherwise become an unclickable half pixel. */
const MIN_DRAWN_PX = 6
/** The anchor dot and the direction arrow of a drawn boundary, in pixels.
 *  Both say where the pin is and which way the place is turned, so they keep
 *  their size at every zoom. */
const PIN_R = 3
const ARROW_PX = 18
/** Metre coordinates are stored with 2 decimals (`world_ops._sanitize_map3d`
 *  rounds the boundary to the centimetre); rounding the local points here
 *  keeps what the editor draws identical to what it sent. */
const r2 = (v: number): number => Math.round(v * 100) / 100

const COL_PLACED = '#8b949e'
const COL_SELECTED = '#58a6ff'
const COL_GHOST = '#3fb950'
const COL_WARN = '#d29922'

/** The scale anchor of a location, or `null` when it has none. Reads
 *  `map3d.plan_width_m` — the ONE anchor field (`location_model3d.py`); the
 *  worldmap payload's hoisted `plan_width_m` is the same number, and unplaced
 *  locations only carry the nested one. */
export function anchorWidthM(loc: EditorLocation): number | null {
  const w = loc.map3d?.plan_width_m
  return typeof w === 'number' && Number.isFinite(w) && w > 0 ? w : null
}

/**
 * The DRAWN footprint of a location (contract v6 Nr. 1), in LOCAL metres
 * around the pin — or `null` when the location has none and is therefore
 * still drawn as a square.
 *
 * Read through a check, never trusted: `map3d` is free-form JSON on the way
 * in, and a boundary of two points encloses nothing. This is the ONE reader
 * of the field in the editor, so the drawing, the handles and the chip always
 * see the same list.
 */
export function boundaryLocal(loc: EditorLocation): Array<[number, number]> | null {
  const raw = loc.map3d?.boundary
  if (!Array.isArray(raw) || raw.length < 3) return null
  const pts: Array<[number, number]> = []
  for (const p of raw) {
    if (!Array.isArray(p) || p.length < 2) return null
    const x = Number(p[0])
    const z = Number(p[1])
    if (!Number.isFinite(x) || !Number.isFinite(z)) return null
    pts.push([x, z])
  }
  return pts.length >= 3 ? pts : null
}

/** The § A1.1 rotation of a location, in degrees; junk is no rotation. */
function yawOf(loc: EditorLocation): number {
  return typeof loc.yaw_deg === 'number' && Number.isFinite(loc.yaw_deg)
    ? loc.yaw_deg : 0
}

/** Local boundary metres -> WORLD metres, through the § A1.1 pin transform.
 *  The pin is passed in rather than read off the location: while it is being
 *  dragged the polygon has to follow the cursor. */
function boundaryWorld(points: Array<[number, number]>, cx: number,
  cz: number, yawDeg: number): Array<[number, number]> {
  return points.map(([lx, lz]) => {
    const p = localToWorld(cx, cz, yawDeg, lx, lz)
    return [p.x, p.z] as [number, number]
  })
}

/** Placed = a finite metre position. Anything else stands on no map at all. */
export function isPlaced(loc: EditorLocation): boolean {
  return typeof loc.pos_x === 'number' && Number.isFinite(loc.pos_x)
    && typeof loc.pos_z === 'number' && Number.isFinite(loc.pos_z)
}

/** Cache-busted 2D map icon of a location (404 = no image; an SVG `<image>`
 *  that fails to load simply draws nothing and lets the fill show). */
export function mapIconUrl(locId: string, ver: number): string {
  return `/world/locations/${encodeURIComponent(locId)}/map-icon-2d?v=${ver}`
}

/**
 * THE PICTURE inside a footprint: the roof view if there is one, the 2D map
 * icon otherwise, both covering the reference square (edge `plan_width_m`,
 * centred on the pin) of the location. It is drawn INSIDE the caller's yaw
 * rotation — the square draws it directly, the polygon draws it clipped to the
 * outline — so the derivation of the icon rotation below holds for both, and
 * there is exactly one place that knows how a location's picture is oriented.
 *
 * The icon carries its own 90°-step display rotation
 * (`map_rotation_2d`), which turns the ARTWORK inside the square and is not
 * the location's rotation in the world — it keeps SVG's own sign, because it
 * always was a screen rotation (the legacy CSS `rotate()` on the tile image),
 * never a § A1.1 world angle.
 *
 * THE ROOF VIEW CARRIES NO EXTRA ROTATION — neither `iconRot` nor a neutralised
 * model yaw. It is a top-down render of the location's SCENE payload, and that
 * payload is TILE-LOCAL: `compose_scene` never reads `location.yaw_deg`, so the
 * only turn baked into the picture is the building spec's own
 * `yaw_deg = map3d.rotation ?? map_rotation_2d` (`scene_recipe.py:1070-1075`).
 * The square's `rotate(−yaw)` then adds exactly what the 3D client's tile group
 * adds (`client3d/src/scene/tiles.ts:592`, `rotation.y = +rad(yaw_deg)`).
 * Hand-checked, so nobody has to prove it twice — location (10,20), yaw 90,
 * edge 10 m, view {cx:10, cz:20, pxPerM:1} on 200×200 (square centre (100,100),
 * corners 95…105; the snapshot images `extent_m` with image-right = local +x,
 * image-top = local −z):
 *
 *   map3d.rotation = 0, model point local (1,0)
 *     3D client: local_to_world -> x = 10 + cos90 = 10, z = 20 − sin90 = 19
 *                -> world (10,19) -> screen (100, 99)
 *     here:      image u = 0.5 + 1/10 = 0.6, v = 0.5 -> (101,100);
 *                rotate(−90) about (100,100): (1,0) -> (0,−1) -> (100, 99)  ✔
 *   map3d.rotation = 90, same model point (1,0)
 *     3D client: spec yaw first -> tile-local (0,−1); tile yaw 90 -> world
 *                (9,20) -> screen (99, 100)
 *     here:      the spec yaw is IN the image, so the point sits at (0,−1) ->
 *                u = 0.5, v = 0.4 -> (100,99); rotate(−90) -> (99, 100)  ✔
 *     with the yaw stripped out of the image it would land on (100,99) — a
 *     90° lie, i.e. off by exactly `map3d.rotation`.
 *
 * That is also why the roof gets NO `iconRot`. For a location without
 * `map3d.rotation` the spec yaw already IS `map_rotation_2d` — and the two
 * turns run against each other: a spec yaw θ reaches the image as three's
 * `R_y(+θ)`, which in image pixels (u right = local +x, v down = local +z) is
 * `(u,v) → (u·cosθ + v·sinθ, −u·sinθ + v·cosθ)`, i.e. SVG `rotate(−θ)`, while
 * `iconRot` is applied as SVG `rotate(+θ)`. Adding it would CANCEL the baked
 * yaw (`rotate(−θ)·rotate(+θ) = identity`) and hand back exactly the neutral
 * picture rejected above — not double it.
 */
function FootImage({ p, size, iconHref, iconRot, roofHref }: {
  p: ScreenPt
  size: number
  iconHref?: string
  iconRot?: number
  /** Top-down render of the location's building model, already covering
   *  exactly this square (`extent_m` == the footprint edge since E4). It
   *  REPLACES the 2D icon — two pictures of the same place in one square only
   *  compete. */
  roofHref?: string
}) {
  const half = size / 2
  // FULLY opaque: the picture is rendered solid (`solidBuilding`), and the
  // grey ground underneath has nothing to add — it is the placeholder for a
  // location that shows no building. Outline and direction are drawn AFTER it
  // by the caller and therefore stay on top.
  if (roofHref) {
    return <image href={roofHref} x={p.x - half} y={p.y - half}
      width={size} height={size} />
  }
  if (iconHref) {
    return <image href={iconHref} x={p.x - half} y={p.y - half}
      width={size} height={size} preserveAspectRatio="xMidYMid slice"
      transform={iconRot ? `rotate(${iconRot} ${p.x} ${p.y})` : undefined} />
  }
  return null
}

/** One footprint square: fill, picture, outline — all inside the yaw
 *  rotation. The transition rendering for a location that carries no drawn
 *  boundary yet (v6: it then has no area at all; the square is what the editor
 *  still offers to click). */
function FootSquare({ p, size, yaw, stroke, strokeWidth, dashed, iconHref, iconRot,
  roofHref }: {
  p: ScreenPt
  size: number
  yaw: number
  stroke: string
  strokeWidth: number
  dashed?: boolean
  iconHref?: string
  iconRot?: number
  roofHref?: string
}) {
  const half = size / 2
  return (
    // NEGATED yaw: SVG turns clockwise on a y-down screen, § A1.1 does not —
    // see the module docstring for the hand-checked case (yaw 90, local (+5,+5)
    // must land on screen (105, 95), which only rotate(−yaw) produces).
    <g transform={`rotate(${-yaw} ${p.x} ${p.y})`}>
      <rect x={p.x - half} y={p.y - half} width={size} height={size}
        fill="rgba(139,148,158,0.14)" stroke="none" />
      <FootImage p={p} size={size} iconHref={iconHref} iconRot={iconRot}
        roofHref={roofHref} />
      <rect x={p.x - half} y={p.y - half} width={size} height={size}
        fill="none" stroke={stroke} strokeWidth={strokeWidth}
        strokeDasharray={dashed ? '6 4' : undefined} />
      {/* The local −z edge (the location's "north") — without it a square
          gives no hint which way it was turned. */}
      <line x1={p.x - half} y1={p.y - half} x2={p.x + half} y2={p.y - half}
        stroke={stroke} strokeWidth={strokeWidth + 1} opacity={0.9} />
    </g>
  )
}

/**
 * One DRAWN footprint (v6): the boundary polygon in world metres, the pin as
 * an anchor dot and the yaw as a short arrow.
 *
 * The polygon points are already world metres — the § A1.1 transform ran in
 * `boundaryWorld`, point by point — so nothing here rotates anything and the
 * sign trap of the square does not exist. The PICTURE still lives in the
 * location's own square frame (the reference square of edge `plan_width_m`
 * around the pin, which is what a roof render and a map icon cover), so it
 * keeps the square's `rotate(−yaw)` and is CLIPPED to the outline. The clip
 * sits on an untransformed group above it, so it is evaluated in the very
 * screen space the path was built in.
 *
 * THE ARROW POINTS ALONG LOCAL −z, the same direction the square marks with its
 * "north" edge. In screen pixels that is (−sin yaw, −cos yaw): at yaw 0 it
 * points up, at yaw 90 it points WEST — the docstring case above, where local
 * +x turns towards world −z and the local north edge ends up west of the pin.
 * A fixed pixel length, because it says which way the place is TURNED, not how
 * big it is.
 */
function FootPoly({ world, pin, yaw, size, stroke, strokeWidth, iconHref,
  iconRot, roofHref }: {
  /** The boundary in WORLD metres (already transformed). */
  world: Array<[number, number]>
  pin: ScreenPt
  yaw: number
  /** Edge of the location's reference square on screen — the picture's box. */
  size: number
  stroke: string
  strokeWidth: number
  iconHref?: string
  iconRot?: number
  roofHref?: string
}) {
  const { view, w, h } = useMapView()
  // `useId` returns something like ":r7:", which is not a usable fragment in
  // `url(#…)` — the colons go.
  const clipId = 'fp' + useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const d = worldPolyToPath(world, view, w, h)
  const rad = (yaw * Math.PI) / 180
  const ax = pin.x - ARROW_PX * Math.sin(rad)
  const ay = pin.y - ARROW_PX * Math.cos(rad)
  return (
    <g>
      <defs>
        <clipPath id={clipId}>
          <path d={d} />
        </clipPath>
      </defs>
      <path d={d} fill="rgba(139,148,158,0.14)" fillRule="evenodd" stroke="none" />
      <g clipPath={`url(#${clipId})`}>
        <g transform={`rotate(${-yaw} ${pin.x} ${pin.y})`}>
          <FootImage p={pin} size={size} iconHref={iconHref} iconRot={iconRot}
            roofHref={roofHref} />
        </g>
      </g>
      <path d={d} fill="none" fillRule="evenodd" stroke={stroke}
        strokeWidth={strokeWidth} strokeLinejoin="round" />
      <line x1={pin.x} y1={pin.y} x2={ax} y2={ay} stroke={stroke}
        strokeWidth={strokeWidth + 1} opacity={0.9} />
      <circle cx={pin.x} cy={pin.y} r={PIN_R} fill="#0d1117" stroke={stroke}
        strokeWidth={strokeWidth} />
    </g>
  )
}

export interface GhostSpec {
  /** What the click will do: place an existing location or clone a template. */
  kind: 'place' | 'clone'
  id: string
  name: string
  /** Edge in metres — the placeholder when the source has no anchor. */
  widthM: number
  anchored: boolean
}

export interface PlacementLayerProps {
  /** PLACED locations only — the caller decides what belongs on the map. */
  locations: EditorLocation[]
  selectedId: string
  onSelect: (id: string) => void
  /** Commit of a finished move, in world metres (already snapped). */
  onMove: (id: string, x: number, z: number) => void
  /** Snap the moved centre onto the 10 m grid. */
  snapM: number
  /** Cache-buster per location id — bumped after an image change. */
  iconVer: Record<string, number>
  /** Rendered roof view per location id, when the map's roof toggle is on.
   *  A missing entry (still rendering, no model, no scene) simply leaves the
   *  square as it was — the picture is an aid, never a precondition. */
  roofUrl?: Record<string, string>
  /** An armed tray entry: its footprint follows the cursor and the placed
   *  ones stop taking pointer events, so a click can land on top of them. */
  ghost: GhostSpec | null
  ghostPt: { x: number; z: number } | null
  /** Are the boundary handles live? The layer is made inert from outside by a
   *  wrapping `pointer-events: none`, and `PolygonHandles` sets its own on the
   *  edges — an explicit value on a descendant wins, so the handles would stay
   *  clickable in a ground mode. This is the switch that answers that. */
  boundaryEdit?: boolean
  /** A finished boundary gesture, in LOCAL metres around the pin — already
   *  through the § A1.1 transform, so the caller writes `map3d.boundary`
   *  verbatim. */
  onBoundary?: (id: string, points: Array<[number, number]>) => void
}

export function PlacementLayer({
  locations, selectedId, onSelect, onMove, snapM, iconVer, roofUrl, ghost, ghostPt,
  boundaryEdit, onBoundary,
}: PlacementLayerProps) {
  const { view, w, h } = useMapView()
  const [drag, setDrag] = useState<{ id: string; x: number; z: number } | null>(null)

  // Live values for the window listeners, which are installed once.
  const viewRef = useRef(view)
  viewRef.current = view
  const snapRef = useRef(snapM)
  snapRef.current = snapM
  const moveRef = useRef(onMove)
  moveRef.current = onMove
  const dragRef = useRef<{
    id: string; sx: number; sy: number; ox: number; oz: number
    moved: boolean; x: number; z: number
  } | null>(null)

  useEffect(() => {
    const snapV = (v: number) => {
      const s = snapRef.current
      return s > 0 ? Math.round(v / s) * s : Math.round(v * 100) / 100
    }
    const move = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      const dx = e.clientX - d.sx
      const dy = e.clientY - d.sy
      if (!d.moved) {
        if (Math.hypot(dx, dy) < CLICK_SLOP_PX) return
        d.moved = true
      }
      const px = viewRef.current.pxPerM
      d.x = snapV(d.ox + dx / px)
      d.z = snapV(d.oz + dy / px)
      setDrag({ id: d.id, x: d.x, z: d.z })
    }
    const up = () => {
      const d = dragRef.current
      if (!d) return
      dragRef.current = null
      setDrag(null)
      if (d.moved) moveRef.current(d.id, d.x, d.z)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [])

  const startDrag = useCallback((e: ReactPointerEvent, loc: EditorLocation) => {
    if (e.button !== 0) return
    // The canvas must not pan while a footprint is being moved.
    e.stopPropagation()
    onSelect(loc.id)
    const ox = loc.pos_x as number
    const oz = loc.pos_z as number
    dragRef.current = {
      id: loc.id, sx: e.clientX, sy: e.clientY, ox, oz, moved: false, x: ox, z: oz,
    }
  }, [onSelect])

  if (!w || !h) return null

  /**
   * A finished boundary gesture: the handles work in WORLD metres (that is the
   * space this canvas draws in), the field is LOCAL metres around the pin — so
   * every point goes back through `worldToLocal`, the exact inverse of the
   * § A1.1 mapping the drawing used. The pin taken here is the STORED one, not
   * a drag position: a vertex gesture and a pin drag are two pointers, and only
   * one of them can be running.
   */
  const commitBoundary = (loc: EditorLocation,
    worldPts: Array<[number, number]>) => {
    if (!onBoundary) return
    const cx = loc.pos_x as number
    const cz = loc.pos_z as number
    const yaw = yawOf(loc)
    onBoundary(loc.id, worldPts.map(([x, z]) => {
      const l = worldToLocal(cx, cz, yaw, x, z)
      return [r2(l.x), r2(l.z)] as [number, number]
    }))
  }

  // The selection's boundary handles, mounted once outside the list: the
  // gesture belongs to ONE location, and drawing it last keeps it above every
  // footprint painted after it.
  const selLoc = locations.find((l) => l.id === selectedId) || null
  const selBoundary = selLoc ? boundaryLocal(selLoc) : null
  const selHandlePts = selLoc && selBoundary
    // Not while the pin itself is being dragged: the polygon follows the
    // cursor then, and a handle whose commit reads the stored pin would move
    // the vertex by the drag distance a second time.
    && !(drag && drag.id === selLoc.id)
    ? boundaryWorld(selBoundary, selLoc.pos_x as number, selLoc.pos_z as number,
      yawOf(selLoc))
    : null

  // Big first, small last: a hut inside a village square stays clickable.
  // The selection is drawn on top of everything regardless of its size.
  const ordered = [...locations].sort((a, b) => {
    if (a.id === selectedId) return 1
    if (b.id === selectedId) return -1
    return (anchorWidthM(b) ?? NO_ANCHOR_WIDTH_M) - (anchorWidthM(a) ?? NO_ANCHOR_WIDTH_M)
  })

  return (
    <g pointerEvents={ghost ? 'none' : undefined}>
      {ordered.map((loc) => {
        const anchor = anchorWidthM(loc)
        const dragging = drag && drag.id === loc.id
        const cx = dragging ? drag.x : (loc.pos_x as number)
        const cz = dragging ? drag.z : (loc.pos_z as number)
        const p = worldToScreen(cx, cz, view, w, h)
        const size = Math.max(MIN_DRAWN_PX, (anchor ?? NO_ANCHOR_WIDTH_M) * view.pxPerM)
        const selected = loc.id === selectedId
        const yaw = yawOf(loc)
        const stroke = selected ? COL_SELECTED : (anchor ? COL_PLACED : COL_WARN)
        // The DRAWN footprint wins wherever there is one (v6 Nr. 1); the
        // square is what is left for a location that has none yet.
        const bd = boundaryLocal(loc)
        const bdWorld = bd ? boundaryWorld(bd, cx, cz, yaw) : null
        // Where the name goes: under the lowest point of what was drawn, so a
        // long polygon does not write its label across its own middle.
        const bottom = bdWorld
          ? Math.max(...bdWorld.map(([bx, bz]) => worldToScreen(bx, bz, view, w, h).y))
          : p.y + size / 2
        return (
          <g key={loc.id} style={{ cursor: 'move' }}
            onPointerDown={(e) => startDrag(e, loc)}>
            {bdWorld ? (
              <FootPoly world={bdWorld} pin={p} yaw={yaw} size={size}
                stroke={stroke} strokeWidth={selected ? 2 : 1}
                iconHref={mapIconUrl(loc.id, iconVer[loc.id] || 0)}
                iconRot={loc.map_rotation_2d || 0}
                roofHref={roofUrl?.[loc.id]} />
            ) : (
              <FootSquare p={p} size={size} yaw={yaw} stroke={stroke}
                strokeWidth={selected ? 2 : 1} dashed={!anchor}
                iconHref={mapIconUrl(loc.id, iconVer[loc.id] || 0)}
                iconRot={loc.map_rotation_2d || 0}
                roofHref={roofUrl?.[loc.id]} />
            )}
            {size >= LABEL_MIN_PX || selected ? (
              <text x={p.x} y={bottom + 12} fontSize={11} textAnchor="middle"
                fill={selected ? COL_SELECTED : '#c9d1d9'} pointerEvents="none"
                style={{ paintOrder: 'stroke', stroke: '#0d1117', strokeWidth: 3 }}>
                {loc.name}
              </text>
            ) : null}
          </g>
        )
      })}

      {/* The ONE point-editing gesture of this canvas, on the location
          boundary: the same component the painted terrain and the world relief
          are reshaped with. It works in the host layer's space — world metres
          here — and `commitBoundary` turns the result back into the local
          metres the field is stored in. */}
      {boundaryEdit && selLoc && selHandlePts && onBoundary ? (
        <PolygonHandles
          points={selHandlePts}
          closed
          color={COL_SELECTED}
          minPoints={3}
          onMove={(i, x, z) => commitBoundary(selLoc,
            selHandlePts.map((pt, k) => (k === i ? [x, z] as [number, number] : pt)))}
          onDelete={(i) => commitBoundary(selLoc,
            selHandlePts.filter((_, k) => k !== i))}
          onInsert={(i, x, z) => {
            const pts = [...selHandlePts]
            pts.splice(i, 0, [x, z])
            commitBoundary(selLoc, pts)
          }}
        />
      ) : null}

      {ghost && ghostPt ? (
        <g pointerEvents="none">
          <FootSquare
            p={worldToScreen(ghostPt.x, ghostPt.z, view, w, h)}
            size={Math.max(MIN_DRAWN_PX, ghost.widthM * view.pxPerM)}
            yaw={0} stroke={ghost.anchored ? COL_GHOST : COL_WARN}
            strokeWidth={2} dashed={!ghost.anchored} />
        </g>
      ) : null}
    </g>
  )
}
