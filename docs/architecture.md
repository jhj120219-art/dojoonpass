Frontend

↓ (search / favorites / recent-items / item 상세 데이터 / payments / registry-requests)

API (FastAPI, /api/v1/*)

↓

Database (SQLite, auction.db)

↓

Crawler

---

API (api/v1/payments.py)

↓ (get_payment_provider(), 환경변수 PAYMENT_PROVIDER=mock/kginicis/toss/portone)

Payment Provider (api/v1/payment_providers.py)
  - MockProvider (현재 사용, 항상 SUCCESS)
  - KGInicisProvider (확정된 PG사, 2026-08-07 클래스 신설 — 6개 메서드 전부
    NotImplementedError. 실제 API 호출 구현은 계약/API Key 발급 후 승인 필요)
  - TossProvider / PortOneProvider (폐기 예정 후보. 선택 시 NotImplementedError +
    경고 로그. 삭제는 승인 필요 작업이라 코드에 그대로 남아있음)

↓ (PG 실연동 시에만)

PG사 (KG이니시스 — 2026-08-06 확정, 실연동 미착수)

---

Frontend

↓ (인증 세션 공통 + /properties 목록·상세진입 데이터, 2026-08-05 기준 API 미경유)

Supabase (Auth + Postgres)

---

Scheduler (Task Scheduler) → Crawler 자동 실행

---

Admin (운영자, 별도 인증 — 2026-08-07부터 SUPER_ADMIN / ADMIN 2단계, 키 값으로 등급 판정)

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
`KGInicisProvider`(2026-08-07 신설) 및 폐기 예정인 `TossProvider`/`PortOneProvider`는
이름과 자리만 있을 뿐 호출하면 `NotImplementedError`가 난다.
**2026-08-06 PG사가 KG이니시스로 확정**되어 `KGInicisProvider` 클래스와 `PAYMENT_PROVIDER=kginicis`
경로는 코드에 반영됐고, 남은 것은 그 안의 **실제 API 호출 구현뿐**이다(외부 API Key/계약 필요로
승인 대기). Provider 인터페이스 자체(v2)는 PG사와 무관하게 설계돼 있어 KG이니시스 연동에도
그대로 재사용 가능하다.

---

Payment (api/v1/payments.py)

↓ (단계별 append-only 기록, 2026-08-07 추가)

payment_logs (CREATE_ORDER / CONFIRM / VERIFY / CANCEL / WEBHOOK)
payment_webhooks (PG 노티 원문 + event_id 멱등 + 서명 검증 여부)

  ※ 실제 PG 호출은 없다. 구조만 준비된 상태이며 MockProvider가 남기는 로그가 전부다.

---

Frontend (구독 UI)

↓ GET /api/v1/plans  ← **가격/플랜의 단일 Source of Truth**

api/v1/payments.py : PLAN_CATALOG + resolve_plan_price()

  ※ 프론트는 가격을 갖지 않는다. 표시 금액과 결제 검증 금액이 같은 함수에서 나온다.

---

Admin (SUPER_ADMIN)

↓ POST /api/v1/admin/registry-credits

registry_credits (조정 원장 — 잔액 컬럼 없음)

↓ 유효 한도 = 플랜 월 한도 + 이번 달 조정 합계

api/v1/registry.py : get_user_free_limit()
