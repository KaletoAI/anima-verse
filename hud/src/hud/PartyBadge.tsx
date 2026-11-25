/**
 * The party in the top bar: who travels with the avatar, as a row of faces
 * beside the panel buttons, and a dropdown under it with the details.
 *
 * Purely presentational, like the panels around it: the `/play/scene` poll of
 * Hud.tsx hands in `party` and the avatar's own open invitations
 * (`party_invites_sent`), and the host owns every request (leave, take back)
 * and the OPEN state — the latter because Esc reaches the dropdown through the
 * same bus path as the game menu (`uiActions.closeMenu`). The only state here
 * is the inline Leave confirmation (no `window.confirm`) and which invitation
 * is being taken back.
 *
 * The badge is a 30px pill, the height of the panel studs: a banner glyph,
 * then overlapping round faces — the leader first and on top with a crown,
 * the followers (the avatar among them where it stands), then the people the
 * avatar invited who have not answered yet, dimmed with a dashed ring and an
 * hourglass. At most `MAX_FACES` faces; the rest becomes a "+N" bead. So the
 * badge also stands while there is no party YET, only an open invitation.
 * On a narrow window hud.css folds the faces away and shows glyph + count.
 *
 * Invitations put TO the avatar are deliberately not here: ScenePanel carries
 * that question, and two places to answer it would answer it twice.
 */
import { useEffect, useRef, useState } from 'react';
import { Icon, useI18n, type SceneData } from '@anima/player-ui';
import { Medallion } from './faces';

/** Faces drawn in the bar before the rest folds into a "+N" bead. */
const MAX_FACES = 4;

type Party = NonNullable<SceneData['party']>;
type SentInvite = NonNullable<SceneData['party_invites_sent']>[number];

interface Face {
  name: string;
  leader: boolean;
  /** an open invitation of the avatar's, not (yet) a member */
  invite?: SentInvite;
}

/** Leader first, then the followers in the server's order, then the open
 *  invitations. A name that is already in the party is not drawn twice. */
function partyFaces(party: Party | null | undefined, sent: SentInvite[]): Face[] {
  const faces: Face[] = [];
  const seen = new Set<string>();
  if (party?.leader) { faces.push({ name: party.leader, leader: true }); seen.add(party.leader); }
  for (const name of party?.members ?? []) {
    if (!name || seen.has(name)) continue;
    faces.push({ name, leader: false });
    seen.add(name);
  }
  for (const invite of sent) {
    if (!invite.invitee || seen.has(invite.invitee)) continue;
    faces.push({ name: invite.invitee, leader: false, invite });
    seen.add(invite.invitee);
  }
  return faces;
}

/** A pennant on a pole — the company that travels under one banner. */
function BannerGlyph() {
  return (
    <svg className="hud-party-glyph" viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 21.5V2.5" />
      <path d="M5 3.5h14l-3.4 4.25L19 12H5z" fill="currentColor" fillOpacity="0.28" />
    </svg>
  );
}

function Crown({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 14 10" aria-hidden="true">
      <path d="M1.2 9h11.6l.9-6.6-3.6 2.7L7 .8 3.9 5.1.3 2.4z" />
    </svg>
  );
}

function Hourglass({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 12 12" aria-hidden="true">
      <path d="M3 1.5h6M3 10.5h6M3.6 1.5c0 2.6 2.4 3 2.4 4.5S3.6 8 3.6 10.5M8.4 1.5c0 2.6-2.4 3-2.4 4.5s2.4 2 2.4 4.5" />
    </svg>
  );
}

export interface PartyBadgeProps {
  party: SceneData['party'] | undefined;
  sent: SceneData['party_invites_sent'] | undefined;
  /** the avatar's name — its row says "You" */
  avatar: string;
  /** name → expression version (cache-buster), from the same scene payload */
  versions: Record<string, string>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Leave the party. The host posts and refreshes — no optimistic UI here. */
  onLeave: () => Promise<void> | void;
  /** Take back one open invitation; the host posts and refreshes. */
  onTakeBack: (inviteId: string) => Promise<void> | void;
}

export function PartyBadge({ party, sent, avatar, versions, open, onOpenChange, onLeave, onTakeBack }: PartyBadgeProps) {
  const { t } = useI18n();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [takingBack, setTakingBack] = useState('');
  const faces = partyFaces(party, sent ?? []);

  // A closed dropdown forgets a half-answered "Leave the party?".
  useEffect(() => { if (!open) setConfirming(false); }, [open]);

  // Outside click closes, like a menu. Capture phase, so a press that starts a
  // camera drag on the canvas closes it as well. Esc goes through the host.
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) onOpenChange(false);
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [open, onOpenChange]);

  if (faces.length === 0) return null;

  const shown = faces.length > MAX_FACES ? faces.slice(0, MAX_FACES) : faces;
  const folded = faces.slice(shown.length);
  const waiting = t('Waiting for an answer…');
  const faceTitle = (f: Face) => f.leader ? `${f.name} · ${t('Party leader')}`
    : f.invite ? `${f.name} · ${waiting}` : f.name;
  const faceClass = (f: Face) => (f.leader ? 'is-leader' : '') + (f.invite ? ' is-pending' : '');
  const takeBack = async (inviteId: string) => {
    if (takingBack) return;
    setTakingBack(inviteId);
    try { await onTakeBack(inviteId); } finally { setTakingBack(''); }
  };

  return (
    <div ref={wrapRef} className="hud-party">
      <button type="button" className={'hud-party-badge' + (open ? ' on' : '')}
        aria-haspopup="dialog" aria-expanded={open}
        aria-label={`${t('Party')}: ${faces.map((f) => f.name).join(', ')}`}
        title={t('Party')} onClick={() => onOpenChange(!open)}>
        <BannerGlyph />
        <span className="hud-party-faces">
          {shown.map((f, i) => (
            // Earlier faces lie ON the later ones, so the leader's crown is
            // never covered by the follower beside it.
            <Medallion key={f.name} name={f.name} version={versions[f.name]}
              className={faceClass(f)} title={faceTitle(f)} style={{ zIndex: shown.length - i + 1 }}>
              {f.leader && <Crown className="hud-face-crown" />}
              {f.invite && <span className="hud-face-wait"><Hourglass className="hud-face-wait-glyph" /></span>}
            </Medallion>
          ))}
          {folded.length > 0 && (
            <span className="hud-face hud-face-more" style={{ zIndex: 1 }}
              title={folded.map(faceTitle).join('\n')}>
              <span className="hud-face-disc">+{folded.length}</span>
            </span>
          )}
        </span>
        <span className="hud-party-count" aria-hidden="true">{faces.length}</span>
      </button>

      {open && (
        <section className="hud-panel hud-party-drop" role="dialog" aria-label={t('Party')}>
          <header className="hud-panel-head">
            <BannerGlyph />
            <span className="hud-panel-title">{t('Party')}</span>
            {party && (
              <span className="hud-panel-sub">· {party.role === 'leader' ? t('You lead') : t('You follow')}</span>
            )}
            <button type="button" className="hud-panel-close" onClick={() => onOpenChange(false)}
              title={t('Close')} aria-label={t('Close')}>
              <Icon name="close" size={14} />
            </button>
          </header>
          <ul className="hud-party-list">
            {faces.map((f) => (
              <li key={f.name} className={'hud-party-row' + (f.invite ? ' is-pending' : '')}>
                <Medallion name={f.name} version={versions[f.name]} className={faceClass(f)} title={faceTitle(f)}>
                  {f.leader && <Crown className="hud-face-crown" />}
                  {f.invite && <span className="hud-face-wait"><Hourglass className="hud-face-wait-glyph" /></span>}
                </Medallion>
                <span className="hud-party-who">
                  <span className="hud-party-name">{f.name}</span>
                  {f.invite && <span className="hud-party-note">{waiting}</span>}
                </span>
                {f.leader && (
                  <span className="hud-party-tag is-lead" title={t('Party leader')}>
                    <Crown className="hud-party-tag-crown" />{t('Leader')}
                  </span>
                )}
                {f.name === avatar && <span className="hud-party-tag is-you">{t('You')}</span>}
                {f.invite && (
                  <button type="button" className="player-chip hud-party-takeback"
                    disabled={!!takingBack} onClick={() => void takeBack(f.invite!.invite_id)}>
                    {t('Take back')}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {party && (
            <footer className="hud-party-foot">
              {confirming ? (
                <>
                  <span className="hud-party-ask">{t('Leave the party?')}</span>
                  <button type="button" className="player-chip hud-party-leave"
                    onClick={() => { setConfirming(false); onOpenChange(false); void onLeave(); }}>
                    {t('Yes')}
                  </button>
                  <button type="button" className="player-chip" onClick={() => setConfirming(false)}>
                    {t('Cancel')}
                  </button>
                </>
              ) : (
                <button type="button" className="player-chip hud-party-leave" onClick={() => setConfirming(true)}>
                  {t('Leave party')}
                </button>
              )}
            </footer>
          )}
        </section>
      )}
    </div>
  );
}
