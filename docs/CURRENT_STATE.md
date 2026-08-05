현재 브랜치

master (2026-08-05 기준 재확인. 이전 버전은 "main"으로 기재되어 있었으나 실제 브랜치명과 다름)

현재 작업

Payment Flow Migration(payments.py를 Interface v2 흐름으로 연결) 완료 → 문서 동기화(Documentation Sync)

**✅ Release Blocking 없음** (Sprint 10에서 해소, 유지 중). 이번 Sprint는 실제 PG API 호출/Webhook
없이 `payments.py`의 내부 호출 순서만 바꿈 — 응답 구조·Frontend·DB 스키마 무변경(회귀 없음).

완료

☑ middleware (Supabase 세션 게이트, `/properties/*`)

☑ Supabase Auth (로그인/회원가입/세션)

☑ Search (`/search`, `api/v1/search.py`, D7 종결물건 기본 필터 포함)

☑ Detail (`/properties/[id]`, `api/v1/item.py`)

☑ Favorites (`/favorites`, `api/v1/favorites.py`)

☑ Recent Items (`/properties/recent`, `api/v1/recent_items.py`)

☑ Payment Mock API (`api/v1/payments.py`, 2026-08-05)

☑ Subscription 자동 생성 (결제 성공 시)

☑ Premium 판정 (`has_active_subscription()`, Registry 신청 게이트로 실사용 중)

☑ Registry 프론트 연동 (`properties/[id]/page.tsx`가 `registry-requests`/`payments` 직접 호출, 기존 Supabase `view_counts` 구현은 삭제)

☑ OVERAGE_USAGE 결제 → `registry_requests.payment_id`/`status` 자동 연결 (트랜잭션, 중복방지, rollback)

☑ Admin MVP (`api/v1/admin.py` — 목록조회/필터/상태전이/completed_at/reason, `X-Admin-Key` 인증)

☑ Registry Download Engine (`GET /registry-requests/{id}/download` 실제 파일 서빙, Admin `doc_url` 연결, 본인확인+경로탐색 방지, `registry_documents/` 신규 디렉터리) — 자동 등기부 수집기는 아님(운영자 수동 배치)

☑ Registry Download UI (`properties/[id]/page.tsx`: `COMPLETED`→다운로드 버튼, `FAILED`→사유 표시. 실제 브라우저에서 다운로드 폴더에 파일 저장까지 Runtime QA 확인)

☑ Payment Provider 구조 분리 (`api/v1/payment_providers.py` — `MockProvider`/`TossProvider`/`PortOneProvider` 자리, `PAYMENT_PROVIDER` 환경변수로 선택, 기본값 mock)

☑ Payment Provider Interface v2 (`create_order`/`confirm_payment`/`cancel_payment`/`verify_payment`/`handle_webhook` 추가, `MockProvider` 전부 구현, `TossProvider`/`PortOneProvider`는 여전히 자리만)

☑ Payment Flow Migration (`payments.py`가 `create_order`→`confirm_payment`→`verify_payment` 순서로 provider 호출, `SUBSCRIPTION`/`OVERAGE_USAGE` 둘 다 새 Flow로 정상 동작 확인. `cancel_payment`/`handle_webhook`은 여전히 미연결)

☑ `SUBSCRIPTION` 결제 금액 서버 검증 (`PLAN_PRICES`, `OVERAGE_USAGE`와 동일 방식 — 이제 둘 다 완료)

☑ 등기부 무료횟수 레이스 컨디션 수정 (`registry.py`에 `BEGIN IMMEDIATE` 적용, 5/10/20 스레드 동시 요청 테스트로 재검증 — Release Blocking 해소)

진행중

□ `ADMIN_API_KEY`를 `.env`에 설정 (Admin 코드는 완료, 값 미설정으로 현재 500)

□ 등기부 무료한도 정책 통일 (코드=평생 5회 vs 문서=월 5회 — 어느 쪽이 맞는 정책인지 미결정)

다음

□ PG사 확정 (사용자/PM 의사결정) → `TossProvider`/`PortOneProvider`가 Interface v2의 6개 메서드를 실제 API 호출로 구현

□ 환불(`cancel_payment`)/Webhook(`handle_webhook`) 엔드포인트 신규 구현 — 여전히 미연결

□ 구독 플랜 비교/선택 UI (현재 베타 얼리버드 단일 옵션 버튼만 존재)

□ (Beta v2) 등기부등본 실제 발급기관(대법원 인터넷등기소 등) 자동 연동

자세한 근거와 우선순위는 `docs/roadmap.md`("진행률 재계산" 섹션), `docs/backend.md` 참고.
