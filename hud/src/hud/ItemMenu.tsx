import { useLayoutEffect, useRef } from 'react';
import { useI18n } from '@anima/player-ui';
import { gameActions, type HudGameState } from './bus';

/** Click menu for a world-placeable room item; mirrors PlaceMenu positioning and key ownership. */
export function ItemMenu({
  menu,
  onLook,
}: {
  menu: NonNullable<HudGameState['itemMenu']>;
  onLook?: (itemId: string) => void;
}) {
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
      gameActions.closeItemMenu?.();
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

  const { item } = menu;
  const title = item.quantity > 1 ? `${item.name} ×${item.quantity}` : item.name;

  return (
    <div
      className="ga-modal-backdrop place-menu-backdrop"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) gameActions.closeItemMenu?.();
      }}
    >
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-label={title}
        className="place-menu item-menu"
        style={{ left: menu.x, top: menu.y }}
      >
        <div className="place-menu-title">{title}</div>
        {item.actions.length ? (
          item.actions.map((action) => (
            <button
              type="button"
              key={action.id}
              className="place-menu-pose"
              onClick={() => {
                if (action.id === 'look') {
                  gameActions.closeItemMenu?.();
                  onLook?.(item.item_id);
                } else {
                  gameActions.pickItemAction?.(item.item_id, action.id);
                  gameActions.closeItemMenu?.();
                }
              }}
            >
              {action.label}
            </button>
          ))
        ) : (
          <div className="item-menu-empty" role="note">{t('Nothing to do here.')}</div>
        )}
      </div>
    </div>
  );
}
