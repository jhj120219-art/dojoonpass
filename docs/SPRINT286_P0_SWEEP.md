# Sprint 286 — P0 백로그 전수 완주 (2026-09-03)

> 앞 Sprint: `docs/SPRINT285_CASE_DATE_PRODUCER.md`
>
> **실행 환경**: 홈 PC. 실크롤 가능. 세션 중 **05:12 예약 크롤이 실제로 돌았고**,
> Sprint 285 가 복원한 `filed_date` 생산자가 그 운영 실행에서 동작했다
> (오늘 생성된 사건 34건 중 34건에 접수일, 누적 217 -> 371).

## P0 판정

| # | 항목 | 상태 |
|---|---|---|
| P0-1 | Frankenstein | **DONE** |
| P0-2 | Pipeline Contract | **DONE** |
| P0-3 | Timezone / 날짜 | **DONE** |
| P0-4 | Identifier Contract | **DONE** |
| P0-5 | API Contract | **DONE** |
| P0-6 | 관심물건 목록 | **DONE** |
| P0-7 | 검색 카드 즐겨찾기 | **DONE** |

## 이번에 찾은 **실제 결함** 둘

### #289 병합사건 순서가 식별자를 가른다 (부분 해결)

같은 물건이 `auction`/`auction_case`/`auction_item` 에 **두 벌**로 들어가 있었다.
법원이 병합사건 구성요소를 어제와 다른 순서로 내려 줬고, 그 문자열이 식별키의
일부이기 때문이다. 검색 결과에 같은 물건이 두 번 나온다.

지금 1건이지만 **병합사건 638행이 같은 위험**에 있다. 근본 수정(정규화 + 기존 행
재키잉)은 데이터 마이그레이션이라 승인 영역이라, **탐지기 확장 + 상한 고정**까지 했다.

### #290 상세 화면 즐겨찾기의 연타 가드가 await 뒤에 있었다 (해결)

검색 카드는 이미 옳았는데(`FavoriteButton.tsx` 가 이유까지 주석으로 적어 뒀다)
상세 화면만 `setFavBusy(true)` 를 `await getSession()` **뒤에** 두고 있었다.
토큰이 캐시되지 않은 첫 조작에서 연타가 가드를 통과했다. 백엔드는 UNIQUE 로
안전해 데이터는 안 깨졌다 — 고친 것은 중복 요청과 **두 화면의 규칙 불일치**다.

## 유실 작업 추가 복구 (stash@{0})

Sprint 285 가 찾은 `HOME_BACKUP_BEFORE_STORE_SYNC_20260831` 을 **34개 .py 전수**로
다시 훑어, 복원한 수정의 **가드**가 함께 유실돼 있던 것을 발견했다.

```
test_crawl_exit_code.py   run_daily.bat 이 마이그레이션을 크롤보다 먼저 도는가 (#285 전제)
test_refresh_trigger.py   기본 실행이 재수집 대상을 자르지 않는가 (#278 회귀)
api/constants.py          NOINDEX_HEADERS  + api_server.py robots.txt (BUGS #254 부분 완화)
test_public_endpoint_exposure.py  그 색인 차단이 실제로 붙는가
```

수정만 살리고 가드를 안 살리면 같은 유실이 또 일어나도 아무도 울지 않는다.
둘 다 변이로 사망 확인(#278 되돌림 / run_daily.bat 순서 뒤집기).

**마스킹(`mask_tenant_name` 등 4함수)은 일부러 가져오지 않았다** — 대항력 판단
근거를 약화시키는 제품·법무 결정이고 저장소가 스스로 "승인 대기"로 기록해 두었다.
대신 응답 **본문을 한 글자도 바꾸지 않는** 색인 차단만 되살렸다.

## 새로 만든 가드 (전부 변이 검증)

| 검사 | 무엇을 막나 | 변이 |
|---|---|---|
| 프런트 중복 심볼 래칫 (`source-contract`) | 복사된 구현이 번지는 것 | 3/3 사망 |
| 진입점 import 그래프 (`schema_hygiene`) | 배선 안 된 모듈이 조용히 늘어나는 것 | 3/3 사망 |
| 핵심 필드 끝에서 끝까지 (`pipeline_integrity`) | 구간은 멀쩡한데 이음매가 끊기는 것 | 5/5 사망 |
| 병합사건 순서 상한 (`pipeline_integrity`) | 같은 물건이 두 행이 되는 것 | 2/2 사망 |
| API 시각 표기 계약 (`pipeline_integrity`) | 응답이 UTC/오프셋으로 바뀌는 것 | 1/1 사망 |
| non-null 숫자 전수 불변식 (`pipeline_integrity`) | 표본 밖 행의 NULL | 1/1 사망 |
| nullability 대조 (`frontend-contract`) | 선언과 실제 타입이 갈리는 것 | 자기검증 내장 |
| 프런트 호출 경로 실재 (`api_regression`) | 화면이 없는 주소를 부르는 것 | 1/1 사망 |
| 식별자 연속성 (`test_identifier_contract`) | id 가 중간에 다른 물건이 되는 것 | 3/3 사망 |
| 관심물건 lifecycle (`test_favorites_lifecycle`) | 중복/정렬/연타/낙관적 UI | 5/5 사망 |

## 확인했지만 **결함이 아니었던 것**

* `storage/migrate_v4_1.py` 가 어떤 배치에서도 안 불린다 → **죽은 코드가 아니다.**
  fresh clone 1회 부트스트랩이고, 빼면 `run_migrations` 가 *"선행 스키마가 없습니다"*
  로 **소리내어 멈춘다**(실측). 지우면 새 배포를 못 세운다 — 그 사실을 목록에 적었다.
* 프런트 세 화면의 `new Date(x).toLocaleDateString()` → **안전하다.** 서버가 오프셋
  없는 naive ISO 를 주므로 파싱도 표시도 같은 시간대라 문자열의 날짜가 그대로 나온다.
  그 전제를 검사로 고정했다(응답 163개 실측, 위반 0).
* `generatedAt: new Date().toISOString()` → 화면에 **그려지지 않는다**(할당만 있다).
* 첫 판본이 IDOR 를 보고했다 → **내 검사의 봉투 파싱 오류**였다(`success(data)` 를
  `items` 로 읽었다). 제품은 정상. 그 교훈을 헬퍼 주석에 남겼다.

## 게이트

```
Python   통과 68 | 실패 0 | 건너뜀 3 | 판정없음 1     단언 11,835 -> 11,919
프런트   320건 / 319 pass / 0 fail / 1 skip
tsc 0 · eslint 0 · npm run build 성공
QA 잔여  favorites/recent_items/search_presets 전부 0행
핵심 데이터  auction_item 2,834 / auction_case 2,078 / filed_date 371 / images 1,741
```

★ `auction.db` md5 는 이번 세션에 **바뀐다** — 05:12 예약 크롤이 돌았고, API 회귀와
새 검사가 QA 행을 실제 DB 에 썼다 지운다(저장소의 기존 관례). 그래서 md5 대신
**QA 잔여 0행 + 핵심 데이터 무결**을 불변식으로 확인했다.

## 남은 것 (승인 영역)

1. **BUGS #254 임차인 PII** — 공개 상세 API 가 실명/주소/보증금/전입일을 그대로 낸다.
   1,850행까지 늘었다(08-28 519 → 09-03 1,850). stash 에 마스킹 구현이 있다.
   마스킹은 대항력 판단 근거를 약화시키므로 제품·법무 결정.
2. **#289 병합사건 재키잉** — 정규화 + 기존 638행 마이그레이션.
3. `경매개시일` / `청구금액` 수집, 상세페이지발 `배당요구종기` — 컬럼 추가 필요.
4. `rights_summary` 위험도 11컬럼 — 판정 기준이 법적 결정.
5. stash 잔여(#276 N+1, #281 failure_streak_days, BUGS #277~#288 문서) — 사람이 선별.
