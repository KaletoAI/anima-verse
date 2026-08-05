/**
 * The in-game menu of the 3D client (plan-3d-game stage 4, task 4).
 *
 * It is the fourth rail panel, not a modal: the world keeps running behind it
 * — this is a living world, and a menu that stops it would be lying. So it
 * uses the same dock, chrome and pointer rules as Self/Others and can stay
 * open while one walks around.
 *
 * WHAT IS IN HERE AND WHAT IS NOT. Everything on this screen is a LOCAL
 * setting of this browser (`game/prefs.ts`): how loud this machine is, and
 * whether it speaks. World settings — the travel pace above all — are not
 * here on purpose; they belong to the world and are changed by an
 * administrator in the admin settings. The hint line under "Session" says so
 * instead of quietly leaving the player to search.
 *
 * PRESENTATIONAL ONLY: it owns no state. `Hud.tsx` holds the prefs, applies
 * the volumes to the audio engine and writes `localStorage` — see `setPrefs`
 * there for the contract between the sliders (live) and the switches (stored
 * for the drivers of tasks 5/6).
 */
import { useI18n } from '@anima/player-ui';
import type { Prefs, TtsMode } from '../game/prefs';

/** The prefs fields that are a volume — the sliders below are one per entry,
 *  in this order (master first, it multiplies onto the other three). */
type VolumeField = 'master' | 'music' | 'ambient' | 'tts';

export interface GameMenuProps {
  prefs: Prefs;
  /** merge, store and (for volumes) apply — `Hud.tsx` owns all three steps */
  onChange: (patch: Partial<Prefs>) => void;
  /** the performance readout is shown (Etappe 5). NOT part of `Prefs`: that
   *  object and its storage key are the AUDIO settings, this is a view one. */
  perfOn: boolean;
  onPerfChange: (on: boolean) => void;
  /** the signed-in account may see the unfiltered map (Etappe 5) — the entry
   *  below exists only for one, and the server refuses the view for anybody
   *  else anyway */
  isAdmin: boolean;
  /** the fog of war is currently switched off for this browser */
  showAll: boolean;
  /** store the switch and apply it — `Hud.tsx` reloads the view */
  onShowAllChange: (on: boolean) => void;
  /** sign out and go back to the title screen (main.ts owns the flow) */
  onBackToTitle: () => void;
}

/** One volume, as a percentage. The stored value is 0..1; percent is what a
 *  player can read and compare, so the slider works in whole percent and the
 *  number next to it is the same value, not a second rounding. */
function Slider({ label, value, onPick }: {
  label: string; value: number; onPick: (v: number) => void;
}) {
  const percent = Math.round(value * 100);
  return (
    <label className="hud-menu-slider">
      <span className="hud-menu-label">{label}</span>
      <span className="hud-menu-value">{percent}%</span>
      <input type="range" min={0} max={100} step={1} value={percent}
        onChange={(e) => onPick(Number(e.target.value) / 100)} />
    </label>
  );
}

/** A switch with two or three positions. Buttons rather than a `<select>`:
 *  every option is visible at once, and the whole menu stays operable with one
 *  click per decision. */
function Choice<T extends string | boolean>({ label, value, options, onPick }: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onPick: (v: T) => void;
}) {
  return (
    <div className="hud-menu-row">
      <span className="hud-menu-label">{label}</span>
      <div className="hud-menu-seg" role="group" aria-label={label}>
        {options.map((o) => (
          <button key={String(o.value)} type="button" aria-pressed={o.value === value}
            className={o.value === value ? 'on' : ''}
            onClick={() => onPick(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function GameMenu({ prefs, onChange, perfOn, onPerfChange,
                           isAdmin, showAll, onShowAllChange,
                           onBackToTitle }: GameMenuProps) {
  const { t } = useI18n();

  const volumes: Array<{ field: VolumeField; label: string }> = [
    { field: 'master', label: t('Master') },
    { field: 'music', label: t('Music') },
    { field: 'ambient', label: t('Ambience') },
    { field: 'tts', label: t('Voices') },
  ];
  const onOff: ReadonlyArray<{ value: boolean; label: string }> = [
    { value: true, label: t('On') },
    { value: false, label: t('Off') },
  ];
  const ttsModes: Array<{ value: TtsMode; label: string }> = [
    { value: 'auto', label: t('Auto') },
    { value: 'on', label: t('On') },
    { value: 'off', label: t('Off') },
  ];

  return (
    <>
      <section className="hud-menu-section">
        <h3 className="hud-menu-head">{t('Audio')}</h3>
        {volumes.map((v) => (
          <Slider key={v.field} label={v.label} value={prefs[v.field]}
            onPick={(n) => onChange({ [v.field]: n } as Partial<Prefs>)} />
        ))}
        <Choice label={t('Music')} value={prefs.musicOn} options={onOff}
          onPick={(v) => onChange({ musicOn: v })} />
        <Choice label={t('Ambience')} value={prefs.ambientOn} options={onOff}
          onPick={(v) => onChange({ ambientOn: v })} />
        <Choice label={t('Voices')} value={prefs.ttsOn} options={ttsModes}
          onPick={(v) => onChange({ ttsOn: v })} />
        <p className="hud-menu-hint">
          {t('Voices follow the server in auto mode. These settings are kept in this browser only.')}
        </p>
      </section>

      <section className="hud-menu-section">
        <h3 className="hud-menu-head">{t('Display')}</h3>
        <Choice label={t('Performance readout')} value={perfOn} options={onOff}
          onPick={onPerfChange} />
        <p className="hud-menu-hint">
          {t('Frame rate, draw calls and how many models stand on the full or the low resolution.')}
        </p>
      </section>

      {/* The one entry that is not a player setting: it lifts the fog of war
          for an administrator, which is a different VIEW of the world and not
          a matter of taste. Hence its own section, and hence the note about
          the reload — the whole map is built from that view at start-up. */}
      {isAdmin && (
        <section className="hud-menu-section">
          <h3 className="hud-menu-head">{t('Administration')}</h3>
          <Choice label={t('Show all locations (admin)')} value={showAll} options={onOff}
            onPick={onShowAllChange} />
          <p className="hud-menu-hint">
            {t('Shows the whole map, including places your character has not discovered yet. Reloads the view.')}
          </p>
        </section>
      )}

      <section className="hud-menu-section">
        <h3 className="hud-menu-head">{t('Session')}</h3>
        <p className="hud-menu-hint">
          {t('The travel pace belongs to the world — an administrator sets it in the admin settings.')}
        </p>
        <button type="button" className="hud-menu-btn" onClick={onBackToTitle}>
          {t('Back to title')}
        </button>
      </section>
    </>
  );
}
