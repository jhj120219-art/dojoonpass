# Sprint 164 — "없는 파일을 수집 완료로 적지 않는다"를 검사로 고정

작성 2026-08-17. 모든 수치는 실행 결과다. **프로덕션 코드 변경 0** — 결함이 없었다.

---

## 1. 커버리지 재측정에서 남은 것

세션 초반 대비 다시 전 파일로 쟀다.

```
api/auth.py        98%  ->  100%   (Sprint 152)
api/v1/admin.py    96%  ->  100%   (Sprint 153/155/158)
storage/database.py            88%  <- 남아 있던 것
```

`storage/database.py` 의 미커버 46줄에서 `query()`(프로덕션 호출부 0개, Sprint 146 §J-5)를
빼면 **전부 자산 기록 경로의 방어 분기**였다.

```
877-878    _sha256_file            파일을 못 읽을 때
892-897    _pdf_page_count         pdfplumber 없음 / 계산
915-916    to_relative_storage_path  루트 밖 경로
948-955    _record_doc_raw         대상 물건 없음 / 알 수 없는 doc_type
965-973    _record_doc_raw         대표 파일 fallback
1027-1049  save_auction_images     대상 없음 / 잘못된 항목 / 0바이트
```

## 2. 왜 이건 "의미 없는 커버리지"가 아닌가

`/goal` 의 Coverage Rule 대로 하나씩 확인했다.

| 질문 | 답 |
|---|---|
| Production 에서 호출되나 | **예** — 크롤러가 문서/사진을 저장할 때마다 탄다 |
| Live Code 인가 | **예** (`backfill_doc_raw.py` 도 세 헬퍼를 import 한다) |
| Defensive 인가 | 예 — 그런데 **무엇을 막는지**가 중요하다 |

이 분기들이 막는 것은 이 저장소의 단골 결함이다 —
**"없는 파일을 수집 완료로 기록하는 것".** `doc_raw`/`auction_image` 에 행이 생기면
화면은 "문서 있음"으로 표시하고, 사용자는 눌렀을 때 **빈 화면**을 본다. 오류 메시지도 없다.
Sprint 98 이 `api/v1/documents.py` 에서 0바이트 파일을 404로 바꾼 것과 같은 계열이며,
이쪽은 **쓰는 쪽**이다.

정상 경로는 `test_asset_pipeline.py` 가 이미 덮는다. 덮이지 않은 것은 **실패했을 때**뿐이었다.

## 3. `test_asset_record_failures.py` (신규) — 7그룹

각 실패마다 두 가지를 단언한다: **예외로 터지지 않는다** + **거짓 성공 행이 남지 않는다.**

```
1. 순수 함수      없는 파일 해시 -> ""  /  PDF 아님·없음 -> None(0 아님)  /  루트 밖 경로 보존
2. doc_raw        대상 물건 없음        -> 행 0
3. doc_raw        알 수 없는 종류·image -> 행 0
4. ★ doc_raw      저장했다는 파일이 없음 -> 행 0
5. ★ auction_image 없는 파일/0바이트/seq 아님/path 없음 4건 -> saved 0, skipped 4, 행 0
6. auction_image  대상 물건 없음        -> saved 0, 행 0
7. 대조군          정상 파일           -> saved 1, 행 1
```

**7번이 없으면 위 여섯 개는 "항상 0"이라서 통과하는 검사일 수 있다.** 정상 파일이 실제로
기록되는 것을 같은 파일에서 증명해 검사가 비어 있지 않음을 보장한다.

`_pdf_page_count` 에서 **None 과 0 을 구분**하는 것도 계약이다 — 0 은 "0쪽짜리 PDF"라는
거짓말이 되어 뷰어가 페이지 이동을 못 그린다(소스 주석이 그 사고 이력을 적고 있다).

## 4. Mutation — 3개 중 1개는 **일부러 살려 두었다**

```
M1 0바이트 이미지 가드 제거         exit=1 잡힘   [FAIL] 하나도 저장되지 않았다: 1 (expected 0)
M2 이미지 "파일 없음" 가드 제거      exit=0 살아남음
M3 잘못된 항목(seq/path) 가드 제거   exit=1 잡힘
원본 복원 확인 OK
```

M2 가 살아남은 이유를 확인했다. `except OSError` 를 지우고 `size = 0` 으로 떨어뜨리면
**바로 다음 줄의 `if size <= 0` 가드가 같은 항목을 걸러 낸다.** 없는 파일은 **두 겹으로**
막혀 있고, 한 겹을 걷어내도 계약("없는 파일은 기록되지 않는다")은 그대로다.

테스트가 약한 것이 아니라 **코드가 겹쳐 방어하고 있는 것**이다. 두 겹을 구분하려면 로그
문구를 단언해야 하는데 그건 계약이 아니라 구현을 고정하는 일이라 하지 않았다
(Sprint 158 의 `conn.rollback()` equivalent mutant 과 같은 판단). 파일 docstring 에도 적어 두었다.

## 5. 검증 결과

```
파이썬 전체   통과 37 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,504건, 46.4s)  ×3회 동일
              실패 1건은 test_schema_hygiene.py — 미추적 파일 문제(`git add` 로만 풀린다)
프런트엔드    113 tests / 113 pass / 0 fail
tsc 0   eslint 0   compileall 0
```

목표한 분기(877-878 / 948-955 / 1027-1049)는 전부 실행됐다 — 미커버 목록에서 사라졌다.

> 수치 주의: 중간에 한 번 "통과 36 | 실패 2 | 단언 4478" 이 나왔는데 **불안정이 아니다.**
> 내가 이 테스트 파일의 docstring 을 편집하는 중에 실행된 것이고(단언 수가 다르다),
> 편집이 끝난 뒤 3회 연속 동일한 결과가 나왔다. 원인을 확인하지 않고 "가끔 그렇다"로
> 넘기지 않았다.

## 6. 변경 파일

```
신규   test_asset_record_failures.py       7그룹
신규   docs/SPRINT164_ASSET_RECORD_FAILURES.md
```

**프로덕션 코드 변경 0.** 방어 분기들이 전부 계약대로 동작해서 고칠 것이 없었다.

## 7. 남은 미커버 (조사 완료, 조치 안 함)

- `storage/database.py:query()` — 프로덕션 호출부 0개. 유일 호출부가 `ALLOW_LIVE_CRAWL`
  게이트된 `test_db.py` 다. 삭제는 Architecture 결정이라 SKIP(Sprint 146 §J-5 에 기록).
- `_pdf_page_count` 의 pdfplumber 실제 계산 경로(897) — pdfplumber 설치 여부에 좌우된다.
  라이브러리 추가는 승인 영역이라 건드리지 않았다.
- `crawler/{court,doc,base}_crawler.py` 24~45% — selenium 드라이버가 필요한 코드다.
  순수 로직은 Sprint 47 이 `crawler/resume.py` 로 분리해 100% 덮여 있다.
