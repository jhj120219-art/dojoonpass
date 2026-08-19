# Sprint 190 — 매일 갱신 체인 실측 감사 (성능 / 원천 생존 / 부채)

2026-08-18. Sprint 189 직후. 기준 커밋 `73ac6eb`.

Sprint 189가 **코드로** 재수집 체인을 완성했다. 이 Sprint는 그 체인이 **실제 환경에서**
어디까지 서 있는지를 잰다. 결론부터: **배관은 전부 살아 있고, 아무도 밸브를 안 열었다.**

---

## 1. ★ 크롤러가 아직 법원 원천을 읽는가 — 실측 OK

가장 중요한 미지수였다. `auction.crawl_date`가 2026-08-12 이후 0건인데, 원인이
"예약 작업 미등록"(BUGS #123)인 것은 확인했지만 **그것만으로는 크롤러 자체의 생존을
알 수 없다.** 법원 사이트 DOM이 그 사이 바뀌었다면 예약 작업을 등록해도 0건이다.

한 법원만, DB에 쓰지 않고 확인했다(`crawl_court()` 결과만 본다. `MAX_ITEMS=10`이라
요청량은 목록 1페이지 + 상세 10건).

```
대상        서울중앙지방법원 (60곳 중 1곳)
수집        9건 / 186.2초
검증        PASS 9 / FAIL 0 / 정확도 100.0%
정규화      9행, 핵심 필드(사건·물건·법원·기일·최저가·감정가·상태·주소) 전부 채워짐

예: 2024타경117502-1  기일 2026-08-19  최저가 304,000,000  감정가 380,000,000  유찰 8회
```

**VERDICT: OK — 크롤러가 아직 원천을 읽는다.**
DB의 같은 물건 값과 일치한다(그 사이 법원이 바꾸지 않았다는 뜻이기도 하다).

실행 후 DB 무변경 확인: `auction` 1,876행 / `max(crawl_date)` 2026-08-12 /
큐 분포 그대로. 읽기 전용 프로브라는 설계가 지켜졌다.

### 파생 실측 — 전체 크롤 소요

```
1곳 186초 x 60곳 ≈ 3.1시간
```

> **[전제 명시 2026-08-18 Sprint 209]** 이것은 **파생이지 실측이 아니다.**
> 끝까지 돌려 본 적이 없다(전체 크롤은 2026-08-02 이후 실행 자체가 없다).
> 성립하려면 두 가지가 참이어야 한다.
>
> 1. `MAX_ITEMS = 10` — 법원당 최대 10건만 본다. **확인함**(`config/settings.py:3`,
>    `crawler/court_crawler.py:115` 가 그 값을 그대로 쓴다). 그래서 1회 실행의
>    상한은 60곳 x 10건 = **600건**이다.
> 2. 60곳이 모두 186초 안팎이다. **확인 안 됨** — 잰 곳은 서울중앙 하나이고,
>    기일이 없는 법원은 즉시 스킵되어 훨씬 빠르다(그쪽으로 치우치면 과대 추정이다).
>
> 즉 3.1시간은 **상한에 가까운 보수적 추정**으로 읽는 것이 맞다.

`run_daily.bat`은 06:00 시작이므로 09:00 전후에 끝난다. 그리고 문서 수집 창은
**다음 날 02:00**이다. 즉 **법원 변경 -> 문서/사진 반영까지 약 17시간**이 설계상의
지연이다(06:00 크롤 -> 09:00 migrate + 재수집 예약 -> 다음 날 02:00 doc_worker).
이 순서는 `docs/CLAUDE.md`가 정한 파이프라인 그대로이고, 바꿀 이유가 없다 —
다만 "당일 반영"이 아니라는 것은 명시해 둔다.

---

## 2. 성능 — 어휘 확장이 비용을 바꿨는가 (실측: 안 바꿨다)

Sprint 189가 `claim_next_queue_item()`의 조건을 `status = 'pending'`에서
`status IN ('pending','refresh')`로 바꿨다. 큐가 3,498행이라 여기서 느려지면
워커 실행 창 전체에 영향이 간다. 운영 DB 사본으로 200회씩 재 봤다.

```
이전(= 'pending')   200회 0.061초  -> 1회 0.30 ms
현재(IN 2값)        200회 0.060초  -> 1회 0.30 ms

두 경우 모두: SEARCH document_queue USING INDEX idx_queue_status (status=?)
              USE TEMP B-TREE FOR ORDER BY
```

**차이 없음.** 계획도 같다.

### 재수집 예약 자체의 비용

상한(300물건)을 꽉 채우고 **네 종류 전부**를 되돌리는 최악의 경우로 쟀다
(UPDATE 300 x 4 x 2 = 2,400회).

```
소요    0.005초        물건당 0.02 ms
계획    SEARCH ... USING INDEX sqlite_autoindex_document_queue_1
        (court_code=? AND case_no=? AND item_no=? AND doc_type=?)
```

식별키 UNIQUE 인덱스를 그대로 탄다. **매일 배치에 사실상 0의 비용**을 더한다.

### 우선순위 재계산

```
소요 0.021초, 실제 변경 17행 (검토 2,753행)
```

### `USE TEMP B-TREE FOR ORDER BY` — 이번에도 착수하지 않는다

`(status, priority, auction_date)` 복합 인덱스를 만들면 정렬을 없앨 수 있다. 하지만
현재 **1회 0.30 ms**다. 인덱스 추가는 스키마 변경(승인 영역)인데 얻을 것이 없다.
roadmap의 기존 결정("데이터가 10배 이상 늘어난 뒤 다시 잰다")과 같은 판단이다.

---

## 3. 어휘 확장의 파급 — 소비자 전수 확인

`document_queue.status`에 값이 늘었으므로, **그 값을 세거나 분기하는 모든 곳**을
훑었다(`git ls-files`로만 — 저장소 안의 낡은 worktree를 현재 코드로 착각하지 않기 위해).

| 파일 | 판정 |
|---|---|
| `api/v1/doc_stats.py` | **고쳤다** — 하드코딩 목록이라 `refresh`가 어느 칸에도 안 잡혔다. 단일 소스 참조 + `queue_refresh` 추가 |
| `measure_endless_collecting.py` | **고쳤다** — 존재하지 않는 `"processing"`을 세고 새 어휘를 못 셌다. `QUEUE_ACTIVE_STATUSES` 참조 |
| `repair_empty_status_capture.py` | 문제없음 — 파일을 격리(이동)한 **뒤** `pending`으로 되돌린다. 자산이 사라졌으니 `refresh`가 아니라 `pending`이 맞다 |
| `unlock_retry.py` | 문제없음 — `last_attempt_at`만 NULL로 만든다(상태 무관) |
| `refresh_priority.py` | `refresh_queue_priority()` 위임 — 함수 쪽에서 이미 해결 |
| `cleanup_orphans_dryrun.py` / `backfill_doc_raw.py` | 읽기 전용 리포터, 상태 무관 |
| `api/v1/admin.py` | 큐를 조회하지 않는다(참조 0건) |

`test_refresh_trigger.py` §11이 하드코딩이 다시 들어오는 것을 막는다.

---

## 4. 신규 코드 사용처 확인 (죽은 코드 0)

Sprint 189가 추가한 함수/상수 전부가 실제로 호출·참조된다.

```
_remove_other_ext_for_seq / _same_bytes_on_disk        image_crawler 내부
move_into_place / _write_text_if_changed               doc_crawler 두 수집기
_fields_hash / status_content_hash                     collect_status + 형제 재사용
doc_types_for_changed_fields / requeue_changed_documents  migrate_execute
QUEUE_* 11개 / REFRESH_* 2개 / DOC_STATUS_HAS_ARTIFACT    전부 참조 ≥ 1
```

이 저장소는 "준비만 되고 배선 안 됨"을 반복해 겪었다(Sprint 144의 `doc_raw`,
Sprint 150의 `get_auction_images()`, 그리고 이번 Sprint가 채운 `overwrite` 자체).
그래서 새로 만든 것은 **만든 그 Sprint 안에서** 사용처를 세어 둔다.

---

## 5. TODO / FIXME / HACK 전수

추적 파일 전체(`*.py` `*.ts` `*.tsx` `*.ps1` `*.bat` `*.sql`) 기준 **실제 항목 3건**,
전부 같은 파일·같은 사유다.

```
src/app/search/SearchForm.tsx:353  TODO(API 미지원) 면적 필터
src/app/search/SearchForm.tsx:361  TODO(API 미지원) special_conditions
src/app/search/SearchForm.tsx:363  TODO(API 미지원) specialSearchType
```

셋 다 **스키마 변경이 필요한 검색 필터**라 승인 영역이고, roadmap에 이미 올라 있다.
`test_search.py`가 "백엔드에 그 이름이 생기면 이 검사가 실패한다"로 고정해 두어,
구현되는 순간 프론트 TODO를 함께 정리하도록 강제한다 — 방치가 아니라 **관리되는 부채**다.

나머지 grep 히트는 오탐이다(`migrate_execute.py`의 "위 Critical TODO를 해소한다"는
해소 기록, `test_api_regression.py`의 `reason_type="HACK"`은 테스트 데이터).

---

## 6. 문서 드리프트 — 실제로 틀린 서술 4건을 정정했다

이번 감사에서 **문서끼리 서로 모순**하는 것을 발견했고, 재서 판정했다.

| 서술 | 판정 |
|---|---|
| `CURRENT_STATE.md` Sprint 187: "DOJOONPASS_DAILY 정상 동작 중(2026-08-17 exit 0)" | **틀렸다** — 지금은 그 작업이 없다. 정정 삽입 |
| `roadmap.md` Sprint 187 정정: "등록 0건은 더 이상 사실이 아니다" | **틀렸다** — 원래의 "0건"이 다시(여전히) 맞다. 재정정 삽입 |
| `BETA_RELEASE_CHECKLIST.md` P0-A: "예약 작업 0개" | **맞았다** — 이 항목이 옳았음을 명시 |
| `BUGS.md` #117 / 체크리스트 P0-C: "마이그레이션 020 미적용" | **해결됐다** — 2026-08-17T09:03:19 적용, API 200 실측으로 정정 |

**서로 다른 세션의 기록이 충돌하면 다시 재는 쪽이 답이다.** `*.db`가 환경마다 다르듯
`Get-ScheduledTask` 결과도 환경·시점마다 다르다 — 문서에 적힌 "정상 동작 중"은
상수가 아니라 **매번 다시 재야 하는 값**이다(#117이 남긴 교훈의 두 번째 적용).

또 하나: `BETA_RELEASE_CHECKLIST.md` 43행이 셸 이스케이프 사고로
`` `.<개행>egister_scheduler_tasks.ps1` ``로 **깨져 있었다.** 고쳤고, 추적 파일
315개를 같은 패턴으로 전수 검색해 다른 사례가 없음을 확인했다(잔여 0건).
같은 사고를 이번 세션에서도 두 번 겪었다 — 셸 heredoc은 본문의 백슬래시 이스케이프를
해석한다.

---

## 7. 남은 것

**코드로 할 수 있는 일은 이 체인에서 소진됐다.** 남은 하나가 승인 영역이다.

```
.\register_scheduler_tasks.ps1 -Apply     # BUGS #123, Release Blocker
```

이것 하나로 아래가 전부 자동으로 이어진다(전부 이미 구현·검증됨):

```
06:00 mvp_scraper   법원 원천 수집          <- 오늘 실측으로 생존 확인
      migrate_execute  auction_item 갱신 + **변경 기반 재수집 예약**  <- Sprint 189
01:50 refresh_priority 우선순위 재계산       <- refresh 행 포함(Sprint 189)
02:00 doc_worker    문서/사진 수집 + **재수집(overwrite)**  <- Sprint 189
      -> previous_hash != new_hash -> document_version_log
      -> API -> 상세페이지 (캐시가 최신화를 막지 않음을 실측 확인)
```


---

## 8. ★★ 마지막 칸까지 — **실제 브라우저**로 재수집 1건 완주

앞의 실측들은 전부 "큐가 refresh 로 바뀐다"까지였다. 그 뒤 —
워커가 실제로 법원에 다시 가서 받아 오고, 무변경을 판정하고, 기록을 남기거나
남기지 않는 부분 — 은 단위 검사로만 고정돼 있었다. 여기서 **한 번 완주**시켰다.

### 격리 (실 데이터는 하나도 건드리지 않는다)

```
DB        auction.db 사본 (tempdir)
문서 루트  tempdir/documents  ->  doc_paths / image_assets 를 갈아 끼운다
큐        사본 안에서 딱 한 행만 남기고 refresh 로 만든다
법원 부하  물건 1건 x 문서 1종
```

### 결과

```
대상: 서울중앙지방법원 / 2024타경126346-1 / status (기일 2026-08-19)
기존 문서 복사: status.html(24,126 B), status.json(4,304 B)   <- "이미 받아 둔 상태" 재현
큐: [('status', 'refresh')]

[INFO] 법원 선택: 서울중앙지방법원                                <- 실제 사이트 진입
[INFO] [2024타경126346-1] status 내용 무변경 - 파일을 다시 쓰지 않는다(브라우저 캐시 보존)
[INFO] doc_raw 기록 생략: 내용 변경 없음 (item_id=11853, doc_type=STATUS, version=1 유지)
[INFO] [2024타경126346-1] status 처리 성공 (재수집)

doc_worker 종료코드 0 / 27.2초
큐            [('status', 'done')]
version_log   0 -> 0        <- 거짓 개정 0건
doc_raw       556 -> 556    <- 버전 안 오름 (v1 유지)
스크래치 파일  status.html 24,126 B / status.json 4,304 B  (바이트 그대로)
```

### 이 한 줄이 증명하는 것

**재수집이 실제로 일어났는데(브라우저가 법원에 다시 갔다) 아무것도 거짓으로 기록되지
않았다.** Sprint 189 이전 코드였다면 같은 실행이:

```
document_version_log  +1행   (extracted_at 때문에 지문이 달라져 — BUGS #124)
doc_raw.doc_version   1 -> 2 (사용자 응답에 그대로 실린다)
status.html/json      다시 쓰기 -> mtime 변경 -> 브라우저 캐시 전량 무효화 (BUGS #125)
```

를 남겼을 것이다. 세 가지가 전부 일어나지 않았다.

### 실 데이터 무변경 확인 (실행 후)

```
auction 1,876행 / 큐 분포 그대로(SKIPPED_EXPIRED 186 / done 559 / pending 2,753)
document_version_log 0 / doc_raw 556
실제 documents/서울중앙지방법원/2024타경126346/1/ 의 mtime 2026-08-12 14:45 그대로
```

격리가 설계대로 지켜졌다.


---

## 9. 사진 쪽도 실제 브라우저로 완주 — 그리고 로그가 거짓말하는 것을 잡았다

§8 은 문서(status)였다. 사진은 수집 방식이 근본적으로 다르므로(버튼 없이 DOM 의
base64 를 읽는다) 따로 완주시켰다. 격리 방식은 §8 과 같다.

```
대상: 서울중앙지방법원 / 2024타경3528-1 (사진 5장, 기일 2026-08-19)
기존 사진 복사: 01.jpg(70,100) 02.jpg(39,676) 03.jpg(73,610) 04.jpg(72,241) 05.gif(76,196)
큐: [('image', 'refresh')]

[INFO] 법원 선택: 서울중앙지방법원                       <- 실제 사이트 진입
[INFO] [2024타경3528-1] 사진 DB 기록: 저장 5 / 누락 0 / 오래된 행 정리 0
[INFO] [2024타경3528-1] image 처리 성공 (재수집)

doc_worker 종료코드 0 / 21.4초
큐 image refresh -> done | version_log 0 -> 0 | auction_image 5 -> 5 | 화면상태 READY

파일 비교 — 5장 전부 크기 동일, **mtime 그대로(캐시 보존)**
```

이 표본은 **한 물건 안에 jpg 4장과 gif 1장이 섞여 있다.** 확장자가 물건마다가 아니라
**장마다** 다를 수 있다는 뜻이고, BUGS #120(형식 변경 시 고아 파일)이 가정한 상황이
실제 데이터에 존재함을 뒷받침한다.

### 잡은 것 — 완료 로그가 사실이 아니었다

실행 로그에 `사진 5장 저장 완료` 가 찍혔다. **한 장도 쓰지 않았는데도.**
BUGS #125 의 무변경 스킵을 넣으면서 그 로그 문구를 같이 손보지 않은 결과다.

이 저장소가 BUGS #47(배치가 실패를 성공으로 보고) 이래 반복해 잡아 온
**"로그가 거짓을 말한다"** 부류다. 실 브라우저 실행이 아니었다면 드러나지 않았다 —
단위 검사는 반환값만 보고 로그 문구는 안 보기 때문이다.

```
바뀐 뒤: [2024타경3528-1] 사진 5장 확보 (신규/변경 0장 기록, 무변경 5장 그대로)
```

그리고 숫자를 **반환값에도 담았다**(`written` / `unchanged`) — 자동 검증이 로그 파싱에
의존하지 않도록. `test_asset_pipeline.py` 5-F 에 3검사를 추가해 세 경우
(최초 2/0, 무변경 0/2, 1장 변경 1/1)를 고정했다.
