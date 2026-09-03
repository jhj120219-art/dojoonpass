# Sprint 295 — 파서 경계값 감사 + 날짜/금액 DB 불변식 신설 (2026-09-03, 매장 환경)

> 매장 환경. 크롤러를 돌리지 않고 **순수 함수에 fixture 를 직접 넣어** 감사했다.
> 운영 DB 미변경(사본에서만 mutation).

---

## 감사 대상

`crawler/base_crawler.py` 의 `parse_*` 는 selenium `driver` 를 받아 fixture 로 부르기
어렵다. 대신 그 출력이 흘러드는 **순수 함수**를 먼저 감사했다 — downstream 연결이
명확하고(파서 → DB → API → 화면) 경계값을 직접 넣을 수 있다.

```
normalize_price · normalize_date · normalize_case_no   (normalizer/normalizer.py)
```

---

## 발견 — 파서가 **실패를 조용히 통과**시킨다 (이미 알려진 위험, 그러나 DB 가드 없음)

fixture 를 직접 넣어 실측했다.

```
normalize_date
  '2026.01.05'  -> '2026-01-05'    정상
  '2026.1.5'    -> '2026.1.5'      ★ 한 자리 월/일은 매치 실패 -> **원문 그대로**
  '26.01.05'    -> '26.01.05'      ★
  '미상'         -> '미상'           ★
  '2026-13-45'  -> '2026-13-45'    ★ 형식만 맞으면 없는 날짜도 통과

normalize_price
  '100,000,000원' -> 100000000     정상
  '1억 2천'       -> 12            ★ 한글 단위를 못 읽고 **12원**
  '1,234.56'     -> 123456         ★ 소수점이 사라져 100배
  '-5000'        -> 5000           부호 소실(경매 금액엔 음수가 없어 무해)
  '-' / '' / None -> 0             ★ 크롤 실패와 '0원'이 구별되지 않는다
```

### downstream 위험이 실재한다

이 저장소는 날짜를 **문자열로 비교**한다(`auction_date >= ?` — D7 필터, 정렬, 우선순위,
doc_worker 의 기일 판정). 파싱 실패값은 **전부 오늘보다 크다**고 판정된다.

```
'미상'       >= '2026-09-03'  -> True
'26.01.05'   >= '2026-09-03'  -> True
'2026.1.5'   >= '2026-09-03'  -> True
'2026-13-45' >= '2026-09-03'  -> True
```

즉 원천 응답 형식이 한 번 바뀌면 **종결된 물건이 기본 검색에 계속 뜬다.**
지역 오염이 지역 필터를 망친 것과 같은 모양이다.

---

## ★ 진짜 공백 — 파서 계약은 고정돼 있는데 DB 결과는 아무도 세지 않았다

`test_normalizer.py` 는 이 위험을 **이미 정확히 알고 있었다**(97~115행 주석). 위 두
항목을 "잠재 위험"으로 명시하고, `normalize_date("2026-8-19") > "2026-09-01"` 이
참이라는 것까지 테스트로 못박아 두었다. 파서 쪽 계약은 충분하다.

그런데 그 주석이 근거로 든 문장이 이것이다.

> 실측(2026-08-13): 실제 데이터에는 두 경우 모두 **0건**이다 … 이 검사는 그 전제가
> 깨지는 순간을 잡기 위한 것이다.

**그 전제를 계속 감시하는 검사가 없었다.** 2026-08-13 에 손으로 잰 값이고, 그 뒤로는
아무도 세지 않는다. 파서가 실패값을 통과시킨다는 사실만 고정돼 있고, **그 값이 실제로
DB 에 들어갔는지**는 시야 밖이었다.

지역 오염 · 면적 드리프트와 같은 계열의 공백이다.

---

## 고친 것 — DB 불변식 3축 신설 (`test_pipeline_integrity.py` §12)

새 파일을 만들지 않고 파생값 검사 절에 이어 붙였다. 형식만 본다 —
"이 날짜가 사실인가"는 판정하지 않는다(그건 원천의 몫이다).

```
대상 컬럼
  날짜  auction_item.auction_date / crawl_date
        auction.auction_date / crawl_date
        document_queue.auction_date
        auction_case.filed_date / demand_deadline   (컬럼 없으면 건너뜀)
  금액  auction_item / auction 의 appraisal_price · minimum_bid_price

검사 3축
  ★ 저장된 날짜가 전부 YYYY-MM-DD 다
  ★ 저장된 날짜가 전부 **실재하는** 날짜다      ('2026-13-45' 는 형식만 맞다)
  ★ 금액이 0 인 행이 없다                     (크롤 실패와 '0원'을 구별할 수 없다)
```

### 실행 결과 (이 머신)

```
검사가 공허하지 않다 - 날짜 118개 값 / 금액 4개 컬럼을 봤다   PASS
★ 저장된 날짜가 전부 YYYY-MM-DD 다        []  PASS
★ 저장된 날짜가 전부 실재하는 날짜다        []  PASS
★ 금액이 0 인 행이 없다                   []  PASS
검출기 자체 검증 3건                          PASS
```

### mutation — 3축 전부 실제로 잡는다

사본 DB 에 주입하고 같은 함수를 돌렸다(운영 DB 미변경).

```
auction_date='2026-8-19'   -> [FAIL] YYYY-MM-DD 다        검출 ✔
crawl_date='미상'           -> [FAIL] YYYY-MM-DD 다        검출 ✔
auction_date='2026-13-45'  -> [FAIL] 실재하는 날짜다        검출 ✔  (형식 축은 통과 — 별도 축이 필요한 이유)
appraisal_price=0          -> [FAIL] 금액이 0 인 행이 없다  검출 ✔
```

`2026-13-45` 가 형식 축을 통과하고 실재성 축에서만 걸리는 것이, 두 축을 나눈 이유다.

---

## 관찰 (결함 아님, 기록만)

`auction_item.auction_date` 가 **빈 문자열인 행이 1건** 있다.

```
id=8185  case_no='2024타경995 / 2024타경1417 / 2025타경5447 / 2025타경5483 / 2025타경5476'
         status='-'  crawl_date='2026-08-01'  (병합사건 5건, 토지 임야)
         document_queue 에 3행 존재
```

원천이 기일을 주지 않은 물건으로 보인다(`status` 도 `'-'`). 빈 값은
`'' >= '2026-09-03'` 이 False 라 **기본 검색에서 제외**되는데, 기일이 없는 물건을
빼는 것은 의도에 부합한다. 그래서 새 불변식도 **빈 값/NULL 은 대상에서 제외**한다 —
"값이 없다"와 "형식이 틀렸다"는 다른 사건이기 때문이다.

---

## regression

```
test_pipeline_integrity   FAILED (1)  <- migration 028 하나뿐. 신규 검사로 인한 회귀 없음
test_normalizer           82건 통과
test_schema_hygiene       FAILED (2)  <- 기존 migration 항목 그대로
```

---

## BLOCKED_EXTERNAL_RUNTIME

```
crawler/base_crawler.py 의 parse_basic_info / parse_section_table / parse_gamjung
  selenium driver 를 인자로 받는다. driver 를 세우지 않고 fixture 로 부르려면
  DOM 을 흉내내는 가짜 driver 가 필요하고, 그것은 "실제 코드 경로"가 아니게 된다.
  실제 DOM 변형 검증은 운영 크롤 1회가 필요하다.
  -> 대신 그 출력이 흘러드는 순수 함수(위 3종)를 경계값으로 감사했다.
```

## APPROVAL_REQUIRED

없음. 파서의 표기 규칙(예: `'1억 2천'` 을 읽을 것인가)은 원천 계약에 대한 제품 판단이라
임의로 바꾸지 않았다. 지금 실데이터에 그런 입력은 0건이고, 들어오는 순간 위 불변식이
`금액이 0` 또는 형식 축에서 운다.

---

# 추가 (2026-09-03 후반) — mutation 강제 + downstream 추적 + `parse_image_alt`

앞 절은 **fixture 경계값**과 **DB 불변식 신설**까지였다. 지시에 따라 남은 둘을 마쳤다:
파서 테스트의 **보호력을 mutation 으로 검증**하고, `case_no` 의 **downstream 을 추적**했다.

## A. Mutation — `test_normalizer.py` 는 공백이 아니다 (3/3 검출)

```
M1  normalize_date 의 실패 폴백을 `return date_str` -> `return ""` 로
    -> 4건 실패:  '2026-8-19'->''  ·  '20260819'->''  ·  'abc'->''
                  + "미정규화 값은 문자열 비교를 깨뜨린다" 검사까지 함께 붉어짐
M2  normalize_price 의 `price_str.split("(")[0]` 제거
    -> 3건 실패:  '500000000원(100%)' -> **500000000100**   (명백한 데이터 오염)
                  '감정가 500,000,000 (70%)' -> 50000000070
M3  normalize_case_no 의 `.strip()` 제거
    -> 3건 실패:  '  2024타경1234 ' 보존 · None AttributeError 계약 ·
                  mylist_import 와의 동치 검사
복원 후 82건 통과
```

세 mutation 모두 잡혔다 → **테스트 공백 없음**. 파서 계약은 충분히 보호된다.

## B. `case_no` downstream 추적 — 식별자가 갈라질 수 있는가

`case_no` 는 `UNIQUE(court_code, case_no, item_no)` 의 일부라 **표기가 흔들리면 같은
사건이 두 행**이 된다. `normalize_case_no` 는 양끝 공백만 털고 내부는 원천을 믿는다
(그것이 의도다 — 타경이 아닌 사건부호를 버리지 않기 위해).

실데이터로 확인했다(distinct 1,381개).

```
양끝 공백 / NBSP / ZWSP / ZWNJ / ZWJ / BOM / 전각공백 / TAB   전부 0건
전각 숫자                                                    0건
내부 공백('타 경', '2024 타경')                               0건
공백만 제거하면 같아지는 서로 다른 case_no 그룹                 0건   <- 중복 식별자 후보 없음
```

병합 표기(`" / "`)는 **269건(19.5%)** 으로 실제로 많이 쓰인다. 순서가 바뀌면 식별자가
갈라지는데, 그 축은 **이미 가드가 있다** — `test_pipeline_integrity.py:3007`
`test_merged_case_component_order_does_not_split_identity()` 와
`detect_merged_case_duplicates_dryrun.py:canon_case()`(순서 무관 정규형).
Sprint 285 가 다룬 영역이라 여기서 반복하지 않았다.

## C. `parse_image_alt` — 다음 순수 파서

`crawler/*` 의 `parse_basic_info` 계열은 selenium `driver` 를 받아 fixture 가 어렵지만,
`crawler/image_assets.py:parse_image_alt` 는 **순수 함수**라 직접 찔렀다.
`seq` 는 `auction_image.seq`(UNIQUE 의 일부)이자 서빙 URL 의 일부라 식별자다.

```
'전경도_1'          -> ('전경도', 1)        '전경도_0' / '_-1'     -> None (거부)
' 전경도 _ 3 '      -> ('전경도', 3)        '_1' / '전경도_'       -> None
'전경도_1_2'        -> ('전경도_1', 2)      '전경도_1.5'           -> None
'ico_new_window.png'-> None (아이콘 제거)   '' / None              -> None
'전경도_999999999'  -> ('전경도', 999999999)
'전경도_１' (전각)   -> ('전경도', 1)   ★   '전경도_١'(아랍) -> 1  ★   '전경도_01' -> 1
'../../etc_1'      -> ('../../etc', 1)  ★ kind 에 경로 문자가 들어간다
```

★ 두 가지를 확인했고 **둘 다 실질 위험이 아니다.**

```
전각/선행0 -> 같은 seq        한 페이지에서 반각과 전각이 섞여야 충돌한다. 실데이터 seq 는
                              1~5 뿐이고, `save_auction_images` 가
                              `DELETE ... WHERE seq NOT IN (...)` 로 매 수집마다 정리한다.
kind 의 경로 문자             파일명은 kind 가 아니라 **seq 로 만든다**
                              (`image_filename(seq, ext)` = "%02d.%s") — 경로 조작 불가.
                              kind 는 DB 저장 + 화면 alt 텍스트로만 쓰이고 React 가 이스케이프한다.
실데이터                      kind 4종(전경도/내부구조도/위치도/관련사진) · seq 1~5 ·
                              경로문자 포함 0건
```

**Mutation**: `if seq <= 0: return None` 가드 제거
→ `test_asset_pipeline.py` 2건 실패(`('전경도', 0)` 기대 `None`) → 복원. 보호력 확인.

## D. 이 추가분의 결론

```
발견한 결함        0   (A~C 전부 방어가 성립)
추가한 가드        0   (기존 테스트가 이미 mutation 을 잡는다 — 중복 테스트를 만들지 않았다)
수정한 코드        0
```

앞 절에서 신설한 **날짜/금액 DB 불변식 3축**이 이번 세션의 유일한 실질 변경이다.
