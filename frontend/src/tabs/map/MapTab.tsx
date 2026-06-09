import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ExportButton, ImportButton } from '../../components/ImportExport'

/**
 * Map tab — replaces the placement UI that used to live on the main
 * worldmap. The list-detail layout matches the other tabs: a tray on
 * the left with unplaced + passable templates, a 2D grid on the right
 * where locations are dropped onto cells.
 *
 * Drag payloads:
 *   "tmpl:<id>"  – passable template, drop on grid → POST clone at (x,y)
 *   "loc:<id>"   – existing location, drop on grid → PATCH position
 *                  (drop on tray → PATCH to (-1,-1) or DELETE if clone)
 */

interface Location {
  id: string
  name: string
  passable?: boolean
  is_template?: boolean
  template_location_id?: string
  grid_x?: number | null
  grid_y?: number | null
  map_z_offset?: number
  map_image?: string
  map_image_2d?: string
  map_rotation_2d?: number
}

interface GalleryResp {
  images?: string[]
  image_types?: Record<string, string>
}

const COLS = 10
const ROWS = 10
const CELL = 88

// Flat 2D map icon with fallback to the iso icon, then hide. The Map tab is a
// flat grid, so the 2D icons are the natural fit. `cacheKey` lets a caller force
// a reload after the per-cell image was changed.
function MapIcon({ locId, className, cacheKey, rotation }: { locId: string; className: string; cacheKey?: string; rotation?: number }) {
  const [stage, setStage] = useState(0) // 0 = 2D, 1 = iso, 2 = hidden
  useEffect(() => { setStage(0) }, [cacheKey, locId])
  if (stage >= 2) return null
  const base = stage === 0
    ? `/world/locations/${encodeURIComponent(locId)}/map-icon-2d`
    : `/world/locations/${encodeURIComponent(locId)}/map-icon`
  const src = cacheKey ? `${base}?v=${encodeURIComponent(cacheKey)}` : base
  // Rotation is a 2D-only display transform; the iso fallback is not rotated.
  const style = stage === 0 && rotation ? { transform: `rotate(${rotation}deg)` } : undefined
  return <img className={className} src={src} alt="" style={style} onError={() => setStage((s) => s + 1)} />
}

export function MapTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [locations, setLocations] = useState<Location[] | null>(null)
  const [dragPayload, setDragPayload] = useState<string | null>(null)
  const [dragOverCell, setDragOverCell] = useState<string | null>(null)
  const [trayDragOver, setTrayDragOver] = useState(false)
  const gridRef = useRef<HTMLDivElement | null>(null)

  // Per-cell image picker: which placed location's picker is open, its gallery,
  // and a per-location cache-buster so the icon reloads after a change.
  const [picker, setPicker] = useState<Location | null>(null)
  const [pickerGallery, setPickerGallery] = useState<GalleryResp | null>(null)
  const [iconVer, setIconVer] = useState<Record<string, number>>({})

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ locations?: Location[] }>('/world/locations')
      setLocations(data.locations || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => {
    reload()
  }, [reload])

  // Clones share their template's gallery — load images from the owner
  // (template_location_id when a clone, else the location itself). The chosen
  // image is stored on the placed location/clone (loc.id) so each cell differs.
  const ownerOf = (loc: Location) => (loc.template_location_id || '').trim() || loc.id

  const openPicker = useCallback(async (loc: Location) => {
    setPicker(loc)
    setPickerGallery(null)
    try {
      const g = await apiGet<GalleryResp>(`/world/locations/${encodeURIComponent(ownerOf(loc))}/gallery`)
      setPickerGallery(g)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setPickerGallery({ images: [], image_types: {} })
    }
  }, [t, toast])

  const chooseImage = useCallback(
    async (loc: Location, type: 'map' | 'map_2d', file: string) => {
      try {
        await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-image`, { type, file })
        setIconVer((v) => ({ ...v, [loc.id]: (v[loc.id] || 0) + 1 }))
        await reload()
        setPicker(null)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  // Rotate the cell's 2D icon by +90° (0→90→180→270→0). Display-only.
  const rotateCell = useCallback(
    async (loc: Location) => {
      const next = ((loc.map_rotation_2d || 0) + 90) % 360
      try {
        await apiPatch(`/world/locations/${encodeURIComponent(loc.id)}/map-rotation`, { rotation: next })
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [reload, t, toast],
  )

  const { placedByCell, unplaced, passableTemplates } = useMemo(() => {
    const byCell = new Map<string, Location>()
    const unp: Location[] = []
    const tmpls: Location[] = []
    for (const loc of locations || []) {
      const isClone = !!(loc.template_location_id || '').trim()
      const isPassableTemplate = !!loc.passable && !isClone
      if (isPassableTemplate) {
        tmpls.push(loc)
        continue
      }
      if (
        loc.grid_x != null &&
        loc.grid_y != null &&
        loc.grid_x >= 0 &&
        loc.grid_y >= 0
      ) {
        byCell.set(`${loc.grid_x},${loc.grid_y}`, loc)
      } else {
        unp.push(loc)
      }
    }
    return { placedByCell: byCell, unplaced: unp, passableTemplates: tmpls }
  }, [locations])

  const onDropOnCell = useCallback(
    async (gridX: number, gridY: number) => {
      const payload = dragPayload
      setDragPayload(null)
      setDragOverCell(null)
      if (!payload) return
      const cellKey = `${gridX},${gridY}`
      const occupant = placedByCell.get(cellKey)
      try {
        if (payload.startsWith('tmpl:')) {
          if (occupant) return
          const templateId = payload.slice(5)
          await apiPost(
            `/world/locations/${encodeURIComponent(templateId)}/clone`,
            { grid_x: gridX, grid_y: gridY },
          )
        } else if (payload.startsWith('loc:')) {
          const locId = payload.slice(4)
          if (occupant && occupant.id !== locId) return
          await apiPatch(
            `/world/locations/${encodeURIComponent(locId)}/position`,
            { grid_x: gridX, grid_y: gridY },
          )
        }
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [dragPayload, placedByCell, reload, t, toast],
  )

  const onDropOnTray = useCallback(async () => {
    const payload = dragPayload
    setDragPayload(null)
    setTrayDragOver(false)
    if (!payload || !payload.startsWith('loc:')) return
    const locId = payload.slice(4)
    const loc = (locations || []).find((l) => l.id === locId)
    if (!loc) return
    const isClone = !!(loc.template_location_id || '').trim()
    try {
      if (isClone) {
        await apiDelete(`/world/locations/${encodeURIComponent(locId)}`)
      } else {
        await apiPatch(
          `/world/locations/${encodeURIComponent(locId)}/position`,
          { grid_x: -1, grid_y: -1 },
        )
      }
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [dragPayload, locations, reload, t, toast])

  const onCellDragOver = useCallback(
    (e: React.DragEvent, gridX: number, gridY: number) => {
      if (!dragPayload) return
      const cellKey = `${gridX},${gridY}`
      const occupant = placedByCell.get(cellKey)
      // Block drop if cell occupied by someone else (template clone target)
      if (dragPayload.startsWith('tmpl:') && occupant) return
      if (dragPayload.startsWith('loc:')) {
        const draggedId = dragPayload.slice(4)
        if (occupant && occupant.id !== draggedId) return
      }
      e.preventDefault()
      e.dataTransfer.dropEffect = dragPayload.startsWith('tmpl:') ? 'copy' : 'move'
      setDragOverCell(cellKey)
    },
    [dragPayload, placedByCell],
  )

  const startDragLoc = useCallback((e: React.DragEvent, loc: Location) => {
    const payload = `loc:${loc.id}`
    e.dataTransfer.setData('text/plain', payload)
    e.dataTransfer.effectAllowed = 'move'
    setDragPayload(payload)
  }, [])

  const startDragTmpl = useCallback((e: React.DragEvent, loc: Location) => {
    const payload = `tmpl:${loc.id}`
    e.dataTransfer.setData('text/plain', payload)
    e.dataTransfer.effectAllowed = 'copy'
    setDragPayload(payload)
  }, [])

  const onTrayDragOver = useCallback(
    (e: React.DragEvent) => {
      if (!dragPayload || !dragPayload.startsWith('loc:')) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      setTrayDragOver(true)
    },
    [dragPayload],
  )

  if (locations == null) {
    return <div className="ga-empty">{t('Loading…')}</div>
  }

  return (
    <div className="ga-map-layout">
      <aside
        className={'ga-map-tray' + (trayDragOver ? ' drag-over' : '')}
        onDragOver={onTrayDragOver}
        onDragLeave={() => setTrayDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          onDropOnTray()
        }}
      >
        <div className="ga-map-tray-section">
          <div
            className="ga-map-tray-title"
            style={{ display: 'flex', alignItems: 'center', gap: 4, justifyContent: 'space-between' }}
          >
            <span>{t('Layout')}</span>
            <span style={{ display: 'flex', gap: 4 }}>
              <ExportButton
                endpoint="/world/map/export"
                filename="map_layout.zip"
                title={t('Download grid positions as a ZIP')}
              />
              <ImportButton
                endpoint="/world/map/import"
                onImported={() => reload()}
                title={t('Apply a saved layout to the current world')}
              />
            </span>
          </div>
        </div>
        <div className="ga-map-tray-section">
          <div className="ga-map-tray-title">{t('Unplaced')}</div>
          {unplaced.length === 0 ? (
            <div className="ga-map-tray-empty">{t('None')}</div>
          ) : (
            <div className="ga-map-tray-items">
              {unplaced.map((loc) => (
                <div
                  key={loc.id}
                  className="ga-map-tray-item"
                  draggable
                  onDragStart={(e) => startDragLoc(e, loc)}
                  onDragEnd={() => setDragPayload(null)}
                  title={loc.name}
                >
                  <MapIcon locId={loc.id} className="ga-map-tray-icon" />
                  <span className="ga-map-tray-name">{loc.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ga-map-tray-section">
          <div className="ga-map-tray-title">{t('Passable templates')}</div>
          {passableTemplates.length === 0 ? (
            <div className="ga-map-tray-empty">{t('None')}</div>
          ) : (
            <div className="ga-map-tray-items">
              {passableTemplates.map((loc) => (
                <div
                  key={loc.id}
                  className="ga-map-tray-item ga-map-tray-template"
                  draggable
                  onDragStart={(e) => startDragTmpl(e, loc)}
                  onDragEnd={() => setDragPayload(null)}
                  title={t('Drag onto map to place a copy')}
                >
                  <MapIcon locId={loc.id} className="ga-map-tray-icon" />
                  <span className="ga-map-tray-name">{loc.name}</span>
                  <span className="ga-map-tray-stamp">∞</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ga-map-tray-hint">
          {t('Drop a placed location here to remove it from the grid.')}
        </div>
      </aside>

      <div className="ga-map-grid-wrap" ref={gridRef}>
        <div
          className="ga-map-grid"
          style={{
            gridTemplateColumns: `repeat(${COLS}, ${CELL}px)`,
            gridTemplateRows: `repeat(${ROWS}, ${CELL}px)`,
          }}
        >
          {Array.from({ length: ROWS }).map((_, y) =>
            Array.from({ length: COLS }).map((__, x) => {
              const cellKey = `${x},${y}`
              const loc = placedByCell.get(cellKey)
              const isClone = !!(loc && (loc.template_location_id || '').trim())
              const dragOver = dragOverCell === cellKey
              const cls = [
                'ga-map-cell',
                loc ? 'occupied' : '',
                loc?.passable ? 'passable' : '',
                isClone ? 'clone' : '',
                dragOver ? 'drag-over' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <div
                  key={cellKey}
                  className={cls}
                  onDragOver={(e) => onCellDragOver(e, x, y)}
                  onDragLeave={() => {
                    if (dragOverCell === cellKey) setDragOverCell(null)
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    onDropOnCell(x, y)
                  }}
                >
                  {loc ? (
                    <div
                      className="ga-map-tile"
                      draggable
                      onDragStart={(e) => startDragLoc(e, loc)}
                      onDragEnd={() => setDragPayload(null)}
                      title={loc.name + (isClone ? ' (' + t('copy') + ')' : '')}
                    >
                      <MapIcon locId={loc.id} className="ga-map-tile-bg" cacheKey={String(iconVer[loc.id] || 0)} rotation={loc.map_rotation_2d || 0} />
                      <span className="ga-map-tile-name">{loc.name}</span>
                      <button
                        type="button"
                        className="ga-map-tile-rotbtn"
                        title={t('Rotate the 2D icon 90°')}
                        draggable={false}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          rotateCell(loc)
                        }}
                      >
                        ↻
                      </button>
                      <button
                        type="button"
                        className="ga-map-tile-imgbtn"
                        title={t('Choose which image this cell shows')}
                        draggable={false}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation()
                          openPicker(loc)
                        }}
                      >
                        🖼
                      </button>
                    </div>
                  ) : (
                    <span className="ga-map-cell-coord">
                      {x},{y}
                    </span>
                  )}
                </div>
              )
            }),
          )}
        </div>
      </div>

      {picker ? (
        <div className="ga-modal-backdrop" onMouseDown={() => setPicker(null)}>
          <div className="ga-modal ga-map-imgpicker" onMouseDown={(e) => e.stopPropagation()}>
            <div className="ga-modal-header">
              <span>{t('Cell image')} — {picker.name}</span>
              <button className="ga-modal-close" onClick={() => setPicker(null)}>×</button>
            </div>
            <div className="ga-modal-body">
              {pickerGallery == null ? (
                <div className="ga-empty">{t('Loading…')}</div>
              ) : (
                ([
                  { type: 'map_2d' as const, label: t('2D icon'), chosen: picker.map_image_2d || '' },
                  { type: 'map' as const, label: t('Isometric icon'), chosen: picker.map_image || '' },
                ]).map(({ type, label, chosen }) => {
                  const imgs = (pickerGallery.images || []).filter(
                    (f) => (pickerGallery.image_types || {})[f] === type,
                  )
                  return (
                    <div key={type} className="ga-map-imgpicker-group">
                      <div className="ga-map-imgpicker-label">{label}</div>
                      {imgs.length === 0 ? (
                        <div className="ga-map-tray-empty">{t('No images of this type.')}</div>
                      ) : (
                        <div className="ga-map-imgpicker-grid">
                          <button
                            type="button"
                            className={'ga-map-imgpicker-item ga-map-imgpicker-none' + (chosen ? '' : ' selected')}
                            title={t('Default (first match)')}
                            onClick={() => chooseImage(picker, type, '')}
                          >
                            {t('Auto')}
                          </button>
                          {imgs.map((f) => (
                            <button
                              key={f}
                              type="button"
                              className={'ga-map-imgpicker-item' + (chosen === f ? ' selected' : '')}
                              onClick={() => chooseImage(picker, type, f)}
                              title={f}
                            >
                              <img
                                src={`/world/locations/${encodeURIComponent(ownerOf(picker))}/gallery/${encodeURIComponent(f)}`}
                                alt=""
                              />
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
