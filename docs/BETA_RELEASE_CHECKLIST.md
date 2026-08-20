# Beta Release Readiness

Status: Active
Last Updated: 2026-08-07 (Sprint 28)
Owner: Project Management

**2026-08-16 정정(Sprint 134, Documentation Drift Audit)**: 이 문서는 Sprint 28
이후 갱신된 적이 없다 — 그 사이 Sprint 29~133이 이 문서의 여러 항목을 이미
해소했다("이미 해소된 병목은 다시 올리지 않는다"는 이 문서 자신의 원칙과
어긋난 상태로 방치돼 있었다는 뜻). 전면 재작성은 이 세션의 범위를 넘어(P0/P1/P2
전 항목을 하나씩 재검증해야 한다) 지금 하지 않지만, **아래에서 확인된 것만
직접 정정한다.** 현재 출시 준비 상태를 보려면 이 문서 대신
`docs/CURRENT_STATE.md`(Sprint 1~99, 계속 갱신됨) +
`docs/SPRINT99_RELEASE_READINESS_AUDIT.md`(가장 최근의 전용 Release Readiness
감사, 2026-08-13) + `docs/SPRINT100_*.md`~`docs/SPRINT134_*.md`(Sprint 100 이후는
이 파일과의 편집 충돌을 피하려 개별 파일로 분리됨)를 먼저 볼 것.

이 문서는 **지금 출시를 막는 것만** 다룬다. 이미 해소된 병목은 다시 올리지 않는다
(해소 이력은 `docs/CHANGELOG.md`, `docs/BUGS.md`에 있다).

---

**2026-08-17 추가(Sprint 174)**: 이 문서의 역할이 "지금 출시를 막는 것"인데, 2026-08-17
자율 감사에서 확인된 **P0 블로커 2건이 아래 목록에 없다.** 둘 다 이 문서가 마지막으로
정리된 시점 이후에 생겼다. 전면 재작성은 여전히 범위 밖이므로 **이 두 건만 여기 올린다**
(상세 근거는 `docs/CURRENT_STATE.md` Sprint 148~173 절).

### P0-A. 데이터 공급이 2026-08-01부터 멈춰 있다 (스케줄러 미등록)

> ## ★ [2026-08-20 Sprint 238 재실측] **등록은 있다. 그런데 최근 실행이 권한 거부로 실패한다.**
>
> 처음으로 "등록 0개"가 아닌 상태를 확인했다. `Get-ScheduledTask` 전수(254개) 중
> `DOJOONPASS_DAILY` 1개가 이 저장소의 `run_daily.bat`을 가리키며 매일 03:00 트리거로
> 등록돼 있다(DocWorker/PriorityRefresh는 여전히 0개, 변동 없음). 그런데:
>
> ```
> LastRunTime      2026-08-20 22:01:17 (오늘, 그러나 03:00 트리거 시각이 아니다)
> LastTaskResult   0x800710E0 -> net helpmsg 4320: "관리자 또는 운영자가 요청을 거부했습니다"
> auction_item.crawl_date 최신값   2026-08-18 (오늘/어제 새 데이터 없음)
> logs/daily_run.log 마지막 완료   "Finished at 2026-08-18 4:46:08"(그 이후 기록 없음)
> ```
>
> `docs/SPRINT112_SCHEDULER_HANDOFF.md`가 경고한 `LogonType Interactive` 제약과 같은
> 계열의 실패로 보인다 — 로그온 세션이 없으면 이 작업은 돌지 않는다. 08-18까지는
> (로그온 상태였거나 수동 실행으로) 정상 수집됐고 그 이후 이틀치 공백이 실제로
> 발생 중이다. 상세와 조치 3안은 `docs/SPRINT238_LIVE_REGRESSION_AND_BATCHING_CONFIRM.md`
> §2 참고 — 전부 승인 영역이라 이 세션은 실행하지 않았다.

> ## ★ [2026-08-20 Sprint 224~229 확정] **예고한 날이 왔다. 그대로 일어났다.**
>
> 아래 본문이 *"2026-08-20부터 기본 검색 결과가 0건이 된다"* 고 예고했다.
> 오늘 실측했다 — **정확히 그렇게 됐다.**
>
> ```
> 예약 작업 중 이 저장소를 가리키는 것        0개   (변동 없음, 249개 중)
> auction_item.crawl_date 최신값             2026-08-12
> auction_item.auction_date 최신값            2026-08-19   <- 어제
> 기일이 오늘 이후인 물건                      **0건**
> GET /api/v1/search (기본 조건)              total = **0**
> ```
>
> 예측이 맞았다는 것은 **이 항목의 진단이 옳았다**는 뜻이다. 추측이 아니었다.
>
> ### 오늘 이것이 실제로 무엇을 무너뜨렸는가 (전부 실측)
>
> ```
> 화면        /search 가 빈 화면 - 다만 문구는 정확하다
>             "검색조건 때문이 아닙니다 - 매각기일이 남은 물건이 아직 등록되지 않았습니다"
>             (조건 때문이 아님을 사용자에게 구분해 알린다 = 설계가 옳았다)
>
> 검사        test_pipeline_integrity.py    FAIL - 가드가 옳게 말하는 것이다
>             tests/frontend-contract       114검사 중 데이터 의존 검사가 판정 불가
>             test_search.py 의 N+1 가드    **0건에서 공허하게 통과하고 있었다**(Sprint 224에 수정)
>
> 큐          document_queue pending 2,753행이 **전부 만료** -> 워커가 집을 실제 작업 0
> 문서        마지막 문서 수집 시도 2026-07-12 (39일 전)
>             doc_raw 556행의 doc_version 이 전부 1 = **변경을 관측한 적이 없다**
> 상태        "영원히 끝나지 않는 COLLECTING" 183 -> **2,921** (16배)
> ```
>
> ### 그래서 이 항목의 등급은 그대로 P0 다
>
> 데이터 공급이 멈추면 **기능이 아니라 관측이 먼저 죽는다.** 위 목록의 검사·큐·문서·상태는
> 전부 "코드가 틀렸다"가 아니라 **"확인할 수 없다"** 로 바뀐 것이고, 그 상태에서 나온
> 초록불은 근거가 되지 못한다(Sprint 224가 찾은 공허한 N+1 가드가 그 실례다).
>
> **등록은 여전히 승인 영역이라 하지 않았다.** 선행 조건은 전부 갖춰져 있다(아래 본문 참고).


**2026-08-18 재실측 — 여전히 참이다. 그리고 이 항목이 옳았다.**
`docs/CURRENT_STATE.md`/`docs/roadmap.md`의 Sprint 187 기록이 그 사이 "DOJOONPASS_DAILY가
매일 03:00에 정상 동작 중"이라고 적어 이 항목과 모순됐는데, 직접 조회한 결과
**그 작업은 없다.** 249개 중 0개 그대로다(`docs/BUGS.md` #123에 실측 근거 정리).
서로 다른 세션의 기록이 충돌하면 **다시 재는 쪽**이 답이다.

등록된 예약 작업 249개 중 **이 저장소를 가리키는 항목이 0개**다. `auction.crawl_date`
이력이 중단 시점을 그대로 보여 준다:

```
~08-01 매일 수집(08-01만 278건)  /  08-02~08-11 0건  /  08-12 9건(단발)  /  08-13~18 0건
```

**2026-08-18 추가 — 이제 이것이 막는 것이 하나 더 늘었다.** Sprint 189가 완성한
변경 기반 재수집(법원이 바꾸면 다음 주기에 문서/사진을 다시 받는 구조)도
**돌 기회 자체가 없다.** `document_version_log`가 0행인 이유가 이제 "기계가 없어서"가
아니라 "배치가 안 돌아서"로 바뀌었다.

지금 살아 있는 물건은 **9건뿐이고 전부 매각기일 2026-08-19**다. 즉 **2026-08-20부터
기본 검색 결과가 0건**이 된다. 이 문서 기준으로 "핵심 동선이 깨진다"에 해당한다.

> **[2026-08-19 Sprint 217 재실측 — 오늘이 그 마지막 날이다]**
>
> ```
> 예약 작업 249개 중 이 저장소를 가리키는 것        0개      (변동 없음)
> DOJOON* 이름의 작업                               없음     (변동 없음)
> auction_item.crawl_date 최신값                    2026-08-12
> 기일이 오늘 이후인 물건                            9건 — 전부 2026-08-19
> 기일이 **내일 이후**인 물건                        0건
> ```
>
> 즉 이 문단이 예고한 날이 내일이다. `register_scheduler_tasks.ps1` 를 dry-run 으로
> 다시 돌려 선행 조건도 재확인했다(배치 3개 OK / PATH python 해석 OK /
> 머신 PATH 불가 -> SYSTEM 계정 등록 금지 그대로). **등록만 남았고 그것은 승인 영역이다.**

배관 자체는 정상이다 — `auction` 1,876 ↔ `auction_item` 1,876, 법원 포함 대조 양방향
불일치 0건. `migrate_execute.py` 미실행분도 없다. **입력만 없다.**

조치는 `.\register_scheduler_tasks.ps1 -Apply` 한 줄이며 운영 환경 변경이라 승인 영역이다.
등록 전 검증은 전부 끝나 있다(인터프리터 폴백·errorlevel·logs 확보·실행창·락·retry·
예상 처리량 약 7분·이미지 첫 큐잉 동작 실증).

**★ 다만 "한 줄이면 끝"이 아니다** (2026-08-17 Sprint 180 정정 — 이 항목을 처음 쓸 때
빠뜨린 전제조건이다). dry-run 실측 결과:

```
머신 PATH 로 해석 가능 : 아니오 -> SYSTEM 계정 등록 금지
실행 방식              : 로그온 상태에서만 (비밀번호 불필요)
```

Python이 **사용자 프로필**에 설치돼 있어(`C:\Users\jhj12\AppData\Local\Programs\Python\Python312`) 머신 PATH로 해석되지
않는다. 그래서 기본 등록은 `LogonType Interactive` — **로그오프 상태에서는 실행되지
않는다.** 01:50~06:00에 기기가 로그인 화면에 있으면 등록해도 수집은 여전히 0건이다.

셋 중 하나를 함께 결정해야 한다:

1. 해당 시간대에 로그온 상태를 유지한다(현재 기본값 그대로 등록)
2. `-RunWhetherLoggedOn` 으로 등록한다 — **계정 비밀번호 입력이 필요**하다
3. Python을 머신 전역에 설치한 뒤 등록한다(그러면 SYSTEM 계정도 가능)

어느 쪽을 고를지는 운영 정책이라 임의로 정하지 않는다. 설계 근거와 절전/노트북 대비
(`-StartWhenAvailable`, `-DontStopIfGoingOnBatteries`, 4시간 제한)는
`docs/SPRINT112_SCHEDULER_HANDOFF.md` 참고.

> **[재정정 2026-08-18 Sprint 204] 아래 Sprint 187 문단은 더 이상 사실이 아니다.**
> 원문은 기록으로 남긴다 - 무엇을 근거로 그렇게 판단했는지가 남아야 같은 오독을 피한다.
>
> 세 축을 따로 재서 전부 일치했다(`audit_schedule_health.py`).
>
> ```
> 등록   schtasks 전체 249개 중 이 저장소를 가리키는 작업 0개
> 흔적   logs/daily_run.log 마지막 갱신 2026-08-11 17:05
>        (마지막 완료 표시는 "Finished at 2026-08-02  6:02:49")
> 데이터 auction_item.crawl_date 최신값 2026-08-12 (단발 9건)
> ```
>
> `DOJOONPASS_DAILY` 는 **지금 존재하지 않는다.** 그리고 그것이 08-17 에 실제로
> `run_daily.bat` 을 돌렸다면 `logs/daily_run.log` 가 그날 갱신됐어야 하는데
> 그렇지 않다. 즉 그 작업이 이 저장소 사본을 가리켰다는 근거가 없다.
>
> **교훈**: 작업 스케줄러의 `LastTaskResult 0` 은 "프로세스가 0으로 끝났다"는
> 뜻이지 "이 저장소에 무엇이 쌓였다"는 뜻이 아니다. 그 둘을 섞은 것이 Sprint 187 의
> 오독이고, 이제 `audit_schedule_health.py` 가 그 모순을 자동으로 지목한다.

**2026-08-17 Sprint 187 정정 — "등록 0개"는 이제 절반만 사실이다.** 재실측
(`Get-ScheduledTask`) 결과, **물건 기본정보 수집(`run_daily.bat`)은 실제로 매일
03:00에 돌고 있다**(작업명 `DOJOONPASS_DAILY`, 이 스크립트가 등록하는 이름과 달라서
아마 수동으로 등록됐을 것, 오늘도 성공). 위 검색 결과 0건 시나리오는 이 부분에는
더 이상 해당하지 않는다.

**그러나 사진/문서 수집(`run_doc_worker.bat`)과 우선순위 재계산
(`run_priority_refresh.bat`)은 여전히 등록된 적이 없다.** 이 둘이 없으면 물건은
계속 검색에 뜨지만 **사진도 문서도 영원히 "수집중"에 머문다** — 상세페이지의
사진/문서 카드가 사실상 죽어 있는 채로 출시되는 셈이다. 실측(2026-08-17):
`document_status` COLLECTING 6,180 / READY 555(과거 1회성), `document_queue`
pending 4,008행(계속 쌓이기만 함), `doc_raw` 0행. 조치는 여전히
`.\register_scheduler_tasks.ps1 -Apply` 한 줄이지만, **기존 `DOJOONPASS_DAILY`와
새로 등록될 `DojoonPass-DailyCrawl`(06:00)이 중복**되므로 적용 전에 하나를 정리할지
결정해야 한다(스크립트가 이제 이 경고를 자동으로 띄운다, 상세는
`docs/SPRINT187_DOCUMENT_PIPELINE_AUDIT.md` §5).

### P0-B. 지금 상태로 커밋하면 API가 부팅되지 않는다

Sprint 144~146에서 만든 실동작 모듈이 아직 `git add`되지 않았고, **추적 중인 파일이
그 미추적 파일을 import한다.** `git commit -a`(추적 파일만 스테이징)로 커밋하면:

```
ModuleNotFoundError: No module named 'api.http_cache'   (api/v1/documents.py:6)
```

라우터 등록 단계에서 죽으므로 검색·상세·문서·이미지가 동시에 정지한다(추적 파일 297개만
복사해 실제로 재현함). 깨지는 import 간선은 4개이고 `test_schema_hygiene.py` §6-B가
자동으로 다시 계산한다.

**반드시 `git add -A` 후 커밋할 것. `git commit -a`나 파일을 골라서 하는 커밋은 안 된다.**

### ~~P0-C. 이 환경의 `auction.db`에 마이그레이션 020이 빠져 검색/상세 API가 전면 500~~
→ **2026-08-17 09:03 적용 확인, 2026-08-18 Sprint 189에 실측 재확인 — 해결**

```
migration_history 20행 (020_create_auction_image.sql, 2026-08-17T09:03:19)
GET /api/v1/search?limit=3                 -> 200  total 9
GET /api/v1/item/505                       -> 200  사진 5장 READY / 문서 3종 READY
GET /api/v1/item/505/images/1              -> 200  image/jpeg 235,194B  (If-None-Match -> 304)
GET /api/v1/item/505/documents/APPRAISAL   -> 200  application/pdf 3,416,671B
test_schema_hygiene.py §3                  -> PASS
```

> ## ★ [2026-08-20 Sprint 238 재실측] **이 환경에서 다시 벌어졌다. P0로 되돌린다.**
>
> `*.db`는 gitignore 대상이라 환경마다 로컬 사본이 다르다는 경고가 바로 아래 문단에
> 이미 있었는데, 그 경고가 그대로 실현됐다. 이번 세션의 로컬 `auction.db`에
> `020_create_auction_image.sql`이 **다시** 미적용 상태다(`migration_history` 19행,
> `auction_image` 테이블 없음). 진짜 서버 프로세스를 띄우고 curl로 재현했다(테스트
> harness가 아니라 실제 `python api_server.py`):
>
> ```
> GET /api/v1/search?limit=3   -> 500  {"detail":"검색 처리 중 오류가 발생했습니다"}
> GET /api/v1/item/1           -> 500  Internal Server Error
>    traceback: api/v1/item.py:56  sqlite3.OperationalError: no such table: auction_image
> ```
>
> 세 개의 독립된 가드가 같은 결론에 도달했다: 라이브 curl 재현, `test_bootstrap.py`의
> fresh-DB 컬럼/인덱스 드리프트 감지, `test_schema_hygiene.py` §3의 migration_history
> 완전성 검사. **검색과 상세 둘 다 100% 500**이며, 이 결손 하나가 `run_python_tests.py`
> 실패 12건 중 8건 + `node --test` 다수 실패의 공통 원인이다(상세는
> `docs/SPRINT238_LIVE_REGRESSION_AND_BATCHING_CONFIRM.md` §1).
>
> 조치는 이전과 동일하고 여전히 승인 영역이라 이 세션은 실행하지 않았다:
> ```
> python -m storage.migrations.run_migrations
> python test_schema_hygiene.py   # §3 통과 확인
> ```
> **배포/운영 환경의 `auction.db`는 이 세션 범위 밖이라 별도로 확인 필요.**
>
> ## ★ [2026-08-21 Sprint 239] **근본 원인은 그대로지만, 더 이상 API 전체를 죽이지 않는다**
>
> migration 020을 적용하지 않았다(여전히 승인 영역). 대신 `docs/BUGS.md` #177에서
> `fetch_thumbnail_seqs()`(검색 썸네일) / `item.py`(상세 사진 목록) / `images.py`(사진
> 서빙) 세 곳의 `sqlite3.OperationalError`를 narrow하게 흡수해, 이 결손이 있어도
> 검색·상세가 "사진 없음"과 같은 모양으로 계속 동작하도록 고쳤다. 실제 프로세스로
> 재확인(운영 방식 그대로 재현):
>
> ```
> GET /api/v1/search?limit=3   -> 200  total 124  (이전: 500)
> GET /api/v1/item/1           -> 200  images: []  (이전: 500)
> GET /api/v1/item/53          -> 200  documents[].available: true, 실파일 다운로드 200
> ```
>
> `python run_python_tests.py` 37→**45**, `node --test` **137/137 PASS**(이전 96 실패
> 전부 이 결손의 파급이었다). 새 회귀 `test_asset_pipeline.py::test_missing_auction_image_table_degrades_not_crashes`
> 가 이 동작과 narrow-catch 둘 다 mutation으로 검증한다(3개 파일 각각 try/except를
> 제거해 재현 → FAIL 확인 → 원복 → PASS 확인, 이번 세션에서 직접 수행).
>
> **여전히 migration 020 적용 전까지는:** 썸네일/사진 자체는 나오지 않는다(사진이
> DB에 없다는 사실은 바뀌지 않았다 — 이번 수정은 "결손이 있어도 안 죽는다"이지
> "결손을 없앤다"가 아니다). `test_bootstrap.py`/`test_schema_hygiene.py` 드리프트
> 가드는 의도대로 계속 FAIL로 남아 있다.

아래 원문은 발견 당시 기록이다.

### P0-C. **[2026-08-17 신규, Sprint 187]** 이 환경의 `auction.db`에 마이그레이션
020이 빠져 검색/상세 API가 전면 500

`api_server.py`를 띄우고 직접 확인했다:

```
GET /api/v1/search?limit=3   -> 500  {"detail":"검색 처리 중 오류가 발생했습니다"}
GET /api/v1/item/58          -> 500  Internal Server Error
```

원인: `migration_history`가 019까지만 기록돼 있고 `020_create_auction_image.sql`이
적용되지 않아 `auction_image` 테이블이 없다. `api/v1/search.py`/`api/v1/item.py`가
이 테이블을 try/except 없이 직접 조회한다 — **검색과 상세 둘 다, 사진/문서 유무와
무관하게 100% 500이다.** `docs/BUGS.md` #117 / `docs/SPRINT187_DOCUMENT_PIPELINE_AUDIT.md` §5 참고.

`*.db`는 gitignore 대상이라 환경마다 로컬 사본이 다를 수 있다 — **실제 출시
환경(서버)에서도 같은 방식으로 마이그레이션 적용 여부를 직접 확인할 것.** 이 세션의
발견을 "이 컴퓨터만의 문제"로 넘기지 말 것.

조치(DB 스키마 변경, 승인 필요):
```bash
python -m storage.migrations.run_migrations
python test_schema_hygiene.py   # §3 통과 확인
```

분류 기준

- **P0** — 이게 남아 있으면 출시할 수 없다(돈을 받을 수 없거나, 핵심 동선이 깨진다)
- **P1** — 출시는 가능하지만 사용자가 즉시 체감하거나 운영이 불가능하다
- **P2** — 출시 후 처리해도 되는 품질/구조 부채

---

## 도메인별 현황 (2026-08-07 코드 기준)

| 도메인 | 상태 | 근거 |
|---|---|---|
| 회원가입 / 로그인 | ✅ | Supabase Auth 실동작, `proxy.ts` 세션 게이트(구 `middleware.ts`), Open Redirect 방어(`sanitizeRedirectPath`) |
| 로그아웃 | ⚠️ | 동작하지만 노출 경로가 `/properties` 한 곳뿐 (P1) |
| 크롤링 데이터 무결성 | ✅ | `auction_case`(#14) · `auction`/`auction_item`(#18) 전부 법원 포함 식별키로 해결. ID 전수 Audit 결과 orphan/중복/불일치 **0건** |
| 검색 | ✅ | 정렬 화이트리스트·페이지네이션·인덱스 확인, 회귀 커버 |
| 검색조건 저장 | ✅ | 서버측 입력 검증 추가(2026-08-07), 소유권 격리, 회귀 커버 |
| 최근조회 | ✅ | 중복 행 없음, 회귀 커버 |
| 즐겨찾기 | ✅ | N+1 제거 완료, 중복/소유권 처리, 회귀 커버 |
| 상세조회 | ✅ | 복합키 Migration 이후 `case.court_code` 일치 회귀로 방어 |
| 등기부 신청 | ✅ | 구독 게이트·월 한도·동시성(`BEGIN IMMEDIATE`)·초과결제 연결까지 회귀 커버 |
| 등기부 발급/전달 | ⚠️ | 다운로드 엔진은 완성. **발급은 운영자 수동**(자동화는 Beta v2) |
| 결제 | ❌ | `MockProvider` — 실제로 돈을 받을 수 없다 (P0). 단 **결제 로그/Webhook 구조는 선구축 완료**(실연동 시 Provider만 채우면 됨) |
| Subscription | ✅ | 플랜/할인/기간/한도 서버 검증, 플랜 tie-break 버그 수정(2026-08-07) |
| 관리자 | ❌ | API 완성 + **SUPER_ADMIN/ADMIN 2단계 권한**·등기부 한도 조정 추가. ~~2026-08-16: 두 키 설정 확인, 정상 403/200~~ → **2026-08-20 재실측(Sprint 233): 두 키가 다시 `.env` 에서 사라져 13개 라우트 전부 500 — Admin API 전체 사용 불가. P1 이 아니라 P0 로 되돌림**(위 P0-2 참고) |
| 문서 | ✅ | 2026-08-07 전수 감사 — 코드와 어긋난 서술 정정 완료 + `API_KEY_CHECKLIST.md` 신설 |
| Runtime | ✅ | Type Check / Lint / Build 전부 통과. **2026-08-08(Sprint 32) 최초로 HTTP 레벨 실제 실행**: `test_api_regression.py` **380검사**(377 + 신규 JWT 적대적 케이스 3건) 전부 PASS, `test_subscription_policy.py` **48항목** 전부 PASS(연속 2회 재실행으로 재현성 확인, 잔여 QA 데이터 0건) |
| 로깅/추적 | ⚠️ | 2026-08-07 API 서버 로깅 설정 신설(그 전엔 `logger.info` 전량 유실). 외부 수집(Sentry 등)은 없음 (P2) |

---

## P0 — 출시 차단

### ~~P0-0. 로컬 `auction.db`/`storage/migrations/`가 문서 기록과 불일치~~ → **2026-08-08 복구 완료**

- 발견(2026-08-08 오전): 이 작업 디렉터리의 `auction.db`/`storage/migrations/`(둘 다 git
  비추적)가 Migration 010~015 이전 상태로 되돌아가 있었다 — `docs/BUGS.md` #18(법원 무시
  UNIQUE 키로 인한 데이터 소실)이 이 DB 파일 기준 미해결이었고, `audit_logs`/`payment_logs`/
  `payment_webhooks`/`registry_credits`/`registry_credit_logs` 5개 테이블도 없었다. 실측
  중 `migrate_execute.py`(정상 코드)가 이 스키마에 대고 실행되면 `INSERT INTO auction_case`에서
  `court_code` 컬럼 부재로 **매일 크롤링 파이프라인이 크래시**하는 것도 함께 확인됨(Runtime Bug)
- 해결(같은 날, CTO 승인): `storage/migrations/010~016.sql` 재작성(코드의 실제 INSERT/SELECT
  문에서 컬럼 추출) → 백업 → 사본 리허설(FK ON/OFF 양쪽) → 실제 `auction.db` 적용 → 30개
  무결성 검증 항목 전부 통과 → `storage/database.py`(`upsert_batch()` court_code 안전화,
  `PRAGMA foreign_keys=ON`, `CREATE_TABLE_SQL` 정정) / `storage/migrate_v4_1.py`(fresh clone도
  같은 제약) 함께 수정 → fresh-clone 전체 부트스트랩(`init_db`→`migrate_v4_1`→`run_migrations`)
  재현 검증까지 완료. 상세는 `docs/CHANGELOG.md` 2026-08-08(Sprint 30) 항목,
  회귀는 `test_auction_identity.py`(신규, 26검사 전부 PASS) 참고
- **`.env`의 `SUPABASE_JWT_SECRET` 부재는 별개 사안으로 여전히 남아 있다** — `.env` 수정은
  승인 목록에 없어 이번에도 Skip. 아래 P0-3 참고

### P0-1. KG이니시스 실연동 미완료 (결제 불가)

- `KGInicisProvider`의 6개 메서드가 전부 `NotImplementedError`(2026-08-07 클래스 자리만 신설).
  현재 `PAYMENT_PROVIDER` 미설정 = `MockProvider` = **결제가 항상 성공으로 기록되지만 실제 입금은 없다.**
- 선행 조건: KG이니시스 사업자 계약·심사 → `KG_MID`/`KG_API_KEY`/`KG_SECRET_KEY` 발급
- 함께 필요: 환불(`cancel_payment`) / Webhook 수신(`handle_webhook`) 엔드포인트 신규 구현 —
  두 메서드는 인터페이스에만 있고 호출부가 없다
- **승인/외부 절차 필요 → 코드로 해결 불가**

### P0-2. `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` — **2026-08-20 Sprint 238 재실측: 다시 돌아왔다**

> ## ★ [2026-08-20 Sprint 238 재실측] **바로 아래 Sprint 233(같은 날 이전 세션) 기록과 다르다 — 지금은 있다**
>
> `.env` 변동이 이 저장소에서 이미 여러 차례 관찰된 패턴 그대로 다시 일어났다. 비밀값은
> 열람하지 않고 `python-dotenv`(실제 앱이 쓰는 로더)로 존재 여부와 길이만 확인했다:
>
> ```
> ADMIN_API_KEY         PRESENT (75자)
> SUPER_ADMIN_API_KEY   PRESENT (74자)
> ```
>
> 실제 서버(진짜 `python api_server.py` 프로세스, curl)로 재확인:
>
> ```
> GET /api/v1/admin/users     (토큰 없음)   -> 403  (500 이 아니다)
> GET /api/v1/admin/payments  (토큰 없음)   -> 403
> ```
>
> **Admin API는 지금 사용 가능하다** — 키를 아는 사람은 정상적으로 쓸 수 있고, 키 없는
> 요청은 설정 오류(500)가 아니라 정상적인 권한 거부(403)를 받는다. 다만 이 값이 세션마다
> 뒤집혀 온 이력을 볼 때 **다음 세션에 다시 사라져 있을 수 있다** — `.env`는 영속성이
> 보장되지 않는 값으로 계속 취급해야 한다. `PAYMENT_WEBHOOK_SECRET`은 여전히 없어
> Webhook 수신은 계속 fail-closed다(변동 없음).

> ## ★ [2026-08-20 Sprint 233 재실측, 이 문서의 더 이전 세션 기록] **Admin API 전체가 다시 사용 불가다**
>
> 바로 아래 2026-08-16(Sprint 134) 기록은 *"둘 다 설정돼 있다 / 이제 403"* 이라고 적고
> 있다. **오늘 다시 재니 그렇지 않다.** 이 저장소가 이미 두 번 겪은 `.env` 변동이
> 세 번째로 일어났다(08-08 있음 -> 08-13 없음 -> 08-16 있음 -> **08-20 없음**).
>
> 비밀값은 열람하지 않고 **두 가지 독립된 방법**으로 확인했다.
>
> ```
> (1) .env 의 변수명 존재 여부
>       ADMIN_API_KEY           이름 **없음**
>       SUPER_ADMIN_API_KEY     이름 **없음**
>       PAYMENT_WEBHOOK_SECRET  이름 **없음**
>       SUPABASE_JWT_SECRET     이름 있음 / 값 채워짐(88자)   <- 이것만 살아 있다
>
> (2) 실제 서버 응답 (OpenAPI 스키마에서 뽑은 **전 라우트**를 토큰 없이 호출)
>       /api/v1/admin/* 13개 라우트 전부  ->  500 "관리자 키 미설정"
>       (403 이 아니다 — `_require_role()` 이 키 부재를 먼저 검사한다)
> ```
>
> 두 방법이 일치하므로 측정 오류가 아니다.
>
> ### 영향
>
> ```
> 등기부 신청 상태 변경        불가
> 결제 환불 / 웹훅 재처리       불가
> 구독 / 사용자 / 감사 로그 조회  불가
> ```
>
> 즉 **운영자가 할 수 있는 일이 하나도 없다.** 아래 준비도 표의
> "이제 정상 403/200 응답 — UI 없음만 남음 (P1)" 은 **오늘 기준 사실이 아니다.**
>
> ### 곁다리로 확인한 것 — 인증 없이 500 을 만들 수 있다
>
> 토큰이 전혀 없는 요청이 13개 라우트에서 500 을 만든다. 이 저장소는 Sprint 146 에서
> *"인증 없이 500을 만들 수 있었다"* 를 결함으로 보고 400 으로 고친 전례가 있다.
> 다만 여기는 **의도된 동작**으로 코드에 명시돼 있다
> (`api/v1/admin.py`: *"두 키 모두 없으면 Admin API 자체를 쓸 수 없다(기존 동작 유지: 500)"*).
> 키가 채워지면 자연히 403 이 되므로 **이번에는 코드를 바꾸지 않았다** —
> 근본 원인은 코드가 아니라 `.env` 이고, `.env` 수정은 승인 영역이다.
>
> ### 조치 (승인 필요)
>
> ```
> python -c "import secrets; print(secrets.token_urlsafe(32))"   # 값 생성
> .env 에 ADMIN_API_KEY / SUPER_ADMIN_API_KEY 이름으로 추가
> ```
>
> **이 세션은 `.env` 를 열어 값을 쓰지 않았다(승인 영역).**

<details>
<summary>2026-08-16 Sprint 134 기록(당시엔 설정돼 있었다 — 보존)</summary>

### ~~2026-08-16 재실측: 지금은 둘 다 설정돼 있다(Sprint 134)~~

> **2026-08-16 재정정(Sprint 134, Documentation Drift Audit)** ― 아래 2026-08-13
> 실측(Sprint 78) 이후 `.env`가 바뀌었다. **비밀값을 열람하지 않고** 같은 방식(이름
> 존재 여부 + `os.getenv()` truthy 여부 + 실제 서버 응답)으로 다시 확인했다:
>
> ```
> os.getenv() truthy       ADMIN_API_KEY        True   <- 2026-08-13엔 이름 자체가 없었다
>                           SUPER_ADMIN_API_KEY  True
>                           PAYMENT_WEBHOOK_SECRET False <- 이것만 여전히 비어 있다
> 실제 서버 응답(키 없이)   /admin/users /admin/payments /admin/subscriptions /admin/audit-logs
>                           전부 403 "권한이 없습니다" (2026-08-13엔 500 "관리자 키 미설정"이었다)
> ```
>
> **즉 "Admin API 전체가 지금도 사용 불가"는 더 이상 사실이 아니다.** 키를 아는
> 사람은 정상적으로 Admin API를 쓸 수 있고, 키 없는/틀린 요청은 500(설정 오류)이
> 아니라 403(정상적인 권한 거부)을 받는다 — 이 도메인은 더 이상 P0가 아니다.
> `PAYMENT_WEBHOOK_SECRET`은 여전히 비어 있어 Webhook 수신은 계속 fail-closed(401)
> 상태다(아래 원문 그대로 유효). `.env`는 승인 영역이라 이 세션이 바꾼 것이 아니다
> — 언제/누가 채웠는지는 이 세션 범위 밖.

</details>

<details>
<summary>2026-08-13 Sprint 78 실측 원문(정정 이전 기록 — 지우지 않고 보존)</summary>

미설정 확정 (2026-08-13 실측)

> **2026-08-13 실측 (Sprint 78 Release Audit)** ― "값 유효성 미확인"이던 이 항목을
> **비밀값을 열람하지 않고** 확정했다. 이름 존재 여부(값이 아니라 키 이름만)와 서버 응답
> 두 가지로 판정할 수 있다.
>
> ```
> .env 의 이름            ADMIN_API_KEY        없음   <- 2026-08-08 기록("이름은 있음")과 다르다
>                         SUPER_ADMIN_API_KEY  없음
>                         PAYMENT_WEBHOOK_SECRET 없음  <- Webhook 서명 검증도 fail-closed 상태
> 실제 서버 응답(키 없이)   /admin/users /admin/payments /admin/subscriptions /admin/audit-logs
>                         전부 500 "관리자 키 미설정"
> ```
>
> 즉 **Admin API 전체가 지금도 사용 불가**이며, 준비도 표의 "키 미설정으로 현재 전체 500"은
> 정확하다. 값을 읽지 않고도 판정된 이유: `os.getenv()`가 빈 값을 falsy로 주고
> `_require_role()`이 두 키가 모두 없을 때 500을 반환하기 때문이다(코드 계약).
>
> `PAYMENT_WEBHOOK_SECRET`도 없어 `MockProvider.verify_webhook_signature()`가 설계대로
> 항상 False다(fail-closed) — Webhook 수신은 401로 막힌다. 이것은 결함이 아니라 의도된
> 안전 기본값이지만, **결제 Webhook을 실제로 받으려면 이 값도 필요**하다는 점을 함께 기록한다.
>
> `.env` 수정은 승인 영역이라 손대지 않았다. 값 생성 명령은 아래 그대로 유효하다.

- **2026-08-08 기록(당시)**: `.env`에 `ADMIN_API_KEY=`/`SUPER_ADMIN_API_KEY=` **변수명 자체는
  존재한다**(이전 문서가 "미설정"으로 기록했던 것과 달리 이름은 있음). 다만 이 세션은
  Secret 값을 열람/출력하지 않는 원칙이라 **실제로 유효한 값이 채워져 있는지는 확인하지
  않았다** — 값이 비어 있거나 형식이 잘못됐다면 여전히 `/api/v1/admin/*` 전체가
  `500 "관리자 키 미설정"`이 된다. 사용자가 직접 `.env`를 열어 값이 채워져 있는지
  확인 필요
- 값이 비어 있다면 생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- **`.env` 수정은 승인 필요 → 이 세션에서는 확인만 가능, 수정 불가**

</details>

### P0-3. Supabase Site URL / Redirect URLs 미확인 (회원가입 완료 불가 위험)

- `signUpAction`은 "이메일을 확인하여 가입을 완료해주세요"를 반환한다 — 가입 확인 메일의 링크는
  Supabase 대시보드의 **Authentication → URL Configuration** 설정을 따라간다.
- 이 값이 `localhost:3000`인 채로 배포되면 **운영 사용자가 회원가입을 끝낼 수 없다.**
  코드로는 확인할 수 없는 외부 대시보드 설정이라 배포 전 반드시 눈으로 확인해야 한다.
- 2026-08-07 신규 등록 (`docs/API_KEY_CHECKLIST.md` 5절)

### ~~P0-4. `.env`에 `SUPABASE_JWT_SECRET` 변수명 자체가 없음~~ → **2026-08-13 이 환경에서 해소 확인 (Sprint 78)**

> **2026-08-13 실측 (Sprint 78 Release Audit)** ― 아래 서술은 **이미 낡았다.** 이 작업
> 환경의 `.env`를 이름 기준으로 확인한 결과(값은 열람하지 않았다):
>
> ```
> .env 의 변수명        SUPABASE_JWT_SECRET  있음 (값 88자)
>                       JWT_SECRET           없음  <- 아래 "조치"대로 이름이 바뀌었다
>                       SUPABASE_URL         있음 (값은 비어 있음)
> .env.local            NEXT_PUBLIC_SUPABASE_URL  있음 (40자)
> ```
>
> 즉 아래 §조치의 "`JWT_SECRET`의 값을 `SUPABASE_JWT_SECRET` 이름으로 옮긴다"가 **이미
> 수행돼 있다.** `SUPABASE_URL`은 이름만 있고 값이 비어 있는데, `api/auth.py`가
> `SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL` 순으로 읽으므로 JWKS 주소는 정상 구성된다
> (이 폴백 경로는 Sprint 78에 회귀로 고정했다 — `test_auth_jwt.py` §6).
>
> **다만 이것이 증명하는 것은 "이 로컬 환경의 이름이 맞다"까지다.** 값이 진짜 Supabase JWT
> Signing Secret인지는 실제 Supabase 발급 토큰으로만 확인할 수 있고(외부 의존 → SKIP),
> 운영 배포 환경의 `.env`는 여전히 별도로 채워야 한다. `.env` 수정은 승인 영역이라
> 이 세션에서도 손대지 않았다 — **확인만** 했다.

<details><summary>원래 서술 (2026-08-08~08-09 기준, 기록 보존)</summary>

### P0-4. **[2026-08-08 신규]** `.env`에 `SUPABASE_JWT_SECRET` 변수명 자체가 없음 (인증 전체 불가)

- `api/auth.py:9`가 `os.getenv("SUPABASE_JWT_SECRET")`을 읽는데, 현재 `.env`에는 이 이름이
  없다(`JWT_SECRET`이라는 **다른 이름**만 존재 — `docs/ENVIRONMENT_VARIABLES.md`가 이미
  경고해온 바로 그 이름 실수). 값이 아니라 **변수명 자체가 코드와 불일치**하므로, 어떤 값을
  넣어도 `JWT_SECRET`이라는 이름으로는 작동하지 않는다
- 영향: `get_current_user()`가 `500 "JWT Secret 미설정"`을 반환 — 인증이 필요한 API
  (favorites/recent-items/search-presets/registry-requests/payments) **전체가 막힌다**.
- **2026-08-08 갱신**: `python-jose`는 승인 하에 설치 완료(P1-x 아래 갱신 참고). 회귀 스크립트
  (`test_api_regression.py`)는 `.env`에 이 이름이 없을 때만 **이 프로세스 안에서만 유효한
  합성 값**을 주입하도록 수정해(`ADMIN_API_KEY`와 동일한 기존 패턴) 380검사(377+신규 3건) 전부
  실제 HTTP 레벨로 통과했다 — **이것은 인가·서명 검증 로직 자체가 옳다는 증거**이지, 실제
  운영 `.env`가 고쳐졌다는 뜻이 아니다. 운영 배포에는 여전히 `.env`에 정확한 이름으로 진짜
  Supabase JWT Secret을 넣어야 한다 — 이 항목은 **여전히 P0**
- **2026-08-09 분류 확정**(사용자 요청, `JWT_SECRET`/`SUPABASE_JWT_SECRET`/`NEXTAUTH_SECRET`
  3개 변수명 코드 전체 재검색, 값은 열람하지 않음):
  - `SUPABASE_JWT_SECRET` — **실제로 별도 필요함**(분류 1). `api/auth.py`(모듈 최상단 로드 +
    `get_current_user()`), `api/v1/item.py`/`api/v1/search.py`(선택적 인증 경로),
    `test_api_regression.py`(테스트 토큰 서명)까지 전부 이 이름 하나로 통일되어 있다.
    다른 이름으로 대체하도록 설계된 적이 없다(분류 2 해당 없음)
  - `JWT_SECRET`(현재 `.env`에 있는 이름) — 코드 참조 **0건**. **분류 3(잘못된 변수명으로
    남은 값)**. Supabase의 실제 JWT Signing Secret일 가능성이 높지만 이름이 코드와 달라
    인식되지 않는다
  - `NEXTAUTH_SECRET`/`NEXTAUTH_URL` — 코드 참조 0건, `next-auth` 패키지 자체도 참조 0건.
    **분류 3(완전히 무관한 잔재)** — 이 프로젝트는 NextAuth.js를 쓰지 않는다(Auth는
    Supabase Auth로 확정, `docs/decision-log.md` "Authentication"). 옮겨 담을 대상이
    아니라 그냥 미사용 항목
- 조치: `.env`에서 `JWT_SECRET`의 **값**을 `SUPABASE_JWT_SECRET`이라는 **이름**으로 옮기거나
  (기존 `JWT_SECRET` 항목은 그대로 둬도 무해 — 코드가 안 읽으므로), 같은 값을
  `SUPABASE_JWT_SECRET`이라는 이름으로 추가 입력하면 해결된다 — Supabase 대시보드
  → Project Settings → API → JWT Settings에서 같은 값을 다시 확인 가능. `NEXTAUTH_SECRET`은
  건드릴 필요 없음(무관)
- **`.env` 수정은 승인 필요 → 이 세션에서는 확인만 가능, 수정 불가**. 사용자가 `.env`에서
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`/`SUPABASE_SERVICE_ROLE_KEY`를 이미 입력해 둔 것으로
  보아(2026-08-08, `docs/API_KEY_CHECKLIST.md` 8절) Supabase 키 자체는 준비돼 있을 가능성이
  높다 — `SUPABASE_JWT_SECRET`이라는 정확한 이름으로 옮겨 담는 작업만 남았을 수 있다

</details>

---

## P1 — 출시는 가능하나 즉시 체감/운영 부담

### ~~P1-0. 레거시 `auction` 키에 법원이 빠져 물건이 소실됨~~ → **2026-08-07 해결**

CTO 승인 하에 Migration 012/013 실행. `auction` → `UNIQUE(court_code, case_no, item_no)`,
`auction_item` → `UNIQUE(case_id, item_no)`. id·전 컬럼 100% 보존, 충돌 시 두 법원 공존 확인.
회귀 방어: `test_api_regression.py` 22번, `test_subscription_policy.py` 7번.

### P1-1. `/properties` 첫 화면의 id 체계 불일치 (`docs/BUGS.md` #17)

- `/`가 로그인 사용자를 `/properties`로 보내는데, 그 화면은 Supabase `properties` 테이블을
  조회하면서 링크는 FastAPI `auction_item` id 기준인 `/properties/{id}`로 건다 —
  **로그인 직후 첫 화면에서 물건을 클릭하면 엉뚱한 물건이 열리거나 404.**
- 우회 동선은 있다(`PrimaryNav`의 "검색" → `/search`는 정상).
- 처리 방향(FastAPI 전환 vs 화면 폐지 후 `/`를 `/search`로)이 **Spec 결정 사항**.

### P1-2. 로그아웃 노출 경로가 1곳뿐 (`docs/BUGS.md` #15)

- `/search`, `/favorites`, `/properties/recent`에서는 로그아웃 불가(`PrimaryNav`에 없음).
- 하필 유일한 경로가 P1-1의 문제 화면이다.
- 배치 위치가 **Spec 결정 사항**.

### P1-3. Admin 화면(UI) 부재

- 운영자가 curl / Swagger UI로만 등기부 상태를 관리해야 한다.
- 신규 화면이라 **Spec 결정 필요**.

### P1-4. Admin 인증이 여전히 키 기반 — 개별 운영자를 특정할 수 없다

- 2026-08-07 **SUPER_ADMIN / ADMIN 2단계 권한을 도입**해 과금 영향 조작(등기부 한도 조정)은
  분리했다. 감사 로그에도 수행 등급이 남는다.
- 그러나 등급 안에서는 여전히 공유키라 **"어느 사람이" 했는지는 알 수 없다.**
  키 유출 시 그 등급 권한 전체가 노출되는 것도 그대로다.
- 사용자 단위 식별이 필요하면 Supabase custom claim 기반 인증으로 교체해야 한다 — **승인 필요**.

### P1-5. Rate Limit 전무

- Admin 키 무차별 대입, 검색/결제 API 남용을 막는 장치가 없다.
- 미들웨어/패키지 도입 필요 — **패키지 설치 승인 필요**.

---

## P2 — 출시 후 처리

- `src/login/`이 라우팅되지 않는 죽은 코드로 남아 있고, 금지된 옛 브랜드명
  "도준 경매 패스"를 사용 중 — **삭제 승인 필요**
- `properties/page.tsx`의 지역 `formatPrice`가 공용 구현과 다르게 동작(`0` → `"0.0억"`).
  P1-1과 같은 화면이라 함께 처리하는 것이 맞다
- `LIKE` 필터의 `%`/`_` 이스케이프 미처리 — 보안 문제는 아니고 와일드카드 의미론.
  `search.py` 전체 검색 동작이 바뀌므로 PM 확인 후
- Admin 목록의 `JOIN auction_item`이 INNER — 물건이 사라진 신청이 목록에서 통째로 빠진다
  (현재 DELETE 경로가 없어 실제 발생은 안 함)
- **[2026-08-07 신규]** 활성 구독 조회·초과결제 대상 선택 쿼리가 `user_id` 인덱스가 아니라
  `status` 인덱스를 타고 TEMP B-TREE 정렬을 만든다(실행계획 실측). `(user_id, status)` 복합
  인덱스가 적합하나 **스키마 변경 승인 필요**
- **[2026-08-07 신규]** `favorites` / `payments` / `registry-requests` 목록에 **LIMIT이 없다.**
  현재 사용자당 최대 보유 행이 0건이라 실제 문제는 없지만 구조적으로 무제한이다.
  페이지네이션 도입은 응답 구조 변경(Breaking Change)이라 승인 필요
- **[2026-08-07 신규]** 외부 로그/예외 수집(Sentry 등) 없음 — 서버 로깅 설정은 2026-08-07
  신설했으나 stdout 스트림뿐이라 운영에서 과거 로그를 되짚기 어렵다 (**CTO 보류 지정**)
- ~~`PRAGMA foreign_keys = 0`~~ → **2026-08-07 해결**(Sprint 28)
- **[2026-08-07 신규, 환경 문제] 저장소가 OneDrive 동기화 폴더 안에 있어 빌드가 간헐적으로
  실패한다.** `npm run build`가 이전 빌드ID 디렉터리(`.next/static/<buildId>/`, 매니페스트 3개)를
  정리하려 할 때 OneDrive가 잠그고 있으면 `EPERM ... unlink`가 난다. 이번 세션에서 두 번 발생했고
  둘 다 그 디렉터리를 **삭제하지 않고 옮겨서** 해결했다.
  근본 해결은 (a) 저장소를 OneDrive 밖으로 옮기거나 (b) `.next`를 OneDrive 동기화 제외로 설정하는
  것이다 — 둘 다 OS/외부 설정이라 **승인 필요**. 코드 문제가 아니며 Type Check·Lint는 항상 정상이다
  - **[2026-08-17 보강 — 같은 원인의 두 번째 축: 파일 잠금이 아니라 '용량']**
    지금까지 이 항목은 `.next` / `logs/`의 **잠금** 문제로만 다뤄졌다. 2026-08-17 실측에서
    같은 원인이 **훨씬 큰 축**을 하나 더 갖고 있음을 확인했다 — 크롤링한 법원 문서·사진
    자체가 `documents/`에 쌓이고, 그 경로도 OneDrive 동기화 대상이다.

    ```
    현재            documents/  1,320 MB  (767 파일)   <- 이미 동기화 중
    현 corpus 완주  약  13.1 GB  (1,876 물건 전부 수집 시)
    1만 물건        약  69.9 GB
    10만 물건       약 699.2 GB
    ```

    로컬 디스크는 여유가 있다(실측 832.8 GB free / 930.6 GB). 문제는 **OneDrive 쪽**이다:
    (a) 계정 저장 용량(무료 5GB / M365 1TB)을 초과하면 동기화가 멈추고,
    (b) 매일 새 문서가 업로드되어 대역폭을 계속 먹으며,
    (c) 동기화 중인 파일을 doc_worker가 쓰는 순간 위와 같은 잠금 충돌이 난다
        (실제로 2026-08-17에 `documents/` 하위를 정리하다 `PermissionError [WinError 5]`를
         만났고, PowerShell `Remove-Item -Force`로 우회했다 — BUGS #35와 같은 계열).

    **`documents/`는 재생성 가능한 크롤 산출물이고 git도 무시한다**(`.gitignore`).
    백업 가치가 없으므로 OneDrive 동기화에서 제외하는 것이 맞다. 조치는 OS 설정이라
    **승인 필요 — 이번 스프린트에서 수행하지 않았다.**
    권장: OneDrive 설정 > "폴더 백업/동기화 선택"에서 `dojoonpass/documents` 제외,
    또는 저장소 전체를 OneDrive 밖(예: `C:\dev\dojoonpass`)으로 이전.
- **[2026-08-07 신규]** Admin 실패 응답이 `{"detail": ...}`(HTTPException)이라 envelope·Error Code를
  쓰지 않는다. 통일하려면 클라이언트가 `status_code`로 분기하는 방식을 바꿔야 해 **Spec 결정 필요**
- **[2026-08-07 신규]** Soft Delete가 컬럼 추가까지만 적용됐다. 실제 전환은
  `UNIQUE(user_id,item_id)` 때문에 재등록이 막히는 문제를 먼저 풀어야 한다
- DB 백업 체계 없음(수동 타임스탬프 백업만), SQLite 단일 파일 운영
- 크롤러 계열 스크립트(`test_db.py` 등)는 이 환경에서 실행되지 않는다 — 이유가 두 겹이다:
  (1) selenium 미설치, (2) **2026-08-11부터 `ALLOW_LIVE_CRAWL=1` 없이는 실행 자체가 막힌다**
  (BUGS #51 — 이름은 test_*.py지만 assert가 0개이고 실제 법원 사이트에 접속한다).
  회귀 스윕은 이 셋을 '실패'가 아니라 '설계상 건너뜀'으로 분류해야 한다
  (패키지 설치 승인 필요)
- 권리분석 화면이 스텁 — `registry_rights` 테이블 + OCR/파싱 파이프라인 신규 구축 필요(Beta v2)
- 등기부 발급기관 자동 연동(Beta v2 범위, Beta v1 출시를 막지 않음)

---

## 이번 회차에 새로 등록된 것만

- **P0-3** Supabase Site URL / Redirect URLs 미확인 — 2026-08-07 신규 발견
- **P1-1** `/properties` id 불일치 — 2026-08-07 신규 발견
- **P2** `formatPrice` 지역 구현 차이 — 2026-08-07 신규 발견
- **P2** `LIKE` 이스케이프 / Admin INNER JOIN — 2026-08-07 신규 발견
- **P2** `.next` 잔여 아티팩트로 build 실패 / Admin 응답 형식 미통일 / Soft Delete 미전환 — 2026-08-07 신규
- **P2** 구독/초과결제 쿼리의 인덱스 선택 · 목록 LIMIT 부재 · 외부 로그 수집 부재 — 2026-08-07 신규 발견

그 외 P0/P1 항목은 이전 회차에서 이미 등록된 것으로, 상태만 갱신했다.

**Sprint 28에서 해소되어 목록에서 내려간 항목**: FK 미강제(P2), 결제/구독 상태 전이 검증 부재,
Admin 작업 이력 추적 불가, 무료횟수 변동 추적 불가, Error Code·Enum 산재.

**Sprint 27에서 해소되어 목록에서 내려간 항목**: P1-0(레거시 `auction` 키 물건 소실, #18),
프론트/서버 가격 이중 관리(`PLAN_OPTIONS` 제거 + Plan API), Admin 단일 등급(2단계 도입),
결제 궤적 추적 불가(payment_logs), 등기부 한도 CS 대응 수단 부재(registry_credits).

Sprint 26에서 해소되어 **목록에서 내려간 항목**: Lint 오류 2건, 구독 플랜 tie-break 버그,
Admin 목록 페이지네이션 비결정성, `layout.tsx` 기본 메타데이터, 문서-코드 불일치 다수,
**API 서버 로깅 설정 부재**(감사 로그가 전량 유실되던 문제), **OpenAPI Duplicate Operation ID**,
미사용 import 2건.


### 운영 점검 도구: `audit_asset_integrity.py` (2026-08-18 Sprint 192 신설)

배포 전/후에 **DB 기록과 디스크 실체가 일치하는지** 한 번에 확인한다. 읽기 전용이라
언제 돌려도 안전하고, **종료 코드로 판단**할 수 있다.

```bash
python audit_asset_integrity.py            # 0=정상 / 1=어긋남 / 2=실행 실패
python audit_asset_integrity.py --selftest # 감사기가 눈이 멀지 않았는지 확인
```

2026-08-18 실측: 5개 항목 전부 GREEN(사진 45행 / 문서 556건 / doc_raw 556행 /
큐↔상태 일치 / 고아 파일 0).

**승인 필요**: 이 파일은 아직 **미추적**이다. `git add` 전까지는 회귀 스위트가 참조하지
못한다(추적 파일이 미추적 파일을 import하면 커밋 시 부팅이 깨진다 — BUGS #105).


---

### P1. 프런트 의존성 권고 7건 (2026-08-18 Sprint 207 실측)

이 문서는 그동안 **`next` 하나만** 다뤘다(SPRINT125). `npm audit` 을 실제로 돌려 보니
권고가 걸린 패키지는 **7개**이고 나머지 6개는 아무도 보고 있지 않았다.

```
moderate 1 / high 6 / 합계 7
```

| 패키지 | 설치본 | 등급 | 비고 |
|---|---|---|---|
| next | 16.2.9 | high | 권고 9건(미들웨어 우회, SSRF, 캐시 혼동, 이미지 최적화 DoS 등) |
| postcss | 8.5.15 | high | sourceMappingURL 경로 순회로 임의 `.map` 파일 노출(CVSS 7.5) |
| sharp | 0.34.5 | high | libvips 상속 취약점 4건 |
| nanoid | 3.3.15 | high | 비보안 생성기 무한 루프 2건 |
| js-yaml | 4.3.0 | high | `!!omap` 이차 CPU 소모(CVSS 7.5) |
| brace-expansion | 1.1.15 | high | 확장 폭주 OOM 3건(CVSS 7.5) |
| @tailwindcss/postcss | 4.3.1 | moderate | postcss 경유 |

**★ 낡은 안내를 정정한다.** 기존 가드와 문서는 "`next@16.2.11` 이상으로 올리면
해소된다"고 적고 있었다. 오늘 실측에서 취약 범위는 `9.3.4-canary.0 ~ 16.3.0-preview.10`
이고 npm 이 제시하는 수정본은 **`16.3.1`** 이다. 16.2.11 로 올리면 CVE-2026-64641
하나만 벗어나고 **나머지 8건은 그대로 남는다.**

**좋은 소식**: `next@16.3.1` 은 `isSemVerMajor: false` 이고, postcss/sharp 의
`fixAvailable` 도 같은 항목을 가리킨다. 즉 **메이저 업그레이드 없이 7건 중 3계열**이
한 번에 정리된다.

**조치는 승인 영역이다** — 의존성 올리기는 빌드/런타임 동작을 바꾼다.
승인 후 `npm install next@16.3.1` 그리고 `npm audit` 재실측 -> 남은 항목 재판정.

**지금 걸어 둔 것**: `test_schema_hygiene.py` 8-B 가 위 7개의 설치본이
**스냅샷보다 낮아지면 실패**한다(오프라인 판정). 새 CVE 는 오프라인으로 알 수 없으므로
`npm audit` 재실측은 여전히 사람이 주기적으로 해야 한다 - 이 표가 그 기준점이다.


---

## 접근성 (2026-08-19 Sprint 223 갱신)

승인 없이 가능한 **기술 항목은 전부 닫혔다.** 남은 것은 제품 결정과 사람 손이 필요한 것뿐이다.

```
[x] 폼 컨트롤 접근 가능한 이름        93/93            (Sprint 222)
[x] 모달 시맨틱(role/aria-modal/이름)  2/2              (Sprint 221)
[x] 모달 포커스 트랩 + 복귀            2/2              (Sprint 223, BUGS #151)
[x] 동적 상태 메시지 알림              13곳 + 검색 결과  (Sprint 223, BUGS #152)
[x] 오류 <-> 폼 컨트롤 연결            aria-describedby (Sprint 223)
[x] main 랜드마크                     화면 6/6         (Sprint 223, BUGS #153)
[x] 키보드 전체 흐름                   양수 tabindex 0 / 클릭 전용 div 0 / 이름 없는 요소 0
[x] Escape 탈출구                      모달 2/2
[x] heading 계층                       건너뜀 0
[x] disabled 표현                      네이티브 disabled (aria-disabled 단독 0)
[x] aria 상태값                        aria-expanded 실제 토글 확인 / aria-current / aria-pressed
[x] 확대 차단 없음                     user-scalable=no 0
[x] 큰글씨 기술 기반                   닿지 않는 글자 8곳 -> **0곳** (Sprint 223)

[ ] 대비 4.5:1 / 탭 타깃 44px         **제품 결정** — 미달 각각 81개 / 44개(실측 유지)
[ ] 큰글씨 토글 UI                     **제품 결정**
[ ] 모바일 실뷰포트 확인               **확인 불가** — 도구가 페이지 뷰포트를 못 바꾼다
                                       (Sprint 223에 resize_window 로 재확인: innerWidth 1920 그대로)
```

체크된 항목은 전부 회귀가 잠그고 있고, 변이로 검출을 확인했다.

---

## 2026-08-20 Sprint 236 재확인 (전부 이번 세션 실측)

### 출시를 막는 것 (승인 필요)

```
1. Scheduler 등록 **0개**       Get-ScheduledTask 로 확인. 이름에 auction/doc/dojoon 을
                                포함하는 작업이 하나도 없다.
                                -> 크롤이 안 돌고 -> 문서 워커도 안 돈다
2. 크롤 정지                    최근 crawl_date 2026-08-12 / 최대 auction_date 2026-08-19
                                **미래 기일 물건 0건** -> 기본 검색이 빈 화면
                                (test_pipeline_integrity.py 와 frontend-contract 가 이걸 운다)
3. Admin API 키 부재            13개 라우트가 500. 운영 Secret 생성은 승인 영역
```

### 처리 능력 (Sprint 236 에서 개선됨)

```
       이동/물건   물건당 시간   하루 처리   공급 중앙값 106   공급 최대 278
예전       4회       92.8초        78건        **못 따라감**       못 따라감
지금       1회       47.2초       153건          감당              못 따라감(부족 125)
```

★ 출시 전 알아야 할 사실: **예전 구조는 평상시 공급조차 따라가지 못했다.**
batching 으로 평상시는 해결됐지만 **최대 공급일은 아직 밀린다.**
실행 창을 02:00~**05:38**(3.6시간)로 늘리면 최대일도 덮고 06:00 크롤과 겹치지 않는다.
-> 창 변경은 승인 영역. 등록 시점에 함께 판단할 것.

### 지금 대기 중인 일감

```
document_queue 3,498행 / 대기 2,753행 / **대기 물건 944개**
-> 능력 153건/일 기준 소진에 약 **6.2일**
   (화면의 COLLECTING 5,069 은 이 밀린 큐가 보이는 것이다. 결함이 아니다)
```

### 이번 세션에 통과한 것

```
자산 체인   이미지 45/45 열림 / 문서 표본 80/80 200 / 썸네일 9/9 / 고아 0 / 큐-화면 갈라짐 0
UI 연결     동작 없는 button 0 / form 제출 경로 2/2
Cache       이미지·문서 304 동작(235KB / 395KB 절약). JSON 캐시 헤더는 없음(알려진 공백)
성능        검색 2.7ms / 상세 2.2ms / 깊은 페이지 4.2ms - 급격한 악화 없음
접근성      main 1 / h1 1 / 이름 없는 컨트롤 0 / alt 누락 0 (검색·상세·관심)
가로 넘침   428개 요소 검사 -> 실질 0건
테스트      python 44 PASS / 2 FAIL(위 blocker) , frontend 137 중 133 PASS / 1 FAIL(위 blocker)
```

### 아직 확인하지 못한 것 (정직하게)

```
모바일 실제 폭(320/360/390/430)   `resize_window` 가 이 환경에서 동작하지 않는다
                                  (성공을 보고하지만 뷰포트가 그대로, outerWidth=0).
                                  breakpoint 와 무관한 min-content 검사로 대체했다.
관심물건 카드 레이아웃              favorites 0건이라 **실행되지 않았다.**
                                  빈 데이터를 통과로 읽지 않는다.
```

---

## 2026-08-20 Sprint 237 추가 확인

### 실행 창 (변경하지 않음, 값만 증명)

```
지금        02:00~04:00   능력 153건/일
넓히면      02:00~05:38   능력 277건/일   <- 실제 가드 통과 확인
안전 상한   02:00~05:55   능력 299건/일   <- 06:00 크롤 앞 5분 여유
05:56 부터  **막힌다**    (마지막 행이 종료 시각을 넘겨 크롤과 겹칠 수 있다)
```

### MAX_ITEMS (변경하지 않음)

```
크롤 로그 1,698회 중 **12.1%가 상한에 걸린다** -> 공급이 실제로 잘리고 있다
올렸을 때의 공급은 **알 수 없다** (자료가 10에서 오른쪽 절단)
여유: 지금 창 1.44배 / 05:38 창 2.61배  -> **창 확대가 먼저**
```

### 이번에 추가된 방어

```
종료 시각과 크롤 시작 사이 **5분 여유** 요구      (전에는 같아도 통과했다)
창이 음수일 때 공허하던 실행시간 한계 검사 수리
사용자별 JSON 에 `Cache-Control: no-store`      (파일의 304 절약 630KB 는 보존)
MAX_ITEMS 의 두 가지 의미를 계약으로 고정
```

### 이번에 **확인하지 못한** 것 (정직하게)

```
실제 모바일 viewport      resize_window 무동작 + iframe 은 X-Frame-Options: DENY 로 차단.
                          보안 헤더를 낮추지 않았다. 대체 측정(클리핑 제외 + 실제 상자)으로
                          카드 31개 전부 넘침 0 확인.
관심물건 카드 레이아웃      favorites 0건. **최근본 실데이터**로 같은 컴포넌트를 태워 대체 검증.
batching 이후 실제 처리시간  크롤이 멈춰 있어 잴 수 없다. 지금 상수는 2026-08-02 이전 값이다.
```
