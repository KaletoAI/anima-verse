/**
 * Start status line: keeps the page alive while we wait for the server (a
 * backend restart during boot). Without it there would only be an empty page
 * that never catches itself again.
 *
 * It survives the title screen (E4-T3) for ONE reason: the very first request
 * — `authStatus` — runs before React exists, because whether the title screen
 * has to ask for a login is exactly what that answer decides. Every later wait
 * is shown by the title screen itself.
 */
export function bootStatus() {
  const el = document.createElement('div');
  el.className = 'boot-status';
  el.style.cssText = 'position:fixed;inset:0;display:flex;align-items:center;'
    + 'justify-content:center;background:#0d1117;color:#c9d1d9;'
    + 'font:15px system-ui;text-align:center;padding:24px;z-index:50';
  return {
    set(text: string) {
      el.textContent = text;
      if (!el.isConnected) document.body.appendChild(el);
    },
    remove() {
      el.remove();
    },
  };
}
