# Sprint 110 ― '끝나지 않는 수집중'의 진짜 규모, 그리고 되돌린 수정 (2026-08-14)

> 앞 Sprint: `docs/SPRINT109_SOFT_DELETE_CHECKLIST_GAP.md`
>
> **별도 파일 이유**: Sprint 100~109와 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

이 스프린트는 **내가 고쳤다가 되돌린 기록**이다. 고친 것이 제품 정책 결정이었고,
그 결정을 **앞선 스프린트가 이미 검토하고 보류**해 뒀기 때문이다.
남은 것은 그 결정에 필요한 **새 측정값**과, 비대칭을 지키는 검사다.

---

## 1. 먼저 데이터 정합성부터 (결함 0건)

`auction`(크롤러가 쓰는 곳)과 `auction_item`(API가 읽는 곳)의 단방향 동기화를 실측했다.

```
auction 1,876행  =  auction_item 1,876행
한쪽에만 있는 행           0   (누락 0 / 고아 0)
공통 14개 컬럼의 값 불일치  0   (updated_at 은 동기화 시각이라 제외)
기일 >= 오늘               둘 다 9행
```

**드리프트 없음.** `migrate_execute.py` 는 제 일을 하고 있다.

## 2. '문서가 있다'의 세 기준도 일치한다

같은 사실을 세 곳이 따로 기록한다 ― 셋을 5,628건 전수 대조했다.

| 레거시 플래그 | `document_status` | 디스크 파일 | 건수 | |
|---|---|---|---|---|
| False | False | False | 5,037 | 일치 |
| True | READY | 있음 | 554 | 일치 |
| True | COLLECTING | 없음 | 35 | 불일치 |
| False | READY | 있음 | 2 | 불일치 |

**불일치 37건(0.7%)**, 그리고 **전부 레거시 플래그 쪽이 틀렸다.**
API 는 레거시 플래그를 읽지 않으므로(`test_schema_hygiene.py` 가 강제) 사용자 화면은
37건 모두 옳다. 그 가드가 실제로 값을 하고 있다는 증거다.

> 처음 측정에서는 불일치가 **591건**으로 나왔다. `doc_exists()` 의 인자 순서를
> `(court, case, doc_type, item_no)` 로 잘못 넣었기 때문이다(실제는
> `(court_code, case_no, item_no, doc_type)`). **5,628건 판정을 통째로 버리고 다시 쟀다.**
> 숫자가 크게 나왔을 때 먼저 의심할 것은 제품이 아니라 내 도구다.

## 3. ★ 새로 드러난 것 ― '끝나지 않는 수집중'이 2,328건

`document_status = COLLECTING`("수집중") 5,069건을 **누가 처리 중인지**로 갈랐다.

```
(정상) 큐에서 대기 중 ― 언젠가 수집된다                     2,741
(b)   큐 행이 없다 ― 기일 경과로 애초에 넣지 않음            2,145   <- 새 발견
(a)   큐가 SKIPPED_EXPIRED 로 종결 ― 다시 집히지 않는다        183

-> 아무도 수집하지 않는 것: 2,328건 (45.9%)
```

`test_document_status_sync.py` §6 은 이 상태를 이미 알고 고정하고 있었지만,
**원인 (a) 하나만, 183건으로** 세고 있었다. 더 큰 원인 (b)가 있다 ―
`enqueue_documents()` 의 1차 방어선이 기일 지난 사건을 **애초에 큐에 넣지 않는다.**
그 문서들은 큐 행 자체가 없어 **어떤 종결 함수도 지나지 않는다.**

이것이 이 스프린트의 실질 기여다: **(a)를 고쳐도 (b)는 그대로 남는다.**
정책을 정할 때 두 경로를 함께 봐야 한다.

사용자 노출은 지금 **0건**이다 ― 2,328건 전부 기일이 지나 검색 기본 필터(D7)에서 빠진다.
`include_closed=true` 조회 / 찜 / 최근 본 물건 / 문서 통계에만 섞인다.

## 4. ★ 고쳤다가 되돌렸다

비대칭을 먼저 찾았다. 이 모듈의 종결 함수 넷 중 **셋만** 화면 상태를 함께 쓴다.

```
mark_queue_done            -> READY
mark_queue_failed          -> FAILED
mark_queue_unsupported     -> FAILED   (Sprint 101)
mark_queue_skipped_expired -> 쓰지 않는다        <- 하나만 다르다
```

사본 DB로 재현하고, `mark_queue_unsupported` 의 선례를 따라 FAILED를 쓰도록 고쳤다.
회귀 검사를 넣고 변이 검증(M75/M76)까지 통과했다.

**그런데 전체 게이트에서 `test_document_status_sync.py` §6 이 깨졌다.**
읽어 보니 Sprint 73이 **정확히 이 변경을 검토하고 거부**해 뒀다.

> **왜 고치지 않았는가** ― "대상이 아님"을 나타낼 상태가 없다. DocStatus는
> COLLECTING/OCR/PARSING/ANALYZING/READY/FAILED뿐이고, FAILED로 쓰면 실패가 아닌 것을
> 실패로 표기하게 된다. 새 상태를 만드는 것은 상태머신·화면 문구 결정이라 **제품 판단**이다.

지시받은 원칙 그대로다 ― **정책을 임의로 결정하지 않는다.** 그래서 되돌렸다.

되돌린 것:

```
storage/database.py:mark_queue_skipped_expired()   동작 원복 (docstring만 남김)
repair_expired_status_docs.py                      삭제 (미결 정책을 실행하는 스크립트)
```

> 만약 전체 게이트를 돌리지 않고 새 검사만 보고 끝냈다면,
> **초록불 여섯 개를 근거로 제품 정책을 바꿔 놓고 "결함을 고쳤다"고 보고했을 것이다.**

### 남는 긴장 (제품 결정 항목)

저장소는 지금 **인접한 두 경우에 반대로** 판단하고 있다.

| 상황 | 화면 상태 | 근거 |
|---|---|---|
| 수집 버튼 id가 없다(구조적 불가) | **FAILED** | Sprint 75/101 ― "빠르게 실패로 남기는 쪽이 정직하다" |
| 기일이 지났다(대상 아님) | **COLLECTING 유지** | Sprint 73 ― "실패가 아닌 것을 실패로 쓸 수 없다" |

둘 다 "영원히 도착하지 않는 문서"인데 표기가 다르다.
어느 쪽이 옳은지는 화면 문구와 함께 정할 일이라 **여기서 정하지 않는다.**

## 5. 남긴 것

### `test_document_queue.py` §18 (신설)

**비대칭 자체를 계약으로 고정**한다 ― 셋은 화면 상태를 쓰고, 넷째는 일부러 안 쓴다.

```
[PASS] mark_queue_done 는 document_status를 함께 갱신한다
[PASS] mark_queue_failed 는 document_status를 함께 갱신한다
[PASS] mark_queue_unsupported 는 document_status를 함께 갱신한다
[PASS] mark_queue_skipped_expired 는 화면 상태를 쓰지 않는다(제품 판단 대기)
[PASS] 화면 상태는 그대로 수집중이다(§6이 고정한 현재 동작)
[PASS] 종결 후에는 큐에서 다시 집히지 않는다(그래서 끝나지 않는 수집중이다)
```

셋 중 하나가 조용히 빠지면 '끝나지 않는 수집중'이 **새로** 생기는데,
§6 은 `skipped_expired` 하나만 보므로 그 손실을 알려 주지 않았다.

> §9(기존 `mark_queue_skipped_expired` 검사)가 이 영역을 못 본 이유도 기록했다 ―
> 큐의 status/retry_count/last_attempt_at만 보고 **화면 상태를 한 번도 보지 않는다.**
> 계약의 절반만 검사하는 테스트는 나머지 절반이 비어도 초록불이다.

### `measure_endless_collecting.py` (신설, **`--apply` 없음**)

`cleanup_orphans_dryrun.py` 와 같은 관례 ― 결정에 필요한 숫자만 낸다. 아무것도 쓰지 않는다.
두 원인 (a)/(b)를 갈라 세고, 그중 **기일이 남아 검색에 노출되는 것**을 따로 표시한다
(지금은 0건 ― 0이 아니게 되는 순간이 우선 대상이다).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M75 | `mark_queue_skipped_expired` 에 화면 갱신 배선 | **검출 O** ― §18 + `test_document_status_sync` §6 이 함께 실패 |
| M76 | 같은 자리에 COLLECTING 을 씀 | **검출 O** |

> M77(예외 가드 제거)은 §18 이전에 §9 가 `no such table: auction_item` 로 **하드 크래시**
> 하며 잡았다. §18 자체의 판정은 성립하지 않았지만(실행 전에 죽음) 스위트는 잡는다.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| `python -m compileall` | **exit 0** |
| 프런트 | 무변경 (Sprint 107에서 107/107, TSC/LINT/BUILD exit 0) |
| 실 DB | **한 줄도 쓰지 않았다** ― 재현은 전부 임시 사본, 측정은 read-only |
| 제품 동작 | **변경 0건** (되돌림 후 `mark_queue_skipped_expired` 는 docstring만 다르다) |

## 수정 파일

```
storage/database.py         mark_queue_skipped_expired docstring ― 보류 사유 + (b) 측정값
test_document_queue.py      §18 신설 (종결 함수의 화면 상태 계약)
measure_endless_collecting.py  신설 (측정 전용, --apply 없음)
```

## SKIP / 제품 결정 대기 (이번에 하나 늘었다)

- **★ 신규: '수집 대상 아님'을 화면에 무엇으로 표시할 것인가.**
  대상 **2,328건**(원인 (a) 183 + (b) 2,145). 지금은 전부 만료라 사용자 노출 0건이지만,
  버튼 id 미지원(Sprint 101)과 **반대로** 판단하고 있는 상태다.
  `measure_endless_collecting.py` 로 언제든 다시 셀 수 있다.
- Task Scheduler 등록 / 각종 `--apply` 실행 / 죽은 스키마 삭제 / worktree 삭제 /
  `total_failures` 정의 / 환불 시 구독 처리 / httpx2 전환 / 현황조사서 버튼 id /
  문서 3종의 구독 게이트 / 소프트 삭제 전환.

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  선행 조건은 전부 확인됐고 **등록만 남았다.**
- Sprint 105~109의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
