/**
 * The SEAT MENU (plan-posen-plaetze.md § 4, Task 13): a small DOM context
 * menu at the mouse point that lists the poses a clicked place allows —
 * the group's default first and bold — and hands the picked pose key back.
 * One menu at a time; it closes on a pick, on a click outside, on Escape.
 * Nothing is decided here: the poses come from `GET /play/places`, the
 * pick goes to `POST /play/self/activity` by the caller.
 */
import type { PlaceOffer } from '../api';

let current: { el: HTMLElement; teardown: () => void } | null = null;

export function closePlaceMenu(): void {
  if (!current) return;
  current.teardown();
  current.el.remove();
  current = null;
}

/** Open the menu for `offer` at client point (x, y); `onPick` gets the pose
 *  key of the button clicked. Kept inside the viewport. */
export function openPlaceMenu(x: number, y: number, offer: PlaceOffer,
                              onPick: (pose: string) => void): void {
  closePlaceMenu();
  const el = document.createElement('div');
  el.className = 'place-menu';
  const title = document.createElement('div');
  title.className = 'place-menu-title';
  title.textContent = offer.label;
  el.appendChild(title);
  offer.poses.forEach((pose, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = i === 0 ? 'place-menu-pose default' : 'place-menu-pose';
    b.textContent = pose.label;
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      closePlaceMenu();
      onPick(pose.key);
    });
    el.appendChild(b);
  });
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  document.body.appendChild(el);
  // Pushed back into the viewport once it has a size.
  const r = el.getBoundingClientRect();
  if (r.right > window.innerWidth) el.style.left = `${Math.max(0, window.innerWidth - r.width - 4)}px`;
  if (r.bottom > window.innerHeight) el.style.top = `${Math.max(0, window.innerHeight - r.height - 4)}px`;
  // Capture phase: the canvas's own pointerdown (a drag, a new click) and the
  // engine's Escape handling see the event AFTER the menu has closed — and
  // an Escape that closed the menu is spent, it must not also leave the mode.
  const onDown = (e: PointerEvent) => {
    if (!el.contains(e.target as Node)) closePlaceMenu();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    closePlaceMenu();
  };
  window.addEventListener('pointerdown', onDown, true);
  window.addEventListener('keydown', onKey, true);
  current = {
    el,
    teardown: () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
    },
  };
}
