/**
 * Hand a fetched blob to the browser as a download.
 *
 * Object URLs stay alive until they are revoked, so this is the one place
 * that does the whole dance — every ZIP download in the admin UI goes
 * through it (export buttons, the collection builder).
 */
export function downloadBlob(blob: Blob, filename: string) {
  const dl = document.createElement('a')
  dl.href = URL.createObjectURL(blob)
  dl.download = filename
  document.body.appendChild(dl)
  dl.click()
  dl.remove()
  URL.revokeObjectURL(dl.href)
}
