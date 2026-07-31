import * as THREE from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { setSurfaceSky, updateSurfaceMaterials } from '@anima/scene-render';

/**
 * Closest the camera may get to its target. Derived from the smallest figure
 * that has to be able to fill the frame: with the 45° vertical FOV a height h
 * fills the picture at dist = h / (2·tan(22.5°)) ≈ 1.21·h. Indoors figures are
 * drawn at scale ~0.3, so a 1.70 m character is ~0.5 m tall and fills the frame
 * at ~0.61 m — 0.8 m keeps that reachable and still leaves a little air
 * (visible height 2·0.8·tan(22.5°) ≈ 0.66 m, the figure covers ~76% of it).
 * The old 2.5 m could not do this: indoors it framed 2 m of empty room.
 */
export const MIN_DIST = 0.8;
const MAX_DIST = 150;

/**
 * True while the key event came out of a form field — typing must never reach
 * the camera. Shared with `main.ts`, which guards its own Esc handler with the
 * exact same rule (E3-T2), so there is ONE definition of "the user is typing".
 */
export function isTypingTarget(e: Event): boolean {
  return !!(e.target as HTMLElement)?.closest?.('input, textarea, select, [contenteditable]');
}

/**
 * AoE-style camera: fixed pitch (slightly zoom-dependent), yaw in 45° steps,
 * pan by drag/WASD, zoom by mouse wheel towards the cursor.
 */
export class Engine {
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  labelRenderer: CSS2DRenderer;
  sun: THREE.DirectionalLight;
  hemi!: THREE.HemisphereLight;
  fill!: THREE.DirectionalLight;
  /** neutral IBL for server models that carry a real metal-roughness texture */
  modelEnv: THREE.Texture;
  /** Sun position from the game time (0..24); drives light, colours, sky. */
  private sunAngle = Math.PI * 0.35;   // default: late morning
  /** 0 = bright day, 1 = deep night — for window lights and the like. */
  nightFactor = 0;
  onDayNight: ((night: number) => void) | null = null;

  target = new THREE.Vector3(0, 0, 0);
  dist = 80;
  targetDist = 80;
  yaw = Math.PI / 4;
  targetYaw = Math.PI / 4;

  private keys = new Set<string>();
  private dragging = false;
  private orbiting = false;              // right mouse button: free orbit
  private orbitLast = { x: 0, y: 0 };
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
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.domElement.className = 'label-layer';
    container.appendChild(this.labelRenderer.domElement);

    this.modelEnv = new THREE.PMREMGenerator(this.renderer)
      .fromScene(new RoomEnvironment(), 0.04).texture;

    this.scene.background = new THREE.Color(0x9fc7e8);
    this.scene.fog = new THREE.Fog(0x9fc7e8, 220, 520);

    this.hemi = new THREE.HemisphereLight(0xdfeeff, 0x8a9a78, 1.5);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(0xfff2d8, 2.0);
    this.fill = new THREE.DirectionalLight(0xdde8ff, 0.5);   // back light, lifts the shadow sides
    this.fill.position.set(-30, 20, -25);
    this.scene.add(this.fill);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0004;
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
    (this.scene.fog as THREE.Fog).color.copy(sky);
    // Water surfaces mirror the sky (Fresnel in the shared material) — that
    // alone turns the lake orange in the evening and dark at night.
    setSurfaceSky(sky.getHex());

    this.nightFactor = THREE.MathUtils.clamp(1 - day * 3, 0, 1);
    this.onDayNight?.(this.nightFactor);
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

  /** Ease the camera onto a point + distance. */
  flyTo(point: THREE.Vector3, dist: number) {
    this.flyFrom = this.target.clone();
    this.flyToPoint = point.clone();
    this.flyT = 0;
    this.targetDist = THREE.MathUtils.clamp(dist, MIN_DIST, MAX_DIST);
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
      const factor = Math.exp(e.deltaY * 0.0012);
      const before = this.targetDist;
      this.targetDist = THREE.MathUtils.clamp(before * factor, MIN_DIST, MAX_DIST);
      if (this.targetDist < before) {
        // Pull the target towards the cursor by exactly the fraction of the
        // distance that was just given up. `before` is a clamped distance and
        // therefore ≥ MIN_DIST > 0, so the ratio can never divide by zero; at
        // the MIN_DIST floor it becomes 0 and the target simply stays put.
        const p = this.groundPoint(e.clientX, e.clientY);
        if (p) this.target.lerp(p, 1 - this.targetDist / before);
      }
      this.flyT = 1; // abort a running camera fly
    }, { passive: false });

    el.addEventListener('pointerdown', (e) => {
      // Free orbit/tilt: middle button or Shift/Ctrl/Alt + left button. The
      // right button stays, but collides with mouse gestures in some browsers.
      const orbit = e.button === 1 || e.button === 2
        || (e.button === 0 && (e.shiftKey || e.ctrlKey || e.altKey));
      if (orbit) {
        e.preventDefault();
        this.orbiting = true;
        this.moved = false;
        this.orbitLast = { x: e.clientX, y: e.clientY };
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
    // Middle-Click-Autoscroll des Browsers unterbinden
    el.addEventListener('mousedown', (e) => {
      if (e.button === 1) e.preventDefault();
    });
    el.addEventListener('pointermove', (e) => {
      if (this.orbiting) {
        const dx = e.clientX - this.orbitLast.x;
        const dy = e.clientY - this.orbitLast.y;
        if (dx || dy) this.moved = true;
        this.orbitLast = { x: e.clientX, y: e.clientY };
        this.targetYaw -= dx * 0.005;
        this.pitchOffset = THREE.MathUtils.clamp(this.pitchOffset + dy * 0.25, -35, 35);
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
      if (e.key === '+') this.targetDist = THREE.MathUtils.clamp(this.targetDist * 0.8, MIN_DIST, MAX_DIST);
      if (e.key === '-') this.targetDist = THREE.MathUtils.clamp(this.targetDist * 1.25, MIN_DIST, MAX_DIST);
    });
    window.addEventListener('keyup', (e) => this.keys.delete(e.key.toLowerCase()));
    container.addEventListener('pointerleave', () => this.onHover?.(null));
  }

  private frame() {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    // ONE time value for ALL water surfaces (shared uniform).
    updateSurfaceMaterials(dt);

    // WASD/arrow-key pan relative to the view direction — skipped while a
    // follow target is set (E3-T2): the camera then belongs to the followed
    // figure and the keys to its movement.
    if (!this.follow) {
      const panSpeed = this.dist * 0.9 * dt;
      const fwd = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
      const right = new THREE.Vector3(-fwd.z, 0, fwd.x);
      if (this.keys.has('w') || this.keys.has('arrowup')) this.target.addScaledVector(fwd, panSpeed);
      if (this.keys.has('s') || this.keys.has('arrowdown')) this.target.addScaledVector(fwd, -panSpeed);
      if (this.keys.has('a') || this.keys.has('arrowleft')) this.target.addScaledVector(right, -panSpeed);
      if (this.keys.has('d') || this.keys.has('arrowright')) this.target.addScaledVector(right, panSpeed);
    }

    // Camera fly
    if (this.flyT < 1 && this.flyFrom && this.flyToPoint) {
      this.flyT = Math.min(1, this.flyT + dt * 1.6);
      const k = this.flyT * this.flyT * (3 - 2 * this.flyT);
      this.target.lerpVectors(this.flyFrom, this.flyToPoint, k);
    }

    // Follow target — the ONE evaluation per frame, deliberately AFTER the fly:
    // during the fly-in both run, the fly carries the distance and the soft
    // chase closes the gap to the moving figure. Together they ARE the ride.
    const followAt = this.follow?.();
    if (followAt) this.target.lerp(followAt, 1 - Math.exp(-6 * dt));

    this.dist = THREE.MathUtils.lerp(this.dist, this.targetDist, 1 - Math.exp(-8 * dt));
    this.yaw = THREE.MathUtils.lerp(this.yaw, this.targetYaw, 1 - Math.exp(-8 * dt));

    // Pitch: nearly eye level up close (18°), steep when far out (62°); the
    // right mouse button shifts the angle on top of that. zoomK is normalised
    // against MIN_DIST, so lowering MIN_DIST keeps the near end at exactly 18°
    // (dist = MIN_DIST ⇒ zoomK = 0) and the divisor MAX_DIST − MIN_DIST = 149.2
    // can never be zero.
    const zoomK = THREE.MathUtils.clamp((this.dist - MIN_DIST) / (MAX_DIST - MIN_DIST), 0, 1);
    const basePitch = THREE.MathUtils.lerp(18, 62, Math.sqrt(zoomK));
    const pitch = THREE.MathUtils.degToRad(THREE.MathUtils.clamp(basePitch + this.pitchOffset, 8, 85));

    const off = new THREE.Vector3(
      Math.sin(this.yaw) * Math.cos(pitch),
      Math.sin(pitch),
      Math.cos(this.yaw) * Math.cos(pitch)
    ).multiplyScalar(this.dist);
    this.camera.position.copy(this.target).add(off);
    this.camera.lookAt(this.target);

    // The sun follows the map section so the shadow map can stay small
    const sx = Math.cos(this.sunAngle), sy = Math.max(0.08, Math.sin(this.sunAngle));
    this.sun.position.copy(this.target).add(new THREE.Vector3(sx * 60, sy * 80, 25));
    this.sun.target.position.copy(this.target);
    const s = this.sun.shadow.camera;
    s.left = -70; s.right = 70; s.top = 70; s.bottom = -70; s.far = 300;
    s.updateProjectionMatrix();

    for (const fn of this.frameHooks) fn(dt);
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}
