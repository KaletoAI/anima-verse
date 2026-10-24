import { useRef, useState } from 'react';
import { pollCore, useI18n, useToast, type SceneData } from '@anima/player-ui';
import { travelTo, cancelTravel } from '../api';
import type { TravelPick } from '../game/travelPick';

/** Picks are HUD-local; only a confirmed action asks the server to move. */
export function TravelBar({ pick, clear, travel, locked, leader }: {
  pick: TravelPick | null; clear: () => void; travel: SceneData['travel'];
  locked: boolean; leader: string;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  async function act(cancel: boolean) {
    if (pending.current || (!cancel && (!pick || locked))) return;
    pending.current = true;
    setBusy(true);
    try {
      if (cancel) await cancelTravel();
      else { await travelTo(pick!.id); clear(); }
      void pollCore().refresh('play-scene');
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), 'error');
    } finally { pending.current = false; setBusy(false); }
  }
  // A party follower gets the "following" line only once there is something
  // to say it about (a pick or a journey) — a permanent bar for every follower
  // would cover the bottom stack for the whole party trip.
  if (!travel && !pick) return null;
  return <div className="hud-travel" role="status">
    {travel ? <>
      <span>{t('On the road to')} {travel.target_name}</span>
      <span title={travel.eta_label}>{travel.eta_hhmm}</span>
      <span>{Math.max(0, Math.round(travel.total_m - travel.progress_m))} m {t('to go')}</span>
      {!locked && <button disabled={busy} onClick={() => void act(true)}>{t('Cancel journey')}</button>}
    </> : pick && <>
      <span>{pick.name}{pick.distanceM !== null && ` · ${Math.round(pick.distanceM)} m`}</span>
      {!locked && <button disabled={busy} onClick={() => void act(false)}>{t('Travel')}</button>}
      <button title={t('Close')} onClick={clear}>✕</button>
    </>}
    {locked && <span>{leader ? `${t('You are following the party of')} ${leader}.` : t('You are part of a party.')}</span>}
  </div>;
}
