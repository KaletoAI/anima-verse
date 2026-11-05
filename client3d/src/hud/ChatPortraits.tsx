/**
 * The picture column of the HUD chat window (plan-hud-chat-portraits.md, 2b).
 *
 * Purely presentational: WHICH faces it shows and in what order is decided by
 * `pickPortraitSpeakers` in `chatPanel.ts`, and how many boxes that becomes by
 * `portraitSlots` right next to it — this file only draws them.
 *
 * The images are the same expression renders /play's Others panel uses
 * (`/characters/<name>/outfit-expression`), with the cache-buster taken from
 * the scene payload's `speaker_expr_versions`: the server fills that for every
 * drawable speaker of the returned history, including someone who has since
 * left the room, so a portrait is never up to an hour stale (the expression
 * route answers `max-age=3600`).
 *
 * Height-filling scaling is SelfPanel's pattern, and it has to be: these files
 * carry no fixed aspect ratio at all (223x512 up to 822x1216, cut-out RGBA
 * PNGs). Container `flex/min-*: 0` + `overflow: hidden` + centred grid, image
 * `max-height/max-width: 100%` + `object-fit: contain` — so a portrait fills
 * whatever box it is given without ever pushing the column open.
 *
 * NOTHING HERE EVER DRAWS EMPTY. A slot without a name and a render that fails
 * to load both fall back to the SILHOUETTE below. The column therefore keeps
 * its width whatever the transcript does, and the chat beside it never jumps
 * wider.
 *
 * Two DIFFERENT boxes end up nameless, and they are told apart by the slot's
 * `narrator` flag alone — never by a name, which on those rows is a localized
 * label: the narrator's own place (it has no portrait and never will, so it is
 * titled as the narrator) and the placeholder for "nothing drawable has been
 * said yet" (titled "No portrait").
 *
 * A DISGUISED speaker the avatar is not in on (`portrait_urls` of the scene
 * payload) shows the persona portrait instead of the render, and the
 * silhouette when the persona has none — never the real face. Names are keys
 * here; the alt text prints the avatar's view (`display_names`).
 */
import { useState } from 'react';
import { portraitOverride, shownName, useI18n } from '@anima/player-ui';

import { portraitSlots } from './chatPanel';

/**
 * The stand-in for a face: head and shoulders, no features, filled with the
 * text colour at low opacity so it reads as "no picture here" rather than as a
 * broken one — and so it works in a light theme as well as a dark one. Inline
 * on purpose: a column that exists to stop layout jumping must not wait for a
 * network round trip to have something to draw.
 */
function Silhouette({ title }: { title: string }) {
  return (
    <svg className="hud-chat-portrait-blank" viewBox="0 0 64 96"
      role="img" aria-label={title}
      preserveAspectRatio="xMidYMax meet" focusable="false">
      <title>{title}</title>
      <circle cx="32" cy="30" r="15" fill="currentColor" />
      <path d="M4 96c0-17 12.5-28 28-28s28 11 28 28z" fill="currentColor" />
    </svg>
  );
}

export function ChatPortraits({ names, versions, labels, portraits }: {
  /** in the order they spoke, YOUNGEST LAST — i.e. next to the chat column */
  names: string[];
  /** name → expression version, straight out of `speaker_expr_versions` */
  versions: Record<string, string>;
  /** name → shown name (`display_names` of the scene payload) */
  labels?: Record<string, string>;
  /** name → persona portrait, '' = none (`portrait_urls` of the scene payload) */
  portraits?: Record<string, string>;
}) {
  const { t } = useI18n();
  // The renders whose <img> reported an error, keyed by name AND version: a
  // new version is a new file and deserves a fresh attempt.
  const [failed, setFailed] = useState<Record<string, true>>({});
  const blankTitle = t('No portrait');
  const narratorTitle = t('Storyteller');
  return (
    <div className="hud-chat-portraits" aria-hidden="true">
      {portraitSlots(names, versions).map((slot, i) => {
        const persona = slot.name ? portraitOverride(portraits, slot.name) : undefined;
        const key = `${slot.name}|${slot.version}|${persona ?? ''}`;
        const url = persona !== undefined ? persona
          : `/characters/${encodeURIComponent(slot.name)}/outfit-expression`
            + `?fallback=default${slot.version ? `&v=${encodeURIComponent(slot.version)}` : ''}`;
        return (
          <div key={slot.name || `blank-${i}`} className="hud-chat-portrait">
            {slot.name && url && !failed[key]
              ? <img src={url} alt={shownName(labels, slot.name)}
                  onError={() => setFailed((f) => ({ ...f, [key]: true }))} />
              : <Silhouette title={slot.narrator ? narratorTitle : blankTitle} />}
          </div>
        );
      })}
    </div>
  );
}
