import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'

/**
 * Per-character skill manager (Characters → Skills), ported from the legacy
 * editor's loadEditorSkills: a list of skills with an enable checkbox each and
 * a dynamic config panel rendered from the skill's `config_fields` metadata
 * (bool / int / float / str / locations). Backed by:
 *   GET  /characters/{c}/skills/available          (list + fields + current values)
 *   PUT  /characters/{c}/skills/{skill}/enabled    (toggle)
 *   POST /characters/{c}/skills/{skill}            (merge config fields)
 *
 * The image_generation / video_generation skills have their own dedicated
 * config (backends, LoRAs, …) via separate routes — those land in their own
 * editor; here they appear with just the enable toggle.
 */

interface ConfigField {
  type: string
  default: unknown
  label?: string
  value?: unknown
}
interface SkillInfo {
  skill_id: string
  name: string
  description?: string
  enabled: boolean
  // Capability group (plugin.yaml capability_label): all verbs of the
  // package render as ONE toggle — e.g. "Party" for invite/join/leave.
  capability_id?: string
  capability_label?: string
  // Package dependency block (requires/conflicts) — non-empty = the toggle
  // is disabled while the skill is off; the backend refuses enabling too.
  blocked_reason?: string
  config_fields: Record<string, ConfigField> | null
}
interface LocationOpt {
  id: string
  name: string
}

export function SkillsTab({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [locations, setLocations] = useState<LocationOpt[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<string>('')  // skill_id im Detail-Pane

  const reload = useCallback(async () => {
    if (!character) return
    setLoading(true)
    try {
      const d = await apiGet<{ skills?: SkillInfo[]; locations?: LocationOpt[] }>(
        `/characters/${encodeURIComponent(character)}/skills/available`,
      )
      setSkills(d.skills || [])
      setLocations(d.locations || [])
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      setSkills([])
    } finally {
      setLoading(false)
    }
  }, [character, t, toast])

  useEffect(() => {
    reload()
  }, [reload])

  const toggleEnabled = useCallback(
    async (skill: SkillInfo, enabled: boolean) => {
      setSkills((prev) =>
        prev.map((s) => (s.skill_id === skill.skill_id ? { ...s, enabled } : s)),
      )
      try {
        await apiPut(
          `/characters/${encodeURIComponent(character)}/skills/${encodeURIComponent(skill.skill_id)}/enabled`,
          { enabled },
        )
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        setSkills((prev) =>
          prev.map((s) => (s.skill_id === skill.skill_id ? { ...s, enabled: !enabled } : s)),
        )
      }
    },
    [character, t, toast],
  )

  // Capability group: all verbs of the package on/off together
  // (optimistic + one PUT per member).
  const toggleGroup = useCallback(
    async (memberIds: string[], enabled: boolean) => {
      const members = new Set(memberIds)
      setSkills((prev) =>
        prev.map((s) => (members.has(s.skill_id) ? { ...s, enabled } : s)),
      )
      try {
        const base = `/characters/${encodeURIComponent(character)}/skills`
        await Promise.all(
          memberIds.map((id) =>
            apiPut(`${base}/${encodeURIComponent(id)}/enabled`, { enabled }),
          ),
        )
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        reload()
      }
    },
    [character, reload, t, toast],
  )

  // Update the field value locally (so inputs stay controlled), then persist
  // the single field via the merge endpoint.
  const setFieldValue = useCallback((skillId: string, field: string, value: unknown) => {
    setSkills((prev) =>
      prev.map((s) =>
        s.skill_id === skillId && s.config_fields
          ? {
              ...s,
              config_fields: {
                ...s.config_fields,
                [field]: { ...s.config_fields[field], value },
              },
            }
          : s,
      ),
    )
  }, [])

  const saveField = useCallback(
    async (skillId: string, field: string, value: unknown) => {
      try {
        await apiPost(
          `/characters/${encodeURIComponent(character)}/skills/${encodeURIComponent(skillId)}`,
          { config: { [field]: value } },
        )
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [character, t, toast],
  )

  if (loading && !skills.length) {
    return <div className="ga-loading">{t('Loading…')}</div>
  }
  if (!skills.length) {
    return <div className="ga-placeholder">{t('No skills available.')}</div>
  }

  // Capability groups (capability_label from the API): all verbs of a
  // package render as ONE entry, named after the capability. The first
  // member is the representative (selection, config fields); the other
  // members are hidden from the list and toggled along.
  const groupMembers: Record<string, SkillInfo[]> = {}
  for (const s of skills) {
    if (s.capability_id) (groupMembers[s.capability_id] ||= []).push(s)
  }
  const secondary = new Set<string>()
  for (const members of Object.values(groupMembers)) {
    for (const m of members.slice(1)) secondary.add(m.skill_id)
  }

  const visible = skills.filter((s) => !secondary.has(s.skill_id))
  const current = visible.find((s) => s.skill_id === selected) || visible[0]
  const membersOf = (s: SkillInfo): SkillInfo[] =>
    s.capability_id ? groupMembers[s.capability_id] || [s] : [s]
  const nameOf = (s: SkillInfo) =>
    s.capability_id ? (s.capability_label || s.name) : (s.name || s.skill_id)
  const groupEnabled = (s: SkillInfo) => membersOf(s).every((m) => m.enabled)
  const groupBlocked = (s: SkillInfo) =>
    membersOf(s).map((m) => m.blocked_reason).find(Boolean) || ''
  const onToggle = (s: SkillInfo, checked: boolean) => {
    const members = membersOf(s)
    return members.length > 1
      ? toggleGroup(members.map((m) => m.skill_id), checked)
      : toggleEnabled(s, checked)
  }

  const fields = current?.config_fields ? Object.entries(current.config_fields) : []
  const idHint = current ? membersOf(current).map((m) => m.skill_id).join(' + ') : ''

  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
      {/* Liste: Aktivierung + Auswahl */}
      <div style={{
        flex: '0 0 230px', maxWidth: 280, display: 'flex', flexDirection: 'column', gap: 1,
        border: '1px solid var(--border, #30363d)', borderRadius: 8, padding: 4,
        maxHeight: '70vh', overflow: 'auto',
      }}>
        {visible.map((s) => {
          const active = current?.skill_id === s.skill_id
          return (
            <div key={s.skill_id} onClick={() => setSelected(s.skill_id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px',
                borderRadius: 6, cursor: 'pointer',
                background: active ? 'rgba(120,170,255,0.16)' : 'transparent',
                border: '1px solid ' + (active ? 'var(--accent, #6aa9ff)' : 'transparent'),
              }}>
              <input type="checkbox" checked={groupEnabled(s)}
                disabled={!groupEnabled(s) && !!groupBlocked(s)}
                title={!groupEnabled(s) && groupBlocked(s) ? groupBlocked(s) : undefined}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => onToggle(s, e.target.checked)} />
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                             whiteSpace: 'nowrap', fontSize: '0.9em', opacity: groupEnabled(s) ? 1 : 0.6 }}
                title={!groupEnabled(s) && groupBlocked(s) ? groupBlocked(s) : undefined}>
                {nameOf(s)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Detail des gewählten Skills */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {!current ? (
          <div className="ga-placeholder">{t('Select a skill.')}</div>
        ) : (
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <strong style={{ fontSize: '1.02em' }}>{nameOf(current)}</strong>
              <code style={{ opacity: 0.4, fontSize: '0.8em' }}>{idHint}</code>
            </div>
            <label className="ga-form-check"
              style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, fontSize: '0.9em' }}>
              <input type="checkbox" checked={current.enabled}
                disabled={!current.enabled && !!current.blocked_reason}
                onChange={(e) => onToggle(current, e.target.checked)} />
              {current.enabled ? t('Enabled') : t('Disabled')}
            </label>
            {!current.enabled && current.blocked_reason && (
              <div style={{ marginTop: 6, fontSize: '0.85em', color: 'var(--warn, #d29922)' }}>
                {t('Blocked by package dependencies')}: {current.blocked_reason}
              </div>
            )}
            {current.description && (
              <div style={{ opacity: 0.7, fontSize: '0.88em', marginTop: 8, lineHeight: 1.4 }}>
                {current.description}
              </div>
            )}
            {current.enabled && fields.length > 0 && (
              <div className="ga-form" style={{ marginTop: 14, gap: 8 }}>
                {fields.map(([fieldName, field]) => (
                  <SkillField
                    key={fieldName}
                    field={field}
                    label={field.label || fieldName}
                    locations={locations}
                    onChangeLocal={(v) => setFieldValue(current.skill_id, fieldName, v)}
                    onCommit={(v) => saveField(current.skill_id, fieldName, v)}
                  />
                ))}
              </div>
            )}
            {current.enabled && fields.length === 0 && (
              <div style={{ opacity: 0.45, fontSize: '0.85em', marginTop: 12 }}>
                {t('No settings for this skill.')}
              </div>
            )}
            {!current.enabled && (
              <div style={{ opacity: 0.45, fontSize: '0.85em', marginTop: 12 }}>
                {t('Enable this skill to configure it.')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function SkillField({
  field,
  label,
  locations,
  onChangeLocal,
  onCommit,
}: {
  field: ConfigField
  label: string
  locations: LocationOpt[]
  onChangeLocal: (v: unknown) => void
  onCommit: (v: unknown) => void
}) {
  const { t } = useI18n()
  const type = field.type
  const value = field.value

  if (type === 'bool') {
    return (
      <label className="ga-form-check" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => {
            onChangeLocal(e.target.checked)
            onCommit(e.target.checked)
          }}
        />
        {label}
      </label>
    )
  }

  if (type === 'int' || type === 'float') {
    return (
      <Field label={label}>
        <input
          className="ga-input"
          type="number"
          step={type === 'float' ? 'any' : 1}
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(e) => onChangeLocal(e.target.value === '' ? '' : Number(e.target.value))}
          onBlur={(e) => {
            const raw = e.target.value
            const num = raw === '' ? 0 : type === 'float' ? parseFloat(raw) : parseInt(raw, 10)
            onCommit(Number.isNaN(num) ? 0 : num)
          }}
        />
      </Field>
    )
  }

  if (type === 'locations') {
    const selected: string[] = Array.isArray(value) ? (value as string[]) : []
    const toggle = (id: string) => {
      const next = selected.includes(id)
        ? selected.filter((x) => x !== id)
        : [...selected, id]
      onChangeLocal(next)
      onCommit(next)
    }
    return (
      <Field label={label} hint={t('Empty = all visitable locations.')}>
        {locations.length === 0 ? (
          <div style={{ opacity: 0.6, fontSize: '0.85em' }}>{t('No locations.')}</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {locations.map((loc) => (
              <label
                key={loc.id}
                className="ga-form-check"
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(loc.id)}
                  onChange={() => toggle(loc.id)}
                />
                {loc.name || loc.id}
              </label>
            ))}
          </div>
        )}
      </Field>
    )
  }

  // str (and any unknown type) → plain text input.
  return (
    <Field label={label}>
      <input
        className="ga-input"
        type="text"
        value={value === undefined || value === null ? '' : String(value)}
        onChange={(e) => onChangeLocal(e.target.value)}
        onBlur={(e) => onCommit(e.target.value)}
      />
    </Field>
  )
}
