# Sprint 160 — 중복 구현 감사: 경로 규칙 사본이 아직 6곳 남아 있다

작성 2026-08-17. 모든 수치는 실행 결과다.

**코드를 바꾸지 않았다** — 해당 파일들을 다른 세션이 같은 시각에 편집 중이라
충돌을 피해 건너뛰었다(`/goal` 규칙). 대신 정확한 위치와 영향 범위를 남긴다.

---

## 1. 왜 중복을 뒤졌나

이번 세션에서 찾은 결함 두 개가 **같은 뿌리**였다.

```
Sprint 156   /search 는 sido 를 정규화하는데 /search/regions 만 안 했다
Sprint 155   목록 6곳은 _offset() 을 쓰는데 registry-requests 만 인라인으로 곱했다
```

둘 다 "같은 규칙이 두 벌"이다. 그래서 같은 모양이 더 있는지 전수로 훑었다.

## 2. 발견 — 경로 정규화 규칙 사본 6곳

Sprint 145가 `sanitize_path_segment()`로 한 곳에 모았고, Sprint 153이
`repair_document_status.py`의 사본을 없앴다. 그런데 **아직 남아 있다.**

```
backfill_doc_raw.py:67   safe_case_no = (case_no or "").replace("/", "_").strip()
backfill_doc_raw.py:68   safe_item_no = (item_no or "1").replace("/", "_").strip()
backfill_doc_raw.py:84   〃 (primary_file_path 에서 한 번 더)
backfill_doc_raw.py:85   〃
step11_report.py:45
step7_report.py:28
```

정본과 비교하면 세 가지가 빠져 있다.

| | 정본 `sanitize_path_segment()` | 남은 사본 |
|---|---|---|
| `/` 치환 | O | O |
| `\` 치환 | **O** | **X** |
| `.` / `..` / 빈 문자열 처리 | **O** (`_` 로) | **X** |

Windows에서는 `\` 도 경로 구분자다. 사건번호에 `\` 가 섞이면 크롤러는 `a_b` 에 쓰고
백필은 `a\b` 를 계산해 **같은 문서를 두 경로로 보게 된다** — BUGS #50/#64/#111 계열.

### 아이러니

`backfill_doc_raw.py` 자신의 docstring(61~62행)이 이렇게 적고 있다.

> 경로 규칙을 여기서 새로 쓰지 않고 `crawler/doc_paths.py`의 파일명 표를 그대로
> 쓴다 — **규칙이 두 벌이 되면 백필이 뷰어와 다른 파일을 가리키게 된다.**

파일명 표(`CANONICAL_DOC_FILENAME`, `_PRIMARY_EXT`)는 실제로 import 한다.
그런데 **정규화 규칙은 인라인으로 다시 썼다.** 경계한 바로 그 일을 옆줄에서 했다.

## 3. 지금 터지고 있나 — 아니다 (실측)

```
auction_item 1,876행
   역슬래시 포함     0      <- 그래서 지금은 어긋나지 않는다
   슬래시 포함     425      <- '/' 치환 자체는 매우 활발히 쓰인다
   '.'/'..'/빈값     0
```

`/` 는 425행에서 실제로 쓰이므로 사본들도 그 부분은 정확히 동작한다.
**잠재 결함이다** — Sprint 145 때와 같은 결론이다.

## 4. 이걸 잡아야 할 검사가 왜 못 잡았나

`test_doc_path_safety.py`의 검사는 **목록 기반**이다.

```python
targets = [
    crawler/doc_paths.py, crawler/image_assets.py,
    api/v1/documents.py, api/v1/images.py,
    repair_document_status.py,     # <- Sprint 153 이 추가
]
```

그 목록에 `backfill_doc_raw.py` 가 없다. 그리고 **바로 그 파일의 주석이 이 실패를
이미 설명하고 있다**(206~208행).

> 2026-08-17 Sprint 153: 여기 빠져 있어서 규칙 사본이 하나 더 살아남았다

같은 이유로 또 하나가 살아남았다. `docs/BUGS.md` 의 교훈도 같은 말을 한다 —
*"목록으로 대상을 지정하는 검사는 목록에서 빠진 파일을 영원히 못 본다.
새 파일이 생길 때 목록을 갱신하는 규율이 없다면, 목록이 아니라 전수 스캔으로 짜야 한다."*

**세 번째로 같은 방식으로 놓쳤다.** 목록을 한 줄 더 늘리는 것은 네 번째를 예약하는 일이다.

## 5. 왜 내가 고치지 않았나

두 파일 다 다른 세션이 **작업 중**이다.

```
backfill_doc_raw.py      16:22 수정   (내가 아님)
test_doc_path_safety.py  15:34 수정   (다른 세션이 repair_document_status.py 항목 추가)
```

`/goal` 규칙: *"충돌 위험이 있는 파일은 건너뛰고 독립적인 작업을 계속한다."*
지금 손대면 그쪽 편집을 덮어쓸 수 있다. 그래서 **위치와 근거만 남긴다.**

내 테스트로 전수 스캔을 새로 만드는 것도 고려했으나, 지금 만들면 위 6곳 때문에
**곧바로 실패하는 테스트**가 하나 더 늘어난다(현재 실패는 `test_schema_hygiene.py`
하나뿐이고, 그것도 스테이징으로만 풀린다). 남의 작업 중인 파일을 근거로 실패를
추가하지 않는 편이 낫다고 판단했다.

## 6. 권고 (다른 세션 또는 사용자에게)

1. `backfill_doc_raw.py` 의 4곳을 `sanitize_path_segment()` import 로 교체
   (`repair_document_status.py` 에 이미 적용된 것과 동일한 수정).
2. `test_doc_path_safety.py` 의 `targets` 목록을 **전수 스캔으로 교체** —
   `.py` 전체를 훑어 `sanitize_path_segment` 정의 한 줄만 예외로 두면 목록 관리가 사라진다.
   실측상 그 방식으로 스캔하면 지금 6곳이 정확히 잡힌다(내가 돌려 확인했다).
3. `step7_report.py` / `step11_report.py` 는 일회성 점검 스크립트라 우선순위가 낮다.

## 7. 함께 훑고 넘어간 것 (결함 없음)

- **`(page-1)*size` 인라인** — `api/v1/search.py:381` 이 인라인으로 계산하지만
  **같은 함수 263행에 범위 가드가 이미 있다.** 가드 후 사용이라 안전하다(결함 아님).
  `admin.py` 쪽은 Sprint 155에서 `_offset()` 으로 통일했다.
- **`is_sqlite_int` 우회** — 범위 상수를 직접 비교하는 코드 0건.
- **`extract_sido` 우회** — sido 를 문자열로 직접 비교하는 코드 0건.

## 8. 변경 파일

```
신규   docs/SPRINT160_DUPLICATE_RULE_AUDIT.md
```

**코드 변경 0.**
