# Sprint 157 — Data Flow 감사: `has_*_pdf` 플래그는 끊어진 배선이다

작성 2026-08-17. 모든 수치는 실행 결과다. 공유 문서는 다른 세션이 편집 중이라 건드리지 않았다.

**결론부터: 결함 아님. 코드를 바꾸지 않았다.** 다만 다음에 같은 것을 발견한 사람이
다시 파헤치지 않도록 추적 결과를 남긴다.

---

## 1. 왜 봤나

Sprint 156의 `sido` 결함이 "쓰는 쪽과 읽는 쪽이 어긋난" 모양이었다. 같은 모양이
더 있는지 정규화 함수부터 역추적하다가 이름이 안 맞는 필드를 봤다.

```
normalize_item() 이 만드는 키 : has_spec_pdf, has_status_pdf,  has_appraisal_pdf
auction 테이블의 컬럼         : has_spec_pdf, has_status_doc,  has_appraisal_pdf
                                              ^^^^^^^^^^^^^^ 이름이 다르다
```

`storage/database.py:128`에 경위가 적혀 있다 — "Step 9에서 `has_status_pdf` ->
`has_status_doc`으로 개명 확정". DB 층은 개명했는데 **`normalizer`/`models`는
옛 이름 그대로**다.

## 2. 추적 — 값이 어디서 끊기나

```
models/auction_item.py:24-26     has_*  기본값 False
   ↓
crawler/                          **아무도 세팅하지 않는다** (grep 0건)
   ↓
normalize_item()                  dict 에 has_spec_pdf / has_status_pdf / has_appraisal_pdf 를 담는다
   ↓
upsert_batch()                    INSERT ... VALUES (...,0,0,0,...)   ← 상수 0 을 박는다
                                  UPDATE  ... has_* 를 **아예 건드리지 않는다**
   ↓
auction.has_*                     현재 값: spec 197 / status 195 / appraisal 197 (1인 행)
                                  = 과거 어느 시점에 들어온 값에서 **얼어붙어 있다**
```

즉 배선이 **두 군데서** 끊겨 있다. 크롤러가 값을 만들지 않고, 만들어도 `upsert_batch`가
버린다. 이름 불일치(`_pdf` vs `_doc`)는 그 뒤에 있는 **세 번째** 끊김이라, 앞의 둘을
고치더라도 조용히 안 맞을 자리다.

## 3. 사용자에게 영향이 있나 — 없다

```
auction_item (API가 쓰는 테이블) 의 has_* 컬럼 :  없음
```

API는 `auction_item`을 읽고 그 테이블에는 이 컬럼이 아예 없다. 프런트(`*.ts/tsx`)에도
참조가 0건이다. **화면에 나가는 값이 아니다.**

읽는 곳은 전부 마이그레이션·일회성 스크립트다.

```
migrate_dryrun.py / migrate_execute.py   document_status 시드용 (이미 실행 완료)
step7_* / step11_* / step16_*            일회성 점검 스크립트
```

## 4. 저장소는 이미 "이 플래그를 믿지 말라"고 결정해 두었다

`repair_document_status.py`의 머리말이 그대로 말한다.

> **판단 근거는 DB 플래그가 아니라 디스크 실물이다.** `auction.has_spec_pdf=1`은 …

실제 권위 있는 출처는 `document_status` + `doc_raw`이고, 둘은 일치한다.

```
document_status  5,628행   COLLECTING 5,069 / READY 556 / FAILED 3
doc_raw            556행   = READY 556 과 정확히 일치
```

## 5. 그래서 무엇을 했나 — **아무것도 바꾸지 않았다**

세 가지 선택지가 있었고 전부 하지 않는 쪽을 골랐다.

| 선택지 | 왜 하지 않았나 |
|---|---|
| `upsert_batch`가 플래그를 저장하게 배선 | `migrate_execute.py`가 이 컬럼으로 `document_status`를 시드한다. 값이 바뀌면 **마이그레이션 결과가 달라진다.** 제품 데이터 파이프라인 변경이라 승인 영역. |
| `normalize_item`의 키를 `has_status_doc`으로 개명 | 값이 어차피 버려지므로 **관측 가능한 동작이 0** 이다. 모델·정규화·크롤러를 건드리는 변경 대비 이득이 없다. |
| 컬럼/필드 삭제 | Architecture 결정. `/goal` 규칙에 따라 SKIP. |

`/goal`의 지침 그대로다 — "Dead Code라면 삭제가 제품/Architecture 결정에 해당하는지
판단한다. 승인이 필요하면 SKIP하고 대신 호출 경로·문서·영향 범위를 조사한다."
이 문서가 그 조사 결과다.

## 6. 함께 확인하고 넘어간 것들

- `normalize_case_no()`는 `.strip()` 뿐이고 `/search`는 `case_no LIKE ?`로 찾으므로
  Sprint 156 같은 어긋남이 없다.
- `extract_sido()`는 정상 동작한다(서울특별시/서울시/경기도/제주특별자치도/부산광역시
  전부 축약형으로 정확히 변환). Sprint 156의 문제는 함수가 아니라 **호출하지 않은 것**이었다.
- `auction` vs `auction_item` 두 테이블은 여전히 동기 상태다(키 1,876개 완전 일치,
  `auction_date` 불일치 0건 — Sprint 146 부록 J-5에서 측정한 것과 동일).

## 7. 남는 위험 (기록만)

`migrate_execute.py`를 **다시 실행하면** 얼어붙은 플래그를 기준으로 `document_status`를
시드한다. 지금은 이미 실행이 끝났고 `repair_document_status.py`가 디스크 기준으로
교정하므로 실질 위험은 없다. 다만 "새 DB를 처음부터 만드는" 절차를 밟으면
`upsert_batch`가 0을 박기 때문에 **시드가 0건이 된다**는 점은 알고 있어야 한다.

이것은 부트스트랩 절차의 문제이지 런타임 결함이 아니며, 고치려면 위 표의 첫 번째
선택지(파이프라인 변경)를 해야 하므로 승인 영역이다.

## 8. 변경 파일

```
코드 변경 0.  이 문서만 추가.
```
