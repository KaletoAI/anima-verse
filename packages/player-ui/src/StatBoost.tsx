import type { StatBoost } from './statBoosts'

export function StatFill({ base, boost, color }: { base: number; boost?: StatBoost; color: string }) {
  const clamp = (n: number) => Math.max(0, Math.min(100, n))
  const value = boost?.value ?? base
  const start = clamp(Math.min(base, value))
  const end = clamp(Math.max(base, value))
  return <>
    <div style={{ position: 'absolute', left: 0, top: 0, width: `${start}%`, height: '100%', background: color }} />
    {boost && <div style={{ position: 'absolute', left: `${start}%`, top: 0, width: `${end - start}%`, height: '100%',
      background: value >= base
        ? 'repeating-linear-gradient(135deg, #7c3aed 0px, #7c3aed 3px, #ddd6fe 3px, #ddd6fe 5px)'
        : 'repeating-linear-gradient(135deg, #52525b 0px, #52525b 3px, #d4d4d8 3px, #d4d4d8 5px)' }} />}
    {value > 100 && <span style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)',
      color: '#fff', background: '#4c1d95', fontSize: 9, fontWeight: 900, lineHeight: '9px' }}>+</span>}
  </>
}
