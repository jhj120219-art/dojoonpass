# Sprint 289 — nullability 계약을 고치고, 실패 4건을 **실험으로** 분류했다 (2026-09-03)

> **실행 환경**: 데스크탑3(개발/QA). 운영 DB·스키마·migration 을 건드리지 않았다.
> 모든 파괴적 실험은 **사본**에서 했고, 실 DB 는 여전히 migration 020 이다(확인).
>
> 이번 세션은 Sprint 288 의 재감사를 이어받아 두 가지를 끝냈다 —
> (1) "지금 DB 에 null 이 없다"로 넘어갔던 nullability 계약을 **실제로 재검색**,
> (2) Python 실패 4건을 설명이 아니라 **실험**으로 분류.

---

## 요약

| # | 무엇 | 종류 | 결과 |
|---|---|---|---|
| 1 | 화면 타입이 **API 가 줄 수 있는 null** 을 15곳에서 거부하고 있었다 | ★ 결함(수정) | 4개 화면 타입 정정 + 미보호 3곳 폴백 |
| 2 | 실패 4건을 **마이그레이션 적용 사본**에서 재실행 | ★ 실험 | 2건 완전 해소, 1건 해소, 1건은 데이터 결함으로 남음 |
| 3 | 재크롤 자가치유를 **실제로 돌려** 확인 | 실험 | 재크롤된 행은 낫고, 안 된 행은 그대로다(대조군 확인) |
| 4 | migration 021~029 가 이 DB 사본에 **깨끗이 적용**된다 | 검증 | rc=0, 9건 전부 기록, 스키마 객체 생성 확인 |
| 5 | 스키마 기반 nullability 가드 신설 | 가드 | 응답 표본이 아니라 **스키마**를 근거로 본다 |
| 6 | 내 수정이 기존 가드 하나를 무너뜨렸다 → 유도 규칙을 고쳐 **더 넓혔다** | 가드 | 감시 대상 4개 → 5개 |
| 7 | 경쟁 상태(busy 플래그) 전수 재검색 | 감사 | 실제 결함 **0건**(8개 핸들러 전부 동기 선점 + finally) |
| 8 | DB 무결성 전수 | 감사 | 고아 0 / 중복 식별자 0 / FK 위반 0 / integrity ok |

---

## 1. ★ 결함 — 화면 타입이 서버가 줄 수 있는 값을 거부하고 있었다

### 어떻게 찾았나

Sprint 288 은 `formatWon` 호출부만 보고 "nullability 불일치 없음"으로 넘어갔다.
이번 지시는 *"현재 DB 에 null 이 없다는 것만으로 통과시키지 마라. 미래 데이터가
들어오면 깨지는 계약인지 확인하라"* 였다. 그래서 **근거를 응답이 아니라 스키마**에 두고
전 엔드포인트를 다시 훑었다.

```
auction_item 에서 NOT NULL 인 컬럼 = case_no **하나뿐**
직렬화 네 곳 전부 보정 없음:
  api/v1/item.py          "court_name": row["court_name"]  …
  api/v1/search.py        row_to_item()  동일
  api/v1/favorites.py     동일
  api/v1/recent_items.py  동일
```

즉 **서버는 null 을 줄 수 있다.** 그런데 화면 타입은 그렇게 적혀 있지 않았다.

### 실증 — 추론이 아니라 실제 응답으로

사본 DB 에서 물건 하나의 11개 컬럼을 NULL 로 만들고 실제 API 를 불렀다.

```
GET /api/v1/item/505  ->  null 로 내려온 필드 11개
  item_no, court_name, property_type, full_address, appraisal_price,
  minimum_bid_price, bid_rate, auction_date, status, fail_count, validation_status
(실 DB 무변경 확인: appraisal_price NULL 행 0)
```

### 무엇이 깨졌을까 (실측한 표기)

```
formatPriceEok(null)  -> "0.0억"    ★ 감정가를 **모르는** 물건에 "0.0억" = 0원이라는 거짓말
formatPrice(null)     -> "-"        (안전)
formatBidRate(null)   -> "-"        (안전 — 이미 넓혀져 있었다)
{item.fail_count}회   -> "유찰 회"   ★ JSX 가 null 을 아무것도 아닌 것으로 그린다
VALIDATION_STATUS_LABEL[null]        ★ 인덱스 접근 (TS2538)
```

### 고친 것 (최소 변경, 값이 있을 때 동작 동일)

```
타입 정직화 4곳
  AuctionItemDetail       11개 필드
  SearchResultItem        숫자 4종 (문자열 5종은 이미 nullable 이었다)
  FavoriteItem            숫자 4종
  RecentItem              숫자 4종

미보호 지점 3곳 (tsc 가 짚어 준 곳 전부)
  상세 감정가/최저입찰가   `!= null ? … : '-'`  ← 같은 파일이 보증금·인수금액에 이미 쓰는 관문
  상세 검증상태           인덱스 접근 앞에 존재 확인
  목록 유찰횟수           `item.fail_count ?? '-'`

format.ts
  formatPrice(price: number | null | undefined)
  — **런타임은 원래 그렇게 동작하고 있었다**(`if (!price) return '-'`).
    같은 파일의 formatBidRate/formatDday 가 이미 넓혀져 있어 그 선례에 맞췄다.
```

`formatPriceEok` 은 **건드리지 않았다** — 0 을 "0.0억" 으로 그리는 것은 의도된 표기이고
(`tests/format.test.mjs` 가 고정한다), 그 기준을 바꾸는 것은 UX 결정이다. null 만
호출부에서 막았다.

### 실브라우저 재검증 — 값이 있을 때는 한 글자도 안 바뀐다

```
/properties/505   감정가 3.8억 · 최저입찰가 3.0억 · 검증상태 검증완료
/search           유찰 8회·8회·5회·5회 · 최저가율 80.0%·32.8%·51.2%
두 화면 모두 null/undefined/NaN/Invalid 문자열 0건
```

---

## 2. ★ 가드 — 응답 표본이 아니라 **스키마**를 근거로 본다 (신설)

`tests/frontend-contract.test.mjs` 의 nullability 검사는 **받은 응답에 실제로 null 이
있을 때만** 위반을 잡는다. 지금 이 DB 에는 null 이 없으므로 그 검사는 통과하면서
선언이 틀린 상태가 유지됐다 — 그것이 이번 결함이 오래 살아남은 이유다.

그래서 `tests/source-contract.test.mjs` 에 **스키마 기반** 검사를 넣었다(서버 불필요).

```
규칙   auction_item 의 컬럼이 NULL 을 허용하면, 그 컬럼을 그대로 내보내는 화면 타입도 nullable 이어야 한다
반대   스키마가 NOT NULL 인데 타입이 nullable 인 것은 위반이 아니다(더 방어적인 선언은 안전하다)
예외   INTEGER PRIMARY KEY 는 PRAGMA 가 notnull=0 으로 보고하지만 **rowid 별칭**이라 NULL 이 될 수 없다
       -> pk 플래그로 구별한다. 이 예외를 안 두면 `id: number` 를 거짓 위반으로 잡는다(실제로 그랬다)
```

**변이 검증**: `SearchResultItem.fail_count` 를 `number` 로 되돌림
→ `[FAIL] SearchResultItem.fail_count: DB 는 NULL 허용인데 선언이 \`number\`` → 원복 후 95/95 통과.

---

## 3. ★ 내 수정이 기존 가드를 무너뜨렸다 — 그리고 그 가드가 알려 줬다

`test_pipeline_integrity.py` 에는 이 불변식이 이미 있었다:

> *"프런트가 non-null 로 선언한 숫자 컬럼에 NULL 인 행이 없다"* (전수, DB 기준)
> 그리고 주석: *"프런트가 선언을 `number | null` 로 바꾸면 이 검사도 저절로 그 컬럼을 놓아 준다."*

내가 선언을 정직하게 고치자 감시 대상이 5개 → **1개(id)** 로 줄었고,
`len >= 3` 가드가 즉시 붉어졌다. **가드가 제 일을 한 것이다.**

무너뜨리는 대신 유도 규칙을 고쳤다. 지키려는 사실은 *프런트의 선언*이 아니라
**"이 숫자들이 실제로 비어 있지 않다"** 이고, 그것은 프런트가 방어적으로 바뀌어도
가치가 그대로다 — 금액이 NULL 이면 화면이 깨지진 않아도 '-' 로 **조용히** 사라지고,
그건 크롤이 가격을 못 읽었다는 신호다.

```
옛 규칙  `number` 이고 `| null` 이 없는 것          -> 4개(+id), 프런트가 방어적이 되면 무너진다
새 규칙  숫자 필드 중 **옵셔널(`?`)이 아닌 것 전부**  -> 5개, 무너지지 않는다
         (`?` 는 "서버가 안 줄 수도 있다" -> 면적 2종 제외)

감시 대상: id, appraisal_price, minimum_bid_price, bid_rate, fail_count  (4개 -> 5개로 **증가**)
단언(NULL 인 행이 없다)은 그대로.
```

**변이 검증**: 사본 DB 의 `minimum_bid_price` 를 NULL 로
→ `[FAIL] … NULL 인 행이 없다: {'minimum_bid_price': 1}` — 옛 규칙이었다면 **감시 대상에서
빠져 못 잡았을** 컬럼이다.

---

## 4. Python 실패 4건 — 설명이 아니라 **실험**으로 분류했다

migration 021~029 를 **사본**에 적용한 뒤, 저장소를 격리 복사(실 `documents/` 는 정션으로
연결)해 네 테스트를 그대로 다시 돌렸다.

```
migration 러너 결과 (사본): rc=0, 021~029 아홉 건 전부 기록
  area 컬럼 생성 ✓ / favorite_notes 표 생성 ✓ / auction.filed_date 생성 ✓
  실 DB 최신은 여전히 020 (무변경 확인)
```

| Test | 020 (현재) | **029 (사본)** | 분류 |
|---|---|---|---|
| `test_auction_identity` | FAIL(중단) | **ALL PASS** | **BLOCKED — MIGRATION** (실험으로 확정) |
| `test_bootstrap` | FAIL(4) | **ALL PASS** | **BLOCKED — MIGRATION** (실험으로 확정) |
| `test_schema_hygiene` | FAIL(7) | **FAIL(2) — 둘 다 격리 사본 아티팩트**(내가 복사에서 뺀 png/csv/html, RunLock 부재) | **BLOCKED — MIGRATION** (마이그레이션 관련 실패는 전부 사라졌다) |
| `test_pipeline_integrity` | FAIL(4) | **FAIL(3) — sido 4건 / sigungu 206건 / 오염 1건** | **FAIL — DATA DEFECT** (마이그레이션으로 안 낫는다) |

> 사본에서 sigungu 가 207 → **206** 인 것은 우연이 아니다 — 아래 §5 의 자가치유 실험에서
> 그 사본의 한 행을 재크롤 재현으로 고쳤기 때문이다. 실험끼리 값이 맞물린다.

**즉 코드 결함은 0건이고, 실제로 남는 것은 데이터 결함 하나다.**

---

## 5. 재크롤 자가치유 — 두 반쪽을 갈라서 실측했다

지시가 요구한 구분: *"새로운 데이터가 정상적으로 들어오는지"* 와
*"기존 잘못된 데이터가 어떻게 처리되는지"* 는 다른 질문이다.

마이그레이션을 적용한 사본에서 **실제로 돌렸다**(크롤러 대신, 크롤러가 쓸 값을
`normalize_address()` 로 만들어 `auction` 에 넣고 `migrate_execute.execute()` 실행).

```
대상 id=46  "경기도 고양시 일산동구 고양대로 953-9 …"
  auction.sigungu       '고양시'            (옛 규칙이 남긴 값)
  정규화기 재계산        '고양시 일산동구'    (지금 코드)
  auction_item.sigungu  '고양시'            <- 사용자가 보는 값

[재크롤 재현 + migrate_execute 후]
  auction_item.sigungu  '고양시 일산동구'    => 자가치유 **예**

대조군 id=48 (재크롤하지 않음)
  auction_item.sigungu  '고양시'            => **그대로 오염 유지**
```

**결론**
- **새 데이터**: 정상이다. 병합 규칙(`row["sigungu"] or existing[...]`)이 새 값으로 덮는다.
- **기존 오염**: 파이프라인이 고쳐 주지 않는다. 재크롤되는 물건만 낫고,
  **기일이 지나 재크롤 대상이 아닌 물건은 영원히 그대로다.**
  이 DB 의 오염 행 crawl_date 는 전부 2026-07-06~07-27 이고 기일도 전부 지났다 —
  즉 이 207건은 **자가치유 대상이 아니다.** 백필이 유일한 해법이다(승인 영역).

---

## 6. 경쟁 상태 · DB 무결성 — 실제 결함 0건

**busy 플래그 경쟁**(지시가 지목한 `await getSession()` 뒤 busy 설정 패턴):
1차로 정적 훑기를 했더니 5곳이 의심으로 나왔는데, **전부 오탐**이었다(함수 경계를
넘어 슬라이스한 탓). 코드를 직접 읽어 8개 변이 핸들러를 전수 확인했다.

```
handleToggleFavorite(상세)  if(favBusy) return -> setFavBusy(true) -> await   OK
handleToggleFavorite(목록)  동일 (주석이 그 이유를 적고 있다)                 OK
handleRegistryRequest / handleSubscribe / handlePayOverage /
handleDownloadRegistry      if(registryBusy) return -> setRegistryBusy(true) -> await
                            + 이른 return 전부 `finally` 가 해제한다           OK
FavoriteNote.save / import.runPreview / runCommit / SearchPresets.handleSave  OK
```

**DB 무결성**(실 DB, 읽기 전용)

```
integrity_check            ok
foreign_key_check          위반 0
고아 행                     8개 관계 전부 0 (auction_image/document_status/doc_raw/
                           tenant_rights/rights_summary/recent_items/favorites/auction_item→case)
식별자 중복                 auction_item(court,case,item) 0 · auction_case(court_code,case_no) 0
                           document_status(item,doc_type) 0 · auction_image(item,seq) 0
```

**인증 경계**(실 API)

```
비인증        favorites·recent-items·search-presets·registry-requests·subscriptions/me·payments  전부 401
위조 토큰      위 셋 재시도                                                                      전부 401
공개(의도)     plans·search·item·item/images·item/documents                                      200
```

---

## 7. 게이트

```
tsc            0
eslint         0
npm run build  성공 (초기 JS 변화 없음: /favorites 200.4K gzip 유지)
node           329건 / 325 pass / 0 fail / 4 skip   (326 -> 329, 신규 3검사)
python         통과 64 | 실패 4 | 건너뜀 3 | 판정없음 1 (단언 11,892)
test_api_regression / test_subscription_policy   ALL PASSED

실 DB   migration 020 유지 · 파괴적 실험은 전부 사본 · documents/ 등 원본 무사 확인
```

---

## 8. 승인 필요 (변화 없음, 근거만 강해졌다)

```
A. [APPROVAL] 지역 오염 백필 — **운영 DB에서**
   python backfill_region_normalize.py --apply
   이번에 실험으로 확정: 마이그레이션으로 낫지 않고, 재크롤로도 낫지 않는다
   (기일이 지난 물건이라 재크롤 대상이 아니다). 백필이 유일한 해법이다.

B. [APPROVAL] migration 021~029
   이번에 사본으로 **깨끗이 적용되는 것까지 확인했다**(rc=0, 9건 기록).
   적용하면 test_auction_identity / test_bootstrap 은 ALL PASS,
   test_schema_hygiene 의 마이그레이션 실패도 사라진다.

C. [APPROVAL] load_spec_data.py 운영 DB 적재 (Sprint 288 실증: 0->192 / 0->187)
D. [APPROVAL] 서버측 썸네일 축소 (Pillow) — SPRINT144 가 이미 SKIP 으로 기록
E. [APPROVAL] 권리분석 위험등급 엔진 — 법률 판단
F. [APPROVAL] 날짜 표기 통일 ("2026. 9. 3. 조회" vs "2026-08-19 매각") — UX 결정
G. [EXTERNAL] filed_date 는 운영 크롤 1회 + migration 028
H. [DEFER]    Frankenstein 전수 복구 — 지시대로 이번 세션 범위 밖
```
