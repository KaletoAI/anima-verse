import * as THREE from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { setSurfaceSky, updateSurfaceMaterials } from '@anima/scene-render';

const MIN_DIST = 2.5;   // ganz nah = Figur formatfüllend
const MAX_DIST = 150;

/**
 * AoE-artige Kamera: fester Pitch (leicht zoomabhängig), Yaw in 45°-Schritten,
 * Pan per Drag/WASD, Zoom per Mausrad Richtung Cursor.
 */
export class Engine {
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  labelRenderer: CSS2DRenderer;
  sun: THREE.DirectionalLight;
  hemi!: THREE.HemisphereLight;
  fill!: THREE.DirectionalLight;
  /** neutrale IBL für Server-Modelle mit echter Metal-Roughness-Textur */
  modelEnv: THREE.Texture;
  /** Sonnenstand aus der Spielzeit (0..24); steuert Licht, Farben, Himmel. */
  private sunAngle = Math.PI * 0.35;   // Default: später Vormittag
  /** 0 = heller Tag, 1 = tiefe Nacht — für Fensterlichter u.ä. */
  nightFactor = 0;
  onDayNight: ((night: number) => void) | null = null;

  target = new THREE.Vector3(0, 0, 0);
  dist = 80;
  targetDist = 80;
  yaw = Math.PI / 4;
  targetYaw = Math.PI / 4;

  private keys = new Set<string>();
  private dragging = false;
  private orbiting = false;              // rechte Maustaste: frei drehen
  private orbitLast = { x: 0, y: 0 };
  pitchOffset = 0;                       // freier Pitch-Anteil (Grad); public für Vorschau-Seiten
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

  constructor(container: HTMLElement) {
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.5, 800);

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
    this.fill = new THREE.DirectionalLight(0xdde8ff, 0.5);   // Gegenlicht, hebt Schattenseiten
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

  /** Tageszeit setzen (Stunde 0..24): Sonnenstand, Lichtfarben, Himmel, Nebel. */
  setGameHour(hour: number) {
    const h = ((hour % 24) + 24) % 24;
    // Sonnenbogen: 6 Uhr = Osten (0), 12 = Zenit (PI/2), 18 = Westen (PI)
    this.sunAngle = ((h - 6) / 12) * Math.PI;
    const day = THREE.MathUtils.clamp(Math.sin(this.sunAngle), 0, 1);       // 0 nachts, 1 mittags
    const dusk = THREE.MathUtils.clamp(1 - Math.abs(h - 12) / 6, 0, 1);     // Nähe zur Mittagszeit

    const noon = new THREE.Color(0xfff2d8);
    const warm = new THREE.Color(0xffb066);   // Morgen-/Abendrot
    const night = new THREE.Color(0x9fb4e0);  // Mondlicht (kühl)
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
    // Blendfaktor erreicht 1 bei day=0.15 — stetiger Übergang zum Nacht-Zweig
    if (day > 0.15 && day < 0.35) sky.lerp(skyDusk, (0.35 - day) / 0.2);
    (this.scene.background as THREE.Color).copy(sky);
    (this.scene.fog as THREE.Fog).color.copy(sky);
    // Wasserflächen spiegeln den Himmel (Fresnel im geteilten Material) —
    // damit wird der See abends orange und nachts dunkel, ohne eigenen Code.
    setSurfaceSky(sky.getHex());

    this.nightFactor = THREE.MathUtils.clamp(1 - day * 3, 0, 1);
    this.onDayNight?.(this.nightFactor);
  }

  addFrameHook(fn: (dt: number) => void) {
    this.frameHooks.push(fn);
  }

  setPickables(objs: THREE.Object3D[]) {
    this.pickables = objs;
  }

  /** Kamera sanft auf einen Punkt + Distanz fahren. */
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

  private groundPoint(clientX: number, clientY: number): THREE.Vector3 | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(this.groundPlane, hit) ? hit : null;
  }

  private pickLocation(clientX: number, clientY: number): string | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.pickables, true);
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
        const p = this.groundPoint(e.clientX, e.clientY);
        if (p) this.target.lerp(p, 1 - this.targetDist / before);
      }
      this.flyT = 1; // laufende Kamerafahrt abbrechen
    }, { passive: false });

    el.addEventListener('pointerdown', (e) => {
      // Frei drehen/neigen: mittlere Taste oder Shift/Strg/Alt+links.
      // Rechte Taste bleibt, kollidiert aber je nach Browser mit Maus-Gesten.
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
      if (!wasDrag && e.button === 0) this.onPick?.(this.pickLocation(e.clientX, e.clientY));
    });
    el.addEventListener('contextmenu', (e) => e.preventDefault());

    window.addEventListener('keydown', (e) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
      this.keys.add(e.key.toLowerCase());
      if (e.key.toLowerCase() === 'q') this.targetYaw += Math.PI / 4;
      if (e.key.toLowerCase() === 'e') this.targetYaw -= Math.PI / 4;
    });
    window.addEventListener('keydown', (e) => {
      if (e.key === '+') this.targetDist = THREE.MathUtils.clamp(this.targetDist * 0.8, MIN_DIST, MAX_DIST);
      if (e.key === '-') this.targetDist = THREE.MathUtils.clamp(this.targetDist * 1.25, MIN_DIST, MAX_DIST);
    });
    window.addEventListener('keyup', (e) => this.keys.delete(e.key.toLowerCase()));
    container.addEventListener('pointerleave', () => this.onHover?.(null));
  }

  private frame() {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    // Eine Zeit für ALLE Wasserflächen (geteiltes Uniform).
    updateSurfaceMaterials(dt);

    // WASD/Pfeiltasten-Pan relativ zur Blickrichtung
    const panSpeed = this.dist * 0.9 * dt;
    const fwd = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    const right = new THREE.Vector3(-fwd.z, 0, fwd.x);
    if (this.keys.has('w') || this.keys.has('arrowup')) this.target.addScaledVector(fwd, panSpeed);
    if (this.keys.has('s') || this.keys.has('arrowdown')) this.target.addScaledVector(fwd, -panSpeed);
    if (this.keys.has('a') || this.keys.has('arrowleft')) this.target.addScaledVector(right, -panSpeed);
    if (this.keys.has('d') || this.keys.has('arrowright')) this.target.addScaledVector(right, panSpeed);

    // Kamerafahrt
    if (this.flyT < 1 && this.flyFrom && this.flyToPoint) {
      this.flyT = Math.min(1, this.flyT + dt * 1.6);
      const k = this.flyT * this.flyT * (3 - 2 * this.flyT);
      this.target.lerpVectors(this.flyFrom, this.flyToPoint, k);
    }

    this.dist = THREE.MathUtils.lerp(this.dist, this.targetDist, 1 - Math.exp(-8 * dt));
    this.yaw = THREE.MathUtils.lerp(this.yaw, this.targetYaw, 1 - Math.exp(-8 * dt));

    // Pitch: ganz nah fast auf Augenhöhe (18°), fern steil (62°); rechte Maus
    // verschiebt den Winkel zusätzlich frei
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

    // Sonne folgt dem Kartenausschnitt, damit die Shadow-Map klein bleiben kann
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
