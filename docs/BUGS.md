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
