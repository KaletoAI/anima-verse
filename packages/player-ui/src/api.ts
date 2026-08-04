/**
 * Thin fetch wrapper.
 *
 * - Sends credentials so session cookies travel with the request (the
 *   FastAPI server expects them for `require_admin`).
 * - On 401/403 redirects to the login page just like the legacy admin
 *   pages did, with a return URL so the user lands back here after
 *   signing in.
 * - Returns parsed JSON; on non-OK status throws an `ApiError` carrying
 *   the server-provided detail when available so call sites can surface
 *   a useful toast.
 */

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown, message: string) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

/** Narrow an unknown JSON body to an index-able object, or null. */
function asRecord(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : null
}

function redirectToLogin(): never {
  // Inform the AuthGate (same page) to show its own login form instead of
  // jumping to the legacy /-UI. The throw cancels the current call.
  window.dispatchEvent(new CustomEvent('auth:required'))
  throw new Error('auth required')
}

async function parseJsonOrThrow(res: Response): Promise<unknown> {
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    /* leave body null */
  }
  // 401 = not logged in → login. 403 = either "not an admin" (auth → login) OR
  // a game block rule (e.g. movement locked during an event) — the latter is
  // NOT an auth error and must NOT redirect to the (old) login UI.
  if (res.status === 401) redirectToLogin()
  if (res.status === 403) {
    const d = asRecord(body)?.detail ?? body
    const reason = String(asRecord(d)?.reason || '')
    const isGameBlock = reason.startsWith('block_') || reason === 'not_at_entry_room'
    if (!isGameBlock) redirectToLogin()
  }
  if (!res.ok) {
    const detail = asRecord(body)?.detail ?? body
    const msg = typeof detail === 'string' ? detail : `HTTP ${res.status}`
    throw new ApiError(res.status, detail, msg)
  }
  return body
}

const COMMON: RequestInit = { credentials: 'same-origin' }

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const res = await fetch(path, { ...COMMON, method: 'GET' })
  return parseJsonOrThrow(res) as Promise<T>
}

export async function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    ...COMMON,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(res) as Promise<T>
}

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    ...COMMON,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(res) as Promise<T>
}

export async function apiPatch<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    ...COMMON,
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(res) as Promise<T>
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
  const res = await fetch(path, { ...COMMON, method: 'DELETE' })
  return parseJsonOrThrow(res) as Promise<T>
}

/**
 * Scene recipe of an UNSAVED location draft (shared/schnittstellen-3d.md
 * § B3): the server composes the complete 3D scene — plates, walls, extras,
 * model placement specs, figures, markers, exits — and the caller only
 * renders it. Same payload as GET /play/locations/{id}/scene, nothing is
 * persisted. Admin-only.
 */
export async function postScenePreview<T = unknown>(draft: unknown): Promise<T> {
  return apiPost<T>('/play/scene-preview', draft)
}

/**
 * Multipart upload. The browser sets the multipart Content-Type (with the
 * boundary) itself, so we must NOT set it manually. Field name defaults to
 * "file" to match the FastAPI upload routes.
 */
export async function apiUpload<T = unknown>(
  path: string,
  file: File,
  field = 'file',
  extra?: Record<string, string>,
): Promise<T> {
  const fd = new FormData()
  fd.append(field, file)
  for (const [k, v] of Object.entries(extra || {})) fd.append(k, v)
  const res = await fetch(path, { ...COMMON, method: 'POST', body: fd })
  return parseJsonOrThrow(res) as Promise<T>
}
