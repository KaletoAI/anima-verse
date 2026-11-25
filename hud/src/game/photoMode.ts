/** Browser photo-mode lifecycle. The engine owns its lens and render-task capture. */
import type { PhotoView } from '@anima/player-ui';
import type { Engine } from '../scene/engine';
import { isTypingTarget } from '../hud/dom';
import { cropPhotoView, type PhotoRect } from './photoView';

export interface PhotoSelection { canvas: HTMLCanvasElement; choose: (rect: PhotoRect) => void; }
export interface PhotoHintState { active: boolean; speed: number; capturing: boolean | PhotoSelection; }
export interface PhotoFrame { jpeg: Blob; view: PhotoView; }
export type PhotoCapture = (source: HTMLCanvasElement, view: PhotoView) => Promise<PhotoFrame>;

export function photoSelectionRect(start: {x: number; y: number}, end: {x: number; y: number},
  bounds: {left: number; top: number; width: number; height: number}, width: number, height: number): PhotoRect {
  const x = (n: number) => Math.round(Math.max(0, Math.min(1, (n - bounds.left) / bounds.width)) * width);
  const y = (n: number) => Math.round(Math.max(0, Math.min(1, (n - bounds.top) / bounds.height)) * height);
  return { x: Math.min(x(start.x), x(end.x)), y: Math.min(y(start.y), y(end.y)),
    width: Math.abs(x(end.x) - x(start.x)), height: Math.abs(y(end.y) - y(start.y)) };
}

export function photoShotRect(rect: PhotoRect, width: number, height: number): PhotoRect {
  return rect.width < 64 || rect.height < 64 ? {x: 0, y: 0, width, height} : rect;
}

/** Copy/encode synchronously after render; toBlob snapshots before its async callback. */
export function encodePhotoCanvas(source: HTMLCanvasElement,
  makeCanvas = () => document.createElement('canvas'),
  rect: PhotoRect = {x: 0, y: 0, width: source.width, height: source.height}): Promise<Blob> {
  return new Promise((resolve, reject) => {
    let canvas = source;
    const scale = Math.min(1, 2048 / Math.max(rect.width, rect.height));
    const cropped = rect.x !== 0 || rect.y !== 0 || rect.width !== source.width || rect.height !== source.height;
    if (scale < 1 || cropped) {
      canvas = makeCanvas();
      canvas.width = Math.max(1, Math.round(rect.width * scale));
      canvas.height = Math.max(1, Math.round(rect.height * scale));
      const ctx = canvas.getContext('2d');
      if (!ctx) { reject(new Error('Photo capture failed')); return; }
      if (cropped) ctx.drawImage(source, rect.x, rect.y, rect.width, rect.height, 0, 0, canvas.width, canvas.height);
      else ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    }
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Photo capture failed')), 'image/jpeg', .9);
  });
}

interface PhotoModeDeps {
  engine: Pick<Engine, 'photoMode' | 'photoSpeed' | 'enterPhotoMode' | 'leavePhotoMode' | 'capturePhotoFrame' | 'setPhotoSelecting'>;
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
  let selecting = false;
  let selection: PhotoSelection | null = null;
  let chooseFull: (() => void) | null = null;
  let cancelSelection: (() => void) | null = null;
  let fullRequested = false;
  const updateHint = () => deps.hint({ active: deps.engine.photoMode, speed: deps.engine.photoSpeed, capturing: selection ?? busy });
  function back() {
    session++;
    cancelSelection?.(); cancelSelection = null; chooseFull = null; selection = null;
    selecting = false; busy = false;
    deps.engine.setPhotoSelecting(false);
    updateHint();
  }
  function leave() {
    back();
    deps.engine.leavePhotoMode();
    restoreHud?.(); restoreHud = null;
    updateHint();
  }
  async function shoot() {
    if (busy) return;
    busy = true;
    selecting = true; fullRequested = false;
    deps.engine.setPhotoSelecting(true);
    const shotSession = session;
    let handedOff = false;
    updateHint();
    try {
      const frame = await deps.engine.capturePhotoFrame(deps.view, (source, view) => {
        // Copy in the render task before WebGL clears its buffer. Keep native pixels
        // and the matching view immutable while the world continues behind selection.
        if (shotSession !== session) return Promise.reject(new Error('Photo capture cancelled'));
        const canvas = document.createElement('canvas');
        canvas.width = source.width; canvas.height = source.height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return Promise.reject(new Error('Photo capture failed'));
        ctx.drawImage(source, 0, 0);
        return new Promise<PhotoRect>((resolve, reject) => {
          cancelSelection = () => reject(new Error('Photo capture cancelled'));
          selection = { canvas, choose: resolve };
          chooseFull = () => resolve({x: 0, y: 0, width: canvas.width, height: canvas.height});
          updateHint();
          if (fullRequested) chooseFull();
        }).then(async selected => {
          const rect = photoShotRect(selected, canvas.width, canvas.height);
          const croppedView = cropPhotoView(view, rect, canvas.width, canvas.height);
          if (shotSession === session) {
            selection = null; selecting = false; chooseFull = null; cancelSelection = null; updateHint();
          }
          return {jpeg: await encodePhotoCanvas(canvas, undefined, rect), view: croppedView};
        });
      });
      if (shotSession !== session) return;
      handedOff = true;
      leave();
      busy = true;
      deps.taken?.();
      await deps.upload(frame.jpeg, frame.view);
    } catch (error) {
      if (!handedOff && shotSession !== session) return;
      if (shotSession === session) leave();
      deps.error(error);
    } finally { if (shotSession === session || handedOff) { busy = false; updateHint(); } }
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
        if (active && selecting) back();
        else if (active) leave();
        else if (!busy) {
          session++;
          deps.engine.enterPhotoMode();
          restoreHud = deps.hideHud();
          updateHint();
        }
      } else if (selecting) { fullRequested = true; chooseFull?.(); }
      else void shoot();
      return true;
    },
  };
}
