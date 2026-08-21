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

### DB schema setup (once, against a fresh `auction.db`, in order)
```bash
python -c "from storage.database import init_db; init_db()"   # creates the legacy auction, document_queue, document_version_log tables
python storage/migrate_v4_1.py                 # creates auction_case, auction_item, document_status, doc_raw, parsed_document, tenant_rights, rights_summary, rights_analysis_history
python -m storage.migrations.run_migrations     # applies numbered SQL files 001~020 (favorites, recent_items, search_presets, subscriptions, registry_usage, payments, registry_requests, indexes, payment_logs, registry_credits, audit/credit logs + soft-delete columns, document_collect_failures, document_queue UNIQUE+item_no, subscriptions.payment_id, auction_image); tracked in `migration_history`, safe to re-run. Running it as a script (`python storage/migrations/run_migrations.py`) also works as of 2026-08-11 — before that only the `-m` form did.
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
- **Frontend** (`src/`): Next.js App Router. Supabase is used only for auth/session (`src/lib/supabaseClient.ts`, `src/lib/supabaseServer.ts`, `src/proxy.ts` gates `/properties/*` — renamed from `src/middleware.ts` in Sprint 50 to follow Next.js 16's `proxy` file convention; logic unchanged) — auction data always comes from the Python API, never queried from Supabase directly. Note `src/login/` is a stale duplicate of the real `src/app/login/`.

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