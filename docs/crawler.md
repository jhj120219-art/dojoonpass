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
- 자동 실행 시 활성 DB: `C:\Users\jhj12\OneDrive\Desktop\dojoonpass\auction.db` (2026-07-26 경로 통합 이전에는 존재하지 않는 `dojun-pass` 경로를 가리키고 있어 Task Scheduler 실행이 매번 실패했음 — 아래 "알려진 문제점" 참고)
- `Desktop\기타\dojun-pass\auction.db` 별도 존재. 스키마 다름(`auction_item` 테이블 없음), 최종 수정 2026-07-08, 자동 실행 경로와 무관
- `api/v1/*.py`, `filter/*.py`, `storage/migrations/*.py`, `api_server.py` 등 대부분 모듈이 동일 `get_connection()` 경유
- `api_server.py` 실행 시 Working Directory: 아직 결정되지 않음 (크롤러와 API가 동일 DB를 보는지 미확정)

## 스케줄링 방식

- Windows Task Scheduler, 작업명 `LawAuctionDailyCrawl`
  > **2026-08-11 실측: 이 예약 작업은 현재 등록돼 있지 않다.** 등록된 248개를 전수 조회했으나
  > 이 저장소를 가리키는 항목이 하나도 없다. 재등록은 운영 조치다 — 아래 "실행 환경" 절 참고.
- 실행 대상: `C:\Users\jhj12\OneDrive\Desktop\dojoonpass\run_daily.bat` (2026-07-26 수정, 이전에는 존재하지 않는 `dojun-pass` 경로를 가리켜 실행이 실패했음)
  ```bat
  @echo off
  cd /d %~dp0

  REM (인터프리터 해석 블록 — 아래 "실행 환경" 절 참고. %PY%가 여기서 정해진다)

  "%PY%" mvp_scraper.py >> logs\daily_run.log 2>&1
  if errorlevel 1 (
      echo ===================================== >> logs\daily_run.log
      echo [FAILED] mvp_scraper.py exited with code %errorlevel% at %date% %time% >> logs\daily_run.log
      exit /b 1
  )

  "%PY%" migrate_execute.py >> logs\migrate_execute.log 2>&1
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

## 물건 사진 수집 (2026-08-17 Sprint 144 신설)

02:00 `doc_worker.py`가 문서와 **같은 큐로** 함께 처리한다(`document_queue.doc_type='image'`,
`document_status.doc_type='IMAGE'`). 새 큐/워커를 만들지 않았다.

문서 수집과 **근본적으로 다른 점 세 가지** —

1. **버튼이 없다.** 상세페이지에 진입한 순간 캐러셀이 이미 DOM에 있다.
   그래서 `doc_worker`는 이 종류만 `get_doc_button_id()` 검사를 건너뛴다.
2. **다운로드할 URL이 없다.** 사진은 `<img src="data:image/png;base64,...">`로 페이지에
   박혀서 온다 — 디코드하면 그것이 원본 바이트다. **법원 서버에 추가 요청 0회.**
3. **선언된 MIME을 믿으면 안 된다.** 전부 `image/png`로 선언하지만 실제 바이트는
   JPEG/GIF다(2026-08-17 표본 45장 중 PNG 0장). 확장자는 **매직 바이트로 판정**한다
   (`crawler/image_assets.py:sniff_image_ext`).

```
crawler/image_assets.py    순수 규칙(alt 파싱 / 매직 판정 / data URI 디코드 / 크기 / 경로)
                           selenium·DB·fastapi 무의존 — doc_paths.py와 같은 이유
crawler/image_crawler.py   selenium 부분(collect_images) — 원자적 쓰기(os.replace)
storage/database.py        save_auction_images() -> auction_image (UNIQUE(item_id, seq))
```

저장 경로는 문서와 같은 물건 디렉터리 아래다:
`documents/<법원>/<사건>/<물건>/images/01.jpg` (순번 0채움 = 캐러셀 순서).

★ `go_to_case_detail()`에 **`item_no`를 반드시 넘긴다.** 이 함수는 예전에 사건번호만 보고
목록의 첫 일치 행으로 들어갔다. 문서는 버튼 id에 물건번호가 붙어 있어 영향이 없었지만
(실측 확인), 사진은 버튼 없이 페이지 DOM을 읽으므로 **잘못된 물건의 페이지에 있으면 그대로
잘못된 사진을 저장한다.**

## 예외 처리

아직 결정되지 않음

- `go_to_detail()`: 신선 데이터 10건×3회 100% 성공, 오래된 데이터 간헐적 실패. 원인: 아직 결정되지 않음. 구조 변경 보류 상태
- `collect_images()`: 사진 요소가 **하나도 없으면** 성공 + `no_asset=True`다(법원이 사진을
  제공하지 않는 물건이 실재한다 — 실패로 기록하면 영원히 재시도된다). 반대로 사진 요소는
  있는데 `alt` 규칙(`<종류>_<순번>`)에 맞는 것이 하나도 없으면 **실패로 처리한다** —
  법원 DOM이 바뀐 신호이고, 조용히 성공으로 넘기면 그날 이후 모든 물건의 사진이 사라진
  것을 아무도 모르게 된다.

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

-1. ~~**현황조사서는 물건번호 1만 수집 가능하다**~~ → **2026-08-17 해결 (Sprint 144+, BUGS #100)**.
   `get_doc_button_id("status", item_no)`가 물건번호 2 이상에 None을 돌려주고 있었고,
   그 때문에 `auction_item`의 **33.5%(629/1,876)**가 현황조사서를 영원히 받을 수 없었다
   (`document_queue`의 status + item_no != 1 중 done이 **0건**이었던 것이 증거).
   실 브라우저로 물건번호 2인 상세페이지 2건의 DOM을 덤프해 확인한 결과
   `..._btn_curstExmndcTop`이 **번호 없이 그대로 존재**하고, 오버레이 내용도 사건의 모든
   물건을 한 문서에 담고 있었다(집행관이 사건 단위로 작성하는 문서다).
   이제 물건번호와 무관하게 같은 버튼을 쓴다.
   ★ 부작용과 그 해소 (2026-08-17 Sprint 145에 함께 처리): 한 사건에 물건이 N개면
   **같은 문서를 N번 받게 된다.** 실측 비용 — 사건 1,384개 / 물건 1,876개이므로 초과
   수집 492회(35.5%), worker 1건당 약 22초이니 **약 3.0시간**이다(가동 창 02:00~04:00 =
   2시간을 넘긴다). 용량은 13.4MB로 무의미하니 **비용은 저장이 아니라 시간**이다.

   ★ **2026-08-17 Sprint 147 정정**: 위 "약 3.0시간"은 navigation까지 건너뛴다고 **가정한**
   값이다. Sprint 145 구현은 `collect_status()` 안에서만 재사용해 물건당 **0.6초(overlay)**만
   아꼈고 navigation 15.2초는 그대로 들었다 — 실제 절감은 492회 기준 **5분**이었다.
   Sprint 147이 `doc_worker`의 호출 순서를 바꿔(재사용 가능하면 이동 자체를 생략)
   실 worker 2건 기준 **41.1초 -> 23.8초**, 492회 기준 **약 130분** 절감으로 실현했다.

   같은 사건의 형제 물건이 방금 받아 둔 것이 있으면 **브라우저를 다시 몰지 않고 복사**한다
   (`crawler/doc_paths.py:find_sibling_case_document()` +
    `crawler/doc_crawler.py:_reuse_sibling_status()`).
   근거: 물건 1과 2에 대해 각각 따로 실제 수집을 돌려 대조한 결과 status.html은 **바이트까지
   동일**했고, status.json도 `fields` 115개 키가 완전히 일치했다(차이는 우리가 찍는
   `extracted_at` 하나뿐).

   **저장 구조는 바뀌지 않았다** — 파일은 종전과 같은 경로에 같은 내용으로 놓이고,
   달라지는 것은 "그 바이트를 어디서 얻는가"뿐이라 API·뷰어·`doc_exists()`는 무영향이다.
   재사용은 `SIBLING_REUSE_MAX_AGE_SECONDS`(기본 6시간) 안의 형제만 대상으로 한다 —
   몇 달 전 파일을 복사하면 새로 받았다면 얻었을 최신본 대신 옛것을 주게 되는데,
   "언제 다시 받을 것인가"는 재수집 정책(미결정)이라 여기서 정하지 않고 보수적으로 좁혔다.
   ★ 2026-08-18 Sprint 189: 정책이 정해졌고, 그래서 **재수집(`overwrite=True`)일 때는
     형제 복사를 아예 쓰지 않는다.** 형제 사본도 같은 옛 수집분이라, 복사해 오면
     법원이 갱신한 새 문서 대신 옛 내용을 다시 저장하고 큐는 done이 되어 재수집 기회가
     사라진다. 최초 수집에서는 그대로 유효하다(물건당 navigation 약 15초 절감).
   형제 파일이 빈 캡처면 복사하지 않고 직접 수집한다(빈 캡처를 퍼뜨리지 않는다).

0. **[2026-08-07 발견, 데이터 소실] `auction` 테이블 UNIQUE 키에 법원이 없다.**
   `UNIQUE(case_no, item_no)`라 서로 다른 법원이 같은 사건번호+물건번호를 쓰면
   `storage/database.py:upsert_batch()`의 UPDATE가 앞선 법원 물건을 통째로 교체한다(병합 아님).
   법원 간 사건번호 공유 3건 실측, 사본 DB로 소실 재현 완료 — 자세한 내용은 `docs/BUGS.md` #18.
   완화(경고 로그 / `migrate_execute.py` 식별키 차단 / 감시 테스트)는 적용했고
   근본 수정(`UNIQUE(court_code, case_no, item_no)`)은 스키마 변경이라 승인 대기.

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

---

## 실행 환경 (2026-08-11 Sprint 54 갱신)

### 배치 실행

```
run_daily.bat            mvp_scraper.py  ->  migrate_execute.py     (logs/daily_run.log)
run_doc_worker.bat       doc_worker.py                              (logs/doc_run.log)
run_priority_refresh.bat refresh_priority.py                        (logs/doc_run.log)
```

세 배치 모두 Python 인터프리터를 다음 순서로 해석한다.

1. `C:\ProgramData\Anaconda3\python.exe` 가 **존재하면** 그것을 쓴다 (기존 환경 무변경)
2. 없으면 `where python` 결과의 첫 항목
3. 둘 다 없으면 **로그에 `[FAILED]`를 남기고 `exit /b 1`**

3번이 그냥 방어 코드가 아니다. 예전에는 1번 경로를 하드코딩했는데 그 Anaconda가 제거되면서
배치가 실행 즉시 실패했고, **리다이렉트 대상 명령 자체가 실행되지 않아 로그가 비어 있었다**.
그래서 2026-08-03부터 8일 동안 크롤이 멈춘 사실을 아무도 몰랐다(BUGS #46).
Sprint 13이 `errorlevel` 검사로 없앤 "실패 은폐 구조"가 한 단계 위에서 재발한 것이다.

### 의존성

크롤러는 `selenium` / `webdriver-manager` / `pandas` / `pdfplumber`를 필요로 한다.
`requirements.txt`에 있으며 **현재 인터프리터(Python 3.12.10)에는 설치돼 있지 않다**.

```
pip install -r requirements.txt
python -c "import selenium, pandas, pdfplumber, webdriver_manager; print('OK')"
```

### 스케줄

등록된 Windows 예약 작업 248개 중 이 저장소를 가리키는 것이 **없다**
(`LawAuctionDailyCrawl` / `PDF우선순위갱신` 모두 부재).
재등록은 실제 정기 수집을 시작시키는 운영 결정이므로 Sprint 54에서는 하지 않았다.

### 마지막 실행 기록

```
logs/daily_run.log  2026-08-02 06:02:49
  [Errno 28] No space left on device
  오류 발생: 59 곳
  총 저장 건수: 0 건
```

디스크는 현재 859.2 GB 여유로 해소됐다. 다만 **59/60 법원 오류가 디스크 때문만이었는지는
아직 모른다** — 사이트 구조 변경이 겹쳤을 수 있고, 이는 실제로 한 번 돌려 봐야 확인된다.
크롤러 실행은 외부 네트워크 접근 + 장시간 작업이라 회귀 스위트에 포함하지 않는다.

---

## 파이프라인 실제 연결 상태 (2026-08-11 Sprint 55 실측)

### 스케줄러가 실제로 실행하는 것

```
run_daily.bat            mvp_scraper.py -> migrate_execute.py
run_doc_worker.bat       doc_worker.py
run_priority_refresh.bat refresh_priority.py
```

이 경로가 채우는 것: `auction_item` / `auction_case` / `document_queue` /
`auction.has_*_pdf` / `document_status`(Sprint 55부터) / `documents/*.pdf` / `document_version_log`

### 어떤 배치도 실행하지 않는 것

```
collect_documents.py    <- document_status / doc_raw / document_collect_failures 를 쓰는 유일한 코드
load_rights_data.py     <- rights_summary / tenant_rights
load_spec_data.py       <- tenant_rights (SPEC)

analyze_docs.py         <- 파이프라인 단계가 **아니다**. 배치에 넣으면 안 된다 (아래 참고)
```

**2026-08-12 Sprint 63 정정 — `analyze_docs.py`를 "PDF 파싱" 단계로 묶어 온 것은 사실이
아니었다.** 이 파일은 DB에 아무것도 쓰지 않고(`get_connection` 0회, SQL 0회) 첫 번째 물건을
하드코딩으로 열어 PDF 텍스트를 화면에 출력하는 **1회성 조사 스크립트**다. 게다가 마지막이
`input("엔터를 누르면 종료...")`라, Task Scheduler에서 실행되면 stdin이 없어 **매달리거나
즉시 죽고 같은 배치의 뒷 단계가 통째로 멈춘다.** 문서의 분류만 믿고 배치에 넣는 순간
사고가 나는 자리였다 — 이제 `test_crawl_exit_code.py`가 구조로 막는다(배치 후보 9종에
입력 대기가 없는지 + `analyze_docs.py`가 여전히 대화형인지 양방향 검사).

따라서 배치 편입을 검토할 대상은 **넷이 아니라 셋**이다.

배치 3종의 import를 재귀적으로 따라가도 이들에는 **도달하지 않는다**(2026-08-11 전수 확인).
그래서 `doc_raw` 0행 / `parsed_document` 0행이고, `rights_summary` 162건은 과거에 사람이
한 번 돌린 결과가 남아 있는 것이다.

> **[2026-08-19 Sprint 217] 위 문단의 "`doc_raw` 0행"은 지금 사실이 아니다.**
> Sprint 144가 `mark_queue_done()` 안에서 채우도록 고쳤고 **실측 556행**이다
> (아래 "Sprint 144에 해소됐다" 절 참고). 이 문단은 2026-08-11 시점의 기록으로 남긴다 —
> 여기까지만 읽고 "지금도 0행"으로 오해하지 않도록 그 자리에 표시해 둔다.
> `parsed_document` 0행은 **여전히 사실**이다. `rights_summary` 는 오늘 재실측에서
> **161건**이다(문서의 162건과 1건 차이 — 그 사이의 정리로 보이나 경위는 확인하지
> 못했다. "확인하지 못함"과 "없음"을 섞지 않기 위해 그대로 적는다).

이것이 권리분석 커버리지가 8.7%(162/1,870)에 머무는 근본 원인이다. 화면 결함이 아니다.

**이 넷을 배치에 넣는 것은 운영 스케줄 변경이므로 Sprint 55 범위 밖(SKIP)이다.**
넣기 전에 결정해야 할 것: 실행 순서, 소요 시간(PDF 파싱은 길다), 실패 시 재시도 정책.

### 종료 코드 규약 (Sprint 55 확립)

| 스크립트 | 0 (성공) | 1 (실패) |
|---|---|---|
| `mvp_scraper.py` | 수집·저장이 한 건이라도 됨 | 전 법원 실패 / 수집 0건 / DB 저장 0건 |
| `doc_worker.py` | 큐가 비었거나 한 건이라도 성공 | 시도했는데 **전건** 실패 |
| `migrate_execute.py` | 정상 | 예외 |
| `refresh_priority.py` | 정상 | 예외 |

부분 실패는 **경고만 남기고 성공**으로 둔다. 임계값을 임의로 정하면 그 자체가 새 정책이고,
멀쩡한 실행이 매일 실패로 보고되면 경보가 무시당해 결국 같은 자리로 돌아온다.

배치는 모든 실패 분기에서 `[FAILED]`를, 정상 종료에서 `[SUCCESS]`를 로그에 남긴다.
**두 마커가 모두 있어야** "돌았는데 할 일이 없었다"와 "아예 실행되지 않았다"가 구분된다 —
2026-08-02까지의 로그에는 이 마커가 한 번도 없었다.

---

## 문서 적재 경로가 두 벌이다 (2026-08-11 Sprint 56 실측, BUGS #55)

| | 파일 저장 | 해시 | `doc_raw` | `document_status` | 스케줄러 |
|---|---|---|---|---|---|
| `crawler/doc_crawler.py:collect_document()` | O | O | **X** | `mark_queue_done`이 대신(Sprint 55~) | **연결됨** |
| `collect_documents.py` | O | O | O | O | 연결 안 됨 |

`doc_raw`(storage_path / file_hash / file_size / page_count)를 채우는 것은 아래쪽뿐이라
현재 **0행**이다. 라이브 경로는 해시를 계산해 `document_version_log`에만 쓰고 나머지는 버린다.

★ **2026-08-17 Sprint 144에 해소됐다** — `mark_queue_done()`이 같은 트랜잭션에서 `doc_raw`를
채운다(실측 556행). 위 표의 `collect_document()` 행 `doc_raw` **X**는 그 함수 자신이
쓰지 않는다는 뜻이고, 파이프라인 전체로는 채워진다. 그리고 `document_version_log`는
2026-08-18 Sprint 189의 변경 기반 재수집으로 **처음으로 실제 도달 가능해졌다**
(아래 "변경 기반 재수집" 절).

라이브 경로가 `doc_raw`를 쓰게 하려면 `page_count`에 pdfplumber가 필요한데,
**2026-08-11 Sprint 61에 설치돼 이 제약은 해소됐다**(`pdfplumber==0.11.10`).
남은 것은 **어느 코드가 적재를 소유할지**뿐이다 — roadmap 16-A/16-B.

덧붙여 `doc_raw`는 **읽는 코드가 저장소 전체에 0곳**이다(자기 writer 안의
`MAX(doc_version)` 조회 제외). `parsed_document`는 **쓰는 코드도 읽는 코드도 0곳**으로
완전히 죽은 테이블이다(roadmap 16-C / BUGS #49에 이미 등록됨). 즉 "파싱 단계가 연결만
안 됐다"가 아니라 **그 단계의 구현 자체가 없다** — 실제로 동작 중인 파싱은
`load_spec_data.py` / `load_rights_data.py`가 `tenant_rights` / `rights_summary`에
쓰는 경로뿐이다(2026-08-12 Sprint 63 전수 확인).

**2026-08-17 Sprint 187 정정 — 위 표의 "라이브 경로는 doc_raw를 X(안 씀)"는 더 이상
사실이 아니다.** Sprint 144(2026-08-17, 이 표보다 나중)에서 `mark_queue_done()`이
같은 트랜잭션 안에서 `_record_doc_raw()`를 직접 호출하도록 고쳤다
(`storage/database.py:mark_queue_done()` docstring 참고 — 이 결함을 고친 경위가
그대로 적혀 있다). 지금은:

```
crawler/doc_crawler.py:collect_document() -> doc_worker.py -> mark_queue_done()
    -> document_status / doc_raw(storage_path, file_hash, file_size, page_count,
       doc_version) 를 **같은 트랜잭션**에서 함께 기록
```

"읽는 코드 0곳"도 더 이상 사실이 아니다 — `api/v1/item.py`가 `doc_raw`를
`MAX(doc_version)`로 JOIN해 상세 API 응답의 `doc_version`/`page_count`/`file_size`
필드로 그대로 노출한다. 다만 **`doc_version` 자체는 Sprint 187 전까지 내용 변경
여부와 무관하게 재수집마다 증가하는 결함이 있었다** — `docs/BUGS.md` #115에서 고쳤다.

이 정정은 코드 변화가 아니라 **문서가 그 사이 벌어진 Sprint 144를 반영하지 못하고
있었던 것**을 바로잡는 것이다 — 이 절 자체가 "실제 코드/테스트/데이터 상태가 MD와
다르면 MD를 함께 고친다"는 원칙의 예시로 남긴다. `collect_documents.py`는 여전히
스케줄러 미도달 상태이므로 위 표의 아래쪽 행("O/O/O/O, 연결 안 됨")은 그대로 유효하다.

## 파이프라인 정합 현황 (2026-08-11)

Sprint 55의 수정 이후 단계 간 불일치가 0이 됐고, `test_pipeline_integrity.py`가 이를
불변식으로 고정한다.

```
done 591건  -> 파일 없음 0 / document_status 없음 0 / READY 아님 0
파일 588개  -> 큐가 done 아님 0
큐 상태     -> in_progress 정체 0 / retry 불일치 0 / 기일 남은 SKIPPED_EXPIRED 0
고아 행     -> 5개 참조 경로 전부 0
```

남은 공백은 **파싱 단계**다(스케줄러 미연결).

```
SPEC   READY 197 / 파싱됨 116  (나머지 81 = 임차인 없음)
STATUS READY 194 / 파싱됨 161  (나머지 33 = 빈 캡처, Sprint 62에 복구)
APPRAISAL           파싱 대상 테이블 자체가 없다(감정평가서 파서 미구현)
```

**2026-08-12 Sprint 62 정정 — 위 "나머지"를 미파싱으로 기록해 온 것은 사실이 아니었다.**
실제로 파일을 전수 확인한 결과 둘은 성격이 완전히 다르다.

- **SPEC 81건은 파싱 실패가 아니다.** 표를 정상적으로 찾았고, 그 표에 적힌 내용이
  literally `조사된 임차내역없음`이다. 즉 **임차인이 없는 물건**이며 파서는 올바르게
  동작했다. "미파싱 81"이라는 기록은 정상 동작을 결함으로 보이게 만들었다.
  (다만 "확인된 임차인 없음"이라는 정보를 저장하지 않아 화면에서 "정보 없음"과
  구분되지 않는다 — 표기 방식은 제품 결정이라 `docs/roadmap.md` Backlog로 남겼다.)
- **STATUS 33건은 진짜 결함이었다** — 내용이 비어 있는 캡처가 정상 수집으로 저장된
  것이다(`docs/BUGS.md` #61). Sprint 62에 크롤러를 고치고 33건을 재수집 대상으로 복구했다.

파싱 결과가 없는 문서는 상세 화면에서 `SPEC_NOT_PARSED` 경고로 표시된다(FRONTEND_MASTER_SPEC §9.5-A).

---

## 실행 소요 시간 실측 (2026-08-12 Sprint 65 — 저장소 최초 측정)

그동안 "소요 시간"은 배치 편입을 미루는 근거로 여러 문서에 언급됐지만 **실제로 측정된
값은 어디에도 없었다.** 이번에 크롤러를 실제로 돌려 처음 측정했다.

```
환경     Chrome 151 / ChromeDriver 자동 확보 / 헤드리스
대상     서울중앙지방법원 (목록 9건, 각 건 상세 진입 포함)

crawl_court() 1개 법원        약 168초
  -> 60개 법원 전체 추정      약 2.8시간
문서 수집 collect_status() 1건  약 12초 (상세 진입 포함)
```

운영 판단에 필요한 것:
- 일일 크롤이 06:00에 시작하면 **약 08:50경 종료**된다. `migrate_execute.py`는 그 뒤에
  돌아야 하므로 배치 순서(`run_daily.bat`)는 이미 올바르다(순차 실행).
- `doc_worker.py`는 `DOC_WORKER_END_TIME`으로 스스로 종료 시각을 지키므로 큐가 아무리
  길어도 정해진 시간에 멈춘다. 현재 대기 큐가 2,700건대라 **하루에 다 비우지 못한다** —
  우선순위(`calc_priority`)가 기일 임박 순으로 처리 순서를 정하는 이유가 이것이다.
- 사이트 목록은 **시점에 따라 반환 건수가 달라진다**(같은 법원 재실행 시 9건 → 1건 관측).
  수집 건수가 줄었다고 곧바로 결함으로 판단하면 안 된다 — `CrawlOutcome`의 실패 판정이
  "전 법원 실패" 또는 "저장 0건" 기준인 이유다.

---

## 2차 방어선은 큐의 사본이 아니라 실제 기일을 본다 (2026-08-17 Sprint 145, BUGS #101)

`document_queue.auction_date`는 06:00 적재 시점에 `auction_item`에서 **복사해 둔
비정규화 사본**이다. 유찰 후 재매각으로 기일이 미래로 다시 잡히면 이 사본은 옛 날짜를
그대로 들고 있을 수 있다.

예전에는 `doc_worker`의 2차 방어선이 그 사본만 보고 `SKIPPED_EXPIRED`로 종결했다.
`SKIPPED_EXPIRED`는 `reset_stale_queue()`의 부활 대상이 아니므로 **살아 있는 사건의
문서가 영구히 수집되지 않았다.**

```
실측 2026-08-17
  document_queue.auction_date != auction_item.auction_date        36행
    그중 pending + 큐는 과거 + 실제 기일은 미래                     3행
      -> item 1533 (2024타경122092-1) spec/status/appraisal 전부
         큐 2026-07-15  vs  실제 2026-08-19
```

지금은 종결하기 **직전에** 권위 있는 값과 대조한다:

```python
# doc_worker.py
today = datetime.now().strftime("%Y-%m-%d")
if auction_date and auction_date < today:
    auction_date = reconcile_queue_auction_date(item["id"], case_no, item_no, auction_date)
if auction_date and auction_date < today:
    mark_queue_skipped_expired(...)
```

`reconcile_queue_auction_date()`(`storage/database.py`)는 `(case_no, item_no)`로
`auction_item`을 조회해(1,876행에서 유일함을 실측 확인) 값이 다르면 큐 행의
`auction_date`와 `priority`를 함께 정정하고 권위 있는 값을 돌려준다.

- **정책은 바뀌지 않았다** — "기일 지난 사건은 수집하지 않는다"는 그대로이고,
  그 판단이 참조하는 값의 출처만 사본에서 원본으로 바뀌었다.
- `status`는 건드리지 않는다 — 이미 종결된 행을 되살릴지는 재수집 정책이라 제품 판단이다
  (`enqueue_documents()`의 Sprint 74 주석과 같은 규약).
  ★ 2026-08-18 Sprint 189: 그 제품 판단이 내려졌다. 되살리는 주체는 여기가 아니라
    `requeue_changed_documents()`이고, 기준은 **법원 원천이 실제로 바뀌었는가**다
    (아래 "변경 기반 재수집" 절 참고). 이 함수는 여전히 status를 건드리지 않는다 —
    "값이 사실과 다른 것"을 고치는 일과 "다시 받을지 정하는 일"은 서로 다른 책임이다.
- 매칭되는 물건이 없으면 큐 값을 그대로 돌려준다(판단을 바꾸지 않는다).
- Sprint 74가 `enqueue_documents()`에 넣은 갱신은 **06:00 크롤이 돌 때만** 동작하므로
  이 검사와 중복이 아니라 보완 관계다(크롤과 크롤 사이의 구멍을 이쪽이 막는다).


---

## 변경 기반 재수집 (2026-08-18, Sprint 189)

법원 원천이 바뀌면 **다음 수집 주기에 그 물건의 관련 자산만** 다시 받는다.
전면 재수집(실측 약 1.9시간)이 아니라 표적 재수집(84초 규모)이다.

### 사슬

```
법원 원천 변경
  -> mvp_scraper -> upsert_batch()       auction 갱신
  -> migrate_execute()                    auction_item 갱신 + **필드 단위 변경 판정**
  -> requeue_changed_documents()          done -> 'refresh'   ★ Sprint 189가 채운 칸
  -> claim_next_item_rows()               한 물건의 행을 한꺼번에 집는다 (Sprint 236)
       -> claim_next_queue_item()         'refresh' -> 'in_progress_refresh', overwrite=True
                                          (첫 행 선택 + overwrite 판정은 여전히 이 함수가 한다)
  -> doc_worker -> collect_document(overwrite=True)
  -> previous_hash != new_hash            document_version_log 1행
  -> auction_image / doc_raw              실체 기록
  -> API -> 상세페이지
```

### 큐 상태 어휘

`document_queue.status`는 TEXT이고 CHECK 제약이 없다 — 값 추가는 **스키마 변경이 아니다**
(그래서 승인 없이 가능하다). 새 컬럼을 만들지 않은 이유가 이것이다.

```
pending              한 번도 수집한 적 없다        -> overwrite=False
refresh              이미 있지만 다시 받아야 한다  -> overwrite=True
in_progress          pending 을 집어간 상태
in_progress_refresh  refresh 를 집어간 상태
```

진행 상태를 두 갈래로 나눈 것이 핵심이다. 재시도(`mark_queue_failed`)와 stale 회수
(`reset_stale_queue`)가 **원래 어느 쪽이었는지 알아야** 제자리로 돌려놓을 수 있다.
하나로 합치면 재수집 의도가 첫 실패에서 조용히 사라지고, 그다음 시도는
`overwrite=False`라 "이미 존재. 스킵"으로 **성공 처리**된다 — 가장 나쁜 실패 방식이다.

### 기록하는 사진은 **서빙될 수 있는 사진**이어야 한다 (2026-08-19 Sprint 218, BUGS #148)

"있다"를 판정하는 자리가 셋이고, 그중 **행을 만드는 곳만** 기준이 달랐다.

```
save_auction_images()      size <= 0 만 거절        <- 행을 만드는 곳
image_exists()             >= MIN_IMAGE_BYTES(1,024)
api/v1/images.py (서빙)     >= MIN_IMAGE_BYTES
```

1~1,023바이트 파일은 DB 에 행이 생기고 → API 가 `image_count=1 / READY` 를 주고
→ 검색목록도 썸네일 URL 을 주는데 → **그 URL 은 404** 였다.
이제 세 곳이 같은 상수를 본다(`test_asset_pipeline.py` 12-Q 가 AST 로 고정).

정상 경로는 바뀌지 않는다 — 수집기가 이미 `len(data) < MIN_IMAGE_BYTES` 로 걸러낸다.
막는 것은 잘린 파일·수동 조작·옛 backfill 이 남길 수 있는 행이다.
운영 실측(2026-08-19): 45행의 최소 크기 35,746바이트로 **영향 0건**.

### "이미 존재. 스킵"도 실체는 기록한다 (2026-08-19 Sprint 217, BUGS #144)

스킵 분기는 **파일을 다시 쓰지 않는다.** 그러나 예전에는 `files_saved=[]` 로 돌아왔고,
그러면 `mark_queue_done()` -> `_record_doc_raw()` 가 맨 앞에서 반환한다
(`if not files_saved: return`). 결과:

```
파일 spec.pdf 는 있다 / doc_raw 는 0행
  -> 큐 done / 화면 READY
  -> API available=true 인데 page_count·file_size·doc_version 이 **영구 null**
  -> 다음 수집도 같은 스킵 분기 -> 스스로 회복되는 경로가 없다
```

이제 세 분기(spec/status/appraisal) 전부 `doc_paths.existing_doc_files()` 로
**이미 갖고 있는 파일**을 결과에 담는다. `doc_exists()` 와 같은 목록·같은 기준을 쓴다.
사진 쪽은 같은 자리를 처음부터 복구하고 있었다(`image_crawler._describe_existing()`) —
문서만 없던 칸을 메운 것이다.

바뀌지 않는 것: 파일을 다시 쓰지 않고(mtime 무변경), `previous_hash`/`new_hash` 는
그대로 비어 `document_version_log` 에 거짓 개정을 남기지 않으며, `_record_doc_raw()` 의
내용 무변경 판정(Sprint 187)이 `doc_version` 부풀림을 막는다.

### 무엇이 바뀌면 무엇을 다시 받는가

`storage/database.py:REFRESH_DOC_TYPES_BY_FIELD` 하나가 유일한 정의처다.

| 바뀐 필드 | 다시 받는 자산 | 근거 |
|---|---|---|
| `auction_date` | spec, status | 법원은 **기일마다 매각물건명세서를 다시 올린다** |
| `minimum_bid_price` | spec | 저감된 최저가가 명세서에 적혀 있다 |
| `status` | spec, status | 유찰/변경/취하/정지가 두 문서에 반영된다 |
| `appraisal_price` | appraisal, image | 감정가 변동 = 재감정 = 감정평가서 + 현장 재촬영 |

**사진을 기일/최저가에 넣지 않는다.** 사진은 감정 시점의 것이라 유찰로 값만 내려갈 때는
바뀌지 않는다. 넣으면 매일 수천 장을 이유 없이 다시 받는다.

### 되돌릴 것과 건드리지 않을 것

```
done                  -> refresh   단, 매각기일이 아직 지나지 않은 물건만
SKIPPED_EXPIRED       -> pending   단, 기일이 미래로 다시 잡혔을 때만 (한 번도 못 받았으므로
                                   overwrite 가 아니다)
pending / refresh     그대로       이미 대기 중
in_progress(_refresh) 그대로       워커가 소유 중 — 뺏으면 그 실행이 done 으로 덮는다
failed                그대로       자기 재시도 경로가 따로 있다
SKIPPED_UNSUPPORTED   그대로       성공할 수 없는 항목의 영구 종결. 되살리면
                                   mark_queue_unsupported() 가 끊은 무한 재시도가 되살아난다
```

"기일이 지난 물건은 되돌리지 않는다"는 조건은 실제 DB 사본으로 돌려 보다가 추가했다 —
되돌리면 워커의 2차 방어선에 걸려 곧바로 `SKIPPED_EXPIRED`가 되므로, **아무것도 다시
받지 못한 채 성공 기록(done)만 잃는다.**

### 상한과 스위치

- `REFRESH_MAX_ITEMS_PER_RUN = 300`. 초과분은 큐에 그대로 남아 다음 실행의 후보가 되고,
  **잘린 건수는 로그와 반환값에 남는다**(조용한 절단 금지).
  아직 실측 근거가 없는 값이라, 재수집이 실제로 돌기 시작하면 다시 정한다.
- `DOJOONPASS_REFRESH_ON_CHANGE=0` 이면 관측만 하고 예약하지 않는다(기본 켬).

### 정렬은 바꾸지 않았다

`priority`는 매각기일 임박도에서 나온 제품의 중요도다. 재수집을 앞세우면 **한 번도
수집된 적 없는 임박 물건**이 뒤로 밀린다. 총량은 위 상한으로 따로 제한한다.

### 실패해도 이미 가진 것을 잃지 않는다

재수집이 최종 실패해도 화면 상태(`document_status`)가 `READY`/`NO_IMAGE`면 **그대로
유지한다**(`DOC_STATUS_HAS_ARTIFACT`). 아니면 화면은 "수집실패"인데 파일 서빙은 200으로
옛 문서를 내려 주는 어긋남이 생긴다(BUGS #122, #50 계열). 큐 행은 `failed`로 남으므로
실패 사실 자체는 유실되지 않는다.

### 지문은 **내용**에서 뜬다 — 우리가 찍은 메타데이터는 제외 (BUGS #124)

`status.json`에는 우리가 매 수집마다 새로 찍는 `extracted_at`이 들어 있다. 파일 전체를
해싱하면 **법원 자료가 그대로여도 지문이 매번 달라진다** = 매 수집이 거짓 개정이다.

```
_fields_hash(fields)          fields 만 정렬된 canonical JSON 으로 직렬화 -> sha256
status_content_hash(path)     디스크의 status.json 에서 **같은 공식**으로
```

두 공식이 갈라지면 이미지 BUGS #113/#120과 정확히 같은 결과가 된다 — 그래서 한 함수를
양쪽이 함께 쓴다. 형제 물건 재사용 경로도 마찬가지다(복사해 온 파일의 `extracted_at`은
그 형제를 수집한 시각이라 비교 근거가 될 수 없다).

자산별 지문의 근거를 한 자리에 모으면:

| 자산 | 지문의 근거 | 왜 |
|---|---|---|
| 사진 | 파일별 sha256을 순번 순으로 이어 붙여 다시 sha256 | 법원이 URL을 안 주므로 바이트가 유일한 근거 |
| 명세서/감정평가서 | PDF 파일 전체 sha256 | 파일에 우리 메타데이터가 없다 |
| 현황조사서 | **`fields`의 canonical JSON** sha256 | 파일에 우리가 찍은 `extracted_at`이 있다 |

### 내용이 그대로면 파일을 다시 쓰지 않는다 (BUGS #125)

같은 바이트를 다시 써도 **mtime이 바뀐다.** 서빙 쪽 ETag는 Starlette가 (mtime, size)로
만들기 때문에, 내용이 그대로여도 **모든 브라우저 캐시가 무효화된다** —
`api/http_cache.py`가 조건부 요청으로 아끼려던 바로 그 바이트다.

```
검색 1페이지 썸네일  약 2MB      물건당 사진 1.3~1.9MB      감정평가서 1건 3.4MB
```

재수집 대상은 정의상 "사용자가 지금 보고 있는" 물건이라 체감이 가장 큰 자리다.

```
사진        _same_bytes_on_disk(dest, digest) 이면 쓰지 않는다
status      내용 지문이 같으면 html/json 둘 다 쓰지 않는다 (_write_text_if_changed)
spec/appr.  new_hash == previous_hash 이면 목적지를 건드리지 않고 다운로드분만 치운다
```

판정은 **크기가 아니라 바이트 지문**으로 한다 — 크기만 보면 같은 크기의 다른 내용을 놓친다.

`status.json`의 `extracted_at`은 이제 **"이 내용을 처음 확인한 수집 시각"**이라는 뜻이다.
#124가 그 필드를 지문에서 뺐으므로 변경 감지에는 영향이 없다.

### 사진 집합의 세 근거는 언제나 같아야 한다 (2026-08-18 Sprint 191)

사진에는 근거가 셋 있고, **완전 수집 뒤에는 반드시 같아야 한다.**

```
수집 결과   collect_images() 가 돌려주는 images[].seq
디스크      documents/<법원>/<사건>/<물건>/images/ 의 파일들
DB          auction_image 행
```

이 저장소가 겪은 사진 결함은 **전부** 이 셋 중 둘이 갈라진 것이다
(#113 #114 #120 #127 #128). 그래서 각 상황을 지키는 코드가 나뉘어 있다:

| 무엇이 | 어디가 지키나 |
|---|---|
| 같은 순번의 다른 확장자 | `_remove_other_ext_for_seq()` (쓰기 직후, BUGS #120) |
| 이제 없는 순번 | `_remove_files_not_in()` (완전 수집일 때만, BUGS #127) |
| DB 옛 행 | `save_auction_images()` **집합 차집합** (완전 수집일 때만, BUGS #127) |
| 0장으로 줄어든 경우 | `clear_images_if_absence_confirmed()` (**2회 확인**, BUGS #128) |
| 바이트가 같은 재수집 | 쓰지 않는다 (mtime/ETag 보존, BUGS #125) |

**부분 수집(`partial=True`)이면 어느 것도 지우지 않는다.** "법원이 줄였다"와 "일부만
받아졌다"는 구별할 수 없고, 지운 것은 되돌릴 수 없다.

`seq > max_seq` 가 아니라 **집합 차집합**인 이유: 법원이 가운데 순번을 빼는 경우
(1,2,4만 제공)를 `>` 비교는 못 잡는다 — 3번 행이 살아남고 그 파일은 이미 없다.

### 0장 케이스만 다르게 다룬다 (BUGS #128)

`doc_worker` 는 `if result.get("images")` 로 가드한다(빈 목록은 전체 실패와 구별되지
않으므로 **그 가드는 옳다**). 그래서 0장은 별도 경로로 처리하고, **두 번 연속 확인**을
요구한다.

```
1회차: document_status 가 READY -> NO_IMAGE. 사진은 남긴다(경고 로그).
2회차: 이미 NO_IMAGE 인데 또 no_asset -> 행과 파일을 정리한다.
```

1회차 기억은 `document_status` 자체가 한다(새 컬럼 없음).
`clear_images_if_absence_confirmed()`는 `mark_queue_done()` **보다 먼저** 불러야 한다.
정리 순서는 **DB 행 -> 파일**이다(반대면 "DB 는 있다는데 파일이 없다"가 된다).

### 문서의 "완료"는 필요한 파일 **전부**다 (BUGS #129)

```
spec        spec.pdf
status      status.html + status.json      <- 둘 다 있어야 완료
appraisal   appraisal.pdf
```

예전에는 status 를 `status.json` 하나로 판정했는데 **뷰어가 서빙하는 것은
`status.html`** 이다. json 만 남으면 "완료"로 오판해 영구히 재수집에서 빠지고 뷰어는
404다. 단일 소스는 `crawler/doc_paths.py:DOC_REQUIRED_FILES` 이고,
`test_doc_storage_atomicity.py` 7i 가 서빙 표와의 정합성을 강제한다.

### 배치는 두 번 돌지 않는다 (2026-08-18 Sprint 194)

```
doc_worker    logs/doc_worker.lock    stale 5시간
mvp_scraper   logs/mvp_scraper.lock   stale 6시간   <- Sprint 194 신설
```

구현은 `storage/checkpoint.py:RunLock` 하나다(규칙을 베끼지 않는다).
락을 못 잡으면 **실패가 아니라 조용한 건너뜀**이다 — 다른 실행이 이미 그 일을 하고 있다.

매일 크롤에 락이 필요한 이유:

```
logs/checkpoint.json   CheckpointManager.save() 가 파일 전체를 읽어 고쳐 쓴다 ->
                       두 실행이 겹치면 진행 상황이 서로 덮인다
법원 서버              전체 크롤 약 3.1시간(파생) -> 같은 사건을 두 배로 긁는다
```

예약 작업끼리는 `MultipleInstances=IgnoreNew` 로 안 겹친다. 락이 막는 것은
**수동 실행과 스케줄 실행이 겹치는 경우**다.

★ 락을 못 잡은 쪽은 **남의 락을 지우면 안 된다.** 지우면 먼저 돌던 실행이 무방비가
된다. `test_doc_worker_recovery.py` §11 이 그것을 고정한다.

### PDF 수집: 탭이 아니라 **파일 도착**이 성공 조건이다 (2026-08-18 Sprint 201, BUGS #135)

`get_download_driver_options()` 는 `plugins.always_open_pdf_externally: True` 를 켠다.
그래서 Chrome 은 PDF 를 **렌더링하지 않고 곧바로 내려받는다.**

그 결과 `window.open(pdf_url)` 로 연 탭은 **그릴 것이 없어 뜨지도 않는다.**
즉 **다운로드가 성공할수록 탭은 안 생긴다.**

```
잘못된 성공 조건   새 탭이 떴는가          -> 성공할수록 거짓이 된다
옳은 성공 조건     파일이 도착했는가        -> wait_for_download()
```

`collect_appraisal()` 은 탭이 없으면 이제 **다운로드 도착 여부로 판단한다.**
둘 다 없을 때만 실패다.

실측(2026-08-18): 수정 전 이 경로는 `success=False` 를 내면서 2.5MB PDF 를
`downloads/` 에 버렸고, 그 파일은 그 물건의 기존 `appraisal.pdf` 와 sha256 이 같았다.
`downloads/` 에는 그렇게 버려진 고아가 **8개 / 14.0MB** 쌓여 있었다.

★ 받아 놓고 못 옮긴 파일은 `audit_asset_integrity.py` [8] 이 상시 탐지한다.

### 명세서도 같았다 (2026-08-18 Sprint 202, BUGS #136)

위 규칙은 감정평가서만의 이야기가 아니다. `collect_spec()` 도 같은 모양이었다.
법원이 명세서를 뷰어 대신 **PDF 로 바로** 내려 주면 탭이 뜨지 않고 파일만 도착하는데,
그 분기가 파일을 확인조차 하지 않고 실패로 끝냈다.

```
탭이 떴다      -> 문서뷰어다. '파일저장' 을 눌러 받는다 (기존 경로, 그대로)
탭이 없는데
파일이 왔다    -> **뷰어 단계를 건너뛰고 바로 저장한다** (신설)
둘 다 없다     -> 그때만 실패다
```

뷰어는 다운로드를 얻기 위한 **수단**이지 목적이 아니다. 파일이 이미 손에 있으면
뷰어를 찾을 이유가 없다.

증거: `downloads/` 고아 8개 중 **5개가 매각물건명세서**였다(2026-08-18 실측).

주의: 여전히 미확정인 경로가 하나 남는다 — **뷰어 탭은 뜨는데 30초 안에 파일이
안 오는** 경우. 그건 타임아웃 튜닝 문제라 운영 로그 없이 정하지 않는다.
`audit_asset_integrity.py` [8] 이 계속 지켜본다.

### ★ 그 타임아웃이 만드는 더 나쁜 결과 (2026-08-20 Sprint 228, BUGS #164)

타임아웃 자체보다 **그 뒤에 일어나는 일**이 위험하다.

`wait_for_download()` 는 `after_files - before_files` 로 **새로 생긴 PDF** 를 집는다.
어느 사건의 것인지는 보지 않는다. 그래서 이런 순서가 성립한다.

```
1. 사건 A 수집 -> 30초 안에 안 옴 -> 포기. **다운로드는 계속 진행 중**
2. 사건 B 수집 시작 -> before_files 스냅샷 (A 의 것은 아직 .crdownload 라 여기 포함)
3. A 완료 -> Chrome 이 A.crdownload 를 A.pdf 로 바꾼다 = before_files 에 없는 **새 파일**
4. wait_for_download() 가 그것을 집는다 -> **A 의 문서가 B 로 저장된다**
```

받은 뒤의 검증이 사건과 무관하다는 것이 문제였다.

```
크기가 0보다 크고 안정적인가   wait_for_download()
정말 PDF 인가(매직 바이트)     _looks_like_pdf()
-> 이 사건의 것인가             **아무도 확인하지 않았다**
```

결과는 조용하다 — 저장된 것은 진짜 PDF 라 크기·해시·READY·화면 표시가 전부 정상이고
`audit_asset_integrity.py` 의 [1]~[9] 를 **전부 통과한다.**
사용자는 다른 사건의 명세서를 보고 입찰을 판단하게 된다.

**방어**: 파일명에 박힌 사건번호로 대조한다. 법원이 주는 명세서 파일명에는 사건번호가
있고(`2023타경118942_..._매각물건명세서...pdf`), 감정평가서는 업체 코드라 없다
(`HR2025-0609-0001.pdf`). 그래서 **확실할 때만** 막는다.

```
사건번호 있음 + 다름  ->  거부       사건번호 있음 + 같음  ->  통과
사건번호 없음         ->  통과 (판단할 근거가 없다 - "없으면 거부"로 만들면 감정평가서가 전부 막힌다)
```

병합 사건은 `crawler/resume.py:case_no_matches_list_entry()` 를 **재사용**한다
(같은 판정을 두 벌 만들면 한쪽만 고쳐진다).
거부해도 파일은 **지우지 않는다** — 원래 주인이 있고, 지우면 그 사건의 재수집도 잃는다.

남은 위험: 파일명에 사건번호가 없는 종류는 여전히 판정할 수 없다. 더 확실한 방어
(수집 전 `downloads/` 비우기 / 사건별 하위 폴더)는 각각 진행 중 다운로드 훼손과
Chrome 프로필 변경이라 승인이 필요하다.

---

## 2026-08-20 Sprint 237 — `MAX_ITEMS` 는 두 가지를 제한한다 (주의)

```
crawler/court_crawler.py  crawl_court()        collect_list_items(driver, MAX_ITEMS)
                                               -> 그날 이 법원에서 몇 건 가져올까 = **공급 상한**
crawler/base_crawler.py   go_to_case_detail()  collect_list_items(driver, MAX_ITEMS)
                                               -> 아는 사건을 찾으려고 몇 행 훑을까 = **조회 창**
```

두 번째는 정책이 아니다. **공급을 줄이려고 이 값을 내리면 이미 큐에 있는 사건을
찾지 못하게 된다** — 조용히, "사건 매칭 실패" 로그만 남기고.
`test_max_items_contract.py` 가 이 관계(조회 창 >= 공급 상한)를 지킨다.

실측(크롤 로그 1,698회): 수집 건수가 **10에서 205회(12.1%) 몰린다** — 상한이 실제로
걸리고 있다. 다만 그 너머의 공급량은 자료가 잘려 있어 알 수 없다.
