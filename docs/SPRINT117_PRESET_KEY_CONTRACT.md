# Sprint 117 ― 저장한 검색조건과 실제로 보내는 조건 (2026-08-14)

> 앞 Sprint: `docs/SPRINT116_PIPELINE_EXIT_CONTRACT.md`
>
> **별도 파일 이유**: Sprint 100~116과 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

프런트를 훑으며 "같은 사실을 두 목록이 따로 들고 있는" 자리를 찾았다.
**결함은 0건**이었지만, 그 일치를 지키는 검사가 없었다.

---

## 1. 먼저 확인한 것들 (전부 결함 0건)

- **쓰기 경로의 거짓 성공**: `postJSON`/`deleteJSON` 은 `!res.ok` 에서만 던지는데
  백엔드의 `error_response()` 는 **HTTP 200 + `success:false`** 다.
  호출부 **6곳 전부** `result.success` 를 보고, 멱등 케이스는 도메인 Error Code 로 구분한다.
- **참조 무결성**: `favorites` / `recent_items` / `registry_requests` / `document_status` /
  `rights_summary` / `tenant_rights` 의 `item_id` 고아 **전부 0건**, FK 선언도 4/4.
- **빈 결과 화면**: `ResultList` 는 "0건"과 "페이지 범위 초과"를 구분하고
  후자는 **검색조건을 유지한 채** 1페이지로 보내는 복구 동선을 준다.
- **`recent_items` 상한**: 읽기 `LIMIT 20` 은 표시 제한이고 보관 상한 정책은 문서에 없다.
  `(user_id, item_id)` upsert 라 사용자당 행 수는 조회한 물건 종류 수만큼 는다.
  **정책이 없으므로 결함이 아니다** ― 보관 기간을 정하는 것은 제품 판단이다.
- **데이터 신선도**: `test_pipeline_integrity.py` §11이 이미 경고를 띄우고 있다.
  `★ 수집이 멈춘 채로 두면 2026-08-20 부터 검색 결과 0건 (6일 남음)`

## 2. ★ 검사가 없던 자리 ― 프런트 **안쪽**의 두 목록

기존 계약 검사는 **프런트 ↔ 백엔드**를 본다(`tests/source-contract.test.mjs`, Sprint 55).
빠져 있던 것은 프런트 안쪽이다.

```
buildSearchQuery()   URL 에 실어 보낼 파라미터를 만든다          24개
FILTER_PARAM_KEYS    "검색조건 저장"이 URL 에서 뽑아 저장할 키   24개
```

둘은 **같은 파일에 있지만 따로 관리된다**. `SearchPresets.tsx` 가 import 해서 쓰는 것은
`FILTER_PARAM_KEYS` 뿐이다.

어긋나면 이렇게 된다 ― 새 필터를 `buildSearchQuery()` 에만 추가하면
**검색은 정상 동작하는데 저장된 검색조건에서는 그 필터가 빠진다.**
사용자는 저장한 조건을 다시 불러왔을 때 **다른 결과**를 본다.
오류도 빈 화면도 아니라 알아챌 방법이 없다 ― 이 저장소가 반복해서 잡아 온
"조용히 틀리는" 모양이다.

2026-08-14 실측: **양쪽 24개, 차이 0.** 지금은 맞다. 그 상태를 고정한다.

```js
test('저장되는 검색조건 키가 실제로 보내는 파라미터와 같다', ...)
```

- **양방향**으로 본다. `FILTER_PARAM_KEYS` 에만 남은 키는 죽은 항목이고,
  쌓이면 목록이 실제 필터 집합을 더 이상 설명하지 못한다.
- 추출이 실패하면 두 집합이 비어 "차이 없음"으로 통과한다 ―
  `size > 10` 전제를 둬서 **공허한 검사**가 되지 않게 했다.

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M93 | `FILTER_PARAM_KEYS` 에서 `min_bid_rate` 제거 | **검출 O** ― "저장한 조건을 다시 불러오면 이 필터가 빠집니다: min_bid_rate" |
| M94 | 목록에 `ghost_filter` 추가 (죽은 키) | **검출 O** ― "목록에서 빼십시오: ghost_filter" |

두 방향 모두 잡고, 메시지가 **무엇이 잘못되는지**를 그대로 말한다.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외) |
| 프런트 테스트 | **108/108** (fail 0 / cancelled 0 / skipped 0) ― 신설 1개 포함 |
| TypeCheck / Lint / Build | **전부 exit 0** |
| 서버 | 기동 후 정리, 포트 8000/3000 **풀린 것으로 확인** |
| 실 DB | **한 줄도 쓰지 않았다** |

## 수정 파일

```
tests/source-contract.test.mjs    저장 키 ↔ 전송 파라미터 양방향 계약 검사 신설
```

**제품 코드 변경 0건.**

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  `register_scheduler_tasks.ps1 -Apply` 한 줄이면 된다(Sprint 112).
- Sprint 105~116의 SKIP 표 항목들 (전부 승인/외부 조치 대기)
