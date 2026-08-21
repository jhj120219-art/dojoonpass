// 공용 표시 포맷 함수. 여러 화면(검색결과/즐겨찾기/최근조회)에 동일하게 복사돼 있던
// formatPrice()를 여기로 모았다 — 동작은 기존 그대로, 정의 위치만 옮김(회귀 없음).
export function formatPrice(price: number) {
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
export function formatWon(amount: number) {
  return amount.toLocaleString() + '원'
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
  const areaRe = /([0-9]+(?:\.[0-9]+)?)\s*(?:㎡|m2|m²)/g
  let total = 0
  let count = 0
  let m: RegExpExecArray | null
  while ((m = areaRe.exec(areaScope)) !== null) {
    total += Number(m[1])
    count += 1
  }
  if (count === 0) return null
  const label = inside.startsWith('토지') ? '토지' : '건물'
  return { label, sqm: total }
}

/** "건물 84.50㎡ (25.56평)" */
export function formatArea(area: ParsedArea): string {
  const pyeong = (area.sqm / SQM_PER_PYEONG).toFixed(2)
  return `${area.label} ${area.sqm.toFixed(2)}㎡ (${pyeong}평)`
}
