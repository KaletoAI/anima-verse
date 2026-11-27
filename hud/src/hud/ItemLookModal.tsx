import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { apiGet, thumbUrl, thumbWidth, useEnlarge, useI18n, useToast } from '@anima/player-ui';
import { uiActions } from './bus';

const PREVIEW_W = thumbWidth(384);

interface RoomItemDetail {
  item_id: string;
  name: string;
  description: string;
  image_url: string | null;
  quantity: number;
}

/** Portaled HUD modal showing an item lying visibly in the avatar's room. */
export function ItemLookModal({
  itemId,
  onClose,
}: {
  itemId: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [item, setItem] = useState<RoomItemDetail | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const lightboxClose = useRef<(() => void) | null>(null);
  const enlarge = useEnlarge((dispose) => {
    lightboxClose.current?.();
    lightboxClose.current = dispose;
  });
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const toastRef = useRef(toast);
  toastRef.current = toast;

  useEffect(() => {
    let alive = true;
    setItem(null);
    apiGet<RoomItemDetail>(`/play/room-item/${encodeURIComponent(itemId)}`)
      .then((data) => {
        if (alive) setItem(data);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        const msg = err instanceof Error ? err.message : String(err);
        if (uiActions.toast) uiActions.toast(msg);
        else toastRef.current(msg, 'error');
        closeRef.current();
      });
    return () => {
      alive = false;
    };
  }, [itemId]);

  useEffect(() => {
    const previous = document.activeElement;
    dialogRef.current?.focus({ preventScroll: true });
    return () => {
      lightboxClose.current?.();
      lightboxClose.current = null;
      if (previous instanceof HTMLElement && previous.isConnected) {
        previous.focus({ preventScroll: true });
      }
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('.lb-overlay')) return;
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      closeRef.current();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, []);

  return createPortal(
    <div
      className="ga-modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="ga-modal item-look-modal"
        role="dialog"
        aria-modal="true"
        aria-label={item ? item.name : t('Loading…')}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{item ? item.name : t('Loading…')}</span>
          <button
            type="button"
            className="ga-modal-close"
            title={t('Close')}
            aria-label={t('Close')}
            onClick={onClose}
          >
            {'×'}
          </button>
        </div>
        <div className="ga-modal-body item-look-body" aria-busy={!item}>
          {!item ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : (
            <>
              {item.image_url && (
                <img
                  className="item-look-image"
                  src={thumbUrl(item.image_url, PREVIEW_W)}
                  alt={item.name}
                  {...enlarge({ src: item.image_url, alt: item.name })}
                />
              )}
              {item.quantity > 1 && (
                <div className="item-look-qty">
                  {t('Quantity: {n}').replace('{n}', String(item.quantity))}
                </div>
              )}
              {item.description && (
                <div className="item-look-desc">{item.description}</div>
              )}
              <div className="item-look-actions">
                <button type="button" className="ga-btn" onClick={onClose}>
                  {t('Close')}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
