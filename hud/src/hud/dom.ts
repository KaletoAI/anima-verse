/**
 * True while the key event came out of a form field — typing must never reach
 * the camera. Shared by HUD focus tracking and browser scene controls, so there is
 * one definition of "the user is typing".
 */
export function isTypingTarget(e: Event): boolean {
  return !!(e.target as HTMLElement)?.closest?.('input, textarea, select, [contenteditable]');
}

