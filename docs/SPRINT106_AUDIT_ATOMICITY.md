# Sprint 106 — 감사 로그 원자성, 죽은 스키마, 다중 쓰기 경로 (2026-08-14)

> 앞 Sprint: `docs/SPRINT105_BACKLOG_SWEEP.md`
>
> **별도 파일 이유**: Sprint 100~105와 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

TRANSACTION / ROLLBACK 감사에서 **실제 결함 1건**을 찾아 고쳤다.
그 결함은 "테스트 주석이 정적 확인 완료라고 적어 둔 주장이 틀린" 형태로 숨어 있었다.

---

## #106-1 ★ 감사 기록이 실패해도 특권 조작이 남는다 (2개 엔드포인트)

**심각도 높음** (과금에 직접 영향을 주는 조작이 **추적 불가능하게** 성립할 수 있었다)

### 어떻게 찾았나 — 다중 쓰기 경로 전수

한 요청에서 **두 개 이상의 테이블에 쓰는** 함수를 AST로 전부 뽑았다(헬퍼 경유 포함).
11개가 나왔고, 각각에 대해 commit / rollback / `BEGIN IMMEDIATE` 유무와
**실패 주입 검사의 존재**를 대조했다.

그 표에서 `adjust_registry_credit`(SUPER_ADMIN 무료횟수 조정)이
`registry_credits` + `registry_credit_logs` + `audit_logs` 3개 테이블에 쓰면서
**실패 주입 검사가 없는** 유일한 과금 경로로 드러났다.

### 실제 구조 — commit 이 감사보다 **앞**에 있었다

```python
credit_id = add_credit(...)      # registry_credits + registry_credit_logs
conn.commit()                    # <- 여기서 이미 확정된다
...
record_audit(...)                # audit_logs
conn.commit()
```

바로 그 아래 주석이 **"과금에 직접 영향을 주는 조작이라 반드시 감사 로그를 남긴다"**
고 적고 있는데, 두 커밋으로 갈라져 있어 그 약속이 지켜지지 않았다.

`record_audit` 5개 호출부를 전부 같은 방법으로 검사한 결과 **2곳이 같은 모양**이었다.

```
update_registry_request_status   commit(본작업) -> record_audit -> commit    ★
adjust_registry_credit           commit(본작업) -> record_audit -> commit    ★
admin_reprocess_webhook          record_audit -> commit    OK
admin_refund_payment             record_audit -> commit    OK
admin_change_subscription_status record_audit -> commit    OK
```

### 재현 — 수정 전/후를 같은 방법으로 측정

`record_audit` 에 예외를 주입하고 무료횟수 조정을 호출했다(테스트 사용자, 뒤에 정리).

```
수정 전 :  registry_credits +1 / registry_credit_logs +1 / audit_logs +0
           -> ★ 감사 기록 없이 크레딧 조정이 영구히 남는다

수정 후 :  registry_credits  0 / registry_credit_logs  0 / audit_logs  0
           -> 감사가 실패하면 조정도 남지 않는다
```

이것이 `test_api_regression.py` 자신이 경고한 상태의 나머지 절반이다 —
*"실패한 조작이 감사 로그에만 남으면 하지도 않은 특권 조작이 기록으로 존재하게 되고,
**반대로 성공한 조작이 안 남으면 추적이 끊긴다**"*.

### 수정 — 본 작업 커밋을 감사 뒤로

두 곳 모두 `conn.commit()` 을 `record_audit()` 뒤로 옮겼다. 나머지 셋과 같은 모양이 된다.

`adjust_registry_credit` 에서 안전한 이유를 확인했다:
`record_audit` 의 `after` 가 `get_credit_adjustment(conn, ...)` 로 결과를 다시 읽는데,
**같은 커넥션은 커밋 전에도 자기 쓰기를 본다.** 따라서 감사 내용은 바뀌지 않는다.
실제로 `test_api_regression` / `test_race_conditions` / `test_subscription_policy`
전부 그대로 통과한다(동작 무변경).

### ★ 그리고 "정적 확인 완료"라는 주석이 틀렸다

`test_api_regression.py` 에 이렇게 적혀 있었다.

> admin.py의 5개 호출부는 전부 `record_audit(...)` 다음에 같은 커넥션으로
> `conn.commit()`을 부르고, 실패 경로에서는 `conn.rollback()`으로 되돌린다
> **(정적 확인 완료)**

**5개 중 2개가 사실이 아니었다.** 주석에 "확인 완료"라고 적는 것으로는 남지 않는다.
그래서 그 주장을 **코드가 확인하게** 바꿨다 — AST 로 admin.py 를 읽어
`record_audit` 앞에 `conn.commit()` 이 있는 엔드포인트를 찾는 구조 검사를 넣었다.

```
[PASS] 본 작업을 감사보다 먼저 커밋하는 admin 엔드포인트 없음: []
```

### 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M61 | `adjust_registry_credit` 를 수정 전 상태로 되돌림 | **검출 O** — 이름까지 지목 |
| M62 | `update_registry_request_status` 를 수정 전 상태로 되돌림 | **검출 O** — 이름까지 지목 |

---

## #106-2 죽은 스키마 — 이미 알려진 것과 같음 (새 사실 없음)

테이블 25개를 행 수 / 운영코드 언급 / 테스트 언급으로 전수 분류했다.

**운영 코드에 INSERT 가 아예 없는 테이블 2개**를 찾았다.

```
parsed_document           0행   읽기 0곳 / 쓰기 0곳   (migrate_v4_1.py 의 CREATE 뿐)
rights_analysis_history   0행   읽기 0곳 / 쓰기 0곳
```

읽는 쪽이 있었다면 **조용히 빈 기능**이 됐겠지만, 읽는 코드도 없다.
그리고 이것은 **이미 `docs/BUGS.md` #49 에 기록돼 있다**("읽기 0곳 쓰기 0곳").
문서 드리프트가 아니다 — 저장소가 알고 있고 적어 두었다. 삭제는 스키마 변경(승인 영역).

> `auction_item` / `auction` 의 **미사용 컬럼은 0개**였다. 컬럼 수준의 죽은 스키마는 없다.

## #106-3 도달 불가 운영 모듈 — `filter/` 3개 (기존 결론 재확인)

운영 진입점 5개(`api_server` / `mvp_scraper` / `doc_worker` / `migrate_execute` /
`refresh_priority`)에서 import 그래프를 BFS 로 훑어 도달 가능한 37개 모듈을 구했다.

도달 불가 운영 모듈 중 `__init__.py` 를 제외하면 **`filter/` 3개와
`collect_documents.py`** 뿐이다. 둘 다 `docs/CLAUDE.md` 가 이미 죽은 코드/미실행으로
기록한 것과 일치한다. **새 사실 없음.**

---

## 다중 쓰기 경로 11개의 방어 현황 (측정값)

| 함수 | 쓰는 테이블 | commit | rollback | 실패주입 검사 |
|---|---|---|---|---|
| `create_payment` | payments / subscriptions / registry_requests | O | O | (BEGIN IMMEDIATE) |
| `create_registry_request` | registry_usage / credit_logs / requests | O | O | **O** (Sprint 105 §41) |
| `update_registry_request_status` | registry_requests / audit_logs | O | O | 구조 검사(신설) |
| `adjust_registry_credit` | registry_credits / credit_logs / audit_logs | O | O | **O** (이번 신설) |
| `mark_queue_done` | queue / document_status / auction / version_log | O | close 롤백 | O |
| `mark_queue_failed` / `_unsupported` / `reset_stale_queue` | queue / document_status | O | close 롤백 | O |
| `record_view` | recent_items | O | - | O |
| `create_payment_record` | payments / payment_logs | 호출부 | 호출부 | 호출부 경유 |
| `_apply_webhook_event` | payments / payment_webhooks | 호출부 | 호출부 | 호출부 경유 |

`mark_queue_*` 계열이 명시적 `rollback()` 없이도 안전한 이유는 Sprint 104 에서 확인했다 —
`finally: conn.close()` 가 미커밋 트랜잭션을 자동 롤백한다(두 겹 방어).

---

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31/31 파일 통과** |
| `python -m compileall` | **exit 0** |
| 프런트 테스트 | **107/107** (fail 0 / cancelled 0 / skipped 0) |
| TypeCheck / Lint / Build | **전부 exit 0** |
| BOM / 콘솔 인코딩 가드 | 통과 |
| 실 DB | 테스트 사용자 행만 만들고 **전부 정리**(qa 잔여 0) |
| 변이 검증 | **M61 / M62 검출** |

## 수정 파일

```
api/v1/admin.py            ★ 감사보다 먼저 커밋하던 2곳을 한 트랜잭션으로
test_api_regression.py     틀린 "정적 확인 완료" 주석 정정 + AST 구조 검사 신설
```

제품 동작 변경은 `api/v1/admin.py` 한 곳이고, **성공 경로의 결과는 그대로**다
(기존 테스트 전부 무변경 통과). 달라지는 것은 **감사가 실패했을 때** 뿐이다.

## SKIP (변동 없음)

Task Scheduler 등록 / 각종 `--apply` 실행 / 죽은 스키마 삭제 / worktree 삭제 /
`total_failures` 정의 / 환불 시 구독 처리 / httpx2 전환 / 현황조사서 버튼 id.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** (2026-08-20에 검색 결과 0건)
- Sprint 105 의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
