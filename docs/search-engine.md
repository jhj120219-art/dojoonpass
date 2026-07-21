# Search Engine Overview

## 목적

법원경매 물건 검색 API 제공. 탱크옥션/지지옥션 수준 검색엔진 구축이 목표.
투자점수, AI추천, 수익률 계산 기능은 개발 금지.

## 검색 구조

- 백엔드: FastAPI
- 데이터 저장소: **SQLite (`auction.db`)** — PostgreSQL/Supabase 아님
- Router가 SQL을 직접 실행하는 구조 (별도 Service 레이어 없음)
- 실제 구현 파일: `api_server.py`, `api/v1/search.py`, `api/v1/item.py`
- DB 커넥션 모듈 `storage/database.py`는 `.gitignore`에 의해 저장소에 존재하지 않음. 내용 미확인 상태로, 임의로 재작성하지 않는다.

인증(Supabase Auth)과 경매 데이터(SQLite)는 분리된 구조다.

```
Supabase Auth (JWT)
      │
      ▼
   FastAPI
      │
      ▼
SQLite (auction.db)
```

## 검색 대상

테이블: `auction_item`

실제 컬럼 (코드에서 확인됨):

```
id, case_no, item_no, court_name, property_type,
sido, sigungu, dong, full_address,
appraisal_price, minimum_bid_price, bid_rate,
auction_date, status, fail_count,
validation_status, crawl_date
```

관련 테이블 (`api/v1/item.py`에서 조인 확인됨): `auction_case`, `document_status`, `tenant_rights`, `rights_summary`

## 검색 인덱스

아직 결정되지 않음.

`storage/database.py` 미확인 상태이므로, 실제 SQLite에 인덱스가 존재하는지, 어떤 컬럼에 걸려 있는지 코드로 검증되지 않았다. 설계 문서(v1~v3)에서 제안한 인덱스안이 실제 DB에 적용됐는지 확인 필요.

## 검색 조건

`GET /api/v1/search` 기준, 실제 구현된 쿼리 파라미터:

```
sido
sigungu
property_type   (LIKE 매칭, ENUM 코드 아님)
court_name
auction_date_from / auction_date_to
min_appraisal / max_appraisal
min_bid_rate / max_bid_rate
min_fail_count / max_fail_count
page, size
```

`status` 필터는 현재 코드에 없음. 설계 문서에서는 추가하기로 했으나 실제 구현 여부 미확인.

## 필터 구조

- 모든 조건은 SQL `AND`로 동적 결합 (`conditions` 리스트 + `params` 리스트 방식)
- `sigungu`, `property_type`은 `LIKE %값%` 부분일치
- 나머지는 정확일치 또는 범위(`>=`, `<=`)
- `property_type` ENUM 코드화(APARTMENT/OFFICETEL 등)는 설계 문서에서 논의만 됐고 실제 코드는 자유 문자열 LIKE 매칭 상태. 코드화 적용 여부는 아직 결정되지 않음.

## 정렬 방식

현재 코드: `ORDER BY auction_date DESC, fail_count DESC` 로 고정.

`sort_by`, `sort_order` 파라미터화는 설계 문서에서 제안됐으나 실제 코드에는 구현되어 있지 않음.

## 검색 성능 전략

아직 결정되지 않음.

`storage/database.py` 미확인, 실제 인덱스 여부 미확인 상태에서는 성능 전략을 확정할 수 없음.

## API 연동 방식

- `api_server.py`가 FastAPI 앱 생성, `/api/v1` prefix로 router 등록
- 현재 등록된 router: `search`, `item`, `doc_stats`
- CORS: 전체 허용 (`allow_origins=["*"]`) — 운영 전환 시 재검토 필요 여부는 아직 결정되지 않음
- 인증: 현재 `/api/v1/search`, `/api/v1/item/{id}` 모두 인증 로직 없음 (Authorization 헤더 검증 코드 없음)

### 기존 엔드포인트 (변경 금지 대상)

```
GET /api/v1/search
GET /api/v1/item/{item_id}
GET /api/v1/stats
```

### 응답 방식

- `GET /api/v1/search`: `{ total, page, size, total_pages, items[] }` — **offset 페이지네이션**
- Cursor 기반 페이지네이션은 v1.0~v2.1 설계 문서에서 제안됐으나, 실제 코드는 offset 방식이며 PM 결정에 따라 **이 방식을 유지**한다 (Breaking Change 금지).

## 사용자 검색 흐름

```
검색 목록 조회 (인증 불필요, 현재 정책상 무료회원도 접근 가능)
    ↓
상세페이지 진입
    ↓ (PM 최종 정책: 프리미엄 회원 전용, 비구독자는 403 + 팝업)
    ※ 이 접근제어는 설계 문서(v2.1)에서 확정됐으나 실제 백엔드 코드에는 아직 미구현
```

## 향후 개발 예정

- `status` 필터 추가 (설계만 완료, 미구현)
- `sort_by` / `sort_order` 파라미터 추가 (설계만 완료, 미구현)
- `property_type` ENUM 코드화 (설계만 완료, 미구현)
- 프리미엄 회원 접근제어 (`GET /item/{id}` 403 처리, 설계만 완료, 미구현)
- 검색 인덱스 실제 적용 여부 점검 및 최적화

## 절대 변경하면 안 되는 것

- 데이터 저장소를 SQLite에서 PostgreSQL로 임의 전환하는 것 (PM이 명시적으로 현재 범위 밖으로 결정함)
- `GET /api/v1/search`, `GET /api/v1/item/{item_id}`의 기존 응답 구조
- `GET /api/v1/search`의 offset 페이지네이션 방식 (`page`, `size`)
- `auction_item` 컬럼명 (`case_no`, `item_no`, `minimum_bid_price`, `appraisal_price`, `fail_count`, `auction_date`, `status` 등 이미 확정되어 있는 이름)
- 투자점수 / AI추천 / 수익률 계산 기능 개발 (프로젝트 규칙상 금지)
- `storage/database.py`를 내용 확인 없이 임의로 새로 작성하는 것

## 알려진 문제점

- `storage/database.py`가 저장소에 없음 (`.gitignore`의 `storage/`, `*.db` 규칙에 의해 제외됨). 실제 커넥션 옵션(`row_factory`, `check_same_thread` 등) 미확인.
- 설계 문서(v1.0~v2.1)와 실제 구현 코드 간 불일치 다수 존재:
  - 페이지네이션: 설계는 cursor / 실제는 offset
  - `status` 필터, `sort_by`: 설계만 있고 미구현
  - `property_type`: 설계는 ENUM 코드 / 실제는 자유 문자열 LIKE
  - 프리미엄 접근제어(403): 설계만 있고 미구현
- 백엔드 API에 인증 로직이 전혀 없는 상태 (Phase 1 JWT 인증 작업 미착수)
- `favorites`, `recent_items`, `search_presets`, `subscriptions`, `payments`, `registry_requests` 테이블은 설계만 완료된 상태이며 실제 SQLite에 생성 여부 미확인

## 주의사항

- `storage/database.py` 내용을 확인하기 전에는 DB 커넥션 관련 코드를 추측으로 작성하지 않는다.
- 검색엔진 파트의 역할은 검색 정확도 향상, 필터 최적화, 검색 성능 개선이며, DB 마이그레이션은 이번 범위에 포함되지 않는다 (PM 지시).
- 신규 사용자 데이터 테이블(`favorites` 등)은 SQLite에 생성하며, `user_id`는 Supabase UUID를 TEXT로 저장하고 DB FK 제약 없이 애플리케이션 레벨에서 검증한다.
- 기존 엔드포인트(`/search`, `/item/{id}`)의 응답 구조와 페이지네이션 방식은 Breaking Change 없이 유지해야 한다.
