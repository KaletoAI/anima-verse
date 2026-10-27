import { useLayoutEffect, useRef } from 'react';
import { gameActions, type HudGameState } from './bus';
import { PropActionOffers, useI18n } from '@anima/player-ui';

/** Exact semantic offers or legitimate room-marker poses; no furniture pose bridge. */
export function PlaceMenu({ menu }: { menu: NonNullable<HudGameState['placeMenu']> }) {
  const { t } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const fit = () => {
      const el = ref.current;
      if (!el) return;
      el.style.left = `${menu.x}px`;
      el.style.top = `${menu.y}px`;
      const r = el.getBoundingClientRect();
      if (r.right > window.innerWidth) el.style.left = `${Math.max(0, window.innerWidth - r.width - 4)}px`;
      if (r.bottom > window.innerHeight) el.style.top = `${Math.max(0, window.innerHeight - r.height - 4)}px`;
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopImmediatePropagation();
      event.preventDefault();
      gameActions.closePlaceMenu?.();
    };
    fit();
    // A menu opened by the parent canvas must receive keys in the HUD realm.
    ref.current?.focus({ preventScroll: true });
    window.addEventListener('resize', fit);
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('resize', fit);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [menu]);
  return <div className="ga-modal-backdrop place-menu-backdrop" onPointerDown={e => {
    if (e.target === e.currentTarget) gameActions.closePlaceMenu?.();
  }}>
    <div ref={ref} tabIndex={-1} role="dialog" aria-label={menu.offer.label} className="place-menu" style={{ left: menu.x, top: menu.y }}>
      <div className="place-menu-title">{menu.offer.label}</div>
      {menu.offer.prop_actions !== undefined
        ? menu.offer.prop_actions.length
          ? <PropActionOffers offers={menu.offer.prop_actions} onPick={(offer, partner) => {
            void gameActions.pickPropAction?.(offer.action_id, offer.target, offer.definition_revision, partner);
          }} />
          : <div role="note">{t('No furniture actions available.')}</div>
        : menu.offer.poses.map((pose, i) => <button type="button" key={pose.key}
          className={`place-menu-pose${i === 0 ? ' default' : ''}`}
          onClick={() => { void gameActions.pickRoomPose?.(menu.offer.id, pose.key); }}>{pose.label}</button>)}
    </div>
  </div>;
}
