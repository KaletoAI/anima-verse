/**
 * Observer / Scene Monitor — read-only god-view on the perception stream.
 * plan-room-conversation Phase 1. Admin/debug tool, lives in the Game-Admin.
 *
 * Two modes: objective room view (raw utterances, sees whisper content) and
 * subjective character view (a character's perceptions, whisper content hidden).
 * Plus an inject form to test earshot without an LLM.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { apiGet, apiPost } from '../../lib/api'
import { SceneView, type SceneLine } from '../../components/SceneView'

interface RoomInfo { room_id: string; name: string; present: string[] }
interface LocInfo { location_id: string; name: string; rooms: RoomInfo[]; present_no_room: string[] }

type Mode = 'room' | 'character'

export function ObserverTab() {
  const { t } = useI18n()
  const { toast } = useToast()

  const [locations, setLocations] = useState<LocInfo[]>([])
  const [mode, setMode] = useState<Mode>('room')
  const [locId, setLocId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [charName, setCharName] = useState('')
  const [lines, setLines] = useState<SceneLine[]>([])
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)  // bump to force a view reload

  // inject form
  const [inSpeaker, setInSpeaker] = useState('')
  const [inVolume, setInVolume] = useState('normal')
  const [inAddr, setInAddr] = useState('')
  const [inContent, setInContent] = useState('')

  const loadPresence = useCallback(async () => {
    try {
      const data = await apiGet<{ locations: LocInfo[] }>('/admin/observer/presence')
      setLocations(data.locations || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => { loadPresence() }, [loadPresence])

  const allChars = useMemo(() => {
    const s = new Set<string>()
    for (const l of locations) {
      l.present_no_room.forEach((c) => s.add(c))
      l.rooms.forEach((r) => r.present.forEach((c) => s.add(c)))
    }
    return Array.from(s).sort()
  }, [locations])

  const currentLoc = useMemo(() => locations.find((l) => l.location_id === locId), [locations, locId])

  const loadView = useCallback(async () => {
    setLoading(true)
    try {
      if (mode === 'room') {
        if (!locId) { setLines([]); return }
        const q = new URLSearchParams({ location_id: locId, room_id: roomId })
        const data = await apiGet<{ utterances: any[] }>(`/admin/observer/room?${q}`)
        setLines((data.utterances || []).map((u): SceneLine => ({
          ts: u.ts, speaker: u.speaker, content: u.content,
          addressees: u.addressees, volume: u.volume, kind: 'utterance',
          meta: u.meta,
        })))
      } else {
        if (!charName) { setLines([]); return }
        const data = await apiGet<{ perceptions: any[] }>(
          `/admin/observer/character/${encodeURIComponent(charName)}/stream`)
        setLines((data.perceptions || []).map((p): SceneLine => ({
          ts: p.ts, content: p.content, kind: p.kind, meta: p.meta,
        })))
      }
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [mode, locId, roomId, charName, tick, t, toast])

  useEffect(() => { loadView() }, [loadView])

  const submitInject = useCallback(async () => {
    if (!inSpeaker.trim() || !inContent.trim()) {
      toast(t('speaker and content are required'), 'error')
      return
    }
    try {
      await apiPost('/admin/observer/inject', {
        speaker: inSpeaker.trim(),
        content: inContent,
        volume: inVolume,
        addressees: inAddr.split(',').map((s) => s.trim()).filter(Boolean),
        location_id: locId || null,
        room_id: roomId || null,
      })
      setInContent('')
      toast(t('Injected'))
      setMode('room')          // zur objektiven Raum-Sicht springen
      setTick((x) => x + 1)    // Reload erzwingen (auch wenn schon in room-mode)
    } catch (e) {
      toast(t('Inject failed') + ': ' + (e as Error).message, 'error')
    }
  }, [inSpeaker, inContent, inVolume, inAddr, locId, roomId, t, toast])

  return (
    <div className="ga-twocol">
      <div className="ga-twocol-left">
        <div className="ga-form-row">
          <button className={mode === 'room' ? 'active' : ''} onClick={() => setMode('room')}>
            {t('Room view')}
          </button>
          <button className={mode === 'character' ? 'active' : ''} onClick={() => setMode('character')}>
            {t('Character view')}
          </button>
          <button onClick={() => { loadPresence(); loadView() }}>{t('Refresh')}</button>
        </div>

        {mode === 'room' ? (
          <>
            <label className="ga-form-row">
              <span>{t('Location')}</span>
              <select className="ga-input" value={locId}
                onChange={(e) => { setLocId(e.target.value); setRoomId('') }}>
                <option value="">{t('— select —')}</option>
                {locations.map((l) => <option key={l.location_id} value={l.location_id}>{l.name}</option>)}
              </select>
            </label>
            <label className="ga-form-row">
              <span>{t('Room')}</span>
              <select className="ga-input" value={roomId} onChange={(e) => setRoomId(e.target.value)}>
                <option value="">{t('(whole location)')}</option>
                {(currentLoc?.rooms || []).map((r) => (
                  <option key={r.room_id} value={r.room_id}>
                    {r.name} {(r.present || []).length ? `· ${(r.present || []).join(', ')}` : ''}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <label className="ga-form-row">
            <span>{t('Character')}</span>
            <select className="ga-input" value={charName} onChange={(e) => setCharName(e.target.value)}>
              <option value="">{t('— select —')}</option>
              {allChars.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        )}

        <hr />
        <div className="ga-form-hint">{t('Inject an utterance (test earshot, no LLM).')}</div>
        <div className="ga-form-hint" style={{ opacity: 0.7 }}>
          {locId
            ? `${t('Injects into')}: ${currentLoc?.name || locId}${roomId ? ' / ' + (currentLoc?.rooms.find((r) => r.room_id === roomId)?.name || roomId) : ' (' + t('whole location') + ')'}`
            : t('No location selected → uses the speaker’s current location/room.')}
        </div>
        <label className="ga-form-row">
          <span>{t('Speaker')}</span>
          <select className="ga-input" value={inSpeaker} onChange={(e) => setInSpeaker(e.target.value)}>
            <option value="">{t('— select —')}</option>
            {allChars.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="ga-form-row">
          <span>{t('Volume')}</span>
          <select className="ga-input" value={inVolume} onChange={(e) => setInVolume(e.target.value)}>
            <option value="whisper">{t('whisper')}</option>
            <option value="normal">{t('normal')}</option>
            <option value="shout">{t('shout')}</option>
          </select>
        </label>
        <label className="ga-form-row">
          <span>{t('Addressees (comma-separated)')}</span>
          <input className="ga-input" value={inAddr} onChange={(e) => setInAddr(e.target.value)} />
        </label>
        <label className="ga-form-row">
          <span>{t('Content')}</span>
          <textarea className="ga-textarea" rows={2} value={inContent} onChange={(e) => setInContent(e.target.value)} />
        </label>
        <button onClick={submitInject}>{t('Inject')}</button>
      </div>

      <div className="ga-twocol-right">
        {loading ? <div className="ga-loading">{t('Loading…')}</div>
          : <SceneView lines={lines} emptyHint={t('Nothing perceived yet — inject something or pick a populated room/character.')} />}
      </div>
    </div>
  )
}
