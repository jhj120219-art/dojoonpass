// 공용 표시 포맷 함수. 여러 화면(검색결과/즐겨찾기/최근조회)에 동일하게 복사돼 있던
// formatPrice()를 여기로 모았다 — 동작은 기존 그대로, 정의 위치만 옮김(회귀 없음).
export function formatPrice(price: number) {
  if (!price) return '-'
  if (price >= 100000000) return (price / 100000000).toFixed(1) + '억'
  if (price >= 10000) return Math.round(price / 10000) + '만'
  return String(price)
}
