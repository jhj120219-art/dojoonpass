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

Note: `docs/architecture.md` currently does not exist inside `docs/` — there is an `architecture.md` sitting one level up at `C:\Users\Administrator\Desktop\architecture.md` (Desktop root, outside this repo). Check there until/unless it's moved into `docs/`.

Each `docs/*.md` file has its own "절대 변경하면 안 되는 것" (do-not-change) and "알려진 문제점" (known issues) sections — read those before touching the corresponding area (frontend, backend, crawler, search). They are more current and detailed than anything summarized below; treat this file as the index, not a replacement.

One correction to keep in mind: `docs/search-engine.md` and `docs/crawler.md` describe `storage/database.py` as "not present in the repository" because of `.gitignore`. That's true for `git`/GitHub (see the Git hygiene note below) but the file exists on disk in this working directory and can be read directly — don't treat it as unknown or reverse-engineer it blind.

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
# serves on 0.0.0.0:8000, Swagger UI at /docs
```
No `requirements.txt` exists — dependencies are inferred from imports (`fastapi`, `uvicorn`, `python-dotenv`, `python-jose`, `selenium`, `webdriver-manager`, `pandas`). Get explicit approval before installing anything (project rule above).

### Daily crawl pipeline (`run_daily.bat`, Task Scheduler job `LawAuctionDailyCrawl`)
```bash
python mvp_scraper.py          # crawl all courts -> validate -> normalize -> upsert into `auction` table -> enqueue documents
python migrate_execute.py      # copies new `auction` rows into `auction_item` (the table the API actually serves)
```
Separately: `doc_worker.py` (~02:00, via `run_doc_worker.bat`) drains `document_queue` to download per-item PDFs/status docs. `refresh_priority.py` (~01:50, via `run_priority_refresh.bat`) recalculates queue priority as auction dates approach.

### DB schema setup (once, against a fresh `auction.db`, in order)
```bash
python storage/migrate_v4_1.py                 # creates auction_case, auction_item, document_status, doc_raw, parsed_document, tenant_rights, rights_summary, rights_analysis_history
python -m storage.migrations.run_migrations     # applies numbered SQL files (favorites, recent_items, search_presets, subscriptions, registry_usage, payments, registry_requests); tracked in `migration_history`, safe to re-run
```
`storage/database.py`'s `init_db()` only creates the legacy `auction` + `document_queue` + `document_version_log` tables (idempotent, runs automatically on every `mvp_scraper.py`/`doc_worker.py` invocation) — it does **not** create the v4.1 tables above.

### Tests
No test runner is configured (no pytest config). Root-level `test_*.py` files are standalone manual scripts, run directly: `python test_db.py`. The many `step*.py`, `check_*.py`, `patch_*.py` files are one-off investigation scripts from past debugging sessions, not a suite — and are gitignored (see below), so don't assume one is current, load-bearing code just because it's on disk.

## Architecture

Quick orientation map — see the matching `docs/*.md` for depth and the current do-not-change / known-issues lists.

- **Crawler** (`crawler/`, `mvp_scraper.py`, `doc_worker.py`): Selenium against `courtauction.go.kr`. `mvp_scraper.py` (06:00) collects listings -> `validator/validation_engine.py` (PASS/FAIL + `logs/validation.jsonl`) -> `normalizer/normalizer.py` (address/price/date parsing) -> `storage/database.py` upserts into the legacy `auction` table and enqueues `document_queue` rows. `doc_worker.py` (02:00) later claims queue rows and drives `crawler/doc_crawler.py` to download per-item documents.
- **Two SQLite schema generations** — know which one you're touching: the legacy `auction` table (crawler's write target, unchanged/do-not-modify per docs/backend.md) vs. the normalized v4.1 schema (`auction_case`/`auction_item`/`document_status`/... created by `storage/migrate_v4_1.py`). `migrate_execute.py` is the one-way sync from `auction` -> `auction_item`. **All `api/v1/*` routes read from the v4.1 tables, not `auction`** — if new crawl data isn't showing up via the API, check whether `migrate_execute.py` has run.
- **API** (`api_server.py` + `api/v1/*.py`): each file is a self-contained `APIRouter` (search, item, doc_stats, favorites, recent_items, search_presets, registry), no service/repository layer — routers query SQLite directly via `storage/database.py`'s `get_connection()`. `api/auth.py` verifies Supabase JWTs (`SUPABASE_JWT_SECRET`, HS256, `sub` claim = user_id) and provides the `{"success", "data", "message"}` envelope used by auth-required routes (search/item do not use this envelope). `filter/` (filter_engine.py/scoring_engine.py) is an earlier standalone module querying the legacy `auction` table directly — it is not wired into `api_server.py` and is effectively dead code, exercised only by `test_filter.py`.
- **Frontend** (`src/`): Next.js App Router. Supabase is used only for auth/session (`src/lib/supabaseClient.ts`, `src/lib/supabaseServer.ts`, `src/middleware.ts` gates `/properties/*`) — auction data always comes from the Python API, never queried from Supabase directly. Note `src/login/` is a stale duplicate of the real `src/app/login/`.

## Git / repo hygiene gotchas

- **`storage/` is entirely gitignored** (meant to exclude crawled data dumps), which also excludes real, load-bearing source code living there — `storage/database.py`, `storage/migrate_v4_1.py`, all of `storage/migrations/*.sql`. Run `git status --ignored` before assuming a change under `storage/` is captured by a commit; today none of it is tracked.
- `.gitignore` also blanket-ignores `step*.py`, `patch_*.py`, `check_*.py`, `*.db`, `*.csv`, `*.log`, `logs/`, `downloads/`, `documents/` as scratch/output, even though some (e.g. `patch_registry.py`) look like recent working scripts.
- **This working directory (`Desktop\dojoonpass`) may not be the live/production copy.** The checked-in `run_daily.bat` does `cd /d C:\Users\Administrator\Desktop\dojun-pass` — that exact path does not currently exist at Desktop root (only `Desktop\dojoonpass`, `Desktop\dojunpass-landing`, and `Desktop\기타\dojun-pass` do). `docs/crawler.md`'s "알려진 문제점" section documents this duplicate-folder/stale-path confusion in more detail — read it before assuming edits here reach whatever the scheduled task actually runs, or before touching `auction.db` path config.
- Korean-language log/print output and comments are the norm throughout the Python codebase — match that style when touching these files.