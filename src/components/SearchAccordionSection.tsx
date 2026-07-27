'use client'

import { useState, type ReactNode } from 'react'

type SearchAccordionSectionProps = {
  title: string
  defaultOpen?: boolean
  children: ReactNode
}

// Tank Auction 검색폼의 toggleBtn/toggleContent 구조를 참고한 접기/펼치기 섹션.
export default function SearchAccordionSection({
  title,
  defaultOpen = true,
  children,
}: SearchAccordionSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border-b border-gray-100 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between py-3 text-sm font-semibold text-gray-800"
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
