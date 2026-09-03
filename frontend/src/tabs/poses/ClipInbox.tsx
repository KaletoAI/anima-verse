/**
 * ClipInbox — importing FOREIGN animation files (plan-clip-import.md steps 1+3).
 *
 * Everything a user drops into `shared/models/clips-inbox` (or uploads here)
 * is listed with the server's probe: which skeleton family the file carries,
 * whether it has fingers, whether it looks like a reference pose. An unknown
 * rig is refused before Blender is ever started — the retargeter has no bone
 * map for it.
 *
 * Three things the form exists for:
 *   * a PAIR is two files, the selected one first; the partner is suggested
 *     from the file names and can be dropped again;
 *   * a REFERENCE POSE (T-/A-pose export of the same rig) gives the bones
 *     their real twist instead of a positional reconstruction;
 *   * the TARGET is the licensed library by default — a foreign file is
 *     licensed material until its owner says otherwise.
 *
 *   GET    /assets/clips-inbox
 *   POST   /assets/clips-inbox/upload    (multipart, field "files")
 *   DELETE /assets/clips-inbox/{name}
 *   POST   /assets/clips-inbox/import    {kind, files, rest_file, set, …}
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ClipPreview } from './ClipPreview'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface Probe {
  skeleton_family: string
  bone_count: number
  has_fingers: boolean
  is_rest_candidate: boolean
  error?: string
}

interface InboxEntry {
  name: string
  size: number
  mtime: number
  probe: Probe
  pair?: string
}

interface InboxData {
  dir: string
  entries: InboxEntry[]
  rest_suggestion: string
  families: string[]
}

interface ClipEntry { kind: string; set: string; source: string }

type Target = 'licensed' | 'free'

/** A kind proposal from the file name: role prefixes and take suffixes off,
 *  the rest slugged. `Female_Resting_Loop0.fbx` → `resting`. */
function slugFromFile(name: string): string {
  let stem = name.replace(/\.[^.]+$/, '')
  stem = stem.replace(/^(female|male)[_-]/i, '')
  stem = stem.replace(/[_-](loop|pose|take|clip)\d*$/i, '')
  stem = stem.replace(/[_-]?(a|b|l|r)$/i, '')
  return stem
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function mb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ClipInbox({ onCreatePose }: { onCreatePose?: (kind: string) => void }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const fileInput = useRef<HTMLInputElement | null>(null)

  const [data, setData] = useState<InboxData | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [clips, setClips] = useState<ClipEntry[]>([])
  const [sets, setSets] = useState<string[]>([])

  const [selected, setSelected] = useState('')
  const [second, setSecond] = useState('')
  const [restFile, setRestFile] = useState('')

  const [kind, setKind] = useState('')
  const [clipSet, setClipSet] = useState('')
  const [startS, setStartS] = useState('0')
  const [endS, setEndS] = useState('')
  const [loopOn, setLoopOn] = useState(false)
  const [loopS, setLoopS] = useState('1.5')
  /** playback factor baked into the clip: 0.5 = half speed, twice as long */
  const [speed, setSpeed] = useState('1')
  const [inPlace, setInPlace] = useState(true)
  /** partner offset for pairs whose halves are not in one world space —
   *  packs say things like "set the male model to -0.3 on the forward axis" */
  const [offFwd, setOffFwd] = useState('0')
  const [offSide, setOffSide] = useState('0')
  const [offUp, setOffUp] = useState('0')
  const [overwrite, setOverwrite] = useState(false)
  const [target, setTarget] = useState<Target>('licensed')
  const [redistributable, setRedistributable] = useState(false)
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState<{ kind: string; files: string[]; seq: number } | null>(null)

  const loadClips = useCallback(async () => {
    try {
      const r = await apiGet<{ clips?: ClipEntry[]; sets?: string[] }>('/assets/animation-clips')
      setClips(r.clips || [])
      setSets(r.sets || [])
    } catch {
      setClips([])
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await apiGet<InboxData>('/assets/clips-inbox'))
      setError('')
    } catch (e) {
      setData(null)
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    void loadClips()
  }, [load, loadClips])

  const entries = useMemo(() => data?.entries || [], [data])
  const entry = useMemo(() => entries.find((e) => e.name === selected) || null, [entries, selected])

  /** The inbox files that may join THIS one: same rig family, and not itself.
   *  A pair half or a reference pose from another rig carries different bones
   *  in different places — the retarget cannot notice and produces a constant
   *  offset in every frame (measured up to -174° on the forearm when a Unity
   *  `Tpose.fbx` was offered for the Mixamo-named MOB1 packs). */
  const kin = useMemo(
    () => entries.filter((e) => e.name !== entry?.name && !!e.probe.skeleton_family
      && e.probe.skeleton_family === entry?.probe.skeleton_family),
    [entries, entry],
  )

  /** Picking a file resets the form to that file's own defaults: the pair the
   *  names suggest, the reference pose the inbox offers, the kind slug. */
  const pick = useCallback(
    (name: string) => {
      const e = entries.find((x) => x.name === name) || null
      setSelected(name)
      setSecond(e?.pair || '')
      const rest = entries.find((x) => x.name === data?.rest_suggestion)
      setRestFile(rest && rest.name !== name
        && rest.probe.skeleton_family === e?.probe.skeleton_family ? rest.name : '')
      setKind(slugFromFile(name))
      setStartS('0')
      setEndS('')
      setLoopOn(false)
      setInPlace(!e?.pair)
      setOverwrite(false)
      setImported(null)
    },
    [data, entries],
  )

  const upload = useCallback(
    async (files: FileList | File[] | null) => {
      const list = Array.from(files || [])
      if (!list.length || uploading) return
      setUploading(true)
      let ok = 0
      for (const file of list) {
        try {
          await apiUpload('/assets/clips-inbox/upload', file, 'files')
          ok += 1
        } catch (e) {
          toast(`${file.name}: ${(e as Error).message}`, 'error')
        }
      }
      if (ok) toast(`${t('Uploaded')}: ${ok}`)
      setUploading(false)
      await load()
    },
    [load, t, toast, uploading],
  )

  const removeFiles = useCallback(
    async (names: string[]) => {
      for (const name of names) {
        try {
          await apiDelete(`/assets/clips-inbox/${encodeURIComponent(name)}`)
        } catch (e) {
          toast(`${name}: ${(e as Error).message}`, 'error')
        }
      }
      if (names.includes(selected)) {
        setSelected('')
        setImported(null)
      }
      await load()
    },
    [load, selected, toast],
  )

  const existingKinds = useMemo(
    () =>
      new Set(
        clips
          .filter((c) => c.source === target && (c.set || '') === clipSet)
          .map((c) => c.kind),
      ),
    [clips, clipSet, target],
  )
  const kindExists = existingKinds.has(kind.trim().toLowerCase())
  const unknownRig = !!entry && !entry.probe.skeleton_family
  const isPair = !!second

  /** probe conversion — the preview plays exactly what the form would import */
  const [probe, setProbe] = useState<{ urls: { a?: string; b?: string; solo?: string }; seq: number; seconds: number } | null>(null)
  const [probing, setProbing] = useState(false)

  const formBody = useCallback((): Record<string, unknown> | null => {
    if (!entry) return null
    const files = isPair ? [entry.name, second] : [entry.name]
    return {
      kind: kind.trim().toLowerCase() || 'preview',
      files,
      rest_file: restFile || null,
      set: clipSet,
      start_s: Number(startS) || 0,
      end_s: endS === '' ? null : Number(endS),
      loop_s: loopOn && !isPair ? Number(loopS) || 1 : null,
      speed: Number(speed) || 1,
      in_place: inPlace && !isPair,
      offset_b_m: isPair ? [Number(offSide) || 0, Number(offUp) || 0, Number(offFwd) || 0] : null,
      overwrite,
      target,
      redistributable: target === 'free' ? redistributable : false,
    }
  }, [clipSet, endS, entry, inPlace, isPair, kind, loopOn, loopS, offFwd, offSide, offUp, speed,
      overwrite, redistributable, restFile, second, speed, startS, target])

  const runProbe = useCallback(async () => {
    const body = formBody()
    if (!body || probing) return
    setProbing(true)
    try {
      const r = await apiPost<{ urls: { a?: string; b?: string; solo?: string }; seconds: number }>(
        '/assets/clips-inbox/preview', body)
      // cache-bust: the probe files are overwritten on every run
      const bust = (u?: string) => (u ? `${u}?v=${Date.now()}` : undefined)
      setProbe((prev) => ({ urls: { a: bust(r.urls.a), b: bust(r.urls.b), solo: bust(r.urls.solo) },
        seq: (prev?.seq || 0) + 1, seconds: r.seconds || 0 }))
      setImported(null)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setProbing(false)
    }
  }, [formBody, probing, t, toast])

  const runImport = useCallback(async () => {
    if (!entry || importing) return
    setImporting(true)
    try {
      const files = isPair ? [entry.name, second] : [entry.name]
      const body: Record<string, unknown> = {
        kind: kind.trim().toLowerCase(),
        files,
        rest_file: restFile || null,
        set: clipSet,
        start_s: Number(startS) || 0,
        end_s: endS === '' ? null : Number(endS),
        loop_s: loopOn && !isPair ? Number(loopS) || 1 : null,
        speed: Number(speed) || 1,
        in_place: inPlace && !isPair,
        offset_b_m: isPair ? [Number(offSide) || 0, Number(offUp) || 0, Number(offFwd) || 0] : null,
        overwrite,
        target,
        redistributable: target === 'free' ? redistributable : false,
      }
      const r = await apiPost<{ kind: string; seconds: number; files: string[] }>(
        '/assets/clips-inbox/import',
        body,
      )
      toast(`${t('Imported as')} ${r.kind} (${(r.seconds || 0).toFixed(1)} s)`)
      setImported((prev) => ({ kind: r.kind, files, seq: (prev?.seq || 0) + 1 }))
      await loadClips()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setImporting(false)
    }
  }, [clipSet, endS, entry, importing, inPlace, isPair, kind, loadClips, loopOn, loopS, offFwd, offSide, offUp, speed,
      overwrite, redistributable, restFile, second, startS, t, target, toast])

  if (loading) return <div className="ga-placeholder">{t('Loading…')}</div>

  return (
    <div
      style={{
        display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(340px, 1.4fr)',
        gap: 14, alignItems: 'stretch', flex: 1, minHeight: 0,
      }}
    >
      {/* ── inbox list + upload ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, minHeight: 0, overflowY: 'auto' }}>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); void upload(e.dataTransfer.files) }}
          style={{
            border: `1px dashed ${dragOver ? 'var(--accent, #58a6ff)' : 'var(--border, #30363d)'}`,
            borderRadius: 6, padding: 12, textAlign: 'center',
            background: dragOver ? 'rgba(88,166,255,0.08)' : 'transparent',
          }}
        >
          <div>{uploading ? t('Uploading…') : t('Drop FBX files here')}</div>
          <div className="ga-hint" style={{ marginTop: 4 }}>
            {t('or')}{' '}
            <button type="button" className="ga-btn ga-btn-sm" disabled={uploading}
              onClick={() => fileInput.current?.click()}>
              {t('Choose files…')}
            </button>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept=".fbx"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => { void upload(e.target.files); e.target.value = '' }}
          />
        </div>

        <div className="ga-hint" style={{ wordBreak: 'break-all' }}>
          {t('Inbox directory')}: <code>{data?.dir || ''}</code>
          {error ? ` — ${error}` : ''}
        </div>

        <ul className="ga-list" style={{ minWidth: 0 }}>
          {!entries.length ? (
            <li className="ga-list-empty">
              {t('Nothing waiting — drop files in the directory above or upload them.')}
            </li>
          ) : null}
          {entries.map((e) => {
            const badges = [
              e.probe.skeleton_family || t('unknown rig'),
              e.probe.has_fingers ? t('fingers') : '',
              e.probe.is_rest_candidate ? t('reference pose') : '',
              e.pair ? `${t('pair with')} ${e.pair}` : '',
              mb(e.size),
            ].filter(Boolean)
            return (
              <li key={e.name} style={{ minWidth: 0 }}>
                <button
                  type="button"
                  className={`ga-list-row${e.name === selected ? ' is-active' : ''}`}
                  style={{ alignItems: 'flex-start' }}
                  onClick={() => pick(e.name)}
                >
                  <span className="ga-list-row-main" style={{ minWidth: 0 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {e.name}
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', fontSize: '0.72em', opacity: 0.75, marginTop: 2 }}>
                      {badges.map((b) => (
                        <span
                          key={b}
                          style={{
                            border: '1px solid var(--border, #30363d)', borderRadius: 3,
                            padding: '0 4px',
                            color: b === t('unknown rig') ? 'var(--warn, #d29922)' : undefined,
                          }}
                        >
                          {b}
                        </span>
                      ))}
                    </div>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      {/* ── the import form ── */}
      <section style={{ minWidth: 0, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
        {!entry ? (
          <div className="ga-placeholder">{t('Pick a file to import it.')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <h3 style={{ margin: '0 0 2px' }}>{entry.name}</h3>
              <div className="ga-hint">
                {entry.probe.skeleton_family
                  ? `${entry.probe.skeleton_family} · ${entry.probe.bone_count} ${t('mapped bones')}`
                    + (entry.probe.has_fingers ? ` · ${t('fingers')}` : '')
                  : t('Unknown rig — no bone map matches this file. It cannot be imported; the known families are listed in the inbox README.')}
              </div>
            </div>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Second file (a pair — both halves become one kind)')}</span>
              <select className="ga-input" value={second} onChange={(e) => setSecond(e.target.value)}>
                <option value="">{t('— solo —')}</option>
                {kin.map((e) => (
                  <option key={e.name} value={e.name}>{e.name}</option>
                ))}
              </select>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Reference pose (optional)')}</span>
              <select className="ga-input" value={restFile} onChange={(e) => setRestFile(e.target.value)}>
                <option value="">{t('— none —')}</option>
                {kin.map((e) => (
                  <option key={e.name} value={e.name}>{e.name}</option>
                ))}
              </select>
              <span className="ga-hint">
                {t('The bind pose of THIS rig — gives the bones their real twist.'
                   + ' Only files of the same rig family are offered.')}
              </span>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Clip kind (the file stem, lowercase, no "__")')}</span>
              <input className="ga-input" value={kind} onChange={(e) => setKind(e.target.value)} />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Set (a subdirectory — empty is the neutral figure)')}</span>
              <select className="ga-input" value={clipSet} onChange={(e) => setClipSet(e.target.value)}>
                <option value="">{t('— neutral —')}</option>
                {sets.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </label>

            <div style={{ display: 'flex', gap: 8 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
                <span className="ga-hint">{t('Start (s)')}</span>
                <input className="ga-input" type="number" step="0.1" min="0" value={startS}
                  onChange={(e) => setStartS(e.target.value)} />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
                <span className="ga-hint">{t('End (s) — empty is the whole take')}</span>
                <input className="ga-input" type="number" step="0.1" min="0" value={endS}
                  onChange={(e) => setEndS(e.target.value)} />
              </label>
            </div>

            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span className="ga-hint">{t('Playback speed ×')}</span>
              <input className="ga-input" type="number" step="0.05" min="0.1" max="4" style={{ width: 80 }}
                value={speed} onChange={(e) => setSpeed(e.target.value)} />
              <span className="ga-hint">{t('0.5 = half speed (twice as long); baked into the clip')}</span>
            </label>

            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={loopOn} disabled={isPair}
                onChange={(e) => setLoopOn(e.target.checked)} />
              <span>{t('Cut to a seamless loop of at least')}</span>
              <input className="ga-input" type="number" step="0.5" min="0.5" style={{ width: 70 }}
                value={loopS} disabled={!loopOn || isPair}
                onChange={(e) => setLoopS(e.target.value)} />
              <span>s</span>
            </label>

            {isPair ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <span className="ga-hint">
                  {t('Partner (B) offset in metres — forward / side / up. Packs whose halves were not recorded in one space say so, e.g. "set the male model to -0.3 on the forward axis" → forward -0.3.')}
                </span>
                <div style={{ display: 'flex', gap: 8 }}>
                  {([['forward', offFwd, setOffFwd], ['side', offSide, setOffSide], ['up', offUp, setOffUp]] as const).map(([lbl, val, set]) => (
                    <label key={lbl} style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
                      <span className="ga-hint">{t(lbl)}</span>
                      <input className="ga-input" type="number" step="0.05" value={val}
                        onChange={(e) => set(e.target.value)} />
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={inPlace && !isPair} disabled={isPair}
                onChange={(e) => setInPlace(e.target.checked)} />
              <span>
                {t('In place (strip the horizontal root travel)')}
                {isPair ? ` — ${t('pairs keep their contact geometry')}` : ''}
              </span>
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span className="ga-hint">{t('Target library')}</span>
              <select className="ga-input" value={target}
                onChange={(e) => setTarget(e.target.value as Target)}>
                <option value="licensed">{t('licensed library (local only)')}</option>
                <option value="free">{t('free library (tracked in git)')}</option>
              </select>
            </label>

            {target === 'free' ? (
              <label style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <input type="checkbox" checked={redistributable}
                  onChange={(e) => setRedistributable(e.target.checked)} />
                <span style={{ color: 'var(--warn, #d29922)' }}>
                  {t('Redistributable — put it in the free library. Only tick this when the licence allows passing the raw files on: everything in the free library is committed to git and travels with the repository.')}
                </span>
              </label>
            ) : null}

            {kindExists ? (
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                <span style={{ color: 'var(--warn, #d29922)' }}>
                  {t('Overwrite the existing clip of this kind')}
                </span>
              </label>
            ) : null}

            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-primary"
                disabled={importing || unknownRig || !kind.trim() || (target === 'free' && !redistributable)}
                onClick={runImport}
              >
                {importing ? t('Converting with Blender…') : t('Import')}
              </button>
              {imported ? (
                <>
                  <span className="ga-source">{t('imported as')} {imported.kind}</span>
                  {onCreatePose ? (
                    <button type="button" className="ga-btn ga-btn-sm"
                      onClick={() => onCreatePose(imported.kind)}>
                      {t('Create pose entry')}
                    </button>
                  ) : null}
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => removeFiles(imported.files)}>
                    {t('Delete inbox file(s)')}
                  </button>
                </>
              ) : null}
            </div>

            <div className="ga-hint">
              {isPair
                ? t('A pair — both halves are converted into one kind (__a / __b) at a shared anchor.')
                : t('One Blender run of a few seconds; the new kind is selectable in the pose editor right after.')}
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button type="button" className="ga-btn" disabled={probing || !entry}
                onClick={() => void runProbe()}>
                {probing ? t('Converting preview…') : t('Preview with these settings')}
              </button>
              <span className="ga-hint">
                {t('Runs the conversion into a scratch folder — offset, window and reference pose exactly as the import would write them. Nothing is imported.')}
              </span>
            </div>
            {probe && !imported ? (
              <>
                <ClipPreview key={`probe:${probe.seq}`} urls={probe.urls} height={300} />
                <div className="ga-hint">{t('Preview of the current settings')} ({probe.seconds.toFixed(1)} s)</div>
              </>
            ) : null}
            {imported ? (
              <ClipPreview key={`${imported.kind}:${imported.seq}`} kind={imported.kind} height={300} />
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}
