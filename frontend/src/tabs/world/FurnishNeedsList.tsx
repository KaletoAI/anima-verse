/**
 * FurnishNeedsList — the editable NEED list of a furnishing proposal
 * (plan-furnish-v2.md § 4, stage 1).
 *
 * ONE list, grouped by where a piece goes. Each row says what the room needs
 * (kind, count, size) and WHO serves it: the match select offers "Build new
 * piece" plus every library prop with the same mount, and that choice is the
 * only thing that decides whether a mesh is generated — `build` is derived
 * server-side from `prop_id` and never sent.
 *
 * The list edits in place and hands the whole array back; the dialog owns the
 * draft and posts it with the confirm.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { MOUNT_KINDS, type MountKind } from '../props/propTypes'
import { groupLabel } from './placeTypes'
import type { PoseGroupSpec } from './placeTypes'
import { MOUNT_GROUPS, propMount, type FurnishLibProp,
  type FurnishNeed } from './furnishTypes'

interface Props {
  needs: FurnishNeed[]
  onChange: (next: FurnishNeed[]) => void
  /** The prop library — `null` while it loads. */
  lib: FurnishLibProp[] | null
  /** What stage 1 threw away, shown as an info line. */
  dropped?: Array<{ kind: string; reason: string }>
  /** Place types of the pose catalog, for the marker chip's label. */
  poseGroups: Record<string, PoseGroupSpec>
  /** Called when the admin follows a link that leaves the dialog (the Props
   *  tab): the modal closes, otherwise it would float over the new tab. */
  onLeave?: () => void
}

/** A hand-added row: the smallest need that survives the server's validator
 *  once its kind is typed (dims 0.05–5 m, count 1–12, mount ∈ MOUNT_KINDS). */
function emptyNeed(key: string): FurnishNeed {
  return { key, kind: '', category: '', count: 1, mount: 'floor',
    width_m: 0.5, depth_m: 0.5, height_m: 0.5, style: '', description: '',
    marker: null, key_areas: [], from_description: false,
    prop_id: null, build: true }
}

export function FurnishNeedsList({ needs, onChange, lib, dropped, poseGroups,
  onLeave }: Props) {
  const { t } = useI18n()

  const patch = (index: number, fields: Partial<FurnishNeed>) => {
    onChange(needs.map((n, i) => (i === index ? { ...n, ...fields } : n)))
  }
  const remove = (index: number) => {
    onChange(needs.filter((_, i) => i !== index))
  }
  const add = () => {
    // Keys only have to be unique inside the list — the server re-mints them
    // as n1..nN on confirm anyway.
    const used = new Set(needs.map((n) => n.key))
    let i = needs.length + 1
    while (used.has(`n${i}`)) i += 1
    onChange([...needs, emptyNeed(`n${i}`)])
  }

  const byId = new Map((lib || []).map((p) => [p.id, p]))

  const numField = (label: string, value: number,
    onValue: (v: number) => void) => (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
      title={label}>
      <span className="ga-hint">{label}</span>
      <input className="ga-input" type="number" step={0.05} min={0.05} max={5}
        style={{ width: 74 }}
        value={value} onChange={(e) => onValue(Number(e.target.value))} />
    </label>
  )

  const row = (need: FurnishNeed, index: number) => {
    const matched = need.prop_id ? byId.get(need.prop_id) : undefined
    // Only pieces that go on the SAME surface can serve this need — the very
    // rule the server re-checks (`furnish_needs.match_fits`).
    const options = (lib || []).filter((p) => propMount(p) === need.mount)
    return (
      <div key={need.key} className="ga-furnish-new">
        <div className="ga-furnish-row" style={{ flexWrap: 'wrap' }}>
          <input className="ga-input" style={{ flex: '2 1 150px' }}
            value={need.kind} title={t('What the room needs')}
            placeholder={t('Kind (e.g. dining chair)')}
            onChange={(e) => patch(index, { kind: e.target.value })} />
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
            title={t('Count')}>
            <span className="ga-hint">×</span>
            <input className="ga-input" type="number" min={1} max={12}
              style={{ width: 56 }} value={need.count}
              onChange={(e) => patch(index, {
                count: Math.max(1, Math.min(12, Number(e.target.value) || 1)) })} />
          </label>
          {numField(t('W (m)'), need.width_m, (v) => patch(index, { width_m: v }))}
          {numField(t('D (m)'), need.depth_m, (v) => patch(index, { depth_m: v }))}
          {numField(t('H (m)'), need.height_m, (v) => patch(index, { height_m: v }))}
          <select className="ga-input" style={{ width: 120 }}
            title={t('Where this piece goes')}
            value={need.mount}
            onChange={(e) => patch(index, {
              mount: e.target.value as MountKind,
              // A piece that changes surface loses its match: the library
              // piece it named stands somewhere else.
              prop_id: null, build: true })}>
            {MOUNT_KINDS.map((m) => (
              <option key={m.kind} value={m.kind}>{t(m.label)}</option>
            ))}
          </select>
          <select className="ga-input" style={{ flex: '1 1 180px', minWidth: 0 }}
            title={t('Which piece serves this need')}
            value={need.prop_id || ''}
            onChange={(e) => patch(index, { prop_id: e.target.value || null,
              build: !e.target.value })}>
            <option value="">{t('Build new piece')}</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.width_m}×{p.depth_m}×{p.height_m} m
                {p.dims_estimated ? ` ${t('(size estimated)')}` : ''}
              </option>
            ))}
            {/* A matched prop the list does not offer (another mount, or gone)
                stays selectable — dropping it silently would rebuild a piece
                that already exists. */}
            {need.prop_id && !options.some((p) => p.id === need.prop_id) ? (
              <option value={need.prop_id}>
                {matched?.name || need.prop_id}
              </option>
            ) : null}
          </select>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
            title={t('Remove this need')} onClick={() => remove(index)}>×</button>
        </div>
        {/* The generation subject gets its own row — it is the field that
            needs the width, and it is what the mesh is made from. */}
        <textarea className="ga-input" rows={2} style={{ width: '100%' }}
          value={need.description || ''}
          placeholder={t('Generation subject — the isolated object, never a scene. Empty = the kind is used.')}
          title={t('Generation subject — the isolated object, never a scene. Empty = the kind is used.')}
          onChange={(e) => patch(index, { description: e.target.value })} />
        <span className="ga-hint" style={{ display: 'flex', gap: 8,
          flexWrap: 'wrap', alignItems: 'center' }}>
          {need.from_description ? (
            <span className="ga-furnish-chip"
              title={t('The room description names this object — it is a promise the room already made.')}>
              📝 {t('from description')}
            </span>
          ) : null}
          {need.marker ? (
            <span className="ga-furnish-chip"
              title={t('The place this piece offers — adjust the marker on the prop later.')}>
              🪑 {t('marker: {label}').replace('{label}',
                groupLabel(poseGroups, need.marker.group))}
            </span>
          ) : null}
          {(need.key_areas || []).map((area) => (
            <span key={area} className="ga-furnish-chip"
              title={t('A fillable panel the render carries.')}>
              🖼 {area}
            </span>
          ))}
          {matched?.dims_estimated ? (
            <span className="ga-furnish-chip ga-furnish-chip--warn">
              ⚠ {t('size estimated —')}{' '}
              <a href="#/props" onClick={() => onLeave?.()}>
                {t('fix it in the Props tab')}
              </a>
            </span>
          ) : null}
          {matched && !matched.has_model ? (
            <span className="ga-furnish-chip">
              {t('no model yet — placeholder')}
            </span>
          ) : null}
        </span>
      </div>
    )
  }

  return (
    <>
      {MOUNT_GROUPS.map(({ mount, label }) => {
        const rows = needs
          .map((n, i) => ({ n, i }))
          .filter(({ n }) => n.mount === mount)
        if (!rows.length) return null
        return (
          <div key={mount} style={{ display: 'flex', flexDirection: 'column',
            gap: 6 }}>
            <div className="ga-plan-panel-title">
              {t(label)} <span className="ga-hint">({rows.length})</span>
            </div>
            {rows.map(({ n, i }) => row(n, i))}
          </div>
        )
      })}
      {!needs.length ? (
        <div className="ga-form-hint">{t('The list is empty — add what the room needs.')}</div>
      ) : null}
      {(dropped || []).length ? (
        <ul className="ga-furnish-list">
          {(dropped || []).map((d, i) => (
            <li key={i}>
              {t('Dropped: {kind} — {reason}')
                .replace('{kind}', d.kind).replace('{reason}', d.reason)}
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" className="ga-btn ga-btn-sm"
        style={{ alignSelf: 'flex-start' }} onClick={add}>
        ＋ {t('Add need')}
      </button>
    </>
  )
}
