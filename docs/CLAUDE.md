너는 DojoonPass 프로젝트의 수석 개발자다.

## Project rules

프로젝트명
- DojoonPass (서비스명: 콕찰)

기술스택
- Frontend : Next.js
- Backend : FastAPI
- Database : SQLite (auction.db)
- Auth : Supabase Auth

원칙
- Breaking Change 금지
- 기존 API 유지 (응답 구조, 필드명, offset 페이지네이션 방식 포함)
- SQLite 유지
- itemId 단일 식별자 체계 유지
- Mock 함수 시그니처 유지
- 최소 변경 원칙 — 요청된 기능만 수정, 관련 없는 파일은 수정하지 않는다
- 기존 구조/코드 스타일을 먼저 분석하고 유지한다. 불필요한 포맷 변경 금지
- 추측하지 않는다. 모르면 질문한다
- 사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다
- 새 라이브러리 설치, .env 수정, DB 스키마 변경은 반드시 사용자 승인 후 진행한다
- 문제 해결 전 현재 구조를 분석하고 원인을 먼저 설명한 뒤 수정을 시작한다
- 투자점수 / AI 추천 / 수익률 계산 / 자동 투자판단 기능은 개발하지 않는다 (프로젝트 범위 밖, docs/decision-log.md 참조)

작업 완료 후 반드시 아래 순서대로 보고하고 멈춘다 (git add/commit/push 없이):

① Type Check
② Build
③ git status
④ git diff 요약
⑤ 변경 파일 목록
⑥ 변경 이유
⑦ 추천 Commit Message

절대 하지 말 것: 자동 `git add` / `git commit` / `git push` / merge / 대규모 리팩토링 / 승인 없는 파일 삭제. 사용자 승인을 받은 뒤에만 수행한다.

## Documentation

Before making architectural or implementation decisions, always consult the documents under `docs/`.

Priority:

1. docs/architecture.md
2. docs/decision-log.md
3. docs/roadmap.md
4. Relevant technical document (frontend.md / backend.md / crawler.md / search-engine.md)

Note (2026-08-07 정정): `docs/architecture.md`는 **저장소 안에 존재한다** — 이전 버전의 "docs/ 안에 없고 `C:\Users\Administrator\Desktop\architecture.md`를 봐야 한다"는 안내는 stale이었다(그 경로는 이 PC에 존재하지 않는 옛 사용자 프로필 경로다). `docs/architecture.md`를 그대로 참조하면 된다.

Each `docs/*.md` file has its own "절대 변경하면 안 되는 것" (do-not-change) and "알려진 문제점" (known issues) sections — read those before touching the corresponding area (frontend, backend, crawler, search). They are more current and detailed than anything summarized below; treat this file as the index, not a replacement.

One correction to keep in mind: `docs/search-engine.md`와 `docs/crawler.md`는 `storage/database.py`를 `.gitignore` 때문에 "저장소에 없다"고 서술한다. **두 서술 모두 지금은 사실이 아니다** (2026-08-13 Sprint 75 실측). Sprint 51의 `.gitignore` 정밀화 이후 이 파일은 git이 추적하고 있고, 작업 디렉터리에도 당연히 존재한다. 미확인 파일로 취급하거나 역추론하지 말고 그냥 읽으면 된다.

## Commands

### Frontend (Next.js)
```bash
npm run dev      # dev server (localhost:3000)
npm run build
npm run start
npm run lint      # eslint
```

### API server (Python/FastAPI)
```bash
python api_server.py
# or: uvicorn api_server:app --reload
# serves on 127.0.0.1:8000 (localhost-only), Swagger UI at /docs
```
2026-08-06 정정: `api_server.py`의 `if __name__ == "__main__":` 블록이 `uvicorn.run(..., host="127.0.0.1", ...)`으로 하드코딩되어 있음(`git log -p -- api_server.py` 확인 결과 커밋 `bfefbf7`(인증 도입 시점)에서 `0.0.0.0` → `127.0.0.1`로 이미 변경됨). `uvicorn api_server:app --reload` CLI 실행도 `--host` 미지정 시 uvicorn 자체 기본값이 `127.0.0.1`이라 결과는 동일. 이전 버전 문서의 "0.0.0.0:8000"은 stale — 자세한 내용은 `docs/backend.md` 참고.
2026-08-14 정정: **`requirements.txt`는 존재한다** — 2026-08-11 Sprint 54에 신설됐고 git이 추적한다. 이전 버전의 "No `requirements.txt` exists — dependencies are inferred from imports"는 stale이었다(그 서술을 믿고 import에서 의존성을 역추론하면 안 된다). 11개 패키지가 **전부 `==`로 고정**돼 있고, 2026-08-14 감사에서 선언 버전과 설치 버전이 11/11 일치하며 전부 import되는 것을 확인했다.

```bash
pip install -r requirements.txt
python -c "import selenium, pandas, pdfplumber, webdriver_manager; print('OK')"

# ★ 위 import 검사만으로는 부족하다 (2026-08-25, docs/BUGS.md #196).
#   패키지가 전부 import 돼도 **크롬 드라이버를 조달하지 못하면** 크롤은 못 돈다.
#   실제로 이 PC 에서 import 는 전부 OK 인데 드라이버 기동이 실패하고 있었고,
#   그 실패 메시지가 "Are you offline?" 이라 원인을 엉뚱한 데서 찾게 만들었다.
#   그래서 **진짜로 띄워 본다**(법원 사이트에는 접속하지 않는다):
python -c "import crawler.base_crawler as b; d=b.build_driver(); print('DRIVER OK', d.capabilities['browserVersion']); d.quit()"
```

`httpx`만은 **어떤 소스도 직접 import하지 않아** 안 쓰는 것처럼 보이지만 지우면 안 된다 — `fastapi.testclient.TestClient`가 내부에서 쓰므로 없으면 TestClient 기반 회귀가 통째로 실행되지 않는다(자세한 사유와 `httpx2` 전환 예고는 `requirements.txt`의 주석 참고). 새 패키지 설치는 여전히 승인 영역이다(위 프로젝트 규칙).

### Daily crawl pipeline (`run_daily.bat`, Task Scheduler job `DojoonPass-DailyCrawl`)
```bash
python mvp_scraper.py          # crawl all courts -> validate -> normalize -> upsert into `auction` table -> enqueue documents
python migrate_execute.py      # copies new `auction` rows into `auction_item` (the table the API actually serves)
```
Separately: `doc_worker.py` (~02:00, via `run_doc_worker.bat`) drains `document_queue` to download per-item PDFs/status docs. `refresh_priority.py` (~01:50, via `run_priority_refresh.bat`) recalculates queue priority as auction dates approach.

**2026-08-21 Sprint 247 실측 — 이 파이프라인은 지금 자동으로 돌지 않는다.**
작업 스케줄러 249개를 전수로 훑어 이 저장소를 가리키는 작업이 **0개**임을 확인했다.
`register_scheduler_tasks.ps1` 이 정의하는 세 작업(`DojoonPass-PriorityRefresh` 01:50 /
`DojoonPass-DocWorker` 02:00 / `DojoonPass-DailyCrawl` 06:00)이 **전부 미등록**이다.
**[2026-08-26 갱신] 이 문단은 더 이상 사실이 아니다** — PriorityRefresh/DocWorker 를
등록했다(DailyCrawl 은 기존 `DOJOONPASS_DAILY` 가 커버). 아래 "지금 사실인 상태" 절 참고.
그 결과가 지금의 Release Blocker다:

```
마지막 크롤            2026-08-12
auction_item           1,876행 (DB 는 비어 있지 않다)
기일이 남은 물건        0건  (가장 늦은 기일 2026-08-19, 오늘 2026-08-21)
기본 검색               total=0  /  include_closed=true 면 1,876
document_queue         pending 2,753 / done 559 / SKIPPED_EXPIRED 186
```

`doc_worker` 는 2026-08-21 08:59 에 한 번 돌았지만 **실행 창(~04:00)이 지나
브라우저를 띄우지 않고 즉시 종료**했다(설계대로다). 즉 "로그가 최근이다"를
"수집이 돌고 있다"로 읽으면 안 된다.

상태를 직접 재려면 `python audit_schedule_health.py` (읽기 전용, 아무것도 바꾸지 않는다).
등록은 **승인 영역**이라 에이전트가 임의로 하지 않는다.

**★★ 2026-08-25 — 머신 역할을 먼저 확인한다 (이 절이 아래 모든 실측 서술의 전제다)**

DOJOONPASS 는 머신을 역할로 나눈다.

```
데스크탑3 (이 저장소로 개발/QA 를 하는 머신)   개발 · 테스트 · Audit · QA · scratch DB 검증
                                              **운영 크롤링을 실행하지 않는다**
데스크탑1 (집)                                운영 Daily Crawl 담당
                                              운영 DB / 크롤링 데이터의 실제 기준점
```

그래서 개발 머신에서 아래를 보더라도 **그 자체를 운영 장애로 기록하지 않는다.**

```
Task Scheduler 등록 0개               크롤 머신이 아니므로 정상이다
auction_item MAX(crawl_date) 가 오래됨  이 머신이 마지막으로 수집한 날일 뿐이다
기일 미도래 물건 0건                    개발 DB 의 값이다. 제품 화면의 근거가 아니다
document_queue / doc_raw 가 운영과 다름  당연하다
```

**아래 "2026-08-25 재정정" 이후의 실측 서술은 전부 데스크탑3 개발 DB 기준이다.**
이 머신의 `auction.db` 가 개발 DB 라는 것은 실측으로 확정했다 — 사용자 테이블
(favorites / payments / subscriptions / registry_requests / audit_logs)이 **전부 0행**인데
`sqlite_sequence` 누적 id 는 수만이다(테스트가 만들었다 지운 흔적, BUGS #186).

운영 상태가 필요하면 셋을 **구분해서** 적는다 — (1) 이 머신의 로컬 상태,
(2) Git 에 기록된 코드/설정/문서, (3) 과거에 확보된 운영 로그/DB 측정 결과.
데스크탑3에서 확인할 수 없는 운영 상태는 **추측하지 않는다.**
데스크탑3에 운영 Scheduler 를 등록하거나 여기서 운영 크롤을 돌리지 않는다.

데이터 신선도를 제품 판정으로 쓰려면 그 머신이 스스로 선언해야 한다 —
`DOJOONPASS_DATA_ROLE=operational`. 미선언이면 `test_pipeline_integrity.py` §11 이
숫자만 찍고 실패로 만들지 않는다. 자세한 것은 `docs/BUGS.md` #200.

**2026-08-25 재정정 — 바로 위 "0개 등록"이 다시 사실이고, 그 사이에 있던 2026-08-24 야간
실측 블록은 전부 철회한다.** 2026-08-24 판에는 "예약 작업 1개(`\DOJOONPASS_DAILY`) 등록 /
auction_item 최신 수집일 2026-08-24 / 기일 남은 물건 291건 / migration_history 최신 019,
020 미적용 / `auction_image` 테이블 없음 / `doc_raw` 0행 / READY 555건 중 다수가 doc_raw
없음"이 적혀 있었다. **여덟 항목이 전부 이 저장소의 운영 DB와 일치하지 않는다.**
2026-08-25 08:20~08:30 재실측(전부 `file:...?mode=ro` 읽기 전용, `storage.database.DB_PATH` 경유):

```
                          2026-08-24 판 주장         2026-08-25 실측
예약 작업                  1개 \DOJOONPASS_DAILY     0개 (전체 478개 전수 스캔)
auction_item 최신 수집일   2026-08-24                2026-08-12  (MAX(crawl_date))
기일 남은 물건             291건 / 최종 09-02        0건 / 최종 2026-08-19
auction_item 총 행         2,376                     1,876
migration_history 최신     019 (020 미적용)          020_create_auction_image (08-17 적용)
auction_image             테이블 없음                있다, 45행
doc_raw                   0행                        556행
READY 중 doc_raw 없음      "다수"                    0건 (READY 556건 전부 뒷받침됨)
```

**오측의 출처를 찾았다.** `auction.db.backup_before_020_20260817_090319` 과
`.claude/worktrees/sprint95-false-success-audit/auction.db` 는 이후 둘 다 삭제됐다 —
당시 둘 다 **정확히 그 주장대로**였다: migration 019까지 / `auction_image` 없음 /
`doc_raw` 0행 / items 1,876 / queue 3,498 / document_status 5,628. 즉 그 세션은 운영 DB가
아니라 **pre-020 백업(또는 worktree 사본)을 잰 것으로 보인다.** 다만
"2,376행 / 291건 / 최종 09-02"는 이 PC의 DB 파일 18개 어느 것과도 일치하지 않아
**출처 확인 불가**로 남긴다.

### ★★★★ [2026-08-25 정정] 위 결론은 틀렸다 — 그 세션이 본 것은 **이 DB 가 맞았다**

바로 위 절은 "그 세션은 백업을 쟀다 / 감사기를 그냥 돌리면 이 오측은 일어나지 않는다"로
끝난다. 2026-08-25 에 `storage.database.DB_PATH`(= 저장소 루트 `auction.db`)를 **경유해서**
다시 쟀더니 그 "오측"이라던 값이 전부 사실이었다:

```
항목                     위 절이 "운영 DB" 라고 적은 값    2026-08-25 실측 (DB_PATH 경유)
-----------------------  -----------------------------  ------------------------------
migration_history 최신     020 (08-17 적용)               **019** — 020 이 없었다
auction_image             있다, 45행                     **테이블 자체가 없었다**
doc_raw                   556행                          **0행**
READY 중 doc_raw 없음      0건                            **555건**
```

즉 경로를 경유하느냐 여부의 문제가 아니었다. **020 은 이 DB 에 실제로 적용된 적이 없고,
`doc_raw` 도 실제로 비어 있었다.** 위 절이 "백업을 잰 탓"으로 돌린 것이 오히려 오진이다.

이 세션에서 둘 다 실제로 닫았다 — 020 적용(`CREATE TABLE IF NOT EXISTS` 뿐, 데이터 무변경)
+ `backfill_doc_raw.py --apply` 로 555행 백필. 자세한 것은 `docs/BUGS.md` #211.

**교훈 — DB를 잴 때는 반드시 `storage.database.DB_PATH`(= 저장소 루트의 `auction.db`)를
경유한다.** 루트에는 이름이 비슷한 백업이 16개 더 있어 손으로 열면 구별되지 않는다.
`audit_asset_integrity.py`/`audit_schedule_health.py` 는 둘 다 그 경유를 이미 하므로
**감사기를 그냥 돌리면 이 오측은 일어나지 않는다.** 자세한 것은 `docs/BUGS.md` #185.

**지금 사실인 상태(2026-08-25 실측):**

- ~~예약 작업 **0개**. 어느 것도 등록돼 있지 않다.~~
  **-> 2026-08-26 갱신: 이제 3개가 전부 등록돼 있다.**

```
\DOJOONPASS_DAILY            03:00  run_daily.bat        (이전부터 등록돼 있었다)
                                    마지막 2026-08-26 03:00:01 / 결과 0
DojoonPass-PriorityRefresh   01:50  run_priority_refresh.bat   <- 2026-08-26 등록
DojoonPass-DocWorker         02:00  run_doc_worker.bat         <- 2026-08-26 등록
```

  `DojoonPass-DailyCrawl`(06:00)은 **일부러 등록하지 않았다** — `DOJOONPASS_DAILY` 가
  이미 같은 `run_daily.bat` 을 03:00 에 돌리고 있어, 추가하면 같은 배치가 하루 두 번 돈다.
  `register_scheduler_tasks.ps1 -SkipCoveredByLegacy` 가 그 판정을 자동으로 한다.

  **★ 등록 전에 선행 조건을 실측했다** — selenium 4.47.0 / 크롬 드라이버 기동 OK
  (Chrome 151) / doc_worker import OK. 그리고 등록만 하고 끝내지 않고 **실제로 돌려**
  파이프라인 전체를 확인했다(13분, 문서 58건 + 사진 85장 수집). 자세한 것은 BUGS #215.

  **한계**: 이 작업들은 **로그온 상태에서만** 실행된다(비밀번호 없이 등록하는 방식).
  완전 로그아웃 운영이 필요하면 `-RunWhetherLoggedOn` 으로 재등록해야 하고
  그때는 자격 증명 입력이 필요하다.
  (2026-08-25 `register_scheduler_tasks.ps1` dry-run 통과 — 선행 조건 전부 OK,
   등록 대상 3개 전부 신규. 등록은 하지 않았다.)
- ★ **등록만으로는 안 됐다** — 2026-08-25 까지 이 PC 에서 수집 파이프라인이
  **브라우저를 못 띄웠다.** `crawler.base_crawler.build_driver()` 와
  `crawler.doc_crawler.build_download_driver()` 가 둘 다 1초 남짓 만에
  `ConnectionError: Could not reach host. Are you offline?` 로 죽었는데,
  **오프라인이 아니었다**(같은 호스트에 stdlib urllib 로 HTTP 200, 0.05초).
  `webdriver_manager` 가 쓰는 `requests` 경로의 CA 검증만 깨져 있었다.
  드라이버 해석을 `crawler.base_crawler.resolve_chrome_driver()` 한 곳으로 모으고
  Selenium Manager 폴백을 붙여 고쳤다 — 지금은 세 진입점 전부 1초 안에 기동한다.
  회귀: `test_schema_hygiene.py` 의
  `test_pipeline_resolves_chrome_driver_through_one_place()`. 자세한 것은 BUGS #196.
- ~~마지막 크롤 **2026-08-12**. 기일 남은 물건 **0건** — 기본 검색이 빈 화면이다.~~
  **-> 2026-08-25 23:00 재실측으로 갱신됐다.** 이 머신에서 크롤이 그날 실제로 돌았다:
  `MAX(crawl_date)` **2026-08-25**(262건), 기일 미도래 물건 **270건**,
  `GET /api/v1/search` **total 270 / 20.4ms / HTTP 200**. 즉 **빈 화면이 아니다.**
  그래서 `docs/BETA_RELEASE_CHECKLIST.md` 의 `P0A-VERDICT` 토큰은 지금 **RESOLVED** 다.
  `test_pipeline_integrity.py` 가 토큰과 실측을 **양방향으로** 대조하므로, 이 값은
  문서가 아니라 **그때그때의 DB** 를 따라간다 — 여기 적힌 숫자를 다음 세션이
  그대로 믿지 말고 **다시 재라.** (이 토큰은 이 머신의 드리프트 가드이지 운영 제품의
  판정이 아니다 — BUGS #200.)
- **그 다음 벽은 문서 공급이다** (2026-08-25 실측). 기본 검색에 보이는 270건 중
  **249건(92.2%)이 문서 전부 `COLLECTING`** 이고 사진이 있는 물건은 **0건**이다.
  검색·상세는 열리는데 열 것이 없다. 실제로 브라우저를 열어야 하는 물건은 270개뿐이라
  (큐 5,314행 중 4,275행은 기일 경과분이라 브라우저 없이 종결된다) **워커를 약 1.8일
  돌리면 따라잡는다.** 자세한 실측은 `docs/SPRINT255_REAL_DB_SCALE_AND_DOC_RAW.md`.
- `document_queue.last_attempt_at` 최댓값이 **2026-07-12** 에서 멈춰 있다(`enqueued_at`
  최댓값은 2026-08-12). DocWorker 가 큐를 만진 적이 없다는 뜻이고, pending 2,753건 중
  **2,750건(99.9%)은 기일이 이미 지나** 지금 수집해도 의미가 없다.
  `audit_schedule_health.py` 의 `queue_stall_signal()` 이 이 정체를 직접 판정한다.
- ~~자산 파이프라인 자체는 **정합**하다 — 어긋남 0건 (`auction_image` 45행,
  `doc_raw` 556행, READY 556건 중 doc_raw 없는 것 0건).~~
  **-> 이 서술은 사실이 아니었다 (2026-08-25 실측, BUGS #211).** 실제로는
  `auction_image` **테이블 자체가 없었고**(migration 020 미적용), `doc_raw` 는 **0행**,
  READY 555건 중 doc_raw 없는 것이 **555건**이었다. 즉 화면은 문서를 열 수 있는데
  **쪽수/크기/버전이 전부 null** 이라 뷰어가 페이지 이동 UI 를 그릴 수 없었다.
  `audit_asset_integrity.py` 어긋남 **581건**.
  이 세션에서 020 을 적용하고(`CREATE TABLE IF NOT EXISTS` 뿐, 데이터 무변경)
  `backfill_doc_raw.py --apply` 로 555행을 채웠다 — **어긋남 581 -> 26건**,
  그리고 감사기 [9] 가 처음으로 실제 검증됐다(**API 가 광고한 문서 URL 555개 / 열리지
  않음 0개**). 남은 26 = 재수집 대기 17 + downloads 고아 7 + 고아 디렉터리 1 + 1.
  고아 큐 행 18건은 별도(아래 감사기 참고).
- **감사기의 자기 검증이 공허했다** — `audit_asset_integrity.py --selftest` 가 결함을
  `SELECT ... FROM auction_image LIMIT 1` 로 심어서, **사진이 이미 수집돼 있어야만**
  검증이 성립했다(사진 수집은 데스크탑1 = 승인 영역이라 이 머신에서는 영원히 0행).
  `auction_item` 에서 씨앗을 가져오도록 고치고 "심을 물건이 있다" 단언을 세웠다.

**~~`run_daily.bat` 에 대한 관찰은 그대로 유효하다~~ -> 2026-08-26 에 고쳤다.**
이제 이 배치가 **맨 앞에서 `python -m storage.migrations.run_migrations` 를 부른다**
(실패하면 거기서 멈춘다 — 틀린 스키마에 크롤 데이터를 쓰는 것보다 안 쓰는 것이 낫다).
러너는 재실행에 안전하다. 아래 원문은 경위를 위해 남긴다.

**`run_daily.bat` 에 대한 관찰은 그대로 유효하다 — 이건 DB가 아니라 코드를 읽어 확인했다.**
`mvp_scraper.py`(→ `init_db()`, 레거시 3테이블만)와 `migrate_execute.py` 만 부르고
**`storage.migrations.run_migrations` 는 어디서도 부르지 않는다.** 즉 migration 은 이 배치로
자동 적용되지 않는다 — 지금까지 001번부터 020번까지 적용된 것은 그 사이 사람이 수동으로
러너를 돌렸기 때문이다(`migration_history` 타임스탬프가 매일 규칙적이지 않고 개발 세션
시각에 몰려 있는 것이 근거). 다만 **이 배치는 애초에 등록돼 있지 않아 지금은 돌지도 않는다** —
2026-08-24 판이 "매일 03:00 에 돈다"를 전제로 세운 위험 서술은 그 전제부터 성립하지 않는다.
migration 적용과 스케줄러 등록은 둘 다 승인 영역이라 이 세션도 손대지 않는다.

### DB schema setup (once, against a fresh `auction.db`, in order)
```bash
python -c "from storage.database import init_db; init_db()"   # creates the legacy auction, document_queue, document_version_log tables
python storage/migrate_v4_1.py                 # creates auction_case, auction_item, document_status, doc_raw, parsed_document, tenant_rights, rights_summary, rights_analysis_history
python -m storage.migrations.run_migrations     # applies numbered SQL files 001~025 (favorites, recent_items, search_presets, subscriptions, registry_usage, payments, registry_requests, indexes, payment_logs, registry_credits, audit/credit logs + soft-delete columns, document_collect_failures, document_queue UNIQUE+item_no, subscriptions.payment_id, auction_image, drop-duplicate-indexes, backfill-missing-indexes, align-drifted-constraints, auction_case-court_code-NOT-NULL, auction_item 면적 컬럼); tracked in `migration_history`, safe to re-run. Running it as a script (`python storage/migrations/run_migrations.py`) also works as of 2026-08-11 — before that only the `-m` form did.
```
2026-08-15 Sprint 122 정정: the `init_db()` step above is **required**, not optional. An earlier
version of this doc listed only the last two commands and said "부트스트랩은 위 두 명령만으로
완결된다" (bootstrap is complete with just these two) — that was wrong. Migrations 011/012 do
`FROM auction`/`DROP TABLE auction` against the **legacy** `auction` table, which only `init_db()`
creates; `migrate_v4_1.py` never touches it. Skipping `init_db()` and running only the last two
commands (i.e. following the old wording literally) applies migrations 001–010 and then dies at
011 with a bare `sqlite3.OperationalError: no such table: auction`, leaving `migration_history`
half-populated (measured 2026-08-15). `storage/migrations/run_migrations.py`'s own preflight
check now catches this and prints the same 3-step sequence as its stop message — but the doc
itself should say it correctly the first time. `test_bootstrap.py` (`test_full_bootstrap_from_scratch`,
`test_runner_refuses_without_prerequisites`) exercises this exact sequence.
(2026-08-11 Sprint 53: `storage/migrate_doc_collect.py`는 Migration 017로 대체되어 제거됐다.)

`storage/database.py`'s `init_db()` only creates the legacy `auction` + `document_queue` + `document_version_log` tables (idempotent, runs automatically on every `mvp_scraper.py`/`doc_worker.py` invocation) — it does **not** create the v4.1 tables above.

### Tests
**Run the whole Python suite with `python run_python_tests.py`** (added 2026-08-17, Sprint 146; `-k <substr>` filters, `-v` shows failing output). There is still no pytest config — each root-level `test_*.py` is a standalone script you can also run directly (`python test_api_regression.py`) — but do not hand-roll a shell loop over them: the runner exists because two such loops misread the results, counting assertion-less scripts as passes. It judges by **exit code**, not by output wording, and reports `PASSED` / `FAILED` / `SKIPPED` / `NO-VERDICT` separately — **`SKIPPED` and `NO-VERDICT` are not passes.** See `docs/TEST_PLAN.md` for the full current list and coverage.

(2026-08-19 Sprint 217 correction: this paragraph used to open with "No test runner is configured", which stayed true-sounding long after `run_python_tests.py` landed.) `test_db.py`/`test_docs.py`/`test_docs2.py` are the exception: they drive Selenium against the live `courtauction.go.kr` and are not meant to be run as part of routine regression (real network calls). As of 2026-08-11 this is **enforced**, not just documented — they exit immediately with `[SKIPPED]` unless `ALLOW_LIVE_CRAWL=1` is set (docs/BUGS.md #51). The many `step*.py`, `check_*.py`, `patch_*.py` files are one-off investigation scripts from past debugging sessions, not a suite — and are gitignored (see below), so don't assume one is current, load-bearing code just because it's on disk.

## Architecture

Quick orientation map — see the matching `docs/*.md` for depth and the current do-not-change / known-issues lists.

- **Crawler** (`crawler/`, `mvp_scraper.py`, `doc_worker.py`): Selenium against `courtauction.go.kr`. `mvp_scraper.py` (06:00) collects listings -> `validator/validation_engine.py` (PASS/FAIL + `logs/validation.jsonl`) -> `normalizer/normalizer.py` (address/price/date parsing) -> `storage/database.py` upserts into the legacy `auction` table and enqueues `document_queue` rows. `doc_worker.py` (02:00) later claims queue rows and drives `crawler/doc_crawler.py` to download per-item documents.
- **Two SQLite schema generations** — know which one you're touching: the legacy `auction` table (crawler's write target, unchanged/do-not-modify per docs/backend.md) vs. the normalized v4.1 schema (`auction_case`/`auction_item`/`document_status`/... created by `storage/migrate_v4_1.py`). `migrate_execute.py` is the one-way sync from `auction` -> `auction_item`. **All `api/v1/*` routes read from the v4.1 tables, not `auction`** — if new crawl data isn't showing up via the API, check whether `migrate_execute.py` has run.
- **API** (`api_server.py` + `api/v1/*.py`): each file is a self-contained `APIRouter` (search, item, doc_stats, favorites, recent_items, search_presets, registry), no service/repository layer — routers query SQLite directly via `storage/database.py`'s `get_connection()`. `api/auth.py` verifies Supabase JWTs (`SUPABASE_JWT_SECRET`, HS256, `sub` claim = user_id) and provides the `{"success", "data", "message"}` envelope used by auth-required routes (search/item do not use this envelope). `filter/` (filter_engine.py/scoring_engine.py/report_generator.py) is an earlier standalone module querying the legacy `auction` table directly — it is not wired into `api_server.py` and is effectively dead code. **Measured 2026-08-13 (Sprint 78): `test_filter.py` only exercises `filter_engine.py` (80%); `scoring_engine.py` and `report_generator.py` are at 0% — nothing in the repo runs them** (the earlier wording "exercised only by test_filter.py" over-claimed coverage for the latter two). `report_generator.py` imports `get_top20` from `scoring_engine.py`, so the two form an isolated pair with no other callers. Deleting them is approval-gated (dead-code removal); do **not** add tests for them either — testing code nobody runs buys nothing. If they are ever wired in, that wiring is the moment to add tests. **2026-08-18 Sprint 213 정밀화**: 그 80%는 **실행률이지 검증이 아니다** — `test_filter.py`는 55줄짜리 출력 스크립트로 단언이 하나도 없고, 회귀 실행기에서 `NO-VERDICT`(종료코드 0인데 판정문 없음)로 분류된다. 즉 `filter/` 세 모듈은 **전부 검증되지 않은 상태**이며, 도달 여부만 다르다(engine 은 단언 없는 스크립트가 부르고, 나머지 둘은 아무도 안 부른다). 실행 경로 전수 조사로 재확인했다 — `run_*.bat`/`api_server.py`/추적 테스트에서 유도한 진입점 그래프에 세 모듈 다 없다.
- **Frontend** (`src/`): Next.js App Router. Supabase is used only for auth/session (`src/lib/supabaseClient.ts`, `src/lib/supabaseServer.ts`, `src/proxy.ts` gates `/properties/*` — renamed from `src/middleware.ts` in Sprint 50 to follow Next.js 16's `proxy` file convention; logic unchanged) — auction data always comes from the Python API, never queried from Supabase directly. 2026-08-24 Sprint 251 정정 ― `src/login/` 은 삭제됐다 ― 이전 판은 그것이 본품 `src/app/login/` 의 죽은 중복본으로 남아 있다고 적었다(2026-08-24 실측: src 아래는 app, components, lib, proxy.ts 네 개뿐). `docs/BETA_RELEASE_CHECKLIST.md` 가 2026-08-22 에 이미 해소로 적었는데 이 색인 문서만 갱신되지 않았다.

## Git / repo hygiene gotchas

- **`storage/`는 더 이상 통째로 무시되지 않는다** (2026-08-13 Sprint 75 실측 정정). 예전에는 `.gitignore`에 `storage/` 한 줄이 있어 크롤 데이터와 함께 `storage/database.py` / `storage/migrate_v4_1.py` / `storage/migrations/*.sql` 같은 **실동작 소스까지 통째로 빠졌다.** 2026-08-11 Sprint 51에 규칙이 정밀화되어 (`storage/*` + `!storage/*.py` + `!storage/migrations/*.sql`) 지금은 **23개 파일이 정상적으로 추적된다**(`git ls-files storage/`로 확인). 데이터 산출물만 무시된다. 이 문서의 예전 서술("today none of it is tracked")은 stale했고, 그대로 믿으면 `storage/` 변경이 커밋에 안 담긴다고 오판하게 된다.
- `.gitignore` also blanket-ignores `step*.py`, `patch_*.py`, `check_*.py`, `*.db`, `*.csv`, `*.log`, `logs/`, `downloads/`, `documents/` as scratch/output, even though some (e.g. `patch_registry.py`) look like recent working scripts.
- **경로 통합 완료 (2026-07-26)**: 과거에 `run_daily.bat`/`run_doc_worker.bat`/`run_priority_refresh.bat`가 존재하지 않는 `C:\Users\Administrator\Desktop\dojun-pass` 경로를 하드코딩하고 있었고, Task Scheduler(`LawAuctionDailyCrawl`, `PDF우선순위갱신`)도 같은 잘못된 경로를 가리켜 매일 실행이 실패하던 문제가 있었다. 지금은 모두 `Desktop\dojoonpass`(이 저장소의 실제 위치)로 통일했다. `.bat` 3개는 `cd /d %~dp0`(배치파일 자기 위치 기준)로 바꿔 절대경로 하드코딩을 없앴고, **Task Scheduler의 Execute 필드만 OS 제약상 절대경로를 유지**한다. `Desktop\기타\dojun-pass`(스키마가 다른 구버전 `auction.db` 보유)는 여전히 존재하지만 자동 실행 경로와는 무관하다.

  **2026-08-21 Sprint 247 정정 — 위 문단의 작업 이름은 stale 하고, 지금은 등록 자체가 없다.**
  `LawAuctionDailyCrawl` / `PDF우선순위갱신` 은 **옛 이름**이다. 현재 등록 스크립트
  (`register_scheduler_tasks.ps1`)가 쓰는 이름은 `DojoonPass-DailyCrawl` /
  `DojoonPass-DocWorker` / `DojoonPass-PriorityRefresh` 다. 그리고 실측 결과 **셋 다
  등록되어 있지 않다**(스케줄러 249개 중 이 저장소를 가리키는 작업 0개).
  옛 이름으로 스케줄러를 뒤지면 "없으니 문제없나 보다"로 오판하게 되므로 이름부터 맞춰야 한다.
  `test_schema_hygiene.py` 의 `test_claude_md_scheduler_claims_match_register_script()` 가
  이 문서와 등록 스크립트의 이름이 어긋나면 실패한다.
- Korean-language log/print output and comments are the norm throughout the Python codebase — match that style when touching these files.