import { isTypingTarget } from '../hud/dom';
import { createPropLightPool } from './lightPool';
import { nightFactorAt } from './ambience';
import { FOG_NEAR_M, FOG_FAR_M } from './fogConstants';
import * as THREE from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { setSurfaceSky, updateSurfaceMaterials } from '@anima/scene-render';
import { setFogVeilSky } from './fogVeil';
import {
  basePitchDeg, FirstPersonZoom, OVERVIEW_NEAR_PITCH_DEG, THIRD_PERSON_MIN_DIST,
} from './cameraFraming';
import {
  clampPitchDeg, clampZoom, damp, flyAdvance, flyEase, MAX_FRAME_DT, orbitOffset,
  orbitStep, type Vec3, wheelFactor, zoomCeiling, zoomFloorOf, zoomTowardCursor,
} from './cameraMath';
import { SHADOW_HALF_M, SHADOW_MAP_PX, snapShadowCentre } from './shadowSnap';
import { type ScreenBox, viewShiftFor } from './viewShift';

/** The framing arithmetic lives in `scene/cameraFraming.ts` and the overview
 *  camera's own arithmetic (wheel, easing, fly-to, orbit, pose) in
 *  `scene/cameraMath.ts` — pure numbers, so they can be checked without a GL
 *  context (`scripts/smoke_embodied_camera.mjs`,
 *  `client3d/scripts/smoke_camera_math.mjs`). Re-exported here because
 *  `MIN_DIST` is a fact about this camera and `main.ts` frames with it. */
export { MIN_DIST } from './cameraFraming';

/**
 * How far the pointer may travel during an orbit gesture and still count as a
 * CLICK, in CSS pixels (B19). 4 px is the usual click slop of a desktop UI —
 * above the one or two pixels a hand moves while pressing a button, far below
 * the movement of an intended turn (0.005 rad/px ⇒ 4 px ≈ 1.1° of yaw, which
 * is not a turn anybody meant). Below it the release still reaches the pick
 * chain, so a click on the ground remains a walk order while embodied, where
 * the bare left button now orbits.
 */
const ORBIT_DRAG_PX = 4;

/**
 * The vectors `frame()` works in, allocated ONCE (review finding UI-11) —
 * the pattern `mirrorScratch` uses in the shared package. This is the
 * innermost loop of the application: four fresh `Vector3` per frame are ~240
 * short-lived objects a second whose only purpose is to be filled with
 * `.set(...)` and read in the same line. Every one of them is consumed before
 * the frame ends (`fwd`/`right` add into `target`, `off` into the camera
 * position, `sunOff` into the sun's), so nothing outlives the call and there
 * is exactly one Engine per page.
 */
const SCRATCH = {
  fwd: new THREE.Vector3(),
  right: new THREE.Vector3(),
  off: new THREE.Vector3(),
  look: new THREE.Vector3(),
  sunOff: new THREE.Vector3(),
  surfaceSky: new THREE.Color(),
  /** `orbitOffset` writes its tuple here before it is copied into `off`. */
  offTuple: [0, 0, 0] as Vec3,
};

/**
 * AoE-style camera: fixed pitch (slightly zoom-dependent), yaw in 45° steps,
 * pan by drag/WASD, zoom by mouse wheel towards the cursor.
 */
export class Engine {
  scene = new THREE.Scene();
  lightPool = createPropLightPool(this.scene);
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  labelRenderer: CSS2DRenderer;
  sun: THREE.DirectionalLight;
  hemi!: THREE.HemisphereLight;
  fill!: THREE.DirectionalLight;
  /** neutral IBL for server models that carry a real metal-roughness texture */
  modelEnv: THREE.Texture;
  private ambienceDaylight = 1;
  private ambienceTint = new THREE.Color(0xffffff);
  /** Clock-computed base values; applied lighting is base × ambience. */
  private baseLights?: {
    sun: THREE.Color; sky: THREE.Color; hemi: THREE.Color; ground: THREE.Color;
    fill: THREE.Color; sunIntensity: number; hemiIntensity: number; fillIntensity: number;
  };
  /** Apply base × ambience each frame without accumulating tint or dimming. */
  applyAmbience(daylight: number, tint: THREE.Color) {
    this.ambienceDaylight = daylight;
    this.ambienceTint.copy(tint);
    const b = this.baseLights;
    if (!b) return;
    this.sun.intensity = b.sunIntensity * daylight;
    this.hemi.intensity = b.hemiIntensity * daylight;
    this.fill.intensity = b.fillIntensity * daylight;
    this.sun.color.copy(b.sun).multiply(tint);
    this.hemi.color.copy(b.hemi).multiply(tint);
    this.hemi.groundColor.copy(b.ground).multiply(tint);
    this.fill.color.copy(b.fill).multiply(tint);
    // Water mirrors the sky through Fresnel; ambience scales and tints that reflection.
    setSurfaceSky(SCRATCH.surfaceSky.copy(b.sky).multiplyScalar(daylight).multiply(tint).getHex());
  }
  /** Sun position from the game time (0..24); drives light, colours, sky. */
  private sunAngle = Math.PI * 0.35;   // default: late morning
  /**
   * The world clock the sun currently stands for, in hours 0..24 — derived
   * from `sunAngle` rather than remembered beside it, so the readout of the
   * ISOLATION panel (`debug3d.ts`) can never disagree with the light it is
   * describing. Inverts `setGameHour`: `sunAngle = ((h − 6) / 12) · π`.
   */
  get gameHour(): number {
    return (this.sunAngle / Math.PI) * 12 + 6;
  }
  /** 0 = bright day, 1 = deep night — for window lights and the like. */
  nightFactor = 0;
  onDayNight: ((night: number) => void) | null = null;

  target = new THREE.Vector3(0, 0, 0);
  dist = 80;
  targetDist = 80;
  yaw = Math.PI / 4;
  targetYaw = Math.PI / 4;

  private firstPersonZoom = new FirstPersonZoom();
  /** First person is available only while following the controlled avatar. */
  get firstPerson(): boolean {
    return this.follow !== null && this.firstPersonZoom.active;
  }
  private keys = new Set<string>();
  private dragging = false;
  private orbiting = false;              // right mouse button: free orbit
  private orbitLast = { x: 0, y: 0 };
  private orbitStart = { x: 0, y: 0 };   // where the gesture began (click vs. drag)
  pitchOffset = 0;                       // free pitch share (degrees); public for the preview pages
  private dragStart = new THREE.Vector3();
  private raycaster = new THREE.Raycaster();
  private groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  private pointer = new THREE.Vector2();
  private clock = new THREE.Clock();
  private frameHooks: Array<(dt: number) => void> = [];
  private pickables: THREE.Object3D[] = [];
  private moved = false;

  onPick: ((locationId: string | null) => void) | null = null;
  onHover: ((locationId: string | null) => void) | null = null;
  /** Where the pointer stands over the canvas, in CLIENT coordinates, or null
   *  while it is outside it. Written on every `pointermove` (two numbers, no
   *  raycast) and meant to be read ONCE PER FRAME by whoever wants to pick
   *  under the cursor — a raycast per pointer event is a storm, one per frame
   *  is the budget the render loop already has. `main.ts` picks the seatable
   *  props with it. */
  pointerAt: { x: number; y: number } | null = null;
  /** Counts up on EVERY write to `pointerAt`, the leave included. A frame
   *  hook that picks under the cursor compares it with the value it last
   *  probed and skips the raycast entirely while the pointer stands still —
   *  the dirty flag for `pointerAt`, kept here so there is one writer of
   *  both. Never negative, so a caller may use −1 to force the next probe. */
  pointerSeq = 0;
  /** Asked BEFORE onPick on a left click (E3-T1): true = the click hit a figure
   *  and is used up, so no tile pick follows. */
  pickFigure: ((x: number, y: number) => boolean) | null = null;
  /** Asked after `pickFigure` and BEFORE `onPick` on a left click (E3-T4):
   *  true = the click became a walk target and must not also open the tile's
   *  info panel. Only the embodied mode answers true — in the overview every
   *  click still belongs to the tile. */
  onGroundClick: ((x: number, y: number) => boolean) | null = null;
  /** Follow target (E3-T2): while set, the camera chases the point this getter
   *  returns per frame and the WASD pan is skipped — those keys then belong to
   *  the avatar (task 3). Wheel zoom, Q/E and orbit stay live. */
  follow: (() => THREE.Vector3 | null) | null = null;
  /** What the HUD covers of the picture, in CLIENT coordinates, or null while
   *  nothing does. TODAY that is the chat window and nothing else: it is the
   *  one panel the user drags to any size, and at its maximum it owns most of
   *  the screen while the avatar sits centred behind it. The engine does not
   *  move the camera for it — it renders an off-centre cut-out of the same
   *  picture, so the aim point slides out of the covered corner while the
   *  viewing direction stays untouched (`scene/viewShift.ts`).
   *
   *  Written by `main.ts` from the HUD, read once per frame. Client
   *  coordinates rather than canvas ones because that is what the HUD can
   *  measure; the frame subtracts the canvas origin itself. */
  obstruction: ScreenBox | null = null;

  /** The shift currently APPLIED, in CSS pixels — the smoothed value, chased
   *  towards what `viewShiftFor` asks for the same way `dist` and `yaw` chase
   *  theirs. The panel fades in over 150 ms and is dragged live, and a shift
   *  that snapped would jerk the whole world sideways with it. */
  private viewDx = 0;
  private viewDy = 0;
  /** What was last handed to `setViewOffset`, so an unchanged frame does not
   *  rebuild the projection matrix. `null` = the camera has no offset set. */
  private viewApplied: { dx: number; dy: number; w: number; h: number } | null = null;
  /** Ceiling of the USER's zoom-out, in metres; `null` = the engine's own
   *  `MAX_DIST`. The embodied mode sets it (finding B12): zooming out there
   *  used to slide seamlessly back into the overview, and the player never
   *  learnt that leaving control is a decision one takes (Esc / the mode
   *  chip). It binds the wheel and the +/- keys only — a `flyTo` is a
   *  deliberate camera move by the app and stays free, which is what lets the
   *  mode fly back out to the overview while leaving. */
  zoomCap: number | null = null;
  /** Floor of the USER's zoom-in, in metres; `null` = `MIN_DIST`. This
   *  clamps requested zoom and flyTo, not the third-person lens stand-off.
   *  Following a figure permits first person at the closest zoom. */
  zoomFloor: number | null = null;
  /** Pitch at the near end of the zoom, in degrees — see
   *  `cameraFraming.basePitchDeg`. The embodied mode flattens it
   *  (`EMBODY_NEAR_PITCH_DEG`) so a close view looks along the avatar's line
   *  of sight instead of down at the ground in front of it. */
  nearPitchDeg = OVERVIEW_NEAR_PITCH_DEG;
  /** Fired when a zoom-out was STOPPED by `zoomCap` — the hint hangs off this,
   *  not off a distance the HUD would have to watch itself. */
  onZoomCapped: (() => void) | null = null;
  /** Plain left drag turns the view instead of panning it (B19). The embodied
   *  mode sets it: while one steers the avatar the camera hangs on the figure
   *  (`follow`), so a pan-drag is pulled straight back by the chase in the very
   *  next frame — dragging was a gesture without effect there, and the one
   *  thing a player wants to do with the mouse in that mode, look around, cost
   *  a modifier key. In the OVERVIEW the flag stays false and every control is
   *  what it was: drag pans, Shift/Ctrl/Alt + drag or the middle button turns.
   *  A CLICK keeps its meaning in both modes — see `ORBIT_DRAG_PX`. */
  orbitOnDrag = false;

  constructor(container: HTMLElement) {
    // near 0.2 (was 0.5) so MIN_DIST = 0.8 stays clear of the near plane: at
    // the closest zoom the figure's front faces sit ~0.7 m from the lens, and
    // the free pitch (right mouse) can bring geometry closer still. Trade-off:
    // far/near goes from 1600 to 4000, i.e. depth resolution at a given range
    // gets 2.5× coarser (≈12 mm at 200 m on a 24-bit buffer). That is still
    // well inside the usual budget for a 24-bit depth buffer, and the fog ends
    // the scene at 520 m anyway, so no co-planar surface loses its ordering.
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.2, 800);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    // Per-material clipping planes (§ B2 addendum 2026-08-23, the prop depth
    // cut). Without this three ignores `Material.clippingPlanes` entirely and
    // a cut prop simply stands there whole; nothing else in the scene sets
    // any, so it costs nothing.
    this.renderer.localClippingEnabled = true;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.className = 'label-layer';
    container.appendChild(this.labelRenderer.domElement);

    this.modelEnv = new THREE.PMREMGenerator(this.renderer)
      .fromScene(new RoomEnvironment(), 0.04).texture;

    this.scene.background = new THREE.Color(0x9fc7e8);
    this.scene.fog = new THREE.Fog(0x9fc7e8, FOG_NEAR_M, FOG_FAR_M);

    this.hemi = new THREE.HemisphereLight(0xdfeeff, 0x8a9a78, 1.5);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(0xfff2d8, 2.0);
    this.fill = new THREE.DirectionalLight(0xdde8ff, 0.5);   // back light, lifts the shadow sides
    this.fill.position.set(-30, 20, -25);
    this.scene.add(this.fill);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(SHADOW_MAP_PX, SHADOW_MAP_PX);
    this.sun.shadow.bias = -0.0004;
    // THE SHADOW FRUSTUM IS A CONSTANT — a fixed half width in metres and a
    // fixed depth, which is exactly what lets `snapShadowCentre` move the
    // whole thing in whole texels. It is therefore set ONCE, here, instead of
    // being written and re-projected on every frame (review finding UI-11);
    // the frame loop only moves `sun.position`/`sun.target.position`, and a
    // translation does not touch an orthographic projection matrix.
    const shadowCam = this.sun.shadow.camera;
    shadowCam.left = -SHADOW_HALF_M;
    shadowCam.right = SHADOW_HALF_M;
    shadowCam.top = SHADOW_HALF_M;
    shadowCam.bottom = -SHADOW_HALF_M;
    shadowCam.far = 300;
    shadowCam.updateProjectionMatrix();
    this.scene.add(this.sun, this.sun.target);

    this.resize(container);
    window.addEventListener('resize', () => this.resize(container));
    this.bindInput(container);
    this.renderer.setAnimationLoop(() => this.frame());
  }

  /** Set the time of day (hour 0..24): sun position, light colours, sky, fog. */
  setGameHour(hour: number) {
    const h = ((hour % 24) + 24) % 24;
    // Sun arc: 6:00 = east (0), 12:00 = zenith (PI/2), 18:00 = west (PI)
    this.sunAngle = ((h - 6) / 12) * Math.PI;
    const day = THREE.MathUtils.clamp(Math.sin(this.sunAngle), 0, 1);       // 0 at night, 1 at noon
    const dusk = THREE.MathUtils.clamp(1 - Math.abs(h - 12) / 6, 0, 1);     // closeness to midday

    const noon = new THREE.Color(0xfff2d8);
    const warm = new THREE.Color(0xffb066);   // dawn/dusk red
    const night = new THREE.Color(0x9fb4e0);  // moonlight (cool)
    const sunColor = day > 0.05
      ? warm.clone().lerp(noon, THREE.MathUtils.smoothstep(day, 0.05, 0.45))
      : night.clone();
    this.sun.color.copy(sunColor);
    this.sun.intensity = 0.25 + day * 2.0;

    this.hemi.intensity = 0.35 + day * 1.2;
    this.fill.intensity = 0.15 + day * 0.4;

    const skyDay = new THREE.Color(0x9fc7e8);
    const skyDusk = new THREE.Color(0xe89a63);
    const skyNight = new THREE.Color(0x1a2340);
    const sky = day > 0.15
      ? skyDay.clone()
      : skyNight.clone().lerp(skyDusk, THREE.MathUtils.clamp(day / 0.15, 0, 1) * (dusk > 0.05 ? 1 : 0.3));
    // The blend factor reaches 1 at day=0.15 — a continuous handover to the night branch
    if (day > 0.15 && day < 0.35) sky.lerp(skyDusk, (0.35 - day) / 0.2);
    (this.scene.background as THREE.Color).copy(sky);
    // The fog can be ABSENT: the isolation panel (`debug3d.ts`, toggle 3) takes
    // it out of the scene, and a colour written into nothing would crash the
    // next world-clock poll.
    if (this.scene.fog) this.scene.fog.color.copy(sky);
    this.baseLights = {
      sun: sunColor.clone(), sky: sky.clone(),
      hemi: this.baseLights?.hemi ?? this.hemi.color.clone(),
      ground: this.baseLights?.ground ?? this.hemi.groundColor.clone(),
      fill: this.baseLights?.fill ?? this.fill.color.clone(),
      sunIntensity: .25 + day * 2, hemiIntensity: .35 + day * 1.2,
      fillIntensity: .15 + day * .4,
    };
    // …and so does the exploration veil: haze is the air between the eye and
    // the ground, so it takes the colour of that air rather than a grey of its
    // own that would be wrong twice a day (`scene/fogVeil.ts`).
    setFogVeilSky(sky.getHex());

    this.nightFactor = nightFactorAt(hour);
    this.onDayNight?.(this.nightFactor);
    this.applyAmbience(this.ambienceDaylight, this.ambienceTint);
  }

  addFrameHook(fn: (dt: number) => void) {
    this.frameHooks.push(fn);
  }

  /** Keys currently held down, lower-case (E3-T2). Read-only on purpose: the
   *  avatar control of task 3 reads the SAME set the camera pan reads, so a
   *  key can never be down for one and up for the other. */
  keysDown(): ReadonlySet<string> {
    return this.keys;
  }

  setPickables(objs: THREE.Object3D[]) {
    this.pickables = objs;
  }

  /** A wanted zoom distance, clamped into what the camera may show — and the
   *  hint when the CAP was what stopped it (`zoomCap`, finding B12). The
   *  engine's own `MIN_DIST`/`MAX_DIST` are silent: they are the lens, not a
   *  rule of the game. */
  private clampZoom(dist: number): number {
    // Every notch beyond the ceiling reports — how OFTEN the player is told is
    // the listener's business (main.ts shows it once per embodied session),
    // and a "first time only" rule down here could not tell one session from
    // the next.
    if (this.zoomCap !== null
        && dist > zoomCeiling(zoomFloorOf(this.zoomFloor), this.zoomCap) + 1e-6) {
      this.onZoomCapped?.();
    }
    return clampZoom(dist, this.zoomFloor, this.zoomCap);
  }

  /** Ease the camera onto a point + distance. */
  flyTo(point: THREE.Vector3, dist: number) {
    this.flyFrom = this.target.clone();
    this.flyToPoint = point.clone();
    this.flyT = 0;
    // The cap binds the user's zoom, not this deliberate move (`zoomCap`).
    this.targetDist = clampZoom(dist, this.zoomFloor, null);
  }
  private flyFrom: THREE.Vector3 | null = null;
  private flyToPoint: THREE.Vector3 | null = null;
  private flyT = 1;

  private resize(container: HTMLElement) {
    const w = container.clientWidth || window.innerWidth;
    const h = container.clientHeight || window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.labelRenderer.setSize(w, h);
  }

  private groundPoint(clientX: number, clientY: number,
                      planeY = 0): THREE.Vector3 | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    // The plane is horizontal, so `constant` is just its height, negated
    // (normal . p + constant = 0 with normal = +y). Every caller passes what it
    // wants, the default 0 being the map's own ground.
    this.groundPlane.constant = -planeY;
    const hit = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(this.groundPlane, hit) ? hit : null;
  }

  /** Where the pointer meets a HORIZONTAL plane at `planeY` (default: the
   *  ground at y = 0), for anything outside the engine that needs a world
   *  position from a click (E3-T4: the walk target). Null when the ray runs
   *  parallel to it.
   *
   *  `planeY` exists because y = 0 is the wrong plane wherever the player
   *  actually stands higher — an upper storey, a raised floor: the click ray
   *  then travels past the floor to the map's ground and the walk goal lands
   *  metres behind the pointer (parked review finding, E3). Callers hand in
   *  the height the figure stands at. */
  groundPointAt(clientX: number, clientY: number,
                planeY = 0): THREE.Vector3 | null {
    return this.groundPoint(clientX, clientY, planeY);
  }

  /** Ray through the pointer position, for anything outside the engine that
   *  needs to pick its own objects (E3-T1: the figures). The instance is the
   *  engine's own and is re-aimed on every call — use it right away. */
  raycasterAt(clientX: number, clientY: number): THREE.Raycaster {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster;
  }

  private pickLocation(clientX: number, clientY: number): string | null {
    const hits = this.raycasterAt(clientX, clientY).intersectObjects(this.pickables, true);
    for (const h of hits) {
      let o: THREE.Object3D | null = h.object;
      while (o) {
        if (o.userData.locationId) return o.userData.locationId as string;
        o = o.parent;
      }
    }
    return null;
  }

  private bindInput(container: HTMLElement) {
    const el = this.renderer.domElement;

    el.addEventListener('wheel', (e) => {
      e.preventDefault();
      // `cameraMath.wheelZoom`, taken apart only so the cap can report.
      const before = this.targetDist;
      this.targetDist = this.clampZoom(before * wheelFactor(e.deltaY));
      if (this.targetDist < before && !this.follow) {
        // Pull the target towards the cursor by exactly the fraction of the
        // distance that was just given up (`cameraMath.zoomTowardCursor`).
        const p = this.groundPoint(e.clientX, e.clientY);
        if (p) {
          const t = zoomTowardCursor([this.target.x, this.target.y, this.target.z],
            [p.x, p.z], before, this.targetDist);
          this.target.set(t[0], t[1], t[2]);
        }
      }
      this.flyT = 1; // abort a running camera fly
    }, { passive: false });

    el.addEventListener('pointerdown', (e) => {
      // Free orbit/tilt: middle button, Shift/Ctrl/Alt + left button — or the
      // bare left button while `orbitOnDrag` is set (B19, embodied mode). The
      // right button stays, but collides with mouse gestures in some browsers.
      const orbit = e.button === 1 || e.button === 2
        || (e.button === 0 && (this.orbitOnDrag || e.shiftKey || e.ctrlKey || e.altKey));
      if (orbit) {
        e.preventDefault();
        this.orbiting = true;
        this.moved = false;
        this.orbitLast = { x: e.clientX, y: e.clientY };
        this.orbitStart = { x: e.clientX, y: e.clientY };
        el.setPointerCapture(e.pointerId);
        return;
      }
      if (e.button !== 0) return;
      const p = this.groundPoint(e.clientX, e.clientY);
      if (!p) return;
      this.dragging = true;
      this.moved = false;
      this.dragStart.copy(p);
      el.setPointerCapture(e.pointerId);
    });
    // Prevent the browser's middle-click autoscroll.
    el.addEventListener('mousedown', (e) => {
      if (e.button === 1) e.preventDefault();
    });
    el.addEventListener('pointermove', (e) => {
      this.pointerAt = { x: e.clientX, y: e.clientY };
      this.pointerSeq += 1;
      if (this.orbiting) {
        const dx = e.clientX - this.orbitLast.x;
        const dy = e.clientY - this.orbitLast.y;
        // Turn on the FIRST pixel, but count as a drag only past the
        // threshold: since B19 the bare left button orbits while embodied, and
        // the same button is the walk order. One pixel of hand tremor between
        // press and release must not swallow the click.
        if (Math.hypot(e.clientX - this.orbitStart.x, e.clientY - this.orbitStart.y)
            > ORBIT_DRAG_PX) this.moved = true;
        this.orbitLast = { x: e.clientX, y: e.clientY };
        const step = orbitStep(this.targetYaw, this.pitchOffset, dx, dy, this.firstPerson);
        this.targetYaw = step.targetYaw;
        this.pitchOffset = step.pitchOffset;
        this.flyT = 1;
        return;
      }
      if (this.dragging) {
        const p = this.groundPoint(e.clientX, e.clientY);
        if (!p) return;
        const delta = this.dragStart.clone().sub(p);
        if (delta.length() > 0.15) this.moved = true;
        this.target.add(delta);
        this.flyT = 1;
      } else {
        this.onHover?.(this.pickLocation(e.clientX, e.clientY));
      }
    });
    el.addEventListener('pointerup', (e) => {
      const wasDrag = (this.dragging || this.orbiting) && this.moved;
      this.dragging = false;
      this.orbiting = false;
      if (wasDrag || e.button !== 0) return;
      // Figures first: a hit figure eats the click, so clicking a character
      // does not also open the tile's info panel.
      if (this.pickFigure?.(e.clientX, e.clientY)) return;
      // Then the ground: while embodied, a click on walkable ground is a walk
      // order and eats the click as well.
      if (this.onGroundClick?.(e.clientX, e.clientY)) return;
      this.onPick?.(this.pickLocation(e.clientX, e.clientY));
    });
    el.addEventListener('contextmenu', (e) => e.preventDefault());

    // Both keydown listeners ignore anything typed into a form field. The old
    // guard only knew `tagName === 'INPUT'`, so every character typed into the
    // HUD chat TEXTAREA also panned the camera (w/a/s/d) and turned it (q/e).
    window.addEventListener('keydown', (e) => {
      if (isTypingTarget(e)) return;
      this.keys.add(e.key.toLowerCase());
      if (e.key.toLowerCase() === 'q') this.targetYaw += Math.PI / 4;
      if (e.key.toLowerCase() === 'e') this.targetYaw -= Math.PI / 4;
    });
    window.addEventListener('keydown', (e) => {
      if (isTypingTarget(e)) return;
      if (e.key === '+') this.targetDist = this.clampZoom(this.targetDist * 0.8);
      if (e.key === '-') this.targetDist = this.clampZoom(this.targetDist * 1.25);
    });
    window.addEventListener('keyup', (e) => this.keys.delete(e.key.toLowerCase()));
    container.addEventListener('pointerleave', () => {
      this.pointerAt = null;
      this.pointerSeq += 1;
      this.onHover?.(null);
    });
  }

  /**
   * Slide the aim point out of the corner the HUD covers — the frustum shift
   * of `scene/viewShift.ts`, applied once per frame.
   *
   * `lookAt` has just put the target in the exact middle of the picture. This
   * renders an OFF-CENTRE cut-out of that same picture instead, which moves
   * where the target lands without touching the camera at all: direction,
   * horizon and the avatar's facing stay as they were, and everything that
   * projects through the camera — clicks, plates, bubbles, culling — follows
   * on its own because it all reads this one projection matrix.
   *
   * `setViewOffset(w, h, x, y, w, h)` shows the cut-out at (x, y) of a
   * full-size picture, so the point that would sit in the middle appears at
   * (w/2 − x, h/2 − y): a NEGATIVE x moves it right, a POSITIVE y moves it up.
   * Hence the two negations — `dx`/`dy` are screen axes (right, down).
   */
  private applyViewShift(dt: number) {
    const el = this.renderer.domElement;
    const w = el.clientWidth;
    const h = el.clientHeight;
    let box: ScreenBox | null = null;
    if (this.obstruction && w > 0 && h > 0) {
      // The HUD measures against the WINDOW, the rule works on the canvas.
      const rect = el.getBoundingClientRect();
      box = {
        x: this.obstruction.x - rect.left,
        y: this.obstruction.y - rect.top,
        w: this.obstruction.w,
        h: this.obstruction.h,
      };
    }
    const want = viewShiftFor(w, h, box);
    const k = damp(dt);
    this.viewDx += (want.dx - this.viewDx) * k;
    this.viewDy += (want.dy - this.viewDy) * k;
    // An exponential chase never arrives. Closing the last twentieth of a
    // pixel by hand is what lets a closed panel actually CLEAR the offset
    // again instead of leaving the camera permanently a hair off centre.
    if (want.dx === 0 && want.dy === 0
        && Math.abs(this.viewDx) < 0.05 && Math.abs(this.viewDy) < 0.05) {
      this.viewDx = 0;
      this.viewDy = 0;
    }
    const applied = this.viewApplied;
    if (this.viewDx === 0 && this.viewDy === 0) {
      if (applied) {
        this.camera.clearViewOffset();
        this.viewApplied = null;
      }
      return;
    }
    // Rebuilding the projection matrix on a frame that changed nothing is
    // waste — and once the chase has settled, nothing changes for minutes.
    if (applied && applied.w === w && applied.h === h
        && Math.abs(applied.dx - this.viewDx) < 0.01
        && Math.abs(applied.dy - this.viewDy) < 0.01) return;
    this.camera.setViewOffset(w, h, -this.viewDx, -this.viewDy, w, h);
    this.viewApplied = { dx: this.viewDx, dy: this.viewDy, w, h };
  }

  private placeFirstPerson(at: THREE.Vector3, viewDir: THREE.Vector3) {
    this.target.copy(at);
    this.camera.position.copy(at);
    this.camera.lookAt(SCRATCH.look.copy(at).add(viewDir));
  }

  /** Optional bench hooks: absent during normal play. Raw wall delta is never clamped. */
  benchFrame?: (dt: number) => void;
  benchCamera?: () => void;
  benchVisibility?: () => void;
  benchRendered?: (dt: number, cpuMs: number, calls: number, tris: number) => void;
  private benchFrameAt = 0;

  private frame() {
    const frameStart = this.benchRendered ? performance.now() : 0;
    const benchDt = this.benchFrameAt ? (frameStart - this.benchFrameAt) / 1000 : 0;
    this.benchFrameAt = this.benchRendered ? frameStart : 0;
    this.benchFrame?.(benchDt);
    const dt = Math.min(this.clock.getDelta(), MAX_FRAME_DT);
    // ONE time value for everything that moves by itself: the water surfaces
    // and, since the terrain animations, the swaying scatter (shared uniform).
    updateSurfaceMaterials(dt);

    // WASD/arrow-key pan relative to the view direction — skipped while a
    // follow target is set (E3-T2): the camera then belongs to the followed
    // figure and the keys to its movement.
    if (!this.follow) {
      const panSpeed = this.dist * 0.9 * dt;
      const fwd = SCRATCH.fwd.set(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
      const right = SCRATCH.right.set(-fwd.z, 0, fwd.x);
      if (this.keys.has('w') || this.keys.has('arrowup')) this.target.addScaledVector(fwd, panSpeed);
      if (this.keys.has('s') || this.keys.has('arrowdown')) this.target.addScaledVector(fwd, -panSpeed);
      if (this.keys.has('a') || this.keys.has('arrowleft')) this.target.addScaledVector(right, -panSpeed);
      if (this.keys.has('d') || this.keys.has('arrowright')) this.target.addScaledVector(right, panSpeed);
    }

    // Camera fly
    if (this.flyT < 1 && this.flyFrom && this.flyToPoint) {
      this.flyT = flyAdvance(this.flyT, dt);
      this.target.lerpVectors(this.flyFrom, this.flyToPoint, flyEase(this.flyT));
    }

    // Follow target — the ONE evaluation per frame, deliberately AFTER the fly:
    // during the fly-in both run, the fly carries the distance and the soft
    // chase closes the gap to the moving figure. Together they ARE the ride.
    const followAt = this.follow?.();
    if (followAt) this.target.lerp(followAt, 1 - Math.exp(-6 * dt));

    const ease = damp(dt);
    this.dist = THREE.MathUtils.lerp(this.dist, this.targetDist, ease);
    this.yaw = THREE.MathUtils.lerp(this.yaw, this.targetYaw, ease);

    // Require the eased zoom to reach the entry threshold too: one large
    // inward scroll must not teleport a distant camera straight to the eyes.
    const zoomDistance = this.firstPersonZoom.active ? this.targetDist
      : Math.max(this.dist - 1e-6, this.targetDist);
    const firstPerson = this.firstPersonZoom.update(zoomDistance, !!followAt, dt);
    const orbitDist = followAt ? Math.max(this.dist, THIRD_PERSON_MIN_DIST) : this.dist;
    const basePitch = firstPerson ? 0 : basePitchDeg(orbitDist, this.nearPitchDeg);
    const pitchDeg = clampPitchDeg(basePitch + this.pitchOffset, firstPerson);
    // `cameraMath.cameraPose`, written into the frame's scratch vector.
    const off = SCRATCH.off.fromArray(orbitOffset(this.yaw, pitchDeg, SCRATCH.offTuple));
    if (firstPerson && followAt) {
      // Place the lens at the actual eyes, without the chase lag behind a
      // walking avatar. Keep the orbit's view direction, now looking ahead.
      // Placed again after the frame hooks, once the figure has its pose.
      this.placeFirstPerson(followAt, off.negate());
    } else {
      this.camera.position.copy(this.target).add(off.multiplyScalar(orbitDist));
      this.camera.lookAt(this.target);
    }
    this.applyViewShift(dt);
    this.benchCamera?.();

    // The sun follows the map section so the shadow map can stay small — but it
    // follows it in WHOLE SHADOW TEXELS (`scene/shadowSnap.ts`). A frustum that
    // slid continuously with the target resampled the whole world on every
    // pan, and every shadow edge in the picture crawled along its own outline.
    const sx = Math.cos(this.sunAngle), sy = Math.max(0.08, Math.sin(this.sunAngle));
    const sunOff = SCRATCH.sunOff.set(sx * 60, sy * 80, 25);
    const centre = snapShadowCentre({
      target: [this.target.x, this.target.y, this.target.z],
      offset: [sunOff.x, sunOff.y, sunOff.z],
    });
    this.sun.target.position.set(centre[0], centre[1], centre[2]);
    this.sun.position.copy(this.sun.target.position).add(sunOff);

    for (const fn of this.frameHooks) fn(dt);
    // The own body is drawn in first person and the lens rides on its head
    // (`npcs.lensOf`): the figures were posed and moved by the hooks above,
    // so the follow point is asked again — the one from the top of the frame
    // lags a pose behind, and a walking body would run ahead of its own eyes.
    if (firstPerson) {
      const at = this.follow?.();
      if (at) this.placeFirstPerson(at, off);
    }
    this.benchCamera?.(); // Reassert after hooks and the first-person lens update.
    this.benchVisibility?.();
    this.renderer.render(this.scene, this.camera);
    this.benchRendered?.(benchDt, performance.now() - frameStart,
      this.renderer.info.render.calls, this.renderer.info.render.triangles);
    this.labelRenderer.render(this.scene, this.camera);
  }
}
