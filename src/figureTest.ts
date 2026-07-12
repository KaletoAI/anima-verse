// Diagnose-Seite: /figure-test.html?model=Kira&clip=idle
// Rendert eine Figur isoliert, groß und neutral beleuchtet.
import * as THREE from 'three';
import { FigureLibrary } from './scene/figures';

const params = new URLSearchParams(location.search);
const who = params.get('model') ?? 'Kira';
const clipKind = (params.get('clip') ?? 'idle') as 'idle' | 'walk' | 'run';

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x8899aa);
scene.add(new THREE.HemisphereLight(0xffffff, 0x888877, 1.4));
const sun = new THREE.DirectionalLight(0xffffff, 2.0);
sun.position.set(2, 4, 3);
scene.add(sun);
scene.add(new THREE.GridHelper(4, 8, 0x555555, 0x777777));

const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 1.4, 3.4);
camera.lookAt(0, 0.9, 0);

// Interaktiv: Ziehen = drehen, Rad = zoomen, rechte Taste = verschieben
let controls: import('three/addons/controls/OrbitControls.js').OrbitControls | null = null;
import('three/addons/controls/OrbitControls.js').then(({ OrbitControls }) => {
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.9, 0);
  controls.enableDamping = true;
  controls.update();
});

const lib = new FigureLibrary();
const clock = new THREE.Clock();
let figure: ReturnType<FigureLibrary['instantiate']> = null;
let rawRoot: THREE.Object3D | null = null;

const rawUrl = params.get('raw'); // ?raw=/models/x.glb|.fbx [&tex=/models/t.png&flip=1]
if (rawUrl) {
  const loadRaw = async (): Promise<THREE.Object3D> => {
    if (/\.fbx(\?|$)/i.test(rawUrl)) {
      const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
      return await new FBXLoader().loadAsync(rawUrl);
    }
    const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
    return (await new GLTFLoader().loadAsync(rawUrl)).scene;
  };
  loadRaw().then(async (root) => {
    const texUrl = params.get('tex');
    if (texUrl) {
      const tex = await new THREE.TextureLoader().loadAsync(texUrl);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.flipY = params.get('flip') === '1';
      root.traverse((o) => {
        if ((o as THREE.Mesh).isMesh) {
          (o as THREE.Mesh).material = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.85 });
        }
      });
    }
    {
      const box = new THREE.Box3().setFromObject(root);
      const size = box.getSize(new THREE.Vector3());
      const scale = 1.7 / Math.max(size.x, size.y, size.z, 0.01);
      root.scale.setScalar(scale);
      const box2 = new THREE.Box3().setFromObject(root);
      root.position.y -= box2.min.y;
      const c = box2.getCenter(new THREE.Vector3());
      root.position.x -= c.x;
      root.position.z -= c.z;
      rawRoot = root;
      scene.add(root);
      document.title = 'Raw: ' + rawUrl;
    }
  });
} else {
  lib.load({ only: who }).then(() => {
    figure = lib.instantiate(who);
    if (!figure) {
      document.title = 'Modell nicht gefunden: ' + who;
      return;
    }
    figure.play(clipKind);
    scene.add(figure.root);
    document.title = `Figur-Test: ${who} (${clipKind})`;
  });
}

const autoRotate = params.get('spin') === '1'; // Standard: selbst drehen per Maus
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  figure?.update(dt);
  if (autoRotate) {
    if (figure) figure.root.rotation.y += dt * 0.4;
    if (rawRoot) rawRoot.rotation.y += dt * 0.4;
  }
  controls?.update();
  renderer.render(scene, camera);
});
