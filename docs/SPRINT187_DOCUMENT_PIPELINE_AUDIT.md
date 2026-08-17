# Sprint 187 — 문서 파이프라인 전수 추적 + 매일 갱신 체인 감사

Status: 코드 결함 2건 수정 + 운영 환경 실측 2건(둘 다 승인 필요) / 회귀 3건 신설
Date: 2026-08-17
Scope: Sprint 186(이미지)과 같은 깊이로 **문서**(명세서/현황조사서/감정평가서)를
법원 원천부터 상세페이지까지 실제 호출부·저장 결과까지 추적. 목표(goal)의 4대 축
(물건 기본정보 / 사진 / 문서 / 매일 스케줄러) 전체를 실측으로 확인.

---

## 0. 한 줄 요약

문서의 **변경 감지 기계**(previous_hash/new_hash → document_version_log)는 이미
정상이었다 — 이미지가 Sprint 186 전까지 빠뜨렸던 계산을 문서는 처음부터 하고 있었다.
이번에 찾은 결함은 한 단계 더 안쪽, **`doc_raw`의 버전 번호**(BUGS #115)와
**PDF 내용 검증 부재**(BUGS #116)였다. 그리고 코드 감사보다 더 큰 소득은 운영
환경을 직접 두드려서 나왔다 — **이 환경의 API가 지금 전면 500이고(BUGS #117),
그 밑에는 "사진/문서 자동 수집이 애초에 스케줄러에 등록된 적이 없다"는 더 큰
사실이 있다.** 둘 다 코드로 고칠 수 없는 승인 영역이지만, 코드 쪽 준비(마이그레이션
파일, 스케줄러 등록 스크립트, doc_worker 하드닝)는 전부 이미 끝나 있다 — 실행 두
줄만 승인되면 된다.

---

## 1. 문서 파이프라인 전수 추적 (법원 원천 → 상세페이지)

goal이 요구한 사슬을 실제 코드로 훑었다.

```
법원 원천 페이지
  -> crawler/base_crawler.py:go_to_case_detail()          (사건 상세 진입)
  -> crawler/doc_crawler.py:collect_document()             (doc_type별 디스패처)
       collect_spec()      매각물건명세서 - 새 탭 -> 파일저장 버튼 -> PDF
       collect_status()    현황조사서    - 오버레이 -> html+json 추출
       collect_appraisal() 감정평가서    - 오버레이 -> iframe -> PDF URL -> 새 탭 다운로드
  -> doc_worker.py                                          (claim -> collect_document -> 판정)
       result["success"] True  -> mark_queue_done()
       result["success"] False -> mark_queue_failed()
  -> storage/database.py:mark_queue_done()                  (하나의 트랜잭션)
       document_queue.status = 'done'
       _set_document_status()    -> document_status (화면이 읽는 테이블)
       _record_doc_raw()         -> doc_raw (파일 실체 - 크기/해시/쪽수/버전)
       document_version_log 조건부 INSERT (previous_hash != new_hash)
  -> api/v1/item.py                                         (document_status + doc_raw MAX(doc_version) JOIN)
  -> src/app/properties/[id]/page.tsx                       (문서 목록 -> 뷰어/다운로드)
```

각 화살표를 실제로 열어 확인했다(추측 없음, 아래 §2/§3에 근거).

### 기존에 이미 정상이던 것

```
변경 감지 계산      collect_spec/status/appraisal 전부 previous_hash(기존 dest_path 해시) ->
                    new_hash(다운로드분 해시)를 계산해 mark_queue_done에 넘긴다
                    (crawler/doc_crawler.py:220, :373, :499 — 셋 다 동일 패턴)
document_version_log  previous_hash != new_hash 일 때만 INSERT (Sprint 78 §8, 그대로 유지)
0바이트 방어         wait_for_download()가 size<=0인 새 파일은 후보에서 제외
                    (`test_wait_for_download_completion_rules`가 고정)
빈 캡처 방어         collect_status()는 저장 직전에 status_overlay_has_data()로
                    한 번 더 확인한다(Sprint 62) — 오버레이 골격만 채워진 빈 캡처를
                    저장하지 않는다
경로 원자성         html_tmp/json_tmp -> os.replace() (Sprint 40) — 쓰기 도중 죽어도
                    잘린 파일이 목적지에 남지 않는다
doc_exists 스킵     기존 파일이 있고 overwrite=False면 스킵 (의도된 동작, 재수집
                    정책이 정해지면 overwrite=True 배선은 이미 돼 있다)
```

---

## 2. 이번에 고친 결함 2건

### BUGS #115 — `doc_raw.doc_version`이 내용 무관하게 재수집마다 증가

`document_version_log`는 `previous_hash != new_hash`로 이미 개정만 골라 기록하는데,
**같은 함수(`mark_queue_done`)가 여는 같은 트랜잭션**에서 `_record_doc_raw()`가 쓰는
`doc_raw.doc_version`은 그 판단이 전혀 없이 매번 `MAX(doc_version)+1`을 무조건
삽입했다. `api/v1/item.py`가 이 값을 그대로 사용자 응답(`doc_version` 필드)에 싣는다.

재수집 트리거(`overwrite=True`)는 지금 아무도 넘기지 않아(§4 참고) 이 결함은
**아직 도달하지 않았다** — 딱 이미지의 BUGS #113/#114와 같은 모양이다. "재수집을
켜는 순간 도달하는 경로"를 미리 막았다.

수정: `_record_doc_raw()`가 삽입 전에 직전 `doc_raw` 행의 `file_hash`와 지금 저장할
파일의 sha256을 직접 비교해, 같으면 새 행을 만들지 않는다. `mark_queue_done()`에
넘어오는 `previous_hash`/`new_hash` 인자에 기대지 않고 자기 손으로 다시 계산한
이유는, 그 인자들이 doc_type마다 크롤러가 따로 계산해 넘기는 값이라 `doc_raw`의
대표 파일(예: status는 html+json 중 json)과 항상 같은 파일을 가리킨다는 보장이
없기 때문이다.

상세: `docs/BUGS.md` #115.

### BUGS #116 — spec/appraisal PDF가 내용 검증 없이 저장됨

`wait_for_download()`는 "크기 > 0 + 두 번 연속 같은 크기"만 본다 — **내용이
실제로 PDF인지는 보지 않는다.** 법원 서버가 오류 페이지(HTML)를
`Content-Type: application/pdf`로 잘못 내려주거나 다운로드가 중간에 끊기면, 그
파일도 이 조건은 통과해 그대로 목적지에 저장되고 READY로 표시될 수 있는 구조였다.

이미지 파이프라인은 선언된 MIME을 믿지 않고 매직 바이트로 판정한다
(`crawler/image_assets.py:sniff_image_ext`) — 문서 쪽에는 같은 수준의 방어가 없었다.
`collect_documents.py`(스케줄러가 부르지 않는 죽은 스크립트)의 0바이트 방어(BUGS #65)와
혼동하면 안 된다 — 실제 운영 경로(`doc_worker.py -> crawler/doc_crawler.py`)에는
이 검증이 아예 없었다.

수정: `_looks_like_pdf()` 신설(파일 앞 1024바이트 안에 `%PDF-`가 있는지 — PDF 표준이
허용하는 한도). `collect_spec()`/`collect_appraisal()`이 다운로드 직후, 이동 전에
이 판정을 거친다. 실패하면 저장하지 않고 다운로드 폴더의 가짜 파일도 지운다.

상세: `docs/BUGS.md` #116.

---

## 3. 시나리오 A~G 검증 (goal이 요구한 항목)

| 시나리오 | 상태 | 근거 |
|---|---|---|
| A. 기존 문서 없음 → 신규 수집 → 정상 저장 | 정상 | `test_mark_queue_done_records_doc_raw` §12 |
| B. 기존 문서 있음 + 동일 문서 → 재수집 → 변경 없음 → version 증가 없음 | **이번에 신설/수정** | `test_doc_raw_version_does_not_bump_on_unchanged_content`(신규) — Sprint 187 이전엔 검사 자체가 없었다(BUGS #115) |
| C. 기존 문서 있음 + 실제 변경 → 재수집 → 변경 감지 → 새 파일 저장 → version log 생성 | 정상 | `document_version_log`는 원래부터 정상(§1). `doc_raw` 버전 증가는 위 신규 검사의 시나리오 C로 함께 고정 |
| D. 부분 다운로드 → 기존 정상 문서 유지 | 문서에는 해당 없음(설계상) | spec/appraisal은 파일 1개, status는 html 저장 후 json 실패 시 `partial=True`로 html만 성공 처리(json은 재시도 큐에 남지 않음 — 기존 동작, 이번 감사에서 결함 아님으로 확인). "부분 수집이 기존 파일을 지운다"는 이미지 전용 결함(BUGS #114)이었다 — 문서는 애초에 다건 삭제 로직이 없다 |
| E. 다운로드 실패 → 기존 정상 문서 유지 | 정상 | 실패 시 `return result`(success=False)뿐, 목적지 파일에 손대지 않음. 이번에 추가한 PDF 내용 검증(BUGS #116)도 실패 시 기존 파일을 그대로 둔다 |
| F. 법원에서 문서가 실제로 사라짐 vs 수집 실패 구분 | **미확정 — 추측 보류** | 이미지는 `NO_IMAGE`로 이 둘을 구분하지만(법원이 사진을 제공하지 않는 것이 정상적으로 흔함), 매각물건명세서/현황조사서/감정평가서 3종은 한국 경매 절차상 법원이 항상 작성하는 법정 서류라 "원래 없음"이 정상 상태인지 근거를 찾지 못했다. 추측으로 `NO_DOCUMENT` 상태를 만들지 않았다 — 실제 그런 사례가 관측되면 그때 다룰 것 |
| G. 법원 문서 교체 → 상세페이지에 최신 문서 노출 | 코드상 정상, **운영 미검증** | `api/v1/item.py`가 MAX(doc_version) 행만 노출하고 storage_path는 canonical 경로(항상 같은 파일명)이므로 교체되면 최신이 자동으로 보인다. 실제 브라우저 확인은 §5의 이유로 이번엔 불가능했다 |

---

## 4. 문서 재수집 트리거 (승인 영역, 기존 정책 그대로)

문서도 이미지와 같다 — 기계는 완성돼 있고 **아무도 `overwrite=True`를 넘기지 않는다.**
이것은 새 발견이 아니라 Sprint 144/145/147이 이미 규명하고 `docs/roadmap.md`
"[결정 대기] 문서 재수집 정책" 절에 선택지(A 기일 임박 강제재수집 / B 해시비교 /
C 현행유지)와 비용 실측(전면 45.9시간 vs 표적)까지 정리돼 있다. 이번 감사는 그
결론이 여전히 유효함을 재확인했을 뿐, 정책 자체는 제품 판단이라 SKIP한다.

---

## 5. ★★ 가장 큰 발견 — 운영 환경을 직접 두드려서 나온 것

코드 감사만으로는 안 보이는 것이 있어서, `api_server.py`를 실제로 띄우고 `curl`로
검색/상세 API를 직접 호출했다(goal의 "실제 브라우저/E2E로 확인" 요구에 대한 대응 —
브라우저까지는 아래 이유로 못 갔지만 최소한 API 계층은 실제로 두드렸다).

```
GET /api/v1/search?limit=3   -> 500  {"detail":"검색 처리 중 오류가 발생했습니다"}
GET /api/v1/item/58          -> 500  Internal Server Error   (58 = 실제 존재하는 item id)
```

원인: 이 환경의 `auction.db`(gitignore 대상, 로컬 사본)에 **마이그레이션
020(`auction_image` 테이블)이 적용되지 않았다**(`migration_history` 마지막 기록이
019, 2026-08-13). `api/v1/search.py`/`api/v1/item.py`가 이 테이블을 try/except 없이
직접 조회해 API 전체가 죽는다. `test_schema_hygiene.py` §3이 이미 이 어긋남을 잡고
있었다 — 이번에 그 원인과 사용자 영향(전면 500)까지 실측으로 연결했다.

**그래서 브라우저 E2E를 하지 못했다.** API 자체가 죽어 있어 프런트가 뜬다 해도
모든 화면이 오류로 막힌다. 정직하게 "이번엔 검증 불가"로 남긴다 — 되는 척 보고하지
않는다.

### 더 근본적인 원인: 스케줄러가 절반만 서 있다

`Get-ScheduledTask`로 실제 등록 상태를 확인했다:

```
DOJOONPASS_DAILY   매일 03:00   run_daily.bat (mvp_scraper.py + migrate_execute.py)
                    -> 수동 등록으로 보임(register_scheduler_tasks.ps1이 쓰는 이름과 다름)
                    -> LastRunTime 2026-08-17 03:00:01, LastTaskResult 0 (정상)

run_doc_worker.bat(사진/문서 수집)       -> 등록된 작업 없음
run_priority_refresh.bat(우선순위 재계산) -> 등록된 작업 없음
```

즉 **"물건 기본정보"만 실제로 매일 갱신되고, 사진/문서는 자동으로 전혀 수집되지
않는다.** Sprint 144~186이 완성하고 검증한 이미지/문서 파이프라인 전체가 **트리거될
기회 자체가 없었다.** 실측이 이 결론과 정확히 맞아떨어진다:

```
doc_raw               0행
document_status        COLLECTING 6,180 / READY 555(과거 1회성 수동 실행분으로 추정) / FAILED 3
document_queue          pending 4,008행 (매일 enqueue_documents()로 계속 쌓이기만 하고 안 빠짐)
auction_image 테이블    존재하지 않음 (위 마이그레이션 문제와 별개로, 애초에 채워질 기회가 없었다)
```

`register_scheduler_tasks.ps1`을 그대로 `-Apply`하면 `run_daily.bat`을 06:00에 **또**
등록해 같은 배치가 하루 두 번(03:00 기존 + 06:00 신규) 도는 중복이 생긴다는 것도
이번에 발견했다 — 스크립트가 자기 이름(`DojoonPass-DailyCrawl`)으로만 기존 작업을
찾아서, 다른 이름(`DOJOONPASS_DAILY`)으로 등록된 것을 모른다. 스크립트에 기존 작업
자동 탐지+경고를 추가했다(자동으로 지우지는 않는다 — 남길지/정리할지는 실행하는
사람의 판단 영역이다).

---

## 6. 승인 필요 (SKIP) — 코드 준비는 전부 끝났다

```
1. python -m storage.migrations.run_migrations
   - DB 스키마 변경(auction_image 테이블 생성)이라 CLAUDE.md 규칙상 승인 필요
   - 새로 만드는 마이그레이션이 아니다 — storage/migrations/020_create_auction_image.sql은
     이미 존재하고 Sprint 144+가 코드로 전제하고 있다. idempotent, 001~020 중
     미적용분만 적용된다.
   - 적용 후 재확인: python test_schema_hygiene.py (§3 통과 여부)

2. .\register_scheduler_tasks.ps1           (계획 확인 - 기존 DOJOONPASS_DAILY 경고가 뜨는지)
   # DOJOONPASS_DAILY를 남길지 정리할지 판단 후:
   .\register_scheduler_tasks.ps1 -Apply
   - Windows Task Scheduler 등록이라 승인 필요
   - DocWorker(02:00)/PriorityRefresh(01:50) 두 작업이 새로 생긴다
   - DailyCrawl(06:00)은 기존 DOJOONPASS_DAILY(03:00)와 중복될 수 있다 — 위 경고 참고
```

이 두 가지만 승인되면, 이미 완성되고 회귀로 고정된 코드가 그대로 "물건 기본정보 +
사진 + 문서" 전체를 매일 자동으로 갱신하는 체인이 된다. **코드 쪽에서 추가로 할
일은 없다.**

---

## 7. 신규 회귀

```
test_asset_pipeline.py
  test_doc_raw_version_does_not_bump_on_unchanged_content   (신규, 시나리오 B/C 고정)
  test_mark_queue_done_records_doc_raw                      (기존 검사의 픽스처를
                                                              실제 내용 변경으로 수정 —
                                                              그러지 않았다면 이번 수정이
                                                              이 검사를 깼을 것)

test_doc_storage_atomicity.py
  test_looks_like_pdf_rejects_non_pdf_bytes                 (신규, 판정 함수 단위 5검사)
  test_collect_spec_refuses_non_pdf_download                (신규, collect_spec() 실제
                                                              호출 경로 — 가짜 PDF 거부 +
                                                              진짜 PDF 정상 저장 대조군)
```

관련 스위트 전체 재실행 결과 — 전부 PASS(회귀 없음):
`test_asset_pipeline.py` / `test_collect_documents.py` / `test_document_status_sync.py` /
`test_doc_storage_atomicity.py` / `test_doc_worker_recovery.py` / `test_race_conditions.py` /
`test_false_success.py` / `test_document_queue.py`.

(`test_schema_hygiene.py`는 §3에서 실패하는데, §5에서 설명한 운영 환경 실측과 같은
원인이고 이번 코드 변경과 무관함을 `git stash`로 격리해 확인했다 — 승인 후 마이그레이션을
적용하면 함께 해소된다.)

---

## 8. 이번 감사로 확인한 것 — SKIP 아님, "이미 맞음"

- 이미지에는 `NO_IMAGE`로 "법원이 안 줌"과 "실패"를 구분하는데, 문서 3종에 그런
  상태가 없는 것이 결함인지 §3 F행에서 검토했다 — 근거 부족으로 추측하지 않고 보류.
- `doc_exists()` 스킵 로직, `overwrite` 배선, 사건 단위 문서(현황조사서) 형제 재사용
  로직은 전부 기존 그대로 정상 동작을 재확인했다(코드 변경 없음).
- 프런트(`src/app/properties/[id]/page.tsx`)의 문서 목록은 COLLECTING 문서를 회색
  비활성 텍스트로만 보여주고 클릭 가능한 링크로 만들지 않는다 — "막다른 상태"가
  아니다(과거 결함을 이미 고쳐 둔 상태, Sprint 이력 주석 확인). `document_status`가
  물건마다 SPEC/STATUS/APPRAISAL 3행을 항상 미리 만들어 두므로(`migrate_execute.py`),
  "문서 목록이 통째로 비는" 상황은 실제로 발생하지 않는다.
