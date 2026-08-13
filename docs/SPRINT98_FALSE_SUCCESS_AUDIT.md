# Sprint 98 — false success 패턴 확장 감사

> **왜 별도 파일인가**: 이 감사를 수행하는 동안 `docs/BUGS.md`, `api/v1/admin.py`,
> `test_api_regression.py` 등이 **다른 세션에서 동시에 편집되고 있었다**(수정 시각으로 확인).
> 그쪽 작업을 덮어쓰지 않기 위해 충돌 없는 새 파일에 기록한다.
> 내용이 안정되면 `docs/BUGS.md`로 합치면 된다.

Sprint 95(등기부 admin이 `doc_url`의 **파일 존재를 확인하지 않아** "발급 완료인데 다운로드
404"를 만들 수 있던 결함)의 **패턴**을 다른 영역으로 확장 조사한 결과.

패턴 정의: **DB/API는 성공이라고 말하는데 사용자가 실제로는 그 결과를 쓸 수 없다.**

---

## #98-1 등기부 신청이 소유자 화면에서만 사라진다 (수정 완료)

**파일** `api/v1/registry.py` — `get_registry_requests()`, `get_registry_request()`
**심각도** 높음 (결제된 문서에 도달 불가)

### 증상

`auction_item` 행이 사라진 등기부 신청은 `INNER JOIN` 탓에 **사용자 목록에서 빠지고 상세는
404**가 된다. 그런데 그 신청은 **멀쩡히 쓸 수 있다** — 다운로드 경로(`download_registry()`)는
JOIN을 하지 않으므로 실제 파일만 있으면 **200으로 문서를 그대로 내려준다.**

관리자 목록은 Sprint 97에서 이미 `LEFT JOIN`으로 고쳐 보이는데, **정작 소유자에게만
안 보이는** 상태였다.

### 실측 (auction.db 임시 복사본, 물건 행 삭제 후)

| 경로 | 수정 전 | 수정 후 |
|---|---|---|
| `GET /registry-requests` (사용자 목록) | **0건 (사라짐)** | 1건 |
| `GET /registry-requests/{id}` (상세) | **404** | 200 (`case_no`는 null) |
| `GET /admin/registry-requests` | 1건 | 1건 |
| `GET /registry-requests/{id}/download` | **200 (파일 정상 전송)** | 200 |

### 원인

`registry.py`의 목록/상세가 `JOIN auction_item`(INNER)이었다. 페이로드의 주체는 **신청**인데
물건 행의 존재가 신청의 표시 여부를 결정하고 있었다.

### 수정

두 쿼리를 `LEFT JOIN`으로 바꿨다. `case_no`/`full_address`는 null로 내려가지만
**계약 변경이 아니다** — 프런트가 이미 `string | null`로 선언하고 `|| '-'`로 그린다
(`mypage/page.tsx`).

### 왜 지금 고칠 가치가 있나

프로덕션 코드에 `auction_item`을 지우는 경로는 없고 런타임 커넥션은 FK를 켠다.
다만 **011~013처럼 테이블을 재작성하는 마이그레이션은 FK를 끄고 돌며**, 그때 UNIQUE 정리로
빠지는 행이 생기면 이 상태가 만들어진다(Sprint 97이 관리자 쪽에 대해 이미 같은 판단을 내렸다).
대가는 JOIN 한 단어이고, 놓쳤을 때는 **결제된 문서의 영구 유실**이다.

### ★ 남은 갭 (승인 필요 — SKIP)

백엔드는 고쳤지만 **UI 경로는 아직 닫혀 있다.**

다운로드 버튼은 물건 상세 페이지에만 있다(`properties/[id]/page.tsx:979`). 그 페이지는
`GET /item/{id}`가 404면 `loadError`로 **510행에서 조기 반환**하므로 버튼까지 렌더되지 않는다.
`mypage`는 등기부 신청 목록을 보여주지만 **다운로드 버튼이 아예 없다**(검색 결과 0건).

따라서 물건 행이 사라진 신청은:

- 이제 **목록에 보인다** (이번 수정) ✔
- API로는 **받을 수 있다** (`/download` 200) ✔
- 그런데 **화면에는 누를 버튼이 없다** �’

`mypage`에 다운로드 버튼을 추가하는 것은 UX 변경이라 제품 승인이 필요하다 → **SKIP**.
권장안: `mypage`의 등기부 신청 카드에서 `status === 'COMPLETED'`일 때
`properties/[id]/page.tsx:405`의 `handleDownloadRegistry()`와 **동일한 처리**(Content-Type으로
파일 vs JSON 실패 구분)를 재사용하는 버튼을 추가.

---

## #98-2 0바이트 문서가 200으로 나간다 (수정 완료)

**파일** `api/v1/documents.py` — `get_document()`
**심각도** 중간 (설명 없는 빈 화면)

`os.path.exists()`만 확인해서 **0바이트 파일이 200으로 나갔다.** 프런트는 뷰어를 열기 전
HEAD로 존재만 확인하고(`properties/[id]/page.tsx:215` — `res.ok`만 본다) 200이면 iframe을
띄우므로, 사용자는 **아무 설명 없는 빈 화면**을 본다. "문서가 없다"는 안내조차 못 받는다.

쓰는 쪽은 이미 크기를 본다 — `crawler/doc_paths.doc_exists()`는 `exists() and getsize() > 0`
이라야 "수집됨"으로 친다. **크롤러는 "아직 없음"이라 재수집 대상으로 보는 파일을 API는
"있음"이라 답하는** 비대칭이었다. 두 정의를 하나로 맞췄다.

`test_document_status_sync.py`는 이미 이 상태를 "뷰어가 200을 주지만 사용자에게는 빈 문서"라고
적어 두고 **데이터에만** 그 조건을 강제하고 있었다(실 DB 현재 0건). 엔드포인트 자체에는
검사가 없었다.

---

## #98-3 `logs/` 없는 새 체크아웃에서 문서 수집이 import조차 안 된다 (수정 완료)

**파일** `collect_documents.py`, `crawler/court_crawler.py`
**심각도** 중간 (신규 배포 차단)

`logs/`는 `.gitignore` 대상이라 **새로 받은 저장소/새 배포에는 없다.**

- `collect_documents.py` — `logging.FileHandler("logs/doc_collect.log")`가 **import 시점에**
  파일을 열어, 디렉터리가 없으면 `FileNotFoundError`로 죽는다. 이 모듈을 import하는
  `test_collect_documents.py`, `test_doc_storage_atomicity.py`가 실제로 죽는 것을 실측했다.
- `crawler/court_crawler.py` — `log_error()`가 `logs/errors.jsonl`에 쓰는데 `except Exception:
  pass`로 감싸여 있다. 디렉터리가 없으면 **크롤 오류 기록이 통째로 조용히 사라진다** —
  정작 가장 필요한 순간에 남는 게 없다.

저장소의 다른 진입점은 이미 `os.makedirs("logs", exist_ok=True)`를 갖고 있다
(`doc_worker.py`, `mvp_scraper.py`, `refresh_priority.py`). 이 두 곳만 빠져 있었다.

---

## #98-4 통과할 수 없는 계약 테스트가 있었고, 그래서 실제 구멍이 안 보였다 (수정 완료)

**파일** `tests/frontend-contract.test.mjs`, `tests/source-contract.test.mjs`
**심각도** 중간 (검증 공백 — 제품은 정상)

### 어떻게 드러났나

`npm run test:frontend`는 Next + FastAPI가 **둘 다 떠 있어야** 돈다. 서버 없이 실행하면
`before()`가 실패해 **48개 검사가 통째로 취소**된다 — 이 상태가 "실패"가 아니라 "실행 안 됨"으로
보이기 때문에 아무도 이상하게 여기지 않았다.

두 서버를 직접 띄우고 돌려 보니 **106개 중 정확히 1개가 실패**했다.

    ✖ 로그인 화면이 redirect 값을 폼에 그대로 싣는다
      AssertionError: 로그인 폼에 redirect hidden input이 없습니다

### 원인 — 제품이 아니라 검사 방법

`/login`은 `'use client'` + `<Suspense fallback={null}>`이라 **서버가 내려주는 HTML은 빈
껍데기**다(빌드 출력에서도 `○ /login` = static). hidden input은 `useSearchParams()`가 도는
**하이드레이션 이후**에 생긴다. 그런데 그 검사는 `fetch`로 받은 HTML 문자열을 정규식으로
훑었다 — **원리상 볼 수 없는 값을 보려 한 것**이라 통과할 수가 없었다.

실제 브라우저에서 하이드레이션 이후를 확인한 결과 **제품은 정상이다**:

    input[name="redirect"]  존재함 / type=hidden / 값이 원래 URL과 정확히 일치

### 진짜 문제 — 생산자 쪽 커버리지 공백

`source-contract.test.mjs`는 **소비자**(`loginAction`이 `formData.get('redirect')`를 읽는다)만
고정하고 있었다. **생산자**(로그인 폼이 그 값을 싣는다)는 어디에서도 고정되지 않았다.

즉 `page.tsx`에서 hidden input 한 줄을 지우면:

- `formData.get('redirect')` → `null`
- `sanitizeRedirectPath(null)` → 기본값 `'/'`
- 사용자는 **오류 없이 첫 화면으로** 보내진다 (보던 물건으로 못 돌아온다)
- **어떤 테스트도 실패하지 않는다**

MASTER_SPEC §3.4가 막으려던 회귀가 정확히 그것인데, 그걸 잡는 검사가 없었다.

### 수정 — 약화가 아니라 이동 + 보강

1. `source-contract.test.mjs`에 **생산자 쪽 계약을 신설**했다(서버 불필요, 관측 가능):
   URL의 `redirect`를 읽는지 / `name="redirect"` hidden input으로 싣는지 /
   그 input이 **`<form>` 안에** 있는지(밖이면 제출되지 않는다).
2. `frontend-contract.test.mjs`의 검사는 **HTTP로 실제 확인 가능한 것**으로 바꿨다 —
   redirect를 달고도 200이고, 값을 유실하거나 외부로 튕기지 않는다.

**변이 검증**: `page.tsx`의 hidden input 줄을 지우면 새 검사가 실패(107→106 pass)하는 것을
확인하고 원복했다. 이전에는 이 변이를 **아무 검사도 잡지 못했다.**

---

## 실 DB 전수 측정 — 이 결함들이 **이미 발생해 있는가** (읽기 전용)

코드에서 막은 상태가 데이터에 이미 존재하는지 `auction.db`를 read-only로 열어 전수 확인했다.

| 검사 | 결과 |
|---|---|
| `registry_requests` 전체 | **0건** |
| COMPLETED + `doc_url` 없음 | 0건 |
| COMPLETED + 실제 파일 없음 (Sprint 95 대상) | 0건 |
| COMPLETED + 0바이트 파일 | 0건 |
| 고아 신청 (`auction_item` 없음, #98-1 대상) | 0건 |
| FAILED + 파일 존재 | 0건 |
| 고아 파일 (디스크에 있으나 DB 미참조) | 0건 |
| `document_status` READY | **556행** |
| READY인데 파일 없음 | 0건 |
| READY인데 0바이트 (#98-2 대상) | 0건 |
| READY가 아닌데 쓸 수 있는 파일 존재 (역방향) | 0건 (5,072행 검사) |

**결론: 이번 수정들은 이미 난 사고를 수습한 것이 아니라 전부 예방적이다.**

두 가지를 함께 봐야 한다:

- **문서 파이프라인은 실제 데이터(556 READY / 5,072행)로 검증된 상태다.** 양방향 불일치가
  모두 0이므로 크롤러↔DB↔파일 정합성은 현재 건강하다.
- **등기부는 아직 실 데이터가 한 건도 없다(0건).** 즉 #98-1이 고친 경로는 **아직 실제 트래픽을
  겪지 않았다.** 결함이 발견되지 않은 것이 아니라 **아직 발생할 기회가 없었다는 뜻**이다 —
  베타에서 첫 결제가 들어오는 순간부터 노출되는 경로이므로, 지금 막아 두는 편이 맞다.

---

## 확인했으나 결함이 **아닌** 것 (재조사 방지용 기록)

| 대상 | 판단 |
|---|---|
| `favorites.py` / `recent_items.py`의 INNER JOIN | **정상.** 이쪽은 `ai.*`가 페이로드 전체라 물건이 사라지면 보여줄 내용 자체가 없다. `LEFT JOIN`으로 바꾸면 `id`까지 null인 행이 나가 프런트가 깨진다. 등기부는 페이로드가 *신청*이라서 다르다. |
| 등기부 다운로드의 200 + JSON 실패 봉투 | **정상 처리됨.** 프런트가 `contentType.includes('application/json')`로 파일과 실패를 구분한다(`properties/[id]/page.tsx:415`). |
| `item.py`가 `document_status`를 그대로 노출 | **정상.** 프런트는 이걸로 버튼만 그리고, 실제 존재는 뷰어를 열 때 HEAD로 다시 확인한다(2단 구조). |
| `api/auth.py`의 JWT 검증 | **정상.** alg 화이트리스트 고정(`alg:none` 차단), JWKS 캐시/회전 대응, 실패를 `JWTError`로 정규화해 선택적 인증 라우트가 500이 되지 않게 한다. |
| document_status READY/0바이트 **데이터** 정합성 | `test_document_status_sync.py`가 실 DB를 전수 대조 중이며 현재 0건. |

---

## 문서화만 하고 손대지 않은 것 (판단 필요)

**`requirements.txt`의 `requests`가 추적 소스에서 미사용.**
`test_schema_hygiene.py`의 "목록에만 있고 소스에서 안 쓰는 항목 없음" 검사는 현재
`step8_verify.py`가 `requests`를 쓰기 때문에 통과한다. 그런데 **`step8_verify.py`는 git에
추적되지 않는 로컬 파일**이다 — 즉 **새로 clone하면 이 검사가 실패한다(CI 파손).**
고치는 길이 두 가지고(파일을 추적에 넣기 / 의존성을 빼기) 어느 쪽이 맞는지는 그 스크립트를
유지할 생각인지에 달려 있어 손대지 않았다.

---

## 검증

**신규 테스트** `test_false_success.py` (독립 파일 — `test_api_regression.py`가 동시 편집
중이라 그 파일을 건드리지 않았다)

- 실 DB를 건드리지 않는다: 등기부 검사는 `auction.db`의 **임시 복사본**에 대고 돈다.
- **모든 검사에 대조군을 둔다.** 대조군이 없으면 "고쳐서 404"인지 "원래 경로가 틀려서
  404"인지 구별할 수 없다.

**변이(mutation) 검증** — 두 수정을 되돌려 테스트가 잡는지 확인 후 원복:

| 되돌린 것 | 결과 |
|---|---|
| `LEFT JOIN` → `JOIN` | 4개 단언 실패. **대조군(다운로드 200 / 관리자 목록)은 계속 통과** — "받을 수는 있는데 안 보인다"는 모순이 출력에 그대로 드러난다. |
| 크기 검사 제거 | 2개 실패. **대조군(내용 있는 문서 200 / HEAD 200)은 통과.** |

**전체 회귀**

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **30개 파일 전부 통과** (`test_false_success.py` 포함) |
| 프런트 테스트 (`npm run test:frontend`, 서버 2개 기동) | **107/107 통과** (수정 전 106개 중 1개 실패) |
| TypeCheck (`npx tsc --noEmit`) | 통과 (exit 0) |
| Lint (`npm run lint`) | 통과 (exit 0) |
| Build (`npm run build`) | 통과 (exit 0, 9개 라우트 생성) |

> **프런트 테스트를 돌리려면 서버 두 개가 필요하다** — 이번에 그 사실이 실패 1건을 가리고
> 있었다. 앞으로는 반드시 아래 순서로 돌린다:
>
> ```
> python -m uvicorn api_server:app --host 127.0.0.1 --port 8000
> npm run build && npm run start
> npm run test:frontend
> ```
>
> 서버 없이 돌리면 48개가 **취소**되고 그 상태가 "실패"로 보이지 않는다.
> (서버가 필요 없는 소스 계약 검사는 `tests/source-contract.test.mjs`에 분리돼 있어
> 서버 없이도 정상 보고된다.)
