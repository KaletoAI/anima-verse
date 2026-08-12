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

export function asphaltTexture(): THREE.CanvasTexture {
  return canvasTexture(256, (ctx) => {
    const rnd = seededRandom('asphalt');
    ctx.fillStyle = '#5a5e63';
    ctx.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 1800; i++) {
      const g = 75 + Math.floor(rnd() * 40);
      ctx.fillStyle = `rgb(${g},${g},${g + 4})`;
      ctx.fillRect(rnd() * 256, rnd() * 256, 2, 2);
    }
  });
}

export function waterTexture(): THREE.CanvasTexture {
  return canvasTexture(256, (ctx) => {
    const rnd = seededRandom('water');
    ctx.fillStyle = '#3f7fb8';
    ctx.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 30; i++) {
      ctx.strokeStyle = `rgba(220,240,255,${0.10 + rnd() * 0.12})`;
      ctx.lineWidth = 1.5 + rnd() * 1.5;
      ctx.beginPath();
      const y = rnd() * 256;
      ctx.moveTo(rnd() * 60, y);
      ctx.bezierCurveTo(80 + rnd() * 40, y - 8 + rnd() * 16, 150 + rnd() * 40, y - 8 + rnd() * 16, 200 + rnd() * 56, y);
      ctx.stroke();
    }
  });
}

export function paversTexture(): THREE.CanvasTexture {
  return canvasTexture(256, (ctx) => {
    ctx.fillStyle = '#b8ac97';
    ctx.fillRect(0, 0, 256, 256);
    ctx.strokeStyle = 'rgba(90,80,65,0.45)';
    ctx.lineWidth = 2;
    for (let y = 0; y < 256; y += 32) {
      for (let x = 0; x < 256; x += 32) {
        const ox = (y / 32) % 2 === 0 ? 0 : 16;
        ctx.strokeRect(x + ox, y, 32, 32);
      }
    }
  });
}

/** Fassade mit Fensterraster; ein Teil der Fenster ist warm beleuchtet. */
export function facadeTexture(base: string, cols: number, rows: number, seed: string): THREE.CanvasTexture {
  return canvasTexture(256, (ctx) => {
    const rnd = seededRandom(seed);
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, 256, 256);
    const cw = 256 / cols;
    const ch = 256 / rows;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const lit = rnd() < 0.28;
        ctx.fillStyle = lit ? '#ffd98a' : '#31404f';
        ctx.fillRect(c * cw + cw * 0.22, r * ch + ch * 0.2, cw * 0.56, ch * 0.55);
        ctx.strokeStyle = 'rgba(0,0,0,0.25)';
        ctx.strokeRect(c * cw + cw * 0.22, r * ch + ch * 0.2, cw * 0.56, ch * 0.55);
      }
    }
    ctx.fillStyle = 'rgba(0,0,0,0.18)';
    ctx.fillRect(0, 248, 256, 8);
  });
}

/** Emissive-Gegenstück zu facadeTexture: alles schwarz, nur die beleuchteten
 *  Fenster leuchten (gleicher Seed -> dieselben Fenster wie in der Fassade). */
export function facadeEmissive(cols: number, rows: number, seed: string): THREE.CanvasTexture {
  return canvasTexture(256, (ctx) => {
    const rnd = seededRandom(seed);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, 256, 256);
    const cw = 256 / cols;
    const ch = 256 / rows;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const lit = rnd() < 0.28;   // identische Sequenz wie in facadeTexture
        if (lit) {
          ctx.fillStyle = '#fff';
          ctx.fillRect(c * cw + cw * 0.22, r * ch + ch * 0.2, cw * 0.56, ch * 0.55);
        }
      }
    }
  });
}

export function awningTexture(colorA: string, colorB: string): THREE.CanvasTexture {
  return canvasTexture(128, (ctx) => {
    for (let i = 0; i < 8; i++) {
      ctx.fillStyle = i % 2 ? colorA : colorB;
      ctx.fillRect(i * 16, 0, 16, 128);
    }
  });
}
