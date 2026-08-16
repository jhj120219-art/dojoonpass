# Sprint 130 ― `migrate_execute.py`(일일 배치)의 N+1 쿼리 제거 (2026-08-15)

> 앞 Sprint: `docs/SPRINT129_OVERAGE_PAYMENT_LOCK_ORDER.md`
>
> **별도 파일 이유**: Sprint 100~129와 같다.

`/goal`의 Performance/N+1 Audit 우선순위를 따라 진행했다. `docs/CURRENT_STATE.md`의
기존 "핫패스 성능" 측정(line 2661)은 `api/v1/*` 엔드포인트만 다뤘고(전부 N+1 없음,
p95 ≤ 3.4ms 확인됨) `migrate_execute.py`(일일 배치, `mvp_scraper.py` 다음 단계)는
그 표에 없었다 — grep으로 확인, 이 스크립트의 쿼리 패턴은 이 세션 이전에 감사된
적이 없다.

## 발견

`migrate_execute.py:execute()`가 `SELECT * FROM auction`으로 전체 원본을 한 번에
읽은 뒤(현재 실측 2,156건), 그 각 row마다 개별 SELECT를 반복하는 3곳:

```
§2 auction_item 루프(78번째 줄대): row마다 case_id를 얻기 위해
   SELECT id FROM auction_case WHERE court_code=? AND case_no=?  (N회)

§3 document_status 루프: row마다 item_id를 얻기 위해
   SELECT ai.id FROM auction_item ai JOIN auction_case ac ...     (N회, §2가 이미
   구한 것과 동일한 신원을 다시 JOIN으로 재조회)
```

인덱스가 있어 각 조회 자체는 빠르다(현재 2,156건 규모에서 체감 지연 없음 — 실측
아래 참고). 문제는 **row 수에 선형으로 비례해 늘어나는 구조**라는 것이다.
`auction_case`는 지난 사건까지 계속 누적되는 테이블이라 절대 줄지 않고, `auction`
원본도 전국 법원경매 크롤 대상이 늘수록 커질 수 있다 — 지금 2,156건에서 무해한
패턴이 데이터가 늘면 그대로 배치 시간에 반영된다. 배치는 매일 새벽 자동 실행되고
결과를 기다리는 사용자는 없지만(`docs/CLAUDE.md`의 `run_daily.bat` 파이프라인),
무한정 커지도록 방치할 이유는 없다.

## 고친 것

`migrate_execute.py`:

1. §1 `auction_case` UPSERT 직후, 그 UPSERT에 쓴 `case_map`의 키 집합
   `(court_code, case_no)`을 SQLite의 row-value `IN`(3.15+, 이 환경 3.50.4)으로
   **한 번에** 읽어 `case_id_by_key` 딕셔너리에 캐시한다. `auction_case` 테이블
   전체가 아니라 지금 필요한 키만 `WHERE (court_code, case_no) IN (...)`로 좁혔다
   — 과거 누적분까지 매일 전부 긁지 않기 위해서다.
2. §2 `auction_item` 루프의 개별 `SELECT ... WHERE court_code=? AND case_no=?`를
   위 딕셔너리 조회로 바꿨다. 같은 루프에서 각 row가 갱신/삽입된 `auction_item.id`를
   `item_id_by_key[(case_id, item_no)]`에 함께 기록한다(UPDATE 분기는
   `existing["id"]`, INSERT 분기는 `cursor.lastrowid`).
3. §3 `document_status` 루프의 JOIN 재조회를, 바로 위 §2가 이미 구해 둔
   `case_id_by_key` + `item_id_by_key` 딕셔너리 조회로 바꿨다 — 완전히 같은 신원
   결정 로직(법원+사건→case_id, case_id+물건번호→item_id)을 그대로 유지하되 DB
   왕복만 없앴다.

식별 로직/조건/우선순위는 전혀 바꾸지 않았다 — 개별 SELECT를 딕셔너리 조회로
바꾼 것뿐이다(로직 변경 없음, "최소 변경 원칙" 그대로 적용).

## 실측 ― 쿼리 수 감소

현재 데이터(auction 2,156건, 고유 (court_code,case_no) 1,574건) 기준:

```
[수정 전] §2: 2,156회 개별 SELECT + §3: 2,156회 JOIN SELECT = 4,312회
[수정 후] §2/§3 공용: WHERE IN 1회(1,574쌍을 한 번에) = 1회
감소량: 4,312회 -> 1회 (해당 구간 쿼리 수 99.98% 감소)
```

배치 전체 실행 결과는 동일하다(아래 검증) — 쿼리 수만 줄었다.

## 동일 패턴 전수 검색

레포 전체에서 `for ... in ...:` 루프 안에 `conn.execute`가 바로 뒤따르는 패턴을
`grep`(멀티라인)으로 찾았다 — `api/`, `crawler/`, 루트 스크립트 전체 포함.
`migrate_execute.py`의 이 3곳 외에는 없었다(API 라우터들의 `for r in rows` 형태는
전부 **이미 fetchall()된 결과를 파이썬에서 매핑**하는 것뿐, 추가 쿼리 없음 —
`api/v1/favorites.py`, `recent_items.py`, `search.py` 등 확인). API 핫패스는
이미 Sprint 15/기존 측정에서 N+1 없음이 확인돼 있었고(위 인용), 이번 대상은
배치 스크립트뿐이었다.

## 회귀 테스트

기존 `test_auction_identity.py`(cross-court 안전성, exit code 계약, dryrun==execute
일치)와 `test_pipeline_integrity.py`가 이미 `migrate_execute.execute()`를 스크래치
DB로 end-to-end 실행하며 결과를 엄격히 검증하고 있었다 — 새 테스트를 추가하는
대신(이미 충분히 정밀한 기존 스위트가 있어 새로 만들면 같은 것을 두 벌 유지하게
된다), 그 기존 스위트가 그대로 통과하는 것으로 회귀를 확인했다. 추가로 실
`auction.db`의 스크래치 복사본에 대고 실행해 `auction_item`/`document_status`
건수가 수정 전과 동일함을 직접 재확인했다(§검증 표).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M129b | `case_id_by_key`를 채우는 `WHERE ... IN` 조회를 통째로 생략(캐시가 항상 빈 딕셔너리) | **검출 O** ― `test_auction_identity.py::test_cross_court_migrate_safety`가 `case_id = case_id_by_key[...]`에서 `KeyError`로 즉시 크래시(예외는 `execute()`의 `except Exception: conn.rollback(); raise`가 그대로 전파 — 조용히 잘못된 결과를 내지 않고 확실히 죽는다) |

원복 후 `diff`로 원본과 바이트 단위 동일 확인(`DIFF_CLEAN`), 전체 스위트 재통과.

## 사후 발견 ― `test_schema_hygiene.py`의 SQL 보간 감시에 걸림 (같은 세션, 후속 회귀 스윕에서 발견)

이 Sprint 작업 직후 Test Gap 감사 겸 전체 스위트를 `coverage run`으로 다시 돌리다가
`test_schema_hygiene.py`가 처음으로 `FAIL`했다: 위 §1의 캐시 조회가 쓴
`f"... IN ({placeholders})"`가 "SQL 텍스트에 새 보간이 생기면 알린다"(2026-08-14 신설)
검사에 걸렸다 — `placeholders`가 `ALLOWED_SQL_TEXT_INTERPOLATIONS`에 없는 새 f-string
보간이었기 때문이다. 이 검사는 정확히 이런 경우(새 SQL 텍스트 조립 지점)를 사람이
한 번 보게 하려고 설계된 것이라 의도대로 작동한 것이다 — 검사 결함이 아니라 이번
수정이 그 검사가 지키는 지점을 새로 하나 만든 것.

내용을 확인한 결과 `placeholders = ",".join(["(?,?)"] * len(case_keys))`는
`api/v1/search.py`에 이미 허용돼 있는 `"placeholders"`(`"?,?,?"`, id 개수만 가변)와
정확히 같은 모양이다 — 텍스트에 들어가는 것은 `(?,?)` 문자의 반복뿐이고 실제 값은
전부 `params` 리스트를 통해 `?`로 바인딩된다. `test_schema_hygiene.py`의
`ALLOWED_SQL_TEXT_INTERPOLATIONS`에 `("migrate_execute.py", "placeholders")`를
같은 근거로 추가해 통과시켰다.

## 검증

| 항목 | 결과 |
|---|---|
| `test_auction_identity.py` | 전체 PASS(내장 실패-시나리오 출력 포함, 기존과 동일) |
| `test_pipeline_integrity.py` | 전체 PASS |
| `test_bootstrap.py` | 전체 PASS |
| `test_schema_hygiene.py` | 최초 FAIL(위 "사후 발견" 참고) -> allowlist 추가 후 PASS |
| 실 `auction.db` 스크래치 복사본에 대고 직접 실행 | `auction_item=2156`(신규 0/갱신 2156), `document_status=6468=orig*3`, `[OK]` 2건 모두 |
| `python -m compileall` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run lint` | 0 issues |
| 변이 잔여 | `migrate_execute.py` 원본과 diff 0(원복 확인) |
| 운영 DB | 스크래치 복사본에만 실행, 원본 `auction.db`는 읽기조차 하지 않음(복사 후 즉시 삭제 확인) |

## 수정 파일

```
migrate_execute.py       §1 직후 case_id 일괄 캐시 신설, §2/§3의 개별 SELECT를 캐시 조회로 교체
test_schema_hygiene.py   ALLOWED_SQL_TEXT_INTERPOLATIONS에 ("migrate_execute.py", "placeholders") 추가
docs/SPRINT130_MIGRATE_EXECUTE_N_PLUS_1.md   신규 (본 문서)
```

**제품 동작/스키마/API 계약 변경 0건.** 배치 스크립트의 내부 쿼리 구현만 바뀌었고,
입출력(auction_case/auction_item/document_status 최종 상태)은 기존과 동일함을
실측으로 확인했다.

## SKIP

없음(정책/승인 필요 항목 없음 — 순수 쿼리 최적화).

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112).
- Sprint 105~129 SKIP 표의 승인 대기 항목들
- 다음 Audit 영역: State Machine 나머지, Server Action idempotency 나머지,
  Test Gap / Documentation Drift / Architecture / Technical Debt (계속 진행)
