'use client'

type CategoryGroup = {
  value: string
  label: string
  items: string[]
}

// Tank Auction 검색폼(search/reference/01_SEARCH_FORM.html)의 물건종류 체크박스 트리
// (chkGrpCtgr = 그룹, chkEaCtgr = 세부항목)에 실제로 존재하는 그룹/항목명을 그대로 옮겼다.
// HTML 전수 파싱(chkGrpCtgr 5개 그룹 x chkEaCtgr 69개 세부항목) 결과를 그대로 반영 — 축약 없음.
// 다중 선택 시 SearchForm.tsx가 콤마로 join해 property_type으로 보내고,
// Backend(api/v1/search.py)가 OR 조건(LIKE)으로 검색한다.
export const PROPERTY_CATEGORY_GROUPS: CategoryGroup[] = [
  {
    value: '10',
    label: '주거용',
    items: ['아파트', '연립주택', '다세대주택', '오피스텔(주거)', '단독주택', '다가구주택', '도시형생활주택', '기숙사', '상가주택'],
  },
  {
    value: '20',
    label: '상업 및 산업용',
    items: [
      '근린생활시설', '오피스텔(상업)', '근린상가', '숙박시설', '숙박(콘도등)', '목욕탕', '업무시설',
      '노유자시설', '문화및집회시설', '종교시설', '의료시설', '교육연구시설', '묘지관련시설', '기타시설',
      '공장', '지식산업센터', '창고시설', '위험물저장및처리', '자동차관련', '동물및식물관련', '분뇨및쓰레기처리',
    ],
  },
  {
    value: '30',
    label: '토지',
    items: [
      '전', '답', '과수원', '임야', '대지', '잡종지', '도로', '주차장', '공원', '유원지', '사적지', '묘지',
      '목장용지', '공장용지', '학교용지', '주유소용지', '창고용지', '철도용지', '수도용지', '체육용지',
      '종교용지', '제방', '하천', '구거', '광천지', '염전', '유지', '양어장',
    ],
  },
  {
    value: '40',
    label: '차량 및 중장비',
    items: ['승용차', '승합차', '버스', '화물차', '기타차량', '덤프트럭', '기타중기'],
  },
  { value: '50', label: '기타', items: ['선박', '어업권', '광업권', '기타'] },
]

type PropertyTypeTreeProps = {
  selected: string[]
  onChange: (selected: string[]) => void
}

export default function PropertyTypeTree({ selected, onChange }: PropertyTypeTreeProps) {
  function toggleItem(item: string) {
    onChange(
      selected.includes(item)
        ? selected.filter((v) => v !== item)
        : [...selected, item]
    )
  }

  function toggleGroup(group: CategoryGroup) {
    const allSelected = group.items.every((item) => selected.includes(item))
    if (allSelected) {
      onChange(selected.filter((v) => !group.items.includes(v)))
    } else {
      onChange(Array.from(new Set([...selected, ...group.items])))
    }
  }

  return (
    <div className="space-y-2">
      {PROPERTY_CATEGORY_GROUPS.map((group) => {
        const allSelected = group.items.every((item) => selected.includes(item))
        return (
          <div key={group.value} className="rounded-xl border border-gray-100 p-2">
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
              <input type="checkbox" checked={allSelected} onChange={() => toggleGroup(group)} />
              {group.label}
            </label>
            <div className="grid grid-cols-2 gap-y-1 pl-4">
              {group.items.map((item) => (
                <label key={item} className="flex items-center gap-1.5 text-xs text-gray-500">
                  <input
                    type="checkbox"
                    checked={selected.includes(item)}
                    onChange={() => toggleItem(item)}
                  />
                  {item}
                </label>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
