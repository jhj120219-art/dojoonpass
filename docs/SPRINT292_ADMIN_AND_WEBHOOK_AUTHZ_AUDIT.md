# Sprint 292 — Admin 권한 경계 · 결제 Webhook 서명 전수 감사 (2026-09-03)

> **운영 DB 무변경.** 모든 positive-path 검증은 **in-process 테스트 자격증명 + 사본 DB**
> 로만 했다. `.env` 를 읽지도 쓰지도 않았고, 실제 시크릿을 출력하지 않았다.
> 테스트 키는 프로세스 환경변수로만 존재하고 파일에 남지 않는다.

---

## 요약

| # | 무엇 | 종류 | 결과 |
|---|---|---|---|
| 1 | Admin 16 엔드포인트 **positive/negative 양방향** 권한 검증 | ★ 감사(신규) | 우회 0건. ADMIN→SUPER 상승 4건 전부 차단 |
| 2 | **인증된 일반 사용자**(유효 JWT)로 admin 접근 | ★ 감사(신규) | 16/16 거부. admin 주장 JWT 도 거부 |
| 3 | 헤더/쿼리/바디/경로 **우회 mutation 12종** | ★ 감사(신규) | 우회 0건 |
| 4 | 결제 Webhook 서명 검증 (공개 상태변경 경로) | ★ 감사(신규) | 8/8 정상. 위조·재전송·시크릿미설정 전부 차단 |
| 5 | 에러 응답 **누출** 14경로 | ★ 감사(신규) | 시크릿/경로/SQL/트레이스백 **0건** |
| 6 | `/docs`·`/openapi.json` 이 admin 16경로를 익명 공개 | ★ 발견(완화) | 배포용 토글 신설(기본값은 현행 유지) + 가드 |

---

## 1. 왜 "16/16 fail-closed" 만으로는 부족했나

직전 세션은 negative path(키 없음/틀린 키)만 봤다. 그것은 *"아무도 못 들어온다"* 는
말이지 *"권한 모델이 실제로 분리돼 있다"* 는 말이 아니다. 이번에는 **가짜 관리자
자격증명을 주입해 positive path 까지** 통과시켜 네 경계를 각각 확인했다.

```
UNAUTHENTICATED           -> DENY   (403)
NORMAL USER (유효 JWT)     -> DENY   (403)   ← 이번에 처음 검증
INVALID ADMIN KEY         -> DENY   (403)
VALID TEST ADMIN          -> 허용돼야 하는 것만 ALLOW
```

---

## 2. 엔드포인트별 권한·DB 접근 표 (코드에서 기계 추출)

전체 49개 엔드포인트 중 권한별 분포: **ADMIN 12 · SUPER_ADMIN 4 · USER(JWT) 8 ·
PUBLIC 7 · OPTIONAL 1** (나머지는 추출기 미포착분으로 §7 참고).

| 엔드포인트 | 필요 등급 | RWD | 스코프 |
|---|---|---|---|
| `GET /admin/registry-requests` | ADMIN | R | user_id |
| `PATCH /admin/registry-requests/{id}` | ADMIN | R,U | — |
| `GET /admin/registry-credits/{user_id}` | ADMIN | R | user_id |
| `GET /admin/users` · `/admin/payments` · `/admin/subscriptions` | ADMIN | R | user_id |
| `GET /admin/payments/{id}/logs` · `/webhooks` · `/webhooks/{id}` | ADMIN | R | — |
| `GET /admin/audit-logs` · `/admin/registry/credit-logs/{user_id}` | ADMIN | R | — |
| **`POST /admin/registry-credits`** | **SUPER_ADMIN** | — | — |
| **`POST /admin/payments/webhooks/{id}/reprocess`** | **SUPER_ADMIN** | R | — |
| **`POST /admin/payments/{id}/refund`** | **SUPER_ADMIN** | R | — |
| **`PATCH /admin/subscriptions/{id}`** | **SUPER_ADMIN** | — | — |

**돈에 직접 영향을 주는 4개 조작이 정확히 상위 등급에 묶여 있다** — 크레딧 부여,
웹훅 재처리, 환불, 구독 변경. 설계 의도와 코드가 일치한다.

---

## 3. 권한 경계 실측

### (a) 키 기준 4조건 (사본 DB, in-process 테스트 키)

```
                          키없음  틀린키  ADMIN키  SUPER키
ADMIN 12개                 403    403    도달     도달
SUPER_ADMIN 4개            403    403    **403**  도달
```

`ADMIN` 키로 `POST /admin/payments/{id}/refund` → **403**
(`Admin 권한 부족: ADMIN 등급이 SUPER_ADMIN 전용 작업을 시도함` 로그 기록).

### (b) 인증된 일반 사용자 (이번에 처음)

유효한 HS256 JWT 를 발급해 admin 16개에 붙였다.

```
일반 사용자 JWT                                   16/16 -> 403
"admin 권한을 주장하는" JWT                        16/16 -> 403
  (role=service_role, is_admin=true, app_metadata.role=admin 을 전부 넣었다)
JWT + 틀린 X-Admin-Key                            16/16 -> 403
```

**JWT 클레임은 admin 권한의 근거가 아니다** — 등급은 `X-Admin-Key` 로만 결정된다.
그래서 토큰 위조로 관리자가 될 수 있는 경로가 구조적으로 없다.

### (c) 우회 mutation 12종 — 전부 403

```
키 앞뒤 공백 / 뒤 개행 / 접두(더 긺) / 접미(더 짧음) / 빈 키          403  (compare_digest, trim 없음)
쿼리스트링 ?X-Admin-Key= / ?admin_key=                              403
바디에 키 / Authorization 헤더에 키                                  403
경로 조작 /admin/../admin/users                                     403
```

> 헤더 이름 `X-ADMIN-KEY` / `x-admin-key` 에 **정상 키**를 넣으면 200 이다 —
> HTTP 표준상 헤더 이름은 대소문자를 가리지 않으므로 **이것이 올바른 동작**이다.
> (첫 판정에서 이것을 "우회 가능"으로 표시했는데, 내 기대표가 틀렸다. 정정한다.)

---

## 4. 결제 Webhook — 인증 없는 공개 상태변경 경로

`POST /api/v1/payments/webhook/{provider}` 는 사용자 인증이 없다. **서명이 유일한
방어선**이라 별도로 전수 검증했다(사본 DB, 테스트 시크릿).

```
① 서명 없음                    -> 401, payment_webhooks 행 +0
② 틀린 서명                    -> 401, 행 +0
③ 빈 서명                      -> 401, 행 +0
④ **다른 바디의 유효 서명**(변조) -> 401, 행 +0     ← 위조 차단
⑤ 올바른 HMAC                  -> 200, 행 +1
⑥ 재전송(같은 event_id)         -> 200 duplicate=true, 행 +0   ← 이중 적용 없음
⑦ 알 수 없는 provider           -> 404, 행 +0
⑧ 시크릿 미설정 + 올바른 서명     -> 401                        ← fail-closed
```

설계도 함께 확인했다.

- 서명 검증이 **파싱보다도, DB 쓰기보다도 앞**이다.
- `PaymentProvider.verify_webhook_signature` 기본 구현이 **`return False`** —
  새 PG 를 추가하며 구현을 잊으면 열리는 것이 아니라 **닫힌다.**
- 거절된 요청은 **행을 만들지 않는다** → 익명 저장소 증폭(DoS) 통로가 없다.
- `hmac.compare_digest` 상수시간 비교.

---

## 5. 에러 응답 누출 — 0건

14개 오류 경로(존재하지 않는 id, 범위 밖 정수, 잘못된 정렬키, 잘못된 토큰,
admin 미인증, webhook 미서명, 알 수 없는 문서종류, 404 …)의 본문을 정규식으로 훑었다.

```
절대경로(C:\ , /home/, /Users/)   0
트레이스백(Traceback, File "…")   0
SQL(SELECT/INSERT/sqlite3/no such table)   0
시크릿(SECRET/API_KEY/Bearer …/eyJ…)       0
내부 모듈명(api.v1., storage.database, uvicorn)  0
```

---

## 6. ★ 발견 — OpenAPI 문서가 admin 표면을 익명에게 공개한다

```
GET /openapi.json   200 (인증 없음)
   경로 42개 중 **/api/v1/admin/* 16개**가 요청/응답 스키마와 함께 실려 있다
GET /docs   200      GET /redoc  200
```

**완화 요인**: 이 서버는 `uvicorn.run(..., host="127.0.0.1")` 로 **로컬호스트에만**
바인딩한다. 그래서 오늘의 결함이 아니라 **배포 시점의 위험**이다 — 리버스 프록시
뒤로 올리는 순간 관리자 API 의 존재·경로·파라미터가 익명에게 공개된다.
인증을 뚫지는 못하지만(키는 여전히 필요하다) 공격 표면을 그대로 알려 준다.

### 고친 방식 — 기본값을 바꾸지 않는 스위치

`/docs` 는 `docs/CLAUDE.md` 가 개발 워크플로로 안내하는 자리다. 끌지 말지는
**배포 정책**이므로 임의로 정하지 않고 스위치만 만들었다.
`CORS_ALLOW_ORIGINS` 가 *"미설정이면 기존 `*`"* 로 들어온 것과 같은 방식이다.

```python
_docs_enabled = os.getenv("API_DOCS_ENABLED", "1").strip().lower() not in ("0","false","no")
app = FastAPI(..., docs_url=... if _docs_enabled else None, redoc_url=..., openapi_url=...)
```

```
미설정(기본)        /docs 200 · /redoc 200 · /openapi.json 200   ← 오늘 동작 그대로
API_DOCS_ENABLED=0  셋 다 404,  그리고 /api/v1/search 는 200      ← API 는 안 죽는다
```

`docs/ENVIRONMENT_VARIABLES.md` 에 항목을 추가했다 —
`test_bootstrap` §15("코드가 읽는 환경변수가 전부 문서에 있는가")가 이것을 요구하고,
추가 후 그 검사가 통과하는 것을 확인했다(코드가 읽는 환경변수 14개).

### 가드 + 변이

새 파일을 만들지 않고 **기존** `test_public_endpoint_exposure.py` 에 넣었다
(이 파일의 주제가 정확히 "공개 엔드포인트가 무엇을 내보내는가" 다).

```
[PASS] 기본값(미설정)에서 /docs · /redoc · /openapi.json 이 열려 있다
[PASS] 열려 있을 때 admin 경로가 스펙에 실린다(검사가 공허하지 않다)
[PASS] API_DOCS_ENABLED=0 에서 셋 다 닫힌다
[PASS] 문서를 꺼도 API 는 그대로 동작한다

변이: api_server.py 에서 토글 3줄 제거
  -> [FAIL] ×3 ("API_DOCS_ENABLED=0 에서 … 닫힌다" 전부 200)
  원복 후 8/8 통과
```

---

## 7. 이 감사가 **판정하지 못한 것** (정직하게)

```
admin 응답의 필드 구성   이 개발 DB 는 users/payments/subscriptions 가 **0행**이라
                        실제 응답 본문을 볼 수 없었다(200 이지만 rows=0).
                        민감정보 범위 판정은 데이터가 있는 머신에서 해야 한다.
엔드포인트 추출          AST 추출기가 49개 중 32개만 잡았다(favorites/recent_items/
                        search_presets/registry/item/doc_stats 등 17개 미포착).
                        미포착분은 이전 세션에서 개별 확인했으나(IDOR·인증 경계),
                        **한 표로 통합된 인벤토리는 아직 없다.**
KGInicis 실연동          6개 메서드 전부 NotImplementedError 상속 — 호출되면 조용히
                        성공하지 않고 명확히 실패한다. 실연동은 승인 대기.
```

---

## 8. 게이트

```
tsc 0 · eslint 0
node    329건 / 325 pass / 0 fail / 4 skip
python  test_public_endpoint_exposure  모두 통과(신규 8검사 포함)
        test_bootstrap §15 환경변수 문서화  PASS
        test_api_regression  ALL PASSED
        전체: 통과 64 | 실패 4 | 건너뜀 3 | 판정없음 1  (실패 4 = migration 뿐)
운영 DB  무변경 (모든 실험은 사본 + in-process 자격증명)
```

---

## 9. 승인/후속

```
B~H  기존 승인 항목 변화 없음 (migration / load_spec_data / 썸네일 / 위험등급 /
     날짜표기 / filed_date / 부천시 구 보정)
I    [운영 배포 시 결정] API_DOCS_ENABLED=0 을 켤 것인가 — 스위치는 만들어 뒀다.
     기본값은 현행 유지이므로 지금 아무 조치도 필요 없다.
J    [데이터 있는 머신에서] admin 읽기 응답의 민감정보 범위 판정(§7)
```
