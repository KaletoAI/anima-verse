import type { MapCharacter, MapEvent, WorldLocation } from './types';

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
  hints.textContent = '🖱 Links ziehen: verschieben · Mitte oder Shift+Links ziehen: drehen/neigen · Rad: zoomen (ganz nah = Figuren) · Q/E: 45°-Drehung · Klick: Ort öffnen';
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
    // Flächen-/Gelände-Locations (Wald, See, Straße): ihre Räume sind Zonen
    // mit generischen Namen — die Liste ist dort Rauschen und bleibt weg,
    // wie die Raum-Labels in der Szene (User-Vorgabe 2026-08-02). Erkennung
    // wie beim Kachelbau: Flächen-Flag, passierbares Gelände oder Natur-Art.
    const area = !!loc.map3d?.area_model || !!loc.passable
      || ['water', 'forest', 'grass', 'road', 'sand', 'rock']
        .includes((loc.terrain || '').toLowerCase());
    const roomsHtml = !area && loc.rooms.length
      ? `<h3>Räume</h3><ul>${loc.rooms.map((r) => {
          const inRoom = chars.filter((c) => roomOf.get(c.name) === r.name || roomOf.get(c.name) === r.id);
          return `<li>${esc(r.name)}${inRoom.length ? ` <span class="who">· ${inRoom.map((c) => esc(c.name)).join(', ')}</span>` : ''}</li>`;
        }).join('')}</ul>`
      : '';
    const charsHtml = chars.length
      ? `<h3>Anwesend</h3><ul>${chars.map((c) =>
          `<li>${esc(c.name)}${c.activity ? ` <span class="who">· ${esc(c.activity)}</span>` : ''}${c.mood ? ` <span class="who">· ${esc(c.mood)}</span>` : ''}${c.movement_target_name ? ` <span class="who">🚶 → ${esc(c.movement_target_name)}${c.travel?.eta_game ? ' · ' + c.travel.eta_game.slice(11, 16) : ''}</span>` : ''}</li>`
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
