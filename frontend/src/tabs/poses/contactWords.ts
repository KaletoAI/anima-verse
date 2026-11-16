import type { ContactTarget } from '@anima/scene-render'

/** The UI word of a contact target. */
export function targetWordOf(t: (s: string) => string, x: ContactTarget): string {
  switch (x) {
    case 'channel': return t('channel')
    case 'hand_left': return t('left hand')
    case 'hand_right': return t('right hand')
    case 'mouth': return t('mouth')
    default: return t('none')
  }
}


/** Does the target have an inside (a depth to report)? A declared channel and the mouth do, a hand does not. */
export function hasInside(x: ContactTarget): boolean {
  return x === 'channel' || x === 'mouth'
}
