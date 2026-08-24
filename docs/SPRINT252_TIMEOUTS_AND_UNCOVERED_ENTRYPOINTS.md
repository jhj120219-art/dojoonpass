# Sprint 252 — 끝나지 않는 요청과, 아무도 실행하지 않던 진입점

**날짜** 2026-08-24 (Sprint 251 에 이어 같은 날). HEAD `ebb5816` / branch `master` /
**커밋·푸시 없음**. 운영 `auction.db` 무변경(행수·`integrity_check` 전후 대조) /
`.env` 무변경 / 스케줄러 등록 없음 / 실크롤 없음 / 의존성 설치 없음.

---

## 0. 기준선 — 이번 세션 실측

```
세션 시작   python  통과 48 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,719 / 53파일)
            node    175개 / 171 PASS / 1 FAIL / 3 SKIP
세션 종료   python  통과 52 | 실패 1 | 건너뜀 3 | 판정없음 1   (단언 7,821 / 57파일)
            node    183개 / 179 PASS / 1 FAIL / 3 SKIP
            tsc 0 / eslint 0 / next build 성공(10 페이지)

운영 DB (작업 전후 동일, integrity_check ok / FK 위반 0)
  auction·auction_item 1,876 / auction_case 1,384 / document_queue 3,498
  auction_image 45 / doc_raw 556 / document_status 5,628 / favorites 0 / recent_items 36
```

실패 1건(python·node 각 1)은 **같은 원인** — 기일 남은 물건 0건. Sprint 251 §1 의
Release Blocker 그 자체이고 승인 영역이라 그대로 둔다.

### 오늘 크롤링 / 스케줄러 (세션 시작 시 재측정, Sprint 251 과 동일)

```
이 저장소를 가리키는 예약 작업   0개 (전체 249개)
등록되지 않은 정의               DojoonPass-PriorityRefresh / DocWorker / DailyCrawl
logs/daily_run.log               마지막 갱신 2026-08-11 17:05
auction_item 최신 수집일          2026-08-12
기일 남은 물건                    0건 (마지막 기일 2026-08-19)
```

**오늘(2026-08-24) 크롤은 실행되지 않았다.** 등록은 승인 영역 -> SKIP.

---

## 1. ★★ 프런트의 모든 API 요청에 **시간 제한이 하나도 없었다**

### 발견과 실측

`src/lib/api.ts` 의 fetch 다섯 곳, 그리고 그 밖의 맨 fetch 한 곳 — 전부 타임아웃이
없었다. 응답을 주지 않는 서버(연결은 받고 한 바이트도 안 보내는 TCP 서버)로 재현했다:

```
타임아웃 없음      15,000ms 경과 후에도 pending  (끝나지 않는다)
AbortSignal 3초    3,007ms 만에 TimeoutError
```

### 왜 나쁜가 — 화면에 **이미 있는 실패 UI 에 도달하지 못한다**

각 화면은 실패 문구를 이미 갖고 있다.

```
properties/[id]        loadError='unavailable'  "일시적인 오류일 수 있습니다"
favorites              "관심물건을 불러오지 못했습니다"
recent / mypage / presets   같은 모양
```

백엔드가 멈추면 이 문구 대신 `불러오는 중...` 이 **영원히** 남는다. 사용자에게는
"느리다"가 아니라 "고장인데 아무 말이 없다"이고, 새로고침 말고는 나갈 길이 없다.
즉 새 화면을 만드는 것이 아니라 **있는 경로를 살리는** 수정이다.

### 무엇을 했나

`timedFetch()` 하나로 모으고 여섯 래퍼가 전부 그것을 거치게 했다.

```
REQUEST_TIMEOUT_MS  = 8000    JSON API
DOWNLOAD_TIMEOUT_MS = 60000   등기부 PDF 등 파일 응답
타임아웃 -> ApiError(408)     그대로 DOMException 을 흘리면 호출부의
                              `err instanceof ApiError` 분기를 전부 비껴간다
```

8초의 근거도 재서 정했다 — JSON 엔드포인트 HTTP 왕복 p50 4~17ms / p95 ~30ms,
DB 계층 p95 ≤ 1.5ms. 정상 요청은 8초 근처에도 가지 않는다. 크게 잡을수록
"고장인데 조용한 시간"만 길어진다.

### 같은 결함이 다른 곳에 — **실제로 하나 더 있었다**

```
src/app/properties/[id]/page.tsx:313   문서 존재 확인을 **맨 fetch** 로 (api.ts 밖 유일)
```

시간 제한이 없어 `.then` / `.catch` 어느 쪽도 안 불리는 상태가 가능했고, 그러면 문서
뷰어가 확인 상태에 그대로 남는다. `api.ts` 의 `headOk()` 로 옮겨 같은 한도를 적용했다.

파이썬 쪽도 같은 질문으로 훑었다 — `urlopen` 5곳 **전부 이미 timeout 인자가 있다**(퍼짐 없음).

### 그 이동이 **또 하나의 누락**을 드러냈다

`headOk()` 로 옮기자 `test_search.py` 의 "옛 값을 보여줄 경로가 없는가" 검사가 울었다.
원인을 보니 **옮겨 온 그 요청에 `cache: 'no-store'` 가 없었다**(맨 fetch 시절에도 없었다).
브라우저가 그 HEAD 응답을 재사용하면 **이미 사라진 문서에 대해 뷰어가 열린다.**
같은 자리에서 함께 고쳤다 — 기존 검사가 제 일을 한 사례다.

같은 검사가 `fetch(` 개수를 세고 있어서 리팩터링 뒤 "1개"를 보고 스스로 공허하다고
판정했다. 세는 대상을 **요청을 내는 호출부**(`timedFetch(`)로 옮기고, `fetch(` 는
**정확히 1개**(정의 안)여야 한다는 조건을 새로 걸었다 — 그래야 우회 경로가 다시 생기면 잡힌다.

### 회귀 방어와 **그 방어가 한 번 눈이 멀었던 기록**

`tests/api-timeout.test.mjs`(신규, 8검사). 응답 없는 서버를 스스로 띄우고 실제로 부른다.

처음 판은 `api.ts` 와 *같은 방식*을 테스트 파일에 다시 구현해 돌렸다. mutation 으로
눈이 먼 것을 확인했다 — `signal: controller.signal` 을 fetch 에서 빼는 변이, **즉
타임아웃이 아무 일도 하지 않게 되는 바로 그 결함**을 놓쳤다(5개 중 그 1개만 통과).
지금은 `src/lib/api.ts` 를 TypeScript 로 트랜스파일해 **그 모듈의 함수를 직접 부른다.**

```
mutation (제품 코드 구동판)
  M1 fetchAuthedRaw 를 맨 fetch 로        검출
  M2 clearTimeout 제거                    검출
  M3 signal 을 fetch 에 안 넘김            검출   <- 첫 판이 놓치던 것
  M4 다운로드 한도를 JSON 과 같게          검출
  M5 JSON 한도를 10ms 로(정상 응답도 끊김)  검출      = 5/5

mutation (no-store 계약, test_search.py)
  N1 headOk 의 no-store 제거              검출
  N2 fetchJSON 의 no-store 제거           검출
  N3 timedFetch 우회 맨 fetch 추가         검출      = 3/3

mutation (src 전체 규칙)
  page.tsx 를 맨 fetch 로 되돌림           검출      = 1/1
```

---

## 2. ★★ 커버리지를 **모듈 단위로** 다시 재니, 아무도 실행하지 않는 진입점이 있었다

`audit_test_reality.py` 는 "어떤 **테스트**가 제품을 얼마나 도나"를 잰다. 이번에는
반대로 물었다 — **어떤 제품 코드가 아무 테스트도 지나지 않나.** 전체 스위트를
합산 coverage 로 돌렸다(제품 모듈 53개).

```
커버리지 0%  refresh_priority.py (16문)   ★ 스케줄 파이프라인 진입점
             unlock_retry.py (45문)        운영자 수동 도구(기본 dry-run, 정적 가드 있음)
             backfill_doc_raw.py (89문)    같음
             filter/report_generator.py    죽은 코드(CLAUDE.md 가 "테스트 붙이지 말라"고 명시)
             filter/scoring_engine.py      같음
낮음         mvp_scraper.py 38% / crawler/base_crawler.py 55% / crawler/doc_crawler.py 70%
높음         api/* 96~100%, storage/database.py 93%
```

### 2-A. `refresh_priority.py` — 매일 01:50 에 돌 코드가 한 줄도 검증되지 않았다

등록은 승인 영역이지만, **등록 직후부터 매일 도는** 코드다. 깨져 있어도 알 수 있는
방법이 "새벽에 배치가 실패하는 것"뿐이었다.

`test_refresh_priority.py`(신규). 스크래치 사본에 우선순위가 틀린 대기 행을 심고
`main()` 을 **실제로 실행**한다. 고정한 계약 다섯:

```
main() 이 예외 없이 끝난다            .bat 의 errorlevel 계약
임박(<=3일)/7일/그 밖 -> 1/2/3        재계산이 실제로 일어난다
반환값은 **바뀐 행 수**               Sprint 63 정정(검토 수가 아니다)
done / SKIPPED_EXPIRED 는 무변경      종결 행이 되살아나지 않는다
두 번째 실행은 0건                    멱등
운영 DB 에 QA 행이 새지 않았다        + DB_PATH 복원 확인

mutation  P1 refresh 상태를 재계산에서 뺌(Sprint 189 회귀)   검출
          P2 반환값을 '검토 수'로 되돌림(Sprint 63 회귀)     검출
          P3 임박 판정 제거                                 검출
          P4 종결 상태까지 재계산 대상에 넣음                검출
          P5 main() 이 재계산을 안 부름                      검출     = 5/5
```

### 2-B. `mvp_scraper.py` 38% — **BUGS #47 이 태어난 자리**가 미검증이었다

미실행 구간이 한 덩어리였다: `run_courts()` 오케스트레이션 전체 + `main()` 의 성패
판정·종료 코드 배선.

```
2026-08-02 실측: 법원 60곳 중 59곳 오류 / 저장 0건인데 배치가 **성공으로 끝났다.**
```

Sprint 55 가 판정 자체(`models/crawl_outcome.py`)를 떼어 고쳤고 그 모델은 **커버리지 100%**
다. 그런데 **그 모델을 채우는 쪽**이 0% 였다 — "판정은 검증됐지만 판정에 넘길 값을
만드는 코드는 미검증"인 상태. `outcome.collected` 에 엉뚱한 값이 들어가도 아무도 모른다.

`test_crawl_orchestration.py`(신규). `crawl_court` 를 모듈 속성으로 갈아 끼워
Selenium 없이 시나리오를 만든다.

```
전 법원 예외      -> "전 법원 수집 실패" / exit 1
전 법원 빈 목록   -> skipped 로 세고 "수집 건수 0건" / exit 1
섞임(성공1·빈1·예외1) -> 부분 실패는 치명적 아님 / exit 0, 저장 2건이 outcome 에 담긴다
저장 0건          -> "DB 저장 0건" / exit 1
main() 정상       -> exit 0 + document_queue 적재 호출
main() 실패       -> exit 1 + 적재 호출 안 함

mutation  C1 main() 이 종료 코드를 버림(BUGS #47 회귀)   검출
          C2 실패 법원을 outcome 에 안 담음               검출
          C3 수집 건수를 안 담음                          검출
          C4 빈 목록을 skipped 로 안 셈                   검출
          C5 실패해도 큐 적재를 부름                      검출
          C6 저장 결과를 안 담음                          검출     = 6/6
```

### 2-C. 그 과정에서 나온 **cwd 의존 잔존 1건** (수정)

테스트가 제품 경로를 그대로 태우자 저장소 루트에 `auction_20260824.csv` 가 생겼다.
원인을 보니 `save_csv_backup()` 이 `df.to_csv("auction_YYYYMMDD.csv")` — **상대경로**였다.

Sprint 245/246 이 같은 계열을 네 군데 고쳤는데(`api/auth.py` load_dotenv,
`storage/database.py` DB_PATH, `doc_worker.py` LOCK_PATH, 운영 도구 8개)
**이 한 곳만 남아 있었다.** 같은 모듈 안에서 로그·락은 이미 `_HERE` 기준인데 CSV 만 아니었다.

정적 감사(`test_schema_hygiene.py` 의 cwd 검사)가 못 잡은 이유도 확인했다 — 그 검사는
알려진 경로 호출(open/connect/makedirs…)에 **문자열 리터럴**이 들어가는 모양만 본다.
여기는 pandas `to_csv` 이고 인자도 조립된 변수라 두 조건 다 비껴간다. 구조적으로 못 잡는다.
그래서 **다른 cwd 에서 실제로 돌리는** 회귀를 따로 뒀다(Sprint 246 이 쓴 방법 그대로).

```
mutation  경로를 상대경로로 되돌림 -> [FAIL] cwd 에 auction_20260824.csv 가 떨어짐   검출
```

### 2-D. `crawler/base_crawler.py` 55% 중 **유일하게 순수한 판단** 하나 (신규 검증)

미실행 구간은 거의 전부 Selenium 조작이라 브라우저 없이 못 돈다. 예외가
`wait_for_detail()` 하나다 — "기대한 사건의 상세 페이지에 도착했는가"를 셋으로 판단한다
(사건번호 존재 / 목록 링크 잔존 / 상세 지표). 드라이버를 흉내 내면 그대로 검증된다.

이 판단이 중요한 이유: **이 저장소가 두 번 당한 자리**다. "2024타경1009" 가
"2024타경100920" 의 접두 부분 문자열이라 서로 다른 진짜 사건이 같다고 판정됐다
(Sprint 121 이 `resume_start_idx` / `go_to_case_detail` 두 벌을 하나로 합쳐 고쳤다).
`wait_for_detail()` 은 그 공용 함수를 쓰지 않고 자기 방식(정규식 토큰 + 집합 교집합)을
쓴다. **지금 구현은 정확하다** — `\d+` 가 greedy 라 접두가 떨어지지 않는다. 다만 그것이
우연이 아니라 계약이라는 것을 아무것도 고정하지 않고 있었다.

```
mutation  W1 부분 문자열 매칭으로 되돌림          검출
          W2 정규식을 \d{1,4} 로 좁힘             검출  <- 가장 미묘한 회귀
          W3 목록 페이지 검사 제거                검출
          W4 상세 지표 검사 제거                  검출     = 4/4
```

---

## 3. 새 테스트가 **운영 산출물을 오염시켰고, 그것도 고쳤다**

정직하게 남긴다. `test_crawl_orchestration.py` 첫 판이 제품 경로를 그대로 태우면서
두 곳에 흔적을 남겼다.

```
logs/validation.jsonl   ValidationEngine 이 QA 검증 결과 5줄 append
auction_20260824.csv    save_csv_backup() 이 저장소 루트에 생성
```

이 저장소의 다른 테스트는 이 규칙을 지킨다 — 검사는 운영 로그/산출물을 건드리지 않는다
(그 흔적이 나중에 진짜 크롤 기록으로 오독된다. Sprint 251 이 `logs/errors.jsonl` 끝의
테스트 잔재 2줄을 정확히 그 이유로 기록했다).

**격리**: `mvp_scraper._HERE` 를 스크래치로 돌리고(validation.jsonl 이 따라온다),
`save_csv_backup` 은 함수째 갈아 끼운다(상대경로라 `_HERE` 를 안 따라온다).
그리고 **격리 자체를 검사로 고정**했다 — 실행 후 `logs/validation.jsonl` 에 QA 기록이
0줄인지, 루트에 오늘 날짜 CSV 가 없는지 확인한다. 격리가 공허하지 않은지도 함께 본다
(CSV 백업 경로를 실제로 지나갔는가).

**남긴 흔적은 되돌렸다.** CSV 는 삭제(이 세션이 만든 산출물), `validation.jsonl` 은
QA 5줄만 제거. 그 과정에서 **내가 두 번째 실수를 했다** — 줄바꿈을 지정하지 않고
읽고 써서 7,893줄의 CRLF 가 전부 LF 로 바뀌었다(8KB 축소로 드러남). 바이트 단위로
되돌려 원래 크기 **1,065,412 bytes** 와 정확히 일치함을 확인했다.

> **교훈**: 텍스트 파일을 제자리에서 다시 쓸 때는 읽기·쓰기 **양쪽에** `newline=""` 를
> 준다. 소스 파일에는 지키던 규칙인데 로그 파일에서 놓쳤다.

---

## 4. 결함이 **나오지 않은** 영역 — 잰 것만 적는다

### SQLite 락 경합 (가설을 세우고, 측정으로 스스로 기각했다)

`journal_mode=delete` / `busy_timeout=5000`(파이썬 기본) 이고 WAL 이 아니다. 그래서
"긴 쓰기 트랜잭션이 읽기를 막아 API 가 500 이 되지 않을까"를 의심했다. **틀렸다.**

```
쓰기 트랜잭션을 3초 열어 둔 채 (스크래치 사본, 운영 DB 무변경)
  모드      읽기            동시 쓰기
  delete    0ms 성공        2,905ms 대기 후 성공
  wal       0ms 성공        2,918ms 대기 후 성공
```

`BEGIN IMMEDIATE` 는 RESERVED 락이라 **읽기를 막지 않는다**(EXCLUSIVE 는 commit 순간뿐).
WAL 로 바꿔도 이 워크로드에서는 차이가 없다.

이어서 "migrate 가 한 트랜잭션으로 수천 행을 쓰니 사용자 쓰기가 5초 안에 못 들어가지
않을까"도 쟀다 — 역시 아니다.

```
migrate_execute.execute() 전체 122ms
  (auction_case 1,384 + auction_item 1,876 + document_status 5,628 을 단일 트랜잭션)
그 사이 사용자 쓰기(관심물건 등록 모양) 21ms 만에 성공, 실패 0회
```

**변경하지 않았다.** WAL 전환은 DB 파일 헤더를 바꾸는 운영 데이터 변경(승인 영역)인데,
바꿀 근거가 측정으로 사라졌다.

### 로그 무한 증가 (측정 후 의도적으로 보류)

회전(rotation) 설정이 **어디에도 없다**(`RotatingFileHandler` 0건). 실제 증가율을 쟀다:

```
logs/scraper.log       2.82MB / 54일 -> 하루 53.5KB -> 1년 19.1MB
logs/doc_collect.log   0.51MB / 45일 -> 하루 11.6KB -> 1년  4.1MB
logs/doc_run.log       0.54MB / 45일 -> 하루 12.3KB -> 1년  4.4MB
```

연 30MB 규모다. 반면 Windows 에서 `RotatingFileHandler` 는 **다중 프로세스에 안전하지
않다** — `doc_run.log` 는 `doc_worker.py` / `refresh_priority.py` / `.bat` 이 함께 쓴다.
회전 시점에 다른 핸들이 열려 있으면 rotation 이 실패한다.
**연 30MB 를 줄이려고 그 위험을 지는 것은 맞바꿈이 나쁘다.** 근거를 남기고 보류한다.

### 검색 필터의 시군구 동명이인 (사용자 영향 확인 후 결함 아님으로 판정)

`address_detail` 에 "중구"만 치면 `sigungu LIKE '%중구%'` 라 **6개 시의 중구**가 함께 나온다.

```
시군구 이름 208개 중 여러 시/도에 걸친 이름 14개 / 해당 물건 307건
  실제 동명 7개(강서구·고성군·남구·동구·북구·서구·중구) = 227건
  나머지 7개는 Sprint 251 이 찾은 **잘못된 sido 4행 + sido 결측 3행**의 부산물
```

결함이 아니다 — 결과 카드가 `full_address` 를 먼저 보여주고 그 값이
"서울특별시 중구…" / "부산광역시 중구…" 로 시작한다(실측). 모호함이 화면에 드러난다.
UI 의 시군구 드롭다운은 시/도를 고른 뒤에만 채워지므로 이 경로로는 애초에 발생하지 않는다.

### 사건번호 정규식 4벌 (드리프트처럼 보였으나 의도된 분화)

```
crawler/base_crawler.py:146,217   r"\d{4}타경\d+"       목록 셀 / 페이지 자유 텍스트
validator/validation_engine.py    r"\d{4}타경\d+"       저장된 값 검증
crawler/doc_paths.py:260          r"\d{4}\s*타경\s*\d+"  현황조사서 **HTML 원문**
```

마지막 하나만 `\s*` 를 허용한다. 입력 도메인이 다르다(문서 HTML 은 공백/마크업이 낀다).
실데이터로도 확인 — 사건번호 1,381개에 대해 두 패턴의 불일치 건수가 **269 대 269 로 동일**
(그 269 는 전부 병합 사건 `" / "` 표기이고 공백 변형이 아니다). 합치는 것이 오히려 틀린다.

### 조용한 예외 처리 65곳 (전수 확인 후 결함 없음)

AST 로 제품 코드의 예외 핸들러를 전수 조사해 로그·재raise 가 없는 65곳을 뽑아 읽었다.
성패 판정을 뒤집는 것은 없었다 — 대부분 정리(cleanup)·폴백 경로다
(`calc_priority` 의 날짜 파싱 실패 -> 최저 우선순위 등).

---

## 4-b. 프로덕션 빌드로도 계약을 확인했다 (release 근거)

프런트 계약 검사는 보통 `npm run dev` 를 띄우고 돌린다. 이번에는 `next build` 산출물을
`npm start` 로 서빙한 상태에서 **같은 스위트를 다시** 돌렸다 — dev 와 prod 는 번들링이
다르므로, 통과가 하나에서만 확인되면 근거가 반쪽이다.

```
프로덕션 서버(npm start) 기준
  node 183개 / 179 PASS / 1 FAIL / 3 SKIP        <- dev 와 동일 (실패 1건도 같은 원인)
  /                    200      /search   200
  /login               200      없는 경로 404 (커스텀 404)
  /properties          307 -> /login?redirect=%2Fproperties
  /favorites           307 -> /login?redirect=%2Ffavorites
  /mypage              307 -> /login?redirect=%2Fmypage      (쿼리 보존 확인)

프로덕션 페이지 응답 (20회)
  화면      p50      p95      max      크기
  홈       11.9ms   34.7ms   36.1ms   17.1KB
  검색     11.0ms   33.0ms   35.1ms   17.6KB
  로그인    6.6ms   26.5ms   26.6ms    8.4KB
  404       1.4ms   18.5ms   21.6ms    9.0KB
```

인증 게이트·커스텀 404·리다이렉트 쿼리 보존이 **프로덕션 번들에서도** 그대로 동작한다.

`check_release_build.py` 도 함께 돌렸다 — 번들에 `http://localhost:8000` fallback 이
박혀 있다고 보고한다. 이는 `NEXT_PUBLIC_API_BASE_URL` 이 이 환경에 설정돼 있지 않기
때문이고(도구가 "로컬 개발 빌드라면 정상"이라고 안내한다), `.env` 설정은 승인 영역이다.

---

## 5. 환경 이슈 하나 (제품 결함 아님, 기록만)

`npm run build` 가 한 번 EPERM 으로 실패했다.

```
Error: EPERM: unlink '.next\static\b4q1mKt-xLBoCuxfx4-mZ'
그 디렉터리 안 파일 3개의 Mode 가 `-a---l` = **OneDrive 재분석 지점(placeholder)**
```

이 저장소는 OneDrive 폴더 안에 있다. 빌드 캐시가 클라우드 placeholder 로 탈수화되면
`next build` 가 지우지 못한다. `Remove-Item -Recurse -Force` 로 치우니 즉시 성공했다
(`.next` 는 gitignore 대상 재생성 산출물이라 안전하다). 코드 회귀가 아니다 — 다시 생길
수 있는 환경 함정이라 여기 남긴다.

---

## 6. 승인이 필요해 SKIP 한 것 (Sprint 251 과 동일, 새로 해소된 것 없음)

| 항목 | 왜 승인 영역인가 |
|---|---|
| 예약 작업 3개 등록 | 사용자 환경 변경. `-SkipCoveredByLegacy` 는 붙이지 말 것(커버 중인 작업 0개) |
| `.env` 에 ADMIN_API_KEY / SUPER_ADMIN_API_KEY | 시크릿 값 결정·주입 |
| `npm install next@16.3.2` | 빌드/런타임 동작 변경(proxy bypass 권고 포함) |
| 고아 큐 18행 / 고아 문서 1폴더 / 다운로드 고아 8개 | 운영 데이터 파괴적 변경(지금 낭비 비용 0) |
| 주소 오분류 4행 UPDATE | 운영 데이터 변경 |
| 명암비 44곳 / `document_status` 새 상태 / 환불 정책 | 디자인·상태머신·정책 결정 |
| `filter/` 죽은 모듈 3개 삭제, 추적된 DB 백업 9개 제거 | 파일 삭제·commit 필요 |

---

## 7. 남은 Backlog (승인 없이 가능한 것)

- `docs/CURRENT_STATE.md` / `docs/CHANGELOG.md` 의 Sprint 251~267 기록 재확인
  (Sprint 251 은 판단에 직접 쓰이는 3문서만 정정했다).
- `logs/errors.jsonl` 끝 2줄 테스트 잔재(2026-08-21). 지금 테스트는 임시 디렉터리를
  쓴다(연속 실행으로 44줄 불변 확인). 잔재 삭제는 운영 로그 변경이라 손대지 않았다.
- `crawler/doc_crawler.py` 70% / `crawler/base_crawler.py` 55% 의 나머지 미실행 구간은
  전부 Selenium 조작이다 — 브라우저 없이는 늘릴 수 없다.
- `unlock_retry.py` / `backfill_doc_raw.py` 는 커버리지 0% 지만 운영자 수동 도구이고
  정적 `--apply` 가드가 있다. 행동 검증을 붙일 수는 있으나 우선순위가 낮다.

---

## 8. 왜 여기서 멈추는가

```
코드      제품 결함 2건 수정(프런트 타임아웃 부재 / save_csv_backup cwd 의존)
          + 캐시 계약 누락 1건(headOk 의 no-store)
테스트    python 48 -> 52 PASS, 단언 7,719 -> 7,821 (신규 파일 4개)
          node 175 -> 183 tests
          mutation 7개 대상 25건 **전부 검출**
          (타임아웃 5/5, no-store 3/3, src 규칙 1/1, refresh_priority 5/5,
           크롤 배선 6/6, wait_for_detail 4/4, CSV cwd 1/1)
데이터    세션 전후 행수·integrity_check·FK 동일. 운영 산출물 오염 0
          (한 번 오염시켰고 바이트 단위로 되돌렸다 — §3)
빌드      tsc 0 / eslint 0 / next build 성공
가설 기각  SQLite 락 경합 / 로그 증가 / 시군구 동명 / 정규식 4벌 — 전부 측정 후 "결함 아님"
```

남은 P0 은 여전히 하나이고 그 하나가 승인 영역이다 — 크롤이 2026-08-11 이후 돌지 않아
기일 남은 물건이 0건이고, 그래서 기본 검색이 빈 화면이다. 이 세션이 할 수 있었던 것은
그 상태에서도 **제품이 조용히 멈추지 않게** 만드는 것(타임아웃), 그리고 크롤이 재개될 때
**성패를 정직하게 보고할 코드가 검증돼 있게** 만드는 것(진입점 3개의 회귀)이었다.
둘 다 했다.
