// Thin path alias after the move to the shared package (plan-3d-game stage 6).
// Frontend modules keep importing './InstagramPanel'; the implementation lives
// in @anima/player-ui so the 3D client's HUD shows the identical panel.
export {
  InstagramPanel,
  type InstagramPanelProps,
  type InstagramImageGenControl,
  type InstagramImageGenSubmit,
  type InstagramAnimateControl,
  type InstagramAnimateSubmit,
} from '@anima/player-ui'
