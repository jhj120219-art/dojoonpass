# Sprint 239 — 검색/상세를 죽이지 않는 방향으로, 그리고 mutation이 내 첫 테스트를 잡았다

**날짜** 2026-08-21. 운영 DB / `.env` / 스케줄러 등록 **무변경**. DB 스키마 변경(migration
020 적용)과 데이터 백필(`backfill_doc_raw.py --apply`)은 둘 다 승인 영역이라 실행하지
않았다 — 상세 근거는 `docs/BUGS.md` #177 참고, 이 문서는 세션 진행 순서와 검증 과정만 남긴다.

---

## 0. 기준선 재확인

```
git HEAD e41575c (Sprint 238과 동일, 커밋 없음) / branch master / working tree에
  docs/BETA_RELEASE_CHECKLIST.md(수정) + docs/SPRINT238_*.md(신규, 미추적) 만 존재
auction_image 여전히 없음 / crawl_date 여전히 2026-08-18 / queue 5,062행(대기 4,318)
```
Sprint 238이 끝난 지 실시간으로 몇 분밖에 지나지 않아 데이터 상태는 그대로였다.
"이전 세션 숫자를 믿지 않는다" 원칙에 따라 다시 쟀고, 실제로 동일했다(허위로 다르다고
적지 않는다).

---

## 1. API 500 방어 — BUGS #177

전체 서술은 `docs/BUGS.md` #177에 있다. 요지:

- `fetch_thumbnail_seqs()`(검색 썸네일) / `item.py`(상세 사진 목록) / `images.py`(사진
  서빙) 세 곳이 `auction_image` 부재 시 `sqlite3.OperationalError`를 그대로 위로
  흘려보내고 있었다. `search.py`가 그 하나의 예외로 전체 검색 응답을 500으로 죽였다.
- 세 곳 모두 **narrow catch**(정확히 `"no such table: auction_image"`)로 "사진 없음"과
  같은 모양(`{}` / `[]` / 404)으로 되돌리게 고쳤다. 다른 `OperationalError`는 그대로
  재던진다 — 이 결손 하나만 흡수하고 다른 결함을 가리지 않기 위해서다.
- 진짜 `api_server.py` 프로세스 + curl로 재현·재확인: `/search` 500→200(total 124),
  `/item/1` 500→200(images: []), `/item/53` 200(READY 문서 실파일 다운로드 200 확인).
- `python run_python_tests.py` 37→45, `node --test` **137/137 PASS**(이전 96 실패 전부
  이 결손의 파급).

### ★ 내 첫 회귀 테스트가 공허했다 — mutation이 그것을 잡았다

`test_asset_pipeline.py`에 새 테스트를 추가하며 narrow-catch를 검증하려고 처음엔
`api.v1.search.fetch_thumbnail_seqs` 자체를 몽키패치로 바꿔치기했다. 그런데 그 자리에
실제로 `except sqlite3.OperationalError as e: raise` 를 지우는 mutation을 걸어 보니
**테스트가 계속 통과했다** — 함수 전체를 갈아치웠으니 진짜 코드의 분기를 한 줄도 지나지
않은 것이다. 이 저장소가 함정 목록에 적어 둔 "실제 함수가 호출되지 않는 가짜 테스트"를
이번 세션이 새로 쓴 코드에서 그대로 재현한 셈이다.

고친 방법: 함수를 바꿔치기하는 대신 **가짜 커넥션**(`.execute()`가 다른 테이블 결손을
던지는 스텁)을 진짜 `fetch_thumbnail_seqs()`에 그대로 넘겼다. 이러면 진짜 코드의
`if "no such table: auction_image" not in str(e): raise` 분기를 실제로 통과한다.

**세 파일 전부 mutation으로 재검증**(각각 try/except를 지우고 FAIL 확인 → 원복 →
PASS 확인, 이번 세션에서 직접 수행):

```
api/v1/thumbnails.py   try/except 제거 -> narrow-catch 검사 FAIL (잡힘)
api/v1/item.py         try/except 제거 -> 500 그대로 재현(raw traceback) (잡힘)
api/v1/images.py       try/except 제거 -> 500 그대로 재현(raw traceback) (잡힘)
```

---

## 2. doc_raw 백필 공백 — 재발, 미해결

`document_status` READY 555행인데 `doc_raw` 0행. **이미 Sprint 144가 겪은 것과 같은
증상**(그때도 파일과 상태는 맞는데 실체 메타데이터만 비어 있었다)이 이 로컬 DB에서
재발했다 — `backfill_doc_raw.py`가 바로 그 상황을 위해 이미 존재한다.

```
python backfill_doc_raw.py   (기본 dry-run)
  document_status READY   555
  이미 doc_raw에 있음      0
  기록 예정                555
  READY인데 파일 없음(문제) 0
```

안전성은 스크립트 자체 docstring이 이미 보증한다 — 파일 존재+비0바이트 확인 후에만
기록, 기존 행 불변, 삭제 없음, document_status/queue/파일 미변경. **DB 쓰기라 `--apply`는
실행하지 않았다.** 실제 영향은 §1에서 확인한 대로 제한적이다(문서 열람 정상, 페이지
이동 UI만 저하).

---

## 3. 스케줄러 — 재확인, 변동 없음

`DOJOONPASS_DAILY`의 `LastTaskResult`는 여전히 `0x800710E0`(권한 거부). `.\register_scheduler_tasks.ps1`을
인자 없이(dry-run) 다시 돌려 도구 자체로 재확인 — 배치 파일 3개 OK, PATH python 해석
OK, 머신 PATH 불가(SYSTEM 등록 금지 그대로), DojoonPass-DocWorker/PriorityRefresh
2개 모두 "신규"(미등록)로 나온다. `DOJOONPASS_DAILY`와의 중복 경고도 여전히 뜬다.
운영 등록/계정 변경은 승인 영역이라 하지 않았다.

---

## 4. item-level batching

`test_worker_batching.py`(268단언)/`test_worker_capacity.py`(22단언) 전 구간 정상
통과, 코드 대조도 Sprint 238에서 이미 끝냈다. §3의 스케줄러 상태가 그대로라 doc_worker가
자동 실행된 적이 여전히 없고, 실거래 처리량은 이번 세션도 **재측정 불가**(추정치를
실측처럼 쓰지 않는다).

---

## 5. 최종 테스트 상태

```
python run_python_tests.py   통과 45 | 실패 3 | 건너뜀 3 | 판정없음 1  (7,029 단언)
  남은 실패 3건: test_bootstrap.py / test_schema_hygiene.py (의도된 드리프트 가드,
                통과시키면 안 됨) / test_http_conditional.py (doc_raw도 비어 있어
                검사할 실사진·실문서 표본 자체가 없다 - §2가 풀리면 자연 회복)
node --test tests/*.test.mjs   137/137 PASS, 0 FAIL, 0 SKIP  (이전 최고 133/137)
tsc / eslint                   0 / 0
```

---

## 6. 다음 (전부 승인 필요)

```
1. migration 020 적용                검색은 이미 살아 있지만, 사진 자체가 나오려면 필요
2. backfill_doc_raw.py --apply       문서 뷰어 페이지 이동 UI 회복(555건, 안전 확인됨)
3. DOJOONPASS_DAILY 실행 계정 문제 해소
4. DocWorker/PriorityRefresh 스케줄러 등록
5. 1~4가 풀린 뒤 batching 실거래 재측정
```
