# Sprint 291 — migration blocker 최종 판정, nullability sweep 종료, 파서 중복 제거 (2026-09-03)

> **운영 DB 무변경.** 이번 세션의 모든 파괴적 실험은 disposable 경로에서만 했고,
> 관심물건 E2E 는 추가 후 **원복**해 favorites 0행으로 돌려놓았다.
> 승인 A(지역 백필)는 Sprint 290 에서 이미 완료됐고 이번 세션은 그 이후를 잇는다.

---

## 요약

| # | 무엇 | 종류 | 결과 |
|---|---|---|---|
| 1 | migration blocker 를 **fresh bootstrap 으로** 최종 판정 | ★ 실험 | 빈 DB → 3단계 부트스트랩 **전부 rc=0**, 29건 기록. 코드 결함 아님이 확정 |
| 2 | nullability sweep **종료** | ★ 결함(수정) | 남은 2건(`DocumentStatusItem.status`, `TenantRow.source`) 정정. 가드 11→15쌍 |
| 3 | 내가 만든 **파서 중복** 제거 | ★ 부채(수정) | 동일 파서 2벌 → `tests/_ts_interface.mjs` 한 곳. 변이로 양쪽 물림 확인 |
| 4 | 백필 결과 재검증(구 단위 재현율) | 검증 | 5개 구 표본 전부 **주소 기준과 정확히 일치** |
| 5 | 남은 '부천시' 중첩 1건 | 판정 | **오염 아님** — 주소 자체에 구가 없다(구 폐지 2016~2024 접수분) |
| 6 | 관심물건 E2E + 연타 내성 | 검증 | 실브라우저 토글 정상. 3중 방어로 데이터 안전. 결함 아님 |
| 7 | 번들 재측정 | 검증 | 8개 라우트 **바이트 동일** (타입 변경은 컴파일에서 지워진다) |

---

## 1. ★ migration blocker — "코드 결함을 숨기고 있는가" 에 실험으로 답했다

지시는 *"migration 부족이라는 이유만으로 자동 BLOCKED 처리하지 말라"* 였다.
그래서 **세 가지를 각각 실행해서** 확인했다.

### (a) migration 파일이 실제로 존재하는가

```
디스크 29개 / DB 기록 20개
미기록          021~029 아홉 개
기록됐는데 파일 없음   0개      ← 유령 마이그레이션 없음
```

### (b) 빈 DB 에서 **fresh bootstrap** 이 되는가 (disposable 경로)

`docs/CLAUDE.md` 가 적어 둔 3단계를 그대로, 빈 파일에 실행했다.

```
① init_db()          rc=0
② migrate_v4_1       rc=0
③ run_migrations     rc=0
결과: 표 28개 / migration 기록 29건 / 최신 029
      auction_item 면적 컬럼 O · favorite_notes 표 O · auction.filed_date O
운영 DB 최신: 020 (무변경 확인)
```

### (c) 이 DB **사본**에 021~029 를 적용하면 테스트가 통과하는가 (Sprint 289 실험)

```
test_auction_identity  ALL PASS
test_bootstrap         ALL PASS
test_schema_hygiene    migration 관련 실패 전부 소멸
test_pipeline_integrity 데이터 결함만 남음 → 그것을 Sprint 290 백필로 해소
```

### 판정

```
A 실제 production code defect   아니다 — fresh bootstrap 이 완전히 성공한다
B 현재 DB state 문제            그렇다
C migration 미적용 로컬 환경     그렇다  ← 이것이 원인
D test harness 문제             아니다 — 사본에서는 같은 테스트가 통과한다
E historical/dead migration     아니다 — 파일/기록 어긋남 0
F approval-required migration   그렇다 — 운영 DB 적용은 승인 영역이라 하지 않았다
```

**코드 결함을 migration 문제로 숨기지 않았다.** 세 실험이 서로 다른 방향에서 같은 답을 냈다.

### 백필 후 최종 상태

| Test | 결과 | 남은 이유 |
|---|---|---|
| `test_pipeline_integrity` | FAILED (**1**) | `filed_date: auction 컬럼 없음` = migration 028 |
| `test_auction_identity` | ABORT | migration 025 (`building_area`/`land_area`) — 스스로 중단, DB 미변경 |
| `test_bootstrap` | FAILED (4) | fresh 스키마와의 드리프트 = migration 021·023·025·026·028 |
| `test_schema_hygiene` | FAILED (2) | 021~029 미기록 + 021 이 지우는 중복 인덱스 |

**넷 다 migration 하나뿐이다. 데이터 결함 0, 코드 결함 0.**

---

## 2. ★ nullability sweep — 종료

Sprint 289 가 `auction_item` 파생 4개 타입을 고쳤고, 이번에 **나머지 전부**를 훑어 끝냈다.

```
표에 대응되는 타입 (스키마 대조)
  CaseInfo · RightsSummary · AuctionImage · Subscription · Payment ·
  RegistryRequest · RegistryRequestSummary · SearchPreset · RightsSummaryRaw   불일치 0
  ★ DocumentStatusItem.status : string        -> string | null   (수정)
  ★ TenantRow.source          : string        -> string | null   (수정)

표에 없는 타입 (실 응답 대조)
  PlanPrice / PlanOption / PlanCatalog  ← /api/v1/plans 실응답과 정확히 일치
      discount_start·discount_end 만 null 이고 선언도 `string | null`
  import Preview/Commit shapes          ← test_favorite_import.py 가 덮는다(통과 확인)
```

### 런타임 영향까지 확인했다 (타입만 바꾸지 않았다)

```
DocumentStatusItem.status
  API   `_document_entry` 가 `row["status"]` 를 그대로 싣는다(보정 없음)
  DB    TEXT, DEFAULT 'COLLECTING' 이지만 NOT NULL 아님 (실 데이터 NULL 0행)
  UI    `DOC_STATUS_LABEL[doc.status]` 인덱스 접근 -> null 이면 TS2538
  수정   `(doc.status && DOC_STATUS_LABEL[doc.status]) || doc.status || '-'`

TenantRow.source
  UI    `t.source === 'SPEC'` / `=== 'STATUS'` 동등 비교뿐
        -> null 은 **양쪽 어디에도 안 들어가고 조용히 빠진다** = 이미 안전
  수정   선언만 정직화(런타임 변경 0). 실 데이터: SPEC 240 / STATUS 279 / NULL 0
```

### 가드 확장 + 변이

```
스키마 기반 nullability 가드   (파일, 타입, 표) 11쌍 -> **15쌍**
대조 컬럼 수 하한 (>=30)       이름이 어긋나면 0건으로 조용히 통과하지 못하게 한다
변이   TenantRow.source 를 non-null 로 되돌림
       -> [FAIL] TenantRow.source: tenant_rights 는 NULL 허용인데 선언이 `string`
       원복 후 95/95
```

---

## 3. ★ 기술부채 — 내가 만든 파서 중복을 즉시 제거했다

§9(Frankenstein 방지)에 따라 자기 변경을 점검하다가 발견했다.

```
tests/frontend-contract.test.mjs  tsTypes()    응답 값 ↔ 선언 (표본, 살아 있는 API)
tests/source-contract.test.mjs    tsFields()   DB 스키마 ↔ 선언 (전수, 정적)
   -> 두 함수가 **글자 단위로 사실상 동일**했다. 내가 후자를 만들면서 복제한 것이다.
```

둘은 **다른 것을 지키지만 같은 것을 읽는다.** 읽는 규칙이 갈라지면 한쪽만 nullable 을
놓치고 두 검사가 서로를 눈감아 준다 — 이 저장소가 `is_stale_contamination()` 에서
이미 겪은 모양이다(BUGS #224). 그래서 **읽는 규칙을 한 곳으로** 모았다.

```
신설  tests/_ts_interface.mjs   (`_` 접두 = 테스트 글롭에 안 잡히는 헬퍼,
                                 `_search_param_contract.mjs` 와 같은 선례)
두 호출부는 이제 `readTsFields()` 에 위임한다.

변이  파서가 모든 필드를 nullable 로 읽게 만듦
      source-contract    pass 94 / fail 1
      frontend-contract  pass 62 / fail 1     ← **양쪽 다** 붉어진다(둘 다 물려 있다)
      원복 후 329/0
```

---

## 4. 백필 결과 재검증 (승인 A 사후)

```
구 단위 재현율 — 검색 total 과 주소 기준 실제 건수 대조
  경기 고양시 일산동구   9 / 9    일치
  경기 안산시 단원구    19 / 19   일치
  경기 용인시 기흥구     4 / 4    일치
  경남 창원시 성산구     6 / 6    일치
  충북 청주시 서원구     4 / 4    일치

시/도 17개 전 지역 드롭다운의 '접두 중첩' 검사 -> 3쌍(경기 부천시)만 남음
```

### 남은 '부천시' 중첩은 **오염이 아니다**

경기 부천시 계열 36행을 전수로 재계산 대조했다 — **36행 전부 일치**.
플레인 `'부천시'` 5행은 주소 자체에 구가 없다.

```
"경기도 부천시 경인로193번길 8-9 …"      -> 재계산도 '부천시'
"경기도 부천시 고리울로28번길 27-14 …"    -> 재계산도 '부천시'
vs
"경기도 부천시 소사구 지봉로 144-1 …"     -> 재계산 '부천시 소사구'
```

부천시는 2016 년 구를 폐지했다가 2024 년에 되살렸다. 그 사이 접수분 주소에는 구가
없고, 정규화기는 **원천을 그대로** 반영한다. 사용자 영향도 정상이다 —
`'부천시'` 를 고르면 LIKE 로 36건 전부, `'부천시 원미구'` 를 고르면 주소에 그 구가
적힌 건만 나온다. 구를 추정해 채우려면 외부 주소 DB 가 필요하다(새 의존성 + 정책 = 승인 영역).

---

## 5. E2E — 관심물건 토글 (실브라우저, 상태 원복)

```
시작   favorites 0행
🤍 클릭 -> ❤️ (aria-label '즐겨찾기 추가' -> '즐겨찾기 해제'), DB 1행
해제   -> 🤍, DB 0행                                   ← 원복 확인

연타 내성
  같은 tick 3연타   요청 3회 / DB **1행** / 오류 표시 없음 / 최종 상태 정상
  현실적 60ms 더블클릭  요청 2회(POST+DELETE) / 정상 토글 / 최종 상태 정상
```

**결함이 아니다.** 같은 tick 연타는 React 상태가 아직 리렌더되지 않아 클로저의
`favBusy` 가 낡은 값이라 통과하는데, 그 경우에도
`UNIQUE(user_id,item_id)` + `FAVORITE_ALREADY_EXISTS` 에러코드 + UI 의 "이미 원하는
상태면 성공으로 취급" 3중 방어가 데이터와 화면을 지킨다. 사람이 낼 수 있는 간격
(60ms)에서는 리렌더가 끝나 가드가 정상 동작한다.
사람이 도달할 수 없는 경우를 위해 P0 로 굳힌 경로를 고치지 않는다.

---

## 6. 성능 / 보안 / 접근성 재확인

```
번들   clean rebuild 후 8개 라우트 **바이트 동일**
       /favorites 200.4K · /login 195.7K · /_not-found 191.3K · shared 181.2K
       (타입 변경은 컴파일에서 지워지고 가드는 테스트에만 있다)

DB     regions 쿼리 계획 COVERING INDEX 유지 / 중앙값 0.054ms (백필 전 0.053ms)
       구 단위 검색도 계획 변화 없음

보안   사용자 스코프 6개 엔드포인트 비인증 401 / 위조 토큰 401
       공개(선언된 정책): plans · search · item · images · documents
무결성  integrity ok · FK 위반 0 · 고아 0 (8개 관계) · 중복 식별자 0
```

---

## 7. 게이트

```
tsc 0 · eslint 0 · npm run build 성공
node    329건 / 325 pass / 0 fail / 4 skip
python  통과 64 | 실패 4 | 건너뜀 3 | 판정없음 1 (단언 11,892)
        실패 4 = migration 021~029 뿐 (§1 참조)
test_api_regression · test_subscription_policy · test_favorite_import ·
test_rights_data_load · test_normalizer(82) · test_search(245)   전부 통과

운영 DB  favorites 0행 원복 · 지역 오염 0 · migration 020 유지
백업     auction.db.backup_before_region_backfill_20260903_141457 보관
```

---

## 8. 남은 승인 항목 (변화 없음)

```
~~A~~  지역 오염 백필                 ✅ Sprint 290 완료
B     migration 021~029              fresh bootstrap·사본 적용 **둘 다 성공 확인**.
                                     적용하면 남은 실패 4건이 전부 해소된다
C     load_spec_data.py 운영 적재     사본 실증 case_type 0→192 / demand_deadline 0→187
D     서버측 썸네일 축소(Pillow)      SPRINT144 가 이미 SKIP 으로 기록
E     권리분석 위험등급 엔진           법률 판단
F     날짜 표기 통일                  UX 결정
G     filed_date                     운영 크롤 1회 + migration 028 (EXTERNAL)
H     부천시 구 보정                  외부 주소 DB 필요 (새 의존성 + 정책)
```
