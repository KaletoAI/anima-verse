import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import type { ApiClipRow, ClipListing } from '../poses/clipSets'
import { isStudioClip } from '../poses/generatedClip'

interface AnimationFile {
  set: string
  library: string
  url: string
}

interface Situation {
  pose: string
  kind: string
  public_kind: string
  file: AnimationFile | null
  public_file: AnimationFile | null
}

interface Animations {
  sets: string[]
  situations: Situation[]
  activity: Situation | null
}

interface ActivityPose {
  key: string
  label?: string
  label_de?: string
  solo: boolean
  movement?: boolean
}

// "Standing" and "Running" are taken in de.json by the queue's own words
// (standing order, task running) — hence the disambiguated sources.
const SITUATION_LABELS: Record<string, string> = {
  standing: 'Standing still',
  walking: 'Walking',
  running: 'Running fast',
  swimming: 'Swimming',
  treading_water: 'Treading water',
  crawling: 'Crawling',
  crawling_rest: 'Crawling – rest',
}

/** Display the server's played/public resolutions; never resolve clips here. */
export function AnimationSituations({ character, onPlay }: {
  character: string
  onPlay: (url: string) => void
}) {
  const { t, lang } = useI18n()
  const [data, setData] = useState<Animations | null>(null)
  const [clips, setClips] = useState<ApiClipRow[]>([])
  const [poses, setPoses] = useState<ActivityPose[]>([])
  const [pose, setPose] = useState('')
  const [activity, setActivity] = useState<Situation | null>(null)
  const [selected, setSelected] = useState('standing')
  const [error, setError] = useState('')
  const [activityError, setActivityError] = useState('')
  const [activityLoading, setActivityLoading] = useState(false)
  const path = `/characters/${encodeURIComponent(character)}/animations`

  useEffect(() => {
    let alive = true
    setData(null)
    setPose('')
    setActivity(null)
    setError('')
    setSelected('standing')
    onPlay('')
    apiGet<Animations>(path).then((result) => {
      if (!alive) return
      setData(result)
      onPlay(result.situations.find((row) => row.pose === 'standing')?.file?.url || '')
    }).catch((e: Error) => { if (alive) setError(e.message) })
    // These independent vocabularies must not prevent the situation table
    // from loading when either supporting request fails.
    apiGet<ClipListing>('/assets/animation-clips').then((result) => {
      if (alive) setClips(result.clips || [])
    }).catch((e: Error) => { if (alive) setError(e.message) })
    apiGet<{ entries: ActivityPose[] }>('/poses').then((result) => {
      if (alive) setPoses(result.entries.filter((row) => row.solo && !row.movement)
        .sort((a, b) => a.key.localeCompare(b.key)))
    }).catch((e: Error) => { if (alive) setError(e.message) })
    return () => { alive = false }
  }, [path, onPlay])

  useEffect(() => {
    let alive = true
    setActivity(null)
    setActivityError('')
    setActivityLoading(!!pose)
    if (pose) {
      apiGet<Animations>(`${path}?pose=${encodeURIComponent(pose)}`).then((result) => {
        if (alive) {
          setActivity(result.activity)
          setActivityLoading(false)
        }
      }).catch((e: Error) => {
        if (alive) {
          setActivityError(e.message)
          setActivityLoading(false)
        }
      })
    }
    return () => { alive = false }
  }, [path, pose])

  const poseLabel = (row: ActivityPose) => (lang === 'de' ? row.label_de : '') || row.label || row.key

  const fileCell = (kind: string, file: AnimationFile | null) => {
    if (!file) return <td>{kind || '—'} · <span className="ga-field-warn">{t('missing')}</span></td>
    const entry = clips.find((clip) => clip.url === file.url)
      || clips.find((clip) => clip.kind === kind && (clip.set || '') === file.set
        && clip.library === file.library)
    const studio = entry && isStudioClip(entry)
    const preferred = data?.sets.find((set) => !!set)
    return <td>
      <code>{kind}</code>{' '}
      <span className="ga-source">{file.library === 'licensed' ? t('licensed') : t('free')}</span>{' '}
      {studio ? <span className="ga-source">{t('studio')}</span> : null}
      <div className="ga-form-hint">
        {file.set || (preferred
          ? t('neutral — no {set} clip').replace('{set}', preferred)
          : t('neutral'))}
      </div>
    </td>
  }

  const play = (row: Situation) => {
    if (!row.file) return
    setSelected(row.pose)
    onPlay(row.file.url)
  }
  const rowView = (row: Situation, label: string) => <tr key={row.pose}
    onClick={() => play(row)} style={{ cursor: row.file ? 'pointer' : undefined }}>
    <td><button type="button" className="ga-btn ga-btn-sm" disabled={!row.file}
      aria-pressed={selected === row.pose}
      onClick={(event) => { event.stopPropagation(); play(row) }}>{label}</button></td>
    {fileCell(row.kind, row.file)}
    {fileCell(row.public_kind, row.public_file)}
  </tr>
  const headings = <thead><tr>
    <th>{t('Situation')}</th><th>{t('Plays')}</th><th>{t('Public')}</th>
  </tr></thead>

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 8, overflowX: 'auto' }}>
    {error ? <div className="ga-field-warn" role="alert">{error}</div> : null}
    {!data && !error ? <div className="ga-hint">{t('Loading…')}</div> : null}
    {data ? <table className="ga-sched-table">
      {headings}
      <tbody>{data.situations.map((row) => rowView(row, t(SITUATION_LABELS[row.pose] || row.pose)))}</tbody>
    </table> : null}
    <label>
      {t('Activity pose')}
      <select className="ga-input" value={pose} onChange={(event) => setPose(event.target.value)}>
        <option value="">{t('None')}</option>
        {poses.map((row) => <option key={row.key} value={row.key}>
          {poseLabel(row)}
        </option>)}
      </select>
    </label>
    {activityLoading ? <div className="ga-hint">{t('Loading…')}</div> : null}
    {activityError ? <div className="ga-field-warn" role="alert">{activityError}</div> : null}
    {activity ? <table className="ga-sched-table">
      {headings}<tbody>{rowView(activity, poseLabel(poses.find((row) => row.key === pose) || { key: pose, solo: true }))}</tbody>
    </table> : null}
  </div>
}
