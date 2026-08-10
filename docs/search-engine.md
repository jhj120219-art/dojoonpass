# Search Engine Overview

## 목적

법원경매 물건 검색 API 제공. 탱크옥션/지지옥션 수준 검색엔진 구축이 목표.
투자점수, AI추천, 수익률 계산 기능은 개발 금지.

## 검색 구조

- 백엔드: FastAPI
- 데이터 저장소: **SQLite (`auction.db`)** — PostgreSQL/Supabase 아님
- Router가 SQL을 직접 실행하는 구조 (별도 Service 레이어 없음)
- 실제 구현 파일: `api_server.py`, `api/v1/search.py`, `api/v1/item.py`
- DB 커넥션 모듈 `storage/database.py`는 `.gitignore`(`storage/` 전체) 규칙 때문에 **git 이력에는** 없지만, 실제 작업 디렉터리에는 파일이 존재하며 읽을 수 있다(2026-08-06 재확인, `docs/CLAUDE.md` 정정 사항과 동일). "미확인 상태"였던 이전 서술은 stale했음 — 아래 검색 인덱스/성능 전략 절의 "미확인" 서술도 실제로는 파일을 열어 확인 가능하다는 전제로 다시 봐야 한다.

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

2026-08-06 코드 재확인 결과 이미 적용되어 있음(더 이상 "미결정" 아님) — `storage/migrations/008_create_search_indexes.sql`:

```
idx_auction_item_case_no          (case_no)
idx_auction_item_court_name       (court_name)
idx_auction_item_sido_sigungu     (sido, sigungu)
idx_auction_item_property_type    (property_type)
idx_auction_item_auction_date     (auction_date)
idx_auction_item_appraisal_price  (appraisal_price)
idx_auction_item_minimum_bid_price(minimum_bid_price)
idx_auction_item_fail_count       (fail_count)
idx_rights_summary_item_id        (rights_summary.item_id)
```

`009_add_default_sort_index.sql`이 기본 정렬(아래 "정렬 방식" 참고)에 맞춘 복합 인덱스도 추가함:
`idx_auction_item_default_sort (auction_date DESC, fail_count DESC)`. `dong`/`lot_number`/`full_address`
(LIKE 검색 대상)에는 별도 인덱스 없음 — LIKE 부분일치는 B-tree 인덱스로 가속되지 않으므로 설계상 의도된 범위로 보임.

## 검색 조건

`GET /api/v1/search` 기준, 실제 구현된 쿼리 파라미터(2026-08-06 `api/v1/search.py` 재확인, 이전 버전
문서에 누락되어 있던 파라미터 다수 추가):

```
case_no                         (LIKE 부분일치)
sido                             (정확일치, extract_sido()로 "서울시" 등 축약 표기 정규화)
sigungu / dong                   (LIKE 부분일치)
address_detail                   (자유텍스트 — 아래 "자유텍스트 주소 검색" 참고)
property_type                    (콤마로 다중 선택 가능, 각각 LIKE 매칭, ENUM 코드 아님)
court_name                       (LIKE 부분일치)
status                           (LIKE 부분일치)
auction_date_from / auction_date_to
min_appraisal / max_appraisal
min_bid_price / max_bid_price
min_bid_rate / max_bid_rate
min_fail_count / max_fail_count
sort_by / sort_order             (아래 "정렬 방식" 참고)
page, size
include_closed                   (기본 false — 아래 D7 필터 참고)
```

`status`는 이전 버전 문서에 "현재 코드에 없음"으로 기재되어 있었으나 실제로는 구현되어 있음(2026-08-06 정정).

## 자유텍스트 주소 검색

이전 버전 문서(및 `docs/backend.md`/`docs/roadmap.md`의 "알려진 문제점")는 "자유텍스트 주소 검색
미지원"으로 기재하고 있었으나, 2026-08-06 코드 재확인 결과 `address_detail` 파라미터로 이미
지원되고 있음(백엔드 `api/v1/search.py:_address_detail_condition()` + `intent/analyzer.py`,
프론트 `src/app/search/SearchForm.tsx`의 `addressDetail` 입력 필드까지 연동 완료):

- `intent/analyzer.py:analyze_intent()`가 입력을 SIDO/SIGUNGU/DONG/LOT_NUMBER/FULL_ADDRESS/MIXED/UNKNOWN으로 분류
- 구조화 가능한 입력(예: "서울 강남구 역삼동")은 `sido`/`sigungu`/`dong` 각 컬럼 조건으로 분해되어 인덱스를 탈 수 있음
- 구조화 불가능한 입력(건물명/도로명 등, UNKNOWN)은 기존 방식 그대로 `full_address LIKE %입력%`으로 폴백 — 이 경로는 인덱스 없이 전체 스캔됨(위 "검색 인덱스" 참고)
- 프론트에서 `sido`/`sigungu`/`dong`을 직접 지정한 경우 `address_detail`은 함께 보내지 않음(상호 배타적 UI, `SearchForm.tsx` 확인)

## 필터 구조

- 모든 조건은 SQL `AND`로 동적 결합 (`conditions` 리스트 + `params` 리스트 방식)
- `sigungu`, `dong`, `court_name`, `status`, `case_no`, `property_type`(콤마 분리 후 각각)은 `LIKE %값%` 부분일치
- 나머지는 정확일치 또는 범위(`>=`, `<=`)
- `property_type` ENUM 코드화(APARTMENT/OFFICETEL 등)는 설계 문서에서 논의만 됐고 실제 코드는 자유 문자열 LIKE 매칭 상태(2026-08-06 재확인, 변경 없음) — `docs/backend.md` 주의사항에 나열된 값(APARTMENT/OFFICETEL/LAND/FACTORY/COMMERCIAL/MULTI_FAMILY)은 관례상 쓰이는 값일 뿐 DB/코드 레벨에서 강제되는 ENUM은 아님
- D7 종결물건 기본 필터(2026-08-05, Search Release 이후 Sprint): `auction_date_from` 미지정 + `include_closed=false`(기본값)면 `auction_date >= 오늘`을 자동 추가. `auction_date_from`을 명시하면 이 기본 필터는 적용되지 않음(기존 호출 호환)

## 정렬 방식

이전 버전 문서는 "`sort_by`/`sort_order`는 설계만 되고 미구현"으로 기재하고 있었으나, 2026-08-06
재확인 결과 구현되어 있음(정정) — `SORT_COLUMNS` 화이트리스트(`auction_date`/`appraisal_price`/
`minimum_bid_price`/`bid_rate`/`fail_count`/`crawl_date`/`case_no`/`full_address`)에 없는 값은
`400`으로 명시 거부. 둘 다 비워두면 기존과 동일하게 `auction_date DESC, fail_count DESC` 고정 정렬 사용.

## 검색 성능 전략

위 "검색 인덱스" 절 참고 — `auction_item`의 주요 필터/정렬 컬럼에는 인덱스가 이미 적용되어 있다.
그 외 캐싱, 검색 결과 사전 집계 등 추가 성능 전략은 아직 결정되지 않음.

## API 연동 방식

- `api_server.py`가 FastAPI 앱 생성, `/api/v1` prefix로 router 등록
- 현재 등록된 router: `search`, `item`, `doc_stats`
- CORS: **제한 메커니즘은 이미 있다**(2026-08-10 Sprint 48 정정). `api_server.py`가
  `CORS_ALLOW_ORIGINS` 환경변수를 콤마 구분으로 읽어 그 목록만 허용하고, **미설정일 때만**
  하위호환을 위해 `["*"]`로 동작한다. 즉 "코드가 전체 허용으로 고정"이 아니라
  "운영 값이 아직 설정되지 않은 상태"다. 인증이 쿠키가 아니라 Authorization 헤더(Bearer)라
  CSRF 위험은 없다. 운영 도메인 확정 후 `.env` 설정만 남았고, `.env` 수정은 승인 사항이다
- 인증: `GET /api/v1/search`는 로그인 없이도 그대로 동작(설계상 의도, 정정 없음). 다만 2026-08-06
  재확인 결과 완전히 "인증 로직 없음"은 아님 — `HTTPBearer(auto_error=False)`로 토큰이 있으면
  선택적으로 검증해 결과 각 item의 `is_favorited`를 채우는 데만 사용하고, 토큰이 없거나
  검증에 실패해도 검색 자체는 그대로 진행됨(`item.py`와 동일한 패턴). 인증 실패가 검색을 막지
  않는다는 원래 취지는 그대로 유지됨

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
첫 진입 화면(/) = 검색 화면 (인증 불필요, redirect 없음)
    ↓
검색조건 입력 → 검색 실행 (인증 불필요)
    ↓
같은 페이지 하단에서 검색 결과 / 물건 목록 탐색 (인증 불필요)
    ↓
상세페이지 진입
    ↓ (PM 최종 정책: 프리미엄 회원 전용, 비구독자는 403 + 팝업)
    ※ 이 접근제어는 설계 문서(v2.1)에서 확정됐으나 실제 백엔드 코드에는 아직 미구현
```

2026-08-10 확정: 첫 진입 화면 / 공개·인증 경계 / 검색 화면 구조의 Single Source of Truth는
`search/00_SEARCH_MVP.md` v0.2다. **검색 API 쪽 변경 사항은 없다** — `GET /api/v1/search`와
`GET /api/v1/search/regions`가 이미 인증 없이 동작하고(선택적 Bearer), 파라미터 없는 호출이
기본 물건 목록(`auction_date >= 오늘`)을 반환하므로 프론트 화면 재구성만으로 충족된다.
이 두 엔드포인트의 선택적 인증 구조는 첫 화면 공개 접근의 전제 조건이므로 **필수 인증으로
바꾸지 않는다**.

## 향후 개발 예정

- ~~`status` 필터 추가~~ (2026-08-06 재확인 결과 이미 구현됨)
- ~~`sort_by` / `sort_order` 파라미터 추가~~ (2026-08-06 재확인 결과 이미 구현됨)
- ~~자유텍스트 주소 검색~~ (2026-08-06 재확인 결과 `address_detail`로 이미 구현됨, 위 참고)
- `property_type` ENUM 코드화 (설계만 완료, 미구현 — 여전히 유효)
- 프리미엄 회원 접근제어 (`GET /item/{id}` 403 처리, 설계만 완료, 미구현 — 2026-08-06 `item.py` 재확인, 여전히 유효, `docs/decision-log.md` Premium 결정 참고)
- 위 인덱스 목록 외 추가 성능 전략(캐싱 등) 검토

## 절대 변경하면 안 되는 것

- 데이터 저장소를 SQLite에서 PostgreSQL로 임의 전환하는 것 (PM이 명시적으로 현재 범위 밖으로 결정함)
- `GET /api/v1/search`, `GET /api/v1/item/{item_id}`의 기존 응답 구조
- `GET /api/v1/search`의 offset 페이지네이션 방식 (`page`, `size`)
- `auction_item` 컬럼명 (`case_no`, `item_no`, `minimum_bid_price`, `appraisal_price`, `fail_count`, `auction_date`, `status` 등 이미 확정되어 있는 이름)
- 투자점수 / AI추천 / 수익률 계산 기능 개발 (프로젝트 규칙상 금지)
- `storage/database.py`를 내용 확인 없이 임의로 새로 작성하는 것

## 알려진 문제점

- ~~`storage/database.py`가 저장소에 없음~~ → 2026-08-06 정정. git 이력에는 없지만(`.gitignore`) 작업 디렉터리에는 실재하며 읽을 수 있음. `row_factory=sqlite3.Row` 등 실제 커넥션 옵션은 `docs/backend.md` 참고
- 설계 문서(v1.0~v2.1)와 실제 구현 코드 간 불일치:
  - 페이지네이션: 설계는 cursor / 실제는 offset (여전히 유효, PM 결정으로 offset 유지)
  - ~~`status` 필터, `sort_by`: 설계만 있고 미구현~~ → 2026-08-06 재확인 결과 둘 다 구현되어 있음
  - `property_type`: 설계는 ENUM 코드 / 실제는 자유 문자열 LIKE (여전히 유효)
  - 프리미엄 접근제어(403): 설계만 있고 미구현
- `search`/`item` 엔드포인트는 인증 없이 공개(설계상 의도). `favorites`/`recent-items`/`search-presets`/`registry-requests`/`payments`는 Supabase JWT 인증 적용됨 (`api/auth.py`, 완료)
- `favorites`, `recent_items`, `search_presets`, `subscriptions`, `payments`, `registry_requests` 테이블은 모두 SQLite에 생성 완료(`storage/migrations/001~007.sql`, `migration_history`로 적용 확인). `subscriptions`/`payments`는 2026-08-05부터 `api/v1/payments.py`(Mock)로 실제 write 발생, `registry_usage`/`registry_requests`는 `api/v1/registry.py`가 write (자세한 내용은 `docs/backend.md` 참고)

## 주의사항

- `storage/database.py` 내용을 확인하기 전에는 DB 커넥션 관련 코드를 추측으로 작성하지 않는다.
- 검색엔진 파트의 역할은 검색 정확도 향상, 필터 최적화, 검색 성능 개선이며, DB 마이그레이션은 이번 범위에 포함되지 않는다 (PM 지시).
- 신규 사용자 데이터 테이블(`favorites` 등)은 SQLite에 생성하며, `user_id`는 Supabase UUID를 TEXT로 저장하고 DB FK 제약 없이 애플리케이션 레벨에서 검증한다.
- 기존 엔드포인트(`/search`, `/item/{id}`)의 응답 구조와 페이지네이션 방식은 Breaking Change 없이 유지해야 한다.
