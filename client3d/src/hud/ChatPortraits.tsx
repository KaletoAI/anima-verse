/**
 * The picture column of the HUD chat window (plan-hud-chat-portraits.md, 2b).
 *
 * Purely presentational: WHICH faces it shows and in what order is decided by
 * `pickPortraitSpeakers` in `chatPanel.ts` and handed down as a plain list of
 * names — this file only draws them.
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
 * whatever box it is given without ever pushing the column open. A missing
 * render (404, a character without one) hides the image instead of leaving the
 * browser's broken-image glyph standing in the column.
 */

export function ChatPortraits({ names, versions }: {
  /** in the order they spoke, YOUNGEST LAST — i.e. next to the chat column */
  names: string[];
  /** name → expression version, straight out of `speaker_expr_versions` */
  versions: Record<string, string>;
}) {
  if (!names.length) return null;
  return (
    <div className="hud-chat-portraits" aria-hidden="true">
      {names.map((name) => {
        const v = versions[name] || '';
        const url = `/characters/${encodeURIComponent(name)}/outfit-expression`
          + `?fallback=default${v ? `&v=${encodeURIComponent(v)}` : ''}`;
        return (
          <div key={name} className="hud-chat-portrait">
            <img src={url} alt={name}
              onError={(e) => {
                (e.target as HTMLImageElement).style.visibility = 'hidden';
              }} />
          </div>
        );
      })}
    </div>
  );
}
