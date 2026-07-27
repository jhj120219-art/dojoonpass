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
  C:\ProgramData\Anaconda3\python.exe migrate_execute.py >> logs\migrate_execute.log 2>&1
  ```
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

1. `auction` 1,010 / `auction_item` 710, 차이 300건 (조사 시작 시점 기준)
   - `auction` 전용 10건 샘플 → 검색 API 조회 10건 전부 실패
   - `migrate_execute.py` 수동 실행 후: `auction_item` 710 → 1,099 (389건 반영), `auction` 1,103 / `auction_item` 1,099, 차이 4건으로 축소
   - 이 실행은 원인 분석 단계 실행 금지 원칙을 벗어나 수행됨
2. 2026-07-11 이후 `migrate_execute.py` 자동 실행 기록 없음. **원인 확정(2026-07-26 조사)**: Task Scheduler(`LawAuctionDailyCrawl`, `PDF우선순위갱신`)의 Execute 경로가 존재하지 않는 `C:\Users\Administrator\Desktop\dojun-pass`를 가리키고 있어 매일 정시에 트리거는 됐으나 실행 자체가 즉시 실패(`LastTaskResult=1`)했음. 2026-07-26 `dojoonpass` 경로로 수정 완료.
3. `Desktop\dojun-pass\`(존재하지 않음)와 `Desktop\기타\dojun-pass\`(구버전, 스키마 다름) 중복/혼선 존재. `Desktop\기타\dojun-pass\`가 왜 남아있는지는 아직 결정되지 않음
4. `api_server.py`의 실제 서빙 DB 경로 미검증

## 주의사항

- `auction` ↔ `auction_item` 관계 미증명 상태. 잔여 차이(4건)를 정상으로 단정하지 않음
- DB 연결 코드 검색 시 `sqlite3.connect()` 직접 호출과 `get_connection()` 경유를 모두 프로젝트 전체 범위에서 확인. 파일 1~2개만으로 판단하지 않음
- 원인 분석 단계에서 실행 금지 원칙을 벗어난 이력(수동 `migrate_execute.py` 실행, `run_daily.bat` 수정) 존재. 승인 기록 없음
- `DB_PATH`가 상대경로이므로 모든 스크립트 실행 전 Working Directory 확인 필수
