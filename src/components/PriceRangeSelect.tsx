'use client'

export type PriceOption = { label: string; value: number }

// Tank Auction 검색폼(search/reference/01_SEARCH_FORM.html)의 apslAmtBgn/End(감정가),
// minbAmtBgn/End(최저입찰가) select 옵션과 값이 완전히 동일하다(두 필드 옵션 목록이 서로 동일함을
// HTML에서 확인). "- 선택 -"만 DojoonPass의 기존 0-sentinel 표기("제한없음")로 맞췄다.
export const PRICE_OPTIONS: PriceOption[] = [
  { label: '제한없음', value: 0 },
  { label: '1백만', value: 1000000 },
  { label: '2백만', value: 2000000 },
  { label: '3백만', value: 3000000 },
  { label: '4백만', value: 4000000 },
  { label: '5백만', value: 5000000 },
  { label: '6백만', value: 6000000 },
  { label: '7백만', value: 7000000 },
  { label: '8백만', value: 8000000 },
  { label: '9백만', value: 9000000 },
  { label: '1천만', value: 10000000 },
  { label: '2천만', value: 20000000 },
  { label: '3천만', value: 30000000 },
  { label: '4천만', value: 40000000 },
  { label: '5천만', value: 50000000 },
  { label: '6천만', value: 60000000 },
  { label: '7천만', value: 70000000 },
  { label: '8천만', value: 80000000 },
  { label: '9천만', value: 90000000 },
  { label: '1억', value: 100000000 },
  { label: '1억 5천만', value: 150000000 },
  { label: '2억', value: 200000000 },
  { label: '2억 5천만', value: 250000000 },
  { label: '3억', value: 300000000 },
  { label: '3억 5천만', value: 350000000 },
  { label: '4억', value: 400000000 },
  { label: '4억 5천만', value: 450000000 },
  { label: '5억', value: 500000000 },
  { label: '6억', value: 600000000 },
  { label: '7억', value: 700000000 },
  { label: '8억', value: 800000000 },
  { label: '9억', value: 900000000 },
  { label: '10억', value: 1000000000 },
  { label: '11억', value: 1100000000 },
  { label: '12억', value: 1200000000 },
  { label: '13억', value: 1300000000 },
  { label: '14억', value: 1400000000 },
  { label: '15억', value: 1500000000 },
  { label: '16억', value: 1600000000 },
  { label: '17억', value: 1700000000 },
  { label: '18억', value: 1800000000 },
  { label: '19억', value: 1900000000 },
  { label: '20억', value: 2000000000 },
  { label: '30억', value: 3000000000 },
  { label: '40억', value: 4000000000 },
  { label: '50억', value: 5000000000 },
  { label: '60억', value: 6000000000 },
  { label: '70억', value: 7000000000 },
  { label: '80억', value: 8000000000 },
  { label: '90억', value: 9000000000 },
  { label: '100억', value: 10000000000 },
  { label: '200억', value: 20000000000 },
  { label: '300억', value: 30000000000 },
  { label: '400억', value: 40000000000 },
  { label: '500억', value: 50000000000 },
  { label: '600억', value: 60000000000 },
  { label: '700억', value: 70000000000 },
  { label: '800억', value: 80000000000 },
  { label: '900억', value: 90000000000 },
  { label: '1000억', value: 100000000000 },
]

type PriceRangeSelectProps = {
  label: string
  minValue: string
  maxValue: string
  onMinChange: (value: string) => void
  onMaxChange: (value: string) => void
  selectClassName: string
  labelClassName: string
}

// 값 0은 "제한없음"(필터 미적용) sentinel이다. 호출 측에서 쿼리 생성 시
// Number(value) > 0으로 판정해야 한다 (빈 문자열이 아니라 "0"이 기본값이므로).
export default function PriceRangeSelect({
  label,
  minValue,
  maxValue,
  onMinChange,
  onMaxChange,
  selectClassName,
  labelClassName,
}: PriceRangeSelectProps) {
  const maxNum = Number(maxValue)
  const minNum = Number(minValue)

  return (
    <div>
      <span className={labelClassName}>{label}</span>
      <div className="grid grid-cols-2 gap-2">
        {/* aria-label - 보이는 `<span>` 레이블은 select 와 프로그래밍적으로 연결돼
            있지 않다. 최소/최대가 나란히 둘이라 스크린리더로는 구분되지 않는다.
            픽셀은 바뀌지 않는다 (2026-08-19 Sprint 222). */}
        <select
          value={minValue}
          onChange={(e) => onMinChange(e.target.value)}
          aria-label={`${label} 최소`}
          className={selectClassName}
        >
          {PRICE_OPTIONS.map((opt) => (
            <option
              key={`min-${opt.value}`}
              value={opt.value}
              // "제한없음"(0)은 항상 선택 가능. 그 외에는 최대값보다 큰 옵션을 막아
              // 최소 > 최대 조합 자체가 만들어지지 않게 한다.
              disabled={opt.value !== 0 && maxNum > 0 && opt.value > maxNum}
            >
              최소 {opt.label}
            </option>
          ))}
        </select>
        <select
          value={maxValue}
          onChange={(e) => onMaxChange(e.target.value)}
          aria-label={`${label} 최대`}
          className={selectClassName}
        >
          {PRICE_OPTIONS.map((opt) => (
            <option
              key={`max-${opt.value}`}
              value={opt.value}
              disabled={opt.value !== 0 && minNum > 0 && opt.value < minNum}
            >
              최대 {opt.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
