/**
 * Thin fetch wrapper.
 *
 * - Sends credentials so session cookies travel with the request (the
 *   FastAPI server expects them for `require_admin`).
 * - On 401 (and only 401) redirects to the login page just like the legacy
 *   admin pages did, with a return URL so the user lands back here after
 *   signing in. A 403 is a refusal, not a missing session.
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
  // Only 401 means "not logged in" — that is the ONE status that may swap the
  // page for the login form. A 403 is a refusal by the running game (a block
  // rule, a missing entrance, a party follower without movement rights, …);
  // it travels on as a normal ApiError so the caller can toast the reason.
  // Deciding this by a reason allowlist logged the player out on every refusal
  // the list did not yet know.
  if (res.status === 401) redirectToLogin()
  if (!res.ok) {
    const detail = asRecord(body)?.detail ?? body
    const msg = typeof detail === 'string' ? detail : `HTTP ${res.status}`
    throw new ApiError(res.status, detail, msg)
  }
  // HTML on an OK response is never a real answer — it is a dev server (or a
  // reverse proxy) that does not forward this prefix and hands back its SPA
  // index instead. Without this the caller would just get `null` and blow up
  // far from the cause; that is how a missing /diary rule in client3d's Vite
  // proxy surfaced as "Cannot read properties of null" inside MindPanel. An
  // empty body with no content type (204 from a DELETE) stays legal.
  if (body === null && (res.headers.get('content-type') || '').includes('html')) {
    throw new ApiError(res.status, null,
      `${res.url || 'request'}: expected JSON, got HTML — is this path proxied to the API?`)
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
