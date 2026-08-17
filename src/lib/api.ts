// ================================================================
// FastAPI 백엔드(api_server.py, /api/v1/*) 호출용 최소 래퍼
// ================================================================

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  // 서버가 준 사람이 읽을 수 있는 사유(`{"detail": "..."}`). 없으면 undefined.
  //
  // ★ 2026-08-17 Sprint 162: 예전에는 응답 본문을 **통째로 버렸다.** 백엔드는
  //   `허용되지 않는 sort_by 값입니다: BOGUS` 처럼 정확한 사유를 주는데, 화면은 그걸 못 받아
  //   고정 문구만 띄웠다(실측). 그 고정 문구가 하필 페이지/개수만 언급해서, sort_by가 틀린
  //   사용자는 **엉뚱한 곳을 고치라는 안내**를 받았다.
  //
  //   문자열일 때만 담는다 — FastAPI 검증 오류(`page=0`, `size=99999`)의 `detail`은
  //   영어 객체 **배열**이라 사용자에게 보여줄 것이 못 된다. 그때는 undefined로 두고
  //   호출부의 기존 안내 문구로 떨어진다.
  detail?: string
  constructor(status: number, message: string, detail?: string) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

// 실패 응답에서 사람이 읽을 수 있는 사유만 뽑는다. 본문이 JSON이 아니거나
// `detail`이 문자열이 아니면 undefined(= 호출부가 기존 문구를 쓴다).
async function readDetail(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : undefined
  } catch {
    return undefined
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
    throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`, await readDetail(res))
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
