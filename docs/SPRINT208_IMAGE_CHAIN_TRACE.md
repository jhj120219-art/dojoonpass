# Sprint 208 — 이미지 트리거 실행 경로 관통 조사

2026-08-18. 기준 커밋 `73ac6eb` + 미커밋 작업트리.

"코드가 존재한다 / 테스트가 있다 / 호출 경로가 있다 / **실제 실행된다**"를 분리해서 본다.
grep 으로 "호출된다"고 결론내지 않는다 — 함수·조건·파라미터·실제 값까지 따라간다.

---

## 0. 결론 먼저

체인 자체는 12단계 전부 이어져 있다. 그런데 **두 곳이 잘못 이어져 있었고**(고쳤다),
**한 곳은 사실상 절대 발동하지 않는다**(승인 영역).

| # | 단계 | 판정 |
|---|---|---|
| 1 | 실제 호출 함수 | 이어짐 |
| 2 | 호출 조건 | 이어짐 (기본 ON, 환경변수 미설정 실측) |
| 3 | 전달 파라미터 | 이어짐 |
| 4 | 변경 감지 값 | **사실상 끊김** — image 는 `appraisal_price` 에만 걸려 있고 41일간 0회 |
| 5 | Queue insert/update | 이어짐 |
| 6 | claim / retry / recovery | 이어짐 |
| 7 | collector 진입 | 이어짐 |
| 8 | partial / complete | 이어짐 |
| 9 | hash 비교 | 이어짐 |
| 10 | DB 반영 | **결함** — 성공 기록이 실체 기록보다 먼저였다 (고침) |
| 11 | API 응답 | **결함** — 자기모순을 그대로 전달했다 (고침) |
| 12 | 상세페이지 | 이어짐 — 이미 안전하게 저하되고 있었다 |

그리고 지금 이 순간 `document_queue` 의 `image` 행은 **0개**다.
그것은 코드 결함이 아니라 **적재 시점 문제**임을 사본으로 실증했다(§4).

---

## 1. 단계별로 무엇을 확인했는가

### 1~3. migrate_execute → requeue_changed_documents

```
migrate_execute.py L189   changed_items.append({court_code, case_no, item_no, fields})
                   L356   if not changed_items:            -> 아무것도 안 한다
                   L358   elif not refresh_on_change_enabled():  -> 경고만 남기고 건너뛴다
                   L363   LAST_REQUEUE = requeue_changed_documents(changed_items)
```

`refresh_on_change_enabled()` 는 `DOJOONPASS_REFRESH_ON_CHANGE` 가
`0/false/no/off` 일 때만 끈다 — **미설정이면 켬**이다. 사용자/머신 환경변수 둘 다
설정돼 있지 않음을 실측했다. 즉 별도 설정 없이 발동한다.

`changed_fields` 는 `if existing:` 분기 안에서만 계산된다 — **신규 물건은 여기 오지 않는다.**
신규는 `enqueue_documents()` 가 담당한다(§4에서 실증).

### 4. 변경 감지 값 — 여기가 사실상 끊긴 지점이다

```python
REFRESH_DOC_TYPES_BY_FIELD = {
    "auction_date":      ("spec", "status"),
    "minimum_bid_price": ("spec",),
    "status":            ("spec", "status"),
    "appraisal_price":   ("appraisal", "image"),   # <- image 는 여기 하나뿐
}
```

`image` 를 트리거하는 필드는 `appraisal_price` **하나뿐**이다. 실제로 얼마나 바뀌는가를
CSV 백업 25개(2026-07-02 ~ 08-12)로 쟀다.

관측 설계 주의(Sprint 198 교훈): 연속한 두 파일만 비교하면 같은 물건이 매일 목록에
있지 않아 0건이 나온다. **물건 키별 처음↔마지막**을 비교했다. 헤더가 다른 파일은
`.get(k,"")` 로 숨기지 않고 지목하고 제외했다(2026-07-02 한 개, 한글 컬럼).

```
두 번 이상 관측된 물건 1,228개 (분모)

  appraisal_price      변경    0건 (0.0%)     <- image 트리거
  minimum_bid_price    변경   44건 (3.6%)
  auction_date         변경   44건 (3.6%)
  status               변경   44건 (3.6%)
```

세 필드는 함께 움직인다(유찰 → 기일 재지정 + 최저가 저감). 감정평가액은 재감정이
없으면 고정이라 움직이지 않는다.

**즉 "이미지가 안 바뀌었다"가 아니라 "이미지 재수집이 발동할 수 없었다"이다.**
41일 관측에서 발동 가능 횟수가 0이다.

매핑을 넓히는 것(예: `auction_date` 에도 `image` 를 붙이기)은 **재크롤 부하와
사진 갱신 정책**을 정하는 일이라 제품 결정 — 이번 SKIP.

### 5~9. 큐 → 워커 → 수집기 → 해시

```
requeue_changed_documents()   done -> refresh        (기일 미경과 물건만)
                              SKIPPED_EXPIRED -> pending (기일이 미래로 재지정된 경우만)
doc_worker L188               needs_button = doc_type != "image"   (사진은 버튼이 없다)
           L248               collect_document(..., overwrite=overwrite)
crawler/image_crawler         _same_bytes_on_disk() 로 동일 바이트면 다시 쓰지 않는다
```

재시도 간격도 확인됐다 — 대조군 실험에서 같은 행을 즉시 다시 집지 못했다
(`RETRY_INTERVAL_MINUTES=30`, `last_attempt_at` 기준). 의도된 동작이다.

### 10. DB 반영 — **결함을 찾았다** (BUGS #140)

`doc_worker` 의 성공 분기 순서가 이랬다.

```python
mark_queue_done(...)        # 큐 done + document_status READY
save_auction_images(...)    # auction_image 행
```

뒤엣것이 실패하면 바깥 `except` 가 큐를 되돌려 재시도는 되지만
**`document_status` 는 이미 READY 로 덮여 있다.** fixture 로 재현했다.

```
worker 종료 코드   1
document_queue     pending (retry 1)
document_status    IMAGE / READY      <- 볼 수 있다고 말한다
auction_image      0행                <- 가리킬 사진이 없다
```

**문서와 사진의 비대칭이 원인이다.** 문서의 실체 기록 `doc_raw` 는
`mark_queue_done()` 이 **여는 트랜잭션 안에서** 쓰인다(`storage/database.py` L1173 주석) —
원자적이라 이 창이 없다. 사진만 `save_auction_images()` 가 트랜잭션 밖에 있었다.

**고침**: 실체를 먼저 적고 성공을 나중에 적는다. 순서만 바꿨다.

남는 창 하나는 그대로 인정한다 — 사진을 적고 `mark_queue_done()` 이 실패하면
`auction_image` 에 행이 있고 성공 표시가 없다. 그 방향은 **안전한 쪽**이다
(화면이 거짓말하지 않고, 재시도가 `INSERT OR REPLACE` 로 덮는다).
완전한 원자성은 두 함수가 커넥션을 공유해야 해서 별도 과제로 둔다.

### 11. API 응답 — **결함을 찾았다** (BUGS #141)

`api/v1/item.py:_images_status()` 는 사진이 0장일 때 `document_status` 값을
그대로 돌려줬다.

```
READY 기록 + 사진 0장 -> "READY"     <- 자기모순을 그대로 전달
```

`NO_IMAGE` / `FAILED` 는 "볼 사진이 없다"와 모순되지 않으므로 그대로 둔다.
`READY` 만 `COLLECTING` 으로 낮춘다 — 실체가 없으니 아직 끝나지 않은 것이고,
큐가 재시도 경로를 갖고 있다(행이 아예 없을 때 `COLLECTING` 이라 답하는 것과 같은 이유).

이것은 **두 번째 방어선**이다. §10 을 고쳤어도 다른 경로(예: 파일이 사라져
`save_auction_images()` 의 `saved=0`)로 같은 상태가 생길 수 있다.

### 12. 상세페이지 — 이미 안전했다

`src/app/properties/[id]/page.tsx` 는 이 순서로 분기한다.

```
sortedImages.length > 0 ? 갤러리
  : NO_IMAGE ? "법원이 이 물건의 사진을 제공하지 않습니다"
  : FAILED   ? "사진을 가져오지 못했습니다"
  :            "사진 수집 중입니다"
```

**사진 배열을 먼저 본다.** 그래서 READY+0장이어도 화면은 "수집 중"으로 저하됐다 —
사용자에게 보이는 증상은 이미 없었다. §11 의 수정은 화면을 고치는 것이 아니라
**API 가 스스로 모순된 답을 내지 않게** 하는 것이다.

---

## 4. `image` 큐 행이 0개인 것은 코드 결함이 아니다 (사본 실증)

운영 DB 를 복사해 `enqueue_documents(rows)` 를 실제로 돌렸다. 원본은 건드리지 않았고
실행 후 원본 카운트가 그대로임을 확인했다.

```
적재 전 : {appraisal: 1166, spec: 1166, status: 1166}          image 없음
입력    : auction_item 1,876건 (기일이 미래인 것 9건)
반환    : {added: 10, refreshed: 9, skipped_expired: 1866}
적재 후 : {appraisal: 1166, spec: 1166, status: 1166, image: 10}   전부 pending
```

**판정**: `enqueue_documents()` 는 `image` 를 정상적으로 넣는다.
지금 0개인 이유는 마지막 적재(2026-08-12)가 `image` 종류 추가(2026-08-17)보다
**앞서기 때문**이다. 다음 크롤 1회로 해소된다.

기일이 지난 1,866건이 걸러지는 것은 **1차 방어선의 정상 동작**이다
(매각기일이 지난 사건은 법원 사이트에서 조회 자체가 안 된다 — Step 13/14 실측).
그래서 오늘 크롤이 돌면 `image` 행은 **10개**만 생긴다. 그것이 지금 살아 있는 물건 전부다.

**그런데 크롤이 돌지 않는다** — 예약 작업 0개(Sprint 204 실측). 이 한 줄이
이미지 체인의 실질적 시작점을 막고 있다.

---

## 5. 하지 않은 것과 이유

| 하지 않은 것 | 이유 |
|---|---|
| `REFRESH_DOC_TYPES_BY_FIELD` 에 image 추가 | 사진 갱신 정책 + 재크롤 부하 = 제품 결정 |
| `save_auction_images` 를 같은 트랜잭션으로 통합 | 커넥션 공유 리팩터링. 순서 교정으로 해로운 방향은 이미 닫혔다 |
| 예약 작업 등록 | 운영 환경 변경 (승인) |
| 운영 DB 에 image 큐 수동 적재 | 운영 데이터 변경 (승인). 사본으로만 실증했다 |
