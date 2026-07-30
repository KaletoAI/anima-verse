/**
 * React island of the 3D client (plan-3d-game stage 2, task 5).
 *
 * The vanilla Three.js app stays untouched: the HUD renders into the
 * dedicated `#hud` element next to `#app` and never touches the canvas.
 * `mountHud` is idempotent — a second call (e.g. a re-run of startApp after
 * login) unmounts the previous root first.
 */
import { createRoot, type Root } from 'react-dom/client';
import { I18nProvider, ToastProvider } from '@anima/player-ui';
import { Hud } from './Hud';

let root: Root | null = null;

export function mountHud(opts: { username: string; avatar: string }): void {
  const host = document.getElementById('hud');
  if (!host) throw new Error('mountHud: #hud element missing');
  if (root) {
    root.unmount();
    root = null;
  }
  root = createRoot(host);
  // ToastProvider is mandatory: ScenePanel calls useToast() and throws on
  // mount without it. Same provider nesting as /play (frontend player/main).
  // `opts.username` is part of the mount contract but unused in HUD v1 — the
  // vanilla top bar already shows the login name.
  root.render(
    <I18nProvider>
      <ToastProvider>
        <Hud avatar={opts.avatar} />
      </ToastProvider>
    </I18nProvider>
  );
}
