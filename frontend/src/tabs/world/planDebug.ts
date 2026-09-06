/**
 * planDebug — the floor plan's own trace, off by default and on with
 * `?planDebug=1` in the URL.
 *
 * "I CANNOT DRAW" IS A REPORT ABOUT SOMETHING THAT DID NOT HAPPEN, and every
 * step of the pen has its own early return: the tool may refuse to arm, the
 * click may never reach the canvas, the snap engine may move the point, the
 * commit may reject the hull. Off the flag nothing is logged and nothing is
 * computed; on it, every one of those exits names itself, so the next report
 * carries the exit instead of the symptom.
 *
 * Its own module since the canvas moved out of RoomLayoutEditor: both halves
 * of the editor log, and neither should have to import the other for it.
 */
const PLAN_DEBUG = typeof window !== 'undefined'
  && new URLSearchParams(window.location.search).get('planDebug') === '1'

export const planLog = (step: string, data?: unknown) => {
  if (PLAN_DEBUG) console.info(`[plan] ${step}`, data ?? '')
}
