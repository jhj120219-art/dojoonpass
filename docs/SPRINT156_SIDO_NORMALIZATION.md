# Sprint 156 — 같은 `sido`를 두 엔드포인트가 다르게 해석한다

작성 2026-08-17. 모든 수치는 실행 결과다.
공유 문서(`BUGS.md`, `CHANGELOG.md`, `CURRENT_STATE.md`, `roadmap.md`, `TEST_PLAN.md`)는
다른 세션이 편집 중이라 건드리지 않았다.

---

## 1. 성능 감사를 하다가 걸렸다

API 지연을 재는 중 `/api/v1/search/regions`만 실패했다.

```
/api/v1/search (기본)        p50 2.1ms   max 22.4ms    5,536 bytes
/api/v1/search?size=100      p50 2.0ms   max  2.2ms    5,537 bytes
/api/v1/item/1               p50 1.9ms   max 18.1ms    1,395 bytes
/api/v1/stats                p50 1.8ms   max 20.9ms      834 bytes
/api/v1/plans                p50 0.9ms   max  1.6ms      857 bytes
/api/v1/document-stats       p50 2.6ms   max  3.2ms      218 bytes
/api/v1/search/regions       실패(HTTPError)
```

**성능 문제는 없다** — 전 구간 p50 약 2ms. `regions` 실패는 422였고,
`sido`가 필수 파라미터인데 내가 안 보낸 탓이었다(**코드가 아니라 내 측정이 틀렸다**).

그런데 파라미터를 넣어 다시 재다가 진짜 문제를 봤다.

```
/api/v1/search/regions?sido=서울특별시  ->  {"sido":"서울특별시","sigungu":[]}   빈 목록
```

## 2. 실측 — 두 엔드포인트가 갈린다

`auction_item.sido`는 **축약형**으로 저장돼 있다(실측 분포: 경기 467 / 서울 275 /
경북 156 / 경남 156 / 부산 135 …). `sido='서울특별시'`인 행은 **0건**이다.

| 요청 `sido` | `/search/regions` | `/search` total |
|---|---|---|
| `서울` | 26건 | 9 |
| `서울특별시` | **0건** | 9 |
| `서울시` | **0건** | 9 |
| `경기` | 39건 | 0 |
| `경기도` | **0건** | 0 |

원인은 한 줄 차이였다.

```python
# /search (search.py:289~294)  — 정규화한다
conditions.append("sido = ?")
params.append(extract_sido(sido) or sido)      # "서울특별시" -> "서울"

# /search/regions (같은 파일)  — 정규화하지 않았다
"WHERE sido = ? ...", (sido,)                  # "서울특별시" 그대로
```

`extract_sido()` 자체는 멀쩡하다(직접 확인: 서울특별시/서울시/경기도/제주특별자치도/
부산광역시 전부 축약형으로 정확히 변환). **호출하지 않은 것이 문제였다.**

## 3. 사용자에게 보이나 — 보인다, 다만 좁은 경로로

지금 화면은 `SearchForm.tsx:12`의 `SIDO_LIST`가 축약형(`'서울','부산',…`)을 보내므로
드롭다운 정상 동작한다. **그래서 평소에는 드러나지 않는다.**

그러나 검색 화면은 **URL 파라미터로 상태를 복원한다.**

```
SearchForm.tsx:190   sido: searchParams.get('sido') ?? ''
SearchForm.tsx:277   fetch(`/api/v1/search/regions?sido=${encodeURIComponent(form.sido)}`)
```

즉 `?sido=서울특별시`가 담긴 링크(공유 링크·북마크·외부 유입)를 열면

```
검색 결과      9건 정상 표시   (search 는 정규화하므로)
시/군/구 목록  비어 있음       (regions 는 정규화하지 않으므로)
```

사용자에게는 **"결과는 나오는데 구를 못 고르겠다"** 로 보인다. 오류 메시지도 없다.

## 4. 수정 — 새 정책이 아니라 기존 규약의 적용

```python
normalized_sido = extract_sido(sido) or sido
... "WHERE sido = ? ...", (normalized_sido,)
```

`search.py`가 이미 정한 규약(주석까지 달려 있다)을 같은 파일의 다른 함수에 적용할 뿐이다.
`extract_sido`가 못 알아들으면 원본을 그대로 쓰는 fallback도 동일하다.

**응답의 `sido`는 요청값 그대로 둔다**(정규화값으로 바꾸지 않는다). 조회에만 정규화를
쓰고 응답 형태는 건드리지 않는다 — 그건 별개의 API 계약 변경이고 이번 목적과 무관하다.

> 자기 정정: 처음에는 "프런트가 응답의 sido를 자기 폼 값과 비교해 경합을 막으므로
> 바꾸면 안 된다"고 주석에 적었다. **확인해 보니 사실이 아니었다** —
> 프런트는 `data.sigungu`만 읽고, 경합 방지는 로컬 `sigunguKey` + `cancelled`
> 플래그로 한다(`SearchForm.tsx:265, 274-287`). 근거를 확인하지 않고 적었던 것이라
> 주석을 사실에 맞게 고쳤다.

### 수정 후

```
sido=서울             regions 26   search.total 9
sido=서울특별시        regions 26   search.total 9      <- 일치
sido=서울시           regions 26   search.total 9      <- 일치
sido=경기             regions 39   search.total 0
sido=경기도           regions 39   search.total 0      <- 일치
sido=제주특별자치도     regions  2
sido=없는지역          regions  0   (200, 500 아님 — fallback 경로)
```

## 5. 회귀 — `test_search.py`에 그룹 추가

```
[PASS] 축약형이 시/군/구를 실제로 돌려준다        (26건 — 대조군이 비어 있으면 검사가 무의미하다)
[PASS] ★ regions?sido=서울특별시 가 축약형과 같은 목록
[PASS] ★ regions?sido=서울시 가 축약형과 같은 목록
[PASS] regions 응답 sido는 요청값 그대로          (응답 계약 불변 고정)
[PASS] ★ search 총건수도 표기와 무관하게 같다      (두 엔드포인트가 어긋나지 않는다)
[PASS] 알 수 없는 sido -> 200 + 빈 목록           (fallback 이 500이 되지 않는다)
전체 81건 통과
```

"축약형이 실제로 26건을 돌려준다"를 먼저 단언한 이유: 대조군이 빈 목록이면
`got == canonical`이 **양쪽 다 비어서** 통과해 버린다. 검사가 비어 있지 않게 만드는 조건이다.

### Mutation

```
M1 regions 정규화 제거   exit=1 FAIL=2  잡힘
   [FAIL] ★ regions?sido=서울특별시 가 축약형과 같은 목록 -> 0건 (축약형 26건)
   [FAIL] ★ regions?sido=서울시 가 축약형과 같은 목록 -> 0건 (축약형 26건)
원본 복원 확인 OK
```

## 6. 곁가지 — 서버가 옛 코드를 돌고 있었다

수정 후 확인했는데 여전히 0건이라 `extract_sido`를 의심했다. 직접 호출해 보니 정상이었고,
원인은 **재기동 실패**였다.

```
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)
포트 8000 점유: PID 4572 (python, 03:26 기동)   <- 옛 프로세스가 살아 있었다
```

`pkill -f`가 이 환경의 uvicorn 프로세스에 닿지 않아, 새 인스턴스가 바인드에 실패하고
**옛 코드가 계속 응답하고 있었다.** 포트 점유 프로세스를 직접 종료하고 재기동하니
기대대로 나왔다.

> 교훈: "고쳤는데 안 바뀐다"일 때 코드를 의심하기 전에 **무엇이 응답하고 있는지**부터
> 확인한다. 재기동 성공을 확인하지 않은 채 측정하면 옛 바이너리를 재는 셈이다.

## 7. 검증 결과

```
파이썬 전체   통과 35 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 4,334건, 40.0s)
              실패 1건은 test_schema_hygiene.py — 이 변경과 무관
프런트엔드    exit 0 (111/111)
tsc 0   eslint 0
```

## 8. 변경 파일

```
수정   api/v1/search.py     get_regions() 에 extract_sido 정규화 적용 (+근거 주석)
수정   test_search.py       sido 표기 정규화 그룹 추가 (81건 통과)
신규   docs/SPRINT156_SIDO_NORMALIZATION.md
```

## 9. 성능 감사 결론 (별도 결함 없음)

```
API p50 0.9~2.6ms, max 27ms(최초 요청 워밍업)
/search 응답 5.5KB (total 9건), size 파라미터 정상 동작 (size=1 -> 1건)
```

병목 없음. **수정할 것이 없어 수정하지 않았다.**
현재 노출 물건이 9건뿐이라 이 수치는 소규모 데이터 기준이며, 물건 수가 늘면
다시 측정해야 한다는 점을 명시해 둔다(측정하지 않은 규모를 추정하지 않는다).
