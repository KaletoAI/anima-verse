/** Standalone HUD: API requests share the host origin and cookie session. */
import * as api from './api';
import { connectHudSide, gdcefTransport, postMessageTransport } from './hud/bridge';
import { getBoot, setBoot, setHudUiState } from './hud/bus';
import { mountHud, mountTitle } from './hud/mount';
import type { AuthUser } from './types';

const embedded = window.parent !== window;
// `?bridge=gdcef`: the native client's Chromium is the host (gdCEF JS binding);
// otherwise the embedding page, over postMessage.
const transport = new URLSearchParams(location.search).get('bridge') === 'gdcef'
  ? gdcefTransport()
  : postMessageTransport(window.parent, location.origin);
const disconnect = connectHudSide(transport);
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
