// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// Frontend modules keep importing '../lib/api'; the implementation lives in
// @anima/player-ui so client3d's HUD uses the identical client.
export * from '@anima/player-ui/api';
