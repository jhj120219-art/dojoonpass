# Sprint 104 — "문서가 있다"의 정의를 한 곳으로 (2026-08-14)

> 앞 Sprint: `docs/SPRINT103_NORMALIZER_DRIFT.md`
>
> **별도 파일 이유**: Sprint 100~103과 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Sprint 103이 "계산해서 저장한 값"의 드리프트를 봤다면, 이번에는
**같은 판정을 하는 코드가 저장소 안에 여러 벌 있고 서로 다른 기준을 쓰는 문제**를 봤다.

찾아보니 "이 문서가 있는가"를 판정하는 자리가 **5곳**이었고, 그중 **3곳이 느슨했다.**
그리고 그중 하나는 **돈이 걸린 경로**였다.

---

## #104-1 ★ 유료 등기부가 0바이트여도 HTTP 200으로 나간다

**심각도 높음** (사용자가 **돈을 내고 빈 파일**을 받는다)

### 재현

```
0바이트 등기부 파일  ->  GET /api/v1/registry-requests/{id}/download
                     ->  HTTP 200 / 0 bytes          ★
대조군(16바이트)      ->  HTTP 200 / 16 bytes
```

### 원인 — 같은 결함을 이미 한 번 고쳤는데, 유료 경로만 빠졌다

`api/v1/documents.py`(무료 법원문서)는 **Sprint 98에 이미 이것을 막았다.**
당시 주석이 이유까지 적어 두었다.

> 쓰는 쪽은 이미 크기를 본다 — `crawler/doc_paths.doc_exists()`는
> `exists() and getsize() > 0`이라야 "수집됨"으로 친다. 읽는 쪽만 기준이 느슨해서
> **크롤러는 "아직 없음"이라 재수집 대상으로 보는 파일을 API는 "있음"이라고 답하는**
> 비대칭이 있었다.

그런데 `api/v1/registry.py`는 `os.path.exists()`만 보고 있었다.
**같은 저장소, 같은 결함, 같은 Sprint에 고칠 수 있었던 것이 유료 경로에만 남았다.**

`exists()`는 **디렉터리에도 True**라 두 번째 문제도 있었다 — 그 경우 `FileResponse`가
터져 404가 아니라 **500**이 된다.

### 수정

```python
# api/v1/registry.py
if not os.path.isfile(real_file_path) or os.path.getsize(real_file_path) == 0:
    raise HTTPException(status_code=404, ...)
```

기준은 새로 만들지 않았다 — 이 저장소가 이미 합의해 둔 `doc_exists()`를 따랐다.

---

## #104-2 ★★ 그 수정이 **내가 만든 새 간극**을 낳았다 (같은 Sprint에서 발견·수정)

`api/v1/admin.py:_require_existing_registry_document()`의 docstring은 이렇게 약속한다.

> 검사 방식은 다운로드 경로(`api/v1/registry.py:download_registry()`)와 **똑같이** 맞춘다.
> 두 곳이 다른 기준을 쓰면 "등록은 됐는데 못 받는" 상태가 다시 생긴다.

그런데 **그 약속을 강제하는 것이 아무것도 없었다.** 실제 코드는 `isfile()`만 봤다.

즉 #104-1에서 **다운로드만 조인 순간**, 이렇게 됐다.

```
admin: 0바이트 파일을 COMPLETED 로 허용     (isfile 만 봄)
사용자: 다운로드 404                        (getsize 까지 봄)
        = "발급 완료"인데 받을 수 없다
```

**Sprint 95가 없앤 바로 그 상태**(BUGS #93)를 내가 반대 방향으로 되살릴 뻔했다.

### 수정 — 쓰는 쪽도 같은 정의로

```python
# api/v1/admin.py
if not os.path.isfile(real_path) or os.path.getsize(real_path) == 0:
    raise HTTPException(400, "해당 문서 파일이 없거나 비어 있습니다: ...")
```

0바이트를 **연결하는 순간** 운영자가 알게 된다 — 사용자가 404를 만나고 나서가 아니라.

### 쓰기 쪽 동작 실측

| 입력 | 결과 |
|---|---|
| 내용 있는 파일 (대조군) | **통과** |
| 0바이트 파일 | **차단 400** |
| 디렉터리 | **차단 400** |
| 존재하지 않는 파일 | **차단 400** |
| 경로 탈출 (`../auction.db`) | **차단 400** |

---

## #104-3 다섯 번째 자리 — `repair_document_status.py`

전수 검색(`getsize` / `def *exists*`)으로 판정 자리를 모두 찾았더니 하나가 더 있었다.

`repair_document_status.py:document_exists()`는 **디스크를 보고 `document_status`를
READY로 바꾸는** 스크립트다. 즉 **화면 상태를 정하는 쓰기 경로**다.
그런데 `return os.path.exists(real_path)`로 끝나고 있었다.

가장 얄궂은 것은 **바로 그 함수의 주석이 이 실패 모드를 예고하고 있었다**는 점이다.

> 여기서 검사를 빼면 DOCUMENT_ROOT 밖 파일의 존재 여부로 상태를 READY로 바꾸게 된다 —
> **서빙은 404인데 화면만 "수집완료"가 되는 상태다.**

0바이트에 대해 정확히 그렇게 동작하고 있었다. 이 스크립트의 **목적이 그 불일치를 없애는
것**인데 기준이 달라 목적과 반대로 동작할 수 있었다.

```python
return os.path.isfile(real_path) and os.path.getsize(real_path) > 0
```

---

## 정의를 하나로 못 박았다 (`test_false_success.py` §3·§4)

이번 결함의 뿌리는 "0바이트를 안 봤다"가 아니라 **같은 판정이 5벌 있었다는 것**이다.
그래서 동작뿐 아니라 **구조**를 고정했다.

```
[PASS] 0바이트 등기부는 404(빈 200이 아니다)              <- §3 동작
[PASS] 대조군: 내용이 있는 등기부는 200
[PASS] 모든 서빙 경로가 0바이트를 거른다: []               <- §4 구조 (FileResponse 전수)
       서빙 경로: api\v1\documents.py, api\v1\registry.py
[PASS] 모든 서빙 경로가 isfile로 판단한다(디렉터리 통과 방지)
[PASS] admin도 0바이트를 거부한다(다운로드와 같은 정의)      <- 쓰기 쪽
[PASS] crawler\doc_paths.py:doc_exists 가 0바이트를 '없음'으로 본다
[PASS] repair_document_status.py:document_exists 가 0바이트를 '없음'으로 본다
```

§4는 **새 서빙 경로가 생겼을 때**를 막는다. 세 번째 `FileResponse`가 추가되면서 크기
검사를 빠뜨리면 같은 결함이 또 생긴다 — 실제로 registry.py가 documents.py보다 뒤늦게
그 상태였다.

### 변이 검증 — 6종 전부 검출

| | 변이 | 검출 |
|---|---|---|
| M34 | registry 를 `exists()` 로 되돌림 | O (§3 동작 + §4 구조) |
| M35 | registry 에서 크기만 뺌(`isfile`은 유지) | O |
| M36 | documents 를 `exists()` 로 되돌림 | O (GET/HEAD 둘 다) |
| M37 | admin 이 다시 크기를 안 봄 | O |
| M38 | repair 가 다시 `exists()` 만 봄 | O |
| M39 | **canonical `doc_exists()` 가 느슨해짐** | O |

M39가 중요하다 — 기준 자체가 무너지는 경우까지 잡는다.

---

## #104-4 무료 등기부 크레딧: 부분 실패 롤백이 **검증된 적이 없었다**

같은 "false success" 계열을 돈 쪽으로 확장했다. `create_registry_request()`의 무료 경로는
**한 트랜잭션에서 세 번 쓴다.**

```
1) registry_usage        INSERT   <- 무료 1회를 "썼다"고 기록 (한도 계산의 근거)
2) registry_credit_logs  INSERT   <- 변동 추적 원장
3) registry_requests     INSERT   <- 사용자가 보는 신청
```

3번이 실패했는데 1번이 남으면 **사용자는 무료 횟수를 잃고 신청은 없다.**
화면에는 "남은 횟수"만 줄어들 뿐 이유를 볼 방법이 없다 — 돈으로 환산되는 자원의
가장 알아채기 어려운 손실이다.

코드는 `except Exception: conn.rollback(); raise`로 되돌리게 돼 있었지만
**그 경로가 한 번도 실행된 적이 없었다**(정적 확인만). 결제 쪽에는 같은 검사가 있는데
등기부에는 없었다.

### 검사 추가 (`test_api_regression.py` §41)

`registry_requests` INSERT만 `OperationalError`로 주입해 실패시키고, **응답이 아니라 DB로**
확인한다.

```
[PASS] 성공(200 + success)으로 응답하지 않는다
[PASS] 오류가 드러난다(예외 전파 또는 5xx)
[PASS] 실패 시 롤백한다
[PASS] registry_usage에 차감 흔적이 남지 않는다: 0
[PASS] registry_credit_logs에 흔적이 남지 않는다: 0
[PASS] registry_requests도 만들어지지 않는다: 0
[PASS] 롤백 후 정상 신청이 성공한다
[PASS] 무료 횟수를 잃지 않았다(첫 신청이 여전히 무료)
```

마지막 두 줄이 사용자 관점이다 — 실패한 뒤에도 **그 사람의 무료 1회가 그대로 남아 있는가.**

### 변이 검증 — 두 방어가 층을 이루고 있다는 것을 발견했다

| | 변이 | 결과 |
|---|---|---|
| M40 | `conn.rollback()` 제거 (예외만 전파) | **검출 O** — 단 `실패 시 롤백한다` 하나만 실패 |
| M41 | `conn.rollback()` → `conn.commit()` (부분쓰기 확정) | **검출 O** — `registry_usage`/`credit_logs`에 1행씩 남음 |

**M40에서 데이터 단언은 통과했다.** 이유가 있다 — `finally: conn.close()`가 있고,
sqlite3는 커밋되지 않은 트랜잭션을 **닫을 때 자동으로 롤백**한다. 즉 데이터 무결성은
`rollback()`과 `close()` **두 겹**으로 지켜지고 있고, 명시적 `rollback()`은 그중 한 겹이다.

이것을 "M40이 데이터 유출을 잡았다"고 적으면 사실이 아니다. 검사가 **동작(롤백 호출)**과
**결과(남은 행 0)**를 따로 보기 때문에 두 층이 각각 무너지는 것을 구분해 잡는다 —
그 구분이 실제로 드러난 것이 이번 변이 결과다.

---

## 프런트는 이 404를 제대로 처리한다 (확인만)

내 수정은 200(빈 파일) → 404로 **동작을 바꿨다.** 호출부를 확인했다.

```js
// src/app/properties/[id]/page.tsx:415
if (!res.ok || contentType.includes('application/json')) {
  const body = await res.json().catch(() => null)
  setRegistryMessage(body?.message ?? '다운로드에 실패했습니다')
  return
}
```

`!res.ok`로 404를 잡아 메시지를 띄운다. 빈 blob을 파일로 저장하는 경로로 가지 않는다.
**바뀐 동작이 프런트에서 안전하게 끝난다.**

> `HTTPException`은 `{"detail": ...}`을 주고 프런트는 `body?.message`를 읽으므로
> 구체 사유 대신 기본 문구("다운로드에 실패했습니다")가 나온다. 상태코드를 바꾸면
> (`error_response`는 HTTP 200 + `success:false`) **기존 API 계약이 깨지므로** 하지 않았다.
> 사용자에게 나가는 문구는 사실과 어긋나지 않는다.

---

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31/31 파일 통과** |
| `python -m compileall` | **exit 0** |
| BOM 무결성 (`test_schema_hygiene` §8) | **통과** |
| 콘솔 인코딩 (`test_console_encoding`) | **통과** |
| 프런트 테스트 | **107/107** (fail 0 / cancelled 0 / skipped 0) |
| TypeCheck / Lint / Build | **전부 exit 0** |
| 실 DB | **무변경** (메모리 DB + 임시 파일로만 재현, 생성 파일 전부 정리) |

## 수정 파일

```
api/v1/registry.py            0바이트/디렉터리를 404로 (읽기)
api/v1/admin.py               0바이트/디렉터리를 400으로 (쓰기)
repair_document_status.py     0바이트를 '없음'으로 (화면 상태 쓰기)
test_false_success.py         §3 동작 + §4 구조 가드 신설
test_api_regression.py        §41 무료 크레딧 부분 실패 롤백 검사 신설
```

**제품 코드 수정은 3개 파일뿐이고 전부 한 줄짜리 판정 조건이다.** 나머지는 검사다.

## SKIP 및 이유

| 항목 | 이유 |
|---|---|
| 404 → `error_response`(200 envelope) 전환 | **기존 API 계약 변경.** 프런트는 이미 404를 처리한다 |
| 0바이트 등기부 파일 실데이터 정리 | 현재 `registry_documents/`에 해당 파일 없음(운영 데이터 정리는 승인 영역) |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** (#102-6 — 2026-08-20에 검색 0건)
- `backfill_region_normalize.py --apply` + 드리프트 상한 4개를 0으로 (#103-1)
- 다른 세션 worktree 48개 파일 병합 결정 (겹치는 5개는 손 병합)
- starlette 업그레이드 시 httpx → httpx2 전환
- `appraisal_summary` 저장 여부 — 저장하면 `validation_status`도 감사 가능 (#103-5)
- `document-stats`의 `total_failures` 정의 결정 (#101-3)
- 현황조사서 item_no != 1 버튼 id 확보 + `SKIPPED_UNSUPPORTED` 복귀 스크립트
- 고아 파일 3개 / 고아 큐 18행 정리
- 커밋된 DB 백업 9개(36.9MB) 인덱스에서 제거
- 구독 결제 환불 시 구독 처리(A/B/C/D)
