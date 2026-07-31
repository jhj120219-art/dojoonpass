// ================================================================
// FastAPI 백엔드(api_server.py, /api/v1/*) 호출용 최소 래퍼
// ================================================================

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Backend가 인증 필요 라우트(favorites 등)에서 공통으로 쓰는 응답 포맷
// ({"success", "data", "message"} — api/auth.py의 success()/fail())
export interface ApiEnvelope<T> {
  success: boolean
  data: T | null
  message: string | null
}

export async function fetchJSON<T>(path: string, token?: string): Promise<T> {
  const headers: HeadersInit | undefined = token ? { Authorization: `Bearer ${token}` } : undefined
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: 'no-store', headers })
  if (!res.ok) {
    throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`)
  }
  return res.json() as Promise<T>
}

export async function postJSON<T>(path: string, body: unknown, token: string): Promise<ApiEnvelope<T>> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`)
  }
  return res.json() as Promise<ApiEnvelope<T>>
}

export async function deleteJSON<T>(path: string, token: string): Promise<ApiEnvelope<T>> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'DELETE',
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`)
  }
  return res.json() as Promise<ApiEnvelope<T>>
}

// GET이지만 인증 필요 라우트(recent-items, search-presets 등)라 envelope 응답을 반환하는 것들 전용
export async function fetchAuthedJSON<T>(path: string, token: string): Promise<ApiEnvelope<T>> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`)
  }
  return res.json() as Promise<ApiEnvelope<T>>
}
