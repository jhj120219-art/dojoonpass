'use client'

import { useRouter, usePathname } from 'next/navigation'
import { useState } from 'react'

const SIDO_LIST = [
  '서울특별시',
  '부산광역시',
  '대구광역시',
  '인천광역시',
  '광주광역시',
  '대전광역시',
  '울산광역시',
  '세종특별자치시',
  '경기도',
  '강원특별자치도',
  '충청북도',
  '충청남도',
  '전북특별자치도',
  '전라남도',
  '경상북도',
  '경상남도',
  '제주특별자치도',
]

const SIGUNGU_MAP: Record<string, string[]> = {
  서울특별시: [
    '강남구', '강동구', '강북구', '강서구', '관악구', '광진구', '구로구',
    '금천구', '노원구', '도봉구', '동대문구', '동작구', '마포구', '서대문구',
    '서초구', '성동구', '성북구', '송파구', '양천구', '영등포구', '용산구',
    '은평구', '종로구', '중구', '중랑구',
  ],
  부산광역시: [
    '해운대구', '수영구', '동래구', '부산진구', '남구', '북구', '사상구',
    '사하구', '연제구', '영도구', '중구', '강서구', '금정구', '기장군',
  ],
  경기도: [
    '수원시', '성남시', '고양시', '용인시', '부천시', '안산시', '안양시',
    '남양주시', '화성시', '평택시', '의정부시', '시흥시', '파주시', '김포시',
  ],
}

const PRICE_OPTIONS = [
  { label: '제한없음', value: 0 },
  { label: '1억', value: 100000000 },
  { label: '2억', value: 200000000 },
  { label: '3억', value: 300000000 },
  { label: '5억', value: 500000000 },
  { label: '10억', value: 1000000000 },
  { label: '20억', value: 2000000000 },
  { label: '30억', value: 3000000000 },
  { label: '50억', value: 5000000000 },
  { label: '100억', value: 10000000000 },
]

type SearchFiltersProps = {
  initialSido?: string
  initialSigungu?: string
  initialMinPrice?: number
  initialMaxPrice?: number
}

export default function SearchFilters({
  initialSido = '',
  initialSigungu = '',
  initialMinPrice = 0,
  initialMaxPrice = 0,
}: SearchFiltersProps) {
  const router = useRouter()
  const pathname = usePathname()

  const [sido, setSido] = useState(initialSido)
  const [sigungu, setSigungu] = useState(initialSigungu)
  const [minPrice, setMinPrice] = useState(initialMinPrice)
  const [maxPrice, setMaxPrice] = useState(initialMaxPrice)

  const sigunguOptions = sido ? SIGUNGU_MAP[sido] ?? [] : []

  function handleSidoChange(value: string) {
    setSido(value)
    setSigungu('')
  }

  function handleSearch() {
    const params = new URLSearchParams()
    if (sido) params.set('sido', sido)
    if (sigungu) params.set('sigungu', sigungu)
    if (minPrice > 0) params.set('minPrice', String(minPrice))
    if (maxPrice > 0) params.set('maxPrice', String(maxPrice))

    const query = params.toString()
    router.push(query ? `${pathname}?${query}` : pathname)
  }

  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 mb-3 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <select
          value={sido}
          onChange={(e) => handleSidoChange(e.target.value)}
          className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
        >
          <option value="">시/도 전체</option>
          {SIDO_LIST.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>

        <select
          value={sigungu}
          onChange={(e) => setSigungu(e.target.value)}
          disabled={!sido}
          className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:opacity-50"
        >
          <option value="">시/군/구 전체</option>
          {sigunguOptions.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <select
          value={minPrice}
          onChange={(e) => setMinPrice(Number(e.target.value))}
          className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
        >
          {PRICE_OPTIONS.map((opt) => (
            <option key={`min-${opt.value}`} value={opt.value}>
              최소 {opt.label}
            </option>
          ))}
        </select>

        <select
          value={maxPrice}
          onChange={(e) => setMaxPrice(Number(e.target.value))}
          className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
        >
          {PRICE_OPTIONS.map((opt) => (
            <option key={`max-${opt.value}`} value={opt.value}>
              최대 {opt.label}
            </option>
          ))}
        </select>
      </div>

      <button
        type="button"
        onClick={handleSearch}
        className="w-full rounded-xl bg-blue-500 py-2.5 text-sm font-medium text-white active:bg-blue-600 transition-colors"
      >
        검색
      </button>
    </div>
  )
}
