/** Standalone HUD: API requests share the host origin and cookie session. */
import * as api from './api';
import { connectHudSide, gdcefTransport, postMessageTransport } from './hud/bridge';
import { getBoot, setBoot, setHudUiState } from './hud/bus';
import { mountHud, mountTitle } from './hud/mount';
import { gdcefStorageSender, mirrorStorage } from './hud/storageMirror';
import type { AuthUser } from './types';

const embedded = window.parent !== window;
// `?bridge=gdcef`: the native client's Chromium is the host (gdCEF JS binding);
// otherwise the embedding page, over postMessage.
const gdcef = new URLSearchParams(location.search).get('bridge') === 'gdcef';
const transport = gdcef ? gdcefTransport() : postMessageTransport(window.parent, location.origin);
// The native browser keeps no storage between starts: Godot does, from this
// mirror (installed before anything mounts, so no write is missed).
if (gdcef) mirrorStorage(localStorage, gdcefStorageSender());
const disconnect = connectHudSide(transport);
window.addEventListener('pagehide', disconnect, { once: true });
let loginOpen = false;
async function start(user: AuthUser): Promise<void> {
  const map = await api.getWorldMap();
  mountHud({ username: user.username, role: user.role, avatar: map.avatar });
  loginOpen = false;
  // A standalone page has no scene to report a start: it declares itself visible.
  // Embedded (iframe) or native (gdCEF), the scene's six boot stages are the only
  // source — a local 100 % would override them until the scene's next message.
  if (!embedded && !gdcef) setBoot({ ...getBoot(), state: { percent: 100, label: 'visible', note: null, stages: ['visible'] } });
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
  // gdCEF: the scene owns the boot state (and its own failed note); the page only logs.
  if (!gdcef) setBoot({ ...getBoot(), state: { ...getBoot().state, note: { kind: 'failed' } } });
});
