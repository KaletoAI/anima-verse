/** Browser photo-mode lifecycle. The engine owns its lens and render-task capture. */
import type { PhotoView } from '@anima/player-ui';
import type { Engine } from '../scene/engine';
import { isTypingTarget } from '../hud/dom';

export interface PhotoHintState { active: boolean; speed: number; capturing: boolean; }
export interface PhotoFrame { jpeg: Blob; view: PhotoView; }

/** Copy/encode synchronously after render; toBlob snapshots before its async callback. */
export function encodePhotoCanvas(source: HTMLCanvasElement,
  makeCanvas = () => document.createElement('canvas')): Promise<Blob> {
  return new Promise((resolve, reject) => {
    let canvas = source;
    const scale = Math.min(1, 2048 / Math.max(source.width, source.height));
    if (scale < 1) {
      canvas = makeCanvas();
      canvas.width = Math.max(1, Math.round(source.width * scale));
      canvas.height = Math.max(1, Math.round(source.height * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) { reject(new Error('Photo capture failed')); return; }
      ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    }
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Photo capture failed')), 'image/jpeg', .9);
  });
}

interface PhotoModeDeps {
  engine: Pick<Engine, 'photoMode' | 'photoSpeed' | 'enterPhotoMode' | 'leavePhotoMode' | 'capturePhotoFrame'>;
  view: () => PhotoView;
  hideHud: () => () => void;
  hint: (state: PhotoHintState) => void;
  upload: (jpeg: Blob, view: PhotoView) => Promise<void>;
  error: (error: unknown) => void;
  taken?: () => void;
}

export function createPhotoMode(deps: PhotoModeDeps) {
  let restoreHud: (() => void) | null = null;
  let busy = false;
  let session = 0;
  const updateHint = () => deps.hint({ active: deps.engine.photoMode, speed: deps.engine.photoSpeed, capturing: busy });
  function leave() {
    session++;
    deps.engine.leavePhotoMode();
    restoreHud?.(); restoreHud = null;
    updateHint();
  }
  async function shoot() {
    if (busy) return;
    busy = true;
    const shotSession = session;
    let handedOff = false;
    updateHint();
    try {
      const frame = await deps.engine.capturePhotoFrame(deps.view);
      if (shotSession !== session) return;
      handedOff = true;
      leave();
      deps.taken?.();
      await deps.upload(frame.jpeg, frame.view);
    } catch (error) {
      if (!handedOff && shotSession !== session) return;
      if (shotSession === session) leave();
      deps.error(error);
    } finally { busy = false; updateHint(); }
  }
  return {
    updateHint, leave,
    keydown(e: KeyboardEvent, typing: boolean): boolean {
      if (typing || isTypingTarget(e) || e.ctrlKey || e.metaKey || e.altKey) return false;
      const active = deps.engine.photoMode;
      if (e.key !== 'F2' && !(active && (e.key === 'Escape' || e.key === ' '))) return false;
      e.preventDefault(); e.stopImmediatePropagation();
      if (e.repeat) return true;
      if (e.key === 'F2' || e.key === 'Escape') {
        if (active) leave();
        else if (!busy) {
          session++;
          deps.engine.enterPhotoMode();
          restoreHud = deps.hideHud();
          updateHint();
        }
      } else void shoot();
      return true;
    },
  };
}
