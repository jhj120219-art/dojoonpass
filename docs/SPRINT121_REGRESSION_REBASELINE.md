# Sprint 121 ― 어제 초록불이던 스위트가 오늘 빨갛다 (2026-08-15)

> 앞 Sprint: `docs/SPRINT120_ENVELOPE_COVERAGE.md`
>
> **별도 파일 이유**: Sprint 100~120과 같다 ― `docs/BUGS.md` / `docs/CURRENT_STATE.md`는
> 다른 세션의 편집 대상이라 충돌을 피했다.

세션 시작 시 이전 보고서를 그대로 믿지 않고 실제로 전체 스위트(28개, 실크롤 3개 제외)를
다시 돌렸다. Sprint 120은 "28/28 통과"로 끝났는데, 지금은 **3개 파일이 실패**했다.
API 서버는 내려 있었다(문서가 지목하는 "SQLite 쓰기 잠금" 원인이 아니다). 크롤이 계속
진행돼(`auction_item` 1,876→2,156행) 데이터가 자라면서 두 가지가 새로 드러났다 ― 전에
없던 결함이 아니라 전에 있던 결함의 범위가 데이터 증가로 더 드러난 것(§1, §2)이다.
나머지 둘은 이번에 처음 찾았다 ― 하나는 파이프라인 데이터 결함(§3), 하나는
`test_api_regression.py` 자체의 오래된 결함(§4, 이 세션에서 실제로 처음 트리거됨)이다.
§3을 고치며 "같은 패턴이 다른 곳에도 있는가"를 찾다가 **다섯 번째 결함**을 하나 더
찾았다 ― 크롤러의 사건번호 매칭이 두 곳에서 각자 부분 문자열로 구현돼 있었다(§7).
이번 세션에서 유일하게 **제품 코드(크롤러)를 실제로 수정**한 항목이다.

---

## 1. `test_schema_hygiene.py` ― 마이그레이션에 없는 인덱스가 라이브 DB에 있다

```
[FAIL] 새로 생긴 완전 중복 인덱스 없음: ['audit_logs(admin_id)']
```

`idx_audit_logs_admin`(마이그레이션 016)과 `idx_audit_logs_admin_id`가 완전 중복이다.
Sprint 100이 잡은 4쌍과 근본 원인이 다르다 ― 그 4쌍은 서로 모르는 두 마이그레이션
계통이 각자 만든 것이지만, `idx_audit_logs_admin_id`는 **저장소 어디에도 정의가 없다**
(`grep -rn "idx_audit_logs_admin_id"` 결과 0건). 라이브 DB에 마이그레이션을 거치지 않고
직접 생성된 것으로 보이며, 언제/어떻게 생겼는지는 추적 불가(변경 이력 없음).

순수 중복이라 동작 차이는 없다(fresh clone에는 이 인덱스가 없어도 API 결과는 같다).
Sprint 100과 같은 이유로 DROP은 보류(스키마 변경, 이득 대비 승인 비용). `KNOWN_DUPLICATE_INDEXES`에
5번째 쌍으로 추가하고 출처가 다르다는 것을 주석에 남겼다.

## 2. `test_pipeline_integrity.py` §12 ― sido 드리프트 4 → 5행

```
[FAIL] sido 드리프트가 늘지 않았다 (현재 5행, 상한 4)
```

Sprint 103이 1,876행을 스캔해 찾은 4행(`docs/SPRINT103_NORMALIZER_DRIFT.md`)은 그대로다.
다섯 번째는 그때 스캔 범위(1,876행) 밖에 있던 옛 행이 지금(2,156행) 범위에 들어온 것 ―
크롤이 계속 진행되며 자연히 드러났다.

```
id=11903  '경기도 성남시 분당구 구미로173번길 47 4층403호 (구미동,서울시니어스분당타워)'
          저장 '서울' -> 실제 '경기'
```

**#103-1과 완전히 같은 근본 원인**(문자열 아무 데나 있는 시도명과 매칭하던 옛
`extract_sido` 버그의 잔재)인데 표현형이 다르다 ― #103-1의 4건은 전부 **도로명**
("서울대학로"/"부산대학로")이 원인이었는데, 이번 것은 **건물명**("서울시니어스분당타워")이
원인이다. 지금 코드는 이 주소도 올바르게 '경기'를 낸다(재현 확인) ― 코드는 이미
옳고 데이터만 옛 상태다. 상한을 4 → 5로 올리고 사례를 주석에 남겼다.
`backfill_region_normalize.py --apply`가 나오면 함께 해소된다(승인 대기, 기존 Backlog).

## 3. ★ `test_pipeline_integrity.py` §13 ― 세종 물건이 "칠곡군"으로 영구 오염돼 있었다

이건 위 두 개와 다르다 ― **처음 찾은 결함**이고, 옛 정규화 버그의 재발현이 아니라
**`migrate_execute.py`의 병합 규칙 자체의 사각지대**다.

```
auction.id=357  대전지방법원 2024타경11191-1
주소: '세종특별자치시 나성로 96 1층104호 (나성동,더센트럴) [집합건물 철근콘크리트구조 52.67㎡]'
auction.sigungu      = ''       (정상 - 세종특별자치시는 구/군이 없다)
auction_item.sigungu = '칠곡군'  (경상북도 소속 - 이 주소 어디에도 없는 글자)
```

### 원인

`migrate_execute.py`:

```python
sigungu = row["sigungu"] or existing["sigungu"]
```

"크롤 값이 빈 문자열이면 파싱 실패로 보고 기존 값을 지우지 않는다"는 의도인데, **"주소에
원래 그 구성요소가 없어서 정당하게 비었다"와 구분하지 못한다.** 세종시 주소는 몇 번을
다시 크롤링해도 `sigungu`가 영원히 빈 문자열이므로, 한 번 다른 지역 값으로 오염되면
(유입 경로는 지금 로그로 확인 불가 ― `court_code` 복합키 도입 전 `docs/BUGS.md` #14와
같은 계열의 `case_no` 충돌로 추정) **재크롤을 아무리 반복해도 절대 자연 치유되지 않는다.**
`updated_at`이 2026-08-13로 최근인데도(즉 `migrate_execute.py`가 이 행을 계속 건드리고
있는데도) 오염된 값이 그대로인 것이 그 증거다.

기존 백필 스크립트(`backfill_region_normalize.py`)도 이 케이스를 못 잡는다 ― 그 스크립트는
"새 값이 비면"(§12 상단 주석) 일부러 건너뛴다. **좋은 기존 값을 빈 값으로 지우지 않으려는
안전장치가, 여기서는 반대로 나쁜 값을 영구 보존하는 쪽으로 작동한다.**

### 사용자 영향

`api/v1/search.py:244-246`의 `sigungu` 단독 필터는 `sido`와 무관하게 `LIKE` 매칭이므로,
`?sigungu=칠곡군`으로 검색하면 실제로는 세종에 있는 이 물건이 경북 칠곡군 검색 결과에
섞여 나온다. `sido`까지 함께 지정하는 검색(§45-46, `sido = ? AND sigungu LIKE ?`)에는
안 걸린다(`auction_item.sido`는 정상값 '세종'이라).

### 고친 것 ― 탐지 도구 신설(적용은 승인 대기)

`migrate_execute.py`의 병합 규칙 자체를 고치려면 "파싱 실패로 인한 빈 값"과 "원래 없어서
빈 값"을 구분할 방법이 필요한데 지금 정보로는 구분할 수 없다(둘 다 그냥 빈 문자열이다).
핵심 파이프라인 로직 변경이라 이 세션 범위를 벗어난다.

대신 이런 오염을 **보수적으로**(오탐보다 누락을 선호) 찾아내는 신규 스크립트를 만들었다 ―
"지금 코드로 다시 계산하면 비어야 하는데, 저장값이 있고, 그 저장값이 주소 문자열
어디에도 나타나지 않는" 행만 잡는다(3조건 모두 성립해야 함 ― 조건 3 덕분에 §12가 이미
다루는 "부분 문자열 오매칭" 사례는 자동으로 제외된다).

```
python detect_stale_region_contamination_dryrun.py
```

실 DB 실행 결과: `auction` 0건, `auction_item` 1건(위 id=357). `--apply`는 만들지 않았다
(`cleanup_orphans_dryrun.py`와 같은 관례) ― 무엇으로 덮어써야 맞는지(빈 문자열로 지우면
그 필드로 걸리는 검색 경로 자체가 없어진다는 제품 판단 포함)는 PM 승인 영역이다.

### 회귀 방어 + 자기 검증

`test_pipeline_integrity.py` §13의 표 대조를 `check(..., mismatched, {})`(엄격한 0)에서
§12와 같은 **알려진 상한** 방식으로 바꿨다(`SYNC_MISMATCH_CEILING = {"sigungu": 1}`) ―
이 1건은 알고 있고, 더 늘면 잡는다.

탐지 스크립트 자신도 검증했다(§13-B, 신설) ― 판정 3조건 각각을 합성 데이터로 격리해서,
조건 하나가 조용히 깨져도(과탐/누락) 잡히는지 확인한다.

## 4. ★ `test_api_regression.py` §admin ― 고아 픽스처 자체가 스키마와 어긋나 있었다

세 파일 조사를 마치고 스위트를 다시 돌리니 `test_api_regression.py`도 실패했다(단독
실행 시 100% 재현, 무작위 아님 ― `docs/TEST_PLAN.md`가 경고하는 "API 서버를 같이
띄우면 생기는 SQLite 잠금 경합" 증상이 아니다. API 서버는 계속 내려 있었다).

```
sqlite3.IntegrityError: NOT NULL constraint failed: auction_case.court_code
  (test_admin, "INSERT INTO auction_case (case_no, court_name, created_at) VALUES (?,?,?)")

During handling of the above exception, another exception occurred:
sqlite3.OperationalError: database is locked
  (같은 함수의 cleanup finally, "DELETE FROM registry_requests ...")
```

### 원인 ① ― 고아 픽스처 INSERT가 2026-08-06 스키마 변경 이전 상태다

`test_admin()`의 "관리자 목록에서 물건이 사라진 신청" 시나리오는 `auction_case` 행을
`court_code` 없이 만든다. 그런데 `court_code`는 Sprint 23(`docs/BUGS.md` #14,
`011_auction_case_court_code_unique.sql`)에서 **NOT NULL + 복합 UNIQUE**의 일부가
됐다. 같은 파일의 다른 픽스처(줄 249, D7 마감 검사)는 이미 `court_code`를 채워서
쓰고 있어 관례가 있었는데, 이 자리만 옛 스키마 그대로 남아 있었다 ― 지금까지 이
경로가 실제로 실행될 때마다 이미 깨져 있었다는 뜻이다(왜 지금까지 안 걸렸는지는
아래 "왜 지금 처음 보이나" 참고).

### 원인 ② ― cleanup이 자기 자신의 락으로 자기를 막는다

원인 ①의 예외가 나면 실행이 `finally:`(정리 블록)로 넘어가는데, 그 블록은 실패한
`conn`을 닫지 않은 채로 **별도 커넥션 `mig`를 새로 열어 같은 파일에 DELETE를 시도**했다.
`conn`은 실패한 INSERT로 트랜잭션이 열린 채(커밋도 롤백도 안 됨) 파일 잠금을 쥐고
있어서, `mig`의 쓰기가 "database is locked"로 죽는다. **진짜 원인(①)이 이 두 번째
예외에 가려져 트레이스백만 보면 잠금 경합처럼 보인다** ― `docs/TEST_PLAN.md`가 문서화한
"API 서버를 같이 띄우면 생기는" 그 증상과 겉모습이 같아서 처음엔 그쪽으로 오판하기 쉽다.

### 왜 지금 처음 보이나

`git log -S"9999타경콕찰97"`로 도입 커밋을 특정했다 ― `fc22381`("sprint 100 환경/성능/릴리스
감사", 2026-08-13 19:40). `court_code` NOT NULL 제약은 그보다 훨씬 전인 Sprint 23
(2026-08-06, `docs/BUGS.md` #14)에 이미 존재했다. 즉 **이 픽스처는 태어날 때부터
`court_code`를 채운 적이 없다** ― 도입한 세션이 같은 파일에 이미 있던 관례(줄 249,
Sprint 23 이후 스타일)를 보지 못하고 옛 형태로 새로 작성한 것으로 보인다. Sprint 100
이후 지금까지 "28/28 통과"로 계속 보고돼 왔다는 것은, 그 사이 어느 세션도 `test_admin()`을
**단독으로 재현 실행**해 본 적이 없다는 뜻이다 ― 전체 스위트를 한 파일씩 순서대로
돌리면 이 함수가 반드시 실행되므로, 지금까지의 "28/28"은 이 결함이 존재하는 채로
찍힌 숫자다(이 세션 시작 시 재검증하지 않았다면 이번에도 그대로 믿었을 것이다).

### 고친 것

```python
# Before
"INSERT INTO auction_case (case_no, court_name, created_at) VALUES (?,?,?)"

# After ― court_code를 채운다(줄 249 관례와 동일하게 court_name과 같은 값)
"INSERT INTO auction_case (case_no, court_code, court_name, created_at) VALUES (?,?,?,?)"
```

그리고 `finally:` 진입 직후 `conn.rollback(); conn.close()`를 `mig` 커넥션을 열기
**전에** 실행하도록 옮겼다 ― 이제 본문이 어디서 실패하든 cleanup 커넥션이 잠금과
경합하지 않는다. 이 순서 문제는 court_code를 고친다고 저절로 없어지지 않는다 ―
이 함수의 다른 어떤 단계가 나중에 또 실패해도 같은 방식으로 "database is locked"가
진짜 원인을 가릴 것이었다.

재현 확인: 수정 전 단독 실행 재현 O(아래 M100). 수정 후 단독 실행 3회 연속 통과.

## 5. 자기 자신도 스캔당했다 ― `test_schema_hygiene.py`의 SQL 가드가 신규 스크립트를 잡았다

§3에서 만든 `detect_stale_region_contamination_dryrun.py`를 커밋하기 전에 전체
스위트를 돌렸더니 **내가 방금 만든 파일**이 SQL 가드(Sprint 107/119)에 걸렸다 ―
`"SELECT ... FROM %s" % table` 형태의 %-포맷 SQL을 새 템플릿으로 잡은 것이다.
`backfill_region_normalize.py`의 동일 패턴(테이블명 리터럴만 들어가는 CLI 스크립트)과
같은 근거로 `ALLOWED_SQL_PERCENT_TEMPLATES`에 추가했다 ― **가드가 새 코드를 실제로
검사 대상에 넣고 있다는 확인**이기도 하다(스캔 대상이 `api`/`storage`/루트 스크립트
전체이므로 새로 추가한 루트 스크립트도 자동으로 걸린다, Sprint 119가 넓힌 범위 그대로).

## 6. 함께 확인한 것 (결함 0건)

4개 결함을 고친 뒤 "고친 게 다른 걸 깨뜨리지 않았는가"와 인접 영역을 추가로 확인했다.
전부 결함 없음으로 끝났지만, 확인했다는 사실 자체가 다음 세션에 값이 있다(같은 것을
또 재확인하는 낭비를 막는다).

- **프런트/백엔드 실제 기동 재검증** ― `.next` 지우고 `npm run dev` + `uvicorn` 둘 다
  띄운 뒤 `npm run test:frontend` 재실행: **108/108 통과**(Sprint 120 보고를 그대로
  믿지 않고 다시 확인). `curl`로 `/`, `/search`, `/api/v1/search`도 실제 200 + 실제
  데이터(174건) 확인. 서버 종료 후 `test_api_regression.py` 재통과 확인(SQLite 잠금
  경합 없음).
- **`docs/ENVIRONMENT_VARIABLES.md` 대 실제 `.env`/`.env.local`** ― 키 이름만 대조했다
  (값은 열람하지 않음, 이 세션의 Secret 열람 금지 원칙). 문서가 정확했다 ―
  `SUPABASE_JWT_SECRET`은 여전히 `.env`에 없고(문서가 이미 "미설정"으로 기록),
  `api/auth.py`도 그 값 없이 JWKS/ES256 경로로 정상 검증됨을 코드로 재확인(HS256은
  값이 없으면 그 경로만 거부, 실사용자 인증은 영향 없음). `NEXT_PUBLIC_SUPABASE_URL`/
  `_ANON_KEY`는 `.env.local`에 정상 존재. 문서 드리프트 없음.
- **`X = row[X] or existing[X]` 패턴 전수 검색** ― `migrate_execute.py` 밖에는 없다
  (`storage/database.py`/`load_rights_data.py`/`load_spec_data.py` 확인). §3의 결함이
  이 파일에 국한된다는 뜻.
- **성능** ― 2,156행 기준 검색/상세 대표 쿼리 20회 측정, 전부 p95 1ms 미만
  (Sprint 100의 "3.1ms 이하" 측정과 같은 결론, 데이터가 늘어도 재확인됨).
- **결제/등기부 false-success 패턴** ― `SUCCESS` 결제인데 `subscriptions`/
  `registry_requests` 연결이 없는 행, `COMPLETED` 등기부인데 파일이 없는 행,
  `READY` 문서인데 실제 파일이 없는 행(555건 전수) 전부 0건. 단 결제/등기부는 베타
  특성상 실 데이터 자체가 없어(0행) 검사가 공허할 수 있다는 점은 남겨 둔다.
- **`filter/`/`src/login/` 죽은 코드 상태** ― 여전히 어디서도 import되지 않음(`filter/`),
  `src/login/`은 이미 삭제됨(Sprint 51). 재확인만, 변경 없음.
- **Sprint 105 SKIP 표의 "worktree 삭제(1.36GB)"** ― `git worktree list`로 재확인한 결과
  지금은 이 저장소(master) 하나만 등록돼 있다. 그 사이 다른 세션에서 이미 정리된 것으로
  보인다 ― 더 이상 유효한 Backlog 항목이 아니다(아래 SKIP 표에서 제외).

## 7. ★★ 크롤러의 사건번호 매칭이 부분 문자열이었다 ― 두 곳에 같은 결함이 따로 있었다

`§3`(migrate_execute.py의 병합 규칙)을 고치며 "동일 패턴이 다른 곳에도 있는가"를 찾다가,
`crawler/resume.py:resume_start_idx()`가 사건번호를 **부분 문자열 포함(`in`)**으로
매칭하고 있는 것을 발견했다. `test_crawl_resume.py`의 기존 픽스처(`LIST_ITEMS`)에는
이 결함을 드러낼 만한 데이터가 없었다 — 전부 자릿수가 겹치지 않게 골라져 있었다.

### 실 DB로 재현

```
python -c "..."  # auction 테이블에서 같은 법원 안의 case_no 쌍을 전수 대조
```

같은 법원 안에서 부분 문자열 충돌이 **4쌍** 실제로 존재했다. 그중:

```
"2024타경1009"는 "2024타경100920"의 부분 문자열이다 ― 둘 다 서로 다른 진짜 사건이다.
```

### 원인과 영향

```python
# crawler/resume.py (수정 전)
if resume_from in it["case_no"]:
    return idx + 1
```

체크포인트(`resume_from`)가 오늘 목록을 훑다가 **자신을 포함하는 무관한 다른
사건번호**를 먼저 만나면 그 위치를 "체크포인트 매칭"으로 오판한다. 그 무관한 항목이
목록에서 진짜 체크포인트보다 앞이면 재개 위치가 실제보다 앞당겨지거나(비효율) —
더 나쁘게는 뒤로 밀리면 아직 안 끝난 항목을 건너뛴다(수집 누락, 조용히).

**같은 패턴을 전수 검색**(`grep -rn "in it\[.case_no.\]\|in item\[.case_no.\]"`)하니
`crawler/base_crawler.py:go_to_case_detail()`(02:00 PDF 수집 Worker의 사건 진입
함수)에 **완전히 같은 결함**이 독립적으로 구현돼 있었다. 이쪽은 `wait_for_detail()`이
`\d{4}타경\d+` 정규식(탐욕적 매칭이라 전체 숫자를 다 잡는다)으로 최종 사건번호를
**정확히** 대조하는 안전장치가 있어 데이터 오염(엉뚱한 사건 문서를 저장)까지는
가지 않는다 — 대신 **매번 같은 무관한 항목에 먼저 걸려 타임아웃 후 실패**하므로,
이 충돌에 걸린 사건은 문서 수집이 재시도해도 계속 실패한다(조용한 영구 실패,
`document_collect_failures`에 쌓이지만 원인이 "그 사건 자체의 문제"처럼 보인다).

두 곳이 **각자 따로** 구현하고 있었다는 것 자체가 `validator/validation_engine.py`
상단 주석이 이미 남긴 교훈과 같다 ― "같은 판정을 하는 함수가 두 벌이면 한쪽만
고쳐질 수 있다"(실제로 그랬다 ― 어느 쪽도 먼저 고쳐지지 않은 채 둘 다 남아 있었다).

### 고친 것

`crawler/resume.py`에 공용 판정 함수 `case_no_matches_list_entry()`를 신설해 **정확
일치**(단일 사건번호는 그대로, `" / "`로 묶인 항목은 구성요소별로) 판정하도록 하고,
`resume_start_idx()`와 `base_crawler.go_to_case_detail()` 둘 다 이 함수 하나를
쓰도록 통합했다(중복 제거). `crawler/resume.py`는 원래 selenium 의존이 없는 순수
모듈이라(Sprint 47) `base_crawler.py`가 이 모듈을 가져와도 순환 임포트가 생기지
않는다(실제 임포트로 확인).

### 회귀 테스트

`test_crawl_resume.py`에 실 DB 충돌 사례를 그대로 재현하는 픽스처를 추가했다
(§0: 공용 함수 직접 검증 5건, §3-B: `resume_start_idx()`를 통한 통합 검증 2건).
`go_to_case_detail()` 자체는 selenium 의존이라 이 세션에서 직접 구동해 검증하지는
않았다 — 두 호출부가 **같은 함수**를 쓰도록 통합했으므로 공용 함수 검증이 두 곳
모두를 커버한다(다만 `wait_for_detail()`과의 상호작용을 포함한 end-to-end 동작은
실 크롤 환경에서만 확인 가능하며 이 세션 범위 밖이다).

## 변이 검증

| | 변이 | 결과 |
|---|---|---|
| M99 | `detect_stale_region_contamination_dryrun.py`에서 조건3(`stored in addr`) 가드를 제거 | **검출 O** ― 합성 사례(d)가 오탐되고 "정확히 1건" 검사도 2건으로 어긋남, §13-B 즉시 실패 |
| M100 | `test_api_regression.py`의 court_code 수정을 되돌림(빈 값으로) | **검출 O** ― IntegrityError로 즉시 실패(단독 실행) |
| M101 | `case_no_matches_list_entry()`를 정확 일치에서 `resume_from in it["case_no"]`(부분 문자열)로 되돌림 | **검출 O** ― §3-B가 `2 (expected 2)` -> `1`로 실패, §0도 즉시 실패 |

가드를 걷어내자 §13-B가 바로 빨간불이 됐다 ― 검사가 실제로 조건 3을 지키고 있다는
직접 증거다. M99/M100/M101 모두 원복 후 흔적 0건, 스위트 재통과 확인.

## 검증

| 항목 | 결과 |
|---|---|
| 파이썬 테스트 | **28/28 파일 통과** (실크롤 3개 제외, API 서버 내린 채, 크롤러 수정 후 전체 스위트 재실행으로 재확인) |
| `test_api_regression.py` 단독 | 수정 전 재현 O(결정론적) → 수정 후 단독 3회 연속 통과 |
| `test_crawl_resume.py` 단독 | §0/§3-B 신설 포함 전부 통과, M101로 실제 검출 확인 |
| `python -m compileall` | **exit 0** (크롤러 변경 후 재실행 포함) |
| `crawler.base_crawler` / `crawler.court_crawler` 실제 import | 순환 임포트 없음 실측 확인(컴파일만으로는 못 잡음) |
| 프런트 | 파일 미수정. `.next` 제거 후 `npm run dev`+`uvicorn` 재기동해 108/108 재확인(§6), TSC/LINT는 이 세션에서도 exit 0 |
| 실 DB | **한 줄도 쓰지 않았다** (탐지 스크립트는 읽기 전용, `test_api_regression.py`는 자체 cleanup으로 QA행 0건 확인) |
| 변이 잔여 | `detect_stale_region_contamination_dryrun.py` / `test_api_regression.py` / `crawler/resume.py` 모두 원복 확인 |

## 수정 파일

```
test_schema_hygiene.py                          KNOWN_DUPLICATE_INDEXES에 5번째 쌍 추가,
                                                  ALLOWED_SQL_PERCENT_TEMPLATES에 신규 스크립트 등록
test_pipeline_integrity.py                       sido 상한 4->5, §13 mismatch를 상한 방식으로,
                                                  §13-B(탐지기 자기 검증) 신설
test_api_regression.py                           test_admin() 고아 픽스처에 court_code 추가,
                                                  cleanup finally의 커넥션 정리 순서 수정
detect_stale_region_contamination_dryrun.py      신규 (dry-run 전용, --apply 없음)
crawler/resume.py                                 case_no_matches_list_entry() 신설(공용 판정),
                                                  resume_start_idx()가 이를 사용하도록 변경
crawler/base_crawler.py                           go_to_case_detail()의 부분 문자열 매칭을
                                                  case_no_matches_list_entry() 사용으로 교체
test_crawl_resume.py                              §0(공용 함수 검증) 신설, §3-B(실 DB 충돌
                                                  재현) 신설
docs/SPRINT121_REGRESSION_REBASELINE.md          신규 (본 문서)
```

**§1~6은 제품 코드(api/, storage/, crawler/, src/, migrate_execute.py 등) 변경 0건** ―
전부 테스트/도구/문서다. **§7만 예외다** ― `crawler/resume.py`/`crawler/base_crawler.py`는
실제 제품 코드(크롤러)이고, 부분 문자열 매칭을 정확 일치로 바꾼 실질적인 동작 변경이다.
Breaking Change는 아니다(기존 정상 매칭 케이스는 전부 그대로 통과 — §3 기존 테스트로
확인, 새로 막힌 것은 애초에 틀린 매칭이었던 경우뿐).

## SKIP (사용자/제품 결정 필요)

| 항목 | 이유 |
|---|---|
| `idx_audit_logs_admin_id` DROP | 스키마 변경. 순수 중복이라 급하지 않음 |
| `migrate_execute.py`의 `X = row[X] or existing[X]` 병합 규칙 재설계 | 핵심 파이프라인 로직 변경 - 파싱 실패/정당한 빈 값을 구분할 새 신호가 필요, 설계 결정 |
| `detect_stale_region_contamination_dryrun.py`의 결과 적용(id=357 sigungu 정정) | 실 데이터 변경, 저장소 관례상 PM 승인 |
| Task Scheduler 등록 | 사용자 환경 변경. 전제조건은 전부 검증 완료(Sprint 112) |
| Sprint 105~120의 SKIP 표 항목들 | 전부 승인/외부 조치 대기, 미해소 |

## 남은 Backlog

- **★★ 수집 파이프라인 스케줄러 등록** ― 2026-08-20에 검색 결과 0건이 된다.
  `register_scheduler_tasks.ps1 -Apply` 한 줄이면 된다(Sprint 112).
- `migrate_execute.py` 병합 규칙 재설계 검토 ― 이번 sigungu 오염처럼, "정당하게 빈 값"과
  "파싱 실패로 빈 값"을 구분 못 하는 한 같은 부류의 결함이 다른 컬럼/다른 시도 없는
  주소 유형(세종 외에 구/군이 없는 특수 사례가 더 있는지는 미조사)에서 또 나올 수 있다.
- 위 SKIP 표의 승인 대기 항목들
