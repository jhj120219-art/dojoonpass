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
