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
