DojoonPass(콕찰) — 법원경매 검색/상세조회/관심물건/등기부 신청/결제 서비스.

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
| Auth | Supabase Auth (JWT) | `api/auth.py`, `src/middleware.ts` |
| Crawler | Selenium | `mvp_scraper.py` → `migrate_execute.py` |

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
npx tsc --noEmit                    # Type Check
npx eslint .                        # Lint
npm run build                       # 빌드
python test_api_regression.py       # 전 도메인 HTTP 회귀
python test_subscription_policy.py  # 구독 정책 회귀
```

자세한 커버 범위와 수동 확인 항목은 `docs/TEST_PLAN.md`를 본다.

## 작업 규칙

`docs/CLAUDE.md`에 정리되어 있다. 요약하면 Breaking Change 금지, 기존 API 응답 구조 유지,
SQLite 유지, `itemId` 단일 식별자 유지, 최소 변경 원칙이며 새 라이브러리 설치·`.env` 수정·
DB 스키마 변경은 승인 후에만 진행한다.
