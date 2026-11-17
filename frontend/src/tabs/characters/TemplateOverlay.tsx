/**
 * TemplateOverlay — A188: the template piece drawn ON the character's plain base-body front, live while the dialog's
 * fields change. The server registers the picture to the body's metres and returns the piece as pixel polygons
 * (`POST …/figure/template/{item}/preview`, `garment_preview.overlay`); this component only draws them: cloth as a
 * semi-transparent fill in the item's colour with an outline, openings (neckline, open front, slit) cut out of the
 * cloth so the person shows through, guides (waist line, length) as lines, and the numbers as labels. Click enlarges.
 */
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import type { TemplateParams } from './figureModel'

interface Shape { role: string; kind: 'fill' | 'cut' | 'line' | 'dash'; points: [number, number][] }
interface Mark { x: number; y: number; text: string; anchor: 'start' | 'middle' | 'end' }
export interface TemplatePreview {
  ok: boolean
  reason?: string
  picture?: { url: string; w: number; h: number }
  px_per_m?: number
  colour?: string
  shapes?: Shape[]
  marks?: Mark[]
}

/** Fills drawn above the openings (a collar / lapel lies over the neckline). */
const OVER_ROLES = new Set(['collar', 'lapel'])
const VIEW_H = 560
/** Room either side of the picture for the labels (share of its width). */
const PAD = 0.32

const pts = (s: Shape) => s.points.map((q) => q.join(',')).join(' ')

function OverlaySvg({ data, height }: { data: TemplatePreview; height: number }) {
  const { t } = useI18n()
  const pic = data.picture!
  const pad = pic.w * PAD
  const colour = data.colour || '#4f8cff'
  // the labels stay ~11 px on screen whatever the picture's size
  const font = (11 * pic.h) / height
  const stroke = (2 * pic.h) / height
  const maskId = useRef(`tpl-cut-${Math.random().toString(36).slice(2)}`).current
  const fills = (data.shapes || []).filter((s) => s.kind === 'fill')
  const cuts = (data.shapes || []).filter((s) => s.kind === 'cut')
  const under = fills.filter((s) => !OVER_ROLES.has(s.role))
  const lines = (data.shapes || []).filter((s) => s.kind === 'line' || s.kind === 'dash')
  return (
    <svg viewBox={`${-pad} 0 ${pic.w + 2 * pad} ${pic.h}`} height={height}
      width={height * (pic.w + 2 * pad) / pic.h} role="img" aria-label={t('The piece on the plain body')}
      data-overlay-shapes={(data.shapes || []).length}>
      <image href={pic.url} x={0} y={0} width={pic.w} height={pic.h} />
      <defs>
        <mask id={maskId} maskUnits="userSpaceOnUse" x={-pad} y={0} width={pic.w + 2 * pad} height={pic.h}>
          <rect x={-pad} y={0} width={pic.w + 2 * pad} height={pic.h} fill="white" />
          {cuts.map((s, i) => <polygon key={i} points={pts(s)} fill="black" />)}
        </mask>
      </defs>
      {/* the outline of the UNION of the cloth: every piece stroked twice as wide, then every fill drawn over it
          (no seam lines where a sleeve overlaps the body); one group opacity, so overlaps never darken */}
      <g mask={`url(#${maskId})`} opacity={0.6}>
        {under.map((s, i) => (
          <polygon key={`o${i}`} points={pts(s)} fill={colour} stroke="#1f4fd1" strokeWidth={stroke * 2}
            strokeLinejoin="round" />
        ))}
        {under.map((s, i) => <polygon key={`f${i}`} points={pts(s)} fill={colour} />)}
      </g>
      {fills.filter((s) => OVER_ROLES.has(s.role)).map((s, i) => (
        <polygon key={i} points={pts(s)} fill={colour} fillOpacity={0.75} stroke="#1f4fd1" strokeWidth={stroke} />
      ))}
      {lines.map((s, i) => (
        <polyline key={i} points={pts(s)} fill="none" stroke={s.role === 'dim' ? '#c0392b' : '#d1242f'}
          strokeWidth={s.role.endsWith('edge') ? stroke * 1.4 : stroke} strokeDasharray={s.kind === 'dash' ? `${stroke * 4} ${stroke * 3}` : undefined} />
      ))}
      {(data.marks || []).map((m, i) => (
        <text key={i} x={m.x} y={m.y + font * 0.35} fontSize={font} textAnchor={m.anchor} fill="#111"
          stroke="#fff" strokeWidth={font * 0.25} paintOrder="stroke" style={{ fontFamily: 'sans-serif' }}>
          {m.text}
        </text>
      ))}
    </svg>
  )
}

/** The picture with the draft on it; re-asks the server 120 ms after the last change. */
export function TemplateOverlay({ path, draft }: { path: string; draft: TemplateParams }) {
  const { t } = useI18n()
  const [data, setData] = useState<TemplatePreview | null>(null)
  const [error, setError] = useState('')
  const [big, setBig] = useState(false)
  const key = JSON.stringify(draft)
  useEffect(() => {
    let gone = false
    const id = window.setTimeout(() => {
      apiPost<TemplatePreview>(`${path}/preview`, { params: JSON.parse(key) })
        .then((r) => { if (!gone) { setData(r); setError('') } })
        .catch((e) => { if (!gone) setError((e as Error).message) })
    }, 120)
    return () => { gone = true; window.clearTimeout(id) }
  }, [path, key])
  const box: CSSProperties = { height: VIEW_H, minWidth: 260, border: '1px solid var(--border, #30363d)',
    borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
    background: '#f4f4f4' }
  const ready = data?.ok && data.picture
  return (
    <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 4, flex: '0 0 auto' }}
      data-template-overlay={ready ? 'ready' : data ? 'none' : 'loading'}>
      {ready ? (
        <button type="button" style={{ ...box, padding: 0, cursor: 'zoom-in' }} onClick={() => setBig(true)}
          title={t('click to enlarge')}>
          <OverlaySvg data={data} height={VIEW_H - 2} />
        </button>
      ) : (
        <div style={{ ...box, width: 260, padding: 12, textAlign: 'center', background: 'transparent' }} className="ga-hint">
          {error || (data ? t(data.reason || '') : t('Loading…'))}
        </div>
      )}
      <figcaption className="ga-form-hint" style={{ textAlign: 'center' }}>
        {ready ? t('Plain body front — the piece drawn at its parameters') : null}
      </figcaption>
      {big && ready ? createPortal(
        <div className="ga-modal-backdrop" style={{ zIndex: 2000, cursor: 'zoom-out' }} onMouseDown={() => setBig(false)}
          role="dialog" aria-modal="true" aria-label={t('The piece on the plain body')}>
          <div style={{ margin: 'auto', background: '#f4f4f4', borderRadius: 6 }}>
            <OverlaySvg data={data} height={Math.round(window.innerHeight * 0.92)} />
          </div>
        </div>,
        document.body,
      ) : null}
    </figure>
  )
}
