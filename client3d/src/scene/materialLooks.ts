/** Pure recipe look decisions; textures and renderer objects remain with the caller. */
import type { SceneExtra, ScenePayload, ScenePlate, SceneWall } from '../api';
type Style = ScenePayload['style'];
export function recipeHex(value?: string): number {
  const n = parseInt((value || '').replace('#', ''), 16);
  return Number.isFinite(n) ? n : 0xffffff;
}
export function plateLook(plate: ScenePlate, style: Style) {
  const upper = plate.opacity_role === 'upper';
  return { color: recipeHex(style.floor_color), transparent: upper,
    opacity: upper ? (style.upper_floor_opacity ?? 1) : 1,
    side: plate.thickness > 0 ? 0 : 2 };
}
export function wallLook(wall: SceneWall, style: Style) {
  if (wall.glass) return { color: recipeHex(style.glass_color), transparent: true,
    opacity: style.glass_opacity ?? 0.25, roughness: 0.3, metalness: 0.02 };
  if (wall.leaf) return { color: recipeHex(style.door_color ?? '#4a3a2e'),
    roughness: 0.75, metalness: 0.02 };
  const upper = wall.opacity_role === 'upper';
  return { color: recipeHex(style.wall_color), transparent: upper,
    opacity: upper ? (style.upper_wall_opacity ?? 1) : 1 };
}
export function extraLook(extra: SceneExtra, style: Style) {
  const glass = extra.kind.endsWith('_glass');
  const cabin = extra.kind === 'elevator_cabin';
  const color = glass ? style.glass_color
    : extra.kind.startsWith('stair_') ? (style.stair_color ?? '#8a7a66')
      : extra.kind === 'elevator_pad' ? style.elevator_pad_color
        : cabin ? style.elevator_cabin_color : style.elevator_frame_color;
  const opacity = glass ? (style.elevator_glass_opacity ?? style.glass_opacity ?? 0.22)
    : cabin ? (style.elevator_cabin_opacity ?? 1) : 1;
  return { color: recipeHex(color), transparent: opacity < 1, opacity,
    roughness: glass ? 0.3 : 0.85, metalness: 0.02 };
}
export function placeholderLook() {
  return { color: 0x9a9a9a, roughness: 0.9, metalness: 0.02,
    transparent: true, opacity: 0.5 };
}
/** Only textured metal receives an environment; the 0.5 threshold is strict. */
export function neutralizeLook(metalness: number, hasMetalnessMap: boolean, hasEnvironment: boolean) {
  return hasMetalnessMap
    ? hasEnvironment ? { metalness, envMapIntensity: 0.7 } : { metalness }
    : { metalness: metalness > 0.5 ? 0 : metalness };
}
