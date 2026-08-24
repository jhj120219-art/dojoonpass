# Sprint 253 — 타임아웃이 **헤더까지만** 보호하고 있었다 + API 2차 Audit

**날짜** 2026-08-24 (Sprint 251/252 에 이어 같은 날). HEAD `ebb5816` / branch `master` /
**커밋·푸시 없음**. 운영 `auction.db` 무변경 / `.env` 무변경 / 스케줄러 등록 없음 /
실크롤 없음 / 의존성 설치 없음.

---

## 0. 기준선

```
세션 시작   python  통과 52 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,825 / 57파일)
            node    183개 / 179 PASS / 1 FAIL / 3 SKIP
세션 종료   python  통과 52 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,834 / 57파일)
            node    188개 / 184 PASS / 1 FAIL / 3 SKIP
            tsc 0 / eslint 0

오늘 크롤   실행되지 않음 (crawl_date max 2026-08-12, 예약 작업 0개) -> 승인 영역 SKIP
운영 DB     행수·integrity_check·FK 전후 동일
```

실패 1건(python·node 각 1)은 **같은 원인** — 기일 남은 물건 0건(승인 영역).

---

## 1. ★★ Sprint 252 의 타임아웃 수정에 결함이 있었다 — 본문을 보호하지 않았다

### 발견 — 자기 수정의 2차 결함을 찾다가 나왔다

Sprint 252 는 `timedFetch()` 가 `Response` 를 돌려주고 `finally` 에서 `clearTimeout` 했다.
그런데 `Response` 는 **헤더가 도착한 시점**에 나온다 — 본문(`res.json()` / `res.blob()`)은
호출부가 **그 뒤에** 읽는다. 타이머는 이미 해제된 상태였다.

헤더는 정상으로 보내고(200, `content-length: 100000`) 본문 10바이트만 보낸 뒤 연결을
유지한 채 멈추는 서버로 실측했다:

```
수정 전   REQUEST_TIMEOUT_MS = 8000 인데  14,000ms 관찰 후에도 **pending**
수정 후                                    8,009ms 에 ApiError/408
```

즉 Sprint 252 가 고치려던 실패 모양이 **한 층 아래에 그대로 남아 있었다.** 현실적인
시나리오다 — 백엔드가 응답을 흘리기 시작한 뒤 느린 쿼리에서 막히거나, 중간 프록시가
스트림 도중 죽으면 정확히 이 모양이 된다.

### 수정 — 요청 전체를 한 타이머 안에 넣는다

`timedFetch(...) -> Response` 를 `timedRequest(..., consume) -> T` 로 바꿨다.
헤더 + 상태 판정 + **본문 파싱**이 모두 같은 타이머 안에서 일어나고, 다 읽은 뒤에야
타이머를 해제한다.

```
jsonConsumer()      !res.ok 판정과 readDetail() 까지 타이머 안 (둘 다 본문을 읽는다)
fetchAuthedRaw()    본문을 arrayBuffer 로 다 받아 **새 Response** 로 돌려준다
                    -> 호출부의 res.ok / res.headers / res.json() / res.blob() 계약 그대로
                    -> 이미 호출부가 res.blob() 으로 전량을 읽으므로 메모리는 그대로다
headOk()            HEAD 라 본문이 없다. consume 은 res.ok 만 본다
```

### 같은 자리에서 고친 **두 번째 결함** — 호출부 signal 을 버리고 있었다

Sprint 252 는 `{ ...init, signal: controller.signal }` 로 호출부 signal 을 **덮어썼다.**
지금 signal 을 넘기는 화면은 없지만 `RequestInit` 은 그것을 허용하므로, 언젠가 화면이
"이동하면 이전 요청 취소"를 붙이는 순간 조용히 무시된다.

두 신호를 연결하고 **누가 먼저 끊었는지 구분**한다. 사용자 취소는 원래 `AbortError` 를
그대로 올려보낸다 — 408 로 위장하면 화면이 "서버가 응답하지 않습니다"를 띄워, 사용자가
방금 누른 취소가 장애로 보인다.

### mutation — survivor 를 하나 만나 설계를 바꿨다

```
T1 setTimeout 제거                      검출
T2 controller.signal 을 fetch 에 안 넘김  검출
T3 clearTimeout 제거                    검출
T4 호출부 signal 을 연결하지 않음         검출
T5 본문 소비를 타이머 밖으로(252 회귀)     검출
T6 사용자 취소를 408 로 위장             ★ **놓침(survivor)**
T7 이미 취소된 signal 을 무시             검출
```

T6 를 분석했다. **테스트 공백이 아니라 동등 변이(equivalent mutant)였다** —
사용자 취소만 일어난 경우엔 `timedOut` 이 false 라서 그 분기가 없어도 결국 같은
`throw err` 로 떨어진다. 판정이 갈리는 것은 **둘이 동시에 성립한 경쟁**(시한이 방금
터졌는데 사용자도 취소함)뿐이고, 그 창은 마이크로초 단위라 HTTP 테스트로 결정적으로
재현할 수 없다.

그래서 규칙만 순수 함수로 꺼냈다 — `abortReason(callerAborted, timedOut)`.
이제 `abortReason(true, true) === 'caller'` 를 직접 단언할 수 있다.

```
T6  우선순위 역전(취소보다 타임아웃 우선)   검출
T6b abortReason 무시하고 항상 408          검출
                                        -> 8/8 검출, survivor 없음
```

### 테스트 쪽에서 고친 것 두 가지

**(1) 테스트가 제품 코드의 종료에 의존하고 있었다.**
대기 지점이 "제품 타임아웃이 끝내 주기"를 기다렸다. 그래서 T1(타임아웃 제거) 변이에서
테스트가 실패하는 대신 **영원히 매달렸다**(실측: mutation 러너가 600초를 넘겨 백그라운드로
밀렸다). `withDeadline()` 을 넣어 테스트가 시한을 직접 들게 했다.

**(2) 테스트 서버가 소켓을 남기고 있었다.**
`srv.close()` 는 새 연결만 막고 기존 소켓은 살려 둔다. 이 파일의 서버는 일부러 응답을
주지 않으므로 소켓이 계속 열려 있고, Node 가 종료 시점에 그것이 끊길 때까지 기다렸다 —
**파일 하나가 318초**(개별 테스트 합은 25초). 소켓을 직접 파괴하게 바꿔 16.8초가 됐다.

### `no-store` 계약 검사도 이름을 따라 갱신했다

`test_search.py` 의 "옛 값을 보여줄 경로가 없는가" 가 `timedFetch(` 개수를 세고 있어
리팩터링 뒤 스스로 공허하다고 판정했다. 세는 대상을 `timedRequest` 로 옮겼다.
mutation 4/4 검출(headOk/fetchJSON 의 no-store 제거, 우회 맨 fetch 추가,
fetchAuthedRaw 를 맨 fetch 로).

---

## 2. API 2차 Audit — 실제 HTTP 로 전수 (★ 0건)

프롬프트 §5 항목을 살아 있는 서버에 대고 훑었다. 읽기 전용 + 인증 실패 경로만 사용했다
(운영 DB 무변경).

```
JSON 파싱        search 200 / application/json / 파싱 성공
pagination       size 0·101·1000·99999 -> 422,  size 1·100 -> 200
                 page 1·93 -> items 20, page 94 -> 16, page 95·100000 -> items 0 (오류 아님)
페이지 무결성     94페이지 전수 순회: 수집 1,876개 / **중복 0개**
IDOR             보호 라우트 10종 x (무인증 / alg=none 위조) = 20회 -> **전부 401**
쓰기 차단        POST·DELETE·PATCH 7종 무인증 -> 사용자 라우트 401, admin 라우트 500(fail-closed)
오류 누출        탐침 5종 -> Traceback / site-packages / 파일경로 / sqlite3 문자열 **0건**
SSRF/리다이렉트   외부 호스트로의 리다이렉트 0건
동시 요청        같은 GET 12회 병렬 -> 응답 1종(total·id 목록 완전 동일)
rate limiting    40연속 요청 중 429 **0건** = 미구현 (아래 §5 참고)
```

> 첫 실행에서 `items=-1` / `('ERR', 200)` 이 나온 것은 **내 탐침이 응답을 2,000바이트로
> 절단**해 JSON 파싱이 깨진 것이었다. 전량 읽기로 다시 재서 위 숫자를 얻었다 —
> 도구가 이상하면 제품보다 도구를 먼저 의심하라는 원칙 그대로다.

---

## 3. 프런트 늦은 응답(stale response) 전수 Audit — 결함 없음

타임아웃을 넣었으니 "그럼 늦게 도착한 응답이 새 화면을 덮어쓰지 않는가"가 다음 질문이다.
`src/` 전체에서 API 래퍼를 호출하는 파일을 뽑아 가드 유무를 봤다.

```
파일                              요청  useEffect  늦은응답 가드
properties/[id]/page.tsx          10    5          cancelled, ref비교, key비교
search/SearchForm.tsx              1    1          cancelled, key비교
favorites/page.tsx                 1    1          없음      <- deps [router] = 마운트 1회
mypage/page.tsx                    1    1          없음      <- deps [router]
properties/recent/page.tsx         1    1          없음      <- deps [router]
search/SearchPresets.tsx           3    1          없음      <- deps []
```

가드가 없는 넷은 **effect 의 의존성이 고정**이라(`[router]` / `[]`) 마운트 때 한 번만
돈다. 입력이 바뀌어 재실행되는 경로가 없으므로 **늦은 응답이 새 상태를 덮어쓰는 일이
구조적으로 발생하지 않는다.** 가드가 필요한 두 곳(파라미터만 바뀌어 재마운트되지 않는
`properties/[id]`, sido 마다 재조회하는 `SearchForm`)에는 이미 있다.

---

## 4. DB Audit — 중복 / 상태 전이 (★ 0건, 18항목)

```
중복            auction_item / auction / document_queue / document_status / doc_raw /
                auction_image / favorites / recent_items  -> 8개 축 전부 0
상태 값         queue: pending 2,753 / done 559 / SKIPPED_EXPIRED 186   (알려진 어휘만)
                status: COLLECTING 5,069 / READY 556 / FAILED 3
모순            READY 인데 doc_raw 없음 0 / doc_raw 있는데 READY 아님 0
                큐 done 인데 화면 COLLECTING 0 / in_progress 로 멈춘 행 0
                retry_count > 3  0 / pending 인데 retry 소진 0
                기일 남았는데 SKIPPED_EXPIRED 0 / 기일 지났는데 refresh 0
                가격 역전 0 / bid_rate 범위 밖 0
```

---

## 5. 측정으로 **기각/보류**한 것

### 큐 claim 의 TEMP B-TREE — 가설도 처방도 틀렸다

EXPLAIN 만 보고 "claim 쿼리가 2,753행을 매번 정렬한다"고 의심했다. **틀렸다.**
제품이 실제로 쓰는 쿼리(`last_attempt_at` 조건 포함)에 `ANALYZE` 를 돌린 상태로 재니,
SQLite 는 `idx_queue_priority` 를 골라 **정렬 없이** 끝낸다.

```
스케일             현재 인덱스                       복합 인덱스 추가
3,498행(대기 2,753) claim p50 0.052ms  (정렬 없음)   0.052ms  (차이 없음)
22,769행(대기 22,024) claim p50 3.745ms (TEMP B-TREE) 3.762ms  (**여전히 TEMP B-TREE**)
```

6.5배 스케일에서는 실제로 TEMP B-TREE 로 넘어가지만 3.75ms 다(워커는 물건당 ~22초를 쓴다).
그리고 내가 떠올린 처방(`(status, priority, auction_date, last_attempt_at)` 복합 인덱스)은
**아무 효과가 없었다** — SQLite 가 여전히 `idx_queue_status` 를 골랐다.
인덱스 추가는 마이그레이션(승인 영역)인데, 그 전에 **효과가 없다는 것이 측정으로 확인됐다.**
전부 스크래치 사본에서 쟀고 운영 DB 인덱스는 3개 그대로다.

### rate limiting 미구현 — 사실만 기록

40연속 요청에 429 가 0건이다. 다만 `api_server.py` 는 `127.0.0.1` 에만 바인딩되어
인터넷에 노출되지 않는다(Sprint 20 확인). 한도값·저장소·per-IP/per-user 기준은
정책 결정이라 임의로 만들지 않는다 — **승인 영역으로 남긴다.**

### 클라이언트 retry 없음 — 의도적으로 만들지 않았다

8초 타임아웃이 생겼으니 "재시도를 넣을까"가 자연스러운 다음 질문이다. 넣지 않았다:
`postJSON`/`deleteJSON` 은 **멱등이 아니다**(결제 생성, 관심물건 등록). 무엇을 재시도해도
되는지는 엔드포인트별 판단이고 그것은 제품 결정이다.

---

## 6. 결제 경로 커버리지 구멍에서 나온 가드 1건

`api/v1/payments.py` 96% 의 미실행 14줄이 전부 오류/롤백 분기였다. 그중 350행이
눈에 걸렸다 — 바로 위에서 `plan not in VALID_PLANS` 를 이미 걸렀는데 **또** 플랜 오류를 낸다.

```
VALID_PLANS          = tuple(PLAN_CATALOG.keys())    <- 카탈로그 파생(어긋날 수 없다)
VALID_BILLING_CYCLES = (MONTHLY, YEARLY)             <- **독립 리터럴**
```

즉 새 플랜을 추가하면서 `prices` 에 `YEARLY` 를 빼먹으면, 플랜 검사는 통과하고 가격만
None 이 된다. 그때 사용자가 보는 문구는 **"구독 플랜이 올바르지 않습니다"** 다 —
가격표에 구멍이 난 것인데 플랜을 잘못 고른 것처럼 안내된다.

2026-08-24 실측: 4개 조합(BASIC/PRO x MONTHLY/YEARLY) 전부 가격이 있어 350행은
**도달 불가**다. 그 상태를 `test_subscription_policy.py` 가 못 박는다.

```
mutation  V1  PRO 의 YEARLY 가격 항목 제거          검출
          V1b BASIC 의 YEARLY 를 0원으로            검출
          V3  새 플랜을 YEARLY 가격 없이 추가        검출
          V2  VALID_PLANS 를 하드코딩 사본으로       검출     = 4/4
```

---

## 6-b. ★ 결제 상태 CAS 분기를 **결정적으로** 실행하는 회귀 신설

`_apply_webhook_event()` 의 조건부 UPDATE 실패 분기는 커버리지 0 이었다.

```
cursor = conn.execute("UPDATE payments SET status=? ... WHERE id=? AND status=?", ...)
if cursor.rowcount == 0:
    return skip("다른 요청이 먼저 상태를 바꿨습니다")
```

이 줄이 없으면 **늦게 도착한 PG 노티가 이미 환불된 결제를 다시 PAID 로 되돌린다.**
기존 검사(`test_webhook_reprocess_guard_is_structural()`)는 소스에
`WHERE id=? AND status=?` 문자열이 남아 있는지만 본다 — 그 조건이 실제로 rowcount 0 을
만들고, 그때 **상태를 보존하며** skip 으로 답하는지는 확인하지 못한다.

저장소에 이미 있던 `_InterleavingConn` 의 방식을 그대로 따라
`_PaymentsInterleavingConn` 을 만들었다(가로채는 문장만 `UPDATE PAYMENTS` 로 다르다).
UPDATE 를 대행하기 직전에 다른 커넥션으로 상태를 REFUNDED 로 바꿔 놓으면 조건부 UPDATE 는
rowcount=0 을 볼 수밖에 없다 — 확률이 개입하지 않는다.

```
검증  CAS 실패 시 skip 으로 답한다                       PASS
      skip 사유가 '다른 요청이 먼저' 임을 밝힌다           PASS
      ★ 끼어든 쪽의 상태(REFUNDED)가 보존된다            PASS
      webhook 수신 기록이 RECEIVED 로 남지 않는다         PASS

mutation  W1 CAS 조건에서 status 확인 제거(늦은 노티가 덮어쓴다)  검출
          W2 rowcount 검사 자체를 없앤다                        검출     = 2/2
```

기대값을 문자열로 베끼지 않고 제품 상수(`pay_mod.WEBHOOK_SKIPPED`)를 그대로 쓴다 —
처음에 `"WEBHOOK_SKIPPED"` 라고 적었다가 실제 값이 `"SKIPPED"` 인 것을 확인하고 고쳤다.

---

## 7. 승인 때문에 SKIP (Sprint 251/252 와 동일, 새로 해소된 것 없음)

예약 작업 3개 등록 / `.env` admin 키 / `npm install next@16.3.2` /
고아 큐·문서·다운로드 정리 / 주소 오분류 4행 UPDATE / 명암비 44곳 /
`document_status` 새 상태 / 환불 정책 / 죽은 모듈 삭제 / 추적된 DB 백업 9개 제거 /
**rate limiting 정책** / **queue claim 인덱스 마이그레이션(효과 없음으로 측정됨)**.

---

## 8. 남은 Backlog (승인 없이 가능한 것)

- `api/v1/payments.py` 의 롤백 분기 3곳(458-459, 602-603, 700-705)과
  `subscriptions.py:213-214` 는 여전히 미실행이다(754 는 §6-b 에서 해소).
  실패 주입으로 도달 가능하지만 결제 표면이 넓어 별도 회차가 맞다.
- `docs/CURRENT_STATE.md` / `docs/CHANGELOG.md` 의 Sprint 251~267 잔여 수치.
- `logs/errors.jsonl` 끝 2줄 테스트 잔재(2026-08-21).
- `crawler/doc_crawler.py` 70% / `base_crawler.py` 55% 의 나머지는 전부 Selenium 조작.

---

## 9. 이번 회차에서 스스로 저지른 실수

정직하게 남긴다.

1. **mutation 러너를 강제 종료해 `src/lib/api.ts` 가 변이 상태로 남았다.**
   그 뒤 몇 분 동안 "제품 타임아웃이 305초에 뜬다"는 이상 측정을 쫓았는데, 원인은
   제품이 아니라 **남아 있던 T2 변이**(signal 을 fetch 에 안 넘김)였다. 파일을 먼저
   확인하고서야 알았다. 이후로는 mutation 전에 `api253.SAFE.ts` 사본을 따로 떠 두고
   실행 후 그 사본으로 복원한다.
   — 부수적으로, 그 사고가 **T2 변이를 새 watchdog 가 실제로 잡는다는 것**을 보여줬다.
2. 탐침이 응답을 2,000바이트로 절단해 API 감사에서 `items=-1` / `ERR` 를 만들었다.
   전량 읽기로 다시 재서 §2 의 숫자를 얻었다.
3. **새 CAS 테스트가 운영 DB 를 오염시켰다.** `TEST_USER_WEBHOOK_CAS` 를 추가하면서
   `cleanup()` 의 사용자 목록에 넣지 않아 `payments` 7 / `subscriptions` 7 /
   `payment_webhooks` 7 / `payment_logs` 23 행이 남았다.
   **저장소의 기존 가드가 그것을 잡았다** — `test_api_regression.py` 의
   "no stray qa-* rows outside qa-reg-*" 가 `['payments=7','subscriptions=7']` 로 실패했다.
   `cleanup()` 을 보강하고(자식 -> 부모 순서, 남았는지 확인하는 집계에도 추가), 이미 샌
   행은 FK 순서대로 지웠다. 재실행 후 잔재 0 / 네 테이블 전부 0 을 확인했다.
   — 교훈: 새 `TEST_USER_*` 를 만들면 **반드시** `cleanup()` 의 목록과 잔재 집계 양쪽에
   넣는다. 코드 옆에 그 문장을 주석으로 남겼다.

---

## 10. 왜 여기서 멈추는가

```
코드      제품 결함 2건 수정(타임아웃이 본문 미보호 / 호출부 signal 무시)
테스트    node 183 -> 188, python 단언 7,825 -> 7,834
          mutation 4축 18건 **전부 검출**
          (타임아웃 8/8, no-store 4/4, 가격표 4/4, 결제 CAS 2/2)
          테스트 자체 결함 2건 수정(제품에 의존한 종료 / 소켓 누수 318초 -> 16.8초)
API       2차 감사 ★ 0건 (IDOR 20회 전부 401, 페이지 중복 0, 오류 누출 0)
DB        중복·상태전이 18항목 전부 0
프런트    늦은 응답 가드 전수 확인 — 필요한 두 곳에 이미 있고 나머지는 구조적으로 불필요
가설 기각  claim 인덱스(효과 없음) / rate limiting(정책) / retry(멱등성)
```

남은 P0 은 여전히 하나이고 그 하나가 승인 영역이다 — 크롤이 2026-08-11 이후 돌지 않아
기일 남은 물건이 0건이고, 그래서 기본 검색이 빈 화면이다.
