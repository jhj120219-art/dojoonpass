# Sprint 245 — 저장소 밖에서 서버를 띄우면 인증이 통째로 죽었다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(읽기 전용) / `.env` **무변경** / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이번 세션 실측

```
.env        142바이트 / BOM 없음 / LF
              SUPABASE_URL         len=0   ** 빈 값 **
              SUPABASE_ANON_KEY    len=0   ** 빈 값 **
              SUPABASE_JWT_SECRET  len=88  OK
.env.local  353바이트 / BOM 없음 / CRLF
              NEXT_PUBLIC_SUPABASE_URL       len=40
              NEXT_PUBLIC_SUPABASE_ANON_KEY  len=208
              NEXT_PUBLIC_API_BASE_URL       len=21

python  통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,596)
node    150개 중 146 PASS / 1 FAIL / 3 SKIP
tsc 0 / eslint 0
```

---

## 1. ★ `.env` 로딩이 **작업 디렉터리에 의존**하고 있었다 (P1, 수정 완료)

### 발견 — "파일에 있다"와 "앱이 읽는다"는 다른 사실이다

이번 목표가 못 박은 그 구분을 그대로 검사했더니 나왔다.
`api/auth.py` 와 `api_server.py` 는 이렇게 쓰고 있었다:

```python
load_dotenv()                              # <- cwd 기준
load_dotenv(".env.local", override=False)  # <- cwd 기준
```

`load_dotenv()` 는 **현재 작업 디렉터리**에서 `.env` 를 찾는다. 저장소 루트가 아닌 곳에서
서버를 띄우면 **환경변수를 하나도 못 읽는다.**

실측(2026-08-21, 같은 코드를 **별도 프로세스**로 cwd 만 바꿔 임포트):

```
cwd = 저장소 루트   JWT_SECRET 88자 / SUPABASE_URL 40자   -> 정상
cwd = 다른 폴더     JWT_SECRET  0자 / SUPABASE_URL  빈값
                    -> GET /api/v1/favorites 가 **500 "JWT 검증 설정 미비"**
```

### 왜 P1 인가 — 조용하고, 진단이 오래 걸린다

그 상태에서는 로그인 사용자의 **관심물건·최근본·검색조건·마이페이지·등기부가 전부 500** 이다.
비로그인 검색/상세만 살아 있어서 "대충 되는 것 같은데 로그인하면 깨진다"로 보인다.

게다가 오류 문구가 `"JWT 검증 설정 미비"` 라 **시크릿이 없는 줄 알고 `.env` 를 뒤지게 된다.**
진짜 원인은 작업 디렉터리다.

`.bat` 3개는 `cd /d %~dp0` 로 스스로를 보호하지만:

```
docs/CLAUDE.md 가 안내하는 실행법   uvicorn api_server:app --reload   <- 운영자의 아무 cwd
서비스 등록(NSSM/작업 스케줄러)      작업 디렉터리를 따로 준다
```

그리고 이 저장소는 **실제로 그 함정을 한 번 밟았다** — Sprint 241 에서 fixture API 를
다른 cwd 로 띄웠다가 인증이 전부 실패했고, 그때는 제품 결함이 아니라 측정 환경 문제로
정리하고 넘어갔다. 원인이 같다는 것을 이번에 확인했다.

### 고침 — 파일 기준 절대경로

```python
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
load_dotenv(os.path.join(_REPO_ROOT, ".env.local"), override=False)
```

`api_server.py` 도 같은 방식으로 바꿨다. **cwd 가 이미 저장소 루트면 동작은 완전히 동일하다.**
`.env` 파일 자체는 건드리지 않았다(승인 영역).

재측정:

```
cwd = 저장소 루트   JWT_SECRET 88자 / SUPABASE_URL 40자
cwd = 다른 폴더     JWT_SECRET 88자 / SUPABASE_URL 40자   <- 같아졌다
다른 cwd 에서 GET /api/v1/favorites -> **401**(정상, 토큰 없음) / 더 이상 500 아님
```

### 회귀 검사 + mutation

`test_auth_jwt.py` 에 신설. **별도 프로세스를 다른 cwd 에서 띄워** 확인한다 —
같은 프로세스 안에서는 이미 로드된 `os.environ` 이 남아 재현되지 않아 검사가 공허해진다.
상속된 환경변수도 지우고 띄운다.

```
MUT-E1 api/auth.py 를 인자 없는 load_dotenv() 로 되돌림   -> test_auth_jwt FAIL
MUT-E2 .env.local 을 상대경로 문자열로 되돌림             -> test_auth_jwt FAIL
MUT-E3 api_server.py 를 되돌림                           -> test_auth_jwt FAIL
```

소스 수준 가드(인자 없는 `load_dotenv()` / 상대경로 `.env` 금지)도 함께 넣어 편집 시점에도 잡는다.

---

## 2. `.env` 의 빈 두 값 — **동작은 정상이다**

```
SUPABASE_URL      = (빈 값)
SUPABASE_ANON_KEY = (빈 값)
```

그런데 인증은 멀쩡하다. `api/auth.py` 가 `SUPABASE_URL` 이 비면 `.env.local` 의
`NEXT_PUBLIC_SUPABASE_URL` 로 폴백하도록 이미 만들어져 있고, 런타임에서 그 값(40자)이
실제로 해석되는 것을 확인했다 — 즉 **JWKS/ES256 검증 경로가 살아 있다.**
`SUPABASE_ANON_KEY` 는 백엔드 코드 어디에서도 읽지 않는다(프런트는 `.env.local` 의
`NEXT_PUBLIC_*` 를 쓴다).

빈 두 줄은 오해를 부르지만 고장은 아니다. `.env` 수정은 승인 영역이라 두었다.

---

## 3. Admin API 상태 계약 — 16개 라우트 전수, **계약대로 동작한다**

프로세스 안에서만 테스트 키를 주입해(파일 무변경) 전수 확인했다.

```
메서드/경로 16개              키 없음   틀린 키   올바른 SUPER 키
                              403      403      200(8) / 404(4) / 422(4)
```

- 404 는 존재하지 않는 id(`webhook_id=1` 등)에 대한 정상 응답
- 422 는 본문이 필요한 POST/PATCH 에 빈 본문을 준 정상 응답
- **키 없음/틀린 키가 403 이 아닌 라우트: 0개**

`_require_role()` 의 계약도 코드로 확인했다:

```
두 키 모두 미설정   -> 500 "관리자 키 미설정"   (서버 설정 오류. 의도된 동작)
키 없음/불일치      -> 403
등급 부족           -> 403
```

키 비교는 `hmac.compare_digest` 로 **상수 시간**이고, 실패 로그에 **키 값을 남기지 않는다**
(`"키 미제공"` / `"키 불일치"` 만 기록).

즉 **admin 은 코드 결함이 없다.** 지금 500 이 나는 이유는 `.env` 에 두 키가 없기 때문이며,
이는 설정 문제이자 승인 영역이다. Sprint 244 의 등급 재분류 판단(베타 사용자 동선을
막지 않는 운영자 도구)이 코드 근거로도 확인됐다.

---

## 4. 인증 계약 전수 — 우회 없음

인증이 필요한 18개 라우트에 4가지 잘못된 토큰을 넣어 확인했다.

```
                          무토큰  깨진토큰  위조서명  sub없음
16개 라우트                401     401      401      401
/api/v1/item/{id}          200     200      200      200   <- 선택적 인증(공개 열람)
/api/v1/search             200     200      200      200   <- 선택적 인증(공개 검색)
```

선택적 인증 두 라우트가 **위조 토큰을 로그인으로 취급하지 않는지** 따로 확인했다:

```
토큰 없음   -> is_favorited=False
진짜 토큰   -> is_favorited=True
★ 위조 서명 -> is_favorited=False   (비로그인으로 취급 - 정상)
★ alg=none  -> jose 가 토큰 생성 자체를 거부
```

**인증 우회 가능성 0건.**

---

## 5. Dead code 감사

진입점(`api_server.py` / `mvp_scraper.py` / `doc_worker.py` / `migrate_execute.py` /
`refresh_priority.py` / `collect_documents.py`)에서 import 그래프를 BFS 했다.

```
제품 모듈 58개 / 도달 43개 / 도달 불가 5개
   filter.filter_engine / filter.report_generator / filter.scoring_engine   <- 진짜 dead
   storage.migrate_v4_1 / storage.migrations.run_migrations                 <- 오탐
```

뒤의 둘은 **수동 부트스트랩 스크립트**다(`python storage/migrate_v4_1.py`,
`python -m storage.migrations.run_migrations` — `docs/CLAUDE.md` 가 안내하는 3단계).
내 진입점 목록에 없었을 뿐이다. 도구 한계이지 결함이 아니다.

`filter/` 3개는 `docs/CLAUDE.md` 가 이미 dead 로 기록한 것과 일치한다.
**파일 삭제는 승인 영역**이라 하지 않았다.

---

## 6. 최종 상태

```
python run_python_tests.py   통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,596 -> **7,604**)
                             실패 1 = test_pipeline_integrity.py (기일 남은 물건 0건 가드)
node --test                  150개 / 146 PASS / 1 FAIL / 3 SKIP
tsc 0 / eslint 0
```

---

## 7. 승인으로 SKIP

```
1. 실크롤 재개 / 스케줄러 등록   <- 유일한 실질 P0 의 해소 수단
2. `.env` 수정
   - ADMIN_API_KEY / SUPER_ADMIN_API_KEY 추가 (없으면 admin 16개 라우트가 500)
   - 빈 SUPABASE_URL / SUPABASE_ANON_KEY 정리 (동작에는 지장 없음)
3. 운영 DB 변경 (COLLECTING 2,145행 등)
4. `filter/` 3개 모듈 삭제 (dead 확인됐으나 파일 삭제는 승인 영역)
5. 면적/특수조건 필터 처리 (Sprint 244 §3) / `document_status` "대상 아님" 상태 신설
6. 결제 실연동 / Supabase Redirect URL 확인
7. git add / commit / push
```

## 8. Release Blocker

```
[P0] 크롤 정지 -> 기일 남은 물건 0건 -> 기본 검색이 빈 화면 (승인 영역)
```

이번에 고친 `.env` cwd 의존은 **출시 후 배포 방식에 따라 인증 전체를 죽일 수 있던**
문제였고, 지금은 해소됐다.

## 9. 남은 Backlog / 다음 Sprint

```
A. 면적·특수조건 필터 (Sprint 244 §3) — 백엔드 구현 / UI 숨김 / 안내 중 제품 선택 필요
B. `document_status` "대상 아님" 상태 — 문서 2,145행 + 사진 1,867물건
C. `audit_viewport.py --cookie` 로 로그인 화면 24칸 실측
D. `audit_test_reality.py` 의 "60줄 미만" 3개 검사 mutation 판정
E. 크롤 재개 후 image 4종 실벽시계 처리량 재측정
F. `.env` 에 ADMIN 키가 없을 때 **부팅 시점에 경고**를 남길지 검토
   (지금은 첫 admin 호출까지 알 수 없다. 로그 한 줄이면 운영자가 즉시 안다)
```
