/**
 * icons.tsx — kleines, handverlesenes Inline-SVG-Icon-Set für die Player-UI.
 *
 * Bewusst kein npm-Dependency: ein paar Dutzend Pfade im lucide-Stil
 * (24×24 viewBox, stroke=currentColor, fill=none, runde Kappen). Über
 * `currentColor` sind sie theme-fähig (erben die Textfarbe des Buttons).
 * Verwendung: <Icon name="chat" size={16} />
 */
import type { SVGProps } from 'react'

export type IconName =
  | 'chat' | 'surroundings' | 'move' | 'worldmap' | 'self' | 'others'
  | 'inventory' | 'journal' | 'gallery' | 'instagram' | 'phone' | 'tasks' | 'layouts'
  | 'reset' | 'close' | 'sendBack' | 'autosize' | 'maximize' | 'lock' | 'unlock'
  | 'zoomIn' | 'zoomOut' | 'settings' | 'trash'

// Jeder Eintrag = der innere Inhalt eines <svg> (Pfade/Formen).
const PATHS: Record<IconName, JSX.Element> = {
  chat: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  surroundings: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.5-3.5a2 2 0 0 0-2.8 0L4 22" />
    </>
  ),
  move: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
      <path d="m9 12 3-5 3 5-3 2z" />
    </>
  ),
  worldmap: (
    <>
      <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Z" />
      <path d="M9 4v14M15 6v14" />
    </>
  ),
  self: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  others: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 21a6 6 0 0 1 12 0" />
      <path d="M16 5.5a3.2 3.2 0 0 1 0 6M17 14a6 6 0 0 1 4 7" />
    </>
  ),
  inventory: (
    <>
      <path d="M8 6V5a4 4 0 0 1 8 0v1" />
      <rect x="4" y="6" width="16" height="15" rx="2" />
      <path d="M9 11h6" />
    </>
  ),
  journal: (
    <>
      <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z" />
      <path d="M19 19H6a2 2 0 0 0-2 2" />
      <path d="M9 7h6M9 11h6" />
    </>
  ),
  gallery: (
    <>
      <rect x="3" y="3" width="14" height="14" rx="2" />
      <circle cx="8" cy="8" r="1.6" />
      <path d="m17 13-3-3-5 5" />
      <path d="M21 7v12a2 2 0 0 1-2 2H7" />
    </>
  ),
  instagram: (
    <>
      <rect x="2" y="2" width="20" height="20" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  phone: (
    <>
      <rect x="6" y="2" width="12" height="20" rx="3" />
      <path d="M11 18h2" />
    </>
  ),
  tasks: (
    <>
      <path d="m3 6 1.5 1.5L7 5M3 12l1.5 1.5L7 11M3 18l1.5 1.5L7 17" />
      <path d="M11 6h10M11 12h10M11 18h10" />
    </>
  ),
  layouts: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </>
  ),
  reset: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
    </>
  ),
  close: <path d="M18 6 6 18M6 6l12 12" />,
  sendBack: (
    <>
      <path d="M12 4v11" />
      <path d="m7 11 5 5 5-5" />
      <path d="M5 20h14" />
    </>
  ),
  autosize: (
    <>
      <path d="m8 7 4-4 4 4M8 17l4 4 4-4" />
      <path d="M12 3v18" />
    </>
  ),
  maximize: (
    <>
      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
      <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
      <path d="M3 16v3a2 2 0 0 0 2 2h3" />
      <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
    </>
  ),
  lock: (
    <>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  unlock: (
    <>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 7.5-2" />
    </>
  ),
  zoomIn: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3M11 8v6M8 11h6" />
    </>
  ),
  zoomOut: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3M8 11h6" />
    </>
  ),
  trash: (
    <>
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M6 6v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
    </>
  ),
}

export function Icon({
  name, size = 16, strokeWidth = 2, ...rest
}: { name: IconName; size?: number; strokeWidth?: number } & Omit<SVGProps<SVGSVGElement>, 'name'>) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false"
      style={{ flex: '0 0 auto', display: 'block', ...rest.style }}
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
