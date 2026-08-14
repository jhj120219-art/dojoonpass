# Sprint 105 — 남은 Backlog 10건 전수 처리 (2026-08-14)

> 앞 Sprint: `docs/SPRINT104_DOCUMENT_EXISTS_DEFINITION.md`
>
> **별도 파일 이유**: Sprint 100~104와 같다 — `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

Backlog 10건을 **하나도 건너뛰지 않고** 실측했다. 결과적으로 그중 **3건은 이전 보고가
과장되었거나 틀렸다**는 것이 드러났다. 그 정정이 이번 Sprint의 절반이다.

---

## #105-1 스케줄러 등록 전제조건 — 전부 충족 (등록은 SKIP)

등록은 사용자 환경 변경이라 하지 않았다. 대신 **"등록만 하면 된다"는 주장을 증명**했다.

| 검사 | 결과 |
|---|---|
| BAT 3종 존재 / `cd /d %~dp0` / logs 선행 생성 / errorlevel 검사 | 전부 OK |
| BAT이 부르는 스크립트 4종 실재 + 문법 통과 | 전부 OK |
| BAT이 고를 인터프리터 (Anaconda 없음 → PATH 폴백) | Python 3.12.10, **Store 스텁 아님** |
| 크롤 의존성 7종 import | 전부 OK |
| DB / 핵심 테이블 5종 / 마이그레이션 19/19 | 전부 OK |
| 배치가 읽는 환경변수 | `DOC_WORKER_TEST_MODE` 하나(선택) |
| Task Scheduler 등록 상태 | 전체 476개 중 **이 저장소 참조 0개** |

**결론: 고쳐야 할 코드가 없다. 등록만 남았다.**

### 새 가드 — BAT이 부르는 스크립트가 실재하는가

`test_crawl_exit_code.py` §8은 **알려진 후보 목록**의 존재를 본다. 그러나 **배치가 무엇을
부르는지**는 아무도 보지 않았다. 배치를 고쳐 없는 스크립트를 부르게 하면 Task Scheduler는
매일 조용히 실패한다(파일이 없어도 cmd는 계속 진행한다).

`test_bootstrap.py` §4에 추가했다. 변이 검증:

| | 변이 | 결과 |
|---|---|---|
| M42 | 배치가 없는 스크립트를 부르게 함 | **검출 O** |
| M43 | REM 주석 안의 예시만 `.py`로 바꿈 | **오탐 없음 O** |

### ★ 내가 만든 오탐 (기록)

처음 만든 감사 도구가 `run_daily.bat`을 NG로 판정했다. 원인은 배치가 아니라 **내 도구**였다 —
파일 전체를 훑느라 8행의 **REM 주석 안 예시**(`REM \`>> logs\daily_run.log\`는 실패하는데…`)를
"첫 리다이렉트"로 잡았다. 실제로는 mkdir(20행)이 첫 실행 리다이렉트(39행)보다 앞이다.

`test_bootstrap.py`는 이미 REM을 건너뛰고 있었고(`# 주석 안의 예시 문구에 걸리지 않게 한다`),
`test_crawl_exit_code.py`도 같다. **저장소는 일관됐고 내 도구만 틀렸다.**
이 함정은 이번 세션에서 **세 번째**다(§9 스캐너 / 문서 드리프트 가드 / 이번).

---

## #105-2 정규화 드리프트 — 전수 검색 완료, **닿지 못하는 3개** 발견

`backfill_region_normalize.py`는 이미 검증돼 있다(dry-run 422건 / 사본 적용 후 드리프트 0).
이번에는 **같은 드리프트가 다른 필드에도 있는지** `auction_item` 21개 컬럼을 전수 분류했다.

```
크롤 원본        12개   (id, case_no, full_address, status, ...)
재계산 가능        6개   sido / sigungu / dong / lot_number / bid_rate / fail_count
★ 재계산 불가     3개   validation_status / appraisal_price / minimum_bid_price
미분류            0개
```

**재계산 불가 3개의 공통 원인: 입력 원문이 저장되지 않는다.**

```
validation_status <- appraisal_summary   (크롤 중 메모리에만 존재, 버려짐)
appraisal_price   <- 크롤 원문 문자열      (INTEGER 로만 남아 복원 불가)
minimum_bid_price <- 크롤 원문 문자열
```

가격 원문으로 보이는 컬럼을 전 테이블에서 찾아봤지만 **0개**였다.

### 그래서 불변식으로 지킨다 (`test_pipeline_integrity.py` §12 확장)

재계산 대조가 불가능하므로 **어떤 경우에도 성립해야 하는 것**만 본다.

```
[PASS] 음수 가격인 행 없음
[PASS] 최저매각가격이 감정평가액을 넘는 행 없음(파싱 역전)
       가격이 0인 행: 감정가 0 / 최저가 0  ← 실패 조건 아님(참고용)
```

"역전"이 중요하다 — 파싱이 두 값을 뒤바꿔 넣으면 `bid_rate`(= 최저/감정)가 1을 넘어
화면에 "120%" 같은 값이 뜬다.

> "가격 0"은 **일부러 실패 조건으로 두지 않았다.** 크롤이 "미상"을 만나면 0이 될 수 있고
> (`upsert_batch`의 `int(... or 0)`), 그건 코드 결함이 아니라 데이터 사정이다.
> 그것으로 스위트를 빨갛게 만들면 곧 무시하게 된다.

### 그리고 두 표가 같은 값을 들고 있는가

`auction`(크롤 원본) ↔ `auction_item`(API가 읽는 표)을 **12필드 × 1,876행** 대조하는
가드를 추가했다. 어긋나면 "크롤은 됐는데 화면은 옛 값"이 된다.

```
[PASS] auction 에만 있고 auction_item 에 없는 행 없음(API가 못 보는 크롤 결과)
[PASS] 두 표의 값이 어긋난 필드 없음
       짝지은 행 1876개 x 12필드 대조
```

변이 검증 M44~M47 전부 검출. 특히 각 변이가 **여러 가드를 동시에** 울렸다
(음수 가격 → `bid_rate` 공식 + 음수 + 두 표 일치 3개가 함께 실패) — 계층 방어가 작동한다.

---

## #105-3 ★★ 다른 worktree 48파일 — **병합할 것이 없다** (이전 보고 정정)

Sprint 102에서 나는 이렇게 적었다.

> 미커밋 48개 파일 / 겹치는 5개는 손 병합 필요 /
> `storage/database.py`는 그쪽 기준 커밋이 2커밋 뒤라 **Sprint 100의 변경조차 들어 있지 않다**

**두 문장 다 틀렸다.** 해시로 대조했다.

```
48개 중 master(fc22381)와 바이트 동일   38개   ← 이미 반영됨
줄바꿈 차이뿐 (내용 동일)                 2개   collect_documents.py, docs/CLAUDE.md
실제 내용이 다른 파일                     8개
master 에만 있는 파일                     0개
```

`storage/database.py`는 **master와 바이트 동일**하다 — Sprint 100이 당연히 들어 있다.
내가 "겹친다"고 지목한 5개 중 4개(`storage/database.py`, `test_document_queue.py`,
`test_document_status_sync.py`, `test_pipeline_integrity.py`)는 **이미 동일**했다.

### 남은 8개도 대부분 master가 앞선다

| 파일 | 그쪽 고유 | master 고유 |
|---|---|---|
| `test_api_regression.py` | **+136** | -27 |
| `docs/CURRENT_STATE.md` | +18 | -229 |
| `api/v1/admin.py` | +11 | -4 |
| `tests/frontend-contract.test.mjs` | +8 | -35 |
| `test_schema_hygiene.py` | +3 | -206 |
| `.gitignore` / `api/v1/documents.py` | +1 / +1 | -9 / -1 |
| `docs/TEST_PLAN.md` | **+0** | -68 |

### 가장 큰 고유 덩어리(+136)도 이미 master에 있다 — 이전됐을 뿐

그 136줄의 정체는 `test_registry_orphan_item_visibility()` 와 0바이트 문서 검사다.
**둘 다 master에서는 `test_false_success.py`로 옮겨져 확장돼 있다** — 단언 문구까지 거의
그대로 남아 있고, 그 파일은 **worktree 에 아예 없다**(만들어지기 전 상태).

`api/v1/admin.py`의 고유 11줄도 **주석 정정뿐**이고, 내가 Sprint 104에서 고친
`_require_existing_registry_document()` 와 **다른 함수**다(그쪽엔 `getsize` 자체가 없다).

### 결론

**그 worktree 는 Sprint 98 이전의 낡은 스냅샷이고 고유 작업이 0이다.**
병합할 것이 없다. 1.36 GB는 회수 가능하지만 **다른 세션의 산출물 삭제는 파괴적 조치**라
하지 않았다(SKIP).

---

## #105-4 httpx / httpx2 — 필요함을 증명, 전환은 아직 (근거 확보)

| 질문 | 실측 |
|---|---|
| 소스가 `httpx`를 직접 import 하는가 | **0개 파일** |
| `TestClient` import 시 httpx가 적재되는가 | **True** |
| 운영 서버(`api_server`) import 시 적재되는가 | **False** |
| `TestClient` 를 쓰는 파일 | **12개** |
| `httpx2` 설치 여부 | **미설치** |
| starlette 요구 | `httpx2>=2.0.0` **와** `httpx<0.29.0,>=0.27.0` 둘 다 (extra `full`) |
| deprecation 경고 재현 | **1건** — `Using httpx with starlette.testclient is deprecated` |

**결론: 테스트 전용이지만 없어서는 안 되는 의존성.** 운영 경로는 필요 없다.
`httpx2`가 설치돼 있지 않으므로 지금 버전만 바꾸면 **검증되지 않은 변경**이 된다 → 전환은
starlette 업그레이드와 함께.

### 예외를 **강제되는 요구사항**으로 바꿨다

`test_schema_hygiene.py`는 `stale = listed - used_dists - {"httpx"}` 로 httpx를 **조용히
빼기만** 했다. 그러면 검사가 한 방향만 본다 — **누가 requirements 에서 지워도 통과한다.**
그리고 지우기 쉽다: 직접 import 가 0건이라 "안 쓰는 의존성"처럼 보인다.

이제 "반드시 있어야 한다"를 직접 단언하고, 그 근거(TestClient 사용 파일 12개)도 함께 센다.

```
[PASS] httpx 가 requirements 에 있다(TestClient 회귀의 전제)
[PASS] httpx 가 필요한 근거가 실재한다(TestClient 사용 파일 존재)
       TestClient 사용 파일 12개 -> httpx 필수
```

변이 M48(requirements 에서 httpx 삭제) → **검출 O** (이전에는 통과했다).

---

## #105-5 `appraisal_summary` — 전 계층 추적 완료

```
생성   crawler/court_crawler.py:75      (parse_gamjung 결과)
모델   models/auction_item.py:19        appraisal_summary: str = ""
사용   validator/validation_engine.py:74  extract_sido(item.appraisal_summary)
DB     쓰지 않음      (0건)
API    노출하지 않음  (0건)
프런트  모름          (0건)
```

**"계산만 하고 저장하지 않는 false-success"는 아니다** — 어디에서도 저장/노출을 약속하지
않으므로 거짓 약속이 없다. 다만 그 결과인 `validation_status`는 다르다.

### 그 결과는 사용자에게 보인다

```
validation_status -> api/v1/search.py:88, item.py:87 -> 상세 화면
   src/app/properties/[id]/page.tsx:642
   VALIDATION_STATUS_LABEL = { PASS:'검증완료', FAIL:'검증실패' }
```

즉 **재계산도 검증도 불가능한 판정이 "검증실패"라는 문구로 사용자에게 나간다.**
현재 FAIL 12건, 기본 검색 노출 0건(전부 만료), 종결포함 검색에서는 전부 노출 가능.
그중 **2건은 #103-3에서 증명된 오탐**(sido 버그가 원인)이다.

---

## #105-6 `total_failures` — 전수 추적, 이름과 의미가 다르다

```
정의   api/v1/doc_stats.py:51        COUNT(document_collect_failures)
쓰기   collect_documents.py:315      ← 유일한 writer
배치   run_*.bat 전수 검색            ← 이 스크립트를 부르는 배치 **없음**
테스트 test_api_regression.py:155,176 현재 계약을 고정 + 증가 추종까지 검증
문서   docs/TEST_PLAN.md:963,967,993  변이가 살아남아 강화한 이력까지 기록
프런트 0건
```

같은 응답의 나머지 6개 값은 `document_status`(살아있는 경로)에서 온다.
즉 **7개 중 1개만 죽은 테이블에서 온다.** 지금 우연히 둘 다 3이라 어긋남이 안 보인다.

정의(누적 사건 vs 현재 FAILED 개수)는 제품 결정이라 바꾸지 않았다.
대신 **엔드포인트가 출처를 말하지 않던 것**을 고쳤다 — `doc_stats.py`에 실측 근거와
함께 주석을 남겨, 다음 읽는 사람이 "6개 합계"로 오해하지 않게 했다.

---

## #105-7 ★ 현황조사서 버튼 id — 628건이 "수집중"으로 멈춰 있다 (내 판정 정정)

Frontend → API → Backend 전 흐름을 실측했다.

```
BACKEND  get_doc_button_id('status','1')  -> 버튼 id 있음
         get_doc_button_id('status','2')  -> None    ← 물건번호 2 이상은 수집 불가
DB       물건번호!=1 인 STATUS 행 629
API      GET /item/{id} -> documents[].status 를 그대로 전달
         GET .../documents/STATUS -> 404 (GET/HEAD 모두)
FRONT    DOC_STATUS_LABEL = { READY:'수집완료', COLLECTING:'수집중', FAILED:'수집실패' }
```

### 내가 방금 내린 판정이 틀렸다

처음에 "화면은 '수집실패'로 정직하게 말한다"고 적었다. **628/629 케이스에서 틀렸다.**

```
document_status = COLLECTING   628건  -> 화면 "수집중"
document_status = FAILED         1건  -> 화면 "수집실패"
```

**628건이 영원히 도착하지 않을 문서를 "수집중"이라고 말하고 있다.**
`docs/BUGS.md` #69와 같은 모양이되, 이쪽은 **기다림이 끝날 수 없다는 것이 코드로 이미
확정**돼 있다는 점이 다르다.

왜 FAILED가 아닌가: 그 행들은 doc_worker가 집지 않는다 — 대부분 기일이 지나
2차 방어선(`SKIPPED_EXPIRED`)에 먼저 걸린다. Sprint 101의 `mark_queue_unsupported()`는
**앞으로 집히는 행**에만 적용된다.

### 새 도구 — `repair_unsupported_status_docs.py` (dry-run 기본)

**새 정책이 아니다.** "이 경우 FAILED로 둔다"는 Sprint 75가 이미 정했고
(`test_document_queue.py` §14), Sprint 101이 구현했다. 이미 쌓인 행에 같은 규칙을 적용한다.

```
수집 버튼 id가 없는 document_status 행 : 629
  이미 FAILED (그대로 둠)             : 1
  READY (파일 있음 - 건드리지 않음)    : 0
  COLLECTING -> FAILED 대상           : 628
```

안전 설계:
- 대상 판정을 **코드에 물어본다**(`get_doc_button_id`) — 규칙을 복제하지 않는다.
  버튼 id가 확보되면 대상이 저절로 줄어든다.
- **`READY`는 절대 건드리지 않는다** — 파일이 있는 문서를 "수집실패"로 가리면
  사용자가 볼 수 있는 것을 못 보게 된다(정반대 방향의 결함).
- `document_status`만 바꾼다. 큐는 doc_worker의 몫이다.

실 DB **복사본** 검증 (인위로 READY 행을 하나 만들어 보호를 시험했다):

```
[PASS] DRY-RUN 이 아무것도 바꾸지 않았다
[PASS] COLLECTING 이 0이 됐다: {'FAILED': 628, 'READY': 1}
[PASS] READY 행은 보존됐다(파일 있는 문서를 가리지 않는다)
[PASS] 다른 doc_type 은 건드리지 않았다: 3356 -> 3356
[PASS] 행 수가 변하지 않았다: 629 -> 629
```

**적용하지 않았다** — 628행 변경은 운영 데이터 변경이고, 저장소 관례상 PM 승인 영역이다.

---

## #105-8 고아 데이터 — `cleanup_orphans_dryrun.py` (삭제 기능 자체를 넣지 않았다)

`--apply` 옵션을 **의도적으로 만들지 않았다.** 호출하면 거부하고 이유를 출력한다.

```
document_queue 고아      18행   (done 3 / pending 12 / SKIPPED_EXPIRED 3)
빈 고아 디렉터리           5개
★ 파일이 든 고아 디렉터리   1개   고양지원/2024타경2803/1 -> 4개 파일 12.4 MB
```

### 이 도구가 곧바로 값을 했다 — "진짜 고아인가" 절

**고아 큐 행 전부가 다른 법원에 같은 사건번호를 갖고 있다.**

```
고양지원 2024타경2803 물건1 -> 다른 법원에 같은 사건번호: [('춘천지방법원','1')]
부산동부지원 2023타경5187 물건1 -> [('서산지원','1'), ('서산지원','2'), ... 7건]
성남지원 2024타경4973 물건1 -> [('통영지원','1'), ('성남지원','2'), ... 9건]
```

법원마다 사건번호를 독립 채번하므로 이들은 **서로 다른 사건**이 맞다. 그러나
`case_no` 단독으로 조인하는 정리 스크립트를 짰다면 **고아가 아니라고 오판하거나
엉뚱한 쪽을 지웠을 것**이다. 그래서 이 도구는 (법원, 사건번호, 물건번호) **3자**로만 맞추고,
그 사실을 출력으로 보여 준다.

삭제 기준은 위험도 순으로 [A] 빈 디렉터리 → [B] 고아 큐 행 → [C] 파일이 든 디렉터리로
나눠 적었다. [C]는 **물건 행이 왜 사라졌는지가 먼저**다 — 유일한 사본일 수 있다.

---

## #105-9 커밋된 DB 백업 — **이득이 거의 없다** (이전 보고 정정)

이전 Backlog는 "36.9MB 인덱스에서 제거"라고 적었다. 실측하니 전제가 틀렸다.

```
추적 중 백업 9개, 작업본 기준 합계   36.9 MB
각 파일이 등장한 커밋 수             전부 1커밋 (한 번도 수정되지 않음)
.git 전체 크기                       15 MB      ← 백업 36.9MB 를 포함한 전체
.gitignore 는 이미 *.db.backup* 을 덮고 있다(64/73행)
```

즉 **git이 잘 압축했고, 히스토리 전체 비용이 15MB를 넘지 않는다.** 그리고:

- `git rm --cached` 는 **클론 크기를 줄이지 않는다**(blob은 히스토리에 남는다).
- 파일이 한 번도 바뀌지 않았으므로 **앞으로 커질 일도 없다.**
- 실제로 줄이려면 히스토리 재작성이 필요한데 그건 SKIP 대상이다.
- 게다가 `git rm --cached` 자체가 **커밋을 요구**한다(이 세션 금지).

**결론: 이득이 거의 없는 항목이다. 우선순위를 낮추는 것이 정직하다.**

---

## #105-10 환불 ↔ 구독 — 불일치 실측 확인 (정책은 정하지 않음)

실제로 결제하고 전액 환불해서 측정했다(테스트 사용자, 뒤에 전부 정리).

```
환불 전  payments: SUCCESS 12,900원   subscriptions: ACTIVE, expires 2026-09-13, payment_id=13813
환불 후  payments: REFUNDED           subscriptions: ACTIVE, expires 2026-09-13  ← 그대로
```

코드로도 확인:

```
refund_payment() 안에서 subscriptions 를 UPDATE 하는가      False
admin 환불 라우터가 subscriptions 를 건드리는가             False
subscriptions.payment_id                                  13813  ← 열쇠는 있다
```

**돈은 전액 돌려주고 서비스는 만료일까지 그대로 준다.** 사용자 화면은 "구독 중"이고,
`is_entitled()`가 ACTIVE + 미래 만료일을 보므로 **무료 등기부 한도 등 혜택도 유지**된다.

`docs/roadmap.md`의 "결정 대기" 항목과 일치한다. 새 불일치는 없고,
**정책 구현에 필요한 열쇠(`payment_id`)는 이미 있다**는 것을 재확인했다(Migration 019).
정책(즉시 해지 / 주기 만료 / 일할 / 표시만)은 제품 결정이라 정하지 않았다.

### ★ 여기서도 내 도구가 틀릴 뻔했다

처음에 ADMIN 키로 환불을 호출해 **403**을 받았는데(환불은 SUPER_ADMIN 전용),
그 상태로 "환불이 구독에 반영됐다 — 정책이 구현돼 있다"고 출력했다.
**실행되지 않은 것을 성공으로 읽은 것이다.** 도구에 "환불이 실행되지 않았으면 판정 무효"
분기를 넣고 다시 측정했다. 이 세션에서 반복해 확인한 교훈과 같다 —
**취소/거부를 성공으로 간주하지 않는다.**

---

---

# Backlog 이후 — 감사 순환 (같은 의미, 다른 기준)

Backlog 10건이 끝난 뒤 순환을 시작했다. 우선 패턴은 이번 세션이 반복해 잡은
**"같은 판정을 하는 코드가 여러 벌"** 이다.

## #105-11 `success` 판정 — 프런트 4곳이 봉투를 보지 않는다 (지금은 안전, 가드 신설)

이 API 에는 실패 응답이 **두 형태**로 있다(의도된 상태 — `test_schema_hygiene` §5).

```
error_response(code,msg)  -> HTTP 200 + {success:false, error:"CODE", ...}
raise HTTPException(...)  -> HTTP 4xx  + {"detail": "..."}
```

그런데 목록 화면 4곳은 봉투의 `success` 를 보지 않는다.

```
src/app/favorites/page.tsx:45          setItems(result.data ?? [])
src/app/properties/recent/page.tsx:45  setItems(result.data ?? [])
src/app/search/SearchPresets.tsx:56    setPresets(result.data ?? [])
src/app/mypage/page.tsx:130            set(result.data ?? [])
```

**지금은 안전하다.** 네 엔드포인트 모두 `error_response` 를 **한 번도 쓰지 않아**
HTTP 200 이면 반드시 성공이다(전수 확인). 즉 확인이 생략된 게 아니라 **생략해도 되는
상태**다. `download_registry`(유일하게 `error_response` 2회 사용)를 부르는 자리는
`!res.ok || content-type` 을 제대로 본다.

문제는 그 전제가 **깨지기 쉽다**는 것이다. 저 GET 중 하나에 `error_response` 를 하나만
추가하면 — 예컨대 "구독이 필요합니다" — 프런트는 그것을 **빈 목록**으로 그린다.
사용자는 오류 대신 "관심물건이 없습니다"를 본다. **실패가 정상 화면으로 둔갑한다.**

`test_schema_hygiene.py` §12 신설 — 그 네 GET 이 `error_response` 를 쓰지 않는다는
전제를 고정한다. 변이 M49(favorites GET 에 `error_response` 주입) → **검출 O**.

## #105-12 ★ 조회가 디스크를 만든다 — `doc_exists()` 의 부작용

중복 로직을 일반적으로 훑다가(같은 이름 함수가 여러 파일에 정의된 곳 11개) 발견했다.
`get_doc_dir()` 이 **3벌**인데(`api/v1/documents.py` / `crawler/doc_paths.py` /
`repair_document_status.py`), 경로 계산은 셋 다 같고 **한 곳만 다르게 행동했다.**

```python
# crawler/doc_paths.py
def get_doc_dir(...):
    path = os.path.join(DOCUMENT_ROOT, court_code, safe_case_no, safe_item_no)
    os.makedirs(path, exist_ok=True)      # <- 디렉터리를 만든다
    return path
```

그리고 **조회 함수가 그것을 부르고 있었다.**

```python
def doc_exists(...):
    path = os.path.join(get_doc_dir(...), key + "." + ext)   # <- 여기
    return os.path.exists(path) and os.path.getsize(path) > 0
```

### 재현 (임시 루트, 실 `documents/` 무변경)

```
시작 시 디렉터리 : (없음)
doc_exists("QA없는법원","2099타경9999","1","spec")  -> False
호출 후 디렉터리 : ['QA없는법원', 'QA없는법원/2099타경9999', 'QA없는법원/2099타경9999/1']
3번 더 물어본 뒤 : 12개 디렉터리
```

**"이 문서 있어요?" 라고 묻기만 해도 디스크에 3단계 디렉터리가 생기고, 물어볼 때마다 쌓인다.**

### 이것이 #105-8 의 고아 빈 디렉터리를 설명한다

`documents/` 아래 대응 물건이 없는 **빈 디렉터리 5개**를 앞에서 목록으로 만들었다.
그중 `A / B / 1` 은 테스트가 물어본 흔적이다 — `test_doc_storage_atomicity.py:296` 이
`canonical_doc_path("A","B","1","STATUS")` 를 부른다. **원인을 찾은 것이다.**

### 수정 — 경로 규칙은 한 곳, 부작용만 분리

```python
def _doc_dir_path(...):   # 경로만 계산. 디스크를 건드리지 않는다
def get_doc_dir(...):     # _doc_dir_path() + makedirs — 쓰기 직전용
def doc_exists(...):      # _doc_dir_path() 를 쓴다
```

규칙을 두 벌로 만들지 않았다 — 그랬으면 "쓰는 곳과 읽는 곳이 다른 경로를 보는"
이 저장소의 단골 결함이 된다. `canonical_doc_path()` 는 `collect_documents.py:248` 이
**쓰기 대상**으로 쓰므로 생성 동작을 그대로 뒀다.

### 변이 검증 — 양방향

| | 변이 | 결과 |
|---|---|---|
| M50 | `doc_exists` 가 다시 `get_doc_dir` 사용 | **검출 O** (`디렉터리를 만들지 않는다: 3 (expected 0)`) |
| M51 | `get_doc_dir` 에서 `makedirs` 제거 (쓰기 경로 파손) | **검출 O** (2개 검사가 함께) |

M51 이 중요하다 — 부작용을 없애다가 **쓰기 경로까지 망가뜨리는 것**을 막는다.

### 규모 실측 — 빈 디렉터리 1,676개

```
documents/ 아래 물건단위 디렉터리   1,882
  파일이 있는 것                      201
  ★ 비었고 물건은 있는 것           1,676
  비었고 물건도 없는 것(고아)            5
```

**물건 1,876개에 대해 사실상 1개씩 디렉터리가 만들어졌는데, 실제 파일이 있는 것은 201개뿐이다.**
나머지는 "있는지 물어본 흔적"이다. 이번 수정으로 **조회 쪽 발생원이 사라졌다**
(쓰기 직전 생성 후 다운로드가 실패해 남는 경우는 남아 있고, 그건 성질이 다르다).

### 테스트가 실 `documents/` 를 오염시키고 있었다

최상위에 법원이 아닌 **`A`** 디렉터리가 있었다. 출처를 찾았다 —
`test_doc_storage_atomicity.py` 가 경로 규칙만 확인하려고
`canonical_doc_path("A","B","1","STATUS")` 를 부르는데, 그 함수는 쓰기 대상 경로라
디렉터리를 만든다. **검사가 저장소에 쓰레기를 남기고 있었다.**

그 검사를 임시 루트에서 돌도록 고쳤고, 남아 있던 `documents/A`(파일 0개, 앞선 고아
목록에 이미 "빈 고아 디렉터리"로 올라 있던 것)를 지웠다. 재실행 후 다시 생기지 않는
것을 확인했다. 고아 빈 디렉터리는 **5 → 4** 로 줄었다.

> 지운 것이 무엇인지 분명히 적는다: **파일 0개의 테스트 산출물 디렉터리 하나**이고
> `documents/` 는 `.gitignore` 대상이다. 운영 데이터가 아니다.

## #105-13 같은 구독을 두 API 가 각자 직렬화한다 (약속은 있고 강제는 없었다)

중복 함수 목록에서 나온 또 하나. `row_to_subscription()` 이 **두 라이브 API 파일에**
각각 정의돼 있다.

```
api/v1/payments.py:row_to_subscription()       기본 9필드
api/v1/subscriptions.py:row_to_subscription()  같은 9필드 + 파생 3필드
                                               (effective_status / is_entitled / grace_period_end)
```

후자의 docstring 이 약속한다 — *"기존 payments.py 와 필드가 동일하고, 파생 필드만
추가한다(기존 필드는 하나도 바꾸지 않는다)"*. **그런데 강제하는 것이 없었다.**

한쪽에만 필드를 추가하면 같은 구독이 **어느 엔드포인트로 받았느냐에 따라 다르게 보인다.**
프런트는 두 응답을 같은 타입으로 다루므로 그 차이는 화면에서 `undefined` 로 나타난다.
Sprint 104 의 admin docstring 과 **정확히 같은 부류**다 — 약속은 검사로 고정해야 남는다.

`test_subscription_policy.py` 에 실행 시점 비교를 추가했다(같은 행을 두 함수에 태운다).

```
[PASS] subscriptions 는 payments 의 모든 필드를 포함한다: []
[PASS] 공통 필드의 값이 같다: []
       공통 9필드 / subscriptions 전용 파생 3필드
[PASS] payments 는 effective_status / is_entitled 를 내지 않는다(판정은 한 곳에서)
```

마지막 줄이 중요하다 — `payments` 가 상태 해석을 흉내내기 시작하면 만료 판정이 두 곳에서
갈린다. `resolve_expected_status()` 가 단일 기준이어야 한다.

### 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M52 | `payments` 에만 필드 추가 | **검출 O** |
| M53 | 공통 필드 값이 갈림 | **검출 O** |
| M54 | `payments` 가 `is_entitled` 를 흉내냄 | **검출 O** |

> M52/M54 는 처음에 "검출 X" 로 나왔는데, 확인해 보니 **내 변이가 엉뚱한 함수를
> 건드린 것**이었다(`payments.py` 안에 같은 모양으로 끝나는 직렬화 함수가 여럿이라
> `replace(...,1)` 이 첫 번째를 잡았다). 함수 구간을 정확히 겨냥해 다시 돌리자 셋 다
> 검출됐다. **변이가 안 잡혔다고 곧바로 "가드에 구멍"이라고 적지 않는다** —
> 변이가 의도한 곳에 적용됐는지부터 확인해야 한다.

## #105-14 감사 로그만 마스킹이 없었다 (같은 기록, 다른 기준)

중복 함수 목록의 마지막 실사용 항목. `_dump()` 가 **두 곳에** 있는데 하는 일이 달랐다.

```python
# api/v1/payment_logs.py
return json.dumps(mask_sensitive(payload), ensure_ascii=False)   # 마스킹 O

# api/v1/audit.py  (수정 전)
return json.dumps(value, ensure_ascii=False, default=str)        # 마스킹 X
```

`payment_logs` 와 `audit_logs` 는 **성질이 같은 기록**이다 — 둘 다 운영자가 폭넓게
열람한다. 그런데 마스킹 기준이 달랐다.

### 지금은 사고가 없다 (전수 확인)

`record_audit()` 호출부 **5곳을 전부** 읽었다. 모두 손으로 고른 스칼라 dict 를 넘긴다.

```
admin.py:370  {status, reason, doc_url}
admin.py:489  {user_id, reason_type, amount, adjustment}
admin.py:794  {webhook_processing_status, payment_status, webhook_id, result}
admin.py:859  {status, refunded_amount, total_refunded, reason}
admin.py:984  {status, expires_at, reason}
```

`card_no` / `cvc` / `access_token` 같은 키가 **하나도 없다.**

### 그런데 그건 관례일 뿐이다

`audit.py` 의 docstring 이 직접 경고한다 — *"전체 행을 통째로 넣으면 무엇이 바뀌었는지
오히려 안 보이고, **민감정보가 섞여 들어갈 여지도 커진다**"*. 그 경고를 강제하는 것이
없었다. 누가 `before=webhook_row` 처럼 행을 통째로 넘기면 그대로 저장된다.

### 수정 — 세 번째 복사본을 만들지 않았다

`payment_logs.mask_sensitive` 를 **재사용**한다(순환 import 없음 — payment_logs 는
audit 를 import 하지 않는다). 같은 판정을 또 한 벌 두면 이번 세션이 반복해서 잡은
바로 그 문제가 된다.

`default=str` 은 유지했다 — datetime 이 섞여도 직렬화가 죽으면 **감사 기록 자체를 잃는다.**

### 검증 — 현재 payload 에는 무영향(no-op)

```
[PASS] 감사 로그도 card_no / 중첩 access_token 을 마스킹한다
[PASS] 비민감 값과 일반 필드는 보존
[PASS] 현재 감사 payload 2종은 **그대로** 직렬화된다 (no-op)
[PASS] datetime 이 섞여도 직렬화가 죽지 않는다
```

변이 M55(마스킹 제거) / M56(`default=str` 제거) **둘 다 검출**.

## #105-15 발급 실패가 사용자의 값을 가져간다 (보고 장치 신설, 정책은 미결정)

STATE MACHINE 감사에서 나왔다. 등기부 신청 전이는 이렇게 정의돼 있다.

```python
ALLOWED_TRANSITIONS = {"PENDING": {"PROCESSING","FAILED"},
                       "PROCESSING": {"COMPLETED","FAILED"}}
```

`PAYMENT_REQUIRED` 가 표에 없는 것은 **의도된 것**이다 — 결제 성공이 그것을 옮긴다
(`payments.py:364,427`, 주석에도 적혀 있다). 여기까지는 정상.

문제는 `FAILED` 다. 등기부 신청은 **값을 소비한다**(무료 1회 또는 초과 요금).
그런데 `FAILED` 전이는 그 값을 되돌리지 않는다.

```sql
UPDATE registry_requests SET status='FAILED', reason=? WHERE id=? AND status=?
-- 크레딧/결제를 건드리는 코드가 없다
```

그리고 무료 횟수 계산은 최종 상태를 보지 않는다.

```python
get_free_count() = COUNT(registry_usage WHERE is_free=1 AND used_at >= 이번달)
```

즉 **시스템이 문서를 못 줬는데도 그 달의 무료 1회는 쓴 것으로 남는다.**

### 보상 어휘는 있는데 아무도 부르지 않는다

`RegistryCreditReason.REFUND`("환불로 인한 복구")가 **이미 정의돼 있다.**
그러나 그것을 자동으로 만드는 코드는 없다 — 운영자가
`POST /admin/registry-credits` (SUPER_ADMIN)로 수동 지급해야 한다.

자동 복구가 옳은지(재시도 여지가 있는 실패도 있다) 수동이 옳은지는 **제품 판단**이라
정하지 않았다. 대신 **아무도 그것을 볼 방법이 없다**는 문제만 없앴다.

`test_pipeline_integrity.py` §13 — **실패시키지 않고 보고만 한다.**

```
등기부 신청 총 N건 / 그중 FAILED M건
FAILED 인데 무료 1회를 쓴 건 : ...
FAILED 인데 결제가 연결된 건  : ...
REFUND 보상이 기록된 사용자   : ...
!! 값이 소비됐는데 복구 기록이 없는 신청 N건  (있을 때만)
```

### ★ 그 보고 장치에 내가 버그를 넣었고, 사본 검증이 잡았다

현재 `registry_requests` 가 0건이라 이 검사는 **공허하게 통과**한다. 그래서 사본에
`FAILED + 무료 소진` 을 심어 **탐지가 실제로 되는지** 확인했는데, 거기서 내 버그가 나왔다.

```
registry_credit_logs 에는 비슷한 이름이 둘 있다
    reason_type   GRANT/DEDUCT/USAGE/REFUND/...   <- enum (이것이 맞다)
    reason        "등기부 신청 (item_id=123)"       <- 사람이 읽는 자유 텍스트
```

처음에 `l.reason = 'REFUND'` 로 썼다. 자유 텍스트에 'REFUND' 가 들어갈 일이 없으니
**보상이 실제로 있어도 영원히 0으로 세는** 검사가 될 뻔했다.
`reason_type` 으로 고친 뒤 두 경우가 모두 맞게 동작했다.

```
[PASS] 복구 없으면 경고
[PASS] 복구 있으면 조용
```

**공허하게 통과하는 검사를 그대로 두지 않은 덕에 잡혔다.** 그리고 이것 자체가
이번 세션의 주제("같은 의미, 다른 기준")의 또 다른 사례다 — 한 테이블에 뜻이 비슷한
컬럼이 둘 있으면 반드시 한쪽을 잘못 고른다.

> 콘솔 인코딩 가드도 다시 나를 잡았다(§13 출력의 em dash U+2014). 세션에서 두 번째다.

## #105-16 "뜻이 비슷한 컬럼" 을 전 테이블로 일반화 — 운영 코드는 깨끗했다

#105-15 에서 내가 밟은 함정(`reason` vs `reason_type`)을 **전 테이블로 확장**해 훑었다.
한 테이블 안에 이름이 겹치는 컬럼 쌍 **42개**를 뽑았고, 대부분은 `id` 대 `*_id` 노이즈였다.
실제 위험은 둘이었다.

```
registry_credits / registry_credit_logs :  reason_type(enum)  vs  reason(자유 텍스트)
auction / auction_item                  :  status("유찰 2회")  vs  validation_status("PASS"/"FAIL")
```

전수 검색 결과 **운영 코드는 둘 다 올바른 쪽을 쓴다**(오용 0건).
`reason_type` 만 enum 비교에 쓰이고, `PASS`/`FAIL` 은 `validation_status` 로만 비교된다.

**즉 이 저장소는 규율을 지키고 있었고, 어긴 것은 내가 새로 쓴 검사였다.**

### 가드 (`test_schema_hygiene.py` §13)

재발을 막되, **오탐을 남기지 않도록 범위를 좁혔다.** 처음에는 `status = "PASS"` 를 전부
잡았는데 테스트들이 **출력 라벨용 지역 변수**로 그 이름을 쓴다
(`status = "PASS" if ok else "FAIL"`). 그런 오탐이 남으면 검사는 곧 무시당한다.

두 형태만 본다 — SQL 문자열 안의 컬럼 비교, 그리고 행에서 꺼낸 값의 비교.

| | 변이 | 기대 | 결과 |
|---|---|---|---|
| M57 | SQL 에서 `reason='REFUND'` | 검출 | **O** |
| M58 | `row["reason"] == "REFUND"` | 검출 | **O** |
| M59 | SQL 에서 `status='PASS'` | 검출 | **O** |
| M60 | 출력용 지역변수 `status = "PASS" if ...` | **검출 안 함** | **O** |

M60 이 이 가드의 값을 지킨다 — 잡아야 할 것만 잡는다.

---

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **31/31 파일 통과** |
| `python -m compileall` | **exit 0** |
| 프런트 테스트 | **107/107** (fail 0 / cancelled 0 / skipped 0) |
| TypeCheck / Lint / Build | **전부 exit 0** |
| BOM / 콘솔 인코딩 가드 | 통과 |
| 실 DB | **무변경** (읽기 전용 + 복사본 + 테스트 사용자 행 정리) |
| 변이 검증 | **M42~M48 전부 검출** (M43은 오탐 없음을 확인) |

## 수정 파일

```
crawler/doc_paths.py                 ★ 조회(doc_exists)의 디렉터리 생성 부작용 제거
api/v1/audit.py                      ★ 감사 로그도 민감정보 마스킹 (기존 payload엔 무영향)
test_subscription_policy.py          두 row_to_subscription 의 필드/값 일치 가드
test_api_regression.py               감사 로그 마스킹 회귀 + 등기부 크레딧 롤백(§41)
api/v1/doc_stats.py                  total_failures 출처를 주석으로 명시 (동작 무변경)
test_bootstrap.py                    BAT -> 스크립트 실재 검사 추가
test_pipeline_integrity.py           가격 불변식 + auction↔auction_item 12필드 일치 가드
test_schema_hygiene.py               httpx 강제 요구사항화 + §12 목록 GET 봉투 가드
test_doc_storage_atomicity.py        조회 무부작용 회귀 (+ 쓰기 경로는 유지되는지 대조군)
repair_unsupported_status_docs.py    신규 (dry-run 기본)
cleanup_orphans_dryrun.py            신규 (--apply 자체를 만들지 않음)
```

제품 동작이 실제로 바뀐 것은 **두 곳**이고 둘 다 계산 결과를 바꾸지 않는다 —
`crawler/doc_paths.py` 는 **부작용을 없앴고**, `api/v1/audit.py` 는 현재 payload 기준
**no-op**(민감 키가 없으므로)이며 앞으로의 사고만 막는다.

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| Task Scheduler 등록 | 사용자 환경 변경. **전제조건은 전부 검증 완료** |
| `backfill_region_normalize.py --apply` | 실 데이터 422행 — 저장소 관례상 PM 승인 |
| `repair_unsupported_status_docs.py --apply` | 실 데이터 628행 — 같은 이유 |
| 고아 데이터 삭제 | 파괴적. 기준·근거만 만들어 둠 |
| worktree 삭제(1.36GB) | 다른 세션 산출물 |
| DB 백업 index 제거 | 커밋 필요 + **이득 거의 없음**(#105-9) |
| `total_failures` 정의 | 제품 결정 |
| 환불 시 구독 처리 | 제품 결정 (열쇠는 준비됨) |
| httpx → httpx2 | starlette 업그레이드와 함께 |
| 현황조사서 버튼 id 확보 | 실제 courtauction.go.kr DOM 분석 필요 |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** (2026-08-20에 검색 0건 — #102-6)
- 위 SKIP 표의 승인 대기 항목들
- `appraisal_summary` 저장 여부 — 저장하면 `validation_status`가 감사 가능해진다 (#103-5)
