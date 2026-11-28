import { FIGURE_HEIGHT_M } from '@anima/scene-render'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from '../characters/Model3DViewer'
import type { Item } from './itemsModel'

interface MeshStatus {
  status: 'none' | 'running' | 'done' | 'failed'
  error?: string
  version?: string
  bbox?: number[]
  copied_from?: string
  backend?: string
  tris?: number
  face_num?: number
  tris_delivered?: number
  reduced_from?: number
  reduce_error?: string
}

interface ReduceResponse {
  status: 'queued' | 'unchanged'
  tris?: number
}

interface CopyCandidate {
  id: string
  name: string
}

const DEFAULT_WORLD_SIZE_M = 0.25
const DEFAULT_FACE_NUM = 20000
const MIN_FACE_NUM = 500
const MAX_FACE_NUM = 200000
const REDUCE_TOLERANCE = 1.05
const POLL_INTERVAL_MS = 2000

function bboxDimensions(bbox?: number[]): [number, number, number] | null {
  if (!bbox || bbox.length < 6) return null
  const dx = Math.abs(bbox[3] - bbox[0])
  const dy = Math.abs(bbox[4] - bbox[1])
  const dz = Math.abs(bbox[5] - bbox[2])
  if (!Number.isFinite(dx) || !Number.isFinite(dy) || !Number.isFinite(dz)) return null
  return [dx, dy, dz]
}

export function ItemMeshTab({ item, onSaved }: { item: Item; onSaved: () => void }) {
  const { t } = useI18n()
  const { toast } = useToast()

  const [placeable, setPlaceable] = useState(Boolean(item.world_placeable))
  const [sizeText, setSizeText] = useState(
    item.world_size_m != null && item.world_size_m > 0 ? String(item.world_size_m) : '',
  )
  const [saving, setSaving] = useState(false)

  const [meshStatus, setMeshStatus] = useState<MeshStatus | null>(null)
  const [faceCountText, setFaceCountText] = useState(String(DEFAULT_FACE_NUM))
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerLoading, setPickerLoading] = useState(false)
  const [candidates, setCandidates] = useState<CopyCandidate[]>([])

  const [viewerBounds, setViewerBounds] = useState<[number, number, number] | null>(null)
  const [showRefFigure, setShowRefFigure] = useState(true)

  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    setPlaceable(Boolean(item.world_placeable))
    setSizeText(item.world_size_m != null && item.world_size_m > 0 ? String(item.world_size_m) : '')
    setConfirmDelete(false)
    setPickerOpen(false)
    setViewerBounds(null)
  }, [item.id, item.world_placeable, item.world_size_m])

  const loadStatus = useCallback(async () => {
    try {
      const st = await apiGet<MeshStatus>(`/inventory/items/${encodeURIComponent(item.id)}/mesh/status`)
      if (mountedRef.current) setMeshStatus(st)
    } catch (e) {
      if (mountedRef.current) toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [item.id, t, toast])

  useEffect(() => {
    setMeshStatus(null)
    void loadStatus()
  }, [loadStatus])

  const isRunning = meshStatus?.status === 'running'
  useEffect(() => {
    if (!isRunning) return
    const timer = window.setInterval(() => {
      void loadStatus()
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [isRunning, loadStatus])

  const saveFields = useCallback(async () => {
    setSaving(true)
    try {
      const trimmed = sizeText.trim()
      let worldSize: number | null = null
      if (trimmed !== '') {
        const parsed = Number(trimmed)
        if (Number.isFinite(parsed) && parsed > 0) {
          worldSize = Math.min(5, parsed)
        }
      }
      await apiPut(`/inventory/items/${encodeURIComponent(item.id)}`, {
        world_placeable: placeable,
        world_size_m: worldSize,
      })
      toast(t('Saved'))
      onSaved()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }, [item.id, onSaved, placeable, sizeText, t, toast])

  const parsedFaceCount = Number(faceCountText.trim())
  const faceNum =
    faceCountText.trim() !== '' && Number.isFinite(parsedFaceCount)
      ? Math.min(MAX_FACE_NUM, Math.max(MIN_FACE_NUM, Math.round(parsedFaceCount)))
      : DEFAULT_FACE_NUM

  const startGenerate = useCallback(async () => {
    setBusy(true)
    setConfirmDelete(false)
    try {
      await apiPost(`/inventory/items/${encodeURIComponent(item.id)}/mesh/generate`, {
        face_num: faceNum,
      })
      toast(t('Mesh queued'))
      await loadStatus()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      if (mountedRef.current) setBusy(false)
    }
  }, [faceNum, item.id, loadStatus, t, toast])

  const startReduce = useCallback(async () => {
    setBusy(true)
    setConfirmDelete(false)
    try {
      const res = await apiPost<ReduceResponse>(
        `/inventory/items/${encodeURIComponent(item.id)}/mesh/reduce`,
        { face_num: faceNum },
      )
      if (res?.status === 'unchanged') {
        toast(t('Already at or below {n} faces').replace('{n}', faceNum.toLocaleString()))
      } else {
        toast(t('Reduction queued'))
      }
      await loadStatus()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      if (mountedRef.current) setBusy(false)
    }
  }, [faceNum, item.id, loadStatus, t, toast])

  const openCopyPicker = useCallback(async () => {
    if (pickerOpen) {
      setPickerOpen(false)
      return
    }
    setPickerOpen(true)
    setPickerLoading(true)
    setCandidates([])
    try {
      const data = await apiGet<{ items?: Item[] }>('/inventory/items?include_shared=1')
      const others = (data.items || [])
        .filter((it) => it.id !== item.id && (it.image || it.world_placeable))
        .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))
      const found: CopyCandidate[] = []
      const batchSize = 6
      for (let i = 0; i < others.length; i += batchSize) {
        if (!mountedRef.current) return
        const slice = others.slice(i, i + batchSize)
        const results = await Promise.all(
          slice.map(async (it) => {
            try {
              const meta = await apiGet<MeshStatus>(
                `/inventory/items/${encodeURIComponent(it.id)}/model/meta`,
              )
              return meta && meta.version ? { id: it.id, name: it.name || it.id } : null
            } catch {
              return null
            }
          }),
        )
        for (const r of results) {
          if (r) found.push(r)
        }
      }
      if (mountedRef.current) setCandidates(found)
    } catch (e) {
      if (mountedRef.current) toast((e as Error).message, 'error')
    } finally {
      if (mountedRef.current) setPickerLoading(false)
    }
  }, [item.id, pickerOpen, toast])

  const copyFromItem = useCallback(async (fromItemId: string) => {
    setBusy(true)
    setConfirmDelete(false)
    try {
      await apiPost(`/inventory/items/${encodeURIComponent(item.id)}/mesh/copy`, {
        from_item_id: fromItemId,
      })
      toast(t('Mesh copied'))
      setPickerOpen(false)
      await loadStatus()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      if (mountedRef.current) setBusy(false)
    }
  }, [item.id, loadStatus, t, toast])

  const deleteMesh = useCallback(async () => {
    setBusy(true)
    try {
      await apiDelete(`/inventory/items/${encodeURIComponent(item.id)}/mesh`)
      toast(t('Mesh deleted'))
      setConfirmDelete(false)
      setViewerBounds(null)
      await loadStatus()
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      if (mountedRef.current) setBusy(false)
    }
  }, [item.id, loadStatus, t, toast])

  const hasImage = Boolean(item.image)
  const hasMesh = Boolean(meshStatus?.version)
  const canPreview = meshStatus?.status === 'done' && Boolean(meshStatus.version)
  const canReduce =
    hasMesh && typeof meshStatus?.tris === 'number' && meshStatus.tris > faceNum * REDUCE_TOLERANCE

  const parsedSize = Number(sizeText.trim())
  const effectiveSizeM =
    sizeText.trim() !== '' && Number.isFinite(parsedSize) && parsedSize > 0
      ? Math.min(5, parsedSize)
      : (item.world_size_m && item.world_size_m > 0 ? item.world_size_m : DEFAULT_WORLD_SIZE_M)

  const bboxSize = viewerBounds ?? bboxDimensions(meshStatus?.bbox)
  const maxEdge = bboxSize ? Math.max(bboxSize[0], bboxSize[1], bboxSize[2]) : 0
  const figureHeight = maxEdge > 0 && effectiveSizeM > 0 ? (FIGURE_HEIGHT_M * maxEdge) / effectiveSizeM : 0

  const statusText = (() => {
    if (!meshStatus || meshStatus.status === 'none') return t('No mesh yet')
    if (meshStatus.status === 'running') return t('Generating mesh…')
    if (meshStatus.status === 'failed') {
      return meshStatus.error
        ? `${t('Mesh generation failed')}: ${meshStatus.error}`
        : t('Mesh generation failed')
    }
    const parts = [t('Mesh ready')]
    if (typeof meshStatus.tris === 'number' && meshStatus.tris > 0) {
      parts.push(t('{n} faces').replace('{n}', meshStatus.tris.toLocaleString()))
    }
    if (meshStatus.backend) parts.push(meshStatus.backend)
    if (meshStatus.copied_from) {
      parts.push(t('Copied from {id}').replace('{id}', meshStatus.copied_from))
    }
    return parts.join(' · ')
  })()

  return (
    <div className="ga-form" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="ga-section">
        <div className="ga-form-section-label">{t('World placement')}</div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 260px))',
            gap: 12,
            alignItems: 'start',
          }}
        >
          <Field label={t('Placeable in the world')}>
            <label className="ga-form-check" style={{ marginTop: 6 }}>
              <input
                type="checkbox"
                checked={placeable}
                onChange={(e) => setPlaceable(e.target.checked)}
              />
              {t('Placeable in the world')}
            </label>
          </Field>
          <Field
            label={t('Size — longest edge (m)')}
            hint={t('Default 0.25 m. A key is about 0.08 m, a book 0.25 m, a chair 0.9 m, a person 1.70 m.')}
          >
            <input
              className="ga-input"
              type="number"
              step={0.01}
              min={0.01}
              max={5}
              placeholder="0.25"
              style={{ maxWidth: 140 }}
              value={sizeText}
              onChange={(e) => setSizeText(e.target.value)}
            />
          </Field>
        </div>
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={saving}
            onClick={() => { void saveFields() }}
          >
            {saving ? t('Saving…') : t('Save')}
          </button>
        </div>
      </div>

      <div className="ga-section">
        <div className="ga-form-section-label">{t('3D mesh')}</div>
        <div className="ga-form-hint" role="status" style={{ marginBottom: 8 }}>
          {statusText}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span className="ga-form-hint">{t('Face count')}</span>
            <input
              className="ga-input"
              type="number"
              min={MIN_FACE_NUM}
              max={MAX_FACE_NUM}
              step={1000}
              style={{ width: 110 }}
              disabled={isRunning || busy}
              value={faceCountText}
              onChange={(e) => setFaceCountText(e.target.value)}
              onBlur={() => setFaceCountText(String(faceNum))}
            />
          </label>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={!hasImage || isRunning || busy}
            onClick={() => { void startGenerate() }}
          >
            {hasMesh ? t('Regenerate mesh') : t('Generate mesh')}
          </button>
          {canReduce ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={isRunning || busy}
              onClick={() => { void startReduce() }}
            >
              {t('Reduce to {n} faces').replace('{n}', faceNum.toLocaleString())}
            </button>
          ) : null}
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={isRunning || busy}
            onClick={() => { void openCopyPicker() }}
          >
            {t('Use mesh of another item')}
          </button>
          {hasMesh ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              disabled={isRunning || busy}
              onClick={() => setConfirmDelete(true)}
            >
              {t('Delete mesh')}
            </button>
          ) : null}
        </div>
        {!hasImage ? (
          <div className="ga-form-hint" style={{ marginTop: 6 }}>
            {t('Generate the item image first')}
          </div>
        ) : null}

        {confirmDelete ? (
          <div
            className="ga-form-row"
            role="alert"
            style={{ marginTop: 10, gap: 8, alignItems: 'center' }}
          >
            <span>{t('Delete mesh?')}</span>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              disabled={busy}
              onClick={() => { void deleteMesh() }}
            >
              {t('Confirm')}
            </button>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={busy}
              onClick={() => setConfirmDelete(false)}
            >
              {t('Cancel')}
            </button>
          </div>
        ) : null}

        {pickerOpen ? (
          <div
            style={{
              marginTop: 10,
              padding: 10,
              border: '1px solid var(--ga-border, #30363d)',
              borderRadius: 6,
              maxWidth: 420,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <strong>{t('Use mesh of another item')}</strong>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => setPickerOpen(false)}
              >
                {t('Close')}
              </button>
            </div>
            {pickerLoading ? (
              <div className="ga-form-hint">{t('Checking available meshes…')}</div>
            ) : candidates.length === 0 ? (
              <div className="ga-form-hint">{t('No other items with a mesh found.')}</div>
            ) : (
              <ul className="ga-list" style={{ maxHeight: 200, overflowY: 'auto', margin: 0 }}>
                {candidates.map((cand) => (
                  <li key={cand.id}>
                    <button
                      type="button"
                      className="ga-list-row"
                      disabled={busy}
                      onClick={() => { void copyFromItem(cand.id) }}
                    >
                      <span className="ga-list-row-main">
                        <strong>{cand.name}</strong>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>

      {canPreview && meshStatus?.version ? (
        <div className="ga-section">
          <div className="ga-form-section-label">{t('3D preview')}</div>
          <Model3DViewer
            url={`/inventory/items/${encodeURIComponent(item.id)}/model?v=${encodeURIComponent(meshStatus.version)}`}
            format="glb"
            height={360}
            onBounds={(b) => setViewerBounds(b.size)}
            figureHeight={figureHeight}
            scaleFigure={showRefFigure && figureHeight > 0}
          />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginTop: 6 }}>
            <label
              className="ga-hint"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}
            >
              <input
                type="checkbox"
                checked={showRefFigure}
                onChange={(e) => setShowRefFigure(e.target.checked)}
              />
              {t('Reference figure (1.70 m)')}
            </label>
            {bboxSize ? (
              <span className="ga-hint">
                {t('Longest edge in the world: {size} m (mesh bbox: {x} × {y} × {z})')
                  .replace('{size}', effectiveSizeM.toFixed(2))
                  .replace('{x}', bboxSize[0].toFixed(2))
                  .replace('{y}', bboxSize[1].toFixed(2))
                  .replace('{z}', bboxSize[2].toFixed(2))}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
