# Test Plan

Status: Active
Last Updated: 2026-08-11 (Sprint 53)

이전 버전(16줄짜리 체크리스트)은 "이미지 ☑", "권리분석 ☑"처럼 **존재하지 않는 기능을 완료로
표시**하고 있었고 실제로 상시 실행 중인 회귀 테스트 2종도 전혀 언급하지 않았다.
2026-08-07 코드 기준으로 다시 작성한다.

---

## 1. 자동 회귀 테스트 (상시 실행 가능)

### 1-A. Frontend 계약 테스트 (2026-08-10 Sprint 45 신규, 2026-08-11 Sprint 49~50 확장)

```bash
python -m uvicorn api_server:app --host 127.0.0.1 --port 8000   # ① 백엔드 (필수)
npm run dev                  # ② 먼저 서버를 띄운다 (npm run start도 가능)
npm run test:frontend        # tests/**/*.test.mjs — 106 검사 (2026-08-13 Sprint 81 기준)
```

**Python 회귀 스위트는 API 서버를 내리고 돌린다** (2026-08-13 Sprint 82 확인).
`test_*.py`의 상당수가 실제 `auction.db`에 쓰고(롤백하더라도 쓰기 잠금은 잡는다),
`uvicorn`이 떠 있으면 같은 파일을 붙들고 있어 **무작위로 1~3개 파일이 실패한다.**
코드 문제가 아니라 SQLite 쓰기 잠금 경합이다.

```
API 서버 켠 채   28개 중 1~3개가 실행마다 다르게 실패
API 서버 내린 뒤 28/28 PASS (2회 연속 확인)
```

증상이 **매번 다른 파일에서 나기 때문에** 원인을 코드에서 찾게 되기 쉽다. 순서는
"프런트 계약 테스트(서버 필요) -> 서버 종료 -> Python 회귀"가 안전하다.

**API 서버를 재시작해도 응답이 안 바뀌면 고아 reloader 자식을 의심한다** (2026-08-17 Sprint 145 실측).
`python api_server.py`는 `uvicorn.run(..., reload=True)`라 `multiprocessing.spawn` 자식을 만든다.
부모만 죽이면 **자식이 살아남아 8000 포트를 계속 들고 옛 코드로 응답한다.** 이번 세션에서
그런 고아가 4개까지 쌓였고, 코드를 고쳐도 반영되지 않아 원인을 한참 헤맸다.

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen   # OwningProcess 가 <gone> 이면 고아
Get-Process python | ForEach-Object { taskkill /PID $_.Id /T /F }   # 트리째 종료
```

함정이 둘이다 — (a) 자식의 명령줄은 `multiprocessing.spawn`이라 `*api_server*`/`*uvicorn*`
필터에 **걸리지 않는다**, (b) `netstat`에는 LISTENING으로 보이는데 프로세스는 이미 없다.
검증용으로는 `python -m uvicorn api_server:app --port <다른포트>`(reload 없음)로 띄우면
이 문제를 통째로 피할 수 있다.

**프런트 변경은 반드시 실제로 렌더해 본다** (2026-08-17 Sprint 145).
`tsc` / `eslint` / `next build`가 **셋 다 통과하는데 화면이 죽는** 결함이 있다 —
서버 컴포넌트에 이벤트 핸들러를 넘기면(`<img onError={...}>`) 런타임에만 터진다
(`Event handlers cannot be passed to Client Component props`). 정적 게이트만 믿으면 놓친다.

**`npm run build` 직후 `npm run dev`를 띄우면 첫 화면이 500이 난다** (2026-08-13 Sprint 79 확인).
production 빌드 산출물과 dev 서버가 같은 `.next`를 공유해 충돌한다. 이것도 제품 결함이 아니다 —
`.next`를 지우고 dev를 다시 띄우면 정상이다. **프런트 계약 테스트를 돌리기 전에는 build를
하지 말거나, 했다면 `.next`를 지우고 dev를 띄운다.**

**`npm run build`가 `EPERM ... unlink '.next/static/...'`으로 실패하면** 제품 결함이 아니다
(2026-08-13 Sprint 79 확인). 이 저장소는 OneDrive 동기화 폴더 안에 있어서, 방금 쓴 빌드
산출물을 OneDrive가 잡고 있는 동안 다음 빌드가 그 파일을 지우지 못한다. dev 서버가 떠
있을 때도 같은 증상이 난다. `.next`를 지우고 다시 빌드하면 정상 통과한다.

    Remove-Item -Recurse -Force .next ; npm run build

**FastAPI 백엔드도 반드시 떠 있어야 한다** (2026-08-13 Sprint 72에 명시). 이 스위트는 Sprint 49
이후 "200이면 통과"가 아니라 **실제 결과 데이터**를 단언하기 때문에, 백엔드가 없으면 검색 결과가
0건이 되고 관련 검사들이 줄줄이 실패한다. 예전에는 그 상황이 `비로그인 결과 카드에 즐겨찾기
버튼이 없습니다`처럼 **원인과 무관한 문구**로 보고됐다. 지금은 `before()` 훅이 두 서버를 각각
확인하고 무엇이 빠졌는지(그리고 띄우는 명령을) 지목한다. 물건이 0건인 경우도 "기능이 깨진 것"과
구분해서 알려준다.

`docs/FRONTEND_MASTER_SPEC.md`가 "절대 변경 금지"로 못박은 계약을 고정한다: `/` 무redirect,
첫 화면이 로그인 폼이 아님, 비로그인 목록 노출, 검색 실행의 pathname 유지, `/search` 호환,
결과→상세 링크 형태, 비로그인 상세 307 게이트, **redirect의 query string 보존**,
로그인 폼의 redirect 복귀 구조, 공개 라우트 무차단, 정렬/페이지 파라미터 비로그인 처리,
개인화 라우트(`/properties/recent`·`/favorites`) 서버 게이트, **Empty State 안내·복구 동선**,
1320px 컨테이너, 반응형 열 구성, **접근성 기본**(h1 단일/main·nav 랜드마크/select 접근 이름/lang), **Open Redirect 방어**(GET 단계 외부 origin 이탈 없음).

**Sprint 49 확장 (29 → 50 검사)** — "200이면 통과"를 넘어 실제 결과 데이터까지 본다.
기존 29검사는 정렬/페이지 파라미터를 붙여도 200인지까지만 봤기 때문에, **정렬 버튼을 눌러도
결과 순서가 그대로**인 결함(`docs/BUGS.md` #29/#30)이 전부 통과한 채로 남아 있었다.

- 정렬: asc/desc의 **렌더된 물건 id 순서가 실제로 다른가**, 화살표 표시가 백엔드 기본 정렬
  (`sort_order` 기본 `desc`)과 일치하는가, 정렬 변경 시 `page=1`로 초기화하는가
- 페이지: 1페이지와 2페이지의 물건이 **겹치지 않는가**, size 변경이 실제 건수에 반영되는가
- 페이지 범위 초과(#31): "결과 없음"으로 오인시키지 않고, 복구 링크가 **검색조건을 유지**하는가
- 검색조건: 지역 조건이 **결과 카드의 실제 주소**에 반영되는가(200만 보고 통과시키지 않음)
- 비로그인 개인화 액션 노출 정책(§8.2), 로그인 성공 후 복귀·로그아웃 복귀 경로

**Sprint 50 확장 (50 → 53 검사) — 서버 인증 게이트의 위치와 규약**

Next.js 16이 `middleware` 파일 규약을 deprecate해 `src/middleware.ts` → `src/proxy.ts`로
이전했다(로직 무변경). 게이트가 **어디에 있고 무엇을 보장하는가**를 소스 레벨로 고정한다.

- `src/proxy.ts`가 존재하고 `src/middleware.ts`가 **동시에 존재하지 않는다**
  (둘 다 있으면 Next가 빌드를 실패시킨다 — 실수로 되살아나는 것을 테스트가 막는다)
- proxy 파일이 Next 규약(`proxy` 이름의 export 또는 default) + `config.matcher`를 지킨다
- 보호 경로 목록(`['/properties','/favorites']`)과
  **`pathname + search` 전체 보존**, `supabase.auth.getUser()` 서버 검증이 그대로다

변이 테스트로 검출력 확인: `pathname + search` → `pathname`으로 되돌리면 **2검사 실패**
(기존 HTTP 검사 + 신규 소스 검사). 두 규약 파일을 동시에 두거나 export 이름을 바꾸면
Next가 앱 전체를 500으로 만들어 스위트 전체가 실패한다.

**Sprint 51 확장 (53 → 59 검사)**

- **잘못된 검색 파라미터**(`?size=500`/`?size=abc`/`?page=0`/`?sort_by=DROP` 등 6종):
  원인을 특정해 안내하는가, 서버 장애 문구를 쓰지 않는가, 복구 링크가 basePath를 유지하는가
- **레거시 라우트 정리**: `/properties`가 자체 화면을 렌더하지 않는가,
  하위 경로(`[id]`/`recent`)가 여전히 게이트되고 redirect 경로를 잃지 않는가,
  도달 불가 중복 코드 `src/login/`이 되살아나지 않았는가

**Backend `test_api_regression.py` §2-B (Sprint 51 신규, 469 → 494 검사)** — 물건종류 어휘
별칭(`docs/BUGS.md` #33)과 토큰 개수 상한(#36). 고정 건수를 단언하지 않고 **관계**로만 단언한다
(별칭 건수 >= 원본 토큰 건수 / 다중 선택은 합집합 / 과확장 없음 / 상한 초과는 400).
변이 5종 검출 확인: 별칭 표 비우기(28실패), 별칭 1개 제거(4실패), 가산성 파괴(7실패),
과확장(2실패), 상한 무력화(스위트 중단).

> **작성 교훈**: 처음에는 기대값을 `PROPERTY_TYPE_ALIASES`에서 끌어와 루프를 돌렸는데,
> **표를 비우면 루프가 0회 실행돼 아무것도 단언하지 않고 전부 통과**했다(검증 대상을
> 기대값의 출처로 삼은 자기참조 결함). 기대 목록은 테스트가 직접 들고, 구현 표는
> "그 목록을 덮는가"로만 검사하도록 바꿨다.

**Sprint 52 확장 (59 → 64 검사, 프론트)** — 기술부채 정리분 고정.
카드에 채워질 수 없는 "조회수" 자리가 없는가 / `crawl_date` 정렬이 UI에 노출되고 **실제로
순서를 바꾸는가** / **타입에 선언된 정렬을 UI가 전부 덮는가**(한쪽만 늘어나는 재발 방지) /
비로그인 저장 시 입력하던 이름이 복귀 URL에 실리는가 / `preset_name`이 검색 결과를 바꾸지 않는가.

**Backend §29~§31 (Sprint 52 신규, 494 → 569 검사)**

- **§29 환불** — 권한 경계(무인증/ADMIN 거부, SUPER_ADMIN만 허용) / 전액·부분·반복 환불 /
  멱등(`already_refunded`) / 잔여 초과·0원·음수 거부 / 상태머신 관문(FAILED 결제 환불 불가) /
  `payment_logs` CANCEL 궤적 / `audit_logs` 전후 상태·금액 기록
- **§30 Webhook** — **보안이 첫 관심사다**: 시크릿 미설정 401(fail-closed), 서명 없음/오류 401,
  본문 변조 401, 위조 시도도 감사 기록, 위조가 결제 상태를 못 바꿈. 그 다음이 정상 동작 —
  적용/멱등(재전송 시 행·로그 중복 없음)/상태머신이 막는 전이 무시/모르는 거래 무시/깨진 payload 400
- **§31 사용자 구독 조회** — 인증 필수, **소유권 격리**(B가 A의 구독을 볼 수 없음),
  파생 필드(`effective_status`/`is_entitled`/`grace_period_end`), lazy sync가 DB 상태까지 맞추는지

변이 5종 전부 검출: 서명 검증 무력화(5실패) / 상태머신 관문 제거(1) / 멱등성 제거(1) /
권한 SUPER_ADMIN→ADMIN 완화(1) / 환불 상한 제거(1).

> **작성 교훈 2**: `no test audit rows left` 검사가 **부모 행을 이미 지운 뒤에** "지금 존재하는
> qa 결제의 감사 행이 있는가"를 물어 **항상 0(공허하게 참)** 이었다. 삭제 전에 캡처한 id로
> 확인하도록 바꾸고 "dangling 감사 행 0건"을 추가했다. Sprint 51의 자기참조 결함과 같은 부류다.

**`tests/source-contract.test.mjs` (Sprint 53 신규 — frontend-contract.test.mjs에서 분리, 10 검사)**

**서버가 필요 없다.** `frontend-contract.test.mjs`의 `before()`가 dev 서버를 확인하는데,
Node 러너는 `before()` 실패 시 **그 파일의 모든 테스트를 취소**한다 — 서버가 잠깐 죽으면
서버와 무관한 소스 검사까지 사라졌다(실측: 46건 전부 cancelled). 소스만 읽는 검사 10건을
분리해, 서버가 꺼져 있어도 정상적으로 통과/실패를 보고한다.

**Backend §32~§33 (Sprint 53 신규, 569 → 616 검사)**

- **§32 Webhook 운영** — 권한 경계(ADMIN 조회 / SUPER_ADMIN 재처리) / "노티가 결제보다 먼저
  도착" 시나리오의 실제 재처리 성공 / 중복 재처리 자동 차단 / **서명 미검증은 상태와 무관하게
  재처리 불가**(가드 격리 검증) / 목록 필터 / 감사 로그
- **§33 인증 경계 전수** — OpenAPI에서 **모든 엔드포인트를 열거**해 익명 접근을 검사한다.
  분류되지 않은 신규 엔드포인트가 나타나면 실패하므로, 추가 시 공개/사용자/관리자 중 무엇인지
  **반드시 의식적으로 선언**하게 된다. 인증이 body 검증보다 먼저인지, 사용자 간 결제 격리(404)도 확인

변이 8종 전부 검출(서명 가드 / PROCESSED 재처리 / 권한 완화 / 상태머신 우회 /
oracle 재도입 / 인증 의존성 제거 2종 / 저장소 증폭).

> **작성 교훈 3**: 변이 테스트가 `FAIL 0건 + 크래시`로 나왔다 — 실패 출력에 **제품 코드의
> em-dash**가 실려 cp949 콘솔에서 죽은 것이다(`docs/BUGS.md` #43). 회귀가 "FAIL"이 아니라
> "중단"으로 보이면 성격을 오판하기 쉽다. 출력 함수 한 곳에서 인코딩을 방어하도록 고쳤다.

**`tests/nav-context.test.mjs` (Sprint 49 신규, 8 검사)** — 상세의 "이전/다음 물건" 컨텍스트
(`docs/BUGS.md` #32). 상세 화면은 로그인 필수 + 클라이언트 렌더라 HTTP 블랙박스로 관찰할 수
없어, 계산을 순수 함수(`src/app/properties/[id]/navContext.ts`)로 분리해 직접 호출한다.
Node 24의 내장 TypeScript type stripping을 쓰므로 새 의존성·빌드 단계가 없다.
변이 테스트로 검출력 확인(빈 세그먼트 필터 제거 → 2검사 실패, `i` 부재를 0으로 폴백 → 1검사 실패).

- **러너는 Node 내장 `node:test`** — 새 라이브러리를 설치하지 않았다(`docs/CLAUDE.md` 규칙).
  기존 Python 스크립트 방식과 중복되는 러너를 만들지 않기 위해 `npm run test:frontend` 하나만 추가.
- **HTTP 블랙박스**로만 검증해 번들러/트랜스파일 설정이 필요 없다.
- **DB 건수에 의존하지 않는다** — `test_search.py`가 기대 건수 노후화로 실패하는 함정을
  반복하지 않도록 구조(상태코드/링크 형태/파라미터 보존)만 단언한다.
- **자격증명을 다루지 않는다** — 비밀번호 제출과 실제 세션 파기는 범위 밖. 그래서
  `sanitizeRedirectPath()`의 Open Redirect 방어는 이 계층에서 검증되지 않는다(의도적 공백).
- 회귀 검출력 확인: `middleware.ts`를 `pathname`만 넘기도록 되돌리는 mutation 테스트로
  "redirect 파라미터가 query string 전체를 보존한다" 검사가 실제로 실패하는 것을 확인했다.

### 1-B. Backend / Crawler 회귀 테스트

별도 러너(pytest 등) 설정은 없다. 아래 스크립트를 직접 실행한다.

```bash
python test_api_regression.py       # 전 도메인 실제 HTTP 회귀 (616 검사, 2026-08-11 Sprint 53 §32 Webhook 운영 + §33 인증 경계 전수 추가, 2026-08-11 Sprint 52 §29 환불 + §30 Webhook + §31 사용자 구독 조회 추가, 2026-08-11 Sprint 51 §2-B 물건종류 어휘 별칭(#33)+토큰 상한(#36) 추가, 2026-08-09 HEAD 프로브 + Admin 결제로그 조회 + 등기부/문서 실다운로드·경로탐색 + 등기부 중복신청 방지 + 구독 중복결제 방지 + 결제 실패 후 재시도 + 2026-08-10 Sprint 43 sort_by 화이트리스트 8개 전수(정렬 결과 body까지) 검증 추가, `docs/BUGS.md` #24)
python test_subscription_policy.py  # 구독 정책/할인/월 리셋/식별키 무결성/credit 원장 (48 항목)
python test_state_machines.py       # Payment/Subscription 상태 전이·유예기간 순수 로직 (2026-08-08 신규, 82 검사)
python test_registry_credits.py     # 등기부 credit 원장 순수 로직 (2026-08-08 신규, 20 검사)
python test_auction_identity.py     # auction 식별키 무결성 + upsert_batch 법원 교차 안전성 (2026-08-08 신규, 26 검사)
python test_schema_hygiene.py       # get_connection(enforce_foreign_keys=) + soft delete 컬럼 + migration_history 완전성 (2026-08-08 신규, 8 검사)
python test_race_conditions.py      # 등기부 무료한도 + 초과결제 + 구독 + Admin 상태전이 동시 요청 방어 (2026-08-09 신규, 실스레드 22 검사, 구독 시나리오는 Sprint 38, Admin 상태전이 시나리오는 Sprint 39에서 각각 결함 수정 후 추가)
python test_intent_analyzer.py      # intent.analyzer 순수 함수 (기존, DB/API 무의존, 16 검사)
python test_normalizer.py           # normalizer.normalize_address 순수 함수 (기존, DB/API 무의존, 29 검사, 2026-08-09 cp949 크래시 수정)
python test_auth_jwt.py             # JWT 인증 체인 — ES256(JWKS, kid 선택/캐시/키회전) + HS256 레거시 + 알고리즘 화이트리스트(alg:none·알고리즘 혼동 거부) + 엔드포인트 레벨 인증필수/선택적인증 (2026-08-10 Sprint 46 신규, 23 검사, `docs/BUGS.md` #27). 자체 EC 키쌍을 JWKS 캐시에 주입해 네트워크 무의존
python test_search.py               # /api/v1/search 주소 Intent 회귀 (2026-08-10 Sprint 47 재설계, 25 검사) — 고정 row count 단언을 전부 제거하고 행 단위 검증 + 컬럼 매핑 동치 + 표기/분해 동치 + 포함 관계로 대체. 데이터가 늘어도 유효하며 mutation 테스트로 검출력 확인
python test_doc_storage_atomicity.py # crawler/doc_paths.py(Sprint 47 분리) 문서 저장 + storage/database.py 큐 완료 처리 순수 로직(Selenium 무의존) — get_doc_dir/doc_exists/원자적 쓰기(os.replace)/mark_queue_done() 부분실패 rollback (2026-08-09 Sprint 40 신규 12검사, 2026-08-10 Sprint 41 mark_queue_done rollback 검증 3검사 추가 → 15 검사, `docs/BUGS.md` #22)
python test_checkpoint_atomicity.py # storage/checkpoint.py(크롤러 재시작 이어받기) 순수 로직(Selenium 무의존) — 여러 법원 공유 파일 격리, 원자적 쓰기(os.replace), 손상 파일에도 크래시하지 않는 폴백 (2026-08-10 Sprint 42 신규, 15 검사, `docs/BUGS.md` #23)
python test_validation_log_integrity.py # validator/validation_engine.py의 logs/validation.jsonl append 순수 로직(Selenium 무의존) — 로그-결과 일치, 마지막 줄 손상이 이전 줄에 영향 없음 (2026-08-10 Sprint 42 신규, 9 검사)
python test_crawl_resume.py         # crawler/resume.py:resume_start_idx()(Sprint 47 분리) 체크포인트 재개 순수 로직(Selenium 무의존) — 정상 매칭/묶인 사건번호/체크포인트가 오늘 목록에 없을 때의 안전한 0-폴백 (2026-08-10 Sprint 43 신규, 10 검사, crawl_court() 인라인 로직을 순수 함수로 추출)
```

**2026-08-16(Sprint 140, Documentation Drift Audit) 추가** — 이 문서는 Sprint 53
(2026-08-11) 이후 개별 파일 목록을 갱신하지 않았다. 그 뒤 신설된 것 중 위
목록에 없는 것만 간단히 보충한다(상세 설명은 각 신설 Sprint 문서 참고,
전면 재작성은 하지 않는다 — 이 문서 범위를 넘는 별도 작업):

```
python test_bootstrap.py            # 부트스트랩 3단계(init_db/migrate_v4_1/run_migrations) 정합성 + fresh clone 스키마 대조(Sprint 99, §3-B는 Sprint 122 컬럼/인덱스 드리프트 allowlist)
python test_pipeline_integrity.py   # document_queue 상태머신 불변식 + 정규화 드리프트 상한 + 크롤 파이프라인 정합성 전수
python test_console_encoding.py     # cp949 콘솔 출력 리터럴 전수 스캔(EM DASH 등) — Sprint 72 신설, Sprint 133이 "출력 래퍼 함수" 탐지로 확장
python test_crawl_exit_code.py      # 크롤러/repair 스크립트들의 종료 코드 계약(빈 입력=0, 실패=1, 거짓 성공 금지)
python test_crawler_parsing.py      # 크롤러 파싱 로직 순수 함수(Selenium 무의존)
python test_rights_data_load.py     # 권리분석 데이터 적재 로직
python test_false_success.py        # 0바이트/orphan 문서가 "성공"으로 보이지 않는지 전수(Sprint 98 계열과 연결)
python test_doc_worker_recovery.py  # doc_worker.py 드라이버 크래시/재시작 복구(Sprint 137 신설) — 재시작 자체가 실패하면 남은 큐를 갉아먹지 않고 이번 실행을 중단하는지 검증
python test_asset_pipeline.py       # 물건 사진 + 문서 실체(doc_raw) 전 계층(Sprint 144 신설, Sprint 145에 24그룹) — alt 파싱/매직 판정/경로/수집/DB 기록/API 계약/경로탈출/프런트 계약. selenium 없이 가짜 드라이버로 실행
```

**2026-08-10(Sprint 45) 주의 — `test_search.py`의 3건 실패는 회귀가 아니다**:
`address_detail='서울'`/`'서울시'`/`'서울특별시'` 3개 검사가 `total=269`인데 기대값이 `284`로
하드코딩돼 있어 실패한다. 크롤러가 매일 데이터를 갱신하므로 **기대 건수가 노후화된 것**이며
(2026-08-09에도 같은 이유로 한 번 재동기화한 이력이 있다), 검색 로직 변경 때문이 아니다.
같은 파일의 응답 스키마 불변 검사와 `sido` 정규화 회귀 검사는 PASS 상태다.
근본 해결은 "절대 건수" 대신 관계(예: 시도 합계 = 하위 시군구 합계)로 단언하도록 바꾸는 것이며,
테스트 검증력을 낮추지 않는 재설계가 필요해 별도 작업으로 남긴다. Sprint 45에서 신설한
Frontend 계약 테스트(§1-A)는 이 함정을 피하려 처음부터 건수를 단언하지 않는다.

**2026-08-09 갱신**: 저장소 루트의 `test_*.py` 전체를 재탐색해 이번 세션 이전에는 실행되지
않았던 3개(`test_intent_analyzer.py`/`test_normalizer.py`/`test_search.py`)를 발견·실행했다.
`test_normalizer.py`는 cp949 콘솔에서 인코딩 불가능한 em-dash(—) 문자 때문에 마지막 출력에서
크래시하던 것을 ASCII로 정리해 해결(검사 자체는 이미 19/19 통과 중이었음, 출력 버그만 수정).
`test_search.py`는 11개 검사가 실패했는데, 원인은 검색 로직이 아니라 이 테스트가 하드코딩한
기대값이 D7 기본 필터(`auction_date >= 오늘`) 도입 이전 스냅숏이었기 때문 —
`include_closed`/필터 유무로 대조해 검증한 뒤 `include_closed=True`를 헬퍼에 추가하고
드리프트가 확인된 두 지역(서울/빛가람동)의 기대값만 오늘 실측치로 갱신했다(나머지는 원래
값과 정확히 일치함을 확인). 신규 `test_race_conditions.py`는 등기부 무료한도(10스레드)와
초과결제 중복방지(8스레드)를 실제 스레드로 검증한다 — 두 방어 모두 과거 문서에 "N스레드
동시 요청으로 실측 검증"이라고 기록돼 있었지만 자동화된 회귀로는 한 번도 남지 않았던 공백이다.
`test_filter.py`(dead code `filter/filter_engine.py` 대상)와 `test_db.py`/`test_docs.py`/
`test_docs2.py`(실제 courtauction.go.kr 크롤링)는 PASS/FAIL 어서션이 없거나 외부 네트워크를
쓰므로 회귀 스위트에 포함하지 않는다(전자는 수동 확인용 데모, 후자는 기존 원칙대로 자동 실행 제외).

**2026-08-08(Sprint 32) 갱신**: 승인 하에 `python-jose`를 설치해 `test_api_regression.py`/
`test_subscription_policy.py`가 **이 세션에서 처음으로 실제 HTTP 레벨로 실행**됐다 —
연속 2회 실행 전부 통과(재현성 확인), 잔여 QA 데이터 0건. `.env`에는 여전히
`SUPABASE_JWT_SECRET`이라는 이름이 없어(`JWT_SECRET`만 존재, `docs/BETA_RELEASE_CHECKLIST.md`
P0-4), `test_api_regression.py`는 `ADMIN_API_KEY`와 같은 기존 패턴으로 **이 프로세스에서만
유효한 합성 값**을 주입하도록 수정됐다(`.env` 무수정, 실제 운영 비밀값과 무관) — 이는
인가·서명 검증 **로직**을 검증하는 것이지 실제 운영 `.env`가 고쳐졌다는 뜻은 아니다.
`test_state_machines.py`/`test_registry_credits.py`/`test_auction_identity.py`/
`test_schema_hygiene.py`(jose 불필요, Sprint 29~31 신설)는 계속 유효하며, jose 확보 여부와
무관하게 더 빠르게 순수 로직만 검증하고 싶을 때 계속 쓸 수 있다.

두 HTTP 회귀 스크립트 모두 **실제 `auction.db`를 사용하되 실사용자 데이터는 건드리지 않는다.**

- `test_api_regression.py`: FastAPI `TestClient`로 `api_server.app`을 직접 호출한다(라우팅/
  의존성/인증/직렬화까지 실제 요청과 같은 경로). 테스트 데이터는 `qa-reg-<uuid>` 전용
  user_id로만 만들고 종료 시 그 행만 삭제한다. `ADMIN_API_KEY`는 프로세스 환경에만 주입한다
  (`.env` 무수정).
- `test_subscription_policy.py`: 정책 계산 함수를 직접 검증하고, DB를 건드리는 검사는
  트랜잭션 롤백 안에서 수행한다.

### `test_api_regression.py` 커버 범위

| # | 섹션 | 주요 검사 |
|---|---|---|
| 1 | Health / Stats | 루트·`/stats`·`/document-stats` 응답 형태 |
| 2 | Search | 비로그인 접근, 필터, **정렬 화이트리스트(미허용 값 400)**, 페이지네이션 경계, 인젝션 문자열 무해 처리 |
| 3 | Detail / Documents | 상세 필드, 문서 서빙, **`case.court_code`와 물건 `court_name` 일치**(복합키 Migration 회귀 방어), **HEAD 프로브**(GET과 상태코드 일치), **실제 문서 성공 다운로드**(파일이 있으면 내용 검증, 없으면 임시로 만들어 왕복 후 정확히 그 파일만 삭제 — 2026-08-09 신규, 이전까지 "200 또는 404 둘 다 통과"로만 검증해 실제 성공 시 내용이 맞는지 확인한 적이 없었음) |
| 4 | Authentication | 무토큰 401 / 위조 토큰 401 / `sub` 없는 토큰 401 / 정상 토큰 200 |
| 5 | Favorite | 등록·중복 거부·목록·삭제, 검색 결과의 `is_favorited` 반영, 소유권 격리 |
| 6 | Recent items | 상세 조회 시 자동 기록, 재조회 시 중복 행 없음 |
| 7 | Search presets | 저장·목록·조건 round-trip·삭제, 소유권 격리, **서버측 입력 검증**(공백/길이/크기/개수 상한, 이름 trim) |
| 8 | Payment / Subscription | 금액 위조 거부, 폐기 플랜명 거부, 잘못된 결제주기 거부, 월/연 기간, 할인가 적용, 소유권 격리, **구독 중복결제 방지**(순차 재요청 — 이미 유효한 구독이 있으면 다른 플랜을 보내도 새 subscriptions/payments 행 생성 없이 기존 구독 반환, `already_subscribed` 플래그 — 2026-08-09 Sprint 38, `docs/BUGS.md` #20), **결제 실패 후 재시도**(provider를 일시 교체해 FAILED 강제 — 실패 시 subscription 미생성, 이어지는 재시도는 정상 생성 — 2026-08-09 Sprint 38 추가) |
| 9 | Registry | 구독 게이트, 무료 한도, 소유권 격리, 미완료 다운로드가 파일이 아님, **실제 성공 다운로드**(200, 파일 바이트 일치, Content-Disposition), **경로 탐색 방어**, **중복 신청 방지**(같은 물건 재신청 시 동일 id 반환·무료횟수 불변·행 수 불변, FAILED 이후 재시도는 허용 — 2026-08-09 Sprint 37 신규, `docs/BUGS.md` #19) |
| 10 | Registry overage | 한도 초과 → `PAYMENT_REQUIRED` → 결제 → `payment_id` 연결, **결제 실패 후 재시도**(provider 일시 교체로 FAILED 강제 — 실패 시 대상 신청이 미연결 상태로 남아 재시도 가능함을 확인 — 2026-08-09 Sprint 38 추가) |
| 11 | Admin | 키 없음/오답 403, 필터, **상태 전이 규칙 전수**, `completed_at`, 없는 파일에 거짓 성공 없음, **동시 상태전이 레이스 방지**(`test_race_conditions.py` — 같은 신청에 다른 목표 상태로 동시 PATCH 시 정확히 1건만 성공, 진 쪽 필드가 섞이지 않음 — 2026-08-09 Sprint 39, `docs/BUGS.md` #21) |
| 12 | Payment Provider | `kginicis` 선택, **6개 메서드가 전부 `NotImplementedError`**(실연동 전 결제가 성공한 것처럼 보이는 사고 방지), 폐기 후보 2종, 알 수 없는 값, 미설정 기본값 |
| 13 | 정렬 결정성 | 동일 타임스탬프 행에서도 목록 순서가 호출마다 동일하고 `id` 내림차순 전순서인지 |
| 14 | 구독 플랜 tie-break | 같은 `started_at`의 BASIC→PRO 업그레이드에서 한도 10이 나오는지 (`docs/BUGS.md` #16) |
| 15 | 가격 미러 정합성 | 프론트 `PLAN_OPTIONS`와 서버 `PLAN_CATALOG`의 한도·정상가·청구액이 일치하는지 |
| 16 | API 표면 고정 | 엔드포인트 23개 집합이 그대로인지(사라짐/추가 둘 다 검출), **OpenAPI 생성 시 경고 0건**, HEAD 프로브가 GET과 같은 상태코드를 주는지 |
| 17 | 응답 envelope | 인증 라우트 5종이 `{success, data, message}` 계약을 유지하는지 / 공개 라우트(search)는 flat 형태 유지 |
| 15 | Plan API | `GET /api/v1/plans`가 `PLAN_CATALOG`와 일치하는지, 응답 금액 그대로 결제가 통과하는지, **프론트에 가격 하드코딩이 되살아나지 않았는지** |
| 18 | CORS 설정 | 미설정 시 `*`, `CORS_ALLOW_ORIGINS` 지정 시 그 목록만 파싱되는지 |
| 19 | Admin 권한 2단계 | 키별 등급 판정, ADMIN은 조정 불가(403)·SUPER_ADMIN은 가능, 기존 ADMIN 운영 하위호환 |
| 20 | registry_credit | GRANT/DEDUCT/RESET 원장 계산, RESET 이후만 유효, 입력 검증, 한도 0 하한, 이력·수행자 기록 |
| 21 | 결제 로그/Webhook | 3단계 기록·순서·연결, 소유권 격리, 민감정보 마스킹, `event_id` 멱등성, **Admin 전용 조회**(`GET /admin/payments/{id}/logs`, 2026-08-09 신규 — 이전까지 테스트 0건이던 라우트) |
| 22 | 크롤러 식별키 | `auction`/`auction_item` 제약 고정, 두 법원 공존(롤백 검증) |
| 23 | FK 런타임 강제 | 기본 커넥션 `ON`, 고아 INSERT 차단, 마이그레이션 커넥션은 `OFF` |
| 24 | Payment 상태머신 | 허용/금지 전이, 레거시 `SUCCESS` 환불 가능, 종결 상태, 알 수 없는 상태 거부 |
| 25 | Subscription Lifecycle | 전이 규칙, 자동 만료(정상/유예/만료), **이용권 게이트 6종**(active/grace/expired/paused/cancelled/none), 유예 중 플랜 한도 유지, 갱신, 해지 불가역 |
| 26 | audit / credit 로그 | 감사 로그 기록·필터·before/after, credit 변동 로그·balance_after·actor, **사용(USAGE) 로깅 + 한도 이중차감 없음** |
| 27 | Admin REST 구조 | 기존 경로 유지 + 새 경로 동일 결과, meta.total, 권한 게이트, 구독 전이 400/404 |
| 28 | Soft Delete 컬럼 | `deleted_at`/`deleted_by` 존재, 기존 DELETE 동작 무변경 |

---

## 1-1. 테스트 Audit — "통과"가 아니라 "잡아내는가"

테스트가 전부 통과했다는 사실만으로는 그 테스트가 무언가를 지키고 있다는 증거가 되지 않는다.
일부러 코드를 망가뜨렸을 때 실패해야 비로소 의미가 있다.

2026-08-07 변이(mutation) 검증: 8가지 결함을 주입 → **8/8 전부 검출**.
그 과정에서 실제 테스트 공백 1건을 발견해 보강했다(이용권 게이트가 DB에 `GRACE_PERIOD`로
저장된 행을 한 번도 쓰지 않아, 조회 조건에서 그 상태를 빼먹어도 통과했다).

새 회귀 테스트를 추가할 때는 **그 테스트가 실패하는 것을 한 번 확인**하고 커밋한다
(해당 코드를 잠깐 망가뜨려 보는 것으로 충분하다).

---

## 2. 품질 게이트 (변경 시 매번)

```bash
npx tsc --noEmit    # Type Check — 통과해야 함
npx eslint .        # Lint — 2026-08-07 기준 0 오류
npm run build       # Next.js 빌드 — 통과해야 함
```

---

## 3. 수동 확인이 필요한 영역 (자동화 미적용)

자동 테스트로 덮이지 않는 부분. 회귀 위험이 있는 변경에서만 수행한다
(`docs/APPROVAL_POLICY.md`: 코드 분석 → 로그 → 서버 → API → **마지막에** 브라우저 QA).

- 회원가입 / 로그인 / 로그아웃 — Supabase Auth 실계정이 필요해 자동화하지 않는다.
  로그아웃 버튼은 현재 `/properties` 화면에만 있다(`docs/BUGS.md` #15)
- 등기부 다운로드 — 실제 파일을 `registry_documents/`에 두고 Admin으로 `doc_url`을 연결한 뒤
  브라우저에서 저장되는지 확인(백엔드 응답까지는 9~11번이 검증)
- 크롤링 파이프라인(`mvp_scraper.py` → `migrate_execute.py`) — courtauction.go.kr에 실제
  요청을 보내므로 회귀 테스트에서 실행하지 않는다

### 실행할 수 없는 테스트 (환경 제약)

- `selenium`/`webdriver-manager`/`pandas`/`python-jose` **전부 이 환경에 설치되어 있다**
  (2026-08-08 재확인). 이전 버전 문서의 "selenium 미설치"/"python-jose 미설치"는 둘 다 stale —
  jose는 2026-08-08(Sprint 32) 승인 하에 설치 완료됐고, `test_api_regression.py`/
  `test_subscription_policy.py`가 이제 실제로 실행된다(위 1절 참고).
- 그럼에도 `test_db.py` 등 크롤러 계열 스크립트는 여전히 회귀에서 **자동 실행하지 않는다** —
  import 실패가 아니라 **실제로 courtauction.go.kr에 크롤링 요청을 보내는 스크립트**이기
  때문이다(위 "수동 확인이 필요한 영역"과 동일한 이유). 코드/의존성 문제는 이제 없다.

---

## 4. 테스트하지 않는 것 (기능 자체가 없음)

이전 버전 문서가 "완료"로 표시했던 항목의 실제 상태다.

- ~~**이미지**: 물건 사진/이미지 기능이 코드에 존재하지 않는다~~ →
  **2026-08-17 Sprint 144에 구현됨.** 이 서술은 그때까지 정확했다(수집·저장·API·화면
  어디에도 없었다). 지금은 `crawler/image_assets.py`(순수 규칙) +
  `crawler/image_crawler.py`(수집) + `auction_image` 테이블(migration 020) +
  `api/v1/images.py`(서빙) + 상세페이지 갤러리까지 연결돼 있고,
  **`test_asset_pipeline.py`(20개 그룹)가 회귀를 막는다.**
  실 법원 E2E 검증: 9물건 45장 수집 성공(2026-08-17). 자세한 내용은
  `docs/SPRINT144_ASSET_PIPELINE.md` 참고.
  아직 없는 것은 **서버 측 썸네일 생성**뿐이다(Pillow 선언이 승인 사항 — 같은 문서 §9).
- **권리분석**: `src/app/properties/[id]/rightsAnalysis.ts`는 REGISTRY 소스를
  `available:false`로 하드코딩한 스텁이다. 등기부 파싱 테이블/파이프라인 자체가 없다
  (`docs/roadmap.md` "In Progress > Frontend" 참고)
- **Admin 화면**: Admin은 API만 있고 UI가 없다

---

## 6. 알려진 테스트 환경 이슈 (2026-08-10 Sprint 46)

- ~~`test_doc_storage_atomicity.py`는 selenium 없이 실행되지 않는다~~ →
  **2026-08-10 Sprint 47 해결**. 같은 문제가 `test_crawl_resume.py`에도 있었다
  (`court_crawler` -> `base_crawler` -> selenium).
  순수 함수를 selenium을 import하지 않는 모듈로 분리해 해결했다(위 (a) 방향):
  `crawler/doc_paths.py`(경로 규칙), `crawler/resume.py`(재개 위치 계산).
  원본 모듈이 이름을 재노출하므로 `doc_worker.py` 등 기존 호출부는 무변경이고,
  테스트가 검증하는 함수는 **동일한 그 함수**라 검증력이 약해지지 않았다.
  selenium 설치는 여전히 하지 않았다(승인 사항).

- **`storage/`가 통째로 gitignore라 그 안의 수정은 조용히 사라질 수 있다.**
  2026-08-10 Sprint 47에 `storage/checkpoint.py`의 원자적 쓰기(BUGS #23 수정분)가
  코드에서 사라진 것을 `test_checkpoint_atomicity.py`가 잡아냈다(BUGS #28).
  git 이력이 없으므로 **이 디렉터리의 회귀 테스트가 유일한 안전장치**다.

---

## Sprint 54 추가 (2026-08-11)

### tests/rights-analysis.test.mjs (신규, 15검사)

`src/app/properties/[id]/rightsAnalysis.ts`는 순수 로직인데도 **테스트가 0건**이었다.
그 사이 신뢰도 등급이 뒤집혀 있었고(BUGS #44) HTTP 블랙박스로는 관찰되지 않았다
(`/properties/[id]`는 로그인 필수 + 클라이언트 렌더).

`nav-context.test.mjs`와 같은 방식 — 순수 함수를 직접 호출한다
(Node 24 내장 TypeScript type stripping, 새 의존성 없음).

고정한 계약:

| 상황 | 기대 등급 | 근거 |
|---|---|---|
| 현황조사서만 | MEDIUM | 대조 상대가 없다 |
| 명세서만 | MEDIUM | 대조 상대가 없다 |
| 정보원 없음 | MEDIUM | 확인된 것이 없다 |
| 둘 다 있고 인원수 일치 | HIGH | 교차 검증됨 |
| 둘 다 있고 인원수 다름 | MEDIUM | AGGREGATION_DIFFERENCE |
| 현황 0명 vs 명세서 N명 | LOW | DIRECT_CONFLICT |
| 둘 다 있으나 비교값 NULL | HIGH 금지 | 비교한 적이 없다 |

핵심 계약 한 줄: **"신뢰도 HIGH와 정보원 누락 경고는 동시에 나올 수 없다."**
화면에 실제로 함께 떠 있던 모순이라 이것 자체를 테스트로 못 박았다.

변이 감사 5종 전부 검출(5/5):
대조불가→HIGH 복귀 / `canCrossCheck` 항상 true / NULL 비교값 무시 /
SPEC 필터 제거 / DIRECT_CONFLICT 등급 하향.

### test_schema_hygiene.py §4 — requirements.txt ↔ 소스 import 일치 (신규 4검사)

의존성 목록을 사람이 관리하면 다음 import가 추가되는 순간 어긋난다. 그래서 **매번 소스에서
재도출해 비교**한다.

- 저장소의 모든 `.py`를 AST 파싱해 third-party 최상위 import를 수집
  (표준 라이브러리·로컬 모듈 제외, import 이름 → pip 배포판 이름 매핑 포함)
- **파싱 실패 파일이 하나라도 있으면 실패** — 파싱 안 된 파일의 import는 조용히 빠져
  검사에 구멍이 생기기 때문
- 양방향 검사: 목록에 빠진 것 / 목록에만 있고 아무도 안 쓰는 것

변이 감사 4종 전부 검출(4/4):
selenium 제거 / pdfplumber 제거 / 미사용 항목 추가 / `python-jose`를 `jose`로 오표기.

### 실행 불가 테스트 (3건) — 회귀 실패 아님

`test_db.py` / `test_docs.py` / `test_docs2.py`는 `selenium`을 직접 import한다.
현재 인터프리터에 selenium이 없어 `ModuleNotFoundError`로 즉시 종료된다(BUGS #46).
`pip install -r requirements.txt` 후 재실행해야 한다. **테스트가 깨진 것이 아니라
환경이 빠진 것**이므로 회귀 실패로 집계하지 않는다.

---

## Sprint 55 추가 (2026-08-11)

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_crawl_exit_code.py` | 44 | 크롤/워커 성패 판정, 진입점 종료코드 전달, 배치 errorlevel·마커, 실접속 스크립트 가드 |
| `test_document_queue.py` | 16 | 큐 UNIQUE 4축 독립성, 다물건 사건 적재, 018 마이그레이션 무손실 |
| `test_document_status_sync.py` | 25 | 수집 결과가 화면 테이블까지 도달, 최종 실패만 FAILED, 경로 탈출 차단 |

세 파일 모두 **selenium 없이** 실행된다. 판정 로직을 `models/crawl_outcome.py`로 분리하고,
DB가 필요한 검사는 임시 DB(`tempfile.mkdtemp`)에 최소 스키마를 만들어 실제 함수를 호출한다.

### 테스트를 약하게 만들지 않기 위해 지킨 것

- **스키마를 테스트에 베껴 쓰지 않는다.** `test_document_queue.py`는 018 마이그레이션
  파일에서 `CREATE TABLE`을 읽어 쓴다. 손으로 베낀 스키마는 진짜 스키마가 바뀌어도
  계속 통과하고, 그것이 바로 BUGS #48이 오래 살아남은 방식이다(주석은 `item_no`가
  있다고 했고 테이블에는 없었다).
- **사유 문자열까지 고정한다.** "수집 0건"과 "저장 0건"은 손봐야 할 곳이 다르다
  (크롤러 vs 저장 계층). 둘 다 "0건"으로 뭉개면 로그를 봐도 어디를 볼지 알 수 없다.
  변이 M1이 이 느슨함을 뚫고 살아남아 단언을 강화했다.
- **배치는 블록 단위로 검사한다.** "파일 어딘가에 `[FAILED]`가 있으면 통과"는 실제로
  변이를 놓쳤다(인터프리터 분기의 마커가 다른 분기의 결손을 가렸다). 지금은 각
  실패 분기 안에서 마커를 찾는다.

### 실행 가드 (BUGS #51)

`test_db.py` / `test_docs.py` / `test_docs2.py`는 이름과 달리 테스트가 아니다 —
assert가 0개이고 실제 `courtauction.go.kr`에 접속한다. 이제 `ALLOW_LIVE_CRAWL=1` 없이는
`[SKIPPED]`를 남기고 즉시 종료한다.

회귀 스윕은 이 셋을 **"설계상 건너뜀"**으로 분류해야 한다(실패도, 환경부재도 아니다).

```
python test_api_regression.py          616검사
그 외 test_*.py 20개                   18 PASS / 3 설계상 건너뜀
npm run test:frontend                   86검사
```

### Sprint 55 프런트엔드 추가

| 파일 | 추가 | 내용 |
|---|---|---|
| `tests/source-contract.test.mjs` | 3 | 검색 파라미터 계약 — 프런트가 만드는 쿼리 키가 백엔드 파라미터를 벗어나지 않는가 |
| `tests/rights-analysis.test.mjs` | 4 | `MISSING_SPEC` vs `SPEC_NOT_PARSED` 구분, 문서 확보가 신뢰도를 바꾸지 않음 |

**검색 파라미터 계약이 왜 필요했나** — `SearchForm.buildSearchQuery()`가 백엔드에 없는
파라미터 5개(면적 4 + 특수조건 1)를 만들고 있었다. FastAPI는 모르는 쿼리 파라미터를
**조용히 무시**하므로, 값이 실리는 순간 "조건을 걸었는데 전체 결과가 나오는" 상태가 된다.
현재는 해당 UI가 "준비 중입니다" 자리표시자라 값이 실릴 수 없어 무해하지만, 그 사실이
주석에만 있었다. 미지원 목록을 테스트에 고정해 **늘어나면 실패하고, 구현되면 목록에서
빼도록** 강제한다. 변이 4종 전부 검출.

프런트엔드 합계: **93검사** (Sprint 54 기준 86 → 93)

---

## Sprint 56 추가 (2026-08-11)

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_pipeline_integrity.py` (신규) | 30 | 파이프라인 단계 간 정합을 **불변식으로 고정** |
| `test_state_machines.py` §8 | 14 | 깨진 만료 시각이 안전하게, 그러나 **조용하지 않게** 처리되는가 |
| `test_race_conditions.py` §5 | 5 | TOCTOU 가드 결정적 구조 검사 |
| `test_api_regression.py` §10 | 10 | 미결제 신청의 관리자 전이/다운로드 차단 |

### 레이스 테스트는 가드를 제거해 보기 전까지 의미가 없다 (BUGS #53)

`test_race_conditions.py`는 4가지 동시성 방어를 검증한다고 돼 있었지만, 실제로 가드를
제거해 보니 **절반이 통과했다.** 스레드를 순서대로 `start()`만 해서 요청이 겹치지 않았다.

```
                                   수정 전   수정 후
BEGIN IMMEDIATE 제거 (무료한도)      2/3      4/4    Barrier + 경합 폭 10->24
조건부 UPDATE 제거 (관리자 TOCTOU)   0/4      4/4    결정적 구조 검사로 대체
```

관리자 TOCTOU는 스레드 수를 6으로 늘리자 검출률이 **오히려 1/5로 나빠졌다** —
Barrier 해제가 계단식이라 첫 스레드가 커밋을 마친 뒤에야 나머지가 SELECT에 도달한다.
창이 수 마이크로초라 실제 스레드로는 안정 재현이 불가능하다고 판단하고,
확률적 테스트(2스레드)와 **결정적 구조 검사**를 함께 두는 방식으로 바꿨다.

### "어느 가드가 막았는지"까지 봐야 한다 (BUGS #54)

기존 "미완료 다운로드" 검사는 `success == False`만 봤다. 다운로드의 COMPLETED 검사를
통째로 없애는 변이를 넣었더니 `doc_url`이 NULL이라 다른 오류로 떨어져 **그대로 통과했다.**
지금은 `error` 코드와 메시지가 실제 상태를 밝히는지까지 고정한다.

### 프런트엔드 결과는 `fail 0`만 보고 판단하지 말 것

dev 서버가 내려가 있으면 `frontend-contract.test.mjs`의 `before()`가 실패해 그 파일 전체가
**cancelled**가 된다. 그때 출력은 이렇게 보인다.

```
tests 93 / pass 45 / fail 0 / cancelled 48      exit code = 1
```

`fail 0`만 읽으면 초록으로 오인한다. **`cancelled`와 종료 코드를 함께** 봐야 한다
(2026-08-11 이 저장소에서 실제로 겪음). 하네스 자체는 정상적으로 exit 1을 낸다.

### 현재 게이트

```
python test_api_regression.py            627검사
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 57 (2026-08-11) — `auction.db` 되돌아감 복구, 신규 테스트는 없음

`docs/BUGS.md` #57. `test_schema_hygiene.py`/`test_pipeline_integrity.py`가 이미 갖고 있던
검사(migration_history 완전성, done↔READY 정합)가 실제로 드리프트를 잡아냈다 — 신규 테스트
작성 없이 기존 회귀가 문제를 검출한 사례. `audit_logs` dangling 698행/`document_status`
574행은 데이터 보정이며 테스트 로직 변경은 없었다.

## Sprint 58 (2026-08-12) — 환불/Webhook 재처리 동시성 커버리지 공백 해소

`docs/roadmap.md` Sprint 57 이후 배경: Admin 키가 실제로 설정된 것을 확인(§ENVIRONMENT_VARIABLES.md
갱신)한 뒤 Admin 엔드포인트 41개를 API Contract Audit으로 재점검하다, 환불(`POST
/admin/payments/{id}/refund`, Sprint 52 신설)과 Webhook 재처리(`POST
/admin/payments/webhooks/{id}/reprocess`, Sprint 53 신설) 둘 다 소스에 `BEGIN IMMEDIATE` +
조건부 UPDATE 가드가 있는데도 **동시 요청 회귀가 없었다** — 순차 재현(`test_api_regression.py`
§29/§32)만 있고 `test_race_conditions.py`에는 두 경로 모두 없었다. Sprint 38의 교훈
("순차 재현만으로는 동시성 결함을 검출 못한다")이 두 신규 경로에는 아직 적용 안 된 상태였다.

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_race_conditions.py` §5 (신규) | 6 | 결제 환불 동시 요청 — 3스레드, 결제액의 절반보다 큰 부분환불을 동시에 3번 보내 총 환불액이 결제액을 넘지 않는지 |
| `test_race_conditions.py` §7 (신규) | 5 | 환불 가드 결정적 구조 검사(`BEGIN IMMEDIATE`/`WHERE id=? AND status=?`/rowcount/rollback/409) |
| `test_race_conditions.py` §8 (신규) | 3 | Webhook 재처리 가드 결정적 구조 검사(`reprocess_webhook`/`_apply_webhook_event` 공유 가드) |

### 스레드 재현은 이번에도 신뢰할 수 없었다 — 구조 검사가 실제로 잡아낸 것은 구조 검사뿐

환불 레이스(§5)에 대해 두 가지 변이를 직접 넣어 검증했다.

```
                                        §5(스레드) 검출   §7(구조) 검출
BEGIN IMMEDIATE 제거                    실패(미검출)      성공
UPDATE의 "AND status=?" 제거            실패(미검출)      성공
```

3스레드 재현은 두 변이 모두 놓쳤다(BEGIN IMMEDIATE 제거는 실행할 때마다 결과가 달라지는
진짜 flaky였고, WHERE 조건 제거는 매번 조용히 통과했다 — `BEGIN IMMEDIATE`가 전체
읽기-판단-쓰기 구간을 이미 완전히 직렬화해 그 안쪽 가드까지 창을 벌리지 못했기 때문으로
추정). Sprint 56이 Admin TOCTOU에서 이미 겪은 것과 같은 결론 — **좁은 창은 스레드 수를
늘려도 안정 재현되지 않는다** — 이 세 번째 사례로 재확인됐다. §7 구조 검사가 두 변이를
전부 결정적으로 잡아냈다(수정 후 원복해 정상 통과 확인).

### 현재 게이트

```
python test_api_regression.py            627검사 (무변동)
test_race_conditions.py                  41검사 (22 -> 41, 신규 3시나리오)
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀(test_db.py/test_docs.py/test_docs2.py, ALLOW_LIVE_CRAWL 가드)
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 59 (2026-08-12) — Admin 구독 상태 변경 동시성 결함(BUGS #58) + 회귀 신설

`test_race_conditions.py`에 2개 시나리오 추가.

| 파일 | 검사 | 대상 |
|---|---|---|
| `test_race_conditions.py` §9 (신규) | 4 | Admin 구독 상태 변경 동시 요청 — 2스레드, 같은 목표(CANCELLED)로 동시 PATCH 시 정확히 1건만 성공 |
| `test_race_conditions.py` §10 (신규) | 4 | 구독 상태 변경 가드 결정적 구조 검사(`BEGIN IMMEDIATE`/`WHERE id=? AND status=?`/rowcount/rollback) |

Sprint 58의 refund/webhook 재처리 감사와 같은 방식(변이 주입 → 스레드/구조 검사 각각의
검출력 비교)으로 검증했다. 결과도 동일했다 — 스레드 재현(§9)은 두 변이(락 제거/조건부
WHERE 제거) 모두 놓쳤고, 구조 검사(§10)만 결정적으로 잡아냈다.

### 현재 게이트

```
python test_api_regression.py            627검사 (무변동)
test_race_conditions.py                  49검사 (41 -> 49, 신규 2시나리오)
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 60 (2026-08-12) — 만료 구독 재활성화 결함(BUGS #59) + 회귀 신설

`test_api_regression.py` §27(admin rest structure)에 11개 검사 추가: expires_at 없이
재활성화 거부(400 + DB 불변) / 형식 오류 거부(400) / expires_at과 함께면 성공(200 +
effective_status/is_entitled 일치 + DB 반영) / PAUSED→ACTIVE 재개는 영향 없음(회귀 방지).

`test_race_conditions.py` §10(구독 상태 변경 구조 검사)을 change_status()의 UPDATE 분기가
2개에서 4개로 늘어난 것에 맞춰 갱신(개수 검사만 정합화, 새 시나리오 아님).

### Sprint 60 마무리 — Release 준비 최종 검증

Commit 전 사용자 지정 11개 회귀 체크리스트를 하나씩 대조하다 ACTIVE→CANCELLED/
ACTIVE→EXPIRED가 실제 Admin 엔드포인트로는 한 번도 검증되지 않았음을 발견(내부 상태머신
순수 로직 테스트만 있었다) — `test_api_regression.py` §27에 8개 신규(638 → 646검사).
`BEGIN IMMEDIATE`/조건부 UPDATE 제거 변이를 최종 재검증(§10이 결정적으로 검출), 저장소
전체에 mutation-test 임시 코드·scratch 파일 잔여 0건 확인.

### 현재 게이트 (최종, Sprint 60 Release 시점)

```
python test_api_regression.py            646검사 (627 -> 638 -> 646)
test_race_conditions.py                  49검사 (무변동, 구조 검사 갱신만)
그 외 test_*.py 21개                     19 PASS / 3 설계상 건너뜀
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
```

---

## Sprint 61 (2026-08-12) — 개인화 도메인 IDOR 커버리지 + 크롤러 복구 경로 회귀

### 배경 — 결함이 아니라 "검증된 적 없음"을 찾은 Sprint

Admin API 계약과 Favorites/Search Presets/Recent Items를 전수 감사했다. **제품 결함은
0건**이었다(모든 소유권 경계가 실제로 지켜지고 있었다). 대신 **검증 공백**을 찾아 메웠다.

### `test_api_regression.py` +14검사 (646 → 660)

**§5 favorites (+6)**
- 남의 즐겨찾기 삭제 시도가 거부되고 **실제로 지워지지도 않는다**
  (`success=False`만 보면 "지워놓고 에러 반환"하는 구현도 통과한다)
- 검색 결과 개인화 3갈래: 소유자 `is_favorited=true` / **다른 로그인 사용자 false** /
  비로그인 false. 소유자 true만 검증하면 "전역 true" 구현이 통과한다

**§6 recent items (+6)** — 이 섹션은 그동안 **격리·정렬·상한 검사가 전부 0건**이었다
- 다른 사용자에게 최근 조회가 새어나가지 않는다
- `viewed_at DESC` 정렬 / 재조회 시 맨 앞으로 이동 / 중복 행 없음 / 다른 행 유실 없음
- 응답이 `LIMIT 20`으로 잘린다

**§7 search presets (+2)**
- 남의 preset 삭제 거부 후 **실제로 남아 있는지** + 남의 목록에 새지 않는지

### `test_document_queue.py` +8검사 — `reset_stale_queue()` 직접 회귀 (신규)

`doc_worker.py`가 기동 시 **가장 먼저 부르는 크래시 복구 함수**인데 직접 검사가 0건이었다
(`test_pipeline_integrity.py`는 "지금 정체된 행이 없다"는 결과만 볼 뿐 로직을 검사하지 않는다).

회수해야 하는 것(죽은 Worker의 in_progress / 하루 지난 failed + retry_count 초기화)보다
**회수하면 안 되는 것**이 더 중요하다 — 살아있는 Worker의 in_progress를 되돌리면 같은
문서를 두 프로세스가 동시에 수집한다. 그래서 in_progress(최근)/failed(최근)/SKIPPED_EXPIRED/
done/pending 5종이 **그대로 남는지**를 함께 단언한다.

### 변이 검증 11/11 검출

| 대상 | 변이 | 결과 |
|---|---|---|
| `recent_items.py` | `WHERE ri.user_id=?` 무력화 | 검출 |
| `recent_items.py` | `LIMIT 20` → 50 | 검출 |
| `recent_items.py` | `ORDER BY viewed_at DESC` → ASC | 검출 |
| `recent_items.py` | `DO UPDATE SET viewed_at` 무력화 | 검출 |
| `search.py` | favorites 조회에서 user 필터 무력화 | 검출 |
| `search_presets.py` | DELETE의 user_id 조건 무력화 | 검출 |
| `favorites.py` | DELETE의 user_id 조건 무력화 | 검출 |
| `database.py` | in_progress 10분 가드 제거 | 검출 |
| `database.py` | failed 1일 가드 → 1분 | 검출 |
| `database.py` | `retry_count=0` 초기화 제거 | 검출 |
| `database.py` | in_progress 회수에 done 포함 | 검출 |

전부 변이 후 **byte 단위 원복 확인**(SHA256 대조, `git diff` 0).

### 함정 — 시계 분해능 때문에 통과하던 정렬 검사 (기록해 둘 것)

recent-items 정렬 검사를 처음에는 "HTTP로 연속 조회 후 순서 확인"으로 썼는데,
`ORDER BY ... DESC`를 `ASC`로 뒤집어도 **통과했다**. 원인은 Windows `datetime.now()`
분해능(~1~16ms)보다 요청이 빨라 `viewed_at`이 **같은 값으로 묶이고**, 정렬이 tie-break
(`ri.id`)로 결정된 것이었다. 실데이터에는 동률이 0건이라 운영 문제가 아니라 **테스트 설계
문제**였다. `viewed_at`을 명시적으로 다른 값으로 심는 방식으로 바꿔 결정적으로 만들었다.

"정렬 검사는 정렬 키가 실제로 여러 값인 데이터에서만 의미가 있다" — 아래 BUGS #60도 같은 축이다.

### `tests/frontend-contract.test.mjs` — 데이터 의존 검사 정정 (BUGS #60)

crawl_date 정렬 검사가 실패했으나 **제품은 정상**이었다. 크롤 중단(#46)으로 기일이 남은
물건이 14건까지 줄고 전부 같은 `crawl_date`가 되어, 정렬 키가 상수인 집합에서 asc/desc가
같은 순서를 내는 **올바른 동작**이 실패로 보인 것이다. 검사 대상을 `include_closed=true`
집합(crawl_date가 실제로 여러 값)으로 바꿨다 — **assertion은 약화하지 않았다.**

### 현재 게이트 (Sprint 61)

```
python test_api_regression.py            660검사 (646 -> 660)
test_document_queue.py                    +8검사 (reset_stale_queue 신규)
그 외 test_*.py                          20 PASS / 3 설계상 건너뜀 (총 23개 파일)
npm run test:frontend                     93검사 PASS (cancelled 0 확인)
변이 검증                                 11/11 검출, 소스 byte 단위 원복
python -m compileall / tsc / eslint / next build   전부 통과
```

### 실행 환경 변화 (Sprint 61)

`selenium` / `webdriver-manager` / `pandas` / `pdfplumber`를 **실제로 설치**했다
(Sprint 54부터 크롤 중단의 직접 원인으로 기록돼 있던 항목). 크롤러 계열 19개 모듈이
전부 import되는 것까지 확인했다. `test_db.py`/`test_docs.py`/`test_docs2.py`는 selenium이
생긴 뒤에도 `ALLOW_LIVE_CRAWL=1` 가드 때문에 여전히 정상적으로 SKIP된다(의도된 동작).
**실제 크롤 실행은 하지 않았다** — 외부 사이트 접속이라 운영 판단 영역이다.

---

## Sprint 62 (2026-08-12) — 파이프라인 후반 실행 검증 + 결함 2건 회귀

### 왜 지금 가능해졌나

`load_rights_data.py` / `load_spec_data.py`는 이 저장소에서 `rights_summary` /
`tenant_rights`를 쓰는 **유일한 코드**인데 테스트가 0건이었다. pdfplumber/pandas가 없어
실행 자체가 불가능했기 때문이다(Sprint 61에 설치). 이번에 처음 실제로 돌려 보고
**결함 2건**을 찾았다 — "문서만 읽고 정상이라고 판단하면 안 된다"의 또 다른 사례다.

### 신규 `test_rights_data_load.py` (27검사)

실제 `auction.db` / `documents/`를 건드리지 않는다 — 임시 DB(스키마는 `migrate_v4_1.py`
**실제 코드**로 생성)와 임시 documents 디렉터리에서만 수행한다.

| # | 검사 | 왜 중요한가 |
|---|---|---|
| 1 | 정상 적재 + 근거 없는 컬럼 NULL 유지 | 이 도메인의 대원칙(추정/생성 금지) |
| 2 | 임차인 0명(공실) | `is_vacant` 성공 경로 |
| 3 | 근거 문서 사라지면 파생 행 정리 | BUGS #62 회귀 |
| 4 | **안전장치**: 문서 0건이면 아무것도 안 지움 | 경로 문제로 **전체 삭제**되는 최악 시나리오 방어 |
| 5 | 파일은 있는데 결과가 비면 지우지 않음 | 파서 회귀와 구분 불가하므로 보수적 |
| 6 | 멱등성 | 반복 실행 시 행 중복/증식 없음 |
| 7~8 | SPEC 정리 + SPEC 안전장치 | 같은 결함이 두 스크립트에 있었다 |

SPEC 검사는 **유효한 PDF 없이** 수행한다 — `load_item()`이 파싱 실패를 `parse_error`로
처리하므로 "파일이 존재한다"는 사실만으로 근거 판정에 필요한 조건이 성립한다.

### `test_doc_storage_atomicity.py` +8검사 — 빈 캡처 판별 (BUGS #61)

순수 함수 판별(빈 골격 / 채워진 데이터 / 빈 문자열 / None / 라벨만 있는 경우 / 공백 표기)에
더해, **크롤러가 그 판정을 저장 전에 실제로 쓰고 있는지**(관문 위치)까지 소스로 확인한다 —
함수만 만들고 배선하지 않는 이 저장소의 반복 패턴을 막기 위해서다.

### `test_pipeline_integrity.py` — 근거 존재 불변식

`rights_summary` / `tenant_rights`의 모든 행에 대해 근거 문서(status.html / spec.pdf)가
실제로 존재하는지 검사한다. `tenant_rights.source` 표기 검사도 함께 둔다 — 새 source 값이
생기면 위 검사가 그 행을 통째로 건너뛰어 **조용한 커버리지 구멍**이 되기 때문이다.

### 변이 검증 14/14 검출

가장 중요한 것은 **원래 버그 형태를 재현한 변이**다. 판별 함수를 `bool(text)`(= 수정 전
동작)로 되돌리면 검사가 실패한다 — 이 회귀가 과거 실제 결함을 검출할 수 있음을 뜻한다.
안전장치를 끈 변이에서는 권리분석 데이터 162행/281행이 전부 삭제되는 것을 확인했다.

전 변이에서 소스를 SHA256 대조로 **byte 단위 원복** 확인(`git diff` 잔여 0).

### 현재 게이트 (Sprint 62)

```
python test_api_regression.py            661검사
test_rights_data_load.py                  27검사 (신규)
그 외 test_*.py                          24개 파일 전부 PASS (3개는 설계상 SKIP)
npm run test:frontend                     93검사 (dev 서버 필요 — cancelled 확인 필수)
변이 검증                                 14/14 검출
compileall / tsc / eslint(0) / next build 전부 통과
```

### Sprint 62 dead code 스캔 (AST 기준, 저장소 전체 참조 대조)

`api/` `storage/` `crawler/` `normalizer/` `validator/` `models/` `config/` 전체 함수 정의를
AST로 뽑아 저장소 전체(.py/.ts/.tsx/.mjs) 텍스트에서 참조 횟수를 셌다. 라우트 핸들러는
데코레이터로 등록되므로 제외했다.

```
정의됐지만 어디서도 참조되지 않는 함수: 3개
  api/v1/subscriptions.py:99   get_active_subscription   (Sprint 29부터 알려진 항목, P3)
  config/courts.py:66          get_court_by_code         (Sprint 43부터 알려진 항목, P3)
  crawler/doc_crawler.py:153   _hash_bytes               (Sprint 62 신규 확인, P3)
```

셋 다 **삭제하지 않았다** — "사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다"는
프로젝트 규칙에 따른다. 신규 발견은 `_hash_bytes` 하나뿐이며, 같은 파일이 파일 경로 기반
해시(`calc_file_hash`)를 쓰고 있어 바이트 기반 변형만 남은 형태다.

TODO/FIXME 재탐색: 소스 전체에 3건이며 전부 `TODO(API 미지원)` 표기가 붙은 알려진 항목이다
(`tests/source-contract.test.mjs`가 이 표기 자체를 계약으로 고정하고 있다). 신규 0건.

---

## Sprint 63 (2026-08-12) — 배치 안전성 가드 + 큐 클레임 동시성 회귀

### `test_crawl_exit_code.py` §8 (12검사) — 배치 후보의 비대화성

문서가 배치 편입 후보로 거론하던 스크립트 중 하나가 `input()`으로 사람 입력을 기다리고
있었다. 스케줄러에서 실행되면 매달리거나 죽고 뒷 단계까지 멈춘다 — **문서 분류를 믿고
배치에 넣는 순간 사고**가 나는 자리였다.

배치 후보 9종(`mvp_scraper` / `doc_worker` / `migrate_execute` / `refresh_priority` /
`collect_documents` / `load_rights_data` / `load_spec_data` / 복구 스크립트 2종)에 입력
대기가 없는지 검사한다. 주석 안의 `input(` 은 세지 않도록 코드 부분만 본다.

반대 방향도 함께 둔다 — `analyze_docs.py`가 **여전히 대화형이고 DB를 쓰지 않는지**.
나중에 이것이 진짜 파이프라인 단계가 되면 검사가 실패해 "배치 후보 목록과 문서를 함께
갱신하라"고 알린다.

> 이 검사를 처음 썼을 때 `sys.path.insert(...)`가 `"INSERT"` 문자열에 걸려 오검출됐다.
> SQL 형태(`INSERT INTO` / `UPDATE ... SET` / `DELETE FROM`)로만 판정하도록 고쳤다.

### `test_document_queue.py` §7~9 (17검사) — 큐 클레임/스킵

`claim_next_queue_item()`은 Worker가 일감을 집는 **유일한 경로**이자 동시 클레임을 막는
가드인데 검사가 0건이었다. `mark_queue_skipped_expired()`도 마찬가지였다.

| 검사 | 내용 |
|---|---|
| 선택 규칙 | 우선순위 ASC → 기일 ASC 순, 반복 호출 시 순서대로 소진 |
| 상태 필터 | done / failed / SKIPPED_EXPIRED / in_progress 는 집지 않는다 |
| 전이 | pending → in_progress + `last_attempt_at` 기록 |
| 재시도 간격 | 30분 전에는 안 집고, 지나면 다시 집는다 |
| **동시성** | **8스레드가 12건을 동시 클레임 — 중복 0, 전건 정확히 1회씩** |
| 스킵 | `SKIPPED_EXPIRED`는 **재시도 횟수를 소모하지 않는다** |

### 스레드 재현이 유효한 경우와 아닌 경우 (이번에 갈린 지점)

Sprint 58/59는 "스레드 재현은 변이를 놓치고 구조 검사만 잡아냈다"고 기록했다. 원인은
`BEGIN IMMEDIATE`가 구간을 이미 직렬화해 안쪽 가드까지 창이 벌어지지 않기 때문이었다.

`claim_next_queue_item()`은 배타 트랜잭션 없이 조건부 UPDATE만 쓰므로 경합 창이 실제로 넓다.
조건부 UPDATE를 제거한 변이에서 **8스레드 재현이 3회 연속 전부 검출**했다(중복 배분 발생).

**교훈** — "스레드 재현은 못 믿는다"가 아니라 **가드 구조에 따라 다르다**. 배타 락으로
직렬화된 경로는 구조 검사가 필요하고, 조건부 UPDATE만 있는 경로는 스레드 재현이 유효하다.

### 변이 검증 5/5 검출 (Sprint 63분)

```
조건부 UPDATE 제거      DETECTED  <- 스레드 재현이 잡음 (3회 연속)
rowcount 가드 제거      DETECTED
정렬 역전               DETECTED
재시도 간격 무력화       DETECTED
SKIPPED_EXPIRED가 재시도 소모   DETECTED
```

소스는 SHA256 대조로 byte 단위 원복 확인.

### 변이 테스트의 함정 — `__pycache__` 때문에 "원복했는데도 변이가 살아있다" (Sprint 63 실측)

이번 Sprint에 실제로 겪은 일이라 반드시 기록해 둔다.

`calc_priority()`의 `except: return 3`을 `return 1`로 바꾸는 변이를 넣고, 검사 후
원본 바이트로 되돌린 뒤 SHA256을 대조해 **"restored byte-exact: True"를 확인**했다.
그런데 바로 다음에 돌린 전체 스위트에서 그 변이의 증상(`형식 오류 -> 3`이 `1`로 나옴)이
그대로 재현됐다.

원인은 소스가 아니라 **바이트코드 캐시**였다. Python은 `.pyc` 유효성을 `(mtime, size)`로
판단하는데, `return 3` → `return 1`은 **길이가 같다**. 되돌리는 쓰기가 같은 mtime 눈금
안에서 일어나면 캐시가 여전히 유효하다고 판정돼, **변이 버전으로 컴파일된 `.pyc`가 계속
쓰인다.** git diff도 SHA256도 깨끗한데 실행만 오염된 상태다.

이것이 위험한 이유는 두 방향 모두다.
- 원복 후 스위트가 **거짓 실패**한다(이번 경우).
- 반대로 변이를 넣었는데 캐시가 남아 **거짓 통과**하면 "검출됨"이라는 결론 자체가 틀린다.

**규칙** — 변이 테스트 전후에는 `__pycache__`를 지운다. 길이가 같은 변이
(`3`→`1`, `>`→`<`, `True`→`False`)일수록 반드시 필요하다.

```bash
find . -name "__pycache__" -type d -not -path "./node_modules/*" -exec rm -rf {} +
```

이번 Sprint의 변이 결과는 캐시를 지운 뒤 전부 재확인했다.

---

## Sprint 64 (2026-08-12) — 경계가 만나는 지점 검증

### 왜 이 두 곳인가

이 저장소의 검사는 도메인별로는 촘촘한데, **두 도메인이 만나는 지점**은 비어 있었다.
Admin이 바꾼 것이 사용자에게 보이는지, 관리자 조정이 실제 사용량과 섞였을 때 산술이
맞는지는 어느 쪽 테스트의 책임도 아니어서 아무도 확인하지 않았다.

### §31-B Admin↔사용자 일관성 (25검사)

한 구독을 세 관점에서 동시에 본다 — 하나라도 어긋나면 실패한다.

| 관점 | 무엇을 보는가 |
|---|---|
| `GET /subscriptions/me` | 사용자가 화면에서 보는 상태 |
| `GET /admin/subscriptions` | 운영자가 보는 상태 |
| `has_active_subscription()` | 실제 기능 접근을 결정하는 게이트 |
| DB `subscriptions.status` | 저장된 진실 |

PAUSED → 재개 → 해지 순으로 돌리며 매 단계 네 값이 일치하는지 확인하고, 마지막에
**해지 사용자가 등기부를 무료로 쓸 수 없는지**까지 확인한다(매출 누수 방지).

### §20-B 조정 × 사용 혼합 산술 (20검사)

`effective_limit = plan_limit + adjustment`, `remaining = effective_limit - used`
두 항등식을 GRANT +3 → 실제 사용 2건 → DEDUCT -1 각 단계에서 단언한다.
핵심은 **사용 후 DEDUCT가 `used`를 건드리지 않는 것** — 건드리면 사용자가 쓰지도 않은
횟수를 잃는다.

### 오탐을 걸러낸 과정 (기록해 둘 가치가 있는 실패)

조사 중 두 건이 버그처럼 보였다.

1. "만료 구독인데 이용권 게이트가 True" → 재현해 보니 그 사용자가 **다른 ACTIVE 구독**을
   함께 갖고 있었다. 게이트는 사용자 단위 판정이므로 정상. 깨끗한 사용자로 다시 확인하니
   만료 단독 False / 유예 기간 True로 설계대로였다.
2. "해지 후 신청이 PAYMENT_REQUIRED가 아님" → 구독이 아예 없으면
   `REGISTRY_SUBSCRIPTION_REQUIRED`가 맞다. `PAYMENT_REQUIRED`는 구독은 있는데 한도를
   초과한 경우다. **내 기대가 틀렸다.**

probe가 빨간 줄을 보였다고 곧바로 버그로 기록하면 없는 결함을 만들어낸다 —
**격리 재현으로 확인한 뒤에만** 기록한다.

### 변이 검증 5/5 (Sprint 64분)

```
is_entitled 항상 True                DETECTED (11개 검사 실패)
is_entitled가 만료를 무시(상태만)      DETECTED (6개)
remaining이 사용량 무시               DETECTED (4개)
effective_limit이 조정 무시           DETECTED (9개)
사용이 balance_after를 2배 차감        DETECTED (1개)
```

전 변이에서 `__pycache__`를 지우고 실행했다(Sprint 63의 캐시 함정 규칙 적용).

### 테스트 잔여 데이터에 관한 실측 메모

작업 중 `no dangling audit rows left` 검사가 두 번 실패했는데, **둘 다 제품이 아니라
내 쪽 문제**였다.
- 한 번은 테스트가 NameError로 중단돼 cleanup이 끝까지 못 간 잔여
- 한 번은 scratchpad probe의 cleanup이 `audit_logs.target_id`를 user_id로 잘못 지운 것
  (REGISTRY_CREDIT 감사의 target_id는 **credit_id**다)

이 검사는 정확히 제 역할을 했다. 정리 후 **연속 2회** 실행해 잔여 0을 확인했다.

---

## Sprint 66 (2026-08-12) — 배치 편입 전 감사 + 약한 검사 강화

### `test_doc_storage_atomicity.py` +14검사 — collect_documents 저장 경로 (BUGS #64)

배치 편입 Backlog에 올라 있던 스크립트가 **뷰어가 서빙하지 않는 경로**에 저장하면서
`document_status`를 READY로 바꾸고 있었다. 실행된 적이 없어 피해는 0건이었지만,
스케줄에 넣는 순간 손대는 문서마다 "화면은 열람 가능, 뷰어는 404"가 된다.

검사 구성:
- 뷰어(`api/v1/documents.py`)의 파일명 정의와 `CANONICAL_DOC_FILENAME`을 **소스 대조**
  (두 곳에 정의가 있는 이유는 `doc_paths`가 fastapi 무의존이어야 하기 때문 — 갈라지면 404)
- canonical 경로가 `documents/` 아래인지, 파일명이 `spec.pdf`/`status.html`인지
- STATUS가 PDF 다운로드 대상에서 제외됐는지(포함하면 매번 FAILED가 찍힌다)
- **배선 확인** — `collect_all`이 실제로 최종 경로를 `save_doc_raw()`에 넘기는지
- **실동작** — 파일이 실제로 옮겨지고, 원본이 남지 않고, 내용이 보존되고,
  `doc_exists()`가 그 경로를 완료로 인정하는지

### `test_api_regression.py` — `/document-stats` 약한 검사 강화

기존 검사는 이랬다.

```python
check("document-stats status", r.status_code, 200)
check_true("document-stats has total_items", "total_items" in r.json())
```

숫자 8개를 돌려주는 엔드포인트인데 **어느 값도 맞는지 확인하지 않았다.** 집계 쿼리가
doc_type을 잘못 세도 통과한다. 각 숫자를 **자기 출처 테이블과 직접 대조**하도록 바꿨다
(`total_items` ↔ `auction_item`, 6개 성공/실패 ↔ `document_status`,
`total_failures` ↔ `document_collect_failures`).

### 데이터가 우연히 같아 변이가 살아남은 사례 (반드시 기록해 둘 것)

`total_failures`의 출처를 다른 테이블로 바꿔치기하는 변이가 **살아남았다.**
현재 DB에서 `document_collect_failures`(3)와 `document_status FAILED`(3)가 **우연히
같았기 때문**이다. 값 비교만으로는 두 출처를 구분할 수 없었다.

해결: 한쪽에만 행을 하나 넣어 두 값을 어긋나게 만든 뒤, 엔드포인트가 **어느 쪽을 따라
움직이는지** 확인하고 넣은 행을 즉시 되돌린다. 이후 같은 변이가 **DETECTED**로 바뀌었다.

> 교훈 — "출처가 다른 두 값"을 검사할 때는 값이 같은 상태에서 단언하면 아무것도 증명하지
> 못한다. 의도적으로 어긋나게 만들어야 검출력이 생긴다.

### 등가 변이(equivalent mutant) 1건 — 테스트 약점이 아님

`doc_stats.py`의 `WHERE ... status IN ('READY','FAILED')` 필터를 제거하는 변이도
살아남았지만, 이것은 **동작이 실제로 같다**. `count_status()`가 `('SPEC','READY')` 같은
키만 조회하므로 dict에 COLLECTING 항목이 더 들어와도 절대 읽히지 않는다.
검출되지 않는 것이 정상이며, 억지로 잡으려고 검사를 만들지 않았다.

### 변이 검증 (Sprint 66분)

```
collect_documents가 다운로드 경로를 기록 (수정 전 동작)   DETECTED
STATUS를 PDF 경로로 시도 (수정 전 동작)                 DETECTED
canonical 파일명이 뷰어와 불일치                        DETECTED
PDF 대상 집합에 STATUS 추가                            DETECTED
비원자적 이동(shutil.copy)                             DETECTED
doc-stats: spec_success가 FAILED를 셈                  DETECTED
doc-stats: total_failures 출처 바꿔치기                 DETECTED (강화 후)
doc-stats: status 필터 제거                            등가 변이(정상적으로 미검출)
```

---

## Sprint 67 (2026-08-12) — collect_documents 저장/실패 경로 (신규 `test_collect_documents.py`, 26검사)

### 왜 필요했나

Sprint 66이 이 스크립트의 **경로** 결함(BUGS #64)을 고쳤지만, 검증 범위는 경로 계산과
파일 이동까지였다. **DB 기록 쪽(성공/실패 상태 전이)은 여전히 미검증**이었고,
그 공백에서 실제 결함(BUGS #65)이 나왔다.

### 구성 (selenium 불필요)

브라우저가 필요한 `download_doc()`은 대상이 아니다. 그 뒤 단계인
`finalize_download()` / `save_doc_raw()` / `save_failure()`만 직접 호출한다.
임시 DB + 임시 documents 루트를 쓰며 실제 `auction.db`/`documents/`는 건드리지 않는다.

스키마는 손으로 베끼지 않는다 — v4.1은 `storage/migrate_v4_1.py` 실제 코드로,
`document_collect_failures`는 Migration 017 SQL 파일로 만든다.
(테스트에 스키마를 복제하면 진짜 스키마가 바뀌어도 통과한다.)

### 잡아낸 것

`save_doc_raw()`가 0바이트 파일을 성공으로 처리해 READY로 기록하고 있었다(BUGS #65).
`doc_exists()`는 같은 파일을 미완료로 보므로 **화면·뷰어·재수집 판정 3자가 어긋난다.**
이 저장소가 이미 두 번 고친 "READY인데 못 쓰는 파일"(BUGS #50/#61)의 세 번째 형태다.

### 변이 검증 5/5

```
0바이트 가드 제거 (수정 전 동작)        DETECTED
0바이트가 READY로 흘러감 (수정 전 동작)  DETECTED
성공인데 FAILED로 기록                 DETECTED
버전이 증가하지 않음                    DETECTED
실패를 성공으로 보고                    DETECTED
```

### 참고 — 이 스크립트를 배치에 넣기 전 남은 확인

`collect_documents`는 `document_queue`를 갱신하지 않는다. 실행하면
`test_pipeline_integrity.py`의 "파일이 있으면 큐도 done" 불변식이 일시적으로 실패한다
(다음 `doc_worker` 실행에서 자가 치유). 이것은 버그가 아니라 **소유권 결정**(roadmap 16-B)
대상이므로 Sprint 67은 표만 남기고 구현하지 않았다.

### Sprint 67 이어서 — `test_collect_documents.py` §7~8 (수렴 시나리오, 총 53검사)

**selenium 없이 doc_worker 경로를 재현하는 방법**

`collect_spec()`은 `doc_exists()`가 참이면 **driver를 건드리기 전에** `success=True`로
단락한다. 그래서 `driver=None`으로 실제 함수를 그대로 호출할 수 있다. 이 단락이 사라지면
테스트가 크래시하므로(변이로 확인), 이 방식은 우회가 아니라 **단락이 load-bearing임을
함께 검증**하는 셈이다.

| § | 시나리오 | 확인 대상 |
|---|---|---|
| 7 | collect_documents 수집 → doc_worker | 큐/document_status/파일/doc_raw/version log |
| 8 | 실패 → 재시도 간격 → 성공 | 큐 상태·retry_count·document_status·doc_exists |

두 시나리오 모두 **HTTP status가 아니라 4개 저장소(큐·상태·원장·파일시스템)를 함께**
확인한다.

**fixture가 운영과 달라 생긴 실패 — assertion을 낮추지 않고 fixture를 고쳤다**

`auction_case` 연결 없이 `auction_item`만 만들었더니 §8에서 "큐는 done인데
document_status는 COLLECTING"이 나왔다. 원인은 제품이 아니라 fixture였다 —
`_set_document_status()`가 `auction_case` JOIN으로 item_id를 찾기 때문이다.
(코드는 이 상황을 조용히 넘기지 않고 경고를 남긴다.)

fixture를 운영과 같게(=`migrate_execute.py`가 만드는 형태로) 고쳐 통과시켰고,
그 결과 **`mark_queue_done`의 상태 동기화가 case 연결에 의존한다**는 사실도 회귀에 고정됐다.

스키마 준비도 실제 부트스트랩 절차 그대로다 — `init_db()` → `migrate_v4_1()` →
`run_migrations()`. 필요한 것만 골라 적용하다 Migration 011의 `auction_case.court_code`를
빠뜨려 깨진 적이 있다. **부분 적용은 진짜 스키마와 어긋난다.**

### Sprint 67 이어서 — Concurrency Audit 완결 (`test_race_conditions.py` 49 → 58검사)

**§11 등기부 크레딧 조정 (append-only 원장)**

다른 경합 지점과 달리 방어 코드가 **없어도 되는** 경로다 — `add_credit()`은 현재 합계를
읽지 않고 INSERT만 한다. 그런데 그 안전성이 검증된 적이 없었다. 12스레드 동시 조정으로
원장 행 수 = 요청 수, 합계 정확(유실·중복 0)을 고정했다.

> 이 검사의 목적은 "지금 안전함"이 아니라 **"나중에 읽기-판단이 들어오면 잡는 것"**이다.
> 누적 상한이나 잔액 확인을 추가하는 순간 조용히 경합이 생긴다.

**§12~13 검색조건 저장 상한 (BUGS #66)**

§12는 실스레드 재현(99개 + 12 동시 요청 → 정확히 1건 성공, 최종 100개),
§13은 결정적 구조 검사(`BEGIN IMMEDIATE`/ROLLBACK/COMMIT 존재 + **COUNT와 INSERT가 모두
트랜잭션 안에 있는지** 인덱스 비교).

스레드 재현과 구조 검사를 함께 두는 이유는 Sprint 58/59의 교훈 때문이다 — 배타 락으로
직렬화된 경로에서는 스레드 재현이 창을 못 벌려 변이를 놓친다. 다만 이번 경로는
**수정 전에 락이 아예 없었으므로 스레드 재현이 확실히 잡았다**(변이 시 최종 103개).

**변이 검증 4/4**

```
BEGIN IMMEDIATE 제거 (수정 전 동작)   DETECTED  최종 103개로 상한 초과 재현
상한 검사 자체 제거                    DETECTED  최종 111개
크레딧 합계 SUM -> MAX                 DETECTED  API adjustment 불일치
크레딧 INSERT OR IGNORE                등가 변이(UNIQUE 제약이 없어 무시 조건 자체가 없음)
```

등가 변이는 억지로 잡으려 하지 않았다 — `registry_credits`에 UNIQUE 제약이 없어
`INSERT OR IGNORE`가 무시할 상황 자체가 존재하지 않음을 스키마로 확인했다.

---

## Sprint 68 (2026-08-12) — Beta 사용자 여정 Release Gate (`test_beta_journey.py`, 66검사)

### 이 파일이 메우는 공백

도메인별 테스트는 **자기 도메인만** 본다. 그래서 도메인 **사이**가 끊겨도 전부 초록이다.

```
검색 테스트      "검색이 된다"           OK
상세 테스트      "상세가 나온다"          OK
최근조회 테스트   "목록이 나온다"          OK
                 -> 그런데 상세에 들어가도 최근조회에 안 남으면? 아무도 안 잡는다
```

이 파일은 그 이음매만 노린다.

### 실행 방법과 대상 선택

```
python test_beta_journey.py           # dev 서버 없어도 실행됨(프런트 단계만 SKIPPED)
BASE_URL=... python test_beta_journey.py
```

여정 대상은 **DB에서 조건으로 고른다** — 문서 3종이 READY이고 기일이 남은 물건.
고정 id를 박아 두면 데이터가 바뀌는 순간 검사가 무의미해지거나 깨진다.

### dev 서버가 없을 때의 규약 (중요)

프런트 로그인 게이트 단계는 dev 서버가 필요하다. 없으면 **`[SKIPPED]`를 출력하고 요약에도
남긴다.** `docs/TEST_PLAN.md`에 이미 기록된 함정 — `frontend-contract.test.mjs`가 서버 없이
`cancelled`가 되면서 `fail 0`으로 보여 초록으로 오인되던 문제 — 를 반복하지 않기 위해서다.
서버를 내린 채와 올린 채 각각 실행해 두 동작을 확인했다.

### 변이 검증 3/3 — 다른 어떤 테스트도 잡지 못하는 것

```
item.py의 record_view() 호출 제거     DETECTED  (recent_items DB 0건 + 목록 빈 값)
search.py의 favorited_ids를 빈 집합으로  DETECTED  (로그인 검색 하트가 False)
registry.py의 중복 방지 플래그 제거      DETECTED
```

각 도메인 테스트는 이 변이들을 **통과시킨다** — `record_view`가 안 불려도 최근조회 API 자체는
정상이고, `favorited_ids`가 비어도 검색 API는 200이기 때문이다. 여정 테스트만 잡는다.

### 현재 게이트 (Sprint 68)

```
python test_api_regression.py      727검사
python test_race_conditions.py      69검사
python test_beta_journey.py         66검사   <- 신규 Release Gate
python test_collect_documents.py    53검사
그 외 test_*.py                     전부 PASS (총 26개 파일)
npm run test:frontend               93검사 (dev 서버 필요 — cancelled 확인 필수)
변이 누적                           58회 시도 → 56 검출 / 2 등가
```

### 현재 게이트 (Sprint 78 실측 — 2026-08-13)

Sprint 68 표기의 "총 26개 파일"이 낡았다(Sprint 74에 `test_normalizer.py`가 늘어 27개).
숫자를 손으로 관리하면 반드시 어긋나므로, **실측값으로 갱신하고 무엇을 셌는지 함께 적는다**
(`grep -cE "^\[PASS\]"` 기준. 파일마다 검사 단위가 달라 합계는 참고값이다).

```
python test_api_regression.py      786검사   (727 -> 786, Sprint 74~78 신규 포함)
python test_document_queue.py      110검사
python test_subscription_policy.py  98검사   (renew 동시성 9 신규)
python test_normalizer.py           75검사   (배치 격리 5 신규)
python test_document_status_sync.py 69검사   (재시도 복구 15 + 고아 측정 4 신규)
python test_race_conditions.py      69검사
python test_beta_journey.py         66검사
python test_collect_documents.py    53검사
python test_search.py               48검사   (필터 20 신규)
python test_auction_identity.py     43검사   (upsert 격리 16 신규)
python test_auth_jwt.py             35검사   (JWKS 12 신규)
python test_schema_hygiene.py       34검사   (UNIQUE 6 + BOM 1 신규)
그 외 test_*.py                     전부 PASS (총 27개 파일)
npm run test:frontend               93검사 (dev 서버 + FastAPI 둘 다 필요 — cancelled 확인 필수)
tsc 0 / eslint 0 / next build 성공 / compileall 0
변이 누적                           Sprint 78에 22종 추가 시도 -> 22 검출
                                    (그 중 2건은 **검사 자체의 결함**을 드러냈다 — 아래)
```

**Sprint 78에서 변이가 잡아낸 무력한 검사 2건** (변이 시험을 하지 않았다면 남았을 것):

```
검색 필터 검사    "court_name -> status 컬럼 오배선" 변이가 통과했다
                  -> 필터가 엉뚱한 컬럼에 걸리면 0건이 되고, "모든 행이 조건을 만족한다"가
                     공허하게 참이 된다. **구분력 단언**(최소 1건은 나와야 한다)을 먼저 두어 고침
하네스(3곳)      가드 제거 변이가 FAIL이 아니라 **크래시**로 끝나 남은 검사가 실행되지 않았다
                  -> `upsert_batch` / JWKS / `normalize_batch` 호출을 감싸 예외를 FAIL로 전환
```

### Sprint 78 최종 실측 (2026-08-13 세션 종료 시점)

```
python test_api_regression.py      826검사   (727 -> 826)
python test_document_queue.py      110검사
python test_subscription_policy.py  98검사
python test_normalizer.py           75검사
python test_document_status_sync.py 69검사
python test_race_conditions.py      69검사
python test_beta_journey.py         66검사
python test_validation_engine.py    62검사   <- 신규 파일(28번째)
python test_collect_documents.py    53검사
python test_search.py               48검사
python test_auction_identity.py     43검사
python test_schema_hygiene.py       42검사   (UNIQUE 6 + BOM 1 + 법원목록 8 신규)
python test_auth_jwt.py             35검사
그 외 test_*.py                     전부 PASS (총 28개 파일)
npm run test:frontend              106검사 (dev 서버 + FastAPI **둘 다** 필요 - cancelled 0 확인)
tsc 0 / eslint 0 / next build 성공 / compileall 0
```

커버리지 변화(전체 스위트 기준):

```
api/auth.py                 81% -> 96%
api/v1/search.py            82% -> 95%
api/v1/payment_providers.py 54% -> 99%   (Sprint 78에 계약을 넓힌 뒤 재측정)
normalizer/normalizer.py    85% -> 100%
validator/validation_engine 52% -> 100%
storage/database.py         80% -> 84%
전체                        71% -> 73%   (남은 미커버는 대부분 selenium 의존 crawler/*)
```

## 2026-08-13 Sprint 85 ― 실측 갱신 (미검증 경로 4개 태운 뒤)

전체 회귀를 파일별 개별 프로세스로 돌려 집계한 값이다(2회 연속 측정).

```
파일 28개                24 PASS / 4 SKIPPED / 0 FAIL
검사 총합                2,097 PASS / 0 FAIL      <- 회차마다 ±수 건(데이터 의존 분기)
총 소요                  16초 (파일별 순차 실행)
```

SKIPPED 4개는 설계상 그렇다: `test_db.py` / `test_docs.py` / `test_docs2.py`(실크롤,
`ALLOW_LIVE_CRAWL=1` 필요)와 `test_beta_journey.py`(62검사까지 돌고 남은 구간은 외부 의존).

이번에 늘어난 검사(파일별 증가분):

```
test_doc_storage_atomicity.py   +8   wait_for_download 완료 판정 (§8, BUGS #84)
test_race_conditions.py         +8   admin 409 결정적 검증 (§14, BUGS #85)
test_schema_hygiene.py          +24  init_db 옛 스키마(§10, #82) + 레거시 플래그 가드(§11, #83)
test_search.py                  +12  프론트가 보내지만 무시되는 필터 (§6, BUGS #81)
```

측정 방법에 대한 주의(이번에 실제로 겪은 것):

- **변이가 적용됐는지 반드시 확인한다.** 패턴을 바이너리로 읽은 텍스트에 `\n`으로 맞추면
  CRLF 파일에서 0곳 일치한다 ― 변이가 안 들어간 채 "SURVIVED"로 보인다. 일치 수가 1이
  아니면 즉시 표시하도록 스크립트를 짰다.
- **변이가 크래시를 만들면 그건 하네스 결함이다.** 결함이 FAIL이 아니라 예외로 나타나면
  집계에서 사라진다. 없는 칼럼 읽기/예외를 내는 함수 호출은 감싸서 FAIL로 만든다.
- **파일을 고치는 명령과 테스트를 같은 블록에서 돌리지 않는다**(Sprint 82 규칙). 저장소가
  OneDrive 동기화 폴더 안이라, 방금 쓴 파일을 읽는 순간과 겹치면 일시적 파싱 실패가 난다
  (이번에 1회 발생, 재현 안 됨 ― `compileall` 0 / 전수 ast 파싱 0실패로 확인).

### Sprint 85 후반 추가분 (커버리지 재측정 후)

```
test_api_regression.py          +19  문서 서빙 방어(§34, #86) + 관심물건 실패 격리(§35, #87)
test_document_status_sync.py    +15  현재 상태 조회 방어(§12) + READY 서빙 가능성(§11, #88)
test_schema_hygiene.py          +6   init_db 실패는 조용하지 않다 (§12, #89)
test_checkpoint_atomicity.py    +8   저장 실패는 크롤을 멈추지 않는다 (§4, #89)
```

최종 실측(2회 연속 동일):

```
파일 28개        24 PASS / 4 SKIPPED / 0 FAIL
검사 총합        2,146 PASS / 0 FAIL
전체 커버리지     79%
```

모듈별 커버리지 변화(전체 스위트 기준, 이번 Sprint):

```
api/v1/documents.py      95% -> 100%
api/v1/favorites.py      94% -> 100%
storage/checkpoint.py    91% -> 100%
storage/database.py      89% ->  90%   남은 미커버는 query() 한 함수(운영 호출부 0곳)
crawler/doc_paths.py            100%   (유지)
```

`crawler/doc_crawler.py`는 23%로 남는다 — 나머지는 selenium 드라이버를 요구하는 구간이다.
이번에 그중 브라우저 비의존 부분(`wait_for_download`)을 100% 덮었고, **호출부의 None 처리**는
실행 대신 AST 구조 검사로 고정했다(호출부는 드라이버 안에 있다).

새로 추가한 측정 규칙 하나 더:

- **변이 실행은 `-B`(바이트코드 미생성)로 한다.** 같은 파일을 길이가 같게 변이하면 `.pyc`가
  재사용되어 **앞 변이의 결과가 다음 변이의 증거로 보고된다**(2026-08-13 실측).

### Sprint 85 최종 실측

```
파일 28개        24 PASS / 4 SKIPPED / 0 FAIL
검사 총합        2,186 PASS / 0 FAIL
전체 커버리지     81%
```

이번 Sprint에 추가된 검사(파일별):

```
test_api_regression.py          +57  문서 서빙 방어(§34) / 관심물건 실패 격리(§35) /
                                     결제·Webhook 실패·멱등 분기(§36) /
                                     결제 생성 실패의 완전 롤백(§37)
test_document_status_sync.py    +15  상태 조회 방어(§12) / READY 서빙 가능성(§11)
test_doc_storage_atomicity.py   +10  wait_for_download(§8) + 호출부 None 처리(§9)
test_race_conditions.py         +8   admin 409 결정적 검증(§14)
test_schema_hygiene.py          +30  옛 스키마 보완(§10) / 레거시 플래그 가드(§11) /
                                     init_db 실패(§12)
test_checkpoint_atomicity.py    +8   저장 실패는 크롤을 멈추지 않는다(§4)
test_search.py                  +12  프론트가 보내지만 무시되는 필터(§6)
```

**검사가 무엇을 통과했는지 확인하는 규칙**(이번에 두 번 걸렸다):

- 통과했더라도 **의도한 분기에 도달했는지** 커버리지로 확인한다. Webhook 검사 두 개가
  매핑표에 없는 `event_type` 때문에 더 앞의 분기에서 걸려 통과하고 있었다.
- 방어 검사는 **가드가 없으면 실제로 나쁜 일이 일어나는 조건**으로 만든다. 경로 탈출은
  존재하는 파일을 겨눠야 하고(없으면 404가 겹친다), 안정화 판정은 반환 시점의 크기를
  봐야 한다(경로만 보면 1회/2회 규칙이 구별되지 않는다).

---

## 2026-08-13 Sprint 96 ― 변이 검증을 돌릴 때의 규율 (실제로 사고가 났다)

이번 스프린트에서 **변이가 걸린 채로 제품 파일이 남았다.** `crawler/doc_crawler.py`의
`while elapsed < timeout:`이 `while True:`인 상태로 작업 트리에 남아 있었고, 회귀 스위트가
멈추는 것으로만 드러났다. 원인은 변이 실행기가 두 가지를 하지 않아서다.

```
하위 프로세스에 타임아웃이 없었다   -> 무한 루프 변이가 실행기를 같이 멈춘다
원본 복구가 finally에 없었다        -> 실행기가 멈추면 복구가 영영 실행되지 않는다
```

### 앞으로 변이 스크립트는 이 형태를 지킨다

```python
raw = open(p, "rb").read()                     # 바이너리로 읽고
bom = raw.startswith(b"ï»¿")           # BOM 유무를 기억한다
src = raw.decode("utf-8-sig" if bom else "utf-8")

def run():
    try:
        r = subprocess.run([sys.executable, TEST], capture_output=True, timeout=45)
    except subprocess.TimeoutExpired:
        return -9, ["<TIMEOUT>"]               # 정지도 결과로 다룬다
    ...

try:
    for label, old, new in MUT:
        write(src.replace(old, new, 1)); c, f = run(); write(src)
finally:
    write(src)                                 # 반드시 원본으로 되돌린다
```

BOM을 기억했다가 그대로 다시 쓰는 부분은 예전 사고(복구가 BOM을 새로 붙여
`test_schema_hygiene.py`의 BOM 가드를 깨뜨렸다)에서 온 것이다. 두 사고를 합쳐서
**"바이너리로 읽고, 타임아웃을 주고, finally로 되돌린다"**가 이 저장소의 규율이다.

### 매 스프린트 끝에 확인하는 것

```
git diff --stat <변이 대상 파일>     변이가 남지 않았는가
git diff --name-only 로 BOM 대조     BOM이 새로 붙거나 사라지지 않았는가
```

### 가짜 시계를 쓰는 테스트는 회차를 스스로 묶는다

`wait_for_download()` 검사는 `time.sleep`을 가로채 실시간을 쓰지 않는다. 그러면 루프
종료 조건을 없애는 변이가 **실패가 아니라 정지**로 나타난다. 가짜 sleep이 폴링 횟수를
직접 세어 `timeout + 3`을 넘으면 예외를 던지게 했다 ― 같은 변이가 `[FAIL]` 한 줄이 된다.
시간을 가로채는 테스트를 새로 쓸 때 같은 장치를 넣는다.

### 프런트엔드 게이트는 두 갈래다

```
node --test "tests/**/*.test.mjs"        frontend-contract는 살아 있는 Next 서버가 필요하다
node --test tests/format.test.mjs        서버 없이 도는 순수 단위 (13/13)
```

서버가 없을 때 `npm run test:frontend`가 실패하는 것은 **환경 조건이지 결함이 아니다**
(`### dev 서버가 없을 때의 규약` 참고). 서버를 띄울 수 없는 상황에서는 순수 단위 쪽만
돌리고 그 사실을 함께 남긴다. 또한 `node --test tests/`처럼 디렉터리를 그대로 넘기면
`MODULE_NOT_FOUND`가 난다 ― 반드시 글롭을 쓴다.

---

## 2026-08-13 Sprint 98 ― 변이 검증이 **거짓말을 했다**: `.pyc` 캐시

이번 세션에서 실제로 겪은 것 중 가장 위험한 함정이다. 변이 결과 자체가 틀릴 수 있다.

### 무슨 일이 있었나

`wait_for_download`의 "연속 2회" 검사가 **소스는 멀쩡한데 계속 실패**했다.
파일을 다시 읽어도, `git diff`를 봐도 변이는 남아 있지 않았다. 그런데 실행하면 틀렸다.

```
crawler/doc_crawler.py            소스: if stable_count >= 2:   (정상)
crawler/__pycache__/doc_crawler.*.pyc  실행된 것: >= 0          (변이)
```

### 왜 Python이 캐시를 버리지 않았나

`.pyc` 헤더는 소스의 **(mtime, size)** 만 기록한다. 그런데

```
"if stable_count >= 2:"   와   "if stable_count >= 0:"   는 바이트 길이가 같다
```

변이를 쓰고 → import(=pyc 생성) → 원본을 복구하는 일이 **같은 초 안에** 일어나면
mtime도 같아진다. 크기도 같고 mtime도 같으니 Python은 **낡은 바이트코드를 그대로 쓴다.**
이 저장소의 변이는 대부분 `>= 2` -> `>= 0`, `<=` -> `<`, `True` -> `False`처럼
**길이가 같은 치환**이라 이 조건에 정확히 들어맞는다.

### 어느 방향으로도 거짓말한다

```
변이가 살아남은 것처럼 보인다   실행된 것은 원본 바이트코드였다   -> 없는 구멍을 "구멍 없음"으로 오인
원본이 실패하는 것처럼 보인다   실행된 것은 변이 바이트코드였다   -> 멀쩡한 코드를 고치려 든다
```

이번엔 두 번째로 나타나서 알아챘다. **첫 번째로 나타났다면 조용히 틀린 결론을 남겼을 것이다.**

### 규율 ― 변이 실행기는 반드시 이렇게 한다

```python
def write(t):
    open(target, "wb").write(...)
    purge(target)                      # __pycache__/<모듈>.*.pyc 삭제

subprocess.run([sys.executable, "-B", test],       # -B: 새 pyc를 쓰지 않는다
               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
               timeout=300)
```

`-B`만으로는 **부족하다** ― 쓰지 않을 뿐 **이미 있는 것은 그대로 쓴다.**
지우는 것과 쓰지 않는 것을 **둘 다** 해야 한다.

Sprint 96에서 정리한 규율(하위 프로세스 타임아웃 + `finally` 복구 + BOM 보존)에
**캐시 무효화**를 더한다. 재사용 가능한 실행기를 이 형태로 만들어 두고, 결론을 문서에
적기 전에 그것으로 한 번 더 돌린다.

### 이번에 다시 돌린 결과 (전부 캐시 안전판에서 재확인)

```
wait_for_download   8종 중 7종 검출 (.crdownload 제외는 증명된 중복 - 결론 유지)
search_presets      3종 전부 검출
admin LEFT JOIN     1종에서 검사 5개 검출
payments 연결       2종 전부 검출
```

결론은 모두 그대로였다. 다만 **그것을 확인하기 전까지는 알 수 없었다**는 것이 요점이다.

---

## Sprint 145 추가 (2026-08-17)

### `test_asset_pipeline.py` §15-B / §15-C — 큐 매각기일 정정 (신규 7검사)

BUGS #101 회귀. `document_queue.auction_date`는 06:00 적재 시점의 사본이라 실제
기일과 어긋날 수 있고, 그 상태로 종결하면 **진행 중 물건이 영구 미수집**이 된다.

| # | 검사 | 잡아내는 회귀 |
|---|---|---|
| 15-B-1 | 권위 있는 값(`auction_item`)을 돌려준다 | 사본을 계속 신뢰하는 회귀 |
| 15-B-2 | 큐 행도 함께 정정된다 | 판단만 고치고 데이터를 남겨 두는 회귀(우선순위가 계속 틀린다) |
| 15-B-3 | `status`는 건드리지 않는다 | 종결 행을 임의로 되살리는 회귀(재수집은 제품 판단) |
| 15-B-4 | 실제로 지난 기일은 그대로 과거 | **과잉 구제** — 만료 사건까지 되살려 크롤을 낭비하는 회귀 |
| 15-B-5 | 매칭되는 물건이 없으면 큐 값 유지 | 조인 실패를 "미래"로 오판하는 회귀 |
| 15-C-1 | `doc_worker`가 import한다 | 함수만 만들고 배선하지 않는 회귀 |
| 15-C-2 | 종결 호출보다 **먼저** 호출된다 | 순서가 뒤집혀 검사가 무의미해지는 회귀 |

Mutation 검증: `doc_worker`에서 reconcile 호출을 제거하면 15-C-2가 `rec=-1`로 실패한다.

### `test_pipeline_integrity.py` §11 — 예약 작업 등록 여부 보고 (보고 전용)

기존 신선도 검사는 "검색 0건"만 실패로 두고 남은 기간을 크게 출력한다(의도된 설계 —
코드로 고칠 수 없는 것을 실패시키면 곧 무시하게 된다). 그 경고문이 *"확인 순서:
스케줄러 등록 여부 -> logs/daily_run.log -> run_daily.bat"* 라고 안내하면서 정작
등록 여부를 확인해 주지 않았다.

`schtasks /query`로 조회해 **보고만** 한다. 등록 0건이면 조치 명령까지 함께 출력한다.
**단언하지 않는다** — 등록은 사용자 환경 변경이고(Sprint 112가 같은 이유로 SKIP),
로그 파일 존재 보고와 같은 취급이다. 비-Windows/권한 없음이면 "확인 불가"로 넘어간다.

> 이 두 가지가 함께 있어야 진단이 닫힌다: 신선도 검사는 **언제 망가지는지**를,
> 등록 보고는 **왜 안 채워지는지**를 답한다.

---

## test_schema_hygiene.py §6-B — 추적 파일이 미추적 파일을 import하지 않는가 (2026-08-17 Sprint 148 신설)

기존 §6은 `storage/`만 본다. Sprint 148 릴리스 감사에서 그 한계가 드러났다 —
신규 실동작 모듈 14개가 미추적이었는데 §6이 잡은 것은 마이그레이션 020 하나뿐이었다.
나머지 13개는 **어떤 테스트도 잡지 못했다**(BUGS #105).

§6-B가 고정하는 불변식은 "새 파일이 전부 추적된다"가 아니다. 새 문서나 새 테스트가
잠시 미추적인 것은 무해하므로 그것까지 실패로 만들면 잡음만 는다. 위험한 것은
**추적 중인 파일이 미추적 파일을 import**하는 간선이다. 그 상태에서 `git commit -a`로
커밋하면 작업트리에서는 전 테스트가 통과하는데 커밋된 트리는 부팅조차 못 한다.

검사 방식 — 하드코딩된 파일 목록이 없다:

```
git ls-files                          -> 추적 집합
git ls-files --others --exclude-standard -> 미추적이지만 무시 대상도 아닌 집합
  (=.gitignore 대상인 산출물/step*.py 등은 애초에 후보에서 빠진다)

미추적 .py  -> `from a.b import` / `import a.b` / `from a import b` 패턴 생성
미추적 .tsx -> `import X from './Base'` 패턴 생성
추적 중인 .py/.ts/.tsx 전부를 훑어 간선을 찾는다
```

2026-08-17 실행 결과 — 미추적 소스 10개를 대상으로 추적 파일 143개를 검사해 간선 4개
검출(오탐 0, 4개 전부 실제 import 문임을 육안 확인):

```
api/v1/documents.py:6            -> api/http_cache.py
api_server.py:32                 -> api/v1/images.py
crawler/doc_crawler.py:619       -> crawler/image_crawler.py
src/app/search/ResultList.tsx:5  -> src/app/search/ResultThumbnail.tsx
```

**이 검사는 현재 의도적으로 FAIL이다.** Commit/add 금지가 상시 제약이라 미추적
상태 자체를 해소할 수 없기 때문이다. 사용자가 `git add -A` 후 커밋하면 테스트 수정
없이 PASS로 돌아온다. `git commit -a`는 쓰면 안 된다 — 그것이 바로 이 검사가 막는 상황이다.

실패 시 출력이 간선 목록과 해소 방법을 그대로 찍으므로 별도 조사가 필요 없다.

---

## Sprint 148~157에 신설된 회귀 (2026-08-17)

이 세션에서 찾은 결함마다 회귀를 남겼다. **모두 "결함을 일부러 되돌리면 FAIL하는지"를
확인**했다 — 통과하는 검사가 실제로 무언가를 지키고 있는지는 그렇게만 알 수 있다.

### test_auction_identity.py — `document_queue` 쓰기 SQL이 법원으로 좁혀지는가

BUGS #107. 사건번호는 법원마다 독립 채번이라 전국적으로 유일하지 않다(실측: case_no
3개가 두 법원에 걸쳐 있고 물건 22건 연루). 같은 계열이 #18/#14/#103으로 세 번
반복됐는데 매번 그 인스턴스만 고쳐서 네 번째가 남아 있었다.

git이 추적하는 프로덕션 `.py`에서 `UPDATE/DELETE document_queue` 문장을 찾아,
`case_no`로 좁히면서 법원이 없으면 실패시킨다. 검사 대상은 목록이 아니라 **전수**다.

오탐을 먼저 없앴다 — 고정 길이 창으로 SQL을 읽으면 `storage/database.py`의
`WHERE id = ?`(정확한 문장)가 7줄 뒤 `logger.info`의 `case_no` 때문에 위반으로 잡힌다.
파이썬 문자열 리터럴만 정확히 읽는 `_sql_literal_at()`으로 해결했다(인접 리터럴 연결 포함).

### test_api_regression.py §16 — 문서 `doc_type` 대소문자 무관

BUGS #108. `document_status`는 대문자, `document_queue`는 소문자로 같은 개념을 저장한다.
API가 대문자만 받아서 큐 쪽 값으로 URL을 만들면 400이 났고, 그 400이 오타와 구별되지
않았다. 소문자/혼합 대소문자가 대문자와 **같은 상태·같은 본문**을 주고, 모르는 종류는
**여전히 400**이며, HEAD도 같은 규칙을 따르는 것을 고정한다.

### test_doc_worker_recovery.py 6·7·8 — 자원 수명

- **6. 드라이버 기동 실패도 락을 해제한다** (BUGS #109). `build_download_driver()`가
  락 해제를 보장하는 두 구간 **사이**에 있어서 기동 실패 시 락이 남았다. `LOCK_STALE_HOURS=5`
  덕에 영구 정지는 아니지만, 하필 곧바로 재시도해야 할 5시간 동안 후속 실행이 전부
  "이미 실행 중"으로 건너뛰어지고 그것이 **종료코드 0(성공)으로 보고**된다.
- **7. 실행 창 밖에서는 브라우저를 띄우지 않는다**. 시간 검사가 `while` 조건에만 있어
  창 밖에서도 Selenium을 띄운 뒤 첫 조건에서 빠져나왔다.
- **8. 드라이버 설정 실패가 브라우저를 고아로 남기지 않는다** (BUGS #110).
  `webdriver.Chrome(...)`으로 프로세스를 띄운 **뒤** `set_page_load_timeout()`이 실패하면
  호출자는 `driver` 참조조차 못 받아 `quit()`을 부를 수 없다. `crawler/doc_crawler.py`는
  커버리지 0%지만 이 함수만은 selenium 진입점을 갈아끼워 실브라우저 없이 검증한다.

### test_doc_path_safety.py 7(확장)·8 — 경로 규칙과 디스크 부작용

- **8. 읽기 전용 조회가 디렉터리를 만들지 않는다** (BUGS #111). `get_doc_dir()`은
  `os.makedirs()`를 부르는데 `repair_empty_status_capture.py`가 **읽기 전용 전수 스캔**에서
  그것을 물건마다 불렀다. 빈 물건 디렉터리 1,674 + 파일 있는 202 = 정확히 1,876
  (= `auction_item` 행수)이 그 증거였다. **대조군으로 `get_doc_dir()`은 실제로 만든다는
  것까지 확인**해, 두 함수가 정말 다르다는 것을 검사 자신이 증명하게 했다.
- **7(확장)**. 규칙 사본 검사 대상에 `repair_document_status.py`를 추가했다(BUGS #112).
  그 파일은 `/`만 치환하는 옛 규칙을 갖고 있으면서 docstring은 "동일한 규칙"이라
  주장하고 있었다. 추가하자 곧바로 오탐이 났다 — **왜 고쳤는지 보이려고 옛 코드를 주석에
  인용**했는데 검사가 그 인용문을 잡았다. 줄 번호는 유지한 채 주석만 비우도록 고쳤다.

### test_asset_pipeline.py 1-B·12-B·16-C

- **1-B. 형식 판정/크기 읽기 경계값** (36검사). 커버리지 실측에서
  `crawler/image_assets.py`가 72%였고 **webp 크기 읽기(VP8/VP8L/VP8X)는 통째로 0%**였다.
  법원이 선언 MIME으로 거짓말하므로(image/png인데 실제로는 JPEG/GIF) 매직 바이트 판정의
  경계값이 중요하다. 72% -> 86%.
- **12-B. doc_raw가 거짓 성공을 기록하지 않는다** (7검사). 파일 없음 / 0바이트 /
  빈 목록 / 사진은 제외 — **대조군(실물이 있으면 1행 + 크기 일치)을 함께** 둬서 네 검사가
  "항상 0"이어도 통과하는 것을 막는다.
- **16-C. 상세 응답이 N+1이 아니다**. 검색에는 쿼리 수 가드가 있었지만 상세에는 없었다.
  사진 1장과 8장으로 각각 호출해 쿼리 수가 같은지 본다(사진 수가 실제로 다른지도 함께
  검사). **결과 본문은 완전히 같고 쿼리 수만 늘어나므로 결과 기반 검사로는 절대 잡히지
  않는다** — BUGS #104에서 겪은 함정과 같은 계열이다.

### 커버리지 실측 (2026-08-17, coverage.py, 33개 테스트)

```
TOTAL 4,001문장 중 739 미커버  ->  82%
api/v1/*            대부분 95~100%   (item/documents/images/doc_stats/registry 등 100%)
api/http_cache.py   98%
storage/database.py 88%
crawler/image_assets.py 86%   (이 세션에 72%에서 올림)
crawler/*(selenium)  24~45%   실브라우저 없이는 올릴 수 없다
filter/scoring_engine.py, report_generator.py  0%  ← 의도적(docs/CLAUDE.md)
```

**모듈명 grep으로 커버리지를 판정하지 말 것.** Sprint 148이 그렇게 해서
`api/http_cache.py`(실제 98%)와 `api/v1/doc_stats.py`(실제 100%)를 "미커버"로 분류했다.
엔드포인트로 동작을 검증하는 테스트는 모듈 이름을 쓰지 않는다.

## Sprint 187 (2026-08-17) — 문서 파이프라인 전수 추적 (`docs/SPRINT187_DOCUMENT_PIPELINE_AUDIT.md`)

### test_asset_pipeline.py — `test_doc_raw_version_does_not_bump_on_unchanged_content`

BUGS #115. `doc_raw.doc_version`이 `document_version_log`와 달리 내용 변경 여부를
안 보고 재수집마다 무조건 증가했다. 같은 파일 내용으로 두 번째 `mark_queue_done()`을
불러 버전이 그대로임을(시나리오 B), 이어서 내용을 실제로 바꿔 세 번째로 불러 버전이
오름을(시나리오 C) **한 검사 안에서** 확인한다 — 반대 상황을 구분하므로 공허할 수 없다.
기존 `test_mark_queue_done_records_doc_raw`의 "재수집 시 버전 증가" 픽스처는
previous_hash/new_hash 문자열만 다르고 파일 내용은 그대로였다 — 새 판정 기준(파일
내용 자체)에서는 오히려 **버전이 안 올라야 맞는** 픽스처였으므로, 실제로 내용을
바꾸도록 함께 고쳤다.

### test_doc_storage_atomicity.py — `test_looks_like_pdf_rejects_non_pdf_bytes` / `test_collect_spec_refuses_non_pdf_download`

BUGS #116. `wait_for_download()`는 크기만 보고 PDF 내용은 확인하지 않는다.
전자는 `_looks_like_pdf()` 판정 함수를 실제 PDF/HTML 오류 페이지/빈 파일/헤더 없는
바이너리/존재하지 않는 파일 5가지로 단위 고정. 후자는 `wait_for_download()`를
몽키패치해 "다운로드는 끝났다고 보고하되 내용은 HTML"인 상황을 만들어 `collect_spec()`이
**실제 호출 경로**에서 저장을 거부하는 것을(목적지 미생성 + 다운로드 폴더 정리까지),
대조군으로 진짜 PDF는 정상 저장되는 것을 함께 고정한다.

### 운영 환경 실측 — 회귀는 아니지만 배포 전 반드시 재확인할 것

`api_server.py`를 띄우고 실제로 호출한 결과 `/api/v1/search`와 `/api/v1/item/<id>`가
**500**이었다(원인: `auction.db`에 마이그레이션 020 미적용, BUGS #117). 마이그레이션
적용 후 재확인 절차:

```bash
python -m storage.migrations.run_migrations
python test_schema_hygiene.py          # §3 통과 확인
python api_server.py &
curl http://127.0.0.1:8000/api/v1/search?limit=3
curl http://127.0.0.1:8000/api/v1/item/<실제 id>
```

둘 다 200이 나와야 상세페이지 브라우저 E2E를 다시 시도할 수 있다 — 이번 Sprint는
API 계층이 죽어 있어 브라우저 검증까지 가지 못했다(정직하게 SKIP으로 남김).

## Sprint 188 (2026-08-18) — 신규 `test_error_logging.py`

BUGS #118. `api/v1/search.py`의 두 핸들러가 예상치 못한 예외를 로그 없이 `HTTPException`
500으로 바꿔 던지고 있었다(FastAPI는 `HTTPException`에 트레이스백을 안 찍는다). 응답
내용은 그대로라 `test_api_regression.py` 같은 상태코드/본문 검사로는 절대 못 잡는다 —
로그 출력 자체를 캡처해야 보인다.

```
python test_error_logging.py
```

1~2번: `get_connection()`을 예외를 던지는 가짜로 바꿔치기하고 `TestClient`로 실제
HTTP 요청 -> 응답은 불변(500 + 같은 문구), 로그에는 원인이 남는지 확인.
3번: `api/` 전체를 AST로 훑어 "`except Exception`이 `HTTPException`을 새로 던지면서
로그가 없는 지점"을 목록 의존 없이 동적으로 찾는다 — 검사 로직 자체가 결함
있는/정상 샘플을 구분하는지 먼저 확인한 뒤 전수 검사하므로, 새 라우터가 같은 실수를
반복해도 이 검사가 잡는다.
