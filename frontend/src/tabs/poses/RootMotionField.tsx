import { rootMotionBlocksLoop, type RootMotionMode, type T } from './rootMotion'

/** The import form's select plus its hints. A pair keeps its contact geometry,
 *  so the field is disabled there and the caller sends `strip`. */
export function RootMotionField({ t, value, onChange, pair, loopOn }: {
  t: T
  value: RootMotionMode
  onChange: (m: RootMotionMode) => void
  pair: boolean
  loopOn: boolean
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="ga-hint">
        {t('Root motion')}
        {pair ? ` — ${t('pairs keep their contact geometry')}` : ''}
      </span>
      <select className="ga-input" value={pair ? 'strip' : value} disabled={pair}
        onChange={(e) => onChange(e.target.value as RootMotionMode)}>
        <option value="strip">{t('In place (strip the travel)')}</option>
        <option value="keep">{t('Keep the recorded travel')}</option>
        <option value="foot_lock">{t('Lock the planted feet (bridge clips)')}</option>
      </select>
      <span className="ga-hint">
        {t('Getting-up and sitting-down clips move the figure: ‘Lock the planted feet’ rebuilds the travel from the foot contacts so the feet do not slide. Loops stay in place.')}
      </span>
      {!pair && rootMotionBlocksLoop(loopOn, value) ? (
        <span style={{ color: 'var(--warn, #d29922)' }}>
          {t('A loop cannot carry travel — switch the loop off or choose ‘In place’.')}
        </span>
      ) : null}
    </label>
  )
}
