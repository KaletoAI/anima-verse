import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Faithful React port of the legacy SoulEditor: a file bar (one button per
 * soul/*.md file with a 🟢 editable / 🔒 locked badge), a raw Markdown editor,
 * and a live structured preview that marks each ## section editable or locked.
 * Backed by /characters/{name}/soul/files and /soul/file/{section}.
 */

interface SoulSection {
  level: number
  heading: string
  body: string
  editable_marker: boolean
}

interface SoulFileMeta {
  section: string
  path: string
  file_default: string
  exists: boolean
  label?: string
  label_de?: string
}

// Mirror of the backend _parse_soul_sections (and the legacy client parser):
// split on '# ' / '## ' headings, strip the <!-- EDITABLE --> marker but
// remember it per section.
function parseSections(text: string): SoulSection[] {
  const sections: SoulSection[] = []
  let curH: string | null = null
  let curLvl = 0
  let curBody: string[] = []
  const flush = () => {
    if (curH === null && curBody.length === 0) return
    const hasMarker = curBody.some((l) => l.includes('<!-- EDITABLE -->'))
    const body = curBody
      .filter((l) => !l.includes('<!-- EDITABLE -->'))
      .join('\n')
      .trim()
    sections.push({ level: curLvl, heading: curH || '', body, editable_marker: hasMarker })
  }
  for (const line of text.split('\n')) {
    if (line.startsWith('# ') && !line.startsWith('## ')) {
      flush()
      curH = line.slice(2).trim()
      curLvl = 1
      curBody = []
    } else if (line.startsWith('## ')) {
      flush()
      curH = line.slice(3).trim()
      curLvl = 2
      curBody = []
    } else {
      curBody.push(line)
    }
  }
  flush()
  return sections
}

export function SoulEditor({ character }: { character: string }) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [files, setFiles] = useState<SoulFileMeta[]>([])
  const [section, setSection] = useState('')
  const [raw, setRaw] = useState('')
  const [fileDefault, setFileDefault] = useState('locked')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(false)

  const selectFile = useCallback(
    async (sec: string) => {
      if (dirty && !window.confirm(t('Discard unsaved changes?'))) return
      try {
        const data = await apiGet<{ raw?: string; file_default?: string }>(
          `/characters/${encodeURIComponent(character)}/soul/file/${encodeURIComponent(sec)}`,
        )
        setSection(sec)
        setRaw(data.raw || '')
        setFileDefault(data.file_default || 'locked')
        setDirty(false)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [character, dirty, t, toast],
  )

  // Load file list when the character changes; auto-select the first file.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFiles([])
    setSection('')
    setRaw('')
    setDirty(false)
    ;(async () => {
      try {
        const data = await apiGet<{ files?: SoulFileMeta[] }>(
          `/characters/${encodeURIComponent(character)}/soul/files`,
        )
        if (cancelled) return
        const list = data.files || []
        setFiles(list)
        if (list.length > 0) {
          const first = list[0].section
          const d = await apiGet<{ raw?: string; file_default?: string }>(
            `/characters/${encodeURIComponent(character)}/soul/file/${encodeURIComponent(first)}`,
          )
          if (cancelled) return
          setSection(first)
          setRaw(d.raw || '')
          setFileDefault(d.file_default || 'locked')
        }
      } catch {
        /* no soul files for this template */
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [character])

  const save = useCallback(async () => {
    if (!section) return
    setSaving(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/soul/file/${encodeURIComponent(section)}`, {
        content: raw,
      })
      setDirty(false)
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [character, raw, section, t, toast])

  const sections = useMemo(() => parseSections(raw), [raw])

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>
  if (files.length === 0)
    return <div className="ga-placeholder">{t('No soul files enabled for this template.')}</div>

  return (
    <div className="soul-tab">
      <div className="soul-files-bar">
        {files.map((f) => {
          const lock = f.file_default === 'editable' ? '🟢' : '🔒'
          // Freundliches Label aus dem Template (DE/EN) statt der Roh-Section-ID.
          const name =
            (lang === 'de' && f.label_de) ||
            f.label ||
            f.section.charAt(0).toUpperCase() + f.section.slice(1)
          return (
            <button
              key={f.section}
              type="button"
              title={f.path}
              className={`soul-file-btn${section === f.section ? ' active' : ''}`}
              onClick={() => selectFile(f.section)}
            >
              {lock} {name}
              {f.exists ? '' : ' ' + t('(empty)')}
            </button>
          )
        })}
      </div>
      <div className="soul-editor-grid">
        <div className="soul-editor-col">
          <div className="soul-col-header">
            <span>{t('Editor (Markdown)')}</span>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={!dirty || saving}
              onClick={save}
            >
              {saving ? t('Saving…') : t('Save')}
            </button>
          </div>
          <textarea
            className="soul-editor"
            spellCheck={false}
            value={raw}
            placeholder={t('Pick a file above…')}
            onChange={(e) => {
              setRaw(e.target.value)
              setDirty(true)
            }}
          />
        </div>
        <div className="soul-preview-col">
          <div className="soul-col-header">
            <span>{t('Preview')}</span>
            <span className="soul-legend">
              <span className="soul-legend-item soul-legend-editable">{t('Editable (character)')}</span>
              <span className="soul-legend-item soul-legend-locked">{t('Locked')}</span>
            </span>
          </div>
          <div className="soul-preview">
            {sections.length === 0 ? (
              <p className="ga-placeholder">{t('(empty)')}</p>
            ) : (
              sections.map((sec, i) => {
                if (sec.level === 1) {
                  return (
                    <div key={i}>
                      <h3 className="soul-h1">{sec.heading}</h3>
                      {sec.body ? <div className="soul-body">{sec.body}</div> : null}
                    </div>
                  )
                }
                const isEditable = fileDefault === 'editable' ? true : sec.editable_marker
                return (
                  <div key={i} className={isEditable ? 'soul-section soul-editable' : 'soul-section soul-locked'}>
                    <h4 className="soul-h2">
                      <span className="soul-section-name">{sec.heading}</span>
                      <span className="soul-section-badge">
                        {isEditable ? '🟢 ' + t('editable') : '🔒 ' + t('locked')}
                      </span>
                    </h4>
                    <div className={sec.body ? 'soul-body' : 'soul-body soul-empty'}>
                      {sec.body || t('(empty)')}
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
