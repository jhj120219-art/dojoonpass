# Sprint 127 ― Sprint 126이 발견만 하고 미룬 보안 헤더 중, 정책 결정이 필요 없는 것들을 실제로 적용했다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT126_SECURITY_HEADERS_GAP.md`
>
> **별도 파일 이유**: Sprint 100~126과 같다.

Sprint 126은 보안 응답 헤더 부재를 발견하고 "CSP 등은 허용 출처 결정이 필요해 승인
영역"이라며 전부 SKIP했다. 다시 보니 **그 SKIP이 필요한 항목(CSP)과 필요 없는
항목(X-Frame-Options 등)을 구분하지 않고 뭉뚱그렸다.** 이번 세션은 그 구분을
다시 하고, 결정이 필요 없는 항목은 실제로 적용했다.

---

## 실제로 적용한 것

### 1. `poweredByHeader: false`

기본값(true)이면 모든 응답에 `X-Powered-By: Next.js`가 붙는다 — Sprint 125가 조사한
Next.js 프레임워크 특정 CVE들의 정찰(recon) 단계를 그냥 도와주는 헤더다. 이 헤더를
읽는 코드는 저장소 전체에 없다(`grep` 0건) — 순수 정보 노출만 없앤다.

### 2. `headers()` — 정책 결정이 필요 없는 4개

| 헤더 | 값 | 정책 결정이 필요 없는 이유 |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | "무엇을 허용할지" 목록이 없다 — 브라우저의 MIME 추측을 끄기만 한다. 파일 응답은 이미 `mimetypes.guess_type()`으로 Content-Type을 명시(`api/v1/registry.py`/`api/v1/documents.py`)해 스니핑에 의존하지 않는다 |
| `X-Frame-Options` | `DENY` | 이 앱이 **남에게 담기는 것**을 막는다. 이 앱이 iframe으로 **담는** 방향(`properties/[id]/page.tsx`, 자기 API 문서 뷰어)과는 반대라 충돌 없음을 재확인했다 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | 최신 브라우저의 기본값과 같은 값이라 실질 동작 변화가 없고, 명시적으로 고정만 한다 |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | 이 앱이 쓰지 않는 기능만 끈다(`grep -rn "navigator\.\(geolocation\|mediaDevices\)" src/` 결과 0건) |

**`Content-Security-Policy`는 그대로 SKIP 유지한다** — 이건 Sprint 126의 판단이
맞았다. 이 앱이 실제로 불러오는 모든 출처(Supabase 프로젝트 URL, 폰트 등)를 전부
확정해야 정책을 짤 수 있고, 잘못 짜면 로그인(Supabase Auth)이나 API 호출 자체가
막혀 앱이 깨진다 — 승인 및 별도 세션의 브라우저 QA가 필요하다.

### 3. `api_server.py`(백엔드)에도 "동일 패턴"을 찾아 적용했다 — 그런데 그대로 복붙하면 깨졌다

"동일 패턴이 다른 곳에도 있는가"를 백엔드까지 넓혔다. `api_server.py`는 CORS만
설정하고 있어 프런트와 같은 사각지대다 — 그런데 **프런트에서 고른 네 헤더를 그대로
옮기면 안 되는 이유**가 있었다.

`properties/[id]/page.tsx`가 문서 뷰어를 이렇게 담는다:

```tsx
<iframe src={`${API_BASE_URL}/api/v1/item/${id}/documents/${viewingDoc}`} />
```

**이 백엔드 자체가 iframe의 대상(피담기는 쪽)이다.** 프런트(3000)와 백엔드(8000)는
포트가 달라 **다른 origin**이므로, `X-Frame-Options: DENY`는커녕 `SAMEORIGIN`조차
이 문서 뷰어를 깨뜨린다 — 프런트 쪽 판단(§2)과 정반대 결론이 나오는 자리다. 같은
"보안 헤더를 추가한다"는 동작이라도, **역할이 반대인 두 서버에 같은 값을 기계적으로
복붙하면 실제 기능을 깬다**는 것을 실측 없이 판단만으로 미리 걸러냈다(적용 전에
`X-Frame-Options`를 뺀 이유를 코드 주석에도 남겨, 다음 세션이 "빠뜨린 줄" 알고
무심코 채워 넣지 않게 했다).

그래서 백엔드에는 **프런트와 겹치는 것 중 framing과 무관한 둘만** 적용했다 —
`X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`.
`Permissions-Policy`는 JSON/파일 API 응답에는 사실상 의미가 없어(브라우저 기능 접근은
HTML 문서 렌더링 컨텍스트에서만 유효) 넣지 않았다 — 넣어도 해는 없지만 의미 없는
헤더를 매 응답에 추가할 이유가 없다.

## 검증

### 실제 응답 헤더 (dev 서버, `curl -D -`)

```
GET /            -> X-Content-Type-Options / X-Frame-Options / Referrer-Policy / Permissions-Policy 전부 실림, X-Powered-By 없음
GET /login       -> 동일
GET /search      -> 동일
GET /properties  -> 307 리다이렉트 응답에도 네 헤더가 실린다(location: /login?redirect=... 그대로 보존 확인 — 헤더 추가가 리다이렉트 로직에 개입하지 않음)
```

### 코드 영향 확인

```
grep -rn "X-Powered-By" .                              -> 0건 (읽는 코드 없음, 안전)
grep -rn "navigator.geolocation\|navigator.mediaDevices" src/  -> 0건 (끄는 기능 자체를 안 씀)
```

### 백엔드 응답도 실측했다 (`curl -D -`, uvicorn)

```
GET /api/v1/search (성공, JSON)             -> nosniff/Referrer-Policy 실림, X-Frame-Options 없음
GET /api/v1/item/1/documents/SPEC (404)     -> 동일
GET /api/v1/item/53/documents/SPEC (200, 실제 PDF 402KB) -> 동일 (FileResponse 경로도 미들웨어를 통과함을 확인)
```

### 회귀 테스트 신설 + 변이 검증 (`test_api_regression.py` §18-B)

성공/404/401/실제 파일 응답(FileResponse 경로) 4가지 모두에서 두 헤더가 실리는지,
그리고 **`X-Frame-Options`가 없는 것 자체**를 검사로 고정했다. 변이 2건으로 실제
검출을 확인했다.

| | 변이 | 결과 |
|---|---|---|
| M104 | 미들웨어에서 헤더 설정 두 줄을 제거 | **검출 O** ― 8개 체크 전부 FAIL(성공/404/401 × 2헤더) |
| M105 | 미들웨어에 `X-Frame-Options: SAMEORIGIN`을 추가(실수로 프런트 값을 복붙했다고 가정) | **검출 O** ― "X-Frame-Options가 없다" 체크 4건(성공/404/401/파일) 전부 FAIL, 실제로 걸리면 문서 뷰어가 깨졌을 조합 |

두 변이 모두 원복 후 `diff`로 원본과 바이트 단위 일치 확인, `compileall` 재통과.

### 프런트 쪽도 Test Gap이었다 — `tests/source-contract.test.mjs`에 소스 계약 신설

백엔드는 §18-B로 커버했는데, **프런트(`next.config.ts`)는 이 변경을 검사하는 테스트가
하나도 없었다**(`grep -l "next.config" tests/*.mjs` 결과 0건). `next.config.ts`는
TypeScript라 이 저장소의 Node 테스트 러너(트랜스파일러 없는 `.mjs`)가 직접
import할 수 없어, 이 파일의 기존 관례(`source-contract.test.mjs`)대로 텍스트를
읽어 정적으로 대조하는 신규 3개 검사를 추가했다.

- `poweredByHeader: false`가 있는가
- `headers()`가 4개 헤더/값을 전부 선언하는가
- `api_server.py`가 **실제로 헤더를 설정하는 코드**(`headers["X-Frame-Options"] =` 모양)로
  `X-Frame-Options`를 넣고 있지 않은가

세 번째 검사는 **작성 직후 자기 자신에게 걸렸다** — 순진하게 `X-Frame-Options`
문자열 존재만 검사했더니, 바로 이 검사의 이유를 설명하는 코드 주석 자체에 그
문자열이 들어 있어(§3) 오탐이 났다. "언급"과 "실제로 설정하는 코드"를 구분하는
정규식(`headers\[["']X-Frame-Options["']\]\s*=`)으로 고쳐 해소했다 — 의도치 않았지만
그 자체로 "테스트가 실제로 도는지"를 실측한 셈이라 정직하게 남긴다.

| | 변이 | 결과 |
|---|---|---|
| M106 | `next.config.ts`에서 `X-Frame-Options` 항목 제거 | **검출 O** ― "정책 결정 불필요한 4개를 전부 선언한다" 즉시 FAIL |
| M107 | `api_server.py` 미들웨어에 `X-Frame-Options: DENY` 실제 추가(문자열 언급이 아니라 진짜 설정 코드) | **검출 O** ― "X-Frame-Options를 넣지 않는다" 즉시 FAIL |

둘 다 원복 후 `diff` 일치 확인, `tsc --noEmit` 재통과.

### 회귀

| 항목 | 결과 |
|---|---|
| `npx tsc --noEmit` | exit 0 (변이 원복 후 재확인 포함) |
| `npx eslint .` | exit 0 |
| `npm run build`(Turbopack, 프로덕션) | 성공, 라우트 구성 무변경(10페이지 그대로) |
| `npm run test:frontend`(신설 3건 포함, 헤더 적용된 dev+backend 서버 대상) | **111/111 통과**(기존 108 + 신설 3) |
| `node --test tests/source-contract.test.mjs`(서버 없이 단독) | 23/23 통과 — 서버 없이도 신설 검사가 도는 것을 확인 |
| 파이썬 전체 스위트 | **28/28** (§18-B 신설 포함, 여러 차례 재확인) |
| 실제 로그인 페이지 브라우저 렌더링 | **끝내 미확인** — 이 세션의 Chrome 자동화 도구를 서로 다른 시점에 총 5회 시도했다(스크린샷 3회, `read_page` 1회, 매번 새 탭 그룹 + 새로 기동한 서버) — 전부 동일하게 "Frame with ID 0 is showing error page"로 실패했다. 탭 제목은 정상 로드를 시사하는 `"localhost"`였고(에러 페이지 제목이 아니다) 콘솔 로그도 0건이라, 페이지 자체보다 확장 프로그램의 렌더링/캡처 파이프라인 쪽 문제로 보인다. 대신 (1) `curl`로 실제 응답 HTML을 받아 로그인 폼(`<form ... method="POST">`, `name="email"`/`name="password"` 입력)이 정상적으로 마크업에 존재함을 확인, (2) 프런트 계약 테스트 111/111(실제 라우트 구조·리다이렉트·인증 게이트 검증), (3) 메커니즘 분석(이 헤더들은 응답 헤더일 뿐 서버사이드 폼 처리/Server Action 경로에 개입할 수단이 없다) 세 가지로 안전성을 확인했다. 실제 클릭·제출까지의 브라우저 검증은 도구가 복구된 다음 세션에서 재시도할 가치가 있다 — 이 세션에서는 더 이상 시도하지 않는다(반복 재시도는 실익이 없다고 판단) |

## 2026-08-16 추가 (Sprint 138 연장, E2E Beta Journey Audit 도중) ― 실제 응답 헤더 라이브 확인 완료

위 표의 "끝내 미확인" 항목이 남아 있었다. 이번엔 Chrome 확장 도구가 아니라
`npm run dev` + `python api_server.py`를 실제로 백그라운드 기동한 뒤 `curl -D -`로
직접 확인했다(브라우저 자동화 없이도 해결되는 문제였다 — 굳이 그 도구가 복구되길
기다릴 필요는 없었다).

```
$ curl -s -D - -o /dev/null http://localhost:3000/
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
(X-Powered-By 없음 — poweredByHeader:false 확인)

$ curl -s -D - -o /dev/null http://localhost:8000/api/v1/search?size=1
x-content-type-options: nosniff
referrer-policy: strict-origin-when-cross-origin
(x-frame-options 없음 — 의도된 제외, 설계대로)
```

프런트/백엔드 둘 다 설계한 그대로 응답에 실린다. 같은 기회에
`node --test tests/frontend-contract.test.mjs`(서버 필요)도 재실행해
**48/48 통과**(0 cancelled, 0 skipped) 확인했고, `test_beta_journey.py`도
dev 서버가 떠 있는 상태로 재실행해 이전에 SKIPPED였던 "프런트 로그인 게이트 +
복귀 URL 보존"(§4) 단계까지 포함해 **SKIPPED 0건**으로 전체 통과했다
(`docs/SPRINT138_TEST_GAP_AND_COURT_CRAWLER_RESTART.md` 참고). 이걸로 이
Sprint의 "다음 세션에서 재시도" 백로그 항목은 닫혔다.

## 수정 파일

```
next.config.ts                              poweredByHeader: false + headers() 4종 추가
api_server.py                               보안 헤더 미들웨어 신설(X-Frame-Options 의도적 제외, 이유는 주석에)
test_api_regression.py                      §18-B 신설(백엔드 보안 헤더 + 의도적 제외 검증)
tests/source-contract.test.mjs               '응답 보안 헤더' describe 신설(next.config.ts + api_server.py 대조, 3검사)
docs/SPRINT127_SECURITY_HEADERS_APPLIED.md   신규 (본 문서)
```

## SKIP (사용자/제품 결정 필요) ― 유지

| 항목 | 이유 |
|---|---|
| `Content-Security-Policy` | 허용 출처 목록 확정 + 브라우저 QA 필요 - 승인 영역(Sprint 126과 동일 판단 유지) |
| `Strict-Transport-Security`(HSTS) | HTTPS로 실제 서빙되는 배포 환경이 확정된 뒤에만 의미가 있다(로컬 dev는 HTTP) - 운영 배포 시점 결정 사항 |

## 남은 Backlog

- ~~다음 세션에서 Chrome 자동화 도구가 정상 동작하면 로그인 페이지 실제 렌더링 +
  로그인 Server Action 제출까지 브라우저로 재확인~~ → **2026-08-16 해소**: 위
  "실제 응답 헤더 라이브 확인 완료" 참고 — 브라우저 자동화가 아니라 실서버 기동
  + curl로 목적(실제 응답 확인)을 달성했다. 로그인 Server Action의 실제 클릭
  제출까지는 여전히 미확인이지만, 이는 헤더 검증과 무관한 별개 항목이라
  아래에 다시 남긴다
- 로그인 Server Action의 실제 클릭 제출(폼 상호작용)까지 브라우저로 확인 —
  계약 테스트(111/111)와 메커니즘 분석으로 안전성은 확인됐으나, 실제 클릭 UX는
  미확인 상태 유지(Chrome 자동화 도구 없이는 어려움)
- CSP: 이 앱이 실제로 부르는 전체 출처 목록(Supabase URL 등) 확정 후 승인 받아 진행
- Sprint 105~126의 SKIP 표 항목들 (전부 승인/외부 조치 대기, 미해소)
