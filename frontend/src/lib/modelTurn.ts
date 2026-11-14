/**
 * modelTurn — the ONE mouse and touch control of every model viewer in the Game-Admin (T-U4): the pointer turns the
 * MODEL, not the camera.
 *
 * - Plain drag (left button, one finger): horizontal turns the model about the vertical axis (yaw), vertical tilts
 *   it forward / back about its own side axis (pitch, clamped to ±90°), both about the viewer's pivot (the model's
 *   centre, or the part a viewer focuses on). Dragging down tilts it forward (its top towards +z, the way it faces).
 * - Shift + drag (or the right button): moves the view left / right and up / down — OrbitControls' pan
 *   (`configureViewControls`: rotation off, so its left button pans only with Shift).
 * - Wheel, two fingers: zoom (and pan), OrbitControls as before.
 * - Double-click, or a viewer's "Reset pose" button (`reset`): back to upright, eased at `RESET_DEG_PER_S`, so a
 *   viewer with simulated hair sees it swing back instead of a jump.
 *
 * The pose is applied by the viewer as `T(pivot) · Ry(yaw) · Rx(pitch) · T(−pivot)` on a group above the model
 * (`poseMatrix`); a viewer that drives a simulation (the Hairstyles preview's strands) reads the model's world
 * matrix after it, so the turn and the tilt drive the sim like any other root motion.
 *
 * Pure parts (`dragPose`, `resetPoseStep`, `poseMatrix`, `wrapAngle`) are checked by
 * `scripts/smoke_model_turn.mjs`; `attachModelTurn` binds them to a viewer's mount element.
 */

/** Degrees the model turns or tilts per pixel of drag (180 px = 90°; the Hairstyles preview's earlier drag turn). */
export const DRAG_TURN_DEG_PER_PX = 0.5
/** The tilt stops at ±this many degrees: lying on the front or on the back. */
export const PITCH_LIMIT_DEG = 90
/** How fast "Reset pose" turns the model back (degrees per second, both axes together). */
export const RESET_DEG_PER_S = 240
/** A press that moves less than this (px) is a click (a viewer's pick), not a drag. */
export const DRAG_SLOP_PX = 3

const DEG = Math.PI / 180

/** The model's turn (radians): yaw about the vertical axis, pitch forward (+) / back (−) about its side axis. */
export interface ModelPose { yaw: number; pitch: number }

export const UPRIGHT: ModelPose = Object.freeze({ yaw: 0, pitch: 0 })

/** `a` into (−π, π]. */
export function wrapAngle(a: number): number {
  const w = a - 2 * Math.PI * Math.floor((a + Math.PI) / (2 * Math.PI))
  return w <= -Math.PI ? w + 2 * Math.PI : w
}

/** The pose after a drag of (`dx`, `dy`) px from `start`: yaw by dx, pitch by dy (down tilts forward), the pitch
 *  clamped to ±`PITCH_LIMIT_DEG`. */
export function dragPose(start: ModelPose, dx: number, dy: number): ModelPose {
  const limit = PITCH_LIMIT_DEG * DEG
  const pitch = start.pitch + dy * DRAG_TURN_DEG_PER_PX * DEG
  return { yaw: start.yaw + dx * DRAG_TURN_DEG_PER_PX * DEG, pitch: Math.max(-limit, Math.min(limit, pitch)) }
}

/** One frame of "Reset pose": `pose` moved towards upright by at most `RESET_DEG_PER_S · dt` (the yaw the short way
 *  round), both axes arriving together; exactly upright once within reach. */
export function resetPoseStep(pose: ModelPose, dt: number): ModelPose {
  const yaw = wrapAngle(pose.yaw), pitch = pose.pitch
  const dist = Math.hypot(yaw, pitch), step = RESET_DEG_PER_S * DEG * Math.max(0, dt)
  if (dist <= step || dist < 1e-9) return { yaw: 0, pitch: 0 }
  const s = 1 - step / dist
  return { yaw: yaw * s, pitch: pitch * s }
}

/** True when `pose` is upright (within 1e-6 rad). */
export function isUpright(pose: ModelPose): boolean {
  return Math.abs(wrapAngle(pose.yaw)) < 1e-6 && Math.abs(pose.pitch) < 1e-6
}

/** `T(pivot + offset) · Ry(yaw) · Rx(pitch) · T(−pivot)`, column-major (three's `Matrix4.elements` order). */
export function poseMatrix(pose: ModelPose, pivot: readonly [number, number, number],
  offset: readonly [number, number, number] = [0, 0, 0]): number[] {
  const cy = Math.cos(pose.yaw), sy = Math.sin(pose.yaw), cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch)
  // R = Ry · Rx (rows): [cy, sy·sp, sy·cp; 0, cp, −sp; −sy, cy·sp, cy·cp]
  const r = [cy, sy * sp, sy * cp, 0, cp, -sp, -sy, cy * sp, cy * cp]
  const [px, py, pz] = pivot
  const t = [0, 1, 2].map(i => pivot[i] + offset[i] - (r[3 * i] * px + r[3 * i + 1] * py + r[3 * i + 2] * pz))
  return [r[0], r[3], r[6], 0, r[1], r[4], r[7], 0, r[2], r[5], r[8], 0, t[0], t[1], t[2], 1]
}

/** The view part (OrbitControls): camera rotation off; left + Shift and the right button pan, the middle button and
 *  the wheel zoom, two fingers zoom and pan; one finger does nothing there (it turns the model). */
export function configureViewControls(three: { MOUSE: { ROTATE: number; DOLLY: number; PAN: number };
  TOUCH: { ROTATE: number; DOLLY_PAN: number } }, controls: { enableRotate: boolean; enablePan: boolean;
  enableZoom: boolean; mouseButtons: object; touches: object; update(): unknown }): void {
  controls.enableRotate = false
  controls.enablePan = true
  controls.enableZoom = true
  // LEFT stays ROTATE on purpose: OrbitControls turns a ROTATE press with Shift (or Ctrl / Meta) into a pan and,
  // with rotation off, ignores the plain one — that is the drag `attachModelTurn` takes.
  controls.mouseButtons = { LEFT: three.MOUSE.ROTATE, MIDDLE: three.MOUSE.DOLLY, RIGHT: three.MOUSE.PAN }
  controls.touches = { ONE: three.TOUCH.ROTATE, TWO: three.TOUCH.DOLLY_PAN }
  controls.update()
}

export interface ModelTurnControl {
  /** The pose now (the viewer applies it every frame). */
  readonly pose: ModelPose
  /** A drag is turning the model right now. */
  readonly dragging: boolean
  /** Ease back to upright (`resetPoseStep` in `tick`). */
  reset(): void
  /** Straight back to upright, at once (a view that needs the model straight on, e.g. the front view). */
  snapUpright(): void
  /** Advance the reset ease by `dt` seconds; true when the pose changed. */
  tick(dt: number): boolean
  dispose(): void
}

/**
 * Bind the control to `el` (a viewer's mount: the canvas sits inside it). `isEnabled` is read on every press (a
 * locked front view or a pick mode answers false: the press goes to OrbitControls / the viewer untouched);
 * `onChange` gets every new pose (a status line). Listens in the capture phase without stopping the event, so the
 * viewer's own click handling (picks) still sees a press that did not move.
 */
export function attachModelTurn(el: HTMLElement, opts: { isEnabled?: () => boolean;
  onChange?: (pose: ModelPose) => void } = {}): ModelTurnControl {
  let pose: ModelPose = { ...UPRIGHT }
  let resetting = false
  let drag: { x: number; y: number; start: ModelPose; id: number } | null = null
  const touches = new Set<number>()
  let multiTouch = false
  const set = (next: ModelPose) => { pose = next; opts.onChange?.(pose) }
  const enabled = () => opts.isEnabled?.() !== false
  const end = (e: PointerEvent) => {
    if (e.pointerType === 'touch') {
      touches.delete(e.pointerId)
      if (!touches.size) multiTouch = false
    }
    if (drag && e.pointerId === drag.id) {
      drag = null
      el.style.cursor = enabled() ? 'grab' : ''
    }
  }
  const onDown = (e: PointerEvent) => {
    if (e.pointerType === 'touch') {
      touches.add(e.pointerId)
      if (touches.size > 1) { multiTouch = true; drag = null; return }   // two fingers: OrbitControls' zoom + pan
    }
    if (!enabled() || multiTouch || e.button !== 0 || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return
    resetting = false
    drag = { x: e.clientX, y: e.clientY, start: pose, id: e.pointerId }
  }
  const onMove = (e: PointerEvent) => {
    if (!drag || e.pointerId !== drag.id || multiTouch) return
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y
    if (pose === drag.start && Math.hypot(dx, dy) < DRAG_SLOP_PX) return
    el.style.cursor = 'grabbing'
    set(dragPose(drag.start, dx, dy))
  }
  const onDouble = (e: MouseEvent) => {
    if (!enabled() || e.shiftKey) return
    resetting = true
  }
  el.addEventListener('pointerdown', onDown, true)
  el.addEventListener('pointermove', onMove, true)
  el.addEventListener('pointerup', end, true)
  el.addEventListener('pointercancel', end, true)
  el.addEventListener('dblclick', onDouble)
  el.style.cursor = enabled() ? 'grab' : ''
  return {
    get pose() { return pose },
    get dragging() { return drag !== null },
    reset() { drag = null; resetting = true },
    snapUpright() {
      drag = null
      resetting = false
      if (!isUpright(pose)) set({ ...UPRIGHT })
    },
    tick(dt: number) {
      if (!resetting) return false
      const next = resetPoseStep(pose, dt)
      if (isUpright(next)) resetting = false
      set(next)
      return true
    },
    dispose() {
      el.removeEventListener('pointerdown', onDown, true)
      el.removeEventListener('pointermove', onMove, true)
      el.removeEventListener('pointerup', end, true)
      el.removeEventListener('pointercancel', end, true)
      el.removeEventListener('dblclick', onDouble)
      el.style.cursor = ''
    },
  }
}
