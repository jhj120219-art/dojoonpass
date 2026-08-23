# Project Roadmap

Status: Beta v1

Owner: Project Management

Last Updated: 2026-08-07

---

# Project Vision

콕찰(Kokchal)은 대한민국 법원경매 정보를 수집하고 검색·상세조회·권리분석·등기부 신청 서비스를 제공하는 플랫폼이다.

Beta v1에서는 안정적인 검색 서비스 구축을 목표로 하며,
AI 투자추천이나 자동 투자판단 기능은 범위에 포함하지 않는다.

---

# Current Status

Project Stage

Beta v1 Development

---

# Completed

## Infrastructure

- Next.js 기반 Frontend 구축
- FastAPI Backend 구축
- SQLite 기반 데이터 저장 구조 구축
- 크롤링 파이프라인 구축
- Search API 구축

---

## Search / Detail / Favorite (Release 완료 — 2026-08-05 코드 기준 재확인, 이 영역은 수정 대상 아님)

- 검색 API 구현 + 프론트 `/search` 연동 (`api/v1/search.py`, `src/app/search/*`)
- 상세조회 API 구현 + 프론트 `/properties/[id]` 연동 (`api/v1/item.py`)
- 관심물건 API + 프론트 `/favorites` 연동 (`api/v1/favorites.py`)
- 페이지네이션 구현 (offset 방식 유지)
- (참고) 최근조회 `/properties/recent`, 검색조건 저장 `search_presets.py`도 코드 상 구현·연동되어 있으나 Release 대상 목록에는 별도 명시되지 않음

---

## Authentication (Release 완료)

- Supabase Auth 실제 동작 (로그인/회원가입, `src/app/login/actions.ts`)
- JWT 검증 실제 동작 (`api/auth.py`, `SUPABASE_JWT_SECRET` 필요)
- `proxy.ts`(구 `middleware.ts`)로 `/properties/*` 세션 게이트

---

## Payment / Subscription / Premium / Registry / Admin / Download / PG Prep (Sprint 1~8 완료 — 2026-08-05, PG·실제 등기부 발급기관 연동 제외)

- `POST /api/v1/payments` Mock 결제 API (`api/v1/payments.py`), 결제 성공 시 `subscriptions` row 자동 생성(Sprint 1)
- Premium = `subscriptions` ACTIVE row 존재 여부로 판정 (`registry.py`의 `has_active_subscription()`, 신규 테이블 없음)
- 등기부 신청 프론트 연동 완료: `properties/[id]/page.tsx`가 `registry-requests`/`payments`를 직접 호출, 무료/초과 판단은 백엔드 응답 그대로 반영(프론트 자체 계산 없음). 기존 Supabase `view_counts` 구현(`properties/[id]/actions.ts`)은 삭제(Sprint 3)
- `OVERAGE_USAGE` 결제 성공 시 `registry_requests.payment_id`/`status`(PAYMENT_REQUIRED→PENDING) 자동 연결, 트랜잭션 처리(부분 성공 시 rollback), 중복 결제/레이스 가드 포함(Sprint 4)
- Admin MVP 완료: `api/v1/admin.py` — `registry_requests` 목록 조회(상태/user_id/item_id/case_no 필터) + 상태 전이(PENDING→PROCESSING/FAILED, PROCESSING→COMPLETED/FAILED), `completed_at`/`reason` 기록. 인증은 `X-Admin-Key`(Supabase JWT 아님) — `ADMIN_API_KEY`는 아직 `.env`에 미설정(Sprint 5)
- **등기부 다운로드 엔진 완료(Sprint 6)**: `GET /registry-requests/{id}/download`가 실제 파일을 서빙한다. Admin이 `COMPLETED` 전이 시 `doc_url`(필수)을 지정하면 `registry_documents/`(신규, `.gitignore`)에서 파일을 찾아 반환. 본인 신청만 다운로드 가능(소유권 검사), 경로 탐색 방지(`documents.py`와 동일 패턴). **자동 등기부 수집 엔진이 아니다** — 대법원 인터넷등기소 등 실제 발급기관과의 연동은 없고, 운영자가 수동으로 발급받아 파일을 배치하는 구조
- **등기부 다운로드 UI 완료(Sprint 7)**: `properties/[id]/page.tsx`에 상태별 UI 완성 — `PAYMENT_REQUIRED`→결제 버튼, `PENDING`/`PROCESSING`→상태 표시, `FAILED`→`reason` 표시, `COMPLETED`→"📥 등기부 다운로드" 버튼(클릭 시 실제 파일이 브라우저로 저장됨, `fetch`+`blob`+`<a download>`). `GET /registry-requests`·`{id}` 응답에 `reason` 필드 추가, CORS에 `expose_headers=["Content-Disposition"]` 추가(파일명 노출용) — 실제 브라우저로 다운로드 완료까지 Runtime QA 확인
- **PG Integration Preparation 완료(Sprint 8)**: `api/v1/payment_providers.py` 신규(`PaymentProvider`→`MockProvider`/`TossProvider`/`PortOneProvider`), `PAYMENT_PROVIDER` 환경변수로 선택. `SUBSCRIPTION` 플랜별 가격도 `PLAN_PRICES`로 서버 검증(`OVERAGE_FEE`와 동일 방식). 리팩터링 전후 Registry 체인 100% 동일 동작 Runtime QA 확인
- 미완료(2026-08-06 갱신): KG이니시스 실연동만 남음(계약·API Key 필요). 구독 플랜 UI/등기부 무료한도 정책은 확정 및 코드 반영 완료, 실제 발급기관 자동 연동은 Beta v2 범위

---

# In Progress

## Frontend

- ~~상세페이지 물건 이미지 Gallery~~ → **2026-08-17 Sprint 144 완료**. 대표 이미지 +
  썸네일 줄(지연 로딩) + 라이트박스(이전·다음, ←/→/Esc) + 상태별 빈 화면 안내
  ("수집 중" / "법원이 사진을 제공하지 않습니다" / "가져오지 못했습니다" — 사용자가
  취할 행동이 다르므로 구분한다)
- ~~문서 뷰어 개선~~ → **2026-08-17 Sprint 144 완료**. 페이지 이동(쪽수를 아는 PDF만),
  확대/축소 50~300%, 로딩/실패 상태, 새 탭 열기. 수집 전 문서를 더 이상 링크처럼
  보이게 하지 않는다(예전에는 누르면 "문서를 찾을 수 없습니다"만 뜨는 빈 모달이 열렸다)
- 권리분석 화면 연동 (`rightsAnalysis.ts` REGISTRY 소스 하드코딩 해소) — 2026-08-06 조사 결과 **승인
  필요(DB 스키마 변경)로 확인되어 보류**. `tenant_rights`/`rights_summary`는 STATUS/SPEC 문서
  파싱 결과만 담는 테이블이고, 등기부(REGISTRY) 파싱 데이터를 저장할 테이블 자체가 없음(`docs/backend.md`
  Phase 2의 `registry_rights` 테이블이 아직 미착수) — 등기부 PDF는 크롤러가 수집하지 않고 운영자가
  수동 배치한 원본 파일일 뿐이라 파싱 로직도 없음. 새 테이블 추가(스키마 변경) + OCR/파싱 파이프라인
  신규 구축이 선행되어야 하는 별도 규모의 작업이라 "하드코딩 해소" 한 줄로 될 수 없음 — 사용자 승인 후 별도 Sprint로 재계획 필요
- ~~플랜 비교/선택 UI 신규 구현~~ (2026-08-06 완료 — `properties/[id]/page.tsx`, BASIC/PRO 비교 카드 + 월/연 토글 + 할인가 표시)

## Backend

- ~~등기부 무료 한도 정책 확정~~ → **2026-08-06 확정 + 코드 반영 완료**(플랜별 월 단위: 베이직 5회 / 프로 10회, 월 자동 리셋)
- ~~확정 구독 정책 코드 반영~~ → **2026-08-06 완료**: `BASIC` 12,900원/월·154,800원/년, `PRO` 22,900원/월·연 정상가 274,800원→판매가 198,000원. 할인은 `list_price`/`sale_price` 분리 구조
- ~~`ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY`를 `.env`에 설정~~ → **2026-08-16 재확인
  완료(Sprint 135/138)**: 값 자체는 여전히 열람하지 않았지만(Secret 열람 금지
  원칙), `.env` 직접 grep(이름 존재)에 이어 이번엔 **실제 서버를 기동해 라이브
  응답으로 확인**했다 — `curl`로 키 없이 4개 Admin 엔드포인트를 호출한 결과
  전부 `500 관리자 키 미설정`이 아니라 `403 권한이 없습니다`를 반환한다(코드
  계약상 `os.getenv()`가 빈 값이면 500, 값이 있으면 403이므로 이는 값이 **실제로
  채워져 있다**는 확실한 증거다). `docs/BETA_RELEASE_CHECKLIST.md` P0-2 참고
- ~~`SUBSCRIPTION` 결제 금액 서버 검증~~ (2026-08-05 완료, 2026-08-06 `PLAN_CATALOG` 기준으로 교체 완료)

## Crawler

- 문서수집 안정화
- 자동 실행 안정화
- ~~물건 사진 수집~~ → **2026-08-17 Sprint 144 완료**. 법원 원천에 사진이 실제로
  제공된다는 것을 브라우저 DOM 실측으로 확인하고(표본 7사건) 수집→저장→DB→API→화면을
  전부 신설했다. `document_queue`에 `doc_type='image'`로 편입돼 기존 02:00 worker가
  함께 처리한다 — **다음 정기 실행부터 자동 수집된다**(현재는 E2E 검증분 9물건 45장만
  적재). 자세한 내용은 `docs/SPRINT144_ASSET_PIPELINE.md`
- ~~`doc_raw` 적재 소유권 결정~~ → **2026-08-17 Sprint 144 완료**. Sprint 67/78이
  "쓰는 코드 1곳(스케줄러 미도달)"으로 남겨 뒀던 것을 운영 경로
  (`mark_queue_done()`)에 편입했고, 기존 556건은 `backfill_doc_raw.py`로 백필했다
  (docs/BUGS.md #97)
- ~~현황조사서 물건번호 2 이상 수집~~ → **2026-08-17 Sprint 144+ 완료**(BUGS #100).
  버튼 id를 DOM 실측으로 확정해 `auction_item`의 33.5%(629건)가 현황조사서를 받을 수
  있게 됐다. 다음 정기 `doc_worker` 실행부터 큐(103행 pending)가 소진된다
- **문서 재수집 정책 미결정** — 2026-08-17 규명: 현재 코드는 파일이 이미 있으면
  early-return하고 `overwrite`를 절대 넘기지 않아 **한 번 받은 문서를 다시 받지 않는다**
  (실측: `doc_raw` 556행 전부 doc_version=1). 그 결과 `document_version_log`와
  `mark_queue_done()`의 해시 비교 분기가 **도달 불가능한 코드**다.
  법원이 문서를 정정해도 최초 수집본을 영구히 들고 있게 되므로 데이터 정확성 항목이다.
  결정 사항: 무엇을 언제 다시 받을 것인가(기일 변경 시? 주기적? 해시 확인만 주기적?)

  ★ 2026-08-17 Sprint 184 — **결정에 필요한 것을 실측했다.** 정책은 여전히 제품 판단이라
  정하지 않되, 추측으로 정하지 않도록 아래 사실을 남긴다.

  **(1) 기계는 이미 완성돼 있다.** `overwrite`가 네 수집기(spec/status/appraisal/images)와
  디스패처 `collect_document`에 **전부 배선돼 있다.** 빠진 것은 호출부 하나뿐이다 —
  아무도 `True`를 넘기지 않는다. 그리고 그 경로에는 **테스트가 0건이었다.**

  그래서 "정책을 정하면 곧바로 쓸 수 있는가"가 미지수였다. 그 미지수를 없앴다 —
  `test_asset_pipeline.py` 5-B 신설(11검사)로 다음을 고정했다:

  ```
  overwrite 기본값  파일이 그대로다      (중복 다운로드 방지가 깨지지 않는다)
  overwrite=True    바이트가 실제로 바뀐다 (스킵만 우회하고 저장 누락되는 일 없음)
                    순번/장수 계약 유지, 집합 해시도 바뀐다(= 변경 감지 값이 반응한다)
  ```

  변경 감지 사슬의 나머지도 이미 고정돼 있다 — 해시 함수 정확성(`test_doc_storage_
  atomicity.py`, 8KB 청크 경계 포함)과 `mark_queue_done(prev != new) -> document_version_log`
  경로(Sprint 78 §8). **즉 트리거만 정하면 나머지는 동작한다.**

  **(2) 전면 재수집은 실행 창에 들어가지 않는다.**

  ```
  READY 문서 556건 x 약 12초(#104 수정 후 실측 기준) = 약 1.9시간
  doc_worker 실행 창 02:00~04:00 = 2.0시간
  -> 신규 물건 처리 여지가 사실상 0
  ```

  매일 전면 재수집은 이 창에서 불가능하다. 창을 늘리거나 주기를 낮추는 것(주 1회 등)이
  전제돼야 한다.

  **(3) 표적 재수집은 비용이 거의 없다.** 가장 강한 변경 신호는 **매각기일이 미래로
  다시 잡힌 것**이다(유찰 -> 재매각). 그때가 법원이 문서를 갱신하는 시점과 겹친다.
  그 신호는 이미 감지되고 있다 — `enqueue_documents()`가 큐의 기일을 최신 값으로
  맞추면서 `refreshed` 카운터를 반환한다(Sprint 74).

  ```
  큐와 실제 기일이 다른 행            18
  그중 기일이 미래(살아있는 사건)       9
  재수집 후보(done + 기일 미래)         7 행   -> 약 84초
  ```

  **(4) 그러므로 남은 결정은 두 가지뿐이다.**

  ```
  a. 트리거   전면/주기적 vs "기일이 미래로 바뀐 것만"(현재 7행, 84초)
  b. 되살릴 상태  done 만? failed/SKIPPED_EXPIRED 까지?
  ```

  `enqueue_documents()`는 지금 **일부러 `status`를 건드리지 않는다**(그 자리 주석 참고).
  b를 정하는 순간 그 한 줄이 구현이다. 코드 변경 자체는 작고, 위 5-B가 기계의 동작을
  이미 보증한다. **정책이 정해지기 전에 임의로 되살리지 않는다** — 되살리는 범위에 따라
  매일 재수집량이 7행에서 556행까지 달라지기 때문이다.
- **`parsed_document` 적재는 여전히 미착수** — 쓰는 코드 0곳 / 읽는 코드 0곳.
  `doc_raw`와 같은 계열로 보이지만 그쪽은 "실행 안 되는 코드가 있었던" 것이고 이쪽은
  **구현 자체가 없다**(docs/CURRENT_STATE.md Sprint 78 §3). 다음 스프린트 후보

## Search

- 검색 최적화
- 필터 개선

---

# Next Priority

Priority 1 (완료, 2026-08-05)

- ~~JWT 인증 완료~~ (Release)
- ~~Mock 제거~~ (search/item 등 완료. 단, Payment는 의도적으로 Mock 유지 — PG 미확정)
- ~~실제 API 연결~~ (search/favorites/recent-items/payments Release·Sprint 1 완료)

Priority 2 (대부분 완료, 2026-08-05)

- ~~프론트엔드 결제 UI + `registry-requests` 연동~~ (완료 — `properties/[id]/page.tsx`)
- ~~OVERAGE_USAGE 결제 → registry_requests 자동 연결~~ (완료)
- ~~관리자 페이지(등기부 신청 상태 관리)~~ (MVP 완료, ~~`ADMIN_API_KEY` 설정만 남음~~ →
  **2026-08-16 완료 확인**(위 "In Progress > Backend" 참고), 남은 것은 화면(UI) 부재뿐)
- ~~등기부 무료 한도 정책 확정~~ → 2026-08-06 확정 + 코드 반영 완료(플랜별 월 단위)
- 권리분석 연동 — 2026-08-06 조사 결과 신규 DB 테이블(`registry_rights`) + OCR/파싱 파이프라인이
  선행돼야 하는 스키마 변경 승인 대기 상태로 확인됨(위 "In Progress > Frontend" 참고)
- 문서 수집 API

Priority 3

- ~~등기부 다운로드 엔진(수동 배치 방식)~~ (완료, Sprint 6 — 아래 Beta v2의 "실제 발급기관 자동 연동"과는 별개)
- ~~Payment Provider 구조 분리~~ (완료, Sprint 8 — PG사 확정 전 기반 구조만)
- ~~PG사 확정~~ → **2026-08-06 KG이니시스로 확정(CTO)**, ~~`KGInicisProvider` 신설~~ → **2026-08-07 완료**. 남은 작업: Interface v2 6개 메서드의 실제 API 호출 구현(외부 API Key/계약 필요 — 승인 대기). `TossProvider`/`PortOneProvider`는 폐기 예정 표기 완료
- ~~`ADMIN_API_KEY` 운영 값 설정~~ → **2026-08-16 완료 확인**(위 참고). 역할(role)
  구분은 이미 2단계(ADMIN/SUPER_ADMIN)로 도입돼 있다(`docs/CURRENT_STATE.md` 인가
  매트릭스 — 돈·권한이 움직이는 4개 엔드포인트는 SUPER_ADMIN 전용). 남은 것은
  **등급 안에서 개별 운영자를 구분하는 것**뿐(지금은 등급별 공유키) — 이건 운영
  인원 확장 시 필요한 제품 결정이라 여전히 승인 영역
- 성능 최적화

---

# Beta v1 Scope

포함

- 검색
- 상세조회
- 관심물건
- 최근조회
- 검색조건 저장
- 회원가입
- 로그인
- 구독 UI (등기부 신청 카드 내에서 BASIC/PRO 두 플랜 + 월/연 결제주기를 비교·선택해 구독 가능, 2026-08-06 갱신 — 별도 페이지가 아니라 기존 카드 내 UI로 구현됨)
- 등기부 신청 구조 (백엔드+프론트+Admin MVP+다운로드 엔진까지 완료 — 아래 Success Criteria 참고. 발급기관 자동 연동만 남음)

제외

- AI 추천
- 투자점수
- 수익률 계산
- 자동 투자판단

---

# Future Roadmap

## Beta v2

- 문서 자동 수집
- 권리분석 고도화
- 등기부등본 실제 발급기관(대법원 인터넷등기소 등) 자동 연동 — 현재는 운영자가 수동으로 발급받아 배치(Sprint 6 완료 범위는 "전달" 엔진까지)

---

## Release

- PG 연동
- 결제 완료
- 관리자 기능
- 운영환경 배포
- 성능 최적화

---

# Technical Debt

- ~~Mock API 제거 필요~~ (search/item 등은 완료. Payment의 Mock 결제는 PG 미확정으로 인한 의도적 유지 — 제거 대상 아님)
- ~~JWT 연동 필요~~ (Release 완료)
- ~~등기부 열람 로직 이원화~~ (2026-08-05 해소 — 프론트 `view_counts` 삭제, `registry_usage`로 일원화)
- 문서 수집 안정화
- 검색 최적화
- DB 백업 체계 구축
- ~~`SUBSCRIPTION` 결제 금액 서버 검증 부재~~ → 2026-08-05 해결, 2026-08-06 `PLAN_CATALOG` 기반으로 갱신(할인가 포함 서버 재계산)
- ~~Admin 인증에 역할(role) 구분 없음~~ → **부분 해소**: 2단계(ADMIN/SUPER_ADMIN)
  역할 구분은 이미 도입돼 있다(`docs/CURRENT_STATE.md` 인가 매트릭스 — 돈/권한이
  움직이는 4개 엔드포인트는 SUPER_ADMIN 전용). 다만 **등급 안에서는 여전히
  단일 공유키**(`X-Admin-Key`, MVP 한계)라 같은 등급 내 개별 운영자는 구분할
  수 없다 — 이 부분만 남은 기술부채. 2026-08-07 상태 전이 **감사 로그**는
  추가했으나 단일 키라 "누가" 했는지는 등급까지만 알 수 있다
- ~~bare `except:` / 과잉 `except Exception` / 미사용 import / 함수 내부 import~~ → 2026-08-07 정리 완료
  (AST 전수 재조사 결과 미사용 import 잔여 **0건**)
- ~~API 서버 로깅 설정 부재~~ → 2026-08-07 해소(`logging.basicConfig` + `LOG_LEVEL`)
- ~~프론트/서버 정렬 비결정성~~ → 2026-08-07 전 도메인 `id` tie-break 적용
- **`PLAN_OPTIONS`(프론트) ↔ `PLAN_CATALOG`(서버) 이중 관리** — 드리프트는 회귀 15번이 감지하지만
  구조적으로는 서버가 카탈로그를 내려주는 편이 맞다
- **목록 엔드포인트 LIMIT 부재**(`favorites`/`payments`/`registry-requests`) — 응답 구조 변경 필요
- **`(user_id, status)` 복합 인덱스 부재** — 구독/초과결제 조회가 `status` 인덱스를 타고
  TEMP B-TREE 정렬을 만든다(2026-08-07 실행계획 실측). **2026-08-16 재실측(Sprint 139)**:
  `get_entitled_subscription()`의 실제 쿼리 플랜을 다시 뽑아 확인했다 —
  `SEARCH ... USING INDEX idx_subscriptions_user_id (user_id=?)` 다음
  `USE TEMP B-TREE FOR ORDER BY`가 여전히 뜬다(사실 자체는 그대로 정확).
  다만 이 TEMP B-TREE는 **테이블 전체가 아니라 `WHERE user_id=?`로 좁혀진
  한 사용자의 구독 이력 행만** 정렬한다 — 한 사용자가 평생 만드는 구독 행
  수는 실질적으로 항상 한 자릿수라, 전체 데이터가 아무리 늘어도(사용자
  10만 명이든 100만 명이든) 이 정렬 비용은 늘지 않는다(사용자당 상수 비용).
  즉 "인덱스가 없다"는 사실은 맞지만 **스케일 위험은 아니다** — search
  정렬의 TEMP B-TREE(전체 테이블 대상, `docs/SPRINT134_PERFORMANCE_SCALE_MEASUREMENT.md`)와
  겉모습은 같아도 위험 등급이 다르다. 인덱스 추가는 스키마 변경(승인
  영역)이고 실측상 이득이 미미해 우선순위를 낮춘다
- **외부 예외/로그 수집 없음**(Sentry 등) — 운영에서 과거 로그 추적 불가
- ~~**selenium 미설치**~~ → **2026-08-16 재확인(Sprint 139): 이제 설치돼 있다**
  (`python -c "import selenium"` 성공). 다만 `test_docs.py` 등 **실동작** 테스트는
  여전히 별도 사유로 기본 실행되지 않는다 — 의존성이 아니라
  `ALLOW_LIVE_CRAWL=1` 가드(2026-08-11 Sprint 51, docs/BUGS.md #51) 때문이다.
  이 가드는 의도적 설계다(실제 법원 웹사이트로 나가는 네트워크 호출을
  일상적 회귀에서 막기 위함) — 그대로 유지. 순수 로직 테스트
  (`test_doc_storage_atomicity.py`/`test_crawl_resume.py`)는 2026-08-10
  Sprint 47에 의존성 분리(`crawler/doc_paths.py`/`crawler/resume.py`)로 복구됨
- ~~**`storage/`가 통째로 gitignore**~~ → **2026-08-11 Sprint 51에 해소됨**
  (`docs/CLAUDE.md`가 이미 정정해 둔 내용 — 이번 세션은 문서 대조로 재확인만
  했다). `.gitignore` 규칙이 `storage/*` + `!storage/*.py` + `!storage/migrations/*.sql`로
  정밀화되어 지금은 소스 23개가 정상 추적되고, 데이터 산출물만 무시된다.
  Sprint 47이 겪은 "checkpoint.py 원자적 쓰기(BUGS #23) 유실" 사고의 **구조적
  원인이 제거**됐다는 뜻 — 회귀 테스트가 유일한 안전장치이던 상태에서
  git 이력 자체가 안전장치로 복귀했다

---

# Sprint Backlog

## [완료] PG 명칭 정리 / Admin·Release Audit / 기술부채·회귀 확대 (Sprint 26, 2026-08-07)

배경: KG이니시스 확정(2026-08-06) 이후 코드/문서에 남아있던 Toss 기준 서술을 정리하고,
Beta 출시 기준으로 Admin·전 도메인·성능·보안·문서를 전수 감사한다. 승인이 필요한 작업
(실연동, `.env` 수정, 스키마 변경, 패키지 설치, 파일 삭제)은 전부 Skip하고 기록만 한다.

완료

- **PG**: `KGInicisProvider` 신설(6개 메서드 자리 구현), `PAYMENT_PROVIDER=kginicis` 허용값 추가,
  `toss`/`portone`은 폐기 예정 표기 + 선택 시 경고 로그, 알 수 없는 값은 허용값 목록과 함께 즉시 실패.
  문서 7종의 Toss 기준 서술을 KG이니시스 기준으로 갱신
- **Bug(신규 발견·수정)**: 정렬 비결정성 — `get_user_free_limit()`의 `ORDER BY started_at DESC`가
  전순서가 아니라 플랜 업그레이드 직후 옛 플랜 한도가 적용될 수 있었다(`docs/BUGS.md` #16).
  전 도메인 6개 쿼리에 `id` tie-break 일괄 적용. **Admin 목록은 offset 페이지네이션이라
  동률 행 중복/누락까지 가능했던 지점**
- **Lint 2 → 0**: `react-hooks/set-state-in-effect` 2건을 파생 상태 방식으로 해소.
  부수적으로 문서 뷰어의 늦은 응답 경쟁 상태, 시/군/구 로딩 중 이전 값 잔상도 함께 사라짐
- **기술부채**: bare `except:` 2건 제거, `favorites.py`의 과잉 `except Exception`(DB 오류를
  "이미 등록됨"으로 오안내) 수정, 미사용 지역변수 제거, 함수 내부 import 4건을 모듈 최상단으로
- **Performance**: `doc_stats.py`의 6회 COUNT 스캔 → 단일 `GROUP BY` 1회
- **Security**: CORS 허용 Origin을 `CORS_ALLOW_ORIGINS`로 제한 가능(미설정 시 기존 `*` 유지),
  검색조건 저장 서버측 입력 검증(이름/크기/개수 상한), Admin 인증 실패·상태 전이 감사 로그,
  `documents.py`의 NULL 컬럼 500 → 404
- **UX/Release**: `layout.tsx` 메타데이터가 `create-next-app` 기본값이던 문제 해결(`콕찰`, `lang="ko"`)
- **Test**: 회귀 118 → **163 검사**(Provider 레지스트리 / 정렬 결정성 / 플랜 tie-break / 입력 검증
  / **API 표면 고정** / **응답 envelope 계약** / CORS 설정)
- **문서**: `docs/API_KEY_CHECKLIST.md` 신설 — 요청 카테고리 16종을 전부 코드에서 검색해
  참조 지점까지 기록. 실제로 읽는 env는 8개뿐이고 OAuth/SMTP/Storage/Analytics/Monitoring/
  SNS/OCR/지도/메일은 참조 0건임을 확정. env 드리프트 실측(`.env`의 `SUPABASE_URL`/
  `SUPABASE_ANON_KEY`는 코드가 읽지 않음)
- **Bug(추가 발견·수정) 2건**:
  (1) **API 서버에 로깅 설정 자체가 없어** 같은 날 추가한 Admin 감사 로그(`logger.info`)가
  전량 유실되고 있었다 — 크롤러와 같은 포맷으로 `basicConfig` 추가, `LOG_LEVEL` 도입
  (2) `documents.py`의 GET/HEAD 겸용 라우트가 **같은 operationId를 생성**해 `/openapi.json`
  생성 시마다 경고가 나고 클라이언트 생성이 깨졌다 — 라우트 분리로 해소
- **Architecture**: AST 미사용 import 재조사(47모듈) → 2건 제거 후 잔여 0건.
  미사용 Component/Type 0건 재확인. 프론트 미호출 엔드포인트는 전부 운영/테스트/Admin UI용으로
  의도된 것임을 확인하고 회귀 16번으로 집합을 고정
- **Performance**: 실행계획 실측 — 검색/최근조회/무료횟수는 인덱스 적중. 구독·초과결제 쿼리가
  `status` 인덱스를 타는 문제와 목록 LIMIT 부재는 **스키마/응답 구조 변경이라 미착수·기록**
- **문서 정합성**: CLAUDE(architecture.md 위치), backend(DB 절대경로, **존재하지 않는
  `X-Test-User-Id` 헤더 안내 삭제**), crawler(절대경로), frontend(`components/` 부재·플랜 UI·
  검색조건 저장 UI·평생 누적 한도·로그아웃 미노출 — 전부 stale이었음) 정정

- **Critical 발견**: 레거시 `auction` 테이블의 `UNIQUE(case_no, item_no)`에 법원이 빠져 있어
  다른 법원 물건이 매일 크롤링에서 **소실**된다(`docs/BUGS.md` #18, 사본 DB로 재현).
  승인 없이 가능한 완화 3종 적용(덮어쓰기 WARNING 로그 / `migrate_execute.py` 식별키를
  `(case_id, item_no)`로 차단 / 위험 규모 감시 테스트). 근본 수정인 스키마 변경은 승인 대기
- **TODO 탐색**: 코드 전체 스윕 결과 실제 TODO는 프론트 4건뿐이며 전부 백엔드 미지원 컬럼에
  대한 정직한 표기. `SearchForm.tsx`의 "단일 선택시에만 API 연동" TODO는 stale로 확인(정정)

Skip (승인 필요 — 기록만)

- **`auction` 테이블 `UNIQUE(court_code, case_no, item_no)` 스키마 변경 (#18)** — 데이터 소실 중
- KG이니시스 실연동 6개 메서드 구현 (계약·API Key·Webhook)
- `ADMIN_API_KEY` `.env` 설정
- `src/login/` 죽은 디렉터리 삭제(금지된 옛 브랜드명 사용 중)
- Rate Limit 도입(패키지 설치 필요)
- `registry_requests` 감사 컬럼 추가(스키마 변경)
- `/properties` 화면 처리 방향(Spec), Admin UI 신설(Spec)

---

## [다음 Sprint 후보] Beta 출시 직전 정리 (Sprint 27)

승인 없이 착수 가능한 것부터. 위 Skip 항목의 결정이 나면 그쪽이 우선한다.
**단 `docs/BUGS.md` #18(레거시 `auction` 키로 인한 물건 소실)은 매일 재발하고 되돌릴 수 없으므로
승인만 나면 아래 어느 항목보다 먼저 처리한다.**

1. ~~`properties/[id]/page.tsx`의 stale 주석 정리~~ → **Sprint 26에서 함께 처리**
   (다운로드 501 서술, 존재하지 않는 `registry.py:9 FREE_LIMIT` 참조 정정)
2. ~~`PLAN_OPTIONS` ↔ `PLAN_CATALOG` 정합성 회귀 테스트~~ → **Sprint 26에서 함께 처리**
   (`test_api_regression.py` 15번 — 한도/정상가/청구액 6항목 × 2플랜)
3. ~~`TEST_PLAN.md` / `README.md` 정합성~~ → **Sprint 26에서 함께 처리**.
   `search-engine.md`/`AI_CONTEXT.md`는 감사 결과 코드와 일치해 수정 없음
4. `admin.py`/`search.py`의 `LIKE` 필터에서 사용자 입력의 `%`/`_` 이스케이프 처리 —
   **Sprint 26에서 의도적으로 보류**. 보안 취약점은 아니고(파라미터 바인딩이라 인젝션 불가)
   와일드카드 의미론만 바뀌는 문제인데, `search.py`의 8개 조건 전체를 바꾸면 사용자가 체감하는
   검색 동작이 달라진다 — "Spec 변경 금지" 원칙상 PM 확인 후 착수
5. Admin 목록의 `JOIN auction_item`이 INNER라 물건이 사라진 신청이 목록에서 통째로 빠지는 문제
   (LEFT JOIN 전환 검토 — 현재 DELETE 경로가 없어 실제 발생은 안 하지만 구조적 사각지대)
6. `PLAN_OPTIONS` 미러 자체를 없애는 방향 검토 — 서버가 카탈로그를 반환하는 엔드포인트를 두면
   프론트/서버 이중 관리가 사라진다(현재는 회귀 15번으로 드리프트만 감지)
7. **(승인 필요)** `(user_id, status)` 복합 인덱스 추가 — 활성 구독 조회와 초과결제 대상 선택이
   `status` 인덱스를 타고 TEMP B-TREE 정렬을 만드는 것을 실행계획으로 실측함. 사용자·구독 수가
   늘수록 나빠지는 구조라 Beta 트래픽이 붙기 전에 결정하는 편이 좋다(스키마 변경)
8. **(승인 필요)** `favorites`/`payments`/`registry-requests` 목록 페이지네이션 —
   현재 LIMIT이 없다. 응답 구조가 배열이라 `{total, items}`로 바꾸면 Breaking Change라
   프론트 동시 수정이 필요하다
9. **(승인 필요)** 외부 예외/로그 수집(Sentry 등) 도입 — 2026-08-07에 서버 로깅 설정을 신설했지만
   stdout 스트림뿐이라 운영에서 과거 로그를 되짚을 수 없다. 패키지 설치 필요
10. **(승인 필요)** selenium 설치 — 크롤러 계열 테스트(`test_db.py` 등)가 이 환경에서
   `ModuleNotFoundError`로 실행 불가하다. 크롤러 회귀를 전혀 돌리지 못하는 상태

---

## [완료] Security/Type/Performance Review (Sprint 15, 2026-08-06)

배경: Beta Release 품질 향상을 위해 처음으로 전용 Security Review를 수행. Sprint Backlog(P2)는
UX/Spec 결정이 선행돼야 해 Skip(위 참고), Critical Path는 PG사 확정 대기라 Security Review로 진행.

완료

- `api/v1/*.py` 전체에서 f-string 기반 SQL 조립 지점을 재확인 — `search.py`/`admin.py`/`payments.py`
  모두 컬럼명/연산자만 하드코딩 리터럴이고 실제 값은 전부 `?` 파라미터 바인딩(`params` 리스트)이라
  SQL Injection 여지 없음을 재확인(수정 불필요)
- **발견 및 수정**: `api/v1/admin.py:require_admin()`이 관리자 키를 `x_admin_key != admin_key`
  단순 문자열 비교로 검증하고 있었음 — Python의 문자열 `!=`는 앞에서부터 다른 문자가 나오는
  즉시 반환되어, 비교에 걸리는 시간이 일치하는 접두 길이에 비례하는 타이밍 사이드채널이 이론상
  존재함. `hmac.compare_digest()`로 상수 시간 비교하도록 교체
- `api/auth.py`의 JWT 검증(`algorithms=["HS256"]` 하드코딩)은 알고리즘 혼동 공격 여지 없음을 확인(수정 불필요)
- `api/v1/documents.py`/`api/v1/registry.py`의 경로 탐색 방지(`commonpath` 검사)는 파일명이
  DB 조회 결과의 화이트리스트 값으로만 결정되어 안전함을 재확인(수정 불필요)
- `favorites.py`/`search_presets.py`/`recent_items.py`는 전부 `WHERE user_id=?` 소유권 검사+
  파라미터 바인딩 확인(수정 불필요)
- Runtime QA: `require_admin()`을 직접 호출해 (1) 올바른 키 → 통과, (2) 틀린 키 → 403,
  (3) 키 미제공 → 403, (4) `ADMIN_API_KEY` 미설정 → 500, 4가지 시나리오 모두 수정 전과 동일한
  결과임을 확인(로직 변화 없음, 비교 방식만 상수 시간으로 교체)
- Compile/Import 확인: `python -m py_compile api/v1/admin.py` 통과, `api_server.py` 전체
  import 및 라우트 등록(16개) 정상 확인
- Admin 인증이 여전히 단일 공유키(role 구분 없음)라는 구조적 한계는 이번 Sprint 범위 밖(기존
  MVP 결정 유지, `docs/decision-log.md` 참고) — 타이밍 공격 방어만 추가한 것으로, 키 자체가
  유출되면 여전히 무방비임에 유의

**같은 Sprint, Type 개선**: `src/app/login/actions.ts`의 `loginAction`/`signUpAction`이 쓰던
`prevState: any` 2건을 `login/page.tsx`의 실제 `useActionState` 상태 모양에 맞춰 명시적 타입으로
교체(런타임 동작 무변경, lint 오류 5→3건).

**같은 Sprint, Performance Review**: `api/v1/favorites.py:get_favorites()`가 즐겨찾기 개수만큼
`get_item_summary()`를 반복 호출하던 N+1 쿼리를 `recent_items.py`와 동일한 단일 JOIN 패턴으로
교체. 롤백 트랜잭션 안에서 기존/신규 로직 출력이 완전히 일치함을 확인(Runtime QA), DB 영구
변경 없음.

---

## [완료] run_daily.bat 실패 은폐 구조 개선 (Sprint 13, 2026-08-06)

배경: migrate_execute.py 로그 파일 잠금 버그(2026-07-27 수정 완료) 조사 중, run_daily.bat가
migrate_execute.py 실패 후에도 뒤따르는 echo 명령 때문에 배치 자체의 종료코드가 0(성공)으로
남는 구조적 결함이 확인됨. Task Scheduler의 LastTaskResult가 실제 내부 실패를 반영하지 못함.

완료

- 재확인: `run_daily.bat`는 `mvp_scraper.py`/`migrate_execute.py` 실행 줄 뒤에 조건 없는
  `echo` 2줄이 항상 실행되는 구조라, 두 스크립트가 0이 아닌 exit code로 끝나도 배치의
  마지막 명령(`echo`, 항상 성공)이 배치 전체 종료코드를 결정해 항상 0으로 남는 것을 확인함.
  `migrate_execute.py`는 이미 `sys.exit(0)/sys.exit(1)`을 정확히 반환하고 있어 이 값을
  bat가 그냥 확인만 안 하고 있었음
- `mvp_scraper.py` 실행 직후 / `migrate_execute.py` 실행 직후 각각 `if errorlevel 1`으로
  즉시 확인 → 실패 시 다음 단계로 진행하지 않고 `exit /b 1`로 즉시 종료
- 실패한 스크립트명과 종료코드를 `logs\daily_run.log`에 `[FAILED] <script>.py exited with
  code %errorlevel% at <timestamp>`로 명시 기록. 성공 시에도 `[SUCCESS] Finished at
  <timestamp>`로 구분 기록
- Runtime QA: 격리된 스크래치 디렉터리에서 동일 구조의 더미 배치 파일로 (1) 1단계 실패 → 2단계
  건너뜀 + 배치 exit code 1 + 실패 로그 기록, (2) 전체 성공 → 배치 exit code 0 + 성공 로그
  기록, 두 시나리오 모두 실제 cmd.exe 실행으로 재현·확인함(실제 크롤러는 courtauction.go.kr에
  대한 실제 크롤링을 유발하므로 이번 QA에서 직접 실행하지 않음)
- `run_doc_worker.bat`/`run_priority_refresh.bat`는 각각 파이썬 호출이 마지막 명령이라 이미
  자신의 exit code가 배치 exit code로 정상 전파됨을 확인 — 수정 대상 아님
- `mvp_scraper.py` 내부의 법원(court)별 개별 try/except(부분 실패 시에도 계속 진행)는 기존
  설계 그대로 유지 — 이번 Sprint는 bat 구조 개선만 범위, 크롤러 내부 예외 처리 정책 변경은
  범위 밖(변경 시 별도 Sprint 필요)

---

## [P2] 로그인 UX 개선 — 비회원 검색 우선 흐름

배경: 현재는 첫 화면에서 로그인부터 시작하는 UX. 향후에는 비회원도 검색/검색결과까지는
볼 수 있고, 상세 진입 시점에 로그인을 요구하는 흐름으로 변경할 계획.

목표(다음 Sprint 후보, 이번 Sprint는 등록만)

- 비회원 → 검색 → 검색결과 → 상세 진입 시 로그인 흐름으로 전환
- 현재 `/properties/*`를 게이트하는 middleware 인증 로직 재검토 필요 (docs/CLAUDE.md 참고)

이번 Sprint 범위: 등록만 함. 구현하지 않음.

2026-08-10 업데이트: **이 항목은 스펙이 전부 확정됐다** — `docs/FRONTEND_MASTER_SPEC.md`(신규,
Frontend 최상위 기준) + `search/00_SEARCH_MVP.md` v0.2(검색 화면 상세).

- 첫 화면: `/`의 무조건 redirect(`src/app/page.tsx`)를 제거하고 `/` 자체를 검색 화면으로 만든다
- 공개 범위: 검색 / 결과 / 목록 탐색 / 정렬 / 페이지 이동까지 비로그인 허용
- **상세(`/properties/[id]`)는 로그인 필수로 확정** — "무엇을 보여줄지"는 더 이상 미결정이 아니다.
  비로그인은 목록까지 보고, 물건 클릭 시 로그인으로 이동한 뒤 원래 상세 URL로 복귀한다.
  `middleware.ts`의 `/properties/*` 게이트는 이 정책과 일치하므로 유지하고, redirect가
  쿼리스트링을 버리는 결함만 수정한다
- 검색 API 변경 없음

**2026-08-10 Sprint 44에서 P0·P1 구현 완료** — 첫 화면 redirect 제거(`/`=검색 화면),
`/`·`/search` 화면 공유(`SearchScreen`), 검색 실행의 pathname 유지, 공통 Header(`SiteHeader`),
1320px 컨테이너 단일화(`src/lib/layout.ts`), 반응형 1/2/3열, 로그인 redirect의 쿼리스트링 보존
(middleware + 상세 액션 3곳), 로그인 기본 복귀 경로 `/`. 자세한 내용은 `docs/CHANGELOG.md`.

**2026-08-10 Sprint 45**: 프론트엔드 자동 테스트 신규(`npm run test:frontend`, 20검사,
Node 내장 러너 — 새 의존성 없음), 상세 화면 공통 Header 적용(네비게이션 막다른 길 해소),
Backlog 6건 코드 근거로 조사 완료(`docs/CHANGELOG.md`).

남은 것: `/properties` 레거시 화면 처리(미결정 — 코드상 inbound 링크 0건인 고아 상태로 확정)와
아래 환경 이슈.

**[해결됨 · 2026-08-10 Sprint 46]** 로그인 사용자의 Supabase JWT를 FastAPI가
401로 거부한다(`docs/BUGS.md` #27). Supabase 프로젝트가 **ES256 비대칭 서명으로 전환**됐음을
JWKS 엔드포인트(200, `kty=EC`/`alg=ES256`)로 확인했는데, 백엔드 검증 3곳
(`api/auth.py:20-23`, `api/v1/item.py:47-48`, `api/v1/search.py:145-146`)이 여전히
`algorithms=["HS256"]` + 공유 시크릿 고정이다. ES256 토큰은 이 방식으로 원리상 검증되지 않는다.

**Secret 교체로는 해결되지 않는다 — 검증 코드를 JWKS 기반 ES256으로 바꿔야 한다**
(`python-jose`가 이미 지원하므로 신규 라이브러리 불필요, `kid` 기반 키 선택 + 캐시 필요,
전환기에는 HS256 병행 허용 권장). Sprint 46에서 JWKS 기반 ES256 검증을 도입해 **해결**했다(HS256 병행 유지, `docs/BUGS.md` #27).
실제 Supabase 토큰으로 401 → 200 전환을 확인했다. **API 서버 완전 재기동 필요.**

2026-08-06(Sprint 15) 재확인: `/search`는 이미 비로그인 접근 가능(기존 구현, `middleware.ts`가
`/properties/*`만 게이트). 남은 범위는 "상세(`/properties/[id]`) 진입 시 무엇을 보여줄지"인데
— 전체 정보를 다 보여줄지, 일부만 보여주고 로그인 유도 배너를 띄울지, 로그인 모달로 막을지 등
UX/정책이 확정되지 않은 상태. 이건 코드 구현 문제가 아니라 화면 스펙(Spec) 결정이 선행돼야
하는 항목이라(이번 세션 원칙상 "Spec 변경 금지"), 임의로 범위를 정해 구현하지 않고 Skip함.
PM이 "상세 페이지에서 비회원에게 무엇을 보여줄지" 결정하면 바로 착수 가능.

---

## [완료] Payment Sprint 2~4 — 프론트 연동 / 결제-Registry 연결 / Admin MVP

배경: Sprint 1(2026-08-05)에서 `payments`/`subscriptions`/Premium 판정까지 백엔드 체인은
Runtime QA로 검증 완료. 이후 3개 Sprint에 걸쳐 아래를 완료함(계획했던 "Sprint 2" 범위 중
무료한도 정책 확정만 남고 나머지는 완료):

- ~~`registry_requests`/`payments` 프론트 연동~~ (완료 — `properties/[id]/page.tsx`, Supabase `view_counts` 삭제)
- ~~`registry.py`의 PAYMENT_REQUIRED 분기와 `payments`(OVERAGE_USAGE) 실제 연결~~ (완료 — 트랜잭션/중복방지/rollback 포함)
- ~~관리자 페이지(MVP)~~ (완료 — `api/v1/admin.py`, 목록조회+상태전이+completed_at/reason)
- 미완료: 등기부 무료 한도 정책 확정(평생 vs 월), 구독 플랜 비교/선택 UI, `ADMIN_API_KEY` 운영 설정

---

## [완료] PG Integration Preparation Sprint (Sprint 8, 2026-08-05)

배경: PG사(Toss/PortOne 등)가 아직 미확정이라 실제 승인 연동은 만들 수 없지만, 그 전에
결제 로직을 Provider 구조로 분리해두면 PG사 확정 후 교체 범위를 최소화할 수 있음.

완료

- `api/v1/payment_providers.py` 신규: `PaymentProvider`(인터페이스) → `MockProvider`(사용 중)
  / `TossProvider`·`PortOneProvider`(자리만, `NotImplementedError`)
- `payments.py`의 `create_mock_payment()` → `create_payment_record()`로 교체, `provider.charge()`
  결과를 그대로 기록 — 라우터가 SQLite에 직접 쓰는 기존 구조는 그대로 유지(서비스 계층 아님)
- 환경변수 `PAYMENT_PROVIDER`(mock/toss/portone, 기본값 mock) 도입 — 미설정 시 기존과 100% 동일 동작
- ~~`SUBSCRIPTION` 플랜별 가격 서버 검증~~ 완료: `PLAN_PRICES`(`BETA_EARLYBIRD`=9,900원, `STANDARD`=22,900원) 도입, `OVERAGE_FEE`와 동일한 방식
- Runtime QA로 Subscription/Overage/Registry/Premium/Download 체인이 리팩터링 전후 100% 동일하게 동작함을 확인

남음 (PG사 확정 후)

- PG사 확정 (사용자/PM 의사결정 필요, 코드로 판단 불가)
- `TossProvider`/`PortOneProvider` 실제 구현(결제창 연동, 승인 API 호출)
- 결제 승인 콜백/웹훅 → `payments.status` 갱신, 실패/취소 처리
- `PAYMENT_PROVIDER`를 `.env`에 실제 값으로 설정

---

## [완료] Payment Final Audit Sprint (Sprint 9, 2026-08-05)

배경: PG 실연동 전 마지막 감사. 새 기능이 아니라 남아있는 Risk 제거가 목적이며, 이번
Sprint에서는 코드 수정 없이 감사만 수행함(다음 Sprint에서 수정 예정).

완료 (감사 항목)

- Payment 상태 전이: `SUCCESS`(실사용), `FAILED`(구조상 존재하나 MockProvider가 항상 SUCCESS라
  현재 도달 안 함), `PENDING`(컬럼 DEFAULT로만 존재, 실제로 쓰인 적 없음), `REFUNDED`(코드
  0건, 환불 기능 자체 없음) — 죽은 상태 2개 확인
- DB 정합성: SQLite FK가 앱에서도 강제되지 않음(`PRAGMA foreign_keys` 없음) 확인. 단 DELETE
  경로가 없어 실제 orphan은 없음. Rollback은 `payments.py`/`admin.py`는 명시적, `registry.py`는
  암묵적(`conn.close()`의 자동 rollback, 실측 확인)이라 안전하지만 일관성 문제로 기록
- Provider 구조: 실제 Toss/PortOne 연동에는 부족함 확인 — 웹훅/재검증/멱등성 개념이 빠짐
- Payment 정책: `PLAN_PRICES`/`OVERAGE_FEE`/무료정책/30일정책 모두 코드-문서 100% 일치 확인(수정 불필요)
- **Security: 등기부 무료횟수 레이스 컨디션을 스레드 동시 요청으로 실제 재현 — 5회 제한이 8회까지
  뚫림을 확인 (Release Blocking)**
- Runtime QA: Subscription/Premium/Registry/Download/Admin/Payment/Search/Detail/Favorite 전부 회귀 통과

다음 Sprint(수정 필요)

- ~~등기부 무료횟수 레이스 컨디션 수정~~ → **Sprint 10에서 완료**(아래 참고)

---

## [완료] Release Blocking Fix — Registry Free Limit Race Condition (Sprint 10, 2026-08-05)

배경: Sprint 9(Payment Final Audit)에서 실증한 Release Blocking 버그를 수정. 다른 기능은
건드리지 않음.

완료

- `registry.py:create_registry_request()`에 `conn.isolation_level = None` + `BEGIN IMMEDIATE`
  적용 — 무료횟수 확인(`get_free_count()`)과 INSERT를 하나의 원자적 트랜잭션으로 묶음
- `payments.py`의 `OVERAGE_USAGE`(조건부 UPDATE+rowcount)와 목적은 같지만, 이쪽은 COUNT
  집계값을 다루므로 row 단위 조건부 UPDATE로는 막을 수 없어 트랜잭션 자체를 직접 제어
- 기존 API 응답 구조, Frontend, DB 스키마는 전혀 변경하지 않음(요청대로)
- Runtime QA: 5/10/20 스레드 동시 요청 테스트 전부에서 정확히 5건만 무료 처리, 나머지는
  `PAYMENT_REQUIRED`로 정상 처리됨을 실증 확인(수정 전엔 5스레드로도 8건까지 초과됐음)
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과

---

## [완료] Payment Provider Interface v2 (Sprint 11, 2026-08-05)

배경: 실제 PG(Toss/PortOne) 연동을 위해 Provider 인터페이스를 확장. 실제 PG API 호출,
Webhook 서버, Frontend, DB 스키마는 이번 Sprint 범위에서 제외.

완료

- `PaymentProvider`에 5개 메서드 추가: `create_order()`(주문 생성) / `confirm_payment()`(결제
  승인) / `cancel_payment()`(취소·환불) / `verify_payment()`(서버가 PG API로 재확인) /
  `handle_webhook()`(Webhook payload 정규화) — 기존 `charge()`는 그대로 유지
- `MockProvider`가 6개 메서드(기존 `charge()` + 신규 5개) 전부 구현, 항상 성공 응답
- `TossProvider`/`PortOneProvider`는 여전히 자리만 — base class의 `NotImplementedError`를
  그대로 상속해 6개 메서드 모두 호출 시 명확히 실패함을 확인
- **`api/v1/payments.py`는 전혀 수정하지 않음** — 여전히 `charge()`만 호출, 신규 5개 메서드는
  아직 어떤 엔드포인트에서도 호출되지 않음(다음 Sprint에서 PG사 확정 후 연결 예정)
- Runtime QA: `MockProvider`로 주문 생성→결제 승인→검증→취소→Webhook Mock 전체 흐름 직접 호출
  검증. `TossProvider` 선택 시 6개 메서드 전부 `NotImplementedError` 확인
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과(무변경 확인)

---

## [완료] Payment Flow Migration (Sprint 12, 2026-08-05)

배경: Sprint 11에서 Interface v2를 만들었지만 `payments.py`는 여전히 `charge()`만 호출했다.
이번 Sprint에서 실제 PG 흐름과 동일한 순서로 연결한다. 실제 PG API/Webhook 서버는 여전히 금지.

완료

- `payments.py:create_payment_record()`가 `provider.charge()` 대신 `create_order()` →
  `confirm_payment()` → `verify_payment()` 순서로 provider를 호출하도록 변경
- `MockProvider`는 그대로 사용(수정 없음), `TossProvider`/`PortOneProvider`는 여전히 구현 금지
- 반환 시그니처(`payment_id`, `status`)는 그대로 유지 — 호출부(구독 생성/등기부 연결 로직)는
  전혀 수정하지 않음
- Runtime QA: `SUBSCRIPTION`/`OVERAGE_USAGE` 둘 다 새 Flow로 정상 동작(결제 SUCCESS, 구독
  생성, 등기부 `payment_id` 연결까지 확인)
- Subscription/Premium/Registry/Payment/Download/Admin/Search/Detail/Favorite 전부 회귀 통과
- `cancel_payment()`/`handle_webhook()`은 이번에도 연결하지 않음(환불·Webhook 엔드포인트 자체가
  없어 범위 밖)

---

## [완료] Registry Download Engine Sprint (Sprint 6, 2026-08-05)

배경: Admin MVP(상태 관리)는 완료됐으나 `GET /registry-requests/{id}/download`가 여전히
`501`이었음. `documents.py`/`document_queue`/`doc_worker`를 분석한 결과, 기존 크롤러
파이프라인은 STATUS/SPEC/APPRAISAL(법원 공개 서류)만 다루고 등기부등본(대법원 인터넷등기소
발급)은 애초에 수집 대상이 아니었음(`doc_crawler.py:collect_document`에 registry 타입 자체가
없음) — 자동 수집 엔진을 새로 만드는 것은 실제 발급기관 연동이 필요한 별도 프로젝트 규모라
이번 Sprint 범위 밖으로 판단.

완료

- `registry_documents/`(신규, `.gitignore`) + Admin `doc_url`(COMPLETED 시 필수) → 실제 파일 서빙
- 본인 신청만 다운로드 가능, 경로 탐색 방지(`documents.py`와 동일 패턴)
- 상태별 정확한 메시지 반환(PENDING/PROCESSING/FAILED 등, 거짓 UI 없음)

남음(Beta v2 범위로 이관)

- 대법원 인터넷등기소 등 실제 발급기관과의 자동 연동(현재는 운영자가 수동으로 발급받아 배치)

---

## [완료] Registry Download UI Sprint (Sprint 7, 2026-08-05)

배경: Sprint 6에서 백엔드 다운로드 엔진은 완성했으나, 프론트(`properties/[id]/page.tsx`)에는
`COMPLETED` 상태여도 실제로 파일을 내려받는 버튼이 없었음(직전 Sprint 보고에서 발견된 gap).

완료

- 상태별 UI 완성: `PAYMENT_REQUIRED`→결제 버튼(기존), `PENDING`/`PROCESSING`→상태 표시(기존),
  `FAILED`→`reason` 표시(신규), `COMPLETED`→"📥 등기부 다운로드" 버튼(신규)
- `handleDownloadRegistry()`: `GET /registry-requests/{id}/download` 호출 → 응답이 JSON(미완료)인지
  실제 파일(COMPLETED)인지 `Content-Type`으로 판별 → 파일이면 `blob`+`<a download>`로 브라우저 다운로드 실행
- `registry.py`의 `GET /registry-requests`·`{id}`에 `reason` 필드 노출 추가(기존 필드 유지, 추가만)
- `api_server.py` CORS에 `expose_headers=["Content-Disposition"]` 추가 — 브라우저가 기본적으로
  숨기는 헤더를 노출해 실제 파일명(`19.pdf` 등)을 프론트가 읽을 수 있도록 함
- Runtime QA: 실제 브라우저(Chrome)에서 버튼 클릭 → `Downloads` 폴더에 실제 파일 저장 확인
  (Supabase 실로그인 세션이 없는 환경이라, 코드와 동일한 fetch+blob+anchor 로직을 실제 백엔드에
  대해 실행하는 최소 테스트 페이지로 검증 — 아래 Runtime QA 절 참고)

---

# Risks

- ~~[Release Blocking] 등기부 무료횟수 레이스 컨디션~~ → 2026-08-05 Sprint 10에서 수정 완료(`BEGIN IMMEDIATE`, 5/10/20 스레드 테스트로 재검증)
- `registry-requests` POST가 이제 DB 전체 쓰기 락을 잠깐 선점한다(`BEGIN IMMEDIATE`) — 현재 트래픽 규모에선 문제 없으나, 등기부 신청이 폭증하면 다른 쓰기 요청과의 대기 시간 증가 가능성 있음(모니터링 필요, Non-blocking)
- SQLite 단일 DB 운영
- 문서 수집 실패 가능성
- ~~PG사 미확정으로 인한 Payment Mock 장기화~~ → 2026-08-06 KG이니시스 확정으로 의사결정 병목은 해소. 다만 계약/API Key 발급이라는 **외부 절차**가 새 병목이며, 그동안 Mock 상태는 계속 유지됨
- ~~등기부 무료한도 정책(평생 vs 월) 미확정~~ → 2026-08-06 확정(플랜별 월 단위)
- ~~확정 Spec과 코드의 불일치~~ → 2026-08-06 해소(구독 정책 코드 반영 완료). 다만 기존 `BETA_EARLYBIRD` 구독 row가 운영 DB에 있다면 새 플랜으로 해석되지 않아 `DEFAULT_FREE_LIMIT`(5)로 폴백한다 — 이관 방침 미정(동작은 안전)
- ~~`SUBSCRIPTION` 결제 금액 서버 미검증~~ → 2026-08-05 해결(Sprint 8)
- ~~Payment Provider 인터페이스가 실제 Toss/PortOne 흐름을 수용하지 못함~~ → 2026-08-05 Interface v2로 해결, 같은 날 `payments.py`가 `create_order`/`confirm_payment`/`verify_payment` 3개를 실제로 호출하도록 연결 완료(Sprint 12). `cancel_payment`/`handle_webhook`은 여전히 미호출(환불·Webhook 엔드포인트 자체가 없어 PG사 확정 후 작업)
- Admin 인증이 단일 공유키(`X-Admin-Key`)라 유출 시 전체 Registry 상태를 조작당할 위험 — 운영 전 역할 구분/키 로테이션 정책 필요. 2026-08-06(Sprint 15) 키 비교 자체를 `hmac.compare_digest`로 타이밍 공격에는 방어했으나, 키가 유출되면 여전히 무방비(role 구분 없음 — 위험 자체는 그대로, 공격 벡터 하나만 줄어듦)
- **[Release Blocking, 2026-08-06 Sprint 16 발견]** `auction_case.case_no` 전국 단일 UNIQUE 제약으로 서로 다른 법원의 동일 사건번호가 병합됨(실측 3건 충돌 확인). Schema 변경(UNIQUE 복합키) + Migration 필요 — 승인 대기, 자세한 내용은 `docs/BUGS.md` #14 · `docs/crawler.md` 알려진 문제점 6번 참고

---

# Success Criteria

Beta v1 출시 기준

- 검색 가능 (완료)
- 상세조회 가능 (완료)
- 로그인 가능 (완료)
- 관심물건 가능 (완료)
- 최근조회 가능 (완료)
- 검색조건 저장 가능 (완료)
- Registry 신청 가능 — **완료** (백엔드+프론트+Admin MVP, 2026-08-05). 단 실제 문서 발급 자동화는 별도(Beta v2 범위)

---

# Out of Scope

다음 기능은 Beta v1 범위가 아니다.

- 투자점수
- AI 추천
- 수익률 계산
- 자동 권리분석 생성
- 자동 투자 의사결정

---

# 진행률 재계산 (2026-08-05, Payment Flow Migration 반영, 코드 기준)

## 도메인별 상태

| 도메인 | 상태 | 근거 |
|---|---|---|
| Search | 완료 | `api/v1/search.py` + `src/app/search/*`, D7 종결물건 기본 필터 포함 |
| Detail | 완료 | `api/v1/item.py` + `src/app/properties/[id]/page.tsx` |
| Favorite | 완료 | `api/v1/favorites.py` + `src/app/favorites/page.tsx` |
| Authentication | 완료 | Supabase Auth + `api/auth.py` JWT 검증 |
| Payment | 진행 중(Flow 준비 완료) | Mock API 완료, `OVERAGE_USAGE`/`SUBSCRIPTION` 금액검증 완료, Provider 인터페이스 분리(Sprint 8) + Interface v2(Sprint 11) + `payments.py`가 실제 PG 흐름과 동일한 순서(`create_order`→`confirm_payment`→`verify_payment`)로 provider를 호출하도록 연결(Sprint 12) 완료. PG사 확정(KG이니시스) + `KGInicisProvider` 클래스 신설(2026-08-07)까지 끝나, 남은 것은 그 6개 메서드의 실제 API 호출 구현뿐 — 흐름 구조 자체는 실연동 준비 완료 |
| Subscription | 진행 중 | 결제 성공 시 자동 생성 완료, 플랜별 가격 서버 검증 완료(Sprint 8). 플랜별 기간 정책은 여전히 미확정(30일 고정은 가정값) |
| Premium | 완료 | `has_active_subscription()`으로 판정, Registry 신청 경로에서 실제 게이트로 사용 중 |
| Registry | **완료 (Release Blocking 해소)** | 신청(프론트 연동) → 무료/초과 판단(백엔드, `BEGIN IMMEDIATE`로 동시성 안전 확보) → 결제 연결(자동) → Admin 상태 관리(MVP) → 실제 문서 다운로드(백엔드+프론트)까지 전체 체인 확인. 5/10/20 스레드 동시 요청 테스트로 무료 한도가 절대 초과되지 않음을 재검증 |
| Admin | 완료(MVP) | `api/v1/admin.py` — 목록조회/필터/상태전이/completed_at/reason/doc_url 전부 Runtime QA 확인. `ADMIN_API_KEY` 미설정으로 현재는 즉시 사용 불가 |

## 전체 진행률(%)

- Beta v1 Success Criteria 7개 항목 기준: **7/7 완료**였으나, 2026-08-06 Sprint 16에서 새 Release Blocking 항목 발견(`auction_case.case_no` 전국 UNIQUE 충돌, 위 Risks/`docs/BUGS.md` #14 참고) — Search/Detail 화면 자체는 지금 당장 안전하지만(잠재적 데이터 오염이 아직 사용자에게 노출되는 필드에 닿지 않음), DB Schema 변경 승인이 있어야 코드로 해결 가능한 상태라 "완전히 알려진 버그 없음"이라고는 더 이상 말할 수 없음(발급기관 자동 연동은 Beta v2 범위로 애초에 제외, 이 항목과는 무관)
- Payment 도메인을 "PG 실연동까지 포함한 완전한 결제 기능" 기준으로 보면: Mock 체인 **100% 동작**(동시성 안전 포함), 금액 검증(구독+초과분) **100% 완료**, Provider 인터페이스 확장(Interface v2) 완료, **`payments.py`가 실제 PG 흐름 순서(주문→승인→검증)로 provider를 호출하도록 연결 완료(Flow Migration)**. PG 실연동 포함 시 **약 92%**(2026-08-07 `KGInicisProvider` 신설로 상승 — 남은 건 그 6개 메서드의 실제 KG이니시스 API 호출 코드 + 환불/Webhook 엔드포인트뿐, 나머지 엔드포인트 구조는 더 손댈 곳이 없음)

## Beta 남은 작업

1. `ADMIN_API_KEY`를 `.env`에 설정 (Admin MVP 자체는 완료, 이 값만 없으면 500)
2. ~~등기부 무료 한도 정책 확정~~ → **2026-08-06 확정**(플랜별 월 단위: 베이직 5회/프로 10회). 남은 것은 **코드 반영**(현재 `FREE_LIMIT=5` 평생 누적)
3. ~~확정 구독 정책 코드 반영~~ → **2026-08-06 완료**(플랜명/가격/연 결제/등기부 월 리셋 전부 반영)
4. ~~PG사 확정~~ → **2026-08-06 KG이니시스 확정**, ~~`KGInicisProvider` 신설~~ → **2026-08-07 완료**. 남은 것은 6개 메서드의 실제 API 호출 구현(외부 API Key/계약 필요, 승인 대기)
5. 환불 엔드포인트(`cancel_payment` 호출부), Webhook 수신 엔드포인트(`handle_webhook` 호출부) 신규 구현 — 이 둘은 여전히 어디서도 호출되지 않음
5. ~~구독 플랜 비교/선택 UI~~ (2026-08-06 완료, Sprint 14), Admin 역할(role) 구분(여전히 미착수)
6. (Beta v2) 등기부등본 실제 발급기관 자동 연동 — 현재는 운영자 수동 배치

## Critical Path

```
[PG사 확정] ✅ 2026-08-06 KG이니시스로 확정 완료 (CTO)
     │
     ▼
[KGInicisProvider 클래스 신설 + PAYMENT_PROVIDER=kginicis 허용값] ✅ 2026-08-07 완료
(6개 메서드는 NotImplementedError 자리 구현. TossProvider/PortOneProvider는 폐기 예정 표기)
     │
     ▼
[KG이니시스 계약 + API Key 발급]  ← 현재 여기 (승인/외부 절차 필요)
     │
     ▼
KGInicisProvider의 Interface v2 6개 메서드를 실제 API 호출로 구현
     │
     ▼
환불(cancel_payment)·Webhook(handle_webhook) 수신 엔드포인트 신규 구현
     │
     ▼
PAYMENT_PROVIDER를 .env에 설정(kginicis)
```

병렬 진행 가능(코드 작업, PG 계약과 무관): **확정 구독 정책 코드 반영** — 플랜명/가격/연 결제/
등기부 월 리셋. 승인만 나면 외부 의존성 없이 즉시 착수 가능해 실질적으로 가장 먼저 처리 가능한 항목.

등기부 무료횟수 레이스 컨디션(Sprint 9에서 발견, Sprint 10에서 수정)이 이 Payment Critical Path에서는
완전히 빠졌다 — Payment 경로만 놓고 보면 남은 것은 PG사 확정 이후의 실연동뿐이다. 단, 2026-08-06
Sprint 16에서 **별개의 새로운 Release Blocking 항목**이 발견됨(위 Risks 참고): `auction_case.case_no`
전국 UNIQUE 충돌 — Search/Detail 자체는 지금 당장 안전하지만(`auction_item.court_name`은 정상),
DB 스키마 변경 승인이 있어야 코드로 고칠 수 있는 상태라 이번 세션에서는 구현하지 않고 발견만 기록함.

`ADMIN_API_KEY` 설정과 등기부 무료 한도 정책 확정은 위 경로와 무관하게 언제든 병행 가능하다
(코드 작업이 거의 없는 운영/정책 결정). 이전 회차의 "프론트 결제 UI + registry-requests 연동",
"Registry-Payment 연결", "Admin MVP", "Registry Download Engine", "Payment Provider 구조 분리"는
모두 완료되어 Critical Path에서 제외됨 — **Beta 출시 관점에서 남은 코드 작업은 "PG사가 확정된
이후" `KGInicisProvider`의 6개 메서드를 실제 API 호출로 구현하는 것뿐이다.** 그 전까지 코드 쪽에서
할 수 있는 준비는 이번 Sprint로 전부 끝났다. 등기부 발급기관 자동 연동은 Beta v2로 이관되어
Beta 출시를 막지 않는다.
---

## 2026-08-11 (Sprint 49) 이후 남은 작업 — Frontend

Sprint 49는 `/ → 검색 → 결과 → 정렬/페이지 → 물건 클릭 → 로그인 → 원래 상세 복귀 → 상세 →
즐겨찾기/최근조회/검색조건 저장 → 로그아웃` 동선을 실제 브라우저로 완주 검증했다.
검색·인증·개인화 경로는 **동작한다**. 아래는 그 과정에서 남은 것들이다.

### Release 전 결정 필요 (P0 판단 대상)

1. **물건종류 검색 어휘 불일치** (`docs/BUGS.md` #33) — 검색 UI의 69개 항목 중 60개가 항상
   0건이고, DB 행의 약 40%(745/1,870)가 이름으로 도달 불가능하다. 세 가지 해결책
   (① UI 어휘를 DB 값으로 교체 ② 백엔드 동의어 매핑 ③ 크롤러 정규화) 중 어느 쪽으로 갈지
   결정이 필요하다. `상가,오피스텔,근린시설` 같은 복합값 처리 방침도 함께 정해야 한다.
   **결정만 나면 코드 작업은 크지 않다**(①은 상수 배열 교체, ②는 매핑 테이블 1개).

### 승인 대기 (코드로는 더 진행 불가)

2. 레거시 `/properties` 처리 방향(FastAPI 전환 vs 화면 폐지) — Sprint 48에서 inbound 링크
   0건(고아 라우트) 확정. 삭제/redirect는 정책 결정
3. `formatPrice` 표기 기준 통일(공용 `formatPrice()` vs `formatPriceEok()`) — UX 결정
4. 결과 목록 table 뷰, `SortBar`의 `crawl_date` 정렬 노출, 마이페이지/Admin/권리분석 화면

### 기술부채 (동작에는 영향 없음)

5. ~~**Next.js 16 `middleware` → `proxy` 규약 전환**~~ → **2026-08-11 Sprint 50 완료**.
   `src/middleware.ts` → `src/proxy.ts`, `export async function middleware` →
   `export async function proxy`. 인증 로직은 주석을 제외하면 **문자 단위로 동일**함을
   `git show HEAD:src/middleware.ts`와 정규화 비교로 확인했다. `export const config = { matcher }`는
   Next가 두 규약을 동일 취급(`isMiddlewareFile()`)해 그대로 동작한다. 유일한 실질 변화는
   Next가 강제하는 런타임(Edge → Node.js)이며 `@supabase/ssr`은 양쪽 모두 지원한다.
   빌드 경고 소멸 확인, 계약 테스트에 규약 회귀 3검사 추가
6. **정렬 3종의 TEMP B-TREE** — `bid_rate` / `crawl_date` / `full_address`로 정렬하면
   `USE TEMP B-TREE FOR ORDER BY`가 발생한다(나머지 5종은 인덱스 적중). 현재 1,870행
   기준 실측 8~10ms라 체감 영향은 없다. 인덱스 추가는 스키마 변경이라 승인 대상
7. 결과 카드의 "조회수 -" — `auction_item`에 조회수 컬럼이 없어 **항상 `-`**로만 렌더된다.
   카드 정보 구성 변경은 `FRONTEND_MASTER_SPEC.md` §12.4에서 범위 밖으로 못박혀 있어 유지
8. 잘못된 `size`/`page` 파라미터(백엔드 422)가 URL로 들어올 때의 안내 문구 부재 (저심각도)
9. 비로그인 상태에서 입력한 검색조건 **이름**이 로그인 복귀 후 남지 않음 (저심각도)

---

## 2026-08-11 (Sprint 50) 이후 — Release Audit 결과와 다음 작업

### Release Blocking (실제 출시를 막는 것)

1. **KG이니시스 실연동** — `KGInicisProvider`의 Interface v2 6개 메서드가 전부
   `NotImplementedError`다. 현재 `PAYMENT_PROVIDER` 미설정 → `mock`으로 폴백해 동작 중.
   **외부 계약 + API Key 발급이 선행**돼야 하는 승인 항목. (변동 없음)

Sprint 50 재검증 결과 **위 1건 외에 출시를 막는 항목은 없다.** 인증(ES256/HS256 + JWKS),
검색, 상세, 개인화(즐겨찾기/최근조회/검색조건 저장), 데이터 무결성
(`integrity_check ok`, FK 위반 0, orphan 0, UNIQUE 위반 0, QA 잔여 0), 보안, 성능 모두 통과.

### 출시 전 결정 필요 (Blocking은 아니지만 그대로 내보내면 곤란)

2. **BUGS #33 물건종류 검색 어휘** — 기본 검색 화면에서 **69개 중 62개(90%)가 항상 0건**,
   진행 중 물건의 **63.4%(26/41)** 가 이름으로 도달 불가. 고쳐야 할 이름은 **6개뿐**이고
   남은 쟁점은 복합값 `상가,오피스텔,근린시설`(202행)을 어느 항목에 노출할지 하나다.
   해결안 3안(UI 어휘 교체 / 백엔드 동의어 매핑 / 크롤러 정규화) 비교표는 `docs/BUGS.md` #33.
   **②백엔드 동의어 매핑이 가장 국소적**(매핑 테이블 1개)이나 검색 API 의미 변경이라 승인 필요
3. **`ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` 미설정** — Admin API 전체가 500.
   Admin 화면(UI)이 아직 없어 사용자 영향은 없지만 운영 대응(CS·등기부 발급 연결)이 불가능하다

### 승인 대기 (코드로는 더 진행 불가)

4. 레거시 `/properties` 처리 방향 — Sprint 50 실측으로 실패 모드 확정(`docs/BUGS.md` #34:
   404가 아니라 **항상 엉뚱한 물건이 열린다**). inbound 링크 0건이라 도달 경로는 없음
5. `src/login/`(도달 불가 중복 코드) 삭제 여부
6. `formatPrice` 표기 기준 통일 / 결과 목록 table 뷰 / `SortBar`의 `crawl_date` 노출
7. 마이페이지 · Admin 화면 · 권리분석 화면 (신규 화면 스펙 미정)
8. 정렬 3종(`bid_rate`/`crawl_date`/`full_address`) 인덱스 추가 — 스키마 변경
9. `.env` UTF-8 BOM 제거(`docs/BUGS.md` #35) — 현재 무해하나 첫 줄 변수가 영원히 안 읽히는 함정.
   `.env` 수정이라 승인 필요

### 기술부채 (동작 영향 없음)

10. 결과 카드의 "조회수 -" — `auction_item`에 컬럼이 없어 항상 `-`.
    카드 정보 구성 변경은 `FRONTEND_MASTER_SPEC.md` §12.4에서 범위 밖
11. 잘못된 `size`/`page` 파라미터(백엔드 422)의 안내 문구 부재 (URL 직접 입력에서만 발생)
12. 비로그인 상태에서 입력한 검색조건 **이름**이 로그인 복귀 후 미보존
13. `storage/` 전체 gitignore — `docs/BUGS.md` #28의 구조적 원인, 여전히 유효
14. 계약 테스트의 `before()` 훅이 dev 서버 상태에 전 검사를 묶는다 —
    서버가 죽으면 소스 레벨 정적 검사까지 함께 취소된다(원래 설계상 의도, 개선 여지)

### 다음 Sprint 후보 (Sprint 51)

- **결정이 나오면**: #33 어휘 구현(상수/매핑 교체 + 회귀 테스트) → 검색 필터 정상화
- **승인 없이 가능한 것**: 남은 기술부채 10~12, 계약 테스트 구조 개선(14),
  Admin 화면 스펙 초안(코드 아님)
- **승인 후**: `ADMIN_API_KEY` 설정, `.env` BOM 제거, 정렬 인덱스 추가

---

## 2026-08-11 (Sprint 51) 이후 — Release Audit

사용자 확정 정책: **KG이니시스 실연동만 SKIP**. 이전 Sprint들이 "승인 대기"로 미뤄둔 항목을
전부 처리했다.

### Release Blocking (실제 출시를 막는 것)

1. **KG이니시스 실연동** — `KGInicisProvider`의 Interface v2 6개 메서드가 `NotImplementedError`.
   현재 `PAYMENT_PROVIDER` 미설정 → `mock` 폴백으로 전 결제 흐름이 동작한다.
   **외부 계약 + API Key 발급이 선행돼야 하는 유일한 항목.** (변동 없음)

**위 1건 외에 출시를 막는 항목은 없다.** Sprint 51에서 해소된 것:

- ~~BUG #33 물건종류 검색(진행 중 물건의 63% 도달 불가)~~ → **해결**, 도달 불가 0행
- ~~레거시 `/properties`의 조용한 오답(#34)~~ → **해결**, `/`로 이동
- ~~fresh clone 부트스트랩 불완전(`document_collect_failures` 누락)~~ → **해결**, 25/25 재현
- ~~`storage/` 소스 22개 미추적(#28 구조적 원인)~~ → **해결**, gitignore 정밀화
- ~~잘못된 파라미터의 오귀인 안내~~ → **해결**, 원인별 분기 + 복구 동선
- ~~`property_type` 대량 입력 500(#36)~~ → **해결**, 상한 + 400

### 사용자 결정 필요 (Commit/이력 변경을 수반)

1-a. **커밋된 DB 백업 9개(약 42MB) 정리** (`docs/BUGS.md` #37) — Sprint 51에서
   `.gitignore`에 `*.db.backup*`를 추가해 **향후 증가는 막았다**. 개인정보 노출은 없음을
   확인했다(개인 테이블 행은 전부 `qa-*` 합성 데이터). 이미 추적 중인 9개는 gitignore로
   빠지지 않으므로 `git rm --cached`(추적 해제, 이력엔 잔존) 또는 이력 재작성 중 선택이 필요하다.

### 운영 설정 (코드 아님, 배포 시점 작업)

2. `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` — 미설정 시 Admin API 500.
   Admin 화면(UI)이 없어 현재 사용자 영향은 없다. **실제 값 생성은 운영자 몫**(임의 발급 금지)
3. `.env` UTF-8 BOM 제거(`docs/BUGS.md` #35) — 현재 무해하나 첫 줄 변수가 영원히 안 읽히는 함정.
   `.env` 수정은 `docs/CLAUDE.md`상 승인 필요
4. Supabase Site URL / Redirect URLs를 운영 도메인으로 — 대시보드 설정

### 제품 확장 (신규 화면, 스펙 미정)

5. 마이페이지 / Admin 화면 / 권리분석 전용 화면
6. 결과 목록 table 뷰, `SortBar`의 `crawl_date` 정렬 노출, `formatPrice` 표기 기준 통일
7. UI 트리에 "빌라" 항목 추가 여부 — 현재 `연립주택`·`다세대주택`으로 도달 가능해 실질 손실 없음

### 기술부채 (동작 영향 없음)

8. 결과 카드의 "조회수 -" — `auction_item`에 컬럼 없음. §12.4가 카드 정보 구성 변경을 범위 밖으로 명시
9. 비로그인 상태에서 입력한 검색조건 **이름**이 로그인 복귀 후 미보존(조건 자체는 보존됨)
10. 정렬 3종(`bid_rate`/`crawl_date`/`full_address`) TEMP B-TREE — 1,870행 기준 2~10ms,
    체감 영향 없어 **스키마 변경하지 않음**(측정 후 판단)
11. 계약 테스트의 `before()` 훅이 dev 서버 상태에 소스 레벨 정적 검사까지 묶는다
12. `storage/migrate_doc_collect.py` — 017 마이그레이션으로 대체됐으나 기존 운영 절차가 있을 수
    있어 삭제하지 않음. 다음 정리 후보
13. 개별 차종(승용차/화물차 등) 검색 — DB에 차종 구분이 없어 매핑 보류. 데이터가 생기면 재검토

### 다음 Sprint 후보 (Sprint 52)

- **결제 도메인 내부 완성**(KG 연동 없이 가능): 환불(`cancel_payment`)·Webhook
  (`handle_webhook`) 엔드포인트를 MockProvider 기준으로 구현 + 상태머신/계약 테스트
- 기술부채 8·9·11·12 정리
- 마이페이지/Admin 화면 스펙 초안(코드 아님)

---

## 2026-08-11 (Sprint 52) 이후 — Release Audit

### Release Blocking

1. **KG이니시스 실연동** — `KGInicisProvider`의 6개 메서드가 `NotImplementedError`.
   외부 계약 + API Key 발급 선행 필요. **여전히 유일한 Blocking 항목.**

Sprint 52에서 해소: ~~환불 경로 부재~~ / ~~Webhook 수신 경로 부재~~ /
~~사용자가 자기 구독을 볼 수 없음~~ / ~~`audit_logs` QA 잔여 792행~~ /
~~카드 조회수 죽은 UI~~ / ~~`crawl_date` 도달 불가 정렬~~ / ~~비로그인 검색조건 이름 유실~~

### 사용자 결정 필요 (Commit/이력 변경 또는 사업 정책)

2. **커밋된 DB 백업 9개(약 42MB)** (`docs/BUGS.md` #37) — 증가는 차단됨. 개인정보 없음 확인
   (전부 `qa-*` 합성). untrack/이력 재작성 모두 Commit이 필요해 SKIP
3. **환불 사업 정책** — 환불 조건·기간·비율(구독 잔여기간 일할 계산 여부),
   **사용자 셀프 환불 개방 여부**, **환불 시 구독 자동 해지 여부**.
   메커니즘은 완성됐고(Admin 경로) 정책만 정하면 사용자 경로를 여는 것은 작은 작업이다
4. `formatPrice` 표기 기준 통일 — 공용 `formatPrice()`(0→'-', 만/억)와
   `formatPriceEok()`(항상 억)가 공존. 화면에 보이는 숫자가 바뀌는 UX 결정
5. 결과 목록 **table 뷰** — 카드/표 이중 구현이라 `FRONTEND_MASTER_SPEC.md` §12.4가
   별도 결정 후 진행으로 명시
6. **마이페이지 / Admin 화면 / 권리분석 전용 화면** — 신규 화면 스펙 미정.
   Sprint 52에서 **API 공백은 메웠다**(`/subscriptions/me`) — 이제 화면 스펙만 정해지면
   기존 API(`/payments`, `/subscriptions/me`, `/registry-requests`, `/favorites`,
   `/recent-items`)로 마이페이지를 만들 수 있다. Admin은 13개 엔드포인트가 이미 있다

### 운영 설정 (배포 시점, 값은 운영자가 생성)

7. `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` — 미설정 시 Admin API 전체 500(환불 포함)
8. `PAYMENT_WEBHOOK_SECRET` — 미설정이 안전한 기본값(Webhook 전부 401). Webhook을 실제로
   받을 때 필요
9. `.env` UTF-8 BOM 제거 (`docs/BUGS.md` #35) — 현재 무해하나 첫 줄 변수가 안 읽히는 함정
10. Supabase Site URL / Redirect URLs를 운영 도메인으로

### 기술부채 (동작 영향 없음)

11. 정렬 3종(`bid_rate`/`crawl_date`/`full_address`) TEMP B-TREE — 1,870행 기준 2~10ms.
    **측정 결과 체감 영향이 없어 스키마 변경하지 않음**(인덱스 추가는 승인 대상)
12. 계약 테스트 `before()` 훅이 dev 서버 상태에 소스 레벨 정적 검사까지 묶는다
13. `storage/migrate_doc_collect.py` — Migration 017로 대체됐으나 기존 운영 절차 가능성 때문에 보존
14. 개별 차종(승용차/화물차) 검색 — DB에 차종 구분이 없어 매핑 보류
15. `TossProvider`/`PortOneProvider` — 폐기 예정 후보. 삭제는 별도 판단

### 다음 Sprint 후보 (Sprint 53)

- **결정이 나오면**: 환불 정책 → 사용자 셀프 환불 경로 / 마이페이지 화면
- **승인 없이 가능**: 기술부채 12·13·15 정리, Admin 화면 스펙 초안,
  Webhook 재처리(실패한 Webhook 재시도) 운영 도구

---

## 2026-08-11 (Sprint 53) 이후 — Release Audit

### Release Blocking

1. **KG이니시스 실연동** — `KGInicisProvider`의 6개 메서드가 `NotImplementedError`.
   외부 계약 + API Key 발급 선행 필요. **여전히 유일한 Blocking 항목.**

Sprint 53에서 해소: ~~Webhook 운영 도구 부재~~ / ~~Webhook 저장소 증폭(DoS)~~ /
~~event_id oracle~~ / ~~인증 경계 검사가 하드코딩 5개 경로~~ / ~~테스트 하네스 인코딩 크래시~~ /
~~계약 테스트 `before()` 서버 의존~~ / ~~`.env` BOM(#35)~~ / ~~`migrate_doc_collect.py` 중복~~

### 사용자 결정 필요 (사업 정책 또는 Commit)

2. **환불 사업 정책** — 조건·기간·비율, **사용자 셀프 환불 개방 여부**,
   **환불 시 구독 자동 해지 여부**. 메커니즘은 완성됐고 정책만 정하면 된다
3. **커밋된 DB 백업 9개(약 42MB)** (`docs/BUGS.md` #37) — 증가는 차단됨, 개인정보 없음 확인.
   untrack/이력 재작성 모두 Commit 필요
4. `formatPrice` 표기 기준 통일 / 결과 목록 **table 뷰** — 화면에 보이는 값이 바뀌는 UX 결정
5. **마이페이지 / Admin / 권리분석 화면** — 신규 화면 스펙 미정.
   **API 공백은 전부 메웠다**: 마이페이지는 `/subscriptions/me` + `/payments` +
   `/registry-requests` + `/favorites` + `/recent-items` 조합으로, Admin은 19개 엔드포인트로
   구현 가능하다. 남은 것은 화면 스펙(무엇을 어떤 순서로 보여줄지)뿐이다

### 운영 설정 (값은 운영자가 생성)

6. `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` — 미설정 시 Admin API 전체 500(환불·Webhook 운영 포함)
7. `PAYMENT_WEBHOOK_SECRET` — 미설정이 안전한 기본값(Webhook 전부 401)
8. Supabase Site URL / Redirect URLs를 운영 도메인으로

### 데이터가 없어 구현 불가 (크롤러 + 스키마 선행)

9. **개별 차종(승용차/화물차 등) 검색** — DB에 차종 구분이 없다(`property_type='자동차'` 하나)
10. **면적 조건 검색** — `auction_item` 21개 컬럼에 면적 관련 0개.
    현재 면적은 `full_address` 문자열 끝의 `[... 66.19㎡]`를 프론트가 파싱해 **표시만** 한다
11. **특수조건 검색** — 대응 컬럼·수집 항목 없음
    → 셋 다 UI에는 "준비 중" 표기로 남아 있다.
    → **2026-08-11 Sprint 55 정정**: "셋 다 크롤러 수집 항목 추가가 선행돼야 한다"는
      **면적에 한해 부정확**했다. 면적 수치는 이미 `full_address`의 99.0%에 들어 있다
      (㎡ 1,952 / 평 14, 전수 파싱 실측). 크롤러 변경 없이 정규화만으로 색인 가능하다.
      다만 2.4%가 층별 다중 면적이고 지분 매각 건은 표기가 전체 필지 면적이라,
      **어느 값을 색인할지는 제품 결정**이므로 그 부분만 SKIP한다.
      차종은 텍스트로만 존재(13건)하고 특수조건은 데이터 자체가 없어 기존 판단 유지.

### 기술부채 (동작 영향 없음)

12. `TossProvider`/`PortOneProvider` — **검토 완료, 유지 결정**.
    제거하면 옛 `.env` 값에 대한 구체적 경고("폐기된 PG 후보")가 일반 오류로 바뀌어
    운영자 진단이 나빠진다. 15줄이고 호출 시 즉시 실패라 오용 위험 없음
13. 정렬 3종 TEMP B-TREE / `/subscriptions/me` 정렬 — **실측상 영향 없어 최적화하지 않음**
14. 저장소가 OneDrive 동기화 폴더 안이라 파일 I/O 테스트·빌드에 간헐적 잠금이 발생
    (`docs/BUGS.md` #40 — 테스트는 시스템 temp로 옮겨 해소, 빌드는 `.next` 삭제로 우회 중)

### 다음 Sprint 후보 (Sprint 54)

- **결정이 나오면**: 환불 정책 → 사용자 셀프 환불 / 마이페이지 화면
- **승인 없이 가능**: Webhook 재처리 이력 조회(현재는 audit_logs로만 추적),
  Admin 화면 스펙 초안, 크롤러 면적/차종 수집 항목 조사

---

## Sprint 54 반영 (2026-08-11)

### 완료

- 마이페이지 (`/mypage`) — 기존 API 3종 조합, 읽기 전용. 신규 엔드포인트 0개
- 권리분석 신뢰도 결함 수정 (BUGS #44) + 모듈 첫 테스트 15건
- 배치 3종 인터프리터 해석 교체 + `requirements.txt` 신설 (BUGS #46 저장소 측)

### Backlog 갱신

기존 9~11번(개별 차종 / 면적 / 특수조건 검색)은 그대로 유지. 아래를 추가한다.

15. **크롤 파이프라인 복구** — **최우선**. 저장소 측 수정은 끝났고 운영 조치 3개가 남았다.
    (a) `pip install -r requirements.txt` (b) 예약 작업 재등록
    (c) 59/60 법원 오류 원인 규명(1회 수동 실행 필요)
    조치 없이는 2026-08-13부터 검색 결과 0건.
16. **문서 수집·파싱 재가동** — `doc_raw` 0행 / `parsed_document` 0행 / `document_queue`
    pending 2,703. 권리분석 19개 분석 컬럼 중 14개가 100% NULL인 직접 원인이다.
    15번이 선행돼야 한다.
17. **권리분석 데이터 커버리지** — `rights_summary`가 1,870건 중 162건(8.7%),
    진행 중 물건 41건 중 **1건**. 화면은 완성돼 있으나 보여줄 것이 거의 없다.
18. **Admin 운영자 신원 체계** — 공유 `X-Admin-Key` 하나로 인증하고 `audit_logs.admin_id`에
    역할 문자열이 들어간다. 환불이 사람 단위로 추적되지 않아 Admin UI 착수의 선행 조건.
19. **권리분석 "정보원" 표기 정리** (BUGS #45) — 화면 설계 결정 필요.

### 다음 Sprint 후보 (Sprint 55)

- **운영 조치가 끝나면**: 크롤 1회 실행 → 59/60 오류 원인 규명 → 문서 파이프라인 재가동 검증
- **승인 없이 가능**: 크롤러 면적/차종 수집 항목 조사(9~11번 선행 작업),
  `document_queue` 2,703건 처리 경로 점검, 결제 도메인 잔여 감사

---

## Sprint 55 반영 (2026-08-11)

### 완료

- 크롤/워커 실패 은폐 구조 제거 (BUGS #47) — 종료 코드 규약 확립, 배치 마커 정비
- `document_queue` 적재 누락 수정 (BUGS #48) — Migration 018, 물건의 38%가 대상이었다
- 문서 상태가 화면에 도달하지 않던 문제 (BUGS #50, #45 해결) — 574행 보정
- 실접속 스크립트 실행 가드 (BUGS #51)
- 데이터 무결성 전수 감사 — 고아 행 0, 가격 이상 0

### Backlog 갱신

15번(크롤 파이프라인 복구)의 **저장소 측 항목은 전부 끝났다.** 남은 것은 운영 조치뿐이다.

16번(문서 수집·파싱 재가동)의 원인이 특정됐다 — 아래로 대체한다.

16-A. **파이프라인 후반 ~~4개~~ → 3개 스크립트의 스케줄 편입** (승인 필요)
     `collect_documents.py` / `load_rights_data.py` / `load_spec_data.py`가
     어떤 배치에서도 도달 불가다. 결정할 것: 실행 순서 / 소요 시간 / 실패 재시도 정책.

     **2026-08-12 Sprint 63 정정** — 여기 함께 적혀 있던 `analyze_docs.py`는 **편입 대상이
     아니다**. DB에 아무것도 쓰지 않는 1회성 조사 스크립트이며, 마지막이 `input()`이라
     배치에 넣으면 stdin이 없어 **매달리거나 죽고 뒷 단계까지 멈춘다**. 이 목록을 그대로
     믿고 배치에 넣었다면 사고가 났을 자리다 — `test_crawl_exit_code.py`가 구조로 막는다.

     또한 `load_rights_data.py` / `load_spec_data.py`는 Sprint 62에 실제 실행 검증을
     마쳤고(멱등성 확인 + 근거 없는 데이터 정리 + 안전장치), Sprint 61에 의존성이 설치돼
     **지금 바로 실행 가능한 상태**다. 남은 것은 순수한 운영 스케줄 결정뿐이다.

     **2026-08-12 Sprint 66 — `collect_documents.py`는 편입 전 수정이 필요했다(완료).**
     이 항목을 그대로 실행했다면 손대는 문서마다 `document_status`는 READY인데 뷰어는
     404가 되는 상태가 됐다(저장 경로가 뷰어 서빙 경로와 완전히 달랐다). STATUS는 구조적으로
     성공할 수 없어 매번 FAILED로 기록되던 문제도 함께 있었다 — 둘 다 수정하고 회귀
     14검사를 붙였다(`docs/BUGS.md` #64). **이제 편입해도 안전하다.**
     남은 것은 `doc_raw` 적재 소유권(16-B)과 실행 스케줄 결정이다.
16-B. **`doc_raw` 적재 경로 정리** — `doc_worker`는 PDF를 디스크에만 쓰고 `doc_raw`에는
     쓰지 않는다. 두 코드가 같은 일을 다르게 한다.

     **2026-08-12 Sprint 67 — 결정에 필요한 실측 소유권 매트릭스** (코드 전수 추적)

     | | PDF 저장 | `doc_raw` | `document_status` | `document_queue` |
     |---|---|---|---|---|
     | `doc_worker` (+`doc_crawler`) | O | **X** | O (`mark_queue_done`) | O |
     | `collect_documents.py` | O | **O** | O (직접) | **X** |

     - Sprint 66 수정 이후 **두 경로가 같은 canonical 경로에 저장**한다(더 이상 갈라지지 않는다).
     - 남은 비대칭은 두 칸이다: `doc_worker`는 `doc_raw`를 안 쓰고,
       `collect_documents`는 `document_queue`를 안 건드린다.
     - **`document_queue` 미갱신의 실제 영향(추적 확인)**: `collect_documents`가 수집하면
       파일+READY는 맞는데 큐는 `pending`으로 남아 `test_pipeline_integrity.py`의
       "파일이 있으면 큐도 done" 불변식이 그 시점에 실패한다. 다만 **자가 치유된다** —
       다음 `doc_worker` 실행에서 그 항목을 claim하면 `collect_spec()`이
       `doc_exists()` 가드로 즉시 `success=True`를 반환하고(재다운로드 없음)
       `mark_queue_done()`이 큐를 done으로 맞춘다. 데이터 손실·중복 다운로드는 없고,
       비용은 claim 1회다.
     - 실데이터 교차 검증(전수): READY인데 파일 없음 **0건** / 파일 있는데 READY 아님 **0건** /
       `doc_raw` 경로 부재 **0건**.

     따라서 이 항목은 **버그가 아니라 소유권 결정**이다. 선택지는 두 가지다 —
     (a) `collect_documents`를 은퇴시키고 `doc_worker`가 `doc_raw`까지 기록,
     (b) `collect_documents`를 유지하고 `document_queue`까지 갱신하게 함.
     어느 쪽이든 코드 변경은 작고, **결정 없이 한쪽을 구현하면 반대 결정 시 낭비**가 되므로
     Sprint 67은 구현하지 않고 이 표만 남긴다.
16-C. **죽은 테이블 정리** (BUGS #49) — `parsed_document` / `rights_analysis_history`.
     삭제하면 부트스트랩 테이블 수 기록이 바뀌므로 16-A와 함께 처리.
     (2026-08-17 Sprint 148 정정: 그 수는 **25개가 아니라 26개**다 — Sprint 144의
      migration 020이 `auction_image`를 추가했다. 두 표가 여전히 죽어 있다는 사실은
      2026-08-17 재확인했다: 각 0행, 프로덕션 읽기/쓰기 0곳.)

20. **면적 검색 정규화** — 데이터는 이미 있다(99.0%). 필요한 것은
    (a) 다중 면적/지분 매각 처리 기준 결정 **(제품 결정)**
    (b) `auction_item`에 수치 컬럼 + 인덱스 (c) 검색 API 파라미터 (d) UI.
    (a)만 정해지면 나머지는 기계적이다.
21. **`property_type` 오분류 2건** (id=317, id=11804) — 자동차로 분류됐으나 내용은
    집합건물/토지다. 크롤 원본 확인이 필요해 재수집 후 판단.

### 다음 Sprint 후보 (Sprint 56)

- **운영 조치가 끝나면**: 크롤 1회 → 종료 코드가 실제로 실패를 잡는지 실증 →
  59/60 오류 원인 규명 → 큐 누락 10건이 실제로 채워지는지 확인
- **승인 없이 가능**: 결제 도메인 잔여 감사, `doc_raw` 이중 경로 정리 조사,
  일회성 스크립트 91개 정리 기준 수립

---

## Sprint 56 반영 (2026-08-11)

### 완료

- 동시성 가드 검증 정상화 (BUGS #53) — 레이스 테스트가 실제로 레이스를 재현하게 만듦
- 구독 만료 파싱 실패의 조용한 폴백 제거 (BUGS #52)
- 금전 가드(미결제 → 완료 차단) 회귀 추가 (BUGS #54)
- 파이프라인 정합 불변식화 (`test_pipeline_integrity.py` 신설)

### Backlog 갱신

16-B가 구체화됐다 — **`doc_raw` 적재 소유권 결정** (BUGS #55).
문서를 저장하는 코드가 두 벌이고 스케줄러가 부르는 쪽이 `doc_raw`를 쓰지 않는다.
`crawler/doc_crawler.py`가 쓰게 할지, `collect_documents.py`를 스케줄에 넣을지가
16-A와 같은 결정이다.

22. **~~미파싱 문서 처리~~ → 2026-08-12 Sprint 62에 실측으로 재정의됨.**
    "SPEC 81 / STATUS 33이 미파싱"이라는 기존 서술은 **사실이 아니었다**.
    - SPEC 81건: 파싱 성공. 표 내용이 `조사된 임차내역없음` — **임차인이 없는 물건**이다.
      남은 것은 "확인된 임차인 없음"을 "정보 없음"과 구분해 보여줄지의 **표기 결정**뿐이다
      (데이터 모델에는 `rights_summary.is_vacant`가 이미 있다). 제품 결정 대기.
    - STATUS 33건: 실제 결함이었고 해결됐다(`docs/BUGS.md` #61 — 빈 캡처가 정상 수집으로
      저장되던 문제. 크롤러 수정 + 33건 재수집 대상 복구 완료).
23. **`property_type` 모순 5건** (BUGS #56) — 원인 규명에 실제 페이지 재확인 필요.
    현재는 상한을 둔 검사로 증가만 막고 있다.
24. **감정평가서 파서 미구현** — APPRAISAL은 READY가 되어도 파싱 대상 테이블 자체가 없다.

### 다음 Sprint 후보 (Sprint 57)

- **운영 조치가 끝나면**: 크롤 1회 → 종료 코드 실증 → 큐 누락 10건 충전 확인 →
  `property_type` 모순 5건의 원본 대조
- **승인 없이 가능**: 일회성 스크립트 91개 정리 기준 수립, `logs/*.py` 스테일 사본 처리,
  Frontend ↔ API 소비 계약 확대(현재 검색 파라미터만 고정됨)

---

## Sprint 57~58 반영 (2026-08-11~12)

### 완료

- `auction.db` 되돌아감 복구(Sprint 57, `docs/BUGS.md` #57) — migration_history 3건,
  audit_logs 698행, document_status 574행
- `ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY`가 실제로는 이미 설정되어 정상 동작 확인(Sprint 58) —
  과거 여러 Sprint가 반복 기록하던 "미설정 → 500" 블로커가 더 이상 유효하지 않다.
  **운영 설정 목록에서 제거**
- 환불/Webhook 재처리 동시성 회귀 신설(Sprint 58) — 새 버그는 없었고 기존 방어가 이미
  올바름을 확인, 검증 공백만 해소

### Backlog 갱신

기존 "운영 설정" 목록(6~8번, ADMIN_API_KEY 등)에서 ADMIN_API_KEY/SUPER_ADMIN_API_KEY 항목을
제거한다. 남은 운영 설정은 `PAYMENT_WEBHOOK_SECRET`(Webhook 실수신 시 필요)과 Supabase
Site URL/Redirect URL(운영 도메인 확정 시)뿐이다.

### Release Blocking (변동 없음)

1. KG이니시스 실연동 — 계속 SKIP
2. 크롤 파이프라인 운영 조치(selenium 설치, 예약 작업 등록) — 저장소 측 원인은 이미 제거됨,
   Sprint 57의 document_queue 복구로 크롤러 재가동 시 이전보다 더 정확하게 큐가 채워진다

### 다음 Sprint 후보 (Sprint 59)

- Admin 41개 엔드포인트 API Contract Audit 계속(이번 Sprint는 refund/webhook reprocess만
  집중 점검) — 나머지 엔드포인트의 동시성/응답 계약 재확인
- Frontend ↔ API 소비 계약 확대(현재 검색 파라미터만 소스 계약으로 고정돼 있음)
- 크롤 파이프라인 운영 조치가 끝나면: 종료 코드 실증, 큐 누락 재확인
- `doc_raw` 적재 소유권 결정(16-B) — 운영 스케줄 결정 대기
- "확인된 임차인 없음"(SPEC 81건)을 "정보 없음"과 구분해 표시할지 — 표기 방식 제품 결정 대기
  (22번 참고. 2026-08-12 Sprint 62에 "미파싱"이 아니라 정상 파싱 결과임이 실측 확인됨)

---

## Sprint 59 반영 (2026-08-12)

### 완료

- Admin 구독 상태 변경(`PATCH /admin/subscriptions/{id}`) 동시성 결함 발견·수정
  (`docs/BUGS.md` #58) — 등기부 #21과 동일한 패턴으로 해소, 회귀 2종 신규

### 다음 Sprint 후보 (Sprint 60)

- Admin 41개 엔드포인트 API Contract Audit 계속 — 이번까지 정밀 점검한 것은 refund/webhook
  reprocess/subscription status 3개뿐, 나머지(users/audit-logs/registry-credits 등) 미점검
- Favorites/Search Presets/Recent Items의 소유권·중복 처리 재점검(§8 IDOR 관점)
- Frontend ↔ API 소비 계약 확대(현재 검색 파라미터만 소스 계약으로 고정됨)
- 크롤 파이프라인 운영 조치가 끝나면: 종료 코드 실증, 큐 누락 재확인

---

## Sprint 60 반영 (2026-08-12)

### 완료

- 만료 구독 재활성화가 항상 조용히 실패하던 결함 발견·수정(`docs/BUGS.md` #59) —
  `change_status()`가 자신의 docstring이 이미 명시한 설계를 실제로는 구현하지 않고 있었다.
  `renew()`(만료 시각 연장 함수)가 저장소 전체에서 호출 0건인 것도 함께 확인(배선 안 된
  준비 코드 — KG이니시스 스텁과 같은 부류, 이번에는 별도 매개변수 추가로 해소해 `renew()`
  자체는 여전히 미배선 상태로 남음)

### 다음 Sprint 후보 (Sprint 61)

- Admin 41개 엔드포인트 API Contract Audit 계속 — 정밀 점검 완료는 refund/webhook
  reprocess/subscription status 4개(상태전이 2건 + 재활성화 1건 + 동시성 1건), 나머지
  (users/audit-logs/registry-credits/payments 등) 미점검
- `renew()`가 여전히 0곳에서 호출됨 — 실제로 필요한 기능인지(자동 갱신 배치? 사용자 셀프
  갱신?), 죽은 코드로 정리할지는 제품 결정 필요, 기록만 하고 SKIP
- Favorites/Search Presets/Recent Items의 소유권·중복 처리 재점검(§8 IDOR 관점)
- Frontend ↔ API 소비 계약 확대(현재 검색 파라미터만 소스 계약으로 고정됨)
- 크롤 파이프라인 운영 조치가 끝나면: 종료 코드 실증, 큐 누락 재확인

---

## 감정평가서 파서 — 기술 검증 결과 (2026-08-12 Sprint 66·69 실측)

제품 정책(무엇을 보여줄지)은 결정하지 않았다. **기술적으로 가능한지**만 측정했다.

### 1. 텍스트 추출 가능성 (Sprint 66, 표본 30)

```
appraisal.pdf 보유            198개
페이지당 추출 문자 중앙값      526자
200자 이상(텍스트 PDF)        24 / 30  (80%)
0자 (스캔 이미지 = OCR 필요)   5 / 30
```

### 2. 감정평가액 추출 정확도 (Sprint 69, **전수 197건**)

정답은 `auction_item.appraisal_price`(목록 크롤 값)를 썼다.

```
match       96  (48.7%)     추출값 = DB값
mismatch    46  (23.4%)     추출은 됐는데 DB값과 다름
no_amount   19  ( 9.6%)     텍스트는 있는데 감정평가액 표기를 못 찾음
no_text     36  (18.3%)     스캔 이미지 (OCR 필요)

추출 성공분(142) 중 DB 일치율 67.6%
```

### 3. **불일치의 원인은 파서가 아니다** (핵심 발견)

불일치 건의 원문을 직접 읽어 확인했다. 추출은 **정확했다**.

```
item=114  PDF: "감정평가액 일십일억칠천육백일십만육천원정 (\1,176,106,000.-)"
          DB : 188,632,000
item=118  PDF: "감정평가액 육억사천사백팔십일만삼천원정 (\644,813,000.-)"
          DB : 637,563,000
item=115  PDF: 607,000,000  = 그 사건 물건 2건의 합계와 정확히 일치
```

**감정평가서의 `감정평가액`은 사건 전체(감정 대상 전부)의 평가액이고,
`auction_item.appraisal_price`는 그 물건 하나의 평가액이다.** 개념이 다르므로 일치하지
않는 것이 정상이며, 48.7%의 "일치"는 사건에 물건이 하나뿐인 경우다.

### 4. 이것이 제품 결정에 뜻하는 것

- **감정평가액은 추출 대상으로서 가치가 낮다.** 화면에는 이미 물건별 감정가가 있고,
  PDF에서 뽑은 사건 총액을 나란히 보여주면 **사용자가 두 숫자를 혼동**한다.
- 파싱으로 새 가치를 만들 수 있는 후보는 오히려 **토지/건물 내역, 면적, 구조, 평가 근거,
  제시외건물 유무**처럼 지금 어디에도 없는 항목이다.
- 어떤 항목을 뽑아 **어디에 저장하고 어떻게 표기할지**는 제품·스키마 결정이라
  여기서 정하지 않는다.

### 5. 착수 시 필요한 기술 준비 (전부 확인 완료)

```
의존성      pdfplumber 0.11.10 설치됨 (Sprint 61)
샘플        198개 확보, 경로 규칙 확정(canonical_doc_path)
정답 데이터  물건별 감정가가 DB에 있어 대조 가능(단, 위 3번의 의미 차이를 전제해야 함)
OCR         약 18%는 텍스트가 0자라 OCR 없이는 불가 — 별개 과제
저장소       `parsed_document`는 쓰는·읽는 코드가 0곳인 죽은 테이블이라
            그대로 쓸지 새로 만들지도 결정 대상(16-C와 함께 처리)
```

**결론: 기술적 장애물은 "18% OCR"뿐이고 나머지는 준비돼 있다. 막고 있는 것은 결정이다.**

---

## 결정 대기 ― 만료 물건의 문서 표시 (2026-08-13 Sprint 73 제기)

기술 조사·측정·회귀 고정은 끝났다(`docs/BUGS.md` #69). **표시 정책만 정하면 된다.**

매각기일이 지나 수집 대상에서 빠진 문서가 상세 화면에 계속 "수집중"으로 남는다.
관심물건/최근조회로 도달할 수 있어 사용자에게 실제로 보인다(만료 물건 1,867건 / 전체의 99.5%).

선택지와 각각의 기술 영향:

```
(A) DocStatus에 새 상태 추가 (예: NOT_APPLICABLE / SKIPPED)
    - api/constants.py:DocStatus, 상태 전이 규칙, 화면 문구 매핑 갱신 필요
    - document_status 기존 5,049행의 소급 갱신 여부도 함께 정해야 함
    - 가장 정직하지만 건드릴 곳이 가장 많다

(B) 화면에서 만료 물건의 문서 영역을 다르게 그린다 (DB 무변경)
    - src/app/properties/[id]/page.tsx만 수정
    - auction_date를 이미 내려주고 있어 추가 API 변경이 없다
    - DB에는 여전히 COLLECTING이 남으므로 통계/운영 조회는 그대로 오해를 부른다

(C) 그대로 둔다
    - 만료 물건은 어차피 검색에 안 나오니 노출이 제한적이라고 볼 수도 있다
    - 다만 관심물건에 담아 둔 물건에서는 계속 보인다
```

어느 쪽이든 `test_document_status_sync.py` §6이 먼저 실패하면서 함께 고쳐야 할 지점을
지목하도록 이미 배선해 두었다.

### 추가 실측 증거 (2026-08-13 Sprint 76)

결정에 필요한 숫자를 더 채웠다. **정책은 여전히 정하지 않았다.**

```
pending 큐 2,753건 중 매각기일이 이미 지난 것    2,736  (99.4%)
                     아직 미래인 것                17

-> 다음 doc_worker 실행에서 2,736건은 브라우저 작업 없이 SKIPPED_EXPIRED가 되고
   그 물건들의 document_status는 COLLECTING("수집중")에 그대로 남는다
```

**"pending 2,753건"은 실제 남은 일(17건)을 크게 부풀려 보여준다.** 운영자가 큐 길이만 보면
크롤이 한참 밀렸다고 오판한다. 이것도 표시/정리 정책과 함께 판단할 재료다.

또 하나 ― Sprint 62의 빈 현황조사서 격리(`documents_quarantine/`) 결과를 추적했다.

```
격리된 (법원,사건,물건)        33
  document_status=COLLECTING + 큐 pending 으로 정상 재큐잉   28
  auction_item/큐가 이미 사라진 것                            5
  그 28건의 매각기일이 미래인 것                               0   <- 전부 과거
  실제로 다시 수집돼 파일이 생긴 것                            0 / 33
```

격리 자체는 설계대로 동작했다(빈 파일 제거 + 재수집 대기로 되돌림). 그러나 **28건 전부
기일이 지나 재수집이 구조적으로 불가능**하다. 즉 이 물건들은 현황조사서 파일이 없는 채로
영구히 "수집중"으로 남는다.

가치 손실은 아니다 ― 격리 전에도 내용이 빈 파일이었으므로 사용자가 얻을 것은 원래 없었다.
다만 **"수집중"이라는 표시만 남는다는 점**이 #69가 지적한 문제의 구체적 사례다.
선택지 (A)/(B)/(C) 중 무엇을 고르든 이 28건이 어떻게 보일지가 함께 정해진다.

---

## Sprint 78 종료 시점의 남은 작업 판정 (2026-08-13 실측)

이번 세션은 "승인 없이 가능한 작업"을 커버리지·불변식·프로브로 **소진**하는 방향으로 돌았다.
종료 시점에 남은 미커버 경로를 전부 분류했고, 결론은 **남은 것이 전부 승인/외부 의존**이다.

```
crawler/base_crawler.py    212문장 0%   selenium + 실제 DOM. HTML 픽스처가 저장소에 없고
crawler/court_crawler.py    89문장 0%   만들려면 실제 courtauction.go.kr 크롤이 필요 -> SKIP
crawler/doc_crawler.py     276문장 12%  (순수 함수 calc_file_hash/_hash_bytes는 Sprint 78에 검증)
filter/scoring_engine.py    68문장 0%   죽은 코드(참조 0). 삭제는 승인 영역이고,
filter/report_generator.py  54문장 0%   아무도 실행하지 않는 코드에 테스트를 붙이는 것은 가치가 없다
storage/database.py:query() 28문장      레거시 auction 조회. 호출부는 죽은 filter/ + 수동 스크립트뿐
storage/database.py:init_db  12문장     구 스키마 ALTER 분기. 구 스키마 픽스처 비용이 가치보다 크다
api/v1/payments.py           30문장     실 PG 응답 / Webhook 일반 예외 -> KG이니시스 실연동 SKIP 대상
api/v1/admin.py              26문장     409 경합·일반 예외 분기(경합은 test_race_conditions가 구조로 고정)
```

### 다음 Sprint 후보 (Sprint 79) — 승인 없이 가능한 것부터

1. **`wait_for_download()` 파일시스템 폴링 검증** — `crawler/doc_crawler.py`의 순수 함수 중
   유일하게 남은 미검증 경로다(브라우저 비의존, `DOWNLOAD_DIR`만 패치하면 된다).
   `.crdownload` 무시 / 크기 안정화 2회 확인 / 타임아웃 시 None을 픽스처로 고정할 수 있다.
   Sprint 78이 해시 두 함수를 검증한 것과 같은 방식.
2. **`storage/database.py:query()` 처리 결정** — 죽은 `filter/`와 수동 스크립트만 부른다.
   삭제(승인 필요) 대신 **호출 경로와 영향 범위를 문서화**하는 것까지가 비승인 범위다.
3. **Admin 409 경합 분기의 동작 검증** — 지금은 구조 검사(소스 레벨)로만 고정돼 있다.
   `test_subscription_policy.py` §11이 쓴 **결정적 끼워넣기**(UPDATE 직전 콜백) 방식이면
   스레드에 기대지 않고 재현할 수 있다. 확률에 기대는 검사를 늘리지 않는 것이 요점.
4. **`init_db()` 구 스키마 업그레이드 경로** — 구 스키마 DB를 픽스처로 만들어 ALTER 분기를
   태운다. 비용이 있으므로 3번 이후 순위.

### 승인/외부 의존으로 계속 SKIP

```
KG이니시스 실연동                    계약 + API Key. 이번에도 SKIP(사용자 확정 방침)
.env 값 입력(ADMIN_API_KEY 등)       .env 수정은 승인 영역 — Sprint 78은 "이름 유무"만 확인했다
selenium 기반 크롤 픽스처            실제 사이트 접속이 필요하다
filter/ 죽은 코드 삭제               구조 변경(승인 영역)
정책 결정 항목                       만료 물건 표시(#69) / 재수집 / doc_raw 소유권 / WAL /
                                     감정평가서 표시 / 예약 등록 / Soft Delete 전환
```

**정책 결정 항목에 대해 이번 세션이 한 것**: 결정 자체는 손대지 않고, 주변 기술 작업만 했다 —
#69의 노출 경로 재측정(고아 큐 18행 측정 경로 고정), 재수집 가능성(#70의 후속으로 큐 stale
갱신 확인), 상태머신 영향(재시도 복구가 화면 상태를 되돌리도록 #73), 회귀 가드 작성.

### Sprint 85 결과 ― 위 후보 4개 전부 완료 (2026-08-13)

위 "다음 Sprint 후보 (Sprint 79)" 목록은 번호만 낡았고 내용은 그대로 유효했다. 4개를 모두
실행했다. **제품 결함은 1건도 없었고**, 대신 문서화되지 않은 한계와 측정 코드 결함이 나왔다.

```
1. wait_for_download 검증        완료  BUGS #84  변이 8종 중 7종 검출, 1종은 "효과 없음" 증명
2. query() 처리 결정             완료(문서화 범위)  BUGS #83  운영 호출부 0곳 재확인 + 레거시
                                 플래그 드리프트 35건 실측 + api/ 참조 금지 가드
3. Admin 409 동작 검증           완료  BUGS #85  결정적 끼워넣기로 확률 제거, 변이 3종 전부 검출
4. init_db 구 스키마 경로        완료  BUGS #82  UNIQUE 제약은 고치지 못한다는 한계 확정
                                 (migration 018 필요) + 하네스 결함 1건 수정
```

추가로 TODO 전수 탐색에서 **사용자에게 잘못된 결과가 보이는 항목 하나**를 찾았다(BUGS #81 ―
면적/특수조건 필터가 걸리지 않는데 걸린 것처럼 보인다). 구현은 승인 영역이라 결정하지 않고
양방향 드리프트 가드만 설치했다.

### 다음 Sprint 후보 (Sprint 86) ― 승인 없이 가능한 것부터

1. **`storage/database.py:init_db()` 예외 경로** ― 남은 미커버 구간이다. 읽기 전용 파일이나
   잠긴 DB로 `logger.error` + 재전파를 태울 수 있다(픽스처 비용이 낮다).
2. **`document_status` 이외의 화면 경로에서 doc_type 대소문자 혼용 재점검** ― Sprint 73이
   `doc_exists()`에서 고친 부류의 결함이 다른 계층에도 있는지 전수로 본다(`api/v1/documents.py`
   `DOC_TYPE_FILES` ↔ DB 값 ↔ 파일명 3자 대조).
3. **`wait_for_download()`의 호출부 검증** ― 이번에 함수 자체는 고정했지만, 호출부가
   `None`(타임아웃)을 어떻게 처리하는지는 selenium 경로 안에 있어 아직 못 봤다. 호출부만
   따로 떼어낼 수 있는지 검토(가능하면 그것도 브라우저 비의존으로 만든다).
4. **레거시 `auction` 테이블의 쓰기 경로 정리안 문서화** ― 삭제/이관은 승인 영역이지만,
   "어느 코드가 무엇을 쓰고 누가 읽는가"를 한 장으로 정리해 두면 결정이 쉬워진다.

### 이번에도 SKIP한 것 (변동 없음)

```
KG이니시스 실연동                계약 + API Key (사용자 확정 방침)
.env 값 입력                     승인 영역
selenium 기반 크롤 픽스처        실제 사이트 접속 필요
filter/ 죽은 코드 삭제           구조 변경(승인 영역)
면적/특수조건 필터 구현(#81)     스키마 변경 + 크롤러 추출 + 정규화 규칙 = 승인 영역
has_* 플래그 스키마 제거(#83)    스키마 변경(승인 영역) - 읽히지 않는다는 가드만 설치
정책 결정 항목                   만료 물건 표시(#69) / 재수집 / doc_raw 소유권 / WAL /
                                 감정평가서 표시 / 예약 등록 / Soft Delete 전환
```

### Sprint 85 후반 ― 커버리지가 지목한 실패·방어 경로 처리 (2026-08-13)

```
api/v1/documents.py 방어 2줄     완료  BUGS #86  탈출 경로에 실파일을 두어 유출을 실증
api/v1/favorites.py 실패 격리    완료  BUGS #87  과거 결함(모든 예외를 "이미 등록"으로)의 가드
READY <-> 뷰어 서빙 파일 일치    완료  BUGS #88  판정은 json, 서빙은 html ― 556행 실측 0건
init_db / checkpoint / 상태조회  완료  BUGS #89  "조용한 실패"에 근거(로그·보존)를 붙였다
기존 테스트의 크래시 하네스 결함  완료  BUGS #86  단언을 약화하지 않고 예외를 None으로
```

### 다음 Sprint 후보 (Sprint 86) ― 승인 없이 가능한 것부터

1. **`api/v1/payments.py` 남은 미커버 26줄** ― 결제 경로 중 provider 실패/경계 분기다.
   돈이 걸린 코드라 우선순위가 가장 높다. Mock Provider로 도달 가능한 것부터 고른다
   (실연동은 계속 SKIP).
2. **`api/v1/admin.py` 남은 미커버 26줄** ― 대부분 예외 처리/권한 경계다. §34에서 쓴
   커넥션 갈아끼우기로 도달할 수 있는지 먼저 확인한다.
3. **`api/v1/payment_logs.py` 7줄 / `api/auth.py` 4줄 / `api/v1/item.py` 3줄** ― 작지만
   전부 실패·경계 경로다. 묶어서 처리하면 한 Sprint 안에 끝난다.
4. **`storage/migrations/run_migrations.py` 6줄** ― 마이그레이션 실패 경로. 옛 스키마
   픽스처(§10)를 그대로 재사용할 수 있다.
5. **레거시 `auction` 테이블 정리안 문서화** ― 삭제/이관은 승인 영역이지만, "누가 쓰고 누가
   읽는가"를 한 장으로 정리하면 결정이 쉬워진다(#83의 실측을 근거로).

### Sprint 85 마무리 ― 돈 경로 실패 분기 (2026-08-13, BUGS #90)

`api/v1/payments.py` 92% -> 95%. 남은 미커버는 **도달 불가이거나 호출부가 없는** 것들이라
문서에 근거를 남겼다(557-558 락 뒤 이중 방어 / 514 API로 만들 수 없는 상태 / 497-498 사용자
경로 미구현 / 420-422 주입 필요).

### 다음 Sprint 후보 (Sprint 86 개정) ― 승인 없이 가능한 것부터

1. **`api/v1/payments.py` 420-422** ― 결제 생성 트랜잭션의 예외 롤백. §35에서 쓴 INSERT 주입
   래퍼를 그대로 쓸 수 있다(그때 `__setattr__`까지 위임해야 한다는 것도 배웠다).
2. **`api/v1/admin.py` 남은 26줄** ― 대부분 예외/권한 경계다. 커넥션 갈아끼우기로 도달
   가능한지부터 확인한다.
3. **`api/v1/payment_logs.py` 7줄 / `api/auth.py` 4줄 / `api/v1/item.py` 3줄** ― 작은 실패·
   경계 경로 묶음. 한 Sprint에 끝난다.
4. **`storage/migrations/run_migrations.py` 6줄** ― 마이그레이션 실패 경로. §10의 옛 스키마
   픽스처를 재사용한다.
5. **`api/v1/search.py` 42 / 52-53 / 345-348 / 368-369** ― 검색 입력 경계. 사용자 눈에 보이는
   경로라 우선순위가 낮지 않다.
6. **레거시 `auction` 테이블 정리안 문서화** ― #83 실측을 근거로 "누가 쓰고 누가 읽는가"를
   한 장으로. 삭제/이관 결정은 승인 영역이므로 문서까지가 범위다.

---

## 결정 대기 ― 구독 결제를 환불하면 구독은 어떻게 되는가 (2026-08-13 Sprint 96 제기, BUGS #94)

### 지금 일어나는 일 (실측)

```
12,900원 전액 환불 -> payment=REFUNDED,  subscription=ACTIVE (만료일 그대로)
                      사용자 화면: "구독 중"
```

돈은 돌려주고 서비스는 계속 준다. **의도된 정책일 리 없지만, 무엇이 옳은지는
제품이 정할 문제라 임의로 바꾸지 않았다.**

### 선택지

| | 전액 환불 시 | 사용자가 느끼는 것 | 다시 볼 문제 |
|---|---|---|---|
| A | 즉시 해지 | 환불 즉시 서비스가 끊긴다 | 이미 쓴 기간은? 환불액과 어긋난다 |
| B | 결제 주기 끝까지 유지 후 만료 | 산 기간은 다 쓰고 갱신되지 않는다 | 전액을 돌려받고 한 달을 더 쓴다 |
| C | 일할 계산 후 남은 기간만 해지 | 가장 공정 | 환불 금액 계산을 누가 하는가(운영자/자동) |
| D | 해지하지 않고 표시만 남긴다 | 변화 없음 | 지금과 같다. 최소한 추적은 된다 |

부분 환불(`PARTIAL_REFUND`)은 또 다른 문제다 ― A/B/C 어디에도 자연스럽게 들어맞지 않는다.

### 정책과 무관하게 먼저 해야 하는 일 (승인 불필요) — ★ 완료 (2026-08-23 Sprint 267 확인)

~~결제와 구독을 잇는 열쇠가 없다.~~ → **이미 만들어져 있다.** `019_add_subscription_payment_id.sql`이
적용되어 `subscriptions.payment_id INTEGER REFERENCES payments(id)`가 실제로 존재하고,
`api/v1/payments.py:create_subscription()`이 `SUBSCRIPTION` 결제 생성 시 이 값을 실제로
채운다(같은 트랜잭션 안, `payments.py:440`). 이 항목을 적었던 바로 그 Sprint(96) 안에서
이미 닫혔는데 이 문단만 갱신되지 않았다 - `docs/BUGS.md` #94도 함께 정정함.

**어떤 선택지를 고르든 이 열쇠가 먼저 있어야 실행된다.** A/B/C/D 전부
"이 결제가 산 구독이 무엇인가"에 답할 수 있어야 한다. D조차 그렇다 ―
표시를 남기려면 어디에 남길지 알아야 한다. **그 전제조건은 충족됐다** -
남은 것은 아래 정책 결정 자체뿐이다.

### 결정 전까지의 상태

지금 동작을 "정상"으로 굳히는 검사는 **넣지 않는다.** Sprint 95에서 겪은 것과 같은
함정이다 ― 결함을 테스트가 정상으로 굳혀 두면 고칠 때 테스트가 먼저 막아선다.
대신 BUGS #94에 실측을 남기고, 이 항목이 열려 있음을 여기서 가리킨다.

---

## Sprint 145 (2026-08-17)

### 완료
- **BUGS #101 수정** — 진행 중 물건이 큐의 옛 매각기일 때문에 영구 미수집으로 종결되던
  문제. `reconcile_queue_auction_date()` 신설 + `doc_worker` 배선. 회귀 7단언 + Mutation.
- **신선도 검사에 예약 작업 등록 여부 보고 추가** (`test_pipeline_integrity.py` §11).

### ★★ 최우선 — 기한 2026-08-20 (3일)

**수집 파이프라인 스케줄러 등록.** Sprint 112가 준비, Sprint 136이 백로그 최상단에
올려 둔 항목이 아직 실행되지 않았다. 이번에 **등록 0건임을 실제로 확인**했다
(예약 작업 249개 중 이 저장소를 가리키는 것 0개).

```powershell
.\register_scheduler_tasks.ps1           # 계획 확인
.\register_scheduler_tasks.ps1 -Apply    # 등록
```

미실행 시 2026-08-20부터 기본 검색 결과가 0건이 된다(검색 노출 9건의 매각기일이
전부 2026-08-19). 사용자 환경 변경이라 SKIP.

### 등록 후 재검증할 것
1. item 1533이 BUGS #101 수정 덕분에 실제로 수집되는가
2. `document_status`에 `IMAGE` 행이 처음 생기는가 (현재 0행 — 사진 45장은 큐가 아니라
   Sprint 144의 직접 호출로 저장된 것)
3. `NO_IMAGE` 실데이터가 처음 관측되는가 (지금까지 합성 테스트로만 검증)

### 측정 완료 — 개선 대상 아님으로 판정
- **사건 단위 문서 중복**: 현재 0건. 전 물건 수집 시에도 495부 ≈ 6.7 MB
  = `documents/` 전체의 **0.52%**. 저장 구조 변경 권장하지 않음(Sprint 145 §7).

### 정책 대기 (제품 판단)
- ~~**재수집 정책** — `document_version_log`가 구조적으로 도달 불가임을 호출 경로로 확정.
  선택지 A(기일 임박 강제 재수집) / B(해시 비교) / C(현행 유지)와 구현 범위·테스트
  방법을 Sprint 145 §6에 정리.~~
  → **2026-08-18 Sprint 189에 결정·구현 완료.** B안을 넓힌 형태(기일뿐 아니라 최저가/
  사건상태/감정가 변경까지 신호로 쓰고 필드마다 다시 받을 자산을 나눈다). 그래서
  `document_version_log`는 더 이상 도달 불가가 아니다 — 다만 **예약 작업이 없어**
  아직 실제로 채워지지 않는다(BUGS #123). 상세는
  `docs/SPRINT189_CHANGE_DRIVEN_REFRESH.md` / `docs/decision-log.md`.

**★ 2026-08-18 Sprint 189 재정정 — 아래 Sprint 187의 정정이 지금은 틀렸다.**
`DOJOONPASS_DAILY`는 **현재 존재하지 않는다**(전체 249개 중 이 저장소를 가리키는 것 0개,
`register_scheduler_tasks.ps1` dry-run이 세 작업 전부 "(신규)"로 보고). 즉 원래의
"등록 0건"이 다시(여전히) 사실이다. 세 근거가 일치한다 — `logs/daily_run.log` 마지막
2026-08-11, `auction.crawl_date` 최신 2026-08-12, 기일 남은 물건 9건. `docs/BUGS.md` #123.

**2026-08-17 Sprint 187 정정 — "등록 0건"은 더 이상 사실이 아니다(부분적으로).**
이 절의 "예약 작업 249개 중 이 저장소를 가리키는 것 0개"는 그 시점(Sprint 145) 실측이었다.
지금 다시 확인하면 **`DOJOONPASS_DAILY`라는 작업이 실제로 등록돼 매일 03:00에 성공적으로
돌고 있다**(`Get-ScheduledTask` 실측, `LastRunTime 2026-08-17 03:00:01`, `LastTaskResult 0`).
단, 이 이름은 `register_scheduler_tasks.ps1`이 등록/조회하는 이름(`DojoonPass-DailyCrawl`)과
**다르다** — 누군가 이 스크립트를 거치지 않고 수동으로 등록한 것으로 보인다(GUI로 보인다).

```
DOJOONPASS_DAILY (수동 등록, 이 스크립트가 모름)  매일 03:00   run_daily.bat
                                                              (mvp_scraper.py + migrate_execute.py)
DojoonPass-DocWorker        (미등록)              02:00 예정   run_doc_worker.bat   <- 사진/문서 수집
DojoonPass-PriorityRefresh  (미등록)              01:50 예정   run_priority_refresh.bat
```

★★ **2026-08-18 Sprint 189 정정 — 위 표는 더 이상 사실이 아니다.** `DOJOONPASS_DAILY`도
지금은 **없다**. 전체 예약 작업 249개 중 이 저장소를 가리키는 것이 **0개**이고,
`register_scheduler_tasks.ps1` dry-run이 세 작업 전부 "(신규)"로 보고한다. 뒷받침:
`logs/daily_run.log` 마지막 기록 2026-08-11 17:05, `auction.crawl_date` 최신 2026-08-12
이후 6일간 0건, 기일이 남은 물건 1,876건 중 **9건**(전부 2026-08-19까지) —
**2026-08-20부터 검색 결과가 0건이 된다.** 상세는 `docs/BUGS.md` #123.
(마이그레이션 020은 그 사이 적용됐다 — BUGS #117 해결.)

아래는 Sprint 187 시점의 기록이다.

즉 **"물건 기본정보"는 실제로 매일 갱신되고 있다**(auction/auction_item UPSERT, Sprint 185
변경 관측까지 포함). 반면 **사진/문서는 여전히 자동으로 전혀 수집되지 않는다** — Sprint 144~186이
쌓은 이미지/문서 파이프라인 전체가 트리거될 기회 자체가 없다. 실측 근거(2026-08-17):
`doc_raw` 0행, `document_status` COLLECTING 6,180 / READY 555(READY는 과거 1회성 수동 실행분),
`document_queue` pending 4,008행(매일 `enqueue_documents()`로 계속 쌓이기만 하고 안 빠짐),
`auction_image` 테이블 자체가 이 환경의 `auction.db`에 없음(마이그레이션 020 미적용 — 별도
Release Blocker, `docs/BUGS.md` #117 / `docs/BETA_RELEASE_CHECKLIST.md` 참고).

`register_scheduler_tasks.ps1`을 그대로 `-Apply`하면 `run_daily.bat`을 06:00에 **또** 등록해
같은 배치가 하루 두 번(03:00 기존 + 06:00 신규) 돈다 — Sprint 187에서 스크립트에 기존
작업 자동 탐지+경고를 추가했다(자동 삭제는 하지 않는다, 사용자 승인 판단 영역이므로).

**여전히 사용자 승인/외부 조치 영역이라 SKIP.** 승인 후 실행할 것:
```powershell
.\register_scheduler_tasks.ps1           # 계획 확인 (기존 DOJOONPASS_DAILY 경고가 뜨는지 확인)
# DOJOONPASS_DAILY를 남길지 정리할지 판단한 뒤:
.\register_scheduler_tasks.ps1 -Apply
```

---

## [결정 완료] 문서 재수집 정책 — 2026-08-18 Sprint 189에 **B안 확장으로 확정·구현**

★ 아래 "결정 대기" 문서는 **결정 당시의 근거로 그대로 남긴다.** 실제로 채택된 것은
표 B안(기일 변경 시 재수집)을 넓힌 형태다 — 기일뿐 아니라 **최저가/사건상태/감정가**
변경까지 신호로 쓰고, 필드마다 다시 받을 자산 종류를 나눈다.

```
auction_date       -> spec, status
minimum_bid_price  -> spec
status             -> spec, status
appraisal_price    -> appraisal, image
```

C안(주기적 전면 재수집)은 채택하지 않았다 — 아래 규모 실측대로 실행 창을 통째로
차지해 **한 번도 수집된 적 없는 물건이 밀리기** 때문이다. D안은 C안과 비용이 같아
따로 볼 이유가 없었다.

구현 위치는 위 "구현 범위" 4번(=`reconcile_queue_auction_date()` 지점)이 아니라
`migrate_execute()`다 — 거기가 **이미 필드 단위로 무엇이 바뀌었는지 판정하고 있는**
유일한 지점이기 때문이다(Sprint 185의 변경 관측). 새로 판정 로직을 만들지 않았다.

전체 설계·경계·실측은 `docs/SPRINT189_CHANGE_DRIVEN_REFRESH.md`와
`docs/crawler.md`의 "변경 기반 재수집" 절, 결정 근거는 `docs/decision-log.md`에 있다.

**구현 범위 1·2번은 이미 해소돼 있었다** — 1번(`overwrite` 인자)은 원래 있었고,
2번(`previous_hash`)은 이미지가 Sprint 186(BUGS #113), 문서는 그 전부터 채우고 있었다.
Sprint 189가 실제로 채운 것은 3번(큐 재적재 규칙)뿐이다.

---

## [결정 대기 — 당시 기록] 문서 재수집 정책 (2026-08-17 Sprint 145 정리 — 정책은 정하지 않았다)

Sprint 144+가 "재수집이 구조적으로 일어나지 않는다"를 규명했고, Sprint 145에서 선택지와
구현 범위를 정리한다. **어느 안을 택할지는 제품 판단이라 여기서 결정하지 않는다.**

### 현재 동작 (코드로 확정된 사실)

```
collect_spec/status/appraisal()  파일이 이미 있으면 early-return (success=True)
                                 previous_hash/new_hash를 "" 로 둔다
mark_queue_done()                if previous_hash and previous_hash != new_hash:  <- 항상 False
collect_document(..., overwrite) doc_worker는 overwrite를 넘기지 않는다 (기본 False)
```

실측 뒷받침: `doc_raw` 556행이 **전부 doc_version=1**(2 이상 0행),
`document_version_log` 0행.

### 데이터 손실 가능성

법원이 문서를 정정·갱신해도(감정평가서 정정, 매각물건명세서 변경 공고 등) 우리는
**영원히 최초 수집본을 보여 준다.** 사용자는 옛 정보로 입찰 판단을 하게 된다.
오류 화면도 빈 값도 아니라 **그럴듯한 옛 문서**라, 이 저장소가 반복해서 경계해 온
"조용히 틀린" 부류다.

또한 `document_version_log`와 `mark_queue_done()`의 해시 비교 분기는 **도달 불가능한
코드**로 남아 있다 — 변경을 감지하려고 만든 장치가 작동한 적이 없다.

> **[정정 2026-08-18 Sprint 211]** 위 문장은 더 이상 사실이 아니다.
> Sprint 189 의 `requeue_changed_documents()` 가 `done -> refresh` 로 큐를 되돌려
> `overwrite=True` 경로를 실제로 열었고, 해시가 달라지면 개정 이력이 남는 것까지
> fixture 로 확인돼 있다. **바뀐 것은 이유다** — 지금 0행인 것은 "경로가 없어서"가
> 아니라 "예약 작업이 0개라 아직 한 번도 돌지 않아서"다(BUGS #123).

### 정책 선택지 (택일 또는 조합)

| 안 | 내용 | 비용 | 위험 |
|---|---|---|---|
| A. 현행 유지 | 한 번 받으면 끝 | 0 | 정정 문서를 영원히 놓친다 |
| B. 기일 변경 시 재수집 | `auction_date`가 바뀌면 그 물건 문서를 다시 받는다 | 유찰/재매각 건만이라 작다 | 기일과 무관한 정정은 못 잡는다 |
| C. 주기적 재수집 | N일 지난 문서를 다시 받는다 | 큐가 N일마다 전체 규모로 늘어난다 | 가동 창(2시간) 초과 — 아래 참고 |
| D. 해시만 주기 확인 | 문서를 받아 해시만 비교하고 달라졌을 때만 교체 | C와 사실상 같다(받아야 해시를 안다) | 실익 대비 비용이 크다 |

### 구현 범위 (어느 안이든 공통)

1. `collect_document(..., overwrite=True)`를 doc_worker가 넘길 수 있게 조건 추가
   — 함수 인자는 **이미 존재한다**(`overwrite`). 새로 만들 것이 없다.
2. `collect_*()`의 early-return을 지나갈 때 `previous_hash`를 채워 준다
   (지금은 `""`라 `mark_queue_done()`의 비교가 항상 거짓이다).
3. 큐 재적재 규칙 — `enqueue_documents()`가 `status`를 건드리지 않기로 한 현재 결정
   (Sprint 74 주석)을 어떻게 바꿀지.
4. B안이면 `reconcile_queue_auction_date()`가 이미 기일 드리프트를 잡고 있으므로
   그 지점에 재수집 트리거를 붙이면 된다(Sprint 145 신설).

### 규모 경고 (C안을 고를 때 반드시 볼 것)

**★ 2026-08-17 Sprint 146 정정 — 앞선 "완주에 8일 이상"은 틀린 계산이었다.**

그 추정은 pending 2,753건 **전부**에 22초를 곱한 것이었다. 그런데 큐 항목의 대다수는
브라우저를 열지 않는다 — 매각기일이 지난 항목은 `mark_queue_skipped_expired()`가
DB 몇 번으로 종결한다. 운영 큐를 그대로 복제해 실측했다:

```
복제한 pending          2,753건
  기일경과로 즉시 종결   2,730건 x 5.1 ms = 13.9초
  실제 수집이 필요한 것     23건 x 22초   = 506초
  ------------------------------------------------
  1회 실행 총 소요                        = 519.9초 (8.7분)
  가동 창(02:00~04:00)                    = 7,200초
  => 한 번의 실행으로 큐 전체를 소진한다 (창의 7%만 사용)
```

즉 **현재 규모에서 가동 창은 병목이 아니다.** 진짜 상한은 "하루에 새로 생기는 물건 수"이며,
크롤이 멈춰 있어 지금은 그마저 0이다. 따라서 C안(주기적 재수집)을 검토할 때도 가동 창
확대나 병렬 worker를 **선행 조건으로 볼 근거가 없다** — 재수집 대상 규모(물건 수 x 문서 3~4종)를
직접 계산해 판단해야 한다. 참고로 전 물건(1,876) x 4종 = 7,504건을 전부 실수집하면
7,504 x 22초 ≈ 45.9시간이라 그때는 창을 넘긴다. 재수집 주기를 정할 때 쓸 숫자는 이쪽이다.

### 테스트 방법 (정책이 정해지면)

- `test_asset_pipeline.py`에 "해시가 바뀌면 `document_version_log`에 1행이 생긴다" 추가
- `test_doc_storage_atomicity.py` §3이 이미 `mark_queue_done()`의 트랜잭션 경계를 지키므로
  버전 로그 기록이 같은 트랜잭션에 들어가는지만 확인하면 된다
- 실 법원 재수집은 표본 1건으로 충분하다(같은 물건을 `overwrite=True`로 두 번 받아
  두 번째에 `doc_version=2`가 생기는지)

---

## [완료] Sprint 145 — 검색 결과 대표 사진 + 사용자 흐름 실화면 검증 (2026-08-17)

- ~~검색 결과에 물건 사진이 없다~~ → **완료**. `api/v1/search.py`가 대표 사진을 배치 조회
  1회로 함께 주고(N+1 아님 — 페이지 크기 10/50/100 모두 SQL 3문 고정),
  `ResultList.tsx`가 사진이 있을 때만 썸네일을 그린다(없으면 종전 레이아웃 유지).
  기존 응답 키 무변경, `thumbnail_url`만 추가.
- ~~사건 단위 문서(현황조사서)를 물건 수만큼 중복 수집~~ → **완료**. 형제 물건이 방금 받아
  둔 것을 복사한다(저장 구조 변경 없음). 초과 수집 492회를 없앤다.
  ★ 2026-08-17 Sprint 147 정정: 절감폭을 "약 3.0시간"으로 적었으나 그것은 navigation까지
  건너뛴다고 가정한 값이었다. Sprint 145 구현은 overlay 0.6초만 아꼈다(492회 = 5분).
  Sprint 147이 doc_worker 호출 순서를 고쳐 약 130분 절감으로 실현했다(실 worker 2건 41.1s -> 23.8s).
- 사용자 흐름 전 구간을 **실제 브라우저에서 확인**: 검색 썸네일 → 상세 갤러리(5장) →
  PDF 뷰어(19쪽, 페이지 이동/확대) → HTML 뷰어(현황조사서). 자세한 결과는
  `docs/CURRENT_STATE.md` Sprint 145 절.

### 남은 사진/문서 관련 Backlog

- 문서 재수집 정책 (위 "[결정 대기]" 절 — 정책 결정 필요)
- `parsed_document` 파싱 파이프라인 (구현 자체가 없음)
- 131MB PDF 쪽 단위 렌더링 (현재는 "새 탭"으로 우회)
- **스케줄러 미등록 — 릴리스 최우선.** 2026-08-17 실측: 등록된 249개 중 이 저장소를
  가리키는 항목 0개. 남은 진행 중 물건이 9건(전부 2026-08-19 기일)이라
  **2026-08-20부터 검색 결과가 0건이 된다.** 조치는 `register_scheduler_tasks.ps1 -Apply`
  한 줄이며 운영 변경이라 승인 영역이다(dry-run으로 선행 조건 전부 정상 확인함).

---

## Sprint 148~157 (2026-08-17) — 자율 감사 사이클 결과

### 릴리스 블로커가 1건에서 2건으로 늘었다

**블로커 1 — 스케줄러 미등록** (위 절에 기록). Sprint 156에 **증상을 날짜 단위로
특정**했다. `auction.crawl_date` 이력이 공급 중단 시점을 그대로 보여 준다:

```
~ 2026-08-01  매일 크롤 (07-29 68건, 07-30 58건, 07-31 20건, 08-01 278건)
  2026-08-02 ~ 08-11  0건
  2026-08-12  9건 (단발성 — 이 9건이 지금 살아있는 물건 전부)
  2026-08-13 ~ 08-17  0건
```

배관 자체는 멀쩡하다 — `auction` 1,876 ↔ `auction_item` 1,876, 법원 포함 정확 대조에서
**양방향 불일치 0건**이다. `migrate_execute.py` 미실행분은 없다. 입력만 없다.

**블로커 2 — 미추적 파일 15개 (BUGS #105, 신규)**. Commit 금지가 상시 제약이라 의도된
상태지만, **추적 파일이 미추적 파일을 import**한다. `git commit -a`로 커밋하면
`ModuleNotFoundError: No module named 'api.http_cache'`로 **API가 부팅조차 못 한다**
(추적 파일 297개만 복사해 실제로 재현함). 반드시 `git add -A` 후 커밋해야 한다.

### 이 사이클에 고친 결함 8건

```
#105 커밋하면 API가 부팅되지 않는다 (미해결·승인 영역, 탐지 가드는 신설)
#106 결과 0건 안내가 막다른 길 — 재고가 0일 때 "조건을 줄이세요"는 틀린 안내
#107 법원 없는 식별키 2곳 (계열 4번째) — 계열 전체를 막는 회귀 신설
#108 문서 엔드포인트 대소문자 — 큐 어휘(소문자)로 URL을 만들면 400
#109 doc_worker: 창 밖에서도 브라우저 기동 + 기동 실패 시 락 누수
#110 드라이버 설정 실패가 크롬 프로세스를 고아로 남김 (#109 계열 검색의 소득)
#111 읽기 전용 dry-run이 디렉터리를 1,876개 만들고 있었다
#112 경로 규칙 세 번째 사본 (#111의 호출부 전수 검색 소득)
```

`#110`과 `#112`는 각각 `#109`와 `#111`을 고친 뒤 **"같은 계열이 다른 곳에 없는가"를
전수로 훑어** 나왔다. 인스턴스만 고치면 반드시 다음이 남는다.

### 감사 결과 GREEN인 영역

```
E2E 정합성   READY 556 전건 파일 존재·API 200 / auction_image 45건 전건 일치 / 비READY 누출 0
Search      필터 10종·정렬 4종 정확, 페이지네이션 350행 중복 0
Performance 검색 3.2~5.4ms, 상세 2.9ms — 현재 규모에서 인덱스 추가 이유 없음
N+1         검색 3쿼리(size 무관) / 상세 7쿼리(사진 수 무관), 둘 다 가드 신설·기존 확인
Security    GET 29개 무인증 호출, admin 역할 매트릭스 전수(403/403/200/200), 상수시간 비교
문서 드리프트  실제 0건 (★차이 4건은 전부 오탐 또는 정당한 과거 기록)
```

### TEMP B-TREE 정렬 인덱스 — 착수하지 않는다

정렬 쿼리가 **3.2ms**다(`auction_item` 1,876행). 현재 규모에서 얻을 것이 없으므로
데이터가 10배 이상 늘어난 뒤 다시 재는 것이 맞다. 백로그에서 내리지는 않되 우선순위는 낮다.

### 새로 기록한 SKIP (승인 영역)

- `.claude/worktrees/sprint95-false-success-audit` — **1.4 GB** 낡은 worktree가 저장소
  안에 있다(HEAD보다 4커밋 뒤진 c4f74e6, `auction.db` 포함). OneDrive 동기 대상이고,
  평범한 `grep -r`이 그 안의 **옛 코드를 현재 코드로 착각하게 만든다**(이번 감사에서
  실제로 발생). `git status`에 뜨지 않아 알아채기 어렵다. 제거는 파일 삭제라 승인 영역.
  당분간 전수 검색은 `git ls-files` 기반으로 할 것.
- `documents/` 빈 디렉터리 1,674개(+ 사건 1,183 / 법원 5). #111 수정으로 **더 늘지는
  않지만** 기존 것은 그대로다.
- 검색 폼의 면적/특수조건 필터는 크롤러·스키마·API 전 계층에 대응이 없다. 구현은 스키마
  변경(승인)이고, 컨트롤을 감추는 것은 제품 판단이라 양쪽 다 임의로 하지 않는다.


---

## Sprint 190 실측 (2026-08-18) — 공급 중단의 원인은 크롤러가 아니다

`auction.crawl_date` 2026-08-12 이후 0건의 원인을 확정했다. **크롤러는 멀쩡하다.**

```
라이브 프로브 (서울중앙지방법원 1곳, DB 미기록, MAX_ITEMS=10)
  수집 9건 / 186.2초 / 검증 PASS 9 FAIL 0 / 핵심 필드 전부 채워짐
  실행 후 DB 무변경 확인
```

즉 남은 원인은 **예약 작업 0개**(BUGS #123) 하나뿐이다. 등록만 하면 공급이 재개된다.

### 파생 수치 — 계획에 쓸 것

```
전체 크롤 소요        1곳 186초 x 60곳 ≈ 3.1시간   (06:00 시작 -> 09:00 전후 종료)
변경 -> 문서 반영 지연  약 17시간
                      06:00 크롤 -> 09:00 migrate + 재수집 예약 -> 다음 날 02:00 doc_worker
재수집 예약 비용       물건당 0.02 ms (최악 300물건 x 4종 = 0.005초)
claim 1회             0.30 ms — 어휘 확장 전후 동일
```

"당일 반영"이 아니라는 점만 명시해 둔다. 파이프라인 순서(01:50 -> 02:00 -> 06:00)는
`docs/CLAUDE.md`가 정한 그대로이고 바꿀 이유가 없다.

### TEMP B-TREE 정렬 인덱스 — 세 번째로 착수하지 않는다

`claim`이 여전히 `USE TEMP B-TREE FOR ORDER BY`를 쓰지만 **1회 0.30 ms**다.
`(status, priority, auction_date)` 복합 인덱스는 스키마 변경(승인 영역)인데 얻을 것이 없다.
기존 결정("데이터가 10배 이상 늘어난 뒤 다시 잰다")을 유지한다.


---

## Sprint 193 실측 (2026-08-18) — 운영 데이터는 대체로 깨끗하다

`audit_asset_integrity.py` 일곱 검사 실측:

```
GREEN   사진 45행 / 문서 READY 556건 / doc_raw 556행 / 큐<->화면 상태 — 전부 일치
남은 것 고아 문서 디렉터리 1개(12.7MB) / 고아 큐 18행 / 빈 디렉터리 1,674개
```

고아는 전부 **법원을 식별키에 넣기 전**의 잔재다(BUGS #14/#18/#103/#107).
지금 코드는 법원 포함 키를 쓰므로 새로 생기지 않는다. 사용자 피해도 없다 —
서빙이 `auction_item` 을 근거로 하므로 고아 경로는 조회되지 않는다.

### 정리는 승인 영역 (SKIP)

```
cleanup_orphans_dryrun.py --apply     고아 큐 18행
documents/고양지원/2024타경2803/       고아 문서 4개 12.7MB
빈 디렉터리 1,674개                    (BUGS #111 수정으로 더 늘지는 않는다)
git add audit_asset_integrity.py      추적되면 --selftest 를 회귀 스위트로 이동
```

배포 전후 점검에 `python audit_asset_integrity.py` 를 쓰면 되고, 종료 코드만으로
판단할 수 있다(0=정상 / 1=어긋남 / 2=실행 실패).


---

## Sprint 198/199 실측 (2026-08-18)

### 변경 감지 트리거는 실제로 발동한다 (Sprint 196 정정)

```
연속 스냅숏 비교        0건        <- 관측 공백. 이걸로 결론내면 안 된다
물건별 처음<->마지막    44물건 132건 (3.58%)
변경 물건의 전부가      "빠졌다 돌아온" 45물건 안에 있다
저감률                  0.7(34) / 0.8(10)  = 법정 저감률과 일치(측정 검증)
```

- 문서 재수집(spec+status = 2행/물건): 하루 약 1.5물건 = 3행 = **72초**(창의 1%)
- 사진 재수집: **발동하지 않는다**(감정가 0/1,228, 관측 공백 탓이 아님)

`REFRESH_MAX_ITEMS_PER_RUN = 60` 은 실측 대비 40배 여유 — 안전 쪽으로 틀렸으므로 유지.

### 물건 단위 묶기 — 가능함이 실증됐다 (미착수)

```
이동 1회 후 두 번째 종류 정상 수집(창/URL 보존, 실브라우저 확인)
사진 수집 비용 0.0초  -> 사진의 전체 비용은 이동 하나뿐
2종 기준 26% 절감 / 4종이면 이동 3회 절감
```

착수 조건: 대기 + 기일 남은 물건이 수백 이상으로 자란 뒤(BUGS #123 해소 후).
설계 제약은 `docs/SPRINT199_BATCHING_FEASIBILITY.md`.

---

## Sprint 217 (2026-08-19) — 스킵 경로의 실체 기록

### 고친 것

`"이미 존재. 스킵"` 이 `files_saved=[]` 로 돌아와 `doc_raw` 기록을 통째로 건너뛰던
결함(BUGS #144). **파일은 있는데 실체 기록이 없는 상태가 영구로 굳었다** — 다음 수집도
같은 분기를 타므로 스스로 회복되는 경로가 없었다. `existing_doc_files()` 로
세 분기가 이미 가진 파일을 결과에 담게 했다(정책 무변경 — 파일을 다시 쓰지 않고
거짓 개정도 남기지 않는다). 상세는 `docs/SPRINT217_SKIP_PATH_AND_EVIDENCE.md`.

### 그대로 두기로 한 것 (근거 있음)

- **큐 성공기록 실패 후 재시도 시 `document_version_log` 한 행 유실.** 실측으로 확인했고,
  `doc_raw` 가 v1->v2 로 사실을 지키며 그 테이블에는 **제품 독자가 없다.**
  되살리려면 수집 전에 지문을 큐에 적어야 하는데(큐 구조 변경) 사용자 영향이 0이다.
  `test_asset_pipeline.py` 12-K 가 이 상태를 명시적으로 고정한다 — 독자가 생기는 날
  다시 결정하도록 강제한다.

### 남은 결정 대기 (제품/운영)

- **고아 큐 행의 종결 어휘.** `auction_item` 이 없는 큐 행이 수집을 끝내면
  `document_status`도 `doc_raw`도 남지 않는다(실측: `2024타경2803/1` — 큐 done x3,
  디스크 파일 4개, DB 기록 0). 지금 대기 중인 고아 12행은 **전부 기일이 과거**라
  2차 방어선에서 종결되므로 실제 낭비는 없다(2026-08-19 재확인). `SKIPPED_NO_ITEM`
  같은 어휘를 만들지 여부는 제품 판단.
- **문서판 `NO_IMAGE`.** "법원에 원래 없는 문서"와 "이번에 실패한 문서"를 원천에서
  구분할 근거가 아직 없다. 현재 FAILED 는 종류당 1건뿐이라 급하지 않다.

### 여전히 최우선 (승인 영역, 변동 없음)

예약 작업 **0개**. 2026-08-19 기준 **기일이 내일 이후인 물건 0건** — 예고된 그날이 내일이다.
등록 선행 조건은 dry-run 으로 재확인했다(머신 PATH 로는 python 이 안 잡히므로
**SYSTEM 계정 등록 금지**).

---

## Sprint 218 (2026-08-19) — 검색목록 썸네일까지 하나의 기능으로

### 고친 것

BUGS #148 — 저장 계층이 **서빙될 수 없는 사진을 기록**했다(`size <= 0` vs 서빙의
`>= MIN_IMAGE_BYTES`). 241바이트로 재현: 상세와 목록 **양쪽에** "사진 있음"인데 열면 404.
운영 영향 0건(45행 최소 35,746바이트). 상세는
`docs/SPRINT218_SEARCH_LIST_IMAGE_CHAIN.md`.

### 처리 용량 — 지금 병목은 적체가 아니다

```
실행 창 120분 / 행당 24.0초  =>  하루 300행 = 75물건
지금 적체 중 브라우저를 여는 행     17행 (나머지 2,736행은 기일 경과로 5.1ms 종결)
=> 적체 처리 6.8분 = 창의 6%, 여유 17.6배
```

**병목은 최초 수집 총량**이다 — 1,876물건 x 4종 = 7,504행, 현재 방식으로 **25.0일**.

### 개선안 — 물건 단위 배칭 (착수 조건 미충족, 대기)

```
현재    물건당 96.0초 (이동 4회)
배칭시  물건당 44.4초 (이동 1회)   절감 54%
창 기준 75 -> 162물건 / 최초 수집 25.0 -> 11.6일
```

Sprint 199 의 착수 조건(*대기 + 기일 남은 물건 수백 이상*)이 지금 **17행**이라
성립하지 않는다. **데이터 공급이 재개된 뒤**가 옳은 시점이다 —
지금 넣으면 얻는 것은 6.8분의 일부이고 잃는 것은 워커 루프의 단순함이다.

### 결정 대기 (제품)

- **검색목록의 사진 상태 배지.** 목록은 "한 번도 안 해 봄 / 법원에 없음 / 수집 실패"를
  구분하지 못한다(이미지 관련 키가 `thumbnail_url` 하나뿐). 상세는 `images_status` 로
  구분한다. 목록에 그 구분을 노출할지는 제품 결정.
- **서버 측 썸네일 생성.** 썸네일 한 장이 평균 약 101 KB(80x80 인데 원본을 그대로).
  Pillow 의존성이라 승인 영역.

---

## Sprint 219 (2026-08-19) — 큰글씨/접근성 감사 결과와 선행 작업

향후 기능 "큰글씨"를 붙이기 전에 **지금 상태를 처음으로 쟀다.** 화면은 바꾸지 않았다.

### 실측 (실브라우저 `/search`)

```
WCAG AA 대비 미달 81/199 (41%)     text-gray-400 실제 대비 2.6:1 (기준 4.5:1)
탭 타깃 44px 미만 44/53 (83%)      그중 24px 미만 5개 (★ 2026-08-20 Sprint 225 정정: 위반 아님 — 간격 예외로 적합)
물건 주소 12px / "최저입찰가"·"감정가" 11px — 판단에 쓰는 정보가 가장 안 보인다
소스: text-xs 111 / text-gray-400 106, 상세페이지가 가장 심하다(각 55)
```

### 큰글씨의 선행 작업은 생각보다 작다 (2026-08-19 Sprint 220 정정)

이 절은 처음에 *"대부분 px 고정이라 루트 글꼴을 키워도 본문이 따라 커지지 않는다"* 고
적었다. **빌드 CSS 를 열어 보니 사실이 아니었다.**

```
--text-xs: .75rem      Tailwind v4 의 이름 있는 크기는 전부 rem 기반이다
```

`text-xs`(111곳)는 루트 글꼴을 키우면 **그대로 따라 커진다.**
닿지 않는 것은 **대괄호 임의값 8곳**뿐이다(`text-[11px]` 6 + `text-[10px]` 2).

**선행 작업 = 그 8곳을 rem 유틸리티로 교체.** 전면 전환이 아니다.
그 뒤에는 큰글씨 토글을 바로 붙일 수 있다.
`test_frontend_accessibility.py` 6 이 그 8곳을 상한으로 잠갔다.

### 착수 순서 제안 (전부 제품 디자인 결정 — 승인 영역)

```
1. 헤더 내비 탭 타깃 h>=44px       ★ 근거 철회 - 위반이 아니다(Sprint 225). 순수 디자인 판단
2. 주소·가격 라벨 14px + gray-600   판단 정보부터
3. 상세페이지 본문 최소 14px        실제 판단이 일어나는 화면
4. text-[10~11px] 8곳을 rem 유틸로  큰글씨의 유일한 기술적 선행 작업 (전면 전환 아님)
5. 큰글씨 토글                      4가 끝난 뒤 바로 붙일 수 있다
```

### 재지 못한 것

**모바일 뷰포트 레이아웃(390~412px)은 확인하지 못했다** — 자동화의 창 리사이즈가
페이지 뷰포트에 반영되지 않고, `X-Frame-Options: DENY` 라 iframe 우회도 막혔다.
"모바일에서 깨지지 않는다"는 **아직 주장할 수 없다.** 실기기 또는 DevTools
디바이스 모드로 사람이 한 번 봐야 한다.

### 잠근 것

`test_frontend_accessibility.py` — 현재 수치를 **상한**으로 고정(줄면 통과, 늘면 실패),
확대 차단 부재, `alt` 규약. 변이 4종 전부 검출.

---

## 향후 기능 1번 "마이리스트 복붙/내보내기" — 구현 가능 범위 분석 (2026-08-19)

roadmap 이 *"단, 현재 구현 가능 범위를 먼저 분석한다 ... 추측하지 않는다"* 고 적은
그대로 수행했다. **구현하지 않았다.** 상세는
`docs/SPRINT219B_MYLIST_EXPORT_FEASIBILITY.md`.

### 막는 것은 기능이 아니라 **식별자**다 (실측 1,876행)

```
병합 사건 ("2008타경25092 / 2015타경19958")   425행 (22.7%)
물건번호가 1이 아닌 행                         629행 (33.5%)
법원명 표기                                     60종
```

사건번호 하나로 물건을 특정할 수 없고, 22.7% 는 애초에 사건번호가 둘이다.
**어느 쪽을 대표로 내보낼지는 제품 결정**이라 우리가 정할 수 없다.

### 확인하지 못한 것 (추측하지 않는다)

지지옥션/탱크옥션의 **실제 입력 형식** — 사건번호 단독인지, 물건번호를 포함하는지,
법원을 문자열로 받는지 코드로 받는지, 여러 건을 한 번에 붙일 수 있는지.
전부 **확인하지 못함**이다("없음"이 아니다). 확인하려면 사람이 상대 서비스의
입력 화면이나 도움말을 봐야 한다.

### 지금 만들 수 있는 것 (미구현 제안)

```
안전   형식 중립 CSV/TSV 내보내기 + 클립보드 복사(탭 구분)
보류   상대 서비스 전용 포맷 — 형식 확인 전에는 만들지 않는다
       (틀린 형식은 "붙여넣었는데 안 들어간다"로 조용히 실패한다)
```

### 선행 조건

`favorites` **0행**이고 검색 재고가 곧 0이 된다. 즉 이 기능은
**데이터 공급 재개 뒤**에야 값을 갖는다 — 지금 만들면 빈 목록을 내보낸다.

---

## Sprint 221 (2026-08-19) — 화면 간 사진 일관성 공백 (신규 Backlog)

### 발견

`thumbnail_url` 을 주는 API 는 `api/v1/search.py` **하나뿐**이다.
**관심물건(`/favorites`)과 최근 본 물건(`/properties/recent`) 화면에는 `<img>` 가
아예 없다.**

```
사용자 흐름:  검색목록에서 사진을 보고 → 관심물건에 담고 → 관심물건에서 사진이 사라진다
```

기존 문서·결정 기록에 이에 대한 언급이 없다(Sprint 145 는 검색목록만 다뤘다).
즉 **의도된 제외가 아니라 미문서화 공백**으로 보인다.

### 해결 (2026-08-20, Sprint 224) — `docs/BUGS.md` #156

Backlog 지시로 구현했다. 예상했던 것과 달리 **레이아웃 결정이 거의 필요 없었다** —
`thumbnail_url` 이 있을 때만 그리고 없으면 종전과 완전히 같은 텍스트 전용 카드를
유지하므로, 사진 없는 물건의 화면은 픽셀이 바뀌지 않는다.

```
API   api/v1/thumbnails.py 신설 — URL 규칙 + 배치 조회의 **유일한 출처**
      search.py / item.py 도 이것을 쓰게 바꿔 흩어져 있던 규칙 2곳을 없앴다
      favorites.py / recent_items.py 에 배치 조회 1회씩 추가 (N+1 아님, 실측 2건 2회 / 10건 2회)
화면  ResultThumbnail.tsx 를 src/components/ 로 옮겨 세 화면이 공유
```

트래픽 우려(썸네일 1장 약 101 KB)는 그대로 유효하다 — 서버 측 썸네일 생성은
여전히 승인 영역이고, 원본을 80x80 으로 줄여 그리는 상태다. 다만 두 화면은
검색목록과 달리 **한 페이지에 담기는 건수가 작다**(최근 본 물건은 상한 20건).

### 실측 (실브라우저)

```
최근 본 물건  카드 11개 중 사진 4개, <img> 4개 전부 naturalWidth > 0 (실제 디코딩됨)
             카드 폭 사진 유무와 무관하게 411px / 가로 오버플로 0 / 콘솔 오류 0
관심물건      이 계정 0건이라 **운영 DB 사본**으로 확인 (카드 6개 중 사진 4개)
```

### 잠근 것

`test_search.py` 의 규칙(어느 화면이든 `thumbnail_url` 을 그리면 그 API 도 주어야 한다)은
그대로 유효하고, 이제 세 화면 모두 그리고 세 화면 모두 받는다.
`test_asset_pipeline.py` 16-B2 가 **네 화면이 글자 그대로 같은 URL** 을 주는지,
그 URL 이 실제로 200 으로 열리는지, 건수가 늘어도 쿼리 수가 같은지까지 본다(변이 5/5).

★ 정정: 위에서 "관심물건/최근본물건은 `SELECT ai.*` 라 계약이 스키마에 묶여 있다"고
적었는데, 실제 응답은 `dict(row)` 가 아니라 **명시적 dict 리터럴**이다. 계약의 근거는
스키마가 아니라 그 dict 이고, `test_search.py` 도 그렇게 읽도록 고쳤다(Sprint 224).
스키마 결합은 따로 본다 — dict 가 읽는 `row["X"]` 의 X 가 실제 컬럼인가(없으면 500).



---

## Sprint 223 (2026-08-19) — 접근성 기술 결함 4건 · 큰글씨 기술 기반 완료

### 끝난 것

```
BUGS #151  모달 포커스 트랩          첫 진입 / Tab 순환 / 닫을 때 여는 버튼으로 복귀
BUGS #152  동적 상태 메시지 알림      13곳 alert|status + 검색 결과용 항상 존재하는 한 줄
BUGS #153  화면마다 main 랜드마크     4개 화면에 없던 것을 채움(로딩·실패 분기 포함)
BUGS #154  검사 도구 스캔 범위        저장소 사본(스테일 worktree) 101개를 훑고 있었다
큰글씨      고정 px 글자 8곳 -> 0곳    같은 크기의 rem 으로 교체(픽셀 무변경)
성능        검색 SQL 3회 고정          N+1 아님을 계측으로 확인하고 회귀로 잠금
```

전부 **픽셀을 바꾸지 않는 기술 수정**이라 제품 디자인 결정이 아니다.

### 큰글씨 — 이제 남은 것은 제품 결정뿐이다

기술 기반이 끝났다. 루트 글꼴을 키우면 **모든 글자가 따라 커진다**(실측: 32px 에서
전에 11px 고정이던 자리가 22px). 남은 결정은 **색·크기·간격을 얼마로 할지**와
토글 UI 를 둘지다 — 그것은 승인 영역이다.

### 다음 후보 (승인 없이 가능한 것부터)

```
1. 모바일 실뷰포트 검증        도구 제약으로 **여전히 확인 불가**(재확인함) — 사람 손이 필요
2. 관심물건·최근본물건 썸네일   제품 결정. 게다가 최근 본 34개 중 사진이 있는 것은 **4개**뿐
3. 마이리스트 내보내기          부르는 곳이 없다(favorites 0행) — 죽은 코드가 된다
4. filter/ 죽은 코드 삭제       승인 영역
5. 스테일 worktree 정리         `git worktree remove` = 승인 영역
```

---

### 2026-08-20 Sprint 236 - 문서 워커 처리 능력 (배경 갱신)

Sprint 235 가 적은 능력 수치(165건/일)와 batching 이득(4.0배)은 **틀렸다**.
`법원 선택` 로그 간격을 이동 비용으로 읽었는데 그 안에 수집과 sleep 이 들어 있었다.

```
실측    행 1개당 23.2초 (897행/5.8시간) / 이동 1회 15.2초
예전    78건/일   <- 실측 공급 중앙값 106건조차 감당하지 못했다
지금    153건/일  (물건 단위 batching, 이동 4회 -> 1회)
```

**다음 순서** (전부 승인 영역)

```
1. Scheduler 등록 + 크롤 재개      출시 blocker. 이것 없이는 나머지가 무의미하다
2. 실행 창 02:00~05:38 로 확대      최대 공급일(278건)을 덮는다. 06:00 크롤과 안 겹친다.
                                   ExecutionTimeLimit(4h) 안에 들어간다. **가장 값싼 다음 수**
3. 행당 sleep(2초) 재검토           물건당 8초 = 배치 비용의 17%. 법원 서버에 대한 예의라
                                   임의로 줄이지 않는다
4. MAX_ITEMS 상향                   위 셋 다음. 지금 올리면 큐만 더 밀린다
```

---

### 2026-08-20 Sprint 237 - 실행 창 / MAX_ITEMS / 캐시 (배경 갱신)

**실행 창은 05:38 로 넓힐 수 있다** - 실제 가드에 태워 확인했다(변경은 하지 않았다).
안전 상한은 **05:55**(06:00 크롤 앞 5분 여유). 05:56 부터 막힌다.

**MAX_ITEMS 는 아직 아니다.** 크롤 로그 1,698회 중 12.1%가 상한에 걸려 공급이
잘리고 있지만, 올렸을 때의 공급은 **자료가 잘려 있어 알 수 없다.**
지금 여유는 1.44배뿐이고, 창을 05:38 로 넓히면 2.61배가 된다.

```
순서   1. Scheduler 등록 + 크롤 재개   (출시 blocker)
       2. 실행 창 02:00~05:38
       3. 크롤 재개 후 시간 재측정      <- 지금 상수는 2026-08-02 이전 로그의 값이다
       4. MAX_ITEMS 상향
```

★ 3번이 중요하다. 이 세션과 Sprint 236 의 시간 상수(행 23.2초 / 이동 15.2초)는
모두 **batching 이전, 기일 경과 방어 이전**의 로그에서 나왔다. 그 로그에는 형제
재사용도 정확 일치도 0회로 기록돼 있다 - 지금 코드의 성능이 아니다.
