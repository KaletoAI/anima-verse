/**
 * FaceSettings — the face settings of the model the face steps act on, saved ON THEIR OWN (Task UI1, rule R3:
 * "a setting is editable and saved without running anything"). The Base body tab's Settings section on the
 * pipeline; ModelFaceActions renders it inline elsewhere (the 3D tab of a temporary NPC).
 *
 * - "Face cleanup before the face retexture" and "Improve face before rigging" — the two switches, each saved at
 *   once (POST /characters/{n}/model3d/options {face_cleanup | face_before_rig}). Switching the cleanup on while
 *   the stored mesh is not cleaned, or "Improve face" on while the stored model has no face retexture, makes that
 *   step due: the Base body tab's "Run all" picks it up (`figure_build.base_run_all`).
 * - The face retexture values — light balance, skin tone match, skin colour correction, face brightness
 *   (`face_photo`) and strength, feather, render resolution, yaw (`face_controls`) — with Save
 *   (POST …/model3d/options {face_photo, face_controls}); only deviations from the defaults are stored. Until
 *   now they could only be set inside the "Face retexture…" dialog, i.e. while running it. A run without the
 *   dialog's values (the face step of a new model, Run all, the Improvements queue) uses the saved ones; the
 *   dialog starts from them.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { Model3DStatus } from './FieldModel3D'
import {
  FACE_CONTROL_DEFAULTS, FACE_PHOTO_DEFAULTS, FACE_SETTINGS_NOTE, faceControlsOf, facePhotoOf, faceSettingsChanged,
  faceSettingsInvalid,
} from './baseBodyModel'
import type { FaceControls, FacePhoto } from './baseBodyModel'

export function FaceSettings({ character, st, pending, onReload }: {
  character: string
  /** GET …/model3d — its `options` hold the saved values. */
  st: Model3DStatus
  /** A model run goes: the switches wait (they decide the next run). */
  pending: boolean
  /** Re-read the status after a save. */
  onReload: () => Promise<unknown> | void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const humanoid = !st.rig || st.rig === 'mixamo'
  const pipeline = !!st.pipeline
  const saved = useMemo(() => ({
    photo: facePhotoOf(st.options?.face_photo as Partial<FacePhoto> | undefined),
    controls: faceControlsOf(st.options?.face_controls as Partial<FaceControls> | undefined),
  }), [st.options?.face_photo, st.options?.face_controls])
  const [photo, setPhoto] = useState<FacePhoto>(saved.photo)
  const [controls, setControls] = useState<FaceControls>(saved.controls)
  const [saving, setSaving] = useState(false)
  // A reload (or another tab's save) replaces the draft with what is stored.
  useEffect(() => { setPhoto(saved.photo); setControls(saved.controls) }, [saved])

  const setOption = useCallback(async (key: 'face_before_rig' | 'face_cleanup', value: boolean) => {
    try {
      await apiPost(`/characters/${enc}/model3d/options`, { [key]: value })
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    await onReload()
  }, [enc, onReload, t, toast])

  const invalid = faceSettingsInvalid(photo, controls)
  const changed = faceSettingsChanged(saved, { photo, controls })
  const save = useCallback(async () => {
    if (saving || invalid) return
    setSaving(true)
    try {
      await apiPost(`/characters/${enc}/model3d/options`, { face_photo: photo, face_controls: controls })
      toast(t('Saved'))
      await onReload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [controls, enc, invalid, onReload, photo, saving, t, toast])

  const pct = (v: number) => `${Math.round(v * 100)} %`
  const slider = (key: keyof FacePhoto, label: string, tip: string, lo: number, hi: number) => (
    <Field label={`${t(label)} ${pct(photo[key])}`} tip={t(tip)}>
      <input type="range" min={lo} max={hi} step={5} value={Math.round(photo[key] * 100)} disabled={saving || !humanoid}
        onChange={(e) => { const v = e.target.valueAsNumber / 100; setPhoto((p) => ({ ...p, [key]: v })) }} />
    </Field>
  )
  const number = (key: keyof FaceControls, label: string, tip: string, lo: number, hi: number, step: number) => (
    <Field label={t(label)} compact tip={t(tip)}>
      <input className="ga-input" style={{ width: 90 }} type="number" min={lo} max={hi} step={step}
        value={controls[key]} disabled={saving || !humanoid}
        onChange={(e) => { const v = e.target.valueAsNumber; setControls((c) => ({ ...c, [key]: v })) }} />
    </Field>
  )

  return (
    <div className="ga-face-settings" role="group" aria-label={t('Face settings')}
      style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label className="ga-check-row"
        title={!humanoid ? t('Humanoid models only.')
          : t('Before the face retexture, lash flaps the mesher built from painted lashes are folded back onto their root (the eyeball, lids and sockets stay) and over-saturated lips in the raw texture are neutralised. Recorded in the model overview as "Face cleanup". Humanoid models only.')}>
        <input type="checkbox" checked={!!st.options?.face_cleanup} disabled={!humanoid || pending}
          onChange={(e) => { void setOption('face_cleanup', e.target.checked) }} />
        <span>{t('Face cleanup before the face retexture (lashes, lips)')}</span>
      </label>
      <label className="ga-check-row"
        title={!humanoid ? t('Humanoid models only.')
          : pipeline ? t('The base body model gets the face correction (upscaler + face retexture) before its first rig; outfit models take the face from it.')
          : t('New meshes get the face correction (upscaler + face retexture) before the first rig, so the rigger runs once. Independent of auto-generate. Humanoid models only.')}>
        <input type="checkbox" checked={!!st.options?.face_before_rig} disabled={!humanoid || pending}
          onChange={(e) => { void setOption('face_before_rig', e.target.checked) }} />
        <span>{t('Improve face before rigging')}</span>
      </label>
      <details>
        <summary style={{ cursor: 'pointer' }}>{t('Face retexture values')}{changed ? ` · ${t('not saved')}` : ''}</summary>
        <div className="ga-form" style={{ marginTop: 6 }}>
          {slider('balance', 'Light balance', 'Removes broad light from the face photo: side light and, on the hub (GLBFaceRetexture 1.2), the darker face edges that show as a shadow along the projection border. Features stay; nothing is mirrored.', 0, 100)}
          {slider('tone_match', 'Skin tone match', "Pulls the face's overall skin colour and brightness toward the model's own face skin, so the projection blends in without a seam. Runs on the hub (needs GLBFaceRetexture 1.1.1).", 0, 100)}
          {slider('skin_recolor', 'Skin colour correction', "Recolours the model's own skin (face, neck, arms, hands) toward the photo's skin tone — for meshes that came out too red. Clothes and hair stay. Runs on the hub (needs GLBFaceRetexture 1.3).", 0, 100)}
          {slider('brightness', 'Face brightness', "Scales the photo's brightness before projection — lower it when the face looks too bright on the model.", 50, 150)}
          <div className="ga-form-row">
            {number('strength', 'Strength', 'How strongly the photo replaces the face texture (0–1).', 0, 1, 0.05)}
            {number('feather', 'Feather', 'Width of the soft blend at the edge of the face (0–0.5).', 0, 0.5, 0.01)}
            {number('render_resolution', 'Render resolution', 'Resolution of the render used to align the photo with the mesh (256–2048).', 256, 2048, 1)}
            {number('yaw', 'Yaw (degrees)', 'Turns only the alignment view. Leave at 0 unless the model does not face forward (−180–180).', -180, 180, 1)}
          </div>
          <div className="ga-face-actions-row" style={{ alignItems: 'center', gap: 6 }}>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={saving || !changed || !!invalid || !humanoid}
              onClick={() => { void save() }}>{saving ? t('Saving…') : t('Save face values')}</button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={saving || !humanoid}
              title={t('Puts the defaults into the fields — Save stores them')}
              onClick={() => { setPhoto({ ...FACE_PHOTO_DEFAULTS }); setControls({ ...FACE_CONTROL_DEFAULTS }) }}>
              {t('Defaults')}
            </button>
            {changed ? (
              <button type="button" className="ga-btn ga-btn-sm" disabled={saving}
                onClick={() => { setPhoto(saved.photo); setControls(saved.controls) }}>{t('Discard')}</button>
            ) : null}
          </div>
          {invalid ? <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{t(invalid)}</div> : null}
          <div className="ga-hint">{t(FACE_SETTINGS_NOTE)}</div>
        </div>
      </details>
    </div>
  )
}
