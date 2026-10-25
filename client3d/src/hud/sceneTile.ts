import type { SceneData } from '@anima/player-ui';

export type TileScene = Pick<SceneData, 'avatar' | 'location_id' | 'location_name' | 'room_id' | 'room_name' | 'present_detail' | 'avatar_expr_version' | 'bg_id' | 'bg_version' | 'travel'>;
export const TILE_COLLAPSE_BELOW_PX = 1200;
export const tileHidden = (s: TileScene): boolean => !s.bg_id || !s.location_id || !!(s.travel && !s.travel.arrived);
export const backgroundUrl = (s: TileScene): string =>
  `/world/locations/${encodeURIComponent(s.location_id)}/background?room=${encodeURIComponent(s.room_id)}&file=${encodeURIComponent(s.bg_id || '')}&v=${encodeURIComponent(s.bg_version || '')}`;
export const exprUrl = (name: string, version?: string): string =>
  `/characters/${encodeURIComponent(name)}/outfit-expression?fallback=default` + (version ? `&v=${encodeURIComponent(version)}` : '');
export function tileFigures(s: TileScene): Array<{ name: string; version: string; isAvatar: boolean }> {
  const figures = s.avatar ? [{ name: s.avatar, version: s.avatar_expr_version || '', isAvatar: true }] : [];
  const seen = new Set(figures.map(f => f.name));
  for (const f of s.present_detail) {
    if (seen.has(f.name)) continue;
    seen.add(f.name);
    figures.push({ name: f.name, version: f.expr_version || '', isAvatar: false });
  }
  return figures;
}
export const sceneKey = (s: TileScene): string => `${s.location_id}/${s.room_id}|${tileFigures(s).map(f => f.name).sort().join(',')}`;
export type RenderAnswer = { ok?: boolean; sig?: string; cached?: boolean; cooldown?: boolean; pending?: boolean };
export function renderOutcome(a: RenderAnswer): { kind: 'show'; sig: string } | { kind: 'cooldown' } | { kind: 'pending' } | { kind: 'empty' } {
  if (a.pending) return { kind: 'pending' };
  if (a.cooldown) return { kind: 'cooldown' };
  return a.ok && a.sig ? { kind: 'show', sig: a.sig } : { kind: 'empty' };
}
export const renderedSig = (pair: { key: string; sig: string } | null, currentKey: string): string | null => pair?.key === currentKey ? pair.sig : null;
