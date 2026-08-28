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

**해결 (2026-08-11 Sprint 51 조치 / 2026-08-28 Sprint 272 실측 확인).**

> 이 항목이 제시한 두 선택지 중 **"화면을 폐지하고 `/`로 redirect"** 가 Sprint 51 에
> 실제로 수행됐는데(#34 참고), 이 줄만 미해결로 남아 있었다. 2026-08-28 에 세 주장을
> 각각 다시 쟀다.
>
> ```
> Supabase 로 경매 데이터를 직접 조회하는 화면    0건  (src/ 전수)
> 지역 formatPrice 중복 정의                    0건  (정의는 lib/format.ts 하나)
> 로그아웃 경로                                 공용 SiteHeader 로 이동 (8개 화면)
> src/app/properties/page.tsx                  redirect('/') 세 줄
> ```
>
> **그런데 그 아키텍처 규칙을 지키는 검사가 하나도 없었다.** `docs/CLAUDE.md` 가
> *"auction data always comes from the Python API, never queried from Supabase
> directly"* 라고 적어 두었을 뿐이라, 누가 다시 화면에서 테이블을 조회해도 알려 줄
> 것이 없었다 — #17 이 만든 피해가 **조용한 오답**(404 도 없이 엉뚱한 물건)이었던
> 만큼 그 침묵이 그대로 재현된다.
>
> `tests/supabase-boundary.test.mjs` 를 신설해 고정했다. Supabase 클라이언트 사용
> 자체는 허용하고(`auth.*` 만), `.from('...')` 데이터 질의만 막는다. 변이 3/3 검출 —
> 그중 하나는 **`/properties` 가 다시 Supabase 목록을 그리는 #17 당시 상태**다.

이하는 2026-08-07 발견 당시 기록(보존).

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

**해결 (2026-08-28 Sprint 272 재측정으로 확인).** 아래 원 기록은 그대로 둔다.

> **재측정 (2026-08-28)** — 이 항목은 `PROPERTY_TYPE_ALIASES` 가 생기면서 이미
> 해소돼 있었는데 문서만 미해결로 남아 있었다. 실제 `auction.db` 로 다시 쟀다.
>
> ```
> 다세대주택  패턴['다세대주택','다세대'] -> 379건   (#33 이 0건이라고 적은 그 항목)
> 오피스텔 307 · 근린시설 369 · 아파트 201 · 단독주택 85 · 연립주택 136
>
> DB 18종 1,876건 중 **어떤 UI 항목으로도 걸리지 않는 값: 0종 0건**
> 한 항목이 4종 이상을 끌어오는 과다매칭: 0건
> 별칭 다리가 실제로 지고 있는 무게: 1,607건
> ```
>
> 남아 있는 0건 항목(묘지/광업권/덤프트럭 등)은 **그런 물건이 아직 없다**는
> 사실이지 어휘 문제가 아니다 — `api/v1/search.py` 주석이 같은 판단을 이미
> 적어 두었다.
>
> **그런데 그 계약을 지키는 검사가 하나도 없었다.** 크롤러가 새 표기를 저장하거나
> 누가 트리 항목을 고치면 그 물건은 화면에서 **조용히 사라진다** — 오류도 없이
> 그냥 0건이 된다. #33 이 정확히 그렇게 생겼고 발견까지 오래 걸린 이유도 그것이다.
> `test_property_type_vocabulary.py` 를 신설해 양방향(도달성/과다매칭)을 고정했다.
> 변이 4/4 검출 — 그중 하나는 **별칭표를 비워 #33 당시 상태를 재현**한 것이다.

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
상한을 둔다. 이 수치가 커지면 크롤러가 계속 잘못 분류하고 있다는 신호다.

> **★ 2026-08-24 Sprint 251 — 역방향 상한을 5 → 3 으로 조였다.**
>
> 위 실측이 처음부터 **3건**(id=542 / 1806 / 6311)이었는데 상한만 5로 적혀 있었다.
> 어떤 측정에도 근거가 없는 **2칸의 여유**였고, 그만큼 새 오분류가 조용히 통과한다.
> 2026-08-24 재실측도 **같은 3건**이다(앞 방향은 여전히 2건 = 상한 2, 정확히 맞다).
>
> 비공허 확인: 상한을 2로 낮추면 이 3건이 그대로 걸린다(검사가 실제로 센다).
>
> 크롤이 재개돼 선박 물건이 새로 들어오면 이 값이 늘 수 있다 — 그때는 **늘어난 행이
> 새 결함인지 같은 부류인지 확인한 뒤** 상한을 올릴 것(Sprint 121이 sido 상한을
> 4→5로 올릴 때 쓴 방식과 같다).

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
`sido`가 남는다. ~~다만 만료 물건이라 검색(D7 기본 제외)에는 나오지 않는다.~~ 운영 데이터를
임의로 고치지 않았다 ― 필요하면 4행 UPDATE로 끝나는 작업이다.

> **★ 2026-08-24 Sprint 251 정정 — "검색에는 나오지 않는다"는 절반만 맞다.**
>
> `src/app/search/SearchForm.tsx:643` 에 **"종결물건 포함" 체크박스**가 있다
> (`includeClosed` → `include_closed=true`). 사용자가 그것을 켜면 이 4행이 그대로 나온다.
>
> ```
> 실측 2026-08-24 (읽기 전용 HTTP)
>   GET /api/v1/search?include_closed=true&sido=서울  -> 시흥시(경기) 물건 id=8160 이 포함된다
>   4행 현황  id=550  '서울'->'인천'   인천 계양구 (건물명 "뉴서울아파트")
>             id=1787 '부산'->'경남'   경남 양산시 (도로명 "부산대학로")
>             id=8160 '서울'->'경기'   경기 시흥시 (도로명 "서울대학로")
>             id=9977 '세종'->'제주'   제주 제주시 (법인명 "뉴세종하우징")
> ```
>
> 즉 "지금은 사용자에게 안 보인다"가 아니라 **"체크박스 한 번 거리에 있다"** 이다.
> 방향도 둘이다 — `sido=서울` 을 고른 사용자에게 **남의 지역 물건이 섞여** 보이고,
> `sido=인천`/`경남`/`경기`/`제주` 를 고른 사용자에게는 **제 지역 물건이 빠진다.**
>
> 등급은 그대로 둔다(만료 물건 4행). 다만 "안 보인다"를 근거로 정리를 미루면 안 된다는
> 것만 바로잡는다. 정리는 4행 UPDATE 이고 **운영 데이터 변경이라 승인 영역**이다
> (`backfill_region_normalize.py --apply` 가 sido 4행 + sigungu 207행을 함께 고친다 —
> 2026-08-24 dry-run 으로 422건 예정 확인, 실행하지 않았다).
>
> 같은 세션에 `test_pipeline_integrity.py` §12 의 `sido` 상한도 **5 → 4** 로 조였다.
> 5는 지금 이 DB 에 없는 id=11903(Sprint 121 사례) 때문에 올려 둔 값이라, 실측보다
> 하나 헐거워 **새 오분류 하나가 조용히 들어와도 통과**하는 상태였다.

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

~~고치려 해도 **대상을 찾을 수 없다.** 결제와 구독을 잇는 열쇠가 아예 없다.~~
→ **해소 확인 (2026-08-23 Sprint 267 재실측) - 이 열쇠는 이미 만들어져 있다.**

```
migration_history          019_add_subscription_payment_id.sql  적용됨(2026-08-13)
subscriptions 스키마        payment_id INTEGER REFERENCES payments(id)  실제 컬럼 존재
api/v1/payments.py:440      create_subscription(..., payment_id=payment_id)로 실제로 채운다
                            (SUBSCRIPTION 결제 생성 시 같은 트랜잭션 안에서 함께 커밋)
```

이 문단이 적힌 시점(Sprint 96, 2026-08-13)에 이미 같은 세션/그 직후에 이 컬럼이
추가된 것으로 보인다 - `create_subscription()`의 docstring 자체가 "이 인자는 BUGS #94
때문에 추가했다"고 적어 두었는데, 이 문서의 문단만 갱신되지 않은 채 "열쇠가 없다"로
남아 있었다. **정책 결정(아래)과 혼동하지 말 것 - 식별자 인프라는 이미 완료됐고,
"환불 시 무엇을 할지"만 정책 결정 대기다.**

**[정책 결정이 필요한 부분 - 이것만 남았다]** 전액 환불 시 구독을 어떻게 할 것인가 ―
즉시 해지 / 결제 주기 끝까지 유지 / 일할 계산. 부분 환불은 또 다르다.
`docs/roadmap.md`에 선택지를 정리했다(이 문서도 함께 정정함). **임의로 정하지 않았다.**

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

~~미해결 — 승인 필요~~ → ~~부분 해소 확인 (2026-08-23 Sprint 267 재실측)~~
→ **★ 미해결 (2026-08-24 Sprint 251 재실측 — 다시 0개다)** (2026-08-18, Sprint 189 발견)

> ### ★★ [2026-08-24 Sprint 251] 바로 아래 2026-08-23 블록은 **이 저장소 상태에서 재현되지 않는다**
>
> 이 문서 자신의 교훈("정상 동작 중은 매번 다시 재는 대상이지 상수가 아니다")을 한 번 더
> 적용했다. 2026-08-24 08:45~08:55 실측:
>
> ```
> Get-ScheduledTask 전체 249개 중 이 저장소를 가리키는 작업   0개
>   - Action 문자열(Execute+Arguments+WorkingDirectory) 전수 매칭   0개
>   - 이름 정규식 (?i)dojoon                                        0개
>   - audit_schedule_health.py (schtasks 기반 독립 도구)            0개
> logs/daily_run.log   mtime 2026-08-11 17:05 / 마지막 완료줄 "Finished at 2026-08-02"
> auction_item          1,876행 / crawl_date max 2026-08-12
> 기일 남은 물건         0건 (가장 늦은 기일 2026-08-19)
> GET /api/v1/search    total 0    (include_closed=true 면 1,876)
> ```
>
> 즉 **DailyCrawl 축도 돌지 않는다.** 아래 블록이 적은 "2026-08-23 04:35:15 완료 / 수집
> 273건 / 기일 남은 물건 291건"은 이 저장소의 `auction.db` 에서는 나올 수 없는 숫자다 —
> DB 경로는 제품 코드가 쓰는 것을 그대로 물었고(`storage.database.DB_PATH` →
> `...\dojoonpass\auction.db`, 5,246,976 bytes, 저장소 안의 다른 `.db` 는 0바이트
> `auction_data.db` 뿐), **이 세션이 열기 전 그 파일의 mtime 은 2026-08-21 19:19** 이었다.
> 어느 쪽이 옳은지 단정하지 않는다 — **지금 이 환경에서 잰 값만 적는다.**
> 2026-08-21 Sprint 247도 네 가지 방법으로 "등록 0개"를 확인했다.
>
> **판정: #123 은 부분 해소가 아니라 미해결이다.** 세 작업 다 등록해야 한다
> (`register_scheduler_tasks.ps1` — 등록은 여전히 승인 영역).
> 문서 숫자를 믿지 말고 `python audit_schedule_health.py` 로 직접 잴 것.

> ### ~~[2026-08-23 재실측] 크롤/마이그레이션 축은 지금 실제로 돈다~~ (위 2026-08-24 재실측으로 무효)
>
> 이 문서 자신의 "교훈"(바로 아래 문단, "정상 동작 중은 매번 다시 재는 대상이지 상수가
> 아니다")을 따라 다시 쟀다. `DOJOONPASS_DAILY`라는(이 문서/`register_scheduler_tasks.ps1`이
> 기대하는 이름과 다른) 작업이 매일 03:00에 등록되어 실제로 돌고 있다:
> ```
> Get-ScheduledTaskInfo DOJOONPASS_DAILY   LastRunTime 2026-08-23 03:00:01, 결과 0
> logs/daily_run.log   [SUCCESS] Finished 2026-08-23 04:35:15 — 수집 273건, 신규 16건
> auction_item 기일 남은 물건   275→291건(당시 9건과 다름)
> ```
> 이 세션이 등록한 것이 아니다 — 다른 세션/사람이 이미 등록해 둔 것을 재발견했을 뿐이다.
> **DocWorker(`DojoonPass-DocWorker`)/PriorityRefresh는 여전히 미등록**이라 사진/문서
> 파이프라인은 그대로 막혀 있다(`docs/BETA_RELEASE_CHECKLIST.md` "활성 물건의 89%가
> 상세 화면에서 문서/사진이 전부 비어 있다" 절 참고, 등록은 여전히 승인 영역).

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

**[회귀]** `test_worker_batching.py` 13 — **결정적**이다. 경쟁자가 한 번만 이기는
상황을 커넥션 래퍼로 만들어(`_QueueInterleavingConn`), 이 실행이 다른 행을 집어 오는지
본다. 상수를 읽지 않고 **행동**을 고정하므로 `CLAIM_RACE_MAX_ATTEMPTS` 를 어떤 값으로
바꾸든 1이면 잡힌다. 같은 파일 11·12 가 형제 행 제외 / 상한 소진 경고(레벨 포함)를 함께 본다.

보조로 `test_refresh_trigger.py` §15 — 스레드 12개로 중복 0 / 남은 행 전부 claim /
행보다 많은 스레드는 정직하게 빈손 / refresh 행도 정확히 한 번만 집힘 + overwrite=True.

★ 2026-08-24 정정 — 이 항목은 원래 "변이 확인: `CLAIM_RACE_MAX_ATTEMPTS = 1` 로
되돌리면 **즉시 3건 FAIL**" 이라고만 적혀 있었다. 실제로 되돌려 반복 실행해 보니
**15/17 (약 88%)** 이다 — 8번에 한 번꼴로 **결함이 있는 코드를 통과시킨다.** 스레드
12개가 매번 같은 순서로 얽히지 않기 때문이다. "즉시 FAIL" 은 그날 한 번 돌려 본
결과였고 상시 참인 문장이 아니었다. 그래서 방어선을 결정적 검사(위 13번)로 옮기고
스레드 검사는 실제 동시성(락 경합/busy_timeout)을 보는 보조로 남겼다.
자세한 실측은 `docs/SPRINT254_CLAIM_RACE_BRANCHES.md` §3.


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

--------

#155

**N+1 감시 가드가 데이터가 하루 낡자 눈을 감았다** — 진짜 성능 회귀를 통과시켰다

해결 (2026-08-20, Sprint 224)

**[경위]** `test_search.py` 의 SQL 횟수 가드(Sprint 223 신설)만 `include_closed` 를 붙이지
않았다. 이 파일의 **다른 모든 호출은 이미 붙이고 있었다** — 파일 상단에 "매각기일 필터는
이 파일의 관심사가 아니다"라고 적혀 있다.

기본 검색은 `auction_date >= 오늘` 이라, 크롤이 멈춘 채 날짜가 지나면 결과가 0건이 된다.

```
DB 총 1,876건 / 최신 매각기일 2026-08-19 / 마지막 크롤 2026-08-12
2026-08-20 기준 기본 검색  0건
계측 결과  {size1: (SQL 2회, 0건), size9: (SQL 2회, 0건)}
```

★ **FAIL 보다 그 아래 두 PASS 가 문제였다.** 별표 두 개(=이 검사의 본체)가
`2 == 2` 로 **공허하게 통과**하고 있었다.

**[증명]** 검색 API 에 진짜 N+1 을 주입하고 고치기 전 방식으로 재 봤다 —
`{1:(2,0), 9:(2,0)}`, 두 별표 모두 **통과**. 실제 성능 회귀가 조용히 초록불이 된다.
살아남은 것은 "검사가 공허하지 않다"는 하한선 하나뿐이었다.

**[해결]** 가드도 파일의 나머지와 같이 `include_closed=True` 로 잰다. 측정 대상은
"행 수에 따라 SQL 이 늘어나는가"이지 "오늘 이후 물건이 있는가"가 아니다
(후자는 `test_pipeline_integrity.py` 가 따로 본다).
실측 복구: `size=1 3회 / size=9 3회` (COUNT + 페이지 행 + 썸네일 배치).

**[변이]** 검색에 N+1 주입 -> 2/2 FAIL (`size1 3회 / size9 11회`).

**[교훈]** 데이터에 의존하는 검사는 **데이터가 없을 때 실패해야지 통과해서는 안 된다.**
같은 파일 안에서도 나중에 추가한 검사가 기존 규칙을 따르지 않으면 이런 구멍이 생긴다.

--------

#156

**관심물건·최근 본 물건에 사진이 없었다** — 검색목록에서 사진 보고 담았는데 사라진다

해결 (2026-08-20, Sprint 224)

**[경위]** `thumbnail_url` 을 주는 API 가 `api/v1/search.py` 하나뿐이었고, 두 화면에는
`<img>` 가 아예 없었다. `docs/CURRENT_STATE.md` 가 "미문서화 공백"으로만 적어 두고
제품 결정이라며 고치지 않은 상태였다.

**[해결]** 경로 규칙이 이미 두 곳에 흩어져 있어(`item.py:_image_url()`,
`search.py:row_to_item()` 안의 문자열) 두 화면을 더하면 넷이 된다. 갈라졌을 때의 증상은
**"목록에는 나오는데 열면 404"** — 화면은 정상으로 보이고 로그도 조용하다.
그래서 먼저 `api/v1/thumbnails.py` 하나로 모으고(`search.py`/`item.py` 도 이것을 쓰게
바꿔 **중복을 늘리지 않고 줄였다**), 두 API 에 배치 조회 1회를 더했다.
프런트는 `ResultThumbnail.tsx` 를 `src/components/` 로 옮겨 세 화면이 공유한다.
`thumbnail_url` 이 있을 때만 그린다 — 사진 없는 물건에 빈 회색 칸을 만들지 않는다.

**[실측]** 실브라우저(진짜 세션) 최근 본 물건: 카드 11개 중 사진 4개,
`<img>` 4개 전부 `naturalWidth > 0`(브라우저가 실제로 디코딩), 80x80 렌더,
카드 폭 사진 유무와 무관하게 411px, 가로 오버플로 0, 콘솔 오류 0.
관심물건은 이 계정에 0건이라 **운영 DB 사본**에 넣고 사본을 읽는 API 로 확인
(카드 6개 중 사진 4개, 전부 디코딩 성공). 운영 DB 는 건드리지 않았다.

**[회귀]** `test_asset_pipeline.py` 16-B2 신설 — 일부러 1번 순번을 비우고 2·3번만 넣어
대표가 `MIN(seq)` 인지 본다. 키 상시 존재 / null 구분 / **URL 이 실제로 200 으로 열리는가** /
네 화면 URL 일치 / 기존 키 15개 유지 / 건수가 늘어도 쿼리 수 불변(2건 2회, 10건 2회).

**[변이]** N+1 주입 / 키 제거 / 없는 URL / MIN->MAX / URL 규칙 어긋남 -> **5/5 FAIL**.

--------

#157

**검사 하나가 프런트 계약 전체를 가리고 있었다** — 접근성·라우팅이 통째로 관측 불능

해결 (2026-08-20, Sprint 224)

**[경위]** `tests/frontend-contract.test.mjs` 의 데이터 전제가 최상위 `before()` 안의
`assert` 였다. node:test 는 `before()` 가 실패하면 **그 아래 전부**를 실패시킨다.

```
수정 전   pass 21 / fail 93   — 93건 전부 "물건이 0건입니다" 한 가지 원인
```

그런데 50개 검사 중 **결과 데이터를 실제로 보는 것은 단 하나**였다. 나머지는
라우팅·리다이렉트 보존·랜드마크·h1·`aria-label`·레이아웃처럼 0건에서도 판정 가능하다.
즉 **크롤이 하루만 멈춰도 접근성/라우팅 계약이 통째로 어두워지고**, 화면에는 "93건 실패"로
보여 진짜 결함과 구별되지 않았다.

**[해결]** 연결 실패/비200 은 그대로 hard fail. 0건은 **전용 검사 하나**만 실패시키고,
데이터 없이 판정 가능한 검사는 전부 실행한다. 꼭 필요한 것만 skip(=통과 아님)이다.
원인도 뭉뚱그리지 않는다 — `include_closed=true` 로 한 번 더 물어
"DB 가 비었다"와 "매각기일이 전부 지났다"를 구분해 알린다.

**[곁다리 결함]** 두 검사가 `if (!homeHtml.includes('/properties/')) return` 으로
"결과 0건이면 건너뛴다"를 쓰고 있었는데, `/properties/` 는 **헤더 네비게이션의
`/properties/recent` 에도 들어 있다.** 그래서 이 분기는 **한 번도 동작한 적이 없다.**
결과 카드만 정확히 가리키는 `/\/properties\/\d+\?ids=/` 로 바꿨다.

```
수정 후   pass 110 / fail 1 / skip 3   (유일한 실패 = 데이터 전제를 알리는 그 검사)
```

**[검증]** 초록이 skip 덕분이 아님을 증명했다 — 운영 DB **사본**에 미래 매각기일 300건을
넣고 그 사본을 읽는 API(8001) + Next 로 같은 스위트를 돌려 **pass 114 / fail 0 / skip 0**.
데이터만 있으면 114개 전부가 실제로 판정된다 = 이번 구조 변경으로 잃은 검증력은 없다.

--------

#158

**"WCAG 2.5.8 위반"이라는 문서의 단정이 사실이 아니었다** — 개선 1순위가 잘못된 근거 위에 있었다

정정 (2026-08-20, Sprint 225)

**[경위]** `docs/SPRINT219_ACCESSIBILITY_AUDIT.md` 가 헤더 내비 5개(높이 16px)를
*"24px 미만이라 **규격 위반**"* 이라고 단정하고, 그것을 근거로 개선안 **1순위**에 올렸다
(*"WCAG 2.5.8 AA 위반이라 디자인 논쟁 여지가 가장 적다"*).

**[사실]** SC 2.5.8 에는 예외가 다섯 개 있고 그중 **간격(Spacing) 예외**가 그대로 적용된다 —
24px 지름의 원을 각 타깃 중심에 놓았을 때 원들이 겹치지 않으면 적합이다.
실브라우저에서 기하를 직접 계산했다.

```
화면              타깃수   24px 미만   원이 겹치는 쌍
/search             29        5개          0쌍
/properties/505     21        9개          0쌍
/mypage              8        5개          0쌍
가장 가까운 중심 간 거리   54px   (임계 24px 의 2.25배)
-> SC 2.5.8 위반 0건. **적합.**
```

**[영향]** 1순위의 근거가 사라진다. 헤더 내비 확대는 규격 준수가 아니라 **순수 디자인 판단**이고,
진짜 규격 위반은 **대비(SC 1.4.3)** 쪽에만 있다(거기엔 쓸 수 있는 예외가 없다).
크기가 작다는 사실 자체는 그대로다 — 다만 "규격 위반"이라 불러서는 안 된다.

**[전수 정정]** 같은 문장이 **6곳**에 퍼져 있었다(SPRINT219 / roadmap / frontend /
CHANGELOG 2곳 / CURRENT_STATE / 검사 파일 주석). 전부 고쳤다.

**[회귀]** 문서 근거 토큰에 `간격(Spacing) 예외` 를 추가해 **정정 자체를 잠갔다** —
지워지면 검사가 먼저 운다. **[변이]** 문서에서 그 서술을 전부 지우기 -> FAIL.

--------

#159

**접근성 ratchet 가드가 `src/components/` 를 아예 보지 않았다** — 공용 컴포넌트로 옮기면 검사에서 사라진다

해결 (2026-08-20, Sprint 225)

**[경위]** `test_frontend_accessibility.py` 의 `_tsx_files()` 가 `src/app/**` 만 훑었다.

```
src/app          text-xs 111 / text-gray-400 106   <- 예전 상한
src/components   text-xs   7 / text-gray-400   4   <- **한 번도 세지 않았다**
합계             text-xs 118 / text-gray-400 110
```

★ 하필 그 사각지대에 `SiteHeader.tsx` / `PrimaryNav.tsx` 가 있다 —
**Sprint 219 가 "가장 나쁘다"고 지목해 실측한 헤더 내비 바로 그것**이다.
문서의 "111회/106회"는 과소 집계였다.

더 나쁜 성질: 이 구조에서는 **공용 컴포넌트로 옮기는 순간 그 글자가 검사에서 사라진다** —
리팩터링이 곧 검사 회피가 된다.

**[함께 발견]** 상한만으로는 **추적 밖의 더 나쁜 색으로 갈아타는 것**을 막지 못한다.
`text-gray-400`(2.6:1) 을 `text-gray-200` 으로 바꾸면 개수가 줄어 오히려 초록불이다.
실제로 `text-red-400`(2.89:1, 오류 문구 2곳)이 표에 없었다.

**[해결]** 스캔 범위를 `src/app + src/components` 로 넓히고 상한을 재기준했다.
쓰이는 저대비 계열(`text-<색>-100~400`)을 전부 열거해 표에 없는 것이 나타나면 실패시킨다
(스캔이 죽어 공허하게 통과하지 않도록 하한도 함께).

**[변이]** 추적 밖 gray-200 으로 교체 / 공용 컴포넌트에 저대비 글자 추가 -> 2/2 FAIL.

--------

#160

**고정 폭 검출기가 `max-w-` 상한을 고정 폭으로 오인했다** — 범위가 좁아 그동안 숨어 있었다

해결 (2026-08-20, Sprint 225)

**[경위]** #159 로 스캔 범위를 넓힌 **첫 실행**에서 드러났다.

```
[FAIL] 가로 넘침 원인 - 고정 w-[NNNpx]: ['src/components/SiteHeader.tsx:72']
```

그 줄은 `max-w-[180px]`(이메일 말줄임 **상한**)이고 고정 폭이 아니다.
`\bw-\[\d{3,}px\]` 는 `-` 가 비단어 문자라 `max-w-` 의 `w` 앞에서도 `\b` 가 성립한다.
앞 판본이 `max-w-[1320px]` 로 한 번 당해 `\d{3,}` 을 붙였지만, 문제는 자릿수가 아니라
**접두사**라서 막히지 않았다.

**[왜 안 보였나]** `max-w-[...]` 를 쓰는 곳이 `src/components/SiteHeader.tsx`(스캔 밖)와
`src/lib/layout.ts`(`.ts` 라 스캔 밖) 둘뿐이었다.
**범위가 좁으면 검사기 자신의 버그도 함께 숨는다.**

**[해결]** `(?<!max-)(?<!min-)\bw-\[\d{3,}px\]`. `min-w-` 는 진짜 원인이지만 바로
아랫줄에서 따로 세므로 여기서는 뺀다(이중 계수 방지).
그리고 검출기를 **넣기 전에** known-good/known-bad 로 시험하게 했다
(잡아야: `w-[420px]`/`w-[1024px]` · 잡으면 안 됨: `max-w-[1320px]`/`max-w-[180px]`/`min-w-[360px]`/`w-[80px]`/`w-full`).

**[변이]** 공용 컴포넌트에 진짜 고정 폭 `w-[1400px]` 추가 -> FAIL.

--------

#161

**절대 실패할 수 없는 단언** — 정규식의 이스케이프가 제어문자로 굳어 있었다

해결 (2026-08-20, Sprint 226)

**[경위]** `tests/source-contract.test.mjs` 의 다음 단언이 **한 번도 동작한 적이 없다.**

```js
assert.ok(
  !/<0x08>formatPrice<0x08>/.test(src),
  '마이페이지가 축약 표기(formatPrice)를 씁니다 - 청구 금액이 실제와 어긋납니다'
)
```

`/\bformatPrice\b/`(단어 경계)로 쓰려던 것이 파일에는
**백스페이스 문자(0x08) 자체**로 들어가 있었다. 정규식이 "백스페이스 + formatPrice +
백스페이스"를 찾게 되니 **영원히 일치하지 않고**, `!` 가 붙어 있어 단언은 **항상 참**이다.
작업트리 변경이 없으므로 커밋된 상태 그대로다(마지막 수정 `21430db`).

**[무엇을 지키려던 가드였나]** `formatPrice` 는 12,900원을 "1만"으로 만든다(-22%).
구독 카드는 `toLocaleString() + '원'` 으로 정확히 쓰는데 내역만 축약하면
**같은 결제가 화면마다 다른 금액으로 보인다.**

**[왜 눈에 안 띄었나]** 에디터가 그 바이트를 거의 보여 주지 않고, 문법 오류도 아니며,
테스트는 **초록불**(23/23)이다. 지금 코드가 실제로 `formatWon` 을 써서 **결과까지 맞다** -
틀린 것은 "그것이 검증되고 있다"는 믿음뿐이었다.

**[변이]** `mypage/page.tsx` 의 `formatWon(` 을 `formatPrice(` 로 바꿔(결함 주입)
두 판본을 각각 돌렸다.

```
수정 후 가드        [검출]  테스트 실패
수정 전 가드(재현)   [놓침]  테스트 **통과**
```

**[해결]** 정규식 리터럴 대신 `String.raw` + `RegExp` 로 쓴다(같은 사고가 나면 이번에는
패턴이 눈에 보이게 깨진다). 그리고 같은 자리에서 합성 입력으로
**잡아야 할 것 / 잡으면 안 될 것**을 둘 다 시험해 공허하지 않음을 증명하게 했다.

--------

#162

**같은 사고를 상시로 잡는 검사가 없었다** — 제어문자로 굳은 이스케이프 전수 탐색

해결 (2026-08-20, Sprint 226)

**[경위]** #161 은 우연히 발견됐다. `\b` 만이 아니라
`\0`(0x00) `\a`(0x07) `\v`(0x0B)
`\f`(0x0C) `\e`(0x1B) 에서도 같은 사고가 난다.

**[전수 탐색]** 390개 파일(.py .mjs .js .ts .tsx .md .json .css) - **발견 1곳**(#161 그것뿐).

**[해결]** `test_console_encoding.py` 에 상시 검사 신설. 이 파일이 이미 소스를 바이트로
훑고 제외 규칙(`SKIP_DIRS`)을 공유하므로 형제 검사로 둔다.

```
훑는 대상   .py .mjs .js .ts .tsx (저장소 사본/의존성 제외)  실측 242개
고정        제어문자로 굳은 이스케이프 0개
하한        훑은 파일 >= 80  (0개를 훑고 조용히 통과하는 것 방지)
자체 검증   진짜 바이트는 잡고, 정상 두 글자 표기는 잡지 않는다
```

**[변이]** .mjs / .py / .tsx 각각에 제어문자 주입 -> **3/3 FAIL**.

**[원인과 대처]** 파일을 도구를 거쳐 쓸 때 역슬래시가 한 겹 사라지면
`"x"` 두 글자가 제어문자 한 글자로 굳는다. 실제로 Sprint 225 문서를 heredoc 으로
넘기다가 같은 일이 실시간으로 났고, 그것을 고치려던 스크립트마저 같은 경로에서 또 깨졌다.
**역슬래시가 들어가는 내용은 heredoc 으로 넘기지 말고 파일로 써서 실행한다.**

--------

#163

**상한 계수기가 주석을 코드로 세고 있었다** — 클래스를 설명만 해도 빨간불, 주석을 지우면 여유가 생긴다

해결 (2026-08-20, Sprint 227)

**[경위]** `test_frontend_accessibility.py` 의 저대비/작은 글자 상한 계수기가
원문을 그대로 셌다. 이 파일은 `_strip_comments()` 를 **이미 갖고 있고** 형제 검사들은
쓰는데 계수기만 쓰지 않아, 저장소 규칙 *"주석/문자열을 실제 코드로 세지 않는다"* 를
계수기만 어기고 있었다.

Sprint 227 에서 새 컴포넌트에 *"text-sm 을 쓴 이유"* 를 주석으로 적었더니
그 주석의 `text-xs` 가 사용 횟수로 잡혀 상한을 넘겼다.

```
클래스            주석포함   코드만
text-xs              119      117   <- 주석 2개를 코드로 세고 있었다
text-gray-400        111      110   <- 주석 1개
```

**[두 방향 모두 해롭다]**

```
클래스를 설명하면 사용으로 잡힌다   -> 멀쩡한 코드가 빨간불
주석을 지우면 상한에 여유가 생긴다   -> 진짜 사용이 늘어도 통과
```

**[해결]** 계수기가 `_strip_comments()` 를 쓰게 하고, 상한을 **코드 기준 실측값**으로
재기준했다(`text-xs` 118 -> 117). 래칫은 조일수록 낫다.

**[변이]** 주석에서 언급 -> 통과 / 진짜 코드로 사용 -> 실패. **2/2 기대대로.**

--------

#164

**내려받은 파일이 어느 사건의 것인지 아무도 확인하지 않았다** — 남의 매각물건명세서가 저장될 수 있다

해결 (2026-08-20, Sprint 228)

**[경위]** `audit_asset_integrity.py` [8] 이 보고하는 고아 다운로드 8개의 **이름**에서
출발했다. 같은 매각물건명세서가 Chrome 의 중복 접미사와 함께 **네 번** 쌓여 있었다.

```
2023타경118942_..._매각물건명세서(재작성,1)_참여_오해주.pdf
2023타경118942_..._매각물건명세서(재작성,1)_참여_오해주 (1).pdf
2023타경118942_..._매각물건명세서(재작성,1)_참여_오해주 (2).pdf
2023타경118942_..._매각물건명세서(재작성,1)_참여_오해주 (3).pdf
```

즉 **네 번 받고 네 번 다 못 옮겼다.** `docs/SPRINT199` 도 실행 중 spec 다운로드
타임아웃(30초)을 겪었다고 적고 있다.

**[결함]** `wait_for_download()` 는 `after_files - before_files` 로 **새로 생긴 PDF** 를
집는다. 어느 사건의 것인지는 보지 않는다. 받은 뒤 검증도 크기·매직 바이트뿐이다.

```
1. 사건 A 수집 -> 타임아웃으로 포기. **다운로드는 계속 진행 중**
2. 사건 B 수집 시작 -> before_files 스냅샷 (A 의 것은 아직 .crdownload)
3. A 완료 -> A.pdf 생성 = **새 파일**
4. wait_for_download() 가 그것을 집는다 -> **A 의 문서가 B 로 저장된다**
```

**[왜 결과 검사로 안 잡히나]** 저장된 것은 진짜 PDF 다. 크기 정상, 해시 계산됨,
`document_status` READY, 화면에서도 열린다. 무결성 감사 [1]~[9] 가 전부 통과한다.
**사용자는 다른 사건의 매각물건명세서를 보고 입찰을 판단하게 된다.**

**[해결]** 파일명에 박힌 사건번호로 대조한다. **확실할 때만 막는다.**

```
사건번호 있음 + 다름  -> 거부      사건번호 있음 + 같음 -> 통과
사건번호 없음         -> 통과 (감정평가서는 업체 코드라 없다 - 모르는 것은 막지 않는다)
```

병합 사건(실측 22.7%)은 `crawler/resume.py:case_no_matches_list_entry()` 를 **재사용**해
구성요소 각각과 정확히 비교한다(같은 판정을 두 벌 만들지 않는다).
거부해도 **파일을 지우지 않는다** - 원래 주인이 있고, 지우면 그 사건의 재수집도 잃는다.

**[회귀]** `test_asset_pipeline.py` 21번 신설 14검사. 실측 파일명을 표본으로 쓰고,
접두 부분 문자열 함정(2024타경1009 vs 2024타경100920)을 양방향으로 본다.
**두 다운로드 경로에 실제로 배선됐는지**도 센다 - 함수만 있고 안 부르면 아무 일도 없다.

**[변이]** 판정 무력화 / 부분 문자열 비교로 회귀 / 사건번호 없을 때 거부 /
배선 하나 제거 -> **4/4 FAIL**.

**[남은 위험]** 파일명에 사건번호가 없는 종류(감정평가서)는 여전히 판정할 수 없다.
더 확실한 방어(수집 전 downloads/ 비우기, 사건별 하위 폴더)는 각각 진행 중 다운로드
훼손·Chrome 프로필 변경이라 이번 범위 밖이다.

--------

#165

**또 하나의 절대 실패할 수 없는 단언** — `COUNT(*) >= 0` 으로 "측정 경로가 유효하다"를 주장했다

해결 (2026-08-20, Sprint 229)

**[경위]** `test_document_status_sync.py` §7 이 실제 DB 에서 "끝나지 않는 수집중"을 센 뒤
이렇게 단언하고 있었다.

```python
check_true("측정할 수 있다(조회 경로가 유효)", expired_collecting >= 0)
check_true("두 값을 구분해서 셀 수 있다", live_collecting >= 0)
```

`COUNT(*)` 는 **언제나 0 이상**이다. 조인이 깨져 0행을 세든, 컬럼 이름이 바뀌어 빈 결과가
나오든 똑같이 통과한다. *"측정 경로가 유효하다"* 를 검증한다고 적어 놓고
**아무것도 검증하지 않았다.** BUGS #161(Sprint 226)과 같은 계열이다.

**[해결]** 깨질 수 있는 불변식으로 바꿨다.

```
만료 + 진행중 + 고아  ==  COLLECTING 전체
```

어긋나면 그 차이는 곧 **대응 물건이 없는 `document_status` 행**이다 —
조인이 조용히 떨어뜨리는 행이고 지금까지 아무도 세지 않았다.
실측 결과 현재 고아는 **0개**(코드는 옳다). 없던 것은 **확인할 수단**이었다.

**[변이]** 운영 DB 는 건드리지 않고 **사본**에 고아 행 1개를 주입해 같은 질의로 재현했다.

```
정상          지금 판본 통과      / 옛 판본 통과
고아 1행 주입   지금 판본 **FAIL** / 옛 판본 **통과**
```

--------

#166

**다른 물건의 사진이 저장될 수 있었다** — 물건번호를 못 찾으면 경고만 남기고 첫 행으로 진행했다

해결 (2026-08-20, Sprint 230)

**[경위]** `crawler/base_crawler.py:go_to_case_detail()` 의 docstring 이 위험을 이미 적고
있었다 — *"물건 사진에는 버튼이 없다. 잘못된 물건의 페이지에 있으면 그대로 잘못된 사진을
저장한다."* 그런데 **실제 동작은 `logger.warning` 만 남기고 첫 일치 항목으로 진행**이었다.
`wait_for_detail()` 은 사건번호만 대조하고 물건번호는 아무도 확인하지 않는다.

**[왜 조용한가]** 저장된 사진은 **진짜 사진**이다. 크기·해시 정상, `auction_image` 기록,
`document_status` READY, 브라우저에서 잘 열린다. `audit_asset_integrity.py` [1]~[9] 가
**전부 통과한다.** 사용자는 다른 물건의 사진을 보고 입찰을 판단하게 된다.

문서는 이 위험이 없다 — 버튼 id 에 물건번호가 붙어 있다(실측: 다중물건 22건에서 서로 다른
물건이 같은 바이트인 경우 0건). **사진만 다르다.**
(같은 docstring 실측: 2025타경311 은 물건 1과 2의 사진이 실제로 같았다 = 그 표본에서는
**우연히** 결과가 같았을 뿐이다.)

**[해결]** `require_exact_item` 을 추가하고 `doc_worker` 가 사진일 때만 True 로 넘긴다.
**모호할 때만** 거부한다 - 항상 거부하면 목록 표기가 조금만 달라져도 사진 수집이 멈춘다.

```
후보 1개 -> 진행 / 후보 여러 개 + 정확 일치 -> 그 행 / 후보 여러 개 + 불일치 -> **거부**
목록이 물건번호를 안 준다 -> 판단 근거 없음. 막지 않는다 (Sprint 228 과 같은 규칙)
```

**[회귀]** `test_asset_pipeline.py` 22번 9검사. 가짜 드라이버로 **실제 함수**를 돌리고,
정확 일치 시 첫 행이 아니라 그 행으로 가는지(`moveDtlPage(11)` vs `(10)`)까지 본다.
`doc_worker` 배선 여부도 센다.

**[변이]** 거부 분기 끄기 / 모호 판정 끄기 / 배선 제거 / 언제나 첫 행 -> **4/4 FAIL**.

--------

#167

**스케줄 산술에 사건 크롤 다리가 빠져 있었다** — 창이 겹치면 Chrome 두 개가 같은 법원을 두드린다

해결 (2026-08-20, Sprint 230)

**[경위]** `test_schema_hygiene.py` 14-B 는 우선순위/문서수집 시각과 실행 순서,
`ExecutionTimeLimit` 까지 촘촘히 잠그고 있었다. 그런데 **`DojoonPass-DailyCrawl`(06:00)은
config 상수 자체가 없고 어떤 검사도 참조하지 않았다.**

세 작업 중 **둘이 Chrome 을 띄운다**(doc_worker / mvp_scraper). 그리고 **서로를 막지
못한다** - 각자 자기 락만 갖는다(`doc_worker.lock` / `mvp_scraper.lock`).
`DOC_WORKER_END_TIME` 을 07:00 으로 늘리는 것은 자연스러운 변경인데, 그 순간 겹친다.

**[해결]** `DOC_WORKER_END_TIME <= DailyCrawl 시작` 을 잠갔다. 함께:
`test_crawl_exit_code.py` 가 **하드코딩한 배치 목록**이 PS1 의 작업 목록과 같은지 대조하고
(네 번째 진입점이 생기면 실패 은폐 검사가 그것만 비껴간다), PS1 -> `.bat` -> `.py` 존재도 확인한다.

**[변이]** END_TIME 07:00 / DailyCrawl 03:00 / 미검사 진입점 추가 / 없는 배치 -> **4/4 FAIL**.

--------

#168

**'사건을 못 찾았다'로 드라이버를 통째로 재시작했다** — 무해한 사실이 하루치 수집을 죽일 수 있다

해결 (2026-08-20, Sprint 232)

**[경위]** `go_to_case_detail()` 이 False 를 돌려주면 코드는 그것을 일반 `Exception` 으로
올렸고, `except` 절이 **드라이버를 통째로 재시작**했다.

그런데 False 의 이유는 둘 다 **정상적인 판단 결과**다.

```
1. 그 사건이 법원 목록에 없다 (기일 경과 / 취하 / 변경)
2. 물건번호가 모호해 **일부러 진입하지 않았다**  <- Sprint 230 의 사진 오염 방어
```

브라우저는 멀쩡하다. 2번은 특히 나쁘다 — **옳은 판단이 재시작을 부른다.**

**[실측]** `logs/doc_run.log` 11일치.

```
"사건 매칭 실패" 255회, 전부 뒤에 재시작이 따라붙었다
재시작 -> 재개까지 평균 5.9초 (중앙값 5.9 / 최대 11.4)
합계 1,506초 = 25.1분  ->  하루 평균 2.3분 (실행 창 120분의 약 2%)
```

**[진짜 문제는 시간이 아니다]** `restart_download_driver()` 가 실패하면 Sprint 137 의
방어가 **그 날 실행 전체를 중단**한다. "사건 하나를 못 찾았다"가 하루치 수집을
통째로 죽일 이유가 없다.

**[해결]** 전용 예외 `CaseNotReachable` 로 그 경우만 잡아 **재시작 없이** 다음 항목으로
넘어간다. 재시도 예산은 종전대로 소모한다(큐 의미론 불변).

**[회귀]** 2종 신설 — 미발견 시 재시작 0회 + 다음 항목 정상 처리 /
**대조군: 진짜 예외는 여전히 재시작한다**(과잉 수정 방지).
**[변이]** 수정 전 복원 / 전용 except 무력화 / 실패 기록 누락 -> **3/3 FAIL**.

**[함께 조사했으나 원인이 아니었던 것]** `MAX_ITEMS=10` 을 의심했으나
매칭 실패 사건 62개 중 10건 초과 조합은 **2개뿐**(나머지 60개는 10건 이하)이라
주원인이 아니다. 가설을 폐기했다. (다만 (법원,기일) 조합 316개 중 14개가 10건을 넘고
앞 10건 밖 물건이 31건(1.7%)인 것은 사실이므로 별도 기록한다.)

--------

#169

**Admin API 키가 다시 사라졌다** — 문서는 "정상 403/200"이라 적고 있었다 (문서 정정)

정정 (2026-08-20, Sprint 233)

**[경위]** `docs/BETA_RELEASE_CHECKLIST.md` 가
*"2026-08-16 재실측(Sprint 134): 두 키 모두 설정 확인, 이제 정상 403/200 응답 — UI 없음만 남음 (P1)"*
이라고 적고 있었다. **오늘 재니 사실이 아니다.**

비밀값을 열람하지 않고 두 가지 독립된 방법으로 확인했다.

```
(1) .env 변수명    ADMIN_API_KEY / SUPER_ADMIN_API_KEY / PAYMENT_WEBHOOK_SECRET  이름 **없음**
                   SUPABASE_JWT_SECRET 만 있음(값 88자)
(2) 실제 서버 응답  OpenAPI 전 라우트 38개를 토큰 없이 호출
                   /api/v1/admin/* 13개 전부 -> 500 "관리자 키 미설정"
```

두 방법이 일치하므로 측정 오류가 아니다. `.env` 변동은 이번이 **세 번째**다
(08-08 있음 -> 08-13 없음 -> 08-16 있음 -> 08-20 없음).

**[영향]** 등기부 신청 상태 변경 / 결제 환불 / 웹훅 재처리 / 구독·사용자·감사 로그 조회
— **운영자가 할 수 있는 일이 하나도 없다.**

**[조치]** 준비도 표를 `P1` -> **`P0`** 로 되돌리고 근거를 남겼다.
`.env` 수정은 승인 영역이라 하지 않았다.

**[함께 확인]** 토큰 없는 요청이 13개 라우트에서 500 을 만든다. Sprint 146 이
*"인증 없이 500"* 을 고친 전례가 있으나, 여기는 코드에 의도가 명시돼 있고
(*"두 키 모두 없으면 Admin API 자체를 쓸 수 없다(기존 동작 유지: 500)"*)
**키가 채워지면 자연히 403 이 된다.** 근본 원인이 `.env` 라 코드는 바꾸지 않았다.

--------

#170

**Admin Secret 계약의 중간 상태들이 검증되지 않았다** — 틀린 키 / 등급 분리 / 사용자 API 영향

해결 (2026-08-20, Sprint 234)

**[경위]** `test_api_regression.py` 31-B 가 *"두 키 모두 없으면 500"* 과 *"되돌리면 200"* 은
잠그고 있었으나 그 **사이의 상태들**이 비어 있었다.

```
키는 있는데 **틀린 키**를 줬을 때        -> 403 이어야 한다(500 도 200 도 아니다)
ADMIN 만 있고 SUPER 가 없을 때           -> 등급 분리가 실제로 되는가
Secret 부재가 **일반 사용자 API** 에      -> 영향을 주면 안 된다
```

마지막이 가장 중요하다. Admin 키는 운영자용인데 그것이 없다고 로그인 사용자의
관심물건/검색까지 죽으면 **운영 불편이 서비스 장애로 바뀐다.**

**[실측]** 이 환경이 정확히 그 상태(ADMIN/SUPER 둘 다 없음)라 가정이 아니라
현재 상태를 그대로 확인했다.

```
공개 API  /search /stats /plans                                   200
인증 API  /favorites /recent-items /search-presets /subscriptions  200 (토큰 있음)
          토큰 없음 -> 401 (500 으로 바뀌지 않는다)
Admin     같은 조건에서 **Admin 만** 500   <- 대조군
```

**[회귀]** `test_admin_secret_contract.py` 신설 30검사. 키는 **프로세스 환경에만** 주입하고
되돌린다(`.env` 는 읽지도 쓰지도 않는다. 운영 Secret 을 만들지 않는다).
Admin 라우트는 **OpenAPI 에서 16개 전수 추출**해 하드코딩 목록을 쓰지 않는다.

**[변이]** 등급 검사 끄기 / 키 미설정 가드 끄기 / 틀린 키 허용 /
**헤더 없으면 최고 등급 부여** -> **4/4 FAIL**. 마지막은 인증 없이 관리자 권한이 되는
최악의 경우인데 잡힌다.

--------

#171

**`DOC_WORKER_TEST_MODE` 가 문서 어디에도 없었다** — 실행 창 검사를 무력화하는 플래그

해결 (2026-08-20, Sprint 234, 문서 보강)

**[경위]** 코드가 읽는 환경변수를 AST 로 전수 추출해 문서와 대조하다 발견했다.
**코드는 읽는데 문서에는 한 줄도 없었다.**

```python
if os.environ.get("DOC_WORKER_TEST_MODE") == "1":
    return False        # doc_worker 의 실행 창(02:00~04:00) 검사를 통째로 끈다
```

운영 환경에 실수로 들어가면 **워커가 종료 시각을 무시하고 계속 돈다** —
06:00 일일 크롤과 겹칠 수 있고, 둘 다 Chrome 을 띄우면서 서로의 락을 보지 않는다
(BUGS #167 이 잠근 바로 그 위험).

**[해결]** `docs/ENVIRONMENT_VARIABLES.md` 에 용도/위험/운영값(**설정하지 않는다**)을 기록.

**[함께 발견]** `SUPABASE_ANON_KEY` 가 `.env` 에 있는데 **읽는 코드가 0곳**이다
(실제로 쓰이는 것은 `.env.local` 의 `NEXT_PUBLIC_SUPABASE_ANON_KEY`).
기능 영향은 없지만 "설정했는데 왜 안 되지"의 원인이 되기 쉬워 함께 기록했다.
`.env` 정리는 승인 영역이라 건드리지 않았다.

--------

#172

**처리 능력을 보는 검사가 하나도 없었다** — 출시 후 조용히 무너지는 쪽은 정확성이 아니라 능력이다

해결 (2026-08-20, Sprint 235)

**[경위]** 큐의 **정확성** 검사는 촘촘했다(claim 원자성 / 재시도 / 회수 / 멱등 / 7일 누적).
그런데 **처리 능력**을 보는 검사가 없었다. 능력 부족은 오류를 남기지 않는다 —
큐는 정상적으로 쌓이고 워커도 정상적으로 돌지만 따라잡지 못하고, **큐 길이만 매일 늘어난다.**

**[실측]** `logs/doc_run.log` 5,424줄.

```
navigate 908회 / 처리 901건       -> 처리 1건당 이동 1.01회
(사건,물건) 287개                 -> 물건 1건당 이동 3.16회 (그 시절 doc_type 3종)
navigate 1회  중앙값 10.9초 (p90 16.0 / 최대 42.2)
```

`doc_worker` 는 큐 행을 하나씩 claim 하고 행마다 `go_to_case_detail()` 을 부른다.
즉 **doc_type 수 = 물건당 이동 횟수**다.

**[능력 vs 공급]** 공급은 추정이 아니라 `auction_item.crawl_date` 실측(크롤이 돈 20일).

```
창 7,200초 / doc_type 4종 x 10.9초 = 물건당 43.6초  ->  하루 **165건**
공급 중앙값 106건  -> 감당 (여유 36%)
공급 최대   278건  -> **밀린다** (부족 113건)
이론 최대   600건  -> **크게 초과** (MAX_ITEMS 10 x 법원 60, 부족 434건)
```

★ 큐에 `image` 행이 **0개**다 — 지금 행들은 Sprint 144 이전 적재분이다.
새로 적재되는 물건부터 4종이 되어 이동이 3회 -> 4회로 는다. 사진 수집 자체는
**0.0초**(DOM 에서 바로 읽는다)인데 그것을 위해 10.9초짜리 이동을 한 번 더 한다.

**[해결]** `test_worker_capacity.py` 신설(15단언). 세 값의 **산술 관계**를 잠근다 —
doc_type 수 x navigate 비용 vs 실행 창 vs 실제 공급. 모델 근거(워커가 행마다 이동하는가,
한 번에 한 행만 claim 하는가)도 코드에서 확인한다.

★ **래칫**을 함께 걸었다 — 중앙값(106)만 보면 doc_type 을 6종까지 늘려도 통과한다(132 > 106).
"기준선(165건) 아래로 떨어지지 않았는가"를 따로 본다.

**[변이]** 창 절반으로(중앙값+래칫 둘 다 FAIL) / doc_type 추가(**래칫만** FAIL — 래칫이
없었으면 놓쳤다) / 워커 호출 형태 변경(모델 근거 FAIL) -> **3/3 검출**.

**[정책은 바꾸지 않았다]** batching 이득이 **4.0배**(165 -> 661건/일)로 이론 최대까지 덮지만,
claim 단위가 행 -> 물건으로 바뀌는 구조 변경이라 운영 판단이 필요하다.
`MAX_ITEMS` 상향은 **batching 다음**이다 — 지금 올리면 큐만 밀린다.

--------

#173

**물건 하나를 받으려고 같은 상세페이지에 네 번 들어갔다** — 그리고 그것을 잡으라던 가드가 놓쳤다

해결 (2026-08-20, Sprint 236)

**[경위]** `doc_worker` 는 큐 행을 하나씩 claim 하고 **행마다** `go_to_case_detail()` 을
불렀다. 같은 물건의 4종(spec/status/appraisal/image)을 받으려고 같은 페이지에 네 번
들어간 것이다. 사진 수집 자체는 DOM 을 읽기만 해 0.0초인데, 그것을 위해 이동을 한 번 더 했다.

**[먼저 발견한 것 - Sprint 235 의 측정이 틀렸다]** 구현 전에 다시 쟀다.
Sprint 235 는 `법원 선택` 줄 사이 간격을 'navigate 비용(10.9초)'이라 적었지만,
그 간격에는 **수집과 sleep 이 들어 있다** - 이동 비용이 아니라 **한 행의 전체 주기**였다.

```
모델 없이 잰 값   실행 7회 합계 897행 / 5.8시간 -> 행 1개당 **23.2초**
                 행/이동 = **1.00** (7회 전부)
구간 분해         법원선택->결과 14.1초 / 결과->법원선택 9.2초 / 합 23.9초
이동 1회          **15.2초** (Sprint 147 독립 측정과 이번 분해 16.4초가 일치.
                 작은 쪽 채택 - 이득을 부풀리지 않는다)
```

-> 능력은 165건/일이 아니라 **78건/일**이었다. **실측 공급 중앙값(106건)조차 감당하지 못했다.**

**[더 나쁜 것]** Sprint 235 가 넣은 '모델 근거' 검사는 *"batching 이 들어오면 여기서
먼저 운다"* 고 적혀 있었는데 **초록불을 유지했다.**
`"claim_next_queue_item()" in src` 가 `doc_worker.py:266` 의 **주석 한 줄**에 걸린 것이다.
다른 검사도 새로 만든 헬퍼 **안쪽의 호출**에 걸려 통과했다.
이 저장소 함정 목록의 "주석/문자열을 코드로 오인" + "grep 만으로 실행 경로 판정"을
그 목록을 아는 상태로 밟았다.

**[해결]** `claim_next_item_rows()` / `release_queue_rows()` 신설.
**claim 단위만** 행 -> 물건으로 바꾸고 나머지 의미는 전부 행 단위로 유지했다
(재시도 예산 / 성공·실패 기록 / refresh 의도 / 부분 실패). 첫 행은 기존
`claim_next_queue_item()` 을 그대로 불러 **판단을 복제하지 않는다.**
형제 행에도 재시도 간격을 똑같이 건다.

★ 재사용 전에 `wait_for_detail()` 로 **화면을 확인한다.** 수집기의 창 복구가 전부
`try/except: pass` 라, 돌아오지 못한 채로 다음 종류를 처리하면 **남의 문서를 긁는다.**

★ **사진을 먼저** 처리한다. 사진만 정확일치가 필요하므로(Sprint 230), 그 엄격한 이동
한 번을 나머지가 재사용한다. 반대 순서면 이동이 2회가 된다.

**[결과]** 이동 **48회 -> 12회**(물건 12개 x 4종, 진짜 `main()` 실측).
처리량 **78 -> 153건/일 (1.97배)**. ★ 이동은 4배 주는데 처리량은 2배다 -
수집과 sleep 은 종류마다 그대로 든다. Sprint 235 의 '4.0배'는 처리량이 아니라
**이동 감소 배수**였고, 이제 검사가 그 혼동을 막는다.

**[변이]** batching 가드 **7/7**, 처리 능력 가드 **5/5**(그중 C5 는 옛 이름을
*주석*에 넣었을 때 **통과**해야 정상 - 주석을 코드로 읽지 않음의 증명).

**[곁다리]** 저장소 가드가 내 코드를 두 번 잡았다 - `IN (%s)` 동적 SQL(예외 목록에
넣지 않고 **동적 SQL 자체를 제거**), 그리고 반쪽 fixture 스키마.

--------

#174

**하나의 상수(`MAX_ITEMS`)가 서로 다른 두 가지를 제한한다** — 공급 상한이면서 조회 반경이다

기록 (2026-08-20, Sprint 237). 값은 **바꾸지 않았다**(정책 = 승인 영역).

**[정적 사실]**

```
crawler/court_crawler.py  crawl_court()        -> 그날 이 법원에서 몇 건 가져올까 = **공급 상한**
crawler/base_crawler.py   go_to_case_detail()  -> 아는 사건을 찾으려고 몇 행 훑을까 = **조회 창**
```

두 번째는 정책이 아니다. 그런데 같은 손잡이를 돌린다. 공급을 줄이려고 값을 내리면
**이미 큐에 있는 사건을 찾지 못하게 된다** - 조용히, "사건 매칭 실패" 로그만 남기고.
진입점도 import 그래프로 확인했다(doc_worker -> 조회 / mvp_scraper -> 공급).

**[절단이 진짜인가 - 진짜 함수로 확인]** 가짜 DOM 19건(DB 실측 최대치)으로
실제 `collect_list_items` 를 태웠다. 상한 10 -> 10건만 반환, 19번째 사건은 **찾을 수 없다**.
상한 없이는 19건 전부 반환하고 찾는다(대조군).

**[실제로 걸리고 있다]** 크롤 로그 1,698회의 수집 건수 분포가 1~10 에 걸쳐 있고
**10에서 205회(12.1%) 몰린다.** 분포가 완만한데 상한값만 튀는 것은 상한이 실제로
걸린다는 뜻이다 -> 실행의 12.1% 에서 그 법원의 물건 일부가 아예 수집되지 않았다.

**[★ 말할 수 없는 것]** "상한을 N 으로 올리면 공급이 얼마가 된다"는 로그로 알 수 없다 -
자료가 10에서 오른쪽으로 잘려 있다(right-censored). 그래서 **역산**했다:
물건 1건 47.2초 기준 능력 153건/일 vs 공급 중앙값 106건 -> 여유 **1.44배**.
창을 05:38 로 넓히면 277건/일 -> 여유 **2.61배**.
**순서가 계산으로 확정된다 - 창을 먼저, MAX_ITEMS 는 그 다음.**

**[해결]** `test_max_items_contract.py` 신설(18검사). 두 의미 / 조회 창 >= 공급 상한 /
절단의 실재 / 상한이 걸리는 비율 / 능력 역산을 잠근다. 변이 **5/5**.

--------

#175

**실행 창 가드가 "종료 == 크롤 시작"을 통과시켰다** — 워커는 종료 시각에 딱 멈추지 않는다

해결 (2026-08-20, Sprint 237)

**[경위]** Sprint 230 이 "문서 수집 창이 사건 크롤 시작 전에 닫힌다"를 잠갔는데
조건이 `종료 <= 크롤시작` 이었다. 그런데 `is_time_up()` 은 루프 **맨 위**에서만
검사되므로, 이미 처리 중이던 행 하나는 **종료 시각을 지나서도** 끝까지 처리된다.

```
실측(logs/doc_run.log 907구간)  행 1개 처리 최대 **42.2초**
이론 최대                        wait_for_detail 20초 + 오버레이 15 + 새창 15 = 약 50초
```

END=06:00 이면 06:00 크롤과 **실제로 겹친다.** 둘은 서로의 락을 보지 않아
(각자 자기 중복만 막는다) 아무도 말리지 않고, 증상은 "가끔 실패"로만 나타난다.

**[해결]** 여유 **5분**을 요구한다(이론 최대의 6배).
또 하나 - `limit >= window` 검사가 **창이 음수일 때 공허하게 통과**했다(음수는 언제나
한계 이하다). 창이 양수인지 먼저 본다.

**[증명]** config 를 잠깐 바꿔 실제 가드에 태우고 되돌렸다(바이트 동일 확인).
05:38 통과 / 05:55 안전 상한 / **05:56·06:00 막힘** / 01:00(음수) 막힘.

**[전제도 잠갔다]** 여유 계산은 "초과분 = 행 하나"에 기대는데, batching 이 그것을
물건 하나(최대 4행)로 키웠다면 무너진다. `is_time_up()` 호출 횟수로 확인한다 -
행 12개 처리에 **14회**(기동 전 1 + 행마다 12 + 종료 1). 변이(묶음 단위 검사) -> 5회, 잡힌다.

--------

#176

**사용자별 JSON 응답에 캐시 정책이 없었다** — 공용 PC 에 남을 수 있다

해결 (2026-08-20, Sprint 237)

**[실측]** JSON 응답 9종 전부 `Cache-Control` 이 **없었다**(검색/상세/통계/문서통계/
관심물건/최근본/프리셋). 헤더가 없으면 브라우저는 휴리스틱 캐싱에 맡겨진다.

**[해결]** `api_server.py` 의 기존 보안 헤더 미들웨어 한 곳에서, **인증 헤더가 있고
검증자(ETag/Last-Modified)가 없는** 응답에만 `Cache-Control: no-store` 를 붙인다.

★ 검증자가 붙은 응답은 **건드리지 않는다.** 그쪽은 문서/사진 파일이고 전부 no-store 로
덮으면 실측 **630KB**(문서 395,675 + 사진 235,194)의 304 절약이 사라진다. 그 경계가 핵심이다.

신선도 계약은 깨지지 않는다 - `no-store` 는 "헤더 없음"보다 엄격하기만 하다.
`max-age` 는 정하지 않았다(`api/http_cache.py` 가 적어 둔 "운영 근거 없음"이 지금도 유효).

**[해결 검증]** 별도 인스턴스(8010)에서 확인 후 종료 - 사용자 서버는 건드리지 않았다.
`test_api_cache_headers.py` 신설(12검사). 변이 **3/3**.

--------

#177

**`auction_image` 테이블이 없는 환경에서 검색·상세·사진 API 전체가 500** — migration 020
미적용이 단일 테이블 부재를 API 전면 장애로 증폭시키고 있었다

해결 (2026-08-21, Sprint 239)

**[실측]** 이 로컬 `auction.db`에 `020_create_auction_image.sql`이 미적용인 상태에서
진짜 `api_server.py` 프로세스를 띄우고 curl로 재현:

```
GET /api/v1/search?limit=3   -> 500  {"detail":"검색 처리 중 오류가 발생했습니다"}
GET /api/v1/item/1           -> 500  Internal Server Error
   traceback: api/v1/item.py:56  sqlite3.OperationalError: no such table: auction_image
```

원인 경로 3곳: `api/v1/thumbnails.py:fetch_thumbnail_seqs()`(검색 목록 썸네일,
`search.py`가 결과 페이지 전체를 감싸는 호출), `api/v1/item.py:get_item()`의 사진 목록
쿼리, `api/v1/images.py:get_item_image()`의 파일 서빙 쿼리. 셋 다 `auction_image`가
없으면 예외가 그대로 위로 새어 나가 **호출부 전체를 죽였다** — 사진은 이미
`thumbnail_url: null`/빈 `images[]`로 "없음"을 표현할 수 있는 nullable 필드인데,
테이블 부재가 그 nullable 경로를 타지 못하고 하드 크래시로 이어진 것이 문제였다.

**[해결]** 세 곳 모두 `sqlite3.OperationalError`를 **narrow하게**(정확히
`"no such table: auction_image"` 메시지만) 잡아 사진 없음과 같은 모양으로 되돌린다 —
`fetch_thumbnail_seqs()`는 `{}`, `item.py`의 `images`는 `[]`, `images.py`는 404.
그 외의 `OperationalError`(예: 문법 오류, 잠금)는 그대로 재던진다 — 이 결손 하나만
narrow하게 흡수하고 다른 결함을 가리지 않기 위해서다.

★ 근본 원인(migration 미적용)은 이 방어로 숨지 않는다 — `test_bootstrap.py`(fresh DB와의
컬럼/인덱스 드리프트 감지)와 `test_schema_hygiene.py` §3(migration_history 완전성)이
독립적으로 계속 이 결손을 잡는다. 여기서 고친 것은 "결손이 있어도 서비스는 죽지 않는다"
뿐이다.

**[증명]** 실제 프로세스로 재확인:

```
GET /api/v1/search?limit=3   -> 200  total 124  (thumbnail_url 전부 null, 검색 자체는 산다)
GET /api/v1/item/1           -> 200  images: []
GET /api/v1/item/53          -> 200  documents[].available: true (READY 문서는 계속 열람 가능)
```

`python run_python_tests.py`: 통과 37 -> **45**(같은 결손이 원인이던 9개 파일 회복,
2개는 여전히 의도대로 FAIL — 아래 참고). `node --test tests/*.test.mjs`: **137/137 PASS**
(이전 96개 실패 전부 이 결손의 파급이었다).

**[의도적으로 안 고친 것]** `test_bootstrap.py`/`test_schema_hygiene.py`는 이 결손을
정확히 잡아야 하는 가드라 **그대로 FAIL로 남겨 둔다.** 이걸 통과시키면 드리프트 감지
자체가 무뎌진다.

**[별도 발견, 미해결]** 같은 조사 중 `doc_raw`가 0행인데 `document_status`는
READY 555행인 것을 확인했다 — 이미 Sprint 144가 같은 상태를 발견하고
`backfill_doc_raw.py`(dry-run 기본, 안전: 파일 존재 확인 후에만 기록/기존 행 불변/삭제 없음)를
만들어 둔 바로 그 상황이 이 로컬 DB에서 재발한 것이다. 2026-08-21 dry-run 재확인:
`기록 예정 555 / READY인데 파일 없음(문제) 0`. **DB 쓰기(`--apply`)는 승인 영역이라
실행하지 않았다.** 영향은 제한적이다 — `available`/`viewer_url`/`download_url`은
`document_status`에서 오므로 문서 열람 자체는 정상 동작하고(item 53 SPEC 다운로드 200,
402,328B 실파일 확인), `page_count`/`file_size`/`doc_version`만 계속 null이라
문서 뷰어의 페이지 이동 UI가 그려지지 않는다.

--------

#178

**법원이 나중에 정정한 사건은 옛 `court_code` 밑에 큐 행이 영구 고아로 남는다** —
"병합 사건 중복"과는 다른, 새로운 원인의 같은 계열 결함

미해결 (2026-08-22 Sprint 257 발견)

**[경위]** `test_pipeline_integrity.py`의 "파이프라인 테이블의 고아 행" 검사는
`document_status`/`tenant_rights`/`rights_summary`/`document_collect_failures`가
전부 `auction_item.id` **FK**로 연결되는 것만 검사하고 있었다 - 그런데 `document_queue`는
`auction_item`을 PK로 참조하지 않고 `(court_code, case_no, item_no, doc_type)` **문자열
조합**으로만 연결된다(`enqueue_documents()`의 `INSERT OR IGNORE`). 이 연결을 실제로
검사하는 곳이 하나도 없었다.

**[실측, 2026-08-22 운영 `auction.db` 읽기 전용]**
```
document_queue 전체                                     5,619행
(court_code, case_no, item_no)가 auction_item에 없는 행    21행 (=7사건 x 3종: spec/status/appraisal)

2024타경2803  고양지원(옛, 2026-07-10 적재) vs 춘천지방법원(현재)
2024타경8092  고양지원(옛)                 vs 창원지방법원(현재)
2025타경712   대구지방법원(옛)              vs 고양지원(현재)
(외 4건 - cleanup_orphans_dryrun.py 실행 결과 참고)
```
7사건 전부 **완전히 다른 지역의 두 법원**이 짝지어져 있다(예: 고양지원↔춘천지방법원,
대구지방법원↔고양지원) - 인접 관할 정정이 아니라, **같은 사건번호를 우연히 공유하는
서로 다른 법원의 별개 사건**을 이 저장소가 한 시점엔 A 법원으로, 다른 시점엔 B 법원으로
크롤한 것으로 보인다(사건번호는 법원별 독립 채번이라 이런 우연한 중복 자체는 정상이다 -
문제는 큐가 옛 법원 밑의 행을 청소하지 않는 것이다).

**[왜 영구인가]** `enqueue_documents()`는 기존 행을 지우지 않고 새 court_code로 새 행만
추가한다. 옛 court_code 밑의 행은 그 뒤 어떤 크롤에서도 다시 일치할 수 없다. 대상 사건은
이미 다른 court_code 밑에 정상적으로 존재하므로 실사용자 피해(잘못된 물건 노출)는 없다.

**[병합 사건 중복과의 차이]** `detect_merged_case_duplicates_dryrun.py`(Sprint249)는
**case_no 문자열 자체가 바뀌는** 경우다(법원의 사건 병합 공고). 이번 건은 case_no/item_no는
그대로고 **court_code만** 바뀐다 - 식별키의 다른 절반이 흔들리는, 원인이 다른 결함이다.

**[정정 - 2026-08-22 Sprint 260, 같은 세션 안에서 스스로 바로잡음]** 위 "발견"은 사실
**재발견이었다.** `cleanup_orphans_dryrun.py`가 **2026-08-14**(Sprint257보다 8일 앞서)에
이미 이 정확히 같은 21행(고양지원/2024타경2803 포함 동일 7사건)을 찾아 훨씬 더 깊이
분석해 두고 있었다 - 처음에 새 탐지 스크립트(`detect_orphaned_queue_court_dryrun.py`)를
만들기 전에 기존 `*_dryrun.py` 전체를 먼저 찾아 읽었어야 했는데 그러지 않았다. 그 스크립트를
찾은 뒤 **중복 도구를 지웠다**(추적된 적 없는 파일이라 삭제가 아니라 미작성 취소에 가깝다).

기존 도구가 이번 조사보다 실제로 더 정확했던 두 지점:

1. **실제 낭비 비용이 0이다.** 21행을 상태별로 나누면 done 3 / pending 15 /
   SKIPPED_EXPIRED 3인데, pending 15행 전부 **기일이 이미 지나** 2차 방어선(`is_time_up`
   이전에 `auction_date < today` 검사)에 막혀 **브라우저를 열지 않는다.** "매일 사건
   매칭 실패로 드라이버 재시작 비용을 쓴다"는 처음 서술은 **과장이었다** - 지금은 비용
   0이고, 크롤이 재개돼 이 사건들과 우연히 같은 번호의 새 사건이 다시 걸릴 때만
   비용이 발생한다.
2. **문서 파일까지 고아로 남아 있다.** `documents/고양지원/2024타경2803/1/`에 실제
   문서 4개(appraisal.pdf/spec.pdf/status.html/status.json, 12.4MB)가 그대로 있다 -
   이번 조사는 큐 행만 보고 디스크 파일 고아는 놓쳤다.

**[조치, 최종]** 새 도구를 만드는 대신 **기존 `cleanup_orphans_dryrun.py`를 그대로
쓴다.** `test_pipeline_integrity.py`의 고아 행 검사에 추가한 "document_queue ->
auction_item(court+case+item)" 자동 회귀 가드(상한 21, mutation 검증 완료)는 **그대로
유지한다** - 기존 도구는 수동 진단 스크립트라 CI에서 안 도는데, 이 가드는 그것을
`run_python_tests.py`가 매번 자동으로 확인하게 만든 것이라 여전히 새로운 가치다.
정리(큐 행 삭제 또는 `mark_queue_unsupported()`, 문서 파일 삭제)는 여전히 운영 데이터
변경이라 승인 영역이다.

--------

#179

**`favorites`/`recent_items`가 `auction_item` INNER JOIN이라, 행이 없어지면
사용자에게 아무 신호 없이 항목이 사라진다** — #98(admin.py 등기부 신청 목록)과
같은 계열, 사용자 화면 두 곳에서 재발

해결 (2026-08-23 Sprint 267 발견·수정)

**[경위]** `api/v1/admin.py`가 Sprint 97에 registry_requests 목록의 `JOIN auction_item`을
`LEFT JOIN`으로 고치면서 "INNER JOIN이면 auction_item 행이 사라진 신청이 관리자
목록에서 아무 신호 없이 사라진다"는 원인을 문서화해 뒀는데, **같은 `auction_item.id`
참조 패턴**을 쓰는 `api/v1/favorites.py:get_favorites()`와
`api/v1/recent_items.py:get_recent_items()`는 그 수정에서 빠져 있었다. 발생 조건은
동일하다 - `auction_item`을 직접 지우는 경로는 없지만, 011~013처럼 **FK를 끄고 도는
재작성 마이그레이션**이 UNIQUE 정리로 행을 떨어뜨리면 이 상태가 된다.

**[영향 차이]** admin.py 케이스는 운영자가 신청 존재 자체를 모르게 되는 문제였다.
이쪽은 **일반 사용자의 관심물건/최근 본 물건이 본인도 모르게 사라지는** 문제라 노출
범위가 더 넓다 - 사용자는 자신이 즐겨찾기한 적 없다고 오해하게 된다.

**[실측]** 이 환경의 `favorites`/`recent_items`는 현재 둘 다 0행이라 실제 고아는
없다(`SELECT COUNT(*) FROM favorites f WHERE NOT EXISTS (SELECT 1 FROM auction_item ai
WHERE ai.id=f.item_id)` → 0). 즉 지금 당장 사용자가 겪고 있는 결함은 아니고, admin.py와
같은 잠재적 재발 경로였다.

**[조치]** 두 쿼리 모두 `LEFT JOIN`으로 바꾸되, admin.py처럼 깨진 카드를 화면에 그대로
보여주지는 않는다(사용자 화면에 전부 null인 카드를 보이는 것은 더 나쁜 UX) - 화면에
보이는 목록에서는 그대로 걸러내되, 걸러진 사실은 `logger.warning(user_id, 건수)`로
남겨 admin.py의 "조용한 영구 방치 방지" 취지를 사용자 화면 특성에 맞게 유지한다.
신규 회귀 `test_favorites_and_recent_items_survive_orphaned_auction_item()`이 실제로
고아 행을 심어(FK OFF) 200 응답 + 목록에서 제외 + 로그 기록을 함께 검증하고,
INNER JOIN으로 되돌리는 mutation으로 "로그 없이 조용히 사라짐"이 재현되는 것도
확인했다. `api/v1/*.py` 전체를 `JOIN auction_item` 패턴으로 재검색해 다른 인스턴스가
없음을 확인했다(admin.py 3곳 / registry.py 2곳은 이미 LEFT JOIN).

--------

#180

**자동 만료 동기화(`sync_expired_status`)가 그 사이 확정된 상태 변경을 조건 없이
덮어쓴다 — 최종 상태인 CANCELLED 를 EXPIRED 로 바꿔 금지된 전이를 DB 에 남긴다**

해결 (2026-08-24 Sprint 254 발견·수정)

**[경위]** `storage/database.py` 의 큐 claim 경쟁 분기를 닫은 뒤(Sprint 254 전반부),
같은 부류 ― "조건부 UPDATE + rowcount 확인" ― 를 제품 전체에서 전수 검색했다.
`api/v1/*.py` 의 `rowcount == 0` 분기 8곳 중 3곳이 합산 커버리지에서 미실행이었다
(payments.py:458/602, subscriptions.py:213). 그 셋을 결정적으로 재현하려다 **셋 다
현재는 도달 불가능**하다는 것을 먼저 확인했다 ― 세 함수 모두 SELECT **앞에서**
`BEGIN IMMEDIATE` 로 쓰기 락을 잡기 때문이다.

```
[BEGIN IMMEDIATE 있음]   끼어든 쪽 1.075초 대기 후 실행   제품 rowcount=1  가드 미도달
[없음 (대조군)]          끼어든 쪽 0.002초 즉시 실행      제품 rowcount=0  가드 도달
```

그렇다면 **락 없이 쓰는 경로**가 있는지가 진짜 질문이 된다. 구독 상태를 쓰는 문장을
전수로 훑었더니 `sync_expired_status()` **하나만** 조건이 없었다:

```sql
UPDATE subscriptions SET status=?, updated_at=? WHERE id=?      -- CAS 없음
```

그리고 이 함수는 **읽기 경로**(`GET /api/v1/subscriptions/me`, Admin 사용자 목록)에서
`BEGIN IMMEDIATE` 없이 불린다. 즉 이 저장소에서 창이 실제로 열려 있는 유일한 자리다.

**[실측]** scratch DB + 커넥션 래퍼로 창을 벌려 결정적으로 재현했다.

```
ACTIVE(만료됨) 을 읽음
  -> 그 사이 사용자가 해지 (change_status: ACTIVE -> CANCELLED, 정식 경로)
  -> sync 가 EXPIRED 로 덮어씀
최종 상태: EXPIRED   (해지가 사라졌다)
```

**[영향]** 세 가지가 함께 깨진다.

1. **금지된 전이가 DB 에 남는다.** `CANCELLED` 는 최종 상태다
   (`api/v1/state_machines.py`: `CANCELLED: set()`). 이 UPDATE 는 바로 위 줄에
   "전이 규칙을 우회하지 않는다 — 자동 전이도 같은 관문을 통과해야 한다"고 적어 둔
   그 관문을 **실제로 우회한다** — `assert_subscription_transition()` 을 부르긴 하지만
   판정에 쓰는 상태(읽었던 ACTIVE)와 덮어쓰는 대상의 상태(CANCELLED)가 다르기 때문이다.
2. **해지된 구독이 되살아날 수 있다.** EXPIRED 는 최종이 아니다(EXPIRED -> ACTIVE 허용).
3. **로그가 사실이 아니다.** `구독 자동 전이: id=1 ACTIVE -> EXPIRED` 가 남는데
   실제로 덮인 것은 CANCELLED 다 (BUGS #47 계열).

일시정지(PAUSED)가 끼어드는 경우도 같다 — 전이 자체는 허용이지만 사용자가 건 정지가
말없이 사라지고 이용 권한이 끊긴다.

**[해결]** 이 모듈의 다른 writer(`change_status()`, `renew()`)가 이미 쓰는 패턴을
그대로 적용했다 — 읽었던 상태를 `WHERE ... AND status=?` 로 다시 걸고, `rowcount == 0`
이면 그 행을 건너뛴다(실패가 아니다. 이긴 쪽의 판단이 더 최신이고, 이 함수는 멱등이라
다음 호출이 새 상태를 기준으로 다시 판단한다). API/스키마 변경은 없다.

**[회귀]** `test_race_conditions.py` 17 — 커넥션 래퍼로 창을 벌려 **결정적으로** 재현하고,
해지 보존 / `changed` 집계 / 멱등성 / "이 전이가 애초에 금지"까지 함께 본다.
같은 파일 18 은 **다음에 추가될 writer** 를 막는다 — 구독 상태를 쓰는 모든 UPDATE 문에
`AND status=?` 가 있는지 소스에서 전수 확인한다(인접 문자열 리터럴을 먼저 이어 붙인다.
조각만 보면 `renew()` 의 CAS 를 오탐한다).
변이 확인 3/3: CAS 제거 / 진 것을 바꿨다고 셈 / CAS 값을 목표 상태로 바꿈 — 전부 검출.

**[남긴 것]** payments.py:458·602 와 subscriptions.py:213 의 `rowcount == 0` 분기는
그대로 둔다. 현재 락 규율에서는 도달하지 않지만, 락 순서가 바뀌는 날 그것들이 유일한
방어선이 된다. 지우면 그날 조용히 뚫린다. 자세한 실측은
`docs/SPRINT254_CLAIM_RACE_BRANCHES.md`.
--------

#181

**stale 회수로 큐 행을 빼앗긴 실행이, 뒤늦게 그 행을 자기 것처럼 종결한다**
(좀비 워커 — 남의 진행을 덮고, 남의 재시도 예산을 깎는다)

해결 (2026-08-24 Sprint 254 발견·수정)

**[경위]** #180 에서 "조건부 UPDATE + rowcount" 를 제품 전체로 전수 감사하면서,
상태를 **조건 없이** 쓰는 문장 6개를 찾았다. 하나(`UPDATE auction SET ...`)는
크롤 데이터 컬럼이라 해당 없고, 나머지 다섯은 전부 큐 **종결** 경로였다.

```
mark_queue_done      UPDATE document_queue SET status='done' WHERE id=?
mark_queue_failed    UPDATE document_queue SET status='failed', retry_count=? ... WHERE id=?
mark_queue_failed    UPDATE document_queue SET status=?, retry_count=?, ... WHERE id=?
mark_queue_skipped_expired / mark_queue_unsupported   (같은 모양)
```

집는 쪽은 CAS 로 단단히 막혀 있는데(Sprint 191/236), **끝내는 쪽은 아무 확인도
하지 않았다.** 그리고 여기서는 상태 CAS 를 걸어도 소용이 없다 — 회수 뒤 다시 집힌
행도 똑같이 `in_progress` 라서 "내 claim" 과 "남의 claim" 이 구별되지 않는다.

**[성립 조건]** 두 가지가 겹치면 된다. 둘 다 이미 제품에 있는 값이다.

```
doc_worker.LOCK_STALE_HOURS = 5     5시간 넘게 락이 남아 있으면 죽은 것으로 보고 넘어간다
reset_stale_queue()  10분          10분 넘게 in_progress 인 행을 회수한다
```

오래 도는 실행 A 가 있고 그 사이 B 가 시작하면, B 는 A 가 붙들고 있던 행을 회수해
자기 것으로 만든다. 그 뒤 A 가 종결을 부른다.

**[실측]** scratch DB 로 결정적으로 재현했다(확률 개입 없음).

```
A claim -> (10분 초과) -> B 의 stale 회수 -> B 가 다시 claim
  사례 1  A 가 성공으로 끝남   -> 행이 'done' 으로 바뀐다   B 는 헛돌고 있다
  사례 2  A 가 실패로 끝남     -> 행이 'pending' + retry 1  제3의 실행이 또 집을 수 있다
```

**[영향]**
- 같은 문서를 두 번 받는다(법원 부하 2배, 같은 다운로드 폴더 동시 접근).
- B 가 뒤이어 실패로 종결하면 **방금 성공한 문서가 'failed' 로 뒤집힌다.**
- 사례 2 는 그 행의 재시도 예산(`MAX_DOC_RETRY=3`)을 자기 몫이 아닌 실행이 깎는다.
  이것이 3회 쌓이면 멀쩡한 문서가 영구 실패로 굳는다(#137 계열).

**[해결]** claim 토큰. `claim_next_queue_item()`/`claim_next_item_rows()` 가 claim 시점에
써 넣은 `last_attempt_at` 을 `claim_token` 으로 함께 돌려주고, 종결 함수가 그 값을
다시 걸어 소유권을 확인한다(`_claim_is_still_ours()`).

**스키마는 바꾸지 않는다** — 이미 있는 컬럼을 세대 번호로 쓴다. 시그니처도 깨지 않는다:
`claim_token=None` 이면 예전 동작 그대로다(토큰을 넘기지 않는 기존 호출부의 계약 유지).

성공과 실패의 규칙을 **다르게** 뒀다.

```
mark_queue_done    큐 상태만 건너뛰고 document_status/doc_raw 는 그대로 쓴다
                   -> 파일은 실제로 받아졌다. 화면이 그 사실을 반영해야 한다(멱등).
mark_queue_failed  아무것도 쓰지 않는다
                   -> 그쪽이 성공할 문서를 '수집실패' 로 보이게 하면 안 되고,
                      남의 claim 을 풀거나 남의 예산을 깎아서도 안 된다.
```

**[회귀]** `test_worker_batching.py` 14/15/16.
14·15 는 회수→재claim 을 만들어 늦은 성공/늦은 실패를 각각 태우고, 대조군(자기 claim)
으로 "검사가 공허하지 않음"까지 본다. 16 은 **실제 `doc_worker.main()`** 을 돌려
워커가 두 종결 경로 모두에 토큰을 넘기는지 본다.
변이 확인 7/7 — 그중 **T7(워커가 토큰을 안 넘김)은 처음에 살아남았다.** 단위 검사는
직접 토큰을 넣어 부르므로 제품의 방어가 옳다는 것만 증명하고, **호출부가 그 방어를
쓰는지**는 증명하지 못했다. 16번이 그 구멍이다.

**[부수 정정]** `test_doc_worker_recovery.py` 의 `mark_queue_failed` 대역 4개가 인자를
2개로 고정하고 있어, 워커가 토큰을 넘기기 시작하자 대역만 터졌다. 대역이 실물보다
좁으면 제품 결함이 아닌 것을 결함처럼 보이게 한다 — 실물과 같은 모양으로 맞췄다.

**[남긴 것]** `mark_queue_skipped_expired()` / `mark_queue_unsupported()` 도 같은 모양이지만
그대로 뒀다. 둘은 **기일이 지났다 / 지원하지 않는 종류다** 라는, 어느 실행이 판단하든
같은 결론이 나오는 사실을 쓴다(진행 상태를 되돌리지도, 재시도 예산을 건드리지도 않는다).
토큰을 걸면 그 사실의 기록만 늦어진다. 판단이 실행마다 달라질 수 있게 되는 날
(예: 기일 판정에 실행 시각이 섞이는 변경) 다시 볼 것.
--------

#182

**브라우저가 죽어도 드라이버 재시작 복구가 발동하지 않는다 - 그리고 그 법원이
"기일 없어 스킵"으로 요약된다** (배치 요약이 사실이 아닌 것을 말한다, #47 계열)

해결 (2026-08-24 Sprint 254 발견·수정)

**[경위]** 전체 스위트 합산 커버리지에서 `crawler/court_crawler.py` 가 **26%** 였다
(93문 중 69 미실행). 미실행 구간이 정확히 `crawl_detail()` + `crawl_court()` 둘,
즉 **매일 06:00 크롤의 본체 판단이 통째로 미검증**이었다.
(`test_crawl_error_log.py` 는 `log_error()` 만, `test_crawl_orchestration.py` 는 그
위층인 `run_courts()` 만 본다 - 가운데가 비어 있었다.)

그 빈칸을 열어 보니 `crawl_court()` 의 복구 코드가 **도달 불가능**했다.

```python
try:
    result = crawl_detail(driver, item_info, court)
except Exception as e:
    logger.error("세션 오류 감지: %s. 드라이버 재시작", str(e))
    driver = restart_driver(driver)          # <- 여기에 오는 길이 없다
```

`crawl_detail()` 이 `except Exception` 으로 **모든** 예외를 잡아 `MAX_RETRY` 만큼
재시도한 뒤 `None` 을 돌려주기 때문이다. 브라우저가 죽어도 그것이 "이 사건을 못
읽었다"로 처리된다.

**[실측]** Selenium 없이 협력자만 갈아 끼워 재현했다(항목 4개, 매번 세션 사망):

```
build_driver     1회
restart_driver   0회   <- 복구가 한 번도 안 돈다
go_to_list      12회   = 항목 4 x 재시도 3, 전부 헛돌았다
수집             0건
```

**[영향]** 두 겹이다.

1. **복구가 없다.** 브라우저가 한 번 죽으면 그 법원의 남은 물건이 전부 실패한다
   (doc_worker 가 #137/#232 에서 고친 연쇄 실패와 같은 모양인데, 이쪽은 고쳐진 적이 없다).
2. **더 나쁜 쪽 - 요약이 거짓이 된다.** `crawl_court()` 이 빈 목록을 돌려주고,
   `run_courts()` 는 `if not items: skipped.append(...)` 로 그것을 **"기일 없어 스킵"**
   으로 센다. 브라우저가 죽은 것을 "그 법원은 경매가 없었다"고 말하는 것이다.
   `failed` 에 안 잡히므로 `CrawlOutcome.exit_code()` 도 0 - **배치가 성공으로 끝난다.**
   이것이 정확히 BUGS #47 이 만든 사고의 모양이다.

**[해결]** "브라우저가 죽었다"와 "이 항목이 실패했다"를 나눈다.
`is_session_dead()` + `BrowserSessionLost` 신설. `crawl_detail()` 은 세션 사망이면
재시도하지 않고 올리고, `crawl_court()` 의 기존 복구가 그것을 받아 재시작한다.
재시작 뒤에도 죽어 있으면 예외가 위로 올라가 `run_courts()` 가 그 법원을
**`failed` 로** 센다(더 이상 `skipped` 가 아니다).

판정은 **이름과 문구를 둘 다** 본다. 어느 한쪽만으로는 실제 사례를 놓친다:
클래스가 `InvalidSessionIdException` 인데 메시지가 낯선 경우(드라이버 버전/로케일),
반대로 클래스는 밋밋한 `WebDriverException` 인데 문구가 `chrome not reachable` /
`disconnected: not connected to DevTools` 인 경우가 **둘 다 실제로 온다.**

★ `WebDriverException` 을 통째로 잡으면 안 된다. `NoSuchElementException` /
`TimeoutException` 이 그 자식이라, 평범한 "이 화면에 그 요소가 없다"까지 세션 사망으로
오판해 멀쩡한 브라우저를 매번 재시작하게 된다.

곁들여 `finally` 의 `driver.quit()` 도 감쌌다 - 죽은 세션을 닫을 때 실제로 던지는데,
그러면 **원래 원인이 종료 실패로 바뀌어** 운영자가 브라우저가 죽었다는 사실을 못 본다.

**[회귀]** `test_court_crawl_recovery.py` 신설(31검사). 판정표(넓은 쪽/좁은 쪽 각 5개) /
죽었다 살아나는 복구 / 끝까지 죽어 있으면 예외 / 평범한 실패는 재시작 없음 /
`go_to_list` 가 False 를 주는 경우 / 조기 반환 3종 + 항상 브라우저를 닫는다 /
`quit()` 실패가 원인을 덮지 않는다 / 체크포인트 재시작·정리 /
**`run_courts()` 요약이 `failed` 로 센다**(이 결함의 사용자 쪽 얼굴).
`crawler/court_crawler.py` 커버리지 **26% -> 100%**.
변이 확인 7/7 - 판정의 두 갈래(이름/문구)를 각각 지우는 변이가 **따로** 잡힌다.

**[걷어낸 것]** 판정에 `isinstance` 로 selenium 클래스를 직접 대조하는 판을 한 번
넣었다가 **도로 뺐다.** 이름 대조와 결과가 갈리는 경우는 "그 클래스의 하위 클래스"
뿐인데 selenium 4.47 에는 그런 클래스가 하나도 없다(실측). 어떤 입력으로도 다른
결과를 내지 못하는 분기였고 mutation 으로 지워도 아무 검사가 죽지 않았다.
검증할 수 없는 코드 대신 **왜 없는지**를 주석으로 남겼다.
--------

#183

**락 자리에 파일이 아닌 것이 있으면 `acquire()` 가 예외를 올려 배치가 죽는다**
(락을 못 얻는 것은 실패가 아닌데, 실패로 끝난다)

해결 (2026-08-24 Sprint 254 발견·수정)

**[경위]** #181 을 고치면서 그 전제 조건인 `RunLock` 의 **회수 토큰 경합** 경로가
합산 커버리지에서 한 줄도 실행되지 않는 것을 발견했다(`storage/checkpoint.py`
85%, 미실행 17줄). 그 경로가 뚫리면 두 실행이 동시에 회수해 **두 워커가 같이
돈다** ― 즉 #181 이 성립하는 조건 자체다. 그래서 그 위층부터 잠그기로 하고
회귀 5건을 썼는데, 그중 하나가 제품 결함을 잡았다.

**[실측]** 락 경로에 **디렉터리**를 두고 `acquire()` 를 부르면:

```
PermissionError(13, 'Permission denied')  가 acquire() 밖으로 나온다
```

`_create_exclusive()` 가 `except FileExistsError` 만 잡기 때문이다. Windows 에서
디렉터리를 `O_CREAT|O_EXCL|O_WRONLY` 로 열면 `FileExistsError` 가 아니라
`PermissionError` 가 온다.

**[영향]** `doc_worker` / `mvp_scraper` 가 **락 정리 하나 때문에 예외로 죽는다.**
그날 수집이 통째로 사라지고, 원인은 "권한 거부" 라는 엉뚱한 메시지로만 남는다.
이 저장소는 OneDrive 동기화 폴더 안에 있어 그런 잔여물이 남는 일이 실제로 있다
(`test_checkpoint_atomicity.py` 상단이 같은 환경에서 겪은 flaky 사고를 이미 기록한다).

락을 못 얻는 것은 **실패가 아니다** ― 설계상 "다른 실행이 이미 그 일을 하고 있으니
이번엔 아무것도 하지 않는다" 이고, 그때는 조용히 0으로 끝나야 한다.

**[해결]** `_create_exclusive()` 에 `except OSError` 를 추가해 False 로 물러난다.
단, 정상적인 "남이 잡고 있다"(`FileExistsError` -> 조용히 False)와 **구별되게
warning 을 남긴다** ― 조용히 False 를 돌려주면 매일 아무 일도 안 하면서 이유를
알 수 없다(이 저장소가 #47 이래 반복해 잡아 온 "조용한 무동작").

**[회귀]** `test_checkpoint_atomicity.py` 8~12.
회수 토큰 경합(진행 중 / 죽은 토큰 / 토큰 경쟁에서 패배) / 토큰을 잡은 뒤 재확인 /
회수 중 락이 사라짐 / 확인 직후 락이 사라짐 / **파일이 아닌 것이 있을 때 물러남**.
`storage/checkpoint.py` 커버리지 **85% -> 96%**. 변이 확인 6/6.

**[남긴 것]** 미실행 4줄(`getmtime(token)` 의 OSError, `finally` 의 토큰 삭제 실패)은
표준 라이브러리를 갈아 끼워야 밟을 수 있다. 방어의 목적(예외를 올리지 않고 물러난다)은
위 검사들이 이미 고정하므로, 그 두 줄을 위해 테스트를 비틀지 않는다.

**[곁가지]** 이 과정에서 커버리지 측정이 **실행마다 달라지는** 것을 발견했다
(`143-145` 가 있다 없다 한다). 원인은 `test_doc_worker_recovery.py` 의 스레드 8개
검사가 그 경로를 "가끔" 밟기 때문이었다. 가끔 밟는 것은 방어선이 아니므로
결정적 검사(11번)를 따로 만들어 고정했다 ― #130 에서 배운 것과 같은 교훈이다.

--------

#184

**운영에 실제로 등록된 유일한 스케줄러 작업(`DOJOONPASS_DAILY` → `run_daily.bat`)은
DB migration 을 절대 적용하지 않는다** (등록 여부와 무관하게 영원히 안 걸린다)

발견 (2026-08-24 야간, 코드로 원인 확정 — 이전 "DB 가 백업으로 되돌아갔다" 추정은 철회)

**[경위]** Sprint 254 문서가 오늘 아침 `auction_image 45행 / doc_raw 556행`으로 기록해
둔 값이, 같은 날 야간 재실측에서 `auction_image` 테이블 자체가 없고 `doc_raw` 는 0행으로
나왔다. 처음에는 이 저장소가 migration 020(Sprint 144, `doc_raw` 를 556행까지 채운 것과
같은 스프린트) 이전 시점의 백업으로 되돌아갔다고 추정했다. 그런데 실제로 유일하게 등록된
작업이 도는 `run_daily.bat` 를 읽으면 추정할 필요가 없다 — 원인이 코드에 그대로 있다.

**[실측]**

```bat
"%PY%" mvp_scraper.py >> logs\daily_run.log 2>&1        REM init_db() 만 호출 (레거시 3테이블)
"%PY%" migrate_execute.py >> logs\migrate_execute.log 2>&1
```

`storage.migrations.run_migrations` 를 부르는 줄이 **어디에도 없다.** `migration_history`
에 001~019 가 이미 적용돼 있는 것도 이 배치 덕이 아니다 — 타임스탬프(07-20, 07-21, 07-25,
07-28, 08-08×3, 08-11×2, 08-13)가 매일 규칙적이지 않고 개발 세션 시각에 몰려 있다. 즉
그때그때 사람이 `python -m storage.migrations.run_migrations` 를 수동으로 돌렸다는 뜻이고,
Sprint 144(08-17) 이후로는 아무도 그렇게 하지 않았다. **매일 자동으로 도는 유일한 작업은
애초에 그 일을 하지 않으므로, 020 도 앞으로 생길 어떤 migration 도 스케줄러 등록 여부와
무관하게 영원히 자동 적용되지 않는다.**

**[영향]** `auction_image` 테이블이 없어 사진 파이프라인이 통째로 죽어 있다(API 는
Sprint 239 이래 이 상태를 우아하게 처리해 500 은 안 나지만, "사진 없는 화면"으로만
보여 사용자가 결함으로 인지하기 어렵다 — 더 위험한 종류다). `document_status` 는 READY
555건인데 그중 `doc_raw` 로 뒷받침되는 것이 **0건**이라, 재수집 없이는 쪽수/크기/버전이
영원히 null 이다(BUGS #144 의 재발이 아니라 지속 — Sprint 144 의 수정 자체는 여전히 코드에
있다, 위 mark_queue_done()/`_record_doc_raw()` 확인). 이 결함은 새 migration 을 추가하는
모든 미래 Sprint 에 반복된다 — 코드로 아무리 잘 고쳐도 운영에 자동으로 안 실린다.

**[doc_raw 0행의 별개 원인]** `document_queue.last_attempt_at` 최댓값이 **2026-07-12**
에서 41일째 정체돼 있다(`enqueued_at` 은 오늘까지 계속 늚 — `audit_schedule_health.py` 의
새 `queue_stall_signal()` 이 이번 세션부터 이것을 직접 잰다). `doc_raw` 를 쓰는 유일한
경로(`mark_queue_done()`)는 DocWorker 안에 있고, `DojoonPass-DocWorker` 는 스케줄러에
등록된 적이 없다(여러 Sprint 가 이미 기록). `logs/doc_run.log` 의 "2026-08-22 06:02
[SUCCESS]" 는 큐를 실제로 비웠다는 뜻이 아니라 — 실행 창(~04:00)이 지난 뒤 브라우저 없이
곧바로 종료하는, 설계된 그 SUCCESS 로 보인다(`last_attempt_at` 이 그 날 전혀 안 움직인
것이 근거) — #47 계열의 "배치가 성공으로 끝나는데 아무 일도 안 했다"가 여기서도 그대로다.

**[해결하지 않음 — 승인 영역]** 정확한 수정안(마이그레이션 1회 수동 실행 /
`run_daily.bat` 에 러너 호출 추가 / DocWorker 등록)은 `docs/BETA_RELEASE_CHECKLIST.md`
2026-08-24 야간 절에 [권장 조치]로 남겼다. `run_daily.bat` 는 내일 03:00 에 사람 검토 없이
그대로 실행되는 운영 스크립트라, 그 내용을 고치는 것 자체가 "무인으로 운영 DB 에 migration
을 적용하는 것"과 같다 — `docs/CLAUDE.md` 프로젝트 원칙(DB 스키마 변경은 승인 후)과 이
세션의 SKIP 목록 둘 다에 걸려 코드를 고치지 않았다.

**[회귀]** `audit_schedule_health.py` 에 `queue_stall_signal()` 신설 + selftest 6건
(ISO 타임스탬프 파싱 / 정체 없음 대조군 / 문턱 초과 지목 / moot 비율 보고 / 처리 이력
전무 지목 / 재료 없으면 판정 보류). `test_audit_selftests.py` 로 재확인 — 그대로 통과.

**[남긴 것]** 이 결함의 근본 수정(마이그레이션 자동화 + DocWorker 등록)은 전부 승인
영역이다. 다음 세션은 이 문서의 [권장 조치] 3단계를 그대로 따르면 된다 — 원인 재조사가
필요하지 않다.

--------

#185

**#184 를 철회한다 — 그 항목의 실측값은 운영 `auction.db` 가 아니라 pre-020 백업 파일을
잰 것으로 보인다** (그리고 그 오측이 회귀 스위트를 red 로 만들었다)

발견 (2026-08-25, `78f4ef5` 직후 상태를 독립 재실측)

**[경위]** `78f4ef5` 는 `docs/BUGS.md` #184 / `docs/CLAUDE.md` / `docs/BETA_RELEASE_CHECKLIST.md`
세 곳에 "2026-08-24 야간 재실측"을 기록하고, 그 근거로 `P0A-VERDICT` 토큰을 OPEN -> RESOLVED
로 뒤집었다. 다음 세션이 그 값을 다시 재니 **여덟 항목이 전부 어긋났다.**

**[실측]** 2026-08-25 08:20~08:30, 전부 읽기 전용(`file:...?mode=ro`), 경로는
`storage.database.DB_PATH` 경유(손으로 파일명을 고르지 않았다):

```
항목                        #184 주장                 2026-08-25 실측
--------------------------  ------------------------  ---------------------------------
migration_history 최신       019 (020 미적용)          020_create_auction_image
                                                      (2026-08-17T09:03:19 적용)
auction_image               "테이블 자체가 없다"       있다, 45행 (파일 누락 0건)
doc_raw                     0행                       556행 (파일 누락 0건)
document_status READY       555건, 뒷받침 0건         556건, doc_raw 없는 것 0건
auction_item crawl_date max 2026-08-24 "오늘도 돌았다" 2026-08-12 (그날 9행, 그 전 08-01)
기일 미도래 물건             291건 (최종 09-02)        0건 (최종 2026-08-19)
auction_item 총 행           2,376                     1,876
예약 작업                    1개 \DOJOONPASS_DAILY     0개 (전체 478개 전수 스캔)
```

`auction.db` 는 그 사이 교체되지 않았다 — `migration_history` 의 020 타임스탬프가
**2026-08-17** 로 #184 작성 시점보다 앞서고, `quick_check ok` / `foreign_key_check` 위반
0건이다.

**[원인 — 어느 파일을 쟀는가]** 저장소 루트에는 이름이 비슷한 DB 백업이 **16개** 있다.
그중 `auction.db.backup_before_020_20260817_090319` 와, 2026-08-13 이후 방치된 worktree 의
`.claude/worktrees/sprint95-false-success-audit/auction.db` 가 **#184 의 서술과 정확히
같은 상태**다:

```
                     migmax  items  queue  docstatus  doc_raw  auction_image
운영 auction.db        20    1,876  3,498    5,628      556       45행
backup_before_020      19    1,876  3,498    5,628        0     테이블 없음   <- #184 가 서술한 값
worktree 사본          19    1,876  3,498    5,628        0     테이블 없음   <- 같음
```

행수가 운영본과 전부 일치해서 **"최신 DB 를 보고 있다"고 착각하기 쉽다.** 다른 것은
migration 번호와 자산 테이블뿐이다. 다만 "2,376행 / 291건 / 최종 09-02" 는 이 PC 의 DB
파일 18개 어느 것과도 일치하지 않아 **출처는 확인 불가**로 남긴다.

**[영향 — 문서 오류가 테스트를 깨뜨렸다]** 이 저장소는 "문서가 실측과 다른 말을 하면
스위트가 빨개진다"를 이미 장치로 갖고 있고, 그 장치가 정확히 작동했다. `78f4ef5` 직후
`python run_python_tests.py` = **통과 52 / 실패 2**:

* `test_bootstrap.py` `test_claude_md_bootstrap_claims_are_true()`
  -> `CLAUDE.md 가 말하는 마이그레이션 끝 번호: 19 (expected 20)`.
  #184 가 `docs/CLAUDE.md` 에 넣은 "001~019" 표현 때문. 같은 문서 다른 줄은 여전히
  "001~020" 이라 **문서가 자기모순**이었다.
* `test_pipeline_integrity.py` `test_checklist_p0a_verdict_matches_reality()`
  -> 토큰은 RESOLVED 인데 실측은 기일 남은 물건 0건(=OPEN).

**[수정]** 세 문서를 실측에 맞춰 정정하고 토큰을 OPEN 으로 되돌렸다. 원래 서술을 지우지
않고 **철회 문단을 앞에 두는** 이 저장소의 관례를 따랐다 — 무엇이 왜 틀렸는지가 남아야
같은 오측이 반복되지 않는다. `audit_asset_integrity.py:160` 의 주석도 같은 이유로 정정했다
(방어 코드 자체는 유효하므로 그대로 둔다 — 새 개발자의 빈 DB 나 pre-020 백업을 대상으로
돌 수 있다).

**[회귀]** 두 실패 중 문서 원인 2건은 해소됐다. 남은 1건
(`기본 검색에 뜰 물건이 남아 있다`)은 **문서가 아니라 실제 데이터 상태**다 —
마지막 크롤이 2026-08-12 이고 기일 미도래 물건이 0건이라, 크롤(승인 영역)이 돌기 전에는
정직하게 red 로 남는 것이 맞다. 이 검사를 통과시키려고 상한이나 판정을 손대지 않았다.

**[교훈]** DB 를 잴 때는 반드시 `storage.database.DB_PATH` 를 경유한다. 감사기
(`audit_asset_integrity.py` / `audit_schedule_health.py`)는 둘 다 그 경유를 이미 하므로
**감사기를 그냥 돌렸으면 이 오측은 일어나지 않았다.** 손으로 `sqlite3.connect("...")` 에
파일명을 적는 순간 16개 백업 중 하나를 고를 위험이 생긴다.

--------

#186

**회귀 스위트가 운영 `auction.db` 에 직접 썼다** — 행수가 원복돼서 아무도 몰랐다

발견 (2026-08-25, `run_python_tests.py` 전후로 운영 DB 의 md5 가 바뀌는 것을 보고)

**[경위]** 기준선을 잡으려고 전체 스위트를 한 번 돌렸는데, 그 전후로 `auction.db` 의
md5 가 바뀌어 있었다. 파일별로 격리해(파일 하나 돌리고 md5 대조) 범인을 특정했다 —
**5개다**:

```
test_api_regression.py / test_beta_journey.py / test_doc_storage_atomicity.py
test_race_conditions.py / test_subscription_policy.py
```

다섯 다 `from storage.database import get_connection` 으로 **운영 DB 에 그대로 붙어**
합성 행(`qa-*` 사용자, 가짜 결제/구독/등기 신청)을 심고 단언한 뒤 지운다.

**[왜 오랫동안 몰랐나]** 끝에 지우므로 **행수가 정확히 원복된다.** 25개 테이블 전수
`COUNT(*)` 비교에서 차이가 0이었다. `iterdump()` 를 통째로 비교해서야 무엇이 바뀌는지
보였다:

```
sqlite_sequence 전진 (1회 실행):
  search_presets       177,089 -> 177,299   (+210)
  payment_logs          88,805 ->  88,917   (+112)
  registry_requests     41,994 ->  42,047   (+53)
  audit_logs            38,701 ->  38,750   (+49)
  subscriptions         34,429 ->  34,472   (+43)
  registry_credit_logs  34,648 ->  34,690   (+42)
  payments              30,996 ->  31,035   (+39)
  recent_items          30,192 ->  30,226   (+34)
  registry_usage        19,043 ->  19,064   (+21)
  payment_webhooks      13,384 ->  13,403   (+19)
  auction_item          16,711 ->  16,720   (+9)
  favorites              7,238 ->   7,247   (+9)
  auction_case           8,613 ->   8,616   (+3)
  document_collect_failures 903 ->    904   (+1)
  document_queue        18,380 ->  18,381   (+1)
```

**[영향]** 숫자만 보면 작아 보이지만 위험은 그것이 아니다.

1. **중간에 죽으면 지우는 코드에 도달하지 못한다** — 합성 행이 운영 테이블에 그대로
   남는다. 하필 이 다섯은 스레드 경합과 실패 주입을 **일부러 일으키는** 파일들이라
   중간에 죽을 여지가 가장 큰 축에 속한다. 실제로 `test_doc_storage_atomicity.py` 는
   과거에 0.1초 만에 25단언에서 죽은 적이 있다(`run_python_tests.py` 의 Sprint 203 주석).
2. 테스트를 돌리는 동안 운영 API/워커가 같은 파일을 쓰고 있으면 경합한다.
3. 감사가 "운영 DB 무변경"을 근거로 삼는 순간 그 근거가 거짓이 된다 — 이 저장소의
   여러 Sprint 문서가 "운영 DB 무변경"을 기준선에 적어 왔다.

**[수정]** 이 저장소에 이미 올바른 선례가 있었다 — `test_admin_failure_injection.py` 는
"`auction.db` 사본을 임시 디렉터리에 두고 `storage.database.DB_PATH` 를 돌린다".
다섯 파일에 같은 블록을 `sys.path.insert(...)` 바로 다음(= `storage.database` /
`api_server` import 전)에 넣었다. `get_connection()` 은 `sqlite3.connect(DB_PATH)` 로
**호출 시점에** 모듈 전역을 읽으므로, 재지정 한 줄로 API 라우터까지 함께 돌아간다
(제품 코드 중 `DB_PATH` 를 직접 import 하는 곳은 없다 — 2026-08-25 전수 확인).

**[재발 방지 — 허용목록이 아니라 행동을 본다]** 고친 것보다 중요한 것은 다시 생기지
않게 하는 것이다 — 새 테스트 파일은 계속 추가된다. `run_python_tests.py` 가
**파일 하나를 돌릴 때마다 운영 DB 파일의 지문(크기+md5)을 재고**, 달라지면 그 자리에서
그 파일을 지목하고 **통과 여부와 무관하게 종료코드 1** 을 돌려준다. 허용목록(누가
무엇을 import 했는가)은 새 파일을 놓치지만 이건 놓치지 않는다. 감시 대상 경로도
이름으로 고르지 않고 `storage.database.DB_PATH` 를 경유한다(루트에 `auction.db.backup_*`
가 16개 더 있다 — BUGS #185 가 바로 그 혼동으로 생긴 사고다). 비용은 파일당 ~10ms
(전체 ~0.6s).

**[검증]**

```
수정 전  전체 스위트 1회      -> auction.db md5 변경됨
수정 후  다섯 파일 개별 실행  -> 전부 exit 0, 운영 DB **바이트 동일**
         전체 스위트 1회      -> 운영 DB **바이트 동일** (2991c5be...)
         감시기 mutation 검증 -> 감시 대상을 임시 파일로 갈아끼우고 그것을 쓰는 probe
                                파일을 심었더니 종료코드 1 + 이름 지목 + 그 자리 증거.
                                대조군(아무것도 안 건드리는 probe)은 종료코드 0.
                                이 검증 자체도 운영 DB 를 건드리지 않았다.
```

**[기준선]** 통과 52 -> **53**, 실패 2 -> **1**. 남은 1건은 문서가 아니라 실제 데이터
상태다(기일 미도래 물건 0건 — 크롤은 승인 영역). 단언 8,113건.

**[2차 결함 — 이 수정이 불러온 것]** 처음에는 공유 모듈 `qa_scratch_db.py` 를 새로 만들어
다섯 파일이 import 하게 했다. 그랬더니 **이 저장소의 기존 가드 둘이 곧바로 잡았다** —
실제로 작동하는 가드라는 증거라 그대로 적어 둔다.

* `test_schema_hygiene.py` 의 `test_tracked_sources_do_not_import_untracked()`
  -> 추적 파일 5개가 **미추적** `qa_scratch_db.py` 를 import 한다(BUGS #105 계열:
  `git commit -a` 하면 커밋된 트리가 ModuleNotFoundError 로 부팅도 못 한다).
  `git add` 는 승인 영역이라 **새 파일을 만드는 설계 자체를 철회**하고
  `test_admin_failure_injection.py` 처럼 파일마다 인라인했다.
* `test_console_encoding.py` -> 새 감시기 출력문에 넣은 엠대시(U+2014) 2개가 cp949
  콘솔에서 못 나간다. 하이픈으로 바꿈.

--------

#187

**`78f4ef5` 가 셸 사고 산출물 파일을 하나 커밋했다** — 파일명에 `"` 가 들어 있어
Windows 도구마다 다르게 보인다

발견 (2026-08-25, `78f4ef5` 의 추가 파일 전수 확인)

**[무엇인가]** 저장소 루트에 이런 파일이 추적되고 있다.

```
git 표기      "e hardening\357\200\242"     (git 이 비ASCII 를 8진 이스케이프로 찍는다)
실제 이름     e hardening"                  (마지막 글자가 큰따옴표)
Git-Bash ls   e hardening"
크기          6,139 B / 82줄
추가된 커밋   78f4ef5 (2026-08-25 06:51)
```

`\357\200\242` 는 UTF-8 로 **U+F022** 다. Windows 파일명에 `"` 를 쓸 수 없어서
Cygwin/Git-Bash 가 `"` 를 사유영역 문자 U+F022 로 바꿔 저장한 것이다. 즉 파일명은
**실제로 `e hardening"`** 이고, git 이 보는 바이트는 그 인코딩이다.

**[내용]** ANSI 색상 이스케이프가 그대로 박힌 **`git diff --check` 의 출력**이다.
`docs/CLAUDE.md:111~151` 에 대한 "trailing whitespace" 경고가 41쌍 나열돼 있고,
강조(`ESC[41m`)된 "공백"은 실제로는 **CR(`\r`)** 이다 — `docs/CLAUDE.md` 가 index 에
CRLF 로 들어 있어서 새로 추가된 줄마다 `git diff --check` 가 경고한 것이다.

```
$ head -c 60 "e hardening\"" | od -c
0000000   d   o   c   s   /   C   L   A   U   D   E   .   m   d   :   1
0000020   1   1   :       t   r   a   i   l   i   n   g       w   h   i
0000040   t   e   s   p   a   c   e   .  \n 033   [   3   2   m   +  ...
```

**[생성 목적]** 프로젝트가 필요로 해서 만든 파일이 **아니다.** 리다이렉션 따옴표가
깨진 셸 명령이 `git diff --check` 의 출력을 파일로 흘려보낸 것으로 보인다. 근거:

* 저장소 어디에서도 참조되지 않는다(`*.py` / `*.md` / `*.ts` / `*.tsx` / `*.bat` /
  `*.ps1` / `*.json` 전수 grep 0건).
* 내용이 도구 출력 그대로다 — 사람이 쓴 문장이 한 줄도 없다.
* 파일명이 커밋 메시지 "audit: continue release **hardening**" 의 꼬리와 일치한다.
* `.gitignore` 어느 규칙에도 걸리지 않아 `git add -A` 에 그대로 딸려 들어갔다.

**[해결하지 않음 — 승인 영역]** **삭제하지 않았다.** `docs/CLAUDE.md` 의 프로젝트 원칙
("승인 없는 파일 삭제 금지")에 걸리고, 이미 **추적 중인** 파일이라 작업트리에서 지우는
것만으로는 저장소에서 빠지지도 않는다(`git rm` + 커밋이 필요하고 그것도 승인 영역).
승인 후 정리할 사람을 위해 명령만 남긴다 — 파일명에 `"` 가 있어 그냥 치면 셸이 삼킨다:

```bash
git rm "e hardening\""        # Git-Bash. 큰따옴표를 이스케이프해야 한다
```

**[같은 계열의 진짜 문제 — `.gitattributes` 부재]** 이 파일이 기록한 "trailing
whitespace" 는 오탐이 아니라 **줄끝 규칙이 저장소에 없다**는 신호다. 실측(2026-08-25):

```
core.autocrlf = true          (시스템 gitconfig, 저장소 설정 아님)
.gitattributes                없음
git ls-files --eol            index 가 파일마다 다르다:
    docs/CLAUDE.md   i/crlf w/crlf     <- index 에 CRLF
    api_server.py    i/crlf w/crlf     <- index 에 CRLF
    docs/BUGS.md     i/lf   w/crlf     <- index 에 LF
    README.md        i/lf   w/crlf     <- index 에 LF
```

index 가 CRLF 인 파일은 `core.autocrlf=true` 와 조합되면 **다음에 `git add` 하는 순간
전체 줄이 LF 로 정규화돼 whitespace-only diff** 가 된다. 지금 `git status` 가 깨끗한
것은 git 이 크기/mtime 캐시로 내용 비교를 건너뛰기 때문이지 정합해서가 아니다.
`.gitattributes` 추가는 **대량 재정규화 커밋**을 유발하므로 승인 영역으로 남긴다.
(그래서 이번 세션의 문서 수정은 전부 **원본 줄끝을 보존**해서 썼다 — 확인:
`docs/CLAUDE.md` / `docs/BUGS.md` / `docs/BETA_RELEASE_CHECKLIST.md` 전부 lone LF 0개.)

--------

#188

**`audit_auth_health.py` 가 네트워크 타임아웃 한 번을 "로그인 인증이 사실상 막혀 있다"로
찍었다** — "모른다"를 "고장났다"로 읽었다 (같은 계열로 `audit_test_reality.py` 는
측정 실패의 이유를 한 글자도 남기지 않았다)

발견 (2026-08-25, 감사 도구를 순서대로 돌리다가 재현)

**[경위]** `python audit_auth_health.py` 가 이렇게 찍었다.

```
[2] ES256 주 경로 (JWKS)
    -> None (TimeoutError: The read operation timed out)
 종합: ★ ES256(주 경로) 실패 - 로그인 사용자 인증이 사실상 막혀 있다
```

문장만 보면 P0 다. 그런데 **몇 초 뒤 같은 주소로 직접 GET 을 보내니**:

```
attempt 1 -> HTTP 200  240 bytes  0.17s
   keys: ['487c69e7-e70b-4217-84b3-8fe11bdbab1d/ES256']
```

설정은 멀쩡했다. 네트워크 자체도 멀쩡했다(같은 시각 `github.com` HTTPS GET 200,
TLS 핸드셰이크 0.04초). 한 번의 딸꾹질이었다.

**[원인]** `_check_jwks_reachable()` 이 **타임아웃 5초로 한 번만** 보내고,
판정을 `status == 200` 두 갈래로만 했다.

```python
except Exception as exc:
    return None, "%s: %s" % (type(exc).__name__, exc)
...
ok = status == 200
...
elif secret_len:
    print(" 종합: ★ ES256(주 경로) 실패 - 로그인 사용자 인증이 사실상 막혀 있다")
return 0 if ok else 1
```

즉 **"주소가 틀렸다"와 "이번에 못 닿았다"가 같은 값으로 뭉개졌다.** 두 상태는 조치가
정반대다 — 앞은 사람이 `.env` 를 고쳐야 하고, 뒤는 고칠 것이 아무것도 없다.
하필 이 감사기의 docstring 은 첫 줄부터 "추측하지 않는다"라고 적고 있었다.

**[영향]** 이 도구는 `docs/BETA_RELEASE_CHECKLIST.md` 가 "운영 점검 도구"로 안내하고
종료코드까지 계약으로 적어 둔 것이다(`0=ES256 정상 / 1=주 경로 실패`). 자동화에 물리면
네트워크 딸꾹질마다 "인증 장애" 경보가 간다. 더 나쁜 것은 사람이 읽었을 때다 —
"로그인 인증이 사실상 막혀 있다"를 보고 `.env` 를 뒤지기 시작하면 멀쩡한 설정을
고치게 된다. **거짓 P0 는 진짜 P0 를 가린다.**

**[수정]** 판정을 세 갈래로 나눴다.

```
0  OK       200 + 공개키 1개 이상
1  FAILED   주소가 틀렸다는 확정 증거 (HTTP 오류 / 200인데 키 0개 / URL 비어 있음)
2  UNKNOWN  5/8/12초 3회 재시도해도 못 닿았다 - 고칠 것이 없다. 다시 재라
```

* 네트워크 계열 예외(타임아웃/DNS/TLS/연결거부)만 재시도한다.
* **HTTP 오류는 재시도하지 않는다** — 몇 번을 보내도 주소는 그대로다.
* `UNKNOWN` 일 때는 "실패"라고 적지 않는다. "확인하지 못했다 (네트워크가 이번에
  안 됐다) / 설정이 틀렸다는 뜻이 아니다"로 찍고 다시 재는 법을 안내한다.
* `SUPABASE_URL` 이 비어 있는 것은 네트워크와 무관하므로 그대로 `FAILED` 다.

**[회귀 + mutation]** `--selftest` 에 12건을 추가했다. `fetch` 를 주입해서 검사하므로
**회귀 스위트가 외부 서비스를 두드리지 않는다**(그 원칙은 `test_audit_selftests.py`
docstring 이 이미 세워 둔 것이다). 실제로 겪은 모양 — "앞 두 번 타임아웃, 세 번째 성공" —
을 그대로 심어 재시도가 있는지 확인한다.

mutation 5/5 검출:

```
M1 타임아웃을 FAILED 로 되돌린다 (원래 버그 그대로)   -> 잡았다
M2 재시도를 없앤다 (기본 1회)                        -> 잡았다
M3 HTTP 오류도 재시도하게 만든다                      -> 잡았다
M4 200/키0개를 OK 로 통과시킨다                       -> 잡았다
M5 빈 SUPABASE_URL 을 UNKNOWN 으로 오분류            -> 잡았다
```

M2 는 **처음에 놓쳤다.** 검사들이 전부 `timeouts=` 를 주입해서 돌기 때문에 상수를
1회로 줄여도 전부 초록이었다. 그래서 기본 상수 자체를 보는 검사 2건을 더 넣었다
(`len(JWKS_ATTEMPT_TIMEOUTS) >= 2`, 타임아웃이 회차마다 늘어나는가). mutation 을
돌리지 않았으면 이 구멍은 남았을 것이다.

**[같은 계열 — `audit_test_reality.py` 의 증거 없는 실패]** 같은 세션에 이 도구를
돌렸더니 55개 중 **연속 8개**가 이렇게 찍혔다.

```
  [34/55] test_image_queue_transition.py         측정 실패
  [35/55] test_intent_analyzer.py                측정 실패
  ...
```

이유가 **빈 문자열**이다. `run_one()` 이 `coverage json` 출력에서 `{` 를 못 찾으면
그냥 `return None` 이었고, 호출부는 `(r or {}).get("error", "")` 로 빈 문자열을 찍었다.
이 출력만으로는 "감사기가 고장났다"와 "검사가 깨졌다"를 구별할 수 없다 — 증거 없는
실패는 이 저장소가 반복해서 당한 함정 그 자체다(`run_python_tests.py` Sprint 203 주석,
로그에 안 남아 9일간 크롤 중단을 몰랐던 일).

이번 건의 **실제 원인은 동시 실행이었다**(같은 시각 전체 스위트와 파일 편집이 돌고
있었다 — 한 파일만 따로 돌리면 정상 측정된다). 즉 제품 결함이 아니었지만, **그것을
확인하는 데 별도 조사가 필요했다는 것 자체가 결함**이다.

`_why_no_json(cov, out)` 을 만들어 두 서브프로세스의 종료코드와 stderr 꼬리를 이유로
남긴다. 순수 함수라 프로세스 없이 검증할 수 있다. 그리고 이 도구에 **`--selftest` 가
아예 없었으므로** 새로 만들고 `test_audit_selftests.py` 의 `TOOLS` 표에 등록했다
(그 표의 "목록이 비어 있지 않다" 하한도 3 -> 4 로 올렸다 — 목록이 줄면 잡히게).

**[남은 것]** `audit_contrast.py` / `audit_viewport.py` 는 아직 `--selftest` 가 없다.
둘 다 프런트 렌더링 측정 도구라 selftest 를 만들려면 가짜 DOM/색상 입력이 필요하다 —
이번 세션 범위 밖으로 남긴다.

--------

#189

**`measure_endless_collecting.py` 가 "끝나지 않는 수집중" 2,145건의 이유를 통짜로
"기일 경과"라고 찍었다 — 실측하면 그중 기일 경과는 0건이다.** 진짜 원인은 migration
018 이 자기 헤더에 이미 적어 둔 UNIQUE 충돌이고, 018 이 약속한 자연 복구는 일어나지 않았다

발견 (2026-08-25, DB 관계 감사 중 `auction_item` 716건에 큐 행이 없는 것을 보고)

**[경위]** 읽기 전용으로 체인을 재다가 이것이 나왔다.

```
auction_item 1,876건 중 document_queue 행이 하나도 없는 것 : 716건 (38%)
그 716건의 document_status                              : COLLECTING 2,145 / FAILED 3
```

`measure_endless_collecting.py` 를 돌리니 같은 2,145건이 이렇게 찍혔다.

```
(b) 큐 행이 없다 ― 기일 경과로 애초에 넣지 않음      2145
```

그런데 그 라벨은 **측정이 아니라 코드에 박힌 가정**이었다.

```python
st = queue.get(...)
if st is None:
    bucket = "(b) 큐 행이 없다 ― 기일 경과로 애초에 넣지 않음"   # 왜인지 확인하지 않는다
```

**[실측 — 가정이 틀렸다]** 716건 전부를 수집 시점 기준으로 다시 쟀다.

```
auction_date <  crawl_date (수집 시점에 이미 기일 지남) :   0건
auction_date >= crawl_date (수집 시점에 기일이 남아 있었다): 716건   <- 전부
대조군(큐 행이 있는 물건 1,160건): 기일 경과 1 / 기일 남음 1,159
```

즉 **기일 때문에 빠진 것이 하나도 없다.** `enqueue_documents()` 의 사전 제외 조건
(`auction_date < today` -> `skipped_expired`)에 걸린 것이 아니다.

**[진짜 원인 — 이미 저장소에 적혀 있었다]** `storage/migrations/018_document_queue_item_no_unique.sql`
헤더가 그대로다(BUGS #48, Sprint 55):

```
-- 018 이전:  UNIQUE(court_code, case_no, doc_type)     <- item_no 가 없다
-- 그 결과 한 사건에 물건이 여러 개일 때
--   **두 번째 물건부터는 INSERT OR IGNORE 에 걸려 조용히 버려졌다.**
-- 실측 (2026-08-11, 적용 전):
--     자기 item_no 로 큐에 없는 물건     716 / 1,870  (38%)
```

**716 이라는 숫자가 오늘 값과 정확히 같다.** 그리고 item_no 분포가 그 서명을 그대로
보여 준다.

```
                item_no='1' 비율
auction_item        1,247 / 1,876  (66%)
document_queue      3,171 / 3,498  (91%)   <- 큐만 '1' 로 쏠려 있다
716건 중 410건은 **같은 사건의 다른 item_no 로는 큐 행이 있다**
```

**[018 이 약속한 복구는 일어나지 않았다]** 018 헤더는 이렇게 끝난다.

```
-- 빠져 있던 물건들은 다음 enqueue_documents() 실행 때 자연히 채워진다.
```

**채워지지 않았다.** 018 적용은 2026-08-11, 오늘은 2026-08-25, 그 사이 크롤이 돈 날은
**2026-08-12 하루뿐**이고 그날 들어간 큐 행은 18개다. `enqueue_documents()` 는 **그날
새로 긁은 rows 로만** 호출되는데, 716건은 그때 이미 기일이 지나 법원 목록에 없다.
게다가 `auction_date < today` 사전 제외에도 걸린다. 즉 **이 잔여는 크롤이 되살아나도
스스로 사라지지 않는다** — 018 의 "자연히 채워진다"는 이 716건에 대해서는 성립하지 않는다.
(앞으로 새로 들어오는 물건은 018 이후 제약이라 정상 적재된다 — 진행형 결함은 아니다.)

**[영향]** `document_status = COLLECTING` 2,145건이 **영구히** 그 상태로 남는다. 어떤
큐 행도 없으므로 `mark_queue_skipped_expired()` 같은 종결 경로를 아예 지나지 않는다.
지금은 716건 전부 기일이 지나 기본 검색에 안 보이지만, `include_closed=true` / 찜 /
최근 본 물건 / 문서 통계에는 "수집중"으로 섞인다.

라벨이 왜 중요한가 — 이 스크립트의 존재 이유가 "표시 정책을 정하는 데 필요한 숫자"를
주는 것이다. **"어차피 기일 지난 것"과 "스키마 결함으로 잃은 것"은 정반대의 결정을
부른다.** 전자는 그냥 숨기면 되고, 후자는 재적재를 검토해야 한다.

**[수정]** 하드코딩 라벨을 증거 기반 분류 `no_queue_reason()` 으로 바꿨다(순수 함수).

```
(b1) 수집 시점에 이미 기일 경과            증거: auction_date < crawl_date
(b2) 같은 사건의 다른 물건만 큐에 있다      증거: 같은 (법원,사건)에 다른 item_no 존재
                                          = 018 이전 UNIQUE 충돌의 서명
(b3) 같은 사건 전체가 큐에 없다 (이유 미상)  추측하지 않고 미상으로 남긴다
(b4) 자기 item_no 는 큐에 있는데 doc_type 만 없다
```

수정 후 실측:

```
before  (b) 기일 경과로 애초에 넣지 않음                     2145
after   (b2) 018 이전 UNIQUE 충돌                          1230   (물건 410개)
        (b3) 같은 사건 전체가 큐에 없다 (이유 미상)             915   (물건 305개)
        (b1) 수집 시점에 기일 경과                              0   <- 옛 라벨이 주장하던 전부
```

**[회귀 + mutation]** 이 스크립트에는 `--selftest` 가 없었다. 8건을 만들어 붙이고
`test_audit_selftests.py` 의 `TOOLS` 표에 등록했다(하한 4 -> 5). DB 도 네트워크도 쓰지
않는다. mutation 4/4 검출:

```
M1 기일 비교를 뒤집는다 (b1 과다 판정)        -> 잡았다
M2 날짜가 없어도 b1 로 몬다 ("모름" -> "지남") -> 잡았다
M3 018 충돌(b2)을 b3 로 뭉갠다               -> 잡았다
M4 b4 를 b3 로 뭉갠다                        -> 잡았다
```

**[해결하지 않음 — 승인 영역]** 잔여 자체를 없애려면 둘 중 하나가 필요하고 **둘 다
운영 DB 변경**이다.

1. 716건을 큐에 재적재 — 다만 전부 기일이 지나 법원 사이트에서 조회되지 않으므로
   (`enqueue_documents()` docstring 의 Step 13/14 실측) **수집은 실패한다.** 실익 없음.
2. `document_status` 를 "대상 아님"으로 종결 — `document_status` enum 에 그 값이 없다.
   새 상태를 만드는 것은 상태머신 + 화면 문구를 함께 정하는 **제품 결정**이고
   `test_document_status_sync.py` §6 이 현재 동작(COLLECTING 유지)을 고정하고 있다.
   Sprint 73 이 검토하고 보류한 그 결정 그대로다.

이 세션은 **숫자와 이유를 정확하게 만드는 것까지** 하고 멈춘다 — 그것이 이 스크립트가
원래 하기로 한 일이다.

**[같은 계열의 인접 결함 — 감사기의 사각]** `audit_asset_integrity.py` 의
`audit_queue_vs_status()` 는 `document_queue` 에서 **INNER JOIN** 으로 시작한다.

```sql
FROM document_queue dq
JOIN ... JOIN document_status ds ON ...
```

그래서 **큐 행이 아예 없는** document_status 2,145건은 이 검사에 보이지 않는다 —
감사기는 "[5] 어긋남 없음" 을 찍는다. 틀린 말은 아니지만(그 검사가 보는 범위 안에서는
사실이다) "큐와 화면이 정합하다"로 읽히기 쉽다. 이 갈래는
`measure_endless_collecting.py` 가 담당하는 것으로 역할이 나뉘어 있으므로 감사기를
고치지는 않고, 여기 적어 둔다 — 다음 세션이 "[5] 어긋남 없음"만 보고
큐/상태가 전부 정합하다고 결론 내리지 않도록.

--------

#190

**Sprint 253 이 "복합 인덱스는 필요 없다"고 기각한 근거가 `ANALYZE` 를 돌린 상태의
측정인데, 운영 DB 에는 `ANALYZE` 가 한 번도 돈 적이 없다** — 그래서 운영은 기각 근거가
말하는 것보다 7.6배 느린 계획으로 돈다

발견 (2026-08-25, 쿼리 계획 감사)

**[경위]** `docs/BETA_RELEASE_CHECKLIST.md` 의 "측정으로 기각/보류" 표에 이 줄이 있다.

```
| 큐 claim 이 매번 2,753행을 정렬한다 | **아니다.** `ANALYZE` 후 `idx_queue_priority` 로
  정렬 없이 0.052ms. 6.5배(22,769행)에서만 TEMP B-TREE 로 3.75ms |
| 복합 인덱스가 그것을 고친다 | **아니다.** 추가해도 3.76ms -> 마이그레이션 근거 소멸 |
```

운영 DB 에 같은 쿼리(`claim_next_queue_item()` 이 실제로 쓰는 것 — `status IN
('pending','refresh')` + `last_attempt_at` 조건 포함)를 걸어 계획을 떠 봤다.

**[실측 2026-08-25]** (읽기 전용, 스크래치 사본에서만 `ANALYZE` 실행)

```
운영 auction.db 에 sqlite_stat1 이 있는가 :  없다

[운영 DB 현재 상태 = ANALYZE 없음]
    SEARCH document_queue USING INDEX idx_queue_status (status=?)
    USE TEMP B-TREE FOR ORDER BY
    100회 평균 0.313 ms

[같은 DB 사본 + ANALYZE]
    SCAN document_queue USING INDEX idx_queue_priority     <- 정렬 없음
    100회 평균 0.041 ms
```

0.041ms 는 체크리스트가 적은 0.052ms 와 사실상 같다. **즉 그 측정 자체는 옳다.
전제가 운영에 없을 뿐이다.** 지금 운영은 매 claim 마다 2,753행짜리 TEMP B-TREE 를
만든다 — 기각 근거가 "없다"고 말한 바로 그 동작이다.

**[왜 아무도 몰랐나]** `ANALYZE` 를 부르는 곳이 저장소 어디에도 없다(2026-08-25 전수
확인 — `storage/`, `crawler/`, `api/`, `config/`, 루트 `*.py`, `*.bat`, `*.ps1`,
마이그레이션 `*.sql` 전부). 부트스트랩 3단계에도 없다. 즉 이 저장소에서 통계가 있는
DB 는 **누군가 손으로 `ANALYZE` 를 친 세션의 사본뿐**이고, Sprint 253 이 바로 그런
사본에서 쟀다. 측정자는 그것을 숨기지 않았다 — "`ANALYZE` 후"라고 명시했다. 다만
**운영에 그 전제가 없다는 사실을 확인하지 않았다.**

같은 계열이 하나 더 있다 — `favorites` 도 `idx_favorites_user_id` 로 좁힌 뒤
`ORDER BY created_at DESC` 에서 TEMP B-TREE 를 만든다. 지금은 0행이라 0.0ms 지만
사용자가 늘면 같은 모양이 된다.

**[영향]** 지금 당장은 작다 — 0.313ms vs 0.041ms 다. 위험한 것은 방향이다.

* 체크리스트가 이 항목을 **"기각"으로 닫아 두었다.** 다음 세션이 큐 지연을 조사할 때
  이 표를 보고 "이미 재 봤고 문제 없다"로 넘어간다.
* 큐는 **계속 커진다.** DocWorker 가 등록되지 않아 pending 이 빠지지 않는 상태이고
  (BUGS #184 계열, 2026-07-12 이후 처리 0), 체크리스트 자신이 6.5배(22,769행)에서
  TEMP B-TREE 가 3.75ms 라고 적어 두었다. 그 지점은 통계가 없으면 더 일찍 온다.

**[해결하지 않음 — 승인 영역]** 고치는 방법은 셋 다 이 세션의 SKIP 목록에 걸린다.

1. 운영 DB 에 `ANALYZE` 1회 — 무손실이고 `sqlite_stat1` 만 추가하지만 **운영 DB 변경**이다.
2. 부트스트랩/마이그레이션 러너에 `ANALYZE` 추가 — 다음 실행 때 운영 DB 를 바꾸게 된다.
3. 복합 인덱스 추가 — **마이그레이션 신설**이고, 애초에 이 기각 근거가 부정한 대상이다
   (통계가 있으면 실제로 불필요하다 — 위 실측이 그것을 재확인한다).

세 중 **1번이 가장 작고 되돌리기 쉽다**(`ANALYZE` 는 언제든 다시 돌리면 되고,
`DROP TABLE sqlite_stat1` 로 원복된다). 다음 세션이 승인받아 처리할 것.

**[문서]** 체크리스트의 해당 표에 이 전제를 함께 적었다 — 표만 읽고 "문제 없음"으로
닫히지 않게 하는 것이 이 항목의 요점이다.

--------

#191

**JWKS 가 응답하지 않으면 요청마다 바깥 호출이 하나씩 나가고, 그 호출이 `_jwks_lock` 을
잡은 채 일어나 API 전체가 직렬화된다** — 외부 한 곳의 지연이 서비스 정지로 번진다

발견 (2026-08-25, SSRF/외부호출 감사 중 `api/auth.py:112` 의 단발 `timeout=5` 를 보고)

**[경위]** 같은 세션에 `audit_auth_health.py` 가 JWKS 타임아웃 한 번을 "인증이 막혀 있다"로
오판한 것을 고쳤다(BUGS #188). 그 김에 **제품 쪽 JWKS 조회**도 같은 모양인지 봤다.
제품 쪽은 방어가 훨씬 낫다 — 10분 TTL 캐시가 있고, 실패해도 기존 캐시로 계속 검증하고
(`if keys:` 로 빈 응답이 캐시를 날리지 않는다), 실패 전에 시각을 갱신해 재시도 폭주를 막는다.

**그런데 캐시가 비어 있는 동안에는 그 방어가 통째로 꺼진다.**

```python
if (now - _jwks_fetched_at) >= _JWKS_MIN_REFETCH_SECONDS or not _jwks_keys:
    #                                                     ^^^^^^^^^^^^^^^^
    try:
        _fetch_jwks_locked()        # timeout=5, 재시도 없음 — `with _jwks_lock:` 안이다
```

`or not _jwks_keys` 는 **캐시가 빌 때 하한을 무효화한다.** 하필 그 상수의 주석이
"알 수 없는 kid 가 쏟아져도 외부 호출이 폭주하지 않게 하는 하한"이다 — 예외 조항이
정확히 그 취지가 필요한 순간에 취지를 껐다.

**[재현]** `urlopen` 을 응답하지 않는 가짜로 갈아끼우고(네트워크 안 탄다) 스레드 8개로
콜드 스타트 상태의 `_get_jwk()` 를 동시에 호출했다. 타임아웃은 재현용으로 1초로 축소했다.

```
수정 전   바깥 JWKS 호출 8회 / 전체 8.00초 / 마지막 요청 8.00초
수정 후   바깥 JWKS 호출 1회 / 전체 1.00초 / 마지막 요청 1.00초
```

호출이 요청 수만큼 나가고, `_jwks_lock` 때문에 **완전히 직렬화된다.**
실제 코드의 `timeout=5` 로 환산하면 **동시 8요청에 마지막 요청이 40초**다.

**[영향 — 우선순위 2(서비스 장애) + 3(인증)]** 캐시가 비는 상황은 드물지 않다.

* 서버 재기동 직후(배포·크래시 복구) = 항상 콜드 스타트다.
* JWKS 장애가 10분 TTL 보다 길면 캐시가 무의미해지고 여기로 떨어진다.

그 순간 **JWKS 가 5초 느려지는 것이 인증 API 전체의 응답시간을 요청 수 × 5초로 만든다.**
게다가 결과는 어차피 401 이다(`_jwks_keys.get(kid)` 가 None) — **5초씩 매달린 끝에 같은
401 을 준다.** 얻는 것 없이 서버만 묶인다. 이 세션에 실제로 JWKS 타임아웃이 한 번
관측됐으므로(BUGS #188) 가상의 상황이 아니다.

**[수정 — 1줄]** 하한을 예외 없이 적용하고, "한 번도 조회한 적 없음"만 따로 본다.

```python
never_fetched = _jwks_fetched_at == 0.0
if never_fetched or (now - _jwks_fetched_at) >= _JWKS_MIN_REFETCH_SECONDS:
```

`_fetch_jwks_locked()` 가 **시도 전에** `_jwks_fetched_at` 을 갱신하므로 시간 조건만으로
실패 후 재시도까지 올바르게 눌린다. 남는 예외는 "아직 한 번도 안 해 봤다"뿐이다.

**0.0 을 시간 비교로 대신하지 않은 이유**: `time.monotonic()` 의 기준점은 플랫폼마다
다르고 부팅 직후에는 작을 수 있다. 시간 비교만 두면 그런 환경에서 **첫 조회를 통째로
건너뛰어** 인증이 30초간 죽는다 — 고치려던 것보다 나쁜 회귀다. 그래서 명시적 플래그로 둔다.

**바뀌는 것과 안 바뀌는 것**

```
캐시 적중(평시)          바깥 호출 0회, 즉시 반환      — 전혀 안 바뀜
캐시 있음 + 모르는 kid    30초 하한                    — 전혀 안 바뀜
콜드 스타트 + 정상 네트워크  첫 조회 그대로 수행           — 전혀 안 바뀜
JWKS 장애 중             401 이 **빠르게** 난다        — 결과 동일, 서버가 살아 있다
```

**[남는 것 — 이번에 손대지 않았다]** 눌린 뒤에도 그 1회 조회는 여전히 `_jwks_lock` 을
잡은 채 최대 5초 걸린다. 즉 30초에 한 번은 동시 요청이 최대 5초 함께 밀린다.
완전히 없애려면 네트워크 호출을 락 **밖으로** 빼고 이중 검사(double-checked) 구조로
바꿔야 하는데, 그것은 인증 경로의 동시성 구조 변경이라 이번 1줄 수정과 위험도가
다르다. **요청당 5초 -> 30초당 5초**로 줄인 것이 이번 범위다. 더 줄이려면 별도 Sprint 로.

**[회귀 + mutation]** `test_auth_jwks_robustness.py` 에 8번/8-b 를 신설했다.
네트워크를 타지 않는다(`urlopen` 교체). 행위 검사(스레드 8개)와 구조 검사
(`or not _jwks_keys` 가 되돌아오면 실패)를 함께 둔다 — 타이밍 검사 하나에만 기대면
느린 CI 에서 흔들린다.

mutation 4/4 검출:

```
M1 `or not _jwks_keys` 를 되돌린다 (원래 버그)          -> 잡았다
M2 하한을 0 으로 만든다 (사실상 무제한 재조회)            -> 잡았다
M3 콜드 스타트 예외를 없앤다 (부팅 직후 첫 조회 누락)      -> 잡았다
M4 실패 전 시각 갱신을 없앤다 (재시도 폭주 복귀)          -> 잡았다
```

인증 경로 회귀 5종 재실행 전부 exit 0:
`test_auth_jwt.py` / `test_auth_jwks_robustness.py` / `test_api_regression.py` /
`test_item_detail_auth.py` / `test_beta_journey.py`.

**[같이 확인한 것 — 결함 아님]**

* **SSRF 없음**: 이 저장소에서 요청 입력으로 바깥 URL 을 만드는 곳이 없다.
  `api/auth.py` 의 유일한 외부 호출도 URL 이 `SUPABASE_URL` 환경변수에서만 온다.
* **SQL injection 없음**: `api/v1/admin.py` 의 `"... WHERE " + where` 형태 4곳은
  `where` 가 전부 **고정 리터럴 조각**이고 값은 전부 `?` 다. `_validate_filter()` 가
  enum 까지 화이트리스트로 막는다. `storage/database.py` 의 `"UPDATE auction SET " + col`
  도 `col` 이 `LEGACY_HAS_COLUMN` 딕셔너리 조회 결과이며, 그 앞에서 `doc_type` 이
  `QUEUE_TO_DOC_STATUS_TYPE` 에 없으면 `KeyError` 로 죽는다.
* **IDOR 없음**: id 를 받는 라우트 19개를 전수 확인했다. admin 8개는 전부
  `require_admin` 또는 `require_super_admin`(과금에 영향 주는 3개는 SUPER),
  사용자 자원 6개는 전부 `AND user_id = ?` 로 좁힌다. 공개 5개는 공개 경매 데이터다.
* **rate limit 은 여전히 없다** — `api_server.py` 가 `127.0.0.1` 바인딩이라 지금은
  노출면이 없지만, 외부에 열면 그 순간 필요해진다. 배포 형태가 정해질 때 함께 정할 일이라
  이번에는 기록만 한다.

--------

#192

**회귀 스위트가 운영 로그 파일에 합성 로그를 써 왔다** — `logs/doc_collect.log` 의 40%,
`logs/scraper.log` 의 최근 이틀치가 전부 QA 산출물이다. 마지막 실제 크롤은 2026-08-12 인데
로그만 읽으면 "오늘 크롤이 돌았고 전 법원이 실패했다"로 보인다

발견 (2026-08-25, BUGS #186 이 닫은 DB 축의 **파일 축**을 같은 방법으로 재다가)

**[경위]** `audit_test_reality.py` 를 돌린 직후 `ls -la logs/` 를 보니
`logs/doc_collect.log` 의 mtime 이 **방금**이었다. 크롤은 13일째 멈춰 있는데 문서 수집
로그가 갱신될 이유가 없다. 파일을 열어 보니 가짜 법원 이름이 들어 있었다.

```
2026-08-25 09:52:00 [INFO] [2026타경12-1] spec 저장 완료:
    C:\...\Temp\qa_specnotab_docs_4fkskgz7\QA법원\2026타경12\1\spec.pdf
2026-08-25 09:51:34 [ERROR] ===== [QA2] 오류: QA 주입 실패 =====
2026-08-25 09:51:34 [ERROR] ===== 사건 수집 실패: 전 법원(2곳) 수집 실패 =====
```

**[실측 — 얼마나 섞였나]** (2026-08-25)

```
logs/doc_collect.log    총 4,136줄 중 'QA법원' 이 들어간 줄  1,651줄 (40%)
                        가장 오래된 QA 줄 2026-08-18, 가장 최근 2026-08-25
logs/scraper.log        총 36,420줄. 2026-08-24 자 1,851줄 / 2026-08-25 자 495줄
                        (마지막 줄까지 전부 'QA1'/'QA2' 합성 크롤이다)
auction_item MAX(crawl_date)   2026-08-12      <- 실제 크롤은 여기서 멈췄다
```

**[원인 — 한 줄이다]** 두 진입점이 **모듈 최상위**에서 파일 핸들러를 붙였다.

```python
# collect_documents.py / mvp_scraper.py — 수정 전
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(_HERE, "logs", "doc_collect.log"), ...),
        logging.StreamHandler(),
    ]
)
```

`basicConfig` 는 **루트 로거**를 설정한다. 그래서 이 모듈을 import 하는 순간, 그
프로세스 안의 **모든** 로그(`crawler/doc_crawler.py` 가 찍는 "spec 저장 완료"까지)가
운영 로그 파일로 흘러간다. 그리고 이 두 모듈을 import 하는 것은 **제품 코드가 아니라
테스트뿐**이다(2026-08-25 전수 확인: 제품 모듈의 import 0건, `.bat` 3개는 전부
`python <파일>` 로 **실행**한다).

**[왜 오랫동안 몰랐나]** 로그는 append 라 아무것도 깨지지 않는다. 테스트는 통과하고,
행수는 늘기만 하며, 아무도 파일을 열어 보지 않는다. BUGS #186 이 DB 축에서 만난 것과
같은 모양이다 — **정상으로 보이는 것이 문제였다.**

**[영향 — 왜 사소하지 않은가]** 이 저장소는 2026-08-03~08-11 **9일간 크롤이 멈춘 것을
몰랐던** 이력이 있고, 그때의 교훈이 "로그에 남지 않으면 아무도 모른다"였다. 지금은
반대 방향의 같은 함정이다 — **로그에 거짓이 남아 있다.**

* `logs/scraper.log` 를 열면 마지막 줄이 오늘 날짜이고 `[ERROR] 전 법원(2곳) 수집 실패`
  다. 이것만 보고 "크롤은 도는데 법원 접속이 막혔다"로 진단하면 **엉뚱한 곳을 판다.**
  실제 원인은 예약 작업이 0개라 크롤이 **아예 실행되지 않는 것**이다.
* `check_pipeline2.py` 는 `logs/scraper.log` / `logs/doc_collect.log` 를 직접 읽고,
  `test_max_items_contract.py` 는 `logs/scraper.log` 를 실측 근거로 인용한다.
* 여러 Sprint 문서가 "운영 무변경"을 기준선에 적어 왔다. DB 는 #186 이 참으로 만들었지만
  **파일은 여전히 거짓이었다.**

**[수정]** 파일 로그를 **import 시점 → `__main__` 시점**으로 옮겼다. 두 파일에
`attach_file_log()` 를 두고 `if __name__ == "__main__":` 첫 줄에서 부른다.

```python
def attach_file_log():
    """운영 파일 로그를 루트 로거에 붙인다. `__main__` 에서만 부른다."""
    root = logging.getLogger()
    target = os.path.abspath(SCRAPER_LOG_PATH)
    for h in root.handlers:                       # 두 번 불러도 겹치지 않는다
        if isinstance(h, logging.FileHandler) and os.path.abspath(h.baseFilename) == target:
            return h
    ...
```

**운영 경로는 전혀 바뀌지 않는다** — `run_daily.bat` 는 `"%PY%" mvp_scraper.py` 로 부르므로
`__main__` 분기를 그대로 지난다. 그리고 이 수정으로 **네 진입점의 import 시점 동작이
같아진다** — `doc_worker.py` / `refresh_priority.py` 는 애초에 StreamHandler 하나뿐이었다.
즉 고친 것이 아니라 **빠져 있던 둘을 나머지 둘에 맞춘 것**이다.

**[재발 방지 — #186 과 같은 방식, 같은 이유]** 허용목록이 아니라 **행동**을 본다.
`run_python_tests.py` 의 감시 대상을 운영 DB 하나에서 **운영 산출물 다섯**으로 넓혔다.

```
auction.db  /  logs/daily_run.log  /  logs/doc_run.log
logs/scraper.log  /  logs/doc_collect.log  /  logs/migrate_execute.log
```

파일 하나를 돌릴 때마다 여섯 개의 지문을 재고, 달라지면 **그 파일이 무엇을 바꿨는지까지
지목**하고 통과 여부와 무관하게 종료코드 1 을 준다. 목록을 `logs/` 전체로 두지 않은
이유는 그 폴더에 세션 산출물(`s2xx_*.log`)이 섞여 있어 감시가 소음만 내기 때문이다 —
**이 저장소가 증거로 쓰는 파일**만 골랐다.

**[회귀 + mutation]** `test_schema_hygiene.py` 에
`test_entrypoints_do_not_attach_file_logs_on_import()` 를 신설했다(9단언).
문자열이 아니라 **행위**를 본다 — 자식 프로세스에서 진짜로 import 해 루트 로거의
FileHandler 목록을 물어본다. 자식 프로세스로 돌리는 이유는 (1) 이 검사 자신이 로그를
오염하지 않기 위해, (2) 이미 import 된 모듈 때문에 `basicConfig` 가 no-op 이 되어
**검사가 저절로 초록이 되는 것**을 피하기 위해서다.

붙이지 "않는" 것만 보면 **아예 파일 로그를 지워버린** 회귀를 놓치므로, `__main__` 이
`attach_file_log()` 를 실제로 부르는지도 AST 로 함께 본다.

mutation 3/3 검출:

```
M1 import 시점 FileHandler 를 되돌린다 (원래 버그 그대로)  -> 잡았다
M2 __main__ 의 attach_file_log() 호출을 지운다              -> 잡았다
M3 attach_file_log() 자체를 없앤다                          -> 잡았다
대조군 (수정본 그대로)                                      -> exit 0
```

감시기 쪽도 따로 재현했다 — M1 을 주입한 채 `run_python_tests.py -k crawl_orchestration`
을 돌리니 **통과 1 / 실패 0 인데 종료코드 1** 이고 `logs/scraper.log` 를 지목했다.
수정본으로 되돌리니 종료코드 0.

**[검증]**

```
수정 전  test_court_crawl_recovery / test_crawl_orchestration -> logs/scraper.log 변경
         test_doc_storage_atomicity                          -> logs/doc_collect.log 변경
수정 후  같은 네 파일 개별 실행                              -> 전부 무변경
         전체 스위트 1회                                     -> 운영 산출물 5개 **바이트 동일**
                                                                auction.db 2991c5be...
__main__ 경로 보존  임시 경로로 attach_file_log() 를 불러 실제로 기록되는 것 확인
                    (크롤러는 돌리지 않았다). 두 번 불러도 핸들러 1개.
```

**[기준선]** 통과 53 / 실패 1 / 건너뜀 3 / 판정없음 1, 단언 **8,138**건
(수정 전 8,129 -> 신규 검사 9단언). 남은 실패 1건은 이 수정과 무관한 P0-A(기일 미도래
물건 0건 — 크롤은 승인 영역)다.

**[같이 확인한 것]**

* `test_filter.py`(판정없음 1)와 `test_db.py`/`test_docs.py`/`test_docs2.py`(건너뜀 3)는
  **전부 의도된 것**이고 파일 자신의 docstring 이 이유를 적고 있다. 정직한 분류다.
* `logs/scraper.log` 에 남은 `CSV 백업 저장: ...\auction_20260825.csv` — 테스트가 저장소
  **루트에 CSV 를 쓴다.** 끝에 지우므로 지금 파일은 없지만, 중간에 죽으면 남는다(#186 의
  "지우는 코드에 도달하지 못한다"와 같은 논리). `*.csv` 가 `.gitignore` 에 있어 커밋되지는
  않는다. 감시 대상에 넣으려면 파일명이 날짜마다 달라 지문 방식이 맞지 않아 이번에는
  기록만 한다.
* `patch_migrate2.py` — 저장소 루트의 **미추적** 일회용 패치 스크립트다(`migrate_execute.py`
  에 로그 핸들러를 넣으려던 것으로 보이나 실제로 적용돼 있지 않다). 아무 데서도 참조되지
  않는다. BUGS #187 의 `e hardening"` 과 같은 계열의 잔여물이지만 **미추적이라 저장소를
  더럽히지는 않는다.** 삭제는 승인 영역이라 남긴다.

--------

#193

**프런트 감사 도구 둘이 "재지 못했다"를 말할 줄 몰랐다** — `audit_contrast.py` 는
드라이버 실패를 40줄짜리 트레이스백으로 토했고, 텍스트 노드를 **0개 보고도**
"기준 미달 0 / 종료코드 0"(=정상)을 돌려줄 수 있었다. 그리고 결함 43곳을 다 찾아
놓고 **보고하다가 죽었다**

발견 (2026-08-25, BUGS #188 이 "남은 것"으로 적어 둔 항목을 실제로 돌려 보다가)

**[경위]** #188 은 `audit_auth_health.py` 의 "모른다를 고장났다로 읽는" 결함을 고치면서
이렇게 남겼다: *"`audit_contrast.py` / `audit_viewport.py` 는 아직 `--selftest` 가 없다.
이번 세션 범위 밖으로 남긴다."* 그 둘을 실제로 돌려 보니, selftest 가 없다는 것보다
**본체가 먼저 문제였다.**

```
$ python audit_contrast.py
...
requests.exceptions.ConnectionError: Could not reach host. Are you offline?
(트레이스백 40줄. 판정문 0줄.)
```

**[결함 1 — "오프라인이 아니다"]** 메시지를 믿지 않고 같은 주소를 직접 쟀다.

```
stdlib urllib  -> HTTP 200, 0.05초, 200 bytes      <- 네트워크는 멀쩡하다
requests       -> SSLCertVerificationError
                  "unable to get local issuer certificate"   (3회 전부, 0.18초)
```

즉 `requests` 의 CA 번들이 이 PC 의 TLS 경로를 검증하지 못하는 것이고,
`webdriver_manager` 가 그것을 삼켜 **"Are you offline?"** 으로 바꿔 던졌다.
같은 순간 Selenium 4.47 내장 해석기(Selenium Manager)는 **9.6초 만에 크롬
151.0.7922.170 을 띄웠다.** 캐시(`~/.wdm/.../151.0.7922.138`)가 브라우저
(`...170`)와 어긋나 있어 webdriver_manager 는 매번 바깥을 봐야 했던 것이다.

`build_driver()` 는 `webdriver_manager` **하나뿐**이었다. 즉 이 도구들은
**바깥 네트워크가 되어야만 도는 구조**였고, 그 사실이 어디에도 적혀 있지 않았다.

**[수정 1]** 해석 순서를 둘로 두고, 전부 실패하면 `DriverUnavailable` 로 올린다.

```
1. Selenium Manager   (내장, 캐시가 맞으면 바깥을 안 본다)   <- 먼저
2. webdriver_manager  (예전 경로)                            <- 폴백
둘 다 실패 -> DriverUnavailable("A -> ...; B -> ...")        <- 두 사유를 **함께**
```

호출부는 그것을 잡아 **시도한 방법과 각각의 사유를 줄마다 찍고 종료코드 2**(측정 불가)를
준다. 사유를 하나만 남기면 "네트워크가 안 된다"와 "크롬이 없다"를 구별할 수 없다.

**[결함 2 — 아무것도 못 재고 "정상"이라고 말한다]** `audit_contrast.py` 의 끝은 이랬다.

```python
print("  합계: 텍스트 노드 %d개 / 기준 미달 %d개" % (total_seen, len(all_bad)))
if not all_bad:
    return 0
```

`all_bad` 가 비는 경우는 **둘**인데 코드는 하나로 봤다.

```
(a) 진짜로 기준 미달이 없다              -> 0 이 맞다
(b) 화면이 안 그려져 **잰 글자가 없다**   -> 0 은 거짓이다
```

(b) 는 서버가 죽었거나 라우트가 바뀌었거나 렌더가 20초 안에 안 끝났을 때 나온다.
그러면 이 도구는 `합계: 텍스트 노드 0개 / 기준 미달 0개` 를 찍고 **종료코드 0** 을
돌려준다 — 아무것도 재지 않고 "정상"이라고 말하는 것이다. 형제 도구
`audit_viewport.py` 는 같은 함정을 `nodes < 15 -> UNUSABLE` 로 이미 막고 있었다.
**이 도구만 빠져 있었다.**

서버 확인도 빠져 있었다(`audit_viewport.py` 는 첫 줄에서 한다).

**[수정 2]** 순수 함수 `contrast_verdict(per_screen, all_bad)` 로 종료코드를 셋으로 가른다.

```
0  기준 미달 없음      전 화면을 실제로 쟀고 미달이 없다
1  결함 있음
2  재지 못했다         텍스트 노드가 0개인 화면이 하나라도 있다 / 잰 화면이 없다
```

**하한을 "0개"로만 둔 이유**: 화면별 텍스트 노드 수의 정상 범위를 아직 재지 않았다
(dev 서버가 떠 있어야 잰다). 재지 않은 값을 상수로 박으면 그것이 다음 오판의 근거가
된다. 지금은 부정할 수 없는 것만 판정한다 — **그려진 화면에 텍스트 노드가 0개일 수는
없다.** 실측 기준선이 생기면 그때 올린다.

**[결함 3 — 다 찾아 놓고 보고하다 죽었다]** 위 둘을 고친 뒤 dev 서버를 띄우고 처음으로
끝까지 돌렸더니, 기준 미달 **43곳을 전부 찾아 놓고** 목록을 찍다가 죽었다.

```
UnicodeEncodeError: 'cp949' codec can't encode character '—' in position 33
```

화면에서 긁어 온 문구에 엠대시가 있었다. 즉 **측정은 성공했는데 보고가 실패**했고,
종료코드는 1(결함 있음)이 아니라 트레이스백이 됐다. 이 저장소의
`test_console_encoding.py` 는 **소스에 박힌 문자열**을 검사하는데, 여기서 터진 것은
소스가 아니라 **측정 대상 데이터**다 — 화면 문구에는 어떤 글자든 올 수 있으므로
검사로 막을 수 없고 찍는 쪽에서 처리해야 한다.

**[수정 3]** `console_safe(text, enc=None)` 로 찍는 문자열만 좁혀서 처리한다.
`sys.stdout` 을 통째로 재설정하지 않는다 — 이 도구는 다른 도구가 import 하기도 해서
(`audit_contrast` -> `audit_viewport`) 전역 스트림을 바꾸면 호출부까지 바뀐다.

**[실제 측정 — 이제 끝까지 돈다]** dev 서버(운영 DB 가 아니라 **임시 사본**을
`storage.database.DB_PATH` 로 지정해 띄운 API)에 대고 2026-08-25 실측:

```
audit_viewport.py    정상 18 / 결함 0 / 로그인필요 18 / 측정불가 0     exit 0
                     (320/360/390/430/900/1400px x 전 화면)
audit_contrast.py    텍스트 노드 77개 / WCAG AA 기준 미달 43곳         exit 1
                     /       35개 중 20  /search 35개 중 19  /login 7개 중 4
```

**[명암비 43곳 — 8조합, 전부 한 단계 진한 색이면 통과한다]** 대체 색이 실제로
통과하는지도 브라우저에 칠해서 쟀다(Tailwind v4 계산값은 oklch 라 손으로 예측할 수 없다).

```
조합                                     지금      한 단계 진하게          곳수
text-gray-400 on white   (12/14px)      2.60:1   gray-500  4.84:1  OK     19
text-gray-400 on gray-50 (14px)         2.49:1   gray-500  4.63:1  OK      3
text-blue-500 on white   (12px)         3.76:1   blue-600  5.25:1  OK      8
white on bg-blue-500     (12/14/16px)   3.76:1   bg-blue-600 5.25:1 OK    11
text-gray-500 on gray-100(14px)         4.39:1   gray-600  6.87:1  OK      2
```

`white on bg-blue-500` 11곳에는 **`/login` 의 로그인 버튼과 `/search` 의 검색 버튼**
— 이 제품의 주 CTA — 이 들어 있다.

**주의**: `bg-blue-700` 은 rgb(0,0,0) 으로 읽혔다. 그 클래스가 이 빌드에 **생성되지
않아**(어디서도 쓰지 않는다) 배경이 투명이었던 것이지 검정이 아니다. 그래서 그 값은
쓰지 않았다 — 도구가 아니라 측정 조건이 만든 값이다.

**[색은 바꾸지 않았다 — 이 저장소가 이미 정한 것]** Sprint 247 이 같은 자리에서
*"색상은 제품/디자인 판단이라 제안만 남겼다"* 고 적었고 그 판단은 지금도 유효하다.
특히 `text-gray-400` 중 일부(아코디언 ▼, "면적 조건"/"특수조건" 제목)는
`SearchAccordionSection` 의 `muted` 가 **일부러** 흐리게 만든 것이다 —
"백엔드 미연동 섹션임을 제목 색상만으로 표시한다"가 그 컴포넌트 주석에 적혀 있다.
그것을 일괄로 진하게 만들면 **의도한 신호를 지우는 것**이 된다. 그래서 이 세션은
**대체 색이 실제로 AA 를 넘는다는 것까지 재 두고** 결정은 남긴다. 위 표의 다섯 줄이
그대로 지시서다.

**[회귀 + mutation]** 두 도구에 `--selftest` 를 신설하고(#188 의 "남은 것" 해소)
`test_audit_selftests.py` 의 `TOOLS` 에 등록했다(하한 5 -> 7). 브라우저도 서버도
네트워크도 쓰지 않는다 — 판정 로직과 드라이버 해석 순서만 본다(가짜 factory 주입).

```
audit_viewport.py  --selftest   20단언   verdict() 4종 + build_driver 순서/실패
audit_contrast.py  --selftest   13단언   contrast_verdict 3종 + console_safe + 드라이버
```

mutation 5/5 검출:

```
M1 빈 화면을 정상으로 되돌린다 (audit_contrast 원래 버그)  -> 잡았다 (FAIL 5줄)
M2 console_safe 를 무력화한다                             -> 잡았다 (FAIL 2줄)
M3 DriverUnavailable 대신 생예외를 던진다                  -> 잡았다 (FAIL 3줄)
M4 nodes<15 검사를 없앤다 (audit_viewport 빈 화면 통과)     -> 잡았다 (FAIL 2줄)
M5 폴백을 없앤다 (첫 방법만 시도)                          -> 잡았다 (FAIL 4줄)
대조군                                                     -> 둘 다 exit 0
```

M5 는 **처음에 트레이스백으로 죽었다** — 종료코드는 1 이라 게이트는 붉어졌지만
`[FAIL]` 줄이 0 이라 무엇이 깨졌는지 알 수 없었다. 그것 자체가 이 저장소가 반복해서
당한 "증거 없는 실패"라, selftest 안에서 예외를 **값으로** 바꾸도록 고쳤다
(`try_build()`). 지금은 어느 단언이 왜 깨졌는지 네 줄로 나온다.

**[검증]**

```
python audit_viewport.py --selftest      exit 0   (20단언)
python audit_contrast.py --selftest      exit 0   (13단언, cp949/utf-8 양쪽에서)
python test_audit_selftests.py           exit 0   (감사 도구 7개 전부)
서버 없이 python audit_contrast.py       exit 2   트레이스백 대신 두 줄 안내
서버 띄우고 audit_viewport.py            exit 0   정상 18 / 결함 0 / 측정불가 0
서버 띄우고 audit_contrast.py            exit 1   43곳 목록이 **끝까지** 출력됨
npm run test:frontend                    191건 / 187 pass / 1 fail / 3 skip
                                         남은 실패 1건 = P0-A (기일 미도래 물건 0건)
운영 auction.db + 운영 로그 5개           **바이트 무변경** (dev/API 서버를 띄운 동안에도)
```

**[같이 확인한 것 — 결함 아님]**

* `audit_viewport.py` 는 원래도 `build_driver` 실패를 잡아 종료코드 2 를 주고 있었다.
  트레이스백이 난 것은 `audit_contrast.py` 쪽뿐이다. 다만 사유를 **한 줄**로만 찍어
  어느 방법이 왜 실패했는지 알 수 없었으므로 그쪽도 함께 고쳤다.
* 로그인 필요 화면 18칸은 여전히 **측정하지 못했다**(헤드리스에 세션이 없다).
  이 도구는 그것을 통과로 세지 않는다 — `--cookie` 로 재는 것은 Sprint 242 이래
  다섯 번 이월된 항목이고, 실제 로그인 세션 쿠키가 필요해 이번에도 남는다.

--------

#194

**`audit_asset_integrity.py` 의 [9] 가 읽기 타임아웃 한 번에 트레이스백으로 죽었다** —
앞서 찍은 [1]~[8] 까지 판정 없이 버려진다. 그리고 그 김에 **자산 URL 601개를 이 저장소에서
처음으로 전수 확인했다 — 열리지 않는 것은 0개다**

발견 (2026-08-25, 체크리스트가 "자산 어긋남 0건"이라고 적어 둔 것을 실제로 다시 돌려 보다가)

**[경위]** `docs/BETA_RELEASE_CHECKLIST.md` 의 세션 검증 표에 이 줄이 있었다.

```
python audit_asset_integrity.py  자산 어긋남 0건 (고아 큐 행 18건은 보고)
```

돌려 보니 **종료코드 1, 어긋남 27건**이었다. 그리고 API 서버를 띄운 뒤 다시 돌리니
아예 죽었다.

```
[9] API 가 광고한 자산 URL 이 실제로 열리는가 (http://127.0.0.1:8000)
Traceback (most recent call last):
  ...
  File "audit_asset_integrity.py", line 818, in get
    return r.status, r.headers.get("content-type", ""), r.read()
TimeoutError: timed out
```

**[결함 — `HTTPError` 만 잡았다]**

```python
def get(path):
    try:
        with urllib.request.urlopen(api_base + path, timeout=15) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""          # <- 서버가 대답한 경우만 처리한다
```

`urlopen` 자체는 성공하고 **`r.read()` 도중에** 타임아웃/연결 리셋이 나면 그대로 위로
샌다. 그러면 감사기 전체가 죽고, 이미 화면에 찍힌 [1]~[8] 도 **판정 없이** 끝난다.
이 파일은 서버 부재는 이미 "확인하지 못함"으로 정직하게 다루고 있었다 — 그 구분이
**연결 단계에만** 있고 읽기 단계에는 없었던 것이다.

**[수정]** `get()` 이 네 번째 값(실패 사유)을 돌려주고, 세 상태를 가른다.

```
status = 200/404/...   서버가 대답했다        -> 판정한다
status = None          이번에 못 닿았다       -> **확인하지 못함** (어긋남에 더하지 않는다)
```

미확인은 어긋남 수에 더하지 않되 **숨기지도 않는다** — "열리지 않음 0" 만 보고 전수
확인됐다고 읽으면 안 되기 때문이다. 별도 줄로 건수와 URL 을 찍는다.

**[재시도 — 넣은 근거는 실측이다]** 처음 수정본으로 전수를 돌리니 601건 중 **16건**이
15초 타임아웃으로 떨어졌다. 그 16개가 진짜로 안 열리는지 확인하려고 표본 8개를 그대로
다시 요청했다.

```
/api/v1/item/111/documents/SPEC        0.05s  200  1,507,996 B
/api/v1/item/114/documents/APPRAISAL   0.05s  200  3,857,768 B
/api/v1/item/118/documents/APPRAISAL   0.02s  200    790,408 B
/api/v1/item/138/documents/SPEC        0.02s  200    396,206 B
/api/v1/item/213/documents/APPRAISAL   0.04s  200  3,464,670 B
/api/v1/item/240/documents/APPRAISAL   0.05s  200  7,068,951 B
/api/v1/item/335/documents/SPEC        0.15s  200    407,346 B
/api/v1/item/392/documents/SPEC        0.15s  200    398,444 B
                                       -> 8/8 즉시 200
```

그래서 **네트워크 계열만** 1회 재시도한다(15초 -> 25초). HTTP 오류는 재시도하지 않는다 —
몇 번을 보내도 404 는 404 다. BUGS #188 이 JWKS 에서 세운 규칙 그대로다.

```
재시도 전   확인하지 못함 16건 / 601
재시도 후   확인하지 못함  2건 / 601   (0.3%)
```

**[그래서 얻은 것 — 자산 URL 전수 확인]** 이 감사가 죽지 않고 끝까지 돈 것은 이번이
처음이다. 2026-08-25 실측(dev/API 서버는 운영 DB 가 아니라 **임시 사본**을 열었다):

```
[9] 물건 206개 / 사진 URL 45개 / 문서 URL 556개 / **열리지 않음 0개**
    확인하지 못함 2건 (재요청하면 열린다 - 아래)
```

즉 **API 가 광고한 자산 URL 601개가 전부 실제로 열린다.** 표본이 아니라 전수다.

**[관측했으나 원인 미확정 — 성급하게 P0 로 올리지 않는다]** 위 타임아웃의 정체를
쫓았고, 아래까지는 확정했다.

```
증상        문서/이미지 URL 요청이 ~19초 멈춘 뒤 ConnectionResetError.
            같은 URL 을 즉시 다시 요청하면 0.02~0.15초에 200. (8/8)
빈도        연속 601요청 중 16건(2.7%). 재시도를 넣으면 2건(0.3%).
배제한 것   * 파일 크기가 아니다 - 400KB 도 12.5MB 도 양쪽에 다 있다
            * 디스크가 아니다 - 같은 파일을 파이썬으로 직접 읽으면 25개 전부 0.00초
              (OneDrive 자리표시자 hydration 아님)
            * 콜드 스타트가 아니다 - 서버를 재기동하고 **첫 요청**으로 12.5MB 문서를
              받아도 0.03초, 3연속 전부 0.01초 이하
            * 특정 물건/문서가 아니다 - 매 실행마다 걸리는 URL 이 다르다
미확정      왜 어떤 요청만 멈추는가. 감사기는 URL 601개를 **연결을 재사용하지 않고**
            빠르게 연속 요청한다(urllib 은 keep-alive 를 쓰지 않는다). 실제 브라우저는
            연결을 재사용하므로 같은 조건이 아니다 - 사용자가 겪는 증상이라는 근거가
            지금은 없다. **그래서 제품 결함으로 올리지 않고 관측으로 남긴다.**
다음에 할 것 keep-alive 를 쓰는 클라이언트로 같은 전수를 돌려 재현되는지 본다.
            재현되면 그때가 제품 문제다.
```

**[문서 정정]** 체크리스트의 `자산 어긋남 0건 (고아 큐 행 18건은 보고)` 은 **[1]~[5]**
(자산 <-> DB 정합)만 가리키는 말이었는데 도구 전체의 결론처럼 읽혔다. 실제 종료코드는
1 이고 27건이다. 내역을 그대로 적는다.

```
[1]~[5]  자산 <-> DB 정합            어긋남 0건   <- 예전 표현이 가리키던 것
[6]      대응 물건 없는 문서 디렉터리   1건        고양지원/2024타경2803/1 (파일 4개)
[7]      고아 큐 행                   18건        전부 기일 경과 (수집 비용 0)
[8]      다운로드 폴더 고아 파일        8건 / 14.0 MB
[9]      API 자산 URL 전수            0건 열리지 않음   <- 이번에 처음 끝까지 돌았다
                                     ----
                                     27건 (= 1 + 18 + 8)
```

**[[8] 은 새 발견이 아니다 - 이미 분석돼 있고 방어까지 붙어 있다]** 다운로드 폴더의
고아 8개(14.0MB)는 `crawler/doc_crawler.py:141~160` 이 **이미 그 숫자 그대로** 적어
두었다. 원인도 거기 있다 - `wait_for_download()` 가 30초 타임아웃으로 포기한 뒤에도
다운로드가 계속 진행되면, 그 파일이 **다음 사건의 것으로 집힌다**. 그래서 사건번호
대조 거부 규칙이 붙어 있다(그쪽이 진짜 위험이다 - 남의 매각물건명세서를 보고 입찰
판단을 하게 된다). 같은 이름이 네 번 쌓인 `" (1)" " (2)" " (3)"` 도 그 문서가
지목한 흔적 그대로다.

이번에 **더한 것은 시각 정보 하나**다 - 여덟 중 일곱은 mtime 이 `2026-08-03 08:39`
로, 이 저장소 스냅숏의 일괄 mtime 과 같다(`logs/doc_worker.py`, 옛 CSV 24개가 전부
같은 값이다). 즉 **실제 생성 시각을 알 수 없다.** 시각을 믿을 수 있는 것은
`HR2025-0609-0001.pdf` (2026-08-18 15:07) **하나뿐**이다. 그러므로 "지금도 계속
쌓이고 있다"고 말할 근거는 없다 - DocWorker 는 2026-07-12 이후 큐를 만진 적이 없다.
정리(삭제)는 어느 물건 것인지 확정할 수 없어(파일 이름에 법원이 없다) 하지 않는다.
**DocWorker 가 다시 도는 날, 이 폴더가 다시 늘어나는지가 그때의 판정 근거**다.

**[검증]**

```
python audit_asset_integrity.py --selftest        exit 0 (기존 selftest 전부 통과)
python test_audit_selftests.py                    exit 0 (감사 도구 7개)
서버 없이 python audit_asset_integrity.py         exit 1, [9] "확인하지 못함" (예전과 동일)
서버 띄우고 python audit_asset_integrity.py       exit 1, [9] 601건 전수, 열리지 않음 0
                                                  (예전에는 여기서 트레이스백)
운영 auction.db                                   md5 2991c5be... 무변경
```

--------

#195

**프런트가 검색 파라미터 다섯 개를 보내는데 백엔드는 그 이름을 모른다** — FastAPI 는
모르는 쿼리 파라미터를 **오류 없이 버리므로**, 필터를 건 것과 안 건 것이 화면에서 같아
보인다. 지금은 사용자에게 도달하지 않지만 그것을 지켜 주는 것이 **주석뿐**이었다

발견 (2026-08-25, 제품 코드의 `TODO(API 미지원)` 표시를 전수 확인하다가)

**[실측]** 양쪽 소스를 직접 대조했다.

```
프런트  src/app/search/SearchForm.tsx  FILTER_PARAM_KEYS   24개
백엔드  api/v1/search.py  def search() 시그니처            24개
백엔드에 이름이 없는 것                                    5개

    min_building_area / max_building_area
    min_land_area / max_land_area
    special_conditions
```

`buildSearchQuery()` 는 이 다섯을 실제로 URL 에 싣는다. 소스에 `TODO(API 미지원)` 주석이
붙어 있으니 **알고 있는 상태**다.

**[왜 지금은 안 터지나 — 그리고 왜 그것이 안심할 근거가 아닌가]** 이 값을 넣는 UI 가
없다. `SearchForm.tsx` 의 "면적 조건" / "특수조건" 아코디언은 둘 다 본문이
`준비 중입니다` 한 줄이고, `SearchAccordionSection` 의 `muted` 가 제목을 흐리게 해
동작하는 섹션과 구분한다 — **정직하게 만들어져 있다.** 폼 상태는 URL 에서만 채워지므로
손으로 URL 을 치지 않는 한 이 다섯은 생성되지 않는다.

문제는 **그 안전장치가 주석과 "준비 중입니다" 문구뿐**이라는 것이다. 누군가 그 아코디언에
입력 UI 를 붙이는 순간, 그날부터 사용자는 **필터를 걸었는데 안 걸린 결과**를 보게 된다.
그리고 그것은 조용하다 — 상태 코드는 200, 로그도 없고, 결과는 "그냥 많이 나온" 것처럼
보인다. 이 저장소가 가장 경계하는 종류의 실패다.

**[수정 — 코드는 그대로 두고 계약을 고정한다]** 다섯을 지우는 것은 답이 아니다. 지우면
백엔드가 구현될 때 프런트를 다시 만들어야 하고, `types.ts` 가 그 필드를 남긴 이유
(*"못 만들고 있는 이유는 데이터가 아니라 의미 정의다 - 다층 건물은 층별 면적이 여러
개이고 지분 물건 128건은 표시 면적이 전체다"*)도 유효하다. 그래서 **목록으로 고정한다.**

`test_schema_hygiene.py` 에 `test_search_form_params_reach_the_backend()` 를 신설했다
(13단언). 서버를 띄우지 않는다 — 양쪽 **소스**를 읽는다.

```
백엔드   api/v1/search.py 의 `def search(...)` 시그니처를 AST 로 읽는다
프런트   SearchForm.tsx 의 FILTER_PARAM_KEYS 배열을 읽는다
판정     (프런트 - 백엔드) 가 KNOWN_UNSUPPORTED_SEARCH_PARAMS 와 **정확히 같아야** 한다
```

집합이 **늘어나도 줄어들어도** 실패한다.

* 늘어남 = 조용히 무시되는 필터가 하나 더 생겼다.
* 줄어듦 = 백엔드가 구현했다. 목록에서 빼라는 신호다(안 빼면 검사가 낡는다).

방향은 프런트 -> 백엔드로만 본다. `sort_by`/`sort_order`/`page`/`size` 는 검색조건이
아니라 표시 설정이라 `FILTER_PARAM_KEYS` 에 일부러 없다(그 파일 주석이 그렇게 정의한다) —
백엔드에만 있는 것은 결함이 아니다.

그리고 **"준비 중입니다"가 사라지는 것**도 함께 잠갔다. 그것이 지금 사용자를 지켜 주는
유일한 것이므로, 없어지면 그 자리에서 알아야 한다.

**[mutation 3/3 검출 — 그리고 그 과정에서 검사 자체의 구멍을 찾았다]**

```
M1 프런트에 백엔드가 모르는 키를 추가한다        -> 잡았다
M2 백엔드가 sido 를 더 이상 받지 않는다          -> 잡았다
M3 '준비 중입니다' 를 입력 UI 로 바꾼다          -> **처음에는 못 잡았다**
대조군                                          -> exit 0
```

M3 를 처음 돌렸을 때 **초록이 나왔다.** 원인은 검사 쪽이었다 — 섹션 본문을 고정 길이
400자로 잘라 보고 있었는데, 그 창이 **다음 섹션까지 삼켰다.** "면적 조건"의 문구를
지워도 바로 아래 "특수조건"의 것이 잡혀 통과했다.

```python
window = form_src[idx:idx + 400]        # <- 400자가 다음 섹션을 삼킨다
```

창을 그 섹션의 닫는 태그(`</SearchAccordionSection>`)까지로 잘라 고쳤다. **mutation 을
돌리지 않았으면 이 구멍은 그대로 남았을 것이다** — 검사가 있는데 아무것도 안 보는,
이 저장소가 반복해서 잡아 온 바로 그 상태로.

**[남긴 것 — 승인/제품 판단]** 다섯 필터를 실제로 구현하는 것은 이 세션 범위 밖이다.
면적은 `auction_item` 에 컬럼 자체가 없고(프런트가 주소 대괄호에서 파싱한다 —
`src/lib/format.ts`), 특수조건은 백엔드에 대응 개념이 없다. 스키마 변경과 의미 정의가
함께 필요하므로 제품 결정이다. 이 세션은 **그 상태가 조용히 바뀌지 않도록 잠그는 것**까지 한다.

--------

#196

**★ 지금 이 PC 에서 수집 파이프라인 전체가 브라우저를 못 띄운다** — 스케줄러를 등록해도
크롤과 DocWorker 는 첫날 밤에 죽는다. 그리고 남는 로그가 `"Are you offline?"` 라서
조사하는 사람은 **멀쩡한 네트워크를 뒤지게 된다**

발견 (2026-08-25, #193 에서 감사 도구의 드라이버 해석을 고친 뒤 *"제품 크롤러도 같은
호출을 쓰지 않나"* 를 확인하다가)

**[왜 이것이 P0-A 와 직결되나]** `docs/BETA_RELEASE_CHECKLIST.md` 는 P0-A(기본 검색이 빈
화면)의 **1순위 조치**를 이렇게 적어 두었다.

```
1. `DojoonPass-DailyCrawl` 스케줄러 등록 (`register_scheduler_tasks.ps1`).
   이것이 없으면 크롤이 돌지 않고, 크롤이 돌지 않으면 P0-A 는 절대 닫히지 않는다.
```

같은 세션에 그 스크립트를 dry-run 해 보니 선행 조건이 전부 OK 였다 — 등록만 하면 될
것처럼 보였다. **그런데 등록해도 안 돈다.** 그 뒤 단계에서 죽기 때문이다.

**[실측 — 제품 코드를 실제로 불러 봤다]** (법원 사이트에는 접속하지 않는다. 드라이버
기동까지만 시도한 것이다.)

```
crawler.base_crawler.build_driver()           (run_daily.bat -> mvp_scraper)   1.3초 만에 실패
crawler.doc_crawler.build_download_driver()   (run_doc_worker.bat -> doc_worker) 1.1초 만에 실패
collect_documents.build_driver()                                                 실패

전부  ConnectionError: Could not reach host. Are you offline?
```

**[그 문장은 거짓이다]** 같은 순간 같은 호스트를 직접 쟀다.

```
stdlib urllib -> https://googlechromelabs.github.io/chrome-for-testing/...
                 HTTP 200, 0.05초, 200 bytes
requests      -> SSLCertVerificationError
                 "unable to get local issuer certificate"        (3회 시도 전부, 0.18초)
```

`webdriver_manager` 는 `requests` 로 최신 드라이버 버전 목록을 받아 오는데 **그 경로의
CA 검증만** 이 PC 에서 깨져 있다(회사/백신 TLS 개입이거나 certifi 가 낡았거나 - 원인은
이 저장소 밖이다). 그리고 그 예외를 삼켜 *"오프라인이냐"* 로 바꿔 던진다.

캐시도 도움이 안 된다 — `~/.wdm/drivers/chromedriver/win64/151.0.7922.138` 인데 설치된
크롬은 **151.0.7922.170** 이라, 버전 확인을 위해 매번 바깥을 봐야 한다.

같은 순간 Selenium 4.47 내장 해석기(Selenium Manager)는 **9.6초 만에 크롬을 띄웠다.**

**[영향]**

* 스케줄러를 등록하면 매일 03:00/06:00 에 조용히 실패한다. `.bat` 의 실패 검출은
  살아 있으므로 `[FAILED] ... exited with code 1` 은 남는다 — **다행히 은폐는 아니다.**
* 그러나 로그 본문의 문장이 "오프라인이냐"다. 이 저장소는 2026-08-03~08-11 에
  **9일간 크롤 중단을 몰랐던** 이력이 있고, 그때의 교훈이 "실패가 로그에 남아야 한다"였다.
  이번에는 로그에 남되 **틀린 것을 가리킨다** — 조사자는 인터넷을 의심하게 된다.
* `docs/CLAUDE.md`/체크리스트가 "선행 조건은 전부 확인됐다. 남은 것은 등록뿐"이라고
  적고 있어, 등록 -> 실패 -> 원인 오인 의 경로가 그대로 깔려 있었다.

**[수정 — 해석 경로를 하나로 모으고 폴백을 둔다]** `crawler/base_crawler.py` 에
`resolve_chrome_driver(opts)` 를 두고, 파이프라인 셋이 전부 그것을 쓴다.

```
1. Selenium Manager   (selenium 4.6+ 내장, 캐시가 맞으면 바깥을 안 본다)   <- 먼저
2. webdriver_manager  (예전 경로)                                          <- 폴백
둘 다 실패 -> DriverUnavailable("A -> ...; B -> ...")                      <- 두 사유 함께
```

* 폴백으로 살아난 경우에도 **앞선 실패를 `logger.warning` 으로 남긴다.** 조용히 넘어가면
  다음에 폴백까지 죽었을 때 "언제부터 이랬나"를 알 수 없다.
* 새 모듈을 만들지 않았다 — 추적되지 않은 파일을 추적된 파일이 import 하면 커밋된 트리가
  부팅하지 못한다(BUGS #105, #186 이 같은 이유로 인라인을 택했다). `crawler/base_crawler.py`
  는 이미 추적되고 이미 "드라이버를 만드는 곳"이라 그 한 곳에 둔다.
* 모듈 최상위의 `from webdriver_manager.chrome import ChromeDriverManager` 는 폴백 함수
  안으로 옮겼다 — 그 패키지가 없는 환경에서도 Selenium Manager 로 돌 수 있어야 한다.

**[검증 — 수정 전후 같은 호출]**

```
                                                    수정 전            수정 후
crawler.base_crawler.build_driver (DailyCrawl)      실패 1.3초        OK  0.9초  크롬 151.0.7922.170
crawler.doc_crawler.build_download_driver (DocWorker) 실패 1.1초      OK  1.2초  크롬 151.0.7922.170
collect_documents.build_driver                       실패             OK  1.2초  크롬 151.0.7922.170
```

**[회귀 + mutation]** `test_schema_hygiene.py` 에
`test_pipeline_resolves_chrome_driver_through_one_place()` 를 신설했다(12단언).
**브라우저를 띄우지 않는다** — 구조는 AST 로, 동작은 가짜 factory 주입으로 본다.

```
구조  스케줄러가 실제로 돌리는 파일 8개가 `ChromeDriverManager` 를 **직접 호출**하지
      않는가 (유일한 예외: crawler/base_crawler.py 의 폴백 함수 안)
      + base_crawler 가 폴백을 **둘 이상** 갖고 있는가
행위  순서 / 폴백 / 전멸 시 DriverUnavailable + 두 사유 보존
```

문자열이 아니라 **호출 노드**를 본다 — 주석에 이름이 나오는 것(수정하며 남긴 설명)까지
결함으로 세면 검사가 곧 무력화된다.

mutation 3/3 검출:

```
M1 doc_crawler 가 다시 직접 ChromeDriverManager 를 부른다 -> 잡았다 (파일:줄 지목)
M2 Selenium Manager 폴백을 없앤다                        -> 잡았다
M3 첫 실패에서 멈춘다(폴백 안 함)                         -> 잡았다 (FAIL 5줄)
대조군                                                   -> exit 0
```

**[범위를 넓혔다 — 추적된 파이썬 전부]** 처음에는 스케줄러가 돌리는 파일 8개만 봤다.
그런데 같은 호출이 추적된 일회용/수동 스크립트에도 여섯 군데 더 있었다
(`analyze_docs.py`, `analyze_hyunhwang.py`, `manual_test.py`, `verify_courts.py`,
`test_docs.py`, `test_docs2.py`). 스케줄러가 돌리지는 않지만 **이 PC 에서는 그것들도
지금 안 뜬다** — 누가 손으로 돌리면 같은 거짓 메시지를 본다. 한 줄씩이라 전부 고쳤다.

그래서 검사도 목록을 손으로 들지 않게 바꿨다 — `git ls-files "*.py"` 로 **추적된
파이썬 150개 전부**를 훑고, 폴백을 들고 있는 둘(`crawler/base_crawler.py`,
`audit_viewport.py`)만 예외로 둔다. 손으로 든 목록은 새 스크립트를 놓치지만 이건
놓치지 않는다 — BUGS #186 의 감시기가 허용목록 대신 행동을 본 것과 같은 이유다.
실측: 추적 파일 150개 중 직접 호출 **0건**(폴백 보유자 2개 제외).

**[같이 확인한 것 — 파급 범위를 한정했다]** `requests` 의 CA 검증이 깨진 것이 원인이므로,
제품 코드가 그 패키지를 쓰는 곳이 또 있으면 같은 방식으로 조용히 죽는다. 전수 확인했다
(2026-08-25, AST 로 import 를 훑음 — `api/` `storage/` `crawler/` `config/` `normalizer/`
`validator/` `models/` `intent/` `filter/` + 루트 진입점 6개):

```
requests / httpx / urllib3 / aiohttp import   0건
제품이 쓰는 HTTP 클라이언트                    stdlib urllib 뿐
  (같은 순간 stdlib urllib 로 외부 HTTPS GET -> HTTP 200, 0.05초)
```

즉 이 환경 문제의 파급은 **드라이버 조달 한 곳뿐**이었고, 그곳을 고쳤다.
`api/auth.py` 의 JWKS 조회도 stdlib 이라 영향이 없다 — 같은 세션에 실제로 200 을 받았다
(`audit_auth_health.py` exit 0).

**법원 사이트(`courtauction.go.kr`) 도달 여부는 재지 않았다** — 이 세션의 SKIP 목록
("실제 crawler 실행 금지")에 걸린다. 다만 크롬은 OS 인증서 저장소를 쓰고 `requests` 를
거치지 않으므로 위 CA 문제와는 경로가 다르다. 확인은 크롤을 승인받는 날 함께.

**[기준선]** 통과 53 / 실패 1, 단언 **8,172**건. 운영 DB 와 `logs/` 전체 바이트 무변경.

--------

#197

**`doc_raw` 에 쓰는 곳이 둘인데 규칙이 갈라져 있었다** — 한쪽은 내용이 그대로면 버전을
안 올리고, 다른 쪽은 **무조건 올린다.** 경로 표기도 한쪽은 상대, 다른 쪽은 절대다

발견 (2026-08-25, 문서 파이프라인의 중복 방지 경로를 사본 DB 에서 직접 눌러 보다가)

**[경위]** `auction_item -> document_queue -> DocWorker -> doc_raw -> document_status`
체인에서 *"동일 문서 재수집 시 중복 INSERT 가 발생하지 않는가"* 를 코드를 읽는 대신
**실제로 눌러** 확인했다(운영 DB 사본, 브라우저·네트워크 없음). doc_worker 경로는
전부 통과했는데, `doc_raw` 작성자가 **하나가 아니라는 것**이 그때 드러났다.

```
storage.database._record_doc_raw()    doc_worker 경로 (스케줄러가 도는 쪽)
collect_documents.save_doc_raw()      손으로 돌리는 진입점 (`python collect_documents.py`)
```

**[실측 — 두 함수를 같은 사본 DB 에 나란히 눌렀다]** (2026-08-25)

```
                        _record_doc_raw            save_doc_raw
같은 파일로 두 번 저장   행 1개 (내용 지문 비교)     **행 2개** (v2, v3 - 지문이 같은데도)
storage_path 표기       documents/남양주지원/...    **절대경로 그대로**
UNIQUE 충돌 시          없음(버전을 새로 계산)      INSERT OR IGNORE 로 **조용히 버림**
실패 사유               logger.warning 에 사유      `str(e)` 만 (예외 종류가 안 남는다)
```

첫 줄이 핵심이다. `save_doc_raw()` 는 `MAX(doc_version)+1` 을 **무조건** 계산한다 —
내용이 한 글자도 안 바뀌어도 새 버전이 쌓인다. 이것은 BUGS #115/#187 이 이미 잡은
결함인데 **`_record_doc_raw` 쪽에서만 고쳐졌다.** 같은 표에 쓰는 다른 함수는 그대로였다.

`api/v1/item.py` 가 `MAX(doc_version)` 을 사용자 응답에 그대로 실으므로, 이 스크립트를
손으로 두 번 돌리면 **내용이 그대로인데 화면의 문서 버전이 오른다.**

두 번째 줄도 실재하는 규약 위반이다. `storage/database.py` 머리 주석과
`to_relative_storage_path()` docstring 이 이유까지 적어 두었다 — *"절대경로를 DB에 넣으면
배포 위치가 바뀌는 순간 전 행이 못 쓰게 된다."* 감사기도 그 규약을 전제로
`os.path.join(PROJECT_ROOT, storage_path)` 로 해석한다. 지금 이 PC 에서는
`os.path.join()` 이 절대경로를 그대로 돌려주는 덕에 **우연히 열린다.**

**[운영 데이터는 아직 깨끗하다]** 실측: `doc_raw` 556행 **전부 상대경로**, 절대경로 0행.
`collect_documents.py` 를 스케줄러가 돌리지 않기 때문이다(BUGS #144 가 적어 둔 사실).
즉 **지금 터진 버그가 아니라, 손으로 한 번 돌리는 순간 터지는 버그**였다.
베타 준비 중 "문서를 좀 채워 두자"고 이 스크립트를 돌리는 것은 충분히 있을 법한 일이다.

**[수정 — 규칙을 두 벌 두지 않는다]** `storage/database.py` 에
`record_doc_raw_row(conn, item_id, ds_type, files_saved, now, primary_ext=None)` 를
두고 **둘 다 그것을 부른다.** 돌려주는 값으로 세 상태를 가른다.

```
""            새 행을 넣었다
"unchanged"   내용이 직전 버전과 같아 넣지 않았다  -> **성공이다**
그 밖의 문자열  기록하지 못했다(사유)               -> **실패로 다뤄야 한다**
```

`_record_doc_raw()` 는 물건 식별 / 종류 매핑 / 사진 제외까지만 하고 규칙은 위임한다.
`save_doc_raw()` 는 자기 버전 계산·INSERT·해시·페이지수 계산을 **전부 버리고** 같은 함수를
부른 뒤, 결과가 실패 사유면 `document_status` 를 건드리지 않고 False 를 돌려준다.

이 판단은 이 저장소가 `claim_next_item_rows()` 에서 이미 내린 것과 같다 —
*"그 어휘가 두 곳에 생기면 한쪽만 고쳐지는 날이 온다."* 실제로 그 날이 와 있었다.

**[계약은 바뀌지 않는다]** `save_doc_raw()` 의 기존 계약 셋을 그대로 유지했고 회귀가
그것을 지킨다(`test_collect_documents.py` §1/§2/§6):

```
파일이 없다 / 0바이트   -> False, doc_raw 행 없음, document_status 는 COLLECTING 유지
내용이 직전과 같다      -> True,  새 행 없음,      document_status 는 READY
새 내용                 -> True,  새 버전 1행,     READY
```

**[함께 고친 것 — 증거 없는 실패]** `except Exception as e: logger.warning("save_doc_raw
실패: %s", str(e))` 는 예외 **종류**를 남기지 않았다. 무결성 위반인지 디스크 문제인지
구분할 수 없다. `type(e).__name__` 과 item/doc_type 을 함께 남기고, 예외 시
`conn.rollback()` 을 부른다(예전에는 부분 쓰기가 그대로 남을 수 있었다).

**[회귀 + mutation]** `test_collect_documents.py` 에
`test_two_doc_raw_writers_share_one_rule()` 을 신설했다(11단언).
**행위 + 구조**를 함께 본다 — 같은 내용 두 번 저장해 버전이 안 오르는지(행위),
두 함수가 실제로 `record_doc_raw_row` 를 부르는지 AST 로(구조),
그리고 `collect_documents.py` 안에 `INSERT INTO doc_raw` 가 다시 생기지 않았는지.
대조군(내용이 바뀌면 버전이 오른다)을 함께 둔다 — 없으면 검사가 공허하다.

경로 규약은 **저장소 루트 안**에 파일을 만들어 확인한다. `Env` 의 임시 디렉터리는
루트 밖이라 `to_relative_storage_path()` 가 원본을 그대로 돌려주는 것이 정상이고,
그 상태로는 상대경로 규약을 검증할 수 없다 — 그래서 검사가 자기 파일을 루트 안에 만든다.

mutation 3/3 검출:

```
M1 내용 지문 비교를 없앤다 (save_doc_raw 의 원래 버그)  -> 잡았다 (FAIL 3줄)
M2 to_relative_storage_path() 를 없앤다                 -> 잡았다 (절대경로 그대로 나옴)
M3 collect_documents 가 자기 INSERT 를 다시 만든다      -> 잡았다 (FAIL 17줄)
대조군                                                  -> exit 0
```

M1 은 **기존 검사도 함께 잡았다**(`doc_raw 행은 1건 유지(중복 생성 없음)`) —
`_record_doc_raw` 쪽은 이미 방어가 있었다는 증거다. 없던 것은 다른 작성자 쪽뿐이었다.

**[같이 확인한 것 — 결함 아님]** 같은 사본 DB 에서 파이프라인의 나머지 질문도 눌러 봤다.

```
같은 내용 재수집        doc_raw 행 안 늘어남                              OK
내용 변경               doc_version +1                                    OK
옛 내용으로 되돌아감     새 버전 생성(직전 버전과만 비교하므로 옳다)        OK
파일 없음 / 0바이트      doc_raw 행 안 만듦                                OK
동시 처리(스레드 2개)    doc_version 중복 0, 예외 0, 두 버전이 순서대로     OK
```

`mark_queue_done()` 을 **직접** 부르면 파일이 없어도 `document_status=READY` /
`queue=done` 이 된다. 다만 이것은 도달하지 않는다 — 유일한 제품 호출부인
`doc_worker.py` 가 그 앞에서 파일 존재/크기를 전수 확인하고 하나라도 없으면
`mark_queue_failed()` 로 보낸다(Sprint 214 §2). 즉 방어가 호출부에 있다.
**지금은 옳게 동작하지만 불변식이 DB 계층이 아니라 호출부에 있다**는 것은 적어 둔다 —
새 호출부가 생기면 같은 방어를 다시 써야 한다.

--------

#198

**문서에는 2차 방어선이 없었다** — `document_status` 가 READY 이기만 하면 서빙 파일이
없어도 `available=true` 에 `viewer_url` 까지 줬고, 그 URL 은 **404** 다.
사진 쪽에는 같은 방어선이 이미 있었다

발견 (2026-08-25, 문서 파이프라인 감사 중 사진/문서의 응답 규칙을 나란히 놓고 보다가)

**[경위]** `api/v1/item.py` 의 사진 판정(`_images_status`)에는 Sprint 208 이 넣은 2차
방어선이 있다 — *"READY 인데 볼 사진이 0장인 것은 자기모순이다. 그대로 전달하면 화면은
'사진 있음'이라고 말하고 목록은 빈 상태가 된다 — 오류도 빈 화면도 아니라 사용자가 원인을
알 수 없다."* 그래서 READY 를 COLLECTING 으로 낮춘다.

**문서 쪽에는 그 규칙이 없었다.**

```python
"available": status == "READY",
"viewer_url": _document_url(item_id, doc_type) if status == "READY" else None,
```

**[재현 — 합성 물건 하나]** 사본 DB 에 `document_status=READY` 인 물건을 만들고
디스크에는 파일을 두지 않았다(실제 파일은 하나도 건드리지 않는다).

```
SPEC       status=READY  available=True  file_size=None
           viewer_url=/api/v1/item/16721/documents/SPEC
APPRAISAL  status=READY  available=True  file_size=None
그 viewer_url 을 실제로 요청  ->  **HTTP 404**

대조군(사진)  images_status=COLLECTING   <- 이쪽은 이미 낮춘다
```

**[판단 근거는 이미 그 함수가 갖고 있었다]** `file_size` 는 `_served_file_size()` 로
**서빙 경로에서 직접 잰 값**이고, 파일이 없거나 0바이트면 None 이다. 그 값을 화면 표시에만
쓰고 **판정에는 쓰지 않았다.** Sprint 214 가 doc_worker 에서 고친 것과 정확히 같은 모양이다
— *"함수를 불렀다"와 "성공했다"는 다르다.*

**[영향]** 사용자가 "열람 가능"을 보고 누르면 404 다. 프런트가 같은 계열의 문제를 이미
한 번 겪었다(`properties/[id]/page.tsx`: *"수집중인 문서도 파란 밑줄 링크였고, 누르면
'문서를 찾을 수 없다'"*). 그때는 프런트에서 막았고, 이번 것은 **서버가 잘못 광고하는**
경우라 프런트가 막을 수 없다.

**[운영 데이터에는 이 상태가 없다 — 그래서 예방이다]** 과장하지 않기 위해 수정 전후
응답을 **전수 비교**했다(사본 DB + TestClient, 문서를 가진 물건 전부).

```
비교 대상          물건 200건 / 문서 응답 전체
응답이 달라진 물건   **0건**
available=true 문서  556 -> 556
```

즉 지금 데이터를 바꾸는 수정이 아니다. `doc_worker` 가 쓰기 전에 파일을 전수 확인하므로
(Sprint 214 §2) 정상 경로로는 이 상태가 생기지 않는다. 파일 유실·수동 조작·
`mark_queue_done()` 직접 호출(BUGS #197 의 "같이 확인한 것")로 생겼을 때를 위한 방어선이다.

**측정 중 한 번 오판했다 — 기록해 둔다.** 처음에 "실물 10건이 낮춰졌다"고 읽었는데,
그 10건은 **원래부터 `document_status=COLLECTING`** 인 STATUS 행이었다(내 판정식이
"COLLECTING + file_size None" 이라 원래 COLLECTING 인 것까지 셌다). 실제 READY 문서
556건의 서빙 파일은 **전부 존재한다**(SPEC 197 / STATUS 162 / APPRAISAL 197, 없음 0).
전수 비교로 다시 재고 나서야 "0건"이 확정됐다.

**[수정]** `_document_entry()` 에서 잰 결과를 판정에 쓴다.

```
measured = READY 이고 item_row 가 있고 서빙 대상 종류다
effective_status = COLLECTING  (measured 인데 크기를 못 쟀을 때)
available / viewer_url / download_url 은 effective_status 를 따른다
```

범위를 좁게 잡았다 —

* `IMAGE` 는 대상이 아니다. 서빙 파일이 하나로 정해지지 않고(0~N장) 판정은
  `_images_status()` 가 이미 한다. 종류 목록은 서빙 계층의 `DOC_TYPE_FILES` 를 그대로
  쓴다(같은 어휘를 두 벌로 만들지 않는다).
* `item_row` 가 없으면 **낮추지 않는다.** 잴 수 없는 것을 "없다"로 읽지 않는다
  (BUGS #188 이 세운 "모른다 != 고장났다" 구분).
* READY 가 아닌 상태(NO_IMAGE/FAILED/COLLECTING)는 건드리지 않는다.

**[회귀 + mutation]** `test_asset_pipeline.py` 에 §17b
`test_ready_document_without_served_file_is_not_advertised()` 를 신설했다(30단언).
사진의 §17 바로 옆에 둔다 — 두 규칙이 대칭이라는 것이 그 자체로 문서다.
대조군을 넷 둔다: 파일이 있으면 READY 유지 + **광고한 URL 이 실제로 200**,
0바이트는 불가, FAILED 는 그대로, IMAGE 는 건드리지 않음.

mutation 3/3 검출:

```
M1 2차 방어선을 없앤다 (원래 동작)          -> 잡았다 (FAIL 14줄)
M2 IMAGE 까지 방어 대상에 넣는다 (과잉 적용)  -> 잡았다
M3 0바이트를 정상 크기로 친다                -> 잡았다
대조군                                      -> exit 0
```

**M2 는 처음에 못 잡았다.** IMAGE 대조군을 `NO_IMAGE` 로 세워 뒀는데, 그러면 애초에
측정 분기(`status == "READY"`)에 들어가지 않아 **대조군이 공허했다.** `READY` 로 바꾸니
잡힌다. mutation 을 돌리지 않았으면 "IMAGE 는 안 건드린다"는 검사가 아무것도 안 보는
채로 남았을 것이다.

**[함께 손본 픽스처]** `test_asset_pipeline.py` §16(`test_api_contract`)이
`document_status=READY` 행만 넣고 **파일은 만들지 않은 채** "열람 가능 = True" 를
기대하고 있었다 — 운영에서는 일어나면 안 되는 상태다(광고한 URL 이 404). 픽스처가
서빙 파일을 실제로 만들도록 고쳤다. 실물 200물건 비교에서 응답이 달라진 물건이 0건이었으므로
**파일 없이 READY 였던 것은 이 픽스처뿐**이다.

**[검증]**

```
python run_python_tests.py    통과 53 / 실패 1 / 단언 8,250 (수정 전 8,203)
                              남은 실패 1건은 P0-A (기일 미도래 0건)
npm run test:frontend         191건 / 187 pass / 1 fail / 3 skip  (서버 띄우고 측정)
                              남은 실패 1건 = 같은 P0-A
전수 비교                     실물 200물건 응답 무변경, available=true 556 -> 556
운영 auction.db + logs/       바이트 무변경
```

--------

#199

**같은 문서를 동시에 기록하면 `IntegrityError` 가 올라간다** — `mark_queue_done()` 이
"멱등"이라고 적어 둔 그 자리가 실제로는 예외였다. 받아 놓은 문서가 **실패로 기록되고
다시 수집된다**

발견 (2026-08-25, #197 로 합친 공통 규칙을 합성 물건으로 끝까지 눌러 보다가)

**[경위]** #197 이 `doc_raw` 작성자 둘을 `record_doc_raw_row()` 하나로 합쳤다. 그 규칙을
**합성 물건**으로 A~F 6축 58항목 검증하던 중, 동시성 축에서 걸렸다.

```
합성 물건 1개에 스레드 4개가 동시에 record_doc_raw_row() 호출 (각자 다른 내용)

  결과 버전   [1]                       <- 하나만 들어갔다
  예외        IntegrityError x 3
              "UNIQUE constraint failed: doc_raw.item_id, doc_raw.doc_type, doc_raw.doc_version"
```

**[원인 — 읽고-계산하고-쓰는 사이가 경쟁 구간이다]**

```python
latest  = SELECT doc_version ... ORDER BY doc_version DESC LIMIT 1
version = latest + 1                      # <- 여기와
INSERT INTO doc_raw (... doc_version ...) # <- 여기 사이
```

네 실행이 모두 `latest = 없음` 을 읽고 전부 `version = 1` 을 계산한 뒤 INSERT 한다.
UNIQUE 가 하나만 통과시키고 나머지 셋은 예외다.

**[왜 이것이 실제 문제인가]** `mark_queue_done()` 은 claim 을 빼앗긴 실행에 대해 이렇게
적어 두었다.

> ★ 그래도 `document_status`/`doc_raw` 는 그대로 쓴다 - 파일은 **실제로** 받아졌기
> 때문이다. 화면이 그 사실을 반영해야 하고, 나중에 그쪽 실행이 같은 값을 다시 써도
> **결과는 같다(멱등).**

**멱등이 아니라 예외였다.** 도달 경로는 BUGS #181 이 서술한 좀비 워커다 — stale 회수로
큐 행을 빼앗긴 실행이 뒤늦게 종결하는 동안 새 실행이 같은 문서를 처리하는 경우.
그때 예외가 `doc_worker` 의 행 단위 `except` 까지 올라가면 `mark_queue_failed()` 로
가므로, **실제로 받아 놓은 문서가 실패로 기록되고 다음 실행이 다시 받는다.**
데이터 손상은 아니지만 거짓 실패 + 헛수집이고, 무엇보다 **문서가 약속한 계약을 깬다.**

**[수정 — 밀리면 다시 읽고 다시 센다]** `claim_next_queue_item()` 이 claim 경쟁에서
이미 택한 방식과 같다.

```
for attempt in range(DOC_RAW_VERSION_RACE_ATTEMPTS):   # 4
    latest = 다시 읽는다
    if latest 의 해시 == 지금 해시:  return "unchanged"   # 상대가 같은 문서를 넣었다
    version = latest + 1
    try:    INSERT;  return ""
    except sqlite3.IntegrityError:  continue            # 밀렸다 - 다시
return "doc_raw 버전 경합이 4회 계속돼 기록하지 못했다"    # 조용히 성공이라고 하지 않는다
```

* 다시 읽었을 때 상대가 **같은 내용**을 넣어 두었으면 그것이 곧 `unchanged` 다 —
  둘이 같은 문서를 받은 것이므로 그 답이 정확하다(멱등이 여기서 진짜가 된다).
* SQLite 는 제약 위반 시 **그 문장만** 되돌리므로 바깥 트랜잭션은 살아 있다.
* 상한을 두는 이유도 claim 과 같다 — 경쟁자가 계속 이겨도 한 호출이 영원히 머물면 안 된다.
* 상한까지 밀리면 **빈 문자열(=성공)을 돌려주지 않는다.** 사유를 돌려주고 경고를 남긴다.

**[함께 손본 것 — 재시도가 곧 지연이 되지 않게]** 루프 안에서 파일을 다시 여는 계산
(`_pdf_page_count()`, 상대경로 변환, 날짜)을 **루프 밖으로 뺐다.** 값은 재시도해도
같은데, `_pdf_page_count()` 는 pdfplumber 로 PDF 를 여는 비용이라(실측: appraisal
최대 259쪽) 그대로 두면 경합이 발생할 때마다 그 파싱을 최대 4번 반복하게 된다.
경합 방어가 스스로 느려지는 것은 방어가 아니다.

**[검증 — 수정 전후 같은 조건]**

```
                              수정 전                     수정 후
동시 4건 (서로 다른 내용)      버전 [1] / 예외 3건         버전 [1,2,3,4] / 예외 0건
동시 4건 (같은 내용)           (같은 계열로 충돌)          행 1개 / 예외 0건
```

**[상한 4 가 충분한가 — 재고 나서 답한다 (2026-08-25 추가 실측)]** 재계산 상한이 4 이므로
writer 가 8개 붙으면 한 실행이 최대 7번 밀릴 수 있다. 이론상 소진 가능해 보여서
**동시성을 올려 가며 실제로 쟀다**(완전 합성 DB, 서로 다른 내용을 동시에 기록).

```
writer  2개  -> 예외 0 / 상한소진 0 / 버전 1..2   연속
writer  4개  -> 예외 0 / 상한소진 0 / 버전 1..4   연속
writer  8개  -> 예외 0 / 상한소진 0 / 버전 1..8   연속
writer 16개  -> 예외 0 / 상한소진 0 / 버전 1..16  연속
writer 32개  -> 예외 0 / 상한소진 0 / 버전 1..32  연속
writer 64개  -> 예외 0 / 상한소진 0 / 버전 1..64  연속
```

**64개에서도 한 번도 소진되지 않는다.** 이유는 SQLite 의 잠금 모델이다 — 이 저장소는
`journal_mode=delete`(롤백 저널, WAL 아님)라 **쓰기가 직렬화**된다. 밀린 실행은 승자가
**커밋한 뒤에** 재시도하므로 다시 읽은 MAX 가 항상 최신이고, 그래서 재시도는 사실상
1회면 끝난다. 상한 4 는 넉넉하다.

그래서 `INSERT ... SELECT COALESCE(MAX(doc_version),0)+1` 로 계산을 한 문장 안에 넣는
"더 단단한" 수정은 **하지 않았다.** 근거 없이 뜨거운 경로를 바꾸지 않는다 — 위 실측이
필요 없다고 말한다. (WAL 로 바꾸면 스냅숏 격리 때문에 이야기가 달라진다.
`journal_mode` 를 바꾸는 날 이 문단을 다시 읽을 것.)

현실의 동시성은 그보다 훨씬 낮다 — `doc_worker` 는 `RunLock` 으로 단일 인스턴스이고,
동시 기록이 생기는 경로는 **좀비 워커 1 + 새 실행 1 = 2** 가 사실상 상한이다(BUGS #181).

**[회귀 + mutation]** `test_collect_documents.py` 에 §10
`test_doc_raw_version_race_does_not_raise()` 를 신설했다(9단언).

mutation 3/3 검출:

```
M1 IntegrityError 를 안 잡는다 (원래 버그)        -> 잡았다 (버전 [1])
M2 상한을 1 로 줄인다 (재계산을 사실상 안 함)      -> 잡았다
M3 경합 실패를 조용히 성공("")으로 답한다          -> 잡았다
대조군                                            -> exit 0
```

**M3 는 처음에 못 잡았다.** 스레드 검사만으로는 그 갈래에 도달하지 않는다 —
4회 안에 항상 성공하기 때문이다. 그래서 **INSERT 만 항상 충돌하는 커넥션**을 끼워
상한 소진 갈래를 결정적으로 밟게 했다. 이 저장소가 반복해서 배운 것과 같다 —
*"가끔 밟는 것은 방어선이 아니다"*(BUGS #183 의 곁가지).

**[같이 확인한 것 — 합성 물건 6축 58항목 전 구간 통과]**

```
A. 공통 규칙 자체 (13)      빈 목록/없는 파일/0바이트 -> 사유 반환, 행 안 만듦
                            정상 -> "" , 같은 내용 -> "unchanged", 변경 -> 새 버전
                            status 는 json 을 대표로 고른다(대표 파일 크기 일치)
B. 작성자 둘의 일치 (6)     경로 표기 · 해시 · 행 수 전부 동일
C. READY x 파일 4조합 (13)  READY+파일있음 -> available, 광고한 URL 이 **실제로 200**
                            READY+파일없음 -> COLLECTING/available=False/URL 없음
                            COLLECTING+파일있음 -> 올려주지 않는다(재수집이 판단한다)
                            FAILED -> 그대로 전달
D. 재처리/중복 (6)          같은 파일 5회 -> 1행 / 변경 -> +1 / 되돌림 -> 새 버전
                            동시 4건 -> 버전 중복 0, 예외 0
E. queue (10)               재적재 0건 / 동시 claim 중복 0 / 실패->pending+retry
                            소진->failed / stale in_progress -> pending 회수
                            기일 경과 -> 적재 안 함 / done -> 되살아나지 않음
F. silent failure (10)      없는 파일·0바이트 -> False + 행/상태 안 만듦 + API 광고 안 함
                            mark_queue_done 직접 호출 -> doc_raw 없음 + status READY 지만
                            **API 2차 방어선이 available=False 로 막는다**
```

**[측정 중 배운 것 — 문서 루트가 네 곳에 따로 있다]** 처음 이 검증을 돌렸을 때
`C. READY+파일있음` 이 전부 실패했다. 원인은 제품이 아니라 검증 환경이었다 —
`api/v1/documents.py` 와 `api/v1/images.py` 가 **자기 `DOCUMENT_ROOT` 를 따로 들고 있어**
`crawler.doc_paths` 하나만 임시 루트로 돌리면 API 는 운영 `documents/` 를 뒤진다.
`test_asset_pipeline.py` 의 `Env` 가 이미 같은 이유로 넷(+PROJECT_ROOT 둘)을 함께 돌리고
있었고, 그 주석이 함정을 정확히 적어 두었다(Sprint 217). 새 검증을 쓰는 사람이 같은 데
빠지지 않도록 여기 적어 둔다 — **문서 루트를 바꾸려면 네 곳을 함께 바꿔야 한다.**

--------

#200

**★ 이 저장소는 "이 머신의 DB" 를 "제품의 상태" 로 읽어 왔다** — 그런데 개발 머신과
운영 크롤 머신이 **다르다.** P0-A("기본 검색이 빈 화면")를 비롯한 여러 결론이
그 전제 위에 서 있었다

확정 (2026-08-25, 사용자가 운영 구조를 알려 줌)

**[운영 구조]**

```
데스크탑3 (이 세션이 도는 곳)   개발 · 테스트 · Audit · QA · scratch DB 검증
                                **운영 크롤링을 실행하지 않는다**
데스크탑1 (집)                  DOJOONPASS 운영 Daily Crawl 담당
                                운영 DB / 크롤링 데이터의 실제 기준점
```

**[이 저장소가 저지른 오류]** 이 머신에서 아래를 보고 **곧바로 운영 장애로 기록**했다.

```
예약 작업 0개                     -> "크롤이 돌지 않는다"
auction_item MAX(crawl_date) 08-12 -> "13일째 공급이 없다"
기일 미도래 물건 0건               -> "사용자에게 빈 화면" = P0-A, 유일한 출시 차단 요소
```

셋 다 **이 머신이 크롤 머신이 아니기 때문에 당연한 값**이다. 운영 상태에 대해서는
아무것도 말해 주지 않는다.

**[이 함정은 이미 적혀 있었다 — 그리고 잊혔다]** `docs/SPRINT102_PATTERN_SPREAD_AND_DOC_DRIFT.md`
가 정확히 이 지점을 짚어 두었다.

> 게다가 **이 PC가 운영 머신이 맞는지도 코드로는 알 수 없다.**

그 문장은 "그래서 내가 스케줄러를 등록하지 않았다"의 근거로만 쓰이고, **측정을 읽는
방식에는 적용되지 않았다.** 이후 스프린트들은 같은 머신의 DB 를 계속 "실측"이라 부르며
제품 판정을 내렸다. BUGS #185 가 "손으로 DB 파일을 고르면 안 된다"를 배웠지만,
그보다 한 겹 위에 **"이 머신이 그 데이터의 주인인가"** 라는 질문이 있었던 것이다.

**[이 머신의 `auction.db` 는 무엇인가 — 실측으로 확정]** (2026-08-25, 읽기 전용)

```
사용자 테이블            favorites 0 / search_presets 0 / payments 0 / subscriptions 0
                        registry_requests 0 / audit_logs 0 / payment_webhooks 0
sqlite_sequence(누적 id) search_presets 177,299 / payment_logs 88,917
                        registry_requests 42,047 / payments 31,035 / audit_logs 38,750
crawl_date              서로 다른 날짜 20개, 마지막 2026-08-12(그날 9행)
```

**행은 0인데 누적 id 는 수만이다.** 실사용자가 만든 데이터라면 남아 있어야 한다.
이것은 **테스트가 만들었다 지운 흔적**이고, BUGS #186 이 기록한 그대로다(회귀 스위트가
이 DB 에 직접 쓰고 끝에 지웠다 — 행수는 원복되고 시퀀스만 전진했다).

따라서 이 머신의 `auction.db` 는 **개발 DB** 다. 운영 DB 의 사본이라고 볼 근거도 없다
(사본이었다면 사용자 데이터가 남아 있었을 것이다).

**[무엇을 철회하는가]** 아래 서술은 **"데스크탑3 기준"으로 범위를 좁힌다.** 지우지 않고
남기는 것은 이 저장소의 관례대로다 — 무엇을 왜 잘못 읽었는지가 남아야 반복하지 않는다.

```
철회 대상                                     올바른 서술
--------------------------------------------  ------------------------------------------
"크롤이 2026-08-12 이후 멈춰 있다"             데스크탑3 개발 DB 의 마지막 수집일이 08-12 다.
                                              운영 크롤 상태는 이 머신에서 알 수 없다.
"예약 작업 0개 = 파이프라인이 안 돈다"          데스크탑3에 없는 것이 정상이다.
                                              운영 등록 상태는 데스크탑1에서 확인해야 한다.
"기일 미도래 0건 = 사용자에게 빈 화면(P0-A)"    개발 DB 의 값이다. 제품 화면이 비었다는
                                              근거가 아니다.
"P0-A 가 유일한 출시 차단 요소"                 **확인되지 않았다.** 데스크탑3에서는
                                              판단할 수 없는 항목이다.
"스케줄러를 등록하면 P0-A 가 닫힌다"            데스크탑3에 등록하는 것은 애초에
                                              운영 구조와 어긋난다(하면 안 된다).
```

**[유효하게 남는 것 — 범위를 좁혀도 살아 있는 결론]**

* **BUGS #196 (드라이버 조달)은 그대로 결함이다.** `webdriver_manager` 단일 경로는
  머신과 무관하게 **코드의 문제**이고, 이 머신에서 실제로 기동 실패를 재현했다.
  다만 *"스케줄러를 등록해도 첫날 밤에 죽는다"* 는 문장은 **이 머신 기준**이다 —
  데스크탑1에서 매일 크롤이 도는지, 거기서 `webdriver_manager` 가 되는지는 모른다.
  폴백을 붙인 수정은 어느 머신에서도 안전하고 유익하다(되던 곳은 그대로 되고,
  안 되던 곳은 살아난다).
* **파이프라인 정합·중복 방지·동시성 검증(#197 · #198 · #199)** 은 전부 **코드와
  합성 데이터**로 한 것이라 머신 역할과 무관하게 유효하다.
* **자산 무결성 / 인증 표면 / 응답시간** 측정은 "이 개발 DB 기준"으로 유효하다.
  운영 규모에서의 값은 다를 수 있다.

**[수정 — 판정을 선언에 묶는다]** 코드로 알 수 없으니 **선언하게 한다.**
`ALLOW_LIVE_CRAWL=1` 이 실크롤을 규약이 아니라 구조로 막는 것과 같은 방식이다.

```
DOJOONPASS_DATA_ROLE=operational   이 머신의 auction.db 가 운영 데이터다
(미선언 / 그 외)                    개발 머신 - 데이터 신선도를 제품 판정으로 쓰지 않는다
```

`test_pipeline_integrity.py` §11(데이터 신선도)이 그 선언을 본다.

```
운영으로 선언한 머신   검색 0건 -> **실패** (이빨이 그대로 남는다)
선언하지 않은 머신     숫자는 크게 찍되 실패로 만들지 않는다
                       + "역할 미선언" 을 매번 출력한다 (선언을 잊은 운영 머신이 보도록)
값이 있는데 인식 못 함  "인식하지 못했다" 를 따로 찍는다 (오타를 미선언과 뭉개지 않는다)
```

**기본값을 개발로 둔 이유**: 잘못 선언하지 않은 개발 머신이 **거짓 P0** 를 만드는 것보다,
선언을 잊은 운영 머신이 경보를 놓치는 쪽이 **눈에 띄기 쉽다**(미선언 상태를 매번 크게
찍는다). 그리고 개발 머신은 여럿이고 운영 머신은 하나다.

이 검사는 그동안 **개발 머신에서 고칠 수 없는 영구 red** 였고, 실제로 여러 세션이 그것을
"유일하게 알려진 실패"로 취급하며 지나갔다 — §11 자기 주석이 예언한 상태 그대로다:
*"코드를 고쳐서 풀 수 있는 실패가 아니다 ― 곧 무시하게 된다."*

`audit_schedule_health.py` 도 "등록되지 않은 정의"를 찍을 때 **이것은 이 머신의 상태이며
운영 크롤 머신은 다를 수 있다**는 단서를 함께 출력한다.

**[회귀 + mutation]** `test_pipeline_integrity.py` 에 §11-c
`test_data_role_gate_is_wired()` 를 신설했다(12단언). **두 방향을 모두** 고정한다 —
한쪽만 보면 다음에 또 갈라진다.

```
값 해석      operational / OPERATIONAL / 공백 포함 -> 운영
             prod / production / development / 빈값 / 미선언 -> 개발
배선(AST)    제품 판정 단언이 `is_operational_data()` 분기 **안에** 있는가
껍데기 방지  미선언 분기에도 단언이 최소 1개 남아 있는가
```

mutation 3/3 검출:

```
M1 제품 판정을 분기 밖으로 꺼낸다 (개발 머신에서 다시 거짓 P0)  -> 잡았다 (FAIL 3줄)
M2 항상 운영으로 본다                                          -> 잡았다 (FAIL 6줄)
M3 미선언 분기의 단언을 없앤다 (껍데기)                         -> 잡았다
대조군                                                         -> exit 0
```

역할별 실동작도 확인했다: 미선언 exit 0 / `operational` exit **1**(검색 0건을 잡는다) /
오타 `prod` exit 0 + "인식하지 못했다" 출력.

**[다음 세션에게 — 운영 상태가 필요할 때]** 이 머신에서 알 수 없는 것은 **추측하지 않는다.**
필요하면 셋을 **구분해서** 적는다.

```
1. 이 머신(데스크탑3)의 로컬 상태          -> "개발 DB 기준" 이라고 명시
2. Git 에 기록된 코드/설정/문서             -> 머신과 무관하게 유효
3. 과거에 확보된 운영 로그/DB 측정 결과      -> 출처와 시점을 함께 적는다
```

`logs/daily_run.log` 등 이 저장소의 로그도 **이 머신에서 돌린 흔적**이므로 운영 근거가
아니다(그리고 BUGS #192 가 밝혔듯 한동안 회귀 스위트의 합성 로그까지 섞여 있었다).

--------

#201

**검색 필터 중 날짜 두 개만 검증이 없었다** — 오타가 400 이 아니라 **조용히 0건**이 된다.
같은 폼의 숫자 필터는 즉시 거절하는데 날짜만 삼킨다

발견 (2026-08-25, 검색/상세 API 에 적대적 입력을 넣어 500 이 나는지 전수로 재다가)

**[경위]** API 적대적 입력 감사를 돌렸다(31케이스, 사본 DB). **500 도 예외도 0건**이라
그 자체로는 깨끗했는데, 표를 읽다가 한 줄이 걸렸다.

```
케이스                       상태   비고
auction_date_from 형식       200   total=0      <- 오타인데 200 이다
min_fail_count 문자          422                <- 숫자는 즉시 거절
min_appraisal 초대형         400
sort_by 임의값               400
property_type 콤마폭탄       400
page 초대형                  400
```

`api/v1/search.py` 는 나머지 필터를 **전부** 400 + 사유로 거절한다 —
`sort_by` / `sort_order` / `property_type` / min·max 숫자 6종 / `page`.
그런데 `auction_date_from` / `auction_date_to` 만 `Optional[str]` 그대로라 아무 값이나
통과하고 SQL 에서 **문자열 비교**가 된다.

**[영향]** `auction_date_from=not-a-date` -> HTTP 200 / total=0. 사용자에게 "검색 결과
없음"과 **구별되지 않는다.** 같은 화면의 같은 폼에서 나온 값인데 숫자에 오타를 내면
즉시 알려 주고 날짜에 오타를 내면 조용히 빈 결과가 온다. 이 저장소가 반복해서 잡아 온
"조용히 틀린 결과"이고, `_document_entry`(#198) 에서 쓴 말이 그대로 적용된다 —
*"오류도 빈 화면도 아니라 사용자가 원인을 알 수 없다."*

**[SQL 주입은 아니다 — 확정했다]** `auction_date_from=2026-01-01') OR 1=1--` 가
**1,875건**을 돌려주기에 주입을 의심했다. 바인딩 대조로 확정했다(2026-08-25):

```
페이로드                        API      바인딩으로 센 값   판정
정상 날짜 2026-01-01            1875     1875            일치
') OR 1=1--                    1875     1875            일치
' OR '1'='1                    1875     1875            일치
UNION SELECT                   1875     1875            일치
주석 --                        1875     1875            일치
주입이 성공했다면                                        1876 (전체) - 어느 것도 아니다
```

즉 **바인딩 파라미터**이고, 1,875 는 `'2026-07-14' >= "2026-01-01') OR 1=1--"` 같은
**사전순 비교** 결과다(전체 1,876 중 auction_date 가 빈 1행만 빠진다).
주입은 아니지만 **뜻 모를 값이 조용히 필터로 쓰이는 것**은 그대로 문제다.

**[수정 — 이웃과 같은 규약으로]** 새 규약을 만들지 않는다. 옆에 있는 여섯 개가 이미 쓰는
방식(400 + 어느 파라미터인지 + 기대 형식)을 그대로 따른다.

```python
for _name, _value in (("auction_date_from", auction_date_from),
                      ("auction_date_to", auction_date_to)):
    if not _value:
        continue          # 빈 값/미지정은 "안 걸었다"는 뜻이다(기존 계약 유지)
    try:
        datetime.strptime(_value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(400, f"{_name} 은 YYYY-MM-DD 형식이어야 합니다: {_value}")
```

형식은 프런트가 실제로 보내는 것에 맞췄다 — `<input type="date">` 의 `YYYY-MM-DD`.
`strptime` 이 `2026-13-01` / `2026-02-30` 같은 **달력상 불가능한 날짜**도 함께 걸러 준다
(정규식만으로는 못 잡는다 — 아래 M2 가 그것을 확인한다).

**[수정 후 실측]**

```
2026-01-01              200        <- 정상
not-a-date              400
2026-13-45              400        <- 달력상 불가능
2026-02-30              400
2026/01/01              400        <- 구분자
2026-01-01T00:00:00     400        <- 시각 포함
2026-01-01') OR 1=1--   400
(빈 값)                  200        <- "안 걸었다" (기존 계약 그대로)
(파라미터 미지정)         200        <- 모든 검색이 여기 해당한다
```

**[회귀 + mutation]** `test_search.py` 에 §9 를 신설했다(22단언).
거절 7종 x 파라미터 2개 + 대조군(정상/빈값/미지정) + 사유 내용 + **필터가 실제로 좁히는가**.
검증만 붙이고 기능이 죽으면 안 되므로 마지막 것을 함께 둔다.

mutation 3/3 검출:

```
M1 날짜 검증을 없앤다 (원래 버그)                    -> 잡았다 (FAIL 16줄)
M2 정규식만 쓴다 (달력 유효성을 안 본다)              -> 잡았다 (2026-13-01 / 2026-02-30 통과)
M3 `if not _value: continue` 가드를 없앤다           -> 잡았다
대조군                                              -> exit 0
```

M3 는 **가드가 load-bearing 이라는 것을 증명한다.** 없애면 `None`(파라미터 미지정)이
`strptime` 에 들어가 **모든 검색이 400** 이 된다. 실패 메시지가 그것을 그대로 보여 준다:

```
AssertionError: ({'size': 100, 'address_detail': '서울'}, 400,
                 '{"detail":"auction_date_from 은 YYYY-MM-DD 형식이어야 합니다: None"}')
```

**[프런트까지 관통 확인 — 실제 렌더]** 400 을 새로 만들었으니 화면이 그것을 어떻게
보여 주는지 **실제로 띄워서** 확인했다(dev 서버 + 임시 DB 사본의 API).

```
GET /search?auction_date_from=not-a-date   -> HTTP 200 (화면은 정상 렌더)
   "검색조건에 잘못된 값이 있습니다"                있음
   "auction_date_from"                            있음   <- 서버 사유가 그대로 보인다
   "YYYY-MM-DD"                                   있음
   "검색 결과를 불러오지 못했습니다"                없음   <- 서버 장애로 오해시키지 않는다
   검색 폼 / 돌아가는 링크                          있음   <- 되돌아갈 동선이 있다

대조군 GET /search?include_closed=true&auction_date_from=2026-01-01
   에러 문구 없음 / 결과 1,875건 정상 표기
```

프런트는 이미 400·422 를 `bad_request` 로 나누고 **서버가 준 사유를 그대로** 띄우도록
만들어져 있었다(`SearchScreen.tsx`, Sprint 162). 그래서 이번 400 메시지를 "어느
파라미터가 왜 틀렸는지"로 쓴 것이 그대로 사용자 문구가 된다 — 고정 안내문만 있으면
**엉뚱한 곳을 고치라는 안내**가 됐을 자리다.

**[같이 확인한 것 — 미검증 문자열 파라미터 전수 스윕]** 같은 계열이 더 있는지 `api/v1/`
19개 파일의 라우트 문자열 파라미터 **70개**를 AST 로 훑었다. 검증 흔적이 없어 보이는
31개를 하나씩 확인한 결과 **추가 결함은 없었다.**

```
user_id / admin_role (24개)   검증된 JWT / require_admin 의존성에서 온다 - 사용자 입력이 아니다
위임 래퍼 (2개)                head_document -> get_document,
                              admin_registry_requests -> list_registry_requests
                              (검증은 피호출부에 있다)
자유 텍스트 (get_regions.sido) 형식이 없는 값이라 "일치 없음"이 옳은 답이다.
                              날짜와 달리 오타를 구별할 근거가 없다.
```

날짜만 **형식이 정해져 있는데 검증이 없던** 유일한 자리였다.

**[같이 확인한 것 — 적대적 입력 31케이스 전수]** 이 감사에서 나온 것은 위 한 건뿐이다.

```
500 / 예외                 0건
SQL 주입                   0건 (바인딩 대조로 확정)
경로 조각(../, NUL)        전부 안전하게 0건 또는 404
초장문(5,000자) sido       200 / 0건 (지연 없음)
콤마 폭탄(500개)           400 으로 거절
size/page/숫자 초대형      422 또는 400
item id 0 / 음수 / 초대형  404
이미지 seq 음수 / 초대형    404
사본 DB                    auction_item 1,876행 / 테이블 27개 — 파괴적 입력이 통과하지 않았다
```

--------

#202

**종결 함수 넷 중 둘만 claim 을 확인했다** — 좀비 워커가 **살아 있는 실행의 큐 행을
종결**시키고, 그러면서 그 실행의 claim 토큰까지 무효로 만든다. 실제로 받아 놓은 문서가
큐에서는 "대상 아님"으로 남는다

발견 (2026-08-25, #199 를 고친 뒤 "같은 규칙이 형제 함수에도 있는가"를 훑다가)

**[경위]** #198(사진엔 있고 문서엔 없던 2차 방어선)과 #201(숫자는 검증하는데 날짜만
안 하던 것)이 **같은 렌즈**로 나왔다 — *"규칙이 한쪽에만 있는가."* 그 렌즈를 큐 종결
함수에 대 봤다.

```
함수                          claim_token 인자   _claim_is_still_ours 확인
mark_queue_done               있음               함  (BUGS #181)
mark_queue_failed             있음               함  (BUGS #181)
mark_queue_skipped_expired    **없음**           **안 함**
mark_queue_unsupported        **없음**           **안 함**
```

**[재현 — 합성 물건 하나]** (스크래치 DB, 브라우저·네트워크 없음)

```
A 가 집는다                    claim_token = T1
A 가 멈춘다 -> reset_stale_queue 가 회수 -> B 가 집는다   claim_token = T2, 큐=in_progress
좀비 A 가 mark_queue_skipped_expired() 를 부른다
    -> 큐 = SKIPPED_EXPIRED           <- B 가 작업 중인데 종결됐다
    -> last_attempt_at 이 덮인다      <- **B 의 토큰까지 무효가 된다**
B 가 수집을 끝내고 mark_queue_done(claim_token=T2)
    -> 토큰 불일치로 큐는 그대로, 문서만 기록된다
최종:  document_status = READY / doc_raw 1행 / **document_queue = SKIPPED_EXPIRED**
```

**[왜 나쁜가]**

* 실제로 받아 놓은 문서가 큐에서는 "애초에 대상이 아님"으로 남는다. 이 저장소가 스스로
  확인해 온 불변식 — *"화면이 READY 인데 큐가 done/refresh 계열이 아닌 행 0건"* — 을
  깨는 상태다(2026-08-25 개발 DB 실측 기준 지금은 0건).
* 방향도 틀렸다. 좀비가 들고 있는 것은 **그때의 낡은 `auction_date`** 다. 그 낡은 판단이
  최신 판단을 덮는다(`reconcile_queue_auction_date()` 가 막으려던 것이 바로 이 종류의
  stale 값이다).
* 두 함수가 `last_attempt_at` 을 덮으므로 **남의 claim 을 무효로 만들면서 종결까지**
  한다. 하나의 호출이 두 가지를 망가뜨린다.

**[수정]** 형제 둘과 **같은 규약**을 적용한다. 새 규약을 만들지 않는다.

```python
if not _claim_is_still_ours(conn, queue_id, claim_token):
    logger.warning("... 그 사이 큐 행(id=%s)이 회수돼 다른 실행이 집어갔다 "
                   "- 종결하지 않는다(그쪽 판단에 맡긴다)", queue_id)
    return
```

* `claim_token=None` 이면 **예전 동작 그대로**다(`_claim_is_still_ours` 가 이미 정한
  하위호환 규약). 토큰을 넘기지 않는 호출부가 깨지지 않는다.
* `doc_worker.py` 의 두 호출부가 `item.get("claim_token")` 을 넘기도록 배선했다.

**[수정 후 같은 시나리오]**

```
좀비 A 의 skipped_expired  -> 큐 = in_progress 그대로, last_attempt_at 도 그대로
B 의 done                  -> 큐 = done / document_status = READY / doc_raw 1행
```

**[회귀 + mutation]** `test_document_queue.py` 에 §19
`test_terminal_functions_respect_the_claim_token()` 을 신설했다(20단언).
**구조 + 행위 + 배선** 셋을 함께 본다 — 하나라도 빠지면 다음에 또 갈라진다.

```
구조   종결 함수 4개 전부 claim_token 을 받고 _claim_is_still_ours 로 확인하는가
행위   남의 토큰으로는 상태도 last_attempt_at 도 바뀌지 않는가
       (대조군) 자기 토큰이면 종결되는가 / 토큰 미지정은 예전대로인가
배선   doc_worker 가 두 함수에 실제로 토큰을 넘기는가
```

mutation 3/3 검출:

```
M1 skipped_expired 의 가드 제거 (원래 버그)     -> 잡았다 (FAIL 3줄, 상태 변화까지 지목)
M2 unsupported 의 가드 제거                     -> 잡았다 (FAIL 3줄)
M3 doc_worker 가 토큰을 안 넘긴다 (배선 끊기)    -> 잡았다
대조군                                          -> exit 0
```

**M2 는 처음에 행위 검사가 공허했다.** 이 파일의 스키마가 큐 전용이라
`mark_queue_unsupported` 가 `document_status` 를 쓰다 `no such table: auction_item` 으로
**죽었고**, 트랜잭션이 롤백돼 큐가 그대로였다 — 즉 가드를 없애도 행위 검사가 통과했다.
빈 스텁 테이블 셋을 만들어 `_set_document_status()` 가 설계대로 "대상 없음" 경고 + False
로 물러나게 하니 그제야 잡힌다. **mutation 을 돌리지 않았으면 이 구멍은 남았을 것이다** —
이 저장소가 반복해서 배운 것과 같다: *"가끔 밟는 것은 방어선이 아니다."*


**[같이 확인한 것 — `release_queue_rows()` 는 고치지 않는다 (재고 판단했다)]**
같은 렌즈로 보면 이 함수도 claim 을 확인하지 않는다. 좀비가 자기 옛 배치 id 로 부르면
**남이 작업 중인 행을 `pending` 으로 되돌린다.** 그런데 실제로 눌러 보니 해가 없다.

```
B 가 집는다                     큐=in_progress, token=T
좀비가 release_queue_rows([B의 행])
   -> 큐=pending  (되돌아갔다)
   -> last_attempt_at = T 그대로   <- 이 함수는 그것을 **일부러** 안 지운다
C 가 집으려 한다                 -> **집지 못한다**
   claim 조건이 `last_attempt_at <= now - 30분` 이라 아직 대상이 아니다
B 가 수집을 끝내고 done(T)       -> 토큰이 그대로라 통과
최종:  큐=done / doc_raw 1행 / document_status=READY   (정상)
```

즉 **30분 재시도 간격이 이미 막고 있다.** 그 값을 남기는 이유를 이 함수의 docstring 이
이미 적어 두었다 — *"그 값을 지우면 30분 재시도 간격이 사라져, 방금 실패한 행이 곧바로
다시 태워질 수 있다."* 그 결정이 여기서 두 번째 효과를 낸다.

그래서 **claim 검사를 넣지 않는다.** 넣어도 얻는 것이 없고, 실행 창이 닫힐 때 배치를
되돌리는 경로라 위험만 늘린다. 다음 세션이 "여기도 비대칭이다"라고 고치려 들지 않도록
근거를 남긴다 — **`last_attempt_at` 을 지우도록 바꾸면 이 보호가 사라진다.**

**[남는 것]** `mark_queue_skipped_expired` 가 `document_status` 를 건드리지 않는 것은
그대로다(Sprint 73 이 검토하고 보류한 제품 판단, `test_document_status_sync.py` §6 이
현재 동작을 고정한다). 이번 수정은 **누가 종결할 수 있는가**만 고쳤고 **무엇을 쓰는가**는
바꾸지 않았다.

--------

#203

**재수집 기계와 버전 정책 사이의 이음매가 검사되지 않았다** — 두 축을 각각 24개/여러 개
검사가 덮는데, **재수집이 실제로 돌 때 버전이 어떻게 되는지**는 아무도 안 봤다.
그리고 그것이 일상 운영 경로다

발견 (2026-08-25, "일상 크롤은 신규가 아니라 **변경**이다"를 깨닫고 그 경로를 처음 관통시켜 보다가)

**[왜 이 자리가 비어 있었나]** 지금까지의 검증은 **신규 수집**에 몰려 있었다. 그런데
데스크탑1이 매일 돌리는 크롤에서 대부분의 물건은 **이미 있는 것**이고, 바뀌는 것은 값이다
(최저가 하락 / 기일 변경 / 유찰 증가). 그 경로를 끝까지 눌러 본 적이 없었다.

```
test_refresh_trigger.py   재수집 기계(예약·claim·retry·상한·배선) 24개 검사
                          `doc_raw` 의 `doc_version` 을 보는 검사 **0개** (2026-08-25 실측)
BUGS #197 / #199          버전 규칙 자체(같은 내용 -> unchanged, 동시성)
                          재수집 경로를 거쳐 도달하는지는 보지 않는다
```

**두 축이 각각 튼튼한데 이음매만 비어 있었다.**

**[실제로 눌러 봤다 — 4일 생애주기]** 완전 합성 DB(부트스트랩 3단계) + 임시 문서 루트.

```
1일차  신규 크롤 -> upsert -> migrate_execute -> enqueue -> 수집
       auction_item 생성 / 큐 4종 pending -> spec·status·appraisal done / 화면 READY
       doc_raw 3행, 버전 1

2일차  값이 바뀐다 (최저가 350,000,000 -> 280,000,000 / 기일 이동 / 유찰 1 -> 2회)
       auction_item 이 새 값을 갖는다                                    OK
       requeue 결과: {'items': 1, 'refreshed': 2, ...}
       큐: spec=refresh / status=refresh / appraisal=done  <- 필드별 매핑이 정확하다
       화면: 셋 다 READY 유지    <- 재수집 예약이 사용자가 보던 것을 뺏지 않는다
       enqueue 를 다시 돌려도 refresh 가 pending 으로 뭉개지지 않는다      OK

2일차 재수집 실행 (법원이 실제로는 안 바꿨다 - 같은 파일)
       claim 이 overwrite=True 로 온다                                   OK
       **doc_raw 3행 그대로 / 버전 1 그대로**                            OK

3일차  아무것도 안 바뀐다 -> requeue 결과 {} / 큐 상태 그대로 (멱등)      OK

4일차  법원이 진짜로 바꿨다 -> 새 행 / 버전 2 / **옛 버전 1행 그대로 남음**
       document_version_log 1행                                          OK
```

**결함은 나오지 않았다.** 제품이 옳게 동작한다 — 그러나 **그것을 지키는 검사가 없었다.**
이 저장소의 기준으로는 그것이 결함이다(`api/v1/item.py` 가 `MAX(doc_version)` 을 사용자
응답에 싣기 때문에, 여기가 무너지면 "매일 밤 문서 버전이 오르는" 형태로 화면에 드러난다 —
BUGS #115 가 이미 한 번 겪은 모양이다).

**[회귀]** `test_refresh_trigger.py` 에 §25
`test_refresh_cycle_respects_the_version_policy()` 를 신설했다(17단언).
이 파일에서 `doc_raw`/`doc_version` 을 보는 **첫 검사**다.

```
첫 수집(pending)          행 1 / 버전 1 / 변경 이력 0 (이전 값이 없다)
재수집 + 같은 내용         행 1 / 버전 1 / 이력 0        <- 늘면 안 된다
재수집 + 바뀐 내용         행 2 / 버전 2 / 이력 1
                          **옛 버전 행이 그대로 존재**  <- 덮어쓰기가 아니라 쌓기
                          두 버전의 크기가 실제로 다르다(공허하지 않다)
화면                      재수집 내내 READY 유지
```

`collect()` 헬퍼가 `expect_overwrite` 를 **인자로** 받는다 — 첫 수집은 `pending`
(overwrite=False), 재수집은 `refresh`(overwrite=True)다. 둘을 같은 값으로 단언하면
검사가 둘 중 하나를 반드시 틀리게 만든다(처음에 실제로 그렇게 써서 붉어졌다).
그 구분이 이 파일의 핵심 어휘라 인자로 드러냈다.

mutation 3/3 검출:

```
M1 같은 내용에도 버전을 올린다 (BUGS #115 회귀)   -> 잡았다 (FAIL 6줄)
M2 버전을 쌓지 않고 1번 행을 덮어쓴다 (정책 파괴)  -> 잡았다 (FAIL 3줄)
M3 document_version_log 를 안 남긴다              -> 잡았다 (기존 검사도 함께 잡았다)
대조군                                            -> exit 0
```

M2 가 이 검사의 존재 이유다 — **바뀐 콘텐츠가 옛 데이터를 파괴하지 않는가.**
버전을 쌓는 대신 덮어쓰면 무엇이 언제 바뀌었는지 되짚을 수 없고, 그 상태는
"행 수가 그대로"라 겉으로는 정상과 구별되지 않는다.

**[기준선]** 통과 54 / 실패 0, 단언 8,392건(#202 시점 8,354 -> +38).

--------

#204

**일부러 두 벌로 둔 구현이 갈라지는 것을 막는 것이 없었다** — 그리고 회귀 스위트가
매 실행마다 컴파일 경고를 하나씩 뱉고 있었다

발견 (2026-08-25, 중복 코드 감사 — 구조가 같은 제품 함수를 AST 로 훑다가)

**[중복 감사]** 제품 함수(`api/` `storage/` `crawler/` `config/` `normalizer/` `validator/`
`models/` `intent/` + 루트 진입점 6개)의 본문을 **이름·상수를 지운 구조**로 정규화해
해시가 같은 묶음을 찾았다. 본문 4문 미만은 우연 일치라 제외했다.

```
구조가 동일한 묶음: 2개

  본문 7문  collect_documents.attach_file_log == mvp_scraper.attach_file_log
  본문 6문  crawler/base_crawler.restart_driver == crawler/doc_crawler.restart_download_driver
```

**[둘째는 결함이 아니다 — 확인했다]** `restart_*` 는 각자 자기 `build_*_driver()` 를
부르고, **그 둘 다 BUGS #196 의 `resolve_chrome_driver()` 를 탄다.** 즉 재시작 경로도
Selenium Manager 폴백을 받는다. 공유 부분은 `quit + sleep + 재생성` 6문의 상용구이고,
두 드라이버는 옵션이 다르다(다운로드 폴더 설정 — `build_download_driver` 의 docstring 이
왜 따로 있어야 하는지 적어 두었다). **묶지 않는다.**

**[첫째는 진짜 위험이다]** `attach_file_log()` 는 BUGS #192 가 **일부러 인라인**한 것이다 —
새 모듈을 만들면 미추적 파일을 추적 파일이 import 하게 되어 커밋된 트리가 부팅하지
못한다(BUGS #105). 그 판단은 지금도 옳다. 문제는 인라인이 남긴 위험이 **관리되지 않고
있었다**는 것이다: 한쪽만 고쳐지는 날.

그것이 바로 BUGS #197 이었다 — `doc_raw` 작성자 둘이 갈라져, 한쪽은 내용 지문을 비교하고
다른 쪽은 매번 버전을 올렸다. **인라인을 택했으면 갈라짐을 막는 것이 함께 와야 한다.**

**[수정 — 구조 비교 가드]** `test_schema_hygiene.py` 의 #192 검사에 붙였다.
이름·상수를 지운 AST 로 비교하므로 **로그 파일명이 달라도 통과**하고 **로직이 달라지면
실패**한다.

```
mutation: mvp_scraper 쪽에서만 setFormatter 한 줄을 지운다
   -> [FAIL] ★ 인라인한 두 구현의 구조가 같다: 2 (expected 1)
자기 검증: 다른 함수(main)는 다른 구조로 나온다  -> 통과 (비교가 공허하지 않다)
```

실패 메시지는 무엇을 하라고 말한다 — *"한쪽만 바꿨다면 다른 쪽도 같이 바꾸라. 일부러
다르게 만든 것이라면 이 검사를 갱신하고 왜 달라야 하는지를 함께 적으라."*

**[같이 고친 것 — 매 실행 나오던 컴파일 경고]** 스위트를 돌릴 때마다 이 줄이 섞여 나왔다.

```
test_asset_record_failures.py:10: SyntaxWarning: invalid escape sequence '\d'
```

원인은 모듈 docstring 안의 Windows 경로였다(`storage\database.py` 의 `\d`).
텍스트를 고치지 않고 **리터럴만 raw 로** 바꿨다(`"""` -> `r"""`).

**소음 자체가 값이다.** 매 실행 나오는 경고는 **진짜 경고가 났을 때 눈에 안 띄게** 만든다 —
이 저장소가 NO-VERDICT 분류를 따로 만든 것과 같은 취지다. 그리고 이 경고는 무해하지
않을 수도 있다:

```
(a) 문서/주석의 Windows 경로가 raw 가 아니다     -> 무해하지만 소음
(b) **정규식을 raw 문자열로 안 썼다**            -> 패턴이 조용히 달라진다
```

(b) 를 (a) 와 구분해 막을 방법이 없으므로 **둘 다 막는다.**
`test_no_python_syntax_warnings()` 를 신설해 추적 파이썬 **150개 전부**를 컴파일하고
`SyntaxWarning` 이 하나라도 나면 그 파일:줄을 지목한다(문법 오류는 다른 검사의 몫이라
건너뛴다). 자기 검증으로 일부러 만든 `"\d"` 를 잡는지 확인한다.

```
현재: 추적 .py 150개 / 컴파일 경고 **0건**
mutation: docstring 을 raw 가 아니게 되돌린다 -> 파일:줄과 함께 잡았다
```

**[기준선]** 통과 54 / 실패 0, 단언 8,398건(#203 시점 8,392 -> +6). 스위트 출력에서
`SyntaxWarning` **0건**.

--------

#205

**설정이 사라졌다고 알려 주는 경고가 정작 조용한 쪽에는 안 붙어 있었다** — 시끄러운
쪽(500)에만 붙어 있고, 사용자 전원을 막는 조용한 쪽(401/403)에는 없었다

발견 (2026-08-25, `.env` 에 admin 두 키를 새로 넣고 그 배선을 검증하다가)

**[출발점 — 검증은 전부 통과했다]** `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` 가 `.env`
에 들어왔다. 값은 어디에도 찍지 않고 행위로만 확인했다(SET/NOT_SET 만 출력).

```
적재        셸 환경만        ADMIN NOT_SET / SUPER NOT_SET
            api_server 임포트 후  ADMIN SET / SUPER SET      <- load_dotenv 가 읽는다
이름        코드가 읽는 이름과 정확히 일치(api/v1/admin.py 의 os.getenv 4곳)
ADMIN 라우트  키 없음 403 / 틀린 키 403 / ADMIN 키 200 / SUPER 키 200
SUPER 전용    키 없음 403 / ADMIN 키 403 / SUPER 키 422(인증 통과 후 본문 검증)
예전 500 의 원인  두 키를 빼면 500 재현 -> 되돌리면 200      <- 원인이 환경변수 미설정이 맞다
부팅 경고     warn_if_admin_keys_missing() 이 더 이상 경고하지 않는다
전수         admin 라우트 16개 중 키 없이 500 인 것 **0개**
```

**여기서 멈췄으면 결함을 못 봤다.** 확인하려던 것은 다 확인됐다.

**[그런데 이 키들은 반복해서 사라져 왔다]** `BETA_RELEASE_CHECKLIST.md` 의 P0-2 이력이
그 자체로 증거다 — Sprint 233 소실 -> 238 복귀 -> 244 소실 -> 267 있음 -> 08-24 소실 ->
오늘 복구. 그래서 물었다: **한쪽만** 사라지면 어떻게 되나. 재봤다.

```
                    부팅        ADMIN 라우트   SUPER 전용
둘 다 있음          조용함      200            422(통과)
SUPER 만 사라짐     **조용함**  200            **403**      <- SUPER 기능이 통째로 죽는다
ADMIN 만 사라짐     **조용함**  **403**        422          <- SUPER 키로만 접근된다
둘 다 사라짐        경고함      500            500
```

**경고가 거꾸로 붙어 있었다.** 경고를 받는 유일한 경우(둘 다 없음)는 어차피 **500** 이라
첫 호출에 드러난다. 정작 조용한 두 경우가 경고를 못 받는데, 그쪽 증상은 **403** 이다.
403 은 "권한 부족"과 구별되지 않는다 — 운영자는 설정 누락을 등급 문제로 읽는다.

원래 그렇게 만든 이유는 잡음 방지였고, 회귀 검사가 그것을 *"키가 하나라도 있으면
경고하지 않는다"* 로 **명문화까지 해 두었다.** 그 판단은 **한쪽만 사라졌을 때 무슨 일이
나는지를 재보지 않고** 내린 것이었다. 실측이 반대를 말하므로 검사를 갱신했다.

**[같은 계열이 인증에 그대로 있었다 — 그리고 더 나빴다]** 규칙대로 인접 코드를 훑었다.
`api/auth.py` 도 **둘 다** 없을 때만 500 을 낸다. 부팅 경고는 **아예 없었다.**
로컬 스텁 JWKS + 진짜 ES256 키로 재현했다(바깥으로 나가지 않는다).

```
                        ES256(현행 서명)   HS256(레거시)   부팅
둘 다 있음              200                200             무음
SUPABASE_URL 만 없음    **401**            200             무음   <- 로그인 사용자 전원
SUPABASE_JWT_SECRET 없음 200               **401**         무음
둘 다 없음              500                500             무음
```

**ES256 이 현행 서명이다**(BUGS #27 에서 Supabase 가 비대칭으로 전환했다). 그러니
`SUPABASE_URL` 하나가 비는 것만으로 **로그인한 사람 전부가 막힌다.** 그때 남는 로그는
요청마다 나오는

```
JWT 검증 실패: JWKS에서 해당 kid의 공개키를 찾지 못했습니다
```

뿐이다 — **키 회전 중 사고처럼 읽힌다.** 설정이 빠졌다는 말은 어디에도 없다.
그리고 이 설정도 실제로 사라진 적이 있다(`api/auth.py` 위쪽 주석: cwd 가 저장소 루트가
아니면 `.env` 를 못 읽어 둘 다 빈값이 됐다). 그때는 500 이라 드러났다. **한쪽만
사라지는 날에는 드러나지 않는다.**

**[수정]** 두 곳 모두 **키별로** 경고한다. 값은 절대 남기지 않는다(로그 유출이 곧
관리자 권한 유출 / 인증 우회다 — 기존 규칙 그대로).

```
api/v1/admin.py   warn_if_admin_keys_missing()    경고 1개 -> 3개(둘다/SUPER만/ADMIN만)
api/auth.py       warn_if_auth_config_missing()   신설, api_server.py 부팅에서 호출
```

각 경고는 **어느 설정이 없는지**와 **무엇이 깨지는지**(403/401/500)를 함께 적는다.
반환값은 이름 그대로 "경고를 남겼으면 True" 다.

**[회귀]** `test_admin_secret_contract.py` 38 -> 46단언,
`test_auth_jwks_robustness.py` §9 신설로 50 -> 68단언.

부분 소실은 **값 누출을 행위로 검사할 수 있는 유일한 자리**이기도 하다 — 경고가 나가는
순간 나머지 한쪽에는 실제 값이 들어 있다. (둘 다 빈 경우엔 흘릴 값 자체가 없어 그
검사가 공허했다. 2026-08-21 에 mutation 으로 확인하고 걷어냈던 바로 그 검사다.)
그래서 이제 **행위 + AST 두 겹**으로 본다.

```
mutation
  M1 전부-아니면-전무로 되돌린다            -> 잡았다 (양쪽 파일 각 4줄 FAIL)
  M2 소실된 키가 아닌 다른 이름을 지목한다  -> 잡았다
  M2' 결과(403/401)를 안 적는다             -> 잡았다
  M3 경고에 살아 있는 값을 끼워 넣는다      -> 잡았다 (행위·AST 둘 다)
  M4 부팅 배선을 지운다                     -> **처음엔 못 잡았다** (아래)
```

**[M4 가 뚫었다 — 검사 자체의 결함]** 배선 확인이 문자열 검색이었다.

```python
code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
check_true("부팅 시 호출한다", "warn_if_admin_keys_missing()" in code, ...)
```

주석 **줄**만 걸러 내므로 `pass  # warn_if_admin_keys_missing()` 같은 **꼬리 주석**이
호출로 통과한다. 배선을 죽이는 mutation 이 실제로 통과했다. AST 로 **모듈 최상위의
호출문**을 찾도록 바꿨다. 이 구멍은 admin 쪽 검사에 원래 있던 것이고 새로 쓴 auth 쪽이
그대로 물려받은 것이라 **둘 다** 고쳤다.

```
M4a 꼬리 주석으로 무력화  -> 두 파일 모두 잡았다
M4b 배선을 통째로 삭제    -> 두 파일 모두 잡았다
대조군                    -> exit 0
```

**[남는 것]** 경고는 **부팅 시점**에만 나간다. 서버가 뜬 뒤 `.env` 가 바뀌는 경우는
잡지 못한다 — 그때는 프로세스를 다시 띄워야 반영되므로(모듈 상수로 읽는다) 실질적으로는
같은 시점이다. 운영 반영 여부는 데스크탑1 몫이라 **여기서는 확인 불가**.

**[기준선]** 통과 54 / 실패 0, 단언 **8,420**건(프런트 dev 서버 없이) / **8,424**건
(서버를 띄우고 - 둘 다 실측). #204 시점의 8,398 은 서버가 떠 있던 값이라 직접 비교하면
안 된다(아래 곁가지 참고). 개발 DB·운영 로그 지문 무변경.

**[곁가지 — 기준선 숫자가 ±4 흔들린다]** #204 의 8,398 을 재현하려다 8,394 가 나와
회귀로 의심했다. 원인은 키가 아니었다: `test_beta_journey.py` 의 4단계(프런트 로그인
게이트)가 **dev 서버가 떠 있을 때만** 돈다. 없으면 `[SKIPPED]` 로 명시하고 넘어간다 —
조용히 통과시키지 않으니 동작 자체는 옳다. dev 서버를 띄우고 재실행해 62 -> 66단언,
4단언 전부 PASS 를 확인했다. **기준선 숫자를 비교할 때는 dev 서버 유무를 같이 봐야 한다.**

--------

#206

**백엔드의 현행 토큰 검증(ES256)이 프런트 전용 파일 이름에 걸려 있었다** — `.env` 만
챙겨 배포하면 로그인 사용자 전원이 401 이 된다

발견 (2026-08-25, BUGS #205 를 적고 나서 P0-4 를 재실측하다가)

**[P0-4 를 재실측하려다 나왔다]** 체크리스트의 P0-4 는 *"`.env` 에 `SUPABASE_JWT_SECRET`
없음"* 이었다. 오늘 재보니 **있다.** 그런데 같은 파일의 다른 값이 비어 있었다.

```
.env        SUPABASE_JWT_SECRET       SET
.env        SUPABASE_URL              **NOT_SET**       <- 이름은 있는데 값이 비었다
.env        NEXT_PUBLIC_SUPABASE_URL  이름 자체가 없다
.env.local  NEXT_PUBLIC_SUPABASE_URL  SET
```

`api/auth.py` 의 해석은 이렇다.

```python
SUPABASE_URL = _project_origin(os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "")
```

`.env` 쪽이 비었으므로 **`.env.local` 의 `NEXT_PUBLIC_SUPABASE_URL` 로 넘어간다.**
런타임에서는 `SUPABASE_URL` 이 SET 으로 보이니 겉으로는 아무 문제가 없다.

**[왜 위험한가]** `NEXT_PUBLIC_*` 은 이름 그대로 **프런트에 노출되는 값**이고
`.env.local` 은 프런트 개발용 파일이다. 그런데 **백엔드의 ES256(현행 서명) 검증이
거기에 걸려 있다.** 둘 다 gitignore·미추적이라 배포 대상에 사람이 직접 넣어야 하는데,
백엔드만 올리는 사람이 `.env` 만 챙기는 것은 자연스러운 선택이다.

```
git check-ignore   .env  -> 무시됨 / 추적 안 됨
                   .env.local -> 무시됨 / 추적 안 됨
```

`.env.local` 이 없는 환경을 재현했다(파일은 건드리지 않고 로더만 막았다).

```
SUPABASE_JWT_SECRET  SET
SUPABASE_URL         **NOT_SET**     <- JWKS 를 받을 곳이 없다
-> ES256 토큰 전부 401. ES256 이 현행 서명이므로 **로그인 사용자 전원.**
```

이것이 정확히 BUGS #205 가 기술한 조용한 실패다. 다행히 **#205 의 부팅 경고가 이
상황에서 실제로 뜬다** — 재현했을 때 그대로 나왔다. 어제였다면 아무 말도 없었다.

**[고칠 수 있는 것과 없는 것]** `.env` 에 `SUPABASE_URL` 을 채우는 것이 정답이지만
`.env` 변경은 **승인 영역이라 SKIP** 한다. 코드로 할 수 있는 것을 했다: **폴백에 걸려
있다는 사실 자체를 부팅 로그에 드러낸다.**

```
_SUPABASE_URL_SOURCE   URL 이 어느 이름에서 왔는지 기억한다(값이 아니라 이름이다)
부팅 로그(INFO)        폴백에서 왔을 때만 한 줄 - "SUPABASE_URL 이 아니라
                       NEXT_PUBLIC_SUPABASE_URL 에서 가져왔다"
```

**경고가 아니라 INFO 다.** 지금 상태는 장애가 아니라 **취약한 배치**다. 경고로 올리면
개발 머신에서 매 부팅마다 떠서 진짜 경고를 가린다 — BUGS #204 가 컴파일 경고를 걷어낸
것과 같은 이유다. 장애가 되는 순간(URL 이 실제로 비는 순간)은 #205 의 경고가 맡는다.

**[회귀]** `test_auth_jwks_robustness.py` §9 에 이어 붙였다(68 -> 79단언).

```
mutation
  M5 폴백 안내를 없앤다                    -> 잡았다
  M6 안내를 경고로 올린다(잡음)            -> 잡았다 (경고 호출 수 3->4 로도 걸린다)
  M7 안내에 URL 값을 끼워 넣는다           -> 잡았다
  M8 출처를 늘 SUPABASE_URL 이라 보고한다  -> **처음엔 못 잡았다**
  M9 출처를 늘 폴백이라 보고한다           -> **처음엔 못 잡았다**
```

**[M8·M9 가 뚫은 이유 — 이 머신에서는 두 분기가 같은 답을 낸다]** `.env` 의
`SUPABASE_URL` 이 비어 있으니 "폴백이 정답"인 상태다. 그래서 출처를 어떻게 보고하든
현재 환경에서는 구별되지 않았다. 환경 자체를 바꾸지 않으면 잴 수 없는 것이었다.

**환경을 바꾼 하위 프로세스**로 나머지 두 분기를 실제로 밟았다.

```
SUPABASE_URL 을 넣은 환경    -> 출처가 "SUPABASE_URL"          (M8 검출)
둘 다 없는 환경(.env 차단)   -> 출처가 ""                      (M9 검출)
```

여기서 배운 것: **검사를 현재 환경에만 걸면 분기가 하나로 접힌다.** 이 저장소가
`ALLOW_LIVE_CRAWL` / `DOJOONPASS_DATA_ROLE` 로 구조적 게이트를 세워 온 것과 같은 문제다.

**[기준선]** 통과 54 / 실패 0, 단언 **8,432**건(프런트 dev 서버 없이) / **8,436**건
(서버를 띄우고 - 둘 다 실측). #205 시점 8,420/8,424 -> +12. 개발 DB·운영 로그 지문 무변경.

**[확인 불가]** 운영(데스크탑1 / 실제 배포 대상)에 `.env` 와 `.env.local` 중 무엇이
올라가 있는지는 **여기서 알 수 없다.** 그쪽 부팅 로그에 위 INFO 한 줄이 뜨는지로
판별할 수 있다 — 뜨면 `.env.local` 에 의존하고 있다는 뜻이다.

--------

#207

**사용자 입력이 SQL 문법에 닿는 유일한 자리를 아무 검사도 지키지 않고 있었다** —
주입은 되지 않았다. 그런데 그것을 지키는 것이 없었다

발견 (2026-08-25, 코드 Audit — `execute()` 첫 인자를 AST 로 전수 훑다가)

**[전수 조사]** 제품 파이썬 92개에서 `execute()/executemany()/executescript()` 의 첫
인자가 **문자열 리터럴이 아닌** 자리를 전부 뽑았다.

```
해당 54건   BinOp(%/+) 31 / f-string 12 / 변수 11
그중 사용자 입력이 닿는 API 라우트  api/v1/{search,admin,payments,subscriptions,audit,thumbnails}.py
```

하나씩 봤다. **전부 안전한 패턴이었다.**

```
where = " AND ".join(conditions)      conditions 는 전부 리터럴, 값은 params 로 바인딩
placeholders = ",".join("?" * n)      개수만 만든다
or_clause = " OR ".join(["property_type LIKE ?"] * n)
_address_detail_condition()           전 분기가 리터럴 + ? 반환
```

조건 리스트에 리터럴이 아닌 것을 넣는 자리는 AST 로 **2건**뿐이었고 둘 다 위의
`or_clause` / `addr_sql` 이다. 즉 **텍스트 필드는 값이 SQL 이 되지 않는다.**

**[그런데 한 곳만 다르다]** 정렬이다.

```python
order_col = SORT_COLUMNS.get(sort_by)
order_dir = "ASC" if str(sort_order).lower() == "asc" else "DESC"
order_clause = f"{order_col} {order_dir}, id {order_dir}" if order_col else "..."
rows = conn.execute(f"SELECT * FROM auction_item WHERE {where} ORDER BY {order_clause} ...")
```

`ORDER BY` 에는 파라미터를 바인딩할 수 없으므로 이렇게 쓸 수밖에 없다. 방어는
`SORT_COLUMNS` 화이트리스트 + 진입부의 400 거부 두 겹이고, **지금 실제로 잘 막는다.**

실제 HTTP(uvicorn, DB 사본)로 적대 입력을 눌러 확인했다.

```
sort_by=auction_date; DROP TABLE auction_item--        400
sort_by=auction_date, (SELECT COUNT(*) FROM sqlite_master)  400
sort_by=(SELECT 1) / auction_date-- / *  / '' / id     400
sort_order=; DROP TABLE auction_item-- / ' OR 1=1--    400
텍스트 6필드 x 페이로드 5종                             200, 500 없음, 스키마 누출 없음
400 본문: 입력을 되비출 뿐 허용 컬럼 목록은 안 알려 준다
```

**[그래서 무엇이 문제인가]** `test_search.py` 142단언 중 **sort_by 적대 입력 검사가
0건**이었다. 이 API 에서 사용자 입력이 SQL 문법에 닿는 곳은 정렬 하나뿐인데,
그 하나를 지키는 검사가 없었다.

화이트리스트는 조용히 무너진다. `SORT_COLUMNS.get(sort_by, sort_by)` 처럼 "친절한"
기본값을 넣거나 진입부 검증 한 줄을 지우면 곧바로 `ORDER BY` 주입이 되는데,
**그 편집은 정상 요청을 하나도 깨뜨리지 않는다.** 이 저장소 기준으로는 그것이 결함이다
(BUGS #203 과 같은 판단 — 제품은 옳은데 그것을 지키는 검사가 없다).

**[합성 DB 로 재야 했던 이유]** 개발 머신의 DB 는 **기본 질의(종결 제외)가 0건**이다.
행이 없어서가 아니라 1,876건의 **기일이 전부 지났기 때문**이다(마지막 크롤 2026-08-12,
P0-A 맥락). 실측: 기본 0건 / `include_closed=true` 1,876건 /
`auction_date_from=2000-01-01` 1,875건.

(처음엔 이걸 "검색 결과가 0건"이라고만 적었는데 부정확했다 — 이 파일의 다른 검사들은
`include_closed=True` 를 붙여 1,876건을 본다. 그래서 그 검사들은 공허하지 않다.
실제로 세어 보니 `test_search.py` 218판정 중 "데이터 없음(검증 생략)" 통과는 **0건**이었다.)

정렬은 값이 서로 다른 행이 눈에 보여야 검증되고, 0건끼리 비교하면 주입이 통해도
통하지 않아도 똑같이 0 이라 공허해진다. 그래서 합성 행 5개를 만들어 잰다. 실제로 첫 실측에서 `total` 이 전부 `None` 으로 나와 "결과 수 불변"
단언이 아무것도 재지 않고 있었다(응답 형태도 `meta.total` 이 아니라 최상위 `total` 이었다).
그래서 정렬이 관측되는 합성 행 5개를 만들어 잰다.

**[회귀]** `test_search.py` §10 `check_sort_and_injection_are_bounded()` 신설
(142 -> 157단언).

```
(0) 합성 행이 실제로 검색된다 (5건)        <- 공허하지 않다
(1) asc/desc 가 실제로 정렬한다, 서로 다르다 <- 정렬이 무시되면 아래가 무의미해진다
    화이트리스트 8개 키가 전부 200
(2) 정렬 적대 입력 18건이 전부 400          <- 200(통과)도 500(터짐)도 아니다
(3) 400 본문이 허용 컬럼 목록을 안 흘린다
(4) 텍스트 적대 입력 18건이 200 + 0건 매치
(5) 주입 시도 뒤 테이블과 행이 그대로다
```

mutation:

```
M1 sort_by 검증 한 줄 삭제                   -> 잡았다 (18건 중 다수가 200)
M2 SORT_COLUMNS.get(sort_by, sort_by)        -> 잡았다 (200/500 이 섞여 나온다)
M4 sort_order 검증 삭제 + 그대로 SQL 에       -> 잡았다
M5 400 본문에 허용 컬럼 목록을 친절히 추가    -> 잡았다
M6 case_no 를 바인딩 대신 문자열에 끼워 넣기  -> 잡았다 (500 2건 + `' OR '1'='1` 이 5건 전부 반환)
M3 order_dir 삼항만 제거                     -> **안 잡힌다. 그리고 그게 맞다** (아래)
대조군                                       -> exit 0
```

**[M3 은 결함이 아니다 — 확인했다]** `order_dir` 삼항을 없애고 `sort_order` 를 그대로
SQL 에 넣어도 검사가 붉어지지 않는다. 진입부의 `sort_order not in ("asc","desc")` 검증이
**먼저** 막기 때문이다. 즉 M3 단독으로는 악용할 수 없다. 두 겹을 함께 걷어낸 M4 는
정확히 잡힌다 — 방어 깊이가 의도대로 동작한다는 뜻이다.

**[따라 나온 것 하나 — 검사가 엉뚱한 이유로 붉어지고 있었다]** 누출 검사가 응답이
400 인지 보지 않고 본문 전체를 훑고 있었다. M1 을 걸면 요청이 **통과(200)** 해서 정상
데이터의 컬럼명이 응답에 들어오는데, 그것을 "누출"로 오인해 붉어졌다. 잡기는 잡았지만
**이유가 틀렸다.** 전제(`code == 400`)를 먼저 단언하도록 고쳤다.

**[한 번 틀렸다가 고친 것]** 처음엔 "텍스트 적대 입력은 전부 0건"이라고 단언해서
`sido="서울' AND 1=1--"` 이 5건을 돌려주며 붉어졌다. 주입인 줄 알고 원인을 재보니
**정규화였다** — `extract_sido()` 가 부분일치라 페이로드에서 `"서울"` 을 뽑아낸다.

```
extract_sido("서울' AND 1=1--")                 -> '서울'
extract_sido("1' UNION SELECT ... --")          -> ''
extract_sido("x서울y") / ("서울대공원")           -> '서울'
```

SQL 은 여전히 `sido = ?` 로 바인딩된다. 그래서 단언을 두 주장으로 갈랐다 —
지역명을 품지 않은 페이로드는 0건이고, 정규화가 걸리는 페이로드는 **평문 `"서울"` 과
결과가 완전히 같다**(= SQL 조각이 아무 역할도 안 했다). 후자가 더 강한 증명이다.

**[기준선]** 통과 54 / 실패 0, 단언 **8,468**건(프런트 dev 서버 없이) / **8,472**건
(서버를 띄우고 - 둘 다 실측). #206 시점 8,432/8,436 -> +36. 개발 DB·운영 로그 지문 무변경.

**[계수 방식 주의]** 이 숫자는 `run_python_tests.py` 의 세는 법(`[PASS]|[OK]` 를 줄
어디서든 찾는다) 기준이다. `grep '^\[PASS'` 로 세면 **들여쓴 표시가 빠져** 더 작게
나온다(이번에 §10 을 단독 실행하며 157 로 세었는데 스위트는 218 이었다 — 회귀가
아니라 계수 차이다). 기준선을 비교할 때는 같은 방법으로 세야 한다.

--------

#208

**인덱스를 추가해도 새 DB 에서는 조용히 사라진다** — 테이블을 재작성하는 마이그레이션이
자기가 아는 목록만 다시 만들기 때문이다. 그리고 그 결과는 **로컬과 배포가 갈리는** 모양이다

발견 (2026-08-25, 성능 Audit — 인덱스 중복을 재다가 옆에서 나왔다)

**[출발은 중복이었다]** `auction_item` 인덱스가 16개다. 기계적으로 훑으니
완전 중복 4쌍 / 접두 중복 7쌍, 전체 63개 중 **9개가 지울 수 있는 것**이었다.
쓰기 비용도 재 봤다(스키마만 복제한 빈 DB 에 20,000행 INSERT).

```
현재 인덱스 전부      0.59s    33,981행/s    11.6 MB   16개
중복 제거 후          0.19s   103,960행/s     9.0 MB    9개
인덱스 없음(하한)     0.05s   420,396행/s     4.2 MB    0개
                      -> 중복 제거 시 쓰기 67.3% 단축, 파일 22.8% 감소
```

**[그런데 이건 이미 판단이 끝난 문제였다]** `test_schema_hygiene.py` §6-3
`test_no_new_duplicate_indexes()` 가 **이미** 완전 중복 4쌍을 알고 있고, 접두 중복은
*"SQLite 가 더 작은 인덱스를 고르는 편이 유리할 수 있어 의도적일 수 있다"* 며 일부러
제외해 두었다. 지우지 않는 이유도 적혀 있다 — *"쓰기도 하루 1회 배치라 비용이 무시할
수준"*.

**그 판단이 맞다.** 67% 는 커 보이지만 절대량은 20,000행에 **0.4초**다. 하루 한 번
배치에서 0.4초는 병목이 아니다. 그래서 **이 측정은 기존 결정을 뒤집지 않는다** —
절대 수치를 붙여 줄 뿐이다. 인덱스 DROP 은 운영 DB 마이그레이션이라 **승인 영역(SKIP)**
이기도 하다.

같은 것을 검사하는 가드를 하나 더 만들려다 걷어냈다. 그게 바로 이 저장소가 BUGS #204 에서
경계한 "두 벌" 이다.

**[진짜 결함은 옆에 있었다]** 중복 가드를 mutation 으로 시험하려고 `008_create_search_
indexes.sql` 에 `CREATE INDEX` 한 줄을 추가했는데 **검사가 붉어지지 않았다.** 인덱스가
안 생겼기 때문이다.

```
008 에 CREATE INDEX 한 줄 추가 -> 부트스트랩 -> 그 인덱스 **존재하지 않음**
오류도 경고도 없다
```

원인: `013_auction_item_case_id_unique.sql` 이 `auction_item` 을 **재작성**한다
(CREATE TABLE + INSERT INTO + DROP TABLE + ALTER TABLE RENAME). 그때 기존 인덱스는
전부 사라지고, **013 이 하드코딩한 16개만** 다시 만들어진다.

그러니 013 보다 앞 번호 마이그레이션에 인덱스를 넣으면 조용히 없어진다. 하필 그 파일
이름이 `create_search_indexes.sql` 이라, 검색이 느려 인덱스를 넣으려는 사람이 **가장 먼저
여는 곳**이다.

**[왜 이게 배포 위험인가]** 마이그레이션은 한 번만 돈다. 013 이 이미 적용된 운영 DB 는
013 을 다시 실행하지 않으므로, 그 뒤에 008 에 추가한 인덱스는 **운영에는 남고 새로 클론한
개발 머신에는 없다.** 같은 소스인데 스키마가 갈린다 — "여기선 되는데"가 되는 전형적인
자리다. 반대 방향(소스에 없는데 라이브 DB 에만 있는 인덱스)은 이미 겪었다:
`idx_audit_logs_admin_id` 는 어떤 소스에도 없다(§6-3 주석에 기록돼 있다).

**[수정 — 가드]** `test_schema_hygiene.py` 에
`test_declared_indexes_survive_bootstrap()` 을 신설했다.

소스(`migrate_v4_1.py` + `migrations/*.sql`)에서 `CREATE INDEX` 로 선언한 이름을 전부
모으고, **실제로 부트스트랩한 DB 에 그 이름이 있는지** 본다. 013 전용 규칙이 아니라
어떤 마이그레이션이 어떤 테이블을 재작성해도 잡힌다.

```
현재: 선언 63개 / 부트스트랩 DB 63개 / 사라진 것 0개

mutation
  M1 013 앞 번호(008)에 인덱스 추가        -> 잡았다 (파일명·테이블명까지 지목)
  M2 013 의 재생성 목록에서 하나 삭제       -> 잡았다 (migrate_v4_1.py 선언분이 사라짐)
  대조군                                   -> exit 0
```

실패 메시지가 무엇을 하라고 말한다 — *"재작성하는 마이그레이션의 CREATE INDEX 목록에도
함께 넣으라."*

**[곁가지 — 자기 검증이 같이 붉어지고 있었다]** 처음엔 자기 검증을 "사라진 목록이
프로브 하나와 **정확히 같다**"로 썼다. 그러면 진짜 결손이 있을 때 자기 검증까지 함께
붉어져 원인 줄이 두 배가 된다. "프로브가 목록에 **들어 있는가**"로 바꿨다 — 탐지기가
동작하는지만 보고, 실제 결손 판정은 위 검사에 맡긴다.

**[M2 를 걸었을 때 BOM 가드가 먼저 잡았다]** mutation 스크립트가 013 을 `utf-8-sig` 로
다시 써서 BOM 이 붙었는데, `test_crlf_blobs_are_not_rewritten_as_lf` 계열의 BOM 검사가
그걸 지목했다. 의도한 mutation 은 아니었지만 **그 가드가 살아 있다는 증거**라 적어 둔다.

**[기준선]** 통과 54 / 실패 0, 단언 8,492건(프런트 dev 서버 없이). 개발 DB·운영 로그 지문 무변경.

**[남는 것 / 승인 영역]** 중복 인덱스 9개의 실제 DROP 은 운영 DB 마이그레이션이라
여기서 하지 않는다. 위 실측(하루 0.4초)대로 **급하지 않다.** 정리한다면 013 처럼
재작성하는 마이그레이션의 목록과 `migrate_v4_1.py` 를 **함께** 고쳐야 한다 —
한쪽만 고치면 이 검사가 즉시 붉어진다(그게 이 검사의 목적이다).

--------

#209

**시크릿 비교를 `==` 로 바꿔도 테스트가 하나도 붉어지지 않았다** — 네 자리 전부.
타이밍 방어는 행위로 잡을 수 없으므로 아무도 지키지 않고 있었다

발견 (2026-08-25, Security Audit — 결제 웹훅 서명 검증을 mutation 으로 눌러 보다가)

**[출발]** 돈이 걸린 경로부터 봤다. `MockProvider.verify_webhook_signature()` 는
`PAYMENT_WEBHOOK_SECRET` 으로 HMAC-SHA256 을 만들어 헤더 값과 맞댄다. 세 가지를 걸었다.

```
M3 시크릿 없을 때 통과시킨다(fail-open)   -> 실패 6건   잘 막힌다
M2 헤더 조회를 대소문자 구분으로 바꾼다    -> 실패 1건   막힌다
M1 hmac.compare_digest 를 `==` 로 바꾼다  -> **실패 0건**
```

admin 쪽도 같았다.

```
resolve_admin_role() 의 compare_digest 둘을 `==` 로
  test_admin_secret_contract   실패 0건
  test_api_regression          실패 0건
  test_schema_hygiene          실패 0건
```

`compare_digest` 를 쓰는 자리는 저장소 전체에 **네 곳**이고(admin 2 + payment 1 + 주석 1),
**전부 무방비**였다.

**[왜 행위로 못 잡나]** `==` 로 바꿔도 **응답이 완전히 같다.** 달라지는 것은 걸리는
시간뿐이고, 그 차이는 단위 테스트에서 안정적으로 측정되지 않는다(마이크로초 단위,
GC·스케줄러 잡음에 묻힌다). 타이밍을 재는 테스트를 쓰면 느린 CI 에서 흔들려 신호가 죽는다.

그래서 **구조로 본다.** 이 저장소가 "경고 인자에 시크릿 값을 넣지 않는가"를 AST 로 보는
것과 같은 방식이다(BUGS #205).

**[아이러니]** `api/v1/admin.py` 의 docstring 이 왜 상수 시간이어야 하는지 이미 적어
두고 있었다 — *"단순 `!=`는 앞에서부터 다르면 즉시 반환되어 비교 시간이 일치하는 접두
길이에 비례하는 타이밍 사이드채널이 된다."* **판단은 옳았고 그것을 지키는 것이 없었다.**
BUGS #207 과 같은 모양이다.

**[수정 — 가드]** `test_schema_hygiene.py` 에
`test_secret_comparisons_are_constant_time()` 을 신설했다. 두 겹이다.

```
(1) 아는 자리가 여전히 compare_digest 를 쓰는가
    api/v1/admin.py                resolve_admin_role
    api/v1/payment_providers.py    MockProvider.verify_webhook_signature
    + 시크릿에서 온 지역 이름을 `==` 로 맞대지 않는가 (줄 번호까지 지목한다)

(2) 시크릿을 **비교하는** 함수가 새로 생겼는데 목록에 없지는 않은가
```

```
mutation
  M1 payment 의 compare_digest 제거   -> 잡았다 (줄 196, `expected`)
  M2 admin 의 compare_digest 둘 제거  -> 잡았다 (줄 94 `super_key`, 줄 97 `admin_key`)
  M3 목록에 없는 새 대조 함수 추가     -> 잡았다 (이름을 지목)
  대조군                              -> exit 0
```

**[가드 자체에 오탐이 둘 있었고 고쳤다]** 처음 판이 붉게 나왔는데 **제품이 아니라 검사가
틀린 것**이었다.

```
(a) find_fn 이 ast.walk 로 이름만 찾아 **기반 클래스 스텁**을 먼저 집었다
    -> PaymentProvider.verify_webhook_signature 는 항상 False 를 돌려주는 자리라
       compare_digest 가 없다. 목록에 **클래스까지** 적고 점 표기를 해석하게 고쳤다.

(b) "시크릿 env 를 읽고 비교문이 있으면 대조 함수"로 판정해 `_require_role()` 을 물었다
    -> 거긴 `if not os.getenv(...) and not os.getenv(...)` 로 **설정 여부만** 본다.
       "compare_digest 를 쓰거나 시크릿에서 온 이름을 `==` 로 맞대는" 함수만 세도록 좁혔다.
```

(b) 는 중요한 구분이다 — **존재 확인은 대조가 아니다.** 그걸 뭉뚱그리면 가드가 매번
붉어져 결국 꺼지게 된다.

**[적용 범위]** `KGInicisProvider` / `TossProvider` 는 아직 `NotImplementedError` 스텁이라
대상이 없다. 실연동이 들어오는 순간 (2) 가 그 함수를 지목한다 — 서명 검증을 새로 쓰면서
`==` 를 쓰면 즉시 붉어진다. 결제 실연동은 승인 영역이므로 여기서는 그 자리만 마련해 둔다.

**[기준선]** 통과 54 / 실패 0, 단언 8,501건(프런트 dev 서버 없이). 개발 DB·운영 로그 지문 무변경.

--------

#210

**상세 화면의 "늦은 응답이 화면을 덮지 않게" 하는 방어를 아무 테스트도 참조하지 않았다** —
소스에 가드가 9곳 있는데 `grep -rn idRef tests/ test_*.py` 결과가 0건이었다

발견 (2026-08-25, Frontend Audit — 응답 경합 보호를 전수로 훑다가)

**[훑은 방법]** `src/**/*.ts(x)` 에서 **비동기 결과로 화면 상태를 바꾸는 useEffect** 를
전부 뽑고, 각 블록에 경합 가드가 있는지 봤다.

```
비동기 결과로 setState 하는 useEffect  9곳
가드가 보이지 않는 곳                   6곳   <- 처음 판정
```

여섯 곳을 하나씩 확인했다. **전부 실제로는 안전했다.**

```
favorites / mypage / recent   deps=[router]  -> 사실상 마운트 1회. 재실행이 없으니 경합이 없다
SearchPresets                 deps=[]        -> 마운트 1회
properties/[id]:308           키 맵에 쓴다   -> 늦게 와도 **자기 키에만** 쓴다(구조적으로 안전)
properties/[id]:319           deps=[id]      -> `idRef` 관용구로 await 마다 끊는다
```

마지막이 핵심이다. 상세는 이전/다음 이동이 **같은 라우트의 파라미터 전환**이라
컴포넌트가 재마운트되지 않는다. A 를 요청하고 곧바로 B 로 넘어가면 A 의 응답이 나중에
도착해 **B 화면을 덮을 수 있다.** 그러면 화면에 "다른 물건의 상세"가 그대로 보인다 —
오류도 로딩도 아니라서 **사용자는 그게 틀린 줄 모른다.**

소스는 그 방어를 이미 갖고 있었다. `const requestId = id` 를 잡고 **모든 await 뒤에**
`if (idRef.current !== requestId) return` 으로 끊는다. 주석까지 정확하다.

**[그런데 그 방어를 지키는 것이 없었다]**

```
소스의 idRef 가드                     9곳
tests/ + test_*.py 에서 idRef 참조     **0건**
```

한 줄만 지워도 아무도 모른다. BUGS #209(상수시간 비교)와 정확히 같은 모양이다 —
**판단은 옳았고 그것을 지키는 것이 없었다.**

**[왜 소스 계약인가]** 경합은 `node --test` 에서 재현할 수 없다 — React 렌더러도 DOM 도
없고, 타이밍을 만들어도 흔들린다. 이 저장소는 이미 같은 자리에서 같은 선택을 했다
(`src/proxy.ts` 의 존재·규약을 소스로 고정한 `tests/source-contract.test.mjs`).

**[수정]** `tests/source-contract.test.mjs` 에 3검사를 신설했다.

```
1. idRef = useRef(id) 가 있고, id 가 바뀔 때 idRef.current 가 따라간다   (기준점)
2. ★ requestId 를 잡은 함수 안에서, await 뒤 가드를 지나지 않고
   화면 상태를 바꾸는 자리가 하나도 없다                                (본 검사)
3. 가드를 전부 지운 사본에 같은 판정을 돌리면 잡힌다                     (자기 검증)
```

```
mutation
  M1 가드 한 줄 삭제(347행)              -> 잡았다. "348: setAccessToken(token)" 을 지목
  M2 idRef.current = id 를 주석 처리      -> 잡았다
  M3 useRef(id) -> useRef(null)          -> 잡았다
  대조군                                  -> 41 pass / 0 fail
```

**[처음 판이 오탐 셋을 냈다 — 검사 쪽이 틀렸다]**

```
387 setAccessToken       requireToken() 안이다 - requestId 를 잡지 않는 별개 함수
407 setRegistryErrorCode performRegistryRequest() 안 - 마찬가지
554 setAccessToken       `if (idRef.current === requestId) setAccessToken(...)` - 이미 가드다
```

원인 둘: **고정 120줄**을 훑어 뒤따르는 함수까지 끌어온 것, 그리고 가드를 `!==` 형태로만
인정한 것. 중괄호 깊이로 **선언한 함수 안에서만** 보게 하고, `===` 형태도 가드로 인정하게
고쳤다.

**[더 중요한 것 — 판정 로직을 두 벌로 썼다가 갈라졌다]** 본 검사와 자기 검증이 각자
스캔을 구현했는데, 한쪽은 `split('\n')` 이라 줄 끝에 `\r` 이 남았다(이 파일은 CRLF 다).
그 탓에 **자기 검증만 엉뚱하게 붉어져** 한참을 헤맸다. BUGS #204 가 경계한 바로 그
"두 벌" 이다. `unguardedWrites(source)` 하나로 합치고 `split(/\r?\n/)` 으로 통일했다.

**[따라 나온 것 — 편집 도구가 파일에 제어문자를 남겼다]** 정규식에 `\b` 를 넣으려던
패치가 **실제 백스페이스 문자(0x08)** 를 파일에 써 넣어 검사가 조용히 틀렸다.
그 바이트를 걷어내고, **추적 파일 전체**를 훑어 텍스트 파일에 제어문자가 없음을 확인했다
(걸린 10개는 전부 바이너리 — `auction.db.backup_*` 9개와 `favicon.ico`).

**[결함이 아니라고 판정한 것]** `performRegistryRequest()` 계열(등기부 신청/구독)은
`requestId` 를 잡지 않는다. 사용자가 버튼을 누른 직후 다른 물건으로 넘어가면 그 결과
문구가 새 물건 화면에 잠깐 뜰 수 있다. 다만 (a) 사용자가 방금 스스로 시작한 동작이고,
(b) `[id]` 효과가 물건이 바뀔 때 `setRegistryMessage(null)` 로 초기화하며,
(c) 다음 요청 시작 시에도 다시 비운다. **데이터가 아니라 안내 문구**라 지금 고치지
않는다 — 대신 여기 적어 다음에 다시 판단할 수 있게 한다.

**[기준선]** 통과 54 / 실패 0, 단언 8,505건(프런트 dev 서버 있음).
node --test 194건 / 190 pass / 0 fail / 4 skip. tsc·eslint·build exit 0.
개발 DB·운영 로그 지문 무변경.

--------

#211

**`doc_raw` 가 0행이었다 — READY 문서 555건 전부가 쪽수/크기/버전이 null 이었고,
migration 020 은 이 DB 에 적용된 적이 없었다** (둘 다 문서는 "해소됨"이라 적고 있었다)

발견 (2026-08-25, 집 PC 실 DB 실측 — 파이썬 스위트 58개 중 7개가 붉었다)

**[어떻게 드러났나]** Audit 을 돌린 것이 아니라 **스위트를 그냥 돌렸더니** 7개가 실패했다.
직전 세션(#210)의 기준선은 "통과 54 / 실패 0" 이었다. 그 사이 이 머신에서 크롤이 실제로
돌았고(`crawl_date` 2026-08-25, 262건 신규), **실 DB 를 재는 검사들이 그 변화에 반응했다.**
가드가 제 일을 한 것이다.

```
실패 7건의 뿌리는 사실 3개였다

  migration 020 미적용 (auction_image 테이블 없음)   -> test_schema_hygiene
                                                       test_audit_selftests
                                                       test_http_conditional
  .env 에 SUPABASE_JWT_SECRET 변수 자체가 없음        -> test_auth_jwt
                                                       test_search
  체크리스트 P0-A 판정이 실측과 반대                   -> test_pipeline_integrity
  sqlite_stat1 (ANALYZE 산물)                        -> test_bootstrap
```

**[1] `doc_raw` 0행 — 화면은 문서를 열 수 있는데 쪽수를 모른다**

`audit_asset_integrity.py` 를 돌리자 [4-b] 가 **555건**을 지목했다.

```
document_status READY      555          <- 파일도 전부 실재한다 (모자란 것 0건)
doc_raw                      0행        <- 그 실체 정보가 통째로 없다
```

`GET /api/v1/item/{id}` 의 `documents[].page_count` / `file_size` / `doc_version` 이
**전부 null** 이었다. 상세페이지 문서 뷰어는 전체 쪽수를 모르면 페이지 이동 UI 를 그릴 수
없다. 즉 **열람은 되는데 몇 쪽짜리인지 알 수 없는** 상태가 555건 전부에 걸려 있었다.

원인은 Sprint 144 가 이미 적어 둔 그대로다 — `doc_raw` 에 쓰는 코드가
`collect_documents.py:save_doc_raw()` 한 곳에만 있었고 **그 스크립트를 부르는 것이 없었다.**
실제로 도는 경로는 `doc_worker.py -> mark_queue_done()` 인데 거기에 기록이 없었다.
Sprint 144 가 `mark_queue_done()` 을 고쳤지만 그것은 **앞으로 받을 문서**에만 적용된다.
이미 받아 둔 555건을 위해 `backfill_doc_raw.py` 가 그때 만들어졌는데 — **한 번도
`--apply` 로 실행된 적이 없었다.**

```
backfill_doc_raw.py --apply
  document_status READY      555
  이미 doc_raw 에 있음         0
  READY 인데 파일이 없다        0        <- 하나도 없다. 전부 실재한다
  기록                       555행 (그중 page_count 확보 394행)
```

`page_count` 가 394/555 인 것은 결함이 아니다 — 나머지 161 은 `status.json`/`status.html`
이라 애초에 PDF 쪽수 개념이 없다(SPEC 197 + APPRAISAL 197 = 394 가 PDF).

검증은 화면이 읽는 그 경로로 했다.

```
GET /api/v1/item/54
  SPEC       READY  avail=True  pages=3   size=406093    ver=1     (백필 전: 전부 null)
  STATUS     READY  avail=True  pages=-   size=45747     ver=1
  APPRAISAL  READY  avail=True  pages=37  size=9773896   ver=1
```

**[2] migration 020 은 이 DB 에 적용된 적이 없다 — 문서 3곳이 반대로 적고 있었다**

`docs/CLAUDE.md` 는 "020 은 08-17 에 적용됐다 / `auction_image` 45행 / `doc_raw` 556행"
이라 적고, 그와 다르게 잰 세션을 **"백업 파일을 잰 오측"** 이라고 결론지었다.
2026-08-25 에 `storage.database.DB_PATH` 를 **경유해서** 다시 쟀더니 그 "오측"이 사실이었다.

```
항목                     CLAUDE.md 가 "운영 DB" 라 적은 값   2026-08-25 실측
migration_history 최신     020 (08-17 적용)                 **019**
auction_image             있다, 45행                       **테이블 자체가 없다**
doc_raw                   556행                            **0행**
READY 중 doc_raw 없음      0건                              **555건**
```

즉 경로를 경유하느냐의 문제가 아니었다. 그 절이 "백업을 잰 탓"으로 돌린 것이 **오히려
오진**이었다. 020 은 `CREATE TABLE/INDEX IF NOT EXISTS` 뿐이라(그 파일 자신의 헤더가
"기존 데이터에 무손실, 재실행 안전"이라 적고 있다) 적용했다. 적용 전후 행수 전부 동일:
`auction_item` 2,444 / `document_queue` 6,033 / `document_status` 7,332 / `auction_case` 1,796.

**[3] 감사기의 자기 검증이 공허했다 — 운영 데이터의 우연에 기대고 있었다**

`audit_asset_integrity.py --selftest` 의 "결함 A"(DB 에는 있는데 파일이 없는 사진 행)
주입이 이렇게 돼 있었다.

```sql
INSERT INTO auction_image (...) SELECT item_id, 9999, ... FROM auction_image LIMIT 1
                                                          ^^^^^^^^^^^^^^^^^^^^^^^^^
```

**사진이 이미 수집돼 있어야만 결함을 심을 수 있다.** `auction_image` 가 0행이면 INSERT 가
0행을 쓰고, `audit_images()` 는 당연히 0 을 돌려주며, 검사는 "감사기가 눈이 멀었다"가
아니라 **아무것도 심지 못했다**는 이유로 붉어진다. 020 미적용 상태에서는 아예
`no such table: auction_image` 로 죽었다.

이 파일의 존재 이유가 *"감사기가 눈이 멀어도 아무도 모르는 상태"* 를 막는 것인데 그
자기 검증이 운영 데이터의 내용에 묶여 있었다. 사진 수집은 승인 영역(데스크탑1)이라 이
머신에서는 영원히 채워지지 않는다. **`auction_item` 에서 씨앗을 가져오도록** 고치고,
"심을 물건이 있다(검사가 공허하지 않다)" 를 별도 단언으로 세웠다.

**[4] `sqlite_stat1` 이 부트스트랩 대조를 영구히 붉게 만들고 있었다**

`test_bootstrap` 의 "운영에만 있고 부트스트랩으로는 못 만드는 테이블" 대조가
`sqlite_stat1` 을 지목했다. 이것은 **ANALYZE 가 만드는 통계 테이블**이라 부트스트랩이
만들 이유가 없고 따라서 **고칠 수 없는 이유로 영원히 붉다.** 바로 옆 줄이 같은 이유로
`sqlite_sequence` 를 이미 빼고 있었다 — 규칙을 `sqlite_` 접두사(= SQLite 예약 이름)
하나로 넓혔다. 그 상태를 방치하면 이 검사가 **잡아야 할 진짜 스키마 누락**이 그 옆에 묻힌다.

**[결과]**

```
audit_asset_integrity.py   어긋남 581건 -> **26건**
  [4-b] READY 인데 doc_raw 없음      555 -> 0
  [9]  API 가 광고한 자산 URL        확인 못 함 -> **문서 URL 555개 / 열리지 않음 0개**
  남은 26 = 큐refresh/화면READY 17(재수집 대기, 정상) + downloads 고아 7 + 고아 디렉터리 1 + 1

파이썬 스위트  통과 47 / 실패 7  ->  **통과 52 / 실패 2**
  남은 2건(test_auth_jwt, test_search)은 **둘 다 `.env` 의 SUPABASE_JWT_SECRET 미설정**이다.
  `.env` 는 승인 영역이라 손대지 않았다 (ADMIN_API_KEY / SUPER_ADMIN_API_KEY 는 설정돼 있다).
node --test 194건 / 193 pass / 0 fail / 1 skip. tsc 0 / eslint 0 / next build 0.
개발 DB 의 크롤링 데이터는 한 행도 지우거나 덮어쓰지 않았다(백업 2개 선취득).
```

--------

#212

**스키마 드리프트 4종을 전부 닫았다 — fresh clone 과 라이브 DB 가 이제 완전히 같다**
(중복 인덱스 5쌍 / 라이브에만 없던 인덱스 5개 / 컬럼 제약 4건 / court_code NOT NULL)

발견·수정 (2026-08-26, migration 021~024)

**[뿌리는 하나였다]** `test_bootstrap.py` 가 알려진 격차로 들고 있던 목록
(`KNOWN_FRESH_ONLY_*` / `KNOWN_LIVE_ONLY_*`)과 `test_schema_hygiene.py` 의
`KNOWN_DUPLICATE_INDEXES` 는 **서로 다른 증상의 같은 원인**이었다 —
*"이미 적용된 마이그레이션을 나중에 편집했다"* 와 *"서로 모르는 두 계통이 각자 만들었다"*.

```
021  완전 중복 인덱스 5쌍에서 한쪽씩 제거      (idx_ai_* / idx_minimum_bid_price / idx_rs_item_id
                                              / idx_audit_logs_admin_id)
022  소스는 선언하는데 라이브에만 없던 인덱스 5개 채움  (014/015 를 적용 후 편집한 결과)
023  컬럼 제약 4건 정렬                        (payment_webhooks.raw_payload NOT NULL 등)
024  auction_case.court_code NOT NULL          ★ 유일하게 **소스를 라이브에 맞춘** 항목
```

**[021 — 왜 지금 지웠나. Sprint 100 은 일부러 미뤘었다]**

그때 사유는 *"현재 규모에서 API p95 가 3.1ms 이하라 병목이 없고, 인덱스 DROP 은
스키마 변경이라 **이득 없이 위험만** 만든다"* 였다. 그 판단은 그때 옳았다.
바뀐 것은 하나다 — **이득을 실제로 쟀다.**

```
합성 500,000행에서 5쌍만 제거
  인덱스 생성      3,706ms -> 3,026ms   (18.4% 단축)
  DB 파일          333.4MB -> 298.5MB   (10.5%, 34.9MB)
  API 쿼리 9종     실행계획 **전부 SAME** / 지연 -2.3%~+3.9%(잡음)
실 DB(2,444행)
  INSERT 5,000행     47.5ms -> 40.8ms   (14.2%)
```

계획이 전부 SAME 인 이유는 단순하다 — 남는 쪽이 **열 구성이 완전히 같아** 플래너가
그냥 대체재로 쓴다.

**[★ 그런데 접두(prefix) 중복은 지우면 안 된다 — 하마터면 5배 느리게 만들 뻔했다]**

처음 후보에는 접두 중복(`idx_ai_sido` ⊂ `idx_auction_item_sido_sigungu` ⊂ `idx_search_main`,
`idx_auction_item_fail_count` ⊂ `idx_fail_count_date` 등)도 넣었다.
**2,444행에서 재니 전부 괜찮아 보였다.**

```
2,444행    sido 검색  0.184ms -> 0.214ms   "차이 없음"
500,000행  sido 검색  38.10ms -> 243.69ms  **+540%**
           COUNT(sido=?)  2.05ms -> 4.45ms  (+117%)
           COUNT(fail>=?) 3.22ms -> 4.75ms  (+ 48%)
```

원인은 **커버링 인덱스의 폭**이다. 좁은 인덱스는 엔트리가 작아 같은 범위를 훑어도 읽는
페이지가 훨씬 적다. 넓은 인덱스로 대체하면 답은 같지만 I/O 가 는다.
**"접두니까 중복"은 점 조회에서만 맞고 범위·커버링 스캔에서는 틀리다.**

작은 개발 DB 만 재고 접두 인덱스를 지웠다면 규모가 커진 뒤에야 드러났을 것이다.
021 주석과 `migrate_v4_1.py` 에 그 함정을 남겨 뒀다.

**[024 만 방향이 반대다]** `auction_case.court_code` 는 소스가 nullable, 라이브가 NOT NULL
이었다. 여기서는 **라이브가 옳다** — 이 열은 `UNIQUE(court_code, case_no)` 의 앞자리인데
SQLite 는 UNIQUE 안에서 **NULL 을 서로 다른 값으로 본다.** nullable 이면
`(NULL,'2024타경1097')` 두 행이 제약을 그냥 통과한다. 011 이 그 UNIQUE 를 만든 이유
(*"법원마다 사건번호를 독립 채번하므로 사건번호만으로는 물건이 소실된다"*)가 통째로
무력해진다. 그래서 소스를 라이브에 맞췄다.

**[검증]** 재작성 4개(payment_webhooks / registry_credits / registry_credit_logs /
auction_case)는 전부 **사본에 합성 행을 심어** 먼저 확인했다.

```
auction_case  1,796행 -> 1,796행,  id min/max/sum 완전 동일
              auction_item -> auction_case JOIN  2,444 -> 2,444  (사건 연결 무손실)
              NOT NULL 실제 작동 확인(NULL INSERT 가 IntegrityError)
payment_webhooks  id 보존 / raw_payload NULL -> '{}' 승격 / 재실행 안전
```

**[결과]** fresh bootstrap 과 라이브 스키마를 전수 대조:
**테이블 26/26, 인덱스 60/60, 컬럼 정의 차이 0.** 알려진-격차 목록 4개가 전부 빈 집합이 됐다.

--------

#213

**검색 폼의 면적 필터가 아무 일도 하지 않고 있었다 — 이제 동작한다** (커버리지 99.3%)

발견·수정 (2026-08-26)

**[증상]** `SearchForm.tsx` 는 `min_building_area` / `max_building_area` /
`min_land_area` / `max_land_area` 를 **URL 에 싣고 있었는데** `api/v1/search.py` 가
그 이름을 받지 않았다. FastAPI 는 모르는 쿼리 파라미터를 **오류 없이 버린다** —
즉 면적을 좁혀도 결과가 그대로다. 소스에는 `TODO(API 미지원)` 이 붙어 있었고
검사 셋(`source-contract.test.mjs` / `test_search.py` / `test_schema_hygiene.py`)이
그 사실을 각자 고정하고 있었다.

**[정정 — 사용자 영향은 처음 생각보다 좁았다]** "사용자가 면적을 넣으면 조용히
무시된다"고 적으려다 화면을 확인했더니, 프런트의 '면적 조건' 섹션은 입력이 아니라
**"준비 중입니다"** 였다(`test_schema_hygiene.py` 가 그 사실까지 고정하고 있었다).
즉 URL 을 직접 만들지 않는 한 도달하지 않았다. **미구현이지 오작동은 아니었다.**

**[데이터가 이미 있었다]** 면적은 `full_address` 원문의 대괄호에 규칙적으로 적혀 있다.

```
대괄호 첫 토큰   집합건물 1,391 / 토지 974 / 건물 64 / 차량·선박 등 15
㎡ 표기가 있는 행  2,416 / 2,444 (98.9%)
토지와 건물 대괄호를 **동시에** 가진 행  0      <- 갈래가 겹치지 않는다
```

**[구현]**

```
normalizer.extract_areas()   순수 함수. 주소 원문 -> {building_area, land_area}
migration 025                auction_item 에 REAL 컬럼 2개 + 인덱스 2개 (ADD COLUMN, 무손실)
backfill_area.py             기존 2,428행 채움 (dry-run 기본, --apply 필요)
api/v1/search.py             WHERE 절 4개 + 응답에 두 키 노출
api/v1/item.py               상세에도 같은 키 (목록에서 걸러 들어왔는데 상세에 없으면 확인 불가)
migrate_execute.py           앞으로 들어오는 행은 INSERT/UPDATE 때 자동으로 채워진다
SearchForm.tsx               '준비 중입니다' -> 실제 RangeSelect 입력 2개
```

```
추출 결과   건물만 1,454(59.5%) / 토지만 974(39.9%) / 없음 16(0.7%)   커버리지 **99.3%**
없는 16행은 전부 차량·선박·건설기계다 — 면적 개념이 자체가 없다
```

**[규칙에서 조심한 것 셋]**

```
다층 건물   [건물 ... 1층 75.60㎡ 2층 70.20㎡]  -> **합**(연면적) 145.80
평 표기     [토지 전 1048평]                    -> ㎡ 환산 (1평=3.3057851㎡)
★ 대지권    [집합건물 74.5482㎡ 대지권의 표시 ... 대 500㎡ 대지권 비율 : 500분의 21.7849]
            -> 건물 74.5482 만 쓰고 **토지는 None 으로 둔다**
```

마지막이 핵심이다. 처음 판은 대지권 뒤의 `500㎡` 를 토지면적으로 넣었다. **틀렸다** —
그 500㎡ 는 **필지 전체**이고 이 물건의 몫은 비율(21.7849/500)이라 그대로 쓰면
**23배 부풀려진다.** 비율을 곱해 계산할 수도 있지만 표기 형태가 하나뿐이라(실데이터 1행)
일반화할 근거가 없다. **틀린 값보다 없는 값이 낫다.**

같은 이유로 값이 없으면 **0 이 아니라 NULL** 이다. 0 으로 채우면 "면적 0㎡ 인 물건"이
되어 `min_building_area=0` 검색에 걸린다. SQLite 에서 `NULL >= 30` 은 참이 아니므로
면적 미상 물건은 면적 조건을 주는 순간 자연히 빠진다 — 그것이 옳다.

**[UI 구간값도 추측하지 않았다]** RangeSelect 옵션을 실데이터 분위수에서 잡았다.

```
건물  p10 21 / p25 30 / p50 49 / p75 84 / p90 151 / p95 294 / p99 1,057
토지  p10 151 / p25 330 / p50 870 / p75 2,766 / p90 8,382 / p95 18,540
```

구간이 데이터와 어긋나면 어느 구간을 골라도 결과가 비거나 전부 나온다.

**[검증]**

```
실 API   건물 30㎡+ 1,054건 / 건물 30~60 497 / 건물 1000+ 16
         토지 500+ 629 / 토지 100~300 169 / 건물+토지 동시 0(실제로 겹치는 행이 없다)
         전부 반환 행이 조건을 지키는 것까지 확인. 0.13~0.30ms, 인덱스 사용
mutation M1 min_building_area WHERE 절 삭제 -> 잡았다("선언만 돼 있고 거르지 않는다")
         M2 extract_areas 가 항상 None      -> 잡았다(9건 실패)
         M3 '면적 조건' 을 다시 '준비 중' 으로 -> 잡았다(신설 가드)
단위     test_normalizer.py 에 13케이스 + 계약 3건 추가(대지권·평·0㎡·빈 입력 포함)
```

**[검사 목록 세 벌을 함께 정리했다]** 미지원 목록이 `source-contract.test.mjs`,
`test_search.py`, `test_schema_hygiene.py` **세 곳**에 있었다(하나는 다른 하나를 읽고,
나머지 둘은 각자 하드코딩). 셋 다 갱신했고, `test_schema_hygiene.py` 에는 반대 방향
가드를 신설했다 — **'면적 조건' 이 다시 '준비 중' 으로 돌아가면 실패한다.**
백엔드는 받는데 화면에서 넣을 수 없는 상태를 막는다.

**[남긴 것]** `special_conditions` 는 그대로 미지원이다. 면적과 결정적으로 다르다 —
`auction_item` 에도 `rights_summary` 에도 대응 데이터가 없어 **뽑아낼 원천이 없다**
(`rights_summary` 는 161행, 6.6% 뿐이다).

**[기준선]** 통과 54 / 실패 0, 단언 9,302건. node 194건 / 193 pass / 0 fail / 1 skip.
tsc 0 / eslint 0. 크롤링 데이터 무변경(auction_item 2,444 / queue 6,033 / status 7,332).

--------

#214

**주소 정규화가 대괄호(물건 표시) 안까지 훑어 "갑구"를 시군구로 읽었다** —
그리고 그와 별개로 **일반구가 빠진 행 167건이 구 단위 검색에서 통째로 누락되고 있었다**

발견 (2026-08-26, 지역 데이터 감사 — `detect_stale_region_contamination_dryrun.py` 를
돌리다가 그 도구 **자체의 사각지대**를 발견한 데서 시작했다)

**[시작 — 감사 도구가 1건만 잡았다]**

```
detect_stale_region_contamination_dryrun.py  ->  오염 의심 1건
   id=357  sigungu='칠곡군' 인데 주소는 "세종특별자치시 나성로 96 ..."
```

그 도구의 판정은 *"저장값이 주소 원문에 없으면 오염"* 이다. 합리적이지만 **원문에
우연히 들어 있는 값은 전부 통과시킨다.** 정규화기와 직접 대조해 전수로 다시 셌더니
숫자가 달랐다.

```
                     감사 도구    정규화기 대조(전수)
sido 불일치              0건            **4건**
sigungu 불일치           1건          **167건**
```

**[사각지대에 있던 것들 — 셋 다 원문에 값이 "있어서" 통과했다]**

```
id=9977   sido='세종'  인데 주소는 "제주특별자치도 제주시 구좌읍 세화리 산29"
          -> 제주 물건이 세종으로 검색된다. '제주시' 가 원문에 있어 도구는 통과시켰다
id=8160   sido='서울'  인데 주소는 "경기도 시흥시 **서울대학로** 59-21"
id=11903  sido='서울'  인데 주소는 "경기도 성남시 분당구 ... **서울시니어스분당타워**"
          -> 옛 정규화기가 **건물명/도로명 속 '서울'** 을 시도로 집은 흔적이다
id=1768   sigungu='갑구'  주소는 "세종특별자치시 전의면 관정리 578-31
              [토지 임야 297㎡ **갑구** 2번, 3번 공유자 ...]"
id=11923  같은 모양
```

**[★ 결함 1 — 정규화기가 지금도 '갑구' 를 만든다]**

앞의 넷은 옛 버전이 남긴 **낡은 값**이라 다시 정규화하면 고쳐진다. 그런데 '갑구' 두 건은
**현재 정규화기를 돌려도 똑같이 '갑구'** 가 나왔다. 즉 살아 있는 결함이다.

```python
remainder = address                       # 대괄호까지 포함한 원문 전체
re.search(r'[가-힣]+[구시군](?:\s+[가-힣]+구)?(?=\s|$)', remainder)
```

`full_address` 는 **"주소 + [물건 표시]"** 형태이고 대괄호 안에는 구조·면적·등기부 항목이
들어 있다 — **주소 성분은 없다.** 세종시는 시군구가 없어 정답이 빈 문자열인데, 정규식이
대괄호까지 훑어 등기부 용어 **'갑구'** 를 행정구역으로 집었다.
그러면 `sigungu LIKE '%갑구%'` 검색에 엉뚱한 물건이 걸리고 **지역 필터가 조용히 틀린다.**

**[수정]** 주소 성분을 뽑기 전에 대괄호 블록을 떼어낸다. 지번은 이미
`(?=\s|$|\[)` 로 대괄호 앞까지만 보고 있었으니 **같은 규칙을 시군구/동에도 맞춘 것**이다.
규칙은 `normalizer.address_without_brackets()` 한 곳에만 둔다(두 벌이 되면 갈라진다).
`full_address` 원문은 **그대로 돌려준다** — 떼어내는 것은 파싱 입력에서만이다.

**[★ 결함 2 — 이쪽이 사용자에게 더 크다. 일반구가 빠진 167행]**

`test_normalizer.py` 첫 줄이 이미 적어 둔 그 버그다 — *"고양시/성남시/수원시 등 일반구를
둔 시는 구(區) 단위를 누락시켜 '일산동구' 검색이 영구히 0건이 된다."*
**정규화기는 고쳐졌는데 이미 들어온 행은 다시 정규화된 적이 없었다.**

```
저장 '고양시'      -> 정답 '고양시 일산동구'
저장 '수원시'      -> 정답 '수원시 팔달구'
저장 '용인시'      -> 정답 '용인시 수지구'      ... 167행
```

`sigungu LIKE '%일산동구%'` 는 이 행들을 **하나도 못 찾는다.**

**[수정과 실측 — 구 단위 검색이 82% 늘었다]**

`backfill_region_normalize.py --apply` (이미 있던 도구다. 한 번도 돌지 않았을 뿐이다).

```
구 단위 검색  BEFORE -> AFTER
  일산동구    8 ->  12      팔달구    12 -> 30      상록구   10 -> 20
  일산서구    7 ->  10      분당구     2 ->  2      단원구   13 -> 30
  수지구      3 ->   6      덕양구    10 -> 12      기흥구    7 -> 10
                            영통구     2 ->  3
  ------------------------------------------------------------
  합계       74 -> 135   (+61, **82% 증가**)

시 단위(고양시/용인시/수원시/안산시)는 변화 없음 — LIKE 라 상위도 계속 잡힌다
```

**[백필의 "지우지 않는다" 규칙에 예외 하나를 뒀다]**

이 스크립트는 *"새 값이 비면 채워진 값을 지우지 않는다"* 를 지킨다(정규화기가 못 읽은
것뿐일 수 있으니 옳은 기본값이다). 그런데 그 규칙 때문에 `sigungu='칠곡군'`(세종 물건)이
**오염인 채로 남았다.** 남기는 쪽이 정보 보존이 아니라 **오염 유지**다.

예외를 좁게 뒀다 — **저장값이 주소 부분(대괄호 제외)에 아예 없을 때만** 지운다.
판정은 추측이 아니라 원문 대조이고, 대괄호를 빼는 데 위 `address_without_brackets()` 를
그대로 쓴다. 이 예외 덕에 '갑구' 2건도 함께 정리됐다(원문 전체와 대조했다면 대괄호 안에
'갑구' 가 있어 계속 남았을 것이다).

**[결과 — 지역 데이터가 처음으로 전수 정합]**

```
                     BEFORE      AFTER
sido 불일치            4행         **0행**
sigungu 불일치       167행         **0행**
행정구역명이 아닌 sigungu  '갑구' 2행   **0행**
detect_stale_region_contamination  1건   **0건**
반영: auction 170행 + auction_item 174행
```

**[검증]** mutation — 대괄호 제거를 되돌리면
"★ 대괄호 안의 '갑구'를 시군구로 읽지 않는다"가 붉어진다.
`test_normalizer.py` 에 5케이스 + 헬퍼 계약 2건 추가(일반구가 기존대로 잡히는 것,
`full_address` 무손실까지 함께 고정).

**[남은 위험]** 감사 도구(`detect_stale_region_contamination_dryrun.py`)의 판정 방식은
그대로다 — *"원문에 있으면 통과"* 라 위 유형을 여전히 못 잡는다. 지금은 불일치가 0이라
당장 문제가 없지만, **정규화기와 직접 대조하는 방식으로 바꾸는 것**이 다음 후보다.
이번에는 그 대조를 손으로 돌려 확인했다.

**[결함이 아니라고 판정한 것]** `detect_merged_case_duplicates_dryrun.py` 가 3쌍을
보고했다(같은 주소·법원·물건번호가 병합 사건번호가 바뀌며 두 행이 됐다).
**기본 검색에 두 행이 함께 보이는 쌍은 0이다** — 옛 행은 전부 기일이 지나 빠진다.
어느 행을 남길지는 제품 판단이라 손대지 않는다.

--------

#215

**DocWorker 가 스케줄러에 등록돼 있지 않아 document_queue 가 44일째 정체돼 있었다** —
등록하고 실제로 돌려 파이프라인 전체를 실물로 검증했다

발견·수정 (2026-08-26)

**[실측으로 드러난 모순]** `audit_schedule_health.py` 가 축 사이의 모순을 직접 지목했다.

```
\DOJOONPASS_DAILY   등록됨. 마지막 2026-08-26 03:00:01, 결과 0   <- 크롤은 돌고 있었다
DojoonPass-DocWorker      **미등록**
DojoonPass-PriorityRefresh **미등록**

document_queue  최신 적재 2026-08-26T04:42 / 최근 처리 **2026-07-12T17:30**  -> 44일 정체
pending 5,828 중 4,716(81%)은 이미 기일 경과
```

즉 **크롤은 매일 큐에 쌓는데 아무도 빼지 않고 있었다.** 이것이 "노출 물건의 92%가
수집중"이라는 베타 최대 병목의 직접 원인이다.

**[등록 전에 선행 조건부터 실측했다]** 등록만 하고 매일 밤 실패하면 더 나쁘다.

```
selenium 4.47.0                     OK
크롬 드라이버 기동                    OK (Chrome 151.0.7922.172)
doc_worker import                    OK
register_scheduler_tasks.ps1 dry-run  선행 조건 전부 OK
```

`-SkipCoveredByLegacy` 로 등록했다 — `DOJOONPASS_DAILY` 가 이미 `run_daily.bat` 을
커버하므로 `DojoonPass-DailyCrawl`(06:00)을 추가하면 **같은 배치가 하루 두 번** 돈다.
그 스위치가 정확히 그것을 막는다.

```
등록: DojoonPass-PriorityRefresh  01:50  (다음 2026-08-27 01:50)
      DojoonPass-DocWorker        02:00  (다음 2026-08-27 02:00)
재조회로 확인 완료
```

**[★ 등록으로 끝내지 않고 실제로 돌렸다]** `DOC_WORKER_TEST_MODE=1` 로 13분 제한 실행.
**의도적으로 시간 초과로 끊어** 중단 복구 경로까지 함께 봤다.

```
                    실행 전      실행 후
document_queue      pending 5,828 -> 1,653
                    SKIPPED_EXPIRED 178 -> 4,306      (기일 경과분 4,128건 종결)
                    done 541 -> 599                   (실제 문서 58건 수집)
document_status     READY 555 -> 613
doc_raw             555 -> 596                        <- mark_queue_done 의 doc_raw 기록이 실동작
auction_image       **0 -> 85**                       <- migration 020 테이블이 처음으로 채워졌다
auction_item        2,558 -> 2,558                    <- 크롤 데이터 무변경
quick_check ok / foreign_key_check 0
```

**실측 처리량** (같은 13분 구간)

```
기일 경과 종결   4,128건 / 5.3건per초   (브라우저를 열지 않는다)
실제 수집          58건 / 약 11.4초per건
락                프로세스를 강제 종료했는데도 남지 않았다
중단 잔여          in_progress 2행 -> `reset_stale_queue()` 가 pending 으로 회수(사본에서 검증)
```

**[베타 영향]** 기본 검색에 보이는 280건 기준:

```
READY 문서 보유 물건    4 -> **21**
사진 보유 물건          0 -> **17**
```

남은 실작업 1,052행 / 야간 창 120분 x 11.4초 = 약 631건per밤 -> **약 1.7밤이면 소진**된다.
이제 자동으로 돈다.

**[남은 위험]** 이 작업은 **로그온 상태에서만** 실행된다(비밀번호 없이 등록하는 방식).
PC 가 잠겨 있어도 로그온 세션이 살아 있으면 돈다. 완전 로그아웃 상태로 운영하려면
`-RunWhetherLoggedOn` 으로 다시 등록해야 하고 그때는 자격 증명 입력이 필요하다.

--------

#216

**★ P0 — `migrate_execute.py` 의 자체 검증이 `orig * 3` 을 하드코딩해, 사진이 수집되는
순간부터 매일 밤 배치가 거짓 실패를 내게 돼 있었다**

발견·수정 (2026-08-26, #215 의 워커 실행 직후 스위트가 잡았다)

**[증상]** 워커를 처음 돌려 IMAGE 행 17개가 생기자 `test_auction_identity` 가 붉어졌다.

```
[FAIL] document_status 불일치: 7697 != 7680      <- 차이가 정확히 17
```

**[원인]** 결과 검증이 이렇게 돼 있었다.

```python
ds = conn.execute("SELECT COUNT(*) FROM document_status").fetchone()[0]
...
if ds == orig * 3:   # auction 1행당 문서 3종
```

`document_status` 에는 **doc_worker 가 만드는 `IMAGE` 행도 들어온다.** 사진은
migrate_execute 가 만드는 것이 아니고 물건마다 있지도 않다(사진 없는 물건은 IMAGE 행이
아예 안 생긴다). 그러니 `ds == orig * 3` 은 **구조적으로 성립할 수 없게** 됐다.

**[왜 P0 인가]** 이 판정은 **exit 1 로 이어진다.** 그리고 `migrate_execute.py` 는
`run_daily.bat` 이 매일 03:00 에 부른다.

```
"%PY%" migrate_execute.py >> logs\migrate_execute.log 2>&1
if errorlevel 1 ( echo [FAILED] ... & exit /b 1 )
```

즉 고치지 않았으면 **오늘 밤부터 매일 `[FAILED]`** 가 찍힌다. 데이터는 멀쩡한데
배치만 실패로 보고된다. 이 파일이 주석으로 길게 경계해 온 *"거짓 실패"* 가
**반대 방향으로 재발**하는 자리였다(예전엔 이모지 인코딩 때문에 같은 일이 11회 있었다).
거짓 실패가 쌓이면 진짜 실패가 그 속에 묻힌다 — 그것이 이 저장소가 BUGS #47 에서 겪은 사고다.

**[수정]** 세는 대상을 **문서 3종으로 좁혔다.** doc_type 목록을 검증과 INSERT 루프가
**같은 상수**(`MIGRATED_DOC_TYPE_COLUMNS` / `MIGRATED_DOC_TYPES`)에서 가져오도록 합쳤다 —
두 곳에 따로 적으면 종류가 늘 때 한쪽만 바뀌고, 그때 검증이 조용히 틀린 답을 낸다.

```
검증: EXIT CODE = 0
      auction_item 2,558 / document_status 7,674건 (문서 3종만. IMAGE 제외)
      [OK] auction_item 건수 일치 / [OK] document_status 건수 일치
mutation: 옛 로직으로 되돌리면 test_auction_identity 가 `7691 != 7674` 로 잡는다
SQL 가드: `IN (%s)` 는 `?` 반복만 만들고 값은 전부 바인딩된다 —
          근거를 적어 ALLOWED_SQL_PERCENT_TEMPLATES 에 등록했다
```

--------

#217

**실 DB 사본을 `shutil.copy2()` 로 뜨는 곳이 10군데였다 — 워커가 쓰는 중이면 찢어진다**
(실측: 18MB DB 에서 **12회 중 10회** 일관성 위반)

발견·수정 (2026-08-26)

**[어떻게 드러났나]** #215 에서 워커를 돌리는 동안 스위트가 같이 돌았다. 두 검사가 붉어졌다.

```
test_crawl_orchestration.py   <- shutil.copy2 로 실 DB 사본을 뜬다
test_worker_batching.py
둘 다 **단독으로는 통과한다**
```

제품 결함이 아니라 **사본이 깨진 것**이다. 그리고 이제 이 조건은 DocWorker 등록으로
**매일 밤 02:00~04:00 에 자동으로 만들어진다.** 이유 없이 붉어지는 검사는 결국
사람이 믿지 않게 된다 — 그게 진짜 손해다.

**[실측으로 확인했다]** 같은 쓰기 부하에서 두 방식을 나란히 쟀다.

```
DB 크기      방식              일관성 위반    손상
8 KB         shutil.copy2       0/12         0/12    <- 너무 작아 구별되지 않는다
8 KB         backup API         0/12         0/12
18.3 MB      shutil.copy2      **10/12**     0/12
18.3 MB      backup API         **0/12**     0/12
```

운영 DB 는 이미 6.5MB 이고 계속 큰다.

**[수정]** `storage/database.py:snapshot_live_db()` 를 신설했다 — SQLite **온라인 백업
API**(`Connection.backup()`)로 트랜잭션 일관 스냅샷을 만들고, 원본은 `mode=ro` 로 연다.
10곳을 전부 이 함수로 옮겼다. 규칙을 한 곳에만 둔다.

**[신설 검사]** `test_db_snapshot.py`

```
동시 쓰기 중 12회 스냅샷 전부 무결 + 트랜잭션 일관
원본 무변경(크기·mtime) / 원본은 읽기 전용으로 열린다
소스 계약: shutil.copy 로 실 DB 사본을 뜨는 곳 0
mutation  한 검사를 copy2 로 되돌리면 -> 잡는다
          snapshot_live_db 내부를 copy2 로 바꾸면 -> 잡는다(9/12 불일치)
```

**[★ 검사 자체가 처음엔 공허했다]** 첫 판은 800행/8KB 짜리 DB 를 썼다. 그 크기에서는
파일 복사가 순식간에 끝나 커밋 사이에 깔끔히 들어가므로 **두 방식이 똑같이 통과했다** —
mutation 으로 실증했다(내부를 copy2 로 바꿔도 통과). 위 표가 그래서 필요했다.
40,000행(약 18MB)으로 키우고 쓰기 스레드의 sleep 을 없애자 비로소 갈렸다.

--------

#218

**검사 셋이 `IMAGE` 를 자산 종류로 몰랐다 — 사진이 처음 수집되자 한꺼번에 붉어졌다**
(사진 쪽은 멀쩡했다. 검사가 몰랐을 뿐이다)

발견·수정 (2026-08-26)

**[왜 이제야 드러났나]** `auction_image` 가 **0행**이었기 때문이다. DocWorker 가 등록돼
있지 않아 사진 수집이 한 번도 돌지 않았고, 그래서 이 경로를 지나는 검사가 없었다.
#215 로 워커를 돌리자 IMAGE 17행 / 사진 85장이 생기며 즉시 드러났다.

```
test_document_status_sync   READY인데 뷰어가 서빙할 수 없는 행: 17   (= IMAGE READY 전부)
test_pipeline_integrity     done인데 파일이 없는 행: image 5건
                            done인데 document_status 행이 없는 것: image 5건
                            파일이 있는데 큐가 done/refresh가 아닌 것: 13건
```

**[원인 셋]**

```
(1) test_document_status_sync 는 DOC_TYPE_FILES(문서 3종)만 알아 IMAGE 를
    "알 수 없는 doc_type" 으로 잡았다. 사진은 auction_image + /images/{seq} 로 서빙된다.
(2) test_pipeline_integrity 의 done 루프는 done 행 **전부**를 도는데
    `QUEUE_DOC_FILE.get(doc_type, "?")` 라 image 는 파일명이 문자 "?" 가 되고,
    `QUEUE_TO_DS.get("image")` 는 None 이라 상태 조회도 빈다 — 걸릴 수밖에 없다.
    (같은 파일에 이미 `QUEUE_TO_DS_ALL`(image 포함)이 있었는데 이 루프만 안 쓰고 있었다.)
(3) doc_worker 2차 방어선이 기일 경과 행을 SKIPPED_EXPIRED 로 종결하는데, 그 행이
    **예전에 이미 수집돼 파일을 갖고 있는** 경우가 있다 -> "파일은 있는데 done 이 아니다".
```

**[수정 — 면제가 아니라 다른 규칙으로 검사한다]** 그냥 건너뛰면 사진은 아무도 안 지키게 된다.
문서에 요구하는 것과 **같은 강도**로 본다: 행이 있고, 파일이 실재하고, 0바이트가 아니다.

(3) 은 통째로 면제하지 않고 **사용자가 실제로 볼 수 있을 때만** 통과시킨다 —
13행 전부 `document_status` 가 READY 라 사용자는 그 문서를 그대로 본다(실측).
파일은 있는데 화면 상태가 READY 가 아니면 그건 받아 놓고도 못 보여 주는 진짜 결함이므로
여전히 잡는다.

```
검증  READY 613행 (APPRAISAL 207, IMAGE 17, SPEC 212, STATUS 177) 전부 서빙 가능
mutation  사진 파일 하나를 옮기면 -> 잡는다
          사진 파일을 0바이트로 만들면 -> 잡는다
          SKIPPED_EXPIRED 행의 화면 상태를 COLLECTING 으로 바꾸면 -> 잡는다
```

**[결함이 아니라고 판정한 것]** 상세 API 의 `documents` 배열에 `IMAGE` 가 섞여
`viewer_url` 이 400 을 준다. 그러나 **프런트는 이미 그것을 걸러 낸다**
(`src/app/properties/[id]/page.tsx` — `.filter((doc) => doc.doc_type !== 'IMAGE')`,
주석까지 그 이유를 적고 있다). 사용자 영향이 없고, 배열에서 빼는 것은 응답 구조 변경이라
"기존 API 유지" 규칙에 걸린다. 기록만 남긴다.

**[기준선]** 통과 56 / 실패 0, 단언 9,380건. node 194건 / 193 pass / 0 fail / 1 skip.
tsc 0 / eslint 0 / build 0. 크롤 데이터 무변경(auction_item 2,558).

--------

#219

**`run_daily.bat` 이 마이그레이션을 부르지 않았다** — 그리고 그것을 고치다가
**.bat 의 UTF-8/cp949 어긋남**이라는 선재 위험을 발견했다

발견·수정 (2026-08-26)

**[1) 마이그레이션이 배치에 없었다]**

`docs/CLAUDE.md` 가 이미 관찰로 적어 둔 것을 실제로 고쳤다.

```
run_daily.bat  ->  mvp_scraper.py  ->  migrate_execute.py     (이게 전부였다)
                   ^ init_db() 는 레거시 3테이블만 만든다. 번호 마이그레이션은 건드리지 않는다
```

즉 001~025 가 적용된 것은 **사람이 수동으로 러너를 돌렸기 때문**이고
(`migration_history` 타임스탬프가 개발 세션 시각에 몰려 있는 것이 근거),
새 마이그레이션이 생겨도 배치로는 자동 반영되지 않았다.
**위험한 순간은 새 배포/새 마이그레이션 뒤 첫 크롤이다 — 옛 스키마에 쓴다.**
2026-08-26 에 025(면적 컬럼)를 넣으며 실제로 그 격차가 생겼다.

**[수정]** 배치 맨 앞에서 `python -m storage.migrations.run_migrations` 를 부르고,
실패하면 거기서 멈춘다(`exit /b 1`). **틀린 스키마에 크롤 데이터를 쓰는 것보다 안 쓰는
것이 낫다.** 러너는 재실행에 안전하다(실측: 전부 적용된 상태에서 재실행 exit 0).

**[2) ★ 그 과정에서 드러난 선재 위험 — cmd 가 주석 조각을 명령으로 실행한다]**

수정한 배치를 **실제 바이트 그대로** cmd 로 돌려 문법을 검증했다(파이썬은 스텁으로 가로채
크롤이 돌지 않게 했다). stderr 에 이런 것이 찍혔다.

```
'_history`'은(는) 내부 또는 외부 명령, 실행할 수 있는 프로그램, 또는 배치 파일이 아닙니다.
```

`migration_history` 의 **뒷토막이 명령으로 실행됐다.** 원인은 인코딩이다.

```
run_daily.bat 파일 인코딩   UTF-8 (BOM 없음)     <- HEAD 도 동일. 내가 바꾼 것이 아니다
cmd 가 읽는 코드페이지        cp949(이 시스템)
```

한글 UTF-8 바이트를 cp949 로 읽으면 **2바이트 조합이 뒤따르는 ASCII 를 트레일 바이트로
삼켜** 토큰 경계가 밀린다. 그래서 주석 한가운데에서 파싱이 재개되고 남은 조각이 명령이 된다.

**이것은 내가 만든 문제가 아니다.** HEAD 의 배치를 같은 방법으로 돌리면 더 나쁘다.

```
HEAD  exit=255   '...[SUCCESS]' 가 명령으로 실행됨 + 구분선까지 명령으로
WORK  exit=0     내가 추가한 구간의 오류는 사라짐(아래 수정), 옛 주석발 경고만 남음
```

**[수정과 한계]** 내가 **추가한 주석 블록만 ASCII 로 다시 썼다.** 그 구간의 오류는 없어졌다.
파일 전체를 바꾸지는 않았다 — 근거를 적는다.

```
cp949 로 저장    -> 실패. 기존 주석의 em-dash(U+2014)를 cp949 가 인코딩하지 못한다
chcp 65001 추가  -> 효과 없음(cmd 는 이미 앞서 파싱한다)
UTF-8 BOM 추가   -> 더 나빠진다('癤?echo' 가 명령이 된다)
```

즉 **간단한 전역 해법이 없다.** 남은 옛 한글 주석은 그대로 위험을 안고 있다.

**[그래서 지금 실제로 위험한가 — 아니다. 다만 운이 좋은 것이다]**
운영에서는 정상 동작한다. `DOJOONPASS_DAILY` 2026-08-26 03:00 실행 **결과 0**,
`logs/daily_run.log` 에 `[SUCCESS] Finished at 2026-08-26 4:42:33`.
지금 밀리는 자리가 하필 아무 해가 없는 곳이라 그렇다. **바이트가 하나만 달라져도
실제 명령 줄을 삼킬 수 있다** — 그것이 이 항목을 남기는 이유다.

**[남은 위험 / 다음 후보]** `.bat` 3개의 한글 주석을 전부 ASCII 로 옮기거나, 설명을
`.md` 로 빼고 배치에는 최소 주석만 남기는 것. 이번에는 범위를 넘어 하지 않았다.
새로 추가하는 `.bat` 주석은 **ASCII 로 쓴다**(수정한 파일에 그 이유를 주석으로 남겼다).

--------

#220

**면적 필터가 migration 025 미적용 DB 에서 검색을 통째로 500 으로 만든다** —
같은 날 들어온 기능의 **두 반쪽이 정반대로** 쓰여 있었다

발견·수정 (2026-08-26)

**[증상]** `min_building_area` / `max_building_area` / `min_land_area` /
`max_land_area` 중 **하나라도** 주면 `/api/v1/search` 가 500 을 돌려준다.
값이 이상해서가 아니다 — `1.5` 도, `-1` 도, `10` 도 전부 500 이다.

```
GET /api/v1/search?page=1&size=5                              200  total=0
GET /api/v1/search?page=1&size=5&include_closed=true          200  total=1876
GET /api/v1/search?page=1&size=5&min_building_area=10         500  <-
GET /api/v1/search?page=1&size=5&min_land_area=10             500  <-

sqlite3.OperationalError: no such column: building_area
  File "api/v1/search.py", line 430, in search  (total = conn.execute(...))
```

**[원인 — 한 커밋 안에서 두 반쪽이 어긋났다]**

면적 검색은 2026-08-26 에 migration 025 + `extract_areas()` + 프런트 입력까지
한 번에 들어왔다. 그런데 **응답 쪽**은 컬럼 결손을 방어하고 **필터 쪽**은 하지 않았다.

```
응답   _area_of(row, "building_area")        컬럼이 없으면 그 필드만 null
       주석: "검색 전체가 500 이 되는 것보다 그 필드만 null 이 낫다"
필터   conditions.append("building_area >= ?")   컬럼이 없으면 그대로 500
```

**같은 파일 안에서 같은 상황을 정반대로 판단하고 있었다.** 응답 쪽 주석이 이미
옳은 답을 적어 두고 있었는데 필터 쪽이 그것을 따르지 않은 것이다.

**[왜 도달 가능한가]** 이 조합은 가정이 아니다. `run_daily.bat` 는 #219 이전까지
`run_migrations` 를 부르지 않았고, 그래서 **새 배포에 025 가 닿지 않을 수 있다.**
그리고 프런트는 같은 날 면적 입력의 '준비 중입니다' 를 걷어내고 **실제 입력을
열었다**(`src/app/search/SearchForm.tsx:366-372`). 즉 사용자가 면적을 만지는 순간
검색이 통째로 깨진다. 이 저장소는 같은 사고를 이미 두 번 겪었다 — migration 020 결손이
검색/상세를 전면 500 으로 만든 P0-C 와 BUGS #177 이다.

**[재현]** 이 머신의 `auction.db` 가 정확히 그 상태였다(021~025 미적용).
저장소의 기존 가드 `test_id_bounds_sweep.py` 가 **20개 조합 전부**를 잡아 이미 붉었다.

```
[FAIL] ★★ 쿼리 파라미터로 5xx 를 내는 라우트:
  ['/api/v1/search?min_building_area=922337203685 -> 500', ..., 20건]
```

**[수정]** `api/v1/search.py`

면적 조건이 **실제로 들어온 요청에서만** `PRAGMA table_info(auction_item)` 로 컬럼
유무를 보고, 없으면 빈 결과를 돌려준다. 조건을 조용히 버리지 않는다.

```python
AREA_COLUMNS = ("building_area", "land_area")

def _area_columns_available(conn) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(auction_item)").fetchall()}
    return all(c in cols for c in AREA_COLUMNS)
```

**왜 '빈 결과' 가 옳은가** — 답은 이미 정해져 있었다. 같은 코드의 주석이
*"면적을 모르는 물건은 면적 조건을 주는 순간 결과에서 빠진다"* 고 규약을 세웠다
(SQLite 에서 `NULL >= 3` 은 NULL 이라 자연히 그렇게 된다). 컬럼 자체가 없으면
**모든 행이 면적 미상**이므로 빈 집합이 그 규약의 결론이다.

조건을 **조용히 버리는 쪽**이 훨씬 나쁘다 — "건물 30㎡ 이상"을 건 사용자에게
면적이 30 이 아닌 물건을 섞어 주면서 조건대로라고 말하는 셈이다.
근본 원인(스키마 드리프트)은 `test_bootstrap` / `test_schema_hygiene` 가 따로 잡는다.
`auction_image` 결손을 다루는 #177 과 정확히 같은 분담이다.

**판정을 캐시하지 않는다** — `run_daily.bat` 가 매일 새벽 러너를 부르므로(#219)
서버가 떠 있는 동안 025 가 적용될 수 있다. 캐시하면 그 뒤로도 계속 "컬럼 없음"이라고
답해 **고쳐졌는데도 빈 결과**를 준다.

**비용은 재서 적는다** — 2,000회 실측 중앙값 **0.128ms**(평균 0.141 / p95 0.228),
같은 커넥션의 단건 COUNT 가 0.073ms 다. 면적 검색 실측 12.4ms 의 1% 수준이고,
면적 조건이 없는 평범한 검색은 이 비용조차 지지 않는다.
★ 처음 주석에 "0.01ms 미만"이라고 적었다가 재 보고 고쳤다 — **13배 틀린 짐작**이었다.

**[회귀 테스트]** `test_search.py :: check_area_filter_survives_missing_migration_025`
— 검사 23건. **컬럼이 있는 DB 부터** 본다.

```
A 컬럼이 있을 때   >=50 -> 2·3 / 50~100 -> 2 / 토지>=200 -> 3 / 면적미상은 빠진다 / 경계 포함
B 한쪽만 없을 때   land_area 만 DROP -> 양쪽 조건 다 200, 빈 결과
B 둘 다 없을 때    DROP COLUMN 으로 실제 재현 -> 6종 전부 200, 계약 모양 유지
C 방어가 좁은가    면적을 안 주면 4건 그대로 / 다른 필터도 그대로 / 면적 필드는 null
D 캐시 없음        뒤늦게 ADD COLUMN 하면 같은 프로세스에서 곧바로 다시 거른다
```

★ **A 가 없으면 이 검사는 공허하다.** 기존 `check_declared_filters_actually_filter()`
는 면적에 극단값(10^9, 1)만 보내고 0건을 기대하는데, 그 검사는 *"면적 조건이 오면
무조건 빈 결과"* 라는 **잘못된 고침으로도 그대로 통과한다.** 실제로 변이 M2 로 확인했다.

★ **B 의 '한쪽만' 단계도 처음에는 없었다.** 두 컬럼을 한꺼번에 지우면
`AREA_COLUMNS` 에서 `land_area` 를 빠뜨리는 실수(변이 M7)가 **살아남는다** —
building_area 하나만 봐도 판정이 False 로 같기 때문이다. 변이가 살아남은 것을 보고
검사를 고쳤다.

**[변이 8/8 검출]**

```
M1  가드를 통째로 삭제(수정 이전 상태)          -> 잡는다 (500)
M2  컬럼 유무와 무관하게 늘 빈 결과(과잉 방어)  -> 잡는다 (A)
M3  판정이 늘 True                              -> 잡는다 (500)
M4  판정이 늘 False                             -> 잡는다 (A)
M5  any -> all (넷 다 줘야 방어가 켜진다)       -> 잡는다 (단일 파라미터 500)
M6  판정을 캐시한다                             -> 잡는다 (D)
M7  building_area 만 본다(land_area 를 잊는다)  -> 잡는다 (B, 검사를 고친 뒤)
M8  all -> any (하나만 있어도 있다고 본다)      -> 잡는다 (B)
```

**[기준선]** 이 수정 전후로 스위트가 **통과 51 -> 52 / 실패 5 -> 4**,
단언 9,355 -> 9,404. 없어진 실패가 `test_id_bounds_sweep` 이다.
남은 실패 4건은 전부 **이 머신 `auction.db` 의 021~025 미적용** 때문이며
(migration 적용은 승인 영역이라 하지 않았다) 제품 결함이 아니다.

--------

#221

**`.bat` 3개의 한글 주석이 cmd 를 오파싱한다** — 그리고 끝까지 실행해서 재 보니
`run_daily.bat` 는 **성공 경로에서 아무 일도 하지 않고 exit 255** 로 끝나고 있었다

발견·수정 (2026-08-26, #219 가 "남은 위험"으로 넘긴 항목)

**[전제 — #219 가 세운 사실]** 세 배치는 **UTF-8(BOM 없음)** 인데 `cmd.exe` 는 이
시스템의 **OEM 코드페이지(cp949)** 로 읽는다. 한글 UTF-8 바이트를 cp949 로 읽으면
2바이트 조합이 뒤따르는 ASCII 를 트레일 바이트로 삼켜 토큰 경계가 밀리고, 주석
한가운데에서 파싱이 재개돼 **남은 조각이 명령으로 실행된다.**

#219 는 자기가 **추가한 구간만** ASCII 로 고치고 옛 한글 주석은 남기며
*"지금 실제로 위험한가 — 아니다. 다만 운이 좋은 것이다"* 라고 적었다.

**[★ 그 판단이 낙관적이었다 — 끝까지 실행해서 재 보니 그렇지 않다]**

#219 의 측정은 파이썬이 없는 사본이라 배치가 **앞부분에서 멈췄다.** cmd 는 줄 단위로
읽으며 실행하므로 **뒤쪽 주석까지 가지도 못했다.** 이번에는 모든 단계가 성공하도록
스텁(`sys.exit(0)`)을 깔아 **끝까지** 실행했다.

```
                          exit   cmd stderr   logs/            daily_run.log
HEAD run_daily.bat         255      7줄      ★ 생성 안 됨      ★ 없음
HEAD run_doc_worker.bat      0      7줄       정상             (해당 없음)
HEAD run_priority_refresh    0      5줄       정상             (해당 없음)
수정 후 셋 다                0      0줄       정상             [SUCCESS] 정상
```

`run_daily.bat` 는 **성공 경로에서** 종료 코드가 255 가 되고, `[SUCCESS]` 도
`[FAILED]` 도 남기지 않는다. 게다가 `logs\` 디렉터리조차 만들어지지 않았다 —
즉 **`if not exist "logs" mkdir "logs"` 줄 자체가** 앞선 한글 주석 블록에 밀려
깨졌고, 그래서 뒤의 리다이렉트가 전부 실패해 **파이썬이 한 번도 실행되지 않았다.**

★ 그 주석 블록이 무엇을 설명하고 있었는지가 이 항목의 요점이다 — *"`logs\` 가 없으면
리다이렉트가 실패하고 스크립트가 아예 실행되지 않는다"*(Sprint 99). **그 설명 자체가
그 사고를 일으키고 있었다.**

관측된 조각들:
```
'�留?[SUCCESS]'은(는) 내부 또는 외부 명령...     <- 주석 속 [SUCCESS] 글자가 명령이 됐다
'-------------------------------------'은(는)... <- REM 구분선
'곕릺硫댁꽌'은(는) ...
湲곗〈은(는) 예상되지 않았습니다.                 <- 구문 오류
파일 이름, 디렉터리 이름 또는 볼륨 레이블 구문이 잘못되었습니다.  <- 리다이렉트가 깨졌다
```

**[★ 처음 잰 값은 틀렸다 — 도구를 먼저 의심했다]**
이 세션의 셸에서 그냥 돌렸을 때는 세 파일 모두 stderr 0줄이었다. 그 셸의 cmd 가
**코드페이지 65001** 을 물려받았기 때문이다(`chcp` 로 확인). 시스템 ACP/OEMCP 는
**949** 이고 작업 스케줄러는 그쪽으로 띄운다. 즉 첫 측정은 **실제 실행 조건이
아니었다.** 949 로 맞추고 다시 재서 위 표를 얻었다.

**[수정]** 세 배치의 주석을 전부 ASCII 로 다시 썼다. 한글 설명은 지운 것이 아니라
`docs/BATCH_SCRIPTS.md` 로 **옮겼고**, 배치에는 그 문서를 가리키는 최소 주석만 남겼다.
#219 가 다음 후보로 적어 둔 방법 그대로다.

**실행되는 줄은 파일당 딱 한 줄만 바뀌었다**(나머지는 바이트 그대로):

```
- echo [FAILED] Python 인터프리터를 찾을 수 없습니다 ^(run_daily.bat^) ...
+ echo [FAILED] Python interpreter not found ^(run_daily.bat^) ...
```

`[FAILED]` 마커·`errorlevel` 검사·`exit /b` 구조는 전부 그대로라
`test_crawl_exit_code.py` 의 배치 계약 검사가 그대로 통과한다(확인함).

**[왜 다른 해법이 없나 — #219 실측 그대로]**
```
cp949 로 저장     실패 — 기존 주석의 em-dash(U+2014)를 cp949 가 인코딩하지 못한다
chcp 65001 추가   효과 없음 — cmd 는 그 줄에 닿기 전에 이미 앞을 파싱한다
UTF-8 BOM 추가    더 나빠진다 — '癤?echo' 가 명령이 된다
```

**[회귀 테스트]** `test_console_encoding.py :: test_batch_files_are_ascii` — 검사 14건.

```
.bat   BOM 이 없다 / ASCII 로만 이루어져 있다 / **cp949 로 읽은 내용 == utf-8 로 읽은 내용**
.ps1   비ASCII 를 쓰면 UTF-8 BOM 이 있어야 한다
       (PowerShell 5.1 은 BOM 이 없으면 ANSI 로 읽는다. `register_scheduler_tasks.ps1`
        은 이미 BOM 을 갖고 있어 안전하다 — 확인함)
자체검증 known-bad(한글 주석 .bat) 를 잡고 known-good 을 잡지 않는다
```

세 번째 줄이 핵심이다 — "ASCII 로 쓰자"는 규칙만 적어 두면 다음 사람이 *"주석인데
뭐 어때"* 로 되돌린다. **cmd 가 보는 바이트가 우리가 쓴 것과 같은지를** 그 자리에서
재면 이유가 검사 안에 남는다.

`.claude/worktrees/` 아래 옛 사본은 훑지 않는다 — 고칠 수 없는 과거 파일 때문에
검사가 영구 red 가 되면 사람이 검사를 끄게 되고, 그것이 가드가 죽는 흔한 경로다.

**[변이]** `run_doc_worker.bat` 를 HEAD 판으로 되돌리자 검사가 **붉어진다**(확인).
복원하면 다시 통과한다.

**[★ 이 머신에서 확인할 수 없는 것 — 승인/역할 영역]**
작업 스케줄러 248개를 전수로 훑어 이 저장소를 가리키는 작업이 **0개**임을 확인했다.
여기는 개발 머신(데스크탑3)이고 운영 크롤은 데스크탑1이 돈다. 그래서:

- 데스크탑1의 `DOJOONPASS_DAILY` 는 2026-08-26 03:00 에 **결과 0** 으로 끝났고
  `[SUCCESS]` 를 남겼다고 기록돼 있다. 그 작업이 `run_daily.bat` 를 부르는지, 아니면
  파이썬을 직접 부르는 옛 작업인지 **여기서는 알 수 없다.**
- 위 255 는 `register_scheduler_tasks.ps1` 이 정의하는 `DojoonPass-DailyCrawl`
  (= `run_daily.bat`)에 해당한다. 그 작업은 #215 때 **일부러 등록하지 않았다.**
- 이 머신의 `logs/daily_run.log` 는 마지막 항목이 **2026-08-02** 이고 `[SUCCESS]`
  접두어조차 없는 옛 형식이다 — 운영 로그가 아니다.

**후속(데스크탑1)**: `DOJOONPASS_DAILY` 의 실제 Action 과 `chcp` 를 확인한다.
`run_daily.bat` 를 부르고 있었다면 이 수정 **전까지** 그 배치는 아무 일도 하지 않았고
255 로 끝났을 것이다.

--------

#222

**머신 역할 게이트가 §11 에만 걸려 있고 §11-b 는 비껴가 있었다** —
그래서 그 검사는 **어느 머신에서도 동시에 만족될 수 없는** 상태였다

발견·수정 (2026-08-26)

**[증상]** `test_pipeline_integrity.py` 의 11-b 가 이 머신에서 붉다.

```
[FAIL] ★ 체크리스트의 P0-A 판정이 실측과 일치한다
       -> 문서는 'RESOLVED' 라고 하는데 실측은 기일 남은 물건 0건(=OPEN)이다
```

**[★ 문서를 고치는 것은 답이 아니다 — 실패가 자리를 옮길 뿐이다]**

판정 토큰(`<!-- P0A-VERDICT: ... -->`)은 **git 이 추적하는 문서 한 줄**인데,
그 값을 **각 머신의 로컬 `auction.db`** 와 대조한다. 두 머신이 요구하는 값이 다르다.

```
이 머신(데스크탑3, 개발/QA)   기일 미도래   0건  -> OPEN 을 요구한다
데스크탑1(운영 크롤)          기일 미도래 110건  -> RESOLVED 를 요구한다
                              (문서 2026-08-26 절의 기록)
```

**한쪽에 맞추면 다른 쪽이 붉어진다.** 즉 이 가드는 구조적으로 만족 불가능하고,
그런 가드는 결국 사람이 꺼 버린다 — 이 저장소가 반복해 경계해 온 실패 모양이다.

**[원인 — 하루 차이로 어긋난 두 결정]**

```
2026-08-24  Sprint 251 이 11-b 를 만든다. 이때는 머신이 하나라고 보고 있었다.
2026-08-25  BUGS #200 이 머신 역할을 가른다. 개발 머신의 DB 신선도는 제품 판정이
            아니라고 정하고, §11 의 제품 단언을 `is_operational_data()` 안으로 옮긴다.
            11-c 를 새로 만들어 그 배선을 AST 로 고정한다.
            ★ 그런데 11-b 는 그 정리에서 빠졌다.
```

11-c 는 배선을 **함수 이름 하나로** 못박고 있었다.

```python
fn = next((n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name == "test_data_freshness_runway"), None)
```

**한 자리만 이름으로 잠그면 다음 자리가 그대로 새어 나간다.** 같은 파일 안에서
같은 부류의 판정을 하는 함수가 둘인데 하나만 지키고 있었다.

**[수정 1 — 11-b 의 대조를 역할 선언 안으로]** `test_pipeline_integrity.py`

운영으로 선언한 머신에서는 **양방향 그대로** 문다(깨졌는데 RESOLVED 여도, 정상인데
OPEN 이어도 실패한다). 이빨은 그쪽에 남는다. 선언하지 않은 머신에서는 숫자와 토큰을
**찍기만** 하고 실패로 만들지 않는다 — BUGS #200 이 세운 규칙 그대로다.

껍데기가 되지 않도록 미선언 머신에도 **머신과 무관한 단언**을 남겼다:
토큰이 아는 값인가 / 실측 경로가 실제로 돌았는가. 대조는 못 해도 **대조에 쓰이는
기계는 살아 있어야** 다음에 그 코드가 조용히 썩지 않는다.

**[수정 2 — 11-c 를 목록 기반으로 일반화하고, 목록 자체도 잠갔다]**

```python
GATED = (
    ("test_data_freshness_runway", "기본 검색에 뜰 물건이 남아 있다"),
    ("test_checklist_p0a_verdict_matches_reality", "체크리스트의 P0-A 판정이 실측과 일치한다"),
)
```

★ 목록을 두면 **목록이 줄어드는 것**이 새 구멍이 된다(정확히 그 방식으로 11-b 가
빠져 있었다). 그래서 목록이 **이 모듈에서 `is_operational_data()` 를 보는 함수
전부**를 덮는지 대조한다. 가드 함수 자신은 제외한다 — 선언값을 바꿔 가며 해석을
검증하는 것이 그 함수의 일이라 당연히 그 이름을 부른다.

새 제품 판정이 생기면 목록에 넣기 전에는 통과하지 못한다.

**[변이 3/3 검출]**

```
N1  11-b 의 `if is_operational_data():` 를 `if True:` 로   -> 잡는다 (배선 검사)
N2  미선언 머신용 최소 단언을 지운다                        -> 잡는다 (껍데기 방지)
N3  GATED 목록에서 11-b 를 뺀다                             -> 잡는다 (목록 커버리지)
```

**[결과]** 11-b / 11-c 전부 통과. `test_pipeline_integrity.py` 의 남은 실패 2건은
`sido`/`sigungu` 드리프트인데, 이는 **이 머신 DB 에 BUGS #214 의 정규화 backfill 이
적용되지 않았기 때문**이다(backfill 실행은 승인 영역이라 하지 않았다). 코드 결함이 아니다.

**[남는 관찰]** 판정 토큰이 **머신마다 다른 사실**을 git 추적 파일 한 줄에 담고 있다는
구조 자체는 그대로다. 지금은 "운영 머신만 판정한다"로 정리했지만, 운영 머신이 둘
이상이 되면 같은 문제가 다시 온다. 그때는 토큰을 **머신별 산출물**(예: 로컬 상태
파일)로 옮기거나, 문서에는 *"마지막으로 잰 머신과 시각"* 을 함께 적게 해야 한다.

--------

#223

**출시 체크리스트의 두 절이 동시에 "가장 최신"이라고 말하고 있었다** — 그리고
둘의 숫자가 달랐다

발견·수정 (2026-08-26)

**[증상]** `docs/BETA_RELEASE_CHECKLIST.md` 는 절을 **시간 역순**으로 쌓는다. 그런데
같은 날짜의 두 절이 각각 자기가 최신이라고 선언하고 있었다.

```
L122  ## ★★★★★★ [2026-08-26 아침]   ... "이 절이 **가장 최신**이다."      (07:40)
L188  ## ★★★★★  [2026-08-26 야간 세션] ... "이 절이 **가장 최신**이다."      (00:30)
```

**두 절의 숫자가 다르다.**

```
                       아침(07:40)     야간(00:30)
auction_item              2,558           2,444
READY 문서 보유 물건          21               4
사진 보유 물건                17               0
```

**[왜 결함인가]** 이 문서는 *"지금 출시를 막는 것이 무엇인가"* 를 사람이 판단하는
자리다. 위에서부터 읽으면 아침 절을, 검색해서 들어오면 야간 절을 최신으로 받아들인다.
**어느 쪽을 먼저 읽느냐로 결론이 갈린다.** 이번 세션도 실제로 두 절을 나란히 놓고
손으로 시각을 비교해서야 어느 쪽이 이기는지 알았다.

"야간 세션"이라는 이름이 혼동을 키운다 — 08-26 **00:30** 이라 같은 날 **아침보다
이르다.** 이름만 보면 더 나중처럼 읽힌다.

**[수정]** 야간 절의 선언을 **위 절을 가리키는 서술**로 바꾸고, 무엇이 어떻게 다른지
숫자를 함께 적었다. 그 자리에 정정 기록(`>` 인용)도 남겨 다음 사람이 같은 자리에서
같은 문장을 다시 쓰지 않게 했다. 절 자체는 지우지 않는다 — 그날 무엇을 했는지의
기록이고, 이 저장소는 옛 판을 지우지 않고 남기는 방식을 써 왔다.

**[회귀 테스트]** `test_pipeline_integrity.py :: test_checklist_has_one_newest_section`
(11-d) — *"이 절이 ... 가장 최신"* 이라고 **주장하는** 줄이 정확히 하나인지 센다.

★ 11-b 와 달리 이 검사는 **머신과 무관하다.** 문서만 보면 판정되므로 개발 머신에서도
이빨이 그대로 남는다(BUGS #222 가 정리한 역할 게이트가 필요 없는 부류다).

검출기가 인용된 정정 기록(`>` 로 시작)과 다른 절을 가리키는 서술("더 최신이고")을
주장으로 오인하지 않는지 **자체 검증 3건**으로 못박았다 — 안 그러면 이번에 남긴
정정 문구 때문에 검사가 스스로 붉어진다.

**[변이]** 야간 절에 *"이 절이 가장 최신이다"* 를 되돌리자 **붉어진다**(확인).

**[남는 관찰]** 이 문서는 12만 자를 넘고 절이 시간 역순으로 계속 쌓인다. 같은 사고가
"가장 최신" 말고 다른 표현(예: *"아래 값이 최신"*, *"여기가 이긴다"*)으로도 생길 수
있다. 근본적으로는 **문서 맨 위에 현재 상태 한 절만 두고 나머지를 이력으로 내리는**
구조가 맞지만, 전면 재편은 이번 범위를 넘어 하지 않았다(다음 Sprint 후보).

--------

#224

**지역 데이터 가드가 "오염" 부류를 통째로 못 보고 있었다** — 상한을 0 으로 조여 놓고도
한 축이 시야 밖이었다. 원인은 **같은 판정이 두 벌**이었던 것

발견·수정 (2026-08-26)

**[어떻게 눈에 띄었나 — 두 도구가 같은 것을 세는데 숫자가 하나 달랐다]**

```
test_pipeline_integrity §12   sigungu 드리프트 207행
backfill_region_normalize     sigungu 변경 대상 208행
```

1행 차이를 추적했다. 두 도구가 **같은 규칙을 각자 적고 있었고**, 한쪽만 갱신돼 있었다.

**[원인]**

`backfill_region_normalize.py` 는 2026-08-26(BUGS #214)에 규칙을 하나 얻었다.
새 값이 비었을 때 무조건 건너뛰지 않고, **저장값이 주소 원문(대괄호 제외)에도 없으면**
그것은 "정규화기가 못 읽은 값"이 아니라 **다른 물건에서 흘러든 값**이라 지운다.

그런데 §12 가드는 그 갱신을 모른 채 이렇게 적혀 있었다.

```python
# 새 값이 비어 있으면 "규칙이 못 잡는 주소"라 드리프트로 세지 않는다
# (백필도 그런 행은 건너뛴다 ― 채워진 값을 빈 값으로 덮지 않는다).
if f and s != f:
    drift[col].append(...)
```

**괄호 안의 근거가 그날부터 사실이 아니게 됐다.** 그래서 가드는 오염 부류를
**한 행도 세지 않는다.**

**[왜 위험한가 — 상한 0 이 '깨끗하다'로 읽힌다]**

§12 는 2026-08-26 에 네 축의 상한을 전부 0 으로 조이면서
*"상한이 실측보다 하나 헐거우면 새 오분류 하나가 조용히 들어와도 통과한다"* 고 적었다.
맞는 말인데, **아예 세지 않는 축은 상한을 0 으로 조여도 소용이 없다.**
초록불이 "지역 데이터가 깨끗하다"로 읽히는데 한 축은 보고 있지도 않았다.

오염 행은 조용하지 않다 — `sigungu LIKE '%칠곡군%'` 검색에 **경북이 아닌 물건**이
섞여 나온다. 사용자에게는 "왜 세종시 물건이 칠곡군 검색에 뜨지"로 보인다.

**[실측 — 이 머신 `auction_item` 1,876행]**

```
A. 드리프트 (새 값이 있고 다르다)          211행   <- 가드가 세고 있었다
B. 오염 (새 값이 비었고 원문에도 없다)        1행   <- ★ 가드가 못 봤다
C. 정규화기가 못 읽음 (원문에는 있다)         0행   <- 세지 않는 것이 맞다

B 실례:  id=1768  sigungu='갑구'
         주소 = "세종특별자치시 전의면 관정리 578-31 [토지 임야 297㎡ 갑구 2번 ...]"
```

`'갑구'` 는 등기부 용어인데 시군구로 잘못 저장된 값이다. 세종시는 시군구가 없어
정규화 결과가 빈 문자열이 맞고, 그래서 **드리프트로도 잡히지 않는다.**
원문 **전체**와 대조하면 대괄호 안에 '갑구' 가 있어 그냥 남는다 — 대괄호를 빼고
봐야 없다는 것이 드러난다.

**[수정 1 — 판정을 한 곳으로]** `backfill_region_normalize.py`

규칙을 `plan_table()` 안에서 꺼내 `is_stale_contamination(stored, fresh, full_address)`
로 만들었다. 백필과 가드가 **같은 함수를 부른다.** 여기에 규칙을 다시 적으면 두 벌이
되고, 한쪽만 바뀌는 날 두 검사가 서로를 눈감아 준다 — 이 결함이 정확히 그렇게 생겼다.

리팩터가 동작을 바꾸지 않았음을 dry-run 으로 확인했다(전후 모두 sido 4 / sigungu 208 /
총 424건, `auction.db` md5 무변경).

**[수정 2 — 가드에 축을 추가]** `test_pipeline_integrity.py` §12

오염 행 수를 세고 상한 0 으로 문다. 고치는 명령은 드리프트와 같다 — 백필이 이 부류까지
함께 정리하므로 승인 후 한 번 돌리면 세 축이 같이 닫힌다.

★ **이 축은 데이터가 깨끗해지는 순간 공허해진다.** 백필을 돌리고 나면 실 데이터가 0이라
판정 코드가 한 번도 실행되지 않는다. 그래서 **합성 입력 자체 검증 4건**을 함께 넣었다 —
*"검증 대상이 없으면 통과"* 를 만들지 않는다.

**[변이 4/4 검출 — 자체 검증만으로 판정했다]**

실 데이터발 실패를 제외하고 **자체 검증만** 보도록 러너를 짰다. 그래야 백필이 돈 뒤
(실 데이터 0) 에도 이 변이 결과가 그대로 유효하다.

```
P1  오염을 절대 인정하지 않는다              -> 잡는다
P2  대괄호를 빼지 않고 원문 전체와 대조       -> 잡는다
P3  새 값이 있어도 오염으로 본다             -> 잡는다 (자체 검증을 고친 뒤)
P4  모든 것을 오염으로 본다                  -> 잡는다
```

★ **P3 는 처음에 살아남았다.** 자체 검증 입력이 `'고양시' -> '고양시 일산동구'` 였는데
저장값이 주소에 들어 있어서, `if fresh: return False` 를 지워도 뒤쪽 대조가 어차피
False 를 냈다. **두 조건을 갈라 놓는 입력**(`'칠곡군'` / 새 값 `'나성동'` / 주소는
세종시)으로 바꾸니 잡힌다. 살아남은 변이를 먼저 의심한 결과다.

**[★ 도달 불가능한 분기 하나를 걷어냈다]**

`if not stored: return False` 를 함께 지웠다. 변이(P5: 그 분기 제거)가 **살아남았고**,
이유를 보니 `"" not in s` 는 파이썬에서 **항상 거짓**이라 그 분기가 있으나 없으나
결과가 같았다. 방어처럼 보이지만 아무것도 막지 않는다.
판단 기준은 하나다 — **다른 결과를 낼 수 있는 입력이 있는가**(Sprint 254 와 같은 규칙).
대조 방식을 바꾸는 날 다시 읽도록 그 자리에 주석을 남겼다.

**[상태]** 이 축은 지금 **붉다**(1행). 드리프트 2축과 **원인·해법이 같고**
`python backfill_region_normalize.py --apply` 는 **승인 영역**이라 실행하지 않았다.
dry-run 으로 영향 범위는 확정해 뒀다 — 424건, 전부 지역값 보정이고 `auction.db` 무변경 확인.

--------

#225

**등기부/구독 핸들러 다섯 개가 늦은 응답 가드 없이 돌고 있었다** — 그리고 그것을
지켜야 할 검사는 **가드를 이미 가진 곳만** 훑고 있어서 내내 초록불이었다

발견·수정 (2026-08-26)

**[전제]** `/properties/[id]` 는 이전/다음 이동이 같은 라우트의 **파라미터 전환**이라
컴포넌트가 재마운트되지 않는다. 그래서 A 에서 시작한 요청의 응답이 **B 화면에 도착**한다.
저장소는 이 방어를 이미 알고 있다 — `handleToggleFavorite` 는 `const requestId = id` 를
잡고 await 뒤마다 `if (idRef.current !== requestId) return` 으로 끊는다(BUGS #210).

**[결함] 그 관용구가 등기부 쪽에는 하나도 없었다.**

```
performRegistryRequest    setRegistryRequest(result.data)              가드 없음
handleRegistryRequest     setRegistryMessage(...)  / finally busy      가드 없음
handleSubscribe           setRegistryMessage(...)  / finally busy      가드 없음
handlePayOverage          setRegistryRequest(...)  / finally busy      가드 없음
handleDownloadRegistry    setRegistryMessage(...)  / finally busy      가드 없음
```

`[id]` 효과는 물건이 바뀔 때 `setRegistryRequest(null)` 로 **초기화까지 한다**(:327).
초기화가 먼저 돌고 늦은 응답이 **그 뒤에** 도착하므로, 화면은 새 물건인데 값은 이전
물건 것이 된다.

**[★ 영향이 문구가 아니다 — 다른 물건의 등기부를 받는다]**

`docs/BETA_RELEASE_CHECKLIST.md` 는 이 항목을 *"이전 물건의 **안내 문구**가 새 화면에
뜰 수 있다"* 로 적어 두고 크기를 "작음"으로 봤다. **그 판단이 낮았다.**
`registryRequest` 는 문구가 아니라 **동작을 만든다.**

```
:520  fetchAuthedRaw(`/api/v1/registry-requests/${registryRequest.id}/download`)
        -> 새 물건 화면에서 **이전 물건의 등기부 파일**을 받는다
:491  { payment_type: 'OVERAGE_USAGE', amount: registryRequest.charged_amount ?? overageFee }
        -> 화면에 보이는 물건과 **다른 신청 건**의 금액으로 결제를 건다
:658  등기열람 무료 잔여 N회        -> 이전 물건 기준 잔여 횟수를 새 물건에서 보여 준다
```

즉 "잘못된 문구"가 아니라 **잘못된 파일 전달과 잘못된 결제 맥락**이다.

**[★ 왜 아무 검사도 울지 않았나 — 가드가 옵트인이었다]**

`tests/source-contract.test.mjs` 에는 이 부류를 잡는 검사가 이미 있었다.
그런데 판정 함수가 이렇게 시작한다.

```js
lines.forEach((l, i) => {
  if (/const\s+requestId\s*=\s*id\b/.test(l)) starts.push(i)   // <- 여기서만 시작한다
})
```

**검사 대상이 되려면 먼저 가드를 갖고 있어야 한다.** 가드를 아예 선언하지 않은 핸들러는
훑지도 않는다 — 자기 참조적인 조건이다. 그래서 무방비 핸들러 다섯이 통째로 시야 밖이었다.

체크리스트가 이것을 "다음 후보"로 적어 두기까지 했는데, 그동안 검사는 **아무 말도 하지
않았다.** BUGS #224 와 같은 모양이다 — *가드가 보는 범위를 스스로 정하면, 그 범위 밖은
영원히 조용하다.*

**[수정 1 — 다섯 핸들러에 가드]** `src/app/properties/[id]/page.tsx`

`performRegistryRequest(requestId)` 로 물건 id 를 **인자로 받게** 했다. 호출부
(`handleRegistryRequest` / `handleSubscribe`)가 자기 시점의 id 를 잡아 넘긴다.
`item_id` 도 `Number(id)` 가 아니라 `Number(requestId)` 로 보낸다 — 늦게 실행되면
`id` 는 이미 새 물건이라, 사용자가 A 에서 누른 신청이 **B 에 대한 신청**이 될 수 있었다.

체크리스트가 걱정한 *"handleSubscribe 가 이어서 부르므로 가드를 잘못 걸면 정상 흐름이
막힌다"* 는 **성립하지 않는다.** 막는 기준이 `busy` 가 아니라 **물건 id** 이고,
구독 직후 이어지는 호출은 같은 물건이라 그대로 통과한다. 물건이 바뀐 경우라면 그때는
이어가지 **않는 것이 맞다**.

**[수정 2 — `registryBusy` 를 `[id]` 효과에서 내린다]**

여기서 함정이 하나 있었다. `finally` 에 가드를 붙이면(`if (idRef.current === requestId)`)
물건을 넘긴 뒤 **버튼이 "처리 중..." 에서 영원히 돌아오지 않는다.**

```
setFavBusy(false)      [id] 효과 안에 있다      -> 즐겨찾기는 안전했다
setRegistryBusy(false) [id] 효과에 **없었다**   -> 가드를 붙이는 순간 갇힌다
```

즉 등기부 쪽은 **가드 없는 finally 가 대신 내려 주는 것에 기대고** 있었다.
두 상태를 대칭으로 맞춰 `[id]` 효과에 `setRegistryBusy(false)` 를 넣었다.
*방어를 넣기 전에, 그 방어가 무엇에 기대고 있었는지 먼저 본다.*

**[검증]** await 이후의 모든 상태 쓰기가 가드 뒤에 오는지 함수 단위로 전수 확인했다.

```
performRegistryRequest / handleRegistryRequest / handleSubscribe /
handlePayOverage / handleDownloadRegistry / handleToggleFavorite   -> 6/6 OK
```

★ 처음 짠 확인 스크립트는 **한글 주석 안의 "await "** 를 코드로 읽어 오탐을 냈다
(주석에 *"busy 를 await 이전에 동기적으로 세운다"* 가 있다). 주석을 걷어내고 다시 쟀다.
*측정값이 뜻밖이면 코드보다 도구를 먼저 의심한다* — 이번 세션에서 두 번째다(#221).

**[수정 3 — 검사의 방향을 뒤집었다]** `tests/source-contract.test.mjs`

*"가드를 선언한 곳이 옳은가"* 대신 **"가드를 선언해야 하는 곳이 전부 선언했는가"** 를
본다. await 가 있고 그 뒤에 `set*` 를 부르는 함수를 전부 찾아, `requestId` 를 잡거나
인자로 받는지 확인한다.

**면제는 좁게 준다.** `requireToken()` 은 await 뒤에 `setAccessToken()` 하나만 쓰는데
그 값은 물건이 아니라 **사용자 세션 토큰**이라 늦게 반영돼도 틀리지 않는다. 그렇다고
이름만으로 통째로 빼 주면 나중에 물건에 딸린 쓰기가 들어와도 조용해진다 — #218 이
지적한 자리다. 그래서 **쓰는 상태의 이름까지** 고정했다.

```js
const GUARD_EXEMPT = { requireToken: ['setAccessToken'] }
```

**[변이 2/2 검출]**

```
Q1  등기부 핸들러의 requestId 선언 제거(= 수정 이전 상태)  -> 잡는다
Q2  면제 함수가 물건 상태(setRegistryMessage)를 쓰기 시작  -> 잡는다
       "387: requireToken -> setAccessToken, setRegistryMessage"
```

★ Q2 는 처음에 **놓친 것으로 나왔다.** 확인해 보니 치환이 `requireToken` 이 아니라
같은 문자열을 가진 **`[id]` 효과 쪽(이미 가드가 있는 곳)** 에 걸려 있었다. 변이가
의도한 자리에 실제로 갔는지부터 확인하고 다시 쟀다. **살아남은 변이를 먼저 의심하되,
변이 자체가 빗나갔을 가능성도 함께 의심한다.**

**[한계 — 정직하게 적는다]** 이 경합은 node --test 에서 **재현하지 못했다**(React
렌더러도 DOM 도 없고, 상세 화면은 로그인 필수라 브라우저 재현도 이 세션에서는 불가).
그래서 판정은 **소스 구조**로 한다 — 저장소가 `src/proxy.ts` 계약과 BUGS #210 에서
이미 쓰던 방식 그대로다. 실제 경합 재현은 다음 후보로 남긴다.

**[게이트]** tsc 0 / eslint 0 / node 196건 192 pass 0 fail 4 skip.

--------

#226

**`test_db_snapshot.py` 의 공허성 임계값이 실측 중앙값 위에 얹혀 있었다** — 15회 중 8회
실패하는 게이트였다. 그리고 **처음 고친 방법은 흔들림과 함께 검출력까지 없앴다**

발견·수정 (2026-08-26)

**[증상]** 전체 스위트에서 이 검사가 간헐적으로 붉어진다. 제품 코드와 무관하다.

```
[FAIL] 쓰기 스레드가 실제로 돌았다(검사가 공허하지 않다) -- -> 20회 커밋
```

**[원인 — 임계값이 하필 중앙값이다]**

이 단언의 목적은 하나다. *"쓰기 스레드가 정말 돌았는가"* = 위 일관성 검사가 공허하지
않은가. 그런데 기준이 **절대 커밋 수 `> 20`** 이었다. 같은 머신에서 15회 재 봤다.

```
15  16  18  18  18  20  20  20  21  21  22  22  23  23  25
최소 15 / 중앙값 20 / 최대 25
-> `> 20` 기준이면 15회 중 **8회 실패**
```

커밋 수는 제품이 정하는 값이 아니라 **그 순간의 머신 부하**가 정한다. 임계값을 분포의
한가운데 두면 동전 던지기가 된다. 이 저장소가 경계해 온 모양 그대로다 — **이유 없이
붉어지는 게이트는 결국 사람이 믿지 않게 된다.**

**[★ 처음 고친 방법이 틀렸다 — 흔들림과 검출력을 함께 없앴다]**

처음에는 *"동시성을 바라지 말고 만들자"* 고 판단해, 스냅샷마다 **직전에 커밋이 일어날
때까지 기다리게** 했다. 흔들림은 깨끗이 사라졌다(12회 중 0회 실패). 그런데 **그 고침이
검사를 죽였다.**

고친 것이 정말 나은지 확인하려고, 이 검사가 막으려던 상태(온라인 백업 API 대신
`shutil.copy2`)로 되돌리는 변이를 태웠다.

```
                          shutil.copy2 변이     정상 코드
HEAD 판(원래)               5회 중 **5회 검출**    5회 중 2회 **거짓 실패**
내 첫 수정(기다리기)         5회 중 **0회 검출**    5회 중 0회
최종 수정(임계값만)          6회 중 **6회 검출**   15회 중 0회
```

이유는 분명하다. **커밋이 끝난 직후에 사본을 뜨면 가장 조용한 순간을 고르는 셈**이다.
찢어짐은 복사가 **커밋 도중에 겹칠 때** 생기는데, 기다리게 만들면 그 겹침이 사라진다.
겹침이 이 검사의 전부였다.

> **여기서 배운 것** — 흔들리는 검사를 고칠 때 *"이제 안 흔들린다"* 는 성공 조건이
> **아니다.** 아무것도 검사하지 않으면 흔들리지도 않는다.
> **고친 검사에도 변이를 태워야** 검출력이 남아 있는지 알 수 있다.

**[최종 수정]** 스냅샷 루프는 **한 줄도 건드리지 않았다.** 임계값만 바꾼다.

```python
check_true("쓰기 스레드가 실제로 돌았다(검사가 공허하지 않다)",
           _writes[0] >= _ROUNDS,          # 스냅샷 1회당 평균 1커밋 이상
           "-> 스냅샷 %d회 동안 커밋 %d회 (기준 %d회 이상)" % (_ROUNDS, _writes[0], _ROUNDS))
```

절대 숫자(20) 대신 **스냅샷 횟수(12)에 묶는다.** 뜻이 분명해지고("스냅샷마다 평균
한 번은 썼다") 실측 최소 15 대비 여유가 생긴다. 쓰기 스레드가 죽은 경우(0~few)는
그대로 잡는다 — 공허성 방어의 목적은 그것이다.

**[검증]**

```
정상 코드          15회 중 실패 **0회**
shutil.copy2 변이   6회 중 실패 **6회**  (전부 검출)
```

**[남는 관찰]** 이 검사는 여전히 **타이밍에 기댄다** — 찢어짐을 잡으려면 복사와 커밋이
겹쳐야 하고, 그 겹침은 보장할 수 없다(보장하려 들면 위처럼 검출력이 사라진다).
지금은 12회 반복이 그 확률을 충분히 올려 주고 있다(변이 6/6). 언젠가 더 빠른 머신에서
검출률이 떨어지면 **반복 횟수를 늘리는 쪽**이지 동기화를 넣는 쪽이 아니다.

--------

#227

**할인 기간을 날짜가 아니라 문자열로 비교하고 있었다** — 월을 한 자리로 적으면
할인이 **끝나지 않거나 시작되지 않는다.** 오류도 로그도 없이 청구 금액만 달라진다

발견·수정 (2026-08-26, 결제 경로 Audit)

**[원인]** `api/v1/payments.py:_is_discount_active()` 가 이렇게 비교했다.

```python
today = (at or datetime.now()).date().isoformat()
if start and today < start:  return False
if end   and today > end:    return False
```

사전순 비교는 **`YYYY-MM-DD` 로 영점을 채웠을 때만** 시간순과 같다.

**[실측 — 두 방향 모두 조용히 틀린다]**

```
discount_end   "2026-9-1"  + 오늘 2026-10-05  ->  할인 적용 **True**   (기대 False)
    "2026-10-05" > "2026-9-1" 이 거짓이다('1' < '9') -> 할인이 영영 끝나지 않는다
    PRO 연간이면 274,800 받을 것을 **198,000 만 받는다**

discount_start "2026-9-1"  + 오늘 2026-09-15  ->  할인 적용 **False**  (기대 True)
    "2026-09-15" < "2026-9-1" 이 참이다('0' < '9') -> 할인이 시작되지 않는다
```

**[왜 지금 안 터졌나 — 그리고 왜 그래도 고치나]**

현재 `PLAN_CATALOG` 에는 `discount_start`/`discount_end` 를 쓰는 항목이 **하나도 없다.**
그래서 이 경로는 지금 죽어 있다. 그런데 그 표의 주석이 설계 의도를 직접 적고 있다 —

> *"향후 할인 이벤트를 붙일 때 이 카탈로그의 값만 바꾸면 되고 결제/검증 로직은
> 손대지 않아도 된다."*

즉 이 표는 **프로그래머가 아닌 사람이 고치는 것을 전제**로 한다. 이벤트를 하나 거는
순간 성립하고, 실패 모양이 **조용한 오과금**이다. 값만 바꾸라고 해 놓고 값이 틀리면
말없이 금액이 달라지는 구조를 남겨 둘 수 없다.

**[수정 1 — 판정을 날짜 객체로]** 문자열이 아니라 `date` 로 비교한다.
종료일/시작일 **당일 포함** 규약은 그대로다.

**[수정 2 — 표를 부팅에서 검증한다]** `validate_plan_catalog()` 를 신설하고
**모듈 최상단에서 실제로 부른다.** 이 표는 소스 리터럴이라, 여기서 raise 하면
배포 시점에 즉시 드러나고 **운영에 조용히 도달할 수 없다.**
*틀린 값으로 돈을 받느니 뜨지 않는 편이 낫다* — 이 저장소가 지켜 온 규칙 그대로다.

날짜 형식만 보지 않는다. 같은 표의 다른 값도 어긋나면 똑같이 조용히 금액을 바꾼다.

```
list_price        양의 정수인가
sale_price        양의 정수이고 **list_price 를 넘지 않는가** (할인이라며 더 받는 것을 막는다)
discount_percent  0 초과 100 미만인가 (100 이상이면 금액이 0 이하가 된다)
discount_start/end  'YYYY-MM-DD' 형식인가 / 시작이 종료보다 늦지 않은가
```

**[★ 형식 검사를 `date.fromisoformat` 하나로 두지 않은 이유]**

파이썬 3.11+ 의 `date.fromisoformat` 은 **대시 없는 기본 형식 `"20260901"` 도 받는다.**
그 값은 날짜로는 유효한데 **사전순과 시간순이 갈린다**(`"2026-09-15" < "20260901"` 이 참).
지금 판정은 날짜 객체로 하므로 당장은 문제가 없지만, 표에 그런 값이 들어오는 것 자체를
막아 두면 이 파일이 훗날 문자열 비교로 되돌아가도 조용히 틀리지 않는다.
그래서 문서가 약속한 **확장 형식(길이 10 + 대시 위치)** 만 받는다.

**[변이 6/7 검출 — 남은 하나는 동등 변이임을 증명했다]**

```
C1  검증 호출 제거(정의만 남긴다)            -> 잡는다
C3  뒤집힌 기간 허용                         -> 잡는다
C4  sale_price > list_price 허용             -> 잡는다
C5  discount_percent 범위 검사 제거          -> 잡는다
C6  list_price 검사 제거                     -> 잡는다
C8  형식 검사 제거(fromisoformat 만 쓴다)    -> 잡는다
C7  날짜 비교를 다시 문자열로(원래 결함)     -> 살아남음 ★ 동등 변이
```

C7 을 단정하지 않고 **재서** 판정했다. 확장 형식만 놓고 보면 사전순 == 시간순이다
(2024-01-01~2030-12-31 **2,557일 전수: 어긋난 쌍 0건**). 검증이 확장 형식만 통과시키므로
`_is_discount_active` 에 닿는 모든 입력에서 두 구현의 결과가 같다.

★ 그리고 **C7 이 동등한 것은 오직 C8 의 형식 검사가 있기 때문**이다. 형식 검사를 지우면
`"20260901"` 이 들어와 두 구현이 갈린다 — 그래서 C8 은 잡힌다. 둘이 짝으로 지켜지고 있다.

**[회귀 테스트]** `test_subscription_policy.py :: test_plan_catalog_rejects_silent_money_errors`
— 검사 25건. 실제 카탈로그가 통과하는지(전제) → 잘못된 값 14종을 **거부**하는지 →
정상 값 5종을 **거부하지 않는지**(과잉 방어면 이벤트를 못 건다) → 경계 4종
(시작/종료 당일 포함) → **모듈 최상단에서 검증을 실제로 부르는지**(AST 로 확인).

마지막 항목이 핵심이다 — 정의만 해 두면 아무것도 지키지 못한다.

**[영향 없음 확인]** 현재 가격은 그대로다.
`BASIC 12,900 / 154,800 · PRO 22,900 / 198,000`(연간 할인가 유지).

--------

#228

**출시 판단 문서의 `Last Updated` 가 19일 뒤처져 있었다** — 그리고 아무도 몰랐다

발견·수정 (2026-08-26)

**[증상]** `docs/BETA_RELEASE_CHECKLIST.md` 머리말.

```
Status: Active
Last Updated: 2026-08-07 (Sprint 28)     <- 실제 최신 절은 2026-08-26
```

**[왜 결함인가]** 이 문서는 **출시 가능 여부를 사람이 판단하는 자리**다. 머리말이
"3주 전 기준"이라고 말하면 읽는 사람은 그 안의 최신 실측까지 낡은 것으로 취급한다.
17만 자짜리 문서라 대개 검색으로 중간에 들어오는데, 그때 머리말 날짜가 유일한 신선도
단서다. `#223`(두 절이 동시에 최신을 주장)과 **같은 부류이되 기제가 반대**다 —
그쪽은 본문이 스스로를 최신이라 우겼고, 이쪽은 머리말이 본문보다 낡았다.

**[원인]** 손으로 적는 정적 필드인데 갱신을 강제하는 것이 아무것도 없었다.
2026-08-07 이후 이 문서에 절이 **17개** 더 붙는 동안 한 번도 바뀌지 않았다.

**[수정]**

1. `Last Updated: 2026-08-26` 으로 맞췄다.
2. 문서 맨 위에 **읽는 법** 안내를 넣었다 — 어느 절이 지금 사실인지, 머신을 먼저
   확인해야 한다는 것, P0 절이 기준이라는 것, 결함 상세는 `BUGS.md` 에 있다는 것.
   17만 자를 검색으로 들어오는 사람이 첫 화면에서 방향을 잡을 수 있어야 한다.

**[회귀 테스트]** `test_pipeline_integrity.py :: test_checklist_last_updated_matches_newest_section`
(11-e) — 머리말 날짜가 **날짜가 붙은 절 중 가장 최신**과 같은지 본다.

절 제목의 날짜만 센다(`^##+ ★* [YYYY-MM-DD`). 본문 아무 데나 있는 날짜까지 세면
인용된 옛 실측이 잡혀 검사가 못 쓰게 된다 — 자체 검증에서 그 구분을 못박았다.

11-d 와 마찬가지로 **머신과 무관하다.** 문서만 보면 판정되므로 개발 머신에서도 이빨이
그대로 남는다(BUGS #222 가 정리한 역할 게이트가 필요 없는 부류).

**[변이 2/2 검출]**

```
옛 날짜로 되돌린다(2026-08-07)     -> 잡는다
하루만 어긋나게 한다(2026-08-25)   -> 잡는다   (경계에서도 무디지 않다)
```

--------

#229

**경로 담기 가드가 "막아야 할 입력"에서 스스로 죽었다** — 서빙 라우트 3곳.
같은 함정을 저장소가 **이미 3곳에서 고쳐 놓고** 나머지 3곳을 빠뜨린 상태였다

발견·수정 (2026-08-26, 파일 서빙 경로 Audit)

**[증상]** `auction_image.storage_path` 에 다른 드라이브 경로가 들어 있으면
사진 서빙이 404 가 아니라 **예외를 그대로 흘려 500** 이 된다.

```
GET /api/v1/item/1/images/6   (storage_path = "D:/evil.txt")
  -> ValueError: Paths don't have the same drive     ★ 가드 안에서 터진다
```

**[원인 — 두 가지가 겹친다]**

```
os.path.join('C:/proj/documents', 'D:/evil')       ->  'D:/evil'     베이스가 통째로 갈린다
os.path.commonpath(['C:/proj/documents','D:/e'])   ->  ValueError    비교 자체가 불가능
```

즉 **가장 위험한 입력(루트 밖 절대경로)에서 담기 검사가 판정을 못 하고 붕괴한다.**
파일이 새지는 않았다 — 응답은 500 이고 내용은 나가지 않는다. 그러나 거절해야 할 것을
거절하지 못하고 죽는 것은 방어의 실패이며, 500 은 공격자에게 "여기서 뭔가 달랐다"는
신호를 준다.

**[★ 이 저장소는 이 함정을 이미 알고 있었다]**

`commonpath` 담기 검사 **6곳** 중 셋은 이미 ValueError 를 잡아 "밖"으로 처리하고 있었다.

```
막고 있던 곳                            빠져 있던 곳
api/v1/admin.py:263                     api/v1/images.py:83
crawler/image_assets.py:372             api/v1/documents.py:86
repair_document_status.py:90            api/v1/registry.py:360
```

빠진 셋이 하필 **사용자에게 파일을 내보내는 라우트 전부**다. 게다가
`api/v1/registry.py` 는 주석에 *"api/v1/documents.py 와 동일한 방식(commonpath 검사)"*
이라고 적고 그 **고쳐지지 않은 판을 베껴 왔다.**
복제된 판정은 결함까지 함께 복제된다 — BUGS #224 와 같은 모양이다.

**[재현]** 스크래치 DB 에 적대적 `storage_path` 9종을 넣고 실제로 서빙을 태웠다.
8종은 404 + 경고 로그로 정상 거절, `"D:/evil.txt"` 하나만 ValueError.
루트 밖 파일(`SECRET.txt`) 내용은 **어느 경우에도 나가지 않았다.**

**[수정]** 세 곳을 `api/v1/admin.py` 가 이미 쓰던 형태로 맞췄다 — 비교할 수 없는 경로는
"밖"으로 본다.

```python
try:
    outside = os.path.commonpath([real_root, real_path]) != real_root
except ValueError:
    outside = True
```

**[회귀 테스트]** `test_doc_path_safety.py` 에 둘을 넣었다.

- **9. 서빙 가드가 비교 불가 경로에서 죽지 않는다** — DB 에 적대적 값을 심고 사진/문서
  라우트를 실제로 태워 **404 이고 루트 밖 내용이 나가지 않는지** 본다(검사 13건).
  문서 쪽은 `court_name='D:'` 로 경로를 escape 시킨다(`get_doc_dir("D:",...)` ->
  `"D:2024타경1"` 실측).
- **9-b. 모든 `commonpath` 담기 검사가 ValueError 를 다루는가** — 라우트별로 세면
  **다음에 생길 네 번째**를 못 막는다. 결함이 "여섯 중 셋만 고쳐져 있었다" 였으므로
  제품 코드 전체를 훑어 맨 호출을 잡는다.

**[★ 내 가드가 먼저 거짓 양성을 냈다]**
9-b 를 처음 쓸 때 `"except ValueError"` 문자열만 봤다가 `crawler/image_assets.py:372`
를 결함으로 잡았다. 그 자리는 `except (OSError, ValueError)` **튜플 형태로 이미 막고
있었다.** 가드가 멀쩡한 코드를 결함이라 부르면 사람이 가드를 끈다 — 판정을
"except 줄에 ValueError 가 있는가"로 고치고, 자체 검증에 튜플 형태와
`except OSError`(ValueError 를 안 잡는 경우)를 함께 넣어 양방향을 못박았다.

**[변이 3/3 검출]** 세 파일을 각각 수정 이전으로 되돌리면 전부 붉어진다.

**[한계]** 도달 가능성은 낮다 — `storage_path` 는 크롤러가 상대경로로 쓰고,
`doc_url` 은 `admin.py` 가 (ValueError 안전한) 검사를 통과시킨 값만 저장한다.
그래도 고친 이유는 **이것이 방어 코드**이기 때문이다. 방어는 이상한 입력이 올 것을
전제로 존재하는데, 정작 그 입력에서 죽으면 존재 이유가 없다.

--------

#230

**시도 어휘가 세 곳에 복사돼 있는데 셋을 묶는 검사가 없었다** — 화면이 고르게 해 준
지역을 백엔드가 모르면 **오류도 안내도 없이 0건**이 된다

발견·수정 (2026-08-26, 설정→호출부→런타임 추적 중)

**[어떻게 눈에 띄었나]** `config/settings.py` 의 상수를 하나씩 *"정의 → 호출부 → 실행
경로 → 런타임 → 테스트 → 문서"* 로 훑던 중, `SIDO_LIST` 가 제품 코드에서 한 번도
import 되지 않는 것을 보고 파고들었다.

```
config/settings.py  SIDO_LIST       17개   ALL_COURTS.region 의 membership 어휘 (§9 가 검사)
SearchForm.tsx      SIDO_LIST       17개   **화면이 실제로 사용자에게 보여 주는 목록**
normalizer          SIDO_PATTERNS   17개   백엔드가 주소에서 알아볼 수 있는 어휘
```

세 벌인데 **어느 둘도 묶여 있지 않았다.** `SIDO_LIST` 자체는 죽은 설정이 아니었다 —
§9 가 `ALL_COURTS.region` 의 기준으로 쓰고 있었다. 죽은 것은 **셋 사이의 계약**이었다.

**[재현 — 실패가 조용하다]**

```
extract_sido("존재하지않는도")  ->  ''            (못 알아본다)
api/v1/search.py : `extract_sido(sido) or sido`  ->  **원본을 그대로** 쓴다
  -> WHERE sido = '존재하지않는도'
GET /api/v1/search?sido=존재하지않는도  ->  200, total **0**
```

오류도 경고도 없다. 사용자에게는 *"그 지역만 매물이 없구나"* 로 보인다 —
화면이 직접 고를 수 있게 해 준 값인데도. `api/v1/search.py:574` 주석이 이미 같은 계열의
사고를 적어 두었다(*"왜 구가 안 뜨지"*).

**[수정]** `test_schema_hygiene.py` §9 에 세 축을 묶는 검사를 넣었다.

```
화면 목록 == config SIDO_LIST (집합)      화면 목록에 중복 없음
★ 화면의 모든 시도를 normalizer 가 알아본다      화면 값이 그대로 정규화된다
```

**[★ 순서는 일부러 비교하지 않는다]**
처음에는 `check(..., fe, list(SIDO_LIST))` 로 **순서까지** 같으라고 썼고, 그것이
**멀쩡한 코드를 붉게 만들었다.** 두 목록은 값이 같고 순서만 다르다.

```
화면   서울 부산 대구 인천 광주 ...   (드롭다운 표시 순서 = UX 결정)
config 서울 경기 인천 부산 대구 ...   (membership 어휘, 순서에 의미 없음)
```

가드가 근거 없이 한쪽 순서를 강요하면 사람이 가드를 끄거나 UX 를 망가뜨린다.
같아야 하는 것은 **집합**이다. — 이번 세션에서 내 가드가 거짓 양성을 낸 두 번째다
(#229 의 `except (OSError, ValueError)` 에 이어).

**[변이 4/4 검출 — 두 축이 각각 잡는다]**

```
M1  화면에만 모르는 시도 추가        -> 잡는다 (집합)
M2  화면에서 시도 하나 제거          -> 잡는다 (집합)
M3  화면 목록에 중복 추가            -> 잡는다 (집합)
M4  화면 + config **양쪽에** 추가해
    집합을 통과시키고 normalizer 만 모르게 한다
                                     -> 잡는다 (**normalizer 축**)
```

★ M4 를 따로 만든 이유: M1~M3 은 전부 집합 검사가 먼저 잡아, **normalizer 축이 한 번도
발동하지 않았다.** 발동하는 것을 보지 않고 "축을 넣었다"고 하면 그 축은 있으나 마나다.
집합을 통과시키는 변이를 일부러 만들어 그 축만 붉어지는 것을 확인했다.

**[결함이 아니라고 판정한 것 — 같은 추적에서]**

```
COURTS (settings)          제품·테스트 어디서도 안 쓴다. 실동작은 config/courts.py ALL_COURTS(60개).
                           **이미 Sprint 19 에 dead code 로 기록**돼 있다(docs/crawler.md 등 4곳). 신규 아님
DOC_TYPE_LIST              제품이 안 쓰지만 `enqueue_documents()` 의 튜플과 **소스 대조로 묶여** 있다
DOC_WORKER_START_TIME      제품이 안 쓰지만 `register_scheduler_tasks.ps1` 등록 시각과 묶여 있다(Sprint 204)
PRIORITY_REFRESH_TIME      같음
DOC_COLLECT_SECONDS_PER_ROW 재수집 상한 산술의 입력. test_refresh_trigger §17 이 네 상수의
                           부등식을 검사하고, **자기 한계까지 주석으로 적어 두었다**
_BASE_BTN_ID               settings.py 안의 get_doc_button_id() 가 쓴다. 죽지 않았다
```

위 넷은 **설정↔스크립트/소스 계약**을 변이로 확인했다 — 값을 바꾸면
`test_schema_hygiene` 가 전부 붉어진다(**3/3**).

--------

#231

**"조회 창 >= 공급 상한" 검사가 오늘 기준 공허했다** — `getattr` 폴백 때문에
단언이 `X >= X` 가 되어 **어떤 값으로도 실패할 수 없었다**

발견·수정 (2026-08-26, 설정 동적 접근 추적 중)

**[어떻게 찾았나]** 설정 Audit 을 **grep 만으로 끝내지 않으려고** 동적 접근
(`getattr` / `vars` / `globals` / `__dict__`)을 따로 훑었다. 제품 코드에는 없었고,
테스트에서 딱 하나 나왔다.

```
test_max_items_contract.py:129
    lookup_win = getattr(cfg, "CASE_LOOKUP_MAX_ROWS", cfg.MAX_ITEMS)
```

`CASE_LOOKUP_MAX_ROWS` 는 **`config/settings.py` 에 존재하지 않는다.**

**[재현 — 실패할 수 없음을 증명했다]**

```
hasattr(cfg, "CASE_LOOKUP_MAX_ROWS")  ->  False
supply_cap = cfg.MAX_ITEMS = 10
lookup_win = 폴백 = cfg.MAX_ITEMS = 10      (같은 객체다: `supply is lookup` -> True)
단언 `lookup_win >= supply_cap`  ->  X >= X

MAX_ITEMS = 1 / 10 / 999 / 0 / -5  -> 전부 통과
```

**[왜 결함인가]** 앞을 내다본 의도 자체는 옳다 — 주석이 *"나중에 둘을 분리하더라도
이 관계는 반드시 지켜야 한다"* 고 적고 있고, 그 관계는 실제로 중요하다
(조회 창이 공급 상한보다 좁으면 **큐에 있는 사건을 목록에서 못 찾는다**, BUGS #174).

문제는 그 의도를 적어 두기만 하고 **오늘 검증력이 0 이라는 사실은 말하지 않았다**는 것이다.
읽는 사람은 `[PASS] ★ 조회 창이 공급 상한보다 좁지 않다` 를 보고 관계가 확인됐다고 믿는다.
이 저장소가 반복해 잡아 온 **"검증하지 않는 PASS"** 다.

**[수정]** 둘로 나눴다.

1. **지금 상태를 정직하게 보고한다** — 분리됐는지 아직 한 상수인지 찍는다.
   한 상수일 때는 `★` 단언을 **아예 걸지 않고**, 대신 *"이 조합에서는 검증력이 없다"* 고
   말한 뒤 그 전제(두 값이 같다)만 확인한다.
   *"검증했다"와 "검증할 것이 없었다"를 섞지 않는다.*
2. **오늘 이빨을 준다** — 판정을 `_lookup_window_ok(lookup, supply)` 한 함수로 빼고
   합성 값으로 실제로 태운다. 분리가 들어오는 날 이 검사가 동작한다는 것을 **지금 증명**한다.

판정 함수를 하나로 둔 이유는 늘 같다 — 실제 검사와 자기 검증이 각자 구현하면 갈라진다
(BUGS #204 / #224 에서 반복해 겪었다).

**[변이 4/4]**

```
M1  판정을 `<=` 로 뒤집는다                       -> 잡는다
M2  판정을 항상 True 로                           -> 잡는다
M3  `CASE_LOOKUP_MAX_ROWS = 5` 를 **실제로 추가**  -> 잡는다
      [FAIL] 조회 창 5 < 공급 상한 10 - 큐에 있는데 목록에서 못 찾는 사건이 생긴다
M4  `CASE_LOOKUP_MAX_ROWS = 50` 을 추가            -> **통과한다**(과잉 방어 아님)
```

★ M3 이 핵심이다 — `if split:` 분기가 **죽어 있지 않다**는 증명이다. 그 분기가 죽어
있으면 분리가 실제로 들어오는 날에도 아무 일이 일어나지 않는다. 합성 검증만 넣고
"이빨을 줬다"고 하면 그 분기는 여전히 미검증이다.

**[남는 사실]** `CASE_LOOKUP_MAX_ROWS` 는 여전히 존재하지 않는다. 즉 BUGS #174 가
지목한 *"하나의 손잡이가 공급 상한과 조회 창 두 가지를 돌린다"* 는 구조는 그대로다.
그 분리는 크롤 능력·큐 소진에 영향을 주는 **운영 판단**이라 여기서 하지 않는다.
이 검사는 이제 그날을 대비해 **실제로 동작할 준비가 된 상태**다.

--------

#232

**환경변수 문서의 상태표가 15일 낡아 있었고, "이름은 있는데 값이 비어 있다"는
가장 위험한 상태를 표가 아예 다루지 않았다**

발견·수정 (2026-08-26, 설정 Audit 의 환경변수 축)

**[증상 1 — stale]** `docs/ENVIRONMENT_VARIABLES.md` §A 표.

```
문서   `SUPABASE_JWT_SECRET` | ❌ 미설정(2026-08-11 재확인)
실측   설정됨 (len 88)                                    <- 15일 낡았다
```

**[증상 2 — 표가 다루지 않는 상태]** `.env` 실측(값은 찍지 않고 길이만).

```
SUPABASE_URL         이름 있음 / **값이 빈 문자열**   <- 표에 아예 없다
SUPABASE_ANON_KEY    이름 있음 / **값이 빈 문자열**   <- 표에 아예 없다
```

*"없음"* 과 *"이름은 있는데 비어 있다"* 는 다르다. `.env` 에 이름이 보이면 운영자는
설정됐다고 읽는다. 실제로는 빈 문자열이라 코드가 폴백으로 넘어가고, **그 폴백이 다른
파일(`.env.local`)에 의존한다는 사실이 가려진다** — BUGS #206 의 기제가 정확히 이것이다.
백엔드만 배포하며 `.env.local` 을 빠뜨리면 **로그인 사용자 전원 401** 이 된다.

**[증상 3 — 구조]** 이 표의 ✅/❌ 칸은 **머신마다 다른 사실**인데 git 이 추적하는 문서에
들어 있다. `.env` 는 추적 대상이 아니므로 다른 머신에서 이 표를 그대로 믿으면 안 된다 —
BUGS #222 가 `P0A-VERDICT` 에서 정리한 것과 **같은 부류**다.

**[수정]**

1. stale 행을 실측으로 고치고, `SUPABASE_URL` / `SUPABASE_ANON_KEY` 를 **"이름은 있는데
   값이 비어 있다"** 상태로 표에 추가했다(각각 #205/#206 로 연결).
2. 표 머리에 **"이 칸은 어느 한 머신의 한 시점 스냅샷"** 이라고 못박고, 머신과 무관한
   것은 *"없을 때 증상"* 칸뿐이며 **그쪽이 이 표의 본체**임을 적었다.
   지금 상태를 재려면 `python audit_auth_health.py`(읽기 전용).

**[회귀 테스트]** `test_bootstrap.py :: test_every_env_var_the_code_reads_is_documented`

★ 방향을 **한쪽만** 잡는다 — *"코드가 읽는 변수가 전부 문서에 있는가"*.
반대 방향(문서에는 있는데 코드가 안 읽음)은 검사하지 않는다. `KG_*` / `SMTP_*` /
`SENTRY_DSN` 등은 **아직 도입하지 않은 연동의 계획 항목**이고 문서가 §B/§C 로 그렇게
분류하고 있다. 그것까지 실패로 만들면 계획을 문서에 적을 수 없게 된다.

★ **머신과 무관하다** — `.env` 의 값은 보지 않는다. "코드가 이 이름을 읽는가"와
"문서가 이 이름을 아는가"만 본다(#222 의 교훈 적용).

**[★ 내 검출기가 두 번 틀렸고, 둘 다 실측으로 잡았다]**

1. **간접 참조를 놓쳤다.** 처음 정규식은 `os.getenv("X")` 직접 호출만 찾아
   `RATE_LIMIT_ENABLED` / `RATE_LIMIT_TRUST_FORWARDED` 를 **문서에만 있는 이름**으로
   오판했다. 그 둘은 `_env_flag("X", ...)` 로 **이름을 인자에 넘겨** 읽는다.
   `os.getenv` 를 감싸 **런타임 추적**으로 실제 읽힌 목록을 뽑아 확인하고 규칙을 넓혔다.
   *grep 결과만으로 결론 내리지 않는다* 를 그대로 적용한 자리다.

2. **부분 문자열에 속았다.** 문서 대조를 `name in doc` 로 썼다가 변이 M3
   (`RATE_LIMIT_TRUST_FORWARDED` -> `..._FORWARDEDX`)을 **놓쳤다** — 지운 이름이 새 이름의
   부분 문자열이라 여전히 "문서에 있다"로 읽혔다. 단어 경계 정규식으로 고치고,
   자체 검증에 그 함정을 못박았다.

**[변이 4/4 검출]**

```
M1  문서에 없는 변수를 **직접** 읽기 시작            -> 잡는다
M2  문서에 없는 변수를 **간접(_env_flag)** 으로 읽음  -> 잡는다
M3  문서의 이름을 더 긴 이름으로 바꾼다(부분 문자열)  -> 잡는다 (경계 수정 후)
M4  문서에서 이름을 통째로 지운다                    -> 잡는다
```

**[실측 결과]** 제품이 읽는 환경변수 **13개, 문서 누락 0건.**
런타임 추적으로도 12개(요청 경로에서 실제로 읽힘)를 확인해 정규식 결과와 대조했다.

--------

#233

**크롤이 "어느 법원 목록을 쓰는가"를 아무도 검사하지 않았다** — import 한 줄만 바꾸면
**60개 법원이 5개로 줄고 `court_code` 체계가 통째로 바뀌는데 전체 스위트가 통과한다**

발견·수정 (2026-08-26, 설정 Audit 의 dead code 영향 범위 추적 중)

**[출발점]** `config/settings.py:COURTS` 는 Sprint 19 에 dead code 로 기록돼 있다.
그 기록을 확인만 하고 넘어가는 대신 **"죽었다면 위험은 없는가"** 를 따져 봤다.

**[★ 죽었지만 위험하다 — 타입이 같아서 그대로 들어간다]**

```
config/settings.py  COURTS      5개   CourtInfo(code='B000210',       name='서울중앙지방법원')
config/courts.py    ALL_COURTS 60개   CourtInfo(code='서울중앙지방법원', name='서울중앙지방법원')

둘 다 List[config.settings.CourtInfo]  ->  run_courts(courts: List[CourtInfo]) 에 **타입 검사 없이 들어간다**
```

`crawler/court_crawler.py` 는 `court_code=court.code` 로 그 값을 **DB 에 그대로 쓴다.**

**[재현 — 변이가 스위트를 통과했다]**

`mvp_scraper.py` 의 import 한 줄을
`from config.settings import COURTS as ALL_COURTS` 로 바꾸고 크롤 관련 검사 9개를 돌렸다.

```
test_crawl_orchestration / test_schema_hygiene / test_crawl_exit_code /
test_court_crawl_recovery / test_max_items_contract / test_bootstrap /
test_pipeline_integrity / test_document_queue / test_auction_identity
  -> 새로 붉어진 검사 **0개**
```

(한 건이 잡힌 것처럼 보였으나 확인해 보니 **변이와 무관한 기존 #224 데이터 실패**였다.
변이 결과를 그대로 믿지 않고 변이 없이도 같은 실패가 나는지 대조해서 알았다.)

**[그 상태에서 벌어지는 일]**

```
크롤 대상    60개 법원 -> **5개**            55개가 조용히 사라진다(공급 붕괴)
court_code   '서울중앙지방법원' -> 'B000210'  이 저장소의 **code == name 전제가 깨진다**
             -> document_queue.court_code / get_doc_dir() / 문서·사진 서빙 경로가 전부 어긋난다
```

**[★ 2026-08-26 추가 추적 — 파급이 경로 어긋남에서 끝나지 않는다]**

`code == name` 은 장식이 아니라 **크롤과 문서 워커를 잇는 조인 키**다.
`crawler/base_crawler.py:go_to_case_detail()` 이 큐 행마다 이렇게 조회한다.

```python
court = next((c for c in ALL_COURTS if c.code == court_code), None)
if not court:
    logger.error("법원 코드 매칭 실패: %s", court_code)
    return False
```

실측:

```
court_code='서울중앙지방법원'  -> 매칭 성공
court_code='B000210'         -> ★ 매칭 실패 -> return False
```

즉 `settings.COURTS` 로 크롤하면 `document_queue.court_code` 가 `B000210` 이 되고
**모든 큐 행에서 이 조회가 실패해 문서 수집이 통째로 멈춘다.** 공급 붕괴(60->5)에 더해
**남은 5개 법원의 문서조차 한 건도 못 받는다.**

현재 실 DB 확인: `auction_case.court_code` / `document_queue.court_code` 표본 모두
한글 법원명이고, **ALL_COURTS 에 없는 court_code 는 0건**이다(전수 대조).

`test_schema_hygiene` §9 는 `ALL_COURTS` 를 **직접 import 해서** 검사하므로,
크롤이 다른 목록을 쓰기 시작해도 §9 는 그대로 초록이다. *목록이 옳은가* 는 봤지만
**크롤이 그 목록을 쓰는가** 는 아무도 보지 않았다.

**[수정]** §9 에 크롤이 **실제로 집는 것**을 못박았다.

```
크롤이 쓰는 목록이 config/courts.py 의 ALL_COURTS **바로 그 객체**인가 (is 비교)
그 목록의 법원 수가 60인가 / code == name 인가
settings.COURTS 와 **다른** 객체인가
run_courts 에 넘기는 인자가 **자르지 않은 맨 `ALL_COURTS`** 인가 (AST)
```

**[★ 모듈 변수만 보면 절반이다]**
처음에는 `mvp_scraper.ALL_COURTS is config.courts.ALL_COURTS` 만 봤다. 변이
`run_courts(ALL_COURTS[:5], ...)` 가 **그대로 통과했다** — 모듈 변수는 여전히 60개이기
때문이다. **실제로 넘기는 인자**를 구문 트리로 보게 고쳤다(슬라이스/필터/다른 이름을 가려낸다).

**[변이 3/3 검출]**

```
M1  import 를 settings.COURTS 로 갈아끼운다   -> 잡는다 (is 비교 + 법원 수 5)
M2  호출부에서 ALL_COURTS[:5] 로 자른다        -> 잡는다 (AST, 수정 후)
M3  호출부에서 서울만 필터링한다               -> 잡는다 (AST)
```

**[SKIP — `settings.COURTS` 삭제]** 제품 코드 삭제는 승인 영역이라 하지 않았다
(`docs/CLAUDE.md`: *"사용 여부가 확실하지 않은 코드는 임의로 삭제하지 않는다"*).
다만 **삭제 전까지의 위험은 이번 가드가 막는다** — 누가 그 목록을 크롤에 물리는 순간
붉어진다. 승인 시 할 일: `config/settings.py` 의 `COURTS` 제거 +
`docs/crawler.md` §220 의 dead code 서술 갱신.

--------

## 설정 전수 판정표 (2026-08-26, BUGS #230~#233 추적 결과)

`config/settings.py` 의 상수 10개를 *정의 -> 기본값 -> 로딩 -> 호출부 -> runtime path ->
데이터 공급 경로 -> 테스트/계약 -> 문서* 로 끝까지 따라간 결과다.
**"사용처 0건 = dead" 로 판정하지 않았다** — 간접 참조 / 동적 접근 / import 재노출 /
CLI 진입점 / 테스트 계약을 각각 따로 확인했다.

| 설정 | 판정 | 근거 (실측) |
|---|---|---|
| `MAX_ITEMS` | **runtime 사용** | `crawler/base_crawler.py:collect_list_items()` 가 실제로 자른다. 진짜 함수를 가짜 DOM 으로 태워 절단 확인(`test_max_items_contract` 3번) |
| `MAX_RETRY` | **runtime 사용** | `crawler/court_crawler.py:114` 의 재시도 루프. `test_court_crawl_recovery` 가 `2 + MAX_RETRY` / `3 * MAX_RETRY` 로 핀 |
| `_BASE_BTN_ID` | **runtime 사용(내부)** | 같은 파일의 `get_doc_button_id()` 가 쓴다. 외부 import 는 없지만 죽지 않았다 |
| `DOC_WORKER_END_TIME` | **runtime 사용** | `doc_worker.is_time_up()` 이 직접 읽는다 |
| `DOC_WORKER_START_TIME` | **테스트/계약용** | 제품 코드는 안 읽는다. `register_scheduler_tasks.ps1` 의 DocWorker 등록 시각과 묶여 있고(`test_schema_hygiene` 14-B), 재수집 상한 산술의 입력이다. **값을 바꾸면 붉어진다(변이 확인)** |
| `PRIORITY_REFRESH_TIME` | **테스트/계약용** | 같음 — `.ps1` 의 PriorityRefresh 시각과 대조 |
| `DOC_TYPE_LIST` | **테스트/계약용** | `storage/database.py:enqueue_documents()` 가 같은 목록을 튜플로 따로 들고 있고, `test_schema_hygiene` 가 **소스 텍스트로 대조**한다. 합치는 것은 별도 과제(Sprint 144 기록) |
| `DOC_COLLECT_SECONDS_PER_ROW` | **테스트/계약용** | `test_refresh_trigger` 17번의 부등식 입력(`상한 x 최악 행 수 x 행당 초 <= 실행 창`). 그 검사가 **자기 한계까지 주석으로 적어 두었다** |
| `SIDO_LIST` | **테스트/계약용** | `test_schema_hygiene` §9 가 `ALL_COURTS.region` 의 membership 어휘로 쓴다. **셋 사이의 계약이 없던 것이 BUGS #230** |
| `COURTS` | **★ dead (그러나 함정)** | 제품·테스트 어디서도 안 쓴다(전수: 정의 1곳 + 문서 언급 8곳). 실동작은 `config/courts.py:ALL_COURTS`(60개). **타입이 같아 바꿔 끼워지는 것이 BUGS #233** |

### 판정 방법 — grep 으로 끝내지 않은 부분

```
직접 참조      단어 경계 grep (전 파일 형식, 주석 포함)
간접 참조      `_env_flag("X", ...)` 처럼 **이름을 인자로 넘기는** 호출 -> 규칙 확장
동적 접근      getattr / vars / globals / __dict__  -> 제품 코드 **0곳**
import 재노출  `import config.settings as cfg` 후 `cfg.X`  -> 전수 확인
환경변수 주입   `os.getenv` 를 감싸 **런타임 추적**으로 실제 읽힌 12개 대조
CLI/스크립트   루트 스크립트 + `.ps1` + `.bat` 까지 포함해 검색
크롤 실행 경로  mvp_scraper -> run_courts -> court_crawler -> base_crawler -> storage 까지 추적
```

### `logs/*.py` 세 개 — 결함 아님 (기록만)

`logs/mvp_scraper.py` / `doc_worker.py` / `refresh_priority.py` 는 2026-08-03 자
**옛 사본**이다(실제 `mvp_scraper.py` 13,319바이트 vs 사본 4,444바이트).
Sprint 21 이 이미 dead 로 기록했다. **`logs/` 는 `.gitignore` 대상이고 셋 다 git
미추적**이라 배포에 실리지 않는다 — 로컬 잔재일 뿐이다. 삭제는 승인 영역.

### 승인이 필요해 하지 않은 것

| 항목 | 이유 | 승인 시 할 일 |
|---|---|---|
| `config/settings.py:COURTS` 제거 | 제품 코드 삭제는 승인 영역(`docs/CLAUDE.md`) | 상수 제거 + `docs/crawler.md` §220 / `CHANGELOG` 의 dead code 서술 갱신. **삭제 전까지의 위험은 BUGS #233 가드가 막는다** |
| `logs/*.py` 사본 3개 제거 | 파일 삭제는 승인 영역 | git 미추적이라 배포 영향 없음. 정리만 하면 된다 |

--------

#234

**가격 해석 함수가 두 벌이었다** — `validate_batch()` 가 쓰는 것과 `normalize_batch()` 가
쓰는 것이 따로 있었고, **한쪽만 고치면 "검증은 통과했는데 저장된 금액이 다른" 상태**가 된다

발견·수정 (2026-08-26, 중복 로직 전수 탐색)

**[어떻게 찾았나]** 중복 판정을 세 번(#224/#229/#230) 연달아 만나 **의도적으로** 찾았다.
제품 코드의 모든 함수 본문을 독스트링 제거 후 **AST 해시**로 묶었다.

```
본문이 완전히 동일한 함수 쌍: 1組
  normalizer/normalizer.py::normalize_price  ==  validator/validation_engine.py::parse_price
```

**[왜 위험한가 — 파이프라인의 서로 다른 단계다]**

```
mvp_scraper.py:187   engine.validate_batch(all_items)   -> parse_price       PASS/FAIL 판정
mvp_scraper.py:191   normalize_batch(all_items)         -> normalize_price   **DB 에 저장할 값**
```

같은 문자열을 **다른 함수로** 해석한다. 둘이 갈라지면 검증은 옛 규칙으로 통과시키고
저장은 새 규칙으로 한다. 가격은 `minimum_bid_price` / `appraisal_price` 라
**화면·검색 필터(min/max_bid_price)·낙찰가율**이 전부 그 값을 쓴다.

**[★ 바로 위 주석이 같은 문제를 이미 적어 두었다]**

`validation_engine.py` 의 `extract_sido` 재노출 위에는 이런 주석이 있다 —
*"같은 판정을 하는 함수가 두 벌이면 한쪽만 고쳐질 수 있다 ... 크롤 데이터는 제주로
저장되는데 검증은 세종으로 판정하는 상태가 됐을 것이다."*
**그 바로 아래 함수가 정확히 그 상태로 남아 있었다.**

**[재현 — 중복이 실제로 불일치를 가린다]**

`normalize_price` 의 규칙만 바꾸고(괄호 뒤를 버리지 않게) 두 검사를 돌렸다.

```
[수정 이전 = 사본이 있는 상태]
  test_validation_engine.py   exit=0   ★ 초록 — 불일치를 못 본다
  test_normalizer.py          exit=1   붉음

[수정 이후 = 재노출]
  test_validation_engine.py   exit=1   [FAIL] parse_price: 괄호 뒤는 버린다(보증금 표기)
                                              80000000080000000 (expected 800000000)
  test_normalizer.py          exit=1   붉음
```

즉 **고치기 전에는 두 벌이 갈라져도 검증 쪽 검사가 초록이었다.**

**[수정]** `extract_sido` 와 **같은 방식**으로 재노출한다.

```python
from normalizer.normalizer import normalize_price as parse_price  # noqa: E402  (재노출)
```

- 방향이 이미 성립해 있다(`validation_engine` -> `normalizer`), 순환 없음
  (`normalizer` 는 `validator` 를 import 하지 않는다 — 확인함).
- **기존 계약 유지**: `from validator.validation_engine import parse_price` 를 쓰던
  `test_validation_engine.py` 가 그대로 동작한다(`parse_price is normalize_price` -> True).
- 동작 무변경: 입력 12종(빈 값/`-`/콤마/괄호/한글 단위/None/20자리)에서 **차이 0건**.

**[회귀]** `test_validation_engine` / `test_normalizer` / `test_validation_log_integrity`
전부 통과. 위 재현이 곧 회귀 검증이다 — 한쪽만 바뀌면 이제 **양쪽이 붉어진다.**

**[남은 이름 중복 — 결함 아님]**

```
build_driver      collect_documents.py / crawler/base_crawler.py
attach_file_log   collect_documents.py / mvp_scraper.py
main              doc_worker.py / mvp_scraper.py / refresh_priority.py
```

`main` 은 진입점이라 같은 이름이 정상이다. 나머지 둘은 **본문이 다르다**(AST 해시가
갈렸다 — 위 "완전히 동일한 쌍" 목록에 없다). 별도로 볼 항목이지 이번 결함은 아니다.

--------

## 바꿔 끼울 수 있는 쌍 전수 탐색 (2026-08-26, BUGS #233 후속)

#233 이 드러낸 위험은 *"타입이 같으면 서로 바꿔 끼워도 아무도 못 잡는다"* 였다.
그 계통이 더 있는지 **의도적으로** 찾았다 — 제품 코드의 모듈 수준 컨테이너 상수 **59개**를
`(컨테이너 종류, 원소 종류)` 로 묶어 같은 모양이 둘 이상인 그룹을 뽑았다.

```
[Dict]            25개
[Tuple of str]    14개
[List of str]      5개
[List of CourtInfo] 2개   <- #233 (ALL_COURTS / settings.COURTS)
```

같은 모양이라고 다 위험한 것은 아니다. **키 공간이 달라 바꿔 끼우면 큰 소리로 죽는 것**은
제외하고, *용도가 인접해 조용히 틀릴 수 있는* 쌍만 골라 실제로 맞바꿔 봤다.

| 쌍 | 바꿨을 때 | 검출 |
|---|---|---|
| `ALL_COURTS` / `settings.COURTS` | 크롤 60개->5개, court_code 체계 붕괴, **문서 수집 전면 중단** | ★ **없었다 -> BUGS #233 로 봉인** |
| `_BUILDING_HEADS` / `_LAND_HEADS` | 건물면적과 토지면적이 **통째로 뒤바뀐다**(조용함) | `test_normalizer` 가 잡는다 |
| `_ALLOWED_SYMMETRIC_ALGS` / `_ALLOWED_ASYMMETRIC_ALGS` | HS256/ES256 검증 경로가 뒤바뀐다(**보안**) | `test_auth_jwks_robustness` / `test_item_detail_auth` 가 잡는다 |
| `PAYMENT_TRANSITIONS` / `SUBSCRIPTION_TRANSITIONS` | 결제·구독 상태 전이 규칙이 뒤바뀐다(**돈**) | `test_race_conditions` 가 잡는다 |

**결론: #233 이 유일한 구멍이었고, 지금은 닫혀 있다.**

### ★ 변이를 두 번 잘못 만들었다 — 둘 다 결과를 의심해서 잡았다

1. **면적 머리말 변이가 적용되지 않았다** — 바이트 리터럴로 치환하려다 실패했는데
   하네스가 `[NOT-APPLIED]` 로 알려 줬다. 텍스트로 다시 치환해 정상 검출.
   *치환이 실제로 적용됐는지 확인하지 않으면 "검출 0"을 "가드 없음"으로 오독한다.*

2. **전이표 변이가 알파 치환이었다** — 두 이름을 서로 바꿨더니 **사용처까지 함께 바뀌어**
   의미가 동일한 프로그램이 됐다(그래서 당연히 검출 0). 이름이 아니라 **값**을 맞바꾸도록
   고치니 즉시 잡혔다. *변이가 정말 의미를 바꿨는지부터 확인한다.*

### 하네스 — 기준선 차집합

이 탐색은 전부 `mutated - baseline` 으로만 판정했다(#224 기존 실패 3건을 매번 명시적으로
제외). 문자열로 거르던 예전 방식이 두 번 오판을 냈기 때문이다.
매 변이마다 **복원 후 기준선과 동일함**까지 확인했다.

--------

#235

**"추적 파일이 미추적 파일을 import 하지 않는다" 검사가 오늘 아무것도 하지 않으면서
`[PASS]` 를 찍고 있었다**

발견·수정 (2026-08-26, 공허한 PASS 전수 탐색)

**[어떻게 찾았나]** #231(공허한 단언)을 일반화해, 테스트 전체에서 **구조적으로 항상 참인
단언**을 AST 로 훑었다. 후보 22건 중 21건은 정상 관용구였고(아래 참고) 1건이 남았다.

```
test_schema_hygiene.py 6-B
    if not patterns:
        print("   미추적 소스 파일이 없다 - 검사할 간선 없음")
        check("추적 파일이 미추적 파일을 import하지 않는다", [], [])   <- 항상 참
        return
```

**[실측]** 지금 이 저장소는 미추적 `.py/.ts/.tsx` 가 **0개**다(`git ls-files --others
--exclude-standard`, `.gitignore` 대상 제외). 그래서 이 검사는 **패턴 매칭 코드를 한 줄도
실행하지 않고** `[PASS]` 를 남긴다.

`run_python_tests.py` 를 만들면서 세운 규약이 *"통과와 무판정을 절대 합치지 않는다"* 인데,
**검사 안에서 그 규약을 어기고 있었다.**

**[왜 중요한가]** 이 가드는 P0-B(*"커밋하면 API 가 부팅되지 않는다"*, BUGS #105)를 막는
자리다. 평소에는 늘 0건이라 초록인데, **정작 필요한 날 동작한다는 보장이 없다.**

**[수정]** 패턴 만드는 규칙을 `_py_pattern()` / `_web_pattern()` 으로 빼고,
**합성 입력으로 그 규칙을 실제로 태운다**(검사 9건).

```
from api.qa_ghost_module import x    -> 간선     from api.other_module import x   -> 아님
import api.qa_ghost_module           -> 간선     # from api.qa_ghost_module ...   -> 아님(주석)
from api import qa_ghost_module      -> 간선     qa_ghost_module_lookalike = 1    -> 아님
from .qa_ghost_module import x       -> 간선     (web) 다른 컴포넌트 import        -> 아님
```

규칙을 함수로 뺀 이유는 늘 같다 — 자기 검증이 규칙을 **다시 적으면** 한쪽만 바뀌는 날
서로 다른 것을 확인하게 된다(BUGS #224/#234 에서 겪은 실수).

미추적 파일이 0개일 때는 이제 `check(..., [], [])` 를 **찍지 않고**
*"자기 검증이 대신 증명한다"* 고 밝힌다.

**[검증 — 진짜 경로도 동작한다]**
합성 검증만으로는 "실제 탐지 경로가 살아 있는가"를 말할 수 없다. 미추적 모듈을 실제로
만들고 추적 파일이 그것을 import 하게 해서 끝까지 태웠다.

```
[FAIL] 추적 파일이 미추적 파일을 import하지 않는다:
       ['api/rate_limit.py:44 -> api/qa_ghost_module.py']
   ★ 커밋하면 깨지는 간선 1개  /  미추적 소스 1개 대상으로 추적 파일 194개 검사
```

**[★ 그 검증을 처음에는 잘못했다]**
첫 시도에서 `[PASS]` 가 나와 "탐지 경로가 죽었다"고 볼 뻔했다. 원인은 제품이 아니라
**변이가 적용되지 않은 것**이었다 — `api/rate_limit.py` 는 CRLF 인데 `b"import os
"` 로
치환을 시도했다. 삽입 여부를 먼저 단언하도록 고치니 즉시 검출됐다.
*"검출 0"을 곧바로 "가드 없음"으로 읽지 않는다 — 변이가 실제로 적용됐는지부터 본다.*

**[함께 판정한 나머지 21건 — 전부 정상]**

```
ids_of(path) == ids_of(path) x2   매 호출이 **실 HTTP 요청**이다. 동률 타임스탬프 3행을
                                  심어 두고 **정렬 결정성**을 검사한다. 오탐
mod._lock() is not mod._lock()    매번 새 객체여야 한다는 의미 있는 단언. 오탐
check_true(..., True) 9건 /       전부 `except` 블록의 "예상한 예외가 떴다" 성공 마커,
check(name, True, True) 6건        또는 라이브러리가 공격 벡터 자체를 막는 문서화된 폴백
```

**[분류]** 제품 결함이 아니라 **검사 품질 결함**이다. 사용자 영향 없음.

--------

#236

**경계 변이(`>=`/`<=`) 캠페인** — 살아남은 변이 3건을 조사해 **2건은 계약을 고정하고
1건은 무해함을 근거와 함께 남겼다.** 그 과정에서 **내 변이 하네스의 맹점**도 찾았다

발견·수정 (2026-08-26, 테스트 검증력 실측)

**[방법]** *"mutation 을 넣어도 실패하지 않는 테스트"* 를 추측이 아니라 **재서** 찾았다.
제품 코드의 경계 비교(`>=` / `<=`) **34개**를 세고, 돈·보안 모듈부터 한 지점씩 뒤집어
소유 테스트를 돌렸다(판정은 기준선 차집합).

**[★ 먼저 하네스가 틀렸다 — 크래시를 "생존"으로 셌다]**

첫 실행에서 `rate_limit.py:101` (`if limit <= 0`)이 생존으로 나왔다. 그런데
`test_rate_limit.py` 에는 *"RATE_LIMIT_PER_MINUTE=0 이면 제한하지 않는다"* 가 있다.
앞뒤가 맞지 않아 직접 태워 봤더니:

```
limit=0 + 변이  ->  len(bucket)=0 >= 0  ->  bucket[0]  ->  IndexError: deque index out of range
test_rate_limit.py  exit=1  그러나 [FAIL] 줄은 **0개**
```

**크래시는 `[FAIL]` 줄을 남기지 않는다.** `[FAIL]` 만 세던 하네스가 그것을 "새 실패 없음"
= 생존으로 읽었다. **종료코드도 신호로 세도록** 고치니 생존이 4건 -> 3건으로 줄었다.
*검출기가 놓치는 신호가 무엇인지부터 확인한다.*

**[살아남은 3건 판정]**

| 지점 | 차이 | 판정 |
|---|---|---|
| `rate_limit.py:115` `bucket[0] <= cutoff` | `now-60` 과 **정확히 같은** 시각이 만료되는가 | **계약 고정함** |
| `payments.py:653` `refundable <= 0` | 잔여가 **정확히 0** 일 때의 **오류 코드** | **계약 고정함** |
| `rate_limit.py:110` `len(_hits) >= _max_clients` | 축출이 10,000 vs 10,001 에서 시작 | **무해 — 고치지 않음** |

**[고친 것 1 — 슬라이딩 창의 포함 경계]** `test_rate_limit.py`

기존 검사는 159.0 / 161.0 / 161.1 만 봐서 **`now - 60.0` 과 정확히 같은 시각**을 한 번도
지나지 않았다. 포함 경계(`<=`)와 배타 경계(`<`)를 가르는 유일한 입력이 그것이다.

```
100.0 에 넣은 요청 -> now=160.0 (== 160-60) 에서 **만료여야** 한다      -> 자리가 난다
                     now=159.999 에서는 **아직 만료가 아니어야** 한다   -> 막힌다
```

양방향으로 넣었다 — 한쪽만 넣으면 경계를 반대로 옮기는 변이를 놓친다.

**[고친 것 2 — 잔여 0 환불의 오류 코드]** `test_admin_failure_injection.py`

변이본에서도 환불은 **거절된다**(뒤의 `amount <= 0` 에 걸린다). 돈은 새지 않는다.
다만 **오류 코드가 바뀐다**.

```
정상  PAY_ALREADY_PROCESSED  "환불 가능한 잔액이 없습니다"
변이  PAY_AMOUNT_MISMATCH    "환불 금액은 1원 이상이어야 합니다"
```

`docs/ERROR_CODES.md` 가 두 값을 **서로 다른 의미로 정의한** 공개 계약이고, 운영자는
그 문구로 원인을 찾는다. 잘못된 코드는 원인을 엉뚱한 데서 찾게 만든다.

검사는 **부분 환불로 전액이 이미 나갔지만 status 는 PARTIAL_REFUND 인** 결제를 만든다 —
status 가 REFUNDED 면 위쪽 멱등 분기에서 먼저 끝나 이 경로에 닿지 못하기 때문이다.

**[고치지 않은 것 — 근거]** `rate_limit.py:110` 은 추적 클라이언트가 **10,000개일 때
축출하느냐 10,001개일 때 하느냐**의 차이다. 상한의 목적(무한 증가 방지)은 그대로 지켜지고
정확성에 영향이 없다. **1개 차이를 위해 검사를 만들면 검사만 늘고 지켜지는 것은 없다.**
동등 변이는 아니지만 **무해하다고 판정**하고 근거를 남긴다.

**[변이 검증]**

```
창 경계 <= -> <          -> 잡는다  [FAIL] cutoff 와 정확히 같은 시각의 요청은 만료로 본다
환불 잔여 <= -> <        -> 잡는다  [FAIL] 잔여 0 의 오류 코드는 PAY_ALREADY_PROCESSED 다
                                    (변이본이 PAY_AMOUNT_MISMATCH 를 낸 것까지 출력에 남는다)
축출 경계 >= -> >        -> 생존(의도적으로 두었다, 위 근거)
```

**[검출된 경계 5건 — 이미 지켜지고 있었다]**
`limit <= 0`(제한 해제) / `len(bucket) >= limit`(상한) / `amount <= 0`(환불 최소액) /
`list_price <= 0` / `sale <= 0`(카탈로그 검증, BUGS #227). 전부 소유 테스트가 잡는다.

**[분류]** 제품 결함 아님. **테스트 검증력 개선**이다.

--------

#237

**`calc_priority` 경계 검사가 이름과 다른 값을 보고 있었다** — "3일 뒤 / 7일 뒤" 라는
이름의 검사가 실제로는 `days_left=2 / 6` 을 보고 있어 **경계에 한 번도 닿지 않았다**

발견·수정 (2026-08-26, 경계 변이 캠페인 완주)

**[발견 경로]** `days_left <= 3` / `<= 7` 변이가 **둘 다 살아남았다.** 그런데
`test_document_queue.py` 에는 *"3일 뒤 -> 최우선(1)"* / *"7일 뒤 -> 2순위"* 가 있었다.
앞뒤가 맞지 않아 값을 직접 쟀다.

**[원인 — 자정과 현재 시각의 차이가 하루를 먹는다]**

```python
target    = datetime.strptime(auction_date, "%Y-%m-%d")   # **자정**
days_left = (target - datetime.now()).days                # now 에는 시각이 붙어 있다
```

`timedelta.days` 는 내림이므로 **`days_left = (달력 일수) - 1`** 이 된다.

실측(2026-08-26 18:21 기준):

```
after(3) -> days_left=2    after(7) -> days_left=6     <- 검사가 쓰던 값. 경계가 아니다
after(4) -> days_left=3    after(8) -> days_left=7     <- **진짜 경계**
```

즉 *"3일 뒤"* 라는 이름의 검사는 `2 <= 3` 을 보고 있었고, 경계를 한 칸 옮겨도(`< 3`)
`2 < 3` 이 여전히 참이라 **통과했다.** 이름과 검증 내용이 어긋난 자리다.

**[제품 동작은 바꾸지 않았다]**
`days_left` 의 정의를 바꾸면 큐 정렬이 통째로 달라지는 **정책 변경**이고, 지금 코드가
스스로 일관되지 않다는 근거는 없다(같은 날 안에서는 시각과 무관하게 같은 값이 나온다 —
확인함). 여기서 할 일은 **경계가 어디인지 정확히 못박는 것**이다.

**[수정]** 진짜 경계와 그 바로 밖을 양쪽으로 넣고, **오프셋 자체**를 고정했다.

```
★ days_left=3 (달력 4일 뒤) -> 1        ★ days_left=4 (달력 5일 뒤) -> 2
★ days_left=7 (달력 8일 뒤) -> 2        ★ days_left=8 (달력 9일 뒤) -> 3
★ days_left = 달력일수 - 1 이라는 전제가 유지된다
```

마지막 줄이 중요하다 — 훗날 기준이 자정에서 now 로 바뀌면 위 경계 검사도 함께 옮겨야
하는데, 그 전제가 깨지는 순간 이 검사가 먼저 알려 준다.

**[변이 재검증]**

```
days_left <= 3  ->  < 3   잡는다  [FAIL] 경계: days_left=3 (달력 4일 뒤) -> 최우선(1): 2 (expected 1)
days_left <= 7  ->  < 7   잡는다  [FAIL] 경계: days_left=7 (달력 8일 뒤) -> 2순위: 3 (expected 2)
```

---

### 경계 변이 캠페인 최종 집계 (34개 전수)

| 결과 | 수 | 내용 |
|---|---|---|
| **검출** | 9 | `limit<=0` `len(bucket)>=limit` `amount<=0` `list_price<=0` `sale<=0` `seq<=0` `len(data)>=26` `size<=0`(0바이트) `new_retry>=MAX_DOC_RETRY` |
| **수정함** | 4 | 창 포함 경계 · 잔여 0 환불 코드(#236) · `days_left<=3` · `<=7`(#237) |
| **무해 판정** | 6 | 아래 |

**무해로 판정하고 고치지 않은 것 — 근거를 남긴다**

```
rate_limit:110  축출 임계 10,000 vs 10,001   상한의 목적(무한 증가 방지)에 영향 없음
image_assets:132/188/194  매직바이트 길이 12/24/10 경계   실제 이미지는 그보다 훨씬 크다.
                          그 길이의 입력은 이미 앞단 검사에서 걸러진다
image_assets:306  seq<=0   같은 검증이 L114 에 있고 **그쪽은 검출된다**(중복 방어)
image_assets:325  getsize >= MIN_IMAGE_BYTES(1024)   정확히 1024바이트인 파일.
                  문서 쪽(`> 0`)과 임계가 다른 것은 **의도**다(잘린 이미지 배제)
database:580/1883  cap=0 / max_rows=1   호출부가 그 값을 넘기는 경로가 없다
```

**★ 이 캠페인에서 내 검출이 두 번 틀렸다**

1. **크래시를 "생존"으로 셌다** — `limit <= 0` 변이는 `IndexError` 로 죽는데
   `[FAIL]` 줄이 안 남아 하네스가 못 봤다. **종료코드도 신호로** 세도록 고쳤다(#236).
2. **소유 테스트를 빠뜨렸다** — `size <= 0`(0바이트 가드)이 생존으로 나왔는데,
   그 가드를 검사하는 `test_asset_pipeline.py` / `test_collect_documents.py` 를
   테스트 집합에 넣지 않았기 때문이었다. 제대로 넣으니 **즉시 검출**된다
   (`0바이트 파일은 doc_raw를 만들지 않는다`).

둘 다 **"생존" 을 곧바로 "검증력 없음" 으로 읽지 않아서** 잡았다.
survivor 는 결함의 증거가 아니라 **조사의 시작점**이다.

--------

#238

**`image_exists()` 의 docstring 이 하한과 비교 방향을 둘 다 틀리게 적고 있었다** —
그대로 믿고 `>=` 를 `>` 로 "고치면" **정확히 1024바이트인 사진을 조용히 잃는다**

발견·수정 (2026-08-26, 경계 변이 survivor 3개 lead 확정)

**[출발]** 경계 변이 `getsize(path) >= MIN_IMAGE_BYTES` -> `>` 가 살아남았다.
docstring 을 읽어 보니 코드와 다른 말을 하고 있었다.

```
docstring   "doc_paths.doc_exists() 와 **같은 기준**을 쓴다 - 존재 + 크기가 하한 **초과**"
코드         os.path.getsize(path) >= MIN_IMAGE_BYTES        하한 1024, **이상**
doc_exists   os.path.getsize(path) > 0                       하한 0,    **초과**
```

**두 군데가 틀렸다** — 하한이 "같은 기준"이 아니고(0 vs 1024), 방향도 "초과"가 아니다(이상).

**[실측 — 값으로 확정했다]** 실제 파일을 만들어 태웠다.

```
사진   0 -> False   1023 -> False   **1024 -> True**   1025 -> True
문서   0 -> False      1 -> True     1023 -> True
```

**[판정 — DOCUMENTATION DRIFT. 코드는 옳다]**

*"docstring 과 코드가 다르다"* 만으로 결함으로 몰지 않고 호출 관계까지 확인했다.

```
쓰기   crawler/image_assets.py:image_exists()   getsize >= MIN_IMAGE_BYTES   (수용)
서빙   api/v1/images.py:99                      getsize <  MIN_IMAGE_BYTES   (거절)
```

**서빙이 쓰기의 정확한 여집합**이라 두 쪽이 어긋나지 않는다. 상수도 서빙이 하드코딩하지
않고 `from crawler.image_assets import MIN_IMAGE_BYTES` 로 같은 값을 쓴다.
하한이 문서(0)와 다른 것도 **의도**다 — 1KB 미만은 잘린 내려받기라 뷰어가 열지 못한다.

즉 **코드는 세 곳이 일관되고 docstring 만 부정확했다.**

**[왜 그래도 고쳤나]** 이 docstring 은 *"쓰는 쪽과 읽는 쪽의 '있다' 정의가 갈라지면
화면은 READY인데 뷰어는 404가 된다"* 고 경고하는 자리다. 그 자리에서 **"초과"라고 적어
두면 다음 사람이 `>=` 를 `>` 로 정정한다** — 그 순간 정확히 1024바이트인 사진이
`image_exists=False` 가 되어 조용히 사라진다. 문구가 곧 함정이었다.

**[수정]** docstring 에 **값과 방향을 명시**하고, 서빙이 여집합이라는 사실도 함께 적었다.

**[회귀 테스트]** `test_doc_path_safety.py :: test_existence_size_floor_is_exact` — 검사 11건.
`MIN_IMAGE_BYTES` 를 상수에서 읽어 **실제 파일**로 하한-1 / 하한 / 하한+1 / 0 을 태우고,
문서 쪽 하한(0)도 함께 고정한다. 서빙이 같은 상수를 쓰는지와 **여집합인지**도 소스로 못박는다.

**[★ 그리고 세 번째 다리를 놓치고 있었다]**

처음에는 쓰기(`image_exists`)와 서빙 둘만 못박았다. 그런데 변이
`storage/database.py:save_auction_images` 의 `size < MIN` -> `<=` 가 **살아남았다.**

그 자리는 `auction_image` **행을 만드는 단계**다. 어긋나면 #148 의 **정반대**가 된다.

```
정확히 1024바이트 사진 -> 파일은 디스크에 있고 서빙도 200 인데
auction_image 행이 **안 생긴다** -> image_count=0 / 썸네일 없음
=> 받아 놓고도 사용자에게 영원히 안 보인다
```

`api/v1/thumbnails.py` 는 크기를 보지 않고 `auction_image` 행만 읽으므로, 이 단계가
어긋나면 목록·상세·서빙이 서로 다른 말을 한다. **판정자가 셋이고 셋 다 같아야 한다.**

**[런타임 전 구간 실측 — 여섯 지점이 같은 경계를 쓴다]**

```
bytes   크롤러수용   image_exists   DB기록   서빙
1023    False       False          생략     404
1024    True        True           기록     200
1025    True        True           기록     200
```

**[변이 5/5 검출]**

```
쓰기      >= -> >     잡는다  [FAIL] 사진 1024바이트 -> image_exists: False (expected True)
서빙      <  -> <=    잡는다  [FAIL] 서빙의 거절 조건이 여집합이다
DB기록    <  -> <=    잡는다  [FAIL] DB 기록의 거절 조건이 `< MIN` 이다
DB기록    상수 대신 자기 숫자   잡는다  [FAIL] 정본 상수를 **import** 한다
썸네일    크기 판정을 갖는다    잡는다  (판정자가 넷이 되는 것을 막는다)
```

세 방향을 모두 넣은 이유는 **한쪽만 옮겨도 갈라지기 때문**이다.

**[★ 소스 검사만으로는 부족하다 — 런타임 end-to-end 검사를 덧붙였다]**

위 검사들은 *"세 다리가 같은 상수·같은 방향을 쓰는가"* 를 **소스로** 본다. 그것만으로는
**정말 그렇게 동작하는가**를 말할 수 없다 — 경로 해석·호출 순서·조기 반환이 끼면
소스가 옳아도 결과가 다를 수 있다.

그래서 임시 DB + 임시 documents 루트에서 `save_auction_images()` 를 **실제로 불러**
하한-1 / 하한 / 하한+1 이 네 지점에서 어떻게 되는지 한 번에 본다.

```
bytes   saved   auction_image행   썸네일seq   서빙
1023      0            0           None      404     <- #148 이 성립 불가
1024      1            1           있음       200
1025      1            1           있음       200
```

`1023` 에서 **썸네일이 없다**는 것이 핵심이다 — 행이 안 생기므로
*"목록엔 보이는데 열면 404"* 라는 #148 의 증상이 **구조적으로 만들어질 수 없다.**

**[★ 이 검사를 쓰다가 내가 먼저 틀렸다]**
처음에는 `path` 에 프로젝트 상대경로를 넘겼다. `save_auction_images()` 는
`os.path.getsize(path)` 를 **준 그대로** 쓰므로 파일을 못 찾아 **1024바이트도 `saved=0`**
이 나왔다. 하마터면 *"하한 가드가 과하다"* 고 오판할 뻔했다. 실 호출부
(`crawler/image_crawler.py`)가 넘기는 것은 `image_path()` 의 **절대경로**다 — 확인하고
같은 형태로 고치니 예상대로 나왔다.
*검사가 실 호출부와 같은 형태로 부르고 있는지부터 본다.*

**[런타임 검사의 변이 검출 4/4]**

```
DB기록 <  -> <=        잡는다  [FAIL] 1024바이트: saved: 0 (expected 1)
DB기록 가드 무력화      잡는다  [FAIL] 1023바이트: saved: 1 (expected 0)
서빙   <  -> <=        잡는다  [FAIL] 1024바이트: 서빙 응답: 404 (expected 200)
쓰기   >= -> >         잡는다  (소스 검사 쪽에서)
```

**[★ 여기서도 부분 문자열에 속았다]**
"DB 기록이 정본 상수를 쓰는가"를 `"MIN_IMAGE_BYTES" in db_src` 로 썼다가, 변이
`_MIN_IMAGE_BYTES = 2048  # 자기 숫자` 를 **놓쳤다** — 그 줄에도 이름이 들어 있다.
`from crawler.image_assets import ... MIN_IMAGE_BYTES` 를 **정규식으로** 찾고
하드코딩(`_MIN_IMAGE_BYTES = <숫자>`)이 없는지도 함께 보게 고쳤다.
BUGS #232 에서 겪은 것과 **똑같은 함정을 두 번째로** 밟았다.

---

### 경계 변이 survivor 10개 최종 분류

| 지점 | 분류 | 근거 |
|---|---|---|
| `image_assets:325` `>= MIN_IMAGE_BYTES` | **DOCUMENTATION DRIFT** | 코드 3곳 일관, docstring 만 틀림 -> #238 로 수정 |
| `database:433` `days_left <= 3` | **WEAK TEST** | 검사 이름이 `days_left=2` 를 보고 있었다 -> #237 |
| `database:435` `days_left <= 7` | **WEAK TEST** | 같음 -> #237 |
| `rate_limit:115` `bucket[0] <= cutoff` | **WEAK TEST** | 정확한 cutoff 를 안 봤다 -> #236 |
| `payments:653` `refundable <= 0` | **WEAK TEST** | 오류 코드 계약 미검증 -> #236 |
| `database:1391` `size <= 0` | **FALSE POSITIVE** | 소유 테스트(`test_asset_pipeline`)를 집합에 안 넣었다. 넣으니 즉시 검출 |
| `rate_limit:110` 축출 임계 | **INTENTIONAL / 무해** | 10,000 vs 10,001. 상한의 목적에 영향 없음 |
| `image_assets:132/188/194` 매직바이트 길이 | **MUTATION EQUIVALENCE(실질)** | 12/24/10바이트 입력은 앞단에서 이미 걸러진다 |
| `image_assets:306` `seq <= 0` | **INTENTIONAL(중복 방어)** | 같은 검증이 `L114` 에 있고 그쪽은 검출된다 |
| `database:580/1883` `cap>=0` / `max_rows<=1` | **INTENTIONAL** | 호출부가 0/1 을 넘기는 경로가 없다 |

**REAL BUG 0건 · WEAK TEST 4건(수정) · DOCUMENTATION DRIFT 1건(수정) ·
FALSE POSITIVE 1건(하네스 정정) · INTENTIONAL/EQUIVALENCE 4건(근거 기록).**

--------

#239

건물면적 / 토지면적을 **함께** 지정하면 결과가 항상 0건 — 두 컬럼은 독립 속성이 아니라
**판별 합집합(discriminated union)** 인데 AND 로 묶고 있었다

상태

**해결 (2026-08-26). 제품 코드 수정 + 회귀 + 변이 12/12 검출.**

### 증상 (실사용 경로)

검색 폼의 `면적 조건` 패널에는 `건물면적`과 `토지면적` 범위 선택이 **나란히** 있다.
둘 다 채우는 것이 가장 자연스러운 조작인데, 그때 결과는 **언제나 0건**이었다.
오류도 안내도 없다 — 사용자는 "그런 물건이 없구나"로 읽는다.

UI 드롭다운 조합을 **전수**로 태워 확인했다(라이브 API, `127.0.0.1:8000`):

```
건물 min 13종 x 토지 min 12종 = 156 조합
  -> 결과가 1건이라도 나오는 조합 :  0 / 156
  -> include_closed=true(전체 재고)에서도 0건
반면 한쪽만 주면          건물 min=10 -> 152건 · 토지 min=50 -> 125건
```

### 원인 — "커버리지 99.3%" 를 잘못 읽었다

`backfill_area.py` 의 실측 표는 이렇게 적혀 있었다.

```
건물면적만  1,454 (59.5%)
토지면적만    974 (39.9%)
둘 다 없음     16 (0.7%)   <- 전부 차량/선박/건설기계다
커버리지    99.3%
```

이 표는 **정확하다.** 틀린 것은 이것을 가져다 쓴 쪽이다. `99.3%` 는 *"둘 중 하나라도
가진"* 비율인데, `api/v1/search.py` 와 `src/app/search/SearchForm.tsx` 는 이것을
*"각 면적 컬럼의 보유율"* 로 읽고 이렇게 적어 뒀다.

> "면적을 모르는 물건(차량/선박 등 **16행**)은 면적 조건을 주는 순간 결과에서 빠진다.
>  그것이 옳다."

**16행이 아니다.** 2026-08-26 전수 재측(`auction_item` 2,558행):

```
건물면적만 보유  1,535 (60.0%)      토지면적만 보유  1,006 (39.3%)
★ 둘 다 보유         0 (0.0%)       둘 다 없음          17 (0.7%)

=> 건물면적 조건이 버리는 행 = 1,023 (40.0%)
=> 토지면적 조건이 버리는 행 = 1,552 (60.7%)
```

버려지는 것은 차량/선박이 아니라 **반대 유형의 정상 부동산 전부**다.
기본 검색 가시 재고(280건) 기준으로 다시 재면:

```
건물면적 조건 -> 128건(45.7%) 이탈.  전답 44 · 임야 19 · 단독주택 · 대지 …
토지면적 조건 -> 153건(54.6%) 이탈.  아파트 45 · 다세대 23 · 오피스텔 20 · 근린시설 17 …
```

`extract_areas()` 는 주소 원문 대괄호 구획의 **머리말**을 보고 건물이면 `building_area`,
토지면 `land_area` 를 채운다. 그래서 한 물건은 둘 중 **하나만** 갖는다. 두 컬럼은
독립 속성이 아니라 **판별 합집합**이다. 그 둘을 AND 로 묶으면 만족 가능한 행이
**구조적으로 0** 이다 — 데이터가 늘어도 영원히 0이다.

### 왜 기존 테스트가 못 잡았나 (fixture 가 존재하지 않는 데이터를 전제했다)

`test_search.py:check_area_filter_survives_missing_migration_025()` 의 씨앗은 4행이
전부 `property_type='아파트'` 이고, 1~3번이 **건물·토지 면적을 둘 다** 갖고 있다.
실데이터에는 그런 행이 **한 행도 없다.** NULL 인 4번에는 `# 차량/선박처럼 …` 이라는
주석까지 달려 있어, 틀린 전제가 코드·주석·fixture 세 곳에 함께 박혀 있었다.

그 fixture 위에서는 무엇을 단언해도 이 결함이 드러나지 않는다. **테스트는 통과했고,
통과가 곧 "확인했다"로 읽혔다.**

### 수정 — 결합 규칙을 하나로 통일한다

```
면적 조건 = 주어진 면적 계열들의 OR,  계열 안의 min/max 는 AND
```

- **한 계열만 주면 OR 의 항이 하나라 기존 동작과 완전히 같다.** NULL 규약 그대로다.
  실측으로 확인: 건물 152/152 · 토지 127/127 · 종결포함 1,523/980 — 수정 전과 동일.
- 두 계열을 주면 "건물이 이 범위이거나, 토지가 이 범위인 물건"이 된다. 판별 합집합인
  데이터에서 사용자가 둘을 채웠을 때 **뜻이 통하는 유일한 읽기**다.
- 바로 위 `property_type` 다중선택을 OR 로 묶는 것과 **같은 원칙**이다(새 규칙이 아니다).

수정 후 156/156 조합이 결과를 돌려주고, `건물10 OR 토지50 = 2,503 = 1,523 + 980` 으로
각 계열 결과의 **정확한 합집합**임을 확인했다.

### SQL 조각은 전부 소스 리터럴로 (보안 가드를 우회하지 않았다)

첫 구현은 컬럼명을 f-string 으로 조립했다가 `test_schema_hygiene` 의
**"WHERE 조각이 전부 상수"**(SPRINT107 SQL Injection Audit)에 걸렸다. 가드를 느슨하게
하지 않고 **조각을 전부 소스 리터럴로** 바꿔 통과시켰다. 가변인 것은 조각의 *개수*뿐이고
면적 값은 언제나 `?` 바인딩으로만 들어간다.

★ 그 예외(`f"({area_clause})"`)가 **이름만 믿는 구멍**이 되지 않도록,
`_names_bound_only_to_str_literals()` + `CONSTANT_CLAUSE_SOURCES` 를 신설해
*"그 변수의 재료가 정말 문자열 리터럴인가"* 를 AST 로 따로 못박았다.
변이 3/3 검출(컬럼명 f-string 조립 / `%` 포맷 삽입 / `area_clause` 우회 조립).

### 회귀

- `test_search.py` `check_area_families_are_a_union_not_a_pair()` (신규, 12단언).
  씨앗을 **실측된 모양 그대로** 만든다 — 아파트·오피스텔은 `building_area` 만,
  전답·임야는 `land_area` 만, 자동차는 둘 다 NULL. "둘 다 가진 행이 0인가"를
  **전제로 먼저 단언**해서, 씨앗이 다시 비현실적으로 바뀌면 그 자리에서 붉어진다.
- `tests/source-contract.test.mjs` — 틀린 전제 문구 부활 방지 + OR 결합 유지.
- `test_schema_hygiene.py` — 위 리터럴 검사.

### 변이 (12/12 검출 · 생존 0)

```
M1 계열간 OR->AND (원래 결함으로 회귀)        검출 (py+node)
M2 계열내 AND->OR (범위가 안 좁혀진다)        검출
M3 NULL 규약 파기 (미상 행 통과)              검출
M4 params 순서 뒤집기                         검출
M5 상한(max_*) 무시                           검출
M6 하한(min_*) 무시                           검출
M7 면적 조건 통째 무시                        검출
M8 land_area 계열 누락                        검출
M9 틀린 전제 문구 부활                        검출 (node)
H1 컬럼명 f-string 조립                       검출 (schema_hygiene)
H2 % 포맷으로 조각 삽입                       검출
H3 area_clause 우회 조립                      검출
```

★ **내 검사가 두 번 틀렸고 둘 다 변이가 잡아냈다.**
(1) 소스 계약에서 그냥 `" OR ".join` 을 찾았더니, **바로 위 `property_type` 이 같은
표현을 쓰고 있어** 면적 쪽을 AND 로 되돌려도 초록으로 남았다(M1 생존).
`area_clause` 식 자체를 보도록 고쳐서 잡았다.
(2) 그 뒤 검사를 **줄 단위**로 썼더니, 구현을 두 줄로 감싸는 순간 붉어졌다 —
공백을 뭉개 **식 단위**로 보도록 고쳤다.
*"검출 0"을 곧바로 "가드 있음"으로 읽지 않는다 — 무엇이 그 단언을 만족시키고 있는지부터 본다.*

★ 변이 앵커가 **CRLF 때문에 두 번 미적용**됐다(#232/#235 와 같은 함정).
하네스가 `[NOT-APPLIED]` 로 알려 줘서 "생존"으로 오독하지 않았다.

### 함께 정정한 문서/주석

- `api/v1/search.py` — "16행 / 차량·선박" 서술을 컬럼별 실측으로 교체
- `src/app/search/SearchForm.tsx` — 같은 서술 3곳(분위수 근거 / query 조립 / JSX 주석)
- `backfill_area.py` — 표에 `둘 다 보유 0` 행 추가, `99.3%` 가 무엇의 비율인지 명시
- `docs/FRONTEND_MASTER_SPEC.md` — "면적조건 = 불가(백엔드 미지원)" 는 **2026-08-26 부터
  사실이 아니다**. 완료로 정정하고 결합 규칙을 적었다(특수조건은 미지원 그대로 분리)

### 남은 결정 (제품 판단 — 임의로 바꾸지 않았다)

한 계열만 줬을 때 *"면적 미상"* 행을 계속 뺄 것인가는 **정책**이다. 지금은 뺀다(기존 규약).
다만 그 대가가 16행이 아니라 **가시 재고의 46~55%** 라는 것이 이제 측정돼 있으므로,
화면에 *"면적 미상 N건은 제외됨"* 을 노출할지는 PM 판단이 필요하다. 다음 Sprint 백로그.

--------

#240

면적 표시/추출 규칙이 **두 구현으로 갈라져 있었다** — 프런트는 천단위 쉼표에서 앞자리를
잃고(`1,000㎡` → **0㎡**), 백엔드는 옛 등기 표기에서 구분호실을 1동 전체로 읽었다(520배)

상태

**해결 (2026-08-26). 양쪽 제품 코드 수정 + 회귀 + 변이 7/7 검출.**
단, **DB 의 기존 2행은 backfill 을 돌려야 정정된다**(아래 "남은 조치").

### 어떻게 찾았나

#239 를 고치다가 *"같은 면적을 화면과 필터가 각각 계산한다"* 는 것을 알았다.

```
화면(카드)   src/lib/format.ts:parseArea()   full_address 대괄호를 JS 로 파싱
필터/DB      normalizer.extract_areas()      같은 문자열을 파이썬으로 파싱 -> DB 컬럼
```

BUGS #204 가 경계하는 *"같은 어휘가 두 곳"* 그대로다. 그래서 **둘을 전수 대조했다**
(운영 DB 2,558행 전부, 실제 두 함수를 각각 실행).

```
일치                 2,544
값이 다름                1     <- 프런트 결함
JS만 없음(DB 있음)      13     <- 그중 2건이 백엔드 결함
DB만 없음(JS 있음)       0
```

### 결함 A — 프런트가 천단위 쉼표에서 **앞자리를 잃는다**

정규식이 `([0-9]+(?:\.[0-9]+)?)` 라 쉼표에서 끊기고 **쉼표 뒤부터** 매치됐다.

```
"1층 3,005.35㎡"   ->    5.35㎡   (562배 축소)
"1층 1,000㎡"      ->       0㎡   ★ 면적이 0 으로 보인다
"1층 12,345.67㎡"  ->  345.67㎡
```

실데이터 `id=443`(평택 공장): 지1층 3,005.35 + 1층 6,110.75 + 2층 5,322.75 =
**14,438.85㎡** 인 건물이 검색 카드에 **438.85㎡** 로 찍혔다. 32배 축소다.

오류도 빈칸도 아니고 **그럴듯한 작은 숫자**가 나오므로 알아챌 방법이 없다.
백엔드는 처음부터 `[0-9][0-9,]*` 로 옳게 읽고 있었다 — 프런트만 갈라져 있었다.

**[수정]** 백엔드와 같은 정규식으로 맞추고 `replace(/,/g,'')` 를 넣었다.

### 결함 B — 백엔드가 **구분호실을 1동 전체로** 읽는다 (평/홉/작 3단 표기)

```
[건물 3층37호 ... 1동 1층192평6홉9작 2층190평2홉6작 3층188평8홉 4층188평8홉 내3층1평4홉6작]
```

앞의 층 목록은 **건물 1동 전체**이고, 이 물건은 `내 ...` 뒤의 **3층 37호(1평4홉6작 ≈ 4.8㎡)**
다. `extract_areas` 는 평 토큰 5개를 전부 더해 **2,509.09㎡** 를 넣었다 — **520배**.
`id=6495` 는 층 목록이 두 번 반복돼 3,771.90㎡(≈344배).

이 값은 그대로 `auction_item.building_area` 가 되고 **면적 검색을 탄다.**
"건물 2,000~3,000㎡" 로 거르면 4.8㎡ 짜리 사무실 한 칸이 나온다.

**이것은 대지권 표기에서 이미 내린 판단과 같은 상황이다** — 부분을 전체로 읽는 오류다.
그때의 답(*"틀린 값보다 없는 값이 낫다 → None"*)을 그대로 쓴다.

★ **그리고 프런트는 이미 옳았다.** `format.ts` 의 docstring 이 이렇게 적고 있었다:

> *"1건(id=6495)은 '192평6홉9작' 처럼 홉/작 하위 단위에 층 목록이 중복돼 있어,
>   일괄 환산하면 **틀린 숫자를 보여줄 위험**이 있다. 아무것도 안 보여주는 편이 낫다."*

**결정은 이미 내려져 있었고 백엔드만 그것을 따르지 않았다.** 그래서 이 수정은 새로운
제품 판단이 아니라 **기존 판단을 한쪽에 마저 적용한 것**이다.

**[수정]** `_PYEONG_SUBUNIT_RE` (`[0-9]평[0-9]+(홉|합|작)`) 가 보이면 그 대괄호는
믿지 않고 None. 홉/작이 없는 단순 평 표기 11행(`[토지 전 1048평]`)은 그대로 환산한다.

**전수 재계산으로 영향 범위를 확정했다: 2,558행 중 바뀌는 행 2개(그 둘뿐), 2,556행 무변경.**

### 함께 정정한 것

`normalizer.py:199` 의 *"평 단위 실데이터에 1행 있다"* — 실제 **13행**이다(전수).
#239 의 "16행"과 같은 종류의 낡은 숫자다.

### 회귀

- `test_normalizer.py` — 평/홉/작 2케이스(둘 다 None) + 단순 평이 살아 있는지 +
  쉼표 3케이스. **프런트와 같은 입력·같은 기대값**을 쓴다.
- `tests/format.test.mjs` — 쉼표 5케이스 + id=443 실데이터 + 회귀 없음 확인 +
  "백엔드와 같은 숫자를 낸다"(같은 입력 3쌍). 한쪽만 고치면 반대쪽이 붉어진다.

### 변이 (7/7 검출 · 생존 0)

```
A1 평/홉/작 배제 제거(원래 결함 회귀)   검출     B1 프런트 쉼표 정규식 되돌리기   검출
A2 배제를 너무 넓게(단순 평도 버림)     검출     B2 프런트 쉼표 제거 되돌리기     검출
A3 쉼표 제거 삭제                       검출
A4 평 환산 상수 파괴                    검출
A5 다층 합산 -> 최대값                  검출
```

### ★ 남은 조치 — DB 의 2행은 아직 옛 값이다

코드는 고쳤지만 `auction_item` 의 기존 값은 그대로다.

```
id=6495   building_area = 3771.9008   -> 정정 후 NULL
id=13584  building_area = 2509.0909   -> 정정 후 NULL
```

정정 수단은 이미 있다: `python backfill_area.py --apply --force`
(전수 재계산 결과 바뀌는 행이 **이 2개뿐**임을 확인했다).

**이번 세션에서는 실행하지 않았다** — 운영 DB 쓰기라 승인 영역이다.
그때까지 그 2행은 면적 검색에서 실제보다 크게 잡힌다(영향 2행 / 2,558행).

--------

#241

물건 상세가 **열리지 않는 문서 URL 을 광고**했다 — `IMAGE` 는 문서가 아닌데
`available:true` + `/documents/IMAGE` 를 줬고 그 주소는 400 이다

상태

**해결 (2026-08-26). 제품 코드 수정 + 회귀 + 변이 5/5 검출.**

### 증상

```json
{"doc_type":"IMAGE","status":"READY","available":true,
 "viewer_url":"/api/v1/item/1450/documents/IMAGE",
 "download_url":"/api/v1/item/1450/documents/IMAGE"}
```

그런데 `GET /api/v1/item/1450/documents/IMAGE` 는
**400 "지원하지 않는 문서 종류입니다"** 다.

사진은 문서가 아니다 — 0~N장이라 단일 서빙 파일이 없고,
`api/v1/documents.py:DOC_TYPE_FILES` 에도 IMAGE 가 없다(APPRAISAL/SPEC/STATUS 뿐).
사진은 `images[]` / `representative_image` / `/api/v1/item/{id}/images/{seq}` 로 나간다.

**실측(2026-08-26 운영 DB): 사진을 가진 17물건 전부**가 그 상태였다.

### 원인 — 규칙은 있었는데 조건이 좁았다

`_document_entry()` 는 이미 `servable`(= `doc_type` 이 `DOC_TYPE_FILES` 에 있는가)을
계산하고 있었다. 다만 그것을 **`file_size` 를 잴지 말지**에만 쓰고,
**URL 을 줄지 말지**에는 쓰지 않았다. URL 은 `ready`(=status READY) 하나만 봤다.

바로 그 자리 주석이 규칙을 정확히 적어 두고 있었다:

> *"READY가 아니면 URL을 주지 않는다. **열 수 없는 주소를 건네고 프런트가 404를
>   받아 보게 하는 것보다, 없다는 사실을 응답에 담는 편이 정직하다.**"*

`document_status` 에 `doc_type='IMAGE'` 행이 있고 사진을 받으면 READY 가 되므로,
그 규칙이 **정확히 반대 결과**를 냈다.

### 왜 프런트가 멀쩡한데도 결함인가

`src/app/properties/[id]/page.tsx` 가 이 목록에서 IMAGE 를 걸러 내고 있었다:

```
.filter((doc) => doc.doc_type !== 'IMAGE')
/* IMAGE 행도 들어 있으므로 이 목록에서는 제외한다 — 그러지 않으면
   "IMAGE / 수집완료"라는 열 수 없는 항목이 문서 목록에 끼어든다. */
```

즉 **소비자 한 곳이 우회하고 있었을 뿐** API 계약은 거짓이었다. 그 우회를 모르는
소비자는 그대로 걸린다 — `audit_asset_integrity.py` [9]("API 가 광고한 자산 URL 이
실제로 열리는가")가 **"열리지 않음 17개"로 계속 붉었다.**

이것은 이 파일이 `file_size` 에 대해 이미 쓴 표현 그대로의 상태다 —
**"API 가 거짓말을 하는 상태"**.

### 수정

`openable = ready and servable` 을 도입하고 `available` / `viewer_url` /
`download_url` 셋 다 그것을 쓴다. 셋은 **같은 주장**("이걸 열 수 있다")이므로 조건이
갈라지면 안 된다. 수집 상태 자체는 `status` 가 그대로 전한다(`IMAGE: READY` 유지) —
화면이 사진 수집 상태를 읽는 경로는 손대지 않았다.

종류 이름을 새로 적지 않고 **서빙 계층(`DOC_TYPE_FILES`)을 진실의 원천으로** 쓴다.

### 결과

```
audit_asset_integrity.py [9]   열리지 않음 17개  ->  0개
전체 어긋남                     43건  ->  26건
```

남은 26건은 코드 결함이 아니라 **데이터 정리**다(디스크 고아 디렉터리 1 / 고아 큐 행 18 /
내려받아 놓고 못 옮긴 파일 7). 스크립트 자신이 *"정리는 승인 영역"*,
*"어느 물건 것인지 확정할 수 없어 여기서 하지 않는다"* 라고 적고 있다.

### 회귀

`test_asset_pipeline.py` `test_every_advertised_document_url_actually_opens()` (신규).
종류 이름을 손으로 적지 않는다 — **광고된 URL 을 전부 실제로 호출해 200 인지 본다.**
새 doc_type 이 늘어도 규칙이 그대로 적용된다. 대조군으로
`/documents/IMAGE` 가 정말 200 이 아님을 확인해 "URL 을 안 준다"가 과잉 방어가 아님을
보인다. 사진이 `images[]` 로 여전히 나가는 것도 함께 못박는다.

### 변이 (5/5 검출 · 생존 0)

```
C1 openable -> ready (원래 결함으로 회귀)      검출
C2 URL 만 되돌리기 (available 은 그대로)       검출
C3 available 만 되돌리기 (URL 은 그대로)       검출
C4 servable 판정을 항상 True 로                검출
C5 IMAGE 행을 통째로 없애기(상태까지 숨김)     검출   <- 과잉 수정도 막는다
```

★ **이 결함은 하마터면 감사 도구의 오탐으로 치부할 뻔했다.** `[9]` 가 `IMAGE` URL 을
찍고 있길래 *"감사 스크립트가 IMAGE 를 문서로 잘못 다루는군"* 이라고 읽었다.
그런데 **API 응답을 직접 열어 보니 그 URL 을 광고하는 쪽은 감사 도구가 아니라 API 였다.**
같은 세션에서 내가 `doc_raw` 짝을 잘못 맞춰 허위 결함을 만든 직후였는데,
이번에는 **도구가 옳고 내 추측이 틀렸다.** 붉은 게이트를 오탐으로 넘기기 전에
그것이 무엇을 근거로 붉은지 확인해야 한다.

--------

#242

명암비 감사가 **컬러 이모지를 글자로 재고 있었다** — `🤍` 를 1.17:1 위반 40곳으로
집계해 진짜 부채 목록에 잡음을 섞었다

상태

**해결 (2026-08-26). 도구 수정. 위반이 아니라 '판정 불가'로 따로 센다.**

### 증상

```
rgb(237, 237, 237) on rgb(255,255,255)  18px  실측 1.17:1  (기준 4.5:1)  40곳
    /   '🤍'   text-lg disabled:opacity-50
```

`audit_contrast.py` 가 텍스트 노드마다 `getComputedStyle(el).color` 를 전경색으로 삼아
배경과 비교한다. 그런데 **컬러 이모지는 폰트가 자체 색 글리프로 그린다** — CSS `color`
는 그 픽셀과 아무 상관이 없다. 상속된 `rgb(237,237,237)` 를 전경색으로 믿고 잰 1.17:1 은
**측정이 아니라 잡음**이었고, 그것이 전체 위반 484곳 중 40곳(8%)을 차지했다.

이 저장소가 반복해서 경계해 온 것과 같은 모양이다 — **못 잰 것을 잰 것처럼 세면
나머지 진짜 숫자까지 믿을 수 없게 된다.**

### 수정 — 지우지 않는다. **따로 센다**

`run_python_tests.py` 가 `SKIPPED`(실행 안 됨)를 `PASSED` 에 절대 섞지 않는 것과
같은 이유다. 이모지를 조용히 버리면 *"흰 하트를 흰 카드 위에 두는 것이 보이느냐"* 는
남아 있는 질문까지 사라진다(WCAG 1.4.3 텍스트가 아니라 **1.4.11 비텍스트 대비** 쪽 논점이고,
눈으로 볼 사람이 있어야 판단할 수 있다). 그래서 **'판정 불가(emoji)'** 버킷으로 보고한다.

```
합계: 텍스트 노드 913개 / 기준 미달 444개 / 판정 불가(emoji) 40개

판정 불가 - 컬러 이모지 (CSS color 로 명암비를 낼 수 없다. 눈으로 볼 것)
    🤍      18px  40곳   예: /  text-lg disabled:opacity-50
```

### 판별을 **범위가 아니라 유니코드 속성**으로 한다

처음엔 `[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}...]` 범위로 잘랐다. **그러면 반대 방향으로
틀린다** — `✓`(U+2713)·`▼`·`↓` 처럼 **텍스트 표현이 기본**인 기호까지 빨려 들어가
측정에서 빠진다. 이 화면들은 실제로 `▼`(아코디언 화살표, 253곳)를 위반으로 갖고 있어서
그것을 잃으면 진짜 부채가 사라진다.

그래서 `\p{Emoji_Presentation}`(기본 표현이 이모지) 또는 `\uFE0F`(이모지 표현 강제
변이 선택자)만 고른다. 경계 10종으로 확인했다:

```
🤍 ❤️            -> emoji (판정 불가)
✓ ▼ ↓ ★ —        -> text  (계속 측정한다)
'입찰 14일전' 등   -> text
```

### 남는 사실 (제품 판단 대기)

`🤍`(즐겨찾기 안 됨)는 **흰 카드 위의 흰 하트**다. 이모지 폰트가 옅은 윤곽선을 주지만
눈에 잘 띄지 않는다. 아이콘을 바꿀지는 디자인 결정이라 여기서 정하지 않는다 —
`aria-label`/`title` 은 이미 `즐겨찾기 추가/해제` 로 붙어 있어 스크린리더 경로는 멀쩡하다.

### 함께 정정 — 체크리스트의 명암비 숫자가 낡았다

`docs/BETA_RELEASE_CHECKLIST.md` 는 *"텍스트 노드 77개 -> 44개가 AA 미달, 8조합"* 이라고
적고 있다. 그때는 **검색 결과가 0건**이라 목록이 비어 있었다. 지금은 기본 검색에 280건이
보이므로 카드가 실제로 그려지고, 같은 도구가 **913노드 / 444곳 / 11조합**을 잰다.
결함이 늘어난 것이 아니라 **화면에 내용이 생긴 것**이다(조합당 곳수만 늘었다).

--------

#243

유니크 사건이 **16,384건**을 넘으면 매일 크롤 파이프라인이 통째로 죽는다 —
`too many SQL variables`

상태

**해결 (2026-08-27). 제품 코드 수정 + 회귀 + 변이 6/6 검출.**

### 증상 — 느려지는 것이 아니라 **멈춘다**

`migrate_execute.execute()` 가 규모에 따라 어떻게 되는지 사본 DB 에서 실측했다.

```
사건   2,500건 ->  0.09s   정상
사건  10,000건 ->  0.36s   정상
사건  16,383건 ->          정상
사건  16,384건 ->  ★ OperationalError: too many SQL variables
사건  20,000건 ->  ★ 같은 실패
```

경계가 정확히 **16,383 / 16,384** 다.

파손 시 결과:

```
auction_case  0건   auction_item  0건   document_status  0건
```

rollback 자체는 깨끗해서 **부분 커밋은 없다.** 그러나 그날 크롤 결과가 통째로 버려지고
`run_daily.bat` 은 `[FAILED]` 만 남긴다. 데이터가 오염되는 것이 아니라 **하나도 안 들어온다.**

### 원인

Sprint 129 가 N+1 을 없애며 `(court_code, case_no)` 쌍 **전부**를 한 문장에 넣었다.

```python
placeholders = ",".join(["(?,?)"] * len(case_keys))     # 쌍당 ? 2개
conn.execute(f"... WHERE (court_code, case_no) IN ({placeholders})", params)
```

SQLite 의 `SQLITE_LIMIT_VARIABLE_NUMBER`(이 환경 실측 **32,766**)를 쌍 16,384개
(= 32,768 변수)에서 넘는다. 실측으로 확인한 쿼리 형태별 상한:

```
row-value `(?,?)` 쌍   최대 16,383 쌍  (= 32,766 변수)
단일값     `?`         최대 32,766 개
```

**지금 운영 DB 는 유니크 사건 1,882건(상한의 11%)이라 아직 닿지 않는다.**
그러나 60개 법원을 매일 전수로 도는 구조라 수집 범위가 넓어지면 닿는 수다.

### 수정 — 값을 SQL 텍스트로 밀어 넣지 않고 **나눈다**

`storage/database.py` 에 `chunked_for_sql()` / `sql_variable_limit()` 을 신설하고
호출부를 청크 루프로 바꿨다. 각 청크는 서로소인 키 집합을 조회해 같은 dict 에 담으므로
결과는 나누기 전과 동일하다.

★ **첫 구현이 상한을 상수로 박아 뒀고, 그것을 내 테스트가 잡았다.**
`SQLITE_MAX_VARIABLES = 32766` 으로 가정했는데 — **SQLite 3.31 이하의 기본값은 999** 다.
낮은 빌드에서는 **500건대부터** 같은 사고가 나는데 그 구현은 아무 도움이 안 된다.
지금은 `conn.getlimit()` 으로 **그 커넥션에 직접 물어보고**, 못 물어보면
가장 낮은 쪽(999)으로 보수적으로 잡는다.

### 회귀 — 16,384행을 만들지 않고 **같은 경계**를 넘는다

그 규모의 씨앗은 매 실행마다 수십 초가 든다. 대신
`sqlite3.Connection.setlimit()` 으로 상한 자체를 낮춰 적은 행으로 같은 제약을 넘는다.
흉내가 아니라 **진짜 같은 제약**이다(넘으면 같은 `OperationalError` 가 난다).

`test_auction_identity.py` `test_migrate_survives_more_cases_than_sql_variable_limit()`.
죽지 않는 것만 보지 않고 **조각을 잃지 않았는지**(사건/물건/문서 건수)와
**재실행 멱등성**까지 함께 못박는다.

★ **낮춘 상한을 처음엔 40 으로 잡았는데, 그것이 검사를 무디게 만들었다.**
청크 산식이 `max(1, (40-64)//n)` 의 클램프에 걸려 **n 이 뭐든 1** 이 되는 바람에,
`vars_per_item` 을 잘못 세는 변이가 그대로 통과했다. 여유분보다 넉넉한 200 으로 올려
산식이 실제로 계산되게 했다.

### 변이 (6/6 검출 · 생존 0)

```
D1 청크 없이 통째로 (원래 결함으로 회귀)      검출
D2 conn 을 안 넘긴다(상한을 안 물어본다)      검출
D3 vars_per_item 을 1로 (쌍인데 1로 셈)       검출   <- 처음엔 생존했다(위 ★)
D4 첫 덩어리만 내보낸다 (조각 유실)           검출
D5 마지막 잔여 덩어리를 버린다                검출
D6 상한을 못 물어봐도 큰 값으로 가정          검출   <- 처음엔 생존했다(fallback 미검증)
```

### ★★ 이 수정을 검증하다 **stale bytecode 함정**을 밟았다 (방법론)

변이 D3 는 `vars_per_item=2` -> `1` 이다. **바이트 수가 같다.** 하네스가 파일을
되돌린 뒤에도 `__pycache__/migrate_execute.cpython-313.pyc` 가 (mtime, size) 검증을
통과해 **되돌리기 전의 바이트코드가 계속 실행됐다.**

그래서 수정을 넣고도 실규모 재현이 계속 실패했고, 원인을 `inspect.getsource()` 로
찾으려 하니 **소스는 새것을 보여 줬다**(getsource 는 파일을 읽는다). 결국
`dis.dis()` 로 `LOAD_CONST 11 (1)` 을 보고서야 확정했다.

**교훈: 변이 하네스는 `PYTHONDONTWRITEBYTECODE=1` 로 돌린다.** 그러지 않으면
같은 길이의 치환이 캐시에 남아 *"수정했는데 안 고쳐진다"* 또는 그 반대인
**허위 검출/허위 생존**을 만든다. 6/6 결과는 바이트코드 캐시를 끈 상태에서 다시 얻은 것이다.

--------

#244

체크포인트가 손상되면 **60개 법원을 전부 처음부터 다시 긁으면서 로그를 한 줄도 남기지
않았다** — 밤새 돈 재크롤의 원인을 알 방법이 없다

상태

**해결 (2026-08-27). 동작은 그대로, 가시성만 추가. 변이 5/5 검출.**

### 증상

`CheckpointManager._load_all()` 이 이랬다.

```python
except Exception:
    return {}
```

이 반환값이 비면 크롤러는 **모든 법원을 처음부터 다시 수집한다** — 바로 위
`_write_atomic()` 의 docstring 이 *"크롤러가 진행 상황을 통째로 잃는다"* 라고
경계한 그 상황이다. 그런데 그 일이 실제로 벌어져도 **로그가 없다.**

실측(2026-08-27): 법원 2곳의 진행 상황을 저장한 뒤 파일을 반쯤 자르고 다시 읽었다.

```
_load_all()  -> {}          (진행 상황 2건이 사라졌다)
로그 출력    -> ''          ★ 빈 문자열
```

운영자가 아침에 보는 것은 *"어제 다 긁었는데 오늘 또 전부 긁었다"* 뿐이고,
그 이유는 어디에도 없다.

### 왜 기존 테스트가 못 잡았나

`test_checkpoint_atomicity.py` 의 `test_corrupted_file_does_not_crash_get()` 은
**"크래시하지 않는가"만** 봤다. 침묵은 크래시가 아니므로 그대로 통과했다.
이 저장소가 반복해 경계해 온 *"실패가 성공처럼 보인다"* 의 한 형태다.

### 수정 — **동작은 그대로 둔다**

여기서 예외를 올리면 체크포인트 하나 때문에 크롤 자체가 죽는다. 처음부터 다시 긁는
선택이 옳다. 바꾸는 것은 *"그 선택을 했다는 사실이 보이는가"* 뿐이다.

```
ERROR 체크포인트를 읽지 못했다 - **모든 법원을 처음부터 다시 수집한다**.
      경로=logs/checkpoint.json 크기=37B 사유=JSONDecodeError: Unterminated string ...
```

**'파일이 없다'(정상 첫 실행)와 '파일이 있는데 못 읽었다'(사고)를 구별한다** —
전자는 로그를 남기지 않는다. 매일 남는 소음은 진짜 신호를 묻는다.

### 회귀

기존 테스트를 확장했다. "죽지 않는다"에 더해 **로그에 남는가 / 결과를 말하는가 /
경로가 들어 있는가**를 단언하고, **대조군으로 '파일 없음은 조용해야 한다'** 를 둔다.

### 변이 (5/5 검출 · 생존 0)

```
E1 로그를 없앤다 (원래 결함으로 회귀)            검출
E2 파일 없을 때도 로그를 남긴다 (소음)           검출
E3 로그에서 '다시 수집한다' 서술을 뺀다          검출
E4 로그에서 경로를 뺀다                          검출
E5 손상에서 예외를 올린다 (크롤이 죽는다)        검출   <- 과잉 수정도 막는다
```

--------

#245

파이프라인 **마지막 단계가 배선돼 있지 않다** — 문서는 매일 받는데 권리분석으로
바꾸는 스크립트는 어떤 .bat/예약 작업에도 없다

상태

**탐지 추가 (2026-08-27). 배선 자체는 승인 영역이라 SKIP.** 변이 5/5 검출.

### 증상 — 숫자가 명확하다

```
수집일        STATUS 문서 수집   권리분석 파싱
2026-08-25          161건            161건  (100%)   <- 사람이 손으로 돌린 날
2026-08-26           16건              0건  (  0%)   <- doc_worker 만 돈 날
```

2026-08-26 에 `DojoonPass-DocWorker` 가 돌아 STATUS 문서 16건을 새로 받았다.
그 16건 중 **권리분석 데이터가 생긴 것은 0건**이다.

### 원인 — 전수 grep

```
.bat 이 부르는 파이썬 스크립트 전수
    mvp_scraper.py      (크롤)
    migrate_execute.py  (auction -> auction_item / document_status)
    doc_worker.py       (문서·사진 수집 -> doc_raw / auction_image)
    refresh_priority.py (큐 우선순위)

    ★ load_rights_data.py  없음
    ★ load_spec_data.py    없음
```

예약 작업 등록 스크립트(`register_scheduler_tasks.ps1`)에도 없다.
즉 **문서를 권리분석 데이터로 바꾸는 단계는 수동 실행 전용**이다.

### 왜 아무도 몰랐나 — 다른 지표가 전부 초록이다

```
큐         done        ✔
문서 파일   존재        ✔
doc_raw    행 있음      ✔
document_status READY  ✔
```

수집은 완벽하게 끝났다. 다만 **그 다음이 없다.** 실패가 아니라 **부재**라
어떤 실패 카운터에도 잡히지 않는다.

### 지금 사용자 영향 — 아직 없다 (그래서 더 위험하다)

```
STATUS=READY 인데 권리분석 없음 : 16건
  그중 기일이 남아 화면에 보이는 물건 : 0건
```

16건 모두 기일이 지나 기본 검색에 뜨지 않는다. 그러나 **이 격차는 매일 자란다** —
doc_worker 가 돌 때마다 파싱되지 않은 문서가 쌓이고, 그중 기일이 남은 물건이
생기는 순간 사용자는 *"문서는 있다는데 권리분석은 비어 있는"* 상세 화면을 본다.

### 조치 — 보이게 만들었다

`audit_schedule_health.py` 에 축 **[6] 파이프라인 마지막 단계**를 신설했다.
수집일별 파싱률을 그대로 찍고, 파싱 0%인 날을 지목한다.

```
[6] 파이프라인 마지막 단계 - 받은 문서가 권리분석으로 바뀌었는가
      2026-08-26  수집   16건 / 파싱    0건 (  0%)   <- ★ 파싱이 안 돌았다
      2026-08-25  수집  161건 / 파싱  161건 (100%)
      STATUS=READY 인데 권리분석 없음 : 16건 (그중 기일 남은 물건 0건)
```

판정부를 순수 함수(`parse_axis_lines()`)로 뽑아 `--selftest` 가 직접 태운다.

### 배선은 왜 안 했나 (SKIP 사유)

`.bat` 에 두 줄을 넣으면 오늘 밤부터 운영에서 자동 실행된다. 그런데 두 스크립트에는
**`purge_orphans()` 라는 DELETE 경로**가 있다(`rights_summary` / `tenant_rights`).
`evidence_found == 0` 안전장치가 있지만, 부분 유실 상황에서 무엇을 지울지는
운영 판단이 필요하다. **운영 야간 작업의 동작을 바꾸는 것은 승인 영역**이라
탐지만 넣고 배선은 다음 Sprint 로 넘긴다.

제안 형태(적용하지 않음):

```bat
"%PY%" load_rights_data.py >> logs\doc_run.log 2>&1
if errorlevel 1 ( ... [FAILED] ... exit /b 1 )
"%PY%" load_spec_data.py  >> logs\doc_run.log 2>&1
if errorlevel 1 ( ... [FAILED] ... exit /b 1 )
```

### 변이 (5/5 검출 · 생존 0)

```
F1 파싱 0% 마커를 없앤다            검출
F2 항상 마커를 찍는다(과잉 경보)     검출
F3 배선 안 된 스크립트 이름을 뺀다   검출
F4 미파싱 요약 줄을 없앤다          검출   <- 처음엔 생존했다(아래 ★)
F5 재료 없음을 '정상'으로 보고       검출
```

★ **여기서 내 검사가 두 번 틀렸고 둘 다 변이가 잡았다.**
(1) 새 검사를 `if fails: return 1` **뒤에** 넣어, 실패해도 아무도 보지 않았다 —
    5개 변이가 전부 생존해서 알았다.
(2) 고친 뒤에도 F4 가 생존했다. `"16건" in _blob` 으로 봤는데 바로 위 일자별 줄이
    *"수집   16건 / 파싱    0건"* 이라 **요약 줄을 통째로 지워도 통과**했다.
    요약 줄 자체를 지목하도록 고쳐서 잡았다.

--------

#246

마이그레이션이 **중간에 실패하면 되돌아오지 않는다** — 한 번의 사고가 매일 06:00
크롤을 영구히 세우고, 023/024 는 결제 테이블을 사라진 채로 확정한다

상태

**해결 (2026-08-27). 한 파일 = 한 트랜잭션. 회귀 `test_migration_atomicity.py`(4묶음).**

### 증상 — 되돌아오지 않는다

`storage/migrations/run_migrations.py` 가 파일 하나를 `conn.executescript(sql)` 로
통째로 실행했다. 이 메서드는 **먼저 커밋하고 스크립트를 트랜잭션 밖에서** 돌린다.
파일 안에 BEGIN/COMMIT 이 없으면(이 폴더의 25개 전부가 그렇다) 각 문장이 **즉시 확정**된다.

실측(2026-08-27, 세 가지 모양을 각각 재현):

```
A) "ALTER ADD COLUMN a;  SELECT 없는컬럼;"
   -> 예외가 났는데 컬럼 a 는 남는다.  rollback() 해도 안 없어진다.

B) "INSERT ...;  ALTER ...;  SELECT 없는컬럼;"
   -> DML 이 섞여도 마찬가지. 행도 컬럼도 둘 다 남는다.

C) "CREATE t_new;  DROP t;  RENAME;  SELECT 없는컬럼;"
   -> t 의 행이 **사라진다**.
```

실패한 파일은 `migration_history` 에 안 들어가므로(INSERT 가 뒤에 있다) 다음 실행이
**처음부터 다시** 적용한다. 그런데 앞부분은 이미 적용돼 있어:

```
duplicate column name: bench_a      <- 영원히 이 자리에서 죽는다
```

SQLite 에는 `ALTER TABLE ADD COLUMN` 용 `IF NOT EXISTS` 가 **없다.** 025 의 주석이
그 사실을 인정하면서 *"정상 경로에서는 두 번 실행되지 않는다"* 에 기대고 있었는데,
부분 적용이 바로 그 "비정상 경로"를 만든다.

### 왜 치명적인가 — 크롤이 통째로 멈춘다

`run_daily.bat` 3단계가 마이그레이션이고, 실패하면 `exit /b 1` 이다. 즉
**`mvp_scraper.py` 가 아예 실행되지 않는다.** 사람이 손으로 DB 를 고치기 전에는
회복 경로가 없다. 이 저장소가 이미 겪은 "9일간 크롤 중단을 몰랐다"와 같은 계열이고,
이쪽은 자동 회복이 **구조적으로 불가능**하다는 점이 더 나쁘다.

### 더 나쁜 형태 — 023/024 는 결제 테이블을 지운다

두 파일은 SQLite 의 제약 변경을 위해
`CREATE _new` -> `INSERT SELECT` -> `DROP 원본` -> `RENAME` 을 돈다.
DROP 과 RENAME **사이**에서 죽으면:

```
실패 후 테이블: [... 'payment_webhooks_new' ...]   <- payment_webhooks 가 없다
재실행:        no such table: payment_webhooks     <- 영구 정지
```

대상이 `payment_webhooks` / `registry_credits` / `registry_credit_logs` — 결제 테이블이다.

### 왜 이제껏 안 터졌나

Sprint 100 대의 판단은 *"18개 전부 정상 적용됐고, 실행 모델을 바꾸는 것이 더 위험하다"* 였다.
그때는 옳았다. 그 뒤 **021~025 가 들어오면서 전제가 둘 다 깨졌다** —
가드를 붙일 수 없는 `ADD COLUMN` 이 생겼고(025), DROP/RENAME 이 생겼다(023/024).

### 수정

SQLite 는 MySQL/Oracle 과 달리 **DDL 도 트랜잭션에 참여한다.** 파일 하나와
`migration_history` INSERT 를 한 트랜잭션으로 묶는 것만으로 위 전부가 사라진다.
묶으려면 `executescript()` 를 버리고 문장을 하나씩 넣어야 하는데, 경계 판정은
**직접 하지 않는다** — `sqlite3.complete_statement()` 가 SQLite 자신의 토크나이저라
주석 안의 세미콜론과 문자열 리터럴 안의 세미콜론을 정확히 건너뛴다.
옛 판단이 걱정한 "SQL 안의 세미콜론 처리"가 정확히 이 지점이고, 정규식으로 쪼갰다면
실제로 위험했다(013/016/023 에 여러 줄 CREATE TABLE 이 있다).

```
실제 .sql 25개 -> 143문장, 전부 complete_statement() 통과, 주석뿐인 조각 0개
빈 DB 부트스트랩(init_db -> migrate_v4_1 -> 25개)   119ms, 26테이블, 미적용 0
라이브 사본에 021~025 적용                            90ms 후 migrate_execute OK
```

### 검사도 반대로 뒤집었다

`test_schema_hygiene.py` §7 은 **버그를 사실로 고정**하고 있었다 —
*"실패해도 앞 문장은 남아 있다"*, *"코드는 바꾸지 않았다"*. 그 검사가 이제
*"실패한 파일은 앞 문장까지 통째로 롤백된다"* 와 **"고친 뒤 재실행이 성공한다"** 를 지킨다.
후자가 이 수정으로 얻은 실제 가치다.

새 회귀 `test_migration_atomicity.py` 는 **고치기 전 코드에서 9건 실패**하는 것을
확인한 뒤 도입했다(검출력 확인).

★ 처음 쓴 2번 검사는 **실패 지점을 RENAME 뒤에 두어 옛 코드에서도 통과했다.**
  INSERT SELECT 가 이미 데이터를 옮긴 뒤라 결과만 보면 멀쩡했기 때문이다.
  방어가 아니라 *실패 지점을 안전한 곳으로 골라 준 것*이었다 — DROP 과 RENAME
  **사이**로 옮겨서야 진짜 위험 구간을 재게 됐다.

--------

#247

`migrate_execute.py` 가 매일 **누적 전체를 다시 쓴다** — 하루 1,900건이 바뀌는데
비용은 누적 행수를 따라가고, 10만 행에서는 동시 writer 가 `database is locked` 로 죽는다

상태

**해결 (2026-08-27). 문장 5.5배 감소, 실행 5.4배 단축, 동시성 실패 제거. 변이 12/13 검출
(1건은 동치 변이), 회귀 `test_migrate_incremental.py`(8묶음, 57검사).**

### 증상 — 비용이 "그날 수집량"이 아니라 "누적"에 붙어 있다

이 스크립트는 `SELECT * FROM auction` 으로 누적 전체를 읽어 **전부 다시 쓴다.**
하루에 새로 들어오는 것은 1,900건 안팎인데:

```
누적       upsert   enqueue  migrate   합계      (하루치 실행 1회)
 2,000      46ms      89ms    208ms     0.34초
 5,000      81ms     148ms    508ms     0.74초
10,000     246ms     652ms  3,902ms     4.80초
25,000   1,377ms   1,653ms 10,322ms    13.35초
50,000   2,478ms   2,718ms 15,942ms    21.14초
```

**25배 데이터에 62배 시간.** 명백한 초선형이다.

### 원인 — 쿼리의 무게가 아니라 문장 **개수**

N=25,000 프로파일:

```
INSERT/UPDATE auction_item          25,000회  1,625ms  (49.8%)  건당 65µs
INSERT OR IGNORE document_status    75,000회    733ms  (22.5%)  건당 9.8µs
SELECT * FROM auction_item          25,000회     83ms  ( 2.5%)
```

건당 비용 차이(65 vs 9.8 = 6.6배)는 **인덱스 개수**에 거의 정확히 비례한다
(auction_item 15개 vs document_status 2개). 즉 진짜 비용은 **인덱스 쓰기 증폭**이다.
행 단위 SELECT 는 2.5%뿐이라 **그쪽을 고쳐도 소용없다.**

cProfile 로 보면 전체 4.87초 중 `sqlite3.Connection.execute` 가 2.54초(52%),
호출이 **254,892회**였다. 1,900건이 바뀐 날에 25만 문장을 보내고 있었다.

### 수정 — "빨리 보내기"가 아니라 **안 보내기**

세 자리에서 no-op 문장을 없앴다.

```
1. auction_item UPDATE     쓰려는 값이 기존과 **전부** 같으면 건너뛴다
2. auction_case INSERT     먼저 있는 것을 읽고 없는 것만 executemany
                           (id 조회를 어차피 하고 있었다 - 순서만 앞으로 옮겼다)
3. document_status INSERT  먼저 (item_id, doc_type) 집합을 읽고 없는 것만
```

같은 데이터 · 같은 조건 (하루 = 기존 변경 1,400 + 신규 500):

```
누적       migrate 전 -> 후        문장 수 전 -> 후        데이터 일치
 5,000        484ms ->    207ms     33,493 ->  9,893      OK (2.3배)
10,000      3,510ms ->  1,339ms     63,493 -> 14,893      OK (2.6배)
25,000      9,882ms ->  2,015ms    153,495 -> 29,894      OK (4.9배)
50,000     17,250ms ->  3,178ms    303,499 -> 54,896      OK (5.4배)
```

**단축률이 누적과 함께 커진다** — 건너뛰는 비율이 커지기 때문이고, 이것이 옳은 모양이다.

### ★ 속도만의 문제가 아니었다 — 10만 행에서 **동시 writer 가 죽는다**

`execute()` 는 실행 전체를 트랜잭션 하나로 묶으므로 그동안 쓰기 락을 잡는다.
Python sqlite3 의 기본 `busy_timeout` 은 **5초**다. migrate 가 도는 동안 다른
커넥션이 짧은 UPDATE 를 계속 시도하게 하고 실측했다:

```
누적       판       migrate    동시 writer 성공  locked 실패  최대 대기
 50,000   전       7,230ms          7             0         6,787ms   <- 5초를 넘겼다
 50,000   후       1,549ms          8             0         1,074ms
100,000   전      15,033ms         11             1 ★       7,284ms
100,000   후       2,907ms         10             0         2,125ms
```

10만 행에서 **실제로 `database is locked` 가 났다.** 이 저장소는 02:00~04:00
`doc_worker`, 06:00 `run_daily`, 상시 `api_server` 가 같은 파일을 쓰므로 가상의 상황이 아니다.

### 함께 좋아진 것 — `updated_at` 이 드디어 의미를 갖는다

지금까지는 전 행이 마지막 실행 시각이라 **아무 정보도 없었다**(실측: 1,876행 100%가
같은 값). 이제 "이 행이 마지막으로 **실제로** 변한 시각"이다. 제품 코드에
`auction_item.updated_at` 을 읽는 곳은 없고(전수 확인), 수집 신선도는
`audit_schedule_health.py` 가 `MAX(auction_item.crawl_date)` 로 보는데 오늘 크롤된 행은
crawl_date 가 달라져 그대로 UPDATE 되므로 그 판정은 바뀌지 않는다.

### 메모리도 함께 줄었다 — 기각 사유의 일관성 확인

선적재는 메모리를 이유로 기각했으므로, **실제로 넣은 것**이 같은 비용을 내지는 않는지
직접 재야 했다(안 그러면 기각 사유가 일관되지 않다).

```
누적       수정 전 최대   수정 후 최대   변화
25,000        67.5MB        58.6MB     -8.9MB  (-13.2%)
50,000       133.8MB       115.7MB    -18.1MB  (-13.5%)
```

**늘지 않고 줄었다.** `existing_ds` 집합은 (int, 짧은 str) 쌍 15만 개인데, 그것을 만드는
대신 없앤 것이 `conn.execute()` **151,500회**다 — 매 호출이 Cursor 와 파라미터 튜플을
만든다. 그 할당 churn 이 집합보다 컸다.

기각한 `auction_item` 선적재는 성격이 다르다. 그쪽은 **20컬럼짜리 행 전체**를 5만 개
들고 있어야 해서 +56MB 이고, 없애는 문장은 5만 개뿐이다.

### 하지 않은 것 — 행 단위 SELECT 선적재 (메모리로 재고 기각)

남은 N+1 은 `SELECT * FROM auction_item WHERE case_id=? AND item_no=?` 하나다.
dict 로 선적재하면 문장이 50,500 -> 1 이 되지만 **메모리를 쟀다**:

```
현재 최대            115.7 MB  (N=50,000)
선적재 dict 추가      56.4 MB  (+49%)
얻는 시간             약 8%
```

메모리 49%를 8%와 바꾸지 않는다. 오히려 **`SELECT * FROM auction` 의 fetchall 자체가
장기 규모의 벽**이다(50,000행에 115MB -> 20만 행이면 약 460MB). 스트리밍으로 바꾸려면
`rows` 를 세 번 순회하는 구조를 손봐야 해서 다음 스프린트로 남긴다.

### 변이 13종 중 12종 검출

살아남은 1종은 러너의 명시적 `conn.rollback()` 제거인데, `run()` 의
`finally: conn.close()` 가 열린 트랜잭션을 어차피 버리므로(실측 확인) **동치 변이다.**
그래도 그 줄은 남겼다 — 나중에 커넥션을 재사용하도록 바꾸는 순간 파일 경계가 무너지기 때문이고,
그 사유를 코드 주석에 적었다.

★ **검사가 두 번 스스로를 속였고 둘 다 변이가 잡았다.**

1. **합성 주소로 면적을 쟀다.** `extract_areas()` 는 대괄호 안에서만 읽는데
   괄호 없는 주소를 썼다 -> 면적이 늘 None 이라 **공허한 검사**였다.
   상태값도 마찬가지다 — 실데이터는 `유찰 3회`(공백)인데 괄호를 넣어 써서
   정규식에 안 걸려 fail_count 가 늘 1이었다. 실데이터 모양으로 바꿔서야 진짜를 재게 됐다.

2. **파생 필드가 원본 필드의 결함을 가려 줬다.** `appraisal_price` / `full_address` /
   `fail_count` 를 각각 "자기 자신과 비교"하도록 망가뜨려도 전부 통과했다 —
   bid_rate·면적이 **같이** 바뀌어 어차피 UPDATE 가 나갔기 때문이다.
   그 필드가 **혼자** 바뀌는 입력(최저가 0인 물건의 감정가만 변경 / 대괄호 면적은 그대로
   두고 주소 앞부분만 정정 / 파생 컬럼을 **한 번에 하나씩만** 틀어 놓기)을 따로 만들어
   셋 다 잡았다.

--------

#248

`auction`(크롤 스테이징 테이블)의 인덱스 5개 중 **3개는 읽는 사람이 없다** —
비용은 매일 크롤이 쓸 때마다 낸다

상태

**측정·검증 완료, 적용은 SKIP (2026-08-27). 마이그레이션은 만들지 않았다 — 아래 사유.**

### 발견 — 누가 `auction` 을 읽는가 (전수)

```
storage/database.py:get_stats()   mvp_scraper 가 실행 끝에 1회. GROUP BY sido / auction_date
storage/database.py:query()       ★ 제품 호출부 0건. test_db.py:70 만 부른다
migrate_execute.py                SELECT * FROM auction  (전체 스캔, 인덱스 무관)
storage/database.py:upsert_batch  (court_code, case_no, item_no) 식별키 조회
                                  -> UNIQUE 자동 인덱스를 쓴다
api/v1/*                          ★ 0건. API 는 auction_item 만 읽는다
```

즉 `idx_case_no` / `idx_court_name` / `idx_validation` 은 **죽은 함수와 임시 진단
스크립트만** 쓴다. `idx_sido` / `idx_auction_date` 는 `get_stats()` 가 실제로 쓴다.

### 비용 실측 (N=25,000, 3회 중앙값)

```
auction 인덱스        upsert 신규   upsert 갱신   get_stats   DB 크기
현재(5개)               242ms        486ms        3.0ms      10.9MB
죽은 3개 제거            200ms        360ms        2.6ms       9.4MB
                       -17.4%       -26.0%      -14.4%      -13.8%
```

**읽기가 나빠지지 않는다** — `get_stats()` 는 오히려 빨라졌다(DB 가 작아져 스캔 페이지가 준다).

### 읽기 안전성 — 쿼리 계획과 결과를 전수 대조

migration 021 의 교훈("접두니까 중복"은 점 조회에서만 맞다)이 여기 그대로 적용되므로,
지우기 전에 `auction` 을 읽는 **모든** 쿼리의 계획과 결과를 맞춰 봤다.

```
get_stats COUNT        결과 동일   COVERING idx_validation -> COVERING idx_sido
get_stats by_sido      결과 동일   SAME
get_stats by_date      결과 동일   SAME
upsert 식별키 조회      결과 동일   SAME  (UNIQUE 자동 인덱스)
migrate 전체 스캔       결과 동일   COVERING idx_validation -> COVERING idx_sido
query() sido           결과 동일   SAME
query() case_no        결과 동일   SEARCH idx_case_no -> SCAN
query() court_name     ★ 집합 다름  SEARCH idx_court_name -> SCAN idx_auction_date
query() validation     ★ 집합 다름  SEARCH idx_validation -> SCAN idx_auction_date
```

마지막 둘은 **인덱스 결함이 아니다.** 두 쿼리는
`WHERE x=? ORDER BY auction_date DESC LIMIT 100` 인데, 같은 `auction_date` 끼리의
순서를 정하지 않는다. 그래서 스캔 방식이 바뀌면 **동점 경계에서 어느 100건이 뽑히는지가
달라진다** — 인덱스가 있든 없든 이 쿼리가 원래 갖고 있던 비결정성이다.
그리고 그 함수(`query()`)는 제품에서 죽어 있다.

★ 이 대조를 처음 돌렸을 때 **4개가 "다름"으로 나왔다.** `SELECT *` 에 딸려 온
  `created_at` / `updated_at` 을 함께 비교했기 때문이다 — 두 사본을 각각 채웠으니
  `datetime.now()` 가 다른 게 당연하다. **인덱스와 무관한 차이를 인덱스 탓으로 읽을 뻔했다.**
  타임스탬프를 빼고 집합으로 비교해서야 진짜 2건이 남았다.

### 왜 마이그레이션 파일을 만들지 않았나

`run_daily.bat` 3단계가 `storage/migrations/` 의 **미적용 파일을 전부 자동 적용**한다.
즉 `026_*.sql` 을 넣는 순간 다음 실행에서 운영 DB 에 적용된다 — 그것은 이 세션의
"운영 DB 변경은 승인 영역" 규칙에 걸린다. SQL 은 아래 그대로면 되고, 적용 여부는
사람이 정한다.

```sql
DROP INDEX IF EXISTS idx_case_no;      -- auction(case_no)
DROP INDEX IF EXISTS idx_court_name;   -- auction(court_name)
DROP INDEX IF EXISTS idx_validation;   -- auction(validation_status)
```

`storage/database.py` 의 `CREATE_INDEX_SQL` 에서도 같은 3줄을 빼야 fresh clone 과
기존 DB 가 같은 상태가 된다(안 그러면 021 이 겪은 "소스는 만들고 마이그레이션은 지운다"가
반복된다).

### 적용 판단에 필요한 것 — 지금 규모에서는 급하지 않다

현재 `auction` 은 1,876행이고 `upsert_batch` 는 약 16ms다. 17~26%는 **4ms** 다.
이 항목의 가치는 누적이 2만 행을 넘어설 때 생긴다. #247 과 달리 **동시성 실패 같은
급한 사유가 없으므로** 다음 스키마 작업에 묶어 처리하는 것이 낫다.

--------

#249

`#247` 과 **같은 계열이 큐 쓰기 두 곳에 더** 있었다 — "바뀌었는지 판정을 DB 에 맡기고
문장은 전부 보낸다". `refresh_queue_priority()` 는 누적 대기 큐를 따라 커진다

상태

**해결 (2026-08-27). 변이 15/15 검출, 회귀 `test_queue_write_batching.py`(10묶음).**

### 어떻게 찾았나 — 같은 결함을 다른 경로에서 의도적으로 다시 찾았다

`#247`(migrate_execute)을 고친 뒤, 같은 모양이 더 있는지 **AST 로 전수 탐색**했다.
"루프 안에서 행마다 쓰기 문장을 보내는" 함수를 뽑으니 제품 코드에 20곳이 나왔고,
그중 **no-op 판정을 DB 에 맡기는** 것이 둘이었다.

```
enqueue_documents()       행마다 INSERT OR IGNORE 4개 (+ 안 들어가면 UPDATE 4개)
refresh_queue_priority()  대기 행마다 UPDATE 1개, no-op 은 `AND priority!=?` 로 거름
```

둘 다 **결과는 옳았다.** DB 가 걸러 주기 때문이다. 낭비되는 것은 문장이다.

### 실측 (같은 데이터를 다시 수집한, 아무것도 안 바뀐 정상적인 날)

```
입력/대기 25,000행
    upsert_batch              1,550ms   50,002문장
    enqueue_documents         2,677ms  200,002문장  ->  실제로 추가된 행  0건
    refresh_queue_priority    2,081ms  100,003문장  ->  실제로 바뀐 행    0건
```

**30만 문장을 보내고 0행이 바뀐다.**

### 왜 `refresh_queue_priority` 가 특히 나쁜가 — 누적을 따라간다

이 함수는 01:50 에 **대기 중인 큐 전체**를 훑는다. `document_queue` 는 물건 하나당
최대 4행이고 과거 사건까지 누적된다. 즉 비용이 그날 일감이 아니라 **쌓인 양**에 붙는다 —
`#247` 이 10만 행에서 동시 writer 를 `database is locked` 로 죽인 것과 같은 구조다.

운영 현재값(2026-08-27 실측): `pending 2,753 / done 559 / SKIPPED_EXPIRED 186`.
매일 밤 2,753개의 UPDATE 를 보내고 대부분의 밤 0건이 바뀐다.

### 수정

```
enqueue_documents()
    지금 입력의 (법원,사건,물건)만 **선조회** -> 없는 것만 executemany INSERT,
    기일이 다른 것만 executemany UPDATE
    ★ 큐 전체를 읽지 않는다. 메모리가 누적이 아니라 **입력 크기**(하루 약 1,900행)에 묶인다.

refresh_queue_priority()
    `priority` 를 함께 읽어 **파이썬에서** 비교 -> 바뀌는 것만 목표값별로 묶는다.
    목표는 1/2/3 셋뿐이라 **최대 3묶음**으로 끝난다.
    ★ `AND priority<>?` 가드는 그대로 둔다 — 한 묶음은 목표값이 하나라 IN 목록에 그대로
      얹히고, `rowcount` 가 "정말 바뀐 행 수"라는 뜻을 유지한다.
```

측정(회귀 테스트가 세는 값):

```
대기 120행, 바뀔 것 없음   ->  UPDATE 문장 0개   (예전 121개)
대기 120행, 전부 틀어 놓음 ->  문장 6개          (예전 121개)
큐 200행 재적재            ->  INSERT 0 / UPDATE 0
```

### `IN (...)` 이 새로 둘 생겼다 — 상한 보호를 **작은 데이터로** 고정했다

둘 다 `chunked_for_sql()` 로 나눈다(#243). 문제는 그 보호가 기본 상한(32,766)에서는
수만 행을 넣어야 발동한다는 것이다 — 그래서 지금까지 검사가 없었고, 변이로 청크 나누기를
지워도 **아무도 잡지 못했다**(실측: 변이 2종 생존).

`sqlite3.Connection.setlimit()` 으로 **커넥션의 변수 상한을 10으로 내리면** 20행짜리
입력으로 같은 경계를 만들 수 있다. 대량 DB 없이 계약을 지킨다
(`test_queue_write_batching.py` 10번). `sql_variable_limit()` 이 `conn.getlimit()` 을
쓴다는 성질까지 함께 고정된다 — 상수를 박으면 이 검사가 붉어진다.

`test_schema_hygiene.py` 의 `SQL_PLACEHOLDER_SITES` 인벤토리에도 두 곳을 등록했다.
등록하지 않으면 그 가드가 붉어진다 — **실제로 붉어져서 알았다.**

### [2026-08-27 후속] `upsert_batch()` 도 결국 했다 — 다만 **다른 방법으로**

아래 절은 "계약 위험이 이득보다 크다"고 판단해 미뤘던 기록이다. 그 뒤 계약을 안전하게
바꾸는 방법(`unchanged` 칸 신설 + `persisted` 에 합산)을 그대로 실행해 해소했다.

★ **첫 구현은 성능을 되레 깎았다.** 비교할 15개 컬럼을 함께 `SELECT` 해 파이썬에서
튜플로 맞춰 봤는데, 실측하니 **1,876행에서 41.6ms -> 63.4ms(0.7배)** 였다. 넓은 SELECT 와
튜플 생성 비용이 절약한 쓰기보다 컸다. "덜 쓰면 빠르다"는 짐작이 틀렸다.

비교를 **SQL 의 WHERE** 로 옮기고서야 이득이 났다 —
`UPDATE ... WHERE <식별키> AND (col IS NOT ? OR ...)`. 문장 수는 예전과 같고
(SELECT 1 + UPDATE 1) **실제 쓰기만 사라진다.** `rowcount` 가 곧 "정말 바뀌었나"다.

```
하루 재크롤(값이 안 바뀐 정상적인 날, 5회 중앙값)
  행수      수정 전    수정 후    쓴 행 전 -> 후
  1,876     38.6ms    23.9ms    1,876 -> 0   (1.6배)
  5,000    100.4ms    61.5ms    5,000 -> 0   (1.6배)
 10,000    241.6ms   120.4ms   10,000 -> 0   (2.0배)
```

`IS NOT` 를 쓴다 — `<>` 는 한쪽이 NULL 이면 NULL(=거짓)이라 **NULL 이 든 열의 변경을
통째로 놓친다.** 레거시 행에 NULL 이 실재하므로 이것이 실제 차이다.

**계약 변경(위험한 쪽)은 이렇게 막았다.**

```
upsert_batch() -> {"inserted", "updated", "unchanged", "failed"}
CrawlOutcome.persisted = inserted + updated + unchanged
```

`unchanged` 를 빼먹으면 법원 자료가 그대로인 **정상적인 날에 `persisted == 0` 이 되어
크롤이 실패로 끝나고 `migrate_execute.py` 가 아예 실행되지 않는다.**
`test_crawl_exit_code.py` §4 와 `test_crawl_orchestration.py` §3-b 가 그 경로를 고정한다.

`updated` 를 "찾은 행 수"로 두는 손쉬운 길은 택하지 않았다 — 그러면 아무것도 안 바뀐 날에도
배치 로그가 *"업데이트: 1,876건"* 을 찍는다(#47 과 같은 부류).

### 변이 10/10 검출 — 그리고 두 번은 검사가 스스로를 속였다

`test_upsert_change_detection.py`(5묶음) 신설. 변이 10종 전부 검출.
★ 처음엔 **8/10** 이었고, 놓친 둘이 전부 **검사 설계 잘못**이었다.

1. **NULL 검사가 열을 여러 개 동시에 비웠다.** 그러면 서로가 서로를 가려 준다 —
   한 열의 비교가 망가져도 **다른 열이 UPDATE 를 유발**해 그 김에 같이 써진다.
   `IS NOT` -> `<>` 변이가 그렇게 살아남았다. **한 번에 한 열만** 비우도록 고쳐 잡았다.
2. **`mvp_scraper` 의 배선을 아무도 실제로 태우지 않았다.** 유일한 검사가
   `upsert_batch` 를 가짜로 덮고 있어서, 그 값을 `outcome` 으로 옮기는지 볼 수 없었다.
   **진짜 upsert 로 `run_courts()` 를 재실행**하는 검사를 넣어 잡았다.

그 과정에서 **가짜와 실제 계약의 불일치**도 드러났다 — `test_crawl_orchestration.py` 의
가짜 `upsert_batch` 가 `unchanged` 를 안 돌려줘 `mvp_scraper` 가 KeyError 로 죽었다.
제품 결함이 아니라 가짜가 낡은 것이었고, 가짜를 실제 계약에 맞췄다.

### 하지 않은 것 — `upsert_batch()` 의 무조건 UPDATE (일부러 남긴다)

같은 계열이 하나 더 있다: `upsert_batch()` 는 값이 같아도 매번 18컬럼 UPDATE 를 보낸다.
**고치지 않았다.** 이유는 성능이 아니라 **계약**이다.

```python
persisted = inserted + updated
if self.persisted == 0: return "DB 저장 0건"   # -> exit 1 -> run_daily.bat [FAILED]
```

`updated` 를 "정말 바뀐 행"으로 줄이면, 법원 자료가 하루 종일 그대로인 **정상적인 날에
크롤이 실패로 판정**되고 `migrate_execute.py` 가 아예 실행되지 않는다. 이 저장소가
반복해서 잡아 온 "배치 로그가 사실이 아닌 것을 말한다"(#47)의 정반대 방향 사고다.

안전하게 고치려면 `unchanged` 카운터를 새로 만들고 `persisted = inserted + updated +
unchanged` 로 바꿔야 한다 — `CrawlOutcome` / `mvp_scraper` / 관련 검사까지 함께 가는
계약 변경이다. 그런데 `upsert_batch()` 는 **오늘 크롤분에만 비례**하고(누적과 무관,
약 1,876행/일 = 약 16ms) 위 둘과 달리 급한 사유가 없다. 그래서 다음 스프린트로 남긴다.

--------

#250

**회귀 검사가 그날 진짜 CSV 백업을 파괴했다.** `test_crawl_orchestration.py` 가
`save_csv_backup()` 을 실제로 돌리는데, 파일명이 `auction_<오늘>.csv` 로 고정이라
운영 산출물을 QA 한 줄로 덮어쓰고 `finally` 가 그것을 지웠다

상태

**해결 (2026-08-27). 회귀 `test_crawl_orchestration.py` (CSV 절, 검사 4개 추가).**

### 어떻게 드러났나

세션 시작 시 `ls` 에 `auction_20260827.csv` 가 있었다. 검사를 한 번 돌린 뒤 다시 보니
**없었다.** CSV 는 `.gitignore` 대상이라 `git status` 는 아무 말도 하지 않는다 —
조용한 소실이다.

```
세션 시작    auction_20260827.csv 있음
검사 1회     save_csv_backup([QA 1행]) -> 같은 경로를 덮어씀
검사 종료    finally: os.remove(written)   <- "이 검사가 만든 CSV" 라고 믿었다
결과         그날 백업 소실 (git 도 모른다)
```

이 파일 위쪽은 이미 DB 를 스크래치로 갈아끼워 격리하고 있었다(`db.DB_PATH = scratch`).
**그 격리를 이 산출물만 갖고 있지 않았다.**

### 고친 방법 — 검사의 목적은 그대로 두고 목적지만 뺀다

이 검사의 목적은 "CSV 가 **cwd 를 따라가지 않는가**"(Sprint 252)다. 그 성질은
목적지를 갈아끼워도 그대로 확인된다 — cwd 와 목적지를 **서로 다른 폴더**로 두고
결과가 어느 쪽에 떨어지는지 보면 된다.

제품에 `mvp_scraper.CSV_BACKUP_DIR` 를 뒀다(기본값 `_HERE`, 경로 규칙은 무변경).
`storage.database.DB_PATH` 를 스크래치로 갈아끼우는 것과 **정확히 같은 방식**이다.

추가한 검사:

```
★ CSV_BACKUP_DIR 의 기본값이 저장소(모듈 위치)다     <- 기본값이 바뀌면 잡는다
★ CSV 백업이 실행 폴더(cwd)에 떨어지지 않는다        <- 원래 목적, 그대로
★ CSV 백업이 지정된 폴더에 생긴다(cwd 가 아니라)
★ 이 검사가 그날 운영 CSV 백업을 건드리지 않는다     <- #250 자체의 회귀
```

마지막 것은 검사 전후로 그 경로의 존재/mtime 을 비교한다. **검사가 자기 부작용을
스스로 감시한다.**

### 남은 것

소실된 `auction_20260827.csv` 는 복구하지 않았다. `.gitignore` 대상이라 이력이 없고,
DB 에서 재생성하면 "그날 크롤이 실제로 뽑은 것"이 아니라 **지금 DB 의 상태**가 된다 —
백업의 뜻이 달라진다. 다음 06:00 크롤이 새로 남긴다.

--------

#251

**실 DB 를 `shutil.copy2()` 로 뜨는 검사가 3파일에 8곳 남아 있었다.** `#`(Sprint 253)에서
만든 정적 감사가 **변수 별칭을 따라가지 못해** 전부 놓쳤다

상태

**해결 (2026-08-27). 8곳 전부 `snapshot_live_db()` 로. 감사에 별칭 추적 + 자기 검증 3개.**

### 증상 — 밤마다 흔들리는 검사 하나

```
전체 스위트 1회차   test_crawl_orchestration.py  FAILED (12건)
전체 스위트 2회차   test_crawl_orchestration.py  PASSED
단독 실행 12회      12/12 PASSED
```

1회차가 붉어진 시각(22:33)에 **다른 프로세스가 실 DB 를 읽고 있었다**(같은 세션의
벤치마크). `snapshot_live_db()` 의 docstring 이 이미 그 이유를 실측으로 적어 두었다 —
"SQLite 파일을 OS 파일 복사로 뜨면 다른 프로세스가 쓰는 중일 때 **찢어진 사본**이 나온다".

### 왜 감사가 못 잡았나 — 글자만 봤다

`test_db_snapshot.py` 의 정규식은 `copy2(...)` 의 인자에 `DB_PATH` 라는 **글자**가
있는지를 본다. 실제 코드는 이랬다:

```python
real_db = db.DB_PATH             # 한 번 받아 두고
shutil.copy2(real_db, scratch)   # 글자로는 DB_PATH 가 없다
```

같은 파일을 가리키는데 검사만 다른 것을 봤다. **감사가 있는데 증상이 났다면 감사가
부족한 것이다.**

### 고친 방법 — 한 파일 범위의 얕은 별칭 추적

`<이름> = ...DB_PATH...` 로 묶인 지역 이름을 모아, 그 이름이 `copy2()` 의 첫 인자로
쓰이면 같은 위반으로 본다. 정확한 데이터플로가 아니지만 **실제로 난 모양을 덮는다.**

강화한 감사가 **곧바로 두 곳을 더 찾아냈다** — 사람이 눈으로 찾은 것이 아니다:

```
test_crawl_orchestration.py  (별칭 real_db)     1곳
test_auction_identity.py     (별칭 real_path)   6곳
test_refresh_priority.py     (별칭 src)         1곳
```

오탐을 막는 자기 검증도 함께 뒀다(무관한 `copy2(src_pdf, dest_pdf)` 는 안 잡는다 /
DB 를 가리켜도 복사에 안 쓰이면 안 잡는다).

--------

#252

`audit_test_reality.py` 에 **다른 컴퓨터의 사용자 프로필 절대경로**가 박혀 있어
이 PC 에서는 `os.chdir()` 이 곧바로 죽었다 — **있는데 한 줄도 안 도는 감사**

상태

**해결 (2026-08-27).** `REPO = os.path.dirname(os.path.abspath(__file__))`.
`test_schema_hygiene.py` 의 하드코딩 경로 검사가 이미 이것을 붉게 잡고 있었다 —
검사는 맞았고 대상이 안 고쳐져 있었다. 저장소의 다른 곳(`DB_PATH`, `_HERE`)과 같은 규칙.

--------

#253

**OneDrive 충돌 사본 8개가 git 에 추적되어** 제품 감사를 영구히 붉게 만들었다

상태

**해결 (2026-08-27) — 분리해서 보이게 했다. 사본 자체는 사람이 정리할 부채로 남긴다.**

```
.cov_test_audit_selftests-DESKTOP-DVRJEGP_py     <- 추적된 SQLite DB 로 잡힘
audit_viewport-DESKTOP-DVRJEGP.py:313            <- 드라이버 직접 생성으로 잡힘
audit_auth_health-DESKTOP-DVRJEGP.py
audit_test_reality-DESKTOP-DVRJEGP.py
test_admin_secret_contract-DESKTOP-DVRJEGP.py
test_audit_selftests-DESKTOP-DVRJEGP.py          <- 스위트에서 FAILED
test_crawl_orchestration-DESKTOP-DVRJEGP.py      <- 스위트에서 FAILED (KeyError)
test_max_items_contract-DESKTOP-DVRJEGP.py
```

내용은 제품 파일의 **옛 판본**이다(예: `test_crawl_orchestration-DESKTOP-DVRJEGP.py` 는
`upsert_batch` 에 `unchanged` 가 생기기 전 판본이라 `KeyError: 'unchanged'` 로 죽는다).

### 왜 그냥 지우지 않았나

각 쌍에서 **어느 쪽이 최신인지 골라야** 하고, 그건 사람의 판단이다. 자동으로 지우면
멀쩡한 판본을 날릴 수 있다.

### 그래도 붉은 채로 두지 않는다 — 숨기지 않고 옮긴다

제품 감사(추적 SQLite / 드라이버 직접 생성)에서는 빼되, **전용 검사**를 새로 만들어
목록을 그대로 찍고 **개수가 늘면 붉어지게** 했다. `run_python_tests.py` 가 "통과와
무판정을 절대 합치지 않는다"고 적어 둔 것과 같은 판단이다 — 영구히 붉은 게이트에서는
**새 회귀와 이미 아는 부채를 구별할 수 없다.**

--------

#254

**기일이 다시 잡혔는데 `SKIPPED_EXPIRED` 로 굳은 큐 행이 36개.** 오늘 매각이 진행되는
물건의 **감정평가서만** 조용히 영구 누락되고 있었다

상태

**해결 (2026-08-27). 회귀: `test_document_queue.py` 12-C 신설 + 12 갱신,
`test_queue_write_batching.py` 3 갱신, `test_pipeline_integrity.py` 는 정적 계수에서
런타임 증명으로 승격.**

### 실측 — 같은 물건에서 세 개는 살고 하나만 죽는다

```
법원=창원지방법원 / 2023타경7795 / item 1
  spec        pending          auction_date=2026-08-27   <- 오늘 수집된다
  status      pending          auction_date=2026-08-27   <- 오늘 수집된다
  image       pending          auction_date=2026-08-27   <- 오늘 수집된다
  appraisal   SKIPPED_EXPIRED  auction_date=2026-08-27   <- "기일이 지났다"고 말한다
```

행이 자기 필드로 자기 주장을 반증하고 있다. 전수로 세면 **36행, 전부 appraisal,
전부 `auction_date` 가 오늘**이고, `document_status` 기록 없음 / `doc_raw` **0행** —
**한 번도 받은 적이 없다.**

### 왜 아무도 다시 안 보나

```
reset_stale_queue()    SKIPPED_* 를 일부러 안 건드린다 (성공 못 할 항목의 영원한 부활 방지)
enqueue_documents()    날짜만 고치고 status 는 그대로 뒀다 (Sprint 74)
그 날짜 고치기조차     "기일이 **바뀌었을 때만**" 돌았다
                       -> 날짜가 이미 최신인 채 굳은 행은 **영원히 안 고쳐진다**
```

### 이것은 보류된 "재수집 정책"이 아니다

Sprint 74 는 `done`/`failed`/`SKIPPED_EXPIRED` 되살리기를 **제품 판단**이라며 보류했다.
그 보류의 내용은 *이미 받아 둔 것을 또 받을지*다. 여기 36행은 `doc_raw` **0행**이다 —
되살리는 것은 재수집이 아니라 **첫 수집**이고, 고치는 것은 "큐가 자기 필드에 사실과
다른 값을 들고 있는 것"뿐이다. Sprint 74 가 `auction_date` 에 대해 내린 판단과 같다.

### 범위를 좁게 잡았다

```
SKIPPED_EXPIRED + 기일이 안 지남   -> pending, retry_count=0   (되살린다)
done / failed                      -> 그대로                    (재수집 정책, 보류 유지)
SKIPPED_UNSUPPORTED                -> 그대로                    (시간이 지나도 성공 못 한다)
```

`retry_count=0` 은 새 정책이 아니다 — `reset_stale_queue()` 가 하루 지난 `failed` 를
되돌릴 때 쓰는 규칙 그대로다. 되돌리지 않으면 예산이 소진된 행이 `pending` 으로 남아
"pending 인데 재시도가 소진된 행 0건" 불변식을 깬다.

### 실 데이터로 증명했다 (운영 DB 는 안 건드렸다)

실 DB **스냅샷**에 오늘 크롤과 같은 입력을 재생:

```
BEFORE  기일이 안 지났는데 SKIPPED_EXPIRED   36행
재생    enqueue_documents(2,608행)
        -> revived_expired 36 / added 0 / refreshed 0
AFTER   0행
        done 746행 그대로 (되살리기가 종결 상태를 무차별로 열지 않는다)
```

운영 DB 는 **다음 06:00 적재가 스스로 고친다** — 여기서 쓰지 않았다.

### ★ 날짜가 바뀌며 **비용이 실측됐다** (2026-08-28 00:30)

같은 세션 안에서 자정을 넘겼다. 어제 36행이던 것을 다시 재니:

```
today = 2026-08-28
기일이 안 지났는데 SKIPPED_EXPIRED : 11행   <- 아직 되살릴 수 있다
그 36행의 기일 분포
    2026-08-27   25행   <- **어젯밤 사이에 기일이 지났다**
    2026-08-28    2행
    2026-09-01    6행
    2026-09-07    2행
    2026-09-09    1행
```

**25행은 이제 되살려도 소용이 없다.** 매각기일이 지난 사건은 법원경매정보의
사건번호 직접검색으로도 조회되지 않는다(Step 13/14 실측 8건, 이 파일 `enqueue_documents`
주석 참고). 즉 그 25건의 감정평가서는 **영구히 받을 수 없다.**

이 결함은 가만히 있는 것이 아니라 **매일 조금씩 회복 불가능한 손실로 바꾸고 있었다.**
하루만 늦게 발견했으면 11행도 그렇게 됐을 것이다. "상한 1" 이 "36" 이 되도록
누가 봐도 늘어나 있었는데, 그 숫자가 무엇을 뜻하는지는 아무도 세어 보지 않았다.

### 검사도 함께 승격했다 (정적 계수 -> 런타임 증명)

`test_pipeline_integrity.py` 는 이것을 "상한 1" 로 세고 있었고 1 -> 36 이 되어 붉어졌다.
그런데 **고친 뒤에도 운영 DB 는 다음 적재 전까지 그대로**라, 세는 방식으로는 "고쳤는데도
붉은" 상태가 남는다. 그래서 잔량을 세는 대신 **불변식을 직접 증명**하도록 바꿨다 —
스냅샷에 적재를 재생해 0 이 되는지 본다. 마지막 크롤 시각과 무관하게 성립한다.

--------

#255

`test_pipeline_integrity.py` 의 물건종류 오분류 검사가 **회사 상호를 물건 종류로 읽어**
오탐을 냈다. 상한을 올릴 뻔했다

상태

**해결 (2026-08-27). 상한은 4 그대로. 검사에 상호 제거 + 자기 검증 3개.**

"역방향 오분류 5건(상한 4)" 으로 붉어졌다. 상한을 5로 올리려다 **다섯째를 실제로 봤다**:

```
542    기타  [기타 동력선]                              진짜 선박
1806   기타  [선박 동력선, 동어호]                       진짜 선박
6311   기타  [선박 동력선 혜원5호]                       진짜 선박
12093  기타  [선박 동력선 공축5호]                       진짜 선박
13732  기타  [토지 도로 368㎡ 에이스건설기계주식회사 지분 2분의 1 전부]   <- 토지다
```

마지막은 **토지**다. `VEHICLE` 정규식의 "건설기계" 가 소유자 **상호**에 걸린 것이고
물건 종류와는 아무 상관이 없다. 즉 늘어난 1건은 데이터 결함이 아니라 **검사의 오탐**이었다.

상한을 올렸으면 오탐을 정상으로 굳히고, 그 한 칸으로 **진짜 오분류 하나가 조용히
통과**했을 것이다. Sprint 251 이 "근거 없는 여유 2칸" 을 없앤 것과 같은 이유다.

판정 전에 `…주식회사` / `㈜…` / `(주)…` 를 걷어낸다. 자기 검증으로 고정했다 —
상호 속 "건설기계" 는 안 잡고, 진짜 선박과 상호가 아닌 "건설기계" 는 그대로 잡는다.

--------

#256

`upsert_batch()` 가 행마다 **두 문장**(SELECT + INSERT/UPDATE)을 보냈다. 하루치
파이프라인 전체 문장의 **99%** 가 여기였다

상태

**해결 (2026-08-27). 한 문장 upsert 로. 회귀 `test_upsert_change_detection.py` 6-A~6-E 신설.**

### 먼저 쟀다 — 어디가 99% 인지

```
하루치 경로 (운영 2,608행 재크롤, 값 동일)
  upsert_batch              5,219문장   30.3ms
  enqueue_documents            40문장   39.1ms
  refresh_queue_priority        2문장    3.6ms
  reset_stale_queue             7문장    0.8ms
```

문장 수는 **압도적으로 upsert** 였다(5,219 / 5,268 = 99%). 그리고 규모를 키워도
꺾이는 지점은 없었다 — 1천~5만 행에서 **선형**이었다(약 90k행/초). 즉 급한 병목은
아니고, 줄일 수 있는 낭비였다.

### ★ 곧은 길이 훨씬 느렸다 — 재 보지 않았으면 성능을 깎았을 것이다

분류(신규/갱신/무변화)를 `RETURNING created_at` + `fetchone()` 으로 하는 것이 가장
자연스럽다. **그것을 먼저 만들었고, 신규 경로가 3배 느려졌다**(50,000행 580ms -> 1,921ms).
원인을 갈라 재 보니 upsert 가 아니라 **커서 물질화**였다(20,000행 신규):

```
plain INSERT                              99.4ms
SELECT + plain INSERT (예전 구현)         123.7ms
upsert, RETURNING 없음                    99.8ms    <- upsert 자체는 공짜다
upsert + RETURNING + fetchone            622.4ms    <- 6배
```

`#249` 때와 같은 교훈이다("넓은 SELECT 로 파이썬에서 비교" 가 더 느렸던 것).
**문장 수가 준다고 빨라지는 것이 아니다.**

### 고친 방법 — 분류를 행마다 묻지 않는다

배치 앞뒤로 **두 번만** 센다. SQL 을 한 문장도 더 쓰지 않는다.

```
inserted  = 행 수 증가분              (COUNT(*) 두 번)
written   = conn.total_changes 증가분 (문장 없음)
updated   = written - inserted
unchanged = 처리한 행 - written
```

### 결과 — 모든 규모/모든 경로에서 이득, 결과값은 완전히 동일

```
             신규            변화없음         변경           문장
 2,608행   32.0->29.8ms    27.9->22.6ms   41.3->35.7ms   5,219->2,613
10,000행  113.5->104.1ms  105.6->82.9ms  152.2->124.7ms 20,003->10,005
50,000행  580.7->529.7ms  536.4->414.4ms 782.3->674.6ms 100,003->50,005
```

하루치 경로 전체: 136.1ms -> 122.8ms.

### 유도가 깨지면 조용하지 않다

이 유도는 **한 upsert 가 정확히 0 또는 1행만 바꾼다**는 전제 위에 있다. `auction` 에는
트리거가 없고 이 테이블을 참조하는 외래키도 없다(전수 확인). 전제가 깨지면 계수가
음수가 되고, 그때 **ERROR 로그**로 원인(트리거/외래키)을 짚는다. 이 값들은
`CrawlOutcome.persisted` 를 거쳐 크롤의 **종료코드**가 되므로 조용히 틀리면 안 된다.

`test_broken_derivation_is_loud_not_silent()` 가 실제로 트리거를 심어 그 경보를 울려 본다 —
**자기 검사가 장식이 아님을 검사가 증명한다.**

### 함께 고정한 것

```
6-A  트리거/참조 외래키가 없다 (유도의 전제)
6-B  전제가 깨지면 ERROR 로그가 나간다 (트리거를 실제로 심어 확인)
6-C  갱신이 created_at / has_spec_pdf / has_status_doc / has_appraisal_pdf 를 보존한다
6-D  한 배치 안의 중복 키 (같은 값 / 다른 값)
6-E  행마다 한 문장이다 (SELECT 는 배치당 2번뿐)
```

6-C 가 중요하다 — SET 목록을 새로 조립했으므로, 거기에 `has_*` 가 끼면 **문서 수집
결과가 매일 크롤에 지워진다.** 조용하고 되돌리기 어려운 손실이다.

--------

#257

**스크래치 DB 를 뜨는 검사 헬퍼가 실 DB 가 아니라 직전 스크래치를 복사하고 있었다.**
검사끼리 스키마 객체가 새어 나갔다

상태

**해결 (2026-08-27). 3파일(`test_upsert_change_detection` / `test_migrate_incremental` /
`test_queue_write_batching`)에서 실 DB 경로를 한 번만 붙잡아 두도록.**

### 어떻게 드러났나 — 새로 쓴 검사가 스스로를 오염시켰다

`#256` 의 6-B 는 유도를 깨뜨리려고 스크래치 DB 에 트리거를 심는다. 그랬더니 **6-D 가
틀린 값을 봤다**:

```
6-D 를 스위트 안에서   inserted = 2   <- 틀렸다
6-D 만 단독으로        inserted = 1   <- 맞다
```

원인은 헬퍼였다:

```python
def scratch_db():
    ...
    dbmod.snapshot_live_db(path)   # 원본 = 지금의 dbmod.DB_PATH
    ...
    dbmod.DB_PATH = path           # <- 여기서 갈아끼운다
```

두 번째 호출부터는 **직전 스크래치의 사본**을 뜬다. 행은 지우므로 데이터는 안
넘어온다 — **그래서 지금까지 아무도 몰랐다.** 넘어가는 것은 **스키마 객체**다.

같은 모양이 `test_migrate_incremental.py`(헬퍼 12회 호출)와
`test_queue_write_batching.py`(11회 호출)에도 있었다. 지금은 증상이 없지만 전제가 같다.

이 세션의 `#251`(찢어진 DB 사본)과 같은 부류다 — **격리한 줄 알았는데 아니었다.**

--------

#258

`audit_test_reality.py` 는 "다른 검사가 공허하지 않은가"를 재면서 **자기 자신은 아무도
재지 않았다.** 그리고 이 도구가 틀리면 나오는 것은 오류가 아니라 **그럴듯한 숫자**다

상태

**해결 (2026-08-27). `--selftest` 신설(검사 15개), `test_audit_selftests.py` 의 TOOLS 에 등록.**

### 어떻게 드러났나 — 다른 것을 고치자 이것이 튀어나왔다

`#252` 로 하드코딩 경로를 고쳤더니 이 도구가 **비로소 실제로 돌기 시작했다.** 그러자
`test_audit_selftests-DESKTOP-DVRJEGP.py`(충돌 사본)가 이 도구를 `--selftest` 로
부르는데 그런 인자가 없어 **전체 스윕이 돌았고 605초**로 파일당 상한에 걸렸다.
스위트가 2분에서 **12분**이 됐다.

즉 세 가지가 한 줄에 있었다: 죽은 감사 / selftest 없음 / 충돌 사본. 각각 고쳤다
(#252 / 이 항목 / #253).

### selftest 가 무엇을 붙잡나 — 전체 스윕은 selftest 로 쓸 수 없다

69개 파일 x coverage 는 몇 분이 걸린다. 그래서 **판정 로직과 측정 경로만** 태운다.

```
[1] is_product()  분류가 **양쪽으로** 옳은가 (제품을 제품이라 / 검사를 검사라)
[2] run_one()     제품을 지나는 파일에서 **0보다 큰** 줄 수가 나오는가
[3] run_one()     제품을 안 지나는 파일에서 **정확히 0** 이 나오는가
[4] 측정 실패가 **이유를 남기는가**
```

[2]와 [3]이 짝이다. 한쪽만 있으면 "항상 0" 이나 "항상 큰 수"인 고장을 못 잡는다.
합성 파일 두 개를 즉석에서 만들어 실제로 coverage 를 돌린다(문자열 검사가 아니다).

### selftest 를 붙이자마자 진짜 결함이 하나 나왔다

```python
raw = out.stdout.decode(...)
i = raw.find("{")
if i < 0:
    return None          # <- 여기
```

호출부는 `(r or {}).get("error", "")` 로 읽는다. 즉 화면에는 **"측정 실패" 뒤에 빈칸**만
남는다 — 왜 실패했는지 한 글자도 없다. **공허함을 재는 도구가 자기 실패를 조용히
삼키고 있었다.** 이제 stderr 를 담아 이유를 들려 보낸다.

### 덤 — 주석 두 곳의 이름이 깨져 있었다

`PRODUCT_ROOT_FILES` 의 설명에서 백틱 안 이름 두 개가 통째로 비어 있었다
("처음엔 빠져 있어서  가 실행 0줄로 나왔다"). `test_runner_contract.py` 가
`run_python_tests` 를 import 하는 것을 확인하고 복원했다(추측하지 않았다).

--------

#259

장시간 검사가 **DB 안의 누적만** 보고 있었다. 프로세스 자원(커넥션/핸들/메모리)과
**바퀴마다 느려지는가**는 아무도 재지 않았다

상태

**해결 (2026-08-27). `test_scheduler_longrun.py` 6절 신설. 변이 4/4 검출.**

### 비어 있던 자리

`test_scheduler_longrun.py` 1~5 절은 큐 행/재시도 예산/재개 의도/멱등을 촘촘히 본다.
비어 있던 것은 **프로세스 밖**이다:

```
sqlite 커넥션이 닫히지 않고 쌓인다   -> 결국 "database is locked"
파일 핸들이 쌓인다                    -> 결국 열기 실패
파이썬 객체가 쌓인다                  -> 밤새 돌면 메모리가 따라 오른다
바퀴마다 조금씩 느려진다              -> "처음엔 정상인데 아침에 안 끝나 있다"
```

이 저장소의 DB 함수는 전부 `try/finally: conn.close()` 를 쓴다. **그 규약이 지켜지는지
아무도 확인하지 않았다** — 한 함수에서 `finally` 를 빠뜨려도 하루치 검사는 전부 통과한다.

### ★ 검출기 판본을 두 번 버렸다 — 둘 다 변이가 그대로 통과했다

변이는 하나다: `refresh_queue_priority()` 의 `finally: conn.close()` 를 지운다.

```
1판  gc.get_objects() 로 살아 있는 Connection 개수를 센다
     -> 변이 통과. CPython 참조 카운팅이 함수 종료 즉시 회수한다.
        "누수가 없다"가 아니라 **"측정할 수 없다"** 를 통과로 읽고 있었다.

2판  conn.close 를 파이썬 함수로 갈아끼워 호출을 센다
     -> 변이 통과. sqlite3.Connection 은 C 타입이라 **속성을 붙일 수 없다**.
        그리고 그 AttributeError 를 잡는 갈래가 "감쌀 수 없으면 닫힌 것으로 친다" 였다
        — **실패를 통과로 바꾸는 폴백**이다. 이 저장소가 반복해서 잡아 온 그 모양이다.

3판  factory= 로 Connection 을 **상속**한다(파이썬이 공식 지원하는 자리).
     상속 인스턴스는 __dict__ 가 있어 중복 close 도 가른다. **폴백을 두지 않는다** —
     감쌀 수 없으면 그 사실 자체를 별도 단언으로 잡는다.
     -> 변이 4/4 검출 (10바퀴에 10개 누수).
```

즉 이 절을 만들면서 **검사가 스스로를 속이는 방식을 두 가지 새로 배웠다.**
`#256` 의 6-B(트리거를 실제로 심어 경보를 울려 본다)와 같은 규율이다.

### 측정 결과 — DB 경로는 깨끗하다

10바퀴(같은 입력을 다시 흘림) / 별도로 20바퀴까지 확인:

```
연 커넥션 165개 -> 닫힌 것 165개 (누수 0)
파일 핸들      128 -> 128 (무변화)
파이썬 힙      0.03MB 고정
DB 행수        **전 테이블 무변화** (완전 멱등)
바퀴 소요      0.059s -> 0.013s (느려지지 않는다. 큐가 빠지며 오히려 준다)
RSS            28.8 -> 33.9MB (초반 5MB 오른 뒤 평평 - SQLite 페이지 캐시)
```

판정은 절대값이 아니라 **기울기**로 한다. 첫 바퀴는 캐시/임포트가 데워지느라 원래
다르므로 워밍업 3바퀴를 버리고 그 뒤 구간만 본다.

--------

#260

`claim_next_queue_item()` 이 **누적을 따라 느려진다** — 한 건 집으려고 대기 행 전체를
임시 B-tree 로 정렬한다

상태

**측정만 하고 고치지 않았다 (2026-08-27). 지금 규모에서는 비용이 0이고,
고치는 수단이 승인 영역이다. 다음 스프린트 후보로 남긴다.**

### 무엇을 쟀나

```sql
SELECT ... FROM document_queue
 WHERE status IN ('pending','refresh') AND (재시도 간격)
 ORDER BY priority ASC, auction_date ASC LIMIT 1
```

```
EXPLAIN QUERY PLAN
  SEARCH document_queue USING INDEX idx_queue_status (status=?)
  USE TEMP B-TREE FOR ORDER BY          <- 한 건 집으려고 전부 정렬한다
```

비용이 **claimable 행 수에 비례**한다. 워커는 이 함수를 하룻밤에 수천 번 부른다.

```
큐 8,000행  (pending 800)     claim40  90ms
큐 40,000행 (pending 4,000)   claim40 121ms
큐 160,000행(pending 16,000)  claim40 212ms
큐 160,000행(pending 96,000)  claim40 562ms   <- 6.2배
```

### ★ 답은 인덱스 추가가 아니었다 — 통계였다

복합 인덱스 `(status, priority, auction_date)` 를 만들어 재려다, 먼저 `ANALYZE` 만
따로 재 봤다. **그것만으로 이득이 전부 나왔다**:

```
                    기준      ANALYZE만      +복합 인덱스
큐 160k/pending 16k  212ms   94ms (2.3배)   132ms (1.6배)
큐 160k/pending 96k  562ms   83ms (6.8배)    95ms (5.9배)
```

통계가 생기면 플래너가 **이미 있는** `idx_queue_priority` 를 골라 정렬 없이 훑다가
첫 행에서 멈춘다. 새 인덱스는 아무것도 더 주지 못하면서 디스크와 쓰기 비용만 늘린다.
**인덱스를 추가했으면 이득의 출처를 오해한 채 부채만 늘렸을 것이다.**

### 그런데 지금 규모에서는 0이다 — 그래서 고치지 않는다

운영 실 데이터 스냅샷(큐 6,876행 / claimable 809행)에서:

```
ANALYZE 전  claim x60  156.6ms
ANALYZE 후  claim x60  156.1ms   (1.00배 — 계획도 그대로 임시 B-tree)
```

claimable 이 809행뿐이라 정렬이 공짜다. `sqlite_stat1` 이 낡아 있기는 하다
(document_queue 5,683 vs 실제 6,876) 그러나 **그 낡음이 오늘 비용을 만들지 않는다.**

### 남은 위험 — 되먹임 고리

claim 비용은 **총 큐**가 아니라 **claimable** 을 따라간다. claimable 은 하루치로
묶여 있어(물건수 x 4) 평소에는 안 자란다. 위험한 것은 **워커가 밀릴 때**다:

```
워커가 밀린다 -> pending 이 쌓인다 -> claim 이 느려진다 -> 더 밀린다
```

이 고리가 돌기 시작하면 `ANALYZE` 한 번이 그것을 끊는다(운영 실측 7.3ms).
지금 넣지 않는 이유는 **효과가 0인 시점에 운영 DB 를 건드리지 않기 위해서**이고,
`sqlite_stat1` 갱신은 스키마 영역이라 승인 대상이다(docs/CLAUDE.md).

**다음 스프린트 제안**: `reset_stale_queue()`(워커 시작 02:00)에서
claimable 이 임계(예: 5,000행)를 넘을 때만 `ANALYZE document_queue` 를 돌린다.
평소에는 아무것도 하지 않고, 고리가 돌기 시작할 때만 개입한다.

--------

#261

**크롤에는 성공했는데 정규화에서 떨어진 건수가 아무 데도 남지 않았다.** 부분 손실이
로그·요약·종료코드 어디에도 드러나지 않는다

상태

**해결 (2026-08-27). `CrawlOutcome.normalize_dropped` + `warnings()` 신설.
회귀 `test_crawl_orchestration.py` 5-b (검사 10개). 변이 3/3 검출.**

### 무엇이 문제였나

`normalize_batch()` 는 기형 행 하나가 배치를 죽이지 않도록 **그 행만 버린다**
(Sprint 78 — 옳은 격리다. `test_normalizer.py` 가 그 격리를 고정하고 있다).

문제는 격리가 아니라 **버렸다는 사실이 파이프라인에서 사라진 것**이다.

```python
rows = normalize_batch(all_items)
logger.info("정규화 완료: %d건", len(rows))     # <- 여기
```

2,608건을 받아 2,600건을 찍어도 **그 줄만으로는 8건이 없어진 것을 알 수 없다.**
앞줄의 수집 건수와 손으로 빼 봐야 안다. 그리고:

```
수집 2,608 -> 정규화 2,600 -> 저장 2,600 -> 종료코드 0
법원에서 받아 온 8건이 DB 에 닿지 못했는데 아무도 모른다.
```

**전부** 떨어지면 `persisted == 0` 으로 잡힌다(#47 이 만든 판정). 부분 손실만
어디에서도 잡히지 않았다 — 이 저장소가 반복해서 고쳐 온 **"조용한 손실"** 이다.
`CrawlOutcome` 에도 그것을 담을 칸이 없었다.

### 고친 방법 — 이미 있는 숫자를 쓴다

새 계산이 필요 없다. `run_courts()` 는 `all_items` 와 `rows` 를 둘 다 들고 있다.

```python
before_normalize = len(all_items)
rows = normalize_batch(all_items)
outcome.normalize_dropped = before_normalize - len(rows)
```

`normalize_batch()` 의 시그니처는 **건드리지 않았다** — 그 함수를 부르는 곳이
넷이고, 반환 계약을 바꾸면 그 넷을 다 따라가야 한다. 정보는 호출부에 이미 있었다.

### 치명적으로 만들지 않았다 (일부러)

`failure_reason()` 이 아니라 새 `warnings()` 로 낸다. 이유는 그 함수의 기존 판단과
같다 — *"임계값을 임의로 정하면 그 자체가 새 정책이 되고, 멀쩡한 실행이 매일 실패로
보고되면 경보가 무시당해 결국 같은 곳으로 돌아간다."* 대신 **숫자를 사실대로 내놓는다.**

`warnings()` 를 만들면서 법원 부분 실패 경고도 그쪽으로 옮겼다. 예전에는
`mvp_scraper` 안에 인라인으로 적혀 있어서, **같은 성격의 새 경고가 생겼을 때 붙일
자리가 없었다.** 이제 "치명적이지는 않지만 눈에 띄어야 하는 것"의 목록이 한 곳이다.

### 회귀 — 기형 행을 실제로 흘린다

문자열 검사가 아니다. `address=None` 인 진짜 `AuctionItem` 을 `run_courts()` 에
흘려 (1) 나머지 2건이 살아남고 (2) 탈락 1건이 `CrawlOutcome` 에 남고
(3) 경고가 **로그로 실제로 나가고** (4) 종료코드는 0인지를 본다.

**대조군을 함께 둔다** — 기형 행이 없으면 탈락 0건이고 경고도 없다.
이게 없으면 위 검사들은 "항상 경고한다"는 고장난 구현도 통과시킨다.

변이 3종(탈락을 안 셈 / `warnings()` 가 침묵 / 로그를 안 남김) **전부 검출**.

--------

#262

**제품 모듈 이름을 가리는 3주 묵은 사본이 `logs/` 에 세 개** 있다

상태

**측정·감시만 했다 (2026-08-27). 파일 삭제는 승인 영역이라 지우지 않았다.
`test_schema_hygiene.py` 에 전용 검사를 두어 늘어나면 붉어지게 했다.**

```
logs/mvp_scraper.py        130줄   (제품은 321줄)   2026-08-04
logs/doc_worker.py          ...
logs/refresh_priority.py     30줄
```

### 왜 위험한가

```
[1] 이 저장소의 진단 스크립트 다수가 `sys.path.insert(0, os.getcwd())` 를 쓴다
    (check_*.py 계열 전수 확인). `logs/` 에서 그런 스크립트를 돌리면
    **3주 전 mvp_scraper 를 import 한다.** 그 판본에는 이 세션이 고친 것이 하나도 없다.
[2] 더 흔한 피해는 사람이다 — 장애를 쫓다 `logs/mvp_scraper.py` 를 열고
    "제품이 이렇게 돼 있네" 라고 읽는다. 그 파일은 제품이 아니다.
```

`-DESKTOP-*` 충돌 사본(#253)과 **같은 부류**다: 제품 파일의 옛 판본이 제품 이름으로
남아 있다. 그래서 처리도 같게 한다 — 지우지 않고 **목록을 찍고 상한을 둔다.**

산출물 폴더(`logs/`, `downloads/`, `documents/`, `documents_quarantine/`,
`registry_documents/`, `public/`)에 저장소 루트의 추적 `.py` 와 같은 이름이 있으면 잡는다.

--------

#263

**체크포인트 기본 경로가 cwd 기준이었다 — 다른 폴더에서 크롤러를 띄우면 재개가
조용히 무력화된다.** 정적 감사가 못 잡는 자리(함수 기본 인자값)였다

상태

**해결 (2026-08-27). 제품 3곳 수정 + cwd 감사에 갈래 둘 추가(C: 기본 인자값,
D: 경로 키워드 인자). 런타임 회귀 신설, 변이 검출 확인.**

### 무엇이 문제였나

```python
class CheckpointManager:
    def __init__(self, path: str = "logs/checkpoint.json"):   # <- cwd 기준
```

`crawler/court_crawler.py:178` 이 이 기본값을 그대로 쓴다. 저장소가 아닌 곳에서
크롤러를 띄우면:

```
그 폴더에 logs/checkpoint.json 이 새로 생긴다
저장소의 진짜 체크포인트를 **못 찾는다** -> resume_from=None -> **처음부터 다시 긁는다**
진행 상황은 엉뚱한 폴더에 쌓인다        -> 다음 실행도 못 찾는다
```

즉 **재개가 조용히 무력화된다.** 오류도 경고도 없다 — 어제 다 한 법원을 오늘 처음부터
다시 돈다. 상세페이지 이동 실측 중앙값이 10.9초/건이라 그 손실이 그대로 시간이다.

실측(2026-08-27, cwd 만 바꿔 `CheckpointManager()` 를 만들어 저장):

```
cwd = 저장소 루트  -> 저장소 logs/checkpoint.json 에 쓴다
cwd = 다른 폴더    -> **그 폴더에** logs/checkpoint.json 이 새로 생긴다 (실제로 생겼다)
```

`.bat` 3개는 `cd /d %~dp0` 로 보호되지만, 수동 실행과 서비스 등록은 아니다 —
Sprint 246 이 같은 문장으로 적어 둔 그 조건이다.

### ★ Sprint 245/246/252 가 네 곳을 고쳤는데 여기만 남아 있었다

```
api/auth.py            load_dotenv        Sprint 245
storage/database.py    DB_PATH            Sprint 246
doc_worker.py          LOCK_PATH          Sprint 246
mvp_scraper.py         CSV 백업            Sprint 252 / #250
storage/checkpoint.py  체크포인트          <- 여기 (이번)
```

`mvp_scraper.py` 의 주석은 "이 계열을 네 군데 고쳤다" 고 **이름까지 나열**하고 있었다.
목록이 완전하다고 믿을 근거가 그 주석뿐이었고, 실제로는 완전하지 않았다.

### 왜 정적 감사가 못 잡았나 — 그리고 고치자 두 개가 더 나왔다

`test_schema_hygiene.py` 의 cwd 감사는 두 갈래만 봤다:

```
(A) 모듈 최상위 상수 할당    DB_PATH = "auction.db"
(B) 경로 호출의 문자열 리터럴  open("logs/x.jsonl")
```

체크포인트는 **함수 기본 인자값**이라 둘 다 비껴갔다. 갈래를 둘 추가했다:

```
(C) 함수 기본 인자값        def __init__(self, path="logs/checkpoint.json")
(D) 경로임을 이름으로 밝힌 키워드 인자   Engine(log_path="logs/revalidation.jsonl")
```

**추가하자마자 두 개가 더 나왔다** — 사람이 눈으로 찾은 것이 아니다:

```
validator/validation_engine.py:80   기본인자:__init__ -> 'logs/validation.jsonl'
revalidate.py:37                    인자:log_path     -> 'logs/revalidation.jsonl'
```

`validation_engine` 쪽은 운영 경로가 무사했다(`mvp_scraper` 가 `_HERE` 기준 경로를
넘긴다). 그래도 고쳤다 — **기본값에 기대는 호출부가 하나라도 생기면 그때 조용히
어긋나고**, 실제로 `revalidate.py` 가 그런 호출부였다.

### 오탐을 늘리지 않았다

(D) 를 넓히다 `dest` 를 넣었더니 argparse 의 `add_argument(..., dest="pattern")` 을
오탐했다(`run_python_tests.py:281`). **`dest` 는 다시 뺐다** — 이름이 경로를 확실히
가리키는 것만 남긴다. 목록을 넓히려다 오탐을 늘리면 이 검사 전체가 무시당한다.
자기 검증에 "경로 키워드에 변수를 넘기는 정상 호출은 안 잡는다" 를 함께 고정했다.

### 정적 검사만 믿지 않는다 — 다른 cwd 에서 실제로 만든다

`test_checkpoint_atomicity.py::test_default_path_does_not_follow_cwd()` 는 별도
프로세스를 **다른 cwd 로** 띄워 `CheckpointManager()` 를 만들고,

```
전제: 정말 다른 cwd 에서 돌았다
★ 기본 경로가 저장소 안을 가리킨다 (cwd 가 아니라)
★ 실행 폴더에 logs/ 가 생기지 않는다      <- 경로만 맞고 부수효과가 남으면 반쪽이다
명시 경로는 그대로 쓰인다                  <- 기존 계약 불변
```

를 본다. 기본값을 옛 문자열로 되돌리는 변이를 **런타임 검사가 잡는다**(정적 감사는
그 변이 모양(`path or "logs/..."`)까지는 못 잡는다 — 그래서 둘 다 필요하다).

--------

#264

**커버리지 산출물 `.cov_*` 가 `.gitignore` 에 없어서 실제로 커밋됐다.** 그리고 지우지
못했을 때 그 사실이 아무 데도 남지 않았다

상태

**해결 (2026-08-27). `.gitignore` 에 `.cov_*` 추가 + 정리 실패를 경고로 드러냄.**

### 어떻게 드러났나 — 내가 만든 쓰레기가 남았다

`#252`/`#258` 로 `audit_test_reality.py` 가 **비로소 실제로 돌기 시작**하자,
저장소 루트에 `.cov_test_doc_path_safety_py` 가 남았다. `git status` 가
`?? .cov_test_doc_path_safety_py` 로 보여 주었다.

### 두 개의 구멍이 겹쳐 있었다

```
[1] .gitignore 가 못 잡는다
    있는 규칙:  .coverage / .coverage.*      <- 접두어가 `.coverage`
    실제 이름:  .cov_test_x_py               <- 접두어가 `.cov_`
    -> 한 글자 차이로 통째로 비껴간다.

[2] 정리 실패가 조용하다
    finally:
        try: os.remove(data_file + suffix)
        except OSError: pass          # <- Windows 파일 잠금이면 그대로 남는다
```

[1] 은 **이미 사고가 났다** — `.cov_test_audit_selftests-DESKTOP-DVRJEGP_py` 가
git 에 **추적된 채로 커밋돼 있고**, `test_schema_hygiene.py` 의 "추적된 SQLite DB"
검사가 그것을 붉게 잡고 있었다(#253 이 분리해 둔 그 항목이다).

즉 #253 에서 "충돌 사본의 부산물"로 분류했던 그 파일의 **진짜 원인은 이 누락**이었다.
규칙이 처음부터 있었으면 애초에 커밋될 수 없었다.

### 고친 것

```
.gitignore                 `.cov_*` 추가
audit_test_reality.py      3회 재시도 후에도 못 지우면 [WARN] 으로 남긴다
```

무시 규칙만으로는 **작업 트리에 쓰레기가 쌓이는 것**을 막지 못한다. 커밋을 막는 것과
남지 않게 하는 것은 다른 문제라 둘 다 한다. 그리고 그래도 남으면 **사람이 알아야 한다** —
조용히 삼키는 `except: pass` 가 애초에 이 상태를 만들었다.

### 남은 것

`.cov_test_audit_selftests-DESKTOP-DVRJEGP_py` 는 **추적을 풀지 않았다.**
`git rm --cached` 는 커밋을 전제로 하고, 그 파일은 OneDrive 충돌 사본 정리(#253)와
함께 사람이 판단할 일이다. 새 규칙 덕에 **더 늘어나지는 않는다.**

--------

#265

**병합 사건번호(`"A / B"`)가 찾는 쪽에 오면 자기 자신과도 일치하지 않았다.**
큐 331행이 매일 밤 반드시 매칭에 실패하고 있었다

상태

**해결 (2026-08-28). `crawler/resume.py:case_no_matches_list_entry()` 를 양쪽 분해 +
교집합으로. 회귀 `test_crawl_resume.py` 0-b (검사 11개).**

### 어떻게 찾았나 — 운영 로그를 실제로 집계했다

2026-08-28 워커 로그를 cp949 로 디코드해 사유별로 집계했더니:

```
106  appraisal 내부 PDF iframe을 찾지 못함            <- #267
 67  사건 매칭 실패: "2023타경300780 / 2023타경302427" 꼴   <- 이 항목
     (2023타경300780/302427 27건, 2024타경101286/2025타경1147 24건,
      2024타경41977/2025타경1617 16건)
```

전부 **" / " 가 들어간 병합 사건번호**였다. 그날 `failed` 가 95 -> 205 로 늘었다.

### 원인 — 한쪽만 쪼개고 있었다

```python
return target_case_no in [c.strip() for c in list_entry_case_no.split(" / ")]
```

Sprint 121 판본은 **목록 쪽만** 쪼갠다. 그래서 찾는 쪽이 병합이면:

```
m("2023타경300780",                  "2023타경300780 / 2023타경302427")  -> True
m("2023타경300780 / 2023타경302427", "2023타경300780 / 2023타경302427")  -> **False**  <- 같은 문자열인데
m("2023타경300780 / 2023타경302427", "2023타경300780")                   -> **False**
m("2023타경302427 / 2023타경300780", "2023타경300780 / 2023타경302427")  -> **False**  <- 순서만 달라도
```

그리고 병합 사건번호는 **저장된다**(`base_crawler` 의 `" / ".join(case_nos)` 가
`auction` / `document_queue` 로 그대로 흘러간다). 즉 찾는 쪽이 병합인 것은 예외가
아니라 일상이다. 실측(2026-08-28 운영 DB):

```
document_queue 병합 사건번호 행   1,507
  그중 pending 222 / failed 105 / refresh 4 = **331행이 현재 진행형**
auction 병합 사건번호 행            602
```

### ★ 사후 정밀 집계 — 매칭 실패는 **전부** 병합 사건번호였다

로그를 사건번호까지 정규화해 다시 세니 훨씬 또렷했다(2026-08-28 doc_run.log).

```
사건 매칭 실패 총 171회 (서로 다른 물건 17개)
  병합 사건번호(" / " 포함)  171회
  단일 사건번호                0회      <- **하나도 없다**

그날 WARNING/ERROR 828줄 중 **21%** 가 이 한 부류다 (단일 실패 사유 1위)
```

즉 "매칭 실패" 라는 증상은 **전부** 이 결함이었다. 다른 원인이 섞여 있지 않다.
그리고 그 뒤를 잇는 `사건 상세 진입 실패` 179건(appraisal 49 / spec 45 / status 43 /
image 42)도 같은 17개 물건이 만든 **하류 증상**이다.

17개 물건이 각각 4종 x 재시도 3회를 매일 밤 태우고 있었다.

그 331행은 **영원히 수집되지 않는다.** 실패 한 번이 상세페이지 이동 1회
(실측 중앙값 10.9초)를 태우고 재시도 예산 3회를 깎는다.

### 왜 이렇게 되나 — 사건번호 묶음은 시간에 따라 변한다

`detect_merged_case_duplicates_dryrun.py` 를 돌려 확인했다.

```
평택지원 / 같은 주소·물건번호
  id=442    case_no=2023타경4767                     기일 2026-07-13
  id=1421   case_no=2023타경4767 / 2026타경51196      기일 2026-08-24   <- 나중에 병합됐다

원주지원
  id=1483   ... 14개 사건번호 묶음  기일 2026-07-20
  id=12054  ... 13개 사건번호 묶음  기일 2026-08-24   <- 하나가 **빠졌다**
```

묶음은 **늘기도 하고 줄기도 한다.** 그래서 문자열 동일성으로는 같은 물건을 따라갈 수 없다.

### 고친 방법 — 양쪽을 쪼개고 **구성요소가 겹치면** 같은 물건

사건번호는 법원 안에서 유일하고 병합 표기는 같은 경매를 가리키므로, 어느 한
구성요소라도 공유하면 같은 물건이다.

★ **Sprint 121 이 막은 것은 그대로 막힌다.** 비교는 여전히 구성요소끼리의 정확
  일치라 `"2024타경1009"` 는 `"2024타경100920"` 과 겹치지 않는다. 회귀에 그 검사를
  **양방향으로** 함께 두어, 이번 완화가 그 결함을 되살리지 않았음을 고정했다.

★ 빈 문자열은 이제 **아무것도 일치시키지 않는다**(예전엔 `m("","")` 가 True).
  사건번호가 비었다는 것은 "모른다"이지 "아무거나 맞다"가 아니다 — 그 상태로 첫
  항목에 진입하면 **엉뚱한 물건의 자산**을 저장할 수 있고, 그것이
  `go_to_case_detail()` 의 `require_exact_item` 이 막으려는 바로 그 사고다.

### 다른 한 벌은 이미 옳았다

`wait_for_detail()` 은 `re.findall(r"\d{4}타경\d+")` 로 토큰을 뽑아 **집합 교집합**을
쓴다 — 병합을 이미 올바르게 다룬다. 즉 "어느 행을 누를까"(틀렸던 쪽)와
"제대로 들어왔나"(옳았던 쪽)가 **서로 다른 판정을 하고 있었다.** 이제 둘이 일치한다.

--------

#266

**CSV 격리 검사가 "존재하나"와 "내가 만들었나"를 구별하지 못해, 크롤이 실제로 돈
날이면 반드시 붉어졌다**

상태

**해결 (2026-08-28). 존재 여부 대신 앞뒤 상태(존재/크기/mtime) 변화를 본다.**

```python
today_csv = os.path.join(root, "auction_%s.csv" % 오늘)
check_true("★ 저장소 루트에 QA CSV 백업이 생기지 않았다", not os.path.exists(today_csv))
```

그 파일은 매일 04:53 크롤이 정상적으로 만드는 **운영 산출물**이다. 즉 이 단언은
*"크롤이 돌지 않은 날에만 통과한다."*

### 지금까지 안 드러난 이유가 고약하다

**이 검사 자신이 그 CSV 를 지우고 있었다**(#250). 그 결함을 고치자마자 이 단언이
드러났다 — 어제는 파일이 없어서(내가 지워서) 통과했고, 오늘 04:53 크롤이
`auction_20260828.csv`(84,230바이트, 실제 컬럼)를 만들자 붉어졌다.

**결함 하나가 다른 결함을 가려 주고 있었던 것**이고, #250 과 정확히 같은 부류다 —
"내가 만들었나"와 "존재하나"를 구별하지 못한다.

이제 검사 시작 전 `(존재, 크기, mtime)` 을 찍어 두고 끝에 비교한다. 실측으로
그 CSV 가 검사 전후 바이트·mtime 모두 무변경임을 확인했다.

--------

#267

**감정평가서 오버레이에서 "내부 PDF iframe을 찾지 못함" 106건 — 단일 실패 사유 1위.
15초 예산을 두고도 사실상 기다리지 않고 있었다**

상태

**해결 (2026-08-28). 대기 조건을 필요한 것으로 교체. 회귀
`test_doc_pdf_iframe.py` 신설(검사 20개, 가짜 드라이버로 경합 재현). 변이 검출.**

### 원인 — **기다리는 대상이 틀렸다**

```python
inner_iframes = WebDriverWait(driver, OVERLAY_TIMEOUT).until(
    lambda d: d.find_elements(By.TAG_NAME, "iframe") or False)
for f in inner_iframes:                 # <- src 를 **딱 한 번** 본다
    if (f.get_attribute("src") or "").lower().endswith(".pdf"): ...
```

기다린 것은 *"iframe 이 하나라도 생겼는가"* 인데 필요한 것은
*"src 가 .pdf 인 iframe 이 생겼는가"* 다. 뷰어는 **iframe 을 먼저 붙이고 src 를
나중에 채운다.** 껍데기가 붙는 순간 대기가 풀리고, 그 찰나에 한 번 훑어 못 찾으면
그대로 실패한다. 15초를 배정해 두고 **0초를 쓴다.**

실패 한 건은 재시도 3회를 부르고, 재시도마다 상세페이지 이동(중앙값 10.9초)과
오버레이 대기를 다시 태운다.

### 고친 방법 — 조건 자체를 바꾼다 (새 예산을 만들지 않는다)

```python
pdf_src = WebDriverWait(driver, OVERLAY_TIMEOUT).until(_pdf_iframe_src)
```

`_pdf_iframe_src()` 는 "지금 프레임에서 src 가 .pdf 인 iframe 의 src, 없으면 None".
`until()` 은 None 을 받으면 계속 폴링하므로 **필요한 것이 생길 때까지** 기다린다.

★ **판정 규칙은 글자 그대로 같다**(`src.lower().endswith(".pdf")`). 바꾼 것은
  *언제 보는가*이지 *무엇을 보는가*가 아니다.
★ **타임아웃을 새로 만들지 않았다** — 이미 있던 `OVERLAY_TIMEOUT`(15초) 그대로다.
  회귀가 그 값과 "옛 조건이 되돌아오지 않았다"를 함께 고정한다.

### 브라우저 없이 경합을 재현했다

`WebDriverWait` 은 조건 함수를 반복 호출할 뿐이라, **호출 횟수에 따라 src 가 나중에
채워지는 가짜 드라이버**로 실제 순서를 그대로 흉내 낼 수 있다.

```
옛 방식(_old_way)  -> None          <- 놓친다
지금 방식(_new_way) -> ".../report.pdf"   <- 잡는다
```

같은 가짜 드라이버에서 **옛 방식이 실패하고 새 방식이 성공**하는 것을 나란히 고정했다.
대조군도 뒀다 — 진짜로 없을 때는 예산 안에 포기한다(무한 대기가 아니다).
`crawler/resume.py` / `crawler/doc_paths.py` 가 selenium 의존을 떼어 낸 것과 같은 방법이다.

### 남긴 것 (실 사이트 확인이 필요해 건드리지 않았다)

`.pdf` 뒤에 쿼리스트링이 붙는 src(`....pdf?token=…`)는 지금 규칙으로는 걸리지 않는다.
106건 중 그런 경우가 있는지는 **실제 페이지를 열어 봐야** 안다(외부 접근 영역).
추측으로 규칙을 넓히면 엉뚱한 iframe 을 PDF 로 볼 수 있어 그대로 두었다.

--------

#268

**`upsert_batch()` 의 트랜잭션 모양과 장애 거동, 큐 claim 의 다중 프로세스 배타성이
아무 데도 고정돼 있지 않았다**

상태

**해결 (2026-08-28). 검사 두 벌 신설 —
`test_db_write_failure_modes.py`(6절 / 단언 30) ·
`test_queue_multiprocess_claim.py`(3절 / 단언 14). 둘 다 변이로 검출 확인.**

### 왜 필요했나 — 정상 경로만 고정돼 있었다

`#256` 이 계수 방식을 바꿨다. 이제 신규/갱신/무변화를 행마다 묻지 않고
**배치 앞뒤로 두 번만 세서 유도**한다. `test_upsert_change_detection.py` 가
정상 경로를 촘촘히 고정하지만, 그 유도는 **배치가 끝까지 갔다는 전제** 위에 있다.
중간에 행이 실패하면? 커밋이 실패하면? DB 가 잠겨 있으면? 프로세스가 죽으면?
**아무것도 고정돼 있지 않았다.** 이 값들은 `CrawlOutcome.persisted` 를 거쳐 크롤의
**종료 코드**가 되므로, 틀린 숫자는 곧 `run_daily.bat` 의 잘못된 판정이다.

### 먼저 쟀다 — 트랜잭션 모양

```
신규 1,000    BEGIN=1 COMMIT=1 ROLLBACK=0  문장/행=1.00
변화없음 1,000 BEGIN=1 COMMIT=1 ROLLBACK=0  문장/행=1.00
변경 1,000    BEGIN=1 COMMIT=1 ROLLBACK=0  문장/행=1.00
```

**배치 하나 = 트랜잭션 하나**, 행당 정확히 한 문장. `#256` 의 이득을 회귀로 못 박았다
(예전엔 행당 2문장이었다).

### 고정한 장애 거동 여섯

```
1 트랜잭션 모양   BEGIN 1 / COMMIT 1 / ROLLBACK 0 / 행당 문장 1 / 배치당 SELECT 2
2 행 하나 실패    나머지는 저장되고 계수가 맞고 **실패한 행은 DB 에 없다**
                 (성공으로 위장하지 않는다) / 트랜잭션은 여전히 하나
3 커밋 실패      예외가 올라가고 그 배치는 **한 행도 남지 않는다**
4 DB 잠김        조용히 성공하지 않는다 (실측: OperationalError 로 올라온다)
5 프로세스 사망   커밋 전 500행이 **하나도 남지 않는다** + 그 뒤 DB 가 정상이다
6 실패 후 재실행  앞선 실패가 다음 배치의 계수를 오염시키지 않는다 + 멱등
```

3/5 는 실제로 주입해서 본다 — 커밋을 던지는 `Connection` 상속(factory), 커밋 직전에
`os._exit(9)` 하는 자식 프로세스. 문자열 검사가 아니다.

### 큐 claim — **스레드가 아니라 진짜 프로세스**로

`test_document_queue.py` §8 이 동시 claim 을 보지만 **스레드 8개**다. 운영에서 겹치는
것은 프로세스다(수동 실행 + 예약 실행, 워커 + 크롤, cwd 가 달라 락이 갈라진 경우 —
`doc_worker.py` 주석이 그 실측을 갖고 있다). 그때 마지막 방어선이 claim 의 원자적 전이다.

자식 프로세스 6개가 같은 순간에 달려들게 해서(출발 시각을 맞춘다) 확인했다:

```
큐 60행 / 자식 6개   -> 두 번 집힌 행 0 / in_progress 60 / 큐 행 수 불변
큐 40행 / 자식 5개   -> **전부 정확히 한 번씩** 집힌다 (누락 0)
                       배타성만 보면 "아무도 못 집는다"는 고장도 통과하므로 짝으로 둔다
claim 토큰            집힌 행은 전부 last_attempt_at 을 갖는다 (BUGS #181/#202 의 전제)
```

### 변이로 확인했다 (공허하지 않다)

claim 의 `WHERE id=? AND status=?` 에서 상태 가드를 빼자 **실제로 중복 claim 이 났고**
(같은 행이 두 번: 4~5건) 검사가 잡았다. `upsert_batch` 쪽도 각 장애 주입이 그대로 붉어진다.

--------

#269

**로그 로테이션이 한 군데도 없다.** 그리고 그 무한 증가가 테스트 스위트 비용에 직접 붙는다

상태

**측정·문서화만 했다 (2026-08-28). 로테이션 도입은 옛 로그를 지우는 일이라 승인 영역.**

### 실측

```
로테이션 설정 참조 0건 (RotatingFileHandler / maxBytes / backupCount 전수 검색)

logs/scraper.log        4.05 MB   약 1,000줄/일 (~85KB/일)
logs/daily_run.log      3.01 MB   약 1,000줄/일
logs/doc_run.log        1.31 MB   약 2,400~3,300줄/일   <- 워커가 매일 돌기 시작해 가속
logs/doc_collect.log    0.15 MB
logs/migrate_execute.log 0.04 MB
```

### 왜 그냥 디스크 문제가 아닌가

`run_python_tests.py` 는 **테스트 파일마다 전후로** 운영 산출물(DB + 로그 5개)의
md5 를 뜬다(#186/#192 가 만든 오염 감시). 그 비용이 로그를 따라 자란다.

```
감시 대상 합계  15.59 MB
지문 1회        19.6 ms
스위트 1회      72파일 x 2 = **2.8초 / 2.19 GB 해싱**   (스위트 약 116초의 2~3%)
1년 뒤 추정     약 40MB -> 스위트당 약 7초 / 5.6 GB
```

그 감시의 원래 주석은 *"5MB md5 가 파일당 ~10ms(전체 ~0.6s), 무시할 수 있다"* 였다 —
**감시 대상이 DB 하나였을 때의 숫자**이고 지금은 로그 5개가 더 붙어 있다.
주석을 실측으로 갈아 끼우고 추세를 함께 적었다.

### 지금은 고치지 않는다

감시를 약화(크기+mtime 선비교)하면 2.8초를 아끼지만, 그 감시는 **테스트가 운영 로그를
오염시킨 실제 사고**(#192: doc_collect.log 4,136줄 중 1,651줄이 QA 산출물) 때문에
생겼다. 2~3% 를 위해 탐지력을 깎을 이유가 없다.

로테이션은 **옛 로그를 지우는 동작**이라 승인 영역이다. 다음 스프린트 후보:
`RotatingFileHandler(maxBytes=10MB, backupCount=5)` 또는 날짜별 분할.

---

## #254 공개 엔드포인트가 임차인 **실명**을 내보낸다 (2026-08-28, 미해결 — 승인 대기)

`GET /api/v1/item/{item_id}` 는 **인증 없이** 읽을 수 있다
(`test_api_regression.PUBLIC_ENDPOINTS` 에 그렇게 등록돼 있다). 그 응답에
`tenants[]` 가 통째로 실려 있다.

### 실측 (익명 요청, 헤더 없음)

```
GET /api/v1/item/53          -> 200
tenants[0].tenant_name          '김미화'
tenants[0].move_in_date         '2017-09-20'
```

```
auction.db  tenant_rights 519행
  tenant_name     240행이 실명
  occupied_area   475행이 전체 주소
  deposit 125 / monthly_rent 33 / move_in_date 211 / fixed_date 81
```

즉 **이름 + 주소 + 보증금/월세 + 전입일**이 한 묶음으로, 로그인 없이, 물건 id 만
바꾸며 순회 수집할 수 있다.

### 감사 문서 두 곳이 반대로 적고 있었다

```
docs/CURRENT_STATE.md §9229   "공개 8개에 개인정보·관리 기능 없음"
docs/CHANGELOG.md     §4827   "공개 8개에 개인정보·관리 기능 없음"
```

두 줄 다 이번에 정정했다. 검사가 없었기 때문에 **틀린 채로 남아 있었고**, 그 문장을
읽은 다음 감사는 이 표면을 다시 보지 않았다.

### 구조적 원인 — `dict(row)`

본체(`auction_item`)는 필드를 하나씩 적어 내보내는데, 곁딸린 세 테이블만 행 전체를
실었다.

```
"case":           dict(case)                  auction_case    9컬럼 (프런트는 3개만 쓴다)
"tenants":        [dict(t) for t in tenants]  tenant_rights  12컬럼 (프런트 9개)
"rights_summary": dict(rights)                rights_summary 21컬럼 (프런트 7개)
```

그래서 마이그레이션이 그 테이블에 컬럼을 하나 추가하면 **그날로 공개 API 에 실린다.**
아무도 그렇게 결정하지 않았고, 알려 줄 검사도 없었다.

### 이번에 한 것 (응답은 한 글자도 바뀌지 않는다)

`api/v1/item.py` 에 `_TENANT_FIELDS` / `_CASE_FIELDS` / `_RIGHTS_FIELDS` 를 두고
`_project()` 로 뽑는다. **목록은 지금 나가고 있는 컬럼 그대로**다 — 실측으로 집합·순서
동일 확인. 좁히지 않은 이유는 그것이 API 계약 축소라 소비자를 먼저 옮겨야 해서다.
여기서 막는 것은 **앞으로 늘어나는 것**이다.

`test_public_endpoint_exposure.py`(신설)가 셋을 고정한다.

```
1  화이트리스트 == 실제 테이블 컬럼      새 컬럼이 생기면 이름을 대며 실패한다
2  dict(row) 덤프로 되돌아가지 않는다    1번이 무력해지는 것을 막는다
3  개인정보가 공개로 나간다는 사실       "없음" 주장이 조용히 돌아오지 못하게 한다
```

변이 3/3 검출, 생존 0.

### 남은 결정 — 마스킹 (승인 영역)

임차인 성명을 `김○○` 로 가릴 것인가는 **제품·법무 판단**이라 여기서 정하지 않았다.
양쪽 다 근거가 있다.

```
가린다   개인정보보호법. 경쟁사(지지옥션/탱크옥션)도 성명을 가린다
안 가린다 임차인 성명은 **대항력 판단의 근거**다. 가리면 권리분석이 약해진다
         원천(현황조사서)은 법원이 공개하는 문서다
```

절충안(로그인 사용자에게만 실명, 익명에는 마스킹)이 가장 그럴듯하지만, 이는
공개 엔드포인트의 인가 정책 변경이라 승인 없이 하지 않는다.

**우선순위 P0**(보안·개인정보). 결정이 나면 위 검사 3번이 실패하며 문서와 함께
정리하라고 알려 준다.
