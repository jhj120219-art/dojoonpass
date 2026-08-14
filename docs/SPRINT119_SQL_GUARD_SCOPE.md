# Sprint 119 ― 내 SQL 가드가 세 번째 조립 형태를 통째로 놓쳤다 (2026-08-14)

> 앞 Sprint: `docs/SPRINT118_TIMEZONE_SCOPE.md`
>
> **별도 파일 이유**: Sprint 100~118과 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

같은 실패 모양을 네 번 고쳤으니(108/109/116/118) **남은 자리를 전수로 찾자**는 것이 출발점이었다.
찾다가 **내가 Sprint 107에 만든 가드가 가장 큰 구멍**을 갖고 있는 것을 발견했다.

---

## 1. 메타 감사 ― 손으로 적은 목록 29곳

검사 파일 전체를 AST로 훑어 "파일/경로 목록을 손으로 적은 자리"를 뽑았다. **29곳**이 나왔다.
대부분은 픽스처거나 의도적으로 작은 집합이다. 그중 **범위를 정하는** 목록만 실제와 대조했다.

거기서 두 개가 걸렸다 ― 둘 다 Sprint 107에서 **내가 적은 것**이다.

## 2. ★ `+` 연결 ― 세 번째 조립 형태를 아예 안 봤다

Sprint 107의 스캐너는 두 형태만 봤다.

```
f"SELECT ... WHERE {where}"        f-string
"SELECT ... WHERE %s" % where      %-포맷
```

**문자열 `+` 연결이 세 번째 형태였고, 스캐너에 그 분기가 없었다.**

```python
storage/database.py:291   "SELECT * FROM auction " + where + " ORDER BY ..."
storage/database.py:805   "UPDATE auction SET " + col + "=1 WHERE ..."
api/v1/admin.py:645       "SELECT COUNT(*) FROM payments WHERE " + where
api/v1/admin.py:742       "SELECT COUNT(*) FROM payment_webhooks WHERE " + where
api/v1/admin.py:942       "SELECT COUNT(*) FROM subscriptions WHERE " + where
```

즉 Sprint 107이 **"보간 지점 22곳"** 이라고 적은 인벤토리가 틀렸다.
`admin.py` 에는 내가 센 2곳 말고 **`where` 조립이 3곳 더** 있었고, 전부
요청으로 도달하는 관리자 목록 엔드포인트다.

### 다시 세어 전부 확인했다 ― 인젝션은 여전히 없다

- `admin.py` 세 곳: 조각이 전부 상수(`"status = ?"` 등)이고 값은 `?` 바인딩.
  게다가 `_validate_filter()` 가 enum 값을 먼저 화이트리스트로 거른다.
- `storage/database.py:805` 의 `col`: **3개 리터럴 dict 조회**이고 모르는 키는 `KeyError`
  로 막힌다(fail-closed). `doc_type` 도 큐에서 오지 결과 사용자 입력이 아니다.
- `filter/` 는 어디에도 배선되지 않은 죽은 코드다(docs/CLAUDE.md).

**Sprint 107의 결론(인젝션 없음)은 유지된다. 틀렸던 것은 인벤토리와 검사 범위다.**

### 고친 것

`_sql_text_interpolations()` 에 `+` 연결 분기를 넣고, 중첩된 `+` 를 평탄화해
**잎 피연산자**만 모은다. 그 목록을 `ALLOWED_SQL_CONCAT_OPERANDS` 로 고정했다(12쌍).

스캔 대상도 넓혔다 ― `api`/`storage` 만 보던 것을 `crawler`/`validator`/`normalizer`/
`filter` + 루트 스크립트까지. 그러자 CLI 백필/복구 스크립트 **9곳**이 더 드러났고
(전부 테이블명 리터럴 또는 `?` 반복 ― 안전), 그것도 함께 고정했다.

## 3. ★ `conditions.append` 파일 목록이 3개 (실제 5개)

```python
for rel in ("api/v1/search.py", "api/v1/admin.py", "api/v1/audit.py"):
```

실제로 `conditions.append` 를 쓰는 파일은 **5개**다 —
`storage/database.py` 와 `filter/filter_engine.py` 가 빠져 있었다.
Sprint 109·116·118과 **똑같은 모양**이라, 여기서도 코드에서 유도하게 바꿨다.

```
    conditions.append 사용 파일 5개: api/v1/admin.py, api/v1/audit.py,
                                     api/v1/search.py, filter/filter_engine.py,
                                     storage/database.py
[PASS] WHERE 조각을 모으는 파일을 실제로 찾았다
[PASS] WHERE 조각이 전부 상수
```

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M96 | `storage/database.py` 에 `"court_name = '" + court_name + "'"` (진짜 인젝션) | **검출 O** ― `database.py:278` |
| M97 | `filter/filter_engine.py` 의 조각을 상수 아니게 | **검출 O** ― `filter_engine.py:43` |

**두 파일 모두 이번 확장 전에는 가드의 범위 밖**이었다.
M96은 Sprint 107이 막으려던 바로 그 결함이고, 그때는 **그 자리에 심었어도 통과했을 것이다.**

원복 후 흔적 0건, 스위트 통과.

## 이 세션에서 다섯 번째 같은 실패

| Sprint | 좁았던 범위 | 실제 |
|---|---|---|
| 108 | 인가 전수가 `openapi()` 기반 | `include_in_schema=False` 라우트가 안 보임 |
| 109 | 소프트 삭제 "함께 고칠 곳" 3개 | 5개 |
| 116 | 종료코드 검사 진입점 2개 | 4개 |
| 118 | 시간대 검사 파일 약 75개 | 107개 |
| **119** | **SQL 조립 형태 2종 / 파일 3개** | **3종 / 5개** |

전부 **초록불인데 범위가 좁은** 상태였다. 공통 해법도 같다 ―
**목록을 손으로 적지 말고 코드에서 유도한다.**

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| `python -m compileall` | **exit 0** |
| 프런트 | 무변경 (Sprint 117에서 108/108, TSC/LINT/BUILD exit 0) |
| 실 DB | **한 줄도 쓰지 않았다** |
| 변이 잔여 | `storage/database.py` 에 M96 흔적 0건, `filter/` 무변경 |

## 수정 파일

```
test_schema_hygiene.py    + 연결 분기 신설 / 스캔 대상 확대 / conditions 파일 목록을 코드 유도
```

**제품 코드 변경 0건.**

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  `register_scheduler_tasks.ps1 -Apply` 한 줄이면 된다(Sprint 112).
- Sprint 105~118의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
