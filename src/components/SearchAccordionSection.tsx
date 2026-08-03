'use client'

import { useState, type ReactNode } from 'react'

type SearchAccordionSectionProps = {
  title: string
  defaultOpen?: boolean
  // 아직 백엔드 연동이 안 돼 항상 "준비 중입니다"만 보여주는 섹션(면적조건/특수조건)임을
  // 제목 색상만으로 표시한다 — 실제 동작하는 섹션과 한눈에 구분되도록.
  muted?: boolean
  children: ReactNode
}

// Tank Auction 검색폼의 toggleBtn/toggleContent 구조를 참고한 접기/펼치기 섹션.
export default function SearchAccordionSection({
  title,
  defaultOpen = true,
  muted = false,
  children,
}: SearchAccordionSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border-b border-gray-100 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={`w-full flex items-center justify-between py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200 ${muted ? 'text-gray-400' : 'text-gray-600'}`}
      >
        {title}
        <span
          className={`text-gray-400 text-xs transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        >
          ▼
        </span>
      </button>
      {open && <div className="pb-4 space-y-3">{children}</div>}
    </div>
  )
}
