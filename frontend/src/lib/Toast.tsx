// Thin path alias after the move to the shared package (plan-3d-game stage 2).
// ~50 frontend modules keep importing '../lib/Toast'; the implementation lives
// in @anima/player-ui so the 3D client's HUD shows the identical toasts.
export { ToastProvider, useToast } from '@anima/player-ui'
