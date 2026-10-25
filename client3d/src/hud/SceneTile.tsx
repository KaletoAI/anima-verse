import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { apiPost, Icon, useI18n, type SceneData } from '@anima/player-ui';
import { backgroundUrl, exprUrl, renderedSig, renderOutcome, sceneKey, tileFigures, tileHidden, type RenderAnswer } from './sceneTile';

export function SceneTile({ scene, collapsed, railEl }: { scene: SceneData | null; collapsed: boolean; railEl: HTMLElement | null }) {
  const { t } = useI18n();
  const [failedFor, setFailedFor] = useState('');
  const [pair, setPair] = useState<{ key: string; sig: string } | null>(null);
  const [showRendered, setShowRendered] = useState(true);
  const [big, setBig] = useState(false);
  const [rendering, setRendering] = useState(false);
  const inFlight = useRef(false);
  const [status, setStatus] = useState<{ key: string; text: string } | null>(null);
  const bg = scene ? backgroundUrl(scene) : '';
  const eligible = !!scene && !tileHidden(scene);
  const hidden = !eligible || bg === failedFor;
  useEffect(() => {
    if (!big || hidden) return;
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setBig(false); } };
    document.addEventListener('keydown', close, true);
    return () => document.removeEventListener('keydown', close, true);
  }, [big, hidden]);
  // Probe even in icon/rendered mode: a missing background hides every surface.
  useEffect(() => {
    if (!eligible) return;
    const image = new Image();
    image.onerror = () => setFailedFor(bg);
    image.src = bg;
    return () => { image.onerror = null; };
  }, [bg, eligible]);
  if (hidden || !scene) return null;
  const key = sceneKey(scene);
  const sig = renderedSig(pair, key);
  const activeSig = showRendered ? sig : null;
  const request = async (force: boolean) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setRendering(true);
    setStatus(null);
    try {
      const outcome = renderOutcome(await apiPost<RenderAnswer>('/play/scene-render', { force }));
      if (outcome.kind === 'show') {
        setPair({ key, sig: outcome.sig });
        setShowRendered(true);
      } else if (outcome.kind === 'cooldown') {
        setStatus({ key, text: t('Cooldown — ⟳ renders a fresh image') });
      } else if (outcome.kind === 'pending') {
        setStatus({ key, text: t('A scene render is already running') });
      }
    } catch (error) {
      setStatus({ key, text: error instanceof Error ? error.message : String(error) });
    } finally {
      inFlight.current = false;
      setRendering(false);
    }
  };
  const controls = <div className="hud-scene-controls">
    <button title={t('Show rendered scene')} aria-label={t('Show rendered scene')} disabled={rendering}
      aria-pressed={!!activeSig} onClick={() => { if (sig) setShowRendered(!showRendered); else void request(false); }}>🎨</button>
    <button title={t('Render a fresh scene image')} aria-label={t('Render a fresh scene image')} disabled={rendering}
      onClick={() => void request(true)}>⟳</button>
  </div>;
  const message = rendering ? t('Rendering scene…') : status?.key === key ? status.text : '';
  const content = <>
    <img className="hud-scene-background" src={bg} alt="" onError={() => setFailedFor(bg)} draggable={false} />
    {activeSig ? <img className="hud-scene-background" src={'/play/scene-render/image?sig=' + encodeURIComponent(activeSig)} alt="" draggable={false} />
      : <div className="hud-scene-figures">{tileFigures(scene).map(f => <div className="hud-scene-figure" key={f.name}
        title={f.isAvatar ? `${f.name} (${t('you')})` : f.name}>
        <span className={f.isAvatar ? 'hud-scene-avatar' : ''}>{f.name}</span>
        <img key={exprUrl(f.name, f.version)} src={exprUrl(f.name, f.version)} alt="" draggable={false}
          onError={e => { e.currentTarget.style.visibility = 'hidden'; }} />
      </div>)}</div>}
    <div className="hud-scene-strip">{scene.room_name || scene.location_name}
      {scene.room_name && scene.location_name !== scene.room_name ? ` · ${scene.location_name}` : ''}</div>
  </>;
  return <>
    {collapsed ? railEl && createPortal(<button className="hud-scene-icon" title={t('Scene')} onClick={() => setBig(true)}><Icon name="gallery" size={20} /></button>, railEl)
      : <div className="hud-scene-tile">
        <button className="hud-scene-image-area" aria-label={t('Scene')} onClick={() => setBig(true)}>{content}</button>
        {controls}{message && <div className="hud-scene-status" role="status">{message}</div>}
      </div>}
    {big && createPortal(<div className="ga-modal-backdrop hud-scene-big" onClick={() => setBig(false)}>
      <div className="hud-scene-large" role="dialog" aria-modal="true" aria-label={t('Scene')} onClick={e => e.stopPropagation()}>
        {content}{controls}
        <button className="hud-scene-close" title={t('Close')} aria-label={t('Close')} autoFocus onClick={() => setBig(false)}>×</button>
        {message && <div className="hud-scene-status" role="status">{message}</div>}
      </div>
    </div>, document.body)}
  </>;
}
