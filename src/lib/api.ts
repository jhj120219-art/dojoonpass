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
// (api/auth.py의 success()/fail()/error_response())
//
// `error`는 도메인 Error Code(docs/ERROR_CODES.md)다. **분기는 message가 아니라 error로 한다** —
// message는 사용자에게 보여줄 한국어 문구라 언제든 바뀌고, 문구 비교는 조용히 깨진다.
// `message`는 하위호환을 위해 유지된다.
export interface ApiEnvelope<T> {
  success: boolean
  data: T | null
  error: string | null
  meta: Record<string, unknown> | null
  message: string | null
}

// 클라이언트가 분기에 쓰는 Error Code. 서버 `api/constants.py:ErrorCode`와 값이 같아야 한다.
export const ERROR_CODES = {
  FAVORITE_ALREADY_EXISTS: 'FAVORITE_ALREADY_EXISTS',
  FAVORITE_NOT_FOUND: 'FAVORITE_NOT_FOUND',
  REGISTRY_SUBSCRIPTION_REQUIRED: 'REGISTRY_SUBSCRIPTION_REQUIRED',
} as const

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

// 응답이 JSON envelope일 수도, 실제 파일(예: 등기부 다운로드)일 수도 있는 엔드포인트 전용.
// 다른 래퍼와 달리 !res.ok에서도 던지지 않는다 — 호출부(registry-requests/{id}/download)가
// Content-Type/상태코드를 직접 보고 "파일" vs "아직 미완료(JSON fail)"를 구분해야 하기 때문.
export async function fetchAuthedRaw(path: string, token: string): Promise<Response> {
  return fetch(`${API_BASE_URL}${path}`, {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
  })
}
