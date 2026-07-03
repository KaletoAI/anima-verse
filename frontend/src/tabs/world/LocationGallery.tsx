import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'
import { IMAGE_TYPES, type GalleryResponse, type Location, type Room } from './worldTypes'

// ── Gallery — list, type-change, night-variant, delete, enlarge. ───────────

interface GalleryCardProps {
  filename: string
  url: string
  type: string
  meta: { backend?: string; model?: string; loras?: string[] }
  isBusy: boolean
  mapUsage: number
  onZoom: (url: string) => void
  onSetType: (image: string, type: string) => void
  onGenerateNight: (image: string) => void
  onRegen: (target: { filename: string; type: string }) => void
  onMove: (image: string) => void
  onRemove: (image: string) => void
}

const GalleryCard = memo(function GalleryCard({
  filename,
  url,
  type,
  meta,
  isBusy,
  mapUsage,
  onZoom,
  onSetType,
  onGenerateNight,
  onRegen,
  onMove,
  onRemove,
}: GalleryCardProps) {
  const { t } = useI18n()
  return (
    <div className="ga-gallery-card">
      <button
        type="button"
        className="ga-gallery-thumb"
        onClick={() => onZoom(url)}
        title={t('Click to enlarge')}
      >
        <img src={url} alt={filename} />
        {type === 'map_2d' ? (
          <span
            className="ga-gallery-usage"
            title={t('How many map cells currently use this image')}
          >
            {mapUsage}
          </span>
        ) : null}
      </button>
      <div className="ga-gallery-card-body">
        <div className="ga-gallery-meta">
          {meta.model ? (
            <div>
              <strong>{t('Model')}</strong> {meta.model}
            </div>
          ) : null}
          {meta.loras && meta.loras.length > 0 ? (
            <div>
              <strong>{t('LoRAs')}</strong> {meta.loras.join(', ')}
            </div>
          ) : null}
          {meta.backend ? (
            <div>
              <strong>{t('Provider')}</strong> {meta.backend}
            </div>
          ) : null}
        </div>
        <div className="ga-gallery-actions">
          <select
            className="ga-input ga-gallery-type-select"
            value={type}
            disabled={isBusy}
            onChange={(e) => onSetType(filename, e.target.value)}
            title={t('Image type')}
          >
            <option value="">— {t('type')} —</option>
            {IMAGE_TYPES.filter((x) => x !== '').map((tp) => (
              <option key={tp} value={tp}>
                {tp}
              </option>
            ))}
          </select>
          <button
            className="ga-btn ga-btn-sm"
            disabled={isBusy}
            onClick={() => onGenerateNight(filename)}
            title={t('Generate a night variant from this image')}
          >
            🌙
          </button>
          <button
            className="ga-btn ga-btn-sm"
            disabled={isBusy}
            onClick={() => onRegen({ filename, type })}
            title={t('Adjust this image via a reference-capable backend + prompt (saved as a new image)')}
          >
            ♻
          </button>
          <button
            className="ga-btn ga-btn-sm"
            disabled={isBusy}
            onClick={() => onMove(filename)}
            title={t('Move this image to another location')}
          >
            ⇄
          </button>
          <button
            className="ga-btn ga-btn-sm ga-btn-danger"
            disabled={isBusy}
            onClick={() => onRemove(filename)}
          >
            ×
          </button>
        </div>
      </div>
    </div>
  )
})

export function LocationGallery({
  locationId,
  location,
  room,
  roomFilter,
  allLocations,
  placements,
}: {
  locationId: string
  location: Location
  room: Room | null
  /** When set, only images assigned to this room are shown. */
  roomFilter?: string
  /** All places (for the "move image to another location" picker). */
  allLocations: Location[]
  /** Unfiltered list incl. clone placements (for the map-usage counter). */
  placements: Location[]
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [data, setData] = useState<GalleryResponse | null>(null)
  const [zoom, setZoom] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [dialogType, setDialogType] = useState<'day' | 'night' | 'map_2d' | null>(null)
  // "Regenerate" target: recreate an existing map image using it as a reference.
  const [regenTarget, setRegenTarget] = useState<{ filename: string; type: string } | null>(null)
  // Independent config suffixes for map icons (editable in the dialog instead of
  // appended server-side). Load once.
  const [mapSuffix, setMapSuffix] = useState({ map_2d: '' })
  // "Move image": the open image + the chosen target location.
  const [moveImage, setMoveImage] = useState<string | null>(null)
  const [moveTarget, setMoveTarget] = useState('')
  useEffect(() => {
    apiGet<{ map_2d_image_prompt_suffix?: string }>('/world/imagegen-options')
      .then((d) => setMapSuffix({ map_2d: d.map_2d_image_prompt_suffix || '' }))
      .catch(() => { /* ignore */ })
  }, [])

  const reload = useCallback(async () => {
    try {
      const d = await apiGet<GalleryResponse>(
        `/world/locations/${encodeURIComponent(locationId)}/gallery`,
      )
      setData({
        images: d.images || [],
        image_rooms: d.image_rooms || {},
        image_types: d.image_types || {},
        image_metas: d.image_metas || {},
      })
    } catch {
      setData({ images: [] })
    }
  }, [locationId])

  useEffect(() => {
    reload()
  }, [reload])

  // Move an image to another location (file + prompt/type/meta).
  const submitMove = useCallback(async () => {
    if (!moveImage || !moveTarget) return
    try {
      await apiPost(
        `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(moveImage)}/move`,
        { target: moveTarget },
      )
      toast(t('Image moved'))
      setMoveImage(null)
      setMoveTarget('')
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [moveImage, moveTarget, locationId, reload, t, toast])

  const allImages = data?.images || []
  const rooms = data?.image_rooms || {}
  const types = data?.image_types || {}
  const metas = data?.image_metas || {}

  // How often each map image is currently used on the map: placed cells
  // whose gallery owner is this location (clones share the template gallery) and
  // that picked exactly this file as the 2D tile. File -> count.
  const mapUsage = useMemo(() => {
    const m: Record<string, number> = {}
    for (const l of placements) {
      if (l.grid_x == null || l.grid_y == null || l.grid_x < 0 || l.grid_y < 0) continue
      if (((l.template_location_id || '').trim() || l.id) !== locationId) continue
      const f = (l.map_image_2d || '').trim()
      if (f) m[f] = (m[f] || 0) + 1
    }
    return m
  }, [placements, locationId])

  // Filter to the selected room (if provided): keep images explicitly
  // assigned to it; images without a room assignment fall back to the
  // location level and stay visible at the location detail.
  const images = useMemo(
    () =>
      roomFilter
        ? allImages.filter((f) => (rooms[f] || '') === roomFilter)
        : allImages.filter((f) => !rooms[f] || rooms[f] === ''),
    [allImages, rooms, roomFilter],
  )

  const setType = useCallback(
    async (image: string, type: string) => {
      setBusy(image)
      try {
        await apiPost(
          `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(image)}/type`,
          { type },
        )
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    },
    [locationId, reload, t, toast],
  )

  const generateNight = useCallback(
    async (image: string) => {
      setBusy(image)
      try {
        await apiPost(
          `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(image)}/time-variant`,
          { target_type: 'night' },
        )
        toast(t('Night variant queued'))
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    },
    [locationId, reload, t, toast],
  )

  // Build the prompt that pre-fills the dialog. Mirrors the server's
  // resolution order in routes/world.py:generate_gallery_image — room
  // first, then location, falling back to description. The user can
  // edit it before submitting; edits are not persisted.
  const buildDefaultPrompt = useCallback(
    (promptType: string): string => {
      const fromRoom = (key: 'image_prompt_day' | 'image_prompt_night') =>
        (room && (room as Record<string, unknown>)[key]) as string | undefined
      const isMap = promptType === 'map_2d'
      let desc = ''
      if (room && !isMap) {
        if (promptType === 'day') desc = (fromRoom('image_prompt_day') || '').trim()
        else if (promptType === 'night') desc = (fromRoom('image_prompt_night') || '').trim()
        if (!desc) desc = (fromRoom('image_prompt_day') || room.description || '').trim()
      }
      if (!desc && promptType === 'day') desc = (location.image_prompt_day || '').trim()
      if (!desc && promptType === 'night') desc = (location.image_prompt_night || '').trim()
      if (!desc && promptType === 'map_2d') desc = (location.image_prompt_map_2d || '').trim()
      if (!desc) desc = location.description || location.name || ''
      // 2D map icon: subject only. The style suffix is admin-managed (Server Admin →
      // Image Generation) and appended server-side, so it isn't duplicated here.
      if (isMap) {
        return desc
      }
      return `${desc}, wide angle establishing shot, no people, atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio`
    },
    [location, room],
  )

  // Submit handler the dialog calls on Generate. Truly fire-and-forget —
  // the function returns immediately so ImageGenDialog can close right
  // away. The POST + reload run on a detached promise. Errors land in
  // the toast bus, not on the dialog (which is already gone).
  const submitGenerate = useCallback(
    async (payload: ImageGenSubmit) => {
      if (!dialogType) return
      const body: Record<string, unknown> = {
        prompt_type: dialogType,
        prompt: payload.prompt,
      }
      if (roomFilter && dialogType !== 'map_2d') body.room_id = roomFilter
      if (payload.backend) body.backend = payload.backend
      if (payload.loras) body.loras = payload.loras
      // The dialog already has the map-icon suffix in the prompt → don't duplicate it server-side.
      if (payload.prompt_settings_applied) body.settings_applied = true

      // Detached: do NOT await. handleSubmit will see a resolved Promise
      // immediately and trigger onClose() in the next microtask.
      void apiPost(
        `/world/locations/${encodeURIComponent(locationId)}/gallery`,
        body,
      )
        // No auto-refresh: the periodic reloads are disruptive when editing
        // something else in parallel. The new image appears on the next gallery reload.
        .then(() => toast(t('Image queued')))
        .catch((e) => {
          toast(t('Error') + ': ' + (e as Error).message, 'error')
        })
    },
    [dialogType, locationId, roomFilter, t, toast],
  )

  // Regenerate an existing map image — using itself as the reference.
  // Always lands as a NEW gallery image (selectable per cell).
  const submitRegenRef = useCallback(
    async (payload: ImageGenSubmit, target: { filename: string; type: string }) => {
      const body: Record<string, unknown> = {
        prompt_type: target.type,
        prompt: payload.prompt,
        reference_image: target.filename,
      }
      if (payload.backend) body.backend = payload.backend
      if (payload.loras) body.loras = payload.loras
      if (payload.prompt_settings_applied) body.settings_applied = true
      // Regenerate with the existing image as its own reference.
      if (payload.use_source_as_reference) body.use_source_as_reference = true
      // Checkbox off: replace the existing image in place instead of creating a new one.
      if (payload.create_new === false) body.replace_source = true
      // Optional "what do you want to change" request → the server rewrites the prompt
      // via LLM (same enhance_prompt function as Character/Instagram).
      if (payload.improvement_request) body.improvement_request = payload.improvement_request
      void apiPost(`/world/locations/${encodeURIComponent(locationId)}/gallery`, body)
        .then(() => toast(t('Image queued')))
        .catch((e) => { toast(t('Error') + ': ' + (e as Error).message, 'error') })
    },
    [locationId, t, toast],
  )

  const remove = useCallback(
    async (image: string) => {
      if (!window.confirm(t('Delete image "{name}"?').replace('{name}', image))) return
      setBusy(image)
      try {
        await apiDelete(
          `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(image)}`,
        )
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    },
    [locationId, reload, t, toast],
  )

  // Upload a background image for this location (optionally a room, when roomFilter
  // is set) instead of generating one.
  const uploadRef = useRef<HTMLInputElement>(null)
  const uploadBg = useCallback(async (file: File) => {
    if (!file) return
    setBusy('upload')
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (roomFilter) fd.append('room_id', roomFilter)
      await fetch(`/world/locations/${encodeURIComponent(locationId)}/background/upload`, {
        method: 'POST', body: fd, credentials: 'same-origin',
      })
      await reload()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(null)
    }
  }, [locationId, roomFilter, reload, t, toast])

  // Stable handler for opening the "move image" flow (keeps GalleryCard memoized).
  const startMove = useCallback((image: string) => {
    setMoveImage(image)
    setMoveTarget('')
  }, [])

  const generatePanel = (
    <div className="ga-gallery-generate">
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => setDialogType('day')}
        title={t('Open the image generation dialog with the day prompt.')}
      >
        ☀️ {t('Generate day')}
      </button>
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => setDialogType('night')}
        title={t('Open the image generation dialog with the night prompt.')}
      >
        🌙 {t('Generate night')}
      </button>
      {!roomFilter ? (
        <button
          className="ga-btn ga-btn-sm"
          disabled={!!busy}
          onClick={() => setDialogType('map_2d')}
          title={t('Open the image generation dialog for the flat 2D map icon.')}
        >
          🟦 {t('Generate 2D icon')}
        </button>
      ) : null}
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => uploadRef.current?.click()}
        title={roomFilter ? t('Upload a background image for this room.') : t('Upload a background image for this place.')}
      >
        ⬆ {t('Upload')}
      </button>
      <input
        ref={uploadRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadBg(f); e.target.value = '' }}
      />
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => { void reload() }}
        title={t('Reload the gallery (show newly generated images)')}
      >
        🔄 {t('Refresh')}
      </button>
    </div>
  )

  const dialog = dialogType ? (
    <ImageGenDialog
      open
      title={
        dialogType === 'day'
          ? t('Generate day image — {name}').replace('{name}', room?.name || location.name)
          : dialogType === 'night'
            ? t('Generate night image — {name}').replace('{name}', room?.name || location.name)
            : t('Generate 2D map icon — {name}').replace('{name}', location.name)
      }
      defaultPrompt={buildDefaultPrompt(dialogType)}
      hideNegative
      settingsSuffix={
        dialogType === 'map_2d' && mapSuffix.map_2d
          ? { label: t('2D map icon'), text: mapSuffix.map_2d }
          : undefined
      }
      onSubmit={submitGenerate}
      onClose={() => setDialogType(null)}
    />
  ) : null

  const regenDialog = regenTarget ? (
    <ImageGenDialog
      open
      title={t('Adjust image — {name}').replace('{name}', room?.name || location.name)}
      mode="regenerate"
      defaultPrompt={buildDefaultPrompt(regenTarget.type)}
      hideNegative
      sourceImageUrl={`/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(regenTarget.filename)}`}
      defaultUseSource
      requireSourceReference
      defaultCreateNew
      settingsSuffix={
        regenTarget.type === 'map_2d' && mapSuffix.map_2d
          ? { label: t('2D map icon'), text: mapSuffix.map_2d }
          : undefined
      }
      onSubmit={(payload) => submitRegenRef(payload, regenTarget)}
      onClose={() => setRegenTarget(null)}
    />
  ) : null

  if (!data) return <div className="ga-loading">{t('Loading…')}</div>
  if (!images.length) {
    return (
      <>
        {generatePanel}
        {dialog}
        {regenDialog}
        <div className="ga-form-hint" style={{ padding: 8 }}>
          {roomFilter
            ? t('No gallery images for this room yet.')
            : t('No gallery images yet.')}
        </div>
      </>
    )
  }

  return (
    <>
      {generatePanel}
      {dialog}
      {regenDialog}
      <div className="ga-form-section-label">
        {t('Gallery')} ({images.length})
      </div>
      <div className="ga-gallery-list">
        {images.map((filename) => {
          const meta = metas[filename] || {}
          const type = types[filename] || ''
          const url = `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(filename)}`
          const isBusy = busy === filename
          return (
            <GalleryCard
              key={filename}
              filename={filename}
              url={url}
              type={type}
              meta={meta}
              isBusy={isBusy}
              mapUsage={mapUsage[filename] || 0}
              onZoom={setZoom}
              onSetType={setType}
              onGenerateNight={generateNight}
              onRegen={setRegenTarget}
              onMove={startMove}
              onRemove={remove}
            />
          )
        })}
      </div>

      {zoom ? (
        <div className="ga-gallery-lightbox" onClick={() => setZoom(null)} role="dialog">
          <img src={zoom} alt="" />
          <button
            type="button"
            className="ga-gallery-lightbox-close"
            onClick={() => setZoom(null)}
            aria-label={t('Close')}
          >
            ×
          </button>
        </div>
      ) : null}

      {moveImage ? (
        <div className="ga-modal-backdrop" onMouseDown={() => setMoveImage(null)}>
          <div className="ga-modal" style={{ maxWidth: 460 }} onMouseDown={(e) => e.stopPropagation()}>
            <div className="ga-modal-header">
              <span>{t('Move image to…')}</span>
              <button className="ga-modal-close" onClick={() => setMoveImage(null)}>×</button>
            </div>
            <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <img
                src={`/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(moveImage)}`}
                alt=""
                style={{ display: 'block', width: '100%', maxHeight: 220, objectFit: 'contain', borderRadius: 6, background: 'var(--bg, #0d1117)' }}
              />
              <label style={{ fontSize: '0.85em' }}>
                {t('Target location')}
                <select
                  className="ga-input"
                  value={moveTarget}
                  onChange={(e) => setMoveTarget(e.target.value)}
                  style={{ width: '100%', marginTop: 4 }}
                >
                  <option value="">— {t('select')} —</option>
                  {allLocations.filter((l) => l.id !== locationId).map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="ga-btn" onClick={() => setMoveImage(null)}>{t('Cancel')}</button>
              <button className="ga-btn ga-btn-primary" disabled={!moveTarget} onClick={submitMove}>
                {t('Move')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
