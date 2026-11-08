/**
 * Character faces of the HUD — one URL rule, one stand-in, one round medallion.
 *
 * The chat's picture column (ChatPortraits) and the party badge in the top
 * bar (PartyBadge) show the SAME render: the expression image /play's Others
 * panel uses (`/characters/<name>/outfit-expression?fallback=default`), with
 * an optional cache-buster out of the scene payload. Both fall back to the
 * same silhouette when a render is missing, so the rule and the drawing live
 * here once instead of drifting apart in two files.
 */
import { useState, type CSSProperties, type ReactNode } from 'react';

/** The expression render of one character; `version` is the cache-buster the
 *  scene payload hands out (`speaker_expr_versions`, `expr_version`). */
export function faceUrl(name: string, version?: string): string {
  return `/characters/${encodeURIComponent(name)}/outfit-expression`
    + `?fallback=default${version ? `&v=${encodeURIComponent(version)}` : ''}`;
}

/**
 * The stand-in for a face: head and shoulders, no features, filled with the
 * text colour at low opacity so it reads as "no picture here" rather than as a
 * broken one — and so it works in a light theme as well as a dark one. Inline
 * on purpose: a surface that exists to stop layout jumping must not wait for a
 * network round trip to have something to draw.
 */
export function Silhouette({ title, className }: { title: string; className: string }) {
  return (
    <svg className={className} viewBox="0 0 64 96"
      role="img" aria-label={title}
      preserveAspectRatio="xMidYMax meet" focusable="false">
      <title>{title}</title>
      <circle cx="32" cy="30" r="15" fill="currentColor" />
      <path d="M4 96c0-17 12.5-28 28-28s28 11 28 28z" fill="currentColor" />
    </svg>
  );
}

/**
 * One face in a round frame (the party badge and its dropdown). The picture
 * is cropped to the circle from the TOP, where the head is; a render that
 * fails to load turns into the silhouette and stays one until the URL changes
 * (a new version is a new file and deserves a fresh attempt). `children` are
 * the small marks laid on the frame (crown, hourglass).
 */
export function Medallion({ name, version, className, title, children, style }: {
  name: string;
  version?: string;
  className?: string;
  title?: string;
  children?: ReactNode;
  style?: CSSProperties;
}) {
  const url = faceUrl(name, version);
  const [failedUrl, setFailedUrl] = useState('');
  return (
    <span className={'hud-face' + (className ? ` ${className}` : '')} title={title ?? name} style={style}>
      <span className="hud-face-disc">
        {failedUrl === url
          ? <Silhouette title={name} className="hud-face-blank" />
          : <img src={url} alt={name} draggable={false} onError={() => setFailedUrl(url)} />}
      </span>
      {children}
    </span>
  );
}
