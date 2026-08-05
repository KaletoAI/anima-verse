/**
 * React island of the 3D client (plan-3d-game stage 2, task 5; title screen
 * added in stage 4, task 3).
 *
 * The vanilla Three.js app stays untouched: the HUD renders into the
 * dedicated `#hud` element next to `#app` and never touches the canvas.
 * `mountHud` is idempotent — a second call (e.g. a re-run of startApp after
 * login) unmounts the previous root first.
 *
 * TWO MOUNTS, TWO ROOTS. `mountTitle` is the second entry point of the same
 * island, and it renders into its OWN node (`#hud-title`, created here and
 * appended after `#hud`) rather than into `#hud` with a mode prop. Two
 * reasons, both about ownership: the two overlap in time — the title stays up
 * while `startApp` builds the world and mounts the HUD underneath it, so one
 * root would have to keep both trees alive at once for no gain — and a React
 * root whose container also holds another root's tree is a question nobody
 * wants to answer later. The title unmounts itself and takes its node with it.
 *
 * `I18nProvider` wraps both: every string on the title screen goes through
 * `t()`. `ToastProvider` wraps only the HUD — the title screen shows its
 * login error inline and has no toast consumer.
 */
import { createRoot, type Root } from 'react-dom/client';
import { I18nProvider, ToastProvider } from '@anima/player-ui';
import { Hud } from './Hud';
// After `Hud`, deliberately: Hud pulls panels.css -> hud.css ->
// theme-fantasy.css in that order, and the title screen's own imports of the
// last two must not get in front of the shared defaults they override.
import { TitleScreen, type TitleScreenProps } from './TitleScreen';

let root: Root | null = null;
let titleRoot: Root | null = null;
let titleNode: HTMLElement | null = null;

/** Options of `mountTitle` — everything but `onDone`, which is this module's
 *  own business (it unmounts the root and removes the node). */
export type MountTitleOpts = Omit<TitleScreenProps, 'onDone'>;

/**
 * Show the title / login / loading screen. Mounted BEFORE the game exists and
 * gone once `game/boot.ts` reports the last stage; idempotent like `mountHud`.
 */
export function mountTitle(opts: MountTitleOpts): void {
  closeTitle();
  const node = document.createElement('div');
  node.id = 'hud-title';
  document.body.appendChild(node);
  titleNode = node;
  titleRoot = createRoot(node);
  titleRoot.render(
    <I18nProvider>
      <TitleScreen {...opts} onDone={closeTitle} />
    </I18nProvider>
  );
}

function closeTitle(): void {
  const oldRoot = titleRoot;
  const oldNode = titleNode;
  if (!oldRoot) return;
  titleRoot = null;
  titleNode = null;
  // The node is captured, never looked up again: a re-mount creates a fresh
  // `#hud-title` before this timer fires, and an id lookup would delete THAT
  // one. Deferring at all is what React asks for — unmounting a root from
  // inside its own lifecycle (the fade timer) is a flush during render.
  setTimeout(() => {
    oldRoot.unmount();
    oldNode?.remove();
  }, 0);
}

export function mountHud(opts: { username: string; avatar: string; role: string }): void {
  const host = document.getElementById('hud');
  if (!host) throw new Error('mountHud: #hud element missing');
  if (root) {
    root.unmount();
    root = null;
  }
  root = createRoot(host);
  // ToastProvider is mandatory: ScenePanel calls useToast() and throws on
  // mount without it. Same provider nesting as /play (frontend player/main).
  // `opts.username` is not shown anywhere (the vanilla top bar already carries
  // the login name) — it is the identity `/tts/speak` is asked with (E4-T6).
  // `opts.role` gates the admin entry of the game menu (Etappe 5): a switch
  // only an administrator may use is only offered to one.
  root.render(
    <I18nProvider>
      <ToastProvider>
        <Hud avatar={opts.avatar} username={opts.username} role={opts.role} />
      </ToastProvider>
    </I18nProvider>
  );
}
