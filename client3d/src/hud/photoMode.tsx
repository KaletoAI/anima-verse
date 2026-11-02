/** A small local React island also works when the main HUD lives in an iframe. */
import { createRoot } from 'react-dom/client';
import { I18nProvider } from '@anima/player-ui';
import { PhotoModeHint } from './PhotoModeHint';
import type { PhotoHintState } from '../game/photoMode';

export function mountPhotoHint() {
  const host = document.createElement('div');
  host.id = 'photo-mode-overlay';
  document.body.appendChild(host);
  const root = createRoot(host);
  let previous = '';
  let taken = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let state: PhotoHintState = { active: false, speed: 4, capturing: false };
  function render() {
    const key = `${state.active}/${state.speed}/${state.capturing}/${taken}`;
    if (key === previous) return;
    previous = key;
    root.render(<I18nProvider><PhotoModeHint state={state} taken={taken} /></I18nProvider>);
  }
  return {
    update(next: PhotoHintState) { state = next; render(); },
    taken() {
      taken = true; render();
      clearTimeout(timer);
      timer = setTimeout(() => { taken = false; render(); }, 1200);
    },
  };
}
