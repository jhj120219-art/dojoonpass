# Sprint 152 — 손상된 JWKS 키가 인증 없이 500을 만든다

작성 2026-08-17. 이 문서의 모든 수치는 실행 결과다.

공유 문서(`docs/BUGS.md`, `CHANGELOG.md`, `CURRENT_STATE.md`, `roadmap.md`,
`TEST_PLAN.md`)는 **다른 세션이 같은 시각에 편집 중이라 건드리지 않았다.**
(실측: 이 작업 시작 시점 기준 `CURRENT_STATE.md` 3.7분 전, `BUGS.md` 10.2분 전 수정)

---

## 1. 어떻게 찾았나 — 커버리지의 0회 실행 두 줄

커버리지를 전수 측정하니 `api/auth.py` 가 98% 였고, 빠진 것이 딱 두 줄이었다.

```
api\auth.py    91    2    98%    134-135
```

그 두 줄은 이 함수의 **핵심 방어**였다.

```python
    except JWTError:
        raise
    except JOSEError as exc:                                   # <- 134-135
        raise JWTError(f"토큰 검증 실패: {type(exc).__name__}") from exc
```

`decode_supabase_jwt()` 의 docstring 은 이렇게 약속한다:

> 검증에 실패하면 **항상 JWTError**를 던진다. 호출부가 인증 필수(401)와 선택적 인증
> (비로그인으로 강등)을 각자 판단할 수 있어야 하기 때문이다 — 여기서 HTTPException을
> 던지면 검색 같은 선택적 인증 API가 토큰 문제로 통째로 실패한다.

약속을 지키는 장치가 한 번도 실행된 적이 없다. **도달시켜 봤다.**

## 2. 도달시키니 방어가 새고 있었다

`jose` 는 키 파싱 단계에서 **JOSE 계열이 아닌** 예외를 던진다.

```
JWKS 캐시에 구조가 깨진 공개키 -> jwt.decode() -> ValueError
   "invalid literal for int() with base 16: ''"

ValueError 는 JOSEError 가 아니다  ->  정규화를 그냥 통과  ->  호출부로 전파
```

`except JOSEError` 는 "jose 가 던지는 것은 전부 JOSEError 자손"이라는 전제인데,
그 전제가 틀렸다.

### 실측 — 수정 전

`api.auth._jwks_keys` 에 합성 손상 키를 심고 TestClient 로 측정했다
(네트워크·실제 credential 미사용).

| 경로 | 인증 성격 | 수정 전 | 기대 |
|---|---|---|---|
| `GET /api/v1/search` | 선택적 | **500** | 200 (비로그인 강등) |
| `GET /api/v1/item/1` | 선택적 | **500** | 200 |
| `GET /api/v1/favorites` | 필수 | **500** | 401 |

즉 docstring 이 막겠다고 적어 둔 바로 그 실패가 실제로 일어난다.

## 3. 왜 심각한가 — `kid` 는 요청자가 고른다

공격자가 JWKS 내용을 바꿀 수는 없다. 그러나 토큰 헤더의 `kid` 로 **어느 키를 쓸지
지목**한다. 그러므로 실제 JWKS 에 jose 가 못 읽는 키가 하나라도 섞이면
(키 회전 중 미지원 `kty`, 부분 손상 응답 등) **그 kid 를 지목하는 것만으로
인증 없이 500** 을 만들 수 있다.

Sprint 144 가 `/api/v1/search` 에서 없앤 "인증 없이 만드는 500"(SQLite INTEGER
범위 밖 정수 -> OverflowError)과 **같은 계열**이다.

키가 멀쩡한 평시에는 재현되지 않는다. 그래서 더 위험하다 — 문제가 드러나는 시점이
하필 **키 회전 중**, 즉 가장 손대기 어려운 때다.

`_fetch_jwks_locked()` 는 `kid` 가 있는 항목을 그대로 캐시에 넣을 뿐 **키 구조를
검증하지 않는다.** 손상 키가 캐시에 들어오는 것을 막는 장치는 없다.

## 4. 수정 — 예외 계층에 기대지 않는다

```python
    except Exception as exc:
        logger.warning("토큰 검증 중 JOSE 계열 밖 예외(%s) ― 인증 실패로 처리",
                       type(exc).__name__)
        raise JWTError(f"토큰 검증 실패: {type(exc).__name__}") from exc
```

설계 판단 세 가지:

1. **왜 넓게 잡는가** — "검증 실패는 종류를 불문하고 JWTError 하나로"가 이 함수의
   계약이다. 계약을 예외 클래스 계층에 의존시키면 상위 라이브러리가 바뀔 때마다 깨진다.
   같은 함수 안 헤더 파싱(101행)이 **이미** `except Exception` 으로 같은 일을 하고
   있어 방식도 일관된다.
2. **왜 삼키지 않는가** — 넓게 잡으면 진짜 버그가 조용한 인증 실패로 묻힌다.
   그래서 `logger.warning` 으로 반드시 흔적을 남긴다.
3. **왜 타입만 남기는가** — 토큰·키·비밀값이 로그로 새면 안 된다.
   `_get_jwk()` 가 이미 쓰는 규칙(`type(exc).__name__` 만)을 그대로 따랐다.

### 실측 — 수정 후

| 경로 | 수정 전 | 수정 후 |
|---|---|---|
| `/api/v1/search` (선택적) | 500 | **200** |
| `/api/v1/item/1` (선택적) | 500 | **200**, `is_favorited=false` |
| `/api/v1/favorites` (필수) | 500 | **401** `{"detail":"토큰 검증 실패"}` |

손상 키 5가지 형태 전부에서 동일하다. 그중 `값이 None` 형태는 `ValueError` 가 아니라
**`TypeError`** 를 낸다 — 특정 예외 타입만 막는 수정으로는 부족했다는 증거다.

## 5. 회귀 — `test_auth_jwks_robustness.py` (신규)

7개 그룹 45단언.

```
1. 손상 JWK 5형태 -> 전부 JWTError 로 정규화
2. ★ 선택적 인증 라우트(/search, /item) -> 200 + is_favorited=false
3. ★ 인증 필수 라우트(/favorites) -> 401
4. 응답에 Traceback/site-packages/소스경로/시크릿이 없다
5. 로그에 예외 타입은 남고 시크릿·키 값은 없다
6. 정상 HS256 토큰은 그대로 동작 + alg:none 은 여전히 거부
7. 배선 고정 — 소스에 넓은 정규화가 존재하고 JWTError 로 바꾼다
```

6번을 넣은 이유: 넓은 `except` 는 **너무 많이 잡을** 위험이 있다. 정상 토큰이 계속
통과하는지, 그리고 `alg:none` 위조가 여전히 거부되는지를 같은 파일에서 못 박았다.

### Mutation — 검사가 비어 있지 않다

```
M1  넓은 except 제거(수정 전으로 복귀)   exit=1  FAIL=15   잡힘
      [FAIL] ★ 16진수가 아닌 x -> JWTError: 'ValueError' (expected 'JWTError')
M2  JWTError 대신 RuntimeError            exit=1  FAIL=13   잡힘
      [FAIL] ★ 16진수가 아닌 x -> JWTError: 'RuntimeError' (expected 'JWTError')
원본 복원 확인 OK
```

## 6. 검증 결과

```
api/auth.py 커버리지     98% (미커버 134-135)  ->  100% (미커버 0)

파이썬 전체   통과 33 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,235건, 38.0s)
              실패 1건은 test_schema_hygiene.py — 이 변경과 무관(아래 8절)
프런트엔드    tests 111 / pass 111 / fail 0, exit 0
tsc           0
eslint        0
compileall    0
```

## 7. 곁가지로 확인한 것 — BUGS #94 의 "근본 문제"는 이미 해소돼 있다

Backlog 를 훑다가 #94(전액 환불한 구독이 그대로 살아 있다)를 봤다. 본문은 이렇게
적고 있다:

> **[더 근본적인 문제 ― 이건 정책이 아니다]** 고치려 해도 **대상을 찾을 수 없다.**
> 결제와 구독을 잇는 열쇠가 아예 없다. … `subscriptions` payment_id 없음

**실측하니 지금은 있다.**

```
storage/migrations/019_add_subscription_payment_id.sql   존재, 운영 DB에 적용됨
   PRAGMA table_info(subscriptions) -> payment_id 컬럼 확인

api/v1/payments.py:440  create_subscription(..., payment_id=payment_id)
                        결제와 같은 트랜잭션 -> 함께 커밋되거나 함께 사라진다

test_api_regression.py:1232  SELECT payment_id FROM subscriptions WHERE id=?
                             "구독이 자신을 산 결제를 가리킨다(BUGS #94)"
```

Mutation 으로 이 연결이 보호되는지도 확인했다 — `payment_id=payment_id` 인자를
떼어 내자 `exit=1`, `[FAIL] 구독이 자신을 산 결제를 가리킨다(BUGS #94): None
(expected 18430)`. **검사가 비어 있지 않다.**

> 따라서 #94 에 남은 것은 **정책 결정뿐**이다(전액 환불 시 즉시 해지 / 주기 만료 /
> 일할). "열쇠가 먼저 있어야 한다"는 전제 조건은 충족됐다. 정책은 승인 영역이라
> 손대지 않았고, `BUGS.md` 는 다른 세션이 편집 중이라 이 사실을 그쪽에 적지 않았다.
> **이 문단이 그 기록이다.**

갱신 경로(`renew()`)는 `payment_id` 를 새 결제로 갱신하지 않지만, 실측상
**프로덕션 호출부가 0곳**이다(`test_subscription_policy.py:360` 이 "배선되지 않은
준비 코드"라고 이미 기록). 지금 문제가 아니다.

## 8. 이 변경과 무관한 기존 실패

`test_schema_hygiene.py` 는 이번 작업 전부터 실패 중이며 원인 3가지 전부 이 변경과
무관하다.

```
storage/migrations/020_create_auction_image.sql 이 미추적
추적 파일 -> 미추적 파일 import 4건 (api/http_cache.py, api/v1/images.py 등)
unlock_retry.py 의 SQL 연결 허용목록 (다른 세션 진행 중)
```

전부 `git add`(스테이징)로 풀리지만 **커밋·푸시는 금지**이고, 공유 인덱스를 건드리면
동시 작업 중인 세션과 충돌하므로 하지 않았다.

## 9. 변경 파일

```
수정   api/auth.py                        JOSE 계열 밖 예외 정규화 (+주석)
신규   test_auth_jwks_robustness.py       7그룹 45단언
신규   docs/SPRINT152_AUTH_JWKS_ROBUSTNESS.md
```

프로덕션 코드 변경은 `api/auth.py` **한 곳**이다.

## 10. 남긴 과제 (승인 영역이라 하지 않음)

- **JWKS 키 구조 검증**: `_fetch_jwks_locked()` 가 손상 키를 캐시에 넣는 것 자체를
  막을 수 있다. 다만 "읽을 수 없는 키를 버린다"는 정책은 키 회전 중 **전원 로그아웃**
  위험과 맞닿아 있어(같은 함수의 기존 주석이 이미 그 위험을 경계한다) 임의로 정하지 않았다.
  지금 수정으로 **500 은 사라졌고 401/강등으로 안전하게 처리**되므로 급하지 않다.
