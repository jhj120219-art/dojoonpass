# Sprint 288 — P1 독립 재감사: 앞 세션 결론을 **다시 재서** 판정했다 (2026-09-03)

> **실행 환경**: 데스크탑3(개발/QA). `auction.db` 는 migration 020 까지 적용된 개발 데이터
> (물건 1,876 / 사건 1,384 / 최신 crawl_date 2026-08-12). **운영 판정으로 읽지 않는다**(BUGS #200).
>
> **`auction.db` 에 대한 정직한 기록** — md5 는 세션 중 바뀌었다
> (`ccff8761…` → `6c9a93ec…`). 원인을 끝까지 확인했고, **내 검증 작업이 쓴 것은 아니다**:
>
>   - `recent_items` 2행 — 로그인 상태로 `/properties/505`·`/properties/111` 을 **브라우저로
>     열어** 확인하는 과정에서 `record_view()` 가 남긴 정상 동작이다(조회 이력).
>   - 나머지 — `run_python_tests.py` 가 매 실행마다 스스로 붉게 표시하는 기존 조건이다
>     (`test_court_crawl_recovery` / `test_favorites_lifecycle` / `test_identifier_contract`
>     가 운영 산출물을 건드린다, BUGS #186/#192). 이번 세션이 만든 문제가 아니다.
>
> **생산자 검증(`load_spec_data.py`)은 사본에서만 했다** — 검증 후 실 DB 의
> `auction_case.case_type / demand_deadline / filed_date` 는 여전히 **0/1384** 이고
> `auction_case.updated_at` 최신값도 2026-08-12 그대로다(확인).
>
> 이번 세션의 지시는 *"앞 보고서의 DONE/PASS/GREEN 을 사실로 가정하지 말고 독립 재검증하라"* 였다.
> 그래서 새 기능을 만들지 않고 **P1 #8~#14 를 8단계 조건으로 다시 판정**했고,
> 변이 8건으로 가드가 공허하지 않은지 확인했다.

---

## 요약

| # | 무엇 | 종류 | 결과 |
|---|---|---|---|
| 1 | Python 실패 4건을 **실제 error output 으로** 재분류 | 판정 | 코드 결함 0건. 그중 1건은 **검사 설계 결함**이었다 |
| 2 | §15(b) 가 게이트 밖에서 DB 나이로 제품 판정 | ★ 결함(수정) | 개발 머신의 고칠 수 없는 red 3건 제거, 운영 판정은 그대로 |
| 3 | 지역 오염(BUGS #214/#224)의 **사용자 영향을 처음 계량** | ★ 측정 | 서울 드롭다운에 계양구·시흥시. 일산동구 검색이 9건 중 3건만 |
| 4 | 사건정보 생산자를 **이 머신에서** 사본 DB 로 실증 | 검증 | case_type 0→192, demand_deadline 0→187 |
| 5 | 권리분석 신뢰도를 **실 DB 전체**에 실제 함수로 통과 | 검증 | HIGH 31 / MEDIUM 1,817 / LOW 28 — 상수가 아니다 |
| 6 | 앞 세션의 이미지 주장 **정정** | 정정 | 첫 페인트에 1장만 받는다(lazy 실동작). "페이지당 2.8MB" 는 과장이었다 |
| 7 | 번들 −22.6% 를 **다시 측정**해 재현 | 재검증 | 258.4 → 200.4KB gzip (−22.4%). supabase 초기 참조 라우트 0 |
| 8 | 내 오판 2건을 증거로 되돌림 | 정정 | 모달 접근명 / crawl_date 시간대 — 둘 다 결함 아니었다 |

---

## 1. Python 실패 4건 — 기존 설명을 복사하지 않고 각각 실행했다

| 파일 | 분류 | **실제 출력이 말하는 근거** |
|---|---|---|
| `test_auction_identity` | **C 마이그레이션** | 스스로 중단한다: `[중단] auction_item 에 필요한 컬럼이 없습니다: building_area, land_area` → `025_add_auction_item_area_columns.sql`. *"중단했으므로 DB 를 전혀 건드리지 않았습니다"* |
| `test_bootstrap` | **C 마이그레이션** | 드리프트 목록이 021·023·025·026·028 그 자체다 — `favorite_notes` 표 전체 누락(026), `building_area`/`land_area` 누락(025), `auction.filed_date` 누락(028), `idx_ai_*`·`idx_minimum_bid_price`·`idx_rs_item_id` 잔존(021 이 지운다) |
| `test_schema_hygiene` | **C 마이그레이션** | `every .sql file on disk is recorded as applied: ['021_...','022_...',…,'029_...']` + 중복 인덱스 4개(021 이 지운다) |
| `test_pipeline_integrity` | **E 데이터 + C + (D 검사설계)** | 아래 §2·§3 |

**코드 결함은 0건이다.** migration 은 실행하지 않았다(승인 영역).

---

## 2. ★ 결함(수정) — 검사 하나가 게이트 밖에서 **DB 나이로 제품을 판정**하고 있었다

### 증상

`test_pipeline_integrity.py` §15 는 두 반쪽이다.

```
(a) 목록에 있는데 채워지기 시작한 컬럼   -> 판정 기준: **최근 3일 생성 행**
(b) 목록에 없는데 producerless 인 컬럼   -> 판정 기준: **표 전체** filled == 0
```

(a) 는 2026-09-03 에 이미 고쳐져 있었고, 그 주석이 이유를 정확히 적어 두었다 —
*"같은 코드가 DB 나이에 따라 뒤집히면 게이트가 아니라 소음이다."*
그런데 **(b) 는 고쳐지지 않았다.**

그래서 Sprint 285 가 `auction_case` 사건정보 3종을 `PRODUCERLESS_COLUMNS` 에서
빼는 순간(생산자가 생겼으므로 **옳은 변경**이다) 크롤을 돌리지 않는 개발 머신은
전부 즉시 붉어졌다. 그 DB 의 행은 전부 생산자가 생기기 전에 만들어졌으니 0 이 당연하다.

```
실측(2026-09-03, 데스크탑3)
  auction_case 1,384행 — 전부 2026-08-12 이전 생성
  case_type / filed_date / demand_deadline  = 0 / 1384
  -> [FAIL] 새로 생산자를 잃은 컬럼 없음: ['auction_case.case_type (0/1384)', ...]
```

이것이 §11 이 막으려던 상태 그대로다 — *"코드를 고쳐서 풀 수 있는 실패가 아니다 ―
곧 무시하게 된다."*

### 생산자는 살아 있다 (사본으로 증명)

같은 작업트리를 **사본 DB** 에 두고 이 머신의 실제 `spec.pdf` 로 `load_spec_data.py` 를 돌렸다.

```
BEFORE  case_type 0 / demand_deadline 0 / filed_date 0
AFTER   case_type 192 / demand_deadline 187 / filed_date 0
        (SPEC 적재: loaded 116 / no_spec_file 1,679 / table_found_no_rows 81)
실 DB 는 이 검증 뒤에도 case_type/demand_deadline/filed_date = 0/1384 —
        즉 사본에만 썼다(값으로 확인. md5 는 다른 이유로 바뀐다, 머리말 참고)
```

즉 붉은 원인은 **생산자 부재가 아니라 DB 나이**였다.
(`filed_date` 만 0 인 것은 그 값이 spec.pdf 가 아니라 크롤 `basic_info['사건접수']` 에서 오고,
`auction.filed_date` 컬럼이 이 머신에 없기 때문이다 — migration 028.)

### 고친 방식 — 새 규칙을 만들지 않고 **이미 있는 게이트**에 넣었다

이 저장소는 데이터 신선도에 기대는 제품 판정을 `is_operational_data()` 안에만 두도록
정해 두었고(BUGS #200), **그 목록(`GATED`)이 역할을 읽는 함수 전부를 덮는지 검사하는
메타 가드까지** 갖고 있다. §15(b) 를 그 규약에 편입했다.

```
if is_operational_data():
    check_true("새로 생산자를 잃은 컬럼 없음", not newly, sorted(newly))
else:
    print("[판정 안 함] ... 크롤이 도는 머신에서만 판정한다(통과가 아니다)")
    print("(참고) 지금 이 DB 에서 비어 있는 컬럼: ...")
    check_true("생산자 판정 대상 컬럼을 실제로 훑었다(개발 머신에서도 공허하지 않다)",
               scanned > 0, scanned)
```

**메타 가드가 내 첫 판을 거부했다** — `check` 가 아니라 `check_true` 여야 하고, `else`
쪽에도 단언이 하나는 남아야 한다("껍데기 방지"). 그 요구를 만족시키고 나서야 통과했다.
가드가 실제로 일하고 있다는 증거다.

### 검증 — 두 갈래가 모두 살아 있다

```
DOJOONPASS_DATA_ROLE=operational  ->  [FAIL] 새로 생산자를 잃은 컬럼 없음: [3개]   판정 살아 있음
(미선언, 개발)                     ->  [판정 안 함] + 비어 있는 컬럼을 그대로 출력
                                       + "실제로 훑었다" 단언은 유지

test_pipeline_integrity 실패:  5건 -> 4건   (없어진 1건이 정확히 이 허위 red)
남은 4건 = sido 드리프트 / sigungu 드리프트 / 흘러든 오염값 / filed_date 컬럼 없음
          → 전부 §3 의 데이터·마이그레이션 항목이다(진짜다)
```

---

## 3. ★ 지역 오염 — 알려진 문제였지만 **사용자 영향은 재어 본 적이 없었다**

BUGS #214/#224 는 이 드리프트를 "backfill 미적용"으로 기록해 두었다. 이번에 **화면에서
무슨 일이 일어나는지**를 처음 쟀다.

### (1) sido 4건 — 지역 드롭다운이 거짓말을 한다

네 건 전부 같은 결함 모양이다: 옛 정규화기가 **건물명·도로명 안의 지명**을 행정구역으로 읽었다.

```
id=550   "인천광역시 계양구 … 뉴서울아파트"      -> 저장 sido='서울'   (정규화기 재계산: '인천')
id=8160  "경기도 시흥시 서울대학로 59-21"        -> 저장 sido='서울'   (재계산: '경기')
id=1787  "경상남도 양산시 물금읍 부산대학로 150" -> 저장 sido='부산'   (재계산: '경남')
id=9977  "제주특별자치도 … 구좌읍 세화리 산29"   -> 저장 sido='세종'   (재계산: '제주')
```

지금 코드는 넷 다 옳게 계산한다. **저장된 값만 옛 규칙이다.**

그 결과 실제 화면(실측, 브라우저):

```
GET /api/v1/search/regions?sido=서울
  -> [..., '계양구', ..., '시흥시', ...]      ← 서울에 없는 구/시가 선택지로 뜬다
```

행 하나가 **드롭다운 선택지 하나**를 통째로 만들어 낸다 — 영향이 행 수에 비례하지 않는다.

### (2) sigungu 207건 — 같은 도시가 두 표기로 갈려 검색이 조용히 빠뜨린다

```
같은 도시가 두 표기로 저장된 곳 10개
  고양시 / 고양시 덕양구 · 일산동구 · 일산서구
  부천시, 수원시, 안산시, 안양시, 창원시, 포항시, 전주시, 천안시, 청주시 …

실측(실 API):
  sigungu='고양시 일산동구'  검색 결과 3건
  주소에 '일산동구' 가 있는 경기 물건        9건
  그중 sigungu 가 '고양시' 로만 저장된 것    6건  ← 드롭다운에서 고르면 **빠진다**
  => 사용자가 보는 결과는 실제의 33%
```

스캔 결과 오염 행의 crawl_date 는 전부 **2026-07-06 ~ 2026-07-27** 이다. 그 뒤 크롤은
새 표기를 저장하고 있고, `migrate_execute.py:300` 의 병합 규칙
(`sigungu = row["sigungu"] or existing["sigungu"]`)은 새 값이 있으면 덮으므로
**재크롤되는 물건은 스스로 낫는다.** 기일이 지나 재크롤 대상이 아닌 물건만 남는다.

### 판정

**코드 결함이 아니다.** 고치는 방법은 저장소가 이미 갖고 있다 —
`backfill_region_normalize.py --apply` (dry-run 으로 424건 변경 예정 확인).
데이터 쓰기이고 **의미가 있으려면 운영 DB 에서 돌아야** 하므로 여기서는 실행하지 않았다.
→ §9 승인 항목.

---

## 4. P1 #8~#14 — 8단계 조건으로 다시 판정

판정 기준: [1]생산자 [2]저장계약 [3]API계약 [4]프런트사용 [5]실DB값 [6]없음/오류상태
[7]회귀검사 [8]변이검증. 하나라도 없으면 DONE 아님.

### #8 이미지 갤러리 — **DONE**

```
[1] crawler/image_assets.py (alt->kind/seq, 확장자 sniff, 치수) + storage.save_auction_images
[2] auction_image UNIQUE(item_id,seq) + 사라진 seq DELETE
[5] 실DB 45행/9물건 — seq 연속 100%, 중복 0, 파일 부재 0, 0바이트 0, 물건 안 동일해시 0,
    고아 item_id 0
[3] images[] / image_count / representative_image / images_status,
    URL 규칙 정본 1곳(api/v1/thumbnails.py). thumbnail_url == url 로 **정직하게** 같다
[4] 히어로 + 썸네일 줄 + 라이트박스 + onError 폴백 + 상태 4분기
[6] 0장 1,867물건 / NO_IMAGE·FAILED 는 실DB에 없어 **실 API + 스크래치 DB** 로 확인
    (test_asset_pipeline test_api_images_status_variants)
[7] test_asset_pipeline.py
[8] 변이 2건 검출:
      READY-인데-0장 자기모순 방어 제거   -> [FAIL] 'READY' (expected 'COLLECTING')
      enqueue 4종에서 'image' 제거        -> [FAIL] ['appraisal','spec','status']
```

브라우저 실측: 상세 진입 시 이미지 요청 **1건**(seq 1). seq 2~5 는 `loading="lazy"` 로
받지 않는다. alt 는 종류별로 다르다("전경도 1" / "위치도 3" / "관련사진 5").
히어로는 578×420 로 그려지는데 원본이 522×700 이라 **확대**되는 쪽이다(과표집 아님).

*이 DB 에 `document_status` 의 IMAGE 행과 `document_queue` 의 image 행이 0 인 것은
결함이 아니다* — `storage/database.py:705` 가 `("spec","status","appraisal","image")` 를
적재하는데, 이 큐는 그 코드(Sprint 144, 2026-08-17)보다 **오래된** DB 다.

### #9 문서수집상태 배지 — **DONE**

```
[5] 실DB 어휘 = {COLLECTING 5,069 / READY 556 / FAILED 3} × {SPEC, STATUS, APPRAISAL}
    → 세 상태 모두 실데이터로 존재한다. document_status 행이 없는 물건은 0건
[3] ★ 거짓 성공을 서버가 막는다: READY 인데 서빙 파일이 없거나 0바이트면
    effective_status 를 COLLECTING 으로 낮추고 URL 을 주지 않는다(api/v1/item.py)
[4] 열 수 없는 문서는 링크가 아니라 회색 텍스트. 라벨 없는 값은 원문 노출(의도된 폴백)
[6] "파일이 없으므로 미수집" 같은 잘못된 추론 없음 — 근거는 document_status 이고
    파일 실체는 **낮추는 방향으로만** 쓴다
[7] test_queue_safety_invariants (b) 선언·(c) DB대조·(d) NO_IMAGE≠실패·(e) 화면 라벨 커버리지
[8] 변이: DOC_STATUS_LABEL 에서 FAILED 제거
      -> [FAIL] 실제로 쓰이는 상태는 전부 화면 라벨이 있다: ['FAILED']
```

### #10 권리분석 신뢰도/충돌 — **A·B DONE / C BLOCKED_APPROVAL**

**실 제품 함수(`assembleRightsAnalysis`)에 실 DB 1,876건을 통과**시켰다(로직 사본 없음).

```
confidence   HIGH 31 · MEDIUM 1,817 · LOW 28          ← 상수가 아니다
conflicts    DIRECT_CONFLICT 28 · AGGREGATION_DIFFERENCE 39
warnings     MISSING_SPEC 1,679 · MISSING_STATUS 1,715 · SPEC_NOT_PARSED 81
조합         MEDIUM/정보원없음 1,697 · MEDIUM/STATUS만 63 · MEDIUM/SPEC만 18
             MEDIUM/집계차이 39 · HIGH/일치 31 · LOW/정면충돌 28
```

`STATUS만 63 + SPEC만 18 = 81` 은 BUGS #44 가 고친 바로 그 모집단이고, 지금은 전부
MEDIUM 이다(예전에는 HIGH 였다). 회귀가 없다는 것이 실데이터로 확인된다.

브라우저 실측(item 111):

```
신뢰도  LOW
충돌    [DIRECT_CONFLICT] 현황조사서는 공실(0명)로, 매각물건명세서는 임차인 4명으로 …
정보원  STATUS ✓ 확보   SPEC ✓ 확보
```

**[8] 변이 2건 검출**

```
computeConfidence 에서 `if (!crossCheckable) return 'MEDIUM'` 삭제(BUGS #44 회귀)
  -> 6검사 실패 ("현황조사서만 있으면 HIGH가 아니다" 등)
DIRECT_CONFLICT(공실 vs 임차인) 검출 제거
  -> [FAIL] 공실(0명) vs 명세서 임차인 있음 -> DIRECT_CONFLICT / LOW
```

**C(법률/상품 위험등급)는 구현되어 있지 않고, 그것이 선언된 상태다.**
`rights_summary` 21컬럼 중 10개가 실DB 전부 NULL 이며
`PRODUCERLESS_COLUMNS` 가 그 이유를 적어 두었다 —
`risk_level`/`risk_reason`/`analysis_explanation`: **"위험도 판정 엔진이 없다 - 배지가 안 뜬다."**
화면은 "정보 없음"으로 정직하게 말한다. 등급 기준을 만드는 것은 법률 판단이므로
**승인 없이 만들지 않는다**(§9).

### #11 case 정보 — **PARTIAL**

```
case_type / demand_deadline
  [1] load_spec_data.py 가 이미 받아 둔 spec.pdf 1쪽에서 읽어 COALESCE 갱신
  [5] ★ 이 머신에서 사본 DB 로 실증: 0 -> 192 / 0 -> 187
      (실 DB 는 검증 후에도 0/1384 유지 — 사본에만 썼다는 것을 값으로 확인)
  [3] 실 API 확인: {"case_type":"부동산임의경매","demand_deadline":"2019-10-16"}
  [4] page.tsx:1061/1069 이 그대로 그린다(없으면 '-')
  [7] test_rights_data_load.py
  [8] 변이: case_type 추출 무력화 -> [FAIL] 2건    => 이 두 필드는 8/8

filed_date
  [1] 생산자 코드는 있다(normalizer.py:372 <- basic_info['사건접수'], migrate_execute.py:87~243)
  [5] ★ 판정 불가 — 이 머신에 `auction.filed_date` 컬럼이 없다(migration 028) +
      크롤이 필요하다  => BLOCKED_APPROVAL(migration) + BLOCKED_EXTERNAL_RUNTIME(크롤)
```

현재 실 DB 의 값이 전부 `-` 인 것은 **UI 결함이 아니라 적재를 아직 안 한 것**이다.
실제 적재(`load_spec_data.py` 를 운영 DB 에)는 데이터 쓰기라 승인 영역이다.

### #12 crawl_date — **DONE**

```
[1] crawler/court_crawler.py:146  datetime.today().strftime("%Y-%m-%d")
    ★ 이것이 계약 위반이 아니다 — 이 저장소는 파이썬 시각을 **naive 로컬**로 통일했고
      (`test_python_timestamps_are_naive_local` 이 utcnow()/tz-aware/astimezone() 를 실패시킨다)
      naive 로 써서 naive 로 읽어야 대칭이 성립한다. 내 첫 의심은 근거로 뒤집혔다.
[5] 실DB: NULL/빈값 0 · distinct 20일 · 전부 YYYY-MM-DD(datetime 문자열 0건)
    · 미래 날짜 0 · **auction_date 와 다른 행 458건** → 두 필드가 실제로 구별된다
[3][4] 검색·상세 응답에 실림. 상세 "최근 수집일 2026-08-12", 정렬 옵션 '수집일'
    실 API: sort_by=crawl_date asc/desc 가 auction_date 정렬과 다른 순서를 낸다(확인)
[6] null 이면 그 줄을 그리지 않는다(`{property.crawl_date && …}`)
[8] 변이: migrate_execute 의 `row["crawl_date"] or existing[...]` -> existing 고정
      -> [FAIL] crawl_date 변경 -> auction_item.crawl_date '2026-08-27' (expected '2026-09-01')
```

### #13 Number/Money Contract — **DONE**

실 모듈을 불러 경계값을 전수로 찍었다.

```
value        formatPrice  formatPriceEok  formatWon        formatBidRate
0            "-"          "0.0억"          "0원"            0    -> "0.0%"
1            "1"          "0.0억"          "1원"            0.8  -> "80.0%"
9999         "9999"       "0.0억"          "9,999원"        1.5  -> "150.0%"
10000        "1만"         "0.0억"          "10,000원"       null -> "-"
12900        "1만"         "0.0억"          "12,900원"
99999999     "10000만"     "1.0억"          "99,999,999원"
100000000    "1.0억"       "1.0억"          "100,000,000원"
null         "-"          "0.0억"          THROW            "-"
```

- `formatPrice(99999999) === '10000만'` 은 **이미 계약으로 못박혀 있다**
  (`tests/format.test.mjs`: *"1억 직전은 아직 만 단위다"*). 실 DB 에 그 구간 행은 **0건**.
- `formatWon(null)` 이 throw 하지만 **도달 불가**다: 호출부 전수 확인 결과
  nullable 인 자리는 전부 `!= null ? … : '정보 없음'` 으로 감싸져 있고,
  감싸지 않은 자리(`sub.price`/`p.amount`/`p.list_price`/`p.price`)는
  DB 가 `INTEGER NOT NULL` 이고 `/api/v1/plans` 실응답도 non-null 이다 — **nullability 불일치 없음**.
- `0` 과 `null` 구분: 실DB 에서 `appraisal_price`/`minimum_bid_price` 는 0 도 NULL 도 **0건**,
  `fail_count` 는 0 이 158건(정수 카운트라 formatPrice 대상이 아니다).
  임차인 보증금/월세는 `!= null` 로 0 과 null 을 실제로 가른다.
- [8] 변이: 만 단위 반올림 -> 내림  => 68검사 중 2건 실패("1억 경계", "만 단위는 반올림한다")

### #14 Frontend Edge / 접근성 — **DONE(현 범위)**

```
test_frontend_accessibility.py   전부 통과(자기검증 "검사가 공허하지 않다" 포함)
node 접근성/계약 검사             326건 중 실패 0

브라우저 실측
  라이트박스   role=dialog · aria-modal=true · aria-labelledby="photo-viewer-title"
               포커스가 모달 안('닫기')으로 이동 · 포커스 가능 요소 3개
  문서 뷰어     role=dialog · aria-modal=true · aria-labelledby="doc-viewer-title"
  ★ 내 첫 판정("접근명이 없다")은 `aria-label` 만 보고 내린 오판이었다 —
    소스를 확인해 `aria-labelledby` 를 찾고 철회했다. 고치지 않았다.
  404(물건)     "매물을 찾을 수 없습니다" + '검색 화면으로' 복구 링크
  빈 결과       "검색 결과가 없습니다" + 조건 완화 안내 + '조건 없이 전체 물건 보기'
                (조건 있음/카탈로그 비었음 두 갈래 중 올바른 쪽을 골랐다)
  빈 목록       관심물건 "관심물건이 없습니다" + 가져오기 동선
  이미지 alt    종류별로 다름(장식용 목록 썸네일만 alt="" + aria-hidden)

catch 전수(src/ 13곳)  — 전부 사용자에게 알리거나 침묵 이유가 주석에 있다. 무음 실패 0건
중복 API 호출          — /search 1 · /favorites 1 · /properties/recent 1 · /mypage 3(병렬)
                         · /properties/[id] 4  → 중복 0
```

---

## 5. 앞 세션 주장 재검증 — 하나는 재현, 하나는 정정

### 재현: 번들 −22.6%

```
supabase 포함 청크: 09a49uzuccsjz.js 하나 (246,737B)
그 청크를 초기 <script> 로 부르는 사전렌더 라우트: **0개** (8/8 전부 NO)

현재(clean rebuild, gzip, noModule 폴리필 포함)
  /favorites 200.4K · /favorites/import 200.3K · /mypage 199.3K
  /properties/recent 198.7K · /login 195.7K · /_not-found 191.3K · shared 181.2K
되돌린 상태(정적 import 로 변이 후 빌드)  /favorites 258.4K
=> 258.4 -> 200.4 = **-58.0K (-22.4%)**   앞 세션 수치가 재현된다
```

### 정정: "20장 카드 페이지 ≈ 2.8MB" 는 **과장이었다**

앞 세션은 20장이 전부 즉시 로드된다고 가정하고 곱했다. 실제로는:

```
브라우저 실측(20건 목록, 썸네일 있는 카드 9개)
  첫 페인트 시점에 실제로 받은 이미지 = **1장**
  나머지는 loading="lazy" 로 뷰포트에 들어올 때까지 받지 않는다
상세 갤러리(5장 보유 물건) = 요청 **1건**(대표 1장만)
```

과표집 자체는 사실이다(80×80 로 그리는데 원본 522×700, curl 실측 52~241KB, 중앙값 ~65KB).
그러나 **첫 화면을 무겁게 만들지 않는다** — 스크롤에 따라 나눠 지불된다.
따라서 이 항목은 "현재 문제"가 아니라 **미래 위험**이며,
서버측 축소는 이미 `SPRINT144_ASSET_PIPELINE.md` 가 승인 SKIP 으로 기록해 둔 항목이다
(`api/v1/item.py` 의 `_image_entry` 주석이 그 사실과 `thumbnail_url` 필드를 미리 만들어 둔 이유를 적고 있다).

---

## 6. 승인 없이 가능한 이미지 최적화 — 찾았지만 **하지 않았다**

지시가 요구한 목록을 전부 확인한 결과 **이미 되어 있다**.

```
lazy loading              목록·상세 썸네일 모두 loading="lazy" (DOM 실측)
중복 요청 방지            thumbnail_url == url 이라 히어로와 썸네일이 같은 URL = 1요청
조건부 요청               304 처리(api/v1/images.py not_modified) — 페이지 재방문 시 바이트 0
요청 시점                 대표 1장만 배치 조회(N+1 없음), 나머지는 뷰포트 진입 시
깨진 이미지               onError -> 자리를 남기지 않는다(목록) / 안내(상세)
없는 물건                 thumbnail_url=null -> 자리 자체를 만들지 않는다
```

남은 것은 **바이트를 줄이는 일**뿐이고 그것은 Pillow(미선언 의존성)가 필요하다.
`decoding="async"` 추가는 이 환경에서 효과를 신뢰성 있게 잴 수 없어 넣지 않았다
(재지 못한 최적화는 넣지 않는다).

---

## 7. 게이트

```
tsc            0
eslint         0
npm run build  성공 (clean rebuild)
node           326건 / 322 pass / 0 fail / 4 skip
python         통과 64 | 실패 4 | 건너뜀 3 | 판정없음 1 | 시간초과 0 (단언 11,888)
test_api_regression.py        ALL PASSED
test_subscription_policy.py   ALL PASSED
tests/client-bundle-boundary  6/6

제품 코드 변경  **0줄** (이번 세션)
검사 변경       test_pipeline_integrity.py +40 / -3
auction.db      md5 변경됨(ccff8761 -> 6c9a93ec). 원인 확인 완료 —
                브라우저 확인으로 생긴 recent_items 2행 + 기존에 알려진
                DB 변경 테스트 3개(BUGS #186/#192). 생산자 검증은 사본에서만 했고
                실 DB 의 사건정보 3종은 여전히 0/1384 다
```

### 실패 4건의 성격 (다시)

| | 코드 결함 | 원인 |
|---|---|---|
| test_auction_identity | 아니다 | migration 025 |
| test_bootstrap | 아니다 | migration 021·023·025·026·028 |
| test_schema_hygiene | 아니다 | migration 021~029 미기록 + 중복 인덱스(021이 지운다) |
| test_pipeline_integrity | 아니다 | 지역 오염 데이터(백필) + migration 028 |

---

## 8. 변이 검증 요약 (8건 전부 검출 후 원복)

```
1 _images_status 자기모순 방어 제거          -> test_asset_pipeline           검출
2 enqueue 4종에서 'image' 제거               -> test_asset_pipeline           검출
3 DOC_STATUS_LABEL 에서 FAILED 제거          -> test_queue_safety_invariants  검출
4 computeConfidence 단일정보원 -> HIGH       -> tests/rights-analysis (6검사)  검출
5 DIRECT_CONFLICT 검출 제거                  -> tests/rights-analysis          검출
6 load_spec_data case_type 추출 무력화       -> test_rights_data_load (2검사)  검출
7 migrate_execute crawl_date 병합 고정       -> test_migrate_incremental       검출
8 formatPrice 만 단위 반올림 -> 내림          -> tests/format (2검사)           검출
+ 내 수정 자체:  DOJOONPASS_DATA_ROLE=operational 로 §15(b) 판정이 살아 있음을 확인
                 (메타 가드가 첫 판을 거부해 형태를 바로잡았다)
전부 원복 확인 — git diff 로 제품 코드 변경 0
```

---

## 9. 승인/외부 실행이 필요한 것 (남은 전부)

```
A. [APPROVAL] 지역 오염 백필 — **가장 사용자 영향이 크다**
   명령      python backfill_region_normalize.py            (dry-run)
             python backfill_region_normalize.py --apply
   범위      이 머신 사본 기준 424건(auction 212 + auction_item 212)
   왜 승인    데이터 쓰기이고, 의미가 있으려면 **운영 DB**(데스크탑1)에서 돌아야 한다
   영향      서울 드롭다운의 계양구/시흥시 제거, '고양시 일산동구' 검색 3건 -> 9건

B. [APPROVAL] migration 021~029 (이 머신)
   효과      python 실패 4건 중 3건이 사라진다. schema 변경이라 실행 금지 규칙에 걸린다

C. [APPROVAL] load_spec_data.py 를 운영 DB 에 적재
   근거      사본에서 case_type 0->192 / demand_deadline 0->187 확인
   왜 승인    데이터 쓰기

D. [APPROVAL] 서버측 썸네일 축소 (Pillow)
   이미 SPRINT144 가 SKIP 으로 기록한 항목. 실측: 80×80 렌더 / 522×700 원본 / 중앙값 65KB
   현재 lazy 로 첫 화면 영향 없음 -> 급하지 않다

E. [APPROVAL] 권리분석 **위험등급 엔진** (risk_level / risk_reason / analysis_explanation)
   법률 판단 기준을 정하는 일이다. 코드로 만들 수 있는 종류가 아니다

F. [APPROVAL] 날짜 표기 통일
   "2026. 9. 3. 조회"(toLocaleDateString, 3곳) vs "2026-08-19 매각"(YYYY-MM-DD, 그 외 전부)
   같은 카드 안에서 두 표기가 공존한다. 어느 쪽으로 통일할지는 UX 결정이라 손대지 않았다
   (formatPrice/formatPriceEok 공존을 남겨 둔 것과 같은 판단)

G. [EXTERNAL RUNTIME] filed_date 는 운영 크롤 1회 + migration 028 이 있어야 판정된다
```
