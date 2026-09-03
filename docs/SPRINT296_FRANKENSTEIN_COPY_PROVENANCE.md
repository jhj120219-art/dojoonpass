# Sprint 296 — Frankenstein 전수 검토: 사본 셋을 실제로 정리하고, "지워도 되나"를 기계가 답하게 했다 (2026-09-04, 집 개발환경)

> 감사만 하지 않았다. **실제로 고친 것 3건 + 신설 가드 4축**이 이 세션의 결과물이다.
> 운영 DB 는 한 바이트도 바뀌지 않았다(전부 `mode=ro` 읽기, 변이는 전부 복원).

---

## 0. 무엇을 훑었나

지시가 요구한 10개 축을 전부 실제 코드/DB/실행으로 확인했다. 아래는 **결론이
"깨끗하다"인 축도 근거와 함께** 남긴다 — 근거 없는 초록은 이 저장소가 반복해서
경계해 온 것이다.

```
축                                    방법                                   결과
1 duplicate implementation            AST 전수(236 py, 최상위 심볼)           중복 11 → 전부 분류됨(아래)
2 legacy implementation               git ls-files + 이력 blob 대조           7건, 전부 정본의 과거 판본
3 alternate implementation            제품 caller 0 인 함수 추출               9건, 전부 설명됨
4 bypass path                         src/ 전수 grep (fetch/sqlite/supabase)   0건
5 dead/unreachable                     참조 0 인 제품 함수                      0건
6 same concept different contract     doc_type/status 어휘 DB 대조             전부 선언과 일치
7 crawler→normalizer→DB merge         auction ↔ auction_item 2,834행 × 13필드  drift 0
8 API→frontend 중복/우회              라우트 46개 중복 0 / 타입계약 66검사 통과  0건
9 identifier 우회/alias               (case_id,item_no) 중복 0 / FK 위반 0      병합순서 1건(기존 BLOCKED)
10 동일 기능 서로 다른 판본            아래 §1                                  2건 수정 (+ §6-A 1건)
```

---

## 1. 실제로 고친 것

### (1) `repair_document_status.py` — 뷰어 파일명표가 **반쪽만 옮겨진 사본**이었다

```
정본        crawler/doc_paths.py:CANONICAL_DOC_FILENAME
서빙        api/v1/documents.py:DOC_TYPE_FILES        (정본과 대조됨 ✔)
크롤러      doc_paths.DOC_REQUIRED_FILES              (정본과 대조됨 ✔)
백필        backfill_doc_raw.py                       (정본을 import ✔)
보정 도구   repair_document_status.py                 ← **손으로 적은 사본**
                                                        위에 "같아야 한다" 주석만 있고
                                                        **그것을 강제하는 검사가 없었다**
```

이 자리가 위험한 이유는 이 스크립트가 그 표로 *"파일이 디스크에 있는가"* 를 판정해
`document_status` 를 **READY 로 바꾸기** 때문이다. 표가 갈라지면 이 저장소가 BUGS
#50/#61/#64/#129 로 반복해 겪은 그 상태가 된다 — **화면은 '수집완료', 뷰어는 404.**
이 파일 docstring 자체가 없애려던 결함이다.

같은 파일의 **경로 규칙**은 Sprint 153 에 이미 정본 호출(`sanitize_path_segment`)로
바뀌었다. 파일명표만 남아 있었다.

**고친 것**: `DOC_TYPE_FILES = dict(CANONICAL_DOC_FILENAME)`.

동작은 바뀌지 않는다 — 실데이터로 확인했다.

```
scan(새 정본 유도)  fix=0  already=1278  missing=7632  total=8910
scan(옛 손 사본)    fix=0  already=1278  missing=7632  total=8910   ← 완전 동일
```

### (2) `api/v1/favorites.py:get_item_summary()` — **쓰이지 않는 두 번째 물건 모양**

`SELECT *` 로 행을 읽어 14개 필드의 물건 응답 dict 를 조립했는데, 유일한 호출부
(`add_favorite`)는 그것을 `if not item:` 으로 **있다/없다만 보고 버렸다.** 응답에는
한 번도 실리지 않는다.

생긴 경위가 남아 있다 — 예전에는 `GET /favorites` 가 이 함수를 관심물건 개수만큼
반복 호출했다(N+1). 그 경로가 단일 JOIN 으로 바뀌면서 **목록의 물건 모양은
`get_favorites()` 안으로 옮겨갔는데** 이 함수는 그대로 남았다. 그 뒤 목록 쪽에만
필드가 다섯 개 늘어(`thumbnail_url`/`favorited_at`/`memo`/`tags`/`note_source`)
**같은 개념의 물건 모양이 두 벌로 갈라졌다.**

지금 고장난 것은 없다. 문제는 **이름이 더 그럴듯하다**는 것이다 — "관심물건 응답에
필드를 더하자"는 사람이 응답에 쓰이지도 않는 이쪽을 고치기 쉽고, 그러면 아무 일도
일어나지 않고 오류도 나지 않는다.

**고친 것**: 하는 일만 남겼다 → `item_exists(conn, item_id) -> bool`.
같은 판정을 하는 정본이 이미 있었고(`favorite_import._commit_one()` 의
`SELECT 1 ... WHERE id = ?`), 이제 둘은 같은 모양이다.

계약 무변경: 응답 키 `{item_id, created_at}` 그대로, 404/200 판정 그대로,
SQLite 범위 밖 id 가드(Sprint 154) 그대로.

---

## 2. ★ "어느 쪽이 최신인가"를 **기계가 답하게 했다** (신설)

OneDrive 충돌 사본 8개는 2026-08-27 이래 *"사람이 둘을 읽고 골라야 한다"* 로
영구히 미뤄져 있었다. 기존 검사는 **개수만** 셌다.

그런데 그 판단은 사람이 읽을 필요가 없다 — 사본의 blob 이 정본의 **어느 과거 커밋과
같으면** git 이 이미 보관 중인 판본이므로 지워도 잃을 것이 없다. 어느 판본과도
다르면, 그 사본에만 있는 작업이다.

`test_schema_hygiene.py` 의 기존 검사에 **이어 붙였다**(새 파일/새 검사를 만들지
않는다 — Sprint 276 의 교훈).

### 실행 결과 — 미뤄져 있던 질문에 답이 나왔다

```
(과거 판본) audit_auth_health-DESKTOP-DVRJEGP.py          == 정본의 옛 커밋
(과거 판본) audit_test_reality-DESKTOP-DVRJEGP.py         == 정본의 옛 커밋 (6481629, 08-25)
(과거 판본) audit_viewport-DESKTOP-DVRJEGP.py             == 정본의 옛 커밋 (0536603, 09-01)
(과거 판본) test_admin_secret_contract-DESKTOP-DVRJEGP.py == 정본의 옛 커밋 (6481629, 08-25)
(과거 판본) test_audit_selftests-DESKTOP-DVRJEGP.py       == 정본의 옛 커밋 (6481629, 08-25)
(과거 판본) test_crawl_orchestration-DESKTOP-DVRJEGP.py   == 정본의 옛 커밋 (f71c3f1, 08-26)
(과거 판본) test_max_items_contract-DESKTOP-DVRJEGP.py    == 정본의 옛 커밋
(판정 보류) .cov_test_audit_selftests-DESKTOP-DVRJEGP_py   커버리지 산출물(정본 없음)
★ 정본 이력에 없는 내용을 가진 충돌 사본이 없다: []
```

**추적 중인 소스 사본 7개 전부가 정본의 과거 판본이다.** 즉 `git rm --cached` 로
빼도 **잃는 내용이 0** 이다. (실행은 여전히 사람의 승인 영역 — 아래 §6.)

`test_admin_secret_contract` 사본은 정본보다 **줄 수가 많은데**(435 vs 418) 그래도
과거 판본이다. 줄 수로 최신을 판단하면 틀린다는 반례라 특히 기록해 둔다.

### 왜 이 검사가 중요한가

반대 경우가 실제로 있었다 — OneDrive 가 두 머신의 변경을 보고 사본을 만들었는데
**사본 쪽이 새 작업**이고 정본이 되돌려진 판본인 상황. 그때 "낡은 사본이니 지우자"
는 그 작업을 영구히 없앤다. 이제 그 경우엔 검사가 먼저 붉어진다.

---

## 3. 삭제/통합하지 **않은** 것 (근거)

| 항목 | 왜 남겼나 |
|---|---|
| `normalize_case_no` ×2 (normalizer / mylist_import) | 크롤은 원천 보존, 가져오기는 추출. 합치면 `2024타채1009` → `''`. `test_normalizer.py` 가 계약 고정 |
| `get_doc_dir` ×3 | 쓰기(makedirs) / 조회(계산만). 합치면 조회가 디렉터리를 만든다(실제 사고: 빈 폴더 1,675개) |
| `row_to_subscription` ×2 | 기본 9필드 동일 + 파생 3. `test_subscription_policy.py` 가 고정 |
| `_area_of` ×2 (search / item) | 4줄 private 헬퍼, 서로를 주석으로 가리킨다. 통합 이득 < layer 결합 비용 |
| `extract_fail_count` ×3 | `filter/` 는 어떤 진입점도 부르지 않는 진단 경로(실측: import 하는 곳이 `test_filter.py` 뿐) |
| `canon_case` ×2 (detector / pipeline test) | 둘 다 진단 측. 검사가 자기 검증 블록으로 의미를 고정한다 |
| `models/auction_item.has_status_pdf` | 컬럼명은 `has_status_doc` — 이름이 안 맞는 죽은 필드. **이미** `test_normalizer.py:run_normalized_keys_reach_storage()` 가 현 상태를 못박고 있다. 모델 시그니처 변경은 승인 영역 |
| `logs/{mvp_scraper,doc_worker,refresh_priority}.py` | gitignore 대상 로컬 사본. 파일 삭제는 승인 영역. 기존 상한 검사 + RunLock 검사가 감시 중 |
| `subscriptions.get_active_subscription()` | 제품 caller 0. 그러나 `registry.get_entitled_subscription()` 과 판정이 일치함을 코드로 확인했고, `test_subscription_policy.py` 가 이미 태운다. 삭제는 이득 없이 위험만 |

---

## 4. 실데이터 검증 (전부 `mode=ro`)

```
auction 2,834 / auction_item 2,834 / auction_case 2,078 / auction_image 1,946
document_queue 8,182 / document_status 8,910 / doc_raw 1,285 / rights_summary 551

identity 중복 (case_id,item_no)            0
identity 중복 (court_code,case_no)         0
(case_no,item_no) 중복 15건                 전부 **다른 법원** — 정상(법원별 독립 채번)
FK 위반 (PRAGMA foreign_key_check)          0
orphan  favorites/document_status/doc_raw/auction_image/rights_summary/tenant_rights  전부 0

auction ↔ auction_item 값 대조 2,834행 × 13필드     drift 0     ← 쓰기 경로가 하나임을 실증
면적 백엔드(extract_areas) ↔ 프런트(parseArea) 2,834행
                       라벨 불일치 0 / 값 불일치 0 / 폴백 발동 0
```

### 병합사건 순서 갈라짐 — 재확인, 여전히 1건 (BLOCKED 유지)

```
상주지원 | 물건 1 | 조각 5개
  id=178    2024타경995 / 2024타경1417 / 2025타경5447 / 2025타경5476 / 2025타경5483
  id=8185   2024타경995 / 2024타경1417 / 2025타경5447 / 2025타경5483 / 2025타경5476
                                                          ^^^^^^^^ 순서만 다르다
```

`detect_merged_case_duplicates_dryrun.py` 로 재현했고 상한 검사(1건)가 지키고 있다.
근본 수정은 `case_no` 정규순서화 + **기존 638행 재키잉**이라 승인 영역이다.

---

## 5. 테스트

```
Python (개별)   test_api_regression / test_subscription_policy / test_pipeline_integrity
                test_schema_hygiene / test_document_status_sync / test_favorites_lifecycle
                test_doc_path_safety / test_doc_storage_atomicity / test_false_success
                test_queue_safety_invariants / test_identifier_contract / test_normalizer
                                                                          12/12 exit=0
Frontend        npx tsc --noEmit            exit=0
                npx eslint .                exit=0
                npm run build               exit=0
                tests/*.test.mjs 10개        전부 통과
                  └ frontend-contract 는 **서버를 실제로 띄워** 돌렸다
                    (uvicorn:8000 + next start:3000) → 66 pass / 0 fail / 1 skip
                    ※ "서버가 없어서 실패"를 환경 탓으로 넘기지 않고 실제로 채웠다
```

### mutation — 신설/수정 가드 7/7 검출

```
M1 repair 표를 손 사본 + status.htm 으로       → [FAIL] 보정 스크립트 파일명표 == 뷰어 서빙 파일명
M2 정본에 4번째 종류 추가                       → [FAIL] 3축 동시(정본/보정/자기검증)
M3 item_exists 를 다시 물건 모양 조립기로       → [FAIL] 3축(모양 조립 금지 / 조립기 1개 / SELECT 1)
M4 SQLite 범위 가드 제거                        → exit=1 (OverflowError 로 즉시 죽는다)
M5 충돌 사본에 정본 이력에 없는 줄 추가          → [FAIL] 정본 이력에 없는 내용을 가진 충돌 사본이 없다
M6 test_crawl_orchestration 의 락 격리 제거     → [FAIL] 3건(운영 락을 쥔 크롤이 도는 동안)
M7 그 검사가 운영 락 mtime 을 건드리게 함        → [FAIL] 이 검사가 운영 락 파일을 건드리지 않는다
전부 복원 후 재실행 → 전부 초록, git status 에 사본/락 변경 없음
```

---

## 6. 승인 필요 (BLOCKED — 손대지 않았다)

```
[1] 병합사건 순서 정규화 + 기존 638행 재키잉        DB 데이터 마이그레이션
[2] 충돌 사본 7개 `git rm --cached`                파일/추적 변경
    ★ 이번에 **"지워도 잃는 내용이 0"임을 기계로 확정**했다. 판단 근거는 더 이상 없지 않다.
[3] logs/ 사본 3개 삭제                            파일 삭제 (락 없는 실행 가능 판본)
[4] models/auction_item.has_status_pdf 정리        모델 시그니처 변경
```

---

## 6-A. 세션 중 추가로 고친 것 — 게이트가 거짓말하던 자리

전체 게이트를 돌렸더니 `test_crawl_orchestration.py` 만 3건 실패했다.
**환경 탓으로 넘기지 않고 원인을 끝까지 확인했다.**

```
증상   ★ main() 이 document_queue 적재를 호출한다   0 (expected 1)
       main() 이 넘긴 행 수                        0 (expected 2)
       ★ main() 실패 경로의 종료 코드              0 (expected 1)
로그   "다른 mvp_scraper.py 실행이 이미 진행 중으로 보임 - 이번 실행은 건너뜀"
실측   logs/mvp_scraper.lock 소유자 PID 11648 = **살아 있는 python**(03:00:01 시작)
확증   락 경로만 임시 파일로 돌려 같은 코드를 돌림 -> **ALL TESTS PASSED**
       (운영 락은 건드리지 않았고, 실행 중인 크롤도 그대로다)
```

즉 **제품은 옳게 동작했다**(락이 제 일을 했다). 붉어진 것은 검사 쪽이다 —
이 파일은 DB(#251)와 그날 CSV(#266)를 이미 격리하면서 **락만 운영 경로 그대로**였다.
이 저장소가 두 번 겪은 것과 같은 부류다: 검사가 자기 것이 아닌 공유 자원에 매달린다.

고친 것: `ms.LOCK_PATH` 를 스크래치로 돌리고 `finally` 에서 복원.
락 자체의 계약은 `test_checkpoint_atomicity.py`(RunLock)/`test_doc_worker_recovery.py`
가 보므로 여기서 갈아 끼워도 **잃는 검증이 없다**. 덧붙여 `_lock_state()` 앞뒤 비교로
**이 검사가 운영 락을 건드리지 않았음**을 스스로 단언하게 했다 — DB 오염 검사보다
이쪽이 더 위험하다(도는 크롤을 죽이거나, 죽은 크롤을 살아 있게 보이게 만든다).

**양쪽 상태에서 확인했다.** 크롤이 락을 쥐고 있는 동안 → 통과, 그 크롤이 끝나 락이
사라진 뒤에도 → 통과. 즉 격리가 "락이 있다"에도 "없다"에도 기대지 않는다.

## 7. 판정

**Frankenstein: 실제 결함 3건 수정 + 가드 4축 신설. 남은 것은 전부 승인 영역이다.**
승인 없이 고칠 수 있는 항목은 이 시점에 남아 있지 않다.

---

# 8. 야간 2부 — 경로/담김 규칙 통합과 **실제로 데이터를 망가뜨릴 뻔한 복구 스크립트**

1부가 사본 셋을 정리했다면, 2부는 지시대로 `get_doc_dir` 부터 끝까지 파고들어
**같은 계열의 결함 다섯 개**를 더 찾아 고쳤다. 그중 하나는 실행하면 운영 데이터가
실제로 뒤집히는 것이었다.

## 8-1. `get_doc_dir` — 세 구현의 계약이 이미 갈라져 있었다

세 구현을 입력 행렬로 직접 태워 비교했다(2026-09-04).

```
입력 (court, case, item)        doc_paths     api/documents   repair_document_status
(None, '2024타경1', '1')        TypeError     TypeError       <ROOT>/2024타경1/1   ★
```

셋째만 법원 조각에 `or ""` 를 붙여 두어, **예외 대신 한 단계 위 경로**를 돌려줬다.
그 경로는 DOCUMENT_ROOT **안**이라 담김 검사도 통과한다. 이 스크립트는 "그 경로에
파일이 있으면 `document_status` 를 READY 로" 바꾸므로, 없애려던 상태
(*화면은 수집완료, 뷰어는 404*)를 스스로 만들 수 있는 모양이었다.

**고친 것**: 규칙은 `crawler/doc_paths.py:_doc_dir_path()` 하나만 남기고 나머지 둘은
이름을 유지한 채 위임. 뿌리는 모듈이 정하도록 `root=` 인자를 열었다 —
`test_rights_data_load.py:Env` 가 `api.v1.documents.DOCUMENT_ROOT` 만 갈아 끼워
격리하기 때문이다(그 격리를 깨뜨렸다가 테스트가 잡아 줘서 되돌렸다).

실데이터 2,873행 × 3구현 대조: 불일치 0.

## 8-2. ★ 방어가 **거꾸로** 걸려 있었다 — 읽기는 막고 쓰기는 안 막았다

`sanitize_path_segment()` 를 지나는 것은 사건번호와 물건번호 **둘뿐**이고
**법원 조각은 원문 그대로** `os.path.join()` 에 들어간다. 실측:

```
_doc_dir_path('..',            '2024타경1','1') -> <저장소>/2024타경1/1
_doc_dir_path('../../Windows', '2024타경1','1') -> <바탕화면>/Windows/2024타경1/1
_doc_dir_path('D:',            '2024타경1','1') -> D: 드라이브로 튄다
```

읽는 쪽은 전부 막혀 있었다(서빙 2곳 + 보정 판정 1곳이 `realpath`+`commonpath`).
**디스크를 실제로 바꾸는 쪽에만 그 검사가 없었다** — `doc_paths.get_doc_dir()` 과
`image_assets.ensure_image_dir()` 둘 다. 사진 쪽은 **삭제**에는 이미 봉쇄가 있었고
(Sprint 192/BUGS #131) 그 주석이 *"읽기보다 쓰기/삭제가 더 위험한데 방어는 읽기에만
있었던 셈"* 이라고 적어 두었는데, **만드는 쪽**이 남아 있었다.

변이(M8)로 가드를 지우고 돌리니 실제로 이런 디렉터리가 생겼다:

```
C:\etc\2099타경QA\1        <바탕화면>\Windows\2099타경QA\1        <저장소>\2099타경QA\1
```

**고친 것**: 두 생성 함수에 담김 가드. 경로 계산은 **한 글자도 바꾸지 않았다** —
법원 조각을 치환하면 이미 저장된 문서의 경로가 달라질 수 있고 `"D:"` 는 어차피
치환으로 막히지 않는다. 담김만 보면 정상 입력의 경로는 그대로다.
실데이터 법원 값 60종(4개 테이블 전수)에 위험 문자 0건 — 정상 동작 무변경.

격리 이동(`repair_empty_status_capture.py` 의 `shutil.move`)에도 같은 가드를 걸었다.
`relpath()` 는 대상이 기준 밖이면 `..` 로 시작하는 값을 주고, 그것을 이어 붙이면
**격리 폴더 밖으로 파일을 옮긴다**(되돌리기 어려운 동작이다).

## 8-3. 여기서 내가 Frankenstein 을 만들었다 (그리고 가드가 잡았다)

문서 쓰기 가드를 만들면서 `doc_paths` 에 담김 함수를 새로 적었다. 그런데
`image_assets.is_inside_document_root()` 가 **이미 같은 규칙**이었다(Sprint 192).
규칙의 두 번째 판본을 만든 것이다.

`test_schema_hygiene.py` 의 중복 심볼 검사가 그 다음 게이트에서 붉어졌다:

```
[FAIL] 새로 생긴 중복 심볼 없음: ['is_inside_document_root']
```

그 검사의 지시문대로 처리했다 — 규칙은 `doc_paths` 하나로 합치고, 사진 쪽은
**뿌리만 바인딩하는 위임**으로 남겼다(`def` 를 지울 수 없는 이유: 뿌리를 호출
시점에 읽어야 한다. `partial` 로 묶으면 모듈별 뿌리 교체 격리가 조용히 죽는다 —
`audit_asset_integrity.py` 가 경고해 둔 함정이다). 그 뒤에 사유와 계약 검사를
함께 만들어 허용목록에 넣었다.

## 8-4. ★★ 실제 defect — 복구 스크립트가 **확인된 답을 실패로 뒤집을** 참이었다

`repair_unsupported_status_docs.py` 를 운영 DB **스냅샷**에 태웠다(읽기 전용).

```
FAILED 로 바꿀 대상 12행  <- **전부 doc_type='IMAGE'**
  그중 status='NO_IMAGE'  3행   (item_id 13553 / 13624 / 13827)
```

두 결함이 겹쳐 있었다.

**(1) 사진이 통째로 흘러들었다.** 이 스크립트의 전제는 *"수집 버튼 id 를 몰라서 못
받는 문서"* 다. 그런데 `get_doc_button_id()` 가 None 을 주는 이유는 둘인데
(버튼 id 를 모른다 / 버튼이라는 개념이 없다) 루프가 구별하지 않았다. 사진이 후자다.
Sprint 144 가 `IMAGE` 를 `document_status` 와 `QUEUE_TO_DOC_STATUS_TYPE` 에 넣는
순간 조용히 대상이 됐다 — **이 파일 상단이 "대상이 0건이 됐다, 설계가 의도대로
동작한 사례다" 라고 적어 둔 뒤에** 벌어진 일이다. 어휘가 늘어난 것을 아무도
이 스크립트에 알려 주지 않았다.

**(2) 덮지 않을 상태를 손으로 적었다.** `== "READY"` 였는데 정본은
`storage/database.py:DOC_STATUS_HAS_ARTIFACT`(READY + **NO_IMAGE**)이고
`mark_queue_failed()` 는 이미 그것을 쓴다. `NO_IMAGE` 는 실패가 아니라
*"법원이 사진을 제공하지 않는다"* 는 **확인된 답**이다(재시도해도 같다).

`--apply` 했다면 3행이 `NO_IMAGE -> FAILED` 가 되어 화면은 "수집실패"가 되고
큐는 영원히 다시 시도했을 것이다. 나머지 9행(COLLECTING)도 아직 큐에 있는 사진을
미리 실패로 못박는다.

**고친 것**: `config/settings.py` 가 `_BASE_BTN_ID` 에서 유도한
`DOC_BUTTON_DOC_TYPES` 를 내보내고, 스크립트는 그 집합에 없는 종류를 건너뛴다.
상태 비교는 `DOC_STATUS_HAS_ARTIFACT` 로 바꿨다. 수정 후 같은 스냅샷에서
**대상 0행** — 그 파일의 docstring 이 주장하던 상태로 되돌아왔다.

## 8-5. 낡은 소스 리터럴 검사 하나 (테스트 결함)

`test_pipeline_integrity.py` 가 `'(item_no or "1")' in src` 로 **문자열**을 찾고
있었다. 규칙을 정본으로 모으자 그 리터럴이 `documents.py` 에서 사라져 붉어졌다 —
**규칙이 좋아졌다는 이유로 실패**한 것이다. 바로 위 주석(Sprint 146)이 이미 같은
문제를 겪고 *"리터럴이 아니라 결과를 대조하라"* 고 적어 두었는데 두 개가 남아 있었다.

값으로 단언하도록 바꿨다(약화가 아니라 강화 — 변이 M13 이 옛 검사로는 못 잡을
"기본값이 `_` 가 되는" 회귀를 잡는다).

## 8-6. 이번 세션 mutation (8건, 전부 검출)

```
M8  문서 쓰기 담김 가드 제거        -> 8건 실패 + 실제 탈출 경로를 이름으로 출력
M9  repair 의 `or ""` 부활          -> 세 구현 답 불일치로 검출
M10 사진 쓰기 담김 가드 제거        -> 4건 실패(소스 + 행위 + syscall 도달 + 공허검사)
M11 사진 봉쇄를 규칙 사본으로 되돌림 -> 위임 계약 검사가 검출
M12 documents.py 가 규칙을 다시 적음 -> 위임 계약 검사가 검출
M13 item_no 기본값 제거             -> 값 검사 3건이 검출('1' -> '_')
M14 사진 제외 규칙 제거             -> IMAGE 가 대상에 나타나 검출
M15 DOC_STATUS_HAS_ARTIFACT -> "READY" -> **처음엔 살아남았다**(아래)
```

★ **M15 가 처음에 살아남은 것이 이번 세션에서 가장 중요한 순간이다.**
(1)번 수정이 사진을 먼저 걸러 내므로 상태 분기에 도달하는 행이 없어, (2)번에 대한
내 검사가 **공허**했다. 버튼을 가진 종류가 "버튼 id 미확보" 가 되는 상황을 만들어
상태 분기를 직접 태우도록 고친 뒤에야 M15 가 잡혔다.
*변이를 돌리지 않았으면 초록인 채로 아무것도 지키지 않는 검사가 남았을 것이다.*

## 8-7. 검사 자체의 결함도 고쳤다

- 탈출 검사가 **붉어질 때 저장소 밖에 디렉터리를 남겼다**(M8 에서 `C:\etc` 등).
  실패한 검사가 파일시스템을 어지르면 안 된다 — `rmdir` 만 쓰는 좁은 뒷정리를 넣었다.
- 사진 검사가 `D:` 에서 `FileNotFoundError` 로 **통째로 중단**돼 뒤 항목이 아예
  안 돌았다. OSError 도 "가드가 syscall 까지 갔다"로 잡아 이름을 대고 실패하게 했다
  (OS 가 우연히 막아 준 것을 안전하다고 읽으면 안 된다).
- 새로 만든 검사의 fixture 가 `UNIQUE(item_id, doc_type)` 때문에 5행 -> 2행으로
  접혔다. **"검사가 공허하지 않다"** 항목이 그것을 잡아 줬다.

## 8-8. 거짓 양성 (조사했고 결함이 아니다)

```
storage/database.py 의 상태 리터럴 3곳   각각 다른 질문을 한다(주석이 근거를 갖고 있다).
                                        1081 은 "볼 수 있는 파일이 있나"라 READY 가 맞다.
api/v1/item.py 의 READY 리터럴 2곳       NO_IMAGE/FAILED 를 그대로 통과시키는 것이 의도다.
repair_document_status.py:159 `== READY` IMAGE 는 파일명표에 없어 도달 불가(NO_IMAGE 는 IMAGE 전용).
VALID_PAYMENT_TYPES x2                  둘 다 `PaymentType` enum 에서 유도 - 갈라질 수 없다.
LOCK_STALE_HOURS 5 vs 6                 doc_worker / mvp_scraper 의 별개 정책값.
DOCUMENT_ROOT x4 / PROJECT_ROOT x6      모듈별 뿌리(격리에 필요). 같은 곳을 가리키는지는 검사가 대조.
audit_asset_integrity 의 UPDATE         전부 `sqlite3.connect(scratch)` — selftest 사본이다.
crawler/doc_crawler 의 makedirs 3곳      전부 고정 상수 `DOWNLOAD_DIR`. DB 값 아님.
제품 caller 없는 함수 9개                이번 변경으로 늘지도 줄지도 않았다.
```

