/**
 * PropVariantStrip — the prop's MODEL VARIANTS as one row of chips.
 *
 * A prop carries several meshes of the same object (E2.3): a scattered wood
 * was the same tree twenty times over, so the prop keeps an ORDERED list of
 * variants, each a mesh gallery of its own. The FIRST ACTIVE one is the
 * PRIMARY variant — what `/assets/props/{id}/model` serves without a
 * `variant` parameter and therefore what every consumer that knows nothing
 * about variants keeps getting.
 *
 * The strip is the selector for everything below it: clicking a chip decides
 * which variant the 3D preview and the mesh gallery (`PropModelPanel`) show
 * and act on. It owns the four variant verbs (add, toggle, delete, select);
 * the LIST itself is loaded by `PropDetail`, because the viewer up there needs
 * the same records to know which mesh URL to show.
 *
 * The active cap comes from the server (`image_generation.prop_variant_max`),
 * so "add" is greyed with a reason instead of letting the POST come back 409.
 *
 * SEASONS (E2c): a variant may be tagged with the seasons it depicts — one row
 * of toggle chips per variant, offered from the world's own season list, never
 * free text. Untagged (the default) means every season. A variant that is
 * tagged for another season keeps its meshes but renders nowhere until that
 * season comes round, which the chip row says in as many words. A world
 * without seasons gets no chips at all: the tags would be inert.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SCENE_CONTEXT_ORIGIN } from './propTypes'
import type { PropVariant } from './propTypes'

export function PropVariantStrip({ propId, variants, max, selected, onSelect,
  onChanged, generating = [], worldSeasons = [], currentSeason = '' }: {
  propId: string
  /** Every variant, active or not, in order (from PropDetail's load). */
  variants: PropVariant[]
  /** Ceiling on ACTIVE variants — the "add" action's gate. */
  max: number
  /** Index of the variant the detail currently works on. */
  selected: number
  /** Select a variant — the caller also drops its file preview. */
  onSelect: (index: number) => void
  /** Reload the variant list and the prop record (a variant changes both the
   *  strip and the prop's mesh signature). */
  onChanged: () => Promise<unknown>
  /** STORE indices with a generation in flight. Matched against a chip's own
   *  `index`, NOT against its position in this list: a switched-off variant
   *  keeps its index, so the two part company as soon as one is toggled off.
   *  Only those chips lose their toggle and their delete — the job is about to
   *  write into that slot, and a delete renumbers everything behind it.
   *  Adding a slot is never blocked by a run: it appends at the end. */
  generating?: number[]
  /** The world's season NAMES (`game_seasons`) — the only values a chip may
   *  set. Empty = a world without seasons, and then no chips are drawn. */
  worldSeasons?: string[]
  /** The season the world is in right now, for the "renders now" hint. */
  currentSeason?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(propId)
  // Two-step delete like the mesh rows: the first click arms the chip, the
  // second one deletes. Same reason as everywhere in this admin — no
  // window.confirm.
  const [armedDel, setArmedDel] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  // Arming is bound to an INDEX, and a delete renumbers everything behind it —
  // so any change of the list disarms rather than pointing at another variant.
  useEffect(() => { setArmedDel(null) }, [propId, variants.length])

  const activeCount = variants.filter((v) => v.active).length
  const capReached = activeCount >= max

  const run = useCallback(async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true)
    try {
      await fn()
      await onChanged()
      toast(ok)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [onChanged, t, toast])

  // The new slot is EMPTY — it is filled by the next generation targeted at
  // it, so selecting it right away is what the admin wants to do next.
  const add = useCallback(() => {
    void run(async () => {
      const d = await apiPost<{ index?: number }>(`/world/props/${enc}/variants`, {})
      if (typeof d?.index === 'number') onSelect(d.index)
    }, t('Variant added'))
  }, [enc, onSelect, run, t])

  const toggle = useCallback((v: PropVariant) => {
    void run(
      () => apiPost(`/world/props/${enc}/variants/${v.index}/active`, { active: !v.active }),
      v.active ? t('Variant switched off') : t('Variant switched on'))
  }, [enc, run, t])

  // Toggling ONE season on a variant: the chips are a set, and the server
  // stores what it is sent — so the new set is computed here and posted whole.
  const toggleSeason = useCallback((v: PropVariant, season: string) => {
    const has = v.seasons.some((s) => s.toLowerCase() === season.toLowerCase())
    const next = has
      ? v.seasons.filter((s) => s.toLowerCase() !== season.toLowerCase())
      : [...v.seasons, season]
    void run(
      () => apiPost(`/world/props/${enc}/variants/${v.index}/seasons`,
        { seasons: next }),
      next.length ? t('Seasons saved') : t('Season tag cleared'))
  }, [enc, run, t])

  const remove = useCallback((index: number) => {
    setArmedDel(null)
    void run(() => apiDelete(`/world/props/${enc}/variants/${index}`), t('Variant deleted'))
  }, [enc, run, t])

  return (
    <>
      <div className="ga-form-section-label">{t('Model variants')}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {variants.map((v) => {
          const isSelected = v.index === selected
          const isBusy = generating.includes(v.index)
          return (
            <div
              key={v.index}
              style={{
                display: 'flex', flexDirection: 'column', gap: 4,
                padding: '4px 6px', borderRadius: 6,
                border: `1px solid ${isSelected
                  ? 'var(--accent, #58a6ff)' : 'var(--border, #30363d)'}`,
                background: isSelected ? 'rgba(88,166,255,0.10)' : 'transparent',
                // A switched-off variant keeps its meshes but is not rendered
                // anywhere — it reads as muted, not as missing.
                opacity: v.active ? 1 : 0.55,
              }}
            >
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                style={{
                  border: 0, background: 'transparent', padding: '0 2px',
                  textAlign: 'left', fontWeight: isSelected ? 600 : 400,
                }}
                onClick={() => onSelect(v.index)}
                title={v.primary
                  ? t('Primary variant — this is the mesh every consumer gets that does not ask for a variant. Click to show it in the preview and the gallery below.')
                  : t('Show this variant in the preview and the mesh gallery below.')}
              >
                {v.primary ? '★ ' : ''}{t('Variant')} {v.index + 1}
              </button>
              <div style={{ display: 'flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
                {/* The spinner belongs on the chip the server names, and on no
                    other one — this is the whole point of the store index. */}
                {isBusy ? (
                  <span className="ga-source"
                    title={t('A generation is running for this variant — its image or its mesh is being written right now.')}>
                    {t('generating…')}
                  </span>
                ) : null}
                {v.has_model ? (
                  v.tiers.map((tier) => (
                    <span key={tier} className="ga-tag ga-tag-tier">{tier}</span>
                  ))
                ) : (
                  <span className="ga-tag ga-tag-missing">{t('no mesh')}</span>
                )}
                {/* The counterpart of the list badge: the row says HOW MANY
                    variants lack their product shot, here stands which one. */}
                {v.has_source ? null : (
                  <span className="ga-tag ga-tag-missing"
                    title={t('This variant has no source image — it cannot be re-meshed until one is rendered or uploaded.')}>
                    {t('no image')}
                  </span>
                )}
                {/* A variant made in the scene is a different KIND of version:
                    its picture was cut out of a rendered spot, so it carries
                    that spot's light and ground. A product shot writes no
                    origin at all, so it wears no badge. */}
                {v.image?.origin === SCENE_CONTEXT_ORIGIN ? (
                  <span className="ga-tag"
                    title={t('Generated in scene at {loc}, {ts}')
                      .replace('{loc}', v.image.origin_location || '—')
                      .replace('{ts}', v.image.origin_ts.slice(0, 10) || '—')}>
                    🎬
                  </span>
                ) : null}
              </div>
              {/* Season chips (E2c). A set, not a single choice: a variant may
                  depict two seasons. No chip lit = every season, which is why
                  the row needs no "always" chip of its own. */}
              {worldSeasons.length ? (
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                  {worldSeasons.map((season) => {
                    const on = v.seasons.some(
                      (s) => s.toLowerCase() === season.toLowerCase())
                    return (
                      <button
                        key={season}
                        type="button"
                        className={`ga-btn ga-btn-sm${on ? ' ga-btn-primary' : ''}`}
                        style={{ padding: '0 5px', fontSize: '0.85em' }}
                        disabled={busy}
                        onClick={() => toggleSeason(v, season)}
                        title={on
                          ? t('This variant renders in {season}. Click to drop that season; with no season left it renders all year.')
                            .replace('{season}', season)
                          : t('Show this variant only in {season} (and in every other season you light up here).')
                            .replace('{season}', season)}
                      >
                        {season}
                      </button>
                    )
                  })}
                </div>
              ) : null}
              {v.seasons.length && !v.in_season ? (
                <span className="ga-tag ga-tag-missing"
                  title={t('Out of season — this variant is not rendered while the world is in {season}.')
                    .replace('{season}', currentSeason || '—')}>
                  {t('out of season')}
                </span>
              ) : null}
              <div style={{ display: 'flex', gap: 3 }}>
                <button
                  type="button"
                  className={`ga-btn ga-btn-sm${v.active ? ' ga-btn-primary' : ''}`}
                  style={{ flex: 1 }}
                  disabled={busy || isBusy}
                  onClick={() => toggle(v)}
                  title={isBusy
                    ? t('This variant is generating right now — switching it off would move the primary variant under the running job.')
                    : v.active
                      ? t('Switch this variant off — its meshes stay stored, but nothing renders it any more. The last active variant cannot be switched off.')
                      : t('Switch this variant back on — it counts against the active limit again.')}
                >
                  {v.active ? '☑' : '☐'} {t('Active')}
                </button>
                <button
                  type="button"
                  className={`ga-btn ga-btn-sm${armedDel === v.index ? ' ga-btn-danger' : ''}`}
                  disabled={busy || isBusy || variants.length < 2}
                  onClick={() => {
                    if (armedDel === v.index) remove(v.index)
                    else setArmedDel(v.index)
                  }}
                  title={isBusy
                    ? t('This variant is generating right now — the run is about to write the very files a delete would remove.')
                    : variants.length < 2
                      ? t('A prop always keeps one variant.')
                      : t('Delete this variant with all its stored meshes.')}
                >
                  {armedDel === v.index ? t('Really?') : '×'}
                </button>
              </div>
            </div>
          )
        })}
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          style={{ alignSelf: 'center' }}
          // NOT gated on a running generation: appending a slot renumbers
          // nothing and touches no file a job holds. `busy` is only this
          // strip's own in-flight request — the concurrent-add guard.
          disabled={busy || capReached}
          onClick={add}
          title={capReached
            ? t('The limit of active variants is reached — switch one off or delete it first.')
            : t('Add an empty variant slot — the next generation fills it, or you upload a GLB into it.')}
        >
          + {t('Add variant')}
        </button>
      </div>
      <span className="ga-hint">
        {t('Several meshes of the SAME object — scattered copies pick one of them, so a wood is not one tree twenty times. ★ marks the primary variant, which is what anything that does not ask for a variant gets. The selected chip decides which variant the preview and the mesh gallery below show.')}
        {worldSeasons.length ? (
          ' ' + t('A variant with no season chip lit renders all year; light one up and it renders only then. If EVERY variant is out of season the prop keeps rendering its primary one — a placement never becomes a hole.')
        ) : null}
        {' '}
        {`${t('Active:')} ${activeCount}/${max}`}
      </span>
    </>
  )
}
