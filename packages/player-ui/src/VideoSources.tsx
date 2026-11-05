/**
 * VideoSources — the ONE place a gallery/Instagram clip becomes a `<video>`.
 *
 * Clips are stored as H.264 MP4; the server keeps a hidden VP9 WebM copy
 * (`app/core/video_webm.py`, route `<mp4 url>/webm`). The native client shows
 * the HUD in CEF, which has no H.264 decoder, so every clip lists the WebM
 * first and the MP4 second and each engine takes what it can play.
 */
import type { VideoHTMLAttributes } from 'react'

/** URL of the WebM companion route of an MP4 URL ('' for anything else). */
export function webmCompanionUrl(url: string): string {
  const q = url.indexOf('?')
  const path = q < 0 ? url : url.slice(0, q)
  if (!/\.mp4$/i.test(path)) return ''
  return `${path}/webm${q < 0 ? '' : url.slice(q)}`
}

/** The `<source>` list for a clip: WebM first, original second. */
export function videoSourceList(url: string): { src: string; type: string }[] {
  const webm = webmCompanionUrl(url)
  return [
    ...(webm ? [{ src: webm, type: 'video/webm' }] : []),
    { src: url, type: /\.webm(\?|$)/i.test(url) ? 'video/webm' : 'video/mp4' },
  ]
}

export function VideoSources(
  { src, ...rest }: { src: string } & Omit<VideoHTMLAttributes<HTMLVideoElement>, 'src'>,
) {
  // key: a new clip must reload; React does not re-run source selection on
  // changed <source> children alone.
  return (
    <video key={src} {...rest}>
      {videoSourceList(src).map(s => <source key={s.src} src={s.src} type={s.type} />)}
    </video>
  )
}
