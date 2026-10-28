/**
 * Operations for the variant selected in the workspace's single selector.
 * Seasons are drafted; add, activation and deletion use the existing
 * UUID-resolved save barrier. The full list still determines active limits
 * and generation/deletion safety, including background variants.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { PropVariant } from './propTypes'
import type { PreparePropVariantOperation } from './propOperations'
import { PropWorkspaceDialog } from './PropWorkspaceDialog'

export function PropVariantStrip({ propId, variants, max, selected, onSelect,
  onChanged, onEditVariant, onDeleted, generating = [], worldSeasons = [],
  currentSeason = '', prepareVariantOperation }: {
  propId: string
  /** Every variant, active or not, in order — the DRAFT list (PropDetail's
   *  load with the change buffer laid on top), so a field edit shows here and
   *  in the preview at once. */
  variants: PropVariant[]
  /** Ceiling on ACTIVE variants — the "add" action's gate. */
  max: number
  /** Index of the variant the detail currently works on. */
  selected: number
  /** Select the newly added variant after the immediate add succeeds. */
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
  prepareVariantOperation: PreparePropVariantOperation
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(propId)
  // Two-step delete like the mesh rows: the first click arms the chip, the
  // second one deletes. Same reason as everywhere in this admin — no
  // window.confirm.
  const [armedDel, setArmedDel] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<PropVariant | null>(null)
  // Arming is bound to an INDEX, and a delete renumbers everything behind it —
  // so any change of the list disarms rather than pointing at another variant.
  useEffect(() => { setArmedDel(null); setDeleteTarget(null) }, [propId, variants.length])

  const activeCount = variants.filter((v) => v.active).length
  const capReached = activeCount >= max

  const run = useCallback(async (uid: string, fn: (target: PropVariant) => Promise<unknown>, ok: string) => {
    const target = await prepareVariantOperation(uid, ok)
    if (!target) return
    setBusy(true)
    try {
      await fn(target)
      await onChanged()
      toast(ok)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [onChanged, t, toast, prepareVariantOperation])

  // The new slot carries no mesh — it is filled by the next generation
  // targeted at it, so selecting it right away is what the admin wants to do
  // next. Its FIELDS come from the chip that is open (`from`): a version of an
  // object is authored by editing the one beside it, not by re-typing size,
  // subject, sink and markers.
  const add = useCallback(() => {
    void run(variants.find((entry) => entry.index === selected)?.uid || '', async (target) => {
      const d = await apiPost<{ index?: number }>(
        `/world/props/${enc}/variants`, { from: target.index })
      if (typeof d?.index === 'number') onSelect(d.index)
    }, t('Variant added'))
  }, [enc, onSelect, run, selected, variants, t])

  const toggle = useCallback((v: PropVariant) => {
    void run(v.uid,
      (target) => apiPost(`/world/props/${enc}/variants/${target.index}/active`, { active: !v.active }),
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
  const remove = useCallback(async (uid: string, acceptedBindings?: string[]) => {
    setArmedDel(null)
    const target = await prepareVariantOperation(uid, t('Variante und ihre Bindungen löschen'))
    if (!target) return
    const references = (target.action_bindings || []).map(binding => binding.action_id)
    if (references.length && (!acceptedBindings || references.some(id => !acceptedBindings.includes(id)))) {
      setDeleteTarget(target)
      return
    }
    setBusy(true)
    try {
      await apiDelete(`/world/props/${enc}/variants/${target.index}`)
      setDeleteTarget(null)
      onDeleted(target.index)
      await onChanged()
      toast(t('Variant deleted'))
    } catch (error) { toast(t('Error') + ': ' + (error as Error).message, 'error') }
    finally { setBusy(false) }
  }, [enc, onDeleted, onChanged, prepareVariantOperation, t, toast])

  return (
    <>
      <div className="ga-form-section-label">{t('Ausgewählte Modellvariante')}</div>
      {generating.length > 0 && <span className="ga-hint" role="status">
        {t('generating…')}: {generating.map(index =>
          variants.find(v => v.index === index)?.label || `${t('Variant')} ${index + 1}`).join(', ')}
      </span>}
      <div className="prop-selected-variant-management">
        {variants.filter(v => v.index === selected).map((v) => {
          const isBusy = generating.includes(v.index)
          // A delete renumbers every variant behind this one, so a run there
          // blocks it too (server: variant_delete_blocked).
          const behindBusy = !isBusy && generating.some((g) => g > v.index)
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
              key={v.uid}
              className="prop-selected-variant-fields"
            >
              <strong>{v.primary ? '★ ' : ''}{t('Variant')} {v.index + 1}</strong>
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
                        aria-pressed={on}
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
                  aria-pressed={v.active}
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
                  disabled={busy || isBusy || behindBusy || variants.length < 2}
                  onClick={() => {
                    if (v.action_bindings?.length) setDeleteTarget(v)
                    else if (armedDel === v.index) void remove(v.uid)
                    else setArmedDel(v.index)
                  }}
                  title={isBusy
                    ? t('This variant is generating right now — the run is about to write the very files a delete would remove.')
                    : behindBusy
                      ? t('A variant after this one is generating — a delete would renumber it under the running job.')
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
            : t('Add a variant slot — size, description, sink and markers are copied from the selected chip AS IT IS SAVED (unsaved edits stay behind, so save them first if they should travel). Then render its picture with “New image” and base it on this variant’s image to author a version of it — a winter one, say.')}
        >
          + {t('Add variant')}
        </button>
      </div>
      {/* One short line — the details live in the field tooltips (user
          2026-08-24: the footer paragraph was long and half-translated). */}
      <span className="ga-hint">
        {t('Die Variantenauswahl oberhalb des Editors bestimmt die Geometrie. Aktivieren, Hinzufügen und Löschen werden sofort angewendet; Jahreszeiten gehören zum Entwurf.')}
        {worldSeasons.length ? ' ' + t('Season chips limit when a variant renders.') : null}
        {' '}
        {`${t('Active:')} ${activeCount}/${max}`}
      </span>
      {deleteTarget && <PropWorkspaceDialog title={t('Variante mit Aktionsbindungen löschen')} onCancel={() => setDeleteTarget(null)}>
        <p>{t('Wird sofort angewendet: Diese Variante, ihre Dateien und alle folgenden Bindungen werden gemeinsam entfernt. Aktionen bleiben am Prop bestehen; andere Varianten bleiben unverändert. Die UUID wird nach der Speicherschranke erneut aufgelöst.')}</p>
        <ul>{(deleteTarget.action_bindings || []).map(binding => <li key={binding.action_id}>{binding.action_id}</li>)}</ul>
        <div className="ga-form-row">
          <button type="button" className="ga-btn ga-btn-danger" disabled={busy}
            onClick={() => { void remove(deleteTarget.uid, (deleteTarget.action_bindings || []).map(binding => binding.action_id)) }}>{t('Variante und sämtliche abhängigen Bindungen löschen')}</button>
          <button type="button" className="ga-btn" disabled={busy} onClick={() => setDeleteTarget(null)}>{t('Abbrechen')}</button>
        </div>
      </PropWorkspaceDialog>}
    </>
  )
}
