/**
 * Title, login and loading screen of the 3D client (plan-3d-game stage 4,
 * task 3). It REPLACES the vanilla login overlay that used to live in `ui.ts`,
 * which was deleted with no shim — there is no second login path.
 *
 * It is one screen with three faces, because they are one moment for the
 * player: the world is named, they identify themselves (or just walk in), and
 * then they watch the world being built. Splitting that into an overlay plus a
 * separate loading indicator is what produced the old black gap between "login
 * accepted" and "the map appears".
 *
 *   gate     login form (`needsLogin`) or the "Enter world" button
 *   loading  the four boot stages of `game/boot.ts` as a bar plus a line
 *   leaving  faded out, then unmounted by `onDone`
 *
 * THE BUTTON IS THE AUTOPLAY GESTURE. A browser only lets an `AudioContext`
 * start from a real click, so `main.ts` unlocks the audio engine in `onLogin`
 * AND in `onEnter` — the second one is the case that used to be missed
 * entirely: a valid session went straight into the game with no click at all,
 * and the context stayed suspended for the whole session.
 *
 * THE SCREEN STAYS UP DURING `startApp`. The engine builds its canvas
 * underneath while this is on top, so the player never sees a half-built
 * world; the fade only starts once the last stage is reported. With
 * `prefers-reduced-motion` there is no fade — the screen is simply gone.
 *
 * Look: `hud.css` carries the structure, `theme-fantasy.css` the fantasy look,
 * same split as the rest of the HUD. Everything is anchored under `#hud-title`
 * so nothing can leak into `/play`.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore,
  type FormEvent } from 'react';
import { useI18n } from '@anima/player-ui';
import { getBootState, subscribeBoot, type BootState } from '../game/boot';
// The screen is up before the HUD is, so it brings its own styles: structure
// then look, the same order Hud.tsx uses (both are already in the graph when
// mount.tsx pulls Hud first, so nothing is loaded twice).
import './hud.css';
import './theme-fantasy.css';

/** How long the fade-out runs. Must match the transition in hud.css — the
 *  unmount is scheduled off this number, and a timer shorter than the
 *  transition would cut the fade off mid-way. */
const FADE_MS = 900;

export interface TitleScreenProps {
  /** no valid session — show the login form instead of the "Enter world" button */
  needsLogin: boolean;
  /** sign in and start the app; a rejection puts the form back with an error */
  onLogin: (username: string, password: string) => Promise<void>;
  /** the player wants in: start the app (and unlock the audio) */
  onEnter: () => void;
  /** the fade is over — the host may unmount and drop the node */
  onDone: () => void;
}

/**
 * The world has no name the client could ask for: neither `/auth/status` nor
 * the worldmap payload carries one (the world is chosen by the server's
 * `--world` flag and never leaves it), so the product name stands here. If a
 * world name is ever exposed, this is the one place it goes.
 */
const GAME_TITLE = 'Anima Verse';

/** Reduced motion is a system setting, read once — it does not change mid-boot,
 *  and reading it at render time would make the fade depend on when React
 *  happens to re-render. */
function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

export function TitleScreen({ needsLogin, onLogin, onEnter, onDone }: TitleScreenProps) {
  const { t } = useI18n();
  const boot = useSyncExternalStore<BootState>(subscribeBoot, getBootState);
  const [entered, setEntered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [leaving, setLeaving] = useState(false);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  /** `onDone` in a ref: the fade timer is started once and must not be
   *  restarted because the host handed down a fresh closure. */
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  /** The trouble line, in words — `game/boot.ts` carries it as a value
   *  because the vanilla side that sets it has no `t()`. */
  const noteText = (note: NonNullable<BootState['note']>): string => {
    if (note.kind === 'failed') return t('Start failed — please reload the page.');
    return t('The server is not answering — trying again in {n} s…')
      .replace('{n}', String(note.seconds));
  };

  /** What the client is doing right now, in words. The pure module returns a
   *  stage NAME so it stays language-free; the sentence belongs here. */
  const stageText = (label: BootState['label']): string => {
    switch (label) {
      case 'world': return t('Consulting the map…');
      case 'figures': return t('Waking the inhabitants…');
      case 'scenes': return t('Raising the buildings…');
      case 'tiles': return t('Laying out the land…');
      default: return t('Ready');
    }
  };

  // The world is built: fade, then hand back. Guarded on `entered`, because
  // the stages are only ever reported after the player is through the gate.
  //
  // `leaving` is deliberately NOT a dependency, and it is not a guard either.
  // As a dependency it would kill the very timer this effect just started: the
  // `setLeaving` below re-renders with a changed dep, React runs the cleanup,
  // the timeout is cleared and the screen never unmounts. As a guard (with a
  // ref) it would break the other way round under a remount, where the
  // cleanup has already run and no timer is left to replace. So the effect
  // depends only on the three facts that decide it — `setLeaving(true)` on an
  // already-true state is a no-op React bails out of.
  //
  // A FAILED START HOLDS THE SCREEN. `startApp` can throw after the last stage
  // was reported (a late load, a bad payload): the bar then stands at 100 %,
  // this effect would fade the screen out and take the one sentence that
  // explains the black world with it. While the trouble line says "failed",
  // the screen stays.
  useEffect(() => {
    if (!entered || boot.percent < 100) return;
    if (boot.note?.kind === 'failed') {
      // The failure may arrive AFTER the fade was started (the throw comes out
      // of a `.catch` on `startApp`, the last stage was reported before it) —
      // then the cleanup of the previous run has just cancelled the unmount,
      // and this brings the half-faded screen back to full.
      setLeaving(false);
      return;
    }
    setLeaving(true);
    const fade = prefersReducedMotion() ? 0 : FADE_MS;
    const timer = window.setTimeout(() => doneRef.current(), fade);
    return () => window.clearTimeout(timer);
  }, [entered, boot.percent, boot.note?.kind]);

  const enter = useCallback(() => {
    setEntered(true);
    onEnter();
  }, [onEnter]);

  const submit = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await onLogin(username, password);
      setEntered(true);
    } catch (ex) {
      // One message for every way this fails, and a translated one. The API
      // has exactly one login error to give ("not accepted"), and a raw
      // exception text — a network error, a proxy's HTML — is neither
      // translatable nor readable; it goes to the console instead.
      console.warn('[title] sign-in failed', ex);
      setError(t('Sign-in failed — check name and passphrase.'));
      setBusy(false);
    }
  }, [busy, onLogin, username, password, t]);

  return (
    <div className={`title-screen${leaving ? ' leaving' : ''}`}>
      <div className="title-plate">
        <h1 className="title-name">{GAME_TITLE}</h1>
        <p className="title-sub">{t('A world that lives on without you')}</p>

        {!entered && needsLogin && (
          <form className="title-form" onSubmit={submit}>
            <label className="title-field">
              <span>{t('Name')}</span>
              <input name="username" autoComplete="username" autoFocus
                     value={username} onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label className="title-field">
              <span>{t('Passphrase')}</span>
              <input name="password" type="password" autoComplete="current-password"
                     value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            {error && <div className="title-error" role="alert">{error}</div>}
            <button className="title-btn" type="submit" disabled={busy}>
              {busy ? t('Opening the gate…') : t('Enter world')}
            </button>
          </form>
        )}

        {!entered && !needsLogin && (
          <button className="title-btn title-btn-solo" type="button" onClick={enter}>
            {t('Enter world')}
          </button>
        )}

        {entered && (
          <div className="title-boot">
            <div className="title-bar" role="progressbar" aria-valuemin={0}
                 aria-valuemax={100} aria-valuenow={boot.percent}
                 aria-label={t('Loading the world')}>
              <div className="title-bar-fill" style={{ width: `${boot.percent}%` }} />
            </div>
            <div className="title-stage">{stageText(boot.label)}</div>
          </div>
        )}

        {boot.note && <div className="title-note" role="status">{noteText(boot.note)}</div>}
      </div>
    </div>
  );
}
