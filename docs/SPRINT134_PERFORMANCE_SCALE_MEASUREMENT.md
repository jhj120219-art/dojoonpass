# Sprint 134 ― Performance/N+1 전수 실측: 새 결함 없음, TEMP B-TREE 스케일 리스크 1건 문서화 (2026-08-16)

> 앞 Sprint: `docs/SPRINT133_CONSOLE_ENCODING_WRAPPER_GAP.md`
>
> **별도 파일 이유**: Sprint 100~133과 같다.

`/goal`이 지정한 순서(Performance/N+1 → Technical Debt → Release Audit)를 따르되,
시작 전 `docs/CURRENT_STATE.md`의 기존 성능 측정("핫패스 성능... 전부 p95 ≤
3.4ms... 최적화하지 않았다", 2,156건 기준 갱신됨)부터 대조했다. 이번 회차는 그
표에 없던 영역(Admin 목록, 크롤러 upsert)까지 넓혀 **실측**했다.

## 1. API 핫패스 재측정 ― 기존 결론 유지, 새로 발견된 것 1건(성능 결함 아님)

`TestClient`로 직접 타이밍(중앙값/최댓값, 10회):

| 경로 | 중앙값 | 최댓값 |
|---|---|---|
| `/api/v1/search?size=20` | 2.46ms | 20.40ms(콜드 스타트 1회) |
| `/api/v1/search?size=20&offset=2000`(깊은 페이지) | 2.52ms | 2.92ms |
| `/api/v1/search?size=20&offset=2100`(사실상 마지막 페이지) | 2.43ms | 2.78ms |
| `/api/v1/search?...&sort_by=minimum_bid_price&offset=2000` | 2.67ms | 4.59ms |
| `/api/v1/search?...&sido=서울&sigungu=강남구` | 2.26ms | 2.33ms |
| `/api/v1/document-stats` | 2.73ms | 3.39ms |

전부 기존 기준(p95 ≤ 3.4ms)과 일치. **새 결함 없음.**

### 발견(결함 아님, 스케일 리스크로만 기록) ― 기본 정렬의 tie-break가 TEMP B-TREE를 쓴다

`EXPLAIN QUERY PLAN`으로 실측:

```
SELECT * FROM auction_item ORDER BY auction_date DESC, fail_count DESC, id DESC
LIMIT 20 OFFSET 2000

  SCAN auction_item USING INDEX idx_auction_item_default_sort
  USE TEMP B-TREE FOR LAST TERM OF ORDER BY
```

`idx_auction_item_default_sort`는 `(auction_date DESC, fail_count DESC)` 2개
컬럼만 커버한다. Sprint 123이 추가한 `id DESC` tie-break(정렬 안정성 보장,
`docs/SPRINT123_SEARCH_SORT_TIEBREAK.md`)는 이 인덱스 밖이라 SQLite가 동률 그룹
안에서만 임시 B-tree로 다시 정렬한다. **Sprint 123도 이 SCAN 라인을 인용했지만
TEMP B-TREE 언급은 없었다** — 정확성(순서 안정성)만 확인했지 이 비용까지는
안 봤다는 뜻이라 새로 보는 것이 맞다(중복 아님).

**실측 영향 — 현재 규모(2,156건)에서 없음.** 위 표의 기본 정렬 깊은 페이지가
2.43~2.92ms로 다른 쿼리와 동일하다 — 동률 그룹 크기가 작아(같은 auction_date +
같은 fail_count인 물건 수가 적어) 임시 B-tree 비용이 측정 잡음 이하다.

**스케일 리스크**: 데이터가 크게 늘어 동률 그룹이 커지면(예: 특정 매각기일에
수백~수천 건이 몰리는 시즌) 비용이 커질 수 있다. 잠재적 해결책은 인덱스를
`(auction_date DESC, fail_count DESC, id DESC)` 3컬럼으로 확장하는 것이다 —
그러면 정렬 전체가 인덱스만으로 끝나 TEMP B-TREE가 사라진다. **이것은 스키마
변경(새 인덱스)이라 `docs/CLAUDE.md` 원칙상 승인 영역**이라 지금 만들지 않는다
(아래 SKIP 표에 실행 가능한 SQL까지 남긴다).

## 2. Admin 목록 엔드포인트 ― 처음 실측(기존 핫패스 표에 없던 영역)

`admin_list_subscriptions()`가 조회 전에 `sync_expired_status(conn, commit=True)`를
부른다(만료 lazy sync, 배치 없이 조회 시점에 갱신). 이 함수는 **페이지네이션과
무관하게 ACTIVE/GRACE_PERIOD 전체를 훑는 SELECT + 필요한 행마다 개별 UPDATE**
루프다 — N+1 모양이 맞다. 실제 위험이 있는지 합성 데이터로 스케일 실측했다
(스크래치 복사본에만 실행, 운영 DB 무변경, 끝나고 즉시 파일 삭제 확인).

| 시나리오 | 건수 | 결과 |
|---|---|---|
| 전부 미래 만료(UPDATE 없음, SELECT+파이썬 루프 순수 비용) | 10,000건 | **8.84ms** |
| 전부 유예기간 경과(전수 UPDATE, 최악 케이스) | 10,000건 | **51.66ms** |

현재 실제 운영 DB의 `subscriptions` 행 수는 0건(테스트 스위트가 자체 정리함 —
QA 데이터는 매 실행 후 회수됨, 실측 확인). **결론: 1만 건 규모에서도 100ms
미만이라 이 서비스의 현실적 사용자 규모(법원경매 구독 서비스, 대량 결제
서비스가 아님)에서는 문제가 되지 않는다.** N+1 모양이지만 배치 크론 없이
lazy sync를 하기 위한 의도된 설계(`sync_expired_status()` 자체 docstring이
이유를 설명한다)이고, 실측상 고칠 필요가 없다 — "N+1이니까 무조건 고친다"가
아니라 실측이 근거다.

## 3. 크롤러 upsert 경로 ― 처음 실측

`storage/database.py:upsert_batch()`(크롤러의 유일한 쓰기 경로,
`docs/backend.md`가 "레거시 auction 테이블 컬럼 구성은 절대 변경 금지"로 지정한
그 테이블)도 row마다 `SELECT ... WHERE court_code=? AND case_no=? AND item_no=?`
후 INSERT/UPDATE를 결정하는 구조라 N+1 모양이다. 스크래치 복사본에 3,000건
합성 삽입(현재 실 데이터 2,156건보다 많은, 전국 법원경매 하루 처리량으로도
넉넉한 규모)으로 실측:

| 시나리오 | 결과 |
|---|---|
| 3,000건 신규 INSERT | **23.48ms** |
| 3,000건 재실행(전부 UPDATE 경로) | **25.23ms** |

**결론: 문제 없음.** 하루 한 번 도는 배치에 25ms는 무의미한 비용이다. 이 함수를
`INSERT ... ON CONFLICT DO UPDATE`로 바꿔 쿼리 수를 절반으로 줄이는 것은
이론적으로 가능하지만, 측정상 이득이 없고 "do-not-modify" 표시가 있는 크롤러
핵심 쓰기 경로를 건드리는 위험만 남는다 — 최소 변경 원칙에 따라 손대지 않는다.

## 4. 동일 패턴 전수 검색 결과 요약

`/goal`이 요구한 목록(목록 조회/검색/상세/문서통계/관리자/결제내역/구독조회/
등기부/registry credit/crawler/document worker/queue/filesystem/frontend API
호출/Server Action)을 실측하거나(위 §1~3) 이전 세션에서 이미 실측된 것을
재확인했다:

| 영역 | 상태 |
|---|---|
| 검색/상세/즐겨찾기/최근조회/구독/결제(사용자용) | 기존 측정 유지, 재확인 완료(§1) |
| 문서통계(`document-stats`) | 재확인 완료(§1), 단일 GROUP BY 쿼리(Sprint 미상이 이미 6회 COUNT를 1회로 통합) |
| Admin 구독 목록(lazy sync) | **신규 실측**(§2), N+1 모양이나 스케일 안전 확인 |
| 크롤러 upsert | **신규 실측**(§3), N+1 모양이나 스케일 안전 확인 |
| Queue/Worker(`claim_next_queue_item`) | 이전 세션(Sprint 129 이전)에 이미 원자적 UPDATE로 확인, 이번 세션에 재확인함(고쳐진 것 없음, N+1 아님) |
| Registry credit(append-only 원장) | 이전 세션에 이미 `SUM(amount)` 집계 방식으로 N+1 아님 확인 |
| Frontend 중복 API 호출 | `properties/[id]/page.tsx` 등 handleSubscribe/handlePayOverage가 이미 busy 가드로 중복 호출 자체를 차단(이전 세션 확인) — 성능이 아니라 정합성 목적이지만 결과적으로 중복 호출도 막는다 |

새로 걸린 것은 §1의 TEMP B-TREE 스케일 리스크 문서화 1건뿐이며, 이는 코드
결함이 아니라 **미래 데이터 증가 시 검토할 인덱스 확장 후보**로 남긴다.

## Before/After 실측 검증

이번 Sprint는 코드를 변경하지 않았으므로(측정과 문서화만) Before/After 비교
대상이 없다 — `/goal`의 "성능 개선은 Before/After로 검증한다"는 원칙은 §1~3에서
"개선하지 않기로 한 결정" 자체를 실측으로 뒷받침하는 데 적용했다(고칠 필요가
없다는 것도 실측으로 증명해야 한다는 뜻으로 해석).

## 검증

| 항목 | 결과 |
|---|---|
| API 핫패스 재측정 | 기존 기준(p95 ≤ 3.4ms) 유지 확인 |
| Admin 구독 동기화 스케일 테스트 | 10,000건 fine, 51.66ms(최악 케이스) — 스크래치 DB만 사용, 운영 DB 미변경 |
| 크롤러 upsert 스케일 테스트 | 3,000건 fine, 25.23ms — 스크래치 DB만 사용, 삭제 확인 |
| 코드 변경 | 0건(측정/문서화만) |

## 수정 파일

```
docs/SPRINT134_PERFORMANCE_SCALE_MEASUREMENT.md   신규 (본 문서)
```

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| `idx_auction_item_default_sort`를 `(auction_date DESC, fail_count DESC, id DESC)` 3컬럼으로 확장 | 스키마 변경(인덱스 추가) — `docs/CLAUDE.md` 원칙상 승인 영역. 실행 가능한 SQL: `CREATE INDEX idx_auction_item_default_sort_v2 ON auction_item(auction_date DESC, fail_count DESC, id DESC)` 후 기존 인덱스 DROP(또는 새 번호 마이그레이션 파일로 추가) — 지금은 스케일 리스크일 뿐 현재 규모에서 효과가 측정되지 않아 승인 후에도 급하지 않음 |
| `upsert_batch()`를 `INSERT ... ON CONFLICT DO UPDATE`로 재작성 | 크롤러 핵심 쓰기 경로("do-not-modify" 표시) 변경 — 측정상 이득 없어 시도 자체를 보류(승인 여부 이전에 가치가 없다고 판단) |
| Sprint 105~133 SKIP 표의 나머지 승인 대기 항목들 | 누적, 미해소 |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112, 4일 남음).
- 위 SKIP 표 항목들
- 다음 Audit 영역: Technical Debt(TODO/FIXME/HACK/Dead Code 2차), Architecture,
  Failure Recovery, Test Gap, Documentation Drift, Release Audit (계속 진행)
