/** Standalone HUD: API requests share the host origin and cookie session. */
import * as api from './api';
import { connectHudSide, postMessageTransport } from './hud/bridge';
import { getBoot, setBoot, setHudUiState } from './hud/bus';
import { mountHud, mountTitle } from './hud/mount';
import type { AuthUser } from './types';

const embedded = window.parent !== window;
const disconnect = connectHudSide(postMessageTransport(window.parent, location.origin));
window.addEventListener('pagehide', disconnect, { once: true });
let loginOpen = false;
async function start(user: AuthUser): Promise<void> {
  const map = await api.getWorldMap();
  mountHud({ username: user.username, role: user.role, avatar: map.avatar });
  loginOpen = false;
  if (!embedded) setBoot({ ...getBoot(), state: { percent: 100, label: 'visible', note: null, stages: ['visible'] } });
}
function loginGate(): void {
  if (loginOpen) return;
  loginOpen = true;
  setHudUiState({ overlayOpen: true });
  mountTitle({
    needsLogin: true,
    onLogin: async (username, password) => {
      await start(await api.login(username, password));
      setHudUiState({ overlayOpen: false });
    },
    onEnter: () => {},
  });
}
window.addEventListener('auth:required', loginGate);
async function boot(): Promise<void> {
  const auth = await api.authStatus();
  if (auth.authenticated && auth.user) await start(auth.user);
  else loginGate();
}
void boot().catch(error => {
  console.error('[hud] Start failed', error);
  setBoot({ ...getBoot(), state: { ...getBoot().state, note: { kind: 'failed' } } });
});
