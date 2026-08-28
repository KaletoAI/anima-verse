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
 *
 * THE CHIP IS THE SELECTOR (2026-08-29, user decision "Spalte 2 zeigt immer
 * die gewählte Variante"). Size, generation subject, sink and the two triangle
 * budgets are the VARIANT's (2026-08-25) — but they are edited beside the
 * model they describe, in the second column: the strip would otherwise be a
 * form of forms, one per version, next to a preview showing exactly one of
 * them. What is left on a chip is what says WHICH version this is and whether
 * it renders: its number, its badges, its seasons, active and delete. The
 * fields themselves live in `variantFields.ts` and are drawn by `PropDetail`.
 *
 * THE FIELDS ARE DRAFTED, THE VERBS ARE IMMEDIATE (2026-08-25). Seasons — like
 * every other field — go into the detail's change buffer (`pendingFields`) and
 * reach the server when Save is pressed, which is why this strip posts none of
 * them; it hands them up. Add, on/off and delete stay immediate: they change
 * the store indices, the mesh signature and what a running generation
 * addresses, and every file action beside them (mesh gallery, source image)
 * speaks to the server about a variant that has to exist there. The `variants`
 * this strip renders are the DRAFT list, so an edit is on screen and in the 3D
 * preview long before it is stored.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { PropVariant } from './propTypes'

/** One chip's width in pixels — wide enough for the badge row, which is the
 *  widest thing in it since the inputs moved into the second column. Fixed on
 *  purpose: the strip may only ever grow DOWNWARDS, never re-flow sideways. */
const CHIP_W = 170

export function PropVariantStrip({ propId, variants, max, selected, onSelect,
  onChanged, onEditVariant, onDeleted, generating = [], worldSeasons = [],
  currentSeason = '' }: {
  propId: string
  /** Every variant, active or not, in order — the DRAFT list (PropDetail's
   *  load with the change buffer laid on top), so a field edit shows here and
   *  in the preview at once. */
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
  /** Put one variant's field edit into the detail's change buffer — nothing is
   *  written until Save. From this strip the patch is always `{seasons}`; the
   *  other fields are drawn beside the model, in the second column. */
  onEditVariant: (index: number, patch: Record<string, unknown>) => void
  /** A variant was really deleted on the server (STORE index). The detail
   *  drops its pending fields and renumbers the ones behind it, exactly as the
   *  server renumbered the list. */
  onDeleted: (index: number) => void
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

  // The new slot carries no mesh — it is filled by the next generation
  // targeted at it, so selecting it right away is what the admin wants to do
  // next. Its FIELDS come from the chip that is open (`from`): a version of an
  // object is authored by editing the one beside it, not by re-typing size,
  // subject, sink and markers.
  const add = useCallback(() => {
    void run(async () => {
      const d = await apiPost<{ index?: number }>(
        `/world/props/${enc}/variants`, { from: selected })
      if (typeof d?.index === 'number') onSelect(d.index)
    }, t('Variant added'))
  }, [enc, onSelect, run, selected, t])

  const toggle = useCallback((v: PropVariant) => {
    void run(
      () => apiPost(`/world/props/${enc}/variants/${v.index}/active`, { active: !v.active }),
      v.active ? t('Variant switched off') : t('Variant switched on'))
  }, [enc, run, t])

  // Toggling ONE season on a variant: the chips are a set, and the server
  // stores what it is sent — so the new set is computed here and drafted whole.
  const toggleSeason = useCallback((v: PropVariant, season: string) => {
    const has = v.seasons.some((s) => s.toLowerCase() === season.toLowerCase())
    const next = has
      ? v.seasons.filter((s) => s.toLowerCase() !== season.toLowerCase())
      : [...v.seasons, season]
    onEditVariant(v.index, { seasons: next })
  }, [onEditVariant])

  // Deleting a variant is IMMEDIATE (it takes its meshes and its source image
  // with it and renumbers everything behind it) — so the detail is told which
  // index went, and it renumbers its pending fields the same way.
  const remove = useCallback((index: number) => {
    setArmedDel(null)
    void run(async () => {
      await apiDelete(`/world/props/${enc}/variants/${index}`)
      onDeleted(index)
    }, t('Variant deleted'))
  }, [enc, onDeleted, run, t])

  return (
    <>
      <div className="ga-form-section-label">{t('Model variants')}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {variants.map((v) => {
          const isSelected = v.index === selected
          const isBusy = generating.includes(v.index)
          // Does this variant render right now? Computed HERE, not read off
          // the record: the chips may hold an unsaved tag, and a badge that
          // still answered from the last load would contradict the chip the
          // admin just lit. Mirrors `props.season_tags_active` on the names
          // this row offers — untagged is always in season, and so is every
          // variant in a world without seasons.
          const inSeason = !v.seasons.length || !currentSeason
            || v.seasons.some(
              (s) => s.toLowerCase() === currentSeason.toLowerCase())
          return (
            <div
              key={v.index}
              style={{
                // FIXED WIDTH, not content width: a chip whose width depended
                // on its badges would re-flow the whole strip whenever a mesh
                // finished or a season was lit. With every chip the same width
                // the line-up never changes.
                display: 'flex', flexDirection: 'column', gap: 4, width: CHIP_W,
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
              {v.seasons.length && !inSeason ? (
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
            : t('Add a variant slot — size, description, sink and markers are copied from the selected chip AS IT IS SAVED (unsaved edits stay behind, so save them first if they should travel); the next generation fills its mesh, or you upload a GLB into it.')}
        >
          + {t('Add variant')}
        </button>
      </div>
      {/* One short line — the details live in the field tooltips (user
          2026-08-24: the footer paragraph was long and half-translated). */}
      <span className="ga-hint">
        {t('Variants of one object — scatter mixes them, ★ is the default, the selected chip drives the preview.')}
        {worldSeasons.length ? ' ' + t('Season chips limit when a variant renders.') : null}
        {' '}
        {`${t('Active:')} ${activeCount}/${max}`}
      </span>
    </>
  )
}
