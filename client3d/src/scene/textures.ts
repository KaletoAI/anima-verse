import * as THREE from 'three';
import { seededRandom } from '@anima/scene-render';

function canvasTexture(size: number, draw: (ctx: CanvasRenderingContext2D) => void): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d')!;
  draw(ctx);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  return tex;
}

/**
 * Deterministic PRNG, so the map looks the same on every load.
 *
 * The body MOVED to `@anima/scene-render` (`scatter.ts`): the map editor has
 * to draw the very points the 3D ground plants, which only works if both sides
 * pull the same numbers in the same order — and a second body here is how that
 * stops being true. Re-exported rather than re-pointed at seven call sites,
 * because this is where the client has always asked for it.
 */
export { seededRandom };

export function grassTexture(): THREE.CanvasTexture {
  return canvasTexture(256, (ctx) => {
    const rnd = seededRandom('grass');
    ctx.fillStyle = '#7fa055';
    ctx.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 2600; i++) {
      const g = 130 + Math.floor(rnd() * 55);
      ctx.fillStyle = `rgb(${g - 45},${g},${60 + Math.floor(rnd() * 30)})`;
      ctx.fillRect(rnd() * 256, rnd() * 256, 2, 2);
    }
    for (let i = 0; i < 14; i++) {
      ctx.fillStyle = `rgba(110,130,70,${0.12 + rnd() * 0.1})`;
      ctx.beginPath();
      ctx.ellipse(rnd() * 256, rnd() * 256, 18 + rnd() * 30, 12 + rnd() * 22, rnd() * Math.PI, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}
