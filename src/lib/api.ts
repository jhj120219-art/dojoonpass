// ================================================================
// FastAPI 백엔드(api_server.py, /api/v1/*) 호출용 최소 래퍼
// ================================================================

// ★ 기본값이 `localhost` 가 아니라 **`127.0.0.1`** 이다 (2026-09-04 실측으로 교체).
//
// `api_server.py` 는 `uvicorn.run(..., host="127.0.0.1")` 로 **IPv4 루프백에만**
// 바인딩한다(보안상 의도된 선택이고 `docs/CLAUDE.md` 에 적혀 있다). 그런데 Windows 에서
// `localhost` 는 **`::1`(IPv6) 로 먼저 해석된다.** 그 주소에는 아무도 듣고 있지 않으므로
// 연결이 타임아웃될 때까지 기다렸다가 IPv4 로 폴백한다.
//
// 실측(2026-09-04, 이 개발 머신):
//
//     http://localhost:8000/api/v1/search   p50  2,044ms
//     http://127.0.0.1:8000/api/v1/search   p50      5.7ms      <- 360배
//     서버 내부(TestClient) 같은 요청        p50      5.5ms
//
// 즉 **서버는 5ms 인데 화면은 2초를 기다린다.** 느린 것이 아니라 아무것도 안 하고
// 기다리는 시간이고, 화면 하나가 여러 번 부르면 그만큼 곱해진다 — 이 제품이 줄이겠다고
// 말한 시간(T2D)을 개발/QA 환경에서 통째로 되돌리고 있었다.
//
// ★ 배포에는 영향이 없다 — `NEXT_PUBLIC_API_BASE_URL` 이 있으면 그것이 이긴다.
//   바뀌는 것은 **그 변수를 주지 않았을 때의 기본값**뿐이고, 그 값은 서버가 실제로
//   바인딩하는 주소와 같아야 한다. `check_release_build.py` 가 배포 빌드에서 이
//   fallback 이 박혔 나가는 것을 여전히 잡는다.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000'

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

// ================================================================
// 요청 타임아웃 (2026-08-24 Sprint 252 신설)
//
// 왜 필요한가 — **이 파일의 fetch에는 시간 제한이 하나도 없었다.**
// 실측(black-hole TCP 서버: 연결은 받고 한 바이트도 응답하지 않음):
//
//     타임아웃 없음  : 15,000ms 경과 후에도 pending (끝나지 않는다)
//     AbortSignal 3s : 3,007ms 만에 TimeoutError 로 종료
//
// 백엔드가 멈추거나(락 대기, 디스크, 크롤러가 물고 있는 커넥션) 네트워크가 죽으면
// 화면은 `불러오는 중...` 에서 **영원히** 멈춘다. 사용자에게는 "느리다"가 아니라
// "고장났는데 아무 말도 없다"로 보이고, 새로고침 말고는 빠져나갈 방법이 없다.
//
// 고칠 곳이 화면이 아니라 여기인 이유: 각 화면에는 **이미 실패 UI가 있다.**
//     properties/[id]  -> loadError='unavailable' ("일시적인 오류일 수 있습니다")
//     favorites        -> setError('관심물건을 불러오지 못했습니다')
//     recent/mypage/presets -> 같은 모양
// 타임아웃이 없어서 그 UI에 **도달하지 못하고** 있었을 뿐이다. 즉 새 화면을 만드는
// 것이 아니라 이미 있는 경로를 살리는 변경이다.
//
// ★ `AbortSignal.timeout()` 대신 AbortController + setTimeout 을 쓴다 —
//   동작은 같고 지원 범위가 더 넓다. `clearTimeout` 을 반드시 부른다(응답이 빨리
//   오면 타이머가 남아 프로세스/탭에 불필요한 작업을 남긴다).
//
// ★ 타임아웃은 `ApiError(408)` 로 바꿔 던진다. 그대로 DOMException 을 흘리면
//   호출부의 `err instanceof ApiError` 분기를 전부 비껴가, 화면마다 처리가 갈린다.
//   408 로 통일하면 기존 분기(401/403/404/400·422)에 걸리지 않고 **각 화면의
//   일반 실패 경로**로 정확히 떨어진다.
// ================================================================
// 값의 근거 (2026-08-24 실측):
//   /api/v1/search 등 JSON 엔드포인트 HTTP 왕복 p50 4~17ms / p95 ~30ms (dev 서버 기준),
//   DB 계층은 p95 ≤ 1.5ms. 즉 정상 요청은 **8초 근처에도 가지 않는다.**
//   한도를 더 크게 잡을수록 "고장인데 아무 말 없는 시간"만 길어진다.
//   반대로 너무 짧으면 느린 회선에서 정상 요청을 끊으므로, 실측 p95의 250배 이상인
//   8초를 택했다. (tests/api-timeout.test.mjs 가 이 값이 정상 응답을 죽이지 않는지 검증한다.)
export const REQUEST_TIMEOUT_MS = 8000     // JSON API
export const DOWNLOAD_TIMEOUT_MS = 60000   // 등기부 PDF 등 파일 응답. 크게 잡는다.

export const TIMEOUT_STATUS = 408

// ================================================================
// ★ 2026-08-24 Sprint 253 — Sprint 252 의 타임아웃은 **헤더까지만** 보호했다
//
// 첫 판은 `timedFetch()` 가 `Response` 를 돌려주고 `finally` 에서 `clearTimeout` 했다.
// 그런데 `Response` 는 **헤더가 도착한 시점**에 나온다 — 본문(`res.json()`/`res.blob()`)은
// 그 뒤에 호출부에서 읽는다. 즉 타이머가 이미 해제된 뒤였다.
//
// 실측(헤더는 200/content-length 100000 으로 정상 전송하고 본문을 10바이트만 보낸 뒤
//       연결을 유지한 채 멈추는 서버):
//
//     REQUEST_TIMEOUT_MS = 8000 인데 14,000ms 관찰 후에도 **여전히 pending**
//
// 고치려던 실패 모양이 한 층 아래에 그대로 남아 있었던 셈이다. 현실적인 시나리오다 —
// 백엔드가 응답을 흘리기 시작한 뒤 느린 쿼리에서 막히거나, 중간 프록시가 스트림 도중
// 죽으면 정확히 이 모양이 된다.
//
// 그래서 요청 전체(**헤더 + 상태 판정 + 본문 파싱**)를 한 타이머 안에 넣는다.
// `consume` 을 받아 그 안에서 본문을 읽고, 다 읽은 뒤에야 타이머를 해제한다.
//
// ★ 호출부가 준 `signal` 을 **버리지 않는다**
//   첫 판은 `{ ...init, signal: controller.signal }` 로 **덮어썼다.** 지금 signal 을
//   넘기는 호출부는 없지만 `RequestInit` 은 그것을 허용하므로, 언젠가 화면이
//   "이동하면 이전 요청 취소"를 붙이는 순간 조용히 무시된다. 두 신호를 연결하고
//   **어느 쪽이 먼저 끊었는지 구분**한다 — 사용자 취소는 원래 AbortError 그대로
//   올려보내야 화면이 "실패"로 오해하지 않는다.
//   (`AbortSignal.any()` 는 지원 범위가 좁아 쓰지 않는다.)
// ================================================================
type Consume<T> = (res: Response) => Promise<T>

/** 요청이 끊겼을 때 **누가 끊었는가**를 정한다. `'caller'` 면 사용자 취소, `'timeout'` 이면 우리 시한.
 *
 * ★ 왜 따로 떼어 냈나 (2026-08-24 Sprint 253) — mutation survivor 를 없애기 위해서다.
 *   원래는 catch 안에 `if (callerSignal?.aborted && !timedOut) throw err` 로 있었다.
 *   그 줄을 지우는 변이를 넣어도 테스트가 **전부 통과했다**. 이유는 테스트 공백이 아니라
 *   *동등 변이*였다 — 사용자 취소만 일어난 경우엔 `timedOut` 이 false 라서 그 줄이 없어도
 *   결국 같은 `throw err` 로 떨어진다. 두 판정이 갈리는 것은 **둘이 동시에 성립한 경쟁**
 *   (시한이 방금 터졌는데 사용자도 취소함)뿐이고, 그 창은 마이크로초 단위라 HTTP 테스트로
 *   결정적으로 재현할 수 없다.
 *
 *   그래서 규칙만 순수 함수로 꺼냈다. 이제 `abortReason(true, true) === 'caller'` 를 직접
 *   단언할 수 있고, 우선순위를 뒤집는 변이는 즉시 죽는다.
 *
 *   우선순위가 이 방향인 이유: 사용자가 스스로 취소한 것을 서버 장애(408)로 보고하면
 *   화면이 "서버가 응답하지 않습니다"를 띄운다 — 사용자가 방금 한 행동의 결과인데
 *   제품이 고장난 것처럼 보인다. 취소는 실패가 아니다.
 */
export function abortReason(callerAborted: boolean, timedOut: boolean): 'caller' | 'timeout' | 'other' {
  if (callerAborted) return 'caller'
  if (timedOut) return 'timeout'
  return 'other'
}

async function timedRequest<T>(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  path: string,
  consume: Consume<T>,
): Promise<T> {
  const controller = new AbortController()
  const callerSignal = init.signal ?? null
  let timedOut = false

  const onCallerAbort = () => controller.abort()
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort()
    else callerSignal.addEventListener('abort', onCallerAbort, { once: true })
  }

  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    const res = await fetch(url, { ...init, signal: controller.signal })
    // 본문 소비까지 **같은 타이머 안에서** 한다 — 여기가 Sprint 252 의 구멍이었다.
    return await consume(res)
  } catch (err) {
    // 누가 끊었는지는 `abortReason()` 하나가 정한다(위 주석 참고).
    // 사용자 취소는 원래 오류를 그대로 올려보낸다 — 408 로 위장하면 화면이
    // "서버가 응답하지 않습니다"를 띄워, 사용자가 방금 한 취소를 장애로 오해한다.
    if (abortReason(Boolean(callerSignal?.aborted), timedOut) === 'timeout') {
      throw new ApiError(
        TIMEOUT_STATUS,
        `API 응답 시간 초과 (${timeoutMs}ms): ${path}`,
        '서버가 응답하지 않습니다. 잠시 후 다시 시도해주세요',
      )
    }
    throw err
  } finally {
    clearTimeout(timer)
    if (callerSignal) callerSignal.removeEventListener('abort', onCallerAbort)
  }
}

// 상태 판정 + JSON 파싱을 **타이머 안에서** 하는 공통 consume.
// `!res.ok` 의 `readDetail(res)` 도 본문을 읽으므로 반드시 여기 있어야 한다.
function jsonConsumer<T>(path: string): Consume<T> {
  return async (res) => {
    if (!res.ok) {
      throw new ApiError(res.status, `API 요청 실패 (${res.status}): ${path}`, await readDetail(res))
    }
    return (await res.json()) as T
  }
}

// `signal` 은 선택이다 — 넘기면 사용자 취소로 존중되고, 안 넘기면 타임아웃만 걸린다
// (지금 넘기는 화면은 없다. 그래도 계약을 열어 두는 이유는 위 timedRequest 주석 참고).
export async function fetchJSON<T>(path: string, token?: string, signal?: AbortSignal): Promise<T> {
  const headers: HeadersInit | undefined = token ? { Authorization: `Bearer ${token}` } : undefined
  return timedRequest<T>(`${API_BASE_URL}${path}`, { cache: 'no-store', headers, signal },
                         REQUEST_TIMEOUT_MS, path, jsonConsumer<T>(path))
}

// `!res.ok` 의 `detail` 전달은 Sprint 162 가 fetchJSON 에만 넣었던 것을 Sprint 252 에
// 나머지 래퍼로 맞춘 것이다 — 지금 이 값을 읽는 화면은 SearchScreen 하나뿐이라 보이는
// 동작은 같지만, 넷 중 하나만 사유를 담으면 다음 사람이 조용히 undefined 를 받는다.
// Sprint 253 부터는 `jsonConsumer()` 하나가 그 규칙을 물고 있어 래퍼마다 갈릴 수 없다.
export async function postJSON<T>(path: string, body: unknown, token: string,
                                  signal?: AbortSignal): Promise<ApiEnvelope<T>> {
  return timedRequest<ApiEnvelope<T>>(`${API_BASE_URL}${path}`, {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal,
  }, REQUEST_TIMEOUT_MS, path, jsonConsumer<ApiEnvelope<T>>(path))
}

// PUT. `postJSON` 과 계약이 같다(타임아웃/detail 전달/envelope). 2026-08-28 Sprint 270 에
// 관심물건 메모 편집(`PUT /api/v1/favorites/{id}/note`)이 처음 PUT 을 쓰면서 추가했다.
// 화면에서 맨 fetch 를 부르지 않는다는 규칙을 지키기 위해 여기에 둔다
// (`tests/api-timeout.test.mjs` 가 그 규칙을 잠근다).
export async function putJSON<T>(path: string, body: unknown, token: string,
                                 signal?: AbortSignal): Promise<ApiEnvelope<T>> {
  return timedRequest<ApiEnvelope<T>>(`${API_BASE_URL}${path}`, {
    method: 'PUT',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal,
  }, REQUEST_TIMEOUT_MS, path, jsonConsumer<ApiEnvelope<T>>(path))
}

export async function deleteJSON<T>(path: string, token: string,
                                    signal?: AbortSignal): Promise<ApiEnvelope<T>> {
  return timedRequest<ApiEnvelope<T>>(`${API_BASE_URL}${path}`, {
    method: 'DELETE',
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
    signal,
  }, REQUEST_TIMEOUT_MS, path, jsonConsumer<ApiEnvelope<T>>(path))
}

// GET이지만 인증 필요 라우트(recent-items, search-presets 등)라 envelope 응답을 반환하는 것들 전용
export async function fetchAuthedJSON<T>(path: string, token: string,
                                         signal?: AbortSignal): Promise<ApiEnvelope<T>> {
  return timedRequest<ApiEnvelope<T>>(`${API_BASE_URL}${path}`, {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
    signal,
  }, REQUEST_TIMEOUT_MS, path, jsonConsumer<ApiEnvelope<T>>(path))
}

// 응답이 JSON envelope일 수도, 실제 파일(예: 등기부 다운로드)일 수도 있는 엔드포인트 전용.
// 다른 래퍼와 달리 !res.ok에서도 던지지 않는다 — 호출부(registry-requests/{id}/download)가
// Content-Type/상태코드를 직접 보고 "파일" vs "아직 미완료(JSON fail)"를 구분해야 하기 때문.
//
// 타임아웃만은 다른 래퍼와 같은 이유로 건다. 다만 파일 응답이라 **한도가 다르다**
// (DOWNLOAD_TIMEOUT_MS) — JSON과 같은 8초를 걸면 정상적인 큰 문서 다운로드를 끊는다.
//
// ★ 2026-08-24 Sprint 253 — 본문을 **타이머 안에서 다 받아** 새 Response 로 돌려준다.
//   호출부는 `res.ok` / `res.headers` / `res.json()` / `res.blob()` 를 그대로 쓰므로
//   계약은 하나도 바뀌지 않는다. 바뀐 것은 "본문이 중간에 멈추면 60초 뒤 끊긴다"는 점이다 —
//   Response 를 그대로 넘기면 본문 읽기가 타이머 밖이라 영원히 매달릴 수 있었다(실측).
//
//   전체 버퍼링이 낭비처럼 보이지만, 호출부가 이미 `res.blob()` 으로 전량을 읽는다
//   (등기부 PDF 를 링크로 만들어 저장한다). 즉 메모리 사용량은 바뀌지 않는다.
export async function fetchAuthedRaw(path: string, token: string,
                                     signal?: AbortSignal): Promise<Response> {
  return timedRequest<Response>(`${API_BASE_URL}${path}`, {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
    signal,
  }, DOWNLOAD_TIMEOUT_MS, path, async (res) => {
    const buf = await res.arrayBuffer()
    return new Response(buf, {
      status: res.status,
      statusText: res.statusText,
      headers: res.headers,
    })
  })
}

// HEAD 로 "이 자산이 실제로 열리는가"만 묻는다. 본문을 받지 않는다.
//
// 2026-08-24 Sprint 252: `properties/[id]/page.tsx` 가 문서 뷰어를 열기 전에 이 확인을
// **맨 fetch 로** 하고 있었다(이 파일 밖의 유일한 fetch였다). 시간 제한이 없어서, 백엔드가
// 멈추면 `.then`/`.catch` 어느 쪽도 불리지 않고 뷰어가 확인 상태에 그대로 남았다.
// 여기로 옮겨 다른 요청과 같은 한도를 적용한다 — 그리고 "네트워크 호출은 api.ts 한 곳"
// 이라는 규칙을 되살린다(tests/api-timeout.test.mjs 가 그 규칙을 잠근다).
//
// 실패(타임아웃/네트워크/4xx/5xx)는 전부 false 다 — 호출부가 원하는 것은 "보여 줘도 되나"
// 하나뿐이라, 실패 사유를 나눌 이유가 없다.
// ★ `cache: 'no-store'` 를 반드시 함께 준다. 옮겨 오기 전의 맨 fetch 에는 이것이 **없었다** —
//   브라우저가 이 HEAD 응답을 재사용하면, 이미 사라진 문서에 대해 뷰어가 열린다
//   (`test_search.py` 의 "옛 값을 보여줄 경로가 없는가" 가 이 누락을 잡아 줬다).
export async function headOk(path: string, signal?: AbortSignal): Promise<boolean> {
  try {
    return await timedRequest<boolean>(`${API_BASE_URL}${path}`,
                                       { method: 'HEAD', cache: 'no-store', signal },
                                       REQUEST_TIMEOUT_MS, path,
                                       async (res) => res.ok)
  } catch {
    return false
  }
}
