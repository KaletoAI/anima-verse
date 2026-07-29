/**
 * ScenePanel — the chat/scene surface of /play (perceived room scene, composer,
 * attachments, scene-photo flow, party invites). Extracted from PlayerApp
 * (plan-3d-game stage 2, task 3).
 *
 * Contract of the cut: PlayerApp keeps the ONE `/play/scene` poll, the
 * capability derivation and the outer `.player-panel` chrome (header, z-order,
 * react-grid-layout behaviour). This component owns the inner body: data and
 * refresh come in via props, actions (say, photo, gift, follow, party
 * respond) live here. No poll of its own — `useQueue` below joins the shared
 * 'queue-status' feed that TaskPanel & co. already share via the poll hub.
 */
import { useCallback, useEffect, useRef, useState,
  type ClipboardEvent as ReactClipboardEvent, type DragEvent as ReactDragEvent } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiPost, apiUpload } from '../lib/api'
import { useToast } from '../lib/Toast'
import { ChatGalleryPicker } from './ChatGalleryPicker'
import { GiftPicker, type GiftResult } from './GiftPicker'
import { SceneView, type SceneLine } from '../components/SceneView'
import { ImageGenDialog, type ImageGenSubmit } from '../components/ImageGenDialog'
import { ScenesRecap } from './ScenesRecap'
import { useQueue } from './useQueue'
import { useLightbox } from './Lightbox'

export type { SceneLine }

export interface RoomInfo { id: string; name: string; is_entry: boolean }
export interface Neighbor { id: string; name: string }
export type Dir = 'north' | 'south' | 'east' | 'west'

export interface SceneData {
  avatar: string
  location_id: string
  location_name: string
  room_id: string
  room_name: string
  present: string[]
  present_detail: Array<{ name: string; avatar_url: string; expr_version?: string }>
  scene: Array<{ ts: string; content: string; kind: string; meta?: Record<string, unknown> }>
  follow_suggestions?: Array<{ character: string; room_id: string; room_name: string }>
  party?: { role: 'leader' | 'follower'; leader: string; members: string[] } | null
  party_invites?: Array<{ invite_id: string; inviter: string }>
  rooms: RoomInfo[]
  neighbors: Partial<Record<Dir, Neighbor | null>>
  at_entry_room: boolean
  entry_room_name: string
  avatar_expr_version?: string
  bg_version?: string
  bg_id?: string
  capabilities?: string[]
}

export interface ScenePanelProps {
  /** The `/play/scene` payload — PlayerApp owns the single poll. */
  data: SceneData | null
  /** Force a poll refresh after own actions (say, photo, gift, party). */
  refreshScene: () => Promise<void>
  /** Active avatar name (sender for the gift/photo flows). */
  avatar: string
  /** Capability gate (PlayerApp keeps the derivation from the scene payload). */
  hasCapability: (skillId: string) => boolean
  /** A room/step change is in flight (shared with the move pad). */
  moving: boolean
  /** Enter a room by id (shared with the move pad; used by "Follow"). */
  onEnterRoom: (roomId: string) => void
}

/** Chat image attachment (#5 upload / #6 gallery). Exactly one source is set:
 * `image_id` for an upload, `image_url` for a library pick. `preview` is the
 * URL shown in the composer thumbnail. `uploading` gates send during upload. */
type AttachInfo = { image_id?: string; image_url?: string; preview: string; uploading?: boolean }
/** Prepared scene-photo dialog payload (from /play/scene-photo/prepare). */
type PhotoDlgInfo = { prompt: string; subjects: string[]; present: string[] }

// Module-level draft cache (same pattern as the Lightbox singleton): /play
// remounts the whole grid subtree on every `openKey` change (panel toggles,
// the Others panel appearing/disappearing, background toggle), which unmounts
// this component. Before the extraction this transient composer state lived in
// PlayerApp and therefore survived those remounts — the cache restores exactly
// that behaviour, keeping the panel self-contained for the 3D HUD island.
// Keyed by avatar: a full PlayerApp remount (avatar gate, page load) mounts the
// panel with avatar '' first, which discards the cache — the draft did not
// survive a PlayerApp remount before the cut either. Never persisted anywhere.
// Async completions that may land after an unmount (send, upload, photo
// prepare) additionally mutate `draft` directly — the render write-through
// alone would drop updates of an already-unmounted instance.
// CONSTRAINT: one mounted ScenePanel per document. A second instance would
// cross-wire composers through this shared object (unlike the Lightbox, whose
// singleton is deliberately global one-host state). If Task 5 ever mounts two,
// the cache must become per-instance (keyed or lifted).
const draft = {
  avatar: '',
  text: '',
  volume: 'normal',
  addressees: [] as string[],
  attach: null as AttachInfo | null,
  pickerOpen: false,
  giftOpen: false,
  photoDlg: null as PhotoDlgInfo | null,
}

function resetDraft(avatar: string) {
  draft.avatar = avatar
  draft.text = ''
  draft.volume = 'normal'
  draft.addressees = []
  draft.attach = null
  draft.pickerOpen = false
  draft.giftOpen = false
  draft.photoDlg = null
}

export function ScenePanel({ data, refreshScene, avatar, hasCapability, moving, onEnterRoom }: ScenePanelProps) {
  const { t } = useI18n()
  // Different avatar than the cached draft (incl. the '' of a fresh PlayerApp
  // mount) → drop the cache BEFORE the initializers below read it.
  if (draft.avatar !== avatar) resetDraft(avatar)
  const [text, setText] = useState(draft.text)
  const [volume, setVolume] = useState(draft.volume)
  const [addressees, setAddressees] = useState<string[]>(draft.addressees)
  const [sending, setSending] = useState(false)
  // An `uploading: true` attach in the cache is dropped at mount: the upload's
  // completion callback belongs to the previous instance and can never resolve
  // into this one — keeping it would leave the send button dead forever.
  const [attach, setAttach] = useState<AttachInfo | null>(
    draft.attach?.uploading ? null : draft.attach)
  const [pickerOpen, setPickerOpen] = useState(draft.pickerOpen)
  const [giftOpen, setGiftOpen] = useState(draft.giftOpen)
  // Write-through on every render (same pattern as PlayerApp's state→ref sync):
  // the cache always holds the last rendered values, so an unmount loses nothing.
  draft.text = text
  draft.volume = volume
  draft.addressees = addressees
  draft.attach = attach
  draft.pickerOpen = pickerOpen
  draft.giftOpen = giftOpen
  const fileInputRef = useRef<HTMLInputElement>(null)
  const lightbox = useLightbox()
  const { toast } = useToast()

  const toggleAddressee = useCallback((name: string) => {
    setAddressees((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name])
  }, [])

  const send = useCallback(async () => {
    // An attached image alone is a valid message; an upload still in flight is not.
    const hasImage = !!(attach && (attach.image_id || attach.image_url))
    if ((!text.trim() && !hasImage) || sending || attach?.uploading) return
    setSending(true)
    // Clear the CACHE for the duration of the request: a grid remount landing
    // mid-flight must not resurrect text/attachment that are already on their
    // way to the server (duplicate send). The still-mounted composer keeps its
    // own state; on failure the cache is restored in the catch below.
    draft.text = ''
    draft.attach = null
    try {
      const addr = volume === 'whisper' ? addressees.slice(0, 1) : addressees
      await apiPost('/play/say', {
        content: text, volume, addressees: addr,
        ...(attach?.image_id ? { image_id: attach.image_id } : {}),
        ...(attach?.image_url ? { image_url: attach.image_url } : {}),
      })
      setText('')
      setAttach(null)
      // Clear the cache again at completion: it may have been re-written by a
      // render of the still-mounted composer during the flight, and this
      // completion may land after an unmount, where the setState calls above
      // are dropped (see the draft-cache note).
      draft.text = ''
      draft.attach = null
      await refreshScene()
    } catch {
      // Failed send keeps the draft (pre-cut behaviour): restore the cache
      // cleared above. The api client handles the auth redirect.
      draft.text = text
      draft.attach = attach
    } finally {
      setSending(false)
    }
  }, [text, volume, addressees, sending, attach, refreshScene])

  // 📷 scene photo: step 1 distills the prompt from the recent room
  // conversation (+ person descriptions) and opens the image-gen dialog
  // (model/LoRA/prompt editable); step 2 generates into the avatar's
  // gallery + narrator line in the chat (present characters can react).
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoDlg, setPhotoDlg] = useState<PhotoDlgInfo | null>(draft.photoDlg)
  draft.photoDlg = photoDlg  // write-through, like the composer state above
  const takePhoto = useCallback(async () => {
    if (photoBusy) return
    setPhotoBusy(true)
    try {
      const d = await apiPost<{ ok?: boolean; prompt?: string; subjects?: string[]; present?: string[] }>(
        '/play/scene-photo/prepare', {})
      if (d?.ok) {
        const dlg = { prompt: d.prompt || '', subjects: d.subjects || [], present: d.present || [] }
        setPhotoDlg(dlg)
        draft.photoDlg = dlg  // completion may land after an unmount (see cache note)
      } else {
        toast(t('Photo failed.'), 'error')
      }
    } catch (e) {
      toast((e as Error).message || t('Photo failed.'), 'error')
    } finally {
      setPhotoBusy(false)
    }
  }, [photoBusy, toast, t])
  const submitPhoto = useCallback(async (payload: ImageGenSubmit) => {
    setPhotoDlg(null)
    setPhotoBusy(true)
    try {
      const d = await apiPost<{ ok?: boolean }>('/play/scene-photo', {
        prompt: payload.prompt,
        backend: payload.backend || '',
        loras: payload.loras || null,
        negative_prompt: payload.negative_prompt || '',
        character_names: payload.character_names || null,
        use_room: payload.use_room !== false,
      })
      if (d?.ok) {
        toast(t('Photo saved to your gallery.'), 'success')
        await refreshScene()
      } else {
        toast(t('Photo failed.'), 'error')
      }
    } catch (e) {
      toast((e as Error).message || t('Photo failed.'), 'error')
    } finally {
      setPhotoBusy(false)
    }
  }, [toast, t, refreshScene])

  // Upload a picked/pasted/dropped file → attach by image_id. A local object URL
  // is shown immediately as the preview while the upload resolves.
  const uploadImage = useCallback(async (file: File) => {
    if (!file.type.startsWith('image/')) return
    const localPreview = URL.createObjectURL(file)
    setAttach({ preview: localPreview, uploading: true })
    try {
      const r = await apiUpload<{ image_id: string }>('/chat/me/upload-image', file)
      const done = { image_id: r.image_id, preview: localPreview, uploading: false }
      setAttach(done)
      // Both completion paths also write the cache directly: they may land
      // after an unmount, and a cached `uploading: true` would otherwise keep
      // the remounted composer's send button dead forever.
      draft.attach = done
    } catch {
      setAttach(null)
      draft.attach = null
      URL.revokeObjectURL(localPreview)
    }
  }, [])

  const onComposerPaste = useCallback((e: ReactClipboardEvent) => {
    const item = Array.from(e.clipboardData.items).find((it) => it.type.startsWith('image/'))
    if (item) {
      const f = item.getAsFile()
      if (f) { e.preventDefault(); uploadImage(f) }
    }
  }, [uploadImage])

  const onComposerDrop = useCallback((e: ReactDragEvent) => {
    const f = Array.from(e.dataTransfer.files).find((x) => x.type.startsWith('image/'))
    if (f) { e.preventDefault(); uploadImage(f) }
  }, [uploadImage])

  // Party (travel together): answer an invitation in the chat window. Leaving
  // sits in the NoticeBanner (persistent party strip).
  const handlePartyRespond = useCallback(async (inviteId: string, accept: boolean) => {
    try {
      const res = await apiPost<{ status?: string; inviter?: string }>(
        '/play/party/respond', { invite_id: inviteId, accept })
      // A party is formed face to face: if the inviter has moved on in the
      // meantime, joining fails — say so instead of letting the row vanish.
      if (res?.status === 'not_present') {
        toast(t('{name} is no longer here — you cannot travel together.')
          .replace('{name}', res.inviter || ''), 'error')
      }
      await refreshScene()
    }
    catch { /* ignore */ }
  }, [refreshScene, toast, t])

  const lines: SceneLine[] = (data?.scene || []).map((p) => ({
    ts: p.ts, content: p.content, kind: p.kind, meta: p.meta,
  }))
  const present = data?.present || []
  // Scene indicator: ONLY replies ("X is responding …"), no background
  // thoughts. The task panel shows all LLM calls (thoughts too) independently.
  const { agentActivity } = useQueue(2000)
  const thinkingHere = present
    .filter((p) => agentActivity[p]?.responding)
    .map((p) => ({ name: p, responding: true }))

  // Auto-scroll the scene to the end (newest perception at the bottom). "Stick
  // to bottom": only follow along when the user already is at the bottom — do
  // not yank them away while they scrolled up to read.
  const sceneScrollRef = useRef<HTMLDivElement>(null)
  const sceneStickRef = useRef(true)
  const onSceneScroll = useCallback(() => {
    const el = sceneScrollRef.current
    if (!el) return
    sceneStickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }, [])
  useEffect(() => {
    const el = sceneScrollRef.current
    if (el && sceneStickRef.current) el.scrollTop = el.scrollHeight
  }, [lines.length, thinkingHere.length])

  // Prune the addressee selection as soon as the present set changes (e.g.
  // after a room/location change) — otherwise someone from the old room stays
  // addressed who is not even here. The backend filters too; this is the UI side.
  // Beware: the join separator is a literal (invisible) U+0001 control byte,
  // carried over verbatim from PlayerApp so adjacent names cannot collide.
  const presentKey = present.join('')
  useEffect(() => {
    setAddressees((prev) => {
      const next = prev.filter((n) => present.includes(n))
      return next.length === prev.length ? prev : next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presentKey])

  return (
    <>
      <div className="player-scene-body">
        <ScenesRecap />
        <div className="player-scene-scroll" ref={sceneScrollRef} onScroll={onSceneScroll}>
          <SceneView lines={lines} emptyHint={t('Nothing here yet.')} thinking={thinkingHere}
            onOpenImage={(u) => lightbox.open({ src: u })} />
        </div>

        {(data?.follow_suggestions?.length ?? 0) > 0 && (
          <div style={{
            flex: '0 0 auto', padding: '6px 12px', display: 'flex', flexWrap: 'wrap',
            gap: 10, alignItems: 'center', borderTop: '1px solid var(--border, #30363d)',
            background: 'rgba(214,176,106,0.08)',
          }}>
            {data!.follow_suggestions!.map((f) => (
              <span key={f.character} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82em' }}>
                <span style={{ fontStyle: 'italic', color: '#d6b06a' }}>
                  {f.character} {t('went to')} {f.room_name}.
                </span>
                <button onClick={() => onEnterRoom(f.room_id)} disabled={moving}
                  className="player-chip player-chip-follow">
                  {t('Follow')}
                </button>
              </span>
            ))}
          </div>
        )}

        {(data?.party_invites?.length ?? 0) > 0 && (
          <div style={{
            flex: '0 0 auto', padding: '6px 12px', display: 'flex', flexWrap: 'wrap',
            gap: 10, alignItems: 'center', borderTop: '1px solid var(--border, #30363d)',
            background: 'rgba(120,170,255,0.10)',
          }}>
            {data!.party_invites!.map((inv) => (
              <span key={inv.invite_id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82em' }}>
                <span style={{ fontStyle: 'italic', color: '#78aaff' }}>
                  👥 {inv.inviter} {t('invites you to travel together.')}
                </span>
                <button onClick={() => handlePartyRespond(inv.invite_id, true)}
                  className="player-chip player-chip-follow">
                  {t('Join')}
                </button>
                <button onClick={() => handlePartyRespond(inv.invite_id, false)}
                  className="player-chip">
                  {t('Decline')}
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="player-composer"
          onDragOver={(e) => { if (Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault() }}
          onDrop={onComposerDrop}>
          {present.length > 0 && (
            <div className="player-address-row">
              <span className="player-address-label">{t('Address')}:</span>
              {present.map((name) => {
                const on = addressees.includes(name)
                return (
                  <button key={name} onClick={() => toggleAddressee(name)}
                    className={`player-chip${on ? ' on' : ''}`}>
                    {name}
                  </button>
                )
              })}
            </div>
          )}
          {attach && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div style={{ position: 'relative', flex: '0 0 auto' }}>
                <img src={attach.preview} alt={t('Attached image')}
                  style={{
                    width: 56, height: 56, objectFit: 'cover', borderRadius: 6,
                    border: '1px solid var(--border, #30363d)',
                    opacity: attach.uploading ? 0.5 : 1,
                  }} />
                <button type="button" onClick={() => setAttach(null)} title={t('Remove')}
                  style={{
                    position: 'absolute', top: -6, right: -6, width: 18, height: 18,
                    borderRadius: '50%', border: 'none', cursor: 'pointer',
                    background: 'var(--danger, #da3633)', color: '#fff', fontSize: 11,
                    lineHeight: '18px', padding: 0,
                  }}>×</button>
              </div>
              <span style={{ fontSize: '0.8em', opacity: 0.7 }}>
                {attach.uploading ? t('Uploading…') : t('Image attached')}
              </span>
            </div>
          )}
          <textarea className="player-composer-input" rows={3} value={text} disabled={sending}
            onChange={(e) => setText(e.target.value)}
            onPaste={onComposerPaste}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder={sending ? t('Waiting for a reply…') : t('Say something…')} />
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadImage(f); e.target.value = '' }} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
            <select className="ga-input" value={volume} onChange={(e) => setVolume(e.target.value)}
              style={{ flex: '0 0 auto', width: 'auto' }}>
              <option value="whisper">{t('whisper')}</option>
              <option value="normal">{t('normal')}</option>
              <option value="shout">{t('shout')}</option>
            </select>
            <button type="button" className="player-chip" title={t('Upload image')}
              onClick={() => fileInputRef.current?.click()} disabled={sending}>📎</button>
            <button type="button" className="player-chip" title={t('Pick from gallery')}
              onClick={() => setPickerOpen(true)} disabled={sending}>🖼</button>
            <button type="button" className="player-chip" title={t('Give a gift')}
              onClick={() => setGiftOpen(true)} disabled={sending || present.length === 0}>🎁</button>
            {hasCapability('image_generation') && (
              <button type="button" className="player-chip" style={{ marginLeft: 12 }}
                title={t('Take a photo of the current moment (saved to your gallery)')}
                onClick={takePhoto} disabled={photoBusy}>
                {photoBusy ? '⌛' : '📷'}
              </button>
            )}
            <span style={{ flex: 1 }} />
            <button className="player-btn-primary" onClick={send}
              disabled={sending || attach?.uploading || (!text.trim() && !attach)}>
              {sending ? t('Sending…') : t('Send')}
            </button>
          </div>
          {volume === 'whisper' && addressees.length !== 1 && (
            <div style={{ opacity: 0.6, fontSize: '0.8em', marginTop: 4 }}>
              {t('Whispering needs exactly one addressee.')}
            </div>
          )}
        </div>
      </div>
      {pickerOpen && (
        <ChatGalleryPicker
          onClose={() => setPickerOpen(false)}
          onPick={(url) => { setAttach({ image_url: url, preview: url }); setPickerOpen(false) }}
        />
      )}
      {photoDlg && (
        <ImageGenDialog
          open
          title={t('Scene photo')}
          defaultPrompt={photoDlg.prompt}
          showRoomReference
          characterOptions={{
            detected: photoDlg.subjects,
            available: Array.from(new Set([...photoDlg.present, ...(avatar ? [avatar] : [])])),
          }}
          onSubmit={submitPhoto}
          onClose={() => setPhotoDlg(null)}
        />
      )}
      {giftOpen && (
        <GiftPicker
          avatar={avatar}
          recipients={present}
          defaultRecipient={addressees.length === 1 ? addressees[0] : undefined}
          onClose={() => setGiftOpen(false)}
          onGifted={(r: GiftResult) => {
            setGiftOpen(false)
            toast(
              `${t('Gift sent')}: ${r.item_name} → ${r.to_character}` +
                (r.boost ? ` (+${r.boost} ${t('relationship')})` : ''),
              'success',
            )
            refreshScene()
          }}
        />
      )}
    </>
  )
}
