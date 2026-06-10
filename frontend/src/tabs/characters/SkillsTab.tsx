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
 * config (workflows, LoRAs, …) via separate routes — those land in their own
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

  return (
    <div className="ga-form" style={{ gap: 12 }}>
      {skills.map((skill) => {
        const fields = skill.config_fields ? Object.entries(skill.config_fields) : []
        return (
          <div
            key={skill.skill_id}
            style={{
              border: '1px solid var(--border, #30363d)',
              borderRadius: 8,
              padding: '10px 12px',
              background: 'var(--bg-alt, #0d1117)',
            }}
          >
            <label
              className="ga-form-check"
              style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontWeight: 600 }}
            >
              <input
                type="checkbox"
                checked={skill.enabled}
                onChange={(e) => toggleEnabled(skill, e.target.checked)}
              />
              <span>{skill.name || skill.skill_id}</span>
              <code style={{ opacity: 0.4, fontWeight: 400, fontSize: '0.8em' }}>
                {skill.skill_id}
              </code>
            </label>
            {skill.description && (
              <div style={{ opacity: 0.7, fontSize: '0.85em', margin: '4px 0 0 24px' }}>
                {skill.description}
              </div>
            )}
            {skill.enabled && fields.length > 0 && (
              <div className="ga-form" style={{ marginTop: 10, marginLeft: 24, gap: 8 }}>
                {fields.map(([fieldName, field]) => (
                  <SkillField
                    key={fieldName}
                    field={field}
                    label={field.label || fieldName}
                    locations={locations}
                    onChangeLocal={(v) => setFieldValue(skill.skill_id, fieldName, v)}
                    onCommit={(v) => saveField(skill.skill_id, fieldName, v)}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
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
