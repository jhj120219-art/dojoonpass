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
