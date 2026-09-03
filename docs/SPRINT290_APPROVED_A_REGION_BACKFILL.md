# Sprint 290 — [승인 A] 지역 오염 백필 실행 (2026-09-03)

> **CEO 승인**: *"승인 A 진행해줘 — 지역 오염 백필"*
> 이 세션에서 **운영 `auction.db` 에 실제로 썼다.** 승인 범위는 `sido` / `sigungu` 두
> 컬럼의 지역 오염 복구뿐이며, 그 밖의 어떤 표·컬럼·스키마도 건드리지 않았다.
>
> ```
> 백업        auction.db.backup_before_region_backfill_20260903_141457
>             md5 c0e47b21bed535b371aca87b9cb4366a  (백필 직전 스냅샷, integrity ok, 복구 가능 확인)
> 백필 후     auction.db  md5 58544d77562aecdbc2880349839b4c34
> 변경        424건 (auction 212 + auction_item 212), sido/sigungu 외 **0건**
> ```

---

## 1. 오염의 정의 (실측으로 확정)

`auction_item` / `auction` 의 `sido` · `sigungu` 는 `full_address` 에서 **결정적으로**
유도되는 파생값이다. "오염" 은 *저장된 값이 지금 규칙으로 다시 계산한 값과 다른 것*이고,
실측 결과 세 가지 모양뿐이었다.

| Pattern | Rows (표당) | Evidence | Repairable |
|---|---:|---|---|
| `WRONG_VALUE_SUBSTRING_MISMATCH` (sido) | 4 | 도로명/건물명 속 지명을 시도로 오독 — "**서울**대학로", "**부산**대학로", "뉴**서울**아파트", "**세**화리" | **YES** — 같은 행 `full_address` 에서 재계산 |
| `OLD_FORMAT_PREFIX_EXPAND` (sigungu) | 207 | 저장값이 새 값의 **접두**("고양시" ⊂ "고양시 일산동구"). 그 외 형태 0건 | **YES** — 정보가 줄지 않는 확장 |
| `CONTAMINATION_NOT_IN_ADDRESS` (sigungu) | 1 | 저장값이 **주소 원문(대괄호 제외)에 아예 없다**(`'갑구'` ← 등기부 용어 오독) | **YES** — 삭제(빈 값) |
| (참고) 새 값이 비어 건너뜀 | 0 | — | 해당 없음 |

정상 행: sido 1,872 / sigungu 1,668. NULL·빈값 행(sido 3 / sigungu 13)은 **건드리지 않았다.**

구분해서 다뤘다 — **물건 소재 지역**(`auction_item.sido/sigungu`, 주소 파생)만 대상이고,
`court_name`(법원 소재), `case_no`(사건 식별), 사용자 검색 필터는 전부 범위 밖이다.

---

## 2. Root Cause

```
크롤러 → parse_basic_info → normalizer.normalize_address → auction → migrate_execute → auction_item → API → 화면
                                    ↑
                          여기가 옛날에 틀렸다(부분 문자열 오매칭)
```

- **원인 지점은 정규화기 하나**이고, **이미 고쳐져 있다.** 네 주소를 지금 코드에 넣으면
  전부 옳은 값이 나온다(실행 확인: 인천 / 경남 / 경기 / 제주).
- `extract_sido()` 는 지금 **"가장 앞선 표기"** 규칙을 쓴다 —
  `'경기도 시흥시 서울대학로 59-21'` → `'경기'`. 이 축은 `test_normalizer.py` 가 지킨다.
- **DB 가 root cause 가 아니다.** 코드는 고쳐졌고 **데이터만 남아 있었다.**
- 왜 스스로 낫지 않았나: `migrate_execute.py:300` 의 병합은 새 크롤값이 있으면 덮으므로
  **재크롤되는 물건은 낫는다.** 그런데 오염 행 211건은 전부 **매각기일이 지나 재크롤
  대상이 아니다**(crawl_date 2026-07-06~07-27). 즉 백필하지 않으면 영구히 그대로였다.

---

## 3. Before

```
auction (1,876행)        sido 오염 4 · sigungu 오염 208 (접두 207 + 흘러든 값 1) · 정상 sido 1,872 / sigungu 1,668
auction_item (1,876행)   동일

사용자에게 보이던 증상 (실 API 실측)
  GET /api/v1/search/regions?sido=서울
      -> [..., '계양구', ..., '시흥시', ...]     ← 서울에 없는 구/시가 선택지로 떴다
  sigungu='고양시 일산동구' 검색  ->  3건
      (주소에 '일산동구' 가 있는 경기 물건은 실제 9건 — 사용자는 33%만 봤다)
```

---

## 4. Dry Run

두 경로로 **독립 계산**해 교차 확인했다.

```
내 독립 계산   auction 212 + auction_item 212 = 424
도구 dry-run   auction (sido 4 / sigungu 208) + auction_item (동일) = 424   ← 일치
```

산출물: `backfill_dryrun.csv` (424행 — table/id/column/before/after/reason/confidence/
evidence_full_address/evidence_address_wo_brackets). 전 건 confidence **HIGH**,
근거는 전부 **같은 행의 `full_address`** 다(외부 입력·추정 0건).

```
예:
 auction_item  550  sido     '서울' -> '인천'            WRONG_VALUE_SUBSTRING_MISMATCH
 auction_item   46  sigungu  '고양시' -> '고양시 일산동구'  OLD_FORMAT_PREFIX_EXPAND
 auction_item 1768  sigungu  '갑구' -> ''                CONTAMINATION_NOT_IN_ADDRESS
```

---

## 5. Backfill Result

```
[APPLIED] 424건 반영
반영 후 남은 불일치: 0건        (도구 자체 사후 검사)
Expected 424 == Applied 424   ✔
```

쓰기 방식(도구 소스 확인): 행별 `UPDATE <table> SET <col>=? WHERE id=?` — WHERE 없는
UPDATE·전체 테이블 UPDATE 없음. `dong`/`lot_number` 는 불일치 0이라 **대상에서 제외**
(바꿀 것이 없는 컬럼은 UPDATE 하지 않는다).

---

## 6. After

```
1) 기대 변경 424건 중 값이 다른 것            0건   ✔
2) sido/sigungu 를 뺀 **모든 컬럼**이 바뀐 표   0개   ✔ (전 27개 표, 내용 md5 대조)
3) 잔여 드리프트/오염                        auction 0 · auction_item 0   ✔
4) integrity_check ok / foreign_key_check 위반 0 / 고아 0
   행 수: auction 1,876 · auction_item 1,876 (변화 없음)

사용자에게 보이는 결과 (실 API·실 브라우저)
  /api/v1/search/regions?sido=서울  ->  24개, **전부 실제 서울 자치구**
                                        (계양구·시흥시 사라짐 ✔)
  프런트 시/군/구 드롭다운           ->  25개 항목(전체 + 24구), 계양구·시흥시 없음 ✔
  sigungu='고양시 일산동구' 검색     ->  3건 → **9건** (주소 기준 실제 9건과 일치, 재현율 100%)
  sido 오류 4건                      ->  550=인천 · 1787=경남 · 8160=경기 · 9977=제주 ✔
```

---

## 7. Re-Crawl Verification

**"고친 뒤 다시 크롤하면 같은 오염이 재발하는가" → 아니오.** 근거는 우연이 아니라 생산자다.

```
normalize_address() 실행 결과 (지금 코드)
  "사용본거지 : 인천광역시 계양구 … 뉴서울아파트"    -> sido='인천'  ✔
  "경상남도 양산시 물금읍 부산대학로 150"          -> sido='경남'  ✔
  "경기도 시흥시 서울대학로 59-21"                -> sido='경기'  ✔
  "제주특별자치도 제주시 구좌읍 세화리 산29"        -> sido='제주'  ✔
  "경기도 고양시 일산동구 고양대로 953-9"          -> sigungu='고양시 일산동구' ✔
```

그리고 Sprint 289 에서 **실제로 돌려** 확인한 사실이 이 판정을 뒷받침한다 —
사본 DB 에서 재크롤을 재현하고 `migrate_execute.execute()` 를 실행하자 그 행이
옛 값에서 새 값으로 덮였고(자가치유), 재크롤하지 않은 대조군은 그대로였다.

즉 **새 데이터는 정상, 기존 오염은 파이프라인이 안 고침** — 그래서 이 백필이 필요했고,
백필 뒤에는 양쪽 모두 정상이다.

---

## 8. Regression Guard

**새 가드를 만들지 않았다** — 이 오염을 잡는 가드가 이미 있고, 중복을 만들지 않는 것이
이 저장소의 규칙이기 때문이다(Sprint 277).

```
test_pipeline_integrity.py §12  "저장된 정규화 결과 == 지금 코드의 결과"
   상한: sido 0 / sigungu 0 / dong 0 / lot_number 0  (불변식)
   오염 축: is_stale_contamination() 을 **불러 쓴다**(판정 규칙은 한 곳에만)
```

이번 백필로 이 가드의 관측값이 **211 → 0** 이 됐다. 즉 백필 전후로 이 가드가
붉었다가 초록이 된 것 자체가 **살아 있는 변이 검증**이다.

가드가 공허해지지 않았는지 추가 확인(오염 재주입):

```
드리프트 검출  stored='고양시'         fresh='고양시 일산동구'  ->  True  ✔
              stored='고양시 일산동구'  fresh=같음             ->  False ✔ (오탐 없음)
오염 검출      '갑구'   / 주소 "…[토지 임야 297㎡ 갑구 2번]"   ->  True  ✔
              '칠곡군' / 주소 "세종특별자치시 나성로 96"        ->  True  ✔
실 DB 재측정   드리프트 0행 / 오염 0행
```

가드 자신의 "검출기 자체 검증" 4건(합성 입력)도 그대로 통과 — 실데이터가 0이 되어도
판정이 살아 있다.

---

## 9. Data Integrity

```
행 수          auction 1,876 / auction_item 1,876 / 전 27개 표 변화 없음
PK             변화 없음
FK             foreign_key_check 위반 0
고아 행         auction_image / favorites / recent_items / auction_item→case  전부 0
다른 컬럼       ★ sido/sigungu 를 뺀 전 컬럼의 내용 md5 가 27개 표 **전부 동일**
파일 크기       5,246,976 bytes (변화 없음)
건드리지 않음   auction_id · item_id · case identity · favorite · user · auth · payment ·
               subscription · tenant PII · rights 기준 · schema · migration_history
merged-case    re-key/migration 하지 않았다(이번 승인 범위 밖)
```

---

## 10. Related Test Results

**핵심: `test_pipeline_integrity` 의 실패가 4건 → 1건으로 줄었고, 없어진 3건이 정확히
이번 백필이 노린 데이터 결함이다.**

| Test | 백필 전 | 백필 후 | 남은 이유 |
|---|---|---|---|
| `test_pipeline_integrity` | FAILED (4) | **FAILED (1)** | `filed_date: auction 컬럼 없음` = **migration 028** |
| `test_auction_identity` | 중단 | 중단 | migration 025 (`building_area`/`land_area`) |
| `test_bootstrap` | FAILED (4) | FAILED (4) | migration 021·023·025·026·028 |
| `test_schema_hygiene` | FAILED (2) | FAILED (2) | migration 021~029 미기록 + 021이 지우는 중복 인덱스 |

```
사라진 3건: sido 드리프트 4행 / sigungu 드리프트 207행 / 흘러든 오염값 1행
=> 남은 4개 파일의 실패는 **전부 migration 뿐**이다. 데이터 결함 0, 코드 결함 0.

기타 게이트
  tsc 0 · eslint 0 · npm run build 성공
  node 329건 / 325 pass / 0 fail / 4 skip
  python 통과 64 | 실패 4 | 건너뜀 3 | 판정없음 1 (단언 11,892)
  test_api_regression / test_subscription_policy / test_normalizer(82) / test_search(245)  전부 통과
```

---

## 11. Performance

백필은 **코드를 한 줄도 추가하지 않았다** — 값만 바꿨다. 새 쿼리·새 인덱스·크롤러 매
실행 시 full scan 같은 것을 만들지 않았다.

```
DB 계층 (권위 있는 측정)
  regions 쿼리 계획   SEARCH … USING COVERING INDEX idx_auction_item_sido_sigungu   (변화 없음)
  regions 중앙값      0.054ms   (백필 전 0.053ms)  = 동일

HTTP 계층 (참고)
  search20 8.60ms / search100 12.43ms / regions 6.15ms / item 7.99ms
  (백필 전 7.03 / 10.19 / 4.67 / 5.51) — 응답 크기는 전부 동일하고 지연만 ~2ms 높다.
  동시에 production build 를 돌리던 중의 측정이라 **머신 잡음**으로 본다.
  DB 계층이 동일하다는 것이 그 근거다.
```

---

## 12. 승인 범위 준수 확인

```
했다        sido/sigungu 424건 복구 · 백업 · dry-run · 사후 검증 · 가드 확인
하지 않았다  schema 변경 · migration 적용 · migration 파일 추가 · 새 dependency ·
            .env · 외부 서비스 · 다른 컬럼/표 · WHERE 없는 UPDATE · 추정 기반 UPDATE ·
            merged-case re-key · git commit/push
```
