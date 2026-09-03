// 공용 표시 포맷 함수. 여러 화면(검색결과/즐겨찾기/최근조회)에 동일하게 복사돼 있던
// formatPrice()를 여기로 모았다 — 동작은 기존 그대로, 정의 위치만 옮김(회귀 없음).

// ---------------------------------------------------------------------------
// 천 단위 구분 — **로케일을 고정한다** (2026-08-31)
//
// 왜 필요한가. `Number.prototype.toLocaleString()`을 인자 없이 부르면 **보는 사람의
// 브라우저 로케일**이 구분자를 정한다. 이 저장소는 그것을 화면 10곳에서 그렇게 쓰고
// 있었고, 그중 5곳이 **실제로 청구되는 금액**이었다.
//
//     ko-KR / en-US   (12900).toLocaleString() -> "12,900"     의도한 값
//     de-DE           (12900).toLocaleString() -> "12.900"     ★ 한국식으로 읽으면 12.9
//     실측 2026-08-31: node -e "(12900).toLocaleString('de-DE')" => 12.900
//
// 즉 같은 결제 화면이 브라우저 설정에 따라 **다른 금액으로 읽힌다.** 오류도 로그도 없다.
// `PLAN_CATALOG`의 날짜를 문자열이 아니라 날짜 객체로 판정하게 만든 것과 같은 부류의
// 결함이다(`api/v1/payments.py` 주석 — "둘 다 오류도 로그도 없이 금액만 달라진다").
//
// 이 저장소는 **날짜 표기에서는 이미 로케일을 고정하고 있다** —
// `favorites/page.tsx` · `properties/recent/page.tsx` · `mypage/page.tsx` 세 곳 모두
// `toLocaleDateString('ko-KR')`이다. 숫자만 고정되지 않아 같은 관심사에 규칙이 둘이었다.
// 여기서 새 정책을 만드는 것이 아니라 **이미 있는 규칙(ko-KR 고정)을 숫자에도 맞춘다.**
// 제품은 한국어 전용이다(`src/app/layout.tsx`의 `lang="ko"`, 화면 문구 전부 한국어).
//
// ko-KR / en-US 사용자가 보는 문자열은 **한 글자도 바뀌지 않는다**(둘 다 쉼표 3자리).
export const DISPLAY_LOCALE = 'ko-KR'

/** 천 단위 구분자를 넣은 숫자. 금액이면 `formatWon()`을 쓴다(원 단위가 함께 붙는다). */
export function formatNumber(value: number) {
  return value.toLocaleString(DISPLAY_LOCALE)
}

// ★ 2026-09-03 — 인자 타입을 **이미 하고 있던 런타임 동작**에 맞춘다.
//   아래 `if (!price)` 는 null/undefined/NaN/0 을 전부 '-' 로 돌려주고 있었는데
//   시그니처만 `number` 라, 서버가 null 을 줄 수 있는 금액 필드(`auction_item` 의
//   appraisal_price/minimum_bid_price 는 NOT NULL 이 아니다)를 넘기려면 호출부가
//   억지로 좁혀야 했다. 같은 파일의 `formatBidRate`/`formatDday` 는 이미 이렇게
//   넓혀져 있다 — 그 선례에 맞춘다. **동작은 한 글자도 바뀌지 않는다.**
export function formatPrice(price: number | null | undefined) {
  if (!price) return '-'
  if (price >= 100000000) return (price / 100000000).toFixed(1) + '억'
  if (price >= 10000) return Math.round(price / 10000) + '만'
  return String(price)
}

// "억" 고정 표기. `formatPrice()`와 달리 0을 '-'로 바꾸지 않고 1억 미만도 억 단위로 쓴다
// (500만 -> "0.1억", 0 -> "0.0억").
//
// 두 표기가 공존하는 것은 **의도된 상태가 아니라 미결정 상태**다. `properties/page.tsx`(레거시
// 목록)와 `properties/[id]/page.tsx`(상세)에 이 구현이 **글자 단위로 똑같이 복사**돼 있었다
// (2026-08-10 Sprint 48 확인). 어느 표기를 기준으로 통일할지는 화면에 보이는 숫자가 바뀌는
// UX 결정이라 임의로 정하지 않고, 우선 **중복만 제거**해 두 화면이 같은 함수를 쓰게 했다.
// 표기 기준이 정해지면 이 함수를 지우고 호출부를 formatPrice()로 옮기면 된다.
export function formatPriceEok(price: number) {
  return (price / 100000000).toFixed(1) + '억'
}

// 정확한 원 단위 표기 — **사용자에게 실제로 청구되는 금액**에 쓴다.
//
// 2026-08-11 Sprint 54: `properties/[id]/page.tsx`에만 지역 함수로 있던 것을 공용으로 옮겼다
// (마이페이지 결제 내역이 같은 표기를 필요로 하면서 중복이 될 상황이었다 — Sprint 18/48이
// formatPrice/formatPriceEok를 여기로 모은 것과 같은 이유).
//
// ★ 금액 종류에 따라 함수가 다른 것은 **의도된 구분**이다:
//   - `formatPrice()` : 감정가·최저입찰가 등 **물건 시세**. 억/만 축약이 이 도메인의 관례이고
//                       천원 단위 오차가 의미 없다
//   - `formatWon()`   : 구독료·환불액 등 **청구 금액**. 축약하면 안 된다 —
//                       `formatPrice(12900)`은 "1만"이 되어 실제 청구액과 2,900원(22%) 어긋난다.
//                       구독 카드가 이미 `price.toLocaleString() + '원'`으로 정확히 표시하고
//                       있어서, 내역만 축약하면 같은 결제가 화면마다 다른 금액으로 보인다.
//
// ★ 2026-08-31 — 위 주석이 말하는 "구독 카드가 이미 그렇게 표시하고 있어서"가 곧
//   **중복 구현**이었다. 상세 페이지의 구독/초과결제 카드 5곳이 `formatWon()`을 부르지 않고
//   `.toLocaleString() + '원'`을 손으로 다시 적고 있었다(Sprint 54가 지역 `formatWon`을
//   지웠을 때 이 다섯 자리는 함께 옮겨지지 않았다). 같은 책임의 표기가 두 곳에 있으면
//   반드시 갈라진다 — 실제로 로케일 고정이 한쪽에만 들어갈 뻔했다. 호출부를 이 함수로
//   모았고, `tests/source-contract.test.mjs`가 되살아나는 것을 막는다.
export function formatWon(amount: number) {
  return formatNumber(amount) + '원'
}


// ---------------------------------------------------------------------------
// 최저가율(= 입찰가율) — **한 자리 소수 퍼센트** (2026-08-31)
//
// 값은 `auction_item.bid_rate` 이고 **0~1 비율**로 저장된다
// (`migrate_execute.py:calc_bid_rate` = `minimum_bid_price / appraisal_price`,
//  `docs/backend.md` "최저가율"). 화면은 100 을 곱해 퍼센트로 쓴다.
//
// ## 왜 공용으로 옮겼나
//
// 같은 계산이 두 곳에 있었고 **둘의 규칙이 달랐다** (2026-08-31 실측).
//
//     src/app/search/ResultList.tsx   (r*100).toFixed(1) + '%'   + null/undefined 가드 -> '-'
//     properties/[id]/page.tsx:772    (r*100).toFixed(1) + '%'   가드 없음
//
// 가드가 없는 쪽은 값이 없을 때 `(null*100).toFixed(1)` = **"0.0%"** 를 찍는다.
// 없는 것을 0 으로 지어내는 것이고, 이 저장소가 반복해서 금지해 온 모양이다
// (`exportList.ts` 의 "값이 없음과 값이 0 은 다른 사실이다", `parseArea`/`formatDday` 가
//  모르면 null 을 돌려주는 것과 같은 규칙). 그래서 **가드가 있는 쪽으로** 모은다.
//
// 지금 DB 에는 `bid_rate` 가 NULL 인 행이 0건이고 컬럼 DEFAULT 도 0 이라
// **화면에 보이는 문자열은 바뀌지 않는다.** 막는 것은 앞으로 생길 "0.0%" 다.
//
// ★ 라벨은 화면마다 다르고 **그것은 의도된 상태다** — 문서가 각각 그렇게 정하고 있다:
//     검색 결과 카드   "최저가율"   (`search/00_SEARCH_MVP.md` §5.2 표시 항목)
//     물건 상세        "입찰가율"   (`docs/FRONTEND_MASTER_SPEC.md` §9.2 가격·일정)
//   한 낱말로 통일할지는 화면 문구 결정이라 여기서 정하지 않는다. 이 함수는 **숫자 표기만**
//   담당하고 라벨은 호출부가 붙인다.
export function formatBidRate(bidRate: number | null | undefined): string {
  if (bidRate === null || bidRate === undefined || Number.isNaN(bidRate)) return '-'
  return (bidRate * 100).toFixed(1) + '%'
}

// ---------------------------------------------------------------------------
// 물건 면적 — `auction_item.full_address` 끝 대괄호에서 읽는다
//
// 크롤러는 주소를 "...주소... [유형 구조 XX.XX㎡]" 형태로 저장한다. 면적 전용 컬럼은
// 없지만 **데이터는 여기 있다**(2026-08-21 Sprint 248 전수 실측: 1,876행 중 1,854행이
// 이 대괄호에 면적을 담고 있다).
//
// 원래 `src/app/search/ResultList.tsx` 안에 있었다. 여기로 옮긴 이유는 두 가지다:
//   1. `.tsx` 는 JSX 라 Node 의 타입 스트리핑으로 import 할 수 없어 **동작 테스트를
//      붙일 수 없었다.** 화면 모든 카드에 찍히는 값인데 계약이 고정돼 있지 않았다.
//   2. `format.ts` 는 이미 "공용 표시 포맷 함수"의 자리다(파일 첫 주석).
// 동작은 아래 ★ 한 곳을 빼면 그대로다.
// ---------------------------------------------------------------------------

// 1평 = 3.305785㎡(공식 환산값)
export const SQM_PER_PYEONG = 3.305785

export type ParsedArea = { label: string; sqm: number }

/**
 * 주소 끝 대괄호에서 면적을 읽는다. 면적 개념이 없는 물건(차량/선박 등)은 null.
 *
 * 다층 건물은 "1층 X㎡ 2층 Y㎡ ..."처럼 층별 면적이 나열되므로 **합산**한다.
 *
 * ★ 2026-08-21 Sprint 248 — 중첩 대괄호 버그 수정.
 *   예전 정규식은 `/\[([^\]]*)\]\s*$/` 였다. `[^\]]*` 가 안쪽 `]` 를 넘지 못해
 *   **대괄호가 중첩된 주소에서 통째로 실패**했다. 실측 4건이 그랬고, 넷 다 면적이
 *   멀쩡히 적혀 있는데 화면에 아무것도 안 나왔다:
 *
 *     [토지 전[현황:묵전(죽림)] 105㎡ ...]                    -> 105㎡
 *     [토지 전[(현황:전 및 묵전(임야)] 694㎡ ...]              -> 694㎡
 *     [토지 임야 6571㎡ ... [... 제외]]                       -> 6571㎡
 *     [건물 ... 97.58㎡ ... 46.4㎡ [현황: 멸실]]               -> 143.98㎡
 *
 *   탐욕적 `(.*)` 로 바꾸면 **바깥 대괄호 전체**를 잡는다. 전체 1,876행으로 대조해
 *   새로 파싱 4건 / 값이 달라진 행 0건 / 파싱을 잃은 행 0건을 확인했다.
 *
 * 알려진 한계(고치지 않았다 — 제품 판단 영역):
 *   - 단위가 '평'인 주소 8건은 여전히 null 이다. 7건은 단순하지만 1건(id=6495)은
 *     '192평6홉9작' 처럼 홉/작 하위 단위에 층 목록이 중복돼 있어, 일괄 환산하면
 *     **틀린 숫자를 보여줄 위험**이 있다. 아무것도 안 보여주는 편이 낫다.
 *   - 지분 물건은 대괄호의 면적이 **전체 면적**이다(예: "5178분의 4657"). 지분을
 *     반영해 표시할지는 표기 정책이라 여기서 정하지 않는다.
 */
export function parseArea(fullAddress: string | null): ParsedArea | null {
  if (!fullAddress) return null
  const bracketMatch = fullAddress.match(/\[(.*)\]\s*$/)
  if (!bracketMatch) return null
  const inside = bracketMatch[1]
  // ★ 2026-08-21 Sprint 249 — '대지권의 표시' 뒤는 **이 물건의 면적이 아니다.**
  //
  //   집합건물 등기에는 전유부분 면적 뒤에 대지권(그 건물이 깔고 앉은 **토지 전체**)이
  //   함께 적히는 형식이 있다. 그대로 다 더하면 아파트 한 채가 토지 전체를 가진 것처럼 된다.
  //
  //   실측(id=6442): '집합건물 ... 74.5482㎡ 대지권의 표시 토지의 표시 : ... 대 500㎡
  //   ... 대지권 비율 : 500분의 21.7849'
  //       고치기 전  건물 574.55㎡ (173.80평)   <- 74.5482 + 500 을 더한 값. 7.7배 부풀었다
  //       고친 뒤    건물  74.55㎡ ( 22.55평)   <- 전유부분 면적
  //
  //   층별 합산(아래 while 루프)은 그대로 둔다 - 다층 건물의 '1층 X㎡ 2층 Y㎡' 는
  //   전부 이 물건의 면적이라 더하는 것이 맞다. 대지권만 성격이 다르다.
  //
  //   전체 1,876행 대조: 값이 바뀌는 행 1개(위 id=6442), 나머지 1,875행 동일,
  //   파싱을 잃은 행 0개.
  const landRightsAt = inside.search(/대지권|토지의\s*표시|대지의\s*표시/)
  const areaScope = landRightsAt >= 0 ? inside.slice(0, landRightsAt) : inside
  // ★ 2026-08-26 — 천단위 쉼표를 받는다 (`docs/BUGS.md` #240).
  //
  //   예전 정규식은 `[0-9]+` 라 쉼표에서 끊겼고, **쉼표 뒤부터** 매치됐다:
  //
  //       "1층 3,005.35㎡"   ->    5.35㎡   (562배 축소)
  //       "1층 1,000㎡"      ->       0㎡   ★ 면적이 0 으로 보인다
  //       "1층 12,345.67㎡"  ->  345.67㎡
  //
  //   실데이터 id=443(평택 공장)이 그랬다 — 지1층 3,005.35 + 1층 6,110.75 +
  //   2층 5,322.75 = 14,438.85㎡ 인 건물이 카드에 **438.85㎡** 로 찍혔다.
  //   백엔드(`normalizer.extract_areas`)는 처음부터 `[0-9][0-9,]*` 로 옳게 읽고
  //   있었다 — **같은 규칙의 두 구현이 갈라져 있었다**(BUGS #204 가 경계하는 그것).
  //   여기서 백엔드 정규식과 같은 모양으로 맞춘다.
  const areaRe = /([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:㎡|m2|m²)/g
  let total = 0
  let count = 0
  let m: RegExpExecArray | null
  while ((m = areaRe.exec(areaScope)) !== null) {
    total += Number(m[1].replace(/,/g, ''))
    count += 1
  }
  if (count === 0) return null
  const label = inside.startsWith('토지') ? '토지' : '건물'
  return { label, sqm: total }
}

// ---------------------------------------------------------------------------
// 카드에 찍을 면적은 **서버 값이 먼저다** (2026-08-31)
//
// ## 무엇이 문제였나 — 같은 규칙의 두 구현
//
// 면적을 뽑는 규칙이 두 곳에 있다.
//
//     백엔드  normalizer.extract_areas()  ->  auction_item.building_area / land_area
//             = 검색 **필터**가 쓰는 값 (migration 025, api/v1/search.py 의 WHERE)
//     프런트  parseArea(full_address)     ->  검색 카드에 **표시**하는 값
//
// 둘 다 같은 원문(`full_address` 끝 대괄호)에서 읽지만 구현이 다르다. 이 저장소는
// 이미 한 번 데였다 — 천단위 쉼표를 백엔드는 읽고 프런트는 못 읽어 3,005.35㎡ 가
// 카드에 5.35㎡ 로 찍혔다(`docs/BUGS.md` #240 / #204 가 경계하는 그것).
//
// 2026-08-31 전수 대조(1,876행): 라벨 불일치 0 / 값 불일치 0 이지만 **커버리지가
// 다르다.** 단위가 '평'인 7건은 백엔드가 ㎡ 로 환산해 저장하는데(`_PYEONG_TO_M2`)
// 프런트는 `㎡|m2|m²` 만 읽어 **아무것도 표시하지 않는다.**
//
//     [토지 전 1048평]   백엔드 land_area 3464.46   프런트 표시 없음
//
// 즉 면적 조건으로 걸러 놓고 그 카드에는 면적이 비어 있다. 필터와 표시가 서로
// 다른 사실을 말한다.
//
// ## 그래서 어떻게 하나
//
// **서버가 준 값이 있으면 그것을 쓴다.** 필터가 쓰는 값과 화면에 보이는 값이 같아진다.
// `parseArea()` 는 지우지 않고 **폴백으로만** 남긴다 — migration 025 이전 스키마나
// 아직 배포되지 않은 백엔드에서는 응답에 이 키가 없고(`api/v1/search.py` 의 `_area_of`
// 가 null 을 준다), 그때 카드가 갑자기 비면 오히려 퇴행이다.
//
// 폴백이 남아 있는 한 두 구현은 계속 공존한다. 그것을 없애는 것은 "면적 컬럼이
// 항상 채워져 있다"를 전제하는 일이고, 그 전제는 운영 DB 마이그레이션 상태에
// 달려 있어(승인 영역) 여기서 세우지 않는다.
// ---------------------------------------------------------------------------

/**
 * 서버가 준 면적 컬럼을 표시용 값으로 바꾼다. 둘 다 없으면 null.
 *
 * 한 물건은 건물면적 **또는** 토지면적 하나만 갖는다(실데이터에 둘 다 가진 행 0건).
 * 그래도 방어적으로 건물을 먼저 본다 — 집합건물의 대지권처럼 토지 값이 이 물건의
 * 몫이 아닌 경우가 있어, 건물 값이 있으면 그쪽이 이 물건을 더 정확히 말한다.
 */
export function serverArea(
  buildingArea: number | null | undefined,
  landArea: number | null | undefined,
): ParsedArea | null {
  // 0 은 "면적을 모른다"가 아니라 "0㎡"다. 그러나 실데이터에 0 은 없고, 있다면
  // 그것은 파싱 사고다 — 표시하지 않는 편이 틀린 숫자를 보여주는 것보다 낫다.
  if (typeof buildingArea === 'number' && buildingArea > 0) {
    return { label: '건물', sqm: buildingArea }
  }
  if (typeof landArea === 'number' && landArea > 0) {
    return { label: '토지', sqm: landArea }
  }
  return null
}

/** 카드에 표시할 면적. 서버 값이 있으면 그것을, 없으면 주소 원문에서 읽는다. */
export function displayArea(item: {
  building_area?: number | null
  land_area?: number | null
  full_address: string | null
}): ParsedArea | null {
  return serverArea(item.building_area, item.land_area) ?? parseArea(item.full_address)
}

/** "건물 84.50㎡ (25.56평)" */
export function formatArea(area: ParsedArea): string {
  const pyeong = (area.sqm / SQM_PER_PYEONG).toFixed(2)
  return `${area.label} ${area.sqm.toFixed(2)}㎡ (${pyeong}평)`
}


// ---------------------------------------------------------------------------
// 매각기일 D-day — **"오늘"을 한국 시각으로 고정한다** (2026-08-31)
//
// 원래 `src/app/search/ResultList.tsx`(JSX) 안에 있었고 상세 페이지가 그 컴포넌트
// 파일에서 함수를 꺼내 쓰고 있었다. 옮긴 이유는 `parseArea` 때와 같다 —
//   1. `.tsx` 는 Node 의 타입 스트리핑으로 import 할 수 없어 **동작 테스트를 붙일 수
//      없었다.** 검색 카드와 상세 배지에 매번 찍히는 값인데 계약이 고정돼 있지 않았다.
//   2. 화면(page)이 다른 라우트의 컴포넌트 파일에서 유틸을 가져오는 것은 계층 우회다.
//
// ## 무엇을 고쳤나 — "오늘"이 두 곳에서 따로 계산되고 있었다
//
//     백엔드  api/v1/search.py:  `auction_date >= date.today()`   서버 로컬 시각
//     프런트  formatDday():      `new Date()` 로 로컬 자정         **보는 사람의 시계**
//
// 이 저장소가 선언한 시각 기준은 **한국 로컬 시각**이다(`storage/database.py` 의
// `_NOW_LOCAL` 주석: "한국(UTC+9)에서 실측한 결과가 이렇다"). 서버는 한국에서 도는데
// 브라우저는 아무 데서나 돈다. 그래서 UTC-05:00 브라우저에서는 자정 부근에
// **목록에는 아직 남아 있는 물건이 배지에서는 "1일 경과"** 로 보였다. 반대로
// UTC+13:00 에서는 하루 일찍 D-Day 가 떴다. 오류도 로그도 없이 날짜만 어긋난다.
//
// `DISPLAY_LOCALE` 과 같은 판단이다 — 새 정책을 만드는 것이 아니라 **이미 선언된
// 기준(한국 시각)** 을 보는 쪽에도 적용한다. 한국에서 보는 사용자의 화면은 한 글자도
// 바뀌지 않는다.
//
// ★ 백엔드는 그대로 둔다. `date.today()` 는 "서버 로컬 시각을 쓴다"는 이 저장소의
//   명시적 규약이고, 서버가 어느 시간대에서 도는가는 배포 결정(승인 영역)이다.
//   여기서 맞추는 것은 **클라이언트가 서버와 같은 날짜를 보게 하는 것**뿐이다.
export const DISPLAY_TIME_ZONE = 'Asia/Seoul'

/** 주어진 시각의 한국 날짜(YYYY-MM-DD). 인자가 없으면 지금. */
export function todayInDisplayZone(now: Date = new Date()): string {
  // en-CA 로케일이 YYYY-MM-DD 를 준다 — 직접 조합하는 것보다 자릿수 실수가 없다.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: DISPLAY_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now)
}

/** `YYYY-MM-DD` 를 UTC 자정 밀리초로. 형식이 다르면 null. */
function parseYmdToUtcMs(ymd: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd)
  if (!m) return null
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(ms) ? null : ms
}

/** `YYYY-MM-DD` 두 개 사이의 일수. 시간대·서머타임의 영향을 받지 않는다. */
function daysBetween(fromYmd: string, toYmd: string): number | null {
  const a = parseYmdToUtcMs(fromYmd)
  const b = parseYmdToUtcMs(toYmd)
  if (a === null || b === null) return null
  return Math.round((b - a) / 86400000)
}

/**
 * `YYYY-MM-DD` 에서 `days` 일 뒤의 `YYYY-MM-DD`. 형식이 다르면 null.
 *
 * 날짜만 다룬다 — 시각을 끼우지 않으므로 시간대도 서머타임도 개입할 수 없다.
 *
 * ## 왜 필요한가 — `new Date()` + `toISOString()` 은 한국에서 **아침마다** 틀렸다
 *
 * 검색폼의 매각기일 퀵버튼(당일/+7/+14)이 `new Date().toISOString().slice(0, 10)`
 * 으로 "오늘"을 만들고 있었다. `toISOString()` 은 **UTC** 로 바꾸므로
 * KST 09:00 이전에는 하루 전 날짜가 나온다(2026-09-01 08:33 KST 실측:
 * `2026-08-31`). 그래서 오전에 "당일"을 누르면 **어제 날짜로 검색**돼
 * 오늘 매각되는 물건이 통째로 안 나왔고, "+7" 은 8일 범위가 됐다
 * (시작은 UTC 로 밀리고 끝은 +7일 뒤라 경계를 다시 넘어간다).
 *
 * `formatDday()` 와 **같은 기준**을 쓴다 — 새 정책을 만드는 것이 아니라
 * 이미 선언된 `DISPLAY_TIME_ZONE` 을 입력쪽에도 적용하는 것이다.
 */
export function ymdPlusDays(ymd: string, days: number): string | null {
  const base = parseYmdToUtcMs(ymd)
  if (base === null || !Number.isFinite(days)) return null
  const d = new Date(base + Math.trunc(days) * 86400000)
  // `toISOString().slice(0, 10)` 이 아니라 UTC 자릿수를 직접 조립한다.
  // 여기서의 `d` 는 UTC 자정이라 둘이 같은 값을 주지만, 자르는 모양을
  // 한 군데라도 남겨 두면 `tests/source-contract.test.mjs` 의 금지 규칙에
  // **예외 목록**이 필요해진다. 이 저장소는 예외 목록이 곧 두 번째 규약이
  // 된다는 것을 이미 한 번 치렀다(Sprint 118). 그래서 규칙을 절대로 둔다.
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}

/**
 * 매각기일까지 남은 일수를 "오늘"(한국 시각) 기준으로 표시한다.
 *
 * 절대 날짜(`auction_date`)는 그대로 유지하고 이 값은 **보조 표시**로만 쓴다.
 * `now`는 테스트에서 시각을 고정하기 위한 인자다(백엔드가 `at: datetime = None`을
 * 두는 것과 같은 이유). 제품 코드는 넘기지 않는다.
 */
export function formatDday(auctionDate: string | null, now: Date = new Date()): string | null {
  if (!auctionDate) return null
  const diffDays = daysBetween(todayInDisplayZone(now), auctionDate)
  if (diffDays === null) return null
  if (diffDays > 0) return `입찰 ${diffDays}일전`
  if (diffDays === 0) return 'D-Day'
  return `입찰 ${Math.abs(diffDays)}일 경과`
}
