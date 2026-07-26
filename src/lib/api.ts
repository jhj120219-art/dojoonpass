// ================================================================
// FastAPI 백엔드(api_server.py, /api/v1/*) 호출용 최소 래퍼
// ================================================================

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: 'no-store' })
  if (!res.ok) {
    throw new Error(`API 요청 실패 (${res.status}): ${path}`)
  }
  return res.json() as Promise<T>
}
