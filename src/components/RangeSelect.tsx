'use client'

export type RangeOption = { value: string; label: string }

type RangeSelectProps = {
  label: string
  minValue: string
  maxValue: string
  onMinChange: (value: string) => void
  onMaxChange: (value: string) => void
  options: RangeOption[]
  placeholder: string
  selectClassName: string
  labelClassName: string
}

// PriceRangeSelect(P1, 가격 프리셋 전용 — 수정하지 않음)와 동일한 "레이블 + 최소/최대 select"
// 구조를, 값 체계가 다른 필드(최저가율/유찰횟수 등)에서도 재사용하기 위한 범용 컴포넌트.
// SearchForm.tsx에 두 번 중복돼 있던 인라인 select 쌍을 이 컴포넌트로 통일했다.
export default function RangeSelect({
  label,
  minValue,
  maxValue,
  onMinChange,
  onMaxChange,
  options,
  placeholder,
  selectClassName,
  labelClassName,
}: RangeSelectProps) {
  return (
    <div>
      <span className={labelClassName}>{label}</span>
      <div className="grid grid-cols-2 gap-2">
        {/* aria-label 은 **픽셀을 바꾸지 않는다** (2026-08-19 Sprint 222).
            `<span>` 으로 그린 레이블은 시각적으로만 붙어 있고 select 와 프로그래밍적으로
            연결돼 있지 않다 - 스크린리더는 "콤보박스"라고만 읽는다. 최소/최대가 나란히
            둘이라 어느 쪽인지도 알 수 없다. 보이는 레이블을 그대로 이름으로 준다. */}
        <select
          value={minValue}
          onChange={(e) => onMinChange(e.target.value)}
          aria-label={`${label} 최소`}
          className={selectClassName}
        >
          <option value="">최소 {placeholder}</option>
          {options.map((opt) => (
            <option
              key={`min-${opt.value}`}
              value={opt.value}
              // "선택 안함"(빈 문자열)은 항상 선택 가능. 그 외에는 최대값보다 큰 옵션을 막아
              // 최소 > 최대 조합 자체가 만들어지지 않게 한다.
              disabled={maxValue !== '' && Number(opt.value) > Number(maxValue)}
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
          <option value="">최대 {placeholder}</option>
          {options.map((opt) => (
            <option
              key={`max-${opt.value}`}
              value={opt.value}
              disabled={minValue !== '' && Number(opt.value) < Number(minValue)}
            >
              최대 {opt.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
