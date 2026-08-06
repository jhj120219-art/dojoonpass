# Crawler Overview

## 목적

법원경매 데이터 수집. 파이프라인: 검색 API → 상세조회 API → 문서수집 → 권리분석. 크롤러는 `auction` 테이블 적재 담당.

## 현재 크롤링 대상

아직 결정되지 않음

## 데이터 수집 구조

- `mvp_scraper.py` → `auction` 테이블 적재
- `api/v1/search.py`, `api/v1/item.py`, `api/v1/doc_stats.py` → `auction_item` 테이블 조회 (auction 아님)
- `auction` → `auction_item` 이전은 `migrate_execute.py`가 수행 (`get_connection()` 경유 INSERT)
- `auction` ↔ `auction_item` 관계가 1:1 미러인지 선별 저장인지: 아직 결정되지 않음

## Playwright 구조

아직 결정되지 않음

## 크롤링 순서

`run_daily.bat` 기준 순서만 확인됨:
```
1. mvp_scraper.py
2. migrate_execute.py
```
내부 단계별 로직: 아직 결정되지 않음

## 데이터 정제 방식

아직 결정되지 않음

## SQLite 저장 방식

- DB 파일: `auction.db`
- 연결: `storage/database.py`
  ```python
  DB_PATH = "auction.db"  # 상대경로

  def get_connection() -> sqlite3.Connection:
      conn = sqlite3.connect(DB_PATH)
  ```
- `DB_PATH`는 상대경로. 실제 연결 대상은 프로세스 실행 시점의 Working Directory에 의해 결정됨
- 자동 실행 시 활성 DB: `C:\Users\Administrator\Desktop\dojoonpass\auction.db` (2026-07-26 경로 통합 이전에는 존재하지 않는 `dojun-pass` 경로를 가리키고 있어 Task Scheduler 실행이 매번 실패했음 — 아래 "알려진 문제점" 참고)
- `Desktop\기타\dojun-pass\auction.db` 별도 존재. 스키마 다름(`auction_item` 테이블 없음), 최종 수정 2026-07-08, 자동 실행 경로와 무관
- `api/v1/*.py`, `filter/*.py`, `storage/migrations/*.py`, `api_server.py` 등 대부분 모듈이 동일 `get_connection()` 경유
- `api_server.py` 실행 시 Working Directory: 아직 결정되지 않음 (크롤러와 API가 동일 DB를 보는지 미확정)

## 스케줄링 방식

- Windows Task Scheduler, 작업명 `LawAuctionDailyCrawl`
- 실행 대상: `C:\Users\Administrator\Desktop\dojoonpass\run_daily.bat` (2026-07-26 수정, 이전에는 존재하지 않는 `dojun-pass` 경로를 가리켜 실행이 실패했음)
  ```bat
  @echo off
  cd /d %~dp0

  C:\ProgramData\Anaconda3\python.exe mvp_scraper.py >> logs\daily_run.log 2>&1
  if errorlevel 1 (
      echo ===================================== >> logs\daily_run.log
      echo [FAILED] mvp_scraper.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
      exit /b 1
  )

  C:\ProgramData\Anaconda3\python.exe migrate_execute.py >> logs\migrate_execute.log 2>&1
  if errorlevel 1 (
      echo ===================================== >> logs\daily_run.log
      echo [FAILED] migrate_execute.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
      exit /b 1
  )

  echo ===================================== >> logs\daily_run.log
  echo [SUCCESS] Finished at %date% %time% >> logs\daily_run.log
  exit /b 0
  ```
  (2026-08-06 수정, 아래 "알려진 문제점" 5번 참고 — 이전 버전은 `mvp_scraper.py`/`migrate_execute.py` 실패 여부와 무관하게 뒤따르는 `echo`가 항상 성공해 배치 전체 종료코드가 0으로 남는 구조였음)
- `migrate_execute.py` 호출 라인은 원래 없었음. 2026-07-11 이후 자동 실행 기록 없음. 이후 수동 추가됨. 승인 이력: 아직 결정되지 않음

## 예외 처리

아직 결정되지 않음

- `go_to_detail()`: 신선 데이터 10건×3회 100% 성공, 오래된 데이터 간헐적 실패. 원인: 아직 결정되지 않음. 구조 변경 보류 상태

## 성능 최적화

아직 결정되지 않음

## 향후 개발 예정

아직 결정되지 않음

## 절대 변경하면 안 되는 것

- `storage/database.py`의 `DB_PATH = "auction.db"` (상대경로). 변경 시 `get_connection()` 사용하는 모든 모듈의 연결 대상 DB가 달라짐
- `run_daily.bat`/`run_doc_worker.bat`/`run_priority_refresh.bat`의 `cd /d %~dp0` 라인(2026-07-26부터, 배치파일 자기 위치 기준으로 변경됨). 제거/변경 시 상대경로 `"auction.db"`가 다른 파일을 열게 됨
- 코드 수정, 마이그레이션 실행, INSERT/UPDATE/DELETE, 동기화 스크립트 실행, 설계 변경 — PM 승인 없이 수행 금지

## 설계 이유

아직 결정되지 않음 (상대경로 DB_PATH 설계, auction/auction_item 분리 설계의 의도된 이유는 이 대화에서 확인되지 않음)

## 알려진 문제점

1. ~~`auction` 1,010 / `auction_item` 710, 차이 300건~~ → 2026-08-06 재확인 결과 `auction`
   1,870건 / `auction_item` 1,870건으로 **차이 0건**, `run_daily.bat`가 매일 두 스크립트를
   순서대로 실행하면서 정상 동기화되고 있음을 확인(stale, 더 이상 유효하지 않은 서술)
   - `auction` 전용 10건 샘플 → 검색 API 조회 10건 전부 실패 (당시 기록, 현재 차이 0건이라 재현 불가/무관)
   - `migrate_execute.py` 수동 실행 후: `auction_item` 710 → 1,099 (389건 반영), `auction` 1,103 / `auction_item` 1,099, 차이 4건으로 축소
   - 이 실행은 원인 분석 단계 실행 금지 원칙을 벗어나 수행됨
2. 2026-07-11 이후 `migrate_execute.py` 자동 실행 기록 없음. **원인 확정(2026-07-26 조사)**: Task Scheduler(`LawAuctionDailyCrawl`, `PDF우선순위갱신`)의 Execute 경로가 존재하지 않는 `C:\Users\Administrator\Desktop\dojun-pass`를 가리키고 있어 매일 정시에 트리거는 됐으나 실행 자체가 즉시 실패(`LastTaskResult=1`)했음. 2026-07-26 `dojoonpass` 경로로 수정 완료.
3. `Desktop\dojun-pass\`(존재하지 않음)와 `Desktop\기타\dojun-pass\`(구버전, 스키마 다름) 중복/혼선 존재. `Desktop\기타\dojun-pass\`가 왜 남아있는지는 아직 결정되지 않음
4. `api_server.py`의 실제 서빙 DB 경로 미검증
5. ~~`run_daily.bat` 실패 은폐~~ → 2026-08-06 수정 완료. 이전 버전은 `mvp_scraper.py`/`migrate_execute.py` 실행 줄 뒤에 조건 없는 `echo` 2줄이 항상 실행돼, 두 파이썬 스크립트가 실패해도(0이 아닌 exit code) 배치 마지막 명령이 `echo`(항상 성공)라서 `run_daily.bat` 자체의 종료코드가 항상 0으로 남았음(Task Scheduler `LastTaskResult`가 실패를 인지 못함). `migrate_execute.py`는 이미 `sys.exit(0)/sys.exit(1)`을 정확히 반환하고 있었으므로, 각 단계 실행 직후 `if errorlevel 1`으로 즉시 확인해 실패 시 다음 단계로 넘어가지 않고 `exit /b 1`로 종료하도록 수정(어느 단계에서 실패했는지 `logs\daily_run.log`에 `[FAILED] <script>.py exited with code %errorlevel%`로 명시). 격리된 로컬 테스트(실패/성공 각각 재현하는 더미 스크립트)로 종료코드 1/0과 로그 메시지 모두 확인함. `mvp_scraper.py` 내부는 과일(court)별 실패를 여전히 개별 try/except로 흡수하고 계속 진행하는 기존 설계 그대로 유지(이번 Sprint 범위 밖 — 전체 크롤링이 완전히 중단되는 미처리 예외가 발생했을 때만 이번 수정이 감지)
6. **[Release Blocking, 2026-08-06 발견, 미수정]** `auction_case.case_no`가 전국 단일 `UNIQUE`
   제약(`storage/migrate_v4_1.py`)이라, 서로 다른 법원이 같은 형식의 사건번호를 채번하면
   `auction_case`에서 같은 row로 병합됨. `config/courts.py:ALL_COURTS`(60개 법원)를 전부
   크롤링하는 현재 구조상 항상 발생 가능하며, 현재 DB에서 서로 다른 법원 간 사건번호 충돌
   3건 실측 확인됨. `auction_item.court_name`(검색/상세 목록 노출 필드)은 법원별로 정확히
   저장되어 당장 눈에 보이는 오류는 없지만, `auction_case` 경유 필드(`case_type`/`filed_date`/
   `demand_deadline`, 현재는 전부 NULL이라 미노출)가 채워지는 순간 데이터 오염이 노출됨. 수정에는
   UNIQUE 키를 `(court_name, case_no)` 복합키로 바꾸는 Schema 변경 + 기존 데이터 재처리(Migration)가
   필요해 승인 없이 구현하지 않음 — 자세한 내용은 `docs/BUGS.md` #14 참고.
7. ~~`mvp_scraper.py`가 `logs/` 디렉터리 존재를 가정~~ → 2026-08-06(Sprint 18) 수정 완료.
   `logging.basicConfig()`가 `logging.FileHandler("logs/scraper.log")`를 모듈 로드 시점(맨 위,
   `main()` 호출 전)에 즉시 생성하는데, `logs/`는 `.gitignore` 대상이라 새로 clone한 환경에는
   존재하지 않아 `FileHandler` 생성 자체가 `FileNotFoundError`로 즉시 실패해 `mvp_scraper.py`가
   단 한 줄도 실행되지 못하고 죽는 구조였음. `doc_worker.py`/`refresh_priority.py`는 이미
   `os.makedirs("logs", exist_ok=True)`를 로깅 설정 직전에 호출해 이 문제가 없었음(기존
   두 스크립트의 검증된 패턴을 그대로 `mvp_scraper.py`에도 적용) — `logs/`가 이미 있는 이번
   저장소에서는 완전히 no-op(동작 무변화), 향후 fresh clone/CI 환경에서만 실질적으로 효과가 생김.
   부수 확인: `logs/checkpoint.json`(`storage/checkpoint.py`)·`logs/errors.jsonl`
   (`crawler/court_crawler.py:log_error`)·`logs/validation.jsonl`(`ValidationEngine`)도
   전부 같은 `logs/` 디렉터리에 의존하므로 이번 수정 하나로 함께 보호됨을 코드 추적으로 확인.
8. **[Dead Code, 2026-08-06(Sprint 19) 발견, 삭제 없이 기록만]** `config/settings.py`가
   실제로는 쓰이지 않는 설정을 갖고 있음 — `COURTS`(서울 5개 법원, 실제 법원코드 `B000210` 등
   사용)와 `PAGE_LOAD_TIMEOUT`/`ELEMENT_TIMEOUT`/`AJAX_TIMEOUT`/`SIDO_LIST`는 저장소 전체에서
   단 한 곳도 import하지 않음(grep으로 확인). 실제 60개 법원 목록은 `config/courts.py:ALL_COURTS`
   (법원명을 `code`로 사용, 진짜 법원코드 아님)이 대체해 쓰이고 있고, 타임아웃 3개는
   `crawler/base_crawler.py`가 동일한 값(30/20/30)을 자체적으로 다시 하드코딩해 쓰고 있어
   `config/settings.py` 쪽 정의와 이름·값이 우연히 같을 뿐 실제로는 연결되어 있지 않음(둘 중
   하나만 바꾸면 조용히 어긋날 수 있는 구조). 60개 법원 확장 이전 초기 개발 단계의 잔재로 보임.
   `config/settings.py`에서 실제로 쓰이는 것: `CourtInfo`(dataclass, `config/courts.py`가 재사용),
   `MAX_ITEMS`/`MAX_RETRY`/`random_delay`(court_crawler.py/base_crawler.py/collect_documents.py),
   `get_doc_button_id`/`DOC_WORKER_END_TIME`(doc_worker.py). 삭제는 이번 세션 원칙상 하지 않음 —
   사용 여부가 100% 확실해도(grep 근거 있음) 삭제 자체가 금지된 작업이라 기록만 함.
9. **[Dead Code, 2026-08-06(Sprint 21) 발견, 삭제 없이 기록만]** `logs/` 디렉터리 안에
   `mvp_scraper.py`/`doc_worker.py`/`refresh_priority.py` 3개 파이썬 파일이 루트 동명 스크립트의
   **오래된 복사본**으로 남아있음. 어떤 코드/배치파일도 이 경로를 참조하지 않으며(`grep`으로
   확인), 실제로 실행되는 것은 루트 버전임(`run_daily.bat`/`run_doc_worker.bat`/
   `run_priority_refresh.bat` 전부 `cd /d %~dp0` 후 루트 파일 실행). **stale임이 코드로 증명됨**:
   `logs/doc_worker.py`가 `crawler.doc_crawler`에서 `crawl_single_document`를 import하는데 이
   함수는 현재 저장소에 존재하지 않는다(현재 이름은 `collect_document`, `grep` 결과 이 이름을
   쓰는 곳은 `logs/doc_worker.py` 2줄뿐) — 즉 이 복사본은 지금 실행하면 즉시 ImportError로
   죽는다. `mark_queue_skipped_expired`(기일 경과 스킵), 부분 성공(`partial`) 로깅 등 이후에
   추가된 기능도 전부 빠져 있음. `logs/`는 `.gitignore` 대상이라 git에는 없고 로컬 디스크에만
   존재. 과거 디버깅 중 백업해둔 스냅샷으로 보이나, 루트 파일과 헷갈릴 위험이 있어 정리 대상 —
   삭제는 이번 세션 원칙상 수행하지 않고 기록만 함.

## 주의사항

- `auction` ↔ `auction_item` 관계 미증명 상태. 잔여 차이(4건)를 정상으로 단정하지 않음
- DB 연결 코드 검색 시 `sqlite3.connect()` 직접 호출과 `get_connection()` 경유를 모두 프로젝트 전체 범위에서 확인. 파일 1~2개만으로 판단하지 않음
- 원인 분석 단계에서 실행 금지 원칙을 벗어난 이력(수동 `migrate_execute.py` 실행, `run_daily.bat` 수정) 존재. 승인 기록 없음
- `DB_PATH`가 상대경로이므로 모든 스크립트 실행 전 Working Directory 확인 필수
