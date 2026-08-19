Known Issues

#12

localhost는 정상

Chrome Extension 권한 반복

상태

해결 (2026-08-06, 절차 적용) — 코드 버그가 아니라 QA 절차 문제였음. `docs/APPROVAL_POLICY.md`에
"브라우저 권한 요청이나 Chrome Extension 사용은 정말 필요한 경우가 아니면 하지 않는다,
우선순위는 코드 분석→로그 확인→서버 확인→API 확인→마지막에 브라우저 QA"로 이미 명시되어
있었음. 이후 QA는 이 우선순위를 따른다(Type Check/Build/Lint/서버 응답 코드로 우선 검증,
브라우저 클릭 테스트는 회귀 위험이 있는 변경에서 정말 필요할 때만 마지막 단계로 수행).

--------

#13

Mock API

실제 API 미연동

상태

부분 해결 (2026-08-06 갱신) — Search/Detail/Favorite/Recent Items/Auth는 전부 실제 API 연동
완료(Mock 아님). Payment만 여전히 Mock(`MockProvider`).

**2026-08-06 변경**: 오랫동안 이 항목을 막고 있던 "PG사 미확정"은 CTO가 **KG이니시스로 확정**해
해소됨(`docs/decision-log.md` 참고). 따라서 이제 남은 것은 의사결정이 아니라 **실제 구현**이다:

- ~~`KGInicisProvider` 클래스 신설~~ → **2026-08-07 완료**(`api/v1/payment_providers.py`.
  `TossProvider`/`PortOneProvider`는 폐기 예정으로 표기 + 선택 시 경고 로그)
- ~~`get_payment_provider()`의 `_PROVIDERS` 맵과 `PAYMENT_PROVIDER` 허용값에 `kginicis` 추가~~ → **2026-08-07 완료**
- Interface v2 6개 메서드(`charge`/`create_order`/`confirm_payment`/`cancel_payment`/
  `verify_payment`/`handle_webhook`)를 KG이니시스 실제 API 호출로 구현 — **미착수(승인 대기)**.
  현재는 전부 `NotImplementedError`라 `PAYMENT_PROVIDER=kginicis`로 바꾸면 결제가 전부 실패한다
- 환불/Webhook 수신 엔드포인트 신규 구현(`cancel_payment`/`handle_webhook`은 여전히 미호출)

단 이 구현은 **외부 API Key 발급 + PG사 계약**이 선행돼야 하므로 승인 필요 작업으로 유지된다
(`docs/backend.md` 주의사항의 "PG 연동 코드 작성 금지"는 PG사 확정 이후에도 그대로 유효).
Provider 인터페이스(v2, Sprint 11)와 `payments.py`의 PG 흐름 순서 연결(Sprint 12)은 이미
완료돼 있어, 승인만 나면 Provider 클래스 하나 추가로 바로 이어질 수 있는 상태.

--------

#14

auction_case.case_no 전국 UNIQUE 제약 — 서로 다른 법원의 동일 사건번호가 하나의 사건으로 병합됨

상태

**해결 (2026-08-06 Sprint 23 Migration 실행 완료)** — `storage/migrations/011_auction_case_court_code_unique.sql`로 `UNIQUE(court_code, case_no)` 적용. `auction_case` 1,377→1,380건(충돌 3건이 법원별로 분리), `auction_item` 1,870건 불변, orphan 0건, **잘못된 법원 연결 0건**. `migrate_execute.py`의 dedup/조회 키도 복합키로 변경해 재오염 방지. 실행 전 백업 생성(`auction.db.backup_before_court_code_20260806_173734`)

`storage/migrate_v4_1.py`의 `auction_case` 테이블이 `case_no TEXT UNIQUE NOT NULL`로 선언되어
있어, 법원이 달라도 사건번호 문자열(예: "2024타경12345")이 같으면 같은 `auction_case` row로
취급된다. `migrate_execute.py`는 60개 법원(`config/courts.py:ALL_COURTS`) 전체를 매일 크롤링하는
구조라 사건번호 형식이 법원마다 독립적으로 채번되므로 충돌 가능성이 항상 존재하고, 실제로
현재 DB(`auction` 테이블) 기준 서로 다른 법원 간 사건번호 충돌이 **3건 실측 확인됨**(예:
"2024타경34089"가 2개 법원에서 동시에 존재). `migrate_execute.py`의 `auction_case` UPSERT가
Python `dict`로 `case_no`만 기준으로 dedup 후 `INSERT OR IGNORE`하므로, 충돌한 두 법원 중
먼저 처리된 쪽의 `court_name`만 `auction_case`에 저장되고 나머지 법원의 사건은 그 잘못된
`auction_case` row에 연결(`case_id` FK)된다.

현재 영향: `auction_item.court_name`(검색/상세 목록에 실제 노출되는 필드)은 법원별로 정확하게
개별 저장되어 있어 **Search/상세 목록에는 아직 눈에 보이는 오류가 없음**. 단
`GET /api/v1/item/{id}`가 반환하는 `case`(=`auction_case` row, `case_type`/`filed_date`/
`demand_deadline`용)는 이미 잘못된 법원에 연결되어 있는 상태이며, 지금은 이 3개 필드가
`migrate_execute.py`에서 전부 `NULL`로 채워지고 있어 화면(`properties/[id]/page.tsx` "사건
정보" 카드)에 당장 드러나지 않을 뿐이다 — 이 필드들을 채우는 기능이 추가되는 즉시 데이터
오염이 사용자에게 노출된다.

**해결 내역 (2026-08-06, CTO 승인 하에 Migration 실행)**

`auction_case`의 UNIQUE 키를 `case_no` 단독에서 **`(court_code, case_no)` 복합 UNIQUE**로 변경.
SQLite는 UNIQUE 제약을 ALTER로 못 바꿔 새 테이블 생성 → 이관 → 교체(표준 재작성 패턴)로 처리했다.

- `auction_case`에 없던 `court_code` 컬럼을 신규 추가. 정본 값은 크롤러 원본 `auction.court_code`
  (현재 법원명 문자열이 들어있고 NULL 0건임을 실측 확인 — `config/settings.py:COURTS`의
  `B000210` 형식과 다르지만 실제 데이터의 정본은 전자)
- `auction_item.case_id`를 `(court_name = court_code)` 매칭으로 재연결
- `migrate_execute.py`의 dedup 키와 조회 키도 복합키로 변경 — 안 했으면 매일 크롤링이
  `court_code=NULL` row를 만들어 재오염됐을 지점
- 사본 DB 리허설로 결과를 먼저 검증한 뒤 실제 적용, 실행 전 타임스탬프 백업 생성

**검증 결과**: `auction_case` 1,377→1,380(충돌 3건이 법원별로 정확히 분리), `auction_item`
1,870건 불변, orphan `case_id` 0건, **court mismatch 0건(원래 버그 해소)**, `migrate_execute.py`
재실행 시 신규 0/갱신 1,870으로 멱등 동작 확인.

--------

#15

로그아웃 기능이 앱 어디에도 노출되지 않음 (기능 공백)

상태

**해결 (2026-08-06 Sprint 23)** — `src/app/properties/page.tsx` 헤더(로그인 사용자만 도달하는 로그인 후 랜딩 화면)에 `LogoutButton`을 연결했다. `PrimaryNav`는 비로그인 접근이 가능한 `/search`에도 쓰이므로 그쪽에는 넣지 않았다.

`src/app/properties/LogoutButton.tsx`가 완성된 상태로 존재하지만(`supabase.auth.signOut()` →
`/login` 리다이렉트까지 구현 완료), **저장소 전체에서 이 컴포넌트를 import하는 곳이 단 한 곳도
없다**(`grep -rn "LogoutButton" src/` 결과 자기 자신의 정의 1줄뿐). `signOut` 호출도 이 죽은
파일 내부가 유일하다(`grep -rn "signOut" src/`) — 즉 **로그인한 사용자가 앱 안에서 로그아웃할
수 있는 경로가 전혀 없다**. 세션은 Supabase 쿠키에 남아 middleware가 계속 통과시키므로, 사용자가
직접 브라우저 쿠키를 지우지 않는 한 로그아웃 불가.

영향: 공용 PC 사용 시 계정 전환/보호 불가. Beta 출시 관점에서 사용자가 즉시 체감하는 기능
공백이며, 결제·등기부 신청 등 개인 정보가 걸린 서비스 특성상 우선순위가 낮지 않음.

수정 방향(구현하지 않음): 컴포넌트 자체는 이미 완성돼 있어 코드 작성은 거의 필요 없고, "어느
화면 어느 위치에 노출할지"(`properties/page.tsx` 헤더인지, `PrimaryNav`에 합칠지, 마이페이지를
신설할지)가 화면 스펙 결정 사항이다 — 이번 세션 원칙상 "Spec 변경 금지"에 해당해 임의로 배치하지
않고 발견 사실만 기록함. PM이 위치만 정하면 즉시 착수 가능(예상 작업량: import 1줄 + JSX 1줄).

2026-08-07 추가 확인: 로그아웃은 동작하지만 **경로가 `/properties` 한 곳뿐**이다 — `/search`,
`/favorites`, `/properties/recent`에서는 여전히 로그아웃할 수 없다(`PrimaryNav`에 로그아웃 없음).
게다가 그 `/properties` 화면 자체가 #17의 문제를 안고 있다. 노출 위치 확대는 여전히 Spec 결정 사항.

--------

#16

구독 플랜 업그레이드 직후 등기부 무료한도가 옛 플랜으로 계산될 수 있었음 (정렬 비결정성)

상태

**해결 (2026-08-07 Sprint 26)** — `api/v1/registry.py:get_user_free_limit()`

`ORDER BY started_at DESC LIMIT 1`은 전순서(total order)가 아니다. `started_at`은
`datetime.now().isoformat()`으로 저장되는데 Windows 시계 분해능(~15.6ms)상 짧은 간격의 두 결제가
**완전히 동일한 문자열**을 가질 수 있고, 그 경우 어느 구독이 뽑힐지 SQLite가 보장하지 않는다.
베이직(월 5회) → 프로(월 10회) 업그레이드를 같은 틱 안에서 하면 업그레이드 후에도 베이직 한도가
적용될 수 있었다.

발견 경위: Sprint 26 회귀 테스트 실행 중 `PRO remaining 9`가 `4`로, `10th request still PENDING`이
`PAYMENT_REQUIRED`로 한 차례 실패(재실행 시 통과) — 플래키의 원인을 추적해 확인했다.
동일 `started_at` 2행을 직접 넣어 옛 쿼리가 `BASIC`, 새 쿼리가 `PRO`를 반환함을 실측 확인.

수정: `ORDER BY started_at DESC, id DESC` — 나중에 INSERT된 구독이 항상 이긴다.

같은 뿌리의 정렬 비결정성을 전 도메인에 일괄 수정했다(`payments` 목록 및 초과결제 대상 선택,
`favorites`, `recent_items`, `registry_requests` 사용자/Admin 목록, `search_presets`).
특히 **Admin 목록은 offset 페이지네이션**이라 동률 행이 두 페이지에 중복 노출되거나 아예
누락될 수 있었다.

회귀 방어: `test_api_regression.py` 13번(정렬 결정성) / 14번(구독 플랜 tie-break) 섹션.

--------

#17

`/properties` 목록의 링크 id와 상세 화면이 읽는 id의 체계가 다름

상태

**미해결 (2026-08-07 발견, Spec 결정 대기)**

`src/app/properties/page.tsx`(로그인 후 첫 화면, `/`가 여기로 redirect)는 Supabase `properties`
테이블을 직접 조회해 카드를 그리고 `href={/properties/${property.id}}`로 이동시킨다. 그런데 상세
화면 `src/app/properties/[id]/page.tsx`는 그 id로 FastAPI `GET /api/v1/item/{id}`
(SQLite `auction_item`)를 조회한다 — **두 id는 서로 다른 시스템에서 독립적으로 채번되므로
전혀 다른 물건이 열리거나 404가 난다**.

영향: 로그인 직후 첫 화면에서 물건을 클릭하는 가장 자연스러운 동선이 깨진다. 다만 `PrimaryNav`의
"검색"으로 `/search`에 들어가면 정상 동선(FastAPI 기반)이라 서비스 자체가 막히지는 않는다.

부수 문제(같은 파일): 지역 `formatPrice`가 공용 `src/lib/format.ts` 구현과 다르게 동작한다
(항상 1억으로 나눔 → `0` → `"0.0억"`, `500만` → `"0.1억"`). 유일한 로그아웃 경로(`LogoutButton`)도
이 화면에만 있다.

수정 방향(구현하지 않음): `/properties` 목록을 FastAPI `auction_item` 기반으로 전환할지, 화면을
폐지하고 `/`를 `/search`로 redirect할지가 먼저 정해져야 한다 — 화면 스펙 결정 사항이라 임의로
바꾸지 않고 기록만 한다. 결정만 나면 작업량은 크지 않다.

--------

#18

레거시 `auction` 테이블의 UNIQUE 키에 법원이 빠져 있어, 다른 법원 물건이 매일 크롤링에서 덮어써짐 (데이터 소실)

상태

**✅ 2026-08-08 실제 복구 완료 (CTO 승인 하에 Migration 010~016 재작성·재실행)** — 2026-08-08
오전 재확인에서 이 작업 디렉터리의 `auction.db`/`storage/migrations/`(둘 다 git 비추적)가
아래 "해결" 내역이 전혀 반영되지 않은 이전 시점 상태로 되돌아가 있음을 발견했다(원인은 git이
이 파일들을 추적하지 않아 확인 불가 — `docs/CHANGELOG.md` 2026-08-08 Sprint 29 항목 참고).
같은 날 CTO가 "Migration 정합성 복구"를 명시 승인해, 존재하지 않던 `storage/migrations/010~016`
SQL을 코드의 실제 INSERT/SELECT 문(컬럼명·제약)을 근거로 재작성하고, 백업 확인 →
사본 리허설(2회, `PRAGMA foreign_keys=ON`/`OFF` 양쪽 모두) → 실제 `auction.db` 적용 →
사후 무결성 검증(30개 항목) → 기능 스모크 테스트 순으로 안전하게 재실행했다. 상세 절차·근거는
`docs/CHANGELOG.md` 2026-08-08(Sprint 30) 항목, 회귀는 `test_auction_identity.py` 참고.
아래는 그 복구 작업이 재현·확정한 최종 상태다.

이하는 그 이전(2026-08-07) 기록 보존.
소실 결함은 실제로 재발 중인 것으로 간주해야 한다.

아래는 2026-08-07 당시 기록(그 시점 조치 내역 보존, 위 재확인 전까지는 현재 상태를 대변하지 않음).

**해결 (2026-08-07, CTO 승인 하에 Migration 012/013 실행 완료)**

`storage/migrations/012_auction_court_code_unique.sql` — `auction`을 **`UNIQUE(court_code, case_no, item_no)`** 로,
`storage/migrations/013_auction_item_case_id_unique.sql` — `auction_item`을 **`UNIQUE(case_id, item_no)`** 로 변경했다.
`auction_item`은 court_code를 또 복제하는 대신 **case_id 기반**으로 갔다(CTO 지시). `case_id`가 가리키는
`auction_case`는 이미 `UNIQUE(court_code, case_no)`라 법원이 특정돼 있으므로, `(case_id, item_no)`는
"법원+사건번호+물건번호"와 동치이면서 같은 정보를 두 곳에 중복 저장하지 않는다.

**검증**: 사본 DB 리허설 후 실제 적용. `auction` 1,870행 / `auction_item` 1,870행 **id·전 컬럼 값 100% 보존**
(자식 테이블 11개가 `auction_item.id`를 참조하므로 id 보존이 필수였다), 인덱스 43개 전부 재생성,
orphan 0건, 충돌 주입 시 **두 법원 행이 공존**함을 확인. 실행 전 백업
`auction.db.backup_before_auction_unique_20260807_095423` 생성.

**함께 수정**: `storage/database.py:upsert_batch()`(조회·갱신 키에 court_code 추가),
`storage/database.py`의 `init_db()` 및 `storage/migrate_v4_1.py`의 CREATE TABLE(fresh clone도 같은 제약),
`migrate_execute.py`(`(case_id, item_no)`). 회귀 방어는 `test_api_regression.py` 22번,
`test_subscription_policy.py` 7번.

---

이하는 발견 당시 기록(보존).

**발견 시점 상태 (2026-08-07)**

`#14`(auction_case 복합키)는 2026-08-06 Migration으로 해결됐지만, **한 단계 아래인 크롤러 원본
테이블 `auction`은 손대지 않았다.** 이 테이블의 제약은 지금도 다음과 같다.

```sql
CREATE TABLE auction (
    ...
    UNIQUE(case_no, item_no)   -- court_code가 없다
)
```

`storage/database.py:upsert_batch()`는 이 키로 기존 행을 찾아 **UPDATE**한다
(`WHERE case_no=? AND item_no=?`). 그런데 UPDATE 대상 컬럼에 `court_code`/`court_name`/주소/
가격이 전부 포함되어 있다 — 즉 서로 다른 법원이 같은 사건번호+물건번호를 쓰면 **병합이 아니라
앞서 저장된 법원의 물건이 통째로 다른 법원 물건으로 교체된다.** 한쪽 법원의 물건이 서비스에서
사라진다.

**실측 (2026-08-07, 읽기 전용 조사)**

법원 간 사건번호 공유는 이미 3건 존재한다.

| case_no | 법원 A | 법원 B | 관측된 item_no |
|---|---|---|---|
| 2024타경34089 | 정읍지원 | 포항지원 | 정읍 `2` / 포항 `1` |
| 2024타경3700 | 부산지방법원 | 수원지방법원 | 부산 `1` / 수원 `2,3,4,5,6,10,11,12,14,15` |
| 2024타경4973 | 통영지원 | 성남지원 | 통영 `1` / 성남 `2,3,4,5,6,8,9,10` |

세 건 모두 **한쪽 법원이 `item_no=1`을 차지하고, 다른 법원의 목록에서는 정확히 `item_no=1`만
비어 있다.** (2024타경3700의 수원은 2~15 중 1·7·13이 없고, 2024타경4973의 성남은 2~10 중 1·7이
없다.) 물건번호 결번은 취하/기각 등으로도 생길 수 있어 **단정할 수는 없지만**, 충돌한 두 사례
모두에서 하필 `item_no=1`이 사라져 있다는 점은 이미 소실이 일어났을 가능성을 강하게 시사한다.
제약 특성상 덮어쓴 뒤에는 흔적이 남지 않아 사후 확인이 불가능하다.

**재현 (사본 DB, 실제 DB 무변경)**

`auction.db` 사본에서 부산지방법원 `2024타경3700 item_no=1` 행이 존재하는 상태로 수원지방법원의
같은 사건번호+물건번호를 `upsert_batch()`에 넣었더니 `updated=1`이 되고, 조회 결과 해당 행의
`court_code`가 `수원지방법원`, 주소도 수원 것으로 바뀌었다 — **부산 물건은 사라졌다.**

**2026-08-07에 한 것 (승인 없이 가능한 범위)**

1. `storage/database.py:upsert_batch()` — 덮어쓰기 직전 기존 행의 `court_code`와 새 값이 다르면
   **WARNING 로그**를 남긴다. 막지는 못하지만 "지금 다른 법원 물건을 지우는 중"이라는 사실이
   더 이상 조용히 지나가지 않는다(스키마를 못 바꾸는 상태에서의 최선)
2. `migrate_execute.py` — `auction_item` 조회/갱신 식별키를 `(case_no, item_no)`에서
   **`(case_id, item_no)`로 변경**했다. `case_id`는 바로 위에서 `(court_code, case_no)`로 구한
   값이라 이미 법원이 특정되어 있어, 스키마 변경 없이 하위 단계의 같은 결함을 차단한다.
   기존 주석에 "Critical TODO로 별도 기록"이라 적혀 있던 항목의 남은 절반이다.
   **검증**: 사본 DB 2개에 구/신 로직을 각각 적용해 `auction_item` 1,870행을 전 컬럼 비교 →
   **차이 0건**(현재 데이터에서는 동작 동일, 잠재 결함만 제거)
3. `test_subscription_policy.py` 7번 — 법원 간 공유 `case_no` 개수를 계속 출력·감시하고,
   `auction_item`에 실제 중복이 생기면 실패하도록 고정

**남은 조치 (승인 필요)**

- `auction`의 `UNIQUE(case_no, item_no)` → **`UNIQUE(court_code, case_no, item_no)`** 로 변경
  (`#14`와 동일한 테이블 재작성 패턴) + `upsert_batch()`의 조회/갱신 키에 `court_code` 추가
- `docs/backend.md`가 `auction` 테이블을 "크롤러 원본, 변경 금지"로 명시하고 있어 **CTO 승인 없이는
  손댈 수 없다.** 다만 "변경 금지"의 취지는 하위호환 보호이고, 이 제약은 데이터를 잃고 있으므로
  예외 판단이 필요하다
- 이미 소실된 물건은 재크롤링으로만 복구 가능하다(과거 데이터는 남아있지 않음)

--------

#19

`POST /api/v1/registry-requests`가 같은 사용자·같은 물건에 대한 중복 신청을 막지 않아, 반복
호출마다 별도 신청 행이 생기고 매번 무료 등기부 횟수가 추가로 소모됨(중복 소모 결함)

상태

**해결 (2026-08-09 Sprint 37, 승인 없이 가능한 버그로 판단해 즉시 수정)**

`api/v1/registry.py:create_registry_request()`는 물건 존재·구독 여부·무료 한도만 확인하고,
**같은 사용자가 같은 `item_id`에 이미 진행 중인 신청이 있는지는 확인하지 않았다.** 실측
재현(스크립트로 같은 `item_id`를 3회 연속 POST): `registry_requests` 3행 생성, 무료횟수
3회 소모 — 화면상으로는 신청 완료 후 "신청하기" 버튼이 사라지는 UI 흐름이라 정상 사용에서는
드러나지 않지만, 중복 클릭/새로고침 후 재제출/직접 API 호출(스크립트, 재시도 로직 있는
클라이언트 등)로 같은 물건에 대해 무료 한도를 여러 번 소모하거나 `PAYMENT_REQUIRED` 행이
중복 생성될 수 있었다.

**해결**: `BEGIN IMMEDIATE` 트랜잭션 안, 무료 한도 확인 이전에 "같은 사용자·같은 물건에
대해 진행 중인(PENDING/PAYMENT_REQUIRED/PROCESSING) 신청이 있는가"를 확인하는 조회를
추가했다. 있으면 새로 만들지 않고 **기존 신청을 그대로 반환**(응답에 `already_requested:
true` 플래그 추가 — 기존 필드는 전혀 바뀌지 않는 순수 추가라 Breaking Change 아님).
`COMPLETED`/`FAILED`(종결 상태)는 이 검사에서 제외해 **발급 실패 후 재시도·재발급 요청 같은
정당한 흐름은 그대로 허용**한다.

**검증**: 재현 스크립트로 수정 전/후 대조 — 수정 후 3회 연속 POST가 동일 `id`를 반환하고
`registry_requests`/`registry_usage` 행이 각각 정확히 1건만 남음(재현 확인). 회귀
`test_api_regression.py` 9번에 8개 검사 추가(중복 시 동일 id 반환·플래그·행 수·무료횟수
불변, FAILED 이후 재시도 허용·플래그 없음 확인, 하위 흐름을 위한 상태 원복까지) — 394→402검사,
연속 3회 PASS. `test_race_conditions.py`(서로 다른 물건 10개 동시 신청)는 이번 수정과
무관해 영향 없음을 재확인.

--------

#20

구독(Subscription) 결제 중복 방지 완전 부재

상태

해결 (2026-08-09, Sprint 38) — `api/v1/payments.py:create_payment()`가 `payment_type=SUBSCRIPTION`
요청을 처리할 때 사용자가 이미 유효한 구독(ACTIVE/GRACE_PERIOD)을 갖고 있는지 전혀 확인하지
않았다. #19(Registry 중복신청)와 같은 감사 방법(State/Data Consistency Audit의 "중복 요청"
항목)을 Payment/Subscription 도메인으로 확장하며 발견했다.

[발견] 실측 재현 — 같은 사용자로 PRO 연간 구독을 2회 연속 요청하면 `subscriptions` 행이 2개
(둘 다 ACTIVE) 생성되고 `payments` 행도 2개(둘 다 SUCCESS, 각 198,000원) 생성된다. 두 번째
구독은 만료 시각을 연장하는 게 아니라 완전히 별도 행으로 존재만 할 뿐, `get_entitled_subscription()`은
"유효한 구독이 하나라도 있는가"만 보므로 두 번째 결제는 사용자에게 아무 추가 혜택 없이 순수
중복 청구로 이어진다.

[판단] 새 UX/Spec 도입이 아니라 이미 존재하는 불변식을 백엔드가 못 지키던 문제로 분류했다 —
프론트(`src/app/properties/[id]/page.tsx`)의 구독 UI 전체가 `registryErrorCode ===
REGISTRY_SUBSCRIPTION_REQUIRED`(즉 "유효한 구독이 없다"는 백엔드 응답)에서만 렌더링되고,
구독 성공 즉시 그 조건이 거짓이 되어 UI가 스스로 사라진다. "이미 유효한 구독이 있으면 재구독
불가"가 프론트에 이미 전제된 불변식이었고, 이 지점에 도달하는 건 중복 클릭·새로고침 재제출·
직접 API 호출뿐이다. 승인 없이 수정 가능한 버그로 판단해 즉시 고쳤다.

[수정] `api/v1/payments.py`
- `create_payment()`에서 `payment_type=SUBSCRIPTION`이면 결제(`create_payment_record`)와
  구독 생성(`create_subscription`)을 시도하기 전에 `get_entitled_subscription()`(DB에 쓰지
  않는 순수 판정 함수, registry.py와 공유)으로 기존 유효 구독을 확인한다
- 있으면 새 결제/구독을 만들지 않고 **기존 구독을 그대로 반환**한다(`payment: null`,
  `registry_request: null`, `already_subscribed: true` — 기존 성공 응답 필드는 그대로 유지되어
  Breaking Change 아님)
- 요청한 plan과 실제 반환되는 plan이 다를 수 있다(예: 이미 PRO인데 BASIC을 다시 요청) — 프론트에
  "플랜 변경/업그레이드" UI 자체가 없어 이 경로로 오는 요청은 전부 중복 제출로 간주하고 기존
  구독을 그대로 지킨다
- CANCELLED/EXPIRED(종결 상태) 이후 재구독은 이 검사 대상이 아니다 — `get_entitled_subscription()`이
  ACTIVE/GRACE_PERIOD만 보므로 자연히 막히지 않는다(재구독은 정상 흐름)

[회귀 검증] `test_api_regression.py` 8번(Payment/Subscription)을 재구성:
- 기존에 같은 TEST_USER로 BASIC 월 구독 후 PRO 연 구독을 연이어 만들던 흐름(중복 방지 수정으로
  더 이상 불가능)을 분리 — 월 결제 기간(~30일) 검증은 전용 사용자로, TEST_USER는 곧바로 PRO
  연 구독 하나만 생성(하위 9번 Registry 테스트가 PRO 한도 10회를 전제하므로)
- 신규 검사 6개: 이미 구독 중 재구독 시도(같은 플랜이 아닌 BASIC으로) → success 유지 +
  기존 PRO 구독 그대로 반환 + `already_subscribed` 플래그 + `payment: null` + `subscriptions`/
  `payments` 행 추가 생성 없음(DB 레벨 COUNT로 확인)
- 연쇄 영향 수정: `test_payment_logs()`(21번)가 공유 TEST_USER로 다시 구독을 시도해 결제 로그
  3단계를 만들던 부분이 이제 차단되어(`payment: null`) `TypeError` 발생 — 전용 사용자로 분리해
  해결. `test_subscription_plan_tiebreak()`(14번)는 DB에 직접 INSERT하는 방식이라 영향 없음.
  `test_plans_api()`(15번)의 "카탈로그 가격 그대로 결제하면 통과"는 `success=True`만 확인해
  영향 없음(이미 구독 중이어도 success는 유지됨)
- 실측 재현 스크립트로 결제 5건 순차 호출 검증: (1) 최초 PRO 구독 성공, (2) 동일 플랜 재요청
  차단(기존 구독 반환), (3) 다른 플랜(BASIC) 재요청도 차단(기존 PRO 유지), (4) CANCELLED 처리
  후 재구독은 정상적으로 새 행 생성 확인, (5) `subscriptions`/`payments` 각 정확히 1행만 존재

[검증] 402 → **410검사**, 연속 3회 실행 전부 PASS, `auction.db` QA 데이터 잔여 0건.
`test_subscription_policy.py`는 이번 변경과 무관(DB 직접 조작 방식)해 영향 없음 재확인.
`python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

[관련 미해결 항목] 같은 감사에서 별도 항목을 하나 더 발견했으나 정책 결정이 필요해 이번에는
고치지 않고 Backlog로만 남긴다 — `registry_requests`가 무료 소진 후 관리자에 의해 FAILED로
처리돼도(`api/v1/admin.py:update_registry_request_status`) 그 무료횟수(`registry_usage` 행,
`get_free_count()`가 그대로 카운트)가 전혀 환불되지 않는다. `api/constants.py`의
`RegistryCreditReason.REFUND`가 이런 상황을 위해 정의는 돼 있지만 실제로 호출하는 코드가
어디에도 없다(죽은 사유 타입). "모든 FAILED가 환불 대상인가, 아니면 사유별로 다른가"는
새 정책 결정이 필요해 승인 없이 임의로 구현하지 않았다 — 다음 Sprint 논의 대상.

[문서] `docs/CHANGELOG.md` Sprint 38 항목, `docs/TEST_PLAN.md` 8번 섹션·검사 총계 갱신.

--------

#20 추가 발견 (같은 날 재감사, 순차 방어만으로는 불충분했음)

구독(Subscription) 결제 중복 방지 — 동시 요청(Race Condition) 재현

상태

해결 (2026-08-09, Sprint 38 재개) — #20의 최초 수정(`get_entitled_subscription()`로 확인 후
생성)은 **순차** 중복 요청만 막았다. 실제로는 확인(SELECT)과 생성(INSERT) 사이에 아무 잠금도
없는 "SELECT -> 판단 -> INSERT" 패턴이라, 동시에 도착한 두 요청이 서로의 커밋을 보지 못한 채
둘 다 "구독 없음"을 확인하고 통과할 수 있었다.

[발견] 실측 재현 — 같은 사용자로 PRO 연 구독을 정확히 동시에 10개 스레드로 요청하면
`subscriptions` 10행(전부 ACTIVE), `payments` 10행(전부 SUCCESS, 각 198,000원)이 생성됨
— 순차 재현으로는 드러나지 않던 결함이었다.

[수정] `api/v1/payments.py:create_payment()` — `payment_type=SUBSCRIPTION`일 때
`registry.py:create_registry_request()`(#19)와 동일한 방식으로 `conn.isolation_level = None`
+ `conn.execute("BEGIN IMMEDIATE")`를 확인 직전에 실행해 쓰기 락을 먼저 선점한다. 확인부터
결제/구독 생성, 최종 commit까지 전부 한 트랜잭션 안에서 이어지므로 동시 요청은 자연히
직렬화된다 — 먼저 락을 잡은 요청만 실제로 생성하고, 나머지는 그 락이 풀린 뒤 "이미 있음"을
보고 기존 구독을 반환한다. OVERAGE_USAGE 경로는 이미 조건부 UPDATE+rowcount로 별도 보호되고
있어 이번 변경의 영향을 받지 않는다(분기 조건으로 SUBSCRIPTION에만 적용).

[검증] 동시 10개 스레드 재현 3회 반복 + 20개 스레드 재현 3회 반복, 전부 `subscriptions`/
`payments` 각 정확히 1행만 생성되고 나머지는 `already_subscribed`로 동일 구독을 반환함을
확인. `test_race_conditions.py`에 3번째 시나리오(`test_subscription_race`, 5검사)로 상시
회귀화. 기존 등기부/초과결제 레이스 시나리오 2종은 이번 변경과 무관해 영향 없음 재확인.

[관련 강화] 같은 재감사에서 "결제 실패 후 재시도"도 실제로는 테스트된 적이 없었음을 확인
(`MockProvider`가 항상 SUCCESS라 자연 재현 불가) — `test_api_regression.py`에 provider를
일시적으로 실패하도록 교체하는 테스트를 추가해, SUBSCRIPTION/OVERAGE_USAGE 둘 다 결제 실패 시
entitlement가 생기지 않고(subscription 미생성 / registry_request 미연결) 재시도가 정상적으로
새 결제를 만들 수 있음을 확인(9검사 추가).

[검증] `test_api_regression.py` 410 → **419검사**, `test_race_conditions.py` 15 → **16검사**
(3개 시나리오 총합, cleanup 검사 포함), 연속 3회 실행 전부 PASS, `auction.db` QA 데이터 잔여
0건. `python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

[교훈] 순차 중복 방지 테스트만으로는 동시성 결함을 검출하지 못한다 — Registry(#19)/
Subscription(#20) 둘 다 "중복 요청 2회 연속 호출" 테스트는 먼저 통과했지만, 실제 동시
스레드 재현에서야 레이스가 드러났다. 앞으로 "확인 후 생성" 패턴을 새로 추가할 때는 순차
재현과 동시 재현을 모두 갖춰야 한다.

--------

#21

Admin 등기부 상태 전이 동시 요청 레이스 — 다른 관리자의 결과를 조용히 덮어씀

상태

해결 (2026-08-09, Sprint 39) — Sprint 37(#19)/Sprint 38(#20)의 "SELECT -> 판단 -> 쓰기" TOCTOU
감사를 `storage/database.py` 및 인접 도메인 전체로 확장하던 중, Admin 전용 상태 전이
엔드포인트에서 같은 부류의 결함을 발견했다.

**[발견]** `api/v1/admin.py:update_registry_request_status()`(`PATCH
/admin/registry-requests/{id}`)가 "현재 status SELECT -> `ALLOWED_TRANSITIONS`로 허용 여부
판단 -> `UPDATE ... WHERE id=?`"만 수행하고, UPDATE에 현재 status를 재확인하는 조건이 없었다.
같은 `request_id`(PROCESSING 상태)에 서로 다른 목표 상태(예: 하나는 COMPLETED, 하나는
FAILED)로 두 관리자 요청이 동시에 도착하면, 둘 다 "지금 PROCESSING"이라는 같은 스냅샷을
보고 전이 허용 검사를 통과한 뒤, 나중에 커밋되는 쪽이 앞서 커밋된 결과(COMPLETED의
`doc_url`이나 FAILED의 `reason`)를 아무 경고 없이 덮어쓸 수 있었다 — 실측 재현(threading)으로
확인.

**[판단]** `payments.py`의 OVERAGE_USAGE 연결이 이미 쓰고 있는 "조건부 UPDATE +
rowcount 확인" 패턴을 그대로 옮기면 되는, 새 정책 없이 기존 상태머신 불변식("한 신청은
한 번만 종결 처리된다")을 실제로 지키게 하는 문제라 승인 없이 수정 가능한 버그로 판단했다.

**[수정] `api/v1/admin.py`**
- COMPLETED/FAILED/PROCESSING 3개 UPDATE문 전부 `WHERE id=? AND status=?`(마지막 인자는
  SELECT 시점에 읽은 현재 status)로 바꿔, 그 사이 다른 요청이 먼저 상태를 바꿨다면
  `rowcount=0`으로 감지한다
- `rowcount=0`이면 롤백 후 `HTTPException(409, "다른 요청이 먼저 상태를 바꿨습니다...")`를
  던진다 — 관리자에게 "덮어썼는지도 모른 채 200이 온 것"이 아니라 명확한 충돌임을 알린다

**[검증]** 같은 PROCESSING 신청에 COMPLETED/FAILED를 동시에 PATCH하는 실측 재현: 정확히
1건만 200으로 성공하고, DB에 남은 최종 상태(status/doc_url/reason)가 이긴 쪽 결과로만
일관되게 남음(진 쪽 필드가 섞여 들어가지 않음)을 확인. 진 쪽이 받는 코드는 스레드 스케줄링에
따라 409(둘 다 SELECT를 통과한 뒤 UPDATE에서 걸림) 또는 400(진 쪽이 SELECT를 나중에 해
이미 바뀐 status를 보고 `ALLOWED_TRANSITIONS` 자체에서 걸림) 둘 다 가능 — 어느 쪽이든
이중 전이를 막는다는 점에서 올바른 결과라 테스트도 두 코드를 모두 유효로 받아들이도록
작성했다(처음에 409로만 단정했다가 5회 중 1회 flaky 실패로 이 사실을 발견, 즉시 보정).

**[영향 범위 확인]** 같은 TOCTOU 관점으로 `storage/database.py` 전체(`upsert_batch`,
`claim_next_queue_item`, `enqueue_documents`, `mark_queue_*`, `reset_stale_queue`)와
Favorites/Recent Items/Registry Credit 관리자 조정 경로를 재검토했다 — `claim_next_queue_item`
은 이미 동일한 조건부 UPDATE 패턴으로 안전, `enqueue_documents`/Favorites는 DB UNIQUE
제약으로 안전, `upsert_batch`는 SELECT-후-쓰기 패턴이지만 단일 스케줄 크롤러 프로세스에서만
호출되어 실질적 동시 호출 경로가 없음(수정 불필요, 문서화만). Search Presets 저장
(`POST /api/v1/search-presets`)은 이름/조건 중복을 막는 장치가 전혀 없음을 재확인했으나,
Registry/Subscription과 달리 프론트가 "중복 저장 불가"를 이미 전제하는 지점이 없어(다른
이름의 프리셋을 여러 개 저장하는 것과 구분이 안 됨) 새 정책 결정 없이 임의로 막을 수 없다고
판단해 Backlog로만 남겼다(낮은 심각도 — 금전/이용권 영향 없음).

**[프론트 동반 강화]** `src/app/properties/[id]/page.tsx`의 등기부/구독/결제 4개 핸들러
(`handleRegistryRequest`/`handleSubscribe`/`handlePayOverage`/`handleDownloadRegistry`)가
`FavoriteButton.tsx`/`handleToggleFavorite`가 이미 쓰던 "busy 플래그를 await 이전에 동기적으로
세운다" 패턴을 따르지 않아 빠른 연속 클릭 시 재진입 가드가 무력화될 수 있는 창이 있었다
(백엔드는 #19/#20으로 이미 안전하지만 불필요한 중복 요청 자체를 막는 게 맞음). 4개 핸들러
모두 같은 패턴으로 통일했다 — `handleSubscribe`가 성공 후 이어서 등기부 신청을 재시도하는
지점은 자기 자신의 가드에 막히지 않도록 가드 없는 내부 헬퍼(`performRegistryRequest`)로
분리했다.

**[회귀 검증]** `test_race_conditions.py`에 4번째 시나리오(`test_admin_registry_status_race`,
5검사) 신규 — 15 → **22검사**(신규 시나리오 5건 + 기존 파일 총합), 연속 5회 실행 전부 PASS.
`test_api_regression.py` 419검사 무변동 PASS. `python -m compileall`/`npx tsc --noEmit`/
`npm run lint`(0건)/`npm run build` 전부 통과.

**[문서]** `docs/CHANGELOG.md` Sprint 39 항목, `docs/TEST_PLAN.md` 검사 총계 갱신.

--------

#22

크롤러 문서 저장(현황조사서) — 쓰기 도중 강제종료 시 손상 파일이 영구히 "완료"로 오인됨

상태

해결 (2026-08-09, Sprint 40) — Sprint 39가 남긴 Backlog 3번(`storage/database.py` TOCTOU
전수 스캔)을 크롤러 파이프라인(`mvp_scraper.py`/`doc_worker.py`/`crawler/doc_crawler.py`)으로
확장하던 중 File/DB Consistency 관점에서 발견했다.

**[감사 방법]** `crawler/doc_crawler.py`의 세 문서 수집기(`collect_spec`/`collect_status`/
`collect_appraisal`)를 전부 재검토 — "다운로드 완료 확인 → 파일 저장 → 완료 상태 기록" 순서와
각 파일 쓰기가 원자적인지 확인했다.

**[발견]** `collect_spec()`/`collect_appraisal()`(PDF)는 `wait_for_download()`가 연속 2회
동일 크기를 확인한 뒤에만 경로를 반환하고(다운로드 완전 종료 보장), 그 파일을 `shutil.move()`
(같은 파일시스템 내에서는 `os.rename()`으로 원자적)로 최종 경로에 옮기므로 안전했다.
반면 **`collect_status()`(현황조사서 html+json)는 최종 경로(`status.html`/`status.json`)에
직접 `open(path, "w").write(...)`했다** — 이 쓰기 도중 프로세스가 강제 종료되면(전원 차단,
OOM kill 등 Python `except`로 잡을 수 없는 죽음) 목적지에 **잘려나간(손상된) 파일**이 남을 수
있었다. `doc_exists()`는 `status.json`의 존재 + 0바이트 초과만으로 "완료"를 판정하므로
(`_PRIMARY_EXT["status"] = "json"`), 손상됐지만 크기는 0이 아닌 파일이 한 번이라도 생기면
그 물건의 현황조사서는 **영구히 재수집 대상에서 제외**됐다(다음 실행이 "이미 존재. 스킵"으로
건너뜀).

**[판단]** 새 정책이 아니라 이미 다른 두 수집기(spec/appraisal)가 지키고 있는 "목적지 경로는
항상 완전한 내용만 갖는다"는 기존 불변식을 status 수집기만 못 지키고 있던 구현 공백이라,
승인 없이 수정 가능한 버그로 판단했다.

**[수정] `crawler/doc_crawler.py:collect_status()`**
- `status.html`/`status.json` 둘 다 `<경로>.tmp`에 먼저 쓰고 `os.replace(tmp, 경로)`로
  원자적 교체한다(같은 파일시스템 내에서 `os.replace()`는 원자적 — 중간 상태 자체가 존재할
  수 없다: 목적지는 항상 이전 내용 그대로이거나 새 내용 그대로만 남는다)
- 기존 예외 처리(json 추출 중 `Exception` 발생 시 html만 저장된 "부분 성공"으로 처리하는
  로직)는 그대로 유지 — 이번 수정은 "Python이 잡을 수 없는 강제종료" 시나리오만 추가로
  방어한다

**[검증]** 신규 `test_doc_storage_atomicity.py`(Selenium 불필요, 순수 파일시스템 로직만
검증, 12검사) — `get_doc_dir()`/`doc_exists()`(크기 가드, status의 json 우선 판정)와
"tmp 쓰기 후 replace 호출 전에 죽었다"를 시뮬레이션해 목적지가 손상되지 않고 이전 상태
그대로 남음을 확인, 이후 정상 재시도가 완료되면 새 내용으로 정확히 교체됨을 확인. 연속 3회
PASS. `test_api_regression.py` 419검사 무변동 PASS(회귀 없음). `python -m compileall`/
`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[영향 범위 확인]** `mvp_scraper.py`의 `upsert_batch()`/`enqueue_documents()`, `doc_worker.py`의
`claim_next_queue_item()` 기반 단일 워커 루프, `collect_spec`/`collect_appraisal`의 PDF
저장 경로는 이미 안전함을 재확인(수정 불필요) — 상세는 `docs/CHANGELOG.md` Sprint 40 참고.

**[문서]** `docs/CHANGELOG.md` Sprint 40 항목, `docs/TEST_PLAN.md` 신규 테스트 파일 등록.

--------

#23

크롤러 재시작 체크포인트(storage/checkpoint.py) — 쓰기 도중 강제종료 시 전체 손상 가능

상태

해결 (2026-08-10, Sprint 42) — Sprint 41의 크롤러 File/DB Consistency 감사를
`crawler/court_crawler.py`/`crawler/base_crawler.py`로 확장하던 중 발견했다.

**[감사 방법]** `court_crawler.py:crawl_court()`가 법원별 크롤링 재개(resume)를 위해 쓰는
`CheckpointManager`(`storage/checkpoint.py`)를 `#22`(collect_status 원자적 쓰기)와 같은
기준으로 재검토했다.

**[발견]** `CheckpointManager.save()`/`clear()`가 `logs/checkpoint.json`에 직접
`open(path, "w")`로 썼다. `crawl_court()`는 사건 하나를 처리할 때마다 `checkpoint.save()`를
반복 호출하므로(`court_crawler.py:143`), 이 저장 도중 프로세스가 강제 종료되면(전원 차단/
OOM kill 등) 파일 전체가 손상될 수 있었다. `_load_all()`은 JSON 파싱 실패를 "체크포인트
없음"으로 처리하므로, 손상되면 지금 저장 중이던 법원뿐 아니라 **이미 저장돼 있던 다른 모든
법원**의 체크포인트까지 함께 사라져(재시작 시 이어받기 불가) 다음 실행이 전체를 처음부터
다시 크롤링해야 했다.

**[판단]** `#22`와 동일한 부류(목적지 경로 직접 쓰기 → 쓰기 도중 손상 가능)의 구현 공백이라
승인 없이 수정 가능한 버그로 판단했다. 동시 다중 프로세스 접근(load-modify-write TOCTOU)
쪽은 `CheckpointManager`가 `mvp_scraper.py`의 단일 프로세스·법원 순차 루프 안에서만
호출되어 실제 동시 호출 경로가 없음을 확인했다 — 이 부분은 이론적 가능성만 있어 수정하지
않았다(근거만 기록).

**[수정] `storage/checkpoint.py`**
- `save()`/`clear()`의 파일 쓰기를 공용 헬퍼 `_write_all()`로 통합하고, `<경로>.tmp`에
  먼저 쓴 뒤 `os.replace()`로 원자적 교체하도록 변경(같은 파일시스템 내에서 원자적 —
  중간 상태 자체가 존재할 수 없다)

**[검증]** 신규 `test_checkpoint_atomicity.py`(Selenium 무의존, 15검사) — 여러 법원이 같은
파일을 공유해도 서로의 데이터를 지우지 않는지, "tmp 쓰기 후 replace 호출 전 강제종료"를
시뮬레이션해 목적지가 손상되지 않는지, 손상된 파일을 만나도 `get()`이 크래시하지 않고
안전하게 폴백하는지 확인. 연속 3회 PASS. `test_api_regression.py` 419검사 무변동 PASS.
`python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[영향 범위 확인]** `crawler/base_crawler.py`는 전부 Selenium DOM 파싱 함수라 파일/DB
쓰기 자체가 없어 감사 대상에서 제외(순수 함수, TOCTOU 불가능). `court_crawler.py:log_error()`
(`logs/errors.jsonl`)는 append 전용이라 손상돼도 최대 마지막 한 줄만 영향받고 이전 줄은
안전함을 확인 — 수정 불필요.

**[문서]** `docs/CHANGELOG.md` Sprint 42 항목, `docs/TEST_PLAN.md` 신규 테스트 파일 등록.

--------

#24

검색 정렬(sort_by) — 백엔드가 지원하는 crawl_date가 프론트엔드 타입/UI/테스트 3곳 모두에서
빠져 있었음

상태

해결 (2026-08-10, Sprint 43) — Frontend ↔ API Response Contract Audit 중 발견했다.

**[발견]** `api/v1/search.py:SORT_COLUMNS` 화이트리스트는 8개
(`auction_date/appraisal_price/minimum_bid_price/bid_rate/fail_count/crawl_date/case_no/
full_address`)인데, `src/app/search/types.ts:SearchQueryParams.sort_by`의 TypeScript
유니온 타입은 7개뿐이라 `crawl_date`가 빠져 있었다. 이 타입 파일 자체가 "필드명은
api/v1/search.py의 기존 쿼리 파라미터명과 동일하게 맞춘다"를 명시하고 있어 이는 그 자체
목적에 어긋나는 불일치였다. `src/app/search/SortBar.tsx`의 `SORT_OPTIONS` UI 버튼 목록도
같은 7개만 나열해, 사용자가 "수집일" 기준 정렬을 선택할 수 있는 경로 자체가 없었다.
회귀 테스트(`test_api_regression.py` §2)도 `sort_by=auction_date` 단 하나만 200인지
확인하고 있어, 나머지 7개(그 중 `crawl_date`)가 화이트리스트에서 빠지거나 오타가 나도
잡아내지 못하는 약한 검증이었다.

**[판단]** 타입 정의 파일의 필드명은 백엔드와 동일하게 맞춘다는 이 파일 자체의 명시적
목적에 따라 타입 정확성만 정정했다. `SortBar.tsx`에 "수집일" 정렬 버튼을 새로 노출할지는
사용자에게 어떤 정렬 기준을 제공할지 결정하는 제품/UX 판단이라 이번에는 손대지 않았다
(타입은 백엔드 능력을 정확히 반영해야 하지만, UI에 무엇을 노출할지는 별개의 결정).

**[수정] `src/app/search/types.ts`**
- `SearchQueryParams.sort_by` 유니온 타입에 `'crawl_date'` 추가(8개로 백엔드 화이트리스트와
  정확히 일치)

**[테스트 강화] `test_api_regression.py` §2(search)**
- 기존 "sort_by=auction_date 하나만 200인지" 검사를 8개 화이트리스트 값 전수 검사로
  확장 — 각 값이 200을 반환하는지뿐 아니라, 실제 응답의 `items`가 그 필드 기준으로 오름차순
  정렬돼 있는지(응답 body 내용까지)까지 확인(16검사 신규)

**[검증]** `test_api_regression.py` 419 → **434검사**(연쇄 반영으로 총합), 연속 3회 실행
전부 PASS. `npx tsc --noEmit`/`npm run lint`(0건)/`npm run build` 전부 통과.

**[관련 확인 — 이상 없음]** `properties/[id]/page.tsx:AuctionItemDetail`(상세 페이지 타입)은
백엔드 `GET /item/{id}` 응답 중 `sido`/`sigungu`/`dong` 3개 필드를 타입에 선언하지 않고
있으나, 이 페이지 어디에서도 그 필드를 실제로 참조하지 않아(grep 확인) 안전한 방향의
불일치(타입이 실제 응답의 부분집합)임을 확인 — TypeScript 구조적 타이핑상 런타임 오류
가능성이 없어 수정하지 않음. Registry/Subscription 결제 응답(`postJSON<unknown>`)은 애초에
타입을 강제하지 않고 `success`/`message`만 읽어 안전함을 재확인.

**[문서]** `docs/CHANGELOG.md` Sprint 43 항목.

---

#25

로그인 Redirect가 쿼리스트링을 버려 원래 URL로 정확히 복귀하지 못함

해결 (2026-08-10, Sprint 44)

**[증상]** 비로그인 사용자가 검색 결과에서 물건을 클릭하면 로그인으로 이동하는데, 로그인 후
돌아온 상세 화면에 **"이전 물건 / 다음 물건" 이동 버튼이 사라져 있었다.** 목록에서 들어온
것이 분명한데도 직접 링크로 들어온 것처럼 취급됐다.

**[원인]** `src/middleware.ts`가 로그인 URL을 만들 때
`loginUrl.searchParams.set('redirect', request.nextUrl.pathname)`으로 **pathname만** 실었다.
검색 결과의 링크는 `/properties/{id}?ids=84,85,86&i=0` 형태로 목록 내 이동 컨텍스트를
쿼리스트링에 담아 전달하는데(`ResultList.tsx`의 `navQuery`), 그 부분이 통째로 잘려나갔다.
로그인 후 `sanitizeRedirectPath()`가 돌려주는 값은 `/properties/{id}`뿐이라
`properties/[id]/page.tsx`의 `navIds`/`navIndex`가 빈 값이 되고, 이전/다음 버튼이
"컨텍스트 없음"으로 판정돼 렌더되지 않는다.

같은 결함이 **세션 만료 후 액션 경로에도** 있었다 — `properties/[id]/page.tsx`의
`router.push(\`/login?redirect=/properties/${id}\`)` 3곳(즐겨찾기 토글, 등기부 신청,
401 응답 처리)도 동일하게 쿼리스트링을 버렸다. 반면 `search/FavoriteButton.tsx`와
`SearchPresets.tsx`는 처음부터 `pathname + search`를 넘기고 있어, **같은 프로젝트 안에서
두 방식이 공존**하고 있었던 것이 문제를 오래 눈에 띄지 않게 만들었다.

**[수정]**
- `src/middleware.ts`: `pathname` → `pathname + search`
- `src/app/properties/[id]/page.tsx`: `loginRedirectUrl()` 헬퍼를 만들어
  `searchParams.toString()`을 붙이도록 3곳 통일
- Open Redirect 방어(`sanitizeRedirectPath`)는 **변경 없음** — 값이 길어졌을 뿐
  `/`로 시작하는 내부 상대경로라는 조건은 그대로다

**[검증]** 비로그인 상태로 `/properties/84?ids=84,85&i=0` 요청 시
`307 -> /login?redirect=%2Fproperties%2F84%3Fids%3D84%252C85%26i%3D0` 확인,
로그인 화면 HTML의 hidden input이 `value="/properties/84?ids=84,85&i=0"`로 전체 URL을
담고 있음을 확인.

**[관련]** `docs/FRONTEND_MASTER_SPEC.md` §3.4가 이 계약("pathname + query string 전체 보존")을
확정 정책으로 명시한다.

---

#26

검색조건 저장 목록이 인증 실패를 "불러오기 실패"로 표시

해결 (2026-08-10, Sprint 44)

**[증상]** 검색 화면의 "검색조건 저장" 카드에 빨간 글씨로
"저장된 검색조건을 불러오지 못했습니다"가 떴다. 사용자가 할 수 있는 조치가 없는 실패 메시지다.

**[원인]** `SearchPresets.tsx`의 초기 목록 조회가 모든 예외를 하나로 묶어 에러 문구를 띄웠다.
그런데 실제로 발생한 예외는 `ApiError(401)` — **세션이 유효하지 않다**는 뜻이었다.
브라우저에 남은 만료 토큰으로 `getSession()`이 세션 객체를 돌려주는 경우가 실제로 있어
(이번에 `SUPABASE_JWT_SECRET` 불일치 환경에서 재현됨) 컴포넌트는 자신을 로그인 상태로 믿고
조회를 시도한다. 같은 파일의 저장/삭제 경로는 이미 401/403을 로그인 유도로 처리하고 있어
**같은 파일 안에서 규칙이 갈렸다.**

**[수정]** `src/app/search/SearchPresets.tsx` — 목록 조회의 `catch`에서 401/403이면
`setAccessToken(null)`로 비로그인 상태로 되돌린다(안내 문구
"로그인하면 검색조건을 저장하고 불러올 수 있습니다"가 대신 표시됨). 그 외 예외만 에러로 표시.

**[검증]** 만료 토큰 상태의 실제 브라우저에서 빨간 에러 → 회색 안내 문구로 바뀌는 것 확인.

---

#27

로그인 상태인데 인증 API가 전부 401 — Supabase가 ES256으로 전환됐는데 백엔드는 HS256만 검증

해결 (2026-08-10 Sprint 46) — Sprint 45에서 원인 확정, Sprint 46에서 수정

**[증상]** 로그인된 사용자인데도
- `/favorites`, `/properties/recent` 진입 시 로그인 화면으로 튕김
- 검색 화면의 "검색조건 저장" 목록 조회 실패
- 검색 결과의 즐겨찾기 하트가 **전부 빈 하트(🤍)** 로 표시 (실제 즐겨찾기 여부와 무관)

Supabase 세션 자체는 유효하다 — `middleware.ts`의 `supabase.auth.getUser()`는 통과하고
`/properties/[id]` 상세 진입도 정상이다. **오직 FastAPI만 같은 토큰을 거부한다.**

**[원인 — 확정]** Supabase 프로젝트가 **비대칭 JWT 서명(ES256)** 으로 전환됐다.
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`이 HTTP 200으로 `kty=EC, alg=ES256` 키를
1개 게시하고 있음을 확인했다(2026-08-10). 즉 사용자 access token은 이제 ES256으로 서명된다.

반면 백엔드는 세 곳 모두 **공유 시크릿 + HS256 고정**으로만 검증한다:
- `api/auth.py:20-23` — `get_current_user()`. favorites / recent-items / search-presets /
  registry-requests / payments 등 **인증 필수 라우트 전부**가 여기를 지난다
- `api/v1/item.py:47-48` — 선택적 인증
- `api/v1/search.py:145-146` — 선택적 인증

ES256으로 서명된 토큰은 `algorithms=["HS256"]` + 대칭 시크릿으로는 **원리상 절대 검증되지
않는다**(서명 알고리즘 자체가 다름). 그래서 인증 필수 라우트는 401, 선택적 인증 라우트는
`JWTError`를 삼키고 비로그인으로 처리 → 검색은 되지만 `is_favorited`가 항상 false가 된다.

참고로 `NEXT_PUBLIC_SUPABASE_ANON_KEY`의 JWT 헤더는 여전히 `alg=HS256`이다 — anon/service
키는 레거시 형식을 유지하므로, **anon 키만 보고 "이 프로젝트는 HS256"이라고 판단하면 안 된다.**
이번 오진의 함정이 정확히 이 지점이었다.

**[해결 방향]** Secret 교체가 아니라 **검증 코드 변경**이다(시크릿을 아무리 바꿔도 해결되지 않음).
JWKS에서 공개키를 받아 ES256으로 검증하도록 위 3곳을 고쳐야 한다. `python-jose`는 ES256과
JWK dict를 이미 지원하므로 **새 라이브러리 설치는 불필요**하다. 키는 `kid`로 선택하고
캐시해야 한다(요청마다 JWKS를 받으면 안 됨). 레거시 HS256 토큰이 남아 있을 수 있으므로
전환기에는 두 알고리즘을 모두 허용하는 편이 안전하다.

**[범위]** Sprint 44는 Frontend 전용(백엔드 코드 수정 금지)이라 원인 확정과 기록까지만 수행.
프론트엔드 코드 결함은 아니다 — 프론트는 토큰을 정확히 실어 보내고 있다.

**[영향]** 이 결함이 해소되기 전에는 즐겨찾기 / 최근조회 / 검색조건 저장 / 등기부 신청 /
구독·결제가 **로그인 상태에서도 동작하지 않는다.** 비로그인 검색 경로는 영향 없음.

### #27 해결 내역 (2026-08-10 Sprint 46)

**[수정] `api/auth.py`** — `decode_supabase_jwt()` 신설. 토큰 헤더의 `alg`를 보고
ES256(JWKS 공개키) / HS256(레거시 공유 시크릿) 중 맞는 경로로 검증한다.

- **알고리즘 화이트리스트 고정**: 토큰이 알려준 `alg`를 그대로 `algorithms=[alg]`에 넘기면
  `alg:"none"` 위조가 통과한다. 대칭(HS256)/비대칭(ES·RS 계열) 두 집합에 없는 alg는 전부 거부
- **kid 기반 키 선택 + JWKS 캐시**(TTL 600초). 캐시에 없는 kid가 오면 재조회해 **키 회전**에
  대응하되, 최소 재조회 간격 30초로 외부 호출 폭주를 막는다. JWKS 조회 실패 시 기존 캐시를
  비우지 않는다(일시적 오류로 전원 로그아웃되는 것을 막기 위함)
- **예외 정규화**: jose는 `JWTError`가 아닌 형제 예외(`JWSError` 등)를 던지는 경로가 있는데,
  호출부는 `except JWTError`만 잡는다. 그대로 새어 나가면 **선택적 인증** 라우트(검색/상세)가
  토큰이 이상하다는 이유로 500이 된다. 검증 실패는 종류 불문 `JWTError`로 정규화했다
  (테스트 작성 중 실제로 발견한 결함)
- **실패 사유 로깅**(토큰/시크릿 제외). 원인 없이 401만 떨어져 이 사고를 오래 못 찾았다
- **HS256을 계속 허용하는 이유**: 전환기의 기존 토큰과, 합성 시크릿으로 HS256 토큰을 만들어
  인증 로직을 검증하는 기존 회귀 스위트(`test_api_regression.py`)가 그대로 동작해야 한다

**[수정] `api/v1/item.py` / `api/v1/search.py`** — 각자 복사돼 있던 `jwt.decode(..., HS256)`을
공용 `decode_supabase_jwt()` 호출로 대체(검증 로직 3중 중복 제거).

**[검증]** `test_auth_jwt.py` 신규 23검사 전부 통과. 결정적 증거는 **실제 Supabase ES256 토큰**으로
같은 요청을 두 서버에 보낸 비교다 — 구 코드 서버는 `search-presets`/`recent-items`/`favorites`
전부 401, 새 코드 서버는 전부 **200**. `test_api_regression.py` 434검사도 무변동 통과
(HS256 경로가 보존됐다는 증거).

**[주의]** 이미 떠 있는 API 서버 프로세스는 `--reload`가 걸려 있어도 이번 변경을 확실히
반영하지 못할 수 있다. 배포/로컬 모두 **API 서버를 완전히 재기동**해야 적용된다.

---

#28

체크포인트 원자적 쓰기가 코드에서 사라져 있었음 (#23 수정분 유실)

해결 (2026-08-10, Sprint 47)

**[증상]** `test_checkpoint_atomicity.py`의 "orphaned tmp from the simulated crash is gone"
검사가 실패했다. 다른 검사는 전부 통과해서 오래 눈에 띄지 않았다.

**[원인]** `storage/checkpoint.py`의 `save()`/`clear()`가 **목적지 파일에 직접 쓰고 있었다** —
임시 파일도 `os.replace()`도 없었다. 이는 `docs/BUGS.md` #23(2026-08-10 Sprint 42)이
"원자적 쓰기로 고쳤다"고 기록한 바로 그 결함이다. 즉 **한 번 고친 수정이 코드에서 사라진 상태**였다.

**`storage/` 전체가 `.gitignore` 대상**이라 이 파일은 git이 추적하지 않는다. 따라서 언제·어떻게
되돌아갔는지 이력으로 확인할 방법이 없다(`docs/CLAUDE.md`의 "storage/ 가 통째로 gitignore되어
load-bearing 소스가 버전관리 밖에 있다"는 경고가 현실화된 사례다).

**[영향]** 체크포인트 저장 도중 프로세스가 죽으면 `logs/checkpoint.json`이 반쯤 잘린 JSON으로
남고, 다음 실행의 `_load_all()`이 이를 파싱하지 못해 `{}`로 폴백한다 → **크롤러가 전체 법원의
진행 상황을 잃고 처음부터 다시 긁는다**(데이터 손상은 아니지만 재수집 비용이 크다).

**[수정] `storage/checkpoint.py`** — `_write_atomic()` 헬퍼를 추가하고 `save()`/`clear()` 둘 다
이를 쓰도록 했다. 임시 파일에 쓰고 `flush()` + `os.fsync()` 후 `os.replace()`로 교체한다
(같은 볼륨에서 원자적이라 목적지는 "이전 내용" 아니면 "새 내용" 둘 중 하나만 된다).
`clear()`도 같은 이유로 원자화했다 — 삭제 도중 죽으면 남은 법원들의 진행 상황까지 날아간다.

**[검증]** `test_checkpoint_atomicity.py` 15검사 전부 통과.

**[교훈]** gitignore된 디렉터리의 소스는 수정이 조용히 사라져도 아무도 모른다. 이번에 이걸
잡아낸 것은 **테스트뿐이었다** — `storage/`의 회귀 테스트는 특히 중요하다.

---

#29

정렬 버튼이 실제 정렬을 바꾸지 못하고, 정렬 화살표가 데이터와 반대로 표시됨

해결 (2026-08-11, Sprint 49)

**[증상]** 첫 화면(`/`)에서 "매각기일 ↑"로 표시되는데 실제 결과는 내림차순이었다. 그 상태에서
"매각기일"을 눌러도 결과 순서가 전혀 바뀌지 않았다(사용자에게는 "눌러도 반응 없는 버튼").

**[원인]** `src/app/search/SortBar.tsx`의 기본값이 백엔드 기본값과 달랐다.

- 백엔드(`api/v1/search.py`): `sort_order` 기본값 `"desc"`, `sort_by`가 없으면
  `ORDER BY auction_date DESC, fail_count DESC`
- 프론트(수정 전): `searchParams.get('sort_order') || 'asc'`

그래서 파라미터가 없는 첫 로드에서 화면은 ↑(asc)라고 말하는데 데이터는 desc였고, 첫 클릭은
`currentSortBy === 'auction_date'`로 판정되어 asc→desc 토글 → **이미 적용 중인 정렬과 같은 값**을
URL에 실었다. 실측(2026-08-11): 파라미터 없는 `/api/v1/search`의 첫 5건 `auction_date`는
전부 2026-08-12(desc), `sort_order=asc`는 2026-08-11(asc)로 서로 다르다.

**[수정]** 기본값을 백엔드와 동일한 `'desc'`로 맞췄다.

---

#30

정렬을 바꿔도 페이지 번호가 유지되어 "감정가 높은 순"인데 가장 싼 물건이 보임

해결 (2026-08-11, Sprint 49)

**[증상]** 실제 브라우저 재현: `/?page=3`(총 41건, 3/3페이지)에서 "감정가"를 누르면 URL이
`/?page=3&sort_by=appraisal_price&sort_order=desc`가 되고, 화면에는 "감정가 ↓"가 활성인데
**감정가 1353만(데이터 최저값) 1건**만 보인다. 사용자가 요청한 것("감정가가 가장 높은 순")과
정반대의 화면이다.

**[원인]** `SortBar.handleSortClick()`이 `page`를 그대로 두었다. 정렬 기준이 바뀌면 결과 순서
자체가 달라지므로 이전 페이지 번호는 의미를 잃는다. 같은 파일군의 다른 동작은 이미 이 규칙을
지키고 있었다 — `Pagination.changeSize()`는 size 변경 시 `page=1`로 리셋하고,
`SearchForm.handleSearch()`는 새 검색 시 page를 아예 생략한다. **SortBar만 예외**였다.

**[수정]** 정렬 변경 시 `params.set('page', '1')`.

---

#31

페이지 번호가 범위를 벗어나면 "검색 결과가 없습니다"라는 틀린 안내 + 조건을 버리는 복구 동선

해결 (2026-08-11, Sprint 49)

**[증상]** `/?address_detail=옥천면&page=9`(조건에 맞는 물건 6건 존재)에서 화면은
"검색 결과가 없습니다 / 검색조건을 줄이거나 지역·가격 범위를 넓혀보세요"라고 안내했다.
원인은 조건이 아니라 페이지 번호인데 정반대의 처방을 한 것이다. 게다가 유일한 복구 동선인
"조건 없이 전체 물건 보기"는 사용자의 검색조건까지 버렸고, 페이지네이션은 "9 / 3"을 표시했다.

**[도달 경로]** UI 조작만으로는 도달하지 않지만(다음 버튼이 마지막 페이지에서 비활성),
**북마크·공유 URL에서 실제로 도달한다**. 기본 필터가 `auction_date >= 오늘`이라 결과 건수가
매일 줄어들기 때문에, 어제 유효했던 3페이지 링크가 오늘은 범위 밖이 될 수 있다.

**[수정]** `ResultList`가 "결과 0건(`total === 0`)"과 "페이지 범위 초과(`total > 0`이고
`items`만 비어 있음)"를 구분한다. 후자에서는 총 건수와 마지막 페이지 번호를 알려주고,
**검색조건을 유지한 채 1페이지로 가는 링크**(`SearchScreen`이 page만 제거해 만든 `firstPageHref`)를
제공한다.

---

#32

목록 컨텍스트 없이 상세에 들어가면 "이전/다음 물건" 바가 죽은 상태로 노출됨

해결 (2026-08-11, Sprint 49)

**[증상]** `/properties/84`처럼 쿼리스트링 없이 상세에 들어가면 "← 이전 물건 / **1 / 1** /
다음 물건 →" 바가 양쪽 버튼 모두 비활성인 채로 떠 있었다. 실제 도달 경로는 흔하다 —
`/favorites`와 `/properties/recent`의 카드가 모두 `/properties/{id}`로만 링크한다.

**[원인]** `''.split(',')`는 `['']`를 돌려주고 `Number('')`는 `0`이며 `Number.isInteger(0)`은
true다. 그래서 `ids` 파라미터가 아예 없어도 `navIds = [0]`(길이 1)이 되고, `Number(null)`도
0이라 `navIndex = 0`으로 판정됐다. `docs/FRONTEND_MASTER_SPEC.md` §9.2와 코드 자신의 주석
("컨텍스트가 없으면 이전/다음 버튼을 아예 노출하지 않는다") 둘 다와 어긋나는 상태였다.

**[수정]** 계산을 순수 함수 `src/app/properties/[id]/navContext.ts:resolveNavContext()`로
분리하고(동작은 그대로), 빈 세그먼트를 먼저 걸러내고 `i` 파라미터의 부재를 `null`로 명시 구분했다.
분리한 이유는 회귀 테스트다 — 상세 화면은 로그인 필수 + 클라이언트 렌더라 HTTP 계약 테스트로
관찰할 수 없다(`crawler/resume.py:resume_start_idx()`를 같은 이유로 분리했던 것과 같은 판단).

**[검증]** `tests/nav-context.test.mjs` 8검사. 변이 테스트로 검출력 확인 —
빈 세그먼트 필터를 제거하면 2검사 실패, `i` 부재를 0으로 폴백시키면 1검사 실패.

---

#33

검색 UI의 물건종류 69개 중 60개가 항상 0건 — 크롤러가 저장하는 값과 어휘가 다름

**미해결 (2026-08-11 Sprint 49 발견·측정). 어휘 결정이 선행돼야 하므로 임의 수정하지 않음.**

**[증상]** `PropertyTypeTree`(주거용/상업및산업용/토지/차량및중장비/기타 5그룹 69항목)에서
"다세대주택"을 선택하면 결과가 0건이다. 그런데 DB에는 `다세대` 물건이 **246건** 있다.

**[측정]** 69개 항목 각각을 백엔드와 동일한 `property_type LIKE '%값%'`으로 조회한 결과
(2026-08-11, `auction_item` 1,870행 기준):

- 결과가 나오는 항목: **9개** (기타 259 / 전 244 / 답 244 / 아파트 201 / 임야 179 /
  연립주택 133 / 대지 103 / 단독주택 85 / 다가구주택 76)
- **항상 0건인 항목: 60개** (다세대주택, 오피스텔(주거), 오피스텔(상업), 근린생활시설,
  근린상가, 공장, 창고시설, 승용차, 선박 … 등 전부)

역방향으로, DB에 실제로 있는데 UI 항목명으로는 고를 수 없는 값:

| DB property_type | 건수 | 부분일치로 도달 가능한 UI 항목 |
|---|---|---|
| `다세대` | 246 | 없음 |
| `상가,오피스텔,근린시설` | 202 | 없음 |
| `근린시설` | 164 | 없음 |
| `오피스텔` | 102 | 없음 |
| `상가` | 18 | 없음 |
| `자동차` / `자동차,중기` | 4 / 9 | 없음 |

이름으로 전혀 도달할 수 없는 행이 **745건 / 1,870건(약 40%)**이다.

**[원인]** 두 어휘가 서로 독립적으로 만들어졌다.

- UI: `src/components/PropertyTypeTree.tsx` — Tank Auction 검색폼 HTML
  (`search/reference/01_SEARCH_FORM.html`)의 `chkGrpCtgr`/`chkEaCtgr`를 **"축약 없음"으로 전수 복사**
- DB: 크롤러가 `courtauction.go.kr`에서 수집한 원문 문자열 18종(`다세대`, `근린시설`,
  `상가,오피스텔,근린시설` 같은 **복합값 포함**)
- 백엔드(`api/v1/search.py`)는 이 값을 ENUM이 아니라 자유 문자열 `LIKE %값%`으로 매칭한다
  (`docs/search-engine.md`에 "ENUM 코드화는 설계만 완료, 미구현"으로 이미 기록된 상태)

**[왜 이번에 고치지 않았나]** 해결책이 셋인데 셋 다 확정된 결정을 뒤집는다.

1. UI 어휘를 DB 값으로 교체 — `PropertyTypeTree`의 "Tank Auction 전수 복사, 축약 없음"이라는
   기록된 결정과 `FRONTEND_MASTER_SPEC.md` §8.1의 "재구현 금지"에 어긋난다
2. 백엔드에 동의어 매핑 도입 — 검색 API 의미가 바뀐다(`docs/CLAUDE.md` 기존 API 유지 원칙)
3. 크롤러가 수집값을 정규 분류로 정규화 — 크롤러/DB 변경 + 재수집 필요

특히 `상가,오피스텔,근린시설` 같은 **복합값**은 단순 1:1 매핑으로 풀리지 않는다
("근린생활시설"을 고른 사용자에게 이 복합 물건을 보여줄 것인가"는 제품 판단이다).

**[영향]** 검색의 핵심 필터 하나가 사실상 동작하지 않는다. 주소/가격/법원/유찰횟수 등 나머지
검색조건은 정상이므로 검색 기능 전체가 막힌 것은 아니지만, **Release 전 결정이 필요한 항목**이다.

### #33 재검증 (2026-08-11 Sprint 50) — 임의 수정 없음, 측정과 해결안 정리만

**결론 먼저**: 상태 변동 없음. 오히려 **사용자가 실제로 보는 화면 기준으로는 더 나쁘다.**

**[재측정 — 실행 중인 API로 69개 항목 전수 조회]**

| 기준 | 결과 |
|---|---|
| 전체 `auction_item` 1,870행 | 결과 나오는 항목 9 / **항상 0건 60** (87%) |
| **기본 검색 화면(`auction_date >= 오늘`, 41행)** | 결과 나오는 항목 7 / **항상 0건 62 (90%)** |
| 이름으로 도달 불가한 행 | 전체 **745/1,870 (39.8%)** · **진행 중 26/41 (63.4%)** |

기본 검색 화면에서 결과가 나오는 항목은 **임야(8) · 기타(4) · 연립주택(2) · 아파트(1) ·
전(1) · 답(1) · 대지(1)** 7개뿐이다. 나머지 62개는 눌러도 항상 "검색 결과가 없습니다"다.

**[DB 값 18종 ↔ UI 어휘 대조표]**

| DB `property_type` | 전체 | 진행중 | 현재 UI에서 LIKE로 잡히는 항목 |
|---|---|---|---|
| `기타` | 259 | 4 | 기타 |
| `다세대` | 246 | 9 | **(없음)** |
| `상가,오피스텔,근린시설` | 202 | 7 | **(없음)** |
| `아파트` | 201 | 1 | 아파트 |
| `전답` | 188 | 1 | 전, 답 |
| `근린시설` | 164 | 5 | **(없음)** |
| `연립주택,다세대,빌라` | 130 | 2 | 연립주택 |
| `임야` | 123 | 8 | 임야 |
| `오피스텔` | 102 | 5 | **(없음)** |
| `대지,임야,전답` | 56 | 0 | 전, 답, 임야, 대지 |
| `대지` | 47 | 1 | 대지 |
| `단독주택,다가구주택` | 43 | 0 | 단독주택, 다가구주택 |
| `단독주택` | 42 | 0 | 단독주택 |
| `다가구주택` | 33 | 0 | 다가구주택 |
| `상가` | 18 | 0 | **(없음)** |
| `자동차,중기` | 9 | 0 | **(없음)** |
| `자동차` | 4 | 0 | **(없음)** |
| `연립주택` | 3 | 0 | 연립주택 |

**[중요 — 고칠 이름은 6개뿐이다]** 도달 불가 745행 전부가 아래 **6개 UI 항목명**의 불일치에서 온다.

| UI 항목(현재) | DB 실제 값 | 회복되는 행 |
|---|---|---|
| `다세대주택` | `다세대` | 246 (+ `연립주택,다세대,빌라` 130은 이미 연립주택으로 도달) |
| `근린생활시설` | `근린시설` | 164 |
| `오피스텔(주거)` / `오피스텔(상업)` | `오피스텔` | 102 |
| `근린상가` (또는 신규 `상가`) | `상가` | 18 |
| `자동차관련` | `자동차` | 4 |
| (없음) | `자동차,중기` | 9 |
| — 복합값 `상가,오피스텔,근린시설` | 위 3개 중 어느 것으로 잡을지 **정책 판단 필요** | 202 |

즉 **결정만 나면 코드 작업은 상수 몇 줄**이다. 남은 진짜 쟁점은 하나다 —
**`상가,오피스텔,근린시설`(202행) 같은 복합값을 세 항목 각각에 노출할 것인가.**
노출하면 "근린생활시설"을 고른 사용자에게 상가/오피스텔 물건이 함께 나오고,
노출하지 않으면 202행이 계속 도달 불가로 남는다. 이건 제품 판단이다.

**[해결안 3가지 · 비용/영향 비교]**

| 안 | 변경 지점 | 비용 | 리스크 | 되돌리기 |
|---|---|---|---|---|
| ① UI 어휘를 DB 값으로 교체 | `src/components/PropertyTypeTree.tsx` 상수 배열 | 낮음 | Tank Auction 전수 복사(§12.2 기록된 결정)와 어긋남. 크롤러가 새 값을 수집하면 다시 어긋남 | 쉬움 |
| ② 백엔드 동의어 매핑 | `api/v1/search.py`에 UI어휘→DB값 매핑 테이블 1개 | 낮음 | 검색 API 의미가 바뀜(`docs/CLAUDE.md` 기존 API 유지 원칙). UI는 그대로 둘 수 있음 | 쉬움 |
| ③ 크롤러가 정규 분류로 정규화 | `normalizer/` + 재수집 또는 백필 | 높음 | 데이터 변경. 원문 소실 위험. 복합값 분해 규칙 필요 | 어려움 |

**②가 가장 국소적**이다 — UI(§8.1 재구현 금지)와 크롤러 원문을 모두 건드리지 않고
매핑 테이블 하나로 끝난다. 다만 검색 API 동작 변경이라 승인이 필요하다.

**[Release Blocking 판정]**

**Release Blocking 아님 — 단, "출시 전 결정 필요" 등급이다.**

- 막지 않는 근거: 검색 자체는 동작한다. 주소(시/도·시군구·읍면동·세부주소) · 법원 · 사건번호 ·
  진행상태 · 가격 · 최저가율 · 유찰횟수 · 매각기일 필터는 전부 정상이고, 물건종류를 선택하지
  않은 기본 검색은 **모든 물건을 정확히 반환**한다(총 41건 = 진행 중 전체). 상세·개인화·인증
  경로도 영향 없다. 즉 "쓸 수 없는 서비스"가 아니라 **필터 하나가 대부분 비어 있는 상태**다.
- 그럼에도 출시 전 처리해야 하는 근거: 사용자가 물건종류 체크박스 62/69개를 눌러도 항상
  0건이면 **"데이터가 없는 서비스"로 오인**한다. 검색 UI의 눈에 띄는 위치에 있는 필터다.

→ 승인 규칙(제품/아키텍처 결정, 기존 API 계약 변경)에 해당하므로 **Sprint 50에서는 SKIP**한다.

---

#34

레거시 `/properties`가 **404가 아니라 엉뚱한 물건을 조용히 연다** (실측 확인)

**미해결 (2026-08-11 Sprint 50 실측 확정). 화면 처리 방향이 미결정이라 임의 수정하지 않음.**

**[기존 기록과의 차이]** `docs/frontend.md`는 이 문제를 "엉뚱한 물건이 열리거나 **404가 난다**"로
양자택일처럼 적어 왔다. Sprint 50에서 실제 데이터로 확인한 결과, 현재 상태에서는
**404가 나지 않고 항상 엉뚱한 물건이 열린다**. 조용한 오답이라 404보다 나쁘다.

**[재현 — 2026-08-11 실측]**

`/properties`는 Supabase `properties` 테이블 5행을 카드로 그리고 `/properties/{id}`로 링크한다.
그 id 1~5는 FastAPI `GET /api/v1/item/{id}`에서 **전부 200**이다(존재하지 않는 id가 아니다).

| 목록 카드(Supabase) | 클릭하면 열리는 상세(FastAPI `auction_item`) |
|---|---|
| 강남구 역삼동 아파트 — 서울특별시 강남구 역삼동 123-45 | `2023타경118942` — 서울특별시 **관악구** 난곡로66가길 19 |
| 마포구 합정동 빌라 — 서울특별시 마포구 합정동 67-8 | `2024타경2532` — 서울특별시 **종로구** 평창동 445-1 |
| 수원시 영통구 아파트 — 경기도 수원시 영통구 매탄동 456-7 | `2024타경2662` — 서울특별시 **강남구** 역삼동 609-10 |

지역·물건종류·사건번호가 전부 다른 물건이 열린다. Supabase 쪽 5행은 주소 형태
("123-45", "67-8")로 보아 초기 시드/데모 데이터다.

**[영향 범위]** 현재는 **사용자에게 도달하지 않는다.** Sprint 48에서 `/properties`로 향하는
inbound 링크가 저장소 전체에 **0건**(고아 라우트)임을 확정했고, Sprint 50에서 재확인했다 —
`PrimaryNav`의 검색 링크는 `/`, 로그아웃 복귀도 `/`, 로그인 기본 복귀도 `/`다.
URL을 직접 입력해야만 도달한다. 따라서 **Release Blocking은 아니다.**

다만 이 화면이 살아 있는 한 "언젠가 링크가 하나 생기면 조용히 오답을 보여주는" 상태가 유지된다.

**[왜 고치지 않았나]** 처리 방향 자체가 미결정이다 — ① FastAPI(`auction_item`) 기반으로 전환,
② 화면 폐지(삭제 또는 `/`로 redirect), ③ 현행 유지. 어느 쪽도 제품 결정이고,
`docs/CLAUDE.md`의 "사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다"에 걸린다.
`docs/FRONTEND_MASTER_SPEC.md` §2.3·§16에 이미 SKIP으로 등록돼 있다.

---

#35

`.env`의 UTF-8 BOM 때문에 첫 줄 환경변수가 영원히 읽히지 않음

**미해결 (2026-08-11 Sprint 50 발견). 지금은 무해. `.env` 수정은 승인 필요라 SKIP.**

**[증상]** `.env`의 첫 3바이트가 `EF BB BF`(UTF-8 BOM)라서 `python-dotenv`가 첫 줄의 키를
`SUPABASE_URL`이 아니라 **`\ufeffSUPABASE_URL`** 로 파싱한다. 따라서
`os.getenv("SUPABASE_URL")`은 값이 무엇이든 항상 `None`이다.

```
>>> dotenv_values('.env').keys()
["'\ufeffSUPABASE_URL'", "'SUPABASE_ANON_KEY'", "'SUPABASE_JWT_SECRET'"]
```

**[현재 영향 = 없음]** 세 가지가 겹쳐 우연히 무해한 상태다.

1. `.env`의 `SUPABASE_URL`은 **값이 비어 있다**(이름만 선언). 읽혀도 쓸 값이 없다
2. `api/auth.py:24`가 `os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")`로
   `.env.local` 폴백을 이미 갖고 있다 — 런타임 실측 결과 JWKS URL은 정상적으로
   `https://<project>.supabase.co/auth/v1/.well-known/jwks.json`으로 만들어진다
3. `SUPABASE_ANON_KEY`(둘째 줄)는 BOM 영향을 받지 않고, 애초에 백엔드 어디서도 읽지 않는다
   (`grep` 결과 참조 0건)

즉 **인증은 정상 동작한다**(`test_auth_jwt.py` 23검사 PASS, 실제 로그인 세션으로
`is_favorited`·즐겨찾기·최근조회 전부 동작 확인).

**[왜 그래도 기록하는가 — 잠재 함정]** 문제가 드러나는 시점은 **누군가 `.env` 첫 줄에 실제
값을 채워 넣을 때**다. 값을 정확히 넣어도 코드가 읽지 못해 "분명히 설정했는데 안 먹는다"가
된다. `.env` 첫 줄에 오는 키가 무엇이든 이 함정에 걸리므로, 나중에 변수 순서를 바꾸거나
새 변수를 맨 위에 추가할 때도 재발한다. 이 저장소는 과거에 `SUPABASE_JWT_SECRET` 이름 부재로
인증이 통째로 막혀 여러 Sprint를 소모한 이력이 있어(`docs/BUGS.md` #27 계열) 같은 부류의
"설정은 했는데 코드가 못 읽는" 사고를 미리 막아둘 가치가 있다.

**[확인 / 해결]**

- 확인: `python -c "print(open('.env','rb').read()[:3])"` → `b'\xef\xbb\xbf'`이면 BOM 있음
- 해결: `.env`를 **BOM 없는 UTF-8**로 다시 저장한다(값은 그대로, 3바이트만 제거).
  메모장으로 편집했다면 "UTF-8" 대신 "UTF-8(BOM 없음)"으로 저장하면 된다
- **`docs/CLAUDE.md`가 `.env` 수정을 승인 대상으로 못박고 있어 이번 Sprint에서는 손대지 않았다.**

**[Release Blocking 아님]** 현재 동작에 영향이 없고, 운영 배포 시 `.env`를 새로 작성하는
과정에서 자연히 해소될 수 있다. 다만 배포 체크리스트에 넣어두는 것을 권한다.

### #33 해결 (2026-08-11 Sprint 51)

**상태: 해결.** 도달 불가 행 **745 → 0**.

**[전수 조사 결과 — 데이터는 깨끗했다]**

`auction_item.property_type` 전수 조사(1,870행):

- 고유 원본값 **18종**, 콤마로 분해하면 고유 토큰 **15개**
  (다세대 376 / 근린시설 366 / 오피스텔 304 / 기타 259 / 전답 244 / 상가 220 / 아파트 201 /
  임야 179 / 연립주택 133 / 빌라 130 / 대지 103 / 단독주택 85 / 다가구주택 76 / 자동차 13 / 중기 9)
- **NULL·빈 문자열 0건, 앞뒤 공백 0건, 내부 공백 0건**
- 레거시 `auction` 테이블과 `auction_item`의 분포가 **완전히 동일** → `migrate_execute.py`가
  값을 변형하지 않음을 확인
- 크롤러 출처 확인: `crawler/court_crawler.py:59`가 `basic.get("물건종류")`를 **원문 그대로** 저장.
  정규화 단계 없음(`normalizer.py`는 이 필드를 통과만 시킨다)

즉 **정규화 실패도 표기 흔들림도 아니었다.** 데이터는 법원 원문 그대로 일관되게 저장돼 있었다.

**[정확한 실패 메커니즘 — LIKE 방향]**

매칭은 `property_type LIKE '%<입력>%'`인데 UI 값이 DB 토큰보다 **더 길다**:

```
'%다세대주택%'   vs  DB '다세대'    -> 패턴이 값보다 길어 절대 매치 불가
'%근린생활시설%'  vs  DB '근린시설'   -> 동일
'%오피스텔(주거)%' vs  DB '오피스텔'   -> 동일
```

반대로 UI 값이 DB 토큰과 같거나(아파트/연립주택/임야/대지/기타…) 더 짧으면(전·답 → `전답`)
지금도 정상 동작했다. 그래서 69개 중 정확히 9개만 살아 있었던 것이다.

**[수정] `api/v1/search.py`에 어휘 별칭 7개 (순수 가산)**

```
다세대주택 -> 다세대        근린생활시설 -> 근린시설      근린상가 -> 상가
오피스텔(주거) -> 오피스텔   오피스텔(상업) -> 오피스텔
자동차관련 -> 자동차        기타중기 -> 중기
```

`_property_type_patterns()`가 **원본을 항상 먼저** 넣고 별칭을 뒤에 덧붙여 OR로 확장한다.
따라서 기존에 매치되던 행은 하나도 빠지지 않는다(**가산성**). 응답 구조·파라미터명·정렬·
페이지네이션 전부 무변경이라 `docs/CLAUDE.md`의 "기존 API 유지" 원칙을 지킨다.

**임의 확장을 하지 않은 부분**(제품 의미 훼손 방지):

- **개별 차종(승용차/승합차/버스/화물차/기타차량/덤프트럭)은 매핑하지 않았다.** DB에는 차종
  구분 없이 `자동차` 하나뿐이라, 매핑하면 "승용차"를 고른 사용자에게 화물차가 나온다.
  차종 구분은 데이터가 생겨야 가능하다
- DB에 대응 토큰이 없는 UI 항목(도시형생활주택/기숙사/공장/창고시설/선박/광업권 등 53개)은
  별칭 없이 **0건을 유지**한다. 그건 버그가 아니라 "해당 물건이 아직 없다"는 사실이다
- 복합값(`상가,오피스텔,근린시설`)은 LIKE 부분일치로 자연히 잡힌다 — 새 규칙이 아니라
  `연립주택`이 `'연립주택,다세대,빌라'`를 잡던 **기존 동작과 완전히 같은 방식**이다

**[검증 — 실제 데이터]**

| 항목 | 수정 전 | 수정 후 |
|---|---|---|
| 다세대주택 | 0건 | **376건** |
| 근린생활시설 | 0건 | **366건** |
| 오피스텔(주거) / (상업) | 0건 | **304건** |
| 근린상가 | 0건 | **220건** |
| 자동차관련 | 0건 | **13건** |
| 기타중기 | 0건 | **9건** |
| **이름으로 도달 불가한 행** | **745 / 1,870** | **0 / 1,870** |
| 결과가 나오는 UI 항목(전체 데이터) | 9 / 69 | **16 / 69** |

가산성 실측: 기존에 동작하던 9개 항목(기타 259 / 전 244 / 답 244 / 아파트 201 / 임야 179 /
연립주택 133 / 대지 103 / 단독주택 85 / 다가구주택 76) **전부 건수 불변**.
다중 선택 합집합 유지(임야 179 + 다세대주택 376 → 555). 필터 미지정 전체 1,870 불변.

**브라우저 실동작**: `?property_type=다세대주택` → 총 376건, 결과 카드의 물건종류가
`다세대` / `연립주택,다세대,빌라`로 정확. 물건정보 아코디언을 열면 체크박스 "다세대주택"이
URL에서 그대로 복원된다(UI 어휘는 Tank Auction 전수 복사 그대로 유지 — §12.2 무위반).

**[회귀 테스트]** `test_api_regression.py`에 §2-B 신설 (469 → **490검사**).

변이 테스트 4종 전부 검출 확인:

| 변이 | 결과 |
|---|---|
| 별칭 표 통째로 비우기(수정 전 상태) | **28검사 실패** |
| 별칭 1개만 제거(다세대주택) | **4검사 실패** |
| 확장에서 원본 제거(가산성 파괴) | **7검사 실패** |
| 과확장(승용차/화물차 → 자동차) | **2검사 실패** |

작성 중 **테스트 자체의 결함을 발견·수정**했다: 처음에는 기대값을
`PROPERTY_TYPE_ALIASES.items()`에서 끌어와 루프를 돌렸는데, 표를 비우면 루프가 0회 돌아
**아무것도 단언하지 않고 전부 통과**했다(검증 대상을 기대값의 출처로 삼은 자기참조 결함).
기대 목록을 테스트가 직접 들고 있도록 바꾸고, 구현 표는 "이 목록을 덮는가"로만 검사한다.

**[남은 항목]** DB 토큰 `빌라`에 대응하는 UI 항목은 없지만, `빌라`가 등장하는 유일한 값
`'연립주택,다세대,빌라'`(130행)는 `연립주택`·`다세대주택` 양쪽으로 이미 도달 가능해 실질 손실이 없다.
UI 트리에 "빌라" 항목을 추가할지는 Tank Auction 어휘 유지 원칙(§12.2)과 얽힌 제품 판단이라
그대로 둔다(도달 가능성에는 영향 없음).

### #34 해결 (2026-08-11 Sprint 51)

**상태: 해결.** `/properties`를 검색 첫 화면(`/`)으로 영구 이동시켰다.

**[판단 근거]** 세 가지가 겹쳐 "유지"가 선택지가 아니었다.

1. **조용한 오답**: 404가 아니라 항상 엉뚱한 물건이 열렸다(실측 재확인 —
   "강남구 역삼동 아파트" 카드 → "관악구 난곡로66가길 2층202호" 상세)
2. **아키텍처 규칙 위반**: `docs/CLAUDE.md`가 "경매 데이터는 항상 Python API 경유,
   Supabase에서 직접 조회하지 않는다"를 못박고 있는데, 저장소에서 이를 어기는 **유일한 화면**이었다
3. **데이터 성격**: Supabase `properties` 5행은 주소가 "…123-45", "…67-8" 형태인
   프로토타입 시드다. 크롤러 데이터(SQLite 1,870행)와 무관하다

**[수정]**

- `src/app/properties/page.tsx` — Supabase 조회/렌더 대신 `redirect('/')`
- `src/app/properties/SearchFilters.tsx` — 이 페이지가 유일한 사용처였으므로 함께 제거
  (자체 `SIDO_LIST`/`SIGUNGU_MAP`/`PRICE_OPTIONS`를 갖고 `/search`의 `SearchForm`과
  완전히 다른 지역·가격 데이터를 쓰던 중복 구현)

**[영향 없음을 확인한 것]**

- `/properties/[id]`(상세)·`/properties/recent`(최근조회)는 **하위 경로라 영향 없음** —
  브라우저 실측으로 둘 다 정상 동작 확인
- `src/proxy.ts`의 `PROTECTED_PREFIXES`에 `/properties`가 그대로 있어 **로그인 게이트 유지**.
  비로그인은 `/login`으로, 로그인 상태는 `/`로 간다(둘 다 실측)
- 저장소 전체 inbound 링크 0건이라 사용자 동선 변화 없음

**[되돌리는 법]** 두 파일 모두 git 추적 중이므로
`git show <Sprint 51 이전 커밋>:src/app/properties/page.tsx`(및 `SearchFilters.tsx`)로 복원 가능.
단 복원해도 id 채번 불일치는 그대로이므로 FastAPI 기반으로 다시 작성해야 한다.

**[회귀 테스트]** `tests/frontend-contract.test.mjs`에 3검사 추가 —
`/properties`가 자체 화면을 렌더하지 않는가 / 하위 경로가 여전히 게이트되고 redirect 경로를
잃지 않는가 / 도달 불가 중복 코드 `src/login/`이 되살아나지 않았는가.

---

#36

`property_type` 토큰을 대량으로 보내면 서버가 500을 반환

해결 (2026-08-11, Sprint 51)

**[증상]** `GET /api/v1/search?property_type=<콤마로 2,000개>` 요청 시 **500 Internal Server
Error**. 클라이언트 입력만으로 서버 오류를 만들 수 있는 상태였다.

**[원인]** `property_type`은 콤마로 몇 개든 받아 토큰 수만큼 `LIKE ?` 절을 만든다. 개수 제한이
없어 SQLite의 표현식/변수 한계를 넘기면 쿼리 자체가 실패했다. 실측: 500개까지는 정상(30ms),
2,000개에서 500 발생.

**[Sprint 51 별칭 도입과의 관계]** 무관한 **기존 결함**이다. 별칭 확장은 고정된 소수(최대 7개)만
더하므로 한계에 영향을 주지 않는다. #33 작업 중 DoS 내성을 점검하다 발견했다.

**[수정] `api/v1/search.py`** — `MAX_PROPERTY_TYPES = 100` 상한을 두고 초과 시 400 + 사유.
같은 파일의 `sort_by`/`sort_order` 거부와 동일한 관례를 따른다. UI(`PropertyTypeTree`)가 낼 수
있는 최대가 69개라 정상 사용에는 여유가 있다.

**[검증]** 69개(UI 최대) 200 / 100개(상한) 200 / 101개 400 / 2,000개 **400**(기존 500) /
10,000개 400. 정상 검색 건수 전부 불변. 회귀 5검사 추가, 상한 무력화 변이로 검출 확인.

---

#37

DB 백업 스냅숏 9개(약 42MB)가 git에 커밋돼 있음 — 저장소 비대

**부분 해결 (2026-08-11 Sprint 51). 향후 증가는 차단, 기존 9개 정리는 사용자 결정 필요.**

**[발견]** Sprint 51에서 마이그레이션 017 적용 전 백업을 만들다, 그 파일이 `git status`에
**untracked로 뜨는 것**을 보고 조사했다. `.gitignore`의 `*.db`는
`auction.db.backup_20260728_103355`처럼 **확장자가 뒤에 오지 않는** 이름을 잡지 못한다.
그 결과 마이그레이션 때마다 만든 백업이 그대로 커밋돼 왔다.

```
git ls-files | grep auction.db.backup   ->  9개
디스크 합계                              ->  약 42MB
```

**[개인정보 노출 여부 — 확인 결과 없음]** 추적 중인 9개 전부를 열어 개인 테이블
(favorites / payments / subscriptions / recent_items / search_presets / registry_requests)의
행을 세어 봤다.

- 7개: 개인 테이블 행 **0건**
- 2개(`..._before_auction_unique_20260807_095423`, `..._before_court_code_20260806_173734`):
  `recent_items` 10행씩 — **user_id가 전부 `qa-*` 합성 테스트 사용자**
  (`qa-admin…`, `qa-race-001`, `qa-link-001` …)

**실사용자 데이터는 하나도 들어 있지 않다.** 즉 이것은 **저장소 용량 문제이지 보안 사고가 아니다.**
(Sprint 51에서 새로 만든 백업에는 테스트 중 생긴 실사용자 행 13개가 있지만, 아래 규칙으로
**추적되지 않는다** — 디스크에만 안전 사본으로 남는다.)

**[수정] `.gitignore`에 `*.db.backup*` / `*.db.bak` 추가**

새로 만들어지는 백업은 커밋되지 않는다(신규 백업이 실제로 무시되는 것 확인).
`storage/` 소스 추적 규칙과 충돌하지 않음도 함께 확인했다.

**[남은 것 — 사용자 결정]** **이미 추적 중인 9개는 `.gitignore`로 빠지지 않는다**(git의 정상
동작이다 — 규칙 자체는 `--no-index`로 확인하면 9개 모두에 매치된다). 정리하려면 둘 중 하나가
필요하고, 둘 다 커밋/이력 변경을 수반해 **Sprint 51 범위(Commit 금지) 밖**이다.

1. `git rm --cached auction.db.backup*` → 추적만 해제(디스크 파일 유지). 커밋 1회 필요.
   **이력에는 42MB가 그대로 남는다**(clone 용량은 안 줄어든다)
2. `git filter-repo` 등으로 이력에서 제거 → clone 용량이 실제로 줄지만 **이력 재작성**이라
   협업자가 있으면 재클론이 필요하다

권장: 협업자가 없다면 지금 2번이 깔끔하고, 확실하지 않으면 1번으로 증가만 멈춰도 충분하다.

---

#38

준비만 되고 한 번도 실행되지 않던 결제 경로 — 환불 / Webhook 미연결

해결 (2026-08-11, Sprint 52)

**[증상]** 결제 도메인의 절반이 "코드는 있는데 도달할 수 없는" 상태였다. Sprint 27~28에
인프라를 미리 만들어 두고 KG 실연동을 기다리는 동안, **호출부가 없어 실행된 적이 없는 코드**가
쌓여 있었다(2026-08-11 전수 확인):

| 준비된 것 | 호출부 |
|---|---|
| `state_machines.PAYMENT_TRANSITIONS`의 PAID → PARTIAL_REFUND/REFUNDED | **없음** (테스트만) |
| `PaymentProvider.cancel_payment()` (MockProvider는 REFUNDED 반환) | **없음** |
| `PaymentProvider.handle_webhook()` | **없음** |
| `payment_webhooks` 테이블 + `record_webhook()`/`mark_webhook_processed()` | **없음** |
| `payment_logs`의 `EVENT_CANCEL` / `EVENT_WEBHOOK` | **없음** |
| `ErrorCode.PAY_NOT_FOUND` / `PAY_INVALID_TRANSITION` | **없음** |

즉 **환불할 방법도, PG 노티를 받을 방법도 없었다.** KG 실연동과 무관하게(Mock으로도)
만들 수 있는 내부 로직인데 미뤄져 있던 것이다.

**[수정] 두 경로 신설 — 실제 PG 호출은 없다(MockProvider)**

1. `POST /api/v1/admin/payments/{payment_id}/refund` — **SUPER_ADMIN 전용**
   - 전액/부분 환불, 부분 환불 반복 가능
   - 누적 환불액은 **스키마 변경 없이** `payment_logs`의 CANCEL 이벤트 합계로 계산한다
     (payments에 컬럼을 더하면 원장과 어긋날 수 있는 두 번째 진실이 생긴다)
   - 상태머신 관문 통과 필수 → FAILED/CANCELLED/EXPIRED 결제는 400
   - 잔여 초과·0원·음수 거부, 이미 전액 환불이면 **멱등**(`already_refunded`, 오류 아님)
   - `BEGIN IMMEDIATE` + 조건부 UPDATE rowcount 검사로 동시 환불 방어
   - provider가 `NotImplementedError`면(kginicis 선택 시) **상태를 바꾸지 않고** 실패 로그만 남긴다 —
     PG에서 환불되지 않았는데 DB만 REFUNDED가 되는 것이 최악이기 때문
   - `audit_logs`에 전후 상태·금액·사유 기록

2. `POST /api/v1/payments/webhook/{provider}` — **사용자 인증 없음**(PG가 호출)
   - 그래서 **서명 검증이 유일한 방어선**이다. `verify_webhook_signature()`를 provider
     인터페이스에 신설하고 **기본 구현을 항상 False(fail-closed)** 로 뒀다 —
     검증 방법을 모르는 provider가 조용히 통과하지 않도록
   - `MockProvider`는 `PAYMENT_WEBHOOK_SECRET` 기반 HMAC-SHA256 + 상수시간 비교.
     **시크릿 미설정이면 모든 요청 401** (기본 배포 상태에서 Webhook으로 상태 변경 불가)
   - 서명은 **payload 파싱보다 먼저** 검증한다
   - `event_id` UNIQUE로 멱등 — 재전송은 아무것도 다시 적용하지 않고 200(재전송 중단 유도)
   - 검증 실패도 `payment_webhooks`에 FAILED로 **기록**한다(공격 탐지용)
   - 상태머신이 막는 전이·모르는 거래·알 수 없는 event_type은 무시하고 200

**[함께 고친 것]** `MockProvider.handle_webhook()`이 event_type과 무관하게 **항상 SUCCESS**를
돌려주고 있었다. 그대로 수신 엔드포인트를 붙였다면 `PAYMENT_FAILED` 노티를 받고도 결제를
성공으로 바꾸는 결함이 됐다 — event_type을 실제로 해석하도록 고쳤다(알 수 없는 값은 무시).

**[검증]** 회귀 `test_api_regression.py` §29(환불)·§30(Webhook) 신설.
변이 5종 전부 검출: 서명 검증 무력화(5실패) / 상태머신 관문 제거(1) / 멱등성 제거(1) /
권한 SUPER_ADMIN→ADMIN 완화(1) / 환불 상한 제거(1).

---

#39

`audit_logs`에 QA 잔여 792행 누적 — cleanup이 감사 테이블을 정리하지 않았음

해결 (2026-08-11, Sprint 52)

**[증상]** `audit_logs`에 **792행**이 쌓여 있었고, 전부 **대상 레코드가 존재하지 않는
dangling 행**이었다(PAYMENT 5 / REGISTRY_REQUEST 212 / SUBSCRIPTION 66 / REGISTRY_CREDIT 509).
운영자가 감사 로그를 조회하면 테스트 흔적만 보이는 상태였다.

**[원인]** `test_api_regression.py:cleanup()`이 `user_id LIKE 'qa-reg-%'`로 지우는데,
`audit_logs`와 `payment_webhooks`에는 **`user_id` 컬럼이 없다.** 그래서 2026-08-07부터
매 실행마다 감사 행만 남았다. 특히 `REGISTRY_CREDIT` 감사는 `target_id`가 user_id가 아니라
`registry_credits.id`라(admin.py:377) user_id 기반 정리로는 애초에 잡히지 않았다.

**[수정]**
- `cleanup()`이 **부모 행을 지우기 전에** 대상 id를 캡처해 정확히 그 감사 행만 삭제한다
  (PAYMENT / REGISTRY_REQUEST / SUBSCRIPTION / REGISTRY_CREDIT 4종 + `payment_webhooks`)
- 검증 체크의 허점도 함께 고쳤다 — 원래 "지금 존재하는 qa 결제의 감사 행이 있는가"로 물어서
  **부모를 이미 지운 뒤라 항상 0(공허하게 참)** 이었다. 캡처한 id로 확인하도록 바꾸고,
  "dangling 감사 행 0건" 검사를 추가했다
- 기존 792행은 **대상이 존재하지 않는 행만** 선별해 1회 정리했다(백업 후 실행,
  `integrity_check ok` / FK 위반 0 확인). 실제 운영 감사 행은 대상 레코드를 가리키므로
  이 조건에 걸리지 않는다. `ADMIN_API_KEY`가 `.env`에 없어 실운영 Admin 호출 자체가
  불가능했던 점도 792행 전부가 QA 산물임을 뒷받침한다

**[결과]** 회귀 실행 후 `audit_logs` 0행 / `payment_webhooks` 0행 / `payment_logs` 0행 —
테스트가 스스로 완전히 정리한다.

---

#40

`test_checkpoint_atomicity.py` 간헐적 실패 — 테스트가 OneDrive 동기화 폴더에 쓰고 있었음

해결 (2026-08-11, Sprint 52)

**[증상]** 15종 회귀를 순차 실행할 때 `test_checkpoint_atomicity.py`가 **간헐적으로** 실패했다.

```
TypeError: 'NoneType' object is not subscriptable
  cm_after_crash.get("COURT_C")["last_case_no"]
```

바로 앞 단언의 실측값을 보면 원인이 드러난다 — 파일 내용이 `'{}'`였다.
즉 직전의 `cm.save("COURT_C", ...)`가 **파일에 반영되기 전에 읽혔다.**

**[중요 — 제품 결함이 아니다]** `storage/checkpoint.py`의 원자적 쓰기(임시파일 + `os.replace()`)는
정상이다. 단독 실행은 5회 연속 통과했고, 아래 수정 후 **15종 전체 순차 실행 3회 연속 통과**했다.

**[원인]** 테스트가 QA 파일을 **저장소 안 `logs/`** 에 만들고 있었다
(`QA_PATH = "logs/qa-checkpoint-<uuid>.json"`). 이 저장소는 **OneDrive 동기화 폴더**
(`C:\Users\jhj12\OneDrive\Desktop\dojoonpass`) 안에 있어서, OneDrive가 방금 만들어진 파일을
실시간으로 스캔·동기화한다. 그 상태에서 `os.replace()` 직후 곧바로 읽으면 간헐적으로
**교체 이전 내용**이 보였다. 다른 테스트들이 같은 디렉터리에 I/O를 하는 순차 실행에서
확률이 올라가 재현됐다(단독 실행에서는 거의 나지 않아 원인 파악이 늦어지기 쉬운 형태다).

같은 세션에서 `npm run build`도 `.next` 삭제 시 `EPERM: operation not permitted, unlink`로
두 번 실패했다 — **동일한 OneDrive 파일 잠금 계열 현상**이다.

**[수정]** 두 테스트의 QA 파일 위치를 **시스템 임시 디렉터리**(`tempfile.mkdtemp()`)로 옮겼다.

- `test_checkpoint_atomicity.py` (재현된 것)
- `test_validation_log_integrity.py` (같은 `logs/` 패턴 + append 직후 바이트 되읽기 구조라
  동일한 노출이 있어 **선제 적용**)

두 테스트 모두 검증 대상은 **순수 로직**(원자적 쓰기 / append 무결성)이지 저장소의 `logs/`
디렉터리가 아니다. 동기화 폴더를 벗어나면 무관한 실패 요인이 사라진다.
**제품 코드는 그대로 `logs/`를 쓴다 — 테스트 경로만 바꿨다.** 임시 디렉터리는
`shutil.rmtree`로 정리하고 "temp dir removed" 검사로 확인한다.

**[교훈]** 저장소가 클라우드 동기화 폴더 안에 있으면 파일시스템 테스트에 **제품과 무관한
실패 요인**이 섞인다. 파일 I/O를 검증하는 테스트는 동기화 대상 밖에서 돌려야 한다.

---

#41

Webhook 수신 경로에 운영 도구가 없어 실패한 노티를 되살릴 방법이 없었음

해결 (2026-08-11, Sprint 53)

**[증상]** Sprint 52에서 Webhook 수신 경로를 만들었지만, `payment_webhooks`에 쌓이기만 하고
**운영자가 볼 방법도 다시 처리할 방법도 없었다.** `row_to_webhook()`도 호출부 0건이었다.

이게 실제로 문제가 되는 상황은 흔하다 — **PG 노티가 우리 `payments` row보다 먼저 도착**하면
"해당 거래의 결제 내역을 찾을 수 없습니다"로 IGNORED 되는데, 되살릴 경로가 없으면 결제 상태가
영구히 어긋난 채 남는다.

**[수정] 운영 엔드포인트 3개 (실제 PG 호출 없음)**

- `GET /admin/payments/webhooks` (ADMIN) — 상태/provider/결제/서명여부 필터 + 페이지네이션.
  각 행에 `reprocessable` / `reprocess_blocked_reason`을 함께 실어 **왜 안 되는지**까지 알려준다
- `GET /admin/payments/webhooks/{id}` (ADMIN) — 원문 payload + 실패 사유
- `POST /admin/payments/webhooks/{id}/reprocess` (**SUPER_ADMIN**) — 결제 상태를 바꿀 수 있으므로
  환불·구독 변경과 같은 등급

**재처리 가능 판정**(`webhook_reprocess_block_reason()`)은 기존 상태 의미에서 도출했고
목록/재처리가 **같은 함수**를 쓴다 — "목록에는 가능하다고 떴는데 누르면 거부"가 구조적으로 불가능하다.

| 상태 | 재처리 | 근거 |
|---|---|---|
| RECEIVED | 가능 | 처리 도중 중단된 것 |
| IGNORED | 가능 | 사유 중 일부는 시간이 지나면 해소된다(결제가 나중에 생김) |
| PROCESSED | 불가 | 이미 반영됨 |
| FAILED | 불가 | 신뢰한 적 없는 payload |
| `signature_verified=0` | **상태 무관 불가** | 미검증을 운영자 손으로 적용하면 서명 검증이 무의미해진다 |

**안전 장치**: 상태 변경은 수신 경로와 **같은** `_apply_webhook_event()`가 하므로 상태머신 관문을
그대로 통과한다(재처리 전용 우회로 없음). 성공하면 PROCESSED가 되어 **두 번째 재처리는 자동 차단**.
`BEGIN IMMEDIATE`로 동시 재처리 방어, `audit_logs` 기록.

**[부수 수정]** 결제에 연결되지 못한 노티의 감사 대상을 `AuditTargetType.PAYMENT_WEBHOOK`으로
분리했다 — 처음엔 `target_id="webhook:234"`처럼 PAYMENT에 욱여넣었다가 **존재하지 않는 결제를
가리키는 dangling 감사 행**으로 검출됐다.

**[검증]** 회귀 §32 신설. 변이 4종 검출: 서명 가드 제거 / PROCESSED 재처리 허용 /
권한 SUPER_ADMIN→ADMIN 완화 / 상태머신 우회.

---

#42

Webhook 수신이 **서명 없는 익명 요청마다 DB 행을 생성** — 저장소 증폭(DoS) 통로

해결 (2026-08-11, Sprint 53)

**[증상·재현]** `POST /api/v1/payments/webhook/{provider}`는 **사용자 인증이 없는 공개 경로**인데,
서명 검증 실패도 "공격 탐지용"으로 `payment_webhooks`에 한 행씩 기록하고 있었다.
익명 요청 하나당 행 하나가 **무제한으로** 늘어난다.

```
서명 없는 요청 5회  ->  payment_webhooks 5행 증가 (실측)
```

성능 감사 중 `payment_webhooks`에 10행이 쌓여 있는 것을 이상하게 여겨 추적하다 발견했다
(전부 `event_id=NULL`, `signature_verified=0`인 테스트/probe 요청의 잔재였다).
인터넷에 노출되면 그대로 저장소 증폭 통로가 된다.

**[함께 발견한 oracle]** 같은 코드에서 `if is_duplicate: return 200`이 서명 검사보다 **먼저**
있었다. 그래서 서명이 없어도 **이미 존재하는 event_id**만 맞히면 200을 받았다 —
익명 공격자가 응답 코드로 "그 event_id가 존재하는가"를 알아낼 수 있었다(존재 200 / 없음 401).
변이 테스트 중 이전 실행이 남긴 event_id로 재현됐다.

**[수정]** 서명 검증을 **가장 먼저** 수행한다 — 파싱보다도, DB 쓰기보다도 앞이다.
검증되지 않은 요청은 **저장하지 않고** 경고 로그만 남기고 401로 거절한다.

- 탐지 정보는 로그가 맞는 자리다 — **로그는 회전(rotate)되지만 DB는 계속 쌓인다**
- 중복 판정 자체가 검증 통과 후에만 일어나므로 event_id oracle도 **구조적으로** 사라진다
- 저장되는 행은 이제 항상 `signature_verified=1`이다

**[검증]** 익명 요청 20회 → `payment_webhooks` 증가 **0행**(실측).
회귀에 "검증 실패 요청은 DB에 저장되지 않는다" / "익명 요청 5회가 행을 만들지 않는다" /
"미검증 요청은 행을 남기지 않는다(저장소 증폭 차단)" 추가.
서명 가드는 미검증 행을 직접 만들어 **격리 검증**한다 — 지금은 그런 행이 생기지 않지만,
다른 경로가 만들 가능성에 대비한 방어를 한 겹에만 의존하지 않기 위해서다.

---

#43

`test_api_regression.py`의 실패 출력이 cp949 콘솔에서 크래시 — 회귀가 "FAIL"이 아니라 "중단"으로 보임

해결 (2026-08-11, Sprint 53)

**[증상]** 변이 테스트로 보안 회귀를 넣었더니 `FAIL 0건 + 스위트 중단`이 나왔다.
실제로는 검출된 것인데 **회귀의 성격을 오판하기 쉬운 형태**였다.

```
UnicodeEncodeError: 'cp949' codec can't encode character '\u2014' (em-dash)
```

**[원인]** 이 파일 상단의 "출력은 ASCII만 사용한다" 규칙은 **테스트가 직접 쓰는 문자열**에만
적용된다. 실패 시 출력하는 `detail`에는 **제품 코드가 만든 문자열**이 그대로 실리는데,
거기 em-dash(—)가 있으면 Windows cp949 콘솔에서 인코딩 예외가 나고 남은 검사가 통째로 취소된다.
(Sprint 33이 `test_normalizer.py`에서 고친 것과 같은 부류가 다른 경로로 재발.)

**[수정]** 개별 문자열을 다듬는 대신 **출력 함수 한 곳**(`_safe_out()`)에서 막는다 —
콘솔 인코딩으로 표현 불가한 문자를 치환한다. 앞으로 어떤 제품 문자열이 들어와도 재발하지 않는다.

**[검증]** 같은 변이를 다시 넣으니 **크래시 없이 6건의 깔끔한 FAIL**로 검출됐다.

---

#44

권리분석 **신뢰도가 뒤집혀 있었다** — 근거가 가장 빈약한 물건이 가장 높은 신뢰도로 표시됨

해결 (2026-08-11, Sprint 54)

**[증상]** 상세 화면에서 이 두 줄이 **나란히** 떠 있었다.

```
신뢰도   HIGH
경고     [MISSING_SPEC] 매각물건명세서에서 확인 가능한 임차인 상세정보가 없습니다.
```

**[원인]** `computeConfidence()`가 "충돌이 없으면 HIGH"였다. 그런데 `detectConflicts()`는
정보원이 하나뿐이면 비교를 **시도조차 못 하고** 즉시 빈 배열을 돌려준다.

```ts
if (!statusView || !specView) return conflicts   // <- 대조 불가인데 "충돌 없음"과 구분되지 않음
```

즉 **"대조해 봤더니 일치"**와 **"대조할 상대가 없음"**이 같은 값(`[]`)으로 뭉개졌고,
후자가 최고 등급을 받았다. 정보가 적을수록 신뢰도가 올라가는 구조였다.

**[영향 범위 — 실측 2026-08-11]**

```
권리 정보원이 하나라도 있는 물건      180건
  STATUS만 (명세서 없음)              63건  <- 전부 HIGH로 표시되고 있었음
  SPEC만   (현황조사서 없음)          18건  <- 전부 HIGH로 표시되고 있었음
  STATUS + SPEC (대조 가능)           99건
                                    ------
  잘못된 HIGH                         81건 (45%)
```

**[수정]** 대조 가능 여부를 등급 계산에 포함한다. 등급 체계는 새로 만들지 않고 기존 3단계의
의미를 명확히 했다.

- `LOW` = 정보원끼리 **정면으로 어긋남** (기존)
- `MEDIUM` = **확정할 수 없음** — 집계 차이(기존) 또는 **대조할 상대가 없음**(추가)
- `HIGH` = **둘 이상의 정보원이 서로 일치** (기존 의미를 지키도록 조건 명시)

반박된 것(LOW)과 확인되지 않은 것(MEDIUM)은 다르므로 단일 정보원을 LOW로 낮추지는 않았다.

재발 방지를 위해 판정 조건을 `canCrossCheck()` **한 함수**로 뽑아 `detectConflicts()`의 가드와
`computeConfidence()`의 입력이 같은 곳을 보게 했다. 두 조건이 갈라지는 순간 같은 버그가
그대로 돌아오기 때문이다. 정보원이 둘 다 있어도 비교값(임차인 수)이 NULL이면 대조 불가로 본다.

**[검증]** `rightsAnalysis.ts`에는 그때까지 **테스트가 하나도 없었다**(순수 로직인데도).
`tests/rights-analysis.test.mjs` 신설 — 15건. 특히 "신뢰도 HIGH와 정보원 누락 경고는
동시에 나올 수 없다"를 계약으로 고정했다. 변이 5종 전부 검출(5/5 KILLED).

브라우저 실측:

```
id=54  (STATUS만)          HIGH -> MEDIUM   경고 MISSING_SPEC 과 일관됨
id=142 (STATUS 1 = SPEC 1) HIGH             대조 성공, 일치
id=111 (STATUS 0 vs SPEC 4) LOW             DIRECT_CONFLICT
```

---

#45

"정보원 SPEC 미확보"가 **명세서 임차인 표 바로 위에** 표시된다

**해결 (2026-08-11, Sprint 55)** — 원인은 UX가 아니라 데이터였다. `document_status`가
수집 완료를 반영하지 못하고 있었을 뿐이다(#50). `mark_queue_done()`이 같은 트랜잭션에서
`document_status`를 갱신하도록 고치고, 과거 어긋남 574행을 디스크 실물 기준으로 보정한 뒤
물건 111은 "SPEC ✓ 확보" + 문서 3종 "수집완료"로 정상 표시된다(브라우저 실측).
아래는 Sprint 54 발견 당시의 기록이다.

~~미해결~~ (2026-08-11, Sprint 54 발견)

**[증상]** id=111 상세 화면:

```
정보원    STATUS ✓ 확보
          SPEC   미확보
...
임차인 상세 (4명)          <- 명세서에서 파싱된 임차인이 4명 표시됨
   곽나연 / 김국래 / 디에스 홈푸드 / 이두상
```

"미확보"라고 써 놓고 바로 아래에서 그 자료를 보여준다.

**[원인]** 한 화면에서 `정보원`이라는 같은 이름으로 **서로 다른 두 사실**을 말하고 있다.

- `sourceStatus[SPEC].available` <- `specDocumentAvailable`, 즉 **원본 PDF 파일의 존재 여부**
  (`GET/HEAD /api/v1/item/{id}/documents/SPEC`)
- `specView` / `sources` <- **파싱된 `tenant_rights` 행의 존재 여부**

현재 문서 수집이 멈춰 있어(#46) PDF는 전부 "수집중"인데 과거에 파싱된 임차인 행은 남아 있다.
그래서 두 사실이 정반대로 갈렸고, 화면은 둘을 구분하지 않는다.

**[왜 이번에 안 고쳤나]** 어느 쪽을 "정보원"으로 부를지, 아니면 "원본 문서"와 "분석 자료"를
두 줄로 나눠 보여줄지는 **화면 설계 결정**이다. 이번 Sprint 지침이 "화면 디자인이나 UX 정책을
임의로 결정하지 않는다"이므로 사실만 기록한다. 신뢰도 계산(#44)은 `specView`(파싱 데이터)
기준으로 일관되게 동작하므로 등급 자체는 영향받지 않는다.

---

#46

일일 크롤이 **8일간 중단** — 배치가 사라진 인터프리터를 가리켰고, 실패가 어디에도 남지 않았다

부분 해결 (2026-08-11, Sprint 54) — **Release Blocking**

**[증상]** 검색 결과가 곧 0건이 된다.

```
crawl_date 최신          2026-08-01  (오늘 2026-08-11)
auction_date >= 오늘      41건  (08-11에 27건, 08-12에 14건)
  -> 2026-08-13부터 검색 결과 0건
document_status          COLLECTING 5,593 / READY 14 / FAILED 3
document_queue           pending 2,703 / done 591
doc_raw / parsed_document  0 / 0
```

**[원인 — 네 겹이 겹쳤다]**

1. **디스크 full (일시적)** — `logs/daily_run.log` 마지막 기록 2026-08-02 06:02:49
   `[Errno 28] No space left on device`, "오류 발생: 59 곳", "총 저장 건수: 0 건".
   지금은 859.2 GB 여유 — 이 원인은 이미 사라졌다.
2. **인터프리터 소멸** — 배치 3종이 `C:\ProgramData\Anaconda3\python.exe`를 하드코딩했는데
   그 Anaconda가 제거됐다. 실행 즉시 실패하고 **로그 한 줄도 남기지 않는다**
   (리다이렉트 대상 명령 자체가 실행되지 않으므로).
3. **의존성 기록 부재** — 저장소에 `requirements.txt`도 `pyproject.toml`도 **없었다**.
   현재 PATH의 Python 3.12.10에는 `selenium` / `pandas` / `pdfplumber` /
   `webdriver-manager`가 전부 없다. 경로를 고쳐도 크롤러는 여전히 못 돈다.
4. **스케줄 등록 소멸** — 등록된 Windows 예약 작업 248개를 전수 조회했지만 이 저장소를
   가리키는 것이 **하나도 없다**(`LawAuctionDailyCrawl` / `PDF우선순위갱신` 모두 부재).

**[이번에 고친 것 — 저장소 안에서 할 수 있는 것]**

- 배치 3종의 인터프리터 해석을 교체했다: 기존 Anaconda 경로가 있으면 그대로 쓰고(환경 무변경),
  없으면 `where python`으로 폴백하고, **둘 다 없으면 로그에 남기고 exit 1**.
  마지막 항목이 핵심이다 — Sprint 13이 없앤 "실패 은폐 구조"가 인터프리터 단계에서 재발했고,
  그래서 8일 동안 아무도 몰랐다.
- `requirements.txt` 신설. 목록은 추측이 아니라 **소스 153개 `.py`의 import를 전수 파싱**해
  도출했다. 지금 설치돼 있어 **실측 가능한 버전만** 고정했고, 사라진 환경의 버전은
  확인할 방법이 없어 고정하지 않았다(추측한 핀은 검증된 것처럼 보이는 거짓 정보가 된다).
- `test_schema_hygiene.py`에 "requirements.txt ↔ 소스 import 일치" 검사를 추가했다.
  목록을 사람이 관리하면 다음 import가 추가되는 순간 또 어긋나므로 **매번 소스에서 재도출해
  비교**한다. 변이 4종 전부 검출.

**[남은 것 — 저장소 밖의 운영 조치]**

이 셋은 코드 수정으로 끝나지 않는다.

1. `pip install -r requirements.txt` — 사용자 환경 변경이라 임의로 실행하지 않았다.
2. **예약 작업 재등록** — 실행하면 courtauction.go.kr에 대한 실제 정기 수집이 시작된다.
   운영 결정이라 등록하지 않았다.
3. **59/60 법원 오류의 원인 규명** — 마지막 실행이 디스크 full 상태였으므로 그것만이
   원인인지, 사이트 구조 변경이 겹쳤는지는 **실제로 한 번 돌려 봐야** 안다.
   크롤러 실행은 외부 네트워크 접근이고 장시간 작업이라 회귀 스위트에서 제외돼 있다.

**[검증]** 배치 3종의 헤더를 그대로 떼어내 dry-run(본체는 echo로 치환)으로 파싱과 해석을 실증:
`RESOLVED=C:\Users\jhj12\AppData\Local\Programs\Python\Python312\python.exe`, `OK 3.12.10`,
exit 0. 인터프리터가 없는 경우도 exit 1과 로그 기록을 확인했다.

---

#47

크롤이 **59/60 실패 + 저장 0건인데 "성공"으로 끝났다** — errorlevel 검사가 발동할 수 없는 구조

해결 (2026-08-11, Sprint 55)

**[증상]** `logs/daily_run.log`의 마지막 실행(2026-08-02) 기록.

```
[수집 완료 요약]
  총 수집 법원: 60 곳
  기일 없어 스킵: 1 곳
  오류 발생: 59 곳
  총 저장 건수: 0 건
=====================================
Finished at 2026-08-02  6:02:49.45      <- 성공 경로로 종료
```

Sprint 54에서 배치의 인터프리터 경로를 고쳤지만, **그 아래에 한 겹이 더 있었다.**

**[원인]** `mvp_scraper.main()`이 `-> None`이었고 `if __name__ == "__main__": main()`이었다.
Python은 예외가 밖으로 나가지 않는 한 **항상 0으로 종료**한다. 그런데 법원별 실패는
`try/except`로 잡아 `failed` 리스트에 세기만 하고 print로 흘려보냈다.

즉 `run_daily.bat`의 `if errorlevel 1`은 **구조적으로 발동할 수 없는 검사**였다.
Sprint 13이 "실패 은폐 구조를 없앴다"고 기록한 것은 배치 레벨이었고, 그 아래 Python
레벨에서 같은 구조가 그대로 살아 있었다.

`doc_worker.py`도 같았다 — 큐의 모든 항목이 실패해도 종료 코드는 0이었다.
게다가 `run_doc_worker.bat` / `run_priority_refresh.bat`에는 **errorlevel 검사도,
성공/실패 마커도 아예 없었다**(Sprint 13이 `run_daily.bat`만 고쳤기 때문). 그래서
`doc_run.log`만 보고는 "돌았는데 할 일이 없었다"와 "아예 실행되지 않았다"를 구분할 수 없었다.

실제로 전체 로그(타임스탬프 25,791개)에 `[SUCCESS]` / `[FAILED]` 마커가 **0회**다.

**[수정]**

- `models/crawl_outcome.py` 신설 — `CrawlOutcome` / `DocWorkerOutcome`.
  `mvp_scraper.py`는 import 한 줄로 selenium을 끌어오므로, 성패 판정을 거기 두면
  **selenium이 있는 환경에서만 테스트 가능**하다. 판정은 순수 산술이라 분리했다.
- 판정 기준은 새 정책을 만들지 않고 **명백한 것만** 잡는다:
  전 법원 실패 / 수집 0건 / DB 저장 0건. 부분 실패는 경고만 남기고 성공으로 둔다 —
  임계값을 임의로 정하면 그 자체가 새 정책이고, 멀쩡한 실행이 매일 실패로 보고되면
  경보가 무시당해 결국 같은 자리로 돌아온다.
- `main() -> int` + `sys.exit(main())`. `doc_worker`는 "시도했는데 전건 실패"만 1.
- 배치 2종에 errorlevel 검사와 `[SUCCESS]`/`[FAILED]` 마커 추가.
- 수집 결과가 비어 `enqueue_documents`를 건너뛸 때 경고 로그 추가(예전에는 무언).

**[검증]** `test_crawl_exit_code.py` 신설 — 2026-08-02 실행을 그대로 재현하는 케이스 포함.
사유 문자열이 "수집 0건"인지 "저장 0건"인지까지 고정한다(손봐야 할 곳이 다르므로).
배치는 **각 실패 분기가 자기 블록 안에서** `[FAILED]`를 남기는지 블록 단위로 검사한다 —
파일 어딘가에 마커가 한 번이라도 있으면 통과시키는 검사는 실제로 변이를 놓쳤다.
변이 14종 전부 검출(14/14).

---

#48

`document_queue`의 UNIQUE에 `item_no`가 빠져 **물건의 38%가 큐에 들어간 적이 없다**

해결 (2026-08-11, Sprint 55) — Migration 018

**[증상]** `enqueue_documents()`의 docstring은 이렇게 적혀 있었다.

```
UNIQUE(court_code, case_no, item_no, doc_type) 이므로 이미 대기 중인 항목은
INSERT OR IGNORE로 조용히 무시된다 (중복 enqueue 방지)
```

실제 스키마는 `UNIQUE(court_code, case_no, doc_type)` — **item_no가 없다.**
`item_no`는 나중에 ALTER TABLE로 붙은 컬럼이고 제약은 갱신되지 않았다.

문서는 물건 단위다(`get_doc_button_id(doc_type, item_no)`가 item_no로 버튼을 고른다).
그런데 한 사건에 물건이 여러 개면 **두 번째부터 `INSERT OR IGNORE`에 걸려 사라졌다.**

**[실측 2026-08-11]**

```
물건이 2개 이상인 사건                    190건 (그 안의 물건 680개)
자기 item_no로 큐에 없는 물건             716 / 1,870  (38%)
(court_code, case_no)당 item_no 종류 수   전부 1건       <- 충돌의 직접 증거
```

권리분석 데이터가 비어 있는 원인 중 하나다 — 큐에 없으니 수집도 파싱도 될 수 없었다.

**[수정]** Migration 018로 UNIQUE에 `item_no` 포함. 제약이 **넓어지는** 방향이라
기존 3,480행은 전부 새 제약도 만족한다. 행을 지우지 않고 id까지 보존해 이관했다
(적용 후 3,480행 / 최대 id 17637 그대로).

빠져 있던 물건은 다음 `enqueue_documents()` 실행 때 채워진다. 기일이 남아 있는 대상은
현재 10건이고, 나머지는 기일이 지나 1차 방어선이 제외하는 것이 정상이다.

**[함께 고친 것]** `storage/migrations/run_migrations.py`가 `sys.path`에 저장소 루트 대신
`.../storage`를 넣고 있었다(dirname 한 단계 부족). 문서가 안내하는
`python -m storage.migrations.run_migrations`에서는 cwd 덕에 우연히 동작했지만,
`python storage/migrations/run_migrations.py`로 직접 부르면 ModuleNotFoundError로 죽었다.

**[검증]** `test_document_queue.py` 신설. 스키마를 테스트에 베껴 쓰지 않고 **018 마이그레이션
파일에서 읽어** 쓴다 — 손으로 베낀 스키마는 진짜 스키마가 바뀌어도 통과하고, 그것이 바로
이 버그가 오래 살아남은 방식이다(주석은 item_no가 있다고 했고 테이블에는 없었다).

---

#49

`parsed_document` / `rights_analysis_history` — 아무도 읽지도 쓰지도 않는 테이블

기록 (2026-08-11, Sprint 55 발견)

```
parsed_document            0행   읽기 0곳  쓰기 0곳   (migrate_v4_1.py가 CREATE만 함)
rights_analysis_history    0행   읽기 0곳  쓰기 0곳
```

전 저장소의 `.py`/`.sql`/`.ts(x)`를 훑어도 INSERT/UPDATE/SELECT가 하나도 없다.
삭제하면 부트스트랩 테이블 수(25개)가 바뀌고 여러 문서의 실측 기록과 어긋나므로,
이번에는 사실만 기록한다. #50과 함께 파이프라인 재설계 시 정리 대상.

**2026-08-17 Sprint 148 정정 — 테이블 수는 이제 26개다.** Sprint 144가 migration 020으로
`auction_image`를 추가했다(사진 파이프라인). 위 "25개"는 2026-08-11 시점의 값이다.
`test_bootstrap.py`는 이 수를 **하드코딩하지 않고 실측해 출력**하므로 테스트는 깨지지
않았다 — 그래서 이 드리프트가 조용히 남아 있었다.

★ 두 표(`parsed_document`/`rights_analysis_history`)가 **여전히 죽어 있다는 것은
2026-08-17에 재확인했다**: 각각 0행, 프로덕션 코드의 INSERT/UPDATE/SELECT 0곳
(`migrate_v4_1.py`의 CREATE와 테스트/문서 참조만 존재). 삭제는 여전히 승인 영역이다.

---

#50

수집이 끝난 문서가 화면에는 계속 "수집중" — 문서 상태가 **두 곳에 따로** 기록되고 있었다

해결 (2026-08-11, Sprint 55)

**[증상]** 물건 111(2024타경1636)은 `documents/강릉지원/2024타경1636/1/spec.pdf`가
디스크에 있고 임차인 4명이 파싱돼 화면에 표시되는데, 같은 화면이

```
정보원    SPEC 미확보
관련 문서  매각물건명세서 수집중
```

라고 말하고 있었다. (BUGS #45로 별도 기록했던 "SPEC 미확보" 모순의 실제 원인이다.)

**[원인]** 파이프라인이 두 동강 나 있었다.

```
스케줄러가 실행하는 것   mvp_scraper -> migrate_execute / doc_worker / refresh_priority
                        -> document_queue, auction.has_*_pdf, documents/*.pdf 까지

어떤 배치도 부르지 않는 것  collect_documents.py  (document_status / doc_raw 를 쓰는 유일한 코드)
                          analyze_docs.py / load_rights_data.py / load_spec_data.py
```

화면이 읽는 것은 `document_status`인데, 그것을 갱신하는 코드가 스케줄러 경로 **밖**에 있었다.
`mark_queue_done()`은 `auction.has_*_pdf`만 세우고 `document_status`는 건드리지 않았다.

**[실측 2026-08-11 (수정 전)]**

```
auction.has_spec_pdf=1                      197건
그중 document_status != READY               192건 (97%)
디스크에 파일이 있는 (법원,사건,물건) 조합    200개
document_status READY                        14개
```

**[수정]**

- `_set_document_status()` 신설. `mark_queue_done()`이 **같은 트랜잭션에서**
  `document_status`를 READY로 함께 갱신한다. 두 기록이 갈라질 여지를 없앤다.
- `mark_queue_failed()`는 **재시도가 소진된 최종 실패만** FAILED로 반영한다.
  중간 재시도까지 FAILED로 바꾸면 다음 시도에 성공할 문서가 잠깐 "실패"로 보인다.
- 큐(`spec`)와 화면(`SPEC`)의 표기 차이는 변환만 한다 — 표기를 통일하면 이미 쌓인
  5,610행과 어긋난다. 규격 외 표기는 기록을 거부하고 경고를 남긴다.
- 과거에 쌓인 어긋남은 `repair_document_status.py`로 **1회 보정**했다(574행).
  판단 근거는 DB 플래그가 아니라 **디스크 실물**이고, 경로 계산은 `api/v1/documents.py`가
  서빙에 쓰는 규칙(경로 탈출 검사 포함)을 그대로 쓴다 — 규칙이 갈라지면
  "화면은 수집완료인데 뷰어는 404"가 된다.
  배치에 넣지 않는다: 위 수정으로 앞으로는 자동으로 맞으므로 1회성이 맞다.

**[검증]** `test_document_status_sync.py` 신설. 임시 DB에 최소 스키마를 만들고
`storage.database`의 **실제 함수**를 호출한다(JOIN 경로까지 검증). 변이 7종 전부 검출.

보정 전 API HEAD로 대상 표본이 실제로 서빙되는지 먼저 확인했다(대상 6건 전부 200,
대조군 2건 404). 보정 후 브라우저 실측:

```
물건 111  정보원 SPEC ✓ 확보 / 관련 문서 3종 "수집완료"   (이전: 미확보 / 수집중)
```

**[남은 것]** `doc_raw`(0행) / `parsed_document`(0행) / `tenant_rights` / `rights_summary`를
채우는 스크립트들은 여전히 스케줄러 경로 밖이다. 이것을 배치에 넣는 것은 운영 스케줄
변경이라 이번 Sprint 범위 밖이다(SKIP). 권리분석 커버리지가 8.7%에 머무는 근본 원인이다.

---

#51

실제 법원 사이트에 접속하는 스크립트가 `test_*.py` 이름을 달고 있어 회귀 스윕에 휩쓸린다

해결 (2026-08-11, Sprint 55)

**[증상]** `test_db.py` / `test_docs.py` / `test_docs2.py`는 assert가 **0개**이고
PASS/FAIL도 없으며, 실제 `courtauction.go.kr`에 접속해 크롤링한다(둘은 `input()`으로
사람 입력까지 기다려 비대화형 실행에서는 멈추거나 EOFError로 죽는다).

"회귀 대상 아님"은 `docs/CLAUDE.md` 등 **6개 문서**에 적혀 있었다. 그런데 그것은 규약일 뿐
아무것도 막지 못했다 — 2026-08-11 감사 중 `test_*.py`를 전부 실행하는 스윕이 두 번 돌았고,
**selenium이 설치돼 있지 않아서 우연히** 실제 접속이 일어나지 않았을 뿐이다.

**[수정]** 세 파일에 실행 가드를 넣었다. `ALLOW_LIVE_CRAWL=1`이 없으면
`[SKIPPED]` 한 줄을 남기고 즉시 종료한다. 가드는 **selenium import보다 앞**에 둬서
selenium이 없는 환경에서도 깔끔히 끝난다.

파일명을 바꾸지 않은 이유: 이 이름이 문서 6곳에 참조돼 있어 rename하면 문서가 한꺼번에
낡는다. 이름은 두고 **실행만** 막는 편이 부작용이 작다.

**[효과]** 회귀 스윕의 분류가 "환경부재(selenium 없음)"에서 **"설계상 건너뜀"**으로 바뀌었다 —
실패와 구분되고, selenium을 설치해도 여전히 안전하다.

**[검증]** `test_crawl_exit_code.py` §7이 세 파일의 가드 존재와 **가드가 import보다 앞에
있는지**를 고정한다. 진짜 회귀 테스트에는 이 가드가 없어야 한다는 것도 함께 검사한다
(있으면 회귀가 조용히 건너뛰어진다).

---

#52

구독 만료 파싱 실패가 **조용히** 폴백 — 깨진 구독이 무기한 유효해진다

해결 (2026-08-11, Sprint 56)

**[증상]** `expires_at`이 해석 불가능한 값이면 두 곳이 안전한 방향으로 폴백한다.

```python
# api/v1/state_machines.py:_parse()
except (TypeError, ValueError):
    return None          # 호출부가 상태를 바꾸지 않는다

# api/v1/subscriptions.py:renew()
except (TypeError, ValueError):
    pass                 # 지금부터 다시 센다
```

**폴백 방향 자체는 옳다.** 파싱 실패를 '만료'로 해석하면 정상 구독자가 끊긴다.
문제는 **로그가 한 줄도 없었다**는 것이다. `_parse()`가 None을 돌려주면
`effective_status()`는 그 구독을 영원히 만료로 넘기지 않는다 — 즉 **무기한 유효한 구독**이
되는데, 그 사실을 알아낼 방법이 없었다. 갱신 쪽은 반대로 사용자가 남은 기간을 잃는다.

안전한 방향으로 실패하는 것과 실패를 숨기는 것은 다르다.

**[수정]** 두 곳 모두 `logger.warning`으로 값과 결과를 남긴다. "만료 판정을 보류했다",
"잔여 기간을 잇지 못하고 지금부터 다시 센다"까지 문장에 담아 무엇이 일어났는지 드러낸다.

**[검증]** `test_state_machines.py` §8 신설. 로그 핸들러를 붙여 **경고가 실제로 나오는지**
확인한다. 테스트를 쓰다 제 가정 두 개가 반증됐다.

- `''`는 부패가 아니라 **부재**다. `effective_status()`가 `_parse` 전에 단락시킨다
- `'20260811'`은 Python 3.11+ `fromisoformat`이 **정상 파싱**한다(기본 ISO 형식)

둘을 부패로 취급하면 테스트가 실제 동작이 아니라 짐작을 검사하게 된다. 부재(`None`/`''`)와
날짜만 있는 값에는 **경고를 남기지 않는 것**까지 함께 고정했다 — 과잉 경고는 진짜 경고를 묻는다.

---

#53

레이스 테스트가 **레이스를 재현하지 못했다** — 동시성 가드가 사라져도 통과

해결 (2026-08-11, Sprint 56)

**[증상]** `test_race_conditions.py`는 4가지 동시성 방어를 검증한다고 기록돼 있었다.
실제로 가드를 제거하는 변이를 넣어 보니 절반이 **살아남았다**.

```
BEGIN IMMEDIATE 제거 (등기부 무료한도)        -> SURVIVED
조건부 UPDATE 제거 (관리자 전이 TOCTOU)       -> SURVIVED
BEGIN IMMEDIATE 제거 (결제 주문/환불)         -> KILLED  (이쪽은 정상 동작)
```

**[원인]** 스레드를 만들고 **순서대로 `start()`만** 했다. 생성/시작 오버헤드 때문에 요청이
어긋나 실제로는 겹치지 않았고, 직렬 실행과 다를 바 없었다. 관리자 전이 쪽은 더 분명하다 —
진 쪽이 항상 나중에 SELECT를 해서 `ALLOWED_TRANSITIONS`에서 400으로 걸렸고,
검증하려던 **조건부 UPDATE에는 도달조차 하지 못했다.**

**[수정]**

- **무료한도 레이스**: `threading.Barrier`로 진입 시점을 맞추고 경합 폭을 10 -> 24로 올렸다.
  변이 검출률 **2/3 -> 4/4**.
- **관리자 TOCTOU**: Barrier를 넣었지만 2스레드 3/4에 그쳤고, 스레드를 6으로 늘리자
  오히려 **1/5로 나빠졌다**(Barrier 해제가 계단식이라 첫 스레드가 커밋을 마친 뒤에야
  나머지가 SELECT에 도달한다). 이 창(SELECT -> UPDATE, 수 마이크로초)은 실제 스레드로
  안정 재현이 불가능하다고 판단하고, **결정적 구조 검사**를 추가했다 —
  UPDATE 세 갈래가 전부 `WHERE id=? AND status=?`인지, `rowcount==0`이면 409로 거부하고
  롤백하는지. 확률적 테스트는 2스레드로 되돌려 함께 둔다.
  변이 4종(각 분기의 조건부 WHERE 제거 / rowcount 검사 제거 / 409->200) **4/4 결정적 검출**.

**[교훈]** "레이스 테스트가 있다"는 것과 "레이스를 재현한다"는 것은 다르다.
동시성 테스트는 **가드를 제거해 보기 전까지는 통과 여부에 의미가 없다.**

---

#54

미결제 등기부 신청을 관리자가 완료 처리할 수 없다는 **금전 가드에 회귀가 없었다**

해결 (2026-08-11, Sprint 56) — 테스트 공백

**[발견]** `PAYMENT_REQUIRED`는 "아직 돈을 안 냈다"는 뜻이고, `COMPLETED`가 되면
다운로드 게이트(`status == COMPLETED`)가 열려 등기부를 공짜로 받게 된다.
`ALLOWED_TRANSITIONS`에 `PAYMENT_REQUIRED` 키가 없어 실제로는 막혀 있지만,
**그 사실을 고정하는 회귀가 없었다** — 키를 하나 추가하는 것만으로 조용히 뚫린다.

**[추가한 검사]** PAYMENT_REQUIRED에서 COMPLETED/PROCESSING/FAILED로 가는 전이가 전부 400,
거부 후 상태·`doc_url`·`completed_at`이 전부 불변, 그 상태로 다운로드도 차단.

**[함께 강화한 약한 단언]** 기존 "미완료 다운로드" 검사는 `success == False`만 봤다.
다운로드의 COMPLETED 검사를 통째로 없애는 변이를 넣었더니 `doc_url`이 NULL이라
**다른 오류로 떨어져 그대로 통과했다.** 이제 `error == "REGISTRY_NOT_COMPLETED"`와
메시지가 실제 상태를 밝히는지까지 고정한다 — **어느 가드가 막았는지**를 봐야 가드 제거가 잡힌다.

변이 5종(전이 허용 / 전이 검사 제거 / 다운로드 상태검사 제거 / 무료판정 뒤집기 /
멱등 처리 제거) **5/5 검출**.

---

#55

`doc_raw`도 라이브 파이프라인이 쓰지 않는다 — `parsed_document`와 같은 부류

기록 (2026-08-11, Sprint 56 발견)

문서를 저장하는 코드가 **두 벌**이고, 스케줄러가 부르는 쪽이 기록을 덜 남긴다.

| | 파일 저장 | 해시 | `doc_raw` | `document_status` |
|---|---|---|---|---|
| `crawler/doc_crawler.py` (doc_worker가 호출, **라이브**) | O | O | **X** | Sprint 55부터 `mark_queue_done`이 대신 |
| `collect_documents.py` (어떤 배치도 부르지 않음) | O | O | O | O |

`doc_raw`(storage_path / file_hash / file_size / page_count)를 채우는 것은 고아 스크립트뿐이라
**0행**이다. 라이브 경로는 해시를 계산해 `document_version_log`에만 쓰고 나머지는 버린다.

라이브 경로가 `doc_raw`를 쓰게 하려면 `page_count`가 필요한데 pdfplumber가 없고(미설치),
무엇보다 **어느 스크립트가 적재를 소유할지**가 정해져야 한다(roadmap 16-A/16-B).
운영 스케줄 결정이라 이번 Sprint 범위 밖이다.

---

#56

`property_type`이 실제 내용과 모순되는 행 — 원인 규명은 실증 필요

기록 (2026-08-11, Sprint 56 발견)

```
id=317    자동차,중기   [집합건물 철근콘크리트구조 45.22㎡]   수원지방법원  crawl 2026-07-07
id=11804  자동차        [토지 목장용지 353㎡]              인천지방법원  crawl 2026-08-01

역방향(내용은 차량인데 분류가 '기타') 3건
id=542 [기타 동력선] / id=1806 [선박 동력선, 동어호] / id=6311 [선박 동력선 혜원5호]
```

`normalizer`는 `property_type`을 가공하지 않고 크롤 값을 그대로 넘긴다. 따라서 원인은
법원 사이트의 원본 분류이거나 크롤 파싱 어긋남인데, **어느 쪽인지는 실제 페이지를 다시
열어 봐야** 안다(외부 네트워크 — SKIP).

고칠 수 없더라도 **늘어나는 것은 막는다.** `test_pipeline_integrity.py` §6이 양방향으로 세고
상한(2건 / 5건)을 둔다. 이 수치가 커지면 크롤러가 계속 잘못 분류하고 있다는 신호다.

---

#57

`auction.db`가 Sprint 51/52/55 완료분을 잃고 이전 시점 상태로 되돌아가 있었다 —
migration_history 3건 미기록 + audit_logs 잔여 698행 + document_status 574행 재역행

해결 (2026-08-11, Sprint 57)

**[발견 경위]** `/goal` 지시에 따라 문서를 그대로 믿지 않고 실제 코드/DB 상태부터
재확인하던 중, 세션 시작 시점 `git status`가 보여준 미추적 파일 3개
(`storage/migrations/016_create_audit_logs.sql`, `017_add_soft_delete_columns.sql`,
`storage/migrate_doc_collect.py`)를 조사하다 발견했다. 이 셋은 `docs/CHANGELOG.md`
Sprint 53 항목이 "제거 완료"로 기록한 것들인데 디스크에 그대로 남아 있었다 — 이 저장소가
반복해서 겪어 온 "`auction.db`/`storage/`가 git 비추적이라 조용히 이전 시점으로
되돌아간다"는 패턴(#18, #23, #28과 동일 부류)이 다시 발생한 것으로 의심해 실측했다.

**[실측 1 — migration_history 드리프트]** `test_schema_hygiene.py`의
"디스크의 모든 .sql이 migration_history에 기록돼 있는가" 검사가 **FAIL**로 나왔다.
실제 `auction.db`의 `migration_history`에는 Sprint 51 이전에 쓰던 옛 파일명
(`016_create_audit_logs.sql`, `017_add_soft_delete_columns.sql`)만 기록돼 있고, Sprint 51이
그 자리를 대체한 현재 추적 파일(`016_create_audit_and_credit_logs.sql`,
`017_create_document_collect_failures.sql`, `018_document_queue_item_no_unique.sql`)은
셋 다 **한 번도 적용된 적이 없었다.** 그 상태로 `run_migrations.py`를 그냥 돌리면
`016_create_audit_and_credit_logs.sql`의 `ALTER TABLE ... ADD COLUMN`이 이미 존재하는
컬럼과 충돌해 `duplicate column name` 에러로 **전체 마이그레이션이 즉시 중단**됨을
사본으로 재현 확인했다(부트스트랩이 아니라 **이미 운영 중인 이 `auction.db` 자체**가
이 상태였다는 점이 #18/#23/#28과 다르다 — 그때는 fresh clone 재현 문제였다).

**[실측 2 — Migration 018이 실제로 반영되지 않고 있었다]** `018_document_queue_item_no_unique.sql`은
`document_queue`의 `UNIQUE(court_code, case_no, doc_type)`에 `item_no`를 넣어 한 사건에
물건이 여럿일 때 두 번째 물건부터 `INSERT OR IGNORE`에 조용히 버려지던 결함(#48)을 고치는
마이그레이션이다. `docs/CURRENT_STATE.md` Sprint 56은 이것을 "완료"로 기록했지만, 실측
결과 **실제 `document_queue` 스키마는 여전히 옛 제약(`UNIQUE(court_code, case_no, doc_type)`)
그대로**였고, 자기 `item_no`로 큐에 없는 물건이 **751/2,012건(37.3%)** — Sprint 55가 처음
발견했을 때의 규모(716/1,870, 38%)와 사실상 동일한 수치로 **재발**해 있었다.

**[실측 3 — audit_logs 잔여 698행]** Sprint 52(#39)가 "정리 완료, 이제 0행"이라 기록한
`audit_logs`의 대상 삭제된(dangling) 행이 **698개** 다시 쌓여 있었다(전부 2026-08-08~
2026-08-10 사이 생성 — 이번 세션 이전의 옛 데이터, 즉 Sprint 52의 정리 작업 자체가 이후
어느 시점엔가 통째로 되돌려진 것이지 새로 쌓인 게 아니다).

**[실측 4 — document_status 574행 재역행]** Sprint 55(#50)가 디스크 실물 기준으로
`document_status`의 COLLECTING→READY 574행을 보정했다고 기록했지만, `repair_document_status.py`
(그 Sprint가 만든 1회성 스크립트, 아직 저장소에 남아 있어 재실행 가능했다)를 다시 돌려보니
**정확히 같은 574건**이 다시 "고쳐야 함" 상태로 잡혔다 — 파일은 디스크에 실제로 존재하는데
DB만 COLLECTING으로 되어 있는, Sprint 55 수정 이전과 동일한 상태였다.

**[판단]** 네 가지 증상 모두 같은 하나의 원인(`auction.db`가 대략 Sprint 50~52 언저리
시점으로 되돌아감)이 서로 다른 각도에서 드러난 것이다. 새 정책 결정이 필요한 사안이
아니라 **이미 완료·승인된 작업이 유실된 것을 재적용**하는 문제라 승인 없이 즉시 복구했다.

**[수정]**
- 실행 전 `auction.db.backup_before_migration_reconcile_20260811_233247` 백업 생성
- `016_create_audit_and_credit_logs.sql`/`017_create_document_collect_failures.sql`을
  문장 단위로 재실행 — 이미 존재하는 테이블/컬럼(`duplicate column name`)은 건너뛰고
  아직 없던 인덱스 9개(`idx_registry_credit_logs_*` 3개, `idx_audit_logs_created_at`/
  `admin`/`action`, `idx_favorites_deleted_at`, `idx_search_presets_deleted_at`)는
  실제로 생성한 뒤 `migration_history`에 두 파일명을 기록
- `run_migrations.py`를 정상 실행해 `018_document_queue_item_no_unique.sql`을 **실제로 적용**
  (행 3,804건 id 보존 재확인, `document_queue` 스키마가
  `UNIQUE(court_code, case_no, item_no, doc_type)`로 전환됨을 확인)
- `db.enqueue_documents()`를 현재 `auction_item` 전량으로 재호출해 새로 열린 제약으로
  큐에 들어갈 수 있게 된 항목을 적재(81건 추가, 나머지는 `auction_date`가 이미 지나
  설계대로 제외됨). 재확인 결과 **매각기일이 남은 물건 중 자기 item_no로 큐에 없는 건
  0건**(만료된 과거 물건 724건은 정책상 큐에 넣지 않는 것이 맞다)
- 대상이 사라진 `audit_logs` 698행 삭제(전부 QA 테스트가 만든 `payments`/`registry_requests`/
  `subscriptions`/`registry_credits` 대상이 이미 지워진 잔재, 실사용자 데이터 아님 확인)
- `repair_document_status.py --apply` 재실행으로 574행을 다시 COLLECTING→READY로 보정
  (판정 근거는 디스크 실물 — Sprint 55와 동일한 스크립트, 동일한 기준)
- 드리프트를 유발한 미추적 중복 파일 3개 삭제: `storage/migrations/016_create_audit_logs.sql`,
  `017_add_soft_delete_columns.sql`(둘 다 Sprint 51에서 이미 대체됐어야 함),
  `storage/migrate_doc_collect.py`(Sprint 53에서 "제거 완료"로 기록됐던 파일 — 코드 참조 0건
  재확인 후 삭제)

**[검증]** `test_schema_hygiene.py`(migration_history 드리프트 검사 포함) 전부 PASS,
`test_api_regression.py`(dangling audit 포함) 전부 PASS, `test_pipeline_integrity.py`
(done↔READY 정합 포함) 전부 PASS, 나머지 Python 회귀 13개 파일 전부 PASS(`test_db.py`는
설계상 SKIP). `npx tsc --noEmit`/`npm run lint`(0건)/`npm run build`(경고 0) 전부 통과.
API 서버 + `npm run dev`를 함께 띄운 상태에서 `npm run test:frontend` 93/93 PASS
(`cancelled: 0`으로 서버가 실제로 응답했음을 확인 — `docs/CURRENT_STATE.md` Sprint 56이
경고한 "cancelled인데 fail 0으로 보이는 함정"을 그대로 점검).

**[재발 방지에 대한 솔직한 평가]** 이 복구는 **증상만 다시 고친 것**이고 `auction.db`가
왜 되돌아갔는지(OneDrive 동기화 충돌 해소, 이전 백업에서의 수동 복원, 다른 세션과의 작업
디렉터리 공유 등)는 이번 조사로 특정하지 못했다. `storage/`가 git 비추적인 것과 별개로
`auction.db` 자체도 처음부터 git 비추적이므로, 같은 일이 다시 벌어져도 git으로는 막을 수
없다 — 유일한 방어선은 `test_schema_hygiene.py`/`test_pipeline_integrity.py`/
`test_api_regression.py`의 dangling 검사처럼 "DB가 스스로의 무결성을 실측 검증하는" 회귀뿐이다.
이번에 그 회귀들이 실제로 문제를 잡아냈다는 점 자체가 그 방어선이 유효함을 보여준다.

---

#58

Admin 구독 상태 변경(`PATCH /admin/subscriptions/{id}`)에 동시성 방어가 전혀 없어, 서로 다른
목표 상태로 동시 요청 시 둘 다 200 성공을 응답하고 진 쪽 요청은 자신이 실제로 반영됐다고
잘못 믿게 됨

해결 (2026-08-12, Sprint 59 — 승인 없이 가능한 버그로 판단해 즉시 수정)

**[발견 경위]** Backend API Contract Audit으로 Admin 41개 엔드포인트를 훑던 중, 등기부 신청
상태 전이(#21)/결제 환불/Webhook 재처리가 전부 `BEGIN IMMEDIATE` + 조건부 UPDATE(`WHERE id=?
AND status=?`) + rowcount 확인 패턴으로 방어돼 있는데, 같은 부류인 구독 상태 변경
(`api/v1/subscriptions.py:change_status()`, `PATCH /admin/subscriptions/{id}`의 유일한
호출부)만 예외임을 코드 대조로 발견했다.

**[재현]** ACTIVE 구독 1건에 PAUSED/CANCELLED로 동시 PATCH 2건을 보내는 실측 재현(5회 반복)
결과 **매번 둘 다 200 성공**을 응답했고, 최종 DB 상태는 나중에 커밋되는 쪽으로 결정됐다 —
어느 쪽이 이길지 예측할 수 없을 뿐 아니라(#16의 정렬 비결정성과 같은 근본 원인은 아니고
순수 TOCTOU), **진 쪽 요청도 200과 함께 자신이 요청한 상태를 응답 body에 그대로 담아
돌려받아** 실제로는 반영되지 않았는데도 성공했다고 믿게 된다. `docs/CLAUDE.md`가 이
엔드포인트를 "과금에 직접 영향을 주므로 SUPER_ADMIN 전용"이라 표기한 것과 정확히 반대로,
가장 방어가 필요한 지점에 방어가 없었다.

**[판단]** 새 정책이 아니라 이 저장소가 이미 세 번(#19 등기부, #20 구독 결제, #21 Admin
등기부 상태전이) 확립한 "확인 후 쓰기" 불변식을 이 경로만 못 지키고 있던 구현 공백이라
승인 없이 수정 가능한 버그로 판단했다.

**[수정] `api/v1/subscriptions.py:change_status()`**
- 함수 진입 직후 `conn.isolation_level = None` + `conn.execute("BEGIN IMMEDIATE")`로 쓰기
  락을 선점(등기부/환불/Webhook 재처리와 동일 패턴)
- 두 UPDATE 분기(CANCELLED/EXPIRED 경로, 그 외 경로) 모두 `WHERE id=? AND status=?`로
  현재 상태를 다시 확인
- `rowcount == 0`이면 롤백 후 신규 `ConcurrentStatusChange` 예외를 던진다
- `api/v1/admin.py:admin_change_subscription_status()`가 이 예외를 잡아 `HTTPException(409)`로
  변환(등기부 #21과 동일한 응답 관례)

**[검증]** 수정 전/후 대조 재현: 수정 후 5/5 전부 **정확히 1건만 200**, 최종 DB 상태가
성공 응답과 항상 일치함을 확인. 기존 `test_api_regression.py`의 순차 테스트(§27, SUPER_ADMIN
권한/전이 규칙/404)는 무변동 PASS(재확인). `test_race_conditions.py`에 신규 시나리오 2개
추가(§9 실스레드 재현, §10 결정적 구조 검사) — `BEGIN IMMEDIATE` 제거/`WHERE status=?` 제거
두 변이 모두 §10(구조 검사)이 결정적으로 검출함을 확인(§9 스레드 재현은 이번에도 두 변이를
놓쳤다 — refund/webhook 재처리 감사에서 이미 확인한 것과 같은 "좁은 창" 한계, 그래서 두
검사를 함께 둔다). 검증 후 소스는 정확히 복구해 최종 diff만 남김.

**[영향 범위]** `change_status()`의 유일한 호출부가 이 엔드포인트뿐이라 다른 경로에는 영향
없음(`sync_expired_status()`/`renew()`는 이 함수를 호출하지 않는 별도 경로 — 각각 "시간
경과에 따른 결정적 자동 전이"와 "결제 성공 시 시스템 갱신"이라 사람이 서로 다른 목표로
경합할 위험이 구조적으로 없어 이번 수정 범위에서 제외했다).

**[회귀]** `test_race_conditions.py` 41 → **49검사**, `test_api_regression.py` 627검사
무변동 PASS. `python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/`npm run build`
전부 통과.

---

#59

만료된 구독을 Admin이 ACTIVE로 되돌려도 만료 시각을 갱신하지 않아, 200 응답 직후 다시
EXPIRED로 조용히 되돌아감(재활성화가 실제로는 항상 실패)

해결 (2026-08-12, Sprint 59 — #58과 같은 감사에서 이어서 발견, 승인 없이 가능한 버그로
판단해 즉시 수정)

**[발견 경위]** #58(구독 상태 변경 동시성 결함) 수정 중 `api/v1/subscriptions.py:change_status()`를
정독하다, 함수 자신의 docstring이 "ACTIVE: 만료된 구독을 되살리는 경우라면 호출부가 새
expires_at을 함께 넘긴다"고 명시하는데 **정작 함수 시그니처에 그 값을 받을 매개변수 자체가
없었다**는 것을 발견했다. 추가로 `renew()`(만료 시각을 올바르게 연장하는 함수)를 저장소
전체에서 호출하는 곳이 **0곳**임도 확인했다 — 준비만 되고 배선이 안 된, 이 저장소에
반복적으로 나타나는 패턴(KG이니시스 스텁, 파이프라인 후반 스크립트와 같은 부류).

**[재현]** EXPIRED 구독(만료 시각이 5일 전)에 Admin PATCH로 `{"status": "ACTIVE"}`만 보내면:
- 응답은 200이고 `status: "ACTIVE"`
- **그러나 같은 응답 안의 `effective_status`가 이미 `"EXPIRED"`, `is_entitled: false`** —
  응답 자체가 자기모순
- 로그에 "구독 자동 만료: id=N ACTIVE -> EXPIRED"가 **같은 요청 처리 중**(응답 body를
  만드는 `row_to_subscription`/lazy sync 계산 과정에서) 즉시 찍힌다
- 뒤이은 `GET /subscriptions/me` 조회에서 DB `status`도 다시 `EXPIRED`로 확인됨

원인은 `change_status()`의 ACTIVE 분기가 `status`/`updated_at`만 갱신하고 `expires_at`은
전혀 건드리지 않아서다 — 상태만 ACTIVE로 바뀌고 만료 시각은 과거 그대로 남으므로, 그 즉시
(혹은 다음 조회에서) `resolve_expected_status()`가 다시 EXPIRED로 판정한다. **CS가 고객
지원 차원에서 구독을 되살려 주려 해도 이 엔드포인트로는 항상 실패한다** — 실패한다는
신호조차 없이(200 응답) 실패한다는 점이 더 나쁘다.

**[판단]** 새 정책을 만드는 대신, 함수 자신의 docstring이 이미 명시한 설계("호출부가 새
expires_at을 넘긴다")를 실제로 배선하는 문제로 좁혔다. 다만 **몇 일을 연장할지는 이 함수가
결정할 수 없다**(요금 정산 정책, `subscriptions` 테이블에 `billing_cycle`도 저장되지
않아 원래 결제 주기를 역산할 방법도 없다) — 그래서 기본값을 추측해 채우는 대신, 그 값이
없을 때는 **명확히 거부**하도록 했다(조용히 성공한 뒤 되돌아가는 것보다 명시적 400이 낫다).

**[수정]**
- `api/v1/subscriptions.py:change_status()` — `new_expires_at: datetime = None` 매개변수
  추가. ACTIVE로 전이할 때 현재 `expires_at`이 이미 지났는데 `new_expires_at`이 없으면
  신규 예외 `ReactivationRequiresNewExpiry`를 던진다(막 잡은 `BEGIN IMMEDIATE` 락은 롤백
  후 해제). `new_expires_at`이 있으면 상태와 만료 시각을 함께 갱신. 아직 만료되지 않은
  경우(PAUSED에서 재개)는 기존과 동일하게 `expires_at`을 건드리지 않는다
- `api/v1/admin.py` — `SubscriptionStatusRequest`에 `expires_at: Optional[str]` 필드 추가
  (ISO 8601 문자열, ACTIVE로 되돌릴 때만 의미가 있다). 파싱 실패는 400,
  `ReactivationRequiresNewExpiry`도 400으로 변환
- `renew()`는 이번에도 배선하지 않았다 — 이 함수는 "기간을 연장"(연장 일수 필요)이고
  Admin 재활성화는 "특정 시각까지"(만료 시각 직접 지정)라 요구사항이 달라, 억지로 재사용하면
  오히려 함수 하나가 두 가지 의미를 갖게 된다

**[검증]** 수정 전/후 대조: 수정 후 (1) `expires_at` 없이 만료 구독 재활성화 시도 → 400,
DB 상태 `EXPIRED` 그대로(수정 전에는 200 + 즉시 자기모순 응답 + 재조회 시 원상복구), (2)
`expires_at` 형식 오류 → 400, (3) `expires_at`을 함께 주면 200 + `effective_status`도
`ACTIVE`로 일치 + DB에 실제로 반영, (4) PAUSED → ACTIVE(재개, 아직 안 지난 만료 시각)는
`expires_at` 없이도 기존과 동일하게 정상 동작(회귀 없음). `test_api_regression.py` §27에
19개 검사 신규(627 → 646검사 — 재활성화 관련 11개 + Sprint 마무리 검증 중 커버리지 공백으로
확인한 ACTIVE→CANCELLED/ACTIVE→EXPIRED 실제 엔드포인트 왕복 8개), `test_race_conditions.py`
§10 구조 검사를 4개 UPDATE 분기 전수로 갱신(49검사 무변동, 검사 내용만 정합화). `BEGIN
IMMEDIATE` 제거·조건부 UPDATE 제거 두 변이 모두 §10이 결정적으로 검출함을 마무리 검증
단계에서 재확인(수정 후 원복, git diff 0).

**[검증 — Type/Lint/Build]** `python -m compileall`/`npx tsc --noEmit`/`npm run lint`(0건)/
`npm run build` 전부 통과.

---

#60

프런트 계약 테스트 "수집일(crawl_date) 정렬이 UI에 노출된다"가 **제품 결함이 아니라
데이터 상태 때문에** 실패 — 정렬 자체는 정상인데 검사 설계가 데이터에 의존하고 있었음

해결 (2026-08-12, Sprint 61 — 테스트 결함. 제품 코드는 변경하지 않았다)

**[발견 경위]** Sprint 61의 품질 게이트로 `npm run test:frontend`를 돌리다 93검사 중
1건이 실패하는 것을 발견했다. Sprint 60 보고서에는 "프런트 계약 93/93 통과"로 기록돼
있었으므로, 그 사이에 **코드가 아니라 데이터가** 바뀌어 실패로 돌아선 경우다.

**[재현·원인]** 실패 메시지는 `crawl_date asc/desc의 결과 순서가 같습니다`였다.
그러나 실측 결과 정렬은 정상 동작한다:

```
GET /api/v1/search?sort_by=crawl_date&sort_order=asc &include_closed=true -> 2026-07-06 부터
GET /api/v1/search?sort_by=crawl_date&sort_order=desc&include_closed=true -> 2026-08-01 부터
```

원인은 **기본 검색 집합의 crawl_date가 전부 같은 값**이 된 것이다. 크롤이 2026-08-01
이후 멈춰 있어(#46), 2026-08-12 기준 아직 기일이 남은 물건은 **14건뿐이고 전부
`crawl_date = 2026-08-01`**이다. 정렬 키가 상수인 집합에서 asc와 desc가 같은 순서
(= `id` tie-break)를 내는 것은 **올바른 동작**이다. 즉 검사가 "정렬이 동작하는가"가 아니라
"오늘 데이터에 crawl_date가 두 종류 이상 있는가"를 검사하고 있었다.

```
auction_item                     1,870건
  auction_date >= 2026-08-12        14건  (전부 2026-08-12, 전부 crawl_date=2026-08-01)
  distinct crawl_date              여러 개 (2026-07-06 ~ 2026-08-01)
```

**[수정]** `tests/frontend-contract.test.mjs` — 검사 대상을 `include_closed=true`가 걸린
집합(1,870건, crawl_date가 실제로 여러 값)으로 바꿨다. 이 집합은 오늘 날짜에 좌우되지
않으므로 시간이 지나도 다시 무효가 되지 않는다. **assertion을 약화하지 않았다** —
`notEqual` 단언은 그대로 두고 검사 대상만 유효한 집합으로 교체했다.

**[중요]** 이 실패는 제품 결함은 아니지만 **#46(크롤 파이프라인 중단)의 2차 증상**이다.
2026-08-12 기준 진행 중 물건이 14건까지 줄었고 전부 오늘이 매각기일이므로,
**2026-08-13부터 기본 검색 결과가 0건이 된다**(Sprint 54가 예측한 시점과 정확히 일치).
운영 조치(selenium 설치, 예약 작업 등록, 크롤 1회 실행)가 없으면 서비스가 빈 화면이 된다.

---

#61

현황조사서(status.html) **내용이 비어 있는 캡처가 "정상 수집"으로 저장**되어, 해당 물건이
영구히 재수집 대상에서 제외됨 (실측 194건 중 33건)

해결 (2026-08-12, Sprint 62 — 원인 수정 + 기존 33건 복구)

**[발견 경위]** `load_rights_data.py`를 실행해 보니 `no_extractable_data`가 33건이었다.
문서 여러 곳이 이를 "미파싱 33건"으로 기록하고 있어 파서 문제로 보였으나, 실제 파일을
열어 보니 **파서가 아니라 파일 자체가 비어 있었다**.

**[재현·판별]** status.html 194건을 전수 대조했다.

```
                     사건번호(YYYY타경NNNNN) 포함   임대차 그리드 행   파일 크기
정상 161건                   161 / 161                  1개 이상      23,526 ~ 351,375 bytes
내용 없음 33건                 0 / 33                     0개          19,253 / 19,268 bytes
```

두 집합이 **완전히 분리**된다(원본 HTML 문자열 기준). 33건은 사건번호·조사일시 필드가
전부 빈 채로 라벨만 있는 골격 페이지다. (초기 가설이던 "검색결과가 없습니다" 문구는
정상 파일 161건에도 전부 들어 있는 **템플릿 문구**라 판별에 쓸 수 없음을 확인했다.)

**[원인]** `crawler/doc_crawler.py:collect_status()`의 대기 조건이 너무 약했다.

```python
WebDriverWait(...).until(lambda d: len((...text or "").strip()) > 0)   # 수정 전
```

주석은 "데이터가 비동기로 채워지는 동안 빈 상태로 읽어가는 타이밍 문제 방지"라고 적혀
있었지만, 오버레이 골격에는 "사건번호"/"조사일시" 같은 **고정 라벨**이 처음부터 들어 있어
이 조건이 데이터 도착 전에 즉시 참이 된다.

치명적인 것은 그 다음이다 — `doc_exists()`는 "파일이 있고 0바이트 초과"만 보므로, 한 번
저장된 빈 파일은 **영구히 재수집에서 제외**된다(BUGS #22/#50과 같은 부류의 함정).
사용자에게는 빈 현황조사서가 계속 보이고 권리분석 데이터도 영원히 채워지지 않는다.

**[수정]**
- `crawler/doc_paths.py`에 `status_overlay_has_data()` 신설(selenium 무의존 순수 함수라
  테스트가 selenium 없이 검증할 수 있다). 판정 기준은 사건번호 표기
- `collect_status()`의 대기 조건을 "텍스트가 있음" → "**실제 사건 데이터가 채워짐**"으로 교체
- **저장 직전 관문 추가** — 대기를 통과했더라도 저장할 HTML에 사건 데이터가 없으면
  저장하지 않고 실패로 반환한다. 빈 캡처를 남기느니 큐에 남겨 재시도하는 편이 옳다
- `repair_empty_status_capture.py` 신설(dry-run 기본, `--apply`) — 기존 33건을 **삭제하지
  않고 격리**(`documents_quarantine/`)한 뒤 `document_status`를 COLLECTING,
  `document_queue`를 pending으로 되돌려 재수집 대상으로 복구. 정상 파일이 0건이면
  판정 기준 자체를 의심해 중단하는 안전장치 포함

**[검증]** 격리 66개 파일 / `document_status` 33행 / `document_queue` 33행 복구,
재실행 시 대상 0건. 변이 4종(판정 항상참 / **원래 버그 형태인 "비어있지 않음"으로 되돌리기** /
저장 관문 제거 / 대기 조건 약화) 전부 검출 — 특히 원래 버그 형태를 재현한 변이를 잡아내므로
이 회귀는 과거 결함을 실제로 검출할 수 있다. `test_doc_storage_atomicity.py` +8검사.

---

#62

근거 문서가 사라져도 권리분석 파생 데이터(`rights_summary` / `tenant_rights`)가 영원히 남음

해결 (2026-08-12, Sprint 62)

**[발견 경위]** `load_rights_data.py`를 실행하니 `적재 완료 161`인데 `rights_summary`는
**162행**이었다. 1행이 설명되지 않았다.

**[원인]** `load_item()`은 근거 파일이 없으면 `DELETE` 이전에 early return 한다. 그래서
한 번 적재된 뒤 근거 문서가 사라지면 파생 행이 **영원히 남는다**. 실측 결과 item_id=540
(춘천지방법원 2024타경2803-1)은 사건 디렉터리 자체가 존재하지 않는데도 rights_summary 1행 +
tenant_rights 4행(STATUS 2 / SPEC 2)이 남아 있었다. 화면은 근거를 확인할 수 없는
"현황조사서 임차인 N명"을 계속 보여준다 — "명시된 내용만 근거로 사용한다"는 이 도메인의
대원칙에 정면으로 어긋난다. `load_spec_data.py`도 **같은 형태의 결함**을 갖고 있었다.

**[수정]** 두 스크립트에 `purge_orphans()` 추가 — 근거 파일이 사라진 물건의 파생 행을 정리한다.

핵심은 **안전장치**다. 근거 파일을 하나도 찾지 못하면(`evidence_found == 0`) 아무것도
지우지 않는다. documents/ 경로 변경·드라이브 미마운트·권한 문제로 전부 "근거 없음"이 되면
**전체 권리분석 데이터가 날아가기** 때문이다. 실제로 안전장치를 끈 변이를 넣으면 162행/281행이
전부 삭제되는 것을 확인했다. 또한 "파일은 있는데 추출 결과가 빈" 경우는 **지우지 않는다** —
파서 회귀로도 같은 증상이 나오므로 파일 부재라는 명확한 근거일 때만 지운다.

**[검증]** 실 DB 사본에서 먼저 검증 후 적용. `rights_summary` 162 → 161(= `loaded` 161과 일치),
`tenant_rights` 523 → 519, 재실행 시 정리 0건(멱등). SPEC 재파싱 결과는 기존 데이터와
**완전히 동일**해(추가 0 / 변경 0) 새로 설치한 pdfplumber로 인한 파싱 드리프트가 없음도 확인했다.
신규 `test_rights_data_load.py`(27검사) + `test_pipeline_integrity.py`에 "파생 데이터에는
근거 문서가 존재한다" 불변식 추가. 변이 7종 전부 검출.

---

#63

`refresh_queue_priority()`가 **검토한 행 수**를 "변경 건수"로 보고해, 매일 밤 배치 로그가
실제로 바뀐 것이 없는 날에도 "재계산 완료: 2,736건"을 남김

해결 (2026-08-12, Sprint 63)

**[발견 경위]** 핵심 모듈의 공개 함수를 AST로 뽑아 테스트가 한 번이라도 언급하는지 대조하다
`calc_priority` / `refresh_queue_priority`가 **검사 0건**임을 발견했다. 매일 01:50에 도는
`run_priority_refresh.bat` -> `refresh_priority.py`의 핵심 로직인데도 그랬다.

**[원인]** UPDATE에 `AND priority!=?`가 걸려 있어 대부분의 행은 실제로 바뀌지 않는데,
카운터는 루프를 돈 횟수를 그대로 셌다.

```python
conn.execute("UPDATE ... WHERE id=? AND priority!=?", ...)
updated += 1        # <- 바뀌었든 아니든 무조건 증가
```

`refresh_priority.py`가 이 값을 "우선순위 재계산 완료: %d건"으로 찍으므로, 운영자는 매일 밤
수천 건이 갱신된다고 믿게 된다. 실제 변경이 0건인 날과 137건인 날이 **로그상 구별되지 않는다** —
BUGS #47(배치가 실패를 성공으로 보고)과 같은 부류의, 로그가 사실이 아닌 것을 말하는 문제다.

**[수정]** `cur.rowcount > 0`인 경우만 세고, 검토/변경을 나눠 로그에 남긴다.
반환값은 **실제 변경 건수**다. 소비처는 `refresh_priority.py`의 로그 한 곳뿐이라
Breaking Change가 아니다.

```
수정 전 로그:  우선순위 재계산: 2736건 검토
수정 후 로그:  우선순위 재계산: 2736건 검토, 137건 변경
```

**[검증]** 실제 배치를 돌려 137건이 실제로 바뀜을 확인했다(크롤 중단으로 기일이 지나면서
p2 22건 + p3 115건이 p1로 승격 — 대기 큐 2,736건 중 2,733건이 이제 최우선이다).
`test_document_queue.py`에 §10~11 신규 17검사(경계값 7종 + 잘못된 입력 4종 + pending 한정 +
멱등성). 변이 4종 전부 검출 — 특히 **수정 전 동작을 그대로 재현한 변이**(`if True:`)를
검출하므로 이 회귀는 과거 결함을 실제로 잡을 수 있다.

---

#64

`collect_documents.py`가 **뷰어가 서빙하지 않는 경로**에 문서를 저장하면서 `document_status`를
READY로 바꿈 — 배치에 편입되는 순간 "화면에는 열람 가능인데 뷰어는 404"가 됨

해결 (2026-08-12, Sprint 66 — 잠재 결함. 아직 실행된 적이 없어 피해는 0건)

**[발견 경위]** Backlog "collect_documents.py 실제 실행 경로 감사"를 수행하며 저장 경로를
뷰어 서빙 경로와 대조했다.

```
collect_documents.py 저장   storage/docs/<doc_type>/<다운로드된 원본 파일명>
api/v1/documents.py 서빙    documents/<법원>/<사건>/<물건>/spec.pdf

-> 디렉터리 구조도, 파일명 규칙도 완전히 다르다
```

`save_doc_raw()`가 저장 직후 `document_status`를 READY로 바꾸므로, 이 스크립트가 손대는
문서마다 상세 화면에는 "열람 가능"으로 뜨지만 뷰어는 404를 낸다. **Sprint 55가 이미 한 번
고친 BUGS #50과 정확히 같은 부류**다.

**왜 중요한가** — 이 스크립트는 지금까지 한 번도 실행된 적이 없어(`storage/docs/` 하위 파일
0개, `doc_raw` 0행) 현재 피해는 없다. 그러나 `docs/roadmap.md` 16-A가 **배치 편입을
Backlog로 올려 둔 대상**이다. 스케줄에 넣는 순간 결함이 즉시 발현된다.

**[동시 발견] STATUS는 이 경로로 성공할 수 없다.** `DOC_BUTTONS`에는 STATUS가 있지만
`download_doc()`은 `.pdf`만 받는다. 현황조사서는 PDF 다운로드가 아니라 오버레이 HTML을
긁어오는 방식(`crawler/doc_crawler.py:collect_status()`)이라 **항상 None이 반환되고
`save_failure()`가 FAILED를 기록**한다. 실패가 아니라 담당 코드가 다른 것뿐인데 FAILED로
남는다.

**[수정]**
- `crawler/doc_paths.py`(selenium/fastapi 무의존)에 `canonical_doc_path()` /
  `CANONICAL_DOC_FILENAME` / `PDF_DOWNLOADABLE_DOC_TYPES` 신설
- `collect_documents.py`에 `finalize_download()` 추가 — 다운로드 파일을 뷰어 경로로
  `os.replace()`(원자적)로 옮긴 뒤 **그 최종 경로**를 `save_doc_raw()`에 넘긴다
- STATUS는 이 경로에서 시도하지 않고 건너뛴다(담당은 doc_worker)

**[검증]** `test_doc_storage_atomicity.py` +14검사 — 뷰어 파일명과 canonical 정의 소스 대조,
canonical 경로가 `documents/` 아래인지, STATUS 제외, 배선 확인(실제로 최종 경로를 넘기는지),
`os.replace` 사용, 그리고 **실제 파일 이동 동작**(옮겨짐/원본 없음/내용 보존/`doc_exists()`가
완료로 인정). 변이 5종 전부 검출 — 그중 2종은 **수정 전 동작을 그대로 재현**한 것이라
이 회귀가 원래 결함을 실제로 잡을 수 있음이 증명됐다.

---

#65

`collect_documents.py`가 **0바이트 다운로드 파일을 "수집 완료(READY)"로 기록** — 화면·뷰어·
재수집 판정 세 곳이 서로 어긋남

해결 (2026-08-12, Sprint 67 — 잠재 결함. 스크립트가 아직 실행된 적이 없어 피해는 0건)

**[발견 경위]** Sprint 67에 `collect_documents.py`의 저장/실패 경로 회귀를 새로 짜면서
0바이트 파일 시나리오를 넣어 봤더니, 현재 구현이 그것을 성공으로 처리하고 있었다.
(Sprint 66은 경로 결함을 고쳤지만 **DB 기록 쪽은 검증하지 않았다** — 그 공백에서 나왔다.)

**[원인]** `save_doc_raw()`가 파일 크기를 보지 않고 `document_status`를 READY로 바꾼다.
그런데 이 저장소에는 "완료"의 기준이 **이미 있다** — `crawler/doc_paths.py:doc_exists()`는
크기가 0보다 커야 완료로 본다. 두 정의가 어긋나 3자 불일치가 생긴다.

```
화면(document_status)   READY        -> 사용자에게 "열람 가능"으로 보인다
뷰어(api/v1/documents)  0바이트 서빙  -> 깨진 문서가 열린다
재수집 판정(doc_exists) False        -> 미완료로 보고 계속 재시도한다
```

Chrome 다운로드가 시작 직후 끊기면 실제로 0바이트 `.pdf`가 남을 수 있다.
BUGS #50 / #61과 같은 부류다 — **"READY인데 실제로는 못 쓰는 파일"**.

**[수정]** `save_doc_raw()`가 `size <= 0`이면 경고 로그를 남기고 `False`를 반환한다.
호출부는 기존 흐름 그대로 `save_failure()`로 이어져 FAILED가 기록된다.
**새 정책을 만든 것이 아니라 이미 있는 완료 기준(`doc_exists`)에 맞춘 것**이다.

**[검증]** 신규 `test_collect_documents.py`(26검사) §6 — 0바이트는 저장 실패 / `doc_raw`
행 미생성 / READY 미전환 / `doc_exists()`와 판정 일치. 변이 5종 전부 검출했고,
그중 2종은 **수정 전 동작을 그대로 재현**한 것이라 이 회귀가 원래 결함을 잡을 수 있음이
증명됐다.

---

#66

검색조건 저장 개수 상한이 **동시 요청에서 뚫린다** — COUNT 확인과 INSERT 사이에 경합

해결 (2026-08-12, Sprint 67)

**[발견 경위]** Concurrency Audit을 이어가며 "확인 후 쓰기(TOCTOU)" 패턴이 남은 곳을
전수 훑다가 발견했다. 이 저장소는 등기부 무료한도(#21)·초과결제·환불·Webhook 재처리·
구독 상태 변경(#58)까지 모든 경합 지점을 `BEGIN IMMEDIATE`나 조건부 UPDATE로 굳혀 왔는데,
**`create_preset()`만 빠져 있었다.**

```python
saved_count = SELECT COUNT(*) FROM search_presets WHERE user_id=?   # 확인
if saved_count >= MAX_PRESETS_PER_USER: 거부
INSERT INTO search_presets ...                                       # 쓰기
```

**[재현]** 상한(100) 직전인 99개 상태에서 12개 요청을 Barrier로 동시에 보냈다.

```
수정 전 : 성공 2건 -> 최종 101개   (상한 초과)
수정 후 : 성공 1건 -> 최종 100개   (3회 반복 전부 동일)
```

저장 개수 상한은 COUNT(집계)로 판정하므로 "row 하나를 조건부로 잠그는" 방식으로는 막을 수
없다 — `api/v1/registry.py:create_registry_request()`가 무료횟수 COUNT에 쓰는 것과 **정확히
같은 상황**이다.

**[영향 범위]** 심각도는 낮다. 상한은 저장 자원 보호용이고 과금·권한과 무관하며, 초과량도
동시 요청 수만큼으로 제한된다(무한 증식 아님). 다만 **서버가 스스로 정한 불변식이 조용히
깨지는 것**이고, 같은 클래스의 결함을 다른 경로에서는 전부 막아 둔 상태라 여기만 남겨 둘
이유가 없다.

**[수정]** 기존 패턴을 그대로 적용했다 — `conn.isolation_level = None` 후
`BEGIN IMMEDIATE`로 COUNT 확인과 INSERT를 원자화하고, 상한 초과면 `ROLLBACK`,
성공하면 `COMMIT`. **새 정책이 아니라 이미 있는 상한을 정확히 집행하는 것**이며
API 계약(응답 형식·에러 코드)은 그대로다.

**[검증]** `test_race_conditions.py`에 2개 시나리오 신규(§12 실스레드 재현 + §13 결정적
구조 검사 — COUNT와 INSERT가 모두 트랜잭션 안에 있는지까지 확인). 변이 2종 전부 검출했고,
그중 `BEGIN IMMEDIATE` 제거 변이는 **수정 전 동작을 그대로 재현**했다(최종 103개).
기존 preset 회귀(생성/삭제/입력검증/상한/정렬)는 전부 무변동 통과.

--------

#67

회귀 게이트의 통과/실패가 **어느 콘솔에서 돌리느냐**에 따라 갈린다 ― 테스트 2종이
UnicodeEncodeError로 죽고, 운영 경고 로그 8종은 조용히 소실된다

해결 (2026-08-13, Sprint 72)

**[발견 경위]** Sprint 72를 시작하며 기준선을 잡으려고 `test_*.py` 전체를 bash에서 돌렸더니
26개 중 2개가 **실패가 아니라 크래시**했다(종료 코드 1).

```
UnicodeEncodeError: 'cp949' codec can't encode character '—'
```

**[원인]** 출력 문자열에 박힌 U+2014 EM DASH다. cp949에 없는 문자인데, 이 저장소의 실행
환경은 cp949가 기본이다.

```
PowerShell(Claude Code)      stdout=utf-8   -> 통과
bash / cmd.exe               stdout=cp949   -> 죽음
run_daily.bat 의 `>> logs\daily_run.log`  리다이렉트된 stdout은 locale 인코딩(cp949) -> 죽음
```

같은 코드가 실행 위치에 따라 결과가 달라지는 것 자체가 게이트로서 결함이다.

**[이것은 3번째 재발이다 ― 그 사실이 핵심이다]** 같은 부류를 이 저장소는 이미 두 번 고쳤다.

```
Sprint 33   test_normalizer.py     해당 파일의 출력을 다듬음
Sprint 53   test_api_regression.py `_safe_out()` 도입 (BUGS #43)
Sprint 72   ← 지금
```

`test_subscription_policy.py`의 docstring도 "콘솔 인코딩(cp949) 문제를 피하려고 출력은
ASCII만 사용한다"고 적어 두었다. 즉 **문제는 세 번 인지됐고 세 번 다 그 파일에서만 고쳐졌다.**
저장소 전체를 보는 장치가 없었기 때문에 다른 파일에서 계속 되살아났다.

Sprint 53의 `_safe_out()`은 옳은 수정이지만 **런타임 치환**이고 `test_api_regression.py`
한 파일에만 있다. 이번 수정은 **소스 리터럴을 전 저장소에서 정적으로 막는** 쪽이라 서로를
대체하지 않고 보완한다 ― `_safe_out()`은 제품 코드가 만든 문자열(정적으로 알 수 없다)을,
새 가드는 우리가 직접 쓴 문자열(치환 전에 애초에 들어오지 못하게)을 담당한다.
이번에 고친 11곳 중 **7곳이 제품 코드(api/)의 logger**라 `_safe_out()`으로는 닿지 않는
자리였다.

**[두 가지 서로 다른 고장]** print와 logger는 실패하는 방식이 다르고, 후자가 더 나쁘다.

```
print(...)       예외를 던진다        -> 프로세스가 죽고 종료 코드 1
logger.xxx(...)  예외를 던지지 않는다  -> 그 로그 라인이 **소실**되고
                                      "--- Logging error ---" 트레이스백으로 대체된다
```

소실되는 쪽에는 `api/auth.py`의 JWKS 조회 실패 경고, `payment_providers.py`의
`PAYMENT_WEBHOOK_SECRET` 미설정 경고, `payments.py`의 Webhook 서명 검증 실패 경고처럼
**운영자가 반드시 봐야 하는 메시지**가 들어 있었다.

**[수정]** 출력 경로 11곳의 U+2014를 U+2015 HORIZONTAL BAR로 교체했다. U+2015는
**cp949에 존재하고(0xA1AA) EM DASH와 시각적으로 동일**해 읽는 사람 입장에서 바뀐 것이 없다.
새 정책을 만든 것이 아니라 이미 있던 관례(ASCII/cp949 안전 출력)를 전 범위에 맞춘 것이다.

API 응답 문자열은 **대상에서 제외**했다. JSON은 UTF-8로 직렬화되므로 콘솔 인코딩과 무관하고,
`payment_logs.py:webhook_reprocess_block_reason()`처럼 응답에만 실리는 문장은 그대로 둔다.
규칙을 실제 고장 경로에만 건다.

**[동시 발견 ― 크롤 데이터 경로는 안전하다]** `mvp_scraper.py`는 크롤한 `sido`/`case_no`/
법원명을 print하므로, 수집 데이터에 cp949 밖 문자가 섞이면 일일 크롤 전체가 죽을 수 있다.
`auction.db` 전 테이블 TEXT 컬럼 **111,980셀을 전수 검사해 0건**임을 확인했다(한글은 cp949에
있다). 현재 이 경로의 위험은 없다.

**[검증]** 신규 `test_console_encoding.py`(17검사) ― 저장소 전 .py의 출력 문자열 전수 스캔,
cp949 스트림 실출력 동작, logger 로그 소실 여부, 수정 지점 재확인. 변이 4종 전부 검출했고
전부 **수정 전 동작을 그대로 재현**했다.

**[스캔 자체의 사각 ― 함께 고침]** 처음 작성한 스캐너는 소스를 `utf-8`로 읽어
`ast.parse()`에 넘겼는데, 이 저장소에는 **UTF-8 BOM이 붙은 소스가 68개**
(`collect_documents.py` / `migrate_execute.py` / `api/v1/favorites.py` 등 운영 파일 포함) 있어
`SyntaxError: invalid non-printable character U+FEFF`로 조용히 건너뛰고 있었다.
`utf-8-sig`로 고치자(저장소의 다른 정적 검사들이 이미 쓰는 규약) **검사 대상 리터럴이
6,959 -> 7,778개로 늘고 숨어 있던 결함 2건이 즉시 드러났다.**

```
api/v1/item.py:53      logger.debug 의 EM DASH  (search.py와 같은 부류)
check_db_path.py:35    U+2705/U+274C 이모지
```

두 번째가 특히 나쁘다 ― `check_db_path.py`는 "크롤러와 API가 같은 DB를 보는가"를 알려주는
진단 스크립트인데, 두 경로를 출력한 **직후 정답을 출력하는 그 줄에서 죽고 있었다.**
`test_console_encoding.py`는 이제 파싱 실패 파일을 삼키지 않고 `SKIPPED`에 모아 0건임을
단언한다 ― 조용히 건너뛴 파일이 있으면 "통과"가 거짓이 되기 때문이다.

--------

#68

프런트 계약 게이트가 **백엔드 미기동을 기능 결함으로 오진**한다

해결 (2026-08-13, Sprint 72)

**[발견 경위]** 릴리즈 게이트를 돌리려고 `docs/TEST_PLAN.md`에 적힌 절차(`npm run dev` 후
`npm run test:frontend`)를 그대로 따랐더니 검사들이 줄줄이 실패했다. 그런데 실패 문구는
이랬다.

```
AssertionError: 비로그인 결과 카드에 즐겨찾기 버튼이 없습니다
```

즐겨찾기 기능에는 아무 문제가 없었다. **FastAPI 백엔드가 떠 있지 않아 검색 결과가 0건**이라
결과 카드 자체가 없었을 뿐이다. 백엔드를 띄우자 93검사 전부 통과했다.

**[원인]** `before()` 훅이 Next 서버만 확인하고 백엔드는 확인하지 않았다. 이 스위트는
Sprint 49에 "200이면 통과"에서 **실제 결과 데이터를 단언**하는 방식으로 의도적으로 바뀌었기
때문에(그 전에는 정렬이 안 되는 BUGS #29/#30이 전부 통과했다) 백엔드 없이는 성립하지 않는다.
그런데 `docs/TEST_PLAN.md`의 실행 절차에는 백엔드 기동이 아예 빠져 있어, 문서를 그대로 따르면
반드시 이 오진을 만난다.

**[수정]**
- `tests/frontend-contract.test.mjs`의 `before()`가 백엔드(`API_BASE_URL`, 기본
  `http://localhost:8000`)도 확인하고, 실패 시 **띄우는 명령까지** 지목한다
- 물건이 0건인 경우를 별도로 구분해 알린다 ― "데이터가 없다"와 "기능이 깨졌다"는 다르다
- `docs/TEST_PLAN.md`의 실행 절차에 백엔드 기동을 ①로 추가

건너뛰지 않고 **실패시키는** 쪽을 택했다. 백엔드 없이 통과한 결과를 "게이트 통과"로
오해하면 안 되기 때문이다.

**[검증]** 백엔드 주소를 죽은 포트로 돌려 재현하니 모든 실패 줄이 원인과 해결 명령을
지목했다(이전에는 즐겨찾기/정렬/페이지 문구로 흩어졌다). 백엔드 정상 기동 시 93/93 무변동 통과.

--------

#69

매각기일이 지난 문서가 상세 화면에 **영원히 "수집중"으로 남는다**

상태: **미해결 (결정 대기)** ― 2026-08-13 Sprint 73 발견·측정·회귀 고정 완료.
표시 정책 결정만 남았다.

**[발견 경위]** Document Lifecycle 감사 중 `document_status`의 상태 분포를 실측하다가
COLLECTING이 5,069건으로 비정상적으로 많은 것을 보고 추적했다.

**[체인]** 세 단계가 각각은 옳은데 이어 놓으면 끝나지 않는 상태가 된다.

```
1. 매각기일 경과
2. doc_worker가 브라우저 작업 없이 SKIPPED_EXPIRED 처리
     -> storage/database.py:mark_queue_skipped_expired()는 document_queue만 바꾼다
3. enqueue_documents()는 만료 물건을 애초에 큐에 넣지 않는다(1차 방어선)
     -> 다시 수집될 일이 없다
```

그 결과 화면이 읽는 `document_status`는 **COLLECTING인 채로 고정**된다.
`src/app/properties/[id]/page.tsx:68`이 COLLECTING을 "수집중"으로 표기하므로,
사용자는 **절대 도착하지 않을 문서를 계속 기다리게 된다.**

**[실측]**

```
SKIPPED_EXPIRED 큐 행                      186   그중 document_status=COLLECTING  183
document_status=COLLECTING & 물건 만료됨   5,049
document_status=COLLECTING & 물건 진행중      20
auction_item 1,876건 중 만료              1,867  (99.5%)
```

**[사용자에게 보이는가 ― 보인다]** 검색은 D7 기본값으로 만료 물건을 제외하지만
`favorites`/`recent_items`에는 날짜 필터가 없고 상세 API도 만료 물건을 200으로 돌려준다.

```
GET /api/v1/item/1  (auction_date=2026-07-07, 5주 전 만료)  -> 200
documents: SPEC / STATUS / APPRAISAL 전부 COLLECTING
```

즉 관심물건에 담아 둔 물건이 만료되면 그 상세 화면은 영구히 "수집중"을 보여준다.

**[왜 지금 고치지 않는가]** "대상이 아님"을 나타낼 상태가 없다. `DocStatus`는
COLLECTING/OCR/PARSING/ANALYZING/READY/FAILED뿐이고, FAILED로 쓰면 **실패가 아닌 것을
실패로** 표기하게 된다(수집을 시도조차 하지 않았다). 새 상태를 만들지, 화면에서 만료
물건의 문서 영역 자체를 다르게 그릴지는 **상태머신·화면 문구 결정**이라 제품 판단이다.
`docs/CLAUDE.md`의 "모르면 질문한다" 원칙에 따라 결정을 임의로 내리지 않았다.

**[대신 한 것]** `test_document_status_sync.py` §6/§7에 **현재 동작을 그대로 고정**했다.
정책을 정해 배선하는 순간 이 검사가 실패하면서 함께 고쳐야 할 세 지점을 지목한다.

```
storage/database.py:mark_queue_skipped_expired()   기록 지점
api/v1/item.py                                     화면에 내려주는 지점
src/app/properties/[id]/page.tsx:68                문구 매핑
```

노출 경로(favorites/recent에 날짜 필터가 없다는 사실, 검색의 D7 기본 제외)도 소스 계약으로
함께 고정해, 그 전제가 바뀌면 위 서술이 낡았다는 것이 드러나게 했다.
변이 검증: `mark_queue_skipped_expired()`가 `document_status`를 건드리도록 배선하니
즉시 1건 실패하며 그 지점을 지목했다.

--------

#70

유찰 후 **재매각된 사건이 문서 수집에서 영구히 빠진다** ― 큐가 옛 매각기일을 계속 들고 있다

해결 (2026-08-13, Sprint 74)

**[발견 경위]** #69(만료 물건의 COLLECTING) 체인을 이어 추적하며 **"만료된 물건이 재매각으로
다시 살아나면 어떻게 되는가"**를 물었다. 재수집 가능성을 확인하려던 질문에서 나왔다.

**[원인]** `enqueue_documents()`는 `INSERT OR IGNORE`를 쓰고 UNIQUE는
(court_code, case_no, item_no, doc_type)이다. 재매각으로 **새 매각기일**이 잡혀도 같은 4-tuple이라
INSERT가 통째로 무시되고, **큐 행은 옛 기일을 그대로 들고 남는다.**

그 다음이 실제 피해다. `doc_worker`의 2차 방어선은 큐에 저장된 값을 본다.

```python
if auction_date and auction_date < today:
    mark_queue_skipped_expired(...)      # 브라우저 작업 없이 종료
```

기일이 미래로 다시 잡힌 **살아 있는 사건**이 옛 날짜 때문에 "기일 경과"로 판정돼 죽는다.
`refresh_queue_priority()`도 같은 stale 값으로 우선순위를 계산하므로 함께 틀린다.

**[실측 ― 실제로 일어나 있었다]**

```
큐 auction_date != auction_item.auction_date        18행
그중 현재 기일이 미래(재매각으로 살아난 사건)          9행

item=1533  큐 2026-07-15 (pending)  vs 현재 2026-08-19   <- 6일 뒤 매각인데 죽는다
item=502   큐 2026-07-15 (done)     vs 현재 2026-08-19
item=505   큐 2026-07-15 (done)     vs 현재 2026-08-19
```

item=1533은 다음 `doc_worker` 실행에서 3건 모두 SKIPPED_EXPIRED가 될 예정이었다.

**[수정]** INSERT가 무시됐을 때(rowcount==0) 그 행의 `auction_date`/`priority`를 최신 크롤
값으로 동기화한다. 반환값에 `refreshed` 건수를 더해 로그로 추적할 수 있게 했다.

**★ status는 건드리지 않는다.** done/failed/SKIPPED_EXPIRED를 되살려 다시 수집할지는
**재수집 정책**이라 제품 판단이다(`docs/roadmap.md` 결정 대기). 여기서 고친 것은 큐가 자기
필드에 사실과 다른 값을 들고 있는 것뿐이며, **그것만으로 pending 행의 오판은 사라진다.**

**[검증]** `test_document_queue.py` §12/§13 신규(17검사). 갱신 동작, 상태 불변,
무관한 행 미변경(다른 사건 / 같은 사건의 다른 물건번호), 그리고 **결과 확인**으로
`claim_next_queue_item()`이 돌려준 일감의 기일이 미래인지까지 본다.

변이 3종 전부 검출. 그중 **"priority 갱신 누락"은 처음에 검출되지 않았다** ― 시드
priority(3)가 계산값과 우연히 같았기 때문이다. 기일을 +5일(계산값 2)로 바꿔 검사가 실제
구분력을 갖게 고친 뒤 검출됐다. 변이 시험이 없었으면 통과하는 무력한 검사가 남을 뻔했다.

**[남은 데이터]** 이미 어긋나 있는 18행은 다음 크롤에서 자연히 맞춰진다(코드가 고쳐졌으므로).
운영 DB를 직접 손대는 것은 이번 범위가 아니라 하지 않았다.

--------

#71

`renew()`가 **동시 갱신에서 사용자가 산 기간 한 주기를 잃는다** ― 조건 없는 UPDATE

해결 (2026-08-13, Sprint 78)

**[발견 경위]** Admin API 전수 프로브를 끝내고 구독 상태머신으로 넘어가, Sprint 74가
`renew()`의 **전 상태 매트릭스**는 고정했지만 **동시 갱신은 다루지 않았다**는 것을 보고
그 경로를 팠다.

**[원인]** `renew()`는 read -> compute -> write인데 write가 `WHERE id=?`뿐이었다.

```python
row = conn.execute("SELECT * FROM subscriptions WHERE id=?", ...)   # base 만료시각을 읽는다
new_expires = base + timedelta(days=period_days)                    # 그 값에서 계산한다
conn.execute("UPDATE subscriptions SET ... WHERE id=?", ...)         # 조건 없이 덮어쓴다
```

SELECT와 UPDATE 사이에 다른 갱신이 끼면 **뒤엣것이 앞엣것의 연장을 통째로 덮어쓴다.**
같은 모듈의 `change_status()`는 2026-08-12에 이미 "조건부 UPDATE + rowcount 확인" 가드를
얻었는데(#21과 같은 부류), **돈을 받고 기간을 늘리는 쪽에만 그 가드가 없었다.**

**[실측 ― 결정적 재현]** 스레드에 기대지 않았다. `test_race_conditions.py` §6/§7이 이미
"스레드 경합은 창이 좁아 가드 제거 변이를 항상 잡지 못한다"고 기록해 두었으므로,
UPDATE 직전에 다른 커넥션의 갱신을 한 건 완주시키는 방식으로 100% 재현했다.

```
기존 만료 2026-06-25, 30일 갱신 2건(= 결제 2건)
  기대            60일 연장
  실제            30일 연장          <- 한 주기 소실. 예외도 경고도 없다
journal_mode      delete / wal 양쪽 동일 (WAL 전환과 무관하게 이미 열려 있었다)
```

**[수정]** 읽은 값을 UPDATE의 WHERE에 다시 걸고 rowcount로 검증한다. 충돌이면
`ConcurrentStatusChange`를 던져 호출부가 **다시 읽어 다시 계산**하게 한다(재시도하면 두
주기가 정확히 누적된다 ― 검증 완료).

```sql
UPDATE subscriptions SET status=?, expires_at=?, updated_at=?
 WHERE id=? AND status=? AND expires_at IS ?      -- NULL 비교라 `=`가 아니라 `IS`
```

`expires_at`은 NULL일 수 있으므로(무기한 구독) `=`를 쓰면 **무기한 구독의 갱신이 항상
충돌로 오판된다.** 변이 시험에서 이 함정이 실제로 검출됐다(M4).

**★ `BEGIN IMMEDIATE`는 쓰지 않았다.** `change_status()`와 트랜잭션 계약이 다르다 ―
`renew()`는 호출부가 트랜잭션을 소유한다(호출부/테스트가 `BEGIN` 안에서 부른다). 여기서
새 트랜잭션을 시작하면 "cannot start a transaction within a transaction"으로 기존 계약이
깨진다. 낙관적 잠금만으로 같은 보호를 얻으며 잠금 모드와도 무관하다.

**[부수 계약 확인]** 던질 때 롤백하지 **않는다** ― 같은 트랜잭션에 담긴 호출부의 다른
작업(결제 기록 등)까지 지우면 안 되기 때문이다. 대신 호출부가 재시도 전에 롤백해야 한다.
이 계약은 추측이 아니라 실측으로 확인했다: 롤백하지 않으면 실패한 UPDATE가 열어 둔 쓰기
트랜잭션이 남아 다음 쓰기가 `database is locked`로 막힌다(테스트를 쓰다 실제로 막혔다).

**[검증]** `test_subscription_policy.py` §11 신규(9검사). 거부만 보지 않고 **재시도 후
누적**까지 본다 ― 거부로 끝나면 사용자는 여전히 한 주기를 못 받으므로, 거부는 계약의
절반일 뿐이다. 함께 고정한 것: 갱신 중 해지가 끼면 해지된 구독이 되살아나지 않는다,
무기한 구독(NULL)도 정상 갱신된다.

변이 4종 전부 검출(가드 제거 / rowcount 무력화 / expires_at 조건 제거 / IS를 =로).

**[현재 노출 범위]** `renew()`는 아직 프로덕션 호출부가 0곳이다(배선되지 않은 준비 코드).
그래서 오늘 실제 피해는 없다. 배선되는 순간이 결제 갱신 경로이므로 그 전에 닫았다.

--------

#72

Admin webhook 목록의 `provider` 필터가 **오타를 빈 결과로 돌려준다**

해결 (2026-08-13, Sprint 78)

**[발견 경위]** Admin endpoint를 코드에서 열거해 차원별(인증/권한/없는 ID/잘못된 필터/
페이지 경계/잘못된 body)로 실제 HTTP를 찍는 프로브를 돌렸다.

**[원인]** Sprint 74가 "잘못된 필터 값은 400 + 허용값 안내"로 규약을 통일했는데,
`admin_list_webhooks()`의 `provider`만 빠져 있었다 ― **같은 함수 안에서** 바로 위
`processing_status`는 검증되고 `provider`는 그대로 SQL 등호로 들어갔다.

```
GET /admin/payments/webhooks?processing_status=BOGUS  ->  400  허용값 안내
GET /admin/payments/webhooks?provider=BOGUS           ->  200  {"data": []}   <- 오타인지 없는지 모른다
```

운영자는 "그 PG의 노티가 한 건도 없다"고 읽는다. Sprint 74가 없애려던 바로 그 상태다.

**[수정]** 허용값을 `_PROVIDERS` 맵에서 도출해(`VALID_PROVIDER_NAMES`) 검증한다 ―
webhook 수신 경로가 같은 맵으로 검증하므로 **저장될 수 있는 값의 집합이 곧 그 맵의 키**다.
목록을 손으로 적지 않는다(provider가 늘 때 조용히 어긋난다).

수신 경로와 **같은 정규화**(`.strip().lower()`)도 함께 적용했다. 그쪽이 소문자로 정규화해
저장하므로, 정규화하지 않으면 `provider=Mock`이 "시스템은 받아주는 이름인데 조회에서는
거부되는" 비대칭이 된다.

**[검증]** `test_api_regression.py` webhook 운영 섹션에 6검사 추가. 빈 테이블에서 검사하면
"필터가 동작한다"와 "아무것도 없다"를 구분할 수 없으므로 **provider='mock' 행이 실재하는
시점**에 검사한다. 유효하지만 없는 값(kginicis)은 200 + 빈 목록으로, 오타는 400으로
갈리는 것까지 확인한다. 변이 3종 검출(검증 제거 / 정규화 제거 / 필터 미적용).

**[함께 확인하고 결함이 아니었던 것]** 같은 프로브로 admin 16개 엔드포인트를 훑었다.
`/admin/users`와 `/admin/subscriptions`에 `plan`/`status` 오타를 줘도 200이 나오는데,
이 둘은 **애초에 선언되지 않은 쿼리 파라미터**라 FastAPI가 무시하는 것이다(필터가 아니다).
`user_id`/`sido` 같은 자유 입력 필터는 검증할 허용 집합 자체가 없다. 즉 남은 미검증
SQL 등호 필터는 `provider` 하나였다.

--------

#73

재시도 복구가 **화면 상태를 되돌리지 않아** 재시도 대기 중인 문서가 "수집실패"로 남는다

해결 (2026-08-13, Sprint 78)

**[발견 경위]** Document lifecycle의 실패/복구 경로를 추적하다가, `mark_queue_failed()`가
자기 규칙을 명시해 둔 것을 보고 그 규칙이 **복구 경로에서도 지켜지는가**를 물었다.

> "재시도가 소진된 **최종** 실패만 화면에 반영한다. 중간 재시도까지 FAILED로 바꾸면
>  다음 시도에서 성공할 문서가 잠깐 '실패'로 보였다가 돌아온다."

**[원인]** `reset_stale_queue()`가 하루 지난 failed 행을 `pending` + `retry_count=0`
(완전히 새 시도)으로 되돌리면서 `document_status`는 손대지 않았다.

```
복구 전  queue=failed   document_status=FAILED     "수집실패"  <- 맞다(재시도 소진)
복구 후  queue=pending  document_status=FAILED     "수집실패"  <- 틀리다(재시도 대기 중)
```

화면이 읽는 것은 `document_status`다(#50). 즉 위 규칙이 **이 경로에서만** 깨져 있었고,
#50이 정한 "두 기록을 같은 트랜잭션에서 함께 갱신한다"도 함께 어긋난 상태였다.

**[실측]** 현재 운영 DB는 `failed` 큐 행이 0건이라 불일치가 **아직 없다**(pending&FAILED 0건).
즉 잠재 결함이고, 문서 하나가 재시도를 소진한 다음 날 나타난다.

```
document_queue.status x document_status.status (실측)
  pending          COLLECTING   2741
  done             READY         556
  SKIPPED_EXPIRED  COLLECTING    183
  failed 큐 행 0건  /  document_status FAILED 3건(모두 큐에서 이미 사라진 행)
```

**[수정]** 회수 대상을 UPDATE **전에** 식별해 두고, 같은 트랜잭션에서 화면 상태를
`COLLECTING`으로 되돌린다. 새 정책이 아니라 위 두 규칙의 적용이다.

**★ `FAILED`인 행만 되돌린다.** `in_progress` 회수분이나 이전에 수집에 성공한 문서(READY)를
COLLECTING으로 덮으면 **파일이 실제로 있는 문서를 "수집중"으로 가려** 사용자가 볼 수 있는
것을 못 보게 된다 — 정반대 방향의 결함이라 회귀 검사에 함께 넣었다.

**[수정 중 발견한 두 번째 결함 ― 기존 테스트가 잡았다]** 처음 구현은 화면 동기화 예외를
그대로 올렸다. 그러면 커밋 전에 빠져나가 **회수 UPDATE까지 사라진다** — doc_worker가
아무것도 회수되지 않은 채 시작하므로 고치려던 것보다 나쁘다. `document_status`/
`auction_item`이 없는 축소 스키마(`test_document_queue.py`의 임시 DB)에서 이 경로가 통째로
죽는 것을 **기존 §6 테스트가 즉시 검출**했다. `_set_document_status()`가 대상이 없을 때
예외 대신 경고+False를 돌려주는 것과 같은 판단으로, 화면 반영 실패를 격리했다.

**[함께 정리한 것]** `document_status` 조회(큐 키 -> item_id)가 쓰기 쪽에만 있었다.
읽기(`_current_document_status`)가 같은 JOIN 경로를 써야 하므로 `_document_status_item_id()`
하나로 뽑아 두 곳이 공유한다 — 조회를 두 벌 두면 한쪽만 고쳐졌을 때 "쓰기는 찾는데 읽기는
못 찾는" 어긋남이 생긴다.

**[검증]** `test_document_status_sync.py` §9 신규(15검사). 복구/보존/미대상/기록없음/
테이블없음 5가지 상황을 전부 본다. 변이 5종 전부 검출(복구 루프 제거 / 조건 없이 덮어쓰기 /
목표 상태 오기 / 대상 식별을 UPDATE 뒤로 이동 / 예외 격리 제거).

--------

#74

JWKS 키 회전 경로가 **커버리지 0%** ― 운영 토큰이 실제로 지나는 길이 미검증이었다

해결 (2026-08-13, Sprint 78) ― 결함은 발견되지 않았고, 계약 12건을 회귀로 고정했다

**[발견 경위]** "미검증 코드 경로"를 추측이 아니라 측정으로 찾기 위해 전체 테스트 스위트를
커버리지로 돌렸다(27개 파일, `--source=api,storage,config,crawler,normalizer,models,filter,validator`).

```
전체 71%.  api/auth.py 81% ― 미커버 55-64, 78-83
```

그 두 구간이 `_fetch_jwks_locked()`와 `_get_jwk()`의 **키 회전/속도제한 분기** 전체다.
기존 `test_auth_jwt.py`는 §1~§5에서 JWKS 캐시를 **미리 채워 두고** 검증하므로 이 경로가
한 번도 실행되지 않았다. 그런데 Supabase가 키를 회전하면 캐시에 없는 kid가 오고, 실제
운영 토큰은 바로 이 코드를 지난다 ― 여기가 틀리면 **전원 401**이 되거나, 반대로 요청마다
외부 호출이 나가 장애를 증폭시킨다.

**[결과] 제품 결함은 없었다.** 6가지 계약이 전부 올바르게 구현돼 있었다. 다만 그것을
확인하는 검사가 없었으므로 회귀로 고정했다(네트워크 미사용 ― `urllib.request.urlopen`을
대역으로 교체).

```
(1) 모르는 kid -> JWKS 재조회 -> 새 키로 서명된 ES256 토큰이 실제로 검증된다
(2) 모르는 kid 5연속에도 외부 조회는 1회 (_JWKS_MIN_REFETCH_SECONDS)
(3) 빈 JWKS 응답이 기존 캐시를 지우지 않는다 (일시 오류에 전원 로그아웃 방지)
(4) 조회 실패가 예외로 새지 않는다 (서버가 죽지 않고 인증 실패로만 이어진다)
(5) 실패해도 조회 시각을 갱신한다 (재시도 폭주 방지)
(6) 신선한 캐시 적중 시 외부 조회 0회 / URL 미설정이면 조회 시도 자체를 하지 않는다
```

**[변이 시험 6종 전부 검출]** 그 과정에서 **검사 자체의 결함 2건**을 고쳤다.

- 처음 작성한 검사는 가드 제거 변이에서 FAIL이 아니라 **크래시**로 끝났다(예외가 최상위로
  올라가 남은 검사가 실행되지 않는다). `test_api_regression.py::_safe_out`이 고친 것과 같은
  종류의 하네스 결함이라 같은 방식으로 막았다 ― 이제 6종 전부 깔끔한 FAIL이다.
- M5 변이("실패 시 조회 시각 미갱신")를 처음에 **의미상 동등하게** 만들어 검출력을 재지
  못했다. 갱신을 함수 끝으로 옮기는 진짜 회귀로 다시 만들어 검출을 확인했다.

**[함께 발견한 것 ― 계측이 틀렸던 사례]** 검사를 쓰다 `json` import를 빠뜨렸는데,
`NameError`가 제품의 예외 격리(위 (4))에 삼켜져 **"키를 못 찾는다"는 증상으로만** 보였다.
격리가 의도대로 동작한다는 증거이기도 하다(서버는 죽지 않았다). 원인을 격리 밖에서 재현해
확인한 뒤 고쳤다.

**[성능 실측 ― 결함 없음]** 같은 감사에서 Sprint 74가 측정하지 않은 핫패스를 함께 쟀다
(TestClient in-process, n=12, 쿼리 수는 `sqlite3.set_trace_callback`으로 계수).

```
item detail 2.2ms(6쿼리) / documents 2.5ms / favorites 2.6ms(2쿼리, N+1 없음)
recent 2.6ms / subscriptions/me 2.3ms / payments 2.3ms
search 2.6ms / search offset=1000 2.5ms(깊은 페이지 열화 없음) / doc-stats 3.0ms
전부 p95 <= 3.4ms
```

첫 계측은 **모든 엔드포인트를 0쿼리로** 보고했다 ― `api/v1/*.py`가
`from storage.database import get_connection`으로 import 시점에 이름을 바인딩하므로 모듈
속성 교체가 닿지 않았다. `sqlite3.connect`를 감싸는 방식으로 고쳐 다시 측정했다.
최적화는 하지 않았다(문제가 없으므로).

--------

#75

검색 필터 12개가 **선언만 되고 한 번도 실행된 적이 없었다** (커버리지 0 구간)

해결 (2026-08-13, Sprint 78) ― 제품 결함은 없었고, 검사 20건을 추가했다

**[발견 경위]** #74와 같은 커버리지 측정에서 `api/v1/search.py` 82%, 미커버 266-305.
그 구간이 필터 분기 전체다.

```
court_name / status / auction_date_to
min·max appraisal / min·max bid_price / min·max bid_rate / min·max fail_count
```

**12개 파라미터를 어떤 테스트도 넘겨본 적이 없었다.** `test_search.py`는 주소 Intent만,
`test_api_regression.py`는 기본 조회만 본다.

이 부류의 결함은 조용하다. `min_appraisal`이 `<=`로 뒤집혀 있으면 사용자는 "최소 감정가
5억"으로 검색해 **5억 이하** 물건을 받는다. 서버는 200을 주고 로그도 남지 않는다.

**[결과] 제품 결함은 없었다.** 12개 필터가 전부 올바른 컬럼·올바른 방향으로 걸려 있었다.
검사만 없었으므로 이 파일의 기존 원칙(건수 비의존, 행 단위 검증)대로 추가했다.

```
(a) 행 단위: 돌아온 모든 행이 조건을 만족하는가
(b) 방향 정합: min/max 결과의 합이 전체를 덮는가 (min/max 구현을 서로 바꿔도 (a)만으론 통과한다)
(c) 모순 범위(min>max)는 빈 결과인가 (조건이 AND가 아니라 OR로 묶이면 여기서 드러난다)
(d) 구간: auction_date_from==to 는 그 날짜만
```

경계값은 하드코딩하지 않고 **실제 데이터의 중앙값**에서 뽑는다(이 파일이 Sprint 47에
"고정 건수 단언"을 걷어낸 것과 같은 이유).

**[변이 시험에서 무력한 검사를 잡았다 ― 가장 중요한 부분]** 변이 5종 중 **M4
(`court_name`을 `status` 컬럼에 오배선)가 검출되지 않았다.**

```
필터가 엉뚱한 컬럼에 걸리면 결과가 0건이 된다
  -> "돌아온 모든 행이 조건을 만족한다"가 **공허하게 참**이 된다
  -> 검사는 통과하고 결함은 남는다
```

검색 대상을 실제 행에서 뽑았으므로 최소 1건은 나와야 한다 ― 그 **구분력 단언**을 먼저
두어 고쳤다. 다시 변이를 넣으니 즉시 검출됐다(FAIL 1). Sprint 74가 `test_document_queue.py`
§13에서 겪은 것과 같은 종류다(시드 priority가 계산값과 우연히 같아 변이가 통과했던 건).

**[테스트 자체의 결함 2건도 함께 고쳤다]**

- `size=200`으로 조회 -> API 상한이 100이라 422. 상한은 제품이 옳다(테스트를 고쳤다).
- float 컬럼(`bid_rate`)에 `max = bound`를 넘기고 "모순 범위"라고 불렀다. `min==max`는
  모순이 아니라 정확일치이므로 293건이 나온 것이 **옳은 동작**이었다. 타입별로 실제 모순값
  (int는 -1, float는 -0.01)을 만들도록 고쳤다.

변이 5종 최종 검출: min 방향 뒤집기 / max 필터 미적용 / 엉뚱한 컬럼 / 컬럼 오배선 /
날짜 상한 방향 뒤집기 ― 전부 FAIL.

--------

#76

`upsert_batch()`의 **행 단위 실패 격리가 미검증** ― 크롤러 일일 쓰기의 FR-101 경로

해결 (2026-08-13, Sprint 78) ― 제품 결함은 없었고, 검사 16건을 추가했다

**[발견 경위]** 커버리지에서 `storage/database.py` 80%, 미커버 245-247/254-257.
그 구간이 `upsert_batch()`의 **행 단위 예외 처리와 전체 롤백**이다. §2(test_auction_identity)는
정상 경로(insert/update/법원 격리)만 봤다.

왜 중요한가 ― 이 함수는 **매일 06:00 크롤러의 유일한 DB 쓰기 경로**다(`mvp_scraper.py`).
법원 60곳에서 모은 수백 행을 한 번에 넣는데, 그중 한 행이 기형이면(가격 필드에 숫자가 아닌
값이 오는 것은 크롤링에서 드문 일이 아니다) 나머지가 함께 사라지면 그날 수집이 통째로 없어진다.

**[결과] 제품 결함은 없었다.** 격리가 올바르게 동작한다.

```
[정상, 기형(가격="가격미정"), 정상]  ->  inserted 2 / updated 0 / failed 1
  깨진 행 앞·뒤의 정상 행이 모두 커밋됐다
  깨진 행은 저장되지 않았다
재실행 -> 정상 행은 update(값이 실제로 바뀐다), 기형 행은 여전히 failed(누적 오염 없음)
빈 배치 -> 0/0/0 (예외 없음)
키가 아예 없는 행 -> 배치를 죽이지 않는다
합계(inserted+updated+failed) == 입력 행 수  <- 조용히 사라지는 행이 없다
```

`get_stats()`(크롤러가 매 실행 끝에 로그로 남기는 요약)도 미커버였으므로 계약을 함께 고정했다.

**[변이 4종 전부 검출]** 격리 제거 / failed 미계수 / commit 제거 / update를 insert로 계수.

**[하네스 개선]** "격리 제거" 변이가 처음에 **크래시**로 나타나 남은 검사가 실행되지 않았다.
`upsert_batch` 호출을 감싸 예외를 FAIL로 바꿨다 ― 이제 같은 변이가 FAIL 6건으로 원인과
범위를 함께 보여준다(#74에서 고친 것과 같은 부류의 하네스 결함).

**[측정 자체의 오판도 기록해 둔다]** 처음에 database.py 커버리지를 재면서 **테스트 파일 일부만**
실행해 "upsert_batch 99문장 전체가 미커버"라고 읽었다. `test_auction_identity.py`를 빼먹은
탓이었고, 전체 스위트로 다시 재니 미커버는 위 7줄뿐이었다. 커버리지 수치는 **어떤 테스트를
포함했는지**와 함께 읽어야 한다.

--------

#77

코드가 **정확성을 위해 의존하는 UNIQUE 제약**을 강제하는 검사가 없었다

해결 (2026-08-13, Sprint 78) ― 제약은 전부 존재했고, 사라지면 잡히도록 고정했다

**[발견 경위]** Concurrency 감사에서 `add_favorite()`를 읽다가, 이 함수가 **애플리케이션에서
중복을 확인하지 않는다**는 점에 주목했다. 조회 후 판단하면 TOCTOU가 되므로 그 설계가 옳은데,
그렇다면 정확성이 **DB 제약에 걸려 있다**는 뜻이다. 그 제약을 지키는 검사가 있는지 물었다.

```
api/v1/favorites.py:add_favorite()       IntegrityError -> FAVORITE_ALREADY_EXISTS
api/v1/recent_items.py                   같은 (user_id,item_id)를 여러 행으로 만들지 않는다
api/v1/payment_logs.py:record_webhook()  event_id UNIQUE -> is_duplicate (Webhook 멱등성)
```

**제약이 사라지면 이 세 방어가 조용히 전부 무력화된다.** 중복 즐겨찾기가 쌓이고, 같은 PG
노티가 두 번 적용된다(결제 상태 이중 반영). 예외가 나지 않으므로 로그도 남지 않는다.

**[실측] 제약은 세 곳 모두 존재한다.** 다만 강제하는 검사가 없었다 —
`test_auction_identity.py` §1이 auction 계열 3개 테이블에 대해 같은 검사를 하고 있는데
이 세 테이블은 빠져 있었다.

**[왜 실제 위험인가]** 이 저장소는 migration 018이 `document_queue`를 **테이블 재생성**
방식으로 바꾼 전례가 있다(CREATE new -> copy -> rename). 재생성 SQL에서 UNIQUE 한 줄을
빠뜨리면 **데이터는 그대로 옮겨지고 제약만 사라진다.** 로컬에서는 아무 증상이 없다.

**[검증]** `test_schema_hygiene.py` §7 신규(6검사). DDL 선언과 **실제 데이터의 중복 0건**을
함께 본다 — 선언만 보면 "제약은 있는데 과거에 이미 쌓인 중복"을 놓친다.

변이 검증은 실제 DB를 건드리지 않고 **스크래치 사본에서 018과 같은 재생성 방식으로**
`favorites`의 UNIQUE만 떨어뜨려 수행했다 → 즉시 FAIL, 무력화되는 방어 이름까지 지목했다.

**[검사 작성 중 잡은 함정]** `payment_webhooks`의 DDL에는 UNIQUE를 설명하는 **주석**에
"UNIQUE"라는 단어가 들어 있다. 주석을 지우지 않고 문자열만 찾으면 **주석만 보고 통과**한다.
주석 제거 후 판정하도록 고쳤다(그러지 않으면 제약이 사라져도 통과하는 검사가 된다).

--------

#78

편집 도구가 **BOM을 조용히 떨어뜨려도** 아무 검사가 잡지 못했다

해결 (2026-08-13, Sprint 78)

**[발견 경위]** Sprint 78 작업을 끝내고 `git diff`를 눈으로 확인하다가 발견했다.
변이 시험 스크립트가 `utf-8-sig`로 읽고 `utf-8`로 다시 쓰면서 `normalizer/normalizer.py`의
BOM을 떨어뜨렸다. **어떤 테스트도 이것을 잡지 못했다** — Python은 두 형태 모두 정상 실행하고
`test_console_encoding.py`는 애초에 `utf-8-sig`로 읽도록 설계돼 있어(BOM 유무에 둔감) PASS다.

발견 경로가 "사람이 diff를 봤다" 하나뿐이었다는 점이 문제다.

**[왜 문제인가]** 조용한 전량 변경은 **진짜 변경을 가린다.** BOM만 달라진 파일도 diff에
뜨므로 리뷰에서 실제 코드 변경을 찾기 어려워지고, "이 파일을 왜 건드렸지?"가 반복된다.
이 저장소는 소스 68개에 BOM이 있는 상태가 **의도된 현재 상태**이고
(`test_console_encoding.py`가 그래서 읽기를 `utf-8-sig`로 고정했다), 그 상태가 편집 도구에
따라 흔들리면 안 된다.

**[조치]** 두 가지를 했다.

1. `normalizer/normalizer.py`의 BOM을 복원했다 — HEAD와 **바이트 단위로 동일**함을 확인
   (`git show HEAD:...` 대조, 줄바꿈 정규화 후 일치). 제품 코드 변경은 0이다.
2. `test_schema_hygiene.py` §8 신규 — **변경된 텍스트 소스의 BOM 유무가 HEAD와 같은가**를
   검사한다. git이 없는 환경(배포본)에서는 조용히 건너뛴다(검사가 실패 원인이 되면 안 된다).

**[검증]** BOM을 일부러 떨어뜨리니 즉시 FAIL하며 **파일명까지 지목**했다. 같은 상태에서
`test_console_encoding.py`는 여전히 PASS다 — 즉 이 결함은 새 검사만이 잡는다는 것이 확인됐다.

**[작성 중 함정 1건]** `BOM = b"..."`를 리터럴로 적으면 **그 리터럴이 이 파일 자체의
인코딩에 휘둘린다**(실제로 `SyntaxError: bytes can only contain ASCII literal characters`가
났다). `codecs.BOM_UTF8`을 쓰도록 고쳤다 — 인코딩을 검사하는 코드가 인코딩에 의존하면 안 된다.

--------

#92

**지역 분류가 문자열 위치가 아니라 사전 선언 순서로 정해졌다** ― 도로명/건물명/사람 이름에
섞인 지역명이 진짜 주소를 이긴다

해결 (2026-08-13, Sprint 78)

**[발견 경위]** validator의 검증 규칙이 미검증 상태인 것을 확인하다가, 실제 DB의
`validation_status='FAIL'` 12건 중 11건이 `address_mismatch`인 것을 보고 **오탐인지 진짜
불일치인지** 확인하러 들어갔다. 오탐이 아니었다 ― validator는 제 일을 했고, 그 뒤에
더 큰 결함이 있었다.

**[원인]** `normalizer.extract_sido()`가 `SIDO_PATTERNS`를 **딕셔너리 선언 순서**로 훑어
**처음 발견된 것**을 돌려줬다. 즉 판정 기준이 문자열 안의 위치가 아니라 **사전의 줄 순서**였다.

```python
for sido, patterns in SIDO_PATTERNS.items():   # 서울, 경기, 인천, ... 세종, ... 제주(마지막)
    for p in patterns:
        if p in text:      # 위치를 보지 않는다
            return sido
```

**[실측 ― 1,876건 중 4건이 잘못 분류돼 있었다]** 원인이 전부 다르다.

```
경기도 시흥시 서울대학로 59-21                -> 서울 (실제 경기)   도로명
경상남도 양산시 물금읍 부산대학로 150          -> 부산 (실제 경남)   도로명
인천광역시 계양구 ... (효성동, 뉴서울아파트)    -> 서울 (실제 인천)   건물명
제주특별자치도 제주시 ... 주식회사 뉴세종하우징  -> 세종 (실제 제주)   공유자(법인) 이름
```

마지막 건이 결함의 성격을 가장 잘 보여준다. **"제주특별자치도"가 0번 위치에 있는데
539번 위치의 "세종"에게 졌다.** 오직 사전에서 세종이 제주보다 위라는 이유였다.

**[왜 중요한가]** `sido`는 검색의 1차 필터다. 잘못 분류된 물건은 **제 지역에서 검색되지
않고 남의 지역을 오염시킨다.** 그리고 `서울대학로`/`부산대학로`는 실재하는 도로명이라
**반드시 재발한다** ― 한 번 고치고 끝나는 데이터 오류가 아니다.

**[수정]** 가장 **앞에 나오는 표기**가 이기도록 바꿨다. 위치가 같으면 더 긴(구체적인)
표기를 택한다. 지역명이 앞에 오지 않는 입력(사용자 검색어 "강남구 아파트", 감정요항
자유 텍스트)에 대해서는 기존 동작이 그대로다 ― 이 함수는 주소 전용이 아니라 세 용도에
쓰이므로 "주소 접두어만 본다"가 아니라 "가장 앞선 언급"으로 고친 이유가 그것이다.

전수 재계산 결과 **1,876건 중 정확히 이 4건만 바뀌었다**(나머지 1,872건 무변동).

**[동시 수정 ― 판정 함수가 두 벌이었다]** `validator/validation_engine.py`에
**바이트 단위로 동일한 복사본**이 따로 있었다. 그 파일의 주석은 데이터(SIDO_MAP)를
"한쪽만 남기고 재사용한다"고 적어 뒀는데, **그 데이터를 해석하는 함수는 합쳐지지 않은 채**
남아 있었다. 복사본을 그대로 뒀다면 **크롤은 제주로 저장하는데 검증은 세종으로 판정**해
address_mismatch 오탐이 되고 화면에 "검증실패"로 떴을 것이다. normalizer의 것을
재노출(re-export)하도록 바꿔 호출부는 그대로 두고 중복만 없앴다.

**[검증]** `test_normalizer.py`에 13검사 추가(실제 4건 + 정상 주소 3종 + 검색어/빈 입력 +
같은 위치면 긴 표기 우선 + **사전 순서를 뒤집어도 결과가 같다** + validator가 같은 함수를
쓴다). 수정 전 구현으로 되돌리는 변이에서 **실제 4건이 정확히 실패**했다.

**[남은 데이터]** 기존 4행은 **매각기일이 전부 지나** 재크롤 대상이 아니므로 DB에는 잘못된
`sido`가 남는다. 다만 만료 물건이라 검색(D7 기본 제외)에는 나오지 않는다. 운영 데이터를
임의로 고치지 않았다 ― 필요하면 4행 UPDATE로 끝나는 작업이다.

--------

#79

`ValidationEngine.validate()`가 **커버리지 0%** ― 크롤 데이터의 검증 판정 전체가 미검증

해결 (2026-08-13, Sprint 78) ― 제품 결함은 없었고, 62검사를 신규 파일로 추가했다

**[발견 경위]** 커버리지 재측정에서 `validator/validation_engine.py` **52%**, 미커버 47-131이
`validate()` **전체**였다. 이 파일에서 실제로 판정하는 코드는 한 번도 실행된 적이 없었다.

**[왜 위험한가]** 판정 결과가 그 자리에서 끝나지 않는다.

```
validate() -> AuctionItem.validation_status -> normalize_item() -> upsert_batch()
  -> auction / auction_item.validation_status
    -> GET /search?validation_status=...  (검색 필터)
    -> GET /item/{id} 의 validation_status (화면 표시)
```

규칙 하나가 어긋나면 **정상 물건이 "검증실패"로 표시되거나** 사건번호 형식이 깨진 물건이
PASS로 흘러간다. 예외가 없으므로 로그에도 남지 않는다.

**결정적으로**, 이 파일은 **같은 날 Sprint 78에 수정됐다** — `extract_sido` 복사본을 없애고
`normalizer`의 것을 재노출하도록 바꿨다. 그 변경의 주석이 위험을 정확히 적어 두었다:
"복사본을 그대로 뒀다면 크롤 데이터는 제주로 저장되는데 검증은 세종으로 판정하는 상태가
됐을 것이다." **검사 0건 상태에서 판정 로직을 건드린 것**이 이 파일을 만든 직접적 이유다.

**[결과] 제품 결함은 없었다.** 네 규칙이 전부 올바르게 동작한다. `test_validation_engine.py`
신규(62검사)로 고정했다 — DB/네트워크/selenium 무의존, 로그는 임시 디렉터리만 사용.

```
필수 필드 4종 x 빈문자열/"-" 두 형태   크롤러가 "-"를 기본값으로 넣으므로 둘 다 누락이어야 한다
지역 불일치 + 인접 허용 11쌍 전수      선언된 인접 쌍이 실제 판정과 일치하는가(양방향)
가격 경계값                            정확히 tolerance면 PASS / 1원 넘으면 FAIL
사건번호 형식 위반 4종 / 정상 3종
로그 실패 격리                         쓸 수 없는 경로에서도 판정은 정상
배치/요약                              accuracy 66.7 / 빈 배치는 0으로 나누지 않는다
```

**[변이 7종 전부 검출]** 인접 허용 제거 / 가격 방향 뒤집기 / **오차 허용 경계 이동** /
정규식 완화 / 필수 필드 검사 제거 / 로그 격리 제거 / PASS-FAIL 반전.

경계값 변이(`> appraisal + TOLERANCE` -> `> appraisal`)가 1건만 잡힌 것은 의도한 설계다 —
경계 검사를 tolerance 정확히/+1원 두 지점에 둔 것이 그 1건을 만들었다. 두 지점 중 하나라도
없었다면 이 변이는 통과했을 것이다.

--------

#80

미구현 PG 메서드가 **사유 없는** `NotImplementedError`를 던져 실패 원인이 통째로 빠졌다

해결 (2026-08-13, Sprint 78)

**[발견 경위]** #79에 이어 커버리지가 지목한 마지막 결제 경로(`api/v1/payments.py` 539-549,
"실연동 전 provider로 환불 시도")를 검증하는 검사를 쓰다가 발견했다. 그 분기의 주석이
지키려는 것은 **돈 안전 불변식**이다 — "PG에서 실제로 환불되지 않았는데 DB만 REFUNDED가
되는 것이 최악의 결과다."

**[실측]** `PAYMENT_PROVIDER=kginicis`로 환불을 시도하니 불변식은 지켜졌다(상태 불변, 원장에
FAILED 기록). 그런데 **사유가 비어 있었다.**

```
payment_logs   status=FAILED  error_message=''        <- 왜 실패했는지 없다
응답 detail    "환불 처리에 실패했습니다: "              <- 콜론 뒤가 비어 있다
```

원인은 `PaymentProvider`의 6개 메서드가 전부 `raise NotImplementedError`(인자 없음)였다는
것이다. `str(e)`가 빈 문자열이라 로그와 응답 양쪽에서 원인이 사라졌다. 같은 파일의
`TossProvider`/`PortOneProvider`는 이미 사유를 담고 있었는데(폐기 안내) **기본 구현만**
빠져 있었고, 확정 PG인 `KGInicisProvider`가 바로 그 기본 구현을 물려받는다.

이 저장소가 진단에 대해 반복해서 지킨 원칙("조용히 넘기면 원인을 추적할 수 없으므로 반드시
남긴다")이 하필 **결제 실패 경로**에서 빠져 있었다.

**[수정]** `_not_implemented(method)` 헬퍼를 두어 **어느 provider의 어느 단계**인지 담는다.

```
NotImplementedError("KGInicisProvider.cancel_payment()는 아직 구현되지 않았습니다 (PG 실연동 대기 중)")
```

provider 교체 전환기에 운영자가 알아야 할 정보가 정확히 그 둘이다. 6개 메서드 전부에
적용되므로 환불·승인·주문·검증·Webhook 어느 경로로 들어와도 사유가 남는다.

**[검증]** `test_api_regression.py` §29에 9검사 추가. 상태 불변은 **특정 값을 기대하지 않고**
시도 전 상태와 비교한다 — 어떤 값이 "결제 완료"인지는 provider가 정하기 때문이다
(Mock은 레거시 `SUCCESS`, 실연동은 `PAID`, `is_paid()`가 둘 다 인정). 처음에 `"PAID"`를
하드코딩해 FAIL이 났고, 그것은 제품이 아니라 **검사의 잘못된 가정**이었다.

누적 환불액 오염도 함께 본다 — 실패 기록이 잔액을 깎으면 나중에 진짜 환불이
"환불 가능 금액 초과"로 막힌다. provider를 mock으로 되돌린 뒤 전액 환불이 되는 것으로 확인했다.

변이 2종 검출: 사유 메시지 제거 / **실패인데 REFUNDED로 바꾸기**(최악의 결과) 전부 FAIL.

**[계약 자체도 고정했다]** `test_api_regression.py` §12의 기존 검사는 6개 메서드가 **예외를
내는지**만 봤다 — 그래서 사유가 비어 있어도 통과했다. 사유가 실제로 담기는지까지 보게 넓혔고,
기본 구현이 **어느 클래스의 어느 단계**인지 담는 것은 하위 클래스가 메시지를 덮어써도 유지돼야
하므로 `PaymentProvider` 기본 구현을 직접 확인한다(빈 서브클래스로 6개 메서드 전수).

`KGInicisProvider.charge`만은 자체 메시지("KG이니시스 실연동 미구현 (계약/API Key 발급 대기)")를
갖고 있어 클래스명 대신 브랜드명이 들어간다 — 처음에 클래스명을 요구해 FAIL이 났고, **계약의
본질은 "운영자가 어느 PG인지 식별할 수 있는가"**이므로 둘 중 하나면 통과하도록 조정했다.

변이 3종 추가 검출: 기본 구현 사유 제거 / 단계 이름 누락 / **KGInicis charge가 조용히 성공**
(실연동 전에 결제가 성공한 것처럼 보이는 최악의 경로). 커버리지 54% -> **99%**.

**[함께 확인한 것]** Admin 실패 응답은 envelope(`error`)가 아니라 `HTTPException(detail)`이다
(`api/v1/admin.py` 상단의 기존 결정). 검사를 쓰며 envelope를 기대해 FAIL이 났고, 문서화된
경계를 다시 확인한 셈이다 — 이것도 제품이 아니라 검사의 가정 오류였다.

--------

#81

검색 화면이 **면적/특수조건 필터를 걸었다고 보여주지만 백엔드는 읽지 않는다**

미해결 — 구현은 승인 사항, 회귀 가드만 설치 (2026-08-13, Sprint 85)

**[발견 경위]** TODO/FIXME 전수 탐색에서 `src/app/search/SearchForm.tsx`의
`TODO(API 미지원)` 주석 3개를 보고 실제 동작을 실측했다. 주석은 "백엔드가 읽지 않는다"고만
적혀 있었고, 그래서 **사용자에게 무엇이 보이는지**는 아무 곳에도 적혀 있지 않았다.

**[실측 2026-08-13]** `/api/v1/search?sido=서울` 275건 기준.

```
min_building_area=9999999   -> 200, 275건 (그대로)
max_building_area=1         -> 200, 275건 (그대로)
min_land_area=9999999       -> 200, 275건 (그대로)
max_land_area=1             -> 200, 275건 (그대로)
special_conditions=유치권   -> 200, 275건 (그대로)
bogus_param=1               -> 200, 275건 (그대로)   <- unknown 파라미터는 전부 무시된다
min_bid_rate=0.9            -> 200, 0건   (반영됨)   <- 대조군: 지원되는 필터는 걸린다
```

즉 프론트는 값을 실어 보내고, FastAPI는 선언되지 않은 쿼리 파라미터를 조용히 버린다.
결과 목록은 필터가 걸린 것처럼 보이지만 **전혀 걸러지지 않은 목록**이다. URL에는
`min_building_area=30`이 남아 있어 새로고침·공유 후에도 같은 오해가 이어진다.

**[왜 지금 구현하지 않는가]** `auction_item`에 면적 컬럼이 없다. 구현에는 (a) 스키마 변경,
(b) 크롤러의 면적 추출, (c) 정규화 규칙(㎡/평, 집합건물 전유면적 vs 대지권)이 함께 필요하다 —
셋 다 승인 사항이라 이 Sprint에서 결정하지 않는다. 화면에서 입력을 감추는 것도 제품 결정이다.

**[대신 한 것 — 양방향 드리프트 가드]** `test_search.py` §6에 12검사 추가.

- 지금 **무시된다는 사실**을 건수 불변으로 고정한다. 대조군(`min_appraisal`이 실제로 0건을
  만든다, 기준 검색이 0건이 아니다)을 함께 둬서 "무시된다"가 "필터가 전부 죽었다"와
  구별되게 했다 — 대조군이 없으면 공허한 검사가 된다.
- **400/422로 깨지지 않는 것**도 함께 고정한다. 프론트가 이미 보내고 있으므로, 백엔드가
  unknown 파라미터를 거부하도록 바뀌면 검색 자체가 죽는다.
- 백엔드 `search.py`에 그 이름이 생기면(=구현되면) 검사가 실패한다. 프론트 TODO와 이
  기대값을 함께 정리하라는 신호다. 조용히 어긋난 채 남지 않게 한다.
- 프론트가 더 이상 그 파라미터를 보내지 않게 되면 그것도 실패로 알려준다(목록 노후화 방지).

--------

#82

`init_db()`의 **옛 스키마 보완 분기 4개가 한 번도 실행되지 않은 채** 남아 있었다

검증 완료 (2026-08-13, Sprint 85) — 제품 결함은 없었고, 대신 문서화되지 않은 한계를 확정했다

**[발견 경위]** 미검증 코드 경로 탐색. `storage/database.py:init_db()`에는 과거 실행분 DB를
위한 분기가 4개 있다(`has_status_pdf` -> `has_status_doc` RENAME / `has_*` 칼럼 추가 /
`document_queue.item_no` 추가 / `document_version_log.item_no` 추가). 운영 DB는 이미 전부
반영돼 있어 **평소에 한 줄도 실행되지 않는다** — 부트스트랩이 매 실행 호출되는데도 검사 0건이었다.

**[검증]** `test_schema_hygiene.py` §10에 18검사 추가. 옛 스키마 DB를 픽스처로 만든다.
옛 DDL을 복사해 두면 현재 DDL이 바뀔 때 같이 낡으므로, **살아 있는 상수에서 파생**시켰다
(현재 DDL에서 나중에 추가된 칼럼만 걷어낸다).

확인한 것: 이미 수집된 표시(`has_status_pdf=1`)가 RENAME으로 **보존**된다 / 새 칼럼은 0으로
채워진다 / 큐의 기존 행 `item_no`이 NULL이 아니라 `'1'`로 채워진다 / 이력 로그 `item_no`은
NULL 허용 / 두 번 실행해도 값이 되돌아가지 않는다 / 신규 DB는 처음부터 올바른 제약으로 생성된다.

RENAME 대신 ADD COLUMN을 했다면 이미 수집한 문서 표시가 전부 0으로 돌아가 같은 문서를 다시
받는다(크롤 부하 + 큐 소진). `NOT NULL DEFAULT '1'` 없이 `item_no`을 추가했다면 기존 큐 행이
NULL이 되어 `(court, case, item_no)` 조회에서 사라진다. 둘 다 변이로 재현해 검출을 확인했다.

**[함께 확정한 한계]** `init_db()`는 **UNIQUE 제약을 고치지 못한다**(SQLite에 제약만 바꾸는
ALTER가 없다). 옛 DB를 init_db()만으로 최신화하면 `document_queue`의 UNIQUE에 `item_no`이
빠진 상태로 남고, enqueue가 `INSERT OR IGNORE`이므로 **같은 사건의 물건번호 2번이 조용히
버려진다**(에러도 나지 않는다). 그래서 migration 018이 반드시 필요하다 — 이 순서를 검사로
고정했다(018 파일 존재까지 확인).

**[변이 7종 중 6종 검출 / 1종은 결함이 아님]** 분기 5개 제거 변이는 모두 FAIL.
`conn.commit()` 제거 변이는 잡히지 않으며 **실제로 아무 차이도 없다** — init_db() 본문은 전부
DDL이고 sqlite3 모듈은 DDL에 트랜잭션을 열지 않으므로 이미 확정돼 있다. 잡을 수 없는 종류라
검사를 늘리지 않고 근거를 주석에 남겼다(나중에 DML이 들어오면 그때는 의미가 생긴다).

**[하네스 결함 1건 수정]** "RENAME 후 칼럼 목록 갱신 제거" 변이가 `duplicate column name`
예외로 **테스트를 죽여** FAIL 집계에서 사라졌다(크래시는 결함을 숨긴다). `init_db()` 호출을
감싸 예외를 FAIL로 바꾸고, 없는 칼럼을 읽을 때도 `<칼럼 없음>`이라는 값으로 취급하게 했다.
재실행 결과 같은 변이가 8건의 FAIL로 나타난다.

--------

#83

`auction.has_*` 레거시 플래그와 화면 테이블이 **35건 어긋나 있다**(화면 쪽이 옳다)

측정 완료 (2026-08-13, Sprint 85) — 사용자 영향 없음, 되살아나지 않게 가드 설치

**[발견 경위]** `storage/database.py:query()`의 호출 경로를 추적하다가(유일한 호출자는
`ALLOW_LIVE_CRAWL` 가드로 회귀에서 제외된 `test_db.py`) 레거시 `auction` 테이블의 문서
플래그가 화면 테이블(`document_status`)과 맞는지 실측했다.

**[실측 2026-08-13]**

```
                auction 플래그=1   document_status READY   플래그만   READY만
SPEC                 197                   197                1         1
APPRAISAL            197                   197                1         1
STATUS               195                   162               33         0
```

어긋난 35건을 **디스크 실물로 하나씩 확인**했다: "플래그만" 34건은 전부 파일이 없고,
"READY만" 1건은 파일이 있다. 즉 **어긋난 35건 전부에서 옳은 쪽은 `document_status`다**.
2026-08-11 Sprint 55(#50)에서 화면 테이블을 디스크 기준으로 1회 보정하고 이후 수집은
`mark_queue_done()`이 두 곳을 한 트랜잭션에서 함께 갱신하도록 고친 결과와 일치한다
(그 동시 갱신은 `test_document_status_sync.py`가 이미 검사한다).

`auction`과 `auction_item`의 키 집합은 **완전히 일치**한다(양방향 차집합 0건, 1,876건).
드리프트는 문서 플래그 값에만 있다.

**[사용자 영향 없음의 근거]** `api/` 어디에서도 이 플래그를 읽지 않는다(전수 스캔).
읽는 곳은 크롤 경로(`normalizer`, `models/auction_item.py`)와 1회성 마이그레이션 스크립트뿐이다.

**[대신 한 것]** `test_schema_hygiene.py` §11 — `api/` 소스가 세 플래그를 참조하면 FAIL.
편의상 다시 읽기 시작하면 "파일이 있는데 수집중으로 보이거나 없는데 있다고 보이는" #50이
그대로 되살아난다. 함께 플래그가 **아직 수집 경로에 존재하는지**도 확인한다 — 그게 없으면
이 검사는 "플래그가 아예 사라진 상태"와 구별되지 않아 의미를 잃는다. 스키마에서 지우는 것은
승인 사항이라 하지 않았다.

--------

#84

다운로드 완료 판정(`wait_for_download()`)이 **검사 0건**이었다

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, 규칙을 픽스처로 고정

**[발견 경위]** `crawler/doc_crawler.py`에서 selenium에 의존하지 않는 순수 함수 중 유일하게
검사가 없던 경로다(Sprint 85 roadmap 후보 1번). 브라우저 없이 `DOWNLOAD_DIR`만 바꿔 끼우면
검증할 수 있는데도 남아 있었다.

이 판정이 틀리는 방식은 두 가지고 둘 다 무겁다. **너무 이르게 성공**하면 받는 중인 파일을
최종 문서로 저장하고(`doc_exists()`는 0바이트만 보므로 잘린 PDF가 "완료"로 굳는다 — Sprint 40이
원자적 쓰기로 막은 것과 같은 계열), **영원히 실패**하면 정상 다운로드를 놓쳐 큐를 소진한다.

**[검증]** `test_doc_storage_atomicity.py` §8에 8검사 추가. `time.sleep`을 대역으로 바꿔
호출마다 파일 상태를 진행시킨다(실제 시간을 흘리지 않고 폴링 루프의 의미를 그대로 밟는다).
새 파일 없음 -> None / PDF가 아닌 새 파일 -> None / 0바이트 -> None / 계속 자라면 미완료 /
안정되면 그 경로 반환 / `before_files`의 파일은 후보가 아니다.

**[변이 8종 중 7종 검출]** "연속 2회 -> 1회" 변이를 잡으려면 **반환 시점의 파일 크기**를
봐야 한다(경로만 비교하면 두 경우가 같은 파일이라 구별되지 않는다). 크기 대본을 **두 번
쉬었다 다시 자라는** 모양(10,10,20,20,30,40,40,40)으로 짜야 "안정 카운터를 리셋하지 않는"
변이까지 잡힌다 — 한 번만 쉬는 대본에서는 그 변이가 살아남았다(실측 후 대본을 고쳤다).
`.pdf` 확장자 필터 제거 변이도 처음엔 살아남아, "PDF가 아닌 새 파일"(법원이 PDF 대신 오류
안내 페이지를 내려주는 경우) 검사를 추가해 잡았다.

**[살아남은 1종은 결함이 아니다]** `.crdownload` 제외 줄을 지워도 검사는 통과한다. 그 다음
줄의 `.pdf` 확장자 필터가 이미 같은 것을 걸러내기 때문이다("doc.pdf.crdownload"는 `.pdf`로
끝나지 않는다) — 어떤 파일명도 두 조건을 동시에 만족할 수 없으므로 **효과가 없는 이중 방어**임이
증명된다. 나중에 후보 조건이 확장자 대신 mtime 등으로 바뀌면 그 줄이 유일한 방어가 되므로
지우지 않고 사실만 주석에 남겼다.

--------

#85

Admin 등기부 상태 전이의 **409 분기가 행동으로는 검증되지 않았다**

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, 확률에 기대던 검사를 결정적으로 대체

**[발견 경위]** 이 분기의 근거는 (a) 확률적 2스레드 재현과 (b) 소스 문자열 검사 두 개뿐이었다
(2026-08-11 실측: 2스레드 3/4, 6스레드 1/5 — 창이 수 마이크로초라 스레드로는 안정 재현 불가).
둘 다 **"실제로 409를 돌려주고 앞선 관리자의 결과를 보존하는가"**는 확인하지 못한다.

**[검증]** `test_race_conditions.py` §14에 8검사 추가. 스레드로 창을 기다리는 대신
**커넥션을 감싸 창을 직접 벌린다** — `UPDATE registry_requests`를 대행하기 바로 전에 다른
커넥션으로 상태를 COMPLETED(+doc_url)로 확정한다. sqlite3 모듈은 SELECT로 트랜잭션을 열지
않으므로 락 없이 끼어들 수 있고, 이것이 TOCTOU 창의 실제 모습이다. 확률이 개입하지 않는다.

확인한 것: 진 쪽은 409 / 사유에 기대했던 현재 상태가 담긴다 / 먼저 반영된 상태와 doc_url이
보존된다 / **진 쪽의 reason이 섞여 들어가지 않는다** / 대조군(끼어들기 없음)은 같은 요청이 200.
대조군이 없으면 409가 "끼어들기 때문"인지 "요청 자체가 잘못돼서"인지 구별되지 않는다.

**[변이 3종 전부 검출]** 조건부 WHERE 제거 / rowcount==0 거부 제거 / 409 -> 200. 첫 변이에서는
**발급된 등기부 URL이 덮이고 진 쪽의 실패 사유가 섞여 들어가는** 것까지 그대로 재현됐다 —
가드가 지키는 손실이 무엇인지 검사가 직접 보여준다.

**[측정 코드 자체의 오답 1건]** 변이 스크립트가 파일을 **바이너리로 읽어** 여러 줄 패턴에
`\n`을 쓴 탓에 CRLF 파일(`api/v1/admin.py`)에서 0곳 일치했고, 변이가 적용되지 않은 채
"SURVIVED"로 보였다. 패턴 일치 수가 1이 아니면 즉시 표시하도록 해 둔 덕에 드러났다 —
변이 테스트에서 **적용 여부를 확인하지 않으면 통과가 거짓 안심이 된다.**

--------

#86

문서 뷰어의 **경로 탈출·NULL 경로 방어에 검사가 0건**이었다 (그리고 기존 테스트가 이 결함을
FAIL이 아니라 크래시로 만들었다)

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, 방어가 실제로 막는 것을 실증

**[발견 경위]** 커버리지가 `api/v1/documents.py`의 두 줄을 지목했다 — 48행(경로를 만들 수
없는 행은 404)과 58행(계산된 경로가 `DOCUMENT_ROOT`를 벗어나면 차단). 둘 다 **방어 코드인데
검사가 없었다.** 방어 코드는 리팩터링 때 조용히 사라지고, 사라진 사실은 사고로만 드러난다.

**[검증]** `test_api_regression.py` §34에 13검사 추가. 운영 테이블에 `..`가 든 행을 만들지
않는다(위험하고 정리 실패 시 흔적이 남는다) — 커넥션만 메모리 DB로 갈아끼운다.

가장 중요한 설계 판단: **탈출 경로에 실제로 존재하는 파일을 둔다.** 파일이 없는 탈출만
검사하면 "가드가 막았다"와 "파일이 없어서 404"가 구별되지 않는다(가드를 지워도 통과한다).
`os.path.join`은 두 번째 인자가 절대경로면 앞을 버리므로, `court_name`에 절대경로를 넣으면
`DOCUMENT_ROOT`를 즉시 벗어난다. 그 위치에 `%PDF-1.4 QA-SECRET-SHOULD-NOT-LEAK`을 둔 뒤
응답 본문에 그 내용이 없는지 본다. GET과 HEAD 양쪽을 확인한다(프론트는 뷰어를 열기 전에
HEAD로 확인한다 — 방어가 한쪽에만 있으면 HEAD로 존재 여부를 떠볼 수 있다).

**[변이 3종 전부 검출 — 그중 하나는 유출을 실제로 재현했다]**

```
경로 탈출 가드 제거   -> 200 + 본문 b'%PDF-1.4 QA-SECRET-SHOULD-NOT-LEAK'   (파일 유출)
NULL 경로 가드 제거   -> 서버 예외(상태코드 없음)                            (500)
doc_type 400 검사 제거 -> 400이어야 할 요청이 예외로 끝난다
```

**[함께 고친 하네스 결함]** 세 번째 변이는 처음에 **FAIL 0건 + 스위트 크래시**로 끝났다.
원인은 §34가 아니라 **기존 §3**이었다 — `client.get(...).status_code`를 그대로 쓰는 줄이
있어, 서버가 예외를 던지면 TestClient가 그것을 올려 스위트가 그 자리에서 죽었다(결함이
집계에서 사라진다). 그 호출을 감싸 예외를 `None`으로 바꿨다. 단언은 그대로다 — 오히려
`None`은 어떤 기대값과도 맞지 않으므로 검출력이 올라간다. 재실행 결과 같은 변이가 2건의
FAIL로 나타난다.

--------

#87

관심물건 등록 실패를 "이미 등록됨"으로 오해하지 않는지 **검사가 없었다**

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, 과거 결함의 회귀 가드 설치

**[발견 경위]** 커버리지가 `api/v1/favorites.py` 57-59행(중복 위반이 **아닌** 예외는 감추지
않고 올린다)을 미커버로 지목했다. 이 분기는 과거의 실제 결함을 고친 자리다 — 예전에는
`except Exception`으로 전부 잡아 DB 잠금/디스크 오류까지 "이미 관심물건으로 등록되어
있습니다"로 안내했다. 사용자는 등록됐다고 믿고 떠나고, 운영자는 오류를 볼 수 없다.
**고쳤다는 기록은 있는데 그 수정을 지키는 검사는 없었다.**

**[검증]** `test_api_regression.py` §35에 6검사 추가. `INSERT INTO favorites`만
`IntegrityError`가 **아닌** 오류(`database is locked`)로 실패시킨다. 확인: 성공으로 응답하지
않는다 / "이미 등록" 안내로 감추지 않는다 / 오류가 드러난다(예외 또는 5xx) / 롤백한다 /
**DB에 행이 남지 않는다**(응답만 보고 판단하지 않는다) / 대조군으로 정상 경로는 200.

**[변이 2종 전부 검출]** `except sqlite3.IntegrityError` -> `except Exception`(과거 결함
재현)에서 응답이 `FAVORITE_ALREADY_EXISTS` + 200으로 돌아왔고, 롤백 제거도 잡혔다.

--------

#88

READY가 **뷰어가 실제로 열 수 있는 상태인지**는 어떤 검사도 보지 않았다

검증 완료 (2026-08-13, Sprint 85) — 실측 결과 어긋남 0건, 계약으로 고정

**[발견 경위]** "완료" 판정과 "서빙" 대상이 **서로 다른 파일**이라는 것을 확인하면서 나왔다.

```
doc_exists() / 보정 스크립트   status.json 을 기준으로 READY를 판정한다
api/v1/documents.py            status.html 을 사용자에게 내려준다
```

`collect_status()`가 둘을 함께 쓰므로 지금은 어긋나지 않는다. 하지만 한쪽만 남는 경우(html
쓰기 실패, 정리 스크립트가 html만 지움, 규칙이 갈라짐)에는 화면이 "완료"라고 말하고 뷰어가
404를 준다. `repair_document_status.py`의 주석이 정확히 그것을 경계한다("여기서 규칙이
갈라지면 READY인데 뷰어는 404가 된다"). 그런데 **기존 일관성 검사는 판정 쪽 파일(json)만
봤다** — 이 갈라짐은 어디에도 걸리지 않았다.

**[실측 2026-08-13]** READY 556행(SPEC 197 / APPRAISAL 197 / STATUS 162) 전부 **뷰어가
서빙하는 파일 이름 그대로** 확인해 존재하고 0바이트가 아니다. STATUS 162행은 json/html이
둘 다 있다. 어긋남이 0이므로 "측정 가능"이 아니라 **0건**을 계약으로 뒀다.

**[검증]** `test_document_status_sync.py` §11에 8검사 추가. 뷰어의 매핑·경로 계산을
**그대로 import해서** 쓴다(여기서 규칙을 복사해 적으면 갈라져도 통과한다). 함께 고정한 것:
크롤러가 저장하는 파일명(`CANONICAL_DOC_FILENAME`) == 뷰어가 서빙하는 파일명 —
갈라지면 크롤러는 저장에 성공하고 뷰어는 영원히 404를 준다.

**[변이 5종 전부 검출]** 뷰어가 STATUS를 pdf/json으로 서빙 / 뷰어 경로에서 item_no 제거
(556행 전부 서빙 불가) / 크롤러 저장 파일명만 변경 / 판정 기준을 pdf로 되돌림(#22 계열).

**[검사의 가정 오류 1건(기록)]** 처음엔 판정 파일을 `CANONICAL_DOC_FILENAME`에서 읽어
`status.json`을 기대했는데 그 상수는 `status.html`이다. 판정은 `_PRIMARY_EXT`가 한다 —
제품이 아니라 **검사의 가정이 틀렸다**(FAIL로 즉시 드러났다).

--------

#89

"조용히 넘어가는 실패 경로" 3곳이 미검증이었다 (부트스트랩 / 체크포인트 / 상태 조회)

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, 삼키는 코드에 근거를 붙였다

**[발견 경위]** 커버리지에 남은 마지막 실패 경로들이다. 세 곳 모두 **의도적으로 조용한**
코드라서, 조용함이 옳은 이유와 그 대가(로그·데이터 보존)를 검사로 못 박아야 한다.

**1) `init_db()`의 `except` (재전파 + ERROR 로그)** — `test_schema_hygiene.py` §12, 6검사.
DB 파일 자리에 DB가 아닌 파일을 두면 첫 DDL에서 실패한다(디스크 손상과 같은 계열).
부트스트랩 실패를 삼키면 이후 모든 작업이 "테이블이 없다"는 엉뚱한 오류로 실패하고 진짜
원인은 사라진다. 확인: 예외 전파 / ERROR 로그 / 로그에 사유가 담긴다(빈 메시지가 아니다) /
**대상 파일을 변형하지 않는다**(남의 파일을 덮으면 원인 조사조차 못 한다).
변이 3종 전부 검출(삼킴 / 로그 제거 / 사유 없는 로그).

**2) `CheckpointManager.save()/clear()`의 `except`** — `test_checkpoint_atomicity.py` §4,
8검사. 이 삼킴은 옳다: 체크포인트는 "다음 실행의 편의"이고, 그 저장 실패로 **이미 성공한
60개 법원 순차 크롤을 중단시키면 손해가 더 크다**. 대가로 (1) 예외가 나가지 않고 (2) ERROR
로그가 남고 (3) **기존 파일이 망가지지 않는지**를 고정했다. (3)이 핵심이다 — 실패한 저장이
기존 내용을 반쯤 덮으면 다른 법원의 진행 상황까지 사라진다(Sprint 42가 막은 사고 그 자체).
변이 3종 전부 검출.

**3) `_current_document_status()`의 "모르면 None" 두 갈래** — `test_document_status_sync.py`
§12, 7검사. `reset_stale_queue()`가 조건부 복구("지금 FAILED인 행만 되돌린다")에 쓰는 조회다.
모르는 값에 예외를 던지면 큐 복구 전체가 멈추고, 아무 값이나 지어내면 **이미 READY인 문서를
COLLECTING으로 덮어 볼 수 있는 문서를 화면에서 가린다**. 그래서 "모르면 None"이 정답이다.
큐 표기는 소문자 계약이므로 `"SPEC"`(대문자)도 모르는 값으로 취급되는 것까지 고정했다.

**[측정 코드 자체의 오답 1건 — 이번 세션 네 번째]** 같은 파일을 **길이가 같게** 변이하면
`__pycache__`의 `.pyc`가 재사용되어 **앞 변이의 결과가 다음 변이의 증거로 보고된다**(pyc
무효화는 소스의 mtime+크기로 판단한다). 실제로 `_PRIMARY_EXT` 변이의 FAIL 메시지가 직전
변이의 값을 담고 있었다. 변이 실행을 `-B`(바이트코드 미생성)로 바꿔 재현이 사라지는 것을
확인했고, 이전에 SURVIVED로 판정한 2종(`.crdownload` 제외 / `init_db`의 `commit`)도 `-B`로
다시 돌려 **크기가 다르므로 캐시 영향이 없었음**을 확인했다 — 두 판정은 그대로 유효하다.

--------

#90

결제·Webhook의 **실패/멱등 분기 7곳**이 미검증이었다 (그중 둘은 내 검사가 헛돌았다)

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, 돈 관련 멱등의 위험 지점을 고정

**[발견 경위]** 커버리지가 `api/v1/payments.py`에 남긴 미커버 중 **Mock Provider로 도달
가능한** 실패 분기를 모두 골랐다(실연동은 계속 SKIP). 돈이 걸린 코드라 우선순위를 가장
높게 뒀다. `test_api_regression.py` §36에 30검사 추가. 커버리지 92% -> **95%**.

**[가장 중요한 발견 ― 내 기대가 틀렸다]** 처음에 "전액 환불 뒤 두 번째 환불은 거절된다"로
썼는데 200이 왔다. 제품이 아니라 **검사의 가정이 틀렸다** — `refund_payment()`는 이미
REFUNDED인 결제에 다시 요청이 오면 `already_refunded=True`, 환불액 0으로 돌려준다(등기부
`already_requested`, 구독 `already_subscribed`와 같은 규약이다).

그래서 검사의 방향을 바꿨다. 돈 관련 멱등에서 진짜 위험은 "거절하지 않는 것"이 아니라
**원장을 두 번 계상하는 것**이다. 멱등 성공이 환불을 한 번 더 적으면 총 환불액이 결제액의
2배가 되고 그 뒤로는 정산이 영구히 어긋난다. 그래서 고정한 것:

```
멱등 응답        already_refunded=True / refunded_amount=0 / total_refunded == 결제액
원장             CANCEL+SUCCESS 기록이 정확히 1건, 합계가 결제액 그대로
감사 로그        멱등 재요청은 늘리지 않는다(admin.py가 already_refunded를 보고 건너뛴다)
```

`get_refunded_amount()`가 항상 0을 돌려주는 변이(이중 환불 허용)를 넣으면 7건이 FAIL한다.

**[동시 환불: 못 태우는 분기를 억지로 태우지 않고 방향을 바꿨다]** 557행(조건부 UPDATE의
rowcount 검사)을 §14처럼 결정적으로 태우려 했는데, 커넥션을 감싸 끼어들기를 시도하니
**끼어든 쪽이 쓰기를 하지 못했다**. 이유가 곧 답이다 — `refund_payment()`는 진입 직후
`BEGIN IMMEDIATE`로 쓰기 락을 선점하므로 같은 프로세스/같은 DB에서는 조회와 UPDATE 사이에
다른 쓰기가 끼어들 수 없다. 557행은 **락 뒤의 이중 방어**다.

그래서 검사를 "1차 방어선이 실제로 직렬화하는지"로 바꿨다 — 끼어든 쓰기가
`database is locked`로 막히는 것이 `BEGIN IMMEDIATE`가 살아 있다는 실행 증거다(이것도
지금까지 소스 문자열 검사밖에 없었다). `BEGIN IMMEDIATE`를 지운 변이를 넣으면 끼어들기가
성공하고(`wrote`), **그 다음에 557행이 발동해 409가 된다** — 두 방어선이 층으로 쌓여 있음이
그대로 드러난다(4건 FAIL).

래퍼를 쓸 때 걸린 함정 하나: `refund_payment()`가 `conn.isolation_level = None`을 설정하는데
`__getattr__`만 위임하면 **대입은 래퍼에 붙어** 실제 커넥션의 트랜잭션 모드가 바뀌지 않는다
(그러면 제품이 아니라 래퍼를 시험하게 된다). `__setattr__`도 위임해야 한다.

**[Webhook 분기 ― 두 검사가 헛돌고 있었다]** `event_type="payment.paid"`로 보낸 검사 두 개가
통과했지만, **무시된 이유가 달랐다**. Mock의 매핑표(`WEBHOOK_EVENT_STATUS`)에 없는 이름이라
status가 빈 문자열이 되어 더 앞의 분기에서 걸렸고, 검사하려던 분기(pg_transaction_id 없음 /
같은 상태)에는 **도달조차 못 했다**. 커버리지가 그 사실을 드러냈다(해당 줄이 그대로 미커버).
실제 event_type(`PAYMENT_CONFIRMED` / `PAYMENT_REFUNDED`)으로 고쳐 세 분기를 실제로 태웠다:

```
모르는 event_type          200 + 무시 (Sprint 52가 고친 "항상 SUCCESS" 결함의 회귀 가드)
pg_transaction_id 없음     200 + 무시, 사유에 그 이름이 담긴다
같은 상태 재통지            200 + "이미 동일한 상태" — 상태도, 원장도 늘지 않는다
```

**[나머지 확인]** Webhook payload 해석 불가(400, 행을 만들지 않는다) / 재처리 시 알 수 없는
provider(400) / 저장된 payload 해석 불가(400). 재처리 가능 상태는 `RECEIVED`/`IGNORED`뿐이라
픽스처를 `PENDING`으로 만들었더니 다른 사유로 먼저 걸렸다 — 이것도 제품이 아니라 픽스처의
잘못이었다(FAIL로 즉시 드러났다).

**[남은 미커버는 도달 불가이거나 호출부가 없다]**

```
557-558행   BEGIN IMMEDIATE 뒤의 이중 방어 — 같은 프로세스에서는 락을 우회할 수 없다
            (락을 지운 변이에서 발동하는 것으로 살아 있음을 확인했다)
514행       "잔액 0인데 상태는 REFUNDED가 아님" — 부분환불 합이 전액이 되면 그 요청이
            REFUNDED로 만들기 때문에 API 경로로는 만들 수 없는 방어 코드
497-498행   user_id를 주는 소유권 확인 경로 — 지금 호출자는 Admin뿐이다(주석에 명시돼 있다)
420-422행   결제 생성 트랜잭션의 예외 롤백 — 주입으로 도달 가능하나 이번에는 하지 않았다
            (다음 Sprint 후보)
```

--------

#91

결제 생성이 중간에 실패했을 때 **결제 행만 남는지**는 검사가 없었다

검증 완료 (2026-08-13, Sprint 85) — 제품 결함 없음, "돈은 받았는데 이용권이 없는" 상태를 가드

**[발견 경위]** `api/v1/payments.py` 420-422행(`except Exception: rollback; raise`)이
마지막 남은 주입 가능 미커버였다. 이 트랜잭션은 **결제 기록 -> 구독 생성 -> 등기부 신청
연결**을 한 묶음으로 처리한다. 중간에서 실패했는데 앞 단계가 남으면 사용자에게 가장 나쁜
형태의 절반 반영이 된다 — **돈은 받았는데 이용권이 없다.**

**[검증]** `test_api_regression.py` §37에 8검사 추가. 구독 INSERT만 실패시킨다(디스크 오류
흉내). 확인: 성공으로 보이지 않는다 / 오류가 드러난다 / 롤백한다 / **결제 행이 남지 않는다** /
구독도 없다 / 원장에 성공 기록도 없다 / 대조군(주입 해제)에서는 결제와 구독이 **함께** 생긴다.
커버리지 95% -> **96%**.

**[정직하게 남긴 사실]** `conn.rollback()`을 지운 변이에서도 **결제 행은 남지 않았다** —
커밋 없이 `close()`하면 sqlite가 암묵적으로 되돌리기 때문이다(데이터는 두 겹으로 안전하다).
그래서 이 변이를 잡은 것은 "rollback이 호출됐는가" 검사다. 구현을 시험하는 검사에 가깝지만
유지할 이유가 있다: 커넥션을 재사용/풀링하는 구조로 바뀌는 순간 암묵적 롤백은 사라지고,
그때 데이터를 지키는 것은 명시적 롤백뿐이다. 그 사실을 검사 주석에 근거로 남겼다.

--------

#93

등기부가 **"발급 완료"로 표시되는데 다운로드는 404** ― 관리자가 파일명을 오타내도 전이가 성공했다

해결 (2026-08-13, Sprint 95)

**[발견 경위]** 등기부 다운로드 방어 매트릭스를 채운 뒤, 요청받은 대로 **lifecycle 전체에서
DB 상태와 실제 파일이 어긋날 수 있는지**를 거슬러 올라갔다. 다운로드 쪽(읽기)은 방어가
촘촘한데 **연결 쪽(쓰기)에는 검사가 없었다.**

**[원인]** `admin.py`의 COMPLETED 전이는 `doc_url`이 **비어 있지 않은지만** 확인했다.

```python
if req.status == "COMPLETED" and not req.doc_url:
    raise HTTPException(400, "COMPLETED 처리에는 doc_url이 필요합니다")
```

파일이 실제로 있는지는 보지 않는다. `registry_documents/`는 운영자가 손으로 파일을 두는
디렉터리이고 `doc_url`도 손으로 입력하므로, **오타 하나면 어긋난다.**

**[재현 ― 실측]**

```
Admin PATCH status=COMPLETED, doc_url="does-not-exist.pdf"   -> 200 성공
DB                        status=COMPLETED                   -> 저장됨
사용자 상세 화면             "발급 완료"                        -> 보인다
사용자 다운로드              404 "문서 파일을 찾을 수 없습니다"    -> 받을 수 없다
```

**[왜 중요한가]** `docs/BUGS.md` #50/#65와 같은 부류다 ― "완료"로 표시되는데 실제로는
못 쓰는 상태. 다만 **이쪽이 더 나쁘다.**

```
크롤러 경로(#50/#65)  재시도가 있어 스스로 회복한다
등기부 경로(이번)      자가 복구가 없다 - 운영자가 알아채기 전까지 그 사용자는 계속 404
```

게다가 등기부는 **유료 서비스**다. 사용자는 돈을 내고 "발급 완료"를 본 뒤 받지 못한다.

**[수정]** COMPLETED 전이 시 `doc_url`이 **실재하는 파일**인지 확인한다. 검사 방식은
다운로드 경로(`registry.py:download_registry()`)와 **똑같이 맞췄다** ― 두 곳이 다른
기준을 쓰면 "등록은 됐는데 못 받는" 상태가 다시 생긴다.

덤으로 **경로 탐색을 쓰기 시점에도 막는다.** 예전에는 읽기 시점에만 막고 있었다.

**[동시 발견 ― 기존 테스트가 결함을 정상으로 굳혀 두고 있었다]**
이 수정을 넣자 기존 검사가 깨졌다. `doc_url="qa-regression-not-a-real-file.pdf"`로
**전이 성공을 기대**하고 있었던 것이다. 바로 아래 줄에 "COMPLETED이지만 실제 파일이 없으면
거짓 성공을 반환하지 않아야 한다"는 검사가 있었으니, **파일이 없다는 사실을 알면서도
읽기 쪽만 막고 쓰기 쪽은 통과를 기대**한 셈이다.

실제 파일을 두고 연결하도록 고쳤고(문서가 안내하는 운영 순서와 같다), "COMPLETED인데 파일
없음"은 **레거시 상태 방어**로 위치를 옮겼다(과거 데이터·수동 복구로는 여전히 생길 수 있다).

**[검증]** 변이 3종. 그중 **경로 탐색 검사 제거는 처음에 검출되지 않았다** ―
`../../../etc/passwd`가 이 환경에 없는 파일이라 "파일 없음" 검사에도 걸렸기 때문이다.
**실재하는** 바깥 파일(`../auction.db` ― `registry_documents/`의 부모가 저장소 루트다)로
바꾸자 검출됐다. 그 검사가 없으면 운영자가 DB 파일을 연결할 수 있고,
**사용자가 DB 전체를 내려받는다.**

--------

#94

**전액 환불한 구독이 그대로 살아 있다** ― 돈은 돌려주고 서비스는 계속 준다

미해결 (2026-08-13, Sprint 96 발견) ― **일부는 정책 결정 대기**

**[실측]** 실제로 재현했다(프로브 행은 실행 후 전부 삭제).

```
BASIC 월 구독 결제        12,900원      payment=SUCCESS  subscription=ACTIVE
SUPER_ADMIN 전액 환불     12,900원      payment=REFUNDED
그 직후 다시 측정         subscription=ACTIVE  expires_at 2026-09-12 그대로
                          GET /subscriptions/me -> ["ACTIVE"]  (화면상 "구독 중")
```

`refund_payment()`는 `payments` 행만 바꾸고 **`subscriptions`는 건드리지 않는다.**
webhook 경로(`_apply_webhook_event`)도 마찬가지로 결제 상태만 바꾼다.

**[같은 계열]** #93(등기부: DB는 발급 완료, 파일은 없음)의 **거울상**이다.
#93은 "돈을 받고 물건을 안 준다", 이쪽은 "돈을 돌려주고 물건을 계속 준다".
두 경우 모두 **DB의 한 쪽 상태만 바뀌고 실제 효과가 따라가지 않았다.**

**[더 근본적인 문제 ― 이건 정책이 아니다]**

고치려 해도 **대상을 찾을 수 없다.** 결제와 구독을 잇는 열쇠가 아예 없다.

```
registry_requests   payment_id 있음      결제 <-> 등기부 신청이 이어진다
subscriptions       payment_id 없음      결제 <-> 구독은 이어지지 않는다
payments            subscription_id 없음
payments.metadata   {"plan": "BASIC"}    플랜만 있고 구독 id는 없다
```

지금 두 행을 맞춰 볼 유일한 방법은 `(user_id, 금액, 생성 시각)` 어림짐작이고,
그것은 식별이 아니다. **어떤 정책을 고르든 이 열쇠가 먼저 있어야 한다** ―
"즉시 해지"든 "기간 만료 시 해지"든 "해지하지 않고 표시만"이든,
전부 "이 결제가 산 구독이 무엇인가"에 답할 수 있어야 실행된다.

**[정책 결정이 필요한 부분]** 전액 환불 시 구독을 어떻게 할 것인가 ―
즉시 해지 / 결제 주기 끝까지 유지 / 일할 계산. 부분 환불은 또 다르다.
`docs/roadmap.md`에 선택지를 정리했다. **임의로 정하지 않았다.**

**[노출 범위]** Admin 환불은 SUPER_ADMIN 전용이고, 사용자 셀프 환불 경로는 없다.
그래서 오늘 임의의 사용자가 이 상태를 만들 수는 없다. 다만 **정상 운영 절차
(환불 요청 처리)가 곧바로 이 상태를 만든다** ― 드문 경로가 아니라 정해진 경로다.

--------

#95

**검색조건 한 행이 손상되면 목록 전체가 500이 되고, 사용자는 빠져나올 수 없다**

해결 (2026-08-13, Sprint 96)

**[실측]** 고치기 전 동작.

```
정상 검색조건 3건 + conditions가 깨진 행 1건
GET /api/v1/search-presets  ->  500 Internal Server Error
                                멀쩡한 3건까지 통째로 사라진다
```

`get_presets()`가 `json.loads(row["conditions"])`를 **아무 방어 없이** 부른다.
반복문 안이라 한 행의 예외가 응답 전체를 무너뜨린다.

**[막다른 길]** 더 나쁜 것은 **사용자가 스스로 복구할 수 없다**는 점이었다.
지우려면 `preset_id`가 필요한데, id를 알 수 있는 유일한 경로가 바로 그 죽은 목록이다.
운영자가 DB를 직접 열어 주기 전까지 그 사용자의 검색조건 기능은 영구히 죽어 있다.
(실측에서 삭제가 200으로 성공한 것은 내가 **DB에서 id를 직접 읽어냈기** 때문이다 ―
사용자에게는 없는 수단이다.)

**[도달 경로]** 정상 API로는 만들 수 없다(POST는 언제나 유효한 JSON을 쓴다).
레거시 행·수동 복구·부분 쓰기로 생길 수 있는 상태다. #93에서 "COMPLETED인데 파일 없음"을
레거시 상태 방어로 남긴 것과 **같은 판단**으로 읽기 쪽을 방어한다.

**[같은 계열]** 저장된 JSON을 해석하는 다른 두 경로는 진작부터 방어하고 있었다.

```
payments.py:646   수신 webhook payload   해석 실패 -> 400
payments.py:784   저장된 payload 재처리   해석 실패 -> 400
search_presets.py:79                     방어 없음 -> 500   <- 여기만 빠져 있었다
```

**[수정]** 행 단위로 감싸고, 실패하면 `{}`로 대체한 뒤 경고를 남긴다.

`None`이 아니라 `{}`인 이유: 프론트가 `preset.conditions[key]`로 읽는다
(`SearchPresets.tsx:139`). `None`이면 거기서 TypeError가 나 화면이 같은 방식으로 죽는다.
`{}`면 "조건 없는 검색"이 되어 무해하고, 무엇보다 **그 행이 목록에 보이므로 지울 수 있다.**

행을 **건너뛰지 않은** 것도 같은 이유다 ― 숨기면 영원히 남으면서 사용자당 상한
(100개)만 갉아먹는다.

**[검증]** 변이 3종 전부 검출(가드 무력화 / 객체 검사 제거 / 손상 행 숨김).
가드를 무력화하면 TestClient가 예외를 되던져 **테스트가 크래시**했다 ―
FAIL 0건에 exit=1이라 무엇이 깨졌는지 알 수 없었다. 호출을 감싸 진단으로 바꿨다.

--------

#96

**물건 행이 사라진 등기부 신청은 관리자 화면에서 통째로 사라진다** ― 사용자는 계속 본다

해결 (2026-08-13, Sprint 97) ― **잠재 결함(현재 실 DB에는 해당 행 0건)**

**[비대칭]** 같은 신청을 두 화면이 다르게 본다.

```
사용자 목록   registry.py:161   SELECT * FROM registry_requests            JOIN 없음 -> 보인다
관리자 목록   admin.py          JOIN auction_item ON rr.item_id = ai.id    INNER    -> 사라진다
```

INNER JOIN이라 물건 행이 없는 신청은 목록에서 빠지고 **`total`까지 같이 줄어든다** ―
무언가 빠졌다는 신호조차 남지 않는다.

**[결과]** 사용자 화면은 "처리 중", 관리자 화면에는 **존재하지 않는다.**
돈을 낸 신청이 영영 처리되지 않고, 관리자는 그런 신청이 있다는 사실조차 모른다.

**[실측]** 실 DB를 건드리지 않고 임시 복사본에서 재현했다.

```
사용자 목록(JOIN 없음)    1건
관리자 목록(INNER JOIN)   0건
LEFT JOIN이면             1건
```

전이(PATCH) 뒤 상세를 다시 읽는 쿼리도 같은 JOIN을 쓴다 ― 거기서는 빈 결과가
응답 조립으로 들어가 `TypeError: 'NoneType' object is not subscriptable`로 **500**이 된다.
회귀 검사가 그 형태까지 함께 잡는다.

**[현재 노출 범위]** 프로덕션 코드에 `auction_item`을 지우는 경로는 **없고**, 런타임
커넥션은 FK를 켠다. 실 DB의 고아 신청도 **0건**으로 확인했다. 다만 011~013처럼
**테이블을 재작성하는 마이그레이션은 FK를 끄고 돌며**(`run_migrations.py:23`),
그때 UNIQUE 정리로 빠지는 행이 생기면 이 상태가 만들어진다.
대비 비용은 `JOIN` 한 단어이고, 놓쳤을 때의 대가는 조용한 영구 방치다.

**[수정]** 관리자 쪽 3개 쿼리(목록 COUNT / 목록 / 전이 후 상세)를 LEFT JOIN으로 바꿨다.
사건번호·주소는 붙일 곳이 없으니 `None`으로 나간다 ― **값을 지어내지 않는다.**

**[검증]** INNER JOIN으로 되돌리는 변이에서 5개 검사가 실패한다(목록 total / 신청 id /
사건번호 / 주소 / 전이 가능 여부). 처음엔 목록이 비어 `got[0]`이 IndexError를 내며
**테스트가 크래시**했고, 앞선 실패까지 묻혔다 ― 빈 자리를 다른 값으로 드러내
크래시를 읽을 수 있는 실패로 바꿨다.

--------

#97

**`doc_raw`가 0행** — 운영 수집 경로에 실체 기록 코드가 아예 없었다

해결 (2026-08-17, Sprint 144)

**[실측]** 디스크에 실제 법원 문서가 **722개(1,313.8 MB)** 있고 `document_status`의
READY도 **556행**인데 `doc_raw`는 **0행**이었다. `parsed_document`도 0행이다.

```
documents/ 실측    appraisal.pdf 198 / spec.pdf 198 / status.html 163 / status.json 163
document_status    READY 556 (SPEC 197 / APPRAISAL 197 / STATUS 162)
doc_raw            0행
```

**[원인]** 쓰는 코드가 **실행되지 않는 경로에만** 있었다.

```
doc_raw에 INSERT하는 코드  ->  collect_documents.py:save_doc_raw()   ← 단 한 곳
그 스크립트를 실행하는 것  ->  없음 (스케줄러 3개 어디에도 없다)
실제로 도는 수집 경로      ->  doc_worker.py → collect_document() → mark_queue_done()
                              ← 여기에는 doc_raw 기록이 없었다
```

BUGS #50이 `has_*_pdf`와 `document_status` 사이에서 고친 것과 **정확히 같은 모양의
결함이 한 층 아래에 하나 더** 있었던 셈이다.

**[결과]** `page_count` / `file_size` / `file_hash` / `doc_version`이 전부 비어 있어
API가 "이 문서 몇 쪽인가"를 답할 수 없었다 — 상세페이지 문서 뷰어의 페이지 이동이
**구조적으로 불가능**했다. 사용자에게는 "기능이 없는 것"으로 보였다.

**[알아채기 어려웠던 이유]** `test_collect_documents.py`의 첫 줄이 이미 "`doc_raw` 0행이라
저장 경로가 한 번도 검증되지 않았다"고 적고 있었다. **증상은 3개 스프린트 전부터 기록돼
있었지만 원인(운영 경로가 다른 함수를 탄다)이 짚이지 않았다.**

**[수정]** `mark_queue_done()`이 같은 트랜잭션에서 `doc_raw`도 쓴다(`_record_doc_raw`).
파일이 실제로 있고 0바이트가 아닐 때만 기록한다 — DB만 앞서가지 않게.
이미 수집된 556건은 `backfill_doc_raw.py --apply`로 채웠다(page_count 확보 394행,
STATUS 162건은 HTML이라 쪽수 개념이 없어 None이 정상).

**[검증]** `test_asset_pipeline.py` §12~13 — `mark_queue_done`이 doc_raw를 남기는가 /
저장했다는 파일이 실제로 없으면 남기지 않는가 / 재수집 시 버전이 오르는가.

--------

#98

**물건 사진 계층이 통째로 없었다** — 상세페이지에 사진이 안 보이던 진짜 이유

해결 (2026-08-17, Sprint 144)

**[증상]** 상세페이지에 물건 이미지가 표시되지 않는다.

**[실측된 원인]** 표시 문제가 아니었다. **crawler / 저장경로 / 테이블 / 컬럼 / API /
프런트 어디에도 사진을 다루는 코드가 없었다.** 전 스키마를 훑어 image/photo/thumb 계열
컬럼을 찾은 결과 **0개**였고, `grep -ri "image"`가 Python 소스에서 잡는 것도 0건이었다.
`docs/TEST_PLAN.md` §4가 "이미지: 물건 사진/이미지 기능이 코드에 존재하지 않는다"라고
정확히 적고 있었다.

**[법원 원천 확인]** 사진은 **제공된다.** 실제 브라우저로 `courtauction.go.kr`
물건상세(PGJ151F00)의 DOM을 직접 확인했다(표본 7사건).

```
IMG#mf_wfm_mainFrame_gen_pic_<N>_img_reltPic
    alt = "<종류>_<순번>"          "전경도_1" / "위치도_4" / "관련사진_5"
    src = "data:image/png;base64,...."
```

★ 두 가지가 이 파이프라인의 모양을 정했다 —

1. **다운로드할 URL이 없다.** 사진은 페이지 안에 base64 data URI로 박혀서 온다.
   "URL 획득 → HTTP 다운로드" 단계가 **존재하지 않는다**(법원 서버 추가 요청 0회).
2. **선언된 MIME이 틀렸다.** `data:image/png`라고 선언하는데 실제 바이트는 JPEG/GIF다
   (표본 45장 중 PNG 0장). 확장자를 선언값에서 가져오면 `.png`로 저장된 JPEG가 쌓인다 —
   **항상 매직 바이트로 판정한다.**

**[수정]** `crawler/image_assets.py`(순수 규칙) + `crawler/image_crawler.py`(수집) +
`auction_image` 테이블(migration 020) + `api/v1/images.py`(서빙) + 상세페이지 갤러리.
수집 대기·재시도·우선순위는 **기존 `document_queue`를 그대로 재사용**한다
(`doc_type='image'`) — 새 큐를 만들지 않았다.

**[관련 결함]** `go_to_case_detail()`이 `item_no`를 받지 않아 다중물건 사건에서 항상
첫 물건의 상세페이지로 들어갔다. 문서는 버튼 id에 물건번호가 붙어 있어 영향이 없었지만
(실측: 파일이 있는 다중물건 사건 22건에서 서로 다른 물건이 같은 바이트인 경우 0건),
**사진은 버튼 없이 페이지 DOM을 읽으므로 곧바로 오염이 된다.** `item_no`를 받아
물건번호가 일치하는 행을 우선 고르도록 고쳤다(못 찾으면 종전 동작 + 경고 로그).

**[검증]** 실 법원 E2E — 9물건 45장 수집 성공(확장자 오판 0건), `auction_image` 45행,
`GET /api/v1/item/502/images/1` → 200 `image/jpeg` 70,100 bytes 브라우저 정상 렌더링.
`test_asset_pipeline.py` 20그룹.

**[주의 — 새로 만든 상태값]** 법원이 사진을 아예 주지 않는 물건이 실재한다. READY로 쓰면
"볼 수 있다"는 거짓말이고 FAILED로 쓰면 실패가 아닌 것을 영원히 재시도한다. 그래서
`document_status`에 **`NO_IMAGE`**를 뒀다(`mark_queue_skipped_expired()`가 같은 이유로
상태를 안 건드리기로 한 것과 같은 계열의 판단이되, 화면 문구가 명확해 상태를 만들었다).

--------

#99

**인증 없이 500을 만들 수 있다** — 큰 정수 id가 sqlite3 OverflowError로 터진다

해결 (2026-08-17, Sprint 144 보안 감사)

**[원인]** 파이썬 int는 무한 정밀도인데 SQLite INTEGER는 64비트다. FastAPI의
`item_id: int` 경로 파라미터는 자릿수를 제한하지 않으므로 큰 수가 그대로 sqlite3에
바인딩되어 `OverflowError: Python int too large to convert to SQLite INTEGER`가 난다.

```
GET /api/v1/item/999999999999999999999                  -> 500
GET /api/v1/item/999999999999999999999/documents/SPEC   -> 500
GET /api/v1/item/999999999999999999999/images/1         -> 500
GET /api/v1/item/502/images/999999999999999999999       -> 500
```

**전부 인증이 필요 없는 공개 경로다.**

**[발견 경위]** Sprint 144가 새로 만든 사진 엔드포인트를 프로빙하다 찾았는데, 확인해 보니
`/item/{id}`와 `/documents/`에 **이미 있던 결함**이고 새 엔드포인트가 같은 모양을 물려받은
것이었다. 이 스프린트가 만든 결함이 아니다.

**[영향]** 데이터가 새거나 서버가 죽지는 않는다. 다만 **없는 물건을 물었을 때 404가 아니라
500이 나가고** 서버 로그에 스택 트레이스가 쌓인다 — 운영 알림을 붙이는 순간 노이즈가 되고,
"500이 나면 장애"라는 판단 기준 자체를 못 쓰게 만든다.

**[수정]** `api/constants.py:is_sqlite_int()`를 두고 세 엔드포인트가 함께 쓴다.
범위를 벗어난 id는 **404**로 답한다 — 422가 아니다. 형식은 올바른 정수이고 다만 존재할 수
없는 값일 뿐이며, **음수 id가 이미 404인 것과 같은 취급**이라 기존 동작과도 일관된다.

**[검증]** `test_asset_pipeline.py` §18-A — 네 경로 전부 404, 경계값(`2**63-1`)이 과잉
차단되지 않음, 정상 id는 여전히 200. 같은 프로빙에서 경로 탈출·SQLi 형태·응답 본문
경로 누출은 전부 이미 막혀 있음을 확인했다.

--------

#100

**현황조사서가 물건번호 2 이상에서 영구 수집 불가였다** — "미지원"이 아니라 틀린 전제였다

해결 (2026-08-17, Sprint 144+)

**[옛 동작]** `config/settings.py:get_doc_button_id("status", item_no)`는 `item_no != '1'`이면
**None(미지원)**을 돌려줬다. 근거는 "물건번호가 2 이상일 때의 버튼 id를 DOM으로 확인한 적이
없다"였고, 추측으로 셀렉터를 만들지 않는다는 방침에 따른 **의도적으로 보수적인 선택**이었다.

**[영향 실측 2026-08-17]**

```
auction_item 1,876건 중 물건번호 != 1        629건 (33.5%)
그 전부가 현황조사서를 영원히 받을 수 없었다
document_status에서 '수집중'으로 갇혀 있던 행  628건
큐에서 성공 가능성 0으로 대기 중이던 행        109건 (그중 pending 103)
document_queue의 status done 중 item_no != 1  0건   <- 단 한 건도 성공한 적이 없다
```

같은 사건의 물건1은 이미 그 문서를 갖고 있는데도 물건2 이상은 못 받는 상태였다.

**[실제 DOM 확인 — 추측이 아니라 실측]** 실 브라우저로 물건번호 2인 상세페이지 **2건**
(서울중앙 2025타경311 물건2, 2023타경2726 물건2)의 DOM을 직접 덤프했다.

```
mf_wfm_mainFrame_btn_dspslGdsSpcfc1   매각물건명세서  (물건1)
mf_wfm_mainFrame_btn_dspslGdsSpcfc2   매각물건명세서  (물건2)
mf_wfm_mainFrame_btn_aeeWevl1         감정평가서      (물건1)
mf_wfm_mainFrame_btn_aeeWevl2         감정평가서      (물건2)
mf_wfm_mainFrame_btn_curstExmndcTop   현황조사서      <- 번호 없음, 단 하나. 물건2 페이지에도 표시됨
```

**번호가 붙은 변형(`...Top2`)은 존재하지 않는다.** 명세서·평가서만 번호가 붙고 현황조사서만
안 붙는다는 것 자체가 "이 문서는 물건 단위가 아니다"라는 신호다.

내용으로도 확인했다 — 물건2 페이지에서 그 버튼을 눌러 오버레이를 읽으니 **한 문서가 사건의
모든 물건을 담고 있었다**(부동산임대차정보 표에 번호 1 = 지2층비201호, 번호 2 = 2층202호가
나란히 들어 있다). 현황조사서는 집행관이 **사건 단위**로 작성하는 문서다.

즉 옛 동작은 "안전한 미지원"이 아니라 **틀린 전제**였다.

**[수정]** 물건번호와 무관하게 같은 버튼 id를 돌려준다.

**[부수 효과 — 설계가 의도대로 작동했다]** `repair_unsupported_status_docs.py`는 대상을
하드코딩하지 않고 `get_doc_button_id()`에 **물어보도록** 만들어져 있었고, 그 파일의 "안전성"
절에 *"나중에 버튼 id가 확보되면 대상이 저절로 줄어든다"*고 적혀 있었다. 실제로 이 수정 직후
그 스크립트의 대상이 **629건 -> 0건**이 됐다(스크립트는 한 줄도 고치지 않았다).
`--apply`는 한 번도 실행된 적이 없어(STATUS FAILED 1행뿐, 그마저 수집 실패로 생긴 것)
되돌릴 행도 없다.

**[검증]** `test_document_queue.py` §14가 새 규약을 고정한다(물건번호가 달라도 같은 버튼,
버튼 id에 물건번호가 붙지 않음). §16은 시드가 더 이상 "미지원"이 아니게 되어 공허해질
뻔했으므로, 지키려던 불변식(종결된 행이 `reset_stale_queue()`에 되살아나지 않는가)을
그대로 두고 전제만 갱신했다 — 지금 남은 영구 미지원 사유는 **알 수 없는 doc_type**뿐이다.

--------

#101

**진행 중 물건이 큐의 옛 매각기일 때문에 영구 미수집으로 종결된다**

해결 (2026-08-17, Sprint 145)

**[옛 동작]** `document_queue.auction_date`는 06:00 적재 시점에 복사해 둔 **비정규화
사본**이다. `doc_worker`의 2차 방어선은 그 사본을 보고 `auction_date < today`면
`mark_queue_skipped_expired()`로 종결했다. 유찰 후 재매각으로 기일이 미래로 다시
잡혀도 사본은 옛 날짜를 들고 있을 수 있는데, 그 경우 **살아 있는 사건이 수집 대상에서
빠진다.** `SKIPPED_EXPIRED`는 `reset_stale_queue()`의 부활 대상도 아니라 영구적이다.

Sprint 74가 이 위험을 알고 `enqueue_documents()`에 갱신 로직을 넣었지만, 그 갱신은
**06:00 크롤이 돌 때만** 일어난다. 크롤과 크롤 사이에 기일이 바뀌면 구멍이 남는다.

**[영향 실측 2026-08-17]**

```
document_queue.auction_date != auction_item.auction_date          36행
  그중 pending + 큐는 과거 + 실제 기일은 미래                       3행
    -> item 1533 (2024타경122092-1) spec/status/appraisal 전부
       큐 2026-07-15  vs  실제 2026-08-19
```

item 1533은 **당시 기본 검색에 뜨는 9건 중 하나**였다. 즉 사용자가 볼 수 있는 물건의
문서가 영원히 도착하지 않고, 화면에는 "수집중"이 무기한 유지된다.

**[수정]** `storage/database.py :: reconcile_queue_auction_date()`를 신설하고
`doc_worker`가 종결 **직전에** 호출한다. 정책("기일 지난 사건은 수집하지 않는다")은
그대로 두고, 그 판단이 참조하는 **값의 출처만** 사본에서 `auction_item`으로 바꿨다.
드리프트를 발견하면 큐 행도 함께 정정한다(`refresh_queue_priority()`의 우선순위 오판도
같이 사라진다). `status`는 건드리지 않는다 — 종결된 행의 부활은 재수집 정책이라
제품 판단이다.

**[검증]** `test_asset_pipeline.py` §15-B(정정 동작 5단언: 권위값 반환 / 큐 정정 /
status 불변 / 실제로 지난 기일은 구제하지 않음 / 물건 없으면 큐 값 유지)와
§15-C(worker 배선: import + 종결보다 먼저 호출). Mutation으로 호출을 제거하면 §15-C가
실패하는 것까지 확인했다.

--------

#102

**경로 조각 정규화 규칙이 쓰는 곳과 읽는 곳에서 서로 달랐다**

해결 (2026-08-17, Sprint 146) — **잠재 결함(현재 실데이터 영향 0건)**

**[경위]** Sprint 145에 `crawler/doc_paths.py:sanitize_path_segment()`가 신설되면서
쓰는 쪽(`_doc_dir_path`, `find_sibling_case_document`, `image_assets.image_path`)은
`/`뿐 아니라 **역슬래시·`..`·빈 값**까지 처리하게 됐다. 그런데 **읽는 쪽인
`api/v1/documents.py:get_doc_dir()`만 옛 규칙(`/`만 치환)으로 남았다.**

**[결과]** 사건번호에 역슬래시가 섞이면 두 계층이 다른 경로를 본다.

```
case_no = "2024\타경1"
  크롤러가 쓰는 곳   documents/법원/2024_타경1/2/spec.pdf
  API가 찾는 곳      documents/법원/2024\타경1/2/spec.pdf   <- 404
```

`documents.py`의 주석이 *"크롤러가 쓴 문서를 API가 못 찾는 문제는 없다"*고 단언하고
있었는데, 그 단언이 규칙 변경으로 조용히 거짓이 된 상태였다.

**[현재 노출 범위]** 실데이터 1,876건에 역슬래시·`..`는 **0건**이다(확인함). 즉 지금
터지는 버그가 아니라 **규칙이 두 벌인 상태 자체**가 결함이다 — 이 저장소가 BUGS #50/#64로
반복해 겪은 "쓰는 곳과 읽는 곳이 다른 경로를 보는" 부류이고, 원천(법원 HTML)이 예상 밖
값을 주는 순간 터진다.

**[수정]** `api/v1/documents.py`가 같은 `sanitize_path_segment()`를 쓰도록 했다.
`crawler.doc_paths`는 selenium/DB/fastapi 무의존이라 API에서 import해도 안전하다
(`api/v1/images.py`가 `crawler.image_assets`를 쓰는 것과 같은 방식).

**[검증]** `test_asset_pipeline.py` §19-B가 **리터럴이 아니라 두 구현의 결과를 직접
대조**한다(`/` 포함·역슬래시·`..`·빈 값 6가지). `test_pipeline_integrity.py` §0의
리터럴 검사도 같은 방식으로 정정했다 — 그 검사는 규칙이 한 곳으로 모이자
**좋아졌는데 실패**하는 상태였다(리터럴이 사라졌으므로).

--------

#103

**큐 기일 정정이 다른 법원의 물건을 보고 덮어쓸 수 있었다** — "법원 없는 식별키" 재발

해결 (2026-08-17, Sprint 146)

**[원인]** Sprint 145에 신설한 `storage/database.py:reconcile_queue_auction_date()`가
물건을 `case_no + item_no`로만 찾았다.

```sql
SELECT auction_date FROM auction_item
 WHERE case_no = ? AND CAST(item_no AS TEXT) = ?     -- 법원이 없다
```

근거로 적어 둔 것은 *"(case_no, item_no)는 auction_item 1,876행에서 유일함을 실측으로
확인했다"* 였다. **그 확인은 틀린 것을 확인한 것이다** — `auction_item` 안에서 유일한
것과, **큐 행이 자기 법원의 물건과 맺어지는가**는 다른 문제다. 조인 상대는 큐이고
큐에는 자기 `court_code`가 따로 있다.

**[실측 2026-08-17]** 법원마다 사건번호를 독립 채번하므로 같은 번호가 여러 법원에 있다.

```
큐의 (사건,물건)이 **다른 법원의** auction_item과 매칭되는 행   18행
  그중 pending (정정이 실제로 호출될 수 있는 것)               12행

  q=7204  큐법원=성남지원    vs 물건법원=통영지원     2024타경4973-1
          -> 통영 물건의 기일(2026-08-10)로 성남 큐를 "정정"하게 된다
  q=9769  큐법원=포항지원    vs 물건법원=부산서부지원  2024타경4705-1
  q=10600 큐법원=부산동부지원 vs 물건법원=서산지원     ...
```

**[결과]** 기일을 바로잡으려던 함수가 **엉뚱한 사건의 날짜를 덮어쓴다.** 그 날짜가
미래면 이미 끝난 사건을 수집하려 브라우저를 몰고, 과거면 수집해야 할 사건을 건너뛴다.
게다가 큐 행 자체를 UPDATE하므로 오염이 **영구히 남는다**.

**[같은 함정의 세 번째다]** `docs/BUGS.md` #18(`auction` UNIQUE 키에 법원 없음),
#14(`auction_case.case_no` 전국 단일 UNIQUE)와 정확히 같은 부류다. 두 번 잡았는데
새 코드에 다시 들어왔다.

**[수정]** `court_code`를 함께 받아 `WHERE court_name=? AND case_no=? AND item_no=?`로
찾는다. **법원을 못 받으면 정정하지 않고 큐 값을 그대로 돌려준다** — 잘못 고치는 것보다
안 고치는 편이 낫다(경고 로그를 남긴다). `doc_worker.py` 호출부도 함께 고쳤다.

**[검증]** `test_asset_pipeline.py` §12-D — 같은 사건번호를 쓰는 두 법원을 심어 두고
성남지원 큐를 정정했을 때 통영지원 기일로 오염되지 않는지, 법원 미지정이면 정정을
건너뛰는지, **진짜 드리프트는 여전히 정정하는지**(과잉 방어 아님)까지 확인한다.
호출부가 `court_code`를 넘기는지도 소스로 고정한다.

**[교훈]** 이 저장소에서 (사건번호, 물건번호)만으로 물건을 특정하는 코드는 **항상
의심해야 한다.** 특히 조인 상대가 `document_queue`이면 반드시 법원을 포함해야 한다.
이번 감사에서 내가 쓴 측정 쿼리 자체도 같은 실수를 해서 "done인데 파일 없음 3건"이라는
**허위 결과**를 냈다(법원을 넣자 0건). 진단 도구도 같은 규칙을 지켜야 한다.

--------

#104

**사건 단위 재사용이 절감의 4%만 실현하고 있었다** — 최적화가 비싼 단계 뒤에 있었다

해결 (2026-08-17, Sprint 147)

**[경위]** Sprint 145가 현황조사서(사건 단위 문서)를 형제 물건에서 복사하는 재사용을
`collect_status()` 안에 넣었다. 그런데 `doc_worker`의 루프는 이렇게 생겼다:

```python
ok = go_to_case_detail(driver, ...)          # ← 무조건 먼저 (비싸다)
result = collect_document(driver, ...)       # ← 재사용은 이 안에 있다
```

즉 **브라우저 이동을 먼저 다 하고 나서** "복사하면 되겠네"를 판단했다.

**[실측 2026-08-17]** 단계별로 계측했다:

```
navigation      15.2초   <- 재사용해도 그대로 들던 비용
overlay 수집     0.6초   <- 재사용이 아끼던 전부
형제 파일 복사   0.002초
```

물건당 절감이 **0.6초(4%)**뿐이었다. 492회 기준 **5분**.
`docs/crawler.md`·`docs/roadmap.md`·`crawler/doc_paths.py`가 적어 둔 **"약 3.0시간 절감"은
navigation까지 건너뛴다고 가정한 값**이라 틀렸다(약 26배 과대).

**[왜 눈에 안 띄었나]** 결과가 완전히 같기 때문이다 — 파일 내용도, DB 행도, 화면도
동일하다. **느려지기만 하고 아무것도 깨지지 않아** 테스트도 전부 통과했다.
합성 테스트(§10-B)는 `collect_status()`를 직접 불렀으므로 navigation을 아예 거치지 않아
이 문제를 볼 수 없었다.

**[수정]** `doc_worker`가 **브라우저를 열기 전에** 형제 재사용 가능 여부를 먼저 본다.
가능하면 `collect_document(None, ...)`로 driver 없이 복사하고 이동을 생략한다.
복사가 실제로 이뤄지지 않으면(`reused_from`이 비어 돌아오면) 정상 경로로 떨어진다 —
브라우저 없이 실패로 종결시키지 않는다.

**[검증]** 실제 `doc_worker.main()`으로 같은 사건 물건 2건 처리:

```
수정 전  41.1초
수정 후  23.8초      (물건당 15.8초 -> 0.002초)
492회 기준 약 130분 절감
```

결과 정합도 그대로다 — 두 물건의 `status.html` 바이트 동일, `document_status` READY x2,
`doc_raw` 2행, 큐 done x2.

**[회귀]** `test_asset_pipeline.py` §12-E가 **호출 순서 자체**를 고정한다 —
재사용이 가능하면 `go_to_case_detail`이 호출되지 않아야 하고, `collect_document`에
`driver=None`이 넘어가야 한다. 순서가 되돌아가면 결과는 같고 성능만 26배 나빠지므로
결과 기반 검사로는 잡을 수 없다.

**[교훈]** 최적화를 넣을 때 **그 최적화가 비싼 단계보다 앞에 있는지** 확인해야 한다.
"재사용이 발동한다"는 것과 "재사용이 비용을 아낀다"는 다른 명제다.

--------

#105

**`git commit -a`를 하면 API가 부팅되지 않는다** — 실동작 신규 모듈 14개가 전부 미추적

발견 (2026-08-17, Sprint 148 Release Audit) — **미해결, 승인 영역**

**[경위]** Sprint 144~146에서 만든 파일들이 아직 `git add`되지 않았다.
Commit/add 금지가 상시 제약이라 의도된 상태지만, **추적중인 파일이 미추적 파일을
import한다**는 점이 문제다. 즉 지금 작업트리는 정상 동작하는데,
`git commit -a`(추적 파일만 스테이징)로 커밋하면 **가져올 수 없는 상태**가 나온다.

의존 간선 4개를 실측했다:

```
api_server.py:32          (M)  →  api/v1/images.py            (??)   최상위 import
api/v1/documents.py:6     (M)  →  api/http_cache.py           (??)   최상위 import
crawler/doc_crawler.py:619(M)  →  crawler/image_crawler.py    (??)   지연 import
src/app/search/ResultList.tsx(M) → ResultThumbnail.tsx        (??)   빌드 시점
storage/database.py       (M)  →  auction_image 테이블 (020 마이그레이션이 ??)
```

**[증명]** 추론이 아니라 재현했다. `git ls-files`로 **추적 파일 297개만** 임시
디렉터리에 복사해 `commit -a` 직후 상태를 그대로 만든 뒤 부팅을 시도했다:

```
$ python -c "import api_server"
  File ".../api/v1/documents.py", line 6, in <module>
    from api.http_cache import not_modified
ModuleNotFoundError: No module named 'api.http_cache'

$ from crawler.image_crawler import collect_images
ModuleNotFoundError: No module named 'crawler.image_crawler'
```

API가 라우터 등록 단계에서 죽으므로 **검색/상세/문서/이미지 전 기능이 동시에 정지**한다.
마이그레이션 020이 빠지면 `auction_image` 테이블이 아예 생성되지 않아 이미지 레이어도
같이 죽는다.

**[미추적 파일]** 전부 `.gitignore` 대상이 **아니다**(`git check-ignore` 0건) —
즉 add를 막는 규칙은 없고, 단지 아직 안 한 것이다.

개수는 세션 중에도 늘어난다(이 항목을 쓴 뒤 실제로 14 -> 15 -> 16으로 늘었다). 그래서
**목록을 여기 박아 두지 않는다** — 숫자를 쫓아 문서를 고치게 되고, 그러다 정작 중요한
사실이 묻힌다. 현재 목록은 이 명령으로 언제든 재현한다:

```
git status --short | grep "^??"
```

**판단에 필요한 사실은 개수가 아니라 "무엇이 무엇을 import하는가"다.** 새로 늘어난
파일들은 전부 테스트라 프로덕션이 참조하지 않으므로, 아래 **깨지는 간선 4개는 그대로다.**
그 4개가 이 항목의 실체이고, `test_schema_hygiene.py` §6-B가 자동으로 다시 계산한다.

**[탐지]** `test_schema_hygiene.py`의 "링크된 storage/ 소스는 git이 추적된다"가
이 중 마이그레이션 020 **하나만** 잡아냈다(그 검사가 `storage/`만 보기 때문이다).
나머지 13개는 어떤 테스트도 잡지 못했다 — 그래서 이 항목을 남긴다.

**[조치]** `git add` 뿐이고 Commit/add 금지라 **SKIP**. 사용자가
`git add -A` 후 커밋하면 해소되며, 그 순간 `test_schema_hygiene.py`도 별도 수정 없이
PASS로 돌아온다. **`git commit -a`나 `git commit <일부파일>`은 쓰면 안 된다.**

**[교훈]** "작업트리에서 테스트가 통과한다"와 "커밋된 것이 동작한다"는 다른 명제다.
신규 파일을 만든 세션에서는 **추적 상태 자체를 산출물의 일부로** 검증해야 한다.

--------

#106

**결과 0건일 때 "조건을 줄여보세요"가 틀린 안내이자 막다른 길이 되는 경우가 있다**

해결 (2026-08-17, Sprint 148)

**[경위]** `ResultList.tsx`의 Empty State는 결과 0건의 원인을 **항상 사용자 검색조건**으로
단정했다. "검색조건을 줄이거나 지역·가격 범위를 넓혀보세요"라는 문구와 "조건 없이 전체
물건 보기" 링크를 띄운다. 조건이 좁아서 0건인 경우에는 맞는 안내다.

그런데 원인이 하나 더 있다 — **카탈로그에 살아있는 물건이 아예 없는 경우**다. 기본 필터가
`auction_date >= 오늘`이므로 크롤이 멈추면 재고가 매일 줄어 결국 0이 된다. 이때는

- 문구가 틀렸다. 사용자 잘못이 아닌데 사용자 조건을 탓한다.
- **복구 링크가 막다른 길이다.** 이미 조건 없는 화면인데 "조건 없이 전체 물건 보기"를
  누르면 똑같은 빈 화면으로 되돌아온다. 사용자는 빠져나갈 방법이 없다.

가정이 아니라 **예정된 상태**다(2026-08-17 실측):

```
auction_item 1,876행 중 미래 매각기일 9건, 전부 2026-08-19
-> 2026-08-20부터 기본 검색이 0건
```

스케줄러 미등록(승인 영역)이 해소되지 않으면 이 화면이 **기본 화면**이 된다.

**[해결]** 원인 두 갈래를 나눴다. `SearchScreen.tsx`가 검색 파라미터로 조건 유무를
계산해 `hasFilters`로 넘기고, `ResultList.tsx`가 갈라 렌더한다.

```
page / size / sort_by / sort_order  -> 조건이 아니라 "표시 방식"이므로 제외
그 외 파라미터가 하나라도 있으면    -> hasFilters = true
```

정렬만 바꾼 사용자를 "조건을 건 사용자"로 오판하지 않게 하려고 제외 목록을 뒀다.

조건이 없는데 0건이면 문구를 바꾸고 **막다른 링크를 아예 없앤다**:

```
현재 공개된 경매 물건이 없습니다
검색조건 때문이 아닙니다 — 매각기일이 남은 물건이 아직 등록되지 않았습니다.
새 물건은 법원 공고에 맞춰 갱신되니 잠시 후 다시 확인해 주세요
```

**[검증]** tsc/eslint/build 통과만으로는 부족하다 — 이 프로젝트에서 이미 "빌드는 통과하는데
화면이 죽는" 사고가 있었다(`ResultList.tsx`의 서버 컴포넌트 `onError`). 그래서 **실제로
렌더시켜** 확인했다.

운영 데이터를 건드리지 않고 2026-08-20 상태를 재현했다. `DB_PATH`가 cwd 상대경로이고
API base가 환경변수라 둘 다 프로세스 단위로 갈아끼울 수 있다:

```
auction.db를 스크래치로 복사 -> 사본에서만 미래 물건 9건 삭제
사본 디렉터리를 cwd로 API를 8010에 기동  -> /search 가 total:0 반환
NEXT_PUBLIC_API_BASE_URL=127.0.0.1:8010 으로 dev 서버를 3010에 기동
```

렌더된 HTML을 직접 확인한 결과:

```
조건 없음 + 0건        -> "현재 공개된 경매 물건이 없습니다"  (옛 문구·막다른 링크 부재)
sort/page만 + 0건      -> 새 문구 (정렬을 조건으로 세지 않는다)
조건 있음 + 0건        -> "검색 결과가 없습니다 / 조건 없이 전체 물건 보기" (기존 동선 유지)
결과 있음              -> 물건 카드 20개 정상 렌더
```

검증 후 두 서버를 종료하고 사본을 삭제했다. **운영 DB는 무변경**(1,876행 / 미래 9건 /
doc_raw 556 / auction_image 45 — 전부 검증 전과 동일).

**[교훈]** "결과가 0건이다"에서 곧바로 "사용자 조건이 좁다"로 건너뛰면 안 된다.
빈 화면의 복구 동선은 **그 동선이 실제로 결과를 만들어 내는지** 확인해야 한다.
이 경우 링크가 자기 자신을 가리키고 있었다.

--------

#107

**법원 없는 식별키가 두 곳 더 남아 있었다** — `document_queue`에 쓰는 SQL 2건

해결 (2026-08-17, Sprint 148)

**[경위]** 같은 계열의 사고가 #18 / #14 / #103으로 세 번 반복됐다. 개별 수정만 해 왔기
때문에 네 번째가 남아 있었다. Data/Pipeline 감사 중 큐 고아를 조사하다 발견했다.

**[먼저, 이 덫이 실재한다는 증거]** "사건번호는 실무상 유일하다"는 가정은 틀렸다.

```
case_no 3개가 서로 다른 두 법원에 걸쳐 있다 (전체 1,381개 중 0.2%)
   2024타경34089   포항지원 / 정읍지원
   2024타경3700    수원지방법원 / 부산지방법원
   2024타경4973    통영지원 / 성남지원
연루된 auction_case 6행 / auction_item 22행
```

같은 감사에서 이 덫에 다시 걸린 것도 확인했다 — 큐 고아를 셀 때 법원을 뺀 조인은 **15건**,
법원을 넣은 조인은 **18건**이었다. 3건이 다른 법원 물건에 잘못 매칭돼 고아가 아닌 것처럼
보였다.

**[결함 1] `repair_empty_status_capture.py`** (git 추적 = 실동작 도구)

```python
"UPDATE document_queue SET status='pending', retry_count=0, last_attempt_at=NULL "
"WHERE case_no=? AND item_no=? AND doc_type='status' AND status='done'"
```

바로 위의 `document_status` UPDATE는 `item_id`로 정확히 좁히는데 큐 UPDATE만 법원이
빠졌다. A법원 물건 하나를 고치면 같은 사건번호를 가진 **B법원의 정상 수집분까지
pending으로 되돌아가** 멀쩡한 문서를 다시 받는다. `court_code=?`를 추가했다
(`e["court_name"]` — 두 컬럼이 같은 60종 어휘를 쓰는 것을 차집합 0으로 실측 확인).

**[결함 2] `unlock_retry.py`** (git 추적)

```python
UPDATE document_queue SET last_attempt_at = NULL
WHERE case_no = '2024타경1775' AND doc_type = 'appraisal'
```

법원 누락에 더해 대상이 소스에 박혀 있고 실행 즉시 운영 DB에 반영됐다(미리보기 없음).
인자로 받도록 바꾸고 **법원을 필수 인자**로 만들었으며, 이 저장소의 다른 도구들과 같이
기본을 dry-run으로 바꿨다(`--apply`로 반영). 오늘 이 사건번호는 서울중앙지방법원 한 곳
뿐이라 당장 오작동하지는 않았지만, 다른 법원에 같은 번호가 생기는 순간 조용히 틀린다.

**[회귀 — 이번엔 개별 수정으로 끝내지 않았다]** `test_auction_identity.py`에
`test_document_queue_writes_are_court_scoped()`를 신설했다. git이 추적하는 프로덕션
`.py`에서 `UPDATE/DELETE document_queue` 문장을 찾아, `case_no`로 좁히면서 법원이 없으면
실패시킨다(테스트 자신과 gitignore 대상 일회성 스크립트는 제외).

**오탐을 먼저 잡았다.** 처음엔 고정 길이(500자) 창으로 SQL을 읽었는데, `storage/database.py`의
`WHERE id = ?`(정확한 문장)이 **7줄 뒤 logger.info의 case_no** 때문에 위반으로 잡혔다.
파이썬 문자열 리터럴만 정확히 읽는 `_sql_literal_at()`으로 바꿔 해소했다(인접 리터럴 연결도
이어 붙인다). 검사가 옳은 코드에 대해 울리면 없느니만 못하다.

**검사기가 비어 있지 않다는 것도 증명했다** — `repair_empty_status_capture.py`에서 법원을
일부러 다시 빼자 정확히 그 줄을 짚어 FAIL했고, 되돌리자 PASS했다.

```
추적 .py 77개에서 document_queue 쓰기 문장 13개 검사 -> 위반 0
```

**[교훈]** 같은 계열의 버그가 세 번 반복됐는데도 매번 그 인스턴스만 고쳤다. 네 번째를
찾은 지금은 **계열 전체를 막는 검사**를 넣었다. 반복되는 버그는 인스턴스가 아니라 계열을
막아야 끝난다.

--------

#108

**문서 엔드포인트가 대소문자를 가려서, 같은 저장소의 다른 어휘로는 400이 났다**

해결 (2026-08-17, Sprint 148)

**[경위]** Performance 감사에서 단건 엔드포인트 응답시간을 재던 중, READY인 물건에
`/documents/status`를 보냈는데 400이 나왔다. 처음엔 측정 스크립트의 실수인 줄 알았으나
아니었다.

이 저장소는 **같은 개념을 두 벌 어휘로 저장한다**:

```
document_status.doc_type   SPEC / STATUS / APPRAISAL     (대문자)
document_queue.doc_type    spec / status / appraisal     (소문자)
```

API는 대문자만 받았다. 화면은 `document_status`에서 값을 받아 URL을 만들기 때문에
지금 깨지지 않는다(그래서 여태 안 보였다). 그러나 **큐 쪽 값으로 URL을 만드는 코드**는
400을 받는다 — 복구 스크립트, 운영 도구, 앞으로 추가될 기능이 전부 해당한다.

더 나쁜 것은 진단이 어렵다는 점이다:

```
GET /documents/status  -> 400 "지원하지 않는 문서 종류입니다"
GET /documents/bogus   -> 400 "지원하지 않는 문서 종류입니다"     ← 구별 불가
```

정상 어휘를 쓴 요청과 오타를 낸 요청이 **같은 응답**을 준다.

**[해결]** `get_document()`에서 `doc_type`을 대문자로 정규화한 뒤 허용 목록과 대조한다.
**받아들이는 입력만 넓히는 변경**이라 기존 대문자 호출의 동작은 그대로다(기존 API 유지).
값은 `DOC_TYPE_FILES`의 키로만 쓰이고 파일명은 상수에서 오므로 경로 조작 위험은 없다.
`HEAD`는 `get_document()`에 위임하므로 자동으로 같은 규칙을 따른다.

**[검증]** item 53(SPEC READY) 기준:

```
SPEC / spec / Spec / sPeC  -> 200, 본문 402,328B 전부 동일
STATUS / status            -> 404 (이 물건의 STATUS는 COLLECTING) — 대소문자 무관하게 동일
bogus                      -> 400 (모르는 종류는 그대로 거부)
'' , ../etc                -> 404 (라우팅 단계, 경로 이탈 없음)
HEAD SPEC / HEAD spec      -> 둘 다 200
```

**[회귀]** `test_api_regression.py` §16에 4검사 추가 — 소문자/혼합 대소문자가 대문자와
같은 상태·같은 본문을 주고, 모르는 종류는 **여전히 400**이며, HEAD도 같은 규칙을 따른다.

**[교훈]** 한 개념에 어휘가 두 벌이면 경계에서 반드시 샌다. 두 벌을 유지할 수밖에 없다면
경계(API 입력)에서 정규화해야 한다. 그리고 "모르는 값"과 "다른 표기의 아는 값"에 같은
오류를 주면 원인을 찾을 수 없다.

--------

#109

**doc_worker가 실행 창 밖에서도 브라우저를 띄웠고, 기동 실패 시 락을 남겼다**

해결 (2026-08-17, Sprint 148)

**[경위]** Recovery 감사 중 `is_time_up()`이 True인데(14:22, 종료시각 04:00) 드라이버가
그대로 기동되는 것을 발견했다. 원인은 시간 검사가 **루프 조건에만** 있었기 때문이다:

```python
if not _acquire_lock(): return 0     # 락은 브라우저 앞에서 검사
...
driver = build_download_driver()     # <- 창 밖이어도 여기서 Selenium 기동
while not is_time_up():              # <- 첫 조건에서 곧바로 탈출
```

바로 위 락 검사에는 "어차피 실행하지 못할 거라면 Selenium 기동 비용을 쓰지 않는다"는
주석이 달려 있다. **같은 원칙이 시간 검사에는 적용되지 않았다.** 스케줄러 실행이 밀리거나
운영자가 낮에 수동으로 돌리면 실제로 도달한다.

**[결함 2 — 이쪽이 더 나쁘다] 드라이버 기동 실패가 락을 남긴다**

조사 중 `build_download_driver()`가 락을 해제하는 **두 구간 사이**에 끼어 있는 것을 봤다:

```python
try:
    init_db(); reset_stale_queue()
except Exception:
    _release_lock(); raise          # <- 여기까지만 보호
driver = build_download_driver()     # <- 무방비 구간
try:
    while ...
finally:
    _release_lock()                  # <- 여기부터 다시 보호
```

추측이 아니라 **재현했다** — 기동 실패를 모사하자 `logs/doc_worker.lock`에 죽은 PID가
남았다(`17984 2026-08-17T14:23:06`).

```
이후 실행 -> "다른 doc_worker.py 인스턴스가 이미 실행 중으로 보임" -> return 0
```

`LOCK_STALE_HOURS=5`가 있어 영구 정지는 아니다. 그러나 하필 **곧바로 재시도하고 싶은
5시간 동안** 후속 실행이 전부 건너뛰어진다. 드라이버 기동 실패는 크롬 업데이트 중이나
일시적 자원 부족처럼 **금방 해소되는 원인**이 많아 재시도 가치가 큰데, 그 창을 스스로
막고 있었다. 게다가 건너뛴 실행은 종료코드 0(성공)으로 보고된다.

**[해결]**

1. 락 검사 직후에 `is_time_up()`을 확인해 창 밖이면 브라우저 없이 종료한다.
   `reset_stale_queue()`보다 **앞**에 둔다 — 처리할 시간이 없는 실행이 큐 상태를
   건드릴 이유가 없다.
2. `build_download_driver()`를 락 해제가 보장되는 try 안으로 옮겼다. 예외는 그대로
   전파시킨다(스케줄러가 실패를 인지해야 하므로 삼키면 안 된다).

**[검증]**

```
창 밖 실행       exit=0, 소요 0.00s, 드라이버 기동 안 함, 락 없음
기동 실패        예외 전파됨, 락 없음
창 안 정상 경로   reset_stale_queue 호출됨, 드라이버 기동 시도됨 (동작 불변)
```

**[회귀]** `test_doc_worker_recovery.py`에 6번(기동 실패도 락을 해제한다)과
7번(창 밖에서는 브라우저를 띄우지 않는다)을 신설했다. 6번이 **비어 있지 않다는 것도
증명했다** — 드라이버 호출을 try 밖으로 되돌리자 정확히 그 검사가 FAIL했고, 되돌리자
PASS했다.

**[교훈]** 값비싼 자원을 얻기 전에 하는 검사는 **한 곳에 모아야 한다.** 락은 앞에서
보고 시간은 뒤에서 보는 구조라, 둘 중 하나만 고쳐진 채 오래 남아 있었다. 그리고
자원 획득 구문은 해제를 보장하는 블록 **안**에 있어야 한다 — 두 보호 구간 사이의
한 줄이 정확히 사고 지점이었다.

--------

#110

**드라이버 생성 후 설정이 실패하면 크롬 프로세스가 고아로 남았다** (#109 계열 전수 검색의 소득)

해결 (2026-08-17, Sprint 149)

**[경위]** #109를 고친 뒤 "같은 계열이 다른 곳에 없는가"를 AST로 전수 검색했다.
자원 획득(`get_connection` / `sqlite3.connect` / `build_download_driver` / `_acquire_lock`)
53곳을 훑어 **해제 보장 블록 밖에 있는 것**을 찾는 방식이다.

1차 규칙(획득 직후가 try가 아니면 의심)은 12곳을 뱉었는데 **전부 오탐**이었다 —
`conn = get_connection()` 다음이 `inserted = 0` 같은 상수 대입이라 예외가 날 수 없다.
"사이에 낀 구문 중 **예외를 낼 수 있는 것**만 위험하다"로 조이자 5곳이 남았고, 그것도
전부 `conn.row_factory = sqlite3.Row` 패턴에 프로세스 종료로 정리되는 일회성 스크립트라
실질 위험이 아니었다.

**진짜는 검사기가 "즉시 반환"이라며 건너뛴 곳에 있었다.**

```python
driver = webdriver.Chrome(service=svc, options=opts)   # 프로세스가 이미 떴다
driver.set_page_load_timeout(30)                        # 여기서 실패하면?
return driver
```

`set_page_load_timeout()`은 브라우저에 명령을 보내므로 기동 직후 죽었거나 연결이
거부되면 실패한다. 그러면 예외만 나가고 **크롬 프로세스는 살아남는다.** 호출자는
`driver` 참조를 받지 못했으니 `quit()`을 부를 방법조차 없다.

**#109와 정확히 맞물린다.** #109 수정으로 기동 실패 시 락은 풀리지만, 실패 지점이
여기라면 좀비 크롬이 남는다. 기동 실패는 재시도 가치가 큰 장애라 반복되기 쉽고,
그때마다 좀비가 하나씩 쌓여 메모리와 다운로드 폴더를 함께 갉아먹는다.

**[해결]** 설정 구간을 try로 감싸 실패 시 `driver.quit()` 후 예외를 **그대로 올린다**
(삼키면 호출자가 기동 실패를 인지하지 못한다).

**[검증]** `crawler/doc_crawler.py`는 실브라우저 의존이라 커버리지 0%지만, 이 함수만은
selenium 진입점(`webdriver.Chrome`/`Service`/`ChromeDriverManager`)을 갈아끼워 실제
브라우저 없이 검증할 수 있다.

```
설정 실패 모사 -> RuntimeError 전파됨,  quit() 호출 1회 (좀비 없음)
```

**[회귀]** `test_doc_worker_recovery.py` 8번 신설.

**[교훈]** "즉시 반환하니 호출자 책임"이라는 규칙에 예외가 있다 — **반환 전에 이미
자원이 존재하면** 그 구간은 여전히 생성자 책임이다. 계열 검색에서 이 케이스를
자동으로 걸러낸 것이 오히려 진짜를 가릴 뻔했다. 검사기가 넘긴 것도 눈으로 봐야 한다.

--------

#111

**읽기 전용 dry-run 도구가 "문서 있어요?"라고 묻기만 해도 디렉터리를 만들었다**

해결 (2026-08-17, Sprint 153)

**[경위]** 저장소에 있는 진단 도구들을 순서대로 돌려 보다가 `empty_doc_dirs_dryrun.py`가
빈 디렉터리를 1,674개 보고했다. 숫자가 눈에 걸렸다:

```
빈 물건 디렉터리        1,674
파일이 있는 물건 디렉터리   202
                     ------
합계                  1,876  =  auction_item 행수와 정확히 일치
```

우연이 아니다. **물건 전수를 훑은 무언가가 디렉터리를 만들었다**는 뜻이다.

범인은 `repair_empty_status_capture.py`였다. `crawler.doc_paths`에서 `get_doc_dir()`을
가져다 쓰는데, 그 함수는 경로를 계산할 뿐 아니라 `os.makedirs()`를 부른다. 그리고
`find_empty_captures()`는 **읽기 전용 스캔**이면서 물건 1,876건 전부에 대해 그것을 부른다:

```python
for r in rows:                                     # auction_item 전수
    d = get_doc_dir(...)                           # <- 여기서 디렉터리가 생긴다
    path = os.path.join(d, "status.html")
    if not os.path.exists(path):
        continue                                   # 파일도 없는데 폴더만 남는다
```

**실증했다.** 존재하지 않는 물건 경로로 `_doc_dir_path()`를 부르면 아무것도 생기지 않고,
`get_doc_dir()`을 부르면 즉시 생긴다.

**[이미 고쳐진 적이 있는 사고다]** 이 저장소는 2026-08-14에 같은 사고를 겪고
`_doc_dir_path()`(계산만)와 `get_doc_dir()`(생성까지)로 함수를 쪼갠 뒤 `doc_exists()`를
고쳤다. `crawler/doc_paths.py`와 `crawler/image_assets.py`의 주석이 그 사고를 명시적으로
경고하고 있다. **그런데 이 스크립트에만 적용이 빠져 있었다.**

**[해결]** import와 호출을 `_doc_dir_path()`로 바꿨다. 이 스크립트는 `e["dir"]`에
쓰지 않는다 — 격리 디렉터리는 따로 `makedirs`하고, 원본에서는 파일을 **꺼내기만** 하므로
생성이 필요 없다.

**[검증]**

```
수정 전 : (실증) 없는 경로로 get_doc_dir 호출 -> 디렉터리 생성됨
수정 후 : 전수 스캔 실행 -> documents/ 디렉터리 3,338개 그대로 (증가 0)
          스캔 결과도 동일 (정상 162건 / 내용 없음 0건)
```

**[회귀]** `test_doc_path_safety.py` 8번 신설. 두 가지를 고정한다.

1. `_doc_dir_path()`는 디스크를 건드리지 않는다 — **대조군으로 `get_doc_dir()`은 실제로
   만든다는 것까지 확인**한다(두 함수가 정말 다르다는 것을 검사 자신이 증명하도록).
2. 읽기 전용 스캐너 3종이 `get_doc_dir()`을 import하지 않는다(소스 대조).

가드가 비어 있지 않은 것도 확인했다 — import를 되돌리자 정확히 그 파일을 짚어 FAIL했다.

**[남은 것]** 이미 만들어진 빈 디렉터리 1,674개(+ 그로 인해 비는 사건 1,183 / 법원 5)는
그대로다. 삭제는 승인 영역이라 SKIP한다. 이 수정은 **더 늘지 않게** 만든다 — 새 물건이
들어온 뒤 이 도구를 돌려도 이제는 생기지 않는다.

**[교훈]** 같은 계열을 고칠 때 **호출부를 전수로 훑어야 한다.** 함수를 둘로 쪼개고
주석까지 남겼는데도 호출부 하나가 옛 함수를 계속 부르고 있었다. 그리고 "dry-run"이라는
이름은 부작용이 없다는 보장이 아니다 — 이 도구는 DB는 안 건드렸지만 파일시스템을 바꿨다.

--------

#112

**경로 규칙 사본이 세 번째로 살아 있었다** (#111의 "호출부 전수 검색" 소득)

해결 (2026-08-17, Sprint 153)

**[경위]** #111을 고치며 "같은 계열을 고칠 때는 호출부를 전수로 훑어야 한다"고 적었다.
그대로 `get_doc_dir` 호출부 전수를 훑다가 나왔다.

```
crawler/doc_crawler.py    5곳   전부 쓰기 직전 (spec/status/appraisal 저장)  정상
api/v1/documents.py       자체 정의 — makedirs 안 함, sanitize_path_segment 사용  정상
load_rights_data.py       api/v1/documents 것을 import                        정상
load_spec_data.py         api/v1/documents 것을 import                        정상
repair_document_status.py 자체 정의 — ★ 규칙 사본                             결함
```

`repair_document_status.py`의 사본은 이랬다:

```python
def get_doc_dir(...):
    """api/v1/documents.py:get_doc_dir() 와 동일한 규칙."""     # <- 더 이상 아니다
    safe_case_no = (case_no or "").replace("/", "_").strip()    # / 만 치환
```

docstring이 "동일한 규칙"이라고 주장하지만 **그 사이 규칙이 바뀌었다.** 크롤러가 쓰는
`sanitize_path_segment()`는 Sprint 145~146에 **역슬래시도 치환**하고 `""`/`"."`/`".."`를
`"_"`로 바꾸도록 확장됐다. 이 사본만 옛 규칙에 멈춰 있었다.

**[왜 위험한가]** 이 스크립트는 파일 존재 여부로 `document_status`를 READY로 바꾼다.
경로 규칙이 갈라지면 크롤러는 `a_b`에 쓰고 이 스크립트는 `a\b`를 찾는다 — 즉
**화면만 "수집완료"이고 서빙은 404**인 상태를 만들 수 있다. 이 저장소가 BUGS #50/#64로
반복해 겪은 어긋남과 같은 계열이다. 현재 실데이터에 역슬래시는 0건이라 지금 터지는
버그는 아니고, 규칙이 세 벌인 상태 자체를 없앤 것이다.

**[왜 안 걸렸나]** `test_doc_path_safety.py` 7번(규칙 사본 검사)이 이미 있었지만
**검사 대상 목록에 이 파일이 없었다**(`doc_paths` / `image_assets` / `documents` /
`images` 4개만 봤다). 목록 기반 검사의 한계가 그대로 드러났다.

**[해결]** `sanitize_path_segment()`를 그대로 쓰게 바꾸고, 7번의 대상 목록에 이 파일을
추가했다.

**[검사기도 고쳤다]** 대상에 넣자 곧바로 오탐이 났다 — 내가 **왜 고쳤는지 보이려고
옛 코드를 주석에 인용**했는데 검사가 그 인용문을 위반으로 잡았다. 사고 이력을 남기는
일과 검사가 싸우면 안 되므로, 줄 번호는 유지한 채 주석 줄만 비우고 코드만 보도록 했다.
그 뒤 **진짜 코드 사본을 한 줄 넣어 FAIL하는 것까지 확인**했다(비어 있지 않음 증명).

**[검증]** 수정 후 스크립트를 실제로 돌렸다.

```
document_status 전체 5,628행 대조
  파일 있음 + 이미 READY   556
  파일 있음 + 상태 어긋남     0     <- 보정 대상 없음
  파일 없음(건드리지 않음)  5,072
```

DB와 파일시스템이 완전히 일치한다 — Sprint 151 E2E 감사(READY 556 전건 파일 존재)를
**다른 코드 경로로** 독립 확증한 셈이다.

**[교훈]** `"...와 동일한 규칙"`이라고 적힌 주석은 **작성 시점의 주장**일 뿐 유지되지
않는다. 규칙을 복제하면 주석이 아니라 import로 묶어야 한다. 그리고 목록으로 대상을
지정하는 검사는 목록에서 빠진 파일을 영원히 못 본다 — 새 파일이 생길 때 목록을
갱신하는 규율이 없다면, 목록이 아니라 **전수 스캔**으로 짜야 한다.

--------

#113

**이미지는 변경 감지 자체가 불가능했다** — `previous_hash`를 끝내 계산하지 않았다

해결 (2026-08-17, Sprint 186)

**[경위]** 이미지 파이프라인을 법원 원천부터 상세페이지까지 전수 추적하다 나왔다.

`mark_queue_done()`의 변경 감지 조건은 이렇다:

```python
if previous_hash and previous_hash != new_hash:
    INSERT INTO document_version_log ...
```

그런데 `collect_images()`는 `previous_hash`를 `""`로 초기화하고 **끝내 계산하지 않았다**
(`crawler/image_crawler.py`에서 `previous_hash`는 초기화 1회만 등장). 즉 이 조건이
**이미지에서는 영원히 거짓**이고, 재수집을 켜도 사진 교체가 어디에도 기록되지 않는다.

문서 수집기는 같은 자리에서 이미 계산하고 있었다 —
`crawler/doc_crawler.py:198  previous_hash = calc_file_hash(dest_path) if os.path.exists(...)`.
**이미지만 빠져 있었다.**

**[해결]** 수집(=덮어쓰기) **전에** 디스크의 기존 사진들로 지문을 뜬다
(`_existing_set_hash()`). 공식은 `new_hash`와 **같아야 한다** — 파일별 sha256을 순번 순으로
이어 붙여 다시 sha256. 공식이 갈라지면 매 수집이 "변경됨"으로 보여(거짓 개정) 진짜 개정을
찾을 수 없다.

근거를 DB가 아니라 파일시스템으로 삼았다 — 이 모듈은 크롤러 계층이라 storage에 의존하지
않고, "실제로 서빙되는 바이트"가 곧 비교 대상이기 때문이다. 읽을 수 없는 파일이 하나라도
있으면 `""`를 돌려준다(반쪽 지문으로 비교하면 바뀌지 않았는데 개정으로 기록된다).

**[회귀]** `test_asset_pipeline.py` 5-C 신설(10검사). 세 경우가 서로 다른 결과를 내는지
고정한다.

```
최초 수집        previous_hash == ""          (비교할 이전 상태가 없다)
같은 사진 재수집  previous_hash == new_hash    (거짓 개정을 만들지 않는다)
다른 사진 재수집  previous_hash != new_hash    (개정을 놓치지 않는다)
그리고 그 값이 실제로 document_version_log 1행으로 이어지는 것까지 확인
```

두 번째가 특히 중요하다 — **통과하려면 디스크 쪽 공식과 수집 결과 쪽 공식이 정확히
같아야** 한다. 이 검사가 공식 일치를 구조적으로 보증한다.

**[교훈]** 문서와 이미지가 "같은 계약(`_empty_result()` 모양)"을 쓴다고 해서 **같은 수준으로
구현돼 있다고 가정하면 안 된다.** 필드 이름이 같아도 한쪽만 채우고 있을 수 있다.

--------

#114

**부분 수집이 사용자가 보던 사진을 지웠다** (재수집을 켜는 순간 도달하는 경로)

해결 (2026-08-17, Sprint 186)

**[경위]** `save_auction_images()`는 이번에 저장된 최대 순번보다 큰 옛 행을 지운다.
의도는 옳다 — 법원이 사진을 5장에서 3장으로 줄이면 옛 4,5번 행이 **없는 사진**을 가리킨다.

문제는 그 함수만 보면 **두 상황이 똑같아 보인다**는 것이다. 둘 다 순번 3까지만 들어온다.

```
법원이 줄였다     -> 옛 4,5번을 지우는 것이 맞다
5장 중 3장만 받아졌다 -> 지우면 사용자가 보던 사진 2장이 사라지고,
                       그 파일들은 디스크에 고아로 남는다
```

`collect_images()`는 이 둘을 `partial`로 정확히 구별하는데(`len(images) < attempted`),
그 정보가 `save_auction_images()`까지 전달되지 않았다.

**[해결]** `complete: bool = True` 파라미터를 추가하고 `doc_worker`가
`complete=not result.get("partial")`로 넘긴다. 기본값이 기존 동작이라 다른 호출부는
영향을 받지 않는다. 부분 수집이면 지우지 않고 경고만 남긴다.

**판단할 수 없을 때는 남기는 쪽**을 택했다 — 남은 행은 여전히 실제 파일을 가리키고 다음
정상 수집이 정리하지만, 지운 행은 되돌릴 수 없다.

**[현재 도달 여부]** 부분 수집은 아직 한 번도 일어나지 않았다(2026-08-17 실측: 경고 0건,
9물건 전부 5장, seq 결번 0). **재수집을 켜는 순간 도달 가능해지는 경로**라 미리 막았다.

**[회귀]** `test_asset_pipeline.py` 7-B 신설(10검사). 같은 입력에 `complete` 플래그만
바꿔 **반대 결과**를 기대하므로 구조적으로 공허할 수 없다.

```
부분 수집(complete=False)  -> removed_stale 0, 5장 그대로
법원 축소(complete=True)   -> removed_stale 2, 3장으로 줄어듦
전체 실패(저장 0장)         -> 어느 쪽이든 삭제 0, 기존 보존
```

--------

#115

**문서(doc_raw)는 내용이 같아도 재수집마다 버전이 올랐다** — 이미지 BUGS #113과 같은 계열

해결 (2026-08-17, Sprint 187)

**[경위]** Sprint 186이 이미지 파이프라인을 법원 원천부터 상세페이지까지 전수 추적한 것과
같은 방식으로, 이번에는 **문서** 파이프라인을 같은 깊이로 훑었다. `document_version_log`는
이미 `previous_hash != new_hash`일 때만 기록하도록 돼 있는데(Sprint 78 §8), 같은
`mark_queue_done()`이 여는 같은 트랜잭션에서 `_record_doc_raw()`가 쓰는 `doc_raw.doc_version`은
그 판단이 **전혀 없이** 매번 `MAX(doc_version)+1`을 무조건 삽입했다
(`storage/database.py:984-1000`, 수정 전).

`api/v1/item.py`가 이 `doc_version`을 그대로 응답에 실어(`doc_raw_by_type` -> `_document_entry`)
사용자에게 노출한다. 즉 문서 재수집을 켜는 순간(현재는 `overwrite=True`를 아무도 넘기지
않아 도달하지 않는다 — roadmap "문서 재수집 정책" 참고) **내용이 한 글자도 안 바뀐 문서도
매일 밤 버전이 올라가는 형태**로 사용자에게 드러나게 되어 있었다.

```
document_version_log 의 조건:  previous_hash != new_hash 일 때만 기록  (Sprint 78, 정상)
doc_raw.doc_version 의 조건:   없음 — 성공할 때마다 무조건 +1          (Sprint 187 이전, 결함)
```

**[해결]** `_record_doc_raw()`가 삽입 전에 직전 `doc_raw` 행의 `file_hash`와 지금 저장하는
파일의 sha256을 **직접 비교**한다. 같으면 새 행을 만들지 않고 조용히 반환한다(버전 유지).
비교 근거는 `mark_queue_done()`에 넘어오는 `previous_hash`/`new_hash` 인자가 아니라 이
함수가 자기 손으로 다시 계산한 해시로 뒀다 — 그 인자들은 크롤러 계층
(`crawler/doc_crawler.py`)이 doc_type마다 각자 계산해 넘기는 값이라, `status`처럼 파일이
두 개(`status.html`+`status.json`)인 경우 대표 파일(`doc_raw`가 기록하는 파일)과 반드시
같은 파일을 가리킨다는 보장이 없다. `doc_raw` 자기 행끼리 비교하면 그 가정이 필요 없다.

**[회귀]** `test_asset_pipeline.py`에 `test_doc_raw_version_does_not_bump_on_unchanged_content`
신설. 같은 내용으로 두 번째 `mark_queue_done()`을 부르면 버전이 그대로임을,
이어서 내용을 실제로 바꿔 세 번째로 부르면 버전이 오름을 **한 검사 안에서** 확인한다
(반대 상황을 구분하므로 공허할 수 없다). 기존 `test_mark_queue_done_records_doc_raw`의
"재수집 시 버전 증가" 검사는 previous_hash/new_hash 문자열만 다르고 실제 파일 내용은
그대로였던 픽스처였다 — 새 판정 기준(파일 내용)에서는 **틀린 기대값**이 되므로, 파일
내용을 실제로 바꾸도록 함께 고쳤다(고치지 않았다면 이 수정이 기존 검사를 깼을 것이다).

**[교훈]** Sprint 186의 교훈("같은 계약을 쓴다고 같은 수준으로 구현돼 있다고 가정하면
안 된다")이 한 단계 더 안쪽에도 적용됐다 — 이번에는 이미지 vs 문서가 아니라
`document_version_log` vs `doc_raw`, **같은 함수 안의 두 기록 대상**이었다.

--------

#116

**spec/appraisal PDF 다운로드가 내용 검증 없이 저장됐다** — 이미지의 매직바이트 판정과
다른 수준

해결 (2026-08-17, Sprint 187)

**[경위]** `wait_for_download()`(`crawler/doc_crawler.py`)는 다운로드 완료를 "크기가
0보다 크고 두 번 연속 같은 크기"로만 판정한다. **내용이 실제로 PDF인지는 보지 않는다.**
법원 서버가 오류 페이지(HTML)를 `Content-Type: application/pdf`로 잘못 내려주거나
다운로드가 중간에 끊겨 잘린 파일이 남으면, 그 파일도 이 조건은 통과해 그대로
`shutil.move()`로 목적지(`spec.pdf`/`appraisal.pdf`)에 저장되고 `document_status`가
READY로 바뀔 수 있는 구조였다.

이미지 파이프라인은 선언된 MIME을 믿지 않고 매직 바이트로 판정한다
(`crawler/image_assets.py:sniff_image_ext`, 판정 못 하면 저장하지 않음) — 문서 쪽에는
같은 수준의 방어가 없었다. `collect_documents.py`(스케줄러가 부르지 않는 죽은 스크립트,
`docs/CLAUDE.md` 참고)의 0바이트 방어(BUGS #65)와 헷갈리면 안 된다 — **실제 운영 경로**인
`doc_worker.py -> crawler/doc_crawler.py`에는 이 검증이 아예 없었다.

**[해결]** `_looks_like_pdf()` 신설 — 파일 앞 1024바이트 안에 `%PDF-`가 있는지로 판정한다
(PDF 표준이 파일 맨 앞을 강제하지 않고 처음 1024바이트를 허용하는 것을 그대로 따름).
`collect_spec()`/`collect_appraisal()`이 `wait_for_download()` 직후, `shutil.move()` 전에
이 판정을 거친다. 실패하면 저장하지 않고(기존 정상 파일이 있었다면 그대로 보존) 다운로드
폴더의 가짜 파일을 지운다(고아 방지, BUGS #114와 같은 원칙).

`status`(html+json)에는 적용하지 않았다 — 그쪽은 이미 별도의 내용 검증
(`status_overlay_has_data()`, Sprint 62)이 저장 직전에 있고, 판정 대상이 PDF가 아니다.

**[회귀]** `test_doc_storage_atomicity.py`에 두 검사 신설:
- `test_looks_like_pdf_rejects_non_pdf_bytes` — 실제 PDF/HTML 오류 페이지/빈 파일/헤더
  없는 바이너리/존재하지 않는 파일 5가지를 판정 함수 단위로 고정.
- `test_collect_spec_refuses_non_pdf_download` — `wait_for_download()`를 몽키패치해
  "다운로드는 끝났다고 보고하되 내용은 HTML"인 상황을 만들어 `collect_spec()`이 실제로
  저장을 거부하는 것을, 대조군으로 진짜 PDF는 정상 저장되는 것을 **같은 호출 경로**로
  확인한다(형식적 PASS가 아니다).

--------

#117

**[운영 환경 실측 — Release Blocker] `auction.db`에 마이그레이션 020이 적용되지 않아
검색/상세 API가 전면 500을 낸다**

해결 (2026-08-17 09:03 마이그레이션 적용 확인, 2026-08-18 Sprint 189에 실측 재확인)

**[해결 확인 — 2026-08-18 Sprint 189]** 이 환경의 `auction.db`에
`020_create_auction_image.sql`이 **2026-08-17T09:03:19에 적용돼 있다**
(`migration_history` 20행 / 백업 파일 `auction.db.backup_before_020_20260817_090319`).
`test_schema_hygiene.py` §3도 통과한다. 실제 API를 다시 두드려 확인했다:

```
GET /api/v1/search?limit=3    -> 200  (total 9)
GET /api/v1/item/505          -> 200  (images 5장 READY, SPEC/STATUS/APPRAISAL READY)
GET /api/v1/item/505/images/1 -> 200 image/jpeg 235,194B   (If-None-Match -> 304)
GET /api/v1/item/505/documents/APPRAISAL -> 200 application/pdf 3,416,671B
```

아래 원문은 발견 당시 기록 그대로 남긴다. **단, 아래에서 근거로 삼은 "DOJOONPASS_DAILY가
정상 동작 중"이라는 관측은 2026-08-18 현재 더 이상 참이 아니다 — BUGS #123 참고.**

**[경위]** Sprint 187에서 문서 파이프라인을 상세페이지까지 실제로 확인하려고 `api_server.py`를
띄워 `/api/v1/search`와 `/api/v1/item/<id>`를 직접 호출했다. 둘 다 **500**을 반환했다.

```python
>>> conn.execute("SELECT item_id FROM auction_image GROUP BY item_id").fetchall()
sqlite3.OperationalError: no such table: auction_image
```

이 환경의 `auction.db`(저장소 루트, `.gitignore` 대상이라 환경마다 로컬 사본)에
`migration_history`가 마지막으로 기록한 것은 `019_add_subscription_payment_id.sql`
(2026-08-13)이고, `020_create_auction_image.sql`(migration 파일은 `storage/migrations/`에
존재하고 코드도 그것을 전제로 짜여 있다 — Sprint 144+)이 **적용되지 않았다**. 그 결과
`auction_image` 테이블 자체가 없다.

`api/v1/search.py`와 `api/v1/item.py`가 이 테이블을 try/except 없이 직접 조회하므로
(대표 이미지/썸네일 조회), 이 환경에서는 **검색 결과 목록과 물건 상세 둘 다 열리지 않는다** —
문서/사진이 안 보이는 정도가 아니라 **API 전체가 죽는다.**

`test_schema_hygiene.py`(§3, `migration_history completeness`)가 이미 이 어긋남을 잡고
있었다(`[FAIL] every .sql file on disk is recorded as applied: ['020_create_auction_image.sql']`) —
이번에 그 원인과 사용자 영향(전면 500)까지 실측으로 연결했다.

**[영향 확인]**
```
GET /api/v1/search?limit=3   -> 500 {"detail":"검색 처리 중 오류가 발생했습니다"}
GET /api/v1/item/58          -> 500 Internal Server Error   (58 = 실제 존재하는 item id)
```

**[근본 원인이 이것뿐인지]** 같은 환경의 스케줄러 실측(roadmap.md Sprint 187 정정 참고)과
합쳐 보면 앞뒤가 맞는다 — `doc_worker.py`가 애초에 스케줄러에 등록된 적이 없어
`save_auction_images()`가 호출된 적이 없고, 그래서 `auction_image` 테이블이 비어 있는 게
아니라 **아예 없다는 사실**이 지금까지 드러나지 않았을 뿐이다. 이 저장소의 다른 세션/환경에서
작성된 것으로 보이는 앞선 Sprint 문서(Sprint 186 등)의 "auction_image 45행" 실측은 **이
환경의 이 `auction.db` 파일**과는 다른 상태에서 관측된 값이다 — `*.db`가 gitignore 대상이라
세션/환경마다 로컬 사본이 갈릴 수 있다는 뜻이고, 그 자체가 하나의 교훈이다(아래 참고).

**[해결 방법 — 준비 완료, 실행만 승인 필요]** `docs/CLAUDE.md`의 DB 스키마 변경 승인 규칙에
따라 **여기서 직접 실행하지 않는다.** 승인 후 아래를 실행하면 된다(이미 코드에 있고
Sprint 144+가 검증한, 새로 만드는 마이그레이션이 아니다):

```bash
python -m storage.migrations.run_migrations   # idempotent, 001~020 중 미적용분만 적용
python test_schema_hygiene.py                 # §3이 통과하는지로 재확인
```

적용 후에도 `auction_image`가 비어 있는 것은 정상이다(위 스케줄러 정정 참고 — `doc_worker`가
아직 등록되지 않았으므로). 사진이 실제로 채워지려면 `DojoonPass-DocWorker` 작업 등록도
함께 필요하다(같은 승인 영역, roadmap.md에 정리).

**[교훈]** 이전 Sprint 문서의 "실측"은 **그 문서를 쓴 세션의 환경**에서 참이었던 값이지,
이 저장소를 여는 모든 환경에서 항상 참인 상수가 아니다. `*.db`처럼 gitignore된 로컬
산출물을 근거로 한 실측은 "코드가 그렇게 동작한다"와 "지금 이 환경이 그 상태다"를
구분해서 읽어야 한다 — 이번 감사는 실행 중인 API를 직접 두드려(`curl`) 후자를 확인했다.

--------

#118

**검색 API의 예상치 못한 서버 오류가 로그에 원인을 남기지 않았다** — BUGS #117을
조사하다 발견

해결 (2026-08-18, Sprint 188)

**[경위]** BUGS #117(마이그레이션 020 미적용으로 검색/상세 API 전면 500)을 실제
서버 로그로 재확인하려다, `logs`에 원인이 **전혀 남지 않는 것**을 발견했다.

`api/v1/search.py`의 `search()`/`get_regions()`는 이렇게 돼 있었다:

```python
except Exception as e:
    raise HTTPException(status_code=500, detail="검색 처리 중 오류가 발생했습니다") from e
```

FastAPI는 `HTTPException`을 "의도된 응답"으로 취급해 **트레이스백을 찍지 않는다.**
그래서 `sqlite3.OperationalError: no such table: auction_image` 같은 진짜 원인이
서버 어디에도 기록되지 않고, 사용자에게 보이는 일반 오류 문구만 남았다 — 운영자가
"왜 500인지"를 로그만으로는 영원히 알 수 없는 구조였다.

같은 저장소 안에서도 라우터마다 방식이 갈려 있었다 — `api/v1/payments.py`의 웹훅
처리(`_handle_webhook` 계열)는 같은 자리에서 이미 `logger.exception(...)`을 먼저
부르고 있었다. `search.py`만 그 관례를 놓치고 있었다.

**[해결]** 두 핸들러 모두 `raise` 앞에 `logger.exception(...)`을 추가했다(요청
파라미터도 함께 남겨 재현에 도움이 되게 했다). 응답 상태코드/본문은 그대로다 —
로그만 추가했다.

**[회귀]** 신규 `test_error_logging.py`.
- 1~2번: `TestClient`로 실제 HTTP 요청을 보내고 `get_connection()`을 예외를 던지는
  가짜로 바꿔치기해, 응답은 그대로(500 + 같은 문구)인데 로그에 원인이 남는지 확인.
  `git stash`로 수정을 되돌려 실제로 FAIL하는 것을 확인했다(공허한 검사 아님).
- 3번: **목록에 의존하지 않고** `api/` 전체를 AST로 훑어 "`except Exception`이
  `HTTPException`을 새로 던지면서 로그가 없는 지점"을 동적으로 찾는다. 검사 로직
  자체가 결함 있는/정상 샘플을 실제로 구분하는지부터 먼저 확인한 뒤 전수 검사한다 —
  이 검사가 있으면 **다음에 같은 실수를 하는 새 라우터도 자동으로 잡힌다.**

**[교훈]** `except Exception: ... raise HTTPException(...)` 패턴은 응답 계약을
지키면서도 원인을 조용히 지울 수 있다 — 결함이 사용자에게는 안 보이고 **운영자에게만**
안 보이는 종류라, 응답 검사 위주인 `test_api_regression.py`류로는 절대 못 잡는다.
로그 출력 자체를 캡처하는 검사가 따로 필요했다.

--------

#119

**하드코딩된 doc_type 목록 회귀 2건이 실 데이터 변화에 거짓 FAIL을 냈다** — BUGS #118
작업 중 전체 회귀를 재실행하다 발견

해결 (2026-08-18, Sprint 188)

**[경위]** #118 수정 뒤 관련 스위트를 다시 돌리다, 전날(Sprint 187)에는 전부 PASS했던
`test_document_queue.py`/`test_pipeline_integrity.py`가 **새로 FAIL**했다.

```
[FAIL] 큐의 doc_type 중 이 함수가 모르는 값 없음: ['image'] (expected [])
[FAIL] document_queue.doc_type 표기: ['appraisal', 'image', 'spec', 'status']
                                      (expected ['appraisal', 'spec', 'status'])
```

원인은 제품 결함이 아니라 **실 `auction.db`가 하루 사이에 실제로 바뀐 것**이다 —
매일 03:00에 도는 `mvp_scraper.py`(`enqueue_documents()`)가 `document_queue`에
`'image'` 행을 계속 쌓아 왔는데(Sprint 144부터 정상 동작), 이 두 검사는 그 값이
실제로 큐에 나타나기 전까지 우연히 통과하고 있었을 뿐이다. 둘 다 `["appraisal",
"spec", "status"]`류 **하드코딩 목록**과 정확히 같아야 한다고 단언하고 있었다 —
이 저장소가 `docs/CLAUDE.md`/roadmap 여러 곳에서 이미 경계해 온 바로 그 패턴이다
("목록으로 대상을 지정하는 검사는 목록에서 빠진 파일을 영원히 못 본다").

`'image'`는 정상적인 doc_type이다(Sprint 144) — 사진은 버튼 없이 상세페이지 DOM을
바로 읽으므로 `get_doc_button_id()`가 모르는 게 맞고(`doc_worker.py`의
`needs_button = doc_type != "image"`), `document_status`/`document_queue`에 `IMAGE`/
`image`가 나타나는 것도 정상이다. 검사가 **정상 상태를 결함으로 오판**하고 있었다.

**[해결]**
- `test_pipeline_integrity.py`: 하드코딩 리스트를 지우고 `storage.database.
  QUEUE_TO_DOC_STATUS_TYPE`(doc_type의 유일한 정의처)에서 알려진 값 집합을 가져와
  부분집합 검사로 바꿨다. 새 doc_type이 정상적으로 추가돼도 그 표만 갱신하면
  검사가 저절로 따라간다 — 하드코딩 사본을 유지할 필요가 없다.
- `test_document_queue.py`: `image`(버튼이 구조적으로 없는 유일한 종류)를 명시적으로
  제외하고 이유를 주석에 남겼다 — 목록에서 그냥 빼는 게 아니라 **왜 아는 값인데도
  None이 맞는지**를 기록해, 다음에 또 다른 버튼 없는 종류가 생기면 이 자리부터
  다시 판단하게 했다.

**[교훈]** 실 데이터에 대고 도는 회귀는 데이터가 자라면서 **전에 안 드러났던
가정**을 드러낸다. 이번 것은 무해했지만(실제로는 결함이 없었다), 하드코딩 목록이
"결함 없음"과 "아직 그 값이 안 나타났을 뿐"을 구분하지 못한다는 것 자체가 문제다 —
단일 소스(예: `QUEUE_TO_DOC_STATUS_TYPE`)를 참조하는 검사만이 그 둘을 구조적으로
구분한다.

--------

#120

**법원이 사진을 다른 형식으로 바꿔 끼우면 옛 파일이 고아로 남고, 그때부터 변경 감지가
영원히 거짓말을 한다**

해결 (2026-08-18, Sprint 189)

**[경위]** Sprint 189가 재수집 트리거를 붙이기 전에 이미지 파이프라인의 6가지 상황
(동일/변경/추가/삭제/부분실패/전체실패)을 실제 코드로 다시 추적하다 발견했다.

사진 파일 이름은 `<순번>.<확장자>`다(`crawler/image_assets.py:image_filename`).
그리고 확장자는 **선언된 MIME이 아니라 실제 바이트**로 정한다
(`sniff_image_ext` — 법원은 JPEG를 `image/png`로 선언하므로 이 판정이 옳다).
따라서 같은 순번 사진의 원본이 JPEG -> PNG로 바뀌면 저장 경로도 `01.jpg` -> `01.png`로
함께 바뀐다. 그런데 **옛 `01.jpg`를 아무도 지우지 않았다.**

**[재현]** (2026-08-18, 스크래치 디렉터리)
```
1) 최초 저장 후  previous_hash = a85fa75c94bbeef7   files = ['01.jpg']
2) PNG로 교체    수집측 new_hash = d598908cf1681374  files = ['01.jpg', '01.png']
3) 다음 주기     디스크측 previous_hash = eef6557e53fe2077

   같은 순번 파일 수: 2        (기대 1)
   디스크측 지문 == 수집측 지문? False   (기대 True)
```

**[영향]** 둘 다 나쁘다.

```
고아 파일   auction_image 는 UNIQUE(item_id, seq)라 DB는 새 경로 한 줄만 갖는다
            -> 옛 파일은 아무도 가리키지 않은 채 디스크에 영원히 남는다
거짓 개정   _existing_set_hash() 가 같은 순번을 두 번 세어, 순번당 한 장을 전제로
            만든 수집 쪽 new_hash 와 공식이 갈라진다
            -> 이후 **매 수집이 "변경됨"** 이 되어 진짜 개정을 찾을 수 없다
```

두 번째가 치명적이다. Sprint 186이 `_existing_set_hash()` docstring에 적어 둔 경고
("공식이 갈라지면 매 수집이 거짓 개정이 되어 진짜 개정을 찾을 수 없다")가 **형식 변경
한 번으로 영구히 현실이 된다.** 재수집(Sprint 189)을 켜는 순간 도달하는 경로다.

**[해결]**
- `crawler/image_crawler.py:_remove_other_ext_for_seq()` 신설 — 쓰기 성공 **직후**
  같은 순번의 다른 확장자 파일을 지운다. 먼저 지우지 않는 이유는 새 파일 쓰기가
  실패했을 때 사용자가 보던 사진이 사라지기 때문이다(부분 수집 보호와 같은 원칙:
  판단할 수 없을 때는 남기는 쪽).
- `_existing_set_hash()`가 같은 순번 중복을 발견하면 **비교 자체를 포기**하고 `""`를
  돌려준다(경고 로그와 함께). `OSError` 분기가 같은 이유로 이미 그렇게 하고 있었다 —
  반쪽 지문으로 비교하면 바뀌지 않았는데 "변경됨"으로 기록된다.
- 회귀: `test_asset_pipeline.py` 5-D(형식 교체 왕복 8검사) / 5-E(중복 순번 2검사).
  5-D의 결정적 검사는 "교체 뒤에도 디스크 지문 == 방금 수집한 지문"이다 — 두 공식의
  일치를 구조적으로 보증한다.

--------

#121

**재수집으로 기존 PDF를 덮어쓸 때만 저장이 비원자적이 된다**

해결 (2026-08-18, Sprint 189)

**[경위]** #120과 같은 추적에서, 문서 쪽 저장 경로를 확인하다 발견했다.
`collect_spec()`/`collect_appraisal()`이 다운로드분을 목적지로 옮길 때
`shutil.move(downloaded_path, dest_path)`를 썼다.

목적지가 **없을 때는** 그것으로 충분하다 — `os.rename()` 한 번이라 원자적이다.
문제는 목적지가 **이미 있을 때**다. Windows의 `os.rename()`은 기존 파일이 있으면
`FileExistsError`를 내고, `shutil.move()`는 그 예외를 잡아 **조용히 `copy2()` 폴백**으로
넘어간다.

**[재현]** (2026-08-18, Python 3.12.10, `copy_function`을 계측용으로 주입)
```
dest exists=False -> RENAME (원자적)
dest exists=True  -> COPY   (비원자적)   <- 재수집이 항상 여기로 온다
```

**[영향]** 비원자적 복사 도중 프로세스가 죽으면(전원 차단·OOM kill 등 except로 잡을 수
없는 죽음) **잘린 PDF가 목적지에 남는다.** 그리고 `doc_paths.doc_exists()`는
"존재 + 크기 0 초과"만 보므로 그 잘린 파일을 **완성된 문서로 취급**해, 다음 수집이
"이미 있다"고 건너뛴다 — 깨진 문서가 영구히 남는다. 이 저장소가 BUGS #22/#50/#61로
반복해 겪은 그 함정이다.

같은 일을 하는 `collect_documents.py:249`는 **이미 `os.replace()`를 쓰고 있었다.**
`crawler/image_crawler.py:_write_image_atomically()`도 그렇다. 두 수집기만 빠져 있었다
— "같은 계약, 한쪽만 실제로 구현" 계열(#113/#115)의 네 번째다.

**[해결]**
- `crawler/doc_crawler.py:move_into_place()` 신설(목적지 옆 `.tmp`로 옮긴 뒤
  `os.replace()`로 교체, 볼륨이 다르면 복사 폴백). 두 호출부를 교체.
- 회귀: `test_doc_storage_atomicity.py` 7d(덮어쓰기 왕복 + 교체 직전 크래시 주입 6검사).
- **전수 가드**: 7e가 `crawler/` `storage/` `collect_documents.py` 전체를 **AST로** 훑어
  목적지에 직접 쓰는 `shutil.move/copy*` 호출이 남아 있으면 실패한다(문자열 grep은
  결함을 **설명하는 산문**을 코드로 오판해서 못 쓴다 — 실제로 그렇게 걸렸다).
  변이 검사로 가드가 헛돌지 않음을 확인했다(원래 코드로 되돌리면 즉시 FAIL).

--------

#122

**재수집이 최종 실패하면 이미 보여 주던 문서가 "수집실패"로 뒤집힌다**

해결 (2026-08-18, Sprint 189 — 같은 Sprint에서 도입될 뻔한 것을 선제 차단)

**[경위]** 재수집 트리거를 붙인 뒤 실패 경로를 되짚다 발견했다. 이것은 기존 결함이
아니라 **재수집을 켜는 순간 새로 생기는** 결함이다.

`mark_queue_failed()`의 최종 실패 분기는 `document_status`에 무조건 `FAILED`를 쓴다.
재수집 이전에는 그 자리에 오는 것이 언제나 "한 번도 못 받은 문서"였으므로 옳았다.
재수집을 켜면 **이미 READY인 문서를 다시 받으려다 실패**하는 경우가 생긴다
(법원이 그 문서를 내렸거나, 버튼 DOM이 바뀌었거나, 그날 서버가 불안정했거나).

**[영향]** 화면(`document_status`)은 "수집실패"라고 말하는데
`GET /api/v1/item/{id}/documents/SPEC`은 여전히 **200으로 옛 문서를 내려 준다.**
사용자 입장에서는 **볼 수 있던 것이 갑자기 사라지는** 순수한 퇴행이고,
화면과 실체가 갈라지는 BUGS #50 계열이다.

**[해결]** 최종 실패 시 현재 화면 상태가 `DOC_STATUS_HAS_ARTIFACT`(=`READY`/`NO_IMAGE`)이면
**그 값을 유지**한다. `NO_IMAGE`를 포함하는 이유는 "법원이 사진을 제공하지 않는다"가
이미 정확한 답이라 재수집 실패로 틀려지지 않기 때문이다("수집 실패"와 "원래 없음"은
다르다). 큐 행은 그대로 `failed`로 남으므로 실패 사실 자체는 유실되지 않는다.

`reset_stale_queue()`가 "파일이 실제로 있는 문서를 COLLECTING으로 가리지 않는다"고
정한 규칙을 **반대 방향에 그대로 적용**한 것이다.

회귀: `test_refresh_trigger.py` §6b — READY/NO_IMAGE는 유지, COLLECTING은 FAILED로
(대조군이 없으면 이 검사는 공허하다).

--------

#123

**[운영 환경 실측 — Release Blocker] 이 저장소를 가리키는 예약 작업이 0개다.
매일 수집이 실제로는 돌지 않는다**

미해결 — 승인 필요 (2026-08-18, Sprint 189)

**[경위]** Sprint 189의 재수집 트리거가 "다음 수집 주기"에 실제로 도달하는지 확인하려고
스케줄러를 직접 조회했다. `docs/CURRENT_STATE.md`의 Sprint 187 기록은
"DOJOONPASS_DAILY(수동 등록)가 매일 03:00에 정상 동작 중, 오늘도(2026-08-17 03:00:01)
성공했다(exit 0)"고 적고 있었다. **이 환경에는 그 작업이 없다.**

**[실측]** (2026-08-18)
```
전체 예약 작업                                    249개
그중 이 저장소(.bat / dojoonpass / auction)를 가리키는 것    0개
register_scheduler_tasks.ps1 (dry-run)  세 작업 모두 "(신규)" — 기존 등록 없음
logs/daily_run.log 마지막 기록          2026-08-11 17:05
auction.crawl_date 최신                 2026-08-12 (9건) — 이후 6일간 0건
auction_item 중 기일이 남은 물건        1,876건 중 **9건**
```

세 근거가 서로 맞아떨어진다 — 스케줄러가 없으니 로그도 안 늘고 데이터도 안 들어온다.

**[영향]**
- **매일 갱신 체인 전체가 서 있다.** 물건 기본정보도, 사진도, 문서도 자동으로는
  아무것도 갱신되지 않는다. Sprint 189가 완성한 재수집 트리거도 트리거될 기회가 없다.
- 살아 있는 물건이 9건뿐이고 전부 2026-08-19까지의 기일이다 — **2026-08-20부터
  검색 결과가 0건이 된다**(Sprint 154가 예고한 시점과 같은 계산).

**[해결 방법 — 준비 완료, 실행만 승인 필요]** `docs/CLAUDE.md`의 승인 규칙상 여기서
직접 등록하지 않는다. 스크립트는 이미 있고 dry-run으로 선행 조건까지 확인했다.

```powershell
.\register_scheduler_tasks.ps1          # dry-run (확인 완료 — 3개 전부 "신규")
.\register_scheduler_tasks.ps1 -Apply   # 실제 등록 (승인 필요)
```

선행 조건 실측: 배치 파일 3개 OK / PATH python OK / 머신 PATH로는 해석 불가
(-> SYSTEM 계정 등록 금지, 스크립트가 이미 현재 사용자 계정으로 등록한다).

**[교훈]** #117이 남긴 교훈("이전 Sprint 문서의 실측은 그 세션의 환경에서 참이었던
값이다")이 **스케줄러에도 그대로 적용된다.** `Get-ScheduledTask` 결과는 `auction.db`와
마찬가지로 환경마다 다르고, 이번에는 하루 만에 달라졌다. 문서에 적힌 "정상 동작 중"은
**매번 다시 재는** 대상이지 상수가 아니다.


--------

#124

**현황조사서 지문이 우리가 찍은 수집 시각 때문에 매번 달라진다 — 재수집을 켜면
`document_version_log`가 거짓 개정으로 가득 찬다**

해결 (2026-08-18, Sprint 189)

**[경위]** 재수집 트리거를 붙인 뒤 "그래서 개정이 정확히 기록되는가"를 되짚다 발견했다.

`status.json`에는 우리가 매 수집마다 새로 찍는 `extracted_at`(수집 시각)이 들어 있다.
그런데 변경 감지 지문은 그 파일 **전체**에서 떴다:

```python
previous_hash = calc_file_hash(json_path)   # extracted_at 포함
...
new_hash      = calc_file_hash(json_path)   # 새 extracted_at 포함
```

즉 **법원 자료가 하나도 안 바뀌어도 두 지문이 항상 다르다.**

**[영향]** 재수집 이전에는 이 경로에 두 번 오지 않아 드러나지 않았다. 켜는 순간:

```
document_version_log   매 수집마다 1행        (전부 거짓 개정 -> 진짜 개정을 찾을 수 없다)
doc_raw.doc_version    매 수집마다 +1         (BUGS #115가 막으려던 바로 그것)
                       -> api/v1/item.py 가 그 값을 사용자 응답에 그대로 싣는다
                          = 아무 일도 없었는데 "버전 7"이 되어 간다
```

이미지 BUGS #113/#120이 "디스크 쪽 공식과 수집 쪽 공식이 갈라지면 매 수집이 거짓
개정이 된다"고 경고한 것과 **같은 결과**를, 문서 쪽은 다른 경로로 만들고 있었다.

**[이 저장소는 원인을 이미 알고 있었다]** Sprint 145의 형제 재사용 주석이 실측으로
적어 두었다 — *"status.json도 fields 115개 키가 완전히 일치했다(차이는 우리가 찍는
extracted_at 하나뿐)"*. 그 관찰이 **변경 감지 쪽으로 연결되지 않았을 뿐**이다.

**[해결]** 지문의 근거를 파일이 아니라 **내용**으로 바꿨다.

- `_fields_hash(fields)` — `fields`만 정렬된 canonical JSON으로 직렬화해 sha256.
  키 순서·들여쓰기 같은 **표현의 차이**가 내용의 차이로 둔갑하지 않는다.
- `status_content_hash(json_path)` — 디스크 쪽이 **같은 공식**을 쓴다(이미지의
  `_existing_set_hash()`가 지는 것과 정확히 같은 책임).
- 형제 물건 재사용 경로도 같은 공식으로 바꿨다 — 복사해 온 파일의 `extracted_at`은
  그 형제를 수집한 시각이라 비교 근거가 될 수 없다.

회귀: `test_doc_storage_atomicity.py` 7f — 수집 시각/키 순서가 달라도 같은 지문,
**내용이 바뀌면 다른 지문**(대조군), 디스크 공식 == 수집 공식, 못 읽으면 빈 지문.

--------

#125

**내용이 하나도 안 바뀐 재수집이 모든 브라우저 캐시를 무효화한다**

해결 (2026-08-18, Sprint 189)

**[경위]** #124와 같은 추적. 재수집이 "같은 내용"을 만났을 때 무엇을 하는지 확인했다.
답: **그냥 다시 쓴다.**

**[영향]** 같은 바이트를 다시 써도 **mtime이 바뀐다.** 서빙 쪽 ETag는 Starlette가
`(mtime, size)`로 만들기 때문에(`api/v1/images.py` / `api/v1/documents.py`),
내용이 그대로여도 **모든 브라우저 캐시가 무효화된다.**

`api/http_cache.py`가 조건부 요청(304)으로 아끼려던 바로 그 바이트다. 그 모듈이
실측해 적어 둔 규모:

```
검색 1페이지 썸네일  약 104KB x 20 = 약 2MB
물건당 사진 5장 합계 1.3 ~ 1.9MB
감정평가서 1건       3.4MB (실측)
```

그리고 재수집 대상은 정의상 **"사용자가 지금 보고 있는" 물건**이라 체감이 가장 큰
자리다. 목표 문서의 상황 A("이미지가 동일함 -> 재다운로드/불필요한 변경 최소화")가
정확히 이것을 가리킨다.

**[해결]** 세 저장 경로 전부 "달라졌을 때만 쓴다"로 바꿨다. 판정은 크기가 아니라
**바이트 지문**으로 한다(같은 크기의 다른 내용을 놓치지 않기 위해).

```
사진        _same_bytes_on_disk(dest, digest) 이면 쓰지 않는다 (crawler/image_crawler.py)
status      내용 지문이 같으면 html/json 둘 다 쓰지 않는다 (_write_text_if_changed)
spec/appr.  new_hash == previous_hash 이면 목적지를 건드리지 않고 다운로드분만 치운다
```

`status.json`의 `extracted_at`은 옛 값이 남는다 — 이제 그 필드의 뜻은 **"이 내용을
처음 확인한 수집 시각"**이다. 매 수집 시각을 남기는 것보다 이쪽이 더 쓸모 있다
(#124가 그 필드를 지문에서 뺐으므로 변경 감지에도 영향이 없다).

회귀: `test_asset_pipeline.py` 5-F(사진, 대조군 포함) /
`test_doc_storage_atomicity.py` 7g(텍스트) · 7h(PDF, 대조군 포함).

**[검사 설계 메모]** "썼다/안 썼다"를 mtime으로만 단언하면 안 된다.
**"안 썼다"는 mtime으로 확실히 말할 수 있지만**(쓰지 않았으면 절대 안 바뀐다),
**"썼다"는 말할 수 없다** — 두 쓰기가 파일시스템의 타임스탬프 갱신 간격보다 가까우면
같은 값이 나온다(작성 중 실제 플레이크를 겪었다). 그래서 후자는 **내용**으로 확인한다.

--------

#126

**테스트 정리(cleanup)의 두 호출 지점 중 하나만 강건해서, 한 번 실패하면 그 뒤 모든
실행이 같은 자리에서 죽는다**

해결 (2026-08-18, Sprint 189)

**[경위]** Sprint 189 작업 중 `test_doc_storage_atomicity.py`가 갑자기 계속 실패하기
시작했다. 판정문에는 `[FAIL]`이 하나도 없었는데 종료 코드가 1이었다 — 실패는 검사가
아니라 **cleanup**에서 났다.

```
PermissionError: [WinError 5] 액세스가 거부되었습니다:
  'documents\qa-atomic-5e1e311f\2026TEST1234\1'
```

**[원인]** 이 저장소는 OneDrive 폴더 안에 있고, OneDrive는 `documents/` 아래
디렉터리에 **R 속성**을 붙인다(실측 `0o555`). 그래서 맨 `shutil.rmtree()`는 실패한다.

이 함정은 **이미 알려져 있었고 방어도 있었다** — Sprint 96이 `_force_rmtree()`
(속성을 풀어 가며 지우는 헬퍼)를 만들어 두었다. 문제는 그것을 **"이전 실행 잔해"
정리에만 쓰고, 정작 이번 실행 자기 디렉터리는 맨 `shutil.rmtree()`로 지우고 있었다**는
점이다. 호출 지점 두 곳 중 하나만 고쳐진 상태였다(#110/#112와 같은 모양).

**[연쇄가 나쁘다]** cleanup이 죽으면 → 테스트 전체가 exit 1 → **지우지 못한
디렉터리가 그대로 남고** → 다음 실행도 같은 자리에서 죽는다. 실측으로 6벌이 쌓여
있었고, 그 상태에서는 이 테스트가 **영원히 실패**한다. 게다가 실패 위치가 검사가
아니라 정리라서, `[FAIL]` 문구를 grep하는 방식으로는 원인이 보이지 않는다
(`run_python_tests.py`가 종료 코드를 1순위로 쓰는 이유가 여기서 또 증명됐다).

**[해결]** `_force_rmtree()`를 모듈 수준으로 올리고 **두 호출 지점이 같은 함수를
쓰도록** 합쳤다. 쌓여 있던 잔해 6벌은 정리됐고, 연속 3회 실행으로 재발하지 않음을
확인했다.


--------

#127

**법원이 사진 수를 줄이면 옛 파일이 디스크에 남아, 그때부터 변경 감지가 영원히 거짓말을
한다** — BUGS #120과 **완전히 같은 실패 방식**의 다른 인스턴스

해결 (2026-08-18, Sprint 191)

**[경위]** #120(형식 변경 시 고아 파일)을 고칠 때 "같은 순번의 다른 확장자"만 봤다.
계열 전수 검색에서 **"이제 존재하지 않는 순번"** 이 그대로 남아 있는 것을 발견했다.

`save_auction_images()`는 DB 행만 지운다. **파일은 아무도 안 지웠다.**

**[재현]** (2026-08-18, 스크래치 문서 루트)
```
1) 최초 5장 수집        디스크: 01..05.jpg
2) 법원이 3장으로 줄임   디스크: 01..05.jpg      <- 기대 3개
3) 다음 주기 previous_hash = 2c9401e67511f7b6   (디스크 5장 기준)
   방금 수집한 new_hash  = 502a9087546a32f6     (수집 3장 기준)
   두 공식 일치?          False
```

**[영향]**
```
고아 파일   auction_image 가 가리키지 않는 파일이 계속 쌓인다
거짓 개정   _existing_set_hash() 는 **파일시스템**을 근거로 삼으므로 옛 파일까지 세고,
            수집 쪽 공식과 갈라진다 -> 이후 매 수집이 "변경됨"
            = 진짜 개정을 영원히 찾을 수 없다
```

**[해결]**
- `crawler/image_crawler.py:_remove_files_not_in()` 신설 — 완전 수집이면 이번에 확보한
  순번에 **없는** 파일을 지운다. **부분 수집이면 절대 지우지 않는다**(DB 쪽 `complete`
  가드와 같은 규칙 — "판단할 수 없을 때는 남기는 쪽").
- `save_auction_images()`의 행 삭제를 `seq > max_seq` -> **집합 차집합**으로 바꿨다.
  법원이 **가운데 순번을 빼는 경우**(1,2,4만 제공)를 `>` 비교는 못 잡아 3번 행이
  살아남고, 그 행이 가리키는 파일은 이미 없다. 파일 쪽과 같은 기준이라 두 근거가
  갈라지지 않는다.

**[검사가 옛 semantics 를 굳히고 있었다]** `test_asset_pipeline.py` §11 이
`save_auction_images()`를 **누적 빌더처럼** 쓰고 있었다({1,2} 저장 -> {1,3} 저장 ->
행이 1,2,3 이 되기를 기대). 그게 통과하려면 "이번에 안 준 순번의 행을 남긴다"가 참이어야
하는데 그건 이 함수가 막으려는 상태다. 옛 구현의 `seq > max_seq` 때문에 **우연히**
통과하던 것이다. 새 semantics 로 고치고 가운데-순번 케이스를 추가했다.

**[회귀]** `test_asset_pipeline.py` 5-G(감소 D / 부분수집 B / 전체실패 C 대조군 포함) +
**5-I 세 근거 불변식**(§아래 참고).

--------

#128

**법원이 사진을 전부 내려도 사용자는 그 사진을 영원히 본다**

해결 (2026-08-18, Sprint 191)

**[경위]** #127 을 고친 뒤 "그럼 0장으로 줄면?"을 따라갔다. 그 경로만 정리 함수에
도달하지 않았다.

`doc_worker` 는 `if result.get("images")` 로 가드하므로 — 빈 목록은 전체 실패와
구별되지 않으니 **그 가드 자체는 옳다** — 0장 케이스만 `save_auction_images()`를 지나가지
않는다.

```
법원이 전부 내림 -> collect_images: no_asset=True, images=[]
                 -> document_status = NO_IMAGE      (상태만 바뀐다)
                 -> auction_image 행/파일은 그대로
                 -> _images_status() 는 "행이 있으면 무조건 READY"
                 -> 화면은 READY, 사용자는 법원이 내린 사진을 계속 본다. 영원히.
```

**[해결 — 한 번 못 봤다고 지우지 않는다]** "법원이 내렸다"와 "이번 관측이 실패했다"는
한 번의 관측으로 구별할 수 없고, 사진을 전부 지우는 것은 이 파이프라인에서 **가장
파괴적인 동작**이다. 그래서 **두 번 연속 확인**을 요구한다.

```
1회차: document_status 가 READY -> NO_IMAGE 로 바뀐다. 사진은 남긴다(경고 로그).
2회차: 이미 NO_IMAGE 인데 또 no_asset 이다 -> 그때 행과 파일을 정리한다.
```

**새 컬럼이 필요 없다** — `document_status` 자체가 1회차를 기억한다(부분 수집 보호가
"판단할 수 없을 때는 남기는 쪽"을 택한 것과 같은 원칙).

`storage/database.py:clear_images_if_absence_confirmed()` 신설.
`mark_queue_done()` **보다 먼저** 불러야 한다 — 그 함수가 상태를 NO_IMAGE 로 덮고 나면
1회차인지 알 수 없다. 순서는 **DB 행 삭제 -> 파일 삭제**다(반대로 하면 "DB 는 있다는데
파일이 없다"가 된다). 파일 삭제는 `crawler/image_assets.py:remove_stored_image_files()`.

**[회귀]** `test_asset_pipeline.py` 5-H — 1회차 보존 / 2회차 정리 / 3회차 무동작 /
정리 후 화면이 정직해지는지(`_images_status`)까지.

--------

#129

**문서의 "수집 완료" 기준과 뷰어가 서빙하는 파일이 서로 다른 파일이었다**

해결 (2026-08-18, Sprint 191)

**[경위]** 사진 쪽 계열 검색을 문서 쪽에도 그대로 적용하다 발견했다.

```
doc_exists(status)            -> status.json 만 본다   (_PRIMARY_EXT)
api/v1/documents.py 가 서빙   -> status.html           (DOC_TYPE_FILES)
```

```
status.json 만 남은 상태 -> doc_exists()=True   (영원히 재수집 대상에서 제외)
                         -> 뷰어는 404
                         = "화면은 READY 인데 열면 없다"
```

BUGS #22/#50/#61/#64 와 같은 계열이고, 이번에는 **정의가 두 벌**인 형태였다.
`crawler/image_assets.py:image_exists()` 가 자기 docstring 에 **바로 그 원칙**을 적어
두었는데("쓰는 쪽과 읽는 쪽의 '있다' 정의가 갈라지면 화면은 READY 인데 뷰어는 404")
문서 쪽만 안 지키고 있었다.

**[실측]** 2026-08-18, `documents/` 전수:
```
status.html + status.json 둘 다   163
html 만 (재수집됨, 정상)            0
★ json 만 (완료로 오판)             0
둘 다 없음                        1,718
```
현재 실데이터에는 0건이라 **지금 터지는 버그는 아니다.** 정의가 두 벌인 상태 자체를 없앤다.

**[해결]** `crawler/doc_paths.py:DOC_REQUIRED_FILES` 신설 — 완료 판정이 **필요한 파일
전부**를 본다(status 는 html + json). 그리고 `test_doc_storage_atomicity.py` 7i 가
**서빙 표에서 파일명을 읽어** 완료 기준 안에 있는지 대조한다 — 목록을 손으로 맞추지
않으므로 새 문서 종류가 생겨도 저절로 따라간다.

--------

#130

**큐 경쟁에서 진 것을 "큐 비었음"으로 오해해 워커 실행이 통째로 조기 종료된다**

해결 (2026-08-18, Sprint 191)

**[경위]** Queue/Retry 감사에서 동시 claim 을 실제 스레드로 두드려 봤다.

`claim_next_queue_item()`은 두 가지 완전히 다른 사건에 **똑같이 `None`** 을 돌려줬다.

```
(a) 진짜로 가져갈 것이 없다
(b) 조회는 됐는데 UPDATE 에서 다른 실행에 밀렸다
```

`doc_worker.main()`은 `None` 을 (a)로 읽고 **그 실행 전체를 끝낸다.**

**[실측]** (2026-08-18, 스레드 12 / 대기 행 4)
```
수정 전   claim 성공 3건 / 중복 0건 / None 9건     큐: in_progress 3, pending 1
          -> 행이 남아 있는데 None 을 받은 스레드가 있다
수정 후   claim 성공 4건 / 중복 0건 / None 8건     큐: in_progress 4
          -> None 8건은 전부 정직하다(가져갈 행이 없다)
```

**중복 claim 은 원래 0건이었다** — 원자적 클레임
(`UPDATE ... WHERE id=? AND status=<집을 때 본 값>`)은 정상 동작하고 있었다.
문제는 **진 쪽의 처리**였다.

**[영향]** claim 충돌 한 번이 그날 남은 큐를 통째로 다음 날로 미룬다. 그리고 로그에
`대기열 비어있음` 이라는 **사실이 아닌 문장**이 남는다(BUGS #47 계열 — 배치 로그가
사실이 아닌 것을 말하는 문제).

`doc_worker` 는 락 파일로 동시 실행을 막지만 **5시간 stale 락 회수 경로**와 운영자의
수동 실행이 겹치는 창이 있다.

**[해결]** `CLAIM_RACE_MAX_ATTEMPTS = 5`. 경쟁에서 지면 **다른 행으로 다시 시도**한다.
`None` 은 SELECT 가 아무것도 못 찾았을 때만 돌려준다. 상한에 걸리면 `None` 을 주되
**왜인지 경고를 남긴다** — "비었다"와 구별되게. 상한을 두는 이유는 경쟁자가 계속
이기는 상황에서 이 실행이 영원히 머물지 않게 하기 위해서다.

**[회귀]** `test_refresh_trigger.py` §15 — 스레드 12개로 중복 0 / 남은 행 전부 claim /
행보다 많은 스레드는 정직하게 빈손 / refresh 행도 정확히 한 번만 집힘 + overwrite=True.
변이 확인: `CLAIM_RACE_MAX_ATTEMPTS = 1` 로 되돌리면 즉시 3건 FAIL.


--------

#131

**DB 값으로 파일을 지우는데 경로 탈출 방어가 없었다** — 읽기에는 있고 **삭제에만 없었다**

해결 (2026-08-18, Sprint 192)

**[경위]** Sprint 191 이 BUGS #128 을 고치며 `remove_stored_image_files()` 를 새로
만들었다. 그 직후 Security Audit 에서, 이 함수가 지우는 경로의 출처가
**`auction_image.storage_path`(DB)** 라는 점을 다시 봤다.

`api/v1/images.py` 는 **서빙**할 때 이미 같은 출처에 대해 봉쇄를 한다. 그 파일의 주석이
이유까지 적어 두었다:

> DB 값에서 경로를 만들기 때문에 문서 쪽보다 오히려 더 필요하다(관리 도구나 옛
> 마이그레이션이 넣은 값이 항상 얌전하다고 가정하지 않는다).

**그런데 지우는 쪽에는 그 검사가 없었다.** 읽기보다 삭제가 더 위험한데 방어는 읽기에만
있었던 셈이다. `storage_path` 가 어떤 이유로든 `..` 를 품으면 `documents/` 밖의 파일이
지워진다.

**[실측]** (2026-08-18, 스크래치)
```
수정 전   [안쪽, 바깥, ..탈출] 3개 요청 -> 지움 2개, 바깥 SECRET.txt **삭제됨**
수정 후   같은 요청            -> 지움 1개, 바깥 파일 보존 + 거부 경고 로그
```

**[해결]** `crawler/image_assets.py:is_inside_document_root()` 신설 —
`realpath` + `commonpath` 로 판정하고(드라이브가 다르면 `ValueError` 도 "밖"으로 취급),
`remove_stored_image_files()` 가 매 경로마다 확인한다. 밖이면 지우지 않고 경고만 남긴다.

**[계열 전수]** 소스 트리의 **모든 삭제 지점 8곳**을 AST 로 훑어 출처를 분류했다.

```
crawler/doc_crawler.py:233,240      move_into_place 의 src/tmp  (코드가 구성)
crawler/doc_crawler.py:325,336      wait_for_download 결과      (DOWNLOAD_DIR glob)
crawler/doc_crawler.py:468          status.*.tmp                (코드가 구성)
crawler/doc_crawler.py:760,771      wait_for_download 결과      (DOWNLOAD_DIR glob)
crawler/image_assets.py:401         ★ auction_image.storage_path (DB)  <- 유일한 DB 출처
crawler/image_crawler.py:383,423,458  image_path()/list_stored_images  (코드가 구성)
doc_worker.py:69                    LOCK_PATH 상수
```

**DB 값을 지우는 곳은 하나뿐**이었고 그것이 이번에 고친 함수다. 나머지는 전부 코드가
구성한 경로라 봉쇄가 필요 없다.

**[회귀]** `test_asset_pipeline.py` 18-B — 봉쇄 판정 3종 + 실제 삭제 동작(안쪽만 지움,
바깥 보존) + 빈/None 입력 + **삭제 지점 AST 전수**. 변이 확인: 봉쇄를 무력화하면
즉시 3건 FAIL(바깥 파일이 실제로 지워진다).

**[검사 자체의 결함도 하나 잡았다]** 처음 작성한 탈출 경로가 `..` 개수가 한 단계 모자라
**`documents/` 안에 머물고 있었다** — "탈출"이라 부르면서 탈출하지 않는 경로였다.
이제 목표 파일까지의 상대경로를 계산해 만들고, **정말로 바깥을 가리키는지 먼저
단언**한 뒤 봉쇄를 검사한다.


--------

#132

**매일 크롤(`mvp_scraper.py`)에 동시 실행 방지가 없다** — 워커에는 있고 크롤에만 없었다

해결 (2026-08-18, Sprint 194)

**[경위]** Scheduler/Queue 감사에서 "중복 실행 방지"를 배치별로 대조했다.
`doc_worker.py` 는 2026-08-16 Sprint 142 부터 락 파일을 갖고 있는데,
**매일 크롤에는 아무 방어도 없었다.**

**[왜 필요한가]** 이 배치가 건드리는 공유 자원이 둘이다.

```
logs/checkpoint.json   CheckpointManager.save() 가 **파일 전체를 읽어 고쳐 쓴다.**
                       두 실행이 겹치면 서로의 진행 상황을 통째로 덮어써, 이어받기가
                       엉뚱한 지점에서 시작하거나 사라진다(BUGS #23 이 원자적 쓰기로
                       막은 것은 "프로세스 죽음"이지 "동시 실행"이 아니다).
법원 서버              같은 사건을 두 배로 긁는다. 전체 크롤은 파생 추정 약 3.1시간
                       (1곳 186초 x 60곳, Sprint 190) — 겹칠 창이 아주 넓다.
```

예약 작업끼리는 기본 `MultipleInstances=IgnoreNew` 로 안 겹치지만, **운영자의 수동
실행이 스케줄 실행과 겹치는 경우**는 막지 못한다 — doc_worker 가 락을 둔 것과 같은 이유다.

**[해결]** doc_worker 의 구현을 **베끼지 않고** `storage/checkpoint.py` 의 `RunLock` 으로
올렸다. 이 저장소는 "규칙이 두 벌"에서 반복해 사고를 겪었다(BUGS #107/#112/#136/#161).

`CheckpointManager`(어디까지 했는가)와 `RunLock`(지금 누가 하고 있는가)은 같은 요구에서
나왔고 같은 규율을 쓴다 — 원자적 쓰기와 **시간 기반 죽은 소유자 판정**
(`reset_stale_queue()` 의 10분 회수와 같은 종류). 그래서 한 모듈에 둔다.

```
doc_worker    logs/doc_worker.lock    stale 5시간 (ExecutionTimeLimit 4시간보다 여유)
mvp_scraper   logs/mvp_scraper.lock   stale 6시간 (전체 크롤 파생 추정 3.1시간보다 여유)
```

**[검증]** `main()` 을 실제로 돌려 세 경우를 고정했다(라이브 크롤 없음, DB 무변경).

```
정상 실행   잡고 -> 돌고 -> 놓는다
락 충돌     아무것도 안 하고 exit 0. ★ **남의 락을 지우지 않는다**
예외        예외는 그대로 올라가되 락은 반드시 놓인다(finally)
```

두 번째가 특히 중요하다 — 진 쪽이 남의 락을 지우면 잠금이 무의미해지는 정도가 아니라
**먼저 돌던 실행이 무방비가 된다.**

**[중간에 가드가 두 번 막았다]** 처음에는 `storage/runlock.py` 를 새로 만들었다.
`test_schema_hygiene.py` 가 **"추적 파일이 미추적 파일을 import하지 않는다"** 로 잡았다 —
그 상태로 커밋하면 `doc_worker.py`/`mvp_scraper.py` 가 **둘 다** `ModuleNotFoundError` 로
죽는다(BUGS #105, 이번에는 매일 크롤과 워커가 동시에 죽는 형태). `git add` 는 승인
영역이므로 가드를 우회하지 않고 **이미 추적된 모듈로 옮겼다.**


--------

#133

**전수 가드가 BOM 파일 16개를 조용히 건너뛰고 있었다** — "전수"가 전수가 아니었다

해결 (2026-08-18, Sprint 195)

**[경위]** 내가 Sprint 191/192 에 추가한 AST 전수 가드 두 개를 스스로 감사하다 발견했다.

```python
with open(path, encoding="utf-8") as fh:
    try:
        tree = ast.parse(fh.read())
    except SyntaxError:
        continue          # <- 파일이 통째로 사라진다
```

이 저장소 소스 **70개에 UTF-8 BOM** 이 있다. `encoding="utf-8"` 로 읽으면 BOM 이
`U+FEFF` 로 남아 `ast.parse` 가 거부하고, `continue` 가 그 파일을 감사에서 지운다.

**[실측]** 스캔 범위(crawler/storage/api) 안에서만 **16개**가 빠졌다.
그중 `crawler/image_crawler.py` 에는 **실제 삭제 지점이 3곳** 있었다 —
삭제 지점 전수 가드가 "8곳"이라 보고했지만 진짜는 **12곳**이었다.

즉 Sprint 192 의 "삭제 지점 8곳 분류 결과 DB 출처는 하나뿐"이라는 결론은 **결론은
맞았지만 방법이 부실했다**(안 본 파일이 16개).

**[이 저장소는 이미 답을 알고 있었다]** 기존 가드 7개는 **전부 `utf-8-sig`** 를 쓰고
있었다. 새로 추가한 둘만 규칙을 안 따랐다.

**[해결]** 두 가지를 함께 고쳤다.
```
(1) encoding="utf-8" -> "utf-8-sig"
(2) 파싱 실패를 조용히 넘기지 않는다 —
    check("스캔 범위의 모든 파일을 실제로 읽고 팠다", unparsed, [])
```
(2)가 핵심이다. **"결함이 없어서 통과"와 "안 봐서 통과"는 겉으로 같다.**
못 본 파일이 하나라도 있으면 그 검사의 결론 자체가 성립하지 않는다.

**[변이 검증 2건]**
```
BOM 파일(storage/database.py)에 shutil.move 주입
   -> 수정 전: 안 보임 / 수정 후: FAIL (storage/database.py:1265)
파싱 불가 파일(crawler/resume.py) 주입
   -> 두 가드 모두 FAIL ("crawler/resume.py (SyntaxError)")
```

--------

#134

**`REFRESH_MAX_ITEMS_PER_RUN = 300` 이 실행 창의 400% 였다** — 근거 없이 정한 숫자

해결 (2026-08-18, Sprint 196)

**[경위]** Sprint 189 가 상한을 도입하며 300 을 적었고, 문서에도 "아직 실측 근거가 없는
값"이라고 남겨 두었다. 이번에 쟀다.

**[실측]** 실행 창 02:00~04:00 = 7,200초
```
기일 경과 적체 2,733행 소진   14초    (브라우저 없이 5.1ms, continue 로 sleep 도 건너뜀)
한 번도 못 받은 물건 20행      480초   (24초/행 = 이동 15.2 + 수집 + sleep 2)
남는 예산                      6,706초
재수집 1물건의 최악            4행 (spec/status/appraisal/image 동시)
-> 최악 기준 상한              6,706 / (4 x 24) = 69 물건

옛 값 300 의 최악 소요         300 x 4 x 24 = 28,800초 = 8.0시간 = 창의 400%
```

**최악 기준**으로 잡는다 — 어느 필드가 바뀔지 미리 알 수 없고, 여러 필드가 한꺼번에
바뀌는 날이 바로 재수집이 가장 필요한 날이다. 69 에서 여유를 두고 **60** 으로 정했다
(최악 5,760초 = 창의 80%).

**[모델을 코드로 검증했다]** 처음 계산은 기일 경과 행에도 `sleep(2)` 를 더해 5,480초가
나왔다. Sprint 146 의 실측치(13.9초)와 맞지 않아 코드를 다시 읽으니 그 분기는
`continue` 로 sleep 을 건너뛰고 있었다(`doc_worker.py:328`).
**모델은 실측과 코드 양쪽에 맞아야 한다.**

**[해결]** 값만 바꾸지 않고 **산술을 고정**했다.
`config/settings.py` 에 `DOC_WORKER_START_TIME` / `DOC_COLLECT_SECONDS_PER_ROW` 를 두고,
`test_refresh_trigger.py` §17 이 네 상수의 관계를 검사한다.

```
상한 x (물건당 최악 행 수) x (행당 초)  <=  실행 창
```

변이 검증: 60 -> 300 으로 되돌리면 즉시 2건 FAIL(400% 진단 포함).

**[이 검사가 잡지 못하는 것]** `DOC_COLLECT_SECONDS_PER_ROW` 는 실측을 사람이 옮겨 적은
값이다. 실제 수집이 느려졌는데 상수를 안 고치면 검사는 통과하면서 현실은 넘친다.
그 갱신은 운영 로그를 봐야 알 수 있다.


--------

#135

**감정평가서 PDF 가 실제로 내려왔는데 "탭 생성 실패"로 버려진다** —
다운로드가 성공할수록 탭이 안 생기는 구조

해결 (2026-08-18, Sprint 201)

**[경위]** Sprint 199 의 묶기 실증을 4종으로 확장하다 발견했다. `appraisal` 이
`success=False`("PDF 탭 생성 실패")로 끝났는데, 실행 직후 `downloads/` 에 PDF 가
와 있었다.

```
다운로드된 파일 : 2,528,908 B  sha e2df2671df009fe7
기존 appraisal  : 2,528,908 B  sha e2df2671df009fe7
동일한 문서인가 : True
```

**[근본 원인]** `get_download_driver_options()` 는
`plugins.always_open_pdf_externally: True` 를 켠다. Chrome 은 PDF 를 렌더링하지 않고
**곧바로 내려받는다.** `window.open(pdf_url)` 로 연 탭은 그릴 것이 없어 **뜨지도
않는다.** 그런데 `collect_appraisal()` 은 탭을 기다리고, 안 뜨면
**`wait_for_download()` 를 부르지도 않고** 실패로 끝냈다.

즉 **다운로드가 성공할수록 탭이 안 생기는데, 탭을 성공 조건으로 삼고 있었다.**

**[증거는 하나가 아니었다]** `downloads/` 최상위에 고아 PDF 8개(14.0MB)가 쌓여 있었고,
그중 4개는 Chrome 의 이름 충돌 회피 규칙이 붙어 있었다
(`... (1).pdf` ~ `(3).pdf`) — **같은 사건 문서를 네 번 받아 네 번 버렸다는 뜻**이다.

**[영향]**
```
수집 실패 보고     실제로는 성공했는데
재시도 예산 소모    MAX_DOC_RETRY 3회를 헛되이
디스크 누적         downloads/ 고아 14.0MB
사용자             받을 수 있는 문서가 FAILED 로 남는다
```
그리고 Sprint 197 의 결론("수집 실패와 원래 없음을 구분할 신호가 없다")을 더 무겁게
만든다 — **실패의 상당수가 사실은 성공이었다.**

**[해결]** 탭이 없으면 **다운로드가 왔는지부터 확인한다.** 둘 다 없을 때만 실패다.
더하기만 하는 변경이라 지금 성공하는 경로는 그대로다.

**[실환경 확인]** 수정 후 같은 물건으로 다시 돌리니 `appraisal success=True` (19.8초).
실제 법원에서 실제 다운로드가 이제 저장된다.

**[회귀]** `test_doc_storage_atomicity.py` 7j — 탭을 절대 만들지 않는 가짜 드라이버로
(실제 조건) 3경우 고정: 도착하면 저장 / 아무것도 없으면 실패(대조군) / 가짜 PDF 는 거부.
변이 검증: `if not new_handle: return result` 복원 시 즉시 2건 FAIL.

--------

#136

**매각물건명세서 다운로드도 고아로 남는다 (원인 미확정, 탐지만)**

미해결 — 탐지 추가 (2026-08-18, Sprint 201)

**[경위]** #135 를 고친 뒤 같은 실행에서 `spec` 은 여전히 실패했는데, 이번에는
**파일이 아예 오지 않았다**(`downloads/` 에 새 파일 0개). #135 와 다른 메커니즘이다.

그러나 고아 8개 중 **5개가 매각물건명세서**다 — 명세서 다운로드도 과거에 도착했는데
저장되지 않았다는 뜻이다.

**[가설 — 확정 아님]** `wait_for_download(timeout=30)` 이 끝난 **뒤에** 파일이 도착하면
그 실행은 이미 실패로 끝났고 파일은 고아가 된다. 다음 실행의 `before_files` 에는 그
고아가 이미 들어 있으므로 **영원히 회수되지 않는다.**

**[왜 고치지 않는가]** 원인을 확정하지 못했다. 타임아웃을 늘리는 것은 운영 로그 없이
정할 수 없는 튜닝이고(실행 창 예산과 얽힌다), 고아를 물건에 붙이는 것은 파일 이름만으로
소유자를 확정할 수 없어 위험하다(법원이 붙인 이름이다).

**[대신 한 것]** `audit_asset_integrity.py` [8] 에 상시 탐지를 붙였다.
```
[8] 다운로드 폴더에 남은 고아 파일
    고아 8개 / 14.0 MB
```
재발하면 즉시 드러난다. 정리는 소유자 확정이 필요해 승인 영역이다.


**#136 갱신 (2026-08-18, Sprint 202) — 원인이 같은 계열임을 확인하고 고쳤다**

Sprint 201 은 명세서 고아의 원인을 "타임아웃 뒤 도착" 으로 **가설**만 세우고 탐지만
붙였다. 계열 전수검색에서 `collect_spec()` 이 **`collect_appraisal()` 과 완전히 같은
모양**임을 확인했다.

```python
if not new_handle:
    logger.warning("spec 새 탭(문서뷰어) 감지 실패")
    return result            # <- 도착한 파일을 확인조차 안 한다  (#135 와 동일)
```

법원이 명세서를 뷰어 대신 **PDF 로 바로** 내려 주면, `always_open_pdf_externally` 때문에
그릴 것이 없어 탭이 뜨지 않고 파일만 도착한다. 그러면 이 분기가 그 파일을 버린다.
`downloads/` 고아 8개 중 **5개가 매각물건명세서**였던 것이 그 흔적이다.

**해결**: 탭이 없으면 짧게(5초) 다운로드 도착을 확인하고, 왔으면 **뷰어 단계를 건너뛰고
바로 저장**한다(뷰어는 다운로드를 얻기 위한 수단이지 목적이 아니다). 둘 다 없을 때만 실패.

**회귀**: `test_doc_storage_atomicity.py` 7k — 탭 없이 도착 -> 저장 / 아무것도 없음 ->
실패 / **뷰어 경로는 그대로 동작**(대조군). 변이 검증: 다운로드 확인을 빼면 2건 FAIL.

**남은 것**: 이번 실브라우저 실행에서 spec 은 파일이 **아예 오지 않아** 실패했다.
그 경로(뷰어 탭은 뜨는데 30초 안에 안 오는 경우)는 여전히 원인 미확정이고,
`audit_asset_integrity.py` [8] 이 계속 탐지한다.

--------

#137

**`wait_for_download` 호출부 가드가 `else:` 블록을 통째로 안 보고 있었다**

해결 (2026-08-18, Sprint 202)

**[경위]** #136 을 고치며 `collect_spec()` 의 뷰어 경로를 `else:` 블록으로 옮겼더니,
그 안의 `wait_for_download()` 호출이 **가드에서 사라졌다**(호출 지점 3개 중 2개만 검사).

가드는 이렇게 훑고 있었다.

```python
for parent in ast.walk(tree):
    body = getattr(parent, "body", None)      # <- body 만 본다
```

`ast.If` 는 `body` 와 **`orelse`** 를 갖는다. `try` 는 `finalbody` 도 갖는다.
`body` 만 보면 **`else:` / `finally:` 안의 코드는 감사 대상에서 통째로 빠진다.**

BUGS #133(BOM 파일을 조용히 건너뜀)과 같은 부류다 — **가드가 "전수"라고 말하면서
전수가 아니었다.**

**[해결]** 문장 리스트를 갖는 속성(`body` / `orelse` / `finalbody`)을 전부 훑는다.

**[변이 검증]** `else:` 안의 None 확인을 제거하니 즉시 2건 FAIL
(`line 341: 다음 문장이 확인 분기가 아니다`). 수정 전이었다면 **보이지 않았다.**


--------

#138

**몇 줄 고친 변경이 "전 파일 재작성"으로 나타난다 (CRLF 로 커밋된 파일)**

해결 (2026-08-18, Sprint 202)

**[경위]** Sprint 202 문서를 붙인 뒤 `git diff --numstat` 을 보다 발견했다.

```
docs/CHANGELOG.md    +3854 / -3560      실제로 늘어난 내용은 294줄
config/settings.py   +136  / -121       실제로 늘어난 내용은 15줄
```

**[근본 원인]** 이 저장소는 `core.autocrlf=true` 이고, 과거 Windows 에서
autocrlf 없이 커밋된 파일이 **73개** 있다(blob 자체에 CRLF 가 들어 있다).
git 은 **index 의 blob 에 CR 이 있으면 그 경로의 CRLF->LF 정규화를 끈다**
(이미 CRLF 로 커밋된 파일을 뒤늦게 뒤집지 않으려는 안전장치다).

그래서 이 부류는 작업본이 **글자 그대로 CRLF 를 유지해야** 한다.
파일을 통째로 읽어 고친 뒤 LF 로 다시 쓰면 **모든 줄이 달라진다.**

**[내 도구가 원인이었다]** 문서를 덧붙이는 헬퍼가 줄끝을 이렇게 판정하고 있었다.

```python
s = io.open(p, encoding="utf-8-sig").read()      # 텍스트 모드 = 개행 자동 변환
crlf = "\r\n" in s                               # <- **항상 False 다**
```

파이썬 텍스트 모드는 CRLF 를 읽는 즉시 LF 로 바꾼다. 그러니 이 판정은 **원리적으로
참이 될 수 없다.** "확인했다"고 믿고 있었지만 확인한 적이 없다.

**[영향]** 기능 결함은 아니다. 피해는 **리뷰 불가능**이다 - 3,681줄의 가짜 변경 속에
진짜 15줄이 묻힌다. 이 세션은 커밋이 금지되어 있어 다행히 이력에는 남지 않았다.

**[해결]**
1. 네 파일의 줄끝을 blob 규약으로 되돌렸다(가짜 변경 3,681줄 소멸).
2. 판정을 **바이트 기준**으로 바꿨다(`raw.count(b"\r\n") > 0`).
3. 구조 가드 `test_schema_hygiene.py` 27 신설.

**[가드가 한 번 틀렸다 - 그것도 기록한다]** 처음에는 "모든 추적 파일의 줄끝이 HEAD 와
같아야 한다"로 만들었다가 **정상 체크아웃 97개**를 잡았다. LF 로 커밋된 파일은
autocrlf 가 정규화하므로 작업본이 CRLF 여도 diff 에 나타나지 않는다 - 규약 위반이
아니다. **CRLF blob 만** 보도록 좁혔다.

**[변이 검증]** 두 방향으로 확인했다.
```
CHANGELOG 를 LF 로 되돌림   -> [FAIL] HEAD 는 CRLF(3560줄)인데 작업본이 LF 로 바뀌었다
열거를 5개로 자름           -> [FAIL] CRLF blob 을 실제로 찾아냈다 (4개)
```
두 번째가 중요하다. 이 가드는 **아무것도 안 보면서 초록**이 되기 쉬운 모양이라
하한(50개)을 함께 고정했다.


--------

#139

**전체 실행에서만 한 번 죽은 테스트 - 그런데 증거가 남지 않았다**

원인 미확정 / 증거 확보 장치 추가 (2026-08-18, Sprint 203)

**[관측]** Sprint 203 검증 중 `run_python_tests.py` 전체 실행에서
`test_doc_storage_atomicity.py` 가 **0.1초 만에 25단언에서** 죽었다.

```
[20/44] FAILED   test_doc_storage_atomicity.py   단언25   0.1s
```

단독 실행은 18.1초에 138단언 전부 통과한다. 이후 **전체 실행을 4번 더** 돌렸고
4번 모두 통과했다(5,485단언). 재현율 **1/5**.

**[왜 원인을 못 봤나 - 이게 진짜 문제다]** 러너는 실패한 파일의 출력을
`-v` 를 줬을 때만 보여 줬다. 그런데 실패를 **발견하는** 순간은 대개 `-v` 없이
돌린 순간이고, 다시 돌리면 통과하는 간헐 실패는 **그 한 번이 유일한 기회**다.
traceback 은 그대로 버려졌다.

이 저장소가 이미 배운 것과 같은 교훈이다 - 실패가 로그에 남지 않아 9일간 크롤
중단을 몰랐던 일(BUGS #47 계열). **실패했는데 흔적이 없으면 실패하지 않은 것과
구별되지 않는다.**

**[가설 - 확정 아님]** 이 테스트는 `documents/qa-atomic-<uuid>/` 를 저장소 안에
만들었다 지운다. 저장소는 **OneDrive 동기화 폴더 아래**에 있다
(`.../OneDrive/Desktop/dojoonpass`). 동기화가 파일을 잠그는 순간과 겹치면
일시적 `PermissionError` 가 날 수 있다. 0.1초에 죽은 것은 초반 파일 조작
단계에서 예외가 났다는 뜻과 맞는다.

확정하지 못했으므로 **코드를 고치지 않는다.** 임시 디렉터리를 저장소 밖으로
옮기는 것은 이 테스트가 "실 DOCUMENT_ROOT 아래에서 동작하는가"를 일부러
검사하고 있어서(1번 검사) 검사 자체를 무디게 만든다.

**[대신 한 것]** `run_python_tests.py` 가 실패/시간초과 파일의 **마지막 12줄을
`-v` 없이도 그 자리에서** 찍는다. 다음에 같은 일이 나면 traceback 이 남는다.

```
[ 1/ 1] FAILED   test_zz_mutation_probe.py   단언1   0.0s
        (종료코드 1 - 마지막 5줄, 전체는 -v)
        | Traceback (most recent call last):
        | RuntimeError: mutation probe
```

변이 검증: 일부러 죽는 테스트를 넣어 위 출력이 실제로 나오는 것을 확인했다.


--------

#140

**사진을 DB에 적기 전에 성공을 먼저 기록한다** — 화면이 "사진 있음"이라 말하는데 0장

해결 (2026-08-18, Sprint 208)

**[경위]** 이미지 트리거 체인을 관통 조사하다 `doc_worker` 의 성공 분기에서 발견했다.

```python
mark_queue_done(...)        # 큐 done + document_status READY
save_auction_images(...)    # auction_image 행
```

뒤엣것이 실패하면(DB 잠금, 파일 접근 실패 등) 바깥 `except` 가 큐를 되돌려 재시도는
되지만 **`document_status` 는 이미 READY 로 덮여 있다.**

**[재현]** fixture 로 `save_auction_images` 에 예외를 주입했다.

```
worker 종료 코드   1
document_queue     pending (retry 1)
document_status    IMAGE / READY      <- 볼 수 있다고 말한다
auction_image      0행                <- 가리킬 사진이 없다
```

재시도가 소진되면(`MAX_DOC_RETRY`) 그 거짓말이 영구가 된다.

**[근본 원인 — 문서와 사진의 비대칭]** 문서(spec/status/appraisal)의 실체 기록인
`doc_raw` 는 `mark_queue_done()` 이 **여는 트랜잭션 안에서** 쓰인다 — 원자적이라 이 창이
없다. 사진만 `save_auction_images()` 가 트랜잭션 밖에 있었다. 같은 계열을 전수로 훑어
확인했다(성공 기록 호출 지점 / doc_raw 쓰기 / auction_image 쓰기 전부).

**[해결]** 실체를 먼저 적고 성공을 나중에 적는다. 순서만 바꿨다. 남는 창(사진은 적혔는데
성공 표시가 없는 경우)은 **안전한 방향**이라 그대로 둔다 — 화면이 거짓말하지 않고
재시도가 `INSERT OR REPLACE` 로 덮는다.

**[회귀]** `test_asset_pipeline.py` 12-F. 변이(순서를 되돌림) -> 즉시 FAIL.

**[테스트 자체의 맹점도 하나 잡았다]** 대조군이 처음에 실패했는데 코드 결함이 아니라
`RETRY_INTERVAL_MINUTES=30` 때문에 같은 행을 즉시 다시 집지 못한 것이었다.
큐를 손으로 되돌린 뒤 돌리도록 고치고 그 이유를 주석에 적었다.

--------

#141

**API가 "READY인데 사진 0장"이라는 자기모순을 그대로 전달한다**

해결 (2026-08-18, Sprint 208)

**[경위]** #140 이 만들어 낸 상태를 API가 어떻게 다루는지 확인하다 발견했다.

```
_images_status(READY 기록, 사진 0장) -> "READY"
```

**[영향]** 화면은 "사진 있음"이라고 말하고 목록은 빈 상태가 된다. 오류도 빈 화면도
아니라 사용자가 원인을 알 수 없다.

**[해결]** `READY` 인데 사진이 0장이면 `COLLECTING` 으로 낮춘다. 실체가 없으니 아직
끝나지 않은 것이고 큐가 재시도 경로를 갖고 있다(행이 아예 없을 때 `COLLECTING` 이라
답하는 것과 같은 이유). `NO_IMAGE` / `FAILED` 는 그대로 전달한다 — 그 둘은
"볼 사진이 없다"와 모순되지 않는다.

**[정직하게 적는다 — 화면은 이미 안전했다]** 상세페이지는 `sortedImages.length > 0` 를
**먼저** 보고 아니면 NO_IMAGE/FAILED/수집중 순으로 분기한다. 그래서 READY+0장이어도
"사진 수집 중입니다"로 저하됐다. 즉 사용자에게 보이는 증상은 없었다.
이 수정은 화면을 고치는 것이 아니라 **API 가 스스로 모순된 답을 내지 않게** 하는 것이고,
프런트가 아닌 다른 소비자에게도 같은 보장을 준다.

**[회귀]** `test_asset_pipeline.py` 17 확장(자기모순 + FAILED 대조군 + 사진 있음 대조군).
변이(방어선 제거) -> 즉시 FAIL.


--------

#142

**재시도가 소진되면 재수집 의도가 사라지고, 그 뒤의 재시도는 구조적으로 헛돈다**

해결 (2026-08-18, Sprint 210)

**[경위]** Queue/Retry/Recovery 를 훑다 발견했다. Sprint 189 는 **중간 재시도**에서
의도가 사라지는 것을 막았다(`QUEUE_RESUME_STATUS`: `in_progress_refresh` -> `refresh`).
막지 못한 것은 **재시도 소진** 경로다.

```
refresh -> in_progress_refresh -> 실패 x3 -> failed      (refresh 정보 소실)
        -> 하루 뒤 reset_stale_queue() -> pending        (refresh 아님)
        -> claim(overwrite=False) -> "이미 존재. 스킵" -> done
```

`collect_spec()` 은 `doc_exists(...) and not overwrite` 이면 즉시 `success=True` 로
돌아온다. 즉 그 재시도는 **아무 일도 하지 않고 큐만 성공으로 종결시킨다.**
법원이 바꾼 문서는 영원히 옛것으로 남는다. 오류도 경고도 없다.

**[재현]** fixture 로 프로덕션 순서(claim -> 실패 x3 -> 하루 뒤 복구 -> 재claim)를 그대로 밟았다.

```
실패 1회 뒤   refresh              (Sprint 189 가 지킨 것)
실패 2회 뒤   refresh
실패 3회 뒤   failed               <- 여기서 소실
복구 뒤       pending
재claim       overwrite = False    <- 헛돈다
```

**[해결 — 상태값을 새로 만들지 않는다]** `document_status` 가 READY 라는 것은
**볼 수 있는 실체가 있다**는 뜻이다. 그런 행을 `pending` 으로 되돌리면 반드시 헛돈다.
그래서 `reset_stale_queue()` 가 **그 행만** `refresh` 로 되돌린다.
실체가 없는 행은 `pending` 이 맞다(처음 받는 것이다).

이미 DB 에 있는 증거로 판정하므로 큐 어휘가 늘지 않는다.

**[계약 변경 — 기존 테스트 하나가 옛 동작을 고정하고 있었다]**
`test_document_status_sync.py` 9번 (2)가 `failed`+`READY` 행의 회수 결과를
`pending` 으로 단언하고 있었다. **회귀가 아니라 계약 변경**이라 기대값을 `refresh` 로
바꾸고 이유를 그 자리에 적었다. 그 검사의 본래 의도(READY 를 COLLECTING 으로 덮지
않는다)는 두 번째 단언이 그대로 지킨다.

**[내 테스트의 결함도 가드가 잡았다]** 새로 쓴 회귀가 `datetime('now','-2 day')` 로
픽스처를 만들었는데 `localtime` 이 빠져 있었다 — `test_pipeline_integrity.py` 의
localtime 가드가 즉시 잡았다. 운영 코드는 `last_attempt_at` 을 파이썬 로컬 시각으로
쓰므로 UTC 로 넣으면 한국 기준 9시간이 어긋난다.

**[회귀]** `test_refresh_trigger.py` 20 (4검사, 대조군 포함).
변이(승격 블록 제거) -> FAIL 2건.

**[같은 계열 전수 검색]** `document_queue.status` 를 쓰는 지점을 전부 훑었다.
claim(`QUEUE_CLAIM_STATUS`) / 중간실패(`QUEUE_RESUME_STATUS`) / done / SKIPPED 2종은
전부 계보를 지키거나 종결 상태다. 계보를 잃는 곳은 이 한 곳뿐이었다.
`repair_empty_status_capture.py` 는 `status='done'` 행만 건드리므로 무관하다.


--------

#143

**"함수를 불렀다"를 "성공했다"로 읽는다** — 기록이 0장/0행이어도 큐가 done 으로 끝난다

해결 (2026-08-18, Sprint 214)

**[경위]** Sprint 208 이 순서를 바로잡은 뒤(실체 -> 성공), 그 수정이 **충분한지**를
A~F 여섯 시나리오로 끝까지 흘려보냈다. 두 곳에서 뚫렸다.

```
A 다운로드 실패          pending   OK
B 부분 수집             done      계약(아래)
C 파일이 디스크에 없다    done/READY/0행   ★
D 기록 중 예외          pending   OK
E 기록이 0장 반환        done/READY/0행   ★
F 전체 성공             done      OK
```

**[근본 원인]** `save_auction_images()` 는 **예외를 던지지 않고** 0장을 기록할 수 있다 —
디스크에 없는 항목을 전부 건너뛰고 `saved=0, skipped_missing=N` 을 돌려준다
(그 가드 자체는 옳다: DB 만 앞서가지 않게 하는 규약이다). 그런데 호출부가 그 반환값을
**로그로만** 썼다. 예외가 없으니 바깥 `except` 도 발동하지 않는다.

**[같은 계열이 문서에도 있었다]** `_record_doc_raw()` 의 docstring 이 이미 적고 있었다 —
*"파일이 없으면 ... doc_raw 행을 만들지 않는다 — 큐/상태는 **이미 done/READY로 갔지만**
... 여기서 뒤집지는 않는다(뒤집으려면 `collect_document()` 의 성공 판정을 고쳐야 한다)."*
그 "고쳐야 한다"가 미뤄진 채로 남아 있었다. 재현했다.

```
수집기가 files_saved=[spec.pdf] 를 돌려줬는데 그 파일이 없다
  -> queue=done / document_status=SPEC/READY / doc_raw=0행
  -> API available=true + viewer_url  (열면 없는 문서)
```

**[해결]** 성공 판정에 **결과를 쓴다.**

```
사진   수집기가 사진을 줬는데 saved==0 이면 실패로 되돌린다(부분 성공은 그대로 성공)
문서   수집기가 저장했다고 말한 파일이 실제로 없으면 실패로 되돌린다
```

범위를 좁게 잡았다 — `files_saved` 가 비면 검사하지 않는다("이미 존재. 스킵" 경로가
정상적으로 빈 목록을 돌려준다). `doc_exists()` 로 완성도를 요구하지도 않는다
(문서에도 부분 성공이 계약으로 있어 정책 변경이 된다).

**[B 가 done 인 것은 결함이 아니다]** `collect_images()` docstring 이 명시한다 —
"부분 성공을 전체 성공으로 뭉개지 않는다 ... **큐에서는 종결되지만** 로그와 반환값에
사실이 남는다." 한 장이라도 남으면 사용자가 볼 것이 생긴다. 회귀가 그 계약을 고정한다.

**[기존 asset 보존]** A/C/D/E 실패 시에도 이미 갖고 있던 사진 2장과 READY 화면 상태가
그대로 남는 것을 함께 고정했다. 저장소 계층이 이미 보장하지만
(`save_auction_images` 는 `saved and complete` 일 때만 지운다) 호출부를 바꾸면 깨질 수 있다.

**[회귀]** `test_asset_pipeline.py` 12-G(A~F x 기존asset 유무 2벌) + 12-H(문서 3경우).

**[변이 3종]**
```
저장 0장을 성공으로 뭉갬          -> FAIL 4건
성공 기록을 실체 기록보다 먼저     -> FAIL 5건
문서 파일 실재 검사 제거          -> FAIL 2건
```

--------

#144

**"이미 존재. 스킵"이 실체 기록까지 건너뛴다** — 파일은 있는데 `doc_raw` 0행이 영구로 굳는다

해결 (2026-08-19, Sprint 217)

**[경위]** BUG #143 후속으로 여섯 시나리오를 다시 흘려보내던 중, 아직 검사한 적 없는
칸에서 나왔다 — **실체는 저장됐는데 큐 성공기록이 실패하고, 그 뒤 재시도하는 경우.**

```
1회차   파일 spec.pdf 저장 성공 -> mark_queue_done() 이 실패(DB 잠금 등)
        트랜잭션이 통째로 롤백되므로 doc_raw / document_status 는 남지 않는다
        큐는 pending 으로 복귀 (여기까지는 설계대로다)

2회차   재시도. 그런데 파일이 이미 디스크에 있다
        -> collect_spec() 의 "이미 존재. 스킵" 분기
        -> files_saved=[] 로 success=True
        -> mark_queue_done() -> _record_doc_raw() 가 `if not files_saved: return`
        -> 큐 done / 화면 READY / **doc_raw 0행**
```

**[왜 영구인가]** 다음 수집도 파일이 있으니 **같은 스킵 분기**를 탄다.
스스로 회복되는 경로가 하나도 없다. `overwrite=True`(재수집)로만 벗어날 수 있는데,
그 트리거는 별개 조건이라 이 물건에 걸린다는 보장이 없다.

**[사용자에게 보이는 것]** API 는 `available=true` + `viewer_url` 을 준다(파일이 실제로
있으므로 이것 자체는 거짓이 아니다). 그런데 `page_count` / `file_size` / `doc_version`
만 **영원히 null** 이다. 프런트는 `page_count` 가 null 이면 페이지 이동 UI 를 아예
그리지 않는다 — `storage/database.py:mark_queue_done()` 이 "상세페이지 뷰어의 페이지
이동이 불가능했던 근본 원인"으로 적어 둔 바로 그 상태가, 고친 뒤에도 이 경로로 다시
만들어질 수 있었다.

**[같은 계열인데 사진 쪽은 이미 고쳐져 있었다]**
`crawler/image_crawler.py:_describe_existing()` 의 주석이 그대로 적고 있다 —
*"이미 받아 둔 사진은 다시 쓰지 않는다. 그래도 DB에는 실체를 다시 알려 줘야 한다 —
파일은 있는데 `auction_image` 행만 없는 상태(이 저장소의 단골 결함)를 여기서 스스로
복구한다."* **문서만 그 복구가 없었다.**

**[해결]** 스킵 분기가 **이미 갖고 있는 파일을 결과에 담는다.**
`crawler/doc_paths.existing_doc_files()` 를 신설해 `doc_exists()` 와 **같은 목록
(`DOC_REQUIRED_FILES`) · 같은 기준(존재 + 0바이트 초과)** 을 쓴다(규칙을 베끼지 않는다).
spec / status / appraisal 세 분기 전부에 적용했다.

정책은 바뀌지 않는다 —
- 파일을 **다시 쓰지 않는다**(스킵은 그대로 스킵이다. mtime/크기 무변경을 회귀가 고정)
- `previous_hash`/`new_hash` 는 그대로 비운다 → `document_version_log` 에 **거짓 개정을
  남기지 않는다**
- `_record_doc_raw()` 의 내용 무변경 판정(Sprint 187)이 있어 반복 실행이 `doc_version`
  을 부풀리지도 않는다

**[테스트 자체의 결함도 함께 고쳤다]** 이 결함을 **두 개의 기존 검사가 오히려 고정하고
있었다.**

```
test_asset_pipeline.py   "스킵 경로는 파일을 다시 쓰지 않는다"  files_saved == []
test_collect_documents.py "저장한 파일이 없다(재다운로드 안 함)" files_saved == []
```

둘 다 **의도는 옳고 증거가 틀렸다** — "다시 쓰지 않았다"의 증거로 빈 목록을 썼다.
의도를 그대로 두고 증거를 **파일이 그대로라는 사실**(mtime/크기 무변경)로 바꿨다.

**[운영 데이터 실측]** 지금 `auction.db` 는 `doc_raw` 556행이고 **READY 인데 doc_raw
가 없는 행은 0건**이다(2026-08-19 읽기 전용 조회). 즉 지금 터져 있는 상태는 아니고,
`backfill_doc_raw.py` 로 과거에 메운 뒤 다시 벌어지지 않은 것이다. 이번 수정은 **다시
벌어지지 않게** 한다.

**[회귀]** `test_asset_pipeline.py` 12-I(3종 문서 x 2회 실행 + API 응답),
12-J(큐 성공기록 실패 -> 재시도 간격 -> 재시도 성공).

**[변이]**
```
existing_doc_files() 가 빈 목록을 돌려줌     -> FAIL 21건
spec 스킵 경로만 옛 동작으로 원복            -> FAIL 7건
doc_raw 내용 무변경 판정 제거                -> FAIL 2건
auction_image INSERT OR REPLACE -> INSERT   -> 종료코드 1 (UNIQUE 위반으로 중단)
claim 의 재시도 간격 조건 제거               -> FAIL 16건
개정 기록에서 변경 감지 제거                 -> FAIL 7건
```

--------

#145

**동시 실행 잠금이 동시 실행을 막지 못했다** — 8개가 전부 락을 잡았다

해결 (2026-08-19, Sprint 217)

**[경위]** `storage/checkpoint.py:RunLock` 은 `doc_worker.py` / `mvp_scraper.py` 두 배치가
겹쳐 도는 것을 막는다. 막으려는 사고가 무엇인지도 모듈 주석에 적혀 있다 —
다운로드 폴더 교차 오염(같은 폴더를 보는 두 프로세스가 남의 파일을 자기 것으로 착각),
그리고 `logs/checkpoint.json` 덮어쓰기.

`test_doc_worker_recovery.py` §9 가 이 락의 계약을 이미 검사하고 있었다. 잡고, 또 잡아
보고, 놓고, 오래된 것을 회수한다 — **전부 순서대로.** 그런데 이 락이 막으려는 상황은
순서가 아니다. *"운영자가 수동으로 실행하는 동안 예약 실행이 겹치는 경우"* 는
**같은 순간**이다. 그 방향으로는 검사가 하나도 없었다.

**[재현]** 스레드 8개를 배리어로 묶어 동시에 `acquire()` 시켰다.

```
200라운드 x 8스레드   ->  200라운드 **전부**에서 8개가 동시에 성공
```

**[근본 원인]** 보고 나서 쓴다.

```python
if os.path.exists(self.path):     # <- 본다
    ...
with open(self.path, "w") as f:   # <- 쓴다.  그 사이가 통째로 열려 있다
```

즉 이 락은 "몇 초 차이로 시작한 실행"만 막았고 **같은 순간에 시작한 실행은 하나도
막지 못했다.** 하필 막으려던 것이 후자다.

**[해결 1 — 만드는 것 자체를 판정으로]** `os.open(..., O_CREAT | O_EXCL)` 는
"없으면 만들고 있으면 실패한다"를 **한 번의 시스템 호출**로 한다(Windows/POSIX 둘 다).
커널이 판정하므로 창 자체가 없다. 결과: 200라운드 전부 정확히 하나.

**[해결 2 — 회수는 한 번에 하나만]** 오래된 락 회수는 `지우고 -> 새로 만들기` 라
그 자체가 두 단계다. 여러 실행이 동시에 회수하면 늦은 쪽이 **먼저 회수한 쪽의 새 락을
지운다.** 세 가지를 차례로 재 봤다 — **추측하지 않고 전부 측정했다.**

```
os.remove 로 회수                 1,000라운드 중 4라운드에서 둘이 성공
지우기 직전 mtime 재확인 추가      그대로 4/1,000   <- 창이 좁아진 게 아니라 종류가 같았다
os.rename 로 회수 권한 중재        8스레드에서 2/40  <- 되돌리기가 셋 이상에서 남을 친다
회수 구역을 배타 토큰으로 감쌈      1,000라운드 전부 정확히 하나 (로깅을 끈 최악 조건)
```

**중간 시도 둘을 그대로 기록한다.** "재확인을 넣었으니 나아졌겠지"가 측정에서
그대로 틀렸다 — 넣지 않았으면 개선했다고 적었을 것이다.

토큰(`<락>.reclaim`)을 쥔 채 죽어도 멈추지 않도록, 오래된 토큰은 같은 기준으로 회수한다.
그 토큰이 남으면 회수가 `stale_hours` 동안 막히는데, 변이 시험에서 **실제로 그 상태를
만들어** 회귀가 우는 것을 확인했다.

**[회귀]** `test_doc_worker_recovery.py` 11 — 두 경우(평범한 경쟁 / 오래된 락 회수 경쟁)
각각 8스레드 x 40라운드로 **성공 수가 정확히 1** 인지 본다. "둘 다 실패"도 결함으로
본다(그날 배치가 통째로 안 도는 것이다). 토큰 잔재 0건도 함께 고정한다.

**[변이]**
```
O_EXCL 제거              -> 종료코드 1 (기존 §3 이 "두 번째 실행이 큐를 건드렸다"로 죽는다)
회수 토큰 중재 제거       -> FAIL 1건
회수 토큰을 안 지움       -> FAIL 1건
```

--------

#146

**전수 가드가 BOM 파일의 1행 import 를 못 본다** — 커밋하면 부팅이 깨지는 것을 막는 가드가 눈이 멀어 있었다

해결 (2026-08-19, Sprint 217)

**[경위]** "감사 도구 자체를 감사한다"로 가드들을 훑다가 나왔다.
`test_schema_hygiene.py` 6-B 는 **추적 파일이 미추적 파일을 import 하지 않는가**를 본다.
그 간선이 하나라도 있으면 커밋 순간 `ModuleNotFoundError` 로 API 가 통째로 죽는다
(BUGS #105). 즉 P0 급 가드다.

그 가드가 소스를 `encoding="utf-8"` 로 읽고 있었다.

**[근본 원인]** BOM 이 본문 맨 앞에 `\ufeff` 로 남는데, 검색 정규식은
`^\s*(?:from|import)` 로 시작한다. `\ufeff` 는 **공백이 아니다.**
따라서 **1행에 있는 import 는 영원히 매치되지 않는다.**

```
"import api.http_cache"          -> 매치됨
"\ufeff" + "import api.http_cache" -> 매치 안 됨
```

**[규모 실측]** 추적 `.py` **44개가 BOM** 파일이고, **그중 31개는 1행이 import** 다
(`api/v1/doc_stats.py`, `api/v1/item.py`, `api/v1/favorites.py`, `api/v1/registry.py` …).
그 31개 파일의 1행에 미추적 모듈 import 가 생기면 가드는 **초록을 유지한 채** 통과시킨다.

**[해결]** `utf-8-sig` 로 읽는다(BOM 을 벗겨 준다). 함께:

- 읽지 못한 파일(`OSError`)을 `continue` 로 삼키지 않고 **"미확인"으로 보고**한다.
  못 읽은 파일은 "간선 없음"이 아니다.
- 스캔 루프를 `_scan_import_edges()` 로 **분리**했다. 함수 밖에 있으면 회귀가 그
  동작을 직접 시험할 수 없다 — 인코딩을 되돌려도 "간선 0개"라는 **같은 초록**이 된다.

**[회귀]** 스캐너에 **BOM + 1행 import 인 탐침 파일**을 직접 먹여 간선이 잡히는지 본다.
없는 경로를 먹여 "미확인"이 미확인으로 보고되는지도 함께 본다.

**[변이]**
```
스캐너를 utf-8 로 되돌림        -> FAIL 1건 (탐침 간선을 못 잡는다)
못 읽은 파일을 조용히 삼킴       -> FAIL 1건
```

**★ 처음 만든 회귀는 무효였다.** "BOM 이면 utf-8 로는 못 읽는다"는 **차이만** 보여
줬을 뿐, 스캔 루프가 어느 쪽을 쓰는지는 보지 않았다 — 인코딩을 되돌려도 그대로
통과했다(변이로 확인). 그래서 스캐너를 분리해 **직접** 먹이는 방식으로 바꿨다.
"검사가 존재한다"와 "검사가 회귀를 잡는다"는 다르다.


--------

#147

**집계기 자신에게는 검사가 없었다** — 판정이 망가지면 결과는 초록으로 기운다

해결 (2026-08-19, Sprint 217)

**[경위]** `run_python_tests.py` 는 이 저장소의 모든 파이썬 회귀 결과를 집계한다.
44개 파일을 판정하는 도구인데 **자기를 검사하는 것은 하나도 없었다.**

위험한 것은 고장 나는 **방향**이다.

```
종료코드 검사가 사라진다   -> 실패한 파일이 PASSED 로 집계된다
판정문 정규식이 넓어진다   -> 단언 없는 스크립트가 PASSED 가 된다
SKIP 판정이 넓어진다       -> 실행되지 않은 것이 통과로 보인다
discover() 가 좁아진다     -> 새 테스트가 조용히 실행되지 않는다
```

전부 "N 통과 / 0 실패"라는 **정상과 똑같은 화면**으로 나온다. 이 실행기가 애초에
만들어진 이유가 그 착각(즉석 셸 반복문이 결과를 두 번 잘못 읽음)이었다.

**[해결]** `test_runner_contract.py` 신설(33단언). 고정하는 것:

```
종료코드 1순위      출력이 "ALL TESTS PASSED" 여도 non-zero 면 FAILED
[FAIL] 오탐 방지     통과하면서 [FAIL] 을 찍는 파일(실재한다)을 실패로 읽지 않는다
NO-VERDICT          종료코드 0 + 판정문 없음 = 통과가 아니다
SKIPPED             스스로 건너뛴 파일. 단, **단언이 있으면** 건너뛴 것이 아니다
실제 실행            가짜 테스트 3개(통과/실패/무판정)를 만들어 요약이 섞이지 않는지 본다
discover()          새로 생긴 루트 test_*.py 를 곧바로 찾는다
맹점 기록            하위 디렉터리의 test_*.py 는 **못 찾는다**(현재 0개, 사실로 고정)
```

**[변이]**
```
종료코드 검사 제거        -> FAIL 4건
판정문 없어도 PASSED      -> FAIL 2건
discover 범위 축소        -> FAIL 9건
실패해도 종료코드 0       -> FAIL 1건
```

**[이 검사 자신도 한 번 틀렸다]** 하위 프로세스 출력을 utf-8 로 디코딩했는데,
파이프로 받으면 파이썬이 **로캘 인코딩(cp949)** 으로 쓴다. 한글이 전부 깨져 요약
문구를 **항상** 못 찾았다 — 원인은 실행기가 아니라 이 검사의 디코딩이었다.
`PYTHONIOENCODING=utf-8` 로 못 박았다. 그리고 그 실패를 화면에 보여 주지도 못했다
(대체문자 U+FFFD 를 cp949 콘솔에 찍다가 죽었다) — `emit()` 으로 감쌌다.

--------

#148

**기록은 되는데 서빙은 404** — 저장 계층의 "있다" 기준이 읽는 쪽과 달랐다

해결 (2026-08-19, Sprint 218)

**[경위]** 검색목록 썸네일을 관통하는 검사를 쓰다가 서빙이 404 를 냈다. 픽스처 사진이
작아서였는데, 그 과정에서 **판정 기준이 세 곳에서 두 벌**이라는 것이 드러났다.

```
save_auction_images()         size <= 0 만 거절        <- 행을 만드는 곳
image_exists()                >= MIN_IMAGE_BYTES(1,024)
api/v1/images.py (서빙)        >= MIN_IMAGE_BYTES
```

**[재현]** 241바이트 사진 하나로 끝까지 흘려보냈다.

```
save_auction_images  -> saved=1        (기록된다)
image_exists()       -> False          (같은 저장소가 반대로 답한다)
API                  -> image_count=1 / images_status=READY / 대표 URL 을 준다
검색 목록            -> 그 URL 을 썸네일로 준다
그 URL               -> 404
```

즉 **상세페이지와 검색목록 양쪽에** "사진이 있다"고 표시해 놓고 열면 없다.
이 저장소가 BUGS #22/#50/#61/#64/#129 로 반복해 잡아 온 바로 그 어긋남이고,
이번에는 **행을 만드는 함수만 규약 밖**에 있는 형태였다.

`image_exists()` 의 docstring 이 그 규약을 이미 적어 두고 있었다 —
*"쓰는 쪽과 읽는 쪽의 '있다' 정의가 갈라지면 화면은 READY 인데 뷰어는 404 가 된다."*

**[해결]** `save_auction_images()` 가 `MIN_IMAGE_BYTES` 를 **같은 상수로** 참조해
하한 미만을 `skipped_missing` 으로 센다(조용히 버리지 않는다).

**[운영 영향 실측]** `auction_image` 45행의 최소 크기 **35,746바이트** — 영향 0건.
수집기가 이미 같은 하한으로 걸러내므로 정상 경로로는 도달하지 않는다.
막는 것은 잘린 파일 · 수동 조작 · 옛 backfill 이 남길 수 있는 행이다.

**★ [픽스처가 서빙 불가능한 데이터로 "정상"을 그리고 있었다]** 이 수정으로 기존 검사
**10건이 깨졌다.** 원인은 픽스처가 100~600바이트 사진으로 `auction_image 2행 /
images_status=READY` 를 단언하고 있었던 것 — **그 사진들은 실제로는 한 장도 서빙될 수
없는 크기**다. 즉 파이프라인 전체가 받아들이지 않는 데이터로 정상 상태를 그렸다.
`MIN_FIXTURE_PAD` 를 두어 한 번에 올렸다(개별 pad 는 "서로 다른 바이트"를 만들기
위한 것이므로 하한만 더하면 의도는 그대로다).

**[회귀]** `test_asset_pipeline.py` 12-P(하한 미만/이상 대조군 + API + 검색목록),
12-Q(판정처 3곳이 **같은 상수**를 보는가).

**[변이]**
```
저장 하한을 옛 기준으로 되돌림      -> FAIL 11건
하한을 숫자로 함수 안에 박음        -> FAIL 2건
```

★ **두 번째 변이는 처음에 통과했다.** 12-Q 가 본문에 `"MIN_IMAGE_BYTES"` 문자열이
있는지만 봤는데, 변이가 만든 `_MIN_IMAGE_BYTES = 1024` 가 그 부분 문자열을 포함했다.
AST 로 **숫자 상수 대입**과 **단일 소스 import 여부**를 보도록 고친 뒤에야 잡혔다.

--------

#149

**전체 화면 모달이 스크린리더에 모달이라고 말하지 않았다** — 뒤의 내용이 계속 읽힌다

해결 (2026-08-19, Sprint 221)

**[경위]** 접근성 구조 감사(색·크기는 건드리지 않고 구조만) 중 상세페이지의 전체 화면
오버레이 둘을 확인했다.

```
문서 뷰어      <div className="fixed inset-0 bg-black bg-opacity-50 flex flex-col z-50">
사진 라이트박스 <div className="fixed inset-0 bg-black bg-opacity-90 flex flex-col z-50">
```

둘 다 화면 전체를 덮는데 **`role="dialog"` 도 `aria-modal` 도 없었다**
(저장소 전체 검색: `role="dialog"` 0건, `aria-modal` 0건).

**[무엇이 잘못되나]** 스크린리더는 그것이 모달인지 모른다. 그래서

```
"모달이 열렸다"를 알리지 못한다
뒤에 있는 검색 결과·가격·주소가 **계속 읽힌다**
사용자는 자기가 어디에 있는지 알 수 없다
```

**[제품 결정이 아니다]** `role`/`aria-modal`/`aria-labelledby` 는 **픽셀을 하나도
바꾸지 않는다.** 색·글자 크기·간격과 달리 디자인 논쟁의 여지가 없어 그대로 고쳤다.
제목 `<h2>` 에 id 를 주고 `aria-labelledby` 로 가리켜 모달의 **이름**도 준다.

**[이미 있던 것]** 함께 확인해 회귀로 고정했다.

```
Escape 로 닫기 / 좌우 화살표로 사진 이동   있음 (키보드 탈출구가 있다)
닫기 버튼의 aria-label="닫기"              있음 (아이콘만 있는 버튼에 이름이 있다)
고정 height 없음(flex-1 + min-h-0)         큰글씨에도 깨지지 않는다
```

**[아직 없는 것 — 기록만 한다]** **포커스 트랩이 없다.** Tab 을 계속 누르면 포커스가
모달 뒤 배경으로 빠져나간다. 넣으려면 첫 진입 포커스·마지막에서 순환·닫을 때 원래
자리로 복귀를 직접 관리해야 해서 동작 변경 폭이 크다. 별도 작업으로 남긴다.

**[회귀]** `test_frontend_accessibility.py` 9 — 전체 화면 오버레이(`fixed inset-0`)를
전수로 찾아 `role`+`aria-modal` 을 요구하고, `aria-labelledby` 가 **실재하는 id** 를
가리키는지, Escape 탈출구가 있는지까지 본다. 열거 하한도 함께 건다.

**[변이]**
```
라이트박스에서 role/aria-modal 제거      -> FAIL 1건
aria-labelledby 가 없는 id 를 가리킴      -> FAIL 1건
```

--------

#150

**폼 컨트롤 16개에 접근 가능한 이름이 없었다** — 스크린리더가 "콤보박스"라고만 읽는다

해결 (2026-08-19, Sprint 222)

**[경위]** 접근성 감사에서 `/search` 의 아코디언을 **전부 펼친 뒤** 실측했다.
접힌 상태만 보면 컨트롤이 5개뿐이라 과소 측정이 된다.

```
폼 컨트롤 93개 중 접근 가능한 이름이 없는 것 16개
  select 9 / input[type=date] 2 / placeholder 만 있는 text input 5
```

**[무엇이 잘못되나]** 보이는 레이블이 `<span>` 으로 그려져 있어 **컨트롤과
프로그래밍적으로 연결돼 있지 않다.**

```
감정가        <span>감정가</span>
              <select>...</select>   <- 스크린리더: "콤보박스"
              <select>...</select>   <- 스크린리더: "콤보박스"
```

최소/최대가 나란히 둘이라 **어느 쪽인지도 알 수 없다.**
`type="date"` 는 보이는 텍스트가 아예 없다.
`placeholder` 는 **입력을 시작하면 사라지므로** 이름이 아니다(WCAG 3.3.2).

**[제품 결정이 아니다]** `aria-label` 은 **픽셀을 하나도 바꾸지 않는다.**
게다가 이 저장소는 **이미 그 패턴을 쓰고 있었다** — `시/도`, `시/군/구`, `법원`
select 에는 `aria-label` 이 붙어 있다. 빠진 자리에 같은 방식을 적용했을 뿐이다.

**[해결]** 공용 컴포넌트 둘을 고쳐 select 8개가 한 번에 해결됐다.

```
RangeSelect / PriceRangeSelect   `${label} 최소` / `${label} 최대`
SearchForm                       읍/면/동 · 세부주소 · 사건번호 연도/번호 · 진행상태
                                 · 매각기일 시작/종료
SearchPresets                    검색조건 이름
login                            이메일 · 비밀번호
```

수정 후 실브라우저 재측정: **93/93 이름 있음**(수정 전 77/93).

**[회귀]** `test_frontend_accessibility.py` 10 — **감싸는 `<label>` 로는 이름을 줄 수
없는 부류**만 본다(`<select>` / `type="date"` / `placeholder` 가 있는 input).
체크박스 77개는 감싸는 label 패턴이라 정적으로 판정하기 어려워 대상에서 뺐다.

**[★ 이 검사의 앞선 판본이 거짓 결과를 냈다]** `<select[^>]*>` 로 여는 태그를 잡았더니
**`onChange={(e) => f(e)}` 의 `>` 에서 잘려** "select 7개 전부 이름 없음"이라고 보고했다
(브라우저로는 전부 이름이 있었다). JSX 는 속성 안에 화살표 함수가 들어가므로
**중괄호 깊이를 추적**해야 한다. 지금 검사는 그 추출기를 **자기 검증**한 뒤 쓴다
(이름 있는 샘플 / 없는 샘플 둘 다).

**[변이]**
```
select 의 aria-label 제거          -> FAIL 1건
date input 의 aria-label 제거      -> FAIL 1건
placeholder 만 남기고 제거          -> FAIL 1건
```


--------

#151

**모달이 키보드 포커스를 가두지 않았다** — 열자마자 오버레이 뒤 버튼에 서 있게 된다

해결 (2026-08-19, Sprint 223)

**[경위]** Sprint 221이 `role="dialog"`/`aria-modal`을 붙였지만 그것은 **스크린리더에게만**
하는 말이다. 순차 포커스 이동은 브라우저 규칙이라 코드로 잡아야 한다. 실브라우저
(`/properties/505`, 진짜 마우스 클릭·진짜 Tab 키)로 잰 값:

```
모달을 연 직후 포커스        "대표 사진 크게 보기"  <- 모달 **뒤**의 버튼
모달 안 포커스 가능 요소      3개 / 화면 전체 24개  -> 21개가 오버레이 뒤에 살아 있다
Tab 한 번                    "전경도 1번 크게 보기"(top 415, left 346) = 완전히 가려진 버튼
Escape 로 닫은 뒤            포커스가 헤매던 자리 그대로 (여는 버튼으로 복귀 안 함)
```

**[해결]** `src/lib/useFocusTrap.ts` 신설 — (1) 열릴 때 모달 안 첫 요소로 이동,
(2) Tab/Shift+Tab 양끝 순환 + Tab 이 아닌 경로는 `focusin` 으로 되돌림,
(3) 닫힐 때 열기 전 포커스로 복귀(사라졌으면 억지로 되돌리지 않는다).
두 모달(문서 뷰어/사진 라이트박스)에 배선. **픽셀 무변경.**

수정 후 실측: 열기 -> '닫기' / Tab x3 순환 / Shift+Tab 역순환 /
Escape -> **여는 버튼 바로 그 노드**로 복귀(`===` 비교) / 밖으로 강제 포커스 -> 되돌아옴.

**[★ 없는 결함을 만들 뻔했다]** 문서 뷰어의 **첫 열기만** 포커스가 안 간다는 결과가
반복해서 나왔고 "PDF iframe 이 포커스를 뺏는다"는 설명까지 세웠다. **틀렸다.**
탭이 **보이지 않는 상태**(`visibilityState: hidden`)에서 `element.focus()` 를 부르면
`activeElement` 는 바뀌지만 **focus/focusin 이벤트가 전혀 발생하지 않는다**
(직접 단 focusin 리스너가 0회 호출됐다). 탭을 보이게 하고 진짜 마우스 클릭으로 재니
첫 열기부터 정상이었다. **보이지 않는 탭에서 잰 포커스 값은 근거로 쓰지 않는다.**

**[회귀]** `test_frontend_accessibility.py` 11 — 훅이 네 가지를 다 하는가 +
**복귀 전에 focusin 감시를 끄는 순서**까지 + 모든 `role="dialog"` 에 트랩이 배선됐는가.

**[변이]** ref 제거 / 복귀 제거 / focusin 감시 제거 / 해제 순서 뒤집기 -> 4/4 FAIL.
★ 첫 판본은 `"'focusin'" in src` 로 봐서 **감시 제거 변이를 놓쳤다**(해제 줄에 같은
문자열이 남는다). `addEventListener('focusin'` 로 조인 뒤 재확인했다.

--------

#152

**나중에 나타나는 안내가 스크린리더에 아무것도 전달되지 않았다** (WCAG 4.1.3)

해결 (2026-08-19, Sprint 223)

**[경위]** 실브라우저 `/search` 실측 — `aria-live`/`role="alert"`/`role="status"` 를 가진
요소가 **0개**였다. 이 서비스의 실패 안내는 전부 비동기 결과로 나중에 나타나는데
(로그인 실패, 관심물건 담기 실패, 검색조건 저장 실패, 목록 로드 실패) 나타날 때
아무것도 읽히지 않았다. 특히 로그인은 **제출해도 반응이 없는 화면**이 된다.

**[해결 (a)]** 개별 상태 메시지 **13곳**에 `role="alert"` / `role="status"`.
조건이 감싸는 **여는 태그 자체**에 붙인다 — 안쪽 자식에 붙이면 바깥이 나타나는 순간을 놓친다.

**[해결 (b)]** 검색 결과는 `SearchScreen` 에 **항상 존재하는 `sr-only` 한 줄**로 알린다.
검색은 `router.push()` 를 transition 안에서 부르는 클라이언트 전환이라 페이지가 다시
읽히지 않고, 결과 목록에 `aria-live` 를 달면 **0건일 때 그 문단이 통째로 사라져** 아무것도
알리지 못한다. 실측: 소프트 전환 후에도 **같은 DOM 노드가 유지되고 글자만 바뀐다**
(정렬 변경 / 실제 0건 검색 둘 다 확인), 렌더 크기 1x1 px 로 화면에는 보이지 않는다.

**[해결 (c)]** 시/군/구 목록 로드 실패를 `aria-describedby` 로 그 select 에 묶었다 —
`role="alert"` 는 나타나는 순간만 읽히고, 나중에 Tab 으로 도착한 사람은 이유를 모른다.

**[회귀]** `test_frontend_accessibility.py` 12 — 탐지기 자기검증 3건 + 상태 메시지 13곳
전부 알림 역할 보유 + `aria-describedby/labelledby` 가 **있는 id** 를 가리키는가 +
검색 화면의 한 줄이 **조건부로 렌더되지 않는가**.
이미 항상 존재하는 live region 을 가진 화면은 **중복 알림 방지**로 개별 검사에서 제외한다.

**[변이]** 로그인 alert 제거 / 상태 한 줄 제거 / 그 줄을 조건부로 / describedby 제거 /
없는 id 가리키기 -> 5/5 FAIL.

--------

#153

**화면 4개에 `main` 랜드마크가 없었다** — 본문으로 건너뛸 수단이 없다 (WCAG 2.4.1)

해결 (2026-08-19, Sprint 223)

**[경위]** Sprint 221의 검사는 `<main>` 사용 횟수를 **저장소 전체로 합산**해 `>=1` 만 봤다.
검색 화면 하나가 갖고 있으면 나머지가 전부 없어도 통과한다 — 실제로 그랬다.
실브라우저로 화면별로 재 보고서야 드러났다.

```
/search 1 · /mypage 1(본문만)
/properties/{id} **0** · /favorites **0** · /properties/recent **0** · /login **0**
```

**[해결]** 감싸는 `<div>` 의 **태그만** `<main>` 으로 교체(className 동일 = 픽셀 무변경).
로딩·실패 분기에도 넣어 어느 상태에서도 랜드마크가 있다.
실측: 상세 grid `622px 622px` / 컨테이너 1320px / 가로 오버플로 0, 로그인 `min-height: 911px` 그대로.

**[회귀]** `test_frontend_accessibility.py` 13 — 화면(`page.tsx` / `*Screen.tsx`, 리다이렉트·위임 제외)
마다 `<main>` 이 있는가 + **화면 루트(`min-h-screen`) 개수만큼** 있는가.
★ 후자를 넣은 이유: 파일 단위 검사는 **분기 하나가 랜드마크를 잃어도 통과했다**(변이로 확인).
**맹점**: 화면 루트를 `min-h-screen` 이 아닌 방식으로 쓰면 이 비교는 무력해진다.

**[변이]** 상세에서 main 하나 제거 / 로그인에서 main 제거 -> 2/2 FAIL.

--------

#154

**검사 도구가 저장소 사본(스테일 worktree)까지 검사하고 있었다**

해결 (2026-08-19, Sprint 223)

**[경위]** `test_console_encoding.py` 의 `SKIP_DIRS` 에 `.claude` 가 없어
`.claude/worktrees/sprint95-false-success-audit/`(Sprint 95 시점 커밋 `c4f74e6` 의
**저장소 통째 사본**)까지 훑었다.

```
제외 전   스캔한 .py 298개 중 **101개(34%)가 그 사본**
제외 후   197개
```

아무도 실행하지 않는 얼린 스냅샷에 규칙을 강제했고, 그 안에 위반이 하나라도 있었으면
**현재 코드가 멀쩡한데도 빨간불**이 켜졌을 것이다. 형제 검사인 `test_doc_path_safety.py` 는
이미 `.claude` 를 제외하고 있었다.

**[해결]** `.claude`(+ `venv`/`.venv`/`htmlcov`)를 제외해 두 검사의 범위를 맞췄다.
스테일 worktree 자체는 그대로 둔다 — `git worktree remove` 는 승인 영역이다.

**[회귀]** 스캔 범위를 잠근다 — 사본을 훑지 않는다 + **0개를 훑고 조용히 통과하지 않는다**(하한).

**[변이]** `.claude` 를 SKIP_DIRS 에서 빼기 -> FAIL.
