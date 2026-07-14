import type { MapCharacter, MapEvent, WorldLocation } from './types';

export function showLogin(onLogin: (u: string, p: string) => Promise<void>): HTMLElement {
  const overlay = document.createElement('div');
  overlay.className = 'login-overlay';
  overlay.innerHTML = `
    <form class="login-card">
      <h1>Anima Verse</h1>
      <p class="subtitle">3D-Weltkarte — Prototyp</p>
      <label>Benutzer <input name="username" autocomplete="username" value="admin" /></label>
      <label>Passwort <input name="password" type="password" autocomplete="current-password" /></label>
      <div class="login-error" hidden></div>
      <button type="submit">Anmelden</button>
    </form>`;
  const form = overlay.querySelector('form')!;
  const err = overlay.querySelector('.login-error') as HTMLElement;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = new FormData(form);
    err.hidden = true;
    try {
      await onLogin(String(data.get('username')), String(data.get('password')));
      overlay.remove();
    } catch (ex) {
      err.textContent = ex instanceof Error ? ex.message : 'Login fehlgeschlagen';
      err.hidden = false;
    }
  });
  document.body.appendChild(overlay);
  return overlay;
}

export function createHud(opts: { username: string; avatar: string; onLogout: () => void }) {
  const bar = document.createElement('div');
  bar.className = 'hud-top';
  bar.innerHTML = `
    <div class="hud-title">⚜ Anima Verse — Weltkarte</div>
    <div class="hud-right">
      <span class="hud-status" title="Verbindung"></span>
      <span class="hud-user"></span>
      <button class="hud-logout">Abmelden</button>
    </div>`;
  const userEl = bar.querySelector('.hud-user') as HTMLElement;
  userEl.textContent = opts.avatar ? `${opts.username} · Avatar: ${opts.avatar}` : opts.username;
  (bar.querySelector('.hud-logout') as HTMLElement).addEventListener('click', opts.onLogout);
  document.body.appendChild(bar);

  const hints = document.createElement('div');
  hints.className = 'hud-hints';
  hints.textContent = '🖱 Links ziehen: verschieben · Rechts ziehen: drehen/neigen · Rad: zoomen (ganz nah = Figuren) · Q/E: 45°-Drehung · Klick: Ort öffnen';
  document.body.appendChild(hints);

  const statusEl = bar.querySelector('.hud-status') as HTMLElement;
  return {
    setOnline(ok: boolean) {
      statusEl.className = 'hud-status ' + (ok ? 'ok' : 'err');
      statusEl.title = ok ? 'Verbunden' : 'Backend nicht erreichbar';
    },
  };
}

export class InfoPanel {
  private el: HTMLElement;
  onZoomTo: ((locationId: string) => void) | null = null;

  constructor() {
    this.el = document.createElement('div');
    this.el.className = 'info-panel';
    this.el.hidden = true;
    document.body.appendChild(this.el);
  }

  show(loc: WorldLocation, chars: MapCharacter[], events: MapEvent[], roomOf: Map<string, string>) {
    const roomsHtml = loc.rooms.length
      ? `<h3>Räume</h3><ul>${loc.rooms.map((r) => {
          const inRoom = chars.filter((c) => roomOf.get(c.name) === r.name || roomOf.get(c.name) === r.id);
          return `<li>${esc(r.name)}${inRoom.length ? ` <span class="who">· ${inRoom.map((c) => esc(c.name)).join(', ')}</span>` : ''}</li>`;
        }).join('')}</ul>`
      : '';
    const charsHtml = chars.length
      ? `<h3>Anwesend</h3><ul>${chars.map((c) =>
          `<li>${esc(c.name)}${c.activity ? ` <span class="who">· ${esc(c.activity)}</span>` : ''}${c.mood ? ` <span class="who">· ${esc(c.mood)}</span>` : ''}${c.movement_target_name ? ` <span class="who">🚶 → ${esc(c.movement_target_name)}</span>` : ''}</li>`
        ).join('')}</ul>`
      : '';
    const eventsHtml = events.length
      ? `<h3>Ereignisse</h3><ul>${events.map((e) => `<li>${e.category === 'danger' ? '🔥' : '❗'} ${esc(e.text)}</li>`).join('')}</ul>`
      : '';
    this.el.innerHTML = `
      <button class="panel-close" title="Schließen">✕</button>
      <h2>${esc(loc.name)}</h2>
      ${loc.description ? `<p class="desc">${esc(loc.description)}</p>` : ''}
      ${roomsHtml}${charsHtml}${eventsHtml}
      <button class="panel-zoom">🔍 Reinzoomen</button>`;
    this.el.hidden = false;
    (this.el.querySelector('.panel-close') as HTMLElement).addEventListener('click', () => this.hide());
    (this.el.querySelector('.panel-zoom') as HTMLElement).addEventListener('click', () => {
      this.onZoomTo?.(loc.id);
    });
  }

  hide() {
    this.el.hidden = true;
  }
}

function esc(s: string): string {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
