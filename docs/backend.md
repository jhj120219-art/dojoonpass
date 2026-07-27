# Backend Overview

## 목적
전국 법원경매 데이터 수집·저장·검색·권리분석 API 제공.
의사결정 기준: 투자자가 실제 돈을 내는 기능인지 여부.

---

## 현재 Backend 구조

dojoonpass/
api_server.py
mvp_scraper.py
collect_documents.py
migrate_execute.py
run_daily.bat
.env
api/
auth.py
v1/
search.py
item.py
favorites.py
recent_items.py
search_presets.py
registry.py
doc_stats.py
storage/
database.py
migrate_v4_1.py
migrate_doc_collect.py
migrations/
001_create_favorites.sql
002_create_recent_items.sql
003_create_search_presets.sql
004_create_subscriptions.sql
005_create_registry_usage.sql
006_create_payments.sql
007_create_registry_requests.sql
run_migrations.py
crawler/
court_crawler.py
doc_crawler.py
models/
auction_item.py
config/
settings.py
courts.py
logs/
daily_run.log
migrate_execute.log
doc_collect.log
docs/
backend.md


---

## FastAPI 구조

- 진입점: `api_server.py`
- 실행: `python api_server.py`
- 포트: 8000
- host: 0.0.0.0
- Swagger: `http://localhost:8000/docs`
- CORS: 전체 허용 (개발 환경)
- 라우터 prefix: `/api/v1`
- 서비스 레이어: 없음 (라우터에 직접 구현)
- 레포지토리 레이어: 없음 (라우터에서 직접 SQLite 쿼리)

---

## API 구조

### 인증 불필요
| 메서드 | 경로 | 비고 |
|--------|------|------|
| GET | / | 헬스체크 |
| GET | /api/v1/stats | 관리자용, 프론트 연동 없음 |
| GET | /api/v1/document-stats | 관리자용, 프론트 연동 없음 |
| GET | /api/v1/search | 검색 |
| GET | /api/v1/item/{item_id} | JWT 있으면 최근조회 자동 기록 |

### 인증 필요 (Supabase JWT)
| 메서드 | 경로 |
|--------|------|
| GET/POST/DELETE | /api/v1/favorites, /api/v1/favorites/{item_id} |
| GET | /api/v1/recent-items |
| GET/POST/DELETE | /api/v1/search-presets, /api/v1/search-presets/{id} |
| POST/GET | /api/v1/registry-requests |
| GET | /api/v1/registry-requests/{id} |
| GET | /api/v1/registry-requests/{id}/download |

### GET /api/v1/search 파라미터
sido, sigungu, property_type, court_name,
auction_date_from, auction_date_to,
min_appraisal, max_appraisal,
min_bid_rate, max_bid_rate,
min_fail_count, max_fail_count,
page(기본 1), size(기본 20, 최대 100)

자유텍스트 주소 검색 미지원.

### 공통 응답 형식 (인증 필요 API 전용)
```json
{"success": true, "data": {...}, "message": null}
{"success": false, "data": null, "message": "오류 내용"}
```

인증 불필요 API(search, item)는 공통 형식 미적용.

---

## Business Logic

### auction → auction_item 동기화
- 설계 이유: mvp_scraper.py는 auction에만 저장. 검색 API는 auction_item 사용. 동기화 누락 방지를 위해 run_daily.bat에 migrate_execute.py 추가.
- 방식: SELECT * FROM auction 전체 대상, INSERT OR IGNORE
- 실행 시간: 0.17초

### 유찰횟수 추출
auction.status 문자열 정규식 추출. "유찰 11회" → fail_count=11

### 최저가율
bid_rate = minimum_bid_price / appraisal_price

### 최근조회 자동 기록
GET /api/v1/item/{item_id} 호출 시 JWT가 있으면 recent_items 자동 기록.
동일 물건 재조회 시 viewed_at 갱신.
JWT 없으면 기록 안 함 (에러 없음).

### 등기부 무료 횟수
월 5회 무료. 초과 시 건당 1,000원.
차감 시점: 신청 시점.
판단 기준: registry_usage WHERE user_id=? AND is_free=1 COUNT.

### 구독 정책
- 베타 얼리버드: 9,900원/월
- 정가: 22,900원/월
- 얼리버드 가입자 평생 9,900원 유지 (정책 확정)

---

## Database 연동 방식

- 종류: SQLite
- 파일: `C:\Users\Administrator\Desktop\dojoonpass\auction.db`
- 연결: `storage/database.py` → `get_connection()`
- DB_PATH: `"auction.db"` (상대경로)
- 크롤러(mvp_scraper.py)와 API 서버(api_server.py) 동일 DB 파일 사용 확인됨
- row_factory: sqlite3.Row
- 중복 처리: INSERT OR IGNORE
- 트랜잭션: commit() / rollback() 수동 관리
- 백업: 없음

---

## 인증 방식

- 방식: Supabase Auth JWT
- 헤더: `Authorization: Bearer {supabase_jwt}`
- 검증 키: `SUPABASE_JWT_SECRET` (환경변수)
- 사용자 식별자: JWT payload.sub = auth.users.id
- users 테이블 없음 (Supabase auth.users 직접 사용)
- NEXTAUTH_SECRET 사용 안 함

### 환경변수 (.env)

SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_JWT_SECRET=

현재 값 미입력 상태.

### 개발용 임시 헤더
JWT 미설정 시에만 동작:

X-Test-User-Id: {user_id}


---

## 자동 수집 파이프라인

Task Scheduler (매일 06:00)
→ run_daily.bat
→ mvp_scraper.py >> logs/daily_run.log
→ migrate_execute.py >> logs/migrate_execute.log


---

## DB 스키마 (v4.1 확정)

### 원본 테이블
- `auction`: 크롤러 원본. 하위호환 유지. 변경 금지.

### 서비스 테이블
- `auction_case`: 사건 단위
- `auction_item`: 물건 단위. 검색/상세 API 기준 테이블.
- `document_status`: COLLECTING/OCR/PARSING/ANALYZING/READY/FAILED
- `doc_raw`: 원본 파일 보관
- `parsed_document`: parsed_json, parser_version (raw_text 없음)
- `tenant_rights`: 임차인 원본 데이터. 분석 결과 없음.
- `rights_summary`: occupancy_difficulty(EASY/NORMAL/HARD), risk_level(LOW/MID/HIGH), risk_reason(JSON)
- `rights_analysis_history`: 분석 이력
- `document_collect_failures`: 수집 실패 로그

### 사용자 테이블 (Phase 1)
- `favorites`: UNIQUE(user_id, item_id)
- `recent_items`: UNIQUE(user_id, item_id), viewed_at 갱신
- `search_presets`: conditions JSON

### 결제/등기부 테이블 (Phase 1)
- `subscriptions`: plan(BETA_EARLYBIRD/STANDARD), status(ACTIVE/CANCELLED/EXPIRED)
- `registry_usage`: is_free, charged_amount
- `payments`: payment_type(SUBSCRIPTION/OVERAGE_USAGE), pg_provider(미연동, null)
- `registry_requests`: status(PENDING/PAYMENT_REQUIRED/PROCESSING/COMPLETED/FAILED)

### 마이그레이션 관리
`migration_history` 테이블로 적용 이력 관리.
`python -m storage.migrations.run_migrations` 으로 실행.
각 SQL 파일은 독립 실행 가능.

---

## Validation 규칙

- validation_status: PASS / FAIL
- FAIL 조건: address_mismatch (addr 시도 ≠ appraisal 시도)
- FAIL 건도 DB 저장 (제외 안 함)

---

## Error 처리 방식

| 코드 | 의미 |
|------|------|
| 401 | 토큰 없음 / 검증 실패 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 402 | 결제 필요 |
| 500 | JWT Secret 미설정 / 서버 오류 |
| 501 | 미구현 (등기부 다운로드) |

---

## 향후 개발 예정

### Phase 2
- 등기부 수집 모듈 연결 → registry_requests download 구현
- PG사 연동 (미확정)
- registry_rights 테이블

### Phase 3
- LLM 기반 권리분석
- 임차인 배당 시뮬레이션

---

## 절대 변경하면 안 되는 것

- `auction.db` 경로: `C:\Users\Administrator\Desktop\dojoonpass\auction.db`
- `auction` 테이블 구조 (크롤러 원본)
- `auction_item.id` (프론트 라우팅 /auction/{itemId} 기준 PK, 정수형)
- GET /api/v1/search 응답 필드명 (프론트 연동 완료)
- GET /api/v1/item/{item_id} 응답 필드명 (프론트 연동 완료)
- 공통 응답 형식 `{"success", "data", "message"}`
- 인증 방식: Supabase JWT (NEXTAUTH_SECRET 사용 금지)
- `python -m storage.migrations.run_migrations` 실행 방식

---

## 알려진 문제점

- 외부 봇/스캐너 접근 중 (0.0.0.0:8000, 방화벽 미설정)
- sido="" 데이터 1건 존재
- 자유텍스트 주소 검색 미지원
- 등기부 다운로드 501 (수집 모듈 미연결)
- SUPABASE_JWT_SECRET 미입력 (.env 파일 있으나 값 없음)
- auction.db 백업 없음

---

## 주의사항

- 투자점수 / AI추천 / 수익률 계산 개발 금지
- 방화벽 설정: 베타 공개 직전 별도 작업
- PG 연동 코드 작성 금지 (PG사 미확정)
- 결제 성공 가정 Mock 로직 백엔드 작성 금지
- PAYMENT_REQUIRED 상태까지만 백엔드 관리
- property_type 코드: APARTMENT/OFFICETEL/LAND/FACTORY/COMMERCIAL/MULTI_FAMILY
- payments.pg_provider: 현재 null
