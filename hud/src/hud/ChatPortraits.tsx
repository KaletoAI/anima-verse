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
 * to load both fall back to the SILHOUETTE (`faces.tsx`, shared with the
 * party badge). The column therefore keeps
 * its width whatever the transcript does, and the chat beside it never jumps
 * wider.
 *
 * Two DIFFERENT boxes end up nameless, and they are told apart by the slot's
 * `narrator` flag alone — never by a name, which on those rows is a localized
 * label: the narrator's own place (it has no portrait and never will, so it is
 * titled as the narrator) and the placeholder for "nothing drawable has been
 * said yet" (titled "No portrait").
 */
import { useState } from 'react';
import { useI18n } from '@anima/player-ui';

import { portraitSlots } from './chatPanel';
import { Silhouette, faceUrl } from './faces';

export function ChatPortraits({ names, versions }: {
  /** in the order they spoke, YOUNGEST LAST — i.e. next to the chat column */
  names: string[];
  /** name → expression version, straight out of `speaker_expr_versions` */
  versions: Record<string, string>;
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
        const key = `${slot.name}|${slot.version}`;
        const url = faceUrl(slot.name, slot.version);
        return (
          <div key={slot.name || `blank-${i}`} className="hud-chat-portrait">
            {slot.name && !failed[key]
              ? <img src={url} alt={slot.name}
                  onError={() => setFailed((f) => ({ ...f, [key]: true }))} />
              : <Silhouette className="hud-chat-portrait-blank"
                  title={slot.narrator ? narratorTitle : blankTitle} />}
          </div>
        );
      })}
    </div>
  );
}
