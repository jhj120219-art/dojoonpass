# Sprint 294 — 복구/정리 스크립트 11개 + 문서 서빙 경로 감사 (2026-09-03, 매장 환경)

> **매장 환경 세션.** 운영 DB·운영 crawler 미접촉. 모든 실행 검증은 SQLite 사본 +
> 임시 디렉터리에서만 했고, 실제 스크립트를 `runpy` 로 **그대로** 호출했다(mock 아님).
>
> **이번 세션은 코드를 한 줄도 바꾸지 않았다** — 바꿀 결함을 찾지 못했다.

---

## 감사 표면과 결과

| # | 표면 | 방법 | 결함 |
|---|---|---|---|
| 1 | `reset_failures.py` (유일한 DELETE 보유) | 사본에서 실제 실행 × 3시나리오 | **0** |
| 2 | repair/backfill 스크립트 10개 | 정적 스캔 + SQL 확인 | **0** |
| 3 | 문서 서빙 경로(`documents.py`) | 경로 탐색 11종 실제 요청 | **0** |

---

## 1. 복구 스크립트 위험 신호 스캔 (11개)

"복구 도구는 정상 경로보다 위험하다"는 전제로, 먼저 위험 신호만 기계적으로 훑었다.

```
파일                              무WHERE쓰기  apply가드  commit  rowcount
reset_failures.py                      1          예       1        0     <- 유일한 DELETE
repair_document_status.py              1*         예       1        0
repair_unsupported_status_docs.py      1*         예       1        0
repair_empty_status_capture.py         0          예       1        2
unlock_retry.py                        0          예       1        1
backfill_area / doc_raw / region /
  dong_normalize / dong_fix_mismatch    0          예       1        0
refresh_priority.py                    0        없음*      0*       0
revalidate.py                          0        없음*      0*       0
```

`*` 는 **내 스캐너의 오탐**이었다. 실제로 확인해 정정한다.

```
repair_document_status / repair_unsupported_status_docs
   -> 둘 다 `UPDATE ... WHERE id=?` 행별 정밀 쓰기다.
      다중행 SQL 문자열에서 내 정규식이 WHERE 를 놓쳤을 뿐이다.

refresh_priority / revalidate
   -> 얇은 **래퍼**다. 실제 write 와 commit 은 `storage/database.py` 안에 있다.
      매일 도는 배치라 dry-run 개념이 없는 것이 정상이다(초기화 도구가 아니다).
```

즉 신호 4건 전부 오탐. 진짜 대상은 **`reset_failures.py` 하나**였다.

---

## 2. `reset_failures.py` — 실제 실행으로 검증

이 스크립트만 `DELETE FROM ...` 를 갖는다. 사본에 synthetic FAILED 를 주입하고
실제 스크립트를 그대로 돌렸다.

### 시나리오 A — dry-run ↔ 실제 일치, 멱등

```
초기 (FAILED 43 / 실패로그 28)
DRY-RUN   예고: 되살림 43 · 종결보호 0 · 로그삭제 28
          DB 변화 (43, 28)  <- 아무것도 쓰지 않았다 ✔
APPLY     실제: 되살림 43 · 남은 FAILED 0 · 남은 로그 0
          ★ dry-run 예고 43 == 실제 43   일치 ✔
재실행     되살린 행 0        <- 멱등 ✔
```

### 시나리오 B — ★ 보호 경로(가장 중요한 안전장치)

A 는 우연히 **종결 보호가 0건인 표본**이라 안전장치가 실행되지 않았다. 그래서
종결 행을 일부러 FAILED 로 만들어 다시 찔렀다.

```
주입: 종결(SKIPPED_*) 연결 30건 + 비종결 20건 + 원래 3건 = FAILED 53
실행 결과
  DRY-RUN 예고     되살릴 23 / 종결이라 두는 것 30
  APPLY            되살린 행 23 · 남은 FAILED 30
  ★ 종결 30건 중 보호된 것   30 / 30      ✔
  ★ 종결인데 잘못 되살아난 것  0            ✔
```

`WHERE status='FAILED' AND id NOT IN (TERMINAL_ROWS)` 의 `NOT IN` 은 서브쿼리에
NULL 이 있으면 전량이 UNKNOWN 이 되어 **아무 행도 안 고쳐지는** 함정이 있는데,
여기서 뽑는 것은 `d.id`(PK)라 NULL 이 될 수 없다 — 그래서 `IN`(dry-run)과
`NOT IN`(실제)이 정확히 상보적이고, 위 두 숫자가 일치하는 것이 그 증거다.

JOIN 성립률도 실데이터로 확인했다(읽기 전용).

```
document_queue SKIPPED_*                     186행
TERMINAL_ROWS 가 잡는 document_status 행      183행   <- 보호가 실제로 작동한다
```

### 기록만 — 결함은 아니지만 비대칭

```
DELETE FROM document_collect_failures   WHERE 없는 **전량 삭제**이고
                                        guard_mass_purge 를 쓰지 않는다.
```

결함으로 보지 않는 근거: (1) 이 표는 수집 실패 **진단 로그**이고 파생 데이터다,
(2) 스크립트 이름·목적 자체가 "실패 초기화"라 전량 삭제가 의도다,
(3) dry-run 이 삭제 건수를 미리 알려 준다, (4) 재수집으로 자연히 다시 쌓인다.

다만 다른 destructive 경로(`purge_orphans` 등)는 `guard_mass_purge` 를 거치는데
여기만 안 거친다는 **비대칭**은 남는다. 지금 고치면 "실패 초기화" 라는 도구의
목적 자체와 충돌하므로 손대지 않았다. 관찰로만 남긴다.

---

## 3. 문서 서빙 경로 — 경로 탐색 11종

`GET /item/{item_id}/documents/{doc_type}` 은 `doc_type` 이 **사용자 입력**이고
파일 경로를 계산해서 만든다(사진 서빙과 달리 DB 의 `storage_path` 를 쓰지 않는다).
그래서 별도로 찔렀다.

```
SPEC                        200   (정상)
spec                        200   (대소문자 정규화)
EVIL                        400   (화이트리스트 밖)
../../.env                  404
..%2f..%2f.env              404
%2e%2e%2f%2e%2e%2f.env      404   (이중 인코딩)
SPEC/../../../.env          404
....//....//.env            404
SPEC%00.pdf                 400   (null byte)
"SPEC "(뒤 공백)             400
"％SPEC"(전각)               400
=> 파일 내용 유출 0
```

방어가 3중이다.

1. `doc_type` 은 **`DOC_TYPE_FILES` 의 키로만** 쓰이고 실제 파일명은 상수에서 온다
2. 조립된 경로를 `realpath` + `commonpath` 로 `documents/` 안인지 검증
   (드라이브가 다를 때 `commonpath` 가 던지는 `ValueError` 까지 "밖"으로 처리 — BUGS #229)
3. `isfile` + `size > 0`

경로 조각 중 `court_name`/`case_no` 는 **DB 값**이라 DB 가 오염되면 위험한데,
2번이 그 경우까지 막는다(이중 방어).

---

## 검증하지 못한 것

```
BLOCKED_EXTERNAL_RUNTIME
  실제 backup restore          운영 백업본으로만 가능
  unlock_retry 의 동시 실행     doc_worker 두 프로세스를 실제로 띄워야 한다.
                              정적으로는 RunLock 이 `_HERE` 기준 경로를 쓰는 것까지
                              확인했다(cwd 가 달라도 락이 갈라지지 않는다).
  운영 규모에서의 reset_failures 이 머신 FAILED 는 3건뿐이라 synthetic 으로 대체했다
```

---

## 승인 필요

없음. 이번 감사에서 정책 판단이 필요한 항목은 나오지 않았다.
기존 승인 대기 항목(B~J)은 변동 없다.
