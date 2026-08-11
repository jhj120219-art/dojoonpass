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
