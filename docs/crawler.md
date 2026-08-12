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

라이브 경로가 `doc_raw`를 쓰게 하려면 `page_count`에 pdfplumber가 필요한데,
**2026-08-11 Sprint 61에 설치돼 이 제약은 해소됐다**(`pdfplumber==0.11.10`).
남은 것은 **어느 코드가 적재를 소유할지**뿐이다 — roadmap 16-A/16-B.

덧붙여 `doc_raw`는 **읽는 코드가 저장소 전체에 0곳**이다(자기 writer 안의
`MAX(doc_version)` 조회 제외). `parsed_document`는 **쓰는 코드도 읽는 코드도 0곳**으로
완전히 죽은 테이블이다(roadmap 16-C / BUGS #49에 이미 등록됨). 즉 "파싱 단계가 연결만
안 됐다"가 아니라 **그 단계의 구현 자체가 없다** — 실제로 동작 중인 파싱은
`load_spec_data.py` / `load_rights_data.py`가 `tenant_rights` / `rights_summary`에
쓰는 경로뿐이다(2026-08-12 Sprint 63 전수 확인).

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
