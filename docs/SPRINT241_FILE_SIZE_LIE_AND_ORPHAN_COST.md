# Sprint 241 — API가 다른 파일의 크기를 광고하고 있었다, 그리고 고아 큐의 값을 처음 매겼다

**날짜** 2026-08-21. HEAD `9c1f8ed` / branch `master` / **커밋·푸시 없음**.
운영 `auction.db` 무변경(읽기만) / `.env` 무변경 / 스케줄러 등록 없음 / 실크롤 없음.

---

## 0. 기준선 — 이번 세션 실측

```
git             HEAD 9c1f8ed / master / origin 동기(0↔0)
                working tree = Sprint 240 미커밋 변경 8파일 + 문서 1개

auction_item    1,876행 / auction_date 2026-07-06~2026-08-19 / crawl_date 최신 2026-08-12
                기일이 오늘(2026-08-21) 이후인 물건 **0건**
auction_image   45행(물건 9개)   doc_raw 556행
document_status READY 556 / COLLECTING 5,069 / FAILED 3
document_queue  3,498행 (pending 2,753 / done 559 / SKIPPED_EXPIRED 186)
favorites 0 / recent_items 36
스케줄러         이 저장소를 가리키는 등록 작업 0개

python run_python_tests.py   통과 47 | 실패 1 | 건너뜀 3 | 판정없음 1 (단언 7,133)
node --test                  143개 중 139 PASS / 1 FAIL / 3 SKIP
tsc 0 / eslint 0
```

실패 1건 + 건너뜀 3건은 **전부 같은 원인 하나**다 — 기일이 남은 물건이 0건이라 기본
검색이 빈 화면이다. 같은 코드를 날짜만 옮긴 fixture 로 돌리면 **143/143 PASS** 다
(이번 세션에서 다시 확인). 코드 결함이 아니라 **데이터 신선도**다.

---

## 1. ★ API 가 `download_url` 옆에서 **다른 파일의 크기**를 광고하고 있었다

### 발견

문서 체인을 바이트 단위로 훑다가(READY 45건 전수) STATUS 12건에서 크기가 어긋났다.
처음엔 내 검사가 틀린 줄 알았고, **실제로 한 번은 틀렸다** — `doc_raw.storage_path`
가 곧 서빙 파일이라고 가정했기 때문이다. 제품 매핑을 직접 읽어 다시 재니 원인이 나왔다.

```
doc_raw.storage_path   status.json    <- 구조화 산출물(변경 감지 지문의 출처)
서빙 파일               status.html    <- api/v1/documents.py DOC_TYPE_FILES
```

`api/v1/item.py:_document_entry()` 가 `file_size` 를 `doc_raw` 에서 그대로 퍼오고
있었다. 그래서 응답이 이렇게 나갔다:

```
"file_size": 12827,                                   <- status.json 크기
"download_url": "/api/v1/item/54/documents/STATUS"     <- status.html 45,747B 를 준다
```

운영 데이터 실측(READY 45건 전수):

```
SPEC / APPRAISAL   33건   doc_raw 파일 == 서빙 파일  -> 크기 일치
STATUS             12건   **전부 불일치**  (예: 광고 12,827B / 실제 45,747B ≈ 3.6배)
```

### 심각도 — 지금은 안 보이지만 거짓말이다

`file_size` 는 TS 인터페이스(`DocumentStatusItem`)에 선언돼 있지만 **JSX 가 그리지
않는다.** 그래서 오늘 사용자에게 보이지는 않는다. 그러나 필드 이름과 바로 옆의
`download_url` 이 "이 주소로 받으면 이만큼"이라고 말하고 있으므로, 쓰는 쪽이
생기는 순간(용량 표시·진행률·사전 할당) **조용히 틀린다.**

### 고침 — 서빙 경로에서 직접 잰다

`api/v1/item.py` 에 `_served_file_size()` 를 넣고, 파일명 매핑과 디렉터리 규칙은
`api/v1/documents.py` 의 것을 **그대로 import 해서** 쓴다(같은 어휘를 두 벌로 만들지
않는다 — 이 저장소가 BUGS #50/#64 로 반복해 겪은 어긋남의 원인이 그것이었다).

```
READY 가 아니면          잰다는 개념 자체가 없다(URL 도 안 준다) -> None
서빙 파일이 없거나 0바이트  documents.py 가 404 를 주는 상태 -> None (0 이 아니다)
그 외                    os.path.getsize(서빙 파일)
```

`doc_raw` 의 의미는 **건드리지 않았다.** 그것이 status.json 을 가리키는 것은 변경
감지의 실체 기록으로서 옳다. 바뀐 것은 API 가 무엇을 광고하느냐뿐이다.

### ★ 내 첫 고침이 조용히 실패할 뻔했다

`_served_file_size()` 를 처음엔 `except Exception:` 으로 감쌌다. 그런데 `import os`
가 누락된 상태였고 — CRLF 때문에 치환이 빗나갔다 — 그 `NameError` 를 bare except 가
삼켜서 **모든 `file_size` 가 조용히 None** 이 될 뻔했다. 이 저장소가 "거짓 성공"이라
부르는 바로 그 모양이다. `except (OSError, ValueError, TypeError)` 로 좁혀
코딩 실수는 터지게 두었다.

### 재측정

```
운영 데이터 READY 45건 전수: file_size == download_url 이 준 실제 바이트 수  **전부 일치**
비-READY(COLLECTING): download_url None / file_size None
```

### 회귀 검사 — mutation 3종으로 검증

`test_asset_pipeline.py` 41번 신설. **STATUS 를 반드시 포함**한다 — SPEC 만 검사하면
두 파일이 같아서 통과해 버리고, 그것이 이 결함이 오래 살아남은 이유다.

```
MUT-F1  doc_raw 값으로 되돌림(원래 결함)          -> 잡힘
MUT-F2  0바이트를 크기로 인정                     -> 처음엔 살아남음 -> 검사 보강 후 잡힘
MUT-F3  READY 아닌 것도 잰다                      -> 처음엔 equivalent(파일이 없어서)
                                                    -> 옛 파일을 실제로 만들어 두게 고쳐 잡힘
```

MUT-F2/F3 는 **내 검사가 공허했던 지점**이다. mutation 을 걸지 않았으면 몰랐다.

---

## 2. ★ 능력 모델이 자기 전제를 잃어도 숫자를 계속 출력하고 있었다

`test_worker_capacity.py` 는 "처리량 **1.97배**", "하루 능력 153건"을 출력한다.
그런데 batching 을 되돌리는 mutation 을 걸어 봤더니:

```
MUT-B1  claim_next_item_rows 기본값을 1 로       -> test_worker_batching 은 잡음
                                                    **test_worker_capacity 는 통과**
```

이유는 5번 검사(`test_batching_gain_is_quantified`)가 `capacity()` 와
`legacy_capacity()` 라는 **상수 계산 두 개를 서로 비교**할 뿐 제품 코드를 한 줄도
지나가지 않기 때문이다. 모델로서는 정직하지만, **그 모델이 현실과 연결돼 있는지는
아무도 확인하지 않았다.** 즉 batching 이 사라져도 "1.97배 이득"이라고 계속 보고한다.

### 고침 — 전제를 코드에 묶는다

7번 검사 `test_the_model_premise_still_holds_in_code()` 신설. 처리량 계산이 딛고 선
"물건 1건당 이동 1회"를 실제로 만드는 두 기계를 확인한다.

```
MUT-B1  claim 기본값 1                          -> 잡힘
MUT-B2  QUEUE_BATCH_MAX_ROWS = 2 (4종을 못 담음)  -> 잡힘
MUT-B3  워커가 _ensure_detail_page 대신 매번 이동  -> ★ 처음엔 살아남음
```

MUT-B3 가 살아남은 이유가 재미있다. 처음엔 `"_ensure_detail_page(" in code` 로 썼는데
**`def _ensure_detail_page(...)` 라는 정의 줄이 검사를 통과시켰다.** 함수는 남아 있고
아무도 부르지 않는 상태 — 이 저장소가 "기능 존재 != 실행 경로 연결"이라 부르는 모양을
내 검사가 그대로 재현했다. **정의를 빼고 호출만** 세도록 고쳐 잡았다.

---

## 3. 고아 큐 행의 값을 처음 매겼다 (삭제하지 않는다)

`cleanup_orphans_dryrun.py` 는 고아 큐 행을 "해를 끼치지 않고 낭비만 한다"고만 적었다.
**얼마를** 낭비하는지가 없으면 정리 우선순위를 정할 수 없다. 그래서 쟀다.

### 비용 모델 — 진짜 `doc_worker.main()` 을 돌려 관측

브라우저만 가짜고, 고아 사건에 대해 `go_to_case_detail()` 이 False 를 돌려주는
실제 상황을 재현했다.

```
30분 간격 cycle1   이동 12회   retry 1  -> pending
30분 간격 cycle2   이동 12회   retry 2  -> pending
30분 간격 cycle3   이동 12회   retry 3  -> failed (종결)
cycle4~6           이동  0회            (종결됐으므로 그날은 더 안 돈다)
★ 다음 날          이동 12회            reset_stale_queue() 가 failed 를 되살린다
```

즉 **기일이 남은 고아 1행 = 하루 MAX_DOC_RETRY(3)회 이동**이고, 그것이 **기일이 지날
때까지 매일 반복**된다. 반대로 **기일이 지난 고아는 공짜다** — 만료 가드가 브라우저를
열기 전에 SKIPPED_EXPIRED 로 종결하고(실측 이동 0회), 그 상태는 `reset_stale_queue()`
가 되살리지 않는다.

### 오늘의 답: 시급하지 않다

```
운영 DB 고아 큐 18행
  종결 상태(더 안 돈다)             6행   비용 0
  기일 경과(만료 가드가 막는다)     12행   비용 0
  ★ 기일이 남았다(매일 재시도)       0행   비용 0
-> 지금은 실제 낭비가 **없다.** 정리의 시급성은 낮다.
   다만 크롤이 재개되면 새 고아는 위 비용(행당 3회/일)을 곧바로 쓴다.
```

이 계산을 `cleanup_orphans_dryrun.py` 3-b 절로 **코드에 넣었다**(실행 창 대비 비율까지
출력한다). 삭제는 하지 않는다 — 승인 영역이다. 안전한 처리 순서도 함께 적었다:
기일이 남은 것만 손대고, 지우기 전에 "진짜 고아인가"를 통과시키고(`migrate_execute`
가 auction_item 을 재작성하는 중에는 **정상 물건도 잠깐 고아로 보인다**), 삭제 대신
`mark_queue_unsupported()` 로 종결시키는 되돌릴 수 있는 선택지도 있다.

### ★ 첫 측정이 두 번 틀렸다

1. `days=4` 로 반복 실행했는데 **이동이 늘지 않았다.** 30분 재시도 간격 때문에
   재claim 이 막힌 것이었는데, 나는 `status='failed'` 행만 시간을 밀고 있었다 —
   고아는 재시도 소진 전까지 **`pending`** 이라 대상이 아니었다.
2. `auction_item` 의 `UNIQUE(case_id,item_no)` 를 몰라 fixture 가 터졌다.

둘 다 고치고서야 위 수치가 나왔다.

---

## 4. Mutation 감사 — 이번 세션 전체

각 변이를 실제로 걸고 어느 스위트가 우는지 관측했다.

```
변이                                          결과      잡은 스위트
MUT-B1 claim 기본값 1 (batching 되돌리기)      잡힘      worker_batching, (보강 후)worker_capacity
MUT-B2 QUEUE_BATCH_MAX_ROWS=2                 잡힘      worker_capacity (신설)
MUT-B3 _ensure_detail_page 호출 제거           잡힘*     worker_capacity (검사 보강 후)
MUT-R1 재시도 상한(MAX_DOC_RETRY) 제거          잡힘      refresh_trigger, document_queue
MUT-C1 claim 원자성(WHERE status) 제거          잡힘      refresh_trigger, document_queue
MUT-CR1 crash 회수(in_progress 되돌리기) 제거   잡힘      refresh_trigger, document_queue
MUT-D1 변경 감지 매핑 무력화                    잡힘      refresh_trigger
MUT-W1 wrong-item 가드 제거                     잡힘      asset_pipeline
MUT-A1 nav 랜드마크 제거                        잡힘      frontend_accessibility, node(+2)
MUT-T1 TS 인터페이스 필드 삭제                  잡힘      tsc
MUT-API1 search API 가 필드를 안 준다            잡힘      search
MUT-API2 favorites API 가 thumbnail_url 안 줌    잡힘      asset_pipeline, search
MUT-F1/F2/F3 file_size 관련 3종                 잡힘*     asset_pipeline (신설/보강 후)
```

`*` = 처음엔 살아남았고 **검사를 보강해서** 잡게 만든 것.

### Equivalent mutant (억지로 고치지 않고 이유를 남긴다)

```
MUT-E  doc_types_for_changed_fields() 의
       `if t in QUEUE_TO_DOC_STATUS_TYPE` 필터 제거   -> 아무도 안 운다
```

**equivalent 다.** `REFRESH_DOC_TYPES_BY_FIELD` 가 만들어내는 종류
(`appraisal/image/spec/status`)가 `QUEUE_TO_DOC_STATUS_TYPE` 키와 **정확히 같아서**
필터가 현재 한 건도 걸러내지 않는다(실측: 차집합 0개). 그 필터는 미래의 드리프트를
막는 방어이고, **드리프트 자체는 이미 다른 검사가 잡는다** —
`test_refresh_trigger.py:test_field_to_doc_type_mapping()` 의
"매핑의 모든 doc_type 이 큐 어휘에 있다". 즉 잡히지 않는 것이 옳고, 여기에 검사를
더하면 오늘 기준 항상 참인 동어반복이 된다. **그래서 고치지 않았다.**

### 관측한 커버리지 분포 이상 (결함은 아니다)

```
test_doc_worker_recovery.py 가 MUT-CR1(crash 회수 제거)을 잡지 못한다.
test_race_conditions.py 가 MUT-C1(claim 원자성 제거)을 잡지 못한다.
```

두 변이 모두 **다른 두 스위트가 잡으므로 시스템 전체로는 구멍이 아니다.**
다만 파일 이름이 가리키는 관심사와 실제 커버 범위가 어긋나 있어 기록해 둔다
(중복 검사를 추가하는 것은 이득보다 유지비가 크다고 판단했다).

---

## 5. 모바일 — **실제 뷰포트**로만 판정했다

Sprint 240 이 쓴 iframe+srcdoc 기법은 **이번엔 판정 근거로 쓰지 않았다.**
전부 `window.open(url,'','width=W')` + `resizeTo()` 로 연 **진짜 창**에서 쟀고,
매 측정마다 `innerWidth == 요청 폭` 과 미디어쿼리 평가를 함께 확인했다.
가로 넘침은 요구대로 `documentElement.scrollWidth > clientWidth` 로 판정했다.

측정기 자체도 매번 검증했다 — 일부러 넓은 요소를 넣으면 잡히고(`selftest: true`),
빼면 0 이 된다. Tailwind 적용 여부도 매번 확인했다.
**스크롤 컨테이너 안에서 넘치는 것**(정렬 칩 줄)과 **페이지를 밀어내는 것**을 구분한다.

```
화면                    320   360   390   430   900   1400      (가로 스크롤 / REAL 넘침)
/                       .     .     .     .     .     .          전부 없음 / 0
/search?sido=서울        .     .     .     .     .     .          전부 없음 / 0
/favorites              .     .     .     .     .     .          전부 없음 / 0
/properties/recent      .     .     .     .     .     .          전부 없음 / 0
/properties/505         .     .     .     .     .     .          전부 없음 / 0
/mypage                 .     .     .     .     .     .          전부 없음 / 0
/login                  .                                        없음 / 0

미디어쿼리   320~430 md=false / 900 md=true,xl=false / 1400 md=true,xl=true
이미지       디코드 실패 0 (전 화면·전 폭)
```

Sprint 240 의 고침(헤더 `flex-wrap`, 카드 `min-w-0`, 검색조건 저장 `min-w-0`)이
**실제 뷰포트에서도** 유효함을 이것으로 처음 확인했다.

---

## 6. 접근성 — 7화면 실측

```
화면                 포커스가능  이름누락  라벨없는폼  h1  헤딩건너뜀  랜드마크           alt없음  양수tabindex
/                        75        0         0       1      0     header,nav,main       0          0
/search                  75        0         0       1      0     header,nav,main       0          0
/favorites               11        0         0       1      0     header,nav,main       0          0
/properties/recent       17        0         0       1      0     header,nav,main       0          0
/properties/505          21        0         0       1      0     header,nav,main       0          0
/mypage                   8        0         0       1      0     header,nav,main       0          0
/login                    5        0         0       1      0     main                  0          0
```

색·글자크기·간격, 큰글씨 UI 최종 디자인은 **승인 영역이라 확정하지 않았다.**

---

## 7. 자산 무결성 — 바이트까지

### 사진 45장 전수

```
DB -> 디스크 -> API -> 브라우저 디코드
바이트 완전 일치 45/45 | sha256 드리프트 0
매직바이트 <-> Content-Type 45/45 (jpg 40 image/jpeg, gif 5 image/gif)
매직바이트 <-> 확장자 45/45
ETag -> If-None-Match -> 304          45/45
Last-Modified -> If-Modified-Since -> 304  45/45
경계: 없는 물건/0번/99번/존재하지 않는 id  전부 404
```

### 문서 45건 전수 (§1 고침 이후)

```
available -> 실제 바이트 -> 제품 매핑 파일과 동일 -> Content-Type 일치 -> ETag 304
SPEC 17 application/pdf / APPRAISAL 16 application/pdf / STATUS 12 text/html
file_size == 실제 서빙 바이트  45/45   (고침 전 12건 불일치)
경계: 지원 안 하는 종류 400 / 없는 물건 404 / 존재하지 않는 id 404
```

---

## 8. Scheduler — 실제 프로세스로 락까지 검증

등록과 실크롤은 승인 영역이라 하지 않았다. 그 앞은 **실제로 실행**했다.

```
[1] 신선한 lock 이 있으면          "이미 실행 중으로 보임 - 건너뜀" / exit 0
                                   선점자의 lock 을 뺏지 않는다  ★확인
[2] stale lock(5시간 초과)         "오래된 락 파일 발견(6.0시간) - 죽은 실행으로 간주하고 회수"
                                   인수 후 진행 -> 정상 해제      ★확인
[3] 실행 창 밖 기동                 브라우저를 띄우지 않고 종료 / exit 0 / DB 무접근
[4] BAT -> Python                  exit 0 / [SUCCESS] 마커 / lock 잔여 없음
[5] logs/doc_run.log               정상 UTF-8 (cp949 로는 디코드 실패)
```

### ★ 락 측정이 한 번 거짓 결함을 냈다

처음 `_acquire_lock()` 이 **False** 를 돌려줘 결함으로 보였다. 원인은 그때
**백그라운드에서 전체 파이썬 스위트가 돌고 있었고**, 그 스위트가 같은
`logs/doc_worker.lock` 을 쓰고 있었기 때문이다. 스위트가 끝난 뒤 다시 재니 정상이었다.
제품 결함이 아니라 **측정 환경 간섭**이다.

---

## 9. 보안 / 권한 — 살아 있는 API 로 확인

```
토큰 없음 / 위조 서명 / sub 없음
  -> /favorites, /recent-items, /search-presets  전부 401       (9/9)

사용자 격리
  관심물건   소유자 3건 / 타인 0건
  최근본     소유자 11건 / 타인 0건
  상세 is_favorited  소유자 True / 타인 False

타인이 소유자의 관심물건 DELETE
  -> 소유자 데이터 3건 그대로(못 지운다)
  -> 응답이 성공이라 말하지 않는다: {"success": false, "error": "FAVORITE_NOT_FOUND"}
     (200 이지만 거짓 성공이 아니다 - 프런트가 "이미 원하는 상태"로 읽는 계약)
```

---

## 10. WEB 사용자 흐름 — 상태별

```
검색조건 -> 검색 -> 목록 -> 썸네일 -> 상세 -> 관심물건 -> 최근본 -> 마이리스트 -> CSV/TSV/클립보드
전 구간 실제 브라우저에서 동작 확인

빈 상태      "검색 결과가 없습니다"  role=status 로 알린다(스크린리더도 읽는다)
없는 물건    "매물을 찾을 수 없습니다" + "검색 화면으로" 복귀 링크
오류         "물건 정보를 불러오지 못했습니다 / 일시적인 오류일 수 있습니다" (없는 것과 구분한다)
partial      문서 3종 "수집중" + 링크 0개(깨진 뷰어를 열지 않는다), 사진 5장은 정상 표시
비로그인     Node 계약 검사 143건이 쿠키 없이 도는 경로로 커버
```

### 마이리스트 내보내기 — 실제 API 응답으로 16검사 통과

```
헤더: 법원 | 사건번호 | 물건번호 | 물건종류 | 소재지 | 감정가 | 최저입찰가 | 매각기일 | 상태 | 유찰횟수
6개 핵심 필드가 원본 API 값과 정확히 일치(불일치 0)
값 안의 쉼표(주소·물건종류 3행)가 파싱 후에도 한 칸으로 복원
CRLF + UTF-8 BOM (한국어 Windows 엑셀) / TSV 전 행 열 수 일치
복사 결과를 role="status" 로 알린다
```

지지옥션/탱크옥션 전용 포맷은 **여전히 만들지 않는다**(외부 포맷 확인은 승인 영역).

---

## 11. 최종 상태

```
python run_python_tests.py   통과 47 | 실패 1 | 건너뜀 3 | 판정없음 1  (단언 7,174, 89.3s)
                             실패 1 = test_pipeline_integrity.py (§0 데이터 신선도 가드)

node --test tests/**/*.test.mjs
  운영 데이터(API :8000)   143개 중 139 PASS / 1 FAIL / 3 SKIP   <- §0 그 하나
  fixture 데이터           143개 중 **143 PASS / 0 FAIL / 0 SKIP**

tsc 0 / eslint 0
git diff --stat  12 files changed, 724 insertions(+), 12 deletions(-)
                 + docs/SPRINT240_*.md, docs/SPRINT241_*.md (신규, 미추적)
```

단언 수 7,133 -> **7,174** (신설 41건).

---

## 12. 승인으로 SKIP

```
1. 실제 법원 크롤 재개          <- Release Blocker 의 유일한 원인
2. 스케줄러 실제 등록(3작업)
3. 고아 데이터 삭제/정리        <- §3 에서 "지금은 시급하지 않다"까지 확인
4. 운영 DB 변경 / 데이터 삭제
5. .env / Secret 변경
6. 외부 서비스 연동 / 지지옥션·탱크옥션 포맷 확정
7. 제품 디자인 확정 / 큰글씨 최종 디자인
8. 모바일 실기기 검증
9. git add / commit / push
```

## 13. Release Blocker

```
[P0] 크롤 정지 -> 기일이 남은 물건 0건 -> 기본 검색이 빈 화면
     코드는 정상이다. fixture 로 143/143 PASS 로 증명했다. 크롤 재개는 승인 영역.
```

그 외 P0 없음.

## 14. 남은 Backlog / 다음 Sprint

```
A. 상수 스텁 mutation 훑기를 계속한다.
   이번에 `wait_for_detail`(S240) 에 이어 `_ensure_detail_page` 호출 검사·file_size 검사에서
   또 공백을 찾았다. harness 가 True/None 으로 박아 둔 자리가 더 있는지 본다.
B. 실제 뷰포트 sweep(§5)을 재사용 가능한 스크립트로 남긴다.
   CI 에는 브라우저가 없으므로 소스 계약과 병행하는 구조로.
C. 큐에 image 종류 0행 — 기존 2,753행은 image 추가 **전** 적재분이다.
   크롤 재개 후 새 물건부터 4종이 되어 물건당 이동/비용이 늘어난다(능력 모델은 이미 4종 기준).
D. 상세 응답의 중복 필드 dong/sido/sigungu 정리 여부 판단(화면은 full_address 만 쓴다).
E. test_doc_worker_recovery / test_race_conditions 의 이름과 실제 커버 범위 어긋남(§4)
   — 중복 검사를 늘리지 않는 선에서 문서로만 정리할지 판단.
```
