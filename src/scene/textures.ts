import * as THREE from 'three';

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

/** Deterministischer PRNG, damit die Karte bei jedem Laden gleich aussieht. */
export function seededRandom(seed: string): () => number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822519);
    h = Math.imul(h ^ (h >>> 13), 3266489917);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

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

export function awningTexture(colorA: string, colorB: string): THREE.CanvasTexture {
  return canvasTexture(128, (ctx) => {
    for (let i = 0; i < 8; i++) {
      ctx.fillStyle = i % 2 ? colorA : colorB;
      ctx.fillRect(i * 16, 0, 16, 128);
    }
  });
}
