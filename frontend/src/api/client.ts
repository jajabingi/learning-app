import { tError } from '@/i18n'

const KEY = 'recall.tokens'

export interface Tokens {
  access_token: string
  refresh_token: string
}

export const tokenStore = {
  get(): Tokens | null {
    try {
      const raw = localStorage.getItem(KEY)
      return raw ? (JSON.parse(raw) as Tokens) : null
    } catch {
      return null
    }
  },
  set(t: Tokens | null) {
    try {
      if (t) localStorage.setItem(KEY, JSON.stringify(t))
      else localStorage.removeItem(KEY)
    } catch {
      /* storage unavailable */
    }
  },
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>

function qs(params?: Params) {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)))
    else sp.append(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

let refreshing: Promise<boolean> | null = null
let onAuthLost: (() => void) | null = null
export const setAuthLostHandler = (fn: () => void) => (onAuthLost = fn)

async function refresh(): Promise<boolean> {
  const t = tokenStore.get()
  if (!t) return false
  refreshing ??= fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) return false
      tokenStore.set(await r.json())
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

async function errorOf(r: Response): Promise<ApiError> {
  let msg = r.statusText || 'Request failed'
  try {
    const j = await r.json()
    if (typeof j.detail === 'string') msg = j.detail
  } catch {
    /* not json */
  }
  return new ApiError(r.status, tError(msg))
}

export async function raw(path: string, init: RequestInit & { params?: Params } = {}, retry = true): Promise<Response> {
  const { params, ...rest } = init
  const headers = new Headers(rest.headers)
  const t = tokenStore.get()
  if (t) headers.set('Authorization', `Bearer ${t.access_token}`)
  const r = await fetch(`/api${path}${qs(params)}`, { ...rest, headers })
  if (r.status === 401 && retry && t && !path.startsWith('/auth/')) {
    if (await refresh()) return raw(path, init, false)
    tokenStore.set(null)
    onAuthLost?.()
  }
  return r
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; params?: Params; form?: FormData } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const r = await raw(path, { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body, params: opts.params })
  if (!r.ok) throw await errorOf(r)
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

export async function download(path: string, filename: string) {
  const r = await raw(path)
  if (!r.ok) throw await errorOf(r)
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const get = <T>(path: string, params?: Params) => api<T>(path, { params })
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

/** Upload with progress (fetch cannot report upload progress). Used for large video files. */
export function uploadWithProgress<T>(path: string, file: File, onProgress: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = tokenStore.get()
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api${path}`)
    if (t) xhr.setRequestHeader('Authorization', `Bearer ${t.access_token}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100))
    xhr.onerror = () => reject(new ApiError(0, 'Network error during upload'))
    xhr.onload = () => {
      let body: any = null
      try { body = JSON.parse(xhr.responseText) } catch { /* not json */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else reject(new ApiError(xhr.status, typeof body?.detail === 'string' ? body.detail : 'Upload failed'))
    }
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}
