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

↓ (**인증 세션 전용**. 2026-08-31 정정 — 경매 데이터 경로는 남아 있지 않다)

  ~~+ /properties 목록·상세진입 데이터, 2026-08-05 기준 API 미경유~~
  → 2026-08-11 Sprint 51 에 `/properties` 는 `redirect('/')` 한 줄이 됐고
    `SearchFilters.tsx` 는 삭제됐다(2026-08-31 실측: `src/app/properties/` 아래는
    `page.tsx`(redirect) / `LogoutButton.tsx` / `[id]/` / `recent/` 뿐).
    즉 **경매 데이터를 Supabase 에서 직접 읽는 화면은 이제 0개**이고,
    `docs/CLAUDE.md` 의 "경매 데이터는 항상 Python API 경유" 규칙에 위반이 없다.

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

~~주의: Frontend는 위 두 경로(FastAPI / Supabase)를 화면별로 병행 사용 중이며 하나로 통합되지 않았다
(`/properties` 목록만 Supabase 직접 조회로 남아있음).~~
**2026-08-31 정정: 병행 사용은 끝났다.** Supabase 는 인증 세션만 담당하고, 경매 데이터는
전 화면이 FastAPI 를 경유한다(`/properties` 는 2026-08-11 Sprint 51 에 `/` 로 영구 이동).
화면별 경로는 `docs/frontend.md` "API 호출 방식" 참고.
이 경계는 `tests/supabase-boundary.test.mjs` 가 회귀로 고정한다.
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

---

시각·날짜 계약 (2026-09-01 전수 실측으로 작성 — 새 정책이 아니라 **이미 그렇게 돌고 있는 것**의 기록)

이 저장소에는 의미가 다른 날짜가 네 종류 있고, **섞으면 조용히 틀린다.**

```
① 사건이 일어난 날짜   auction_date / filed_date / demand_deadline / priority_date
                      move_in_date / fixed_date / demand_date
                      법원 페이지의 값을 그대로 저장한다. 날짜-only(YYYY-MM-DD).
                      화면에 **가공 없이** 찍는다 (`{property.case.filed_date || '-'}`).

② 우리가 수집한 날짜   crawl_date
                      `datetime.today().strftime("%Y-%m-%d")` — 서버 로컬 날짜.
                      ①과 절대 같은 것으로 취급하지 않는다.

③ DB 행의 생성/수정    created_at / updated_at / viewed_at / favorited_at
                      started_at / expires_at / requested_at / enqueued_at ...
                      전부 `datetime.now().isoformat()` = **naive 로컬(KST) 시각**.

④ 화면의 "오늘"        `src/lib/format.ts` 의 DISPLAY_TIME_ZONE = 'Asia/Seoul'
                      `todayInDisplayZone()` / `ymdPlusDays()` / `formatDday()`
```

계층별 기준

```
DB 저장            naive 로컬 문자열. 오프셋도 Z 도 붙이지 않는다
                   -> test_pipeline_integrity.py §9-b 가 tz-aware 생성 0건을 고정

SQLite 시각 비교    반드시 `datetime('now','localtime')`
                   storage/database.py 의 `_NOW_LOCAL` 하나만 쓴다
                   -> §9 가 `now` 를 쓰면서 localtime 을 빠뜨린 자리 0건을 고정

Backend 계산       서버 로컬. `date.today()` (api/v1/search.py 의 기본 기일 필터)
                   서버가 어느 시간대에서 도는가는 **배포 결정(승인 영역)**이다

API serialization  변환하지 않는다. DB 문자열을 그대로 싣는다

Frontend 표시      ③ 은 `new Date(값).toLocaleDateString('ko-KR')`
                   -> naive 문자열이라 **로컬로 파싱되고 로컬로 찍혀 대칭**이다.
                      그래서 어느 나라에서 봐도 한국 달력 날짜가 그대로 보인다.
                      ★ 여기에 `timeZone: 'Asia/Seoul'` 을 붙이면 **오히려 깨진다**
                        (이미 로컬로 해석된 값을 한 번 더 옮기게 된다)
                   ① 은 문자열 그대로 찍는다
                   ④ 만 DISPLAY_TIME_ZONE 을 쓴다
```

왜 ④만 시간대를 고정하나 — ①②③은 **이미 확정된 값**을 보여 줄 뿐이지만, "오늘"은
보는 사람의 시계에서 계산된다. 그래서 브라우저 시간대가 개입할 수 있는 유일한 자리다.

자정 경계

```
날짜-only 값끼리의 뺄셈은 **문자열을 날짜로 파싱해 날짜끼리** 뺀다
  (format.ts 의 parseYmdToUtcMs / daysBetween / ymdPlusDays — 시각을 끼우지 않으므로
   시간대도 서머타임도 개입할 자리가 없다)
`toISOString().slice(0, 10)` 로 "오늘"을 만들지 않는다 — UTC 날짜라 KST 09:00
  이전에 하루 당긴다. 실제 결함이었다(docs/BUGS.md #270)
  -> tests/source-contract.test.mjs 가 src 전체에서 이 모양을 금지한다
```

알려진 불일치 (고치지 않았다 — 제품 결정)

```
storage/database.py:calc_priority()
  `(자정 - datetime.now()).days` 라 **달력 일수 - 1** 이다.
  같은 auction_date 에 대해 화면 배지(formatDday)는 달력 일수를 쓴다.
  달력 4일 뒤 물건: 배지 "입찰 4일전" / 큐 등급 days_left=3 -> 최우선(1)
  경계를 옮기는 것은 "어떤 물건을 먼저 받는가"라는 정책이다.
  경위와 근거는 test_document_queue.py 의 calc_priority 경계 검사 주석 참고.
```
