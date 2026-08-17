# Sprint 154 — 로그인 사용자면 누구나 만들 수 있는 500이 8곳 더 있었다

작성 2026-08-17. 모든 수치는 실행 결과다.

공유 문서(`docs/BUGS.md`, `CHANGELOG.md`, `CURRENT_STATE.md`, `roadmap.md`,
`TEST_PLAN.md`)는 다른 세션이 동시에 편집 중이라 건드리지 않았다.

---

## 1. 세 번 연속 "빠뜨린 파일"에서 같은 결함이 나왔다

```
Sprint 144   search / item / documents / images 를 고쳤다      <- 4개 파일만
Sprint 153   admin.py 가 빠져 있었다                            6개 핸들러 500
Sprint 154   favorites / registry / search_presets / payments   8곳 500
```

매번 "고쳤다"고 적혔지만 매번 남아 있었다. **원인은 방법이다** — 사람이 파일을
나열해서 고치면 나열에서 빠진 것을 영원히 못 본다.

## 2. 내 첫 스윕은 "5xx 0건"이라는 거짓 신호를 줬다

Sprint 153에서 무인증으로 전 라우트를 두드리고 admin 외에는 깨끗하다고 봤다.
**그 0건은 틀렸다.**

```
무인증으로 GET /api/v1/payments/{2^63}   ->  401   (쿼리에 닿지도 못함)
사용자 토큰으로 같은 요청                 ->  500   ← 여기 있었다
```

경계 검사는 **인증 뒤**에 있다. 그러므로 인증을 통과한 상태로 두드려야만 보인다.
`> 정정: Sprint 153 문서의 "무인증 GET 퍼징 154회 -> 5xx 0건"은 사용자 라우트에 대해서는
근거가 되지 못한다. 401이 쿼리를 가린 결과였다.`

## 3. 실측 — 관리자 권한이 **필요 없는** 500 8곳

`auction.db` 사본을 임시 디렉터리에 두고(POST는 쓰기 경로다) 합성 토큰으로 측정했다.

| 경로 | 종류 | 2^63 | 정상 id |
|---|---|---|---|
| `POST /api/v1/favorites` | 본문 `item_id` | **500** | 404 |
| `POST /api/v1/registry-requests` | 본문 `item_id` | **500** | 404 |
| `DELETE /api/v1/favorites/{item_id}` | 경로변수 | **500** | 200(없음 봉투) |
| `DELETE /api/v1/search-presets/{preset_id}` | 경로변수 | **500** | 200(없음 봉투) |
| `GET /api/v1/registry-requests/{request_id}` | 경로변수 | **500** | 404 |
| `GET /api/v1/registry-requests/{request_id}/download` | 경로변수 | **500** | 404 |
| `GET /api/v1/payments/{payment_id}` | 경로변수 | **500** | 404 |
| `GET /api/v1/payments/{payment_id}/logs` | 경로변수 | **500** | 404 |

원인은 Sprint 144·153과 동일하다.

```
OverflowError: Python int too large to convert to SQLite INTEGER
```

**Sprint 153의 admin 6곳보다 심각도가 높다** — Admin 키가 필요 없고, 로그인만 하면 된다.
본문 필드(`item_id`)로도 들어간다는 점에서 경로변수만 막아서는 부족했다.

## 4. 수정 — 4개 파일

각 핸들러가 이미 쓰는 "없음" 응답을 그대로 재사용했다. 새 상태코드를 만들지 않았다.

```
api/v1/favorites.py       get_item_summary() 안에서 None 반환(호출부의 404 경로를 탄다)
                          remove_favorite()  rowcount=0 과 같은 error_response
api/v1/registry.py        create_registry_request() / get_registry_request()
                          / download_registry()  -> 각자의 404
api/v1/search_presets.py  delete_preset()  rowcount=0 과 같은 error_response
api/v1/payments.py        get_payment() / get_payment_log_history() -> 404
```

**설계 판단**: `get_item_summary()`는 "없으면 None"이 계약이므로 범위 밖도 None으로
돌려준다 — 호출부를 고치지 않아도 되고, 앞으로 이 함수를 쓰는 코드도 자동으로 보호된다.
반면 삭제 계열은 `rowcount=0`과 **구별할 이유가 없으므로** 같은 봉투를 준다.

**경계값**: `is_sqlite_int`는 순수 범위 검사라 `-1`/`0`/`2^63-1`은 그대로 통과해
조회까지 간다. 기존 동작이 바뀌지 않는다(회귀 3번이 고정).

### 수정 후

```
경로변수 퍼징(사용자+관리자)  104회 -> 5xx 0건
본문 item_id 퍼징              10회 -> 5xx 0건
대조(범위 안 미존재)  favorites=404  registry=404  delete=200  payment=404   (수정 전과 동일)
```

## 5. 회귀 — `test_id_bounds_sweep.py` (신규)

**핸들러를 나열하지 않는다.** OpenAPI 스키마에서 라우트를 뽑아 경로변수를 범위 밖
정수로 채워 전부 두드린다. 새 라우트가 생기면 **이 파일을 고치지 않아도** 사정권에
들어온다. 이번 결함이 "나열에서 빠져서" 세 번 반복된 것이라 방법 자체를 바꿨다.

```
1. ★★ 전 라우트 스윕 39회 -> 5xx/예외 0건
2. 본문 item_id 경계 (favorites / registry-requests) -> 전부 404
3. 대조군 — 범위 안 동작 불변 + 경계값 2^63-1 통과(off-by-one 방지)
   + 삭제는 범위 밖과 범위 안의 상태코드가 같다
4. 응답에 OverflowError/Traceback/sqlite3/키/시크릿이 없다
```

`_headers_for()`에 **인증을 통과시키는 이유**를 주석으로 박아 두었다 — 이 함수를
지우거나 무인증으로 되돌리면 검사가 조용히 무력해지기 때문이다(내가 실제로 속았던 지점).

### Mutation — 5개 파일 각각에서 잡힌다

```
M1 favorites POST 가드 제거        exit=1 FAIL=6  잡힘
M2 favorites DELETE 가드 제거      exit=1 FAIL=2  잡힘
M3 registry POST 가드 제거         exit=1 FAIL=6  잡힘
M4 payments GET 가드 제거          exit=1 FAIL=1  잡힘
M5 search_presets DELETE 가드 제거 exit=1 FAIL=1  잡힘
전 파일 원본 복원 확인 OK
```

## 6. 운영 데이터 안전성

POST는 쓰기 경로라 `auction.db`를 **임시 사본**으로 갈아끼우고 두드렸다.
사후 확인:

```
운영 DB 에서 qa-body-fuzz-user / qa-user-sweep / qa-idsweep-user / qa-verify /
            qa-cause / jwks-probe-user 의 행 수
   favorites · recent_items · search_presets · registry_requests · payments  전부 0
```

Admin 키·JWT 시크릿은 합성값이며 프로세스 환경에만 넣었다. `.env`와 OS 환경은
변경하지 않았다.

## 7. 검증 결과

```
파이썬 전체   통과 35 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,318건, 39.0s)
              실패 1건은 test_schema_hygiene.py — 이 변경과 무관
프런트엔드    tests 111 / pass 111 / fail 0, exit 0
tsc 0   eslint 0   compileall 0
```

## 8. 변경 파일

```
수정   api/v1/favorites.py        가드 2곳 (+ is_sqlite_int import)
수정   api/v1/registry.py         가드 3곳 (+ import)
수정   api/v1/search_presets.py   가드 1곳 (+ import)
수정   api/v1/payments.py         가드 2곳 (+ import)
신규   test_id_bounds_sweep.py    4그룹, 라우트 자동 발견
신규   docs/SPRINT154_ID_BOUNDS_SWEEP.md
```

## 9. 남긴 것

- **POST/PATCH 본문의 `item_id` 외 필드**는 340회 퍼징에서 5xx가 나오지 않았다
  (Pydantic이 타입을 먼저 막는다). `item_id` 계열만 int로 선언돼 통과했다.
- **웹훅 경로**(`POST /payments/webhook/{provider_name}`)는 문자열 파라미터라
  이 계열이 아니다. 별도 감사 대상.
- `api/v1/admin.py`의 rollback·409 동시성 분기는 여전히 미커버(Sprint 153 §8과 동일).

---

# Sprint 155 — 세 번째 입력면: 쿼리 파라미터에서 10곳 더

경로변수와 본문을 막고 나서 **쿼리 파라미터**를 훑었다. 같은 계열이 10곳 더 있었다.

## 실측 (수정 전)

```
쿼리 파라미터 퍼징: 파라미터 61개, 요청 915회 -> 5xx 23건 (고유 라우트×파라미터 10개)

/api/v1/admin/registry-requests   page, item_id
/api/v1/admin/registry/requests   page, item_id
/api/v1/admin/users               page
/api/v1/admin/payments            page
/api/v1/admin/payments/webhooks   page, payment_id
/api/v1/admin/subscriptions       page
/api/v1/admin/audit-logs          page
```

`page`에는 `Query(1, ge=1)`로 **하한만** 있고 상한이 없었다. `(page-1)*size`가
그대로 OFFSET으로 내려가 sqlite3이 터진다.

```
GET /api/v1/admin/users?page=9223372036854775808  ->  500
```

## 수정 — 한 곳에서 막는다

목록 6곳이 이미 `_offset(page, size)` 헬퍼를 쓰고 있었다. **그 헬퍼 안에서** 검사하면
모든 호출부가 자동으로 보호되고 새 목록 엔드포인트도 마찬가지다.

```python
def _offset(page: int, size: int) -> int:
    offset = (page - 1) * size
    if not is_sqlite_int(offset):
        raise HTTPException(status_code=400, detail="page 값이 허용 범위를 벗어났습니다")
    return offset
```

다만 `/admin/registry-requests` **한 곳만 직접 곱하고 있어 검사를 비켜 갔다** —
`_offset()`을 쓰도록 고쳤다. (헬퍼가 있는데 한 곳만 인라인으로 남아 있는 것이
정확히 이번 감사가 반복해 만난 모양이다.)

필터용으로는 `_require_sqlite_filter(value, name)`를 따로 뒀다.

### 왜 404가 아니라 400인가

`_require_sqlite_id()`(경로변수)와 상태 코드가 다르다.

```
경로변수  그 행을 **지목**한다        -> 범위 밖이면 404 "찾을 수 없다"
쿼리 필터 조회 **조건**이다           -> 범위 밖이면 400 "허용 범위를 벗어났습니다"
page      페이지네이션 **조건**이다   -> 400
```

`api/v1/search.py`가 min/max 필터에 대해 이미 쓰는 규약과 같다.

## 수정 후

```
쿼리 파라미터 재퍼징 915회 -> 5xx 0건

대조(정상 페이지네이션)
  /admin/users?page=1&size=5              200
  /admin/payments?page=2&size=10          200
  /admin/registry-requests?page=1&size=5  200
  /admin/payments/webhooks?page=1&size=5  200

범위 밖 page -> 400 {"detail":"page 값이 허용 범위를 벗어났습니다"}
```

## 회귀 — `test_id_bounds_sweep.py`에 3-B / 3-C 추가

여기도 라우트를 나열하지 않는다. OpenAPI에서 **쿼리 파라미터를 읽어** 전부 두드린다
(파라미터 61개 / 요청 488회). 3-C는 정상 페이지네이션이 그대로 도는지와
범위 밖 page가 400인지를 함께 고정한다 — 넓게 막다가 정상 조회를 깨뜨리지 않았음을
같은 파일에서 증명하기 위해서다.

### Mutation

```
M1 _offset 범위검사 제거                     exit=1 FAIL=3  잡힘
M2 _require_sqlite_filter 무력화             exit=1 FAIL=1  잡힘
M3 registry-requests 만 인라인 곱셈으로 되돌림  exit=1 FAIL=1  잡힘
원본 복원 확인 OK
```

M3이 중요하다 — **헬퍼는 멀쩡한데 한 곳만 비켜 가는** 모양을 잡는다. 이번 결함이
정확히 그것이었다.

## 세 입력면 정리 (Sprint 153~155)

| 입력면 | 발견 | 상태 |
|---|---|---|
| 경로변수 (admin) | 6곳 500 | Sprint 153 수정 |
| 경로변수 (사용자) + 본문 | 8곳 500 | Sprint 154 수정 |
| 쿼리 파라미터 | 10곳 500 | Sprint 155 수정 |
| 웹훅 `provider_name`(문자열) | 91회 퍼징 5xx 0건 | 결함 없음 — 서명 검증이 먼저 막는다 |

## 검증

```
파이썬 전체   통과 35 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,326건, 40.0s)
프런트엔드    exit 0 (111/111)
tsc 0   eslint 0
```

## 변경 파일 (Sprint 155분)

```
수정   api/v1/admin.py            _offset() 범위검사 + _require_sqlite_filter() 신설
                                  + 필터 가드 2곳 + 인라인 곱셈 1곳을 헬퍼로 교체
수정   test_id_bounds_sweep.py    3-B(쿼리 스윕) / 3-C(페이지네이션 회귀) 추가
```

## 아직 두드리지 않은 입력면

- **HTTP 헤더**(Range, Accept-Encoding, If-Match 등) — 다음 후보
- **POST/PATCH 본문의 문자열 필드 길이·인코딩** — 340회 퍼징에서 5xx는 없었으나
  Pydantic 타입 검증이 먼저 막은 것이라 별도 확인 가치가 있다
