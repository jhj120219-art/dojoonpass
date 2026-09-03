# Sprint 293 — 면적 2축이 드리프트 감시 밖에 있었다 (2026-09-03, 매장 환경)

> **매장 환경 세션.** 무거운 작업을 하지 않았다 — 정적 추적 + 작은 사본 DB 검증만 했다.
> 운영 crawler 미실행, 운영 DB 미접근, 전체 빌드/전체 스위트 반복 없음.

---

## 발견

`migrate_execute.py` 의 merge 경계를 정적으로 추적하다가 찾았다.

```
full_address 에서 파생되어 저장되는 값
  sido · sigungu · dong · lot_number     <- NORMALIZE_DRIFT_CEILING 이 상한 0 으로 감시
  building_area · land_area              <- ★ 아무도 세지 않았다
```

둘은 **같은 입력에서, 같은 merge 경로로** 저장된다.

```
migrate_execute.py:355   _areas = extract_areas(full_address or "")
                         ^ 병합된 full_address (새 크롤이 비면 기존값으로 폴백된 값)
migrate_execute.py:412   UPDATE ... building_area=?, land_area=? ...
```

지역 오염(BUGS #214/#224)이 정확히 이 모양이었다 — **추출 규칙이 좋아져도 기존 행은
재계산되지 않는다.** 재크롤되는 물건만 낫고, 기일이 지나 재크롤 대상이 아닌 물건은
영구히 옛 값으로 남는다.

그리고 면적은 **검색 필터가 실제로 쓰는 값**이다
(`api/v1/search.py` 의 `min_building_area` / `max_land_area` 등). stale 이면
지역 오염이 지역 필터를 망친 것과 **같은 방식으로** 면적 필터가 조용히 틀린 결과를 낸다 —
오류도 빈 화면도 아니라 "그 조건에 물건이 없다"로 보인다.

**고치는 도구는 이미 있었다**(`backfill_area.py`). 없던 것은 **세는 사람**뿐이다.

---

## 함께 확인하고 **정정**한 것

추적 중 세운 가설 하나가 틀렸다. 기록해 둔다.

```
가설   building_area 가 `or` 병합 목록에 없으니, 새 크롤의 full_address 가 비면
       면적이 정상값에서 NULL 로 덮이지 않을까
사실   아니다. 355행이 **병합된** full_address 를 쓴다(= 폴백된 값).
       면적도 사실상 다른 13개 필드와 같은 안전성을 갖는다. 결함 아님.
```

merge 경계에서 확인한 나머지 (전부 정상):

```
`X = row["X"] or existing["X"]` 13개 필드   새 값이 비면 기존값 유지 — stale 을 만들지만
                                            정상값을 빈값으로 덮지는 않는다
fail_count / bid_rate                       병합 후 값으로 **재계산** (일관적)
auction_case.filed_date                     write-once (`WHERE ... AND filed_date IS NULL`)
                                            접수일은 불변값이라 의도가 옳다. 다만 틀린 값이
                                            한 번 들어가면 파이프라인에 고칠 경로가 없다
                                            — 이 머신은 컬럼 자체가 없어 데이터 0건이라
                                            아직 오염될 기회가 없었다(기록만)
auction_case.case_type / demand_deadline    COALESCE 로 덮어쓴다 (재수집 시 갱신됨)
```

즉 `auction_case` 세 필드가 **서로 다른 갱신 정책**을 갖는다(write-once vs last-write-wins).
둘 다 각자 근거가 있어 결함은 아니지만, 같은 표에서 정책이 갈린다는 사실은 기록해 둔다.

---

## 고친 것 — 감시 축 추가 (`test_pipeline_integrity.py` §12)

새 파일도, 새 규칙도 만들지 않았다. **정본 함수를 불러 쓴다.**

```python
from normalizer.normalizer import extract_areas   # 추출 규칙 정본 하나
```

설계상 지킨 것 두 가지:

1. **컬럼이 없는 머신에서는 판정하지 않는다** — 이 매장 머신은 migration 025 미적용이라
   `building_area` 컬럼 자체가 없다. 그때 조용히 통과시키면 "판정했다"와 "판정하지
   못했다"가 구별되지 않으므로 `[판정 안 함]` 을 명시적으로 찍는다.
2. **검출기 자체 검증은 컬럼 유무와 무관하게 항상 돈다** — 그래야 이 절이 통째로
   공허해지지 않는다.

---

## 검증 (작은 사본 DB, 실 DB 미접촉)

```
이 머신(컬럼 없음)
  [PASS] 검출기 자체 검증: 주소에서 면적을 실제로 뽑는다
  [PASS] 검출기 자체 검증: 면적이 없는 주소는 None 이다
  [판정 안 함] auction_item 에 면적 컬럼이 없다(migration 025 미적용)
  기존 실패 1건(migration 028)만 유지 — 회귀 없음

사본에 면적 컬럼을 붙여 실제로 재본 결과
  정본 함수로 백필 후 드리프트      0        <- 검사가 옳다
  면적 보유 행                     1,148 / 1,876 (61.2%)
                                   backfill_area.py 문서의 "60.0%" 와 일치
  stale 값 1행 주입 후 드리프트     1        <- 가드가 실제로 잡는다
  실 DB                            컬럼 없음 그대로 (무변경 확인)
```

---

## 남은 것

```
BLOCKED_EXTERNAL_RUNTIME  면적 드리프트의 **실제 규모**는 migration 025 가 적용된
                          머신에서만 잴 수 있다. 이 가드가 그때 자동으로 판정한다.
                          어긋남이 나오면 명령은 정해져 있다: python backfill_area.py
기록만                    auction_case.filed_date write-once — 틀린 값이 들어가면
                          파이프라인 자체에는 복구 경로가 없다(현재 데이터 0건)
```
