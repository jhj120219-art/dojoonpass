# Sprint 284 — **생산자 없는 필드**와 사용자 입력 계약 (2026-09-02)

> 앞 Sprint: `docs/SPRINT283`(`docs/CURRENT_STATE.md` 내), Sprint 273(`docs/SPRINT273_*.md`)
>
> **별도 파일 이유**: Sprint 100~283 과 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md` 는
> 다른 세션의 편집 대상이라 충돌을 피했다.
>
> **실행 환경**: 매장 PC. `auction.db` 는 있으나 **migration 020 / 최신 crawl_date 2026-08-12**
> 인 낡은 개발 DB다. **실크롤 불가.** 그래서 아래 모든 항목에 검증 근거를 표시했다:
> `[실제데이터]` `[fixture]` `[static]` `[검증불가]`.

---

## 요약

| # | 무엇 | 종류 | 사용자 영향 | 근거 |
|---|---|---|---|---|
| 1 | 검색 필터가 `%` `_` 를 **와일드카드로 살렸다** | 결함(수정) | `%` 하나로 필터가 전부를 반환 | [실제데이터] |
| 2 | NFD 한글 입력이 **0건**을 냈다 (검색·가져오기) | 결함(수정) | 맥에서 복사해 붙이면 아무것도 안 나옴 | [실제데이터] |
| 3 | 양끝 공백이 **0건**을 냈다 (8개 중 7개 파라미터) | 결함(수정) | 붙여넣기 공백 하나로 결과 0 | [실제데이터] |
| 4 | `rights_summary` 위험도 필드에 **생산자가 없다** | 미배선 | 위험도 배지가 영원히 안 뜸 | [실제데이터] |
| 5 | `auction_case` 날짜 3종에 **생산자가 없다** | 미배선 | 상세 '접수일/배당요구종기일'이 영원히 `-` | [실제데이터] |
| 6 | 크롤러가 **채웠는데 버려지는** 필드 5개 | 데이터흐름 | 위 4·5 가 여기에 걸려 있다 | [static] |
| 7 | `normalize_case_no` 가 **같은 패키지에 두 판본** | Frankenstein | 합치면 `타경` 아닌 사건번호가 사라짐 | [static] |
| 8 | `parsed_document` / `rights_analysis_history` **writer 0곳** | 죽은 스키마 | 선언된 파싱 단계를 아무도 안 씀 | [실제데이터] |
| 9 | `PAGE_LOAD_TIMEOUT` 이 리터럴 `30` 으로 2곳 | 중복 상수 | 상한이 두 벌 | [static] |

---

## 1~3. 사용자 입력 계약 — 같은 뿌리의 결함 셋

세 가지 모두 **"오류도 빈 화면도 아닌 조용한 오답"** 이고, 저장소 전체·`docs/BUGS.md`
검색 결과 **선례가 없었다**.

```
수정 전 (실 DB 1,876행)              수정 후
address_detail='아파트'    94행        94행
address_detail='아_트'     94행  ->     0행   '_' 가 아무 글자 하나와 맞았다
address_detail='아%트'    187행  ->     0행
address_detail='%'       1876행  ->     0행   필터가 전부를 돌려주고 있었다
address_detail='  아파트'    0행  ->    94행   앞 공백 하나로 0건이었다
NFD('아파트')                0행  ->    94행   맥 복사 붙여넣기
```

**정본은 한 곳**이다.

* `api/constants.py:escape_like()` — `LIKE ? ESCAPE '\'` 배선 **19곳 전수**
  (`search.py` 13 / `admin.py` 2 / `favorite_import.py` 1 / `database.py` 1 / `filter_engine.py` 2)
* `api/constants.py:to_nfc()` — 검색 입구 + `parse_mylist_text()` 입구
* `api/v1/search.py:_clean_param()` — NFC + 양끝 공백을 입구 한 곳에서

`property_type` **만** 예전부터 `t.strip()` 을 하고 있었다. 여덟 중 하나만 털고 있었던 것이
이것이 정책이 아니라 **누락**이라는 근거다. (`sido` 만 우연히 멀쩡했다 — `extract_sido()`
가 문자열 *안*에서 찾기 때문이라 방어가 아니라 우연이었다.)

---

## 4~6. 생산자 없는 필드 — 이번 세션의 핵심 발견

### 무엇이 없나 `[실제데이터]`

```
rights_summary 161행 중
  risk_level / risk_reason / analysis_explanation        0 / 161
  dangerous_tenant_count / total_deposit / priority_right 0 / 161  (총 11개 컬럼)
  -> load_rights_data.py:97 이 21개 중 11개를 **리터럴 NULL** 로 넣는다

auction_case 1,384행 중
  filed_date / demand_deadline / case_type                0 / 1,384
  -> migrate_execute.py:184 가 `VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)`
```

스키마도 API 도 화면도 인덱스(`idx_rs_risk`)도 있는데 **파이프라인에 생산자가 없다.**
코드만 읽으면 "구현되어 있다"고 읽힌다.

### 왜 거기서 막혔나 `[static]`

크롤러는 `AuctionItem` 의 다섯 필드를 **채우기는 한다.** 그런데 저장하지 않는다.

```
basic_info         상세페이지의 th/td 를 **전부** 긁는다   -> 버려진다
schedule           기일 내역                             -> 버려진다
property_list      물건 목록                             -> 버려진다
appraisal_summary  감정요항 원문                          -> 버려진다
nearby_cases       인근 사건                             -> 버려진다
```

두 가지가 여기서 걸린다.

1. **case 날짜(5번)** — `parse_basic_info()` 가 표의 모든 th/td 를 담으므로, 법원
   페이지에 그 항목이 **행으로 있다면 이미 캡처되고 있다.** 난이도가 "새 크롤 설계"가
   아니라 "이미 파싱된 것을 저장"일 수 있다.
2. **validator 재현 불가** — `appraisal_summary` 는 `validation_engine` 이 크롤 시점에
   읽어 `address_mismatch` 를 판정하는 **바로 그 입력**인데 저장하지 않는다. 그래서
   `validation_reasons` 에 남은 판정을 **사후에 아무도 검증할 수 없다.**

### 이번에 하지 않은 것과 그 이유

* 위험도 판정 기준 = **법적·제품 결정** → SKIP
* case 날짜 수집 범위 = **제품 결정** + 키 존재 확인에 **실크롤 필요** → SKIP
* `basic_info` 저장 = **스키마 변경** → SKIP
* `idx_rs_risk`(항상 NULL 인 컬럼의 인덱스) 제거 = **migration** → SKIP

대신 **지금 비어 있다는 사실**을 검사로 고정했다. 배선되든 필드가 사라지든 검사가 먼저 운다.

### 운영 머신에서 확인할 항목 (실크롤 1회면 판정된다)

1. 법원 상세페이지의 `parse_basic_info()` 결과 dict 에 **접수일 / 배당요구종기일** 키가
   실제로 있는가. 있다면 키 이름이 정확히 무엇인가.
2. 없다면 그 값이 **어느 화면/탭**에 있는가 (현재 저장된 페이지 덤프 2개는 메뉴
   페이지라 근거가 되지 못했다 — `배당요구종기공고` 는 **네비게이션 링크**였다).
3. `appraisal_summary` 원문에서 `extract_sido()` 가 **감정평가법인 소재지**를 먼저
   집는지 (부산 기장군 중원타워 4세대가 전부 `addr=부산 appraisal=서울` 로 검증실패인
   실측 패턴이 있다 — 한 감정서를 공유하는 4세대라 독립 오류로 보기 어렵다).

---

## 7. `normalize_case_no` 두 판본 — 합치면 안 되는 중복

```
normalizer/normalizer.py     크롤 원천을 **믿는다**. 양끝 공백만 턴다.
normalizer/mylist_import.py  사람이 붙여 넣은 잡음에서 **뽑아낸다**.
```

같은 패키지·같은 이름이라 잘못 쓰기 쉽지만 **합쳐서도 안 된다**:

```
입력              크롤 판본        가져오기 판본
'2024타채1009'    '2024타채1009'   ''            <- 타경이 아니면 버린다
'2024타경1009-1'  '2024타경1009-1' '2024타경1009' <- 물건번호를 뗀다
```

크롤 판본을 위임하면 **타경이 아닌 사건부호의 사건번호가 통째로 빈 문자열**이 된다.
합치지 않고 `test_normalizer.py` 가 (a) 정상 표기 동일 (b) 의도된 차이를 함께 고정한다.
변이(위임)로 사망 확인.

---

## 이번 Sprint 가 추가한 검사 (9종, 전부 변이 검증)

| 검사 | 파일 | 무엇을 막나 |
|---|---|---|
| LIKE 와일드카드 문자 취급 | `test_search.py` | `%`/`_` 가 다시 와일드카드로 살아나는 것 |
| 한글 정규화(NFC/NFD) | `test_search.py` | 표현이 다르면 0건이 되는 것 |
| 양끝 공백 무시 | `test_search.py` | 붙여넣기 공백으로 0건이 되는 것 |
| NFD 붙여넣기 | `test_favorite_import.py` | 맥에서 복사한 목록이 0건이 되는 것 |
| `normalize_case_no` 두 판본 계약 | `test_normalizer.py` | 잘못된 통합으로 식별자가 갈라지는 것 |
| **버려지는 필드 데이터흐름** | `test_normalizer.py` | 배선/삭제가 조용히 일어나는 것 |
| **생산자 없는 컬럼**(§15) | `test_pipeline_integrity.py` | 빈 기능이 구현된 것처럼 보이는 것 |
| **중복 심볼 래칫** | `test_schema_hygiene.py` | 새 Frankenstein |
| **위험도 배지 null 안전** | `test_schema_hygiene.py` | `null` 을 `0` 으로 그려 **거짓 안심**을 주는 것 |

마지막 것이 가장 위험한 축이다 — 경매 권리관계에서 `null -> "위험 임차인 0명"` 은
**사용자가 돈을 잃는 방향**의 거짓말이다. `!= null` 대신 truthy/`?? 0` 을 쓰면 실패한다.

---

## 품질 게이트

```
Python   통과 62 | 실패 4 | 건너뜀 3 | 판정없음 1   단언 11,480 -> 11,685
프런트 계약  309 PASS / 0 FAIL (백엔드+Next 기동 상태)
변이       19 / 19 사망
BOM       수정 .py 15개 전부 HEAD 와 일치
```

실패 4건은 **이 머신의 기존 기준선**이다(마이그레이션 021~029 미적용 3 + 지역 백필
미적용 1). 이번 세션이 새로 만든 실패는 없다.

### 문서 드리프트 (미해소)

`docs/CURRENT_STATE.md` 의 마지막 단언 기록은 Sprint 283 의 **10,854** 인데, 이번 세션
시작 시 실측은 **11,480** 이었다. 약 626 건이 문서에 반영되지 않았다. 스프린트 번호
체계는 소유자 관례라 `CURRENT_STATE.md` 본문은 건드리지 않고 여기에만 적어 둔다.

---

## 다음 Sprint 후보

1. **운영 머신 실크롤 1회** — 위 "확인할 항목" 3가지를 판정한다. `basic_info` 에 키가
   있으면 4·5번이 스키마 추가 + 배선으로 풀린다.
2. 승인 후 **migration 021~029 + `backfill_region_normalize --apply`** — 적색 4건 해소
   (지역 드리프트 sido 4 / sigungu 207 / 오염 1).
3. **권리분석 판정 기준 정의**(제품·법무) → 그 뒤에 producer 구현.
4. 인증 화면 24건의 **렌더 기반** 뷰포트 측정 — 헤드리스 세션 주입 설계가 필요하다.
   정적 검사(13축 × TSX 30개)는 이미 인증 화면을 포함해 돌고 있다.
