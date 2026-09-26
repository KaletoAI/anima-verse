/**
 * Which clip a bridge smoke lets its figure LEAVE — shared by
 * `smoke_bridge_lift.mjs` and `smoke_bridge_root.mjs` (not a smoke itself).
 *
 * A smoke must not depend on a file only one working tree has: the lying and
 * sitting clips the live transition table names may be imports another
 * session has not committed yet. So the source is read at RUN TIME from
 * `shared/config/clip_transitions.json` (every `from` of a rule whose `kind`
 * is the bridge, in table order), and the first of them whose `.fbx` exists
 * AND is tracked by git (`git ls-files --error-unmatch`) is taken. Otherwise
 * the given tracked fallback, under the same test; otherwise `null` — the
 * caller skips what needs it, with a message.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

function tracked(root, rel) {
  try {
    execFileSync('git', ['ls-files', '--error-unmatch', rel], { cwd: root, stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

/** `{ kind, note }` for the clip the bridge `bridgeKind` leaves, or `null`.
 *  `note` says where it came from, for the smoke's log. */
export function bridgeSourceClip(root, bridgeKind, fallback) {
  const usable = (kind) => {
    const rel = `shared/models/clips/${kind}.fbx`;
    if (!existsSync(join(root, rel))) return 'missing';
    return tracked(root, rel) ? '' : 'not tracked';
  };
  const skipped = [];
  let named = [];
  try {
    const table = JSON.parse(readFileSync(join(root, 'shared/config/clip_transitions.json'), 'utf8'));
    named = [...new Set((table.transitions ?? [])
      .filter((r) => r && r.kind === bridgeKind && typeof r.from === 'string' && r.from !== '*')
      .map((r) => r.from))];
  } catch {
    skipped.push('transition table unreadable');
  }
  for (const kind of named) {
    const why = usable(kind);
    if (!why) return { kind, note: `named by the transition table for ${bridgeKind}` };
    skipped.push(`${kind} ${why}`);
  }
  if (!named.length) skipped.push(`the table names no source for ${bridgeKind}`);
  const why = usable(fallback);
  if (!why) return { kind: fallback, note: `fallback (${skipped.join('; ')})` };
  skipped.push(`fallback ${fallback} ${why}`);
  console.log(`  skip — no tracked clip to leave through ${bridgeKind}: ${skipped.join('; ')}`);
  return null;
}
