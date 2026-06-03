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

function redirectToLogin(): never {
  const ret = encodeURIComponent(window.location.pathname + window.location.hash)
  window.location.href = `/?return=${ret}`
  // The redirect cancels execution; the throw is just for the type system.
  throw new Error('redirecting to login')
}

async function parseJsonOrThrow(res: Response): Promise<any> {
  let body: any = null
  try {
    body = await res.json()
  } catch {
    /* leave body null */
  }
  // 401 = nicht eingeloggt → Login. 403 = entweder "nicht Admin" (Auth → Login)
  // ODER eine Game-Block-Regel (z.B. Bewegung während eines Events gesperrt) —
  // Letzteres ist KEIN Auth-Fehler und darf NICHT zur (alten) Login-UI umleiten.
  if (res.status === 401) redirectToLogin()
  if (res.status === 403) {
    const d = body && typeof body === 'object' ? (body.detail ?? body) : body
    const reason = d && typeof d === 'object' ? String(d.reason || '') : ''
    const isGameBlock = reason.startsWith('block_') || reason === 'not_at_entry_room'
    if (!isGameBlock) redirectToLogin()
  }
  if (!res.ok) {
    const detail = body && typeof body === 'object' ? body.detail ?? body : body
    const msg = typeof detail === 'string' ? detail : `HTTP ${res.status}`
    throw new ApiError(res.status, detail, msg)
  }
  return body
}

const COMMON: RequestInit = { credentials: 'same-origin' }

export async function apiGet<T = any>(path: string): Promise<T> {
  const res = await fetch(path, { ...COMMON, method: 'GET' })
  return parseJsonOrThrow(res)
}

export async function apiPut<T = any>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    ...COMMON,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(res)
}

export async function apiPost<T = any>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    ...COMMON,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(res)
}

export async function apiPatch<T = any>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    ...COMMON,
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(res)
}

export async function apiDelete<T = any>(path: string): Promise<T> {
  const res = await fetch(path, { ...COMMON, method: 'DELETE' })
  return parseJsonOrThrow(res)
}
