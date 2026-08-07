# Test Plan

Status: Active
Last Updated: 2026-08-07

이전 버전(16줄짜리 체크리스트)은 "이미지 ☑", "권리분석 ☑"처럼 **존재하지 않는 기능을 완료로
표시**하고 있었고 실제로 상시 실행 중인 회귀 테스트 2종도 전혀 언급하지 않았다.
2026-08-07 코드 기준으로 다시 작성한다.

---

## 1. 자동 회귀 테스트 (상시 실행 가능)

별도 러너(pytest 등) 설정은 없다. 두 스크립트를 직접 실행한다.

```bash
python test_api_regression.py       # 전 도메인 실제 HTTP 회귀 (377 검사)
python test_subscription_policy.py  # 구독 정책/할인/월 리셋/식별키 무결성/credit 원장 (48 항목)
```

두 스크립트 모두 **실제 `auction.db`를 사용하되 실사용자 데이터는 건드리지 않는다.**

- `test_api_regression.py`: FastAPI `TestClient`로 `api_server.app`을 직접 호출한다(라우팅/
  의존성/인증/직렬화까지 실제 요청과 같은 경로). 테스트 데이터는 `qa-reg-<uuid>` 전용
  user_id로만 만들고 종료 시 그 행만 삭제한다. `ADMIN_API_KEY`는 프로세스 환경에만 주입한다
  (`.env` 무수정).
- `test_subscription_policy.py`: 정책 계산 함수를 직접 검증하고, DB를 건드리는 검사는
  트랜잭션 롤백 안에서 수행한다.

### `test_api_regression.py` 커버 범위

| # | 섹션 | 주요 검사 |
|---|---|---|
| 1 | Health / Stats | 루트·`/stats`·`/document-stats` 응답 형태 |
| 2 | Search | 비로그인 접근, 필터, **정렬 화이트리스트(미허용 값 400)**, 페이지네이션 경계, 인젝션 문자열 무해 처리 |
| 3 | Detail / Documents | 상세 필드, 문서 서빙, **`case.court_code`와 물건 `court_name` 일치**(복합키 Migration 회귀 방어) |
| 4 | Authentication | 무토큰 401 / 위조 토큰 401 / `sub` 없는 토큰 401 / 정상 토큰 200 |
| 5 | Favorite | 등록·중복 거부·목록·삭제, 검색 결과의 `is_favorited` 반영, 소유권 격리 |
| 6 | Recent items | 상세 조회 시 자동 기록, 재조회 시 중복 행 없음 |
| 7 | Search presets | 저장·목록·조건 round-trip·삭제, 소유권 격리, **서버측 입력 검증**(공백/길이/크기/개수 상한, 이름 trim) |
| 8 | Payment / Subscription | 금액 위조 거부, 폐기 플랜명 거부, 잘못된 결제주기 거부, 월/연 기간, 할인가 적용, 소유권 격리 |
| 9 | Registry | 구독 게이트, 무료 한도, 소유권 격리, 미완료 다운로드가 파일이 아님 |
| 10 | Registry overage | 한도 초과 → `PAYMENT_REQUIRED` → 결제 → `payment_id` 연결 |
| 11 | Admin | 키 없음/오답 403, 필터, **상태 전이 규칙 전수**, `completed_at`, 없는 파일에 거짓 성공 없음 |
| 12 | Payment Provider | `kginicis` 선택, **6개 메서드가 전부 `NotImplementedError`**(실연동 전 결제가 성공한 것처럼 보이는 사고 방지), 폐기 후보 2종, 알 수 없는 값, 미설정 기본값 |
| 13 | 정렬 결정성 | 동일 타임스탬프 행에서도 목록 순서가 호출마다 동일하고 `id` 내림차순 전순서인지 |
| 14 | 구독 플랜 tie-break | 같은 `started_at`의 BASIC→PRO 업그레이드에서 한도 10이 나오는지 (`docs/BUGS.md` #16) |
| 15 | 가격 미러 정합성 | 프론트 `PLAN_OPTIONS`와 서버 `PLAN_CATALOG`의 한도·정상가·청구액이 일치하는지 |
| 16 | API 표면 고정 | 엔드포인트 23개 집합이 그대로인지(사라짐/추가 둘 다 검출), **OpenAPI 생성 시 경고 0건**, HEAD 프로브가 GET과 같은 상태코드를 주는지 |
| 17 | 응답 envelope | 인증 라우트 5종이 `{success, data, message}` 계약을 유지하는지 / 공개 라우트(search)는 flat 형태 유지 |
| 15 | Plan API | `GET /api/v1/plans`가 `PLAN_CATALOG`와 일치하는지, 응답 금액 그대로 결제가 통과하는지, **프론트에 가격 하드코딩이 되살아나지 않았는지** |
| 18 | CORS 설정 | 미설정 시 `*`, `CORS_ALLOW_ORIGINS` 지정 시 그 목록만 파싱되는지 |
| 19 | Admin 권한 2단계 | 키별 등급 판정, ADMIN은 조정 불가(403)·SUPER_ADMIN은 가능, 기존 ADMIN 운영 하위호환 |
| 20 | registry_credit | GRANT/DEDUCT/RESET 원장 계산, RESET 이후만 유효, 입력 검증, 한도 0 하한, 이력·수행자 기록 |
| 21 | 결제 로그/Webhook | 3단계 기록·순서·연결, 소유권 격리, 민감정보 마스킹, `event_id` 멱등성 |
| 22 | 크롤러 식별키 | `auction`/`auction_item` 제약 고정, 두 법원 공존(롤백 검증) |
| 23 | FK 런타임 강제 | 기본 커넥션 `ON`, 고아 INSERT 차단, 마이그레이션 커넥션은 `OFF` |
| 24 | Payment 상태머신 | 허용/금지 전이, 레거시 `SUCCESS` 환불 가능, 종결 상태, 알 수 없는 상태 거부 |
| 25 | Subscription Lifecycle | 전이 규칙, 자동 만료(정상/유예/만료), **이용권 게이트 6종**(active/grace/expired/paused/cancelled/none), 유예 중 플랜 한도 유지, 갱신, 해지 불가역 |
| 26 | audit / credit 로그 | 감사 로그 기록·필터·before/after, credit 변동 로그·balance_after·actor, **사용(USAGE) 로깅 + 한도 이중차감 없음** |
| 27 | Admin REST 구조 | 기존 경로 유지 + 새 경로 동일 결과, meta.total, 권한 게이트, 구독 전이 400/404 |
| 28 | Soft Delete 컬럼 | `deleted_at`/`deleted_by` 존재, 기존 DELETE 동작 무변경 |

---

## 1-1. 테스트 Audit — "통과"가 아니라 "잡아내는가"

테스트가 전부 통과했다는 사실만으로는 그 테스트가 무언가를 지키고 있다는 증거가 되지 않는다.
일부러 코드를 망가뜨렸을 때 실패해야 비로소 의미가 있다.

2026-08-07 변이(mutation) 검증: 8가지 결함을 주입 → **8/8 전부 검출**.
그 과정에서 실제 테스트 공백 1건을 발견해 보강했다(이용권 게이트가 DB에 `GRACE_PERIOD`로
저장된 행을 한 번도 쓰지 않아, 조회 조건에서 그 상태를 빼먹어도 통과했다).

새 회귀 테스트를 추가할 때는 **그 테스트가 실패하는 것을 한 번 확인**하고 커밋한다
(해당 코드를 잠깐 망가뜨려 보는 것으로 충분하다).

---

## 2. 품질 게이트 (변경 시 매번)

```bash
npx tsc --noEmit    # Type Check — 통과해야 함
npx eslint .        # Lint — 2026-08-07 기준 0 오류
npm run build       # Next.js 빌드 — 통과해야 함
```

---

## 3. 수동 확인이 필요한 영역 (자동화 미적용)

자동 테스트로 덮이지 않는 부분. 회귀 위험이 있는 변경에서만 수행한다
(`docs/APPROVAL_POLICY.md`: 코드 분석 → 로그 → 서버 → API → **마지막에** 브라우저 QA).

- 회원가입 / 로그인 / 로그아웃 — Supabase Auth 실계정이 필요해 자동화하지 않는다.
  로그아웃 버튼은 현재 `/properties` 화면에만 있다(`docs/BUGS.md` #15)
- 등기부 다운로드 — 실제 파일을 `registry_documents/`에 두고 Admin으로 `doc_url`을 연결한 뒤
  브라우저에서 저장되는지 확인(백엔드 응답까지는 9~11번이 검증)
- 크롤링 파이프라인(`mvp_scraper.py` → `migrate_execute.py`) — courtauction.go.kr에 실제
  요청을 보내므로 회귀 테스트에서 실행하지 않는다

### 실행할 수 없는 테스트 (환경 제약)

- `test_db.py`, `test_docs*.py`, `test_normalizer.py` 등 크롤러를 import하는 스크립트는
  이 환경에 **selenium이 설치되어 있지 않아** `ModuleNotFoundError`로 즉시 실패한다.
  코드 문제가 아니라 의존성 미설치이며, 패키지 설치는 승인 필요 작업이라 Skip 상태다
  (`docs/CLAUDE.md`: `requirements.txt` 없음, 설치 전 승인 필요).
  위 자동 회귀 2종은 selenium을 쓰지 않으므로 영향 없다.

---

## 4. 테스트하지 않는 것 (기능 자체가 없음)

이전 버전 문서가 "완료"로 표시했던 항목의 실제 상태다.

- **이미지**: 물건 사진/이미지 기능이 코드에 존재하지 않는다
- **권리분석**: `src/app/properties/[id]/rightsAnalysis.ts`는 REGISTRY 소스를
  `available:false`로 하드코딩한 스텁이다. 등기부 파싱 테이블/파이프라인 자체가 없다
  (`docs/roadmap.md` "In Progress > Frontend" 참고)
- **Admin 화면**: Admin은 API만 있고 UI가 없다
