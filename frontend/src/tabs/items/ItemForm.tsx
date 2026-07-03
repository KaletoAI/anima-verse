import { useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { Field } from '../../components/Field'
import { EffectsEditor } from '../../components/EffectsEditor'
import {
  CATEGORIES,
  RARITIES,
  VALID_PIECE_SLOTS,
  type Category,
  type ConditionOption,
  type DraftItem,
  type Item,
  type Rarity,
} from './itemsModel'

interface TagPickerProps {
  options: string[]
  values: string[]
  onToggle: (value: string) => void
  allowFreeform?: boolean
}

function TagPicker({ options, values, onToggle, allowFreeform }: TagPickerProps) {
  const { t } = useI18n()
  const [draft, setDraft] = useState('')
  const remaining = options.filter((o) => !values.includes(o))
  return (
    <div className="ga-tags-row">
      {values.map((v) => (
        <button key={v} type="button" className="ga-tag-pill" onClick={() => onToggle(v)} title={t('Remove')}>
          {v} ×
        </button>
      ))}
      <select
        className="ga-input"
        style={{ width: 'auto', fontSize: 11, padding: '2px 6px' }}
        value=""
        onChange={(e) => {
          if (e.target.value) onToggle(e.target.value)
        }}
      >
        <option value="">+ {t('add')}</option>
        {remaining.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      {allowFreeform ? (
        <input
          className="ga-input"
          style={{ width: 130, fontSize: 11, padding: '2px 6px' }}
          value={draft}
          placeholder={t('+ new')}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim()) {
              onToggle(draft.trim().toLowerCase())
              setDraft('')
            }
          }}
        />
      ) : null}
    </div>
  )
}

interface OutfitPieceFieldsProps {
  outfitTypes: string[]
  slots: string[]
  covers: string[]
  partiallyCovers: string[]
  outfitTypeOptions: string[]
  onToggleListItem: (key: 'outfit_types' | 'slots' | 'covers' | 'partially_covers', value: string) => void
}

function OutfitPieceFields({
  outfitTypes,
  slots,
  covers,
  partiallyCovers,
  outfitTypeOptions,
  onToggleListItem,
}: OutfitPieceFieldsProps) {
  const { t } = useI18n()
  return (
    <div className="ga-section">
      <div className="ga-form-section-label">{t('Outfit piece')}</div>
      <Field label={t('Outfit types')}>
        <TagPicker
          options={outfitTypeOptions}
          values={outfitTypes}
          onToggle={(v) => onToggleListItem('outfit_types', v)}
          allowFreeform
        />
      </Field>
      <Field label={t('Slots')} hint={t('Single-slot items wear one slot. Multi-slot items (dress, jumpsuit, thigh-highs) wear several.')}>
        <TagPicker
          options={VALID_PIECE_SLOTS}
          values={slots}
          onToggle={(v) => onToggleListItem('slots', v)}
        />
      </Field>
      <Field label={t('Fully covers')}>
        <TagPicker
          options={VALID_PIECE_SLOTS}
          values={covers}
          onToggle={(v) => onToggleListItem('covers', v)}
        />
      </Field>
      <Field label={t('Partially covers')}>
        <TagPicker
          options={VALID_PIECE_SLOTS}
          values={partiallyCovers}
          onToggle={(v) => onToggleListItem('partially_covers', v)}
        />
      </Field>
    </div>
  )
}

interface SpellFieldsProps {
  extras: Record<string, unknown>
  items: Item[]
  draftId: string
  onUpdateExtra: (key: string, value: unknown) => void
}

function SpellFields({ extras, items, draftId, onUpdateExtra }: SpellFieldsProps) {
  const { t } = useI18n()
  // Other items sorted by name, used by both the effect-item and anchor-item
  // selects. Computed once so the render doesn't sort twice.
  const sortedOtherItems = useMemo(
    () => items.filter((it) => it.id !== draftId).sort((a, b) => (a.name || '').localeCompare(b.name || '')),
    [items, draftId],
  )
  return (
    <div className="ga-section">
      <div className="ga-form-section-label">{t('Spell')}</div>
      <Field
        label={t('Incantation')}
        hint={t('Trigger phrase the avatar must say in chat. Detected case-insensitively.')}
      >
        <input
          className="ga-input"
          value={(extras.incantation as string) || ''}
          placeholder={t("e.g. 'Heimfaden, zieh mich heim'")}
          onChange={(e) => onUpdateExtra('incantation', e.target.value)}
        />
      </Field>
      <div className="ga-form-row">
        <Field label={t('Mode')} hint={t('force = spell on target. gift = scroll/potion handed over.')}>
          <select
            className="ga-input"
            value={(extras.spell_mode as string) || 'force'}
            onChange={(e) => onUpdateExtra('spell_mode', e.target.value)}
          >
            <option value="force">force</option>
            <option value="gift">gift</option>
          </select>
        </Field>
        <Field label={t('Success chance')} hint={t('0–100. Roll above = fail.')}>
          <input
            type="number"
            className="ga-input"
            style={{ width: 90 }}
            min={0}
            max={100}
            value={(extras.success_chance as number) ?? 100}
            onChange={(e) => onUpdateExtra('success_chance', parseInt(e.target.value, 10) || 0)}
          />
        </Field>
        <Field label={t('Caster keeps spell')} hint={t('On = learned spell (reusable). Off = scroll/potion (consumed).')}>
          <label className="ga-form-check" style={{ marginTop: 6 }}>
            <input
              type="checkbox"
              checked={!!extras.copy_on_give}
              onChange={(e) => onUpdateExtra('copy_on_give', e.target.checked)}
            />
            {t('copy_on_give')}
          </label>
        </Field>
      </div>
      <div className="ga-form-row">
        <Field label={t('Success text')} hint={t('Hint injected into the target NPC prompt on success.')}>
          <textarea
            className="ga-textarea"
            rows={2}
            value={(extras.success_text as string) || ''}
            onChange={(e) => onUpdateExtra('success_text', e.target.value)}
          />
        </Field>
        <Field label={t('Fail text')} hint={t('Hint injected on failure.')}>
          <textarea
            className="ga-textarea"
            rows={2}
            value={(extras.fail_text as string) || ''}
            onChange={(e) => onUpdateExtra('fail_text', e.target.value)}
          />
        </Field>
      </div>
      <div className="ga-form-row">
        <Field label={t('Cast activity')} hint={t('Optional library activity set on the caster after the cast (cooldown).')}>
          <input
            className="ga-input"
            value={(extras.cast_activity as string) || ''}
            placeholder={t("e.g. 'channeling'")}
            onChange={(e) => onUpdateExtra('cast_activity', e.target.value)}
          />
        </Field>
        <Field label={t('Effect item (clone_item_id)')} hint={t('Item handed to the target on success. Defaults to the spell item itself.')}>
          <select
            className="ga-input"
            value={(extras.clone_item_id as string) || ''}
            onChange={(e) => onUpdateExtra('clone_item_id', e.target.value)}
          >
            <option value="">{t('-- spell item itself --')}</option>
            {sortedOtherItems.map((it) => (
              <option key={it.id} value={it.id}>
                {it.name || it.id}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="ga-form-section-label" style={{ marginTop: 12 }}>{t('Anchor teleport')}</div>
      <div className="ga-form-row">
        <Field
          label={t('Anchor item')}
          hint={t('When set, casting teleports to wherever this item currently is (a character carrying it, or a room it lies in). Leave empty for non-teleport spells.')}
        >
          <select
            className="ga-input"
            value={(extras.anchor_item_id as string) || ''}
            onChange={(e) => onUpdateExtra('anchor_item_id', e.target.value)}
          >
            <option value="">{t('-- no anchor (not a teleport) --')}</option>
            {sortedOtherItems.map((it) => (
              <option key={it.id} value={it.id}>
                {it.name || it.id} <span>— {it.category || 'tool'}</span>
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t('Direction')}
          hint={t('caster: caster jumps to the anchor. anchor_holder: anchor carrier is pulled to the caster (only works if a character carries the anchor).')}
        >
          <select
            className="ga-input"
            value={(extras.teleport_subject as string) || 'caster'}
            onChange={(e) => onUpdateExtra('teleport_subject', e.target.value)}
            disabled={!extras.anchor_item_id}
          >
            <option value="caster">{t('caster → anchor')}</option>
            <option value="anchor_holder">{t('anchor holder → caster')}</option>
          </select>
        </Field>
      </div>
    </div>
  )
}

interface ItemFormProps {
  draft: DraftItem
  items: Item[]
  outfitTypeOptions: string[]
  conditionOptions: ConditionOption[]
  onUpdate: <K extends keyof DraftItem>(key: K, value: DraftItem[K]) => void
  onUpdateExtra: (key: string, value: unknown) => void
  onToggleListItem: (key: 'outfit_types' | 'slots' | 'covers' | 'partially_covers', value: string) => void
}

export function ItemForm({ draft, items, outfitTypeOptions, conditionOptions, onUpdate, onUpdateExtra, onToggleListItem }: ItemFormProps) {
  const { t } = useI18n()
  const isOutfit = draft.category === 'outfit_piece'
  const isSpell = draft.category === 'spell'
  return (
    <div className="ga-form">
      {!draft.isNew ? (
        <Field label={t('Item ID (read-only)')} hint={t('Permanent identifier — set when the item was created. Used in rules as has_item:{id}.').replace('{id}', draft.id)}>
          <input
            className="ga-input"
            value={draft.id}
            readOnly
            disabled
            style={{ fontFamily: 'monospace', opacity: 0.7 }}
          />
        </Field>
      ) : (
        <Field
          label={t('Item ID')}
          hint={t('Used in rule conditions (e.g. has_item:item_holoprojector). Lowercase letters, digits, underscore. Leave empty to derive it from the name.')}
        >
          <input
            className="ga-input"
            value={draft.id}
            placeholder="item_holoprojector"
            onChange={(e) => onUpdate('id', e.target.value)}
            style={{ fontFamily: 'monospace' }}
          />
        </Field>
      )}
      <div className="ga-form-row">
        <Field label={t('Name')} hint={t('English. Also used as display name.')}>
          <input
            className="ga-input"
            value={draft.name}
            onChange={(e) => onUpdate('name', e.target.value)}
          />
        </Field>
        <Field label={t('Description')}>
          <input
            className="ga-input"
            value={draft.description}
            onChange={(e) => onUpdate('description', e.target.value)}
          />
        </Field>
      </div>

      <div className="ga-form-row">
        <Field label={t('Category')}>
          <select
            className="ga-input"
            value={draft.category}
            onChange={(e) => onUpdate('category', e.target.value as Category)}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('Rarity')}>
          <select
            className="ga-input"
            value={draft.rarity}
            onChange={(e) => onUpdate('rarity', e.target.value as Rarity)}
          >
            {RARITIES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field label={t('Flags')}>
        <div className="ga-form-row" style={{ gap: 14 }}>
          <label className="ga-form-check">
            <input type="checkbox" checked={draft.stackable} onChange={(e) => onUpdate('stackable', e.target.checked)} />
            {t('Stackable')}
          </label>
          <label className="ga-form-check">
            <input
              type="checkbox"
              checked={draft.transferable}
              onChange={(e) => onUpdate('transferable', e.target.checked)}
            />
            {t('Transferable')}
          </label>
          <label className="ga-form-check">
            <input
              type="checkbox"
              checked={draft.consumable}
              onChange={(e) => onUpdate('consumable', e.target.checked)}
            />
            {t('Consumable')}
          </label>
        </div>
      </Field>

      <Field label={t('Image prompt')} help="image_prompt" hint={t('Used to generate the item image.')}>
        <input
          className="ga-input"
          value={draft.image_prompt}
          placeholder={t("e.g. 'silver house key on wooden table, realistic'")}
          onChange={(e) => onUpdate('image_prompt', e.target.value)}
        />
      </Field>
      <Field label={t('Prompt fragment')} help="image_prompt" hint={t('Used in the character image when this item is held or worn.')}>
        <input
          className="ga-input"
          value={draft.prompt_fragment}
          placeholder={t("e.g. 'holding a hammer' or 'black leather jacket, slim fit'")}
          onChange={(e) => onUpdate('prompt_fragment', e.target.value)}
        />
      </Field>

      {isOutfit ? (
        <OutfitPieceFields
          outfitTypes={draft.outfit_types}
          slots={draft.slots}
          covers={draft.covers}
          partiallyCovers={draft.partially_covers}
          outfitTypeOptions={outfitTypeOptions}
          onToggleListItem={onToggleListItem}
        />
      ) : null}

      {isSpell ? (
        <SpellFields
          extras={draft.extras}
          items={items}
          draftId={draft.id}
          onUpdateExtra={onUpdateExtra}
        />
      ) : null}

      {draft.consumable || draft.category === 'spell' ? (
        <div className="ga-section">
          <div className="ga-form-section-label">
            {draft.category === 'spell' ? t('Effect on cast') : t('Effect on consume')}
          </div>
          <Field
            label={t('Effects')}
            help="effects_syntax"
            hint={t('Format: "stat_change: +/-value" per line. Click a stat or mood to insert it.')}
          >
            <EffectsEditor value={draft.effects} onChange={(v) => onUpdate('effects', v)} />
          </Field>
          <div className="ga-form-row">
            <Field label={t('Apply condition')} hint={t('Optional. Activates a state tag in the character profile.')}>
              <select
                className="ga-input"
                value={draft.apply_condition}
                onChange={(e) => onUpdate('apply_condition', e.target.value)}
              >
                <option value="">{t('-- none --')}</option>
                {conditionOptions.map((c) => {
                  const icon = c.icon ? `${c.icon} ` : ''
                  const label = c.label ? ` — ${c.label}` : ''
                  return (
                    <option key={c.name} value={c.name}>
                      {icon}
                      {c.name}
                      {label}
                    </option>
                  )
                })}
                {draft.apply_condition &&
                !conditionOptions.some((c) => c.name === draft.apply_condition) ? (
                  <option value={draft.apply_condition}>
                    {draft.apply_condition} {t('(not in conditions)')}
                  </option>
                ) : null}
              </select>
            </Field>
            <Field label={t('Duration in hours')}>
              <input
                type="number"
                className="ga-input"
                style={{ width: 90 }}
                min={1}
                value={draft.condition_duration}
                onChange={(e) => onUpdate('condition_duration', parseInt(e.target.value, 10) || 0)}
              />
            </Field>
          </div>
        </div>
      ) : null}
    </div>
  )
}
