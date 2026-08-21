# Sprint 250 — 로그인 뒤 화면의 주소 계약을 끝까지 확인하고, 테스트 감사를 닫았다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(행수 전후 대조) / `.env` 무변경 / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이번 세션 실측

```
세션 시작   python  통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,662건)
세션 종료   python  통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,689건, 148.6s)
            node    173개 / 169 PASS / 1 FAIL / 3 SKIP
            tsc 0 / eslint 0

운영 DB (작업 전후 동일)
  auction 1,876 / auction_item 1,876 / auction_case 1,384
  document_queue 3,498 / auction_image 45 / favorites 0 / recent_items 36
```

남은 실패 1건(python·node 각 1)은 **기일 남은 물건 0건** — Release Blocker 그 자체다.

---

## 1. 주소 감사 결론 재확인 (이전 숫자를 복사하지 않고 다시 쟀다)

```
auction_item              1,876
full_address 결측/공백         0
'앞[안]' 분해 실패              0
중첩 대괄호(문자 2개)            4
```

제품 `parseArea` 를 실제로 import 해 전수 실행한 결과:

```
정상(면적 1개)     1,810  96.48%
정상(다층/대지권)      44   2.35%
불가(면적 개념 없음)   14   0.75%
불가(단위 '평')        8   0.43%
불가(대괄호 없음)       0   0.00%
----
면적 표시 가능      1,854  98.83%
```

지난 Sprint 의 1,850(98.61%) 에서 **1,854(98.83%)** 로 올랐다 — 중첩 대괄호 수정이
4건을 되살렸기 때문이다. 파싱 로직은 새로 만들지 않았고, 지금도 대괄호를 파싱하는 곳은
`src/lib/format.ts:86` **한 곳뿐**이다.

---

## 2. ★ 로그인 뒤 화면의 주소 계약 — 세 Sprint 동안 막혀 있던 것을 뚫었다

### 무엇이 막혀 있었나

`/favorites` `/properties/recent` `/mypage` `/properties/[id]` 는 세션이 필요하다.
헤드리스 브라우저에는 Supabase 세션이 없어 `/login` 으로 튕기므로, 지금까지 세 번
연속 **"API 계약은 확인했고 화면은 못 봤다"** 로 끝났다.

### 어떻게 뚫었나 — mock 이 아니라 **제품 인증 경로**로

fixture DB 를 새로 만들고, 앱이 실제로 쓰는 시크릿으로 토큰을 서명했다. 그러면
제품의 실제 `get_current_user()` 를 그대로 지난다. 전제부터 확인했다:

```
토큰이 제품 인증 경로를 통과하는가  : 예 (200)
인증 없이 부르면 막히는가          : 예 (401)
```

### 결과 — 주소 원문 불일치 0건

입력은 이 저장소가 실제로 밟았던 네 가지 모양을 그대로 넣었다.

```
중첩 대괄호   [토지 전[현황:묵전(죽림)] 105㎡ ...]
대지권 표기   [집합건물 ... 74.5482㎡ 대지권의 표시 ... 대 500㎡]
괄호+쉼표    (안락동,동래에코하임)
비부동산     사용본거지 : ... [카니발 2016년식 승용차]
```

```
관심물건      4행   주소 일치 4/4   full_address 키 있음
최근 본 물건   4행   주소 일치 4/4   full_address 키 있음
상세         4행   주소 일치 4/4
불일치 총 0건
```

주소는 **파싱되지 않고 원문 그대로** 실린다 — 어느 화면도 대괄호를 자르거나 trim 하지 않는다.

### 회귀 + mutation

`test_search.py` 에 `check_authed_screens_get_the_same_address()` 신설(7단언).
운영 DB 는 건드리지 않는다 — 임시 DB 를 만들고 끝나면 지운다(실측으로 확인: fixture
사용자 두 명 모두 운영 DB 에 0행).

```
MUT-F1  api/v1/favorites.py 응답에서 대괄호를 잘라냄(2곳)   -> [잡힘]
MUT-R1  api/v1/recent_items.py 에서 같은 변형              -> [잡힘]
```

### 아직 못 한 것 — 분명히 적어 둔다

**브라우저 실렌더는 여전히 확인하지 못했다.** 확인한 것은 API 계약(JSON)까지다.
JSX 가 그 값을 어떻게 그리는지는 소스로만 봤다. 로그인한 탭의 세션 쿠키가 있으면
`audit_viewport.py --cookie` 로 그 자리에서 잰다.

---

## 3. 테스트 감사 — 의심 목록 5개를 **전부** mutation 으로 판정했다

`audit_test_reality.py` 를 다시 돌려 제품 코드 실행량을 쟀다. 큐/회복 계열은 전부
실질적이다(mock 이 아니다):

```
test_refresh_trigger      1,652줄 / 모듈 38     test_worker_batching     633줄 / 12
test_image_queue_transition 637줄 / 12          test_doc_worker_recovery 580줄 / 16
test_scheduler_longrun      487줄 /  4          test_document_queue      288줄 /  3
```

의심 목록 5개 중 3개는 지난 Sprint 에 판정했고(전부 실질적), **남은 2개를 이번에 닫았다.**

```
test_frontend_accessibility  MUT: PrimaryNav 에 text-gray-400 추가
                             -> [잡힘] "text-gray-400 사용 횟수: 111 (상한 110)"
test_console_encoding        MUT: 출력 리터럴에 U+2014 EM DASH 삽입(구문은 정상)
                             -> [잡힘] "storage/database.py:129 U+2014"
```

두 검사는 제품 코드를 0줄 실행하지만 **드리프트 가드로서 실질적이다.**
이로써 **의심 목록 전체(5/5)가 판정 완료**다.

★ `test_console_encoding` 은 처음에 잘못 판정할 뻔했다 — 셸 이스케이프 실수로 파일에
리터럴 `\n` 이 들어가 SyntaxError 가 났고, 검사는 그걸 "파싱 실패" 로 잡았다.
그건 em dash 가드를 판정한 것이 아니다. 구문이 멀쩡한 상태로 다시 넣어 재판정했다.

---

## 4. 이미지 변경 감지 — 두 가지 mutation 으로 확인, 구멍 없음

합성 지문은 `sha256(순번순 개별해시 이어붙이기)` 다(`image_crawler.py:382`).
개별 해시가 64자 고정이라 구분자 없이 이어 붙여도 모호하지 않고, `images` 는
해시 계산 **전에** `sorted(..., key=seq)` 로 정렬된다(338행). 즉 순서는 결정적이다.

"한 장이라도 바뀌면 값이 바뀐다"는 주석의 주장을 mutation 으로 검증했다:

```
MUT-1  수집 시점 공식만 '첫 장만' 보도록      -> [잡힘] "이전 지문이 1차의 새 지문과 같다"
       (디스크 공식과 갈라져 거짓 개정이 된다 — 테스트가 그 불변식을 지키고 있었다)
MUT-2  디스크·수집 **두 공식을 함께** 바꿈     -> [잡힘] "집합 지문이 바뀐다(개정 감지)"
```

일관성 불변식을 우회해도 잡힌다. **가정했던 구멍은 없었다.**

---

## 5. 큐 / 재시도 / 회복 — 이미 촘촘하다

```
document_status  5,628행 (= 1,876물건 x 3종)  COLLECTING 5,069 / READY 556 / FAILED 3
doc_raw            556행  doc_version 전부 1
document_collect_failures  3행
```

FAILED 3건은 **한 물건(item_id=14)의 세 문서**이고 시각이 같으며 사유가
`상세페이지 진입 실패` 하나다 — 흩어진 오류가 아니라 일관된 단일 실패 기록이다.

`reset_stale_queue()` 의 계약은 코드 주석에 Sprint 78/189/210 의 실측 이력과 함께
적혀 있고, 9개 테스트 파일이 참조한다. 자동 부활 금지(SKIPPED_*), 실체 있는 행은
`refresh` 로 복귀, `document_status` 동기화까지 fixture 로 재현돼 있다.
**새로 만들 것이 없었다.**

---

## 6. 발견 — 운영 `recent_items` 에 8일 전 잔재 25행

```
recent_items 36행
   'leaked-user'                            25행   viewed_at 전부 2026-08-13
   '126e425c-91e8-...' (실사용자로 보임)        11행
favorites 0행 / search_presets 0행
```

`leaked-user` 라는 문자열을 쓰는 코드는 **지금 저장소에 없다**(전수 검색). 8일 전
어떤 검사/조사 스크립트가 남긴 잔재로 보이며, 그 스크립트는 이후 바뀌었거나
gitignore 대상이다.

**지금 테스트 스위트는 뒷정리를 한다** — 확인했다:

```
test_api_regression.py 실행 전  recent_items 36 / favorites 0
                       실행 후  recent_items 36 / favorites 0   (변동 없음)
```

그 파일 12행이 규약을 적어 두었다: *"테스트 전용 user_id(qa-reg-<uuid>)로만 데이터를
만들고, 끝나면 그 user_id의 행만 정리한다."*

`leaked-user` 는 로그인할 수 없는 id 라 실사용자 화면에는 보이지 않는다.
**정리는 운영 DB 쓰기라 승인 영역**이므로 기록만 한다.

---

## 7. 최소 변경 / 인코딩

```
                       추가   삭제
test_search.py         +140    -0    check_authed_screens_get_the_same_address (7단언)
```

**제품 코드는 이번 Sprint 에 한 줄도 바꾸지 않았다.** 발견한 것이 전부 "이미 옳다"
였기 때문이다. BOM 이 바뀐 파일 0개.

---

## 8. 승인으로 SKIP

```
1. 스케줄러 등록 / 실크롤 재개                  <- 유일한 Release Blocker
2. 병합 사건 중복 1행 정리 (탐지기는 Sprint 249 에 신설)
3. backfill_region_normalize.py --apply (422건)
4. recent_items 의 'leaked-user' 25행 정리
5. `.env` 수정 (ADMIN 키)
6. 면적 노출 확대 / '평' 8건 / 지분 표시 / 물건번호 표기 통일   <- 표시 정책
7. 명암비 44건                                <- 디자인 판단
8. git add / commit / push
```

## 9. Release Blocker

```
[P0] 스케줄러 미등록 -> 크롤 정지 -> 기일 남은 물건 0건 -> 기본 검색이 빈 화면
```

## 10. 남은 Backlog / 다음 Sprint

```
A. 로그인 화면 **브라우저 실렌더** 측정 — 세션 쿠키가 있으면 즉시 가능(§2 마지막)
B. 병합 사건 중복 / 지역 데이터 드리프트 / leaked-user 잔재 — 전부 승인만 나면 되는 상태
C. 면적 노출 확대 · '평' 8건 · 지분 표시 · 명암비 44건 — 제품/디자인 판단
D. `document_status` COLLECTING 5,069행의 "대상 아님" 상태 신설 — 제품 판단
E. `filter/` dead 모듈 3개(364줄) 삭제 — 승인 영역
F. 크롤 재개 후: image 4종 실처리량, 문서 재수집 개정 이력(document_version_log)
   첫 동작 확인 — 지금은 구조만 있고 한 번도 돌지 않았다
```
