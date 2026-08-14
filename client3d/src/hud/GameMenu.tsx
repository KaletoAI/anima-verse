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
 * PRESENTATIONAL: it owns no SETTING. `Hud.tsx` holds the prefs, applies the
 * volumes to the audio engine and writes `localStorage` — see `setPrefs` there
 * for the contract between the sliders (live) and the switches (stored for the
 * drivers of tasks 5/6). The one `useState` in here holds the TEXT of the
 * three distance fields while they are being typed, which is a keyboard and
 * not a setting; nothing leaves this file until it is a valid triple.
 */
import { useState } from 'react';
import { useI18n } from '@anima/player-ui';
import { checkScatterPrefs, DEFAULT_SCATTER_PREFS, SCATTER_PREF_MAX_M,
  SCATTER_PREF_MIN_M } from '../game/prefs';
import type { Prefs, ScatterPrefs, TtsMode } from '../game/prefs';

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
  /** the minimap is shown in the embodied mode (Etappe 5). A view setting like
   *  `perfOn`, with its own storage key — see `Hud.tsx`. */
  minimapOn: boolean;
  onMinimapChange: (on: boolean) => void;
  /** the three scatter detail distances of this browser (per-object scatter
   *  LOD). A view setting with its own storage key, like the two above — see
   *  `Hud.tsx`, which owns the store and the action into the running world. */
  scatterPrefs: ScatterPrefs;
  /** take an ORDERED triple: the fields below only report what passed
   *  `checkScatterPrefs`, and a refused one stays in the field with a hint
   *  under it instead of reaching the world. */
  onScatterChange: (prefs: ScatterPrefs) => void;
  /** the signed-in account may see the unfiltered map (Etappe 5) — the entry
   *  below exists only for one, and the server refuses the view for anybody
   *  else anyway */
  isAdmin: boolean;
  /** the fog of war is currently switched off for this browser */
  showAll: boolean;
  /** store the switch and apply it — `Hud.tsx` hands it to main.ts, which
   *  switches the view in the running world */
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

/** One distance of the scatter LOD, in metres. A number input rather than a
 *  slider: three distances that have to CLIMB are typed and compared, not
 *  dragged, and the browser's own stepper is the whole control this needs. */
function Metres({ label, value, onType }: {
  label: string; value: string; onType: (v: string) => void;
}) {
  return (
    <label className="hud-menu-row">
      <span className="hud-menu-label">{label}</span>
      <input className="hud-menu-num" type="number" inputMode="numeric"
        min={SCATTER_PREF_MIN_M} max={SCATTER_PREF_MAX_M} step={5}
        value={value} onChange={(e) => onType(e.target.value)} />
    </label>
  );
}

export function GameMenu({ prefs, onChange, perfOn, onPerfChange,
                           minimapOn, onMinimapChange,
                           scatterPrefs, onScatterChange,
                           isAdmin, showAll, onShowAllChange,
                           onBackToTitle }: GameMenuProps) {
  const { t } = useI18n();

  /**
   * THE ONE PIECE OF STATE IN THIS FILE, and it is not a setting: the three
   * distance fields hold TEXT while they are being typed. A field one has
   * cleared to type a new number is empty, not 0, and the intermediate "4" of
   * a "45" is not a distance either — so what is stored is what the player
   * has typed, and only a triple that passes `checkScatterPrefs` is handed up.
   * The stored settings still live in `Hud.tsx` like every other one here.
   */
  const [draft, setDraft] = useState(() => ({
    near: String(scatterPrefs.scatterNearM),
    far: String(scatterPrefs.scatterFarM),
    cull: String(scatterPrefs.scatterCullM),
  }));
  /** why the last typing was NOT taken (`''` = it was) — the hint under the
   *  fields, and the reason a refused triple leaves the world alone */
  const [scatterError, setScatterError] = useState<'' | 'number' | 'order'>('');
  /** An empty field is NOT a zero: `Number('')` is 0, which would sail through
   *  the check as a legal (if clamped) distance and re-draw the world while
   *  somebody is still typing. NaN is what "no number here" means. */
  const metres = (raw: string): number => (raw.trim() === '' ? NaN : Number(raw));
  const typeDistance = (patch: Partial<typeof draft>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    const checked = checkScatterPrefs(metres(next.near), metres(next.far),
                                      metres(next.cull));
    setScatterError(checked.ok ? '' : checked.error);
    // Applied AS TYPED, without an OK button — the world behind the menu is
    // the preview, and a distance one cannot see the effect of is a distance
    // nobody can set sensibly.
    if (checked.ok) onScatterChange(checked.prefs);
  };
  const resetDistances = () => {
    setDraft({
      near: String(DEFAULT_SCATTER_PREFS.scatterNearM),
      far: String(DEFAULT_SCATTER_PREFS.scatterFarM),
      cull: String(DEFAULT_SCATTER_PREFS.scatterCullM),
    });
    setScatterError('');
    onScatterChange({ ...DEFAULT_SCATTER_PREFS });
  };

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
        <Choice label={t('Minimap')} value={minimapOn} options={onOff}
          onPick={onMinimapChange} />
        <p className="hud-menu-hint">
          {t('The whole world in the top right corner, north up, with your position and heading. Only while you are in the world.')}
        </p>
        <Choice label={t('Performance readout')} value={perfOn} options={onOff}
          onPick={onPerfChange} />
        <p className="hud-menu-hint">
          {t('Frame rate, draw calls and how many models stand on the full or the low resolution.')}
        </p>
      </section>

      {/* The scatter detail distances. Kept apart from "Display" because these
          three are not a switch but a budget: they say how much of the ground
          cover this machine draws, and they are the first thing to turn down
          on a weak one. */}
      <section className="hud-menu-section">
        <h3 className="hud-menu-head">{t('Detail distances')}</h3>
        <Metres label={t('Full detail up to (m)')} value={draft.near}
          onType={(v) => typeDistance({ near: v })} />
        <Metres label={t('Low detail up to (m)')} value={draft.far}
          onType={(v) => typeDistance({ far: v })} />
        <Metres label={t('Not drawn beyond (m)')} value={draft.cull}
          onType={(v) => typeDistance({ cull: v })} />
        {scatterError === 'number' && (
          <p className="hud-menu-warn">
            {t('Each of the three fields needs a number of metres.')}
          </p>
        )}
        {scatterError === 'order' && (
          <p className="hud-menu-warn">
            {t('The three distances have to climb: full detail, then low detail, then hidden.')}
          </p>
        )}
        <p className="hud-menu-hint">
          {t('How far away trees, bushes and grass drop to the cheap model and where they stop being drawn. Lower distances buy frame rate.')}
        </p>
        <button type="button" className="hud-menu-btn" onClick={resetDistances}>
          {t('Reset detail distances')}
        </button>
      </section>

      {/* The one entry that is not a player setting: it lifts the fog of war
          for an administrator, which is a different VIEW of the world and not
          a matter of taste. Hence its own section. It takes effect at once —
          main.ts adds and removes the places of the other view in the running
          world, so there is nothing to warn about. */}
      {isAdmin && (
        <section className="hud-menu-section">
          <h3 className="hud-menu-head">{t('Administration')}</h3>
          <Choice label={t('Show all locations (admin)')} value={showAll} options={onOff}
            onPick={onShowAllChange} />
          <p className="hud-menu-hint">
            {t('Shows the whole map, including places your character has not discovered yet. Takes effect at once.')}
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
