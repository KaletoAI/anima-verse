import { useCallback, useEffect, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * The core block `linked_characters` of a package panel section
 * (docs/plugins.md → "Character panels"): one mind in several bodies
 * (app/core/linked_characters.py).
 *
 * A LINKED character (a body) names its leading character; the leader owns the
 * mind (memories, thoughts, secrets, the shared soul sections) and the body
 * reads gender and age live from it. Only one family member stands in the
 * world — the others are DORMANT. The server decides everything (candidates,
 * refusals); this block only shows and asks.
 *   GET    /characters/{c}/link     → LinkState
 *   PUT    /characters/{c}/link     {leader, shared_soul_sections}
 *   PUT    /characters/{body}/link  {leader: c} (link an existing character as a body of c)
 *   DELETE /characters/{c}/link     (unlink a dormant body)
 * Creating a NEW body is the embedding package's action (core `create_linked`).
 * Admin-only world authoring.
 */

interface LinkState {
  leader: string
  bodies: Array<{ name: string; status: string }>
  shared_soul_sections: string[]
  status: string
  shareable: string[]
  candidates: string[]
  /** Who may be linked to this character as a body. */
  body_candidates: string[]
}

const SECTION_LABELS: Record<string, string> = {
  soul: 'Soul',
  beliefs: 'Beliefs',
  lessons: 'Lessons',
  personality: 'Personality',
  presence: 'Presence',
  tasks: 'Tasks',
  roleplay_rules: 'Roleplay rules',
}

export function LinkedCharacterPanel({
  character,
  onOpen,
  onChanged,
}: {
  character: string
  /** Open another character in the editor. */
  onOpen: (name: string) => void
  /** The roster changed (a body was created, linked or unlinked). */
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [state, setState] = useState<LinkState | null>(null)
  const [leader, setLeader] = useState('')
  const [shared, setShared] = useState<string[]>([])
  const [newBody, setNewBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmLink, setConfirmLink] = useState(false)
  const [confirmBody, setConfirmBody] = useState(false)

  const apply = useCallback((s: LinkState) => {
    setState(s)
    setLeader(s.leader)
    setShared(s.leader ? s.shared_soul_sections : ['soul', 'beliefs', 'lessons'])
  }, [])

  const load = useCallback(async () => {
    setError('')
    try {
      apply(await apiGet<LinkState>(`/characters/${encodeURIComponent(character)}/link`))
    } catch (e) {
      setState(null)
      setError((e as Error).message)
    }
  }, [character, apply])

  useEffect(() => {
    setNewBody('')
    load()
  }, [load])

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true)
    setError('')
    try {
      const res = await fn()
      if (res && typeof res === 'object' && 'leader' in (res as object)) apply(res as LinkState)
      else await load()
      toast(t(done))
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!state) {
    return error ? <div className="ga-form"><div className="ga-pp-error">{error}</div></div>
      : <div className="ga-loading">{t('Loading…')}</div>
  }

  const isLeader = state.bodies.length > 0
  const linked = !!state.leader
  const dirtyShared = linked && (
    shared.length !== state.shared_soul_sections.length
    || shared.some((s) => !state.shared_soul_sections.includes(s)))
  const enc = encodeURIComponent(character)
  const save = () => run(
    () => apiPut(`/characters/${enc}/link`, { leader, shared_soul_sections: shared }),
    linked ? 'Saved' : 'Linked')

  return (
    <div className="ga-form">
      <div className="ga-pp-body">
        <div className="ga-pp-fields">
          <div className="ga-pp-f ga-pp-w6">
            <span className="ga-pp-label">{t('Leading character')}</span>
            {linked ? (
              <span className="ga-pp-inline">
                <strong>{state.leader}</strong>
                <button type="button" className="ga-btn ga-btn-sm" onClick={() => onOpen(state.leader)}>
                  {t('Open')}
                </button>
              </span>
            ) : (
              <select className="ga-input" value={leader} disabled={busy || isLeader}
                onChange={(e) => setLeader(e.target.value)}>
                <option value="">{isLeader ? t('Leads linked characters') : t('Not linked')}</option>
                {state.candidates.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            )}
            <span className="ga-pp-hint">
              {linked
                ? t('One mind: memories, thoughts, secrets and the shared soul sections belong to the leading character. Gender and age are read from it.')
                : t('Linking makes this character dormant. Its own memories, thoughts and secrets stay stored but are not read while it is linked.')}
            </span>
          </div>
          <div className="ga-pp-f ga-pp-w3">
            <span className="ga-pp-label">{t('Status')}</span>
            <span>
              <span className="ga-chip">{state.status === 'dormant' ? t('dormant') : t('present')}</span>
            </span>
          </div>
          <div className="ga-pp-f ga-pp-w3">
            <span className="ga-pp-label">&nbsp;</span>
            {linked ? (
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                title={state.status === 'dormant' ? '' : t('Stands in the world right now — revert first.')}
                onClick={() => run(() => apiDelete(`/characters/${enc}/link`), 'Unlinked')}>
                {t('Unlink')}
              </button>
            ) : (
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
                disabled={busy || !leader} onClick={() => setConfirmLink(true)}>
                {t('Link')}
              </button>
            )}
          </div>

          {!isLeader ? (
            <div className="ga-pp-f ga-pp-w12">
              <span className="ga-pp-label">{t('Shared soul sections (read from the leading character)')}</span>
              <span className="ga-pp-inline" style={{ flexWrap: 'wrap', gap: 14 }}>
                {state.shareable.map((s) => (
                  <label key={s} className="ga-pp-inline">
                    <input type="checkbox" checked={shared.includes(s)} disabled={busy}
                      onChange={(e) => setShared((cur) => e.target.checked
                        ? [...cur, s] : cur.filter((x) => x !== s))} />
                    {t(SECTION_LABELS[s] || s)}
                  </label>
                ))}
                {linked ? (
                  <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !dirtyShared}
                    onClick={save}>
                    {t('Save')}
                  </button>
                ) : null}
              </span>
              <span className="ga-pp-hint">{t('Goals are never shared: every body has its own.')}</span>
            </div>
          ) : null}

          {!linked ? (
            <>
              <div className="ga-pp-f ga-pp-w6">
                <span className="ga-pp-label">{t('Linked characters')}</span>
                {state.bodies.length === 0 ? (
                  <span className="ga-pp-hint">{t('None yet.')}</span>
                ) : (
                  <span className="ga-pp-inline" style={{ flexWrap: 'wrap' }}>
                    {state.bodies.map((b) => (
                      <button key={b.name} type="button" className="ga-btn ga-btn-sm"
                        onClick={() => onOpen(b.name)}>
                        {b.name}{b.status === 'dormant' ? ` · ${t('dormant')}` : ''}
                      </button>
                    ))}
                  </span>
                )}
              </div>
              <div className="ga-pp-f ga-pp-w6">
                <span className="ga-pp-label">{t('Link an existing character')}</span>
                <span className="ga-pp-inline">
                  <select className="ga-input" value={newBody} disabled={busy}
                    onChange={(e) => setNewBody(e.target.value)}>
                    <option value="">{t('— select —')}</option>
                    {(state.body_candidates || []).map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !newBody}
                    onClick={() => setConfirmBody(true)}>
                    {t('Link')}
                  </button>
                </span>
                <span className="ga-pp-hint">{t('It becomes a linked character of this one and goes dormant.')}</span>
              </div>
            </>
          ) : null}

          {error ? <div className="ga-pp-f ga-pp-w12"><div className="ga-pp-error">{error}</div></div> : null}
        </div>
      </div>

      <ConfirmDialog
        open={confirmLink}
        title={t('Link {name}?').replace('{name}', character)}
        message={t('{name} becomes dormant and leaves the world. Its own memories, thoughts and secrets stay stored but are not read while it is linked.').replace('{name}', character)}
        confirmLabel={t('Link')}
        onConfirm={() => { setConfirmLink(false); void save() }}
        onClose={() => setConfirmLink(false)}
      />
      <ConfirmDialog
        open={confirmBody}
        title={t('Link {name}?').replace('{name}', newBody)}
        message={t('{name} becomes dormant and leaves the world. Its own memories, thoughts and secrets stay stored but are not read while it is linked.').replace('{name}', newBody)}
        confirmLabel={t('Link')}
        onConfirm={() => {
          setConfirmBody(false)
          const body = newBody
          // The answer is the BODY's link state — reload this character's own.
          void run(async () => {
            await apiPut(`/characters/${encodeURIComponent(body)}/link`, { leader: character })
            setNewBody('')
            return null
          }, 'Linked')
        }}
        onClose={() => setConfirmBody(false)}
      />
    </div>
  )
}
