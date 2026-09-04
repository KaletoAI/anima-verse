/**
 * DefaultExpressionField — the ONE default expression of a temporary NPC,
 * shown as a template `special` slot (`default_expression`) on the
 * Appearance tab, next to the Body section, with a button that renders it
 * again. A display with a re-render button, NOT an input: there is no
 * profile field behind it — the default expression is the mood ""/pose ""
 * coordinate of the expression cache (`npc_assets._render_default_expression`),
 * and its prompt default comes from the pose catalog.
 *
 * Image:     GET /characters/{name}/outfit-expression?override=1
 * Re-render: GET /characters/{name}/outfit-expression?override=1&trigger=1&force=1
 *
 * WHY `override=1`: without it the route fills an empty `mood` from the
 * character's current feeling and an empty `pose_key` from its effective pose
 * key, i.e. it asks for the variant of the current MOMENT. A temporary NPC has
 * exactly one variant — mood "" and pose "" — and asking for any other one
 * would answer 404 forever, because its template's
 * `expression_variants_enabled` gate refuses to generate. `override=1` pins
 * both axes to empty; the equipped state it implies (no pieces, no items) is
 * this NPC's real one, since its template has no outfit system, so the key
 * resolves to the very file the finishing job wrote.
 *
 * WHY NO `fallback=default`: it would make this view LIE. While a render runs,
 * the route answers the fallback chain instead of 202, and step 1 of that
 * chain is `find_nearest_expression` — which scores sidecars by outfit
 * similarity, and "empty vs empty is 1.0". A temporary NPC has an EMPTY
 * equipped state in every sidecar it ever wrote, so every leftover variant
 * ties at the top and the newest one is served with 200. That is exactly the
 * picture of the OLD outfit, orphaned by the very edit that queued this render
 * and still on disk until `outfit_cache_gc` reaps it — and a 200 fires
 * `onLoad`, which stops the polling and presents it as the result. Without
 * the parameter a cache miss is 202 or 404, both of which keep the
 * "Rendering…" overlay up and the poll running until the real file lands.
 *
 * The button adds `trigger=1&force=1`: `force` deletes the cached file, and
 * `trigger` is what makes the route pass `ignore_feature_gate=True` — the one
 * documented way past the closed variant gate, the same one the finishing job
 * takes. The answer is 202 ("generating"), so the image is polled afterwards.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { openLightbox } from '../../components/Lightbox'

/** How long the re-render is polled for before the view gives up (4 s steps). */
const POLL_LIMIT = 45

/** Floor for the picture in a column that has little height to give. */
const MIN_H = 320

export function DefaultExpressionField({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [nonce, setNonce] = useState(1)
  const [polls, setPolls] = useState(0)
  const [rendering, setRendering] = useState(false)
  const [ready, setReady] = useState<boolean | null>(null)

  const base = `/characters/${encodeURIComponent(character)}/outfit-expression`
  const src = `${base}?override=1&_=${nonce}`

  useEffect(() => {
    setRendering(false)
    setPolls(0)
    setReady(null)
    setNonce((n) => n + 1)
  }, [character])

  // Poll while a render is running — the generator is a background thread, so
  // nothing tells this view when the file lands.
  useEffect(() => {
    if (!rendering) return
    if (polls >= POLL_LIMIT) {
      setRendering(false)
      return
    }
    const id = window.setTimeout(() => {
      setPolls((p) => p + 1)
      setNonce((n) => n + 1)
    }, 4000)
    return () => window.clearTimeout(id)
  }, [rendering, polls])

  const rerender = async () => {
    if (rendering) return
    setRendering(true)
    setPolls(0)
    try {
      await apiGet(`${base}?override=1&trigger=1&force=1`)
      toast(t('Rendering the default expression — this takes a moment.'))
      setReady(null)
      setNonce((n) => n + 1)
    } catch (e) {
      setRendering(false)
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }

  // The section declares `grow` in the template, so this column hands its
  // leftover height down to here: hint and button keep their natural size, the
  // picture takes the rest. MIN_H is the floor for a short column — below it
  // the picture stops shrinking and the column simply grows instead.
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 8,
      alignItems: 'stretch', height: '100%', minHeight: 0,
    }}>
      <div style={{ fontSize: '0.78em', opacity: 0.7 }}>
        {t('This character kind has no mood or pose variants — it is shown by this one default expression.')}
      </div>
      {/* The image stays MOUNTED even while it 404s: the poll works by
          changing its src, and an unmounted img would never re-fetch. */}
      <div style={{
        position: 'relative', flex: '1 1 auto', minHeight: MIN_H, width: '100%',
        borderRadius: 8,
        overflow: 'hidden', border: '1px solid var(--border, #30363d)',
        background: 'var(--bg, #0d1117)',
      }}>
        <img src={src} alt={t('Default expression')}
          onLoad={() => { setReady(true); setRendering(false) }}
          onError={() => setReady(false)}
          onClick={() => { if (ready === true) openLightbox({ src, alt: t('Default expression') }) }}
          style={{
            position: 'absolute', inset: 0,
            width: '100%', height: '100%', objectFit: 'contain',
            display: ready === true ? 'block' : 'none', cursor: 'zoom-in',
          }} />
        {ready !== true && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
            justifyContent: 'center', padding: 8, textAlign: 'center',
            fontSize: '0.76em', opacity: 0.6,
          }}>
            {/* `null` = the first load has not answered yet: say nothing
                rather than claim there is no picture. */}
            {rendering ? t('Rendering…') : ready === false ? t('No default expression yet') : ''}
          </div>
        )}
      </div>
      <button type="button" className="ga-btn ga-btn-sm" style={{ alignSelf: 'flex-start' }}
        disabled={rendering} onClick={rerender}>
        {rendering ? t('Rendering…') : t('Re-render default expression')}
      </button>
      {rendering && (
        <span style={{ fontSize: '0.74em', opacity: 0.6 }}>
          {t('The picture appears here as soon as the backend delivers it.')}
        </span>
      )}
    </div>
  )
}
