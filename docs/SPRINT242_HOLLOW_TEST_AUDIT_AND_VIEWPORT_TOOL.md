# Sprint 242 — 공허한 검사를 전수로 찾고, 진짜 뷰포트 측정을 도구로 고정했다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(읽기만) / `.env` 무변경 / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이번 세션 실측

```
git             HEAD 9c1f8ed / master / origin 동기(0↔0)
auction_item    1,876행 / 기일 2026-07-06~2026-08-19 / 오늘 이후 **0건** / crawl_date 2026-08-12
auction_image   45행(물건 9개)   doc_raw 556행
document_status READY 556 / COLLECTING 5,069 / FAILED 3
document_queue  3,498행 (pending 2,753 / done 559 / SKIPPED_EXPIRED 186)
                doc_type = {spec 1166, status 1166, appraisal 1166}  ★ image 0행
favorites 0 / recent_items 36

python  통과 47 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,174)
node    143개 중 139 PASS / 1 FAIL / 3 SKIP
tsc 0 / eslint 0
```

실패 1 + 건너뜀 3 은 **같은 원인 하나**(기일 남은 물건 0건 -> 기본 검색 빈 화면)다.

---

## 1. ★ 진짜 뷰포트 측정을 도구로 고정했다 — 그리고 **새 결함을 찾았다**

### 1.1 `audit_viewport.py` 신설 (새 의존성 없음)

Sprint 240/241 은 `window.open(...)` 으로 진짜 창을 띄워 쟀지만, 그것은 **사람이
브라우저 세션 안에서 손으로** 하는 일이라 재실행이 불가능했다. 이번에 `selenium`
+ `webdriver_manager`(크롤러가 이미 쓰는 것)로 **재실행 가능한 도구**로 만들었다.

    python audit_viewport.py                # 6폭 x 전 화면
    python audit_viewport.py --width 320
    python audit_viewport.py --cookie "..." # 로그인 화면까지

### 1.2 도구가 스스로를 의심하게 만들었다 — 실제로 세 번 걸렀다

```
(a) 요청 폭 != innerWidth      Windows Chrome 최소 창 폭이 ~500px 라 320 을 요청해도
                              창은 500 이었다. 그대로면 "재지도 않고 통과"다.
                              -> UNUSABLE 로 떨어뜨리고, CDP Emulation.setDeviceMetricsOverride
                                 로 진짜 320 뷰포트를 만들었다(미디어쿼리도 그 폭으로 평가된다).
(b) 탐지기 self-test           일부러 넓은 요소를 넣어 잡히는지 매번 확인한다.
(c) Tailwind 적용 확인          CSS 가 안 붙은 화면의 "넘침 0"은 무의미하다.
```

그리고 **로그인이 필요한 화면은 통과로 세지 않는다.** 헤드리스에는 세션이 없어
`/login` 으로 튕기는데 그 단순한 화면은 당연히 넘치지 않는다. `AUTH` 로 따로 표시한다.

### 1.3 ★ 도구가 "정상"이라 답해서 도구를 의심했다 — 두 가지가 틀려 있었다

만들자마자 **Sprint 240 이 고쳤던 결함을 일부러 되돌려** 도구에 물었다.
도구는 **"결함 0"이라고 답했다.** 잡아야 할 것을 못 잡은 것이다. 원인 둘:

```
(1) --hide-scrollbars 를 쓰고 있었다
    숨김   vw=320  컨테이너 288  트랙 288    -> 안 넘친다(결함이 안 보인다)
    안숨김 vw=305  컨테이너 273  트랙 277.6  -> 넘친다(결함이 보인다)
    좁은 데스크톱 창이 더 빠듯하다. **빠듯한 쪽**으로 잠근다.

(2) 뷰포트 기준 넘침만 봤다
    Sprint 240 의 목록 카드 결함은 grid 컨테이너(273)를 트랙(277.6)이 넘긴 것인데,
    카드 오른쪽 끝(293.6)은 여전히 뷰포트(305) **안**이라 "뷰포트 밖" 검사에 안 걸렸다.
    -> **자식이 부모 박스를 넘치는가**를 새로 본다.
```

고친 뒤 다시 물으니 정확히 잡았다:

```
DIV.grid gap-4 md:grid-cols-2 xl:grid- > A.block (+5px, 부모 273 / 자식 278)
```

### 1.4 ★ 그 새 탐지기가 **아무도 몰랐던 결함**을 찾았다

정상 코드에서도 9건이 걸렸다. 조사해 보니 진짜였다.

```
카드의 [물건종류 배지] / [D-day + 하트] 줄은 justify-between 인데
오른쪽 묶음이 shrink-0 이라 줄어들지 않는다 -> **왼쪽 배지만** 계속 짜부라진다.

320px 실측:  가용 147px = 배지 37px + gap 8 + 오른쪽 110px(고정)
             "연립주택,다세대,빌라" 가 37px 안에서 **9줄**로 접힌다
             -> 한 글자씩 세로로 늘어선 기둥, 카드 높이 403px
             -> 오른쪽 묶음이 부모 박스를 7px 넘어간다
360px 3줄 / 390px 2줄 / 430px 2줄   (좁을수록 급격히 나빠진다)
```

스크린샷으로 눈으로도 확인했다 — 배지가 세로 기둥이 되고 카드 오른쪽이 텅 빈다.
**페이지가 가로로 스크롤되지는 않아서**, "가로 넘침만" 보던 이전 모든 검사가 놓쳤다.

고침은 `flex-wrap` **하나뿐**이다(색·글자크기·간격 무변경, 한 줄에 들어가면 발동하지 않는다).
`/search`·`/favorites`·`/properties/recent` 세 곳에 같은 구조가 있어 함께 고쳤다.

재측정: **전 폭에서 배지 1줄(144px)**, 카드 정상.

### 1.5 전 화면 x 6폭 재측정

```
                     320  360  390  430  900  1400
/                     OK   OK   OK   OK   OK   OK
/search?sido=서울      OK   OK   OK   OK   OK   OK
/login                OK   OK   OK   OK   OK   OK
/favorites            ---- AUTH (헤드리스 세션 없음, 통과로 세지 않음) ----
/properties/recent    ---- AUTH ----
/mypage               ---- AUTH ----
/properties/505       ---- AUTH ----

정상 18 / 결함 0 / 로그인필요(측정안함) 24 / 측정불가 0
```

AUTH 24칸은 `--cookie` 로 로그인 세션을 주면 측정된다(자격증명은 도구가 만들지 않는다 —
이미 로그인된 브라우저의 쿠키를 받아 붙일 뿐이다).

---

## 2. ★ 공허한 검사 전수 감사 — 의견이 아니라 coverage 로 쟀다

`audit_test_reality.py` 신설. 각 `test_*.py` 를 따로 coverage 로 돌려 **제품 코드에서
몇 줄을 실제로 실행했는지** 센다.

```
49개 검사 중 제품 코드 실행 0줄:  3개
              60줄 미만:         3개
나머지 43개는 수백~수천 줄을 실제로 실행한다 (최대 test_api_regression 2,152줄)
```

### 도구가 멀쩡한 검사를 "공허하다"고 부를 뻔했다

`test_runner_contract.py` 가 **실행 0줄**로 나왔다. 그런데 그 파일은 실제로
`run_python_tests` 를 import 하고 subprocess 로 돌린다 — **내 분류 목록에
`run_python_tests.py` 가 빠져 있었다.** 도구를 고치니 33줄로 잡혔다.
제품 결함으로 단정하기 전에 도구부터 확인한다는 규칙이 또 한 번 맞았다.

### 0줄 2개는 **설계상 소스만 보는 것이 옳다** — mutation 으로 확인

```
test_console_encoding.py       cp949 로 못 내보내는 출력 리터럴을 소스에서 찾는다.
                               Sprint 240 에서 내가 넣은 em-dash 를 실제로 잡았다.
test_frontend_accessibility.py 실브라우저 실측값을 **상한으로 박아 두는** 드리프트 가드.
                               mutation 3종으로 확인:
                                 mypage 의 main 랜드마크 제거    -> 잡힘
                                 검색조건 input 의 aria-label 제거 -> 잡힘
                                 썸네일 alt="" 속성 제거          -> 잡힘
                               (첫 시도는 **주석 줄**을 지운 무효 변이였다 — 알아채고 다시 했다)
```

---

## 3. ★ RunLock 에 검사가 없었다 (mutation 이 찾음)

`RunLock` 은 `storage/checkpoint.py` 에 있는데, 같은 파일의 검사
(`test_checkpoint_atomicity.py`)는 checkpoint 저장/조회만 보고 **락은 한 줄도 보지
않았다.** 락은 `test_doc_worker_recovery.py` 가 간접적으로만 지나갔다.

```
MUT-L1  O_EXCL 제거 (보고 나서 쓴다 = 경쟁 창 부활)
          -> doc_worker_recovery 만 잡음. checkpoint_atomicity 는 통과.
MUT-L2  `age_hours < stale_hours` 를 항상 거짓으로 (신선한 락도 회수)
          -> ★ **어떤 검사도 잡지 못했다.**
```

MUT-L2 가 성립하면 **실행 중인 워커의 락을 다음 실행이 빼앗아** doc_worker 두 개가
동시에 뜬다. 이 락이 막으려던 것 — Selenium 다운로드 폴더 교차 오염(한쪽이 받은
파일을 다른 쪽이 자기 것으로 착각해 **엉뚱한 물건에 연결**) — 이 그대로 일어난다.

### 검사 3종 신설 후 재-mutation

```
MUT-L1 O_EXCL 제거              -> 잡힘 (신설)
MUT-L3 락 검사 자체 무력화        -> 잡힘 (신설)
MUT-L6 신선도 검사 **둘 다** 제거 -> 잡힘 (신설)
동시성: 60라운드 x 8스레드에서 둘 이상이 동시에 잡은 라운드 **0**
```

### ★ Equivalent mutant — 억지로 고치지 않고 이유를 남긴다

```
MUT-L2  1차(빠른 경로) 신선도 검사만 제거   -> 잡히지 않는다
MUT-L4  2차(임계구역 안) 신선도 검사만 제거 -> 잡히지 않는다
MUT-L6  둘 다 제거                        -> 잡힌다
```

**둘은 의도된 이중 방어다.** 1차는 토큰을 만들기 전에 빠르게 물러나는 최적화이고,
권위 있는 판정은 회수 토큰으로 보호된 임계구역 안에서 **다시** 한다(검사와 회수 사이에
누가 정상적으로 락을 잡는 경쟁을 막기 위해서다). 그래서 **한쪽만 지우면 나머지가
그대로 막아 관측 가능한 동작이 바뀌지 않는다** — 정의상 equivalent mutant다.
여기에 검사를 더하면 오늘 기준 항상 참인 동어반복이 되므로 **더하지 않았다.**
대신 둘이 함께 사라지는 것(MUT-L6)을 잠갔다.

---

## 4. image 큐 전환 상태 — 크롤 재개 시 **모든 기존 물건**이 지나갈 경로

운영 큐는 `image` 가 **0행**이다(추가되기 전에 적재됐다). 그런데
`enqueue_documents()` 는 지금 4종을 넣는다. 즉 크롤이 재개되면 **기존 944개 물건이
`image` 행을 하나씩 새로 받고**, 그중 다수는 나머지 3종이 이미 `done` 이다.

그 전환 상태를 지나가는 검사가 없었다(기존 검사는 "처음부터 4종" 이거나 "빈 큐에 신규
적재"만 본다). 신설해서 실제 `doc_worker.main()` 으로 확인:

```
[전] 큐 3종 전부 done
[적재] image 만 pending 으로 새로 생긴다 / 이미 done 인 3종은 그대로 (되살아나지 않는다)
[처리] 이동 **1회**, 그 이동은 **엄격**(image 단독이어도 정확 일치 요구 - Sprint 230 방어 유지)
       수집한 것은 image 하나뿐 (받아 둔 문서를 다시 받지 않는다)
[재적재] 행 수 그대로 4 / done 을 되살리지 않는다 / 워커가 할 일 0 (멱등)
```

mutation:

```
MUT-I1 enqueue 가 image 를 빼먹는다   -> batching, asset_pipeline, schema_hygiene 3곳이 잡음
MUT-I2 image 도 느슨하게 진입          -> batching, asset_pipeline 2곳이 잡음
```

---

## 5. 고아 큐 비용 — 재측정 (변동 없음)

```
운영 DB 고아 큐 18행
  종결 상태 6행 / 기일 경과 12행 / ★ 기일이 남은 것 **0행**
-> 지금 실제 낭비 0. 정리 시급성 낮음.
```

비용 모델(Sprint 241 에서 실측해 `cleanup_orphans_dryrun.py` 3-b 절에 넣은 것)은 그대로다 —
**기일이 남은 고아 1행 = 하루 3회 이동**, 기일이 지날 때까지 매일 반복.
삭제는 승인 영역이라 하지 않았다.

---

## 6. Backlog E — 상세 API 중복 필드: **삭제하지 않는다**

```
/api/v1/item/{id} 가 sido/sigungu/dong 을 내보낸다
  상세 TS(AuctionItemDetail) 에 선언 없음 / 상세 JSX 사용 없음
그러나 같은 이름의 필드가 **목록/관심물건/최근본에서는 실제로 쓰인다**
  full_address || [sido, sigungu, dong].join(' ')   <- 주소 폴백
상세 응답의 그 필드를 단언하는 검사는 없다(= 지워도 검사는 안 운다)
```

**그래도 지우지 않는다.** (1) 형제 엔드포인트와 모양을 맞추는 값이고, (2) 지우는 것은
API 파괴적 변경인데 얻는 것이 없으며, (3) TypeScript 인터페이스는 응답을 남김없이
선언할 의무가 없다. 정리안만 남긴다.

덧붙여 확인한 것: 상세는 `full_address || '주소 미확인'` 폴백이 이미 있고,
운영 데이터 1,876건 중 `full_address` 가 빈 물건은 **0건**이라 그 경로는 현재 도달하지 않는다.

---

## 7. 이번 세션 mutation 감사 종합

```
변이                                              결과    잡은 곳
MUT-I1 enqueue 가 image 누락                       잡힘   batching / asset_pipeline / schema_hygiene
MUT-I2 image 도 느슨하게 진입                       잡힘   batching / asset_pipeline
MUT-A2 mypage main 랜드마크 제거                    잡힘   frontend_accessibility
MUT-A3 폼 aria-label 제거                          잡힘   frontend_accessibility
MUT-A4b 썸네일 alt 속성 제거                        잡힘   frontend_accessibility
MUT-L1 O_EXCL 제거                                 잡힘   checkpoint_atomicity(신설) / doc_worker_recovery
MUT-L3 락 검사 무력화                               잡힘   checkpoint_atomicity(신설)
MUT-L6 신선도 검사 2개 동시 제거                     잡힘   checkpoint_atomicity(신설) / doc_worker_recovery
카드 flex-wrap 제거 x3화면                          잡힘   source-contract(신설)
도구에서 부모넘침 탐지 제거 / 스크롤바 숨김           잡힘   source-contract(신설)

Equivalent (고치지 않고 이유 기록)
MUT-L2 / MUT-L4  신선도 검사 **한쪽만** 제거   -> 이중 방어라 나머지가 막는다(§3)
MUT-E (Sprint 241) 변경감지 종류 필터 제거     -> 차집합이 0이고 드리프트는 다른 검사가 잡는다
```

### ★ 내 mutation 루프가 한 번 거짓 "살아남음"을 냈다

카드 `flex-wrap` 제거 3종을 처음 돌렸을 때 **전부 exit 0(살아남음)** 으로 나왔다.
단독으로 다시 돌리니 정상적으로 잡혔다 — 루프 스크립트가 백업 파일 한 경로를
세 파일이 돌려쓰면서 복원이 꼬였던 것이다. **검사가 아니라 내 하네스가 틀렸다.**
"이상하면 측정 도구부터"가 이번 세션에서만 세 번 맞았다(§1.3 / §2 / 여기).

---

## 8. 최종 상태

```
python run_python_tests.py   통과 47 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,174 -> **7,230**)
                             실패 1 = test_pipeline_integrity.py (§0 데이터 신선도 가드)
node --test                  143 -> **147개** / 143 PASS / 1 FAIL / 3 SKIP
                             (FAIL/SKIP 4건은 전부 §0 그 하나)
tsc 0 / eslint 0
audit_viewport.py            정상 18 / 결함 0 / AUTH 24 / 측정불가 0

git diff --stat  13 files changed, 1078 insertions(+), 15 deletions(-)
신규 파일        audit_viewport.py, audit_test_reality.py, docs/SPRINT240~242
```

---

## 9. 승인으로 SKIP

```
1. 실제 법원 크롤 재개          <- Release Blocker 의 유일한 원인
2. 스케줄러 실제 등록
3. 고아 데이터 삭제/정리        <- §5 에서 "지금 낭비 0" 까지 확인
4. 운영 DB 변경 / 데이터 삭제
5. .env / Secret 변경
6. 외부 서비스 연동 / 외부 포맷 확정
7. 제품 디자인 확정 / 큰글씨 최종 디자인
8. 모바일 실기기 검증
9. git add / commit / push
```

## 10. Release Blocker

```
[P0] 크롤 정지 -> 기일이 남은 물건 0건 -> 기본 검색이 빈 화면
     코드는 정상(fixture 로 전 검사 통과 확인). 크롤 재개는 승인 영역.
```

그 외 P0 없음.

## 11. 남은 Backlog / 다음 Sprint

```
A. `audit_viewport.py --cookie` 로 로그인 화면 24칸을 실제로 재기
   (지금은 AUTH 로 남아 있다 — 통과로 세지 않았을 뿐 측정된 것도 아니다)
B. `audit_test_reality.py` 의 "60줄 미만" 3개(test_crawl_resume / test_crawl_exit_code /
   test_checkpoint_atomicity)를 mutation 으로 마저 판정
C. 크롤 재개 후 image 4종 체제의 **실제** 처리량 재측정
   (§4 로 전환 경로는 검증했지만 실벽시계 시간은 실크롤이 필요하다)
D. test_doc_worker_recovery / test_race_conditions 의 이름 대비 커버 범위 어긋남
   (다른 스위트가 잡으므로 구멍은 아니다 — 중복을 늘리지 않는 선에서 정리 판단)
E. 상세 응답 중복 필드 정리는 **하지 않기로** 결론(§6). 재론 시 이 문서를 근거로.
```
