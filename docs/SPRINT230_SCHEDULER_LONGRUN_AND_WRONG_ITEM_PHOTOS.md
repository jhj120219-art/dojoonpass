# Sprint 230 — 무인 운전 시뮬레이션 · 스케줄 산술 · 다른 물건 사진 차단

**날짜** 2026-08-20. 운영 DB / 스케줄러 등록 **무변경**.

목표는 *"사람이 하루 한 번 실행하는 프로그램"이 아니라 **"Scheduler 가 붙으면 장시간
자동으로 안정적으로 도는 시스템"*** 이다. 그 기준으로 승인 없이 가능한 것만 했다.

---

## 1. ★ 다른 물건의 사진이 저장될 수 있었다 (수정)

### 코드가 스스로 적어 둔 위험

`crawler/base_crawler.py:go_to_case_detail()` 의 docstring 이 이미 이렇게 적고 있었다.

> **물건 사진에는 버튼이 없다.** 상세페이지에 이미 그려져 있는 캐러셀을 읽는 방식이라,
> 잘못된 물건의 페이지에 있으면 그대로 잘못된 사진을 저장한다.

그런데 **실제 동작은 경고만 남기고 진행**이었다.

```python
target = next((m for m in matches if (m.get("obj_no") or "").strip() == want), None)
if target is None:
    logger.warning("... 첫 일치 항목으로 진행한다")   # <- 그리고 진행한다
if target is None and matches:
    target = matches[0]
```

`wait_for_detail()` 은 **사건번호**만 대조한다. 물건번호는 아무도 확인하지 않는다.

### 왜 조용한가

저장된 사진은 **진짜 사진**이다. 크기도 정상, 해시도 계산되고, `auction_image` 에 기록되고,
`document_status` 는 READY 가 되고, 브라우저에서 잘 열린다.
`audit_asset_integrity.py` 의 [1]~[9] 가 **전부 통과한다.**
사용자는 **다른 물건의 사진**을 보고 입찰을 판단하게 된다.

문서는 이 위험이 없다 — 버튼 id 에 물건번호가 붙어 있어 어느 물건의 페이지에서 눌러도
그 물건의 문서가 나온다(그 docstring 의 실측: 다중물건 22건에서 서로 다른 물건이 같은
바이트인 경우 0건). **사진만 다르다.**

> 그 docstring 의 다른 실측도 그대로 옮겨 둔다 — 2025타경311 은 물건 1과 2의 사진이
> 실제로 **같았다**(같은 건물이라 법원이 같은 전경도를 준다). 즉 그 표본에서는
> 결과가 **우연히** 같았을 뿐이고, 우연에 기댄 상태였다.

### 해결 — 모호할 때만 거부한다

항상 거부하면 blast radius 가 너무 크다(목록의 물건번호 표기가 조금만 달라져도 사진
수집이 통째로 멈춘다). 그래서 **판단할 수 있고 위험할 때만** 막는다.

```
후보가 1개                 -> 모호하지 않다. 진행
후보 여러 개 + 정확 일치    -> 그 행으로 진행
후보 여러 개 + 불일치       -> **거부** (사진일 때만)
목록이 물건번호를 안 준다    -> 판단 근거가 없다. 막지 않는다
```

마지막 줄은 Sprint 228(사건번호 대조)과 같은 규칙이다 — **모르는 것은 막지 않는다.**

`doc_worker` 가 `require_exact_item=(doc_type == "image")` 로 넘긴다.
문서는 종전 동작 그대로다.

### 회귀 (`test_asset_pipeline.py` 22번 신설, 9검사)

가짜 드라이버로 **실제 `go_to_case_detail()`** 을 돌린다(목록/진입 단계만 대체).

```
모호할 때 사진은 진입하지 않는다 / 거부하면 moveDtlPage 조차 부르지 않는다
문서는 종전대로 진행한다
정확 일치가 있으면 **첫 행이 아니라 그 행**으로 간다  (moveDtlPage(11), not (10))
후보 1개면 막지 않는다 / 물건번호 정보가 없으면 막지 않는다
★ doc_worker 가 실제로 그 인자를 넘기는가(배선)
```

### 변이 4/4 검출

```
거부 분기를 끈다(수정 전 동작)          -> FAIL
모호 판정을 사실상 끈다                 -> FAIL
doc_worker 배선을 뗀다                   -> FAIL
언제나 첫 행을 고르게 한다               -> FAIL (moveDtlPage(10) != (11))
```

### 곁다리 — 기존 가드가 내 변경을 잡았다

`test_doc_worker_recovery.py` 의 스텁이 호출 시그니처를 고정하고 있어 즉시 실패했다.
**`**kwargs` 로 뭉개지 않고** 새 인자를 이름으로 받게 고쳤다 — 뭉개면 다음에 인자가
바뀌어도 조용히 통과한다.

---

## 2. 스케줄 산술의 마지막 다리 (신규 가드)

`test_schema_hygiene.py` 14-B 는 이미 촘촘했다 — 우선순위 시각 ↔ PS1, 문서 수집 시각 ↔ PS1,
실행 순서, `ExecutionTimeLimit` ≥ 실행 창. **비어 있던 것은 사건 크롤 다리였다.**

```
DojoonPass-PriorityRefresh  01:50   (config PRIORITY_REFRESH_TIME  ↔ 검사 있음)
DojoonPass-DocWorker        02:00   (config DOC_WORKER_START_TIME  ↔ 검사 있음)
  창 종료                   04:00   (config DOC_WORKER_END_TIME)
DojoonPass-DailyCrawl       06:00   ← config 상수 자체가 없고, **어떤 검사도 참조하지 않았다**
```

### 겹치면 무슨 일이 나는가

세 작업 중 **둘이 Chrome 을 띄운다.**

```
DocWorker  -> doc_worker.py  -> build_download_driver()   (다운로드 폴더 사용)
DailyCrawl -> mvp_scraper.py -> crawl_court() -> base_crawler.build_driver()
```

그리고 **서로를 막지 못한다** — 각자 자기 락만 갖고 있다
(`doc_worker.lock` / `mvp_scraper.lock`). 락은 자기 자신의 중복 실행만 막는다.

`DOC_WORKER_END_TIME` 을 큐를 더 소진하려고 07:00 으로 늘리는 것은 지극히 자연스러운
변경인데, 그 순간 Chrome 두 개가 **같은 법원 사이트를 동시에** 두드린다.

### 함께 잠근 것 — 하드코딩한 진입점 목록

`test_crawl_exit_code.py` 는 배치 3종 이름을 **하드코딩**해 두고 errorlevel 검사를 확인한다.
PS1 에 네 번째 작업이 생기면 그 배치는 **아무도 검사하지 않는다** — 실패 은폐 검사가
새 진입점만 비껴간다. 두 목록이 같은지 대조하게 했다(어느 쪽이 늘어도 걸린다).

PS1 → `.bat` → `.py` 의 존재 여부도 함께 확인한다.

### 변이 4/4 검출

```
DOC_WORKER_END_TIME 07:00 (크롤과 겹침)   -> FAIL
DailyCrawl 을 03:00 으로 (창 한가운데)     -> FAIL
검사되지 않는 네 번째 진입점 추가          -> FAIL
존재하지 않는 배치를 가리키기              -> FAIL
```

---

## 3. 장시간 무인 운전 시뮬레이션 (`test_scheduler_longrun.py` 신설, 121단언)

기존 큐/락/재시도 검사는 전부 **한 동작**을 본다. 비어 있던 것은 **누적**이다.

**실제 함수만 부른다** — `enqueue_documents` / `claim_next_queue_item` /
`mark_queue_done` / `mark_queue_failed` / `reset_stale_queue` / `refresh_queue_priority`,
그리고 `run_daily.bat` 이 그렇듯 `upsert_batch` 다음에 `migrate_execute.execute()` 를 부른다.
운영 `auction.db` 는 열지 않는다(임시 디렉터리에 실제 부트스트랩 3단계).

크래시는 **claim 한 뒤 아무 표시도 남기지 않고 버리는 것**으로 만든다 — DB 에서 프로세스
사망과 구별되지 않는다. 시간 경과는 `last_attempt_at` 을 과거로 밀어 재현한다.

### 7일 연속 운전 결과

```
D1  claim   0 (done  0 / fail  0 / crash  0)  큐  16행
D2  claim  16 (done  5 / fail 10 / crash  1)  큐  32행
D3  claim  27 (done  9 / fail  7 / crash 11)  큐  48행
...
D7  claim  30 (done 15 / fail  9 / crash  6)  큐 112행

일별 증가폭 [16, 16, 16, 16, 16, 16]   <- 일정하다(누수 없음)
auction_item 28행 / document_status 106행
불변식 위반 0
```

매일 검사하는 불변식 4가지 — 중복 큐 행 / 재시도 상한 / 고아 `document_status` /
`done` 인데 화면은 `COLLECTING`(두 기록이 갈라짐).

### 나머지 4개 시나리오

```
2. 크래시로 남은 claim 이 다음 날 **원래 자리로** 회수된다
   -> in_progress_refresh 가 pending 이 아니라 **refresh** 로 되돌아온다
3. 재시도 예산이 날짜를 넘기며 무한히 되살아나지 않는다
   -> 한 행의 retry_count 가 상한을 넘지 않고, 되살아난 행이 화면에 FAILED 로 남지 않는다
4. 같은 날 두 번 돌려도 중복/손상이 없다 (재실행 멱등)
   -> 이미 done 인 행이 재적재로 되살아나지 않는다
5. 만료 200행 뒤에서도 살아 있는 작업에 도달한다 (starvation 없음)
```

### ★ 이 검사가 처음에 **공허하게 통과**하고 있었다

`upsert_batch` 는 **`auction`** 에 쓴다. `auction_item` 은 `migrate_execute` 가 채운다.
그 단계를 빼먹었더니 `auction_item` 이 0행이 됐고, **그것을 조인하는 불변식 2개가
언제나 빈 결과로 통과**했다. 동기화 단계를 넣고, 그 위에
*"auction_item 이 실제로 채워졌다"* / *"document_status 가 실제로 쌓였다"* 를
명시적으로 잠갔다.

### 변이 — 3/4 검출, 그리고 나머지 하나는 **내 변이가 틀렸다**

```
회수 시 refresh 를 pending 으로 강등        -> FAIL
크래시 회수를 아예 안 함                     -> FAIL (D3~D5 누적으로 드러난다)
UNIQUE 키를 느슨하게 해 중복 적재 허용       -> FAIL (재실행 멱등 검사가 잡는다)
INSERT OR IGNORE 제거                        -> **놓침**
```

마지막은 가드의 구멍이 아니다. `INSERT` 로 바꿔도 UNIQUE 제약이 막아 **중복이 생기지
않는다** — 변이가 결함을 만들지 못한 것이다. 중복의 실제 근원인 UNIQUE 를 건드리자
곧바로 잡혔다.

> 그 과정에서 한 번 더 틀렸다. 처음에는 `UNIQUE(...)` 줄을 주석으로 바꿨는데,
> 앞 줄의 쉼표가 남아 **SQL 문법 오류**가 되고 부트스트랩이 옛 스키마를 유지했다.
> 유효한 SQL 을 유지하면서(`UNIQUE(..., enqueued_at)`) 다시 하니 검출됐다.
> **변이가 안 잡히면 가드를 의심하기 전에 변이가 진짜 결함을 만들었는지 먼저 본다.**

---

## 4. 이미지 체인 실브라우저 관통

```
crawler -> 저장 -> auction_image -> READY -> API -> 검색목록 -> 관심/최근 -> 상세
```

서버를 띄운 상태에서 실제로 걸었다.

```
자산 감사 [9]   물건 206 / 사진 URL 45 / 문서 URL 556 / **열리지 않음 0**
최근 본 물건    카드 11개 중 사진 4개, 전부 디코딩 (522x700 / 700x393 / 525x700 x2)
                ★ 화면 URL == 검색 API == 상세 API   (4건 전부 일치)
검색목록        총 1,876건 / 카드 20개 / 썸네일 9개
                뷰포트 안 6개 전부 디코딩, alt="" + aria-hidden 전부 준수
                h1 1개 / main 1개 / 가로 오버플로 0
상세 /505       물건 사진 5장, 대표 사진 렌더, 권리분석·가격·상태 전부 표시
```

### ★ 하마터면 없는 결함을 보고할 뻔했다

첫 측정에서 사진 4장이 전부 `naturalWidth: 0`, `complete: false` 였다.
"저장은 됐는데 브라우저에 안 뜬다"로 보였다 — 이 저장소가 가장 경계하는 모양이다.

도구부터 의심했다.

```
서버 직접 fetch     200 / image/jpeg / 235,194 B / FF D8 FF E0 (정상 JPEG)
새 Image() 로 로드   **성공** (522x700)
페이지의 <img>       complete:false, naturalWidth:0, **currentSrc 비어 있음**
                     -> 브라우저가 **요청을 시작조차 하지 않았다**
document.visibilityState   **"hidden"**
```

원인은 앱이 아니라 **측정 환경**이었다. 탭이 백그라운드면 Chrome 은 `loading="lazy"`
이미지의 로드를 **미룬다.** 스크린샷으로 렌더를 강제한 뒤 다시 재니 4장 전부 디코딩됐다.

Sprint 223 이 포커스에서 배운 것과 **똑같은 함정**이다
(*"보이지 않는 탭에서 잰 포커스 값은 근거로 쓰지 않는다"*).
이제 이미지에도 같은 규칙이 필요하다 — **보이지 않는 탭에서 잰 lazy 이미지 로드 상태는
근거로 쓰지 않는다. 렌더를 강제한 뒤 재측정한다.**

---

## 5. 최종 상태

```
python run_python_tests.py   통과 41 | 실패 2 | 건너뜀 3 | 판정없음 1   (단언 6,701건)
```

단언 6,564 -> **6,701**(+137). 통과 파일 40 -> **41**(신규 `test_scheduler_longrun.py`).
남은 실패 2건은 Sprint 224~229 와 같다(크롤 정지 / 미추적 파일 — 해소책이 승인 영역).

---

## 6. 승인 없이 더 할 수 없는 것

```
Scheduler 실제 등록      선행 조건은 전부 갖춰져 있다(PS1 dry-run 통과). 등록만 남았다.
실제 크롤 실행           모든 "0건"의 근본 원인
운영 DB / 고아 데이터 정리
```
