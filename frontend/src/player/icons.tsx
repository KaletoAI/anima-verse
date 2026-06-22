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
  | 'inventory' | 'journal' | 'gallery' | 'instagram' | 'phone' | 'tasks' | 'layouts' | 'news'
  | 'reset' | 'close' | 'sendBack' | 'autosize' | 'maximize' | 'lock' | 'unlock'
  | 'zoomIn' | 'zoomOut' | 'settings' | 'trash'
  | 'brain' | 'cpu' | 'cloud' | 'sliders'
  | 'background' | 'tag' | 'backpack' | 'avatar'

// Jeder Eintrag = der innere Inhalt eines <svg> (Pfade/Formen).
const PATHS: Record<IconName, JSX.Element> = {
  chat: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  // Umgebung — Landschaft (Sonne + Berge), KEIN Foto-Rahmen.
  surroundings: (
    <>
      <circle cx="6.5" cy="7" r="2.2" />
      <path d="M2 20h20" />
      <path d="m4 20 5-7 3 4 3-5 5 8" />
    </>
  ),
  // Move — Kompass.
  move: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m16 8-2 6-6 2 2-6z" />
    </>
  ),
  // Karte — Globus.
  worldmap: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14.5 14.5 0 0 0 0 18 14.5 14.5 0 0 0 0-18" />
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
      <circle cx="9" cy="7" r="4" />
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <path d="M16 3.1a4 4 0 0 1 0 7.8M22 21v-2a4 4 0 0 0-3-3.87" />
    </>
  ),
  inventory: (
    <>
      <path d="M8 6V5a4 4 0 0 1 8 0v1" />
      <rect x="4" y="6" width="16" height="15" rx="2" />
      <path d="M9 11h6" />
    </>
  ),
  // News — Zeitung.
  news: (
    <>
      <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h2" />
      <path d="M10 6h8v4h-8z" />
      <path d="M18 14h-8M15 18h-5" />
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
  // Tasks/Queue — Ueberwachung: Monitor mit Aktivitaets-Puls.
  tasks: (
    <>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M6 10h2.5l1.5-3 2 5 1.5-2H18" />
      <path d="M9 21h6M12 17v4" />
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
  // LLM-Provider — Gehirn (lucide "brain")
  brain: (
    <>
      <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z" />
      <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z" />
    </>
  ),
  // Lokales ComfyUI-Backend — Chip (lucide "cpu")
  cpu: (
    <>
      <rect width="16" height="16" x="4" y="4" rx="2" />
      <rect width="6" height="6" x="9" y="9" rx="1" />
      <path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2" />
    </>
  ),
  // Cloud-Image-Backends (CivitAI/Together/OpenAI-kompatibel) — Wolke (lucide "cloud")
  cloud: <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />,
  // Automatic1111 — Regler (lucide "sliders")
  sliders: (
    <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4" />
  ),
  // "Als Hintergrund": großer Rahmen mit kleinem Inhalt (Inhalt füllt die Fläche).
  background: (
    <>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <rect x="6" y="8" width="8" height="6" rx="1" />
    </>
  ),
  // Label/Tag — für den Map-Beschriftungs-Umschalter.
  tag: (
    <>
      <path d="M20.59 13.41 11 3.83A2 2 0 0 0 9.59 3H4a1 1 0 0 0-1 1v5.59a2 2 0 0 0 .59 1.41l9.58 9.59a2 2 0 0 0 2.83 0l4.59-4.59a2 2 0 0 0 0-2.83Z" />
      <circle cx="7.5" cy="7.5" r="1.5" />
    </>
  ),
  // Inventar — Rucksack.
  backpack: (
    <>
      <path d="M5 10a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v9a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z" />
      <path d="M9 6V4.5A2.5 2.5 0 0 1 11.5 2h1A2.5 2.5 0 0 1 15 4.5V6" />
      <path d="M8 21v-4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v4" />
      <path d="M9 11h6" />
    </>
  ),
  // Avatar — Person im Profil-Kreis.
  avatar: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="10" r="3" />
      <path d="M6.5 18.5a6 6 0 0 1 11 0" />
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
