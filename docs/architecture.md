Frontend

↓ (search / favorites / recent-items / item 상세 데이터 / payments / registry-requests)

API (FastAPI, /api/v1/*)

↓

Database (SQLite, auction.db)

↓

Crawler

---

API (api/v1/payments.py)

↓ (get_payment_provider(), 환경변수 PAYMENT_PROVIDER=mock/toss/portone)

Payment Provider (api/v1/payment_providers.py)
  - MockProvider (현재 사용, 항상 SUCCESS)
  - TossProvider / PortOneProvider (자리만 있음, 호출 시 NotImplementedError — PG사 미확정)

↓ (PG 실연동 시에만)

PG사 (Toss/PortOne, 미연동)

---

Frontend

↓ (인증 세션 공통 + /properties 목록·상세진입 데이터, 2026-08-05 기준 API 미경유)

Supabase (Auth + Postgres)

---

Scheduler (Task Scheduler) → Crawler 자동 실행

---

Admin (운영자, 별도 인증)

↓ (X-Admin-Key 헤더, Supabase JWT 아님)

API (FastAPI, /api/v1/admin/*)

↓

Database (registry_requests 상태/doc_url 관리)

---

Admin (운영자, 등기부 파일 수동 배치)

↓ (대법원 인터넷등기소 등에서 수동 발급 → 실연동 아님)

registry_documents/ (신규 디렉터리, .gitignore)

↓ (Admin이 PATCH .../admin/registry-requests/{id}에 doc_url 등록)

Frontend(본인 확인 후) ↓ GET /api/v1/registry-requests/{id}/download ↓ 실제 파일

---

주의: Frontend는 위 두 경로(FastAPI / Supabase)를 화면별로 병행 사용 중이며 하나로 통합되지 않았다
(`/properties` 목록만 Supabase 직접 조회로 남아있음 — 자세한 화면별 경로는 `docs/frontend.md` "API 호출 방식" 참고).
Payment(payments.py) → Subscription(subscriptions) → Premium(has_active_subscription) →
Registry(registry.py) → **Download(registry_documents/, 2026-08-05 추가)** 체인은 전부
Frontend↔API 화살표에 포함된다(`properties/[id]/page.tsx`가 `payments`/`registry-requests`를
실제로 호출, 기존 Supabase `view_counts` 기반 구현은 삭제됨). Admin 경로만 별도 인증
(`X-Admin-Key`)으로 완전히 분리되어 있다. **Download 엔진은 자동 수집기가 아니다** —
크롤러(Crawler 박스)는 STATUS/SPEC/APPRAISAL만 수집하고 등기부등본은 대상이 아니므로,
운영자가 별도로 발급받아 `registry_documents/`에 배치하는 수동 경로로 연결된다.

**Payment Provider(2026-08-05 추가)는 서비스/레포지토리 계층이 아니다** — `payments.py` 라우터는
여전히 SQLite에 직접 쓰고 읽으며(기존 아키텍처 그대로), Provider는 오직 "이 결제가
승인됐는지"만 판단해 돌려주는 좁은 역할만 한다. 지금은 `MockProvider`만 실제로 쓰이고
`TossProvider`/`PortOneProvider`는 이름과 자리만 있을 뿐 호출하면 에러가 난다.