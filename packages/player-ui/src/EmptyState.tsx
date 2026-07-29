/**
 * EmptyState — einheitlicher Leerzustand für Player-Panels.
 * Zentriertes Icon + Titel + optionaler Hilfstext. `small` für Abschnitts-
 * Leerzustände (kein volles Panel, kompakter, ohne erzwungene Höhe).
 */
import { Icon, type IconName } from './icons'

export function EmptyState({
  icon, title, hint, small,
}: { icon?: IconName; title: string; hint?: string; small?: boolean }) {
  return (
    <div className={`player-empty${small ? ' player-empty-sm' : ''}`}>
      {icon && <Icon name={icon} size={small ? 18 : 30} className="player-empty-icon" />}
      <div className="player-empty-title">{title}</div>
      {hint && <div className="player-empty-hint">{hint}</div>}
    </div>
  )
}
