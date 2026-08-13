# Sprint 100 — 환경변수 / 성능 / 인덱스 Audit

> 앞 Sprint: `docs/SPRINT98_FALSE_SUCCESS_AUDIT.md`, `docs/SPRINT99_RELEASE_READINESS_AUDIT.md`
>
> **별도 파일 이유**: `docs/BUGS.md` 등이 다른 세션 편집 대상이라 충돌을 피했다.

Sprint 99의 fresh-clone 감사를 이어, 아직 측정된 적 없는 두 영역을 실측했다:
**환경변수 부재 시 동작**과 **성능/인덱스**.

---

## #100-1 환경변수 없이도 빌드가 성공한다 (문서화, 코드 변경 없음)

**심각도** 낮음 (런타임은 시끄럽게 실패한다)

`.env*`는 `.gitignore` 대상(`.gitignore:34`)이라 **새 clone에는 환경변수 파일이 하나도 없다.**
그 상태를 실제로 재현해 측정했다.

### 실측

| 단계 | 결과 |
|---|---|
| `npm run build` (환경변수 전무) | **rc=0 성공. 경고 한 줄 없음** |
| 그 빌드로 `npm run start` 후 `GET /` | **500 Internal Server Error** |
| 같은 빌드로 `GET /mypage` | **500 Internal Server Error** |

원인은 `src/proxy.ts`가 모든 요청에서 `createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, ...)`를
호출하기 때문이다. `!`는 **TypeScript 단언일 뿐 런타임에는 아무 일도 하지 않으므로**
`undefined`가 그대로 넘어가 예외가 난다.

### 판단 — 결함이 아니다 (fail closed)

런타임이 **모든 페이지에서 500**을 내므로 조용한 실패가 아니다. 사용자가 잘못된 데이터를
보거나 기능이 반쯤 동작하는 상태가 아니라, 배포 즉시 눈에 띈다. **fail closed가 맞다.**

남는 간극은 하나뿐이다: **빌드 단계가 신호를 주지 않는다.** `npm run build`만 돌리는 CI는
초록불인데 산출물은 모든 요청에 500을 낸다.

### 왜 고치지 않았나

빌드를 실패시키는 검사를 넣으면 **배포/개발 흐름이 바뀐다**(환경변수 없이 빌드하던 경우가
막힌다). 런타임이 이미 즉시·전면적으로 실패해 놓치기 어려운 상태라 추가 방어의 한계 이득이
작다. 배포 파이프라인 정책에 해당한다고 보고 **SKIP**하되, 사실은 여기 남긴다.

> 참고: `NEXT_PUBLIC_API_BASE_URL`은 없으면 `'http://localhost:8000'`으로 폴백한다
> (`src/lib/api.ts:5`). 현재 `.env.local` 값이 정확히 그 값이라 개발 환경에서는 차이가 없다.
> 다만 **운영 배포에서 이 변수를 빠뜨리면 브라우저가 사용자 자신의 PC를 호출하게 된다.**
> 위 500과 달리 이건 "서버 장애"처럼 보여 원인 파악이 늦어질 수 있다 — 배포 체크리스트 항목.

---

## #100-2 성능 실측 — 현재 규모에 병목 없음 (최적화하지 않음)

실제 DB(`auction_item` 1,876행 / `document_status` 5,628행 / DB 5.0MB)에 대고
FastAPI TestClient로 25회씩 측정했다.

| 엔드포인트 | p50 | p95 |
|---|---|---|
| `GET /api/v1/search` (기본) | 2.6ms | 2.8ms |
| `GET /api/v1/search` (지역+정렬) | 2.9ms | 3.1ms |
| `GET /api/v1/search` (키워드) | 2.6ms | 2.8ms |
| `GET /api/v1/search` (깊은 페이지 page=50) | 2.4ms | 2.7ms |
| `GET /api/v1/search` (size=100) | 2.6ms | 3.0ms |
| `GET /api/v1/item/{id}` (상세) | 2.3ms | 2.5ms |
| `GET /api/v1/document-stats` | 3.0ms | 3.1ms |

**전부 p95 3.1ms 이하.** 깊은 페이지네이션(offset 980)도 느려지지 않는다.
**병목이 없으므로 최적화하지 않는다** — 측정값만 남기고 다음으로 넘어간다.

---

## #100-3 완전히 겹치는 인덱스 4쌍 (계측 + 증가 차단, 제거는 하지 않음)

같은 컬럼 조합에 인덱스가 둘 이상이면 **읽기 이득은 0이고** 쓰기 비용과 파일 크기만 는다.

### 실측 — 완전 중복 4쌍 / 접두 포함 7쌍

| 테이블 | 컬럼 | 중복된 두 인덱스 |
|---|---|---|
| `auction_item` | `auction_date` | `idx_ai_auction_date` == `idx_auction_item_auction_date` |
| `auction_item` | `case_no` | `idx_ai_case_no` == `idx_auction_item_case_no` |
| `auction_item` | `minimum_bid_price` | `idx_auction_item_minimum_bid_price` == `idx_minimum_bid_price` |
| `rights_summary` | `item_id` | `idx_rights_summary_item_id` == `idx_rs_item_id` |

### 원인

이름 규칙이 다른 두 계통(`idx_ai_*` vs `idx_auction_item_*`)이 **서로를 모른 채 같은 인덱스를
각각 만들었다** — `storage/migrate_v4_1.py`와 마이그레이션 008/009. Sprint 99의 부트스트랩
문제와 같은 뿌리다: **스키마를 만드는 곳이 두 군데인데 서로를 모른다.**

### 왜 지우지 않았나

위 #100-2대로 현재 규모에서 병목이 없다. 쓰기도 하루 1회 배치라 중복 인덱스 유지 비용이
무시할 수준이고, 인덱스 DROP은 스키마 변경이라 **이득 없이 위험만 만든다.**
측정값을 남기고 **증가만 막는다**.

접두 포함(prefix, 7쌍)은 대상에서 제외했다 — SQLite가 더 작은 인덱스를 고르는 편이 유리한
경우가 있어 의도적일 수 있다. **완전 중복은 어떤 경우에도 의도일 수 없다.**

### 신규 테스트

`test_schema_hygiene.py`에 완전 중복 인덱스 증가 차단을 추가했다(알려진 4쌍은 상수로 고정,
새로 생기면 즉시 실패, 정리되면 상수에서 빼라고 안내).
**변이 검증**: 상수에서 한 쌍을 빼면 `['rights_summary(item_id)']`로 잡힌다.

---

## #100-4 Dead code / 라우트 커버리지 감사 — 결함 없음 (기록만)

API 라우트를 **OpenAPI 스키마로 전수 열거**해(41개) 프런트 호출부와 테스트 소스에 대조했다.

> 주의: `app.routes`를 훑으면 **하위 라우트가 보이지 않는다.** 이 FastAPI 버전은
> `include_router`를 `_IncludedRouter`로 감싸 두어 최상위에 2개만 노출된다(실측).
> 전수 목록은 `app.openapi()`가 유일하게 정확하다 — 앞으로 라우트를 세는 코드는 이걸 쓸 것.

| 항목 | 결과 |
|---|---|
| 정의된 라우트 | **41개** |
| 프런트도 테스트도 호출하지 않는 라우트(dead endpoint 후보) | **0개** |
| 테스트가 한 번도 건드리지 않는 라우트 | **0개** |
| 프런트가 호출하지 않는 라우트 | 21개 — **전부 정상** (admin 운영용 / PG webhook 수신 / `/stats` 모니터링) |

**죽은 엔드포인트가 없고, 라우트 표면 전체가 테스트로 덮여 있다.** 손댈 것이 없다.

### TODO/FIXME/HACK

`api/ crawler/ storage/ src/ normalizer/ validator/ filter/ intent/ models/ config/` 전수 검색:
**3건뿐**이고 전부 `src/app/search/SearchForm.tsx`의 `TODO(API 미지원)`이다.
그리고 그 3건은 `tests/source-contract.test.mjs`가 **표시가 남아 있는지 검사로 강제**하고 있다.
방치된 TODO가 아니라 관리되는 항목이다 — 손댈 것 없음.

---

## 이번 Sprint에서 **내가 만든** 운영 사고와 그 교훈

정직하게 남긴다.

환경변수 실험을 위해 `npm run start`를 파이썬 `subprocess.Popen`으로 띄우고
`terminate()`로 정리했는데, **npm이 띄운 node 자식 프로세스가 살아남았다.**
그 자식은 **환경변수 없이 빌드한 산출물**을 메모리에 들고 계속 3000 포트를 점유했고,
그 결과 다음 전체 회귀에서 `test_beta_journey.py`가 실패했다:

```
[FAIL] 비로그인 상세는 307로 막힌다: 500 (expected 307)
```

제품 결함이 아니라 **내가 남긴 유령 서버** 때문이었다. 포트 기준으로 정리한 뒤 정상 통과.

교훈 두 가지:

1. `npm run start`는 **부모를 죽여도 자식이 남는다.** 포트 기준(`Get-NetTCPConnection` →
   `Stop-Process`)으로 확인·정리해야 한다.
2. 이 상황에서 `test_beta_journey.py`의 동작은 **정확했다** — 서버가 없으면 `[SKIPPED]`,
   서버가 있는데 응답이 틀리면 `[FAIL]`. "서버 없음"과 "서버가 틀린 답을 함"을 구분한다.
   Sprint 98에서 얻은 "취소됨을 PASS로 간주하지 않는다"가 반대 방향으로도 지켜지고 있었다.

---

## #100-5 ★ `npm run build`가 OneDrive 때문에 실패하고 있었다 (환경, 해소함)

**심각도** 중간 (빌드 불가 — 다만 제품 결함이 아니라 개발 환경)

### 증상

```
Error: EPERM: operation not permitted, unlink
  'C:\...\dojoonpass\.next\server\app\favorites.segments'
build exit = 1   (3회 연속 재현, 매번 같은 경로)
```

### 원인

문제의 `favorites.segments`는 **파일이 아니라 디렉터리**이고 속성이 이랬다:

```
Attributes: ReadOnly, Directory, Archive, ReparsePoint
```

`ReparsePoint` + `ReadOnly` = **OneDrive Files On-Demand가 `.next` 일부를 클라우드
자리표시자로 탈수(dehydrate)시킨 상태**다. 그러면 Next가 이전 빌드 산출물을 지우지 못해
`unlink`가 EPERM으로 실패한다. 최상위 속성만 풀어도 하위 `favorites`가 같은 상태라 안 된다.

이 저장소가 OneDrive 동기화 폴더 안에 있어 생기는 간섭이고, **이미 알려진 유형**이다 —
`test_checkpoint_atomicity.py`가 같은 이유로 체크포인트 테스트를 시스템 임시 디렉터리로
옮겼고, Sprint 98에서 `documents/qa-atomic-*` 정리가 OneDrive READONLY 때문에
실패하던 것도 같은 뿌리였다.

### 조치

`.next` 하위 ReadOnly 속성을 재귀적으로 해제하고 `.next`를 통째로 지운 뒤 재빌드했다.
`.next`는 `.gitignore` 대상이고 **전부 재생성 가능한 산출물**이라 지워도 잃는 것이 없다.
재빌드 결과 **exit 0**, 연속 2회 안정. 라우트 9개 정상 생성.

### 권장 (환경 설정 — 코드 아님)

`.next`, `node_modules`, `logs`, `documents`를 OneDrive 동기화 대상에서 제외하는 것이 좋다.
빌드 산출물과 수집 문서는 동기화할 이유가 없고, 위 간섭이 **빌드·테스트·문서 정리 세 곳에서**
이미 실제로 사고를 냈다. (환경 설정 변경이라 이 세션에서 하지 않았다.)

---

## ★ 내 측정 방법의 오류 정정

이번 Sprint에서 **내가 이전에 보고한 "Build PASS"가 틀렸다**는 것을 발견해 정정한다.

```bash
npm run build 2>&1 | tail -3; echo "build=$?"     # <- $?는 npm이 아니라 tail의 종료코드
```

파이프 뒤의 `$?`는 **마지막 명령(`tail`)의 종료코드**다. `tail`은 늘 0이므로
빌드가 exit 1로 실패해도 "0"이 찍혔다. 파이프 없이 다시 측정한 결과:

| 검사 | 잘못된 측정 | **실제 (재측정)** |
|---|---|---|
| `npm run build` | "0" | **1 (실패)** -> `.next` 정리 후 **0** |
| `npx tsc --noEmit` | "0" | **0 (맞음, 출력 0줄)** |
| `npm run lint` | "0" | **0 (맞음, error/warning 0건)** |

TypeCheck/Lint는 결과적으로 맞았지만 **측정 방법이 틀렸으므로 신뢰할 근거가 없었다.**
파이썬 스위트는 `subprocess.returncode`를 직접 읽고, 프런트 테스트는 러너가 출력하는
`pass/fail` 수를 파싱하므로 이 오류의 영향을 받지 않는다 — 그 결과들은 유효하다.

교훈: **종료코드는 파이프를 통과하지 못한다.** 로그는 파일로 받고 종료코드는 따로 읽는다.

---

## 검증 (서버 2개를 **실제로 기동**하고 측정)

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31/31 파일 통과** |
| 프런트 테스트 | **107/107 통과** (서버 의존 48개가 실제로 실행됨, 취소 0) |
| `test_beta_journey.py` 프런트 게이트 | **SKIP이 아니라 실제 PASS** (307 + 복귀 URL 보존) |
| TypeCheck (`npx tsc --noEmit`) | **exit 0** (출력 0줄) — 파이프 없이 재측정 |
| Lint (`npm run lint`) | **exit 0** (error/warning 0건) — 파이프 없이 재측정 |
| Build (`npm run build`) | **exit 0**, 연속 2회 (`.next` 정리 후) — 파이프 없이 재측정 |
| 서버 정리 | 3000/8000 포트 모두 해제 확인 |

---

## SKIP 및 이유

| 항목 | 이유 |
|---|---|
| 빌드 시점 환경변수 필수 검사 | 배포 파이프라인 정책 변경. 런타임이 이미 500으로 즉시 실패. |
| 중복 인덱스 4쌍 DROP | 병목 없음(p95 ≤ 3.1ms). 스키마 변경은 이득 없이 위험만. |
| 접두 포함 인덱스 7쌍 | 의도적일 수 있음(SQLite 플래너 선택). |
| `NEXT_PUBLIC_API_BASE_URL` 폴백 제거 | 개발 편의와 상충. 배포 체크리스트 항목으로 남김. |

## 남은 Backlog

- 커밋된 DB 백업 9개(36.9MB) 인덱스에서 제거 — commit 필요 (Sprint 99)
- 부트스트랩 3단계를 README/docs에 반영 — docs 동시 편집 중 (Sprint 99)
- `mypage` 등기부 다운로드 버튼 — UX 결정 (Sprint 98)
- 스키마 생성 경로 일원화(`init_db` + `migrate_v4_1` 통합) — 운영 절차 변경 (Sprint 99)
