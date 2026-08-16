# Sprint 122 ― fresh clone과 운영 DB가 컬럼/인덱스 단위로 갈라져 있었다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT121_REGRESSION_REBASELINE.md`
>
> **별도 파일 이유**: Sprint 100~121과 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Sprint 121에서 "동일 패턴이 다른 곳에도 있는가"를 계속 찾다가, DB Schema/Index/Constraint
감사로 넘어갔다. `test_schema_hygiene.py`의 완전 중복 인덱스 검사를 다시 보며 "인덱스
하나가 어긋났으면 다른 것도 어긋나 있지 않은가"를 직접 fresh clone을 만들어 대조했다.

**대조했다.** 부트스트랩(빈 DB에서 `init_db()` → `migrate_v4_1.py` → `run_migrations`)으로
만든 스키마와 운영 `auction.db`를 테이블/컬럼/인덱스 단위로 실측 대조한 것은 이 세션이
처음이다(기존 `test_bootstrap_matches_live_schema()`는 **테이블 이름 집합**까지만 봤다).

---

## 1. ★★ 부트스트랩 안내 문서 자체가 죽는 순서였다

`docs/CLAUDE.md`가 안내하는 부트스트랩은 두 줄이었다.

```bash
python storage/migrate_v4_1.py
python -m storage.migrations.run_migrations
```

그 아래 "부트스트랩은 위 두 명령만으로 완결된다"고 못박고 있었다. **실제로 돌려보니
011에서 죽는다.**

```
[FAIL] 011_auction_case_court_code_unique.sql: no such table: auction
```

### 원인

`migrate_v4_1.py`는 `auction_case`/`auction_item`/... (v4.1 스키마)만 만든다. **레거시
`auction` 테이블은 `storage/database.py`의 `init_db()`만 만든다** ― 이건 `docs/CLAUDE.md`
바로 아래 문단에 이미 적혀 있었다("`init_db()`는 v4.1 테이블을 만들지 않는다"는 문장은
있는데, 그 역방향("`migrate_v4_1.py`는 레거시 테이블을 안 만든다") 때문에 **부트스트랩
안내에 `init_db()`가 아예 빠져 있다**는 것은 아무도 이어 붙이지 않았다).

그런데 마이그레이션 011/012는 레거시 `auction`을 읽는다(`docs/BUGS.md` #14 해소, 법원별
분리):

```sql
-- 011_auction_case_court_code_unique.sql:44
FROM auction a
```
```sql
-- 012_auction_court_code_unique.sql:66,69,70
FROM auction;
DROP TABLE auction;
ALTER TABLE auction_new RENAME TO auction;
```

안내대로 두 줄만 돌리면 001~010은 성공해 `migration_history`에 기록되고, 011에서
죽어 **DB가 절반만 마이그레이션된 상태**로 남는다 ― 이 저장소가 반복해서 잡아 온
바로 그 partial-success 모양이다(`test_bootstrap.py` 1번 검사가 막으려던 것과 같은
종류인데, 그 검사는 **다른 진입점**(`init_db()`만 있고 `migrate_v4_1.py`가 없는 경우,
008 실패)을 막고 이건 못 막고 있었다).

### 왜 지금까지 안 걸렸나 ― preflight 가드에 "auction"이 빠져 있었다

`run_migrations.py`는 Sprint 99가 만든 선행 스키마 확인이 있다 ― 지금 적용할 SQL이
`auction_item`/`auction_case`를 참조하는데 없으면, 죽기 전에 "1) init_db() 2) migrate_v4_1.py
3) run_migrations.py" 순서를 안내하고 **아무것도 적용하지 않고** 멈춘다. 그런데 이
목록(`PREREQ_TABLES`)에 **레거시 `auction`이 빠져 있었다.** 011/012는 `auction_item`이
아니라 `auction`(레거시)에 의존하므로 이 가드를 통과해 버리고, 진짜로 SQL을 실행하다가
raw `sqlite3.OperationalError`로 죽는다 ― Sprint 99가 막으려던 정확히 그 실패 모양이
"auction"이라는 한 단어가 빠진 자리로 재발하고 있었다.

### 고친 것

```python
# storage/migrations/run_migrations.py
PREREQ_TABLES = ("auction_item", "auction_case", "auction")  # "auction" 추가
```

`\bauction\b(?!_new)` 정규식이 이미 있어(Sprint 99), `auction_item`/`auction_case`/
`auction_new`는 오탐하지 않는다(단어 경계상 "auction_"의 "_"가 `\b`를 막는다 ―
실제로 재현해 확인). 한 단어만 추가하면 됐다.

`docs/CLAUDE.md`도 3단계로 고치고, "위 두 명령만으로 완결된다"는 틀린 문장을
정정 문단으로 바꿨다(이 저장소의 관례 ― 문장을 지우지 않고 정정을 덧붙인다).

### 검증 ― 두 경로 모두 실측

```
[가드 검증] init_db() 없이 migrate_v4_1.py -> run_migrations만 실행
  -> [중단] 선행 스키마가 없습니다: auction
     (1) init_db() (2) migrate_v4_1.py (3) run_migrations.py 안내, DB 변경 없음 확인

[정상 경로 검증] init_db() -> migrate_v4_1.py -> run_migrations
  -> 19개 마이그레이션 전부 적용, 25개 테이블 생성 (아래 §2 대조와 동일 결과)
```

---

## 2. ★★★ 이미 적용된 마이그레이션 파일이 나중에 편집됐다 ― fresh clone과 운영이 다르다

위 수정 후 fresh clone이 끝까지 도는 것을 확인했다. **그런데 끝까지 돈 스키마가 운영
`auction.db`와 완전히 같지 않았다.** 테이블 이름 집합은 같지만(25개, 일치), 그 안의
컬럼 제약과 인덱스가 6개 테이블에서 갈라져 있었다.

```
auction_case.court_code        fresh: NULL 허용         운영: NOT NULL
payment_webhooks.raw_payload   fresh: NOT NULL          운영: NULL 허용
payment_webhooks.processing_status  fresh: DEFAULT 'RECEIVED'   운영: 기본값 없음
registry_credits.amount        fresh: DEFAULT 0         운영: 기본값 없음
registry_credit_logs.delta     fresh: DEFAULT 0         운영: 기본값 없음

payment_logs      fresh에만: idx_payment_logs_created_at, idx_payment_logs_event_type
payment_webhooks  fresh에만: idx_payment_webhooks_received_at, idx_payment_webhooks_status
registry_credits  fresh에만: idx_registry_credits_created_at
audit_logs             운영에만: idx_audit_logs_admin_id (Sprint 121에서 이미 발견 - 출처 불명)
registry_credit_logs   운영에만: idx_registry_credit_logs_user_id
```

### 원인

`migration_history`(운영 DB)의 적용 시각을 보면 원인이 그대로 드러난다.

```
2026-08-08T15:43:24  016_create_audit_logs.sql          <- 지금 storage/migrations/에 없다
2026-08-08T16:09:24  017_add_soft_delete_columns.sql     <- 지금 storage/migrations/에 없다
2026-08-11T23:33:34  016_create_audit_and_credit_logs.sql   <- 지금 있는 016
2026-08-11T23:33:34  017_create_document_collect_failures.sql <- 지금 있는 017
```

**016/017이라는 번호가 파일명을 두 번 갈아탔다.** git 이력에도 옛 파일명 두 개는 전혀
안 남아 있다(`git log --all -- **/016_create_audit_logs.sql` 등 0건) ― `storage/`는
`.py`/`.sql`만 추적되므로(Sprint 51) 커밋되기 전에 로컬에서 이름이 바뀐 것으로 보인다.

`run_migrations.py`는 **파일명으로만** "적용됨"을 판단한다. 그래서:

1. 016/017 옛 이름으로 뭔가가 실행되고 `migration_history`에 기록됨(2026-08-08)
2. 그 파일이 나중에 다른 이름(현재 파일)으로 다시 쓰임(파일 내용이 바뀌었을 수 있다)
3. 새 이름은 `migration_history`에 없으므로 러너가 "안 적용됨"으로 보고 **또 실행**(2026-08-11)

014/015도 번호 자체는 그대로지만 **파일명이 바뀌지 않고 내용만 편집됐을 가능성**이
있다(014/015는 migration_history에 한 번만 기록돼 있다 ― 016/017과 달리 이름이
안 바뀌었으니 애초에 재실행 경로 자체가 없었다). 즉 014(`payment_logs`/`payment_webhooks`
생성)가 **처음 적용된 뒤 컬럼 제약/인덱스가 추가되도록 파일이 수정됐지만, 운영 DB에는
다시 반영되지 않았다** ― 파일명이 그대로라 러너가 "이미 적용됨"으로 스킵하기 때문이다.
015(`registry_credits`)도 같은 모양이다.

**공통 원인: 이미 적용된 마이그레이션 파일을 사후에 편집했다.** 마이그레이션은
append-only(한 번 적용되면 그 파일은 고정, 바꾸려면 새 번호로 추가)여야 하는데
그 원칙이 지켜지지 않은 흔적이 최소 4개 파일(011 계열 제외, 014/015/016/017)에 남아
있다.

### 왜 지금까지 안 걸렸나

`test_bootstrap_matches_live_schema()`(Sprint 99)가 이미 "fresh clone과 운영을 대조"
하고 있었지만 **테이블 이름 집합만** 봤다. 같은 이름의 테이블 안에서 컬럼 제약이나
인덱스가 다른 것은 그 검사의 사각지대였다 ― "테스트는 있지만 실제 결함을 못 잡는다"의
정확한 사례다.

### 실사용자 영향 ― 심각도가 균일하지 않다

전부 같은 무게가 아니다.

- **`payment_webhooks.raw_payload NOT NULL`(fresh만)** ― 위험이 실재한다.
  `api/v1/payment_logs.py:_dump()`는 `payload is None`이면 `None`을 그대로 돌려준다.
  `record_webhook(raw_payload=payload, ...)`가 이 `None`을 그대로 INSERT에 넘기면,
  **운영에서는 통과하지만(nullable) fresh 배포에서는 IntegrityError로 죽는다** ―
  "운영에서는 되는데 새 배포에서만 깨진다"는 이 저장소가 계속 경계해 온 모양 그대로다.
  (`payload`가 실제로 `None`이 되는 호출 경로가 지금 있는지는 이 세션에서 끝까지
  추적하지 않았다 ― 웹훅 수신 엔드포인트의 요청 파싱 단계까지 봐야 한다. 다음 Backlog.)
- **`auction_case.court_code`(운영만 NOT NULL)** ― Sprint 121의 `test_api_regression.py`
  수정(court_code 누락 INSERT)이 바로 이 제약 때문에 재현됐었다. fresh clone은 이
  제약이 **없으므로** 같은 실수를 해도 fresh 환경에서는 조용히 통과한다 ― 반대 방향의
  위험(운영에서만 걸리는 결함을 fresh 환경 테스트가 못 잡는다).
- **나머지(DEFAULT 값 차이, 누락된 보조 인덱스)** ― 애플리케이션 코드가 값을 항상
  명시적으로 채워 넣거나(예: `record_webhook`이 `processing_status`를 항상 직접
  넘긴다, 재확인함) 성능 인덱스일 뿐이라 당장 정확성에 영향은 없다. 다만 존재 자체가
  "마이그레이션 파일이 사후 편집됐다"는 같은 근본 원인의 증거로서 가치가 있다.

### 고친 것 ― 이 세션에서는 감지만 한다

운영 DB 스키마는 고치지 않았다(스키마 변경은 승인 영역, `docs/CLAUDE.md`). 대신
`test_bootstrap.py`에 §3-B를 신설해 **알려진 드리프트를 정확히 못박고, 새로 늘면
잡는다**(이 저장소의 상한/allowlist 관례와 동일):

```python
KNOWN_FRESH_ONLY_COLUMNS = { ... }   # fresh에만 있는 (테이블, 컬럼정의) 10건
KNOWN_LIVE_ONLY_COLUMNS  = { ... }   # 운영에만 있는 대응 쌍
KNOWN_FRESH_ONLY_INDEXES = { ... }   # fresh에만 있는 (테이블, 인덱스명) 5건
KNOWN_LIVE_ONLY_INDEXES  = { ... }   # 운영에만 있는 2건(audit_logs 건 포함)
```

정리되면(운영에 반영되면) 자동으로 "[정리됨] ... 상수에서 빼십시오"를 출력한다 ―
이 스크립트 자신이 낡은 allowlist가 되는 것을 막는다.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M102 | `run_migrations.py`의 `PREREQ_TABLES`에서 `"auction"`을 다시 뺌 | **검출 O** ― fresh clone이 011에서 raw `OperationalError`로 죽음(가드 우회 재현) |
| M103 | `test_bootstrap.py`의 `KNOWN_LIVE_ONLY_INDEXES`에서 `audit_logs` 항목 제거 | **검출 O** ― §3-B가 `[('audit_logs', 'idx_audit_logs_admin_id')]`로 즉시 실패 |

둘 다 원복 후 스위트 재통과 확인.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외, 전체 스위트 재실행으로 확인) |
| `test_bootstrap.py` 단독 | 신설 §3-B 포함 전부 통과, 2회 연속 확인 |
| fresh clone 3단계 부트스트랩 | 19/19 마이그레이션, 25개 테이블 ― 운영과 테이블명 일치 재확인 |
| `python -m compileall` | **exit 0** |
| 실 DB | **한 줄도 쓰지 않았다**(전부 임시 디렉터리 DB에 대고 실행, 운영 DB는 읽기 전용 연결만) |
| 변이 잔여 | `run_migrations.py`/`test_bootstrap.py` 모두 원복 확인 |

## 수정 파일

```
storage/migrations/run_migrations.py    PREREQ_TABLES에 "auction" 추가
docs/CLAUDE.md                          부트스트랩 안내 3단계로 정정(init_db() 추가)
test_bootstrap.py                       §3-B 신설(컬럼/인덱스 단위 드리프트 감지 + allowlist)
docs/SPRINT122_MIGRATION_DRIFT.md       신규 (본 문서)
```

**제품 코드(api/, storage/database.py, storage/migrate_v4_1.py, crawler/, src/) 변경
0건.** `run_migrations.py` 수정은 배포 스크립트의 안전장치 확장이지 스키마 변경이
아니다(빈 튜플에 문자열 하나 추가 ― 실행되는 SQL은 그대로).

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| 운영 DB 스키마를 파일과 일치시키기(6개 테이블 컬럼/인덱스) | 실제 스키마 변경(NOT NULL 추가/완화, 인덱스 추가) - 승인 영역 |
| `payment_webhooks.raw_payload`에 `payload=None`이 실제로 도달하는지 끝까지 추적 | 웹훅 수신 엔드포인트의 요청 파싱까지 봐야 하는 별도 조사 - 다음 Backlog로 남김(승인 대기는 아니지만 이 세션에서 미착수) |
| 마이그레이션 파일 사후 편집 재발 방지(예: 체크섬 기록) | 마이그레이션 시스템 자체의 설계 변경 |
| `idx_audit_logs_admin_id` DROP | Sprint 121과 동일(스키마 변경) |
| Task Scheduler 등록 | 사용자 환경 변경(Sprint 112) |
| Sprint 105~121의 SKIP 표 항목들 | 전부 승인/외부 조치 대기, 미해소 |

## 사후 대조 (2026-08-15, 같은 세션) ― Sprint 57 및 "25/25" 기록과 중복이 아닌가 확인

이후 `/goal`이 "새 발견 전에 과거 기록부터 대조하라"고 재차 지시해, 이 발견 자체를
`docs/CURRENT_STATE.md`/`docs/CHANGELOG.md`와 대조했다(Sprint 128이 이 대조를
건너뛰어 정정한 직후라 더 주의 깊게 봤다).

- `docs/CURRENT_STATE.md`의 **"25/25 완전 재현"** 문구(Migration 017 신설 시점,
  Sprint 57 이전)와 **"2026-08-11 Sprint 57 ― `auction.db` 되돌아감 재발견·복구"**
  섹션(migration_history에 옛 016/017 파일명이 다시 나타났던 사고) 둘 다 찾아 읽었다.
  둘 다 **테이블 이름 집합** 또는 **행 존재 여부**(dangling rows, 미적용 마이그레이션)
  수준의 대조였다 ― `test_bootstrap_matches_live_schema()`(Sprint 99)가 애초에
  테이블 이름 집합만 비교하는 것과 동일한 한계다. **컬럼 제약(NOT NULL/DEFAULT)이나
  인덱스 존재 여부를 테이블 단위로 대조한 기록은 이 문서 이전에 없다** ― 위 §2가
  발견한 6개 테이블 드리프트는 그래서 중복이 아니라 더 깊은 층위의 새 발견이다.
- 현재 `migration_history`를 다시 조회해 옛 016/017 행(2026-08-08)과 새 016/017 행
  (2026-08-11)이 **둘 다 공존**하는 것을 확인했다 ― 이것이 Sprint 57의 "정합화"
  결과물 그 자체다(옛 실행 이력은 남기고 새 파일명에 대한 행만 보강). 즉 지금
  `migration_history`가 이 모양인 것은 **되돌아간 게 아니라 Sprint 57이 의도적으로
  남긴 최종 상태**다 ― 되돌아감이 다시 재발했다는 뜻이 아니다.
- §2의 5개 컬럼 드리프트 값을 운영 `auction.db`에 대고 재조회해 **지금도 그대로임을
  재확인**했다(`court_code notnull=1`, `raw_payload notnull=0`,
  `processing_status default=None`, `registry_credits.amount default=None`,
  `registry_credit_logs.delta default=None`) ― 위 표와 전부 일치, 새로 벌어진 것도
  아니고 사라진 것도 아니다.

**결론**: 중복 아님, 정정 불필요. Sprint 57과의 관계만 이 문단으로 명시해 다음
세션이 두 문서를 같은 사고로 착각하지 않게 남긴다.

## 후속 조사 완료 ― `payment_webhooks.raw_payload`에 `None`이 실제로 도달하는가

위 Backlog로 남겨뒀던 것을 이어서 확인했다. `api/v1/payments.py:receive_payment_webhook()`
(§614)가 유일한 `record_webhook()` 프로덕션 호출부다(`grep` 확인, 테스트 제외 호출 1곳).
그 안에서 `payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}` ―
본문이 비어 있어도 **항상 dict**(`{}` 이상)가 되고, 바로 다음 줄이
`if not isinstance(payload, dict): raise ValueError`로 dict가 아니면 400을 돌려주므로
`record_webhook(..., raw_payload=payload, ...)`에 `None`이 넘어가는 경로가 **현재
코드에는 없다**. `_dump(payload)`(`api/v1/payment_logs.py:74`)가 `None`을 그대로
`NULL`로 직렬화하는 것은 사실이지만, 그 입력 자체가 프로덕션 호출부에서 발생할 수
없다 ― §2의 컬럼 드리프트(fresh: NOT NULL, 운영: NULL 허용)는 여전히 사실(파일과
운영 스키마가 다르다)이지만, "지금 당장 실서비스에서 NULL이 써질 위험"은 **아니다**.
잠재 위험은 `record_webhook()`을 직접 호출하는 새 코드가 나중에 `raw_payload=None`을
넘길 경우로 한정된다(함수 시그니처가 `Any`를 받아 막지 않는다) ― 지금 발생하지
않는다는 것과 앞으로도 안전하다는 것은 다른 얘기라 §2의 SKIP 항목(운영 스키마를
파일과 일치시키기)은 유효하게 남는다.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다(Sprint 112).
- 운영 DB 스키마를 파일과 맞추는 승인 후 작업(위 SKIP 표) ― 맞춘 뒤에는
  `test_bootstrap.py`의 `KNOWN_*` 상수들이 "[정리됨]"으로 표시되므로 그때 비우면 된다
- 위 SKIP 표의 나머지 승인 대기 항목들
