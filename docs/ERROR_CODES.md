# Error Code 표준 (도메인별)

Status: Active
Last Updated: 2026-08-07 (Sprint 28)
Owner: CTO

정의 위치: `api/constants.py:ErrorCode` — **이 문서가 아니라 코드가 기준**이다.

---

## 왜 코드로 분기해야 하는가

응답의 `message`는 한국어 문구이고 언제든 바뀐다. 클라이언트가 문구를 비교해 분기하면
문구를 다듬는 순간 조용히 깨진다. `error` 필드의 **코드**로 분기해야 한다.

```jsonc
{
  "success": false,
  "data": null,
  "error": "PAY_AMOUNT_MISMATCH",   // ← 클라이언트는 이걸 본다
  "meta": null,
  "message": "결제 금액이 올바르지 않습니다 (198000원)"  // ← 사용자에게 보여줄 문구
}
```

`message`는 **하위호환을 위해 유지**한다 — 프론트가 이미 `result.message`를 읽고 있어
제거하면 Breaking Change다(`docs/decision-log.md` "기존 API 유지").

---

## 형식

`<DOMAIN>_<SNAKE_CASE>`

| 접두사 | 담당 영역 |
|---|---|
| `AUTH` | 인증 (`api/auth.py`) |
| `PAY` | 결제 (`api/v1/payments.py`) |
| `SEARCH` | 검색·검색조건 저장 (`api/v1/search.py`, `search_presets.py`) |
| `REGISTRY` | 등기부 신청·무료횟수 (`api/v1/registry.py`, `registry_credits.py`) |
| `ADMIN` | 관리자 (`api/v1/admin.py`) |
| `SUBSCRIPTION` | 구독 (`api/v1/subscriptions.py`) |
| `FAVORITE` | 관심물건 (`api/v1/favorites.py`) |
| `ITEM` / `INTERNAL` | 물건 공통 / 서버 내부 |

---

## 코드 목록

### AUTH
| 코드 | 의미 |
|---|---|
| `AUTH_TOKEN_MISSING` | Authorization 헤더 없음 |
| `AUTH_TOKEN_INVALID` | 토큰 검증 실패 / `sub` 없음 |
| `AUTH_SECRET_NOT_CONFIGURED` | `SUPABASE_JWT_SECRET` 미설정(서버 설정 문제) |

### PAY
| 코드 | 의미 |
|---|---|
| `PAY_INVALID_TYPE` | 지원하지 않는 `payment_type` |
| `PAY_INVALID_PLAN` | 알 수 없는 플랜 |
| `PAY_INVALID_BILLING_CYCLE` | 알 수 없는 결제주기 |
| `PAY_AMOUNT_MISMATCH` | 요청 금액이 서버 계산 금액과 다름 |
| `PAY_NO_TARGET_REQUEST` | 초과결제 대상 등기부 신청이 없음 |
| `PAY_ALREADY_PROCESSED` | 이미 결제 처리된 신청(동시 결제 레이스) |
| `PAY_FAILED` | PG가 승인을 거절함 |
| `PAY_NOT_FOUND` | 결제 내역 없음 |
| `PAY_INVALID_TRANSITION` | 허용되지 않은 결제 상태 전이 |

### SEARCH
| 코드 | 의미 |
|---|---|
| `SEARCH_INVALID_SORT` | 화이트리스트에 없는 `sort_by`/`sort_order` |
| `SEARCH_FAILED` | 검색 처리 중 서버 오류 |
| `SEARCH_PRESET_NAME_REQUIRED` | 검색조건 이름 공백 |
| `SEARCH_PRESET_NAME_TOO_LONG` | 이름 100자 초과 |
| `SEARCH_PRESET_TOO_LARGE` | 조건 JSON 4000자 초과 |
| `SEARCH_PRESET_LIMIT_EXCEEDED` | 사용자당 100개 초과 |
| `SEARCH_PRESET_NOT_FOUND` | 검색조건 없음(또는 타인 소유) |

### REGISTRY
| 코드 | 의미 |
|---|---|
| `REGISTRY_ITEM_NOT_FOUND` | 물건 없음 |
| `REGISTRY_SUBSCRIPTION_REQUIRED` | 구독이 없어 신청 불가 |
| `REGISTRY_REQUEST_NOT_FOUND` | 신청 없음(또는 타인 소유) |
| `REGISTRY_NOT_COMPLETED` | 아직 발급 완료 상태가 아님 |
| `REGISTRY_DOCUMENT_NOT_FOUND` | `doc_url` 없음 또는 파일 없음 |
| `REGISTRY_INVALID_TRANSITION` | 허용되지 않은 신청 상태 전이 |
| `REGISTRY_CREDIT_INVALID_AMOUNT` | 조정 수량이 1~100 범위 밖 |
| `REGISTRY_CREDIT_INVALID_REASON` | 알 수 없는 조정 유형 |

### ADMIN
| 코드 | 의미 |
|---|---|
| `ADMIN_KEY_NOT_CONFIGURED` | `ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY` 둘 다 미설정 |
| `ADMIN_FORBIDDEN` | 키 불일치/미제공 |
| `ADMIN_INSUFFICIENT_ROLE` | ADMIN이 SUPER_ADMIN 전용 작업 시도 |
| `ADMIN_INVALID_STATUS` | 허용되지 않는 상태 값 |
| `ADMIN_TARGET_NOT_FOUND` | 대상 없음 |
| `ADMIN_INVALID_PARAMETER` | 잘못된 파라미터 |

### SUBSCRIPTION
| 코드 | 의미 |
|---|---|
| `SUBSCRIPTION_NOT_FOUND` | 구독 없음 |
| `SUBSCRIPTION_INVALID_TRANSITION` | 허용되지 않은 구독 상태 전이 |
| `SUBSCRIPTION_ALREADY_CANCELLED` | 이미 해지됨(되돌릴 수 없음) |

### FAVORITE / 공통
| 코드 | 의미 |
|---|---|
| `FAVORITE_ALREADY_EXISTS` | 이미 관심물건으로 등록됨 |
| `FAVORITE_NOT_FOUND` | 등록된 관심물건 없음 |
| `ITEM_NOT_FOUND` | 물건 없음 |
| `INTERNAL_ERROR` | 분류되지 않은 서버 오류 |

---

## 적용 현황 (2026-08-07)

**Error Code가 붙은 곳** — envelope(`{success, data, error, meta, message}`)를 쓰는 라우트:
`payments` / `registry` / `favorites` / `search_presets`.

**아직 붙지 않은 곳** — `HTTPException`으로 실패를 반환하는 지점(FastAPI 표준 `{"detail": ...}`).
`admin` 전체와 각 라우트의 404/400이 여기 해당한다. **의도적으로 두었다**: 기존 클라이언트가
`status_code`로 분기하고 있어 envelope로 바꾸면 Breaking Change이며, 이는 Spec 결정 사항이라
이번 범위에서 Skip했다(`docs/BETA_RELEASE_CHECKLIST.md` 참고).

전환하려면 FastAPI `exception_handler`로 `HTTPException`을 envelope로 감싸는 방식이 가장
작은 변경이지만, 응답 형태가 바뀌므로 프론트 동시 수정이 필요하다.

---

## 추가 규칙

1. 새 실패 경로를 만들면 **먼저 `api/constants.py:ErrorCode`에 코드를 추가**하고 이 문서를 갱신한다
2. `api.auth.error_response(code, message)`를 쓴다 — `fail(message)`는 코드 없는 레거시 경로다
3. 코드 값은 한 번 배포되면 바꾸지 않는다(클라이언트가 분기 기준으로 쓰므로).
   의미가 바뀌면 새 코드를 만든다
4. 회귀 테스트 17번이 "실패 응답에 error 코드가 붙는지"를 검증한다
