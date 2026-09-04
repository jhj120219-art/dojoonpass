DojoonPass(콕찰) — **본업이 있는 투자자를 위한 경매 의사결정 서비스.**

경매 정보를 더 많이 주는 서비스가 아니라, **한 물건을 판단하기까지 걸리는 시간(T2D)을
줄이는** 서비스다. 사용자의 흐름은 네 칸이다:

    DISCOVER (검색·필터) → REVIEW (권리·임차인·문서) → FIELD (임장) → DECIDE (입찰 판단)

제품 정의(고객/문제/가치/Workflow/KPI)의 정본은 `docs/PRODUCT_STRATEGY.md` 다.

프로젝트 현황, 완료/미완료 기능, 로드맵은 이 README가 아니라 `docs/`(특히 `docs/roadmap.md`,
`docs/CURRENT_STATE.md`, `docs/backend.md`)를 기준으로 확인한다. 이 README는 별도의 진행률
정보를 유지하지 않는다 (Single Source of Truth는 `docs/README.md` 참고).

---

## 구성

| 영역 | 스택 | 진입점 |
|---|---|---|
| Frontend | Next.js (App Router) | `src/app/` |
| Backend | FastAPI | `api_server.py` + `api/v1/*.py` |
| Database | SQLite | `auction.db` (`storage/database.py`) |
| Auth | Supabase Auth (JWT) | `api/auth.py`, `src/proxy.ts` |
| Crawler | Selenium | `mvp_scraper.py` → `migrate_execute.py` |

화면과 Workflow 의 대응:

| 단계 | 화면 | API |
|---|---|---|
| DISCOVER | `src/app/search`, `src/app/page.tsx` | `api/v1/search.py` |
| REVIEW | `src/app/properties/[id]` | `api/v1/item.py`, `documents.py`, `images.py` |
| FIELD | `src/app/properties/[id]/field` | `api/v1/field_visits.py` |
| DECIDE | 같은 화면의 판단 버튼 | `api/v1/field_visits.py` (`/decision`) |

인증만 Supabase를 쓰고, 경매 데이터는 전부 SQLite에서 FastAPI를 거쳐 나온다.

## 실행

```bash
# Frontend (localhost:3000)
npm install
npm run dev

# Backend API (127.0.0.1:8000, Swagger UI: /docs)
python api_server.py
```

두 서버를 함께 띄워야 검색/상세/결제 화면이 동작한다. 환경변수는
`docs/ENVIRONMENT_VARIABLES.md`를 참고한다(`.env` = 백엔드, `.env.local` = 프론트).

## 검사

```bash
python run_python_tests.py          # 파이썬 회귀 전체 (이것이 게이트다)
npm run test:frontend               # 프런트 회귀 (먼저 next 서버를 띄운다)
npx tsc --noEmit                    # Type Check
npx eslint .                        # Lint
npm run build                       # 빌드
```

위 다섯 줄이 이 저장소의 게이트다. `run_python_tests.py` 는 루트의 `test_*.py` 를
스스로 찾아 돌리므로 새 회귀를 따로 등록할 필요가 없다. **건너뜀과 판정없음은
통과가 아니다** — 요약이 그 둘을 따로 세고 이름을 남긴다.

아래는 한 영역만 빠르게 볼 때 쓰는 부분집합이다(전체를 대신하지 않는다).

```bash
python test_api_regression.py       # 전 도메인 HTTP 회귀
python test_subscription_policy.py  # 구독 정책 회귀
python test_field_visits.py         # 임장(FIELD→DECIDE) 회귀
python test_migration_chain.py      # 마이그레이션 체인 (fresh + 운영 사본)
python audit_time_to_decision.py    # T2D 측정 (읽기 전용)
```

자세한 커버 범위와 수동 확인 항목은 `docs/TEST_PLAN.md`를 본다.

## 작업 규칙

`docs/CLAUDE.md`에 정리되어 있다. 요약하면 Breaking Change 금지, 기존 API 응답 구조 유지,
SQLite 유지, `itemId` 단일 식별자 유지, 최소 변경 원칙이며 새 라이브러리 설치·`.env` 수정·
DB 스키마 변경은 승인 후에만 진행한다.
