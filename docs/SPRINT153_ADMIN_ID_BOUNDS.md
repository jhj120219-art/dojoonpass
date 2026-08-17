# Sprint 153 — Admin 경로 6곳이 범위 밖 id에 500을 낸다

작성 2026-08-17. 모든 수치는 실행 결과다.

공유 문서(`docs/BUGS.md`, `CHANGELOG.md`, `CURRENT_STATE.md`, `roadmap.md`,
`TEST_PLAN.md`)는 다른 세션이 동시에 편집 중이라 건드리지 않았다.

---

## 1. 어떻게 찾았나 — 전 라우트 적대적 입력 스윕

Sprint 152에서 JWT 500을 찾은 방식이 통했으므로, 같은 것을 **전수로** 했다.
OpenAPI 스키마에서 경로를 뽑아(38경로 42오퍼레이션) 경로변수를 적대값으로 채웠다.

```
1차 (무인증)  GET 경로변수 퍼징 143회 -> 5xx 41건
```

41건 전부 `/api/v1/admin/*` 였다. **여기서 멈추지 않고 원인을 확인했다** —
정상 id로도 같은 500이 났고 본문이 `{"detail":"관리자 키 미설정"}` 였다.
내 환경에 `ADMIN_API_KEY`가 없어서지 입력 처리 결함이 아니다.
**41건을 결함으로 보고하지 않았다.**

대신 그 사실이 알려 준 것이 있다 — **admin 경로는 지금까지 한 번도 퍼징된 적이 없다.**
합성 키를 프로세스 환경에 넣고 다시 돌렸다.

```
2차 (ADMIN 등급)       GET 퍼징 110회 -> 5xx 4건   ← 진짜 결함
3차 (SUPER_ADMIN 등급) POST/PATCH 포함 -> 5xx 3건 추가
4차 (status 검증 통과)  registry-requests -> 5xx 1건 추가
```

## 2. 결함 — Sprint 144가 놓친 파일 하나

```
GET /api/v1/admin/payments/9223372036854775808/logs
   -> OverflowError: Python int too large to convert to SQLite INTEGER
   -> 500 Internal Server Error        (정상 범위 id는 404)
```

파이썬 int는 임의 정밀도라 `2**63`이 그대로 쿼리까지 내려가고 sqlite3이 터진다.
Sprint 144가 `search`·`item`·`documents`·`images`에서 없앤 것과 **같은 계열**이다.

```
실측:  api/v1/admin.py                     is_sqlite_int 사용  0건   <- 빠져 있었다
       api/v1/{item,documents,images,search}.py            전부 사용 중
```

### 6개 핸들러 전부에서 재현 (수정 전)

| 핸들러 | 필요 등급 | 2^63 | 정상 id |
|---|---|---|---|
| `GET /admin/payments/{id}/logs` | ADMIN | **500** | 404 |
| `GET /admin/payments/webhooks/{id}` | ADMIN | **500** | 404 |
| `POST /admin/payments/webhooks/{id}/reprocess` | SUPER_ADMIN | **500** | 404 |
| `POST /admin/payments/{id}/refund` | SUPER_ADMIN | **500** | 404 |
| `PATCH /admin/subscriptions/{id}` | SUPER_ADMIN | **500** | 404 |
| `PATCH /admin/registry-requests/{id}` | ADMIN | **500** | 404 |

**앞의 둘만 바로 보였다.** 나머지 넷은 권한/검증 단계에 가려 있었다 —
넷 중 셋은 SUPER_ADMIN 검사에, 하나는 status 값 검증에 막혀 쿼리까지 가지 못했다.
등급을 올리고 `status=FAILED`로 통과시킨 뒤에야 드러났다.
**"403이 나온다"를 "안전하다"로 읽지 않은 것이 이 넷을 찾은 이유다.**

### 심각도

전부 Admin 키가 필요하므로 **무인증 공격은 아니다**(Sprint 152의 JWT 건과 다른 점).
문제는 운영자가 잘못된 id로 조회했을 때 "찾을 수 없다"가 아니라 **원인 없는 500**을
받는다는 것이다. 운영 도구에서 500은 장애로 오인되고, 이 저장소가 반복해 지켜 온
"실패했으면 왜인지 남긴다"에 어긋난다.

## 3. 수정

`_require_sqlite_id(value, not_found_detail)` 헬퍼 하나를 두고 6곳에서 부른다.

**왜 404인가** — 범위 밖 정수는 어떤 행도 될 수 없으므로 "찾을 수 없다"가 정확한
답이다. 400("잘못된 형식")이 아니다. 형식은 올바른 정수다. `api/v1/item.py` 등이
이미 같은 판단을 하고 있어 응답 규약도 일치한다.

**왜 첫 DB 접근 직전인가** — 앞단 검증(권한·status·doc_url)을 앞지르지 않기 위해서다.
가드를 함수 맨 앞에 두면 지금 400/403으로 **정확히 응답하고 있는** 요청의 상태 코드까지
바뀐다. 이 수정이 바꾸는 것은 **500이던 경로뿐**이다.

**경계값** — `is_sqlite_int`는 순수 범위 검사(`MIN <= v <= MAX`)라 `-1`/`0`/`2^63-1`은
그대로 통과해 조회까지 간다. 즉 기존 동작이 바뀌지 않는다(회귀 2번이 이를 고정).

### 수정 후 실측

```
2^63 / -2^63-1 / 2^200   6개 핸들러 전부 404 + 각자의 정확한 메시지
999999999 (범위 안)      6개 전부 404 (수정 전과 동일)
2^63-1 (경계)            404 — 가드에 걸리지 않고 조회까지 간다

전 라우트 재스윕
   무인증        GET 퍼징 154회 -> 5xx 0건
   SUPER_ADMIN   GET 퍼징 154회 -> 5xx 0건
```

## 4. 회귀 — `test_admin_id_bounds.py` (신규)

4개 그룹.

```
1. ★ 범위 밖 id 3종 × 6핸들러 -> 404 + 메시지 일치
2. 대조군 — 범위 안 미존재 id 는 원래대로 404 / 경계값 2^63-1 은 통과
3. 404 응답에 OverflowError·Traceback·sqlite3·Admin키가 없다
4. ★ 전수 스캔 — int 경로변수를 받는 **모든** 핸들러가 가드를 부른다
```

4번이 이 파일의 핵심이다. 목록으로 대상을 지정하는 검사는 **목록에서 빠진 새 핸들러를
영원히 못 본다** — 이번 결함이 정확히 그렇게 생겼다(Sprint 144가 4개 파일만 훑고
admin.py를 빠뜨렸다). `docs/BUGS.md`도 같은 교훈을 적어 두었다("목록이 아니라 전수
스캔으로 짜야 한다"). 그래서 소스를 파싱해 `@router` 데코레이터와 시그니처에서
int 경로변수 핸들러를 **직접 찾아내고**, 그 각각이 가드를 부르는지 확인한다.

```
      발견한 핸들러 6개:
        /admin/registry-requests/{request_id}          가드=있음
        /admin/payments/{payment_id}/logs              가드=있음
        /admin/payments/webhooks/{webhook_id}          가드=있음
        /admin/payments/webhooks/{webhook_id}/reprocess 가드=있음
        /admin/payments/{payment_id}/refund            가드=있음
        /admin/subscriptions/{subscription_id}         가드=있음
```

### Mutation — 검사가 비어 있지 않다

```
M1  refund 한 곳만 가드 제거     exit=1 FAIL=4    잡힘
      [FAIL] ★ POST /payments/{id}/refund [2^63]: 500 (expected 404)
M2  헬퍼를 무력화(항상 통과)      exit=1 FAIL=18   잡힘
M3  404 대신 400 을 던지게        exit=1 FAIL=18   잡힘
원본 복원 확인 OK
```

M1이 중요하다 — **한 곳만** 빠져도 잡힌다(4번 전수 스캔이 함께 걸린다).

## 5. 운영 데이터·credential 안전성

- Admin 키는 **합성값**을 프로세스 환경에만 넣었다. 운영 키를 읽지도 출력하지도 않았다.
- 존재하지 않는 id만 다루므로 **쓰기가 일어나지 않는다** — refund/reprocess/PATCH 전부
  조회 단계에서 404로 끝난다.
- `.env`나 OS 환경은 변경하지 않았다.

## 6. 검증 결과

```
파이썬 전체   통과 34 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,294건, 40.8s)
              실패 1건은 test_schema_hygiene.py — 이 변경과 무관
프런트엔드    tests 111 / pass 111 / fail 0, exit 0
tsc 0   eslint 0   compileall 0

커버리지: 추가한 가드 6줄(339/694/798/828/896/1021)과 헬퍼 전부 실행됨.
   admin.py 에 남은 미커버는 rollback·409 동시성 분기 등 **기존** 경로다.
   (95% 라는 수치는 5개 파일만 돌린 값이라 이전 전체 측정 96% 와 직접 비교하지 않는다)
```

## 7. 변경 파일

```
수정   api/v1/admin.py              is_sqlite_int import + _require_sqlite_id 헬퍼 + 호출 6곳
신규   test_admin_id_bounds.py      4그룹
신규   docs/SPRINT153_ADMIN_ID_BOUNDS.md
```

## 8. 남긴 것

- **admin.py 의 rollback/409 분기**는 여전히 미커버다. 실패 주입으로 도달할 수 있으나
  동시성 재현이 필요해 다음 작업으로 남긴다. Dead 아님 — 실제 도달 가능한 Live 경로다.
- **POST/PATCH 본문(body) 필드 퍼징**은 이번에 하지 않았다. 이번 스윕은 **경로변수**만
  다뤘다. 본문 필드도 같은 계열 결함이 있을 수 있어 다음 후보다.
