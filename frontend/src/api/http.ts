import type { TokenPair } from '@/types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
const ACCESS_KEY = 'atlas_access_token'
const REFRESH_KEY = 'atlas_refresh_token'
const USER_KEY = 'atlas_username'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export const tokenStore = {
  access: () => sessionStorage.getItem(ACCESS_KEY),
  refresh: () => sessionStorage.getItem(REFRESH_KEY),
  username: () => sessionStorage.getItem(USER_KEY),
  set(tokens: TokenPair, username?: string) {
    sessionStorage.setItem(ACCESS_KEY, tokens.access_token)
    sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token)
    if (username) sessionStorage.setItem(USER_KEY, username)
  },
  clear() {
    sessionStorage.removeItem(ACCESS_KEY)
    sessionStorage.removeItem(REFRESH_KEY)
    sessionStorage.removeItem(USER_KEY)
  },
}

let refreshing: Promise<string> | null = null

function handleRefreshFailure(): never {
  tokenStore.clear()
  if (!location.pathname.startsWith('/login')) location.assign('/login?expired=1')
  throw new ApiError(401, '登录状态已过期')
}

async function fetchOrApiError(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (error) {
    const reason = error instanceof Error && error.message ? `：${error.message}` : ''
    throw new ApiError(0, `网络请求失败${reason}`)
  }
}

async function refreshAccessToken(): Promise<string> {
  const refreshToken = tokenStore.refresh()
  if (!refreshToken) throw new ApiError(401, '登录状态已失效')
  const response = await fetchOrApiError(`${API_BASE}/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!response.ok) {
    tokenStore.clear()
    throw new ApiError(401, '登录状态已过期，请重新登录')
  }
  const tokens = (await response.json()) as TokenPair
  tokenStore.set(tokens)
  return tokens.access_token
}

function messageFrom(body: unknown, fallback: string) {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail) return String(detail.message)
  }
  return fallback
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  const token = tokenStore.access()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')

  const response = await fetchOrApiError(`${API_BASE}${path}`, { ...init, headers })
  if (response.status === 401 && retry && tokenStore.refresh()) {
    try {
      refreshing ||= refreshAccessToken().finally(() => { refreshing = null })
      await refreshing
      return api<T>(path, init, false)
    } catch {
      handleRefreshFailure()
    }
  }
  if (!response.ok) {
    let body: unknown
    try { body = await response.json() } catch { body = null }
    throw new ApiError(response.status, messageFrom(body, `请求失败 (${response.status})`))
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const postJson = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) })

export async function postSse(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  retry = true,
): Promise<void> {
  const headers = new Headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' })
  const token = tokenStore.access()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetchOrApiError(`${API_BASE}${path}`, {
    method: 'POST', headers, body: JSON.stringify(body),
  })
  if (response.status === 401 && retry && tokenStore.refresh()) {
    try {
      refreshing ||= refreshAccessToken().finally(() => { refreshing = null })
      await refreshing
      return postSse(path, body, onEvent, false)
    } catch {
      handleRefreshFailure()
    }
  }
  if (!response.ok || !response.body) {
    let errorBody: unknown
    try { errorBody = await response.json() } catch { errorBody = null }
    throw new ApiError(response.status, messageFrom(errorBody, `流式请求失败 (${response.status})`))
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        let event = 'message'
        const dataLines: string[] = []
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
        }
        if (dataLines.length) {
          const raw = dataLines.join('\n')
          try {
            onEvent(event, raw ? JSON.parse(raw) : {})
          } catch (error) {
            if (error instanceof SyntaxError) throw new ApiError(0, `流式响应 JSON 解析失败：${event}`)
            throw error
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
  } catch (error) {
    await reader.cancel()
    throw error
  } finally {
    reader.releaseLock()
  }
}
