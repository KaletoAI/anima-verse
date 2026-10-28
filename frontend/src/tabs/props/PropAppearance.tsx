import { Field } from '@anima/player-ui'
import { PropAreasPanel } from './PropAreasPanel'
import { WaterPanel } from './WaterPanel'
import { LIGHT_PRESETS } from './usePropWorkspace'
import type { PropLight } from './propTypes'
import type { PropWorkspace } from './usePropWorkspace'

export function PropAppearance({ workspace }: { workspace: PropWorkspace }) {
  const { shownVariant, t, lightPreset, setPlacing, queueVariant, variant, light,
    editLight, placing, shownHasMesh, previewFile, drawKind, armPlacing,
    variants, waterController, setDrawKind, prop, serverVariants, variantMax,
    reloadKey, variantAreas, areasFailed, areaTools, meshesChanged,
    beforeImmediate, prepareVariantOperation, setMobilePane, dirtyCount } = workspace
  return <div className="ga-form prop-area-content">
    <h3>{t("Appearance")}</h3>
    <p className="ga-hint">{t("Light belongs to the shared draft. Surfaces and water apply immediately.")}</p>
          {shownVariant && <fieldset className="prop-editor-fields" disabled={!!previewFile}>
            <div className="ga-form-section-label">{t('Prop light')}</div>
            <Field label={t('Light preset')}>
              <select className="ga-input" value={lightPreset} onChange={(e) => {
                const preset = LIGHT_PRESETS.find((p) => p.name === e.target.value)
                setPlacing(null)
                queueVariant(variant, { light: e.target.value === '' ? null : {
                  ...(preset?.light || light || LIGHT_PRESETS[0].light),
                  at: light?.at || [0.5, 0.9, 0.5],
                } })
              }}>
                <option value="">{t('None')}</option>
                {LIGHT_PRESETS.map((p) => <option key={p.name} value={p.name}>{t(p.name)}</option>)}
                <option value="Custom">{t('Custom')}</option>
              </select>
            </Field>
            {light && <>
              <div className="ga-form-row">
                <Field label={t('Color')}><input type="color" value={light.color}
                  onChange={(e) => editLight({ color: e.target.value })} /></Field>
                {([
                  ['intensity', 'Intensity', 0.05, 100, 0.05],
                  ['range_m', 'Range (m)', 0.5, 40, 0.1],
                  ['glow_m', 'Halo size (m)', 0, 2, 0.01],
                ] as const).map(([key, label, min, max, step]) => <Field key={key} label={t(label)}>
                  <input className="ga-input" type="number" min={min} max={max} step={step} value={light[key]}
                    onChange={(e) => { if (e.target.value !== '' && Number.isFinite(e.target.valueAsNumber))
                      editLight({ [key]: Math.min(max, Math.max(min, e.target.valueAsNumber)) }) }} />
                </Field>)}
              </div>
              <div className="ga-form-row">
                <Field label={t('Flicker')}><select className="ga-input" value={light.flicker}
                  onChange={(e) => editLight({ flicker: e.target.value as PropLight['flicker'] })}>
                  <option value="none">{t('None')}</option><option value="candle">{t('Candle')}</option><option value="fire">{t('Fire')}</option>
                </select></Field>
                <Field label={t('When')}><select className="ga-input" value={light.when}
                  onChange={(e) => editLight({ when: e.target.value as PropLight['when'] })}>
                  <option value="always">{t('Always')}</option><option value="night">{t('Night')}</option>
                </select></Field>
              </div>
              <div className="ga-form-row">
                {['Light point u', 'Light point v', 'Light point w'].map((label, i) => <Field key={label} label={t(label)}>
                  <input className="ga-input" type="number" min={-0.5} max={2} step={0.01} value={light.at[i]}
                    onChange={(e) => {
                      if (e.target.value === '' || !Number.isFinite(e.target.valueAsNumber)) return
                      const at = [...light.at] as PropLight['at']
                      at[i] = Math.min(2, Math.max(-0.5, e.target.valueAsNumber))
                      editLight({ at })
                    }} />
                </Field>)}
              </div>
              <button type="button" className={`ga-btn ga-btn-sm${placing === 'light' ? ' ga-btn-primary' : ''}`}
                disabled={!shownHasMesh || !!previewFile || !!drawKind}
                onClick={() => armPlacing('light')}>{placing === 'light' ? t('Click the model…') : t('Place in viewer')}</button>
            </>}
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => {
              for (const v of variants) queueVariant(v.index, { light: light ? { ...light, at: [...light.at] } : null })
            }}>{t('Apply to all variants')}</button>
          </fieldset>}
    {previewFile && <p role="status" className="ga-hint">{t("Historical mesh preview: light, surface and water editing are locked. Return to the published model in the preview.")}</p>}
    <fieldset className="prop-editor-fields" disabled={!!previewFile}>

    {dirtyCount > 0 && <button type="button" className="ga-btn" onClick={async () => {
      if (await beforeImmediate(t("Use water tools"))) await meshesChanged()
    }}>{t("Save draft & use water tools")}</button>}
    <fieldset className="prop-editor-fields" disabled={dirtyCount > 0}>
          {shownVariant && shownHasMesh && <WaterPanel controller={waterController} onPlace={() => {
            setPlacing(null)
            setDrawKind('')
            setMobilePane('preview')
          }} />}
    </fieldset>
          {shownHasMesh ? (
            <PropAreasPanel
              prop={prop}
              variant={variant}
              variants={serverVariants}
              variantMax={variantMax}
              reloadKey={reloadKey}
              // The areas of the OPEN variant, read once above — the panel
              // lists and splits exactly the file the preview shows.
              info={variantAreas}
              infoFailed={areasFailed}
              // The one 3D view (V11): the panel has none of its own, it
              // switches the preview in the column beside it and shares its
              // call lock.
              tools={areaTools}
              prepareVariantOperation={prepareVariantOperation}
              onVariantsChanged={() => { void meshesChanged() }}
            />
          ) : null}
    </fieldset>
    {!shownHasMesh && <p className="ga-hint">{t("Surfaces and water require a model of this variant.")}</p>}
  </div>
}
